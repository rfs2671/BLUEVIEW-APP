"""THE SUPERINTENDENT DOES NOT LEAVE BEFORE HE ARRIVED -- unless he says so.

Ruled 2026-10-10, after 588 Thomas's superintendent's log for 2026-10-05 was
filed reading "arrived 05:50 PM, departed 04:30 PM" with "departed next day"
unticked. Five filed logs on that project read backwards. The form checked
only that both times were present, and the server checked nothing.

  - Departure before arrival is REFUSED at filing (create, the PUT that
    submits, finalize) unless `departed_next_day` is true.
  - It is a refusal and never a correction: no time is rewritten and the tick
    is never inferred.
  - A draft may hold anything; a time the gate cannot read is not its business.
  - Nothing already filed is touched.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from tests.test_submit_requires_signature import (  # noqa: E402
    _FakeDb, _db_for_create, _db_for_update, _post, _put, _user,
)

_SIG = {"paths": [[1, 2]], "signed_at": "2026-10-05T21:52:00Z",
        "affirmed": True, "affirmedAt": "2026-10-05T21:52:00Z"}


def _presence(arrived, departed, next_day=False):
    return {"presence": {"printed_name": "Michael Cespedes",
                         "arrived_at": arrived, "departed_at": departed,
                         "departed_next_day": next_day}}


def _detail(arrived, departed, next_day=False):
    return server._submit_presence_order_detail(
        "site_superintendent_log", _presence(arrived, departed, next_day))


class TheRule(unittest.TestCase):

    def test_1005_is_refused_and_both_times_are_quoted(self):
        d = _detail("05:50 PM", "04:30 PM")
        self.assertEqual(d, {"code": "SUBMIT_DEPARTURE_BEFORE_ARRIVAL",
                             "arrived_at": "05:50 PM",
                             "departed_at": "04:30 PM"})

    def test_the_five_filed_logs_would_each_be_refused(self):
        for arrived, departed in [("06:05 PM", "04:30 AM"),   # 09-04
                                  ("06:30 PM", "04:00 AM"),   # 09-08
                                  ("03:19 PM", "04:04 AM"),   # 09-16
                                  ("03:00 PM", "03:40 AM"),   # 09-18
                                  ("05:50 PM", "04:30 PM")]:  # 10-05
            with self.subTest(arrived=arrived, departed=departed):
                self.assertIsNotNone(_detail(arrived, departed))

    def test_the_next_day_tick_allows_it(self):
        self.assertIsNone(_detail("08:00 PM", "04:00 AM", next_day=True))

    def test_the_tick_is_his_a_truthy_non_boolean_is_not_it(self):
        self.assertIsNotNone(_detail("08:00 PM", "04:00 AM", next_day="yes"))

    def test_an_ordinary_day_and_equal_times_pass(self):
        self.assertIsNone(_detail("07:00 AM", "04:00 PM"))
        self.assertIsNone(_detail("07:00 AM", "07:00 AM"))

    def test_the_older_24_hour_shape_is_read(self):
        self.assertIsNotNone(_detail("17:50", "16:30"))
        self.assertIsNotNone(_detail("05:50 PM", "16:30"))

    def test_midnight_and_noon(self):
        self.assertEqual(server._presence_clock_minutes("12:00 AM"), 0)
        self.assertEqual(server._presence_clock_minutes("12:30 PM"), 750)
        self.assertEqual(server._presence_clock_minutes("11:59 PM"), 1439)

    def test_a_time_it_cannot_read_is_not_its_business(self):
        for bad in ("", None, "half four", "25:00", "13:00 PM", "07:75 AM"):
            with self.subTest(bad=bad):
                self.assertIsNone(_detail(bad, "04:30 PM"))
                self.assertIsNone(_detail("05:50 PM", bad))

    def test_other_log_types_and_malformed_bodies_are_declined(self):
        self.assertIsNone(server._submit_presence_order_detail(
            "daily_jobsite", _presence("05:50 PM", "04:30 PM")))
        self.assertIsNone(server._submit_presence_order_detail(
            "site_superintendent_log", None))
        self.assertIsNone(server._submit_presence_order_detail(
            "site_superintendent_log", {"presence": "05:50 PM"}))


def _stored(data, **extra):
    doc = {"_id": "lb1", "project_id": "proj1",
           "log_type": "site_superintendent_log", "date": "2026-10-05",
           "data": data, "cp_signature": _SIG, "cp_name": "Michael Cespedes",
           "is_locked": False, "status": "draft"}
    doc.update(extra)
    return doc


class FilingIsWhereItIsRefused(unittest.TestCase):

    def test_create_refuses_a_submit_and_writes_nothing(self):
        db = _db_for_create()
        resp = _post(db, {"project_id": "proj1",
                          "log_type": "site_superintendent_log",
                          "date": "2026-10-05",
                          "data": _presence("05:50 PM", "04:30 PM"),
                          "cp_signature": _SIG, "status": "submitted"})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"],
                         "SUBMIT_DEPARTURE_BEFORE_ARRIVAL")
        self.assertEqual(db.logbooks.inserted, [])
        self.assertEqual(db.logbooks.updated, [])

    def test_a_draft_may_hold_it(self):
        """Mid-entry he is never blocked -- he may type departure first."""
        db = _db_for_create()
        resp = _post(db, {"project_id": "proj1",
                          "log_type": "site_superintendent_log",
                          "date": "2026-10-05",
                          "data": _presence("05:50 PM", "04:30 PM"),
                          "cp_signature": _SIG, "status": "draft"})
        self.assertNotEqual(
            (resp.json().get("detail") or {}).get("code")
            if isinstance(resp.json().get("detail"), dict) else None,
            "SUBMIT_DEPARTURE_BEFORE_ARRIVAL", resp.text)

    def test_the_put_that_submits_is_refused(self):
        db = _db_for_update(_stored(_presence("05:50 PM", "04:30 PM")))
        resp = _put(db, {"status": "submitted"})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"],
                         "SUBMIT_DEPARTURE_BEFORE_ARRIVAL")
        self.assertEqual(db.logbooks.updated, [])

    def test_finalize_is_refused_and_does_not_lock(self):
        db = _FakeDb()
        db.projects.set_find_one(lambda q: {"_id": "proj1", "name": "588"})
        db.logbooks.set_find_one(
            lambda q: _stored(_presence("05:50 PM", "04:30 PM")))

        async def _fake_user():
            return _user("cp")

        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            with patch.object(server, "db", db):
                resp = TestClient(server.app).post("/api/logbooks/lb1/finalize")
        finally:
            server.app.dependency_overrides.clear()
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"],
                         "SUBMIT_DEPARTURE_BEFORE_ARRIVAL")
        self.assertEqual(
            [u for u in db.logbooks.updated if "is_locked" in str(u)], [])


if __name__ == "__main__":
    unittest.main()
