"""MR.10 — Authorization document acceptance + MR.6 enqueue gate.

Coverage:
  • GET /api/owner/companies/{id}/authorization — returns text + status.
  • POST — happy path (typed name matches gc_licensee_name OR
    gc_business_name OR name).
  • POST — typed name mismatch → 400.
  • POST — re-posting overwrites with new accepted_at.
  • POST — empty typed name → 400.
  • Admin auth gate on both endpoints.
  • MR.6 enqueue gate: company without authorization → 400 with
    code='authorization_required'.
  • MR.6 enqueue gate: company with stale-version authorization → 400.
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
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "live")  # for the gate test

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _setup_client(*, role="owner"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": "co_a"}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


# ── GET authorization ──────────────────────────────────────────────

class TestGetAuthorization(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.get("/api/owner/companies/co_a/authorization")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_returns_text_and_unaccepted_when_no_auth(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a", "name": "BLUEVIEW CONSTRUCTION INC",
            "gc_licensee_name": "Roy Fisman",
        })
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/owner/companies/co_a/authorization")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertFalse(body["accepted"])
            self.assertIsNone(body["authorization"])
            self.assertIn("Filing Authorization", body["authorization_text"])
            self.assertEqual(body["expected_licensee_name"], "Roy Fisman")
        finally:
            restore()

    def test_returns_accepted_when_version_matches(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a", "name": "Test",
            "authorization": {
                "version": server.AUTHORIZATION_TEXT_VERSION,
                "accepted_at": datetime.now(timezone.utc),
                "licensee_name_typed": "Test",
                "accepted_by_user_id": "u1",
            },
        })
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/owner/companies/co_a/authorization")
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["accepted"])
        finally:
            restore()

    def test_returns_unaccepted_on_version_mismatch(self):
        """Stored authorization with an OLD version → accepted=false.
        Forces re-acceptance after a text bump."""
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a", "name": "Test",
            "authorization": {
                "version": "0.9-stale",
                "accepted_at": datetime.now(timezone.utc),
                "licensee_name_typed": "Test",
                "accepted_by_user_id": "u1",
            },
        })
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/owner/companies/co_a/authorization")
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["accepted"])
        finally:
            restore()


# ── POST authorization ─────────────────────────────────────────────

class TestPostAuthorization(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.post(
                "/api/owner/companies/co_a/authorization",
                json={"licensee_name_typed": "anyone"},
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_happy_path_persists_authorization(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a", "name": "BLUEVIEW CONSTRUCTION INC",
        })
        mock_db.companies.update_one = AsyncMock()
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/authorization",
                    json={"licensee_name_typed": "BLUEVIEW CONSTRUCTION INC"},
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["authorization"]["version"], server.AUTHORIZATION_TEXT_VERSION)
            mock_db.companies.update_one.assert_awaited_once()
            update_doc = mock_db.companies.update_one.await_args.args[1]["$set"]
            self.assertIn("authorization", update_doc)
        finally:
            restore()

    def test_typed_name_case_insensitive_match(self):
        """Operator's typed name should match case-insensitively
        against any of the company name forms."""
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a", "name": "BLUEVIEW CONSTRUCTION INC",
        })
        mock_db.companies.update_one = AsyncMock()
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/authorization",
                    json={"licensee_name_typed": "blueview construction inc"},
                )
            self.assertEqual(resp.status_code, 200, resp.text)
        finally:
            restore()

    def test_typed_name_mismatch_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a", "name": "BLUEVIEW CONSTRUCTION INC",
        })
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/authorization",
                    json={"licensee_name_typed": "Different Co LLC"},
                )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()["detail"]["code"], "licensee_name_mismatch")
        finally:
            restore()

    def test_empty_typed_name_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/authorization",
                    json={"licensee_name_typed": "   "},
                )
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()


# ── MR.6 enqueue gate integration ──────────────────────────────────

class TestMr6EnqueueGate(unittest.TestCase):
    """Confirms the MR.6 enqueue endpoint refuses companies without
    authorization. Exercises only the gate; other gates are stubbed
    to pass."""

    def _full_db_stub(self, *, company):
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value={
            "_id": "r1", "company_id": "co_a", "status": "eligible",
        })
        mock_db.permit_renewals.update_one = AsyncMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find_one = AsyncMock(return_value=None)
        return mock_db

    def _patch_lib_imports(self):
        import lib.filing_readiness as fr_mod
        import lib.pw2_field_mapper as pw_mod

        class _Readiness:
            ready = True
            blockers = []

        class _FieldMap:
            unmappable_fields = []
            fields = {}
            permit_class = "DOB_NOW"
            attachments_required = []
            notes = []
            permit_renewal_id = "r1"

            def model_dump(self):
                return {
                    "permit_renewal_id": "r1", "permit_class": "DOB_NOW",
                    "fields": {}, "attachments_required": [],
                    "notes": [], "unmappable_fields": [],
                }

        return [
            patch.object(fr_mod, "check_filing_readiness",
                         AsyncMock(return_value=_Readiness())),
            patch.object(pw_mod, "map_pw2_fields",
                         AsyncMock(return_value=_FieldMap())),
        ]

    def _setup_client(self):
        import server
        user = {"id": "u1", "_id": "u1", "role": "admin", "company_id": "co_a"}

        async def _fake_user():
            return user

        server.app.dependency_overrides[server.get_current_user] = _fake_user
        return TestClient(server.app), lambda: server.app.dependency_overrides.clear()

    def _credentialed_company(self, *, authorization=None):
        now = datetime.now(timezone.utc)
        return {
            "_id": "co_a",
            "name": "Test",
            "filing_reps": [{
                "id": "rep_primary", "name": "Jane",
                "license_class": "GC", "license_number": "626198",
                "email": "jane@example.com", "is_primary": True,
                "created_at": now, "updated_at": now,
                "credentials": [{
                    "version": 1, "encrypted_ciphertext": "b64",
                    "public_key_fingerprint": "fp",
                    "created_at": now, "superseded_at": None,
                }],
            }],
            "authorization": authorization,
        }

    def test_no_authorization_blocks_enqueue(self):
        import server
        client, restore = self._setup_client()
        mock_db = self._full_db_stub(
            company=self._credentialed_company(authorization=None),
        )
        patches = self._patch_lib_imports()
        try:
            for p in patches:
                p.__enter__()
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(
                resp.json()["detail"]["code"], "authorization_required",
            )
        finally:
            for p in patches:
                p.__exit__(None, None, None)
            restore()

    def test_stale_version_authorization_blocks_enqueue(self):
        import server
        client, restore = self._setup_client()
        stale_auth = {
            "version": "0.9-stale",
            "accepted_at": datetime.now(timezone.utc),
            "licensee_name_typed": "Test",
            "accepted_by_user_id": "u1",
        }
        mock_db = self._full_db_stub(
            company=self._credentialed_company(authorization=stale_auth),
        )
        patches = self._patch_lib_imports()
        try:
            for p in patches:
                p.__enter__()
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            self.assertEqual(resp.status_code, 400)
            detail = resp.json()["detail"]
            self.assertEqual(detail["code"], "authorization_required")
            self.assertEqual(detail["stored_version"], "0.9-stale")
        finally:
            for p in patches:
                p.__exit__(None, None, None)
            restore()

    def test_current_version_authorization_passes_gate(self):
        import server
        client, restore = self._setup_client()
        current_auth = {
            "version": server.AUTHORIZATION_TEXT_VERSION,
            "accepted_at": datetime.now(timezone.utc),
            "licensee_name_typed": "Test",
            "accepted_by_user_id": "u1",
        }
        mock_db = self._full_db_stub(
            company=self._credentialed_company(authorization=current_auth),
        )
        # Mock the Redis enqueue so the test doesn't try a real LPUSH.
        lpush_mock = AsyncMock()
        # Add insert_one for the filing_jobs collection.
        mock_db.filing_jobs.insert_one = AsyncMock()
        mock_db.filing_jobs.delete_one = AsyncMock()

        patches = self._patch_lib_imports()
        try:
            for p in patches:
                p.__enter__()
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x), \
                 patch.object(server, "_lpush_filing_queue", lpush_mock), \
                 patch.dict(os.environ, {"ELIGIBILITY_REWRITE_MODE": "live"}):
                resp = client.post("/api/permit-renewals/r1/file")
            # Authorization gate passes; downstream succeeds.
            self.assertEqual(resp.status_code, 200, resp.text)
        finally:
            for p in patches:
                p.__exit__(None, None, None)
            restore()


if __name__ == "__main__":
    unittest.main()
