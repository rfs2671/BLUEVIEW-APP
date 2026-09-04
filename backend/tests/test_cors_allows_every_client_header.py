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

WHY THE HEADER SET IS DERIVED AND NOT WRITTEN DOWN HERE. A hand-written list is
a second copy of the client's behaviour that agrees with itself forever while
the client moves -- the same failure as a merge test that reimplements the
merge. This reads the header names out of the client source, so the day
somebody adds `X-Whatever` to a request without touching allow_headers, this
goes red on the commit that adds it rather than in production.

AND IT SCANS THE WHOLE CLIENT, not just api.js. Scoping the scan to the one
file that happened to break would be the hand-written subset again, one level
up: `offlineQueue.js` builds its own header dict and calls bare `fetch`,
precisely because it does NOT go through the axios interceptor. Any file that
can originate a request is read.

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

CLIENT_ROOTS = (
    _REPO / "frontend" / "src",
    _REPO / "frontend" / "app",
)

# A real route, not a synthetic one: the preflight has to pass for the call the
# user is actually making. This is the one that was failing.
PREFLIGHT_PATH = "/api/auth/login"

# The four the fetch spec lets through with no preflight at all. Starlette adds
# them to the allow list itself; they are never the thing that breaks.
SAFELISTED = {"accept", "accept-language", "content-language", "content-type"}

# `const REQUEST_ID_HEADER = 'X-Request-Id';`
_CONST_RE = re.compile(r"const\s+([A-Z][A-Z0-9_]*)\s*=\s*['\"]([A-Za-z0-9-]+)['\"]")

# The four shapes a header name is written in across this client. A fifth
# arriving later shows up as a header these do NOT return, which is what
# test_the_extractor_still_reads_the_client guards against.
_OBJECT_LITERAL_RE = re.compile(r"headers\s*[:=]\s*\{([^}]*)\}")
_OBJECT_KEY_RE = re.compile(r"['\"]([A-Za-z0-9-]+)['\"]\s*:")
_SUBSCRIPT_LITERAL_RE = re.compile(r"headers\[\s*['\"]([A-Za-z0-9-]+)['\"]\s*\]")
_SUBSCRIPT_CONST_RE = re.compile(r"headers\[\s*([A-Z][A-Z0-9_]*)\s*\]")
_DOTTED_RE = re.compile(r"\.headers\.([A-Za-z][A-Za-z0-9-]*)\s*=")


def client_sources():
    """Every non-test client file that could originate a request."""
    out = []
    for root in CLIENT_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in (".js", ".jsx", ".ts", ".tsx"):
                continue
            if ".test." in path.name or "node_modules" in path.parts:
                continue
            out.append(path)
    return out


def header_symbols(sources):
    """Header-name constants, gathered across ALL files before extraction.

    offlineQueue.js writes `headers[REQUEST_ID_HEADER]` but IMPORTS that name
    from api.js, so a per-file symbol table resolves it to nothing and silently
    drops the header. The table has to be global to the client.
    """
    consts = {}
    for path in sources:
        for m in _CONST_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
            consts[m.group(1)] = m.group(2)
    return consts


def headers_in(src, consts):
    """Header names this one file attaches to an outbound request."""
    found = set()

    # 1. axios.create({ headers: {...} }) and `const headers = {...}` before a
    #    bare fetch -- both ride on a real request.
    for block in _OBJECT_LITERAL_RE.finditer(src):
        for key in _OBJECT_KEY_RE.finditer(block.group(1)):
            found.add(key.group(1))

    # 2. config.headers['X-Client-Version'] = ...      (literal subscript)
    for m in _SUBSCRIPT_LITERAL_RE.finditer(src):
        found.add(m.group(1))

    # 3. headers[REQUEST_ID_HEADER] = ...              (subscript via a const)
    for m in _SUBSCRIPT_CONST_RE.finditer(src):
        if m.group(1) in consts:
            found.add(consts[m.group(1)])

    # 4. config.headers.Authorization = ...            (dotted)
    for m in _DOTTED_RE.finditer(src):
        found.add(m.group(1))

    return found


def headers_by_file():
    """{path: {header, ...}} across the whole client."""
    sources = client_sources()
    consts = header_symbols(sources)
    out = {}
    for path in sources:
        found = headers_in(path.read_text(encoding="utf-8", errors="replace"), consts)
        if found:
            out[path] = found
    return out


def client_headers():
    """The union: everything any client file can put on a request."""
    found = set()
    for names in headers_by_file().values():
        found |= names
    return found


class TheDerivationItself(unittest.TestCase):
    """A silently-empty extractor would make every assertion below pass while
    proving nothing, which is the exact failure mode this file exists to avoid
    committing a second time."""

    def test_the_client_source_is_where_we_think_it_is(self):
        for root in CLIENT_ROOTS:
            self.assertTrue(root.is_dir(), "client source moved: %s" % root)
        self.assertTrue(client_sources(), "found no client files to scan")

    def test_the_extractor_still_reads_the_client(self):
        by_file = headers_by_file()
        self.assertTrue(
            by_file,
            "extracted NO headers from any client file -- the request paths "
            "were rewritten in a shape these regexes do not parse, and every "
            "CORS assertion below is now vacuous",
        )
        found = client_headers()
        # Canaries on the parse, not a substitute for it. Each covers a
        # DIFFERENT one of the four shapes, so a regex that rots is caught:
        #   literal subscript  ->  config.headers['X-Client-Version']
        #   const subscript    ->  headers[REQUEST_ID_HEADER]  (imported name)
        #   dotted             ->  config.headers.Authorization
        #   object literal     ->  headers: { 'Content-Type': ... }
        for name in ("X-Client-Version", "X-Request-Id",
                     "Authorization", "Content-Type"):
            with self.subTest(shape=name):
                self.assertIn(
                    name, found,
                    "the client no longer sets %s in a shape this test can "
                    "read -- fix the extractor, do not delete this" % name,
                )

    def test_the_bare_fetch_path_is_scanned_too(self):
        """offlineQueue.js does NOT go through the axios interceptor. Scoping
        this test to api.js would be the hand-written subset one level up."""
        by_file = headers_by_file()
        names = {p.name for p in by_file}
        self.assertIn("api.js", names)
        self.assertIn("offlineQueue.js", names)


class PreflightAcceptsTheRealHeaderSet(unittest.TestCase):
    """One OPTIONS carrying exactly what the browser would ask for."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.headers = sorted(client_headers())
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
                    "the client sends %s on a request and the server does not "
                    "allow it -- add it to allow_headers in server.py or the "
                    "web build cannot call this API" % name,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
