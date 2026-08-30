"""The agreement to sign electronically, recorded before anything is signed.

Buildings Bulletin 2024-007 sec V.5 requires that "all involved parties must
clearly intend to sign electronically and agree to conduct transactions
electronically". Nothing in this application recorded such an agreement -- a
search returned only comments describing the worker-facing gate affirmation,
which authorises ONE captured signature on ONE day's pre-shift sheet and is not
a general consent.

WHY THIS SHIPS BEFORE THE LOG IT WAS BUILT FOR. Consent cannot be retrofitted.
If the superintendent log shipped first and this a week later, every entry
signed in between was signed without recorded consent, and no later record can
reach backwards to cover it. That ordering is the whole reason PR 1 was split.

THE TEXT IS STORED ON THE ROW, not merely its version. A version pointer alone
resolves, years later, to whatever the registry says THEN -- text the person
never saw. lib/esra_consent.py keeps every version so a row can be checked
against what it claims to have said, and `verify_stored_consent` reports which
of four ways that check can fail.

NOTHING HERE ASSERTS THE CONSENT SATISFIES ESRA. It records what a person
agreed to and when. See docs/compliance/esra-bb2024-007-compliance.md, which
states plainly that it certifies nothing.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

# TOLERATED AT IMPORT so the file still COLLECTS against a tree without the
# module. A hard import made the whole file one collection ERROR in a control
# run -- "1 error" tells you nothing about which assertions the change is
# load-bearing for. With EC as None each test fails on its own and the control
# reports a count.
try:
    from lib import esra_consent as EC  # noqa: E402
except ImportError:  # pragma: no cover
    EC = None

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
USER = {"id": "u1", "email": "cs@example.com", "name": "A Superintendent",
        "role": "superintendent", "company_id": "co_a"}


def _run(coro):
    return asyncio.run(coro)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return list(self._docs)


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.inserted = []

    def find(self, *a, **k):
        return _Cursor(self.docs)

    async def insert_one(self, doc):
        self.inserted.append(doc)
        self.docs.append(doc)
        return MagicMock(inserted_id="new")


def _db(rows=None):
    d = MagicMock()
    d.esra_consents = _Coll(rows or [])
    return d


def _request():
    r = MagicMock()
    r.client.host = "203.0.113.7"
    r.headers = {"user-agent": "LeveLog/1.3.0 (iPad)"}
    return r


# ── the registry ────────────────────────────────────────────────────────────

class TheWordingIsReproducible(unittest.TestCase):
    def test_the_current_version_resolves_to_the_current_text(self):
        self.assertEqual(EC.consent_text_for(EC.ESRA_CONSENT_VERSION),
                         EC.ESRA_CONSENT_TEXT)

    def test_every_registered_version_has_text(self):
        for v, t in EC.ESRA_CONSENT_TEXTS.items():
            self.assertTrue(t and t.strip(), v)

    def test_an_unknown_version_is_None_not_a_guess(self):
        """None is a real answer: a row written by a LATER build naming a
        version this one does not carry is newer, not corrupt."""
        self.assertIsNone(EC.consent_text_for("1999-01-01.1"))
        self.assertIsNone(EC.consent_text_for(None))
        self.assertIsNone(EC.consent_text_for(""))

    def test_the_version_is_dated_so_it_reads_without_a_lookup(self):
        v = EC.ESRA_CONSENT_VERSION
        self.assertRegex(v, r"^\d{4}-\d{2}-\d{2}\.\d+$")

    def test_only_the_current_version_is_current(self):
        self.assertTrue(EC.consent_is_current(EC.ESRA_CONSENT_VERSION))
        self.assertFalse(EC.consent_is_current("2020-01-01.1"))
        self.assertFalse(EC.consent_is_current(None))


class TheTextSaysWhatTheBulletinAsksFor(unittest.TestCase):
    """sec V.5 has two limbs and the wording must carry both, plus the two
    things a person is entitled to know before agreeing rather than after."""

    def test_it_consents_to_conducting_business_electronically(self):
        self.assertIn("do business electronically", EC.ESRA_CONSENT_TEXT)

    def test_it_states_the_intent_that_the_mark_IS_the_signature(self):
        t = EC.ESRA_CONSENT_TEXT
        self.assertIn("is my signature", t)
        self.assertIn("same effect as a signature I write", t)

    def test_it_warns_that_a_signed_record_cannot_be_edited(self):
        """True of this system, and a fact the signer is entitled to know
        BEFORE agreeing."""
        self.assertIn("cannot edit a record after I have signed", EC.ESRA_CONSENT_TEXT)

    def test_it_offers_a_copy(self):
        """A promise the software can keep -- every logbook renders to PDF."""
        self.assertIn("given a copy", EC.ESRA_CONSENT_TEXT)

    def test_it_says_how_to_withdraw(self):
        """A consent with no exit is not freely given."""
        self.assertIn("withdraw this agreement", EC.ESRA_CONSENT_TEXT)

    def test_it_claims_no_legal_effect_it_cannot_deliver(self):
        t = EC.ESRA_CONSENT_TEXT.lower()
        for overclaim in ("legally binding", "complies with", "esra",
                          "satisfies", "department of buildings"):
            self.assertNotIn(overclaim, t)


class VerifyingAStoredRow(unittest.TestCase):
    """Four ways the check can fail, and they are not the same failure."""

    def _row(self, **kw):
        base = {"consent_version": EC.ESRA_CONSENT_VERSION,
                "consent_text": EC.ESRA_CONSENT_TEXT}
        base.update(kw)
        return base

    def test_a_good_row_verifies(self):
        out = EC.verify_stored_consent(self._row())
        self.assertTrue(out["ok"])
        self.assertIsNone(out["reason"])
        self.assertTrue(out["current"])

    def test_no_row_is_MISSING(self):
        for empty in (None, {}, "not a dict"):
            self.assertEqual(EC.verify_stored_consent(empty)["reason"], "MISSING")

    def test_a_row_with_no_text_is_unverifiable_and_says_so(self):
        out = EC.verify_stored_consent(self._row(consent_text=""))
        self.assertEqual(out["reason"], "NO_TEXT")

    def test_a_version_this_build_never_carried_is_UNKNOWN_not_WRONG(self):
        """NOT a failure of the row. It reports that this build cannot check
        it, which is a different fact -- the distinction the OSHA register
        draws between "No findings" and "Not checked"."""
        out = EC.verify_stored_consent(
            self._row(consent_version="2099-01-01.1"))
        self.assertEqual(out["reason"], "UNKNOWN_VERSION")

    def test_altered_wording_is_TEXT_MISMATCH(self):
        out = EC.verify_stored_consent(
            self._row(consent_text=EC.ESRA_CONSENT_TEXT + " and also anything"))
        self.assertEqual(out["reason"], "TEXT_MISMATCH")

    def test_an_old_but_intact_row_verifies_while_not_being_current(self):
        """Both facts are reported separately, because agreeing to superseded
        wording is not the same as agreeing to nothing."""
        EC.ESRA_CONSENT_TEXTS["2020-01-01.1"] = "old wording"
        try:
            out = EC.verify_stored_consent(
                {"consent_version": "2020-01-01.1", "consent_text": "old wording"})
            self.assertTrue(out["ok"])
            self.assertFalse(out["current"])
        finally:
            EC.ESRA_CONSENT_TEXTS.pop("2020-01-01.1", None)


# ── the endpoints ───────────────────────────────────────────────────────────

class RecordingAConsent(unittest.TestCase):
    def _post(self, db, version=None, user=None):
        body = server.EsraConsentAgree(
            consent_version=version or EC.ESRA_CONSENT_VERSION)
        with patch.object(server, "db", db), \
             patch.object(server, "audit_log", _noop):
            return _run(server.agree_esra_consent(body, _request(), user or USER))

    def test_it_stores_the_wording_verbatim_not_only_the_version(self):
        db = _db()
        self._post(db)
        row = db.esra_consents.inserted[0]
        self.assertEqual(row["consent_text"], EC.ESRA_CONSENT_TEXT)
        self.assertEqual(row["consent_version"], EC.ESRA_CONSENT_VERSION)

    def test_it_records_who_agreed_and_when_and_from_where(self):
        db = _db()
        self._post(db)
        row = db.esra_consents.inserted[0]
        self.assertEqual(row["user_id"], "u1")
        self.assertEqual(row["user_email"], "cs@example.com")
        self.assertEqual(row["role_at_time"], "superintendent")
        self.assertEqual(row["company_id"], "co_a")
        self.assertIsInstance(row["agreed_at"], datetime)
        self.assertEqual(row["ip_address"], "203.0.113.7")
        self.assertIn("LeveLog", row["user_agent"])

    def test_the_identity_comes_from_the_SERVER_not_the_body(self):
        """A consent whose subject the client could choose would not be
        evidence of anything. The request model carries a version and nothing
        else."""
        self.assertEqual(set(server.EsraConsentAgree.model_fields),
                         {"consent_version"})

    def test_a_stale_version_is_refused(self):
        """A client holding older wording must not have its agreement recorded
        against text the user never saw."""
        db = _db()
        with self.assertRaises(server.HTTPException) as cm:
            self._post(db, version="2020-01-01.1")
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["code"], "ESRA_CONSENT_VERSION_STALE")
        self.assertEqual(db.esra_consents.inserted, [])

    def test_the_refusal_is_a_machine_code_never_prose(self):
        db = _db()
        with self.assertRaises(server.HTTPException) as cm:
            self._post(db, version="nope")
        self.assertIsInstance(cm.exception.detail, dict)

    def test_agreeing_twice_does_not_write_a_second_row(self):
        """Re-tapping must not multiply the record, and the ORIGINAL
        timestamp is the one that matters."""
        first = {"user_id": "u1", "consent_version": EC.ESRA_CONSENT_VERSION,
                 "consent_text": EC.ESRA_CONSENT_TEXT, "agreed_at": NOW}
        db = _db([first])
        out = self._post(db)
        self.assertFalse(out["recorded"])
        self.assertTrue(out["already"])
        self.assertEqual(db.esra_consents.inserted, [])
        self.assertEqual(out["agreed_at"], NOW.isoformat())

    def test_a_user_with_no_id_is_refused(self):
        db = _db()
        with self.assertRaises(server.HTTPException) as cm:
            self._post(db, user={"email": "x@y.z"})
        self.assertEqual(cm.exception.detail["code"], "ESRA_CONSENT_NO_SUBJECT")


class ReadingAConsent(unittest.TestCase):
    def _get(self, db, user=None):
        with patch.object(server, "db", db):
            return _run(server.get_esra_consent(user or USER))

    def test_it_returns_the_current_wording_even_with_no_consent(self):
        """So the client can show something without a second round trip."""
        out = self._get(_db())
        self.assertEqual(out["current_text"], EC.ESRA_CONSENT_TEXT)
        self.assertFalse(out["has_consented"])
        self.assertFalse(out["is_current"])
        self.assertEqual(out["verification"], "MISSING")

    def test_it_reports_a_current_consent(self):
        db = _db([{"user_id": "u1", "consent_version": EC.ESRA_CONSENT_VERSION,
                   "consent_text": EC.ESRA_CONSENT_TEXT, "agreed_at": NOW}])
        out = self._get(db)
        self.assertTrue(out["has_consented"])
        self.assertTrue(out["is_current"])
        self.assertIsNone(out["verification"])
        self.assertEqual(out["agreed_at"], NOW.isoformat())

    def test_it_separates_CONSENTED_from_CONSENTED_TO_THIS_WORDING(self):
        db = _db([{"user_id": "u1", "consent_version": "2020-01-01.1",
                   "consent_text": "old", "agreed_at": NOW}])
        out = self._get(db)
        self.assertTrue(out["has_consented"])
        self.assertFalse(out["is_current"])


class ItFailsClosed(unittest.TestCase):
    """Failing OPEN on a consent check is the one direction that cannot be
    undone: an entry signed without consent cannot be consented to later."""

    def test_a_read_failure_is_NOT_a_consent(self):
        db = MagicMock()
        db.esra_consents = MagicMock()
        db.esra_consents.find = MagicMock(side_effect=RuntimeError("mongo down"))
        self.assertIsNone(_run(server.latest_esra_consent(db, "u1")))
        self.assertFalse(_run(server.has_current_esra_consent(db, "u1")))

    def test_no_database_is_not_a_consent(self):
        self.assertFalse(_run(server.has_current_esra_consent(None, "u1")))

    def test_no_user_is_not_a_consent(self):
        self.assertFalse(_run(server.has_current_esra_consent(_db(), "")))

    def test_an_old_version_is_not_a_CURRENT_consent(self):
        db = _db([{"user_id": "u1", "consent_version": "2020-01-01.1",
                   "consent_text": "old", "agreed_at": NOW}])
        self.assertFalse(_run(server.has_current_esra_consent(db, "u1")))
        self.assertIsNotNone(_run(server.latest_esra_consent(db, "u1")))


class TheConsentOutlivesEverything(unittest.TestCase):
    def test_the_collection_is_never_purged(self):
        """A consent is evidence ABOUT a signature and outlives the signature
        it authorises."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        block = src.split("SOFT_DELETE_NEVER_PURGE = {")[1].split("}")[0]
        self.assertIn('"esra_consents"', block)

    def test_the_row_carries_identity_that_survives_the_user_record(self):
        """Denormalised on purpose: the consent must stay readable when the
        user row has been renamed, soft-deleted, or moved between companies."""
        db = _db()
        with patch.object(server, "db", db), patch.object(server, "audit_log", _noop):
            _run(server.agree_esra_consent(
                server.EsraConsentAgree(consent_version=EC.ESRA_CONSENT_VERSION),
                _request(), USER))
        row = db.esra_consents.inserted[0]
        for k in ("user_email", "user_name", "role_at_time", "company_id"):
            self.assertIn(k, row)


class TheSuperintendentRole(unittest.TestCase):
    def test_the_role_string_matches_the_one_already_in_the_file(self):
        """"superintendent", not "super". The string existed before the role
        did -- the people-directory search lists users with it -- so a second
        spelling would be the fifth name for a thing already over-named here."""
        self.assertEqual(server.ROLE_SUPERINTENDENT, "superintendent")
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn('"cp", "superintendent"', src)

    def test_it_is_recognised(self):
        self.assertTrue(server.is_superintendent({"role": "superintendent"}))
        self.assertTrue(server.is_superintendent({"role": "SUPERINTENDENT"}))
        self.assertTrue(server.is_superintendent({"role": " superintendent "}))

    def test_and_nothing_else_is(self):
        for other in ("cp", "admin", "owner", "worker", "super", "", None):
            self.assertFalse(server.is_superintendent({"role": other}), other)
        self.assertFalse(server.is_superintendent(None))

    def test_it_hard_requires_a_company_like_cp(self):
        """A user in this role without a company 403s on every company-gated
        endpoint and their session merely looks broken."""
        self.assertIn("cp", server.ROLES_REQUIRING_COMPANY)
        self.assertIn(server.ROLE_SUPERINTENDENT, server.ROLES_REQUIRING_COMPANY)

    def test_the_creation_gate_reads_the_tuple_not_a_literal(self):
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.create_admin_user))))
        self.assertIn("ROLES_REQUIRING_COMPANY", code)


async def _noop(*a, **k):
    return None


if __name__ == "__main__":
    unittest.main()
