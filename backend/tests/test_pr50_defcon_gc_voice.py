"""PR #50 — Defcon detail screen GC-voice backend support.

The Defcon detail screen (PR #45) leaked engineering vocabulary into
the UX ("Cohort Context", "n_peer_matches", "hazard ratio",
"project_rate_ratio"). PR #50 pre-renders GC-voice strings in the
backend (single-source-of-truth pattern from PR #15D.1) so the
frontend renders plain English directly.

Two new helpers tested here:

  • _cohort_comparison_text(hazard_ratio, borough, work_type) -> str
    Maps the hazard ratio to a plain-English comparison sentence using
    the PR #15D.1 5-tier thresholds. NEVER surfaces the raw ratio.

  • _contributing_factors_to_text(factors) -> List[str]
    Translates the internal {factor, weight, evidence} dicts to
    GC-voice sentences. Hazard-ratio factors are rendered ratio-free.

Plus integration assertions that compute_defcon_status now emits both
new fields while keeping the raw fields for engineering debug.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.run(coro)


try:
    from lib.statistical_engine.defcon import (
        _cohort_comparison_text,
        _contributing_factors_to_text,
        compute_defcon_status,
    )
    HAS_HELPERS = True
except ImportError:
    _cohort_comparison_text = None        # type: ignore
    _contributing_factors_to_text = None  # type: ignore
    compute_defcon_status = None          # type: ignore
    HAS_HELPERS = False


class _BareDb:
    """compute_defcon_status reads every collection via getattr(db, X,
    None); a bare object with no attributes degrades all resolvers to
    their no-signal defaults (NORMAL tier, no factors, hr=None)."""
    pass


# ═══════════════════════════════════════════════════════════════════
# _cohort_comparison_text — threshold mapping
# ═══════════════════════════════════════════════════════════════════


class TestCohortComparisonText(unittest.TestCase):

    def _require(self):
        if not HAS_HELPERS:
            self.fail(
                "defcon GC-voice helpers not implemented. PR #50 Stage 2.A."
            )

    def test_cohort_comparison_text_returns_lower_for_ratio_below_0_75(self):
        self._require()
        out = _cohort_comparison_text(0.5, "BROOKLYN", "major alteration")
        self.assertIn("Lower than typical", out)

    def test_cohort_comparison_text_returns_tracking_for_ratio_1_0(self):
        self._require()
        out = _cohort_comparison_text(1.0, "BROOKLYN", "major alteration")
        self.assertIn("Tracking with", out)

    def test_cohort_comparison_text_returns_slightly_above_for_ratio_1_3(self):
        self._require()
        out = _cohort_comparison_text(1.3, "BROOKLYN", "major alteration")
        self.assertIn("Slightly above typical", out)

    def test_cohort_comparison_text_returns_above_for_ratio_2_0(self):
        self._require()
        out = _cohort_comparison_text(2.0, "BROOKLYN", "major alteration")
        # "Above typical" but NOT "Slightly above" / "Notably"
        self.assertIn("Above typical", out)
        self.assertNotIn("Slightly", out)
        self.assertNotIn("Notably", out)

    def test_cohort_comparison_text_returns_notably_elevated_for_ratio_3_5(self):
        self._require()
        out = _cohort_comparison_text(3.5, "BROOKLYN", "major alteration")
        self.assertIn("Notably elevated", out)

    def test_cohort_comparison_text_returns_significantly_above_for_ratio_5(self):
        self._require()
        out = _cohort_comparison_text(5.0, "BROOKLYN", "major alteration")
        self.assertIn("Significantly above typical", out)

    def test_cohort_comparison_text_handles_null_ratio(self):
        self._require()
        self.assertEqual(
            _cohort_comparison_text(None, "BROOKLYN", "major alteration"),
            "Comparison not yet available",
        )

    def test_cohort_comparison_text_interpolates_borough_and_work_type(self):
        self._require()
        out = _cohort_comparison_text(2.0, "BROOKLYN", "major alteration")
        # Borough title-cased, work_type interpolated.
        self.assertIn("Brooklyn", out)
        self.assertIn("major alteration", out)
        self.assertNotIn("BROOKLYN", out)

    def test_cohort_comparison_text_never_leaks_raw_ratio(self):
        self._require()
        for r in (0.5, 1.0, 1.3, 2.0, 3.5, 5.0):
            out = _cohort_comparison_text(r, "QUEENS", "new building")
            self.assertNotIn("×", out)
            self.assertNotIn("ratio", out.lower())
            self.assertNotIn(str(r), out)

    def test_cohort_comparison_text_falls_back_to_similar_sites(self):
        """No borough → generic 'similar sites' descriptor."""
        self._require()
        out = _cohort_comparison_text(2.0, "", "")
        self.assertIn("similar sites", out)


# ═══════════════════════════════════════════════════════════════════
# _contributing_factors_to_text — translation
# ═══════════════════════════════════════════════════════════════════


class TestContributingFactorsText(unittest.TestCase):

    def _require(self):
        if not HAS_HELPERS:
            self.fail("defcon GC-voice helpers not implemented. PR #50.")

    def test_contributing_factors_text_translates_swo_active(self):
        self._require()
        out = _contributing_factors_to_text([
            {"factor": "swo_active", "weight": 0.7,
             "evidence": "Active stop-work order"},
        ])
        self.assertEqual(len(out), 1)
        self.assertIn("stop-work order", out[0].lower())

    def test_contributing_factors_text_translates_class_1_violation(self):
        self._require()
        out = _contributing_factors_to_text([
            {"factor": "class_1_violation_recent", "weight": 1.0,
             "evidence": "CLASS-1 violation in last 7 days (safety hazard), "
                         "3 days ago"},
        ])
        self.assertEqual(len(out), 1)
        # GC-readable: references a serious violation, no raw bucket key.
        self.assertTrue(len(out[0]) > 0)

    def test_contributing_factors_text_translates_complaint_clustering(self):
        self._require()
        out = _contributing_factors_to_text([
            {"factor": "complaint_clustering", "weight": 0.4,
             "evidence": "4 complaints filed in last 30 days"},
        ])
        self.assertEqual(len(out), 1)
        self.assertIn("complaint", out[0].lower())

    def test_contributing_factors_text_hazard_factor_no_number_leak(self):
        """Hazard-ratio factors must render ratio-free — no '×', no
        'cohort', no 'baseline', no 'threshold'."""
        self._require()
        out = _contributing_factors_to_text([
            {"factor": "hazard_ratio_elevated", "weight": 0.5,
             "evidence": "14-day violation rate 2.3× cohort baseline "
                         "(threshold: 1.5×)"},
            {"factor": "hazard_ratio_immediate", "weight": 1.0,
             "evidence": "14-day violation rate 5.0× cohort baseline "
                         "(threshold: 4.0×)"},
        ])
        self.assertEqual(len(out), 2)
        for s in out:
            self.assertNotIn("×", s)
            self.assertNotIn("cohort", s.lower())
            self.assertNotIn("baseline", s.lower())
            self.assertNotIn("threshold", s.lower())

    def test_contributing_factors_text_empty_returns_empty_list(self):
        self._require()
        self.assertEqual(_contributing_factors_to_text([]), [])

    def test_contributing_factors_text_preserves_order(self):
        self._require()
        out = _contributing_factors_to_text([
            {"factor": "swo_active", "weight": 0.7, "evidence": "x"},
            {"factor": "complaint_clustering", "weight": 0.4,
             "evidence": "3 complaints filed in last 30 days"},
        ])
        self.assertEqual(len(out), 2)
        self.assertIn("stop-work", out[0].lower())
        self.assertIn("complaint", out[1].lower())


# ═══════════════════════════════════════════════════════════════════
# compute_defcon_status — response shape
# ═══════════════════════════════════════════════════════════════════


class TestDefconResponseShape(unittest.TestCase):

    def _require(self):
        if not HAS_HELPERS:
            self.fail("defcon GC-voice helpers not implemented. PR #50.")

    def test_defcon_response_includes_both_new_fields(self):
        self._require()
        project = {
            "_id": "P1", "borough": "BROOKLYN",
            "prediction_cache": {
                "prob_violation_14d": 0.2,
                "anchored_baseline_prob_14d": 0.1,  # hr = 2.0
                "cohort_sample_size": 120,
            },
        }
        result = _run(compute_defcon_status(_BareDb(), project))
        self.assertIn("cohort_comparison_text", result)
        self.assertIn("contributing_factors_text", result)
        self.assertIsInstance(result["cohort_comparison_text"], str)
        self.assertIsInstance(result["contributing_factors_text"], list)
        # hr 2.0 → "Above typical"
        self.assertIn("Above typical", result["cohort_comparison_text"])

    def test_defcon_response_old_fields_still_present_for_backward_compat(self):
        self._require()
        project = {"_id": "P2", "borough": "QUEENS", "prediction_cache": {}}
        result = _run(compute_defcon_status(_BareDb(), project))
        # Raw debug fields retained.
        self.assertIn("contributing_factors", result)
        self.assertIn("cohort_context", result)
        self.assertIn("tier", result)
        self.assertIn("primary_reason", result)
        # No prediction cache → hr None → comparison-not-available.
        self.assertEqual(
            result["cohort_comparison_text"],
            "Comparison not yet available",
        )


if __name__ == "__main__":
    unittest.main()
