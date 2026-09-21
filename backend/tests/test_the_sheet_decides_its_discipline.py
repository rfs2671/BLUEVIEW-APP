"""44 ARCHITECTURAL SHEETS WERE FILED AS STRUCTURAL BECAUSE OF A STREET.

`discipline` was `detect_discipline(file_name)` — one regex over the file
name, one value stamped on every page of the file:

    _DISCIPLINE_PATTERNS["ST"]  =  \\b(?:st|str|strl|structural)\\b
    "588 THOMAS BOYLAND ST SET_UPDATED .pdf"  ->  ST
                           ^^ the building's own address

Every A.N.N sheet in that file — FLOOR PLAN x7, RENDERS x9, PLUMBING PLAN
x5, KITCHEN KEY PLAN x4, SECTION x3, RCP AND LIGHTING x3 — came out
structural. `ST - 7.29.26.pdf` is genuinely structural, so 44 of the 58 ST
pages were wrong and ST was the largest bucket in the corpus.

NOT COSMETIC. There are indexes on (project_id, discipline) and
`search_plans` takes a discipline argument, so a wrong value silently
narrows a filtered query: a plumbing question misses five plumbing sheets
filed under structural, and says nothing about it.

── THE ORDER OF EVIDENCE, AND WHY PREFIX BEATS TITLE ──────────────────────

  1. the sheet NUMBER's prefix — printed on the sheet, assigned by the
     drafter, and no fragment of an address can reach it
  2. the sheet TITLE — only when there is no usable prefix
  3. the FILE NAME, last and never first, for a page with neither

`A.4.1 PLUMBING PLAN` is an ARCHITECTURAL sheet that shows plumbing. The
drafter said so by numbering it A. Its title stays "PLUMBING PLAN" in
`sheet_title`, recorded as what the sheet SHOWS. Letting the title decide
would move those five pages out of the architectural set for the same reason
the file name moved all 44 — a word about the content standing in for the
sheet's identity.

SUPERSEDED IN PART, 2026-09-21. That argument holds where the set numbers its
sheets with more than one prefix. 588 Boyland's set numbers EVERY sheet `A.`,
so there the prefix says nothing and the title decides: A.4.1 PLUMBING PLAN is
PL when the indexer passes the set's prefixes. These tests pass no set, which
keeps the order above. See test_a_prefix_is_evidence_where_the_set_has_two.

A HYPOTHESIS THAT WAS WRONG, kept because it also explained the evidence:
that the field came from the sheet-number prefix and failed on the `A.N.N`
scheme. The sheet number was never consulted at all.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_text  # noqa: E402

d = plan_text.discipline_for_page


class TheSixThatWereWrong(unittest.TestCase):
    """Every one of these was `ST` or `other` in the indexed corpus. The file
    discipline is passed as `ST` because that is what the file name gave."""

    CASES = (
        ("A-103.00", "FOURTH FLOOR PLAN"),
        ("A.4.3", "PLUMBING PLAN"),
        ("A.3.3", "REFLECTED CEILING AND LIGHTING PLAN"),
        ("A.3.1", "LIGHTING PLAN"),
        ("A.4.1", "PLUMBING PLAN"),
        ("A.5.1", "KITCHEN KEY PLAN"),
    )

    def test_they_are_architectural(self):
        for sheet, title in self.CASES:
            self.assertEqual(d(sheet, title, "ST"), "AR",
                             f"{sheet} {title!r}")

    def test_the_street_cannot_reach_them(self):
        """The whole defect, stated as a property: what the file is CALLED
        must not change a page that names itself."""
        for sheet, title in self.CASES:
            self.assertEqual(d(sheet, title, "ST"), d(sheet, title, "PL"),
                             f"{sheet}: the file name changed the answer")
            self.assertEqual(d(sheet, title, "ST"), d(sheet, title, ""),
                             f"{sheet}: the file name changed the answer")


class PrefixBeatsTitle(unittest.TestCase):

    def test_an_architectural_sheet_showing_plumbing_stays_architectural(self):
        self.assertEqual(d("A.4.1", "PLUMBING PLAN", ""), "AR")

    def test_a_plumbing_sheet_showing_plumbing_is_plumbing(self):
        self.assertEqual(d("P-103.00", "PLUMBING PLAN", ""), "PL")

    def test_the_title_is_used_only_with_no_prefix(self):
        self.assertEqual(d("", "SPRINKLER SPECIFICATION", "other"), "SP")
        self.assertEqual(d("", "FIRE ALARM RISER DIAGRAM", "other"), "FA")


class TheOnesThatWereRightMustStayRight(unittest.TestCase):
    """A FIX REPORTS WHAT SHOULD NOT HAVE CHANGED. The X-NNN.NN sets were
    already correct and none of them may move."""

    def test_unchanged(self):
        for sheet, title, expect in (
                ("M-103.00", "MECHANICAL PLAN", "ME"),
                ("M-200.00", "MECHANICAL SCHEDULES", "ME"),
                ("P-400.00", "PLUMBING RISER", "PL"),
                ("SP-002.00", "SPRINKLER PLAN", "SP"),
                ("S-001.00", "GENERAL NOTES", "ST"),
                ("GN-001.00", "GENERAL NOTES", "GN"),
                ("A-101.00", "FIRST FLOOR PLAN", "AR"),
                ("RCP-001.00", "REFLECTED CEILING PLAN", "AR")):
            self.assertEqual(d(sheet, title, "other"), expect, sheet)


class OtherByOmissionIsNotOther(unittest.TestCase):
    """SSP and FA had no pattern at all, so two whole sets were `other` — not
    misfiled, unreachable. A filter could not name them."""

    def test_site_safety_and_fire_alarm_have_a_code_now(self):
        self.assertEqual(d("SSP-009.00", "SITE SAFETY PLAN", "other"), "SSP")
        self.assertEqual(d("FA-001", "FIRE ALARM RISER", "other"), "FA")

    def test_the_general_bucket_takes_the_rest(self):
        """Zoning, energy and title sheets go to GN rather than getting codes
        of their own. A new code is a new filter value every caller would
        have to learn; these three are not queried by discipline."""
        for sheet in ("Z-001.01", "EN-001.00", "T-001.00", "G-001"):
            self.assertEqual(d(sheet, "", "other"), "GN", sheet)


class APagePositionIsNotAPrefix(unittest.TestCase):
    """THIRD INSTANCE of a position standing in for an identity, after
    `candidate_sheet` returning "1 OF 1" and the small-image title-block read
    returning "25" for a sheet numbered A.3.1. `1 OF 3` must not yield `1`
    and must not match anything."""

    def test_a_position_has_no_discipline_of_its_own(self):
        for pos in ("1 OF 3", "1 OF 1", "Page 2 of 2", "0", "16 OF 31"):
            self.assertIsNone(plan_text.discipline_from_sheet_number(pos), pos)

    def test_it_falls_through_to_the_file(self):
        self.assertEqual(d("1 OF 3", "", "PL"), "PL")
        self.assertEqual(d("1 OF 3", "", "other"), "other")


class TheFileIsTheLastResortAndOtherIsNotEvidence(unittest.TestCase):

    def test_a_page_with_nothing_is_other(self):
        self.assertEqual(d("", "", ""), "other")
        self.assertEqual(d("", "", "other"), "other")

    def test_a_spec_page_still_inherits_its_file(self):
        """The two spec-page branches in the indexer carry no sheet number and
        the placeholder title `[SPECIFICATION PAGE]`, so the file name is all
        they have — which is exactly what it is kept for."""
        self.assertEqual(d("", "[SPECIFICATION PAGE]", "PL"), "PL")

    def test_none_and_empty_are_handled(self):
        self.assertEqual(d(None, None, None), "other")


class TheUnknownPrefixDoesNotInventADiscipline(unittest.TestCase):
    """'NY-112', 'FO-202', 'AJ-208' are UL systems and detail references, not
    sheets. plan_text already refuses to read them as disciplines and this
    must not reintroduce them."""

    def test_a_code_reference_is_not_a_sheet_prefix(self):
        for junk in ("NY-112", "FO-202", "AJ-208", "UL-263"):
            self.assertIsNone(plan_text.discipline_from_sheet_number(junk),
                              junk)


if __name__ == "__main__":
    unittest.main()
