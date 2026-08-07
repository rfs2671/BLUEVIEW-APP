"""Tenant isolation — BATCH 2 (project-scoped WRITE endpoints).

Batch 1 closed the READ side. The write side was left open: 25 project-scoped
writes either had no ownership check at all, or a hand-rolled one of the shape

    company_id = get_user_company_id(admin)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(403, ...)

which SILENTLY PASSES when the caller's company_id is falsy — the `and`
short-circuits, so an admin whose user document has no company_id reached every
project in the database. `require_project_access` fails closed instead: a falsy
user_company falls through to the 403 at the end (server.py:2814-2822).

Two variants were worse than the generic pattern:
  * upload-file then did `company_id = company_id or project.get("company_id")`,
    adopting the VICTIM's company for the R2 key — the attacker's document was
    filed inside the victim tenant.
  * report-settings wrapped its check in `if user_role == "admin"`, so the
    `owner` role — which every self-serve signup receives — skipped it entirely.

Three directions per route, because a guard that 403s everyone is as broken as
one that 403s nobody:

  1. cross-company caller            -> 403   (the hole is closed)
  2. own-company approved admin      -> works (the customer is not broken)
  3. pending account                 -> 403   (require_approved is live)

A fourth direction matters here: a SITE DEVICE must still reach its OWN project.
require_approved bypasses site devices by design (server.py:2542 — it sits in
front of check-in and must never break it), and require_project_access branch 1
authorizes a device for its provisioned project only. Both are asserted so a
future edit cannot quietly break the kiosk.

NOT COVERED BY THE PINS BELOW, BUT NO LONGER OPEN — the kiosk write path. POST
/daily-logs takes project_id in the BODY, not the path, so it cannot declare
`Depends(require_project_access)` and the decorator pins here cannot see it. The
rules were extracted into `_assert_project_access` (a plain coroutine over the
same three branches, site-device included) and both endpoints now call it: the
create with the body's project_id, the update with the STORED project_id so the
body cannot re-parent a log. PUT also pops project_id/company_id out of the $set
dict. Those two routes are covered by test_daily_logs_tenant_isolation.py
instead. Also excluded: hard-delete (platform
operator — require_project_access has no operator bypass and would break the
cross-company purge), assign-projects and cs-registrations (no {project_id} in
the path), repair-file-names (deliberately unfiltered for legacy rows), and
/checkin/register-and-checkin (public by design).

Two regression pins, deliberately different in kind:
  * a SOURCE pin (ast-parses server.py) — catches a deleted decorator argument.
  * a WIRING pin (walks the live FastAPI dependant tree) — catches the case
    where the decorator text is right but the dependency never took effect.
"""

import ast
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
PROJECTS = {"projA": PROJECT_A, "projB": PROJECT_B}

ADMIN_A = {"_id": "ua", "role": "admin", "company_id": "companyA",
           "account_status": "approved", "assigned_projects": []}
ADMIN_B = {"_id": "ub", "role": "admin", "company_id": "companyB",
           "account_status": "approved", "assigned_projects": []}
# `owner` is what every self-serve signup receives — a CUSTOMER role, not a
# platform role. report-settings used to skip its tenancy check for it.
OWNER_B = {"_id": "ob", "role": "owner", "company_id": "companyB",
           "account_status": "approved", "assigned_projects": []}
# The falsy-company_id case the old hand-rolled checks let straight through.
ADMIN_NO_COMPANY = {"_id": "un", "role": "admin", "company_id": None,
                    "account_status": "approved", "assigned_projects": []}
PENDING_A = {"_id": "up", "role": "admin", "company_id": "companyA",
             "account_status": "pending", "assigned_projects": []}
# Cross-company contractor explicitly assigned to A's project.
ASSIGNED_C = {"_id": "uc", "role": "cp", "company_id": "companyC",
              "account_status": "approved", "assigned_projects": ["projA"]}
DEVICE_A = {"_id": "dev1", "site_mode": True, "role": "site_device",
            "project_id": "projA", "company_id": "companyA"}

TIER1_DESTRUCTIVE = [
    ("delete", "/projects/{project_id}"),
    ("delete", "/projects/{project_id}/nfc-tags/{tag_id}"),
    ("delete", "/projects/{project_id}/files/{file_id}"),
    ("post", "/projects/{project_id}/site-devices"),
    ("put", "/projects/{project_id}"),
    ("post", "/projects/{project_id}/link-dropbox"),
]

TIER2_SETTINGS = [
    ("post", "/projects/{project_id}/nfc-tags"),
    ("put", "/projects/{project_id}/site-device-subfolders"),
    ("put", "/logbooks/project/{project_id}/scaffold-info"),
    ("post", "/projects/{project_id}/safety-staff"),
    ("put", "/projects/{project_id}/report-settings"),
    ("put", "/projects/{project_id}/dob-config"),
]

TIER3_ACTIONS = [
    ("post", "/projects/{project_id}/logbook/attestations/generate"),
    ("post", "/projects/{project_id}/risk-score/calculate"),
    ("post", "/projects/{project_id}/sync-dropbox"),
    ("post", "/projects/{project_id}/upload-file"),
    ("post", "/projects/{project_id}/dob-logs/{log_id}/mark-read"),
    ("post", "/projects/{project_id}/dob-logs/mark-all-read"),
    ("post", "/projects/{project_id}/dob-sync"),
    ("post", "/projects/{project_id}/reindex-document"),
    ("post", "/projects/{project_id}/reindex-all"),
    ("post", "/projects/{project_id}/debug/test-plan-image-send"),
    ("post", "/projects/{project_id}/model/aggregate"),
    ("patch", "/projects/{project_id}/model/confirm"),
    ("post", "/projects/{project_id}/schedule/generate"),
]

CLEAN_ROUTES = TIER1_DESTRUCTIVE + TIER2_SETTINGS + TIER3_ACTIONS


def _db_with(projects):
    """Minimal db double: projects.find_one keyed on _id."""
    async def _find_one(q, *a, **kw):
        return projects.get(q.get("_id"))
    db = MagicMock()
    db.projects.find_one = AsyncMock(side_effect=_find_one)
    return db


class ProjectAccessDirections(unittest.TestCase):
    """require_project_access IS the authorization boundary for all 25 routes."""

    def _call(self, project_id, user):
        import server
        with patch.object(server, "db", _db_with(PROJECTS)):
            return asyncio.run(
                server.require_project_access(project_id=project_id, current_user=user)
            )

    # ---- direction 1: cross-company caller blocked, both ways ----
    def test_cross_company_admin_blocked(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call("projB", ADMIN_A)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_cross_company_admin_blocked_reverse(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call("projA", ADMIN_B)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_cross_company_owner_blocked(self):
        """`owner` is a customer role — report-settings used to exempt it."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("projA", OWNER_B)
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- direction 2: own-company caller still works (over-gate check) ----
    def test_own_company_admin_allowed(self):
        self.assertEqual(self._call("projA", ADMIN_A)["_id"], "projA")

    def test_own_company_admin_allowed_b(self):
        self.assertEqual(self._call("projB", ADMIN_B)["_id"], "projB")

    def test_own_company_owner_allowed(self):
        self.assertEqual(self._call("projB", OWNER_B)["_id"], "projB")

    def test_assigned_contractor_allowed_cross_company(self):
        """Explicit assignment is a legitimate access path — must not over-gate."""
        self.assertEqual(self._call("projA", ASSIGNED_C)["_id"], "projA")

    # ---- the falsy-company_id bypass the old checks permitted ----
    def test_null_company_admin_now_blocked(self):
        """Previously `if company_id and ...` short-circuited and ALLOWED this."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("projA", ADMIN_NO_COMPANY)
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- device direction: own project yes, other project no ----
    def test_site_device_own_project_allowed(self):
        self.assertEqual(self._call("projA", DEVICE_A)["_id"], "projA")

    def test_site_device_other_project_blocked(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call("projB", DEVICE_A)
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- a missing project is 404, not 403: never confirm an id ----
    def test_missing_project_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call("nope", ADMIN_A)
        self.assertEqual(ctx.exception.status_code, 404)


class RequireApprovedDirections(unittest.TestCase):
    """direction 3: a pending account cannot reach any gated write."""

    def _call(self, user):
        import server
        return asyncio.run(server.require_approved(current_user=user))

    def test_pending_blocked(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call(PENDING_A)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, {"error": "account_pending"})

    def test_approved_allowed(self):
        self.assertEqual(self._call(ADMIN_A)["_id"], "ua")

    def test_site_device_bypasses(self):
        """Kiosk must never be blocked by the account gate — check-in needs it."""
        self.assertEqual(self._call(DEVICE_A)["_id"], "dev1")


class SourcePin(unittest.TestCase):
    """Parse server.py and assert every clean route still DECLARES both guards.
    Catches a deleted decorator argument."""

    @classmethod
    def setUpClass(cls):
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8"
        )
        cls.tree = ast.parse(src)

    def _decorator_for(self, method, path):
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                f = dec.func
                if not (isinstance(f, ast.Attribute) and f.attr == method):
                    continue
                if not (isinstance(f.value, ast.Name) and f.value.id == "api_router"):
                    continue
                if dec.args and isinstance(dec.args[0], ast.Constant) \
                        and dec.args[0].value == path:
                    return dec
        return None

    def test_all_clean_routes_declare_both_guards(self):
        missing = []
        for method, path in CLEAN_ROUTES:
            dec = self._decorator_for(method, path)
            if dec is None:
                missing.append(f"{method.upper()} {path}: route not found")
                continue
            deps = ""
            for kw in dec.keywords:
                if kw.arg == "dependencies":
                    deps = ast.unparse(kw.value)
            if "require_approved" not in deps:
                missing.append(f"{method.upper()} {path}: require_approved MISSING")
            if "require_project_access" not in deps:
                missing.append(f"{method.upper()} {path}: require_project_access MISSING")
        self.assertEqual(missing, [], "guards dropped:\n  " + "\n  ".join(missing))

    def test_clean_bucket_size(self):
        """Adding a route to a tier means adding it here too."""
        self.assertEqual(len(TIER1_DESTRUCTIVE), 6)
        self.assertEqual(len(TIER2_SETTINGS), 6)
        self.assertEqual(len(TIER3_ACTIONS), 13)
        self.assertEqual(len(CLEAN_ROUTES), 25)


class WiringPin(unittest.TestCase):
    """Walk the LIVE FastAPI dependant tree. The source pin proves the text is
    present; this proves the dependency actually took effect on the registered
    route — a decorator can be textually correct and still not be wired."""

    @classmethod
    def setUpClass(cls):
        import server
        cls.app = server.app

    def _dependant_callables(self, dependant, seen=None):
        if seen is None:
            seen = set()
        names = set()
        for sub in dependant.dependencies:
            call = getattr(sub, "call", None)
            if call is not None:
                names.add(getattr(call, "__name__", ""))
            if id(sub) not in seen:
                seen.add(id(sub))
                names |= self._dependant_callables(sub, seen)
        return names

    def test_live_routes_carry_both_guards(self):
        missing = []
        for method, path in CLEAN_ROUTES:
            want_method = method.upper()
            found = None
            for route in self.app.routes:
                if not hasattr(route, "dependant"):
                    continue
                if not route.path.endswith(path):
                    continue
                if want_method not in (route.methods or set()):
                    continue
                found = route
                break
            if found is None:
                missing.append(f"{want_method} {path}: not registered on app")
                continue
            names = self._dependant_callables(found.dependant)
            if "require_approved" not in names:
                missing.append(f"{want_method} {path}: require_approved not wired")
            if "require_project_access" not in names:
                missing.append(f"{want_method} {path}: require_project_access not wired")
        self.assertEqual(missing, [], "guards not wired:\n  " + "\n  ".join(missing))


if __name__ == "__main__":
    unittest.main()
