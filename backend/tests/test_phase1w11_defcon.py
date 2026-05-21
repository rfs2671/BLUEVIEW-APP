"""Phase 1 Week 11-12 PR-A — Defcon 3-tier urgency tests.

Strategy: test the PURE tier-precedence + reason-formatter logic
directly via _apply_tier_precedence(inputs) and _format_primary_reason
(tier, factors, inputs). The integration wrapper compute_defcon_status
is exercised by a smaller set of stub-backed end-to-end tests.

This split lets us cover all 9 precedence rules + the phase override
+ severity mapping + reason templates without standing up the
dob_logs aggregate stub for every case.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
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
    from lib.statistical_engine.defcon import (
        TIER_NORMAL,
        TIER_ELEVATED,
        TIER_IMMEDIATE,
        TIER_TO_COLOR,
        compute_defcon_status,
        _apply_tier_precedence,
        _format_primary_reason,
    )
    HAS_DEFCON = True
except ImportError:
    TIER_NORMAL = "NORMAL"          # type: ignore
    TIER_ELEVATED = "ELEVATED"      # type: ignore
    TIER_IMMEDIATE = "IMMEDIATE"    # type: ignore
    TIER_TO_COLOR = {}              # type: ignore
    compute_defcon_status = None    # type: ignore
    _apply_tier_precedence = None   # type: ignore
    _format_primary_reason = None   # type: ignore
    HAS_DEFCON = False


def _make_inputs(**overrides) -> Dict[str, Any]:
    """Default Defcon input dict — caller overrides the fields under test.
    All defaults are "no signal" so the tier resolves to NORMAL unless
    a specific override fires a rule."""
    base = {
        "swo_active":                   False,
        "swo_days_open":                None,
        "hr_14d":                       None,
        "recent_class_1_count":         0,
        "recent_class_2_count":         0,
        "recent_complaints_count":      0,
        "phase":                        "unknown",
        # for primary_reason rendering:
        "borough":                      "BROOKLYN",
        "work_type":                    "General Construction",
        "most_recent_class_1_days_ago": None,
        "most_recent_class_1_bucket":   None,
        "most_recent_class_2_days_ago": None,
        "most_recent_class_2_bucket":   None,
    }
    base.update(overrides)
    return base


class TestDefconTierPrecedence(unittest.TestCase):
    """Phase 1 Week 11 PR-A — pure precedence rule tests."""

    def _require(self):
        if not HAS_DEFCON:
            self.fail(
                "lib.statistical_engine.defcon not implemented. "
                "Phase 1 Week 11 PR-A: add the module per Stage 2.A spec."
            )

    # ──────────────────────────────────────────────────────────
    # Rule 9 — Default NORMAL
    # ──────────────────────────────────────────────────────────

    def test_normal_default_when_nothing_fires(self):
        """All signals quiet → NORMAL. No factors fired."""
        self._require()
        tier, factors = _apply_tier_precedence(_make_inputs())
        self.assertEqual(tier, TIER_NORMAL)
        # Factors list may be empty or contain only informational
        # entries — the contract is that no escalating factor fired.

    # ──────────────────────────────────────────────────────────
    # Rule 5 — Active SWO alone → ELEVATED
    # ──────────────────────────────────────────────────────────

    def test_elevated_when_swo_active_alone(self):
        """Active SWO (short duration, no demolition) → ELEVATED minimum."""
        self._require()
        tier, factors = _apply_tier_precedence(_make_inputs(
            swo_active=True, swo_days_open=5, phase="interior",
        ))
        self.assertEqual(tier, TIER_ELEVATED)
        # At least one factor must reference SWO
        self.assertTrue(
            any("swo" in f.get("factor", "").lower() for f in factors),
            msg=f"Expected at least one SWO-related factor. Got: {factors!r}",
        )

    # ──────────────────────────────────────────────────────────
    # Rule 8 — Complaint clustering → ELEVATED
    # ──────────────────────────────────────────────────────────

    def test_elevated_when_complaint_clustering(self):
        """≥3 complaints in 30d → ELEVATED."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(
            recent_complaints_count=4,
        ))
        self.assertEqual(tier, TIER_ELEVATED)

    def test_normal_when_complaints_below_threshold(self):
        """2 complaints (< 3 cluster threshold) → no escalation."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(
            recent_complaints_count=2,
        ))
        self.assertEqual(tier, TIER_NORMAL)

    # ──────────────────────────────────────────────────────────
    # Rule 6 — CLASS-2 in 14d → ELEVATED
    # ──────────────────────────────────────────────────────────

    def test_elevated_when_class_2_in_14d(self):
        """CLASS-2 violation in last 14d → ELEVATED."""
        self._require()
        tier, factors = _apply_tier_precedence(_make_inputs(
            recent_class_2_count=1,
            most_recent_class_2_days_ago=10,
        ))
        self.assertEqual(tier, TIER_ELEVATED)
        self.assertTrue(
            any("class_2" in f.get("factor", "").lower() for f in factors),
            msg=f"Factors should reference CLASS-2. Got: {factors!r}",
        )

    # ──────────────────────────────────────────────────────────
    # Rule 7 — HR 1.5-4.0 → ELEVATED
    # ──────────────────────────────────────────────────────────

    def test_elevated_when_hr_between_1_5_and_4(self):
        """HR_14d ∈ [1.5, 4.0) → ELEVATED."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(hr_14d=2.6))
        self.assertEqual(tier, TIER_ELEVATED)

    # ──────────────────────────────────────────────────────────
    # Rule 3 — CLASS-1 in 7d → IMMEDIATE
    # ──────────────────────────────────────────────────────────

    def test_immediate_when_class_1_in_7d(self):
        """CLASS-1 violation in last 7d → IMMEDIATE."""
        self._require()
        tier, factors = _apply_tier_precedence(_make_inputs(
            recent_class_1_count=1,
            most_recent_class_1_days_ago=3,
            most_recent_class_1_bucket="safety_hazards",
        ))
        self.assertEqual(tier, TIER_IMMEDIATE)
        self.assertTrue(
            any("class_1" in f.get("factor", "").lower() for f in factors),
        )

    # ──────────────────────────────────────────────────────────
    # Rule 4 — HR >= 4.0 → IMMEDIATE
    # ──────────────────────────────────────────────────────────

    def test_immediate_when_hr_above_4(self):
        """HR_14d ≥ 4.0 → IMMEDIATE."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(hr_14d=5.2))
        self.assertEqual(tier, TIER_IMMEDIATE)

    # ──────────────────────────────────────────────────────────
    # Rule 1 — SWO + demolition phase → IMMEDIATE
    # ──────────────────────────────────────────────────────────

    def test_immediate_when_swo_demolition_phase(self):
        """Active SWO + demolition phase (not in PHASE_TO_RATIO but a
        directive-locked override) → IMMEDIATE.

        Note: 'demolition' isn't one of the 6 PHASE_TO_RATIO enums
        (foundation, superstructure, interior, mep, finishes, closeout).
        Per Stage 2.A L1, the phase string 'demolition' is a recognized
        override case for tier escalation. Other "demo-like" states
        (full_demo, partial_demo project_class) may need separate
        handling but the directive explicitly says 'demolition phase'."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(
            swo_active=True, swo_days_open=5, phase="demolition",
        ))
        self.assertEqual(tier, TIER_IMMEDIATE)

    # ──────────────────────────────────────────────────────────
    # Rule 2 — SWO > 30d → IMMEDIATE
    # ──────────────────────────────────────────────────────────

    def test_immediate_when_swo_over_30d(self):
        """Active SWO open > 30 days (long-running) → IMMEDIATE
        regardless of phase. Per Stage 2.A L4."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(
            swo_active=True, swo_days_open=45, phase="interior",
        ))
        self.assertEqual(tier, TIER_IMMEDIATE)

    # ──────────────────────────────────────────────────────────
    # Phase override (L2)
    # ──────────────────────────────────────────────────────────

    def test_closeout_phase_demotes_hr_1_5_to_normal(self):
        """closeout phase + HR ∈ [1.5, 2.0) → demote to NORMAL.
        Punch-list inspection backlog inflates HR without reflecting
        active site risk."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(
            hr_14d=1.7, phase="closeout",
        ))
        self.assertEqual(
            tier, TIER_NORMAL,
            msg="closeout + HR in [1.5, 2.0) should demote ELEVATED → "
                "NORMAL per Stage 2.A L2",
        )

    def test_closeout_phase_does_not_demote_swo_or_class_1(self):
        """The closeout demotion ONLY applies to HR-driven escalation
        in the [1.5, 2.0) band. SWO and CLASS-1 escalations are NOT
        demoted (active site risk indicators that closeout context
        doesn't dampen)."""
        self._require()
        # closeout + SWO → still ELEVATED at minimum (rule 5)
        tier_swo, _ = _apply_tier_precedence(_make_inputs(
            swo_active=True, swo_days_open=10, phase="closeout",
        ))
        self.assertEqual(tier_swo, TIER_ELEVATED)
        # closeout + CLASS-1 → still IMMEDIATE (rule 3)
        tier_c1, _ = _apply_tier_precedence(_make_inputs(
            recent_class_1_count=1, most_recent_class_1_days_ago=2,
            phase="closeout",
        ))
        self.assertEqual(tier_c1, TIER_IMMEDIATE)

    # ──────────────────────────────────────────────────────────
    # Severity mapping (L7)
    # ──────────────────────────────────────────────────────────

    def test_hazardous_severity_treated_as_class_1(self):
        """L7 lock: 'Hazardous' severity counts toward CLASS-1
        thresholds. (The Socrata severity field has both 'CLASS - 1'
        AND 'Hazardous' values; both represent top-severity ECB
        violations.) Since _apply_tier_precedence takes
        recent_class_1_count as an already-aggregated input, this
        test pins the contract that 'Hazardous' rows must be folded
        into the class_1_count by the input-resolver — verified at
        the integration layer. Here we just verify that the precedence
        rule treats recent_class_1_count >= 1 as IMMEDIATE-eligible
        regardless of what severity strings the resolver folded."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(
            recent_class_1_count=1, most_recent_class_1_days_ago=3,
            most_recent_class_1_bucket="environmental",  # Hazardous → env
        ))
        self.assertEqual(tier, TIER_IMMEDIATE)

    def test_class_3_does_not_escalate(self):
        """CLASS-3 violations are informational only — must NOT escalate.
        The input contract: recent_class_3_count is NOT a field — only
        class_1 and class_2 counts are passed (L7 lock: CLASS-3 /
        Non-Hazardous / Unknown excluded from escalation). This test
        pins that all-zero counts + no other signals → NORMAL."""
        self._require()
        tier, _ = _apply_tier_precedence(_make_inputs(
            recent_class_1_count=0,
            recent_class_2_count=0,
        ))
        self.assertEqual(tier, TIER_NORMAL)

    # ──────────────────────────────────────────────────────────
    # primary_reason templates
    # ──────────────────────────────────────────────────────────

    def test_primary_reason_includes_days_since_for_swo(self):
        """SWO-driven primary_reason mentions days since SWO opened."""
        self._require()
        inputs = _make_inputs(
            swo_active=True, swo_days_open=3, phase="interior",
        )
        tier, factors = _apply_tier_precedence(inputs)
        reason = _format_primary_reason(tier, factors, inputs)
        self.assertIn("3", reason,
                      msg=f"SWO reason should reference days_open=3. "
                          f"Got: {reason!r}")
        self.assertIn("stop-work", reason.lower())

    def test_primary_reason_includes_hr_for_violation_rate(self):
        """HR-driven primary_reason mentions the multiple (1.5×, 2.6×,
        etc.) per the locked template."""
        self._require()
        inputs = _make_inputs(hr_14d=2.6)
        tier, factors = _apply_tier_precedence(inputs)
        reason = _format_primary_reason(tier, factors, inputs)
        # "2.6" should appear in some form (raw or formatted).
        self.assertIn(
            "2.6", reason,
            msg=f"HR-driven reason should reference 2.6× ratio. "
                f"Got: {reason!r}",
        )

    def test_primary_reason_format_with_borough_title_case(self):
        """borough rendered title-case in primary_reason (matches PR #42
        disclosure_text convention). BROOKLYN → Brooklyn."""
        self._require()
        inputs = _make_inputs(
            hr_14d=3.0, borough="BROOKLYN",
            work_type="General Construction",
        )
        tier, factors = _apply_tier_precedence(inputs)
        reason = _format_primary_reason(tier, factors, inputs)
        self.assertIn("Brooklyn", reason,
                      msg=f"Borough must be title-cased. Got: {reason!r}")
        self.assertNotIn("BROOKLYN", reason)


class TestDefconColorMapping(unittest.TestCase):
    """Phase 1 Week 11 PR-A — tier → color mapping."""

    def _require(self):
        if not HAS_DEFCON:
            self.fail("defcon module not implemented.")

    def test_tier_to_color_maps_all_three_tiers(self):
        self._require()
        self.assertEqual(TIER_TO_COLOR[TIER_NORMAL], "green")
        self.assertEqual(TIER_TO_COLOR[TIER_ELEVATED], "amber")
        self.assertEqual(TIER_TO_COLOR[TIER_IMMEDIATE], "red")


class TestDefconIntegration(unittest.TestCase):
    """Phase 1 Week 11 PR-A — end-to-end compute_defcon_status with
    minimal stub db."""

    def _require(self):
        if not HAS_DEFCON:
            self.fail("compute_defcon_status not implemented.")

    def test_null_prediction_cache_returns_normal_with_unknown_reason(self):
        """Project with no prediction_cache yet (cold-start day-zero) →
        NORMAL with a sensible default reason."""
        self._require()

        class _Db:  # minimal — just enough to satisfy attribute access
            projects = None
            daily_logs = None
            dob_logs = None
            socrata_ecb_violations_historical = None
            socrata_complaints_historical = None
            socrata_permits_historical = None
            prediction_models = None

        project = {
            "_id": "P_NOCACHE", "nyc_bin": "3000000",
            "borough": "BROOKLYN",
            # No prediction_cache at all
        }
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        result = _run(compute_defcon_status(_Db(), project, now=now))
        self.assertEqual(result["tier"], TIER_NORMAL)
        self.assertEqual(result["tier_color"], "green")
        self.assertIsInstance(result["primary_reason"], str)
        self.assertGreater(len(result["primary_reason"]), 0)

    def test_canonical_hazard_ratio_in_response_matches_internal_calc(self):
        """The response's cohort_context.project_rate_ratio MUST equal
        prob_violation_14d / anchored_baseline_prob_14d — the canonical
        hazard ratio derivation, exposed to downstream consumers."""
        self._require()

        class _Db:
            projects = None
            daily_logs = None
            dob_logs = None
            socrata_ecb_violations_historical = None
            socrata_complaints_historical = None
            socrata_permits_historical = None
            prediction_models = None

        project = {
            "_id": "P_HR", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {
                "prob_violation_14d":         0.10,
                "anchored_baseline_prob_14d": 0.04,
            },
        }
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        result = _run(compute_defcon_status(_Db(), project, now=now))
        # 0.10 / 0.04 = 2.5
        self.assertAlmostEqual(
            result["cohort_context"]["project_rate_ratio"], 2.5, places=4,
        )
        # HR=2.5 ∈ [1.5, 4.0) → ELEVATED
        self.assertEqual(result["tier"], TIER_ELEVATED)


if __name__ == "__main__":
    unittest.main()
