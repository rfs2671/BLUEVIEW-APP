"""Tests for step 6 commit 2.1 — RenewalEligibility v2 enrichment passthrough.

The dispatcher's `_v2_to_renewal_eligibility` adapter previously
downcast the v2 dict back to the legacy Pydantic shape, stripping
effective_expiry, renewal_strategy, limiting_factor, action. Frontend
had no fields to render against. 2.1 adds these as Optional fields on
RenewalEligibility and plumbs them through.

Three-mode coverage is mandatory because 2.1 deploys against
ELIGIBILITY_REWRITE_MODE=shadow in prod — the only commit in this
batch that ships before the cutover. A bug in the shadow path would
break the renewal-eligibility endpoint for users *before* the flip
even happens, which is the worst possible time.

- mode=off    : legacy result, all four v2 fields must be None
- mode=shadow : legacy result drives UI (same as off for response
                shape), shadow doc is written to db side-effect.
                v2 fields must be None.
- mode=live   : v2 drives UI, all four fields must be populated
                with real values from the v2 dict.

Plus: cross-tenant 404 protection on the read endpoints touched
(check-eligibility delegates auth to the route handler, but the
RenewalEligibility model itself has no tenant identifier — verifying
here that the response shape doesn't leak project_id/permit_id of
another company's permit when given crafted IDs).
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib import eligibility_dispatcher  # noqa: E402
from permit_renewal import RenewalEligibility  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── Fixtures ────────────────────────────────────────────────────────

def _v2_result_manual_1yr():
    """A representative v2 result for a permit hitting the 1-year
    issuance ceiling — exactly the Cat 3 escalation pattern from the
    shadow report. Strategy=MANUAL_1YR_CEILING, blocking_reasons set,
    full action payload."""
    return {
        "permit_id": "permit_a",
        "project_id": "proj_a",
        "filing_system": "DOB_NOW",
        "permit_class": "standard",
        "renewal_strategy": "MANUAL_1YR_CEILING",
        "calendar_expiry": "2027-01-01T00:00:00+00:00",
        "effective_expiry": "2026-12-15T00:00:00+00:00",
        "limiting_factor": {
            "label": "1-year issuance ceiling",
            "kind":  "annual_ceiling",
            "expires_in_days": 14,
        },
        "action": {
            "kind": "manual_renewal",
            "deadline_days": 14,
            "instructions": [
                "File a renewal on DOB NOW.",
                "Pay the $130 LL128 fee.",
            ],
        },
        "blocking_reasons": [
            "1-year issuance ceiling",
            "manual $130",
        ],
        "insurance_not_entered": False,
        "issuance_date": "2025-12-15T00:00:00+00:00",
        "permittee_license_number": "626198",
    }


def _legacy_result_eligible():
    """Legacy RenewalEligibility-shaped dict (what the legacy inner
    function actually returns)."""
    return RenewalEligibility(
        eligible=True,
        permit_id="permit_a",
        project_id="proj_a",
        job_number="B12345-I1",
        permit_type="NB",
        expiration_date="2027-01-01T00:00:00+00:00",
        days_until_expiry=365,
        renewal_path="dob_now",
        paa_required=False,
        gc_license=None,
        blocking_reasons=[],
        insurance_flags=[],
        insurance_not_entered=False,
    )


def _stub_db_with_docs():
    db = MagicMock()
    db.dob_logs.find_one = AsyncMock(return_value={
        "_id": "permit_a",
        "filing_system": "DOB_NOW",
        "permit_class": "standard",
        "issuance_date": datetime(2025, 12, 15, tzinfo=timezone.utc),
        "expiration_date": datetime(2027, 1, 1, tzinfo=timezone.utc),
    })
    db.projects.find_one = AsyncMock(return_value={
        "_id": "proj_a", "company_id": "co_a",
    })
    db.companies.find_one = AsyncMock(return_value={
        "_id": "co_a", "name": "Acme GC",
    })
    db.eligibility_shadow = MagicMock()
    db.eligibility_shadow.insert_one = AsyncMock()
    return db


# ── Pydantic model: optional fields default to None ────────────────

class TestRenewalEligibilityModel(unittest.TestCase):

    def test_new_fields_default_to_none(self):
        m = RenewalEligibility(permit_id="x", project_id="y")
        self.assertIsNone(m.effective_expiry)
        self.assertIsNone(m.renewal_strategy)
        self.assertIsNone(m.limiting_factor)
        self.assertIsNone(m.action)

    def test_new_fields_round_trip_via_dict(self):
        m = RenewalEligibility(
            permit_id="x", project_id="y",
            effective_expiry="2026-12-15T00:00:00+00:00",
            renewal_strategy="MANUAL_1YR_CEILING",
            limiting_factor={"label": "1-year issuance ceiling",
                             "kind": "annual_ceiling",
                             "expires_in_days": 14},
            action={"kind": "manual_renewal",
                    "deadline_days": 14,
                    "instructions": ["File on DOB NOW.", "Pay $130."]},
        )
        d = m.model_dump()
        self.assertEqual(d["renewal_strategy"], "MANUAL_1YR_CEILING")
        self.assertEqual(d["limiting_factor"]["expires_in_days"], 14)
        self.assertEqual(len(d["action"]["instructions"]), 2)


# ── Adapter: v2 dict → RenewalEligibility passthrough ──────────────

class TestV2Adapter(unittest.TestCase):

    def test_passes_through_v2_enrichment(self):
        out = eligibility_dispatcher._v2_to_renewal_eligibility(
            _v2_result_manual_1yr(),
            project_id="proj_a",
            permit_id="permit_a",
        )
        self.assertEqual(out.renewal_strategy, "MANUAL_1YR_CEILING")
        self.assertEqual(out.effective_expiry, "2026-12-15T00:00:00+00:00")
        self.assertEqual(out.limiting_factor["label"], "1-year issuance ceiling")
        self.assertEqual(out.action["kind"], "manual_renewal")
        self.assertEqual(out.blocking_reasons, ["1-year issuance ceiling", "manual $130"])
        # MR.1.6: issuance_date passthrough.
        self.assertEqual(out.issuance_date, "2025-12-15T00:00:00+00:00")
        # Sanity: the legacy-shape fields are still populated.
        self.assertFalse(out.eligible)  # blocking_reasons set
        self.assertEqual(out.expiration_date, "2027-01-01T00:00:00+00:00")
        self.assertEqual(out.days_until_expiry, 14)

    def test_handles_v2_dict_with_missing_enrichment_keys(self):
        """Defensive: an older v2 result (or a partial mock) shouldn't
        crash the adapter."""
        out = eligibility_dispatcher._v2_to_renewal_eligibility(
            {
                "renewal_strategy": "AUTO_EXTEND_DOB_NOW",
                "blocking_reasons": [],
                "insurance_not_entered": False,
                "calendar_expiry": "2027-01-01",
                "filing_system": "DOB_NOW",
            },
            project_id="proj_a", permit_id="permit_a",
        )
        # Strategy passes through; the missing keys come back as None.
        self.assertEqual(out.renewal_strategy, "AUTO_EXTEND_DOB_NOW")
        self.assertIsNone(out.effective_expiry)
        self.assertIsNone(out.limiting_factor)
        self.assertIsNone(out.action)
        # MR.1.6: missing issuance_date defaults to None.
        self.assertIsNone(out.issuance_date)
        self.assertTrue(out.eligible)


# ── Three-mode dispatcher behavior ─────────────────────────────────

class TestDispatcherModes(unittest.TestCase):
    """Covers the contract for each ELIGIBILITY_REWRITE_MODE value.

    Critical: shadow mode is the production state at 2.1 deploy time.
    Its assertion is the regression-protection net for the gap between
    2.1 ship and the dispatcher cutover."""

    def _call_dispatch(self):
        db = _stub_db_with_docs()
        # Patch the legacy and v2 inner functions so the test stays
        # focused on the dispatcher routing, not the eligibility logic.
        with patch("permit_renewal._check_renewal_eligibility_legacy_inner",
                   new=AsyncMock(return_value=_legacy_result_eligible())), \
             patch("lib.eligibility_v2.evaluate",
                   new=AsyncMock(return_value=_v2_result_manual_1yr())), \
             patch("lib.eligibility_shadow.run_one",
                   new=AsyncMock(return_value={
                       "old_crashed": False,
                       "new_crashed": False,
                       "permit_id": "permit_a",
                   })):
            result = _run(eligibility_dispatcher.check_renewal_eligibility(
                db, "permit_a", "proj_a", "Acme GC", company_id="co_a",
            ))
        return db, result

    def test_mode_off_returns_legacy_with_v2_fields_none(self):
        with patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "off"}):
            db, result = self._call_dispatch()
        self.assertTrue(result.eligible)
        self.assertIsNone(result.renewal_strategy)
        self.assertIsNone(result.effective_expiry)
        self.assertIsNone(result.limiting_factor)
        self.assertIsNone(result.action)
        # No shadow write in off mode.
        db.eligibility_shadow.insert_one.assert_not_awaited()

    def test_mode_shadow_returns_legacy_shape_v2_fields_none(self):
        """The 2.1-deploy-window critical case. Production is in
        shadow mode when this commit lands. The endpoint MUST return
        the legacy shape (v2 fields None) to keep existing frontend
        code working unchanged."""
        with patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "shadow"}):
            db, result = self._call_dispatch()
        self.assertTrue(result.eligible)
        self.assertEqual(result.expiration_date, "2027-01-01T00:00:00+00:00")
        # v2 fields must be None: shadow mode returns legacy result.
        # If a future refactor accidentally wired the v2 dict through
        # shadow mode's response path, this test catches it before the
        # 2.1 deploy breaks the production endpoint.
        self.assertIsNone(result.renewal_strategy)
        self.assertIsNone(result.effective_expiry)
        self.assertIsNone(result.limiting_factor)
        self.assertIsNone(result.action)
        # Shadow doc was written to side-channel collection.
        db.eligibility_shadow.insert_one.assert_awaited_once()

    def test_mode_live_returns_v2_enrichment(self):
        with patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
            db, result = self._call_dispatch()
        self.assertEqual(result.renewal_strategy, "MANUAL_1YR_CEILING")
        self.assertEqual(result.effective_expiry, "2026-12-15T00:00:00+00:00")
        self.assertEqual(result.limiting_factor["label"], "1-year issuance ceiling")
        self.assertEqual(result.limiting_factor["expires_in_days"], 14)
        self.assertEqual(result.action["kind"], "manual_renewal")
        self.assertEqual(len(result.action["instructions"]), 2)
        self.assertFalse(result.eligible)  # blocking_reasons set
        # No shadow write in live mode.
        db.eligibility_shadow.insert_one.assert_not_awaited()


# ── Tenant isolation ───────────────────────────────────────────────

class TestTenantIsolation(unittest.TestCase):
    """Per the A8 architectural rule: every read endpoint touched in
    this batch needs cross-tenant 404 coverage. The check-eligibility
    route handler in permit_renewal.py resolves company_id from the
    authenticated user and passes it explicitly into the dispatcher.

    The dispatcher's contract under tenant mismatch is to receive a
    company doc whose _id !== the permit's project's company_id; here
    we assert that even when this happens, no cross-tenant data
    leaks into the response shape — the response carries the IDs
    that were passed in, never sniffs around for additional company
    state. (The 404 itself is enforced upstream at the route layer.)"""

    def test_response_carries_only_passed_in_ids(self):
        """Sanity: the returned RenewalEligibility's project_id and
        permit_id match exactly what the caller passed. No leak from
        the company doc or v2 result's own ID fields."""
        # v2 result has project_id="proj_a" baked in; caller passes
        # "proj_TENANT_BOUNDARY". The adapter must use the caller's
        # value (the route layer's tenant-resolved ID), not the
        # v2 dict's internal one.
        out = eligibility_dispatcher._v2_to_renewal_eligibility(
            _v2_result_manual_1yr(),
            project_id="proj_TENANT_BOUNDARY",
            permit_id="permit_TENANT_BOUNDARY",
        )
        self.assertEqual(out.project_id, "proj_TENANT_BOUNDARY")
        self.assertEqual(out.permit_id, "permit_TENANT_BOUNDARY")


if __name__ == "__main__":
    unittest.main()
