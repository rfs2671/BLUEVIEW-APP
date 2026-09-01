"""A superintendent is scoped to his assigned projects, exactly as a CP is.

THE HOLE. create_logbook gated the assigned-projects check on ONE role:

    if current_user.get('role') == 'cp':
        assigned = current_user.get('assigned_projects', []) or []
        if data.project_id not in assigned:
            raise HTTPException(403, 'Not assigned to this project')

A `superintendent`-role user skipped that branch entirely and fell through to
project_access_ok, whose branch 2 admits anyone in the project's COMPANY. So
the role intended to be narrower than a CP's was broader: it could file on any
project in the company, while a CP could only file on the ones assigned to him.

NOBODY HOLDS THAT ROLE TODAY, which is why nothing is exposed — and is also
why it is worth closing now. A gap that opens the moment a role is first used
reads as deliberate when it is found later.

WHY A SEPARATE CONSTANT, and not ROLES_REQUIRING_COMPANY. That tuple has the
same two members today, but its job is "these roles must carry a company_id
when created" (server.py:7466) — a different question. Reusing it here would
mean a future role added for the COMPANY reason silently acquires a PROJECT
restriction, or the reverse. Two rules that happen to agree are still two
rules, and this codebase spent the week on fields whose meaning drifted because
one reader assumed another's intent.
"""

import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402


class TheGateCoversBothScopedRoles(unittest.TestCase):
    def test_the_constant_names_what_it_decides(self):
        self.assertEqual(set(server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS),
                         {"cp", server.ROLE_SUPERINTENDENT})

    def test_it_is_a_DISTINCT_constant_from_the_company_rule(self):
        """Same members today, different question. If a role is ever added to
        one for its own reason, it must not silently join the other."""
        self.assertIsNot(server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS,
                         server.ROLES_REQUIRING_COMPANY)

    def test_create_logbook_gates_on_the_set_not_on_cp_alone(self):
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.create_logbook))))
        self.assertIn("ROLES_SCOPED_TO_ASSIGNED_PROJECTS", code)
        self.assertNotIn("current_user.get('role') == 'cp'", code)

    def test_the_refusal_still_names_the_same_condition(self):
        """The message a client already handles must not change underneath it."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn("Not assigned to this project", src)


class TheRoleComparisonIsRobust(unittest.TestCase):
    """`role` arrives off a Mongo document. Case and whitespace are not
    guarantees, and a gate that a stray space defeats is not a gate."""

    def test_it_normalises_before_comparing(self):
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.create_logbook))))
        self.assertIn(".strip().lower()", code)


class WhatMustNotChange(unittest.TestCase):
    """PASSES EITHER WAY — the shape of the existing decision."""

    def test_admin_and_owner_are_not_project_scoped(self):
        """They are scoped by COMPANY, through project_access_ok. Adding them
        here would break every admin who files on a project they do not
        personally hold an assignment for."""
        self.assertNotIn("admin", server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS)
        self.assertNotIn("owner", server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS)

    def test_site_device_is_not_project_scoped_here(self):
        """A site device is scoped by project_access_ok branch 1 — the project
        it was provisioned for — not by assigned_projects, which it has none
        of."""
        self.assertNotIn("site_device", server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS)

    def test_project_access_ok_is_untouched(self):
        """This fix narrows ONE branch of create_logbook. It does not widen the
        three-branch rule, which is a security decision and gets its own PR."""
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.project_access_ok))))
        self.assertNotIn("ROLES_SCOPED_TO_ASSIGNED_PROJECTS", code)
        self.assertNotIn("is_superintendent", code)


if __name__ == "__main__":
    unittest.main()
