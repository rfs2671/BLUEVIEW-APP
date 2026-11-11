"""`dob_logs.job_number` IS WRITTEN, for every permit dataset the sync polls.

The reads-without-writers sweep cannot see the writer - it is
server._extract_permit_fields, which RETURNS a dict the sync merges into each
permit row - so its baseline lists ("dob_logs", "job_number"). That entry is
allowed only with proof (Roy, 2026-11-11). This is the proof:

  1. Every permit endpoint in server._query_dob_apis is covered here: a new
     permit dataset added there fails this file until it is added below.
  2. For each one, a record in that dataset's own shape goes through the REAL
     path - the HTTP fetch (faked), _query_dob_apis' dedup, and
     run_dob_sync_for_project's insert - and the stored row carries the job
     number, in DOB NOW (B00736381-I1) and BIS (121234567) formats.
  3. The brief never queries dob_logs by job_number or work_type: its renewal
     and current-job rules run in memory over the rows it already read by
     project_id, so no (job_number, work_type) index is needed for them.

What production rows hold is counted by scripts/permit_job_numbers.py.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
import permit_job_numbers as pjn  # noqa: E402
from tests.test_dob_status_refresh import (  # noqa: E402
    BIN, _FakeClient, _project, _Resp, _run, _Sync,
)

SRC = (Path(server.__file__)).read_text(encoding="utf-8")

#: One record per permit dataset, in that dataset's own field names.
SAMPLES = {
    # DOB NOW: Build - Approved Permits
    "rbx6-tga4": {"job_filing_number": "B00736381-I1", "work_type": "General Construction",
                  "permit_status": "Permit Issued", "issued_date": "2026-01-05T00:00:00.000",
                  "expired_date": "2027-01-05T00:00:00.000", "bin": BIN},
    # DOB NOW: Electrical Permit Applications
    "dm9a-ab7w": {"job_filing_number": "B00988811-I1", "filing_status": "Permit Issued",
                  "permit_issued_date": "2026-02-01T00:00:00.000", "bin": BIN},
    # BIS: DOB Permit Issuance (legacy)
    "ipu4-2q9a": {"job__": "121234567", "work_type": "PL", "permit_status": "ISSUED",
                  "permit_sequence__": "02", "expiration_date": "10/01/2027",
                  "issuance_date": "10/01/2026", "bin__": BIN},
}
EXPECTED = {"rbx6-tga4": "B00736381-I1", "dm9a-ab7w": "B00988811-I1",
            "ipu4-2q9a": "121234567"}


_ENDPOINT = re.compile(
    r'resource/([a-z0-9]{4}-[a-z0-9]{4})\.json",\s*"params":\s*\{.*?\},\s*'
    r'"record_type":\s*"(\w+)",\s*"id_field":\s*"(\w+)"', re.S)


def _endpoints_in_server():
    """[(dataset slug, record_type, id_field)] of every endpoint _query_dob_apis
    polls, read from its source."""
    body = SRC[SRC.index("async def _query_dob_apis"):]
    return _ENDPOINT.findall(body[:body.index("\nasync def ", 10)])


def _permit_endpoints_in_server():
    return {(slug, f) for slug, rt, f in _endpoints_in_server() if rt == "permit"}


class EveryPermitDatasetIsCovered(unittest.TestCase):

    def test_the_server_polls_exactly_these_permit_datasets(self):
        self.assertGreater(len(_endpoints_in_server()), 15)    # the reader reads them all
        found = _permit_endpoints_in_server()
        self.assertEqual({slug for slug, _f in found}, set(SAMPLES),
                         "a permit dataset was added or removed in _query_dob_apis: "
                         "add its record shape to SAMPLES")
        for slug, id_field in found:
            self.assertIn(id_field, SAMPLES[slug], (slug, id_field))


class TheExtractorWritesIt(unittest.TestCase):

    def test_each_dataset_shape(self):
        for slug, rec in SAMPLES.items():
            self.assertEqual(server._extract_permit_fields(dict(rec))["job_number"],
                             EXPECTED[slug], slug)

    def test_dob_now_and_bis_formats(self):
        for jn in ("B00736381-I1", "B23173802-S5", "M01234567-I2", "Q00012345-P1",
                   "X00012345", "121234567", "320045678"):
            for key in ("job__", "job_filing_number", "job_number"):
                self.assertEqual(server._extract_permit_fields({key: jn})["job_number"], jn,
                                 (key, jn))


class TheSyncStoresIt(unittest.TestCase):
    """Fetch -> _query_dob_apis -> run_dob_sync_for_project -> dob_logs."""

    def test_every_permit_dataset_row_carries_its_job_number(self):
        def script(url, params):
            for slug, rec in SAMPLES.items():
                if f"/{slug}.json" in url:
                    return _Resp(200, [dict(rec)])
            return _Resp(200, [])

        s = _Sync()
        _FakeClient.calls = []
        _FakeClient.script = staticmethod(script)
        with patch.object(server, "db", s.db), \
                patch.object(server, "ServerHttpClient", _FakeClient), \
                patch.object(server, "_send_critical_dob_alert_throttled", s.alert):
            _run(server.run_dob_sync_for_project(_project()))
        rows = s.rows(rt="permit")
        by_source = {r.get("dataset"): r for r in rows}
        self.assertEqual(set(by_source), set(SAMPLES), [r.get("dataset") for r in rows])
        for slug, row in by_source.items():
            self.assertEqual(row.get("job_number"), EXPECTED[slug], slug)
        self.assertFalse([r for r in rows if pjn._missing(r.get("job_number"))])


class TheBriefNeverQueriesByIt(unittest.TestCase):
    """(3) No (job_number, work_type) index: the brief reads dob_logs by
    project_id; the renewal and current-job rules are in memory."""

    def test_brief_job_dob_logs_filters(self):
        seen = []

        class _Spy:
            def __init__(self, inner):
                self.inner = inner

            def find(self, flt=None, *a, **k):
                seen.append(dict(flt or {}))
                return self.inner.find(flt, *a, **k)

            def __getattr__(self, n):
                return getattr(self.inner, n)

        s = _Sync()
        db = s.db
        spy = _Spy(db.dob_logs)
        with patch.object(server, "db", db), patch.object(db, "dob_logs", spy, create=True):
            now = datetime(2026, 10, 13, 12, 5, tzinfo=timezone.utc)
            _run(server._brief_job(_project(), "c1", now - timedelta(days=1), now, None, False))
        self.assertTrue(seen)
        for flt in seen:
            self.assertEqual(set(flt) - {"project_id", "record_type", "is_deleted"}, set(), flt)


class TheCountScript(unittest.TestCase):

    def test_shapes_and_recovery_never_guess(self):
        self.assertEqual(pjn.recover_job_number("permit:B00736381-I1"), "B00736381-I1")
        self.assertEqual(pjn.recover_job_number("121234567:PL"), "121234567")
        self.assertIsNone(pjn.recover_job_number("permit:B00736381:General Construction"))
        self.assertIsNone(pjn.recover_job_number("viol:123"))
        self.assertIsNone(pjn.recover_job_number(None))
        self.assertEqual(pjn.shape("permit:B23173802-S5"), "permit:<job>")
        self.assertEqual(pjn.shape("permit:B001:GC"), "permit:<other>")
        self.assertEqual(pjn.shape("121234567:PL"), "<job>:<work>")

    def test_tally(self):
        rows = [
            {"dataset": "rbx6-tga4", "raw_dob_id": "permit:B00736381-I1", "job_number": "B00736381-I1"},
            {"dataset": None, "raw_dob_id": "permit:B00736382-I1", "job_number": None},
            {"dataset": None, "raw_dob_id": "permit:B1:GC", "job_number": ""},
            {"dataset": "ipu4-2q9a", "raw_dob_id": "121234567:PL", "job_number": "b121"},
        ]
        t = pjn.tally(rows)
        self.assertEqual(t[("unstamped", "permit:<job>")]["recoverable"], 1)
        self.assertEqual(t[("unstamped", "permit:<other>")]["missing"], 1)
        self.assertEqual(t[("unstamped", "permit:<other>")]["recoverable"], 0)
        self.assertEqual(t[("ipu4-2q9a", "<job>:<work>")]["not_upper"], 1)
        text = pjn.report(t)
        self.assertNotIn("B00736381", text)                       # shapes, never values
        self.assertIn("ALL", text)


if __name__ == "__main__":
    unittest.main()
