"""A VIEW URL MUST NOT CARRY A THIRTY-DAY SESSION CREDENTIAL.

An <iframe> and a system browser cannot set an Authorization header, so a
document url has to carry its own credential in the query string. It carried
the SESSION JWT, and `JWT_EXPIRATION_HOURS` is 720.

MEASURED RATHER THAN INFERRED: a request with a marker in its query string was
sent to production and the marker read back out of the platform log as
`/api/version?probe=<marker>`. So every document open wrote a live 30-day
bearer token into a month of log retention, plus the browser history of whoever
opened it and any link they copied.

A GRANT NAMES ONE THING AND DIES. One R2 object or one rendered report, 120
seconds, and no other authority -- the public route that serves it takes no
session at all, so a leaked link discloses one document for two minutes instead
of one account for a month.
"""

from __future__ import annotations

import ast
import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_TREE = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))


def _fn(name):
    for n in ast.walk(_TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} is not defined in server.py")


class _Grants:
    """A stand-in for one Mongo collection, holding real rows."""

    def __init__(self):
        self.rows = []

    async def insert_one(self, doc):
        self.rows.append(dict(doc))

    async def create_index(self, *a, **k):
        return "idx"

    async def find_one(self, q):
        for r in self.rows:
            if all(r.get(k) == v for k, v in q.items()):
                return dict(r)
        return None


class _DB:
    def __init__(self, grants):
        self._g = grants

    def __getitem__(self, name):
        return self._g


class AGrantIsShortLivedAndSinglePurpose(unittest.TestCase):

    def test_the_lifetime_is_SECONDS_not_hours(self):
        """The whole point. A session is 720 hours; this must be nowhere near
        it, and the assertion is on the number rather than on a comment."""
        self.assertLessEqual(server.VIEW_GRANT_TTL_SECONDS, 300)
        self.assertGreater(server.VIEW_GRANT_TTL_SECONDS, 0)
        self.assertGreater(server.JWT_EXPIRATION_HOURS * 3600,
                           server.VIEW_GRANT_TTL_SECONDS * 100,
                           "the grant is not meaningfully shorter than the "
                           "session token it replaces")

    def test_a_grant_round_trips_and_carries_only_its_payload(self):
        g = _Grants()
        with patch.object(server, "db", _DB(g)):
            tok = asyncio.run(server._mint_view_grant(
                "r2_object", r2_key="k/1.pdf", filename="A-101.pdf"))
            self.assertTrue(tok)
            row = asyncio.run(server._resolve_view_grant(tok))
        self.assertEqual(row["kind"], "r2_object")
        self.assertEqual(row["payload"]["r2_key"], "k/1.pdf")
        # NOTHING ABOUT A USER. A grant that carried an identity would be a
        # session by another name.
        self.assertNotIn("user_id", row)
        self.assertNotIn("company_id", row)
        self.assertNotIn("role", row)

    def test_the_token_is_not_derived_from_what_it_names(self):
        """An opaque token. If it were a hash of the key, two people holding
        the same document would hold the same link."""
        g = _Grants()
        with patch.object(server, "db", _DB(g)):
            a = asyncio.run(server._mint_view_grant("r2_object", r2_key="same"))
            b = asyncio.run(server._mint_view_grant("r2_object", r2_key="same"))
        self.assertNotEqual(a, b)
        self.assertNotIn("same", a)
        self.assertGreaterEqual(len(a), 24)

    def test_an_EXPIRED_grant_resolves_to_NOTHING(self):
        """CHECKED ON RESOLVE, not only by the TTL index. A TTL sweep runs
        about once a minute, so an index alone would let a 120-second
        credential live for three."""
        g = _Grants()
        g.rows.append({
            "token": "old", "kind": "r2_object", "payload": {"r2_key": "k"},
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        })
        with patch.object(server, "db", _DB(g)):
            self.assertIsNone(asyncio.run(server._resolve_view_grant("old")))

    def test_a_naive_expiry_is_read_as_UTC_and_still_expires(self):
        """Mongo hands back naive datetimes. Comparing one to an aware `now`
        raises, and a resolver that raises here fails OPEN or 500s."""
        g = _Grants()
        g.rows.append({
            "token": "naive", "kind": "r2_object", "payload": {},
            "expires_at": datetime.utcnow() - timedelta(minutes=5),
        })
        with patch.object(server, "db", _DB(g)):
            self.assertIsNone(asyncio.run(server._resolve_view_grant("naive")))

    def test_a_LIVE_grant_still_resolves(self):
        """The other half: a guard that refuses everything is not a guard."""
        g = _Grants()
        g.rows.append({
            "token": "live", "kind": "r2_object", "payload": {"r2_key": "k"},
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
        })
        with patch.object(server, "db", _DB(g)):
            self.assertIsNotNone(asyncio.run(server._resolve_view_grant("live")))

    def test_an_unstorable_grant_returns_None_rather_than_raising(self):
        """A document that cannot be granted must not take down the screen
        listing it."""
        class _Broken:
            def __getitem__(self, name):
                raise RuntimeError("mongo down")
        with patch.object(server, "db", _Broken()):
            self.assertIsNone(asyncio.run(server._mint_view_grant("r2_object")))


class ThePublicRouteServesOnlyWhatTheGrantNames(unittest.TestCase):

    def test_it_streams_rather_than_buffering(self):
        """37.9MB is the largest file in production and 171MB is the total
        across 26. A buffered read is that spike per concurrent viewer, which
        is why this does not reuse `public_temp_media_get`."""
        body = ast.unparse(_fn("public_view_grant"))
        self.assertTrue("StreamingResponse" in body,
                        "the public view route buffers its object")
        self.assertTrue("65536" in body,
                        "the object is no longer read in chunks")

    def test_it_does_not_declare_a_PUBLIC_cache(self):
        """The token is opaque and short-lived; the BYTES are a private
        project document and a shared cache must not keep them."""
        body = ast.unparse(_fn("public_view_grant"))
        self.assertTrue("private, no-store" in body)
        self.assertTrue("public, max-age" not in body,
                        "a shared cache may store a project document")

    def test_an_unknown_KIND_is_refused_rather_than_falling_through(self):
        g = _Grants()
        g.rows.append({
            "token": "weird", "kind": "something_else", "payload": {},
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
        })
        with patch.object(server, "db", _DB(g)):
            with self.assertRaises(server.HTTPException) as c:
                asyncio.run(server.public_view_grant("weird"))
        self.assertEqual(c.exception.status_code, 404)

    def test_an_unknown_TOKEN_is_a_404(self):
        g = _Grants()
        with patch.object(server, "db", _DB(g)):
            with self.assertRaises(server.HTTPException) as c:
                asyncio.run(server.public_view_grant("nope"))
        self.assertEqual(c.exception.status_code, 404)


class TheMintSitesCarryTheGuardsOfWhatTheyReplace(unittest.TestCase):

    def test_the_report_grant_requires_project_access(self):
        """The grant IS the whole credential downstream, so the check has to
        happen before it is minted and nowhere after."""
        dec = " ".join(ast.unparse(d)
                       for d in _fn("mint_report_view_grant").decorator_list)
        self.assertIn("require_project_access", dec)

    def test_the_file_grant_is_minted_AFTER_the_allow_list(self):
        """`get_dropbox_file_url` asks `_site_device_may_retrieve` before it
        hands out anything. A grant minted first would outlive the refusal."""
        fn = _fn("get_dropbox_file_url")
        src = ast.unparse(fn)
        self.assertLess(src.index("_site_device_may_retrieve"),
                        src.index("_mint_view_grant"),
                        "a grant is minted before the allow-list has spoken")

    def test_the_file_route_still_answers_when_a_grant_cannot_be_minted(self):
        """The authenticated proxy path remains the fallback rather than a
        second convention, so a Mongo blip does not close the plan room."""
        src = ast.unparse(_fn("get_dropbox_file_url"))
        self.assertIn("r2_proxy", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
