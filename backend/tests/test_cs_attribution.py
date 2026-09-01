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

    def test_deactivated_BEFORE_the_log_means_it_was_not_active_then(self):
        r = CA.attribute_signer(
            SIGNER,
            dict(REG, is_active=False,
                 deactivated_at=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            "2026-08-30")
        self.assertEqual(r["state"], CA.NO_REGISTRATION)

    def test_deactivated_AFTER_the_log_still_described_it(self):
        """A registration retired last month does not un-describe a log signed
        while it stood."""
        r = CA.attribute_signer(
            SIGNER,
            dict(REG, is_active=False,
                 deactivated_at=datetime(2026, 10, 1, tzinfo=timezone.utc)),
            "2026-08-30")
        self.assertEqual(r["state"], CA.MATCHED_ACCOUNT)

    def test_BOTH_off_switches_stamp_a_time_so_the_question_is_answerable(self):
        """AN EARLIER VERSION OF THIS MODULE CLAIMED ONLY THE DELETE PATH
        STAMPED ONE, and documented a permanent "cannot be determined" for a
        question the data could already answer. The writers had been INFERRED
        from the model and the delete endpoint rather than ENUMERATED. This
        asserts the two that were missed."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        # supersession by a new CS, and an admin switching it off
        self.assertIn(
            '{"$set": {"is_active": False, "deactivated_at": now, "updated_at": now}}',
            src)
        self.assertIn('update["deactivated_at"] = now', src)

    def test_UNDETERMINED_survives_ONLY_for_the_pre_stamping_rump(self):
        """A row switched off before either stamper existed carries is_active
        False and no deactivated_at. The moment is unrecoverable, so the check
        says so. THAT SET CANNOT GROW."""
        r = CA.attribute_signer(SIGNER, dict(REG, is_active=False), "2026-08-30")
        self.assertEqual(r["state"], CA.UNDETERMINED)

    def test_a_TODAYS_log_is_unaffected_by_that_rump(self):
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


class TheSameQuestionAskedAtMENU_Time(unittest.IsolatedAsyncioTestCase):
    """`is_registered_cs` / `superintendent_projects_for` — the CP nav's gate.

    ONE PREDICATE, TWO CALLERS, and that is the whole design. The nav decides
    whether to offer the superintendent's log by asking `attribute_signer` --
    the same function, the same states -- so the menu and the filed document
    cannot disagree about who the superintendent is.

    WHY NOT THE ROLE. The superintendent on 588 Thomas holds a `cp` account. A
    role test hides his own statutory log from him AND offers it to every CP
    who is not a superintendent: wrong in both directions, and silent, because
    a missing nav item looks like a nav without that feature.

    AND IT ONLY EVER HIDES A SHORTCUT. The log is required on every project
    class, so the dashboard lists it and routes to it regardless. If this
    predicate is ever used to REFUSE a filing, the module's first rule -- IT
    NEVER BLOCKS -- is broken, and the reasoning that makes this safe with it.
    """

    def test_the_two_matched_states_are_the_capability(self):
        for state in (CA.MATCHED_ACCOUNT, CA.MATCHED_LICENCE):
            self.assertTrue(CA.is_registered_cs({"state": state}), state)

    def test_and_NO_REGISTRATION_IS_NOT(self):
        """Different from the read-time rule, deliberately.

        At read time an absent registration means NOTHING WAS CHECKED and must
        never print as a finding. At menu time the question is "should this be
        his primary action", and "nobody is registered" is not a yes.
        """
        for state in (CA.NO_REGISTRATION, CA.NOT_REGISTERED_CS,
                      CA.REGISTERED_LATER, CA.UNDETERMINED):
            self.assertFalse(CA.is_registered_cs({"state": state}), state)

    def test_junk_is_not_a_capability(self):
        for junk in (None, {}, {"state": None}, "matched_account", 1):
            self.assertFalse(CA.is_registered_cs(junk), repr(junk))

    # ── the I/O half ────────────────────────────────────────────────────────
    class _Cursor:
        def __init__(self, rows):
            self._rows = rows

        def sort(self, *_a, **_kw):
            # NOT `return self` WITHOUT SORTING. A double whose sort() did
            # nothing once passed a determinism assertion on this project --
            # the assertion tested the fake, not the code. This one really
            # orders, so a caller relying on the order is actually exercised.
            self._rows = sorted(
                self._rows,
                key=lambda r: (str(r.get("created_at")), str(r.get("_id"))),
                reverse=True)
            return self

        async def to_list(self, _n):
            return list(self._rows)

    class _Regs:
        def __init__(self, rows, boom=False):
            self.rows, self.boom, self.query = rows, boom, None

        def find(self, query):
            if self.boom:
                raise RuntimeError("mongo down")
            self.query = query
            ors = query.get("$or") or [{}]
            keep = [r for r in self.rows
                    if any(all(r.get(k) == v for k, v in o.items()) for o in ors)
                    and r.get("is_active") and not r.get("is_deleted")]
            return TheSameQuestionAskedAtMENU_Time._Cursor(keep)

    class _DB:
        def __init__(self, regs):
            self.cs_registrations = regs

    async def test_the_account_link_names_his_project(self):
        db = self._DB(self._Regs([dict(REG, project_id="p1")]))
        self.assertEqual(
            await server.superintendent_projects_for(db, SIGNER), ["p1"])

    async def test_a_licence_match_counts_too(self):
        db = self._DB(self._Regs([dict(REG, project_id="p1", user_id=None)]))
        got = await server.superintendent_projects_for(
            db, {"id": "u9", "cs_license_number": "123-45 67"})
        self.assertEqual(got, ["p1"], "formatting is not identity")

    async def test_somebody_elses_registration_is_not_his_capability(self):
        db = self._DB(self._Regs([dict(REG, project_id="p1")]))
        self.assertEqual(
            await server.superintendent_projects_for(db, {"id": "u9"}), [])

    async def test_a_deactivated_registration_does_not_confer_it(self):
        db = self._DB(self._Regs([
            dict(REG, project_id="p1", is_active=False,
                 deactivated_at=datetime(2026, 2, 1, tzinfo=timezone.utc)),
        ]))
        self.assertEqual(
            await server.superintendent_projects_for(db, SIGNER), [])

    async def test_a_registration_created_AFTER_today_does_not_either(self):
        db = self._DB(self._Regs([
            dict(REG, project_id="p1",
                 created_at=datetime(2099, 1, 1, tzinfo=timezone.utc)),
        ]))
        self.assertEqual(
            await server.superintendent_projects_for(db, SIGNER), [])

    async def test_an_outage_returns_NO_capability_rather_than_raising(self):
        """This runs on the session-start path. A registration lookup falling
        over must cost a menu shortcut, never a login."""
        db = self._DB(self._Regs([], boom=True))
        self.assertEqual(
            await server.superintendent_projects_for(db, SIGNER), [])

    async def test_a_principal_with_no_id_and_no_licence_queries_nothing(self):
        regs = self._Regs([dict(REG, project_id="p1")])
        self.assertEqual(
            await server.superintendent_projects_for(self._DB(regs), {}), [])
        self.assertIsNone(regs.query, "it must not query on an empty $or")

    async def test_the_query_asks_only_for_live_rows(self):
        regs = self._Regs([dict(REG, project_id="p1")])
        await server.superintendent_projects_for(self._DB(regs), SIGNER)
        self.assertEqual(regs.query.get("is_active"), True)
        self.assertEqual(regs.query.get("is_deleted"), {"$ne": True})

    async def test_two_projects_are_both_reported(self):
        """The DOB one-job rule makes this an anomaly, not an impossibility --
        and the nav must be TOLD about it rather than shown one at random, so
        it can send him to the picker instead of guessing which site he is on.
        """
        db = self._DB(self._Regs([
            dict(REG, project_id="p1", _id="a"),
            dict(REG, project_id="p2", _id="b"),
        ]))
        got = await server.superintendent_projects_for(db, SIGNER)
        self.assertEqual(sorted(got), ["p1", "p2"])

    async def test_no_db_is_no_capability(self):
        self.assertEqual(
            await server.superintendent_projects_for(None, SIGNER), [])


if __name__ == "__main__":
    unittest.main()
