"""A live check-in point is never silently moved to another project.

THE BUG. `add_nfc_tag_to_project` looked the tag_id up across the WHOLE
collection (it has to — tag_id carries a unique index, so an insert would
conflict) and, on finding it live somewhere else, `$pull`ed it off that
project's nfc_tags array and repointed the row at the caller's project. The
company check in that handler is on the TARGET project only, so an admin of
company A could take a check-in point off company B's project document by
typing its id. A cross-tenant edit reachable from a typo, leaving nothing but
an info-level log line.

WHY THE FIX IS A NARROW PREDICATE AND NOT `if existing_tag: 409`. The unique
index means this same branch is the ONLY way any tag re-registers — an insert
can never be the fallback. Three states have to keep passing, and each one is
a way this fix could become a worse trap than the bug it closes:

  1. same project, active      — the only path that renames location_description
  2. is_deleted                — an admin released it; also the second half of
                                 the delete-then-add move that REPLACES the
                                 silent reassignment, so breaking it would
                                 break the documented remedy
  3. status "project_closed"   — set by mark_project_for_deletion, which sweeps
                                 a closed site's tags and leaves is_deleted
                                 alone. Refuse this and a physical sticker from
                                 a closed site is unusable FOREVER: the only
                                 release is DELETE, DELETE needs the old
                                 project_id, and that project is gone from
                                 every listing.

(3) is the one a future reader will "tidy" into the is_deleted check without
knowing why it is separate. It is asserted here, and the reason is in the
handler, so neither the code nor the test can lose it alone.

Run:  pytest tests/test_nfc_tag_no_silent_reassign.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402

PROJ_A = "projA"
PROJ_B = "projB"
TAG = "04A2B3C4D5E680"

ADMIN_A = {
    "_id": "ua", "id": "ua", "role": "admin", "company_id": "companyA",
    "account_status": "approved", "assigned_projects": [],
}


class _Coll:
    """Just enough of a Motor collection for this handler."""

    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
        self.updates = []   # (filter, update) for every update_one
        self.inserts = []

    @staticmethod
    def _match(doc, query):
        for k, v in (query or {}).items():
            if isinstance(v, dict):
                if "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
                if "$in" in v and doc.get(k) not in v["$in"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if self._match(d, query):
                return dict(d)
        return None

    async def update_one(self, flt, update, *a, **k):
        self.updates.append((flt, update))
        for d in self.docs:
            if self._match(d, flt):
                d.update(update.get("$set") or {})
        return None

    async def insert_one(self, doc, *a, **k):
        self.inserts.append(dict(doc))
        self.docs.append(dict(doc))
        return None


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())

    def __getitem__(self, name):
        return getattr(self, name)


def _projects():
    return _Coll([
        {"_id": PROJ_A, "name": "A", "company_id": "companyA", "nfc_tags": []},
        {"_id": PROJ_B, "name": "B", "company_id": "companyB",
         "nfc_tags": [{"tag_id": TAG, "location": "B main gate"}]},
    ])


def _post(db, project_id=PROJ_A, tag_id=TAG, location="Main Gate"):
    """POST the tag, with ADMIN_A authenticated and `db` swapped in."""
    async def _fake_user():
        return ADMIN_A

    orig_db = server.db
    orig_company = server.get_user_company_id
    orig_qid = server.to_query_id
    server.db = db
    server.get_user_company_id = lambda u: u.get("company_id")
    # The fixture ids are plain strings, not ObjectIds.
    server.to_query_id = lambda v: v
    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        client = TestClient(server.app)
        return client.post(
            f"/api/projects/{project_id}/nfc-tags",
            json={"tag_id": tag_id, "location_description": location},
        )
    finally:
        server.db = orig_db
        server.get_user_company_id = orig_company
        server.to_query_id = orig_qid
        server.app.dependency_overrides.clear()


class TestTheCrossTenantMoveIsRefused(unittest.TestCase):

    def _live_on_b(self):
        return _Coll([{
            "_id": "t1", "tag_id": TAG, "project_id": PROJ_B,
            "company_id": "companyB", "status": "active", "is_deleted": False,
            "location_description": "B main gate",
        }])

    def test_409_not_a_move(self):
        tags = self._live_on_b()
        projects = _projects()
        res = _post(_Db(projects=projects, nfc_tags=tags))
        self.assertEqual(res.status_code, 409, res.text)

    def test_the_tag_still_belongs_to_the_other_project(self):
        tags = self._live_on_b()
        projects = _projects()
        _post(_Db(projects=projects, nfc_tags=tags))
        self.assertEqual(tags.docs[0]["project_id"], PROJ_B,
                         "the tag row must not be repointed")
        self.assertEqual(tags.docs[0]["company_id"], "companyB")

    def test_the_other_projects_array_is_untouched(self):
        # The $pull was the actual cross-tenant WRITE. Its absence is the fix.
        tags = self._live_on_b()
        projects = _projects()
        _post(_Db(projects=projects, nfc_tags=tags))
        proj_b = [d for d in projects.docs if d["_id"] == PROJ_B][0]
        self.assertEqual(
            proj_b["nfc_tags"], [{"tag_id": TAG, "location": "B main gate"}],
            "another company's project document must never be written",
        )
        self.assertEqual(
            [f for f, _u in projects.updates if f.get("_id") == PROJ_B], [],
            "no update may target the other project at all",
        )

    def test_the_message_names_the_id_and_no_project(self):
        tags = self._live_on_b()
        res = _post(_Db(projects=_projects(), nfc_tags=tags))
        detail = res.json().get("detail", "")
        self.assertIn(TAG, detail, "the caller's own input is safe to echo")
        # Naming the holder would be a smaller version of the leak being closed.
        for leak in ("projB", "companyB", "B main gate"):
            self.assertNotIn(leak, detail,
                             f"the 409 must not disclose {leak}")
        self.assertIn("in use", detail.lower())
        self.assertIn("remove it", detail.lower())


class TestTheThreePermittedStates(unittest.TestCase):
    """Each of these is a way the fix could become a worse trap than the bug.

    All three go through the SAME branch as the refusal above, because the
    unique index on tag_id means an insert is never available as a fallback.
    """

    def test_1_same_project_active_still_re_registers(self):
        # The only path that renames a check-in point.
        tags = _Coll([{
            "_id": "t1", "tag_id": TAG, "project_id": PROJ_A,
            "company_id": "companyA", "status": "active", "is_deleted": False,
            "location_description": "Old name",
        }])
        res = _post(_Db(projects=_projects(), nfc_tags=tags),
                    location="New name")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(tags.docs[0]["location_description"], "New name")

    def test_2_a_deleted_tag_revives_onto_the_new_project(self):
        # The delete-then-add move that REPLACES the silent reassignment. If
        # this 409s, the remedy the 409 message recommends does not work.
        tags = _Coll([{
            "_id": "t1", "tag_id": TAG, "project_id": PROJ_B,
            "company_id": "companyB", "status": "active", "is_deleted": True,
            "location_description": "B main gate",
        }])
        res = _post(_Db(projects=_projects(), nfc_tags=tags))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(tags.docs[0]["project_id"], PROJ_A)
        self.assertEqual(tags.docs[0]["company_id"], "companyA")
        self.assertIs(tags.docs[0]["is_deleted"], False)
        self.assertEqual(tags.docs[0]["status"], "active")

    def test_3_a_project_closed_tag_revives_onto_the_new_project(self):
        # DO NOT FOLD THIS INTO test_2. mark_project_for_deletion sets
        # status="project_closed" and leaves is_deleted ALONE, so this row is
        # neither deleted nor active. Refusing it strands the physical sticker
        # forever: DELETE is the only release and it needs the old project_id,
        # which is gone from every listing once the project is closed.
        tags = _Coll([{
            "_id": "t1", "tag_id": TAG, "project_id": PROJ_B,
            "company_id": "companyB", "status": "project_closed",
            "is_deleted": False, "location_description": "B main gate",
        }])
        res = _post(_Db(projects=_projects(), nfc_tags=tags))
        self.assertEqual(
            res.status_code, 200,
            "a tag from a closed site must be reusable, or the sticker is "
            f"dead forever: {res.text}",
        )
        self.assertEqual(tags.docs[0]["project_id"], PROJ_A)
        self.assertEqual(tags.docs[0]["status"], "active")

    def test_3_is_distinguishable_from_the_refusal(self):
        # The two fixtures differ ONLY in `status`. If someone rewrites the
        # predicate as a truthiness test on is_deleted, this pair is what
        # catches it: same is_deleted, opposite outcomes.
        base = {
            "_id": "t1", "tag_id": TAG, "project_id": PROJ_B,
            "company_id": "companyB", "is_deleted": False,
            "location_description": "B main gate",
        }
        closed = _post(_Db(projects=_projects(),
                           nfc_tags=_Coll([{**base, "status": "project_closed"}])))
        active = _post(_Db(projects=_projects(),
                           nfc_tags=_Coll([{**base, "status": "active"}])))
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(active.status_code, 409)


class TestABrandNewTagIsUnaffected(unittest.TestCase):

    def test_insert_still_happens(self):
        tags = _Coll([])
        res = _post(_Db(projects=_projects(), nfc_tags=tags))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(tags.inserts), 1)
        self.assertEqual(tags.inserts[0]["tag_id"], TAG)
        self.assertEqual(tags.inserts[0]["project_id"], PROJ_A)


if __name__ == "__main__":
    unittest.main()
