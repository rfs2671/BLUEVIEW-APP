"""The progress board: how far each kind of work has got, floor by floor, from
the filed daily logs, with an ESTIMATED percent per trade.

Operator, 2026-11-18: "schedule should be automatic based on photos ... from
progress so far explained in plain english with charts showing the actual
progress". Ruled: a trade-by-floor stage board plus an estimated percent per
trade, labelled as estimated from site records.

The rows below are SYNTHETIC, shaped like 588 Boyland's real daily-log rows
(Arkon Builders' "Ceiling drops, interior framing, sheet rack" is quoted from
its Nov 2026 logs: one company, two kinds of work).
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

END = date(2026, 11, 17)


def row(d, company, trade, work, where, **kw):
    return {"date": d, "company": company, "key": company.lower(), "trade": trade, "work": work,
            "where": where, "floors": S.floors_of_text(where), "photos": [], "work_trades": kw.get("work_trades")}


def days(first, last):
    d = first
    while d <= last:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


class WhatKindOfWork(unittest.TestCase):
    def test_one_line_naming_two_kinds_of_work_is_two(self):
        fams = S.families_of(row(END, "Arkon Builders", "Framers", "Ceiling drops, interior framing, sheet rack",
                                 "floors 1-4"))
        self.assertEqual([f for f, _ph in fams], ["framing", "framing", "drywall"])

    def test_taping_compound_and_paint_are_their_own_work(self):
        for text, fam in (("Taping and compound", "taping"), ("spackle 2nd coat", "taping"),
                          ("Prime and paint corridors", "painting"), ("hang sheetrock", "drywall"),
                          ("metal stud framing", "framing"), ("Underlayment, waterproof", "flooring"),
                          ("Spray foam", "insulation"), ("Domestic water rough", "plumbing"),
                          ("Cable pull, data", "low_voltage"), ("Ductwork rough", "hvac")):
            self.assertEqual(S.families_of(row(END, "X", "", text, "floor 2"))[0][0], fam, text)

    def test_a_line_with_no_trade_words_is_the_crews_trade(self):
        self.assertEqual(S.families_of(row(END, "Quality Plumbing", "Plumber", "Floor 3 bathrooms", "floor 3"))[0][0],
                         "plumbing")

    def test_the_daily_logs_recorded_work_trades_win_over_the_crews(self):
        r = row(END, "Arkon Builders", "Framers", "Corridor", "floor 2", work_trades=["Drywall"])
        self.assertEqual(S.families_of(r)[0][0], "drywall")

    def test_a_cleaning_crew_is_never_progress(self):
        self.assertEqual(S.families_of(row(END, "Echo", "Cleaning", "House cleaning, stucco", "floors 1-4")), [])

    def test_a_floor_number_is_not_flooring(self):
        self.assertEqual(S.families_of(row(END, "Power Direct", "Electrician", "Floor 4 wiring", "floor 4"))[0][0],
                         "electrical")


class TheBoard(unittest.TestCase):
    def board(self, rows, end=END):
        return S.build(rows, end=end, period_start=end - timedelta(days=13))

    def test_worked_this_week_is_in_progress_and_counts_half(self):
        rows = [row(d, "Arkon Builders", "Framers", "Interior framing", "floors 1-4")
                for d in days(date(2026, 11, 4), END)]
        b = self.board(rows)
        fr = b["trades"]["framing"]
        self.assertEqual(b["floors"], [1, 2, 3, 4])
        self.assertEqual({f: c["stage"] for f, c in fr["cells"].items()}, {1: S.ACTIVE, 2: S.ACTIVE, 3: S.ACTIVE, 4: S.ACTIVE})
        self.assertEqual(fr["estimate"], 50)

    def test_the_next_trade_following_on_a_floor_marks_the_first_complete(self):
        rows = [row(date(2026, 10, 20), "Arkon", "Framers", "Interior framing", "floors 1-2"),
                row(date(2026, 10, 27), "Arkon", "Framers", "Interior framing", "floor 2"),
                *[row(d, "Arkon", "Framers", "hang sheetrock", "floor 1")
                  for d in (date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5))],
                row(date(2026, 11, 16), "Arkon", "Framers", "Interior framing", "floor 3")]
        fr = self.board(rows)["trades"]["framing"]
        self.assertEqual(fr["cells"][1]["stage"], S.DONE)          # sheetrock followed 3 days, framing gone 4 weeks
        self.assertEqual(fr["cells"][2]["stage"], S.STARTED)       # worked, nothing followed, not this week
        self.assertEqual(fr["cells"][3]["stage"], S.ACTIVE)
        # floors 1..3 known: (100 + 50 + 50) / 3 = 66.7 -> nearest 5
        self.assertEqual(fr["estimate"], 65)

    def test_a_trade_back_on_the_floor_this_week_is_not_complete(self):
        rows = [row(date(2026, 11, 3), "Arkon", "Framers", "Interior framing", "floor 1"),
                row(date(2026, 11, 5), "Arkon", "Framers", "hang sheetrock", "floor 1"),
                row(date(2026, 11, 16), "Arkon", "Framers", "Interior framing", "floor 1")]
        self.assertEqual(self.board(rows)["trades"]["framing"]["cells"][1]["stage"], S.ACTIVE)

    def test_the_words_complete_or_done_mark_a_floor_complete(self):
        rows = [row(date(2026, 11, 2), "Quality Plumbing", "Plumber", "Rough plumbing complete", "floor 2")]
        self.assertEqual(self.board(rows)["trades"]["plumbing"]["cells"][2]["stage"], S.DONE)

    def test_a_not_yet_complete_is_not_complete(self):
        rows = [row(date(2026, 11, 2), "Quality Plumbing", "Plumber", "rough not complete", "floor 2")]
        self.assertEqual(self.board(rows)["trades"]["plumbing"]["cells"][2]["stage"], S.STARTED)

    def test_floors_nobody_reached_count_zero(self):
        rows = [row(END, "Arkon", "Framers", "Interior framing", "floors 1-4"),
                row(END, "Arkon", "Framers", "hang sheetrock", "floor 1")]
        dw = self.board(rows)["trades"]["drywall"]
        self.assertEqual(dw["cells"][2]["stage"], S.NONE)
        self.assertEqual(dw["estimate"], 15)               # 50 / 4 = 12.5 -> 15 (half up)

    def test_work_with_no_floor_has_a_stage_but_no_estimate(self):
        rows = [row(END, "J&P Construction", "Stucco", "Stucco", "Outer bldg"),
                row(END, "Arkon", "Framers", "Interior framing", "floors 1-2")]
        fa = self.board(rows)["trades"]["facade"]
        self.assertEqual(fa["elsewhere"]["stage"], S.ACTIVE)
        self.assertIsNone(fa["estimate"])

    def test_only_records_up_to_the_end_of_the_period(self):
        rows = [row(END + timedelta(days=1), "Arkon", "Framers", "Interior framing", "floor 1")]
        self.assertEqual(self.board(rows)["trades"], {})

    def test_the_board_is_in_building_order(self):
        rows = [row(END, "A", "Painter", "paint", "floor 1"), row(END, "B", "Framers", "framing", "floor 1"),
                row(END, "C", "Plumber", "rough", "floor 1")]
        self.assertEqual(list(self.board(rows)["trades"]), ["framing", "plumbing", "painting"])

    def test_who_did_it_is_kept(self):
        rows = [row(END, "Arkon Builders", "Framers", "sheet rack", "floor 1")]
        self.assertEqual(self.board(rows)["trades"]["drywall"]["companies"], ["Arkon Builders"])


class OneDayOfTheNextTradeIsNotEnough(unittest.TestCase):
    def test_a_single_day_of_sheetrock_does_not_close_in_the_ductwork(self):
        rows = [row(date(2026, 10, 20), "BreezCo", "HVAC / Mechanical", "Ductwork rough", "floor 2"),
                row(date(2026, 11, 3), "Arkon", "Framers", "hang sheetrock", "floor 2")]
        b = S.build(rows, end=END)
        self.assertEqual(b["trades"]["hvac"]["cells"][2]["stage"], S.STARTED)
        self.assertEqual(b["trades"]["hvac"]["label"], "HVAC / ductwork rough-in")

    def test_all_areas_is_every_floor_named(self):
        rows = [row(END, "Arkon", "Framers", "Interior framing", "floors 1-3"),
                row(END, "Echo2", "Insulation", "Spray foam", "All areas")]
        cells = S.build(rows, end=END)["trades"]["insulation"]["cells"]
        self.assertEqual(set(cells), {1, 2, 3})
        self.assertTrue(all(c["stage"] == S.ACTIVE for c in cells.values()))


class NotFloorByFloor(unittest.TestCase):
    def test_a_foundation_is_the_buildings_not_a_share_of_floors(self):
        # 588: "Plumbing, excavation, underground plumbing · floors 1, 4" read as
        # excavation on floors 1 and 4 -- "25%" of a foundation.
        rows = [row(END, "AAZ", "Excavation", "Excavation, footings", "floor 1"),
                row(END, "Arkon", "Framers", "Interior framing", "floors 1-4")]
        b = S.build(rows, end=END)
        ex = b["trades"]["excavation"]
        self.assertIsNone(ex["estimate"])
        self.assertEqual(ex["elsewhere"]["stage"], S.ACTIVE)
        self.assertTrue(all(c["stage"] == S.NONE for c in ex["cells"].values()))

    def test_ground_floor_and_one_floor_are_floor_1_but_four_floors_is_a_count(self):
        self.assertEqual(S.floors_of_text("Ground floor"), [1])
        self.assertEqual(S.floors_of_text("1 floor"), [1])
        self.assertEqual(S.floors_of_text("4 floors"), [])
        self.assertEqual(S.floors_of_text("First floor"), [1])
        self.assertEqual(S.floors_of_text("third fl"), [3])


class TheMostWorkedFirst(unittest.TestCase):
    def test_the_periods_work_is_ordered_by_days_worked(self):
        rows = ([row(d, "Arkon", "Framers", "Interior framing", "floor 1") for d in days(date(2026, 11, 4), END)]
                + [row(END, "24/7 Plumbing", "Water Main", "Excavation", "floor 1")])
        b = S.build(rows, end=END, period_start=date(2026, 11, 4))
        self.assertEqual(b["worked_in_period"][0], "framing")


class OverTime(unittest.TestCase):
    def test_the_estimate_week_by_week_never_reads_the_future(self):
        rows = [row(date(2026, 10, 20), "Arkon", "Framers", "Interior framing", "floors 1-2"),
                *[row(date(2026, 11, n), "Arkon", "Framers", "hang sheetrock", "floors 1-2") for n in (3, 4, 5)],
                row(END, "Arkon", "Framers", "Interior framing", "floors 3-4")]
        b = S.build(rows, end=END, period_start=date(2026, 11, 4))
        weeks = b["history"]
        self.assertEqual(weeks[-1]["end"], END)
        self.assertTrue(all(w["end"] <= END for w in weeks))
        fr = [w["estimates"].get("framing") for w in weeks]
        # Counted over the floors known at the end (1-4): Oct 20, floors 1-2 in
        # progress -> 25; by Nov 17, 1-2 done and 3-4 active -> 75. A floor named
        # later never makes an earlier week look further along.
        self.assertEqual(fr[-1], 75)
        self.assertEqual(fr[0], 25)
        self.assertEqual(fr, sorted(fr))


class InPlainEnglish(unittest.TestCase):
    def test_the_sentences_say_stage_and_floors_and_never_a_bare_percent(self):
        rows = [row(date(2026, 10, 20), "Arkon Builders", "Framers", "Interior framing", "floors 1-2"),
                *[row(date(2026, 11, n), "Arkon Builders", "Framers", "hang sheetrock", "floors 1-2")
                  for n in (3, 4, 5)],
                row(END, "Arkon Builders", "Framers", "Interior framing", "floors 3-4")]
        b = S.build(rows, end=END, period_start=date(2026, 11, 4))
        line = S.sentence(b["trades"]["framing"], b["floors"])
        self.assertIn("appears complete on floors 1–2", line)
        self.assertIn("in progress on floors 3–4", line)
        self.assertIn("Arkon Builders", line)
        self.assertNotIn("%", line)


if __name__ == "__main__":
    unittest.main()
