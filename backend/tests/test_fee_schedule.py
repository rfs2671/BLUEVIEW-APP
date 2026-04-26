"""Boundary tests for the date-windowed fee schedule.

Date-gated logic fails at the boundary, never in the middle. These
tests pin the LL128 cutover (2025-12-20 23:59 → $100; 2025-12-21
00:00 → $130) and the no-rule-found error path.

The pure function `pick_active_rule` is fully sync, so these tests
need no event loop or Mongo mock. The cache test exercises the
module-level state directly via `bust_fee_cache()`.
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Allow running with `python -m unittest tests.test_fee_schedule`
# from the backend/ directory.
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib import fee_schedule  # noqa: E402
from lib.fee_schedule import (  # noqa: E402
    pick_active_rule,
    bust_fee_cache,
    get_fee,
)


# Mirror the seed payload exactly so the test bites if the seed
# changes shape without an associated test update.
RULES = [
    {
        "_id": "old",
        "effective_from":  datetime(2020, 1, 1, tzinfo=timezone.utc),
        "effective_until": datetime(2025, 12, 20, 23, 59, 59, tzinfo=timezone.utc),
        "applies_to":      ["ALL"],
        "min_renewal_fee_cents": 10_000,
        "notes": "DOB pre-LL128 schedule",
        "split_rules": {"all": {"at_filing_pct": 100, "before_issuance_pct": 0}},
    },
    {
        "_id": "ll128",
        "effective_from":  datetime(2025, 12, 21, tzinfo=timezone.utc),
        "effective_until": None,
        "applies_to":      ["ALL"],
        "min_renewal_fee_cents": 13_000,
        "notes": "Local Law 128 of 2024",
        "split_rules": {
            "non_electrical_co_change": {"at_filing_pct": 50, "before_issuance_pct": 50},
            "non_electrical_no_co_change": {"at_filing_pct": 100, "before_issuance_pct": 0},
            "electrical": {
                "at_filing_pct": 50, "before_inspection_pct": 50,
                "min_at_filing_cents": 13_000,
            },
        },
    },
]


class TestPickActiveRule(unittest.TestCase):

    def test_mid_window_old_rule(self):
        """Date in [2020-01-01, 2025-12-20] → returns $100 rule."""
        result = pick_active_rule(
            RULES,
            datetime(2023, 6, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(result["fee_cents"], 10_000)
        self.assertEqual(result["rule_id"], "old")

    def test_boundary_2025_12_20_picks_old_rule(self):
        """Date 2025-12-20 23:59:59 (effective_until of old rule, inclusive) → $100."""
        result = pick_active_rule(
            RULES,
            datetime(2025, 12, 20, 23, 59, 59, tzinfo=timezone.utc),
        )
        self.assertEqual(result["fee_cents"], 10_000)
        self.assertEqual(result["rule_id"], "old")

    def test_boundary_2025_12_21_picks_new_rule(self):
        """Date 2025-12-21 00:00 (effective_from of new rule, inclusive) → $130."""
        result = pick_active_rule(
            RULES,
            datetime(2025, 12, 21, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(result["fee_cents"], 13_000)
        self.assertEqual(result["rule_id"], "ll128")

    def test_2026_picks_ll128(self):
        """Date in 2026 → returns $130 rule."""
        result = pick_active_rule(
            RULES,
            datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(result["fee_cents"], 13_000)
        self.assertEqual(result["rule_id"], "ll128")

    def test_pre_2020_raises(self):
        """Date 1999-01-01 → raises RuntimeError (no rule covers it)."""
        with self.assertRaises(RuntimeError) as ctx:
            pick_active_rule(
                RULES,
                datetime(1999, 1, 1, tzinfo=timezone.utc),
            )
        self.assertIn("No fee_schedule rule active", str(ctx.exception))

    def test_split_for_electrical_under_ll128(self):
        result = pick_active_rule(
            RULES,
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            work_type="EW",
        )
        self.assertEqual(result["split"]["at_filing_pct"], 50)
        self.assertEqual(result["split"]["before_inspection_pct"], 50)
        self.assertEqual(result["split"]["min_at_filing_cents"], 13_000)

    def test_split_for_non_electrical_no_co_change(self):
        result = pick_active_rule(
            RULES,
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            work_type="GC",
            co_change=False,
        )
        self.assertEqual(result["split"]["at_filing_pct"], 100)
        self.assertEqual(result["split"]["before_issuance_pct"], 0)

    def test_split_for_non_electrical_co_change(self):
        result = pick_active_rule(
            RULES,
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            work_type="GC",
            co_change=True,
        )
        self.assertEqual(result["split"]["at_filing_pct"], 50)
        self.assertEqual(result["split"]["before_issuance_pct"], 50)

    def test_split_legacy_rule_uses_all_key(self):
        result = pick_active_rule(
            RULES,
            datetime(2023, 6, 15, tzinfo=timezone.utc),
            work_type="EW",  # ignored — old rule has only "all"
        )
        self.assertEqual(result["split"]["at_filing_pct"], 100)

    def test_specificity_prefers_specific_over_all(self):
        """If two rules match by date, the work_type-specific one wins."""
        rules = [
            {
                "_id": "all",
                "effective_from": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "effective_until": None,
                "applies_to": ["ALL"],
                "min_renewal_fee_cents": 13_000,
                "split_rules": {"all": {"at_filing_pct": 100}},
            },
            {
                "_id": "shed_specific",
                "effective_from": datetime(2026, 1, 26, tzinfo=timezone.utc),
                "effective_until": None,
                "applies_to": ["SH"],
                "min_renewal_fee_cents": 13_000,
                "notes": "hypothetical shed-specific override",
                "split_rules": {"all": {"at_filing_pct": 100}},
            },
        ]
        result = pick_active_rule(
            rules,
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            work_type="SH",
        )
        self.assertEqual(result["rule_id"], "shed_specific")


class TestCache(unittest.TestCase):
    """Verify cache hits don't re-fetch and bust_fee_cache forces refresh."""

    def setUp(self):
        bust_fee_cache()

    def test_cache_hit_skips_db(self):
        """Second call within TTL must not re-fetch from the (mock) db."""
        calls = {"n": 0}

        class _MockColl:
            def find(self, _q):
                calls["n"] += 1
                class _Cursor:
                    async def to_list(_self, _n):
                        return RULES
                return _Cursor()

        class _MockDb:
            fee_schedule = _MockColl()

        async def run():
            db = _MockDb()
            await get_fee(db, today=datetime(2026, 1, 1, tzinfo=timezone.utc))
            await get_fee(db, today=datetime(2026, 2, 1, tzinfo=timezone.utc))

        asyncio.run(run())
        self.assertEqual(calls["n"], 1, "second call should hit cache, not db")

    def test_bust_forces_refetch(self):
        calls = {"n": 0}

        class _MockColl:
            def find(self, _q):
                calls["n"] += 1
                class _Cursor:
                    async def to_list(_self, _n):
                        return RULES
                return _Cursor()

        class _MockDb:
            fee_schedule = _MockColl()

        async def run():
            db = _MockDb()
            await get_fee(db, today=datetime(2026, 1, 1, tzinfo=timezone.utc))
            bust_fee_cache()
            await get_fee(db, today=datetime(2026, 2, 1, tzinfo=timezone.utc))

        asyncio.run(run())
        self.assertEqual(calls["n"], 2, "bust_fee_cache should force a re-fetch")

    def test_ttl_expiry_forces_refetch(self):
        """When the monotonic clock crosses the TTL, the next call re-fetches."""
        calls = {"n": 0}

        class _MockColl:
            def find(self, _q):
                calls["n"] += 1
                class _Cursor:
                    async def to_list(_self, _n):
                        return RULES
                return _Cursor()

        class _MockDb:
            fee_schedule = _MockColl()

        async def run():
            db = _MockDb()
            await get_fee(db, today=datetime(2026, 1, 1, tzinfo=timezone.utc))
            # Force cache to look expired.
            fee_schedule._cache["expires_at"] = time.monotonic() - 1
            await get_fee(db, today=datetime(2026, 1, 2, tzinfo=timezone.utc))

        asyncio.run(run())
        self.assertEqual(calls["n"], 2, "expired cache should re-fetch")


if __name__ == "__main__":
    unittest.main()
