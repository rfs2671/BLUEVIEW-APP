"""Phase V2.3 — Lazy peer-comparison engine tests.

Replaces test_v2_2_baselines.py. V2.2 mocked the local Mongo
mirror; V2.3 mocks the SocrataClient (see tests/_socrata_mock.py).
Pins every contract the V2.3 rewrite preserves + the new
peer_stats_cache lifecycle.

  • Peer-key extraction from project doc (pure, untouched).
  • Fallback ladder: full → drop use_type → drop class → citywide
    (rewritten to lazy PLUTO queries via MockSocrataClient).
  • SoQL helpers (_soql_quote / _soql_in / _iso_z) produce
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


class _StubDb:
    def __init__(self, projects=None):
        self.projects = _StubProjectsColl(projects)


# ──────────────────────────────────────────────────────────────────
# Peer-set key (pure, no I/O)
# ──────────────────────────────────────────────────────────────────


class TestPeerKey(unittest.TestCase):

    def test_uses_explicit_borough(self):
        key = bl._project_peer_key({
            "borough": "MANHATTAN",
            "project_class": "major_b",
            "use_type": "residential",
        })
        self.assertEqual(key["borough"], "MANHATTAN")
        self.assertEqual(key["project_class"], "major_b")
        self.assertEqual(key["use_type"], "residential")

    def test_falls_back_to_bbl_borough(self):
        key = bl._project_peer_key({"bbl": "1001234567"})
        self.assertEqual(key["borough"], "MANHATTAN")
        self.assertEqual(key["project_class"], "regular")

    def test_falls_back_to_landuse_for_use_type(self):
        key = bl._project_peer_key({
            "borough": "QUEENS", "landuse": "commercial",
        })
        self.assertEqual(key["use_type"], "commercial")

    def test_borough_unknown_when_no_bbl(self):
        key = bl._project_peer_key({})
        self.assertIsNone(key["borough"])

    def test_borough_decoded_for_each_code(self):
        cases = [
            ("1", "MANHATTAN"), ("2", "BRONX"), ("3", "BROOKLYN"),
            ("4", "QUEENS"), ("5", "STATEN ISLAND"),
        ]
        for code, name in cases:
            key = bl._project_peer_key({"bbl": f"{code}001234567"})
            self.assertEqual(key["borough"], name, f"code {code}")


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

    def test_iso_z_format(self):
        dt = datetime(2026, 5, 8, 12, 30, 45, tzinfo=timezone.utc)
        self.assertEqual(bl._iso_z(dt), "2026-05-08T12:30:45")


# ──────────────────────────────────────────────────────────────────
# Peer fallback ladder (lazy PLUTO via mock)
# ──────────────────────────────────────────────────────────────────


def _pluto_row(bbl_, borough, bldgclass=None, landuse=None):
    d = {"bbl": bbl_, "borough": borough}
    if bldgclass: d["bldgclass"] = bldgclass
    if landuse:   d["landuse"] = landuse
    return d


class TestFallbackLadder(unittest.TestCase):

    def test_tier_1_full_match(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_PLUTO, [
            _pluto_row(f"100000{i:04d}", "MANHATTAN", "major_b", "residential")
            for i in range(1, 26)
        ])
        proj = {"borough": "MANHATTAN", "project_class": "major_b",
                "use_type": "residential"}
        bbls, meta = _run(bl.peer_bbls(socrata, proj))
        self.assertEqual(len(bbls), 25)
        self.assertEqual(meta["tier"], "borough_class_use")
        self.assertEqual(meta["sample_size"], 25)

    def test_tier_2_drop_use_type(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_PLUTO, [
            _pluto_row(f"100001{i:04d}", "MANHATTAN", "major_b", "residential")
            for i in range(5)
        ] + [
            _pluto_row(f"100002{i:04d}", "MANHATTAN", "major_b", "commercial")
            for i in range(25)
        ])
        proj = {"borough": "MANHATTAN", "project_class": "major_b",
                "use_type": "residential"}
        bbls, meta = _run(bl.peer_bbls(socrata, proj))
        self.assertEqual(meta["tier"], "borough_class")
        self.assertEqual(meta["sample_size"], 30)

    def test_tier_3_drop_class(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_PLUTO, [
            _pluto_row(f"400003{i:04d}", "QUEENS", "regular", "residential")
            for i in range(2)
        ] + [
            _pluto_row(f"400004{i:04d}", "QUEENS", "major_a", "industrial")
            for i in range(2)
        ] + [
            _pluto_row(f"400005{i:04d}", "QUEENS", "regular", "office")
            for i in range(25)
        ])
        proj = {"borough": "QUEENS", "project_class": "major_b",
                "use_type": "school"}
        bbls, meta = _run(bl.peer_bbls(socrata, proj))
        self.assertEqual(meta["tier"], "borough")
        self.assertGreaterEqual(meta["sample_size"], 20)

    def test_tier_4_citywide(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_PLUTO, [
            _pluto_row(f"500006{i:04d}", "STATEN ISLAND") for i in range(5)
        ] + [
            _pluto_row(f"100007{i:04d}", "MANHATTAN") for i in range(15)
        ])
        proj = {"borough": "BRONX"}
        bbls, meta = _run(bl.peer_bbls(socrata, proj))
        self.assertEqual(meta["tier"], "citywide")
        self.assertEqual(meta["sample_size"], 20)

    def test_pluto_bbl_decimal_suffix_stripped(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_PLUTO, [
            {"bbl": f"100008{i:04d}.00000000", "borough": "MANHATTAN",
             "bldgclass": "O", "landuse": "office"}
            for i in range(20)
        ])
        proj = {"borough": "MANHATTAN", "project_class": "O",
                "use_type": "office"}
        bbls, _meta = _run(bl.peer_bbls(socrata, proj))
        for b in bbls:
            self.assertNotIn(".", b, f"BBL {b!r} carries .0 suffix")


# ──────────────────────────────────────────────────────────────────
# Per-BBL event counts (lazy Socrata)
# ──────────────────────────────────────────────────────────────────


class TestCountEventsForBblsSocrata(unittest.TestCase):

    def test_includes_zero_count_bbls(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_VIOLATIONS, [
            {"bbl": "1008470001", "issue_date": "2026-04-01T00:00:00"},
            {"bbl": "1008470001", "issue_date": "2026-04-02T00:00:00"},
            {"bbl": "1008470002", "issue_date": "2026-04-03T00:00:00"},
        ])
        counts = _run(bl._count_events_for_bbls_socrata(
            socrata, DATASET_DOB_VIOLATIONS,
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
        n_total = bl.SOQL_IN_CHUNK_SIZE + 50
        bbls = [f"100100{i:04d}" for i in range(n_total)]
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_VIOLATIONS, [
            {"bbl": b, "issue_date": "2026-04-01T00:00:00"} for b in bbls
        ])
        counts = _run(bl._count_events_for_bbls_socrata(
            socrata, DATASET_DOB_VIOLATIONS, bbls,
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        self.assertEqual(len(counts), n_total)
        self.assertTrue(all(v == 1 for v in counts.values()))
        v_calls = [c for c in socrata.calls if c[0] == DATASET_DOB_VIOLATIONS]
        self.assertGreater(len(v_calls), 1)


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

    def _seed_full_dataset(self, socrata, *, peer_bbls, project_bbl,
                           v_per_bbl, project_v):
        socrata.seed(DATASET_PLUTO, [
            {"bbl": b, "borough": "MANHATTAN", "bldgclass": "O",
             "landuse": "office"}
            for b in peer_bbls
        ])
        # Project events.
        socrata.seed(DATASET_DOB_VIOLATIONS, [
            {"bbl": project_bbl, "issue_date": "2025-06-01T00:00:00"}
            for _ in range(project_v)
        ])
        # Peer events.
        for b in peer_bbls:
            if b == project_bbl:
                continue
            socrata.seed(DATASET_DOB_VIOLATIONS, [
                {"bbl": b, "issue_date": "2025-06-01T00:00:00"}
                for _ in range(v_per_bbl)
            ])
        # Empty inspections + complaints to satisfy gather pattern.
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])

    def test_returns_documented_shape(self):
        socrata = MockSocrataClient()
        peer_set = [f"100010{i:04d}" for i in range(25)]
        self._seed_full_dataset(
            socrata, peer_bbls=peer_set,
            project_bbl="1000100000", v_per_bbl=1, project_v=10,
        )
        cache = _run(bl.compute_peer_stats_full(
            socrata,
            {"bbl": "1000100000", "borough": "MANHATTAN",
             "project_class": "O", "use_type": "office"},
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(cache["status"], "ready")
        self.assertIn("computed_at", cache)
        self.assertIn("last_refreshed_at", cache)
        self.assertEqual(cache["computed_at"], cache["last_refreshed_at"])
        self.assertEqual(cache["peer_criteria"]["fallback_level"], 1)
        self.assertEqual(cache["peer_criteria"]["tier"], "borough_class_use")
        self.assertEqual(cache["peer_criteria"]["sample_size"], 24)
        self.assertIn("violations", cache)
        self.assertIn("inspections", cache)
        self.assertIn("complaints", cache)
        self.assertEqual(cache["violations"]["project_count"], 10)

    def test_excludes_project_own_bbl_from_peer_summary(self):
        socrata = MockSocrataClient()
        peer_set = [f"100011{i:04d}" for i in range(25)]
        self._seed_full_dataset(
            socrata, peer_bbls=peer_set,
            project_bbl="1000110000", v_per_bbl=1, project_v=50,
        )
        cache = _run(bl.compute_peer_stats_full(
            socrata,
            {"bbl": "1000110000", "borough": "MANHATTAN",
             "project_class": "O", "use_type": "office"},
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(cache["violations"]["project_count"], 50)
        self.assertEqual(cache["violations"]["median"], 1.0)
        self.assertEqual(cache["violations"]["n"], 24)
        self.assertAlmostEqual(
            cache["violations"]["percentile_rank"], 100.0,
        )


# ──────────────────────────────────────────────────────────────────
# refresh_peer_stats_incremental
# ──────────────────────────────────────────────────────────────────


class TestRefreshPeerStatsIncremental(unittest.TestCase):

    def test_falls_back_to_full_compute_on_empty_cache(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_PLUTO, [
            {"bbl": f"100012{i:04d}", "borough": "MANHATTAN",
             "bldgclass": "O", "landuse": "office"}
            for i in range(25)
        ])
        socrata.seed(DATASET_DOB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])
        project = {
            "bbl": "1000120000", "borough": "MANHATTAN",
            "project_class": "O", "use_type": "office",
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
            "project_class": "O", "use_type": "office",
            "peer_stats_cache": {
                "computed_at": old_computed_at,
                "last_refreshed_at": old_last_refreshed,
                "status": "ready",
                "peer_criteria": {
                    "borough": "MANHATTAN",
                    "project_class": "O", "use_type": "office",
                    "tier": "borough_class_use",
                    "bbl": "1000130000",
                    "sample_size": len(peer_set) - 1,
                    "fallback_level": 1,
                    "peer_bbl_list": peer_set,
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
# count_own_building_events
# ──────────────────────────────────────────────────────────────────


class TestCountOwnBuildingEvents(unittest.TestCase):

    def test_empty_bin_returns_all_zeros(self):
        socrata = MockSocrataClient()
        out = _run(bl.count_own_building_events(socrata, bin_=None))
        self.assertEqual(out, {
            "violations_30d": 0, "violations_90d": 0,
            "inspections_failed_60d": 0, "open_complaints_30d": 0,
        })

    def test_violations_split_into_30d_and_90d_buckets(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_VIOLATIONS, [
            {"bin": "1234567", "issue_date":
                (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S")},
            {"bin": "1234567", "issue_date":
                (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")},
            {"bin": "1234567", "issue_date":
                (now - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%S")},
            {"bin": "1234567", "issue_date":
                (now - timedelta(days=80)).strftime("%Y-%m-%dT%H:%M:%S")},
        ])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])
        out = _run(bl.count_own_building_events(
            socrata, bin_="1234567", now=now,
        ))
        self.assertEqual(out["violations_30d"], 2)
        self.assertEqual(out["violations_90d"], 4)

    def test_failed_inspections_substring_match(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [
            {"bin": "1234567",
             "inspection_date": (now - timedelta(days=10)).strftime(
                 "%Y-%m-%dT%H:%M:%S"),
             "result": "Failed - Reinspect"},
            {"bin": "1234567",
             "inspection_date": (now - timedelta(days=20)).strftime(
                 "%Y-%m-%dT%H:%M:%S"),
             "result": "Passed"},
            {"bin": "1234567",
             "inspection_date": (now - timedelta(days=30)).strftime(
                 "%Y-%m-%dT%H:%M:%S"),
             "result": "Violation issued"},
        ])
        socrata.seed(DATASET_COMPLAINTS_311, [])
        out = _run(bl.count_own_building_events(
            socrata, bin_="1234567", now=now,
        ))
        self.assertEqual(out["inspections_failed_60d"], 2)

    def test_open_complaints_excludes_closed(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [
            {"bin": "1234567",
             "created_date": (now - timedelta(days=5)).strftime(
                 "%Y-%m-%dT%H:%M:%S"),
             "status": "Open"},
            {"bin": "1234567",
             "created_date": (now - timedelta(days=10)).strftime(
                 "%Y-%m-%dT%H:%M:%S"),
             "status": "Closed"},
            {"bin": "1234567",
             "created_date": (now - timedelta(days=15)).strftime(
                 "%Y-%m-%dT%H:%M:%S"),
             "status": "In Progress"},
        ])
        out = _run(bl.count_own_building_events(
            socrata, bin_="1234567", now=now,
        ))
        self.assertEqual(out["open_complaints_30d"], 2)


# ──────────────────────────────────────────────────────────────────
# compare_project_to_peers — cache-aware
# ──────────────────────────────────────────────────────────────────


class TestCompareProjectToPeersCacheAware(unittest.TestCase):

    def test_returns_cached_when_ready(self):
        socrata = MockSocrataClient()
        cache = {
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
            "violations": {"n": 24, "median": 1.0, "p75": 2.0, "p90": 3.0,
                           "project_count": 5, "percentile_rank": 80.0},
            "inspections": {"n": 24, "median": 0.5, "p75": 1.0, "p90": 2.0,
                            "project_count": 2, "percentile_rank": 70.0},
            "complaints": {"n": 24, "median": 0.0, "p75": 0.5, "p90": 1.0,
                           "project_count": 0, "percentile_rank": 50.0},
        }
        project = {"_id": "P1", "peer_stats_cache": cache}
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(result["peer_set"]["sample_size"], 24)
        self.assertEqual(result["violations"]["project_count"], 5)
        self.assertEqual(result["violations"]["percentile_rank"], 80.0)
        # Hot path: no Socrata calls.
        self.assertEqual(len(socrata.calls), 0)

        # Strict shape parity with V2.2: top-level + each dataset
        # sub-dict + peer_set for tier 1 must have EXACTLY these
        # key sets. A regression that adds or drops a field
        # silently breaks score.py's peer-subscore math.
        self.assertSetEqual(
            set(result.keys()),
            {"peer_set", "violations", "inspections", "complaints"},
        )
        per_dataset_keys = {
            "project_count", "peer_median", "peer_p75", "peer_p90",
            "percentile_rank", "peer_sample_size",
        }
        for label in ("violations", "inspections", "complaints"):
            self.assertSetEqual(
                set(result[label].keys()), per_dataset_keys,
                f"{label} sub-dict shape diverged from V2.2",
            )
        # Tier 1 peer_set carries all five keys (the V2.2 tier-1
        # baseline emission from peer_bbls()).
        self.assertSetEqual(
            set(result["peer_set"].keys()),
            {"tier", "sample_size", "borough", "project_class", "use_type"},
        )
        # Tier value remains the V2.2 string, not the int level.
        self.assertEqual(result["peer_set"]["tier"], "borough_class_use")

    def test_cached_return_shape_tier_3(self):
        """Tier-3 (borough-only) fallback: V2.2 ``peer_bbls()``
        emitted only ``{tier, borough, sample_size}`` — no
        ``project_class``, no ``use_type``. The V2.3 cache-hit
        path must mirror that exactly so consumers (including
        the FE drawer) don't see phantom None-valued fields."""
        socrata = MockSocrataClient()
        cache = {
            "status": "ready",
            "computed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "last_refreshed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "peer_criteria": {
                "borough":        "BRONX",
                "project_class":  "X",      # cache stores it, but
                "use_type":       "y",      # tier-3 must NOT emit
                "tier":           "borough",
                "sample_size":    35,
                "fallback_level": 3,
            },
            "violations":  {"n": 35, "median": 0.0, "p75": 1.0, "p90": 2.0,
                            "project_count": 0, "percentile_rank": 50.0},
            "inspections": {"n": 35, "median": 0.0, "p75": 0.0, "p90": 1.0,
                            "project_count": 0, "percentile_rank": 50.0},
            "complaints":  {"n": 35, "median": 0.0, "p75": 0.0, "p90": 0.0,
                            "project_count": 0, "percentile_rank": 50.0},
        }
        project = {"_id": "P_T3", "peer_stats_cache": cache}
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(len(socrata.calls), 0)
        # Exact tier-3 peer_set key set — no project_class, no use_type.
        self.assertSetEqual(
            set(result["peer_set"].keys()),
            {"tier", "sample_size", "borough"},
        )
        self.assertEqual(result["peer_set"]["tier"], "borough")
        self.assertEqual(result["peer_set"]["borough"], "BRONX")
        self.assertEqual(result["peer_set"]["sample_size"], 35)
        self.assertNotIn("project_class", result["peer_set"])
        self.assertNotIn("use_type", result["peer_set"])

    def test_cached_return_shape_tier_4(self):
        """Tier-4 (citywide) fallback: V2.2 ``peer_bbls()``
        emitted only ``{tier, sample_size}`` — no borough,
        no project_class, no use_type."""
        socrata = MockSocrataClient()
        cache = {
            "status": "ready",
            "computed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "last_refreshed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "peer_criteria": {
                "borough":        "QUEENS",  # cache stores them, but
                "project_class":  "X",       # tier-4 must NOT emit
                "use_type":       "y",       # any of these three.
                "tier":           "citywide",
                "sample_size":    1200,
                "fallback_level": 4,
            },
            "violations":  {"n": 1200, "median": 0.0, "p75": 1.0, "p90": 2.0,
                            "project_count": 0, "percentile_rank": 50.0},
            "inspections": {"n": 1200, "median": 0.0, "p75": 0.0, "p90": 1.0,
                            "project_count": 0, "percentile_rank": 50.0},
            "complaints":  {"n": 1200, "median": 0.0, "p75": 0.0, "p90": 0.0,
                            "project_count": 0, "percentile_rank": 50.0},
        }
        project = {"_id": "P_T4", "peer_stats_cache": cache}
        db = _StubDb(projects=[project])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(len(socrata.calls), 0)
        # Exact tier-4 peer_set key set — only tier + sample_size.
        self.assertSetEqual(
            set(result["peer_set"].keys()),
            {"tier", "sample_size"},
        )
        self.assertEqual(result["peer_set"]["tier"], "citywide")
        self.assertEqual(result["peer_set"]["sample_size"], 1200)
        self.assertNotIn("borough", result["peer_set"])
        self.assertNotIn("project_class", result["peer_set"])
        self.assertNotIn("use_type", result["peer_set"])

    def test_synchronous_compute_on_cache_miss_persists_back(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_PLUTO, [
            {"bbl": f"100014{i:04d}", "borough": "MANHATTAN",
             "bldgclass": "O", "landuse": "office"}
            for i in range(25)
        ])
        socrata.seed(DATASET_DOB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_COMPLAINTS_311, [])
        project = {
            "_id": "P2", "bbl": "1000140000", "borough": "MANHATTAN",
            "project_class": "O", "use_type": "office",
        }
        db = _StubDb(projects=[dict(project)])

        result = _run(bl.compare_project_to_peers(
            db, project, socrata=socrata,
            now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        self.assertEqual(result["peer_set"]["tier"], "borough_class_use")
        self.assertIn("violations", result)
        self.assertEqual(len(db.projects.update_one_calls), 1)
        persisted_set = db.projects.update_one_calls[0]["update"]["$set"]
        self.assertIn("peer_stats_cache", persisted_set)
        new_cache = persisted_set["peer_stats_cache"]
        self.assertEqual(new_cache["status"], "ready")

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
        for name in (
            "peer_bbls",
            "compare_project_to_peers",
            "compute_peer_stats_full",
            "refresh_peer_stats_incremental",
            "count_own_building_events",
            "PEER_STATS_FRESH_DAYS",
            "PEER_STATS_LOOKBACK_DAYS",
            "PEER_STATS_COMPUTE_TIMEOUT_SECONDS",
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


if __name__ == "__main__":
    unittest.main()
