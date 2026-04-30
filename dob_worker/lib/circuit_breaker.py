"""Per-job-type circuit breaker.

Per §2.5 of the permit-renewal v3 plan: pause 30 minutes if
challenge_rate > 10% over the last 50 requests, evaluated per job
type. Independent breakers for bis_scrape vs dob_now_filing so a
spike in one doesn't trip the other.

Records pass through as a sliding window of the last 50 outcomes
(boolean: True = challenge encountered, False = clean). When the
window is full (50 entries) AND the True-rate exceeds 0.10, the
breaker trips. While tripped, calls to should_proceed() return False
for 30 minutes.
"""

from __future__ import annotations

import logging
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Optional


logger = logging.getLogger(__name__)


WINDOW_SIZE = int(os.environ.get("BREAKER_WINDOW_SIZE", "50"))
TRIP_THRESHOLD = float(os.environ.get("BREAKER_TRIP_THRESHOLD", "0.10"))
PAUSE_MINUTES = int(os.environ.get("BREAKER_PAUSE_MINUTES", "30"))


class CircuitBreaker:
    """Single breaker (one per job_type). Caller maintains
    a registry { job_type: CircuitBreaker } and routes records by
    job type."""

    def __init__(self, name: str):
        self.name = name
        self._window: Deque[bool] = deque(maxlen=WINDOW_SIZE)
        self._tripped_until: Optional[datetime] = None

    def record(self, challenged: bool) -> None:
        """Append an outcome to the rolling window. Trips the
        breaker if the threshold is met."""
        self._window.append(bool(challenged))
        if len(self._window) >= WINDOW_SIZE:
            rate = sum(1 for x in self._window if x) / float(len(self._window))
            if rate > TRIP_THRESHOLD and not self.is_tripped():
                self._tripped_until = (
                    datetime.now(timezone.utc) + timedelta(minutes=PAUSE_MINUTES)
                )
                logger.warning(
                    "[breaker] %s TRIPPED at challenge_rate=%.2f; paused until %s",
                    self.name, rate, self._tripped_until.isoformat(),
                )

    def challenge_rate(self) -> float:
        if not self._window:
            return 0.0
        return sum(1 for x in self._window if x) / float(len(self._window))

    def is_tripped(self) -> bool:
        if self._tripped_until is None:
            return False
        if datetime.now(timezone.utc) >= self._tripped_until:
            self._tripped_until = None
            self._window.clear()
            logger.info("[breaker] %s recovered; resumed", self.name)
            return False
        return True

    def state_label(self) -> str:
        return "open" if self.is_tripped() else "closed"

    def should_proceed(self) -> bool:
        return not self.is_tripped()


class BreakerRegistry:
    """One CircuitBreaker per job_type; auto-creates on first
    access."""

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}

    def get(self, job_type: str) -> CircuitBreaker:
        if job_type not in self._breakers:
            self._breakers[job_type] = CircuitBreaker(job_type)
        return self._breakers[job_type]

    def state_summary(self) -> Dict[str, str]:
        return {jt: br.state_label() for jt, br in self._breakers.items()}

    def challenge_rates(self) -> Dict[str, float]:
        return {jt: br.challenge_rate() for jt, br in self._breakers.items()}
