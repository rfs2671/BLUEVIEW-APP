"""Attendance Q&A in the DM assistant -- every number from the check-ins.

  "how many days has arkon been on 588"
      -> "Arkon Builders: 23 days (Sep 14 → today), 230 man-days, avg 10/day, ..."
  "how many guys were on site each day last week" -> a short per-day list
  "who was on site on Oct 3"                      -> subs + counts
  "busiest day this month"                        -> the date + the count
Ranges as said ("last week", "since Oct 1", "this month"); long lists ->
the first lines + the offer of the full report. None of these is today's
headcount route.
"""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import attendance as A, wa_headcount  # noqa: E402
from tests.test_dm_facts_and_brief import WED, _arkon_rows, _run  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_morning_brief import _world  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx  # noqa: E402

NY = A.NY


def _at(d: date, h=7, m=30):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=NY).astimezone(timezone.utc)


def _site():
    """Arkon (the 23-day fixture) plus Power Direct on some days."""
    rows, count = _arkon_rows()
    rows = [r for r in rows if r.get("worker_company") != "Power Direct"]
    power = {date(2026, 10, 2): 6, date(2026, 10, 3): 4, date(2026, 10, 6): 5, date(2026, 10, 7): 5}
    for d, n in power.items():
        for w in range(n):
            rows.append({"_id": f"pd-{d}-{w}", "project_id": THOMAS, "worker_id": f"pd{w}",
                         "worker_company": "Power Direct", "check_in_time": _at(d, 8)})
    return rows, count, power


class SubAttendance(unittest.TestCase):

    def test_how_many_days_has_arkon_been_on_588(self):
        rows, count, _ = _site()
        self.assertEqual(sum(count.values()), 230)
        got = A.answer("sub_attendance", {"sub": "arkon"}, rows, WED, "588",
                       "how many days has arkon been on 588")
        self.assertEqual(got, "Arkon Builders: 23 days (Sep 14 → today), 230 man-days, avg 10/day, "
                              "most 14 on Oct 2; 9 today.")

    def test_a_range_as_said(self):
        rows, count, _ = _site()
        got = A.answer("sub_attendance", {"sub": "arkon", "range": "since Oct 1"}, rows, WED, "588")
        days = [d for d in count if d >= date(2026, 10, 1)]
        man = sum(count[d] for d in days)
        self.assertTrue(got.startswith(f"Arkon Builders: {len(days)} days since Oct 1 (Oct 1 → today), "
                                       f"{man} man-days"), got)

    def test_one_worker_twice_a_day_is_one_man_day(self):
        rows = [{"worker_id": "a", "worker_company": "Arkon", "check_in_time": _at(date(2026, 10, 13), 7)},
                {"worker_id": "a", "worker_company": "Arkon", "check_in_time": _at(date(2026, 10, 13), 13)}]
        s = A.summary(rows, WED, "arkon")
        self.assertEqual((len(s["days"]), s["man_days"]), (1, 1))

    def test_a_worker_in_two_companies_one_day_counts_once_first_company(self):
        # Codex on #794: a corrected company on a later check-in is not a
        # second worker -- the first check-in's company, as the headcount does.
        d = date(2026, 10, 13)
        rows = [{"worker_id": "a", "worker_company": "Arkon", "check_in_time": _at(d, 7)},
                {"worker_id": "a", "worker_company": "Power Direct", "check_in_time": _at(d, 13)},
                {"worker_id": "b", "worker_company": "Power Direct", "check_in_time": _at(d, 8)}]
        days = A.by_day(reversed(rows))
        self.assertEqual({c: sorted(w) for c, w in days[d].items()},
                         {"Arkon": ["a"], "Power Direct": ["b"]})
        self.assertEqual(A.summary(rows, WED)["man_days"], 2)
        self.assertEqual(A.summary(rows, WED, "power direct")["man_days"], 1)

    def test_no_check_ins_says_so(self):
        self.assertEqual(A.answer("sub_attendance", {"sub": "arkon", "range": "last week"}, [], WED, "588"),
                         "No check-ins at 588 from a company called 'arkon'.")
        rows, _, _ = _site()
        self.assertEqual(A.answer("sub_attendance", {"range": "in May"}, rows, WED, "588"),
                         "No check-ins at 588 for anyone May.")


class Headcount(unittest.TestCase):

    def test_each_day_last_week(self):
        rows, count, power = _site()
        got = A.answer("site_headcount", {"view": "per_day"}, rows, WED, "588",
                       "how many guys were on site each day last week")
        lines = got.splitlines()
        week = [date(2026, 10, 5) + timedelta(days=i) for i in range(5)]
        total = sum(count[d] + power.get(d, 0) for d in week)
        self.assertEqual(lines[0], f"Last week at 588 — 5 days, {total} man-days:")
        self.assertEqual(lines[1], "• Fri Oct 9: 10 (Arkon Builders 10)")
        self.assertIn("• Tue Oct 6: 15 (Arkon Builders 10, Power Direct 5)", lines)
        self.assertEqual(len(lines), 6)

    def test_who_was_on_site_on_oct_3(self):
        rows, _, _ = _site()
        # Oct 3 2026 is a Saturday: Arkon's fixture has weekdays only.
        self.assertEqual(A.answer("site_headcount", {"view": "day"}, rows, WED, "588",
                                  "who was on site on Oct 3"),
                         "Sat Oct 3 at 588: 4 on site — Power Direct 4.")
        self.assertEqual(A.answer("site_headcount", {"view": "day", "range": "Oct 2"}, rows, WED, "588"),
                         "Fri Oct 2 at 588: 20 on site — Arkon Builders 14, Power Direct 6.")

    def test_busiest_day_this_month(self):
        rows, _, _ = _site()
        self.assertEqual(A.answer("site_headcount", {"view": "busiest"}, rows, WED, "588",
                                  "busiest day this month"),
                         "Busiest day this month at 588: Fri Oct 2 — 20 on site "
                         "(Arkon Builders 14, Power Direct 6).")

    def test_a_long_list_offers_the_report(self):
        rows, _, _ = _site()
        got = A.answer("site_headcount", {"view": "per_day", "range": "since Sep 1"}, rows, WED, "588")
        lines = got.splitlines()
        self.assertEqual(len(lines), 1 + A.CHAT_LINES + 1)
        self.assertTrue(lines[-1].startswith("…and "), lines[-1])
        self.assertIn('Want the full report? Say "report for 588".', lines[-1])

    def test_the_words_win_over_model_dates(self):
        # The model said Oct 1-14 for "last week"; the words say Oct 5-11.
        a, b, label = A.resolve_range({"date_from": "2026-10-01", "date_to": "2026-10-14"},
                                      "how many guys each day last week", WED)
        self.assertEqual((a, b, label), (date(2026, 10, 5), date(2026, 10, 11), "last week"))


class Ranges(unittest.TestCase):

    def test_phrases(self):
        cases = {
            "last week": (date(2026, 10, 5), date(2026, 10, 11)),
            "this week": (date(2026, 10, 12), date(2026, 10, 14)),
            "this month": (date(2026, 10, 1), date(2026, 10, 14)),
            "last month": (date(2026, 9, 1), date(2026, 9, 30)),
            "since Oct 1": (date(2026, 10, 1), date(2026, 10, 14)),
            "on Oct 3": (date(2026, 10, 3), date(2026, 10, 3)),
            "from Oct 1 to Oct 9": (date(2026, 10, 1), date(2026, 10, 9)),
            # Codex on #794: one interval, one year; past today ends today.
            "from Oct 1 to Oct 20": (date(2026, 10, 1), date(2026, 10, 14)),
            "from Nov 1 to Nov 9": (date(2025, 11, 1), date(2025, 11, 9)),
            "between Dec 20 and Jan 5": (date(2025, 12, 20), date(2026, 1, 5)),
            "September": (date(2026, 9, 1), date(2026, 9, 30)),
            "the last 2 weeks": (date(2026, 10, 1), date(2026, 10, 14)),
            "yesterday": (date(2026, 10, 13), date(2026, 10, 13)),
            "10/3": (date(2026, 10, 3), date(2026, 10, 3)),
            "how many guys may be there": (None, None),
            "how many days has arkon been on 588": (None, None),
        }
        for said, want in cases.items():
            with self.subTest(said):
                self.assertEqual(A.parse_range(said, WED)[:2], want)


class Routing(unittest.TestCase):

    def test_history_questions_never_go_to_todays_headcount(self):
        for q in ("how many guys were on site each day last week", "who was on site on Oct 3",
                  "busiest day this month", "how many days has arkon been on 588", "daily headcount"):
            with self.subTest(q):
                self.assertIsNone(wa_headcount.intent(q))
        for q in ("how many guys on site", "how many workers at 588 thomas", "how many guys today"):
            with self.subTest(q):
                self.assertEqual(wa_headcount.intent(q), wa_headcount.COUNT)

    def test_kinds(self):
        self.assertEqual(A.kind_of("how many days has arkon been on 588"), "sub_attendance")
        self.assertEqual(A.kind_of("how many guys were on site each day last week"), "per_day")
        self.assertEqual(A.kind_of("who was on site on Oct 3"), "day")
        self.assertEqual(A.kind_of("busiest day this month"), "busiest")

    def test_the_tools_are_offered_and_read_the_jobs_check_ins(self):
        names = {t["function"]["name"] for t in server._AGENT_TOOLS}
        self.assertTrue({"sub_attendance", "site_headcount"} <= names)
        db = _world()
        db.checkins.rows[:] = _site()[0]
        with _Ctx(db):
            got = _run(server._facts_tool("site_headcount", {"view": "busiest"}, company_id=CO_A,
                                          project_id=THOMAS, group_id=f"{ADMIN_PHONE}@c.us",
                                          now=WED, question="busiest day this month"))
        self.assertEqual(got, "Busiest day this month at 588 Thomas S Boyland St: Fri Oct 2 — 20 on "
                              "site (Arkon Builders 14, Power Direct 6).")

    def test_the_backstop_answers_from_the_check_ins(self):
        from unittest.mock import patch
        db = _world()
        db.checkins.rows[:] = _site()[0]

        async def agent(**kw):
            return "The data doesn't specify how many workers were on site each day."
        ident = {"company_id": CO_A, "user_id": "u_admin", "role": "admin", "user": {}}
        project = next(p for p in db.projects.rows if p["_id"] == THOMAS)
        real = server._attendance_fallback

        async def on_wed(project, body, now=None):
            return await real(project, body, now=WED)       # "this month" is October
        with _Ctx(db), patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_attendance_fallback", on_wed):
            out = _run(server._dm_answer_job(ident, project, f"{ADMIN_PHONE}@c.us",
                                             "busiest day this month", "m1"))
        self.assertIn("Fri Oct 2 — 20 on site", out)


if __name__ == "__main__":
    unittest.main()
