"""BC 3301.13.13 IS THE SUPERINTENDENT'S OWN RECORD, AND ONLY HE MAY FILE IT.

Until this, the write path's only gates were project assignment and project
access -- neither of which knows what a log type is. So ANY competent person
assigned to the project could open, fill and sign the construction
superintendent's log, producing a filed statutory document attributed to a role
the signer does not hold.

MEASURED ON 588 THOMAS. Two accounts are assigned to project
6a5f63bc147407d3261df2c7:

    Michael Cespedes   role=cp   registered CS (licence 32299, user_id linked)
    wilson peleaz      role=cp   no registration -- a temporary competent person

Both passed every gate. The exposure was live and unexercised: the one filed
superintendent log (2026-09-04) was created by Michael, who IS the registered
CS. A mechanism, not an incident.

── IT IS NOT A ROLE CHECK, AND THE DATA IS WHY ─────────────────────────────

Production holds admin 4, owner 3, cp 3 -- and ZERO accounts with role
"superintendent". The registered CS on the only live project holds `cp`. A gate
reading `role` would refuse the one man who must file, which is the failure the
module's own docstring warned about before this was built.

The question is "is this the person the project registered", and
`cs_registrations` answers it.

── WHY NOT `is_registered_cs`, WHICH ALREADY EXISTED ───────────────────────

Because that function forbids it in writing:

    THIS IS SAFE ONLY BECAUSE IT GATES A SHORTCUT ... If this predicate is ever
    used to REFUSE a filing, that reasoning collapses and the module's first
    rule -- IT NEVER BLOCKS -- is broken.

It answers a MENU question, where "nobody is registered" is fairly read as "do
not offer this shortcut" -- so it returns False for NO_REGISTRATION. Reusing it
here would have refused on absence, blocking a log that must be filed before a
man leaves the site over a field an admin never filled in. `cs_filing_refused`
is a second predicate with the opposite answer on exactly that state.

── THE TWO HALVES, AND NEITHER WORKS ALONE ─────────────────────────────────

The refusal deliberately leaves an ungated state -- flag on, nobody registered.
The activation gate closes it from the other side: turning the CS log ON now
requires a registration, so the flag and the designation are one act. 37
projects, one registration, one flag: they coincide today only by accident, and
this is what stops the second one diverging.
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
from lib.logbook.cs_attribution import (  # noqa: E402
    cs_filing_refused, is_registered_cs,
    MATCHED_ACCOUNT, MATCHED_LICENCE, NOT_REGISTERED_CS, NO_REGISTRATION,
    REGISTERED_LATER, UNDETERMINED,
)

PROJECT = "6a5f63bc147407d3261df2c7"
CS_LOG = "site_superintendent_log"

#: Production shapes, verbatim.
MICHAEL = {"id": "6a68b16ebe9c27dedf5cf47f", "name": "Michael Cespedes",
           "role": "cp"}
WILSON = {"id": "6a5e15aac7ac7a6451aa2d34", "name": "wilson peleaz",
          "role": "cp"}
REGISTRATION = {
    "project_id": PROJECT, "full_name": "Michael Cespedes",
    "license_number": "32299", "user_id": "6a68b16ebe9c27dedf5cf47f",
    "is_active": True, "is_deleted": False,
    "created_at": "2026-09-01T12:13:32",
}


class _Regs:
    """db.cs_registrations, with whatever row the test wants."""

    def __init__(self, row):
        self.row = row
        self.queries = []

    async def find_one(self, query, projection=None):
        self.queries.append(query)
        return self.row


def _install(row):
    class _DB:
        cs_registrations = _Regs(row)
    server.db = _DB()
    return _DB.cs_registrations


def _refuse(user, row=REGISTRATION, log_type=CS_LOG, date="2026-09-04"):
    _install(row)
    return asyncio.run(server._refuse_if_not_the_superintendent(
        log_type, PROJECT, date, user))


class Base(unittest.TestCase):
    def setUp(self):
        self._db = server.db

    def tearDown(self):
        server.db = self._db


class TheControlRun(Base):
    """WILSON REFUSED, MICHAEL ACCEPTED — the two named accounts, against the
    production registration."""

    def test_the_registered_superintendent_is_accepted(self):
        self.assertIsNone(_refuse(MICHAEL))

    def test_the_temporary_competent_person_is_REFUSED(self):
        with self.assertRaises(HTTPException) as cm:
            _refuse(WILSON)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(cm.exception.detail["code"],
                         "NOT_THE_REGISTERED_SUPERINTENDENT")

    def test_the_refusal_names_who_MAY_file(self):
        """A refusal that does not say who may file leaves the CP with nothing
        to do about it, on a log with a deadline."""
        with self.assertRaises(HTTPException) as cm:
            _refuse(WILSON)
        self.assertIn("Michael Cespedes", cm.exception.detail["message"])
        self.assertEqual(cm.exception.detail["registered_name"],
                         "Michael Cespedes")

    def test_the_message_cites_the_section(self):
        with self.assertRaises(HTTPException) as cm:
            _refuse(WILSON)
        self.assertIn("3301.13.13", cm.exception.detail["message"])


class NoRegistrationDoesNotGate(Base):
    """THE FAILURE THAT WAS RULED OUT. Refusing on absence blocks a log that
    must be filed before he leaves the site, over a field an admin never
    filled in."""

    def test_a_project_with_no_registration_refuses_NOBODY(self):
        for user in (MICHAEL, WILSON):
            with self.subTest(user["name"]):
                self.assertIsNone(_refuse(user, row=None))

    def test_and_it_does_not_even_look_when_the_type_is_wrong(self):
        """One query, for the one log type it governs. A read per logbook write
        would be a cost on every type to gate one."""
        regs = _install(REGISTRATION)
        asyncio.run(server._refuse_if_not_the_superintendent(
            "daily_jobsite", PROJECT, "2026-09-04", WILSON))
        self.assertEqual(regs.queries, [])

    def test_a_deleted_registration_is_not_a_registration(self):
        regs = _install(REGISTRATION)
        asyncio.run(server._refuse_if_not_the_superintendent(
            CS_LOG, PROJECT, "2026-09-04", MICHAEL))
        self.assertEqual(regs.queries[0]["is_deleted"], {"$ne": True})


class EveryOtherLogTypeIsUntouched(Base):
    """`fall_protection` IS NOT A SUPERINTENDENT-CLASS LOG, and was nearly
    gated as one from its name alone. Its declaration carries NO
    `dob_reference` and a subtitle reading "industry standard, not
    DOB-required": OSHA 1926.502(d)(21) mandates the INSPECTION, not a written
    record, and the documented periodic inspection comes from ANSI Z359, a
    consensus standard rather than law. It is a competent-person equipment log
    and a CS gate would refuse exactly the people who should file it."""

    def test_fall_protection_is_never_refused(self):
        self.assertIsNone(_refuse(WILSON, log_type="fall_protection"))

    def test_nor_is_any_of_the_others(self):
        for lt in ("daily_jobsite", "toolbox_talk", "preshift_signin",
                   "osha_log", "subcontractor_orientation", "hot_work",
                   "crane_operations", "excavation_monitoring",
                   "scaffold_maintenance", "concrete_operations",
                   "ssc_daily_safety_log"):
            with self.subTest(lt):
                self.assertIsNone(_refuse(WILSON, log_type=lt))

    def test_fall_protection_still_carries_no_dob_reference(self):
        """The premise of the exemption above, asserted so it cannot rot into
        a stale comment."""
        entry = next(e for e in server.LOGBOOK_TYPE_REGISTRY
                     if e["key"] == "fall_protection")
        self.assertNotIn("dob_reference", entry)
        cs = next(e for e in server.LOGBOOK_TYPE_REGISTRY if e["key"] == CS_LOG)
        self.assertEqual(cs.get("dob_reference"), "§3301.13.13")


class TheRefusalPredicateIsItsOwn(unittest.TestCase):
    """`is_registered_cs` forbids being used to refuse a filing, in writing."""

    def test_exactly_one_state_refuses(self):
        refused = [st for st in (MATCHED_ACCOUNT, MATCHED_LICENCE,
                                 NO_REGISTRATION, REGISTERED_LATER,
                                 UNDETERMINED, NOT_REGISTERED_CS)
                   if cs_filing_refused({"state": st})]
        self.assertEqual(refused, [NOT_REGISTERED_CS])

    def test_it_DISAGREES_with_is_registered_cs_on_absence(self):
        """The whole reason it is a second function. `is_registered_cs` says
        False for NO_REGISTRATION -- correct for a menu, catastrophic for a
        gate."""
        no_reg = {"state": NO_REGISTRATION}
        self.assertFalse(is_registered_cs(no_reg))
        self.assertFalse(cs_filing_refused(no_reg))

    def test_a_malformed_result_never_refuses(self):
        for junk in (None, "", {}, [], {"state": "invented"}):
            with self.subTest(repr(junk)):
                self.assertFalse(cs_filing_refused(junk))


class BothWritePathsCarryIt(unittest.TestCase):
    """Save Draft then Submit arrives as a PUT, so a gate on create alone would
    let the wrong man file by taking the ordinary two-step route."""

    def _fn(self, name):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index(f"async def {name}(")
        j = src.index("\n@api_router", i)
        return src[i:j]

    def test_create_logbook_calls_it(self):
        self.assertTrue(
            "_refuse_if_not_the_superintendent(" in self._fn("create_logbook"),
            "create_logbook does not gate the superintendent's log")

    def test_update_logbook_calls_it(self):
        self.assertTrue(
            "_refuse_if_not_the_superintendent(" in self._fn("update_logbook"),
            "update_logbook does not gate it — Save Draft then Submit is the "
            "path the CP actually walks")


class ActivationRequiresARegistration(unittest.TestCase):
    """The other half. The refusal leaves an ungated state on purpose; this
    stops that state being reachable going forward."""

    def _fn(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index('detail={"code": "ACTIVATION_STATE_REQUIRED"')
        j = src.index("_refresh_required_logbooks", i)
        return src[i:j]

    def test_turning_it_on_requires_one(self):
        body = self._fn()
        self.assertIn("ACTIVATION_REQUIRES_CS_REGISTRATION", body)
        self.assertIn("cs_registrations", body)

    def test_turning_it_OFF_never_requires_one(self):
        """A project whose registration was removed must still be able to
        switch the log off. A gate that could trap a project in the ON state
        would be worse than the one it replaces."""
        self.assertIn("if active and entry[\"conditional\"]", self._fn())

    def test_it_governs_only_the_CS_log(self):
        """The other five conditionals — scaffold, hot work, crane, excavation,
        fall protection — have no registration to require."""
        self.assertIn('== "superintendent_log_active"', self._fn())


if __name__ == "__main__":
    unittest.main(verbosity=2)
