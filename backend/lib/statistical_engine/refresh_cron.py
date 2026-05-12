"""Phase V2.3 Commit 5 — Stagger-paced peer_stats_cache refresh cron.

Runs every 15 minutes via APScheduler. Picks up to
``REFRESH_BATCH_SIZE`` projects per tick whose peer_stats_cache
is eligible for refresh:

  • ``status="ready"`` AND ``last_refreshed_at`` older than 14
    days → ``refresh_peer_stats_incremental`` (delta refresh).
  • ``status="failed"`` AND ``failed_at`` older than 24 hours →
    ``compute_peer_stats_full`` (closes Commit 4's retry escape
    hatch, prevents permanently-stuck projects).
  • ``status="pending"`` AND ``started_at`` older than 15 minutes
    → ``compute_peer_stats_full`` (recovers from mid-compute
    process crashes; the prewarm timeout is only 30s so anything
    older than 15 minutes is definitely abandoned).

Pacing IS the feature — projects are processed SEQUENTIALLY
within a tick, not in parallel. With 10 per tick at 15-min
cadence, sustained Socrata throughput is bounded at
40 projects/hour ≈ 600 GETs/hour worst case, well under the
1000/hour authenticated quota.

Per-project workflow:

  1. ``_patch_pending`` writes ``status="pending"`` with fresh
     ``started_at`` BEFORE compute begins. This is the lock —
     Commit 4's ``compare_project_to_peers`` guard returns the
     pending zero-marker for projects in this state, so a
     concurrent user-triggered Recalculate doesn't race the
     refresh.
  2. Construct ``SocrataClient`` (shared across all batched
     projects via one ``ServerHttpClient`` ``async with`` block
     for connection reuse).
  3. Run the appropriate compute function per Option B explicit
     routing (see classify above).
  4. Persist result. Success → full-cache ``$set`` overwrite
     (wipes the pending marker fields). Failure → ``_patch_failed``
     partial $set with ``status="failed"``, ``failed_at``,
     ``error_kind``, ``error_message``.

Per-project failures stay inside this module — sweep continues
across the rest of the batch. The outer try/except in the
server.py ``_peer_stats_refresh_tick`` wrapper handles sweep-
level failures (Mongo blip on the eligibility query, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    from bson import ObjectId  # type: ignore
except ImportError:  # pragma: no cover — bson always available in prod
    ObjectId = None  # type: ignore

from lib.server_http import ServerHttpClient
from lib.statistical_engine.baselines import (
    PEER_STATS_FAILED_RETRY_TTL_HOURS,
    PEER_STATS_FRESH_DAYS,
    compute_peer_stats_full,
    refresh_peer_stats_incremental,
)
from lib.statistical_engine.prewarm import (
    ERROR_KIND_SOCRATA,
    ERROR_KIND_TIMEOUT,
    ERROR_KIND_UNEXPECTED,
)
from lib.statistical_engine.socrata_client import (
    SocrataClient,
    SocrataQueryError,
)


logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────

# How many projects to refresh per tick. Bounded throughput is the
# design intent: 10/tick × 4 ticks/hour = 40 projects/hour
# sustained. Even at 1000 stale projects, that's a 25-hour catch-up
# window which is acceptable — peer stats are 14-day-stale anyway,
# a few extra hours doesn't change the operator experience.
REFRESH_BATCH_SIZE = 10

# Tick cadence — every N minutes via APScheduler IntervalTrigger.
REFRESH_TICK_MINUTES = 15

# Per-project compute budget. More generous than prewarm's 30s
# because the cron is patient — we'd rather succeed slowly than
# fail fast in the background.
REFRESH_COMPUTE_TIMEOUT_SECONDS = 60.0

# Orphan-pending threshold. A ``status="pending"`` cache whose
# ``started_at`` is older than this is considered abandoned
# (whatever process wrote the pending marker has either crashed
# or hung — prewarm's 30s timeout means any pending older than
# ~1 minute is already past the failure boundary, 15 minutes is
# a defensive safety margin).
ORPHAN_PENDING_THRESHOLD_MINUTES = 15


# ── Project-id coercion (mirrors prewarm.py) ──────────────────────


def _to_mongo_id(project_id: Any) -> Any:
    """Coerce a project_id into the Mongo storage form. Accepts
    ObjectId pass-through, 24-char hex strings, or anything else
    as-is."""
    if ObjectId is None or isinstance(project_id, ObjectId):
        return project_id
    if isinstance(project_id, str) and len(project_id) == 24:
        try:
            return ObjectId(project_id)
        except Exception:
            return project_id
    return project_id


# ── Sweep eligibility query ───────────────────────────────────────


def _build_eligibility_query(now: datetime) -> Dict[str, Any]:
    """Return the Mongo query that selects projects eligible for a
    refresh tick.

    Three ``$or`` clauses match the three eligibility classes (see
    module docstring). Cache fields referenced here MUST match
    what Commit 4 actually writes to the project doc:

      • ``status="ready"`` caches have ``last_refreshed_at`` from
        ``_assemble_cache`` (full overwrite).
      • ``status="failed"`` caches have ``failed_at`` from
        ``_patch_failed`` (partial $set after compute failure).
      • ``status="pending"`` caches have ``started_at`` from
        ``_patch_pending`` (partial $set at compute start).
    """
    stale_cutoff = now - timedelta(days=PEER_STATS_FRESH_DAYS)
    failed_cutoff = now - timedelta(hours=PEER_STATS_FAILED_RETRY_TTL_HOURS)
    orphan_cutoff = now - timedelta(minutes=ORPHAN_PENDING_THRESHOLD_MINUTES)
    return {
        "$or": [
            # 1. Stale ready cache (matches Commit 3's _is_cache_stale).
            {
                "peer_stats_cache.status": "ready",
                "peer_stats_cache.last_refreshed_at": {"$lt": stale_cutoff},
            },
            # 2. Failed cache past the 24h retry-escape window
            #    (matches Commit 4's guard in compare_project_to_peers).
            {
                "peer_stats_cache.status": "failed",
                "peer_stats_cache.failed_at": {"$lt": failed_cutoff},
            },
            # 3. Orphaned pending cache (process died mid-compute).
            #    No corresponding Python-side guard — this is purely a
            #    cron-side recovery path.
            {
                "peer_stats_cache.status": "pending",
                "peer_stats_cache.started_at": {"$lt": orphan_cutoff},
            },
        ],
    }


def _classify_eligibility(cache: Dict[str, Any]) -> str:
    """Pick the per-project eligibility kind for Option B routing.

    Returns one of: ``"stale"`` / ``"failed"`` / ``"orphan"`` /
    ``"unknown"``. The kind drives which compute function runs
    (incremental for stale, full recompute for failed/orphan) and
    appears in per-project log lines so an operator can grep the
    log for ``kind=failed`` to find all failed-cache retries.
    """
    status = (cache or {}).get("status")
    if status == "ready":
        return "stale"
    if status == "failed":
        return "failed"
    if status == "pending":
        return "orphan"
    return "unknown"


# ── Per-project cache state writes ────────────────────────────────


async def _patch_pending(
    db, project_id: Any, *, now: datetime,
) -> None:
    """Lock the project for compute. Writes:

      peer_stats_cache.status        = "pending"
      peer_stats_cache.started_at    = now
      peer_stats_cache.error_kind    = ""    (clear prior failure)
      peer_stats_cache.error_message = ""    (clear prior failure)
      peer_stats_cache.failed_at     = None  (clear prior failure)

    Partial ``$set`` so a leftover full cache (success path will
    overwrite later) is preserved field-by-field; peer_criteria
    stays intact so ``refresh_peer_stats_incremental`` can find
    the cached peer-BBL list. Errors are logged + swallowed —
    failure here is non-fatal (next tick will retry).
    """
    try:
        await db.projects.update_one(
            {"_id": _to_mongo_id(project_id)},
            {"$set": {
                "peer_stats_cache.status":        "pending",
                "peer_stats_cache.started_at":    now,
                "peer_stats_cache.error_kind":    "",
                "peer_stats_cache.error_message": "",
                "peer_stats_cache.failed_at":     None,
            }},
        )
    except Exception as e:
        logger.error(
            "[refresh_cron] pending-lock failed for %s: %r",
            project_id, e,
        )


async def _patch_failed(
    db, project_id: Any, *, now: datetime,
    error_kind: str, error_message: str,
) -> None:
    """Stamp a failed marker on a project's cache. Mirrors
    prewarm._patch_cache_status semantics."""
    try:
        await db.projects.update_one(
            {"_id": _to_mongo_id(project_id)},
            {"$set": {
                "peer_stats_cache.status":        "failed",
                "peer_stats_cache.failed_at":     now,
                "peer_stats_cache.error_kind":    error_kind,
                "peer_stats_cache.error_message": (error_message or "")[:500],
            }},
        )
    except Exception as e:
        logger.error(
            "[refresh_cron] failed-marker patch failed for %s: %r",
            project_id, e,
        )


async def _persist_full_cache(
    db, project_id: Any, cache: Dict[str, Any],
) -> bool:
    """Replace peer_stats_cache wholesale with a freshly-computed
    cache. Returns True on success. Wholesale $set wipes any
    leftover failed/pending fields, leaving a clean ready cache.
    """
    try:
        await db.projects.update_one(
            {"_id": _to_mongo_id(project_id)},
            {"$set": {"peer_stats_cache": cache}},
        )
        return True
    except Exception as e:
        logger.exception(
            "[refresh_cron] full-cache persist failed for %s: %r",
            project_id, e,
        )
        return False


# ── Per-project refresh ───────────────────────────────────────────


async def _refresh_one_project(
    db,
    socrata: SocrataClient,
    project: Dict[str, Any],
    *,
    now: datetime,
) -> str:
    """Process a single project. Returns one of these strings,
    which match the stats-dict keys so the caller can ``+= 1``
    them directly:

      • ``"refreshed_stale"``  — status="ready" → incremental ok
      • ``"recovered_failed"`` — status="failed" (>24h) → full ok
      • ``"recovered_orphan"`` — status="pending" (>15m) → full ok
      • ``"failed"``           — compute failed; failed marker
                                 stamped on the project

    Every exception during compute is caught here and converted
    to a "failed" return — the sweep continues over the rest of
    the batch.
    """
    project_id = project.get("_id")
    log_id = str(project_id)
    cache_before = project.get("peer_stats_cache") or {}
    kind = _classify_eligibility(cache_before)

    # Lock-before-compute: stamp pending immediately so a
    # concurrent tick (overlap defense) OR a user-triggered
    # Recalculate sees the pending marker via Commit 4's
    # compare_project_to_peers guard.
    await _patch_pending(db, project_id, now=now)

    # Option B explicit routing per Stage 1 Q4 decision.
    try:
        if kind == "stale":
            # The in-memory ``project`` dict still holds the
            # ORIGINAL cache shape (with peer_criteria.peer_bbl_list,
            # _peer_counts_by_dataset, last_refreshed_at). Only
            # Mongo was patched. refresh_peer_stats_incremental
            # reads from the dict, not Mongo, so it gets the data
            # it needs.
            cache = await asyncio.wait_for(
                refresh_peer_stats_incremental(socrata, project, now=now),
                timeout=REFRESH_COMPUTE_TIMEOUT_SECONDS,
            )
            log_kind = "refreshed_stale"
        elif kind == "failed":
            cache = await asyncio.wait_for(
                compute_peer_stats_full(socrata, project, now=now),
                timeout=REFRESH_COMPUTE_TIMEOUT_SECONDS,
            )
            log_kind = "recovered_failed"
        elif kind == "orphan":
            cache = await asyncio.wait_for(
                compute_peer_stats_full(socrata, project, now=now),
                timeout=REFRESH_COMPUTE_TIMEOUT_SECONDS,
            )
            log_kind = "recovered_orphan"
        else:
            # kind == "unknown" — shouldn't happen given the
            # eligibility query filters on the three known statuses.
            # Defensive: skip via failed marker so it doesn't loop
            # in the next tick.
            logger.warning(
                "[refresh_cron] %s unexpected eligibility kind=%r "
                "for status=%r; marking failed",
                log_id, kind, cache_before.get("status"),
            )
            await _patch_failed(
                db, project_id, now=datetime.now(timezone.utc),
                error_kind=ERROR_KIND_UNEXPECTED,
                error_message=f"unknown eligibility kind for status={cache_before.get('status')!r}",
            )
            return "failed"
    except asyncio.TimeoutError:
        logger.error(
            "[refresh_cron] %s timeout (kind=%s) after %.1fs",
            log_id, kind, REFRESH_COMPUTE_TIMEOUT_SECONDS,
        )
        await _patch_failed(
            db, project_id, now=datetime.now(timezone.utc),
            error_kind=ERROR_KIND_TIMEOUT,
            error_message=(
                f"refresh compute exceeded "
                f"{REFRESH_COMPUTE_TIMEOUT_SECONDS:.0f}s"
            ),
        )
        return "failed"
    except SocrataQueryError as e:
        logger.error(
            "[refresh_cron] %s Socrata error (kind=%s): "
            "dataset=%s status=%s",
            log_id, kind, e.dataset_id, e.status_code,
        )
        await _patch_failed(
            db, project_id, now=datetime.now(timezone.utc),
            error_kind=ERROR_KIND_SOCRATA,
            error_message=(
                f"{e.dataset_id or '?'}:"
                f"{e.status_code if e.status_code else 'transport'}"
            ),
        )
        return "failed"
    except Exception as e:
        logger.exception(
            "[refresh_cron] %s unexpected exception (kind=%s)",
            log_id, kind,
        )
        await _patch_failed(
            db, project_id, now=datetime.now(timezone.utc),
            error_kind=ERROR_KIND_UNEXPECTED,
            error_message=repr(e)[:500],
        )
        return "failed"

    # Persist the fresh cache. Full-cache $set wipes any leftover
    # pending fields (started_at, error_kind="", etc.) from the
    # lock-before-compute step.
    persisted = await _persist_full_cache(db, project_id, cache)
    if not persisted:
        # Compute succeeded, persist didn't. Cache state on Mongo
        # is whatever the pending patch left — Commit 4's guard
        # will treat the project as pending until the next tick
        # retries. Don't stamp failed here (compute itself worked;
        # this is a Mongo-side transient).
        logger.warning(
            "[refresh_cron] %s compute succeeded but persist "
            "failed; will retry on next tick",
            log_id,
        )
        return "failed"

    sample = (cache.get("peer_criteria") or {}).get("sample_size", 0)
    logger.info(
        "[refresh_cron] %s %s (kind=%s, peer_sample=%d)",
        log_id, log_kind, kind, sample,
    )
    return log_kind


# ── Sweep entry point ─────────────────────────────────────────────


async def refresh_stale_peer_stats_caches(
    db,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Sweep projects, refresh eligible peer_stats_caches.

    Returns a stats dict the wrapper tick logs:

      ::

          {
            "checked": int,                 # projects fetched from sweep query
            "eligible": int,                # same as checked (alias for clarity)
            "refreshed_stale": int,         # status=ready → incremental
            "recovered_failed": int,        # status=failed (>24h) → full
            "recovered_orphan": int,        # status=pending (>15m) → full
            "failed": int,                  # compute failures (any kind)
            "tick_duration_seconds": float,
          }

    Sweep batches limit at ``REFRESH_BATCH_SIZE`` projects per
    tick, sorted by ``_id`` ascending (per Stage 1 Q2 decision —
    insertion order, deterministic across ticks).

    The optional ``now`` parameter is for test injection only —
    production callers (the APScheduler wrapper) pass nothing and
    the function uses real wall-clock time. Tests pass an
    explicit ``now`` so cache timestamps can be deterministic.
    Matches the same convention as ``compute_peer_stats_full``
    and ``refresh_peer_stats_incremental``.

    Designed to be called periodically by APScheduler. Per-project
    failures stay inside this function (failed marker stamped,
    sweep continues). The outer try/except in the server.py
    wrapper tick handles sweep-level failures (Mongo blip on the
    eligibility query, etc.).
    """
    started = now or datetime.now(timezone.utc)
    stats: Dict[str, Any] = {
        "checked": 0,
        "eligible": 0,
        "refreshed_stale": 0,
        "recovered_failed": 0,
        "recovered_orphan": 0,
        "failed": 0,
        "tick_duration_seconds": 0.0,
    }

    # ── Step 1: eligibility query ───────────────────────────────
    query = _build_eligibility_query(started)
    try:
        projects = await (
            db.projects
            .find(query)
            .sort("_id", 1)
            .limit(REFRESH_BATCH_SIZE)
            .to_list(REFRESH_BATCH_SIZE)
        )
    except Exception as e:
        logger.error("[refresh_cron] eligibility query failed: %r", e)
        stats["tick_duration_seconds"] = (
            datetime.now(timezone.utc) - started
        ).total_seconds()
        return stats

    stats["checked"] = len(projects)
    stats["eligible"] = len(projects)

    if not projects:
        stats["tick_duration_seconds"] = (
            datetime.now(timezone.utc) - started
        ).total_seconds()
        return stats

    # ── Step 2: process sequentially ────────────────────────────
    # Pacing IS the feature. One ServerHttpClient shared across
    # the batch (connection pool reuse), but per-project work is
    # serialized — no asyncio.gather, no semaphore. This bounds
    # Socrata burst rate to REFRESH_BATCH_SIZE projects spread
    # across (tick_duration_seconds), typically ~50-100s for a
    # full batch of 10.
    async with ServerHttpClient(timeout=10.0) as http:
        socrata = SocrataClient(http)
        for project in projects:
            # Per-project ``now`` uses real wall-clock for the
            # pending-lock / failed-marker timestamps so a long
            # batch shows accurate timing in admin diagnostics.
            # Tests that pinned ``now`` for the eligibility query
            # don't care about these per-project stamps (no test
            # asserts on the specific value).
            result = await _refresh_one_project(
                db, socrata, project,
                now=now or datetime.now(timezone.utc),
            )
            if result in stats:
                stats[result] += 1

    stats["tick_duration_seconds"] = (
        datetime.now(timezone.utc) - started
    ).total_seconds()
    return stats
