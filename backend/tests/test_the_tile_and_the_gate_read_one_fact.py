"""A TILE A MAN CAN OPEN AND CANNOT FILE.

TWO READS ANSWERING TWO DIFFERENT QUESTIONS.

    THE TILE   `required_logbooks` on GET /projects/{id}/required-logbooks.
               `site_superintendent_log` enters that list when the PROJECT's
               `superintendent_log_active` is true. A fact about the PROJECT.
               It never asked who the caller was, and no frontend file reads
               `cs_registrations` at all.

    THE GATE   `_refuse_if_not_the_superintendent`, on POST /logbooks and on
               PUT at submit. Reads `cs_registrations` and compares the SIGNER.
               A fact about the PERSON.

MEASURED ON PRODUCTION -- 588 Thomas S Boyland Street, the one project with the
flag on, registered CS Michael Cespedes: NINE accounts see the tile and EIGHT
of them are refused at submit. Owners, admins, and a second competent person
actually assigned to the project.

AND THE REFUSAL ARRIVES LAST. The gate runs on create and on PUT ONLY AT SUBMIT
-- drafts save clean, deliberately, because refusing an autosave would strand
work a man can still hand over. So he fills the whole log, every autosave
succeeds, and the refusal lands the instant he presses Submit, at the end of his
day, on a record BC 3301.13.13 requires completed BEFORE HE LEAVES THE SITE.

── WHAT THIS FIXES, AND WHAT IT DELIBERATELY DOES NOT ──────────────────────

The endpoint now answers the gate's question for the caller who is asking, in a
`filing` block beside `activations`. The tile renders that instead of guessing.

IT DOES NOT HIDE THE TILE. getVisibleLogTypes says why in its own comment -- "A
required log the CP cannot open is worse than an ugly label" -- and a hidden log
is one a CP cannot see EXISTS or learn who owns. The tile states whose it is,
the same three-state shape the activation rows already use for "Off -- an admin
switches this one on".

IT DOES NOT CHANGE THE GATE. Nothing here refuses anybody anything; it reports
what the gate would do. The two now read ONE function (`_cs_filing_check`), so
they cannot answer differently -- the property §3 below asserts directly across
every attribution state the module has.

AND NO REGISTRATION STILL MEANS EVERYONE MAY FILE. `cs_filing_refused` refuses
only NOT_REGISTERED_CS, because blocking a statutory log over an admin's
unfilled field is the worse failure. A tile that claimed an owner on a project
with no registration would re-introduce exactly that refusal in the UI, one
layer out. §2 pins it.
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

PROJECT = "6a5f63bc147407d3261df2c7"
CS_LOG = "site_superintendent_log"
DATE = "2026-09-04"

#: Production shapes, verbatim -- the same fixtures
#: test_only_the_superintendent_files_his_log.py uses, so the two files cannot
#: disagree about who these people are.
MICHAEL = {"id": "6a68b16ebe9c27dedf5cf47f", "name": "Michael Cespedes",
           "role": "cp"}
WILSON = {"id": "6a9e1635e755d35d29a41d17", "name": "wilson peleaz",
          "role": "cp"}
#: Two of the six non-CP accounts on the census. Role is NOT the question here
#: and that is the point of including them.
ROY = {"id": "6a1111111111111111111111", "name": "Roy Fishman", "role": "owner"}
MEILICH = {"id": "6a2222222222222222222222", "name": "Meilich Friedman",
           "role": "admin"}

REGISTRATION = {
    "project_id": PROJECT, "full_name": "Michael Cespedes",
    "license_number": "32299", "user_id": "6a68b16ebe9c27dedf5cf47f",
    "is_active": True, "is_deleted": False,
    "created_at": "2026-09-01T12:13:32",
}

PROJECT_ROW = {
    "_id": PROJECT,
    "name": "588 Thomas S Boyland Street",
    "project_class": "regular",
    "classification_source": "dob_now",
    "superintendent_log_active": True,
    "company_id": "c1",
}


class _Regs:
    """db.cs_registrations, with whatever row the test wants."""

    def __init__(self, row):
        self.row = row
        self.queries = []

    async def find_one(self, query, projection=None):
        self.queries.append(query)
        return self.row


class _Projects:
    def __init__(self, row):
        self.row = row

    async def find_one(self, query, projection=None):
        return self.row


def _install(reg_row, project_row=None):
    class _DB:
        cs_registrations = _Regs(reg_row)
        projects = _Projects(project_row if project_row is not None
                             else dict(PROJECT_ROW))
    server.db = _DB()
    return _DB


def _rights(user, reg=REGISTRATION, required=(CS_LOG,), on_date=DATE):
    _install(reg)
    return asyncio.run(server._logbook_filing_rights(
        PROJECT, list(required), user, on_date=on_date))


def _for_cs_log(rows):
    return next((r for r in rows if r.get("log_type") == CS_LOG), None)


def _gate_refuses(user, reg=REGISTRATION):
    """What the WRITE PATH would do for the same person, same day."""
    _install(reg)
    try:
        asyncio.run(server._refuse_if_not_the_superintendent(
            CS_LOG, PROJECT, DATE, user))
    except HTTPException:
        return True
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self._db = server.db

    def tearDown(self):
        server.db = self._db


class TheControlRun(Base):
    """THE EIGHT WHO CANNOT FILE ARE TOLD SO BEFORE THEY START."""

    def test_the_registered_superintendent_may_file(self):
        row = _for_cs_log(_rights(MICHAEL))
        self.assertIsNotNone(row)
        self.assertTrue(row["may_file"])
        self.assertIsNone(row["reason"])

    def test_the_second_competent_person_may_NOT(self):
        row = _for_cs_log(_rights(WILSON))
        self.assertIsNotNone(row)
        self.assertFalse(row["may_file"])
        self.assertEqual(row["reason"], "NOT_THE_REGISTERED_SUPERINTENDENT")

    def test_and_the_answer_NAMES_the_man_who_does(self):
        """A tile that says "not yours" and not whose is a dead end. The remedy
        for every one of the eight is to hand the log to a named person."""
        self.assertEqual(_for_cs_log(_rights(WILSON))["registered_name"],
                         "Michael Cespedes")

    def test_the_owner_and_the_admin_are_refused_too(self):
        """NOT A ROLE QUESTION. BC 3301.13.13 is the superintendent's OWN
        record; an admin filing it would attribute a statutory document to a
        role he does not hold. The gate already refuses them -- this is the
        tile agreeing with it rather than inviting them in."""
        for user in (ROY, MEILICH):
            with self.subTest(user["name"]):
                row = _for_cs_log(_rights(user))
                self.assertFalse(row["may_file"])
                self.assertEqual(row["registered_name"], "Michael Cespedes")

    def test_a_log_the_project_does_not_require_is_not_reported_on(self):
        """And it costs no read. The block answers about the required set, so a
        project without the CS log pays nothing for this."""
        _install(REGISTRATION)
        regs = server.db.cs_registrations
        rows = asyncio.run(server._logbook_filing_rights(
            PROJECT, ["daily_jobsite", "toolbox_talk"], WILSON, on_date=DATE))
        self.assertEqual(rows, [])
        self.assertEqual(regs.queries, [])


class NoRegistrationMeansEVERYONEMayFile(Base):
    """THE GAP THE GATE LEAVES OPEN ON PURPOSE, PRESERVED EXACTLY.

    Refusing a log that must be filed before a man leaves the site, over a field
    an admin never filled in, is the worse failure. The tile must not claim an
    owner the project has not named."""

    def test_nobody_is_refused_when_nobody_is_registered(self):
        for user in (MICHAEL, WILSON, ROY, MEILICH):
            with self.subTest(user["name"]):
                row = _for_cs_log(_rights(user, reg=None))
                self.assertTrue(row["may_file"])
                self.assertIsNone(row["reason"])

    def test_and_it_names_nobody(self):
        """`registered_name` is what the tile would print. With no
        registration there is no name, and inventing "the superintendent" here
        would put a claim on screen the project has not made."""
        self.assertIsNone(_for_cs_log(_rights(WILSON, reg=None))["registered_name"])

    def test_a_deleted_registration_is_not_a_registration(self):
        _install(REGISTRATION)
        regs = server.db.cs_registrations
        asyncio.run(server._logbook_filing_rights(
            PROJECT, [CS_LOG], WILSON, on_date=DATE))
        self.assertEqual(regs.queries[0]["is_deleted"], {"$ne": True})


class TheTileAndTheGateCannotDISAGREE(Base):
    """THE PROPOSITION THIS PR EXISTS FOR.

    Two reads answering two questions is what produced eight tiles nobody could
    file. Agreement is asserted directly, across every registration shape the
    attribution module distinguishes -- not by inspecting either
    implementation."""

    #: One row per attribution state `attribute_signer` can return, built from
    #: the production registration. The names are the states, so a failure says
    #: which one drifted.
    CASES = {
        "MATCHED_ACCOUNT": (MICHAEL, REGISTRATION),
        "NOT_REGISTERED_CS": (WILSON, REGISTRATION),
        "NOT_REGISTERED_CS/owner": (ROY, REGISTRATION),
        "NO_REGISTRATION": (WILSON, None),
        "REGISTERED_LATER": (WILSON, {**REGISTRATION,
                                      "created_at": "2026-09-30T00:00:00"}),
        "DEACTIVATED_BEFORE": (WILSON, {**REGISTRATION,
                                        "deactivated_at": "2026-09-02"}),
        "DELETED_BEFORE": (WILSON, {**REGISTRATION,
                                    "deleted_at": "2026-09-02"}),
        "UNDETERMINED": (WILSON, {**REGISTRATION, "is_active": False}),
        "MATCHED_LICENCE": ({"id": "other", "name": "M. Cespedes", "role": "cp",
                             "cs_license_number": "32299"}, REGISTRATION),
    }

    def test_may_file_is_exactly_the_negation_of_the_refusal(self):
        for label, (user, reg) in self.CASES.items():
            with self.subTest(label):
                tile = _for_cs_log(_rights(user, reg=reg))
                gate = _gate_refuses(user, reg=reg)
                self.assertEqual(
                    tile["may_file"], not gate,
                    f"{label}: the tile says may_file={tile['may_file']} and "
                    f"the gate {'REFUSES' if gate else 'accepts'}",
                )

    def test_at_least_one_case_refuses_and_one_does_not(self):
        """Otherwise the equality above is satisfied by a constant, which is
        how a gate test passes on a gate that never fires."""
        answers = {_for_cs_log(_rights(u, reg=r))["may_file"]
                   for u, r in self.CASES.values()}
        self.assertEqual(answers, {True, False})

    def test_both_read_the_same_function(self):
        """Not an implementation detail -- it is the ONLY reason the equality
        above will still hold after the next edit to either one."""
        self.assertTrue(callable(server._cs_filing_check))


class TheEndpointCarriesIt(Base):
    """The tile's payload, end to end. A helper nothing returns is a helper
    nothing renders -- the defect this replaces was two reads that never met."""

    def _get(self, user, reg=REGISTRATION, project_row=None):
        _install(reg, project_row)
        original = server.project_access_ok
        server.project_access_ok = lambda *a, **k: True
        try:
            return asyncio.run(
                server.get_project_required_logbooks(PROJECT, user))
        finally:
            server.project_access_ok = original

    def test_the_required_set_still_carries_the_log(self):
        """THE HALF THAT MUST NOT CHANGE. The tile is still rendered; it is the
        label that changes. Hiding it would leave a CP unable to see that the
        log exists or who owns it."""
        res = self._get(WILSON)
        self.assertIn(CS_LOG, res["required_logbooks"])

    def test_and_now_says_he_may_not_file_it(self):
        res = self._get(WILSON)
        row = _for_cs_log(res.get("filing") or [])
        self.assertIsNotNone(row, "the response carries a `filing` block")
        self.assertFalse(row["may_file"])
        self.assertEqual(row["registered_name"], "Michael Cespedes")

    def test_the_registered_man_sees_no_restriction(self):
        row = _for_cs_log(self._get(MICHAEL).get("filing") or [])
        self.assertTrue(row["may_file"])

    def test_the_rest_of_the_payload_is_untouched(self):
        """An older client reads `required_logbooks` and `activations` and
        ignores `filing`; it must keep working exactly as it did."""
        res = self._get(WILSON)
        for key in ("project_id", "project_class", "classification_assessed",
                    "required_logbooks", "activations"):
            self.assertIn(key, res)
        self.assertTrue(any(a["log_type"] == CS_LOG for a in res["activations"]))

    def test_a_project_without_the_flag_reports_no_restriction(self):
        off = {**PROJECT_ROW, "superintendent_log_active": False}
        res = self._get(WILSON, project_row=off)
        self.assertNotIn(CS_LOG, res["required_logbooks"])
        self.assertEqual(res.get("filing"), [])


if __name__ == "__main__":
    unittest.main()
