"""Was the person who signed this log the registered CS for this project?

THE TWO RECORDS NEVER MET. `cs_registrations` holds the DOB designation --
full name, licence number, NYC.ID -- created by an ADMIN for a PROJECT. `users`
holds the account that signs. Nothing connected them, so a signature on a
BC 3301.13.13 log could not be tied to the licence that gives it weight.

IT NEVER BLOCKS. A missing registration must not stop a superintendent
recording his visit: the visit happened, and the obligation to record it does
not wait on an admin typing a form. Everything here DESCRIBES.

FOUR STATES PLUS TWO HISTORICAL ONES, and the separations are the point:

    MATCHED_ACCOUNT / MATCHED_LICENCE are kept apart because "bound to this
    account" and "two humans typed the same string" are different strengths of
    evidence. This codebase has been bitten four times by string-keyed
    identity.

    NO_REGISTRATION is not NOT_REGISTERED_CS. An absent registration is NOT
    evidence the signer is wrong; collapsing them would print a finding against
    a named superintendent because an admin never filled a form -- the shape
    that produced 285 false compliance flags.

    REGISTERED_LATER and UNDETERMINED exist because the check resolves against
    THE LOG'S OWN DATE and a registration has no validity period. Three of the
    four historical questions are answerable; the fourth says so rather than
    guessing.
"""

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

try:
    from lib.logbook import cs_attribution as CA  # noqa: E402
    from lib.logbook import superintendent_log as SL  # noqa: E402
except ImportError:  # pragma: no cover — control runs report a count
    CA = SL = None

JAN = datetime(2026, 1, 1, tzinfo=timezone.utc)
REG = {
    "full_name": "M Rivera", "license_number": "1234567",
    "license_number_normalized": "1234567", "user_id": "u1",
    "is_active": True, "created_at": JAN,
}
SIGNER = {"id": "u1", "name": "M Rivera"}


class TheStrongLinkIsTheAccount(unittest.TestCase):
    def test_a_matching_user_id_is_the_strongest_answer(self):
        r = CA.attribute_signer(SIGNER, REG, "2026-08-30")
        self.assertEqual(r["state"], CA.MATCHED_ACCOUNT)

    def test_the_licence_is_corroboration_and_is_reported_as_such(self):
        """Two humans typed the same string. Weaker than an id, and the
        document must not make the stronger claim on the weaker basis."""
        r = CA.attribute_signer(
            {"id": "u9", "name": "M Rivera", "cs_license_number": "1234567"},
            REG, "2026-08-30")
        self.assertEqual(r["state"], CA.MATCHED_LICENCE)

    def test_a_messy_licence_still_matches(self):
        """Formatting is not identity: 123-45 67 is the same licence."""
        for messy in ("123-45 67", " 1234567 ", "1234567", "12/34567"):
            r = CA.attribute_signer(
                {"id": "u9", "cs_license_number": messy}, REG, "2026-08-30")
            self.assertEqual(r["state"], CA.MATCHED_LICENCE, messy)

    def test_the_normaliser_matches_what_the_endpoint_already_stores(self):
        self.assertEqual(CA.normalise_licence("123-45 67"), "1234567")
        self.assertEqual(CA.normalise_licence(None), "")

    def test_someone_else_is_reported_as_someone_else(self):
        r = CA.attribute_signer({"id": "u9", "name": "K Other"}, REG, "2026-08-30")
        self.assertEqual(r["state"], CA.NOT_REGISTERED_CS)
        self.assertEqual(r["registered_name"], "M Rivera")


class AnAbsentRegistrationIsNotAFinding(unittest.TestCase):
    """The distinction that keeps this off the 285-false-flags path."""

    def test_no_registration_is_its_own_state(self):
        for nothing in (None, {}, "not a dict"):
            r = CA.attribute_signer(SIGNER, nothing, "2026-08-30")
            self.assertEqual(r["state"], CA.NO_REGISTRATION)

    def test_it_is_NOT_reported_as_the_wrong_person(self):
        r = CA.attribute_signer(SIGNER, None, "2026-08-30")
        self.assertNotEqual(r["state"], CA.NOT_REGISTERED_CS)

    def test_and_the_sentence_says_the_SYSTEM_has_none(self):
        """A scope statement about the app, not an accusation about the man."""
        s = CA.attribution_sentence(CA.attribute_signer(SIGNER, None, "2026-08-30"))
        self.assertIn("No construction superintendent is registered", s)
        self.assertIn("in this system", s)


class ItResolvesAgainstTheLOGS_OwnDate(unittest.TestCase):
    def test_a_registration_created_after_the_log_cannot_describe_it(self):
        """Saying "matched" here would be an anachronism."""
        r = CA.attribute_signer(SIGNER, REG, "2025-06-01")
        self.assertEqual(r["state"], CA.REGISTERED_LATER)

    def test_a_registration_deleted_before_the_log_is_no_registration(self):
        reg = dict(REG, deleted_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        r = CA.attribute_signer(SIGNER, reg, "2026-08-30")
        self.assertEqual(r["state"], CA.NO_REGISTRATION)

    def test_a_registration_deleted_AFTER_the_log_still_described_it(self):
        reg = dict(REG, deleted_at=datetime(2026, 9, 30, tzinfo=timezone.utc))
        r = CA.attribute_signer(SIGNER, reg, "2026-08-30")
        self.assertEqual(r["state"], CA.MATCHED_ACCOUNT)

    def test_a_silently_DEACTIVATED_registration_is_UNDETERMINED_not_a_match(self):
        """THE HONEST LIMIT. is_active is a CURRENT-STATE boolean and only the
        delete path stamps a timestamp, so switching a registration off erases
        when it was on. The check says it cannot tell rather than guessing."""
        r = CA.attribute_signer(SIGNER, dict(REG, is_active=False), "2026-08-30")
        self.assertEqual(r["state"], CA.UNDETERMINED)

    def test_a_TODAYS_log_is_unaffected_by_that_limit(self):
        """is_active is current, so for a log dated at or before the
        registration's creation there is nothing historical to determine."""
        r = CA.attribute_signer(SIGNER, dict(REG, is_active=False), "2026-01-01")
        self.assertNotEqual(r["state"], CA.UNDETERMINED)

    def test_it_never_reads_the_clock(self):
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(CA.attribute_signer))))
        for clock in ("now(", "utcnow", "today("):
            self.assertNotIn(clock, code)


class ItDescribesAndNeverBlocks(unittest.TestCase):
    def test_the_module_raises_nothing_and_refuses_nothing(self):
        import ast
        import inspect
        import textwrap
        for fn in (CA.attribute_signer, CA.attribution_sentence):
            code = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))
            self.assertNotIn("raise", code)
            self.assertNotIn("HTTPException", code)

    def test_the_submit_gate_does_not_consult_it(self):
        """A superintendent must never be stopped from recording his visit
        because an admin has not typed a registration."""
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.create_logbook))))
        for name in ("attribute_signer", "cs_attribution_for",
                     "NOT_REGISTERED_CS"):
            self.assertNotIn(name, code)

    def test_a_failed_read_reports_no_registration_never_a_mismatch(self):
        """An outage must not become a finding against a named person on a
        statutory record."""
        import asyncio
        from unittest.mock import MagicMock
        db = MagicMock()
        db.cs_registrations.find_one = MagicMock(side_effect=RuntimeError("down"))
        r = asyncio.run(server.cs_attribution_for(db, "p1", "2026-08-30", SIGNER))
        self.assertEqual(r["state"], CA.NO_REGISTRATION)

    def test_nothing_writes_to_the_registration(self):
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.cs_attribution_for))))
        for write in ("update_one", "insert_one", "$set", "delete_one"):
            self.assertNotIn(write, code)


class TheSentenceIsAFactNotAnAccusation(unittest.TestCase):
    def test_a_mismatch_states_who_is_registered_and_stops(self):
        s = CA.attribution_sentence(
            CA.attribute_signer({"id": "u9", "name": "K Other"}, REG, "2026-08-30"))
        self.assertIn("K Other", s)
        self.assertIn("M Rivera", s)
        for accusation in ("not authorised", "invalid", "unauthorized",
                           "should not", "error", "violation"):
            self.assertNotIn(accusation, s.lower())

    def test_a_match_says_HOW_it_matched(self):
        by_id = CA.attribution_sentence(
            CA.attribute_signer(SIGNER, REG, "2026-08-30"))
        by_lic = CA.attribution_sentence(CA.attribute_signer(
            {"id": "u9", "cs_license_number": "1234567", "name": "M R"},
            REG, "2026-08-30"))
        self.assertIn("account", by_id)
        self.assertIn("licence number", by_lic)

    def test_every_state_produces_a_sentence(self):
        for state in (CA.MATCHED_ACCOUNT, CA.MATCHED_LICENCE,
                      CA.NOT_REGISTERED_CS, CA.NO_REGISTRATION,
                      CA.REGISTERED_LATER, CA.UNDETERMINED):
            s = CA.attribution_sentence({"state": state, "signer_name": "X"})
            self.assertTrue(s and s.strip().endswith("."), state)


class ItReachesTheDocument(unittest.TestCase):
    def test_both_renderers_resolve_it(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("await cs_attribution_for("), 2)

    def test_the_sentence_sits_above_the_signature(self):
        html = server._superintendent_log_html(
            {"date": "2026-08-30",
             # A SIGNATURE IS REQUIRED FOR THIS ASSERTION TO MEAN ANYTHING:
             # render_signature_html emits nothing without one, so a fixture
             # with no ink would make an ordering test pass on an absence.
             "data": {"presence": {"printed_name": "M R",
                                   "signature": {"data": "aGk="}}}},
            attribution=CA.attribute_signer(SIGNER, REG, "2026-08-30"))
        self.assertIn("registered for this project", html)
        self.assertIn("Superintendent Signature", html)
        self.assertLess(html.index("registered for this project"),
                        html.index("Superintendent Signature"))

    def test_a_log_with_no_attribution_renders_without_the_sentence(self):
        """1a-era logs and any caller that does not resolve it must not gain a
        blank or a guess."""
        html = server._superintendent_log_html(
            {"date": "2026-08-30", "data": {"presence": {"printed_name": "M R"}}})
        self.assertNotIn("registered for this project", html)


class TheRegistrationCarriesTheLink(unittest.TestCase):
    def test_user_id_is_settable_at_creation(self):
        self.assertIn("user_id", server.CSRegistrationCreate.model_fields)

    def test_and_afterwards(self):
        """The commonest real sequence is a registration typed for DOB first
        and the account created later."""
        self.assertIn("user_id", server.CSRegistrationUpdate.model_fields)

    def test_it_is_optional_because_a_CS_may_have_no_account(self):
        self.assertIsNone(
            server.CSRegistrationCreate.model_fields["user_id"].default)

    def test_it_is_stored(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn('"user_id": (str(data.user_id).strip() or None)', src)


class ItemTwoSaysWhereItCameFrom(unittest.TestCase):
    """Retrofitting provenance onto filed records is impossible, which is why
    the flag ships before the divergence check that will read it."""

    def test_unedited_autofill_is_adopted(self):
        self.assertEqual(
            SL.item_provenance({"progress": {"summary": "x", "source": "adopted"}}),
            SL.PROVENANCE_ADOPTED)

    def test_edited_is_his_own(self):
        self.assertEqual(
            SL.item_provenance({"progress": {"summary": "x", "source": "own"}}),
            SL.PROVENANCE_OWN)

    def test_a_log_filed_before_the_flag_is_UNMARKED_not_adopted(self):
        """A record that predates the question has not answered it. Guessing
        would put a provenance on a document nobody recorded one for."""
        for legacy in ({"progress": {"summary": "x"}}, {}, None,
                       {"progress": {"summary": "x", "source": "junk"}}):
            self.assertEqual(SL.item_provenance(legacy), SL.PROVENANCE_UNMARKED)

    def test_it_reads_only_what_was_STORED(self):
        """It must not compare the text against the CP's log to decide -- that
        would make a filed document's provenance depend on a record that can
        change afterwards."""
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(SL.item_provenance))))
        self.assertNotIn("daily_jobsite", code)
        self.assertNotIn("activities", code)

    def test_the_document_prints_which_it_was(self):
        for source, expected in (("adopted", "adopted from the daily jobsite log"),
                                 ("own", "own account")):
            html = server._superintendent_log_html({
                "date": "2026-08-30",
                "data": {"presence": {"printed_name": "M R"},
                         "progress": {"summary": "formwork", "source": source}}})
            self.assertIn(expected, html)

    def test_and_prints_NOTHING_for_an_unmarked_one(self):
        html = server._superintendent_log_html({
            "date": "2026-08-30",
            "data": {"presence": {"printed_name": "M R"},
                     "progress": {"summary": "formwork"}}})
        self.assertNotIn("adopted from", html)
        self.assertNotIn("own account", html)

    def test_only_item_2_carries_provenance(self):
        """It is the ONE item that overlaps with the CP's log."""
        flagged = [i["key"] for i in SL.ITEMS if i.get("provenance")]
        self.assertEqual(flagged, ["progress"])


if __name__ == "__main__":
    unittest.main()
