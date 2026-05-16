"""PR #15A.1 — startup-hook wiring tests for daily_panels +
prediction_validation_ledger indexes.

Three tests in TestPR15AIndexStartupWiring:

  1. test_pr15a_index_specs_iterated_at_startup
        RED at Stage 2.B — text-grep on server.py for the
        ALL_PR15A_INDEX_SPECS loop. Stage 3 lands the loop.

  2. test_all_pr15a_index_specs_present_and_complete
        GREEN at Stage 2.B (PR #15A landed the spec); serves
        as regression guard so the Stage 3 wiring change
        doesn't accidentally mutate the inventory.

  3. test_pr15a_index_specs_re_exported_from_init
        GREEN at Stage 2.B (PR #15A landed the re-export);
        serves as regression guard so a future cleanup PR
        can't silently drop the package-level attribute
        and brick the Stage 3 startup wiring.

Mirrors test_v2_2_schema_scaffolding.py's
TestServerPyV22Wiring + TestAllV22IndexSpecs + TestPackageReExports
patterns. Pure-static contract — no motor, no asyncio,
no fixtures, no stub-DB.
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


class TestPR15AIndexStartupWiring(unittest.TestCase):
    """PR #15A.1 — single-class test surface for daily_panels +
    prediction_validation_ledger index-creation wiring at FastAPI
    startup. Mirrors test_v2_2_schema_scaffolding.py's
    TestServerPyV22Wiring + TestAllV22IndexSpecs + TestPackageReExports.
    """

    @classmethod
    def setUpClass(cls):
        cls.server_text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    # ──────────────────────────────────────────────────────────
    # Test 1 — wiring assertion (text-grep on server.py)
    # ──────────────────────────────────────────────────────────

    def test_pr15a_index_specs_iterated_at_startup(self):
        """server.py:startup_event() must walk ALL_PR15A_INDEX_SPECS
        alongside the ALL_V22_INDEX_SPECS loop, ensuring the
        daily_panels + prediction_validation_ledger indexes are
        created at boot via _ensure_index_resilient."""
        needle = (
            "for _coll_name, _idx_specs in "
            "_stat_engine.ALL_PR15A_INDEX_SPECS:"
        )
        self.assertIn(
            needle, self.server_text,
            msg=(
                "Stage 3 PR #15A.1: in server.py:startup_event(), "
                "after the ALL_V22_INDEX_SPECS loop at line ~24969, "
                "add the parallel loop:\n"
                "  for _coll_name, _idx_specs in "
                "_stat_engine.ALL_PR15A_INDEX_SPECS:\n"
                "      _coll = db[_coll_name]\n"
                "      for _idx_spec in _idx_specs:\n"
                "          await _ensure_index_resilient(\n"
                "              _coll,\n"
                "              keys=_idx_spec['keys'],\n"
                "              name=_idx_spec['name'],\n"
                "              **{k: v for k, v in _idx_spec.items() "
                "if k not in ('keys', 'name')},\n"
                "          )\n"
                "This uses the existing resilient helper at "
                "server.py:570 (idempotent + drop-recreate on spec "
                "conflict)."
            ),
        )

    # ──────────────────────────────────────────────────────────
    # Test 2 — spec inventory + completeness (regression guard)
    # ──────────────────────────────────────────────────────────

    def test_all_pr15a_index_specs_present_and_complete(self):
        """Verify ALL_PR15A_INDEX_SPECS in schema.py exactly matches
        the locked 6-index inventory:
          • daily_panels (2): panels_project_built, panels_built_ttl
          • prediction_validation_ledger (4): validation_horizon,
            validation_project_predicted, validation_scored_brier,
            validation_project_day (unique).
        """
        from lib import statistical_engine as stat_engine

        specs = stat_engine.ALL_PR15A_INDEX_SPECS

        # 2.1 — exactly 2 collection entries
        self.assertEqual(
            len(specs), 2,
            msg=(
                f"ALL_PR15A_INDEX_SPECS must have exactly 2 entries "
                f"(daily_panels + prediction_validation_ledger). "
                f"Got {len(specs)}. Stage 3: re-check schema.py:237."
            ),
        )

        # 2.2 — collection-name coverage
        by_coll = {name: idx_tuple for name, idx_tuple in specs}
        self.assertEqual(
            set(by_coll.keys()),
            {"daily_panels", "prediction_validation_ledger"},
            msg=(
                "Collection-name set must be exactly "
                "{daily_panels, prediction_validation_ledger}. "
                "Stage 3: verify DAILY_PANELS_COLLECTION + "
                "PREDICTION_VALIDATION_LEDGER_COLLECTION constants."
            ),
        )

        # 2.3 — daily_panels has 2 named indexes
        dp_names = {s["name"] for s in by_coll["daily_panels"]}
        self.assertEqual(
            dp_names,
            {"panels_project_built", "panels_built_ttl"},
            msg=(
                f"daily_panels index names must be exactly "
                f"{{panels_project_built, panels_built_ttl}}. "
                f"Got {dp_names}. Stage 3: re-check "
                f"DAILY_PANELS_INDEXES."
            ),
        )

        # 2.4 — prediction_validation_ledger has 4 named indexes
        vl_names = {
            s["name"] for s in by_coll["prediction_validation_ledger"]
        }
        self.assertEqual(
            vl_names,
            {
                "validation_horizon",
                "validation_project_predicted",
                "validation_scored_brier",
                "validation_project_day",
            },
            msg=(
                f"prediction_validation_ledger index names must be "
                f"exactly {{validation_horizon, "
                f"validation_project_predicted, "
                f"validation_scored_brier, "
                f"validation_project_day}}. Got {vl_names}. "
                f"Stage 3: re-check "
                f"PREDICTION_VALIDATION_LEDGER_INDEXES."
            ),
        )

        # 2.5 — validation_project_day has unique=True
        vpd = next(
            s for s in by_coll["prediction_validation_ledger"]
            if s["name"] == "validation_project_day"
        )
        self.assertTrue(
            vpd.get("unique") is True,
            msg=(
                "validation_project_day MUST carry unique=True so "
                "the T7 canonical-per-(project, day) contract is "
                "enforced at the DB layer (defense in depth against "
                "the _upsert_validation_ledger_entry caller)."
            ),
        )

        # 2.6 — panels_built_ttl has expireAfterSeconds=604800 (7d)
        ttl = next(
            s for s in by_coll["daily_panels"]
            if s["name"] == "panels_built_ttl"
        )
        self.assertEqual(
            ttl.get("expireAfterSeconds"), 7 * 86400,
            msg=(
                f"panels_built_ttl must expire after 7 days "
                f"(604800 seconds) per Stage 2.A T6 cadence "
                f"(single missed nightly leaves yesterday's panel "
                f"usable). Got expireAfterSeconds="
                f"{ttl.get('expireAfterSeconds')}."
            ),
        )

    # ──────────────────────────────────────────────────────────
    # Test 3 — re-export pinning (regression guard)
    # ──────────────────────────────────────────────────────────

    def test_pr15a_index_specs_re_exported_from_init(self):
        """Pin ALL_PR15A_INDEX_SPECS as accessible via the package
        __init__, so server.py's
        `_stat_engine.ALL_PR15A_INDEX_SPECS` attribute-access works
        without breaking. Done in PR #15A; re-verified here so a
        future cleanup PR can't silently drop the re-export and
        brick PR #15A.1 startup wiring."""
        from lib import statistical_engine as stat_engine

        self.assertTrue(
            hasattr(stat_engine, "ALL_PR15A_INDEX_SPECS"),
            msg=(
                "lib.statistical_engine must re-export "
                "ALL_PR15A_INDEX_SPECS. Stage 3 PR #15A.1: "
                "re-export already in place from PR #15A. If "
                "missing, add to lib/statistical_engine/__init__.py."
            ),
        )
        self.assertEqual(
            len(stat_engine.ALL_PR15A_INDEX_SPECS), 2,
            msg=(
                "ALL_PR15A_INDEX_SPECS must have len()==2 "
                "(daily_panels + prediction_validation_ledger)."
            ),
        )


if __name__ == "__main__":
    unittest.main()
