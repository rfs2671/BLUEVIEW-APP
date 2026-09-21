"""A TOLERANCE CHOSEN AFTER SEEING THE ERROR IS NOT A TOLERANCE.

These numbers were committed before any registration residual was computed,
on purpose. The failure this prevents is the one this project keeps finding
in other forms: a threshold fitted to the cases it is judged on. Once a
residual exists, any change to these constants is a change to the standard
and has to be argued as one.

The tests below pin the RELATIONSHIPS, not just the values, because the
values could be loosened one at a time without anything noticing while the
ordering — clash tighter than wall, wall tighter than room, match radius
tighter than all of them — is what makes the scheme mean anything.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_registration as reg  # noqa: E402


class TheConversionIsTheThingEveryToleranceIsReallyIn(unittest.TestCase):
    """A tolerance in pixels is a tolerance in inches whether or not anyone
    says so, so the conversion is pinned rather than recomputed by whoever
    next writes a scan."""

    def test_a_pixel_at_quarter_inch_scale_and_250_dpi(self):
        self.assertAlmostEqual(reg.real_inches_per_pixel(), 0.192, places=3)

    def test_an_inch_and_a_foot_in_pixels(self):
        self.assertAlmostEqual(reg.inches_to_pixels(1.0), 5.208, places=2)
        self.assertAlmostEqual(reg.inches_to_pixels(12.0), 62.5, places=1)

    def test_a_detail_sheet_rendered_at_300_dpi_is_finer(self):
        self.assertLess(reg.real_inches_per_pixel(dpi=300),
                        reg.real_inches_per_pixel(dpi=250))

    def test_an_eighth_inch_scale_sheet_is_coarser(self):
        """1/8" = 1'-0" puts twice as much building in each pixel."""
        self.assertAlmostEqual(reg.real_inches_per_pixel(scale_denom=8),
                               2 * reg.real_inches_per_pixel(scale_denom=4),
                               places=6)


class TheToleranceBelongsToTheQuestion(unittest.TestCase):
    """One registration can be good enough to say which room something is in
    and nowhere near good enough to say whether a duct clears a beam. The
    failure this guards is a single 'accuracy' number quoted for every use."""

    def test_the_ordering(self):
        self.assertLess(reg.TOL_CLEARANCE_IN, reg.TOL_WALL_SIDE_IN)
        self.assertLess(reg.TOL_WALL_SIDE_IN, reg.TOL_ROOM_MEMBERSHIP_IN)

    def test_wall_side_is_under_half_a_partition(self):
        """Interior partitions here are about 4.5in. A wall-side answer whose
        tolerance exceeds half that can invert."""
        self.assertLess(reg.TOL_WALL_SIDE_IN, 4.5 / 2)

    def test_a_membership_claim_is_refused_near_a_boundary(self):
        """The room tolerance is only honest in the interior; near a wall the
        answer is 'too close to call'."""
        self.assertGreater(reg.ROOM_EDGE_EXCLUSION_IN,
                           reg.TOL_ROOM_MEMBERSHIP_IN)

    def test_a_fit_good_enough_for_rooms_is_not_good_enough_for_clashes(self):
        self.assertTrue(reg.usable_for("room_membership", 4.0))
        self.assertFalse(reg.usable_for("wall_side", 4.0, max_residual_in=4.0))
        self.assertFalse(reg.usable_for("clearance", 4.0, max_residual_in=4.0))

    def test_an_unnamed_question_is_refused_not_defaulted(self):
        """Defaulting to the loosest tolerance is how a clash question gets
        answered with a room-grade fit."""
        self.assertFalse(reg.usable_for("does it fit", 0.01))


class APointQuestionIsJudgedOnTheWorstCase(unittest.TestCase):
    """CORRECTION, 2026-09-21. `usable_for` originally compared RMS for every
    question. An average over 562 anchors says nothing about the one anchor
    nearest the thing being asked about, and a clash sits at ONE PLACE.

    The case that exposed it, measured on A-103.00 -> P-103.00:
    RMS 0.068in, max 0.812in. By RMS that pair clears the 0.5in clearance
    tolerance. By worst case it does not."""

    def test_the_real_pair_passes_on_rms_and_fails_on_worst_case(self):
        self.assertTrue(0.068 <= reg.TOL_CLEARANCE_IN)      # the trap
        self.assertFalse(reg.usable_for("clearance", 0.068,
                                        max_residual_in=0.812))

    def test_room_membership_still_uses_rms(self):
        """A bulk property, and already refused near a boundary, so the
        average is the honest summary."""
        self.assertTrue(reg.usable_for("room_membership", 0.5,
                                       max_residual_in=5.0))

    def test_every_pointwise_question_uses_the_worst_case(self):
        for kind in ("wall_side", "penetration", "clearance", "clash"):
            self.assertIn(kind, reg.POINTWISE_QUESTIONS, kind)
            self.assertFalse(
                reg.usable_for(kind, 0.001, max_residual_in=9.0), kind)

    def test_a_pointwise_question_without_a_worst_case_is_refused(self):
        """Falling back to RMS is how the stricter test gets skipped exactly
        when the caller did not have the number to pass."""
        for kind in sorted(reg.POINTWISE_QUESTIONS):
            self.assertFalse(reg.usable_for(kind, 0.001), kind)

    def test_the_correction_is_stricter_not_looser(self):
        """It flips answers from usable to refused, never the reverse."""
        self.assertFalse(reg.usable_for("wall_side", 0.1, max_residual_in=3.0))
        self.assertTrue(reg.usable_for("wall_side", 0.1, max_residual_in=1.0))


class AMatchedAnchorIsTighterThanAnyUseOfIt(unittest.TestCase):

    def test_the_match_radius_is_under_every_tolerance(self):
        self.assertLessEqual(reg.ANCHOR_MATCH_RADIUS_IN, reg.TOL_WALL_SIDE_IN)
        self.assertLessEqual(reg.ANCHOR_MATCH_RADIUS_IN,
                             reg.TOL_ROOM_MEMBERSHIP_IN)

    def test_an_anchor_must_be_corner_like(self):
        """A point on a long line is unconstrained ALONG the line, so a
        'match' there measures where the scan sampled, not where the building
        is."""
        self.assertTrue(reg.ANCHOR_MUST_BE_CORNER_LIKE)


class RegisteredIsNotTheSameAsCoincidentallyClose(unittest.TestCase):
    """RMS alone cannot tell them apart: three anchors in one corner fit
    almost anything."""

    def test_a_clean_fit_registers(self):
        v, why = reg.registration_verdict(12, 0.8, 0.7, 0.3, 0.9)
        self.assertEqual((v, why), ("registered", []))

    def test_few_anchors_is_coincidental_not_registered(self):
        v, why = reg.registration_verdict(3, 0.8, 0.7, 0.1, 0.2)
        self.assertEqual(v, "coincidental")
        self.assertTrue(any("anchors" in r for r in why))

    def test_clustered_anchors_are_coincidental_however_good_the_rms(self):
        """The fit is pinned by one corner and is wrong everywhere else."""
        v, why = reg.registration_verdict(20, 0.9, 0.1, 0.05, 0.1)
        self.assertEqual(v, "coincidental")

    def test_one_bad_anchor_fails_even_with_a_passing_rms(self):
        """An RMS that passes while one anchor is far out means the fit is
        being averaged into looking correct."""
        v, why = reg.registration_verdict(20, 0.8, 0.8, 0.9, 5.0)
        self.assertEqual(v, "failed")

    def test_a_fitted_rotation_is_a_finding_not_a_fit(self):
        """The discipline sheets carry the SAME linework, so translation and
        uniform scale should suffice. Rotation means something else is going
        on and must be looked at before the fit is used."""
        v, why = reg.registration_verdict(20, 0.8, 0.8, 0.2, 0.5,
                                          rotation_deg=0.5)
        self.assertEqual(v, "failed")
        self.assertTrue(any("rotation" in r for r in why))

    def test_non_uniform_scale_is_a_finding(self):
        v, why = reg.registration_verdict(20, 0.8, 0.8, 0.2, 0.5,
                                          scale_anisotropy=0.01)
        self.assertEqual(v, "failed")

    def test_the_verdict_carries_reasons_not_a_score(self):
        """A single number invites 'close enough'. The conditions fail for
        different causes and the remedies differ: more anchors versus a
        better fit versus stop and look."""
        _v, why = reg.registration_verdict(2, 0.1, 0.1, 9.0, 20.0)
        self.assertGreaterEqual(len(why), 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
