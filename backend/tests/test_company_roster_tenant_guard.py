"""A CALLER WITH NO COMPANY RECEIVED EVERY USER ON THE PLATFORM.

`GET /users/company-roster` returns name, email and role for the caller's
company, and any authenticated caller may hit it. Its tenant filter was:

    if company_id:
        query["company_id"] = company_id

so a caller whose `company_id` is falsy skipped the filter entirely and got the
whole `users` collection, capped at 500.

**AND THAT IS THE DEFAULT ACCOUNT STATE.** Self-serve registration sets
`company_id = None`; a company is attached later by `POST /onboarding/company`.
So a trial signup could read the platform's user directory — names and email
addresses — with nothing but a valid token.

MEASURED BEFORE THE ALARM, NOT AFTER: 2 of 8 live users carry a null
`company_id`, and the directory is 8 people. The leak is real, the shape is one
already fixed twice, and today's harm is negligible. It is fixed because it is
wrong and because it scales with every self-serve signup — not as an incident.
(docs/audits/check-harness.md §9.)

THIRD INSTANCE OF THE SHAPE IN ONE FILE. `get_workers` was fixed after the same
leak and its comment explains the reasoning at length; `get_project_roster` was
written with the guard; this one kept the pre-fix form. The ported-fix pattern,
on a tenant boundary.

WHY `_id: None` AND NOT AN EARLY RETURN. An unsatisfiable filter keeps one code
path and one response shape: a caller who owns nobody gets exactly what a
company with no other users gets. `company_id: None` would be worse than the
bug — it matches precisely the orphan rows, i.e. every other un-onboarded
signup.
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


def _match(doc, query):
    for k, cond in query.items():
        v = doc.get(k)
        if isinstance(cond, dict):
            if "$ne" in cond and v == cond["$ne"]:
                return False
        elif v != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Users:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    def find(self, query=None, projection=None):
        self.queries.append(query or {})
        return _Cursor([d for d in self.docs if _match(d, query or {})])


class _DB:
    def __init__(self, users):
        self.users = users


#: Two tenants and one un-onboarded signup, the shape production actually holds.
_DOCS = [
    {"_id": "u1", "name": "Michael Cespedes", "email": "m@a.com",
     "role": "cp", "company_id": "c1", "is_deleted": False},
    {"_id": "u2", "name": "Roy Fishman", "email": "r@a.com",
     "role": "admin", "company_id": "c1", "is_deleted": False},
    {"_id": "u3", "name": "Other Tenant", "email": "o@b.com",
     "role": "admin", "company_id": "c2", "is_deleted": False},
    {"_id": "u4", "name": "Fresh Signup", "email": "f@c.com",
     "role": "owner", "company_id": None, "is_deleted": False},
]


class Base(unittest.TestCase):
    def setUp(self):
        self.users = _Users(_DOCS)
        self._orig = {"db": server.db, "gid": server.get_user_company_id,
                      "op": server.is_platform_operator}
        server.db = _DB(self.users)

    def tearDown(self):
        server.db = self._orig["db"]
        server.get_user_company_id = self._orig["gid"]
        server.is_platform_operator = self._orig["op"]

    def call(self, user):
        return asyncio.run(server.get_company_roster(user))


class ACallerWithNoCompanySeesNobody(Base):

    def test_the_default_account_state_gets_an_empty_list(self):
        """Self-serve registration sets company_id = None. This is not an edge
        case; it is every account between signup and onboarding."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        self.assertEqual(self.call({"id": "u4"}), [])

    def test_the_refusal_is_an_UNSATISFIABLE_FILTER_not_a_second_path(self):
        """One code path and one response shape. `_id: None` cannot match; a
        caller who owns nobody gets what a company with no other users gets."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        self.call({"id": "u4"})
        self.assertEqual(len(self.users.queries), 1)
        self.assertEqual(self.users.queries[0].get("_id"), None)
        self.assertIn("_id", self.users.queries[0],
                      "the key must be PRESENT and None, not absent")

    def test_it_is_NOT_company_id_None(self):
        """That would be worse than the bug: it matches precisely the orphan
        rows — every other un-onboarded signup."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        self.call({"id": "u4"})
        self.assertNotIn("company_id", self.users.queries[0])

    def test_an_empty_string_company_is_treated_the_same_as_None(self):
        """`if company_id:` is falsy for both, and a stored "" is a real state.
        The refusal has to cover what the old condition covered."""
        server.get_user_company_id = lambda u: ""
        server.is_platform_operator = lambda u: False
        self.assertEqual(self.call({"id": "u4"}), [])


class TheOrdinaryCasesAreUnchanged(Base):

    def test_a_company_user_sees_their_own_company(self):
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False
        names = {r["name"] for r in self.call({"id": "u1"})}
        self.assertEqual(names, {"Michael Cespedes", "Roy Fishman"})

    def test_and_never_the_other_tenant(self):
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False
        names = {r["name"] for r in self.call({"id": "u1"})}
        self.assertNotIn("Other Tenant", names)

    def test_the_response_shape_is_unchanged(self):
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False
        row = self.call({"id": "u1"})[0]
        self.assertEqual(sorted(row), ["email", "id", "name", "role"])

    def test_the_platform_operator_carve_out_is_explicit(self):
        """Never inferred from `role` — "owner" is what every self-serve signup
        receives, which is exactly the account this guard exists to stop."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: True
        self.assertEqual(len(self.call({"id": "root"})), 4)

    def test_an_owner_role_alone_does_NOT_open_the_platform(self):
        """The control on the carve-out. `role: "owner"` with no company is the
        un-onboarded signup, and it must see nobody."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        self.assertEqual(self.call({"id": "u4", "role": "owner"}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
