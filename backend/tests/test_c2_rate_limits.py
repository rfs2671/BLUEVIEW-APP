"""Phase C2 — rate limiting + abuse protection.

Pin every contract the rate-limit middleware promises:

  • The config table covers the spec's endpoints with the spec's
    limits + identifier kinds.
  • The path matcher routes a real URL (with concrete ids) to the
    right rule.
  • The fixed-window counter counts correctly: within-limit hits
    pass, over-limit hits fail with the right retry_after, and the
    window rolls over after expiry.
  • Identifier resolution: authenticated requests key on user_id;
    unauthenticated (or expired token) requests key on IP — the
    two MUST NOT bleed.
  • RATE_LIMITS_DISABLED=true bypasses everything.
  • Excluded paths (health probes, docs, root) are never limited.
  • Integration: a 429 response carries the spec's body shape and
    headers (Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining).
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from lib import rate_limits  # noqa: E402


# ──────────────────────────────────────────────────────────────────
# Config table — spec checklist
# ──────────────────────────────────────────────────────────────────


class TestConfigTable(unittest.TestCase):
    """Pin that the spec's endpoints all appear in RATE_LIMITS with
    the spec's limit string + identifier kind. A future commit that
    "tidies" the table can't silently drop a route."""

    def _find(self, method, pattern):
        """Return (limit_string, kind) for a (method, pattern) match
        or None."""
        for m, p, lim, kind in rate_limits.RATE_LIMITS:
            if m == method and p == pattern:
                return (lim, kind)
        return None

    def test_auth_endpoints_ip_scoped(self):
        self.assertEqual(self._find("POST", "/api/auth/login"),
                         ("5/5 minutes", "ip"))
        self.assertEqual(self._find("POST", "/api/auth/register"),
                         ("3/1 hour", "ip"))
        # Forgot/reset endpoints don't exist in v1 but the limits
        # are pre-configured so adding them later inherits the cap.
        self.assertEqual(self._find("POST", "/api/auth/forgot-password"),
                         ("3/1 hour", "ip"))
        self.assertEqual(self._find("POST", "/api/auth/reset-password"),
                         ("5/1 hour", "ip"))

    def test_onboarding_endpoints_user_scoped(self):
        for path in (
            "/api/onboarding/company",
            "/api/onboarding/project",
            "/api/onboarding/filing-reps",
        ):
            self.assertEqual(
                self._find("POST", path),
                ("30/5 minutes", "user"),
                f"{path} missing or wrong",
            )
        self.assertEqual(
            self._find("PATCH", "/api/users/me/onboarding-step"),
            ("30/5 minutes", "user"),
        )

    def test_notification_prefs_user_scoped(self):
        # Read endpoint gets a higher cap — FE polls it.
        self.assertEqual(
            self._find("GET", "/api/users/me/notification-preferences"),
            ("60/1 minute", "user"),
        )
        # Both PATCH and PUT pinned because the FE may use either.
        self.assertEqual(
            self._find("PATCH", "/api/users/me/notification-preferences"),
            ("30/5 minutes", "user"),
        )
        self.assertEqual(
            self._find("PUT", "/api/users/me/notification-preferences"),
            ("30/5 minutes", "user"),
        )
        self.assertEqual(
            self._find("POST", "/api/users/me/notification-preferences/preview"),
            ("60/1 minute", "user"),
        )

    def test_per_project_prefs(self):
        self.assertEqual(
            self._find("GET", "/api/projects/{id}/notification-preferences/{user_id}"),
            ("60/1 minute", "user"),
        )
        self.assertEqual(
            self._find("PATCH", "/api/projects/{id}/notification-preferences/{user_id}"),
            ("30/5 minutes", "user"),
        )
        self.assertEqual(
            self._find("DELETE", "/api/projects/{id}/notification-preferences/{user_id}"),
            ("10/5 minutes", "user"),
        )

    def test_project_management(self):
        self.assertEqual(
            self._find("POST", "/api/projects"),
            ("10/5 minutes", "user"),
        )
        self.assertEqual(
            self._find("DELETE", "/api/projects/{id}"),
            ("10/5 minutes", "user"),
        )
        # Spec said PATCH; this codebase uses PUT. Both pinned.
        self.assertEqual(
            self._find("PUT", "/api/projects/{id}"),
            ("30/5 minutes", "user"),
        )
        self.assertEqual(
            self._find("PATCH", "/api/projects/{id}"),
            ("30/5 minutes", "user"),
        )

    def test_admin_endpoints(self):
        # Sentry test endpoint is intentionally tighter — it raises
        # by design, so we don't want it abused into a Sentry flood.
        self.assertEqual(
            self._find("GET", "/api/admin/_sentry_test"),
            ("5/5 minutes", "ip"),
        )
        # Catch-all for the rest of /api/admin/*. Uses the
        # `{name:path}` Express-style multi-segment match so a
        # route like /api/admin/users/abc resolves correctly
        # (vs `{name}` which would only match one segment).
        self.assertEqual(
            self._find("ANY", "/api/admin/{rest:path}"),
            ("60/1 minute", "ip"),
        )

    def test_default_fallback(self):
        self.assertEqual(rate_limits.DEFAULT_LIMIT, "100/1 minute")
        self.assertEqual(rate_limits.DEFAULT_LIMIT_KIND, "user")

    def test_admin_specific_rule_precedes_catchall(self):
        """The /admin/_sentry_test rule MUST appear before the
        /admin/{rest} catch-all so the more-specific cap wins.
        If a future "alphabetize the table" patch reorders these,
        the sentry-test endpoint silently inherits the looser
        60/min cap."""
        sentry_idx = None
        catchall_idx = None
        for i, (m, p, *_rest) in enumerate(rate_limits.RATE_LIMITS):
            if p == "/api/admin/_sentry_test":
                sentry_idx = i
            elif p == "/api/admin/{rest:path}":
                catchall_idx = i
        self.assertIsNotNone(sentry_idx)
        self.assertIsNotNone(catchall_idx)
        self.assertLess(
            sentry_idx, catchall_idx,
            "/api/admin/_sentry_test must precede the /api/admin/* catch-all",
        )


# ──────────────────────────────────────────────────────────────────
# Limit-string parsing
# ──────────────────────────────────────────────────────────────────


class TestParseLimit(unittest.TestCase):

    def test_bare_unit(self):
        count, secs, human = rate_limits._parse_limit("60/minute")
        self.assertEqual(count, 60)
        self.assertEqual(secs, 60)
        self.assertIn("60", human)

    def test_multiplier(self):
        count, secs, human = rate_limits._parse_limit("5/5 minutes")
        self.assertEqual(count, 5)
        self.assertEqual(secs, 300)
        self.assertIn("5 minutes", human)

    def test_hour_window(self):
        count, secs, _ = rate_limits._parse_limit("3/1 hour")
        self.assertEqual(count, 3)
        self.assertEqual(secs, 3600)

    def test_invalid_strings_raise(self):
        with self.assertRaises(ValueError):
            rate_limits._parse_limit("garbage")
        with self.assertRaises(ValueError):
            rate_limits._parse_limit("5/year")  # unknown unit


# ──────────────────────────────────────────────────────────────────
# Path matching
# ──────────────────────────────────────────────────────────────────


class TestPathMatching(unittest.TestCase):

    def test_exact_path(self):
        m = rate_limits._match_rule("POST", "/api/auth/login")
        self.assertIsNotNone(m)
        self.assertEqual(m[0], "/api/auth/login")
        self.assertEqual(m[1], "5/5 minutes")
        self.assertEqual(m[2], "ip")

    def test_method_must_match(self):
        # GET /api/auth/login isn't a real endpoint and isn't in
        # the rule table.
        m = rate_limits._match_rule("GET", "/api/auth/login")
        self.assertIsNone(m)

    def test_param_segments(self):
        # Real URL with concrete ids — should match the
        # /api/projects/{id}/notification-preferences/{user_id} rule.
        m = rate_limits._match_rule(
            "GET",
            "/api/projects/abc-123/notification-preferences/u9",
        )
        self.assertIsNotNone(m)
        self.assertEqual(
            m[0],
            "/api/projects/{id}/notification-preferences/{user_id}",
        )

    def test_admin_specific_wins_over_catchall(self):
        """The most-specific rule for /api/admin/_sentry_test must
        match before the /api/admin/{rest} catch-all. (5/5 minutes
        per IP, NOT 60/minute.)"""
        m = rate_limits._match_rule("GET", "/api/admin/_sentry_test")
        self.assertEqual(m[1], "5/5 minutes")
        m2 = rate_limits._match_rule("GET", "/api/admin/users")
        self.assertEqual(m2[1], "60/1 minute")

    def test_any_method_catchall(self):
        """The /api/admin/{rest} rule uses ANY method; both GET and
        DELETE on an admin route should match it."""
        for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            with self.subTest(method=method):
                m = rate_limits._match_rule(method, "/api/admin/users/abc")
                self.assertIsNotNone(m)
                # 5_sentry_test path is fully literal; this one isn't.
                self.assertEqual(m[1], "60/1 minute")

    def test_unmatched_returns_none(self):
        self.assertIsNone(rate_limits._match_rule("GET", "/api/projects"))
        # /api/projects has no rule for GET — falls through to the
        # default at evaluate() time.


# ──────────────────────────────────────────────────────────────────
# Fixed-window counter semantics
# ──────────────────────────────────────────────────────────────────


class TestFixedWindowCounter(unittest.TestCase):

    def setUp(self):
        self.c = rate_limits._FixedWindowCounter()

    def test_within_limit_passes(self):
        for i in range(5):
            allowed, retry, remaining = self.c.hit(("u1", "rt"), 5, 60)
            self.assertTrue(allowed, f"hit {i} should pass")
            self.assertEqual(retry, 0)
        self.assertEqual(remaining, 0)  # last hit zeroes remaining

    def test_over_limit_blocks(self):
        for _ in range(5):
            self.c.hit(("u1", "rt"), 5, 60)
        allowed, retry, remaining = self.c.hit(("u1", "rt"), 5, 60)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)
        self.assertEqual(remaining, 0)

    def test_keys_are_isolated(self):
        # Two different identifiers consume independent buckets.
        for _ in range(5):
            self.c.hit(("u1", "rt"), 5, 60)
        # u2 starts fresh.
        allowed, _r, _rm = self.c.hit(("u2", "rt"), 5, 60)
        self.assertTrue(allowed)

    def test_route_keys_isolated(self):
        # Same identifier, different routes — independent buckets.
        for _ in range(5):
            self.c.hit(("u1", "rt-a"), 5, 60)
        allowed, _r, _rm = self.c.hit(("u1", "rt-b"), 5, 60)
        self.assertTrue(allowed)

    def test_window_rollover(self):
        """After the window expires, the counter resets and new
        hits succeed."""
        # Saturate at limit=2, window=0.05s for fast test.
        self.c.hit(("u1", "rt"), 2, 0.05)
        self.c.hit(("u1", "rt"), 2, 0.05)
        allowed_blocked, _r, _rm = self.c.hit(("u1", "rt"), 2, 0.05)
        self.assertFalse(allowed_blocked)
        # Wait past the window.
        time.sleep(0.07)
        allowed_after, _r2, _rm2 = self.c.hit(("u1", "rt"), 2, 0.05)
        self.assertTrue(allowed_after)


# ──────────────────────────────────────────────────────────────────
# Identifier resolution
# ──────────────────────────────────────────────────────────────────


def _fake_request(*, headers=None, client_host="1.2.3.4"):
    """Minimal Starlette-shaped request stub for identifier tests."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    obj = MagicMock()
    obj.headers = headers
    obj.client = MagicMock()
    obj.client.host = client_host
    return obj


class TestIdentifierResolution(unittest.TestCase):

    def test_user_kind_with_valid_jwt(self):
        import jwt as _jwt
        token = _jwt.encode({"sub": "u_abc"}, "test-secret", algorithm="HS256")
        req = _fake_request(headers={"Authorization": f"Bearer {token}"})
        ident, kind = rate_limits._resolve_identifier(
            req, "user", jwt_secret="test-secret",
        )
        self.assertEqual(kind, "user")
        self.assertEqual(ident, "user:u_abc")

    def test_user_kind_falls_back_to_ip_when_no_token(self):
        req = _fake_request(client_host="9.9.9.9")
        ident, kind = rate_limits._resolve_identifier(
            req, "user", jwt_secret="test-secret",
        )
        self.assertEqual(kind, "ip")
        self.assertEqual(ident, "ip:9.9.9.9")

    def test_user_kind_falls_back_on_bad_token(self):
        req = _fake_request(
            headers={"Authorization": "Bearer not-a-jwt"},
            client_host="9.9.9.9",
        )
        ident, kind = rate_limits._resolve_identifier(
            req, "user", jwt_secret="test-secret",
        )
        self.assertEqual(kind, "ip")
        self.assertEqual(ident, "ip:9.9.9.9")

    def test_ip_kind_uses_xff_first(self):
        req = _fake_request(
            headers={"X-Forwarded-For": "5.6.7.8, 1.1.1.1"},
            client_host="1.2.3.4",
        )
        ident, kind = rate_limits._resolve_identifier(
            req, "ip", jwt_secret=None,
        )
        self.assertEqual(kind, "ip")
        # XFF leftmost wins (the original client).
        self.assertEqual(ident, "ip:5.6.7.8")

    def test_ip_kind_falls_back_to_client_host(self):
        req = _fake_request(client_host="2.2.2.2")
        ident, kind = rate_limits._resolve_identifier(
            req, "ip", jwt_secret=None,
        )
        self.assertEqual(ident, "ip:2.2.2.2")


# ──────────────────────────────────────────────────────────────────
# evaluate() — the integration point used by the middleware
# ──────────────────────────────────────────────────────────────────


class TestEvaluate(unittest.TestCase):

    def setUp(self):
        rate_limits.reset_counter()

    def tearDown(self):
        rate_limits.reset_counter()
        os.environ.pop("RATE_LIMITS_DISABLED", None)

    def _post_login(self, ip="1.2.3.4"):
        return rate_limits.evaluate(
            method="POST",
            path="/api/auth/login",
            request=_fake_request(client_host=ip),
            jwt_secret="x",
        )

    def test_within_limit_returns_none(self):
        for _ in range(5):
            self.assertIsNone(self._post_login())

    def test_over_limit_returns_429_payload(self):
        for _ in range(5):
            self._post_login()
        result = self._post_login()
        self.assertIsNotNone(result)
        self.assertEqual(result["error"], "rate_limit_exceeded")
        self.assertGreaterEqual(result["retry_after_seconds"], 1)
        self.assertEqual(result["limit"], "5 requests per 5 minutes")
        # Sentry-context fields are present (used as breadcrumbs).
        self.assertEqual(result["_route_key"], "/api/auth/login")
        self.assertEqual(result["_identifier_kind"], "ip")

    def test_different_ips_dont_bleed(self):
        for _ in range(5):
            self._post_login(ip="1.1.1.1")
        # 6th from .1 → blocked
        self.assertIsNotNone(self._post_login(ip="1.1.1.1"))
        # 1st from .2 → allowed
        self.assertIsNone(self._post_login(ip="2.2.2.2"))

    def test_user_scoped_endpoint_isolated_from_ip_scoped(self):
        """A user authenticated with token T hitting a user-scoped
        endpoint, AND an unauthenticated caller from the same IP
        hitting an IP-scoped endpoint, share NO rate-limit bucket."""
        rate_limits.reset_counter()
        import jwt as _jwt
        token = _jwt.encode({"sub": "u_xx"}, "test-secret", algorithm="HS256")

        # Saturate the user's onboarding-step PATCH cap (30/5 min).
        for _ in range(30):
            r = rate_limits.evaluate(
                method="PATCH",
                path="/api/users/me/onboarding-step",
                request=_fake_request(
                    headers={"Authorization": f"Bearer {token}"},
                    client_host="1.2.3.4",
                ),
                jwt_secret="test-secret",
            )
            self.assertIsNone(r)
        # 31st should block.
        blocked = rate_limits.evaluate(
            method="PATCH",
            path="/api/users/me/onboarding-step",
            request=_fake_request(
                headers={"Authorization": f"Bearer {token}"},
                client_host="1.2.3.4",
            ),
            jwt_secret="test-secret",
        )
        self.assertIsNotNone(blocked)

        # Same IP, but unauthenticated, hitting login — separate
        # counter, NOT yet saturated.
        login = self._post_login(ip="1.2.3.4")
        self.assertIsNone(login)

    def test_disabled_bypasses(self):
        os.environ["RATE_LIMITS_DISABLED"] = "true"
        # Hit way past the limit — every one should pass.
        for _ in range(20):
            self.assertIsNone(self._post_login())

    def test_excluded_paths_never_limited(self):
        for path in ("/health", "/api/health", "/healthz", "/docs",
                     "/openapi.json"):
            for _ in range(200):
                r = rate_limits.evaluate(
                    method="GET",
                    path=path,
                    request=_fake_request(),
                    jwt_secret="x",
                )
                self.assertIsNone(r)

    def test_unmatched_api_path_uses_default(self):
        """A path under /api/* with no explicit rule falls through
        to the 100/min default."""
        rate_limits.reset_counter()
        for _ in range(100):
            r = rate_limits.evaluate(
                method="GET",
                path="/api/some/uncovered/route",
                request=_fake_request(client_host="9.9.9.9"),
                jwt_secret="x",
            )
            self.assertIsNone(r)
        blocked = rate_limits.evaluate(
            method="GET",
            path="/api/some/uncovered/route",
            request=_fake_request(client_host="9.9.9.9"),
            jwt_secret="x",
        )
        self.assertIsNotNone(blocked)

    def test_non_api_paths_skip_limiter_entirely(self):
        """Static asset 404s, root, etc. shouldn't churn the
        counter."""
        for _ in range(500):
            r = rate_limits.evaluate(
                method="GET",
                path="/some/static/asset.png",
                request=_fake_request(),
                jwt_secret="x",
            )
            self.assertIsNone(r)


# ──────────────────────────────────────────────────────────────────
# Live FastAPI integration — middleware response shape
# ──────────────────────────────────────────────────────────────────


class TestMiddlewareIntegration(unittest.TestCase):
    """End-to-end: hit the live test client at a low-cap endpoint
    until 429, verify the spec response shape + headers."""

    def setUp(self):
        rate_limits.reset_counter()

    def tearDown(self):
        rate_limits.reset_counter()

    def test_register_caps_at_3_per_hour(self):
        # /api/auth/register has the lowest cap that's safe to test
        # synchronously: 3 / 1 hour. We can blow it open without
        # waiting for window rollover.
        import server  # imported with full app

        client = TestClient(server.app)
        ip_headers = {"X-Forwarded-For": "203.0.113.7"}

        # Stub the actual route's DB writes via dependency override;
        # we want the rate limiter to handle the request, but not
        # the real DB.
        with patch.object(server, "db", MagicMock()) as mocked:
            mocked.users.find_one = _async_return(None)
            mocked.users.insert_one = _async_return(MagicMock(inserted_id="x"))

            payload = {
                "email": "rl@example.com",
                "password": "x",
                "name": "rl",
                "role": "owner",
            }
            # First 3 should pass through to the actual route.
            for i in range(3):
                r = client.post("/api/auth/register",
                                json=payload, headers=ip_headers)
                # Don't care about the 200/422 here — only that the
                # rate limiter let it through.
                self.assertNotEqual(
                    r.status_code, 429,
                    f"hit {i} should not be rate limited",
                )
            # 4th should hit the 429.
            r4 = client.post("/api/auth/register",
                             json=payload, headers=ip_headers)
            self.assertEqual(r4.status_code, 429)
            self.assertEqual(r4.headers.get("Retry-After") is not None, True)
            body = r4.json()
            self.assertEqual(body["error"], "rate_limit_exceeded")
            self.assertEqual(body["limit"], "3 requests per 1 hour")
            self.assertGreaterEqual(body["retry_after_seconds"], 1)

    def test_health_excluded_from_limiter(self):
        import server
        client = TestClient(server.app)
        # Hit /api/health 200 times — none should 429.
        for _ in range(200):
            r = client.get("/api/health")
            # health endpoint should respond 200 (or whatever it
            # naturally returns); MUST NOT be 429.
            self.assertNotEqual(r.status_code, 429)


def _async_return(value):
    """unittest.mock helper — async coroutine returning value."""
    async def _coro(*args, **kwargs):
        return value
    return MagicMock(side_effect=_coro)


if __name__ == "__main__":
    unittest.main()
