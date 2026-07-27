"""Tenant isolation — BATCH 1 (read endpoints).

Before require_project_access, project-scoped routes put the {project_id} path
parameter straight into the query with no ownership check, so any authenticated
user could read another company's rosters, reports, daily logs, safety staff and
kiosk credentials by supplying that project's id.

These tests pin the invariant in BOTH directions, because a guard that 403s
everyone is as broken as one that 403s nobody:

  1. company A CANNOT reach company B's project            -> 403
  2. company A CAN still reach its own project             -> not 403
  3. a user ASSIGNED to a project reaches it cross-company -> not 403
  4. a SITE DEVICE reaches its own project, not another    -> not 403 / 403
  5. a missing project is 404, not 403 (no id confirmation)

Most cases exercise require_project_access directly — it IS the authorization
boundary, every batch-1 route delegates to it, and calling it directly keeps
the test independent of each route's unrelated payload plumbing. Two further
cases drive a real patched route through TestClient, because "the dependency
authorizes correctly" and "the route still serves a legitimate request" are
different claims: a wiring mistake would pass the unit tests and 500 in
production.

A table-driven case asserts every batch-1 route still DECLARES the dependency,
so silently dropping it fails CI rather than quietly reopening the hole.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi import HTTPException  # noqa: E402

PROJECT_A = {"_id": "projA", "company_id": "companyA", "name": "A Site"}
PROJECT_B = {"_id": "projB", "company_id": "companyB", "name": "B Site"}

USER_A_ADMIN = {"_id": "ua", "role": "admin", "company_id": "companyA", "assigned_projects": []}
USER_A_WORKER = {"_id": "uw", "role": "worker", "company_id": "companyA", "assigned_projects": []}
USER_B_ADMIN = {"_id": "ub", "role": "admin", "company_id": "companyB", "assigned_projects": []}
# Cross-company contractor explicitly assigned to A's project.
USER_C_ASSIGNED = {"_id": "uc", "role": "cp", "company_id": "companyC", "assigned_projects": ["projA"]}
# Kiosk provisioned for A's project: company derived server-side by get_current_user.
DEVICE_A = {"_id": "dev1", "site_mode": True, "role": "site_device",
            "project_id": "projA", "company_id": "companyA"}


def _db_with(projects):
    async def _find_one(q, *a, **kw):
        pid = q.get("_id")
        return projects.get(str(pid))
    db = MagicMock()
    db.projects = MagicMock()
    db.projects.find_one = AsyncMock(side_effect=_find_one)
    return db


def _call(user, project_id, projects=None):
    from server import require_project_access
    projects = projects if projects is not None else {"projA": PROJECT_A, "projB": PROJECT_B}
    with patch("server.db", _db_with(projects)), \
         patch("server.to_query_id", lambda v: v):
        return asyncio.run(require_project_access(project_id=project_id, current_user=user))


class TestCrossTenantDenied(unittest.TestCase):
    def test_company_a_admin_cannot_reach_company_b_project(self):
        with self.assertRaises(HTTPException) as ctx:
            _call(USER_A_ADMIN, "projB")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_company_b_admin_cannot_reach_company_a_project(self):
        with self.assertRaises(HTTPException) as ctx:
            _call(USER_B_ADMIN, "projA")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_worker_cannot_reach_other_company_project(self):
        with self.assertRaises(HTTPException) as ctx:
            _call(USER_A_WORKER, "projB")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_user_with_no_company_cannot_reach_any_project(self):
        """A null company_id must not match a project whose company_id is also
        falsy-ish; no company means no tenant claim."""
        nobody = {"_id": "un", "role": "worker", "company_id": None, "assigned_projects": []}
        with self.assertRaises(HTTPException) as ctx:
            _call(nobody, "projA")
        self.assertEqual(ctx.exception.status_code, 403)


class TestLegitimateAccessStillWorks(unittest.TestCase):
    """The half that proves the fix did not just break the product."""

    def test_company_a_admin_reaches_own_project(self):
        self.assertEqual(_call(USER_A_ADMIN, "projA")["_id"], "projA")

    def test_company_a_worker_reaches_own_project(self):
        # NOT admin-gated: a company's own staff must keep read access.
        self.assertEqual(_call(USER_A_WORKER, "projA")["_id"], "projA")

    def test_company_b_admin_reaches_own_project(self):
        self.assertEqual(_call(USER_B_ADMIN, "projB")["_id"], "projB")

    def test_assigned_user_reaches_project_across_company(self):
        self.assertEqual(_call(USER_C_ASSIGNED, "projA")["_id"], "projA")

    def test_assigned_user_still_blocked_elsewhere(self):
        with self.assertRaises(HTTPException) as ctx:
            _call(USER_C_ASSIGNED, "projB")
        self.assertEqual(ctx.exception.status_code, 403)


class TestSiteDeviceCheckInPath(unittest.TestCase):
    """The kiosk must keep working — this guard sits in front of check-in."""

    def test_device_reaches_its_own_project(self):
        self.assertEqual(_call(DEVICE_A, "projA")["_id"], "projA")

    def test_device_cannot_reach_another_project(self):
        with self.assertRaises(HTTPException) as ctx:
            _call(DEVICE_A, "projB")
        self.assertEqual(ctx.exception.status_code, 403)


class TestMissingProject(unittest.TestCase):
    def test_unknown_project_is_404_not_403(self):
        with self.assertRaises(HTTPException) as ctx:
            _call(USER_A_ADMIN, "nope")
        self.assertEqual(ctx.exception.status_code, 404)


class TestEveryBatch1RouteAdoptedTheGuard(unittest.TestCase):
    """Table-driven: if a batch-1 route loses the dependency, this fails.

    Guards against the exact failure mode that caused the original hole —
    scoping that is opt-in and silently dropped."""

    BATCH_1 = [
        "/checkins/project/{project_id}",
        "/checkins/project/{project_id}/active",
        "/checkins/project/{project_id}/today",
        "/logbooks/project/{project_id}/checkins-today",
        "/projects/{project_id}/site-devices",
        "/projects/{project_id}/nfc-tags",
        "/reports/project/{project_id}",
        "/daily-logs/project/{project_id}",
        "/projects/{project_id}/safety-staff",
        "/projects/{project_id}/checklists",
        "/logbooks/project/{project_id}/submitted",
        "/cs/project/{project_id}",
    ]

    def test_batch1_routes_depend_on_require_project_access(self):
        import server
        by_path = {}
        for r in server.app.routes:
            path = getattr(r, "path", "")
            if path:
                by_path.setdefault(path.replace("/api", "", 1), []).append(r)

        missing = []
        for path in self.BATCH_1:
            routes = by_path.get(path) or []
            if not routes:
                missing.append(f"{path} (route not found)")
                continue
            ok = False
            for r in routes:
                deps = getattr(getattr(r, "dependant", None), "dependencies", []) or []
                names = [getattr(d.call, "__name__", "") for d in deps if d.call]
                # nested one level: the dependency is declared on the handler
                for d in deps:
                    names += [getattr(sd.call, "__name__", "") for sd in (d.dependencies or []) if sd.call]
                if "require_project_access" in names:
                    ok = True
                    break
            if not ok:
                missing.append(path)

        self.assertEqual(
            missing, [],
            "these project-scoped routes lost require_project_access — "
            "cross-tenant reads are open again on: " + ", ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()


# ── End-to-end: the guard through the real ASGI stack ────────────────────────
# The tests above call require_project_access directly. This one drives an
# actual patched route through TestClient, because "the dependency returns the
# project" and "the route still serves a legitimate request" are different
# claims — a wiring mistake (wrong param name, duplicate declaration, ordering)
# would pass the unit tests and 500 in production.
class TestPatchedRouteEndToEnd(unittest.TestCase):
    ROUTE = "/api/checkins/project/projA/active"

    def _client(self, user, projects):
        from fastapi.testclient import TestClient
        import server
        server.app.dependency_overrides[server.get_current_user] = lambda: user
        return TestClient(server.app), server

    def _run(self, user):
        projects = {"projA": PROJECT_A, "projB": PROJECT_B}
        client, server = self._client(user, projects)

        class _Cursor:
            async def to_list(self, *a, **kw):
                return []

        db = _db_with(projects)
        db.checkins = MagicMock()
        db.checkins.find = MagicMock(return_value=_Cursor())
        db.workers = MagicMock()
        db.workers.find = MagicMock(return_value=_Cursor())
        try:
            with patch("server.db", db), patch("server.to_query_id", lambda v: v):
                return client.get(self.ROUTE)
        finally:
            server.app.dependency_overrides.clear()

    def test_own_company_gets_200_through_the_stack(self):
        r = self._run(USER_A_ADMIN)
        self.assertEqual(r.status_code, 200, r.text[:300])

    def test_cross_tenant_gets_403_through_the_stack(self):
        r = self._run(USER_B_ADMIN)
        self.assertEqual(r.status_code, 403, r.text[:300])
