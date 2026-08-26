"""A plan note belongs to a project, and only that project's people may touch it.

WHAT WAS OPEN. Five annotation routes, and only one of them was scoped:

    GET    /annotations/{project_id}/{path}   Depends(require_project_access)  OK
    POST   /annotations                       project_id from the BODY, unchecked
    PUT    /annotations/{id}/reply            NO CHECK OF ANY KIND
    PUT    /annotations/{id}/resolve          creator / recipient / ROLE
    DELETE /annotations/{id}                  creator / ROLE

`is_admin = user_role in ["admin", "owner"]` is a role test with no tenant in
it, so an admin of ANY company could resolve or soft-delete another company's
plan note. `reply` needed nothing beyond a valid token. And `create` took a
project_id from the request body and never checked it -- then stamped
company_id from the CALLER, so the row would carry his tenancy while pointing
at somebody else's project.

The annotation id was the only thing between a caller and another tenant's
document, and ids are not secrets.

THE FIX USES THE EXISTING RULE. _assert_project_access is what
require_project_access wraps; it is called directly because the project id
comes from the body or from the stored document, so FastAPI has no path
parameter to resolve a dependency from. That also subsumes the company check --
project_access_ok compares company on the PROJECT -- without adding another
`if company_id and ...`, the conditional shape that passes for a company-less
caller and is still open on 24 other routes.

    python backend/tests/test_annotation_authorization.py
"""

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

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

# ── Two tenants ─────────────────────────────────────────────────────────────
PROJ_A = {"_id": "projA", "id": "projA", "company_id": "companyA", "name": "588 Thomas"}

OWNER_A = {"_id": "u1", "id": "u1", "role": "cp", "company_id": "companyA",
           "account_status": "approved", "name": "Owner A"}
COLLEAGUE_A = {"_id": "u2", "id": "u2", "role": "cp", "company_id": "companyA",
               "account_status": "approved", "name": "Colleague A"}
ADMIN_A = {"_id": "u3", "id": "u3", "role": "admin", "company_id": "companyA",
           "account_status": "approved", "name": "Admin A"}

# THE ATTACKER, and he is an ADMIN -- of a different tenant. The old rule let
# `is_admin` decide, and it never asked which company he administered.
ADMIN_B = {"_id": "v1", "id": "v1", "role": "admin", "company_id": "companyB",
           "account_status": "approved", "name": "Admin B"}
USER_B = {"_id": "v2", "id": "v2", "role": "cp", "company_id": "companyB",
          "account_status": "approved", "name": "User B"}
# The DEFAULT state of every self-registration: server.py sets
# user_dict["company_id"] = None at /auth/register.
COMPANYLESS = {"_id": "w1", "id": "w1", "role": "cp", "company_id": None,
               "account_status": "approved", "name": "Fresh Signup"}

ANNOTATION = {
    "_id": "ann1", "id": "ann1",
    "project_id": "projA",
    "company_id": "companyA",
    "document_path": "/Projects/588/A-101.pdf",
    "created_by": "u1",
    "recipients": ["u2"],
    "thread": [],
    "resolved": False,
    "is_deleted": False,
}


def _db(annotation=None, project=PROJ_A):
    """Doubles for the two collections these routes touch."""
    state = {"updates": [], "inserts": []}

    async def ann_find_one(q, *a, **kw):
        return dict(annotation) if annotation else None

    async def ann_update_one(q, upd, *a, **kw):
        state["updates"].append(upd)
        r = MagicMock()
        r.matched_count = 1
        return r

    async def ann_insert_one(doc):
        state["inserts"].append(dict(doc))
        r = MagicMock()
        r.inserted_id = "newann"
        return r

    async def proj_find_one(q, *a, **kw):
        return dict(project) if project else None

    db = MagicMock()
    db.document_annotations.find_one = AsyncMock(side_effect=ann_find_one)
    db.document_annotations.update_one = AsyncMock(side_effect=ann_update_one)
    db.document_annotations.insert_one = AsyncMock(side_effect=ann_insert_one)
    db.projects.find_one = AsyncMock(side_effect=proj_find_one)
    db.users.find = MagicMock(return_value=MagicMock(
        to_list=AsyncMock(return_value=[])))
    return db, state


def _run(coro_factory, db):
    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()), \
         patch.object(server, "dispatch_notification", AsyncMock(), create=True):
        return asyncio.run(coro_factory())


def _reply(user, annotation=ANNOTATION, project=PROJ_A):
    db, state = _db(annotation, project)
    bg = MagicMock()
    bg.add_task = MagicMock()
    _run(lambda: server.add_annotation_reply(
        annotation_id="ann1", data={"message": "hi"},
        background_tasks=bg, current_user=user), db)
    return state


def _resolve(user, annotation=ANNOTATION, project=PROJ_A):
    db, state = _db(annotation, project)
    _run(lambda: server.resolve_annotation(
        annotation_id="ann1", current_user=user), db)
    return state


def _delete(user, annotation=ANNOTATION, project=PROJ_A):
    db, state = _db(annotation, project)
    _run(lambda: server.delete_annotation(
        annotation_id="ann1", current_user=user), db)
    return state


def _create(user, project_id="projA", project=PROJ_A):
    db, state = _db(None, project)
    bg = MagicMock()
    bg.add_task = MagicMock()
    _run(lambda: server.create_annotation(
        data={"project_id": project_id, "document_path": "/p/A-101.pdf",
              "comment": "note", "recipients": []},
        background_tasks=bg, current_user=user), db)
    return state


class ReplyIsScoped(unittest.TestCase):
    """It had NO check of any kind -- the only one of the five with none."""

    def test_a_cross_tenant_user_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _reply(USER_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_cross_tenant_ADMIN_is_refused(self):
        """Role is not tenancy."""
        with self.assertRaises(HTTPException) as c:
            _reply(ADMIN_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_company_less_signup_is_refused(self):
        """THE DEFAULT STATE. /auth/register sets company_id = None, so this is
        every fresh account until it onboards."""
        with self.assertRaises(HTTPException) as c:
            _reply(COMPANYLESS)
        self.assertEqual(c.exception.status_code, 403)

    def test_nothing_is_written_when_refused(self):
        try:
            state = _reply(USER_B)
        except HTTPException:
            return
        self.fail(f"the reply was written: {state}")

    def test_a_PROJECT_COLLEAGUE_may_still_reply(self):
        """NOT restricted to creator or recipient, deliberately. A thread is the
        collaborative half of a plan note -- the creator asks and someone else
        answers. Locking replies to the named parties would break the feature
        to close the hole."""
        state = _reply(COLLEAGUE_A)
        self.assertEqual(len(state["updates"]), 1)

    def test_the_creator_may_still_reply(self):
        self.assertEqual(len(_reply(OWNER_A)["updates"]), 1)


class ResolveIsScoped(unittest.TestCase):
    """It had creator / recipient / ROLE, and role has no tenant in it."""

    def test_a_cross_tenant_ADMIN_is_refused(self):
        """THE REPORTED HOLE. `is_admin = user_role in ["admin","owner"]` never
        asked WHICH company he administered."""
        with self.assertRaises(HTTPException) as c:
            _resolve(ADMIN_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_cross_tenant_user_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _resolve(USER_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_nothing_is_written_when_refused(self):
        try:
            state = _resolve(ADMIN_B)
        except HTTPException:
            return
        self.fail(f"the resolve was written: {state}")

    def test_the_creator_may_still_resolve(self):
        self.assertEqual(len(_resolve(OWNER_A)["updates"]), 1)

    def test_a_RECIPIENT_may_still_resolve(self):
        self.assertEqual(len(_resolve(COLLEAGUE_A)["updates"]), 1)

    def test_a_SAME_COMPANY_admin_may_still_resolve(self):
        """The admin branch is not removed -- it is scoped."""
        self.assertEqual(len(_resolve(ADMIN_A)["updates"]), 1)

    def test_a_same_company_bystander_is_still_refused_by_OWNERSHIP(self):
        """Project access is necessary, not sufficient. The ownership rule
        still decides which of those people may resolve."""
        bystander = {**COLLEAGUE_A, "_id": "u9", "id": "u9"}
        with self.assertRaises(HTTPException) as c:
            _resolve(bystander)
        self.assertEqual(c.exception.status_code, 403)


class DeleteIsScoped(unittest.TestCase):
    """It had creator / ROLE."""

    def test_a_cross_tenant_ADMIN_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _delete(ADMIN_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_nothing_is_written_when_refused(self):
        try:
            state = _delete(ADMIN_B)
        except HTTPException:
            return
        self.fail(f"the delete was written: {state}")

    def test_the_creator_may_still_delete(self):
        self.assertEqual(len(_delete(OWNER_A)["updates"]), 1)

    def test_a_SAME_COMPANY_admin_may_still_delete(self):
        self.assertEqual(len(_delete(ADMIN_A)["updates"]), 1)

    def test_a_recipient_may_NOT_delete(self):
        """Unchanged: resolve admits recipients, delete does not. Closing the
        tenancy hole must not widen the ownership rule."""
        with self.assertRaises(HTTPException) as c:
            _delete(COLLEAGUE_A)
        self.assertEqual(c.exception.status_code, 403)


class CreateChecksTheProjectItNames(unittest.TestCase):
    """project_id came from the BODY and was never checked."""

    def test_naming_another_tenants_project_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _create(USER_B, project_id="projA")
        self.assertEqual(c.exception.status_code, 403)

    def test_a_cross_tenant_ADMIN_is_refused_too(self):
        with self.assertRaises(HTTPException) as c:
            _create(ADMIN_B, project_id="projA")
        self.assertEqual(c.exception.status_code, 403)

    def test_a_company_less_signup_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _create(COMPANYLESS, project_id="projA")
        self.assertEqual(c.exception.status_code, 403)

    def test_nothing_is_inserted_when_refused(self):
        """The row would have carried the CALLER's company_id while pointing at
        someone else's project -- a document belonging to two tenants at once."""
        try:
            state = _create(USER_B, project_id="projA")
        except HTTPException:
            return
        self.fail(f"the annotation was inserted: {state}")

    def test_an_unknown_project_is_404_not_a_silent_insert(self):
        with self.assertRaises(HTTPException) as c:
            _create(OWNER_A, project_id="nope", project=None)
        self.assertEqual(c.exception.status_code, 404)

    def test_the_owner_may_still_create_on_his_own_project(self):
        state = _create(OWNER_A, project_id="projA")
        self.assertEqual(len(state["inserts"]), 1)
        self.assertEqual(state["inserts"][0]["project_id"], "projA")

    def test_project_id_is_still_required(self):
        """Unchanged 400, and it must fire BEFORE the access check so a missing
        id is not reported as a permissions problem."""
        with self.assertRaises(HTTPException) as c:
            _create(OWNER_A, project_id="")
        self.assertEqual(c.exception.status_code, 400)


class TheRuleIsTheEXISTINGOne(unittest.TestCase):
    """Not a hand-rolled check. The conditional company_id shape is what is
    still open on 24 other routes; this must not add a 25th."""

    SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8")

    def _region(self):
        i = self.SRC.index("async def _annotation_for_user")
        return self.SRC[i:self.SRC.index("# ==================== PERMIT RENEWAL", i)]

    def test_the_helper_uses_assert_project_access(self):
        self.assertIn("await _assert_project_access(project_id, current_user)",
                      self._region())

    def test_no_conditional_company_id_check_was_added(self):
        """The shape that passes for a company-less caller."""
        import re
        self.assertIsNone(
            re.search(r'if\s+\w*company_id\s+and\s+.*\.get\("company_id"\)\s*!=',
                      self._region()))

    def test_all_three_id_routes_go_through_one_helper(self):
        region = self._region()
        self.assertEqual(region.count("await _annotation_for_user("), 3)

    def test_a_projectless_annotation_fails_CLOSED(self):
        """A legacy row that cannot be scoped cannot be acted on. Create has
        required project_id for as long as this endpoint existed; such a row
        needs a migration, not an exception."""
        orphan = {**ANNOTATION, "project_id": None}
        with self.assertRaises(HTTPException) as c:
            _resolve(OWNER_A, annotation=orphan)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_missing_annotation_is_still_404(self):
        with self.assertRaises(HTTPException) as c:
            _resolve(OWNER_A, annotation=None)
        self.assertEqual(c.exception.status_code, 404)

    def test_the_GET_route_still_carries_its_dependency(self):
        """Unchanged, and pinned: it was the one route that was already right."""
        for r in server.app.routes:
            if getattr(r, "path", "") == "/api/annotations/{project_id}/{document_path:path}":
                deps = str(getattr(r, "dependant", ""))
                self.assertIn("require_project_access",
                              deps + str(r.endpoint.__annotations__))
                return
        self.fail("the GET annotations route disappeared")


if __name__ == "__main__":
    unittest.main(verbosity=2)
