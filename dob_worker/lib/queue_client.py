"""Redis queue client for the dob_worker dispatch loop.

Plain Redis BRPOP pattern — chosen over BullMQ because the Python
BullMQ ecosystem is immature (no maintained client; the JS BullMQ
wire format is undocumented for foreign-language consumers).

Job message shape (per MR.5 task 6):
    {
      "id": "<uuid>",
      "type": "bis_scrape" | "dob_now_filing",
      "data": { ... type-specific payload ... },
      "idempotency_key": "{type}:{permit_renewal_id_or_license_number}:{day_bucket}",
      "enqueued_at": "<iso8601>"
    }

Queue key: levelog:filing-queue (configurable via QUEUE_KEY env var).

Idempotency: BRPOP removes the job atomically. Before the handler
runs, the worker calls the cloud's /api/internal/permit-renewal-claim
endpoint to record a claim. The cloud refuses claims for renewals
already in {filed, in_progress, awaiting_dob_approval}. If the cloud
returns 409, the worker acks the job (drops it) and continues.

Crash safety: a stale-claim watchdog scheduled job in the backend
(every 5 min, this commit) returns claims older than 30 minutes
back to the queue. The worker doesn't need to handle crash recovery
beyond writing the claim before processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional


logger = logging.getLogger(__name__)


QUEUE_KEY = os.environ.get("QUEUE_KEY", "levelog:filing-queue")
BRPOP_TIMEOUT_SECONDS = int(os.environ.get("BRPOP_TIMEOUT_SECONDS", "5"))


class QueueClient:
    """Thin wrapper over redis.asyncio for the worker's dispatch loop.

    Constructed once at boot. The poll() coroutine runs forever,
    yielding decoded job dicts as they arrive. Cancellation-safe:
    asyncio.CancelledError propagates cleanly (caller cancels on
    SIGTERM)."""

    def __init__(self, redis_url: str, queue_key: Optional[str] = None):
        self._redis_url = redis_url
        self._queue_key = queue_key or QUEUE_KEY
        self._redis = None  # initialized on first poll

    async def _connect(self):
        if self._redis is not None:
            return
        # Import here so tests can patch / so the module loads even
        # without redis available (e.g., in static analysis).
        import redis.asyncio as redis_asyncio
        self._redis = redis_asyncio.from_url(
            self._redis_url, encoding="utf-8", decode_responses=True,
        )
        logger.info("[queue] connected to %s, key=%s", self._redis_url, self._queue_key)

    async def poll_one(self) -> Optional[Dict[str, Any]]:
        """Single BRPOP iteration. Returns the decoded job dict or
        None if the timeout elapsed with no job available. The
        outer dispatch loop calls this repeatedly."""
        await self._connect()
        result = await self._redis.brpop(self._queue_key, timeout=BRPOP_TIMEOUT_SECONDS)
        if result is None:
            return None
        # redis-py returns (key, value); value is the JSON string.
        _key, raw = result
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("[queue] dropping malformed job (id unknown): %s", e)
            return None

    async def close(self):
        if self._redis is not None:
            await self._redis.close()


async def claim_renewal(
    http_client,
    permit_renewal_id: str,
    *,
    backend_url: str,
    worker_id: str,
) -> bool:
    """Ask the cloud to record a claim on this renewal. Returns True
    if the claim was accepted (worker proceeds), False if the cloud
    refused (renewal already in a terminal-or-in-progress state →
    worker drops the job)."""
    if not permit_renewal_id:
        # bis_scrape jobs don't carry a permit_renewal_id — they're
        # not bound to renewal state. Auto-claim by returning True.
        return True
    resp = await http_client.post(
        f"{backend_url}/api/internal/permit-renewal-claim",
        json={"permit_renewal_id": permit_renewal_id, "worker_id": worker_id},
    )
    if resp.status_code == 200:
        return True
    if resp.status_code == 409:
        logger.info(
            "[queue] claim refused for permit_renewal_id=%s (already in progress)",
            permit_renewal_id,
        )
        return False
    logger.warning(
        "[queue] unexpected claim response %s for %s",
        resp.status_code, permit_renewal_id,
    )
    return False


async def post_result(
    http_client,
    *,
    backend_url: str,
    job_id: str,
    job_type: str,
    permit_renewal_id: Optional[str],
    result_dict: Dict[str, Any],
    worker_id: str,
):
    """Post the handler's result to the cloud. Cloud transitions
    permit_renewals state based on result_dict['status']."""
    payload = {
        "job_id": job_id,
        "job_type": job_type,
        "permit_renewal_id": permit_renewal_id,
        "worker_id": worker_id,
        "result": result_dict,
    }
    resp = await http_client.post(
        f"{backend_url}/api/internal/job-result",
        json=payload,
    )
    if resp.status_code != 200:
        logger.warning(
            "[queue] /job-result returned %s: %s", resp.status_code, resp.text,
        )
