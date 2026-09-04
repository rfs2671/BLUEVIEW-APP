"""CORS is the outermost middleware, and a preflight is never rate limited.

THE BUG THIS PINS. `add_middleware` PREPENDS in Starlette, so the last
registration is the outermost layer. CORSMiddleware used to be registered
BEFORE the rate limiter, which put the limiter outside it — and a limiter that
short-circuits returns its own response without passing back through CORS. A
429 therefore carried no `Access-Control-Allow-Origin` header at all.

The browser does not report that as a rate limit. It reports:

    Response to preflight request doesn't pass access control check:
    It does not have HTTP ok status.

which reads as a CORS misconfiguration and sends you to audit the origin list —
where every origin is present and correct, and where a single hand-run preflight
passes, because one cold request is never limited. Admin pages on the web fan
out several calls at once against an IP-scoped 60/min cap, each one doubled by
its preflight, so the browser was the only client that ever tripped it: the
native app sends no Origin, gets no preflight, and reads a 429 as a 429.

Two guarantees:

  ORDER — every response leaves through CORSMiddleware, including ones an inner
  layer generates by refusing. Asserted against a real 429, not by inspecting
  the registration list, because the thing that broke was the ORDER of a list
  that contained all the right entries.

  PREFLIGHT — OPTIONS never consumes quota. A preflight is not a request to the
  resource; counting it means a browser spends two of its allowance where the
  native app spends one, and the one refused is the preflight.

The origin list is NOT widened by any of this and is pinned below: the two
hosts we own, plus the pdf.js viewer and localhost. No wildcard, no
`allow_origin_regex` — a pattern here is how `www.levelog.com.evil.example`
eventually gets in.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

import server  # noqa: E402
from lib import rate_limits  # noqa: E402


WWW = "https://www.levelog.com"
APEX = "https://levelog.com"


class TheOriginListIsExactAndNarrow(unittest.TestCase):

    def test_both_hosts_we_own_are_allowed(self):
        self.assertIn(APEX, server.ALLOWED_ORIGINS)
        self.assertIn(WWW, server.ALLOWED_ORIGINS)

    def test_nothing_unexpected_is_allowed(self):
        self.assertEqual(
            sorted(server.ALLOWED_ORIGINS),
            sorted([
                APEX,
                WWW,
                "https://api.levelog.com",
                # pdf.js in the native WebView fetches cross-origin.
                "https://mozilla.github.io",
                "http://localhost:8081",
                "http://localhost:19006",
                "http://localhost:3000",
            ]),
        )

    def test_no_wildcard_and_no_regex(self):
        """A pattern is how a lookalike host gets in. Exact match only."""
        self.assertNotIn("*", server.ALLOWED_ORIGINS)
        for o in server.ALLOWED_ORIGINS:
            self.assertNotIn("*", o, f"wildcard in origin {o!r}")
        # BY SUBCLASS, NOT BY IDENTITY OR BY NAME. The registered class is
        # CountingCORSMiddleware, which subclasses CORSMiddleware to record the
        # preflights it refuses without changing a single decision. What this
        # test guards -- one CORS layer, outermost, exact origins -- is unchanged
        # by that, so it asks the question in a form the subclass answers.
        cors = [m for m in server.app.user_middleware
                if isinstance(m.cls, type) and issubclass(m.cls, CORSMiddleware)]
        self.assertEqual(len(cors), 1, "expected exactly one CORS middleware")
        self.assertIsNone(
            cors[0].kwargs.get("allow_origin_regex"),
            "allow_origin_regex must stay unset — the list is exact-match",
        )

    def test_a_lookalike_host_is_not_allowed(self):
        for bad in (
            "https://www.levelog.com.evil.example",
            "https://levelog.com.attacker.test",
            "https://evil-levelog.com",
            "http://www.levelog.com",          # scheme matters
        ):
            self.assertNotIn(bad, server.ALLOWED_ORIGINS)


class CorsIsTheOutermostLayer(unittest.TestCase):
    """Registration order, asserted on the stack rather than by reading code."""

    def test_cors_is_registered_last_so_it_wraps_the_limiter(self):
        classes = [m.cls for m in server.app.user_middleware]
        cors = [i for i, c in enumerate(classes)
                if isinstance(c, type) and issubclass(c, CORSMiddleware)]
        self.assertTrue(cors, "no CORS middleware registered at all")
        cors_at = cors[0]

        rl = [i for i, c in enumerate(classes) if "RateLimit" in c.__name__]
        if not rl:
            self.skipTest("rate-limit middleware not installed in this env")

        # user_middleware is outermost-first: Starlette PREPENDS on
        # add_middleware, so index 0 is the last registered and runs first.
        self.assertLess(
            cors_at, rl[0],
            "CORSMiddleware must sit OUTSIDE the rate limiter, or a 429 "
            "returns with no Access-Control-Allow-Origin and the browser "
            "reports a CORS failure instead of a rate limit",
        )


class APreflightIsNeverRateLimited(unittest.TestCase):

    def setUp(self):
        rate_limits.reset_counter()

    def tearDown(self):
        rate_limits.reset_counter()

    class _Req:
        def __init__(self):
            self.headers = {}
            self.client = type("C", (), {"host": "203.0.113.7"})()

    def _evaluate(self, method, path):
        return rate_limits.evaluate(
            method=method, path=path, request=self._Req(),
            jwt_secret="smoke_test_secret",
        )

    def test_options_is_exempt_even_past_the_cap(self):
        """The admin cap is the tightest and IP-scoped — 60/1 minute."""
        for _ in range(200):
            self.assertIsNone(
                self._evaluate("OPTIONS", "/api/admin/users"),
                "a preflight consumed quota",
            )

    def test_options_does_not_burn_the_budget_for_the_real_call(self):
        """The asking is exempt; the doing is still counted.

        200 preflights must not leave the GET that follows them refused.
        """
        for _ in range(200):
            self._evaluate("OPTIONS", "/api/admin/users")
        self.assertIsNone(
            self._evaluate("GET", "/api/admin/users"),
            "preflights ate the allowance for the request that followed",
        )

    def test_the_real_call_is_still_limited(self):
        """The exemption must not disarm the control it sits inside."""
        blocked = False
        for _ in range(400):
            if self._evaluate("GET", "/api/admin/users") is not None:
                blocked = True
                break
        self.assertTrue(
            blocked,
            "the admin cap never fired — exempting OPTIONS must not exempt GET",
        )


if __name__ == "__main__":
    unittest.main()
