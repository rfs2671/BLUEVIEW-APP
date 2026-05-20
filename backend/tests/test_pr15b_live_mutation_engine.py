"""PR #15B — live mutation engine tests.

10 tests in TestLiveMutationEngine:
  1.  test_compute_x_now_returns_5_features
  2.  test_compute_x_now_active_swo_flag_from_dob_logs
  3.  test_compute_x_now_complaint_velocity_14d_window
  4.  test_compute_x_now_days_since_last_violation_clamped
  5.  test_live_mutation_clips_x_now_to_3sigma (L2, T8)
  6.  test_live_mutation_returns_within_100ms (T3)
  7.  test_live_mutation_refreshes_when_stale_gt_5min (L7)
  8.  test_live_mutation_non_blocking_returns_cached_immediately (L11)
  9.  test_live_mutation_writes_validation_ledger_upsert (T7)
  10. test_live_mutation_does_not_run_when_prediction_cache_absent
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))


def _run(coro):
    return asyncio.run(coro)


try:
    from lib.statistical_engine.live_mutation import (  # type: ignore
        compute_x_now_for_project,
        predict_for_project_live,
        winsorize_x_now,
    )
    HAS_LIVE_HELPERS = True
except ImportError:
    compute_x_now_for_project = None  # type: ignore
    predict_for_project_live = None   # type: ignore
    winsorize_x_now = None            # type: ignore
    HAS_LIVE_HELPERS = False


from _pr14b_fixtures import seed_prediction_models_fixture  # noqa: E402
from _pr15a_panel_fixtures import (  # noqa: E402
    _StubDb, _StubProjectsForCache,
)


class _StubDobLogs:
    """Minimal dob_logs stub for live-mutation x_now tests.
    Supports the $facet aggregate pattern from triggers.py:606."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def aggregate(self, pipeline, **_kw):
        """Evaluate $match + $facet pipeline used by compute_x_now."""
        # First stage = $match filter
        rows = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                m = stage["$match"]
                rows = [r for r in rows
                        if all(_match_field(r, k, v) for k, v in m.items())]
            elif "$facet" in stage:
                out = {}
                for fname, fpipeline in stage["$facet"].items():
                    fr = list(rows)
                    for fs in fpipeline:
                        if "$match" in fs:
                            fr = [r for r in fr
                                  if all(_match_field(r, k, v)
                                         for k, v in fs["$match"].items())]
                        if "$count" in fs:
                            fr = [{fs["$count"]: len(fr)}] if fr else []
                        if "$group" in fs:
                            g = fs["$group"]
                            grp = {"_id": g.get("_id")}
                            for k, expr in g.items():
                                if k == "_id":
                                    continue
                                if "$max" in expr:
                                    field = expr["$max"].lstrip("$")
                                    vals = [r.get(field) for r in fr
                                            if r.get(field) is not None]
                                    grp[k] = max(vals) if vals else None
                                elif "$sum" in expr:
                                    grp[k] = len(fr) if expr["$sum"] == 1 else 0
                            fr = [grp] if fr else []
                    out[fname] = fr
                rows = [out]
        return _AsyncIter(rows)


def _match_field(doc, key, criterion):
    val = doc.get(key)
    if isinstance(criterion, dict):
        for op, target in criterion.items():
            if op == "$gte" and not (val is not None and val >= target):
                return False
            if op == "$lt" and not (val is not None and val < target):
                return False
            if op == "$ne" and val == target:
                return False
            if op == "$in" and val not in target:
                return False
            if op == "$nin" and val in target:
                return False
        return True
    return val == criterion


class _AsyncIter:
    def __init__(self, rows):
        self.rows = rows
    def __aiter__(self):
        self._i = 0
        return self
    async def __anext__(self):
        if self._i >= len(self.rows):
            raise StopAsyncIteration
        r = self.rows[self._i]
        self._i += 1
        return r
    async def to_list(self, length=None):
        return list(self.rows[:length]) if length is not None else list(self.rows)


class TestLiveMutationEngine(unittest.TestCase):
    """PR #15B — live mutation engine reads dob_logs aggregates +
    prediction_models β to produce intra-day x_now → sigmoid(β·x_now)
    in <100ms p99 (L11 non-blocking)."""

    def _require_helpers(self):
        if not HAS_LIVE_HELPERS:
            self.fail(
                "Stage 3 PR #15B: implement "
                "lib/statistical_engine/live_mutation.py with at least:\n"
                "  • async compute_x_now_for_project(db, project, *, now)\n"
                "      -> Dict[str, float]  (5 features)\n"
                "  • async predict_for_project_live(db, project, *, now)\n"
                "      -> Dict[str, float]  (3 horizon probs)\n"
                "  • winsorize_x_now(x_now, mu, sigma, *, k=3.0)\n"
                "      -> Tuple[Dict[str, float], List[str]]  (clipped, fields_clipped)"
            )

    # ── Test 1 — 5 features ───────────────────────────────────

    def test_compute_x_now_returns_5_features(self):
        self._require_helpers()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {"_id": "P-1", "bbl": "3001000000",
                   "borough": "BROOKLYN"}
        db = _StubDb(projects=_StubProjectsForCache([project]),
                     dob_logs=_StubDobLogs([]))
        x = _run(compute_x_now_for_project(db, project, now=now))
        self.assertEqual(
            set(x.keys()),
            {
                "active_swo_flag",
                "complaint_velocity_14d",
                "days_since_last_violation",
                "schedule_position_ratio",
                "district_caseload_proxy_days",
            },
            msg=(
                f"compute_x_now_for_project must return exactly 5 "
                f"feature keys. Got {set(x.keys())}."
            ),
        )

    # ── Test 2 — active_swo_flag from dob_logs ───────────

    def test_compute_x_now_active_swo_flag_from_dob_logs(self):
        self._require_helpers()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {"_id": "P-SWO", "bbl": "3001000001", "borough": "BROOKLYN"}
        # active SWO present:
        db = _StubDb(
            projects=_StubProjectsForCache([project]),
            dob_logs=_StubDobLogs([{
                "project_id": "P-SWO",
                "record_type": "swo",
                "resolution_state": "ACTIVE",
                "is_deleted": False,
            }]),
        )
        x = _run(compute_x_now_for_project(db, project, now=now))
        self.assertEqual(
            x["active_swo_flag"], 1,
            msg="active_swo_flag must be 1 when an active SWO exists.",
        )
        # closed-only:
        db_closed = _StubDb(
            projects=_StubProjectsForCache([project]),
            dob_logs=_StubDobLogs([{
                "project_id": "P-SWO",
                "record_type": "swo",
                "resolution_state": "CLOSED",
                "is_deleted": False,
            }]),
        )
        x2 = _run(compute_x_now_for_project(db_closed, project, now=now))
        self.assertEqual(
            x2["active_swo_flag"], 0,
            msg="active_swo_flag must be 0 when only closed SWOs.",
        )

    # ── Test 3 — complaint_velocity_14d ────────────────

    def test_compute_x_now_complaint_velocity_14d_window(self):
        self._require_helpers()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {"_id": "P-VEL", "bbl": "3001000002", "borough": "BROOKLYN"}
        # 5 inside, 3 outside
        rows = []
        for i in range(5):
            rows.append({
                "project_id": "P-VEL", "record_type": "complaint",
                "violation_date": (now - timedelta(days=i+1)).strftime("%Y%m%d"),
                "is_deleted": False,
            })
        for i in range(3):
            rows.append({
                "project_id": "P-VEL", "record_type": "complaint",
                "violation_date": (now - timedelta(days=30+i)).strftime("%Y%m%d"),
                "is_deleted": False,
            })
        db = _StubDb(
            projects=_StubProjectsForCache([project]),
            dob_logs=_StubDobLogs(rows),
        )
        x = _run(compute_x_now_for_project(db, project, now=now))
        self.assertEqual(
            x["complaint_velocity_14d"], 5,
            msg=(
                f"complaint_velocity_14d must count only complaints "
                f"in last 14 days. Expected 5, got "
                f"{x['complaint_velocity_14d']}."
            ),
        )

    # ── Test 4 — days_since_last_violation clamped ───

    def test_compute_x_now_days_since_last_violation_clamped(self):
        self._require_helpers()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {"_id": "P-DSV", "bbl": "3001000003", "borough": "BROOKLYN"}
        old_vio = (now - timedelta(days=200)).strftime("%Y%m%d")
        db = _StubDb(
            projects=_StubProjectsForCache([project]),
            dob_logs=_StubDobLogs([{
                "project_id": "P-DSV", "record_type": "violation",
                "violation_date": old_vio, "is_deleted": False,
            }]),
        )
        x = _run(compute_x_now_for_project(db, project, now=now))
        self.assertEqual(
            x["days_since_last_violation"], 90,
            msg=(
                f"200-day-old violation must clamp to 90. Got "
                f"{x['days_since_last_violation']}."
            ),
        )

    # ── Test 5 — L2 winsorization ───────────────────

    def test_live_mutation_clips_x_now_to_3sigma(self):
        """L2 + T8 — value 4σ above mean must clip to 3σ; log emitted."""
        self._require_helpers()
        x_raw = {
            "active_swo_flag": 0.0,
            "complaint_velocity_14d": 50.0,  # 30σ above mean → clip
            "days_since_last_violation": 40.0,
            "schedule_position_ratio": 50.0,
            "district_caseload_proxy_days": 7.0,
        }
        mu = {
            "active_swo_flag": 0.2,
            "complaint_velocity_14d": 5.0,
            "days_since_last_violation": 40.0,
            "schedule_position_ratio": 50.0,
            "district_caseload_proxy_days": 7.0,
        }
        sigma = {
            "active_swo_flag": 0.4,
            "complaint_velocity_14d": 2.0,
            "days_since_last_violation": 25.0,
            "schedule_position_ratio": 25.0,
            "district_caseload_proxy_days": 3.0,
        }
        clipped, fields_clipped = winsorize_x_now(x_raw, mu, sigma, k=3.0)
        # Expected clip: 5.0 + 3*2.0 = 11.0
        self.assertAlmostEqual(
            clipped["complaint_velocity_14d"], 11.0, delta=1e-6,
            msg=(
                f"L2: x_now[complaint_velocity_14d]=50 must clip to "
                f"mu + 3*sigma = 5 + 3*2 = 11. Got "
                f"{clipped['complaint_velocity_14d']}."
            ),
        )
        self.assertIn(
            "complaint_velocity_14d", fields_clipped,
            msg="fields_clipped must include the clipped feature.",
        )

    # ── Test 6 — T3 latency assertion ────────────────

    def test_live_mutation_returns_within_100ms(self):
        """T3 — full live mutation under 100ms (warm cache)."""
        self._require_helpers()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {
            "_id": "P-LATENCY", "bbl": "3001000004", "borough": "BROOKLYN",
            "prediction_cache": {
                "schema_version": "pr15b_v1",
                "model_coefficients_hash": "abc",
                "last_validated_timestamp": now - timedelta(seconds=10),
                "prob_violation_7d": 0.05,
                "prob_violation_14d": 0.10,
                "prob_violation_30d": 0.18,
            },
        }
        db = _StubDb(
            projects=_StubProjectsForCache([project]),
            dob_logs=_StubDobLogs([]),
        )
        seed_prediction_models_fixture(
            db, project_id="P-LATENCY",
            beta={
                "intercept": -2.5, "active_swo_flag": 1.2,
                "complaint_velocity_14d": 0.3,
                "days_since_last_violation": -0.02,
                "schedule_position_ratio": 0.01,
                "district_caseload_proxy_days": 0.05,
            },
        )
        t0 = time.perf_counter()
        _run(predict_for_project_live(db, project, now=now))
        elapsed = time.perf_counter() - t0
        self.assertLess(
            elapsed, 0.100,
            msg=(
                f"T3 latency budget: predict_for_project_live must "
                f"complete in <100ms p99. Got {elapsed*1000:.1f}ms."
            ),
        )

    # ── Test 7 — L7 5-min staleness ─────────────────

    def test_live_mutation_refreshes_when_stale_gt_5min(self):
        """L7 — last_validated_timestamp > 5 min stale triggers refresh."""
        self._require_helpers()
        try:
            from lib.statistical_engine.live_mutation import (
                is_prediction_cache_stale,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement is_prediction_cache_stale"
                "(prediction_cache, *, now) -> bool. L7: True iff "
                "(now - last_validated_timestamp) > 300s. Strict >."
            )
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        cache_299 = {"last_validated_timestamp": now - timedelta(seconds=299)}
        cache_301 = {"last_validated_timestamp": now - timedelta(seconds=301)}
        self.assertFalse(
            is_prediction_cache_stale(cache_299, now=now),
            msg="L7: 299s old must NOT be stale.",
        )
        self.assertTrue(
            is_prediction_cache_stale(cache_301, now=now),
            msg="L7: 301s old MUST be stale.",
        )

    # ── Test 8 — L11 non-blocking pattern ─────────

    def test_live_mutation_non_blocking_returns_cached_immediately(self):
        """L11 — synchronous accessor returns cached prediction
        immediately; refresh runs as asyncio.create_task."""
        self._require_helpers()
        try:
            from lib.statistical_engine.live_mutation import (
                serve_prediction_cache_with_optional_refresh,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement serve_prediction_cache_"
                "with_optional_refresh(db, project, *, now=None) -> "
                "(cached_dict, refresh_task_or_None). L11 returns "
                "the existing prediction_cache immediately; if stale, "
                "schedules predict_for_project_live as a background "
                "task via asyncio.create_task. Non-blocking."
            )
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {
            "_id": "P-NONBLOCK", "bbl": "3001000005", "borough": "BROOKLYN",
            "prediction_cache": {
                "schema_version": "pr15b_v1",
                "model_coefficients_hash": "abc",
                "last_validated_timestamp": now - timedelta(minutes=10),
                "prob_violation_14d": 0.12,
            },
        }
        db = _StubDb(projects=_StubProjectsForCache([project]),
                     dob_logs=_StubDobLogs([]))
        seed_prediction_models_fixture(
            db, project_id="P-NONBLOCK",
            beta={
                "intercept": -2.5, "active_swo_flag": 1.2,
                "complaint_velocity_14d": 0.3,
                "days_since_last_violation": -0.02,
                "schedule_position_ratio": 0.01,
                "district_caseload_proxy_days": 0.05,
            },
        )

        async def _exercise():
            cached, refresh_task = await serve_prediction_cache_with_optional_refresh(
                db, project, now=now,
            )
            # 1 — cached prediction returned IMMEDIATELY
            assert cached["prob_violation_14d"] == 0.12, cached
            # 2 — refresh_task is a real Task object (or None if
            # not yet stale; this fixture IS stale → Task)
            assert refresh_task is not None, (
                "L11: stale cache must schedule a refresh task."
            )
            return refresh_task
        try:
            _run(_exercise())
        except AssertionError as e:
            self.fail(str(e))

    # ── Test 9 — T7 upsert pattern ──────────────────

    def test_live_mutation_writes_validation_ledger_upsert(self):
        self._require_helpers()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {
            "_id": "P-UPSERT", "bbl": "3001000006", "borough": "BROOKLYN",
            "prediction_cache": {
                "schema_version": "pr15b_v1",
                "model_coefficients_hash": "abc",
                "last_validated_timestamp": now - timedelta(minutes=10),
                "prob_violation_14d": 0.12,
            },
        }
        db = _StubDb(projects=_StubProjectsForCache([project]),
                     dob_logs=_StubDobLogs([]))
        seed_prediction_models_fixture(
            db, project_id="P-UPSERT",
            beta={
                "intercept": -2.5, "active_swo_flag": 1.2,
                "complaint_velocity_14d": 0.3,
                "days_since_last_violation": -0.02,
                "schedule_position_ratio": 0.01,
                "district_caseload_proxy_days": 0.05,
            },
        )
        _run(predict_for_project_live(db, project, now=now))
        ups = db.prediction_validation_ledger.update_one_calls
        self.assertGreaterEqual(
            len(ups), 1,
            msg=(
                "T7: live mutation must upsert a ledger entry. "
                "No update_one calls recorded."
            ),
        )
        last = ups[-1]
        self.assertTrue(
            last.get("upsert"),
            msg="T7: upsert=True required.",
        )
        self.assertEqual(
            last["filter"].get("project_id"), "P-UPSERT",
            msg="T7: filter must contain project_id.",
        )
        self.assertIn(
            "calendar_date", last["filter"],
            msg="T7: filter must contain calendar_date.",
        )

    # ── Test 10 — no prediction_cache yet ───────────

    def test_live_mutation_does_not_run_when_prediction_cache_absent(self):
        """Stage 3 — if no nightly fit yet, live mutation skips +
        logs '[pr15b] no model for {id}, skipping live mutation'."""
        self._require_helpers()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {"_id": "P-NEW", "bbl": "3001000007", "borough": "BROOKLYN"}
        # No prediction_cache → live mutation must be a no-op.
        db = _StubDb(projects=_StubProjectsForCache([project]),
                     dob_logs=_StubDobLogs([]))
        try:
            result = _run(predict_for_project_live(db, project, now=now))
        except Exception as e:
            self.fail(
                f"Live mutation must NOT crash for projects without "
                f"prediction_cache. Got: {e!r}. Stage 3: early-return "
                f"None when prediction_cache absent."
            )
        self.assertIsNone(
            result,
            msg="Live mutation on uncached project must return None.",
        )


if __name__ == "__main__":
    unittest.main()
