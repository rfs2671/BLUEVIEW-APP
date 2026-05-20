"""PR #15B — prediction_cache sub-document shape + label format.

3 tests in TestPredictionCache:
  1. test_prediction_cache_shape_matches_spec
  2. test_prediction_cache_schema_version_invalidation
  3. test_prediction_cache_anchored_baseline_label_format (L8)

PR #15D.2 — the L6/T7 ensemble-trigger tests were removed alongside the
should_fire_ensemble + combine_ensemble_probs helpers, which were never
called from any production inference path (spec audit §3.5). The deployed
fit pipeline is a single sklearn LogisticRegression over weighted rows
(modern=1.0, legacy=0.4) — no separate legacy fit, no p_legacy.
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
    "schedule_position_ratio",
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
                "schedule_position_ratio": 0.01,
                "district_caseload_proxy_days": 0.05,
            },
            x_now_standardized={
                "active_swo_flag": 0.0, "complaint_velocity_14d": 0.0,
                "days_since_last_violation": 0.0,
                "schedule_position_ratio": 0.0,
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
