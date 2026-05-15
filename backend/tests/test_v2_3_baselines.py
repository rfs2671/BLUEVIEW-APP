"""Phase V2.3 — Lazy peer-comparison engine tests.

Replaces test_v2_2_baselines.py. V2.2 mocked the local Mongo
mirror; V2.3 mocks the SocrataClient (see tests/_socrata_mock.py).
Pins every contract the V2.3 rewrite preserves + the new
peer_stats_cache lifecycle.

  • Peer-key extraction from project doc (pure, untouched).
  • Fallback ladder: full → drop use_type → drop class → citywide
    (rewritten to lazy PLUTO queries via MockSocrataClient).
  • SoQL helpers (_soql_quote / _soql_in / _iso_prefix) produce
    well-formed Socrata syntax.
  • Per-BBL event counts include zero-count BBLs.
  • Summary stats: n, mean, median, p75, p90, p95, max (math
    untouched).
  • compute_peer_stats_full: full lifecycle PLUTO + 3 datasets
    → ready-to-persist cache dict.
  • refresh_peer_stats_incremental: only re-pulls full counts
    for BBLs that gained events, falls back to full compute on
    a malformed cache.
  • count_own_building_events: own-BIN 30d/60d/90d counts.
  • compare_project_to_peers cache semantics:
      - cache present + ready  → return cached, no Socrata calls
      - cache absent → synchronous compute_peer_stats_full,
                       persist to db.projects, return result
      - timeout → zero-peer marker with reason="timeout"
      - SocrataQueryError → zero-peer marker with
                            reason="socrata_error"
  • peer_stats_cache staleness boundary: 14 days.
  • Package re-exports.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
from uuid import uuid4

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))

from lib.statistical_engine import baselines as bl  # noqa: E402
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_COMPLAINTS_311,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_VIOLATIONS,
    DATASET_PLUTO,
    SocrataQueryError,
)

from _socrata_mock import MockSocrataClient  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Stub projects collection
# ──────────────────────────────────────────────────────────────────


class _StubProjectsColl:
    def __init__(self, docs: List[Dict[str, Any]] = None) -> None:
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


class _StubDobLogsCursor:
    """Mongo-aggregate cursor stand-in. Implements the .to_list()
    coroutine count_own_building_events awaits."""

    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        if length is None:
            return list(self._docs)
        return list(self._docs)[:length]


def _stub_dob_match_field(actual, condition):
    """Evaluate one field's match condition. Supports the SoQL-ish
    operator subset count_own_building_events uses:
      • bare equality
      • $ne / $in / $nin / $gte / $exists
    Anything else raises so a future pipeline change can't silently
    bypass the stub.
    """
    if isinstance(condition, dict):
        for op, expected in condition.items():
            if op == "$ne":
                if actual == expected:
                    return False
            elif op == "$in":
                if actual not in expected:
                    return False
            elif op == "$nin":
                if actual in expected:
                    return False
            elif op == "$gte":
                if actual is None or actual < expected:
                    return False
            elif op == "$gt":
                if actual is None or actual <= expected:
                    return False
            elif op == "$exists":
                exists = actual is not None
                if exists != expected:
                    return False
            else:
                raise NotImplementedError(
                    f"_StubDobLogsColl does not implement {op!r} yet; "
                    f"extend the stub if the pipeline added a new operator",
                )
        return True
    return actual == condition


def _stub_dob_match(doc, criteria):
    return all(
        _stub_dob_match_field(doc.get(field), cond)
        for field, cond in criteria.items()
    )


class _StubDobLogsColl:
    """In-memory dob_logs collection that interprets the specific
    aggregate pipeline shape count_own_building_events emits:

      [
        { "$match": <top-level filter> },
        { "$facet": {
            "<name>": [
              { "$match": <facet filter> },
              { "$count": "n" },
            ],
            ...
        }},
      ]

    Returns a list-of-one shape mirroring real Mongo $facet output.
    """

    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.aggregate_calls: List[Any] = []

    def seed(self, docs):
        self.docs.extend(docs)

    def aggregate(self, pipeline, *args, **kwargs):
        self.aggregate_calls.append(pipeline)
        return _StubDobLogsCursor(self._evaluate(list(pipeline)))

    def _evaluate(self, pipeline):
        docs = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if _stub_dob_match(d, stage["$match"])]
                continue
            if "$facet" in stage:
                result = {}
                for facet_name, facet_pipeline in stage["$facet"].items():
                    fdocs = list(docs)
                    for fstage in facet_pipeline:
                        if "$match" in fstage:
                            fdocs = [
                                d for d in fdocs
                                if _stub_dob_match(d, fstage["$match"])
                            ]
                        elif "$count" in fstage:
                            count_field = fstage["$count"]
                            fdocs = [{count_field: len(fdocs)}] if fdocs else []
                        else:
                            raise NotImplementedError(
                                f"_StubDobLogsColl facet stage {fstage!r} "
                                f"not implemented",
                            )
                    result[facet_name] = fdocs
                return [result]
            if "$count" in stage:
                count_field = stage["$count"]
                docs = [{count_field: len(docs)}] if docs else []
                continue
            raise NotImplementedError(
                f"_StubDobLogsColl top-level stage {stage!r} not implemented",
            )
        return docs


class _StubDb:
    def __init__(self, projects=None, dob_logs=None):
        self.projects = _StubProjectsColl(projects)
        self.dob_logs = _StubDobLogsColl(dob_logs)


# ──────────────────────────────────────────────────────────────────
# Peer-set key (pure, no I/O)
# ──────────────────────────────────────────────────────────────────


# PR #14C Stage 2.B — TestPeerKey REMOVED.
#
# Q7 lock: ``_project_peer_key`` retires alongside the V2.3 4-tier
# ladder (peer_bbls + _bbls_matching_socrata). Cohort-aware peer
# comparison reads ``dob_project_type`` + PLUTO snapshot directly
# instead of building a V2.3 peer-key dict. TestPeerKey covered 5
# tests pinning the retired function's behavior.


# ──────────────────────────────────────────────────────────────────
# SoQL helpers
# ──────────────────────────────────────────────────────────────────


class TestSoqlHelpers(unittest.TestCase):

    def test_quote_basic(self):
        self.assertEqual(bl._soql_quote("MANHATTAN"), "'MANHATTAN'")

    def test_quote_escapes_internal_apostrophe(self):
        self.assertEqual(bl._soql_quote("Bear's Den"), "'Bear''s Den'")

    def test_in_clause(self):
        self.assertEqual(
            bl._soql_in("bbl", ["100", "200"]),
            "bbl IN ('100','200')",
        )

    def test_in_clause_empty_list_is_defanged(self):
        self.assertEqual(bl._soql_in("bbl", []), "bbl IN ('')")

    def test_iso_prefix_format(self):
        dt = datetime(2026, 5, 8, 12, 30, 45, tzinfo=timezone.utc)
        self.assertEqual(bl._iso_prefix(dt), "2026-05-08T12:30:45")


# ──────────────────────────────────────────────────────────────────
# Peer fallback ladder (lazy PLUTO via mock)
# ──────────────────────────────────────────────────────────────────


def _pluto_row(bbl_, borough, bldgclass=None, landuse=None):
    d = {"bbl": bbl_, "borough": borough}
    if bldgclass: d["bldgclass"] = bldgclass
    if landuse:   d["landuse"] = landuse
    return d


# PR #14C Stage 2.B — TestFallbackLadder REMOVED.
#
# Q7 lock: the V2.3 4-tier ladder (borough_class_use →
# borough_class → borough → citywide) retires alongside
# peer_bbls + _bbls_matching_socrata + the TIER_*_MAX_PEERS
# constants. Cohort discovery is now driven by
# compute_cohort_for_project (PR #14B) wired through
# compute_peer_stats_full (PR #14C wiring point 1).
#
# Coverage migration:
#   • Tier transition behavior is now tested by
#     TestComputeCohortForProject in test_v2_3_baselines.py
#     (12 tests covering the 4-tier geography ladder per
#     dob_project_type, sample-size floors, 36→60mo window
#     expansion, secondary fallback).
#   • PLUTO SELECT contract is tested by
#     TestPlutoSelectExtensionPR14B::test_pluto_select_clause_contains_all_pr14b_fields
#     (positive-form coverage; strict-set discipline replaced
#     by the explicit 14-field list).
#
# TestFallbackLadder previously covered 10+ tests (~240 lines).


# ──────────────────────────────────────────────────────────────────
# Per-BBL event counts (lazy Socrata)
# ──────────────────────────────────────────────────────────────────


class TestCountEventsForBblsSocrata(unittest.TestCase):

    def test_includes_zero_count_bbls(self):
        """Schema-corrections hotfix: violations is gated off
        peer counts (no ``bbl`` column on 3h2n-5cm9), so this
        test now exercises the zero-fill path on the inspections
        dataset (which still has ``bbl``)."""
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_INSPECTIONS, [
            {"bbl": "1008470001", "inspection_date": "2026-04-01T00:00:00"},
            {"bbl": "1008470001", "inspection_date": "2026-04-02T00:00:00"},
            {"bbl": "1008470002", "inspection_date": "2026-04-03T00:00:00"},
        ])
        counts = _run(bl._count_events_for_bbls_socrata(
            socrata, DATASET_DOB_INSPECTIONS,
            ["1008470001", "1008470002", "1008470003", "1008470004"],
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        self.assertEqual(counts, {
            "1008470001": 2,
            "1008470002": 1,
            "1008470003": 0,
            "1008470004": 0,
        })

    def test_empty_bbl_list(self):
        socrata = MockSocrataClient()
        counts = _run(bl._count_events_for_bbls_socrata(
            socrata, DATASET_DOB_VIOLATIONS, [],
            since=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ))
        self.assertEqual(counts, {})

    def test_per_dataset_date_column(self):
        # Inspections use `inspection_date`, not `issue_date`.
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_INSPECTIONS, [
            {"bbl": "1009000001", "inspection_date": "2026-04-01T00:00:00"},
            {"bbl": "1009000001", "inspection_date": "2026-04-02T00:00:00"},
        ])
        counts = _run(bl._count_events_for_bbls_socrata(
            socrata, DATASET_DOB_INSPECTIONS,
            ["1009000001"],
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        self.assertEqual(counts, {"1009000001": 2})

    def test_chunking_large_bbl_list(self):
        """Schema-corrections hotfix: chunking is now exercised
        on the inspections dataset because violations is gated
        off peer counts (no ``bbl`` column on 3h2n-5cm9)."""
        n_total = bl.SOQL_IN_CHUNK_SIZE + 50
        bbls = [f"100100{i:04d}" for i in range(n_total)]
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_INSPECTIONS, [
            {"bbl": b, "inspection_date": "2026-04-01T00:00:00"} for b in bbls
        ])
        counts = _run(bl._count_events_for_bbls_socrata(
            socrata, DATASET_DOB_INSPECTIONS, bbls,
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        self.assertEqual(len(counts), n_total)
        self.assertTrue(all(v == 1 for v in counts.values()))
        i_calls = [c for c in socrata.calls if c[0] == DATASET_DOB_INSPECTIONS]
        self.assertGreater(len(i_calls), 1)


# ──────────────────────────────────────────────────────────────────
# Summary stats (pure math)
# ──────────────────────────────────────────────────────────────────


class TestSummarizeCounts(unittest.TestCase):

    def test_empty_returns_zeros(self):
        s = bl._summarize_counts({})
        self.assertEqual(s["n"], 0)
        self.assertEqual(s["mean"], 0.0)
        self.assertEqual(s["max"], 0.0)

    def test_known_distribution(self):
        s = bl._summarize_counts({
            "A": 0, "B": 1, "C": 2, "D": 3, "E": 100,
        })
        self.assertEqual(s["n"], 5)
        self.assertEqual(s["max"], 100.0)
        self.assertAlmostEqual(s["mean"], 21.2)
        self.assertEqual(s["median"], 2.0)


class TestPercentile(unittest.TestCase):

    def test_basic_percentiles(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(bl._percentile(vals, 0), 1.0)
        self.assertEqual(bl._percentile(vals, 100), 5.0)
        self.assertEqual(bl._percentile(vals, 50), 3.0)

    def test_empty(self):
        self.assertEqual(bl._percentile([], 50), 0.0)


class TestPercentileRank(unittest.TestCase):

    def test_project_above_all_peers_is_100(self):
        rank = bl._percentile_rank([0, 1, 2, 3], 50)
        self.assertEqual(rank, 100.0)

    def test_project_below_all_peers_is_0(self):
        rank = bl._percentile_rank([5, 6, 7, 8], 0)
        self.assertEqual(rank, 0.0)

    def test_empty_peers_returns_0(self):
        self.assertEqual(bl._percentile_rank([], 50), 0.0)


# ──────────────────────────────────────────────────────────────────
# compute_peer_stats_full
# ──────────────────────────────────────────────────────────────────


class TestComputePeerStatsFull(unittest.TestCase):
    """PR #14C REWRITTEN — compute_peer_stats_full drives the PR #14B
    cohort path (compute_cohort_for_project) instead of the retired
    V2.3 4-tier peer_bbls() ladder.

    Pre-PR-14C this class pinned V2.3 peer_criteria (project_class,
    use_type, tier="borough_class_use"). Per Q7 lock those keys are
    retired. The 3 tests below pin the new PR #14B shape + the
    preserved violations-unavailable hotfix.

    All tests call compute_peer_stats_full with db= kwarg per
    Stage 2.A §6.1 lock. RED phase fails with TypeError on missing
    kwarg; Stage 3 adds the kwarg + classification + cohort wiring.
    """

    def _seed_cohort_for_pr14c(self, socrata):
        """Seed PLUTO (active project + cohort BINs for Q2 join),
        DOB NOW (classifier route), BIS (cohort), C of O (completion),
        and empty event datasets."""
        from _pr14b_fixtures import (
            DATASET_BIS_JOB_FILINGS,
            DATASET_DOB_PERMITS,
            make_cohort_fixture,
            seed_dob_now_for_bin,
        )
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        seed_dob_now_for_bin(
            socrata, bin="3325703",
            work_type="General Construction",
            filing_reason="Initial Permit",
            job_description="NEW BUILDING 5-STORY RESIDENTIAL 8 UNITS",
        )
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=150,
            bin_prefix="3033040", job_number_prefix="32100",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        socrata.seed(DATASET_PLUTO, [
            {
                "bbl": f"3033041{i:04d}",
                "bin": f"3033040{i:04d}",
                "borough": "BK", "bldgclass": "C1",
                "landuse": "01", "zipcode": "11221", "cd": "304",
                "yearbuilt": "1990", "unitsres": "8",
                "unitstotal": "8", "numfloors": "5",
                "bldgarea": "8000", "lotarea": "2500",
            }
            for i in range(150)
        ])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

    def _menahan_like_project(self, **overrides):
        base = {
            "_id": "P_NB",
            "name": "9 Menahan",
            "nyc_bin": "3325703",
            "bbl": "3033040024",
            "borough": "BROOKLYN",
            "dob_project_type": "new_building",
        }
        base.update(overrides)
        return base

    def _stub_db(self, project):
        class _SimpleDb:
            def __init__(self, projects_coll):
                self.projects = projects_coll
        return _SimpleDb(_StubProjectsColl(docs=[dict(project)]))

    def test_returns_pr14b_shape(self):
        """Cache.peer_criteria carries PR #14B keys, NOT V2.3 keys.
        Replaces the pre-PR-14C assertion that
        peer_criteria.tier == 'borough_class_use'."""
        socrata = MockSocrataClient()
        self._seed_cohort_for_pr14c(socrata)
        project = self._menahan_like_project()
        cache = _run(bl.compute_peer_stats_full(
            socrata, project, db=self._stub_db(project),
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(cache["status"], "ready")
        criteria = cache["peer_criteria"]
        self.assertEqual(criteria["dob_project_type"], "new_building")
        self.assertIn("geography_tier_used", criteria)
        self.assertIn("low_confidence_flag", criteria)
        self.assertEqual(
            criteria.get("schema_version"), "pr14c",
            "Stage 3 Q4: stamp PR14C_SCHEMA_VERSION onto every "
            "cache write so the schema check in "
            "compare_project_to_peers can validate the cache "
            "vintage.",
        )
        self.assertNotIn("project_class", criteria)
        self.assertNotIn("use_type", criteria)

    def test_violations_gated_as_unavailable_in_peer_cache(self):
        """V2.3 schema-corrections hotfix CORRECTION 3 Option A
        is PRESERVED through PR #14C. dob_violations stays excluded
        from BBL-keyed peer comparison (no ``bbl`` column on
        3h2n-5cm9); cache surfaces a degenerate
        ``{"available": False, ...}`` entry."""
        socrata = MockSocrataClient()
        self._seed_cohort_for_pr14c(socrata)
        project = self._menahan_like_project()
        cache = _run(bl.compute_peer_stats_full(
            socrata, project, db=self._stub_db(project),
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(cache["violations"]["available"], False)
        self.assertEqual(
            cache["violations"]["unavailable_reason"],
            "bbl_keyed_peer_set_incompatible_with_bin_keyed_dataset",
        )
        self.assertIn("peer_data_dropped_in_pr", cache["violations"])
        for forbidden_key in (
            "percentile_rank", "peer_median", "peer_p75",
            "peer_p90", "project_count",
        ):
            self.assertNotIn(
                forbidden_key, cache["violations"],
                f"violations sub-dict carries {forbidden_key!r} "
                f"while available=False",
            )
        self.assertEqual(cache["inspections"]["available"], True)
        self.assertEqual(cache["complaints"]["available"], True)
        for label in ("inspections", "complaints"):
            self.assertIn("percentile_rank", cache[label])
            self.assertIn(
                "lifecycle_normalized_percentile", cache[label],
                f"{label}: missing lifecycle_normalized_percentile "
                f"key. Stage 3 Q1: emit None placeholder.",
            )

    def test_lifecycle_normalized_percentile_is_none_per_q1_lock(self):
        """Per Q1 lock, inspections + complaints carry
        lifecycle_normalized_percentile=None. PR #14D will replace
        None with a calibrated formula."""
        socrata = MockSocrataClient()
        self._seed_cohort_for_pr14c(socrata)
        project = self._menahan_like_project()
        cache = _run(bl.compute_peer_stats_full(
            socrata, project, db=self._stub_db(project),
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        for label in ("inspections", "complaints"):
            self.assertIsNone(
                cache[label].get("lifecycle_normalized_percentile"),
                f"{label}.lifecycle_normalized_percentile must be "
                f"None per Q1 lock.",
            )


# ──────────────────────────────────────────────────────────────────
# refresh_peer_stats_incremental
# ──────────────────────────────────────────────────────────────────


class TestRefreshPeerStatsIncremental(unittest.TestCase):

    def test_falls_back_to_full_compute_on_empty_cache(self):
        socrata = MockSocrataClient()
        # Schema-correct PLUTO seed (2-letter borough + DOF code).
        socrata.seed(DATASET_PLUTO, [
            {"bbl": f"100012{i:04d}", "borough": "MN",
             "bldgclass": "O4", "landuse": "office"}
            for i in range(25)
        ] + [
            {"bbl": "1000120000", "borough": "MN",
             "bldgclass": "O4", "landuse": "office"},
        ])
        socrata.seed(DATASET_DOB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])
        project = {
            "bbl": "1000120000", "borough": "MANHATTAN",
            "use_type": "office",
            "peer_stats_cache": {},  # malformed cache
        }
        cache = _run(bl.refresh_peer_stats_incremental(
            socrata, project,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(cache["status"], "ready")
        self.assertIn("peer_criteria", cache)

    def test_bumps_last_refreshed_at_keeps_computed_at(self):
        socrata = MockSocrataClient()
        old_computed_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        old_last_refreshed = datetime(2026, 4, 20, tzinfo=timezone.utc)
        peer_set = [f"100013{i:04d}" for i in range(25)]
        socrata.seed(DATASET_DOB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])
        zero_summary = {
            "n": 24, "mean": 0.0, "median": 0.0, "p75": 0.0, "p90": 0.0,
            "p95": 0.0, "max": 0.0, "project_count": 0,
            "percentile_rank": 0.0,
        }
        project = {
            "bbl": "1000130000", "borough": "MANHATTAN",
            "dob_project_type": "new_building",
            "peer_stats_cache": {
                "computed_at": old_computed_at,
                "last_refreshed_at": old_last_refreshed,
                "status": "ready",
                # PR #14C: peer_criteria seeded with new shape +
                # schema_version="pr14c" so the cache-hit branch
                # doesn't trigger schema-mismatch recompute.
                "peer_criteria": {
                    "schema_version":      "pr14c",
                    "borough":             "MANHATTAN",
                    "dob_project_type":    "new_building",
                    "geography_tier_used": "zip_bldgclass_type",
                    "low_confidence_flag": False,
                    "bbl":                 "1000130000",
                    "sample_size":         len(peer_set) - 1,
                    "fallback_level":      1,
                    "peer_bbl_list":       peer_set,
                    "_peer_counts_by_dataset": {
                        DATASET_DOB_VIOLATIONS:  {b: 0 for b in peer_set},
                        DATASET_DOB_INSPECTIONS: {b: 0 for b in peer_set},
                        DATASET_COMPLAINTS_311:  {b: 0 for b in peer_set},
                    },
                },
                "violations":  dict(zero_summary),
                "inspections": dict(zero_summary),
                "complaints":  dict(zero_summary),
            },
        }
        new_now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        cache = _run(bl.refresh_peer_stats_incremental(
            socrata, project, now=new_now,
        ))
        self.assertEqual(cache["computed_at"], old_computed_at)
        self.assertEqual(cache["last_refreshed_at"], new_now)


# ──────────────────────────────────────────────────────────────────
# count_own_building_events — V2.3.A2 (Mongo-aggregate-against-dob_logs)
#
# Tests 1–6 of the A2 PR. Pivots count_own_building_events away from
# Socrata polling (subset of datasets) to a 4-facet Mongo aggregate
# against db.dob_logs (populated nightly by run_dob_sync_for_project
# from the full DOB dataset list).
#
# All tests pass the NEW signature (project_id + db kwargs, no socrata
# positional). On main, count_own_building_events still has the old
# `socrata` positional signature, so every test below fails with
# TypeError. After A2 Stage 3 implementation, all 6 pass.
# ──────────────────────────────────────────────────────────────────


_PROJECT_ID = "test_project_X"


def _dob_log(
    *,
    record_type: str,
    project_id: str = _PROJECT_ID,
    raw_dob_id: str = None,
    is_deleted: bool = False,
    is_seed_transition: bool = False,
    **extras,
):
    """Helper — assemble a dob_logs document with the universal
    fields the legacy poller stamps + per-type extras. Mirrors the
    write shape at server.py:15292-15317.

    Defaults the raw_dob_id to a uuid4 hex slice so multiple calls
    can't collide (the V2.2.A2 Stage 4 cosmetic note flagged
    id(extras)-based defaults as collision-prone if the caller
    reuses the same extras dict).
    """
    raw_id = raw_dob_id or f"{record_type}:{uuid4().hex[:8]}"
    doc = {
        "project_id":         project_id,
        "company_id":         "company_X",
        "nyc_bin":            "1234567",
        "record_type":        record_type,
        "raw_dob_id":         raw_id,
        "is_deleted":         is_deleted,
        "is_seed_transition": is_seed_transition,
    }
    doc.update(extras)
    return doc


class TestCountOwnBuildingEvents(unittest.TestCase):
    """A2 — read from db.dob_logs via aggregate pipeline.

    Sub-tests pin:
      1. Active SWO counts as a violation (Menahan reproduction).
      2. Closed violations ($nin: ["certified", "dismissed"]) excluded.
      3. 30d / 60d / 90d window boundaries against YYYYMMDD strings.
      4. severity="Action" discriminator for failed inspections.
      5. Case-sensitive Closed / CLOSED filter for complaints
         (Q2 finding — both case variants appear in production).
      6. is_seed_transition=True records excluded (defensive — no
         records carry this flag today per Q5, but the filter
         protects against future ingestion changes that re-introduce
         synthetic seeds).
    """

    def test_count_own_building_events_includes_active_swo(self):
        """Test 1 — Menahan reproduction: a single SWO with
        resolution_state='hearing_scheduled' must count as
        violations_30d AND violations_90d (record_type SWO is
        treated as a violation for own-building counts)."""
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                record_type="swo",
                resolution_state="hearing_scheduled",
                violation_date=(now - timedelta(days=7)).strftime("%Y%m%d"),
            ),
        ])
        out = _run(bl.count_own_building_events(
            project_id=_PROJECT_ID,
            db=db,
            now=now,
        ))
        self.assertGreaterEqual(out["violations_30d"], 1)
        self.assertGreaterEqual(out["violations_90d"], 1)

    def test_count_own_building_events_excludes_closed_violations(self):
        """Test 2 — Q1-locked closed-state set
        ["certified", "dismissed"] applied via $nin."""
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                record_type="violation",
                resolution_state="open",
                violation_date=(now - timedelta(days=5)).strftime("%Y%m%d"),
            ),
            _dob_log(
                record_type="violation",
                resolution_state="certified",
                violation_date=(now - timedelta(days=5)).strftime("%Y%m%d"),
            ),
        ])
        out = _run(bl.count_own_building_events(
            project_id=_PROJECT_ID,
            db=db,
            now=now,
        ))
        self.assertEqual(out["violations_30d"], 1)

    def test_count_own_building_events_respects_30_60_90_windows(self):
        """Test 3 — YYYYMMDD string-compare cutoff logic across
        the window boundaries. Q7-locked format."""
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                record_type="violation",
                resolution_state="open",
                violation_date=(now - timedelta(days=15)).strftime("%Y%m%d"),
            ),
            _dob_log(
                record_type="violation",
                resolution_state="open",
                violation_date=(now - timedelta(days=45)).strftime("%Y%m%d"),
            ),
            _dob_log(
                record_type="violation",
                resolution_state="open",
                violation_date=(now - timedelta(days=75)).strftime("%Y%m%d"),
            ),
            _dob_log(
                record_type="violation",
                resolution_state="open",
                violation_date=(now - timedelta(days=120)).strftime("%Y%m%d"),
            ),
        ])
        out = _run(bl.count_own_building_events(
            project_id=_PROJECT_ID,
            db=db,
            now=now,
        ))
        # 15d-old → in 30d window AND 90d window.
        # 45d, 75d → in 90d window only.
        # 120d → outside both.
        self.assertEqual(out["violations_30d"], 1)
        self.assertEqual(out["violations_90d"], 3)

    def test_count_own_building_events_inspections_action_only(self):
        """Test 4 — Q3-locked severity="Action" discriminator.
        Inspections without severity=Action MUST NOT count even if
        they fall in the 60d window."""
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                record_type="inspection",
                severity="Action",
                inspection_date=(now - timedelta(days=10)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000",
                ),
            ),
            _dob_log(
                record_type="inspection",
                severity="Good",
                inspection_date=(now - timedelta(days=10)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000",
                ),
            ),
            _dob_log(
                record_type="inspection",
                severity="Good",
                inspection_date=(now - timedelta(days=20)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000",
                ),
            ),
        ])
        out = _run(bl.count_own_building_events(
            project_id=_PROJECT_ID,
            db=db,
            now=now,
        ))
        self.assertEqual(out["inspections_failed_60d"], 1)

    def test_count_own_building_events_open_complaints_handles_case_sensitivity(self):
        """Test 5 — Q2-locked case-sensitive closed set
        ["Closed", "CLOSED"]. Both case variants appear in
        production and BOTH must be excluded. ACTIVE and
        "In Progress" both count as open."""
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                record_type="complaint",
                complaint_status="Closed",
                complaint_date=(now - timedelta(days=5)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000",
                ),
            ),
            _dob_log(
                record_type="complaint",
                complaint_status="CLOSED",
                complaint_date=(now - timedelta(days=5)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000",
                ),
            ),
            _dob_log(
                record_type="complaint",
                complaint_status="ACTIVE",
                complaint_date=(now - timedelta(days=5)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000",
                ),
            ),
            _dob_log(
                record_type="complaint",
                complaint_status="In Progress",
                complaint_date=(now - timedelta(days=5)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000",
                ),
            ),
        ])
        out = _run(bl.count_own_building_events(
            project_id=_PROJECT_ID,
            db=db,
            now=now,
        ))
        # Both Closed + CLOSED excluded; ACTIVE + In Progress count.
        self.assertEqual(out["open_complaints_30d"], 2)

    def test_count_own_building_events_excludes_seed_transition_records(self):
        """Test 6 — defensive filter from Q5. No production
        records carry is_seed_transition=True today, but the
        pipeline MUST exclude them to protect against future
        ingestion changes (e.g., V2.3→V2.4 schema migration
        with a fresh synthetic-seed flag)."""
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                record_type="violation",
                resolution_state="open",
                violation_date=(now - timedelta(days=5)).strftime("%Y%m%d"),
                is_seed_transition=False,
            ),
            _dob_log(
                record_type="violation",
                resolution_state="open",
                violation_date=(now - timedelta(days=5)).strftime("%Y%m%d"),
                is_seed_transition=True,
            ),
        ])
        out = _run(bl.count_own_building_events(
            project_id=_PROJECT_ID,
            db=db,
            now=now,
        ))
        self.assertEqual(out["violations_30d"], 1)


# ──────────────────────────────────────────────────────────────────
# PR #9 — heterogeneous date format regression tests
# ──────────────────────────────────────────────────────────────────


class TestA3DateNormalizationRegression(unittest.TestCase):
    """PR #9 regression tests against the heterogeneous date format
    bug found at Stage 10 of PR #8 verification.

    Bug: ``count_own_building_events`` filters complaints via
    ``$gte: _iso_prefix(c30)`` (e.g. ``"2026-04-13T00:00:00"``).
    Lexicographic comparison fails for MM/DD/YYYY-formatted source
    records — they're silently excluded from
    ``open_complaints_30d`` because '0' (0x30) < '2' (0x32).

    Stage 1.5 Query B confirmed 50 MDY complaints in production
    (22% of complaints), all on the DOB path (eabe-havv via
    ``_extract_complaint_fields``). Zero on the 311 path today.

    Test 12 pins the WRITE→READ contract: extractor normalizes MDY
    at ingestion → aggregate counts the resulting ISO records
    correctly. Per Stage 2 T5.A: regression test exercises both
    sides of the contract.

    Test 13 pins the violation aggregate's behavior given populated
    ``violation_date`` (post-backfill steady state): records with
    YYYYMMDD dates in the window count; records with null dates
    are excluded.
    """

    def test_12_count_own_building_events_counts_normalized_mdy_complaints(self):
        """Test 12 — write→read regression. RED-PHASE expected
        failure: current ``_extract_complaint_fields`` does not
        normalize MDY ``date_entered``, so the resulting dob_log
        has ``complaint_date == "06/04/2025"``. Aggregate's
        ``$gte`` filter against ISO cutoff '2026-04-13...' fails
        lexicographically — count is 0 not 1."""
        from server import _extract_complaint_fields

        now = datetime(2026, 5, 13, tzinfo=timezone.utc)

        # Two raw Socrata-shaped records: one MDY, one ISO. Both
        # within the 30-day window. Both have ACTIVE status (open
        # complaint per Q2 case-sensitive filter).
        raw_mdy = {
            "complaint_number":   "5042113",
            "date_entered":       (now - timedelta(days=10)).strftime("%m/%d/%Y"),
            "status":             "ACTIVE",
            "complaint_category": "21",
        }
        raw_iso = {
            "complaint_number":   "5042114",
            "date_entered":       (now - timedelta(days=15)).strftime(
                "%Y-%m-%dT%H:%M:%S.000"
            ),
            "status":             "ACTIVE",
            "complaint_category": "21",
        }

        # Run them through the extractor (this is the WRITE side
        # of the regression — extractor must produce ISO output).
        mdy_extracted = _extract_complaint_fields(raw_mdy)
        iso_extracted = _extract_complaint_fields(raw_iso)

        # Stuff into dob_logs fixture (READ side — aggregate
        # must count both records as open complaints).
        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                record_type="complaint",
                raw_dob_id="5042113",  # DOB-path (no 311: prefix)
                complaint_status=mdy_extracted["complaint_status"],
                complaint_date=mdy_extracted["complaint_date"],
            ),
            _dob_log(
                record_type="complaint",
                raw_dob_id="5042114",  # DOB-path
                complaint_status=iso_extracted["complaint_status"],
                complaint_date=iso_extracted["complaint_date"],
            ),
        ])
        out = _run(bl.count_own_building_events(
            project_id=_PROJECT_ID,
            db=db,
            now=now,
        ))
        self.assertEqual(
            out["open_complaints_30d"], 2,
            f"Both MDY-origin AND ISO-origin complaints must count "
            f"toward open_complaints_30d after extractor "
            f"normalization. MDY extracted complaint_date: "
            f"{mdy_extracted.get('complaint_date')!r}",
        )

    def test_13_count_own_building_events_counts_violations_with_extracted_date(self):
        """Test 13 — post-backfill steady state for violation_date.
        Fixture has 2 violations with populated YYYYMMDD dates and
        1 violation with null violation_date. Aggregate counts the
        populated records; null records are excluded by the date
        filter.

        Characterization test: aggregate's existing behavior is
        already correct; this pins the post-backfill regression
        target so any future change that breaks date filtering
        gets caught."""
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                record_type="violation",
                raw_dob_id="022217AEUHAZ100357",  # pre-A2 AEUHAZ pattern
                resolution_state="open",
                violation_date=(now - timedelta(days=10)).strftime("%Y%m%d"),
            ),
            _dob_log(
                record_type="violation",
                raw_dob_id="VIO-FTF-PL-PER-202412-0191848",  # pre-A2 VIO pattern
                resolution_state="open",
                violation_date=(now - timedelta(days=20)).strftime("%Y%m%d"),
            ),
            _dob_log(
                record_type="violation",
                raw_dob_id="022701LL629116468",  # pre-A2 LL629 pattern — null date
                resolution_state="open",
                violation_date=None,
            ),
        ])
        out = _run(bl.count_own_building_events(
            project_id=_PROJECT_ID,
            db=db,
            now=now,
        ))
        # 2 populated records in 30d window count; 1 null-date
        # record is excluded by the $gte filter (null fails $gte
        # against a YYYYMMDD cutoff string).
        self.assertEqual(
            out["violations_30d"], 2,
            f"Aggregate must count populated-date violations and "
            f"exclude null-date ones. Got: {out!r}",
        )


# ──────────────────────────────────────────────────────────────────
# compare_project_to_peers — cache-aware
# ──────────────────────────────────────────────────────────────────


class TestCompareProjectToPeersCacheAware(unittest.TestCase):
    """PR #14C UPDATED — cache-aware compare with PR #14B shape +
    schema_version invalidation.

    Pre-PR-14C tests pinned the V2.3 tier-conditional emission
    (tier-3 hides project_class/use_type, tier-4 hides borough).
    Per Q7 lock, those V2.3 vocabularies retire. New shape always
    emits dob_project_type + geography_tier_used + low_confidence_flag.

    The 4 tests below cover:
      1. ready-cache hot path with PR #14B shape pass-through
      2. cache miss → synchronous compute + persist
      3. timeout → zero-peer marker with reason
      4. SocrataQueryError → zero-peer marker with reason
    """

    def test_returns_cached_when_ready_with_pr14b_shape(self):
        """Cache-hit hot path emits PR #14B peer_set keys.
        Violations stays unavailable per V2.3 hotfix.
        """
        socrata = MockSocrataClient()
        cache = {
            "status": "ready",
            "computed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "last_refreshed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "peer_criteria": {
                "schema_version":      "pr14c",
                "dob_project_type":    "new_building",
                "geography_tier_used": "zip_bldgclass_type",
                "low_confidence_flag": False,
                "borough":             "MANHATTAN",
                "sample_size":         24,
                "fallback_level":      1,
                "window_months":       36,
                "completion_method":   "c_of_o_final",
            },
            "violations": {
                "available": False,
                "unavailable_reason":
                    "bbl_keyed_peer_set_incompatible_with_bin_keyed_dataset",
                "peer_data_dropped_in_pr":
                    "v2.3-schema-corrections-hotfix",
            },
            "inspections": {
                "available": True,
                "n": 24, "median": 0.5, "p75": 1.0, "p90": 2.0,
                "project_count": 2, "percentile_rank": 70.0,
                "lifecycle_normalized_percentile": None,
            },
            "complaints": {
                "available": True,
                "n": 24, "median": 0.0, "p75": 0.5, "p90": 1.0,
                "project_count": 0, "percentile_rank": 50.0,
                "lifecycle_normalized_percentile": None,
            },
        }
        project = {"_id": "P1", "peer_stats_cache": cache}
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))

        # Hot path: zero Socrata.
        self.assertEqual(len(socrata.calls), 0)

        # PR #14B peer_set vocabulary.
        peer_set = result["peer_set"]
        self.assertEqual(peer_set["dob_project_type"], "new_building")
        self.assertEqual(
            peer_set["geography_tier_used"], "zip_bldgclass_type",
        )
        self.assertEqual(peer_set["low_confidence_flag"], False)
        self.assertEqual(peer_set["sample_size"], 24)
        # V2.3 keys ABSENT.
        self.assertNotIn("project_class", peer_set)
        self.assertNotIn("use_type", peer_set)

        # Violations preserved as unavailable.
        self.assertFalse(result["violations"]["available"])
        # Lifecycle keys pass through.
        for label in ("inspections", "complaints"):
            self.assertIn(
                "lifecycle_normalized_percentile", result[label],
            )
            self.assertIsNone(
                result[label]["lifecycle_normalized_percentile"],
            )

    def test_synchronous_compute_on_cache_miss_persists_back(self):
        """Cache absent → sync compute path fires. Cohort + classify
        wired via PR #14C (call sites confirmed by test_pr14c_wiring).
        Just pin the persist-back contract here.
        """
        socrata = MockSocrataClient()
        from _pr14b_fixtures import (
            make_cohort_fixture, seed_dob_now_for_bin,
        )
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        seed_dob_now_for_bin(
            socrata, bin="3325703",
            work_type="General Construction",
            filing_reason="Initial Permit",
            job_description="NEW BUILDING 5-STORY RESIDENTIAL 8 UNITS",
        )
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=120,
            bin_prefix="3033041", job_number_prefix="32200",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        socrata.seed(DATASET_PLUTO, [
            {
                "bbl": f"3033042{i:04d}",
                "bin": f"3033041{i:04d}",
                "borough": "BK", "bldgclass": "C1",
                "landuse": "01", "zipcode": "11221", "cd": "304",
                "yearbuilt": "1990", "unitsres": "8",
                "unitstotal": "8", "numfloors": "5",
                "bldgarea": "8000", "lotarea": "2500",
            }
            for i in range(120)
        ])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

        project = {
            "_id": "P2",
            "bbl": "3033040024",
            "nyc_bin": "3325703",
            "borough": "BROOKLYN",
            "dob_project_type": "new_building",
        }
        db = _StubDb(projects=[dict(project)])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        # PR #14B shape in returned result.
        self.assertEqual(
            result["peer_set"].get("dob_project_type"), "new_building",
        )
        # Cache was persisted.
        self.assertGreaterEqual(len(db.projects.update_one_calls), 1)
        # Find the call that wrote peer_stats_cache.
        peer_stats_writes = [
            c for c in db.projects.update_one_calls
            if "peer_stats_cache" in (c["update"].get("$set") or {})
        ]
        self.assertGreaterEqual(len(peer_stats_writes), 1)
        new_cache = peer_stats_writes[-1]["update"]["$set"]["peer_stats_cache"]
        self.assertEqual(new_cache["status"], "ready")
        self.assertEqual(
            new_cache["peer_criteria"].get("schema_version"), "pr14c",
            "Sync-compute path must stamp schema_version per Q4.",
        )

    def test_timeout_returns_zero_peer_marker_with_reason(self):
        socrata = MockSocrataClient()
        project = {"_id": "P3", "bbl": "1000150000"}
        db = _StubDb(projects=[project])

        async def _hang(*_a, **_kw):
            await asyncio.sleep(10)
            return {}

        with patch.object(bl, "compute_peer_stats_full", new=_hang), \
             patch.object(bl, "PEER_STATS_COMPUTE_TIMEOUT_SECONDS", 0.05):
            result = _run(bl.compare_project_to_peers(
                db, project, socrata=socrata,
                now=datetime(2026, 5, 10, tzinfo=timezone.utc),
            ))
        self.assertEqual(result["peer_set"]["sample_size"], 0)
        self.assertEqual(result["peer_set"]["reason"], "timeout")
        self.assertEqual(result["violations"]["project_count"], 0)

    def test_socrata_error_returns_zero_peer_marker_with_reason(self):
        socrata = MockSocrataClient()
        project = {"_id": "P4", "bbl": "1000160000"}
        db = _StubDb(projects=[project])

        async def _raise_query_error(*_a, **_kw):
            raise SocrataQueryError("oops", dataset_id=DATASET_PLUTO)

        with patch.object(bl, "compute_peer_stats_full", new=_raise_query_error):
            result = _run(bl.compare_project_to_peers(
                db, project, socrata=socrata,
                now=datetime(2026, 5, 10, tzinfo=timezone.utc),
            ))
        self.assertEqual(result["peer_set"]["reason"], "socrata_error")


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 4 — status guards on compare_project_to_peers
# ──────────────────────────────────────────────────────────────────


class TestCompareProjectStatusGuards(unittest.TestCase):
    """Pin the pending/failed handling that Commit 4 adds to
    compare_project_to_peers. These guards close a race + a
    quota-burn regression introduced when the async pre-warm
    task started writing status="pending" and status="failed"
    markers to the cache.
    """

    def _make_cache(self, **overrides) -> Dict[str, Any]:
        base = {
            "status": "ready",
            "computed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "last_refreshed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "peer_criteria": {
                "borough": "MANHATTAN",
                "project_class": "O",
                "use_type": "office",
                "tier": "borough_class_use",
                "sample_size": 24,
                "fallback_level": 1,
            },
            "violations":  {"n": 24, "median": 1.0, "p75": 2.0, "p90": 3.0,
                            "project_count": 5, "percentile_rank": 80.0},
            "inspections": {"n": 24, "median": 0.5, "p75": 1.0, "p90": 2.0,
                            "project_count": 2, "percentile_rank": 70.0},
            "complaints":  {"n": 24, "median": 0.0, "p75": 0.5, "p90": 1.0,
                            "project_count": 0, "percentile_rank": 50.0},
        }
        base.update(overrides)
        return base

    def test_pending_status_returns_zero_marker_no_socrata_calls(self):
        """status=pending → background prewarm in flight. Don't
        race it with a sync compute. Return the zero-peer marker
        with reason='pending' and emit zero Socrata calls."""
        socrata = MockSocrataClient()
        cache = self._make_cache(status="pending")
        project = {"_id": "PG1", "peer_stats_cache": cache}
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(result["peer_set"]["sample_size"], 0)
        self.assertEqual(result["peer_set"]["reason"], "pending")
        self.assertEqual(result["violations"]["project_count"], 0)
        # Critical: no Socrata calls. A regression here would
        # mean we race the in-flight prewarm task.
        self.assertEqual(len(socrata.calls), 0)
        # No cache write — we observed pending, didn't compute.
        self.assertEqual(len(db.projects.update_one_calls), 0)

    def test_failed_status_under_24h_returns_zero_marker(self):
        """status=failed + failed_at within 24h → return zero
        marker without retrying. Don't burn Socrata quota on a
        query that just failed."""
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
        # Failed 2 hours ago — well within the 24h TTL.
        failed_at = now - timedelta(hours=2)
        cache = self._make_cache(
            status="failed",
            failed_at=failed_at,
            error_kind="socrata_error",
            error_message="rate limited",
        )
        project = {"_id": "PG2", "peer_stats_cache": cache}
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata, now=now,
        ))
        self.assertEqual(result["peer_set"]["reason"], "failed")
        self.assertEqual(len(socrata.calls), 0)
        self.assertEqual(len(db.projects.update_one_calls), 0)

    def test_failed_status_over_24h_falls_through_to_sync_compute(self):
        """status=failed + failed_at > 24h ago → retry escape
        hatch fires. Permanently-stuck projects shouldn't stay
        broken forever. Verify sync compute runs and writes a
        fresh cache."""
        socrata = MockSocrataClient()
        # Seed a tier-1 PLUTO peer set so compute can complete.
        # Schema-correct (2-letter borough + DOF code) + own-BBL
        # snapshot row for fetch_project_pluto_snapshot.
        socrata.seed(DATASET_PLUTO, [
            {"bbl": f"100250{i:04d}", "borough": "MN",
             "bldgclass": "O4", "landuse": "office"}
            for i in range(25)
        ] + [
            {"bbl": "1002500000", "borough": "MN",
             "bldgclass": "O4", "landuse": "office"},
        ])
        socrata.seed(DATASET_DOB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

        now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
        # Failed 25 hours ago — past the 24h TTL.
        failed_at = now - timedelta(hours=25)
        cache = self._make_cache(
            status="failed",
            failed_at=failed_at,
            error_kind="socrata_error",
        )
        project = {
            "_id": "PG3", "peer_stats_cache": cache,
            "bbl": "1002500000", "borough": "MANHATTAN",
            "use_type": "office",
        }
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata, now=now,
        ))
        # PR #14C: V2.3 ``borough_class_use`` tier vocab retired
        # (Q7). The retry escape hatch's contract is that the
        # status-failed-past-24h project gets a FRESH compute
        # written — verify by checking peer_stats_cache.status =
        # ready was persisted, not zero/failed marker. The exact
        # tier value depends on whether the project's DOB classify
        # + cohort path resolved data; here we don't seed enough
        # cohort-side data, so the tier may be None (empty cohort)
        # — that's still a successful compute, just an
        # unavailable-cohort one.
        self.assertGreater(len(socrata.calls), 0)
        # At least one cache-persist write fired. Note: schema
        # check at the head of compare_project_to_peers may
        # invalidate the seeded "failed" cache via the status-ready
        # gate, but the retry path still runs sync compute, which
        # writes a fresh status="ready" cache.
        self.assertGreaterEqual(len(db.projects.update_one_calls), 1)
        # Find the call that wrote peer_stats_cache.
        peer_writes = [
            c for c in db.projects.update_one_calls
            if "peer_stats_cache" in (c["update"].get("$set") or {})
        ]
        self.assertGreaterEqual(len(peer_writes), 1)
        persisted_cache = peer_writes[-1]["update"]["$set"]["peer_stats_cache"]
        self.assertEqual(persisted_cache["status"], "ready")

    def test_failed_status_with_naive_datetime_normalized_to_utc(self):
        """Defensive: if failed_at is a naive datetime (no
        tzinfo), the guard must still compare correctly by
        normalizing to UTC. Mongo bson sometimes returns naive
        datetimes depending on client config."""
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
        # Naive datetime 2h ago — equivalent UTC; should be
        # within the 24h TTL.
        failed_at_naive = datetime(2026, 5, 10, 10, 0)  # no tzinfo
        cache = self._make_cache(
            status="failed", failed_at=failed_at_naive,
        )
        project = {"_id": "PG4", "peer_stats_cache": cache}
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata, now=now,
        ))
        # Within TTL → zero marker.
        self.assertEqual(result["peer_set"]["reason"], "failed")
        self.assertEqual(len(socrata.calls), 0)

    def test_failed_status_no_failed_at_returns_zero_marker_defensive(self):
        """Malformed cache (status=failed but no failed_at field
        — e.g. a pre-Commit-4 failed marker) → return zero
        marker. Without a timestamp we can't decide whether to
        retry, and the safer default is "don't burn quota until
        an operator looks at it"."""
        socrata = MockSocrataClient()
        cache = self._make_cache(status="failed")  # no failed_at
        cache.pop("failed_at", None)
        project = {"_id": "PG5", "peer_stats_cache": cache}
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(result["peer_set"]["reason"], "failed")
        self.assertEqual(len(socrata.calls), 0)


# ──────────────────────────────────────────────────────────────────
# Cache staleness boundary
# ──────────────────────────────────────────────────────────────────


class TestCacheStalenessLogic(unittest.TestCase):

    def test_fresh_under_14_days(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        cache = {"last_refreshed_at": now - timedelta(days=7)}
        self.assertFalse(bl._is_cache_stale(cache, now=now))

    def test_stale_over_14_days(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        cache = {"last_refreshed_at": now - timedelta(days=15)}
        self.assertTrue(bl._is_cache_stale(cache, now=now))

    def test_at_exact_14_day_boundary_is_fresh(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        cache = {"last_refreshed_at": now - timedelta(days=14)}
        self.assertFalse(bl._is_cache_stale(cache, now=now))

    def test_missing_last_refreshed_at_is_stale(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        self.assertTrue(bl._is_cache_stale({}, now=now))


# ──────────────────────────────────────────────────────────────────
# Package re-exports
# ──────────────────────────────────────────────────────────────────


class TestPackageReExports(unittest.TestCase):

    def test_v23_api_reexported(self):
        from lib import statistical_engine as stat_engine
        # PR #14C: peer_bbls retired per Q7 lock — replaced by
        # compute_cohort_for_project. PR14C_SCHEMA_VERSION added.
        for name in (
            "compare_project_to_peers",
            "compute_peer_stats_full",
            "refresh_peer_stats_incremental",
            "count_own_building_events",
            "PEER_STATS_FRESH_DAYS",
            "PEER_STATS_LOOKBACK_DAYS",
            "PEER_STATS_COMPUTE_TIMEOUT_SECONDS",
            "PR14C_SCHEMA_VERSION",
            "compute_cohort_for_project",
        ):
            self.assertTrue(
                hasattr(stat_engine, name),
                f"missing re-export: {name}",
            )

    def test_v22_aggregator_funcs_removed(self):
        from lib import statistical_engine as stat_engine
        for name in (
            "compute_baseline_for_peer_set",
            "upsert_baseline",
            "run_baseline_aggregator",
        ):
            self.assertFalse(
                hasattr(stat_engine, name),
                f"{name} still exported; should have been removed",
            )


# ──────────────────────────────────────────────────────────────────
# A2 integration — Menahan-fixture produces non-zero own_building
#
# Test 10 of the A2 PR. End-to-end pin: a project doc + dob_logs
# shaped roughly like Menahan (active SWO + recent violations +
# active complaint + failed inspection) feeds recompute_and_persist
# which writes a risk_scores doc whose contributing_factors[group=
# "own_building"].value is > 0.
#
# Uses the new module-level coefficient constants in score.py (C3
# Path 1: OWN_BUILDING_WEIGHT_VIOLATIONS_30D etc.). Before Stage 3
# implementation these constants don't exist → test fails on
# AttributeError when accessed via getattr (caught explicitly so
# the failure message is informative).
# ──────────────────────────────────────────────────────────────────


class TestRecomputePersistMenahanFixture(unittest.TestCase):
    """A2 — Menahan-fixture integration test (test 10)."""

    def test_recompute_persist_produces_nonzero_own_building_for_menahan_fixture(self):
        """Seeds dob_logs with a Menahan-like enforcement shape,
        runs recompute_and_persist, asserts:

          (a) The contributing_factors row for group=='own_building'
              has value > 0.
          (b) The value equals the formula's output using the new
              module-level coefficient constants in score.py:
                v30 * OWN_BUILDING_WEIGHT_VIOLATIONS_30D
              + v90 * OWN_BUILDING_WEIGHT_VIOLATIONS_90D
              + i_failed * OWN_BUILDING_WEIGHT_INSPECTIONS_FAILED_60D
              + open_311 * OWN_BUILDING_WEIGHT_OPEN_COMPLAINTS_30D
              clamped to [0, 100].

        Fixture shape:
          • 3 active violations within 30d  → v30 = 3
          • 2 additional active violations within 90d (but
            outside 30d)                    → v90 = 5  (total in 90d)
          • 1 failed inspection within 60d  → i_failed = 1
          • 1 open (ACTIVE) complaint w/in 30d → open_311 = 1

        Expected own_building (with current constants 8/2/12/4):
          3*8 + 5*2 + 1*12 + 1*4 = 24 + 10 + 12 + 4 = 50.
        Test computes expected dynamically from the constants so a
        future coefficient retune doesn't break this test
        spuriously.
        """
        from lib.statistical_engine import score as sc

        # Verify the new coefficient constants exist (C3 Path 1).
        # On main these don't exist yet → AttributeError with a
        # message that flags this as Stage 3 work.
        weights = {}
        for name in (
            "OWN_BUILDING_WEIGHT_VIOLATIONS_30D",
            "OWN_BUILDING_WEIGHT_VIOLATIONS_90D",
            "OWN_BUILDING_WEIGHT_INSPECTIONS_FAILED_60D",
            "OWN_BUILDING_WEIGHT_OPEN_COMPLAINTS_30D",
        ):
            value = getattr(sc, name, None)
            self.assertIsNotNone(
                value,
                f"score.py missing module-level constant {name!r} — "
                f"A2 Stage 3 must extract the own-building formula "
                f"coefficients per C3 Path 1.",
            )
            weights[name] = value

        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        project_id = "menahan_fixture_project"
        project = {
            "_id": project_id,
            "id": project_id,
            "company_id": "fixture_company",
            "name": "9 Menahan Street",
            "nyc_bin": "3325703",
            "bbl": "3033040024",
            "borough": "BROOKLYN",
            "track_dob_status": True,
            # Pre-staged to a known-good state so the test isolates
            # the own_building factor.
            "peer_stats_cache": {
                "status": "ready",
                "computed_at": now - timedelta(days=1),
                "last_refreshed_at": now - timedelta(days=1),
                "peer_criteria": {
                    # PR #14C: schema_version added so the cache-hit
                    # branch's schema check (Q4 Option B) doesn't
                    # invalidate this fixture and force recompute.
                    # Test isolates own_building math, doesn't care
                    # about peer factor — just needs the cache served
                    # so the rest of recompute_and_persist runs.
                    "schema_version":      "pr14c",
                    "borough":             "BROOKLYN",
                    "dob_project_type":    "new_building",
                    "geography_tier_used": "zip_bldgclass_type",
                    "low_confidence_flag": False,
                    "sample_size":         24,
                    "fallback_level":      1,
                },
                "violations": {
                    "available": False,
                    "unavailable_reason":
                        "bbl_keyed_peer_set_incompatible_with_bin_keyed_dataset",
                    "peer_data_dropped_in_pr": "v2.3-schema-corrections-hotfix",
                },
                "inspections": {
                    "available": True,
                    "n": 24, "median": 0.0, "p75": 0.0, "p90": 0.0,
                    "project_count": 0, "percentile_rank": 50.0,
                },
                "complaints": {
                    "available": True,
                    "n": 24, "median": 0.0, "p75": 0.0, "p90": 0.0,
                    "project_count": 0, "percentile_rank": 50.0,
                },
            },
        }
        db = _StubDb(projects=[project])

        # Seed dob_logs with a Menahan-like shape.
        dob_logs_seed = []
        for i in range(3):
            dob_logs_seed.append(_dob_log(
                project_id=project_id,
                record_type="violation",
                resolution_state="open",
                violation_date=(now - timedelta(days=(5 + i))).strftime("%Y%m%d"),
                raw_dob_id=f"v30:{i}",
            ))
        for i in range(2):
            dob_logs_seed.append(_dob_log(
                project_id=project_id,
                record_type="violation",
                resolution_state="hearing_scheduled",
                violation_date=(now - timedelta(days=(45 + i))).strftime("%Y%m%d"),
                raw_dob_id=f"v90:{i}",
            ))
        dob_logs_seed.append(_dob_log(
            project_id=project_id,
            record_type="inspection",
            severity="Action",
            inspection_date=(now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000"),
            raw_dob_id="i60:0",
        ))
        dob_logs_seed.append(_dob_log(
            project_id=project_id,
            record_type="complaint",
            complaint_status="ACTIVE",
            complaint_date=(now - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S.000"),
            raw_dob_id="c30:0",
        ))
        db.dob_logs.seed(dob_logs_seed)

        # Stub the risk_scores collection (recompute_and_persist
        # writes a doc to it).
        from unittest.mock import MagicMock as _MM
        rs_inserts = []

        class _StubRiskScoresColl:
            async def insert_one(self, doc):
                rs_inserts.append(doc)
                r = _MM(); r.inserted_id = "fake_score_id"
                return r

            async def update_many(self, *_a, **_kw):
                r = _MM(); r.matched_count = 0; r.modified_count = 0
                return r

        db.risk_scores = _StubRiskScoresColl()

        # Run recompute_and_persist with an empty Socrata mock.
        # Prevents real network calls during the trigger-evaluation
        # path that ``recompute_and_persist`` invokes before
        # ``gather_score_inputs`` (per Stage 4 Confirmation 2 —
        # without the mock, the trigger path would attempt real
        # Socrata queries that fail and get swallowed by the
        # try/except in ``recompute_and_persist``, costing ~8s of
        # retry backoff per test run).
        mock_socrata = MockSocrataClient()
        doc = _run(sc.recompute_and_persist(
            db, project, socrata=mock_socrata, now=now,
        ))

        # Find the own_building factor row.
        contributing = doc.get("contributing_factors") or []
        own_row = next(
            (f for f in contributing
             if f.get("group") == "own_building"
             or f.get("name") == "own_building"),
            None,
        )
        self.assertIsNotNone(
            own_row, "no own_building factor in contributing_factors",
        )

        # Expected value computed from the dynamic coefficients.
        # Fixture: v30=3, v90=5, i_failed=1, open_311=1.
        expected = (
            3 * weights["OWN_BUILDING_WEIGHT_VIOLATIONS_30D"]
            + 5 * weights["OWN_BUILDING_WEIGHT_VIOLATIONS_90D"]
            + 1 * weights["OWN_BUILDING_WEIGHT_INSPECTIONS_FAILED_60D"]
            + 1 * weights["OWN_BUILDING_WEIGHT_OPEN_COMPLAINTS_30D"]
        )
        expected = float(max(0.0, min(100.0, expected)))

        actual = float(own_row.get("value") or own_row.get("subscore") or 0.0)
        self.assertGreater(
            actual, 0.0,
            "own_building subscore is 0 — A2 pivot to dob_logs "
            "did not produce non-zero output for Menahan fixture",
        )
        self.assertAlmostEqual(
            actual, expected,
            msg=(
                f"own_building value {actual} != expected {expected} "
                f"(formula: v30=3, v90=5, i_failed=1, open_311=1 with "
                f"weights {weights})"
            ),
        )


# ──────────────────────────────────────────────────────────────────
# PR #14B — cohort-aware peer comparison (3 test classes, 22 tests)
# ──────────────────────────────────────────────────────────────────


# Lazy imports for PR #14B production symbols.
try:
    from lib.statistical_engine.baselines import (  # noqa: E402
        compute_cohort_for_project,
    )
    HAS_COMPUTE_COHORT = True
except ImportError:
    compute_cohort_for_project = None  # type: ignore
    HAS_COMPUTE_COHORT = False

try:
    from lib.statistical_engine.baselines import (  # noqa: E402
        _compute_completion_pct,
        _cohort_duration_median,
    )
    HAS_LIFECYCLE_HELPERS = True
except ImportError:
    _compute_completion_pct = None  # type: ignore
    _cohort_duration_median = None  # type: ignore
    HAS_LIFECYCLE_HELPERS = False


# PR #14B fixture helpers (in tests/_pr14b_fixtures.py).
from _pr14b_fixtures import (  # noqa: E402
    DATASET_BIS_JOB_FILINGS,
    DATASET_C_OF_O_LEGACY,
    DATASET_DOB_PERMITS,
    seed_bis_for_bin,
    seed_c_of_o_for_job,
    seed_dob_now_for_bin,
    make_cohort_fixture,
)


class TestComputeCohortForProject(unittest.TestCase):
    """PR #14B — verify ``compute_cohort_for_project``.

    Per Stage 2.A locked design:
      • 4-tier geography ladder (zip → cd → borough+broader → borough)
      • Sample size N≥100 high confidence, 30≤N<100 low_confidence,
        N<30 fall back to next tier
      • 36mo window primary, expand to 60mo if N<100
      • Completion: C of O Final primary, job_status_x_or_u fallback
      • Per-project_type filter from cohort_config.py
    """

    def _require_compute_cohort(self):
        if not HAS_COMPUTE_COHORT:
            self.fail(
                "lib.statistical_engine.baselines.compute_cohort_for_project "
                "not implemented. Stage 3: add the function that "
                "reads project.dob_project_type, looks up cohort spec, "
                "queries BIS + C of O, applies tolerance bands + "
                "geography ladder."
            )

    def _project_new_building(self, **overrides):
        base = {
            "_id": "P_NB",
            "nyc_bin": "3325703",
            "bbl": "3033040024",
            "borough": "BROOKLYN",
            "address": "100 Main St, BROOKLYN, NY 11221",
            "dob_project_type": "new_building",
            "pluto_snapshot": {
                "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
                "numfloors": 5, "unitsres": 8, "unitstotal": 8,
                "zipcode": "11221", "cd": "304",
            },
        }
        base.update(overrides)
        return base

    def test_new_building_tier_1_happy_path_zip_match(self):
        """Test 29 — 120 NB filings matching tier 1 (zip+bldgclass+type)
        → fires tier 1, no low_confidence flag."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=120,
            bin_prefix="3033040", job_number_prefix="32100",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertEqual(result["tier_used"], "zip_bldgclass_type")
        self.assertEqual(result["fallback_level"], 1)
        self.assertEqual(result["sample_size"], 120)
        self.assertFalse(result["low_confidence_flag"])
        self.assertEqual(len(result["cohort_job_numbers"]), 120)

    def test_major_alt_with_enlargement_uses_a1_filter_first_then_nb_secondary(self):
        """Test 30 — primary A1 cohort < 30; secondary fallback per
        T4 merges in new_building cohort to reach floor."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="major_alt_with_enlargement",
            n_records=25, bin_prefix="3033041", job_number_prefix="32200",
            borough="BROOKLYN", building_class="C1", bis_job_type="A1",
            story_count=5, dwelling_units=8, completed=True,
        )
        make_cohort_fixture(
            socrata, project_type="new_building",
            n_records=200, bin_prefix="3033042", job_number_prefix="32300",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = self._project_new_building(
            _id="P_ALT", dob_project_type="major_alt_with_enlargement",
        )
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertGreaterEqual(result["sample_size"], 30)
        self.assertTrue(
            result["cohort_filter_spec"].get("secondary_fallback_applied"),
        )

    def test_minor_alt_skips_story_units_filters(self):
        """Test 31 — minor_alt does NOT filter on story_count or
        dwelling_units. 150 mixed-story A2/A3 records all qualify."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="minor_alt", n_records=50,
            bin_prefix="3000050", job_number_prefix="32400",
            borough="BROOKLYN", building_class="C1", bis_job_type="A2",
            story_count=2, dwelling_units=2, completed=True,
        )
        make_cohort_fixture(
            socrata, project_type="minor_alt", n_records=50,
            bin_prefix="3000060", job_number_prefix="32500",
            borough="BROOKLYN", building_class="C1", bis_job_type="A3",
            story_count=8, dwelling_units=12, completed=True,
        )
        make_cohort_fixture(
            socrata, project_type="minor_alt", n_records=50,
            bin_prefix="3000070", job_number_prefix="32600",
            borough="BROOKLYN", building_class="C1", bis_job_type="A2",
            story_count=12, dwelling_units=40, completed=True,
        )
        project = self._project_new_building(
            _id="P_MINOR", dob_project_type="minor_alt",
        )
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertEqual(
            result["sample_size"], 150,
            "minor_alt must include all records regardless of story "
            "count per cohort_config (no story_count_band filter)",
        )

    def test_full_demo_uses_demolished_attributes_from_pluto_snapshot(self):
        """Test 32 — full_demo cohort uses pre-demolition bldgclass
        from frozen pluto_snapshot per Risk 7 lock."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="full_demo", n_records=150,
            bin_prefix="3001000", job_number_prefix="32700",
            borough="BROOKLYN", building_class="A2", bis_job_type="DM",
            story_count=2, dwelling_units=2, completed=True,
        )
        project = self._project_new_building(
            _id="P_DEMO", dob_project_type="full_demo",
            pluto_snapshot={
                "bbl": "3033040024", "borough": "BK",
                "bldgclass": "A2",  # frozen pre-demolition class
                "numfloors": 2, "unitsres": 2, "unitstotal": 2,
                "zipcode": "11221", "cd": "304",
            },
        )
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertGreater(result["sample_size"], 100)
        self.assertEqual(
            result["cohort_filter_spec"].get("building_class"), "A2",
        )

    def test_geography_ladder_falls_through_tier_1_to_tier_2_when_zip_below_floor(self):
        """Test 33 — Tier 1 (zip) returns 20 below floor. Ladder
        advances to tier 2 (cd)."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=20,
            bin_prefix="3003000", job_number_prefix="32800",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        # Stage 3's ladder may advance OR may still report zip if
        # secondary fixtures absent. Accept either as in-bounds —
        # the durable assertion is that the result is internally
        # consistent.
        self.assertIn(
            result["tier_used"],
            ("cd_bldgclass_type", "borough_broader_type", "borough_type"),
            "Sub-30 sample at tier 1 must advance ladder. Got: "
            + repr(result["tier_used"]),
        )

    def test_geography_ladder_final_fallback_to_borough_only(self):
        """Test 34 — Tiers 1-3 all fail; tier 4 (borough+type)
        returns 5000 (project's bldgclass C1, cohort R6)."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=5000,
            bin_prefix="3099000", job_number_prefix="32900",
            borough="BROOKLYN", building_class="R6",
            bis_job_type="NB", story_count=5, dwelling_units=8,
            completed=True,
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertIn(
            result["fallback_level"], (3, 4),
            "Ladder must fall to tier 3 or 4 when narrower tiers "
            "fail. Got fallback_level=" + str(result["fallback_level"]),
        )

    def test_sample_size_above_100_no_low_confidence_flag(self):
        """Test 35 — N=200 above 100 high-confidence threshold."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=200,
            bin_prefix="3033040", job_number_prefix="33000",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertFalse(result["low_confidence_flag"])

    def test_sample_size_below_100_above_30_sets_low_confidence_flag(self):
        """Test 36 — N=50, between 30 floor + 100 high-confidence."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=50,
            bin_prefix="3033040", job_number_prefix="33100",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertEqual(result["sample_size"], 50)
        self.assertTrue(result["low_confidence_flag"])

    def test_sample_size_below_30_falls_back_to_next_tier(self):
        """Test 37 — N=20 at tier 1 → fallback_level ≥ 2."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=20,
            bin_prefix="3033040", job_number_prefix="33200",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertGreaterEqual(result["fallback_level"], 2)

    def test_completion_filter_uses_c_of_o_final_primary(self):
        """Test 38 — C of O Final present → completion_method =
        c_of_o_final."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=150,
            bin_prefix="3033040", job_number_prefix="33300",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
            c_o_issue_type="Final",
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertEqual(result["completion_method"], "c_of_o_final")

    def test_completion_filter_falls_back_to_job_status_x_or_u(self):
        """Test 39 — Risk 6 key lock: when C of O empty, completion
        filter falls back to job_status_x_or_u."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=150,
            bin_prefix="3033040", job_number_prefix="33400",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8,
            completed=False,  # No C of O written
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertEqual(
            result["completion_method"], "job_status_x_or_u",
            "Fallback completion_method per Risk 6 key lock",
        )

    def test_window_expands_from_36mo_to_60mo_when_under_100(self):
        """Test 40 — 36mo cohort <100; 60mo cohort >100. Window
        expands to 60mo."""
        self._require_compute_cohort()
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=60,
            bin_prefix="3033040", job_number_prefix="33500",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
            pre__filing_date="2023-06-15",
        )
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=190,
            bin_prefix="3033050", job_number_prefix="33600",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
            pre__filing_date="2021-08-15",
        )
        project = self._project_new_building()
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertEqual(
            result["window_months"], 60,
            "Window must expand from 36mo to 60mo when 36mo N<100",
        )


class TestLifecycleNormalization(unittest.TestCase):
    """PR #14B — lifecycle-stage normalization helpers.

    T_0 = permit issuance, T_end = completion. Active project's
    completion_pct compared against cohort median to produce
    lifecycle_normalized_percentile.
    """

    def _require_lifecycle_helpers(self):
        if not HAS_LIFECYCLE_HELPERS:
            self.fail(
                "lib.statistical_engine.baselines._compute_completion_pct "
                "or _cohort_duration_median not implemented. "
                "Stage 3: add module-level helpers."
            )

    def test_completion_pct_compute_from_t0_and_expected_duration(self):
        """Test 41 — (now − t0) / expected_duration = 0.5."""
        self._require_lifecycle_helpers()
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        pct = _compute_completion_pct(t0, now, expected_duration_days=730)
        self.assertAlmostEqual(pct, 0.5, places=3)

    def test_cohort_duration_median_when_samples_exist(self):
        """Test 42 — median of cohort durations in days.
        5 records with c_o_issue_date − permit_issue_date deltas
        ≈[200, 400, 600, 800, 1000] days → median ≈600."""
        self._require_lifecycle_helpers()
        cohort_records = [
            {"permit_issue_date": "2022-01-01", "c_o_issue_date": "2022-07-20"},
            {"permit_issue_date": "2022-01-01", "c_o_issue_date": "2023-02-05"},
            {"permit_issue_date": "2022-01-01", "c_o_issue_date": "2023-08-24"},
            {"permit_issue_date": "2022-01-01", "c_o_issue_date": "2024-03-10"},
            {"permit_issue_date": "2022-01-01", "c_o_issue_date": "2024-09-27"},
        ]
        median_days = _cohort_duration_median(cohort_records)
        self.assertGreaterEqual(median_days, 599)
        self.assertLessEqual(median_days, 601)

    def test_lifecycle_normalized_percentile_output_shape(self):
        """Test 43 — compute_cohort_for_project surfaces
        cohort_median_duration_days for downstream lifecycle math."""
        if not HAS_COMPUTE_COHORT:
            self.fail("compute_cohort_for_project not implemented.")
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=150,
            bin_prefix="3033040", job_number_prefix="33700",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = {
            "_id": "P_LC", "nyc_bin": "3325703", "bbl": "3033040024",
            "borough": "BROOKLYN", "dob_project_type": "new_building",
            "pluto_snapshot": {
                "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
                "numfloors": 5, "unitsres": 8, "unitstotal": 8,
                "zipcode": "11221", "cd": "304",
            },
        }
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertIn(
            "cohort_median_duration_days", result,
            "Cohort result must carry median duration for downstream "
            "lifecycle math. Keys: " + repr(sorted(result.keys())),
        )

    def test_milestone_snap_to_superstructure_when_permit_observed(self):
        """Test 44 — Risk 8 mapping: Structural permit observed →
        completion_pct snaps to 0.40."""
        if not HAS_COMPUTE_COHORT:
            self.fail("compute_cohort_for_project not implemented.")
        socrata = MockSocrataClient()
        seed_dob_now_for_bin(
            socrata, bin="3325703",
            work_type="Structural",
            filing_reason="Initial Permit",
            permit_status="Issued",
        )
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=150,
            bin_prefix="3033040", job_number_prefix="33800",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = {
            "_id": "P_MILESTONE", "nyc_bin": "3325703",
            "bbl": "3033040024", "borough": "BROOKLYN",
            "dob_project_type": "new_building",
            "pluto_snapshot": {
                "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
                "numfloors": 5, "unitsres": 8, "unitstotal": 8,
                "zipcode": "11221", "cd": "304",
            },
        }
        result = _run(compute_cohort_for_project(socrata, project))
        active = result.get("active_project") or {}
        self.assertAlmostEqual(
            active.get("completion_pct", 0.0), 0.40, places=2,
            msg=(
                "Structural permit must snap completion_pct to 0.40 "
                "per Risk 8 milestone mapping. Got: "
                + repr(active.get("completion_pct"))
            ),
        )

    def test_skip_lifecycle_when_cohort_empty(self):
        """Test 45 — T2.a fallback: empty cohort → skip lifecycle,
        emit None + 'empty_cohort' reason."""
        if not HAS_COMPUTE_COHORT:
            self.fail("compute_cohort_for_project not implemented.")
        socrata = MockSocrataClient()
        socrata.seed(DATASET_BIS_JOB_FILINGS, [])
        socrata.seed(DATASET_C_OF_O_LEGACY, [])
        project = {
            "_id": "P_EMPTY", "nyc_bin": "1111111",
            "bbl": "1001110000", "borough": "MANHATTAN",
            "dob_project_type": "new_building",
            "pluto_snapshot": {
                "bbl": "1001110000", "borough": "MN", "bldgclass": "C1",
                "numfloors": 5, "unitsres": 8, "unitstotal": 8,
                "zipcode": "10044", "cd": "108",
            },
        }
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertEqual(result.get("sample_size"), 0)
        self.assertIsNone(result.get("cohort_median_duration_days"))
        self.assertEqual(
            result.get("lifecycle_skip_reason"), "empty_cohort",
        )

    def test_skip_lifecycle_when_cohort_duration_data_missing(self):
        """Test 46 — cohort has 50 BBLs but no C of O Final issue
        dates → no_duration_data reason."""
        if not HAS_COMPUTE_COHORT:
            self.fail("compute_cohort_for_project not implemented.")
        socrata = MockSocrataClient()
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=50,
            bin_prefix="3033040", job_number_prefix="33900",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8,
            completed=False,
        )
        project = {
            "_id": "P_NODUR", "nyc_bin": "3325703",
            "bbl": "3033040024", "borough": "BROOKLYN",
            "dob_project_type": "new_building",
            "pluto_snapshot": {
                "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
                "numfloors": 5, "unitsres": 8, "unitstotal": 8,
                "zipcode": "11221", "cd": "304",
            },
        }
        result = _run(compute_cohort_for_project(socrata, project))
        self.assertIsNone(result.get("cohort_median_duration_days"))
        self.assertEqual(
            result.get("lifecycle_skip_reason"), "no_duration_data",
        )


class TestPlutoSelectExtensionPR14B(unittest.TestCase):
    """PR #14B PLUTO SELECT extension.

    PR #14 added zipcode. PR #14B adds cd, yearbuilt, unitsres,
    unitstotal, numfloors, bldgarea, lotarea (7 new fields).
    """

    def test_pluto_snapshot_includes_new_fields_after_pr14b(self):
        """Test 47 — fresh PLUTO fetch surfaces all 7 PR #14B fields."""
        socrata = MockSocrataClient()
        project_bbl = "3033040024"
        socrata.seed(DATASET_PLUTO, [{
            "bbl": project_bbl, "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        snapshot = _run(bl.fetch_project_pluto_snapshot(
            socrata, {"bbl": project_bbl},
        ))
        self.assertIsNotNone(snapshot)
        for field in (
            "cd", "yearbuilt", "unitsres", "unitstotal",
            "numfloors", "bldgarea", "lotarea",
        ):
            self.assertIn(
                field, snapshot,
                f"PLUTO snapshot missing PR #14B field {field!r}. "
                f"Stage 3: add to SELECT clause in "
                f"baselines.fetch_project_pluto_snapshot.",
            )

    def test_pluto_select_clause_contains_all_pr14b_fields(self):
        """Test 48 — actual $select clause has all 14 fields."""
        socrata = MockSocrataClient()
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        _run(bl.fetch_project_pluto_snapshot(
            socrata, {"bbl": "3033040024"},
        ))
        pluto_calls = [c for c in socrata.calls if c[0] == DATASET_PLUTO]
        self.assertGreaterEqual(len(pluto_calls), 1)
        _, kwargs = pluto_calls[0]
        select_set = set(kwargs.get("select") or [])
        for required in (
            "bbl", "borough", "bldgclass", "landuse", "block", "lot",
            "zipcode", "cd", "yearbuilt", "unitsres", "unitstotal",
            "numfloors", "bldgarea", "lotarea",
        ):
            self.assertIn(
                required, select_set,
                f"PLUTO SELECT missing {required!r}. Got: "
                + repr(sorted(select_set)),
            )

    def test_lazy_pluto_refresh_when_existing_snapshot_lacks_new_fields(self):
        """Test 49 — pre-PR-14B snapshot triggers lazy re-query."""
        if not HAS_COMPUTE_COHORT:
            self.fail("compute_cohort_for_project not implemented.")
        socrata = MockSocrataClient()
        legacy_snapshot = {
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221",
            # Missing: cd, yearbuilt, unitsres, unitstotal, numfloors,
            # bldgarea, lotarea
        }
        socrata.seed(DATASET_PLUTO, [{
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": "8", "unitstotal": "8", "numfloors": "5",
            "bldgarea": "8038", "lotarea": "2500",
        }])
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=120,
            bin_prefix="3033040", job_number_prefix="34000",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = {
            "_id": "P_LAZY", "nyc_bin": "3325703",
            "bbl": "3033040024", "borough": "BROOKLYN",
            "dob_project_type": "new_building",
            "pluto_snapshot": legacy_snapshot,
        }
        _run(compute_cohort_for_project(socrata, project))
        snapshot = project.get("pluto_snapshot")
        self.assertIn("cd", snapshot)
        self.assertIn("numfloors", snapshot)

    def test_idempotent_refresh_no_unnecessary_query_when_all_fields_present(self):
        """Test 50 — complete snapshot → no PLUTO query issued."""
        if not HAS_COMPUTE_COHORT:
            self.fail("compute_cohort_for_project not implemented.")
        socrata = MockSocrataClient()
        complete_snapshot = {
            "bbl": "3033040024", "borough": "BK", "bldgclass": "C1",
            "landuse": "01", "block": "3040", "lot": "24",
            "zipcode": "11221", "cd": "304", "yearbuilt": "1925",
            "unitsres": 8, "unitstotal": 8, "numfloors": 5,
            "bldgarea": 8038, "lotarea": 2500,
        }
        make_cohort_fixture(
            socrata, project_type="new_building", n_records=120,
            bin_prefix="3033040", job_number_prefix="34100",
            borough="BROOKLYN", building_class="C1", bis_job_type="NB",
            story_count=5, dwelling_units=8, completed=True,
        )
        project = {
            "_id": "P_IDEM", "nyc_bin": "3325703",
            "bbl": "3033040024", "borough": "BROOKLYN",
            "dob_project_type": "new_building",
            "pluto_snapshot": dict(complete_snapshot),
        }
        _run(compute_cohort_for_project(socrata, project))
        pluto_calls = [c for c in socrata.calls if c[0] == DATASET_PLUTO]
        self.assertEqual(
            len(pluto_calls), 0,
            f"Idempotent path issued {len(pluto_calls)} PLUTO "
            f"query/queries; expected 0 (snapshot is complete).",
        )


if __name__ == "__main__":
    unittest.main()
