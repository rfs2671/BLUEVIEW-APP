"""MICHAEL'S REGISTRATION STILL GOVERNS, WITH THE SCREEN THAT MADE ONE GONE.

Operator ruling, 2026-10-08: "OUTSIDE SUPERS: DELETE THE TAB. There is no such
case. [...] `cs_registrations` stays as the collection and stays the filing
gate. Nothing about the super log changes. [...] Existing rows untouched.
Michael's 588 registration must still govern -- assert it."

`app/admin/superintendent.jsx` is deleted. It was a CLIENT, and the thing it
called is not: POST /admin/cs-registrations, `_register_cs_on_project`, the
`cs_registrations` collection, `_refuse_if_not_the_superintendent`, the
activation gate and `cs_attribution_for` are all untouched by that removal.
THIS FILE IS THE ASSERTION THAT THEY ARE, measured from the direction that
matters: the one live registration, and whether the gate still admits the one
man who may file and still refuses everybody else.

── WHY A DELETED SCREEN NEEDS A SERVER TEST AT ALL ─────────────────────────

Because the gate and the screen were only ever connected by a collection name,
and a change that "only removes a client" is exactly the shape that takes a
server rule with it when the rule was reached through a shared helper. Nothing
here is new behaviour; every assertion below is a characterisation of what the
gate did the day before the screen went, so a later change that moves the gate
fails HERE rather than at 16:00 on a jobsite.

── THE PREMISE THE RULING GAVE, AND THE ONE CORRECTION TO IT ───────────────

The ruling's reason was "a superintendent with no account cannot file any
logbook, so recording one serves nothing". The first half holds, and for a
stronger reason than stated. `attribute_signer` has TWO ways to match a signer
and only the first consults `user_id`:

    MATCHED_ACCOUNT   signer["id"] == registration["user_id"]
    MATCHED_LICENCE   normalise_licence(signer["cs_license_number"]
                                        or signer["license_number"])
                      == registration["license_number_normalized"]

So BY RULE an unlinked row can permit a filing -- the licence branch never
looks at `user_id`. IN THIS BUILD IT CANNOT, because the signer-side licence is
read from `cs_license_number` / `license_number` while a user document stores
its licence as `dob_superintendent_number`; production carries 0 user rows with
either of the two names the branch looks for, and no code path writes them.
`SECTION 4` pins both halves of that, so the day somebody wires the fields
together it is a decision and not a surprise.

WHAT IS WRONG IS "serves nothing". An unlinked registration is not inert: it
returns NOT_REGISTERED_CS for EVERY caller, and `cs_filing_refused` refuses on
exactly that state -- so it locks BC 3301.13.13 for the whole project while
still satisfying `ACTIVATION_REQUIRES_CS_REGISTRATION`, whose read asks only
that a row exist. Deleting the only screen that could create one removes a
footgun, not a capability. `SECTION 3` is that measurement.

── THE FIXTURES ARE THE LIVE ROW, READ-ONLY, 2026-10-08 ────────────────────

One `cs_registrations` document exists platform-wide: BLUEVIEW CONSTRUCTION
INC, project 588 Thomas S Boyland Street, Michael Cespedes, licence 32299,
linked to a `superintendent`-role account whose `dob_superintendent_number` is
the same 32299. Zero unlinked rows, zero on a `cp`-role account.

HIS ROLE IS `superintendent`, NOT `cp`, AND THE NEIGHBOURING FIXTURES SAY `cp`.
test_the_tile_and_the_gate_read_one_fact.py and
test_only_the_superintendent_files_his_log.py both carry him as `role: "cp"`,
and server.py's own comments still say "the registered CS on the one live
project holds `cp`". That was true when they were written and the account has
since been changed. THOSE FILES ARE LEFT ALONE: role is not the question the
gate asks -- `_refuse_if_not_the_superintendent` says so at length -- so their
fixtures still exercise what they were written to exercise, and editing them
from here would be a sweep. The live value is used below, and `SECTION 1`
asserts the gate is indifferent to which of the two it is.
"""

from __future__ import annotations

import asyncio
import inspect
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
from lib.logbook.cs_attribution import (  # noqa: E402
    attribute_signer, cs_filing_refused,
    MATCHED_ACCOUNT, MATCHED_LICENCE, NOT_REGISTERED_CS,
)
from tests.source_text import code_of  # noqa: E402

PROJECT = "6a5f63bc147407d3261df2c7"
CS_LOG = "site_superintendent_log"
DATE = "2026-10-08"

#: The live account, as production holds it.
MICHAEL = {"id": "6a68b16ebe9c27dedf5cf47f", "name": "Michael Cespedes",
           "role": "superintendent", "company_id": "6a5e153cc7ac7a6451aa2d32",
           "dob_superintendent_number": "32299"}
#: The same person as the older fixtures carry him. SECTION 1 runs both.
MICHAEL_AS_CP = {**MICHAEL, "role": "cp"}
#: A competent person actually assigned to 588 Thomas. The gate's whole point.
WILSON = {"id": "6a9e1635e755d35d29a41d17", "name": "wilson peleaz",
          "role": "cp", "company_id": "6a5e153cc7ac7a6451aa2d32"}
#: An admin of the same company, to show the refusal is not a rank question.
MEILICH = {"id": "6a2222222222222222222222", "name": "Meilich Friedman",
           "role": "admin", "company_id": "6a5e153cc7ac7a6451aa2d32"}

#: The live row, field for field.
REGISTRATION = {
    "project_id": PROJECT,
    "full_name": "Michael Cespedes",
    "license_number": "32299",
    "license_number_normalized": "32299",
    "user_id": "6a68b16ebe9c27dedf5cf47f",
    "company_id": "6a5e153cc7ac7a6451aa2d32",
    "is_active": True,
    "is_deleted": False,
    "created_at": "2026-09-01T12:13:32",
}
#: THE SHAPE THE DELETED SCREEN COULD MAKE AND USER MANAGEMENT CANNOT.
UNLINKED = {**REGISTRATION, "user_id": None}


class _RowsCursor:
    """What `find` returns: sortable, listable, async-iterable."""

    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return list(self._rows)

    def __aiter__(self):
        async def gen():
            for r in self._rows:
                yield r
        return gen()


class _Regs:
    def __init__(self, row):
        self.row = row
        self.queries = []

    async def find_one(self, query, projection=None):
        self.queries.append(query)
        return self.row

    def find(self, query=None, projection=None, **kw):
        # THE SAME ROW, AS A LIST. The filing gate reads a project's whole
        # registration history now (the row in force on the log's date is
        # chosen from it); this fake still answers with the one row the test
        # wants, whatever the query.
        self.queries.append(query)
        return _RowsCursor([self.row] if self.row else [])


def _install(reg_row):
    class _DB:
        cs_registrations = _Regs(reg_row)
    server.db = _DB()
    return _DB.cs_registrations


def _gate_refuses(user, reg=REGISTRATION, on_date=DATE):
    """Exactly what POST /logbooks and submit-time PUT would do.

    THE REAL FUNCTION, NOT A RE-IMPLEMENTATION OF ITS RULE. A test that
    recomputed `attribute_signer` and compared would pass with the gate
    unwired, which is the one failure this file exists to catch.
    """
    _install(reg)
    try:
        asyncio.run(server._refuse_if_not_the_superintendent(
            CS_LOG, PROJECT, on_date, user))
    except HTTPException as exc:
        return exc
    return None


class Base(unittest.TestCase):
    def setUp(self):
        self._db = getattr(server, "db", None)

    def tearDown(self):
        server.db = self._db


# ── SECTION 1. THE RULING'S OWN ASSERTION ───────────────────────────────────

class MichaelStillGoverns(Base):
    """"Michael's 588 registration must still govern -- assert it.\""""

    def test_the_gate_admits_the_registered_superintendent(self):
        self.assertIsNone(
            _gate_refuses(MICHAEL),
            "the registered construction superintendent is refused his own "
            "BC 3301.13.13 log",
        )

    def test_it_admits_him_whichever_role_the_account_holds(self):
        # ROLE IS NOT THE QUESTION, and this is the assertion that says so.
        # His account was `cp` when the gate was written and is
        # `superintendent` now; a gate that had quietly become a role test
        # would still pass the test above and fail this one.
        for who in (MICHAEL, MICHAEL_AS_CP):
            with self.subTest(role=who["role"]):
                self.assertIsNone(_gate_refuses(who))

    def test_the_gate_refuses_a_caller_who_is_not_registered(self):
        # THE OTHER HALF, AND WITHOUT IT THE TEST ABOVE PASSES ON A GATE THAT
        # ADMITS EVERYBODY. wilson is assigned to 588 Thomas and is a real
        # competent person on it, so project assignment and project access
        # both pass and this refusal is the only thing standing between him
        # and a statutory record attributed to a role he does not hold.
        exc = _gate_refuses(WILSON)
        self.assertIsNotNone(exc, "a non-registered caller may file the "
                                  "superintendent's log")
        self.assertEqual(exc.status_code, 403)
        self.assertEqual(exc.detail["code"], "NOT_THE_REGISTERED_SUPERINTENDENT")
        # THE NAME IS IN THE MESSAGE, which is the gate's own stated rule: a
        # refusal that does not say who MAY file leaves the CP with nothing to
        # do about it, on a log with a before-he-leaves-the-site deadline.
        self.assertIn("Michael Cespedes", exc.detail["message"])

    def test_the_refusal_is_not_a_rank_question(self):
        self.assertIsNotNone(
            _gate_refuses(MEILICH),
            "an admin of the company may sign the superintendent's log",
        )

    def test_the_gate_reads_cs_registrations_for_this_project(self):
        # THE COLLECTION IS STILL THE GATE, per the ruling. Asserted on the
        # QUERY the gate actually issued, so a gate rewired to read the
        # project document or the user's role would fail here even if its
        # verdicts happened to match.
        regs = _install(REGISTRATION)
        asyncio.run(server._refuse_if_not_the_superintendent(
            CS_LOG, PROJECT, DATE, MICHAEL))
        self.assertEqual(len(regs.queries), 1, "the gate made no read, or two")
        self.assertEqual(regs.queries[0].get("project_id"), str(PROJECT))

    def test_it_governs_only_the_one_log_type(self):
        # READ-ONLY, ONE QUERY, AND ONLY FOR THE ONE TYPE -- `_cs_filing_check`
        # returns before querying for anything else, so no other logbook
        # gained a gate when this one did.
        regs = _install(REGISTRATION)
        asyncio.run(server._refuse_if_not_the_superintendent(
            "daily_jobsite", PROJECT, DATE, WILSON))
        self.assertEqual(regs.queries, [],
                         "the CS gate reads the registration for other log types")


# ── SECTION 2. THE SCREEN IS GONE AND THE SERVER SIDE IS NOT ────────────────

class TheServerSideSurvivedTheRemoval(Base):
    """The ruling's "do not touch" list, asserted rather than assumed."""

    def test_the_shared_writer_survives(self):
        # `_register_cs_on_project` is called by BOTH routes and the ruling
        # keeps it whichever way the POST is decided.
        fn = getattr(server, "_register_cs_on_project", None)
        self.assertTrue(callable(fn), "_register_cs_on_project is gone")
        params = inspect.signature(fn).parameters
        for name in ("project", "project_id", "full_name", "license_number",
                     "admin", "user_id"):
            self.assertIn(name, params, f"{name} left _register_cs_on_project")

    def test_user_management_can_still_write_a_registration(self):
        self.assertTrue(callable(getattr(server, "set_user_cs_registrations",
                                         None)),
                        "the surviving registration writer is gone")

    def test_the_attribution_and_the_gate_helpers_survive(self):
        for name in ("cs_attribution_for", "_cs_filing_check",
                     "_logbook_filing_rights", "superintendent_projects_for",
                     "_refuse_if_not_the_superintendent"):
            self.assertTrue(callable(getattr(server, name, None)),
                            f"{name} is gone")

    def test_the_activation_gate_still_requires_a_registration(self):
        src = code_of("server.py")
        self.assertIn("ACTIVATION_REQUIRES_CS_REGISTRATION", src,
                      "the activation gate's refusal code is gone")

    def test_user_management_always_writes_the_account_link(self):
        # THE CAPABILITY THE DELETION REMOVES, STATED AS A TEST.
        # `set_user_cs_registrations` passes `user_id=str(user_id)`
        # unconditionally, so it cannot produce the unlinked row SECTION 3
        # measures. This is the whole of what the deleted screen could do that
        # the surviving writer cannot, and it is pinned so that a later change
        # making the link optional there is a decision somebody took.
        #
        # COMMENT-STRIPPED SOURCE. `code_of` removes docstrings and `#` lines;
        # this function's own docstring discusses `user_id` at length and a raw
        # scan would match the prose rather than the call.
        body = inspect.getsource(server.set_user_cs_registrations)
        from tests.source_text import strip_python
        code = strip_python(body)
        self.assertIn("user_id=str(user_id)", code,
                      "User Management no longer links the registration to "
                      "the account it was made from")
        self.assertNotIn("user_id=None", code)


# ── SECTION 3. WHAT AN UNLINKED ROW ACTUALLY DOES ───────────────────────────

class AnUnlinkedRegistrationLocksRatherThanServesNothing(Base):
    """The ruling's premise, corrected and pinned.

    The ruling said recording an account-less registration "serves nothing".
    It does something worse: it refuses EVERY caller, including the man whose
    name and licence are on the row, while still satisfying the activation
    gate. These assertions are why deleting the only screen that could create
    one is a removal of a footgun.
    """

    def test_it_refuses_the_person_it_names(self):
        exc = _gate_refuses(MICHAEL, reg=UNLINKED)
        self.assertIsNotNone(
            exc,
            "an unlinked registration admits the man it names -- if this "
            "fails, the licence fallback has been wired to the field the user "
            "document actually uses, and SECTION 4 explains what that changes",
        )
        self.assertEqual(exc.detail["code"], "NOT_THE_REGISTERED_SUPERINTENDENT")

    def test_it_refuses_everybody_else_too(self):
        for who in (WILSON, MEILICH):
            with self.subTest(name=who["name"]):
                self.assertIsNotNone(_gate_refuses(who, reg=UNLINKED))

    def test_so_the_log_is_fileable_by_nobody(self):
        # THE SAME FACT STATED AS THE PROPERTY IT IS, because the three
        # assertions above are each about one person and the finding is about
        # the project. A log that is required, counted by the deficiency
        # detector, and refusable to every account is the state this measures.
        everyone = (MICHAEL, MICHAEL_AS_CP, WILSON, MEILICH)
        admitted = [w["name"] for w in everyone
                    if _gate_refuses(w, reg=UNLINKED) is None]
        self.assertEqual(admitted, [],
                         f"somebody can file after all: {admitted}")

    def test_and_an_absent_registration_refuses_nobody(self):
        # THE CONTRAST THAT MAKES THE ABOVE A FINDING RATHER THAN A SETTING.
        # `cs_filing_refused` refuses only NOT_REGISTERED_CS, so NO row at all
        # lets everyone file -- deliberately, because blocking a log that must
        # be filed before a man leaves the site over a field an admin never
        # filled in is the worse failure. An unlinked row is therefore STRICTER
        # than no row, which is the opposite of "serves nothing".
        for who in (MICHAEL, WILSON, MEILICH):
            with self.subTest(name=who["name"]):
                self.assertIsNone(_gate_refuses(who, reg=None))


# ── SECTION 4. THE LICENCE FALLBACK, AND THE FIELD IT READS ─────────────────

class TheLicenceFallbackReadsAFieldNoAccountCarries(Base):
    """Both halves of the correction in the module docstring above.

    THIS IS A CHARACTERISATION, NOT AN ENDORSEMENT. The key mismatch is not
    fixed here -- the ruling's "do not touch" list covers the filing gate and
    `cs_attribution_for`, and widening who may file a statutory log is not a
    side effect of deleting a screen. It is pinned so that the behaviour is on
    the record and a later repair has to pass through this file.
    """

    def test_the_rule_does_permit_an_unlinked_filing_by_licence(self):
        # THE BRANCH EXISTS AND NEVER CONSULTS user_id. Fed the licence under
        # the name the branch looks for, an unlinked row admits the caller.
        result = attribute_signer(
            {**MICHAEL, "cs_license_number": "32299"}, UNLINKED, DATE)
        self.assertEqual(result["state"], MATCHED_LICENCE)
        self.assertFalse(cs_filing_refused(result))

    def test_but_a_user_document_carries_its_licence_under_another_name(self):
        # `dob_superintendent_number` is the field the user document actually
        # uses -- SUPERINTENDENT_LICENCE_FIELDS names it, ALLOWED_USER_FIELDS
        # admits it, and `superintendent_licence_state` reads it. Neither name
        # the fallback looks for appears in either place, so the branch above
        # is unreachable from the gate.
        self.assertIn("dob_superintendent_number",
                      server.SUPERINTENDENT_LICENCE_FIELDS)
        result = attribute_signer(MICHAEL, UNLINKED, DATE)
        self.assertEqual(result["state"], NOT_REGISTERED_CS)

    def test_no_code_path_writes_either_name_onto_a_user_document(self):
        # THE MEASUREMENT BEHIND THE CLAIM, so it cannot go stale silently: if
        # a writer appears, this fails and the gate's reach has changed.
        src = code_of("server.py")
        for banned in ('"cs_license_number":', "cs_license_number=",
                       'update_data["license_number"]'):
            self.assertNotIn(banned, src,
                             f"something now writes {banned} -- the licence "
                             "fallback may have become reachable")

    def test_the_account_link_is_what_admits_him_today(self):
        result = attribute_signer(MICHAEL, REGISTRATION, DATE)
        self.assertEqual(result["state"], MATCHED_ACCOUNT)
        self.assertFalse(cs_filing_refused(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
