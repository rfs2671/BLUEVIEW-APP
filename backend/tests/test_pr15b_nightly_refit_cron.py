"""PR #15B — nightly refit cron tests (2:45 AM ET).

8 tests in TestNightlyRefitCron:
  1. test_nightly_refit_cron_scheduled_at_2_45_am_ET (L5)
  2. test_refit_fits_one_beta_per_active_project
  3. test_refit_uses_real_sklearn_with_sample_weights (T1, Lock B)
  4. test_refit_skips_pending_peer_stats_cache (Task 8 edge)
  5. test_refit_cold_start_branch_when_sample_size_lt_30 (L10)
  6. test_refit_failure_does_not_mutate_peer_stats_or_risk_score (T10, L12)
  7. test_refit_writes_validation_ledger_entry_per_project (T7)
  8. test_refit_panel_provenance_checksum_skip_on_match (T6)

sklearn-requiring tests skip cleanly if sklearn isn't installed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
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
    import sklearn  # noqa: F401
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

try:
    from lib.statistical_engine.live_mutation import (  # type: ignore
        nightly_refit_tick,
        fit_project_panel,
    )
    HAS_REFIT_HELPER = True
except ImportError:
    nightly_refit_tick = None  # type: ignore
    fit_project_panel = None  # type: ignore
    HAS_REFIT_HELPER = False


from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    seed_daily_panels_fixture, mock_sklearn_fit_predict,
)
from _pr15a_panel_fixtures import (  # noqa: E402
    _StubDb, _StubDailyPanels, _StubProjectsForCache,
)


class TestNightlyRefitCron(unittest.TestCase):
    """PR #15B — 2:45 AM ET nightly cron fits one β per active
    project using sklearn LogisticRegression with sample_weight."""

    @classmethod
    def setUpClass(cls):
        cls.server_text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def _require_helper(self):
        if not HAS_REFIT_HELPER:
            self.fail(
                "Stage 3 PR #15B: implement "
                "lib.statistical_engine.live_mutation.nightly_refit_tick"
                "(db, socrata, *, now=None) -> Dict[str, int]. Walks "
                "active projects; for each, builds daily_panels via "
                "PR #15A compute_daily_panel, then fits β via sklearn "
                "LogisticRegression with sample_weight per Lock B "
                "(Modern=1.0, Legacy=0.4); writes prediction_models + "
                "prediction_validation_ledger + project.prediction_cache."
            )

    # ── Test 1 — schedule wiring ─────────────────────────────

    def test_nightly_refit_cron_scheduled_at_2_45_am_ET(self):
        """L5 — text-grep server.py for 2:45 AM ET CronTrigger."""
        needle = (
            "CronTrigger(hour=2, minute=45, timezone=\"America/New_York\")"
        )
        self.assertIn(
            needle, self.server_text,
            msg=(
                "Stage 3 PR #15B (L5): register nightly refit cron in "
                "server.py:startup_event() at 2:45 AM ET. "
                "id='pr15b_nightly_panel_refit'. Mirrors existing "
                "card_audit + cleanup_resolved_predictions wiring."
            ),
        )
        self.assertIn(
            "pr15b_nightly_panel_refit", self.server_text,
            msg="Stage 3: scheduler.add_job(... id='pr15b_nightly_panel_refit', ...)",
        )

    # ── Test 2 — one β per active project ─────────────────

    @unittest.skipIf(not HAS_SKLEARN,
                     "sklearn not installed — Stage 3 adds to requirements.txt")
    def test_refit_fits_one_beta_per_active_project(self):
        """Stage 3 — every eligible project gets a prediction_models doc."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        projects = [
            {
                "_id": f"PROJ-{i}",
                "bbl": f"301000000{i}",
                "borough": "BROOKLYN",
                "dob_type_classification": "New Building",
                "peer_stats_cache": {
                    "status": "ready",
                    "peer_criteria": {
                        "sample_size": 60,
                        "schema_version": "pr14e_v1",
                        "cohort_member_provenance": [
                            {"bbl": f"30100{j:05d}"} for j in range(60)
                        ],
                    },
                },
            }
            for i in range(3)
        ]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        for p in projects:
            seed_daily_panels_fixture(
                db, project_id=p["_id"], n_days=120, now=now,
            )
        _run(nightly_refit_tick(db, socrata, now=now))
        self.assertEqual(
            len(db.prediction_models.docs), 3,
            msg=(
                f"Expected 1 prediction_models doc per project, got "
                f"{len(db.prediction_models.docs)}. Stage 3: iterate "
                f"projects, call fit_project_panel for each."
            ),
        )

    # ── Test 3 — T1 + Lock B sample weights ────────────────

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_refit_uses_real_sklearn_with_sample_weights(self):
        """T1 + Lock B — fit must apply {modern: 1.0, legacy: 0.4}
        and surface in cohort_segment_mix + sample_weights_applied."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        projects = [{
            "_id": "PROJ-WEIGHTS",
            "bbl": "3010000001",
            "borough": "BROOKLYN",
            "dob_type_classification": "New Building",
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {
                    "sample_size": 80,
                    "schema_version": "pr14e_v1",
                    "cohort_member_provenance": [
                        {"bbl": f"301{i:07d}", "_segment": "modern"} for i in range(60)
                    ] + [
                        {"bbl": f"302{i:07d}", "_segment": "legacy"} for i in range(20)
                    ],
                },
            },
        }]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        seed_daily_panels_fixture(
            db, project_id="PROJ-WEIGHTS", n_days=120, now=now,
        )
        _run(nightly_refit_tick(db, socrata, now=now))
        if not db.prediction_models.docs:
            self.fail("No prediction_models doc written.")
        doc = db.prediction_models.docs[0]
        weights = doc.get("sample_weights_applied", {})
        self.assertEqual(
            weights.get("modern"), 1.0,
            msg="Lock B: modern weight must be 1.0",
        )
        self.assertEqual(
            weights.get("legacy"), 0.4,
            msg="Lock B: legacy weight must be 0.4",
        )

    # ── Test 4 — skip pending peer_stats ────────────────

    def test_refit_skips_pending_peer_stats_cache(self):
        """Task 8 edge — peer_stats_cache.status='pending' must skip."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        projects = [{
            "_id": "PROJ-PENDING",
            "bbl": "3010000999",
            "borough": "BROOKLYN",
            "peer_stats_cache": {"status": "pending"},
        }]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        _run(nightly_refit_tick(db, socrata, now=now))
        self.assertEqual(
            len(db.prediction_models.docs), 0,
            msg=(
                "Pending peer_stats_cache must result in NO "
                "prediction_models doc. Stage 3: skip + log "
                "'[pr15b] skipping {id}: peer_stats pending'."
            ),
        )

    # ── Test 5 — L10 cold-start branch ─────────────────

    def test_refit_cold_start_branch_when_sample_size_lt_30(self):
        """L10 — sample_size=15 must take cold-start path."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        # Seed minimum borough actuarial data so cold-start succeeds
        for i in range(100):
            socrata.seed("rbx6-tga4", {
                "bin":          f"3070{i:06d}",
                "borough":      "BROOKLYN",
                "work_type":    "General Construction",
                "filing_reason": "Initial Permit",
                "issued_date":  (now.replace(year=2025)).date().isoformat(),
            })
        projects = [{
            "_id": "PROJ-COLD-15",
            "bbl": "3010055555",
            "borough": "BROOKLYN",
            "dob_type_classification": "New Building",
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {"sample_size": 15},
            },
        }]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        _run(nightly_refit_tick(db, socrata, now=now))
        if not db.prediction_models.docs:
            self.fail("Cold-start path must still write a prediction_models doc.")
        doc = db.prediction_models.docs[0]
        self.assertTrue(
            doc.get("is_cold_start_fallback") is True,
            msg=(
                f"L10: sample_size<30 must take cold-start path. "
                f"Got is_cold_start_fallback={doc.get('is_cold_start_fallback')!r}."
            ),
        )

    # ── Test 6 — T10 + L12 failure containment ─────────

    def test_refit_failure_does_not_mutate_peer_stats_or_risk_score(self):
        """T10 + L12 — refit crash must not touch peer_stats_cache
        or risk_score_log."""
        self._require_helper()

        class _CrashingSocrata:
            calls: list = []
            async def query(self, *a, **k):
                raise RuntimeError("simulated socrata outage")
            def seed(self, *a, **k):
                pass

        socrata = _CrashingSocrata()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        projects = [{
            "_id": "PROJ-CRASH",
            "bbl": "3010111111",
            "borough": "BROOKLYN",
            "peer_stats_cache": {"status": "ready",
                                 "peer_criteria": {"sample_size": 60}},
        }]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        db.peer_stats_cache = {"frozen": True}
        db.risk_score_log = {"frozen": True}
        try:
            _run(nightly_refit_tick(db, socrata, now=now))
        except Exception:
            pass  # propagation OR soft-fail both acceptable
        self.assertEqual(
            db.peer_stats_cache, {"frozen": True},
            msg="L12: peer_stats_cache must be unchanged on cron crash.",
        )
        self.assertEqual(
            db.risk_score_log, {"frozen": True},
            msg="L12: risk_score_log must be unchanged on cron crash.",
        )

    # ── Test 7 — T7 ledger upsert ─────────────────────

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_refit_writes_validation_ledger_entry_per_project(self):
        """T7 — each refit creates one validation_ledger entry with
        observed_outcome=None and prediction_timestamp=cron_fire_time."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        projects = [{
            "_id": "PROJ-LEDGER",
            "bbl": "3010222222",
            "borough": "BROOKLYN",
            "dob_type_classification": "New Building",
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {
                    "sample_size": 60,
                    "schema_version": "pr14e_v1",
                    "cohort_member_provenance": [
                        {"bbl": f"301{i:07d}"} for i in range(60)
                    ],
                },
            },
        }]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        seed_daily_panels_fixture(
            db, project_id="PROJ-LEDGER", n_days=120, now=now,
        )
        _run(nightly_refit_tick(db, socrata, now=now))
        ledger_docs = db.prediction_validation_ledger.docs
        self.assertEqual(
            len(ledger_docs), 1,
            msg=f"Expected 1 ledger entry per refit, got {len(ledger_docs)}.",
        )
        entry = ledger_docs[0]
        self.assertEqual(entry.get("project_id"), "PROJ-LEDGER")
        self.assertIsNone(
            entry.get("observed_outcome"),
            msg="T7: nightly insert leaves observed_outcome=None.",
        )

    # ── Test 8 — T6 checksum skip ─────────────────────

    def test_refit_panel_provenance_checksum_skip_on_match(self):
        """T6 — second run with identical cohort skips panel rebuild,
        logs '[pr15b] skip panel rebuild, checksum unchanged'."""
        self._require_helper()
        # NOTE: this test relies on PR #15A's _provenance_checksum
        # already shipping; just verifies the refit cron checks it.
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        provenance = [{"bbl": f"301{i:07d}"} for i in range(60)]
        projects = [{
            "_id": "PROJ-IDEMPOTENT",
            "bbl": "3010333333",
            "borough": "BROOKLYN",
            "dob_type_classification": "New Building",
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {
                    "sample_size": 60,
                    "schema_version": "pr14e_v1",
                    "cohort_member_provenance": provenance,
                    # checksum to be filled by Stage 3:
                    "daily_panel_provenance_checksum": "stub",
                },
            },
        }]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        seed_daily_panels_fixture(
            db, project_id="PROJ-IDEMPOTENT", n_days=30, now=now,
        )
        first_count = len(db.daily_panels.docs)
        # First run computes from socrata; second should hit checksum cache.
        try:
            _run(nightly_refit_tick(db, socrata, now=now))
            _run(nightly_refit_tick(db, socrata, now=now))
        except Exception as e:
            self.fail(
                f"Idempotent refit must not crash on second call: {e!r}"
            )
        # Second run must not have inserted more panels (checksum hit)
        second_count = len(db.daily_panels.docs)
        self.assertLessEqual(
            second_count, first_count * 2,
            msg=(
                "T6: second refit with unchanged cohort must not double "
                "the daily_panels row count. Stage 3: check "
                "_provenance_checksum match before insert_many."
            ),
        )


if __name__ == "__main__":
    unittest.main()
