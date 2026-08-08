"""Tenant isolation for the two daily-log WRITE endpoints.

Neither route has {project_id} in its path, so neither can declare
`Depends(require_project_access)` and neither is reachable by the decorator
pins in test_tenant_isolation_writes.py. They call `_assert_project_access`
directly instead, and that is what these tests pin.

POST /daily-logs takes project_id in the BODY. Before the guard, any
authenticated caller could create a log under any project id — including one
that did not exist at all, which inserted a row with no company_id.

PUT /daily-logs/{log_id} was worse: no access check of any kind, and it $set
an arbitrary caller-supplied dict without popping project_id/company_id, so a
caller could RE-PARENT an existing log into another tenant.

Four directions per route, because a guard that 403s everyone is as broken as
one that 403s nobody:

  1. cross-company caller       -> 403
  2. own-company admin          -> works
  3. assigned (cross-company)   -> works   (branch 3 of the guard)
  4. site device, own project   -> works   (branch 1 — the kiosk must not break)
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


class _Result:
    def __init__(self, _id):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
        self.inserted = []
        self.updated = []

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query or {}) if callable(v) else v

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))
        return _Result("dl_new")

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result("dl1")

    def last_set(self):
        for _q, u in reversed(self.updated):
            if "$set" in u:
                return u["$set"]
        return {}


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


# The project every test authorizes against. Owned by co_a.
_PROJECT = {"_id": "proj1", "name": "Test Tower", "company_id": "co_a"}
# An existing daily log on proj1 / co_a, for the PUT tests.
_LOG = {
    "_id": "dl1", "project_id": "proj1", "company_id": "co_a",
    "date": "2026-07-20", "notes": "original", "worker_count": 3,
    "created_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
}


def _mk_db(*, project=_PROJECT, existing_log=_LOG, duplicate=None):
    db = _FakeDb()
    db.projects.set_find_one(lambda q: project)

    def _daily_logs(q):
        # The duplicate probe in create_daily_log filters on date; the by-id
        # reads in update_daily_log do not.
        if "date" in q:
            return duplicate
        return existing_log

    db.daily_logs.set_find_one(_daily_logs)
    return db


def _client(*, role="admin", company_id="co_a", user_id="u1",
            assigned_projects=None, site_mode=False, device_project_id=None):
    user = {
        "_id": user_id, "id": user_id, "role": role, "company_id": company_id,
        "full_name": "Ada Admin", "assigned_projects": assigned_projects or [],
    }
    if site_mode:
        user.update({
            "site_mode": True, "role": "site_device",
            "device_name": "Gate Tablet", "project_id": device_project_id,
        })

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _call(db, method, url, body, **kw):
    client, cleanup = _client(**kw)
    try:
        with patch.object(server, "db", db):
            return getattr(client, method)(url, json=body)
    finally:
        cleanup()


_NEW_LOG = {"project_id": "proj1", "date": "2026-07-21", "notes": "hello"}


class CreateDailyLogAccessTest(unittest.TestCase):
    """POST /daily-logs — project_id comes from the BODY."""

    def test_cross_company_caller_is_rejected(self):
        db = _mk_db()
        resp = _call(db, "post", "/api/daily-logs", _NEW_LOG, company_id="co_b")
        self.assertEqual(resp.status_code, 403, resp.text)
        # Nothing was written.
        self.assertEqual(db.daily_logs.inserted, [])

    def test_own_company_admin_succeeds(self):
        db = _mk_db()
        resp = _call(db, "post", "/api/daily-logs", _NEW_LOG)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.daily_logs.inserted), 1)

    def test_assigned_cross_company_user_succeeds(self):
        """Branch 3 of the guard — assigned contractors keep working."""
        db = _mk_db()
        resp = _call(db, "post", "/api/daily-logs", _NEW_LOG,
                     role="cp", company_id="co_b", assigned_projects=["proj1"])
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_site_device_on_its_own_project_succeeds(self):
        """Branch 1 — the kiosk must not be broken by the new guard."""
        db = _mk_db()
        resp = _call(db, "post", "/api/daily-logs", _NEW_LOG,
                     site_mode=True, device_project_id="proj1", company_id="co_a")
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_site_device_on_another_project_is_rejected(self):
        db = _mk_db()
        resp = _call(db, "post", "/api/daily-logs", _NEW_LOG,
                     site_mode=True, device_project_id="other", company_id="co_a")
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertEqual(db.daily_logs.inserted, [])

    def test_nonexistent_project_is_404_not_a_headless_insert(self):
        """The old code did `if project:` and inserted anyway, producing a row
        with no company_id that belonged to no tenant."""
        db = _mk_db(project=None)
        resp = _call(db, "post", "/api/daily-logs", _NEW_LOG)
        self.assertEqual(resp.status_code, 404, resp.text)
        self.assertEqual(db.daily_logs.inserted, [])

    def test_company_id_comes_from_the_project_not_the_body(self):
        db = _mk_db()
        resp = _call(db, "post", "/api/daily-logs",
                     {**_NEW_LOG, "company_id": "co_evil"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.daily_logs.inserted[0]["company_id"], "co_a")

    def test_access_is_checked_before_the_duplicate_probe(self):
        """A 409 would otherwise confirm that another tenant has a log on that
        project+date."""
        db = _mk_db(duplicate={"_id": "dl_other"})
        resp = _call(db, "post", "/api/daily-logs", _NEW_LOG, company_id="co_b")
        self.assertEqual(resp.status_code, 403, resp.text)


class UpdateDailyLogAccessTest(unittest.TestCase):
    """PUT /daily-logs/{log_id} — authorized against the STORED project id."""

    def test_cross_company_caller_is_rejected(self):
        db = _mk_db()
        resp = _call(db, "put", "/api/daily-logs/dl1", {"notes": "pwned"},
                     company_id="co_b")
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertEqual(db.daily_logs.updated, [])

    def test_own_company_admin_succeeds(self):
        db = _mk_db()
        resp = _call(db, "put", "/api/daily-logs/dl1", {"notes": "edited"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.daily_logs.last_set()["notes"], "edited")

    def test_assigned_cross_company_user_succeeds(self):
        db = _mk_db()
        resp = _call(db, "put", "/api/daily-logs/dl1", {"notes": "edited"},
                     role="cp", company_id="co_b", assigned_projects=["proj1"])
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_site_device_on_its_own_project_succeeds(self):
        db = _mk_db()
        resp = _call(db, "put", "/api/daily-logs/dl1", {"notes": "edited"},
                     site_mode=True, device_project_id="proj1", company_id="co_a")
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_body_project_id_cannot_reparent_the_log(self):
        """The guard reads the STORED project_id, and project_id is popped out
        of the $set dict, so neither the check nor the write can be steered."""
        db = _mk_db()
        resp = _call(db, "put", "/api/daily-logs/dl1",
                     {"project_id": "proj_evil", "notes": "edited"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotIn("project_id", db.daily_logs.last_set())

    def test_body_company_id_cannot_reparent_the_log(self):
        db = _mk_db()
        resp = _call(db, "put", "/api/daily-logs/dl1",
                     {"company_id": "co_evil", "notes": "edited"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotIn("company_id", db.daily_logs.last_set())

    def test_naming_an_accessible_project_does_not_unlock_a_foreign_log(self):
        """The attack the stored-id rule exists to stop: caller belongs to co_b
        and names a co_b project in the body, but the log lives on co_a."""
        db = _mk_db()
        resp = _call(db, "put", "/api/daily-logs/dl1",
                     {"project_id": "proj_co_b", "notes": "pwned"},
                     company_id="co_b")
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertEqual(db.daily_logs.updated, [])

    def test_missing_log_is_404(self):
        db = _mk_db(existing_log=None)
        resp = _call(db, "put", "/api/daily-logs/dl1", {"notes": "x"})
        self.assertEqual(resp.status_code, 404, resp.text)


class GuardWiringTest(unittest.TestCase):
    """`require_project_access` must stay a thin wrapper over the extracted
    helper — 45 existing Depends sites rely on it being unchanged."""

    def test_require_project_access_delegates_to_the_helper(self):
        import ast
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "require_project_access"
        )
        body = [s for s in fn.body if not isinstance(s, ast.Expr)]
        self.assertEqual(len(body), 1, "wrapper grew a second statement")
        self.assertIn("_assert_project_access", ast.unparse(body[0]))

    def test_helper_is_not_a_fastapi_dependency(self):
        """It takes current_user as a plain argument, so callers must pass it.
        A Depends() default here would silently make body-param callers pass
        None."""
        import inspect
        sig = inspect.signature(server._assert_project_access)
        self.assertEqual(
            list(sig.parameters), ["project_id", "current_user"],
        )
        for p in sig.parameters.values():
            self.assertIs(p.default, inspect.Parameter.empty)


if __name__ == "__main__":
    unittest.main()
