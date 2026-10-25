"""The schedule endpoints: an import is a draft, and only a person's
confirmation makes it count. A confirmed schedule is never replaced silently;
non-admins and other companies cannot touch it; an unreadable draft cannot be
confirmed; imports and generation are rate limited."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import rate_limits  # noqa: E402
from tests import report_588 as F  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_morning_brief import _world  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx, _run  # noqa: E402

ADMIN = {"id": "u_admin", "_id": "u_admin", "role": "admin", "company_id": CO_A, "full_name": "Site PM"}
PM = {**ADMIN, "id": "u_pm", "_id": "u_pm", "role": "pm"}


def _rec(_id, status, doc=None, name="588 Master Schedule.xlsx"):
    return {"_id": _id, "company_id": str(CO_A), "project_id": THOMAS, "status": status,
            "doc": doc if doc is not None else F.schedule_doc(), "source_name": name,
            "imported_at": datetime(2026, 10, 14, tzinfo=timezone.utc)}


class ImportsNeverOverwriteWhatWasConfirmed(unittest.TestCase):

    def call(self, fn, db, user, *a, **kw):
        with _Ctx(db), patch.object(server, "_memory_project", AsyncMock(return_value=CO_A)), \
                patch.object(server, "audit_log", AsyncMock()):
            return _run(fn(THOMAS, *a, current_user=user, **kw))

    def db(self, *recs):
        db = _world()
        for r in recs:
            _run(db[server.PROJECT_SCHEDULES].insert_one(r))
        return db

    def status_of(self, db, _id):
        return next(r["status"] for r in db[server.PROJECT_SCHEDULES].rows if r["_id"] == _id)

    def test_confirming_with_nothing_confirmed_works(self):
        db = self.db(_rec("d1", "draft"))
        out = self.call(server.confirm_baseline_schedule, db, ADMIN, "d1", server.ScheduleConfirm(reviewed=True))
        self.assertEqual(out["status"], "confirmed")
        self.assertEqual(self.status_of(db, "d1"), "confirmed")

    def test_a_second_confirmation_needs_the_replace_flag(self):
        db = self.db(_rec("c1", "confirmed"), _rec("d1", "draft", name="new.xlsx"))
        with self.assertRaises(HTTPException) as cm:
            self.call(server.confirm_baseline_schedule, db, ADMIN, "d1", server.ScheduleConfirm(reviewed=True))
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual((self.status_of(db, "c1"), self.status_of(db, "d1")), ("confirmed", "draft"))

    def test_replacing_keeps_the_old_one_as_superseded(self):
        db = self.db(_rec("c1", "confirmed"), _rec("d1", "draft", name="new.xlsx"))
        self.call(server.confirm_baseline_schedule, db, ADMIN, "d1",
                  server.ScheduleConfirm(reviewed=True, replace_confirmed=True))
        self.assertEqual((self.status_of(db, "c1"), self.status_of(db, "d1")), ("superseded", "confirmed"))

    def test_the_reviewed_box_is_required(self):
        db = self.db(_rec("d1", "draft"))
        with self.assertRaises(HTTPException) as cm:
            self.call(server.confirm_baseline_schedule, db, ADMIN, "d1", server.ScheduleConfirm())
        self.assertEqual(cm.exception.status_code, 400)

    def test_a_draft_with_no_dated_activities_cannot_be_confirmed(self):
        empty = {**F.schedule_doc(), "activities": []}
        db = self.db(_rec("d1", "draft", empty))
        with self.assertRaises(HTTPException) as cm:
            self.call(server.confirm_baseline_schedule, db, ADMIN, "d1", server.ScheduleConfirm(reviewed=True))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertEqual(self.status_of(db, "d1"), "draft")

    def test_only_admins_confirm_or_discard(self):
        db = self.db(_rec("d1", "draft"))
        for fn, args in ((server.confirm_baseline_schedule, ("d1", server.ScheduleConfirm(reviewed=True))),
                         (server.discard_baseline_schedule, ("d1",))):
            with self.assertRaises(HTTPException) as cm:
                self.call(fn, db, PM, *args)
            self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(self.status_of(db, "d1"), "draft")

    def test_another_companys_draft_is_not_found(self):
        other = {**_rec("d1", "draft"), "company_id": "someone-else"}
        db = self.db(other)
        with self.assertRaises(HTTPException) as cm:
            self.call(server.confirm_baseline_schedule, db, ADMIN, "d1", server.ScheduleConfirm(reviewed=True))
        self.assertEqual(cm.exception.status_code, 404)

    def test_the_report_reads_only_the_confirmed_one(self):
        db = self.db(_rec("c1", "confirmed"), _rec("d1", "draft", name="draft.xlsx"),
                     _rec("s1", "superseded", name="old.xlsx"))
        view = self.call(server.get_baseline_schedule, db, PM)
        self.assertEqual(view["confirmed"]["source_name"], "588 Master Schedule.xlsx")
        self.assertEqual(view["draft"]["source_name"], "draft.xlsx")
        self.assertFalse(view["can_edit"])


class OnDemandGenerationIsRateLimited(unittest.TestCase):

    def test_the_routes_have_their_own_limits(self):
        for method, path, limit in (
                ("POST", "/api/projects/abc/project-reports", "6/10 minutes"),
                ("POST", "/api/projects/abc/baseline-schedule/upload", "10/10 minutes"),
                ("POST", "/api/projects/abc/baseline-schedule/from-file", "10/10 minutes")):
            got = rate_limits._match_rule(method, path)
            self.assertIsNotNone(got, path)
            self.assertEqual((got[1], got[2]), (limit, "user"), path)

    def test_listing_reports_keeps_the_default(self):
        self.assertIsNone(rate_limits._match_rule("GET", "/api/projects/abc/project-reports"))


if __name__ == "__main__":
    unittest.main()


class TheLimitHoldsAcrossInstances(unittest.TestCase):
    """The counter is in the database, so a second instance sees the first's
    hits; one person's hits are not another's; a window that has passed no
    longer counts; an unreachable database lets the request through."""

    def hit(self, db, who, n=1):
        out = []
        with _Ctx(db):
            for _ in range(n):
                try:
                    _run(server._shared_limit("report", who, server.REPORT_LIMIT))
                    out.append(200)
                except HTTPException as e:
                    out.append(e.status_code)
        return out

    def test_the_seventh_request_in_ten_minutes_is_refused(self):
        db = _world()
        self.assertEqual(self.hit(db, "u1", 8), [200] * 6 + [429, 429])

    def test_another_person_is_not_limited_by_it(self):
        db = _world()
        self.hit(db, "u1", 8)
        self.assertEqual(self.hit(db, "u2"), [200])

    def test_a_second_instance_shares_the_count(self):
        db = _world()
        self.hit(db, "u1", 4)                       # instance A
        self.assertEqual(self.hit(db, "u1", 3), [200, 200, 429])   # instance B, same database

    def test_old_hits_do_not_count(self):
        from datetime import timedelta
        db = _world()
        old = datetime.now(timezone.utc) - timedelta(seconds=server.REPORT_LIMIT[1] + 5)
        for i in range(10):
            _run(db[server.RATE_WINDOWS].insert_one({"_id": f"o{i}", "key": "report:u1", "at": old}))
        self.assertEqual(self.hit(db, "u1"), [200])

    def test_an_unreachable_database_lets_it_through(self):
        db = _world()

        async def boom(*a, **k):
            raise RuntimeError("mongo down")
        with _Ctx(db), patch.object(db[server.RATE_WINDOWS], "insert_one", boom):
            _run(server._shared_limit("report", "u1", server.REPORT_LIMIT))
