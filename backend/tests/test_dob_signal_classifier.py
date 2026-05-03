"""MR.14 (commit 2b) — signal_kind classifier branch coverage.

Every branch in lib.dob_signal_classifier must have at least one
representative input. KNOWN_SIGNAL_KINDS coverage check ensures a
new branch added without a test breaks loudly.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ── Permit ────────────────────────────────────────────────────────


class TestClassifyPermit(unittest.TestCase):

    def test_issued(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "permit", "current_status": "ISSUED"}
        self.assertEqual(classify_signal_kind(log), "permit_issued")

    def test_active(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "permit", "current_status": "ACTIVE"}
        self.assertEqual(classify_signal_kind(log), "permit_issued")

    def test_expired(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "permit", "current_status": "EXPIRED"}
        self.assertEqual(classify_signal_kind(log), "permit_expired")

    def test_revoked(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "permit", "current_status": "REVOKED"}
        self.assertEqual(classify_signal_kind(log), "permit_revoked")

    def test_renewed(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "permit", "current_status": "RENEWED"}
        self.assertEqual(classify_signal_kind(log), "permit_renewed")

    def test_unknown_status_falls_back(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "permit", "current_status": "MYSTERY"}
        self.assertEqual(classify_signal_kind(log), "permit")


# ── Job filings ───────────────────────────────────────────────────


class TestClassifyJobStatus(unittest.TestCase):

    def test_approved(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "job_status", "current_status": "APPROVED"}
        self.assertEqual(classify_signal_kind(log), "filing_approved")

    def test_disapproved(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "job_status", "current_status": "DISAPPROVED"}
        self.assertEqual(classify_signal_kind(log), "filing_disapproved")

    def test_rejected_classifies_as_disapproved(self):
        """Some datasets use 'Rejected' instead of 'Disapproved'."""
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "job_status", "current_status": "REJECTED"}
        self.assertEqual(classify_signal_kind(log), "filing_disapproved")

    def test_withdrawn(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "job_status", "current_status": "WITHDRAWN"}
        self.assertEqual(classify_signal_kind(log), "filing_withdrawn")

    def test_pending(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "job_status", "current_status": "PENDING REVIEW"}
        self.assertEqual(classify_signal_kind(log), "filing_pending")


# ── Violation ─────────────────────────────────────────────────────


class TestClassifyViolation(unittest.TestCase):

    def test_dob_default(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "violation", "current_status": "ACTIVE"}
        self.assertEqual(classify_signal_kind(log), "violation_dob")

    def test_ecb_via_subtype(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {
            "record_type": "violation",
            "violation_subtype": "ECB",
            "current_status": "ACTIVE",
        }
        self.assertEqual(classify_signal_kind(log), "violation_ecb")

    def test_ecb_via_violation_number(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {
            "record_type": "violation",
            "ecb_violation_number": "1234567890",
            "current_status": "ACTIVE",
        }
        self.assertEqual(classify_signal_kind(log), "violation_ecb")

    def test_resolved_via_resolution_state(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {
            "record_type": "violation",
            "current_status": "ACTIVE",
            "resolution_state": "certified",
        }
        self.assertEqual(classify_signal_kind(log), "violation_resolved")

    def test_resolved_dismissed(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {
            "record_type": "violation",
            "resolution_state": "dismissed",
        }
        self.assertEqual(classify_signal_kind(log), "violation_resolved")


# ── SWO ───────────────────────────────────────────────────────────


class TestClassifySwo(unittest.TestCase):

    def test_full_default(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "swo", "current_status": "ACTIVE"}
        self.assertEqual(classify_signal_kind(log), "stop_work_full")

    def test_partial_via_subtype(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {
            "record_type": "swo",
            "violation_subtype": "SWO_PARTIAL",
        }
        self.assertEqual(classify_signal_kind(log), "stop_work_partial")

    def test_partial_via_description(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {
            "record_type": "swo",
            "description": "PARTIAL STOP WORK ORDER ISSUED FOR PLUMBING",
        }
        self.assertEqual(classify_signal_kind(log), "stop_work_partial")


# ── Complaint ─────────────────────────────────────────────────────


class TestClassifyComplaint(unittest.TestCase):

    def test_dob_complaint(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "complaint", "complaint_source": "dob"}
        self.assertEqual(classify_signal_kind(log), "complaint_dob")

    def test_311_complaint(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "complaint", "source": "311"}
        self.assertEqual(classify_signal_kind(log), "complaint_311")

    def test_default_to_dob(self):
        """A complaint without an explicit source defaults to DOB —
        matches the eabe-havv path which doesn't stamp a source."""
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "complaint"}
        self.assertEqual(classify_signal_kind(log), "complaint_dob")


# ── Inspection ────────────────────────────────────────────────────


class TestClassifyInspection(unittest.TestCase):

    def test_passed(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "inspection", "current_status": "PASSED"}
        self.assertEqual(classify_signal_kind(log), "inspection_passed")

    def test_failed(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "inspection", "current_status": "FAILED"}
        self.assertEqual(classify_signal_kind(log), "inspection_failed")

    def test_final_signoff_outranks_pass(self):
        """Final inspection passes are 'final_signoff', not just
        'inspection_passed' — the milestone matters more than the
        result for templating/notification routing."""
        from lib.dob_signal_classifier import classify_signal_kind
        log = {
            "record_type": "inspection",
            "inspection_type": "Plumbing — Final",
            "current_status": "PASSED",
        }
        self.assertEqual(classify_signal_kind(log), "final_signoff")

    def test_scheduled_via_future_date(self):
        from lib.dob_signal_classifier import classify_signal_kind
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        log = {
            "record_type": "inspection",
            "inspection_date": future,
            # No status / no result → scheduled
        }
        self.assertEqual(classify_signal_kind(log), "inspection_scheduled")

    def test_past_date_no_disposition_falls_back(self):
        from lib.dob_signal_classifier import classify_signal_kind
        past = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        log = {
            "record_type": "inspection",
            "inspection_date": past,
        }
        self.assertEqual(classify_signal_kind(log), "inspection")


# ── CofO ──────────────────────────────────────────────────────────


class TestClassifyCofo(unittest.TestCase):

    def test_temporary(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "cofo", "cofo_type": "TEMP"}
        self.assertEqual(classify_signal_kind(log), "cofo_temporary")

    def test_temporary_via_status_TCO(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "cofo", "current_status": "TCO ISSUED"}
        self.assertEqual(classify_signal_kind(log), "cofo_temporary")

    def test_final(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "cofo", "cofo_type": "FINAL"}
        self.assertEqual(classify_signal_kind(log), "cofo_final")

    def test_pending(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "cofo", "current_status": "PENDING"}
        self.assertEqual(classify_signal_kind(log), "cofo_pending")


# ── Compliance & license ──────────────────────────────────────────


class TestClassifyCompliance(unittest.TestCase):

    def test_facade_fisp(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "facade_fisp"}
        self.assertEqual(classify_signal_kind(log), "facade_fisp")

    def test_boiler(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "boiler"}
        self.assertEqual(classify_signal_kind(log), "boiler_inspection")

    def test_elevator(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "elevator"}
        self.assertEqual(classify_signal_kind(log), "elevator_inspection")

    def test_license_renewal_due(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "license_renewal"}
        self.assertEqual(classify_signal_kind(log), "license_renewal_due")


# ── Coverage / fallback ───────────────────────────────────────────


class TestClassifierFallbackAndCoverage(unittest.TestCase):

    def test_unknown_record_type_returns_record_type(self):
        from lib.dob_signal_classifier import classify_signal_kind
        log = {"record_type": "weird_new_thing"}
        self.assertEqual(classify_signal_kind(log), "weird_new_thing")

    def test_empty_log_returns_unknown(self):
        from lib.dob_signal_classifier import classify_signal_kind
        self.assertEqual(classify_signal_kind({}), "unknown")

    def test_known_signal_kinds_set_covers_classifier_outputs(self):
        """Every concrete output the classifier produces must be in
        KNOWN_SIGNAL_KINDS. Catches drift between classifier branches
        and the canonical kinds list."""
        from lib.dob_signal_classifier import (
            classify_signal_kind,
            KNOWN_SIGNAL_KINDS,
        )
        # Each concrete branch's expected output:
        produced = {
            classify_signal_kind({"record_type": "permit", "current_status": "ISSUED"}),
            classify_signal_kind({"record_type": "permit", "current_status": "EXPIRED"}),
            classify_signal_kind({"record_type": "permit", "current_status": "REVOKED"}),
            classify_signal_kind({"record_type": "permit", "current_status": "RENEWED"}),
            classify_signal_kind({"record_type": "permit"}),  # fallback
            classify_signal_kind({"record_type": "job_status", "current_status": "APPROVED"}),
            classify_signal_kind({"record_type": "job_status", "current_status": "DISAPPROVED"}),
            classify_signal_kind({"record_type": "job_status", "current_status": "WITHDRAWN"}),
            classify_signal_kind({"record_type": "job_status", "current_status": "PENDING"}),
            classify_signal_kind({"record_type": "violation"}),
            classify_signal_kind({"record_type": "violation", "violation_subtype": "ECB"}),
            classify_signal_kind({"record_type": "violation", "resolution_state": "dismissed"}),
            classify_signal_kind({"record_type": "swo"}),
            classify_signal_kind({"record_type": "swo", "violation_subtype": "SWO_PARTIAL"}),
            classify_signal_kind({"record_type": "complaint", "source": "311"}),
            classify_signal_kind({"record_type": "complaint"}),
            classify_signal_kind({"record_type": "inspection", "current_status": "PASSED"}),
            classify_signal_kind({"record_type": "inspection", "current_status": "FAILED"}),
            classify_signal_kind({"record_type": "inspection", "inspection_type": "Final"}),
            classify_signal_kind({"record_type": "cofo", "cofo_type": "TEMP"}),
            classify_signal_kind({"record_type": "cofo", "cofo_type": "FINAL"}),
            classify_signal_kind({"record_type": "cofo", "current_status": "PENDING"}),
            classify_signal_kind({"record_type": "facade_fisp"}),
            classify_signal_kind({"record_type": "boiler"}),
            classify_signal_kind({"record_type": "elevator"}),
            classify_signal_kind({"record_type": "license_renewal"}),
        }
        # Every produced value must be in KNOWN_SIGNAL_KINDS.
        missing = produced - set(KNOWN_SIGNAL_KINDS)
        self.assertEqual(
            missing, set(),
            f"Classifier produces signal_kinds not in KNOWN_SIGNAL_KINDS: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
