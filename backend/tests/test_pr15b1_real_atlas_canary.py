"""PR #15B.1 — Real-Atlas integration canary tests.

5 tests in TestRealAtlasCanary:
  1. test_menahan_canary_produces_modern_fit_not_cold_start
  2. test_bronx_canary_resolves_borough_via_pluto_BX_to_BRONX
  3. test_bailey_canary_resolves_borough_via_pluto_BX_to_BRONX_minor_alt
  4. test_lafayette_canary_resolves_borough_via_pluto_BK_to_BROOKLYN
  5. test_boyland_canary_cold_start_with_borough_baseline_populated

CRITICAL: loads REAL Atlas project documents from saved JSON
fixtures via _pr15b1_atlas_snapshot_loader (Stage 1 Probe C).
Sanitization stripped admin_id, company_id, report_email_list,
dropbox_folder.

These tests exercise the END-TO-END predict_for_project_nightly
flow against MockSocrataClient seeded with realistic 6bgk-3dad
+ rbx6-tga4 data, asserting on the actual production-shape inputs
that PR #15B failed against.
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


from lib.statistical_engine.live_mutation import (  # noqa: E402
    predict_for_project_nightly,
)
from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    seed_cold_start_borough_actuarial_data,
    seed_daily_panels_fixture,
)
from _pr15a_panel_fixtures import _StubDb, _StubProjectsForCache  # noqa: E402
from _pr15b1_atlas_snapshot_loader import (  # noqa: E402
    load_atlas_snapshot,
)


def _seed_realistic_ecb_for_borough(socrata, *, boro_code: str,
                                     n_severe: int = 50) -> None:
    """Seed 6bgk-3dad with realistic shape per Stage 1 receipts:
    boro numeric code, severity in SEVERE_ECB_SEVERITIES, issue_date
    YYYYMMDD. Used to populate borough actuarial denominator data."""
    from datetime import timedelta
    base = datetime(2025, 11, 1, tzinfo=timezone.utc)
    for i in range(n_severe):
        socrata.seed("6bgk-3dad", [{
            "bin":                  f"3060{i:06d}",
            "ecb_violation_number": f"ECB-{boro_code}-{i:05d}",
            "severity":             "CLASS - 1",
            "issue_date":           (base + timedelta(days=i)).strftime("%Y%m%d"),
            "boro":                 boro_code,
            "violation_status":     "ACTIVE",
        }])


def _seed_realistic_permits_for_borough(socrata, *, borough: str,
                                         n: int = 200) -> None:
    """Seed rbx6-tga4 with realistic shape per Stage 1 receipts:
    borough full uppercase, Initial Permit filing_reason."""
    from datetime import timedelta
    base = datetime(2025, 6, 1, tzinfo=timezone.utc)
    for i in range(n):
        socrata.seed("rbx6-tga4", [{
            "bin":          f"3055{i:06d}",
            "borough":      borough,
            "work_type":    "General Construction",
            "filing_reason": "Initial Permit",
            "issued_date":  (base + timedelta(days=i)).date().isoformat(),
        }])


class TestRealAtlasCanary(unittest.TestCase):
    """Integration canary: real Atlas project doc shape + realistic
    Socrata seed shape. Exercises the bugs PR #15B's MockSocrata-only
    tests missed (Bugs B2, B3, B6)."""

    # ── Test 1 — Menahan (Brooklyn, major_alt_with_enlargement, n=85) ──

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_menahan_canary_produces_modern_fit_not_cold_start(self):
        """Stage 1 receipt: Menahan has pluto.borough='BK',
        dob_project_type='major_alt_with_enlargement', sample_size=85.
        After PR #15B.1, must produce a MODERN fit (NOT cold-start)
        with anchored label 'BROOKLYN major_alt_with_enlargement
        macro baseline'."""
        project = load_atlas_snapshot("menahan")
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        # Seed cohort BBLs into daily_panels so fit_project_panel
        # has training data (Q5 backstop wouldn't have time to fully
        # build a panel during a unit test).
        seed_daily_panels_fixture(
            db=_StubDb(),  # unused — we re-seed via the test db below
            project_id=str(project["_id"]),
            cohort_bbls=[
                f"3{i:09d}" for i in range(85)
            ],
            n_days=120, now=now,
        )
        db = _StubDb(projects=_StubProjectsForCache([project]))
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"3{i:09d}" for i in range(85)],
            n_days=120, now=now,
        )
        _seed_realistic_ecb_for_borough(socrata, boro_code="3")
        _seed_realistic_permits_for_borough(socrata, borough="BROOKLYN")
        try:
            _run(predict_for_project_nightly(db, socrata, project, now=now))
        except Exception as e:
            self.fail(f"Menahan canary crashed: {e!r}")
        # Read back the prediction_cache the nightly cron wrote.
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        cache = (proj_after or {}).get("prediction_cache", {})
        self.assertFalse(
            cache.get("is_cold_start"),
            msg=f"Menahan (n=85) MUST NOT take cold-start branch. "
                f"Got is_cold_start={cache.get('is_cold_start')!r}. "
                f"This was PR #15B's bug — Bugs B1+B2+B3 conspired "
                f"to force cold-start. PR #15B.1 should produce a "
                f"real fit.",
        )
        label = cache.get("anchored_baseline_label", "")
        self.assertIn(
            "BROOKLYN", label,
            msg=f"B6: Menahan borough must derive BROOKLYN (via "
                f"pluto.borough='BK'). Got label={label!r}",
        )
        self.assertIn(
            "major_alt_with_enlargement", label,
            msg=f"B3: Menahan project_type must read dob_project_type "
                f"top-level. Got label={label!r}",
        )

    # ── Test 2 — Bronx (pluto BX → BRONX, full_demo) ─────────

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_bronx_canary_resolves_borough_via_pluto_BX_to_BRONX(self):
        """B6 critical: Bronx project's pluto.borough='BX' must derive
        'BRONX' (NOT default to 'BROOKLYN' as PR #15B did)."""
        project = load_atlas_snapshot("bronx")
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        # Use a smaller cohort to keep test fast (real is 253)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"2{i:09d}" for i in range(60)],
            n_days=120, now=now,
        )
        _seed_realistic_ecb_for_borough(socrata, boro_code="2")
        _seed_realistic_permits_for_borough(socrata, borough="BRONX")
        try:
            _run(predict_for_project_nightly(db, socrata, project, now=now))
        except Exception as e:
            self.fail(f"Bronx canary crashed: {e!r}")
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        label = (proj_after or {}).get("prediction_cache", {}).get(
            "anchored_baseline_label", "",
        )
        self.assertIn(
            "BRONX", label,
            msg=f"B6: Bronx must derive BRONX (NOT BROOKLYN default). "
                f"Got label={label!r}. PR #15B Bug B6: top borough "
                f"NULL + no pluto-fallback wiring → every project "
                f"labeled BROOKLYN.",
        )
        self.assertNotIn(
            "BROOKLYN", label,
            msg=f"B6: Bronx label must NOT contain BROOKLYN. Got "
                f"label={label!r}",
        )

    # ── Test 3 — Bailey (pluto BX → BRONX, minor_alt) ────────

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_bailey_canary_resolves_borough_via_pluto_BX_to_BRONX_minor_alt(self):
        project = load_atlas_snapshot("bailey")
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"2{i:09d}" for i in range(60)],
            n_days=120, now=now,
        )
        _seed_realistic_ecb_for_borough(socrata, boro_code="2")
        _seed_realistic_permits_for_borough(socrata, borough="BRONX")
        try:
            _run(predict_for_project_nightly(db, socrata, project, now=now))
        except Exception as e:
            self.fail(f"Bailey canary crashed: {e!r}")
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        label = (proj_after or {}).get("prediction_cache", {}).get(
            "anchored_baseline_label", "",
        )
        self.assertIn(
            "BRONX minor_alt", label,
            msg=f"Bailey must label 'BRONX minor_alt macro baseline'. "
                f"Got {label!r}",
        )

    # ── Test 4 — Lafayette (pluto BK → BROOKLYN, new_building) ──

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_lafayette_canary_resolves_borough_via_pluto_BK_to_BROOKLYN(self):
        project = load_atlas_snapshot("lafayette")
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"3{i:09d}" for i in range(51)],
            n_days=120, now=now,
        )
        _seed_realistic_ecb_for_borough(socrata, boro_code="3")
        _seed_realistic_permits_for_borough(socrata, borough="BROOKLYN")
        try:
            _run(predict_for_project_nightly(db, socrata, project, now=now))
        except Exception as e:
            self.fail(f"Lafayette canary crashed: {e!r}")
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        label = (proj_after or {}).get("prediction_cache", {}).get(
            "anchored_baseline_label", "",
        )
        self.assertIn(
            "BROOKLYN new_building", label,
            msg=f"Lafayette must label 'BROOKLYN new_building macro "
                f"baseline'. Got {label!r}",
        )

    # ── Test 5 — Boyland (cold-start, full_demo) ─────────────

    def test_boyland_canary_cold_start_with_borough_baseline_populated(self):
        """Boyland has sample_size=0 (cold-start path correct). Verify
        the borough_baseline_p_*d are NON-ZERO after PR #15B.1 B2 fix
        (PR #15B's bug made them all 0.0 because the WHERE failed)."""
        project = load_atlas_snapshot("boyland")
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        # No daily_panels for Boyland (correct — cold-start path).
        # Seed realistic borough data so cold-start hazard calc has
        # something to compute against.
        seed_cold_start_borough_actuarial_data(
            socrata, borough="BROOKLYN", n_permits=100, n_severe_ecb=5,
            window_end=now,
        )
        try:
            _run(predict_for_project_nightly(db, socrata, project, now=now))
        except Exception as e:
            self.fail(f"Boyland canary crashed: {e!r}")
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        cache = (proj_after or {}).get("prediction_cache", {})
        self.assertTrue(
            cache.get("is_cold_start"),
            msg=f"Boyland (n=0) MUST take cold-start branch. Got "
                f"is_cold_start={cache.get('is_cold_start')!r}",
        )
        label = cache.get("anchored_baseline_label", "")
        self.assertIn(
            "BROOKLYN full_demo", label,
            msg=f"Boyland cold-start label must be 'BROOKLYN full_demo "
                f"macro baseline'. Got {label!r}",
        )
        # B2 fix: prob_*d must be > 0 (PR #15B returned 0.0 because
        # WHERE borough=... failed against 6bgk-3dad).
        p7 = cache.get("prob_violation_7d")
        self.assertIsNotNone(p7)
        self.assertGreater(
            p7, 0.0,
            msg=f"B2: Boyland prob_violation_7d must be > 0 after fix. "
                f"Got {p7}. PR #15B's bug: WHERE borough='BROOKLYN' "
                f"returned 400 → 0 ECBs counted → rate 0.0.",
        )


if __name__ == "__main__":
    unittest.main()
