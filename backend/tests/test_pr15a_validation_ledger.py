"""PR #15A Stage 2.B — prediction_validation_ledger schema tests.

The validation ledger captures one canonical record per
(project_id, calendar_date) tracking predicted_probability,
observed_outcome (scored at horizon), and brier_score_delta.

Rolling 30-day Brier score aggregation per project drives the
structural-recalibration alert (threshold = 0.20).

Per Stage 2.A T7 lock: one entry per (project_id, calendar_date).
Subsequent intra-day predictions UPSERT (not insert) the canonical
entry.

3 tests in TestPredictionValidationLedger:
  1. test_validation_ledger_indexes_align_with_audit_cron_query
  2. test_one_canonical_entry_per_project_per_day
  3. test_rolling_30d_brier_score_aggregation

All 3 RED at Stage 2.B. Stage 3 lands:
  • PREDICTION_VALIDATION_LEDGER_COLLECTION constant
  • PREDICTION_VALIDATION_LEDGER_INDEXES tuple
  • _upsert_validation_ledger_entry helper
  • compute_rolling_30d_brier helper
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# ─── Lazy imports for PR #15A symbols ──────────────────────────────

try:
    from lib.statistical_engine.schema import (  # type: ignore
        PREDICTION_VALIDATION_LEDGER_COLLECTION,
        PREDICTION_VALIDATION_LEDGER_INDEXES,
    )
    HAS_LEDGER_SCHEMA = True
except ImportError:
    PREDICTION_VALIDATION_LEDGER_COLLECTION = None  # type: ignore
    PREDICTION_VALIDATION_LEDGER_INDEXES = None  # type: ignore
    HAS_LEDGER_SCHEMA = False


try:
    from lib.statistical_engine.daily_panel import (  # type: ignore
        _upsert_validation_ledger_entry,
        compute_rolling_30d_brier,
    )
    HAS_LEDGER_HELPERS = True
except ImportError:
    _upsert_validation_ledger_entry = None  # type: ignore
    compute_rolling_30d_brier = None  # type: ignore
    HAS_LEDGER_HELPERS = False


# ─── Test infrastructure imports ──────────────────────────────────

from _pr14b_fixtures import (  # noqa: E402
    seed_validation_ledger_entries,
)
from _pr15a_panel_fixtures import (  # noqa: E402
    _StubDb,
    _StubPredictionValidationLedger,
)


# ──────────────────────────────────────────────────────────────────
# Test class
# ──────────────────────────────────────────────────────────────────


class TestPredictionValidationLedger(unittest.TestCase):
    """PR #15A — 3 tests for the prediction_validation_ledger
    collection schema + upsert flow + rolling Brier aggregation."""

    def _require_schema(self):
        if not HAS_LEDGER_SCHEMA:
            self.fail(
                "lib.statistical_engine.schema.PREDICTION_VALIDATION_LEDGER_"
                "COLLECTION + _INDEXES not defined. Stage 3 PR #15A "
                "schema additions: add "
                "``PREDICTION_VALIDATION_LEDGER_COLLECTION = "
                "'prediction_validation_ledger'`` plus the "
                "PREDICTION_VALIDATION_LEDGER_INDEXES tuple covering "
                "(target_horizon_at, asc) for the daily audit cron "
                "AND (project_id, prediction_timestamp desc) for "
                "per-project history queries."
            )

    def _require_helpers(self):
        if not HAS_LEDGER_HELPERS:
            self.fail(
                "lib.statistical_engine.daily_panel."
                "_upsert_validation_ledger_entry + "
                "compute_rolling_30d_brier not implemented. Stage 3 "
                "PR #15A: ledger helpers in daily_panel.py."
            )

    # ──────────────────────────────────────────────────────────
    # Test 1 — indexes align with audit cron query
    # ──────────────────────────────────────────────────────────

    def test_validation_ledger_indexes_align_with_audit_cron_query(self):
        """The audit cron walks predictions whose
        ``target_horizon_at`` is <= today; the per-project history
        view filters by (project_id, prediction_timestamp desc);
        the rolling-30d brier aggregation matches
        (project_id, scored_at >= now-30d).

        Verify the index specs declared in schema.py cover these
        three access patterns.
        """
        self._require_schema()
        index_names = {
            spec.get("name") for spec in PREDICTION_VALIDATION_LEDGER_INDEXES
        }

        # (1) target_horizon_at index for the daily audit walk.
        target_horizon_keys = [
            tuple(spec.get("keys") or []) for spec in PREDICTION_VALIDATION_LEDGER_INDEXES
            if any(k[0] == "target_horizon_at" for k in (spec.get("keys") or []))
        ]
        self.assertTrue(
            len(target_horizon_keys) > 0,
            f"Audit cron index missing. Stage 3: add index on "
            f"``target_horizon_at`` so the daily audit can "
            f"efficiently $match: target_horizon_at <= today AND "
            f"observed_outcome is null. Got index names: "
            f"{index_names!r}",
        )

        # (2) Per-project history index.
        project_history = [
            spec for spec in PREDICTION_VALIDATION_LEDGER_INDEXES
            if any(k[0] == "project_id" for k in (spec.get("keys") or []))
        ]
        self.assertTrue(
            len(project_history) > 0,
            f"Per-project history index missing. Stage 3: add "
            f"compound index (project_id, prediction_timestamp -1). "
            f"Got: {index_names!r}",
        )

        # (3) Collection name uses the locked constant string.
        self.assertEqual(
            PREDICTION_VALIDATION_LEDGER_COLLECTION,
            "prediction_validation_ledger",
            f"Constant collection name must equal "
            f"'prediction_validation_ledger'. Got: "
            f"{PREDICTION_VALIDATION_LEDGER_COLLECTION!r}",
        )

    # ──────────────────────────────────────────────────────────
    # Test 2 — one canonical entry per (project_id, calendar_date)
    # ──────────────────────────────────────────────────────────

    def test_one_canonical_entry_per_project_per_day(self):
        """Stage 2.A T7 lock — one canonical record per
        (project_id, calendar_date). Subsequent intra-day predictions
        for the same day overwrite, not insert duplicates.

        Fixture: 5 intra-day predictions for project P_T7 on the
        same calendar_date. Final state must have 1 doc in the
        ledger with the LAST prediction's values.
        """
        self._require_helpers()
        db = _StubDb(prediction_validation_ledger=_StubPredictionValidationLedger())
        project_id = "P_T7_CANONICAL"
        calendar_date = "2026-05-15"
        cur_now = datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)

        for i in range(5):
            ts = cur_now + timedelta(hours=i * 2)  # 09:00, 11:00, 13:00, 15:00, 17:00
            _run(_upsert_validation_ledger_entry(
                db,
                project_id=project_id,
                calendar_date=calendar_date,
                prediction_timestamp=ts,
                predicted_probability=0.10 + 0.05 * i,  # 0.10, 0.15, 0.20, 0.25, 0.30
                x_features_snapshot={
                    "active_swo_flag":              0,
                    "complaint_velocity_14d":       i,
                    "days_since_last_violation":    90 - i,
                    "derived_lifecycle_stage_pct":  0.20,
                    "district_caseload_proxy_days": 7.0,
                },
                model_coefficients_hash="sha1-canon-test",
                target_horizon_days=7,
            ))

        ledger_docs = db.prediction_validation_ledger.docs
        self.assertEqual(
            len(ledger_docs), 1,
            f"PR #15A T7 lock — canonical-per-day. Expected 1 doc "
            f"after 5 intra-day upserts; got {len(ledger_docs)}. "
            f"Stage 3: ``_upsert_validation_ledger_entry`` must "
            f"call update_one(filter={{project_id, calendar_date}}, "
            f"upsert=True), NOT insert_one.",
        )
        final = ledger_docs[0]
        # Last write wins.
        self.assertAlmostEqual(
            final["predicted_probability"], 0.30,
            msg=(
                f"Last predicted_probability must overwrite earlier "
                f"intra-day values. Expected 0.30; got "
                f"{final['predicted_probability']}"
            ),
        )
        self.assertEqual(
            final["x_features_snapshot"]["complaint_velocity_14d"], 4,
            f"x_features_snapshot must reflect the most recent "
            f"prediction's state (i=4 → complaint_velocity_14d=4).",
        )

    # ──────────────────────────────────────────────────────────
    # Test 3 — rolling 30-day Brier score aggregation
    # ──────────────────────────────────────────────────────────

    def test_rolling_30d_brier_score_aggregation(self):
        """Per-project rolling 30-day Brier score:
          Brier = mean of (predicted - observed)² over scored entries
                  with scored_at >= now - 30d AND observed_outcome != None.

        Fixture (50 entries over 60 days):
          • 30 entries within last 30 days, ½ True (brier=0.04), ½ False (brier=0.36)
            → expected rolling mean = 0.20
          • 20 entries outside the 30-day window — must be excluded
          • One entry inside-window with observed_outcome=None — must
            be excluded by ``$ne: None`` clause
        """
        self._require_helpers()
        db = _StubDb(prediction_validation_ledger=_StubPredictionValidationLedger())
        project_id = "P_BRIER_ROLLING"
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)

        # 30 entries within last 30 days. Half observed True (predicted
        # 0.20 → brier (0.20-1)² = 0.64) — actually we want exact 0.04
        # and 0.36. Let predicted=0.8 → observed True → brier = (0.8-1)² = 0.04
        # Let predicted=0.6 → observed False → brier = (0.6-0)² = 0.36
        prediction_timestamps_30 = [
            cur_now - timedelta(days=i)
            for i in range(30)
        ]
        brier_30 = [0.04 if i % 2 == 0 else 0.36 for i in range(30)]
        observed_30 = [(True if i % 2 == 0 else False) for i in range(30)]
        seed_validation_ledger_entries(
            db,
            project_id=project_id,
            n_entries=30,
            prediction_timestamps=prediction_timestamps_30,
            brier_distribution=brier_30,
            observed_outcomes=observed_30,
        )

        # 20 entries from 40-60 days ago — outside the 30d window.
        prediction_timestamps_old = [
            cur_now - timedelta(days=40 + i)
            for i in range(20)
        ]
        seed_validation_ledger_entries(
            db,
            project_id=project_id,
            n_entries=20,
            prediction_timestamps=prediction_timestamps_old,
            brier_distribution=[0.99] * 20,  # extreme values; should be excluded
            observed_outcomes=[True] * 20,
        )

        # 1 entry in-window with observed_outcome=None — must be excluded.
        seed_validation_ledger_entries(
            db,
            project_id=project_id,
            n_entries=1,
            prediction_timestamps=[cur_now - timedelta(days=5)],
            brier_distribution=[0.99],  # would skew mean if not excluded
            observed_outcomes=[None],
        )

        result = _run(compute_rolling_30d_brier(
            db, project_id=project_id, now=cur_now,
        ))
        self.assertIsInstance(result, dict)
        brier_mean = result.get("brier_mean")
        n = result.get("n")
        self.assertEqual(
            n, 30,
            f"Rolling 30d Brier must aggregate over 30 in-window "
            f"scored entries (20 old excluded, 1 None excluded). "
            f"Got n={n}. Stage 3: $match must include "
            f"scored_at >= cur_now - 30d AND observed_outcome != None.",
        )
        # mean of {0.04, 0.36} alternating over 30 entries = 0.20
        self.assertAlmostEqual(
            brier_mean, 0.20, delta=0.001,
            msg=(
                f"Rolling 30d Brier mean for fixture = 0.20 "
                f"(15×0.04 + 15×0.36) / 30. Got: {brier_mean}. "
                f"Stage 3: $group: brier_mean = $avg of "
                f"brier_score_delta."
            ),
        )
        # Alert threshold check: 0.20 is exactly at the locked threshold.
        # Helper should NOT auto-emit the alert flag — that's the
        # cron caller's responsibility. But assert the result includes
        # the threshold-comparison-friendly shape.
        self.assertIn(
            "brier_mean", result,
            "Result dict must carry 'brier_mean' key for alert "
            "threshold comparison.",
        )


if __name__ == "__main__":
    unittest.main()
