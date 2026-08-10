"""Company A cannot create, match, or overwrite company B's logbook.

THE DEFECT. POST /logbooks took its project id from the BODY and checked, for
every role but `cp`, that the project EXISTED. Nothing compared the project's
company_id to the caller's. The dedupe query underneath had no company_id
either. So a caller holding another company's project id did not merely create
a stray log — the dedupe MATCHED that company's existing unlocked row and
`$set` over it: their content replaced, the document still labelled with their
company_id, still carrying their instance_seq. Silent destruction of another
company's filed compliance record, with no new document to notice.

Found while adding coverage for instance_seq, which is how it presented: the
new filing was not numbered 2, because there was no new filing.

THE READ GUARD IS NOT THE WRITE GUARD. GET /logbooks/{id} was hardened
separately and authorizes per project. That did nothing for this path, and
these tests drive the WRITE — the `$set` branch specifically, asserting the
victim document byte-for-byte, not merely that the request was refused.
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
from server import LogbookCreate  # noqa: E402

A_PROJECT = "6a5f63bc147407d3261df2c7"   # belongs to company A
DATE = "2026-07-29"
DAILY = "daily_jobsite"


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


class _Coll:
    def __init__(self):
        self.docs = []
        self._n = 0

    async def find_one(self, query, sort=None):
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))

    async def insert_one(self, doc):
        self._n += 1
        doc = dict(doc)
        doc["_id"] = doc.get("_id") or f"oid_{self._n}"
        self.docs.append(doc)
        return _Result(doc["_id"])

    async def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _match(d, flt):
                d.update(update.get("$set", {}))
                return


class _DB:
    def __init__(self):
        self.logbooks = _Coll()
        self.projects = _Coll()


async def _noop(*a, **k):
    return None


def _payload(project_id=A_PROJECT, log_type=DAILY, status="draft"):
    return LogbookCreate(
        project_id=project_id, log_type=log_type, date=DATE,
        data={"note": "written by the intruder"},
        cp_signature={"image": "x"} if status == "submitted" else None,
        cp_name="Someone" if status == "submitted" else None,
        status=status,
    )


def _victim_row():
    """Company A's own unlocked daily log, as create_logbook writes one."""
    return {
        "_id": "A_row", "project_id": A_PROJECT, "project_name": "588 Boyland",
        "company_id": "coA", "log_type": DAILY, "date": DATE,
        "data": {"note": "company A's real record"},
        "status": "draft", "is_locked": False, "is_deleted": False,
        "is_amendment": False, "instance_seq": 1, "created_by": "a_user",
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

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]
        server._enhance_logbook_photos = self._orig["enh"]
        server.audit_log = self._orig["audit"]
        self.loop.close()

    def create(self, user, payload=None):
        return self.loop.run_until_complete(
            server.create_logbook(data=payload or _payload(), current_user=user),
        )

    def refused(self, user, payload=None):
        with self.assertRaises(HTTPException) as caught:
            self.create(user, payload)
        return caught.exception


def _user(role, company, **extra):
    u = {"_id": f"{role}_{company}", "id": f"{role}_{company}", "role": role,
         "company_id": company, "full_name": role.title(),
         "account_status": "approved"}
    u.update(extra)
    return u


class TheVictimsRecordSurvives(Base):
    """THE test. Not 'the request was refused' — the DOCUMENT is untouched."""

    def setUp(self):
        super().setUp()
        self.db.logbooks.docs.append(_victim_row())
        self.before = copy.deepcopy(self.db.logbooks.docs[0])

    def test_a_foreign_admin_cannot_overwrite_it(self):
        self.refused(_user("admin", "coB"))
        self.assertEqual(self.db.logbooks.docs[0], self.before,
                         "company A's record was modified")

    def test_the_document_is_byte_identical_field_by_field(self):
        """Spelled out, because `$set` replaces only the fields it names — an
        assertion on one field would pass while the rest were rewritten."""
        self.refused(_user("owner", "coB"))
        after = self.db.logbooks.docs[0]
        for field in ("data", "status", "instance_seq", "company_id",
                      "created_by", "is_locked"):
            self.assertEqual(after[field], self.before[field], field)

    def test_no_new_row_is_inserted_either(self):
        self.refused(_user("admin", "coB"))
        self.assertEqual(len(self.db.logbooks.docs), 1,
                         "a refused create must write nothing at all")

    def test_the_refusal_is_403_and_names_no_other_tenant(self):
        e = self.refused(_user("admin", "coB"))
        self.assertEqual(e.status_code, 403)
        for leak in ("coA", "588 Boyland"):
            self.assertNotIn(leak, str(e.detail),
                             "the refusal confirmed another tenant's data")

    def test_company_A_ITSELF_still_edits_its_own_row(self):
        """The control. Without it every assertion above would also pass on a
        server that refused everyone."""
        self.create(_user("admin", "coA"))
        self.assertEqual(len(self.db.logbooks.docs), 1, "upserted, not duplicated")
        self.assertEqual(self.db.logbooks.docs[0]["data"],
                         {"note": "written by the intruder"},
                         "company A's own edit must still land")


class EveryRoleThatReachedItIsGated(Base):
    """`cp` was gated on assigned_projects and is unchanged. Every other role
    reached the dedupe on project EXISTENCE alone."""

    ROLES = ("admin", "owner", "assistant", "cp", "user", "presentation")

    def test_no_role_of_another_company_gets_through(self):
        for role in self.ROLES:
            with self.subTest(role=role):
                self.db.logbooks.docs[:] = [_victim_row()]
                e = self.refused(_user(role, "coB"))
                self.assertEqual(e.status_code, 403)
                self.assertEqual(len(self.db.logbooks.docs), 1)

    def test_a_caller_with_NO_company_is_refused(self):
        """GET /projects returns EVERY company's projects when the caller has
        no company_id (`if company_id:` — the filter is skipped), so this is
        the caller most likely to be holding a foreign id. Absence is not
        authorization."""
        self.db.logbooks.docs.append(_victim_row())
        e = self.refused(_user("admin", None))
        self.assertEqual(e.status_code, 403)
        self.assertEqual(len(self.db.logbooks.docs), 1)

    def test_an_empty_string_company_is_refused_too(self):
        self.db.logbooks.docs.append(_victim_row())
        self.refused(_user("admin", ""))
        self.assertEqual(len(self.db.logbooks.docs), 1)

    def test_TWO_absences_do_not_match_each_other(self):
        """ABSENCE IS NOT AUTHORIZATION, and this is the case that proves the
        `user_company and` guard is load-bearing rather than decorative: a
        project with no company_id and a caller with no company_id both
        normalise to "", and a bare equality check would authorize the pair.

        Caught by mutation: dropping that guard passed every other test here."""
        self.db.projects.docs[:] = [{
            "_id": A_PROJECT, "name": "Orphan", "is_deleted": False,
        }]
        # BOTH empty forms. `None` stringifies to "None" and would fail the
        # comparison by accident; only "" actually collides with an absent
        # project company, so only "" proves the guard is doing the work.
        for empty in (None, "", "   "):
            with self.subTest(company=repr(empty)):
                self.db.logbooks.docs[:] = [{**_victim_row(), "company_id": empty}]
                before = copy.deepcopy(self.db.logbooks.docs[0])
                e = self.refused(_user("admin", empty))
                self.assertEqual(e.status_code, 403)
                self.assertEqual(self.db.logbooks.docs[0], before)
                self.assertEqual(len(self.db.logbooks.docs), 1)


class TheThreeLegitimatePathsStillWork(Base):
    """A tenant gate that breaks a real flow is not a fix."""

    def test_same_company_admin(self):
        self.create(_user("admin", "coA"))
        self.assertEqual(len(self.db.logbooks.docs), 1)

    def test_an_ASSIGNED_user_of_another_company(self):
        """Branch 3 of the shared rule. validate_assignable_projects makes
        this same-company at every write site today, but rows written before
        it exist — the dangling assignment found on 2@2.com is one — so the
        branch stays and is asserted."""
        self.create(_user("cp", "coB", assigned_projects=[A_PROJECT]))
        self.assertEqual(len(self.db.logbooks.docs), 1)

    def test_a_cp_of_the_right_company_but_NOT_assigned_is_still_refused(self):
        """The CP gate is stricter than the company branch and runs first.
        It must not be loosened by adding the company check behind it."""
        e = self.refused(_user("cp", "coA", assigned_projects=[]))
        self.assertEqual(e.status_code, 403)
        self.assertIn("assigned", str(e.detail).lower())

    def test_the_site_device_for_THIS_project(self):
        self.create({"_id": "dev1", "id": "dev1", "role": "site_device",
                     "site_mode": True, "project_id": A_PROJECT,
                     "company_id": "coA"})
        self.assertEqual(len(self.db.logbooks.docs), 1)

    def test_a_site_device_for_ANOTHER_project_is_refused(self):
        e = self.refused({"_id": "dev2", "id": "dev2", "role": "site_device",
                          "site_mode": True, "project_id": "someone_elses",
                          "company_id": "coA"})
        self.assertEqual(e.status_code, 403,
                         "a kiosk may act on the project it was provisioned for")

    def test_a_project_marked_for_deletion_still_accepts_its_own_companys_log(self):
        """DELIBERATE. _assert_project_access applies ACTIVE_PROJECT_FILTER,
        which excludes marked_for_deletion; this path does not adopt it. An
        offline draft syncing after an admin marked the project must not 404 —
        that is a CP losing a filed day to an admin action taken while he was
        out of signal. Authorization was what was missing, not existence."""
        self.db.projects.docs[0]["marked_for_deletion"] = True
        self.create(_user("admin", "coA"))
        self.assertEqual(len(self.db.logbooks.docs), 1)


class TheDedupeCannotCrossTenants(Base):
    """Defence in depth: even reached with a foreign id, the query must not
    match. Asserted by calling the dedupe's own shape, since the gate above
    now prevents the endpoint from getting here."""

    def test_the_dedupe_filter_carries_company_id(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("    dedupe_filter = {")
        block = src[i:src.index("    }", i)]
        self.assertIn('"company_id": company_id', block,
                      "the dedupe can match another tenant's row")
        self.assertNotIn("data.company_id", block,
                         "scoped from auth, never from the request body")

    def test_it_is_taken_from_auth_and_not_the_request(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        head = src[src.index("async def create_logbook"):src.index("    dedupe_filter = {")]
        self.assertIn("company_id = get_user_company_id(current_user)", head)

    def test_a_row_of_another_company_does_not_match_the_filter(self):
        """The filter's semantics, executed rather than read."""
        flt = {"project_id": A_PROJECT, "company_id": "coA", "log_type": DAILY,
               "date": DATE, "is_deleted": {"$ne": True},
               "is_amendment": {"$ne": True}}
        self.assertTrue(_match(_victim_row(), flt))
        foreign = {**_victim_row(), "company_id": "coB"}
        self.assertFalse(_match(foreign, flt), "matched across tenants")
        legacy = {k: v for k, v in _victim_row().items() if k != "company_id"}
        self.assertFalse(_match(legacy, flt),
                         "a row with NO company_id no longer matches")

    def test_no_writer_in_this_repo_has_ever_omitted_company_id(self):
        """Which is what makes the assertion above safe. A row without the
        field would now be edited into a SECOND document instead of updated —
        so the claim that no such row exists is asserted, not assumed.

        Both writers are checked. Rows written outside this codebase, or
        before its first commit, cannot be checked from here: that needs a
        production read, and this project does no production DB operations."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        create_fn = src[src.index("async def create_logbook"):]
        create_doc = create_fn[create_fn.index("    doc = {"):]
        self.assertIn('"company_id": company_id,', create_doc[:800],
                      "create_logbook stopped stamping company_id")
        gate = src[src.index("async def register_and_checkin"):]
        gate_insert = gate[gate.index("await db.logbooks.insert_one({"):]
        self.assertIn('"company_id": company_id,', gate_insert[:900],
                      "the gate's orientation insert stopped stamping company_id")


class TheSharedRuleIsUnchangedForItsOtherCallers(unittest.TestCase):
    """project_access_ok was EXTRACTED from _assert_project_access, which has
    57 call sites. The extraction must be a no-op for all of them."""

    SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_assert_project_access_still_applies_the_active_filter(self):
        body = self.SRC[self.SRC.index("async def _assert_project_access"):]
        body = body[:body.index("async def require_project_access")]
        self.assertIn("**ACTIVE_PROJECT_FILTER", body)
        self.assertIn('status_code=404', body)
        self.assertIn("project_access_ok(project, project_id, current_user)", body)

    def test_the_three_branches_survived_the_extraction(self):
        body = self.SRC[self.SRC.index("def project_access_ok"):]
        body = body[:body.index("async def _assert_project_access")]
        self.assertIn("site_mode", body)
        self.assertIn("get_user_company_id(current_user)", body)
        self.assertIn("assigned_projects", body)

    def test_no_platform_operator_branch_was_introduced(self):
        body = self.SRC[self.SRC.index("def project_access_ok"):]
        body = body[:body.index("async def _assert_project_access")]
        code = "\n".join(l for l in body.splitlines()
                         if not l.strip().startswith("#"))
        self.assertNotIn("is_platform_operator(", code,
                         "the operator appears in no logbook flow; this adds none")


if __name__ == "__main__":
    unittest.main()
