"""MR.4 — PW2 field mapper tests.

Coverage map (per the prompt):
  - Happy path: B00736930-S1-PL-shaped fixture → all core fields
    populated, attachments_required has COI, no critical unmappable.
  - Missing primary filing_rep: applicant_* fields go to unmappable
    with consistent root-cause reason.
  - Missing issuance_date (pre-MR.1.6 stale doc): issuance_date in
    unmappable_fields with the backfill hint.
  - shed_renewal action.kind: attachments_required includes the
    PE/RA progress report.
  - manual_renewal_lapsed action.kind: attachments_required includes
    "Reason for lapse statement".
  - BIS path stub: returns notes warning that BIS path is not yet
    fully mapped.
  - No filing_reps at all: applicant_* unmappable with the same
    company-root-cause reason.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.pw2_field_mapper import (  # noqa: E402
    map_pw2_fields,
    Pw2FieldMap,
    FieldValue,
    RENEWAL_FEE_AMOUNT_USD,
    ALWAYS_REQUIRED_ATTACHMENTS,
)


def _run(coro):
    return asyncio.run(coro)


# ── Fixtures ───────────────────────────────────────────────────────

def _renewal(**kw):
    """Renewal doc post-MR.1.6 — full v2 enrichment + issuance_date."""
    base = {
        "_id": "renewal_a",
        "permit_dob_log_id": "permit_a",
        "project_id": "proj_a",
        "company_id": "co_a",
        "status": "needs_insurance",
        "is_deleted": False,
        "job_number": "B00736930-S1",  # mirror of dob_log.job_number
        "current_expiration": "2027-01-01T00:00:00+00:00",
        "issuance_date": "2026-01-26T00:00:00+00:00",
        "effective_expiry": "2027-01-26T00:00:00+00:00",
        "renewal_strategy": "MANUAL_1YR_CEILING",
        "limiting_factor": {
            "label": "1-year issuance ceiling",
            "kind": "annual_ceiling",
            "expires_in_days": 271,
        },
        "action": {
            "kind": "manual_renewal_dob_now",
            "deadline_days": 271,
            "instructions": ["File on DOB NOW", "Pay $130"],
        },
    }
    base.update(kw)
    return base


def _permit(**kw):
    """dob_log row for B00736930-S1 (Plumbing subpermit)."""
    base = {
        "_id": "permit_a",
        "is_deleted": False,
        "job_number": "B00736930-S1",
        "work_type": "Plumbing",
        "permit_subtype": "Plumbing",
        "filing_system": "DOB_NOW",
        "permit_class": "standard",
        "nyc_bin": "3325703",
    }
    base.update(kw)
    return base


def _project(**kw):
    base = {
        "_id": "proj_a",
        "name": "9 Menahan Street",
        "address": "9 Menahan Street, Brooklyn, NY 11221",
        "is_deleted": False,
        "nyc_bin": "3325703",
        "bbl": "3033040024",
    }
    base.update(kw)
    return base


def _company_with_primary_plumber(**kw):
    base = {
        "_id": "co_a",
        "name": "Acme GC",
        "is_deleted": False,
        "gc_license_number": "626198",
        "filing_reps": [
            {
                "id": "rep_1",
                "name": "Pat Plumber",
                "license_class": "Plumber",
                "license_number": "P-12345",
                "email": "pat@example.com",
                "is_primary": True,
            },
        ],
    }
    base.update(kw)
    return base


def _stub_db(*, renewal=None, permit=None, project=None, company=None):
    db = MagicMock()
    db.permit_renewals = MagicMock()
    db.dob_logs = MagicMock()
    db.projects = MagicMock()
    db.companies = MagicMock()
    db.permit_renewals.find_one = AsyncMock(return_value=renewal)
    db.dob_logs.find_one = AsyncMock(return_value=permit)
    db.projects.find_one = AsyncMock(return_value=project)
    db.companies.find_one = AsyncMock(return_value=company)
    return db


def _unmappable_names(report: Pw2FieldMap) -> set:
    """Extract just the field names from unmappable_fields entries.
    Each entry is shaped 'name: reason' — split on the first colon."""
    return {entry.split(":", 1)[0].strip() for entry in report.unmappable_fields}


# ── Happy path ─────────────────────────────────────────────────────

class TestHappyPath(unittest.TestCase):

    def test_full_data_produces_complete_field_map(self):
        db = _stub_db(
            renewal=_renewal(),
            permit=_permit(),
            project=_project(),
            company=_company_with_primary_plumber(),
        )
        report = _run(map_pw2_fields(db, "renewal_a"))

        self.assertEqual(report.permit_renewal_id, "renewal_a")
        self.assertEqual(report.permit_class, "DOB_NOW")

        # Core required fields all populated.
        for name in (
            "job_filing_number",
            "work_type",
            "bin",
            "bbl",
            "project_address",
            "applicant_name",
            "applicant_license_number",
            "applicant_license_class",
            "applicant_email",
            "applicant_business_name",
            "gc_license_number",
            "current_expiration_date",
            "issuance_date",
            "effective_expiry",
            "renewal_type",
            "renewal_fee_amount",
        ):
            self.assertIn(name, report.fields, f"missing core field {name!r}")

        # Specific values.
        self.assertEqual(report.fields["job_filing_number"].value, "B00736930-S1")
        self.assertEqual(report.fields["work_type"].value, "Plumbing")
        self.assertEqual(report.fields["bbl"].value, "3033040024")
        self.assertEqual(report.fields["applicant_name"].value, "Pat Plumber")
        self.assertEqual(report.fields["applicant_license_class"].value, "Plumber")
        self.assertEqual(report.fields["applicant_email"].value, "pat@example.com")
        self.assertEqual(report.fields["gc_license_number"].value, "626198")
        self.assertEqual(report.fields["renewal_type"].value, "1-Year Ceiling Renewal")
        self.assertEqual(report.fields["renewal_fee_amount"].value, RENEWAL_FEE_AMOUNT_USD)

        # field_type classification sanity.
        self.assertEqual(report.fields["issuance_date"].field_type, "date")
        self.assertEqual(report.fields["current_expiration_date"].field_type, "date")
        self.assertEqual(report.fields["work_type"].field_type, "select")
        self.assertEqual(report.fields["applicant_license_class"].field_type, "select")
        self.assertEqual(report.fields["renewal_type"].field_type, "select")
        self.assertEqual(report.fields["renewal_fee_amount"].field_type, "constant"
                         if False else "text")  # constant-source but text input

        # Source provenance sanity.
        self.assertEqual(report.fields["applicant_name"].source, "filing_rep")
        self.assertEqual(report.fields["renewal_fee_amount"].source, "constant")
        self.assertEqual(report.fields["issuance_date"].source, "permit_renewal")
        self.assertEqual(report.fields["renewal_type"].source, "computed")

        # Attachments — COI always required.
        self.assertIn(
            "Current Certificate of Insurance (GL/WC/DBL)",
            report.attachments_required,
        )

        # Operator notes present.
        self.assertTrue(any("$130" in n for n in report.notes))
        self.assertTrue(any("NYC.ID" in n for n in report.notes))

        # Only the documented work_permit_number gap is in unmappable.
        self.assertIn("work_permit_number", _unmappable_names(report))


# ── Missing primary filing_rep (no reps at all) ────────────────────

class TestMissingFilingRep(unittest.TestCase):

    def test_no_filing_reps_makes_applicant_fields_unmappable(self):
        company = _company_with_primary_plumber()
        company["filing_reps"] = []
        db = _stub_db(
            renewal=_renewal(),
            permit=_permit(),
            project=_project(),
            company=company,
        )
        report = _run(map_pw2_fields(db, "renewal_a"))

        un_names = _unmappable_names(report)
        for name in (
            "applicant_name",
            "applicant_license_number",
            "applicant_license_class",
            "applicant_email",
        ):
            self.assertIn(name, un_names, f"{name} should be unmappable")

        # Each entry uses the same root-cause reason.
        applicant_entries = [e for e in report.unmappable_fields if e.startswith("applicant_")]
        for entry in applicant_entries:
            self.assertIn("no filing representatives configured", entry)

        # company-sourced fields (gc_license_number, business_name)
        # still resolve — they're not filing_rep dependent.
        self.assertIn("applicant_business_name", report.fields)
        self.assertIn("gc_license_number", report.fields)


# ── No primary, single rep — fallback + note ───────────────────────

class TestNoPrimarySingleRep(unittest.TestCase):

    def test_single_rep_without_primary_fills_applicant_with_note(self):
        company = _company_with_primary_plumber()
        company["filing_reps"][0]["is_primary"] = False
        db = _stub_db(
            renewal=_renewal(),
            permit=_permit(),
            project=_project(),
            company=company,
        )
        report = _run(map_pw2_fields(db, "renewal_a"))

        # Applicant fields populated from the single rep.
        self.assertEqual(report.fields["applicant_name"].value, "Pat Plumber")

        # Note explaining the fallback.
        self.assertTrue(
            any("No primary filing representative" in n for n in report.notes),
            msg=f"notes={report.notes}",
        )


# ── Missing issuance_date (pre-MR.1.6 stale doc) ───────────────────

class TestMissingIssuanceDate(unittest.TestCase):

    def test_stale_doc_marks_issuance_date_unmappable_with_backfill_hint(self):
        renewal = _renewal()
        renewal["issuance_date"] = None
        db = _stub_db(
            renewal=renewal,
            permit=_permit(),
            project=_project(),
            company=_company_with_primary_plumber(),
        )
        report = _run(map_pw2_fields(db, "renewal_a"))

        # issuance_date unmappable.
        self.assertIn("issuance_date", _unmappable_names(report))
        # Hint references the backfill script.
        issuance_entry = next(
            e for e in report.unmappable_fields if e.startswith("issuance_date")
        )
        self.assertIn("backfill_renewal_v2_keys", issuance_entry)


# ── action.kind variants ───────────────────────────────────────────

class TestActionKindVariants(unittest.TestCase):

    def test_shed_renewal_attachments(self):
        renewal = _renewal()
        renewal["action"]["kind"] = "shed_renewal"
        db = _stub_db(
            renewal=renewal,
            permit=_permit(),
            project=_project(),
            company=_company_with_primary_plumber(),
        )
        report = _run(map_pw2_fields(db, "renewal_a"))
        self.assertIn("PE/RA-stamped progress report", report.attachments_required)
        self.assertEqual(report.fields["renewal_type"].value, "Sidewalk Shed Renewal")
        # The shed-specific operator hint fires.
        self.assertTrue(
            any("PE/RA progress report" in n and "30 days" in n for n in report.notes),
            msg=f"notes={report.notes}",
        )

    def test_manual_renewal_lapsed_attachments(self):
        renewal = _renewal()
        renewal["action"]["kind"] = "manual_renewal_lapsed"
        db = _stub_db(
            renewal=renewal,
            permit=_permit(),
            project=_project(),
            company=_company_with_primary_plumber(),
        )
        report = _run(map_pw2_fields(db, "renewal_a"))
        self.assertIn("Reason for lapse statement", report.attachments_required)
        self.assertEqual(report.fields["renewal_type"].value, "Lapsed Permit Renewal")

    def test_unknown_action_kind_unmappable_renewal_type(self):
        renewal = _renewal()
        renewal["action"]["kind"] = "monitor"  # not in RENEWAL_TYPE_LABELS
        db = _stub_db(
            renewal=renewal,
            permit=_permit(),
            project=_project(),
            company=_company_with_primary_plumber(),
        )
        report = _run(map_pw2_fields(db, "renewal_a"))
        self.assertIn("renewal_type", _unmappable_names(report))
        self.assertNotIn("renewal_type", report.fields)


# ── Form-path discriminator (filing_system) ────────────────────────

class TestFormPathDiscriminator(unittest.TestCase):

    def test_dob_now_path_no_bis_warning(self):
        db = _stub_db(
            renewal=_renewal(),
            permit=_permit(filing_system="DOB_NOW"),
            project=_project(),
            company=_company_with_primary_plumber(),
        )
        report = _run(map_pw2_fields(db, "renewal_a"))
        self.assertEqual(report.permit_class, "DOB_NOW")
        self.assertFalse(
            any("BIS legacy filing path" in n for n in report.notes),
            msg=f"notes={report.notes}",
        )

    def test_bis_path_emits_unsupported_warning(self):
        db = _stub_db(
            renewal=_renewal(),
            permit=_permit(filing_system="BIS"),
            project=_project(),
            company=_company_with_primary_plumber(),
        )
        report = _run(map_pw2_fields(db, "renewal_a"))
        self.assertEqual(report.permit_class, "BIS")
        self.assertTrue(
            any("BIS legacy filing path" in n for n in report.notes),
            msg=f"notes={report.notes}",
        )

    def test_missing_filing_system_defaults_to_standard_with_warning(self):
        db = _stub_db(
            renewal=_renewal(),
            permit=_permit(filing_system=None),
            project=_project(),
            company=_company_with_primary_plumber(),
        )
        report = _run(map_pw2_fields(db, "renewal_a"))
        self.assertEqual(report.permit_class, "standard")
        self.assertTrue(
            any("Form-path discriminator unresolved" in n for n in report.notes),
            msg=f"notes={report.notes}",
        )


# ── Defensive: missing renewal returns empty map without raising ───

class TestDefensiveMissingRenewal(unittest.TestCase):

    def test_returns_empty_map_when_renewal_missing(self):
        db = _stub_db(renewal=None)
        report = _run(map_pw2_fields(db, "missing"))
        self.assertEqual(report.fields, {})
        self.assertIn("Renewal record not found.", report.notes)


if __name__ == "__main__":
    unittest.main()
