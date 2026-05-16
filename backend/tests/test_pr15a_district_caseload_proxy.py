"""PR #15A Stage 2.B — District Caseload Proxy tests.

The District Caseload Proxy is the 5th state-vector feature
(x[4] = district_caseload_proxy_days). Stage 1 confirmed:
  • Source: eabe-havv ``date_entered`` + ``disposition_date``
    (MM/DD/YYYY text format).
  • Metric: rolling 30-day median of
    (disposition_date - date_entered) per community_board.
  • Cadence: cached per-CD once nightly (T3 lock), shared across
    projects in the same CD.

3 tests in TestDistrictCaseloadProxy:
  1. test_caseload_proxy_computes_rolling_30d_median_disposition_lag
  2. test_caseload_proxy_cached_per_cd_not_per_project
  3. test_caseload_proxy_missing_disposition_date_handled

All 3 RED at Stage 2.B. Stage 3 lands:
  • New helper: lib.statistical_engine.daily_panel.compute_caseload_proxy_for_cd
  • New helper: lib.statistical_engine.daily_panel._caseload_proxy_cache (per-CD cache)
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
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


# ─── Lazy imports for PR #15A symbols (don't exist until Stage 3) ────

try:
    from lib.statistical_engine.daily_panel import (  # type: ignore
        compute_caseload_proxy_for_cd,
    )
    HAS_CASELOAD_PROXY_HELPER = True
except ImportError:
    compute_caseload_proxy_for_cd = None  # type: ignore
    HAS_CASELOAD_PROXY_HELPER = False


# ─── Test infrastructure imports ──────────────────────────────────

from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    DATASET_DOB_COMPLAINTS,
    seed_swo_disposition_for_bin,
)


# ──────────────────────────────────────────────────────────────────
# Test class
# ──────────────────────────────────────────────────────────────────


class TestDistrictCaseloadProxy(unittest.TestCase):
    """PR #15A — 3 tests for the CD-level rolling-30d median
    disposition-lag metric used as state-vector feature x[4]."""

    def setUp(self):
        # PR #15A T3 lock — module-level _caseload_proxy_cache
        # persists across test methods. Production semantics: cache
        # is per-nightly-cron-run; each test simulates a fresh run.
        try:
            from lib.statistical_engine.daily_panel import (  # type: ignore
                _caseload_proxy_cache,
            )
            _caseload_proxy_cache.clear()
        except ImportError:
            pass

    def _require_helper(self):
        if not HAS_CASELOAD_PROXY_HELPER:
            self.fail(
                "lib.statistical_engine.daily_panel."
                "compute_caseload_proxy_for_cd not implemented. "
                "Stage 3 PR #15A: add helper that queries eabe-havv "
                "WHERE community_board=<cd> AND date_entered "
                "(parsed via _parse_bis_mdy_date) within rolling "
                "30-day window from cur_now. Returns float median "
                "of (disposition_date - date_entered) in days, "
                "dropping rows where disposition_date is null."
            )

    def _seed_cd_complaints(
        self,
        socrata,
        *,
        cd: str,
        entries: List[Dict[str, Any]],
    ) -> None:
        """Bulk-seed eabe-havv rows for one CD with explicit
        (date_entered, disposition_date) pairs.

        Each entry: {date_entered: 'MM/DD/YYYY',
                     disposition_date: 'MM/DD/YYYY' | None}
        """
        for i, e in enumerate(entries):
            seed_swo_disposition_for_bin(
                socrata,
                bin=f"3{i:06d}",
                complaint_number=f"{cd}-CN-{i:05d}",
                date_entered=e["date_entered"],
                disposition_code=e.get("disposition_code", "A8"),
                disposition_date=e.get("disposition_date"),
                community_board=cd,
            )

    # ──────────────────────────────────────────────────────────
    # Test 1 — rolling 30d median disposition lag
    # ──────────────────────────────────────────────────────────

    def test_caseload_proxy_computes_rolling_30d_median_disposition_lag(self):
        """Stage 2.A T3 lock — caseload proxy = rolling 30-day median
        of (disposition_date - date_entered) per community_board.

        Fixture: 50 in-window + 5 outside-window complaints for CB
        301. In-window lag distribution = {2, 5, 7, 10, 14} days
        cyclically → median = 7.
        """
        self._require_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)

        # 50 in-window entries, lag cycling through {2,5,7,10,14}.
        in_window_entries = []
        lags = [2, 5, 7, 10, 14]
        for i in range(50):
            entered = cur_now - timedelta(days=(i % 28) + 1)  # within 30d
            lag = lags[i % 5]
            disposed = entered + timedelta(days=lag)
            in_window_entries.append({
                "date_entered":     entered.strftime("%m/%d/%Y"),
                "disposition_date": disposed.strftime("%m/%d/%Y"),
            })
        self._seed_cd_complaints(socrata, cd="301", entries=in_window_entries)

        # 5 outside-window (>60 days old) — must be excluded.
        outside_window = [
            {
                "date_entered":     (cur_now - timedelta(days=80 + i)).strftime("%m/%d/%Y"),
                "disposition_date": (cur_now - timedelta(days=70 + i)).strftime("%m/%d/%Y"),
            }
            for i in range(5)
        ]
        self._seed_cd_complaints(socrata, cd="301", entries=outside_window)

        result = _run(compute_caseload_proxy_for_cd(
            socrata, cd="301", now=cur_now,
        ))
        self.assertIsInstance(
            result, float,
            f"Caseload proxy must return float. Got: {type(result).__name__}",
        )
        # Median of {2, 5, 7, 10, 14} = 7.0.
        self.assertAlmostEqual(
            result, 7.0, delta=0.5,
            msg=(
                f"Rolling 30d median disposition lag for CB 301 "
                f"should be 7 days (median of {{2,5,7,10,14}}). "
                f"Got: {result}. Stage 3: parse "
                f"(disposition_date - date_entered) via "
                f"_parse_bis_mdy_date; median over rows where "
                f"date_entered >= cur_now - 30d AND "
                f"disposition_date is not null."
            ),
        )

    # ──────────────────────────────────────────────────────────
    # Test 2 — caseload proxy cached per CD across projects
    # ──────────────────────────────────────────────────────────

    def test_caseload_proxy_cached_per_cd_not_per_project(self):
        """Stage 2.A T3 lock — per-CD cache. Two projects in CB 301
        must share a single ``compute_caseload_proxy_for_cd``
        invocation per nightly run.
        """
        self._require_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)

        # Seed 10 in-window complaints for CB 301.
        entries = []
        for i in range(10):
            entered = cur_now - timedelta(days=i + 1)
            disposed = entered + timedelta(days=5)
            entries.append({
                "date_entered":     entered.strftime("%m/%d/%Y"),
                "disposition_date": disposed.strftime("%m/%d/%Y"),
            })
        self._seed_cd_complaints(socrata, cd="301", entries=entries)

        # Lazy import — the cache module/var must be present for
        # the per-CD cache assertion.
        try:
            from lib.statistical_engine.daily_panel import (  # type: ignore
                _caseload_proxy_cache,
            )
        except ImportError:
            self.fail(
                "lib.statistical_engine.daily_panel."
                "_caseload_proxy_cache not implemented. Stage 3 "
                "T3 lock: maintain a per-CD cache dict keyed on "
                "community_board so subsequent project panel builds "
                "for the same CD hit the cache rather than re-querying."
            )

        # Clear cache to start fresh.
        _caseload_proxy_cache.clear()

        # First call computes from socrata.
        first = _run(compute_caseload_proxy_for_cd(
            socrata, cd="301", now=cur_now,
        ))
        socrata_calls_after_first = len([
            c for c in socrata.calls if c[0] == DATASET_DOB_COMPLAINTS
        ])

        # Second call (same CD, same nightly run) must hit cache.
        second = _run(compute_caseload_proxy_for_cd(
            socrata, cd="301", now=cur_now,
        ))
        socrata_calls_after_second = len([
            c for c in socrata.calls if c[0] == DATASET_DOB_COMPLAINTS
        ])

        self.assertEqual(
            first, second,
            "Cached value must equal initial compute.",
        )
        self.assertEqual(
            socrata_calls_after_first, socrata_calls_after_second,
            f"PR #15A T3 cache regression — second call for same "
            f"CD must hit _caseload_proxy_cache. Got "
            f"{socrata_calls_after_second - socrata_calls_after_first} "
            f"extra eabe-havv queries. Stage 3: keyed-by-CD dict "
            f"check before socrata.query."
        )

    # ──────────────────────────────────────────────────────────
    # Test 3 — missing disposition_date defensive handling
    # ──────────────────────────────────────────────────────────

    def test_caseload_proxy_missing_disposition_date_handled(self):
        """Lock C complaint-ageing fallback pattern — when
        disposition_date is null (in-flight cases), drop the row
        from median calculation rather than crashing or producing
        NaN.

        Fixture: 7 closed + 3 in-flight (no disposition_date) →
        median computed over the 7 closed only.
        """
        self._require_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)

        # 7 closed with lag=5 days each.
        closed_entries = []
        for i in range(7):
            entered = cur_now - timedelta(days=i + 1)
            disposed = entered + timedelta(days=5)
            closed_entries.append({
                "date_entered":     entered.strftime("%m/%d/%Y"),
                "disposition_date": disposed.strftime("%m/%d/%Y"),
            })

        # 3 in-flight (disposition_date is None).
        in_flight = [
            {
                "date_entered":     (cur_now - timedelta(days=i + 1)).strftime("%m/%d/%Y"),
                "disposition_date": None,
            }
            for i in range(3)
        ]

        self._seed_cd_complaints(socrata, cd="301",
                                 entries=closed_entries + in_flight)

        # Helper must not raise on None disposition_date.
        try:
            result = _run(compute_caseload_proxy_for_cd(
                socrata, cd="301", now=cur_now,
            ))
        except (TypeError, ValueError) as e:
            self.fail(
                f"compute_caseload_proxy_for_cd crashed on null "
                f"disposition_date: {e!r}. Stage 3: drop rows where "
                f"_parse_bis_mdy_date(disposition_date) is None "
                f"BEFORE the median computation. Lock C fallback "
                f"pattern."
            )
        self.assertAlmostEqual(
            result, 5.0, delta=0.5,
            msg=(
                f"Median must be computed over the 7 closed rows only. "
                f"Got: {result}. Stage 3: filter out null "
                f"disposition_date entries; emit log "
                f"'[caseload_proxy] cb=301 dropped 3 rows missing "
                f"disposition_date'."
            ),
        )


if __name__ == "__main__":
    unittest.main()
