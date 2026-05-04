"""MR.7-followup — CRITICAL_PW2_FIELDS partition + enqueue gate.

Why this file exists
────────────────────
Operator hit a verification blocker on MR.7: the /file enqueue
endpoint rejected with mapper_unmappable_fields when MR.4's mapper
produced ANY unmappable_fields. work_permit_number is unmappable
BY DESIGN (architectural note 3 in pw2_field_mapper.py — no
authoritative DOB letter-code mapping for the -PL/-SP/-FB suffix
yet) and is INFORMATIONAL on the PW2 form, not a primary identifier.
Other production permits will hit this same gate.

This test file pins:
  • the CRITICAL_PW2_FIELDS membership (frozen set of 9 entries)
  • the partition_unmappable_fields helper's classification logic
  • the enqueue-side behavior:
      - non-critical only → success, audit_log carries the
        non_critical_unmappable_fields event
      - critical present → 400 with critical_unmappable_fields
        and full_unmappable_fields in the response body
  • the production case: B00736930-S1 plumbing, where the only
    unmappable entry is work_permit_number (non-critical) → enqueue
    succeeds.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


# ── CRITICAL_PW2_FIELDS membership ─────────────────────────────────

class TestCriticalPw2FieldsMembership(unittest.TestCase):

    def test_set_contents(self):
        """Pinned to the spec from MR.7-followup. If a future commit
        adds or removes an entry, this test forces an explicit decision
        — don't drift the membership silently."""
        from lib.pw2_field_mapper import CRITICAL_PW2_FIELDS
        self.assertEqual(
            set(CRITICAL_PW2_FIELDS),
            {
                "applicant_name",
                "applicant_license_number",
                "applicant_email",
                "applicant_business_name",
                "project_address",
                "bin",
                "job_filing_number",
                "current_expiration_date",
                "all_fields",  # synthetic root-cause bucket
            },
        )

    def test_non_critical_fields_not_in_set(self):
        """The user-listed non-critical fields must NOT be in the set
        — flipping any of these to critical would re-introduce the
        original over-strict gate behavior."""
        from lib.pw2_field_mapper import CRITICAL_PW2_FIELDS
        for fld in (
            "work_permit_number",
            "bbl",
            "gc_license_number",
            "issuance_date",
            "effective_expiry",
        ):
            self.assertNotIn(fld, CRITICAL_PW2_FIELDS, fld)


# ── partition_unmappable_fields ────────────────────────────────────

class TestPartitionUnmappableFields(unittest.TestCase):

    def test_classifies_critical_and_non_critical_correctly(self):
        from lib.pw2_field_mapper import partition_unmappable_fields
        entries = [
            "work_permit_number: not stored on dob_logs",            # non-critical
            "applicant_email: primary filing rep has no email",      # critical
            "bbl: project record missing BBL",                       # non-critical
            "bin: project.nyc_bin and dob_log.nyc_bin both missing", # critical
            "issuance_date: re-run backfill",                        # non-critical
        ]
        out = partition_unmappable_fields(entries)
        self.assertEqual(len(out["critical"]), 2)
        self.assertEqual(len(out["non_critical"]), 3)
        self.assertIn(
            "applicant_email: primary filing rep has no email",
            out["critical"],
        )
        self.assertIn(
            "bin: project.nyc_bin and dob_log.nyc_bin both missing",
            out["critical"],
        )

    def test_empty_input_returns_empty_partition(self):
        from lib.pw2_field_mapper import partition_unmappable_fields
        self.assertEqual(
            partition_unmappable_fields([]),
            {"critical": [], "non_critical": []},
        )

    def test_none_input_safe(self):
        from lib.pw2_field_mapper import partition_unmappable_fields
        self.assertEqual(
            partition_unmappable_fields(None),
            {"critical": [], "non_critical": []},
        )

    def test_all_fields_synthetic_treated_as_critical(self):
        """The 'all_fields' entry is emitted only when the renewal
        record itself is missing — must hard-block."""
        from lib.pw2_field_mapper import partition_unmappable_fields
        out = partition_unmappable_fields(["all_fields: renewal record not found"])
        self.assertEqual(len(out["critical"]), 1)
        self.assertEqual(len(out["non_critical"]), 0)

    def test_entry_without_colon_falls_to_non_critical(self):
        """Defensive: malformed entries don't hard-block. The gate
        already records the full original list in the audit log."""
        from lib.pw2_field_mapper import partition_unmappable_fields
        out = partition_unmappable_fields(["something_weird"])
        self.assertEqual(out["critical"], [])
        self.assertEqual(out["non_critical"], ["something_weird"])

    def test_non_string_entries_skipped(self):
        from lib.pw2_field_mapper import partition_unmappable_fields
        out = partition_unmappable_fields(["applicant_email: x", None, 42])
        self.assertEqual(len(out["critical"]), 1)
        self.assertEqual(len(out["non_critical"]), 0)


# ── Enqueue endpoint integration — REMOVED in MR.14 commit 4b.
# enqueue_filing_job is a hard 503 stub (renewal automation
# deferred to v2). The CRITICAL_PW2_FIELDS membership + the
# partition_unmappable_fields helper are still pinned by the
# tests above; the gate behavior they used to integrate with
# has no live consumer.


if __name__ == "__main__":
    unittest.main()
