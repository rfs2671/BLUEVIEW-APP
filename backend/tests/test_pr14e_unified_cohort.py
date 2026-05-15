"""PR #14E Stage 2.B — Unified Cohort architecture integration tests.

PR #14D Menahan production validation revealed BIS legacy has zero
filings in the last 60 months — cohort builder structurally broken
for current-era projects. PR #14E pivots cohort source to a Modern
primary (pkdm-hqz6 = DOB NOW C of O, 2021+) with BIS Legacy
fallback (2018-06-30 to 2021-06-30 Golden Era).

This file holds 8 integration tests for the Unified Cohort:

  1. test_unified_cohort_modern_primary_when_above_100
  2. test_unified_cohort_legacy_extends_when_modern_below_100
  3. test_unified_cohort_per_row_provenance_marks_segment
  4. test_nb_yearbuilt_filter_applied (NB-only per Q3 lock)
  5. test_a1_target_state_uses_parser_with_pluto_fallback (Q5 hybrid)
  6. test_pkdm_date_parser_handles_mdy_am_pm_format (§7.7 lock)
  7. test_pkdm_job_type_case_insensitive_matching (Risk 3 lock)
  8. test_menahan_real_data_modern_cohort_populates (T8 canary)

All 8 RED at Stage 2.B. Stage 3 lands:
  • New baselines.py helpers: _parse_pkdm_date, _fetch_modern_cohort,
    _fetch_legacy_cohort
  • New constants: PR14E_SCHEMA_VERSION, DATASET_DOB_C_OF_O
  • COHORT_CONFIG entries gain modern_path + legacy_path dicts
  • compute_cohort_for_project rewires to Modern primary + Legacy
    fallback at <100 floor
  • peer_meta + peer_criteria gain cohort_source_segments,
    cohort_member_provenance, target_state

Test infra reuse: MockSocrataClient + _pr14b_fixtures helpers
(seed_menahan_realistic_dob_now, seed_pkdm_co_for_bin,
make_modern_cohort_fixture per Stage 2.A §4).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

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


# ─── Production symbol imports (eager — these all exist post-PR-14D) ─

from lib.statistical_engine import baselines as bl  # noqa: E402
from lib.statistical_engine.baselines import (  # noqa: E402
    compute_peer_stats_full,
)
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_PLUTO,
    DATASET_DOB_INSPECTIONS,
    DATASET_COMPLAINTS_311,
)


# ─── Lazy imports for PR #14E symbols (don't exist until Stage 3) ────

try:
    from lib.statistical_engine.baselines import PR14E_SCHEMA_VERSION  # type: ignore
    HAS_PR14E_SCHEMA_VERSION = True
except ImportError:
    PR14E_SCHEMA_VERSION = None  # type: ignore
    HAS_PR14E_SCHEMA_VERSION = False


try:
    from lib.statistical_engine.baselines import _parse_pkdm_date  # type: ignore
    HAS_PARSE_PKDM_DATE = True
except ImportError:
    _parse_pkdm_date = None  # type: ignore
    HAS_PARSE_PKDM_DATE = False


try:
    from lib.statistical_engine.baselines import _fetch_modern_cohort  # type: ignore
    HAS_FETCH_MODERN_COHORT = True
except ImportError:
    _fetch_modern_cohort = None  # type: ignore
    HAS_FETCH_MODERN_COHORT = False


# ─── Test infrastructure imports ──────────────────────────────────

from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    DATASET_BIS_JOB_FILINGS,
    DATASET_DOB_PERMITS,
    DATASET_DOB_C_OF_O,
    make_cohort_fixture,
    make_modern_cohort_fixture,
    seed_bis_for_bin,
    seed_dob_now_for_bin,
    seed_pkdm_co_for_bin,
    seed_menahan_realistic_dob_now,
)


# ──────────────────────────────────────────────────────────────────
# Module-local helpers (per §7.5 lock — _seed_modern_cohort_world
# stays in the test file rather than _pr14b_fixtures.py)
# ──────────────────────────────────────────────────────────────────


class _StubProjects:
    """Reusable projects-collection stub. Mirrors test_pr14c_wiring's
    _StubProjects. Kept local to this file per §7.5 (test-orchestration
    helpers stay in tests, not in fixtures)."""

    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.update_one_calls: List[Dict[str, Any]] = []

    async def update_one(self, filter_, update, upsert=False):
        self.update_one_calls.append({"filter": filter_, "update": update})
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    d.update(update["$set"])
                r = MagicMock(); r.upserted_id = None
                return r
        new_doc = dict(filter_)
        if "$set" in update:
            new_doc.update(update["$set"])
        self.docs.append(new_doc)
        r = MagicMock(); r.upserted_id = "new"
        return r

    async def find_one(self, filter_, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                return dict(d)
        return None


class _StubDb:
    def __init__(self, projects=None):
        self.projects = _StubProjects(projects)


def _menahan_like_project(
    *, pluto_numfloors: str = "2", **overrides
) -> Dict[str, Any]:
    """Menahan-shaped project doc for PR #14E tests.

    Mirrors test_pr14c_wiring's _menahan_like_project but with the
    pre-enlargement PLUTO snapshot (numfloors=2 default) so
    target-state derivation tests can verify parser-extracted
    target=4 wins over PLUTO fallback target=2.

    ``pluto_numfloors`` kwarg lets NB tests align the active
    project's pluto.numfloors with the seeded peer pool so the
    target_state filter passes the seeded peers through.
    """
    base = {
        "_id":              "P_MENAHAN_PR14E",
        "name":             "9 Menahan Street",
        "nyc_bin":          "3325703",
        "bbl":              "3033040024",
        "borough":          "BROOKLYN",
        "track_dob_status": True,
        "pluto_snapshot": {
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8",
            "numfloors": str(pluto_numfloors),
            "bldgarea": "8038", "lotarea": "2500",
        },
    }
    base.update(overrides)
    return base


def _seed_modern_cohort_world(
    socrata: MockSocrataClient,
    *,
    n_modern: int = 150,
    n_legacy: int = 0,
    project_type: str = "new_building",
    borough: str = "BROOKLYN",
    building_class: str = "C1",
    numfloors: int = 5,
    yearbuilt: int = 2020,
    legacy_pre__filing_date: str = "2020-01-15",
) -> Dict[str, Any]:
    """End-to-end seed for PR #14E Unified Cohort tests.

    Seeds 3 layers:
      1. Active project PLUTO + classifier source DOB NOW row
      2. n_modern Modern cohort (pkdm-hqz6 + PLUTO + rbx6-tga4 via
         make_modern_cohort_fixture)
      3. n_legacy Legacy cohort (BIS + C of O via make_cohort_fixture)
    """
    # Active project PLUTO snapshot.
    socrata.seed(DATASET_PLUTO, [{
        "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
        "landuse": "01", "block": "3040", "lot": "24",
        "zipcode": "11221", "cd": "304", "yearbuilt": "2020",
        "unitsres": "8", "unitstotal": "8",
        "numfloors": str(numfloors),
        "bldgarea": "8038", "lotarea": "2500",
    }])
    # Classifier source (drives dob_project_type via classifier).
    classifier_desc = {
        "new_building": "NEW BUILDING 5-STORY RESIDENTIAL 8 UNITS",
        "major_alt_with_enlargement":
            "VERTICAL AND HORIZONTAL ENLARGEMENT 4-STORY+CELLAR",
        "minor_alt": "INTERIOR PARTITION WORK. NO CHANGE IN USE.",
    }.get(project_type, "NEW BUILDING 5-STORY RESIDENTIAL")
    seed_dob_now_for_bin(
        socrata, bin="3325703",
        work_type="General Construction",
        job_description=classifier_desc,
    )

    # n_modern Modern cohort.
    if n_modern > 0 and project_type != "full_demo":
        make_modern_cohort_fixture(
            socrata, project_type=project_type, n_records=n_modern,
            bin_prefix="500100", bbl_prefix="500101",
            borough=borough, building_class=building_class,
            numfloors=numfloors, yearbuilt=yearbuilt,
        )

    # n_legacy Legacy cohort.
    bis_job_type = {
        "new_building":              "NB",
        "major_alt_with_enlargement":"A1",
        "minor_alt":                 "A2",
        "full_demo":                 "DM",
    }.get(project_type, "NB")
    if n_legacy > 0:
        make_cohort_fixture(
            socrata, project_type=project_type, n_records=n_legacy,
            bin_prefix="3033099", borough=borough,
            building_class=building_class,
            bis_job_type=bis_job_type,
            pre__filing_date=legacy_pre__filing_date,
            completed=True,
        )

    # Empty event datasets — tests override.
    socrata.seed(DATASET_DOB_INSPECTIONS, [])
    socrata.seed(DATASET_COMPLAINTS_311, [])

    return {
        "n_modern_seeded": n_modern,
        "n_legacy_seeded": n_legacy,
        "project_type":    project_type,
    }


# ──────────────────────────────────────────────────────────────────
# Signature check guards
# ──────────────────────────────────────────────────────────────────


_PEER_STATS_SIG = inspect.signature(compute_peer_stats_full)
HAS_DB_KWARG = "db" in _PEER_STATS_SIG.parameters


# ──────────────────────────────────────────────────────────────────
# Test class — TestUnifiedCohort (per §7.4 single-class layout)
# ──────────────────────────────────────────────────────────────────


class TestUnifiedCohort(unittest.TestCase):
    """PR #14E — 8 integration tests for the Unified Cohort
    architecture. Single class per §7.4.

    Tests pin BEHAVIOR not MECHANISM where possible. Each RED
    failure carries Stage 3 implementation hints with file:line
    targets + §/Q lock references.
    """

    def _require_db_kwarg(self):
        if not HAS_DB_KWARG:
            self.fail(
                "compute_peer_stats_full missing `db` kwarg. "
                "Pre-PR-14C signature. Fix should already be in "
                "place from PR #14C §6.1 — investigate if this fires."
            )

    def _require_pr14e_schema(self):
        if not HAS_PR14E_SCHEMA_VERSION:
            self.fail(
                "baselines.PR14E_SCHEMA_VERSION constant not "
                "defined. Stage 3 §7.3 + Risk 6: add "
                "``PR14E_SCHEMA_VERSION = 'pr14e'`` to baselines.py "
                "near PR14C_SCHEMA_VERSION. Schema check in "
                "compare_project_to_peers must invalidate any "
                "cache with schema_version != PR14E_SCHEMA_VERSION."
            )

    # ──────────────────────────────────────────────────────────
    # Test 1 — Modern primary at ≥100
    # ──────────────────────────────────────────────────────────

    def test_unified_cohort_modern_primary_when_above_100(self):
        """Q2 lock — Modern (pkdm-hqz6) is PRIMARY when its cohort
        ≥100. Legacy BIS does NOT fire. Cache surfaces
        ``cohort_source_segments`` with modern_count > 0 and
        legacy_count = 0.
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()
        socrata = MockSocrataClient()
        meta = _seed_modern_cohort_world(
            socrata, n_modern=150, n_legacy=0,
            project_type="major_alt_with_enlargement",
            building_class="C1", numfloors=4,
        )
        project = _menahan_like_project()
        db = _StubDb(projects=[dict(project)])
        cache = _run(compute_peer_stats_full(socrata, project, db=db))
        criteria = cache.get("peer_criteria") or {}
        segments = criteria.get("cohort_source_segments")
        self.assertIsNotNone(
            segments,
            "peer_criteria.cohort_source_segments missing. "
            "Stage 3 §7.6: emit "
            "``cohort_source_segments = {modern_count, legacy_count, "
            "modern_window_months, legacy_window_start, "
            "legacy_window_end}`` from compute_cohort_for_project; "
            "thread into peer_meta + _assemble_cache.",
        )
        self.assertEqual(
            segments.get("modern_count"), 150,
            f"Modern cohort with 150 seeded rows must populate "
            f"modern_count=150. Got {segments.get('modern_count')}. "
            f"Stage 3: wire _fetch_modern_cohort into "
            f"compute_cohort_for_project primary path.",
        )
        self.assertEqual(
            segments.get("legacy_count", 0), 0,
            "Modern ≥ 100 must NOT trigger Legacy. Q7 floor.",
        )
        # No BIS query fired.
        bis_calls = [
            c for c in socrata.calls if c[0] == DATASET_BIS_JOB_FILINGS
        ]
        self.assertEqual(
            len(bis_calls), 0,
            f"BIS Legacy MUST NOT fire when Modern ≥ 100. "
            f"Got {len(bis_calls)} BIS calls. Stage 3 Q7 lock: "
            f"short-circuit _fetch_legacy_cohort.",
        )

    # ──────────────────────────────────────────────────────────
    # Test 2 — Legacy extends when Modern < 100
    # ──────────────────────────────────────────────────────────

    def test_unified_cohort_legacy_extends_when_modern_below_100(self):
        """Q7 lock — Modern at 40 (under 100 floor) MUST trigger
        Legacy BIS extension. Total cohort grows past 40."""
        self._require_db_kwarg()
        self._require_pr14e_schema()
        socrata = MockSocrataClient()
        _seed_modern_cohort_world(
            socrata, n_modern=40, n_legacy=200,
            project_type="new_building",
            building_class="C1", numfloors=5, yearbuilt=2020,
        )
        project = _menahan_like_project(
            dob_project_type="new_building",
            pluto_numfloors="5",  # align with seeded peers
        )
        db = _StubDb(projects=[dict(project)])
        cache = _run(compute_peer_stats_full(socrata, project, db=db))
        segments = (cache.get("peer_criteria") or {}).get(
            "cohort_source_segments"
        ) or {}
        self.assertEqual(segments.get("modern_count"), 40)
        self.assertGreater(
            segments.get("legacy_count", 0), 0,
            f"Modern=40 (under 100 floor) MUST trigger Legacy. "
            f"Stage 3 Q7 lock: if len(modern_cohort) < 100, call "
            f"_fetch_legacy_cohort and merge with dedup by bbl.",
        )

    # ──────────────────────────────────────────────────────────
    # Test 3 — Per-row provenance marks segment
    # ──────────────────────────────────────────────────────────

    def test_unified_cohort_per_row_provenance_marks_segment(self):
        """§7.3 lock — peer_criteria.cohort_member_provenance is a
        list of dicts, each with ``source: "modern" | "legacy"``.
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()
        socrata = MockSocrataClient()
        _seed_modern_cohort_world(
            socrata, n_modern=40, n_legacy=200,
            project_type="new_building",
            building_class="C1", numfloors=5, yearbuilt=2020,
        )
        project = _menahan_like_project(
            dob_project_type="new_building",
            pluto_numfloors="5",  # align with seeded peers
        )
        db = _StubDb(projects=[dict(project)])
        cache = _run(compute_peer_stats_full(socrata, project, db=db))
        criteria = cache.get("peer_criteria") or {}
        provenance = criteria.get("cohort_member_provenance")
        self.assertIsNotNone(
            provenance,
            f"peer_criteria.cohort_member_provenance missing. "
            f"Stage 3 §7.3 + T4: emit list-of-dicts shape "
            f"``[{{'job_id': ..., 'source': 'modern'|'legacy'}}, ...]`` "
            f"sized to sample_size.",
        )
        # Length should match sample_size.
        self.assertEqual(
            len(provenance), criteria.get("sample_size"),
            "cohort_member_provenance length must equal "
            "sample_size (one entry per cohort row).",
        )
        modern_n = sum(1 for r in provenance if r.get("source") == "modern")
        legacy_n = sum(1 for r in provenance if r.get("source") == "legacy")
        self.assertEqual(modern_n, 40)
        self.assertGreater(legacy_n, 0)
        for entry in provenance[:5]:
            self.assertIn("source", entry)
            self.assertIn(entry["source"], ("modern", "legacy"))

    # ──────────────────────────────────────────────────────────
    # Test 4 — NB yearbuilt filter applied; A1 skips
    # ──────────────────────────────────────────────────────────

    def test_nb_yearbuilt_filter_applied(self):
        """Q3 lock — new_building cohort filters PLUTO
        yearbuilt >= 2000. major_alt_with_enlargement does NOT.

        Verified via paired NB / A1 cases against identical seeds:
        40 pre-2000 rows + 40 post-2000 rows. NB → 40 (filtered),
        A1 → 80 (unfiltered).
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()

        # Case A — NB: yearbuilt filter ACTIVE.
        socrata_nb = MockSocrataClient()
        # Active project PLUTO + classifier source.
        socrata_nb.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "2020",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        seed_dob_now_for_bin(
            socrata_nb, bin="3325703",
            work_type="General Construction",
            job_description="NEW BUILDING 5-STORY RESIDENTIAL 8 UNITS",
        )
        # 40 pre-2000 + 40 post-2000.
        make_modern_cohort_fixture(
            socrata_nb, project_type="new_building", n_records=40,
            bin_prefix="100200", bbl_prefix="100201",
            borough="BROOKLYN", building_class="C1",
            numfloors=5, yearbuilt=1985,
        )
        make_modern_cohort_fixture(
            socrata_nb, project_type="new_building", n_records=40,
            bin_prefix="100300", bbl_prefix="100301",
            borough="BROOKLYN", building_class="C1",
            numfloors=5, yearbuilt=2015,
        )
        socrata_nb.seed(DATASET_DOB_INSPECTIONS, [])
        socrata_nb.seed(DATASET_COMPLAINTS_311, [])
        project_nb = _menahan_like_project(
            _id="P_NB", dob_project_type="new_building",
            pluto_numfloors="5",  # align with seeded peers (default numfloors=4)
        )
        db_nb = _StubDb(projects=[dict(project_nb)])
        cache_nb = _run(compute_peer_stats_full(socrata_nb, project_nb, db=db_nb))
        segments_nb = (cache_nb.get("peer_criteria") or {}).get(
            "cohort_source_segments"
        ) or {}
        # 40 post-2000 rows pass; 40 pre-2000 drop.
        self.assertEqual(
            segments_nb.get("modern_count"), 40,
            f"NB yearbuilt filter not applied. Expected 40 (post-"
            f"2000 seeds only); got {segments_nb.get('modern_count')}. "
            f"Stage 3 Q3 lock: gate yearbuilt >= 2000 filter on "
            f"project_type == 'new_building'.",
        )

        # Case B — A1: yearbuilt filter SKIPPED.
        socrata_a1 = MockSocrataClient()
        socrata_a1.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "2",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        seed_dob_now_for_bin(
            socrata_a1, bin="3325703",
            work_type="General Construction",
            job_description="VERTICAL ENLARGEMENT EXISTING 2-STORY",
        )
        make_modern_cohort_fixture(
            socrata_a1, project_type="major_alt_with_enlargement",
            n_records=40, bin_prefix="100400", bbl_prefix="100401",
            borough="BROOKLYN", building_class="C1",
            numfloors=4, yearbuilt=1985,
        )
        make_modern_cohort_fixture(
            socrata_a1, project_type="major_alt_with_enlargement",
            n_records=40, bin_prefix="100500", bbl_prefix="100501",
            borough="BROOKLYN", building_class="C1",
            numfloors=4, yearbuilt=2015,
        )
        socrata_a1.seed(DATASET_DOB_INSPECTIONS, [])
        socrata_a1.seed(DATASET_COMPLAINTS_311, [])
        project_a1 = _menahan_like_project(
            _id="P_A1",
            dob_project_type="major_alt_with_enlargement",
            dob_extracted_scope={"story_count": 4},
        )
        db_a1 = _StubDb(projects=[dict(project_a1)])
        cache_a1 = _run(compute_peer_stats_full(socrata_a1, project_a1, db=db_a1))
        segments_a1 = (cache_a1.get("peer_criteria") or {}).get(
            "cohort_source_segments"
        ) or {}
        self.assertEqual(
            segments_a1.get("modern_count"), 80,
            f"A1 cohort must NOT filter yearbuilt. Expected 80 "
            f"(all seeds pass); got {segments_a1.get('modern_count')}. "
            f"Stage 3 Q3 lock: yearbuilt filter is NB-only.",
        )

    # ──────────────────────────────────────────────────────────
    # Test 5 — A1 target_state hybrid (parser primary, PLUTO fallback)
    # ──────────────────────────────────────────────────────────

    def test_a1_target_state_uses_parser_with_pluto_fallback(self):
        """Q5 hybrid lock — A1 cohort target_numfloors:
          5a: parser primary when dob_extracted_scope.story_count
              is confident → target = parser value, band ±25%,
              target_state.source = "parser"
          5b: PLUTO fallback when parser absent or unreliable →
              target = PLUTO numfloors, band ±50% (widened),
              target_state.source = "pluto_fallback",
              band_widened = True
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()

        # 5a — parser primary.
        socrata_a = MockSocrataClient()
        _seed_modern_cohort_world(
            socrata_a, n_modern=150, n_legacy=0,
            project_type="major_alt_with_enlargement",
            building_class="C1", numfloors=4,
        )
        project_a = _menahan_like_project(
            _id="P_5A",
            dob_project_type="major_alt_with_enlargement",
            dob_extracted_scope={"story_count": 4},  # parser confident
        )
        db_a = _StubDb(projects=[dict(project_a)])
        cache_a = _run(compute_peer_stats_full(socrata_a, project_a, db=db_a))
        target_a = (cache_a.get("peer_criteria") or {}).get("target_state") or {}
        self.assertEqual(target_a.get("numfloors"), 4)
        self.assertEqual(
            target_a.get("source"), "parser",
            f"Q5 lock — parser primary failed. Expected source="
            f"'parser', got {target_a.get('source')!r}. Stage 3: "
            f"check dob_extracted_scope.story_count first.",
        )

        # 5b — PLUTO fallback (parser absent).
        socrata_b = MockSocrataClient()
        _seed_modern_cohort_world(
            socrata_b, n_modern=150, n_legacy=0,
            project_type="major_alt_with_enlargement",
            building_class="C1", numfloors=2,
        )
        project_b = _menahan_like_project(
            _id="P_5B",
            dob_project_type="major_alt_with_enlargement",
            dob_extracted_scope={"story_count": None},  # parser empty
        )
        db_b = _StubDb(projects=[dict(project_b)])
        cache_b = _run(compute_peer_stats_full(socrata_b, project_b, db=db_b))
        target_b = (cache_b.get("peer_criteria") or {}).get("target_state") or {}
        # numfloors from PLUTO snapshot (2 pre-enlargement).
        self.assertEqual(target_b.get("numfloors"), 2)
        self.assertEqual(
            target_b.get("source"), "pluto_fallback",
            f"Q5 lock — PLUTO fallback failed. Expected source="
            f"'pluto_fallback'; got {target_b.get('source')!r}. "
            f"Stage 3: when dob_extracted_scope.story_count is "
            f"None/unconfident, fall back to PLUTO numfloors.",
        )
        self.assertTrue(
            target_b.get("band_widened"),
            "Q5 lock — band_widened=True when PLUTO fallback fires.",
        )

    # ──────────────────────────────────────────────────────────
    # Test 6 — _parse_pkdm_date format coverage
    # ──────────────────────────────────────────────────────────

    def test_pkdm_date_parser_handles_mdy_am_pm_format(self):
        """Risk 2 + §7.7 lock — _parse_pkdm_date helper parses
        pkdm-hqz6's MM/DD/YY HH:MM:SS AM/PM format with both
        single- and double-space variants per production data."""
        if not HAS_PARSE_PKDM_DATE:
            self.fail(
                "baselines._parse_pkdm_date not implemented. "
                "Stage 3 §7.2 + Risk 2: add helper near "
                "_parse_socrata_dt / _parse_socrata_yyyymmdd in "
                "baselines.py. Parse with regex tolerating \\s+ "
                "between date and time (§7.7). T1 Y2K cutoff: "
                "yy<50 → 20yy; yy>=50 → 19yy. Returns tz-aware UTC "
                "datetime or None on malformed input."
            )

        # Single-space variant.
        self.assertEqual(
            _parse_pkdm_date("09/02/25 1:24:22 PM"),
            datetime(2025, 9, 2, 13, 24, 22, tzinfo=timezone.utc),
        )
        # Double-space variant (real production sample from
        # Stage 1 Task 1: "09/02/25  1:24:22 PM" per curl probe).
        self.assertEqual(
            _parse_pkdm_date("09/02/25  1:24:22 PM"),
            datetime(2025, 9, 2, 13, 24, 22, tzinfo=timezone.utc),
            "§7.7 lock — _parse_pkdm_date must tolerate one OR "
            "more spaces between date and time. Production data "
            "ships double-space.",
        )
        # AM/PM handling.
        self.assertEqual(
            _parse_pkdm_date("01/15/24 11:30:00 AM"),
            datetime(2024, 1, 15, 11, 30, 0, tzinfo=timezone.utc),
        )
        # Midnight (12:00 AM = 00:00).
        self.assertEqual(
            _parse_pkdm_date("12/31/23 12:00:00 AM"),
            datetime(2023, 12, 31, 0, 0, 0, tzinfo=timezone.utc),
        )
        # Noon (12:00 PM = 12:00).
        self.assertEqual(
            _parse_pkdm_date("06/15/24 12:00:00 PM"),
            datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        # T1 Y2K cutoff: 49 → 2049, 50 → 1950.
        result_49 = _parse_pkdm_date("01/01/49 12:00:00 AM")
        self.assertEqual(result_49.year, 2049)
        result_50 = _parse_pkdm_date("01/01/50 12:00:00 AM")
        self.assertEqual(result_50.year, 1950)
        # Malformed → None.
        self.assertIsNone(_parse_pkdm_date("garbage"))
        self.assertIsNone(_parse_pkdm_date(""))
        self.assertIsNone(_parse_pkdm_date(None))

    # ──────────────────────────────────────────────────────────
    # Test 7 — case-insensitive job_type matching
    # ──────────────────────────────────────────────────────────

    def test_pkdm_job_type_case_insensitive_matching(self):
        """Risk 3 lock — Modern cohort query matches both
        'NEW BUILDING' and 'New Building' casings.

        Stage 1 Task 1 found pkdm-hqz6 enum carries BOTH casings:
        NEW BUILDING (26,762) + New Building (4,593). Cohort
        query must produce the union of both.
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()

        socrata = MockSocrataClient()
        # Active project (NB).
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "2020",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        seed_dob_now_for_bin(
            socrata, bin="3325703",
            work_type="General Construction",
            job_description="NEW BUILDING 5-STORY RESIDENTIAL",
        )
        # 25 with uppercase, 25 with mixed case.
        make_modern_cohort_fixture(
            socrata, project_type="new_building", n_records=25,
            bin_prefix="200200", bbl_prefix="200201",
            borough="BROOKLYN", building_class="C1",
            numfloors=5, yearbuilt=2020,
        )
        make_modern_cohort_fixture(
            socrata, project_type="new_building", n_records=25,
            bin_prefix="200300", bbl_prefix="200301",
            borough="BROOKLYN", building_class="C1",
            numfloors=5, yearbuilt=2020,
            job_type_override="New Building",  # mixed-case variant
        )
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

        project = _menahan_like_project(
            _id="P_CASE", dob_project_type="new_building",
            pluto_numfloors="5",  # align with seeded peers
        )
        db = _StubDb(projects=[dict(project)])
        cache = _run(compute_peer_stats_full(socrata, project, db=db))
        segments = (cache.get("peer_criteria") or {}).get(
            "cohort_source_segments"
        ) or {}
        self.assertEqual(
            segments.get("modern_count"), 50,
            f"Modern cohort query MUST match both 'NEW BUILDING' "
            f"and 'New Building' casings (Risk 3 / pkdm-hqz6 enum "
            f"inconsistency). Got {segments.get('modern_count')}. "
            f"Stage 3: build WHERE as ``job_type IN ('NEW BUILDING', "
            f"'New Building')`` for NB project type. "
            f"COHORT_CONFIG[new_building].modern_path.pkdm_job_types "
            f"= ('NEW BUILDING', 'New Building').",
        )

    # ──────────────────────────────────────────────────────────
    # Test 8 — Menahan canary (T8 lock)
    # ──────────────────────────────────────────────────────────

    def test_menahan_real_data_modern_cohort_populates(self):
        """T8 + T3 lock — Real Menahan DOB NOW data + 120 A1
        Modern cohort peers. Pipeline produces:
          • classifier picks major_alt_with_enlargement
          • Modern cohort populated
          • target_state.source = "parser", numfloors = 4
            (Menahan "PROPOSED 4-STORY+CELLAR+MEZZ" description)
          • status = "ready" (no timeout, no zero-marker)
          • schema_version = "pr14e"
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()
        socrata = MockSocrataClient()
        # Menahan-shaped active project PLUTO (pre-enlargement state).
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "2",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        # Real 5 Menahan DOB NOW rows from operator's curl probe.
        menahan_meta = seed_menahan_realistic_dob_now(socrata)
        # 120 A1 Modern cohort peers in Brooklyn.
        make_modern_cohort_fixture(
            socrata, project_type="major_alt_with_enlargement",
            n_records=120, bin_prefix="3033041",
            bbl_prefix="3033042", borough="BROOKLYN",
            building_class="C1", numfloors=4, yearbuilt=1925,
        )
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

        project = {
            "_id":     "P_MENAHAN_PR14E_DEDICATED",
            "name":    "9 Menahan Street",
            "nyc_bin": menahan_meta["bin"],
            "bbl":     "3033040024",
            "borough": "BROOKLYN",
            # No dob_project_type — classifier MUST fire.
        }
        db = _StubDb(projects=[dict(project)])
        cache = _run(compute_peer_stats_full(socrata, project, db=db))
        criteria = cache.get("peer_criteria") or {}

        # 1. Classifier output.
        self.assertEqual(
            criteria.get("dob_project_type"),
            "major_alt_with_enlargement",
            f"Classifier regression. Got "
            f"{criteria.get('dob_project_type')!r}. Expected "
            f"major_alt_with_enlargement from Menahan B00736930-I1 "
            f"General Construction (real description with VERTICAL "
            f"AND HORIZONTAL ENLARGEMENT).",
        )
        # 2. PR #14E schema bump applied.
        self.assertEqual(
            criteria.get("schema_version"), "pr14e",
        )
        # 3. Modern cohort populated (Q2 primary).
        segments = criteria.get("cohort_source_segments") or {}
        self.assertGreater(
            segments.get("modern_count", 0), 0,
            f"Modern cohort empty for Menahan. Got modern_count="
            f"{segments.get('modern_count')}. Stage 3: thread "
            f"_fetch_modern_cohort into compute_cohort_for_project.",
        )
        # 4. target_state from parser (Q5 hybrid).
        target = criteria.get("target_state") or {}
        self.assertEqual(target.get("numfloors"), 4)
        self.assertEqual(target.get("source"), "parser")
        # PR #14F: parser path uses ±25% band, NOT the widened ±50%
        # PLUTO fallback band. For numfloors=4, band = [3, 5].
        self.assertEqual(
            list(target.get("numfloors_band") or []), [3, 5],
            f"PR #14F regression — parser-derived numfloors_band must "
            f"be ±25% = [3, 5] for numfloors=4. Got "
            f"{target.get('numfloors_band')!r}. If band is [2, 6] the "
            f"helper fell through to pluto_fallback (±50%) — see "
            f"Step 2b _derive_target_state_for_project plumbing.",
        )
        self.assertFalse(
            target.get("band_widened"),
            "PR #14F: parser path must NOT widen band; band_widened=False.",
        )
        # 5. Pipeline reached ready (not timeout / zero-marker).
        self.assertEqual(
            cache.get("status"), "ready",
            f"Pipeline produced non-ready cache "
            f"(status={cache.get('status')!r}). Pre-PR-14E "
            f"Menahan timed out + had latent BIN→BBL bridge bug; "
            f"PR #14E fixes both via Modern primary (pkdm-hqz6 "
            f"ships bbl inline, no BIN→BBL bridge needed).",
        )

    # ──────────────────────────────────────────────────────────
    # PR #14F regression tests
    # ──────────────────────────────────────────────────────────

    def test_modern_cohort_applies_date_filter_client_side(self):
        """PR #14F (Stage 10 lex-comparison bugfix) — Modern path
        does NOT push a c_of_o_issuance_date threshold into SoQL
        WHERE (pkdm-hqz6 stores dates as MM/DD/YY text; lex compare
        against MM/DD/YY threshold lets older years through, e.g.
        '06/23/21' > '05/15/23' as strings). Window is enforced
        client-side via _parse_pkdm_date.

        Seeds 5 in-window + 5 out-of-window pkdm-hqz6 rows;
        confirms cohort_source_segments.modern_count == 5 and the
        SoQL WHERE clause does NOT carry the date filter.
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        from _pr14b_fixtures import _pkdm_co_issuance_date_mdy

        socrata = MockSocrataClient()
        fixed_now = _dt(2026, 5, 15, tzinfo=_tz.utc)
        # Active project + classifier seed.
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "2020",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        seed_dob_now_for_bin(
            socrata, bin="3325703",
            work_type="General Construction",
            job_description="NEW BUILDING 5-STORY RESIDENTIAL",
        )
        # 5 in-window peers (months_ago=12, well within 36mo).
        make_modern_cohort_fixture(
            socrata, project_type="new_building", n_records=5,
            bin_prefix="900100", bbl_prefix="900101",
            borough="BROOKLYN", building_class="C1",
            numfloors=5, yearbuilt=2020,
            months_ago=12, now=fixed_now,
        )
        # 5 out-of-window peers (months_ago=60 = 5 years back).
        make_modern_cohort_fixture(
            socrata, project_type="new_building", n_records=5,
            bin_prefix="900200", bbl_prefix="900201",
            borough="BROOKLYN", building_class="C1",
            numfloors=5, yearbuilt=2020,
            months_ago=60, now=fixed_now,
        )
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

        project = _menahan_like_project(
            _id="P_DATE_FILTER_MODERN",
            dob_project_type="new_building",
            pluto_numfloors="5",
        )
        db = _StubDb(projects=[dict(project)])
        cache = _run(compute_peer_stats_full(
            socrata, project, db=db, now=fixed_now,
        ))
        segments = (cache.get("peer_criteria") or {}).get(
            "cohort_source_segments"
        ) or {}
        self.assertEqual(
            segments.get("modern_count"), 5,
            f"PR #14F: Modern cohort must filter date client-side. "
            f"Expected 5 in-window peers; got "
            f"{segments.get('modern_count')}. If 10: the 36mo "
            f"window wasn't applied. If 0: the un-filtered pull "
            f"didn't work.",
        )
        # Verify the SoQL WHERE clauses to pkdm-hqz6 lack date filter.
        pkdm_calls = [
            c for c in socrata.calls if c[0] == DATASET_DOB_C_OF_O
        ]
        self.assertGreater(len(pkdm_calls), 0)
        for ds, kw in pkdm_calls:
            where = kw.get("where") or ""
            self.assertNotIn(
                "c_of_o_issuance_date", where,
                f"PR #14F lock — c_of_o_issuance_date must NOT appear "
                f"in pkdm-hqz6 SoQL WHERE (text-typed column lex "
                f"comparison would let 2021 rows pass a 2023 "
                f"threshold). Got WHERE: {where!r}",
            )

    def test_legacy_cohort_applies_date_filter_client_side(self):
        """PR #14F (Stage 10 lex-comparison bugfix) — Legacy BIS
        path does NOT push a pre__filing_date threshold into SoQL
        WHERE (BIS stores pre__filing_date as MM/DD/YYYY text;
        '06/30/2018' < '2018-06-30' lex because '0' < '2', so an
        ISO threshold silently fails every row). Window enforced
        client-side via _parse_bis_mdy_date.

        Seeds 5 in-window + 5 out-of-window BIS rows; confirms
        only in-window rows pass through.
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()
        from lib.statistical_engine.baselines import _fetch_legacy_cohort

        socrata = MockSocrataClient()
        # 5 in-window rows (MM/DD/YYYY format, 2018-2020 inside
        # Golden Era 2016-01-01 .. 2021-06-30).
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=5,
            bin_prefix="800100", borough="BROOKLYN",
            building_class="C1", bis_job_type="NB",
            pre__filing_date="06/30/2018",
        )
        # 5 out-of-window rows (pre-2016 OR post-2021).
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=3,
            bin_prefix="800200", borough="BROOKLYN",
            building_class="C1", bis_job_type="NB",
            pre__filing_date="01/01/2014",  # pre-Golden-Era
        )
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=2,
            bin_prefix="800300", borough="BROOKLYN",
            building_class="C1", bis_job_type="NB",
            pre__filing_date="01/01/2025",  # post-Golden-Era
        )
        project = {
            "_id": "P_DATE_FILTER_LEGACY", "nyc_bin": "3325703",
            "bbl": "3033040024", "borough": "BROOKLYN",
            "dob_project_type": "new_building",
            "pluto_snapshot": {"bldgclass": "C1", "numfloors": 5},
        }
        cohort = _run(_fetch_legacy_cohort(socrata, project))
        self.assertEqual(
            len(cohort), 5,
            f"PR #14F: Legacy cohort must filter Golden Era window "
            f"client-side. Expected 5 in-window rows; got "
            f"{len(cohort)}. If 10: window not applied. If 0: "
            f"client-side filter is broken — verify _parse_bis_mdy_date "
            f"handles MM/DD/YYYY format.",
        )
        # Verify WHERE lacks pre__filing_date threshold.
        bis_calls = [
            c for c in socrata.calls if c[0] == DATASET_BIS_JOB_FILINGS
        ]
        self.assertGreater(len(bis_calls), 0)
        for ds, kw in bis_calls:
            where = kw.get("where") or ""
            self.assertNotIn(
                "pre__filing_date", where,
                f"PR #14F lock — pre__filing_date must NOT appear in "
                f"BIS SoQL WHERE. Got WHERE: {where!r}",
            )

    def test_parse_bis_mdy_date_handles_mdy_yyyy_format(self):
        """PR #14F — _parse_bis_mdy_date unit test for the BIS
        pre__filing_date format (MM/DD/YYYY, optional trailing time).
        """
        try:
            from lib.statistical_engine.baselines import _parse_bis_mdy_date
        except ImportError:
            self.fail(
                "_parse_bis_mdy_date not implemented. PR #14F: add "
                "helper near _parse_pkdm_date in baselines.py."
            )
        from datetime import datetime as _dt, timezone as _tz
        # Basic MM/DD/YYYY.
        self.assertEqual(
            _parse_bis_mdy_date("06/30/2018"),
            _dt(2018, 6, 30, tzinfo=_tz.utc),
        )
        self.assertEqual(
            _parse_bis_mdy_date("01/01/2016"),
            _dt(2016, 1, 1, tzinfo=_tz.utc),
        )
        # Trailing time (space separator) — discarded.
        self.assertEqual(
            _parse_bis_mdy_date("12/31/2020 11:59:59 PM"),
            _dt(2020, 12, 31, tzinfo=_tz.utc),
        )
        # Trailing time (T separator) — discarded.
        self.assertEqual(
            _parse_bis_mdy_date("06/30/2018T00:00:00.000"),
            _dt(2018, 6, 30, tzinfo=_tz.utc),
        )
        # Malformed / out-of-range → None.
        self.assertIsNone(_parse_bis_mdy_date("garbage"))
        self.assertIsNone(_parse_bis_mdy_date(""))
        self.assertIsNone(_parse_bis_mdy_date(None))
        self.assertIsNone(_parse_bis_mdy_date("13/01/2020"))  # bad month
        # Pass-through for already-parsed datetimes.
        dt = _dt(2020, 6, 15, tzinfo=_tz.utc)
        self.assertEqual(_parse_bis_mdy_date(dt), dt)

    def test_target_state_reads_persisted_dob_extracted_scope(self):
        """PR #14F regression — when ``dob_project_type`` is already
        set on the in-memory project dict (idempotent classifier
        skip), ``compute_peer_stats_full`` must still sync
        ``dob_extracted_scope`` from db so the Q5 parser primary
        path fires. Stage 10 mongosh on Menahan showed this was
        broken: parser had extracted story_count=4 (saved in db)
        yet target_state.source == "pluto_fallback".
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()
        socrata = MockSocrataClient()
        # Modern peers at numfloors=4 (parser-extracted target).
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "2",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        seed_dob_now_for_bin(
            socrata, bin="3325703",
            work_type="General Construction",
            job_description=(
                "PROPOSED ALTERATION TYPE 1 TO EXISTING 2 STORY + "
                "CELLAR BUILDING. PROPOSED 4-STORY+CELLAR+MEZZ."
            ),
        )
        make_modern_cohort_fixture(
            socrata, project_type="major_alt_with_enlargement",
            n_records=120, bin_prefix="700100", bbl_prefix="700101",
            borough="BROOKLYN", building_class="C1",
            numfloors=4, yearbuilt=1925,
        )
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

        # Project in-memory has dob_project_type set BUT NO
        # dob_extracted_scope in the dict — mirrors the production
        # state where prior classification persisted to db but the
        # in-memory project doc was reconstructed without it.
        project = _menahan_like_project(
            _id="P_DOB_SCOPE_SYNC",
            dob_project_type="major_alt_with_enlargement",
        )
        # Persist dob_extracted_scope to the stub db (simulates
        # a previously-run classifier). project dict in-memory
        # deliberately lacks the key.
        db = _StubDb(projects=[{
            "_id": "P_DOB_SCOPE_SYNC",
            "dob_extracted_scope": {"story_count": 4},
        }])

        cache = _run(compute_peer_stats_full(socrata, project, db=db))
        criteria = cache.get("peer_criteria") or {}
        target = criteria.get("target_state") or {}

        self.assertEqual(
            target.get("source"), "parser",
            f"PR #14F regression — target_state.source must be "
            f"'parser' when dob_extracted_scope.story_count is "
            f"persisted in db, even if in-memory project dict "
            f"lacked it on entry. Got: {target.get('source')!r}. "
            f"Stage 10 production showed 'pluto_fallback' here. "
            f"Fix: compute_peer_stats_full Step 2b re-reads from "
            f"db when in-memory dict lacks dob_extracted_scope.",
        )
        self.assertEqual(target.get("numfloors"), 4)
        self.assertEqual(
            list(target.get("numfloors_band") or []), [3, 5],
            "PR #14F: parser path uses ±25% band [3,5], not "
            "widened [2,6].",
        )
        self.assertFalse(target.get("band_widened"))

    # ──────────────────────────────────────────────────────────
    # PR #14G regression tests — PLUTO bbl format normalization
    # ──────────────────────────────────────────────────────────

    def test_normalize_pluto_bbl_handles_production_format(self):
        """PR #14G unit test — _normalize_pluto_bbl strips the
        Socrata numeric-float ``.00000000`` suffix from PLUTO bbl
        values so cohort joins match pkdm-hqz6 / BIS plain
        10-digit format.
        """
        try:
            from lib.statistical_engine.baselines import _normalize_pluto_bbl
        except ImportError:
            self.fail(
                "_normalize_pluto_bbl not implemented. PR #14G: add "
                "helper near _parse_bis_mdy_date in baselines.py."
            )
        # Production PLUTO format → strip suffix.
        self.assertEqual(
            _normalize_pluto_bbl("3012440018.00000000"), "3012440018",
        )
        # Plain 10-digit → pass-through.
        self.assertEqual(
            _normalize_pluto_bbl("3012440018"), "3012440018",
        )
        # Float input → coerce via str(), strip suffix.
        self.assertEqual(
            _normalize_pluto_bbl(3012440018.0), "3012440018",
        )
        # Defensive: non-zero fractional still strips (would be
        # malformed bbl in practice but helper is permissive).
        self.assertEqual(
            _normalize_pluto_bbl("3012440018.5"), "3012440018",
        )
        # None / empty → None.
        self.assertIsNone(_normalize_pluto_bbl(None))
        self.assertIsNone(_normalize_pluto_bbl(""))
        self.assertIsNone(_normalize_pluto_bbl("   "))

    def test_pluto_bbl_normalization_matches_pkdm_format(self):
        """PR #14G regression — PLUTO returns bbl with .00000000
        suffix; cohort join must normalize so dict-keyed match
        works against pkdm-hqz6 / BIS plain format. Pre-fix:
        Modern cohort returned 0 rows because pluto_by_bbl was
        keyed on un-normalized "3012440018.00000000" but the
        lookup used the plain pkdm bbl "3012440018".

        Test seeds 5 pkdm-hqz6 rows + 5 PLUTO rows with the
        production ``.00000000`` suffix. Modern cohort must
        produce 5 cohort members; if normalization is dropped,
        cohort_source_segments.modern_count == 0.
        """
        self._require_db_kwarg()
        self._require_pr14e_schema()

        socrata = MockSocrataClient()
        # Active project's PLUTO snapshot — production format.
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024.00000000",  # production suffix
            "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8",
            "numfloors": "4.0000000",  # production numeric-text format
            "bldgarea": "8038", "lotarea": "2500",
        }])
        seed_dob_now_for_bin(
            socrata, bin="3325703",
            work_type="General Construction",
            job_description=(
                "PROPOSED ALTERATION TYPE 1. PROPOSED 4-STORY+CELLAR."
            ),
        )
        # 5 pkdm-hqz6 rows (plain bbl) + matching PLUTO peer rows
        # (with .00000000 suffix per make_modern_cohort_fixture
        # production-format seed).
        make_modern_cohort_fixture(
            socrata, project_type="major_alt_with_enlargement",
            n_records=5, bin_prefix="600100", bbl_prefix="600101",
            borough="BROOKLYN", building_class="C1",
            numfloors=4, yearbuilt=1925,
        )
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

        project = _menahan_like_project(
            _id="P_PLUTO_BBL_FMT",
            dob_project_type="major_alt_with_enlargement",
            dob_extracted_scope={"story_count": 4},
            pluto_numfloors="4",
        )
        db = _StubDb(projects=[dict(project)])
        cache = _run(compute_peer_stats_full(socrata, project, db=db))
        segments = (cache.get("peer_criteria") or {}).get(
            "cohort_source_segments"
        ) or {}
        self.assertEqual(
            segments.get("modern_count"), 5,
            f"PR #14G regression — PLUTO bbl .00000000 suffix must "
            f"be normalized so cohort join matches. Expected 5 "
            f"cohort rows; got {segments.get('modern_count')}. "
            f"If 0: _normalize_pluto_bbl was dropped or not applied "
            f"at the pluto_by_bbl dict-keying site in "
            f"_fetch_modern_cohort Step 4.",
        )
        # Confirm the cohort_member_provenance carries plain bbls
        # (not suffixed) — downstream event queries depend on this.
        provenance = (cache.get("peer_criteria") or {}).get(
            "cohort_member_provenance"
        ) or []
        for entry in provenance:
            bbl = entry.get("bbl")
            if bbl:
                self.assertNotIn(
                    ".", bbl,
                    f"cohort_member_provenance entry has bbl with "
                    f"'.' suffix: {bbl!r}. Normalization must "
                    f"happen before provenance is built.",
                )


if __name__ == "__main__":
    unittest.main()
