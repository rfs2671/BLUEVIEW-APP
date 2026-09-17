"""THE WARNING NAMED A FACT IT DID NOT MEASURE.

── WHAT PRODUCTION HELD, MEASURED BEFORE THIS WAS WRITTEN ──────────────────

    dob_superintendent_number   '32299'        the operator DID save it
    dob_registration_expiry     '07/212029'    saved, and unparseable
    superintendent_licence_state -> {'state': 'unknown', ...}

and `roleVocabulary.js` renders `state === 'unknown'` as the words "No DOB
registration recorded". THE NUMBER IS RECORDED. The operator typed it, the save
landed, and the screen went on telling him it had not -- because
`superintendent_licence_state` read `dob_registration_expiry` and nothing else,
then reported its verdict in a sentence about the NUMBER.

── THREE DEFECTS, AND THEY ARE GENUINELY THREE ─────────────────────────────

  1. THE WARNING READS THE EXPIRY, NEVER THE NUMBER. A function that measures
     one field must not return a verdict about another. `number` and
     `registered` are now part of the answer, so the sentence has something
     true to be about.

  2. '07/212029' IS A TYPO NOTHING CAUGHT -- a missing slash in '07/21/2029'.
     The parser wants ISO; the form posted free text; the save succeeded. FROM
     THE DEVICE THAT IS INDISTINGUISHABLE FROM THE SAVE FAILING, which is why
     the operator saved it twice. The refusal now happens at the point of
     typing (the shared date field; frontend/src/utils/dateEntry.js, which
     replaced roleVocabulary.licenceExpiryError) AND at the write, because a
     client-side validator is a courtesy and not a gate.

  3. AN UNPARSEABLE DATE WAS SILENTLY IDENTICAL TO AN ABSENT ONE. The old
     docstring called that deliberate, and for DISPLAY it was sound. What it
     cost is discovery: a typo and an empty field produced the same state, so
     nothing anywhere -- no badge, no report, no query -- could find the row
     and say "somebody typed this and it did not take". LICENCE_UNREADABLE is
     that sentence.

── AND THE FALLBACK, WHICH IS THE "ONE FIELD, READ" HALF ───────────────────

The ruling: the warning clears if the user field OR an active `cs_registrations`
row carries a licence number. THE NAMING TRAP IS MEASURED AND IT IS REAL --
the registration row spells it `license_number` (US) and `is_active`; the user
document spells it `dob_superintendent_number`. Three names for two facts. A
filter written against `active` rather than `is_active` matches EVERY row,
including the soft-deleted ones, and silently. Asserted by name below.

NO BACKFILL IS TESTED HERE BECAUSE THE RULED BACKFILL IS A NO-OP: the user
field already holds 32299. There is nothing to write and this suite does not
pretend there is.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402

TODAY = date(2026, 9, 17)

#: Michael, exactly as production holds him.
MICHAEL = {
    "_id": "su1", "id": "su1", "name": "Michael Cespedes",
    "role": "superintendent", "company_id": "c1",
    "dob_superintendent_number": "32299",
    "dob_registration_expiry": "07/212029",
}


class ADateNobodyCanReadIsNotAnAbsentOne(unittest.TestCase):
    """DEFECT 3. Both produced `unknown`; they are different sentences."""

    def test_an_unparseable_expiry_reads_as_unreadable(self):
        got = server.superintendent_licence_state(MICHAEL, TODAY)
        self.assertEqual(got["state"], server.LICENCE_UNREADABLE)

    def test_and_it_hands_back_what_was_actually_stored(self):
        """So the admin can SEE the typo. A state name with no value attached
        tells him something is wrong and not what."""
        got = server.superintendent_licence_state(MICHAEL, TODAY)
        self.assertEqual(got["expires_on"], "07/212029")

    def test_an_absent_expiry_is_still_unknown_and_not_unreadable(self):
        doc = {"role": "superintendent", "dob_superintendent_number": "32299"}
        self.assertEqual(
            server.superintendent_licence_state(doc, TODAY)["state"],
            server.LICENCE_UNKNOWN)

    def test_the_two_states_are_different_strings(self):
        self.assertNotEqual(server.LICENCE_UNKNOWN, server.LICENCE_UNREADABLE)

    def test_a_readable_expiry_is_unaffected_in_all_three_directions(self):
        """THE REGRESSION GUARD. Splitting the unknown case must not move the
        three verdicts that were already right."""
        base = {"role": "superintendent", "dob_superintendent_number": "32299"}
        cases = {
            "2029-07-21": server.LICENCE_OK,
            "2026-10-01": server.LICENCE_EXPIRING,
            "2026-09-17": server.LICENCE_EXPIRING,   # lapses today
            "2026-09-16": server.LICENCE_EXPIRED,
        }
        for raw, want in cases.items():
            got = server.superintendent_licence_state({**base, "dob_registration_expiry": raw}, TODAY)
            self.assertEqual(got["state"], want, raw)


class TheVerdictCarriesTheNumberItIsAbout(unittest.TestCase):
    """DEFECT 1. The sentence on screen is about the registration NUMBER, so
    the number has to be in the answer the sentence is drawn from."""

    def test_michael_reads_as_registered(self):
        got = server.superintendent_licence_state(MICHAEL, TODAY)
        self.assertTrue(got["registered"])
        self.assertEqual(got["number"], "32299")

    def test_an_account_with_no_number_reads_as_not_registered(self):
        doc = {"role": "superintendent", "dob_registration_expiry": "2029-07-21"}
        got = server.superintendent_licence_state(doc, TODAY)
        self.assertFalse(got["registered"])
        self.assertIsNone(got["number"])

    def test_a_blank_number_is_not_a_number(self):
        """The absent/null/"" collapse this file documents elsewhere. A form
        posting "" for a field nobody filled must not read as recorded."""
        for blank in ("", "   ", None):
            doc = {"role": "superintendent", "dob_superintendent_number": blank}
            self.assertFalse(
                server.superintendent_licence_state(doc, TODAY)["registered"],
                repr(blank))

    def test_a_registration_row_supplies_the_number_when_the_field_is_empty(self):
        """THE RULED FALLBACK. One fact, two places it can be written; the
        warning clears on either."""
        doc = {"role": "superintendent"}
        got = server.superintendent_licence_state(doc, TODAY, "32299")
        self.assertTrue(got["registered"])
        self.assertEqual(got["number"], "32299")

    def test_the_user_field_wins_when_both_are_present(self):
        """Not an arbitrary choice: the user document is where the ruling says
        the licence lives, and the registration row is a copy taken at the time
        it was made."""
        got = server.superintendent_licence_state(MICHAEL, TODAY, "99999")
        self.assertEqual(got["number"], "32299")


class TheListReadsTheRegistrationsWithTheRightFieldNames(unittest.TestCase):
    """THE NAMING TRAP, MEASURED. `is_active` and `license_number` on the row;
    `dob_superintendent_number` on the user. A filter on `active` matches every
    row silently, soft-deleted ones included."""

    def setUp(self):
        self.seen = []
        rows = [
            # Michael's live row. license_number, US spelling.
            {"user_id": "su1", "project_id": "p1", "is_active": True,
             "license_number": "32299"},
            # A retired row for somebody else. `is_active: False` -- a query
            # written against `active` would take this as live.
            {"user_id": "su2", "project_id": "p1", "is_active": False,
             "license_number": "11111"},
        ]
        seen = self.seen

        class _Cursor:
            def __init__(self, r):
                self.r = r

            async def to_list(self, n):
                return self.r[:n]

        def _match(doc, q):
            for k, cond in q.items():
                if k == "$or":
                    if not any(_match(doc, c) for c in cond):
                        return False
                    continue
                v = doc.get(k)
                if isinstance(cond, dict):
                    if "$ne" in cond and v == cond["$ne"]:
                        return False
                    if "$in" in cond and v not in cond["$in"]:
                        return False
                elif v != cond:
                    return False
            return True

        class _Regs:
            def find(self, query=None, projection=None):
                seen.append(query or {})
                return _Cursor([d for d in rows if _match(d, query or {})])

        class _DB:
            cs_registrations = _Regs()

        self._orig = server.db
        server.db = _DB()

    def tearDown(self):
        server.db = self._orig

    def test_it_finds_the_number_on_the_active_row(self):
        got = asyncio.run(server.licence_numbers_from_registrations(["su1"]))
        self.assertEqual(got.get("su1"), "32299")

    def test_it_asks_for_is_active_and_not_active(self):
        asyncio.run(server.licence_numbers_from_registrations(["su1"]))
        q = self.seen[0]
        self.assertIn("is_active", q)
        self.assertNotIn("active", q)
        self.assertTrue(q["is_active"])

    def test_a_retired_row_is_not_a_registration(self):
        got = asyncio.run(server.licence_numbers_from_registrations(["su2"]))
        self.assertNotIn("su2", got)

    def test_it_asks_nothing_at_all_for_an_empty_set(self):
        """A page with no superintendent missing a number must not cost a
        second round trip. The badge is drawn on the list call."""
        self.assertEqual(asyncio.run(server.licence_numbers_from_registrations([])), {})
        self.assertEqual(self.seen, [])


class AnExpiryTheParserCannotReadIsRefusedAtTheWrite(unittest.TestCase):
    """DEFECT 2, ON THE SERVER SIDE. The client refuses it at the point of
    typing; this is the gate. A save that succeeds and stores something the
    reader cannot parse is indistinguishable, from the device, from a save that
    failed -- which is why the operator typed it twice."""

    def test_the_real_typo_is_refused_by_name(self):
        with self.assertRaises(HTTPException) as cm:
            server.assert_licence_expiry("07/212029")
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("YYYY-MM-DD", str(cm.exception.detail))

    def test_an_iso_date_passes_through_unchanged(self):
        self.assertEqual(server.assert_licence_expiry("2029-07-21"), "2029-07-21")

    def test_a_date_that_is_not_on_the_calendar_is_refused(self):
        for raw in ("2029-02-30", "2029-13-01", "2029-00-10"):
            with self.assertRaises(HTTPException, msg=raw):
                server.assert_licence_expiry(raw)

    def test_blank_is_not_an_error_it_is_an_absence(self):
        """An admin who left it empty has not made a mistake; he has recorded
        nothing, and the badge says so in its own words."""
        for blank in ("", "   ", None):
            self.assertIsNone(server.assert_licence_expiry(blank))

    def test_the_refusal_does_not_reach_a_role_that_has_no_licence(self):
        """THE ORDERING, PINNED. `update_admin_user` DROPS the licence fields
        for every role but superintendent, so validating the expiry before that
        branch would 422 an admin who was editing a CP's NAME — a refusal about
        a value that was never going to be stored. Read off the source because
        the two statements' ORDER is the whole property, and a behavioural test
        of it needs the whole route stood up."""
        from tests.source_text import strip_python
        code = strip_python(inspect.getsource(server.update_admin_user))
        drop = code.index("_unset_licence = {")
        check = code.index("assert_licence_expiry(")
        self.assertGreater(
            check, drop,
            "the expiry is validated before the fields are dropped, so a "
            "non-superintendent edit can be refused over a field it discards")

    def test_the_server_accepts_exactly_what_it_can_read_back(self):
        """THE IDENTITY, not two lists. Anything the validator admits must
        produce a dated verdict, never LICENCE_UNREADABLE -- otherwise the gate
        and the reader disagree and a value slips between them."""
        for raw in ("2029-07-21", "2026-02-29", "2024-02-29", "2027-12-31"):
            try:
                kept = server.assert_licence_expiry(raw)
            except HTTPException:
                kept = None
            if kept is None:
                continue
            got = server.superintendent_licence_state(
                {"dob_superintendent_number": "1", "dob_registration_expiry": kept},
                TODAY)
            self.assertNotEqual(got["state"], server.LICENCE_UNREADABLE, raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
