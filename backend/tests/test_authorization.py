"""MR.10 — Authorization document acceptance.

Coverage:
  • GET /api/owner/companies/{id}/authorization — returns text + status.
  • POST — happy path (typed name matches gc_licensee_name OR
    gc_business_name OR name).
  • POST — typed name mismatch → 400.
  • POST — re-posting overwrites with new accepted_at.
  • POST — empty typed name → 400.
  • Admin auth gate on both endpoints.

MR.14 commit 4b — enqueue-gate integration tests REMOVED. The
enqueue endpoint is now a hard 503 stub; the credential and
authorization gates inside it are dead code (no behavior to pin).
The endpoint itself goes away entirely in commit 4c.
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


# ── MR.6 enqueue gate integration — REMOVED in MR.14 commit 4b.
# enqueue_filing_job is a hard 503 stub; the credential gate +
# authorization gate inside it are dead code with no behavior to
# pin. The endpoint itself goes away entirely in commit 4c.


if __name__ == "__main__":
    unittest.main()
