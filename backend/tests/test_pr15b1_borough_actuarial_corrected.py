"""PR #15B.1 — B2a/B2b/B2c borough actuarial corrections.

6 tests in TestBoroughActuarialCorrected:
  1. test_borough_to_boro_brooklyn_maps_to_3                  (Q5)
  2. test_compute_borough_actuarial_uses_boro_field_not_borough  (B2a)
  3. test_compute_borough_actuarial_selects_ecb_violation_number (B2b)
  4. test_compute_borough_actuarial_applies_server_side_date_filter  (B2c)
  5. test_compute_borough_actuarial_12_month_window_regression (L4)
  6. test_compute_borough_actuarial_returns_non_zero_for_realistic_data
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
    from lib.statistical_engine.socrata_client import (  # type: ignore
        _BIS_BORO_CODES, borough_to_boro_code,
    )
    HAS_BORO_CODES = True
except ImportError:
    _BIS_BORO_CODES = None  # type: ignore
    borough_to_boro_code = None  # type: ignore
    HAS_BORO_CODES = False

from lib.statistical_engine.live_mutation import (  # noqa: E402
    compute_borough_actuarial_hazard,
)
from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import seed_cold_start_borough_actuarial_data  # noqa: E402


class TestBoroughActuarialCorrected(unittest.TestCase):
    """B2 lock — 6bgk-3dad field corrections per Stage 1 receipts."""

    # ── Test 1 — Q5 BIS borough codes ────────────────────────

    def test_borough_to_boro_brooklyn_maps_to_3(self):
        if not HAS_BORO_CODES:
            self.fail(
                "Stage 3 PR #15B.1 (B2a, Q5): add to "
                "lib.statistical_engine.socrata_client:\n"
                "  _BIS_BORO_CODES = {\n"
                "    'MANHATTAN':'1', 'BRONX':'2', 'BROOKLYN':'3',\n"
                "    'QUEENS':'4', 'STATEN ISLAND':'5',\n"
                "  }\n"
                "  def borough_to_boro_code(borough_name): -> Optional[str]\n"
                "Stage 1 Probe A.3/A.4 confirmed boro='3' = BROOKLYN "
                "via direct address cross-reference."
            )
        self.assertEqual(borough_to_boro_code("BROOKLYN"), "3")
        self.assertEqual(borough_to_boro_code("BRONX"), "2")
        self.assertEqual(borough_to_boro_code("MANHATTAN"), "1")
        self.assertEqual(borough_to_boro_code("QUEENS"), "4")
        self.assertEqual(borough_to_boro_code("STATEN ISLAND"), "5")
        self.assertIsNone(borough_to_boro_code(None))
        self.assertIsNone(borough_to_boro_code("UNKNOWN"))

    # ── Test 2 — B2a: SoQL WHERE uses `boro` not `borough` ──

    def test_compute_borough_actuarial_uses_boro_field_not_borough(self):
        """B2a — Stage 1 Probe A.5 confirmed `boro` is the correct
        field name; `borough` returns HTTP 400 'No such column'."""
        socrata = MockSocrataClient()
        seed_cold_start_borough_actuarial_data(
            socrata, borough="BROOKLYN", n_permits=10, n_severe_ecb=2,
        )
        _run(compute_borough_actuarial_hazard(
            socrata, borough="BROOKLYN", project_type="New Building",
            horizon_days=7,
        ))
        ecb_calls = [c for c in socrata.calls if c[0] == "6bgk-3dad"]
        self.assertTrue(
            ecb_calls,
            msg="Expected at least 1 6bgk-3dad call",
        )
        where = ecb_calls[0][1].get("where", "")
        self.assertIn(
            "boro", where,
            msg=f"B2a: WHERE clause must filter by `boro` (BIS numeric "
                f"code). Got WHERE={where!r}",
        )
        self.assertNotIn(
            "borough = ", where,
            msg=f"B2a: WHERE clause MUST NOT contain `borough = ...` "
                f"(returns HTTP 400 per Probe A.5). Got WHERE={where!r}",
        )

    # ── Test 3 — B2b: SELECT contains ecb_violation_number ──

    def test_compute_borough_actuarial_selects_ecb_violation_number(self):
        """B2b — Stage 1 Probe A.2 confirmed column name is
        `ecb_violation_number` (NOT `ecb_number`)."""
        socrata = MockSocrataClient()
        seed_cold_start_borough_actuarial_data(socrata)
        _run(compute_borough_actuarial_hazard(
            socrata, borough="BROOKLYN", horizon_days=7,
        ))
        ecb_calls = [c for c in socrata.calls if c[0] == "6bgk-3dad"]
        if not ecb_calls:
            self.fail("Expected at least 1 6bgk-3dad call")
        select = ecb_calls[0][1].get("select") or []
        self.assertIn(
            "ecb_violation_number", select,
            msg=f"B2b: SELECT must include `ecb_violation_number` "
                f"(not `ecb_number`). Got SELECT={select!r}",
        )
        self.assertNotIn(
            "ecb_number", select,
            msg=f"B2b: SELECT must NOT include `ecb_number` (column "
                f"does not exist). Got SELECT={select!r}",
        )

    # ── Test 4 — B2c: server-side date filter ────────────────

    def test_compute_borough_actuarial_applies_server_side_date_filter(self):
        """B2c — Stage 1 Probe E.2 confirmed `issue_date > 'YYYYMMDD'`
        works in SoQL (lex-sortable). Saves ~99% of returned bytes
        vs client-side filtering all 545K Brooklyn rows."""
        socrata = MockSocrataClient()
        seed_cold_start_borough_actuarial_data(socrata)
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        _run(compute_borough_actuarial_hazard(
            socrata, borough="BROOKLYN", horizon_days=7, now=now,
        ))
        ecb_calls = [c for c in socrata.calls if c[0] == "6bgk-3dad"]
        if not ecb_calls:
            self.fail("Expected at least 1 6bgk-3dad call")
        where = ecb_calls[0][1].get("where", "")
        self.assertIn(
            "issue_date >", where,
            msg=f"B2c: WHERE clause must include server-side date "
                f"filter (issue_date > 'YYYYMMDD'). Got WHERE={where!r}",
        )

    # ── Test 5 — L4 12-month window regression ───────────────

    def test_compute_borough_actuarial_12_month_window_regression(self):
        """L4 — existing PR #15B regression. With fixture now seeding
        `boro` field, the 12-month boundary still must be respected.
        100 in-window + 50 out-of-window permits + 5 ECBs → annual
        rate = 5/100 = 0.05."""
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        seed_cold_start_borough_actuarial_data(
            socrata, borough="BROOKLYN",
            n_permits=100, n_severe_ecb=5, window_end=now,
        )
        # Add 50 permits from 18 months ago — must NOT be counted
        # in denominator. Use [{...}] list form (Stage 3.B test fix).
        for i in range(50):
            socrata.seed("rbx6-tga4", [{
                "bin":          f"3060{i:06d}",
                "borough":      "BROOKLYN",
                "work_type":    "General Construction",
                "filing_reason": "Initial Permit",
                "issued_date":  "2024-08-01",
            }])
        rate = _run(compute_borough_actuarial_hazard(
            socrata, borough="BROOKLYN", horizon_days=365, now=now,
        ))
        self.assertAlmostEqual(
            rate, 0.05, delta=0.005,
            msg=f"L4 regression: 12-month window must clamp denominator "
                f"to 100 permits (not 150). Annual hazard expected "
                f"5/100=0.05. Got {rate}",
        )

    # ── Test 6 — non-zero return on realistic data ───────────

    def test_compute_borough_actuarial_returns_non_zero_for_realistic_data(self):
        """End-to-end: with fixture seeding boro='3' + severity in
        SEVERE_ECB_SEVERITIES + dates in window, the corrected query
        returns a real probability, not 0.0."""
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        expected = seed_cold_start_borough_actuarial_data(
            socrata, borough="BROOKLYN", n_permits=100, n_severe_ecb=5,
            window_end=now,
        )
        rate_7d = _run(compute_borough_actuarial_hazard(
            socrata, borough="BROOKLYN", horizon_days=7, now=now,
        ))
        self.assertGreater(
            rate_7d, 0.0,
            msg=f"PR #15B's bug (Probe E.1) was: 0.0 returned because "
                f"WHERE borough=... matched no rows. PR #15B.1's fix: "
                f"WHERE boro='3' matches → non-zero rate. Got {rate_7d}",
        )
        self.assertAlmostEqual(
            rate_7d, expected["expected_p_7d"], delta=1e-4,
            msg=f"Expected p_7d ≈ {expected['expected_p_7d']:.6f}; got "
                f"{rate_7d:.6f}",
        )


if __name__ == "__main__":
    unittest.main()
