"""Regression test for the nightly_renewal_scan datetime bug.

The cron read `system_config.last_run` (and similarly `sent_at` on the
health-check alert cooldown), both of which round-trip through Motor as
offset-NAIVE datetimes — Mongo BSON dates don't carry tz unless the
PyMongo client is constructed with tz_aware=True. Subtracting them from
`datetime.now(timezone.utc)` (offset-AWARE) raised:

    TypeError: can't subtract offset-naive and offset-aware datetimes

…which crashed the nightly cron. This test pins the fix.

Two layers:
- Pure: `_ensure_utc` returns aware-UTC for naive input, leaves aware
  inputs unchanged, and round-trips None.
- Integration-ish: invoke `nightly_renewal_scan` with a stub db whose
  `system_config.find_one` returns a naive `last_run`. Pre-fix the
  scan crashes; post-fix it logs the cooldown-skip path cleanly.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import permit_renewal  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── _ensure_utc unit ───────────────────────────────────────────────

class TestEnsureUtc(unittest.TestCase):

    def test_none_passthrough(self):
        self.assertIsNone(permit_renewal._ensure_utc(None))

    def test_naive_gets_utc_stamped(self):
        naive = datetime(2026, 4, 28, 12, 0, 0)
        self.assertIsNone(naive.tzinfo)
        result = permit_renewal._ensure_utc(naive)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.replace(tzinfo=None), naive)

    def test_aware_unchanged(self):
        aware = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
        result = permit_renewal._ensure_utc(aware)
        self.assertIs(result, aware)

    def test_naive_subtraction_no_longer_raises(self):
        """The exact pattern that crashed prod: now(utc) - mongo_naive."""
        mongo_naive = datetime(2026, 4, 27, 12, 0, 0)  # 1 day ago, no tz
        delta = (
            datetime.now(timezone.utc) - permit_renewal._ensure_utc(mongo_naive)
        )
        # If _ensure_utc had been a no-op, this subtraction would have
        # raised TypeError before we ever got here.
        self.assertGreater(delta.total_seconds(), 0)


# ── nightly_renewal_scan integration with naive last_run ───────────

class TestNightlyScanWithNaiveTimestamps(unittest.TestCase):
    """Pre-fix: this test crashes inside the Job 3 health-check block
    with TypeError. Post-fix: it completes cleanly and logs the
    cooldown-skip path."""

    def _make_db(self, *, last_run_naive: datetime):
        db = MagicMock()

        # Job 1: no permits to scan — keep the test focused on the bug.
        db.dob_logs = MagicMock()
        permits_cursor = MagicMock()
        permits_cursor.to_list = AsyncMock(return_value=[])
        db.dob_logs.find = MagicMock(return_value=permits_cursor)

        # Job 2: no awaiting renewals.
        db.permit_renewals = MagicMock()
        renewals_cursor = MagicMock()
        renewals_cursor.to_list = AsyncMock(return_value=[])
        db.permit_renewals.find = MagicMock(return_value=renewals_cursor)

        # Job 3: system_config returns a NAIVE last_run — the prod bug
        # condition. Returning <23h ago means the cooldown branch fires
        # (which is where the subtraction happens).
        db.system_config = MagicMock()
        db.system_config.find_one = AsyncMock(return_value={
            "key": "dob_now_health_check",
            "last_run": last_run_naive,
        })

        return db

    def test_naive_last_run_does_not_crash_cron(self):
        # 1 hour ago, deliberately naive — exactly what Motor returns
        # from a Mongo BSON date.
        one_hour_ago_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        self.assertIsNone(one_hour_ago_naive.tzinfo)

        db = self._make_db(last_run_naive=one_hour_ago_naive)

        # Should NOT raise. Pre-fix this call raises TypeError inside
        # the Job 3 cooldown block.
        result = _run(permit_renewal.nightly_renewal_scan(db))

        # The function returns None; success is "didn't raise".
        self.assertIsNone(result)

        # Cooldown branch must have been entered (i.e. the subtraction
        # happened). Verified indirectly: find_one was awaited exactly
        # once for the health-check key.
        db.system_config.find_one.assert_awaited_once_with(
            {"key": "dob_now_health_check"}
        )


if __name__ == "__main__":
    unittest.main()
