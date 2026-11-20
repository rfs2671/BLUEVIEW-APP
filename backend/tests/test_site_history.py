"""What happened on site, kind of work by kind of work: visits, gaps, crews,
and where the record shows time going (lib/site_history.py).

The rows are SYNTHETIC, shaped like the crew rows of 588 Boyland's daily logs.
Every figure the module prints is a count of rows, so each test builds the
rows and counts by hand.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import progress_stages as S  # noqa: E402
from lib import site_history as H  # noqa: E402


def row(d, company, trade, work, where="2nd Floor", workers=4):
    return {"date": d, "company": company, "key": company.lower(), "trade": trade, "work": work, "where": where,
            "floors": S.floors_of_text(where), "workers": workers, "photos": [], "work_trades": []}


def weekdays(first, last):
    d = first
    while d <= last:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


MON = date(2026, 10, 5)                 # a Monday with no federal holiday that week
END = date(2026, 11, 13)


class Shares(unittest.TestCase):
    def test_a_line_naming_two_kinds_of_work_gives_each_half_the_crew(self):
        got = H.shares([row(MON, "Arkon", "Framers", "Ceiling drops, Sheet rack", workers=10)])
        self.assertEqual({s["family"]: s["workers"] for s in got}, {"framing": 5.0, "drywall": 5.0})

    def test_a_crew_that_installs_nothing_is_not_counted_as_work(self):
        self.assertEqual(H.shares([row(MON, "Echo", "Cleaning", "House cleaning", workers=3)]), [])

    def test_but_its_men_are_still_on_the_site_total(self):
        rows = [row(MON, "Echo", "Cleaning", "House cleaning", workers=3),
                row(MON, "Arkon", "Framers", "Interior framing", workers=7)]
        self.assertEqual(H.site_days(rows), {MON: 10.0})

    def test_a_head_count_that_is_not_a_number_counts_as_zero(self):
        self.assertEqual(H.shares([row(MON, "Arkon", "Framers", "Interior framing", workers="many")])[0]["workers"], 0.0)


class Runs(unittest.TestCase):
    def test_a_weekend_is_not_a_gap(self):
        rows = [row(d, "Arkon", "Framers", "Interior framing") for d in weekdays(MON, MON + timedelta(days=11))]
        t = H.runs(rows, END)["framing"]
        self.assertEqual((t["days"], len(t["visits"]), t["away"], t["longest_gap"]), (10, 1, 0, 0))

    def test_two_working_days_away_is_the_same_visit_three_is_a_return_trip(self):
        same = [row(MON, "B", "HVAC / Mechanical", "Ductwork rough"),
                row(MON + timedelta(days=3), "B", "HVAC / Mechanical", "Ductwork rough")]      # Tue, Wed away
        back = [row(MON, "B", "HVAC / Mechanical", "Ductwork rough"),
                row(MON + timedelta(days=4), "B", "HVAC / Mechanical", "Ductwork rough")]      # Tue-Thu away
        self.assertEqual(len(H.runs(same, END)["hvac"]["visits"]), 1)
        t = H.runs(back, END)["hvac"]
        self.assertEqual((len(t["visits"]), t["span"], t["away"], t["longest_gap"]), (2, 5, 3, 3))

    def test_a_federal_holiday_is_not_a_day_away(self):
        # Mon Oct 12 2026 is Columbus Day: Fri Oct 9 then Tue Oct 13 is consecutive working days.
        rows = [row(date(2026, 10, 9), "A", "Plumber", "Domestic water rough"),
                row(date(2026, 10, 13), "A", "Plumber", "Domestic water rough")]
        t = H.runs(rows, END)["plumbing"]
        self.assertEqual((t["span"], t["away"]), (2, 0))

    def test_worker_days_crew_and_the_companies_behind_them(self):
        rows = [row(MON, "Power Direct", "Electrician", "Pull wire", workers=3),
                row(MON + timedelta(days=1), "Power Direct", "Electrician", "Pull wire", workers=9),
                row(MON + timedelta(days=2), "Power Direct", "Electrician", "Pull wire", workers=6)]
        t = H.runs(rows, END)["electrical"]
        self.assertEqual((t["worker_days"], t["crew"], t["crew_max"], t["companies"]), (18.0, 6, 9, ["Power Direct"]))

    def test_on_site_now_means_worked_in_the_last_five_working_days(self):
        rows = [row(END - timedelta(days=4), "A", "Plumber", "Domestic water rough"),      # Mon of the last week
                # Thu Nov 5: five working days before the end (Nov 11, Veterans Day, is not one)
                row(END - timedelta(days=8), "B", "HVAC / Mechanical", "Ductwork rough"),
                row(END, "C", "Electrician", "Pull wire")]
        rr = H.runs(rows, END)
        self.assertTrue(rr["plumbing"]["on_site"])
        self.assertFalse(rr["hvac"]["on_site"])
        self.assertEqual(rr["hvac"]["since_last"], 5)

    def test_rows_after_the_end_are_not_read(self):
        rows = [row(MON, "A", "Plumber", "Domestic water rough"),
                row(END + timedelta(days=3), "A", "Plumber", "Domestic water rough")]
        self.assertEqual(H.runs(rows, END)["plumbing"]["days"], 1)


class TimeLost(unittest.TestCase):
    def kinds(self, rows, weather=None):
        return {f["kind"]: f for f in H.time_lost(rows, END, weather)}

    def test_three_visits_with_more_days_away_than_worked_is_a_return_trip_finding(self):
        rows = [row(MON + timedelta(days=n), "MQ", "Steel / Ironwork", "Stairs", workers=2) for n in (0, 7, 14)]
        rows += [row(d, "Arkon", "Framers", "Interior framing", workers=8) for d in weekdays(MON, END)]
        f = self.kinds(rows)["return_trips"]
        self.assertEqual((f["family"], f["visits"], f["days"], f["away"]), ("steel", 3, 3, 8))
        self.assertIn("3 worked days in 3 separate visits", f["text"])

    def test_a_trade_that_stays_is_not_a_return_trip(self):
        rows = [row(d, "Arkon", "Framers", "Interior framing", workers=8) for d in weekdays(MON, END)]
        self.assertNotIn("return_trips", self.kinds(rows))

    def test_coming_back_twice_is_not_a_finding_when_most_of_the_stretch_was_worked(self):
        # Four days worked, three working days away, twice over: 3 visits, 12 worked days, 6 away.
        # (Oct 5-8; away Oct 9, 13, 14 -- Oct 12 is a holiday; Oct 15-20; away Oct 21-23; Oct 26-29.)
        on = [MON + timedelta(days=n) for n in (0, 1, 2, 3, 10, 11, 14, 15, 21, 22, 23, 24)]
        rows = [row(d, "A", "Plumber", "Domestic water rough") for d in on]
        t = H.runs(rows, END)["plumbing"]
        self.assertEqual((len(t["visits"]), t["days"], t["away"]), (3, 12, 6))
        self.assertNotIn("return_trips", self.kinds(rows))

    def test_one_man_at_a_time_for_five_days_is_a_thin_crew(self):
        rows = [row(MON + timedelta(days=n), "B", "HVAC / Mechanical", "Ductwork rough", workers=1) for n in range(5)]
        self.assertEqual(self.kinds(rows)["thin_crew"]["family"], "hvac")
        rows = [row(MON + timedelta(days=n), "B", "HVAC / Mechanical", "Ductwork rough", workers=2) for n in range(5)]
        self.assertNotIn("thin_crew", self.kinds(rows))

    def test_a_working_day_with_no_crew_is_listed_and_a_holiday_or_weekend_is_not(self):
        # Nobody on Oct 21 (a Wednesday), nor on Columbus Day (Oct 12) or Veterans Day (Nov 11).
        off = (date(2026, 10, 21), date(2026, 10, 12), date(2026, 11, 11))
        days = [d for d in weekdays(MON, END) if d not in off]
        f = self.kinds([row(d, "Arkon", "Framers", "Interior framing", workers=8) for d in days])["no_work_days"]
        self.assertEqual(f["days"], [date(2026, 10, 21)])
        self.assertEqual(f["of"], 28)

    def test_a_day_under_half_the_usual_head_count_is_low_and_carries_its_weather(self):
        days = list(weekdays(MON, END))
        wet = days[12]
        rows = [row(d, "Arkon", "Framers", "Interior framing", workers=(2 if d == wet else 10)) for d in days]
        f = self.kinds(rows, {wet: "Rainy"})["low_days"]
        self.assertEqual((f["days"], f["wet"], f["size"]), ([wet], [wet], 8))
        self.assertNotIn("low_days", self.kinds([row(d, "Arkon", "Framers", "Interior framing", workers=10)
                                                 for d in days]))

    def test_no_finding_names_a_cause(self):
        rows = [row(MON + timedelta(days=n), "MQ", "Steel / Ironwork", "Stairs", workers=1) for n in (0, 7, 14, 21, 28)]
        for f in H.time_lost(rows, END):
            for word in ("because", "due to", "delay", "late", "waiting"):
                self.assertNotIn(word, f["text"].lower(), f["text"])


class Summary(unittest.TestCase):
    def test_shares_add_up_and_the_most_labour_is_first(self):
        rows = [row(d, "Arkon", "Framers", "Interior framing", workers=9) for d in weekdays(MON, END)]
        rows += [row(MON, "A", "Plumber", "Domestic water rough", workers=3)]
        s = H.summary(rows, END)
        self.assertEqual([t["key"] for t in s["trades"]], ["framing", "plumbing"])
        self.assertAlmostEqual(sum(t["share"] for t in s["trades"]), 1.0)
        self.assertEqual(s["worker_days_all"], s["worker_days_installing"])

    def test_nothing_filed_is_an_empty_summary_not_an_error(self):
        s = H.summary([], END)
        self.assertEqual((s["first"], s["worked_days"], s["trades"]), (None, 0, []))
        self.assertEqual(H.time_lost([], END), [])


if __name__ == "__main__":
    unittest.main()
