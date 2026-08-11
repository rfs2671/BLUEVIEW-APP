"""The four logbook endpoints that take a logbook_id, and the list that leaked
the ids in the first place.

THE GAP. #110 closed create_logbook, which takes a PROJECT id in the body.
update, finalize and amend take a LOGBOOK id in the path, and each gated `cp`
on assigned_projects and every other role on NOTHING — not the company, not
the project. Any authenticated non-CP holding a logbook id could edit, freeze
or amend another company's filed compliance record. delete_logbook was worse
by design: "admin/owner can delete any" meant any COMPANY'S.

WHERE THE IDS CAME FROM. GET /projects applied its tenant filter
conditionally — `if company_id:` — so a caller with no company_id received
every company's projects. That is the DEFAULT state of a new account: register
sets company_id = None outright and a company is attached later by
POST /onboarding/company.

THE IDIOM IS get_logbook's, as it must be for an id that names a document:
load the logbook, load ITS project, then authorize with
user_can_act_on_project. Not create_logbook's project_access_ok, which also
admits a site device — no screen under frontend/app/site writes a logbook.

Every test below asserts the victim DOCUMENT, not that a request was refused.
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

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from server import LogbookUpdate  # noqa: E402

A_PROJECT = "6a5f63bc147407d3261df2c7"
B_PROJECT = "6a5f63bc147407d3261df2c8"
DATE = "2026-07-29"


def _get(doc, key):
    if "." not in key:
        return doc.get(key)
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict) and "$ne" in v:
            if _get(doc, k) == v["$ne"]:
                return False
            continue
        if _get(doc, k) != v:
            return False
    return True


class _Result:
    def __init__(self, _id):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _Coll:
    def __init__(self):
        self.docs = []
        self._n = 0

    async def find_one(self, query, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))

    async def insert_one(self, doc):
        self._n += 1
        doc = dict(doc)
        doc["_id"] = doc.get("_id") or f"new_{self._n}"
        self.docs.append(doc)
        return _Result(doc["_id"])

    async def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _match(d, flt):
                d.update(update.get("$set", {}))
                return _Result(d["_id"])
        return _Result(None)


class _DB:
    def __init__(self):
        self.logbooks = _Coll()
        self.projects = _Coll()


async def _noop(*a, **k):
    return None


def _user(role, company, **extra):
    u = {"_id": f"{role}_{company}", "id": f"{role}_{company}", "role": role,
         "company_id": company, "email": f"{role}@{company}.test",
         "full_name": role.title(), "account_status": "approved"}
    u.update(extra)
    return u


def _log(_id="A_log", company="coA", project=A_PROJECT, locked=False,
         created_by="a_user"):
    return {
        "_id": _id, "project_id": project, "project_name": "588 Boyland",
        "company_id": company, "log_type": "daily_jobsite", "date": DATE,
        "data": {"note": "company A's real record"}, "status": "draft",
        "is_locked": locked, "is_deleted": False, "is_amendment": False,
        "instance_seq": 1, "created_by": created_by,
        "cp_signature": {"image": "x"}, "cp_name": "Carl CP",
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.projects.docs.append({
            "_id": A_PROJECT, "name": "588 Boyland", "company_id": "coA",
            "is_deleted": False, "marked_for_deletion": False,
        })
        self._orig = {
            "db": server.db, "tqid": server.to_query_id,
            "enh": server._enhance_logbook_photos, "audit": server.audit_log,
        }
        server.db = self.db
        server.to_query_id = lambda x: x
        server._enhance_logbook_photos = _noop
        server.audit_log = _noop
        self.db.logbooks.docs.append(_log())
        self.before = copy.deepcopy(self.db.logbooks.docs[0])

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]
        server._enhance_logbook_photos = self._orig["enh"]
        server.audit_log = self._orig["audit"]
        self.loop.close()

    def run_(self, coro):
        return self.loop.run_until_complete(coro)

    # The four writes, each called exactly as its route would.
    def do_update(self, user):
        return self.run_(server.update_logbook(
            logbook_id="A_log",
            data=LogbookUpdate(data={"note": "overwritten"}, status="draft"),
            current_user=user))

    def do_finalize(self, user):
        return self.run_(server.finalize_logbook(logbook_id="A_log", current_user=user))

    def do_amend(self, user):
        return self.run_(server.amend_logbook(
            logbook_id="A_log", data={"reason": "because"}, current_user=user))

    def do_delete(self, user):
        return self.run_(server.delete_logbook(logbook_id="A_log", current_user=user))

    def all_four(self):
        return (("update", self.do_update), ("finalize", self.do_finalize),
                ("amend", self.do_amend), ("delete", self.do_delete))

    def refused(self, fn, user):
        with self.assertRaises(HTTPException) as c:
            fn(user)
        return c.exception

    def assert_untouched(self):
        self.assertEqual(len(self.db.logbooks.docs), 1,
                         "a refused write must not insert an amendment either")
        after = self.db.logbooks.docs[0]
        for field in ("data", "status", "is_locked", "is_deleted",
                      "company_id", "instance_seq", "created_by"):
            self.assertEqual(after[field], self.before[field], field)
        self.assertEqual(after, self.before)


class AForeignCallerTouchesNothing(Base):
    """THE test, four times over. The DOCUMENT, field by field."""

    def test_no_foreign_role_can_write(self):
        for name, fn in self.all_four():
            for role in ("admin", "owner", "cp", "user"):
                with self.subTest(endpoint=name, role=role):
                    self.db.logbooks.docs[:] = [copy.deepcopy(self.before)]
                    e = self.refused(fn, _user(role, "coB"))
                    self.assertEqual(e.status_code, 403)
                    self.assert_untouched()

    def test_delete_no_longer_lets_ANY_admin_delete_ANY_companys_log(self):
        """The one that was worst by design: `admin/owner can delete any`
        meant any company's. It now means any on a project they can act on."""
        self.refused(self.do_delete, _user("admin", "coB"))
        self.assertFalse(self.db.logbooks.docs[0]["is_deleted"])

    def test_finalize_refuses_BEFORE_its_idempotent_early_return(self):
        """A locked log returns itself instead of erroring. Ordering the gate
        after that would hand an outsider another company's document and tell
        them it is already finalized."""
        self.db.logbooks.docs[:] = [_log(locked=True)]
        e = self.refused(self.do_finalize, _user("admin", "coB"))
        self.assertEqual(e.status_code, 403)

    def test_the_refusal_names_no_other_tenant(self):
        for name, fn in self.all_four():
            with self.subTest(endpoint=name):
                self.db.logbooks.docs[:] = [copy.deepcopy(self.before)]
                e = self.refused(fn, _user("admin", "coB"))
                for leak in ("coA", "588 Boyland", "company A's real record"):
                    self.assertNotIn(leak, str(e.detail), name)

    def test_a_missing_project_is_refused_rather_than_defaulting_open(self):
        """A logbook whose project row is gone must not become writable by
        anyone. Fails closed."""
        self.db.projects.docs[:] = []
        for name, fn in self.all_four():
            with self.subTest(endpoint=name):
                self.db.logbooks.docs[:] = [copy.deepcopy(self.before)]
                self.refused(fn, _user("admin", "coA"))
                self.assert_untouched()


class TheLegitimateWritesStillWork(Base):
    """The control. Without these, every assertion above would also pass on a
    server that refused everyone."""

    def test_a_same_company_admin_can_still_update(self):
        self.do_update(_user("admin", "coA"))
        self.assertEqual(self.db.logbooks.docs[0]["data"], {"note": "overwritten"})

    def test_an_assigned_cp_can_still_update(self):
        self.do_update(_user("cp", "coA", assigned_projects=[A_PROJECT]))
        self.assertEqual(self.db.logbooks.docs[0]["data"], {"note": "overwritten"})

    def test_an_assigned_cp_of_ANOTHER_company_can_still_update(self):
        """Branch 2 of user_can_act_on_project. Assignments are validated
        same-company at every write site now, but rows predating that exist."""
        self.do_update(_user("cp", "coB", assigned_projects=[A_PROJECT]))
        self.assertEqual(self.db.logbooks.docs[0]["data"], {"note": "overwritten"})

    def test_a_cp_of_the_right_company_but_NOT_assigned_is_refused(self):
        e = self.refused(self.do_update, _user("cp", "coA", assigned_projects=[]))
        self.assertEqual(e.status_code, 403)
        self.assert_untouched()

    def test_a_same_company_admin_can_still_finalize(self):
        self.do_finalize(_user("admin", "coA"))
        self.assertTrue(self.db.logbooks.docs[0]["is_locked"])

    def test_a_same_company_admin_can_still_amend(self):
        self.do_amend(_user("admin", "coA"))
        self.assertEqual(len(self.db.logbooks.docs), 2, "the amendment child was created")
        self.assertTrue(self.db.logbooks.docs[1].get("is_amendment"))

    def test_a_same_company_admin_can_still_delete(self):
        self.do_delete(_user("admin", "coA"))
        self.assertTrue(self.db.logbooks.docs[0]["is_deleted"])

    def test_the_author_can_still_delete_their_own(self):
        """The created_by rule is unchanged — the gate narrows WHOSE projects
        are reachable, it does not replace who may delete what within one."""
        self.db.logbooks.docs[:] = [_log(created_by="cp_coA")]
        self.do_delete(_user("cp", "coA", assigned_projects=[A_PROJECT], _id="cp_coA"))
        self.assertTrue(self.db.logbooks.docs[0]["is_deleted"])

    def test_a_non_author_non_admin_still_cannot_delete_within_the_project(self):
        e = self.refused(
            self.do_delete, _user("cp", "coA", assigned_projects=[A_PROJECT]))
        self.assertEqual(e.status_code, 403)
        self.assertFalse(self.db.logbooks.docs[0]["is_deleted"])


class AllFourGoThroughTheOneGuard(unittest.TestCase):
    SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_one_definition_and_four_call_sites(self):
        self.assertEqual(self.SRC.count("_authorize_logbook_write("), 5)

    def test_none_of_them_kept_a_bare_unauthorized_fetch(self):
        """The exact shape that was there before: load the doc, check nothing."""
        for fn in ("update_logbook", "finalize_logbook", "amend_logbook",
                   "delete_logbook"):
            body = self.SRC[self.SRC.index(f"async def {fn}("):]
            body = body[:2000]
            with self.subTest(endpoint=fn):
                self.assertIn("_authorize_logbook_write(logbook_id, current_user)", body)

    def test_it_uses_get_logbooks_guard_not_create_logbooks(self):
        body = self.SRC[self.SRC.index("async def _authorize_logbook_write"):]
        body = body[:body.index("async def update_logbook")]
        code = "\n".join(l for l in body.splitlines()
                         if not l.strip().startswith("#") and '"""' not in l)
        self.assertIn("user_can_act_on_project(project, project_id, current_user)", code)
        self.assertNotIn("project_access_ok(", code,
                         "a site device has no logbook write to lose")


class TheProjectListNoLongerLeaksIds(unittest.TestCase):
    """Where a foreign logbook's project id came from."""

    SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def _query_block(self):
        i = self.SRC.index("async def get_projects(")
        return self.SRC[i:self.SRC.index("result = await paginated_query", i)]

    def test_a_caller_with_no_company_no_longer_matches_everything(self):
        block = self._query_block()
        self.assertIn('query["_id"] = None', block,
                      "the tenant filter is still skipped for a company-less caller")

    def test_the_platform_operator_keeps_the_cross_company_view(self):
        block = self._query_block()
        self.assertIn("is_platform_operator(current_user)", block)

    def test_it_is_never_inferred_from_role(self):
        block = self._query_block()
        self.assertNotIn('get("role") == "owner"', block,
                         'role "owner" is what every self-serve signup receives')

    def test_registration_really_does_leave_company_id_None(self):
        """The premise of all of the above, asserted rather than assumed: this
        is why the company-less caller is the DEFAULT state, not a rare one."""
        reg = self.SRC[self.SRC.index("async def register("):]
        reg = reg[:reg.index("result = await db.users.insert_one(user_dict)")]
        self.assertIn('user_dict["company_id"] = None', reg)

    def test_a_pending_user_still_has_something_to_look_at(self):
        """Gating the list must not leave a pre-onboarding user with nothing —
        /demo/project is what they are meant to see, and it is untouched."""
        self.assertIn('@api_router.get("/demo/project")', self.SRC)


if __name__ == "__main__":
    unittest.main()
