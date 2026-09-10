"""A FILED RECORD OPENS FOR SOMEBODY WITH NO LOGIN, FOR NINETY DAYS.

The investor report's PROJECT RECORD page names eight filed logbooks and gives
each a View Document button. Today the report EMBEDS every logbook in full, so
a lender reading the attachment already has the content: the button is a
MECHANISM CHANGE, not an access change, replacing twenty pages of embedded
record with eight links.

`get_single_logbook_pdf` is `Depends(get_current_user)` and its `token` query
parameter is a JWT for that same authenticated user, so a recipient clicking a
card would get a 401. This is the route that answers instead.

── WHAT IS ASSERTED, AND WHY EACH ONE ──────────────────────────────────────

THE MOUNT. On `app`, not `api_router`. The router carries an auth dependency;
a route added there would 401 exactly the reader it exists for, and it would
do so only in production where a real recipient clicks it. Asserted against
FastAPI's own route table rather than the source, because "it is written
outside the router" and "it is registered outside the router" are different
claims and only the second one matters.

THE PAYLOAD IS A LOGBOOK ID, NOT AN R2 KEY. This reuses `temp-media`'s pattern
deliberately and its RESOLVER deliberately not: a per-logbook PDF is rendered
on demand and is not an object in storage. A token minted here must not be
resolvable by the media route and vice versa -- two collections, so a token
that leaks from one cannot address the other.

NINETY DAYS. temp-media's default is 3600 seconds because WaAPI fetches within
seconds. A report is read weeks later. The value is asserted BY NAME so that
lowering it back toward an hour, or raising it to "permanent", is a visible
edit rather than a silent one -- and the reason it is not permanent is asserted
as prose, because that is the question the next reader will have.

EXPIRY IS ENFORCED BY DELETION. The TTL index removes the row; the resolver
also checks, because Mongo's TTL monitor runs about once a minute and a
resolver that trusts the sweep returns a stale grant.

EVERY FETCH IS RECORDED. Nothing else in this system would show that a
statutory record was read by somebody with no account.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

PATH = "/api/public/logbook/{token}"


class TheRouteIsReachableWithoutAnAccount(unittest.TestCase):

    def _route(self):
        return next((r for r in server.app.routes
                     if getattr(r, "path", None) == PATH), None)

    def test_it_is_registered_at_all(self):
        self.assertIsNotNone(self._route(), f"{PATH} is not mounted")

    def test_it_is_NOT_on_the_authenticated_router(self):
        """`api_router` carries the auth dependency. A route added there 401s
        the one reader this exists for, and only in production."""
        on_router = [r for r in server.api_router.routes
                     if "public/logbook" in getattr(r, "path", "")]
        self.assertEqual(on_router, [])

    def test_it_takes_the_token_and_nothing_else(self):
        """A `?logbook_id=` beside a token would let the link be re-pointed at
        a different record by editing the URL."""
        params = list(inspect.signature(server.public_logbook_pdf)
                      .parameters)
        self.assertEqual(params, ["token"])

    def test_it_depends_on_no_current_user(self):
        deps = str(getattr(self._route(), "dependant", ""))
        self.assertNotIn("get_current_user", deps)
        i = _SRC.index("async def public_logbook_pdf(")
        self.assertNotIn("Depends(", _SRC[i:i + 200])


class NinetyDaysAndTheReasonIsWrittenDown(unittest.TestCase):

    def test_the_ttl_is_ninety_days(self):
        self.assertEqual(server.SHARED_LOGBOOK_TTL_SECONDS, 90 * 24 * 3600)

    def test_the_minter_defaults_to_it(self):
        d = inspect.signature(server._mint_logbook_share_token) \
            .parameters["ttl_seconds"].default
        self.assertEqual(d, server.SHARED_LOGBOOK_TTL_SECONDS)

    def test_it_is_not_temp_media_s_hour(self):
        """The pattern is borrowed; the number must not be."""
        self.assertNotEqual(server.SHARED_LOGBOOK_TTL_SECONDS, 3600)

    def test_the_reason_it_is_not_permanent_is_beside_the_value(self):
        """The next person to see a 90-day TTL on a compliance link will ask
        why it is not permanent. Anchored on the constant, so the prose cannot
        drift to a different part of the file."""
        i = _SRC.index("SHARED_LOGBOOK_TTL_SECONDS = ")
        above = _SRC[max(0, i - 2600):i]
        self.assertIn("THE LINK KEEPS WORKING AND", above)
        self.assertIn("forwards", above.lower())
        self.assertIn("EXPIRY IS ENFORCED BY DELETION", above)


class TheTokenIsTheAuthAndItsPayloadIsAnId(unittest.TestCase):

    def test_the_row_holds_a_logbook_id_not_an_r2_key(self):
        i = _SRC.index("async def _mint_logbook_share_token(")
        j = _SRC.index("async def _resolve_logbook_share_token(")
        body = _SRC[i:j]
        self.assertIn('"logbook_id": str(logbook_id)', body)
        self.assertNotIn("r2_key", body)

    def test_it_is_a_SEPARATE_collection_from_temp_media(self):
        """A token that leaks from one must not address the other."""
        i = _SRC.index("async def _mint_logbook_share_token(")
        j = _SRC.index("def _public_logbook_url(")
        self.assertIn("db.logbook_share_tokens", _SRC[i:j])
        self.assertNotIn("db.temp_media_tokens", _SRC[i:j])

    def test_the_id_comes_from_the_ROW_not_the_url(self):
        i = _SRC.index("async def public_logbook_pdf(")
        j = _SRC.index("\n@", i + 10) if "\n@" in _SRC[i:] else len(_SRC)
        body = _SRC[i:j]
        self.assertIn('row.get("logbook_id")', body)

    def test_the_ttl_index_is_created(self):
        i = _SRC.index("async def _mint_logbook_share_token(")
        j = _SRC.index("async def _resolve_logbook_share_token(")
        self.assertIn("expireAfterSeconds=0", _SRC[i:j])


class _Rows:
    """One collection, driven by the test."""

    def __init__(self, row=None):
        self.row = row
        self.inserted = []
        self.queries = []

    async def find_one(self, query, projection=None):
        self.queries.append(query)
        return self.row

    async def insert_one(self, doc):
        self.inserted.append(doc)

    async def create_index(self, *a, **k):
        return None


class TheResolverRefusesExpiredAndUnknown(unittest.TestCase):
    """RUN, NOT READ. The index deletes rows on its own schedule; this is the
    half that does not depend on when the sweep last ran."""

    def setUp(self):
        self._db = server.db

    def tearDown(self):
        server.db = self._db

    def _resolve(self, row):
        class _DB:
            logbook_share_tokens = _Rows(row)
        server.db = _DB()
        return asyncio.run(server._resolve_logbook_share_token("tok"))

    def _row(self, delta):
        return {"token": "tok", "logbook_id": "lb1",
                "expires_at": datetime.now(timezone.utc) + delta}

    def test_a_live_token_resolves(self):
        self.assertIsNotNone(self._resolve(self._row(timedelta(days=1))))

    def test_an_expired_token_does_not(self):
        """Up to a minute can pass between expiry and the TTL sweep. A
        resolver that trusts the sweep returns a grant that has ended."""
        self.assertIsNone(self._resolve(self._row(timedelta(seconds=-1))))

    def test_one_second_before_expiry_still_works(self):
        self.assertIsNotNone(self._resolve(self._row(timedelta(seconds=1))))

    def test_an_unknown_token_does_not(self):
        self.assertIsNone(self._resolve(None))

    def test_a_naive_datetime_is_read_as_utc(self):
        """Mongo returns naive datetimes. Comparing one to an aware `now`
        raises, and an exception here would 500 the read rather than refuse
        it."""
        naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        self.assertIsNone(self._resolve(
            {"token": "tok", "logbook_id": "lb1", "expires_at": naive}))

    def test_a_row_with_no_expiry_is_not_refused_by_this_function(self):
        """The index is what removes it. This function refuses what it can
        JUDGE; an absent field is not evidence of expiry."""
        self.assertIsNotNone(self._resolve({"token": "tok", "logbook_id": "lb1"}))


class UnknownAndExpiredGiveTheSameAnswer(unittest.TestCase):
    """Distinguishing them tells the holder of a guessed token that it was
    once real."""

    def setUp(self):
        self._db = server.db

    def tearDown(self):
        server.db = self._db

    def test_both_are_404_with_one_message(self):
        class _DB:
            logbook_share_tokens = _Rows(None)
        server.db = _DB()
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(server.public_logbook_pdf("nope"))
        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(cm.exception.detail, "Not found or expired")

    def test_a_deleted_logbook_gives_the_SAME_answer(self):
        """A token whose record was deleted must not read differently from one
        that never existed."""
        i = _SRC.index("async def public_logbook_pdf(")
        body = _SRC[i:i + 2200]
        self.assertEqual(body.count('detail="Not found or expired"'), 2)
        self.assertIn('"is_deleted": {"$ne": True}', body)


class EveryFetchIsRecorded(unittest.TestCase):

    def test_a_read_is_written_before_the_render(self):
        """A fetch that fails to render is still a fetch. What matters is that
        the door opened, not that the PDF came back."""
        i = _SRC.index("async def public_logbook_pdf(")
        body = _SRC[i:i + 2600]
        self.assertIn("db.logbook_share_reads.insert_one", body)
        self.assertLess(body.index("logbook_share_reads"),
                        body.index("generate_single_logbook_html"))

    def test_it_records_what_was_read_and_when(self):
        i = _SRC.index("db.logbook_share_reads.insert_one")
        body = _SRC[i:i + 700]
        for field in ("logbook_id", "project_id", "log_type", "date", "read_at"):
            self.assertIn(f'"{field}"', body)

    def test_it_never_raises(self):
        """An audit write that can 500 the read turns a logging feature into
        an availability risk on somebody else's document."""
        i = _SRC.index("db.logbook_share_reads.insert_one")
        self.assertIn("except Exception", _SRC[i:i + 600])

    def test_no_ip_and_no_user_agent(self):
        """Neither identifies anyone here, and both are personal data on a
        record about a construction site."""
        i = _SRC.index("db.logbook_share_reads.insert_one")
        body = _SRC[i:i + 700]
        for banned in ("ip_address", "user_agent", "remote_addr"):
            self.assertNotIn(banned, body)


class TheMinterFailsSoftly(unittest.TestCase):
    """It runs while a report is being rendered for email. A failed insert
    costs the reader one button, not the document."""

    def setUp(self):
        self._db = server.db

    def tearDown(self):
        server.db = self._db

    def test_a_broken_insert_returns_None_rather_than_raising(self):
        class _Broken:
            async def insert_one(self, doc):
                raise RuntimeError("mongo is down")

            async def create_index(self, *a, **k):
                return None

        class _DB:
            logbook_share_tokens = _Broken()
        server.db = _DB()
        self.assertIsNone(asyncio.run(server._mint_logbook_share_token("lb1")))

    def test_a_good_insert_returns_an_opaque_token(self):
        rows = _Rows()

        class _DB:
            logbook_share_tokens = rows
        server.db = _DB()
        tok = asyncio.run(server._mint_logbook_share_token("lb1"))
        self.assertIsInstance(tok, str)
        self.assertGreaterEqual(len(tok), 24)
        self.assertNotIn("lb1", tok, "the token must not encode the id it maps")
        doc = rows.inserted[0]
        self.assertEqual(doc["logbook_id"], "lb1")
        delta = doc["expires_at"] - doc["created_at"]
        self.assertEqual(int(delta.total_seconds()), server.SHARED_LOGBOOK_TTL_SECONDS)


class TheAuthenticatedRouteIsUNCHANGED(unittest.TestCase):
    """This adds a door; it does not widen the existing one."""

    def test_the_per_logbook_pdf_still_requires_a_user(self):
        i = _SRC.index("async def get_single_logbook_pdf(")
        self.assertIn("Depends(get_current_user)", _SRC[i:i + 200])

    def test_and_the_public_url_helper_points_at_the_new_route(self):
        self.assertEqual(server._public_logbook_url("TOK"),
                         "https://api.levelog.com/api/public/logbook/TOK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
