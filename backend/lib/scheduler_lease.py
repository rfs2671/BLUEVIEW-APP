"""One firing per schedule slot, however many processes run the scheduler.

── WHY ──────────────────────────────────────────────────────────────────────

APScheduler is in-process. Every container that boots registers and starts
every job (server.py startup_event), and `max_instances=1` only stops overlap
INSIDE one process. Two Railway replicas — or one replica overlapping its own
redeploy for a minute — fire every job twice: two digests, two DOB scans, two
copies of each email whose dedupe is check-then-act.

── HOW ──────────────────────────────────────────────────────────────────────

Each firing first claims its SLOT by inserting a document whose `_id` is
`<job_id>:<slot number>` into `scheduler_leases`. `_id` is unique by
definition, so exactly one insert wins; every other process gets a
DuplicateKeyError and skips that firing. No read-then-write window exists.

How a firing claims depends on the trigger:

    interval jobs  — SPACING, not a slot. Replicas start at different times,
                     so their ticks are offset by an arbitrary amount, and any
                     rounding of the tick time has a boundary two offset ticks
                     can straddle (12:07 and 12:08 round to different 15-minute
                     slots, and both run). Instead each job has ONE row,
                     `<job_id>:spacing`, holding `next_allowed_at`. A firing
                     runs only if it atomically moves that forward from a
                     value <= now (update_one on `_id` + `next_allowed_at`),
                     or inserts the row when none exists. The gap is 90% of
                     the interval: the replica that won keeps winning on its
                     own ticks, every other replica's tick lands inside the
                     gap and is skipped, and if the winner dies another
                     replica takes over on its next tick.
    cron jobs      — a slot: the firing's time rounded to half the gap
                     between two consecutive fire times, between
                     30 seconds and one hour. Every replica fires a cron job at
                     the same wall-clock moment; ROUNDING (not flooring) keeps a
                     replica whose clock is a few seconds early in the same
                     slot instead of the previous one.

A firing that cannot reach Mongo to claim its slot does not run. The jobs all
need Mongo anyway, and "ran twice because the lock was down" is the failure
this exists to remove.

Rows carry `expires_at` and a TTL index removes them (server.py,
ensure_scheduler_lease_indexes). A slot that crashed mid-run stays claimed;
the next slot runs normally.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

LEASE_COLLECTION = "scheduler_leases"
MIN_SLOT_SECONDS = 30
MAX_CRON_SLOT_SECONDS = 3600
SPACING_FRACTION = 0.9

HOLDER = f"{socket.gethostname()}:{os.getpid()}"


def slot_seconds(trigger: Any, now: Optional[datetime] = None) -> int:
    """The slot width for a trigger. Unknown triggers get the minimum."""
    interval = getattr(trigger, "interval", None)
    if isinstance(interval, timedelta):
        return max(MIN_SLOT_SECONDS, int(interval.total_seconds()))
    get_next = getattr(trigger, "get_next_fire_time", None)
    if callable(get_next):
        try:
            now = now or datetime.now(timezone.utc)
            first = get_next(None, now)
            second = get_next(first, first + timedelta(seconds=1)) if first else None
            if first and second:
                gap = (second - first).total_seconds()
                return int(max(MIN_SLOT_SECONDS,
                               min(gap / 2, MAX_CRON_SLOT_SECONDS)))
        except Exception:  # pragma: no cover - defensive
            pass
    return MIN_SLOT_SECONDS


def is_interval(trigger: Any) -> bool:
    return isinstance(getattr(trigger, "interval", None), timedelta)


def slot_key(job_id: str, seconds: int, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    ts = now.timestamp()
    slot = int((ts + seconds / 2) // seconds)
    return f"{job_id}:{slot}"


async def try_acquire(db: Any, job_id: str, seconds: int,
                      now: Optional[datetime] = None,
                      holder: str = HOLDER) -> bool:
    """Claim this firing's slot. True means: you, and only you, run it."""
    from pymongo.errors import DuplicateKeyError

    now = now or datetime.now(timezone.utc)
    key = slot_key(job_id, seconds, now)
    try:
        await db[LEASE_COLLECTION].insert_one({
            "_id": key,
            "job_id": job_id,
            "holder": holder,
            "acquired_at": now,
            "expires_at": now + timedelta(seconds=max(seconds * 4, 3600)),
        })
        return True
    except DuplicateKeyError:
        return False
    except Exception as e:
        logger.warning(f"[scheduler-lease] {job_id}: could not claim slot "
                       f"({type(e).__name__}); skipping this firing")
        return False


async def try_acquire_spaced(db: Any, job_id: str, interval_seconds: int,
                             now: Optional[datetime] = None,
                             holder: str = HOLDER) -> bool:
    """Claim an interval job's firing unless another process ran it within
    the last SPACING_FRACTION of the interval. True means: you run it."""
    from pymongo.errors import DuplicateKeyError

    now = now or datetime.now(timezone.utc)
    gap = max(MIN_SLOT_SECONDS, interval_seconds * SPACING_FRACTION)
    key = f"{job_id}:spacing"
    fields = {
        "job_id": job_id,
        "holder": holder,
        "acquired_at": now,
        "next_allowed_at": now + timedelta(seconds=gap),
        "expires_at": now + timedelta(seconds=max(interval_seconds * 4, 3600)),
    }
    coll = None
    try:
        coll = db[LEASE_COLLECTION]
        res = await coll.update_one(
            {"_id": key, "next_allowed_at": {"$lte": now}}, {"$set": fields})
        if res.modified_count:
            return True
        # No row yet (first run, or the TTL removed it after a long
        # silence), or the row is inside its gap — the insert tells which.
        await coll.insert_one({"_id": key, **fields})
        return True
    except DuplicateKeyError:
        return False
    except Exception as e:
        logger.warning(f"[scheduler-lease] {job_id}: could not claim firing "
                       f"({type(e).__name__}); skipping this firing")
        return False


def leased(job_id: str, seconds: int, fn: Callable[..., Awaitable[Any]],
           get_db: Callable[[], Any], *,
           spaced: bool = False) -> Callable[..., Awaitable[Any]]:
    """Wrap an async job so each firing runs at most once across processes.
    `spaced` selects the interval-job claim (see the module docstring)."""

    @functools.wraps(fn)
    async def _run(*args, **kwargs):
        acquire = try_acquire_spaced if spaced else try_acquire
        if not await acquire(get_db(), job_id, seconds):
            logger.info(f"[scheduler-lease] {job_id}: slot held elsewhere, skipped")
            return None
        return await fn(*args, **kwargs)

    _run.__leased_job_id__ = job_id
    _run.__lease_slot_seconds__ = seconds
    _run.__lease_spaced__ = spaced
    return _run


def make_leased_scheduler_class(base_cls: type,
                                get_db: Callable[[], Any]) -> type:
    """A scheduler class whose add_job wraps every async job in a lease.

    Wrapping at add_job means every existing `scheduler.add_job(...)` call is
    covered without editing any of them, and a job added later is covered
    without anyone remembering to."""

    class LeasedScheduler(base_cls):
        def add_job(self, func, trigger=None, *args, **kwargs):
            job_id = kwargs.get("id")
            if job_id and asyncio.iscoroutinefunction(func):
                func = leased(job_id, slot_seconds(trigger), func, get_db,
                              spaced=is_interval(trigger))
            return super().add_job(func, trigger, *args, **kwargs)

    LeasedScheduler.__name__ = f"Leased{base_cls.__name__}"
    return LeasedScheduler
