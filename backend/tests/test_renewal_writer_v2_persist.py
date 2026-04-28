"""Step 6.2.3 — assert v2 enrichment fields are persisted on the
renewal doc, sourced verbatim from the dispatcher response.

Two write paths to cover:
  1. `nightly_renewal_scan` Job 1 insert
  2. (Spot-checked separately — covered by the dispatcher passthrough
     test in 6.2.1.) The `prepare_renewal` API endpoint follows the
     same pattern; testing the nightly scan path proves the writer
     contract.

Two scenarios per path:
  A. Dispatcher returns v2-enriched RenewalEligibility (live mode):
     persisted doc carries all four fields with real values.
  B. Dispatcher returns v1-shape RenewalEligibility (shadow/off mode,
     all four v2 fields None): persisted doc carries None — explicit
     shape stability so older records and 6.2.2's fallback path keep
     working unchanged.

The test stubs `check_renewal_eligibility` so we exercise the writer
path's handling of the dispatcher response, not the dispatcher logic
itself (already covered in test_dispatcher_v2_passthrough.py).
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import permit_renewal  # noqa: E402
from permit_renewal import RenewalEligibility, GCLicenseInfo  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── Fixtures ───────────────────────────────────────────────────────

def _eligibility_v2_enriched():
    """RenewalEligibility as the live-mode dispatcher would return,
    with all four v2 enrichment fields populated."""
    return RenewalEligibility(
        eligible=False,
        permit_id="permit_a",
        project_id="proj_a",
        job_number="B12345-I1",
        permit_type="NB",
        expiration_date="2027-01-01T00:00:00+00:00",
        days_until_expiry=14,
        renewal_path="dob_now",
        paa_required=False,
        gc_license=GCLicenseInfo(license_number="626198"),
        blocking_reasons=["1-year issuance ceiling", "manual $130"],
        insurance_flags=[],
        insurance_not_entered=False,
        renewal_strategy="MANUAL_1YR_CEILING",
        effective_expiry="2026-12-15T00:00:00+00:00",
        limiting_factor={
            "label": "1-year issuance ceiling",
            "kind":  "annual_ceiling",
            "expires_in_days": 14,
        },
        action={
            "kind": "manual_renewal",
            "deadline_days": 14,
            "instructions": [
                "File a renewal on DOB NOW.",
                "Pay the $130 LL128 fee.",
            ],
        },
    )


def _eligibility_v1_shape():
    """RenewalEligibility as the legacy/shadow dispatcher returns —
    v2 enrichment fields are None (the deploy-window state between
    6.2.1 ship and the dispatcher flip)."""
    return RenewalEligibility(
        eligible=True,
        permit_id="permit_legacy",
        project_id="proj_legacy",
        job_number="B99999-I1",
        permit_type="NB",
        expiration_date="2027-06-01T00:00:00+00:00",
        days_until_expiry=20,
        renewal_path="dob_now",
        paa_required=False,
        gc_license=GCLicenseInfo(license_number="626198"),
        blocking_reasons=[],
        insurance_flags=[],
        insurance_not_entered=False,
        # renewal_strategy / effective_expiry / limiting_factor /
        # action all default to None.
    )


def _make_db(*, permit_id: str, project_id: str, company_id: str):
    """Stub Mongo with one expiring permit, one project, one company.
    Captures the inserted renewal_doc for assertions."""
    inserted = {}

    db = MagicMock()
    db.dob_logs = MagicMock()
    permits_cursor = MagicMock()
    # Permit expiring in 14 days (within the ≤30-day window so Job 1
    # creates a renewal record).
    expiry = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    permits_cursor.to_list = AsyncMock(return_value=[{
        "_id": permit_id,
        "record_type": "permit",
        "expiration_date": expiry,
        "is_deleted": False,
        "project_id": project_id,
    }])
    db.dob_logs.find = MagicMock(return_value=permits_cursor)

    db.permit_renewals = MagicMock()
    # No existing renewal record — the writer takes the insert branch.
    db.permit_renewals.find_one = AsyncMock(return_value=None)

    async def _capture_insert(doc):
        inserted["doc"] = doc
        result = MagicMock()
        result.inserted_id = "renewal_inserted"
        return result
    db.permit_renewals.insert_one = AsyncMock(side_effect=_capture_insert)

    # Job 2 awaiting renewals — empty.
    awaiting_cursor = MagicMock()
    awaiting_cursor.to_list = AsyncMock(return_value=[])
    db.permit_renewals.find = MagicMock(return_value=awaiting_cursor)

    db.projects = MagicMock()
    db.projects.find_one = AsyncMock(return_value={
        "_id": project_id,
        "name": "9 Menahan",
        "address": "9 Menahan Street, Brooklyn, NY 11221",
        "company_id": company_id,
    })

    db.companies = MagicMock()
    db.companies.find_one = AsyncMock(return_value={
        "_id": company_id,
        "name": "Acme GC",
    })

    # Job 3 health-check — return a recent last_run so the cooldown
    # branch fires (no actual health check executes during this test).
    db.system_config = MagicMock()
    db.system_config.find_one = AsyncMock(return_value={
        "key": "dob_now_health_check",
        "last_run": datetime.now(timezone.utc) - timedelta(minutes=5),
    })

    return db, inserted


# ── Scenario A: dispatcher returns v2-enriched eligibility ──────────

class TestNightlyScanWritesV2Fields(unittest.TestCase):

    def test_persisted_doc_carries_v2_enrichment(self):
        db, inserted = _make_db(
            permit_id="permit_a", project_id="proj_a", company_id="co_a",
        )

        # Patch _to_oid to avoid ObjectId construction on string IDs.
        with patch("permit_renewal._to_oid", side_effect=lambda x: x), \
             patch("permit_renewal.check_renewal_eligibility",
                   new=AsyncMock(return_value=_eligibility_v2_enriched())):
            _run(permit_renewal.nightly_renewal_scan(db))

        doc = inserted.get("doc")
        self.assertIsNotNone(doc, "writer never called insert_one")

        # The four v2 fields must be present and equal to the
        # dispatcher response — no recomputation in the writer.
        self.assertEqual(doc["renewal_strategy"], "MANUAL_1YR_CEILING")
        self.assertEqual(doc["effective_expiry"], "2026-12-15T00:00:00+00:00")
        self.assertEqual(doc["limiting_factor"]["label"], "1-year issuance ceiling")
        self.assertEqual(doc["limiting_factor"]["expires_in_days"], 14)
        self.assertEqual(doc["action"]["kind"], "manual_renewal")
        self.assertEqual(len(doc["action"]["instructions"]), 2)

        # Sanity: legacy fields still populated (we didn't accidentally
        # break the v1 shape).
        self.assertEqual(doc["job_number"], "B12345-I1")
        self.assertEqual(doc["blocking_reasons"],
                         ["1-year issuance ceiling", "manual $130"])

    def test_persisted_doc_is_none_when_dispatcher_returns_v1_shape(self):
        """Shadow / off-mode safety: writer must not crash or fabricate
        values when v2 fields are None on the dispatcher response.
        Older records and 6.2.2's fallback rendering rely on this
        graceful-absence behavior."""
        db, inserted = _make_db(
            permit_id="permit_legacy", project_id="proj_legacy",
            company_id="co_legacy",
        )

        with patch("permit_renewal._to_oid", side_effect=lambda x: x), \
             patch("permit_renewal.check_renewal_eligibility",
                   new=AsyncMock(return_value=_eligibility_v1_shape())):
            _run(permit_renewal.nightly_renewal_scan(db))

        doc = inserted.get("doc")
        self.assertIsNotNone(doc, "writer never called insert_one")

        # Each v2 field must be present in the doc shape (key exists
        # so future reads don't KeyError) but None as the value.
        for k in ("renewal_strategy", "effective_expiry",
                  "limiting_factor", "action"):
            self.assertIn(k, doc, f"writer dropped key {k!r}")
            self.assertIsNone(doc[k], f"v1 shape leaked non-None for {k!r}")

        # Sanity: legacy fields still populated.
        self.assertEqual(doc["job_number"], "B99999-I1")
        self.assertEqual(doc["blocking_reasons"], [])


if __name__ == "__main__":
    unittest.main()
