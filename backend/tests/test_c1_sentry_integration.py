"""Phase C1 — Sentry error tracking integration.

Pin contracts for the Sentry init + per-request tagging + PII
scrubbing + admin health-check endpoint.

We don't actually ship events at test time (that would burn the
free-tier quota and require a real DSN). Instead the tests
exercise the pure-Python helpers that run inside Sentry's
before_send hook, plus a static-source pin on the requirements
file + the auth tagging hook.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


# ──────────────────────────────────────────────────────────────────
# Graceful degradation when DSN missing
# ──────────────────────────────────────────────────────────────────


class TestSentryGracefulDegradation(unittest.TestCase):
    """The whole point: no DSN env var must NOT crash the server.
    The full pytest suite runs without sentry-sdk installed AND
    without SENTRY_DSN — every other test in this repo would
    already fail if the import or init were strict."""

    def test_server_imports_without_sentry(self):
        """Already exercised by every other test loading server.py.
        Smoke-assert it explicitly so a future regression that adds
        a strict import lands on this test."""
        import server
        self.assertTrue(hasattr(server, "_SENTRY_AVAILABLE"))
        # In the local pytest environment, sentry-sdk isn't
        # installed so the module's _SENTRY_AVAILABLE flips False.
        # The flag itself must always exist regardless.
        self.assertIsInstance(server._SENTRY_AVAILABLE, bool)

    def test_sentry_set_user_context_noops_when_disabled(self):
        """The auth-time tagging helper must noop when Sentry is
        disabled. Otherwise every authenticated request in local
        dev would explode."""
        import server
        # Force-disable so this test doesn't depend on SDK install state.
        with patch.object(server, "_SENTRY_AVAILABLE", False), \
             patch.object(server, "sentry_sdk", None):
            # Should NOT raise.
            server._sentry_set_user_context({"id": "u1", "company_id": "co"})

    def test_no_sentry_env_var_does_not_set_dsn(self):
        """Pin: SENTRY_DSN env var read at import. Empty == disabled."""
        import server
        # If the test environment somehow had a DSN, we wouldn't
        # disable Sentry. The pin: the SENTRY_DSN constant equals
        # whatever os.environ.get returned at import time; it
        # MUST default to "" (not None, not crash) when unset.
        self.assertIsInstance(server.SENTRY_DSN, str)


# ──────────────────────────────────────────────────────────────────
# PII scrubbing via _sentry_redact_request_body
# ──────────────────────────────────────────────────────────────────


class TestSentryPIIScrubbing(unittest.TestCase):
    """The before_send hook must redact request bodies for paths
    that carry credentials or preference docs."""

    def test_redacts_auth_login_body(self):
        import server
        event = {
            "request": {
                "url": "https://api.levelog.com/api/auth/login",
                "data": {"email": "u@x.com", "password": "secret-plain-text"},
                "body": '{"email":"u@x.com","password":"secret-plain-text"}',
                "headers": {"Authorization": "Bearer abc.def.ghi"},
            }
        }
        scrubbed = server._sentry_redact_request_body(event)
        self.assertEqual(scrubbed["request"]["data"], "[redacted by levelog scrubber]")
        self.assertEqual(scrubbed["request"]["body"], "[redacted by levelog scrubber]")
        # Authorization header always stripped, even outside auth paths.
        self.assertEqual(scrubbed["request"]["headers"]["Authorization"], "[redacted]")

    def test_redacts_auth_register_body(self):
        import server
        event = {
            "request": {
                "url": "https://api.levelog.com/api/auth/register",
                "data": {"email": "u@x.com", "password": "another-secret"},
                "body": '{"password":"another-secret"}',
                "headers": {},
            }
        }
        scrubbed = server._sentry_redact_request_body(event)
        self.assertNotIn("another-secret", scrubbed["request"]["data"])
        self.assertNotIn("another-secret", scrubbed["request"]["body"])

    def test_redacts_notification_preferences_body(self):
        """Notification preference docs may carry PII fields in
        future releases (channel routes, custom severity overrides
        keyed on email destinations). Scrub defensively."""
        import server
        event = {
            "request": {
                "url": "https://api.levelog.com/api/users/me/notification-preferences",
                "data": {"signal_kind_overrides": {}},
                "headers": {},
            }
        }
        scrubbed = server._sentry_redact_request_body(event)
        self.assertEqual(scrubbed["request"]["data"], "[redacted by levelog scrubber]")

    def test_does_not_redact_non_sensitive_paths(self):
        import server
        event = {
            "request": {
                "url": "https://api.levelog.com/api/projects",
                "data": {"name": "My Project"},
                "headers": {},
            }
        }
        scrubbed = server._sentry_redact_request_body(event)
        self.assertEqual(scrubbed["request"]["data"], {"name": "My Project"})

    def test_strips_authorization_header_globally(self):
        """Even on non-auth paths, the Authorization header (Bearer
        token) must be stripped. A leaked JWT in a Sentry event
        would let an attacker impersonate the user."""
        import server
        event = {
            "request": {
                "url": "https://api.levelog.com/api/projects",
                "data": {"name": "Foo"},
                "headers": {
                    "Authorization": "Bearer eyJ.token.value",
                    "Cookie": "sid=abc; session=def",
                    "X-API-Key": "api_key_value",
                    "Content-Type": "application/json",
                },
            }
        }
        scrubbed = server._sentry_redact_request_body(event)
        h = scrubbed["request"]["headers"]
        self.assertEqual(h["Authorization"], "[redacted]")
        self.assertEqual(h["Cookie"], "[redacted]")
        self.assertEqual(h["X-API-Key"], "[redacted]")
        # Content-Type is fine to keep; it's not sensitive.
        self.assertEqual(h["Content-Type"], "application/json")

    def test_redacts_query_string_on_sensitive_paths(self):
        import server
        event = {
            "request": {
                "url": "https://api.levelog.com/api/auth/reset?token=secret",
                "data": {},
                "query_string": "token=secret",
                "headers": {},
            }
        }
        scrubbed = server._sentry_redact_request_body(event)
        self.assertEqual(
            scrubbed["request"]["query_string"],
            "[redacted by levelog scrubber]",
        )


# ──────────────────────────────────────────────────────────────────
# Drop-event hook for 404s + bots
# ──────────────────────────────────────────────────────────────────


class TestSentryDropFilter(unittest.TestCase):

    def test_drops_404_from_response_context(self):
        import server
        event = {
            "request": {"url": "/missing", "headers": {}},
            "contexts": {"response": {"status_code": 404}},
        }
        self.assertTrue(server._sentry_should_drop_event(event))

    def test_drops_404_from_httpexception_value(self):
        import server
        event = {
            "request": {"url": "/missing", "headers": {}},
            "exception": {
                "values": [
                    {"type": "HTTPException", "value": "404: Not Found"},
                ],
            },
        }
        self.assertTrue(server._sentry_should_drop_event(event))

    def test_drops_known_bot_ua(self):
        import server
        for bot_ua in (
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "AhrefsBot/7.0",
            "Twitterbot/1.0",
            "facebookexternalhit/1.1",
            "Mozilla/5.0 (HeadlessChrome/91)",
        ):
            with self.subTest(ua=bot_ua):
                event = {
                    "request": {"url": "/api/projects", "headers": {"user-agent": bot_ua}},
                }
                self.assertTrue(
                    server._sentry_should_drop_event(event),
                    f"bot UA {bot_ua!r} should drop",
                )

    def test_does_not_drop_real_users(self):
        import server
        event = {
            "request": {
                "url": "/api/projects",
                "headers": {
                    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                },
            },
        }
        self.assertFalse(server._sentry_should_drop_event(event))

    def test_before_send_drops_404(self):
        import server
        event = {
            "request": {"url": "/missing", "headers": {}},
            "contexts": {"response": {"status_code": 404}},
        }
        self.assertIsNone(server._sentry_before_send(event, None))

    def test_before_send_returns_event_for_real_errors(self):
        import server
        event = {
            "request": {
                "url": "/api/projects",
                "headers": {"user-agent": "Mozilla/5.0"},
                "data": {"foo": "bar"},
            },
        }
        out = server._sentry_before_send(event, None)
        self.assertIsNotNone(out)
        # Authorization stripping is the only mutation on a non-auth
        # path; data passes through.
        self.assertEqual(out["request"]["data"], {"foo": "bar"})


# ──────────────────────────────────────────────────────────────────
# Per-request user / company tagging
# ──────────────────────────────────────────────────────────────────


class TestSentryUserContextTagging(unittest.TestCase):

    def test_set_user_pushes_id_company_role(self):
        import server
        # Force "Sentry available" so the helper actually invokes
        # the SDK (mocked).
        fake_sdk = MagicMock()
        with patch.object(server, "_SENTRY_AVAILABLE", True), \
             patch.object(server, "sentry_sdk", fake_sdk):
            server._sentry_set_user_context({
                "id": "u_1",
                "company_id": "co_a",
                "role": "admin",
            })
        # set_user called with id (no email — sendDefaultPii=False).
        fake_sdk.set_user.assert_called_once()
        kwargs = fake_sdk.set_user.call_args[0][0]
        self.assertEqual(kwargs["id"], "u_1")

        # set_tag called for company_id + role.
        tag_calls = [c.args for c in fake_sdk.set_tag.call_args_list]
        self.assertIn(("company_id", "co_a"), tag_calls)
        self.assertIn(("role", "admin"), tag_calls)

    def test_set_user_swallows_sdk_exceptions(self):
        """Tagging is purely additive — must never bubble out of
        get_current_user."""
        import server
        boom = MagicMock()
        boom.set_user.side_effect = RuntimeError("sdk boom")
        with patch.object(server, "_SENTRY_AVAILABLE", True), \
             patch.object(server, "sentry_sdk", boom):
            # Should NOT raise.
            server._sentry_set_user_context({"id": "u_1"})


# ──────────────────────────────────────────────────────────────────
# /api/admin/_sentry_test endpoint
# ──────────────────────────────────────────────────────────────────


class TestSentryTestEndpoint(unittest.TestCase):
    """Admin-only endpoint that intentionally raises so an operator
    can verify Sentry capture after deploy."""

    def setUp(self):
        import server
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def tearDown(self):
        import server
        server.app.dependency_overrides.clear()

    def _login_as(self, role):
        import server

        async def _fake_user():
            return {"id": "u1", "_id": "u1", "role": role, "company_id": "co_a"}

        server.app.dependency_overrides[server.get_current_user] = _fake_user

    def test_admin_can_hit_endpoint_and_it_500s(self):
        self._login_as("admin")
        resp = self.client.get("/api/admin/_sentry_test")
        self.assertEqual(resp.status_code, 500)

    def test_owner_can_hit_endpoint(self):
        self._login_as("owner")
        resp = self.client.get("/api/admin/_sentry_test")
        self.assertEqual(resp.status_code, 500)

    def test_non_admin_rejected(self):
        self._login_as("worker")
        resp = self.client.get("/api/admin/_sentry_test")
        self.assertEqual(resp.status_code, 403)


# ──────────────────────────────────────────────────────────────────
# Static-source pins
# ──────────────────────────────────────────────────────────────────


class TestSentryRequirements(unittest.TestCase):
    """Pin that the production requirements file lists sentry-sdk.
    A regression that drops it means Railway will deploy without
    Sentry on next push, silently breaking error tracking."""

    def test_sentry_sdk_in_requirements(self):
        path = _REPO / "requirements.txt"
        text = path.read_text(encoding="utf-8")
        self.assertIn("sentry-sdk", text)
        # FastAPI extra is required for the framework integration
        # we wire in server.py.
        self.assertIn("[fastapi]", text)


class TestSentryFrontendPins(unittest.TestCase):
    """Pin the frontend Sentry surface — file present, init wired
    in _layout.jsx, AuthContext sets/clears user, ErrorBoundary
    forwards to Sentry."""

    def setUp(self):
        self.frontend = _REPO / "frontend"

    def test_sentry_helper_module_present(self):
        path = self.frontend / "src" / "lib" / "sentry.js"
        self.assertTrue(path.exists(), str(path))
        text = path.read_text(encoding="utf-8")
        self.assertIn("export function initSentry", text)
        self.assertIn("export function setSentryUser", text)
        self.assertIn("export function clearSentryUser", text)
        self.assertIn("export function captureException", text)
        # DSN read from EXPO_PUBLIC_SENTRY_DSN.
        self.assertIn("EXPO_PUBLIC_SENTRY_DSN", text)
        # Sample rates per spec.
        self.assertIn("tracesSampleRate: 0.1", text)
        self.assertIn("replaysSessionSampleRate: 0", text)

    def test_sentry_react_in_package_json(self):
        path = self.frontend / "package.json"
        text = path.read_text(encoding="utf-8")
        self.assertIn("@sentry/react", text)

    def test_layout_initializes_sentry_at_top_level(self):
        path = self.frontend / "app" / "_layout.jsx"
        text = path.read_text(encoding="utf-8")
        self.assertIn("import { initSentry", text)
        self.assertIn("initSentry()", text)

    def test_error_boundary_reports_to_sentry(self):
        path = self.frontend / "app" / "_layout.jsx"
        text = path.read_text(encoding="utf-8")
        self.assertIn("sentryCaptureException", text)
        # componentDidCatch is the React hook we forward from.
        self.assertIn("componentDidCatch", text)

    def test_unhandled_promise_rejection_listener(self):
        path = self.frontend / "src" / "lib" / "sentry.js"
        text = path.read_text(encoding="utf-8")
        self.assertIn("unhandledrejection", text)

    def test_auth_context_sets_sentry_user_on_login(self):
        path = self.frontend / "src" / "context" / "AuthContext.js"
        text = path.read_text(encoding="utf-8")
        self.assertIn("setSentryUser", text)
        self.assertIn("clearSentryUser", text)
        # company_name is in the tag payload.
        self.assertIn("company_name", text)


if __name__ == "__main__":
    unittest.main()
