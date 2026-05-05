"""Phase B1c — preview endpoint + project summary + DELETE endpoint
behavioral coverage.

Tests in this file:

  Preview endpoint
    • Happy path: returns aggregates broken into immediate / digest /
      feed buckets.
    • Tenant-scoping: pipeline filters by company_id.
    • Site-mode device → 403.
    • No company_id → empty payload, no Mongo touch.
    • Invalid body → 400 with structured errors.
    • days clamped to [1, 30].
    • Cache hit returns the same response without re-running the
      aggregation.
    • Cache key separates preferences with different shapes.

  Project summary endpoint
    • Returns the caller's projects with has_override flags.
    • Tenant-scoped.

  DELETE project preferences
    • Removes the record.
    • Idempotent (delete-twice safe).
    • Auth gate: self can delete; cross-tenant rejected.
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


def _setup_client(*, role="admin", user_id="u1", company_id="co_a", site_mode=False):
    import server
    user = {
        "id": user_id, "_id": user_id, "user_id": user_id,
        "role": role, "company_id": company_id,
        "site_mode": site_mode,
    }
    async def _fake_user():
        return user
    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


class _AsyncCursor:
    """Async-iterable wrapper for find() mocks."""
    def __init__(self, items):
        self._items = items
    def __aiter__(self):
        async def _gen():
            for it in self._items:
                yield it
        return _gen()
    def sort(self, *args, **kwargs):
        return self
    def limit(self, n):
        self._items = self._items[:n]
        return self


# ──────────────────────────────────────────────────────────────────
# Preview endpoint
# ──────────────────────────────────────────────────────────────────


class TestPreviewHappyPath(unittest.TestCase):

    def _build_db(self, *, logs):
        db = MagicMock()
        db.dob_logs = MagicMock()
        db.dob_logs.find = MagicMock(return_value=_AsyncCursor(logs))
        return db

    def test_aggregates_by_delivery_bucket(self):
        import server
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        client, restore = _setup_client(company_id="co_a", user_id="u1")
        # 3 violation_dob (critical) → email/immediate via Critical-only defaults.
        # 2 complaint_311 (info) → feed_only.
        logs = [
            {"signal_kind": "violation_dob", "company_id": "co_a"} for _ in range(3)
        ] + [
            {"signal_kind": "complaint_311", "company_id": "co_a"} for _ in range(2)
        ]
        mock_db = self._build_db(logs=logs)

        # POST with the synthesized Critical-only defaults shape.
        from lib.notification_preferences import (
            default_signal_kind_overrides,
            default_channel_routes_default,
            default_digest_window,
        )
        body = {
            "signal_kind_overrides": default_signal_kind_overrides(),
            "channel_routes_default": default_channel_routes_default(),
            "digest_window": default_digest_window(),
        }

        try:
            with patch.object(server, "db", mock_db):
                resp = client.post(
                    "/api/users/me/notification-preferences/preview",
                    json=body,
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()
            self.assertEqual(data["window_days"], 7)
            self.assertEqual(data["scope"], "user_global")
            self.assertEqual(data["summary"]["immediate_emails"], 3)
            self.assertEqual(data["summary"]["suppressed_signals"], 2)
            self.assertEqual(data["summary"]["total_signals_seen"], 5)
            # Pipeline scoped to caller's company.
            args, _ = mock_db.dob_logs.find.call_args
            query = args[0]
            self.assertEqual(query["company_id"], "co_a")
            self.assertNotIn("project_id", query)
        finally:
            restore()


class TestPreviewProjectScope(unittest.TestCase):
    """When project_id query param is supplied, the endpoint scopes
    dob_logs to the project AND verifies caller has access."""

    def test_project_id_added_to_query_with_auth_check(self):
        import server
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        client, restore = _setup_client(role="admin", company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find = MagicMock(return_value=_AsyncCursor([]))
        # Project lookup for auth check.
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(
            return_value={"_id": "p1", "company_id": "co_a"},
        )
        body = {
            "signal_kind_overrides": {},
            "channel_routes_default": {"critical": [], "warning": [], "info": []},
            "digest_window": {},
        }
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/users/me/notification-preferences/preview?project_id=p1",
                    json=body,
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            args, _ = mock_db.dob_logs.find.call_args
            query = args[0]
            self.assertEqual(query["company_id"], "co_a")
            self.assertEqual(query["project_id"], "p1")
        finally:
            restore()

    def test_project_owned_by_other_company_rejected(self):
        import server
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        # Caller is admin of co_a; project belongs to co_b.
        client, restore = _setup_client(role="admin", company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(
            return_value={"_id": "p_other", "company_id": "co_b"},
        )
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/users/me/notification-preferences/preview?project_id=p_other",
                    json={
                        "signal_kind_overrides": {},
                        "channel_routes_default": {},
                        "digest_window": {},
                    },
                )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


class TestPreviewSiteMode(unittest.TestCase):

    def test_site_mode_device_rejected_403(self):
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        client, restore = _setup_client(site_mode=True)
        try:
            resp = client.post(
                "/api/users/me/notification-preferences/preview",
                json={"signal_kind_overrides": {}},
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


class TestPreviewNoCompanyId(unittest.TestCase):

    def test_no_company_id_returns_empty_payload(self):
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        client, restore = _setup_client(company_id=None, user_id="u1")
        try:
            resp = client.post(
                "/api/users/me/notification-preferences/preview",
                json={
                    "signal_kind_overrides": {},
                    "channel_routes_default": {},
                    "digest_window": {},
                },
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["summary"]["total_signals_seen"], 0)
            self.assertEqual(body["would_receive_email"], [])
        finally:
            restore()


class TestPreviewBodyValidation(unittest.TestCase):

    def test_invalid_delivery_value_rejected_400(self):
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        import server
        client, restore = _setup_client(company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find = MagicMock(return_value=_AsyncCursor([]))
        body = {
            "signal_kind_overrides": {
                "violation_dob": {
                    "channels": ["email"],
                    "delivery": "BOGUS",
                },
            },
        }
        try:
            with patch.object(server, "db", mock_db):
                resp = client.post(
                    "/api/users/me/notification-preferences/preview",
                    json=body,
                )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("errors", resp.json()["detail"])
        finally:
            restore()


class TestPreviewDaysClamping(unittest.TestCase):

    def test_days_zero_clamps_to_one(self):
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        import server
        client, restore = _setup_client(company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find = MagicMock(return_value=_AsyncCursor([]))
        try:
            with patch.object(server, "db", mock_db):
                resp = client.post(
                    "/api/users/me/notification-preferences/preview?days=0",
                    json={"signal_kind_overrides": {}, "channel_routes_default": {}, "digest_window": {}},
                )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["window_days"], 1)
        finally:
            restore()

    def test_days_huge_clamps_to_30(self):
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        import server
        client, restore = _setup_client(company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find = MagicMock(return_value=_AsyncCursor([]))
        try:
            with patch.object(server, "db", mock_db):
                resp = client.post(
                    "/api/users/me/notification-preferences/preview?days=500",
                    json={"signal_kind_overrides": {}, "channel_routes_default": {}, "digest_window": {}},
                )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["window_days"], 30)
        finally:
            restore()


class TestPreviewCache(unittest.TestCase):

    def test_second_call_with_same_body_uses_cache(self):
        """Identical body within the cache TTL → no second Mongo scan.
        Verified via call-count on db.dob_logs.find."""
        import server
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        client, restore = _setup_client(company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find = MagicMock(return_value=_AsyncCursor([
            {"signal_kind": "violation_dob", "company_id": "co_a"},
        ]))
        body = {
            "signal_kind_overrides": {},
            "channel_routes_default": {"critical": ["email"], "warning": [], "info": []},
            "digest_window": {},
        }
        try:
            with patch.object(server, "db", mock_db):
                resp1 = client.post(
                    "/api/users/me/notification-preferences/preview", json=body,
                )
                resp2 = client.post(
                    "/api/users/me/notification-preferences/preview", json=body,
                )
            self.assertEqual(resp1.status_code, 200)
            self.assertEqual(resp2.status_code, 200)
            self.assertEqual(resp1.json(), resp2.json())
            # Mongo find called exactly once (cache hit on second call).
            self.assertEqual(mock_db.dob_logs.find.call_count, 1)
        finally:
            restore()

    def test_different_body_misses_cache(self):
        import server
        from lib.notification_preferences import preview_cache_clear
        preview_cache_clear()
        client, restore = _setup_client(company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find = MagicMock(return_value=_AsyncCursor([]))
        body_a = {
            "signal_kind_overrides": {},
            "channel_routes_default": {"critical": ["email"], "warning": [], "info": []},
            "digest_window": {},
        }
        body_b = {
            "signal_kind_overrides": {},
            # Different routes shape.
            "channel_routes_default": {"critical": ["email"], "warning": ["email"], "info": []},
            "digest_window": {},
        }
        try:
            with patch.object(server, "db", mock_db):
                resp1 = client.post(
                    "/api/users/me/notification-preferences/preview", json=body_a,
                )
                resp2 = client.post(
                    "/api/users/me/notification-preferences/preview", json=body_b,
                )
            self.assertEqual(resp1.status_code, 200)
            self.assertEqual(resp2.status_code, 200)
            # Two cache misses → two Mongo scans.
            self.assertEqual(mock_db.dob_logs.find.call_count, 2)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# Project preferences summary
# ──────────────────────────────────────────────────────────────────


class TestProjectSummary(unittest.TestCase):

    def test_returns_projects_with_override_flags(self):
        import server
        client, restore = _setup_client(company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.projects = MagicMock()
        mock_db.projects.find = MagicMock(return_value=_AsyncCursor([
            {"_id": "p1", "name": "Acme Tower", "address": "123 Main St"},
            {"_id": "p2", "name": "Beta Site", "address": "456 Oak Ave"},
            {"_id": "p3", "name": "Gamma Loft", "address": "789 Elm"},
        ]))
        # Only p2 has a project-scoped record for this user.
        mock_db.notification_preferences = MagicMock()
        mock_db.notification_preferences.find = MagicMock(return_value=_AsyncCursor([
            {"project_id": "p2"},
        ]))
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/users/me/project-preferences-summary",
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()
            self.assertEqual(data["total"], 3)
            by_id = {p["project_id"]: p for p in data["projects"]}
            self.assertFalse(by_id["p1"]["has_override"])
            self.assertTrue(by_id["p2"]["has_override"])
            self.assertFalse(by_id["p3"]["has_override"])
        finally:
            restore()

    def test_no_company_id_returns_empty(self):
        import server
        client, restore = _setup_client(company_id=None, user_id="u1")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/users/me/project-preferences-summary",
                )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"projects": [], "total": 0})
        finally:
            restore()

    def test_site_mode_device_rejected(self):
        client, restore = _setup_client(site_mode=True)
        try:
            resp = client.get(
                "/api/users/me/project-preferences-summary",
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# DELETE project notification preferences
# ──────────────────────────────────────────────────────────────────


class TestDeleteProjectPreferences(unittest.TestCase):

    def test_self_can_delete_own_record(self):
        import server
        client, restore = _setup_client(role="admin", company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.notification_preferences = MagicMock()
        mock_db.notification_preferences.delete_one = AsyncMock(
            return_value=MagicMock(deleted_count=1),
        )
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(
            return_value={"_id": "p1", "company_id": "co_a"},
        )
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/projects/p1/notification-preferences/u1",
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertTrue(resp.json()["deleted"])
        finally:
            restore()

    def test_idempotent_when_no_record(self):
        """Deleting a non-existent record returns 200 with deleted=False.
        Reset-to-user-global called twice in a row should not 404."""
        import server
        client, restore = _setup_client(role="admin", company_id="co_a", user_id="u1")
        mock_db = MagicMock()
        mock_db.notification_preferences = MagicMock()
        mock_db.notification_preferences.delete_one = AsyncMock(
            return_value=MagicMock(deleted_count=0),
        )
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(
            return_value={"_id": "p1", "company_id": "co_a"},
        )
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/projects/p1/notification-preferences/u1",
                )
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["deleted"])
        finally:
            restore()

    def test_cross_tenant_rejected(self):
        import server
        # Caller on co_b; project on co_a; target user u_other.
        client, restore = _setup_client(role="admin", company_id="co_b", user_id="u_caller")
        mock_db = MagicMock()
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(
            return_value={"_id": "p1", "company_id": "co_a"},
        )
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/projects/p1/notification-preferences/u_other",
                )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# Static-source pins
# ──────────────────────────────────────────────────────────────────


class TestB1cRoutePins(unittest.TestCase):

    def test_preview_route_registered(self):
        import server
        found = any(
            "POST" in (r.methods or set())
            and (getattr(r, "path", "") or "").endswith(
                "/users/me/notification-preferences/preview"
            )
            for r in server.app.routes
        )
        self.assertTrue(found)

    def test_summary_route_registered(self):
        import server
        found = any(
            "GET" in (r.methods or set())
            and (getattr(r, "path", "") or "").endswith(
                "/users/me/project-preferences-summary"
            )
            for r in server.app.routes
        )
        self.assertTrue(found)

    def test_delete_project_prefs_route_registered(self):
        import server
        found = any(
            "DELETE" in (r.methods or set())
            and (getattr(r, "path", "") or "").endswith(
                "/projects/{project_id}/notification-preferences/{user_id}"
            )
            for r in server.app.routes
        )
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()
