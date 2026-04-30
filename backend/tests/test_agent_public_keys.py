"""MR.10 — Agent public key registry endpoints.

Coverage:
  • POST /admin/agent-keys — register, computes fingerprint, owner-only.
  • GET /admin/agent-keys — list all (active + revoked), owner-only.
  • DELETE /admin/agent-keys/{id} — set revoked_at, owner-only.
  • GET /agent-public-key — no-auth read of active key, 503 when none.
  • Validation: malformed PEM → 400.
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


def _generate_pem():
    """Tiny RSA-4096 keypair generation for fixtures."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    pk = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    return pk.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def _async_iter(items):
    async def gen(self):
        for it in items:
            yield it
    return gen


def _setup_client(*, role="owner"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": "co_a"}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _setup_anon_client():
    """No auth override — used for the public /agent-public-key
    endpoint which requires no auth."""
    import server
    server.app.dependency_overrides.clear()
    return TestClient(server.app)


# ── POST /admin/agent-keys ─────────────────────────────────────────

class TestRegisterAgentKey(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.post(
                "/api/admin/agent-keys",
                json={"worker_id": "w1", "public_key_pem": _generate_pem()},
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_owner_registers_and_fingerprint_computed(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        insert_result = MagicMock()
        insert_result.inserted_id = "key_doc_id"
        mock_db.agent_public_keys = MagicMock()
        mock_db.agent_public_keys.insert_one = AsyncMock(return_value=insert_result)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.post(
                    "/api/admin/agent-keys",
                    json={"worker_id": "w1", "public_key_pem": _generate_pem()},
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["worker_id"], "w1")
            self.assertEqual(len(body["fingerprint_sha256"]), 64)
            self.assertIsNone(body["revoked_at"])
            mock_db.agent_public_keys.insert_one.assert_awaited_once()
        finally:
            restore()

    def test_malformed_pem_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.post(
                    "/api/admin/agent-keys",
                    json={"worker_id": "w1", "public_key_pem": "not a pem"},
                )
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()

    def test_pem_with_correct_markers_but_garbage_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.post(
                    "/api/admin/agent-keys",
                    json={
                        "worker_id": "w1",
                        "public_key_pem": (
                            "-----BEGIN PUBLIC KEY-----\n"
                            "garbageGARBAGEgarbage==\n"
                            "-----END PUBLIC KEY-----\n"
                        ),
                    },
                )
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()


# ── GET /admin/agent-keys ──────────────────────────────────────────

class TestListAgentKeys(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.get("/api/admin/agent-keys")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_lists_both_active_and_revoked(self):
        import server
        client, restore = _setup_client(role="owner")
        keys = [
            {
                "_id": "k1", "worker_id": "w1",
                "public_key_pem": "pem1", "fingerprint_sha256": "fp1",
                "created_at": datetime.now(timezone.utc),
                "revoked_at": None,
            },
            {
                "_id": "k2", "worker_id": "w_old",
                "public_key_pem": "pem2", "fingerprint_sha256": "fp2",
                "created_at": datetime.now(timezone.utc),
                "revoked_at": datetime.now(timezone.utc),
            },
        ]
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.__aiter__ = _async_iter(keys)
        mock_db = MagicMock()
        mock_db.agent_public_keys = MagicMock()
        mock_db.agent_public_keys.find = MagicMock(return_value=cursor)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/agent-keys")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["total"], 2)
        finally:
            restore()


# ── DELETE /admin/agent-keys/{id} ──────────────────────────────────

class TestRevokeAgentKey(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.delete("/api/admin/agent-keys/k1")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_revoke_sets_revoked_at(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.agent_public_keys = MagicMock()
        mock_db.agent_public_keys.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1, modified_count=1),
        )
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete("/api/admin/agent-keys/k1")
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertTrue(resp.json()["revoked"])
            args = mock_db.agent_public_keys.update_one.await_args.args
            self.assertIn("revoked_at", args[1]["$set"])
        finally:
            restore()

    def test_404_when_key_missing(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.agent_public_keys = MagicMock()
        mock_db.agent_public_keys.update_one = AsyncMock(
            return_value=MagicMock(matched_count=0, modified_count=0),
        )
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete("/api/admin/agent-keys/missing")
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()


# ── GET /agent-public-key (no auth) ────────────────────────────────

class TestPublicGetActiveKey(unittest.TestCase):

    def test_no_active_key_503(self):
        import server
        client = _setup_anon_client()
        mock_db = MagicMock()
        mock_db.agent_public_keys = MagicMock()
        mock_db.agent_public_keys.find_one = AsyncMock(return_value=None)
        with patch.object(server, "db", mock_db):
            resp = client.get("/api/agent-public-key")
        self.assertEqual(resp.status_code, 503)

    def test_returns_active_key_pem_and_fingerprint(self):
        import server
        client = _setup_anon_client()
        mock_db = MagicMock()
        mock_db.agent_public_keys = MagicMock()
        mock_db.agent_public_keys.find_one = AsyncMock(return_value={
            "_id": "k1",
            "worker_id": "agent-1",
            "public_key_pem": "PEM_TEXT_HERE",
            "fingerprint_sha256": "abc123",
            "created_at": datetime.now(timezone.utc),
            "revoked_at": None,
        })
        with patch.object(server, "db", mock_db):
            resp = client.get("/api/agent-public-key")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["public_key_pem"], "PEM_TEXT_HERE")
        self.assertEqual(body["fingerprint_sha256"], "abc123")
        self.assertEqual(body["worker_id"], "agent-1")
        # Should NOT leak DB doc internals.
        self.assertNotIn("_id", body)
        self.assertNotIn("created_at", body)


if __name__ == "__main__":
    unittest.main()
