"""Heartbeat protocol per §2.6 of the permit-renewal v3 plan.

Worker → backend every 60s with:
  ts, queue_depth, last_akamai_success_ts, circuit_breaker state,
  challenge_rate over last 50 requests, storage_state age + request
  count, plus per-job-type metrics distinguishing bis_scrape from
  dob_now_filing.

Backend's heartbeat-watchdog (this commit) flags workers as degraded
if no heartbeat in 30 minutes; email escalation lands in MR.9.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional


logger = logging.getLogger(__name__)


HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "60"))


class HeartbeatState:
    """Mutable snapshot of worker state. dob_worker.py + handlers
    write into this; the heartbeat task reads + ships."""

    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.last_akamai_success_ts: Optional[str] = None
        self.circuit_breaker: Dict[str, str] = {  # per-job-type
            "bis_scrape": "closed",
            "dob_now_filing": "closed",
        }
        self.challenge_rate_50req: Dict[str, float] = {
            "bis_scrape": 0.0,
            "dob_now_filing": 0.0,
        }
        # Per-job-type counters for the report.
        self.jobs_completed: Dict[str, int] = {
            "bis_scrape": 0,
            "dob_now_filing": 0,
        }
        self.jobs_failed: Dict[str, int] = {
            "bis_scrape": 0,
            "dob_now_filing": 0,
        }
        # Queue depth — set by the dispatch loop on each poll.
        self.queue_depth: int = 0

    def snapshot(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "queue_depth": self.queue_depth,
            "last_akamai_success_ts": self.last_akamai_success_ts,
            "circuit_breaker": dict(self.circuit_breaker),
            "challenge_rate_50req": dict(self.challenge_rate_50req),
            "jobs_completed": dict(self.jobs_completed),
            "jobs_failed": dict(self.jobs_failed),
        }


async def heartbeat_loop(
    state: HeartbeatState,
    *,
    backend_url: str,
    http_client,
    interval_seconds: Optional[int] = None,
    max_retries: int = 3,
):
    """Forever-loop that POSTs state.snapshot() to
    /api/internal/agent-heartbeat every N seconds. Backoff retries
    on 5xx; logs and continues on 4xx."""
    interval = interval_seconds or HEARTBEAT_INTERVAL_SECONDS
    while True:
        await asyncio.sleep(interval)
        payload = state.snapshot()
        for attempt in range(max_retries):
            try:
                resp = await http_client.post(
                    f"{backend_url}/api/internal/agent-heartbeat",
                    json=payload,
                )
                if resp.status_code == 200:
                    break
                if 500 <= resp.status_code < 600:
                    logger.warning(
                        "[heartbeat] %s on attempt %d; retrying",
                        resp.status_code, attempt + 1,
                    )
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.warning(
                    "[heartbeat] non-retryable %s response: %s",
                    resp.status_code, resp.text,
                )
                break
            except Exception as e:
                logger.warning("[heartbeat] exception on attempt %d: %s",
                               attempt + 1, e)
                await asyncio.sleep(2 ** attempt)
