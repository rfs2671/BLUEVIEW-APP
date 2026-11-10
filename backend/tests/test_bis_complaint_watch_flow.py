"""The BIS complaint watch, end to end over the real 546 Saratoga BIS pages.

server.run_bis_complaint_watch_for_project with a fake Mongo and an HTTP stub
that serves tests/fixtures/bis_complaints/ (fetched 2026-11-10 19:48 UTC). The
project is seeded with what the Open Data scan had actually stored for 546 that
day (history, none of the two new complaints).

Pins: shadow writes no record and sends nothing; live stores the two new
complaints once and emails each once; a second pass changes nothing; the
Open Data row that arrives the next day refreshes the same row; a BIS outage
is recorded as a failure, never as "no complaints".
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402
from lib import bis_complaints as bis  # noqa: E402
from lib import complaint_watch as cw  # noqa: E402
from tests.async_fake_mongo import AsyncFakeCollection, AsyncFakeDB, matches  # noqa: E402

FIX = _HERE / "fixtures" / "bis_complaints"
NOW = datetime(2026, 11, 10, 19, 48, tzinfo=timezone.utc)
PROJECT = {"_id": "p546", "company_id": "co_blueview", "name": "546 Saratoga Ave", "nyc_bin": "3255205",
           "track_dob_status": True}


class _Coll(AsyncFakeCollection):
    async def insert_one(self, doc, **kw):
        if "_id" in doc and any(d.get("_id") == doc["_id"] for d in self.docs):
            raise RuntimeError("E11000 duplicate key")
        return await super().insert_one(doc, **kw)

    async def distinct(self, key, flt=None):
        return sorted({d.get(key) for d in self.docs if matches(d, flt) and d.get(key) is not None})

    async def update_one(self, flt, update, upsert=False, **kw):
        hit = [d for d in self.docs if matches(d, flt)]
        if not hit and upsert:
            self.docs.append({k: v for k, v in flt.items() if not isinstance(v, dict)})
        for d in [x for x in self.docs if matches(x, flt)][:1]:
            for k, spec in (update.get("$addToSet") or {}).items():
                cur, parts = d, k.split(".")
                for p in parts[:-1]:
                    cur = cur.setdefault(p, {})
                lst = cur.setdefault(parts[-1], [])
                for v in (spec.get("$each") if isinstance(spec, dict) else [spec]):
                    if v not in lst:
                        lst.append(v)
        return await super().update_one(flt, {k: v for k, v in update.items() if k != "$addToSet"})


class _DB(AsyncFakeDB):
    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = _Coll(name)
        return self._c[name]


class _Resp:
    def __init__(self, code, text):
        self.status_code, self.text = code, text


class _BIS:
    """Serves the real pages by URL; `down` makes every call a 503."""
    def __init__(self, down=False):
        self.down, self.urls = down, []

    async def get(self, url, **kw):
        self.urls.append(url)
        if self.down:
            return _Resp(503, "Service Unavailable")
        if "PropertyProfileOverviewServlet" in url and "bin=3255205" in url:
            return _Resp(200, (FIX / "property_3255205.html").read_text(encoding="latin-1"))
        if "ComplaintsByAddressServlet" in url and "allbin=3255205" in url:
            return _Resp(200, (FIX / "list_3255205.html").read_text(encoding="latin-1"))
        if "ComplaintsByAddressServlet" in url and "allbin=3423445" in url:
            return _Resp(200, (FIX / "list_3423445.html").read_text(encoding="latin-1"))
        if "OverviewForComplaintServlet" in url:
            cn = url.split("complaintno=")[1].split("&")[0]
            f = FIX / f"detail_{cn}.html"
            if f.exists():
                return _Resp(200, f.read_text(encoding="latin-1"))
            return _Resp(200, "Overview for Complaint #: = *** COMPLAINT NUMBER NOT FOUND ****")
        return _Resp(404, "")


def _seed() -> _DB:
    db = _DB()
    db.projects.docs.append(copy.deepcopy(PROJECT))
    # What the Open Data scan had stored for 546 on 2026-11-10 (by number/status).
    for cn, st, disp, day in (("3A70078", "CLOSED", "A8", "2026-07-07"), ("3A70077", "CLOSED", "L1", "2026-07-07"),
                              ("3A68500", "CLOSED", "A8", "2026-06-25"), ("3A48317", "CLOSED", "I2", "2026-02-11"),
                              ("3A35232", "CLOSED", "L2", "2025-10-30"), ("3A35190", "CLOSED", "L2", "2025-10-30"),
                              ("3A35075", "CLOSED", "L2", "2025-10-29")):
        db.dob_logs.docs.append({"_id": f"od_{cn}", "project_id": "p546", "company_id": "co_blueview",
                                 "record_type": "complaint", "raw_dob_id": cn, "complaint_number": cn,
                                 "complaint_status": st, "current_status": st, "disposition_code": disp,
                                 "complaint_date": f"{day}T00:00:00.000", "nyc_bin": "3255205",
                                 "detected_at": datetime(2026, 10, 13, 15, 47, tzinfo=timezone.utc),
                                 "is_deleted": False})
    db.source_sync_state.docs.append({"_id": "p546", "company_id": "co_blueview", "sources": {
        "dob_complaints": {"first_synced_at": datetime(2026, 10, 13, tzinfo=timezone.utc),
                           "synced_at": NOW - timedelta(minutes=14)}}})
    return db


def _run(db, client, mode, now=NOW, emails=None, bodies=None):
    async def fake_send(project, doc, source="dob", *, event):
        from lib import dob_alert_gate
        assert event in dob_alert_gate.EVENTS, event          # the email's own vocabulary
        emails.append((doc.get("raw_dob_id"), source, event))
        if bodies is not None:
            bodies.append(doc.get("ai_summary") or "")
        return True
    with patch.object(server, "db", db), \
            patch.object(server, "_send_critical_dob_alert_throttled", fake_send):
        return asyncio.run(server.run_bis_complaint_watch_for_project(
            copy.deepcopy(PROJECT), client, mode=mode, now=now))


class Shadow(unittest.TestCase):
    def test_shadow_records_decisions_and_writes_no_record(self):
        db, emails = _seed(), []
        s = _run(db, _BIS(), "shadow", emails=emails)
        self.assertEqual(emails, [])
        self.assertFalse([d for d in db.dob_logs.docs if d["raw_dob_id"] in ("3A88489", "3A88492")])
        led = {d["complaint_number"]: d for d in db.complaint_watch_ledger.docs}
        self.assertEqual((led["3A88489"]["status"], led["3A88492"]["status"]), ("would_alert", "would_alert"))
        self.assertEqual(led["3A88489"]["priority"], "high")
        self.assertEqual(sorted(b["bin"] for b in s["bins"]), ["3255205", "3423445"])
        w = db.source_sync_state.docs[0]["watch"]["bis_complaints"]
        self.assertEqual((w["last_success_at"], w["last_error"]), (NOW, None))


def _details(client) -> int:
    return sum("OverviewForComplaintServlet" in u for u in client.urls)


class FetchBudget(unittest.TestCase):
    """BIS says RESOLVED where Open Data says CLOSED. Without treating them as
    one state every stored history row looks changed and is re-fetched."""

    def test_first_pass_fetches_details_only_for_rows_open_data_had_not_stored(self):
        db, emails, client = _seed(), [], _BIS()
        _run(db, client, "live", emails=emails)
        # 16 rows on BIN 3255205 + 1 on 3423445, minus the 7 Open Data had stored unchanged
        self.assertEqual(_details(client), 10, client.urls)

    def test_shadow_does_not_refetch_what_it_already_decided(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "shadow", emails=emails)
        again = _BIS()
        _run(db, again, "shadow", now=NOW + timedelta(minutes=10), emails=emails)
        self.assertEqual(_details(again), 0, again.urls)


class Live(unittest.TestCase):
    def test_live_stores_each_new_complaint_once_and_emails_each_once(self):
        db, emails, bodies = _seed(), [], []
        _run(db, _BIS(), "live", emails=emails, bodies=bodies)
        new = [d for d in db.dob_logs.docs if d["raw_dob_id"] in ("3A88489", "3A88492")]
        self.assertEqual(sorted(d["raw_dob_id"] for d in new), ["3A88489", "3A88492"])
        for d in new:
            self.assertEqual((d["dataset"], d["severity"], d["bin_first_pass"], d["current_status"]),
                             ("bis", "Action", False, "ACTIVE"))
            self.assertEqual(d["complaint_date"], "2026-11-10T00:00:00.000")
        self.assertEqual(sorted(emails), [("3A88489", "bis", "new"), ("3A88492", "bis", "new")])
        body = next(b for b in bodies if "3A88489" in b)
        self.assertIn("NO ROOF PROTECTION", body)
        self.assertIn("A complaint is not a violation", body)
        # history that Open Data already stored was not duplicated
        for cn in ("3A70078", "3A35190"):
            self.assertEqual(len([d for d in db.dob_logs.docs if d["raw_dob_id"] == cn]), 1)

    def test_a_second_pass_changes_nothing_and_sends_nothing(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        n_rows, n_led = len(db.dob_logs.docs), len(db.complaint_watch_ledger.docs)
        emails.clear()
        client = _BIS()
        _run(db, client, "live", now=NOW + timedelta(minutes=10), emails=emails)
        self.assertEqual((len(db.dob_logs.docs), len(db.complaint_watch_ledger.docs), emails), (n_rows, n_led, []))
        # a quiet pass is one property page + one list page per BIN: no detail fetches
        self.assertEqual(len(client.urls), 3, client.urls)

    def test_the_open_data_row_next_day_refreshes_the_same_row(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        row = next(d for d in db.dob_logs.docs if d["raw_dob_id"] == "3A88489")
        # what the Open Data path builds for the same complaint the next day
        od = {"project_id": "p546", "record_type": "complaint", "raw_dob_id": "3A88489",
              "current_status": "ACTIVE", "complaint_status": "ACTIVE", "detected_at": NOW + timedelta(days=1),
              "severity": "Action", "dataset": "eabe-havv"}
        update, changed, _ = server._plan_in_place_refresh(row, od, NOW + timedelta(days=1))
        self.assertNotIn("detected_at", update, "detection time must stay the BIS time")
        self.assertNotIn("bis", update)
        self.assertFalse(changed)


class Outage(unittest.TestCase):
    def test_a_bis_outage_is_a_recorded_failure_not_an_absence(self):
        db, emails = _seed(), []
        s = _run(db, _BIS(down=True), "live", emails=emails)
        self.assertTrue(s["errors"])
        self.assertEqual(s["decisions"], [])
        w = db.source_sync_state.docs[0]["watch"]["bis_complaints"]
        self.assertNotIn("last_success_at", w)
        self.assertIn("HTTP 503", w["last_error"])
        f = cw.freshness(db.source_sync_state.docs[0], now=NOW)
        self.assertFalse(f["can_say_no_new_complaints"])
        self.assertEqual(f["sources"][0]["status"], "never")


class Off(unittest.TestCase):
    def test_off_is_the_default_and_does_nothing(self):
        with patch.dict(os.environ, {"BIS_COMPLAINT_WATCH_MODE": ""}):
            self.assertEqual(server._bis_watch_mode(), "off")
        with patch.dict(os.environ, {"BIS_COMPLAINT_WATCH_MODE": "LIVE "}):
            self.assertEqual(server._bis_watch_mode(), "live")
        with patch.dict(os.environ, {"BIS_COMPLAINT_WATCH_MODE": "yes"}):
            self.assertEqual(server._bis_watch_mode(), "off")


if __name__ == "__main__":
    unittest.main()
