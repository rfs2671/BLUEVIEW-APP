"""GET /logbooks/{logbook_id} — the by-id read must be authorized.

It used to match on `_id` alone: no company, no project, no is_deleted. Any
authenticated user could read any company's logbook — and any soft-deleted
one — from a guessed or harvested ObjectId.

`Depends(require_project_access)` is not usable here: there is no
{project_id} in the path for FastAPI to resolve. The endpoint uses the by-id
idiom instead (load doc -> load its project -> authorize), with
`user_can_act_on_project`, the same helper the check-in by-id endpoints use.

SITE DEVICES: `user_can_act_on_project` has no site-device branch, so a
kiosk token gets 403 here. That is asserted below as INTENDED, not incidental
— no site-device flow reaches this route. The kiosk's only logbook read is
/logbooks/project/{id}/submitted (frontend/app/site/logbooks.jsx:175), which
carries Depends(require_project_access) and its own site-device branch. The
one caller of this route in the repo, logbooksAPI.getById
(frontend/src/utils/api.js:815-818), has no call sites at all.
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


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
        self.queries = []

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        self.queries.append(query or {})
        v = self._find_one
        return v(query or {}) if callable(v) else v


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection(n)
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


_LOG = {
    "_id": "lb1", "project_id": "proj1", "company_id": "co_a",
    "log_type": "pre_shift", "date": "2026-07-20",
    "data": {"workers": [{"name": "Jane"}]},
    "created_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
}
_PROJECT = {"_id": "proj1", "name": "Test Tower", "company_id": "co_a"}


def _mk_db(*, logbook=_LOG, project=_PROJECT):
    db = _FakeDb()
    # Honour the is_deleted filter so a soft-deleted doc really disappears.
    def _logbooks(q):
        if logbook is None:
            return None
        if "is_deleted" in q and logbook.get("is_deleted") is True:
            return None
        return logbook

    db.logbooks.set_find_one(_logbooks)
    db.projects.set_find_one(lambda q: project)
    return db


def _get(db, *, role="admin", company_id="co_a",
         assigned_projects=None, site_mode=False):
    user = {
        "_id": "u1", "id": "u1", "role": role, "company_id": company_id,
        "full_name": "Ada Admin", "assigned_projects": assigned_projects or [],
    }
    if site_mode:
        user.update({"site_mode": True, "role": "site_device",
                     "project_id": "proj1"})

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            return TestClient(server.app).get("/api/logbooks/lb1")
    finally:
        server.app.dependency_overrides.clear()


class LogbookByIdGuardTest(unittest.TestCase):

    # ── the hole is closed ───────────────────────────────────────────────

    def test_cross_company_admin_is_rejected(self):
        resp = _get(_mk_db(), company_id="co_b")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_unassigned_cp_is_rejected(self):
        resp = _get(_mk_db(), role="cp", company_id="co_b",
                    assigned_projects=["other"])
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_worker_role_is_rejected(self):
        resp = _get(_mk_db(), role="worker", company_id="co_a")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_logbook_with_no_project_is_rejected(self):
        """A doc whose project is missing or deleted cannot be authorized, so
        it must not fall through to a 200."""
        resp = _get(_mk_db(project=None))
        self.assertEqual(resp.status_code, 403, resp.text)

    # ── the customer is not broken ───────────────────────────────────────

    def test_same_company_admin_succeeds(self):
        resp = _get(_mk_db())
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["project_id"], "proj1")

    def test_same_company_owner_succeeds(self):
        resp = _get(_mk_db(), role="owner")
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_assigned_cp_succeeds_across_companies(self):
        resp = _get(_mk_db(), role="cp", company_id="co_b",
                    assigned_projects=["proj1"])
        self.assertEqual(resp.status_code, 200, resp.text)

    # ── soft-deleted rows ────────────────────────────────────────────────

    def test_soft_deleted_logbook_is_404(self):
        resp = _get(_mk_db(logbook={**_LOG, "is_deleted": True}))
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_read_filters_is_deleted(self):
        db = _mk_db()
        _get(db)
        self.assertEqual(db.logbooks.queries[0].get("is_deleted"),
                         {"$ne": True})

    def test_missing_logbook_is_404(self):
        resp = _get(_mk_db(logbook=None))
        self.assertEqual(resp.status_code, 404, resp.text)

    # ── the site-device consequence, asserted as intended ────────────────

    def test_site_device_is_rejected_and_that_is_intended(self):
        """user_can_act_on_project has no site-device branch. No kiosk flow
        calls this route (the kiosk reads /logbooks/project/{id}/submitted),
        so this 403 breaks nothing. Pinned so the day a kiosk caller IS added,
        this test fails and forces the branch to be added deliberately."""
        resp = _get(_mk_db(), site_mode=True, company_id="co_a")
        self.assertEqual(resp.status_code, 403, resp.text)


if __name__ == "__main__":
    unittest.main()
