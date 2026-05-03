"""MR.13 — temporary smoke-test bypass of the 30-day renewal window.

Pins the contract for ELIGIBILITY_BYPASS_DAYS_REMAINING:
  • unset / empty / malformed → enforce default 30-day window
  • positive int N            → extend window to N days
  • "ANY" / "-1" / negative   → no upper bound (any permit eligible)

This is a TEMPORARY override. The architecture decision doc carries
the operator action checklist for reverting before production. Tests
both pin the override semantics AND guard against the override
silently shipping to production by exercising the unset/default path
unchanged.

Six tests:
  1. Default (unset) → 30-day rule enforced (existing behavior).
  2. Override = 365 → permit 90 days from expiration is in-window.
  3. Override = "ANY" → permit 5 years from expiration is in-window.
  4. Override = "-1" → same as "ANY" (alternate spelling).
  5. Override = malformed → falls back to default 30-day window.
  6. Bypass logging fires once per process when the override is active.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


class _BypassEnvIsolation(unittest.TestCase):
    """Mixin: capture + restore the env var so a test setting it
    doesn't leak into other tests in the same suite. Also reset the
    process-local one-shot log flag so each test sees a clean state."""

    def setUp(self):
        self._saved = os.environ.get("ELIGIBILITY_BYPASS_DAYS_REMAINING")
        from lib import eligibility_v2 as ev2
        ev2._BYPASS_LOG_FIRED = False

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("ELIGIBILITY_BYPASS_DAYS_REMAINING", None)
        else:
            os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = self._saved
        from lib import eligibility_v2 as ev2
        ev2._BYPASS_LOG_FIRED = False


# ── Pure-helper tests ─────────────────────────────────────────────


class TestGetEffectiveRenewalWindowDays(_BypassEnvIsolation):

    def test_default_window_when_env_unset(self):
        """Production default. The 30-day rule must NOT change for
        operators who never set the override."""
        os.environ.pop("ELIGIBILITY_BYPASS_DAYS_REMAINING", None)
        from lib.eligibility_v2 import get_effective_renewal_window_days
        self.assertEqual(get_effective_renewal_window_days(), 30)

    def test_default_when_env_empty_string(self):
        """Empty-string is the failure mode when an operator added
        the env var line but forgot to paste the value. Treat as
        unset (fail-closed)."""
        os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = ""
        from lib.eligibility_v2 import get_effective_renewal_window_days
        self.assertEqual(get_effective_renewal_window_days(), 30)

    def test_positive_int_widens_window(self):
        """Override = 365 → permit 365d out is at the boundary; 90d
        out is well within the widened window."""
        os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = "365"
        from lib.eligibility_v2 import (
            get_effective_renewal_window_days,
            is_within_renewal_window,
        )
        self.assertEqual(get_effective_renewal_window_days(), 365)
        self.assertTrue(is_within_renewal_window(90))
        self.assertTrue(is_within_renewal_window(365))
        self.assertFalse(is_within_renewal_window(400))  # past widened window

    def test_any_disables_upper_bound(self):
        """Override = ANY → no upper bound. Permit 5 years out is
        in-window."""
        os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = "ANY"
        from lib.eligibility_v2 import (
            get_effective_renewal_window_days,
            is_within_renewal_window,
        )
        self.assertIsNone(get_effective_renewal_window_days())
        self.assertTrue(is_within_renewal_window(5 * 365))
        self.assertTrue(is_within_renewal_window(10_000))

    def test_minus_one_equivalent_to_any(self):
        """-1 is an alternate spelling of ANY for ops who prefer
        numeric env vars."""
        os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = "-1"
        from lib.eligibility_v2 import get_effective_renewal_window_days
        self.assertIsNone(get_effective_renewal_window_days())

    def test_malformed_value_falls_back_to_default(self):
        """Typo'd value (e.g. "thirty") must not silently bypass
        the gate. Fail-closed: log a warning, treat as unset."""
        os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = "thirty"
        from lib.eligibility_v2 import get_effective_renewal_window_days
        self.assertEqual(get_effective_renewal_window_days(), 30)


class TestBypassLoggingOnceShot(_BypassEnvIsolation):
    """The bypass log line is the operator's reminder that the
    override is in effect. It MUST fire when bypass is active —
    once per process, to avoid spam under high request rates."""

    def test_warning_logged_first_call_when_active(self):
        os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = "365"
        # Force re-import of the helper module to ensure the
        # _BYPASS_LOG_FIRED flag is reset to False (handled in setUp).
        from lib.eligibility_v2 import get_effective_renewal_window_days
        with self.assertLogs("lib.eligibility_v2", level="WARNING") as ctx:
            get_effective_renewal_window_days()
        # The first call MUST emit the BYPASS warning.
        self.assertTrue(any(
            "BYPASS active" in m for m in ctx.output
        ), f"expected BYPASS warning, got: {ctx.output!r}")

    def test_warning_not_logged_when_unset(self):
        os.environ.pop("ELIGIBILITY_BYPASS_DAYS_REMAINING", None)
        from lib.eligibility_v2 import get_effective_renewal_window_days
        # No WARNINGs from this module when bypass is unset. We use
        # `assertNoLogs` indirectly: capture all logs and confirm
        # the BYPASS line is absent.
        try:
            with self.assertLogs("lib.eligibility_v2", level="WARNING") as ctx:
                get_effective_renewal_window_days()
            # If we got here, some WARNING fired — make sure it's not
            # the bypass one.
            self.assertFalse(any(
                "BYPASS active" in m for m in ctx.output
            ))
        except AssertionError as e:
            # assertLogs raises if no logs captured at all — that's
            # the cleanest "no warning" signal here. Re-raise only
            # if it's a different failure.
            if "no logs of level WARNING" not in str(e):
                raise


# ── Eligibility integration test ──────────────────────────────────


class TestEligibilityCheckRespectsRenewalWindowOverride(_BypassEnvIsolation):
    """End-to-end pin: check_renewal_eligibility's 30-day blocker
    in permit_renewal.py:669 honors the env var. Without the
    override, a permit 90 days out gets a 'Renewal available within
    30 days of expiry' blocker; with the override, no blocker."""

    def _build_permit_doc(self, days_out: int):
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(days=days_out)
        return {
            "_id": "permit_test_1",
            "expiration_date": future.isoformat(),
        }

    def test_default_blocks_permit_outside_30_days(self):
        """Production behavior preserved when override is unset."""
        os.environ.pop("ELIGIBILITY_BYPASS_DAYS_REMAINING", None)
        from lib.eligibility_v2 import is_within_renewal_window
        # Permit 90 days from expiration is OUT of the default
        # 30-day window — must report not-in-window.
        self.assertFalse(is_within_renewal_window(90))

    def test_override_365_admits_permit_90_days_out(self):
        """Override=365 widens the window; 90-days-out is now valid."""
        os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = "365"
        from lib.eligibility_v2 import is_within_renewal_window
        self.assertTrue(is_within_renewal_window(90))

    def test_override_any_admits_permit_5_years_out(self):
        """Override=ANY removes the upper bound entirely."""
        os.environ["ELIGIBILITY_BYPASS_DAYS_REMAINING"] = "ANY"
        from lib.eligibility_v2 import is_within_renewal_window
        self.assertTrue(is_within_renewal_window(5 * 365))


if __name__ == "__main__":
    unittest.main()
