"""PR #15B.1 — T1 discrete-time hazard math tests.

5 tests in TestDiscreteTimeHazard:
  1. test_zero_probability_propagates              (edge: p_7=0)
  2. test_one_probability_propagates               (edge: p_7=1)
  3. test_low_risk_5pct_diverges_from_poisson      (Stage 1 verified)
  4. test_high_risk_50pct_diverges_from_poisson    (Stage 1 verified)
  5. test_numerical_clipping_handles_sigmoid_artifacts  (defensive)

All RED at Stage 2.B until _discrete_time_hazard_horizons lands in
Stage 3 (live_mutation.py).
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
        _discrete_time_hazard_horizons,
    )
    HAS_DTH = True
except ImportError:
    _discrete_time_hazard_horizons = None  # type: ignore
    HAS_DTH = False


class TestDiscreteTimeHazard(unittest.TestCase):
    """T1 lock — discrete-time hazard math replaces PR #15B's Poisson
    extrapolation. Formula: daily_hazard = 1 - (1 - p_7)**(1/7);
    then p_n = 1 - (1 - daily_hazard)**n. Pure helper; no I/O."""

    def _require(self):
        if not HAS_DTH:
            self.fail(
                "Stage 3 PR #15B.1 (T1): implement "
                "lib.statistical_engine.live_mutation."
                "_discrete_time_hazard_horizons(prob_7d: float) -> "
                "Tuple[float, float, float]\n"
                "Returns (prob_7d, prob_14d, prob_30d) via discrete-"
                "time hazard math:\n"
                "    daily = 1 - (1 - clip(p_7, 0, 1)) ** (1/7)\n"
                "    p_n   = 1 - (1 - daily) ** n\n"
                "Replaces Poisson extrapolation at 2 sites in "
                "live_mutation.py (predict_for_project_nightly + "
                "predict_for_project_live)."
            )

    # ── Test 1 — zero edge case ──────────────────────────────

    def test_zero_probability_propagates(self):
        """Edge: p_7=0 → daily=0 → all horizons = 0."""
        self._require()
        p7, p14, p30 = _discrete_time_hazard_horizons(0.0)
        self.assertAlmostEqual(p7, 0.0, delta=1e-9)
        self.assertAlmostEqual(p14, 0.0, delta=1e-9)
        self.assertAlmostEqual(
            p30, 0.0, delta=1e-9,
            msg="Stage 3 T1 edge case: prob_7d=0 must yield prob_30d=0. "
                "Verifies numerator zero propagates through hazard math.",
        )

    # ── Test 2 — unit edge case ──────────────────────────────

    def test_one_probability_propagates(self):
        """Edge: p_7=1 → daily=1 → all horizons = 1 (asymptote)."""
        self._require()
        p7, p14, p30 = _discrete_time_hazard_horizons(1.0)
        self.assertAlmostEqual(p7, 1.0, delta=1e-9)
        self.assertAlmostEqual(p14, 1.0, delta=1e-9)
        self.assertAlmostEqual(
            p30, 1.0, delta=1e-9,
            msg="Stage 3 T1 edge case: prob_7d=1 must yield "
                "prob_30d=1 (asymptote). Math: 1 - 0**n == 1.",
        )

    # ── Test 3 — low risk divergence from Poisson ────────────

    def test_low_risk_5pct_diverges_from_poisson(self):
        """Stage 1 verified: prob_7d=0.05 → prob_14d=0.0975, prob_30d=0.1973.
        Poisson would give prob_14d=0.10, prob_30d=0.2143."""
        self._require()
        p7, p14, p30 = _discrete_time_hazard_horizons(0.05)
        self.assertAlmostEqual(p7, 0.05, delta=1e-6)
        self.assertAlmostEqual(
            p14, 0.0975, delta=0.005,
            msg=f"T1 low-risk 14d: expected ~0.0975 (DTH); got {p14}",
        )
        self.assertAlmostEqual(
            p30, 0.1973, delta=0.005,
            msg=f"T1 low-risk 30d: expected ~0.1973 (DTH, NOT Poisson "
                f"0.2143). Got {p30}",
        )

    # ── Test 4 — high risk divergence from Poisson ───────────

    def test_high_risk_50pct_diverges_from_poisson(self):
        """Stage 1 verified: prob_7d=0.50 → prob_14d=0.75, prob_30d=0.9487.
        Poisson would clamp BOTH to 1.0 (over-fire alerts)."""
        self._require()
        p7, p14, p30 = _discrete_time_hazard_horizons(0.50)
        self.assertAlmostEqual(
            p14, 0.75, delta=0.005,
            msg=f"T1 high-risk 14d: expected ~0.75 (DTH, NOT Poisson "
                f"clamp 1.0). Got {p14}",
        )
        self.assertAlmostEqual(
            p30, 0.9487, delta=0.005,
            msg=f"T1 high-risk 30d: expected ~0.9487 (DTH, NOT Poisson "
                f"clamp 1.0). Got {p30}. The Poisson over-firing "
                f"surfaces here — DTH asymptotes correctly.",
        )

    # ── Test 5 — sigmoid artifact defense ────────────────────

    def test_numerical_clipping_handles_sigmoid_artifacts(self):
        """Defensive: _sigmoid may produce 1.0000001 due to float
        precision; helper must clip to 1.0 before applying the
        formula (otherwise (1 - 1.0000001) is negative → complex)."""
        self._require()
        p7, p14, p30 = _discrete_time_hazard_horizons(1.0000001)
        for h, name in ((p7, "p_7"), (p14, "p_14"), (p30, "p_30")):
            self.assertGreaterEqual(
                h, 0.0,
                msg=f"T1 defensive: {name}={h} negative. Stage 3: "
                    f"clip input prob_7d to [0, 1] before formula.",
            )
            self.assertLessEqual(
                h, 1.0,
                msg=f"T1 defensive: {name}={h} > 1.0. Stage 3: clip "
                    f"input prob_7d to [0, 1].",
            )


if __name__ == "__main__":
    unittest.main()
