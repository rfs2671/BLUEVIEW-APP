"""PR #14C Stage 2.B — wiring integration tests.

PR #14B (87cebf9) shipped cohort-aware peer comparison machinery but
never wired it into the runtime path. Production validation found:

  • Menahan refresh produces a score identical to pre-PR-14B baseline
  • peer_set tier = "borough_class_use" (V2.3 OLD ladder)
  • peer_set carries V2.3 keys (project_class, use_type) not PR #14B
    keys (dob_project_type, geography_tier_used, low_confidence_flag)
  • inspections_lifecycle_normalized_percentile = null,
    complaints_lifecycle_normalized_percentile = null
  • Project doc lacks dob_project_type, dob_job_snapshot
  • compute_cohort_for_project: ZERO call sites
  • maybe_classify_project_dob_type: ZERO call sites

PR #14C wires the cohort logic into compute_peer_stats_full so:

  1. Every cache write goes through the cohort path (UI button,
     project creation, scheduled refresh, retry, orphan recovery).
  2. Stale V2.3 caches are auto-invalidated via a schema_version
     check in compare_project_to_peers.
  3. The Latent Bug 1 fix (PR #14B Q6) ensures refreshed PLUTO
     snapshots reach db.projects.

All 12 tests in this file are RED at Stage 2.B. Stage 3 lands the
wiring + retires the V2.3 ladder. Failure messages include exact
file:line Stage 3 implementation hints.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
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


# ─── Production symbol imports (eager — these all exist post-PR-14B) ─

from lib.statistical_engine import baselines as bl  # noqa: E402
from lib.statistical_engine.baselines import (  # noqa: E402
    compute_peer_stats_full,
    compare_project_to_peers,
    _v22_shape_from_cache,
    _persist_cache,
)
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_PLUTO,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_VIOLATIONS,
    DATASET_COMPLAINTS_311,
)


# ─── Lazy imports for PR #14C symbols (don't exist until Stage 3) ────

try:
    from lib.statistical_engine.baselines import PR14C_SCHEMA_VERSION  # type: ignore
    HAS_PR14C_SCHEMA_VERSION = True
except ImportError:
    PR14C_SCHEMA_VERSION = None  # type: ignore
    HAS_PR14C_SCHEMA_VERSION = False


try:
    from lib.statistical_engine.baselines import (  # type: ignore # noqa: E402
        _resolve_bbls_for_cohort_bins,
    )
    HAS_RESOLVE_BBLS_HELPER = True
except ImportError:
    _resolve_bbls_for_cohort_bins = None  # type: ignore
    HAS_RESOLVE_BBLS_HELPER = False


# ─── Test infrastructure imports ──────────────────────────────────

from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    DATASET_BIS_JOB_FILINGS,
    DATASET_C_OF_O_LEGACY,
    DATASET_DOB_PERMITS,
    make_cohort_fixture,
    seed_bis_for_bin,
    seed_c_of_o_for_job,
    seed_dob_now_for_bin,
)


# ──────────────────────────────────────────────────────────────────
# Signature check helpers
#
# Stage 2.A §6.1 lock: PR #14C adds ``db`` as a required keyword arg
# to ``compute_peer_stats_full``. The lazy check below lets each test
# emit a clean Stage 3 hint instead of a raw TypeError when the
# signature hasn't been updated yet.
# ──────────────────────────────────────────────────────────────────

_PEER_STATS_SIG = inspect.signature(compute_peer_stats_full)
HAS_DB_KWARG = "db" in _PEER_STATS_SIG.parameters


# ──────────────────────────────────────────────────────────────────
# Module-level helpers (kept inside this test file per Stage 2.A —
# they're PR #14C-specific; _pr14b_fixtures stays canonical for
# PR #14B shape primitives)
# ──────────────────────────────────────────────────────────────────


def _menahan_like_project(**overrides) -> Dict[str, Any]:
    """Canonical project doc shaped like the production Menahan
    record at the moment PR #14B's validation surfaced the gap:

      • Has nyc_bin + bbl + borough (set during onboarding)
      • Has NO dob_project_type (classifier never fired)
      • Has NO pluto_snapshot OR a stub one with only ``bldgclass``
        (production state — PLUTO SELECT extension never refreshed)
      • Has NO peer_stats_cache (cleared by Stage 6 deploy nuke)
    """
    base = {
        "_id": "P_MENAHAN",
        "name": "9 Menahan Street",
        "nyc_bin": "3325703",
        "bbl": "3033040024",
        "borough": "BROOKLYN",
        "track_dob_status": True,
    }
    base.update(overrides)
    return base


def _seed_cohort_world(socrata: MockSocrataClient) -> Dict[str, Any]:
    """Seed all 6 datasets so compute_peer_stats_full can walk
    the full pipeline end-to-end.

    Seeded:
      • DATASET_PLUTO: active project's row (14-field PR #14B SELECT)
        AND cohort BIN→BBL rows (per Q2/T2 PLUTO join)
      • DATASET_DOB_PERMITS: a row for the active project's BIN
        that drives the classifier to "new_building"
      • DATASET_BIS_JOB_FILINGS: 150 NB cohort rows
      • DATASET_C_OF_O_LEGACY: matching Final C of O rows
      • DATASET_DOB_INSPECTIONS / DATASET_COMPLAINTS_311: empty
        (tests that need event counts seed them explicitly)
    """
    # 1. Active project's PLUTO row (all 14 PR #14B fields).
    socrata.seed(DATASET_PLUTO, [{
        "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
        "landuse": "01", "block": "3040", "lot": "24",
        "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
        "unitsres": "8", "unitstotal": "8", "numfloors": "5",
        "bldgarea": "8038", "lotarea": "2500",
    }])

    # 2. DOB NOW row for classification → new_building.
    seed_dob_now_for_bin(
        socrata, bin="3325703",
        work_type="General Construction",
        filing_reason="Initial Permit",
        job_description="NEW BUILDING 5-STORY RESIDENTIAL 8 UNITS",
    )

    # 3. 150-record cohort (BIS + C of O Final).
    make_cohort_fixture(
        socrata, project_type="new_building", n_records=150,
        bin_prefix="3033040", job_number_prefix="32100",
        borough="BROOKLYN", building_class="C1", bis_job_type="NB",
        story_count=5, dwelling_units=8, completed=True,
    )

    # 4. PLUTO rows for cohort BINs so the Stage 3 PLUTO BIN→BBL
    #    join resolves them. Per Q2/T2, the join is a single
    #    batched ``bin IN (chunk)`` query that the new
    #    ``_resolve_bbls_for_cohort_bins`` helper will issue.
    pluto_cohort_rows = [
        {
            "bbl": f"3033041{i:04d}",
            "bin": f"3033040{i:04d}",
            "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3041", "lot": f"{i:04d}",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1990",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8000", "lotarea": "2500",
        }
        for i in range(150)
    ]
    socrata.seed(DATASET_PLUTO, pluto_cohort_rows)

    # 5. Empty event datasets — tests override per-case.
    socrata.seed(DATASET_DOB_INSPECTIONS, [])
    socrata.seed(DATASET_COMPLAINTS_311, [])

    return {
        "cohort_size": 150,
        "cohort_bins": [f"3033040{i:04d}" for i in range(150)],
        "cohort_bbls": [f"3033041{i:04d}" for i in range(150)],
    }


def _minimal_cohort_result() -> Dict[str, Any]:
    """Synthetic return value for a mocked compute_cohort_for_project.

    Matches the shape Stage 2.A §1.1 documented: PR #14B's
    compute_cohort_for_project output as defined in baselines.py:2148.
    """
    return {
        "tier_used":                   "zip_bldgclass_type",
        "fallback_level":              1,
        "sample_size":                 150,
        "low_confidence_flag":         False,
        "window_months":               36,
        "completion_method":           "c_of_o_final",
        "cohort_filter_spec": {
            "dob_project_type":  "new_building",
            "building_class":    "C1",
            "bis_job_types":     ["NB"],
            "story_count_band":  [4, 6],
            "dwelling_units_band": [6, 10],
        },
        "cohort_job_numbers":          [f"320100{i:04d}" for i in range(150)],
        "cohort_median_duration_days": 600.0,
        "lifecycle_skip_reason":       None,
        "active_project": {
            "completion_pct":      0.4,
            "observed_milestones": ["structural"],
        },
    }


def _pr14b_cache_doc(**overrides) -> Dict[str, Any]:
    """Synthetic PR #14B-shape cache doc for cache-hit tests.

    Carries ``schema_version="pr14c"`` so Q4 Option B's schema
    check serves the cache (test 12). For invalidation tests
    (test 11), use ``_v23_cache_doc()`` instead.
    """
    now = datetime.now(timezone.utc)
    peer_criteria = {
        "schema_version":              "pr14c",
        "dob_project_type":            "new_building",
        "geography_tier_used":         "zip_bldgclass_type",
        "low_confidence_flag":         False,
        "borough":                     "BROOKLYN",
        "sample_size":                 149,
        "fallback_level":              1,
        "window_months":               36,
        "completion_method":           "c_of_o_final",
        "cohort_median_duration_days": 600.0,
        "cohort_filter_spec": {
            "dob_project_type": "new_building",
            "building_class":   "C1",
        },
        "active_project": {
            "completion_pct":      0.4,
            "observed_milestones": ["structural"],
        },
    }
    if "peer_criteria" in overrides:
        peer_criteria.update(overrides.pop("peer_criteria"))

    base = {
        "status":            "ready",
        "computed_at":       now - timedelta(days=1),
        "last_refreshed_at": now - timedelta(days=1),
        "peer_criteria":     peer_criteria,
        "events_window_start": now - timedelta(days=730),
        "events_window_end":   now - timedelta(days=1),
        "inspections": {
            "available": True, "n": 149, "median": 5.0,
            "p75": 8.0, "p90": 12.0, "p95": 15.0, "max": 20.0,
            "mean": 6.5,
            "project_count": 12, "percentile_rank": 63.0,
            "lifecycle_normalized_percentile": None,
        },
        "complaints": {
            "available": True, "n": 149, "median": 2.0,
            "p75": 4.0, "p90": 7.0, "p95": 9.0, "max": 12.0,
            "mean": 2.8,
            "project_count": 5, "percentile_rank": 42.0,
            "lifecycle_normalized_percentile": None,
        },
        "violations": {
            "available": False,
            "unavailable_reason":
                "bbl_keyed_peer_set_incompatible_with_bin_keyed_dataset",
            "peer_data_dropped_in_pr": "v2.3-schema-corrections-hotfix",
        },
    }
    base.update(overrides)
    return base


def _v23_cache_doc(**overrides) -> Dict[str, Any]:
    """Synthetic V2.3-shape cache doc (NO schema_version) for
    Test 11 (invalidation when stale).
    """
    now = datetime.now(timezone.utc)
    peer_criteria = {
        # NO schema_version → must invalidate per Q4 Option B + T4
        "borough":        "BROOKLYN",
        "project_class":  "O4",          # V2.3 vocabulary
        "use_type":       "office",       # V2.3 vocabulary
        "tier":           "borough_class_use",  # V2.3 tier names
        "sample_size":    24,
        "fallback_level": 1,
    }
    if "peer_criteria" in overrides:
        peer_criteria.update(overrides.pop("peer_criteria"))

    base = {
        "status":            "ready",
        "computed_at":       now - timedelta(days=1),
        "last_refreshed_at": now - timedelta(days=1),
        "peer_criteria":     peer_criteria,
        "inspections": {
            "available": True, "n": 24, "median": 3.0,
            "p75": 5.0, "p90": 7.0, "project_count": 5,
            "percentile_rank": 50.0,
        },
        "complaints": {
            "available": True, "n": 24, "median": 1.0,
            "p75": 2.0, "p90": 4.0, "project_count": 2,
            "percentile_rank": 40.0,
        },
        "violations": {
            "available": False,
            "unavailable_reason":
                "bbl_keyed_peer_set_incompatible_with_bin_keyed_dataset",
        },
    }
    base.update(overrides)
    return base


class _StubProjects:
    """Reusable projects-collection stub.

    Mirrors _StubProjectsColl in test_v2_3_baselines.py (we re-implement
    locally to keep PR #14C's test file self-contained for the diff
    review at Stage 4).
    """

    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.update_one_calls: List[Dict[str, Any]] = []

    async def update_one(self, filter_, update, upsert=False):
        self.update_one_calls.append({
            "filter": filter_, "update": update,
        })
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


# ──────────────────────────────────────────────────────────────────
# Test class
# ──────────────────────────────────────────────────────────────────


class TestPr14cWiring(unittest.TestCase):
    """PR #14C — verify cohort wiring into compute_peer_stats_full.

    Each test is RED at Stage 2.B. Stage 3 lands the wiring;
    these turn GREEN. Failure messages embed Stage 3 implementation
    hints (target file:line, missing call sites).
    """

    # ── Guards ────────────────────────────────────────────────

    def _require_db_kwarg(self):
        if not HAS_DB_KWARG:
            self.fail(
                "compute_peer_stats_full does not accept `db` kwarg. "
                "Stage 3 §6.1: add ``db`` as required kwarg and "
                "update 5 call sites: baselines.py:993, "
                "baselines.py:1546, prewarm.py:260, "
                "refresh_cron.py:320, refresh_cron.py:326."
            )

    def _require_schema_version_constant(self):
        if not HAS_PR14C_SCHEMA_VERSION:
            self.fail(
                "baselines.PR14C_SCHEMA_VERSION constant not "
                "defined. Stage 3 §6.3: add "
                "``PR14C_SCHEMA_VERSION = \"pr14c\"`` to "
                "baselines.py near the existing PEER_STATS_* "
                "constants."
            )

    # ──────────────────────────────────────────────────────────
    # Test 1 — compute_cohort_for_project invocation
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_calls_compute_cohort_for_project(self):
        """compute_peer_stats_full MUST call compute_cohort_for_project.

        PR #14B shipped compute_cohort_for_project but no caller
        invokes it. Stage 3 wires the call inside
        compute_peer_stats_full BEFORE the event-count queries,
        replacing the V2.3 peer_bbls() call at baselines.py:780.
        """
        self._require_db_kwarg()
        socrata = MockSocrataClient()
        _seed_cohort_world(socrata)
        project = _menahan_like_project(dob_project_type="new_building")
        db = _StubDb(projects=[dict(project)])

        with patch(
            "lib.statistical_engine.baselines.compute_cohort_for_project",
            new=AsyncMock(return_value=_minimal_cohort_result()),
        ) as cohort_spy:
            _run(compute_peer_stats_full(socrata, project, db=db))

        self.assertEqual(
            cohort_spy.call_count, 1,
            f"compute_cohort_for_project called "
            f"{cohort_spy.call_count} times; expected 1. "
            "Stage 3: replace peer_bbls() call at baselines.py:780 "
            "with compute_cohort_for_project(socrata, project). "
            "ZERO call sites today (Stage 1 investigation finding)."
        )

    # ──────────────────────────────────────────────────────────
    # Test 2 — peer_criteria shape with PR #14B keys
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_writes_pr14b_peer_criteria_shape(self):
        """Cache.peer_criteria MUST carry PR #14B keys and MUST NOT
        carry V2.3 keys.

        Production Menahan currently has V2.3 keys (project_class,
        use_type) leaking through because _assemble_cache writes
        the V2.3 shape. Stage 3 updates _assemble_cache to emit
        the new vocabulary.
        """
        self._require_db_kwarg()
        self._require_schema_version_constant()
        socrata = MockSocrataClient()
        _seed_cohort_world(socrata)
        project = _menahan_like_project()
        db = _StubDb(projects=[dict(project)])

        cache = _run(compute_peer_stats_full(socrata, project, db=db))

        criteria = cache.get("peer_criteria") or {}
        # PR #14B keys must be present.
        for required_key in (
            "dob_project_type", "geography_tier_used",
            "low_confidence_flag", "schema_version",
            "cohort_median_duration_days", "window_months",
            "completion_method", "cohort_filter_spec",
            "active_project",
        ):
            self.assertIn(
                required_key, criteria,
                f"peer_criteria missing PR #14B key {required_key!r}. "
                f"Stage 3: update _assemble_cache "
                f"(baselines.py:840-944) to emit the new vocabulary. "
                f"Got keys: {sorted(criteria.keys())!r}"
            )
        # V2.3 keys must be ABSENT.
        for retired_key in ("project_class", "use_type"):
            self.assertNotIn(
                retired_key, criteria,
                f"peer_criteria still emits V2.3 key {retired_key!r}. "
                f"Stage 3: remove from _assemble_cache "
                f"(baselines.py:911-914) and tier_to_fallback_level "
                f"map at baselines.py:901-906."
            )
        # Schema version stamp.
        self.assertEqual(
            criteria.get("schema_version"), "pr14c",
            "peer_criteria.schema_version must be 'pr14c'. "
            "Stage 3 §6.3 + Q4 Option B: stamp PR14C_SCHEMA_VERSION "
            "into every cache write."
        )

    # ──────────────────────────────────────────────────────────
    # Test 3 — lifecycle_normalized_percentile placeholder
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_writes_lifecycle_normalized_percentile_for_each_dataset(self):
        """Per Q1 lock, the cache must emit
        ``lifecycle_normalized_percentile`` keys with placeholder
        value ``None`` on inspections + complaints.

        PR #14D will replace None with a calibrated formula. Today
        score.py reads the key (PR #14B change) but _assemble_cache
        doesn't write it → null in production.
        """
        self._require_db_kwarg()
        socrata = MockSocrataClient()
        _seed_cohort_world(socrata)
        project = _menahan_like_project()
        db = _StubDb(projects=[dict(project)])

        cache = _run(compute_peer_stats_full(socrata, project, db=db))

        for label in ("inspections", "complaints"):
            self.assertIn(
                "lifecycle_normalized_percentile", cache.get(label, {}),
                f"cache[{label!r}] missing "
                f"'lifecycle_normalized_percentile' key. "
                f"Stage 3: update _assemble_cache "
                f"(baselines.py:868-880) to emit the key with "
                f"None placeholder per Q1 lock. Real formula "
                f"deferred to PR #14D."
            )
            self.assertIsNone(
                cache[label]["lifecycle_normalized_percentile"],
                f"cache[{label!r}].lifecycle_normalized_percentile "
                f"must be None per Q1 lock (PR #14D will compute). "
                f"Got: {cache[label]['lifecycle_normalized_percentile']!r}"
            )

        # Violations stays unavailable per V2.3 hotfix; no lifecycle
        # field required there.
        self.assertFalse(
            cache.get("violations", {}).get("available", True),
            "violations stays available=False per V2.3 hotfix; "
            "PR #14C must not regress that.",
        )

    # ──────────────────────────────────────────────────────────
    # Test 4 — classify fires when type missing
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_calls_maybe_classify_when_dob_project_type_missing(self):
        """When project doc lacks dob_project_type,
        maybe_classify_project_dob_type MUST be invoked.

        Otherwise the cohort builder has no project type to read
        and falls through to lifecycle_skip_reason="no_spec". This
        is the gap producing the Menahan production state.
        """
        self._require_db_kwarg()
        socrata = MockSocrataClient()
        _seed_cohort_world(socrata)
        project = _menahan_like_project()  # no dob_project_type
        db = _StubDb(projects=[dict(project)])

        with patch(
            "lib.statistical_engine.baselines.maybe_classify_project_dob_type",
            new=AsyncMock(),
        ) as classify_spy, patch(
            "lib.statistical_engine.baselines.compute_cohort_for_project",
            new=AsyncMock(return_value=_minimal_cohort_result()),
        ):
            _run(compute_peer_stats_full(socrata, project, db=db))

        self.assertEqual(
            classify_spy.call_count, 1,
            f"maybe_classify_project_dob_type called "
            f"{classify_spy.call_count} times; expected 1. "
            "Stage 3: wire the call inside compute_peer_stats_full "
            "BEFORE compute_cohort_for_project. The classifier "
            "short-circuits if nyc_bin missing, so safe to call "
            "unconditionally when dob_project_type is None."
        )

    # ──────────────────────────────────────────────────────────
    # Test 5 — idempotency on classify (positive assertion)
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_skips_classify_when_dob_project_type_present(self):
        """Per §6.5 lock: positive assertion. When the project doc
        ALREADY has dob_project_type, the wrapper's guard must
        short-circuit before calling maybe_classify_project_dob_type
        — saving a defensive Socrata round-trip.

        Pairs with Test 1 to enforce the wired-but-conditional
        contract: cohort_spy.called AND classify_spy.not_called.
        """
        self._require_db_kwarg()
        socrata = MockSocrataClient()
        _seed_cohort_world(socrata)
        # Project doc ALREADY has dob_project_type set.
        project = _menahan_like_project(dob_project_type="new_building")
        db = _StubDb(projects=[dict(project)])

        with patch(
            "lib.statistical_engine.baselines.maybe_classify_project_dob_type",
            new=AsyncMock(),
        ) as classify_spy, patch(
            "lib.statistical_engine.baselines.compute_cohort_for_project",
            new=AsyncMock(return_value=_minimal_cohort_result()),
        ) as cohort_spy:
            _run(compute_peer_stats_full(socrata, project, db=db))

        # Positive assertion #1: cohort_spy DID fire (proves the
        # wrapper is wired up — pairs with Test 1).
        self.assertGreater(
            cohort_spy.call_count, 0,
            "compute_cohort_for_project must still fire when "
            "dob_project_type is already set. Stage 3: guard "
            "should short-circuit ONLY classification, not the "
            "cohort compute."
        )

        # Positive assertion #2: classify_spy did NOT fire.
        self.assertEqual(
            classify_spy.call_count, 0,
            f"maybe_classify_project_dob_type called "
            f"{classify_spy.call_count} times when "
            f"dob_project_type was already set. Stage 3: "
            "add ``if not project.get('dob_project_type')`` guard "
            "BEFORE the classify call in compute_peer_stats_full. "
            "Idempotency check belongs in the wrapper, NOT inside "
            "maybe_classify_project_dob_type (which has its own "
            "guard but still costs a Python call frame)."
        )

    # ──────────────────────────────────────────────────────────
    # Test 6 — lazy PLUTO refresh invocation
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_calls_ensure_pluto_snapshot_complete(self):
        """compute_peer_stats_full MUST call
        _ensure_pluto_snapshot_pr14b_complete so PLUTO snapshot has
        all 14 fields before the cohort builder reads it.

        Production Menahan has pluto_snapshot={"bldgclass": "C1"}
        only — missing the 13 other fields. The helper exists
        (PR #14B baselines.py:2056) but is only called inside
        compute_cohort_for_project. By the time cohort fires,
        downstream readers may already have hit the partial doc.
        """
        self._require_db_kwarg()
        socrata = MockSocrataClient()
        _seed_cohort_world(socrata)
        # Partial snapshot like production Menahan.
        project = _menahan_like_project(
            pluto_snapshot={"bldgclass": "C1"},
            dob_project_type="new_building",
        )
        db = _StubDb(projects=[dict(project)])

        with patch(
            "lib.statistical_engine.baselines._ensure_pluto_snapshot_pr14b_complete",
            new=AsyncMock(side_effect=bl._ensure_pluto_snapshot_pr14b_complete),
        ) as snapshot_spy, patch(
            "lib.statistical_engine.baselines.compute_cohort_for_project",
            new=AsyncMock(return_value=_minimal_cohort_result()),
        ):
            _run(compute_peer_stats_full(socrata, project, db=db))

        self.assertGreater(
            snapshot_spy.call_count, 0,
            f"_ensure_pluto_snapshot_pr14b_complete called "
            f"{snapshot_spy.call_count} times; expected ≥1. "
            "Stage 3: call _ensure_pluto_snapshot_pr14b_complete "
            "inside compute_peer_stats_full BEFORE classification "
            "and cohort compute. The helper is idempotent — "
            "skips re-fetch when snapshot already has all PR #14B "
            "fields AND when project is full_demo (Risk 7)."
        )

    # ──────────────────────────────────────────────────────────
    # Test 7 — _v22_shape_from_cache emits PR #14B FE keys
    # ──────────────────────────────────────────────────────────

    def test_v22_shape_from_cache_emits_pr14b_peer_set_keys(self):
        """_v22_shape_from_cache is the FE-facing shape transformer.
        It MUST emit PR #14B vocabulary (dob_project_type,
        geography_tier_used, low_confidence_flag) — NOT the V2.3
        vocabulary (project_class, use_type).

        Pure shape projection — no Socrata involved.
        """
        cache = _pr14b_cache_doc()
        out = _v22_shape_from_cache(cache)

        peer_set = out.get("peer_set") or {}

        # New PR #14B keys must appear.
        for required_key in (
            "dob_project_type", "geography_tier_used",
            "low_confidence_flag",
        ):
            self.assertIn(
                required_key, peer_set,
                f"_v22_shape_from_cache output.peer_set missing "
                f"{required_key!r}. Stage 3: update "
                f"_v22_shape_from_cache (baselines.py:1356-1420) "
                f"to project PR #14B keys onto the FE surface. "
                f"Got peer_set keys: {sorted(peer_set.keys())!r}"
            )

        # Values flow through correctly.
        self.assertEqual(peer_set.get("dob_project_type"), "new_building")
        self.assertEqual(
            peer_set.get("geography_tier_used"), "zip_bldgclass_type",
        )
        self.assertEqual(peer_set.get("low_confidence_flag"), False)

        # V2.3 keys must be ABSENT (per Q7 retirement).
        for retired_key in ("project_class", "use_type"):
            self.assertNotIn(
                retired_key, peer_set,
                f"_v22_shape_from_cache still emits V2.3 key "
                f"{retired_key!r} on the FE surface. Stage 3: "
                f"delete the tier-conditional emission at "
                f"baselines.py:1384-1389."
            )

        # Per-dataset lifecycle_normalized_percentile passes through.
        for label in ("inspections", "complaints"):
            self.assertIn(
                "lifecycle_normalized_percentile", out.get(label, {}),
                f"_v22_shape_from_cache output[{label!r}] missing "
                f"'lifecycle_normalized_percentile'. Stage 3: add "
                f"the pass-through at the per-dataset projection "
                f"in baselines.py:1410-1419."
            )
            self.assertIsNone(
                out[label]["lifecycle_normalized_percentile"],
                "lifecycle_normalized_percentile pass-through "
                "must preserve None when input is None (Q1 lock).",
            )

    # ──────────────────────────────────────────────────────────
    # Test 8 — Latent Bug 1 fix
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_persists_refreshed_pluto_snapshot_to_db(self):
        """Q6 / Latent Bug 1: when PLUTO snapshot is refreshed
        mid-compute, the refreshed snapshot MUST be written to
        db.projects.

        Current _persist_cache guard at baselines.py:1443 reads
        ``if snapshot and not project.get('pluto_snapshot')`` —
        after in-memory refresh, the guard skips the DB write
        because the project already has a (just-updated) snapshot.
        The refreshed snapshot never reaches the projects collection.

        Stage 3 fix: add ``peer_criteria.pluto_snapshot_refreshed_at``
        timestamp; _persist_cache writes the snapshot when that
        field is set, regardless of project.pluto_snapshot state.
        """
        # Project with INCOMPLETE pluto_snapshot (only bldgclass —
        # production Menahan state).
        project = _menahan_like_project(
            pluto_snapshot={"bldgclass": "C1"},
        )
        db = _StubDb(projects=[dict(project)])

        # Fresh 14-field snapshot (as if _ensure_pluto_snapshot_pr14b_complete
        # just refreshed it).
        fresh_snapshot = {
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }

        # Synthesize a cache that carries both the fresh snapshot AND
        # the refresh marker the Stage 3 fix introduces.
        cache_with_refresh = _pr14b_cache_doc(
            peer_criteria={
                "pluto_snapshot":              fresh_snapshot,
                "pluto_snapshot_refreshed_at": datetime.now(timezone.utc),
            }
        )

        _run(_persist_cache(db, project, cache_with_refresh))

        # The persist must have written pluto_snapshot to $set, even
        # though project["pluto_snapshot"] is already truthy.
        self.assertGreater(
            len(db.projects.update_one_calls), 0,
            "_persist_cache did not call db.projects.update_one. "
            "The function must always write peer_stats_cache."
        )
        last_set = (
            db.projects.update_one_calls[-1]["update"].get("$set") or {}
        )
        self.assertIn(
            "pluto_snapshot", last_set,
            "_persist_cache did NOT include pluto_snapshot in $set "
            "despite peer_criteria.pluto_snapshot_refreshed_at being "
            "set. Stage 3 Q6 fix: in _persist_cache "
            "(baselines.py:1423-1454), change the guard from "
            "``if snapshot and not project.get('pluto_snapshot')`` "
            "to ``if snapshot and (not project.get('pluto_snapshot') "
            "or refreshed_at_marker_present)``. Closes Latent Bug 1."
        )
        persisted_snapshot = last_set["pluto_snapshot"]
        for required_field in ("cd", "numfloors", "unitsres",
                               "unitstotal", "bldgarea", "lotarea",
                               "yearbuilt", "zipcode"):
            self.assertIn(
                required_field, persisted_snapshot,
                f"Persisted snapshot missing PR #14B field "
                f"{required_field!r}. The fresh snapshot wasn't "
                f"the one that landed in $set.",
            )

    # ──────────────────────────────────────────────────────────
    # Test 9 — empty cohort cache with diagnostic markers (Q3)
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_writes_empty_cohort_cache_when_unknown_classification(self):
        """Per Q3 + T3 lock: when classifier returns "unknown",
        the cache must still get written with PR #14B shape PLUS a
        ``cohort_unavailable: true`` sentinel and diagnostic markers.

        NOT a zero-peer marker (that's for timeout / socrata_error
        cases). The cache should describe WHY the cohort couldn't
        be built so the FE drawer can render a "classification
        pending" state.
        """
        self._require_db_kwarg()
        self._require_schema_version_constant()
        socrata = MockSocrataClient()
        # PLUTO row for active project so snapshot refresh works.
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "9001234567", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "9001", "lot": "234",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        # No DOB NOW seed, no BIS seed → classifier returns "unknown".
        socrata.seed(DATASET_DOB_PERMITS, [])
        socrata.seed(DATASET_BIS_JOB_FILINGS, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

        project = _menahan_like_project(
            _id="P_UNKNOWN",
            nyc_bin="9999999",
            bbl="9001234567",
        )
        db = _StubDb(projects=[dict(project)])

        cache = _run(compute_peer_stats_full(socrata, project, db=db))

        criteria = cache.get("peer_criteria") or {}
        self.assertEqual(
            criteria.get("dob_project_type"), "unknown",
            "Empty-cohort cache must record dob_project_type='unknown'. "
            "Stage 3 Q3: thread the classifier result into "
            "_assemble_cache's peer_criteria, even when cohort empty."
        )
        self.assertTrue(
            criteria.get("cohort_unavailable"),
            "Empty-cohort cache must carry "
            "cohort_unavailable=True sentinel. Stage 3 Q3/T3: "
            "_assemble_cache emits this when sample_size=0; FE "
            "drawer + score normalizer use it to skip percentile "
            "display / weighting."
        )
        self.assertEqual(criteria.get("sample_size"), 0)
        self.assertEqual(
            criteria.get("lifecycle_skip_reason"), "no_spec",
            "compute_cohort_for_project returns "
            "lifecycle_skip_reason='no_spec' for unknown types; "
            "_assemble_cache must preserve that marker."
        )
        self.assertEqual(
            criteria.get("cohort_filter_spec"), {},
            "Empty cohort spec is the diagnostic — empty dict "
            "preserved per Q3.",
        )
        self.assertEqual(
            criteria.get("schema_version"), "pr14c",
            "Even empty-cohort caches must be stamped with "
            "schema_version (Q4 Option B).",
        )

    # ──────────────────────────────────────────────────────────
    # Test 10 — PLUTO BIN→BBL join produces event-keyed BBLs (Q2)
    # ──────────────────────────────────────────────────────────

    def test_compute_peer_stats_full_pluto_bin_to_bbl_join_produces_event_keyed_bbls(self):
        """Per Q2/T2: cohort BINs (from BIS rows) must be resolved
        to BBLs via a single batched PLUTO query, and those BBLs
        must key the event-count queries.

        Closes the _bis_geography_clause TODO. Today the event
        counts use V2.3 ladder BBLs (random tier-1 peers), not
        cohort-matched ones.
        """
        self._require_db_kwarg()
        socrata = MockSocrataClient()
        seed_meta = _seed_cohort_world(socrata)
        cohort_bbls_expected = seed_meta["cohort_bbls"]

        project = _menahan_like_project(dob_project_type="new_building")
        db = _StubDb(projects=[dict(project)])

        _run(compute_peer_stats_full(socrata, project, db=db))

        # Inspect SoQL WHERE clauses on the inspections dataset.
        inspections_calls = [
            kw for ds, kw in socrata.calls
            if ds == DATASET_DOB_INSPECTIONS
        ]
        self.assertGreater(
            len(inspections_calls), 0,
            "No inspections queries fired during "
            "compute_peer_stats_full. Stage 3: ensure event-count "
            "queries still happen after cohort cohort_job_numbers "
            "are resolved to BBLs via PLUTO join."
        )
        all_wheres = " | ".join(
            (kw.get("where") or "") for kw in inspections_calls
        )

        # Spot-check: at least the first 5 cohort BBLs should appear.
        missing = [
            bbl for bbl in cohort_bbls_expected[:5]
            if bbl not in all_wheres
        ]
        self.assertEqual(
            missing, [],
            f"Cohort BBLs {missing!r} did not appear in inspections "
            f"SoQL WHERE clauses. Stage 3 (Q2/T2): add helper "
            f"``_resolve_bbls_for_cohort_bins(socrata, bin_list)`` "
            f"that issues batched PLUTO ``bin IN (chunk)`` queries "
            f"(reuse _chunk + SOQL_IN_CHUNK_SIZE), then key event "
            f"counts on the resolved BBLs. "
            f"WHERE clauses observed: "
            f"{all_wheres[:200]!r}{'…' if len(all_wheres) > 200 else ''}"
        )

    # ──────────────────────────────────────────────────────────
    # Test 11 — schema check INVALIDATES stale V2.3 cache (Q4)
    # ──────────────────────────────────────────────────────────

    def test_compare_project_to_peers_invalidates_cache_when_schema_version_missing(self):
        """Per Q4 Option B + T4: a cache lacking ``schema_version``
        (V2.3 leftover) MUST be treated as a miss → triggers
        recompute via compute_peer_stats_full.

        This is the auto-detect half of Q4 + T5 belt-and-suspenders
        (operator $unset at deploy is the other half).
        """
        self._require_schema_version_constant()
        socrata = MockSocrataClient()
        project = _menahan_like_project(
            peer_stats_cache=_v23_cache_doc(),  # no schema_version
        )
        db = _StubDb(projects=[dict(project)])

        with patch(
            "lib.statistical_engine.baselines.compute_peer_stats_full",
            new=AsyncMock(return_value=_pr14b_cache_doc()),
        ) as recompute_spy:
            _run(compare_project_to_peers(
                db, project, socrata=socrata,
                now=datetime.now(timezone.utc),
            ))

        self.assertEqual(
            recompute_spy.call_count, 1,
            f"compute_peer_stats_full was NOT called for a cache "
            f"missing schema_version (call count: "
            f"{recompute_spy.call_count}). Stage 3 Q4 Option B: "
            f"in compare_project_to_peers cache-hit branch "
            f"(baselines.py:1500-1505), add "
            f"``if criteria.get('schema_version') != "
            f"PR14C_SCHEMA_VERSION: → cache miss``. Per T4 lock: "
            f"BOTH missing AND unmatched versions invalidate."
        )

    # ──────────────────────────────────────────────────────────
    # Test 12 — schema check PRESERVES hot path (Q4)
    # ──────────────────────────────────────────────────────────

    def test_compare_project_to_peers_serves_cache_when_schema_version_matches(self):
        """Positive case for the schema check: caches with
        ``schema_version="pr14c"`` are served from cache (hot path
        preserved, no Socrata calls).

        Pairs with Test 11 — the schema check must be strict-equality,
        not "is anything truthy".
        """
        self._require_schema_version_constant()
        socrata = MockSocrataClient()
        project = _menahan_like_project(
            peer_stats_cache=_pr14b_cache_doc(),  # schema_version="pr14c"
        )
        db = _StubDb(projects=[dict(project)])

        with patch(
            "lib.statistical_engine.baselines.compute_peer_stats_full",
            new=AsyncMock(),
        ) as recompute_spy:
            result = _run(compare_project_to_peers(
                db, project, socrata=socrata,
                now=datetime.now(timezone.utc),
            ))

        self.assertEqual(
            recompute_spy.call_count, 0,
            f"compute_peer_stats_full was called {recompute_spy.call_count} "
            "times on a current-schema cache hit. Stage 3: the schema "
            "check must accept ``schema_version='pr14c'`` and return "
            "the cached values without recompute."
        )
        # Hot path: zero Socrata calls.
        self.assertEqual(
            len(socrata.calls), 0,
            f"Hot-path cache hit fired {len(socrata.calls)} Socrata "
            "calls; expected 0. The whole point of the cache."
        )
        # Returned shape carries PR #14B keys (depends on Test 7 turning green).
        self.assertEqual(
            result.get("peer_set", {}).get("dob_project_type"),
            "new_building",
            "Cache-hit return shape doesn't emit dob_project_type. "
            "Depends on Test 7 (_v22_shape_from_cache update) "
            "landing in the same Stage 3."
        )


if __name__ == "__main__":
    unittest.main()
