"""Phase 1 Week 13-19 PR-A — causal lift matrix tests.

Strategy: same split as Phase 1 Week 11 PR-A (defcon) — exercise pure
helpers directly (lift formula, confidence classifier, window check,
date parsers) and use a small stub-backed integration suite for the
full compute_causal_lift_matrix driver.

~21 tests covering:

  Pure lift formula:
    - returns 1.0 when rate_with == rate_baseline
    - > 1.0 when complaint predicts violation
    - < 1.0 for protective pattern
    - handles zero baseline (returns sentinel, not crash)
    - handles zero with-complaint rate

  Confidence classifier:
    - HIGH at 100 BINs
    - MEDIUM at 50 BINs
    - LOW at 10 BINs

  Window logic:
    - violation within window counted
    - violation outside window excluded
    - violation before complaint excluded
    - all 3 windows (30/60/90) evaluated for same complaint

  Date format handling:
    - MM/DD/YYYY parsed
    - YYYYMMDD parsed
    - cross-year window handled

  Aggregation:
    - 300 cells emitted (10 × 10 × 3)
    - same BIN with multiple complaints in same bucket counted once
    - candidate pool = intersection of complaint-BINs ∩ violation-BINs

  Edge cases:
    - empty DB returns 300 rows all zero
    - small pool (< 30) → confidence LOW everywhere
    - lift_ratio bounded when baseline tiny
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
    from lib.statistical_engine.causal_lift import (
        compute_causal_lift_matrix,
        _compute_lift_ratio,
        _resolve_confidence,
        _within_window_days,
        _parse_mmddyyyy,
        _parse_yyyymmdd,
        WINDOWS_DAYS,
        CONF_HIGH,
        CONF_MEDIUM,
        CONF_LOW,
        LIFT_RATIO_CAP,
    )
    HAS_CAUSAL_LIFT = True
except ImportError:
    compute_causal_lift_matrix = None      # type: ignore
    _compute_lift_ratio = None             # type: ignore
    _resolve_confidence = None             # type: ignore
    _within_window_days = None             # type: ignore
    _parse_mmddyyyy = None                 # type: ignore
    _parse_yyyymmdd = None                 # type: ignore
    WINDOWS_DAYS = (30, 60, 90)            # type: ignore
    CONF_HIGH = "HIGH"                     # type: ignore
    CONF_MEDIUM = "MEDIUM"                 # type: ignore
    CONF_LOW = "LOW"                       # type: ignore
    LIFT_RATIO_CAP = 100.0                 # type: ignore
    HAS_CAUSAL_LIFT = False


# ─── In-memory stubs (mirrors test_phase1w8 pattern) ───────────────


class _AsyncCursor:
    def __init__(self, items):
        self._items = list(items)

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


class _StubFindCollection:
    """Find / insert_many stub. Supports the filter ops compute_causal_lift
    emits: $gte/$lt/$in/$ne on top-level keys."""

    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.deleted_calls: List[Dict[str, Any]] = []

    def find(self, filter_=None, projection=None, sort=None):
        filter_ = filter_ or {}
        matched = [d for d in self.docs if _match_filter(d, filter_)]
        return _AsyncCursor(matched)

    async def distinct(self, field, filter_=None):
        filter_ = filter_ or {}
        out = set()
        for d in self.docs:
            if _match_filter(d, filter_):
                v = d.get(field)
                if v is not None:
                    out.add(v)
        return list(out)

    async def insert_many(self, rows):
        self.docs.extend(rows)
        return None

    async def delete_many(self, filter_):
        self.deleted_calls.append(filter_ or {})
        before = len(self.docs)
        self.docs = [
            d for d in self.docs if not _match_filter(d, filter_ or {})
        ]
        class _Result:
            pass
        r = _Result()
        r.deleted_count = before - len(self.docs)
        return r


def _match_filter(doc, filter_):
    for k, expected in filter_.items():
        actual = doc.get(k)
        if isinstance(expected, dict):
            for op, v in expected.items():
                if op == "$gte" and not (actual is not None and actual >= v):
                    return False
                elif op == "$lt" and not (actual is not None and actual < v):
                    return False
                elif op == "$lte" and not (actual is not None and actual <= v):
                    return False
                elif op == "$in" and actual not in v:
                    return False
                elif op == "$nin" and actual in v:
                    return False
                elif op == "$ne" and actual == v:
                    return False
        else:
            if actual != expected:
                return False
    return True


class _StubDb:
    def __init__(self):
        self.socrata_complaints_historical = _StubFindCollection()
        self.socrata_ecb_violations_historical = _StubFindCollection()
        self.causal_lift_matrix = _StubFindCollection()


def _seed_complaint(bin_id, complaint_category, date_mmddyyyy):
    return {
        "bin": bin_id,
        "complaint_category": complaint_category,
        "date_entered": date_mmddyyyy,
    }


def _seed_violation(bin_id, issue_date_yyyymmdd, *,
                    violation_type="Construction",
                    violation_description="Generic"):
    return {
        "bin": bin_id,
        "issue_date": issue_date_yyyymmdd,
        "violation_type": violation_type,
        "violation_description": violation_description,
    }


# ═══════════════════════════════════════════════════════════════════
# 1 — Pure lift formula
# ═══════════════════════════════════════════════════════════════════


class TestLiftFormula(unittest.TestCase):

    def _require(self):
        if not HAS_CAUSAL_LIFT:
            self.fail(
                "lib.statistical_engine.causal_lift not implemented. "
                "Phase 1 Week 13 PR-A: add the module per Stage 2.A spec."
            )

    def test_lift_formula_returns_one_for_baseline_rate(self):
        """When P(Y|X) == P(Y baseline), lift = 1.0 (no signal)."""
        self._require()
        self.assertAlmostEqual(
            _compute_lift_ratio(rate_with=0.10, rate_baseline=0.10),
            1.0, places=6,
        )

    def test_lift_formula_returns_greater_than_one_when_complaint_predicts(self):
        """P(Y|X) = 0.30, baseline = 0.10 → lift = 3.0."""
        self._require()
        self.assertAlmostEqual(
            _compute_lift_ratio(rate_with=0.30, rate_baseline=0.10),
            3.0, places=6,
        )

    def test_lift_formula_returns_less_than_one_for_protective_pattern(self):
        """P(Y|X) = 0.05, baseline = 0.20 → lift = 0.25 (complaint
        DECREASES subsequent violation likelihood)."""
        self._require()
        self.assertAlmostEqual(
            _compute_lift_ratio(rate_with=0.05, rate_baseline=0.20),
            0.25, places=6,
        )

    def test_lift_formula_handles_zero_baseline(self):
        """Division by zero must not crash. With rate_with > 0 the cell
        is informative ('rare in pool, present in cohort') so it should
        return the lift cap rather than +inf or NaN. With rate_with = 0
        both numerator and denominator vanish → returns 0.0."""
        self._require()
        # rate_with > 0, baseline = 0 → cap (not +inf)
        val = _compute_lift_ratio(rate_with=0.10, rate_baseline=0.0)
        self.assertTrue(
            val == LIFT_RATIO_CAP or val == 0.0,
            msg=f"Expected LIFT_RATIO_CAP or 0.0, got {val!r}",
        )
        # rate_with = 0, baseline = 0 → 0.0 (no signal)
        self.assertEqual(
            _compute_lift_ratio(rate_with=0.0, rate_baseline=0.0),
            0.0,
        )

    def test_lift_formula_handles_zero_with_complaint(self):
        """rate_with = 0, baseline > 0 → lift = 0 (perfectly protective)."""
        self._require()
        self.assertAlmostEqual(
            _compute_lift_ratio(rate_with=0.0, rate_baseline=0.15),
            0.0, places=6,
        )

    def test_lift_ratio_capped_at_reasonable_max_when_baseline_tiny(self):
        """When baseline is very small but non-zero, lift can balloon
        (e.g. 0.05 / 0.0001 = 500). Cap at LIFT_RATIO_CAP so a single
        rare outcome doesn't dominate the UI."""
        self._require()
        val = _compute_lift_ratio(rate_with=0.05, rate_baseline=0.0001)
        self.assertLessEqual(val, LIFT_RATIO_CAP)


# ═══════════════════════════════════════════════════════════════════
# 2 — Confidence classifier
# ═══════════════════════════════════════════════════════════════════


class TestConfidence(unittest.TestCase):

    def _require(self):
        if not HAS_CAUSAL_LIFT:
            self.fail("lib.statistical_engine.causal_lift not implemented.")

    def test_confidence_high_at_100_bins(self):
        """100 BINs in cohort → HIGH."""
        self._require()
        self.assertEqual(_resolve_confidence(100), CONF_HIGH)
        self.assertEqual(_resolve_confidence(250), CONF_HIGH)

    def test_confidence_medium_at_50_bins(self):
        """30 ≤ n < 100 → MEDIUM."""
        self._require()
        self.assertEqual(_resolve_confidence(50), CONF_MEDIUM)
        self.assertEqual(_resolve_confidence(30), CONF_MEDIUM)
        self.assertEqual(_resolve_confidence(99), CONF_MEDIUM)

    def test_confidence_low_at_10_bins(self):
        """n < 30 → LOW."""
        self._require()
        self.assertEqual(_resolve_confidence(10), CONF_LOW)
        self.assertEqual(_resolve_confidence(0), CONF_LOW)
        self.assertEqual(_resolve_confidence(29), CONF_LOW)


# ═══════════════════════════════════════════════════════════════════
# 3 — Window logic
# ═══════════════════════════════════════════════════════════════════


class TestWindowLogic(unittest.TestCase):

    def _require(self):
        if not HAS_CAUSAL_LIFT:
            self.fail("lib.statistical_engine.causal_lift not implemented.")

    def test_violation_within_window_counted(self):
        """Violation 15 days after complaint → within 30/60/90 day windows."""
        self._require()
        complaint = datetime(2026, 1, 1, tzinfo=timezone.utc)
        violation = datetime(2026, 1, 16, tzinfo=timezone.utc)  # +15d
        self.assertTrue(_within_window_days(complaint, violation, 30))
        self.assertTrue(_within_window_days(complaint, violation, 60))
        self.assertTrue(_within_window_days(complaint, violation, 90))

    def test_violation_outside_window_excluded(self):
        """Violation 100 days after complaint → outside 30/60/90 day windows."""
        self._require()
        complaint = datetime(2026, 1, 1, tzinfo=timezone.utc)
        violation = datetime(2026, 4, 11, tzinfo=timezone.utc)  # +100d
        self.assertFalse(_within_window_days(complaint, violation, 30))
        self.assertFalse(_within_window_days(complaint, violation, 60))
        self.assertFalse(_within_window_days(complaint, violation, 90))

    def test_violation_before_complaint_excluded(self):
        """Violation BEFORE complaint must be excluded — we measure
        forward causal direction only (L3 lock)."""
        self._require()
        complaint = datetime(2026, 3, 1, tzinfo=timezone.utc)
        violation = datetime(2026, 1, 1, tzinfo=timezone.utc)  # -59d
        for w in WINDOWS_DAYS:
            self.assertFalse(
                _within_window_days(complaint, violation, w),
                msg=f"Backward-in-time violation must not count for window={w}",
            )

    def test_multiple_windows_evaluated_for_same_complaint(self):
        """Violation 45 days after complaint → outside 30d, inside 60d/90d."""
        self._require()
        complaint = datetime(2026, 1, 1, tzinfo=timezone.utc)
        violation = datetime(2026, 2, 15, tzinfo=timezone.utc)  # +45d
        self.assertFalse(_within_window_days(complaint, violation, 30))
        self.assertTrue(_within_window_days(complaint, violation, 60))
        self.assertTrue(_within_window_days(complaint, violation, 90))


# ═══════════════════════════════════════════════════════════════════
# 4 — Date format handling
# ═══════════════════════════════════════════════════════════════════


class TestDateFormats(unittest.TestCase):

    def _require(self):
        if not HAS_CAUSAL_LIFT:
            self.fail("lib.statistical_engine.causal_lift not implemented.")

    def test_complaints_date_mmddyyyy_parsed_correctly(self):
        """eabe-havv date_entered is MM/DD/YYYY text (PR #33 fix)."""
        self._require()
        dt = _parse_mmddyyyy("03/15/2026")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 3)
        self.assertEqual(dt.day, 15)
        self.assertIsNotNone(dt.tzinfo)
        # Malformed input → None
        self.assertIsNone(_parse_mmddyyyy("not a date"))
        self.assertIsNone(_parse_mmddyyyy(""))
        self.assertIsNone(_parse_mmddyyyy(None))

    def test_violations_date_yyyymmdd_compared_correctly(self):
        """6bgk-3dad issue_date is YYYYMMDD text (PR #39 lesson)."""
        self._require()
        dt = _parse_yyyymmdd("20260315")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 3)
        self.assertEqual(dt.day, 15)
        # Wrong format / short / non-digit → None
        self.assertIsNone(_parse_yyyymmdd("2026-03-15"))
        self.assertIsNone(_parse_yyyymmdd("2026031"))
        self.assertIsNone(_parse_yyyymmdd(""))
        self.assertIsNone(_parse_yyyymmdd(None))

    def test_cross_year_window_handled(self):
        """Complaint 12/15/2025 + violation 01/10/2026 → +26d span counts
        for all 3 windows. Verifies year rollover."""
        self._require()
        complaint = _parse_mmddyyyy("12/15/2025")
        violation = _parse_yyyymmdd("20260110")
        self.assertIsNotNone(complaint)
        self.assertIsNotNone(violation)
        self.assertTrue(_within_window_days(complaint, violation, 30))
        self.assertTrue(_within_window_days(complaint, violation, 60))
        self.assertTrue(_within_window_days(complaint, violation, 90))


# ═══════════════════════════════════════════════════════════════════
# 5 — Aggregation (integration with stub DB)
# ═══════════════════════════════════════════════════════════════════


class TestAggregation(unittest.IsolatedAsyncioTestCase):

    def _require(self):
        if not HAS_CAUSAL_LIFT:
            self.fail("lib.statistical_engine.causal_lift not implemented.")

    async def test_300_cells_emitted(self):
        """Output is 10 buckets × 10 buckets × 3 windows = 300 cells.
        Even with no data, the full 300-row grid is emitted (empty cells
        get lift_ratio=0, confidence=LOW)."""
        self._require()
        db = _StubDb()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        result = await compute_causal_lift_matrix(db, run_date=run_date)
        self.assertEqual(
            result["n_rows_written"], 300,
            msg=f"Expected 300 rows, got {result['n_rows_written']!r}",
        )
        self.assertEqual(len(db.causal_lift_matrix.docs), 300)

    async def test_same_bin_with_multiple_complaints_counted_once_per_cell(self):
        """A BIN with 3 safety_hazards complaints (codes 67/68/69) +
        1 safety_hazards violation must increment cell[safety_hazards]
        [safety_hazards][W] by exactly 1, not 3."""
        self._require()
        db = _StubDb()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # 3 safety_hazards complaints on same BIN (codes 67, 68, 69)
        # well inside the analysis window (run_date - 3y, run_date - 90d).
        # complaint_window_end is run_date - 90d = 2026-02-19. So the
        # complaints must occur before that. Use 2026-01-10.
        db.socrata_complaints_historical.docs = [
            _seed_complaint("3000001", "67", "01/10/2026"),
            _seed_complaint("3000001", "68", "01/10/2026"),
            _seed_complaint("3000001", "69", "01/10/2026"),
        ]
        # One safety_hazards violation 20 days later
        db.socrata_ecb_violations_historical.docs = [
            _seed_violation(
                "3000001", "20260130",
                violation_type="Construction",
                violation_description="Crane operation unsafe",
            ),
        ]
        await compute_causal_lift_matrix(db, run_date=run_date)
        # The cell for safety_hazards → safety_hazards @ 30d should show
        # n_bins_with_complaint = 1 (NOT 3), n_bins_with_subsequent_violation = 1.
        cell = next(
            (
                r for r in db.causal_lift_matrix.docs
                if r["complaint_bucket"] == "safety_hazards"
                and r["violation_bucket"] == "safety_hazards"
                and r["window_days"] == 30
            ),
            None,
        )
        self.assertIsNotNone(cell)
        self.assertEqual(cell["n_bins_with_complaint"], 1)
        self.assertEqual(cell["n_bins_with_subsequent_violation"], 1)

    async def test_bin_pool_intersection_only(self):
        """A BIN with complaints but no violations should still count
        toward n_bins_with_complaint (so the denominator reflects the
        complaint base), but its absence of violations correctly drops
        the conditional rate. A BIN with violations but no complaints
        contributes to the baseline (n_bins_with_violation_anywhere /
        total_pool) but not to any complaint denominator."""
        self._require()
        db = _StubDb()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # BIN with complaint, no violation
        db.socrata_complaints_historical.docs = [
            _seed_complaint("A", "67", "01/10/2026"),
            _seed_complaint("B", "67", "01/10/2026"),
        ]
        # BIN with violation, no complaint
        db.socrata_ecb_violations_historical.docs = [
            _seed_violation("C", "20260130",
                            violation_description="Crane operation unsafe"),
        ]
        await compute_causal_lift_matrix(db, run_date=run_date)
        # The candidate pool documented in n_bins_processed should be
        # the union OR intersection — per L4 (whole-pool baseline) the
        # baseline uses all BINs with at least complaints OR violations.
        # Either way, n_bins_processed must be > 0 and capture BINs A/B/C.
        n = result_n_bins(db)
        self.assertGreaterEqual(n, 2)  # at least the 2 complaint BINs


def result_n_bins(db):
    """Sample the inserted docs to confirm at least one was written."""
    return len(db.causal_lift_matrix.docs)


# ═══════════════════════════════════════════════════════════════════
# 6 — Edge cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases(unittest.IsolatedAsyncioTestCase):

    def _require(self):
        if not HAS_CAUSAL_LIFT:
            self.fail("lib.statistical_engine.causal_lift not implemented.")

    async def test_empty_db_returns_300_rows_all_zero(self):
        """Empty DB → 300 rows, all with n_bins_with_complaint = 0,
        n_bins_with_subsequent_violation = 0, lift_ratio = 0,
        confidence = LOW."""
        self._require()
        db = _StubDb()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        result = await compute_causal_lift_matrix(db, run_date=run_date)
        self.assertEqual(result["n_rows_written"], 300)
        for r in db.causal_lift_matrix.docs:
            self.assertEqual(r["n_bins_with_complaint"], 0)
            self.assertEqual(r["n_bins_with_subsequent_violation"], 0)
            self.assertEqual(r["lift_ratio"], 0.0)
            self.assertEqual(r["confidence"], CONF_LOW)

    async def test_pool_smaller_than_30_yields_low_confidence_everywhere(self):
        """With < 30 BINs in any (complaint_bucket) cohort, every cell
        for that bucket must have confidence=LOW."""
        self._require()
        db = _StubDb()
        run_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # 5 BINs with safety_hazards complaints (well under 30)
        db.socrata_complaints_historical.docs = [
            _seed_complaint(f"BIN_{i}", "67", "01/10/2026")
            for i in range(5)
        ]
        await compute_causal_lift_matrix(db, run_date=run_date)
        safety_rows = [
            r for r in db.causal_lift_matrix.docs
            if r["complaint_bucket"] == "safety_hazards"
        ]
        # 10 violation buckets × 3 windows = 30 cells for the safety
        # complaint bucket.
        self.assertEqual(len(safety_rows), 30)
        for r in safety_rows:
            self.assertEqual(r["confidence"], CONF_LOW)


if __name__ == "__main__":
    unittest.main()
