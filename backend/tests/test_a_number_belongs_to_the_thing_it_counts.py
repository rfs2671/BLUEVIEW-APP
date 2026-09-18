"""A QUANTITY MUST COME FROM A RECORD ABOUT THE THING IT COUNTS.

`answer_is_grounded` asked whether a number appeared in ANY returned record.
Measured on 588 Thomas S Boyland Street on 2026-09-18, with the contested
PTAC-2 record correctly excluded from vouching, the gate still passed
"There are 9 PTAC-2 units":

  - on "how many PTAC-2 units are there", the 9 came from a DCDA & RPZ
    backflow installation schedule's unverified cells, and the 6 from a
    ZONING ANALYSIS table
  - on "number of PTAC-2", the 9 came from the Sheet List Table — a sheet index

None of those records is about PTAC-2. They contained the digit, and that was
the whole test. So the contested-cell rule (#602) was doing its work and being
defeated downstream by digit collision, and any invented single digit passed
whenever some co-returned record happened to contain it.

── WHY COUNT INTENT AND NOT EVERYTHING ───────────────────────────────────────

Measured before building, on the ten suite cases that state a number: eight
bind to a mark or a schedule, and the two that do not — a 42" parapet height
and a 1,970 sf recreation area — are both ATTRIBUTE cases, where the number
belongs to a quoted note rather than to any mark. Binding those would refuse
two true answers to catch nothing.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as ps  # noqa: E402


def _element(tag, quote, page="p1", sheet="M-200.00", **payload):
    return {"record_type": "element", "tier": "ocr_grid_cell", "page_id": page,
            "sheet_number": sheet, "quote": quote,
            "payload": {"tag": tag, **payload}}


def _schedule(name, quote, page="p2", sheet="Z-001.00", **payload):
    return {"record_type": "schedule", "tier": "schedule_cell", "page_id": page,
            "sheet_number": sheet, "quote": quote,
            "payload": {"name": name, **payload}}


#: The shape of the real result set, reduced to what decides the outcome.
BOYLAND = [
    _element("PTAC-2", "PTAC-2 - QTY on the sheet, readings disagree",
             count_contested=True,
             count_readings=[{"value": 6}, {"value": 9}]),
    _element("PTAC-1", "PTAC-1 - count 21", count_if_stated=21),
    _element("PTAC-3", "PTAC-3 - count 11", count_if_stated=11),
    _schedule("ZONING ANALYSIS",
              "ZONING ANALYSIS: | PERMITTED | PROPOSED | 6 DWELLING UNITS"),
    _schedule("PROPOSED DCDA & RPZ INSTALLATION",
              "PROPOSED DCDA & RPZ INSTALLATION AT: 588 THOMAS S. BOYLAND",
              unverified_cells=["9", "2 INCH"]),
    _schedule("Sheet List Table",
              "Sheet List Table Sheet Number | Sheet Title | 9 | A-105.01"),
]


class TheDigitCollisionThatDefeatedTheContestedRule(unittest.TestCase):

    def test_the_backflow_schedule_may_not_vouch_for_a_ptac_count(self):
        ok, bad = ps.answer_is_grounded(
            "There are 9 PTAC-2 units.", BOYLAND, intent="count")
        self.assertFalse(ok, "a backflow schedule vouched for a PTAC quantity")
        self.assertEqual(bad, ["9"])

    def test_the_zoning_table_may_not_vouch_either(self):
        ok, bad = ps.answer_is_grounded(
            "There are 6 PTAC-2 units.", BOYLAND, intent="count")
        self.assertFalse(ok)
        self.assertEqual(bad, ["6"])

    def test_this_is_what_the_union_used_to_allow(self):
        """The old behaviour, kept as a named comparison so the change cannot
        be quietly undone: under the union both numbers pass."""
        for n in ("6", "9"):
            ok, _bad = ps.answer_is_grounded(
                f"There are {n} PTAC-2 units.", BOYLAND)
            self.assertTrue(ok, f"the union was expected to allow {n}")


class ATrueCountStillPasses(unittest.TestCase):

    def test_a_mark_vouches_for_its_own_quantity(self):
        ok, bad = ps.answer_is_grounded(
            "There are 21 PTAC-1 units.", BOYLAND, intent="count")
        self.assertTrue(ok, f"a true count was refused: {bad}")

    def test_several_marks_in_one_sentence_each_keep_their_own(self):
        ok, bad = ps.answer_is_grounded(
            "PTAC-1: 21, PTAC-2: readings disagree, PTAC-3: 11.",
            BOYLAND, intent="count")
        self.assertTrue(ok, f"a true multi-mark answer was refused: {bad}")

    def test_a_colon_binds_a_label_to_its_value(self):
        """'PTAC-1: 21' is ONE claim. Splitting on the colon put the mark in
        one clause and its quantity in the next, and refused the true answer —
        the first thing the smoke test caught."""
        self.assertIn("PTAC-1: 21", ps._clauses("PTAC-1: 21, PTAC-3: 11")[0])

    def test_a_citation_is_not_a_claim(self):
        ok, bad = ps.answer_is_grounded(
            "See M-200.00 for the schedule.", BOYLAND, intent="count")
        self.assertTrue(ok, f"a sheet number was read as a quantity: {bad}")

    def test_a_record_vouches_for_its_own_subject(self):
        ok, _bad = ps.answer_is_grounded(
            "The zoning analysis shows 6 dwelling units.", BOYLAND,
            intent="count")
        self.assertTrue(ok)


class OneMarkMayNotBorrowAnothersNumber(unittest.TestCase):

    def test_a_number_does_not_travel_between_marks(self):
        ok, bad = ps.answer_is_grounded(
            "PTAC-1: 21, PTAC-3: 21.", BOYLAND, intent="count")
        self.assertFalse(ok, "PTAC-3 borrowed PTAC-1's quantity")
        self.assertEqual(bad, ["21"])

    def test_a_quantity_naming_nothing_is_refused(self):
        """A bare quantity with no subject is the shape of an invented count."""
        ok, bad = ps.answer_is_grounded(
            "There are 9 of them.", BOYLAND, intent="count")
        self.assertFalse(ok)
        self.assertEqual(bad, ["9"])


class EveryOtherIntentKeepsTheUnion(unittest.TestCase):
    """Of ten suite cases stating a number, the two that bind to no mark are
    both attribute cases. Binding them would refuse true answers to catch
    nothing, so the union stands everywhere except a count."""

    def test_an_attribute_answer_is_not_bound(self):
        for intent in ("attribute", "existence", "location", "identify",
                       "geometry", ""):
            ok, _bad = ps.answer_is_grounded(
                "The parapet is 9 inches.", BOYLAND, intent=intent)
            self.assertTrue(ok, f"intent {intent!r} was bound like a count")

    def test_only_the_exact_word_switches_the_rule(self):
        for spelling in ("count", "COUNT", " Count "):
            ok, _bad = ps.answer_is_grounded(
                "There are 9 of them.", BOYLAND, intent=spelling)
            self.assertFalse(ok, f"{spelling!r} did not select the bound rule")


class ARowNumberIsNotASubject(unittest.TestCase):
    """The second bug the live corpus caught, and the worst kind: CIRCULAR.

    Grids number their rows, so a schedule's `row[0]` is often just '1', '2',
    '9'. Indexed as an ident, the clause "There are 9 PTAC-2 units" NAMES the
    ident '9', which holds the value 9 — and the number vouches for itself.
    Measured on 'number of PTAC-2', where a numbered row let both 6 and 9 back
    through after row indexing was added.

    This is the FA-001 mistake in a second place: there a row index merged into
    a description cell and was read as a sprinkler count.
    """

    SHEET_LIST = [
        {"record_type": "schedule", "tier": "schedule_cell", "page_id": "p3",
         "sheet_number": "T-001.00", "quote": "Sheet List Table",
         "payload": {"name": "Sheet List Table",
                     "rows": [["1", "T-001.00", "TITLE SHEET"],
                              ["9", "A-105.01", "FOURTH FLOOR PLAN"]]}},
    ]

    def test_a_numbered_row_never_becomes_an_ident(self):
        by_ident = ps._values_by_ident(self.SHEET_LIST)
        self.assertNotIn("9", by_ident)
        self.assertNotIn("1", by_ident)
        self.assertIn("SHEET LIST TABLE", by_ident)

    def test_the_digit_cannot_vouch_for_itself(self):
        ok, bad = ps.answer_is_grounded(
            "There are 9 PTAC-2 units.", self.SHEET_LIST, intent="count")
        self.assertFalse(ok, "a row number vouched for a quantity")
        self.assertEqual(bad, ["9"])

    def test_an_identless_name_is_never_matched(self):
        self.assertEqual(ps._idents_named_in("there are 9 of them", ["9"]), [])


class AScheduleIsAboutEveryMarkItLists(unittest.TestCase):
    """Indexing a schedule under its NAME alone refused true answers.

    Asked "number of PTAC-2", retrieval returns the ROOMS PTAC UNITS SCHEDULE
    but not the individual PTAC-1 element — so "PTAC-1: 21" named a thing no
    returned record was indexed under, though 21 is printed in PTAC-1's own
    row. 14 true answers were refused that way before rows were indexed.
    """

    SCHED = [
        {"record_type": "schedule", "tier": "ocr_grid_cell", "page_id": "p1",
         "sheet_number": "M-200.00", "quote": "ROOMS PTAC UNITS SCHEDULE",
         "payload": {"name": "ROOMS PTAC UNITS SCHEDULE",
                     "rows": [["PTAC-1", "21", "AMANA"],
                              ["PTAC-2", "(readings disagree", "AMANA"],
                              ["PTAC-3", "11", "AMANA"]]}},
    ]

    def test_a_mark_is_vouched_for_by_its_own_row(self):
        ok, bad = ps.answer_is_grounded(
            "PTAC-1: 21.", self.SCHED, intent="count")
        self.assertTrue(ok, f"a mark's own row did not vouch for it: {bad}")

    def test_a_mark_may_not_borrow_the_row_below(self):
        """Row by row, not grid-wide — otherwise PTAC-3 borrows PTAC-1's 21,
        a smaller hole than the one being closed but the same kind."""
        ok, bad = ps.answer_is_grounded(
            "PTAC-3: 21.", self.SCHED, intent="count")
        self.assertFalse(ok, "a mark borrowed another row's quantity")
        self.assertEqual(bad, ["21"])

    def test_the_contested_cell_keeps_its_digits_out_of_the_grid(self):
        """What makes row indexing SAFE: PTAC-2's QTY was written as text, so
        the schedule carries 21 and 11 and neither 6 nor 9. If a contested cell
        ever wrote a number instead, this would leak."""
        by_ident = ps._values_by_ident(self.SCHED)
        self.assertEqual(by_ident.get("PTAC-2", set()) & {"6", "9"}, set())
        self.assertIn("21", by_ident["PTAC-1"])
        self.assertIn("11", by_ident["PTAC-3"])


class AContestedCellVouchesForNothingUnderEitherRule(unittest.TestCase):

    def test_the_contested_record_is_excluded_from_its_own_marks_values(self):
        by_ident = ps._values_by_ident(BOYLAND)
        self.assertNotIn("6", by_ident.get("PTAC-2", set()))
        self.assertNotIn("9", by_ident.get("PTAC-2", set()))
        self.assertIn("21", by_ident.get("PTAC-1", set()))


if __name__ == "__main__":
    unittest.main()
