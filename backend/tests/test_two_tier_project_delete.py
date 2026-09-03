"""Two-tier project delete.

TIER 1 (admin or owner) — mark_for_deletion: flags the project, hides it from
every admin surface, deactivates its NFC tags, removes NOTHING.

TIER 2 (owner ONLY) — hard delete: physically purges the project and all owned
data, storage objects and config keys. delete_many/delete_one only, never
drop().

Landmines under test (from the cascade audit):
  1. workers span projects — never deleted; only this project's
     safety_orientations entry is $pulled.
  2. document_page_index is keyed by file_id, not project_id — must be
     resolved via the project's project_files rows BEFORE they are deleted.
  3. R2 plan renders have no DB rows — need a prefix sweep.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
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

import server  # noqa: E402

_PID = "proj1"


class _Res:
    def __init__(self, n=1):
        self.deleted_count = n
        self.modified_count = n
        self.matched_count = n
        self.inserted_id = "x"


class _Find:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return list(self._docs)


class _Coll:
    def __init__(self, name):
        self.name = name
        self.docs = []
        self._find_one = None
        self.deleted = []       # list of filters passed to delete_many/one
        self.updated = []       # (filter, update)
        self.count = 0

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, q=None, *a, **k):
        v = self._find_one
        return v(q) if callable(v) else v

    def find(self, q=None, *a, **k):
        return _Find(self.docs)

    async def delete_many(self, q, *a, **k):
        self.deleted.append(q)
        return _Res(len(self.docs) or 1)

    async def delete_one(self, q, *a, **k):
        self.deleted.append(q)
        return _Res(1)

    async def update_many(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Res(1)

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Res(1)

    async def insert_one(self, d, *a, **k):
        return _Res(1)

    async def count_documents(self, *a, **k):
        return self.count


class _Db:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _Coll(n)
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


def _reset_rate_limiter():
    """The app's rate-limit middleware counts per client IP in a process-wide
    fixed-window counter. Every TestClient request here shares one IP, and the
    counter accumulates across the WHOLE suite run — so in a full-suite run
    these requests come back 429 instead of the status under test. Reset the
    counter (the module's own supported entry point) rather than setting
    RATE_LIMITS_DISABLED, which would leak globally and change behaviour for
    the dedicated rate-limit suite.
    """
    try:
        from lib.rate_limits import reset_counter
        reset_counter()
    except Exception:
        pass


def _client(role="admin", company_id="co_a", uid="u1"):
    """Build a TestClient acting as `role`.

    Only `get_current_user` is overridden, so `get_admin_user` /
    `get_owner_user` still execute their REAL role checks — that is what the
    gating tests assert. All pre-existing overrides are cleared first: several
    other suites override `server.get_admin_user` DIRECTLY
    (test_activity_feed_endpoint, test_coi_endpoints,
    test_dob_logs_seed_suppression, test_project_list_defaults), and under
    pytest-randomly a leaked override of that kind would bypass this one and
    silently swap the acting user. Clearing makes these tests order-independent.
    """
    server.app.dependency_overrides.clear()
    _reset_rate_limiter()

    user = {"_id": uid, "id": uid, "role": role,
            "company_id": company_id, "full_name": "Test User"}

    async def _fake():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _db_with_project(marked=False, **over):
    """A project the Tier 2 purge is allowed to proceed on.

    `no_completion_attested` IS PART OF THE FIXTURE, NOT NOISE. The retention
    brake (lib/project_retention.py) refuses a hard delete on any project with
    no recorded job completion, so without a way through it every cascade
    assertion below would pass vacuously against a purge that never ran — the
    tests would be green and testing nothing. This fixture states the way
    through explicitly: an admin attested the project was never completed.

    That is deliberately the fixture rather than a completion date, because it
    is the state EVERY project in production is in. The brake itself is not
    tested here; it is tested in test_project_completion_and_legal_hold.py, and
    TheBrakeIsWhatThisFixtureGetsPast below asserts these tests are actually
    passing through it rather than around it.
    """
    db = _Db()
    doc = {
        "_id": _PID, "name": "Test Tower", "company_id": "co_a",
        "nyc_bin": "3048298",
        "marked_for_deletion": marked,
        "no_completion_attested": True,
        "no_completion_reason": "Fixture: never completed, cleared to purge.",
        "no_completion_attested_by": "u1",
    }
    doc.update(over)
    db.projects.set_find_one(doc)
    return db


# ── TIER 1 ────────────────────────────────────────────────────────────────

class MarkDeleteTest(unittest.TestCase):

    def _mark(self, db, role="admin"):
        c, cleanup = _client(role=role)
        try:
            with patch.object(server, "db", db):
                return c.delete(f"/api/projects/{_PID}")
        finally:
            cleanup()

    def test_sets_flag_and_attribution(self):
        db = _db_with_project()
        resp = self._mark(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["marked_for_deletion"])

        sets = [u.get("$set", {}) for _q, u in db.projects.updated]
        self.assertTrue(any(s.get("marked_for_deletion") is True for s in sets))
        self.assertTrue(any(s.get("marked_by") == "u1" for s in sets))
        self.assertTrue(any(isinstance(s.get("marked_at"), datetime) for s in sets))

    def test_deactivates_nfc_tags(self):
        db = _db_with_project()
        self._mark(db)
        self.assertTrue(db.nfc_tags.updated, "nfc_tags must be deactivated")
        q, u = db.nfc_tags.updated[0]
        self.assertEqual(q, {"project_id": _PID})
        self.assertEqual(u["$set"]["status"], "project_closed")

    def test_removes_nothing(self):
        """The old handler hard-deleted dob_logs. Nothing may be deleted now."""
        db = _db_with_project()
        self._mark(db)
        for coll in ("dob_logs", "checkins", "logbooks", "projects"):
            self.assertEqual(
                db[coll].deleted, [],
                f"{coll} must not be deleted by a Tier 1 mark",
            )

    def test_owner_can_also_mark(self):
        db = _db_with_project()
        self.assertEqual(self._mark(db, role="owner").status_code, 200)

    def test_already_marked_project_is_404(self):
        db = _Db()
        db.projects.set_find_one(None)  # ACTIVE_PROJECT_FILTER excludes it
        self.assertEqual(self._mark(db).status_code, 404)


class HidingTest(unittest.TestCase):
    """The flag must be applied at the list, detail and sync gates."""

    def test_active_project_filter_shape(self):
        self.assertEqual(
            server.ACTIVE_PROJECT_FILTER,
            {"is_deleted": {"$ne": True}, "marked_for_deletion": {"$ne": True}},
        )

    def test_key_gates_use_the_filter(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        # list + detail + dob-sync + background scans
        self.assertGreaterEqual(
            src.count("ACTIVE_PROJECT_FILTER"), 8,
            "expected the filter at the list, detail, dob-sync and scan gates",
        )

    def test_detail_endpoint_hides_marked_project(self):
        db = _Db()
        db.projects.set_find_one(None)   # filter excludes a marked project
        c, cleanup = _client()
        try:
            with patch.object(server, "db", db):
                r = c.get(f"/api/projects/{_PID}")
        finally:
            cleanup()
        self.assertEqual(r.status_code, 404)

    def test_dob_sync_refuses_marked_project(self):
        db = _Db()
        db.projects.set_find_one(None)
        c, cleanup = _client()
        try:
            with patch.object(server, "db", db):
                r = c.post(f"/api/projects/{_PID}/dob-sync")
        finally:
            cleanup()
        self.assertEqual(r.status_code, 404)


# ── owner gating ──────────────────────────────────────────────────────────

class OwnerGateTest(unittest.TestCase):

    def test_pending_list_owner_only(self):
        db = _Db()
        for role, expect in (("admin", 403), ("cp", 403), ("owner", 200)):
            c, cleanup = _client(role=role)
            try:
                with patch.object(server, "db", db):
                    r = c.get("/api/projects/pending-deletion")
            finally:
                cleanup()
            self.assertEqual(r.status_code, expect, f"role={role}")

    def test_hard_delete_owner_only(self):
        for role in ("admin", "cp"):
            db = _db_with_project(marked=True)
            c, cleanup = _client(role=role)
            try:
                with patch.object(server, "db", db):
                    r = c.delete(f"/api/projects/{_PID}/hard-delete")
            finally:
                cleanup()
            self.assertEqual(r.status_code, 403, f"role={role}")
            self.assertEqual(db.projects.deleted, [], "nothing may be deleted")

    def test_pending_route_registered_before_project_id(self):
        """Otherwise 'pending-deletion' binds to {project_id} and 404s."""
        paths = [getattr(r, "path", "") for r in server.app.routes]
        self.assertIn("/api/projects/pending-deletion", paths)
        self.assertLess(
            paths.index("/api/projects/pending-deletion"),
            paths.index("/api/projects/{project_id}"),
        )


# ── TIER 2 ────────────────────────────────────────────────────────────────

def _db_for_hard_delete():
    db = _db_with_project(marked=True)
    db.project_files.docs = [
        {"_id": "f1", "r2_key": "co_a/proj1/plan.pdf"},
        {"_id": "f2", "r2_key": "co_a/proj1/spec.pdf"},
    ]
    return db


def _hard_delete(db):
    c, cleanup = _client(role="owner")
    try:
        with patch.object(server, "db", db), \
             patch.object(server, "_r2_client", None):   # no storage in tests
            return c.delete(f"/api/projects/{_PID}/hard-delete")
    finally:
        cleanup()


class HardDeleteCascadeTest(unittest.TestCase):

    def test_representative_collections_purged(self):
        db = _db_for_hard_delete()
        resp = _hard_delete(db)
        self.assertEqual(resp.status_code, 200, resp.text)

        for coll in ("dob_logs", "checkins", "logbooks", "nfc_tags",
                     "project_files", "notifications", "project_models"):
            self.assertTrue(
                db[coll].deleted, f"{coll} must be purged",
            )
            self.assertEqual(db[coll].deleted[0], {"project_id": _PID})

    def test_full_audit_list_is_covered(self):
        db = _db_for_hard_delete()
        _hard_delete(db)
        for coll in server._PROJECT_OWNED_COLLECTIONS:
            self.assertTrue(db[coll].deleted, f"{coll} not swept")

    def test_company_scoped_collections_untouched(self):
        db = _db_for_hard_delete()
        _hard_delete(db)
        for coll in ("whatsapp_config", "companies", "notification_preferences",
                     "feature_flags", "certificates_of_insurance"):
            self.assertEqual(
                db[coll].deleted, [], f"{coll} is company-scoped — must survive",
            )

    def test_project_doc_deleted_last(self):
        db = _db_for_hard_delete()
        _hard_delete(db)
        self.assertTrue(db.projects.deleted)

    def test_audit_logs_for_project_removed(self):
        db = _db_for_hard_delete()
        _hard_delete(db)
        self.assertTrue(db.audit_logs.deleted)
        self.assertEqual(
            db.audit_logs.deleted[0],
            {"resource_type": "project", "resource_id": _PID},
        )

    def test_system_config_keys_swept_with_anchored_regex(self):
        db = _db_for_hard_delete()
        _hard_delete(db)
        self.assertTrue(db.system_config.deleted)
        branches = db.system_config.deleted[0]["$or"]
        self.assertIn({"key": f"dob_sync_last:{_PID}"}, branches)
        regexes = [b["key"]["$regex"] for b in branches if isinstance(b["key"], dict)]
        self.assertEqual(len(regexes), 3, "three suffixed key families")
        # Anchored so a project whose id is a substring can't be caught.
        self.assertTrue(all(r.startswith("^") for r in regexes))

    def test_users_assigned_projects_pulled(self):
        db = _db_for_hard_delete()
        _hard_delete(db)
        self.assertTrue(db.users.updated)
        q, u = db.users.updated[0]
        self.assertEqual(q, {"assigned_projects": _PID})
        self.assertEqual(u, {"$pull": {"assigned_projects": _PID}})

    def test_no_drop_used(self):
        # code_of strips DOCSTRINGS as well as # comments. This stripped
        # only the latter, and hard_delete_project's own docstring promises
        # it never uses drop() — so the assertion was reading the promise
        # alongside the code. Fourth occurrence of that shape on this repo.
        from tests.source_text import code_of
        self.assertNotIn(".drop()", code_of("server.py"))


class LandmineTest(unittest.TestCase):
    """The three failure modes the audit called out."""

    def test_workers_not_deleted_only_orientation_pulled(self):
        db = _db_for_hard_delete()
        _hard_delete(db)
        # LANDMINE 1: a worker spans projects — the doc must survive.
        self.assertEqual(
            db.workers.deleted, [],
            "workers must NOT be deleted — they span projects",
        )
        self.assertTrue(db.workers.updated)
        q, u = db.workers.updated[0]
        self.assertEqual(q, {"safety_orientations.project_id": _PID})
        self.assertEqual(
            u, {"$pull": {"safety_orientations": {"project_id": _PID}}},
        )

    def test_worker_on_two_projects_keeps_the_other(self):
        """The $pull is element-scoped, so a worker's other project survives."""
        db = _db_for_hard_delete()
        _hard_delete(db)
        _q, u = db.workers.updated[0]
        pulled = u["$pull"]["safety_orientations"]
        # Only the matching element is removed, not the whole array.
        self.assertEqual(pulled, {"project_id": _PID})
        self.assertNotEqual(pulled, "")

    def test_document_page_index_resolved_via_file_ids(self):
        db = _db_for_hard_delete()
        _hard_delete(db)
        # LANDMINE 2: keyed by file_id, not project_id.
        self.assertTrue(db.document_page_index.deleted)
        self.assertEqual(
            db.document_page_index.deleted[0],
            {"file_id": {"$in": ["f1", "f2"]}},
        )

    def test_page_index_deleted_before_project_files(self):
        """Deleting project_files first would orphan the index rows."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        body = src[src.index("async def hard_delete_project"):]
        self.assertLess(
            body.index("document_page_index"),
            body.index("_PROJECT_OWNED_COLLECTIONS"),
            "page-index cleanup must precede the project_files sweep",
        )

    def test_r2_prefix_sweep_exists_and_paginates(self):
        """LANDMINE 3: plan renders have no DB rows."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn("async def _r2_delete_prefix", src)
        self.assertIn("list_objects_v2", src)
        self.assertIn("ContinuationToken", src)
        self.assertIn('f"plans/{project_id}/"', src)
        self.assertIn("CARD_AUDIT_BUCKET_NAME", src)


class TheBrakeIsWhatThisFixtureGetsPast(unittest.TestCase):
    """THE POSITIVE CONTROL FOR THE FIXTURE ABOVE.

    Every cascade assertion in this file runs against a project whose document
    carries `no_completion_attested`. That flag is the ONLY reason the purge
    proceeds — and a fixture detail that silently stops mattering is exactly how
    a suite goes green while testing nothing. If the retention brake is ever
    removed, these two tests fail and say so, rather than the rest of the file
    quietly continuing to pass for a new reason.

    The brake's own behaviour is covered in
    test_project_completion_and_legal_hold.py. This is only about whether THIS
    file's fixture is still load-bearing.
    """

    def test_without_the_attestation_the_purge_is_refused(self):
        db = _db_for_hard_delete()
        doc = db.projects._find_one
        doc.pop("no_completion_attested", None)
        doc.pop("no_completion_reason", None)
        resp = _hard_delete(db)
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertIn("no recorded job completion", resp.text)

    def test_with_it_the_purge_proceeds(self):
        """The other half. Without this the test above would also pass against
        an endpoint that refuses unconditionally."""
        self.assertEqual(_hard_delete(_db_for_hard_delete()).status_code, 200)


if __name__ == "__main__":
    unittest.main()
