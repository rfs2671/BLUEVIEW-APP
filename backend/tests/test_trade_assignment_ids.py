"""Stable ids on project.trade_assignments + soft-delete visibility.

PUT /api/projects/{id} replaces the whole trade_assignments array, so the
row ids CANNOT come from the client. update_project mints and merges them
server-side (_merge_trade_assignments). These tests pin:

  • an id survives a full PUT round-trip and is stable across PUTs
  • an id-less client PUT does NOT wipe the stored ids
  • a client-supplied id is never trusted
  • `id: None` never reaches Mongo (it would 500 the read-back, because
    ProjectResponse.trade_assignments is List[Dict[str, str]])
  • the soft-delete marker is a STRING — a bool in the array 500s the
    same read-back
  • rows the client omits are soft-deleted, never hard-deleted
  • inactive rows are hidden from every consumer that offers a NEW
    selection
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import server  # noqa: E402


# ── fakes ────────────────────────────────────────────────────────────────

class _Result:
    def __init__(self):
        self.inserted_id = "x"
        self.matched_count = 1
        self.modified_count = 1


class _StatefulProjects:
    """One project doc that update_one actually mutates, so a PUT can be
    read back the way the endpoint reads it back."""

    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, query=None, *a, **k):
        return dict(self.doc)

    async def update_one(self, q, u, *a, **k):
        self.doc.update(u.get("$set") or {})
        return _Result()


class _FakeCollection:
    def __init__(self):
        self._find_one = None
        self.updated = []
        self.inserted = []

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query) if callable(v) else v

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))
        return _Result()

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result()

    def last_set(self, field):
        for _q, u in reversed(self.updated):
            s = u.get("$set") or {}
            if field in s:
                return s[field]
        return None


class _FakeDb:
    def __init__(self, projects=None):
        self._c = {}
        if projects is not None:
            self._c["projects"] = projects

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


_BASE_PROJECT = {
    "_id": "proj1",
    "name": "Test Tower",
    "company_id": "co_test",
    "status": "active",
    "is_deleted": False,
}


def _project_doc(**over):
    d = dict(_BASE_PROJECT)
    d.update(over)
    return d


def _admin_client():
    user = {
        "_id": "admin_1", "id": "admin_1", "role": "admin",
        "company_id": "co_test", "account_status": "approved",
        "full_name": "Ada Admin", "assigned_projects": [],
    }

    async def _fake_user():
        return user

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    ov[server.get_admin_user] = _fake_user
    ov[server.require_approved] = _fake_user
    ov[server.require_project_access] = _fake_user
    return TestClient(server.app), ov.clear


def _put(store, body):
    client, cleanup = _admin_client()
    try:
        with patch.object(server, "db", _FakeDb(projects=store)):
            return client.put("/api/projects/proj1", json=body)
    finally:
        cleanup()


# ── id minting / merging ─────────────────────────────────────────────────

class TradeAssignmentIdTest(unittest.TestCase):

    def test_id_survives_a_full_put_round_trip(self):
        store = _StatefulProjects(_project_doc(trade_assignments=[]))
        resp = _put(store, {"trade_assignments": [
            {"trade": "Carpenter", "company": "Acme Co"},
        ]})
        self.assertEqual(resp.status_code, 200, resp.text)

        stored = store.doc["trade_assignments"]
        self.assertEqual(len(stored), 1)
        minted = stored[0]["id"]
        self.assertTrue(minted.startswith("srv_"), minted)

        # The response the client reads back carries the same id.
        body = resp.json()["trade_assignments"]
        self.assertEqual(body[0]["id"], minted)

        # And a second PUT echoing the row keeps it — not a fresh mint.
        resp2 = _put(store, {"trade_assignments": [
            {"trade": "Carpenter", "company": "Acme Co", "id": minted},
        ]})
        self.assertEqual(resp2.status_code, 200, resp2.text)
        self.assertEqual(store.doc["trade_assignments"][0]["id"], minted)

    def test_idless_client_put_does_not_wipe_ids(self):
        """The regression this whole mechanism exists for: $set replaces the
        array, so an older client that never learned about `id` would blank
        every id on the roster."""
        store = _StatefulProjects(_project_doc(trade_assignments=[
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_keepme"},
            {"trade": "Electrician", "company": "Volt LLC", "id": "srv_keeptoo"},
        ]))
        resp = _put(store, {"trade_assignments": [
            {"trade": "Carpenter", "company": "Acme Co"},
            {"trade": "Electrician", "company": "Volt LLC"},
        ]})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            [r["id"] for r in store.doc["trade_assignments"]],
            ["srv_keepme", "srv_keeptoo"],
        )

    def test_id_carried_forward_across_case_and_whitespace_edits(self):
        """Matching uses _roster_key — the SAME normalization the check-in
        strict-roster match uses — so a case-only edit is the same row."""
        store = _StatefulProjects(_project_doc(trade_assignments=[
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_keepme"},
        ]))
        _put(store, {"trade_assignments": [
            {"trade": "  carpenter ", "company": "ACME CO"},
        ]})
        rows = store.doc["trade_assignments"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "srv_keepme")
        # The submitted (stripped) casing is what gets STORED.
        self.assertEqual(rows[0]["trade"], "carpenter")

    def test_client_supplied_id_is_never_trusted(self):
        store = _StatefulProjects(_project_doc(trade_assignments=[]))
        _put(store, {"trade_assignments": [
            {"trade": "Plumber", "company": "Pipes Inc", "id": "attacker_id"},
        ]})
        row = store.doc["trade_assignments"][0]
        self.assertNotEqual(row["id"], "attacker_id")
        self.assertTrue(row["id"].startswith("srv_"))

    def test_no_none_value_ever_reaches_mongo(self):
        """`id: None` would pass the endpoint's top-level None filter and
        then 500 the ProjectResponse read-back on this same request."""
        store = _StatefulProjects(_project_doc(trade_assignments=[]))
        resp = _put(store, {"trade_assignments": [
            {"trade": "Mason", "company": "Stone Co", "id": None,
             "status": None},
        ]})
        self.assertEqual(resp.status_code, 200, resp.text)
        for row in store.doc["trade_assignments"]:
            for k, v in row.items():
                self.assertIsInstance(v, str, f"{k}={v!r} is not a str")
            self.assertTrue(row["id"])

    def test_duplicate_pairs_collapse_to_one_row(self):
        store = _StatefulProjects(_project_doc(trade_assignments=[]))
        _put(store, {"trade_assignments": [
            {"trade": "Roofer", "company": "Top Co"},
            {"trade": "roofer", "company": "top co"},
        ]})
        self.assertEqual(len(store.doc["trade_assignments"]), 1)


# ── soft delete ──────────────────────────────────────────────────────────

class SoftDeleteTest(unittest.TestCase):

    def test_status_inactive_is_persisted(self):
        store = _StatefulProjects(_project_doc(trade_assignments=[
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1"},
        ]))
        _put(store, {"trade_assignments": [
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1",
             "status": "inactive"},
        ]})
        row = store.doc["trade_assignments"][0]
        self.assertEqual(row["status"], "inactive")
        self.assertEqual(row["id"], "srv_1")

    def test_omitted_row_is_soft_deleted_not_dropped(self):
        store = _StatefulProjects(_project_doc(trade_assignments=[
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1"},
            {"trade": "Electrician", "company": "Volt LLC", "id": "srv_2"},
        ]))
        _put(store, {"trade_assignments": [
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1"},
        ]})
        rows = store.doc["trade_assignments"]
        self.assertEqual(len(rows), 2, "the omitted row was hard-deleted")
        gone = [r for r in rows if r["id"] == "srv_2"][0]
        self.assertEqual(gone["status"], "inactive")

    def test_reactivating_a_pair_reuses_its_row_and_id(self):
        store = _StatefulProjects(_project_doc(trade_assignments=[
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1",
             "status": "inactive"},
        ]))
        _put(store, {"trade_assignments": [
            {"trade": "Carpenter", "company": "Acme Co"},
        ]})
        rows = store.doc["trade_assignments"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "srv_1")
        self.assertNotIn("status", rows[0])

    def test_soft_delete_state_must_be_a_string_not_a_bool(self):
        """Why the marker is `status: "inactive"` and not `deleted: True`:
        ProjectResponse.trade_assignments is List[Dict[str, str]], so a bool
        (or a None) in a stored row fails validation — every later
        GET /api/projects/{id} would 500."""
        base = {
            "id": "p1", "name": "T", "trade_assignments": [
                {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1"},
            ],
        }
        # The string approach validates.
        ok = dict(base)
        ok["trade_assignments"] = [
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1",
             "status": "inactive"},
        ]
        self.assertEqual(
            server.ProjectResponse(**ok).trade_assignments[0]["status"],
            "inactive",
        )
        # A bool does not.
        bad = dict(base)
        bad["trade_assignments"] = [
            {"trade": "Carpenter", "company": "Acme Co", "deleted": True},
        ]
        with self.assertRaises(ValidationError):
            server.ProjectResponse(**bad)
        # Neither does a None id.
        bad_none = dict(base)
        bad_none["trade_assignments"] = [
            {"trade": "Carpenter", "company": "Acme Co", "id": None},
        ]
        with self.assertRaises(ValidationError):
            server.ProjectResponse(**bad_none)


# ── inactive rows are hidden from every selection consumer ───────────────

_MIXED_ROSTER = [
    {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1"},
    {"trade": "Electrician", "company": "Volt LLC", "id": "srv_2",
     "status": "inactive"},
]


class InactiveHiddenTest(unittest.TestCase):

    def test_active_assignments_helper_drops_only_inactive(self):
        rows = server._active_assignments({"trade_assignments": _MIXED_ROSTER})
        self.assertEqual([r["id"] for r in rows], ["srv_1"])
        # Rows are passed through UNMODIFIED — not rebuilt.
        self.assertIs(rows[0], _MIXED_ROSTER[0])

    def test_status_match_is_case_and_whitespace_tolerant(self):
        self.assertTrue(server._assignment_is_inactive({"status": " INACTIVE "}))
        self.assertFalse(server._assignment_is_inactive({"status": "active"}))
        self.assertFalse(server._assignment_is_inactive({}))

    def test_site_info_dropdown_hides_inactive(self):
        db = _FakeDb()
        db.nfc_tags.set_find_one({
            "tag_id": "t1", "project_id": "proj1", "status": "active",
            "location_description": "Gate A",
        })
        db.projects.set_find_one(_project_doc(trade_assignments=_MIXED_ROSTER))
        with patch.object(server, "db", db):
            resp = TestClient(server.app).get("/api/checkin/proj1/t1/info")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            resp.json()["trade_assignments"],
            [{"trade": "Carpenter", "company": "Acme Co"}],
        )

    def test_register_and_checkin_rejects_an_inactive_pair(self):
        db = _FakeDb()
        db.nfc_tags.set_find_one({
            "tag_id": "t1", "project_id": "proj1", "status": "active",
        })
        db.projects.set_find_one(_project_doc(trade_assignments=_MIXED_ROSTER))
        with patch.object(server, "db", db):
            resp = TestClient(server.app).post(
                "/api/checkin/register-and-checkin",
                json={
                    "project_id": "proj1", "tag_id": "t1", "name": "Jane",
                    "phone": "5551234567",
                    "trade": "Electrician", "company": "Volt LLC",
                },
            )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("not assigned to this project", resp.json()["detail"])

    def test_assign_trade_rejects_an_inactive_pair(self):
        db = _FakeDb()
        db.checkins.set_find_one({
            "_id": "chk1", "project_id": "proj1", "worker_id": "w1",
            "needs_trade_assignment": True,
        })
        db.projects.set_find_one(_project_doc(trade_assignments=_MIXED_ROSTER))
        db.workers.set_find_one({"_id": "w1", "name": "Jane", "trade": ""})

        user = {
            "_id": "u1", "id": "u1", "role": "admin", "company_id": "co_test",
            "full_name": "Ada Admin", "assigned_projects": [],
        }

        async def _fake_user():
            return user

        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            with patch.object(server, "db", db):
                resp = TestClient(server.app).post(
                    "/api/checkins/chk1/assign-trade",
                    json={"trade": "Electrician", "company": "Volt LLC"},
                )
        finally:
            server.app.dependency_overrides.clear()
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_flagged_roster_passthrough_hides_inactive(self):
        db = _FakeDb()
        db.projects.set_find_one(_project_doc(trade_assignments=_MIXED_ROSTER))

        class _FindCursor:
            def sort(self, *a, **k):
                return self

            def skip(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            async def to_list(self, *a, **k):
                return []

        db.checkins.find = lambda *a, **k: _FindCursor()
        db.workers.find = lambda *a, **k: _FindCursor()

        user = {
            "_id": "u1", "id": "u1", "role": "admin", "company_id": "co_test",
            "assigned_projects": [],
        }

        async def _fake_user():
            return user

        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            with patch.object(server, "db", db):
                resp = TestClient(server.app).get(
                    "/api/checkins/project/proj1/flagged",
                )
        finally:
            server.app.dependency_overrides.clear()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            [r["id"] for r in resp.json()["trade_assignments"]], ["srv_1"],
        )


if __name__ == "__main__":
    unittest.main()
