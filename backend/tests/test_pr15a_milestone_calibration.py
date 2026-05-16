"""PR #15A Stage 2.B — Cohort-derived milestone calibration tests.

Lock 1.2: derived_lifecycle_stage_pct uses cohort-median time-to-
milestone ratios (foundation_pct, structural_pct, c_of_o_final_pct)
rather than hardcoded _MILESTONE_COMPLETION_PCT defaults.

Fallback: when cohort has <30 contributing members for a given
milestone, the hardcoded baselines._MILESTONE_COMPLETION_PCT values
are used.

Plus Chapter 33 Safety Cliff: when target_stories >= 7, the
numfloors_band floor is raised to max(7, int(target_stories * 0.75)).

4 tests in TestMilestoneCalibration:
  1. test_cohort_derived_milestone_pct_uses_median_of_per_member_ratios
  2. test_cohort_derived_milestone_skips_members_without_complete_milestones
  3. test_cohort_derived_milestone_falls_back_to_hardcoded_when_n_below_30
  4. test_safety_cliff_floor_applied_when_target_stories_above_7

All 4 RED at Stage 2.B. Stage 3 lands:
  • New helper: lib.statistical_engine.daily_panel.derive_cohort_milestone_pct
  • Safety Cliff floor in lib.statistical_engine.baselines._derive_target_state_for_project
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
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
        derive_cohort_milestone_pct,
    )
    HAS_DERIVE_HELPER = True
except ImportError:
    derive_cohort_milestone_pct = None  # type: ignore
    HAS_DERIVE_HELPER = False


# Existing helper — must remain available
from lib.statistical_engine.baselines import (  # noqa: E402
    _derive_target_state_for_project,
    _MILESTONE_COMPLETION_PCT,
)


# ─── Test infrastructure imports ──────────────────────────────────

from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    DATASET_DOB_C_OF_O,
    DATASET_DOB_PERMITS,
    seed_pkdm_co_for_bin,
    seed_dob_now_for_bin,
)


# ──────────────────────────────────────────────────────────────────
# Test class
# ──────────────────────────────────────────────────────────────────


class TestMilestoneCalibration(unittest.TestCase):
    """PR #15A — 4 tests for cohort-derived lifecycle milestone
    calibration + Chapter 33 Safety Cliff floor."""

    def _require_derive_helper(self):
        if not HAS_DERIVE_HELPER:
            self.fail(
                "lib.statistical_engine.daily_panel."
                "derive_cohort_milestone_pct not implemented. "
                "Stage 3 PR #15A Lock 1.2: per-cohort milestone "
                "calibration. Walk each cohort member's rbx6-tga4 "
                "permits + pkdm-hqz6 C of O to compute per-member "
                "(t_milestone - t_0) / (t_end - t_0) ratios. Median "
                "across all members yields cohort-derived milestone "
                "pct. Falls back to _MILESTONE_COMPLETION_PCT when "
                "N<30 contributors."
            )

    def _seed_cohort_member_lifecycle(
        self,
        socrata,
        *,
        bin: str,
        bbl: str,
        t_0_iso: str,
        t_foundation_iso: Optional[str],
        t_structural_iso: Optional[str],
        t_end_pkdm_mdy: str,
        borough: str = "BROOKLYN",
    ) -> None:
        """Seed one cohort member's full milestone timeline:
          • rbx6-tga4 row for Initial Permit at t_0
          • rbx6-tga4 row for Foundation at t_foundation (optional)
          • rbx6-tga4 row for Structural at t_structural (optional)
          • pkdm-hqz6 row for Final C of O at t_end
        """
        # T_0 — Initial Permit, General Construction.
        # Seed directly into rbx6-tga4 with bbl set (production
        # format) — seed_dob_now_for_bin is BIN-keyed and doesn't
        # populate bbl, but derive_cohort_milestone_pct queries by
        # bbl IN (chunk).
        socrata.seed(DATASET_DOB_PERMITS, [{
            "bin":               bin,
            "bbl":               bbl,
            "job_filing_number": f"B{bin[-7:]}-I1",
            "work_type":         "General Construction",
            "filing_reason":     "Initial Permit",
            "permit_status":     "Permit Issued",
            "borough":           borough,
            "issued_date":       t_0_iso,
            "approved_date":     f"{t_0_iso}T00:00:00.000",
        }])
        # Foundation milestone (optional — Test 2 omits some members).
        if t_foundation_iso is not None:
            socrata.seed(DATASET_DOB_PERMITS, [{
                "bin":               bin,
                "bbl":               bbl,
                "job_filing_number": f"B{bin[-7:]}-S1",
                "work_type":         "Foundation",
                "filing_reason":     "Initial Permit",
                "permit_status":     "Permit Issued",
                "borough":           borough,
                "issued_date":       t_foundation_iso,
                "approved_date":     f"{t_foundation_iso}T00:00:00.000",
            }])
        if t_structural_iso is not None:
            socrata.seed(DATASET_DOB_PERMITS, [{
                "bin":               bin,
                "bbl":               bbl,
                "job_filing_number": f"B{bin[-7:]}-S2",
                "work_type":         "Structural",
                "filing_reason":     "Initial Permit",
                "permit_status":     "Permit Issued",
                "borough":           borough,
                "issued_date":       t_structural_iso,
                "approved_date":     f"{t_structural_iso}T00:00:00.000",
            }])
        # T_end — Final C of O (pkdm-hqz6, MM/DD/YY HH:MM:SS AM/PM).
        seed_pkdm_co_for_bin(
            socrata, bin=bin, bbl=bbl,
            job_type="ALTERATION TYPE 1",
            c_of_o_filing_type="Final",
            c_of_o_issuance_date_mdy=t_end_pkdm_mdy,
            borough=borough,
        )

    # ──────────────────────────────────────────────────────────
    # Test 1 — median of per-member ratios
    # ──────────────────────────────────────────────────────────

    def test_cohort_derived_milestone_pct_uses_median_of_per_member_ratios(self):
        """Lock 1.2 — cohort-derived milestone pct = median of per-
        member (t_milestone - t_0) / (t_end - t_0) ratios.

        Fixture: 5-peer cohort with synthesized per-peer ratios for
        foundation = {0.15, 0.18, 0.20, 0.22, 0.25} → median 0.20.
        For structural = {0.35, 0.38, 0.40, 0.42, 0.45} → median 0.40.

        Note: 5-peer cohort is BELOW the N=30 fallback floor in
        production (Test 3); this test bypasses the floor by
        passing ``n_floor=1`` to exercise the median computation
        directly.
        """
        self._require_derive_helper()
        socrata = MockSocrataClient()

        # 5 peers, T_0 = 2022-01-01, T_end = 2024-01-01 (730 days).
        # Foundation at {0.15, 0.18, 0.20, 0.22, 0.25} of 730 days.
        # Structural at {0.35, 0.38, 0.40, 0.42, 0.45} of 730 days.
        foundation_ratios = [0.15, 0.18, 0.20, 0.22, 0.25]
        structural_ratios = [0.35, 0.38, 0.40, 0.42, 0.45]
        for i in range(5):
            bbl = f"30033010{i:03d}"
            bin_ = f"30033{i:03d}"
            # rbx6-tga4 issued_date is ISO; bin needs to be 7 digits.
            from datetime import timedelta as _td
            t0 = datetime(2022, 1, 1)
            tend_days = 730
            tfound = t0 + _td(days=int(tend_days * foundation_ratios[i]))
            tstruct = t0 + _td(days=int(tend_days * structural_ratios[i]))
            tend = t0 + _td(days=tend_days)
            self._seed_cohort_member_lifecycle(
                socrata,
                bin=bin_, bbl=bbl,
                t_0_iso=t0.strftime("%Y-%m-%d"),
                t_foundation_iso=tfound.strftime("%Y-%m-%d"),
                t_structural_iso=tstruct.strftime("%Y-%m-%d"),
                t_end_pkdm_mdy=tend.strftime("%m/%d/%y %I:%M:%S %p"),
            )

        cohort_bbls = [f"30033010{i:03d}" for i in range(5)]
        cohort_bins = [f"30033{i:03d}" for i in range(5)]
        # Pass n_floor=1 to bypass the production N=30 fallback gate.
        result = _run(derive_cohort_milestone_pct(
            socrata,
            cohort_bbls=cohort_bbls,
            cohort_bins=cohort_bins,
            n_floor=1,
        ))
        self.assertIsInstance(result, dict)
        self.assertAlmostEqual(
            result.get("foundation"), 0.20, delta=0.02,
            msg=(
                f"foundation pct must be the median of per-member "
                f"ratios {foundation_ratios} = 0.20. Got: "
                f"{result.get('foundation')!r}. Stage 3 Lock 1.2: "
                f"compute (t_foundation - t_0) / (t_end - t_0) per "
                f"member; statistics.median across all members."
            ),
        )
        self.assertAlmostEqual(
            result.get("structural"), 0.40, delta=0.02,
            msg=(
                f"structural pct must be the median of per-member "
                f"ratios {structural_ratios} = 0.40. Got: "
                f"{result.get('structural')!r}."
            ),
        )

    # ──────────────────────────────────────────────────────────
    # Test 2 — skip members without complete milestones
    # ──────────────────────────────────────────────────────────

    def test_cohort_derived_milestone_skips_members_without_complete_milestones(self):
        """Lock 1.2 — drop a member from the median calculation
        for any milestone they lack. Helper must report per-
        milestone contributor counts so the alert layer can see
        which milestones are well-calibrated.

        Fixture: 10 peers; 7 have Foundation permit, 3 don't.
        All 10 have T_0 + T_end.
        """
        self._require_derive_helper()
        socrata = MockSocrataClient()

        for i in range(10):
            bbl = f"30033020{i:03d}"
            bin_ = f"30034{i:03d}"
            from datetime import timedelta as _td
            t0 = datetime(2022, 1, 1)
            tfound = (t0 + _td(days=146)) if i < 7 else None  # 0.20 of 730
            tend = t0 + _td(days=730)
            self._seed_cohort_member_lifecycle(
                socrata,
                bin=bin_, bbl=bbl,
                t_0_iso=t0.strftime("%Y-%m-%d"),
                t_foundation_iso=tfound.strftime("%Y-%m-%d") if tfound else None,
                t_structural_iso=None,
                t_end_pkdm_mdy=tend.strftime("%m/%d/%y %I:%M:%S %p"),
            )

        cohort_bbls = [f"30033020{i:03d}" for i in range(10)]
        cohort_bins = [f"30034{i:03d}" for i in range(10)]
        result = _run(derive_cohort_milestone_pct(
            socrata,
            cohort_bbls=cohort_bbls,
            cohort_bins=cohort_bins,
            n_floor=1,
        ))
        # Contributors metadata must reflect 7, not 10.
        contributors = result.get("foundation_n_contributors")
        self.assertEqual(
            contributors, 7,
            f"foundation_n_contributors must be 7 (3 of 10 peers "
            f"lack Foundation permit). Got: {contributors!r}. "
            f"Stage 3: emit per-milestone _n_contributors alongside "
            f"the median pct. Log: '[milestone] foundation skipped "
            f"for 3 cohort members (no permit record)'."
        )
        # Median is over the 7 contributing peers — all with ratio 0.20.
        self.assertAlmostEqual(
            result.get("foundation"), 0.20, delta=0.02,
            msg=(
                f"foundation median over 7 contributors all at 0.20 "
                f"should be 0.20. Got: {result.get('foundation')!r}"
            ),
        )

    # ──────────────────────────────────────────────────────────
    # Test 3 — fallback to hardcoded when N<30
    # ──────────────────────────────────────────────────────────

    def test_cohort_derived_milestone_falls_back_to_hardcoded_when_n_below_30(self):
        """Lock 1.2 — when cohort has <30 contributing members for
        a milestone, fall back to baselines._MILESTONE_COMPLETION_PCT
        hardcoded values. Source marker indicates the fallback path
        fired so downstream consumers can flag low-confidence.

        Fixture: 5-peer cohort, all with complete milestones (so 5
        contributors). Helper called with production default
        n_floor=30 → falls back.
        """
        self._require_derive_helper()
        socrata = MockSocrataClient()

        for i in range(5):
            bbl = f"30033030{i:03d}"
            bin_ = f"30035{i:03d}"
            from datetime import timedelta as _td
            t0 = datetime(2022, 1, 1)
            tend = t0 + _td(days=730)
            self._seed_cohort_member_lifecycle(
                socrata,
                bin=bin_, bbl=bbl,
                t_0_iso=t0.strftime("%Y-%m-%d"),
                t_foundation_iso=(t0 + _td(days=146)).strftime("%Y-%m-%d"),
                t_structural_iso=(t0 + _td(days=292)).strftime("%Y-%m-%d"),
                t_end_pkdm_mdy=tend.strftime("%m/%d/%y %I:%M:%S %p"),
            )

        cohort_bbls = [f"30033030{i:03d}" for i in range(5)]
        cohort_bins = [f"30035{i:03d}" for i in range(5)]
        # Default n_floor=30 → 5 contributors below floor → fallback.
        result = _run(derive_cohort_milestone_pct(
            socrata,
            cohort_bbls=cohort_bbls,
            cohort_bins=cohort_bins,
        ))
        # Fallback uses hardcoded values from _MILESTONE_COMPLETION_PCT.
        self.assertEqual(
            result.get("foundation"),
            _MILESTONE_COMPLETION_PCT.get("foundation"),
            f"PR #15A Lock 1.2 — small cohort must fall back to "
            f"_MILESTONE_COMPLETION_PCT['foundation']="
            f"{_MILESTONE_COMPLETION_PCT.get('foundation')}. Got: "
            f"{result.get('foundation')!r}",
        )
        self.assertEqual(
            result.get("source"), "hardcoded_fallback",
            f"Stage 3: emit ``source=\"hardcoded_fallback\"`` "
            f"marker so prediction_cache can flag low-confidence. "
            f"Got: {result.get('source')!r}",
        )

    # ──────────────────────────────────────────────────────────
    # Test 4 — Chapter 33 Safety Cliff floor
    # ──────────────────────────────────────────────────────────

    def test_safety_cliff_floor_applied_when_target_stories_above_7(self):
        """PR #15A Chapter 33 — target_stories>=7 triggers Safety
        Cliff floor: min_stories = max(7, int(target_stories * 0.75)).

        Per #5 lock: input target_stories=8.
          Without Safety Cliff: ±25% band = [6, 10]
          With Safety Cliff: floor raised to max(7, int(8*0.75)=6) = 7
          Resulting band: [7, 10]
        """
        project = {
            "_id":              "P_SAFETY_CLIFF",
            "nyc_bin":          "3000001",
            "bbl":              "3000010001",
            "borough":          "BROOKLYN",
            "dob_project_type": "major_alt_with_enlargement",
            "dob_extracted_scope": {"story_count": 8},  # parser-derived
            "pluto_snapshot": {
                "bbl":        "3000010001", "borough": "BK",
                "bldgclass":  "C1", "numfloors": "8",
                "yearbuilt":  "1925",
            },
        }
        target_state = _derive_target_state_for_project(
            project, "major_alt_with_enlargement",
        )
        band = target_state.get("numfloors_band")
        self.assertIsNotNone(band, "numfloors_band must be present")
        self.assertEqual(
            list(band), [7, 10],
            f"PR #15A Chapter 33 Safety Cliff — target_stories=8 "
            f"must raise band floor from 6 to 7 (max(7, "
            f"int(8*0.75))=7). Expected band [7, 10]; got "
            f"{list(band)!r}. Stage 3: in "
            f"baselines._derive_target_state_for_project, after "
            f"computing the ±25% / ±50% band for A1, apply "
            f"``if parser_floors >= 7: base['numfloors_band'][0] = "
            f"max(base['numfloors_band'][0], max(7, "
            f"int(parser_floors * 0.75)))``",
        )
        self.assertTrue(
            target_state.get("numfloors_band_safety_cliff_applied"),
            f"Stage 3: emit ``numfloors_band_safety_cliff_applied = "
            f"True`` flag when the floor raises the lower bound. "
            f"Got: {target_state.get('numfloors_band_safety_cliff_applied')!r}",
        )


if __name__ == "__main__":
    unittest.main()
