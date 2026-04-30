"""MR.9 — admin endpoints for notification observability + manual resend.

Coverage:
  • GET /admin/notifications:
      - Owner-tier auth gate (admin role → 403)
      - Filters: trigger_type, status, permit_renewal_id, date range
      - Invalid trigger_type / status → 400
      - Invalid ISO-8601 date → 400
      - Pagination envelope
  • POST /admin/notifications/{id}/resend:
      - Owner-tier auth gate
      - 404 when notification missing
      - 404 when underlying renewal missing
      - Happy path: re-renders + calls send_notification, writes a
        new log entry whose metadata.resent_from_notification_id
        points back to the original.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
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


def _make_cursor(items):
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.skip = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.__aiter__ = _async_iter(items)
    return cursor


def _log_entry(_id="n1", trigger_type="renewal_t_minus_30",
               status="sent", permit_renewal_id="r1"):
    return {
        "_id": _id,
        "permit_renewal_id": permit_renewal_id,
        "trigger_type": trigger_type,
        "recipient": "rep@example.com",
        "subject": "x",
        "status": status,
        "sent_at": datetime.now(timezone.utc),
        "resend_message_id": "msg_1" if status == "sent" else None,
        "error_detail": None,
        "metadata": {},
        "is_deleted": False,
    }


# ── List endpoint auth + filters ───────────────────────────────────

class TestAdminListAuth(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.get("/api/admin/notifications")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_owner_role_accepted(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.notification_log = MagicMock()
        mock_db.notification_log.find = MagicMock(return_value=_make_cursor([]))
        mock_db.notification_log.count_documents = AsyncMock(return_value=0)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/notifications")
            self.assertEqual(resp.status_code, 200, resp.text)
        finally:
            restore()


class TestAdminListFilters(unittest.TestCase):

    def test_filter_by_trigger_type(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.notification_log = MagicMock()
        mock_db.notification_log.find = MagicMock(return_value=_make_cursor([]))
        mock_db.notification_log.count_documents = AsyncMock(return_value=0)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/admin/notifications?trigger_type=filing_stuck"
                )
            self.assertEqual(resp.status_code, 200)
            query = mock_db.notification_log.find.call_args.args[0]
            self.assertEqual(query["trigger_type"], "filing_stuck")
        finally:
            restore()

    def test_invalid_trigger_type_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/admin/notifications?trigger_type=bogus"
                )
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()

    def test_invalid_status_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/notifications?status=bogus")
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()

    def test_filter_by_renewal_id(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.notification_log = MagicMock()
        mock_db.notification_log.find = MagicMock(return_value=_make_cursor([]))
        mock_db.notification_log.count_documents = AsyncMock(return_value=0)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/admin/notifications?permit_renewal_id=r99"
                )
            self.assertEqual(resp.status_code, 200)
            query = mock_db.notification_log.find.call_args.args[0]
            self.assertEqual(query["permit_renewal_id"], "r99")
        finally:
            restore()

    def test_invalid_date_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/admin/notifications?sent_after=not-a-date"
                )
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()


class TestAdminListPagination(unittest.TestCase):

    def test_envelope_shape(self):
        import server
        client, restore = _setup_client(role="owner")
        items = [_log_entry(_id=f"n_{i}") for i in range(3)]
        mock_db = MagicMock()
        mock_db.notification_log = MagicMock()
        mock_db.notification_log.find = MagicMock(return_value=_make_cursor(items))
        mock_db.notification_log.count_documents = AsyncMock(return_value=10)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/admin/notifications?limit=3&skip=0"
                )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(len(body["items"]), 3)
            self.assertEqual(body["total"], 10)
            self.assertTrue(body["has_more"])
        finally:
            restore()


# ── Resend endpoint ────────────────────────────────────────────────

class TestAdminResend(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.post("/api/admin/notifications/n1/resend")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_404_when_notification_missing(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.notification_log = MagicMock()
        mock_db.notification_log.find_one = AsyncMock(return_value=None)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post("/api/admin/notifications/n_missing/resend")
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_404_when_underlying_renewal_missing(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.notification_log = MagicMock()
        mock_db.notification_log.find_one = AsyncMock(
            return_value=_log_entry(),
        )
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value=None)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post("/api/admin/notifications/n1/resend")
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_happy_path_writes_new_log_entry(self):
        import server
        client, restore = _setup_client(role="owner")
        original = _log_entry(_id="n1", trigger_type="renewal_t_minus_30",
                              status="failed")
        mock_db = MagicMock()
        mock_db.notification_log = MagicMock()
        # find_one is called twice: once for original lookup, once
        # for the idempotency check inside send_notification.
        mock_db.notification_log.find_one = AsyncMock(
            side_effect=[original, None],
        )
        insert_result = MagicMock()
        insert_result.inserted_id = "new_log_id"
        mock_db.notification_log.insert_one = AsyncMock(return_value=insert_result)

        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value={
            "_id": "r1", "company_id": "co_a", "project_id": "p1",
            "permit_dob_log_id": "dl1",
            "current_expiration": "2026-04-01",
        })
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(return_value={
            "_id": "p1", "name": "Test", "address": "1 Main",
        })
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find_one = AsyncMock(return_value={
            "_id": "dl1", "job_number": "B00736930", "work_type": "Plumbing",
        })
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a", "filing_reps": [{"email": "rep@example.com"}],
        })
        mock_db.users = MagicMock()
        mock_db.users.find_one = AsyncMock(return_value=None)

        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post("/api/admin/notifications/n1/resend")
            self.assertEqual(resp.status_code, 200, resp.text)
            # New log entry was written.
            mock_db.notification_log.insert_one.assert_awaited_once()
            inserted = mock_db.notification_log.insert_one.await_args.args[0]
            # Metadata back-references the original.
            self.assertEqual(
                inserted["metadata"]["resent_from_notification_id"], "n1",
            )
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
