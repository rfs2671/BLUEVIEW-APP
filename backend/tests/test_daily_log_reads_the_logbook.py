"""The day's log tool returns what was filed.

Measured on production, 2026-09-16:

  daily_logs carrying `observations`     0 of 92
  daily_logs carrying `signed_by_name`   0 of 92
  daily_logs carrying `status`           1 of 92

_handle_daily_log read exactly those three fields, so every answer was
"Daily log <date>: 0 observation(s), 0 uncorrected" — well formed, and empty
of the weather, the head count, the work performed, the corrective actions and
the incident log that the row actually carries.

The schema it was reading belongs to `logbooks`: a different collection, four
times larger, seven log types, which no tool reached at all. And on 588
Boyland — the one project the bot is used on — there are 329 logbooks and ZERO
daily_logs, so every date answered "No daily log filed" whatever had been
filed that day.

The fixtures below are the shapes production actually holds, trimmed.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402


# ── 588 Boyland: logbooks, no daily_logs ─────────────────────────────────
BOYLAND_JOBSITE = {
    "project_id": "boyland", "date": "2026-09-16", "log_type": "daily_jobsite",
    "cp_name": "shawn", "status": "submitted",
    "data": {
        "weather": "Cloudy", "weather_temp": "74F", "weather_wind": "9 mph",
        "general_description": "carpentry",
        "activities": [{
            "crew_id": "C1", "company": "Arkon Builders", "num_workers": "11",
            "work_description": "framing (layout, track and studs)",
            "work_locations": "2nd-3rd floor, Roof protection",
            "photos": [{"original_r2_key": "a"}, {"original_r2_key": "b"}],
        }],
        "checklist_items": {"street_frontage": {"result": "pass"},
                            "permits": {"result": "fail"}},
        "equipment_on_site": {"compressor": True, "scissor_lift": False},
        "visitors_deliveries": "bC certified lumber",
    },
}
BOYLAND_SUPER = {
    "project_id": "boyland", "date": "2026-09-16",
    "log_type": "site_superintendent_log", "cp_name": "Michael Cespedes",
    "data": {
        "presence": {"arrived_at": "07:55 AM", "departed_at": "04:00 PM"},
        "progress": {"summary": "3rd floor flooring and Wall"},
        "daily_inspection": {"location": "Sidewalk shed 1st/2nd 3rd fl"},
        "unsafe_conditions": {"none_to_report": True},
        "incidents": {"none_to_report": False, "summary": "near miss at hoist"},
    },
}
BOYLAND_TALK = {
    "project_id": "boyland", "date": "2026-09-16", "log_type": "toolbox_talk",
    "cp_name": "shawn",
    "data": {"type_of_work": "Framing and roof protection", "meeting_time": "08:00 AM",
             "attendees": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
}

# ── 3846 Bailey: a daily_logs row, no logbooks ───────────────────────────
BAILEY_ROW = {
    "project_id": "bailey", "date": "2026-04-13", "created_by_name": "Roy Fishman",
    "weather": "Light Rain, 62F, wind 10 mph E", "weather_condition": "Light Rain",
    "weather_temp": "62F", "weather_wind": "10 mph E",
    "worker_count": "18",
    "work_performed": "Concrete placement, finishing, curing protection",
    "notes": "Concrete placement 340 cubic yards. Temperature monitored, no cold joints.",
    "corrective_actions": "None", "incident_log": "None",
    "subcontractor_cards": "None", "safety_checklist": "None",
}


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n=None):
        return [dict(r) for r in self.rows]


class _Coll:
    def __init__(self, rows):
        self.rows = list(rows)

    def _match(self, r, q):
        for k, v in (q or {}).items():
            if isinstance(v, dict) and "$ne" in v:
                if r.get(k) == v["$ne"]:
                    return False
            elif r.get(k) != v:
                return False
        return True

    def find(self, q=None, proj=None):
        return _Cursor([r for r in self.rows if self._match(r, q)])

    async def find_one(self, q=None, proj=None):
        for r in self.rows:
            if self._match(r, q):
                return dict(r)
        return None


class _Db:
    def __init__(self, logbooks=(), daily_logs=()):
        self.logbooks = _Coll(logbooks)
        self.daily_logs = _Coll(daily_logs)


def ask(project_id, date, logbooks=(), daily_logs=()):
    with mock.patch.object(server, "db", _Db(logbooks, daily_logs)):
        return asyncio.run(server._handle_daily_log(project_id, date))


class BoylandFilesLogbooksAndNoDailyLogs(unittest.TestCase):
    """329 logbooks, 0 daily_logs. Every date used to answer 'No daily log
    filed'."""

    def setUp(self):
        self.out = ask("boyland", "2026-09-16",
                       logbooks=[BOYLAND_TALK, BOYLAND_SUPER, BOYLAND_JOBSITE])

    def test_it_is_not_reported_as_nothing(self):
        self.assertNotIn("No daily log filed", self.out)
        self.assertTrue(self.out.startswith("Log for 2026-09-16:"))

    def test_the_work_performed(self):
        self.assertIn("framing (layout, track and studs)", self.out)
        self.assertIn("Arkon Builders (11)", self.out)

    def test_where_the_work_was(self):
        self.assertIn("2nd-3rd floor, Roof protection", self.out)

    def test_the_weather_and_who_filed_it(self):
        self.assertIn("Cloudy, 74F, 9 mph", self.out)
        self.assertIn("(shawn)", self.out)

    def test_a_failed_checklist_item_is_named_and_a_passed_one_is_not(self):
        self.assertIn("checklist not passed: permits", self.out)
        self.assertNotIn("street frontage", self.out)

    def test_photos_are_counted(self):
        self.assertIn("2 photo(s)", self.out)

    def test_the_superintendent_log_too(self):
        self.assertIn("on site 07:55 AM to 04:00 PM", self.out)
        self.assertIn("progress: 3rd floor flooring and Wall", self.out)
        self.assertIn("inspected: Sidewalk shed 1st/2nd 3rd fl", self.out)

    def test_none_to_report_costs_no_line_but_a_real_one_does(self):
        self.assertNotIn("unsafe conditions", self.out)
        self.assertIn("incidents: near miss at hoist", self.out)

    def test_the_toolbox_talk(self):
        self.assertIn("Framing and roof protection, 08:00 AM, 3 attended", self.out)

    def test_the_daily_log_leads(self):
        first = [l for l in self.out.splitlines() if l.startswith("  ")][0]
        self.assertIn("daily jobsite log", first)


class BaileyFilesDailyLogsAndNoLogbooks(unittest.TestCase):
    """The other collection, whose fields were never printed."""

    def setUp(self):
        self.out = ask("bailey", "2026-04-13", daily_logs=[BAILEY_ROW])

    def test_the_substance_is_there(self):
        self.assertIn("18 workers", self.out)
        self.assertIn("Concrete placement, finishing, curing protection", self.out)
        self.assertIn("340 cubic yards", self.out)
        self.assertIn("(Roy Fishman)", self.out)

    def test_the_weather_is_not_printed_twice(self):
        # The row carries a composed `weather` AND the pieces it was made from.
        self.assertIn("Light Rain, 62F, wind 10 mph E", self.out)
        self.assertEqual(self.out.count("Light Rain"), 1)

    def test_none_is_not_content(self):
        self.assertNotIn("corrective actions: None", self.out)
        self.assertNotIn("incidents: None", self.out)

    def test_the_old_answer_is_gone(self):
        self.assertNotIn("observation(s)", self.out)


class BothCollectionsOnOneDay(unittest.TestCase):

    def test_each_is_rendered(self):
        out = ask("boyland", "2026-09-16", logbooks=[BOYLAND_JOBSITE],
                  daily_logs=[dict(BAILEY_ROW, project_id="boyland",
                                   date="2026-09-16")])
        self.assertIn("daily jobsite log", out)
        self.assertIn("daily log (Roy Fishman)", out)


class ADayWithNothingFiled(unittest.TestCase):

    def test_it_names_the_day_it_looked_at(self):
        self.assertEqual(ask("boyland", "2026-01-01"), "Nothing filed for 2026-01-01.")


class WhatTheRenderersRefuseToPrint(unittest.TestCase):

    def test_a_checkbox_group_prints_its_ticked_names(self):
        out = ask("boyland", "2026-09-16", logbooks=[BOYLAND_JOBSITE])
        self.assertIn("equipment: compressor", out)
        self.assertNotIn("{", out, "a dict reached the reader")
        self.assertNotIn("True", out)

    def test_the_reply_is_bounded(self):
        many = [dict(BOYLAND_JOBSITE, data=dict(BOYLAND_JOBSITE["data"],
                                                general_description="x" * 400))
                for _ in range(12)]
        out = ask("boyland", "2026-09-16", logbooks=many)
        self.assertLessEqual(len(out), server.DAILY_LOG_MAX_CHARS)


class TheToolNoLongerReadsFieldsThatDoNotExist(unittest.TestCase):

    def test_the_handler_reads_both_collections(self):
        import inspect
        src = inspect.getsource(server._handle_daily_log)
        self.assertIn("db.logbooks.find(", src)
        self.assertIn("db.daily_logs.find_one(", src)

    def test_it_no_longer_reports_signed_by_name_or_observation_counts(self):
        import inspect
        src = inspect.getsource(server._handle_daily_log)
        # Anchored: the field only ever appeared as a quoted key on a .get(),
        # and a bare word would be satisfied by any line mentioning it.
        self.assertNotIn('.get("signed_by_name")', src)
        self.assertNotIn('"observations"', src)
        self.assertNotIn('observation(s),', src)


if __name__ == "__main__":
    unittest.main()
