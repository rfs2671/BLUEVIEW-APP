"""The Site Manager / PM: admin powers, scoped to assigned projects, and the
four things he must never be able to do.

── THE RULING, AND WHY EACH HALF NEEDS A DIFFERENT TEST ────────────────────

"Admin powers scoped to assigned projects; cannot create projects; Daily Logs
are view-only but he may ADD PHOTOS; no signing; no user management."

Those are five statements about one role and they are enforced in five
different places, because they are five different kinds of rule:

  SCOPE        project_access_ok, branch 1b. A RETURN, not a fall-through.
  USERS        get_user_admin, on the six /admin/users routes.
  PROJECTS     POST /projects keeps get_admin_user, which does not admit him.
  LOGBOOKS     refuse_if_logbooks_are_read_only, at the four write gates.
  SIGNING      record_signature_event, before anything is written.

── THE ONE THAT WOULD HAVE BEEN SILENT ─────────────────────────────────────

`project_access_ok` branch 2 admits ANYONE IN THE PROJECT'S COMPANY. A PM who
reached it would hold every power he has on every job the company runs, which
is the ruling with its only qualifying clause deleted -- and it would have read
as working, because he would see his own projects too. The test is the
INVARIANT: for a project of his own company that he is not assigned to, the
answer is False. Asserting only the assigned case would pass on a role with no
scoping at all.

── AND THE ONE THE RULING GRANTS ───────────────────────────────────────────

He MAY append a photograph. `append_activity_photo` is guarded by
`_authorize_logbook_view` on a ruling of its own, and it already stamps
`added_by`, `added_by_name` and `added_at` on the row -- which is exactly the
record the Site Manager ruling asks for. A refusal added there would take away
the one write he has, so its ABSENCE is asserted.
"""

import ast
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://example.test")

import server  # noqa: E402

PM = server.ROLE_PM
COMPANY = "company-a"
MINE = "project-assigned"
THEIRS = "project-same-company-not-assigned"


def _src(fn) -> str:
    return ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))


def _pm(assigned=(MINE,)):
    return {"role": PM, "company_id": COMPANY,
            "assigned_projects": list(assigned)}


class HeIsHisAssignmentsAndNothingMore(unittest.TestCase):
    def test_an_assigned_project_is_his(self):
        self.assertTrue(server.project_access_ok(
            {"company_id": COMPANY}, MINE, _pm()))

    def test_a_project_of_his_own_company_is_NOT_his(self):
        """THE WHOLE RULE. Branch 2 would say True here for any company member.
        Without this assertion a PM with no scoping at all passes the suite."""
        self.assertFalse(server.project_access_ok(
            {"company_id": COMPANY}, THEIRS, _pm()))

    def test_another_companys_project_is_not_his_either(self):
        self.assertFalse(server.project_access_ok(
            {"company_id": "company-b"}, THEIRS, _pm()))

    def test_a_pm_with_no_assignments_reaches_nothing(self):
        self.assertFalse(server.project_access_ok(
            {"company_id": COMPANY}, MINE, _pm(assigned=())))

    def test_the_branch_returns_rather_than_falling_through(self):
        """If it fell through, the company branch below would answer for him
        and the refusal above would be unreachable. Same assertion as the test
        above it, stated as the property rather than the case -- an assigned
        project and an unassigned one of the same company must DISAGREE."""
        self.assertNotEqual(
            server.project_access_ok({"company_id": COMPANY}, MINE, _pm()),
            server.project_access_ok({"company_id": COMPANY}, THEIRS, _pm()),
        )

    def test_the_role_comparison_survives_case_and_whitespace(self):
        """`role` arrives off a Mongo document."""
        user = {"role": " PM ", "company_id": COMPANY,
                "assigned_projects": [MINE]}
        self.assertFalse(server.project_access_ok(
            {"company_id": COMPANY}, THEIRS, user))

    def test_nobody_else_is_moved_by_this_branch(self):
        """cp and superintendent still reach the company branch. Production
        holds zero pm accounts, so this change must be a no-op on every account
        that exists (admin 4, owner 3, cp 3, superintendent 0)."""
        for role in ("cp", server.ROLE_SUPERINTENDENT, "admin", "owner"):
            user = {"role": role, "company_id": COMPANY,
                    "assigned_projects": []}
            self.assertTrue(
                server.project_access_ok({"company_id": COMPANY}, THEIRS, user),
                f"{role} lost company-scoped access",
            )


class TheThreeAdminGates(unittest.TestCase):
    def test_a_pm_holds_project_admin_and_neither_of_the_others(self):
        self.assertIn(PM, server.PROJECT_ADMIN_ROLES)
        self.assertNotIn(PM, server.USER_MANAGEMENT_ROLES)
        self.assertNotIn(PM, server.COMPANY_ADMIN_ROLES)

    def test_the_company_gate_membership_did_not_move(self):
        """get_admin_user guards roughly a hundred routes. Naming its list was
        the edit; widening it was not."""
        self.assertEqual(server.COMPANY_ADMIN_ROLES, ("admin", "owner"))

    def test_user_management_is_a_SEPARATE_constant(self):
        """Same members as COMPANY_ADMIN_ROLES today and a different question.
        One list governing both is how account administration acquires a role
        somebody added for an unrelated reason.

        ASSERTED ON THE SOURCE, NOT WITH `assertIsNot`. CPython folds two
        identical string tuples in one module to ONE object, so an identity
        check here passes on `USER_MANAGEMENT_ROLES = COMPANY_ADMIN_ROLES` and
        on two separate declarations alike -- it cannot fail, which makes it no
        instrument at all. Two declarations is the fact being pinned.
        """
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn('USER_MANAGEMENT_ROLES = ("admin", "owner")', src)
        self.assertIn('COMPANY_ADMIN_ROLES = ("admin", "owner")', src)
        self.assertNotIn("USER_MANAGEMENT_ROLES = COMPANY_ADMIN_ROLES", src)

    def test_project_admin_is_wider_by_exactly_one_role(self):
        self.assertEqual(
            set(server.PROJECT_ADMIN_ROLES) - set(server.COMPANY_ADMIN_ROLES),
            {PM},
        )


class HeCannotManageUsers(unittest.TestCase):
    """The refusal that keeps every other refusal standing: a PM who could edit
    users could set his own role to admin, or write another company's project
    into his own `assigned_projects`, which require_project_access honours."""

    ROUTES = (
        "get_admin_users", "create_admin_user", "get_admin_user_by_id",
        "update_admin_user", "delete_admin_user", "assign_projects_to_user",
    )

    def test_every_account_route_carries_the_narrow_gate(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        for name in self.ROUTES:
            i = src.index(f"async def {name}(")
            # The signature, however many lines it spans.
            sig = src[i:src.index("):", i)]
            self.assertIn("get_user_admin", sig, f"{name} is not on get_user_admin")
            self.assertNotIn("Depends(get_admin_user)", sig, name)

    def test_the_gate_itself_refuses_a_pm(self):
        self.assertNotIn(PM, server.USER_MANAGEMENT_ROLES)


class HeCannotCreateAProject(unittest.TestCase):
    def test_project_creation_keeps_the_company_gate(self):
        self.assertIn("get_admin_user", _src(server.create_project))
        self.assertNotIn("get_project_admin_user", _src(server.create_project))

    def test_project_deletion_keeps_it_too(self):
        """Not named by the ruling, and left alone deliberately: an
        irreversible act is not a power to hand a new role by inference."""
        self.assertIn("get_admin_user", _src(server.delete_project))


class DailyLogsAreViewOnly(unittest.TestCase):
    WRITE_GATES = (
        "_authorize_logbook_write",   # update / finalize / amend / delete
        "create_logbook",
        "create_daily_log",
        "update_daily_log",
    )

    def test_the_role_is_named_by_a_constant(self):
        self.assertEqual(server.ROLES_WITH_READ_ONLY_LOGBOOKS, (PM,))

    def test_every_write_gate_refuses_him(self):
        for name in self.WRITE_GATES:
            self.assertIn(
                "refuse_if_logbooks_are_read_only",
                _src(getattr(server, name)),
                f"{name} does not refuse a read-only role",
            )

    def test_the_refusal_fires(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            server.refuse_if_logbooks_are_read_only({"role": PM})
        self.assertEqual(ctx.exception.status_code, 403)

    def test_it_does_not_fire_for_anybody_else(self):
        for role in ("cp", server.ROLE_SUPERINTENDENT, "admin", "owner",
                     "site_device"):
            server.refuse_if_logbooks_are_read_only({"role": role})

    def test_appending_a_photograph_is_NOT_refused(self):
        """The one write the ruling grants him. Its absence here is the
        assertion -- adding the guard to this route would silently remove the
        only thing a Site Manager can contribute to a log."""
        self.assertNotIn(
            "refuse_if_logbooks_are_read_only",
            _src(server.append_activity_photo),
        )

    def test_the_photo_row_records_who_added_it_and_when(self):
        """The ruling's own words. Already true; pinned so a refactor of the
        photo row cannot drop the attribution the ruling asked for."""
        src = _src(server.append_activity_photo)
        for field in ("'added_by'", "'added_at'", "'added_by_name'"):
            self.assertIn(field, src)


class HeSignsNothing(unittest.TestCase):
    def test_the_role_is_named_by_a_constant(self):
        self.assertEqual(server.ROLES_WITHOUT_SIGNING_AUTHORITY, (PM,))

    def test_the_ledger_endpoint_refuses_him(self):
        self.assertIn("ROLES_WITHOUT_SIGNING_AUTHORITY",
                      _src(server.record_signature_event))

    def test_the_refusal_is_ahead_of_every_write(self):
        """A 403 after the document read is still a refusal; a 403 after the
        ledger insert is a signed record by a person with no capacity."""
        src = _src(server.record_signature_event)
        self.assertLess(src.index("ROLES_WITHOUT_SIGNING_AUTHORITY"),
                        src.index("create_signature_event"))


if __name__ == "__main__":
    unittest.main()
