"""A DRAWING LIST IS NOT THE DRAWING.

Asked 'door schedule', retrieval returned T-001.01 — the DRAWING LIST, whose
row happens to read 'A-400 DOOR SCHEDULE' — ahead of A-400.00, which IS the
door schedule. Asked 'vent fan', the GENERAL ABBREVIATIONS table on M-001.00
led. Both were live complaints from a GC on 2026-09-19: he got a width and no
height for the doors, and '3 vent fans' for a building with ten-plus units.

This is not a ranking problem and is not fixed by scores. An index
LEGITIMATELY matches the words, because it lists the things the set contains.
It is the KIND of record that disqualifies it from leading.

── MEASURED BEFORE IT WAS BUILT, AND AFTER ─────────────────────────────────

Before: of 26 cases, 3 had an index anywhere in the result set and ZERO had
one leading — so the rule was free, and it changed no outcome.

That is also why it looked pointless. The failure the GC hit was on subjects
the suite did not ask about, which is the larger finding: four of seven live
complaints landed outside the suite entirely. The cases were added first,
`door-size` and `ceiling-height` both failed with T-001.01 LEADING, and then
this rule made `door-size` pass and moved `ceiling-height`'s lead from the
drawing list to A-500.00 — where it still fails, correctly, because ceiling
heights are an EXTRACTION gap and not a retrieval one.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as ps  # noqa: E402


def sched(name, rows=None, quote=""):
    return {"record_type": "schedule", "tier": "schedule_cell",
            "page_id": "p1", "sheet_number": "T-001.01",
            "quote": quote or name,
            "payload": {"name": name, "rows": rows or []}}


DOOR = {"record_type": "schedule", "tier": "schedule_cell", "page_id": "p2",
        "sheet_number": "A-400.00",
        "quote": "INTERIOR DOOR SCHEDULE SIZE 3'-0\" X 7'-0\"",
        "payload": {"name": "INTERIOR DOOR SCHEDULE",
                    "rows": [["A", "3'-0\" X 7'-0\""], ["B", "3'-0\" X 7'-0\""]]}}


class AnIndexIsRecognisedByWhatItIs(unittest.TestCase):

    def test_a_drawing_list_by_name(self):
        self.assertTrue(ps.is_index_record(sched("DRAWING LIST")))

    def test_a_sheet_list_by_name(self):
        self.assertTrue(ps.is_index_record(sched("Sheet List Table")))

    def test_an_abbreviations_table_by_name(self):
        self.assertTrue(ps.is_index_record(sched("GENERAL ABBREVIATIONS")))

    def test_a_table_whose_rows_are_sheet_numbers(self):
        """Whatever it calls itself. No equipment schedule on 588 Boyland
        keys its rows by sheet number, and every index does."""
        self.assertTrue(ps.is_index_record(sched("CONTENTS", rows=[
            ["T-001.00", "COVER SHEET"],
            ["A-100.00", "FIRST FLOOR PLAN"],
            ["A-400.00", "WINDOW SCHEDULE"],
            ["M-200.00", "MECHANICAL SCHEDULES"]])))

    def test_an_equipment_schedule_is_not_an_index(self):
        self.assertFalse(ps.is_index_record(DOOR))

    def test_a_schedule_with_a_couple_of_sheet_refs_is_not_an_index(self):
        """A REMARKS column pointing at two sheets does not make a schedule
        an index. The share has to be most of the first column."""
        self.assertFalse(ps.is_index_record(sched("FAN SCHEDULE", rows=[
            ["EF-1", "SEE A-400.00"],
            ["EF-2", "NUTONE"],
            ["SAF-1", "GREENHECK"],
            ["SAF-2", "SEE M-200.00"]])))

    def test_too_few_rows_to_judge(self):
        self.assertFalse(ps.is_index_record(sched("LIST", rows=[
            ["A-100.00", "x"], ["A-101.00", "y"]])))

    def test_a_record_with_no_payload_survives(self):
        self.assertFalse(ps.is_index_record({"quote": "PTAC-1 count 21"}))
        self.assertFalse(ps.is_index_record({}))


class TheIndexIsDroppedWhenSomethingElseAnswered(unittest.TestCase):

    def test_the_door_schedule_leads_over_the_drawing_list(self):
        got = ps.drop_indexes([sched("DRAWING LIST"), DOOR])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["sheet_number"], "A-400.00")

    def test_several_indexes_all_go(self):
        got = ps.drop_indexes([sched("DRAWING LIST"),
                               sched("GENERAL ABBREVIATIONS"), DOOR])
        self.assertEqual([r["sheet_number"] for r in got], ["A-400.00"])

    def test_nothing_else_matched_keeps_the_pointer(self):
        """A question whose ONLY match is the drawing list has not been
        answered — but dropping it to nothing would lose 'Closest: T-001.01',
        and the render decides what to say, not this."""
        idx = sched("DRAWING LIST")
        self.assertEqual(ps.drop_indexes([idx]), [idx])

    def test_an_empty_set_stays_empty(self):
        self.assertEqual(ps.drop_indexes([]), [])
        self.assertEqual(ps.drop_indexes(None), [])

    def test_order_is_otherwise_untouched(self):
        a = dict(DOOR, sheet_number="A-400.00")
        b = dict(DOOR, sheet_number="A-401.00")
        self.assertEqual([r["sheet_number"] for r in ps.drop_indexes([a, b])],
                         ["A-400.00", "A-401.00"])


class TheRuleIsKeyedOnKindNotOnScore(unittest.TestCase):
    """The distinction that made this worth building rather than tuning."""

    def test_an_index_that_matches_every_term_is_still_dropped(self):
        perfect = sched("DRAWING LIST",
                        quote="DRAWING LIST DOOR SCHEDULE A-400 DOOR SCHEDULE")
        got = ps.drop_indexes([perfect, DOOR])
        self.assertEqual([r["sheet_number"] for r in got], ["A-400.00"])

    def test_and_a_weak_non_index_survives(self):
        weak = {"record_type": "text", "tier": "text_layer", "page_id": "p3",
                "sheet_number": "A-999.00", "quote": "DOOR"}
        got = ps.drop_indexes([sched("DRAWING LIST"), weak])
        self.assertEqual([r["sheet_number"] for r in got], ["A-999.00"])


if __name__ == "__main__":
    unittest.main()
