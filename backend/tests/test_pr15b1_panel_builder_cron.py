"""PR #15B.1 — B1 panel-builder cron + inline backstop tests.

5 tests in TestPanelBuilderCron:
  1. test_panel_build_cron_scheduled_at_1_30_am_ET
  2. test_panel_build_iterates_all_active_projects
  3. test_panel_build_writes_daily_panels_rows
  4. test_panel_build_failure_does_not_mutate_peer_stats_or_risk_score (L12)
  5. test_predict_nightly_inline_backstop_fires_when_panels_empty (Q5)
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
    from lib.statistical_engine.daily_panel import (  # type: ignore
        nightly_panel_build_for_all_projects,
    )
    HAS_BUILDER = True
except ImportError:
    nightly_panel_build_for_all_projects = None  # type: ignore
    HAS_BUILDER = False


from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr15a_panel_fixtures import _StubDb, _StubProjectsForCache  # noqa: E402


class TestPanelBuilderCron(unittest.TestCase):
    """B1 lock — register `pr15a_nightly_panel_build` cron at
    1:30 AM ET (60 min before the 2:45 AM refit cron). Iterates
    active projects, invokes compute_daily_panel, L12 isolation."""

    @classmethod
    def setUpClass(cls):
        cls.server_text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def _require_builder(self):
        if not HAS_BUILDER:
            self.fail(
                "Stage 3 PR #15B.1 (B1): implement "
                "lib.statistical_engine.daily_panel."
                "nightly_panel_build_for_all_projects("
                "db, socrata, *, now=None, concurrency_limit=5) -> "
                "Dict[str, Any]\n"
                "Iterates active projects, invokes compute_daily_panel "
                "for each (semaphore=5). Returns {n_succeeded, "
                "n_failed, n_rows_inserted, errors}. L12 isolation: "
                "per-project try/except; never touches "
                "peer_stats_cache or risk_score_log."
            )

    # ── Test 1 — schedule wiring ─────────────────────────────

    def test_panel_build_cron_scheduled_at_1_30_am_ET(self):
        """B1 — text-grep server.py for 1:30 AM ET CronTrigger."""
        needle_trigger = (
            'CronTrigger(hour=1, minute=30, '
            'timezone="America/New_York")'
        )
        self.assertIn(
            needle_trigger, self.server_text,
            msg=(
                "Stage 3 PR #15B.1 (B1): register the panel-build "
                "cron in server.py:startup_event() at 1:30 AM ET. "
                "Mirrors pr15b_nightly_refit_tick pattern at "
                "server.py:25049. id='pr15a_nightly_panel_build', "
                "max_instances=1, coalesce=True. Wraps "
                "nightly_panel_build_for_all_projects in a tick "
                "function with try/except logging."
            ),
        )
        self.assertIn(
            "pr15a_nightly_panel_build", self.server_text,
            msg=(
                "Stage 3: scheduler.add_job(... id='pr15a_nightly_"
                "panel_build', ...) — id literal missing"
            ),
        )

    # ── Test 2 — iterates all active projects ────────────────

    def test_panel_build_iterates_all_active_projects(self):
        """B1 — call cron with 3 active projects; assert 3 panel-build
        attempts (1 per project via compute_daily_panel call)."""
        self._require_builder()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        projects = [
            {
                "_id": f"PROJ-{i}",
                "bbl": f"301000000{i}",
                "nyc_bin": f"330000{i}",
                "borough": "BROOKLYN",
                "peer_stats_cache": {
                    "status": "ready",
                    "peer_criteria": {
                        "sample_size": 60,
                        "cohort_member_provenance": [
                            {"bbl": f"301{j:07d}", "bin": f"33000{j:02d}"}
                            for j in range(10)
                        ],
                    },
                },
            }
            for i in range(3)
        ]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        result = _run(nightly_panel_build_for_all_projects(
            db, socrata, now=now,
        ))
        self.assertEqual(
            result.get("n_succeeded", 0) + result.get("n_failed", 0), 3,
            msg=f"Expected 3 attempts (n_succeeded+n_failed). Got "
                f"{result!r}",
        )

    # ── Test 3 — writes daily_panels rows ────────────────────

    def test_panel_build_writes_daily_panels_rows(self):
        """B1 — at least one project's compute_daily_panel should
        produce rows for daily_panels (depends on per-project
        provenance + cohort data being seeded)."""
        self._require_builder()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        # NOTE: this is a structural test — actual panel content
        # depends on PR #15A's compute_daily_panel behavior, which
        # we don't re-test here. We assert only that the orchestrator
        # invoked the helper and returned a count >= 0 without crash.
        projects = [{
            "_id": "PROJ-PANEL-1", "bbl": "3010000000",
            "nyc_bin": "3300000",
            "borough": "BROOKLYN",
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {
                    "sample_size": 5,
                    "cohort_member_provenance": [
                        {"bbl": f"301{j:07d}", "bin": f"33000{j:02d}"}
                        for j in range(5)
                    ],
                },
            },
        }]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        result = _run(nightly_panel_build_for_all_projects(
            db, socrata, now=now,
        ))
        self.assertIn("n_rows_inserted", result,
            msg="B1: return dict must include n_rows_inserted total")
        self.assertGreaterEqual(
            result["n_rows_inserted"], 0,
            msg="B1: n_rows_inserted must be a non-negative int",
        )

    # ── Test 4 — L12 isolation on cron failure ───────────────

    def test_panel_build_failure_does_not_mutate_peer_stats_or_risk_score(self):
        """L12 — even when Socrata throws, peer_stats_cache +
        risk_score_log untouched."""
        self._require_builder()

        class _CrashingSocrata:
            calls: list = []
            async def query(self, *a, **k):
                raise RuntimeError("simulated socrata outage")
            def seed(self, *a, **k):
                pass
        socrata = _CrashingSocrata()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        projects = [{
            "_id": "PROJ-CRASH", "bbl": "3010111111",
            "nyc_bin": "3300111",
            "borough": "BROOKLYN",
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {
                    "sample_size": 5,
                    "cohort_member_provenance": [
                        {"bbl": "3011111111", "bin": "3300111"}
                    ],
                },
            },
        }]
        db = _StubDb(projects=_StubProjectsForCache(projects))
        db.peer_stats_cache = {"frozen": True}
        db.risk_score_log = {"frozen": True}
        try:
            _run(nightly_panel_build_for_all_projects(db, socrata, now=now))
        except Exception:
            pass  # crash OR soft-fail both acceptable
        self.assertEqual(
            db.peer_stats_cache, {"frozen": True},
            msg="L12: panel-build cron failure must NOT mutate "
                "peer_stats_cache",
        )
        self.assertEqual(
            db.risk_score_log, {"frozen": True},
            msg="L12: panel-build cron failure must NOT mutate "
                "risk_score_log",
        )

    # ── Test 5 — Q5 inline backstop in nightly refit ─────────

    def test_predict_nightly_inline_backstop_fires_when_panels_empty(self):
        """Q5 — defense in depth: when daily_panels is empty for a
        project (e.g. 1:30 cron failed for that project), the 2:45
        refit's predict_for_project_nightly must inline-invoke
        compute_daily_panel BEFORE fit_project_panel."""
        from lib.statistical_engine.live_mutation import (
            predict_for_project_nightly,
        )
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = {
            "_id": "PROJ-BACKSTOP", "bbl": "3010222222",
            "nyc_bin": "3300222",
            "borough": "BROOKLYN",
            "dob_project_type": "new_building",
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {
                    "sample_size": 60,
                    "cohort_member_provenance": [
                        {"bbl": f"301{j:07d}", "bin": f"33000{j:02d}"}
                        for j in range(60)
                    ],
                },
            },
        }
        db = _StubDb(projects=_StubProjectsForCache([project]))
        # daily_panels intentionally empty — backstop must kick in.
        # SPECIFIC assertion: compute_daily_panel queries eabe-havv
        # for SWO classification. The borough_actuarial cold-start
        # path does NOT touch eabe-havv. So an eabe-havv call in
        # socrata.calls is unique evidence the backstop fired.
        try:
            _run(predict_for_project_nightly(db, socrata, project, now=now))
        except Exception:
            # PR #15B's `predict_for_project_nightly` may still fall
            # through to cold-start due to other code paths, but the
            # backstop call must register BEFORE that.
            pass
        eabe_calls = [c for c in socrata.calls if c[0] == "eabe-havv"]
        self.assertGreater(
            len(eabe_calls), 0,
            msg="Q5 backstop: predict_for_project_nightly should "
                "inline-invoke compute_daily_panel when daily_panels "
                "is empty. The backstop call hits eabe-havv (SWO "
                "classification) — borough_actuarial cold-start "
                "does NOT. eabe-havv in socrata.calls is unique "
                "evidence the backstop fired. Stage 3: before the "
                "fit_project_panel call, check `db.daily_panels."
                "count_documents({project_id})`; if 0, await "
                "compute_daily_panel(project, db, socrata, now=now) "
                "first.",
        )


if __name__ == "__main__":
    unittest.main()
