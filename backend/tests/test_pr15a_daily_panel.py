"""PR #15A Stage 2.B — Daily panel builder integration tests.

The daily panel is the (cohort_member, day) tuple-row training data
the nightly cron materializes for logistic-regression refit.

Locked design parameters (Stage 2.A):
  • T1 hybrid: panel builds active_swo_flag state machine per BIN/day;
    x_now wiring deferred to PR #15B.
  • T5 right-censoring: trailing 7 days have
    outcome_violation_d_to_d_plus_7 = None.
  • T6 provenance checksum: SHA1 of sorted cohort_member_provenance.bbl
    list; cache key = "daily_panel_provenance_checksum".
  • T8 cohort EXCLUDES active project (train/eval separation).
  • Severity filter: IN ('CLASS - 1', 'CLASS - 2', 'Hazardous').
  • Sample weights: Modern=1.0, Legacy=0.4 (Lock B).

9 tests in TestDailyPanel (single class per PR #14E/14F pattern):
  1. test_panel_build_produces_one_row_per_cohort_member_day
  2. test_panel_severity_filter_drops_class_3_and_non_hazardous
  3. test_active_swo_state_machine_last_disposition_wins
  4. test_complaint_velocity_14d_combines_eabe_and_311
  5. test_days_since_last_violation_clamped_at_90
  6. test_panel_carries_per_member_sample_weight_per_segment
  7. test_panel_skips_rebuild_when_provenance_checksum_unchanged
  8. test_menahan_real_data_panel_canary (120 peers, active excluded)
  9. test_legacy_extension_path_when_modern_below_100

All 9 RED at Stage 2.B. Stage 3 lands compute_daily_panel +
helpers.
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
sys.path.insert(0, str(_HERE))


def _run(coro):
    return asyncio.run(coro)


# ─── Lazy imports for PR #15A symbols ──────────────────────────────

try:
    from lib.statistical_engine.daily_panel import (  # type: ignore
        compute_daily_panel,
        _provenance_checksum,
    )
    HAS_PANEL_HELPER = True
except ImportError:
    compute_daily_panel = None  # type: ignore
    _provenance_checksum = None  # type: ignore
    HAS_PANEL_HELPER = False


# ─── Existing production imports ──────────────────────────────────

from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_PLUTO,
    DATASET_DOB_INSPECTIONS,
    DATASET_COMPLAINTS_311,
)


# ─── Test infrastructure imports ──────────────────────────────────

from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    DATASET_BIS_JOB_FILINGS,
    DATASET_DOB_PERMITS,
    DATASET_DOB_C_OF_O,
    DATASET_DOB_ECB_VIOLATIONS,
    DATASET_DOB_COMPLAINTS,
    DATASET_311,
    make_cohort_fixture,
    make_modern_cohort_fixture,
    seed_dob_now_for_bin,
    seed_menahan_realistic_dob_now,
    seed_ecb_violation_for_bin,
    seed_swo_disposition_for_bin,
)
from _pr15a_panel_fixtures import (  # noqa: E402
    _StubDailyPanels,
    _StubDb,
)


# ──────────────────────────────────────────────────────────────────
# Module-local helpers
# ──────────────────────────────────────────────────────────────────


def _menahan_like_project(**overrides) -> Dict[str, Any]:
    """Menahan-shaped project doc for PR #15A panel tests."""
    base = {
        "_id":                "P_MENAHAN_PR15A",
        "name":               "9 Menahan Street",
        "nyc_bin":            "3325703",
        "bbl":                "3033040024",
        "borough":            "BROOKLYN",
        "dob_project_type":   "major_alt_with_enlargement",
        "dob_extracted_scope": {"story_count": 4},
        "pluto_snapshot": {
            "bbl":       "3033040024.00000000",
            "borough":   "BK",
            "bldgclass": "C1",
            "landuse":   "01",
            "block":     "3040",
            "lot":       "24",
            "zipcode":   "11221",
            "cd":        "304",
            "yearbuilt": "1925",
            "unitsres":  "8",
            "unitstotal": "8",
            "numfloors": "4.0000000",
            "bldgarea":  "8038",
            "lotarea":   "2500",
        },
    }
    base.update(overrides)
    return base


def _build_project_with_provenance(
    *,
    n_modern: int = 0,
    n_legacy: int = 0,
    bbl_prefix_modern: str = "500101",
    bbl_prefix_legacy: str = "600101",
    bin_prefix_modern: str = "500100",
    bin_prefix_legacy: str = "600100",
) -> Dict[str, Any]:
    """Construct a project doc whose peer_stats_cache.peer_criteria
    carries the cohort_member_provenance list panel tests need.

    The panel builder reads cohort BBLs+BINs+segments straight from
    this list (PR #14E surface) — it does NOT recompute the cohort.
    """
    project = _menahan_like_project()
    provenance = []
    for i in range(n_modern):
        provenance.append({
            "job_id": f"MOD-{i:04d}",
            "bbl":    f"{bbl_prefix_modern}{i:04d}",
            "bin":    f"{bin_prefix_modern}{i:04d}",
            "source": "modern",
        })
    for i in range(n_legacy):
        provenance.append({
            "job_id": f"LEG-{i:04d}",
            "bbl":    f"{bbl_prefix_legacy}{i:04d}",
            "bin":    f"{bin_prefix_legacy}{i:04d}",
            "source": "legacy",
        })
    project["peer_stats_cache"] = {
        "status": "ready",
        "peer_criteria": {
            "schema_version":            "pr14e",
            "dob_project_type":          "major_alt_with_enlargement",
            "cohort_member_provenance":  provenance,
            "sample_size":               len(provenance),
            "cohort_source_segments": {
                "modern_count":         n_modern,
                "legacy_count":         n_legacy,
                "modern_window_months": 36,
                "legacy_window_start":  "2016-01-01",
                "legacy_window_end":    "2021-06-30",
            },
            "target_state": {
                "bldgclass":     "C1",
                "numfloors":     4,
                "numfloors_band": [3, 5],
                "source":        "parser",
                "band_widened":  False,
            },
        },
    }
    return project


# ──────────────────────────────────────────────────────────────────
# Test class
# ──────────────────────────────────────────────────────────────────


class TestDailyPanel(unittest.TestCase):
    """PR #15A — 9 daily-panel integration tests."""

    def _require_panel_helper(self):
        if not HAS_PANEL_HELPER:
            self.fail(
                "lib.statistical_engine.daily_panel.compute_daily_panel "
                "not implemented. Stage 3 PR #15A: create "
                "``lib/statistical_engine/daily_panel.py`` with "
                "``compute_daily_panel(project, db, socrata, *, "
                "panel_window_days, now=None) -> List[Dict]``. "
                "Reads cohort_member_provenance from "
                "peer_stats_cache.peer_criteria; emits one row per "
                "(cohort_member_bbl, day) into "
                "db.daily_panels.insert_many. Active project bbl "
                "EXCLUDED per T8 train/eval separation."
            )

    # ──────────────────────────────────────────────────────────
    # Test 1 — one row per (cohort_member, day)
    # ──────────────────────────────────────────────────────────

    def test_panel_build_produces_one_row_per_cohort_member_day(self):
        """Stage 2.A T1+T5 — panel emits one row per (cohort_member,
        day) tuple. 3 peers × 30 days = 90 rows. T5 right-censoring:
        last 7 days of each peer get outcome_violation_d_to_d_plus_7
        = None.
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = _build_project_with_provenance(
            n_modern=3, n_legacy=0,
        )
        # Empty event datasets — no outcomes, no SWO, no complaints.
        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = _StubDb()
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))

        # 3 peers × 30 days = 90 rows.
        self.assertEqual(
            len(rows), 90,
            f"Panel must emit 1 row per (cohort_member, day). "
            f"Expected 90 (3 peers × 30 days). Got {len(rows)}. "
            f"Stage 3: outer loop over cohort_member_provenance, "
            f"inner loop over day in range(panel_window_days).",
        )

        # Required columns present on every row.
        required_cols = {
            "project_id", "cohort_member_bbl", "cohort_member_bin",
            "cohort_segment", "sample_weight", "day_in_lifecycle",
            "day_calendar_date", "x_features",
            "outcome_violation_d", "outcome_violation_d_to_d_plus_7",
            "built_at", "panel_schema_version",
        }
        for r in rows[:5]:
            missing = required_cols - set(r.keys())
            self.assertFalse(
                missing,
                f"Panel row missing columns: {missing!r}. "
                f"Stage 3 §7.1: every row carries the full column "
                f"set. Row keys: {sorted(r.keys())!r}",
            )

        # T5 right-censoring: trailing 7 days = None.
        for r in rows:
            if r["day_in_lifecycle"] >= 30 - 7:
                self.assertIsNone(
                    r["outcome_violation_d_to_d_plus_7"],
                    f"PR #15A T5 lock — outcome_violation_d_to_d_plus_7 "
                    f"must be None for trailing 7 days. Got: "
                    f"{r['outcome_violation_d_to_d_plus_7']!r} for "
                    f"day_in_lifecycle={r['day_in_lifecycle']}",
                )

        # Schema version stamped.
        self.assertEqual(rows[0]["panel_schema_version"], "pr15a_v1")

    # ──────────────────────────────────────────────────────────
    # Test 2 — severity filter drops Class-3 / Non-Hazardous / Unknown
    # ──────────────────────────────────────────────────────────

    def test_panel_severity_filter_drops_class_3_and_non_hazardous(self):
        """Stage 2.A T4 lock — locked severity filter:
        ``severity IN ('CLASS - 1', 'CLASS - 2', 'Hazardous')``.
        Class-3, Non-Hazardous, Unknown must NOT trigger
        outcome_violation_d.

        Fixture: 1-peer cohort with 6 ECB violations on different
        days, one per severity enum value. Expected: 3 days have
        outcome_violation_d=True; 3 days have False.
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = _build_project_with_provenance(
            n_modern=1, n_legacy=0,
        )
        peer_bin = "5001000000"

        # 6 violations on days T-5, T-6, ..., T-10 (in panel window).
        severities_and_days = [
            ("CLASS - 1",     5),   # → outcome=True
            ("CLASS - 2",     6),   # → outcome=True
            ("Hazardous",     7),   # → outcome=True
            ("CLASS - 3",     8),   # → outcome=False (excluded)
            ("Non-Hazardous", 9),   # → outcome=False (excluded)
            ("Unknown",       10),  # → outcome=False (excluded)
        ]
        for sev, days_ago in severities_and_days:
            issue_dt = cur_now - timedelta(days=days_ago)
            seed_ecb_violation_for_bin(
                socrata, bin=peer_bin,
                issue_date=issue_dt.strftime("%Y%m%d"),
                severity=sev,
            )
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = _StubDb()
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))

        # Count outcome_d True days for this peer.
        n_true = sum(1 for r in rows if r["outcome_violation_d"])
        self.assertEqual(
            n_true, 3,
            f"PR #15A T4 lock — exactly 3 severe violations must "
            f"flip outcome_violation_d=True (CLASS-1, CLASS-2, "
            f"Hazardous). Class-3 / Non-Hazardous / Unknown are "
            f"excluded by the SoQL WHERE filter. Got n_true="
            f"{n_true}. Stage 3: WHERE severity IN ('CLASS - 1', "
            f"'CLASS - 2', 'Hazardous').",
        )

        # Verify the SoQL sent to Socrata carries the locked filter.
        ecb_calls = [c for c in socrata.calls
                     if c[0] == DATASET_DOB_ECB_VIOLATIONS]
        self.assertGreater(len(ecb_calls), 0)
        where = ecb_calls[0][1].get("where") or ""
        self.assertIn("CLASS - 1", where)
        self.assertIn("CLASS - 2", where)
        self.assertIn("Hazardous", where)
        self.assertNotIn(
            "CLASS - 3", where,
            f"Stage 3 T4 — locked filter must NOT include CLASS-3. "
            f"Got WHERE: {where!r}",
        )

    # ──────────────────────────────────────────────────────────
    # Test 3 — active SWO state machine (last-disposition-wins)
    # ──────────────────────────────────────────────────────────

    def test_active_swo_state_machine_last_disposition_wins(self):
        """Stage 2.A T1 lock — panel walks full disposition history
        per BIN; last disposition before day d wins.

        Codes: A8/A1 = active SWO; A9/B1 = rescind. Expected timeline
        for 1 peer:
          Day 5  → A8 (work close)        → active=1 from day 5 onward
          Day 10 → A8 (re-issued)         → still active=1
          Day 15 → B1 (rescind)           → active=0 from day 15
          Day 20 → A1 (issue work-stop)   → active=1 from day 20
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = _build_project_with_provenance(n_modern=1, n_legacy=0)
        peer_bin = "5001000000"

        # 4 dispositions for the same BIN on different disposition_date.
        events = [
            (5,  "A8"),  # active SWO issued
            (10, "A8"),  # re-issued (still active)
            (15, "B1"),  # rescind
            (20, "A1"),  # new work-stop
        ]
        for offset, code in events:
            disp_dt = (cur_now - timedelta(days=30 - 1 - offset))
            seed_swo_disposition_for_bin(
                socrata,
                bin=peer_bin,
                complaint_number=f"SWO-{offset:03d}",
                date_entered=disp_dt.strftime("%m/%d/%Y"),
                disposition_code=code,
                disposition_date=disp_dt.strftime("%m/%d/%Y"),
            )
        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])
        socrata.seed(DATASET_311, [])

        db = _StubDb()
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))
        # Sort by day_in_lifecycle to ease lookup.
        by_day = {r["day_in_lifecycle"]: r for r in rows}

        # Day 0-4: no disposition yet → active=0
        for d in range(5):
            self.assertEqual(
                by_day[d]["x_features"]["active_swo_flag"], 0,
                f"day {d}: no SWO yet, expected active_swo_flag=0",
            )
        # Day 5-14: A8 active
        for d in range(5, 15):
            self.assertEqual(
                by_day[d]["x_features"]["active_swo_flag"], 1,
                f"day {d}: A8 issued at day 5, still active. Got: "
                f"{by_day[d]['x_features']['active_swo_flag']!r}. "
                f"Stage 3 T1 hybrid: walk full disposition history "
                f"per BIN; last-disposition-wins per (BIN, day) tuple.",
            )
        # Day 15-19: B1 rescind → active=0
        for d in range(15, 20):
            self.assertEqual(
                by_day[d]["x_features"]["active_swo_flag"], 0,
                f"day {d}: B1 rescind at day 15, expected active=0",
            )
        # Day 20+: A1 work-stop → active=1
        for d in range(20, 30):
            self.assertEqual(
                by_day[d]["x_features"]["active_swo_flag"], 1,
                f"day {d}: A1 issued at day 20, expected active=1",
            )

    # ──────────────────────────────────────────────────────────
    # Test 4 — complaint velocity combines eabe-havv + 311
    # ──────────────────────────────────────────────────────────

    def test_complaint_velocity_14d_combines_eabe_and_311(self):
        """Stage 2.A T2 + Lock C — complaint_velocity_14d at panel
        build is a RAW count combining:
          • eabe-havv complaints by BIN in (day-14, day]
          • erm2-nwe9 (311) complaints by BBL in (day-14, day]

        Lock C ageing weight applied at x_now (PR #15B), NOT here.
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = _build_project_with_provenance(n_modern=1, n_legacy=0)
        peer_bbl = "5001010000"
        peer_bin = "5001000000"

        # 3 eabe-havv complaints by BIN: 2 within 14d of T-1, 1 outside.
        target_day = cur_now - timedelta(days=1)
        eabe_days = [(target_day - timedelta(days=2)),
                     (target_day - timedelta(days=5)),
                     (target_day - timedelta(days=15))]
        for i, dt in enumerate(eabe_days):
            seed_swo_disposition_for_bin(
                socrata,
                bin=peer_bin,
                complaint_number=f"CV-EABE-{i}",
                date_entered=dt.strftime("%m/%d/%Y"),
                disposition_code="A8",
                disposition_date=dt.strftime("%m/%d/%Y"),
            )

        # 4 erm2-nwe9 by BBL: 3 within 14d, 1 outside.
        e311_days = [(target_day - timedelta(days=1)),
                     (target_day - timedelta(days=7)),
                     (target_day - timedelta(days=10)),
                     (target_day - timedelta(days=20))]
        for i, dt in enumerate(e311_days):
            socrata.seed(DATASET_311, [{
                "unique_key":     f"311-{i:06d}",
                "bbl":            peer_bbl,
                "created_date":   dt.strftime("%Y-%m-%dT%H:%M:%S.000"),
                "complaint_type": "General Construction/Plumbing",
                "agency":         "DOB",
            }])
        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])

        db = _StubDb()
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))
        # Find row at target_day = day 28 (last full row before T5 censoring).
        by_day = {r["day_in_lifecycle"]: r for r in rows}
        # day_in_lifecycle = 30 - 1 - 1 = 28 for "yesterday".
        row = by_day[28]
        self.assertEqual(
            row["x_features"]["complaint_velocity_14d"],
            2 + 3,  # 2 eabe within 14d + 3 e311 within 14d
            f"PR #15A T2 — complaint_velocity_14d = raw count of "
            f"eabe-havv BIN complaints + erm2-nwe9 BBL complaints "
            f"in (day-14, day]. Expected 2+3=5; got: "
            f"{row['x_features']['complaint_velocity_14d']!r}. "
            f"Stage 3: union BIN+BBL queries, count rows where "
            f"date_entered >= day-14 (eabe) OR created_date >= "
            f"day-14 (311).",
        )

    # ──────────────────────────────────────────────────────────
    # Test 5 — days_since_last_violation clamped at 90
    # ──────────────────────────────────────────────────────────

    def test_days_since_last_violation_clamped_at_90(self):
        """Stage 2.A x[2] — days_since_last_violation clamped [0, 90].

        Fixture: 1 severe violation seeded with issue_date one year
        before panel window. Every panel row's
        days_since_last_violation must be 90 (clamped), not 365+.
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = _build_project_with_provenance(n_modern=1, n_legacy=0)
        peer_bin = "5001000000"

        # 1 violation 1 year before the panel start.
        old_issue_dt = cur_now - timedelta(days=395)  # 30 days before panel + 365
        seed_ecb_violation_for_bin(
            socrata, bin=peer_bin,
            issue_date=old_issue_dt.strftime("%Y%m%d"),
            severity="CLASS - 1",
        )
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = _StubDb()
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))
        for r in rows:
            dslv = r["x_features"]["days_since_last_violation"]
            self.assertEqual(
                dslv, 90,
                f"PR #15A x[2] clamp — days_since_last_violation "
                f"must be clamped to 90 (not 365+). day_in_lifecycle="
                f"{r['day_in_lifecycle']}, got dslv={dslv}. Stage 3: "
                f"``days_since_last_violation = min(90, max(0, "
                f"actual_delta))`` per spec V1.0.",
            )

    # ──────────────────────────────────────────────────────────
    # Test 6 — per-segment sample_weight
    # ──────────────────────────────────────────────────────────

    def test_panel_carries_per_member_sample_weight_per_segment(self):
        """Lock B — Modern=1.0, Legacy=0.4 sample weights.

        Fixture: 3 modern + 3 legacy peers; panel rows must carry
        the locked weight per segment.
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = _build_project_with_provenance(
            n_modern=3, n_legacy=3,
        )
        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = _StubDb()
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))

        modern_rows = [r for r in rows if r["cohort_segment"] == "modern"]
        legacy_rows = [r for r in rows if r["cohort_segment"] == "legacy"]
        self.assertEqual(len(modern_rows), 3 * 30,
                         "3 modern peers × 30 days")
        self.assertEqual(len(legacy_rows), 3 * 30,
                         "3 legacy peers × 30 days")

        for r in modern_rows:
            self.assertEqual(
                r["sample_weight"], 1.0,
                f"PR #15A Lock B — Modern peer sample_weight must "
                f"be 1.0. Got: {r['sample_weight']!r}. Stage 3: "
                f"map cohort_member_provenance.source ∈ "
                f"{{modern, legacy}} → {{1.0, 0.4}}.",
            )
        for r in legacy_rows:
            self.assertEqual(
                r["sample_weight"], 0.4,
                f"PR #15A Lock B — Legacy peer sample_weight must "
                f"be 0.4. Got: {r['sample_weight']!r}",
            )

    # ──────────────────────────────────────────────────────────
    # Test 7 — provenance-checksum no-op rebuild
    # ──────────────────────────────────────────────────────────

    def test_panel_skips_rebuild_when_provenance_checksum_unchanged(self):
        """Stage 2.A T6 lock — daily_panel_provenance_checksum =
        SHA1 of sorted cohort_member_provenance.bbl list. When
        nightly cron runs with unchanged cohort, no insert_many call.

        Fixture:
          1. Run cron → panel materialized
          2. Run cron again with same provenance → no rebuild
          3. Mutate provenance (add a 4th BBL) → rebuild fires
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = _build_project_with_provenance(n_modern=3, n_legacy=0)
        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = _StubDb()

        # Run 1: panel materializes.
        _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))
        first_insert_count = len(db.daily_panels.insert_many_calls)
        first_checksum = (project.get("peer_stats_cache", {})
                          .get("peer_criteria", {})
                          .get("daily_panel_provenance_checksum"))
        self.assertIsNotNone(
            first_checksum,
            f"PR #15A T6 — first run must set "
            f"peer_criteria.daily_panel_provenance_checksum. "
            f"Stage 3: compute SHA1 of sorted bbl list; persist "
            f"into peer_stats_cache via update_one.",
        )

        # Run 2: same cohort → no rebuild.
        _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))
        second_insert_count = len(db.daily_panels.insert_many_calls)
        self.assertEqual(
            second_insert_count, first_insert_count,
            f"PR #15A T6 — second run with unchanged provenance "
            f"checksum must NOT re-insert. Got "
            f"{second_insert_count - first_insert_count} extra "
            f"insert_many calls. Stage 3: compare incoming "
            f"checksum vs persisted; skip rebuild on match.",
        )

        # Run 3: mutate provenance (add 4th BBL), rebuild fires.
        project["peer_stats_cache"]["peer_criteria"][
            "cohort_member_provenance"
        ].append({
            "job_id": "MOD-9999",
            "bbl":    "5001019999",
            "bin":    "5001009999",
            "source": "modern",
        })
        _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))
        third_insert_count = len(db.daily_panels.insert_many_calls)
        self.assertGreater(
            third_insert_count, second_insert_count,
            f"PR #15A T6 — provenance mutation (new BBL added) "
            f"must trigger rebuild. Got {third_insert_count} total "
            f"inserts after 3 runs (expected > {second_insert_count}).",
        )

    # ──────────────────────────────────────────────────────────
    # Test 8 — Menahan real-data canary (n_records=120, active excluded)
    # ──────────────────────────────────────────────────────────

    def test_menahan_real_data_panel_canary(self):
        """T8 canary — real Menahan + 120 A1 peers (Modern primary,
        no Legacy fires above 100 floor). Per #7 lock: active
        project EXCLUDED from cohort panel.

        Real 19 severe Menahan ECB violations are seeded for
        Menahan's BIN, but Menahan is NOT in cohort_member_provenance
        → must NOT appear as cohort_member_bbl in panel rows.
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        menahan_bin = "3325703"
        menahan_bbl = "3033040024"

        # 120-peer modern cohort (above Q7 floor of 100 → no Legacy).
        provenance = [
            {"job_id": f"PEER-{i:04d}",
             "bbl":    f"303304{i+100:04d}",
             "bin":    f"303304{i+1:04d}",
             "source": "modern"}
            for i in range(120)
        ]
        project = _menahan_like_project(_id="P_MENAHAN_PR15A_CANARY")
        project["peer_stats_cache"] = {
            "status": "ready",
            "peer_criteria": {
                "schema_version": "pr14e",
                "cohort_member_provenance": provenance,
                "sample_size": 120,
                "cohort_source_segments": {
                    "modern_count": 120, "legacy_count": 0,
                    "modern_window_months": 36,
                    "legacy_window_start": "2016-01-01",
                    "legacy_window_end":   "2021-06-30",
                },
                "target_state": {
                    "bldgclass": "C1", "numfloors": 4,
                    "numfloors_band": [3, 5],
                    "source": "parser",
                },
            },
        }

        # Real Menahan rbx6-tga4 rows (PR #14D fixture).
        seed_menahan_realistic_dob_now(socrata)
        # Real Menahan ECB history: 19 severe (CLASS-1: 7, CLASS-2: 11,
        # Hazardous: 1) + 2 Non-Hazardous excluded.
        # Per Stage 1 curl verification, dates span 2008-01 → 2026-03.
        # Within panel window (last 90 days from 2026-05-15 = 2026-02-14),
        # we expect 1 severe at issue_date=20260320 — but that's AFTER
        # cur_now=2026-05-15. Adjust the test seed to put 1 recent
        # severe inside the window.
        # Most realistic: seed Menahan's 19 verified severe violations
        # AT their real dates per curl evidence; only the most recent
        # (2026-03-20) lands in the panel window.
        # The test treats Menahan's history as REPRESENTATIVE — the
        # seed exists so any future "active project also in panel"
        # bug would surface, but per #7 lock the active project IS
        # NOT in the panel. The assertion below verifies this.
        seed_ecb_violation_for_bin(
            socrata, bin=menahan_bin,
            issue_date="20260320",      # within panel window
            severity="CLASS - 1",
        )
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = _StubDb()
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=90, now=cur_now,
        ))

        # 120 peers × 90 days = 10,800 rows.
        self.assertEqual(
            len(rows), 120 * 90,
            f"PR #15A T8 + #6 lock — n_records=120 cohort × 90 days "
            f"= 10,800 panel rows. Got: {len(rows)}. Stage 3: "
            f"panel builder reads cohort_member_provenance verbatim.",
        )

        # #7 lock: Menahan's own BIN/BBL must NOT appear as a
        # cohort_member.
        menahan_panel_rows = [
            r for r in rows
            if r["cohort_member_bbl"] == menahan_bbl
            or r["cohort_member_bin"] == menahan_bin
        ]
        self.assertEqual(
            len(menahan_panel_rows), 0,
            f"PR #15A #7 lock — active project EXCLUDED from cohort "
            f"panel (train/eval separation). Menahan bbl/bin "
            f"appeared in {len(menahan_panel_rows)} panel rows. "
            f"Stage 3: filter cohort_member_provenance against "
            f"project.bbl + project.nyc_bin before panel build.",
        )

    # ──────────────────────────────────────────────────────────
    # Test 9 — Legacy extension when Modern < 100
    # ──────────────────────────────────────────────────────────

    def test_legacy_extension_path_when_modern_below_100(self):
        """#6 lock — when cohort_source_segments shows mixed
        modern + legacy, panel correctly tags each row's
        cohort_segment AND applies per-segment sample_weight.

        Fixture: provenance carries 80 modern + 40 legacy entries
        (mirrors PR #14E Q7 legacy-extension path).
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        project = _build_project_with_provenance(
            n_modern=80, n_legacy=40,
        )
        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = _StubDb()
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))

        # 120 peers × 30 days = 3,600 rows.
        self.assertEqual(len(rows), 120 * 30)

        modern_rows = [r for r in rows if r["cohort_segment"] == "modern"]
        legacy_rows = [r for r in rows if r["cohort_segment"] == "legacy"]
        self.assertEqual(
            len(modern_rows), 80 * 30,
            f"Expected 2400 modern rows (80 × 30). Got {len(modern_rows)}.",
        )
        self.assertEqual(
            len(legacy_rows), 40 * 30,
            f"Expected 1200 legacy rows (40 × 30). Got {len(legacy_rows)}.",
        )

        # Per-segment sample_weight applied (re-check on mixed cohort).
        for r in modern_rows[:5]:
            self.assertEqual(r["sample_weight"], 1.0)
        for r in legacy_rows[:5]:
            self.assertEqual(r["sample_weight"], 0.4)

        # Provenance metadata in cache reflects 80/40 split.
        segments = (project.get("peer_stats_cache", {})
                    .get("peer_criteria", {})
                    .get("cohort_source_segments", {}))
        self.assertEqual(segments.get("modern_count"), 80)
        self.assertEqual(segments.get("legacy_count"), 40)

    # ──────────────────────────────────────────────────────────
    # Phase 1 Week 2 — schedule_position_ratio per-(member, day)
    # ──────────────────────────────────────────────────────────

    def _build_db_with_permits(self, permit_rows):
        """Attach a minimal socrata_permits_historical stub onto
        the standard _StubDb. The B3 prefetch reads via
        db.socrata_permits_historical.find({...}, {...}); the stub
        below supports that single query shape."""
        db = _StubDb()
        db.socrata_permits_historical = _StubPermitsHistorical(permit_rows)
        return db

    def test_earliest_issued_prefetch_returns_per_bin_dict(self):
        """Phase 1 Week 2 D4 — B3 pre-fetch step builds per-BIN
        earliest_issued dict from socrata_permits_historical.

        Seed 3 cohort BINs × 2 permits each with different dates;
        panel-row emission should use each BIN's MIN issued_date as
        the start anchor for that member's schedule_position_ratio.
        """
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = _build_project_with_provenance(n_modern=3, n_legacy=0)
        # Cohort BINs: 5001000000, 5001000001, 5001000002
        project["peer_stats_cache"]["peer_criteria"][
            "cohort_median_duration_days"
        ] = 365.0  # 1-year expected duration

        # Seed permits with KNOWN earliest_issued per BIN.
        # BIN 5001000000 → 2025-11-21 (180 days before cur_now)
        # BIN 5001000001 → 2026-02-19 (90 days before cur_now)
        # BIN 5001000002 → 2026-05-05 (15 days before cur_now)
        permit_rows = [
            {"bin": "5001000000", "filing_reason": "Initial Permit",
             "issued_date": "2025-11-21T00:00:00.000"},
            {"bin": "5001000000", "filing_reason": "Initial Permit",
             "issued_date": "2026-01-15T00:00:00.000"},   # later — dropped
            {"bin": "5001000001", "filing_reason": "Initial Permit",
             "issued_date": "2026-02-19T00:00:00.000"},
            {"bin": "5001000001", "filing_reason": "Initial Permit",
             "issued_date": "2026-03-30T00:00:00.000"},   # later — dropped
            {"bin": "5001000002", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-05T00:00:00.000"},
            {"bin": "5001000002", "filing_reason": "Initial Permit",
             "issued_date": "2026-05-10T00:00:00.000"},   # later — dropped
        ]

        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = self._build_db_with_permits(permit_rows)
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=1, now=cur_now,
        ))

        # Trailing day_dt = cur_now. For BIN ...000 elapsed = 180,
        # for ...001 elapsed = 90, for ...002 elapsed = 15. Ratio
        # vs 365-day expected → ~0.493, ~0.247, ~0.041.
        by_bin = {r["cohort_member_bin"]: r for r in rows}
        self.assertEqual(set(by_bin), {
            "5001000000", "5001000001", "5001000002",
        })
        r0 = by_bin["5001000000"]["x_features"]["schedule_position_ratio"]
        r1 = by_bin["5001000001"]["x_features"]["schedule_position_ratio"]
        r2 = by_bin["5001000002"]["x_features"]["schedule_position_ratio"]
        self.assertAlmostEqual(r0, 180.0 / 365.0, places=2)
        self.assertAlmostEqual(r1,  90.0 / 365.0, places=2)
        self.assertAlmostEqual(r2,  15.0 / 365.0, places=2)

    def test_earliest_issued_prefetch_skips_bins_without_initial_permit(self):
        """Phase 1 Week 2 D4 — BINs with no Initial Permit rows in
        socrata_permits_historical produce schedule_position_ratio =
        None on every panel row. Downstream _substitute_panel_mu_for_nones
        handles fallback. Backfill scope is 5k BINs; the cohort may
        include BINs outside that scope, and those land here."""
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = _build_project_with_provenance(n_modern=2, n_legacy=0)
        project["peer_stats_cache"]["peer_criteria"][
            "cohort_median_duration_days"
        ] = 365.0

        # Seed permits for only ONE of the two cohort BINs, and only
        # with non-Initial Permit filing_reason for the other (must
        # be skipped by the WHERE clause).
        permit_rows = [
            {"bin": "5001000000", "filing_reason": "Initial Permit",
             "issued_date": "2025-11-21T00:00:00.000"},
            {"bin": "5001000001", "filing_reason": "Renewal Permit",
             "issued_date": "2026-01-15T00:00:00.000"},
            # BIN 5001000001 has NO Initial Permit row.
        ]

        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = self._build_db_with_permits(permit_rows)
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=1, now=cur_now,
        ))

        by_bin = {r["cohort_member_bin"]: r for r in rows}
        r0 = by_bin["5001000000"]["x_features"]["schedule_position_ratio"]
        r1 = by_bin["5001000001"]["x_features"]["schedule_position_ratio"]
        # BIN with Initial Permit row gets a real value.
        self.assertIsNotNone(r0)
        self.assertGreater(r0, 0.0)
        # BIN without Initial Permit row gets None.
        self.assertIsNone(r1)

    def test_panel_row_schedule_position_uses_per_member_per_day_value(self):
        """Phase 1 Week 2 — regression test for the cohort-constant
        bug. Two cohort members with DIFFERENT earliest_issued dates,
        sampled across multiple panel days, must produce DIFFERENT
        ratios per day. The OLD derived_lifecycle_stage_pct returned
        the same cohort-median value for every (member, day) tuple —
        this test pins the new per-(member, day) behavior."""
        self._require_panel_helper()
        socrata = MockSocrataClient()
        cur_now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = _build_project_with_provenance(n_modern=2, n_legacy=0)
        project["peer_stats_cache"]["peer_criteria"][
            "cohort_median_duration_days"
        ] = 365.0

        permit_rows = [
            # Member A — permit 365 days ago → ratio rises 0.00→1.00
            # across a 30-day panel window (day_offset 0 = ~335 days
            # since permit, ratio ≈ 0.918; day_offset 29 = ~365 days,
            # ratio ≈ 1.0).
            {"bin": "5001000000", "filing_reason": "Initial Permit",
             "issued_date": "2025-05-20T00:00:00.000"},
            # Member B — permit 100 days ago → ratio ≈ 0.19 → 0.27
            # across the window.
            {"bin": "5001000001", "filing_reason": "Initial Permit",
             "issued_date": "2026-02-09T00:00:00.000"},
        ]

        socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [])
        socrata.seed(DATASET_DOB_COMPLAINTS, [])
        socrata.seed(DATASET_311, [])

        db = self._build_db_with_permits(permit_rows)
        rows = _run(compute_daily_panel(
            project=project, db=db, socrata=socrata,
            panel_window_days=30, now=cur_now,
        ))

        # 2 peers × 30 days = 60 rows.
        self.assertEqual(len(rows), 60)

        # Same-member, different-day rows must vary in ratio (the
        # core fix — cohort-constant was the bug).
        by_bin = {}
        for r in rows:
            by_bin.setdefault(r["cohort_member_bin"], []).append(r)

        a_ratios = [
            r["x_features"]["schedule_position_ratio"]
            for r in sorted(by_bin["5001000000"],
                            key=lambda r: r["day_in_lifecycle"])
        ]
        b_ratios = [
            r["x_features"]["schedule_position_ratio"]
            for r in sorted(by_bin["5001000001"],
                            key=lambda r: r["day_in_lifecycle"])
        ]

        # Per-day variation within member A — last day strictly
        # greater than first day (time advanced 29 days).
        self.assertGreater(a_ratios[-1], a_ratios[0])
        self.assertGreater(b_ratios[-1], b_ratios[0])

        # Cross-member variation on the same day — member A's ratio
        # should be larger than B's at every day (A's permit is older).
        for day_idx in range(30):
            self.assertGreater(
                a_ratios[day_idx], b_ratios[day_idx],
                f"day_idx={day_idx}: A's older permit must yield "
                f"higher ratio than B's newer permit. "
                f"a={a_ratios[day_idx]!r} b={b_ratios[day_idx]!r}",
            )


# ─── Stub for Phase 1 Week 2 D4 — socrata_permits_historical ──────


class _StubPermitsHistorical:
    """Minimal stub matching the production Motor collection's
    `find(filter, projection)` surface used by the new B3 prefetch
    step. Filter shape supported:

      {"bin": {"$in": [...]}, "filing_reason": "Initial Permit"}

    Projection shape supported:

      {"bin": 1, "issued_date": 1}

    Returns an _AsyncCursorList compatible with `.to_list(length=None)`.
    """

    def __init__(self, rows):
        self._rows = list(rows or [])

    def find(self, filter_=None, projection=None):
        filter_ = filter_ or {}
        bin_filter = filter_.get("bin") or {}
        in_list = bin_filter.get("$in") if isinstance(bin_filter, dict) else None
        filing_reason = filter_.get("filing_reason")

        out = []
        for r in self._rows:
            if in_list is not None and r.get("bin") not in in_list:
                continue
            if filing_reason is not None and r.get("filing_reason") != filing_reason:
                continue
            out.append(r)
        return _AsyncCursorList(out)


class _AsyncCursorList:
    """Tiny shim mimicking Motor cursors' `.to_list(length=None)`."""
    def __init__(self, items):
        self._items = items

    async def to_list(self, length=None):
        if length is None:
            return list(self._items)
        return list(self._items[:length])


if __name__ == "__main__":
    unittest.main()
