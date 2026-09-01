"""A REFUSAL IS RECORDED, AND IT CAN NEVER READ AS A CONSENT.

── WHY IT IS RECORDED AT ALL ────────────────────────────────────────────────

"He was asked on the 2nd and said no" is a different statement from "no consent
on file" -- which is also what an admin who never sent the invitation produces.
Nothing could tell them apart, and the person the difference describes is the
one whose signature is missing from a BC 3301.13.13 log.

── THE FAILURE THIS FILE EXISTS TO PREVENT ──────────────────────────────────

`latest_esra_consent` returns the newest row in `esra_consents` and EVERY
CALLER TREATS A ROW AS A CONSENT -- `has_consented` is literally `bool(row)`.
Writing a decline into that collection would therefore make a refusal read as
an agreement: exactly the direction its own docstring says cannot be undone,
because "an entry signed without consent cannot be retroactively consented to".

So declines go to `esra_consent_declines`, and the consent read path is
byte-identical to before the endpoint existed. That separation is the whole
safety argument, so it is asserted from both sides.

── AND THE WORDING IS STORED VERBATIM ───────────────────────────────────────

Same rule as the agreement, for the same reason: if the text later changes, a
refusal naming only a version pointer would resolve to words he was never
shown. What he declined is as much part of the record as what someone else
accepted.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, field, direction=-1):
        # REALLY SORTS. A double whose sort() returned self unchanged once
        # passed a determinism assertion on this project -- the assertion
        # tested the fake, not the code.
        self._rows = sorted(
            self._rows, key=lambda r: str(r.get(field) or ""),
            reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return list(self._rows)[:n]


class _Coll:
    def __init__(self, rows=None, boom=False):
        self.rows = list(rows or [])
        self.boom = boom
        self.inserted = []

    def find(self, query):
        if self.boom:
            raise RuntimeError("mongo down")
        keep = [r for r in self.rows
                if r.get("user_id") == query.get("user_id")
                and not r.get("is_deleted")]
        return _Cursor(keep)

    async def insert_one(self, doc):
        self.inserted.append(doc)
        self.rows.append(doc)
        return type("R", (), {"inserted_id": "x"})()


class _DB:
    def __init__(self, consents=None, declines=None):
        self.esra_consents = consents or _Coll()
        self.esra_consent_declines = declines or _Coll()


JAN = datetime(2026, 1, 1, tzinfo=timezone.utc)


class ADeclineIsNeverAConsent(unittest.TestCase):
    def test_a_decline_row_is_not_in_the_consent_collection(self):
        """THE SEPARATION, asserted from the source. Both reads name their own
        collection and neither names the other's."""
        i = SRC.index("async def latest_esra_consent(")
        consent_fn = SRC[i:SRC.index("\nasync def", i + 10)]
        self.assertIn("esra_consents", consent_fn)
        self.assertNotIn("esra_consent_declines", consent_fn)

        j = SRC.index("async def latest_esra_decline(")
        decline_fn = SRC[j:SRC.index("\nasync def", j + 10)]
        self.assertIn("esra_consent_declines", decline_fn)

    def test_a_declined_user_still_reads_as_NOT_consented(self):
        """RUN, NOT READ. The property is behavioural: a decline on file must
        leave has_current_esra_consent false."""
        db = _DB(declines=_Coll([{
            "user_id": "u1", "consent_version": server.ESRA_CONSENT_VERSION,
            "consent_text": server.ESRA_CONSENT_TEXT, "declined_at": JAN,
        }]))
        self.assertIsNone(_run(server.latest_esra_consent(db, "u1")))
        self.assertFalse(_run(server.has_current_esra_consent(db, "u1")))

    def test_and_the_decline_is_readable(self):
        db = _DB(declines=_Coll([{
            "user_id": "u1", "consent_version": server.ESRA_CONSENT_VERSION,
            "declined_at": JAN, "is_deleted": False,
        }]))
        row = _run(server.latest_esra_decline(db, "u1"))
        self.assertIsNotNone(row)
        self.assertEqual(row["consent_version"], server.ESRA_CONSENT_VERSION)

    def test_a_consent_does_not_read_as_a_decline_either(self):
        db = _DB(consents=_Coll([{
            "user_id": "u1", "consent_version": server.ESRA_CONSENT_VERSION,
            "agreed_at": JAN, "is_deleted": False,
        }]))
        self.assertIsNone(_run(server.latest_esra_decline(db, "u1")))

    def test_the_newest_decline_wins(self):
        db = _DB(declines=_Coll([
            {"user_id": "u1", "declined_at": JAN, "consent_version": "old"},
            {"user_id": "u1",
             "declined_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
             "consent_version": "new"},
        ]))
        self.assertEqual(
            _run(server.latest_esra_decline(db, "u1"))["consent_version"], "new")

    def test_a_soft_deleted_decline_is_ignored(self):
        db = _DB(declines=_Coll([{
            "user_id": "u1", "declined_at": JAN, "is_deleted": True,
        }]))
        self.assertIsNone(_run(server.latest_esra_decline(db, "u1")))

    def test_another_users_decline_is_not_his(self):
        db = _DB(declines=_Coll([{"user_id": "u2", "declined_at": JAN}]))
        self.assertIsNone(_run(server.latest_esra_decline(db, "u1")))

    def test_a_failed_read_reports_NO_decline_rather_than_raising(self):
        """The opposite posture to the consent read, deliberately.

        An unreadable CONSENT must not be assumed present. An unreadable
        DECLINE must not be assumed present either -- reporting one would
        strand him behind a refusal the system cannot see. Asking again is
        recoverable; a silent permanent block is not.
        """
        self.assertIsNone(_run(server.latest_esra_decline(_DB(declines=_Coll(boom=True)), "u1")))
        self.assertIsNone(_run(server.latest_esra_decline(None, "u1")))
        self.assertIsNone(_run(server.latest_esra_decline(_DB(), "")))


class TheENDPOINTWritesWhereItSaysItDoes(unittest.TestCase):
    """THE WRITE, EXERCISED — not the readers with a hand-filled fixture.

    WHY THIS CLASS EXISTS. The behavioural tests above populate the double
    directly, so they prove the READERS keep the collections apart and say
    nothing about where the endpoint puts a row. A control run made that
    concrete: pointing the insert at `esra_consents` left every behavioural
    assertion green and was caught only by a source grep.

    A grep is the weakest thing that could hold the safety property here, so
    the endpoint is called and the collections are inspected afterwards.
    """

    class _Req:
        client = None
        headers = {}

    USER = {"id": "u1", "email": "m@test", "name": "M C", "role": "cp",
            "company_id": "c1"}

    def _call_decline(self, db):
        original = server.db
        server.db = db
        try:
            return _run(server.decline_esra_consent(
                server.EsraConsentAgree(consent_version=server.ESRA_CONSENT_VERSION),
                self._Req(), self.USER))
        finally:
            server.db = original

    def test_the_row_lands_in_the_DECLINES_collection(self):
        db = _DB()
        result = self._call_decline(db)
        self.assertTrue(result["recorded"])
        self.assertEqual(len(db.esra_consent_declines.inserted), 1)

    def test_and_NOTHING_lands_in_the_consent_collection(self):
        """THE ONE THAT MATTERS. A row in `esra_consents` is read as a consent
        by every caller, so a decline written there is an agreement."""
        db = _DB()
        self._call_decline(db)
        self.assertEqual(db.esra_consents.inserted, [],
                         "a refusal was written where consents are read from")

    def test_and_he_STILL_reads_as_not_consented_afterwards(self):
        """End to end: decline, then ask the question the signing path asks."""
        db = _DB()
        self._call_decline(db)
        self.assertFalse(_run(server.has_current_esra_consent(db, "u1")))
        self.assertIsNotNone(_run(server.latest_esra_decline(db, "u1")))

    def test_the_stored_row_carries_the_wording_verbatim(self):
        db = _DB()
        self._call_decline(db)
        doc = db.esra_consent_declines.inserted[0]
        self.assertEqual(doc["consent_text"], server.ESRA_CONSENT_TEXT)
        self.assertEqual(doc["consent_version"], server.ESRA_CONSENT_VERSION)
        self.assertIsInstance(doc["declined_at"], datetime)
        self.assertEqual(doc["user_id"], "u1")

    def test_a_stale_version_is_refused_and_writes_nothing(self):
        from fastapi import HTTPException
        db = _DB()
        original = server.db
        server.db = db
        try:
            with self.assertRaises(HTTPException) as ctx:
                _run(server.decline_esra_consent(
                    server.EsraConsentAgree(consent_version="1999-01-01.1"),
                    self._Req(), self.USER))
        finally:
            server.db = original
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(db.esra_consent_declines.inserted, [],
                         "a refusal of wording he was never shown was recorded")

    def test_declining_twice_records_BOTH(self):
        """Deliberately not idempotent. Two refusals are two facts: he was
        asked again and refused again. The agreement collapses repeats because
        the FIRST one matters; for a refusal it is the most recent."""
        db = _DB()
        self._call_decline(db)
        self._call_decline(db)
        self.assertEqual(len(db.esra_consent_declines.inserted), 2)


class TheRefusalCarriesItsOwnWording(unittest.TestCase):
    def test_the_endpoint_stores_the_text_verbatim(self):
        i = SRC.index("async def decline_esra_consent(")
        body = SRC[i:SRC.index("\n@api_router", i)]
        self.assertIn('"consent_text": ESRA_CONSENT_TEXT', body)
        self.assertIn('"consent_version": ESRA_CONSENT_VERSION', body)
        self.assertIn('"declined_at": now', body)

    def test_it_denormalises_who_declined(self):
        """The refusal must stay readable when the user row has been renamed,
        soft-deleted or moved -- same reason the agreement denormalises."""
        i = SRC.index("async def decline_esra_consent(")
        body = SRC[i:SRC.index("\n@api_router", i)]
        for field in ('"user_email"', '"user_name"', '"role_at_time"', '"company_id"'):
            self.assertIn(field, body)

    def test_the_version_is_CHECKED_not_trusted(self):
        i = SRC.index("async def decline_esra_consent(")
        body = SRC[i:SRC.index("\n@api_router", i)]
        self.assertIn("ESRA_CONSENT_VERSION_STALE", body)

    def test_the_wording_it_stores_is_the_registry_s(self):
        """Not a paraphrase living in server.py. If these ever diverge, a
        stored refusal would name text that no version resolves to."""
        from lib.esra_consent import ESRA_CONSENT_TEXT, consent_text_for
        self.assertEqual(consent_text_for(server.ESRA_CONSENT_VERSION),
                         ESRA_CONSENT_TEXT)


class ItIsNotAPermanentLock(unittest.TestCase):
    def test_declining_writes_nothing_that_bars_a_later_consent(self):
        """A one-tap permanent block would be a state the product has no exit
        from, and the agreement's own wording promises he may withdraw -- which
        only means something if he can also change his mind the other way."""
        i = SRC.index("async def decline_esra_consent(")
        body = SRC[i:SRC.index("\n@api_router", i)]
        self.assertNotIn("esra_consents", body,
                         "the decline path must not touch the consent collection")
        for banned in ("consent_blocked", "is_blocked", "locked"):
            self.assertNotIn(banned, body)

    def test_a_later_consent_is_read_normally_despite_a_decline(self):
        db = _DB(
            consents=_Coll([{
                "user_id": "u1", "consent_version": server.ESRA_CONSENT_VERSION,
                "consent_text": server.ESRA_CONSENT_TEXT,
                "agreed_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
                "is_deleted": False,
            }]),
            declines=_Coll([{"user_id": "u1", "declined_at": JAN}]),
        )
        self.assertTrue(_run(server.has_current_esra_consent(db, "u1")))


class TheCollectionIsNeverPurged(unittest.TestCase):
    def test_declines_are_on_the_never_purge_list(self):
        """A refusal is evidence about why a statutory log carries no
        signature. Listed explicitly rather than relying on its absence from
        the purge allowlist, because that absence is not a decision."""
        self.assertIn('"esra_consent_declines"', SRC)
        i = SRC.index("SOFT_DELETE_NEVER_PURGE = {")
        block = SRC[i:SRC.index("}", i)]
        self.assertIn("esra_consent_declines", block)
        self.assertIn("esra_consents", block)


if __name__ == "__main__":
    unittest.main()
