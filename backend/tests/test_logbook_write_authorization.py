"""WHAT ACTUALLY GATES A LOGBOOK WRITE — written down because it was misread.

THIS FILE CHANGES NO BEHAVIOUR. It exists because an audit of `/finalize`
reached the wrong conclusion twice, and the thing that misled it is still in
the source and is staying there. A wrong conclusion about what is enforced is
worth a test even when nothing needs fixing.

── THE MISREADING ───────────────────────────────────────────────────────────

    existing = await _authorize_logbook_write(logbook_id, current_user)
    if current_user.get("role") == "cp":
        assigned = ...
        if existing.get("project_id") not in assigned: 403

Read from the bottom up, that names ONE role and refuses it, which invites the
conclusion that every other role is ungated — that finalize "happens to work
for the current CP by accident", and that a `superintendent` account would
freeze any project's records.

IT IS NOT THE GATE. `_authorize_logbook_write`, the line above, runs
`user_can_act_on_project`, which is ROLE-BLIND except for the admin branch: a
company admin/owner of the project's company, OR anyone assigned to the
project. Every role is covered, including one that does not exist yet.

── THE DUPLICATE IS DELIBERATE AND STAYS ────────────────────────────────────

update_logbook says why, and it applies to all three: "kept ahead of the
general rule for its specific message. Subsumed by the assigned branch above,
and cheap." The authorizer raises "Not authorized for this logbook"; the
duplicate raises "Not assigned to this project", which is the sentence that
tells a CP what to do about it.

update, amend and finalize all carry it. Removing it from one was tried and
reverted: it would have made that one INCONSISTENT with the other two and
degraded a 403 message, in the name of tidiness.

── AND THE COST GATE'S ABSENCE IS NOT A HOLE ────────────────────────────────

`require_approved` is on create and update, and not on finalize / amend /
delete. test_logbook_writes_require_approved.py records that as a scope
decision belonging to the operator, since the gate is cost control and those
three spend nothing.

The reachability half is asserted here: a pending account cannot reach them
anyway. /auth/register is the only writer of "pending" and forces role="owner"
with company_id=None, so the admin branch cannot match a real project and the
assigned branch has an empty list.

WHAT WOULD MAKE THIS FILE WRONG: `user_can_act_on_project` gaining a role
branch, `_authorize_logbook_write` being dropped from a handler, or a pending
account acquiring a company_id. Each is asserted.
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
from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")

ID_ADDRESSED_WRITES = ("update_logbook", "finalize_logbook",
                       "amend_logbook", "delete_logbook")


def _fn_body(name: str) -> str:
    start = SRC.index(f"async def {name}(")
    nxt = SRC.find("\n@api_router.", start)
    return SRC[start:nxt if nxt != -1 else len(SRC)]


class TheSharedAuthorizerIsTheGate(unittest.TestCase):
    def test_every_id_addressed_write_goes_through_it(self):
        """THE ACTUAL ENFORCEMENT, asserted where a reader will look for it."""
        for fn in ID_ADDRESSED_WRITES:
            with self.subTest(fn=fn):
                self.assertIn("_authorize_logbook_write", _fn_body(fn))

    def test_it_runs_BEFORE_any_per_role_check(self):
        """The order is what makes the duplicate cosmetic rather than the gate.
        If a handler ever checked a role FIRST and authorized after, the
        misreading would become correct."""
        for fn in ID_ADDRESSED_WRITES:
            body = _fn_body(fn)
            role_at = body.find('current_user.get("role") == "cp"')
            if role_at == -1:
                continue
            with self.subTest(fn=fn):
                self.assertLess(body.index("_authorize_logbook_write"), role_at)

    def test_the_authorizer_is_role_blind_apart_from_the_admin_branch(self):
        """No allowlist of roles, so a role added tomorrow is covered today —
        which is the property #338 had to add to create_logbook by hand,
        because create takes a project id in the body and never had this."""
        body = SRC[SRC.index("def user_can_act_on_project("):]
        body = body[:body.index("\nasync def", 1) if "\nasync def" in body[1:] else 4000]
        self.assertNotIn("superintendent", body)
        self.assertIn('role in ("admin", "owner")', body)


class WhoTheAuthorizerAllows(unittest.TestCase):
    """RUN, NOT READ. The claim is about behaviour, so it is exercised."""

    PROJECT = {"company_id": "c1"}

    def _can(self, **user):
        return server.user_can_act_on_project(self.PROJECT, "p1", user)

    def test_an_assigned_cp_may_act(self):
        self.assertTrue(self._can(id="u1", role="cp", company_id="c1",
                                  assigned_projects=["p1"]))

    def test_an_unassigned_cp_may_not(self):
        """Exactly what the duplicate says — produced by the authorizer."""
        self.assertFalse(self._can(id="u2", role="cp", company_id="c1",
                                   assigned_projects=[]))

    def test_an_unassigned_SUPERINTENDENT_may_not(self):
        """THE ROLE THE DUPLICATE NEVER MENTIONS, and the reason the wrong
        audit sounded plausible. It was covered all along."""
        self.assertFalse(self._can(id="u3", role=server.ROLE_SUPERINTENDENT,
                                   company_id="c1", assigned_projects=[]))

    def test_an_ASSIGNED_superintendent_may(self):
        self.assertTrue(self._can(id="u4", role=server.ROLE_SUPERINTENDENT,
                                  company_id="c1", assigned_projects=["p1"]))

    def test_a_company_admin_may(self):
        self.assertTrue(self._can(id="u5", role="admin", company_id="c1",
                                  assigned_projects=[]))

    def test_an_admin_of_ANOTHER_company_may_not(self):
        self.assertFalse(self._can(id="u6", role="admin", company_id="c2",
                                   assigned_projects=[]))

    def test_an_unknown_role_may_not(self):
        """Fails closed on a role nobody has thought of yet."""
        self.assertFalse(self._can(id="u7", role="auditor", company_id="c1",
                                   assigned_projects=[]))

    def test_a_PENDING_account_may_not_even_without_require_approved(self):
        """WHY THE ABSENT COST GATE IS NOT REACHABLE on finalize/amend/delete.

        Pending is only ever set by /auth/register, which forces role="owner"
        and company_id=None on the same path. None matches no real project, so
        the admin branch fails; the assigned list is empty, so that fails too.
        """
        self.assertFalse(self._can(id="u9", role="owner", company_id=None,
                                   account_status="pending",
                                   assigned_projects=[]))


class TheDuplicateStaysAndSaysWhy(unittest.TestCase):
    """A GUARD ON THE REVERT — deleting it was tried and undone.

    It is redundant, and it is NOT noise: it produces the sentence that tells a
    CP what is wrong. Removing it from one handler would leave three that
    disagree about how they refuse.
    """

    def test_all_three_that_carry_it_still_do(self):
        """THE INVARIANT IS THE SCOPE CHECK AND ITS MESSAGE, not the predicate.

        This asserted the literal `current_user.get("role") == "cp"`, which is
        a stronger claim than the docstring above makes: the reason the
        duplicate stays is that it produces the SPECIFIC sentence, and that is
        unchanged. The predicate itself widened to
        ROLES_SCOPED_TO_ASSIGNED_PROJECTS because #338 added superintendents to
        create_logbook and left these three spelled the old way — so a
        superintendent could not create a logbook on an unassigned project and
        could still update, amend and FINALIZE one there.

        Pinned as "reads the shared constant" so the next role added to that
        tuple reaches all four gates without editing this file.
        """
        for fn in ("update_logbook", "finalize_logbook", "amend_logbook"):
            with self.subTest(fn=fn):
                body = _fn_body(fn)
                self.assertIn("ROLES_SCOPED_TO_ASSIGNED_PROJECTS", body)
                self.assertIn('current_user.get("assigned_projects"', body)

    def test_and_it_produces_the_more_specific_message(self):
        for fn in ("update_logbook", "finalize_logbook", "amend_logbook"):
            with self.subTest(fn=fn):
                self.assertIn("Not assigned to this project", _fn_body(fn))

    def test_while_the_authorizer_gives_the_general_one(self):
        self.assertIn('detail="Not authorized for this logbook"',
                      _fn_body("_authorize_logbook_write"))


if __name__ == "__main__":
    unittest.main()
