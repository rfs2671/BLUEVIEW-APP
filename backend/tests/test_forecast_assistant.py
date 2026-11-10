"""schedule_status and the lookahead, through server.py: scoped to the job's
company, read only, offered to field roles, and carrying lib/forecast.py's four
groups. The pure rules are tests/test_forecast.py."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import dm_roles  # noqa: E402
from tests.test_dm_brain import _Brain  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402


class ScheduleStatusTool(_Brain):

    def _seed_confirmed(self):
        today = datetime.now(timezone.utc).date()
        self.db[server.PROJECT_SCHEDULES].rows.append(
            {"_id": "c1", "company_id": str(CO_A), "project_id": THOMAS, "status": "confirmed",
             "doc": {"data_date": today.isoformat(), "activities": [
                 {"id": "A1", "name": "Drywall Floor 3", "kind": "task", "predecessors": [],
                  "current_start": (today - timedelta(days=20)).isoformat(),
                  "current_finish": (today - timedelta(days=5)).isoformat()},
                 {"id": "A2", "name": "Prime Floor 3", "kind": "task",
                  "predecessors": [{"id": "A1", "type": "FS", "lag": None, "lag_unit": None}],
                  "current_start": (today + timedelta(days=2)).isoformat(),
                  "current_finish": (today + timedelta(days=9)).isoformat()}]}})

    def _call(self, tool, args=None, company=CO_A):
        async def go():
            ctx = {"ident": {"company_id": company, "user_id": "u_admin", "role": "admin", "user": {"name": "Ada"}},
                   "text": "are we on schedule?"}
            return await getattr(server, tool)(ctx, {"id": THOMAS, "label": "588"}, args or {})
        with _Ctx(db=self.db):
            return asyncio.run(go())

    def test_it_is_offered_classified_and_dispatched(self):
        self.assertIn("schedule_status", {t["name"] for t in server._DM_BRAIN_EXTRA_TOOLS})
        self.assertIn("schedule_status", server._DM_BRAIN_ONE_JOB)
        self.assertIn("schedule_status", dm_roles.FIELD_TOOLS)
        self.assertIsNone(dm_roles.tool_refusal("cp", "schedule_status", {}))
        self.assertIsNone(dm_roles.tool_refusal("superintendent", "schedule_status", {}))
        src = Path(server.__file__).read_text(encoding="utf-8")
        body = src[src.index("async def _dm_brain_exec_one("):]
        self.assertIn('if name == "schedule_status":\n            return await _dm_schedule_status(', body)

    def test_no_confirmed_file_no_forecast(self):
        self.assertIn("No confirmed schedule is on file for 588", self._call("_dm_schedule_status"))

    def test_the_four_groups_come_back_and_nothing_is_written(self):
        self._seed_confirmed()
        self.db[server.INSPECTION_REPORTS].rows.append(
            {"_id": "r1", "project_id": THOMAS, "company_id": str(CO_A), "status": "attested", "gate": "gate_plumbing_rough",
             "result": "passed", "levels": ["FLOOR_3"], "inspected_on": None, "reporter_name": "Sam",
             "quote": "plumbing rough passed on 3", "created_at": datetime.now(timezone.utc)})
        before = {name: [dict(r) for r in coll.rows] for name, coll in self.db._c.items() if coll.rows}
        out = self._call("_dm_schedule_status")
        for label in ("VERIFIED (", "FILE (", "REPORTED (", "ESTIMATES ("):
            self.assertIn(label, out)
        self.assertIn("  - Drywall Floor 3 (A1): planned finish", out)
        self.assertIn("ESTIMATE: Prime Floor 3 (A2)", out)
        after = {name: [dict(r) for r in coll.rows] for name, coll in self.db._c.items() if coll.rows}
        self.assertEqual(before, after)

    def test_the_lookahead_carries_the_status(self):
        self._seed_confirmed()
        out = self._call("_dm_schedule_lookahead", {"days": 14})
        self.assertIn("Prime Floor 3 (A2). FILE: planned current", out)
        self.assertIn("SCHEDULE STATUS for 588", out)

    def test_another_companys_job_is_refused(self):
        self._seed_confirmed()
        self.assertEqual(self._call("_dm_schedule_status", company="c0ffee000000000000000099"),
                         server.wa_security.BOT_SCOPE_REFUSAL)


if __name__ == "__main__":
    unittest.main()
