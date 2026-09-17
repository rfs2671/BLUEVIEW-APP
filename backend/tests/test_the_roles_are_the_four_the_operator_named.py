"""User Management offers four roles, and the server is what enforces it.

── WHAT WAS ACTUALLY OPEN ──────────────────────────────────────────────────

POST /admin/users took `role` off the request body and wrote it to the user
document untouched. There was no validation anywhere on the path -- not in
UserCreate, whose declaration is `role: str = "worker"`, and not in the handler.
PUT /admin/users/{id} was the same, through `ALLOWED_USER_FIELDS`, which has
carried "role" since it was written.

So an admin console could mint:

  * "owner", which `get_admin_user` admits and which `is_platform_operator`
    does not grant -- but which, before #? closed it, skipped the tenant filter
    on GET /admin/users. That filter is now on the FLAG, so this is no longer a
    cross-tenant read; it is still a role an admin should not be able to hand
    out, because "owner" means "created this company".
  * "worker", which the operator has now withdrawn. It was the MODEL DEFAULT
    and the second button on both role pickers, so it was also what a POST with
    no role at all produced.
  * any typo at all, which produces an account matching no gate. That account
    reads as broken rather than as refused, and the person holding it files a
    support ticket instead of being told no.

── THE FOUR, AND THE ORDER ─────────────────────────────────────────────────

Admin, Site Manager / PM, Superintendent, CP. A tuple rather than a set so the
picker's order and the 422's order are the same thing, most privileged first.

── THE TEST THAT MATTERS IS THE SECOND WRITER ──────────────────────────────

An allow-list on create alone would refuse "owner" at the door and admit it
through the window: create a cp, then PUT a role of "owner". Both writers are
asserted, and they are asserted through the ROUTE'S OWN SOURCE rather than by
calling the validator -- the question is not "does the validator work", it is
"is it on the path".
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

from fastapi import HTTPException  # noqa: E402


def _src(fn) -> str:
    return ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))


class TheFourRoles(unittest.TestCase):
    def test_the_allow_list_is_exactly_the_operators_four_in_order(self):
        self.assertEqual(
            server.ASSIGNABLE_ROLES,
            ("admin", "pm", "superintendent", "cp"),
        )

    def test_the_names_are_used_and_not_restated(self):
        """`pm` and `superintendent` come from the constants, so a rename moves
        the allow-list with them rather than leaving a literal behind."""
        self.assertIn(server.ROLE_PM, server.ASSIGNABLE_ROLES)
        self.assertIn(server.ROLE_SUPERINTENDENT, server.ASSIGNABLE_ROLES)

    def test_worker_is_withdrawn(self):
        with self.assertRaises(HTTPException) as ctx:
            server.assert_assignable_role("worker")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_owner_is_not_assignable(self):
        """It is minted by self-serve registration and means "created this
        company". An admin handing it out is a different act from a signup."""
        with self.assertRaises(HTTPException):
            server.assert_assignable_role("owner")

    def test_site_device_is_not_assignable(self):
        with self.assertRaises(HTTPException):
            server.assert_assignable_role("site_device")

    def test_a_typo_is_refused_rather_than_stored(self):
        with self.assertRaises(HTTPException):
            server.assert_assignable_role("superintendant")

    def test_an_absent_role_is_refused_by_name(self):
        """UserCreate still defaults to "worker", so a POST that omits `role`
        arrives here holding the withdrawn value. It must be told which roles
        exist, not silently given one."""
        for absent in (None, "", "   "):
            with self.assertRaises(HTTPException) as ctx:
                server.assert_assignable_role(absent)
            self.assertIn("cp", str(ctx.exception.detail))

    def test_it_normalises_before_it_judges(self):
        """`role` arrives off a JSON body typed by a human. " CP " is not a role
        nobody holds; it is "cp" with whitespace."""
        for given in ("cp", "CP", " Cp ", "\tcp\n"):
            self.assertEqual(server.assert_assignable_role(given), "cp")
        self.assertEqual(
            server.assert_assignable_role("Superintendent"),
            server.ROLE_SUPERINTENDENT,
        )

    def test_the_refusal_names_what_may_be_assigned(self):
        """A 422 saying only "invalid role" makes the caller guess. The four
        are printed, in the picker's order."""
        with self.assertRaises(HTTPException) as ctx:
            server.assert_assignable_role("worker")
        detail = str(ctx.exception.detail)
        for role in server.ASSIGNABLE_ROLES:
            self.assertIn(role, detail)


class BothWritersAreOnTheList(unittest.TestCase):
    """The window as well as the door. See the header."""

    def test_create_admin_user_validates_the_role(self):
        self.assertIn("assert_assignable_role", _src(server.create_admin_user))

    def test_update_admin_user_validates_the_role(self):
        self.assertIn("assert_assignable_role", _src(server.update_admin_user))

    def test_role_is_still_editable_at_all(self):
        """If `role` ever leaves ALLOWED_USER_FIELDS the validator above
        becomes decoration, and this test would still pass on its own. Pin the
        premise: the edit path CAN write a role, and that is why it is checked.
        """
        self.assertIn("'role'", _src(server.update_admin_user))


class TheLicenceBelongsToOneRole(unittest.TestCase):
    """A DOB registration number on a CP's account is a claim about a
    credential nobody holds, and `superintendent_licence_state` would badge it.
    """

    def test_create_drops_the_licence_for_a_non_superintendent(self):
        src = _src(server.create_admin_user)
        self.assertIn("ROLE_SUPERINTENDENT", src)
        self.assertIn("dob_superintendent_number", src)

    def test_update_clears_the_licence_on_demotion(self):
        """The forgotten direction. Setting the fields on promotion is obvious;
        an account demoted out of `superintendent` keeping a live expiry is the
        defect."""
        src = _src(server.update_admin_user)
        self.assertIn("$unset", src)
        self.assertIn("SUPERINTENDENT_LICENCE_FIELDS", src)

    def test_the_card_image_never_reaches_the_user_document(self):
        """`dob_card_image` is a base64 data URL. A field inside
        ALLOWED_USER_FIELDS is $set verbatim, so its ABSENCE from that set is
        what keeps image bytes out of db.users -- the same collection whose
        inline signatures produced two 500s in one day."""
        src = inspect.getsource(server.update_admin_user)
        allowed = src[src.index("ALLOWED_USER_FIELDS = {"):]
        allowed = allowed[:allowed.index("}")]
        self.assertNotIn("dob_card_image", allowed)
        self.assertIn("dob_superintendent_number", allowed)


if __name__ == "__main__":
    unittest.main()
