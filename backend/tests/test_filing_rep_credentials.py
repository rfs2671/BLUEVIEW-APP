"""MR.6 — filing_rep credentials data model + CRUD endpoints.

Coverage:
  - FilingRepCredential Pydantic shape (version int, ciphertext str,
    fingerprint str, created_at datetime, optional superseded_at).
  - filing_rep_active_credential() helper:
      • returns the highest-version entry where superseded_at is None
      • returns None when all entries are superseded
      • returns None on a rep with no credentials
  - POST /api/owner/companies/{company_id}/filing-reps/{rep_id}/credentials
      • requires owner role (admin → 403)
      • 404 when company missing
      • 404 when rep missing
      • 400 when ciphertext or fingerprint missing
      • happy path: supersede prior active, push new entry,
        version auto-increments from max(existing) + 1, the response
        is metadata-only (no ciphertext)
  - DELETE /api/owner/companies/{company_id}/filing-reps/{rep_id}/credentials/active
      • requires owner role
      • 404 when no active credential
      • happy path: stamps superseded_at on the active entry
  - GET /api/owner/companies/{company_id}/filing-reps/{rep_id}/credentials
      • returns metadata-only (ciphertext stripped)
      • orders by version descending
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


# ── Pydantic validation ────────────────────────────────────────────

class TestFilingRepCredentialModel(unittest.TestCase):

    def test_required_fields(self):
        from server import FilingRepCredential
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            FilingRepCredential()

    def test_happy_construction(self):
        from server import FilingRepCredential
        now = datetime.now(timezone.utc)
        cred = FilingRepCredential(
            version=1,
            encrypted_ciphertext="b64-blob",
            public_key_fingerprint="sha256:" + "0" * 64,
            created_at=now,
        )
        self.assertEqual(cred.version, 1)
        self.assertIsNone(cred.superseded_at)

    def test_superseded_at_optional(self):
        from server import FilingRepCredential
        now = datetime.now(timezone.utc)
        cred = FilingRepCredential(
            version=2,
            encrypted_ciphertext="b64",
            public_key_fingerprint="sha256:" + "a" * 64,
            created_at=now,
            superseded_at=now,
        )
        self.assertEqual(cred.superseded_at, now)


# ── filing_rep_active_credential helper ────────────────────────────

class TestActiveCredentialHelper(unittest.TestCase):

    def test_returns_none_on_no_credentials(self):
        from server import filing_rep_active_credential
        rep = {"id": "r1", "credentials": []}
        self.assertIsNone(filing_rep_active_credential(rep))

    def test_returns_none_when_all_superseded(self):
        from server import filing_rep_active_credential
        now = datetime.now(timezone.utc)
        rep = {
            "id": "r1",
            "credentials": [
                {"version": 1, "superseded_at": now},
                {"version": 2, "superseded_at": now},
            ],
        }
        self.assertIsNone(filing_rep_active_credential(rep))

    def test_returns_highest_version_with_no_superseded_at(self):
        from server import filing_rep_active_credential
        now = datetime.now(timezone.utc)
        rep = {
            "id": "r1",
            "credentials": [
                {"version": 1, "superseded_at": now},
                {"version": 2, "superseded_at": now},
                {"version": 3, "superseded_at": None},
            ],
        }
        active = filing_rep_active_credential(rep)
        self.assertIsNotNone(active)
        self.assertEqual(active["version"], 3)

    def test_handles_missing_credentials_field(self):
        from server import filing_rep_active_credential
        rep = {"id": "r1"}  # credentials key absent
        self.assertIsNone(filing_rep_active_credential(rep))

    def test_handles_non_dict_input(self):
        from server import filing_rep_active_credential
        self.assertIsNone(filing_rep_active_credential(None))
        self.assertIsNone(filing_rep_active_credential("nope"))


# ── Endpoint helpers ───────────────────────────────────────────────

def _setup_client(*, role: str = "owner"):
    """TestClient with auth override. Returns (client, restore_fn)."""
    import server
    user = {"id": "u1", "role": role, "_id": "u1"}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _make_rep(rep_id="r1", credentials=None):
    now = datetime.now(timezone.utc)
    return {
        "id": rep_id,
        "name": "Jane Filer",
        "license_class": "GC",
        "license_number": "626198",
        "email": "jane@example.com",
        "is_primary": True,
        "created_at": now,
        "updated_at": now,
        "credentials": credentials if credentials is not None else [],
    }


# ── POST /credentials ──────────────────────────────────────────────

class TestPostCredential(unittest.TestCase):

    HEADERS = {}

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.post(
                "/api/owner/companies/co_a/filing-reps/r1/credentials",
                json={"encrypted_ciphertext": "b64", "public_key_fingerprint": "fp"},
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_404_when_company_missing(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=None)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_missing/filing-reps/r1/credentials",
                    json={"encrypted_ciphertext": "b64", "public_key_fingerprint": "fp"},
                )
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_404_when_rep_missing(self):
        import server
        client, restore = _setup_client(role="owner")
        company = {"_id": "co_a", "filing_reps": []}
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/filing-reps/r_unknown/credentials",
                    json={"encrypted_ciphertext": "b64", "public_key_fingerprint": "fp"},
                )
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_400_when_ciphertext_or_fingerprint_missing(self):
        import server
        client, restore = _setup_client(role="owner")
        company = {"_id": "co_a", "filing_reps": [_make_rep()]}
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                # Empty ciphertext.
                resp = client.post(
                    "/api/owner/companies/co_a/filing-reps/r1/credentials",
                    json={"encrypted_ciphertext": "", "public_key_fingerprint": "fp"},
                )
                self.assertEqual(resp.status_code, 400)
        finally:
            restore()

    def test_first_credential_gets_version_1(self):
        import server
        client, restore = _setup_client(role="owner")
        company = {"_id": "co_a", "filing_reps": [_make_rep(credentials=[])]}
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        mock_db.companies.update_one = AsyncMock(return_value=MagicMock(
            matched_count=1, modified_count=1,
        ))
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/filing-reps/r1/credentials",
                    json={
                        "encrypted_ciphertext": "ciphertext-v1",
                        "public_key_fingerprint": "fp:" + "0" * 60,
                    },
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["version"], 1)
            self.assertNotIn("encrypted_ciphertext", body)
            # Two update_one calls: supersede (no-op when first) + push.
            self.assertEqual(mock_db.companies.update_one.await_count, 2)
        finally:
            restore()

    def test_subsequent_credential_increments_version_and_supersedes(self):
        import server
        client, restore = _setup_client(role="owner")
        existing_now = datetime.now(timezone.utc)
        existing_creds = [
            {
                "version": 1,
                "encrypted_ciphertext": "v1",
                "public_key_fingerprint": "fp1",
                "created_at": existing_now,
                "superseded_at": None,
            },
        ]
        company = {
            "_id": "co_a",
            "filing_reps": [_make_rep(credentials=existing_creds)],
        }
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        mock_db.companies.update_one = AsyncMock(return_value=MagicMock(
            matched_count=1, modified_count=1,
        ))
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/filing-reps/r1/credentials",
                    json={
                        "encrypted_ciphertext": "ciphertext-v2",
                        "public_key_fingerprint": "fp2",
                    },
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["version"], 2)
            # First call: supersede (filter on superseded_at: None).
            first_call = mock_db.companies.update_one.await_args_list[0]
            af0 = first_call.kwargs.get("array_filters") or first_call.args[2:3] or [None]
            # Either positional or kwarg form is fine; assert filter shape.
            af_present = first_call.kwargs.get("array_filters")
            self.assertIsNotNone(af_present)
            cred_filter = next(f for f in af_present if "cred.superseded_at" in f)
            self.assertIsNone(cred_filter["cred.superseded_at"])
            # Second call: $push on credentials.
            second_call = mock_db.companies.update_one.await_args_list[1]
            update_doc = second_call.args[1]
            self.assertIn("$push", update_doc)
            new_cred = update_doc["$push"]["filing_reps.$[rep].credentials"]
            self.assertEqual(new_cred["version"], 2)
            self.assertEqual(new_cred["encrypted_ciphertext"], "ciphertext-v2")
            self.assertIsNone(new_cred["superseded_at"])
        finally:
            restore()


# ── DELETE /credentials/active ─────────────────────────────────────

class TestRevokeActiveCredential(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.delete(
                "/api/owner/companies/co_a/filing-reps/r1/credentials/active"
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_404_when_no_active(self):
        import server
        client, restore = _setup_client(role="owner")
        # All credentials already superseded.
        now = datetime.now(timezone.utc)
        rep = _make_rep(credentials=[
            {"version": 1, "encrypted_ciphertext": "v1", "public_key_fingerprint": "fp",
             "created_at": now, "superseded_at": now},
        ])
        company = {"_id": "co_a", "filing_reps": [rep]}
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/owner/companies/co_a/filing-reps/r1/credentials/active"
                )
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_revoke_sets_superseded_at(self):
        import server
        client, restore = _setup_client(role="owner")
        now = datetime.now(timezone.utc)
        rep = _make_rep(credentials=[
            {"version": 1, "encrypted_ciphertext": "v1", "public_key_fingerprint": "fp",
             "created_at": now, "superseded_at": None},
        ])
        company = {"_id": "co_a", "filing_reps": [rep]}
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        mock_db.companies.update_one = AsyncMock(return_value=MagicMock(
            matched_count=1, modified_count=1,
        ))
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/owner/companies/co_a/filing-reps/r1/credentials/active"
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertTrue(body["revoked"])
            self.assertEqual(body["version"], 1)
            # update_one set superseded_at on the active entry.
            args, kwargs = mock_db.companies.update_one.await_args
            self.assertIn("$set", args[1])
            set_payload = args[1]["$set"]
            self.assertIn("filing_reps.$[rep].credentials.$[cred].superseded_at", set_payload)
        finally:
            restore()


# ── GET /credentials ───────────────────────────────────────────────

class TestListCredentials(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.get(
                "/api/owner/companies/co_a/filing-reps/r1/credentials"
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_returns_metadata_only_no_ciphertext(self):
        import server
        client, restore = _setup_client(role="owner")
        now = datetime.now(timezone.utc)
        rep = _make_rep(credentials=[
            {"version": 1, "encrypted_ciphertext": "secret-v1",
             "public_key_fingerprint": "fp1", "created_at": now,
             "superseded_at": now},
            {"version": 2, "encrypted_ciphertext": "secret-v2",
             "public_key_fingerprint": "fp2", "created_at": now,
             "superseded_at": None},
        ])
        company = {"_id": "co_a", "filing_reps": [rep]}
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get(
                    "/api/owner/companies/co_a/filing-reps/r1/credentials"
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(len(body), 2)
            for entry in body:
                self.assertNotIn("encrypted_ciphertext", entry)
                self.assertIn("version", entry)
                self.assertIn("public_key_fingerprint", entry)
            # Ordering: highest version first.
            self.assertEqual(body[0]["version"], 2)
            self.assertEqual(body[1]["version"], 1)
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
