"""A SUPERINTENDENT'S ASSIGNED PROJECTS ARE HIS ACTIVE REGISTRATIONS.

OPERATOR RULING. Registration does both. Registering a superintendent on a
project writes the `cs_registrations` row AND adds the project to his
`assigned_projects`; unregistering soft-deletes the row and removes the
assignment. The superintendent card therefore carries Registration, Edit and
Delete, and no Assign button -- CP and PM keep theirs.

    INVARIANT: for a superintendent, set(assigned_projects)
               == {r.project_id for r in cs_registrations if r.is_active}

── WHY THE TWO HALVES SHIP TOGETHER AND CANNOT BE SPLIT ────────────────────

Before this, registration could only be made on a project he was ALREADY
assigned to -- `selectable` was his assignment list, and the endpoint refused
anything outside it. Remove the Assign button first and a newly created
superintendent has an empty assignment list, so the Registration modal offers
him nothing and he can never be registered on anything. Land the write first
and Assign becomes a second writer of a set that now has an owner. Both, or
neither.

── WHAT THIS DOES NOT DO, AND THE MEASUREMENT THAT SAYS SO ─────────────────

NO REPAIR. The invariant holds in production today -- one superintendent
exists, and his `assigned_projects` and his single active registration are the
same project. Nothing diverges, so there is nothing to reconcile, and a
migration written for a population of zero is a migration nobody can test. What
lands is the code that keeps it true going forward.

── THE DE-SELECTION PASS IS STILL SCOPED, FOR THE ORIGINAL REASON ──────────

A save must never retire a registration the screen could not show. That rule
does not go away when `selectable` widens from "his assignments" to "his
company's projects" -- it just has a new set to be scoped to. A row on a
project outside the company (or on a deleted one) is still returned as
`registered_elsewhere` and still left alone.

AND THAT FIELD IS NOW THE INSTRUMENT. Under the invariant it should be empty
forever; a non-empty `registered_elsewhere` is the divergence reporting itself,
on the screen, rather than a report nobody runs.
"""

from __future__ import annotations

import asyncio
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

ADMIN = {"id": "a1", "_id": "a1", "role": "admin", "company_id": "c1"}


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return self.rows[:n]


class _Result:
    def __init__(self, n):
        self.modified_count = n
        self.matched_count = n


def _match(doc, q):
    for k, cond in q.items():
        if k == "$or":
            if not any(_match(doc, c) for c in cond):
                return False
            continue
        v = doc.get(k)
        if isinstance(cond, dict):
            if "$ne" in cond and v == cond["$ne"]:
                return False
            if "$in" in cond and v not in cond["$in"]:
                return False
        elif v != cond:
            return False
    return True


class _Coll:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.rows if _match(d, query or {})])

    async def find_one(self, query=None, projection=None):
        for d in self.rows:
            if _match(d, query or {}):
                return d
        return None

    async def update_one(self, query, update, **kw):
        self.updates.append((query, update))
        hit = 0
        for d in self.rows:
            if _match(d, query):
                _apply(d, update)
                hit = 1
                break
        return _Result(hit)

    async def update_many(self, query, update, **kw):
        self.updates.append((query, update))
        n = 0
        for d in self.rows:
            if _match(d, query):
                _apply(d, update)
                n += 1
        return _Result(n)


def _apply(doc, update):
    for k, v in (update.get("$set") or {}).items():
        doc[k] = v
    for k, v in (update.get("$addToSet") or {}).items():
        cur = list(doc.get(k) or [])
        vals = v.get("$each", [v]) if isinstance(v, dict) else [v]
        for one in vals:
            if one not in cur:
                cur.append(one)
        doc[k] = cur
    for k, v in (update.get("$pull") or {}).items():
        cur = list(doc.get(k) or [])
        vals = v.get("$in", [v]) if isinstance(v, dict) else [v]
        doc[k] = [x for x in cur if x not in vals]


class Base(unittest.TestCase):
    def setUp(self):
        self.michael = {
            "_id": "su1", "id": "su1", "name": "Michael Cespedes",
            "email": "m@a.com", "role": "superintendent", "company_id": "c1",
            "dob_superintendent_number": "32299",
            "assigned_projects": ["p1"], "is_deleted": False,
        }
        self.users = _Coll([self.michael, ADMIN])
        self.projects = _Coll([
            {"_id": "p1", "id": "p1", "name": "588 Thomas", "company_id": "c1"},
            {"_id": "p2", "id": "p2", "name": "12 Vestry", "company_id": "c1"},
        ])
        self.regs = _Coll([
            {"_id": "r1", "user_id": "su1", "project_id": "p1",
             "is_active": True, "is_deleted": False, "license_number": "32299"},
        ])
        self.registered = []

        outer = self

        class _DB:
            users = self.users
            projects = self.projects
            cs_registrations = self.regs

        self._orig = {
            "db": server.db,
            "reg": server._register_cs_on_project,
            "audit": server.audit_log,
            "val": server.validate_assignable_projects,
            "op": server.is_platform_operator,
            "cid": server.get_user_company_id,
            "acc": server.project_access_ok,
        }
        server.db = _DB()
        server.is_platform_operator = lambda u: False
        server.get_user_company_id = lambda u: (u or {}).get("company_id")
        server.project_access_ok = lambda project, pid, user: True

        async def _register(**kw):
            outer.registered.append(kw["project_id"])
            outer.regs.rows.append({
                "_id": f"r-{kw['project_id']}", "user_id": kw["user_id"],
                "project_id": kw["project_id"], "is_active": True,
                "is_deleted": False, "license_number": kw["license_number"],
            })
            return {"project_id": kw["project_id"], "conflict_warning": None}

        async def _audit(*a, **k):
            return None

        async def _validate(actor, ids):
            company = (actor or {}).get("company_id")
            out = []
            for raw in ids or []:
                pid = str(raw or "").strip()
                if not pid or pid in out:
                    continue
                prj = next((p for p in outer.projects.rows if p["_id"] == pid), None)
                if not prj or prj.get("company_id") != company:
                    raise HTTPException(
                        status_code=403,
                        detail="Cannot assign a project outside your company")
                out.append(pid)
            return out

        server._register_cs_on_project = _register
        server.audit_log = _audit
        server.validate_assignable_projects = _validate

    def tearDown(self):
        server.db = self._orig["db"]
        server._register_cs_on_project = self._orig["reg"]
        server.audit_log = self._orig["audit"]
        server.validate_assignable_projects = self._orig["val"]
        server.is_platform_operator = self._orig["op"]
        server.get_user_company_id = self._orig["cid"]
        server.project_access_ok = self._orig["acc"]

    def save(self, project_ids):
        body = server.UserCSRegistrationsSet(project_ids=project_ids)
        return asyncio.run(server.set_user_cs_registrations("su1", body, ADMIN))

    def read(self):
        return asyncio.run(server.get_user_cs_registrations("su1", ADMIN))

    def active(self):
        return {r["project_id"] for r in self.regs.rows if r.get("is_active")}

    def assigned(self):
        return set(self.michael.get("assigned_projects") or [])


class RegisteringAlsoAssigns(Base):
    """THE HALF THAT MAKES THE BUTTON REMOVABLE."""

    def test_a_new_registration_lands_in_assigned_projects(self):
        self.save(["p1", "p2"])
        self.assertIn("p2", self.assigned())

    def test_and_the_two_sets_are_the_same_set(self):
        self.save(["p1", "p2"])
        self.assertEqual(self.assigned(), self.active())

    def test_a_superintendent_can_be_registered_on_a_project_he_was_never_assigned(self):
        """THE CASE THAT BREAKS IF THE HALVES ARE SPLIT. p2 is not in his
        assignment list. Before this the endpoint refused it by name."""
        self.michael["assigned_projects"] = []
        self.save(["p2"])
        self.assertEqual(self.assigned(), {"p2"})
        self.assertIn("p2", self.registered)

    def test_the_picker_offers_the_companys_projects_not_his_assignments(self):
        """`selectable` WAS his assignment list, which under this ruling would
        be the set he is already registered on -- a picker that can only offer
        what is already ticked."""
        self.michael["assigned_projects"] = []
        got = self.read()
        self.assertEqual({p["project_id"] for p in got["selectable"]},
                         {"p1", "p2"})


class UnregisteringAlsoUnassigns(Base):
    """THE OTHER DIRECTION. An assignment left behind is a live authorization
    grant: `require_project_access` honours `assigned_projects` (branch 3), so
    a superintendent unregistered from a job would keep reaching it."""

    def test_a_removed_project_leaves_assigned_projects(self):
        self.save([])
        self.assertEqual(self.assigned(), set())

    def test_and_the_row_is_soft_deleted_not_removed(self):
        """Unchanged, and it must stay unchanged. The row is the provenance of
        every log filed under it -- `attribute_signer` reads `deactivated_at`
        and `deleted_at` to decide what a document signed months ago can say
        about who signed it."""
        self.save([])
        row = self.regs.rows[0]
        self.assertFalse(row["is_active"])
        self.assertTrue(row["is_deleted"])
        self.assertIn(row, self.regs.rows)

    def test_swapping_one_job_for_another_leaves_exactly_one_of_each(self):
        self.save(["p2"])
        self.assertEqual(self.assigned(), {"p2"})
        self.assertEqual(self.active(), {"p2"})

    def test_a_no_op_save_writes_nothing_and_changes_nothing(self):
        """Re-running `_register_cs_on_project` for a project already
        registered would supersede his own row with an identical one, moving
        `created_at` forward -- and `attribute_signer` returns REGISTERED_LATER
        for a registration that postdates the log. A no-op save would make
        every log he has already filed stop being attributable to him."""
        self.save(["p1"])
        self.assertEqual(self.registered, [])
        self.assertEqual(self.assigned(), {"p1"})
        self.assertEqual(self.active(), {"p1"})


class TheTenantCheckSurvivesTheWiderPicker(Base):
    """`selectable` widened from "his assignments" to "his company's projects",
    and his assignment list was ALSO the tenant check -- ids in it had already
    been through `validate_assignable_projects`. Widening the set without
    replacing that check would have made this endpoint a way to mint
    cross-tenant access."""

    def test_a_project_outside_the_company_is_refused(self):
        self.projects.rows.append(
            {"_id": "p9", "id": "p9", "name": "Other Tenant", "company_id": "c2"})
        with self.assertRaises(HTTPException) as cm:
            self.save(["p1", "p9"])
        self.assertEqual(cm.exception.status_code, 403)

    def test_and_the_refusal_is_total_not_partial(self):
        """The whole request, or none of it. A partial success that looked like
        a full one would leave an admin believing a registration exists."""
        self.projects.rows.append(
            {"_id": "p9", "id": "p9", "name": "Other Tenant", "company_id": "c2"})
        try:
            self.save(["p2", "p9"])
        except HTTPException:
            pass
        self.assertEqual(self.assigned(), {"p1"})
        self.assertEqual(self.active(), {"p1"})


class ARegistrationTheScreenCannotSeeIsLeftAlone(Base):
    """UNCHANGED RULE, NEW SCOPE. The de-selection pass touches only what the
    picker could show. Under the invariant this set is empty forever -- which
    makes a non-empty one the divergence reporting itself."""

    def test_a_row_on_a_project_outside_the_company_survives_a_save(self):
        self.regs.rows.append(
            {"_id": "rX", "user_id": "su1", "project_id": "pZ",
             "is_active": True, "is_deleted": False, "license_number": "32299"})
        self.save(["p1"])
        survivor = next(r for r in self.regs.rows if r["_id"] == "rX")
        self.assertTrue(survivor["is_active"])

    def test_and_the_read_names_it_rather_than_hiding_it(self):
        self.regs.rows.append(
            {"_id": "rX", "user_id": "su1", "project_id": "pZ",
             "is_active": True, "is_deleted": False, "license_number": "32299"})
        got = self.read()
        self.assertEqual([r["project_id"] for r in got["registered_elsewhere"]],
                         ["pZ"])

    def test_it_is_empty_when_nothing_diverges(self):
        self.assertEqual(self.read()["registered_elsewhere"], [])


class AssignIsNoLongerASecondWriterForHim(Base):
    """THE BUTTON IS GONE FROM THE CARD AND THE ENDPOINT IT CALLED IS CLOSED
    FOR THIS ROLE. Hiding a control is a courtesy; the invariant needs the
    write refused, or the next caller re-opens the divergence the screen no
    longer can."""

    def test_assign_projects_refuses_a_superintendent(self):
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(server.assign_projects_to_user(
                "su1", {"project_ids": ["p2"]}, ADMIN))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("Registration", str(cm.exception.detail))

    def test_and_it_still_serves_a_cp(self):
        """The refusal is about ONE role. A guard that refused everybody would
        pass the test above and take Assign away from every CP in the
        product."""
        self.users.rows.append({
            "_id": "cp1", "id": "cp1", "name": "A CP", "role": "cp",
            "company_id": "c1", "assigned_projects": [], "is_deleted": False})
        asyncio.run(server.assign_projects_to_user(
            "cp1", {"project_ids": ["p2"]}, ADMIN))
        cp = next(u for u in self.users.rows if u["_id"] == "cp1")
        self.assertEqual(cp["assigned_projects"], ["p2"])

    def test_the_edit_route_refuses_the_same_write(self):
        """The second door. `assigned_projects` is in ALLOWED_USER_FIELDS, so
        PUT /admin/users is a way to set the list directly."""
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(server.update_admin_user(
                "su1", {"assigned_projects": ["p2"]}, ADMIN))
        self.assertEqual(cm.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
