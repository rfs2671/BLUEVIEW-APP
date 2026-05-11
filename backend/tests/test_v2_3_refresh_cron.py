"""Phase V2.3 Commit 5 — Stagger refresh cron tests.

Coverage of the 12 spec contract points:

  1. Empty DB → returns zero stats, no crash.
  2. Stale ready cache → incremental refresh.
  3. Failed cache <24h → skipped.
  4. Failed cache >24h → recovered via full compute.
  5. Orphan pending <15min → skipped.
  6. Orphan pending >15min → recovered via full compute.
  7. Batch size enforcement (REFRESH_BATCH_SIZE=10) with oldest
     _id first.
  8. Per-project SocrataQueryError → status=failed, sweep
     continues for the rest of the batch.
  9. Per-project timeout → status=failed (error_kind=timeout),
     sweep continues.
  10. Concurrent-tick safety: lock-before-compute writes
      status=pending BEFORE compute runs.
  11. Mixed eligibility batch (stale + failed + orphan) all
      handled correctly, stats reflect per-class counts.
  12. (Stage 2.5 in test_v2_2_schema_scaffolding.py) server.py
      registers the peer_stats_refresh APScheduler job.

Plus eligibility query construction, classification helper, and
re-export pins.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))

from lib.statistical_engine import refresh_cron as rc  # noqa: E402
from lib.statistical_engine.refresh_cron import (  # noqa: E402
    ORPHAN_PENDING_THRESHOLD_MINUTES,
    REFRESH_BATCH_SIZE,
    REFRESH_COMPUTE_TIMEOUT_SECONDS,
    REFRESH_TICK_MINUTES,
    _build_eligibility_query,
    _classify_eligibility,
    refresh_stale_peer_stats_caches,
)
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_PLUTO,
    SocrataQueryError,
)


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Stub projects collection with find().sort().limit().to_list()
# ──────────────────────────────────────────────────────────────────


class _StubCursor:
    """Minimal motor-cursor stub supporting the chain
    find().sort().limit().to_list()."""

    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)
        self._sort_key: Optional[str] = None
        self._sort_dir: int = 1
        self._limit: Optional[int] = None

    def sort(self, key: str, direction: int = 1) -> "_StubCursor":
        self._sort_key = key
        self._sort_dir = direction
        return self

    def limit(self, n: int) -> "_StubCursor":
        self._limit = n
        return self

    async def to_list(self, length: Optional[int] = None):
        docs = list(self._docs)
        if self._sort_key:
            docs.sort(key=lambda d: d.get(self._sort_key),
                      reverse=(self._sort_dir == -1))
        if self._limit is not None:
            docs = docs[:self._limit]
        if length is not None and len(docs) > length:
            docs = docs[:length]
        return docs


class _StubProjectsColl:
    """Project collection stub that evaluates the refresh-cron
    eligibility query in Python. Supports dotted $set updates so
    the lock-before-compute and failed-marker patches land on the
    nested peer_stats_cache fields correctly.
    """

    def __init__(self, docs: List[Dict[str, Any]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.update_one_calls: List[Dict[str, Any]] = []
        self.find_raises: Optional[Exception] = None

    # ── Query helpers ──────────────────────────────────────────

    def _doc_matches_clause(self, doc: Dict[str, Any], clause: Dict[str, Any]) -> bool:
        """Evaluate a single clause (no $or) against one doc.
        Supports dotted keys + {$lt: ...} operator."""
        for key, expected in clause.items():
            actual = self._dotted_get(doc, key)
            if isinstance(expected, dict):
                if "$lt" in expected:
                    cmp = expected["$lt"]
                    if not isinstance(actual, datetime):
                        return False
                    a = actual if actual.tzinfo else actual.replace(tzinfo=timezone.utc)
                    c = cmp if cmp.tzinfo else cmp.replace(tzinfo=timezone.utc)
                    if not (a < c):
                        return False
                else:
                    # Unsupported operator in tests.
                    return False
            else:
                if actual != expected:
                    return False
        return True

    @staticmethod
    def _dotted_get(doc: Dict[str, Any], dotted: str) -> Any:
        cur: Any = doc
        for part in dotted.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    def _doc_matches(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        if "$or" in query:
            return any(self._doc_matches_clause(doc, c) for c in query["$or"])
        return self._doc_matches_clause(doc, query)

    # ── motor surface ──────────────────────────────────────────

    def find(self, query: Dict[str, Any] = None) -> _StubCursor:
        if self.find_raises is not None:
            raise self.find_raises
        if query is None:
            return _StubCursor(self.docs)
        return _StubCursor([d for d in self.docs if self._doc_matches(d, query)])

    async def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    async def update_one(self, filter_: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):
        self.update_one_calls.append({
            "filter": dict(filter_),
            "update": {k: dict(v) if isinstance(v, dict) else v
                       for k, v in update.items()},
        })
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        if "." in k:
                            top, sub = k.split(".", 1)
                            container = d.setdefault(top, {})
                            # Handle nested-further dotted keys if any.
                            if "." in sub:
                                # Not exercised by the cron, but keep
                                # the stub general.
                                parts = sub.split(".")
                                inner = container
                                for p in parts[:-1]:
                                    inner = inner.setdefault(p, {})
                                inner[parts[-1]] = v
                            elif v is None and not isinstance(container, dict):
                                # Defensive: shouldn't happen
                                pass
                            else:
                                container[sub] = v
                        else:
                            d[k] = v
                r = MagicMock(); r.upserted_id = None
                return r
        r = MagicMock(); r.upserted_id = None
        return r


class _StubDb:
    def __init__(self, projects: List[Dict[str, Any]] = None):
        self.projects = _StubProjectsColl(projects)


# ──────────────────────────────────────────────────────────────────
# Cache builders
# ──────────────────────────────────────────────────────────────────


def _ready_cache(*, last_refreshed_at: datetime, sample_size: int = 24) -> Dict[str, Any]:
    return {
        "status": "ready",
        "computed_at": last_refreshed_at,
        "last_refreshed_at": last_refreshed_at,
        "peer_criteria": {
            "borough": "MANHATTAN",
            "project_class": "O",
            "use_type": "office",
            "tier": "borough_class_use",
            "sample_size": sample_size,
            "fallback_level": 1,
            "peer_bbl_list": [f"100000{i:04d}" for i in range(sample_size)],
            "_peer_counts_by_dataset": {},
        },
        "violations":  {"n": sample_size, "median": 0.0, "p75": 0.0, "p90": 0.0,
                        "project_count": 0, "percentile_rank": 0.0},
        "inspections": {"n": sample_size, "median": 0.0, "p75": 0.0, "p90": 0.0,
                        "project_count": 0, "percentile_rank": 0.0},
        "complaints":  {"n": sample_size, "median": 0.0, "p75": 0.0, "p90": 0.0,
                        "project_count": 0, "percentile_rank": 0.0},
    }


def _failed_cache(*, failed_at: datetime, error_kind: str = "socrata_error") -> Dict[str, Any]:
    return {
        "status": "failed",
        "started_at": failed_at - timedelta(seconds=30),
        "failed_at": failed_at,
        "error_kind": error_kind,
        "error_message": "test failure",
    }


def _pending_cache(*, started_at: datetime) -> Dict[str, Any]:
    return {
        "status": "pending",
        "started_at": started_at,
        "error_kind": "",
        "error_message": "",
        "failed_at": None,
    }


def _project(
    _id: str, *,
    cache: Optional[Dict[str, Any]] = None,
    bbl: str = "1000000001",
) -> Dict[str, Any]:
    p: Dict[str, Any] = {
        "_id": _id,
        "bbl": bbl,
        "borough": "MANHATTAN",
        "project_class": "O",
        "use_type": "office",
    }
    if cache is not None:
        p["peer_stats_cache"] = cache
    return p


# ──────────────────────────────────────────────────────────────────
# Compute stubs
# ──────────────────────────────────────────────────────────────────


def _fake_ready_cache_result(sample_size: int = 24) -> Dict[str, Any]:
    """What compute_peer_stats_full / refresh_peer_stats_incremental
    return on success — a full ready cache dict."""
    now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
    return _ready_cache(last_refreshed_at=now, sample_size=sample_size)


async def _fake_full(*_a, **_kw):
    return _fake_ready_cache_result()


async def _fake_incremental(*_a, **_kw):
    return _fake_ready_cache_result(sample_size=22)


# ──────────────────────────────────────────────────────────────────
# Eligibility query construction
# ──────────────────────────────────────────────────────────────────


class TestBuildEligibilityQuery(unittest.TestCase):
    """Pin the 3-clause $or shape against Commit 4's cache field
    names. A regression that uses the wrong field (e.g.
    last_refreshed_at on failed caches) would silently fail to
    select eligible projects."""

    def test_query_has_three_or_clauses(self):
        now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        q = _build_eligibility_query(now)
        self.assertIn("$or", q)
        self.assertEqual(len(q["$or"]), 3)

    def test_stale_ready_clause_uses_last_refreshed_at(self):
        now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        q = _build_eligibility_query(now)
        stale = next(c for c in q["$or"]
                     if c.get("peer_stats_cache.status") == "ready")
        self.assertIn("peer_stats_cache.last_refreshed_at", stale)
        cutoff = stale["peer_stats_cache.last_refreshed_at"]["$lt"]
        self.assertEqual(cutoff, now - timedelta(days=14))

    def test_failed_clause_uses_failed_at_not_last_refreshed_at(self):
        """Heightened-review pin: failed caches have failed_at,
        not last_refreshed_at. Wrong field → zero failed retries
        in production."""
        now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        q = _build_eligibility_query(now)
        failed = next(c for c in q["$or"]
                      if c.get("peer_stats_cache.status") == "failed")
        self.assertIn("peer_stats_cache.failed_at", failed)
        self.assertNotIn("peer_stats_cache.last_refreshed_at", failed)
        cutoff = failed["peer_stats_cache.failed_at"]["$lt"]
        self.assertEqual(cutoff, now - timedelta(hours=24))

    def test_orphan_clause_uses_started_at_not_computed_at(self):
        """Heightened-review pin: pending caches have started_at,
        not computed_at. Wrong field → orphans never recovered."""
        now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        q = _build_eligibility_query(now)
        orphan = next(c for c in q["$or"]
                      if c.get("peer_stats_cache.status") == "pending")
        self.assertIn("peer_stats_cache.started_at", orphan)
        self.assertNotIn("peer_stats_cache.computed_at", orphan)
        cutoff = orphan["peer_stats_cache.started_at"]["$lt"]
        self.assertEqual(
            cutoff, now - timedelta(minutes=ORPHAN_PENDING_THRESHOLD_MINUTES),
        )

    def test_no_extra_exclusion_clauses(self):
        """Spec Stage 1 Q1: dropped the $ne pending exclusion.
        Sweep semantics rely on the three $or clauses alone."""
        now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        q = _build_eligibility_query(now)
        # Top-level keys should be only $or.
        self.assertEqual(set(q.keys()), {"$or"})


class TestClassifyEligibility(unittest.TestCase):

    def test_ready_status_is_stale(self):
        self.assertEqual(_classify_eligibility({"status": "ready"}), "stale")

    def test_failed_status_is_failed(self):
        self.assertEqual(_classify_eligibility({"status": "failed"}), "failed")

    def test_pending_status_is_orphan(self):
        self.assertEqual(_classify_eligibility({"status": "pending"}), "orphan")

    def test_unknown_status_is_unknown(self):
        self.assertEqual(_classify_eligibility({"status": "garbage"}), "unknown")
        self.assertEqual(_classify_eligibility({}), "unknown")
        self.assertEqual(_classify_eligibility(None), "unknown")


# ──────────────────────────────────────────────────────────────────
# Empty DB
# ──────────────────────────────────────────────────────────────────


class TestRefreshCronEmptyDb(unittest.TestCase):

    def test_empty_database_returns_zero_stats_no_crash(self):
        db = _StubDb(projects=[])
        stats = _run(refresh_stale_peer_stats_caches(db))
        self.assertEqual(stats["checked"], 0)
        self.assertEqual(stats["eligible"], 0)
        self.assertEqual(stats["refreshed_stale"], 0)
        self.assertEqual(stats["recovered_failed"], 0)
        self.assertEqual(stats["recovered_orphan"], 0)
        self.assertEqual(stats["failed"], 0)
        self.assertGreaterEqual(stats["tick_duration_seconds"], 0)


# ──────────────────────────────────────────────────────────────────
# Per-class eligibility
# ──────────────────────────────────────────────────────────────────


class TestRefreshCronEligibility(unittest.TestCase):

    def setUp(self):
        # Pin a time so the test cutoffs are deterministic.
        self.now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)

    def test_stale_ready_cache_refreshed_incrementally(self):
        # Last refreshed 15 days ago → past the 14-day threshold.
        proj = _project("P1", cache=_ready_cache(
            last_refreshed_at=self.now - timedelta(days=15),
        ))
        db = _StubDb(projects=[proj])

        incremental_called = []
        async def _track_incremental(_socrata, _project, *, now=None):
            incremental_called.append(_project["_id"])
            return _fake_ready_cache_result()

        with patch.object(rc, "refresh_peer_stats_incremental", new=_track_incremental), \
             patch.object(rc, "compute_peer_stats_full", new=_fake_full):
            stats = _run(refresh_stale_peer_stats_caches(db, now=self.now))

        self.assertEqual(stats["refreshed_stale"], 1)
        self.assertEqual(stats["recovered_failed"], 0)
        self.assertEqual(stats["recovered_orphan"], 0)
        self.assertEqual(incremental_called, ["P1"])
        # Final cache is ready.
        self.assertEqual(db.projects.docs[0]["peer_stats_cache"]["status"], "ready")

    def test_recent_ready_cache_skipped(self):
        # Last refreshed 5 days ago → within 14-day window.
        proj = _project("P2", cache=_ready_cache(
            last_refreshed_at=self.now - timedelta(days=5),
        ))
        db = _StubDb(projects=[proj])
        stats = _run(refresh_stale_peer_stats_caches(db))
        self.assertEqual(stats["checked"], 0)

    def test_failed_cache_under_24h_skipped(self):
        # Failed 2 hours ago → within 24h escape window.
        proj = _project("P3", cache=_failed_cache(
            failed_at=self.now - timedelta(hours=2),
        ))
        db = _StubDb(projects=[proj])
        stats = _run(refresh_stale_peer_stats_caches(db))
        self.assertEqual(stats["checked"], 0)

    def test_failed_cache_over_24h_recovered_via_full_compute(self):
        # Failed 25 hours ago → past 24h threshold.
        proj = _project("P4", cache=_failed_cache(
            failed_at=self.now - timedelta(hours=25),
        ))
        db = _StubDb(projects=[proj])

        full_called = []
        async def _track_full(_s, _p, *, now=None):
            full_called.append(_p["_id"])
            return _fake_ready_cache_result()

        with patch.object(rc, "compute_peer_stats_full", new=_track_full), \
             patch.object(rc, "refresh_peer_stats_incremental", new=_fake_incremental):
            stats = _run(refresh_stale_peer_stats_caches(db, now=self.now))

        self.assertEqual(stats["recovered_failed"], 1)
        self.assertEqual(stats["refreshed_stale"], 0)
        self.assertEqual(full_called, ["P4"])
        # Final cache is ready, error fields wiped (full $set
        # overwrite).
        final = db.projects.docs[0]["peer_stats_cache"]
        self.assertEqual(final["status"], "ready")
        self.assertNotIn("error_kind", final)
        self.assertNotIn("failed_at", final)

    def test_pending_under_15min_skipped(self):
        proj = _project("P5", cache=_pending_cache(
            started_at=self.now - timedelta(minutes=5),
        ))
        db = _StubDb(projects=[proj])
        stats = _run(refresh_stale_peer_stats_caches(db))
        self.assertEqual(stats["checked"], 0)

    def test_pending_over_15min_recovered_via_full_compute(self):
        proj = _project("P6", cache=_pending_cache(
            started_at=self.now - timedelta(minutes=20),
        ))
        db = _StubDb(projects=[proj])

        full_called = []
        async def _track_full(_s, _p, *, now=None):
            full_called.append(_p["_id"])
            return _fake_ready_cache_result()

        with patch.object(rc, "compute_peer_stats_full", new=_track_full), \
             patch.object(rc, "refresh_peer_stats_incremental", new=_fake_incremental):
            stats = _run(refresh_stale_peer_stats_caches(db, now=self.now))

        self.assertEqual(stats["recovered_orphan"], 1)
        self.assertEqual(stats["refreshed_stale"], 0)
        self.assertEqual(full_called, ["P6"])

    def test_mixed_eligibility_classes_all_handled(self):
        """Five stale + three failed-old + two orphan-pending all
        in the same sweep. Verify per-class counts in stats."""
        stale = [_project(f"S{i}", cache=_ready_cache(
            last_refreshed_at=self.now - timedelta(days=15, hours=i),
        )) for i in range(5)]
        failed = [_project(f"F{i}", cache=_failed_cache(
            failed_at=self.now - timedelta(hours=25 + i),
        )) for i in range(3)]
        orphan = [_project(f"O{i}", cache=_pending_cache(
            started_at=self.now - timedelta(minutes=20 + i),
        )) for i in range(2)]
        db = _StubDb(projects=stale + failed + orphan)

        with patch.object(rc, "compute_peer_stats_full", new=_fake_full), \
             patch.object(rc, "refresh_peer_stats_incremental", new=_fake_incremental):
            stats = _run(refresh_stale_peer_stats_caches(db, now=self.now))

        self.assertEqual(stats["checked"], 10)
        self.assertEqual(stats["refreshed_stale"], 5)
        self.assertEqual(stats["recovered_failed"], 3)
        self.assertEqual(stats["recovered_orphan"], 2)
        self.assertEqual(stats["failed"], 0)


# ──────────────────────────────────────────────────────────────────
# Batch size + ordering
# ──────────────────────────────────────────────────────────────────


class TestRefreshCronBatching(unittest.TestCase):

    def test_batch_size_enforced_oldest_id_first(self):
        """25 eligible projects + REFRESH_BATCH_SIZE=10 → only
        10 fetched, sorted by _id ascending."""
        self.now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        now = self.now
        # IDs P000..P024 alphabetical sort puts P000 first.
        projects = [
            _project(f"P{i:03d}", cache=_ready_cache(
                last_refreshed_at=now - timedelta(days=15),
            ))
            for i in range(25)
        ]
        db = _StubDb(projects=projects)

        processed = []
        async def _track_incremental(_s, _p, *, now=None):
            processed.append(_p["_id"])
            return _fake_ready_cache_result()

        with patch.object(rc, "refresh_peer_stats_incremental", new=_track_incremental), \
             patch.object(rc, "compute_peer_stats_full", new=_fake_full):
            stats = _run(refresh_stale_peer_stats_caches(db, now=self.now))

        self.assertEqual(stats["checked"], REFRESH_BATCH_SIZE)
        self.assertEqual(len(processed), REFRESH_BATCH_SIZE)
        # First 10 IDs by ascending _id.
        self.assertEqual(processed, [f"P{i:03d}" for i in range(REFRESH_BATCH_SIZE)])


# ──────────────────────────────────────────────────────────────────
# Per-project error paths — sweep continues
# ──────────────────────────────────────────────────────────────────


class TestRefreshCronErrorPaths(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)

    def test_socrata_query_error_marks_failed_continues_sweep(self):
        """Three stale projects; the middle one's incremental
        refresh raises. Sweep must mark it failed and continue
        with the third. Returns mixed stats."""
        projects = [
            _project(f"P{i}", cache=_ready_cache(
                last_refreshed_at=self.now - timedelta(days=15, hours=i),
            ))
            for i in range(3)
        ]
        db = _StubDb(projects=projects)

        call_count = [0]
        async def _flaky_incremental(_s, p, *, now=None):
            call_count[0] += 1
            if p["_id"] == "P1":
                raise SocrataQueryError(
                    "boom", dataset_id=DATASET_PLUTO, status_code=429,
                )
            return _fake_ready_cache_result()

        with patch.object(rc, "refresh_peer_stats_incremental", new=_flaky_incremental), \
             patch.object(rc, "compute_peer_stats_full", new=_fake_full):
            stats = _run(refresh_stale_peer_stats_caches(db, now=self.now))

        self.assertEqual(stats["checked"], 3)
        self.assertEqual(stats["refreshed_stale"], 2)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(call_count[0], 3, "sweep must continue past failure")
        # P1 ends with status=failed + correct error_kind.
        p1_final = next(d for d in db.projects.docs if d["_id"] == "P1")
        self.assertEqual(p1_final["peer_stats_cache"]["status"], "failed")
        self.assertEqual(p1_final["peer_stats_cache"]["error_kind"], "socrata_error")
        # P0 and P2 succeeded.
        self.assertEqual(
            db.projects.docs[0]["peer_stats_cache"]["status"], "ready",
        )
        self.assertEqual(
            db.projects.docs[2]["peer_stats_cache"]["status"], "ready",
        )

    def test_compute_timeout_marks_failed_continues_sweep(self):
        projects = [
            _project(f"T{i}", cache=_ready_cache(
                last_refreshed_at=self.now - timedelta(days=15, hours=i),
            ))
            for i in range(2)
        ]
        db = _StubDb(projects=projects)

        async def _slow_when_t0(_s, p, *, now=None):
            if p["_id"] == "T0":
                await asyncio.sleep(99)  # > test timeout
            return _fake_ready_cache_result()

        with patch.object(rc, "refresh_peer_stats_incremental", new=_slow_when_t0), \
             patch.object(rc, "compute_peer_stats_full", new=_fake_full), \
             patch.object(rc, "REFRESH_COMPUTE_TIMEOUT_SECONDS", 0.05):
            stats = _run(refresh_stale_peer_stats_caches(db, now=self.now))

        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["refreshed_stale"], 1)
        t0_final = next(d for d in db.projects.docs if d["_id"] == "T0")
        self.assertEqual(t0_final["peer_stats_cache"]["status"], "failed")
        self.assertEqual(t0_final["peer_stats_cache"]["error_kind"], "timeout")

    def test_eligibility_query_failure_returns_zero_stats_no_crash(self):
        """If db.projects.find raises (e.g. Mongo blip), the sweep
        logs and returns zero stats. Does NOT raise — APScheduler
        wrapper relies on this."""
        db = _StubDb(projects=[])
        db.projects.find_raises = RuntimeError("mongo down")
        stats = _run(refresh_stale_peer_stats_caches(db))
        self.assertEqual(stats["checked"], 0)
        self.assertEqual(stats["failed"], 0)


# ──────────────────────────────────────────────────────────────────
# Lock-before-compute (Stage 2 refinement B)
# ──────────────────────────────────────────────────────────────────


class TestRefreshCronLockBeforeCompute(unittest.TestCase):

    def test_pending_marker_written_before_compute_runs(self):
        """Stage 2 refinement B: each project gets status=pending
        BEFORE compute fires. Pin via a compute stub that
        observes the doc state at compute-start."""
        now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        proj = _project("LK", cache=_ready_cache(
            last_refreshed_at=now - timedelta(days=15),
        ))
        db = _StubDb(projects=[proj])
        observed_status: List[Optional[str]] = []

        async def _observe(_s, p, *, now=None):
            current = await db.projects.find_one({"_id": "LK"})
            observed_status.append(
                (current.get("peer_stats_cache") or {}).get("status"),
            )
            return _fake_ready_cache_result()

        with patch.object(rc, "refresh_peer_stats_incremental", new=_observe), \
             patch.object(rc, "compute_peer_stats_full", new=_fake_full):
            _run(refresh_stale_peer_stats_caches(db, now=now))

        # At the moment refresh_peer_stats_incremental was called,
        # the project doc's peer_stats_cache.status should have
        # already been flipped to "pending" by the cron's
        # _patch_pending step.
        self.assertEqual(observed_status, ["pending"])


# ──────────────────────────────────────────────────────────────────
# Re-exports
# ──────────────────────────────────────────────────────────────────


class TestRefreshCronReexports(unittest.TestCase):

    def test_api_reexported(self):
        from lib import statistical_engine as stat_engine
        for name in (
            "refresh_stale_peer_stats_caches",
            "REFRESH_BATCH_SIZE",
            "REFRESH_TICK_MINUTES",
            "REFRESH_COMPUTE_TIMEOUT_SECONDS",
            "ORPHAN_PENDING_THRESHOLD_MINUTES",
        ):
            self.assertTrue(
                hasattr(stat_engine, name),
                f"missing re-export: {name}",
            )


if __name__ == "__main__":
    unittest.main()
