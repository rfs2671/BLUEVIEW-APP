"""Regression tests for the _build_action conditional ordering bug.

Production observation 2026-04-29 — permit B00736930-S1 (strategy=
MANUAL_1YR_CEILING, insurance_not_entered=true) was emitting
action.kind="enter_insurance" instead of "manual_renewal_dob_now".
The 1-year-since-issuance ceiling is a regulatory trigger that fires
"regardless of insurance state" (verbatim, blocking_reasons text in
the live response), so the insurance CTA is the wrong next-step.

Root cause was conditional ordering in
backend/lib/eligibility_v2.py:_build_action. The
`insurance_not_entered` gate was at position 2, BEFORE the MANUAL_*
strategy dispatches at positions 5/6/7. Any permit hitting a manual
track without insurance dates in LeveLog short-circuited at the gate.

Fix: reorder so insurance-independent strategies dispatch first
(AWAITING_EXTENSION + the three MANUAL_* tracks), then the
insurance_not_entered gate, then AUTO_EXTEND_* (which is genuinely
insurance-dependent because the GC needs to have submitted a fresh
COI to DOB Licensing for those tracks to work).

These tests cover:
  - The exact prod bug case (MANUAL_1YR_CEILING + insurance_not_entered)
  - The symmetric cases (MANUAL_90D_SHED + insurance_not_entered,
    MANUAL_LAPSED + insurance_not_entered)
  - The negative path: insurance_not_entered=true with an AUTO_EXTEND_*
    strategy still routes to enter_insurance (gate still active for
    insurance-dependent tracks)
  - AWAITING_EXTENSION still wins over insurance_not_entered (was
    already correctly first; pinned here so future refactors don't
    regress it)
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib import eligibility_v2  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _permit():
    """Minimal permit dict with enough fields for fee lookup."""
    return {
        "_id": "permit_test",
        "filing_system": "DOB_NOW",
        "permit_class": "standard",
        "issuance_date": datetime(2025, 4, 28, tzinfo=timezone.utc),
        "expiration_date": datetime(2026, 4, 28, tzinfo=timezone.utc),
        "job_number": "B00736930-S1",
        "work_type": "GC",
    }


def _today():
    return datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def _effective_expiry_past():
    """An effective_expiry that's in the past — what MANUAL_LAPSED
    typically sees and what MANUAL_1YR_CEILING produces when the
    permit has crossed the 1-year mark."""
    return datetime(2026, 4, 28, tzinfo=timezone.utc)


# Stub fee_schedule.get_fee to a known value so the test doesn't need
# a real fee_schedule collection. $130 is the prod value for the
# 1-year-ceiling renewal.
_FAKE_FEE = {"fee_cents": 13000, "split": None}


# ── The prod bug case ──────────────────────────────────────────────

class TestManual1YrCeilingWithoutInsurance(unittest.TestCase):
    """The exact prod bug: MANUAL_1YR_CEILING + insurance_not_entered=true.
    Pre-fix: emits kind="enter_insurance". Post-fix: emits
    kind="manual_renewal_dob_now"."""

    def test_emits_manual_renewal_dob_now_not_enter_insurance(self):
        with patch("lib.eligibility_v2.get_fee",
                   new=AsyncMock(return_value=_FAKE_FEE)):
            result = _run(eligibility_v2._build_action(
                db=MagicMock(),
                permit=_permit(),
                strategy="MANUAL_1YR_CEILING",
                effective_expiry=_effective_expiry_past(),
                today=_today(),
                insurance_not_entered=True,
            ))

        self.assertEqual(result["kind"], "manual_renewal_dob_now")
        self.assertNotEqual(result["kind"], "enter_insurance")
        # Fee was looked up correctly.
        self.assertEqual(result["fee_cents"], 13000)
        # Instructions reference the 1-year ceiling regulatory trigger,
        # not insurance.
        self.assertTrue(any("1-year ceiling" in s.lower() or
                            "ceiling" in s.lower()
                            for s in result["instructions"]))


# ── Symmetric cases — same fix benefits MANUAL_90D_SHED + MANUAL_LAPSED ──

class TestOtherManualStrategiesWithoutInsurance(unittest.TestCase):

    def test_manual_90d_shed_emits_shed_renewal(self):
        with patch("lib.eligibility_v2.get_fee",
                   new=AsyncMock(return_value=_FAKE_FEE)):
            result = _run(eligibility_v2._build_action(
                db=MagicMock(),
                permit={**_permit(), "permit_class": "sidewalk_shed"},
                strategy="MANUAL_90D_SHED",
                effective_expiry=_effective_expiry_past(),
                today=_today(),
                insurance_not_entered=True,
            ))
        self.assertEqual(result["kind"], "shed_renewal")
        self.assertNotEqual(result["kind"], "enter_insurance")

    def test_manual_lapsed_emits_manual_renewal_lapsed(self):
        with patch("lib.eligibility_v2.get_fee",
                   new=AsyncMock(return_value=_FAKE_FEE)):
            result = _run(eligibility_v2._build_action(
                db=MagicMock(),
                permit=_permit(),
                strategy="MANUAL_LAPSED",
                effective_expiry=_effective_expiry_past(),
                today=_today(),
                insurance_not_entered=True,
            ))
        self.assertEqual(result["kind"], "manual_renewal_lapsed")
        self.assertNotEqual(result["kind"], "enter_insurance")


# ── Insurance gate still works for insurance-dependent strategies ──

class TestInsuranceGateForAutoExtend(unittest.TestCase):
    """For AUTO_EXTEND_* the gate must still fire — those tracks rely
    on the GC having submitted a fresh COI to DOB Licensing, which we
    can't verify without insurance dates on file."""

    def test_auto_extend_dob_now_still_routes_to_enter_insurance(self):
        result = _run(eligibility_v2._build_action(
            db=MagicMock(),
            permit=_permit(),
            strategy="AUTO_EXTEND_DOB_NOW",
            effective_expiry=datetime(2026, 5, 28, tzinfo=timezone.utc),
            today=_today(),
            insurance_not_entered=True,
        ))
        self.assertEqual(result["kind"], "enter_insurance")

    def test_auto_extend_bis_31d_still_routes_to_enter_insurance(self):
        result = _run(eligibility_v2._build_action(
            db=MagicMock(),
            permit={**_permit(), "filing_system": "BIS"},
            strategy="AUTO_EXTEND_BIS_31D",
            effective_expiry=datetime(2026, 5, 28, tzinfo=timezone.utc),
            today=_today(),
            insurance_not_entered=True,
        ))
        self.assertEqual(result["kind"], "enter_insurance")


# ── AWAITING_EXTENSION (already correctly first) ────────────────────

class TestAwaitingExtensionWinsOverInsuranceGate(unittest.TestCase):
    """Was already correctly ordered first pre-fix. Pinning here so
    future refactors don't regress."""

    def test_awaiting_extension_returns_kind_regardless_of_insurance(self):
        result = _run(eligibility_v2._build_action(
            db=MagicMock(),
            permit=_permit(),
            strategy="AWAITING_EXTENSION",
            effective_expiry=datetime(2026, 5, 28, tzinfo=timezone.utc),
            today=_today(),
            insurance_not_entered=True,
        ))
        self.assertEqual(result["kind"], "awaiting_extension")


# ── Negative control — manual strategies WITH insurance entered ─────

class TestManualStrategiesAreUnaffectedWhenInsuranceEntered(unittest.TestCase):
    """When insurance_not_entered=False, the manual tracks should
    still emit their respective kinds. This pins that the reorder
    didn't accidentally change behavior on the happy path."""

    def test_manual_1yr_ceiling_with_insurance(self):
        with patch("lib.eligibility_v2.get_fee",
                   new=AsyncMock(return_value=_FAKE_FEE)):
            result = _run(eligibility_v2._build_action(
                db=MagicMock(),
                permit=_permit(),
                strategy="MANUAL_1YR_CEILING",
                effective_expiry=_effective_expiry_past(),
                today=_today(),
                insurance_not_entered=False,
            ))
        self.assertEqual(result["kind"], "manual_renewal_dob_now")


if __name__ == "__main__":
    unittest.main()
