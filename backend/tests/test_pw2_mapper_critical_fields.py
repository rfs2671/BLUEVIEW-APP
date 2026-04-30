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


# ── Enqueue endpoint integration ───────────────────────────────────
# Mirrors the test_filing_jobs.py setup but pinned to the partition
# behavior. We test BOTH branches of the gate.

def _setup_client(*, role="admin", company_id="co_a"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": company_id}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _stub_company():
    import server as _server
    now = datetime.now(timezone.utc)
    return {
        "_id": "co_a",
        # MR.10 — pre-authorized so the partition gate (mapper) is the
        # one being exercised. Authorization gate is tested in
        # test_authorization.py.
        "authorization": {
            "version": _server.AUTHORIZATION_TEXT_VERSION,
            "accepted_at": now,
            "accepted_by_user_id": "u1",
            "licensee_name_typed": "Acme GC",
        },
        "filing_reps": [{
            "id": "rep_primary", "name": "Jane", "license_class": "GC",
            "license_number": "626198", "email": "jane@example.com",
            "is_primary": True, "created_at": now, "updated_at": now,
            "credentials": [{
                "version": 1, "encrypted_ciphertext": "b64",
                "public_key_fingerprint": "fp", "created_at": now,
                "superseded_at": None,
            }],
        }],
    }


class _ReadinessReport:
    def __init__(self, ready=True, blockers=None):
        self.ready = ready
        self.blockers = blockers or []


class _FieldMap:
    def __init__(self, unmappable=None):
        self.unmappable_fields = unmappable or []
        self.fields = {}
        self.permit_class = "DOB_NOW"
        self.attachments_required = []
        self.notes = []
        self.permit_renewal_id = "r1"

    def model_dump(self):
        return {
            "permit_renewal_id": self.permit_renewal_id,
            "permit_class": self.permit_class,
            "fields": self.fields,
            "attachments_required": self.attachments_required,
            "notes": self.notes,
            "unmappable_fields": self.unmappable_fields,
        }


def _stub_db():
    mock_db = MagicMock()
    mock_db.permit_renewals = MagicMock()
    mock_db.permit_renewals.find_one = AsyncMock(
        return_value={"_id": "r1", "company_id": "co_a", "status": "eligible"},
    )
    mock_db.permit_renewals.update_one = AsyncMock()
    mock_db.companies = MagicMock()
    mock_db.companies.find_one = AsyncMock(return_value=_stub_company())
    mock_db.filing_jobs = MagicMock()
    mock_db.filing_jobs.find_one = AsyncMock(return_value=None)
    mock_db.filing_jobs.insert_one = AsyncMock()
    mock_db.filing_jobs.delete_one = AsyncMock()
    return mock_db


class TestEnqueueGateNonCriticalProceeds(unittest.TestCase):
    """Production permit B00736930-S1 plumbing reproduction.

    work_permit_number is the only unmappable entry (per MR.4
    architectural note 3); the gate must NOT block. Audit log
    captures the gap as a non_critical_unmappable_fields event."""

    def test_b00736930_s1_plumbing_enqueue_proceeds(self):
        import server
        import lib.filing_readiness as fr_mod
        import lib.pw2_field_mapper as pw_mod

        client, restore = _setup_client(company_id="co_a")
        mock_db = _stub_db()
        non_critical_only = [
            "work_permit_number: not stored on dob_logs; canonical "
            "-PL/-SP/-FB suffix requires a permit_type letter-code "
            "mapping that's not yet sourced from DOB."
        ]
        lpush_mock = AsyncMock()

        with patch.object(fr_mod, "check_filing_readiness",
                          AsyncMock(return_value=_ReadinessReport(ready=True))), \
             patch.object(pw_mod, "map_pw2_fields",
                          AsyncMock(return_value=_FieldMap(unmappable=non_critical_only))), \
             patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x), \
             patch.object(server, "_lpush_filing_queue", lpush_mock), \
             patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
            try:
                resp = client.post("/api/permit-renewals/r1/file")
            finally:
                restore()

        # Enqueue succeeded — production permit unblocked.
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "queued")

        # Audit log carries TWO events: queued + non_critical_unmappable_fields.
        mock_db.filing_jobs.insert_one.assert_awaited_once()
        inserted = mock_db.filing_jobs.insert_one.await_args.args[0]
        audit_log = inserted["audit_log"]
        self.assertEqual(len(audit_log), 2)
        self.assertEqual(audit_log[0]["event_type"], "queued")
        self.assertEqual(
            audit_log[1]["event_type"], "non_critical_unmappable_fields"
        )
        self.assertEqual(
            audit_log[1]["metadata"]["unmappable_fields"],
            non_critical_only,
        )
        # Redis received the LPUSH.
        lpush_mock.assert_awaited_once()


class TestEnqueueGateCriticalRejects(unittest.TestCase):

    def test_critical_unmappable_blocks_enqueue(self):
        import server
        import lib.filing_readiness as fr_mod
        import lib.pw2_field_mapper as pw_mod

        client, restore = _setup_client(company_id="co_a")
        mock_db = _stub_db()
        mixed = [
            "work_permit_number: informational",                 # non-critical
            "applicant_name: primary filing rep has no name",    # critical
            "bbl: project record missing BBL",                   # non-critical
        ]

        with patch.object(fr_mod, "check_filing_readiness",
                          AsyncMock(return_value=_ReadinessReport(ready=True))), \
             patch.object(pw_mod, "map_pw2_fields",
                          AsyncMock(return_value=_FieldMap(unmappable=mixed))), \
             patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x), \
             patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
            try:
                resp = client.post("/api/permit-renewals/r1/file")
            finally:
                restore()

        self.assertEqual(resp.status_code, 400)
        detail = resp.json()["detail"]
        self.assertEqual(detail["code"], "mapper_unmappable_fields")
        # Critical list surfaces only the blocker.
        self.assertEqual(len(detail["critical_unmappable_fields"]), 1)
        self.assertIn("applicant_name", detail["critical_unmappable_fields"][0])
        # Full list preserves the entire mapper output for debugging.
        self.assertEqual(detail["full_unmappable_fields"], mixed)
        # No filing_jobs insert occurred.
        mock_db.filing_jobs.insert_one.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
