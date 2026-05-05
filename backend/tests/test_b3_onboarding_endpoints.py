"""Phase B3 — onboarding state endpoints.

Pin the contract for the two endpoints that drive the customer
onboarding flow:

  • GET /api/users/me/onboarding-status
  • PATCH /api/users/me/onboarding-step

And the registration-side default that puts every new user onto
step 1.

Backward-compat invariant: a user document with NO `onboarding_step`
field — i.e. a user who existed before Phase B3 shipped — must
get show_onboarding=False from the GET endpoint. The 622 production
users (BLUEVIEW CONSTRUCTION INC + 3 active projects) cannot be
forced through the onboarding flow on their next login.

Test pattern: mock `server.db` on the module via `patch.object`
(matches the convention in test_b1c_endpoints.py + most other
endpoint tests). No live Mongo dependency.
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

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _setup_client(*, role="owner", user_id="u_b3"):
    """Override the auth dependency with a fixed user dict and
    return (client, teardown). Each test injects its own mocked
    `server.db` via patch.object inside the test body."""
    import server

    user = {
        "id": user_id,
        "_id": user_id,
        "user_id": user_id,
        "email": "owner@example.com",
        "role": role,
        "company_id": None,
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _build_users_db(*, find_one_result, update_one_result=None):
    """Build a MagicMock `db` whose users.find_one and users.update_one
    behave async and return the supplied values."""
    db = MagicMock()
    db.users = MagicMock()
    db.users.find_one = AsyncMock(return_value=find_one_result)
    if update_one_result is None:
        update_one_result = MagicMock(matched_count=1, modified_count=1)
    db.users.update_one = AsyncMock(return_value=update_one_result)
    db.users.insert_one = AsyncMock(return_value=MagicMock(inserted_id="u_inserted"))
    return db


# ──────────────────────────────────────────────────────────────────
# GET /api/users/me/onboarding-status
# ──────────────────────────────────────────────────────────────────


class TestOnboardingStatusEndpoint(unittest.TestCase):

    def test_pre_b3_user_no_field_no_onboarding(self):
        """Existing user (no `onboarding_step` field on doc) must be
        treated as already onboarded — backward-compat for the 622
        production users."""
        import server

        user_doc = {
            "_id": "u_b3",
            "email": "owner@example.com",
            "role": "owner",
            # no onboarding_step / onboarding_completed_at
        }
        db = _build_users_db(find_one_result=user_doc)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                r = client.get("/api/users/me/onboarding-status")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertFalse(body["show_onboarding"])
                self.assertEqual(body["step"], "completed")
                self.assertIsNone(body["completed_at"])
        finally:
            restore()

    def test_step_1_user_sees_onboarding(self):
        import server

        user_doc = {"_id": "u_b3", "onboarding_step": "1"}
        db = _build_users_db(find_one_result=user_doc)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                body = client.get("/api/users/me/onboarding-status").json()
                self.assertTrue(body["show_onboarding"])
                self.assertEqual(body["step"], "1")
        finally:
            restore()

    def test_step_3_user_sees_onboarding(self):
        import server

        user_doc = {"_id": "u_b3", "onboarding_step": "3"}
        db = _build_users_db(find_one_result=user_doc)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                body = client.get("/api/users/me/onboarding-status").json()
                self.assertTrue(body["show_onboarding"])
                self.assertEqual(body["step"], "3")
        finally:
            restore()

    def test_completed_user_does_not_see_flow(self):
        import server

        completed_at = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        user_doc = {
            "_id": "u_b3",
            "onboarding_step": "completed",
            "onboarding_completed_at": completed_at,
        }
        db = _build_users_db(find_one_result=user_doc)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                body = client.get("/api/users/me/onboarding-status").json()
                self.assertFalse(body["show_onboarding"])
                self.assertEqual(body["step"], "completed")
                self.assertIsNotNone(body["completed_at"])
        finally:
            restore()

    def test_skipped_user_does_not_see_flow(self):
        import server

        user_doc = {"_id": "u_b3", "onboarding_step": "skipped"}
        db = _build_users_db(find_one_result=user_doc)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                body = client.get("/api/users/me/onboarding-status").json()
                self.assertFalse(body["show_onboarding"])
                self.assertEqual(body["step"], "skipped")
        finally:
            restore()

    def test_user_not_found_returns_404(self):
        import server

        db = _build_users_db(find_one_result=None)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                r = client.get("/api/users/me/onboarding-status")
                self.assertEqual(r.status_code, 404)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# PATCH /api/users/me/onboarding-step
# ──────────────────────────────────────────────────────────────────


class TestOnboardingStepUpdate(unittest.TestCase):

    def test_advance_from_1_to_2(self):
        import server

        db = _build_users_db(find_one_result=None)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                r = client.patch(
                    "/api/users/me/onboarding-step",
                    json={"step": "2"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["step"], "2")

                # update_one was called with onboarding_step=2.
                args, kwargs = db.users.update_one.call_args
                set_ops = args[1]["$set"]
                self.assertEqual(set_ops["onboarding_step"], "2")
                # No completed_at on a non-terminal step.
                self.assertNotIn("onboarding_completed_at", set_ops)
        finally:
            restore()

    def test_skip_path(self):
        import server

        db = _build_users_db(find_one_result=None)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                r = client.patch(
                    "/api/users/me/onboarding-step",
                    json={"step": "skipped"},
                )
                self.assertEqual(r.status_code, 200)

                args, _ = db.users.update_one.call_args
                set_ops = args[1]["$set"]
                self.assertEqual(set_ops["onboarding_step"], "skipped")
                # Skipped does NOT set completed_at.
                self.assertNotIn("onboarding_completed_at", set_ops)
        finally:
            restore()

    def test_complete_stamps_completed_at(self):
        import server

        db = _build_users_db(find_one_result=None)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                r = client.patch(
                    "/api/users/me/onboarding-step",
                    json={"step": "completed"},
                )
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertEqual(body["step"], "completed")
                self.assertIsNotNone(body["completed_at"])

                args, _ = db.users.update_one.call_args
                set_ops = args[1]["$set"]
                self.assertEqual(set_ops["onboarding_step"], "completed")
                # Completed STAMPS the completed_at timestamp.
                self.assertIn("onboarding_completed_at", set_ops)
        finally:
            restore()

    def test_invalid_step_rejected(self):
        import server

        db = _build_users_db(find_one_result=None)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                r = client.patch(
                    "/api/users/me/onboarding-step",
                    json={"step": "5"},  # 5 is not a valid step
                )
                self.assertEqual(r.status_code, 422)
        finally:
            restore()

    def test_empty_step_rejected(self):
        import server

        db = _build_users_db(find_one_result=None)
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                r = client.patch(
                    "/api/users/me/onboarding-step",
                    json={"step": ""},
                )
                self.assertEqual(r.status_code, 422)
        finally:
            restore()

    def test_user_not_found_returns_404(self):
        import server

        # update_one returns matched_count=0 → user vanished.
        db = _build_users_db(
            find_one_result=None,
            update_one_result=MagicMock(matched_count=0, modified_count=0),
        )
        client, restore = _setup_client()
        try:
            with patch.object(server, "db", db):
                r = client.patch(
                    "/api/users/me/onboarding-step",
                    json={"step": "2"},
                )
                self.assertEqual(r.status_code, 404)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# Register endpoint default — every new user starts at step 1.
# ──────────────────────────────────────────────────────────────────


class TestRegisterInitializesOnboarding(unittest.TestCase):
    """POST /api/auth/register stamps onboarding_step="1" on the
    new user doc. Pinned via inspecting the dict passed to insert_one."""

    def test_new_user_starts_at_step_1(self):
        import server

        db = MagicMock()
        db.users = MagicMock()
        db.users.find_one = AsyncMock(return_value=None)  # email not taken
        db.users.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="u_new")
        )

        with patch.object(server, "db", db):
            client = TestClient(server.app)
            payload = {
                "email": "newgc@example.com",
                "password": "secret",
                "name": "B3 New GC Owner",
                "role": "owner",  # owner doesn't require company_id
            }
            r = client.post("/api/auth/register", json=payload)
            self.assertEqual(r.status_code, 200, r.text)

        # Inspect what insert_one was called with.
        self.assertTrue(db.users.insert_one.called)
        inserted_doc = db.users.insert_one.call_args[0][0]
        self.assertEqual(inserted_doc.get("onboarding_step"), "1")
        # completed_at is explicitly None at registration; gets stamped
        # only when the user PATCHes step="completed" later.
        self.assertIn("onboarding_completed_at", inserted_doc)
        self.assertIsNone(inserted_doc["onboarding_completed_at"])


if __name__ == "__main__":
    unittest.main()
