"""Phase V2.2 — Commit 1 schema scaffolding tests.

Pin every contract that V2.2 Commit 1 promises:

  • The 11 V2.2 collections exist in lib.statistical_engine.schema
    with the documented constants.
  • Every NYC-source collection has the four-index baseline
    (record_id unique, bin/date, borough/date, date) plus a
    dedicated bbl/date index for nyc_complaints_311.
  • PLUTO has bin-unique + bbl + borough/class indexes
    (PLUTO is a snapshot, not an event stream).
  • statistical_baselines, predicted_events, prediction_outcomes,
    ingestion_state all have their documented indexes.
  • ALL_V22_INDEX_SPECS covers every V2.2 collection.
  • MODEL_VERSION pinned to "statistical-v1".
  • score_band cutoffs match V2.1.2 backend (≤30 / ≤60 / ≤80 / >80)
    so the FE bandFor helper in RiskScoreCircle.jsx stays in sync.
  • Sample-size + confidence thresholds (20+, 0.70+) pinned per
    spec.
  • V2.1 lib path (lib/risk_score/*) is GONE — importing it fails.
  • V2.1 server.py surfaces (v2_risk_score flag, helper, scheduler
    tick) are GONE.
  • V2.2 server.py wiring: endpoints in place, ALL_V22_INDEX_SPECS
    registered at startup, _stat_engine import line present.
  • Frontend RiskScoreCircle + RiskScoreDrawer files still exist
    with first-hook + band-threshold pins (carrying the V2.1.2 +
    V2.1.4 invariants forward against the V2.2 backend).
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
# Collection names + counts
# ──────────────────────────────────────────────────────────────────


class TestCollectionNames(unittest.TestCase):

    def test_eleven_collections(self):
        self.assertEqual(len(se_schema.ALL_V22_COLLECTIONS), 11)

    def test_nyc_violations_name(self):
        self.assertEqual(se_schema.NYC_VIOLATIONS_COLLECTION, "nyc_violations")

    def test_nyc_inspections_name(self):
        self.assertEqual(
            se_schema.NYC_INSPECTIONS_COLLECTION, "nyc_inspections")

    def test_nyc_permits_name(self):
        self.assertEqual(se_schema.NYC_PERMITS_COLLECTION, "nyc_permits")

    def test_nyc_complaints_311_name(self):
        self.assertEqual(
            se_schema.NYC_COMPLAINTS_311_COLLECTION, "nyc_complaints_311")

    def test_nyc_ecb_violations_name(self):
        self.assertEqual(
            se_schema.NYC_ECB_VIOLATIONS_COLLECTION, "nyc_ecb_violations")

    def test_nyc_hpd_violations_name(self):
        self.assertEqual(
            se_schema.NYC_HPD_VIOLATIONS_COLLECTION, "nyc_hpd_violations")

    def test_nyc_pluto_name(self):
        self.assertEqual(se_schema.NYC_PLUTO_COLLECTION, "nyc_pluto")

    def test_statistical_baselines_name(self):
        self.assertEqual(
            se_schema.STATISTICAL_BASELINES_COLLECTION,
            "statistical_baselines",
        )

    def test_predicted_events_name(self):
        self.assertEqual(
            se_schema.PREDICTED_EVENTS_COLLECTION, "predicted_events")

    def test_prediction_outcomes_name(self):
        self.assertEqual(
            se_schema.PREDICTION_OUTCOMES_COLLECTION, "prediction_outcomes")

    def test_ingestion_state_name(self):
        self.assertEqual(
            se_schema.INGESTION_STATE_COLLECTION, "ingestion_state")


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
        # None defaults to green (defensive).
        self.assertEqual(se_schema.score_band(None), "green")

    def test_min_peer_sample_size(self):
        # Spec §peer matching: "Fallback only if sample < 20."
        self.assertEqual(se_schema.MIN_PEER_SAMPLE_SIZE, 20)

    def test_min_confidence_threshold(self):
        # Spec §triggers: "Confidence threshold 70%."
        self.assertEqual(se_schema.MIN_CONFIDENCE_THRESHOLD, 0.70)


# ──────────────────────────────────────────────────────────────────
# Index specs — NYC source datasets
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


class TestNycSourceIndexes(unittest.TestCase):
    """Every NYC-source collection has the standard 4-index
    baseline: record_id unique + (bin, date) + (borough, date) +
    (date)."""

    def _check_baseline(self, specs, prefix):
        names = _index_names(specs)
        # record_id unique
        self.assertIn(f"{prefix}_record_id_unique", names)
        self.assertTrue(_has_unique_index_on(specs, "record_id"))
        # (bin, occurred_date)
        self.assertIn(f"{prefix}_bin_date", names)
        # (borough, occurred_date)
        self.assertIn(f"{prefix}_borough_date", names)
        # (occurred_date)
        self.assertIn(f"{prefix}_date", names)

    def test_nyc_violations(self):
        self._check_baseline(
            se_schema.NYC_VIOLATIONS_INDEXES, "nyc_violations")

    def test_nyc_inspections(self):
        self._check_baseline(
            se_schema.NYC_INSPECTIONS_INDEXES, "nyc_inspections")

    def test_nyc_permits(self):
        self._check_baseline(
            se_schema.NYC_PERMITS_INDEXES, "nyc_permits")

    def test_nyc_complaints_311_baseline(self):
        self._check_baseline(
            se_schema.NYC_COMPLAINTS_311_INDEXES, "nyc_complaints_311")

    def test_nyc_complaints_311_has_bbl_index(self):
        # 311 has an extra (bbl, date) index for the
        # neighbor-trigger (proximity via BBL block component).
        names = _index_names(se_schema.NYC_COMPLAINTS_311_INDEXES)
        self.assertIn("nyc_complaints_311_bbl_date", names)

    def test_nyc_ecb_violations(self):
        self._check_baseline(
            se_schema.NYC_ECB_VIOLATIONS_INDEXES, "nyc_ecb_violations")

    def test_nyc_hpd_violations(self):
        self._check_baseline(
            se_schema.NYC_HPD_VIOLATIONS_INDEXES, "nyc_hpd_violations")


class TestPlutoIndexes(unittest.TestCase):
    """PLUTO is a snapshot keyed by BIN (not an event stream)."""

    def test_bin_unique(self):
        self.assertTrue(_has_unique_index_on(
            se_schema.NYC_PLUTO_INDEXES, "bin"))

    def test_bbl_index(self):
        names = _index_names(se_schema.NYC_PLUTO_INDEXES)
        self.assertIn("nyc_pluto_bbl", names)

    def test_borough_class_index(self):
        names = _index_names(se_schema.NYC_PLUTO_INDEXES)
        self.assertIn("nyc_pluto_borough_class", names)


# ──────────────────────────────────────────────────────────────────
# Index specs — aggregation + prediction collections
# ──────────────────────────────────────────────────────────────────


class TestAggregationIndexes(unittest.TestCase):

    def test_baselines_peer_key_index(self):
        names = _index_names(se_schema.STATISTICAL_BASELINES_INDEXES)
        self.assertIn("statistical_baselines_peer_key", names)

    def test_baselines_year_month_index(self):
        names = _index_names(se_schema.STATISTICAL_BASELINES_INDEXES)
        self.assertIn("statistical_baselines_year_month", names)

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

    def test_ingestion_state_dataset_unique(self):
        self.assertTrue(_has_unique_index_on(
            se_schema.INGESTION_STATE_INDEXES, "dataset"))


class TestAllV22IndexSpecs(unittest.TestCase):
    """ALL_V22_INDEX_SPECS is the iterable used by server.py at
    startup. It must cover every V2.2 collection — adding a new
    collection means adding a new entry here AND in ALL_V22_COLLECTIONS,
    and these tests catch a forgotten ALL_V22_INDEX_SPECS entry."""

    def test_covers_every_collection(self):
        covered = set(name for name, _ in se_schema.ALL_V22_INDEX_SPECS)
        all_collections = set(se_schema.ALL_V22_COLLECTIONS)
        self.assertEqual(covered, all_collections,
                         "ALL_V22_INDEX_SPECS doesn't match collection set")

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
        self.assertEqual(stat_engine.NYC_VIOLATIONS_COLLECTION,
                         "nyc_violations")
        self.assertEqual(stat_engine.PREDICTED_EVENTS_COLLECTION,
                         "predicted_events")

    def test_indexes_reexported(self):
        # Server.py needs ALL_V22_INDEX_SPECS to wire startup.
        self.assertTrue(hasattr(stat_engine, "ALL_V22_INDEX_SPECS"))
        self.assertEqual(len(stat_engine.ALL_V22_INDEX_SPECS), 11)

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
