"""A.0.1 IS A SHEET NUMBER, AND NOT READING IT COST A WHOLE SET.

`588 THOMAS BOYLAND ST SET_UPDATED .pdf` numbers all 44 of its pages A.0.1
through A.1.7 — ordinary NYC architectural numbering. `SHEET_ID_RE` required
a DASH and exactly three digits, so it matched none of them. The chain that
followed:

    the parser cannot read the scheme
      -> 38 of 44 pages look like they carry no sheet number
        -> `looks_combined` fires
          -> the discipline-level coverage check passes ({A} is covered by
             the AR sets)
            -> the whole file is SKIPPED as a duplicate

and the sections carrying the building's ceiling heights reached nothing. The
skip recorded `covered_by: ['AR - 6.9.26 (Gas change).pdf',
'AR - 8.18.26.pdf']` as fact; measured 2026-09-20, those files contain ZERO
CEILING-with-a-dimension hits. The claim was never tested.

── THE RULE IS STRUCTURAL ──────────────────────────────────────────────────

Letters, a separator, digit groups. The LEADING LETTER does the work: it is
what separates a sheet number from the code citations (110.3.4), zoning
figures (1704.13), phone numbers (212-961) and dates (08-24) that share the
shape and are printed in the same title blocks.

Not a list of schemes, and NOT widened speculatively: `A101`, with no
separator, appears in no set here and is left out. One project with two or
three consultants cannot establish what exists in the wild, and the honest
move was to fix what is in front of us and stop.

── THE FINDER AND THE VALIDATOR NOW AGREE ──────────────────────────────────

They did not. `_SHEET_NUMBER_RE` had `-?` optional and allowed four letters,
so it accepted `IIA1` (a construction class), `R19` and `R11.5` (insulation
values), `I1`, `P5` and `A101` — none of them sheet numbers, all printed in
title blocks. A finder too narrow and a validator too broad fail in opposite
directions, and the gap between them is where `F`, `1` and `PAGE 2 OF 2`
became stored sheet numbers.

MEASURED BEFORE CHANGING, against all 173 sheet numbers the corpus holds:
zero become unfindable, zero become invalid.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_text as pt  # noqa: E402


def found(v: str) -> bool:
    return bool(pt.SHEET_ID_RE.search(v))


class TheSchemesThatAreReal(unittest.TestCase):
    """Every shape observed in the 588 Boyland sets."""

    DASHED = ["A-100.00", "SP-101.00", "RCP-001.00", "SSP-002.00",
              "EN-001.00", "FA-001", "M-201", "A-200", "T-001.01"]
    DOTTED = ["A.0.1", "A.0.8", "A.1.2", "A.1.7"]

    def test_the_dashed_schemes_still_read(self):
        for v in self.DASHED:
            self.assertTrue(found(v), v)
            self.assertTrue(pt.looks_like_a_sheet_number(v), v)

    def test_the_dotted_scheme_now_reads(self):
        """The one this exists for."""
        for v in self.DOTTED:
            self.assertTrue(found(v), f"{v} is a sheet number and was invisible")
            self.assertTrue(pt.looks_like_a_sheet_number(v), v)

    def test_a_revision_letter_is_carried(self):
        self.assertTrue(found("A-101A"))
        self.assertTrue(pt.looks_like_a_sheet_number("A-101A"))

    def test_sheet_ids_lifts_a_dotted_id_out_of_running_text(self):
        got = pt.sheet_ids("SEE DRAWING A.1.2 FOR THE SECTION")
        self.assertIn("A.1.2", got)


class TheThingsThatShareTheShapeAndAreNot(unittest.TestCase):
    """All of these are printed in the title blocks of this project's files."""

    NOT = {
        "110.3.4": "a code citation",
        "C403.1.1": "a code citation",
        "1704.13": "a zoning figure",
        "212-961": "a phone number",
        "845.234": "a phone number",
        "08-24": "a date",
        "1.1": "a bare figure",
        "R19": "an insulation value",
        "R11.5": "an insulation value",
        "IIA1": "a construction class",
        "IB2": "a construction class",
        "I1": "a filing letter",
        "P5": "a filing letter",
    }

    def test_none_of_them_is_found(self):
        for v, why in self.NOT.items():
            self.assertFalse(found(v), f"{v} is {why}")

    def test_none_of_them_validates(self):
        """The validator accepted six of these before this change."""
        for v, why in self.NOT.items():
            self.assertFalse(pt.looks_like_a_sheet_number(v), f"{v} is {why}")

    def test_the_leading_letter_is_what_decides(self):
        """Stated as a property, so the reason survives a future edit: the
        same digits with a letter in front ARE a sheet number, and without
        one are not."""
        self.assertFalse(found("110.3.4"))
        self.assertTrue(found("A-110.3"))


class TheFinderAndTheValidatorAgree(unittest.TestCase):
    """The defect was not either pattern. It was the gap between them.

    COMPARED ON WHOLE-STRING SEMANTICS, which is the comparison that means
    anything. `SHEET_ID_RE.search` locates an id INSIDE running text and the
    validator judges a WHOLE candidate, so searching `A-500.00A` succeeds
    (it contains `A-500.00`) while validating it fails — and those two
    verdicts do not disagree, they answer different questions. Comparing them
    directly reports a conflict that is not there, which it did once while
    this was being written.
    """

    def whole(self, v: str) -> bool:
        """Does the finder read the ENTIRE value as one id?"""
        return pt.sheet_ids(v) == [v]

    def test_every_shape_gets_the_same_verdict_from_both(self):
        every = (TheSchemesThatAreReal.DASHED + TheSchemesThatAreReal.DOTTED
                 + ["A-101A", "A-500.00A", "S-001.00"]
                 + list(TheThingsThatShareTheShapeAndAreNot.NOT))
        disagree = [v for v in every
                    if self.whole(v) != pt.looks_like_a_sheet_number(v)]
        self.assertEqual(
            [], disagree,
            "a value one pattern accepts as a whole id and the other refuses "
            "is how a non-sheet becomes a sheet number: " + repr(disagree))


class AnIdArrivesGluedToItsNeighbour(unittest.TestCase):
    """The two cases that pinned the old pattern's shape, and that a rewrite
    breaks if the decimal stops being preferred without a trailing check."""

    def test_glued_to_its_drawing_list_index(self):
        self.assertEqual(pt.sheet_ids("2S-001.00GENERAL NOTES 3S-002.00"),
                         ["S-001.00", "S-002.00"])

    def test_glued_to_its_page_count(self):
        self.assertEqual(pt.sheet_ids("A-500.0024 OF 31"), ["A-500.00"])

    def test_the_revision_letter_does_not_eat_the_next_word(self):
        """`[A-Z]?` on the decimal branch turned S-001.00GENERAL into
        'S-001.00G'. A revision letter belongs to the BASE number."""
        self.assertEqual(pt.sheet_ids("S-001.00GENERAL"), ["S-001.00"])
        self.assertEqual(pt.sheet_ids("A-101A"), ["A-101A"])


class AnEquipmentMarkIsNotASheetNumber(unittest.TestCase):
    """`EF-1` is a fan, not a sheet. Widening the dashed form to 1-3 digits
    made every first column of a FAN SCHEDULE look like a drawing list, and
    `is_index_record` classified the schedule as an index of the set."""

    def test_marks_are_not_ids(self):
        for mark in ("EF-1", "EF-2", "SAF-1", "SAF-2", "PTAC-2", "L-1"):
            self.assertFalse(found(mark), mark)
            self.assertFalse(pt.looks_like_a_sheet_number(mark), mark)


class ASkipMustNotRestOnAnUnreadScheme(unittest.TestCase):
    """The consequence, asserted at the level that caused the loss."""

    def test_a_dotted_set_no_longer_looks_unnumbered(self):
        profile = {"vector_pages": 44, "title_id_pages": 44,
                   "text_prefixes": ["A"]}
        self.assertFalse(
            pt.looks_combined(profile),
            "a set whose every page carries a readable sheet number is not a "
            "combined set, and must not be skipped as one")

    def test_and_an_actually_unnumbered_set_still_does(self):
        """The rule is not defanged — a set that really carries no numbers is
        still recognised."""
        profile = {"vector_pages": 44, "title_id_pages": 2,
                   "text_prefixes": ["A"]}
        self.assertTrue(pt.looks_combined(profile))


class EveryExitFromTheGridReaderReturnsTheSameShape(unittest.TestCase):
    """Persisting the contested readings widened `_ocr_blind_grids` from a
    two-tuple to a three-tuple, and THREE EARLY RETURNS were left at two.

    The full suite passed anyway — nothing exercises a page with no pdf_path,
    no OCR engine, or no grids — so a production page taking any of those
    three paths would have raised on the caller's unpack. Found by reading the
    diff, not by the suite, which is the reason this test exists: a signature
    change is only as good as its least-travelled exit.

    Asserted structurally rather than by calling the function, because the
    point is that the UNTESTED paths agree, and a test that called it would
    only ever reach the ones already covered.
    """

    def test_all_of_them(self):
        import ast as _ast
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text(
            encoding="utf-8")
        fn = next(n for n in _ast.walk(_ast.parse(src))
                  if isinstance(n, _ast.AsyncFunctionDef)
                  and n.name == "_ocr_blind_grids")
        arities = [
            (n.lineno, len(n.value.elts) if isinstance(n.value, _ast.Tuple) else 1)
            for n in _ast.walk(fn) if isinstance(n, _ast.Return) and n.value
        ]
        self.assertTrue(arities, "no returns found — the walk is broken")
        wrong = [a for a in arities if a[1] != 3]
        self.assertEqual(
            [], wrong,
            "_ocr_blind_grids returns (schedules, flags, contested); an exit "
            "that returns fewer raises on the caller's unpack: " + repr(wrong))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
