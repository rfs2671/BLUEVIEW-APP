"""Phase 1 Week 3 PR-C — violation baseline aggregator tests.

8 tests in TestViolationBaselineAggregator:
  1. test_compute_baseline_aggregates_empty_db_returns_zero_rows
  2. test_compute_baseline_aggregates_single_violation_creates_one_row
  3. test_compute_baseline_aggregates_groups_by_borough_work_type_phase
  4. test_compute_baseline_aggregates_assigns_unknown_phase_when_no_daily_log
  5. test_compute_baseline_aggregates_uses_most_recent_initial_permit_work_type
  6. test_compute_baseline_aggregates_30d_window_excludes_older_violations
  7. test_compute_baseline_aggregates_rate_calculation_is_per_project_day
  8. test_compute_baseline_aggregates_known_phase_count_tracks_daily_log_coverage

The aggregator computes 30d violation rates per (borough, work_type, phase)
cohort by joining:
  • socrata_ecb_violations_historical (Phase 1 Week 1 backfill)
  • socrata_permits_historical (Phase 1 Week 1 backfill)
  • db.projects + db.daily_logs (PR-A + PR-B; phase=unknown for BINs
    without a matching project / daily_log)

Writes one row per cohort per weekly run to violation_baseline_aggregates.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    from lib.statistical_engine.violation_baseline_aggregator import (
        compute_baseline_aggregates,
    )
    HAS_AGGREGATOR = True
except ImportError:
    compute_baseline_aggregates = None  # type: ignore
    HAS_AGGREGATOR = False


# ─── In-memory test stubs ─────────────────────────────────────────


class _StubFindCollection:
    """Minimal Motor-like collection stub supporting the find/to_list
    pattern the aggregator uses + insert_many for the output collection.

    Filter shapes supported:
      • {"field": value} — equality
      • {"field": {"$gte": v}, "field": {"$lt": v}, "field": {"$in": [...]}}
      • {"field": {"$nin": [...]}, "field": {"$ne": v}}
      • {"$or": [...]} — top-level OR
    """

    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    def find(self, filter_=None, projection=None, sort=None):
        filter_ = filter_ or {}
        matched = [d for d in self.docs if _match_filter(d, filter_)]
        if sort:
            # Apply each (field, direction) in reverse so the first
            # (highest-priority) is applied LAST.
            for field, direction in reversed(sort):
                matched.sort(
                    key=lambda d, f=field: d.get(f) or "",
                    reverse=(direction == -1),
                )
        return _AsyncCursor(matched, sort)

    async def find_one(self, filter_=None, sort=None, projection=None):
        # Used by aggregator to look up most-recent daily_log per project.
        filter_ = filter_ or {}
        matched = [d for d in self.docs if _match_filter(d, filter_)]
        if not matched:
            return None
        if sort:
            for field, direction in reversed(sort):
                matched.sort(
                    key=lambda d, f=field: d.get(f) or "",
                    reverse=(direction == -1),
                )
        return matched[0]

    async def insert_many(self, rows):
        self.docs.extend(list(rows or []))
        # Mongo returns InsertManyResult; we don't need it in tests.
        return None

    async def estimated_document_count(self):
        return len(self.docs)


class _AsyncCursor:
    def __init__(self, items, sort=None):
        self._items = items
        self._sort = sort

    def sort(self, field_or_list, direction=None):
        if direction is not None:
            sort = [(field_or_list, direction)]
        else:
            sort = field_or_list
        for field, d in reversed(sort):
            self._items.sort(
                key=lambda doc, f=field: doc.get(f) or "",
                reverse=(d == -1),
            )
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self._items)
        return list(self._items[:length])


def _match_filter(doc: Dict[str, Any], filter_: Dict[str, Any]) -> bool:
    """Apply a Mongo-shaped filter to one doc. Supports the subset the
    aggregator emits."""
    if "$or" in filter_:
        if not any(_match_filter(doc, sub) for sub in filter_["$or"]):
            return False
        filter_ = {k: v for k, v in filter_.items() if k != "$or"}
    for k, expected in filter_.items():
        actual = doc.get(k)
        if isinstance(expected, dict):
            for op, v in expected.items():
                if op == "$gte":
                    if not (actual is not None and actual >= v):
                        return False
                elif op == "$lt":
                    if not (actual is not None and actual < v):
                        return False
                elif op == "$in":
                    if actual not in v:
                        return False
                elif op == "$nin":
                    if actual in v:
                        return False
                elif op == "$ne":
                    if actual == v:
                        return False
                elif op == "$exists":
                    if v != (k in doc):
                        return False
                else:
                    raise NotImplementedError(f"_match_filter op {op}")
        else:
            if actual != expected:
                return False
    return True


class _StubDbForAggregator:
    """Composite stub matching the production db shape the aggregator
    reads. Each collection is independently seedable.
    """

    def __init__(self):
        self.socrata_ecb_violations_historical = _StubFindCollection()
        self.socrata_permits_historical = _StubFindCollection()
        self.projects = _StubFindCollection()
        self.daily_logs = _StubFindCollection()
        self.violation_baseline_aggregates = _StubFindCollection()


# ─── Test class ────────────────────────────────────────────────────


class TestViolationBaselineAggregator(unittest.TestCase):
    """Phase 1 Week 3 PR-C — 8 tests covering the cohort baseline
    aggregator's grouping + windowing + phase resolution logic."""

    def _require_aggregator(self):
        if not HAS_AGGREGATOR:
            self.fail(
                "lib.statistical_engine.violation_baseline_aggregator."
                "compute_baseline_aggregates not implemented. "
                "Phase 1 Week 3 PR-C: add per Stage 2.A design."
            )

    # ──────────────────────────────────────────────────────────
    # Test 1 — empty DB yields zero rows
    # ──────────────────────────────────────────────────────────

    def test_compute_baseline_aggregates_empty_db_returns_zero_rows(self):
        """Phase 1 Week 3 PR-C — no violations + no permits in window
        → zero cohorts → zero aggregate rows written."""
        self._require_aggregator()
        db = _StubDbForAggregator()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        result = _run(compute_baseline_aggregates(db, run_date=run_date))
        self.assertEqual(
            result["n_rows_written"], 0,
            msg="Empty DB must produce 0 aggregate rows. Got: %r" % result,
        )
        self.assertEqual(len(db.violation_baseline_aggregates.docs), 0)

    # ──────────────────────────────────────────────────────────
    # Test 2 — single violation creates one row
    # ──────────────────────────────────────────────────────────

    def test_compute_baseline_aggregates_single_violation_creates_one_row(self):
        """Phase 1 Week 3 PR-C — one BIN with a permit in window + one
        violation against that BIN → one aggregate row with
        n_violations=1, n_active_projects=1."""
        self._require_aggregator()
        db = _StubDbForAggregator()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # Permit issued 10 days before run_date (inside window).
        db.socrata_permits_historical.docs = [{
            "bin": "3000001", "filing_reason": "Initial Permit",
            "issued_date": "2026-05-10T00:00:00.000",
            "borough": "BROOKLYN", "work_type": "General Construction",
        }]
        # Violation issued 5 days before run_date (inside window).
        db.socrata_ecb_violations_historical.docs = [{
            "bin": "3000001", "boro": "3",
            "issue_date": "20260515",
        }]
        result = _run(compute_baseline_aggregates(db, run_date=run_date))
        self.assertEqual(result["n_rows_written"], 1)
        row = db.violation_baseline_aggregates.docs[0]
        self.assertEqual(row["borough"], "BROOKLYN")
        self.assertEqual(row["work_type"], "General Construction")
        self.assertEqual(row["n_violations"], 1)
        self.assertEqual(row["n_active_projects"], 1)

    # ──────────────────────────────────────────────────────────
    # Test 3 — grouping by (borough, work_type, phase) tuples
    # ──────────────────────────────────────────────────────────

    def test_compute_baseline_aggregates_groups_by_borough_work_type_phase(self):
        """Phase 1 Week 3 PR-C — cohorts split by all 3 dimensions.
        Seed 3 BINs across (BROOKLYN, GC) + (BROOKLYN, Plumbing) +
        (MANHATTAN, GC) → 3 distinct aggregate rows (all phase=unknown
        because no daily_logs)."""
        self._require_aggregator()
        db = _StubDbForAggregator()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        db.socrata_permits_historical.docs = [
            {"bin": "3000001", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-10T00:00:00.000",
             "borough": "BROOKLYN", "work_type": "General Construction"},
            {"bin": "3000002", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-11T00:00:00.000",
             "borough": "BROOKLYN", "work_type": "Plumbing"},
            {"bin": "1000003", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-12T00:00:00.000",
             "borough": "MANHATTAN", "work_type": "General Construction"},
        ]
        result = _run(compute_baseline_aggregates(db, run_date=run_date))
        self.assertEqual(result["n_rows_written"], 3)
        cohorts = {
            (r["borough"], r["work_type"], r["phase"])
            for r in db.violation_baseline_aggregates.docs
        }
        self.assertEqual(cohorts, {
            ("BROOKLYN",  "General Construction", "unknown"),
            ("BROOKLYN",  "Plumbing",             "unknown"),
            ("MANHATTAN", "General Construction", "unknown"),
        })

    # ──────────────────────────────────────────────────────────
    # Test 4 — unknown phase default when no daily_log
    # ──────────────────────────────────────────────────────────

    def test_compute_baseline_aggregates_assigns_unknown_phase_when_no_daily_log(self):
        """Phase 1 Week 3 PR-C — BIN without a matching db.projects
        entry (or with a project but no daily_log carrying phase) gets
        phase='unknown'. This is the default bucket for the 99.9% of
        backfilled cohort BINs that aren't production-tracked projects.
        """
        self._require_aggregator()
        db = _StubDbForAggregator()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        db.socrata_permits_historical.docs = [{
            "bin": "3000001", "filing_reason": "Initial Permit",
            "issued_date": "2026-05-10T00:00:00.000",
            "borough": "BROOKLYN", "work_type": "General Construction",
        }]
        # No project, no daily_log — phase falls back to "unknown".
        result = _run(compute_baseline_aggregates(db, run_date=run_date))
        self.assertEqual(result["n_rows_written"], 1)
        row = db.violation_baseline_aggregates.docs[0]
        self.assertEqual(row["phase"], "unknown")
        self.assertEqual(row["n_projects_unknown_phase"], 1)
        self.assertEqual(row["n_projects_known_phase"], 0)

    # ──────────────────────────────────────────────────────────
    # Test 5 — work_type from most-recent Initial Permit
    # ──────────────────────────────────────────────────────────

    def test_compute_baseline_aggregates_uses_most_recent_initial_permit_work_type(self):
        """Phase 1 Week 3 PR-C — when a BIN has multiple Initial Permit
        rows in the window with different work_types (e.g., Foundation
        then General Construction as work progresses), the aggregator
        picks the MOST-RECENT issued_date's work_type as the cohort
        classifier for that BIN."""
        self._require_aggregator()
        db = _StubDbForAggregator()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        db.socrata_permits_historical.docs = [
            # Older Initial Permit — should be ignored.
            {"bin": "3000001", "filing_reason": "Initial Permit",
             "issued_date": "2026-04-25T00:00:00.000",
             "borough": "BROOKLYN", "work_type": "Foundation"},
            # Newer Initial Permit — wins.
            {"bin": "3000001", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-15T00:00:00.000",
             "borough": "BROOKLYN", "work_type": "General Construction"},
        ]
        result = _run(compute_baseline_aggregates(db, run_date=run_date))
        self.assertEqual(result["n_rows_written"], 1)
        row = db.violation_baseline_aggregates.docs[0]
        self.assertEqual(
            row["work_type"], "General Construction",
            msg="Most-recent Initial Permit's work_type must win. "
                "Older Foundation entry from 2026-04-25 should NOT "
                "classify the BIN.",
        )

    # ──────────────────────────────────────────────────────────
    # Test 6 — 30d window excludes older violations
    # ──────────────────────────────────────────────────────────

    def test_compute_baseline_aggregates_30d_window_excludes_older_violations(self):
        """Phase 1 Week 3 PR-C — retrospective 30d window. Violations
        outside [window_end - 30d, window_end) MUST NOT count toward
        n_violations."""
        self._require_aggregator()
        db = _StubDbForAggregator()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        db.socrata_permits_historical.docs = [{
            "bin": "3000001", "filing_reason": "Initial Permit",
            "issued_date": "2026-05-10T00:00:00.000",
            "borough": "BROOKLYN", "work_type": "General Construction",
        }]
        db.socrata_ecb_violations_historical.docs = [
            # 5 days ago — inside window.
            {"bin": "3000001", "boro": "3",
             "issue_date": "20260515"},
            # 60 days ago — outside window.
            {"bin": "3000001", "boro": "3",
             "issue_date": "20260321"},
            # 120 days ago — outside window.
            {"bin": "3000001", "boro": "3",
             "issue_date": "20260120"},
        ]
        result = _run(compute_baseline_aggregates(db, run_date=run_date))
        self.assertEqual(result["n_rows_written"], 1)
        row = db.violation_baseline_aggregates.docs[0]
        self.assertEqual(
            row["n_violations"], 1,
            msg=f"30d window must exclude violations older than 30d. "
                f"Expected 1 (the 2026-05-15 violation). Got: "
                f"{row['n_violations']}",
        )

    # ──────────────────────────────────────────────────────────
    # Test 7 — rate calculation
    # ──────────────────────────────────────────────────────────

    def test_compute_baseline_aggregates_rate_calculation_is_per_project_day(self):
        """Phase 1 Week 3 PR-C — rate = n_violations / (n_active_projects
        * window_days). 2 BINs × 30 days = 60 project-days; 6 violations
        → rate = 0.1 violations per project per day."""
        self._require_aggregator()
        db = _StubDbForAggregator()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # 2 BINs, same cohort.
        db.socrata_permits_historical.docs = [
            {"bin": "3000001", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-10T00:00:00.000",
             "borough": "BROOKLYN", "work_type": "General Construction"},
            {"bin": "3000002", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-11T00:00:00.000",
             "borough": "BROOKLYN", "work_type": "General Construction"},
        ]
        # 6 violations split across the 2 BINs (3 each).
        db.socrata_ecb_violations_historical.docs = [
            {"bin": "3000001", "boro": "3",
             "issue_date": "20260512"},
            {"bin": "3000001", "boro": "3",
             "issue_date": "20260513"},
            {"bin": "3000001", "boro": "3",
             "issue_date": "20260514"},
            {"bin": "3000002", "boro": "3",
             "issue_date": "20260515"},
            {"bin": "3000002", "boro": "3",
             "issue_date": "20260516"},
            {"bin": "3000002", "boro": "3",
             "issue_date": "20260517"},
        ]
        result = _run(compute_baseline_aggregates(db, run_date=run_date))
        self.assertEqual(result["n_rows_written"], 1)
        row = db.violation_baseline_aggregates.docs[0]
        self.assertEqual(row["n_violations"], 6)
        self.assertEqual(row["n_active_projects"], 2)
        self.assertAlmostEqual(
            row["rate_per_project_day"], 6.0 / (2 * 30), places=6,
            msg=f"rate = n_violations / (n_active_projects * window_days)"
                f" = 6 / (2*30) = 0.1. Got: {row['rate_per_project_day']}",
        )

    # ──────────────────────────────────────────────────────────
    # Test 8 — known_phase count tracks daily_log coverage
    # ──────────────────────────────────────────────────────────

    def test_compute_baseline_aggregates_known_phase_count_tracks_daily_log_coverage(self):
        """Phase 1 Week 3 PR-C — when a BIN has a project + daily_log
        with a non-null phase, that BIN goes into the known cohort
        (its own row with phase=<actual>); BINs without phase data go
        into the 'unknown' cohort. n_projects_known_phase = n_active
        for the known-phase row; n_projects_unknown_phase = 0."""
        self._require_aggregator()
        db = _StubDbForAggregator()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # Two BINs: one with project + daily_log phase=mep, one without.
        db.socrata_permits_historical.docs = [
            {"bin": "3000001", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-10T00:00:00.000",
             "borough": "BROOKLYN", "work_type": "General Construction"},
            {"bin": "3000002", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-11T00:00:00.000",
             "borough": "BROOKLYN", "work_type": "General Construction"},
        ]
        db.projects.docs = [
            {"_id": "P_KNOWN", "nyc_bin": "3000001",
             "is_deleted": False},
        ]
        db.daily_logs.docs = [
            {"project_id": "P_KNOWN", "date": "2026-05-19",
             "phase": "mep", "is_deleted": False},
        ]
        result = _run(compute_baseline_aggregates(db, run_date=run_date))
        # Two cohorts: (BROOKLYN, GC, mep) + (BROOKLYN, GC, unknown).
        self.assertEqual(result["n_rows_written"], 2)
        by_phase = {
            r["phase"]: r for r in db.violation_baseline_aggregates.docs
        }
        self.assertIn("mep", by_phase)
        self.assertIn("unknown", by_phase)
        self.assertEqual(by_phase["mep"]["n_projects_known_phase"], 1)
        self.assertEqual(by_phase["mep"]["n_projects_unknown_phase"], 0)
        self.assertEqual(by_phase["unknown"]["n_projects_known_phase"], 0)
        self.assertEqual(by_phase["unknown"]["n_projects_unknown_phase"], 1)


if __name__ == "__main__":
    unittest.main()
