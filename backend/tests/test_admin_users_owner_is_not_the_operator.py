"""`role == "owner"` IS NOT THE PLATFORM OPERATOR, AND A LIVE ACCOUNT PROVED IT.

`GET /admin/users` filtered like this:

    if current_user.get("role") != "owner" and company_id:
        query["company_id"] = company_id

so ANY owner skipped the tenant filter and received every user on the platform:
name, email, PHONE, role, company and assigned projects, 500 rows a page.

THE TWO FACTS THAT MAKE THAT THE ORDINARY PATH, NOT AN EDGE CASE:

  * `register` sets `role = "owner"` and `company_id = None` on EVERY
    self-serve signup.
  * `get_admin_user` admits any role in ("admin", "owner").

So the gate on the route and the carve-out inside it were satisfied by the same
fact — having registered. Both halves of the compound condition were true for a
brand-new account, and neither was about being trusted.

NOT HYPOTHETICAL. The platform holds two owner accounts with a null company.
One carries `is_platform_operator`; the other does not, and could read the
first's email and phone number today. The census that found this shape was
about a pattern; this test is about an account that exists.

`is_platform_operator` IS THE FUNCTION THAT MEANS THIS, and it is now the only
carve-out. Asserted in BOTH directions, because a carve-out is only as good as
the case it refuses: the flagged account still sees everyone, and an UNFLAGGED
owner with no company sees nobody.

THIRD FIX OF THIS SHAPE TODAY, and the first one that did not need a null
company to fire. `get_workers` and `get_company_roster` leaked only to a caller
between signup and onboarding; this leaked to every customer owner, always.
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

#: The shape production holds: two owners with no company, one of them flagged.
_DOCS = [
    {"_id": "u1", "name": "Michael Cespedes", "email": "m@a.com",
     "phone": "212-555-0134", "role": "cp", "company_id": "c1",
     "is_deleted": False},
    {"_id": "u2", "name": "Company Owner", "email": "o@a.com",
     "phone": "212-555-0100", "role": "owner", "company_id": "c1",
     "is_deleted": False},
    {"_id": "u3", "name": "Other Tenant", "email": "x@b.com",
     "phone": "718-555-0199", "role": "admin", "company_id": "c2",
     "is_deleted": False},
    {"_id": "u4", "name": "Fresh Signup", "email": "t@ios.com",
     "phone": "", "role": "owner", "company_id": None, "is_deleted": False},
]


def _match(doc, query):
    for k, cond in query.items():
        v = doc.get(k)
        if isinstance(cond, dict):
            if "$ne" in cond and v == cond["$ne"]:
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


class AnUnflaggedOwnerIsScopedLikeAnybodyElse(Base):
    """THE DEFECT. Every assertion here failed before this change."""

    def test_an_owner_WITH_a_company_sees_only_that_company(self):
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False
        got = self.names({"id": "u2", "role": "owner"})
        self.assertEqual(got, {"Michael Cespedes", "Company Owner"})
        self.assertNotIn("Other Tenant", got)

    def test_an_owner_with_NO_company_sees_nobody(self):
        """The live account: an owner, a null company, no operator flag. It
        could read a real CP's email and phone number."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        self.assertEqual(self.names({"id": "u4", "role": "owner"}), set())

    def test_and_that_refusal_is_an_unsatisfiable_filter(self):
        """One code path, one response shape. `company_id: None` would be worse
        than the bug -- it matches precisely the other un-onboarded signups."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        self.call({"id": "u4", "role": "owner"})
        q = self.users.queries[0]
        self.assertIn("_id", q)
        self.assertIsNone(q["_id"])
        self.assertNotIn("company_id", q)

    def test_no_email_or_phone_of_another_tenant_is_returned(self):
        """THE PAYLOAD, asserted rather than implied. The projection carries
        `email` and `phone`; the leak was those fields for every user on the
        platform."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        body = repr(self.call({"id": "u4", "role": "owner"}))
        for secret in ("m@a.com", "212-555-0134", "x@b.com", "718-555-0199"):
            self.assertNotIn(secret, body)


class TheFlaggedOperatorKeepsTheCrossTenantView(Base):
    """THE OTHER DIRECTION. A carve-out is only as good as the case it refuses,
    and a guard that refused everybody would satisfy the class above."""

    def test_the_platform_operator_still_sees_every_tenant(self):
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: True
        self.assertEqual(len(self.names({"id": "root", "role": "owner"})), 4)

    def test_and_the_operator_query_carries_no_tenant_predicate(self):
        """Which is the premise of the projection reasoning beside the field
        list: the operator's call has no equality predicate, so nothing but an
        index led by `name` could serve it."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: True
        self.call({"id": "root", "role": "owner"})
        q = self.users.queries[0]
        self.assertNotIn("company_id", q)
        self.assertNotIn("_id", q)

    def test_the_flag_is_what_decides_it_and_not_the_role(self):
        """Same role, same absent company, opposite outcomes."""
        server.get_user_company_id = lambda u: None
        user = {"id": "x", "role": "owner"}

        server.is_platform_operator = lambda u: True
        self.assertEqual(len(self.names(user)), 4)

        self.users.queries.clear()
        server.is_platform_operator = lambda u: False
        self.assertEqual(self.names(user), set())


class TheRoleIsNeverConsultedForTenancyAgain(unittest.TestCase):
    """The regression guard. The defect was a ROLE STRING standing in for a
    trust decision, so the check is that the role has left the filter."""

    def test_the_tenant_filter_does_not_mention_the_role(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("async def get_admin_users(")
        j = src.index("USER_LIST_FIELDS = {", i)
        body = src[i:j]
        # Comments explain the removed condition by quoting it, so read the
        # code: this is the trap the harness doc records four times.
        code = "\n".join(l for l in body.split("\n")
                         if not l.lstrip().startswith("#"))
        self.assertNotIn('"role"', code,
                         "the role is back in the tenant decision")
        self.assertIn("is_platform_operator(current_user)", code)
        self.assertIn('query["_id"] = None', code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
