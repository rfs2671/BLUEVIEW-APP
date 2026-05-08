"""Phase V2.1 — NYC DOB Risk Score tests.

Pin every contract the v2 risk-score system promises:

  • Schema: model version constant, weights sum to 100, indexes
    cover the documented query paths.
  • Heuristic: clean inputs → 0, worst inputs → 100, monotonic in
    each input, top-N factor ordering deterministic.
  • Confidence interval: deterministic with a seeded RNG, low ≤ high,
    bounds collapse for zero-input case.
  • Calibration: brier score + roc_auc compute correctly on known
    samples, log_inspector_review writes a review row, aggregator
    reads risk_scores + risk_score_reviews.
  • Orchestrator: persists a doc, idempotency holds (12h freshness),
    force=True bypasses the freshness check.
  • Endpoints: flag DISABLED → 404 on every endpoint;
    flag ENABLED → returns the expected shape.
  • Frontend RiskScoreCard: useFeatureFlag is the FIRST hook;
    flag-off returns null before fetching; calibration POST goes
    to /api/projects/{id}/risk-score/calibration.
  • server.py wiring: 5 endpoints flag-gated, scheduler tick at 4 AM
    ET, three new collections' indexes registered at startup.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import unittest
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from lib import risk_score  # noqa: E402
from lib.risk_score import (  # noqa: E402
    schema as rs_schema,
    heuristic as rs_heuristic,
    calibration as rs_calibration,
    orchestrator as rs_orchestrator,
)
from lib.risk_score.heuristic import (  # noqa: E402
    INPUT_KEYS,
    INPUT_KEY_ACTIVE_DOB_VIOLATIONS,
    INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION,
    INPUT_KEY_INSPECTION_COMPLIANCE_MISSED,
    INPUT_KEY_DEFICIENCY_COUNT_30D,
    INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP,
    INPUT_KEY_MISSING_LOGS_30D,
    INPUT_KEY_SST_EXPIRATIONS_NEXT_30D,
    INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY,
    WEIGHTS,
    NORMALIZATION_CAPS,
)
from lib import feature_flags  # noqa: E402


def _run(coro):
    """Fresh event loop per async test — same pattern as V2.0."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _clean_inputs():
    """Helper: a project with zero risk on every axis. Note that
    permit_days_to_expiration is set well ABOVE its cap (1000) —
    a 0 means 'expired today' (full risk on that axis), and the
    cap-boundary value 30 is sensitive to bootstrap perturbation.
    Setting it to 1000 keeps it deeply in the no-risk zone even
    after Gaussian noise so the CI for clean inputs collapses
    cleanly to 0."""
    return {
        INPUT_KEY_ACTIVE_DOB_VIOLATIONS:        0.0,
        INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION: 1000.0,
        INPUT_KEY_INSPECTION_COMPLIANCE_MISSED: 0.0,
        INPUT_KEY_DEFICIENCY_COUNT_30D:         0.0,
        INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP:  0.0,
        INPUT_KEY_MISSING_LOGS_30D:             0.0,
        INPUT_KEY_SST_EXPIRATIONS_NEXT_30D:     0.0,
        INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY:     0.0,
    }


def _worst_inputs():
    """Helper: maxed-out on every axis (or beyond cap).
    Score should resolve to exactly 100."""
    return {
        INPUT_KEY_ACTIVE_DOB_VIOLATIONS:        5.0,
        INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION:    0.0,    # expired
        INPUT_KEY_INSPECTION_COMPLIANCE_MISSED: 10.0,
        INPUT_KEY_DEFICIENCY_COUNT_30D:         20.0,
        INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP:  5.0,
        INPUT_KEY_MISSING_LOGS_30D:             22.0,
        INPUT_KEY_SST_EXPIRATIONS_NEXT_30D:     50.0,
        INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY:     30.0,
    }


class _AsyncCursor:
    """Mocks motor.find() returning a chainable cursor.
    Same shape as V2.0 test helper."""

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        async def _gen():
            for it in self._items:
                yield it
        return _gen()

    def sort(self, *_a, **_k):
        return self

    def limit(self, n):
        if n is not None and n >= 0:
            self._items = self._items[:n]
        return self

    def to_list(self, _n=None):
        async def _coro():
            if _n is not None and _n >= 0:
                return self._items[:_n]
            return self._items
        return _coro()


# ──────────────────────────────────────────────────────────────────
# Schema + constants
# ──────────────────────────────────────────────────────────────────


class TestSchemaConstants(unittest.TestCase):

    def test_collection_names_pinned(self):
        self.assertEqual(rs_schema.RISK_SCORES_COLLECTION, "risk_scores")
        self.assertEqual(rs_schema.RISK_SCORE_REVIEWS_COLLECTION,
                         "risk_score_reviews")
        self.assertEqual(rs_schema.RISK_SCORE_CALIBRATION_COLLECTION,
                         "risk_score_calibration")

    def test_model_version_pinned(self):
        # Bumps are intentional + documented; this pin catches an
        # accidental rename that would orphan all prior scores.
        self.assertEqual(rs_schema.MODEL_VERSION, "heuristic-v1")

    def test_score_band_thresholds(self):
        self.assertEqual(rs_schema.score_band(0), "green")
        self.assertEqual(rs_schema.score_band(30), "green")
        self.assertEqual(rs_schema.score_band(31), "yellow")
        self.assertEqual(rs_schema.score_band(60), "yellow")
        self.assertEqual(rs_schema.score_band(61), "orange")
        self.assertEqual(rs_schema.score_band(80), "orange")
        self.assertEqual(rs_schema.score_band(81), "red")
        self.assertEqual(rs_schema.score_band(100), "red")
        # None / weird input = green (defensive default).
        self.assertEqual(rs_schema.score_band(None), "green")

    def test_indexes_cover_documented_queries(self):
        # risk_scores: latest-per-project + history + model-version.
        names = [idx["name"] for idx in rs_schema.RISK_SCORES_INDEXES]
        self.assertIn("risk_scores_company_project_calculated", names)
        self.assertIn("risk_scores_project_calculated_desc", names)
        self.assertIn("risk_scores_model_calculated", names)

        rev_names = [idx["name"] for idx in rs_schema.RISK_SCORE_REVIEWS_INDEXES]
        self.assertIn("risk_score_reviews_model_reviewed", rev_names)
        self.assertIn("risk_score_reviews_score", rev_names)

        cal_names = [idx["name"] for idx in rs_schema.RISK_SCORE_CALIBRATION_INDEXES]
        self.assertIn("risk_score_calibration_model_evaluated", cal_names)


# ──────────────────────────────────────────────────────────────────
# Weights + normalization
# ──────────────────────────────────────────────────────────────────


class TestWeightsAndNormalization(unittest.TestCase):

    def test_weights_sum_to_100(self):
        # Critical invariant: a maxed-out project must score exactly
        # 100, not 99 / 101 from drift.
        self.assertAlmostEqual(sum(WEIGHTS.values()), 100.0, places=6)

    def test_weights_cover_every_input(self):
        for k in INPUT_KEYS:
            self.assertIn(k, WEIGHTS, f"missing weight for {k}")

    def test_normalization_caps_cover_every_input(self):
        for k in INPUT_KEYS:
            self.assertIn(k, NORMALIZATION_CAPS, f"missing cap for {k}")

    def test_violations_have_highest_weight(self):
        """Domain rule: active DOB violations are the most direct
        regulatory signal. A weight reshuffling that demotes them
        below another input is suspicious and warrants test review."""
        violation_w = WEIGHTS[INPUT_KEY_ACTIVE_DOB_VIOLATIONS]
        for k, w in WEIGHTS.items():
            if k == INPUT_KEY_ACTIVE_DOB_VIOLATIONS:
                continue
            self.assertGreaterEqual(violation_w, w,
                                    f"{k} weight {w} ≥ violations {violation_w}")

    def test_normalize_clean(self):
        n = rs_heuristic._normalize_input(INPUT_KEY_DEFICIENCY_COUNT_30D, 0)
        self.assertEqual(n, 0.0)

    def test_normalize_at_cap(self):
        n = rs_heuristic._normalize_input(
            INPUT_KEY_DEFICIENCY_COUNT_30D,
            NORMALIZATION_CAPS[INPUT_KEY_DEFICIENCY_COUNT_30D],
        )
        self.assertEqual(n, 1.0)

    def test_normalize_above_cap_clamps_to_one(self):
        n = rs_heuristic._normalize_input(
            INPUT_KEY_DEFICIENCY_COUNT_30D,
            NORMALIZATION_CAPS[INPUT_KEY_DEFICIENCY_COUNT_30D] * 5,
        )
        self.assertEqual(n, 1.0)

    def test_permit_days_inverts(self):
        # 0 days remaining = max risk on this axis.
        n_zero = rs_heuristic._normalize_input(
            INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION, 0,
        )
        self.assertEqual(n_zero, 1.0)
        # cap (30) days = no risk.
        n_safe = rs_heuristic._normalize_input(
            INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION,
            NORMALIZATION_CAPS[INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION],
        )
        self.assertEqual(n_safe, 0.0)
        # Negative (already expired) clamps to max risk.
        n_expired = rs_heuristic._normalize_input(
            INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION, -10,
        )
        self.assertEqual(n_expired, 1.0)

    def test_normalize_handles_none(self):
        self.assertEqual(rs_heuristic._normalize_input("anything", None), 0.0)


# ──────────────────────────────────────────────────────────────────
# Pure scoring math
# ──────────────────────────────────────────────────────────────────


class TestScoreFromInputs(unittest.TestCase):

    def test_clean_inputs_score_zero(self):
        self.assertEqual(rs_heuristic.score_from_inputs(_clean_inputs()), 0.0)

    def test_worst_inputs_score_one_hundred(self):
        self.assertEqual(rs_heuristic.score_from_inputs(_worst_inputs()), 100.0)

    def test_score_clamped_to_one_hundred(self):
        # Even with all inputs WAY past cap, score stays at 100.
        beyond_cap = {k: NORMALIZATION_CAPS[k] * 100 for k in INPUT_KEYS}
        beyond_cap[INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION] = -1000
        self.assertEqual(rs_heuristic.score_from_inputs(beyond_cap), 100.0)

    def test_score_bounded_below_at_zero(self):
        weird = {k: -100 for k in INPUT_KEYS}
        # Permit input inverts: -100 days = expired = max risk.
        # Other negative inputs clamp to 0. So the score will be
        # exactly the permit weight.
        s = rs_heuristic.score_from_inputs(weird)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_each_input_contributes_alone(self):
        """Increasing one input from 0 to its cap should add
        exactly that input's weight to the score (others held
        at clean)."""
        for key in INPUT_KEYS:
            inputs = _clean_inputs()
            inputs[key] = NORMALIZATION_CAPS[key]
            if key == INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION:
                # cap means safe, not unsafe. Use 0 (expired) instead.
                inputs[key] = 0
            score = rs_heuristic.score_from_inputs(inputs)
            self.assertAlmostEqual(
                score, WEIGHTS[key], places=4,
                msg=f"{key} alone should contribute {WEIGHTS[key]}",
            )

    def test_monotonic_in_violations(self):
        prev = -1.0
        for n in range(0, 8):
            inputs = _clean_inputs()
            inputs[INPUT_KEY_ACTIVE_DOB_VIOLATIONS] = float(n)
            s = rs_heuristic.score_from_inputs(inputs)
            self.assertGreaterEqual(s, prev,
                                    f"violations={n} regressed: {s} < {prev}")
            prev = s


# ──────────────────────────────────────────────────────────────────
# Bootstrap confidence interval
# ──────────────────────────────────────────────────────────────────


class TestBootstrapCI(unittest.TestCase):

    def test_low_le_high(self):
        inputs = _worst_inputs()
        low, high = rs_heuristic.bootstrap_confidence_interval(
            inputs, rng=random.Random(42),
        )
        self.assertLessEqual(low, high)

    def test_deterministic_with_seeded_rng(self):
        inputs = _worst_inputs()
        a = rs_heuristic.bootstrap_confidence_interval(
            inputs, rng=random.Random(42),
        )
        b = rs_heuristic.bootstrap_confidence_interval(
            inputs, rng=random.Random(42),
        )
        self.assertEqual(a, b)

    def test_zero_inputs_collapse_ci(self):
        """When every input is 0 (and permit_days is at cap), the
        score is deterministic 0; the CI must collapse to (0, 0)."""
        low, high = rs_heuristic.bootstrap_confidence_interval(
            _clean_inputs(), rng=random.Random(0),
        )
        self.assertEqual(low, 0.0)
        self.assertEqual(high, 0.0)

    def test_ci_contains_point_estimate_for_typical_input(self):
        # Pick a moderate input vector, run bootstrap, verify the
        # point estimate lies inside the 95% CI most of the time.
        # Flat assertion: low ≤ point ≤ high for at least 90% of
        # 50 RNG seeds.
        inputs = {
            INPUT_KEY_ACTIVE_DOB_VIOLATIONS:        2.0,
            INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION:   15.0,
            INPUT_KEY_INSPECTION_COMPLIANCE_MISSED: 1.0,
            INPUT_KEY_DEFICIENCY_COUNT_30D:         5.0,
            INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP:  1.0,
            INPUT_KEY_MISSING_LOGS_30D:             3.0,
            INPUT_KEY_SST_EXPIRATIONS_NEXT_30D:     8.0,
            INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY:     2.0,
        }
        point = rs_heuristic.score_from_inputs(inputs)
        contained = 0
        for seed in range(50):
            low, high = rs_heuristic.bootstrap_confidence_interval(
                inputs, rng=random.Random(seed),
            )
            if low <= point <= high:
                contained += 1
        self.assertGreaterEqual(contained, 45,
                                f"point in CI {contained}/50 seeds")

    def test_bootstrap_samples_constant_pinned(self):
        # The spec is non-negotiable: 1000 samples or document why.
        self.assertEqual(rs_heuristic.BOOTSTRAP_SAMPLES, 1000)
        self.assertEqual(rs_heuristic.CONFIDENCE_INTERVAL_PCT, 95)


# ──────────────────────────────────────────────────────────────────
# Top contributing factors
# ──────────────────────────────────────────────────────────────────


class TestTopContributingFactors(unittest.TestCase):

    def test_returns_top_5_by_default(self):
        factors = rs_heuristic.top_contributing_factors(_worst_inputs())
        self.assertEqual(len(factors), 5)

    def test_ordered_by_contribution_desc(self):
        factors = rs_heuristic.top_contributing_factors(_worst_inputs())
        contribs = [f["contribution"] for f in factors]
        self.assertEqual(contribs, sorted(contribs, reverse=True))

    def test_violations_first_in_worst_case(self):
        factors = rs_heuristic.top_contributing_factors(_worst_inputs())
        self.assertEqual(factors[0]["factor"], INPUT_KEY_ACTIVE_DOB_VIOLATIONS)

    def test_zero_inputs_returns_zero_contributions(self):
        factors = rs_heuristic.top_contributing_factors(_clean_inputs())
        for f in factors:
            self.assertEqual(f["contribution"], 0.0)

    def test_factor_record_has_expected_fields(self):
        factors = rs_heuristic.top_contributing_factors(_worst_inputs())
        for f in factors:
            self.assertIn("factor", f)
            self.assertIn("weight", f)
            self.assertIn("value", f)
            self.assertIn("contribution", f)
            self.assertIn("normalized", f)


# ──────────────────────────────────────────────────────────────────
# End-to-end pure scorer
# ──────────────────────────────────────────────────────────────────


class TestCalculateRiskScore(unittest.TestCase):

    def test_returns_score_ci_factors_breakdown(self):
        result = rs_heuristic.calculate_risk_score(
            _worst_inputs(), rng=random.Random(0),
        )
        self.assertIn("score", result)
        self.assertIn("confidence_low", result)
        self.assertIn("confidence_high", result)
        self.assertIn("contributing_factors", result)
        self.assertIn("all_factors", result)

    def test_all_factors_includes_every_input(self):
        result = rs_heuristic.calculate_risk_score(_worst_inputs())
        keys = [f["factor"] for f in result["all_factors"]]
        for k in INPUT_KEYS:
            self.assertIn(k, keys)

    def test_clean_inputs_score_zero_ci_zero(self):
        result = rs_heuristic.calculate_risk_score(_clean_inputs())
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["confidence_low"], 0.0)
        self.assertEqual(result["confidence_high"], 0.0)


# ──────────────────────────────────────────────────────────────────
# gather_inputs (DB side)
# ──────────────────────────────────────────────────────────────────


def _make_gather_db(*, dob_logs=None, logbook_entries=None,
                   subs=None, workers=None, daily_logs=None):
    """Build a MagicMock DB that satisfies gather_inputs() queries."""
    db = MagicMock()

    db.dob_logs = MagicMock()
    db.dob_logs.count_documents = AsyncMock(return_value=0)
    db.dob_logs.find = MagicMock(return_value=_AsyncCursor(dob_logs or []))

    db.logbook_entries = MagicMock()

    def _logbook_count(query):
        # Simulate the two queries: deficiency count + missing count.
        async def _coro():
            cat = query.get("category")
            status = query.get("status")
            if cat == "deficiency":
                return sum(1 for e in (logbook_entries or [])
                           if e.get("category") == "deficiency")
            if cat == "daily_log" and status == "missing":
                return sum(1 for e in (logbook_entries or [])
                           if e.get("category") == "daily_log"
                           and e.get("status") == "missing")
            return 0
        return _coro()
    db.logbook_entries.count_documents = MagicMock(side_effect=_logbook_count)

    db.subcontractors = MagicMock()
    db.subcontractors.find = MagicMock(return_value=_AsyncCursor(subs or []))

    db.workers = MagicMock()
    db.workers.find = MagicMock(return_value=_AsyncCursor(workers or []))

    db.daily_logs = MagicMock()
    db.daily_logs.find = MagicMock(return_value=_AsyncCursor(daily_logs or []))

    return db


class TestGatherInputs(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
        self.project = {
            "_id": "p1", "company_id": "co_a",
            "nyc_bin": "1234567",
            "inspection_windows": [],
        }

    def test_clean_project_yields_no_risk_inputs(self):
        db = _make_gather_db()
        out = _run(rs_heuristic.gather_inputs(
            db, project=self.project, now=self.now,
        ))
        # No DOB violations, no permits (defaults to cap = no risk),
        # no logbook entries, no subs, no workers, no daily logs.
        self.assertEqual(out[INPUT_KEY_ACTIVE_DOB_VIOLATIONS], 0.0)
        self.assertEqual(out[INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION], 30.0)
        self.assertEqual(out[INPUT_KEY_INSPECTION_COMPLIANCE_MISSED], 0.0)
        self.assertEqual(out[INPUT_KEY_DEFICIENCY_COUNT_30D], 0.0)
        self.assertEqual(out[INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP], 0.0)
        self.assertEqual(out[INPUT_KEY_MISSING_LOGS_30D], 0.0)
        self.assertEqual(out[INPUT_KEY_SST_EXPIRATIONS_NEXT_30D], 0.0)
        # No activity at all → 0 staleness (we never observed any).
        self.assertEqual(out[INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY], 0.0)

    def test_violation_count_pulled_from_dob_logs(self):
        db = _make_gather_db()
        db.dob_logs.count_documents = AsyncMock(return_value=3)
        out = _run(rs_heuristic.gather_inputs(
            db, project=self.project, now=self.now,
        ))
        self.assertEqual(out[INPUT_KEY_ACTIVE_DOB_VIOLATIONS], 3.0)

    def test_permit_min_days_to_expiration(self):
        permits = [
            {"signal_kind": "permit_issued", "expiration_date": "2026-05-20"},  # +13d
            {"signal_kind": "permit_renewed", "expiration_date": "2026-05-12"},  #  +5d
            {"signal_kind": "permit_issued", "expiration_date": "2026-06-30"},  # +54d
        ]
        db = _make_gather_db(dob_logs=permits)
        out = _run(rs_heuristic.gather_inputs(
            db, project=self.project, now=self.now,
        ))
        self.assertEqual(out[INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION], 5.0)

    def test_inspection_windows_missed(self):
        proj = dict(self.project, inspection_windows=[
            {"name": "fa1", "by_date": "2026-05-01", "done": False},  # missed
            {"name": "fa2", "by_date": "2026-05-10", "done": False},  # future
            {"name": "fa3", "by_date": "2026-04-30", "done": True},   # done
            {"name": "fa4", "by_date": "2026-04-15", "done": False},  # missed
        ])
        db = _make_gather_db()
        out = _run(rs_heuristic.gather_inputs(
            db, project=proj, now=self.now,
        ))
        self.assertEqual(out[INPUT_KEY_INSPECTION_COMPLIANCE_MISSED], 2.0)

    def test_deficiency_count_from_logbook(self):
        entries = [
            {"category": "deficiency"}, {"category": "deficiency"},
            {"category": "deficiency"}, {"category": "daily_log"},
        ]
        db = _make_gather_db(logbook_entries=entries)
        out = _run(rs_heuristic.gather_inputs(
            db, project=self.project, now=self.now,
        ))
        self.assertEqual(out[INPUT_KEY_DEFICIENCY_COUNT_30D], 3.0)

    def test_subcontractor_insurance_expirations(self):
        subs = [
            {"company_id": "co_a", "coi_on_file": False},                  # +1
            {"company_id": "co_a", "coi_on_file": True,
             "coi_expiration": "2026-05-15"},                              # +1 (≤30d)
            {"company_id": "co_a", "coi_on_file": True,
             "coi_expiration": "2027-01-01"},                              # safe
        ]
        db = _make_gather_db(subs=subs)
        out = _run(rs_heuristic.gather_inputs(
            db, project=self.project, now=self.now,
        ))
        self.assertEqual(out[INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP], 2.0)

    def test_missing_logs_count_from_logbook(self):
        entries = [
            {"category": "daily_log", "status": "missing"},
            {"category": "daily_log", "status": "missing"},
            {"category": "daily_log", "status": "complete"},
        ]
        db = _make_gather_db(logbook_entries=entries)
        out = _run(rs_heuristic.gather_inputs(
            db, project=self.project, now=self.now,
        ))
        self.assertEqual(out[INPUT_KEY_MISSING_LOGS_30D], 2.0)

    def test_sst_expirations_distinct_workers(self):
        # Two workers with SST in the next 30 days; one beyond.
        workers = [
            {"company_id": "co_a", "certifications": [
                {"type": "SST_FULL", "expiration_date": "2026-05-20"},
            ]},
            {"company_id": "co_a", "certifications": [
                {"type": "SST_LIMITED", "expiration_date": "2026-05-25"},
            ]},
            {"company_id": "co_a", "certifications": [
                {"type": "SST_FULL", "expiration_date": "2027-01-01"},
            ]},
        ]
        db = _make_gather_db(workers=workers)
        out = _run(rs_heuristic.gather_inputs(
            db, project=self.project, now=self.now,
        ))
        self.assertEqual(out[INPUT_KEY_SST_EXPIRATIONS_NEXT_30D], 2.0)


# ──────────────────────────────────────────────────────────────────
# Calibration: brier + roc_auc + log_inspector_review + aggregator
# ──────────────────────────────────────────────────────────────────


class TestBrierAndAUC(unittest.TestCase):

    def test_brier_perfect_predictions(self):
        samples = [
            {"predicted_prob": 1.0, "observed_label": 1},
            {"predicted_prob": 0.0, "observed_label": 0},
            {"predicted_prob": 1.0, "observed_label": 1},
        ]
        self.assertEqual(rs_calibration.brier_score(samples), 0.0)

    def test_brier_chance_baseline(self):
        # Predicting 0.5 for every sample yields Brier = 0.25.
        samples = [
            {"predicted_prob": 0.5, "observed_label": 1},
            {"predicted_prob": 0.5, "observed_label": 0},
            {"predicted_prob": 0.5, "observed_label": 1},
            {"predicted_prob": 0.5, "observed_label": 0},
        ]
        self.assertAlmostEqual(rs_calibration.brier_score(samples), 0.25)

    def test_brier_empty_returns_zero(self):
        self.assertEqual(rs_calibration.brier_score([]), 0.0)

    def test_roc_auc_perfect_separation(self):
        samples = [
            {"predicted_prob": 0.9, "observed_label": 1},
            {"predicted_prob": 0.8, "observed_label": 1},
            {"predicted_prob": 0.2, "observed_label": 0},
            {"predicted_prob": 0.1, "observed_label": 0},
        ]
        self.assertEqual(rs_calibration.roc_auc(samples), 1.0)

    def test_roc_auc_inverted_predictions(self):
        samples = [
            {"predicted_prob": 0.1, "observed_label": 1},
            {"predicted_prob": 0.2, "observed_label": 1},
            {"predicted_prob": 0.8, "observed_label": 0},
            {"predicted_prob": 0.9, "observed_label": 0},
        ]
        self.assertEqual(rs_calibration.roc_auc(samples), 0.0)

    def test_roc_auc_only_one_class_returns_chance(self):
        samples = [
            {"predicted_prob": 0.9, "observed_label": 1},
            {"predicted_prob": 0.8, "observed_label": 1},
        ]
        self.assertEqual(rs_calibration.roc_auc(samples), 0.5)


def _wire_collection_dispatch(db, **collections):
    """Helper: route db[name] lookups to per-name MagicMocks.
    MagicMock's __setitem__ doesn't persist for __getitem__, so
    we install a side_effect on __getitem__ instead."""
    db.__getitem__.side_effect = lambda name: collections.get(
        name, MagicMock(),
    )
    return db


class TestLogInspectorReview(unittest.TestCase):

    def test_inserts_review_with_score_metadata(self):
        score_doc = {
            "_id": "score_1",
            "model_version": "heuristic-v1",
            "score": 75.0,
        }
        scores_mock = MagicMock()
        scores_mock.find_one = AsyncMock(return_value=score_doc)

        reviews_mock = MagicMock()
        reviews_mock.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="review_1"),
        )
        db = _wire_collection_dispatch(
            MagicMock(),
            **{
                rs_schema.RISK_SCORES_COLLECTION:        scores_mock,
                rs_schema.RISK_SCORE_REVIEWS_COLLECTION: reviews_mock,
            },
        )

        record = _run(rs_calibration.log_inspector_review(
            db,
            score_id="score_1", project_id="p1",
            was_high_risk_correct=True, notes="looks right",
            reviewed_by_user_id="u_admin",
        ))
        self.assertEqual(record["score_id"], "score_1")
        self.assertEqual(record["model_version"], "heuristic-v1")
        self.assertTrue(record["was_high_risk_correct"])
        self.assertEqual(record["notes"], "looks right")
        self.assertEqual(reviews_mock.insert_one.await_count, 1)


class TestComputeCalibrationStats(unittest.TestCase):

    def test_aggregates_brier_and_auc_from_reviews(self):
        # 4 reviews, 2 high-risk-correct + 2 low-risk-correct.
        reviews = [
            {"score_id": "s_h_correct", "model_version": "heuristic-v1",
             "was_high_risk_correct": True},
            {"score_id": "s_h_wrong",   "model_version": "heuristic-v1",
             "was_high_risk_correct": False},
            {"score_id": "s_l_correct", "model_version": "heuristic-v1",
             "was_high_risk_correct": True},
            {"score_id": "s_l_wrong",   "model_version": "heuristic-v1",
             "was_high_risk_correct": False},
        ]
        scores_by_id = {
            "s_h_correct": {"_id": "s_h_correct", "score": 80.0,
                            "model_version": "heuristic-v1"},
            "s_h_wrong":   {"_id": "s_h_wrong",   "score": 90.0,
                            "model_version": "heuristic-v1"},
            "s_l_correct": {"_id": "s_l_correct", "score": 10.0,
                            "model_version": "heuristic-v1"},
            "s_l_wrong":   {"_id": "s_l_wrong",   "score": 20.0,
                            "model_version": "heuristic-v1"},
        }
        scores_mock = MagicMock()
        async def _find_score(query):
            return scores_by_id.get(query.get("_id"))
        scores_mock.find_one = MagicMock(side_effect=_find_score)
        reviews_mock = MagicMock()
        reviews_mock.find = MagicMock(return_value=_AsyncCursor(reviews))
        db = _wire_collection_dispatch(
            MagicMock(),
            **{
                rs_schema.RISK_SCORES_COLLECTION:        scores_mock,
                rs_schema.RISK_SCORE_REVIEWS_COLLECTION: reviews_mock,
            },
        )

        stats = _run(rs_calibration.compute_calibration_stats(
            db, model_version="heuristic-v1",
        ))
        self.assertEqual(stats["model_version"], "heuristic-v1")
        self.assertEqual(stats["sample_size"], 4)
        self.assertEqual(stats["inspector_review_count"], 4)
        # Brier + ROC-AUC are floats in [0, 1].
        self.assertGreaterEqual(stats["brier_score"], 0.0)
        self.assertLessEqual(stats["brier_score"], 1.0)
        self.assertGreaterEqual(stats["roc_auc"], 0.0)
        self.assertLessEqual(stats["roc_auc"], 1.0)


# ──────────────────────────────────────────────────────────────────
# Orchestrator (idempotency + force=True)
# ──────────────────────────────────────────────────────────────────


def _orchestrator_db_with_score(*, recent_score=None,
                                inserted_id="new_score_id"):
    db = _make_gather_db()
    risk_scores_mock = MagicMock()
    risk_scores_mock.find = MagicMock(
        return_value=_AsyncCursor([recent_score] if recent_score else []),
    )
    risk_scores_mock.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=inserted_id),
    )
    db.__getitem__.side_effect = lambda name: (
        risk_scores_mock
        if name == rs_schema.RISK_SCORES_COLLECTION
        else MagicMock()
    )
    db.risk_scores = risk_scores_mock
    db.projects = MagicMock()
    return db


class TestOrchestrator(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
        self.project = {"_id": "p1", "company_id": "co_a",
                        "inspection_windows": []}

    def test_writes_score_when_no_recent_doc(self):
        db = _orchestrator_db_with_score()
        doc = _run(rs_orchestrator.run_risk_score_for_project(
            db, project=self.project, now=self.now,
        ))
        self.assertIsNotNone(doc)
        self.assertEqual(doc["project_id"], "p1")
        self.assertEqual(doc["model_version"], "heuristic-v1")
        self.assertIn("inputs_snapshot", doc)
        self.assertIn("contributing_factors", doc)
        self.assertEqual(
            db.risk_scores.insert_one.await_count, 1,
        )

    def test_freshness_check_blocks_within_12_hours(self):
        recent = {
            "_id": "old", "project_id": "p1",
            "calculated_at": self.now - timedelta(hours=3),
            "score": 50.0, "model_version": "heuristic-v1",
        }
        db = _orchestrator_db_with_score(recent_score=recent)
        result = _run(rs_orchestrator.run_risk_score_for_project(
            db, project=self.project, now=self.now,
        ))
        self.assertIsNone(result)
        self.assertEqual(
            db.risk_scores.insert_one.await_count, 0,
        )

    def test_freshness_check_passes_after_12_hours(self):
        old = {
            "_id": "old", "project_id": "p1",
            "calculated_at": self.now - timedelta(hours=20),
            "score": 50.0, "model_version": "heuristic-v1",
        }
        # Old score is OUTSIDE the 12h window — find returns empty.
        db = _orchestrator_db_with_score()  # no recent
        # The orchestrator's _has_recent_score query filters by
        # calculated_at >= cutoff. With no in-window doc the cursor
        # is empty, so the helper returns False; old doc doesn't
        # block.
        doc = _run(rs_orchestrator.run_risk_score_for_project(
            db, project=self.project, now=self.now,
        ))
        self.assertIsNotNone(doc)

    def test_force_bypasses_freshness_check(self):
        recent = {
            "_id": "old", "project_id": "p1",
            "calculated_at": self.now - timedelta(hours=1),
            "score": 50.0, "model_version": "heuristic-v1",
        }
        db = _orchestrator_db_with_score(recent_score=recent)
        doc = _run(rs_orchestrator.run_risk_score_for_project(
            db, project=self.project, force=True, now=self.now,
        ))
        self.assertIsNotNone(doc)
        self.assertEqual(
            db.risk_scores.insert_one.await_count, 1,
        )

    def test_freshness_window_pinned_at_12h(self):
        # The constant is referenced by the freshness check in
        # _has_recent_score; pinning it surfaces an accidental
        # change to a wider/narrower window.
        self.assertEqual(rs_orchestrator.SCORE_FRESHNESS_HOURS, 12)


# ──────────────────────────────────────────────────────────────────
# Endpoints — feature-flag gating
# ──────────────────────────────────────────────────────────────────


def _setup_authed_client(*, role="admin", user_id="u_x", company_id="co_a"):
    import server
    user = {"id": user_id, "_id": user_id,
            "role": role, "company_id": company_id}
    async def _fake_user():
        return user
    server.app.dependency_overrides[server.get_current_user] = _fake_user
    if hasattr(server, "get_admin_user"):
        server.app.dependency_overrides[server.get_admin_user] = _fake_user
    return TestClient(server.app, raise_server_exceptions=False), \
        lambda: server.app.dependency_overrides.clear()


def _build_endpoint_db(*, flag_doc=None, scores=None, reviews=None,
                       project_doc=None):
    db = _make_gather_db()
    db.feature_flags = MagicMock()
    db.feature_flags.find_one = AsyncMock(return_value=flag_doc)
    score_list = list(scores or [])

    # Build the named-collection mocks separately so __getitem__
    # dispatch can hand them out by name. MagicMock's __setitem__
    # does NOT persist for __getitem__ retrieval, so we wire
    # side_effect explicitly.
    risk_scores_mock = MagicMock()
    risk_scores_mock.find = MagicMock(
        side_effect=lambda *a, **k: _AsyncCursor(list(score_list)),
    )
    risk_scores_mock.find_one = AsyncMock(
        return_value=score_list[0] if score_list else None,
    )
    risk_scores_mock.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="new_score"),
    )

    reviews_mock = MagicMock()
    reviews_mock.find = MagicMock(
        return_value=_AsyncCursor(list(reviews or [])),
    )
    reviews_mock.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="new_review"),
    )

    calibration_mock = MagicMock()

    collection_dispatch = {
        rs_schema.RISK_SCORES_COLLECTION:            risk_scores_mock,
        rs_schema.RISK_SCORE_REVIEWS_COLLECTION:     reviews_mock,
        rs_schema.RISK_SCORE_CALIBRATION_COLLECTION: calibration_mock,
    }
    db.__getitem__.side_effect = lambda name: collection_dispatch.get(
        name, MagicMock(),
    )
    # Also expose them as attributes so attribute-access paths
    # (db.risk_scores...) resolve to the same mock.
    db.risk_scores = risk_scores_mock
    db.risk_score_reviews = reviews_mock
    db.risk_score_calibration = calibration_mock

    db.projects = MagicMock()
    db.projects.find_one = AsyncMock(
        return_value=project_doc or {
            "_id": "p1", "name": "Test", "company_id": "co_a",
            "inspection_windows": [],
        },
    )
    return db


class TestEndpointsFlagDisabled(unittest.TestCase):
    """Every risk-score endpoint MUST 404 when the flag is off —
    same security-parity contract as V2.0 logbook endpoints."""

    def setUp(self):
        feature_flags.cache_invalidate(None)

    def tearDown(self):
        feature_flags.cache_invalidate(None)

    def _check_404(self, method, path, **kwargs):
        import server
        db = _build_endpoint_db(flag_doc=None)
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                fn = getattr(client, method.lower())
                r = fn(path, **kwargs)
                self.assertEqual(r.status_code, 404, r.text)
        finally:
            restore()

    def test_get_risk_score_404(self):
        self._check_404("GET", "/api/projects/p1/risk-score")

    def test_get_history_404(self):
        self._check_404("GET", "/api/projects/p1/risk-score/history")

    def test_post_calculate_404(self):
        self._check_404("POST", "/api/projects/p1/risk-score/calculate")

    def test_post_calibration_404(self):
        self._check_404(
            "POST", "/api/projects/p1/risk-score/calibration",
            json={"score_id": "s1", "was_high_risk_correct": True},
        )

    def test_get_admin_calibration_404(self):
        self._check_404("GET", "/api/admin/risk-score/calibration")


class TestEndpointsFlagEnabled(unittest.TestCase):

    def setUp(self):
        feature_flags.cache_invalidate(None)

    def tearDown(self):
        feature_flags.cache_invalidate(None)

    @staticmethod
    def _flag_on():
        return {
            "flag": "v2_risk_score", "enabled_globally": True,
            "enabled_for_companies": [], "enabled_for_users": [],
            "enabled_percentage": 0,
        }

    def test_get_returns_latest_score(self):
        import server
        score = {
            "_id": "score_1", "project_id": "p1", "company_id": "co_a",
            "score": 42.0, "confidence_low": 38.0, "confidence_high": 47.0,
            "contributing_factors": [],
            "model_version": "heuristic-v1",
            "calculated_at": datetime(2026, 5, 7, tzinfo=timezone.utc),
        }
        db = _build_endpoint_db(flag_doc=self._flag_on(), scores=[score])
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.get("/api/projects/p1/risk-score")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertIn("score", body)
                self.assertEqual(body["score"]["score"], 42.0)
        finally:
            restore()

    def test_history_returns_list(self):
        import server
        scores = [
            {"_id": f"s{i}", "project_id": "p1", "company_id": "co_a",
             "score": float(i * 10), "model_version": "heuristic-v1",
             "calculated_at": datetime(2026, 5, 7 - i, tzinfo=timezone.utc)}
            for i in range(3)
        ]
        db = _build_endpoint_db(flag_doc=self._flag_on(), scores=scores)
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.get("/api/projects/p1/risk-score/history?days=30")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertIn("history", body)
                self.assertEqual(len(body["history"]), 3)
        finally:
            restore()

    def test_calculate_writes_new_score(self):
        import server
        db = _build_endpoint_db(flag_doc=self._flag_on(), scores=[])
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.post("/api/projects/p1/risk-score/calculate")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertIn("score", body)
                self.assertEqual(
                    db.risk_scores.insert_one.await_count, 1,
                )
        finally:
            restore()

    def test_calibration_post_writes_review(self):
        import server
        score = {
            "_id": "score_1", "project_id": "p1", "company_id": "co_a",
            "score": 70.0, "model_version": "heuristic-v1",
            "calculated_at": datetime(2026, 5, 7, tzinfo=timezone.utc),
        }
        db = _build_endpoint_db(flag_doc=self._flag_on(), scores=[score])
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/projects/p1/risk-score/calibration",
                    json={
                        "score_id": "score_1",
                        "was_high_risk_correct": True,
                        "notes": "looks correct",
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(
                    db.risk_score_reviews.insert_one.await_count, 1,
                )
        finally:
            restore()

    def test_calibration_rejects_missing_score_id(self):
        import server
        db = _build_endpoint_db(flag_doc=self._flag_on())
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/projects/p1/risk-score/calibration",
                    json={"score_id": "", "was_high_risk_correct": True},
                )
                self.assertEqual(r.status_code, 422, r.text)
        finally:
            restore()

    def test_admin_calibration_returns_stats(self):
        import server
        db = _build_endpoint_db(flag_doc=self._flag_on())
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.get("/api/admin/risk-score/calibration")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertIn("calibration", body)
                cal = body["calibration"]
                self.assertEqual(cal["model_version"], "heuristic-v1")
                self.assertIn("brier_score", cal)
                self.assertIn("roc_auc", cal)
                self.assertIn("sample_size", cal)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# Frontend — RiskScoreCard static-source pins
# ──────────────────────────────────────────────────────────────────


class TestFrontendRiskScoreCard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCard.jsx"
        )
        cls.text = (
            cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""
        )

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_uses_feature_flag_hook(self):
        self.assertIn("useFeatureFlag('v2_risk_score')", self.text)

    def test_flag_check_is_first_hook(self):
        """Rules-of-hooks: useFeatureFlag must be the FIRST hook
        called in the component body. C1.3 incident pattern."""
        comp_idx = self.text.find("const RiskScoreCard = (")
        self.assertGreater(comp_idx, 0)
        body_open = self.text.find("{", comp_idx)
        flag_idx = self.text.find("useFeatureFlag", body_open)
        other_hooks = ("useTheme(", "useState(", "useEffect(", "useMemo(")
        first_other = min(
            (self.text.find(h, body_open) for h in other_hooks
             if self.text.find(h, body_open) > 0),
            default=-1,
        )
        self.assertGreater(flag_idx, 0, "useFeatureFlag missing")
        self.assertGreater(first_other, 0)
        self.assertLess(
            flag_idx, first_other,
            "useFeatureFlag must be the FIRST hook (rules-of-hooks)",
        )

    def test_returns_null_when_flag_disabled(self):
        """Flag-off render path = `return null`. No spinner, no
        placeholder. v1 users see no v2 UI flicker."""
        self.assertIn("if (!v2RiskScoreEnabled)", self.text)
        flag_check = self.text.find("if (!v2RiskScoreEnabled)")
        next_return = self.text.find("return null", flag_check)
        self.assertGreater(next_return, flag_check)

    def test_calls_calibration_endpoint(self):
        self.assertIn(
            "/api/projects/${projectId}/risk-score/calibration",
            self.text,
        )

    def test_calls_history_endpoint(self):
        self.assertIn(
            "/api/projects/${projectId}/risk-score/history",
            self.text,
        )

    def test_uses_design_system(self):
        self.assertIn("GlassCard", self.text)
        self.assertIn("useTheme", self.text)


class TestProjectDetailMount(unittest.TestCase):
    """RiskScoreCard must be imported AND rendered in
    project/[id].jsx — otherwise the gating works but no v2
    customer ever sees the score."""

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / "frontend" / "app" / "project" / "[id].jsx"
        cls.text = (
            cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""
        )

    def test_imports_risk_score_card(self):
        self.assertIn("import RiskScoreCard", self.text)

    def test_mounts_risk_score_card(self):
        self.assertIn("<RiskScoreCard", self.text)

    def test_passes_projectid_prop(self):
        # Mount must include projectId={projectId} so the card can
        # fetch its data.
        idx = self.text.find("<RiskScoreCard")
        close = self.text.find("/>", idx)
        snippet = self.text[idx:close + 2]
        self.assertIn("projectId={projectId}", snippet)


# ──────────────────────────────────────────────────────────────────
# server.py wiring (static-source pins)
# ──────────────────────────────────────────────────────────────────


class TestServerWiring(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_risk_score_helper_present(self):
        self.assertIn("_risk_score_flag_enabled_for", self.text)
        self.assertIn('"v2_risk_score"', self.text)

    def test_endpoints_flag_gated(self):
        # Each endpoint must call the flag helper.
        endpoints = (
            "/projects/{project_id}/risk-score",
            "/projects/{project_id}/risk-score/history",
            "/projects/{project_id}/risk-score/calculate",
            "/projects/{project_id}/risk-score/calibration",
            "/admin/risk-score/calibration",
        )
        for path in endpoints:
            self.assertIn(path, self.text, f"endpoint {path} missing")
        # And the helper is invoked enough times — once per
        # endpoint at minimum.
        self.assertGreaterEqual(
            self.text.count("await _risk_score_flag_enabled_for"),
            5,
            "every endpoint must gate on _risk_score_flag_enabled_for",
        )

    def test_scheduler_tick_4am_et(self):
        self.assertIn("v2_risk_score_daily_tick", self.text)
        self.assertIn(
            'CronTrigger(hour=4, minute=0, timezone="America/New_York")',
            self.text,
        )

    def test_scheduler_tick_globally_gated(self):
        # Must check the global flag before walking projects.
        s = self.text.find("async def _risk_score_daily_tick")
        self.assertGreater(s, 0)
        e = self.text.find("scheduler.add_job", s)
        slice_ = self.text[s:e]
        self.assertIn("is_feature_enabled", slice_)
        self.assertIn("v2_risk_score", slice_)

    def test_indexes_registered_for_three_collections(self):
        # All three risk_score-related collections must have their
        # indexes registered at startup.
        self.assertIn("RISK_SCORES_INDEXES", self.text)
        self.assertIn("RISK_SCORE_REVIEWS_INDEXES", self.text)
        self.assertIn("RISK_SCORE_CALIBRATION_INDEXES", self.text)


if __name__ == "__main__":
    unittest.main()
