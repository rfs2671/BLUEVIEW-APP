"""Server-side HTTP client with Akamai egress guard.

ARCHITECTURAL RULE (see ~/.claude/plans/permit-renewal-v3.md §2.2):
  Akamai-protected DOB hosts (a810-*.nyc.gov) MUST NOT be called from
  server-side code. Those reads route through the worker queue
  (dob_license_lookup, dob_insurance_snapshot, dob_verify_coi jobs).

  Violating this rule will get the production IP flagged by Akamai
  Bot Manager, degrading legitimate user traffic from Microsoft /
  Google email link prefetchers as a knock-on effect.

  If you find yourself wanting to bypass this guard, you're solving
  the wrong problem. Enqueue a worker job instead.

WHAT THIS WRAPPER DOES:
  1. Refuses any direct request whose target host is on the Akamai
     blocklist — raises EgressViolation at the request site.
  2. Refuses redirected responses landing on a blocked host. The
     naive guard checks only the initial URL; auto-redirects can
     still smuggle a request to Akamai. Default behavior here is
     `follow_redirects=False` to make the bypass impossible. When a
     caller explicitly opts in (`follow_redirects=True`), every hop
     of the chain is re-validated, and the chain is aborted with
     EgressViolation on the first blocked host.
  3. Auto-attaches the X-App-Token header for Socrata hosts so we
     stay above the 1000 req/hr anonymous quota. Logs a one-time
     warning if SOCRATA_APP_TOKEN is unset (dev env vs. prod
     misconfiguration distinguishable in logs).

WHAT THIS WRAPPER DOES NOT DO:
  - Wrap sync `httpx.Client`. Codebase audit at the time of writing:
    zero sync httpx usages in backend/. If a sync usage is added
    later, this module needs a sync sibling.
  - Wrap `requests` or `urllib.request`. Codebase audit: zero such
    imports in backend/. CI lint catches future regressions.
  - Get imported in worker code. The worker (bis_scraper/) is the
    intentional Akamai-talking process and has its own raw httpx
    client. CI check forbids `from backend.lib.server_http` or
    `import server_http` inside the worker tree.

USAGE:
    async with ServerHttpClient(timeout=20.0) as client:
        resp = await client.get("https://data.cityofnewyork.us/...")
        # X-App-Token auto-attached if SOCRATA_APP_TOKEN env is set

    # Direct hit to a blocked DOB host raises:
    async with ServerHttpClient() as client:
        await client.get("https://a810-dobnow.nyc.gov/...")
        # → EgressViolation
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Set
from urllib.parse import urlparse

import httpx


logger = logging.getLogger(__name__)


# Akamai-protected NYC DOB hosts. Any GET/POST/etc. against these from
# server-side code is forbidden. The worker (bis_scraper/) uses raw
# httpx and is the intentional caller.
AKAMAI_BLOCKED_HOSTS: Set[str] = {
    "a810-dobnow.nyc.gov",
    "a810-bisweb.nyc.gov",
    "a810-dobnowtor.nyc.gov",
    "a810-efiling.nyc.gov",
}

# Socrata data hosts where we auto-attach X-App-Token to stay under
# anonymous rate limits.
SOCRATA_HOSTS: Set[str] = {
    "data.cityofnewyork.us",
}


class EgressViolation(RuntimeError):
    """Raised when server-side code tries to talk to an Akamai-protected
    DOB host. Indicates a callsite that should be routing through the
    worker queue instead.
    """


# One-time warning latch — Socrata calls without a token shouldn't spam
# logs every request, but the first one per process should be visible
# enough to notice during local dev.
_socrata_token_warning_emitted = False
_socrata_token_shape_logged = False
_socrata_malformed_token_warned = False

# Socrata App Tokens are 25 chars of [A-Za-z0-9]. Allow a tolerant
# range so future format changes don't break us, but reject obvious
# garbage (empty, surrounded by quotes, contains newlines, way wrong
# length). Sending a malformed token to Socrata returns 403 on every
# request — far worse than falling back to the anonymous quota.
_SOCRATA_TOKEN_MIN_LEN = 20
_SOCRATA_TOKEN_MAX_LEN = 50


def _socrata_app_token() -> Optional[str]:
    """Read SOCRATA_APP_TOKEN. Strips whitespace + surrounding quotes
    that Railway env-var copy-paste sometimes leaves in. Returns None
    if the token is empty after cleanup OR shaped wrong — the latter
    case logs a loud one-time warning so the operator sees it.
    """
    global _socrata_malformed_token_warned

    raw = os.environ.get("SOCRATA_APP_TOKEN", "")
    # Strip whitespace + matched surrounding quotes. Order matters:
    # strip whitespace first (might reveal stray quotes), then quotes.
    cleaned = raw.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or \
       (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()

    if not cleaned:
        return None

    # Sanity-check shape. If garbage made it into the env, refuse to
    # send it — anonymous-quota fallback is strictly better than
    # 403'ing every Socrata request in production.
    n = len(cleaned)
    if n < _SOCRATA_TOKEN_MIN_LEN or n > _SOCRATA_TOKEN_MAX_LEN \
       or not cleaned.isalnum():
        if not _socrata_malformed_token_warned:
            logger.error(
                "SOCRATA_APP_TOKEN appears malformed (length=%d, "
                "alphanumeric=%s). Falling back to anonymous quota. "
                "Expected 25 chars of [A-Za-z0-9]. Check the env var "
                "for whitespace, quotes, or wrong token type "
                "(App Token, NOT Secret Token).",
                n, cleaned.isalnum(),
            )
            _socrata_malformed_token_warned = True
        return None

    return cleaned


def _check_host_or_raise(url: str) -> str:
    """Returns the lowercased hostname; raises EgressViolation if it's
    on the blocklist. Centralized so the same logic gates both the
    initial request and every redirect hop.
    """
    host = (urlparse(url).hostname or "").lower()
    if host in AKAMAI_BLOCKED_HOSTS:
        raise EgressViolation(
            f"Server-side request to Akamai-protected host {host!r} is "
            f"forbidden. Route via worker queue (dob_license_lookup / "
            f"dob_insurance_snapshot / dob_verify_coi jobs). See "
            f"backend/lib/server_http.py for the architectural rule."
        )
    return host


def _maybe_inject_socrata_token(host: str, kwargs: dict) -> None:
    """If `host` is a known Socrata host, attach X-App-Token. Logs a
    one-time warning if the token is unset so dev environments notice
    they're unauthenticated against the anonymous quota."""
    global _socrata_token_warning_emitted, _socrata_token_shape_logged
    if host not in SOCRATA_HOSTS:
        return
    token = _socrata_app_token()
    if not token:
        if not _socrata_token_warning_emitted:
            logger.warning(
                "SOCRATA_APP_TOKEN env var is not set or malformed. "
                "Server-side Socrata calls will use the anonymous "
                "quota (~1000 req/hr per IP) and may produce "
                "intermittent 429s under load. Suppressing further "
                "warnings for this process."
            )
            _socrata_token_warning_emitted = True
        return

    # One-time shape diagnostic — masked, never logs the full token.
    # Lets the operator confirm in Railway logs that the right value
    # is in env (length matches, no whitespace prefix/suffix snuck in).
    if not _socrata_token_shape_logged:
        masked = (
            f"{token[:4]}…{token[-4:]}"
            if len(token) >= 8 else "????"
        )
        logger.info(
            "Socrata token attached to outbound request: shape=%s "
            "length=%d alphanumeric=%s",
            masked, len(token), token.isalnum(),
        )
        _socrata_token_shape_logged = True

    headers = kwargs.setdefault("headers", {})
    # Don't clobber an explicit caller-supplied token.
    if isinstance(headers, dict) and "X-App-Token" not in headers:
        headers["X-App-Token"] = token


class ServerHttpClient:
    """The ONLY async HTTP client server-side code should use.

    Drop-in replacement for `httpx.AsyncClient`: same constructor
    kwargs, same context-manager protocol, same `.get/.post/.request`
    surface. Two behavioral differences from raw httpx:

      1. Calls to AKAMAI_BLOCKED_HOSTS raise EgressViolation.
      2. `follow_redirects` defaults to False. When set True by the
         caller, every redirect hop is re-validated against the
         blocklist; first blocked hop aborts the chain.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Force redirect-following off by default. Callers who want
        # auto-redirect behavior must pass follow_redirects=True
        # explicitly to .request() — see _request_following_redirects.
        # We do NOT propagate follow_redirects to the inner client;
        # it always runs with auto-redirect off so we control the chain.
        self._caller_default_follow = kwargs.pop("follow_redirects", False)
        kwargs["follow_redirects"] = False
        self._inner: httpx.AsyncClient = httpx.AsyncClient(*args, **kwargs)

    async def __aenter__(self) -> "ServerHttpClient":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._inner.__aexit__(exc_type, exc, tb)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        follow_redirects: Optional[bool] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        host = _check_host_or_raise(url)
        _maybe_inject_socrata_token(host, kwargs)

        do_follow = (
            follow_redirects
            if follow_redirects is not None
            else self._caller_default_follow
        )
        if do_follow:
            return await self._request_following_redirects(method, url, **kwargs)
        return await self._inner.request(method, url, **kwargs)

    async def _request_following_redirects(
        self,
        method: str,
        url: str,
        max_redirects: int = 20,
        **kwargs: Any,
    ) -> httpx.Response:
        """Manual redirect walker. Re-validates every hop's host
        against the blocklist. The naive guard at the call site only
        sees the initial URL; without this, a 302 from an allowed
        host to an Akamai host would silently route through Akamai.
        """
        current_url = url
        current_method = method
        # body shouldn't be replayed past 303 → GET (per RFC 7231).
        # We follow httpx's behavior loosely.
        for _hop in range(max_redirects):
            resp = await self._inner.request(current_method, current_url, **kwargs)
            if resp.status_code not in (301, 302, 303, 307, 308):
                return resp
            location = resp.headers.get("location")
            if not location:
                return resp
            # Resolve relative redirects against the current URL.
            next_url = str(httpx.URL(current_url).join(location))
            _check_host_or_raise(next_url)
            current_url = next_url
            # 303 forces GET; 307/308 preserve method; 301/302 are
            # commonly downgraded to GET in browsers — match httpx
            # default behavior of preserving method on 307/308 and
            # downgrading on 301/302/303 for non-GET/HEAD.
            if resp.status_code == 303 or (
                resp.status_code in (301, 302) and current_method not in ("GET", "HEAD")
            ):
                current_method = "GET"
                kwargs.pop("content", None)
                kwargs.pop("data", None)
                kwargs.pop("json", None)
                kwargs.pop("files", None)
        raise httpx.TooManyRedirects(
            f"Exceeded {max_redirects} redirect hops",
            request=resp.request,
        )

    # Convenience methods mirroring httpx.AsyncClient's surface.
    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("HEAD", url, **kwargs)

    # Common attribute passthroughs so existing code that pokes at the
    # client's properties keeps working.
    @property
    def headers(self):
        return self._inner.headers

    @property
    def cookies(self):
        return self._inner.cookies

    @property
    def timeout(self):
        return self._inner.timeout
