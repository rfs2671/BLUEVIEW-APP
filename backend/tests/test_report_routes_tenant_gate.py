"""Tenant isolation on the three report sidecar routes.

    GET /reports/project/{project_id}/preview/{date}
    GET /reports/project/{project_id}/history
    GET /reports/project/{project_id}/logs

WHAT WAS OPEN. All three gated cross-company access with

    if role == "admin" and project.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Access denied")

`role == "owner"` never reaches the comparison. And /auth/register FORCES
role = "owner" on every self-serve signup — its own comment says so, and says
in as many words that an approved owner of company A reaching company B is a
tenant-scoping defect tracked separately. So the guard was inert for exactly
the role every customer account holds: any approved self-serve account could
read any other company's filed logbooks, headcount and full send history by
supplying a project id. GET .../preview/{date} additionally carried no
require_approved and no require_project_access at all.

WHY THERE IS NO PLATFORM-OPERATOR BRANCH HERE. The operator's cross-company
carve-out lives on LIST endpoints (GET /projects, GET /workers) and on the
explicit /owner/* routes. Both `project_access_ok` and `_assert_worker_access`
say in comments that single-resource routes do not grant it. The decisive
precedent is next door: /reports/project/{id}/date/{date} and its /pdf twin —
the FULL report — already carry require_project_access with no operator
branch, so nobody could read a foreign company's report yesterday. Only these
three metadata sidecars leaked. Closing them takes nothing away that the full
report did not already refuse.

BOTH DIRECTIONS, because a guard that 403s everyone is as broken as one that
403s nobody: company A's owner is refused B's project, and still served their
own.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi.testclient import TestClient  # noqa: E402

PROJECT_A = {"_id": "projA", "company_id": "companyA", "name": "A Site"}
PROJECT_B = {"_id": "projB", "company_id": "companyB", "name": "B Site"}
# Marked for deletion by an admin: invisible and inert everywhere except the
# owner's pending-deletion review list. ACTIVE_PROJECT_FILTER excludes it.
PROJECT_A_MARKED = {
    "_id": "projAdel", "company_id": "companyA", "name": "A Site (marked)",
    "marked_for_deletion": True,
}

PROJECTS = {p["_id"]: p for p in (PROJECT_A, PROJECT_B, PROJECT_A_MARKED)}

# THE PRINCIPAL THAT MATTERS: role "owner" is what /auth/register forces on
# every self-serve signup, and it is approved, so require_approved alone does
# not stop it.
OWNER_A = {
    "_id": "ua", "email": "a@example.com", "role": "owner",
    "company_id": "companyA", "account_status": "approved",
    "assigned_projects": [],
}
OWNER_B = {
    "_id": "ub", "email": "b@example.com", "role": "owner",
    "company_id": "companyB", "account_status": "approved",
    "assigned_projects": [],
}
ADMIN_A = {
    "_id": "aa", "email": "aa@example.com", "role": "admin",
    "company_id": "companyA", "account_status": "approved",
    "assigned_projects": [],
}

# The three routes under test, as (path template, concrete url for projA/projB).
ROUTES = {
    "preview": "/api/reports/project/{pid}/preview/2026-08-07",
    "history": "/api/reports/project/{pid}/history",
    "logs": "/api/reports/project/{pid}/logs",
}

ROUTE_PATHS = [
    "/reports/project/{project_id}/preview/{date}",
    "/reports/project/{project_id}/history",
    "/reports/project/{project_id}/logs",
]


class _Cursor:
    """Stands in for a motor cursor; every chained call returns self."""

    def __init__(self, rows=None):
        self._rows = rows or []

    def sort(self, *a, **kw):
        return self

    def skip(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    async def to_list(self, *a, **kw):
        return list(self._rows)


def _mock_db():
    """A db whose projects collection honours ACTIVE_PROJECT_FILTER.

    require_project_access looks projects up WITH that filter; the routes'
    own lookups do not. Honouring it here is what lets the marked-for-deletion
    case say something true.
    """

    async def _find_one_project(q, *a, **kw):
        doc = PROJECTS.get(str(q.get("_id")))
        if doc is None:
            return None
        # {"is_deleted": {"$ne": True}} / {"marked_for_deletion": {"$ne": True}}
        for field, cond in q.items():
            if field == "_id":
                continue
            if isinstance(cond, dict) and "$ne" in cond:
                if doc.get(field) == cond["$ne"]:
                    return None
        return doc

    db = MagicMock()
    db.projects = MagicMock()
    db.projects.find_one = AsyncMock(side_effect=_find_one_project)

    db.logbooks = MagicMock()
    db.logbooks.find = MagicMock(return_value=_Cursor([]))
    db.logbooks.find_one = AsyncMock(return_value=None)

    db.checkins = MagicMock()
    db.checkins.count_documents = AsyncMock(return_value=0)
    db.checkins.find = MagicMock(return_value=_Cursor([]))

    db.report_emails = MagicMock()
    db.report_emails.find = MagicMock(return_value=_Cursor([]))
    db.report_emails.find_one = AsyncMock(return_value=None)
    db.report_emails.count_documents = AsyncMock(return_value=0)

    return db


def _get(user, project_id, route_key):
    import server

    server.app.dependency_overrides[server.get_current_user] = lambda: user
    client = TestClient(server.app)
    url = ROUTES[route_key].format(pid=project_id)
    try:
        with patch("server.db", _mock_db()), patch("server.to_query_id", lambda v: v):
            return client.get(url)
    finally:
        server.app.dependency_overrides.clear()


class TestCrossTenantOwnerIsRefused(unittest.TestCase):
    """THE BUG. Company A's owner must not read company B's report data.

    Pre-fix every one of these returned 200 with company B's payload."""

    def test_preview(self):
        r = _get(OWNER_A, "projB", "preview")
        self.assertEqual(r.status_code, 403, f"owner of A read B's preview: {r.text[:400]}")

    def test_history(self):
        r = _get(OWNER_A, "projB", "history")
        self.assertEqual(r.status_code, 403, f"owner of A read B's send history: {r.text[:400]}")

    def test_logs(self):
        r = _get(OWNER_A, "projB", "logs")
        self.assertEqual(r.status_code, 403, f"owner of A read B's filed logbooks: {r.text[:400]}")

    def test_no_company_b_data_leaks_in_the_body(self):
        """Not just the status code — B's project name must not come back."""
        for key in ROUTES:
            with self.subTest(route=key):
                r = _get(OWNER_A, "projB", key)
                self.assertNotIn("B Site", r.text)


class TestSameCompanyReaderStillServed(unittest.TestCase):
    """A guard that 403s everyone is as broken as one that 403s nobody."""

    def test_owner_reads_own_project(self):
        for key in ROUTES:
            with self.subTest(route=key):
                r = _get(OWNER_A, "projA", key)
                self.assertEqual(r.status_code, 200, f"{key}: {r.text[:400]}")

    def test_admin_reads_own_project(self):
        for key in ROUTES:
            with self.subTest(route=key):
                r = _get(ADMIN_A, "projA", key)
                self.assertEqual(r.status_code, 200, f"{key}: {r.text[:400]}")

    def test_owner_b_reads_own_project(self):
        for key in ROUTES:
            with self.subTest(route=key):
                r = _get(OWNER_B, "projB", key)
                self.assertEqual(r.status_code, 200, f"{key}: {r.text[:400]}")


class TestMarkedForDeletionProject(unittest.TestCase):
    """require_project_access resolves through ACTIVE_PROJECT_FILTER, so a
    project an admin marked for deletion reads as 404 — the same answer its
    FULL report (/date/{date}) already gives, and the same answer GET /projects
    gives by omitting it from the list. No UI can select one."""

    def test_marked_project_is_404_for_its_own_company(self):
        for key in ROUTES:
            with self.subTest(route=key):
                r = _get(OWNER_A, "projAdel", key)
                self.assertEqual(r.status_code, 404, f"{key}: {r.text[:400]}")


class TestUnknownProject(unittest.TestCase):
    def test_unknown_project_is_404_not_403(self):
        for key in ROUTES:
            with self.subTest(route=key):
                r = _get(OWNER_A, "nope", key)
                self.assertEqual(r.status_code, 404, f"{key}: {r.text[:400]}")


class TestPendingAccountRefused(unittest.TestCase):
    """require_approved: a pending self-serve owner reads nothing, even in
    their own company."""

    PENDING = dict(OWNER_A, _id="up", account_status="pending")

    def test_pending_owner_is_403(self):
        for key in ROUTES:
            with self.subTest(route=key):
                r = _get(self.PENDING, "projA", key)
                self.assertEqual(r.status_code, 403, f"{key}: {r.text[:400]}")


class TestRoutesDeclareTheGuards(unittest.TestCase):
    """Table-driven, so silently dropping a dependency fails CI rather than
    quietly reopening the hole."""

    def _dep_names(self, route):
        deps = getattr(getattr(route, "dependant", None), "dependencies", []) or []
        names = [getattr(d.call, "__name__", "") for d in deps if d.call]
        for d in deps:
            names += [getattr(sd.call, "__name__", "") for sd in (d.dependencies or []) if sd.call]
        return names

    def test_all_three_declare_require_project_access_and_require_approved(self):
        import server

        by_path = {}
        for r in server.app.routes:
            path = getattr(r, "path", "")
            if path:
                by_path.setdefault(path.replace("/api", "", 1), []).append(r)

        missing = []
        for path in ROUTE_PATHS:
            routes = by_path.get(path) or []
            if not routes:
                missing.append(f"{path} (route not found)")
                continue
            names = []
            for r in routes:
                names += self._dep_names(r)
            for required in ("require_project_access", "require_approved"):
                if required not in names:
                    missing.append(f"{path} -> {required}")

        self.assertEqual(
            missing, [],
            "report routes lost a tenant guard — cross-tenant reads are open "
            "again on: " + ", ".join(missing),
        )

    def test_the_owner_shaped_hole_is_gone_from_the_source(self):
        """The literal shape that made `owner` skip the comparison.

        Pinned as text because the dependency test above would still pass if
        someone re-added the inert conditional alongside it and a later reader
        trusted it."""
        src = Path(__file__).resolve().parent.parent / "server.py"
        needle = 'if role == "admin" and project.get("company_id") != current_user.get("company_id")'
        # COMMENT LINES ARE EXCLUDED on purpose: the fix quotes the dead shape
        # verbatim in the note above get_report_preview, so that a reader who
        # meets it elsewhere recognises it. A quotation is not a gate.
        hits = [
            n for n, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1)
            if needle in line and not line.lstrip().startswith("#")
        ]
        # assertEqual on the LINE NUMBERS, not assertNotIn on the body — a
        # failing assertNotIn prints the whole 39k-line file into the report.
        self.assertEqual(
            hits, [],
            f"the `role == 'admin' and ...` gate is back at server.py line(s) {hits}. "
            "It is inert for role 'owner', which is what /auth/register forces "
            "on every signup.",
        )


if __name__ == "__main__":
    unittest.main()
