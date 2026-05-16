"""PR #15B — borough actuarial cold-start fallback tests.

6 tests in TestBoroughActuarialFallback:
  1. test_borough_actuarial_uses_12_month_window (L4)
  2. test_borough_actuarial_hazard_rate_calculation
  3. test_cold_start_writes_prediction_models_with_borough_baselines
  4. test_cold_start_writes_prediction_cache_with_anchored_baseline_label (L8)
  5. test_cold_start_boundary_at_sample_size_29 (L10)
  6. test_cold_start_high_confidence_at_sample_size_100 (T6)

All RED at Stage 2.B — production helper compute_borough_actuarial_hazard
and the cold-start branch in the nightly refit cron defer to Stage 3.
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
    from lib.statistical_engine.live_mutation import (  # type: ignore
        compute_borough_actuarial_hazard,
    )
    HAS_BOROUGH_HELPER = True
except ImportError:
    compute_borough_actuarial_hazard = None  # type: ignore
    HAS_BOROUGH_HELPER = False


from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    seed_cold_start_borough_actuarial_data,
)
from _pr15a_panel_fixtures import _StubDb  # noqa: E402


class TestBoroughActuarialFallback(unittest.TestCase):
    """PR #15B — borough-wide actuarial hazard fallback used when a
    project's peer cohort is too sparse (sample_size < 30, L10)."""

    def _require_helper(self):
        if not HAS_BOROUGH_HELPER:
            self.fail(
                "Stage 3 PR #15B: implement "
                "lib.statistical_engine.live_mutation."
                "compute_borough_actuarial_hazard(socrata, *, "
                "borough, project_type, horizon_days, "
                "now=None) -> float\n"
                "Queries 6bgk-3dad (numerator: severe ECB issuances "
                "in (now-12mo, now]) and rbx6-tga4 (denominator: "
                "permitted projects in (borough, project_type) over "
                "same 12mo window). Returns annualized hazard scaled "
                "to horizon. Lock L4."
            )

    # ── Test 1 — L4 12-month window ───────────────────────────

    def test_borough_actuarial_uses_12_month_window(self):
        """L4 — denominator window must be exactly 12 months."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)

        # Seed 100 permits + 5 severe ECBs all within last 12 months.
        seed_cold_start_borough_actuarial_data(
            socrata,
            borough="BROOKLYN", project_type="New Building",
            n_permits=100, n_severe_ecb=5,
            window_end=now,
        )
        # Seed 50 ADDITIONAL permits from 18 months ago — must NOT
        # be counted in denominator.
        for i in range(50):
            socrata.seed("rbx6-tga4", [{
                "bin":          f"3060{i:06d}",
                "borough":      "BROOKLYN",
                "work_type":    "General Construction",
                "filing_reason": "Initial Permit",
                "issued_date":  "2024-08-01",  # ~18 mo before May 2026
            }])

        rate = _run(compute_borough_actuarial_hazard(
            socrata, borough="BROOKLYN", project_type="New Building",
            horizon_days=365, now=now,
        ))
        # If implementation used 18-month window, rate would be
        # 5 / (100+50) = 0.0333. 12-month window: 5 / 100 = 0.05.
        self.assertAlmostEqual(
            rate, 0.05, delta=0.005,
            msg=(
                f"L4: annual hazard must be 0.05 (5 severe ECBs / "
                f"100 permits in last 12 months). Got {rate}. If 18mo "
                f"window leaked, would compute 0.0333. Stage 3: clamp "
                f"permits query to (now - 365 days, now]."
            ),
        )

    # ── Test 2 — hazard rate calculation ─────────────────────

    def test_borough_actuarial_hazard_rate_calculation(self):
        """Annualized rate must scale to 7-day horizon correctly."""
        self._require_helper()
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        expected = seed_cold_start_borough_actuarial_data(
            socrata,
            borough="MANHATTAN", project_type="New Building",
            n_permits=100, n_severe_ecb=5, window_end=now,
        )
        p_7d = _run(compute_borough_actuarial_hazard(
            socrata, borough="MANHATTAN", project_type="New Building",
            horizon_days=7, now=now,
        ))
        # expected p_7d = 0.05 * 7/365 = 0.000959
        self.assertAlmostEqual(
            p_7d, expected["expected_p_7d"], delta=1e-4,
            msg=(
                f"7-day hazard rate must be annual_hazard * (7/365). "
                f"Expected {expected['expected_p_7d']:.6f}, got {p_7d:.6f}."
            ),
        )

    # ── Test 3 — cold-start prediction_models doc ────────────

    def test_cold_start_writes_prediction_models_with_borough_baselines(self):
        """Stage 3 — cold-start branch writes prediction_models with
        is_cold_start_fallback=True + 3 horizon baseline_p_*."""
        try:
            from lib.statistical_engine.live_mutation import (
                refit_project_cold_start,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement "
                "lib.statistical_engine.live_mutation."
                "refit_project_cold_start(db, project, socrata, *, "
                "now=None) — writes one prediction_models doc with "
                "beta_coefficients=None, is_cold_start_fallback=True, "
                "borough_baseline_p_{7,14,30}d populated via "
                "compute_borough_actuarial_hazard."
            )
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        seed_cold_start_borough_actuarial_data(socrata, window_end=now)
        db = _StubDb()
        project = {
            "_id":     "PROJ-COLD-001",
            "borough": "BROOKLYN",
            "dob_type_classification": "New Building",
            "peer_stats_cache": {
                "status": "ready",
                "peer_criteria": {"sample_size": 0},
            },
        }
        _run(refit_project_cold_start(db, project, socrata, now=now))
        self.assertEqual(
            len(db.prediction_models.docs), 1,
            msg="Cold-start refit must write 1 prediction_models doc.",
        )
        doc = db.prediction_models.docs[0]
        self.assertTrue(
            doc.get("is_cold_start_fallback") is True,
            msg=f"is_cold_start_fallback must be True. Got {doc!r}.",
        )
        self.assertIsNone(
            doc.get("beta_coefficients"),
            msg="beta_coefficients must be None for cold-start.",
        )
        for h in ("7d", "14d", "30d"):
            self.assertIsNotNone(
                doc.get(f"borough_baseline_p_{h}"),
                msg=f"borough_baseline_p_{h} must be populated.",
            )

    # ── Test 4 — anchored_baseline_label (L8) ────────────────

    def test_cold_start_writes_prediction_cache_with_anchored_baseline_label(self):
        """L8 — anchored_baseline_label exactly "{borough} {project_type}
        macro baseline" — drives UX copy in PR #15D."""
        try:
            from lib.statistical_engine.live_mutation import (
                build_cold_start_prediction_cache,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement build_cold_start_prediction_"
                "cache(*, borough, project_type, borough_baseline_probs) "
                "-> Dict[str, Any]. Returns the prediction_cache "
                "sub-document with cohort_tier_utilized='borough_"
                "baseline', anchored_baseline_label formatted "
                "f'{borough} {project_type} macro baseline'."
            )
        cache = build_cold_start_prediction_cache(
            borough="BROOKLYN",
            project_type="New Building",
            borough_baseline_probs={"7d": 0.001, "14d": 0.002, "30d": 0.004},
        )
        self.assertEqual(
            cache["cohort_tier_utilized"], "borough_baseline",
            msg="cohort_tier_utilized must be 'borough_baseline'.",
        )
        self.assertEqual(
            cache["anchored_baseline_label"],
            "BROOKLYN New Building macro baseline",
            msg=(
                f"L8 anchored_baseline_label format: \"{{borough}} "
                f"{{project_type}} macro baseline\". Got "
                f"{cache.get('anchored_baseline_label')!r}."
            ),
        )
        self.assertTrue(
            cache.get("is_cold_start") is True,
            msg="is_cold_start must be True.",
        )

    # ── Test 5 — sample_size=29 → cold-start (L10) ────────

    def test_cold_start_boundary_at_sample_size_29(self):
        """L10 — sample_size=29 triggers cold-start path."""
        try:
            from lib.statistical_engine.live_mutation import (
                should_use_cold_start_fallback,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement should_use_cold_start_"
                "fallback(peer_stats_cache: Optional[Dict]) -> bool. "
                "Returns True when peer_stats_cache is missing OR "
                "peer_criteria.sample_size < 30 (L10 boundary)."
            )
        for n in (0, 1, 15, 28, 29):
            self.assertTrue(
                should_use_cold_start_fallback({
                    "peer_criteria": {"sample_size": n},
                }),
                msg=f"L10: sample_size={n} must trigger cold-start.",
            )
        # Boundary: n=30 must NOT trigger
        self.assertFalse(
            should_use_cold_start_fallback({
                "peer_criteria": {"sample_size": 30},
            }),
            msg=(
                "L10 boundary: sample_size=30 must NOT trigger "
                "cold-start (use low_confidence_flag instead)."
            ),
        )

    # ── Test 6 — high-confidence at sample_size=100 (T6) ──

    def test_cold_start_high_confidence_at_sample_size_100(self):
        """T6 — sample_size=100 yields full model path, no flags."""
        try:
            from lib.statistical_engine.live_mutation import (
                should_use_cold_start_fallback,
                cohort_confidence_tier,
            )
        except ImportError:
            self.fail(
                "Stage 3 PR #15B: implement cohort_confidence_tier"
                "(sample_size: int) -> str. Returns 'cold_start' "
                "(N<30), 'low_confidence' (30<=N<100), or "
                "'high_confidence' (N>=100). T6 triple-boundary."
            )
        self.assertFalse(
            should_use_cold_start_fallback({"peer_criteria": {"sample_size": 100}}),
            msg="sample_size=100 must NOT trigger cold-start.",
        )
        self.assertEqual(cohort_confidence_tier(29), "cold_start")
        self.assertEqual(cohort_confidence_tier(30), "low_confidence")
        self.assertEqual(cohort_confidence_tier(99), "low_confidence")
        self.assertEqual(
            cohort_confidence_tier(100), "high_confidence",
            msg="T6: sample_size=100 → high_confidence tier.",
        )


if __name__ == "__main__":
    unittest.main()
