"""PR #15B — prediction_cache sub-document shape + label format.

3 tests in TestPredictionCache:
  1. test_prediction_cache_shape_matches_spec
  2. test_prediction_cache_schema_version_invalidation
  3. test_prediction_cache_anchored_baseline_label_format (L8)

PR #15D.2 — the L6/T7 ensemble-trigger tests were removed alongside the
should_fire_ensemble + combine_ensemble_probs helpers, which were never
called from any production inference path (spec audit §3.5). The deployed
fit pipeline is a single sklearn LogisticRegression over weighted rows
(modern=1.0, legacy=0.4) — no separate legacy fit, no p_legacy.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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


# Required prediction_cache fields per Task 5 design.
PREDICTION_CACHE_REQUIRED_FIELDS = frozenset({
    "prob_violation_7d",
    "prob_violation_14d",
    "prob_violation_30d",
    "anchored_baseline_prob_14d",
    "anchored_baseline_label",
    "cohort_tier_utilized",
    "cohort_sample_size",
    "low_confidence_flag",
    "is_cold_start",
    "schedule_position_ratio",
    "district_caseload_proxy_days",
    "model_coefficients_hash",
    "last_validated_timestamp",
    "fit_at",
    "schema_version",
})


class TestPredictionCache(unittest.TestCase):
    """PR #15B — prediction_cache sub-document shape pins."""

    def test_prediction_cache_shape_matches_spec(self):
        """Stage 3 — build_prediction_cache must return a dict with
        all 15 required fields populated."""
        try:
            from lib.statistical_engine.live_mutation import (
                build_prediction_cache,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement build_prediction_cache(\n"
                "    *, beta_coefficients, x_now_standardized, mu, "
                "sigma,\n"
                "    cohort_segment_mix, cohort_sample_size,\n"
                "    anchored_baseline_prob_14d, anchored_baseline_label,\n"
                "    model_coefficients_hash, fit_at, now,\n"
                ") -> Dict[str, Any]. Returns 15-field prediction_cache "
                "sub-document. See Task 5 design doc."
            )
        cache = build_prediction_cache(
            beta_coefficients={
                "intercept": -2.5, "active_swo_flag": 1.2,
                "complaint_velocity_14d": 0.3,
                "days_since_last_violation": -0.02,
                "schedule_position_ratio": 0.01,
                "district_caseload_proxy_days": 0.05,
            },
            x_now_standardized={
                "active_swo_flag": 0.0, "complaint_velocity_14d": 0.0,
                "days_since_last_violation": 0.0,
                "schedule_position_ratio": 0.0,
                "district_caseload_proxy_days": 0.0,
            },
            mu={}, sigma={},
            cohort_segment_mix={"modern": 60, "legacy": 20},
            cohort_sample_size=80,
            anchored_baseline_prob_14d=0.04,
            anchored_baseline_label="BROOKLYN New Building macro baseline",
            model_coefficients_hash="abc123",
            fit_at=None, now=None,
        )
        missing = PREDICTION_CACHE_REQUIRED_FIELDS - set(cache.keys())
        self.assertEqual(
            missing, set(),
            msg=(
                f"prediction_cache missing required fields: {sorted(missing)}. "
                f"All 15 fields from PREDICTION_CACHE_REQUIRED_FIELDS "
                f"must be present per Task 5 design."
            ),
        )

    def test_prediction_cache_schema_version_invalidation(self):
        """Stage 3 — cache with stale schema_version is treated as
        absent on read. Mirrors peer_stats_cache pattern at
        baselines.py:1950."""
        try:
            from lib.statistical_engine.live_mutation import (
                is_prediction_cache_valid,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement is_prediction_cache_valid"
                "(cache: Optional[Dict]) -> bool. Returns False when "
                "cache is None, missing schema_version, or carries a "
                "schema_version other than the current 'pr15b_v1'. "
                "Mirrors baselines.py:1950 pattern."
            )
        self.assertFalse(is_prediction_cache_valid(None))
        self.assertFalse(
            is_prediction_cache_valid({"schema_version": "pr15a_v1"}),
            msg="Wrong schema_version must invalidate.",
        )
        self.assertFalse(
            is_prediction_cache_valid({}),
            msg="Missing schema_version must invalidate.",
        )
        self.assertTrue(
            is_prediction_cache_valid({
                "schema_version": "pr15b_v1",
                "model_coefficients_hash": "abc",
            }),
            msg="Current schema_version='pr15b_v1' must be valid.",
        )

    def test_prediction_cache_anchored_baseline_label_format(self):
        """L8 — exact format: f'{borough} {project_type} macro baseline'.
        Drives UX copy in PR #15D."""
        try:
            from lib.statistical_engine.live_mutation import (
                format_anchored_baseline_label,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement format_anchored_baseline_"
                "label(borough: str, project_type: str) -> str. "
                "Returns exactly f'{borough} {project_type} macro baseline'."
            )
        self.assertEqual(
            format_anchored_baseline_label("BROOKLYN", "New Building"),
            "BROOKLYN New Building macro baseline",
        )
        self.assertEqual(
            format_anchored_baseline_label("MANHATTAN", "Major Alteration"),
            "MANHATTAN Major Alteration macro baseline",
        )

    # ──────────────────────────────────────────────────────────
    # Phase 1 Week 2 hotfix — cache_doc must read
    # schedule_position_ratio from x_now, not peer_criteria
    # ──────────────────────────────────────────────────────────

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_cache_doc_reads_schedule_position_from_x_now(self):
        """PR #34 hotfix — cache_doc construction in
        predict_for_project_nightly must read schedule_position_ratio
        from x_now (the live-computed value) NOT from peer_criteria
        (which daily_panel.py deliberately persists as None per
        Stage 2.A D3: the live path is the source of truth).

        Initial Stage 3 implementation read from peer_criteria,
        silently discarding the live-computed value. Symptom:
        prediction_cache.schedule_position_ratio: null on all
        27 production projects post-migration, including Menahan
        which has 13 Initial Permit filings and a valid cohort
        median duration.
        """
        # Imports deferred so the file still loads when sklearn
        # is absent for the earlier static tests.
        from bson import ObjectId
        from lib.statistical_engine.live_mutation import (
            predict_for_project_nightly,
        )
        from _socrata_mock import MockSocrataClient
        from _pr14b_fixtures import seed_daily_panels_fixture
        from _pr15a_panel_fixtures import _StubDb, _StubProjectsForCache

        project = {
            "_id":      ObjectId("69e7c10013506cc459fcd046"),
            "bbl":      "3033040024",
            "nyc_bin":  "3325703",
            "dob_project_type": "major_alt_with_enlargement",
            "pluto_snapshot": {"borough": "BK"},
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {
                    "sample_size": 60,
                    "dob_project_type": "major_alt_with_enlargement",
                    "cohort_member_provenance": [
                        {"bbl": f"3{i:09d}"} for i in range(60)
                    ],
                    # Phase 1 Week 2 invariant: daily_panel.py persists
                    # None here; the live path provides the real value.
                    "schedule_position_ratio": None,
                },
            },
        }
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        socrata = MockSocrataClient()
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"3{i:09d}" for i in range(40)],
            n_days=120, now=now,
        )
        for row in db.daily_panels.docs:
            row["project_id"] = project["_id"]

        # The bug: cache_doc reads peer_criteria.schedule_position_ratio
        # (None) instead of x_now["schedule_position_ratio"] (0.42).
        live_x_now = {
            "active_swo_flag":              0.0,
            "complaint_velocity_14d":       1.0,
            "days_since_last_violation":    45.0,
            "schedule_position_ratio":      0.42,  # ← live-computed
            "district_caseload_proxy_days": 7.0,
        }
        with patch(
            "lib.statistical_engine.live_mutation."
            "compute_x_now_for_project",
            return_value=live_x_now,
        ):
            _run(predict_for_project_nightly(
                db, socrata, project, now=now,
            ))

        cache = (project.get("prediction_cache") or {})
        self.assertAlmostEqual(
            cache.get("schedule_position_ratio"), 0.42, places=4,
            msg=(
                "Phase 1 Week 2 hotfix: cache_doc.schedule_position_ratio "
                "must equal x_now['schedule_position_ratio'] (the live "
                "value, 0.42), NOT peer_criteria.schedule_position_ratio "
                "(None, which is the daily_panel persistence). Bug: "
                "live_mutation.py:~1649 reads from cache.peer_criteria "
                "instead of x_now."
            ),
        )

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_cache_doc_falls_back_gracefully_when_x_now_missing(self):
        """PR #34 hotfix — defense: when x_now lacks the
        schedule_position_ratio key, predict_for_project_nightly
        must not crash. The PR #15B.3 Site 3 path
        (_validate_x_now_with_fallback) substitutes panel_mu for
        invalid/missing values BEFORE standardization, so the
        cache_doc receives the substituted value — not None, not a
        KeyError.

        Exercises the ``(x_now or {}).get('schedule_position_ratio')``
        defensive read in concert with the upstream panel_mu fallback.
        """
        from bson import ObjectId
        from lib.statistical_engine.live_mutation import (
            predict_for_project_nightly,
        )
        from _socrata_mock import MockSocrataClient
        from _pr14b_fixtures import seed_daily_panels_fixture
        from _pr15a_panel_fixtures import _StubDb, _StubProjectsForCache

        project = {
            "_id":      ObjectId("69e7c10013506cc459fcd046"),
            "bbl":      "3033040024",
            "nyc_bin":  "3325703",
            "dob_project_type": "major_alt_with_enlargement",
            "pluto_snapshot": {"borough": "BK"},
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {
                    "sample_size": 60,
                    "dob_project_type": "major_alt_with_enlargement",
                    "cohort_member_provenance": [
                        {"bbl": f"3{i:09d}"} for i in range(60)
                    ],
                },
            },
        }
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        socrata = MockSocrataClient()
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"3{i:09d}" for i in range(40)],
            n_days=120, now=now,
        )
        for row in db.daily_panels.docs:
            row["project_id"] = project["_id"]

        # x_now without the schedule_position_ratio key — the live
        # compute path returned None or didn't include this feature.
        # The four other features stay valid so _standardize succeeds.
        x_now_missing_key = {
            "active_swo_flag":              0.0,
            "complaint_velocity_14d":       1.0,
            "days_since_last_violation":    45.0,
            "district_caseload_proxy_days": 7.0,
            # NOTE: no "schedule_position_ratio" key.
        }
        with patch(
            "lib.statistical_engine.live_mutation."
            "compute_x_now_for_project",
            return_value=x_now_missing_key,
        ):
            # Should not raise even with missing key.
            _run(predict_for_project_nightly(
                db, socrata, project, now=now,
            ))

        cache = (project.get("prediction_cache") or {})
        sp = cache.get("schedule_position_ratio")
        # PR #15B.3 Site 3's _validate_x_now_with_fallback fires
        # before cache_doc construction and substitutes panel_mu
        # when x_now is missing the key. So cache_doc receives a
        # real float — not None, not a crash. Both outcomes prove
        # the hotfix is wired correctly.
        self.assertIsNotNone(
            sp,
            msg=(
                "PR #34 hotfix: predict_for_project_nightly must not "
                "crash when x_now lacks 'schedule_position_ratio'; the "
                "PR #15B.3 Site 3 panel_mu fallback should substitute "
                "before cache_doc construction. Got None — fallback "
                "did not fire."
            ),
        )
        self.assertIsInstance(
            sp, (int, float),
            msg=f"cache_doc.schedule_position_ratio must be numeric "
                f"after panel_mu substitution; got {type(sp).__name__}",
        )


if __name__ == "__main__":
    unittest.main()
