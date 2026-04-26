"""Egress-guard tests for the server-side HTTP wrapper.

The redirect attack is the highest-stakes test in this file. The
naive guard checks only the initial URL, so a 302 from an allowed
host to an Akamai host would silently route through Akamai. The
redirect-walking guard re-validates every hop. If this test ever
goes red, server-side traffic is at risk of leaking to Akamai.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402

from lib import server_http  # noqa: E402
from lib.server_http import (  # noqa: E402
    ServerHttpClient,
    EgressViolation,
    AKAMAI_BLOCKED_HOSTS,
    SOCRATA_HOSTS,
)


def _run(coro):
    return asyncio.run(coro)


class TestDirectBlocklist(unittest.TestCase):
    """Initial-URL host check fires before any network call."""

    def test_direct_call_to_akamai_host_raises(self):
        async def go():
            async with ServerHttpClient() as c:
                with self.assertRaises(EgressViolation) as ctx:
                    await c.get("https://a810-dobnow.nyc.gov/Publish/Index.html")
                self.assertIn("a810-dobnow.nyc.gov", str(ctx.exception))
                self.assertIn("worker queue", str(ctx.exception).lower())
        _run(go())

    def test_all_blocked_hosts_rejected(self):
        for host in AKAMAI_BLOCKED_HOSTS:
            async def go(h=host):
                async with ServerHttpClient() as c:
                    with self.assertRaises(EgressViolation):
                        await c.get(f"https://{h}/")
            _run(go())

    def test_uppercase_host_still_blocked(self):
        """Hostname comparison must be case-insensitive."""
        async def go():
            async with ServerHttpClient() as c:
                with self.assertRaises(EgressViolation):
                    await c.get("https://A810-DOBNOW.NYC.GOV/Publish/")
        _run(go())

    def test_subdomain_not_in_blocklist_passes_initial_check(self):
        """Only exact host matches are blocked. A future subdomain
        that's not on the list must NOT be falsely blocked here.
        Verifies we're not over-eager."""
        # We use a mock here — we don't actually want to hit the
        # network. The test only proves the host check doesn't raise.
        async def go():
            with patch.object(
                httpx.AsyncClient, "request",
                new=AsyncMock(return_value=httpx.Response(200)),
            ):
                async with ServerHttpClient() as c:
                    resp = await c.get("https://other-subdomain.nyc.gov/")
                    self.assertEqual(resp.status_code, 200)
        _run(go())


class TestRedirectAttack(unittest.TestCase):
    """The high-stakes test: a 302 from an allowed host to an Akamai
    host MUST raise EgressViolation, even with follow_redirects=True.
    Without redirect-chain validation, this is the bypass."""

    def test_default_no_follow_redirects(self):
        """Default behavior: don't follow redirects at all. The 302
        is returned to the caller as a normal response. No bypass
        possible because the redirect was never followed."""
        async def go():
            redirect_response = httpx.Response(
                302,
                headers={"location": "https://a810-dobnow.nyc.gov/secret"},
            )
            with patch.object(
                httpx.AsyncClient, "request",
                new=AsyncMock(return_value=redirect_response),
            ):
                async with ServerHttpClient() as c:
                    # follow_redirects defaults False — wrapper returns
                    # the 302 unchanged, never touching the redirect target
                    resp = await c.get("https://www1.nyc.gov/something")
                    self.assertEqual(resp.status_code, 302)
                    self.assertEqual(
                        resp.headers["location"],
                        "https://a810-dobnow.nyc.gov/secret",
                    )
        _run(go())

    def test_opt_in_follow_redirects_blocks_akamai_hop(self):
        """The actual attack scenario: caller opts into auto-redirect,
        the response is a 302 to an Akamai host, the wrapper MUST
        raise EgressViolation before issuing the second request."""
        async def go():
            redirect_response = httpx.Response(
                302,
                headers={"location": "https://a810-dobnow.nyc.gov/secret"},
            )
            inner_request = AsyncMock(return_value=redirect_response)
            with patch.object(httpx.AsyncClient, "request", new=inner_request):
                async with ServerHttpClient() as c:
                    with self.assertRaises(EgressViolation) as ctx:
                        await c.get(
                            "https://www1.nyc.gov/something",
                            follow_redirects=True,
                        )
                    self.assertIn("a810-dobnow.nyc.gov", str(ctx.exception))
            # Inner client was called exactly once (for the initial
            # request that produced the 302). The blocked second hop
            # never went out.
            self.assertEqual(inner_request.await_count, 1)
        _run(go())

    def test_redirect_chain_validates_every_hop(self):
        """Multi-hop chain: allowed → allowed → BLOCKED. Wrapper
        must abort at the second-to-third transition."""
        async def go():
            responses = iter([
                httpx.Response(302, headers={"location": "https://www2.nyc.gov/"}),
                httpx.Response(302, headers={"location": "https://a810-bisweb.nyc.gov/"}),
            ])

            async def fake_request(_self, method, url, **kwargs):
                return next(responses)

            with patch.object(httpx.AsyncClient, "request", new=fake_request):
                async with ServerHttpClient() as c:
                    with self.assertRaises(EgressViolation):
                        await c.get(
                            "https://www1.nyc.gov/start",
                            follow_redirects=True,
                        )
        _run(go())

    def test_relative_redirect_resolved_then_validated(self):
        """A relative `location: /foo` from an allowed host stays on
        that host — pass. A relative redirect from www1 to /foo never
        hits Akamai."""
        async def go():
            responses = iter([
                httpx.Response(302, headers={"location": "/safe/path"}),
                httpx.Response(200),
            ])
            seen = []

            async def fake_request(_self, method, url, **kwargs):
                seen.append(url)
                return next(responses)

            with patch.object(httpx.AsyncClient, "request", new=fake_request):
                async with ServerHttpClient() as c:
                    resp = await c.get(
                        "https://www1.nyc.gov/start",
                        follow_redirects=True,
                    )
                    self.assertEqual(resp.status_code, 200)
            self.assertEqual(seen[0], "https://www1.nyc.gov/start")
            self.assertEqual(seen[1], "https://www1.nyc.gov/safe/path")
        _run(go())


class TestSocrataTokenInjection(unittest.TestCase):

    def setUp(self):
        # Reset the one-time warning latch so each test sees a fresh state.
        server_http._socrata_token_warning_emitted = False

    def test_token_attached_when_env_set(self):
        async def go():
            captured = {}

            async def fake_request(_self, method, url, **kwargs):
                captured["headers"] = dict(kwargs.get("headers") or {})
                return httpx.Response(200)

            with patch.dict(os.environ, {"SOCRATA_APP_TOKEN": "abc123"}):
                with patch.object(httpx.AsyncClient, "request", new=fake_request):
                    async with ServerHttpClient() as c:
                        await c.get("https://data.cityofnewyork.us/resource/x.json")
            self.assertEqual(captured["headers"].get("X-App-Token"), "abc123")
        _run(go())

    def test_token_not_attached_when_env_unset_warns_once(self):
        captured = []

        async def fake_request(_self, method, url, **kwargs):
            captured.append(dict(kwargs.get("headers") or {}))
            return httpx.Response(200)

        async def go():
            async with ServerHttpClient() as c:
                await c.get("https://data.cityofnewyork.us/resource/x.json")
                await c.get("https://data.cityofnewyork.us/resource/y.json")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOCRATA_APP_TOKEN", None)
            with patch.object(httpx.AsyncClient, "request", new=fake_request):
                # assertLogs is a sync context manager; wrap the
                # async work inside it.
                with self.assertLogs("lib.server_http", level="WARNING") as logs:
                    _run(go())

        # No token attached on either call.
        for h in captured:
            self.assertNotIn("X-App-Token", h)
        # Exactly one warning emitted (the "suppressing further" line).
        warnings = [r for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("SOCRATA_APP_TOKEN", warnings[0].getMessage())

    def test_explicit_caller_token_not_overwritten(self):
        async def go():
            captured = {}

            async def fake_request(_self, method, url, **kwargs):
                captured["headers"] = dict(kwargs.get("headers") or {})
                return httpx.Response(200)

            with patch.dict(os.environ, {"SOCRATA_APP_TOKEN": "from-env"}):
                with patch.object(httpx.AsyncClient, "request", new=fake_request):
                    async with ServerHttpClient() as c:
                        await c.get(
                            "https://data.cityofnewyork.us/resource/x.json",
                            headers={"X-App-Token": "from-caller"},
                        )
            self.assertEqual(captured["headers"]["X-App-Token"], "from-caller")
        _run(go())


class TestNonHttpHostsPassThrough(unittest.TestCase):

    def test_socrata_call_with_token_succeeds(self):
        async def go():
            with patch.dict(os.environ, {"SOCRATA_APP_TOKEN": "tok"}):
                with patch.object(
                    httpx.AsyncClient, "request",
                    new=AsyncMock(return_value=httpx.Response(200, json={"ok": True})),
                ):
                    async with ServerHttpClient() as c:
                        resp = await c.get(
                            "https://data.cityofnewyork.us/resource/rbx6-tga4.json"
                        )
                        self.assertEqual(resp.status_code, 200)
        _run(go())

    def test_arbitrary_third_party_host_passes(self):
        async def go():
            with patch.object(
                httpx.AsyncClient, "request",
                new=AsyncMock(return_value=httpx.Response(200)),
            ):
                async with ServerHttpClient() as c:
                    resp = await c.get("https://api.together.xyz/v1/chat/completions")
                    self.assertEqual(resp.status_code, 200)
        _run(go())


if __name__ == "__main__":
    unittest.main()
