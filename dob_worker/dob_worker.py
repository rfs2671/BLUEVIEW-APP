"""dob_worker — main orchestrator.

Entry point for the local Docker worker. Boots:
  1. Heartbeat task (60s interval)
  2. Queue dispatch loop (Redis BRPOP → handler routing)
  3. The legacy bis_scrape internal scheduler (preserved verbatim)

All three run concurrently as asyncio tasks. SIGTERM cancels them
cleanly via asyncio.gather + cancellation propagation.

This module replaces `python -u bis_scraper.py` as the container's
entrypoint command. The bis_scrape behavior is preserved 1:1 — the
same internal APScheduler that bis_scrape.py boots when run standalone
is still booted here, just inside a larger orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Optional

# Path bootstrap: when run as `python -u dob_worker.py` from /app,
# imports of sibling subpackages (handlers, lib) need /app on sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from handlers import HANDLERS, get_handler  # noqa: E402
from lib.circuit_breaker import BreakerRegistry  # noqa: E402
from lib.handler_types import HandlerContext, HandlerResult  # noqa: E402
from lib.heartbeat import HeartbeatState, heartbeat_loop  # noqa: E402
from lib.queue_client import QueueClient, claim_renewal, post_result  # noqa: E402


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dob_worker")


WORKER_ID = os.environ.get("WORKER_ID", "dob-worker-local-1")
BACKEND_URL = os.environ.get("BACKEND_URL", "https://api.levelog.com")
WORKER_SECRET = os.environ.get("WORKER_SECRET", "")
REDIS_URL = os.environ.get("REDIS_URL", "")
ELIGIBILITY_REWRITE_MODE = os.environ.get("ELIGIBILITY_REWRITE_MODE", "off")


# ── HTTP client factory ────────────────────────────────────────────

def _build_http_client():
    """Preconfigured httpx.AsyncClient with X-Worker-Secret pre-applied
    on every request and a generous timeout for backend round-trips."""
    import httpx
    headers = {"X-Worker-Secret": WORKER_SECRET} if WORKER_SECRET else {}
    return httpx.AsyncClient(headers=headers, timeout=30.0)


# ── Dispatcher ─────────────────────────────────────────────────────

async def _dispatch_one(
    job: dict,
    *,
    context: HandlerContext,
    breakers: BreakerRegistry,
    state: HeartbeatState,
):
    """Route a single decoded job to its handler and post the
    result to /api/internal/job-result. Skips if the per-job-type
    breaker is open or if the cloud refuses the renewal claim."""
    job_id = job.get("id") or "no-id"
    job_type = job.get("type") or "unknown"
    data = job.get("data") or {}
    permit_renewal_id = data.get("permit_renewal_id")

    # Hard refuse dob_now_filing jobs when the dispatcher is not in
    # live mode — defensive against accidental enqueues during
    # shadow-mode testing.
    if job_type == "dob_now_filing" and ELIGIBILITY_REWRITE_MODE != "live":
        logger.warning(
            "[dispatch] refusing dob_now_filing job %s — ELIGIBILITY_REWRITE_MODE=%s, expected 'live'",
            job_id, ELIGIBILITY_REWRITE_MODE,
        )
        await post_result(
            context.http_client,
            backend_url=BACKEND_URL,
            job_id=job_id,
            job_type=job_type,
            permit_renewal_id=permit_renewal_id,
            result_dict=HandlerResult(
                status="failed",
                detail=f"Worker refused job: ELIGIBILITY_REWRITE_MODE={ELIGIBILITY_REWRITE_MODE}",
                metadata={},
            ).to_dict(),
            worker_id=state.worker_id,
        )
        return

    breaker = breakers.get(job_type)
    if not breaker.should_proceed():
        logger.warning(
            "[dispatch] breaker open for %s; dropping job %s",
            job_type, job_id,
        )
        return

    handler = get_handler(job_type)
    if handler is None:
        logger.warning("[dispatch] no handler for job_type=%s; dropping", job_type)
        await post_result(
            context.http_client,
            backend_url=BACKEND_URL,
            job_id=job_id,
            job_type=job_type,
            permit_renewal_id=permit_renewal_id,
            result_dict=HandlerResult(
                status="failed",
                detail=f"Unknown job_type: {job_type}",
                metadata={},
            ).to_dict(),
            worker_id=state.worker_id,
        )
        state.jobs_failed[job_type] = state.jobs_failed.get(job_type, 0) + 1
        return

    # Idempotency: claim the renewal before processing.
    claimed = await claim_renewal(
        context.http_client, permit_renewal_id,
        backend_url=BACKEND_URL, worker_id=state.worker_id,
    )
    if not claimed:
        logger.info(
            "[dispatch] claim refused for %s — dropping job", permit_renewal_id,
        )
        return

    try:
        result = await handler(data, context)
    except Exception as e:
        logger.exception("[dispatch] handler %s raised: %s", job_type, e)
        breaker.record(challenged=True)
        result = HandlerResult(
            status="failed",
            detail=f"Handler exception: {type(e).__name__}: {e}",
            metadata={},
        )
        state.jobs_failed[job_type] = state.jobs_failed.get(job_type, 0) + 1
    else:
        # Treat handler success / not_implemented as non-challenge.
        breaker.record(challenged=False)
        if result.status in ("filed", "completed"):
            state.jobs_completed[job_type] = state.jobs_completed.get(job_type, 0) + 1
        elif result.status == "failed":
            state.jobs_failed[job_type] = state.jobs_failed.get(job_type, 0) + 1

    await post_result(
        context.http_client,
        backend_url=BACKEND_URL,
        job_id=job_id,
        job_type=job_type,
        permit_renewal_id=permit_renewal_id,
        result_dict=result.to_dict(),
        worker_id=state.worker_id,
    )


# ── Loops ──────────────────────────────────────────────────────────

async def _queue_dispatch_loop(
    queue: QueueClient,
    *,
    context: HandlerContext,
    breakers: BreakerRegistry,
    state: HeartbeatState,
):
    """Forever-loop polling Redis. One job at a time; the worker
    serializes execution by design (concurrency added in v2)."""
    while True:
        job = await queue.poll_one()
        if job is None:
            continue  # BRPOP timeout, no job
        # Update queue-depth on the heartbeat snapshot. Real depth
        # would require a separate LLEN call; for v1 we just signal
        # "had a job" with 1, decrementing on completion. v2 can
        # add proper depth measurement.
        state.queue_depth = 1
        try:
            await _dispatch_one(
                job, context=context, breakers=breakers, state=state,
            )
        finally:
            state.queue_depth = 0


async def _bis_scrape_scheduler():
    """Boots the legacy bis_scrape internal scheduler. Preserved
    verbatim — bis_scrape.py runs its own APScheduler + scan loop
    when its main() is invoked. We invoke that here so the existing
    BIS scraping behavior is unchanged from the operator's
    perspective.

    Imported lazily to keep startup ordering predictable (Playwright
    Chromium boot inside the legacy module shouldn't race with
    queue/heartbeat init)."""
    from handlers import bis_scrape
    # bis_scrape.main() is sync (calls asyncio.run internally); we
    # call its async core (_run_forever) directly so the periodic
    # scan runs inside our existing event loop instead of spawning
    # a new one. Behavior identical to running bis_scrape.py
    # standalone.
    if hasattr(bis_scrape, "_run_forever"):
        await bis_scrape._run_forever()
    else:
        logger.error(
            "[bis_scrape] module has no _run_forever(); legacy scraper not "
            "started. Existing behavior may be broken — investigate."
        )


# ── Main ───────────────────────────────────────────────────────────

async def main():
    logger.info("[dob_worker] booting worker_id=%s", WORKER_ID)
    if not REDIS_URL:
        logger.warning(
            "[dob_worker] REDIS_URL not set; queue dispatch loop will idle. "
            "bis_scrape continues normally."
        )
    if not WORKER_SECRET:
        logger.warning(
            "[dob_worker] WORKER_SECRET not set; backend will reject "
            "/api/internal/* posts. Set WORKER_SECRET to authenticate."
        )

    http_client = _build_http_client()
    state = HeartbeatState(worker_id=WORKER_ID)
    breakers = BreakerRegistry()
    context = HandlerContext(
        worker_id=WORKER_ID,
        http_client=http_client,
        heartbeat_push=None,  # interim pushes are MR.6+ territory
        browser=None,  # bis_scrape creates its own browser; dob_now_filing in MR.6
    )

    tasks = []

    # 1. Heartbeat loop
    tasks.append(asyncio.create_task(
        heartbeat_loop(state, backend_url=BACKEND_URL, http_client=http_client),
        name="heartbeat",
    ))

    # 2. Queue dispatch loop (only if Redis configured)
    if REDIS_URL:
        queue = QueueClient(REDIS_URL)
        tasks.append(asyncio.create_task(
            _queue_dispatch_loop(queue, context=context, breakers=breakers, state=state),
            name="queue_dispatch",
        ))

    # 3. Legacy bis_scrape scheduler (preserved verbatim)
    tasks.append(asyncio.create_task(
        _bis_scrape_scheduler(),
        name="bis_scrape_scheduler",
    ))

    # Cancellation handling — SIGTERM from Docker sends to the asyncio loop.
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _stop(*_):
        logger.info("[dob_worker] SIGTERM received; cancelling tasks")
        stop_event.set()
        for t in tasks:
            t.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler on the
            # default ProactorEventLoop. Ignore — Docker on Windows
            # still kills the container, just less gracefully.
            pass

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await http_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
