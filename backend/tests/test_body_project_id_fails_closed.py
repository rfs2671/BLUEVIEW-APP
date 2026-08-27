"""A project id from the request body is scoped like one from the path.

TWO ROUTES took project_id out of the BODY and checked it with

    if company_id and project.get("company_id") != company_id:

which short-circuits: a caller whose company_id is falsy never reaches the
comparison, so the 403 could not fire. /auth/register sets
user_dict["company_id"] = None on every self-serve signup, so that is the
DEFAULT state until onboarding attaches a company.

    POST /admin/site-devices
    POST /admin/cs-registrations

BOTH ARE WRITES, AND BOTH STAMP TENANCY FROM THE PROJECT THEY WERE HANDED:

    device_dict["company_id"] = project.get("company_id")

So a site device provisioned onto another tenant's project would have been
stamped into the VICTIM's company and then authenticated against it -- an
account inside a tenancy nobody in that tenancy created. A Construction
Superintendent registration asserts who is responsible for a jobsite, so the
second is a false statement about a DOB-facing role.

get_admin_user DOES NOT HELP. It is a ROLE gate: an admin of any company passed
it. The conditional was the only tenancy control, and it could not fire.

THE FIX IS THE EXISTING RULE. project_access_ok is what require_project_access
applies; it is called directly because the id is in the body, so there is no
path parameter for a dependency to resolve. Same as _pm_load_project_or_403 and
create_annotation.

    python backend/tests/test_body_project_id_fails_closed.py
"""

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

PROJ_A = {"_id": "projA", "id": "projA", "company_id": "companyA", "name": "588 Thomas"}

ADMIN_A = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
           "account_status": "approved"}
# THE ATTACKER: a real admin, of a different tenant. get_admin_user admits him.
ADMIN_B = {"_id": "v1", "id": "v1", "role": "admin", "company_id": "companyB",
           "account_status": "approved"}
# THE DEFAULT STATE of every self-serve signup.
COMPANYLESS = {"_id": "w1", "id": "w1", "role": "admin", "company_id": None,
               "account_status": "approved"}
ASSIGNED_B = {"_id": "x1", "id": "x1", "role": "admin", "company_id": "companyB",
              "account_status": "approved", "assigned_projects": ["projA"]}


def _db(project=PROJ_A):
    state = {"inserts": []}

    async def proj_find_one(q, *a, **kw):
        return dict(project) if project else None

    async def generic_find_one(q, *a, **kw):
        return None

    async def insert_one(doc):
        state["inserts"].append(dict(doc))
        r = MagicMock()
        r.inserted_id = "new1"
        return r

    db = MagicMock()
    db.projects.find_one = AsyncMock(side_effect=proj_find_one)
    for coll in ("site_devices", "cs_registrations", "users"):
        getattr(db, coll).find_one = AsyncMock(side_effect=generic_find_one)
        getattr(db, coll).insert_one = AsyncMock(side_effect=insert_one)
        getattr(db, coll).find = MagicMock(
            return_value=MagicMock(to_list=AsyncMock(return_value=[])))
    return db, state


def _site_device(admin, project=PROJ_A):
    db, state = _db(project)
    body = server.SiteDeviceCreate(
        username="gate1", password="pw123456", project_id="projA",
        device_name="North Gate",
    )
    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()):
        asyncio.run(server.create_site_device(device_data=body, admin=admin))
    return state


def _cs_registration(admin, project=PROJ_A):
    db, state = _db(project)
    fields = set(server.CSRegistrationCreate.model_fields)
    payload = {"project_id": "projA"}
    for name, f in server.CSRegistrationCreate.model_fields.items():
        if name in payload or not f.is_required():
            continue
        payload[name] = "X"
    body = server.CSRegistrationCreate(**payload)
    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()), \
         patch.object(server, "dispatch_notification", AsyncMock(), create=True):
        asyncio.run(server.register_construction_superintendent(
            data=body, admin=admin))
    return state


class SiteDeviceIsScoped(unittest.TestCase):

    def test_a_cross_tenant_ADMIN_is_refused(self):
        """get_admin_user is a ROLE gate. It admitted him; only the conditional
        stood between him and another tenant's project, and it could not fire
        for a company-less caller."""
        with self.assertRaises(HTTPException) as c:
            _site_device(ADMIN_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_company_less_admin_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _site_device(COMPANYLESS)
        self.assertEqual(c.exception.status_code, 403)

    def test_nothing_is_provisioned_when_refused(self):
        """THE CONSEQUENCE. The insert stamps
        `device_dict["company_id"] = project.get("company_id")`, so a device
        created here lands in the VICTIM's tenancy and then authenticates
        against it."""
        try:
            state = _site_device(ADMIN_B)
        except HTTPException:
            return
        self.fail(f"a device was provisioned into another tenant: {state}")

    def test_the_owning_admin_may_still_provision(self):
        state = _site_device(ADMIN_A)
        self.assertEqual(len(state["inserts"]), 1)
        self.assertEqual(state["inserts"][0]["company_id"], "companyA")

    def test_a_missing_project_is_still_404(self):
        with self.assertRaises(HTTPException) as c:
            _site_device(ADMIN_A, project=None)
        self.assertEqual(c.exception.status_code, 404)

    def test_an_ASSIGNED_admin_is_allowed(self):
        """The shared rule's third branch, consistent with every other
        project-scoped route rather than this one keeping a narrower private
        rule."""
        self.assertEqual(len(_site_device(ASSIGNED_B)["inserts"]), 1)


class CSRegistrationIsScoped(unittest.TestCase):

    def test_a_cross_tenant_ADMIN_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _cs_registration(ADMIN_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_company_less_admin_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _cs_registration(COMPANYLESS)
        self.assertEqual(c.exception.status_code, 403)

    def test_nothing_is_registered_when_refused(self):
        """A CS registration asserts who is RESPONSIBLE for a jobsite. Writing
        one onto another tenant's project is a false statement about a
        DOB-facing role."""
        try:
            state = _cs_registration(ADMIN_B)
        except HTTPException:
            return
        self.fail(f"a CS was registered on another tenant's project: {state}")

    def test_the_owning_admin_may_still_register(self):
        self.assertEqual(len(_cs_registration(ADMIN_A)["inserts"]), 1)

    def test_a_missing_project_is_still_404(self):
        with self.assertRaises(HTTPException) as c:
            _cs_registration(ADMIN_A, project=None)
        self.assertEqual(c.exception.status_code, 404)


class ItUsesTheSharedRule(unittest.TestCase):
    """Read as CODE. A substring check here would match the comments that
    explain the removed line -- see the practice note in followups.md."""

    def _fn_conditions(self, name):
        import ast
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return [ast.unparse(n.test) for n in ast.walk(node)
                        if isinstance(n, ast.If)]
        self.fail(f"{name} not found")

    def test_site_device_has_no_conditional_company_check(self):
        for cond in self._fn_conditions("create_site_device"):
            self.assertIsNone(
                re.search(r"""^company_id\s+and\s+.*\.get\(['"]company_id['"]\).*!=""", cond),
                cond)

    def test_cs_registration_has_no_conditional_company_check(self):
        for cond in self._fn_conditions("register_construction_superintendent"):
            self.assertIsNone(
                re.search(r"""^company_id\s+and\s+.*\.get\(['"]company_id['"]\).*!=""", cond),
                cond)

    def test_both_call_project_access_ok(self):
        for name in ("create_site_device", "register_construction_superintendent"):
            conds = self._fn_conditions(name)
            self.assertTrue(
                any("project_access_ok" in c for c in conds),
                f"{name} does not use the shared rule: {conds}")

    def test_the_lookup_filter_is_unchanged(self):
        """Still `is_deleted`, not ACTIVE_PROJECT_FILTER. Authorization was what
        was missing; adopting the wider filter would newly 404 these writes on a
        project an admin has just marked for deletion."""
        captured = []

        db, _state = _db()
        orig = db.projects.find_one

        async def spy(q, *a, **kw):
            captured.append(q)
            return dict(PROJ_A)

        db.projects.find_one = AsyncMock(side_effect=spy)
        body = server.SiteDeviceCreate(
            username="g", password="pw123456", project_id="projA",
            device_name="G")
        with patch.object(server, "db", db), patch.object(server, "audit_log", AsyncMock()):
            asyncio.run(server.create_site_device(device_data=body, admin=ADMIN_A))
        self.assertTrue(captured)
        self.assertIn("is_deleted", captured[0])
        self.assertNotIn("marked_for_deletion", captured[0])


class TheseTwoRoutesLeftTheSweep(unittest.TestCase):
    """The mechanism from the previous PR, exercised rather than trusted.

    NO LITERAL TOTAL HERE. An earlier version of this class asserted the count
    was exactly 32, and the very next PR in the series broke it -- the total is
    designed to keep falling, so pinning it in more than one file makes every
    subsequent fix look like a regression and trains people to edit the number
    until the suite goes quiet.

    EXPECTED_TOTAL lives in ONE place. This file asserts the sweep agrees with
    it, and that these two routes are no longer among the hits -- which is the
    claim this PR is actually making.
    """

    def test_the_sweep_agrees_with_the_single_pinned_total(self):
        mod = __import__("test_pm_load_project_fails_closed")
        self.assertEqual(len(mod.sweep_bypass_sites()),
                         mod.TheSweepCountOnlyGoesDOWN.EXPECTED_TOTAL)

    def test_neither_route_is_still_in_the_sweep(self):
        mod = __import__("test_pm_load_project_fails_closed")
        hits = set(mod.sweep_bypass_sites())
        src = (BACKEND / "server.py").read_text(encoding="utf-8-sig").splitlines()
        for hit in hits:
            name, lineno = hit.split(":")
            if name != "server.py":
                continue
            window = " ".join(src[max(0, int(lineno) - 40):int(lineno)])
            self.assertNotIn("async def create_site_device", window)
            self.assertNotIn("async def register_construction_superintendent", window)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    unittest.main(verbosity=2)
