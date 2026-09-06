"""A DROPBOX CONNECTION BELONGS TO A COMPANY, NOT TO WHOEVER CONNECTED FIRST.

The stored row is keyed `{"company_id": company_id}` and Mongo matches null AND
absent, so every account without a company shared ONE row — holding a refresh
token and an access token for somebody's Dropbox.

What a second company-less account could do with it, established by reading
every reader: list the first account's folder tree at any path; silently take
the row over by connecting, since `get_dropbox_status` reports "Not Connected"
for it and the UI therefore offers a Connect button over a live connection; and
**revoke the first account's connection outright** — `disconnect_dropbox` finds
the shared row, calls Dropbox's token revoke, and nulls both tokens.

What it could NOT do: file names, file content, download URLs. Those sit behind
`project_access_ok`, which fails closed for a company-less caller, and it
cannot mint itself a project assignment either. There are no Dropbox WRITE
endpoints in this codebase at all.

── NOT AN INCIDENT, AND THE NUMBERS SAY SO ────────────────────────────────

Production holds 2 connection rows, **both with real company ids**. Zero
null-company rows have ever existed; zero null-company projects, files or sync
runs. Two accounts could create one. Neither has.

It is fixed because a token store shared across tenants is wrong by
construction, and because one live account is already in the shape that reaches
it: `onboarding_step: null` escapes the RouteGuard redirect and can open
`/admin/integrations`.

── THE REFUSAL IS ON THE WRITE; THE READ GUARD IS THE BELT ────────────────

If the row cannot be created it cannot be shared, and there are no old rows to
migrate. `get_valid_dropbox_token` carries the matching read guard because
every reader funnels through it, including the two a call-site sweep did not
name (`register_dropbox_webhook`, `_generate_annotation_screenshot`).

── AND THE WORDING IS NOT AN ERROR ────────────────────────────────────────

"Complete company setup first, then connect Dropbox." He has not done anything
wrong; this is the next step. Asserted, because a message is the whole of what
the CP experiences here and a 409 with a stack-trace-shaped body would read as
a fault he caused.
"""

from __future__ import annotations

import asyncio
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

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402

MSG = "Complete company setup first, then connect Dropbox."


class _Conns:
    """The shared row, as it would have existed."""

    def __init__(self):
        self.queries = []

    async def find_one(self, query, projection=None):
        self.queries.append(query)
        return {"_id": "shared", "company_id": None,
                "access_token": "SECRET-A", "refresh_token": "SECRET-R",
                "access_token_expires_at": None}


class _DB:
    def __init__(self, conns):
        self.dropbox_connections = conns


class Base(unittest.TestCase):
    def setUp(self):
        self.conns = _Conns()
        self._orig = {"db": server.db, "gid": server.get_user_company_id}
        server.db = _DB(self.conns)

    def tearDown(self):
        server.db = self._orig["db"]
        server.get_user_company_id = self._orig["gid"]


class TheConnectPathsRefuseACompanylessAccount(Base):
    """THE REAL FIX. A row that cannot be created cannot be shared."""

    def setUp(self):
        super().setUp()
        server.get_user_company_id = lambda u: None

    def test_the_auth_url_is_refused_before_the_round_trip(self):
        """Refused here so the CP never reaches Dropbox's consent screen and
        comes back to a rejection."""
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(server.get_dropbox_auth_url({"id": "u1"}))
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["code"], "COMPANY_REQUIRED")

    def test_complete_auth_is_refused_too(self):
        """The alternative completion path. Refusing only the auth-url would
        leave a caller who kept an old code able to create the row."""
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(server.complete_dropbox_auth({"code": "abc"},
                                                     {"id": "u1"}))
        self.assertEqual(cm.exception.status_code, 409)

    def test_and_it_is_refused_BEFORE_the_code_is_even_validated(self):
        """Order matters: a company-less caller with no code should hear about
        the company, not about the code. The reverse would send him to fix the
        wrong thing."""
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(server.complete_dropbox_auth({}, {"id": "u1"}))
        self.assertEqual(cm.exception.detail["code"], "COMPANY_REQUIRED")

    def test_the_message_is_a_next_step_and_not_an_error(self):
        """He has not done anything wrong. This is the whole of what he sees."""
        for call in (lambda: server.get_dropbox_auth_url({"id": "u1"}),
                     lambda: server.complete_dropbox_auth({"code": "c"},
                                                          {"id": "u1"})):
            with self.subTest():
                with self.assertRaises(HTTPException) as cm:
                    asyncio.run(call())
                self.assertEqual(cm.exception.detail["message"], MSG)
                for shouty in ("Error", "error", "Forbidden", "denied",
                               "Invalid", "failed"):
                    self.assertNotIn(shouty, cm.exception.detail["message"])


class ACompanyAccountIsUnaffected(Base):
    def setUp(self):
        super().setUp()
        server.get_user_company_id = lambda u: "c1"

    def test_the_auth_url_is_still_issued(self):
        """The control. A guard that refused everybody would satisfy every
        assertion above."""
        out = asyncio.run(server.get_dropbox_auth_url({"id": "u1"}))
        self.assertIn("auth_url", out)
        self.assertIn("dropbox.com", out["auth_url"])


class TheReadGuardFailsClosed(Base):
    """The belt to the write refusal's braces. `{"company_id": None}` is a
    MATCHING query -- null and absent both hit -- so a falsy company would have
    found the shared row rather than nothing."""

    def test_a_falsy_company_never_reaches_the_database(self):
        for cid in (None, ""):
            with self.subTest(company_id=cid):
                self.conns.queries.clear()
                with self.assertRaises(HTTPException) as cm:
                    asyncio.run(server.get_valid_dropbox_token(cid))
                self.assertEqual(cm.exception.status_code, 400)
                self.assertEqual(
                    self.conns.queries, [],
                    "the shared row was looked up before the guard fired")

    def test_no_token_is_returned_for_a_falsy_company(self):
        """The property that matters, stated on the secret rather than on the
        status code: nothing that could authenticate to Dropbox comes back."""
        try:
            out = asyncio.run(server.get_valid_dropbox_token(None))
        except HTTPException:
            out = ""
        self.assertNotIn("SECRET", str(out))

    def test_a_real_company_still_queries(self):
        """The control on this half."""
        try:
            asyncio.run(server.get_valid_dropbox_token("c1"))
        except Exception:
            pass
        self.assertEqual(len(self.conns.queries), 1)
        self.assertEqual(self.conns.queries[0]["company_id"], "c1")


class TheCallbackRefusesWithAPageAndNotAStackTrace(unittest.TestCase):
    """That route answers the browser after Dropbox's redirect, so a raw 409
    would render as a blank error page."""

    def test_the_refusal_is_rendered_html_carrying_the_same_words(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("async def dropbox_callback(")
        j = src.index("\n@api_router", i)
        body = src[i:j]
        self.assertIn("HTMLResponse", body)
        self.assertIn(MSG, body)

    def test_it_resolves_the_company_from_the_STORED_user(self):
        """Not from a token claim -- so it cannot be talked out of the check by
        a forged state parameter."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("async def dropbox_callback(")
        j = src.index("\n@api_router", i)
        body = src[i:j]
        self.assertIn('db.users.find_one({"_id": to_query_id(user_id)})', body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
