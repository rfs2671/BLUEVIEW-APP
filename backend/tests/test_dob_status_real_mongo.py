"""Against a REAL MongoDB: what the fake databases cannot prove.

tests/async_fake_mongo.py ignores .sort() and the to_list() length, so a test
on it cannot fail for a query that sorts the wrong way or cuts at a row count.
That is how the assistant's "open DOB complaints" answer shipped twice with a
row limit that 311 traffic could fill (80, then 2000). These tests run the
real code on a real mongod, where filtering, sorting and limits are enforced.

    docker run -d --rm -p 27018:27017 --name levelog-test-mongo mongo:7.0
    LEVELOG_TEST_MONGO_URL=mongodb://localhost:27018 python -m pytest tests/test_dob_status_real_mongo.py

Without LEVELOG_TEST_MONGO_URL the module SKIPS, and says so: CI is hermetic
by design (.github/workflows/tests.yml: "no database, no network, no service
containers"). It refuses any host but localhost, and drops its own database.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402
from tests.test_bis_complaint_watch_flow import NOW, PROJECT, _BIS, _Resp, _seed  # noqa: E402

URL = os.environ.get("LEVELOG_TEST_MONGO_URL", "")
_LOCAL = urlparse(URL).hostname in ("localhost", "127.0.0.1", "::1") if URL else False


class _Reads:
    """Wraps a real motor collection and records how many rows each find()
    handed back -- so a test can tell the DATABASE excluded a row from the
    code having skipped it."""
    def __init__(self, coll, log):
        self._c, self._log = coll, log

    def __getattr__(self, n):
        return getattr(self._c, n)

    def find(self, *a, **k):
        cur, log = self._c.find(*a, **k), self._log

        class _Cur:
            def sort(self, *sa, **sk):
                cur.sort(*sa, **sk)
                return self

            async def to_list(self, n=None):
                rows = await cur.to_list(n)
                log.append(len(rows))
                return rows
        return _Cur()


class _DB:
    def __init__(self, db, log):
        self._db, self._log = db, log

    def __getattr__(self, n):
        return self[n]

    def __getitem__(self, n):
        c = self._db[n]
        return _Reads(c, self._log) if n == "dob_logs" else c


@unittest.skipUnless(URL and _LOCAL, "needs a local mongod: set LEVELOG_TEST_MONGO_URL=mongodb://localhost:<port>")
class _RealMongo(unittest.TestCase):
    def setUp(self):
        import motor.motor_asyncio
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.name = f"levelog_realdb_{uuid.uuid4().hex[:10]}"
        self.client = motor.motor_asyncio.AsyncIOMotorClient(URL, serverSelectionTimeoutMS=5000,
                                                             io_loop=self.loop)
        self.db = self.client[self.name]
        self.reads: list = []

    def tearDown(self):
        self.loop.run_until_complete(self.client.drop_database(self.name))
        self.client.close()
        self.loop.close()
        asyncio.set_event_loop(None)

    def run_(self, coro):
        return self.loop.run_until_complete(coro)


def _complaint(i, cn, status, at, **kw):
    return {"_id": f"c{i}", "project_id": "p546", "company_id": "co_blueview", "record_type": "complaint",
            "raw_dob_id": cn, "complaint_number": cn, "complaint_status": status, "current_status": status.upper(),
            "complaint_source": "DOB Complaint", "complaint_date": "2026-11-10T00:00:00.000",
            "description": f"complaint {cn}", "detected_at": at, "is_deleted": False, **kw}


def _311(i, at):
    return {"_id": f"s{i}", "project_id": "p546", "company_id": "co_blueview", "record_type": "complaint",
            "raw_dob_id": f"311:{70000000 + i}", "complaint_number": str(70000000 + i),
            "complaint_status": "In Progress", "current_status": "IN PROGRESS",
            "complaint_source": "311", "source": "311", "detected_at": at, "is_deleted": False}


class AssistantOpenComplaintsOnARealDatabase(_RealMongo):
    def _status(self):
        with patch.object(server, "db", _DB(self.db, self.reads)):
            return self.run_(server._handle_dob_status("p546", company_id="co_blueview"))

    def _seed(self, n311):
        base = NOW - timedelta(days=5)
        rows = [
            # Open, and OLDER than every 311 row: the one a row limit drops first.
            _complaint(1, "3A88489", "ACTIVE", base),
            # Its newest row is CLOSED. The older ACTIVE row is inserted FIRST,
            # so natural order reaches it first: only a real sort gets this right.
            _complaint(2, "3A70078", "ACTIVE", base - timedelta(days=2)),
            _complaint(3, "3A70078", "CLOSED", base - timedelta(days=1)),
            _complaint(4, "3A68500", "RESOLVED", base),                     # closed
            _complaint(5, "3A11111", "ACTIVE", base, is_deleted=True),      # removed by a person
            dict(_complaint(6, "3A22222", "ACTIVE", base), company_id="co_other"),  # another company
        ]
        rows += [_311(i, base + timedelta(minutes=1 + i)) for i in range(n311)]
        self.run_(self.db.dob_logs.insert_many(rows))
        self.run_(self.db.projects.insert_one(copy.deepcopy(PROJECT)))

    def test_an_open_complaint_older_than_2500_newer_311_rows_is_listed(self):
        self._seed(2500)
        out = self._status()
        self.assertIn("3A88489", out)
        self.assertIn("Open DOB complaints (1)", out)
        for gone in ("3A70078", "3A68500", "3A11111", "3A22222", "311:"):
            self.assertNotIn(gone, out)
        # The DATABASE excluded the 311 rows: the complaint read handed back the
        # 4 non-311 rows of this company that are not deleted, not 2504.
        self.assertIn(4, self.reads)
        self.assertTrue(all(n < 100 for n in self.reads), self.reads)

    def test_closed_complaints_are_not_listed_among_hundreds_of_311_rows(self):
        self._seed(400)
        out = self._status()
        self.assertNotIn("3A70078", out)        # newest row CLOSED
        self.assertNotIn("3A68500", out)        # RESOLVED
        self.assertIn("3A88489", out)

    def test_no_open_complaint_says_none(self):
        self._seed(300)
        self.run_(self.db.dob_logs.update_many({"raw_dob_id": "3A88489"}, {"$set": {"complaint_status": "CLOSED"}}))
        out = self._status()
        self.assertIn("No open DOB complaints on file.", out)


class _ClosedBeforeLive(_BIS):
    """3A88489 resolved with no enforcement disposition between shadow and live."""
    async def get(self, url, **kw):
        r = await super().get(url, **kw)
        if "ComplaintsByAddressServlet" in url and "allbin=3255205" in url:
            head, tail = r.text.split(">3A88489</a></td>", 1)
            tail = tail.replace('<td class="content" align="center">ACT</td>',
                                '<td class="content" align="center">RES</td>', 1)
            return _Resp(200, head + ">3A88489</a></td>" + tail)
        if "OverviewForComplaintServlet" in url and "complaintno=3A88489" in url:
            return _Resp(200, "Overview for Complaint #: = *** COMPLAINT NUMBER NOT FOUND ****")
        return r


class ShadowThenLiveOnARealDatabase(_RealMongo):
    """The real 546 Saratoga BIS pages, the real watcher, a real database.
    Both BINs list history LeveLog never stored: 3A32841 (closed 2025, A8 =
    violation served), 3A27772, 3931368, ... and two ACTIVE Class 2 summonses
    from July (39556258Y, 39556260N). None of it is news."""

    def setUp(self):
        super().setUp()
        fake = _seed()
        for name in ("projects", "dob_logs", "source_sync_state"):
            docs = copy.deepcopy(getattr(fake, name).docs)
            if docs:
                self.run_(self.db[name].insert_many(docs))

    def _pass(self, mode, now, client=None):
        emails = []

        async def fake_send(project, doc, source="dob", *, event):
            emails.append((doc.get("raw_dob_id"), event))
            return True
        with patch.object(server, "db", self.db), \
                patch.object(server, "_send_critical_dob_alert_throttled", fake_send):
            self.run_(server.run_bis_complaint_watch_for_project(
                copy.deepcopy(PROJECT), client or _BIS(), mode=mode, now=now))
        return emails

    def _ledger(self, **flt):
        return self.run_(self.db.complaint_watch_ledger.find(flt).to_list(None))

    def test_live_after_shadow_emails_only_the_two_new_complaints(self):
        self.assertEqual(self._pass("shadow", NOW), [])
        would = sorted(r["complaint_number"] for r in self._ledger(mode="shadow", status="would_alert"))
        self.assertEqual(would, ["3A88489", "3A88492"])
        emails = self._pass("live", NOW + timedelta(minutes=30))
        self.assertEqual(sorted(emails), [("3A88489", "new"), ("3A88492", "new")])
        # History was stored silently (it is on the Compliance screen), never emailed.
        hist = self.run_(self.db.dob_logs.find_one({"raw_dob_id": "3A32841"}))
        self.assertIsNotNone(hist)
        self.assertTrue(hist["bin_first_pass"])
        ecb = self.run_(self.db.dob_logs.find({"dataset": "bis-ecb"}).to_list(None))
        self.assertEqual(len(ecb), 20)
        self.assertTrue(all(r["bin_first_pass"] for r in ecb))
        # And a second live pass sends nothing.
        self.assertEqual(self._pass("live", NOW + timedelta(minutes=40)), [])

    def test_what_shadow_judged_new_is_emailed_when_live_starts_days_later(self):
        self._pass("shadow", NOW)
        emails = self._pass("live", NOW + timedelta(days=3))
        self.assertEqual(sorted(emails), [("3A88489", "new"), ("3A88492", "new")])
        late = {r["complaint_number"]: r["late"] for r in self._ledger(mode="live", status="alerting")}
        self.assertEqual(late, {"3A88489": True, "3A88492": True})

    def test_a_complaint_resolved_between_shadow_and_live_is_not_emailed(self):
        self._pass("shadow", NOW)
        emails = self._pass("live", NOW + timedelta(hours=5), client=_ClosedBeforeLive())
        self.assertEqual(emails, [("3A88492", "new")])

    def test_the_compliance_summary_counts_what_is_open_after_live(self):
        """/projects/dob-summary is a $sort/$group/$match aggregation: only a real
        database runs it. After a live pass stores both BINs' history, the
        count is the two open complaints and the two open July summonses --
        not the 18 resolved summonses and 8 resolved complaints also stored."""
        self._pass("live", NOW)
        user = {"id": "u1", "_id": "u1", "company_id": "co_blueview", "role": "admin"}
        with patch.object(server, "db", self.db):
            res = self.run_(server.get_projects_dob_summary(project_id="p546", current_user=user))
        got = res["by_project"].get("p546") or res.get("totals")
        self.assertEqual((got["open_complaints"], got["open_violations"]), (2, 2), got)

    def test_live_with_no_shadow_first_emails_only_the_two_new_complaints(self):
        emails = self._pass("live", NOW)
        self.assertEqual(sorted(emails), [("3A88489", "new"), ("3A88492", "new")])


if __name__ == "__main__":
    unittest.main()
