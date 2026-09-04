"""Every header the web build actually sends survives a real preflight.

THE OUTAGE THIS PINS. The frontend request interceptor sets `X-Client-Version`
on EVERY request. It is not a CORS-safelisted header, so a cross-origin call
from the web build triggers a preflight that asks permission for it -- and
`allow_headers` did not name it. Starlette's CORSMiddleware answered

    HTTP/1.1 400 Bad Request
    Disallowed CORS headers

and Chrome then refused to send the request at all: provisional headers, no
response, net::ERR_FAILED. Not one endpoint -- EVERY endpoint, including
POST /api/auth/login, so the web app could not sign in.

WHY NOTHING CAUGHT IT.

  * Native clients send no Origin and therefore get no preflight. The entire
    mobile surface is structurally incapable of seeing a CORS failure, so the
    device the team tests on works perfectly while the web build is dead.
  * backend/scripts/postdeploy_login_check.py sends X-Client-Version, which is
    exactly right for the 2026-08-31 500 -- but it speaks urllib, sends no
    Origin, and issues no OPTIONS. It is green through this.
  * /api/version is 200 with correct CORS headers, because a GET carrying no
    unsafe header needs no preflight at all.

WHY THE HEADER SET IS DERIVED AND NOT WRITTEN DOWN HERE. A hand-written list
is a second copy of the client's behaviour that agrees with itself forever
while the client moves -- the same failure as a merge test that reimplements
the merge. This reads the header names out of the client source, so the day
somebody adds `X-Whatever` to the interceptor without touching allow_headers,
this goes red on the commit that adds it rather than in production.

Run:  python -m pytest backend/tests/test_cors_allows_every_client_header.py
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

API_JS = _REPO / "frontend" / "src" / "utils" / "api.js"

# A real route, not a synthetic one: the preflight has to pass for the call the
# user is actually making. This is the one that was failing.
PREFLIGHT_PATH = "/api/auth/login"

# The four the fetch spec lets through with no preflight at all. Starlette adds
# them to the allow list itself; they are never the thing that breaks.
SAFELISTED = {"accept", "accept-language", "content-language", "content-type"}


def client_headers_from_source(src):
    """Every header name the client attaches to an outbound request.

    Reads api.js rather than restating it. Four forms appear there and all four
    are parsed; a fifth form arriving later shows up as a header this function
    fails to return, which is why `test_the_extractor_still_reads_the_file`
    exists below.
    """
    # `const REQUEST_ID_HEADER = 'X-Request-Id';` -- names used indirectly.
    consts = {}
    for m in re.finditer(
        r"const\s+([A-Z][A-Z0-9_]*)\s*=\s*['\"]([A-Za-z0-9-]+)['\"]", src
    ):
        consts[m.group(1)] = m.group(2)

    found = set()

    # 1. axios.create({ headers: { 'Content-Type': ... } }) -- the instance
    #    defaults, which ride on every request just like the interceptor's.
    for block in re.finditer(r"headers:\s*\{([^}]*)\}", src):
        for key in re.finditer(r"['\"]([A-Za-z0-9-]+)['\"]\s*:", block.group(1)):
            found.add(key.group(1))

    # 2. config.headers['X-Client-Version'] = ...   (literal subscript)
    for m in re.finditer(r"\.headers\[\s*['\"]([A-Za-z0-9-]+)['\"]\s*\]", src):
        found.add(m.group(1))

    # 3. config.headers[REQUEST_ID_HEADER] = ...    (subscript via a const)
    for m in re.finditer(r"\.headers\[\s*([A-Z][A-Z0-9_]*)\s*\]", src):
        if m.group(1) in consts:
            found.add(consts[m.group(1)])

    # 4. config.headers.Authorization = ...          (dotted)
    for m in re.finditer(r"\.headers\.([A-Za-z][A-Za-z0-9-]*)\s*=", src):
        found.add(m.group(1))

    return found


class ClientHeadersAreExtractable(unittest.TestCase):
    """The derivation itself, because a silently-empty extractor would make
    every assertion below pass while proving nothing."""

    def test_the_extractor_still_reads_the_file(self):
        self.assertTrue(API_JS.is_file(), "client source moved: %s" % API_JS)
        found = client_headers_from_source(API_JS.read_text(encoding="utf-8"))
        self.assertTrue(
            found,
            "extracted NO headers from api.js -- the interceptor was rewritten "
            "in a shape this function does not parse, and every CORS assertion "
            "below is now vacuous",
        )
        # A canary on the parse, not a substitute for it: this is the header
        # the outage was about, set through the literal-subscript form.
        self.assertIn(
            "X-Client-Version", found,
            "api.js no longer sets X-Client-Version the way this test reads it "
            "-- fix the extractor, do not delete this",
        )


class PreflightAcceptsTheRealHeaderSet(unittest.TestCase):
    """One OPTIONS carrying exactly what the browser would ask for."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.headers = sorted(
            client_headers_from_source(API_JS.read_text(encoding="utf-8"))
        )
        cls.origin = "https://www.levelog.com"
        assert cls.origin in server.ALLOWED_ORIGINS, (
            "%s is not in ALLOWED_ORIGINS -- this test would be asserting "
            "against an origin the product does not serve" % cls.origin
        )

    def _preflight(self):
        return self.client.options(
            PREFLIGHT_PATH,
            headers={
                "Origin": self.origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": ", ".join(self.headers),
            },
        )

    def test_preflight_with_every_client_header_is_200(self):
        resp = self._preflight()
        self.assertEqual(
            resp.status_code, 200,
            "preflight for %s returned %s %r -- the browser blocks the request "
            "before sending it, on EVERY endpoint including auth/login"
            % (self.headers, resp.status_code, resp.text),
        )
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"), self.origin)

    def test_every_client_header_is_named_in_allow_headers(self):
        """The 200 above is the user-visible half; this says WHICH header is
        the missing one, so a failure names it instead of listing the set."""
        resp = self._preflight()
        raw = resp.headers.get("access-control-allow-headers") or ""
        allowed = set(h.strip().lower() for h in raw.split(",") if h.strip())
        self.assertTrue(
            allowed,
            "no Access-Control-Allow-Headers in the preflight response at all",
        )
        for name in self.headers:
            with self.subTest(header=name):
                self.assertIn(
                    name.lower(), allowed | SAFELISTED,
                    "the client sends %s on every request and the server does "
                    "not allow it -- add it to allow_headers in server.py or "
                    "the web build cannot call this API" % name,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
