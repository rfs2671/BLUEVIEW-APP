"""BC 3301.13.13 IS THE SUPERINTENDENT'S RECORD, AND THE CP DOES NOT SEE IT.

── WHAT WAS ON SCREEN ──────────────────────────────────────────────────────

The tile was RETURNED to everybody and labelled. On 588 Thomas that is three CP
accounts -- Michael Cespedes, wilson peleaz, shawn -- opening their own logbook
list every morning and reading another man's name on a padlocked document, plus
a row in the block beneath it saying "On -- it is on your logbook list" about a
log none of them may file.

The label was deliberate and the reasoning was written into the endpoint: a CP
who cannot see the log cannot learn that it EXISTS or who owns it, and a
required log he cannot open is worse than an ugly label. OPERATOR RULING
OVERRIDES IT: the superintendent's log is not the CP's document and its
existence is not his business. Hide it; do not lock it.

── THE INVARIANT, AND WHY IT IS ASSERTED AND NOT THE TWO SIDES ─────────────

    site_superintendent_log is in the caller's required_logbooks
        IF AND ONLY IF
    the filing row for it says he may file.

Both halves come from ONE read -- `_logbook_filing_rights`, which is the same
call `_refuse_if_not_the_superintendent` makes on the write path. Asserting the
visibility rule separately from the filing rule is how the two reads that
produced this defect in the first place would be recreated in the tests. So
every case below checks the identity, and the named cases underneath it only
pin which side of the identity each person lands on.

── THE THREE CASES THE RULING NAMES ────────────────────────────────────────

  a plain CP on a project WITH a registration        never sees it
  a CP who IS the registered CS                      sees it and files it
  a project with NO registration                     everyone sees it, as today

The third is not a leftover. `cs_filing_refused` refuses only NOT_REGISTERED_CS
-- the project HAS named somebody and this is not him -- because blocking a log
that must be filed before a man leaves the site, over a field an admin never
filled in, punishes the site for the office's omission. Visibility follows the
registration for exactly the same reason: on a project that has designated
nobody there is nobody to withhold it from.

── AND THE PROJECT'S OWN SET IS UNTOUCHED ──────────────────────────────────

`get_required_logbooks` still answers about the PROJECT and asks nobody who is
calling. The nightly deficiency detector, the stored `required_logbooks` field
and every compliance count read that, so a log hidden from a CP's screen is
still required, still counted, and still missing if nobody files it. Asserted
directly below, because a filter written one layer too deep would have silently
retired a statutory obligation instead of a tile.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

PROJECT = "6a5f63bc147407d3261df2c7"
CS_LOG = "site_superintendent_log"
COMPANY = "c1"

#: Production shapes. Same fixtures as test_the_tile_and_the_gate_read_one_fact
#: and test_only_the_superintendent_files_his_log, so the three files cannot
#: disagree about who these people are. `company_id` is added because these go
#: through the real endpoint, which runs project_access_ok first.
MICHAEL = {"id": "6a68b16ebe9c27dedf5cf47f", "name": "Michael Cespedes",
           "role": "cp", "company_id": COMPANY}
WILSON = {"id": "6a9e1635e755d35d29a41d17", "name": "wilson peleaz",
          "role": "cp", "company_id": COMPANY}
SHAWN = {"id": "6a3333333333333333333333", "name": "shawn",
         "role": "cp", "company_id": COMPANY}
ROY = {"id": "6a1111111111111111111111", "name": "Roy Fishman",
       "role": "owner", "company_id": COMPANY}
MEILICH = {"id": "6a2222222222222222222222", "name": "Meilich Friedman",
           "role": "admin", "company_id": COMPANY}

EVERYBODY = (MICHAEL, WILSON, SHAWN, ROY, MEILICH)

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
    "company_id": COMPANY,
}


class _One:
    def __init__(self, row):
        self.row = row

    async def find_one(self, query, projection=None, **kw):
        return self.row


class _EmptyColl:
    """logbooks / checkins for the cadence block, which reads both.

    IT ANSWERS NOTHING RATHER THAN BEING ABSENT. The endpoint gained a weekly
    cadence read after these fixtures were written; an absent attribute made
    every test in the file fail with an AttributeError that had nothing to do
    with what it was asserting."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    def find(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return list(self.rows)

    def __aiter__(self):
        async def _gen():
            for r in self.rows:
                yield r
        return _gen()


def _install(reg_row, project_row=None):
    class _DB:
        cs_registrations = _One(reg_row)
        projects = _One(project_row if project_row is not None
                        else dict(PROJECT_ROW))
        logbooks = _EmptyColl()
        checkins = _EmptyColl()
    server.db = _DB()


def _payload(user, reg=REGISTRATION, project_row=None):
    """THE REAL ENDPOINT, not a re-implementation of it.

    The ordering inside the handler is the thing most likely to break -- the
    rights must be computed against the PROJECT's full set, because
    `_logbook_filing_rights` returns [] for a type that is not in the list it is
    handed, and filtering first would make the second call answer "nobody is
    withheld" and put the tile straight back. A test over the two helpers alone
    would pass on that.
    """
    _install(reg, project_row)
    return asyncio.run(server.get_project_required_logbooks(PROJECT, user))


def _filing_row(payload):
    return next((r for r in (payload.get("filing") or [])
                 if r.get("log_type") == CS_LOG), None)


def _act_row(payload):
    return next((a for a in (payload.get("activations") or [])
                 if a.get("log_type") == CS_LOG), None)


class Base(unittest.TestCase):
    def setUp(self):
        self._db = server.db

    def tearDown(self):
        server.db = self._db


class TheInvariant(Base):
    """VISIBLE IF AND ONLY IF FILEABLE -- one read, one answer, no second rule.

    Every account on the census, against every registration shape, with the
    conclusion DERIVED from the filing row rather than restated beside it."""

    def test_visibility_equals_may_file_for_everyone(self):
        for reg_name, reg in (("registered", REGISTRATION), ("none", None)):
            for user in EVERYBODY:
                with self.subTest(reg=reg_name, user=user["name"]):
                    p = _payload(user, reg=reg)
                    row = _filing_row(p)
                    # No row at all means nothing is withheld -- the client
                    # defaults to "he may file" for exactly that reason.
                    may_file = row is None or row.get("may_file") is not False
                    visible = CS_LOG in p["required_logbooks"]
                    self.assertEqual(visible, may_file)

    def test_the_rights_are_computed_before_the_filter(self):
        """The filing row SURVIVES the removal, and it has to.

        It is the evidence of why the tile went, it is what the invariant above
        is read from, and it is what still answers `mayFile` if the CP reaches
        the editor by any other route."""
        p = _payload(WILSON)
        self.assertNotIn(CS_LOG, p["required_logbooks"])
        row = _filing_row(p)
        self.assertIsNotNone(row)
        self.assertFalse(row["may_file"])
        self.assertEqual(row["reason"], "NOT_THE_REGISTERED_SUPERINTENDENT")


class ThePlainCpNeverSeesIt(Base):
    """CASE A. wilson peleaz and shawn are competent persons on 588 Thomas who
    are not the registered CS."""

    def test_not_in_his_required_logbooks(self):
        for user in (WILSON, SHAWN):
            with self.subTest(user["name"]):
                self.assertNotIn(CS_LOG, _payload(user)["required_logbooks"])

    def test_and_not_in_the_block_underneath_either(self):
        """THE SECOND SURFACE, AND IT NAMED THE LOG IN PROSE.

        `site_superintendent_log` carries `conditional:
        superintendent_log_active`, so it is also an activation row -- rendered
        as "Construction Superintendent Log / On -- it is on your logbook
        list". Hiding the tile alone would leave the name on his screen over a
        sentence that had just been made false."""
        for user in (WILSON, SHAWN):
            with self.subTest(user["name"]):
                self.assertIsNone(_act_row(_payload(user)))

    def test_the_rest_of_his_list_is_unchanged(self):
        """A filter that took anything else with it would be a far worse
        defect than the one it fixes."""
        mine = _payload(WILSON)["required_logbooks"]
        his = _payload(MICHAEL)["required_logbooks"]
        self.assertEqual(mine, [t for t in his if t != CS_LOG])
        self.assertIn("daily_jobsite", mine)
        self.assertIn("preshift_signin", mine)


class TheRegisteredCsSeesItAndFilesIt(Base):
    """CASE B, AND IT IS THE 588 CASE: the registered CS holds a `cp` account.

    Production has ZERO accounts with role "superintendent" (admin 4, owner 3,
    cp 3). A visibility rule written on `role` would hide this log from the one
    man who must file it, which is why this follows the REGISTRATION."""

    def test_he_sees_it(self):
        self.assertIn(CS_LOG, _payload(MICHAEL)["required_logbooks"])

    def test_and_he_may_file_it(self):
        row = _filing_row(_payload(MICHAEL))
        self.assertTrue(row["may_file"])
        self.assertIsNone(row["reason"])

    def test_and_his_activation_row_is_still_there(self):
        self.assertIsNotNone(_act_row(_payload(MICHAEL)))


class NoRegistrationHIDESITFROMNOBODY(Base):
    """CASE C. The gate's deliberate gap, preserved on the list as well.

    `cs_filing_refused` fires only on NOT_REGISTERED_CS. An unregistered project
    refuses nobody, so it must hide from nobody -- otherwise a field an admin
    never filled in would make a statutory log unreachable for the whole site,
    which is the failure direction cs_attribution chose against in writing."""

    def test_everyone_still_sees_it(self):
        for user in EVERYBODY:
            with self.subTest(user["name"]):
                self.assertIn(CS_LOG,
                              _payload(user, reg=None)["required_logbooks"])

    def test_and_the_activation_row_survives_for_everyone(self):
        for user in EVERYBODY:
            with self.subTest(user["name"]):
                self.assertIsNotNone(_act_row(_payload(user, reg=None)))


class TheAdminKeepsTheSwitch(Base):
    """THE ONE THING THAT IS NOT SYMMETRIC, AND IT IS NOT AN EXEMPTION.

    An admin is refused the FILING -- it is not his record -- so the tile goes,
    like anyone else's. But `superintendent_log_active` is `activated_by:
    "admin"`, and there is exactly one call site in the app behind that test. A
    filter that took his row too would leave the flag unsettable from any
    screen, on any project, by anybody: the precise defect the client records
    having already been fixed once (app/logbooks/index.jsx:770).

    So the rule is "could neither file it nor switch it on", and only the second
    clause saves him."""

    def test_the_tile_is_gone_for_an_admin_and_an_owner(self):
        for user in (MEILICH, ROY):
            with self.subTest(user["name"]):
                self.assertNotIn(CS_LOG, _payload(user)["required_logbooks"])

    def test_but_the_toggle_is_not(self):
        for user in (MEILICH, ROY):
            with self.subTest(user["name"]):
                row = _act_row(_payload(user))
                self.assertIsNotNone(row)
                self.assertEqual(row["activated_by"], "admin")

    def test_and_a_cp_gated_toggle_would_NOT_survive_for_him(self):
        """The role test does not grant a blanket pass. A withheld log whose
        switch is the CP's own is hidden from an admin as well -- there is no
        such type today, and the rule must not acquire one by accident."""
        acts = [{"log_type": CS_LOG, "label": "x", "field": "f",
                 "active": True, "activated_by": "cp"}]
        filing = [{"log_type": CS_LOG, "may_file": False,
                   "registered_name": "Michael Cespedes", "reason": "x"}]
        self.assertEqual(server._visible_activations(acts, filing, MEILICH), [])


class ThePROJECTSSetIsUntouched(Base):
    """THE FILTER IS AT THE PER-CALLER READ AND NOWHERE ELSE.

    `get_required_logbooks` is what the nightly detector, the stored field and
    the investor report use. If the hiding had been done there, a required
    statutory log would have stopped being required -- 285 false deficiency
    flags were removed from this product by making a log conditional, and this
    is the same mechanism pointed the other way."""

    def test_the_project_still_requires_it(self):
        self.assertIn(CS_LOG, server.get_required_logbooks(
            "regular", dict(PROJECT_ROW)))

    def test_the_helper_asks_nobody_who_is_calling(self):
        """Signature proof: there is no caller argument to pass."""
        import inspect
        params = list(inspect.signature(
            server.get_required_logbooks).parameters)
        self.assertEqual(params, ["project_class", "project"])


class TheFilterIsGeneric(Base):
    """A SECOND RESTRICTED TYPE NEEDS NO CHANGE HERE.

    `_logbook_filing_rights` documents its list shape as existing for exactly
    that. The filter reads `may_file` off whatever rows it is given and knows
    no log type by name."""

    def test_any_withheld_type_is_removed(self):
        required = ["daily_jobsite", "some_future_log", "toolbox_talk"]
        filing = [{"log_type": "some_future_log", "may_file": False,
                   "registered_name": "N", "reason": "R"}]
        self.assertEqual(
            server._visible_required_logbooks(required, filing),
            ["daily_jobsite", "toolbox_talk"])

    def test_and_nothing_is_removed_without_a_refusal(self):
        required = ["daily_jobsite", CS_LOG]
        for filing in ([], None,
                       [{"log_type": CS_LOG, "may_file": True,
                         "registered_name": None, "reason": None}]):
            with self.subTest(filing=filing):
                self.assertEqual(
                    server._visible_required_logbooks(required, filing),
                    required)


if __name__ == "__main__":
    unittest.main(verbosity=2)
