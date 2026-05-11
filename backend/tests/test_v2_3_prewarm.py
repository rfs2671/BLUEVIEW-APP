"""Phase V2.3 Commit 4 — Pre-warm task tests.

Coverage:

  • Happy path: prewarm_peer_stats persists a status="ready"
    cache and bumps to the success branch.
  • Pending marker is written BEFORE compute starts (operators
    must see it if they query during the compute window).
  • Categorized exceptions:
      - SocrataQueryError → status="failed", error_kind="socrata_error"
      - asyncio.TimeoutError → status="failed", error_kind="timeout"
      - bare Exception → status="failed", error_kind="unexpected"
      - All three: exception does NOT escape the task body.
  • Dedup: existing status ∈ {"pending", "ready"} → early return,
    no compute fires.
  • Dedup: existing status == "failed" → proceeds to compute
    (handled by compare_project_to_peers's 24h TTL upstream).
  • Edge: project_id not in db.projects → graceful log, no crash.
  • Edge: db.projects raising during pending-status write → still
    proceeds with compute (errors logged + swallowed by helper).
  • Concurrent-same-project spawn: two tasks fired back-to-back;
    only one runs the compute, the second sees "pending" and
    early-returns.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import unittest
from datetime import datetime, timezone
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

from lib.statistical_engine import prewarm as pw  # noqa: E402
from lib.statistical_engine.prewarm import (  # noqa: E402
    ERROR_KIND_SOCRATA,
    ERROR_KIND_TIMEOUT,
    ERROR_KIND_UNEXPECTED,
    PREWARM_TIMEOUT_SECONDS,
    prewarm_peer_stats,
)
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_PLUTO,
    SocrataQueryError,
)


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Stub projects collection
# ──────────────────────────────────────────────────────────────────


class _StubProjectsColl:
    """Minimal stub for db.projects with find_one + update_one.

    Tracks every update_one call so tests can assert on the order
    of state transitions (pending → ready / pending → failed).
    Lookup matches by _id only — the prewarm task only calls
    find_one({"_id": ...}).
    """

    def __init__(self, docs: List[Dict[str, Any]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.update_one_calls: List[Dict[str, Any]] = []
        # Hooks for failure-injection tests.
        self.update_one_raises: Optional[Exception] = None
        self.find_one_raises: Optional[Exception] = None

    async def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self.find_one_raises is not None:
            raise self.find_one_raises
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                # Return a deep-enough copy so callers mutating the
                # result don't leak back into the store. (Prewarm
                # currently doesn't mutate but defensive.)
                return dict(d)
        return None

    async def update_one(self, filter_: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):
        self.update_one_calls.append({
            "filter": dict(filter_),
            "update": {k: dict(v) if isinstance(v, dict) else v
                       for k, v in update.items()},
        })
        if self.update_one_raises is not None:
            raise self.update_one_raises
        # Apply the update to the matching doc.
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    # Support dotted keys (peer_stats_cache.status etc.)
                    for k, v in update["$set"].items():
                        if "." in k:
                            top, sub = k.split(".", 1)
                            container = d.setdefault(top, {})
                            if v is None:
                                container.pop(sub, None)
                            else:
                                container[sub] = v
                        else:
                            d[k] = v
                r = MagicMock(); r.upserted_id = None
                return r
        new_doc = dict(filter_)
        if upsert and "$set" in update:
            for k, v in update["$set"].items():
                if "." not in k:
                    new_doc[k] = v
            self.docs.append(new_doc)
        r = MagicMock(); r.upserted_id = "new" if upsert else None
        return r


class _StubDb:
    def __init__(self, projects=None):
        self.projects = _StubProjectsColl(projects)


# ──────────────────────────────────────────────────────────────────
# Compute stubs
# ──────────────────────────────────────────────────────────────────


def _make_ready_cache(sample_size: int = 24, tier: str = "borough_class_use"):
    """Build a plausible peer_stats_cache dict that
    compute_peer_stats_full might return."""
    now = datetime(2026, 5, 11, tzinfo=timezone.utc)
    return {
        "computed_at":       now,
        "last_refreshed_at": now,
        "peer_criteria": {
            "borough": "MANHATTAN",
            "project_class": "O",
            "use_type": "office",
            "bbl": "1000000001",
            "sample_size": sample_size,
            "fallback_level": 1,
            "tier": tier,
            "peer_bbl_list": [f"100000{i:04d}" for i in range(sample_size)],
            "_peer_counts_by_dataset": {},
        },
        "events_window_start": now,
        "events_window_end":   now,
        "violations":  {"n": sample_size, "mean": 0.0, "median": 0.0,
                        "p75": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0,
                        "project_count": 0, "percentile_rank": 0.0},
        "inspections": {"n": sample_size, "mean": 0.0, "median": 0.0,
                        "p75": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0,
                        "project_count": 0, "percentile_rank": 0.0},
        "complaints":  {"n": sample_size, "mean": 0.0, "median": 0.0,
                        "p75": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0,
                        "project_count": 0, "percentile_rank": 0.0},
        "status":              "ready",
        "error_message":       None,
    }


# ──────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────


class TestPrewarmHappyPath(unittest.TestCase):

    def test_persists_cache_with_status_ready(self):
        db = _StubDb(projects=[{
            "_id": "P1", "bbl": "1000000001", "borough": "MANHATTAN",
            "project_class": "O", "use_type": "office",
        }])

        async def _fake_compute(_socrata, _project, *, lookback_days=None, now=None):
            return _make_ready_cache(sample_size=24)

        with patch.object(pw, "compute_peer_stats_full", new=_fake_compute):
            _run(prewarm_peer_stats(db, "P1"))

        # Final doc should carry the ready cache.
        final = db.projects.docs[0]["peer_stats_cache"]
        self.assertEqual(final["status"], "ready")
        self.assertEqual(final["peer_criteria"]["sample_size"], 24)

    def test_sets_pending_before_compute_starts(self):
        """The pending marker MUST be written before
        compute_peer_stats_full is invoked, so a concurrent
        compare_project_to_peers call observes the pending state
        instead of racing the background task with its own sync
        compute. Pin via a compute stub that observes the doc
        state at compute-start time."""
        db = _StubDb(projects=[{"_id": "P2"}])
        observed_at_compute: List[Optional[str]] = []

        async def _observe_compute(_socrata, _project, *, lookback_days=None, now=None):
            # Re-fetch the project doc as it stands at this moment.
            current = await db.projects.find_one({"_id": "P2"})
            observed_at_compute.append(
                (current.get("peer_stats_cache") or {}).get("status"),
            )
            return _make_ready_cache()

        with patch.object(pw, "compute_peer_stats_full", new=_observe_compute):
            _run(prewarm_peer_stats(db, "P2"))

        self.assertEqual(observed_at_compute, ["pending"])

    def test_logs_duration_and_sample_size_on_success(self):
        db = _StubDb(projects=[{"_id": "P3"}])

        async def _fake(_s, _p, *, lookback_days=None, now=None):
            return _make_ready_cache(sample_size=37, tier="borough_class")

        with patch.object(pw, "compute_peer_stats_full", new=_fake), \
             self.assertLogs(pw.logger, level="INFO") as logs:
            _run(prewarm_peer_stats(db, "P3"))

        msg = "\n".join(logs.output)
        self.assertIn("ready", msg)
        self.assertIn("peer_sample=37", msg)
        self.assertIn("borough_class", msg)


# ──────────────────────────────────────────────────────────────────
# Error categorization — NO bare exception can escape
# ──────────────────────────────────────────────────────────────────


class TestPrewarmErrorCategorization(unittest.TestCase):

    def _failed_cache(self, db) -> Dict[str, Any]:
        return db.projects.docs[0].get("peer_stats_cache") or {}

    def test_socrata_error_categorized(self):
        db = _StubDb(projects=[{"_id": "PE1"}])

        async def _explode_socrata(*_a, **_kw):
            raise SocrataQueryError(
                "rate limited", dataset_id=DATASET_PLUTO,
                status_code=429,
            )

        with patch.object(pw, "compute_peer_stats_full", new=_explode_socrata):
            _run(prewarm_peer_stats(db, "PE1"))

        cache = self._failed_cache(db)
        self.assertEqual(cache["status"], "failed")
        self.assertEqual(cache["error_kind"], ERROR_KIND_SOCRATA)
        self.assertIn("429", cache["error_message"])
        self.assertIsInstance(cache.get("failed_at"), datetime)

    def test_timeout_error_categorized(self):
        db = _StubDb(projects=[{"_id": "PE2"}])

        async def _hang(*_a, **_kw):
            await asyncio.sleep(99)  # never completes within the cap

        # Patch the timeout to a tiny value so the test is fast.
        with patch.object(pw, "compute_peer_stats_full", new=_hang), \
             patch.object(pw, "PREWARM_TIMEOUT_SECONDS", 0.05):
            _run(prewarm_peer_stats(db, "PE2"))

        cache = self._failed_cache(db)
        self.assertEqual(cache["status"], "failed")
        self.assertEqual(cache["error_kind"], ERROR_KIND_TIMEOUT)
        self.assertIsInstance(cache.get("failed_at"), datetime)

    def test_unexpected_exception_categorized(self):
        """A non-SocrataQueryError, non-TimeoutError exception
        (e.g. a bug in compute_peer_stats_full, a Mongo blip
        inside it) lands in the catch-all branch with
        error_kind="unexpected"."""
        db = _StubDb(projects=[{"_id": "PE3"}])

        async def _bug(*_a, **_kw):
            raise RuntimeError("simulated code bug")

        with patch.object(pw, "compute_peer_stats_full", new=_bug):
            _run(prewarm_peer_stats(db, "PE3"))

        cache = self._failed_cache(db)
        self.assertEqual(cache["status"], "failed")
        self.assertEqual(cache["error_kind"], ERROR_KIND_UNEXPECTED)
        self.assertIn("simulated code bug", cache["error_message"])

    def test_exception_during_compute_does_not_escape(self):
        """All three compute-failure branches return cleanly. The
        prewarm coroutine is fire-and-forget; if any branch
        re-raised, asyncio would log 'Task exception was never
        retrieved' and operators would have a noisy unhandled
        exception. Pin that nothing escapes."""
        db = _StubDb(projects=[{"_id": "PE4"}])

        async def _bug(*_a, **_kw):
            raise RuntimeError("escape test")

        # Should NOT raise.
        with patch.object(pw, "compute_peer_stats_full", new=_bug):
            _run(prewarm_peer_stats(db, "PE4"))
        # If we got here, no exception escaped — pin the state
        # for good measure.
        self.assertEqual(
            db.projects.docs[0]["peer_stats_cache"]["status"], "failed",
        )

    def test_outer_catch_all_swallows_top_level_exception(self):
        """The outer try/except in prewarm_peer_stats is the
        last line of defense — guards against unexpected
        failures in the helpers themselves (db.projects raising,
        ServerHttpClient construction failing, etc.). Inject a
        failure into find_one to exercise the outer catch."""
        db = _StubDb(projects=[{"_id": "PE5"}])
        db.projects.find_one_raises = RuntimeError("mongo down")

        # Should NOT raise; the inner _resolve_project helper
        # catches its own exception, returns None, and the task
        # exits with a "project not found" log. But if a deeper
        # failure ever sneaks through, the outer catch-all
        # logger.exception is the safety net.
        _run(prewarm_peer_stats(db, "PE5"))
        # No exception escaped. Test passes by reaching this line.


# ──────────────────────────────────────────────────────────────────
# Deduplication
# ──────────────────────────────────────────────────────────────────


class TestPrewarmDedup(unittest.TestCase):

    def test_skips_when_existing_status_pending(self):
        """If a previous prewarm task is in flight (or a prior
        compare_project_to_peers wrote pending), a second spawn
        must early-return WITHOUT firing compute."""
        db = _StubDb(projects=[{
            "_id": "PD1",
            "peer_stats_cache": {"status": "pending"},
        }])
        compute_fired = []

        async def _watch_compute(*_a, **_kw):
            compute_fired.append(True)
            return _make_ready_cache()

        with patch.object(pw, "compute_peer_stats_full", new=_watch_compute):
            _run(prewarm_peer_stats(db, "PD1"))

        self.assertEqual(compute_fired, [], "compute should not fire")
        # Status preserved as pending (no state mutation).
        self.assertEqual(
            db.projects.docs[0]["peer_stats_cache"]["status"], "pending",
        )

    def test_skips_when_existing_status_ready(self):
        db = _StubDb(projects=[{
            "_id": "PD2",
            "peer_stats_cache": _make_ready_cache(sample_size=99),
        }])
        compute_fired = []

        async def _watch_compute(*_a, **_kw):
            compute_fired.append(True)
            return _make_ready_cache()

        with patch.object(pw, "compute_peer_stats_full", new=_watch_compute):
            _run(prewarm_peer_stats(db, "PD2"))

        self.assertEqual(compute_fired, [])
        # Sample size preserved — we did NOT overwrite the cache.
        self.assertEqual(
            db.projects.docs[0]["peer_stats_cache"]["peer_criteria"]["sample_size"],
            99,
        )

    def test_proceeds_when_existing_status_failed(self):
        """Failed-state cache does NOT dedup — that's the retry
        opportunity (the 24h TTL guard lives in
        compare_project_to_peers, not here). The prewarm should
        re-attempt the compute when called against a failed
        project."""
        db = _StubDb(projects=[{
            "_id": "PD3",
            "peer_stats_cache": {
                "status": "failed",
                "error_kind": "timeout",
                "failed_at": datetime(2026, 5, 10, tzinfo=timezone.utc),
            },
        }])

        async def _fake(*_a, **_kw):
            return _make_ready_cache(sample_size=22)

        with patch.object(pw, "compute_peer_stats_full", new=_fake):
            _run(prewarm_peer_stats(db, "PD3"))

        # Cache rewrote to ready.
        cache = db.projects.docs[0]["peer_stats_cache"]
        self.assertEqual(cache["status"], "ready")
        self.assertEqual(cache["peer_criteria"]["sample_size"], 22)
        # error_kind / failed_at fields cleared by the full
        # overwrite (the success path uses a wholesale $set, not
        # a partial patch).
        self.assertNotIn("error_kind", cache)
        self.assertNotIn("failed_at", cache)

    def test_concurrent_same_project_spawn_dedups(self):
        """Two tasks spawned back-to-back for the same project.
        First runs the compute (slow, gated on an Event), second
        observes status="pending" written by the first and
        early-returns. Net: exactly one compute fires."""
        db = _StubDb(projects=[{"_id": "PD4"}])

        gate = asyncio.Event()
        compute_count = []

        async def _gated_compute(*_a, **_kw):
            compute_count.append(True)
            await gate.wait()
            return _make_ready_cache(sample_size=15)

        async def _go():
            with patch.object(pw, "compute_peer_stats_full", new=_gated_compute):
                # Spawn the first task; let it run to the point
                # where it's awaiting the gate (one event loop
                # tick is enough — the pending marker is written
                # before compute_peer_stats_full is awaited).
                t1 = asyncio.create_task(prewarm_peer_stats(db, "PD4"))
                # Yield until the first task has written the
                # pending marker. Loop ensures we don't race on
                # asyncio scheduling.
                for _ in range(20):
                    await asyncio.sleep(0)
                    current = await db.projects.find_one({"_id": "PD4"})
                    if (current.get("peer_stats_cache") or {}).get("status") == "pending":
                        break
                else:
                    self.fail("first task never wrote pending marker")

                # Spawn the second task — it should observe
                # pending and early-return without firing
                # compute_peer_stats_full a second time.
                t2 = asyncio.create_task(prewarm_peer_stats(db, "PD4"))
                await t2  # second task is fast (just dedup + return)

                # Release the gate; first task completes.
                gate.set()
                await t1

        _run(_go())

        # Exactly one compute fired.
        self.assertEqual(len(compute_count), 1)
        # Final state is ready.
        self.assertEqual(
            db.projects.docs[0]["peer_stats_cache"]["status"], "ready",
        )


# ──────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────


class TestPrewarmEdgeCases(unittest.TestCase):

    def test_nonexistent_project_logs_and_returns(self):
        """An id that doesn't resolve in db.projects is logged
        at WARNING and the task exits cleanly. Should not crash
        and should not attempt to write any cache state."""
        db = _StubDb(projects=[])

        async def _fake(*_a, **_kw):
            return _make_ready_cache()

        with patch.object(pw, "compute_peer_stats_full", new=_fake), \
             self.assertLogs(pw.logger, level="WARNING") as logs:
            _run(prewarm_peer_stats(db, "GHOST"))

        self.assertIn("not found", "\n".join(logs.output))
        self.assertEqual(db.projects.update_one_calls, [])

    def test_db_failure_during_pending_write_does_not_crash(self):
        """If db.projects.update_one raises while writing the
        pending marker, the task continues to compute (cache
        state is best-effort; sync compute path is the safety
        net). The error helper logs and swallows the failure."""
        db = _StubDb(projects=[{"_id": "EDG"}])
        db.projects.update_one_raises = RuntimeError("transient mongo")

        async def _fake(*_a, **_kw):
            return _make_ready_cache()

        # Should not raise.
        with patch.object(pw, "compute_peer_stats_full", new=_fake):
            _run(prewarm_peer_stats(db, "EDG"))


# ──────────────────────────────────────────────────────────────────
# Package re-exports
# ──────────────────────────────────────────────────────────────────


class TestPrewarmReexports(unittest.TestCase):

    def test_prewarm_api_reexported(self):
        from lib import statistical_engine as stat_engine
        for name in (
            "prewarm_peer_stats",
            "PREWARM_TIMEOUT_SECONDS",
            "ERROR_KIND_TIMEOUT",
            "ERROR_KIND_SOCRATA",
            "ERROR_KIND_UNEXPECTED",
        ):
            self.assertTrue(
                hasattr(stat_engine, name),
                f"missing re-export: {name}",
            )


if __name__ == "__main__":
    unittest.main()
