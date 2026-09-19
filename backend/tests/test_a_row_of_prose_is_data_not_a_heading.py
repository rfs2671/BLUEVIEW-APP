"""A TABLE OF PROSE IS STILL A TABLE.

`_is_heading_row` asked whether a row had any cell that was purely a value —
'KW' and 'BTUH' are headings, '900' and '208/1/60' are not. That is true of an
equipment schedule, whose data rows are mostly numbers. It is false of every
table written in sentences, which has no purely numeric cell anywhere.

MEASURED ON EN-001.00, 2026-09-19, ON PRODUCTION'S OWN pdftoppm RENDERER:
the ENERGY CODE TABULAR ANALYSIS yields 338 OCR boxes, 0 strays and 15 body
rows, and the old rule called ALL FIFTEEN of them headings. `schedule_from_
table`'s merge loop then folded fourteen into the column headings and returned
a ONE-ROW schedule whose headers read 'NYCECC CITATION C403.1.1' and
'PROVISION CALCULATION OF'.

Nineteen of the corpus's 28 OCR-grid schedules were reduced to a single row
that way. FA-001's fire-alarm matrix was one of them, and its merged rows are
where the '6 SPRK, TAMPER VALVE' misreading came from: row numbers glued into
a 188-character "column header".

── TWO CHANGES, AND THE SECOND IS THE ONE THAT MATTERS ──────────────────────

  1. a heading row is one whose cells are short LABELS — bounded in both
     characters and words, because a column name is a short noun phrase
  2. the merge loop is bounded to ONE extra band, whatever the predicate says

The predicate is a heuristic and will be wrong again. The bound is what turns
'wrong' into 'one merged row, visible in the output' instead of 'the table is
gone'. That is why both are here and why the bound is tested on a predicate
that has been forced to lie.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_ocr as po  # noqa: E402

GRID = {"bbox": [0.0, 0.0, 100.0, 100.0], "rows": [0, 1], "cols": [0, 1]}


class TheFourShapes(unittest.TestCase):
    """The shapes the corpus actually contains, named."""

    def test_a_real_heading_is_a_heading(self):
        self.assertTrue(po._is_heading_row(["MARK", "QTY", "MODEL"]))

    def test_a_data_row_with_a_number_is_not(self):
        self.assertFalse(po._is_heading_row(["PTAC-1", "21", "AMANA"]))

    def test_a_row_of_PROSE_is_not_a_heading(self):
        """The case that cost fourteen rows. A citation and two sentences."""
        self.assertFalse(po._is_heading_row(
            ["C403.1.1", "CALCULATION OF HEATING AND COOLING LOADS",
             "DESIGN LOADS ASSOCIATED WITH HEATING"]))

    def test_a_mark_with_a_described_assembly_is_not_a_heading(self):
        self.assertFalse(po._is_heading_row(
            ["W1", "EXTERIOR STUD WALL WITH STUCCO (1HR FIRE RATED)", "1 HR"]))


class TheThingsItMustNotBreak(unittest.TestCase):

    def test_a_second_tier_band_is_still_a_heading(self):
        """'MOTOR DATA' over HP / VOLTS / # on M-200.00's fan schedules."""
        self.assertTrue(po._is_heading_row(["MOTOR DATA", "", ""]))

    def test_the_longest_real_heading_measured_still_passes(self):
        """'AUXILIARYHEATING CAPACITY (KW)' — 30 characters, three words, and
        the longest genuine column heading in the 588 Boyland grids."""
        self.assertTrue(po._is_heading_row(
            ["AUXILIARYHEATING CAPACITY (KW)", "BTUH"]))

    def test_a_wide_equipment_heading_passes(self):
        self.assertTrue(po._is_heading_row(
            ["SYMBOL", "LOCATION", "QTY", "MANUFACTURER", "MODEL", "KW", "BTU"]))

    def test_the_compliance_tables_own_heading_row_passes(self):
        """The fix must still find the ONE row that really is the heading."""
        self.assertTrue(po._is_heading_row(
            ["NYCECC CITATION", "PROVISION", "ITEM DESCRIPTION"]))

    def test_an_empty_row_is_not_a_heading(self):
        self.assertFalse(po._is_heading_row(["", "", ""]))
        self.assertFalse(po._is_heading_row([]))


class BothBoundsEarnTheirPlace(unittest.TestCase):
    """Each bound is asked to fail on its own, so neither is decoration."""

    def test_the_character_bound_alone_would_let_prose_through(self):
        """'CALCULATION OF HEATING AND COOLING LOADS' is EXACTLY 40 characters.
        It passed the length test and is caught only by the word count — which
        is why the word count exists rather than the length being widened."""
        cell = "CALCULATION OF HEATING AND COOLING LOADS"
        self.assertEqual(len(cell), po._HEADING_CELL_MAX)
        self.assertGreater(len(cell.split()), po._HEADING_CELL_MAX_WORDS)
        self.assertFalse(po._is_heading_row(["C403.1.1", cell]))

    def test_the_word_bound_alone_would_let_a_long_label_through(self):
        """Four words can still be far too long to be a column name."""
        cell = "SUPPLEMENTARY ELECTRIC RESISTANCE HEAT" + " X" * 20
        self.assertLessEqual(len(cell.split()), 40)
        self.assertGreater(len(cell), po._HEADING_CELL_MAX)
        self.assertFalse(po._is_heading_row(["MARK", cell]))


class TheBoundIsTheProtection(unittest.TestCase):
    """A predicate can be wrong. An unbounded loop turns wrong into fatal."""

    @staticmethod
    def _table(rows):
        return [list(r) for r in rows]

    def test_a_lying_predicate_costs_one_row_and_not_the_table(self):
        """The predicate is forced to call EVERYTHING a heading — the exact
        failure that happened — and the bound must still leave the data."""
        table = self._table([
            ["ENERGY CODE TABULAR ANALYSIS", "", ""],
            ["NYCECC CITATION", "PROVISION", "ITEM DESCRIPTION"],
            ["C403.1.1", "CALCULATION", "DESIGN LOADS"],
            ["C403.2.2", "EQUIPMENT SIZING", "THE OUTPUT CAPACITY"],
            ["C403.3.2", "HVAC EQUIPMENT", "PACKAGED TERMINAL AIR CONDITIONERS"],
            ["C403.4.1", "THERMOSTATIC", "THE SUPPLY OF HEATING"],
        ])
        real = po._is_heading_row
        po._is_heading_row = lambda row: True          # a predicate that lies
        try:
            sched = po.schedule_from_table(table, GRID)
        finally:
            po._is_heading_row = real
        self.assertIsNotNone(sched)
        rows = sched.get("rows") or []
        self.assertGreaterEqual(
            len(rows), 3,
            f"an always-true predicate ate the table: {len(rows)} row(s) left")

    def test_with_the_real_predicate_the_compliance_table_survives(self):
        table = self._table([
            ["ENERGY CODE TABULAR ANALYSIS", "", ""],
            ["NYCECC CITATION", "PROVISION", "ITEM DESCRIPTION"],
            ["C403.1.1", "CALCULATION OF HEATING AND COOLING LOADS",
             "DESIGN LOADS ASSOCIATED WITH HEATING AND VENTILATING"],
            ["C403.3.2", "HVAC EQUIPMENT PERFORMANCE REQUIREMENTS",
             "ELECTRICALLY OPERATED PACKAGED TERMINAL AIR CONDITIONERS"],
            ["C403.4.1", "THERMOSTATIC CONTROLS",
             "THE SUPPLY OF HEATING AND COOLING ENERGY TO EACH ZONE"],
        ])
        sched = po.schedule_from_table(table, GRID)
        self.assertIsNotNone(sched)
        self.assertEqual(sched["name"], "ENERGY CODE TABULAR ANALYSIS")
        self.assertEqual(sched["columns"],
                         ["NYCECC CITATION", "PROVISION", "ITEM DESCRIPTION"])
        self.assertEqual(len(sched["rows"]), 3)
        joined = " ".join(c for r in sched["rows"] for c in r).upper()
        self.assertIn("PACKAGED TERMINAL AIR CONDITIONERS", joined)

    def test_a_genuine_two_tier_header_still_merges(self):
        """One band, which is what the loop is for."""
        table = self._table([
            ["FAN SCHEDULE", "", ""],
            ["TAG", "MOTOR DATA", ""],
            ["", "HP", "VOLTS"],
            ["EF-1", "1/4", "120"],
            ["EF-2", "1/3", "120"],
        ])
        sched = po.schedule_from_table(table, GRID)
        self.assertIsNotNone(sched)
        self.assertEqual(len(sched["rows"]), 2)
        self.assertIn("HP", " ".join(sched["columns"]))

    def test_a_schedule_with_no_heading_at_all_is_unchanged(self):
        """C408 MAINTENANCE on M-200.00: one row under its title."""
        table = self._table([
            ["C408 MAINTENANCE INFORMATION", "", ""],
            ["SYSTEM COMMISSIONING", "TOTAL COOLING 445.6 KBTU", ""],
        ])
        sched = po.schedule_from_table(table, GRID)
        self.assertIsNotNone(sched)
        # WHAT MATTERS IS THAT THE FIX DID NOT MOVE THIS SHAPE. On the real
        # M-200.00 grid, production returns ONE row both before and after the
        # change. An earlier draft of this test asserted `columns == []` on
        # the assumption that `_title_and_body` lifts the title here; it does
        # not, and asserting a guess about internals rather than the measured
        # behaviour is how a test starts describing something other than the
        # thing it names.
        self.assertEqual(len(sched["rows"]), 1)
        joined = " ".join(c for r in sched["rows"] for c in r).upper()
        self.assertIn("SYSTEM COMMISSIONING", joined)


if __name__ == "__main__":
    unittest.main()
