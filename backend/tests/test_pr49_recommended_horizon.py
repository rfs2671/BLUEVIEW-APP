"""PR #49 — recommended primary horizon (SWO suppression) tests.

The CompliancePanel restructure collapses the 3-horizon forecast to a
single adaptive primary horizon:

  • default 14 days
  • 30 days when an active SWO was issued within the last 7 days
    (DOB cool-off: they were just on site issuing the SWO, so
    short-term re-enforcement is statistically suppressed)

8 tests covering the pure ``_recommended_primary_horizon`` helper +
the prediction-response field wiring.
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
sys.path.insert(0, str(_HERE))


try:
    from lib.statistical_engine.live_mutation import (
        _recommended_primary_horizon,
        DEFAULT_PRIMARY_HORIZON,
        SWO_SUPPRESSED_HORIZON,
        SWO_COOLOFF_DAYS,
    )
    HAS_HELPER = True
except ImportError:
    _recommended_primary_horizon = None   # type: ignore
    DEFAULT_PRIMARY_HORIZON = 14          # type: ignore
    SWO_SUPPRESSED_HORIZON = 30           # type: ignore
    SWO_COOLOFF_DAYS = 7                  # type: ignore
    HAS_HELPER = False


class TestRecommendedHorizon(unittest.TestCase):

    def _require(self):
        if not HAS_HELPER:
            self.fail(
                "_recommended_primary_horizon not implemented. "
                "PR #49 Stage 2.A — add to live_mutation.py."
            )

    def test_recommended_horizon_no_swo_returns_14(self):
        self._require()
        self.assertEqual(
            _recommended_primary_horizon({"is_active": False}),
            DEFAULT_PRIMARY_HORIZON,
        )

    def test_recommended_horizon_active_swo_within_7d_returns_30(self):
        self._require()
        self.assertEqual(
            _recommended_primary_horizon(
                {"is_active": True, "days_since_open": 3},
            ),
            SWO_SUPPRESSED_HORIZON,
        )

    def test_recommended_horizon_active_swo_exactly_7d_returns_30(self):
        """Boundary — 7 days is still inside the cool-off window."""
        self._require()
        self.assertEqual(
            _recommended_primary_horizon(
                {"is_active": True, "days_since_open": SWO_COOLOFF_DAYS},
            ),
            SWO_SUPPRESSED_HORIZON,
        )

    def test_recommended_horizon_active_swo_older_than_7d_returns_14(self):
        self._require()
        self.assertEqual(
            _recommended_primary_horizon(
                {"is_active": True, "days_since_open": 10},
            ),
            DEFAULT_PRIMARY_HORIZON,
        )

    def test_recommended_horizon_inactive_swo_returns_14(self):
        """Even with a recent days_since_open, an inactive SWO doesn't
        suppress — the cool-off only applies while the SWO is open."""
        self._require()
        self.assertEqual(
            _recommended_primary_horizon(
                {"is_active": False, "days_since_open": 2},
            ),
            DEFAULT_PRIMARY_HORIZON,
        )

    def test_recommended_horizon_defaults_when_swo_state_missing(self):
        """None / empty dict → safe default of 14."""
        self._require()
        self.assertEqual(
            _recommended_primary_horizon(None), DEFAULT_PRIMARY_HORIZON,
        )
        self.assertEqual(
            _recommended_primary_horizon({}), DEFAULT_PRIMARY_HORIZON,
        )

    def test_recommended_horizon_accepts_days_open_alias(self):
        """defcon._resolve_swo_state emits `days_open`; the helper must
        read it as well as the canonical `days_since_open`."""
        self._require()
        self.assertEqual(
            _recommended_primary_horizon(
                {"is_active": True, "days_open": 2},
            ),
            SWO_SUPPRESSED_HORIZON,
        )

    def test_recommended_horizon_active_swo_unknown_age_returns_14(self):
        """Active SWO but no age info (both keys absent) → cannot assert
        cool-off, so fall back to the default 14-day horizon."""
        self._require()
        self.assertEqual(
            _recommended_primary_horizon({"is_active": True}),
            DEFAULT_PRIMARY_HORIZON,
        )


class TestPredictionResponseField(unittest.TestCase):

    def test_prediction_response_includes_recommended_primary_horizon(self):
        if not HAS_HELPER:
            self.skipTest("helper not implemented yet")
        import server  # heavy import, lazy to keep other tests fast
        # No prediction cache → unavailable response, but the new field
        # must still be present with the safe default.
        resp = server.serialize_prediction_cache_to_response({})
        self.assertTrue(hasattr(resp, "recommended_primary_horizon"))
        self.assertEqual(
            resp.recommended_primary_horizon, DEFAULT_PRIMARY_HORIZON,
        )


if __name__ == "__main__":
    unittest.main()
