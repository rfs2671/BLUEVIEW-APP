"""A drawing is scaled by the note in its own title bar, and only once the
drawing's own printed dimensions agree with it (operator's rule, Roy
2026-10-26; lib.plan_scale).

What this guards, each from a reading that went wrong on 588 Boyland:

  * A-100.01 prints "PTAC UNIT 3'-8" X 1'-6" = 5.5'" in a code note.
    Matchline read it as a scale of 1:11. It is not a scale note at all.
  * A-105.01 holds a 3/32" BULKHEAD PLAN above a 1/4" ROOF PLAN, and
    S-106.00 a 1/4" ROOF FRAMING PLAN beside a 1/8" BULKHEAD ROOF FRAMING
    PLAN. One scale per sheet is wrong for one of each pair, and the nearest
    note to a point at the top of the roof plan is the BULKHEAD's.
  * The P sheets print their scale as vector (SHX) text: there is no note in
    the text layer, so there is no scale, whatever the drawing measures.
  * A note is a claim. The drawing's own dimensions, measured, must back it
    - at least three of them - or the viewport is refused.
  * Copies count, but the three must include two different printed values
    (Roy, 2026-10-27): GN-004.00's ROOF EGRESS PLAN verified on four copies
    of one 3'-0" door width, and the elevations on six 10'-0" floor heights.

WRITTEN TO FAIL BY ASSERTION ON A TREE WITHOUT THE MODULE: every test reaches
lib.plan_scale through `_ps()`, which turns a missing module or name into an
AssertionError rather than an ImportError at collection.
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

#: 1/4" = 1'-0" is 0.25in of paper (18pt) per real foot: 1.5pt per real inch.
QUARTER = 1.5
EIGHTH = 0.75
THREE_SIXTEENTHS = 1.125


def _ps(*names):
    try:
        mod = importlib.import_module("lib.plan_scale")
    except ImportError as e:
        raise AssertionError(f"lib.plan_scale is not importable: {e}")
    for n in names:
        assert hasattr(mod, n), f"lib.plan_scale has no {n}"
    return mod


#: Printed values for test dimensions: a different one each, unless a test
#: asks for copies.
_VALUES = (96.0, 120.0, 36.0, 48.0, 60.0, 72.0, 84.0, 108.0, 132.0, 144.0)


def _text(inches):
    ft, inch = divmod(int(inches), 12)
    return f"{ft}'-{inch}\""


def _dims(implied, inches=None):
    """One measured dimension per implied pt/in. `inches`: one printed value
    for all of them (copies), a list (one each), or None (all different)."""
    ps = _ps("Dimension")
    if inches is None:
        inches = [_VALUES[i % len(_VALUES)] for i in range(len(implied))]
    elif not isinstance(inches, (list, tuple)):
        inches = [inches] * len(implied)
    return [ps.Dimension(text=_text(n), inches=n, bbox=(0, 0, 1, 1), measured_pt=v * n)
            for v, n in zip(implied, inches)]


def _note(pt_per_in, text="note"):
    ps = _ps("ScaleNote")
    return ps.ScaleNote(text=text, bbox=(0, 0, 1, 1), pt_per_in=pt_per_in,
                        ratio=72 / pt_per_in if pt_per_in else None, nts=pt_per_in is None)


# ── the note ───────────────────────────────────────────────────────────────

class AScaleNoteIsPaperInchesEqualToRealFeet(unittest.TestCase):

    def test_the_ptac_arithmetic_is_not_a_scale(self):
        ps = _ps("parse_scale_note")
        self.assertIsNone(ps.parse_scale_note('PTAC UNIT 3\'-8" X 1\'-6" = 5.5\''))
        self.assertIsNone(ps.parse_scale_note("20' + 5.5'= 25.5' < 70' OK"))

    def test_the_standard_scales_read_as_printed(self):
        ps = _ps("parse_scale_note")
        for text, ppi in (('Scale:1/4" = 1\'-0"', QUARTER), ('SCALE: 1/8" = 1\'-0"', EIGHTH),
                          ('3/16" = 1\'-0"', THREE_SIXTEENTHS), ('Scale:3/32" = 1\'-0"', 0.5625),
                          ('Scale: 3/4"=1\'-0"', 4.5), ('1 1/2" = 1\'-0"', 9.0),
                          ('1" = 20\'-0"', 0.3)):
            got = ps.parse_scale_note(text)
            self.assertIsNotNone(got, text)
            self.assertAlmostEqual(got["pt_per_in"], ppi, places=6, msg=text)

    def test_a_detail_bubble_number_is_not_part_of_the_scale(self):
        # S-302.00: the bubble "5" prints beside a 3/16" note.
        ps = _ps("parse_scale_note")
        self.assertAlmostEqual(ps.parse_scale_note('5 3/16" = 1\'-0"')["pt_per_in"],
                               THREE_SIXTEENTHS, places=6)

    def test_not_to_scale_is_a_note_with_no_scale(self):
        ps = _ps("parse_scale_note")
        for text in ("SCALE: N.T.S.", "SCALE: NONE", "SCALE: AS NOTED"):
            got = ps.parse_scale_note(text)
            self.assertTrue(got and got["nts"] and got["pt_per_in"] is None, text)


# ── the verification ───────────────────────────────────────────────────────

class ANoteIsAcceptedOnlyWhenItsDimensionsAgree(unittest.TestCase):

    def test_three_agreeing_dimensions_verify(self):
        ps = _ps("verify")
        ok, n, why = ps.verify(_note(QUARTER), _dims([1.5, 1.5, 1.5]))
        self.assertTrue(ok, why)
        self.assertEqual(n, 3)

    def test_two_agreeing_dimensions_do_not(self):
        ps = _ps("verify")
        ok, n, why = ps.verify(_note(QUARTER), _dims([1.5, 1.5]))
        self.assertFalse(ok)
        self.assertEqual(n, 2)
        self.assertIn("need 3", why)

    def test_a_dimension_rounded_to_the_half_inch_still_agrees(self):
        # A 1'-0" dimension printed for 12 1/4" drawn: 2.1% off, rounding.
        ps = _ps("verify")
        ok, _n, why = ps.verify(_note(QUARTER), _dims([1.5 * 12.25 / 12] * 3, inches=[12.0, 12.0, 24.0]))
        self.assertTrue(ok, why)

    def test_a_dimension_ten_percent_off_does_not_agree(self):
        ps = _ps("verify")
        ok, n, _why = ps.verify(_note(QUARTER), _dims([1.65, 1.65, 1.65, 1.35]))
        self.assertFalse(ok)
        self.assertEqual(n, 0)

    def test_the_neighbouring_standard_scale_never_agrees(self):
        # 3/16" against a 1/4" note: 25% apart, the closest standard pair.
        ps = _ps("verify")
        ok, n, _why = ps.verify(_note(QUARTER), _dims([THREE_SIXTEENTHS] * 6))
        self.assertFalse(ok)
        self.assertEqual(n, 0)

    def test_a_scale_most_dimensions_contradict_is_refused(self):
        ps = _ps("verify")
        ok, n, why = ps.verify(_note(QUARTER), _dims([1.5] * 3 + [EIGHTH] * 5))
        self.assertFalse(ok)
        self.assertEqual(n, 3)
        self.assertIn("another scale", why)

    def test_no_note_and_not_to_scale_are_refused(self):
        ps = _ps("verify")
        self.assertFalse(ps.verify(None, _dims([1.5] * 9))[0])
        self.assertFalse(ps.verify(_note(None, "SCALE: N.T.S."), _dims([1.5] * 9))[0])

    def test_two_title_bars_with_different_scales_refuse_their_drawing(self):
        # One body of ink claimed by a 1/4" bar and a 1/8" bar: which governs
        # cannot be guessed, even when the dimensions back one of them.
        ps = _ps("claimed_viewport")
        v = ps.claimed_viewport((0, 0, 100, 100), [_note(QUARTER, "1/4"), _note(EIGHTH, "1/8")],
                                _dims([1.5] * 9))
        self.assertFalse(v.verified)
        self.assertIsNone(v.pt_per_in)
        self.assertIn("different scales", v.refusal)
        same = ps.claimed_viewport((0, 0, 100, 100), [_note(QUARTER), _note(QUARTER)], _dims([1.5] * 3))
        self.assertTrue(same.verified, same.refusal)

    def test_copies_of_one_value_do_not_verify(self):
        # GN-004.00 ROOF EGRESS PLAN: four 3'-0" door widths, each exactly
        # 1/8". One length checked four times is one length checked.
        ps = _ps("verify")
        ok, n, why = ps.verify(_note(EIGHTH, "1/8\" = 1'-0\""), _dims([EIGHTH] * 4, inches=36.0))
        self.assertFalse(ok)
        self.assertEqual(n, 4, "copies still count as agreeing")
        self.assertIn("all read 3'-0\"", why)
        self.assertIn("2 different values needed", why)

    def test_copies_count_toward_the_three(self):
        # Two copies of 3'-0" and one 10'-0": three agree, two values. The
        # copies are not thrown away - a viewport needs two VALUES, not three.
        ps = _ps("verify")
        ok, n, why = ps.verify(_note(EIGHTH), _dims([EIGHTH] * 3, inches=[36.0, 36.0, 120.0]))
        self.assertTrue(ok, why)
        self.assertEqual(n, 3)

    def test_one_value_written_two_ways_is_one_value(self):
        ps = _ps("Dimension", "verify")
        dims = [ps.Dimension(text=t, inches=36.0, bbox=(0, 0, 1, 1), measured_pt=27.0)
                for t in ("3'-0\"", '36"', "3'-0\"")]
        ok, n, _why = ps.verify(_note(EIGHTH), dims)
        self.assertFalse(ok)
        self.assertEqual(n, 3)

    def test_the_second_value_must_itself_agree(self):
        # Three 3'-0" agree; the 10'-0" beside them is 10% off the note. It is
        # a different value, but it backs nothing.
        ps = _ps("verify")
        ok, n, why = ps.verify(_note(EIGHTH), _dims([EIGHTH] * 3 + [EIGHTH * 1.10],
                                                     inches=[36.0, 36.0, 36.0, 120.0]))
        self.assertFalse(ok)
        self.assertEqual(n, 3)
        self.assertIn("all read", why)

    def test_values_are_counted_per_viewport_not_per_sheet(self):
        # Two viewports on one sheet: the first prints 3'-0" and 10'-0", the
        # second only 3'-0". The first's 10'-0" is no evidence for the second,
        # in either order, and through claimed_viewport as through verify.
        ps = _ps("verify", "claimed_viewport")
        both = _dims([EIGHTH] * 4, inches=[36.0, 36.0, 120.0, 120.0])
        only = _dims([EIGHTH] * 4, inches=36.0)
        for dims, want in ((both, True), (only, False), (only, False), (both, True), (only, False)):
            self.assertEqual(ps.verify(_note(EIGHTH), dims)[0], want)
        a = ps.claimed_viewport((0, 0, 100, 100), [_note(EIGHTH)], both)
        b = ps.claimed_viewport((200, 0, 300, 100), [_note(EIGHTH)], only)
        self.assertTrue(a.verified, a.refusal)
        self.assertFalse(b.verified)
        self.assertIsNone(b.pt_per_in)
        self.assertIn("all read", b.refusal)

    def test_an_unverified_viewport_gives_no_length(self):
        ps = _ps("Viewport")
        v = ps.Viewport(bbox=(0, 0, 1, 1), drawing_bbox=(0, 0, 1, 1), pt_per_in=None,
                        verified=False, refusal="no note")
        with self.assertRaises(ValueError):
            v.real_inches(100.0)


# ── the drawings ───────────────────────────────────────────────────────────

class _Sheet(unittest.TestCase):
    FILE = PAGE = None
    _cache = {}

    @classmethod
    def setUpClass(cls):
        cls.path = require_pdf(cls.FILE)          # a missing PDF skips, loudly

    @property
    def sheet(self):
        # Read inside the test, not in setUpClass: on a tree without the
        # module this must FAIL by assertion, not error in setup.
        key = (self.FILE, self.PAGE)
        if key not in _Sheet._cache:
            from lib.plan_page import open_page
            ps = _ps("read_sheet")
            _Sheet._cache[key] = ps.read_sheet(open_page(str(self.path), self.PAGE))
        return _Sheet._cache[key]

    def titled(self, words):
        hits = [v for v in self.sheet.viewports if (v.title or "").strip().upper() == words.upper()]
        self.assertEqual(len(hits), 1, f"{words!r}: {[(v.title, v.scale_text) for v in self.sheet.viewports]}")
        return hits[0]

    def scale_at(self, x, y):
        v = self.sheet.at(x, y)
        return v.pt_per_in if v else None


class A100_01TheCodeNoteIsNotAScale(_Sheet):
    FILE, PAGE = "AR - 8.18.26.pdf", 6

    def test_the_floor_plan_is_quarter_inch_and_verified(self):
        v = self.titled("FIRST FLOOR PLAN")
        self.assertTrue(v.verified, v.refusal)
        self.assertAlmostEqual(v.pt_per_in, QUARTER, places=6)
        self.assertGreaterEqual(v.agreeing, 3)

    def test_no_viewport_reads_the_ptac_line(self):
        for v in self.sheet.viewports:
            self.assertNotIn("PTAC", v.scale_text)
            if v.note and v.note.ratio:
                self.assertNotAlmostEqual(v.note.ratio, 11.0, places=3)

    def test_a_point_in_the_plan_is_quarter_inch(self):
        self.assertAlmostEqual(self.scale_at(1100, 800), QUARTER, places=6)

    def test_a_point_outside_every_drawing_has_no_scale(self):
        # Blank paper at the lower left: no drawing, so no viewport - not
        # the nearest one.
        self.assertIsNone(self.sheet.at(100, 1600))

    def test_the_plans_dimensions_refuse_a_wrong_note(self):
        ps = _ps("verify")
        v = self.titled("FIRST FLOOR PLAN")
        for wrong in (EIGHTH, THREE_SIXTEENTHS):
            self.assertFalse(ps.verify(_note(wrong), v.dimensions)[0], wrong)


class A105_01TwoViewsTwoScales(_Sheet):
    FILE, PAGE = "AR - 8.18.26.pdf", 7

    def test_each_view_has_its_own_note(self):
        self.assertAlmostEqual(self.titled("BULKHEAD PLAN").note.pt_per_in, 0.5625, places=6)
        self.assertAlmostEqual(self.titled("ROOF PLAN").note.pt_per_in, QUARTER, places=6)

    def test_the_roof_plan_verifies(self):
        v = self.titled("ROOF PLAN")
        self.assertTrue(v.verified, v.refusal)
        self.assertAlmostEqual(v.pt_per_in, QUARTER, places=6)

    def test_the_bulkhead_plan_prints_no_dimensions_and_is_refused(self):
        v = self.titled("BULKHEAD PLAN")
        self.assertFalse(v.verified)
        self.assertIsNone(v.pt_per_in)

    def test_the_bulkhead_drawing_never_takes_the_roof_scale(self):
        v = self.sheet.at(500, 200)
        self.assertIsNotNone(v)
        self.assertIn("BULKHEAD", v.title.upper())
        self.assertIsNone(v.pt_per_in)

    def test_the_nearest_note_is_not_the_scale(self):
        # Top-left of the roof plan: the BULKHEAD note is nearest.
        v = self.sheet.at(250, 450)
        self.assertIsNotNone(v)
        self.assertIn("ROOF PLAN", v.title.upper())
        self.assertAlmostEqual(v.pt_per_in, QUARTER, places=6)


class S106TheSplitSheet(_Sheet):
    FILE, PAGE = "ST - 7.29.26.pdf", 10

    def test_the_roof_framing_plan_is_quarter_inch(self):
        v = self.titled("ROOF FRAMING PLAN")
        if "BULKHEAD" in v.title.upper():
            self.fail(f"the two views were merged: {v.title}")
        self.assertTrue(v.verified, v.refusal)
        self.assertAlmostEqual(v.pt_per_in, QUARTER, places=6)

    def test_the_bulkhead_is_an_eighth_and_refused_without_dimensions(self):
        v = self.titled("BULKHEAD ROOF FRAMING PLAN")
        self.assertAlmostEqual(v.note.pt_per_in, EIGHTH, places=6)
        self.assertFalse(v.verified)
        self.assertIsNone(v.pt_per_in)

    def test_a_point_in_the_bulkhead_never_gets_a_quarter(self):
        self.assertIsNone(self.scale_at(1700, 1200))


class P201NoNoteNoScale(_Sheet):
    FILE, PAGE = "PL - 6.29.26.pdf", 9

    def test_nothing_on_the_sheet_is_scaled(self):
        self.assertTrue(self.sheet.viewports)
        for v in self.sheet.viewports:
            self.assertFalse(v.verified)
            self.assertIsNone(v.pt_per_in)
            self.assertIn("no title bar with a scale note", v.refusal)

    def test_the_plan_itself_is_found_and_refused(self):
        self.assertIsNone(self.scale_at(1100, 800))
        v = self.sheet.at(1100, 800)
        self.assertIsNotNone(v, "the plan is a viewport, refused - not missing")


class GN004AnEighthIsReadNotAssumed(_Sheet):
    FILE, PAGE = "AR - 3.28.25.pdf", 9

    def test_egress_plans_verify_at_an_eighth(self):
        v = self.titled("FIRST FLOOR EGRESS PLAN")
        self.assertTrue(v.verified, v.refusal)
        self.assertAlmostEqual(v.pt_per_in, EIGHTH, places=6)

    def test_two_agreeing_dimensions_are_not_enough(self):
        v = self.titled("MEZZANINE EGRESS PLAN")
        self.assertEqual(v.agreeing, 2)
        self.assertFalse(v.verified)

    def test_four_copies_of_one_door_width_are_refused(self):
        # Every agreeing dimension on the roof egress plan is a 3'-0" door
        # width. On the same sheet the first floor plan also prints 30'-5",
        # and that is the first floor's evidence, not the roof's.
        v = self.titled("ROOF EGRESS PLAN")
        self.assertGreaterEqual(v.agreeing, 3, "copies still count as agreeing")
        self.assertFalse(v.verified)
        self.assertIsNone(v.pt_per_in)
        self.assertIn("all read 3'-0\"", v.refusal)
        x0, y0, x1, y1 = v.drawing_bbox
        self.assertIsNone(self.scale_at((x0 + x1) / 2, (y0 + y1) / 2))

    def test_the_first_floor_still_verifies_on_two_values(self):
        v = self.titled("FIRST FLOOR EGRESS PLAN")
        ok = [d for d in v.dimensions
              if d.implied_pt_per_in and abs(d.implied_pt_per_in / EIGHTH - 1) <= 0.03]
        self.assertGreaterEqual(len({round(d.inches * 16) for d in ok}), 2)
        self.assertTrue(v.verified, v.refusal)


class A202_01AnElevationOfOneFloorHeight(_Sheet):
    """Six 10'-0" floor-to-floor heights, each exactly 3/16": one value."""
    FILE, PAGE = "AR - 8.18.26.pdf", 10

    def test_six_copies_of_ten_feet_are_refused(self):
        v = self.titled("SIDE ELEVATION")
        self.assertEqual(v.agreeing, 6)
        self.assertFalse(v.verified)
        self.assertIsNone(v.pt_per_in)
        self.assertIn("all read 10'-0\"", v.refusal)


if __name__ == "__main__":
    unittest.main()
