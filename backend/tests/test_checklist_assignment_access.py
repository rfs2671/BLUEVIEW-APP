"""Tenant isolation for the two {assignment_id} routes.

Both took the assignment id from the path and answered it with no membership,
project or tenancy check:

  GET /checklists/assignments/{id}           read another tenant's checklist
  PUT /checklists/assignments/{id}/complete  file a completion against it

Same class as the batch-1 read holes and the 25 company_id write sites — the
path parameter went straight into the query.

Pinned in BOTH directions, because a guard that 403s everyone is as broken as
one that 403s nobody. The open cases here are not padding: the admin who was
never assigned, the cross-company contractor who was, and the CP holding the
project through assigned_projects are the three people the feature exists for,
and a membership-only guard would refuse two of them.

READ is "named on it, or project access". WRITE is "named on it", full stop —
so the admin who may read an assignment may NOT file a completion against it.
Those two claims are tested against each other, route by route.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402


PROJECT_A = {"_id": "projA", "name": "857 Prescott", "company_id": "companyA"}

# Company A's own people.
CP_NAMED = {"_id": "cp1", "id": "cp1", "role": "cp", "company_id": "companyA",
            "name": "Cara CP", "assigned_projects": []}
ADMIN_A = {"_id": "ad1", "id": "ad1", "role": "admin", "company_id": "companyA",
           "name": "Ada Admin", "assigned_projects": []}
WORKER_A = {"_id": "wk1", "id": "wk1", "role": "worker", "company_id": "companyA",
            "name": "Will Worker", "assigned_projects": []}

# Cross-company contractor NAMED on the assignment.
SUB_NAMED = {"_id": "sub1", "id": "sub1", "role": "cp", "company_id": "companyC",
             "name": "Sam Sub", "assigned_projects": []}
# Cross-company CP holding the PROJECT through assigned_projects, not named.
SUB_ON_PROJECT = {"_id": "sub2", "id": "sub2", "role": "cp", "company_id": "companyC",
                  "name": "Pat Project", "assigned_projects": ["projA"]}

# The outsiders.
OTHER_ADMIN = {"_id": "ad2", "id": "ad2", "role": "admin", "company_id": "companyB",
               "name": "Bob B", "assigned_projects": []}
# Self-serve signup: /auth/register sets company_id = None. The DEFAULT state,
# and the short-circuit that made the original holes reachable platform-wide.
NO_COMPANY = {"_id": "new1", "id": "new1", "role": "admin", "company_id": None,
              "name": "Nora New", "assigned_projects": []}
# Kiosk provisioned for THIS VERY PROJECT — the case that must still be refused.
DEVICE_A = {"_id": "dev1", "id": "dev1", "role": "site_device", "site_mode": True,
            "project_id": "projA", "company_id": "companyA"}

CHECKLIST = {
    "_id": "cl1", "title": "Fall Protection — Daily", "description": "At height.",
    "items": [{"id": "i1", "text": "Harness inspected", "order": 0}],
    "company_id": "companyA", "is_deleted": False,
}

ASSIGNMENT = {
    "_id": "as1", "checklist_id": "cl1", "project_id": "projA",
    "project_name": "857 Prescott", "assigned_user_ids": ["cp1", "sub1"],
    "assigned_users": [{"id": "cp1", "name": "Cara CP"}, {"id": "sub1", "name": "Sam Sub"}],
    "company_id": "companyA", "is_deleted": False,
}


def _match(doc, query):
    for key, cond in (query or {}).items():
        value = doc.get(key)
        if isinstance(cond, dict):
            if "$ne" in cond and value == cond["$ne"]:
                return False
            if "$in" in cond and value not in cond["$in"]:
                return False
        elif isinstance(value, list):
            if cond not in value:
                return False
        elif value != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _Coll:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
        self.updates = []
        self.inserted = []

    def find(self, query=None, *a, **k):
        return _Cursor([dict(d) for d in self.docs if _match(d, query)])

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _match(d, query):
                return dict(d)
        return None

    async def update_one(self, query, update, *a, **k):
        self.updates.append((query, update))

        class _R:
            matched_count = 1
        return _R()

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))

        class _R:
            inserted_id = "cmp_new"
        return _R()


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())


def _db(assignments=None):
    return _Db(
        projects=_Coll([PROJECT_A]),
        checklists=_Coll([CHECKLIST]),
        checklist_assignments=_Coll(
            assignments if assignments is not None else [ASSIGNMENT]),
        checklist_completions=_Coll([]),
    )


def _run(db, factory):
    with patch.object(server, "db", db), patch.object(server, "to_query_id", lambda v: v):
        return asyncio.run(factory())


def _read(user, db=None, assignment_id="as1"):
    return _run(db or _db(), lambda: server.get_assignment_details(assignment_id, user))


def _write(user, db=None, assignment_id="as1"):
    payload = server.ChecklistCompletionUpdate(
        item_completions={"i1": {"checked": True, "note": "", "timestamp": "2026-08-28T00:00:00Z"}},
    )
    return _run(db or _db(), lambda: server.complete_checklist(assignment_id, payload, user))


def _status(fn, *a, **k):
    try:
        fn(*a, **k)
    except HTTPException as exc:
        return exc.status_code
    return 200


# ---------------------------------------------------------------- REFUSED ---

class TestReadIsRefused(unittest.TestCase):
    def test_another_companys_admin(self):
        self.assertEqual(_status(_read, OTHER_ADMIN), 403)

    def test_a_caller_with_no_company_at_all(self):
        """The self-serve default. company_id None must not be a wildcard."""
        self.assertEqual(_status(_read, NO_COMPANY), 403)

    def test_a_site_device_provisioned_for_this_very_project(self):
        """EXPLICIT EXCLUSION, not a fallthrough. The kiosk carries projA and
        would pass the project branch; it is refused before reaching it. A
        checklist assignment is a task given to a named person and a site
        device is not a person."""
        self.assertEqual(_status(_read, DEVICE_A), 403)

    def test_an_assignment_with_no_project_to_scope_through(self):
        db = _db(assignments=[dict(ASSIGNMENT, project_id="")])
        self.assertEqual(_status(_read, ADMIN_A, db), 403)

    def test_an_assignment_whose_project_id_is_absent(self):
        orphan = {k: v for k, v in ASSIGNMENT.items() if k != "project_id"}
        self.assertEqual(_status(_read, ADMIN_A, _db(assignments=[orphan])), 403)

    def test_an_unknown_assignment_is_404_not_403(self):
        """Does not confirm ids to a prober, and matches the route's existing
        answer for a deleted assignment."""
        self.assertEqual(_status(_read, ADMIN_A, _db(), "nope"), 404)

    def test_a_deleted_assignment_is_404(self):
        db = _db(assignments=[dict(ASSIGNMENT, is_deleted=True)])
        self.assertEqual(_status(_read, CP_NAMED, db), 404)


class TestWriteIsRefused(unittest.TestCase):
    def test_another_companys_admin_cannot_file_a_completion(self):
        self.assertEqual(_status(_write, OTHER_ADMIN), 403)

    def test_a_caller_with_no_company_cannot_file_a_completion(self):
        self.assertEqual(_status(_write, NO_COMPANY), 403)

    def test_a_site_device_cannot_file_a_completion(self):
        self.assertEqual(_status(_write, DEVICE_A), 403)

    def test_the_owning_companys_admin_cannot_file_one_either(self):
        """The rule READ and WRITE do not share. Ada may review this
        assignment; she may not attest to work nobody assigned her."""
        self.assertEqual(_status(_read, ADMIN_A), 200)
        self.assertEqual(_status(_write, ADMIN_A), 403)

    def test_a_project_member_who_was_not_named_cannot_file_one(self):
        self.assertEqual(_status(_write, WORKER_A), 403)

    def test_a_refused_write_stores_nothing(self):
        db = _db()
        self.assertEqual(_status(_write, OTHER_ADMIN, db), 403)
        self.assertEqual(db.checklist_completions.inserted, [])
        self.assertEqual(db.checklist_completions.updates, [])


# ----------------------------------------------------------------- ALLOWED --

class TestReadIsAllowed(unittest.TestCase):
    def test_the_person_it_was_assigned_to(self):
        out = _read(CP_NAMED)
        self.assertEqual(out["checklist"]["title"], CHECKLIST["title"])

    def test_a_cross_company_contractor_NAMED_on_it(self):
        """Sam's company does not own the project. The assignment names him,
        which is the strongest claim there is — it mirrors the
        assigned_projects branch require_project_access already honours."""
        self.assertEqual(_status(_read, SUB_NAMED), 200)

    def test_an_admin_of_the_owning_company_who_was_never_assigned(self):
        """The entire admin review surface. A membership-only guard kills it."""
        self.assertEqual(_status(_read, ADMIN_A), 200)

    def test_a_worker_of_the_owning_company(self):
        """Deliberately not restricted to admin/owner — same rule
        project_access_ok states for every batch-1 read."""
        self.assertEqual(_status(_read, WORKER_A), 200)

    def test_a_cross_company_cp_holding_the_project_via_assigned_projects(self):
        self.assertEqual(_status(_read, SUB_ON_PROJECT), 200)

    def test_the_completion_stays_scoped_to_the_caller(self):
        """Widening who may READ must not widen whose ANSWERS they see."""
        db = _db()
        db.checklist_completions.docs.append({
            "_id": "c1", "assignment_id": "as1", "user_id": "cp1",
            "user_name": "Cara CP", "item_completions": {"i1": {"checked": True}},
        })
        out = _run(db, lambda: server.get_assignment_details("as1", ADMIN_A))
        self.assertIsNone(out["completion"])


class TestWriteIsAllowed(unittest.TestCase):
    def test_the_person_it_was_assigned_to(self):
        db = _db()
        out = _write(CP_NAMED, db)
        self.assertEqual(out["user_id"], "cp1")
        self.assertEqual(len(db.checklist_completions.inserted), 1)

    def test_a_cross_company_contractor_named_on_it(self):
        db = _db()
        self.assertEqual(_status(_write, SUB_NAMED, db), 200)
        self.assertEqual(len(db.checklist_completions.inserted), 1)


# --------------------------------------------------------------- the wiring -

class TestBothRoutesGoThroughTheGate(unittest.TestCase):
    """A bare find_one reintroduces the hole silently — the route keeps
    working for everyone, which is exactly how it shipped the first time."""

    def test_read_route_calls_the_gate(self):
        import inspect
        body = inspect.getsource(server.get_assignment_details)
        self.assertIn("_assert_assignment_access", body)
        self.assertNotIn("db.checklist_assignments.find_one", body)

    def test_write_route_calls_the_gate_in_write_mode(self):
        import inspect
        body = inspect.getsource(server.complete_checklist)
        self.assertIn("_assert_assignment_access", body)
        self.assertIn("write=True", body)
        self.assertNotIn("db.checklist_assignments.find_one", body)


if __name__ == "__main__":
    unittest.main()
