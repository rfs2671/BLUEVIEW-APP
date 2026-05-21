"""Phase 1 Week 13-19 PR-B — recent complaint buckets resolver tests.

Backend support for the Tactical Recommendations FE component. Provides
a per-project rollup of the project's complaints in the last 90 days,
classified into the 10 violation_taxonomy buckets and sorted by count.

The endpoint itself is a thin wrapper around the helper exercised here:
``_resolve_recent_complaint_buckets(db, bin_id, *, now)``.

5 tests covering:
  - empty BIN / no complaints → empty list
  - in-window complaints classified + counted
  - out-of-window complaints excluded
  - results sorted by count DESC
  - same-bucket multiple complaints accumulated, not deduplicated
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.run(coro)


try:
    from lib.statistical_engine.causal_lift import (
        _resolve_recent_complaint_buckets,
    )
    HAS_HELPER = True
except ImportError:
    _resolve_recent_complaint_buckets = None   # type: ignore
    HAS_HELPER = False


# ─── In-memory stubs ───────────────────────────────────────────────


class _AsyncCursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        return list(self._items)


class _StubComplaints:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, filter_=None, projection=None):
        filter_ = filter_ or {}
        bin_id = filter_.get("bin")
        if bin_id is None:
            return _AsyncCursor(self.docs)
        return _AsyncCursor(
            [d for d in self.docs if d.get("bin") == bin_id],
        )


class _StubDb:
    def __init__(self):
        self.socrata_complaints_historical = _StubComplaints()


def _seed(bin_id, code, date_mmddyyyy):
    return {
        "bin": bin_id,
        "complaint_category": code,
        "date_entered": date_mmddyyyy,
    }


class TestRecentComplaintBuckets(unittest.IsolatedAsyncioTestCase):

    def _require(self):
        if not HAS_HELPER:
            self.fail(
                "lib.statistical_engine.causal_lift._resolve_recent_"
                "complaint_buckets not implemented. Phase 1 Week 13 PR-B."
            )

    async def test_no_complaints_returns_empty(self):
        """BIN with zero complaints in window → empty list."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        out = await _resolve_recent_complaint_buckets(
            db, "3000000", now=now,
        )
        self.assertEqual(out, [])

    async def test_in_window_complaints_classified_and_counted(self):
        """A safety_hazards complaint (code 67) 15 days ago appears
        once in the result with bucket='safety_hazards' and
        n_complaints=1."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # 15 days ago — well inside the 90-day window
        in_window = (now - timedelta(days=15)).strftime("%m/%d/%Y")
        db.socrata_complaints_historical.docs = [
            _seed("3000000", "67", in_window),  # safety_hazards
        ]
        out = await _resolve_recent_complaint_buckets(
            db, "3000000", now=now,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bucket"], "safety_hazards")
        self.assertEqual(out[0]["n_complaints"], 1)

    async def test_out_of_window_complaints_excluded(self):
        """A complaint 120 days ago is outside the 90-day window and
        must not appear."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # 120 days ago — outside the window
        stale = (now - timedelta(days=120)).strftime("%m/%d/%Y")
        # 10 days ago — inside the window
        fresh = (now - timedelta(days=10)).strftime("%m/%d/%Y")
        db.socrata_complaints_historical.docs = [
            _seed("3000000", "67", stale),  # excluded
            _seed("3000000", "45", fresh),  # included — occupancy_violations
        ]
        out = await _resolve_recent_complaint_buckets(
            db, "3000000", now=now,
        )
        # Only the fresh occupancy_violations complaint counts.
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bucket"], "occupancy_violations")
        self.assertEqual(out[0]["n_complaints"], 1)

    async def test_results_sorted_by_count_desc(self):
        """When multiple buckets present, the most-frequent bucket
        comes first."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        d = (now - timedelta(days=10)).strftime("%m/%d/%Y")
        db.socrata_complaints_historical.docs = [
            _seed("3000000", "67", d),  # safety_hazards #1
            _seed("3000000", "68", d),  # safety_hazards #2
            _seed("3000000", "69", d),  # safety_hazards #3
            _seed("3000000", "45", d),  # occupancy_violations #1
            _seed("3000000", "55", d),  # zoning #1
        ]
        out = await _resolve_recent_complaint_buckets(
            db, "3000000", now=now,
        )
        # Three buckets emitted, sorted by count DESC.
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["bucket"], "safety_hazards")
        self.assertEqual(out[0]["n_complaints"], 3)
        self.assertEqual(out[1]["n_complaints"], 1)
        self.assertEqual(out[2]["n_complaints"], 1)

    async def test_same_bucket_multiple_complaints_accumulated(self):
        """Two safety_hazards complaints on the same day → count = 2,
        NOT deduped to 1 (this is a per-complaint rollup, unlike the
        per-BIN dedup used by causal_lift_matrix)."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        d = (now - timedelta(days=5)).strftime("%m/%d/%Y")
        db.socrata_complaints_historical.docs = [
            _seed("3000000", "67", d),
            _seed("3000000", "67", d),  # same code same day
        ]
        out = await _resolve_recent_complaint_buckets(
            db, "3000000", now=now,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bucket"], "safety_hazards")
        self.assertEqual(out[0]["n_complaints"], 2)


if __name__ == "__main__":
    unittest.main()
