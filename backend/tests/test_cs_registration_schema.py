"""The CS card carries a REGISTRATION NUMBER, and two dates we never stored.

WHAT THE PHYSICAL CARD SAYS. A NYC construction superintendent carries a
DOB-issued card printed with a REGISTRATION NUMBER, an ISSUE date and an
EXPIRATION date. This system stored one of the three and called it a licence
number. On a BC 3301.13.13 log -- a statutory record -- the field label is part
of the record, and "licence 12345" is a claim about a credential the man does
not hold.

AN EXPIRY WE DO NOT STORE IS AN EXPIRY NOTHING CAN CHECK. safety-staff licences
have `license_expiration` and section 4 of nightly_compliance_check reads it;
worker certifications have `expiration_date` and section 5 reads it. The
superintendent -- the one person the log is ABOUT -- had neither field, so no
sweep could ever have found a lapsed registration.

── WHAT IS BEING FIXED, AND WHAT IS DELIBERATELY NOT ────────────────────────

FIXED: the stored name (`registration_number`), and two new optional dates.

NOT FIXED, ON PURPOSE:

  * NO DATA MIGRATION. Every row written before today carries `license_number`
    and no `registration_number`. Reads take EITHER; writes take the new name.
    The tests below pin both directions, because a rename that only reads the
    new name silently blanks the licence on every historical registration --
    and the place it would blank it is the attribution sentence on a filed log.

  * `license_number_normalized` KEEPS ITS NAME. It is the comparison key three
    queries run on -- the one-job conflict check, the list endpoint's conflict
    count, and superintendent_projects_for -- and it is never shown to a human.
    Renaming it is exactly the migration that is out of scope; until every row
    carries the new key, every one of those queries would need an $or and the
    one-job rule would be answering on half the data. A test below pins that it
    is still written, because dropping it is how the conflict check goes quiet.

  * NO ENFORCEMENT. An expired registration does not block anything: not the
    registration itself, not the log, not the attribution. `attribute_signer`'s
    first rule is IT NEVER BLOCKS, and whether an expired card should stop a
    filing is a product ruling the operator has not made. The last test class
    pins the absence, so adding enforcement is a deliberate act that has to
    delete a test rather than an afternoon's oversight.

Run:  python -m pytest tests/test_cs_registration_schema.py -q
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import ObjectId

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib.logbook import cs_attribution as CA  # noqa: E402

DAY = "2026-09-01"
T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)

PROJ = ObjectId("66f0a1b2c3d4e5f60718ccc3")
ADMIN = {"id": "ad1", "role": "admin", "company_id": "co1"}


# ── THE OLD SHAPE AND THE NEW SHAPE, side by side ──────────────────────────
#
# `LEGACY` is what every row in production looks like right now. `MODERN` is
# what this change writes. Nothing migrates one into the other, so both must
# read.

def LEGACY(**over):
    doc = {
        "_id": "r1", "project_id": "P1", "full_name": "Michael Cespedes",
        "license_number": "CS 12345", "license_number_normalized": "CS12345",
        "user_id": None, "is_active": True, "is_deleted": False,
        "created_at": T0,
    }
    doc.update(over)
    return doc


def MODERN(**over):
    doc = {
        "_id": "r2", "project_id": "P1", "full_name": "Michael Cespedes",
        "registration_number": "CS 12345",
        "license_number_normalized": "CS12345",
        "issue_date": "2024-03-01", "expiration_date": "2027-03-01",
        "user_id": None, "is_active": True, "is_deleted": False,
        "created_at": T0,
    }
    doc.update(over)
    return doc


# ══════════════════════════════════════════════════════════════════════════
#  1. THE NUMBER IS READ UNDER EITHER NAME
# ══════════════════════════════════════════════════════════════════════════

class TheNumberIsReadableUnderEitherName(unittest.TestCase):
    def test_the_new_name_is_read(self):
        self.assertEqual(
            CA.registration_number_of({"registration_number": "CS 12345"}),
            "CS 12345")

    def test_the_old_name_still_reads(self):
        """EVERY EXISTING ROW. Not a legacy corner -- the whole collection."""
        self.assertEqual(
            CA.registration_number_of({"license_number": "CS 12345"}),
            "CS 12345")

    def test_the_new_name_wins_when_both_are_present(self):
        self.assertEqual(
            CA.registration_number_of(
                {"registration_number": "NEW", "license_number": "OLD"}),
            "NEW")

    def test_an_empty_new_name_falls_through_to_the_old_one(self):
        """A blank is not an answer. `"" or x` must reach x, not stop at ""."""
        self.assertEqual(
            CA.registration_number_of(
                {"registration_number": "", "license_number": "OLD"}),
            "OLD")

    def test_neither_is_the_empty_string_not_a_crash(self):
        self.assertEqual(CA.registration_number_of({}), "")
        self.assertEqual(CA.registration_number_of(None), "")


# ══════════════════════════════════════════════════════════════════════════
#  2. ATTRIBUTION READS BOTH SHAPES
# ══════════════════════════════════════════════════════════════════════════

SIGNER = {"id": "u9", "name": "M Rivera", "cs_license_number": "CS12345"}


class AttributionReadsBothShapes(unittest.TestCase):
    def test_a_modern_registration_still_matches_on_the_number(self):
        """PRE-FIX: NOT_REGISTERED_CS.

        attribute_signer reads registration["license_number"] only. A row
        written under the new name has none, so the corroborating match cannot
        fire and the filed log prints "the superintendent registered for this
        project is recorded under another name" about the man who IS it.
        """
        r = CA.attribute_signer(SIGNER, MODERN(), DAY)
        self.assertEqual(r["state"], CA.MATCHED_LICENCE)

    def test_a_modern_registration_reports_the_number_it_matched(self):
        r = CA.attribute_signer(SIGNER, MODERN(), DAY)
        self.assertEqual(r["registered_licence"], "CS 12345")

    def test_a_legacy_registration_is_untouched(self):
        """THE REGRESSION GUARD. Nothing migrates; this must never stop."""
        r = CA.attribute_signer(SIGNER, LEGACY(), DAY)
        self.assertEqual(r["state"], CA.MATCHED_LICENCE)
        self.assertEqual(r["registered_licence"], "CS 12345")

    def test_a_modern_mismatch_still_names_the_registered_number(self):
        r = CA.attribute_signer({"id": "zz", "name": "K Other"}, MODERN(), DAY)
        self.assertEqual(r["state"], CA.NOT_REGISTERED_CS)
        self.assertEqual(r["registered_licence"], "CS 12345")

    def test_the_account_link_is_unaffected_by_the_rename(self):
        """#336's strong link does not go through the number at all."""
        r = CA.attribute_signer({"id": "u1", "name": "M"},
                                MODERN(user_id="u1"), DAY)
        self.assertEqual(r["state"], CA.MATCHED_ACCOUNT)


class TheSentenceCallsItARegistration(unittest.TestCase):
    """THE FIELD LABEL IS PART OF THE RECORD.

    This sentence is printed onto the BC 3301.13.13 log by
    _superintendent_log_html, in both renderers. Calling the number a licence
    there states something about the man's credentials that his card does not.
    """

    def test_a_match_prints_the_registration_number(self):
        s = CA.attribution_sentence(CA.attribute_signer(SIGNER, MODERN(), DAY))
        self.assertIn("registration CS 12345", s)
        self.assertNotIn("licence CS 12345", s)

    def test_a_match_says_it_matched_by_registration_number(self):
        s = CA.attribution_sentence(CA.attribute_signer(SIGNER, MODERN(), DAY))
        self.assertIn("registration number", s)

    def test_the_legacy_shape_prints_the_same_sentence(self):
        modern = CA.attribution_sentence(
            CA.attribute_signer(SIGNER, MODERN(), DAY))
        legacy = CA.attribution_sentence(
            CA.attribute_signer(SIGNER, LEGACY(), DAY))
        self.assertEqual(modern, legacy)

    def test_it_is_still_a_fact_and_not_an_accusation(self):
        s = CA.attribution_sentence(
            CA.attribute_signer({"id": "zz", "name": "K Other"}, MODERN(), DAY))
        for accusation in ("not authorised", "invalid", "unauthorized",
                           "should not", "expired", "violation"):
            self.assertNotIn(accusation, s.lower())


# ══════════════════════════════════════════════════════════════════════════
#  3. THE MODELS
# ══════════════════════════════════════════════════════════════════════════

class TheCreateModelTakesTheCardsOwnFields(unittest.TestCase):
    def test_registration_number_alone_is_enough(self):
        """PRE-FIX: ValidationError, license_number is required."""
        m = server.CSRegistrationCreate(
            project_id="P1", full_name="M C", registration_number="CS 12345")
        self.assertEqual(m.registration_number, "CS 12345")

    def test_the_legacy_field_name_is_still_accepted(self):
        """An OTA client in the field posts license_number. It must work."""
        m = server.CSRegistrationCreate(
            project_id="P1", full_name="M C", license_number="CS 12345")
        self.assertEqual(m.license_number, "CS 12345")

    def test_neither_is_refused(self):
        """Optional on the model must not mean optional on the record."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            server.CSRegistrationCreate(project_id="P1", full_name="M C")

    def test_a_blank_number_is_refused(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            server.CSRegistrationCreate(
                project_id="P1", full_name="M C", registration_number="   ")

    def test_the_two_dates_are_carried(self):
        """PRE-FIX: AttributeError -- BaseModel drops what it does not declare."""
        m = server.CSRegistrationCreate(
            project_id="P1", full_name="M C", registration_number="CS 12345",
            issue_date="2024-03-01", expiration_date="2027-03-01")
        self.assertEqual(m.issue_date, "2024-03-01")
        self.assertEqual(m.expiration_date, "2027-03-01")

    def test_the_dates_are_optional(self):
        """EXISTING RECORDS STAY VALID. A card whose dates nobody typed is
        still a registration; requiring them would refuse every re-save."""
        m = server.CSRegistrationCreate(
            project_id="P1", full_name="M C", registration_number="CS 12345")
        self.assertIsNone(m.issue_date)
        self.assertIsNone(m.expiration_date)

    def test_a_malformed_date_is_refused(self):
        """`license_number` IS SUPPLIED HERE ON PURPOSE.

        Pre-fix, omitting it raises ValidationError for the missing licence and
        the assertion passes without ever exercising a date. Supplying it makes
        the model valid pre-fix, so this fails until the date rule exists.
        """
        from pydantic import ValidationError
        for bad in ("03/01/2024", "2024-13-01", "next tuesday", "2024-02-30"):
            with self.assertRaises(ValidationError, msg=bad):
                server.CSRegistrationCreate(
                    project_id="P1", full_name="M C",
                    license_number="CS 1", expiration_date=bad)

    def test_an_unpadded_date_is_normalised_rather_than_refused(self):
        """2024-3-1 IS A DATE. It is the same day as 2024-03-01, and the whole
        point of validating here is that a later sweep can compare these as
        strings — so it is stored in one form, not refused."""
        m = server.CSRegistrationCreate(
            project_id="P1", full_name="M C", license_number="CS 1",
            issue_date="2024-3-1")
        self.assertEqual(m.issue_date, "2024-03-01")

    def test_an_expiry_before_its_issue_is_refused(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            server.CSRegistrationCreate(
                project_id="P1", full_name="M C", license_number="CS 1",
                issue_date="2027-03-01", expiration_date="2024-03-01")


class TheUpdateModelTakesThemToo(unittest.TestCase):
    def test_registration_number_is_settable(self):
        m = server.CSRegistrationUpdate(registration_number="CS 999")
        self.assertEqual(m.registration_number, "CS 999")

    def test_the_legacy_name_is_still_settable(self):
        m = server.CSRegistrationUpdate(license_number="CS 999")
        self.assertEqual(m.license_number, "CS 999")

    def test_the_dates_are_settable(self):
        m = server.CSRegistrationUpdate(
            issue_date="2024-03-01", expiration_date="2027-03-01")
        self.assertEqual(m.issue_date, "2024-03-01")
        self.assertEqual(m.expiration_date, "2027-03-01")

    def test_an_empty_update_is_still_legal(self):
        """PUT with only is_active must not trip the create model's rule."""
        m = server.CSRegistrationUpdate(is_active=False)
        self.assertIs(m.is_active, False)


class TheResponseModelCarriesThem(unittest.TestCase):
    def test_it_declares_the_new_fields(self):
        f = server.CSRegistrationResponse.model_fields
        for name in ("registration_number", "issue_date", "expiration_date"):
            self.assertIn(name, f)

    def test_it_still_declares_the_legacy_one(self):
        """Clients already in the field read `license_number`."""
        self.assertIn("license_number", server.CSRegistrationResponse.model_fields)


# ══════════════════════════════════════════════════════════════════════════
#  4. THE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════

class _Cursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, spec, *a, **k):
        for field, direction in reversed(list(spec)):
            self.docs.sort(key=lambda d: (d.get(field) is not None,
                                          str(d.get(field) or "")),
                           reverse=(direction < 0))
        return self

    async def to_list(self, *a, **k):
        return self.docs


class _Inserted:
    def __init__(self, oid):
        self.inserted_id = oid


class _Regs:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.inserted = []
        self.updates = []

    def find(self, query, *a, **k):
        return _Cursor(self.docs)

    async def find_one(self, query, *a, **k):
        for d in self.docs:
            if query.get("project_id") and d.get("project_id") != query["project_id"]:
                continue
            if query.get("is_active") is True and not d.get("is_active"):
                continue
            if query.get("_id") is not None and d.get("_id") != query["_id"]:
                continue
            return d
        return None

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return _Inserted(ObjectId())

    async def update_one(self, query, update, *a, **k):
        self.updates.append((query, update))

        class _R:
            matched_count = 1
        return _R()

    async def count_documents(self, *a, **k):
        return 0


class _Projects:
    async def find_one(self, *a, **k):
        return {"_id": PROJ, "name": "857 Prescott", "company_id": "co1"}


class _Alerts:
    def __init__(self):
        self.inserted = []

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return _Inserted(ObjectId())


class _DB:
    def __init__(self, regs=None):
        self.cs_registrations = _Regs(regs)
        self.projects = _Projects()
        self.compliance_alerts = _Alerts()


def _with_db(db, coro_factory):
    real = server.db
    server.db = db
    try:
        return asyncio.run(coro_factory())
    finally:
        server.db = real


class TheRegistrationEndpointStoresTheCard(unittest.TestCase):
    def _register(self, **kw):
        db = _DB()
        body = dict(project_id=str(PROJ), full_name="Michael Cespedes")
        body.update(kw)
        data = server.CSRegistrationCreate(**body)
        out = _with_db(db, lambda: server.register_construction_superintendent(
            data=data, admin=ADMIN))
        return db, out

    def test_it_writes_the_new_name(self):
        """PRE-FIX: the stored doc has license_number and nothing else."""
        db, _ = self._register(registration_number="CS 12345")
        doc = db.cs_registrations.inserted[0]
        self.assertEqual(doc["registration_number"], "CS 12345")

    def test_it_writes_the_two_dates(self):
        db, _ = self._register(registration_number="CS 12345",
                               issue_date="2024-03-01",
                               expiration_date="2027-03-01")
        doc = db.cs_registrations.inserted[0]
        self.assertEqual(doc["issue_date"], "2024-03-01")
        self.assertEqual(doc["expiration_date"], "2027-03-01")

    def test_absent_dates_store_as_none_not_as_empty_string(self):
        db, _ = self._register(registration_number="CS 12345")
        doc = db.cs_registrations.inserted[0]
        self.assertIsNone(doc["issue_date"])
        self.assertIsNone(doc["expiration_date"])

    def test_it_still_writes_the_comparison_key(self):
        """THE ONE-JOB RULE RUNS ON THIS FIELD.

        Three queries key on license_number_normalized and none of them is
        being migrated. Dropping it does not fail loudly -- the conflict check
        simply stops finding conflicts.
        """
        db, _ = self._register(registration_number="cs 12345")
        doc = db.cs_registrations.inserted[0]
        self.assertEqual(doc["license_number_normalized"], "CS 12345")

    def test_a_legacy_body_lands_under_the_new_name(self):
        """An old client's license_number is the same number. Store it once,
        under the name the card uses."""
        db, _ = self._register(license_number="CS 12345")
        doc = db.cs_registrations.inserted[0]
        self.assertEqual(doc["registration_number"], "CS 12345")
        self.assertEqual(doc["license_number_normalized"], "CS 12345")

    def test_the_response_carries_both_names(self):
        """NO CLIENT BREAKS. Bundles in the field read `license_number`; the
        rename is not a reason to blank the number on somebody's phone."""
        _, out = self._register(registration_number="CS 12345",
                                issue_date="2024-03-01",
                                expiration_date="2027-03-01")
        self.assertEqual(out["registration_number"], "CS 12345")
        self.assertEqual(out["license_number"], "CS 12345")
        self.assertEqual(out["issue_date"], "2024-03-01")
        self.assertEqual(out["expiration_date"], "2027-03-01")


class TheUpdateEndpointWritesTheNewName(unittest.TestCase):
    def _update(self, **kw):
        db = _DB([{"_id": "r1", "project_id": "P1"}])
        data = server.CSRegistrationUpdate(**kw)
        _with_db(db, lambda: server.update_cs_registration(
            registration_id="66f0a1b2c3d4e5f60718aaa1", data=data, admin=ADMIN))
        return db.cs_registrations.updates[0][1]["$set"]

    def test_the_new_name_sets_both_the_number_and_the_key(self):
        s = self._update(registration_number="cs 999")
        self.assertEqual(s["registration_number"], "cs 999")
        self.assertEqual(s["license_number_normalized"], "CS 999")

    def test_the_legacy_name_also_sets_the_new_field(self):
        s = self._update(license_number="cs 999")
        self.assertEqual(s["registration_number"], "cs 999")
        self.assertEqual(s["license_number_normalized"], "CS 999")

    def test_the_dates_are_written(self):
        s = self._update(issue_date="2024-03-01", expiration_date="2027-03-01")
        self.assertEqual(s["issue_date"], "2024-03-01")
        self.assertEqual(s["expiration_date"], "2027-03-01")

    def test_an_unmentioned_field_is_not_touched(self):
        """THE EXACT KEY SET, not two spot checks. A PUT carrying one field
        must not rewrite the number or either date to null."""
        s = self._update(phone="212-555-0100")
        self.assertEqual({"updated_at", "phone"}, set(s))


class TheProjectLookupReportsTheCard(unittest.TestCase):
    def _get(self, reg):
        db = _DB([reg])
        return _with_db(db, lambda: server.get_project_cs(
            project_id="P1", current_user=ADMIN, _proj=None))

    def test_a_modern_row_reports_both_names(self):
        out = self._get(MODERN())
        self.assertEqual(out["registration_number"], "CS 12345")
        self.assertEqual(out["license_number"], "CS 12345")

    def test_a_legacy_row_reports_both_names(self):
        """THE FALLBACK, AT THE ENDPOINT. Every production row is this row."""
        out = self._get(LEGACY())
        self.assertEqual(out["registration_number"], "CS 12345")
        self.assertEqual(out["license_number"], "CS 12345")

    def test_the_dates_are_reported(self):
        out = self._get(MODERN())
        self.assertEqual(out["issue_date"], "2024-03-01")
        self.assertEqual(out["expiration_date"], "2027-03-01")

    def test_a_legacy_row_reports_the_dates_as_absent(self):
        out = self._get(LEGACY())
        self.assertIsNone(out["issue_date"])
        self.assertIsNone(out["expiration_date"])


# ══════════════════════════════════════════════════════════════════════════
#  5. NOTHING BLOCKS ON AN EXPIRY -- PINNED, NOT ASSUMED
# ══════════════════════════════════════════════════════════════════════════

class AnExpiredRegistrationChangesNothing(unittest.TestCase):
    """THE PRODUCT RULING HAS NOT BEEN MADE.

    Storing the date is not deciding what to do about it. If enforcement is
    ever wanted it goes in nightly_compliance_check beside sections 4 and 5 --
    an alert, not a refusal -- and these tests are the ones that have to be
    deliberately rewritten.
    """

    YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

    def test_an_expired_card_still_registers(self):
        db = _DB()
        data = server.CSRegistrationCreate(
            project_id=str(PROJ), full_name="M C",
            registration_number="CS 12345",
            issue_date="2019-01-01", expiration_date=self.YESTERDAY)
        out = _with_db(db, lambda: server.register_construction_superintendent(
            data=data, admin=ADMIN))
        self.assertTrue(db.cs_registrations.inserted)
        self.assertIsNone(out.get("conflict_warning"))

    def test_an_expired_card_raises_no_alert(self):
        db = _DB()
        data = server.CSRegistrationCreate(
            project_id=str(PROJ), full_name="M C",
            registration_number="CS 12345", expiration_date=self.YESTERDAY)
        _with_db(db, lambda: server.register_construction_superintendent(
            data=data, admin=ADMIN))
        kinds = [str(a.get("alert_type")) for a in db.compliance_alerts.inserted]
        # EXHAUSTIVE, not two named guesses: no alert of ANY kind about the
        # registration itself is raised, so a differently-named one added later
        # still trips this.
        self.assertEqual([], [k for k in kinds if "cs_registration" in k])

    def test_an_expired_registration_still_attributes_the_signer(self):
        r = CA.attribute_signer(SIGNER, MODERN(expiration_date="2019-01-01"), DAY)
        self.assertEqual(r["state"], CA.MATCHED_LICENCE)

    def test_the_sentence_is_byte_identical_with_and_without_an_expiry(self):
        """Stronger than banning the word: the expiry changes NOTHING.

        A substring ban on "expir" would also be satisfied by a sentence that
        said "lapsed", and it bans a bare word rather than a construct.
        Equality against the same sentence built from an unexpired card leaves
        no room for a clause of any wording.
        """
        expired = CA.attribution_sentence(
            CA.attribute_signer(SIGNER, MODERN(expiration_date="2019-01-01"), DAY))
        current = CA.attribution_sentence(
            CA.attribute_signer(SIGNER, MODERN(expiration_date="2099-01-01"), DAY))
        self.assertEqual(expired, current)

    def test_the_project_lookup_still_reports_registered(self):
        db = _DB([MODERN(expiration_date="2019-01-01")])
        out = _with_db(db, lambda: server.get_project_cs(
            project_id="P1", current_user=ADMIN, _proj=None))
        self.assertIs(out["registered"], True)

    def test_the_nightly_sweep_does_not_read_the_collection(self):
        """No sweep hook exists yet, and this pins that it does not.

        When one is added it will be section 6 of nightly_compliance_check,
        reading cs_registrations.expiration_date the way section 4 reads
        safety_staff_registrations.license_expiration.
        """
        import inspect
        src = inspect.getsource(server.nightly_compliance_check)
        self.assertNotIn("cs_registrations", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
