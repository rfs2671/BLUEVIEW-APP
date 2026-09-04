"""assigned_projects is an AUTHORIZATION GRANT — validate every write to it.

require_project_access branch 3 (server.py) returns the project when its id
appears in the caller's assigned_projects:

    if str(project_id) in (current_user.get("assigned_projects") or []):
        return project

So a route that writes that list without checking WHOSE projects are going in
does not merely edit a preference — it MINTS access, and defeats every guard
that delegates to require_project_access: all 25 write endpoints gated in
6cb510e and every batch-1 read.

Two write vectors existed, and only one of them looked dangerous:

  POST /admin/users/{user_id}/assign-projects   no checks at all (SEV-0)
  PUT  /admin/users/{user_id}                   `assigned_projects` is in
                                                ALLOWED_USER_FIELDS; the route
                                                tenant-scoped the TARGET USER
                                                but never the project ids

The second is the subtle one. Scoping the target user stops a company-A admin
editing a company-B user; it does NOT stop that admin adding a company-B project
to their OWN company-A user, or to themselves. Both routes now call
validate_assignable_projects.

Every other site that writes assigned_projects sets a literal [] immediately
after model_dump() (user create, admin create, subcontractor create, company
bootstrap, startup seeding), so the Pydantic models accepting the field from a
request body is not exploitable. test_creation_paths_force_empty_list pins that,
because the safety is one line deep and a reorder would reopen it.

Directions asserted per vector:
  foreign-company project        -> 403
  own-company project            -> works
  self-assign a foreign project  -> 403   (target-user scoping alone misses this)
  platform operator cross-company-> works (the one deliberate path)
  unknown project id             -> 403   (not silently dropped)
  actor with no company_id       -> 403   (absence is not authorization)
"""

import ast
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server as S  # noqa: E402
from fastapi import HTTPException  # noqa: E402

PROJECT_A = {"_id": "projA", "company_id": "companyA", "name": "A Site"}
PROJECT_A2 = {"_id": "projA2", "company_id": "companyA", "name": "A Site 2"}
PROJECT_B = {"_id": "projB", "company_id": "companyB", "name": "B Site"}
PROJECTS = {"projA": PROJECT_A, "projA2": PROJECT_A2, "projB": PROJECT_B}

ADMIN_A = {"_id": "ua", "role": "admin", "company_id": "companyA",
           "account_status": "approved"}
ADMIN_B = {"_id": "ub", "role": "admin", "company_id": "companyB",
           "account_status": "approved"}
ADMIN_NO_COMPANY = {"_id": "un", "role": "admin", "company_id": None,
                    "account_status": "approved"}
OPERATOR = {"_id": "op", "role": "owner", "company_id": "companyA",
            "is_platform_operator": True, "account_status": "approved"}


def _db():
    """projects.find({_id: {$in: [...]}}) over the fixture set."""
    async def _to_list(n=None):
        return _to_list.rows

    def _find(query, *a, **kw):
        wanted = query.get("_id", {}).get("$in", [])
        wanted = {str(w) for w in wanted}
        cur = MagicMock()
        rows = [p for pid, p in PROJECTS.items() if pid in wanted]
        cur.to_list = AsyncMock(return_value=rows)
        return cur

    db = MagicMock()
    db.projects.find = MagicMock(side_effect=_find)
    return db


def _validate(actor, ids):
    import server
    with patch.object(server, "db", _db()):
        return asyncio.run(server.validate_assignable_projects(actor, ids))


class ForeignProjectRejected(unittest.TestCase):
    """direction 1: a project outside the caller's company is refused."""

    def test_foreign_project_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate(ADMIN_A, ["projB"])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_foreign_project_rejected_reverse(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate(ADMIN_B, ["projA"])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_mixed_list_rejects_whole_request(self):
        """A partial success must never look like a full one."""
        with self.assertRaises(HTTPException) as ctx:
            _validate(ADMIN_A, ["projA", "projB"])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_unknown_id_rejected_not_dropped(self):
        """Dropping unknown ids would let a caller probe which ids exist."""
        with self.assertRaises(HTTPException) as ctx:
            _validate(ADMIN_A, ["projA", "does-not-exist"])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_error_does_not_distinguish_foreign_from_unknown(self):
        """Distinguishing them would confirm another tenant's project id."""
        foreign = unknown = None
        try:
            _validate(ADMIN_A, ["projB"])
        except HTTPException as e:
            foreign = e.detail
        try:
            _validate(ADMIN_A, ["nope"])
        except HTTPException as e:
            unknown = e.detail
        self.assertEqual(foreign, unknown)


class OwnProjectAllowed(unittest.TestCase):
    """direction 2: the legitimate case still works (over-gate mirror)."""

    def test_own_project_allowed(self):
        self.assertEqual(_validate(ADMIN_A, ["projA"]), ["projA"])

    def test_multiple_own_projects_allowed(self):
        self.assertEqual(_validate(ADMIN_A, ["projA", "projA2"]), ["projA", "projA2"])

    def test_other_company_own_project_allowed(self):
        self.assertEqual(_validate(ADMIN_B, ["projB"]), ["projB"])

    def test_empty_list_allowed(self):
        """Clearing a user's assignments must stay possible."""
        self.assertEqual(_validate(ADMIN_A, []), [])

    def test_none_treated_as_empty(self):
        self.assertEqual(_validate(ADMIN_A, None), [])

    def test_duplicates_collapsed_order_preserved(self):
        self.assertEqual(_validate(ADMIN_A, ["projA2", "projA", "projA2"]),
                         ["projA2", "projA"])


class SelfAssignAndFailClosed(unittest.TestCase):
    """direction 3 + the fail-closed rules."""

    def test_self_assign_foreign_project_rejected(self):
        """The actor IS the target here — target-user scoping cannot catch this,
        only the project-side check does."""
        with self.assertRaises(HTTPException) as ctx:
            _validate(ADMIN_A, ["projB"])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_actor_without_company_cannot_assign_anything(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate(ADMIN_NO_COMPANY, ["projA"])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_actor_without_company_may_still_clear(self):
        """An empty list grants nothing, so it short-circuits before the check."""
        self.assertEqual(_validate(ADMIN_NO_COMPANY, []), [])

    def test_non_list_payload_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate(ADMIN_A, "projA")
        self.assertEqual(ctx.exception.status_code, 400)


class PlatformOperatorBypass(unittest.TestCase):
    """direction 4: the one deliberate cross-company path."""

    def test_operator_may_assign_cross_company(self):
        self.assertEqual(_validate(OPERATOR, ["projA", "projB"]), ["projA", "projB"])

    def test_operator_bypass_is_flag_based_not_role_based(self):
        """`owner` is the self-serve signup role — it must NOT confer the bypass."""
        owner_not_operator = {"_id": "o2", "role": "owner", "company_id": "companyA",
                              "account_status": "approved"}
        with self.assertRaises(HTTPException) as ctx:
            _validate(owner_not_operator, ["projB"])
        self.assertEqual(ctx.exception.status_code, 403)


class BothVectorsCallTheValidator(unittest.TestCase):
    """Source pin. Both write sites must route through the shared validator —
    a new one added later without it silently reopens the hole."""

    @classmethod
    def setUpClass(cls):
        cls.src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8"
        )
        cls.tree = ast.parse(cls.src)

    def _func(self, name):
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                    and node.name == name:
                return node
        return None

    def test_assign_projects_route_validates(self):
        fn = self._func("assign_projects_to_user")
        self.assertIsNotNone(fn, "assign_projects_to_user not found")
        body = ast.unparse(fn)
        self.assertIn("validate_assignable_projects", body)
        self.assertIn("_same_company", body)

    def test_put_admin_user_validates(self):
        fn = self._func("update_admin_user")
        self.assertIsNotNone(fn, "update_admin_user not found")
        body = ast.unparse(fn)
        self.assertIn("validate_assignable_projects", body)

    def test_assigned_projects_still_in_allowed_fields(self):
        """If this ever drops out of the allow-list the PUT validation becomes
        dead code — that is fine, but the test should say so out loud."""
        fn = self._func("update_admin_user")
        self.assertIn("assigned_projects", ast.unparse(fn))

    def test_creation_paths_force_empty_list(self):
        """The Pydantic models accept assigned_projects from the body; every
        creation handler overwrites it with []. That one line is the only thing
        stopping injection at signup."""
        self.assertIn('user_dict["assigned_projects"] = []', self.src)
        # THE SECOND VECTOR WAS `create_subcontractor`, REMOVED 2026-09-04 with
        # the other four /admin/subcontractors handlers as zero-caller dead
        # code. Its line was `sub_dict["assigned_projects"] = []` and this test
        # pinned that literal, so deleting the handler deleted the subject and
        # the assertion failed about a vector that no longer exists.
        #
        # CONDITIONAL, NOT DELETED. An injection guard is worth keeping for a
        # handler that is gone only in the sense that it must come back WITH
        # the handler. Deleting the line outright is how a re-added endpoint
        # ships without it — and the models, SubcontractorCreate included, were
        # deliberately kept, so re-adding one is a plausible afternoon's work.
        #
        # ENUMERATED, NOT NAMED. Any creation handler that builds a `*_dict`
        # from a Pydantic body has to force the list; asking the module which
        # ones exist keeps this honest as handlers come and go, instead of
        # pinning today's two by hand.
        creators = [n for n in ("create_admin_user", "create_subcontractor",
                                "register_user", "create_worker")
                    if hasattr(S, n)]
        self.assertTrue(creators, "no creation handler found at all")
        if hasattr(S, "create_subcontractor"):
            self.assertIn('sub_dict["assigned_projects"] = []', self.src)


class GrantIsHonouredByRequireProjectAccess(unittest.TestCase):
    """The reason all of the above matters: require_project_access trusts the
    list. This pins that relationship so the coupling is visible in CI — if the
    branch is ever removed, this test is the breadcrumb explaining why the
    assignment guard existed."""

    def _access(self, project_id, user):
        import server

        async def _find_one(q, *a, **kw):
            return PROJECTS.get(q.get("_id"))

        db = MagicMock()
        db.projects.find_one = AsyncMock(side_effect=_find_one)
        with patch.object(server, "db", db):
            return asyncio.run(
                server.require_project_access(project_id=project_id, current_user=user)
            )

    def test_assignment_grants_cross_company_access(self):
        """A foreign entry DOES grant access — which is exactly why writing one
        has to be gated. require_project_access does not re-verify the project's
        company (defense-in-depth item, logged in followups)."""
        holder = {"_id": "uh", "role": "cp", "company_id": "companyC",
                  "assigned_projects": ["projA"], "account_status": "approved"}
        self.assertEqual(self._access("projA", holder)["_id"], "projA")

    def test_without_assignment_cross_company_is_denied(self):
        holder = {"_id": "uh", "role": "cp", "company_id": "companyC",
                  "assigned_projects": [], "account_status": "approved"}
        with self.assertRaises(HTTPException) as ctx:
            self._access("projA", holder)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
