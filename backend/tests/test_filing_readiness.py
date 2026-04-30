"""MR.3 — Filing readiness checker tests.

Coverage map (per the prompt):
  - Happy path: all 10 checks pass
  - Each check failure path: 9 distinct cases, one per non-short-
    circuit check, asserting the blockers list contains the right
    detail
  - Warnings paths: license_class GC for plumbing → warn (not fail);
    no-primary single-rep → warn
  - License class mismatch: plumbing + Electrician → fail
  - Multiple primaries: data corrupt fixture → fail with integrity msg
  - v2_keys_present check: stale doc without renewal_strategy → fail
  - Short-circuit: missing/deleted/terminal-status renewal returns a
    one-check report
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

from lib.filing_readiness import (  # noqa: E402
    check_filing_readiness,
    FilingReadinessReport,
    ReadinessCheck,
)


def _run(coro):
    return asyncio.run(coro)


# ── Fixtures ───────────────────────────────────────────────────────

def _full_renewal():
    """Renewal doc with everything populated — happy-path baseline."""
    return {
        "_id": "renewal_a",
        "permit_dob_log_id": "permit_a",
        "project_id": "proj_a",
        "company_id": "co_a",
        "status": "needs_insurance",
        "is_deleted": False,
        "renewal_strategy": "MANUAL_1YR_CEILING",
        "effective_expiry": "2027-01-26T00:00:00+00:00",
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
        "issuance_date": "2026-01-26T00:00:00+00:00",
    }


def _full_permit():
    return {
        "_id": "permit_a",
        "is_deleted": False,
        "work_type": "Plumbing",
        "job_number": "B00736930-S1",
    }


def _full_project():
    return {"_id": "proj_a", "name": "9 Menahan Street", "is_deleted": False}


def _full_company_with_primary_plumber():
    return {
        "_id": "co_a",
        "name": "Acme GC",
        "is_deleted": False,
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


def _stub_db(*, renewal=None, permit=None, project=None, company=None):
    """Build a MagicMock db that returns the given fixtures from
    find_one. Any not-passed fixture returns None (= reference
    missing)."""
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


def _check_by_name(report: FilingReadinessReport, name: str) -> ReadinessCheck:
    for c in report.checks:
        if c.name == name:
            return c
    raise AssertionError(
        f"Check {name!r} not found in report. Got: {[c.name for c in report.checks]}"
    )


# ── Happy path ─────────────────────────────────────────────────────

class TestHappyPath(unittest.TestCase):

    def test_all_checks_pass_for_full_data(self):
        db = _stub_db(
            renewal=_full_renewal(),
            permit=_full_permit(),
            project=_full_project(),
            company=_full_company_with_primary_plumber(),
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        self.assertTrue(report.ready, msg=f"blockers={report.blockers}")
        self.assertEqual(report.blockers, [])
        # 10 checks total. All pass for the happy path.
        self.assertEqual(len(report.checks), 10)
        for c in report.checks:
            self.assertEqual(
                c.status, "pass",
                msg=f"{c.name}: {c.detail} (status={c.status})",
            )


# ── Short-circuit (check 1) ────────────────────────────────────────

class TestPermitRenewalExistsShortCircuit(unittest.TestCase):

    def test_renewal_not_found_returns_one_check_report(self):
        db = _stub_db(renewal=None)
        report = _run(check_filing_readiness(db, "missing"))
        self.assertFalse(report.ready)
        self.assertEqual(len(report.checks), 1)
        self.assertEqual(report.checks[0].name, "permit_renewal_exists")
        self.assertEqual(report.checks[0].status, "fail")

    def test_soft_deleted_renewal_short_circuits(self):
        renewal = _full_renewal()
        renewal["is_deleted"] = True
        db = _stub_db(renewal=renewal)
        report = _run(check_filing_readiness(db, "renewal_a"))
        self.assertFalse(report.ready)
        self.assertEqual(len(report.checks), 1)
        self.assertIn("soft-deleted", report.checks[0].detail)

    def test_terminal_status_short_circuits(self):
        for status in ("completed", "failed"):
            with self.subTest(status=status):
                renewal = _full_renewal()
                renewal["status"] = status
                db = _stub_db(renewal=renewal)
                report = _run(check_filing_readiness(db, "renewal_a"))
                self.assertFalse(report.ready)
                self.assertEqual(len(report.checks), 1)
                self.assertIn("terminal status", report.checks[0].detail)


# ── Each non-short-circuit check failure ───────────────────────────

class TestIndividualCheckFailures(unittest.TestCase):

    def test_permit_dob_log_missing(self):
        db = _stub_db(
            renewal=_full_renewal(),
            permit=None,
            project=_full_project(),
            company=_full_company_with_primary_plumber(),
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        self.assertFalse(report.ready)
        c = _check_by_name(report, "permit_dob_log_exists")
        self.assertEqual(c.status, "fail")
        self.assertIn("orphaned", c.detail.lower())

    def test_permit_dob_log_soft_deleted(self):
        permit = _full_permit()
        permit["is_deleted"] = True
        db = _stub_db(
            renewal=_full_renewal(),
            permit=permit,
            project=_full_project(),
            company=_full_company_with_primary_plumber(),
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "permit_dob_log_exists")
        self.assertEqual(c.status, "fail")

    def test_project_missing(self):
        db = _stub_db(
            renewal=_full_renewal(),
            permit=_full_permit(),
            project=None,
            company=_full_company_with_primary_plumber(),
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "project_exists")
        self.assertEqual(c.status, "fail")

    def test_company_missing(self):
        db = _stub_db(
            renewal=_full_renewal(),
            permit=_full_permit(),
            project=_full_project(),
            company=None,
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "company_exists")
        self.assertEqual(c.status, "fail")

    def test_filing_reps_empty(self):
        company = _full_company_with_primary_plumber()
        company["filing_reps"] = []
        db = _stub_db(
            renewal=_full_renewal(),
            permit=_full_permit(),
            project=_full_project(),
            company=company,
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "filing_reps_present")
        self.assertEqual(c.status, "fail")
        self.assertIn("owner portal", c.detail)

    def test_multiple_primaries_data_integrity_failure(self):
        company = {
            "_id": "co_a", "name": "Acme", "is_deleted": False,
            "filing_reps": [
                {"id": "r1", "name": "A", "license_class": "Plumber",
                 "license_number": "1", "email": "a@example.com", "is_primary": True},
                {"id": "r2", "name": "B", "license_class": "GC",
                 "license_number": "2", "email": "b@example.com", "is_primary": True},
            ],
        }
        db = _stub_db(
            renewal=_full_renewal(),
            permit=_full_permit(),
            project=_full_project(),
            company=company,
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "primary_filing_rep_present")
        self.assertEqual(c.status, "fail")
        self.assertIn("Data integrity", c.detail)
        self.assertIn("2", c.detail)

    def test_license_class_mismatch_plumbing_with_electrician(self):
        company = _full_company_with_primary_plumber()
        company["filing_reps"][0]["license_class"] = "Electrician"
        db = _stub_db(
            renewal=_full_renewal(),
            permit=_full_permit(),  # work_type = "Plumbing"
            project=_full_project(),
            company=company,
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "license_class_appropriate")
        self.assertEqual(c.status, "fail")
        self.assertIn("Electrician", c.detail)
        self.assertIn("Plumbing", c.detail)

    def test_v2_keys_missing_renewal_strategy(self):
        renewal = _full_renewal()
        renewal["renewal_strategy"] = None
        db = _stub_db(
            renewal=renewal,
            permit=_full_permit(),
            project=_full_project(),
            company=_full_company_with_primary_plumber(),
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "v2_keys_present")
        self.assertEqual(c.status, "fail")
        self.assertIn("renewal_strategy", c.detail)
        self.assertIn("backfill", c.detail.lower())

    def test_issuance_date_missing(self):
        renewal = _full_renewal()
        renewal["issuance_date"] = None
        db = _stub_db(
            renewal=renewal,
            permit=_full_permit(),
            project=_full_project(),
            company=_full_company_with_primary_plumber(),
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "issuance_date_present")
        self.assertEqual(c.status, "fail")
        self.assertIn("backfill", c.detail.lower())


# ── Warning paths (non-blocking) ───────────────────────────────────

class TestWarningPaths(unittest.TestCase):

    def test_gc_for_plumbing_warns_not_fails(self):
        """GC license can pull plumbing in some cases — surface as
        warn so the operator can verify scope, but don't block the
        filing."""
        company = _full_company_with_primary_plumber()
        company["filing_reps"][0]["license_class"] = "GC"
        db = _stub_db(
            renewal=_full_renewal(),
            permit=_full_permit(),  # work_type = "Plumbing"
            project=_full_project(),
            company=company,
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "license_class_appropriate")
        self.assertEqual(c.status, "warn")
        self.assertIn("GC", c.detail)
        # Other checks pass → ready=True even with this warn.
        self.assertTrue(report.ready, msg=f"blockers={report.blockers}")
        self.assertEqual(len(report.warnings), 1)

    def test_no_primary_single_rep_warns_and_proceeds(self):
        company = _full_company_with_primary_plumber()
        company["filing_reps"][0]["is_primary"] = False
        db = _stub_db(
            renewal=_full_renewal(),
            permit=_full_permit(),
            project=_full_project(),
            company=company,
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "primary_filing_rep_present")
        self.assertEqual(c.status, "warn")
        self.assertIn("default to the first", c.detail)
        # license_class still runs against the first rep.
        license_check = _check_by_name(report, "license_class_appropriate")
        self.assertEqual(license_check.status, "pass")
        # Ready: only warns, no blockers.
        self.assertTrue(report.ready, msg=f"blockers={report.blockers}")

    def test_unmapped_work_type_warns(self):
        permit = _full_permit()
        permit["work_type"] = "Curtain Wall"
        db = _stub_db(
            renewal=_full_renewal(),
            permit=permit,
            project=_full_project(),
            company=_full_company_with_primary_plumber(),
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "license_class_appropriate")
        self.assertEqual(c.status, "warn")
        self.assertIn("No license-class mapping", c.detail)

    def test_unactionable_action_kind_warns(self):
        renewal = _full_renewal()
        renewal["action"] = {
            "kind": "manual_renewal_lapsed",
            "instructions": ["..."],
        }
        db = _stub_db(
            renewal=renewal,
            permit=_full_permit(),
            project=_full_project(),
            company=_full_company_with_primary_plumber(),
        )
        report = _run(check_filing_readiness(db, "renewal_a"))
        c = _check_by_name(report, "action_kind_actionable")
        self.assertEqual(c.status, "warn")
        self.assertIn("manual_renewal_lapsed", c.detail)


if __name__ == "__main__":
    unittest.main()
