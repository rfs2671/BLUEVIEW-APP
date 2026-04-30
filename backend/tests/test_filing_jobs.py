"""MR.6 — POST /api/permit-renewals/{id}/file enqueue endpoint.

Coverage of the gate chain (each gate test independently fails the
target gate while satisfying all earlier gates):
  1. tenant guard (cross-tenant → 403)
  2. ELIGIBILITY_REWRITE_MODE != 'live' → 400
  3. filing readiness blocked → 400
  4. PW2 mapper unmappable_fields non-empty → 400
  5. no filing_rep → 400
  6. filing_rep present but no active credential → 400
  7. dedup: existing non-terminal job → 409

Plus:
  - 404 when renewal missing
  - happy path: filing_jobs insert + LPUSH + permit_renewals status flip
  - 503 + rollback when Redis fails: filing_jobs.delete_one fires so
    dedup gate doesn't lock the renewal forever
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
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "live")  # default to live; tests override

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


# ── Fixtures / stubs ───────────────────────────────────────────────

def _setup_client(*, role: str = "admin", company_id: str = "co_a"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": company_id}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _stub_renewal(company_id: str = "co_a"):
    return {"_id": "r1", "company_id": company_id, "status": "eligible"}


def _stub_company_with_credentialed_rep():
    now = datetime.now(timezone.utc)
    return {
        "_id": "co_a",
        "name": "Acme GC",
        "filing_reps": [{
            "id": "rep_primary",
            "name": "Jane",
            "license_class": "GC",
            "license_number": "626198",
            "email": "jane@example.com",
            "is_primary": True,
            "created_at": now,
            "updated_at": now,
            "credentials": [{
                "version": 3,
                "encrypted_ciphertext": "b64-blob",
                "public_key_fingerprint": "fp",
                "created_at": now,
                "superseded_at": None,
            }],
        }],
    }


class _ReadinessReport:
    def __init__(self, ready: bool, blockers=None):
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


def _full_db_stub(*, renewal=None, company=None, existing_job=None):
    """Default: every gate passes."""
    mock_db = MagicMock()
    mock_db.permit_renewals = MagicMock()
    mock_db.permit_renewals.find_one = AsyncMock(
        return_value=renewal or _stub_renewal()
    )
    mock_db.permit_renewals.update_one = AsyncMock()
    mock_db.companies = MagicMock()
    mock_db.companies.find_one = AsyncMock(
        return_value=company or _stub_company_with_credentialed_rep()
    )
    mock_db.filing_jobs = MagicMock()
    mock_db.filing_jobs.find_one = AsyncMock(return_value=existing_job)
    mock_db.filing_jobs.insert_one = AsyncMock()
    mock_db.filing_jobs.delete_one = AsyncMock()
    return mock_db


def _patch_lib_imports(*, ready=True, unmappable=None):
    """Patch the lib imports inside the enqueue endpoint."""
    import lib.filing_readiness as fr_mod
    import lib.pw2_field_mapper as pw_mod
    return [
        patch.object(fr_mod, "check_filing_readiness",
                     AsyncMock(return_value=_ReadinessReport(ready=ready))),
        patch.object(pw_mod, "map_pw2_fields",
                     AsyncMock(return_value=_FieldMap(unmappable=unmappable))),
    ]


def _enter(patches):
    return [p.__enter__() for p in patches]


def _exit(patches):
    for p in patches:
        p.__exit__(None, None, None)


# ── Tests ──────────────────────────────────────────────────────────

class TestEnqueueGates(unittest.TestCase):

    def test_404_when_renewal_missing(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _full_db_stub()
        mock_db.permit_renewals.find_one = AsyncMock(return_value=None)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post("/api/permit-renewals/r_missing/file")
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_403_cross_tenant(self):
        import server
        client, restore = _setup_client(company_id="co_other")
        mock_db = _full_db_stub()
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_400_when_mode_not_live(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _full_db_stub()
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "shadow"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()["detail"]["code"], "mode_not_live")
        finally:
            restore()

    def test_400_when_readiness_blocked(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _full_db_stub()
        patches = _patch_lib_imports(ready=False)
        try:
            _enter(patches)
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()["detail"]["code"], "readiness_blocked")
        finally:
            _exit(patches)
            restore()

    def test_400_when_critical_unmappable_fields(self):
        # MR.7-followup: the gate now partitions unmappable_fields
        # into critical (CRITICAL_PW2_FIELDS) vs. non-critical. Only
        # critical entries 400. work_permit_number — used by the
        # original test fixture — is now non-critical (it's
        # informational on the PW2 form per MR.4 architectural note 3),
        # so this fixture is updated to use applicant_email which IS
        # critical.
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _full_db_stub()
        patches = _patch_lib_imports(
            ready=True,
            unmappable=["applicant_email: primary filing rep has no email"],
        )
        try:
            _enter(patches)
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 400)
            body = resp.json()
            self.assertEqual(body["detail"]["code"], "mapper_unmappable_fields")
            # Critical list surfaces the blocker; full list mirrors
            # since this fixture only has the one entry.
            self.assertEqual(
                body["detail"]["critical_unmappable_fields"],
                ["applicant_email: primary filing rep has no email"],
            )
        finally:
            _exit(patches)
            restore()

    def test_400_when_no_filing_rep(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _full_db_stub(company={
            "_id": "co_a", "name": "Acme", "filing_reps": [],
        })
        patches = _patch_lib_imports()
        try:
            _enter(patches)
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()["detail"]["code"], "no_filing_rep")
        finally:
            _exit(patches)
            restore()

    def test_400_when_no_active_credential(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        now = datetime.now(timezone.utc)
        company_no_active = {
            "_id": "co_a",
            "filing_reps": [{
                "id": "rep_x", "name": "X", "license_class": "GC",
                "license_number": "1", "email": "x@example.com",
                "is_primary": True,
                "created_at": now, "updated_at": now,
                "credentials": [
                    {"version": 1, "encrypted_ciphertext": "v1",
                     "public_key_fingerprint": "fp", "created_at": now,
                     "superseded_at": now},  # superseded → no active
                ],
            }],
        }
        mock_db = _full_db_stub(company=company_no_active)
        patches = _patch_lib_imports()
        try:
            _enter(patches)
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()["detail"]["code"], "no_active_credential")
        finally:
            _exit(patches)
            restore()

    def test_409_when_non_terminal_job_exists(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _full_db_stub(existing_job={
            "_id": "fj_existing", "permit_renewal_id": "r1",
            "status": "queued",
        })
        patches = _patch_lib_imports()
        try:
            _enter(patches)
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 409)
            self.assertEqual(resp.json()["detail"]["code"], "filing_job_already_active")
        finally:
            _exit(patches)
            restore()


class TestEnqueueHappyPath(unittest.TestCase):

    def test_creates_job_and_lpushes_and_flips_renewal_status(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _full_db_stub()
        patches = _patch_lib_imports()
        # Mock the redis enqueue so we don't need a live broker.
        lpush_mock = AsyncMock()
        try:
            _enter(patches)
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.object(server, "_lpush_filing_queue", lpush_mock), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["status"], "queued")
            self.assertEqual(body["credential_version"], 3)
            self.assertEqual(body["filing_rep_id"], "rep_primary")
            self.assertEqual(body["retry_count"], 0)
            self.assertNotIn("encrypted_ciphertext", body)

            # filing_jobs.insert_one fired with status=queued.
            mock_db.filing_jobs.insert_one.assert_awaited_once()
            inserted_doc = mock_db.filing_jobs.insert_one.await_args.args[0]
            self.assertEqual(inserted_doc["status"], "queued")
            # Audit log includes initial 'queued' event.
            self.assertEqual(len(inserted_doc["audit_log"]), 1)
            self.assertEqual(inserted_doc["audit_log"][0]["event_type"], "queued")

            # LPUSH ran with the right payload shape.
            lpush_mock.assert_awaited_once()
            payload = lpush_mock.await_args.args[0]
            self.assertEqual(payload["type"], "dob_now_filing")
            self.assertIn("filing_job_id", payload["data"])
            self.assertEqual(
                payload["data"]["encrypted_credentials_b64"], "b64-blob"
            )
            self.assertIn("idempotency_key", payload)

            # permit_renewals flipped to AWAITING_DOB_FILING.
            mock_db.permit_renewals.update_one.assert_awaited_once()
            renewal_set = mock_db.permit_renewals.update_one.await_args.args[1]["$set"]
            self.assertEqual(renewal_set["status"], "awaiting_dob_filing")
        finally:
            _exit(patches)
            restore()


class TestEnqueueRollback(unittest.TestCase):

    def test_503_and_rollback_when_redis_fails(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _full_db_stub()
        patches = _patch_lib_imports()

        async def _boom(_):
            raise RuntimeError("redis down")

        try:
            _enter(patches)
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.object(server, "_lpush_filing_queue", _boom), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 503)
            # Rollback fired.
            mock_db.filing_jobs.insert_one.assert_awaited_once()
            mock_db.filing_jobs.delete_one.assert_awaited_once()
            # Renewal status NOT flipped on failure.
            mock_db.permit_renewals.update_one.assert_not_awaited()
        finally:
            _exit(patches)
            restore()


if __name__ == "__main__":
    unittest.main()
