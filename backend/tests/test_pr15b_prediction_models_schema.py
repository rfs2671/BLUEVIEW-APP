"""PR #15B — prediction_models collection schema + startup-hook tests.

6 tests in TestPR15BPredictionModelsSchema. Mirrors PR #15A.1's
test_pr15a_index_startup_wiring.py pattern.

Red-phase predictions (Stage 2.B → Stage 3):
  1. test_prediction_models_collection_name      — RED (constant missing)
  2. test_prediction_models_indexes_present      — RED (3 indexes missing)
  3. test_all_pr15b_index_specs_aggregator       — RED (aggregator missing)
  4. test_pr15b_index_specs_iterated_at_startup  — RED (server.py loop missing)
  5. test_all_pr15b_index_specs_re_exported      — RED (package re-export missing)
  6. test_models_fit_ttl_is_60_days              — RED (TTL value missing)
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


class TestPR15BPredictionModelsSchema(unittest.TestCase):
    """PR #15B — schema scaffolding tests for prediction_models
    collection. Validates 3 indexes (project_fit, hash, fit_ttl)
    are declared + re-exported + wired into server.py startup_event.
    """

    @classmethod
    def setUpClass(cls):
        cls.server_text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_prediction_models_collection_name(self):
        """L9 Stage 3 — schema.py must define PREDICTION_MODELS_COLLECTION."""
        from lib.statistical_engine import schema as se_schema
        self.assertTrue(
            hasattr(se_schema, "PREDICTION_MODELS_COLLECTION"),
            msg=(
                "Stage 3 PR #15B (L9): add to "
                "lib/statistical_engine/schema.py:\n"
                "  PREDICTION_MODELS_COLLECTION = \"prediction_models\"\n"
                "Then re-export from lib/statistical_engine/__init__.py."
            ),
        )
        self.assertEqual(
            se_schema.PREDICTION_MODELS_COLLECTION, "prediction_models",
            msg="Collection name must be exactly \"prediction_models\".",
        )

    def test_prediction_models_indexes_present_and_complete(self):
        """Stage 3 — PREDICTION_MODELS_INDEXES must contain exactly
        3 indexes: models_project_fit, models_hash, models_fit_ttl."""
        from lib.statistical_engine import schema as se_schema
        self.assertTrue(
            hasattr(se_schema, "PREDICTION_MODELS_INDEXES"),
            msg=(
                "Stage 3 PR #15B (L9): add PREDICTION_MODELS_INDEXES "
                "tuple to schema.py mirroring DAILY_PANELS_INDEXES "
                "shape. 3 indexes: models_project_fit (project_id "
                "ASC + fit_at DESC), models_hash (model_coefficients_"
                "hash), models_fit_ttl (fit_at ASC, expireAfterSeconds="
                "60 days = 5184000)."
            ),
        )
        names = {s["name"] for s in se_schema.PREDICTION_MODELS_INDEXES}
        self.assertEqual(
            names,
            {"models_project_fit", "models_hash", "models_fit_ttl"},
            msg=(
                f"PREDICTION_MODELS_INDEXES must contain exactly "
                f"3 indexes: models_project_fit, models_hash, "
                f"models_fit_ttl. Got {sorted(names)}."
            ),
        )

    def test_all_pr15b_index_specs_aggregator_present(self):
        """Stage 3 L9 — ALL_PR15B_INDEX_SPECS aggregator must be
        defined in schema.py for the server.py startup loop walker.
        """
        from lib.statistical_engine import schema as se_schema
        self.assertTrue(
            hasattr(se_schema, "ALL_PR15B_INDEX_SPECS"),
            msg=(
                "Stage 3 PR #15B (L9): add to schema.py near line 240, "
                "mirroring ALL_PR15A_INDEX_SPECS:\n"
                "  ALL_PR15B_INDEX_SPECS = (\n"
                "      (PREDICTION_MODELS_COLLECTION, "
                "PREDICTION_MODELS_INDEXES),\n"
                "  )"
            ),
        )
        self.assertEqual(
            len(se_schema.ALL_PR15B_INDEX_SPECS), 1,
            msg=(
                "ALL_PR15B_INDEX_SPECS must have exactly 1 entry "
                "(prediction_models). Got "
                f"{len(se_schema.ALL_PR15B_INDEX_SPECS)}."
            ),
        )

    def test_pr15b_index_specs_iterated_at_startup(self):
        """Stage 3 L9 — server.py:startup_event() must walk
        ALL_PR15B_INDEX_SPECS alongside ALL_V22_INDEX_SPECS +
        ALL_PR15A_INDEX_SPECS."""
        needle = (
            "for _coll_name, _idx_specs in "
            "_stat_engine.ALL_PR15B_INDEX_SPECS:"
        )
        self.assertIn(
            needle, self.server_text,
            msg=(
                "Stage 3 PR #15B (L9): after the ALL_PR15A_INDEX_SPECS "
                "loop, add the parallel ALL_PR15B_INDEX_SPECS loop in "
                "server.py:startup_event(). Mirrors PR #15A.1 wiring."
            ),
        )

    def test_pr15b_index_specs_re_exported_from_init(self):
        """Stage 3 L9 — ALL_PR15B_INDEX_SPECS accessible via package
        __init__ so server.py's _stat_engine.ALL_PR15B_INDEX_SPECS
        attribute-access works."""
        from lib import statistical_engine as stat_engine
        self.assertTrue(
            hasattr(stat_engine, "ALL_PR15B_INDEX_SPECS"),
            msg=(
                "Stage 3 PR #15B (L9): re-export ALL_PR15B_INDEX_SPECS "
                "and PREDICTION_MODELS_COLLECTION from "
                "lib/statistical_engine/__init__.py."
            ),
        )
        self.assertTrue(
            hasattr(stat_engine, "PREDICTION_MODELS_COLLECTION"),
            msg="Re-export PREDICTION_MODELS_COLLECTION too.",
        )

    def test_models_fit_ttl_is_60_days(self):
        """Stage 3 — models_fit_ttl must carry expireAfterSeconds=
        60*86400=5184000 (60 days retention for drift detection)."""
        from lib.statistical_engine import schema as se_schema
        if not hasattr(se_schema, "PREDICTION_MODELS_INDEXES"):
            self.fail(
                "Stage 3 PR #15B (L9): PREDICTION_MODELS_INDEXES not "
                "defined. See test_prediction_models_indexes_present_"
                "and_complete for the spec."
            )
        ttl = next(
            (s for s in se_schema.PREDICTION_MODELS_INDEXES
             if s["name"] == "models_fit_ttl"),
            None,
        )
        self.assertIsNotNone(
            ttl,
            msg=(
                "models_fit_ttl index missing. Stage 3: "
                "{'keys': [('fit_at', 1)], 'name': 'models_fit_ttl', "
                "'expireAfterSeconds': 60 * 86400}."
            ),
        )
        self.assertEqual(
            ttl.get("expireAfterSeconds"), 60 * 86400,
            msg=(
                f"models_fit_ttl must expire after 60 days = 5184000s. "
                f"Got expireAfterSeconds={ttl.get('expireAfterSeconds')}."
            ),
        )


if __name__ == "__main__":
    unittest.main()
