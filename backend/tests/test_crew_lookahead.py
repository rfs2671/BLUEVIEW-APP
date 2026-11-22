"""The next week's crews, and the scorecard that says how often the forecast's
range held (lib/crew_lookahead.py).

The operator's bar is "over 90%". These tests pin what that sentence is allowed
to mean: a range, built only from days before the day it is made on, and a hit
rate that is counted by replaying the job -- with the honest floor beside it.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import crew_lookahead as L  # noqa: E402
from lib import progress_stages as S  # noqa: E402


def row(d, company, trade, work, workers, where="2nd Floor"):
    return {"date": d, "company": company, "key": company.lower(), "trade": trade, "work": work, "where": where,
            "floors": S.floors_of_text(where), "workers": workers, "photos": [], "work_trades": []}


def weekdays(first, last):
    d = first
    while d <= last:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


START = date(2026, 3, 2)                # a Monday; no federal holiday until Memorial Day
END = date(2026, 5, 15)                 # a Friday, 11 full weeks later


def steady(workers=8, first=START, last=END):
    return [row(d, "Arkon", "Framers", "Interior framing", workers) for d in weekdays(first, last)]


def uneven(first=START, last=END):
    """A crew that swings between 4 and 12 men, on a pattern that is not weekly."""
    return [row(d, "Arkon", "Framers", "Interior framing", (4, 12, 8, 6, 10, 9, 5)[n % 7])
            for n, d in enumerate(weekdays(first, last))]


class Window(unittest.TestCase):
    def test_the_next_five_working_days_skip_the_weekend(self):
        self.assertEqual(L.window(date(2026, 3, 5)), [date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10),
                                                      date(2026, 3, 11), date(2026, 3, 12)])

    def test_and_a_federal_holiday(self):
        # Thu Nov 26 2026 is Thanksgiving.
        self.assertEqual(L.window(date(2026, 11, 19))[-1], date(2026, 11, 27))


class Predict(unittest.TestCase):
    def test_a_steady_crew_is_expected_to_stay_steady(self):
        f = L.predict(steady(8), END)
        (t,) = f["trades"]
        self.assertEqual((t["key"], t["expected"], t["per_day"]), ("framing", 40.0, 8.0))
        self.assertTrue(f["ranged"])
        self.assertLessEqual(t["low"], 40.0)
        self.assertGreaterEqual(t["high"], 40.0)

    def test_the_recent_week_weighs_more_than_the_one_before(self):
        rows = steady(10, last=END - timedelta(days=7)) + steady(5, first=END - timedelta(days=4))
        self.assertEqual(L.predict(rows, END)["trades"][0]["expected"], 5 * (0.6 * 5 + 0.4 * 10))

    def test_no_range_until_there_are_enough_past_misses_to_build_one_from(self):
        f = L.predict(steady(8, last=START + timedelta(days=18)), START + timedelta(days=18))
        self.assertFalse(f["ranged"])
        self.assertLess(f["misses"], L.MIN_MISSES)
        self.assertEqual((f["trades"][0]["low"], f["trades"][0]["high"]), (None, None))
        self.assertEqual(f["trades"][0]["expected"], 40.0)

    def test_only_weeks_that_have_fully_passed_count_as_past_misses(self):
        # 55 working days; the first forecast is possible on day 10 and its week must end by day 55:
        # days 10..50 inclusive = 41 forecasts for the one kind of work.
        self.assertEqual(L.predict(steady(8), END)["misses"], 41)

    def test_the_future_cannot_leak_into_a_forecast(self):
        as_of = date(2026, 4, 17)
        known = [r for r in uneven() if r["date"] <= as_of]
        self.assertEqual(L.predict(uneven(), as_of), L.predict(known, as_of))
        surprise = known + [row(d, "Arkon", "Framers", "Interior framing", 60)
                            for d in weekdays(as_of + timedelta(days=1), END)]
        self.assertEqual(L.predict(surprise, as_of), L.predict(known, as_of))

    def test_a_kind_of_work_not_seen_for_ten_working_days_gets_no_forecast(self):
        rows = steady(8) + [row(START, "MQ", "Steel / Ironwork", "Stairs", 2)]
        self.assertEqual([t["key"] for t in L.predict(rows, END)["trades"]], ["framing"])

    def test_a_range_never_goes_below_zero(self):
        rows = uneven() + [row(d, "B", "HVAC / Mechanical", "Ductwork rough", 1)
                           for n, d in enumerate(weekdays(START, END)) if n % 4 == 0]
        for t in L.predict(rows, END)["trades"]:
            self.assertGreaterEqual(t["low"], 0.0)
            self.assertGreaterEqual(t["high"], t["low"])


class LowerBound(unittest.TestCase):
    def test_it_takes_29_tries_without_a_miss_to_claim_ninety_percent(self):
        self.assertLess(L.lower_bound(28, 28), 0.90)
        self.assertGreaterEqual(L.lower_bound(29, 29), 0.90)

    def test_54_of_61_is_an_89_percent_rate_that_could_be_80(self):
        self.assertAlmostEqual(L.lower_bound(54, 61), 0.80, delta=0.01)

    def test_no_hits_or_no_tries_is_zero(self):
        self.assertEqual((L.lower_bound(0, 10), L.lower_bound(0, 0)), (0.0, 0.0))


class Score(unittest.TestCase):
    def test_a_steady_job_is_forecast_every_time(self):
        sc = L.score(steady(8), END)
        self.assertGreater(sc["tries"], 0)
        self.assertEqual(sc["hits"], sc["tries"])
        self.assertEqual(sc["rate"], 1.0)
        self.assertLess(sc["floor"], 1.0)

    def test_replayed_weeks_do_not_overlap_and_all_ended_on_or_before_the_end(self):
        sc = L.score(uneven(), END)
        stops = sorted({c["as_of"] for c in sc["cases"]})
        self.assertTrue(stops)
        for a, b in zip(stops, stops[1:]):
            self.assertGreaterEqual(len(list(weekdays(a + timedelta(days=1), b))), 5)
        self.assertLessEqual(L.window(stops[-1])[-1], END)

    def test_a_week_the_crew_vanished_is_a_miss_and_is_counted_as_one(self):
        gone = date(2026, 5, 4)
        rows = [r for r in uneven() if not (gone <= r["date"] <= gone + timedelta(days=4))]
        sc = L.score(rows, END)
        missed = [c for c in sc["cases"] if not c["hit"]]
        self.assertTrue(any(c["actual"] == 0 for c in missed))
        self.assertLess(sc["hits"], sc["tries"])
        self.assertEqual(sc["rate"], sc["hits"] / sc["tries"])

    def test_labour_from_a_trade_that_was_not_on_site_before_is_counted_as_unseen(self):
        arrives = date(2026, 5, 4)
        rows = steady(8) + [row(d, "Supero", "Flooring", "Underlayment", 6) for d in weekdays(arrives, arrives + timedelta(days=4))]
        sc = L.score(rows, END)
        self.assertEqual(sc["unseen"], 30.0)

    def test_forecasts_made_before_a_range_exists_are_reported_not_scored(self):
        sc = L.score(steady(8), END)
        self.assertGreater(sc["unranged"], 0)
        self.assertEqual(sc["tries"], len(sc["cases"]))

    def test_no_rows_is_an_empty_scorecard(self):
        sc = L.score([], END)
        self.assertEqual((sc["tries"], sc["rate"], sc["floor"]), (0, None, None))


if __name__ == "__main__":
    unittest.main()
