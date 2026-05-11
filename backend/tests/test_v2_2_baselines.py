"""Phase V2.2 — Commit 3 baseline computation tests.

Pin every contract the baseline engine promises:

  • Peer-set key extraction from project doc; borough fallback
    via BBL first character.
  • Fallback ladder: full → drop use_type → drop class → citywide.
    Sample-size threshold = 20 (from spec).
  • Per-BIN event counts include zero-count BINs (so percentile
    math is correct).
  • Summary stats: n, mean, median, p75, p90, p95, max.
  • Baseline upsert is idempotent on (borough, project_class,
    use_type, year_month).
  • Aggregator walks every distinct PLUTO tuple, soft-fails per-set.
  • Compare-to-peer:
      - excludes the project's own BIN from peer counts
      - returns percentile_rank, peer_median, peer_sample_size
      - structure includes violations / inspections / complaints
        + a peer_set metadata block.
  • server.py wires the nightly aggregator at 3:30 AM ET.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.statistical_engine import baselines as bl  # noqa: E402
from lib.statistical_engine import schema as se_schema  # noqa: E402

# V2.3 Commit 1: baselines.py still queries the V2.2 local mirror
# collections (nyc_violations / nyc_inspections / nyc_complaints_311
# / nyc_pluto / statistical_baselines), which are scheduled for
# removal. Commit 3 rewrites baselines.py to lazy Socrata queries
# and these tests will be rewritten alongside.
pytestmark = pytest.mark.skip(
    reason="v2.3 lazy-query rewrite pending (commit 3)"
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────────
# Stub DB (PLUTO + event collections + baselines)
# ──────────────────────────────────────────────────────────────────


class _AsyncCursor:
    def __init__(self, items, projection=None):
        self._items = list(items)
        self._projection = projection

    def __aiter__(self):
        async def _gen():
            for it in self._items:
                yield it
        return _gen()


class _StubColl:
    def __init__(self, docs=None):
        self.docs: list = list(docs or [])
        self.update_one_calls = 0

    def find(self, query=None, projection=None):
        # Filter docs against query; very small subset of Mongo
        # operators (eq, $in) — enough for the baseline tests.
        out = []
        q = query or {}
        for d in self.docs:
            ok = True
            for k, v in q.items():
                actual = d.get(k)
                if isinstance(v, dict) and "$in" in v:
                    if actual not in v["$in"]:
                        ok = False; break
                elif isinstance(v, dict) and "$gte" in v:
                    if actual is None or actual < v["$gte"]:
                        ok = False; break
                else:
                    if actual != v:
                        ok = False; break
            if ok:
                out.append(d)
        return _AsyncCursor(out, projection)

    async def update_one(self, filter_, update, upsert=False):
        self.update_one_calls += 1
        # Very loose match — find first doc whose keys equal the
        # filter (best-effort for upsert semantics).
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    d.update(update["$set"])
                r = MagicMock()
                r.upserted_id = None
                return r
        new_doc = dict(filter_)
        if "$set" in update:
            new_doc.update(update["$set"])
        self.docs.append(new_doc)
        r = MagicMock()
        r.upserted_id = "new"
        return r


class _StubDb:
    def __init__(self, **collections):
        self._cs = {}
        for name, docs in collections.items():
            self._cs[name] = _StubColl(docs)

    def __getitem__(self, name):
        if name not in self._cs:
            self._cs[name] = _StubColl([])
        return self._cs[name]


# ──────────────────────────────────────────────────────────────────
# Peer-set key
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
        key = bl._project_peer_key({
            "bbl": "1001234567",
        })
        self.assertEqual(key["borough"], "MANHATTAN")
        # Default project_class is "regular" when missing.
        self.assertEqual(key["project_class"], "regular")

    def test_falls_back_to_landuse_for_use_type(self):
        key = bl._project_peer_key({
            "borough": "QUEENS",
            "landuse": "commercial",
        })
        self.assertEqual(key["use_type"], "commercial")

    def test_borough_unknown_when_no_bbl(self):
        key = bl._project_peer_key({})
        self.assertIsNone(key["borough"])

    def test_borough_decoded_for_each_code(self):
        cases = [
            ("1", "MANHATTAN"),
            ("2", "BRONX"),
            ("3", "BROOKLYN"),
            ("4", "QUEENS"),
            ("5", "STATEN ISLAND"),
        ]
        for code, name in cases:
            key = bl._project_peer_key({"bbl": f"{code}001234567"})
            self.assertEqual(key["borough"], name, f"code {code}")


# ──────────────────────────────────────────────────────────────────
# Peer-set fallback ladder
# ──────────────────────────────────────────────────────────────────


def _pluto_doc(bbl_, borough, bldgclass=None, landuse=None):
    """V2.2.4 Path A: PLUTO docs are BBL-keyed. Helper signature
    flipped from bin_ → bbl_ to match the production schema."""
    d = {"bbl": bbl_, "borough": borough}
    if bldgclass: d["bldgclass"] = bldgclass
    if landuse:   d["landuse"] = landuse
    return d


class TestFallbackLadder(unittest.TestCase):

    def test_tier_1_full_match(self):
        # 25 BBLs all matching borough+class+use → no fallback.
        # 10-char canonical BBLs (boro=1 + block=00000 + lot=NNNN).
        pluto = [
            _pluto_doc(f"100000{i:04d}", "MANHATTAN", "major_b", "residential")
            for i in range(1, 26)
        ]
        db = _StubDb(nyc_pluto=pluto)
        proj = {"borough": "MANHATTAN", "project_class": "major_b",
                "use_type": "residential"}
        bbls, meta = _run(bl.peer_bbls(db, proj))
        self.assertEqual(len(bbls), 25)
        self.assertEqual(meta["tier"], "borough_class_use")
        self.assertEqual(meta["sample_size"], 25)

    def test_tier_2_drop_use_type(self):
        # 5 with full match (< 20), 25 with class but different use.
        pluto = [
            _pluto_doc(f"100001{i:04d}", "MANHATTAN", "major_b", "residential")
            for i in range(5)
        ] + [
            _pluto_doc(f"100002{i:04d}", "MANHATTAN", "major_b", "commercial")
            for i in range(25)
        ]
        db = _StubDb(nyc_pluto=pluto)
        proj = {"borough": "MANHATTAN", "project_class": "major_b",
                "use_type": "residential"}
        bbls, meta = _run(bl.peer_bbls(db, proj))
        self.assertEqual(meta["tier"], "borough_class")
        self.assertEqual(meta["sample_size"], 30)

    def test_tier_3_drop_class(self):
        # Few projects share class; many share borough.
        pluto = [
            _pluto_doc(f"400003{i:04d}", "QUEENS", "regular", "residential")
            for i in range(2)
        ] + [
            _pluto_doc(f"400004{i:04d}", "QUEENS", "major_a", "industrial")
            for i in range(2)
        ] + [
            _pluto_doc(f"400005{i:04d}", "QUEENS", "regular", "office")
            for i in range(25)
        ]
        db = _StubDb(nyc_pluto=pluto)
        proj = {"borough": "QUEENS", "project_class": "major_b",
                "use_type": "school"}
        bbls, meta = _run(bl.peer_bbls(db, proj))
        self.assertEqual(meta["tier"], "borough")
        self.assertGreaterEqual(meta["sample_size"], 20)

    def test_tier_4_citywide(self):
        # Few in any single borough.
        pluto = [
            _pluto_doc(f"500006{i:04d}", "STATEN ISLAND")
            for i in range(5)
        ] + [
            _pluto_doc(f"100007{i:04d}", "MANHATTAN")
            for i in range(15)
        ]
        db = _StubDb(nyc_pluto=pluto)
        proj = {"borough": "BRONX"}  # zero peers in Bronx
        bbls, meta = _run(bl.peer_bbls(db, proj))
        self.assertEqual(meta["tier"], "citywide")
        self.assertEqual(meta["sample_size"], 20)


# ──────────────────────────────────────────────────────────────────
# Per-BBL event counts (zero-count BBLs included)
# V2.2.4 Path A: was per-BIN before the BBL-keyed migration.
# ──────────────────────────────────────────────────────────────────


class TestCountEventsForBbls(unittest.TestCase):

    def test_includes_zero_count_bbls(self):
        # 4 BBLs, only 2 with violations. Use canonical 10-char form
        # to mirror what production stores post-V2.2.4.
        violations = [
            {"bbl": "1008470001", "occurred_date": datetime(2026, 4, 1, tzinfo=timezone.utc)},
            {"bbl": "1008470001", "occurred_date": datetime(2026, 4, 2, tzinfo=timezone.utc)},
            {"bbl": "1008470002", "occurred_date": datetime(2026, 4, 3, tzinfo=timezone.utc)},
        ]
        db = _StubDb(nyc_violations=violations)
        counts = _run(bl._count_events_for_bbls(
            db, "nyc_violations",
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
        db = _StubDb()
        counts = _run(bl._count_events_for_bbls(
            db, "nyc_violations", [],
            since=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ))
        self.assertEqual(counts, {})


# ──────────────────────────────────────────────────────────────────
# Summary stats
# ──────────────────────────────────────────────────────────────────


class TestSummarizeCounts(unittest.TestCase):

    def test_empty_returns_zeros(self):
        s = bl._summarize_counts({})
        self.assertEqual(s["n"], 0)
        self.assertEqual(s["mean"], 0.0)
        self.assertEqual(s["max"], 0.0)

    def test_known_distribution(self):
        # 5 BINs: counts = [0, 1, 2, 3, 100]
        s = bl._summarize_counts({
            "A": 0, "B": 1, "C": 2, "D": 3, "E": 100,
        })
        self.assertEqual(s["n"], 5)
        self.assertEqual(s["max"], 100.0)
        self.assertAlmostEqual(s["mean"], 21.2)
        # Median is the middle value (index 2 of 5) = 2.
        self.assertEqual(s["median"], 2.0)


class TestPercentile(unittest.TestCase):

    def test_basic_percentiles(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(bl._percentile(vals, 0), 1.0)
        self.assertEqual(bl._percentile(vals, 100), 5.0)
        self.assertEqual(bl._percentile(vals, 50), 3.0)

    def test_empty(self):
        self.assertEqual(bl._percentile([], 50), 0.0)


# ──────────────────────────────────────────────────────────────────
# Baseline upsert
# ──────────────────────────────────────────────────────────────────


class TestBaselineUpsert(unittest.TestCase):

    def test_upsert_idempotent_on_peer_key(self):
        db = _StubDb()
        baseline = {
            "borough":       "MANHATTAN",
            "project_class": "major_b",
            "use_type":      "residential",
            "year_month":    "2026-05",
            "peer_sample_size": 42,
            "violations":    {"n": 42, "mean": 1.5},
            "inspections":   {"n": 42, "mean": 3.2},
            "complaints":    {"n": 42, "mean": 0.8},
        }
        ok1 = _run(bl.upsert_baseline(db, baseline))
        ok2 = _run(bl.upsert_baseline(db, baseline))
        self.assertTrue(ok1)
        # Second upsert should be a no-op (no new doc).
        self.assertFalse(ok2)
        # Only one doc in the collection.
        self.assertEqual(
            len(db[se_schema.STATISTICAL_BASELINES_COLLECTION].docs),
            1,
        )


# ──────────────────────────────────────────────────────────────────
# compute_baseline_for_peer_set
# ──────────────────────────────────────────────────────────────────


class TestComputeBaseline(unittest.TestCase):

    def test_returns_documented_shape(self):
        # 3 BBLs in PLUTO with shared key.
        pluto = [
            _pluto_doc(f"100847000{i}", "MANHATTAN", "major_b", "residential")
            for i in range(3)
        ]
        # Some events on B0, none on B1, 5 on B2.
        violations = (
            [{"bbl": "1008470000", "occurred_date": datetime(2025, 5, 1, tzinfo=timezone.utc)}]
            + [{"bbl": "1008470002", "occurred_date": datetime(2025, 5, i, tzinfo=timezone.utc)}
               for i in range(1, 6)]
        )
        db = _StubDb(
            nyc_pluto=pluto,
            nyc_violations=violations,
        )
        baseline = _run(bl.compute_baseline_for_peer_set(
            db,
            borough="MANHATTAN",
            project_class="major_b",
            use_type="residential",
            year_month="2026-05",
            now=datetime(2026, 5, 8, tzinfo=timezone.utc),
        ))
        self.assertEqual(baseline["borough"], "MANHATTAN")
        self.assertEqual(baseline["project_class"], "major_b")
        self.assertEqual(baseline["use_type"], "residential")
        self.assertEqual(baseline["year_month"], "2026-05")
        self.assertEqual(baseline["peer_sample_size"], 3)
        self.assertEqual(baseline["violations"]["n"], 3)
        # Max violation count among B0/B1/B2 is 5.
        self.assertEqual(baseline["violations"]["max"], 5.0)


# ──────────────────────────────────────────────────────────────────
# Compare-to-peer
# ──────────────────────────────────────────────────────────────────


class TestCompareToPeers(unittest.TestCase):

    def test_excludes_project_own_bbl_from_peers(self):
        # V2.2.4 Path A: peer-comparison is BBL-keyed. Project's
        # own BBL must be excluded so the comparison is "us vs.
        # peers", not "us vs. (peers + us)".
        pluto = [
            _pluto_doc(f"100848{i:04d}", "MANHATTAN", "major_b", "residential")
            for i in range(25)
        ]
        # Project's own BBL gets 50 violations; peers get 1 each.
        violations = [
            {"bbl": "1008480000", "occurred_date": datetime(2025, 5, i % 28 + 1, tzinfo=timezone.utc)}
            for i in range(50)
        ] + [
            {"bbl": f"100848{i:04d}", "occurred_date": datetime(2025, 5, 1, tzinfo=timezone.utc)}
            for i in range(1, 25)
        ]
        db = _StubDb(nyc_pluto=pluto, nyc_violations=violations)
        proj = {
            "bbl": "1008480000", "borough": "MANHATTAN",
            "project_class": "major_b", "use_type": "residential",
        }
        result = _run(bl.compare_project_to_peers(
            db, proj,
            now=datetime(2026, 5, 8, tzinfo=timezone.utc),
        ))
        v = result["violations"]
        self.assertEqual(v["project_count"], 50)
        # Peer sample size is total peers minus self = 24.
        self.assertEqual(v["peer_sample_size"], 24)
        # Peers each have ~1 violation; median should be 1.
        self.assertEqual(v["peer_median"], 1.0)
        # Project at 50 dwarfs peers; percentile rank near 100%.
        self.assertAlmostEqual(v["percentile_rank"], 100.0, places=4)

    def test_returns_peer_set_metadata(self):
        pluto = [
            _pluto_doc(f"400849{i:04d}", "QUEENS", "regular", "office")
            for i in range(25)
        ]
        db = _StubDb(nyc_pluto=pluto)
        proj = {"bbl": "4008490000", "borough": "QUEENS",
                "project_class": "regular", "use_type": "office"}
        result = _run(bl.compare_project_to_peers(
            db, proj,
            now=datetime(2026, 5, 8, tzinfo=timezone.utc),
        ))
        self.assertIn("peer_set", result)
        self.assertEqual(result["peer_set"]["tier"], "borough_class_use")
        self.assertEqual(result["peer_set"]["borough"], "QUEENS")

    def test_includes_all_three_event_types(self):
        pluto = [
            _pluto_doc(f"200850{i:04d}", "BRONX", "major_a", "school")
            for i in range(25)
        ]
        db = _StubDb(nyc_pluto=pluto)
        proj = {"bbl": "2008500000", "borough": "BRONX",
                "project_class": "major_a", "use_type": "school"}
        result = _run(bl.compare_project_to_peers(
            db, proj,
            now=datetime(2026, 5, 8, tzinfo=timezone.utc),
        ))
        self.assertIn("violations", result)
        self.assertIn("inspections", result)
        self.assertIn("complaints", result)


# ──────────────────────────────────────────────────────────────────
# Aggregator (nightly tick)
# ──────────────────────────────────────────────────────────────────


class TestAggregator(unittest.TestCase):

    def test_walks_distinct_pluto_tuples(self):
        # 5 BBLs spread across 3 distinct (borough, class, use)
        # tuples → 3 baselines written. V2.2.4 Path A: BBL-keyed.
        pluto = [
            _pluto_doc("1008510001", "MANHATTAN", "major_b", "residential"),
            _pluto_doc("1008510002", "MANHATTAN", "major_b", "residential"),
            _pluto_doc("4008510003", "QUEENS",    "regular", "office"),
            _pluto_doc("3008510004", "BROOKLYN",  "regular", "residential"),
            _pluto_doc("3008510005", "BROOKLYN",  "regular", "residential"),
        ]
        db = _StubDb(nyc_pluto=pluto)
        summary = _run(bl.run_baseline_aggregator(
            db,
            now=datetime(2026, 5, 8, tzinfo=timezone.utc),
        ))
        self.assertEqual(summary["peer_sets_seen"], 3)
        self.assertEqual(summary["baselines_written"], 3)


# ──────────────────────────────────────────────────────────────────
# server.py wiring
# ──────────────────────────────────────────────────────────────────


class TestServerBaselineCronWiring(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_baseline_aggregator_job_id(self):
        self.assertIn("v2_2_baseline_aggregator", self.text)

    def test_baseline_aggregator_at_3_30_am(self):
        # Documented as 3:30 AM ET — between V2.0 logbook (3 AM)
        # and V2.2 weekly ingest (Sunday 2 AM).
        self.assertIn(
            'CronTrigger(hour=3, minute=30, timezone="America/New_York")',
            self.text,
        )

    def test_baseline_aggregator_calls_run_aggregator(self):
        s = self.text.find("async def _v22_baseline_aggregator_tick")
        self.assertGreater(s, 0)
        e = self.text.find("scheduler.add_job", s)
        slice_ = self.text[s:e]
        self.assertIn("run_baseline_aggregator", slice_)


# ──────────────────────────────────────────────────────────────────
# Package re-exports
# ──────────────────────────────────────────────────────────────────


class TestPackageReExportsCommit3(unittest.TestCase):

    def test_baselines_api_reexported(self):
        from lib import statistical_engine as stat_engine
        # V2.2.4 Path A: was `peer_bins`; renamed to `peer_bbls`.
        self.assertTrue(hasattr(stat_engine, "peer_bbls"))
        self.assertTrue(hasattr(stat_engine, "compute_baseline_for_peer_set"))
        self.assertTrue(hasattr(stat_engine, "run_baseline_aggregator"))
        self.assertTrue(hasattr(stat_engine, "compare_project_to_peers"))


if __name__ == "__main__":
    unittest.main()
