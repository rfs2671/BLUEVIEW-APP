"""PR #15D — hazard ratio → color tier helper tests (T8' lock).

7 tests. Pure helper, no I/O, no DB.

Target:
  lib.statistical_engine.live_mutation.hazard_ratio_to_color_tier(
      ratio: Optional[float],
  ) -> str

Returns one of: "green", "yellow", "amber", "orange", "red", "neutral"

L6 thresholds:
  ratio < 0.75               → "green"   (safer than baseline)
  0.75 <= ratio < 1.5        → "yellow"  (typical)
  1.5  <= ratio < 3.0        → "amber"   (above typical)
  3.0  <= ratio < 4.0        → "orange"  (high)
  ratio >= 4.0               → "red"     (critical)
  ratio None / NaN / inf     → "neutral" (unable to compute)
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
        hazard_ratio_to_color_tier,
    )
    HAS_HELPER = True
except ImportError:
    hazard_ratio_to_color_tier = None  # type: ignore
    HAS_HELPER = False


class TestHazardRatioColor(unittest.TestCase):
    """L6 + T8' — 5-tier hazard ratio color mapping. Backend Python
    helper; frontend ports the same logic by hand at Stage 3 per F2."""

    def _require(self):
        if not HAS_HELPER:
            self.fail(
                "Stage 3 PR #15D (L6, T8'): implement "
                "lib.statistical_engine.live_mutation."
                "hazard_ratio_to_color_tier(ratio: Optional[float]) "
                "-> str\n"
                "Returns one of {'green', 'yellow', 'amber', "
                "'orange', 'red', 'neutral'} per L6 thresholds:\n"
                "  ratio < 0.75       → 'green'\n"
                "  0.75 <= r < 1.5    → 'yellow'\n"
                "  1.5 <= r < 3.0     → 'amber'\n"
                "  3.0 <= r < 4.0     → 'orange'\n"
                "  r >= 4.0           → 'red'\n"
                "  None / NaN / inf   → 'neutral'\n"
                "Frontend ports this verbatim at Stage 3 per F2 lock."
            )

    def test_returns_green_for_ratio_below_0_75(self):
        self._require()
        self.assertEqual(hazard_ratio_to_color_tier(0.5), "green")
        self.assertEqual(hazard_ratio_to_color_tier(0.0), "green")
        self.assertEqual(hazard_ratio_to_color_tier(0.749), "green")

    def test_returns_yellow_for_ratio_at_1_0(self):
        self._require()
        self.assertEqual(hazard_ratio_to_color_tier(1.0), "yellow")
        self.assertEqual(hazard_ratio_to_color_tier(0.75), "yellow")
        self.assertEqual(hazard_ratio_to_color_tier(1.49), "yellow")

    def test_returns_amber_for_ratio_at_2_0(self):
        self._require()
        self.assertEqual(hazard_ratio_to_color_tier(2.0), "amber")
        self.assertEqual(hazard_ratio_to_color_tier(1.5), "amber")
        self.assertEqual(hazard_ratio_to_color_tier(2.99), "amber")

    def test_returns_orange_for_ratio_at_3_5(self):
        self._require()
        self.assertEqual(hazard_ratio_to_color_tier(3.5), "orange")
        self.assertEqual(hazard_ratio_to_color_tier(3.0), "orange")
        self.assertEqual(hazard_ratio_to_color_tier(3.99), "orange")

    def test_returns_red_for_ratio_above_4_0(self):
        self._require()
        self.assertEqual(hazard_ratio_to_color_tier(4.0), "red")
        self.assertEqual(hazard_ratio_to_color_tier(5.0), "red")
        self.assertEqual(hazard_ratio_to_color_tier(100.0), "red")

    def test_boundary_at_0_75_returns_yellow_not_green(self):
        """L6 boundary: exact 0.75 is the threshold; >= 0.75 = yellow."""
        self._require()
        self.assertEqual(
            hazard_ratio_to_color_tier(0.75), "yellow",
            msg="L6 boundary: ratio==0.75 must be 'yellow' (>= 0.75 "
                "threshold), NOT 'green'. Avoids confusing border cases.",
        )

    def test_handles_null_or_invalid_ratio_returns_neutral(self):
        import math
        self._require()
        self.assertEqual(hazard_ratio_to_color_tier(None), "neutral")
        self.assertEqual(hazard_ratio_to_color_tier(float("nan")), "neutral")
        self.assertEqual(hazard_ratio_to_color_tier(float("inf")), "neutral")
        # Negative ratio is mathematically impossible (probs are
        # non-negative) but defensive.
        self.assertEqual(
            hazard_ratio_to_color_tier(-1.0), "neutral",
            msg="Negative ratio should yield 'neutral' — math invariant "
                "violated, can't trust the color signal.",
        )


if __name__ == "__main__":
    unittest.main()
