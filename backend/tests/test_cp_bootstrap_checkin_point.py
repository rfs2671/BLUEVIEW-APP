"""A CP may open a gate when the project has none, and close one they opened.

THE FAILURE THIS EXISTS FOR. A tag is destroyed mid-shift, no admin is
reachable, and the project has no other check-in point. /info 404s without an
ACTIVE row, so tap and scan both fail. The men still work — nothing turns
anyone away — but the 3301.11 orientation record for that shift is simply
missing and cannot be reconstructed afterwards. The CP is the one person
standing there and, until now, the one person forbidden from fixing it.

THE POWER IS DELIBERATELY NARROW, and each bound is asserted here:

  * only when the project has ZERO ACTIVE tags — not "no rows"; see
    TestZeroActiveNotNoRows, which is the case a reopened site produces;
  * the CALLER NEVER SUPPLIES AN ID — the server mints "qr-<hex>", which
    cannot collide with a hardware UID because NFC UIDs are hex and hex has
    no "q" and no "-";
  * the row is PROVISIONAL — QR-only, permanently shareable, and flagged so
    the emergency fix cannot silently become the permanent state;
  * a CP may DELETE only their own gate, and only before a man has tapped in.

Run:  pytest tests/test_cp_bootstrap_checkin_point.py
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402

PROJ = "projA"

CP = {"_id": "cp1", "id": "cp1", "role": "cp", "company_id": "companyA",
      "account_status": "approved", "assigned_projects": [PROJ]}
ADMIN = {"_id": "ad1", "id": "ad1", "role": "admin", "company_id": "companyA",
         "account_status": "approved", "assigned_projects": []}
CP_OTHER = {"_id": "cp2", "id": "cp2", "role": "cp", "company_id": "companyA",
            "account_status": "approved", "assigned_projects": [PROJ]}


class _Coll:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
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

    async def count_documents(self, query=None, *a, **k):
        return sum(1 for d in self.docs if self._match(d, query))

    async def update_one(self, flt, update, *a, **k):
        for d in self.docs:
            if self._match(d, flt):
                d.update(update.get("$set") or {})
                # $push is honoured so the array assertion below is real
                # rather than vacuously true over an empty list.
                for key, val in (update.get("$push") or {}).items():
                    d.setdefault(key, []).append(val)
        return None

    async def insert_one(self, doc, *a, **k):
        self.inserts.append(dict(doc))
        self.docs.append(dict(doc))
        return None

    def find(self, query=None, projection=None, *a, **k):
        docs = [dict(d) for d in self.docs if self._match(d, query)]

        class _Cur:
            def __aiter__(self_inner):
                async def gen():
                    for d in docs:
                        yield d
                return gen()

        return _Cur()


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
    return _Coll([{"_id": PROJ, "name": "A", "company_id": "companyA", "nfc_tags": []}])


def _call(user, db, method="post", path=None, json=None):
    async def _fake_user():
        return user

    orig_db, orig_company, orig_qid = server.db, server.get_user_company_id, server.to_query_id
    server.db = db
    server.get_user_company_id = lambda u: u.get("company_id")
    server.to_query_id = lambda v: v
    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        client = TestClient(server.app)
        if method == "post":
            return client.post(path, json=json or {})
        return client.delete(path)
    finally:
        server.db = orig_db
        server.get_user_company_id = orig_company
        server.to_query_id = orig_qid
        server.app.dependency_overrides.clear()


BOOTSTRAP = f"/api/projects/{PROJ}/checkin-points/bootstrap"


class TestTheCpCanOpenAGate(unittest.TestCase):

    def test_mints_one_when_the_project_has_none(self):
        tags = _Coll([])
        res = _call(CP, _Db(projects=_projects(), nfc_tags=tags), path=BOOTSTRAP)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(tags.inserts), 1)

    def test_the_server_mints_the_id_and_the_caller_cannot(self):
        # A CP who cannot type an id cannot typo one, cannot squat one, and
        # cannot reach the cross-project collision branch add_nfc_tag refuses.
        tags = _Coll([])
        res = _call(CP, _Db(projects=_projects(), nfc_tags=tags), path=BOOTSTRAP,
                    json={"tag_id": "04DEADBEEF0000", "location_description": "Gate 1"})
        self.assertEqual(res.status_code, 200, res.text)
        minted = res.json()["tag_id"]
        self.assertNotEqual(minted, "04DEADBEEF0000",
                            "a client-supplied id must never be honoured")
        self.assertEqual(tags.inserts[0]["tag_id"], minted)

    def test_the_id_cannot_collide_with_a_hardware_uid(self):
        # NFC UIDs are hex. "qr-" carries a letter and a separator hex cannot
        # produce, so no chip of any UID length can ever collide.
        tags = _Coll([])
        res = _call(CP, _Db(projects=_projects(), nfc_tags=tags), path=BOOTSTRAP)
        minted = res.json()["tag_id"]
        self.assertTrue(minted.startswith("qr-"), minted)
        self.assertFalse(re.fullmatch(r"[0-9A-Fa-f]+", minted),
                         "a minted id must not be parseable as a hex UID")

    def test_the_row_is_provisional_and_attributed(self):
        tags = _Coll([])
        res = _call(CP, _Db(projects=_projects(), nfc_tags=tags), path=BOOTSTRAP)
        row = tags.inserts[0]
        self.assertIs(row["provisional"], True,
                      "without the flag the emergency fix silently becomes permanent")
        self.assertEqual(row["created_by_role"], "cp")
        self.assertEqual(row["created_by"], "cp1")
        self.assertIs(res.json()["provisional"], True,
                      "the caller is told what they just made")

    def test_it_is_a_working_gate(self):
        # Same shape the gate queries: status active, not deleted, on this
        # project. A row that /info would 404 on is not a fix.
        tags = _Coll([])
        _call(CP, _Db(projects=_projects(), nfc_tags=tags), path=BOOTSTRAP)
        row = tags.inserts[0]
        self.assertEqual(row["status"], "active")
        self.assertIs(row["is_deleted"], False)
        self.assertEqual(row["project_id"], PROJ)

    def test_an_admin_may_use_it_too(self):
        res = _call(ADMIN, _Db(projects=_projects(), nfc_tags=_Coll([])), path=BOOTSTRAP)
        self.assertEqual(res.status_code, 200, res.text)


class TestTheGateIsNotAGeneralCreationPower(unittest.TestCase):

    def test_refused_when_an_active_tag_exists(self):
        tags = _Coll([{
            "_id": "t1", "tag_id": "04AABBCCDD", "project_id": PROJ,
            "status": "active", "is_deleted": False,
        }])
        res = _call(CP, _Db(projects=_projects(), nfc_tags=tags), path=BOOTSTRAP)
        self.assertEqual(res.status_code, 409, res.text)
        self.assertEqual(len(tags.inserts), 0)


class TestZeroActiveNotNoRows(unittest.TestCase):
    """The rule asks "zero ACTIVE tags", and the difference is load-bearing.

    A REOPENED SITE is the case. Marking a project for deletion sweeps its tags
    to status "project_closed"; restoring the project leaves them there. Those
    rows exist, and NOBODY CAN CHECK IN THROUGH THEM — /info and
    register_and_checkin both match status "active". A "no existing rows" rule
    would see them and refuse, stranding the CP on a site that genuinely has no
    working gate, which is the exact failure this endpoint exists for.
    """

    def test_a_project_closed_row_does_not_block(self):
        tags = _Coll([{
            "_id": "t1", "tag_id": "04AABBCCDD", "project_id": PROJ,
            "status": "project_closed", "is_deleted": False,
        }])
        res = _call(CP, _Db(projects=_projects(), nfc_tags=tags), path=BOOTSTRAP)
        self.assertEqual(res.status_code, 200,
                         f"a reopened site must be able to open a gate: {res.text}")

    def test_a_deleted_row_does_not_block(self):
        tags = _Coll([{
            "_id": "t1", "tag_id": "04AABBCCDD", "project_id": PROJ,
            "status": "active", "is_deleted": True,
        }])
        res = _call(CP, _Db(projects=_projects(), nfc_tags=tags), path=BOOTSTRAP)
        self.assertEqual(res.status_code, 200, res.text)

    def test_the_two_are_distinguishable(self):
        # Same fixture but for `status`. If someone rewrites the count as
        # "any row on this project", both of these go to 409.
        base = {"_id": "t1", "tag_id": "04AABBCCDD", "project_id": PROJ,
                "is_deleted": False}
        closed = _call(CP, _Db(projects=_projects(),
                               nfc_tags=_Coll([{**base, "status": "project_closed"}])),
                       path=BOOTSTRAP)
        active = _call(CP, _Db(projects=_projects(),
                               nfc_tags=_Coll([{**base, "status": "active"}])),
                       path=BOOTSTRAP)
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(active.status_code, 409)


class TestTheCpCanCloseTheirOwnMistake(unittest.TestCase):
    """A rule that lets someone act in an emergency and then traps them with
    the result is not a safety property. bootstrap refuses once a gate exists,
    so without a delete the CP's emergency power is a one-shot already spent.
    """

    def _tag(self, **over):
        row = {"_id": "t1", "tag_id": "qr-aabbccddeeff", "project_id": PROJ,
               "status": "active", "is_deleted": False,
               "created_by_role": "cp", "created_by": "cp1", "provisional": True}
        row.update(over)
        return row

    def _delete(self, user, tag_row, checkins=None):
        tags = _Coll([tag_row])
        db = _Db(projects=_projects(), nfc_tags=tags,
                 checkins=_Coll(checkins or []))
        res = _call(user, db, method="delete",
                    path=f"/api/projects/{PROJ}/checkin-points/{tag_row['tag_id']}")
        return res, tags

    def test_unused_and_theirs_is_removable(self):
        res, tags = self._delete(CP, self._tag())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIs(tags.docs[0]["is_deleted"], True)

    def test_any_cp_on_the_project_may_close_a_cp_gate(self):
        # Scoped to the PROJECT, not to the individual. Two CPs cover one site
        # across shifts, and "only the man who made it" would strand the other.
        res, _ = self._delete(CP_OTHER, self._tag())
        self.assertEqual(res.status_code, 200, res.text)

    def test_once_a_man_has_tapped_in_it_is_evidence(self):
        # A check-in is a 3301.11 record and it names this tag_id. The same
        # rule holds everywhere else a signed artifact exists, and it is not
        # relaxed because the row was created under an emergency.
        res, tags = self._delete(
            CP, self._tag(),
            checkins=[{"tag_id": "qr-aabbccddeeff", "project_id": PROJ}],
        )
        self.assertEqual(res.status_code, 409, res.text)
        self.assertIsNot(tags.docs[0].get("is_deleted"), True)

    def test_a_cp_may_not_remove_an_admins_gate(self):
        # Undoing your own mistake is not the same power as removing the gate
        # an admin programmed onto a chip in the field.
        res, tags = self._delete(CP, self._tag(created_by_role="admin",
                                               provisional=False))
        self.assertEqual(res.status_code, 403, res.text)
        self.assertIsNot(tags.docs[0].get("is_deleted"), True)

    def test_an_admin_is_not_bound_by_either_condition(self):
        res, tags = self._delete(
            ADMIN, self._tag(created_by_role="admin", provisional=False),
            checkins=[{"tag_id": "qr-aabbccddeeff", "project_id": PROJ}],
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIs(tags.docs[0]["is_deleted"], True)


class TestTheAdminSeesTheFlag(unittest.TestCase):
    """Read from the COLLECTION, never copied into the project's array.

    The array is a denormalized {tag_id, location} list. Two copies of one fact
    is the shape behind two live bugs already in followups.md — in both, one
    copy was updated and the one the screen renders was not. `provisional` is
    meant to change once an admin programs a chip, so it must not be stored
    where a later write can miss it.
    """

    def _get(self, tags_docs, array):
        projects = _Coll([{"_id": PROJ, "name": "A", "company_id": "companyA",
                           "nfc_tags": array}])
        db = _Db(projects=projects, nfc_tags=_Coll(tags_docs))

        async def _fake_user():
            return ADMIN

        orig_db, orig_company, orig_qid = server.db, server.get_user_company_id, server.to_query_id
        server.db = db
        server.get_user_company_id = lambda u: u.get("company_id")
        server.to_query_id = lambda v: v
        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            return TestClient(server.app).get(f"/api/projects/{PROJ}/nfc-tags")
        finally:
            server.db = orig_db
            server.get_user_company_id = orig_company
            server.to_query_id = orig_qid
            server.app.dependency_overrides.clear()

    def test_a_provisional_gate_is_flagged(self):
        res = self._get(
            [{"tag_id": "qr-aa", "project_id": PROJ, "provisional": True,
              "created_by_role": "cp", "is_deleted": False}],
            [{"tag_id": "qr-aa", "location": "Main Gate"}],
        )
        self.assertEqual(res.status_code, 200, res.text)
        row = res.json()[0]
        self.assertIs(row["provisional"], True)
        self.assertEqual(row["created_by_role"], "cp")
        self.assertEqual(row["location"], "Main Gate", "existing fields survive")

    def test_absent_means_not_provisional(self):
        # Every tag predating this feature was programmed onto a chip by an
        # admin, so the default has to be "real", never "unknown".
        res = self._get(
            [{"tag_id": "04AABB", "project_id": PROJ, "is_deleted": False}],
            [{"tag_id": "04AABB", "location": "Main Gate"}],
        )
        row = res.json()[0]
        self.assertIs(row["provisional"], False)
        self.assertEqual(row["created_by_role"], "admin")

    def test_the_flag_is_not_written_into_the_project_array(self):
        tags = _Coll([])
        projects = _projects()
        _call(CP, _Db(projects=projects, nfc_tags=tags), path=BOOTSTRAP)
        pushed = projects.docs[0]["nfc_tags"]
        # The push is {tag_id, location} exactly, as it was before.
        self.assertTrue(all(set(r) == {"tag_id", "location"} for r in pushed), pushed)


if __name__ == "__main__":
    unittest.main()
