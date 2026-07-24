"""Phase V2.2 — Commit 1 schema scaffolding tests.

V2.3 Commit 1 trim: the V2.2 local-mirror collections
(nyc_violations / nyc_inspections / nyc_permits / nyc_complaints_311
/ nyc_ecb_violations / nyc_hpd_violations / nyc_pluto /
statistical_baselines / ingestion_state) are being replaced by
lazy Socrata queries. The constants + index specs that pinned
those collections are gone from schema.py — assertions about
them have been dropped here.

What survives in this file:

  • predicted_events + prediction_outcomes collection names
    (these are written by the trigger detector + calibration,
    which keep their MongoDB state).
  • MODEL_VERSION pinned to "statistical-v1".
  • score_band cutoffs match V2.1.2 backend (≤30 / ≤60 / ≤80 / >80)
    so the FE bandFor helper in RiskScoreCircle.jsx stays in sync.
  • Sample-size + confidence thresholds (20+, 0.70+) pinned per
    spec.
  • predicted_events + prediction_outcomes indexes.
  • ALL_V22_INDEX_SPECS covers the surviving 2 collections + no
    duplicate index names.
  • V2.1 lib path (lib/risk_score/*) is GONE — importing it fails.
  • V2.1 server.py surfaces (v2_risk_score flag, helper, scheduler
    tick) are GONE.
  • V2.2 server.py wiring: endpoints in place, ALL_V22_INDEX_SPECS
    registered at startup, _stat_engine import line present.
  • Frontend RiskScoreCircle + RiskScoreDrawer files still exist
    with first-hook + band-threshold pins (carrying the V2.1.2 +
    V2.1.4 invariants forward against the V2.2/V2.3 backend).
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from importlib import import_module
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from lib import statistical_engine as stat_engine  # noqa: E402
from lib.statistical_engine import schema as se_schema  # noqa: E402


# ──────────────────────────────────────────────────────────────────
# Surviving collection names (V2.3 Commit 1: only the two
# prediction-state collections remain in schema.py)
# ──────────────────────────────────────────────────────────────────


class TestCollectionNames(unittest.TestCase):

    def test_predicted_events_name(self):
        self.assertEqual(
            se_schema.PREDICTED_EVENTS_COLLECTION, "predicted_events")

    def test_prediction_outcomes_name(self):
        self.assertEqual(
            se_schema.PREDICTION_OUTCOMES_COLLECTION, "prediction_outcomes")


# ──────────────────────────────────────────────────────────────────
# Model version, band thresholds, sample-size guards
# ──────────────────────────────────────────────────────────────────


class TestVersionAndThresholds(unittest.TestCase):

    def test_model_version_pinned(self):
        # New version string for the statistical model — bumped
        # from V2.1's "heuristic-v1" so historical scores aren't
        # confused across model generations.
        self.assertEqual(se_schema.MODEL_VERSION, "statistical-v1")

    def test_band_thresholds_match_v21_cutoffs(self):
        # Same cutoffs as V2.1: ≤30 green, ≤60 yellow, ≤80 orange,
        # >80 red. The frontend bandFor helper depends on this.
        self.assertEqual(se_schema.score_band(0),   "green")
        self.assertEqual(se_schema.score_band(29),  "green")
        self.assertEqual(se_schema.score_band(30),  "green")
        self.assertEqual(se_schema.score_band(31),  "yellow")
        self.assertEqual(se_schema.score_band(60),  "yellow")
        self.assertEqual(se_schema.score_band(61),  "orange")
        self.assertEqual(se_schema.score_band(80),  "orange")
        self.assertEqual(se_schema.score_band(81),  "red")
        self.assertEqual(se_schema.score_band(100), "red")
        # 0 is a REAL score — it must stay green, never pending.
        self.assertEqual(se_schema.score_band(0),   "green")
        # Missing / uncomputed / invalid scores return "pending", NOT
        # green — an uncomputed score must not read as low-risk. Guarded
        # before any numeric comparison.
        self.assertEqual(se_schema.score_band(None),        "pending")
        self.assertEqual(se_schema.score_band(float("nan")), "pending")
        self.assertEqual(se_schema.score_band("abc"),       "pending")

    def test_min_peer_sample_size(self):
        # Spec §peer matching: "Fallback only if sample < 20."
        self.assertEqual(se_schema.MIN_PEER_SAMPLE_SIZE, 20)

    def test_min_confidence_threshold(self):
        # Spec §triggers: "Confidence threshold 70%."
        self.assertEqual(se_schema.MIN_CONFIDENCE_THRESHOLD, 0.70)


# ──────────────────────────────────────────────────────────────────
# Index specs — surviving aggregation + prediction collections
# ──────────────────────────────────────────────────────────────────


def _index_names(specs):
    return [s["name"] for s in specs]


def _has_unique_index_on(specs, *fields):
    for s in specs:
        if not s.get("unique"):
            continue
        keys = [k for k, _dir in s["keys"]]
        if keys == list(fields):
            return True
    return False


class TestAggregationIndexes(unittest.TestCase):

    def test_predicted_events_project_expires_index(self):
        names = _index_names(se_schema.PREDICTED_EVENTS_INDEXES)
        self.assertIn("predicted_events_project_expires", names)

    def test_predicted_events_expires_index(self):
        # Calibration sweep needs to find every prediction
        # expiring by `now` to attribute hit/miss.
        names = _index_names(se_schema.PREDICTED_EVENTS_INDEXES)
        self.assertIn("predicted_events_expires", names)

    def test_predicted_events_trigger_predicted_index(self):
        names = _index_names(se_schema.PREDICTED_EVENTS_INDEXES)
        self.assertIn("predicted_events_trigger_predicted", names)

    def test_prediction_outcomes_trigger_expired_index(self):
        names = _index_names(se_schema.PREDICTION_OUTCOMES_INDEXES)
        self.assertIn("prediction_outcomes_trigger_expired", names)

    def test_prediction_outcomes_project_expired_index(self):
        names = _index_names(se_schema.PREDICTION_OUTCOMES_INDEXES)
        self.assertIn("prediction_outcomes_project_expired", names)


class TestAllV22IndexSpecs(unittest.TestCase):
    """ALL_V22_INDEX_SPECS is the iterable used by server.py at
    startup. V2.3 Commit 1: it now covers only the two surviving
    collections (predicted_events + prediction_outcomes)."""

    def test_only_surviving_collections(self):
        covered = set(name for name, _ in se_schema.ALL_V22_INDEX_SPECS)
        self.assertEqual(
            covered,
            {
                se_schema.PREDICTED_EVENTS_COLLECTION,
                se_schema.PREDICTION_OUTCOMES_COLLECTION,
            },
        )

    def test_no_duplicate_index_names_across_collections(self):
        # Index names are globally unique within the codebase to
        # avoid Mongo-level conflicts when two collections
        # accidentally share an index name.
        seen = []
        for _coll, specs in se_schema.ALL_V22_INDEX_SPECS:
            for s in specs:
                seen.append(s["name"])
        dupes = [n for n in seen if seen.count(n) > 1]
        self.assertEqual(set(dupes), set(),
                         f"duplicate index names: {sorted(set(dupes))}")


class TestPackageReExports(unittest.TestCase):
    """The package __init__ re-exports the constants the rest of
    the codebase reads. server.py does
    `import lib.statistical_engine as _stat_engine` and then
    accesses `_stat_engine.ALL_V22_INDEX_SPECS` etc. — pin those
    re-exports."""

    def test_collection_names_reexported(self):
        self.assertEqual(stat_engine.PREDICTED_EVENTS_COLLECTION,
                         "predicted_events")
        self.assertEqual(stat_engine.PREDICTION_OUTCOMES_COLLECTION,
                         "prediction_outcomes")

    def test_indexes_reexported(self):
        # Server.py needs ALL_V22_INDEX_SPECS to wire startup.
        # V2.3 Commit 1: shrank from 11 to 2 (the prediction
        # state collections only).
        self.assertTrue(hasattr(stat_engine, "ALL_V22_INDEX_SPECS"))
        self.assertEqual(len(stat_engine.ALL_V22_INDEX_SPECS), 2)

    def test_model_version_reexported(self):
        self.assertEqual(stat_engine.MODEL_VERSION, "statistical-v1")

    def test_score_band_reexported(self):
        # Server.py + future scoring code call
        # _stat_engine.score_band — pin the helper is callable.
        self.assertEqual(stat_engine.score_band(50), "yellow")

    def test_threshold_constants_reexported(self):
        self.assertEqual(stat_engine.MIN_PEER_SAMPLE_SIZE, 20)
        self.assertAlmostEqual(stat_engine.MIN_CONFIDENCE_THRESHOLD, 0.70)


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 1: removed schema surfaces are actually gone
# ──────────────────────────────────────────────────────────────────


class TestV22MirrorSurfacesRemoved(unittest.TestCase):
    """The V2.2 local-mirror constants and their index specs
    must NOT be on the schema module anymore. They live
    transitionally in lib.statistical_engine.utils (consumed by
    baselines.py / triggers.py / score.py / calibration.py until
    Commit 3), but schema.py is no longer the source."""

    def test_nyc_collection_constants_gone(self):
        for name in (
            "NYC_VIOLATIONS_COLLECTION",
            "NYC_INSPECTIONS_COLLECTION",
            "NYC_PERMITS_COLLECTION",
            "NYC_COMPLAINTS_311_COLLECTION",
            "NYC_ECB_VIOLATIONS_COLLECTION",
            "NYC_HPD_VIOLATIONS_COLLECTION",
            "NYC_PLUTO_COLLECTION",
            "STATISTICAL_BASELINES_COLLECTION",
            "INGESTION_STATE_COLLECTION",
            "ALL_V22_COLLECTIONS",
        ):
            self.assertFalse(
                hasattr(se_schema, name),
                f"schema.py still exposes {name}; should have been removed",
            )

    def test_nyc_index_specs_gone(self):
        for name in (
            "NYC_VIOLATIONS_INDEXES",
            "NYC_INSPECTIONS_INDEXES",
            "NYC_PERMITS_INDEXES",
            "NYC_COMPLAINTS_311_INDEXES",
            "NYC_ECB_VIOLATIONS_INDEXES",
            "NYC_HPD_VIOLATIONS_INDEXES",
            "NYC_PLUTO_INDEXES",
            "STATISTICAL_BASELINES_INDEXES",
            "INGESTION_STATE_INDEXES",
        ):
            self.assertFalse(
                hasattr(se_schema, name),
                f"schema.py still exposes {name}; should have been removed",
            )

    def test_nyc_source_indexes_helper_gone(self):
        self.assertFalse(hasattr(se_schema, "_nyc_source_indexes"))


# ──────────────────────────────────────────────────────────────────
# V2.1 removal verification
# ──────────────────────────────────────────────────────────────────


class TestV21LibRemoved(unittest.TestCase):
    """The V2.1 module path is gone. Anything that imports from
    `lib.risk_score` should fail. This catches a future commit
    that accidentally re-introduces the old module."""

    def test_import_fails(self):
        with self.assertRaises((ImportError, ModuleNotFoundError)):
            import_module("lib.risk_score.heuristic")

    def test_schema_module_gone(self):
        path = _BACKEND / "lib" / "risk_score" / "schema.py"
        self.assertFalse(path.exists())

    def test_heuristic_module_gone(self):
        path = _BACKEND / "lib" / "risk_score" / "heuristic.py"
        self.assertFalse(path.exists())

    def test_calibration_module_gone(self):
        path = _BACKEND / "lib" / "risk_score" / "calibration.py"
        self.assertFalse(path.exists())

    def test_orchestrator_module_gone(self):
        path = _BACKEND / "lib" / "risk_score" / "orchestrator.py"
        self.assertFalse(path.exists())


class TestServerPyV21Removed(unittest.TestCase):
    """server.py must NOT contain any V2.1 surface area:
      • `_risk_score_flag_enabled_for` helper
      • `v2_risk_score` flag references
      • V2.1 scheduler tick id
      • imports from lib.risk_score
      • RiskScoreCalibrationRequest model
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_no_flag_helper(self):
        self.assertNotIn("_risk_score_flag_enabled_for", self.text)

    def test_no_flag_string(self):
        # The flag name should not appear anywhere — V2.2 has no
        # flag, so even a stale string reference would be a smell.
        self.assertNotIn('"v2_risk_score"', self.text)
        self.assertNotIn("'v2_risk_score'", self.text)

    def test_no_v21_scheduler_tick(self):
        self.assertNotIn("v2_risk_score_daily_tick", self.text)

    def test_no_lib_risk_score_import(self):
        self.assertNotIn("import lib.risk_score", self.text)
        self.assertNotIn("from lib.risk_score", self.text)

    def test_no_calibration_request_model(self):
        # Old V2.1 admin calibration request shape is gone.
        self.assertNotIn("RiskScoreCalibrationRequest", self.text)

    def test_no_v21_risk_score_404_helper(self):
        # The "hide endpoint behind 404 if flag off" helper went
        # away with the flag.
        self.assertNotIn("_risk_score_404", self.text)


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 1: server.py V2.2 cron + backfill removal
# ──────────────────────────────────────────────────────────────────


class TestServerPyV22CronTicksRemoved(unittest.TestCase):
    """V2.3 Commit 1 stripped the three V2.2 scheduler ticks +
    the V22 backfill endpoint + the V22BackfillRequest model.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_no_weekly_ingest_tick(self):
        self.assertNotIn("_v22_weekly_ingest_tick", self.text)
        self.assertNotIn("v2_2_weekly_ingest", self.text)

    def test_no_baseline_aggregator_tick(self):
        self.assertNotIn("_v22_baseline_aggregator_tick", self.text)
        self.assertNotIn("v2_2_baseline_aggregator", self.text)

    def test_no_calibration_tick(self):
        self.assertNotIn("_v22_calibration_tick", self.text)
        self.assertNotIn("v2_2_calibration_attribution", self.text)

    def test_no_backfill_endpoint(self):
        self.assertNotIn("V22BackfillRequest", self.text)
        self.assertNotIn(
            "/admin/risk-score/backfill", self.text,
        )


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 4: project-creation endpoints spawn prewarm_peer_stats
# ──────────────────────────────────────────────────────────────────


class TestServerPyV23PrewarmWiring(unittest.TestCase):
    """Commit 4 added a fire-and-forget ``prewarm_peer_stats``
    spawn to BOTH project creation endpoints:

        POST /api/projects                  (line ~6726)
        POST /api/onboarding/project        (line ~2839)

    The third site (test-data seed at startup, ~24107) is
    intentionally NOT wired per the Commit 4 spec.

    Each wiring must:
      • spawn via ``asyncio.create_task``
      • call ``_stat_engine.prewarm_peer_stats(db, result.inserted_id)``
      • include a ``name=`` tag for asyncio task debugging
      • wrap the spawn in try/except so project creation never
        fails because of pre-warm code
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def _slice_endpoint(self, anchor: str) -> str:
        """Return the text from ``anchor`` to the next
        ``@api_router`` decorator (i.e. the full handler body).
        Falls back to a generous span if the anchor is the last
        endpoint in the file."""
        s = self.text.find(anchor)
        self.assertGreater(s, 0, f"endpoint anchor not found: {anchor}")
        e = self.text.find("@api_router", s + len(anchor))
        if e < 0:
            # Last endpoint in file — take a wide window.
            e = min(len(self.text), s + 20000)
        return self.text[s:e]

    # NOTE (2026-07-23): the two POST /projects source-text tests that used
    # to live here — test_create_project_endpoint_spawns_prewarm and
    # test_create_project_endpoint_wraps_spawn_in_try_except — were removed
    # and replaced by a BEHAVIORAL test in
    # tests/test_prewarm_endpoint_wiring.py. Their substring anchor
    # ('@api_router.post("/projects", response_model=ProjectResponse)')
    # silently broke on 2026-07-19 when the decorator gained
    # dependencies=[Depends(require_approved)]; the production spawn was
    # never touched, yet the anchor stopped matching — and would have failed
    # identically had the spawn actually been deleted. The behavioral test
    # drives the endpoint and asserts the task is spawned, so it survives
    # decorator/formatting churn and fails only on a real regression. The
    # onboarding source-text tests below still match their anchor and are
    # left in place; replacing them is a separate decision.

    def test_onboarding_create_project_endpoint_spawns_prewarm(self):
        slice_ = self._slice_endpoint(
            '@api_router.post("/onboarding/project")',
        )
        self.assertIn("asyncio.create_task(", slice_)
        self.assertIn("_stat_engine.prewarm_peer_stats(db, result.inserted_id)",
                      slice_)
        self.assertIn(
            'name=f"prewarm_peer_stats:{result.inserted_id}"',
            slice_,
        )

    def test_onboarding_create_project_endpoint_wraps_spawn_in_try_except(self):
        slice_ = self._slice_endpoint(
            '@api_router.post("/onboarding/project")',
        )
        spawn_idx = slice_.find("asyncio.create_task(")
        self.assertGreater(spawn_idx, 0)
        preceding = slice_[:spawn_idx]
        last_try = preceding.rfind("try:")
        self.assertGreater(last_try, 0,
                           "prewarm spawn not wrapped in try block")
        following = slice_[spawn_idx:]
        self.assertIn("except Exception", following)
        self.assertIn("prewarm task spawn failed", following)

    def test_prewarm_NOT_wired_to_test_data_seed(self):
        """Site C — the test-data seeding block at line ~24107 —
        is intentionally NOT wired. Per Commit 4 spec Q1: skip
        test-data seed. Pin via a targeted search: the seed block
        creates an ESB test project; that block must not contain
        a prewarm spawn."""
        # Locate the test-project seed insert by its unique
        # marker.
        s = self.text.find("Test Project - ESB")
        self.assertGreater(s, 0, "test-data seed marker missing")
        # Walk forward to the end of the seed block (logger.info
        # is the closing marker).
        e = self.text.find("Test data seeding complete", s)
        self.assertGreater(e, s, "seed block end-marker missing")
        seed_slice = self.text[s:e]
        # No prewarm_peer_stats call within the seed block.
        self.assertNotIn("prewarm_peer_stats", seed_slice)


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 5: peer_stats refresh cron + index wiring
# ──────────────────────────────────────────────────────────────────


class TestServerPyV23RefreshCronWiring(unittest.TestCase):
    """Commit 5 wired three things in server.py:

      1. ``_peer_stats_refresh_tick`` wrapper-tick function
         (matches the ``_logbook_nightly_tick`` precedent —
         try/except + logger.error with exc_info=True).
      2. ``scheduler.add_job(_peer_stats_refresh_tick, ...)``
         registration with IntervalTrigger, max_instances=1,
         coalesce=True (cron-lock).
      3. ``_ensure_index_resilient`` for the compound index on
         peer_stats_cache.{status, last_refreshed_at} so the
         sweep query is index-backed.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_refresh_tick_function_defined(self):
        self.assertIn(
            "async def _peer_stats_refresh_tick():",
            self.text,
        )

    def test_refresh_tick_wraps_call_in_try_except(self):
        """Wrapper pattern from _logbook_nightly_tick — sweep
        crashes must be logged at ERROR with exc_info=True, not
        crash the scheduler."""
        s = self.text.find("async def _peer_stats_refresh_tick():")
        self.assertGreater(s, 0)
        # Walk forward to the end of the tick body (next
        # scheduler.add_job marks it).
        e = self.text.find("scheduler.add_job(", s)
        self.assertGreater(e, s)
        body = self.text[s:e]
        self.assertIn("try:", body)
        self.assertIn("refresh_stale_peer_stats_caches", body)
        self.assertIn("except Exception", body)
        self.assertIn("exc_info=True", body)

    def test_refresh_tick_registered_with_interval_trigger(self):
        """IntervalTrigger every REFRESH_TICK_MINUTES, id +
        replace_existing + max_instances=1 + coalesce=True."""
        s = self.text.find("id='peer_stats_refresh'")
        self.assertGreater(s, 0, "peer_stats_refresh job id missing")
        # Take a generous slice around the registration call.
        start = max(0, s - 500)
        end = min(len(self.text), s + 500)
        slice_ = self.text[start:end]
        self.assertIn("scheduler.add_job(", slice_)
        self.assertIn("_peer_stats_refresh_tick,", slice_)
        self.assertIn("IntervalTrigger(minutes=", slice_)
        self.assertIn("_stat_engine.REFRESH_TICK_MINUTES", slice_)
        self.assertIn("replace_existing=True", slice_)
        self.assertIn("max_instances=1", slice_)
        self.assertIn("coalesce=True", slice_)

    def test_peer_stats_index_ensured_at_startup(self):
        """Compound index on peer_stats_cache.{status,
        last_refreshed_at} ensured via _ensure_index_resilient."""
        s = self.text.find("projects_peer_stats_status_refreshed_at")
        self.assertGreater(s, 0, "peer_stats index name missing")
        # The call should be inside an _ensure_index_resilient
        # invocation against db.projects.
        start = max(0, s - 500)
        end = min(len(self.text), s + 500)
        slice_ = self.text[start:end]
        self.assertIn("_ensure_index_resilient(", slice_)
        self.assertIn("db.projects,", slice_)
        self.assertIn("peer_stats_cache.status", slice_)
        self.assertIn("peer_stats_cache.last_refreshed_at", slice_)


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 6: predictive inspection hook + 2 crons + opportunistic
# ──────────────────────────────────────────────────────────────────


class TestServerPyV23PredictionsHookWiring(unittest.TestCase):
    """Commit 6 wires four things in server.py:

      1. Prediction-spawn hook inside ``_ingest_311_for_project``
         immediately after the existing ``db.dob_logs.insert_one``
         + ``_send_critical_dob_alert_throttled`` block, gated by
         ALL FOUR suppression conditions (existing is None +
         not is_seed_transition_311 + severity == "Action" +
         _initial_scan_done).
      2. ``_prediction_resolution_sweep_tick`` — 30-min interval
         APScheduler tick with max_instances=1 + coalesce=True.
      3. ``_prediction_cleanup_tick`` — daily cron at 03:45 ET
         (NOT 03:15) with max_instances=1 + coalesce=True.
      4. Opportunistic resolution check fire-and-forget from
         GET ``/projects/{project_id}/risk-score``.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    # ── Hook predicate ──────────────────────────────────────────

    def _hook_slice(self) -> str:
        # The hook lives inside _ingest_311_for_project right
        # after db.dob_logs.insert_one. Anchor on the unique
        # task-name template.
        s = self.text.find('name=f"predict_inspection:')
        self.assertGreater(s, 0, "predict_inspection task spawn missing")
        start = max(0, s - 2000)
        end = min(len(self.text), s + 500)
        return self.text[start:end]

    def test_hook_predicate_checks_existing_is_None(self):
        slice_ = self._hook_slice()
        self.assertIn("existing is None", slice_)

    def test_hook_predicate_checks_not_seed_transition(self):
        slice_ = self._hook_slice()
        self.assertIn("not is_seed_transition_311", slice_)

    def test_hook_predicate_checks_severity_action(self):
        slice_ = self._hook_slice()
        self.assertIn('severity == "Action"', slice_)

    def test_hook_predicate_checks_initial_scan_done(self):
        slice_ = self._hook_slice()
        self.assertIn('_initial_scan_done(project_id, "311")', slice_)

    def test_hook_calls_stat_engine_try_predict(self):
        slice_ = self._hook_slice()
        self.assertIn(
            "_stat_engine.try_predict_inspection_from_complaint",
            slice_,
        )

    def test_hook_wraps_spawn_in_try_except(self):
        slice_ = self._hook_slice()
        # Walk back from the create_task to find the enclosing try.
        spawn_idx = slice_.find("asyncio.create_task(")
        self.assertGreater(spawn_idx, 0)
        preceding = slice_[:spawn_idx]
        last_try = preceding.rfind("try:")
        self.assertGreater(last_try, 0,
                           "predict-spawn not wrapped in try block")
        self.assertIn("except Exception", slice_[spawn_idx:])

    # ── Resolution sweep cron ──────────────────────────────────

    def test_resolution_sweep_tick_function_defined(self):
        self.assertIn(
            "async def _prediction_resolution_sweep_tick():",
            self.text,
        )

    def test_resolution_sweep_registered_30min_interval(self):
        s = self.text.find("id='prediction_resolution_sweep'")
        self.assertGreater(s, 0, "resolution sweep job id missing")
        start = max(0, s - 500)
        end = min(len(self.text), s + 500)
        slice_ = self.text[start:end]
        self.assertIn("scheduler.add_job(", slice_)
        self.assertIn("_prediction_resolution_sweep_tick,", slice_)
        self.assertIn("IntervalTrigger(minutes=30)", slice_)
        self.assertIn("replace_existing=True", slice_)
        self.assertIn("max_instances=1", slice_)
        self.assertIn("coalesce=True", slice_)

    # ── Daily cleanup cron ─────────────────────────────────────

    def test_cleanup_tick_function_defined(self):
        self.assertIn(
            "async def _prediction_cleanup_tick():",
            self.text,
        )

    def test_cleanup_registered_at_03_45_ET(self):
        """Q8 refinement: cleanup at 03:45 ET, NOT 03:15."""
        s = self.text.find("id='prediction_cleanup'")
        self.assertGreater(s, 0, "cleanup job id missing")
        start = max(0, s - 500)
        end = min(len(self.text), s + 500)
        slice_ = self.text[start:end]
        self.assertIn(
            'CronTrigger(hour=3, minute=45, timezone="America/New_York")',
            slice_,
        )
        self.assertIn("max_instances=1", slice_)
        self.assertIn("coalesce=True", slice_)

    # ── Opportunistic resolution check wire ────────────────────

    def test_opportunistic_resolution_check_wired_on_get_risk_score(self):
        # Anchor on the GET endpoint decorator + walk to the
        # next @api_router. The opportunistic spawn must appear
        # inside the handler body.
        s = self.text.find(
            '@api_router.get("/projects/{project_id}/risk-score")',
        )
        self.assertGreater(s, 0)
        e = self.text.find("@api_router", s + 1)
        slice_ = self.text[s:e]
        self.assertIn(
            "_stat_engine.opportunistic_resolution_check(db, project_id)",
            slice_,
        )
        self.assertIn("asyncio.create_task(", slice_)
        # Must be wrapped in try/except so a spawn-side bug
        # never breaks the GET.
        self.assertIn("except Exception", slice_)


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 7: notifications inbox endpoints + indexes + cron
# ──────────────────────────────────────────────────────────────────


class TestServerPyV23NotificationsInboxWiring(unittest.TestCase):
    """Commit 7 wires:

      1. ``lib/notifications_inbox.py`` import (under
         ``_notifications_inbox``).
      2. Four FE-facing endpoints:
           GET  /api/notifications
           GET  /api/notifications/unread-count
           POST /api/notifications/{notification_id}/mark-read
           POST /api/notifications/mark-all-read
         Each scoped to ``current_user`` via ``Depends(get_current_user)``
         and per-query ``user_id`` filter (no cross-user leakage).
      3. Five compound indexes on the ``notifications`` collection
         via ``_ensure_index_resilient``.
      4. ``_notifications_cleanup_tick`` cron at 03:55 ET
         (post Commit 6's 03:45 prediction cleanup).
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    # ── Import ─────────────────────────────────────────────────

    def test_notifications_inbox_module_imported(self):
        self.assertIn(
            "import lib.notifications_inbox as _notifications_inbox",
            self.text,
        )

    # ── Four endpoints exist ───────────────────────────────────

    def test_list_endpoint_present(self):
        self.assertIn(
            '@api_router.get("/notifications", tags=["Notifications"])',
            self.text,
        )

    def test_unread_count_endpoint_present(self):
        self.assertIn(
            '@api_router.get("/notifications/unread-count", tags=["Notifications"])',
            self.text,
        )

    def test_mark_read_endpoint_present(self):
        # The decorator wraps over multiple lines, so anchor on
        # the path + tags pair separately.
        self.assertIn(
            '"/notifications/{notification_id}/mark-read"', self.text,
        )

    def test_mark_all_read_endpoint_present(self):
        self.assertIn('"/notifications/mark-all-read"', self.text)

    # ── Auth dependency on every endpoint ──────────────────────

    def test_all_endpoints_gated_by_get_current_user(self):
        """Each of the 4 endpoint handlers must take
        ``current_user = Depends(get_current_user)``. Pin via
        per-handler search."""
        for handler in (
            "async def list_notifications(",
            "async def get_notifications_unread_count(",
            "async def mark_notification_read(",
            "async def mark_all_notifications_read(",
        ):
            s = self.text.find(handler)
            self.assertGreater(s, 0, f"{handler} not found")
            # Walk to the next handler-bodied decorator (or +800 chars).
            slice_ = self.text[s:s + 800]
            self.assertIn(
                "Depends(get_current_user)", slice_,
                f"{handler} missing auth dependency",
            )

    # ── User-scope filter on every endpoint ────────────────────

    def test_list_endpoint_scopes_query_to_user_id(self):
        s = self.text.find("async def list_notifications(")
        self.assertGreater(s, 0)
        e = self.text.find("@api_router", s + 1)
        slice_ = self.text[s:e]
        # The query dict must include user_id derived from current_user.
        self.assertIn('"user_id": user_id', slice_)
        # And status="active" as the default visibility filter.
        self.assertIn('"status":  "active"', slice_)

    def test_unread_count_scopes_query_to_user_id(self):
        s = self.text.find("async def get_notifications_unread_count(")
        self.assertGreater(s, 0)
        e = self.text.find("@api_router", s + 1)
        slice_ = self.text[s:e]
        self.assertIn('"user_id": user_id', slice_)
        self.assertIn('"read_at": None', slice_)

    def test_mark_read_uses_ownership_compound_filter(self):
        """The (_id, user_id) compound filter ensures cross-user
        mark-read attempts return 404 instead of writing to
        someone else's notification."""
        s = self.text.find("async def mark_notification_read(")
        self.assertGreater(s, 0)
        e = self.text.find("@api_router", s + 1)
        slice_ = self.text[s:e]
        self.assertIn(
            'to_query_id(notification_id), "user_id": user_id',
            slice_,
        )

    def test_mark_all_read_scopes_to_user_and_status(self):
        s = self.text.find("async def mark_all_notifications_read(")
        self.assertGreater(s, 0)
        e = self.text.find("@api_router", s + 1)
        slice_ = self.text[s:e]
        self.assertIn('"user_id": user_id', slice_)
        self.assertIn('"status":  "active"', slice_)
        self.assertIn('"read_at": None', slice_)

    # ── Indexes ────────────────────────────────────────────────

    def test_five_notifications_indexes_ensured(self):
        for name in (
            "notifications_user_created",
            "notifications_user_read_created",
            "notifications_project_created",
            "notifications_expires",
            "notifications_source_lookup",
        ):
            self.assertIn(
                f'name="{name}"', self.text,
                f"index {name} not ensured at startup",
            )

    # ── Cleanup cron ────────────────────────────────────────────

    def test_cleanup_tick_function_defined(self):
        self.assertIn(
            "async def _notifications_cleanup_tick():",
            self.text,
        )

    def test_cleanup_cron_registered_at_03_55_ET(self):
        s = self.text.find("id='notifications_cleanup'")
        self.assertGreater(s, 0, "cleanup cron job id missing")
        start = max(0, s - 500)
        end = min(len(self.text), s + 500)
        slice_ = self.text[start:end]
        self.assertIn(
            'CronTrigger(hour=3, minute=55, timezone="America/New_York")',
            slice_,
        )
        self.assertIn("_notifications_cleanup_tick,", slice_)
        self.assertIn("max_instances=1", slice_)
        self.assertIn("coalesce=True", slice_)


class TestPredictionsModuleCommit7Wiring(unittest.TestCase):
    """The WOULD-NOTIFY log line in predictions.py is replaced
    with a real ``dispatch_notification`` call wrapped in
    try/except so prediction storage success is not undone by a
    dispatch failure."""

    @classmethod
    def setUpClass(cls):
        cls.text = (
            _BACKEND / "lib" / "statistical_engine" / "predictions.py"
        ).read_text(encoding="utf-8")

    def test_would_notify_log_replaced(self):
        """The placeholder log string must be GONE from the
        module (verifies the WOULD-NOTIFY removal didn't get
        accidentally left behind)."""
        self.assertNotIn("WOULD NOTIFY", self.text)

    def test_dispatch_notification_imported(self):
        self.assertIn(
            "from lib.notifications_inbox import dispatch_notification",
            self.text,
        )

    def test_dispatch_called_with_documented_kwargs(self):
        """All the spec-documented kwargs appear in the dispatch
        call site."""
        # Anchor on the await dispatch_notification call. The
        # call spans many lines with nested expressions; take a
        # generous slice that comfortably covers the full call
        # site (~1500 chars).
        s = self.text.find("await dispatch_notification(")
        self.assertGreater(s, 0, "dispatch_notification call site missing")
        slice_ = self.text[s:s + 1500]
        for kwarg in (
            "project=project",
            'kind="inspection_prediction"',
            "severity=_severity",
            'title="Inspection Prediction"',
            'source_kind="prediction"',
            "source_id=",
            "metadata=",
            "expires_at=",
            'deeplink_anchor="predictions"',
        ):
            self.assertIn(
                kwarg, slice_,
                f"dispatch_notification missing kwarg: {kwarg}",
            )

    def test_dispatch_wrapped_in_try_except(self):
        """Dispatch failure must NOT undo the prediction storage
        that already succeeded above."""
        s = self.text.find("await dispatch_notification(")
        self.assertGreater(s, 0)
        # Walk back to find the enclosing try.
        preceding = self.text[:s]
        last_try = preceding.rfind("try:")
        self.assertGreater(last_try, 0,
                           "dispatch_notification not wrapped in try block")
        # And the except must mention the prediction-stored
        # invariant for log archaeology.
        slice_ = self.text[s:s + 1000]
        self.assertIn("except Exception", slice_)
        self.assertIn("prediction stored", slice_)


# ──────────────────────────────────────────────────────────────────
# V2.2 server.py wiring
# ──────────────────────────────────────────────────────────────────


class TestServerPyV22Wiring(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_stat_engine_imported(self):
        self.assertIn(
            "import lib.statistical_engine as _stat_engine",
            self.text,
        )

    def test_all_v22_index_specs_iterated_at_startup(self):
        # The startup loop walks ALL_V22_INDEX_SPECS to register
        # every V2.2 collection's indexes in one pass.
        self.assertIn(
            "for _coll_name, _idx_specs in _stat_engine.ALL_V22_INDEX_SPECS:",
            self.text,
        )

    def test_endpoints_present(self):
        # Three endpoints in Commit 1 (the FE-facing trio kept
        # path-compatible with V2.1):
        for path in (
            "/projects/{project_id}/risk-score",
            "/projects/{project_id}/risk-score/history",
            "/projects/{project_id}/risk-score/calculate",
        ):
            self.assertIn(path, self.text, f"endpoint {path} missing")

    def test_endpoints_no_flag_gate(self):
        """V2.2 has no feature flag. The new endpoints must NOT
        call any flag-check helper before doing their work."""
        # Find the V2.2 endpoint block and confirm no
        # is_feature_enabled call inside.
        anchor = '@api_router.get("/projects/{project_id}/risk-score")'
        s = self.text.find(anchor)
        self.assertGreater(s, 0)
        e = self.text.find(
            "@api_router.post(\"/projects/{project_id}/risk-score/calculate\")",
            s,
        )
        # Walk to the end of the calculate handler — search for
        # the next decorator.
        e_close = self.text.find("@api_router", e + 1)
        slice_ = self.text[s: e_close if e_close > 0 else len(self.text)]
        self.assertNotIn("is_feature_enabled", slice_)
        self.assertNotIn("feature_flags.is_feature_enabled", slice_)

    def test_risk_scores_indexes_still_registered(self):
        # The risk_scores collection (where the FE reads scores
        # from) needs its indexes regardless of V2.2 vs V2.1
        # because the FE query path hasn't changed.
        self.assertIn(
            "risk_scores_project_calculated_desc", self.text,
        )

    def test_calculate_uses_recompute_and_persist(self):
        # Commit 5 — the calculate endpoint now invokes the real
        # V2.2 scoring pipeline. The Commit 1 placeholder
        # ("queued" status) was replaced when Commit 5 wired
        # `_stat_engine.recompute_and_persist`. Pin the wiring
        # so a future regression that re-stubs the endpoint
        # surfaces immediately.
        anchor = "calculate_project_risk_score"
        s = self.text.find(anchor)
        self.assertGreater(s, 0)
        e = self.text.find("@api_router", s + len("calculate_project_risk_score"))
        slice_ = self.text[s:e if e > s else s + 1000]
        self.assertIn("_stat_engine.recompute_and_persist", slice_)


# ──────────────────────────────────────────────────────────────────
# Frontend — RiskScoreCircle / RiskScoreDrawer carry forward
# ──────────────────────────────────────────────────────────────────


class TestRiskScoreCircleStillPresent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = (
            cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""
        )

    def test_file_present(self):
        self.assertTrue(self.path.exists())

    def test_band_thresholds_match_backend(self):
        # The FE bandFor() helper must use the same cutoffs as
        # the backend score_band(). Same boundary check that V2.1.2
        # added — carried forward against the new V2.2 backend.
        cutoffs = [
            int(m) for m in re.findall(r"s\s*<=\s*(\d+)", self.text)
        ]
        # The first three cutoffs in the file are the bandFor
        # cutoffs (30, 60, 80). Other matches may exist from
        # later code; we only check the prefix.
        self.assertGreaterEqual(len(cutoffs), 3)
        self.assertEqual(cutoffs[:3], [30, 60, 80])

    def test_use_feature_flag_first_hook(self):
        # Inherited from V2.1.2 — the hook is still gated, even
        # though V2.2 has no flag. The hook just always returns
        # true now (or, if the operator removes the gate later,
        # always-true is the upgrade path). For Commit 1 we keep
        # the hook in place.
        self.assertIn("useFeatureFlag(", self.text)


class TestRiskScoreDrawerStillPresent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreDrawer.jsx"
        )

    def test_file_present(self):
        self.assertTrue(self.path.exists())


class TestOldRiskScoreCardDeleted(unittest.TestCase):
    """The deprecated RiskScoreCard.jsx is finally removed in V2.2
    Commit 1. V2.1.2 marked it deprecated, V2.1.4 left it as a
    reference; V2.2 has no use for it."""

    def test_file_removed(self):
        path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCard.jsx"
        )
        self.assertFalse(path.exists(),
                         "deprecated RiskScoreCard.jsx must be deleted")


if __name__ == "__main__":
    unittest.main()
