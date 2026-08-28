"""The checklist read shape — nested `checklist`, computed `completions`.

Four endpoints served the assignment flat (`checklist_title`,
`checklist_items`) and both clients read it nested. The fatal one:
`app/checklists.jsx:101` calls `details.checklist.items.forEach(...)` on the
payload from `/checklists/assignments/{id}`, which had no `checklist` key. It
threw, the surrounding catch swallowed it, and the CP saw "Could not load
checklist" — only on FIRST open, because once a completion record exists the
other branch runs. A newly assigned checklist could not be opened by the person
it was assigned to.

These tests pin the shape the clients actually read, endpoint by endpoint, plus
the three things that are easy to undo by accident:

  1. the flat keys STAY GONE and the title is DERIVED (the frozen
     `checklist_title` copy must never reach a response again);
  2. `completed <= total` however the checklist is edited afterwards;
  3. the joins stay batched — one $in, not a query per assignment.

The handlers are called directly. `db` is patched to an in-memory double and
`to_query_id` to identity, so string ids behave the way ObjectIds do in prod.
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


CP = {"_id": "u_cp", "id": "u_cp", "role": "cp", "company_id": "co_a", "name": "Cara CP"}
ADMIN = {"_id": "u_ad", "id": "u_ad", "role": "admin", "company_id": "co_a", "name": "Ada Admin"}

ITEMS = [
    {"id": "i1", "text": "Harness inspected", "order": 0},
    {"id": "i2", "text": "Anchor points rated", "order": 1},
    {"id": "i3", "text": "Lanyard in date", "order": 2},
    {"id": "i4", "text": "Rescue plan posted", "order": 3},
]

CHECKLIST = {
    "_id": "cl1",
    "title": "Fall Protection — Daily",
    "description": "Before any work at height.",
    "items": ITEMS,
    "company_id": "co_a",
    "is_deleted": False,
}

# The assignment carries a STALE title: the checklist was renamed after it was
# created and `update_checklist` never propagated the rename. No response may
# print this string.
STALE_TITLE = "Fall Protection (old name)"

ASSIGNMENT = {
    "_id": "as1",
    "checklist_id": "cl1",
    "checklist_title": STALE_TITLE,
    "project_id": "p1",
    "project_name": "857 Prescott",
    "assigned_user_ids": ["u_cp"],
    "assigned_users": [{"id": "u_cp", "name": "Cara CP"}],
    "company_id": "co_a",
    "is_deleted": False,
}


def _completion(checked_ids, user_id="u_cp", assignment_id="as1", user_name="Cara CP"):
    return {
        "_id": f"cmp_{user_id}",
        "assignment_id": assignment_id,
        "checklist_id": "cl1",
        "project_id": "p1",
        "user_id": user_id,
        "user_name": user_name,
        "item_completions": {
            i: {"checked": True, "note": "", "timestamp": "2026-08-01T12:00:00Z"}
            for i in checked_ids
        },
    }


# ---------------------------------------------------------------- doubles ---

def _match(doc, query):
    """Enough of the query language for these endpoints: equality, $ne, $in,
    and membership against an array field."""
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
        self.find_queries = []
        self.updates = []
        self.inserted = []

    def find(self, query=None, *a, **k):
        self.find_queries.append(query)
        return _Cursor([dict(d) for d in self.docs if _match(d, query)])

    async def find_one(self, query=None, *a, **k):
        self.find_queries.append(query)
        for d in self.docs:
            if _match(d, query):
                return dict(d)
        return None

    async def count_documents(self, query=None, *a, **k):
        return len([d for d in self.docs if _match(d, query)])

    async def update_one(self, query, update, *a, **k):
        self.updates.append((query, update))

        class _R:
            matched_count = 1
        return _R()

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))

        class _R:
            inserted_id = f"new{len(self.inserted)}"
        return _R()


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())


def _db(checklists=None, assignments=None, completions=None, users=None, projects=None):
    return _Db(
        checklists=_Coll(checklists if checklists is not None else [CHECKLIST]),
        checklist_assignments=_Coll(assignments if assignments is not None else [ASSIGNMENT]),
        checklist_completions=_Coll(completions or []),
        users=_Coll(users or [CP, ADMIN]),
        projects=_Coll(projects or [{"_id": "p1", "name": "857 Prescott", "company_id": "co_a"}]),
    )


def _run(db, coro_factory):
    with patch.object(server, "db", db), patch.object(server, "to_query_id", lambda v: v):
        return asyncio.run(coro_factory())


# ------------------------------------------------------------- the break ---

class TestFirstOpenCarriesTheChecklist(unittest.TestCase):
    """`/checklists/assignments/{id}` — the payload the CP's screen dies on."""

    def test_first_open_with_no_completion_serves_checklist_items(self):
        """The exact failing path: assigned, never opened, no completion doc."""
        db = _db(completions=[])
        out = _run(db, lambda: server.get_assignment_details("as1", CP))

        # app/checklists.jsx:101 — this is the line that threw.
        self.assertIn("checklist", out)
        item_ids = [i["id"] for i in out["checklist"]["items"]]
        self.assertEqual(item_ids, ["i1", "i2", "i3", "i4"])
        self.assertIsNone(out["completion"])

    def test_flat_keys_are_gone(self):
        out = _run(_db(), lambda: server.get_assignment_details("as1", CP))
        self.assertNotIn("checklist_title", out)
        self.assertNotIn("checklist_items", out)

    def test_existing_completion_still_carries_item_completions(self):
        """The branch that already worked must keep working."""
        db = _db(completions=[_completion(["i1", "i2"])])
        out = _run(db, lambda: server.get_assignment_details("as1", CP))
        self.assertEqual(set(out["completion"]["item_completions"]), {"i1", "i2"})
        self.assertEqual(out["completion"]["progress"], {"completed": 2, "total": 4})

    def test_missing_checklist_is_404_not_a_null_dereference(self):
        """A stale deep link to an assignment whose checklist is gone answers
        404 — serving `checklist: null` would put the client back on the
        TypeError this change exists to remove."""
        db = _db(checklists=[])
        with self.assertRaises(HTTPException) as ctx:
            _run(db, lambda: server.get_assignment_details("as1", CP))
        self.assertEqual(ctx.exception.status_code, 404)


# ------------------------------------------------------------- progress ----

class TestProgressIsComputedAndBounded(unittest.TestCase):
    def test_completed_counts_truthy_checked_flags(self):
        db = _db(completions=[_completion(["i1", "i3"])])
        out = _run(db, lambda: server.get_assigned_checklists(CP))
        self.assertEqual(out[0]["completion"]["progress"], {"completed": 2, "total": 4})

    def test_unchecked_items_do_not_count(self):
        c = _completion(["i1", "i2"])
        c["item_completions"]["i2"]["checked"] = False
        db = _db(completions=[c])
        out = _run(db, lambda: server.get_assigned_checklists(CP))
        self.assertEqual(out[0]["completion"]["progress"]["completed"], 1)

    def test_completed_never_exceeds_total_after_an_item_is_deleted(self):
        """A CP ticked five items; an admin then deleted one from the
        checklist. Counting stored flags blind would report 5/4."""
        db = _db(completions=[_completion(["i1", "i2", "i3", "i4", "i_deleted"])])
        out = _run(db, lambda: server.get_assigned_checklists(CP))
        progress = out[0]["completion"]["progress"]
        self.assertEqual(progress, {"completed": 4, "total": 4})
        self.assertLessEqual(progress["completed"], progress["total"])

    def test_total_follows_an_item_added_after_completion(self):
        grown = dict(CHECKLIST, items=ITEMS + [{"id": "i5", "text": "New rule", "order": 4}])
        db = _db(checklists=[grown], completions=[_completion(["i1", "i2", "i3", "i4"])])
        out = _run(db, lambda: server.get_assigned_checklists(CP))
        self.assertEqual(out[0]["completion"]["progress"], {"completed": 4, "total": 5})

    def test_empty_checklist_reports_zero_of_zero_not_a_crash(self):
        db = _db(checklists=[dict(CHECKLIST, items=[])], completions=[_completion(["i1"])])
        out = _run(db, lambda: server.get_assigned_checklists(CP))
        self.assertEqual(out[0]["completion"]["progress"], {"completed": 0, "total": 0})


# --------------------------------------------------------- the CP's list ---

class TestAssignedListShape(unittest.TestCase):
    def test_serves_nested_checklist_and_no_flat_keys(self):
        out = _run(_db(), lambda: server.get_assigned_checklists(CP))
        self.assertEqual(out[0]["checklist"]["title"], CHECKLIST["title"])
        self.assertEqual(out[0]["checklist"]["description"], CHECKLIST["description"])
        self.assertEqual(len(out[0]["checklist"]["items"]), 4)
        self.assertNotIn("checklist_title", out[0])
        self.assertNotIn("checklist_items", out[0])

    def test_progress_object_exists_for_the_card_that_read_zero_of_zero(self):
        """app/checklists.jsx:198 reads `assignment.completion.progress`. The
        stored completion has never had one, so the bar read 0/0 · 0% for a CP
        who had ticked every item."""
        db = _db(completions=[_completion(["i1", "i2", "i3", "i4"])])
        out = _run(db, lambda: server.get_assigned_checklists(CP))
        self.assertEqual(out[0]["completion"]["progress"], {"completed": 4, "total": 4})
        self.assertTrue(out[0]["is_completed"])

    def test_another_users_completion_is_not_served_as_mine(self):
        db = _db(completions=[_completion(["i1", "i2"], user_id="u_other", user_name="Someone Else")])
        out = _run(db, lambda: server.get_assigned_checklists(CP))
        self.assertIsNone(out[0]["completion"])
        self.assertFalse(out[0]["is_completed"])

    def test_assignment_whose_checklist_is_deleted_is_skipped(self):
        out = _run(_db(checklists=[]), lambda: server.get_assigned_checklists(CP))
        self.assertEqual(out, [])


# ----------------------------------------------------- the admin surfaces --

class TestAdminSurfacesGetCompletionRows(unittest.TestCase):
    """Both admin surfaces render
    `[{user_id, progress: {completed, total}}]`, keyed against
    `assigned_users`. Neither the list nor the progress was ever served."""

    def test_project_screen_rows(self):
        db = _db(completions=[_completion(["i1", "i2"])])
        out = _run(db, lambda: server.get_project_checklists("p1", ADMIN, None))
        rows = out[0]["completions"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_id"], "u_cp")
        self.assertEqual(rows[0]["progress"], {"completed": 2, "total": 4})
        # keyed by user_id against assigned_users, which already reached the client
        self.assertEqual([u["id"] for u in out[0]["assigned_users"]], ["u_cp"])

    def test_project_screen_serves_nested_checklist(self):
        out = _run(_db(), lambda: server.get_project_checklists("p1", ADMIN, None))
        self.assertEqual(out[0]["checklist"]["title"], CHECKLIST["title"])
        self.assertEqual(len(out[0]["checklist"]["items"]), 4)
        self.assertNotIn("checklist_items", out[0])

    def test_admin_assignments_rows(self):
        db = _db(completions=[_completion(["i1", "i2", "i3", "i4"])])
        out = _run(db, lambda: server.get_checklist_assignments("cl1", ADMIN))
        rows = out[0]["completions"]
        self.assertEqual(rows[0]["progress"], {"completed": 4, "total": 4})

    def test_user_name_is_carried_through(self):
        """`complete_checklist` has always stored `user_name`; the row carries
        it rather than re-deriving a name that is already recorded."""
        db = _db(completions=[_completion(["i1"])])
        out = _run(db, lambda: server.get_checklist_assignments("cl1", ADMIN))
        self.assertEqual(out[0]["completions"][0]["user_name"], "Cara CP")

    def test_completion_stats_keeps_its_old_meaning(self):
        """It counts completion RECORDS, exactly as the count_documents it
        replaced did. Nothing reads it, but nothing may silently redefine it."""
        db = _db(completions=[
            _completion(["i1"]),
            _completion(["i2"], user_id="u2", user_name="Second"),
        ])
        out = _run(db, lambda: server.get_checklist_assignments("cl1", ADMIN))
        self.assertEqual(out[0]["completion_stats"], {"total_assigned": 1, "completed": 2})


# ------------------------------------------------- the derived title -------

class TestFrozenTitleNeverReachesAResponse(unittest.TestCase):
    """`checklist_title` is copied onto the assignment at creation and no
    rename propagates. Deriving the title on read makes that stale copy
    invisible WITHOUT a migration — so no response may carry the stored key,
    on any of the four endpoints. Restoring it restores the bug."""

    def _assert_clean(self, payload):
        blob = repr(payload)
        self.assertNotIn(STALE_TITLE, blob)
        self.assertNotIn("checklist_title", blob)
        self.assertIn(CHECKLIST["title"], blob)

    def test_project_checklists(self):
        self._assert_clean(_run(_db(), lambda: server.get_project_checklists("p1", ADMIN, None)))

    def test_admin_assignments(self):
        self._assert_clean(_run(_db(), lambda: server.get_checklist_assignments("cl1", ADMIN)))

    def test_assigned(self):
        self._assert_clean(_run(_db(), lambda: server.get_assigned_checklists(CP)))

    def test_assignment_details(self):
        self._assert_clean(_run(_db(), lambda: server.get_assignment_details("as1", CP)))


# ------------------------------------------------------------ batching -----

class TestListEndpointsBatchTheirJoins(unittest.TestCase):
    """One $in per collection for a whole page, not a query per assignment."""

    def _page(self, n=6):
        assignments, checklists, completions = [], [], []
        for i in range(n):
            assignments.append(dict(ASSIGNMENT, _id=f"as{i}", checklist_id=f"cl{i}"))
            checklists.append(dict(CHECKLIST, _id=f"cl{i}"))
            completions.append(_completion(["i1"], assignment_id=f"as{i}"))
        return _db(checklists=checklists, assignments=assignments, completions=completions)

    def test_assigned_issues_one_query_per_collection(self):
        db = self._page()
        out = _run(db, lambda: server.get_assigned_checklists(CP))
        self.assertEqual(len(out), 6)
        self.assertEqual(len(db.checklists.find_queries), 1)
        self.assertEqual(len(db.checklist_completions.find_queries), 1)

    def test_project_checklists_issues_one_query_per_collection(self):
        db = self._page()
        out = _run(db, lambda: server.get_project_checklists("p1", ADMIN, None))
        self.assertEqual(len(out), 6)
        self.assertEqual(len(db.checklists.find_queries), 1)
        self.assertEqual(len(db.checklist_completions.find_queries), 1)

    def test_admin_assignments_issues_one_completions_query(self):
        db = self._page()
        # every assignment on this page belongs to the same checklist
        for d in db.checklist_assignments.docs:
            d["checklist_id"] = "cl0"
        out = _run(db, lambda: server.get_checklist_assignments("cl0", ADMIN))
        self.assertEqual(len(out), 6)
        self.assertEqual(len(db.checklist_completions.find_queries), 1)

    def test_empty_page_touches_nothing(self):
        db = _db(assignments=[])
        self.assertEqual(_run(db, lambda: server.get_assigned_checklists(CP)), [])
        self.assertEqual(db.checklists.find_queries, [])
        self.assertEqual(db.checklist_completions.find_queries, [])


# -------------------------------------------------- followup #4: re-assign --

class TestReassignWritesBothCopiesOfTheRoster(unittest.TestCase):
    """The re-assign path $set `assigned_user_ids` and not `assigned_users` —
    it changed the list the server queries by and left the list the screen
    prints naming whoever was assigned before."""

    def _reassign(self, user_ids):
        db = _db()
        payload = server.ChecklistAssignmentCreate(
            checklist_id="cl1", project_ids=["p1"], user_ids=user_ids,
        )
        _run(db, lambda: server.assign_checklist("cl1", payload, ADMIN))
        return db

    def test_both_copies_are_written(self):
        db = self._reassign(["u_ad"])
        self.assertEqual(len(db.checklist_assignments.updates), 1)
        _query, update = db.checklist_assignments.updates[0]
        self.assertEqual(update["$set"]["assigned_user_ids"], ["u_ad"])
        self.assertEqual(update["$set"]["assigned_users"], [{"id": "u_ad", "name": "Ada Admin"}])

    def test_the_names_the_screen_prints_actually_change(self):
        db = self._reassign(["u_ad"])
        _query, update = db.checklist_assignments.updates[0]
        printed = [u["name"] for u in update["$set"]["assigned_users"]]
        self.assertEqual(printed, ["Ada Admin"])
        self.assertNotIn("Cara CP", printed)

    def test_a_new_assignment_still_denormalizes_the_roster(self):
        db = _db(assignments=[])
        payload = server.ChecklistAssignmentCreate(
            checklist_id="cl1", project_ids=["p1"], user_ids=["u_cp"],
        )
        _run(db, lambda: server.assign_checklist("cl1", payload, ADMIN))
        created = db.checklist_assignments.inserted[0]
        self.assertEqual(created["assigned_users"], [{"id": "u_cp", "name": "Cara CP"}])
        self.assertEqual(created["assigned_user_ids"], ["u_cp"])


if __name__ == "__main__":
    unittest.main()
