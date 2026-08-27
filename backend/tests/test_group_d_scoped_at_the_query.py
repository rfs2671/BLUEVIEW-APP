"""The list is scoped at the query, and the group write uses the shared helper.

TWO ROUTES THAT FIT NO DEPENDENCY.

1. GET /admin/site-devices LEAKED RATHER THAN REFUSING. It fetched every device
   in the database and dropped foreign ones inside the loop:

       if company_id and project.get("company_id") != company_id:
           continue

   TWO WAYS PAST IT, and NEITHER produced a 403 -- both produced a 200 with
   other tenants' rows in the body:

     a. a falsy CALLER company: `and` short-circuits, the filter never applies,
        and the caller receives every site device on the platform;
     b. an ORPHANED DEVICE: the check sat inside `if device.get("project_id")`
        and `if project:`, so a device with no project_id -- or one whose
        project was soft-deleted -- skipped it entirely and was appended
        regardless of company, EVEN FOR A CALLER WITH A VALID COMPANY.

   SO EVERY TEST HERE ASSERTS THE BODY. A test checking only for a 403 would
   have passed against the old code on path (b) and against a 200-with-leak on
   path (a). The status code was never the defect.

   A site device row is a CREDENTIAL -- username, hashed password, and the
   project it authenticates against. The projection drops the hash; the
   username and the site it opens are enough.

2. PUT /whatsapp/groups/{id}/config now uses _same_company_or_403, which did
   not exist when group D was first surveyed.

    python backend/tests/test_group_d_scoped_at_the_query.py
"""

import ast
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

ADMIN_A = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
           "account_status": "approved"}
ADMIN_B = {"_id": "v1", "id": "v1", "role": "admin", "company_id": "companyB",
           "account_status": "approved"}
COMPANYLESS = {"_id": "w1", "id": "w1", "role": "admin", "company_id": None,
               "account_status": "approved"}

PROJ_A = {"_id": "projA", "company_id": "companyA", "name": "588 Thomas"}
PROJ_B = {"_id": "projB", "company_id": "companyB", "name": "857 Prescott"}

DEV_A = {"_id": "d1", "username": "gate-a", "project_id": "projA",
         "company_id": "companyA", "is_deleted": False}
DEV_B = {"_id": "d2", "username": "gate-b", "project_id": "projB",
         "company_id": "companyB", "is_deleted": False}
# THE ORPHANS -- path (b). Under the old code these skipped the filter and were
# returned to EVERY caller, whatever company they had.
DEV_NO_PROJECT = {"_id": "d3", "username": "orphan-noproj", "company_id": "companyB",
                  "is_deleted": False}
DEV_DEAD_PROJECT = {"_id": "d4", "username": "orphan-deadproj",
                    "project_id": "projGONE", "company_id": "companyB",
                    "is_deleted": False}

ALL_DEVICES = [DEV_A, DEV_B, DEV_NO_PROJECT, DEV_DEAD_PROJECT]
PROJECTS = {"projA": PROJ_A, "projB": PROJ_B}     # projGONE resolves to None


def _list(admin, devices=ALL_DEVICES):
    """Drive the real handler. The fake HONOURS the query filter, so a handler
    that fetched everything and filtered in Python would still leak here."""
    seen = {}

    def find(q, projection=None):
        seen["query"] = dict(q)
        rows = []
        for d in devices:
            if q.get("is_deleted") == {"$ne": True} and d.get("is_deleted") is True:
                continue
            if "company_id" in q and d.get("company_id") != q["company_id"]:
                continue
            row = {k: v for k, v in d.items() if not (projection or {}).get(k) == 0}
            rows.append(row)
        return MagicMock(to_list=AsyncMock(return_value=rows))

    db = MagicMock()
    db.site_devices.find = find
    db.projects.find_one = AsyncMock(
        side_effect=lambda q, *a, **kw: dict(PROJECTS[q["_id"]])
        if q.get("_id") in PROJECTS else None)
    with patch.object(server, "db", db), \
         patch.object(server, "to_query_id", lambda x: x):
        out = asyncio.run(server.get_site_devices(admin=admin))
    return out, seen.get("query", {})


class TheListIsScopedAtTheQuery(unittest.TestCase):
    """EVERY ASSERTION READS THE BODY. The defect never produced a bad status."""

    def test_an_admin_sees_only_his_own_companys_devices(self):
        out, _q = _list(ADMIN_A)
        self.assertEqual([d["username"] for d in out], ["gate-a"])

    def test_no_foreign_device_appears_in_the_body(self):
        out, _q = _list(ADMIN_A)
        names = {d["username"] for d in out}
        for leaked in ("gate-b", "orphan-noproj", "orphan-deadproj"):
            self.assertNotIn(leaked, names, f"{leaked} leaked into the response")

    def test_a_device_with_NO_project_id_does_not_leak(self):
        """PATH (b). The old filter lived inside `if device.get("project_id")`,
        so this row skipped it and was returned to everyone."""
        out, _q = _list(ADMIN_A, devices=[DEV_NO_PROJECT])
        self.assertEqual(out, [])

    def test_a_device_whose_project_is_GONE_does_not_leak(self):
        """PATH (b) again -- the check also sat inside `if project:`."""
        out, _q = _list(ADMIN_A, devices=[DEV_DEAD_PROJECT])
        self.assertEqual(out, [])

    def test_the_query_itself_carries_the_company(self):
        """SCOPED, NOT FILTERED. A handler that fetched everything and dropped
        rows in Python is one `continue` away from leaking again."""
        _out, q = _list(ADMIN_A)
        self.assertEqual(q.get("company_id"), "companyA")
        self.assertEqual(q.get("is_deleted"), {"$ne": True})

    def test_a_company_less_admin_is_REFUSED_not_given_everything(self):
        """PATH (a). `and` short-circuited, so this caller received every site
        device on the platform with a 200."""
        with self.assertRaises(HTTPException) as c:
            _list(COMPANYLESS)
        self.assertEqual(c.exception.status_code, 403)

    def test_the_refusal_says_why_rather_than_returning_an_empty_list(self):
        """An empty list would read as "no devices configured" -- the same
        class of false statement as reporting a designed absence as missing
        data."""
        with self.assertRaises(HTTPException) as c:
            _list(COMPANYLESS)
        self.assertIn("no company", str(c.exception.detail).lower())

    def test_the_password_is_still_projected_out(self):
        """Unchanged, and the reason the leak was survivable: the hash never
        left the server. The username and the site it opens still did."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8-sig")
        i = src.index("async def get_site_devices")
        body = src[i:src.index("@api_router", i)]
        self.assertIn('{"password": 0}', body)

    def test_the_project_lookup_no_longer_decides_visibility(self):
        """It resolves a display name and nothing else. Read as CODE: the
        docstring quotes the removed `continue`."""
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_site_devices":
                self.assertEqual(
                    [n for n in ast.walk(node) if isinstance(n, ast.Continue)], [],
                    "a `continue` still decides whether a row is returned")
                return
        self.fail("get_site_devices not found")


# ── PUT /whatsapp/groups/{id}/config ────────────────────────────────────────
GROUP_A = {"_id": "g1", "company_id": "companyA", "config": {}}


# A REAL config key. `_WHATSAPP_CONFIG_KEYS` is validated AFTER the tenancy
# guard, so an invented key 422s on the owner path -- which would have looked
# like the guard refusing its own tenant.
def _group_config(group, user):
    db = MagicMock()
    db.whatsapp_groups.find_one = AsyncMock(
        side_effect=lambda q, *a, **kw: dict(group) if group is not None else None)
    db.whatsapp_groups.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    with patch.object(server, "db", db), \
         patch.object(server, "to_query_id", lambda x: x):
        return asyncio.run(server.whatsapp_update_group_config(
            group_doc_id="g1", body={"bot_enabled": True}, current_user=user))


class TheGroupConfigWriteIsScoped(unittest.TestCase):

    def _refused(self, group, user=ADMIN_A):
        with self.assertRaises(HTTPException) as c:
            _group_config(group, user)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_cross_tenant_admin_is_refused(self):
        self._refused(GROUP_A, ADMIN_B)

    def test_a_company_less_caller_is_refused(self):
        self._refused(GROUP_A, COMPANYLESS)

    def test_a_NULL_company_group_is_refused(self):
        self._refused({**GROUP_A, "company_id": None})

    def test_an_EMPTY_company_group_is_refused(self):
        """Unowned is unowned, whichever falsy shape it takes."""
        self._refused({**GROUP_A, "company_id": ""})

    def test_a_MISSING_company_group_is_refused(self):
        self._refused({k: v for k, v in GROUP_A.items() if k != "company_id"})

    def test_nothing_is_written_when_refused(self):
        db = MagicMock()
        db.whatsapp_groups.find_one = AsyncMock(return_value=dict(GROUP_A))
        db.whatsapp_groups.update_one = AsyncMock()
        with patch.object(server, "db", db), patch.object(server, "to_query_id", lambda x: x):
            with self.assertRaises(HTTPException):
                asyncio.run(server.whatsapp_update_group_config(
                    group_doc_id="g1", body={"bot_enabled": True}, current_user=ADMIN_B))
        db.whatsapp_groups.update_one.assert_not_awaited()

    def test_the_owner_may_still_write(self):
        self.assertIsNotNone(_group_config(GROUP_A, ADMIN_A))

    def test_a_missing_group_is_still_404(self):
        with self.assertRaises(HTTPException) as c:
            _group_config(None, ADMIN_A)
        self.assertEqual(c.exception.status_code, 404)

    def test_it_uses_the_shared_helper(self):
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "whatsapp_update_group_config":
                calls = [ast.unparse(n.func) for n in ast.walk(node)
                         if isinstance(n, ast.Call)]
                self.assertIn("_same_company_or_403", calls)
                for n in ast.walk(node):
                    if isinstance(n, ast.If):
                        self.assertIsNone(
                            re.search(
                                r"""^\w*company_id\s+and\s+.*\.get\(['"]company_id['"]\)""",
                                ast.unparse(n.test)))
                return
        self.fail("whatsapp_update_group_config not found")


class TheSweepIsDown(unittest.TestCase):

    def test_the_sweep_matches_the_single_pinned_total(self):
        mod = __import__("test_pm_load_project_fails_closed")
        self.assertEqual(len(mod.sweep_bypass_sites()),
                         mod.TheSweepCountOnlyGoesDOWN.EXPECTED_TOTAL)

    # AND NOT A LITERAL TOTAL HERE EITHER. Writing one is what broke a sibling
    # file in each of the four preceding PRs; this file would have been the
    # fifth. Agreement with the single constant is the whole assertion.

    def test_what_remains_is_belt_and_braces_only(self):
        """Every remaining hit sits on a route that ALREADY carries a
        fail-closed tenancy dependency, so the conditional is redundant rather
        than load-bearing. That is the end state this series was aiming at:
        nothing left where the short-circuit is the only control."""
        mod = __import__("test_pm_load_project_fails_closed")
        src = (BACKEND / "server.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(src)
        owner = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for ln in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
                    owner[ln] = node
        unguarded = []
        for hit in mod.sweep_bypass_sites():
            name, lineno = hit.split(":")
            if name != "server.py":
                continue
            fn = owner.get(int(lineno))
            if fn is None:
                continue
            deco = " ".join(ast.unparse(d) for d in fn.decorator_list)
            if "require_project_access" not in deco:
                unguarded.append(f"{hit} ({fn.name})")
        self.assertEqual(unguarded, [], "a conditional-only site remains")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    unittest.main(verbosity=2)
