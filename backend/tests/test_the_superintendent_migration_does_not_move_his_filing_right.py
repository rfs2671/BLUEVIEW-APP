"""Michael's role changes and his right to file the superintendent's log does not.

── THE MIGRATION, AND THE ONE QUESTION ABOUT IT ────────────────────────────

backend/scripts/migrate_cp_to_superintendent.py sets

    users[6a68b16ebe9c27dedf5cf47f].role : "cp" -> "superintendent"

Michael Cespedes, michaelcespedes99@gmail.com, is the ONLY row in
`cs_registrations` on the platform, on 588 Thomas (6a5f63bc147407d3261df2c7).
He files that log today. The operator's question about the migration is exactly
one sentence long: AFTER IT RUNS, CAN HE STILL SEE AND FILE THAT LOG?

── THE ARGUMENT, AND WHY AN ARGUMENT IS NOT ENOUGH ─────────────────────────

lib/logbook/superintendent_log.py says the access gate keys on the CS
REGISTRATION and never on `role`, and gives the reason: a `role ==
"superintendent"` gate would lock out precisely the dual-capacity user -- the
licensed CS who also acts as the competent person -- and on this product's
first customer that is the same man.

That reasoning is written down and it is load-bearing, and a migration is
exactly the kind of change that gets shipped on the strength of a paragraph. So
this drives the real predicate with the real registration under BOTH roles and
asserts THE IDENTITY: not "he may file as a superintendent" and separately "he
may file as a cp", which two different bugs could each satisfy, but that the
answer does not depend on the role at all.

── WHAT WOULD MAKE THIS FAIL ───────────────────────────────────────────────

Somebody adding `role == "superintendent"` to the filing gate -- the change
that looks like tidying up once the role exists, and that would have locked
Michael out of his own statutory log on the day it deployed.
"""

import inspect
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://example.test")

import server  # noqa: E402
from lib.logbook.cs_attribution import (  # noqa: E402
    attribute_signer, cs_filing_refused, is_registered_cs,
    MATCHED_ACCOUNT, NOT_REGISTERED_CS,
)

MICHAEL = "6a68b16ebe9c27dedf5cf47f"
PROJECT = "6a5f63bc147407d3261df2c7"

#: His registration as it stands in production: bound by ACCOUNT ID, which is
#: the strongest of the two matches and the one the role change cannot touch.
REGISTRATION = {
    "project_id": PROJECT,
    "user_id": MICHAEL,
    "full_name": "Michael Cespedes",
    "license_number": "CS-XXXXX",
    "is_active": True,
    "created_at": "2026-01-01",
}


def _michael(role):
    return {
        "id": MICHAEL,
        "name": "Michael Cespedes",
        "email": "michaelcespedes99@gmail.com",
        "role": role,
        "company_id": "company-a",
        "assigned_projects": [PROJECT],
    }


class TheAnswerDoesNotDependOnHisRole(unittest.TestCase):
    LOG_DATE = "2026-09-16"

    def test_the_attribution_is_identical_under_both_roles(self):
        before = attribute_signer(_michael("cp"), REGISTRATION, self.LOG_DATE)
        after = attribute_signer(
            _michael(server.ROLE_SUPERINTENDENT), REGISTRATION, self.LOG_DATE)
        self.assertEqual(before, after)

    def test_he_is_matched_by_ACCOUNT_before_and_after(self):
        """Named rather than left to the equality above: if both sides
        regressed to NOT_REGISTERED_CS they would still be equal."""
        for role in ("cp", server.ROLE_SUPERINTENDENT):
            self.assertEqual(
                attribute_signer(_michael(role), REGISTRATION,
                                 self.LOG_DATE)["state"],
                MATCHED_ACCOUNT,
                role,
            )

    def test_he_is_not_refused_the_filing_under_either_role(self):
        for role in ("cp", server.ROLE_SUPERINTENDENT):
            self.assertFalse(
                cs_filing_refused(
                    attribute_signer(_michael(role), REGISTRATION,
                                     self.LOG_DATE)),
                role,
            )

    def test_the_log_stays_VISIBLE_to_him_under_both_roles(self):
        """The list is filtered per viewer from the same `may_file` the gate
        computes (`_visible_required_logbooks`), so a role that could file and
        could not SEE the tile is a state this pins out of existence."""
        filing = [{"log_type": "site_superintendent_log", "may_file": True}]
        required = ["daily_jobsite_log", "site_superintendent_log"]
        self.assertIn(
            "site_superintendent_log",
            server._visible_required_logbooks(required, filing),
        )

    def test_somebody_ELSE_is_still_refused_after_the_migration(self):
        """The instrument has to be able to read "no". A second CP on 588
        Thomas is refused before and after; if this passed too, the test above
        would be measuring nothing."""
        other = {"id": "some-other-cp", "name": "Not Michael", "role": "cp"}
        result = attribute_signer(other, REGISTRATION, self.LOG_DATE)
        self.assertEqual(result["state"], NOT_REGISTERED_CS)
        self.assertTrue(cs_filing_refused(result))

    def test_the_predicate_never_reads_role_at_all(self):
        """The structural half. The two tests above would both keep passing if
        a role branch were added that happened to admit `superintendent` -- and
        that branch is the one that locks out the next dual-capacity CP."""
        src = inspect.getsource(attribute_signer)
        # ANCHORED LITERALS. A bare "role" would be satisfied or broken by
        # `signer_role`, `registered_role` or the word in a sentence; a bare
        # "superintendent" matches this module's own name in a comment. Each
        # needle below is a CONSTRUCT -- a dict key read, or the role string as
        # a literal -- which is what is actually being banned.
        self.assertNotIn('"role"', src)
        self.assertNotIn("'role'", src)
        self.assertNotIn('"superintendent"', src)
        self.assertNotIn("'superintendent'", src)

    def test_the_menu_predicate_agrees_too(self):
        for role in ("cp", server.ROLE_SUPERINTENDENT):
            self.assertTrue(
                is_registered_cs(
                    attribute_signer(_michael(role), REGISTRATION,
                                     self.LOG_DATE)),
                role,
            )


class NothingELSEHeHoldsMovesEither(unittest.TestCase):
    """The migration writes ONE field. These are the properties of the account
    that would change underneath him if it wrote more, or if the role carried
    a restriction `cp` did not."""

    def test_both_roles_are_scoped_to_assigned_projects(self):
        self.assertIn("cp", server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS)
        self.assertIn(server.ROLE_SUPERINTENDENT,
                      server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS)

    def test_both_roles_hard_require_a_company(self):
        """So the migration's company_id precondition is not defensive
        nicety -- a superintendent with no company 403s everywhere."""
        self.assertIn("cp", server.ROLES_REQUIRING_COMPANY)
        self.assertIn(server.ROLE_SUPERINTENDENT,
                      server.ROLES_REQUIRING_COMPANY)

    def test_neither_role_is_read_only_on_logbooks(self):
        self.assertNotIn("cp", server.ROLES_WITH_READ_ONLY_LOGBOOKS)
        self.assertNotIn(server.ROLE_SUPERINTENDENT,
                         server.ROLES_WITH_READ_ONLY_LOGBOOKS)

    def test_neither_role_loses_its_signing_capacity(self):
        self.assertNotIn("cp", server.ROLES_WITHOUT_SIGNING_AUTHORITY)
        self.assertNotIn(server.ROLE_SUPERINTENDENT,
                         server.ROLES_WITHOUT_SIGNING_AUTHORITY)

    def test_his_licence_reads_UNKNOWN_and_not_OK_after_the_migration(self):
        """He arrives as a superintendent with no DOB number recorded, because
        nobody has typed one in. That must not print as a valid licence."""
        state = server.superintendent_licence_state(
            _michael(server.ROLE_SUPERINTENDENT))
        self.assertEqual(state["state"], server.LICENCE_UNKNOWN)

    def test_superintendent_is_an_assignable_role(self):
        """The migration promotes him by script; an admin must be able to do
        the same thing on the screen, or the script becomes the only way."""
        self.assertEqual(
            server.assert_assignable_role("superintendent"),
            server.ROLE_SUPERINTENDENT,
        )


class TheScriptItself(unittest.TestCase):
    """Read as source. It talks to a database, so nothing here runs it."""

    PATH = BACKEND / "scripts" / "migrate_cp_to_superintendent.py"

    def setUp(self):
        self.src = self.PATH.read_text(encoding="utf-8")

    def test_it_carries_the_production_guard(self):
        for name in ("add_guard_args", "check_guard", "script_audit",
                     "report_dry_run"):
            self.assertIn(name, self.src)

    def test_it_is_a_dry_run_by_default(self):
        """`check_guard` returns False without --i-know, and the branch that
        follows must REPORT AND RETURN rather than fall through to the write."""
        self.assertIn("if not check_guard(args):", self.src)
        self.assertIn("report_dry_run(", self.src)

    def test_it_writes_exactly_one_field_to_exactly_one_collection(self):
        """`role`, and nothing else.

        THE $set BLOCK IS READ, NOT THE WHOLE FILE. An earlier version of this
        searched the source for "assigned_projects" and failed on the AUDIT
        DETAILS, which record the assignment list precisely because the script
        does not change it. A test that cannot tell a write from a record of a
        write is measuring the wrong text.
        """
        set_block = self.src[self.src.index('{"$set": {"role":'):]
        set_block = set_block[:set_block.index("}")]
        self.assertIn("server.ROLE_SUPERINTENDENT", set_block)
        self.assertIn("updated_at", set_block)
        for never in ("assigned_projects", "company_id", "license",
                      "dob_", "cs_"):
            self.assertNotIn(never, set_block)

    def test_it_writes_to_db_users_and_to_nothing_else(self):
        """`cs_registrations` is the FILING GATE. A script that wrote one
        would be inventing the fact the gate exists to record."""
        writers = [ln for ln in self.src.splitlines()
                   if "update_one(" in ln or "insert_one(" in ln
                   or "delete_one(" in ln]
        self.assertEqual(len(writers), 1, writers)
        self.assertIn("db.users.update_one(", writers[0])

    def test_it_refuses_an_account_with_no_company(self):
        self.assertIn("ROLES_REQUIRING_COMPANY", self.src)

    def test_the_update_filter_pins_the_role_it_read(self):
        """Idempotence. A rerun, or a second session, must not write a second
        audit row claiming to have made a change that had already been made."""
        self.assertIn('"role": role}', self.src)


if __name__ == "__main__":
    unittest.main()
