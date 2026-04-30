"""Circuit breaker trip + recovery."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

_DOB_WORKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DOB_WORKER))


class TestCircuitBreaker(unittest.TestCase):

    def test_under_threshold_does_not_trip(self):
        from lib.circuit_breaker import CircuitBreaker
        br = CircuitBreaker("bis_scrape")
        # 50 records, 5 challenges = 10% — exactly at threshold,
        # NOT over (trip condition is strictly > 0.10).
        for _ in range(45):
            br.record(challenged=False)
        for _ in range(5):
            br.record(challenged=True)
        self.assertFalse(br.is_tripped())

    def test_over_threshold_trips(self):
        from lib.circuit_breaker import CircuitBreaker
        br = CircuitBreaker("dob_now_filing")
        # 50 records, 6 challenges = 12% → trip
        for _ in range(44):
            br.record(challenged=False)
        for _ in range(6):
            br.record(challenged=True)
        self.assertTrue(br.is_tripped())
        self.assertFalse(br.should_proceed())

    def test_recovery_after_pause(self):
        from lib.circuit_breaker import CircuitBreaker
        br = CircuitBreaker("bis_scrape")
        for _ in range(50):
            br.record(challenged=True)
        self.assertTrue(br.is_tripped())
        # Fast-forward past the pause window.
        br._tripped_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertFalse(br.is_tripped())
        self.assertTrue(br.should_proceed())

    def test_per_job_type_isolation(self):
        from lib.circuit_breaker import BreakerRegistry
        reg = BreakerRegistry()
        bis = reg.get("bis_scrape")
        dob = reg.get("dob_now_filing")
        for _ in range(50):
            bis.record(challenged=True)  # trip bis only
        self.assertTrue(bis.is_tripped())
        self.assertFalse(dob.is_tripped())
        self.assertEqual(reg.state_summary()["bis_scrape"], "open")
        self.assertEqual(reg.state_summary()["dob_now_filing"], "closed")


if __name__ == "__main__":
    unittest.main()
