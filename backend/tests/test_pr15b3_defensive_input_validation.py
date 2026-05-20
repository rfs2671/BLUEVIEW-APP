"""PR #15B.3 — defensive input validation + logit clipping tests.

6 tests in TestDefensiveInputValidation:
  1. test_fit_project_panel_handles_zero_variance_feature       (Site 1)
  2. test_logit_clipping_prevents_saturation_to_one              (Site 2)
  3. test_logit_clipping_prevents_underflow_to_zero              (Site 2)
  4. test_compute_x_now_fallback_on_None_feature                 (Site 3)
  5. test_compute_x_now_fallback_on_NaN_feature                  (Site 3)
  6. test_compute_x_now_fallback_on_inf_feature                  (Site 3)

Production Stage 10 (post-PR-#15B.2) surfaced 3 remaining issues:
  • Some panel rows produced zero-variance features (constant value
    across all training rows) → sklearn fits but coefficient is
    arbitrary noise → Brier score degenerate.
  • Sigmoid saturated to exactly 1.0 for extreme β · x_now logits →
    UI displayed 100% risk, an unhelpful and misleading signal.
  • Live x_now compute occasionally returned None/NaN/inf for the
    schedule_position_ratio feature (PR #15A bug carried
    forward; surfacing as numeric exception in predict_for_live).

Defensive Site fixes:
  S1: zero out coefficient post-fit for features with sigma < 1e-6
  S2: clip logit to [-10, +10] before sigmoid
  S3: fall back to mu (or 0.0) for invalid x_now values
"""

from __future__ import annotations

import asyncio
import math
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

from bson import ObjectId  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


try:
    import sklearn  # noqa: F401
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


from lib.statistical_engine.live_mutation import (  # noqa: E402
    _apply_beta_to_x_now,
    fit_project_panel,
    predict_for_project_nightly,
    STATE_VECTOR_FEATURES,
)
from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import seed_daily_panels_fixture  # noqa: E402
from _pr15a_panel_fixtures import (  # noqa: E402
    _StubDb, _StubProjectsForCache,
)


def _menahan_project(oid_hex: str = "69e7c10013506cc459fcd046"):
    return {
        "_id":      ObjectId(oid_hex),
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


class TestDefensiveInputValidation(unittest.TestCase):
    """PR #15B.3 — defensive guards for production-encountered edge
    cases that PR #15B/15B.1/15B.2 didn't anticipate."""

    # ──────────────────────────────────────────────────────────
    # Site 1 — Zero-variance feature handling
    # ──────────────────────────────────────────────────────────

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_fit_project_panel_handles_zero_variance_feature(self):
        """Site 1 — when a feature has zero variance across training
        rows (constant value), the standardization step would
        divide by zero. PR #15B.3 detects this AFTER std computation,
        sets sigma=1.0 to avoid div-by-zero, and zeros out the
        learned coefficient post-fit to neutralize prediction-time
        contribution.

        Fixture: force district_caseload_proxy_days to constant 7.0
        (sigma=0 in gauss → returns the mean every time).
        """
        project = _menahan_project()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        # PR #14B fixture seed lets us override feature_dist per feature.
        # tuple (mean, sigma) — sigma=0 forces constant output.
        seed_daily_panels_fixture(
            db,
            project_id=str(project["_id"]),
            cohort_bbls=[f"3{i:09d}" for i in range(40)],
            n_days=120, now=now,
            feature_dist={
                # All others use their seeder defaults; zero-variance
                # ONLY for district_caseload_proxy_days.
                "active_swo_flag":               (0.0, 1.0),
                "complaint_velocity_14d":        (1.5, 1.5),
                "days_since_last_violation":     (40.0, 25.0),
                "schedule_position_ratio":   (50.0, 25.0),
                "district_caseload_proxy_days":  (7.0, 0.0),   # ← ZERO sigma
            },
        )
        # Mutate seeded rows so project_id is ObjectId (production shape).
        for row in db.daily_panels.docs:
            row["project_id"] = project["_id"]

        result = _run(fit_project_panel(db, project, now=now))
        self.assertIsNotNone(
            result,
            msg="fit_project_panel returned None — should produce a "
                "model_doc even with one zero-variance feature.",
        )
        beta = result.get("beta_coefficients") or {}
        sigma = result.get("panel_sigma") or {}

        # S1 expectation A: coefficient for the zero-variance feature
        # is forced to exactly 0.0 post-fit.
        self.assertEqual(
            beta.get("district_caseload_proxy_days"), 0.0,
            msg=f"Stage 3 PR #15B.3 Site 1: beta for zero-variance "
                f"feature must be zeroed post-fit. Got "
                f"{beta.get('district_caseload_proxy_days')!r}. "
                f"Without zeroing, sklearn's noise coefficient "
                f"propagates to live prediction.",
        )

        # S1 expectation B: panel_sigma replaced with 1.0 (sentinel)
        # for the zero-variance feature, so live-mutation
        # standardization doesn't div-by-zero.
        self.assertEqual(
            sigma.get("district_caseload_proxy_days"), 1.0,
            msg=f"Stage 3 PR #15B.3 Site 1: panel_sigma for zero-"
                f"variance feature must be set to 1.0 (sentinel) so "
                f"_standardize avoids div-by-zero. Got "
                f"{sigma.get('district_caseload_proxy_days')!r}.",
        )

    # ──────────────────────────────────────────────────────────
    # Site 2 — Logit clipping
    # ──────────────────────────────────────────────────────────

    def test_logit_clipping_prevents_saturation_to_one(self):
        """Site 2 — extreme positive β · x_now produces logit > 100
        → sigmoid saturates to exactly 1.0 → UI shows 100% risk
        (misleading + meaningless). PR #15B.3 clips logit to
        [-10, +10] before sigmoid.

        sigmoid(10) ≈ 0.99995, so clip-bounded output is below 1.0
        but still asymptotically meaningful as "very high risk".
        """
        beta = {
            "intercept":                     50.0,   # absurdly positive
            "active_swo_flag":               20.0,
            "complaint_velocity_14d":        10.0,
            "days_since_last_violation":      5.0,
            "schedule_position_ratio":    5.0,
            "district_caseload_proxy_days":   5.0,
        }
        # All x_std values positive → logit massively positive (sum ~ 100+)
        x_std = {
            "active_swo_flag":               5.0,
            "complaint_velocity_14d":        5.0,
            "days_since_last_violation":     5.0,
            "schedule_position_ratio":   5.0,
            "district_caseload_proxy_days":  5.0,
        }
        result = _apply_beta_to_x_now(beta, x_std)
        # sigmoid(10) ≈ 0.9999546021312976. Threshold 0.99996 is just
        # above that — passes when clipping kicks in, fails when
        # un-clipped saturation produces exactly 1.0.
        self.assertLess(
            result, 0.99996,
            msg=f"Stage 3 PR #15B.3 Site 2: sigmoid saturated to "
                f"{result}. With logit clipping to [-10, +10], "
                f"sigmoid output must be <= sigmoid(10) ≈ 0.9999546 "
                f"(NOT 1.0). Existing _sigmoid clips at z>30 but "
                f"PR #15B.3 wants tighter [-10, +10] clip in "
                f"_apply_beta_to_x_now.",
        )

    def test_logit_clipping_prevents_underflow_to_zero(self):
        """Site 2 — extreme negative β · x_now produces logit < -100
        → sigmoid underflows to 0.0 → UI shows 0% risk (false
        confidence). Clip to lower bound -10 → sigmoid(-10) ≈ 4.54e-5.
        """
        beta = {
            "intercept":                    -50.0,
            "active_swo_flag":              -20.0,
            "complaint_velocity_14d":       -10.0,
            "days_since_last_violation":     -5.0,
            "schedule_position_ratio":   -5.0,
            "district_caseload_proxy_days":  -5.0,
        }
        x_std = {
            "active_swo_flag":               5.0,
            "complaint_velocity_14d":        5.0,
            "days_since_last_violation":     5.0,
            "schedule_position_ratio":   5.0,
            "district_caseload_proxy_days":  5.0,
        }
        result = _apply_beta_to_x_now(beta, x_std)
        # sigmoid(-10) ≈ 4.5397868702e-5. Threshold 4.5e-5 is just
        # below that — passes when clipping kicks in, fails when
        # un-clipped underflow produces exactly 0.0.
        self.assertGreater(
            result, 4.5e-5,
            msg=f"Stage 3 PR #15B.3 Site 2: sigmoid underflowed to "
                f"{result}. With logit clipping to [-10, +10], "
                f"sigmoid output must be >= sigmoid(-10) ≈ 4.5398e-5 "
                f"(NOT 0.0). Avoids UI displaying 0% risk for "
                f"projects with out-of-distribution low signal.",
        )

    # ──────────────────────────────────────────────────────────
    # Site 3 — x_now invalid-value fallback
    # ──────────────────────────────────────────────────────────

    def _setup_for_x_now_test(self, x_now_mock_value: dict):
        """Common harness: seed real panels for Menahan, mock
        compute_x_now_for_project to return ``x_now_mock_value``,
        run predict_for_project_nightly. Returns the (db, project,
        socrata, now) tuple plus the prediction_cache after the call.
        """
        project = _menahan_project()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        socrata = MockSocrataClient()
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"3{i:09d}" for i in range(40)],
            n_days=120, now=now,
        )
        # Mutate to ObjectId (PR #15A's production write shape — covered
        # by PR #15B.2's $in filter fix).
        for row in db.daily_panels.docs:
            row["project_id"] = project["_id"]
        return project, db, socrata, now

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_compute_x_now_fallback_on_None_feature(self):
        """Site 3 — x_now returning {feature: None, ...} would
        explode at _standardize. PR #15B.3 detects None BEFORE
        standardization, logs a structured warning, and substitutes
        panel_mu (the training-time mean).

        Strict assertion: ``[pr15b3] x_now['<feat>'] invalid`` log
        line must appear. Pre-PR-#15B.3 the existing _standardize
        silently substitutes 0.0 via the TypeError catch — that's
        a HIDDEN fallback, not an explicit one. The warning is the
        observable signal that the fallback fired.
        """
        bad_x_now = {
            "active_swo_flag":               0.0,
            "complaint_velocity_14d":        None,  # ← invalid
            "days_since_last_violation":     45.0,
            "schedule_position_ratio":   50.0,
            "district_caseload_proxy_days":  7.0,
        }
        project, db, socrata, now = self._setup_for_x_now_test(bad_x_now)
        with patch(
            "lib.statistical_engine.live_mutation."
            "compute_x_now_for_project",
            return_value=bad_x_now,
        ):
            with self.assertLogs(
                "lib.statistical_engine.live_mutation",
                level="WARNING",
            ) as ctx:
                try:
                    _run(predict_for_project_nightly(
                        db, socrata, project, now=now,
                    ))
                except Exception as e:
                    self.fail(
                        f"Stage 3 PR #15B.3 Site 3: predict_for_"
                        f"project_nightly crashed on None x_now "
                        f"feature: {e!r}. Expected: detect None, "
                        f"log warning, substitute panel_mu, continue."
                    )
        # The diagnostic warning MUST appear — proves the explicit
        # fallback was invoked (not the implicit _standardize catch).
        joined = "\n".join(ctx.output)
        self.assertIn(
            "[pr15b3]", joined,
            msg=f"Stage 3 PR #15B.3 Site 3: no [pr15b3] warning log "
                f"detected when x_now had None feature. Existing "
                f"_standardize silently maps None→0.0; PR #15B.3 "
                f"wants an explicit warning + panel_mu fallback. "
                f"Captured logs: {ctx.output!r}",
        )

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_compute_x_now_fallback_on_NaN_feature(self):
        """Site 3 — NaN propagates through standardize → sigmoid →
        prediction_cache. Python's min/max with NaN is undefined
        (often returns 1.0 due to NaN-comparison False semantics),
        producing degenerate 100% probability output. PR #15B.3
        detects NaN via math.isnan() and falls back.

        Strict assertions:
          • prob_violation_14d is not NaN
          • prob_violation_14d is not 1.0 (the Python min-quirk
            artifact that NaN would produce without explicit
            fallback)
        """
        bad_x_now = {
            "active_swo_flag":               0.0,
            "complaint_velocity_14d":        1.5,
            "days_since_last_violation":     float("nan"),  # ← invalid
            "schedule_position_ratio":   50.0,
            "district_caseload_proxy_days":  7.0,
        }
        project, db, socrata, now = self._setup_for_x_now_test(bad_x_now)
        with patch(
            "lib.statistical_engine.live_mutation."
            "compute_x_now_for_project",
            return_value=bad_x_now,
        ):
            try:
                _run(predict_for_project_nightly(db, socrata, project, now=now))
            except Exception as e:
                self.fail(
                    f"Stage 3 PR #15B.3 Site 3: crashed on NaN x_now "
                    f"feature: {e!r}. Expected math.isnan() detection "
                    f"+ panel_mu fallback."
                )
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        cache = (proj_after or {}).get("prediction_cache") or {}
        p14 = cache.get("prob_violation_14d")
        self.assertIsNotNone(p14)
        self.assertFalse(
            math.isnan(p14),
            msg=f"PR #15B.3: NaN propagated to prob_violation_14d. "
                f"Got {p14}. Fallback to panel_mu before "
                f"_apply_beta_to_x_now must catch NaN inputs.",
        )
        # Strict: NaN-induced min/max quirk produces 1.0 without fix.
        self.assertLess(
            p14, 1.0,
            msg=f"PR #15B.3: prob_violation_14d=1.0 likely from "
                f"NaN→min(1.0, NaN)=1.0 quirk in "
                f"_discrete_time_hazard_horizons. Need explicit "
                f"math.isnan() check + panel_mu fallback at Site 3.",
        )

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_compute_x_now_fallback_on_inf_feature(self):
        """Site 3 — inf propagates through standardize, then
        _apply_beta_to_x_now produces logit=inf, sigmoid(inf)=1.0
        exactly. PR #15B.3 catches inf early via math.isinf()."""
        bad_x_now = {
            "active_swo_flag":               0.0,
            "complaint_velocity_14d":        float("inf"),  # ← invalid
            "days_since_last_violation":     40.0,
            "schedule_position_ratio":   50.0,
            "district_caseload_proxy_days":  7.0,
        }
        project, db, socrata, now = self._setup_for_x_now_test(bad_x_now)
        with patch(
            "lib.statistical_engine.live_mutation."
            "compute_x_now_for_project",
            return_value=bad_x_now,
        ):
            try:
                _run(predict_for_project_nightly(db, socrata, project, now=now))
            except Exception as e:
                self.fail(
                    f"Stage 3 PR #15B.3 Site 3: crashed on inf x_now "
                    f"feature: {e!r}."
                )
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        cache = (proj_after or {}).get("prediction_cache") or {}
        p14 = cache.get("prob_violation_14d")
        self.assertIsNotNone(p14)
        self.assertFalse(
            math.isinf(p14),
            msg=f"PR #15B.3: inf propagated. Got {p14}.",
        )
        self.assertLess(
            p14, 1.0,
            msg=f"PR #15B.3: inf x_now produced p_14d=1.0 — fallback "
                f"to panel_mu must prevent saturation. Got {p14}.",
        )


if __name__ == "__main__":
    unittest.main()
