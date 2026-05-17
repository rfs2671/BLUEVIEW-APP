"""PR #15B.1 — T2 cohort baseline rate helper tests.

2 tests in TestCohortBaselineRate:
  1. test_returns_mean_non_censored_outcome_rate
  2. test_returns_zero_for_empty_or_all_censored
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


try:
    from lib.statistical_engine.live_mutation import (  # type: ignore
        compute_cohort_baseline_rate,
    )
    HAS_HELPER = True
except ImportError:
    compute_cohort_baseline_rate = None  # type: ignore
    HAS_HELPER = False


class TestCohortBaselineRate(unittest.TestCase):
    """T2 lock — replaces training_brier_score as the
    anchored_baseline_prob_14d proxy. Brier measures accuracy,
    not base rate; cohort mean IS the base rate."""

    def _require(self):
        if not HAS_HELPER:
            self.fail(
                "Stage 3 PR #15B.1 (T2): implement "
                "lib.statistical_engine.live_mutation."
                "compute_cohort_baseline_rate("
                "panel_rows: List[Dict[str, Any]]) -> float\n"
                "Returns mean of outcome_violation_d_to_d_plus_7 over "
                "rows where outcome is not None (drops right-censored "
                "trailing-7 rows per PR #15A T5). Returns 0.0 for "
                "empty / all-censored. Used by "
                "predict_for_project_nightly to populate "
                "anchored_baseline_prob_14d in the prediction_cache "
                "(replacing training_brier_score-as-baseline at "
                "live_mutation.py:1113)."
            )

    def test_returns_mean_non_censored_outcome_rate(self):
        """3 True + 5 False + 2 None (censored) → rate = 3/8 = 0.375."""
        self._require()
        rows = (
            [{"outcome_violation_d_to_d_plus_7": True}  for _ in range(3)]
            + [{"outcome_violation_d_to_d_plus_7": False} for _ in range(5)]
            + [{"outcome_violation_d_to_d_plus_7": None}  for _ in range(2)]
        )
        rate = compute_cohort_baseline_rate(rows)
        self.assertAlmostEqual(
            rate, 0.375, delta=1e-6,
            msg=f"T2: expected mean(True=1, False=0) over 8 non-censored "
                f"rows = 3/8 = 0.375. Got {rate}.",
        )

    def test_returns_zero_for_empty_or_all_censored(self):
        """Empty list → 0.0; all-None outcomes → 0.0."""
        self._require()
        self.assertEqual(
            compute_cohort_baseline_rate([]), 0.0,
            msg="T2: empty list must return 0.0 (not crash, not NaN)",
        )
        rows = [{"outcome_violation_d_to_d_plus_7": None} for _ in range(5)]
        self.assertEqual(
            compute_cohort_baseline_rate(rows), 0.0,
            msg="T2: all-censored panel must return 0.0",
        )


if __name__ == "__main__":
    unittest.main()
