"""PR #15B — prediction_cache sub-document shape + ensemble logic.

5 tests in TestPredictionCache:
  1. test_prediction_cache_shape_matches_spec
  2. test_prediction_cache_schema_version_invalidation
  3. test_ensemble_trigger_at_brier_divergence_14_9_pct_no_fire (L6, T7)
  4. test_ensemble_trigger_at_brier_divergence_15_1_pct_fires (L6, T7)
  5. test_prediction_cache_anchored_baseline_label_format (L8)
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# Required prediction_cache fields per Task 5 design.
PREDICTION_CACHE_REQUIRED_FIELDS = frozenset({
    "prob_violation_7d",
    "prob_violation_14d",
    "prob_violation_30d",
    "anchored_baseline_prob_14d",
    "anchored_baseline_label",
    "cohort_tier_utilized",
    "cohort_sample_size",
    "low_confidence_flag",
    "is_cold_start",
    "lifecycle_stage_pct",
    "district_caseload_proxy_days",
    "model_coefficients_hash",
    "last_validated_timestamp",
    "fit_at",
    "schema_version",
})


class TestPredictionCache(unittest.TestCase):
    """PR #15B — prediction_cache sub-document shape pins."""

    def test_prediction_cache_shape_matches_spec(self):
        """Stage 3 — build_prediction_cache must return a dict with
        all 15 required fields populated."""
        try:
            from lib.statistical_engine.live_mutation import (
                build_prediction_cache,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement build_prediction_cache(\n"
                "    *, beta_coefficients, x_now_standardized, mu, "
                "sigma,\n"
                "    cohort_segment_mix, cohort_sample_size,\n"
                "    anchored_baseline_prob_14d, anchored_baseline_label,\n"
                "    model_coefficients_hash, fit_at, now,\n"
                ") -> Dict[str, Any]. Returns 15-field prediction_cache "
                "sub-document. See Task 5 design doc."
            )
        cache = build_prediction_cache(
            beta_coefficients={
                "intercept": -2.5, "active_swo_flag": 1.2,
                "complaint_velocity_14d": 0.3,
                "days_since_last_violation": -0.02,
                "derived_lifecycle_stage_pct": 0.01,
                "district_caseload_proxy_days": 0.05,
            },
            x_now_standardized={
                "active_swo_flag": 0.0, "complaint_velocity_14d": 0.0,
                "days_since_last_violation": 0.0,
                "derived_lifecycle_stage_pct": 0.0,
                "district_caseload_proxy_days": 0.0,
            },
            mu={}, sigma={},
            cohort_segment_mix={"modern": 60, "legacy": 20},
            cohort_sample_size=80,
            anchored_baseline_prob_14d=0.04,
            anchored_baseline_label="BROOKLYN New Building macro baseline",
            model_coefficients_hash="abc123",
            fit_at=None, now=None,
        )
        missing = PREDICTION_CACHE_REQUIRED_FIELDS - set(cache.keys())
        self.assertEqual(
            missing, set(),
            msg=(
                f"prediction_cache missing required fields: {sorted(missing)}. "
                f"All 15 fields from PREDICTION_CACHE_REQUIRED_FIELDS "
                f"must be present per Task 5 design."
            ),
        )

    def test_prediction_cache_schema_version_invalidation(self):
        """Stage 3 — cache with stale schema_version is treated as
        absent on read. Mirrors peer_stats_cache pattern at
        baselines.py:1950."""
        try:
            from lib.statistical_engine.live_mutation import (
                is_prediction_cache_valid,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement is_prediction_cache_valid"
                "(cache: Optional[Dict]) -> bool. Returns False when "
                "cache is None, missing schema_version, or carries a "
                "schema_version other than the current 'pr15b_v1'. "
                "Mirrors baselines.py:1950 pattern."
            )
        self.assertFalse(is_prediction_cache_valid(None))
        self.assertFalse(
            is_prediction_cache_valid({"schema_version": "pr15a_v1"}),
            msg="Wrong schema_version must invalidate.",
        )
        self.assertFalse(
            is_prediction_cache_valid({}),
            msg="Missing schema_version must invalidate.",
        )
        self.assertTrue(
            is_prediction_cache_valid({
                "schema_version": "pr15b_v1",
                "model_coefficients_hash": "abc",
            }),
            msg="Current schema_version='pr15b_v1' must be valid.",
        )

    def test_ensemble_trigger_at_brier_divergence_14_9_pct_no_fire(self):
        """L6 + T7 — divergence < 15% must NOT trigger ensemble.

        modern_brier=0.1, legacy_brier=0.087 → divergence=14.94%."""
        try:
            from lib.statistical_engine.live_mutation import (
                should_fire_ensemble,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement should_fire_ensemble("
                "modern_brier: float, legacy_brier: float) -> bool. "
                "Returns True iff (modern_brier - legacy_brier) / "
                "legacy_brier > 0.15. Lock L6 formula."
            )
        # divergence = (0.1 - 0.087) / 0.087 = 0.1494
        self.assertFalse(
            should_fire_ensemble(0.1, 0.087),
            msg=(
                "T7 boundary: divergence=14.94% must NOT fire. "
                "Stage 3 L6: strict > comparison, not >=."
            ),
        )

    def test_ensemble_trigger_at_brier_divergence_15_1_pct_fires(self):
        """L6 + T7 — divergence > 15% triggers ensemble.

        modern_brier=0.1, legacy_brier=0.0868 → divergence=15.21%."""
        try:
            from lib.statistical_engine.live_mutation import (
                should_fire_ensemble,
                combine_ensemble_probs,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement should_fire_ensemble + "
                "combine_ensemble_probs(p_modern, p_legacy) -> float. "
                "L6: divergence > 15%. Combination formula: "
                "P_final = 0.7 * P_modern + 0.3 * P_legacy."
            )
        # divergence = (0.1 - 0.0868) / 0.0868 = 0.1521
        self.assertTrue(
            should_fire_ensemble(0.1, 0.0868),
            msg="T7 boundary: divergence=15.21% MUST fire ensemble.",
        )
        # Combination check: 0.7 * 0.4 + 0.3 * 0.6 = 0.46
        combined = combine_ensemble_probs(0.4, 0.6)
        self.assertAlmostEqual(
            combined, 0.46, delta=1e-6,
            msg=(
                f"Ensemble formula must be 0.7 * P_modern + 0.3 * "
                f"P_legacy. Expected 0.46, got {combined}."
            ),
        )

    def test_prediction_cache_anchored_baseline_label_format(self):
        """L8 — exact format: f'{borough} {project_type} macro baseline'.
        Drives UX copy in PR #15D."""
        try:
            from lib.statistical_engine.live_mutation import (
                format_anchored_baseline_label,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement format_anchored_baseline_"
                "label(borough: str, project_type: str) -> str. "
                "Returns exactly f'{borough} {project_type} macro baseline'."
            )
        self.assertEqual(
            format_anchored_baseline_label("BROOKLYN", "New Building"),
            "BROOKLYN New Building macro baseline",
        )
        self.assertEqual(
            format_anchored_baseline_label("MANHATTAN", "Major Alteration"),
            "MANHATTAN Major Alteration macro baseline",
        )


if __name__ == "__main__":
    unittest.main()
