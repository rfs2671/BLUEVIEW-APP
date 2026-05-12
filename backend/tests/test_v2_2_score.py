"""Phase V2.2 — Commit 5 score recomputation tests.

Pin every contract:

  • GROUP_WEIGHTS sum to 1.0; weights cover all 4 groups.
  • Each group normalizer maps known inputs to the right [0,100]
    value (or close to it).
  • _score_from_group_values weights the groups correctly,
    clamps to [0,100].
  • Bootstrap CI: deterministic with seeded RNG, low ≤ high,
    zero inputs collapse CI to (0,0).
  • Factor breakdown emits 4 rows, one per group, with
    contribution = value * weight.
  • Score doc shape matches the FE expectation (score,
    confidence_low, confidence_high, contributing_factors,
    group_values, model_version, weights_snapshot).
  • recompute_and_persist persists a row to db.risk_scores
    AND fires triggers first.
  • The /calculate endpoint runs recompute_and_persist (already
    pinned in scaffolding tests).
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.statistical_engine import score as sc  # noqa: E402
from lib.statistical_engine import schema as se_schema  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────────
# Group weights
# ──────────────────────────────────────────────────────────────────


class TestGroupWeights(unittest.TestCase):

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(sc.GROUP_WEIGHTS.values()), 1.0, places=6)

    def test_weights_cover_every_group(self):
        for g in sc.ALL_GROUPS:
            self.assertIn(g, sc.GROUP_WEIGHTS)

    def test_own_building_highest_weight(self):
        # Spec rationale: own-building events are the most direct
        # signal. Highest weight by design.
        own = sc.GROUP_WEIGHTS[sc.GROUP_OWN_BUILDING]
        for g, w in sc.GROUP_WEIGHTS.items():
            if g == sc.GROUP_OWN_BUILDING:
                continue
            self.assertGreaterEqual(own, w,
                                    f"{g} weight {w} > own_building {own}")

    def test_internal_compliance_lowest_weight(self):
        internal = sc.GROUP_WEIGHTS[sc.GROUP_INTERNAL_COMPLIANCE]
        for g, w in sc.GROUP_WEIGHTS.items():
            if g == sc.GROUP_INTERNAL_COMPLIANCE:
                continue
            self.assertLessEqual(internal, w,
                                 f"{g} weight {w} < internal {internal}")


# ──────────────────────────────────────────────────────────────────
# Group normalizers
# ──────────────────────────────────────────────────────────────────


class TestNormalizers(unittest.TestCase):

    def test_own_building_clean_is_zero(self):
        self.assertEqual(sc._normalize_own_building(
            violations_30d=0, violations_90d=0,
            inspections_failed_60d=0, open_complaints_30d=0,
        ), 0.0)

    def test_own_building_capped_at_100(self):
        # Insanely large numbers still clamp.
        self.assertEqual(sc._normalize_own_building(
            violations_30d=100, violations_90d=100,
            inspections_failed_60d=100, open_complaints_30d=100,
        ), 100.0)

    def test_own_building_known_distribution(self):
        # 2 recent violations + 1 failed inspection + 3 complaints
        # = 2*8 + 0*2 + 1*12 + 3*4 = 16 + 12 + 12 = 40.
        v = sc._normalize_own_building(
            violations_30d=2, violations_90d=2,
            inspections_failed_60d=1, open_complaints_30d=3,
        )
        # The 2 violations also count in the 90d bucket → +4.
        # Total = 16 + 4 + 12 + 12 = 44.
        self.assertEqual(v, 44.0)

    def test_peer_comparison_mean_of_three(self):
        v = sc._normalize_peer_comparison(
            violations_percentile=60.0,
            inspections_percentile=30.0,
            complaints_percentile=90.0,
        )
        self.assertEqual(v, 60.0)

    def test_peer_comparison_zero(self):
        v = sc._normalize_peer_comparison(
            violations_percentile=0.0,
            inspections_percentile=0.0,
            complaints_percentile=0.0,
        )
        self.assertEqual(v, 0.0)


# ──────────────────────────────────────────────────────────────────
# NEW PIN 2 — schema-corrections hotfix
# ──────────────────────────────────────────────────────────────────


class TestNormalizePeerComparison(unittest.TestCase):
    """Pin the dynamic-divisor behavior introduced by the
    schema-corrections hotfix: violations is gated off the peer
    comparison (no ``bbl`` column on 3h2n-5cm9), and the peer
    normalizer averages over the AVAILABLE dimensions only — the
    divisor is the count of non-None inputs, not a hard-coded 3.
    Without this, a pinned percentile_rank from the gated
    dimension would bias the peer subscore by ~33%."""

    def test_averages_over_available_dimensions_only(self):
        # Two available + one None → mean of the two.
        v = sc._normalize_peer_comparison(
            violations_percentile=None,
            inspections_percentile=85.0,
            complaints_percentile=72.0,
        )
        self.assertEqual(v, (85.0 + 72.0) / 2)
        self.assertEqual(v, 78.5)

        # All three None → 0.0 (theoretical edge case).
        v = sc._normalize_peer_comparison(
            violations_percentile=None,
            inspections_percentile=None,
            complaints_percentile=None,
        )
        self.assertEqual(v, 0.0)

        # Two None + one float → return that float (divisor = 1,
        # not 3).
        v = sc._normalize_peer_comparison(
            violations_percentile=None,
            inspections_percentile=42.5,
            complaints_percentile=None,
        )
        self.assertEqual(v, 42.5)

        # Clamp invariant: never exceeds 100.0. Each
        # percentile_rank is mathematically bounded to [0, 100],
        # but the clamp must hold defensively.
        v = sc._normalize_peer_comparison(
            violations_percentile=None,
            inspections_percentile=100.0,
            complaints_percentile=100.0,
        )
        self.assertEqual(v, 100.0)
        # Defensive: hypothetical out-of-range input.
        v = sc._normalize_peer_comparison(
            violations_percentile=None,
            inspections_percentile=150.0,
            complaints_percentile=100.0,
        )
        self.assertLessEqual(v, 100.0)

    def test_active_triggers_empty_is_zero(self):
        self.assertEqual(sc._normalize_active_triggers([]), 0.0)

    def test_active_triggers_diminishing_returns(self):
        # 1 prediction at confidence 0.80 = 80 * 1.0 = 80.
        v1 = sc._normalize_active_triggers([{"confidence": 0.80}])
        self.assertEqual(v1, 80.0)
        # 2 predictions: 0.80 * 1.0 + 0.80 * 0.5 = 80 + 40 = 120 → clamp 100.
        v2 = sc._normalize_active_triggers([
            {"confidence": 0.80}, {"confidence": 0.80},
        ])
        self.assertEqual(v2, 100.0)

    def test_internal_compliance_clean(self):
        self.assertEqual(sc._normalize_internal_compliance(
            deficiency_count_30d=0, missing_logs_30d=0, sst_expiring_30d=0,
        ), 0.0)


# ──────────────────────────────────────────────────────────────────
# Score from group values
# ──────────────────────────────────────────────────────────────────


class TestScoreFromGroupValues(unittest.TestCase):

    def test_zero_groups_zero_score(self):
        s = sc._score_from_group_values({
            sc.GROUP_OWN_BUILDING: 0.0,
            sc.GROUP_PEER_COMPARISON: 0.0,
            sc.GROUP_ACTIVE_TRIGGERS: 0.0,
            sc.GROUP_INTERNAL_COMPLIANCE: 0.0,
        })
        self.assertEqual(s, 0.0)

    def test_max_groups_max_score(self):
        s = sc._score_from_group_values({
            sc.GROUP_OWN_BUILDING: 100.0,
            sc.GROUP_PEER_COMPARISON: 100.0,
            sc.GROUP_ACTIVE_TRIGGERS: 100.0,
            sc.GROUP_INTERNAL_COMPLIANCE: 100.0,
        })
        self.assertEqual(s, 100.0)

    def test_known_weighted_sum(self):
        # own=40 (×0.40 = 16), peer=80 (×0.25 = 20),
        # triggers=0 (×0.25 = 0), internal=10 (×0.10 = 1).
        # Total = 16 + 20 + 0 + 1 = 37.
        s = sc._score_from_group_values({
            sc.GROUP_OWN_BUILDING: 40.0,
            sc.GROUP_PEER_COMPARISON: 80.0,
            sc.GROUP_ACTIVE_TRIGGERS: 0.0,
            sc.GROUP_INTERNAL_COMPLIANCE: 10.0,
        })
        self.assertEqual(s, 37.0)


# ──────────────────────────────────────────────────────────────────
# Bootstrap CI
# ──────────────────────────────────────────────────────────────────


class TestBootstrapCI(unittest.TestCase):

    def test_zero_inputs_collapse_ci(self):
        low, high = sc._bootstrap_ci(
            {g: 0.0 for g in sc.ALL_GROUPS},
            rng=random.Random(0),
        )
        self.assertEqual(low, 0.0)
        self.assertEqual(high, 0.0)

    def test_low_le_high(self):
        low, high = sc._bootstrap_ci(
            {sc.GROUP_OWN_BUILDING: 50.0,
             sc.GROUP_PEER_COMPARISON: 60.0,
             sc.GROUP_ACTIVE_TRIGGERS: 70.0,
             sc.GROUP_INTERNAL_COMPLIANCE: 30.0},
            rng=random.Random(42),
        )
        self.assertLessEqual(low, high)

    def test_deterministic_with_seeded_rng(self):
        gv = {sc.GROUP_OWN_BUILDING: 50.0,
              sc.GROUP_PEER_COMPARISON: 60.0,
              sc.GROUP_ACTIVE_TRIGGERS: 0.0,
              sc.GROUP_INTERNAL_COMPLIANCE: 0.0}
        a = sc._bootstrap_ci(gv, rng=random.Random(7))
        b = sc._bootstrap_ci(gv, rng=random.Random(7))
        self.assertEqual(a, b)

    def test_bootstrap_constants_pinned(self):
        self.assertEqual(sc.BOOTSTRAP_SAMPLES, 1000)
        self.assertEqual(sc.CONFIDENCE_INTERVAL_PCT, 95)


# ──────────────────────────────────────────────────────────────────
# calculate_risk_score (pure end-to-end)
# ──────────────────────────────────────────────────────────────────


class TestCalculateRiskScore(unittest.TestCase):

    def _inputs(self, **overrides):
        base = {
            "now": datetime(2026, 5, 8, tzinfo=timezone.utc),
            "own": {
                "violations_30d": 0, "violations_90d": 0,
                "inspections_failed_60d": 0, "open_complaints_30d": 0,
            },
            "peer_compare": {
                "peer_set": {"sample_size": 25, "borough": "MANHATTAN",
                             "tier": "borough_class_use"},
                "violations":  {"percentile_rank": 0.0},
                "inspections": {"percentile_rank": 0.0},
                "complaints":  {"percentile_rank": 0.0},
            },
            "active_predictions": [],
            "internal": {
                "deficiency_count_30d": 0,
                "missing_logs_30d": 0,
                "sst_expiring_30d": 0,
            },
        }
        for k, v in overrides.items():
            base[k] = v
        return base

    def test_clean_inputs_score_zero(self):
        result = sc.calculate_risk_score(self._inputs())
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["confidence_low"], 0.0)
        self.assertEqual(result["confidence_high"], 0.0)

    def test_high_inputs_high_score(self):
        result = sc.calculate_risk_score(self._inputs(
            own={
                "violations_30d": 5, "violations_90d": 8,
                "inspections_failed_60d": 3, "open_complaints_30d": 5,
            },
            peer_compare={
                "peer_set": {"sample_size": 25, "borough": "MANHATTAN",
                             "tier": "borough_class_use"},
                "violations":  {"percentile_rank": 95.0},
                "inspections": {"percentile_rank": 90.0},
                "complaints":  {"percentile_rank": 85.0},
            },
            active_predictions=[
                {"confidence": 0.85, "trigger_kind": "311_at_bin"},
                {"confidence": 0.78, "trigger_kind": "csc_periodic"},
            ],
        ))
        # Score should be moderately high (60+).
        self.assertGreater(result["score"], 50.0)
        self.assertLessEqual(result["score"], 100.0)

    def test_returns_documented_shape(self):
        result = sc.calculate_risk_score(self._inputs())
        for k in ("score", "confidence_low", "confidence_high",
                  "group_values", "contributing_factors"):
            self.assertIn(k, result)

    def test_contributing_factors_has_4_groups(self):
        result = sc.calculate_risk_score(self._inputs())
        groups = [f["group"] for f in result["contributing_factors"]]
        self.assertEqual(set(groups), set(sc.ALL_GROUPS))
        self.assertEqual(len(groups), 4)

    def test_contribution_equals_value_times_weight(self):
        result = sc.calculate_risk_score(self._inputs(
            own={
                "violations_30d": 5, "violations_90d": 5,
                "inspections_failed_60d": 0, "open_complaints_30d": 0,
            },
        ))
        for f in result["contributing_factors"]:
            expected = f["value"] * f["weight"]
            self.assertAlmostEqual(
                f["contribution"], expected, places=4,
                msg=f"group {f['group']} contribution mismatch",
            )


# ──────────────────────────────────────────────────────────────────
# Async pipeline (stub DB)
# ──────────────────────────────────────────────────────────────────


class _StubColl:
    def __init__(self, docs=None):
        self.docs: list = list(docs or [])

    def find(self, query=None, projection=None):
        out = list(self.docs)
        # tiny operator subset: bin, occurred_date $gte, project_id
        if query:
            filtered = []
            for d in out:
                ok = True
                for k, v in query.items():
                    actual = d.get(k)
                    if isinstance(v, dict):
                        if "$gte" in v and not (
                            actual is not None and actual >= v["$gte"]
                        ):
                            ok = False; break
                    elif actual != v:
                        ok = False; break
                if ok:
                    filtered.append(d)
            out = filtered

        class _Cur:
            def __aiter__(_self):
                async def _gen():
                    for it in out: yield it
                return _gen()
        return _Cur()

    async def count_documents(self, query):
        # Match-everything for simplicity in this stub; tests
        # don't depend on real counts.
        return len(self.docs)

    async def insert_one(self, doc):
        self.docs.append(doc)
        r = MagicMock()
        r.inserted_id = "new_score"
        return r

    async def update_one(self, filter_, update, upsert=False):
        r = MagicMock()
        r.upserted_id = "u" if upsert else None
        return r

    async def update_many(self, filter_, update):
        r = MagicMock()
        r.modified_count = 0
        return r


class _StubDb:
    def __init__(self):
        self._cs = {}
        # Attribute-access for `.risk_scores`, `.logbook_entries`,
        # `.workers`. They're empty by default.
        self.risk_scores = _StubColl()
        self.logbook_entries = _StubColl()
        self.workers = _StubColl()
        self.subcontractors = _StubColl()
        self.dob_logs = _StubColl()
        self.daily_logs = _StubColl()
        self.projects = _StubColl()

    def __getitem__(self, name):
        if name not in self._cs:
            self._cs[name] = _StubColl()
        return self._cs[name]


class TestRecomputeAndPersist(unittest.TestCase):

    def test_persists_a_row(self):
        db = _StubDb()
        project = {
            "_id": "P1", "company_id": "co_a",
            "nyc_bin": "1234567", "bbl": "1001234567",
            "borough": "MANHATTAN",
        }
        doc = _run(sc.recompute_and_persist(
            db, project,
            now=datetime(2026, 5, 8, tzinfo=timezone.utc),
        ))
        self.assertIn("score", doc)
        self.assertIn("confidence_low", doc)
        self.assertIn("confidence_high", doc)
        self.assertEqual(doc["model_version"], se_schema.MODEL_VERSION)
        self.assertIn("weights_snapshot", doc)
        # Inserted into db.risk_scores.
        self.assertEqual(len(db.risk_scores.docs), 1)


# ──────────────────────────────────────────────────────────────────
# V2.2.1 — GET /risk-score must filter by model_version
# ──────────────────────────────────────────────────────────────────
#
# The risk_scores collection on production carries BOTH V2.1
# heuristic-v1 rows (left over from V2.1) and V2.2 statistical-v1
# rows. Without a model_version filter the GET handler returns
# whichever has the newest calculated_at, which after deploy
# was always the V2.1 row (V2.2 hadn't run a backfill yet).
# Operator saw stale heuristic-v1 scores in the FE.


class _SortLimitCursor:
    """Cursor stub that supports the .find().sort().limit() chain.
    Both async iteration (latest-score endpoint) AND .to_list(n)
    (history endpoint, V2.2.1.1) are supported."""

    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction=-1):
        # Only -1 desc on `calculated_at` is exercised by the
        # endpoint; supporting that one shape is enough.
        reverse = (direction == -1)
        self._docs.sort(
            key=lambda d: d.get(key) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=reverse,
        )
        return self

    def limit(self, n):
        if n is not None and n >= 0:
            self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        async def _gen():
            for it in self._docs:
                yield it
        return _gen()

    def to_list(self, n=None):
        # The history endpoint uses `await cursor.to_list(500)`.
        # motor's .to_list returns an awaitable that resolves to
        # the materialized list.
        items = self._docs[:n] if (n is not None and n >= 0) else self._docs
        async def _coro():
            return items
        return _coro()


class _ModelVersionStubColl:
    """Stub that emulates the find/sort/limit/(async-iter | to_list)
    chain AND honors:
      • equality filters (project_id, model_version)
      • {$gte: <datetime>} on calculated_at (history endpoint)
    """

    def __init__(self):
        self.docs: list = []

    def find(self, query=None):
        q = query or {}
        out = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                actual = d.get(k)
                if isinstance(v, dict) and "$gte" in v:
                    if actual is None or actual < v["$gte"]:
                        ok = False
                        break
                elif actual != v:
                    ok = False
                    break
            if ok:
                out.append(d)
        return _SortLimitCursor(out)


def _setup_authed_client(*, role="admin", user_id="u_x", company_id="co_a"):
    """Mirrors test_v2_0_logbook.py's helper. Returns
    (client, restore) — call restore() to clear dependency
    overrides."""
    from fastapi.testclient import TestClient
    import server
    user = {"id": user_id, "_id": user_id,
            "role": role, "company_id": company_id}
    async def _fake_user():
        return user
    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app, raise_server_exceptions=False), \
        lambda: server.app.dependency_overrides.clear()


class TestGetRiskScoreFiltersModelVersion(unittest.TestCase):
    """V2.2.1 regression test for the
    "GET returns stale V2.1 heuristic-v1 row" bug.

    Sequence:
      1. Insert a heuristic-v1 row from yesterday. NO statistical-
         v1 row. GET → 404 "No score yet".
      2. Insert a statistical-v1 row (calculated today). GET →
         200, body.score.model_version == "statistical-v1".
    The handler MUST NOT return the heuristic-v1 row even when
    it's the newest by calculated_at.
    """

    def test_filters_by_statistical_v1_model_version(self):
        from unittest.mock import patch
        import server

        yesterday = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
        today = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)

        risk_scores = _ModelVersionStubColl()
        risk_scores.docs.append({
            "_id": "v21_row",
            "project_id": "P1",
            "model_version": "heuristic-v1",
            "score": 12.5,
            "calculated_at": yesterday,
        })

        # Stub db: only need risk_scores. The endpoint reads
        # exactly db.risk_scores.find(...).sort(...).limit(...).
        stub_db = MagicMock()
        stub_db.risk_scores = risk_scores

        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", stub_db):
                # Phase 1: only V2.1 row → 404.
                r = client.get("/api/projects/P1/risk-score")
                self.assertEqual(r.status_code, 404, r.text)
                self.assertEqual(r.json().get("detail"), "No score yet")

                # Phase 2: insert a V2.2 row, GET should return it
                # (NOT the V2.1 row).
                risk_scores.docs.append({
                    "_id": "v22_row",
                    "project_id": "P1",
                    "model_version": "statistical-v1",
                    "score": 47.0,
                    "calculated_at": today,
                })
                r = client.get("/api/projects/P1/risk-score")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertIn("score", body)
                self.assertEqual(
                    body["score"]["model_version"], "statistical-v1",
                )
                # And critically, NOT the heuristic-v1 row.
                self.assertNotEqual(
                    body["score"].get("id"), "v21_row",
                )
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# V2.2.1.1 — GET /risk-score/history must filter by model_version
# ──────────────────────────────────────────────────────────────────
#
# Same logical bug as V2.2.1, on the time-series endpoint. Without
# the filter the trend chart on a long-lived project would mix
# V2.1 heuristic-v1 points with V2.2 statistical-v1 points —
# visually continuous but semantically apples-and-oranges since
# the two models have different scoring distributions.


class TestGetRiskScoreHistoryFiltersModelVersion(unittest.TestCase):
    """V2.2.1.1 regression test for the
    "GET /history mixes V2.1 heuristic-v1 + V2.2 statistical-v1
    rows" bug.

    Fixture: 4 rows on the same project — 2 heuristic-v1 (older)
    + 2 statistical-v1 (newer), all within the 30-day window.
    GET /history?days=30 MUST return exactly the 2 V2.2 rows.
    """

    def test_history_filters_by_statistical_v1(self):
        from unittest.mock import patch
        import server

        now = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
        # Older V2.1 rows (still within the 30-day window so the
        # cutoff doesn't accidentally filter them — the bug is
        # specifically about model_version, not the time window).
        d_minus_15 = now - timedelta(days=15)
        d_minus_12 = now - timedelta(days=12)
        # Newer V2.2 rows.
        d_minus_3 = now - timedelta(days=3)
        d_minus_1 = now - timedelta(days=1)

        risk_scores = _ModelVersionStubColl()
        risk_scores.docs.extend([
            {"_id": "v21_a", "project_id": "P1",
             "model_version": "heuristic-v1", "score": 11.0,
             "calculated_at": d_minus_15},
            {"_id": "v21_b", "project_id": "P1",
             "model_version": "heuristic-v1", "score": 13.0,
             "calculated_at": d_minus_12},
            {"_id": "v22_a", "project_id": "P1",
             "model_version": "statistical-v1", "score": 41.0,
             "calculated_at": d_minus_3},
            {"_id": "v22_b", "project_id": "P1",
             "model_version": "statistical-v1", "score": 47.0,
             "calculated_at": d_minus_1},
        ])

        stub_db = MagicMock()
        stub_db.risk_scores = risk_scores

        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", stub_db):
                r = client.get("/api/projects/P1/risk-score/history?days=30")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertIn("history", body)
                items = body["history"]
                # Exactly 2 — the V2.2 rows. NOT 4.
                self.assertEqual(
                    len(items), 2,
                    f"history returned {len(items)} rows, expected 2 "
                    f"V2.2 rows (V2.1 rows must be filtered out)",
                )
                # All returned items are V2.2.
                for item in items:
                    self.assertEqual(
                        item.get("model_version"), "statistical-v1",
                        f"non-V2.2 row leaked through: {item}",
                    )
                # And critically, NEITHER V2.1 row id appears.
                returned_ids = {item.get("id") for item in items}
                self.assertNotIn("v21_a", returned_ids)
                self.assertNotIn("v21_b", returned_ids)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# Package re-exports
# ──────────────────────────────────────────────────────────────────


class TestPackageReExportsCommit5(unittest.TestCase):

    def test_score_api_reexported(self):
        from lib import statistical_engine as stat_engine
        for name in (
            "GROUP_WEIGHTS", "ALL_GROUPS",
            "GROUP_OWN_BUILDING", "GROUP_PEER_COMPARISON",
            "GROUP_ACTIVE_TRIGGERS", "GROUP_INTERNAL_COMPLIANCE",
            "calculate_risk_score", "recompute_and_persist",
        ):
            self.assertTrue(hasattr(stat_engine, name),
                            f"missing re-export: {name}")


if __name__ == "__main__":
    unittest.main()
