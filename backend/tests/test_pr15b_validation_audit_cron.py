"""PR #15B — validation audit cron tests (4:15 AM ET).

7 tests in TestValidationAuditCron:
  1. test_validation_audit_cron_scheduled_at_4_15_am_ET (L5)
  2. test_audit_scores_observed_outcome_from_ecb_violations
  3. test_audit_computes_brier_score_delta
  4. test_audit_refuses_to_overwrite_non_null_observed_outcome (L3, Q4)
  5. test_audit_skips_entries_horizon_in_future
  6. test_audit_handles_missing_x_features_snapshot_defensively
  7. test_audit_failure_does_not_mutate_other_collections (L12)

Q4 — L3 enforcement tests live in this file only (PR #15A test
file frozen post-merge).
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


try:
    from lib.statistical_engine.live_mutation import (  # type: ignore
        validation_audit_sweep,
    )
    HAS_AUDIT_HELPER = True
except ImportError:
    validation_audit_sweep = None  # type: ignore
    HAS_AUDIT_HELPER = False


from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr15a_panel_fixtures import (  # noqa: E402
    _StubDb, _StubPredictionValidationLedger,
)


class TestValidationAuditCron(unittest.TestCase):
    """PR #15B — daily 4:15 AM ET audit cron walks the
    prediction_validation_ledger entries whose target_horizon_at has
    passed, scores observed_outcome from severe ECB violations, and
    computes brier_score_delta. NEVER overwrites a non-null
    observed_outcome (L3)."""

    @classmethod
    def setUpClass(cls):
        cls.server_text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def _require_helper(self):
        if not HAS_AUDIT_HELPER:
            self.fail(
                "Stage 3 PR #15B: implement "
                "lib.statistical_engine.live_mutation."
                "validation_audit_sweep(db, socrata, *, now=None) "
                "-> Dict[str, int]. Walks prediction_validation_ledger "
                "where target_horizon_at < now AND observed_outcome IS "
                "NULL; queries 6bgk-3dad for severe ECB on the project "
                "bin in (target_horizon_at - 7d, target_horizon_at]; "
                "patches observed_outcome + brier_score_delta. "
                "L3: refuses to overwrite non-null observed_outcome."
            )

    # ── Test 1 — schedule wiring ─────────────────────────────

    def test_validation_audit_cron_scheduled_at_4_15_am_ET(self):
        """L5 — text-grep server.py for 4:15 AM ET CronTrigger."""
        needle = (
            "CronTrigger(hour=4, minute=15, timezone=\"America/New_York\")"
        )
        self.assertIn(
            needle, self.server_text,
            msg=(
                "Stage 3 PR #15B (L5): register the validation audit "
                "cron in server.py:startup_event() at 4:15 AM ET. "
                "Mirrors PR #15B nightly_panel_refit at 2:45 AM ET. "
                "id='pr15b_validation_audit_sweep', max_instances=1, "
                "coalesce=True. Wraps validation_audit_sweep with "
                "try/except logging."
            ),
        )
        self.assertIn(
            "pr15b_validation_audit_sweep", self.server_text,
            msg="Stage 3: scheduler.add_job(... id='pr15b_validation_"
                "audit_sweep', ...)",
        )

    # ── Test 2 — score observed_outcome from ECB ─────────────

    def test_audit_scores_observed_outcome_from_ecb_violations(self):
        """Stage 3 — audit reads severe ECBs in the horizon window
        and patches observed_outcome=True when any hit."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        horizon_at = now - timedelta(hours=1)

        # Seed a ledger entry whose horizon just passed.
        ledger = _StubPredictionValidationLedger([{
            "project_id":          "PROJ-001",
            "calendar_date":       (horizon_at - timedelta(days=7)).date().isoformat(),
            "prediction_timestamp": horizon_at - timedelta(days=7),
            "target_horizon_at":   horizon_at,
            "target_horizon_days": 7,
            "predicted_probability": 0.7,
            "x_features_snapshot": {"bin": "3000001"},
            "observed_outcome":    None,
        }])
        # Seed severe ECB inside (horizon_at - 7d, horizon_at]:
        ecb_day = (horizon_at - timedelta(days=2)).strftime("%Y%m%d")
        socrata.seed("6bgk-3dad", [{
            "bin":           "3000001",
            "ecb_number":    "ECB-AUDIT-001",
            "severity":      "CLASS - 1",
            "issue_date":    ecb_day,
            "violation_status": "ACTIVE",
        }])
        db = _StubDb(prediction_validation_ledger=ledger)

        _run(validation_audit_sweep(db, socrata, now=now))
        entry = ledger.docs[0]
        self.assertTrue(
            entry.get("observed_outcome") is True,
            msg=(
                f"observed_outcome must be True after severe ECB hit. "
                f"Got {entry.get('observed_outcome')!r}."
            ),
        )

    # ── Test 3 — Brier delta calculation ─────────────────────

    def test_audit_computes_brier_score_delta(self):
        """Stage 3 — brier_score_delta = (observed - predicted)²."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        horizon_at = now - timedelta(hours=1)

        ledger = _StubPredictionValidationLedger([{
            "project_id":          "PROJ-001",
            "calendar_date":       (horizon_at - timedelta(days=7)).date().isoformat(),
            "prediction_timestamp": horizon_at - timedelta(days=7),
            "target_horizon_at":   horizon_at,
            "target_horizon_days": 7,
            "predicted_probability": 0.7,
            "x_features_snapshot": {"bin": "3000002"},
            "observed_outcome":    None,
        }])
        # No ECB hit → observed_outcome=False; brier_delta=(0-0.7)²=0.49
        db = _StubDb(prediction_validation_ledger=ledger)
        _run(validation_audit_sweep(db, socrata, now=now))
        entry = ledger.docs[0]
        self.assertFalse(
            entry.get("observed_outcome"),
            msg="No ECB hit → observed_outcome must be False.",
        )
        self.assertAlmostEqual(
            entry.get("brier_score_delta"), 0.49, delta=1e-6,
            msg=(
                f"brier_score_delta = (1*observed - predicted)² = "
                f"(0 - 0.7)² = 0.49. Got "
                f"{entry.get('brier_score_delta')}."
            ),
        )

    # ── Test 4 — L3 overwrite guard (Q4: soft-fail) ────────

    def test_audit_refuses_to_overwrite_non_null_observed_outcome(self):
        """L3, Q4 soft-fail — second audit on already-scored entry
        emits warning + no-ops; original observed_outcome preserved."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        horizon_at = now - timedelta(hours=1)

        ledger = _StubPredictionValidationLedger([{
            "project_id":          "PROJ-LOCKED",
            "calendar_date":       (horizon_at - timedelta(days=7)).date().isoformat(),
            "target_horizon_at":   horizon_at,
            "target_horizon_days": 7,
            "predicted_probability": 0.7,
            "x_features_snapshot": {"bin": "3000003"},
            "observed_outcome":    True,           # already scored
            "brier_score_delta":   0.09,
        }])
        # Even if ECBs are absent now (would imply False), audit must
        # preserve the original True outcome.
        db = _StubDb(prediction_validation_ledger=ledger)
        _run(validation_audit_sweep(db, socrata, now=now))
        entry = ledger.docs[0]
        self.assertTrue(
            entry.get("observed_outcome") is True,
            msg=(
                "L3 + Q4: validation_audit_sweep must NOT overwrite a "
                "non-null observed_outcome. Original True preserved. "
                "Stage 3: emit logger.warning('[validation_audit] "
                "refusing overwrite for {project_id} {calendar_date}: "
                "outcome already True') and continue."
            ),
        )
        self.assertAlmostEqual(
            entry.get("brier_score_delta"), 0.09, delta=1e-6,
            msg="brier_score_delta must also be preserved.",
        )

    # ── Test 5 — skip future-horizon entries ─────────────────

    def test_audit_skips_entries_horizon_in_future(self):
        """Stage 3 — target_horizon_at > now must be skipped."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        ledger = _StubPredictionValidationLedger([{
            "project_id":          "PROJ-FUTURE",
            "calendar_date":       now.date().isoformat(),
            "target_horizon_at":   now + timedelta(days=1),
            "target_horizon_days": 7,
            "predicted_probability": 0.5,
            "x_features_snapshot": {"bin": "3000004"},
            "observed_outcome":    None,
        }])
        db = _StubDb(prediction_validation_ledger=ledger)
        _run(validation_audit_sweep(db, socrata, now=now))
        entry = ledger.docs[0]
        self.assertIsNone(
            entry.get("observed_outcome"),
            msg=(
                "Future-horizon entries must NOT be scored. Got "
                f"observed_outcome={entry.get('observed_outcome')!r}."
            ),
        )

    # ── Test 6 — missing x_features_snapshot ─────────────────

    def test_audit_handles_missing_x_features_snapshot_defensively(self):
        """Stage 3 — malformed entry without x_features_snapshot.bin
        skipped + warning logged, no crash."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        horizon_at = now - timedelta(hours=1)
        ledger = _StubPredictionValidationLedger([{
            "project_id":          "PROJ-MALFORMED",
            "calendar_date":       (horizon_at - timedelta(days=7)).date().isoformat(),
            "target_horizon_at":   horizon_at,
            "target_horizon_days": 7,
            "predicted_probability": 0.5,
            "x_features_snapshot": None,  # malformed
            "observed_outcome":    None,
        }])
        db = _StubDb(prediction_validation_ledger=ledger)
        try:
            _run(validation_audit_sweep(db, socrata, now=now))
        except Exception as e:
            self.fail(
                f"Stage 3: must handle missing x_features_snapshot "
                f"defensively. Crash: {e!r}. Expected: skip + warning."
            )

    # ── Test 7 — L12 cron failure containment ────────────────

    def test_audit_failure_does_not_mutate_other_collections(self):
        """L12 — even when ECB query crashes, peer_stats_cache and
        risk_score_log are untouched."""
        self._require_helper()

        class _RaisingSocrata:
            calls: list = []
            async def query(self, *a, **k):
                raise RuntimeError("simulated socrata outage")
            def seed(self, *a, **k):
                pass

        socrata = _RaisingSocrata()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        horizon_at = now - timedelta(hours=1)
        ledger = _StubPredictionValidationLedger([{
            "project_id":          "PROJ-OUTAGE",
            "calendar_date":       (horizon_at - timedelta(days=7)).date().isoformat(),
            "target_horizon_at":   horizon_at,
            "target_horizon_days": 7,
            "predicted_probability": 0.5,
            "x_features_snapshot": {"bin": "3000005"},
            "observed_outcome":    None,
        }])
        db = _StubDb(prediction_validation_ledger=ledger)
        # Snapshot a fake peer_stats_cache + risk_score_log on db
        db.peer_stats_cache = {"frozen": True}
        db.risk_score_log = {"frozen": True}
        try:
            _run(validation_audit_sweep(db, socrata, now=now))
        except Exception:
            pass  # crash OR soft-fail both acceptable
        self.assertEqual(
            db.peer_stats_cache, {"frozen": True},
            msg=(
                "L12: cron failure must NOT mutate peer_stats_cache. "
                "Stage 3: wrap each per-entry update in try/except so "
                "one project's failure doesn't cascade."
            ),
        )
        self.assertEqual(
            db.risk_score_log, {"frozen": True},
            msg="L12: risk_score_log must be untouched.",
        )


if __name__ == "__main__":
    unittest.main()
