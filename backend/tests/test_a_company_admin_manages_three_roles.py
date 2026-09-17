"""A COMPANY ADMIN SEES AND MANAGES PM, SUPERINTENDENT AND CP. NOBODY ELSE.

OPERATOR RULING. User Management, opened by a company admin, is the list of the
people he administers: the Site Managers, the superintendents and the CPs of his
own company. It is not the list of his peers and it is not a mirror. ADMIN
ACCOUNTS ARE THE PLATFORM OPERATOR'S TO MANAGE, in the owner panel, and the
operator viewing a company still sees everybody in it.

── ONE CLAUSE DELIVERS BOTH HALVES, AND THAT IS WHY IT IS ONE CLAUSE ─────────

"not other admins" and "not himself" are not two rules. He IS an admin, so a
filter that drops the admin role drops him with them. A second, separate
`_id != me` clause would be a second place the answer lives, and the day the
role list changes the two would disagree about who is looking at the screen.

── AND WHY THE PICKER HAD TO MOVE IN THE SAME CHANGE ────────────────────────

`ASSIGNABLE_ROLES` offers "admin". Under the filter alone, a company admin could
still CREATE an admin -- and then watch it vanish on the next refresh. That is
precisely the defect #576 fixed (`.filter(u => u.role !== 'admin')` on the
client, "created users don't vanish"), reintroduced by design from the other
end. So `POST /admin/users` refuses `role: admin` from a non-operator, `PUT`
refuses the same promotion through the second door, and the picker stops
offering it. The platform operator keeps all four.

THE REFUSAL IS THE GATE AND THE PICKER IS NOT. Deleting a button stops the app
sending a value and stops nothing else -- the same sentence
`assert_assignable_role` is written under, for the same reason.

── WHAT THIS FILTER ALSO HIDES, NAMED RATHER THAN DISCOVERED LATER ──────────

It is an ALLOW-LIST of three, so a legacy row holding "worker", "owner" or
"demo" is hidden from a company admin too. That is deliberate and it is the
ruling's shape -- those accounts reach no screen of their own and none of them
is a person he administers -- but it does mean a company admin cannot delete
one. The platform operator can: his view carries no role clause at all, which
the last class here asserts in both directions.
"""

from __future__ import annotations

import asyncio
import copy
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

#: One company with one of everything, plus a second tenant to prove the
#: company filter is still doing its own job underneath the role filter.
_DOCS = [
    {"_id": "me", "name": "The Admin Looking", "email": "me@a.com",
     "role": "admin", "company_id": "c1", "is_deleted": False},
    {"_id": "peer", "name": "Another Admin", "email": "peer@a.com",
     "role": "admin", "company_id": "c1", "is_deleted": False},
    {"_id": "pm1", "name": "A Site Manager", "email": "pm@a.com",
     "role": "pm", "company_id": "c1", "is_deleted": False},
    {"_id": "su1", "name": "Michael Cespedes", "email": "su@a.com",
     "role": "superintendent", "company_id": "c1", "is_deleted": False},
    {"_id": "cp1", "name": "A Competent Person", "email": "cp@a.com",
     "role": "cp", "company_id": "c1", "is_deleted": False},
    # Legacy rows. Named in the docstring above: an allow-list hides them.
    {"_id": "old", "name": "A Legacy Worker", "email": "w@a.com",
     "role": "worker", "company_id": "c1", "is_deleted": False},
    {"_id": "sig", "name": "A Fresh Signup", "email": "d@a.com",
     "role": "demo", "company_id": "c1", "is_deleted": False},
    # The other tenant, so "sees only three roles" cannot be mistaken for
    # "sees only his company" passing by itself.
    {"_id": "cp2", "name": "Other Tenant CP", "email": "cp@b.com",
     "role": "cp", "company_id": "c2", "is_deleted": False},
]


def _match(doc, query):
    for k, cond in query.items():
        v = doc.get(k)
        if isinstance(cond, dict):
            if "$ne" in cond and v == cond["$ne"]:
                return False
            if "$in" in cond and v not in cond["$in"]:
                return False
        elif v != cond:
            return False
    return True


class _Users:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    def find(self, query=None, projection=None):
        self.queries.append(query or {})
        return [d for d in self.docs if _match(d, query or {})]


class Base(unittest.TestCase):
    def setUp(self):
        self.users = _Users(_DOCS)
        self._orig = {"db": server.db, "gid": server.get_user_company_id,
                      "op": server.is_platform_operator,
                      "pq": server.paginated_query}

        async def _paginated(coll, query, **kw):
            rows = coll.find(query, kw.get("projection"))
            return {"items": [copy.deepcopy(r) for r in rows],
                    "total": len(rows), "has_more": False}

        class _DB:
            users = self.users
            # No superintendent in the page is missing a licence number in
            # these fixtures, so the registration fallback never queries. It
            # is stubbed anyway: a collection that is absent rather than empty
            # would make an unrelated failure look like this one.
            cs_registrations = _Registrations()

        server.db = _DB()
        server.paginated_query = _paginated

    def tearDown(self):
        server.db = self._orig["db"]
        server.get_user_company_id = self._orig["gid"]
        server.is_platform_operator = self._orig["op"]
        server.paginated_query = self._orig["pq"]

    def call(self, user):
        return asyncio.run(server.get_admin_users(user))

    def names(self, user):
        return {r["name"] for r in self.call(user)["items"]}


class _Registrations:
    """Empty, and it records whether anything asked."""

    def __init__(self):
        self.queries = []

    def find(self, query=None, projection=None):
        self.queries.append(query or {})
        return _Cursor([])


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return self.rows[:n]


class ACompanyAdminSeesTheThreeHeManages(Base):
    """THE RULING. Every assertion in this class failed before the change."""

    def setUp(self):
        super().setUp()
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False

    def me(self):
        return {"id": "me", "_id": "me", "role": "admin", "company_id": "c1"}

    def test_he_sees_the_pm_the_superintendent_and_the_cp(self):
        got = self.names(self.me())
        self.assertEqual(
            got, {"A Site Manager", "Michael Cespedes", "A Competent Person"})

    def test_he_does_not_see_another_admin(self):
        self.assertNotIn("Another Admin", self.names(self.me()))

    def test_and_he_does_not_see_himself(self):
        """THE SECOND HALF OF THE SAME CLAUSE. He is an admin; dropping the
        role drops him. Nothing here tests an `_id != me` rule, because there
        is deliberately no such rule to test."""
        self.assertNotIn("The Admin Looking", self.names(self.me()))

    def test_the_other_tenant_is_still_out_of_reach(self):
        """The company filter is UNDER the role filter, not replaced by it.
        A CP of another company holds an admitted role."""
        self.assertNotIn("Other Tenant CP", self.names(self.me()))

    def test_a_legacy_worker_or_demo_row_is_not_his_to_manage(self):
        got = self.names(self.me())
        self.assertNotIn("A Legacy Worker", got)
        self.assertNotIn("A Fresh Signup", got)

    def test_the_clause_is_a_role_allow_list_of_exactly_three(self):
        self.call(self.me())
        q = self.users.queries[0]
        self.assertIn("role", q)
        self.assertEqual(set(q["role"]["$in"]),
                         {"pm", "superintendent", "cp"})
        self.assertEqual(q.get("company_id"), "c1")

    def test_a_company_less_admin_still_sees_nobody(self):
        """The unsatisfiable filter survives. The role clause must not become a
        way back in for a caller who owns nobody."""
        server.get_user_company_id = lambda u: None
        self.assertEqual(self.names(self.me()), set())


class TheOperatorViewingACompanyStillSeesEveryone(Base):
    """THE OTHER DIRECTION. A filter that hid admins from EVERYBODY would
    satisfy the class above and would take the operator's own product away from
    him -- he administers admins, and the owner panel reads this route."""

    def setUp(self):
        super().setUp()
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: True

    def test_he_sees_every_role_in_every_tenant(self):
        got = self.names({"id": "root", "role": "admin",
                          "is_platform_operator": True})
        self.assertEqual(len(got), len(_DOCS))
        self.assertIn("Another Admin", got)
        self.assertIn("A Legacy Worker", got)
        self.assertIn("Other Tenant CP", got)

    def test_and_his_query_carries_no_role_clause_at_all(self):
        self.call({"id": "root", "role": "admin", "is_platform_operator": True})
        q = self.users.queries[0]
        self.assertNotIn("role", q)
        self.assertNotIn("company_id", q)
        self.assertNotIn("_id", q)


class AnAdminMayNotMintAnAdmin(unittest.TestCase):
    """THE PICKER'S GATE, ASKED DIRECTLY.

    `assert_role_assignable_by` is the whole rule: the existing allow-list, plus
    who the actor is. Both write routes call it, so there is one answer rather
    than a create-side answer and an edit-side answer that drift.
    """

    OPERATOR = {"id": "root", "role": "admin", "is_platform_operator": True}
    ADMIN = {"id": "me", "role": "admin", "company_id": "c1"}

    def test_a_company_admin_is_refused_the_admin_role(self):
        with self.assertRaises(HTTPException) as cm:
            server.assert_role_assignable_by("admin", self.ADMIN)
        self.assertEqual(cm.exception.status_code, 403)

    def test_and_whitespace_and_case_do_not_get_round_it(self):
        for spelling in (" Admin ", "ADMIN", "aDmIn"):
            with self.assertRaises(HTTPException) as cm:
                server.assert_role_assignable_by(spelling, self.ADMIN)
            self.assertEqual(cm.exception.status_code, 403, spelling)

    def test_he_may_still_assign_the_three_he_manages(self):
        for role in ("pm", "superintendent", "cp"):
            self.assertEqual(
                server.assert_role_assignable_by(role, self.ADMIN), role)

    def test_the_platform_operator_keeps_admin(self):
        self.assertEqual(
            server.assert_role_assignable_by("admin", self.OPERATOR), "admin")

    def test_a_role_off_the_allow_list_is_still_422_and_not_403(self):
        """The two refusals stay distinguishable. "worker" is not a role the
        operator may hand out either, and calling that a permission problem
        would send an admin looking for a permission he cannot be given."""
        for actor in (self.ADMIN, self.OPERATOR):
            with self.assertRaises(HTTPException) as cm:
                server.assert_role_assignable_by("worker", actor)
            self.assertEqual(cm.exception.status_code, 422)

    def test_the_refusal_names_what_he_may_do_instead(self):
        """A 403 that says only "forbidden" sends an admin to support. This one
        says who creates an admin account."""
        with self.assertRaises(HTTPException) as cm:
            server.assert_role_assignable_by("admin", self.ADMIN)
        self.assertIn("admin", str(cm.exception.detail).lower())


class TheOtherTwoSCREENSReadThisListToo(unittest.TestCase):
    """NAMED, BECAUSE THE FILTER NARROWS THEM AND NOBODY ASKED IT TO.

    `adminUsersAPI.getAll` has THREE callers, which the projection's own comment
    enumerates. This change was ruled for one of them and lands on all three:

      app/admin/users.jsx          the screen the ruling is about.
      app/admin/checklists/index.jsx   the "assign this checklist to" picker.
                                   An admin can no longer be assigned a
                                   checklist by another admin — consistent with
                                   the ruling, and a change to that screen.
      app/admin/superintendent.jsx the "link an account to a CS registration"
                                   picker, whose own comment reads "EVERY
                                   APPROVED USER IN THE COMPANY, NO ROLE FILTER
                                   ... Michael is role 'cp' and IS the
                                   construction superintendent." A company
                                   ADMIN who is also the CS on a job can no
                                   longer be linked from that screen.

    THE COUNT IS THREE AND THE THIRD IS THE ONE TO WATCH. This test does not
    assert that the consequence is right — the operator rules that. It asserts
    the population has not grown behind the ruling: a FOURTH caller would be a
    screen narrowed by a decision nobody made about it.

    The remedy, if the operator wants that screen to see everyone, is one
    optional query parameter on this route, admitted only for a caller that
    names it — not the removal of the clause.
    """

    CALLERS = (
        "app/admin/users.jsx",
        "app/admin/checklists/index.jsx",
        "app/admin/superintendent.jsx",
    )

    def test_the_callers_are_still_exactly_these_three(self):
        frontend = _BACKEND.parent / "frontend"
        found = set()
        for path in frontend.rglob("*.js*"):
            rel = path.relative_to(frontend).as_posix()
            if rel.startswith(("node_modules/", "dist/")):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "adminUsersAPI.getAll" in text and "export const adminUsersAPI" not in text:
                found.add(rel)
        self.assertEqual(
            found, set(self.CALLERS),
            "the set of screens this role filter narrows has changed")


class BothWriteRoutesAskTheSameQuestion(unittest.TestCase):
    """THE SECOND DOOR. `role` is in ALLOWED_USER_FIELDS, so a create-side
    refusal alone would be refused at the door and admitted through the window:
    create a cp, PUT a role of "admin". Both writers or neither -- the same
    sentence `assert_assignable_role` was given when IT gained an edit-side
    caller."""

    def test_create_and_update_both_route_through_the_actor_aware_check(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        for fn in ("async def create_admin_user(", "async def update_admin_user("):
            i = src.index(fn)
            body = src[i:i + 6000]
            code = "\n".join(l for l in body.split("\n")
                             if not l.lstrip().startswith("#"))
            self.assertIn("assert_role_assignable_by(", code,
                          f"{fn} does not ask who the actor is")


if __name__ == "__main__":
    unittest.main(verbosity=2)
