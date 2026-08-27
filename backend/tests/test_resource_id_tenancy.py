"""A record reached by its own id is still scoped to its owner.

SEVEN ROUTES took a RESOURCE id -- not a project id -- and checked tenancy with

    if company_id and <record>.get("company_id") != company_id:

which short-circuits: a caller whose company_id is falsy never reached the
comparison, so the 403 could not fire. /auth/register sets
user_dict["company_id"] = None on every self-serve signup, so that is the
DEFAULT until onboarding attaches a company.

    GET  /permit-renewals/{renewal_id}
    GET  /permit-renewals/{renewal_id}/pw2-field-map
    GET  /permit-renewals/{renewal_id}/filing-readiness
    POST /permit-renewals/{permit_renewal_id}/start-renewal-clicked
    GET  /permit-renewals/{permit_renewal_id}/filing-jobs
    GET  /permit-renewals/{permit_renewal_id}/dob-confirmation
    GET  /signatures/{signin_id}

TWO DIFFERENT RULES, DELIBERATELY.

The six renewal routes use COMPANY EQUALITY, not project_access_ok, even though
a renewal carries both project_id and company_id:

  * a permit renewal OUTLIVES its project, so resolving through the project
    would 403 or 404 a historical renewal whose project has since been
    soft-deleted -- exactly when somebody needs to read it;
  * renewals are a COMPANY-level filing concern. project_access_ok's third
    branch admits a user with the project in assigned_projects, and a CP
    assigned to a jobsite has no business in the GC's permit filings.

The signature route uses project_access_ok, because a signature IS per-project
and every other project-scoped route in this sweep now uses it.

THE SIGNATURE ROUTE'S RESPONSE SHAPE IS UNCHANGED. It returns
JSONResponse({"error": ...}) rather than raising, and its docstring documents
those bodies. SignatureImage.jsx branches only on err.response.status (404 ->
missing, 403 -> forbidden, else -> unavailable) and a repo-wide grep for
`data.error` finds no reader -- so a shape change would have been safe, and is
therefore not worth making.

    python backend/tests/test_resource_id_tenancy.py
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

import permit_renewal  # noqa: E402
import server  # noqa: E402

PROJ_A = {"_id": "projA", "id": "projA", "company_id": "companyA"}
MEMBER_A = {"_id": "u1", "id": "u1", "role": "cp", "company_id": "companyA",
            "account_status": "approved"}
USER_B = {"_id": "v1", "id": "v1", "role": "cp", "company_id": "companyB",
          "account_status": "approved"}
ADMIN_B = {"_id": "v2", "id": "v2", "role": "admin", "company_id": "companyB",
           "account_status": "approved"}
COMPANYLESS = {"_id": "w1", "id": "w1", "role": "admin", "company_id": None,
               "account_status": "approved"}
ASSIGNED_B = {"_id": "x1", "id": "x1", "role": "cp", "company_id": "companyB",
              "account_status": "approved", "assigned_projects": ["projA"]}

RENEWAL = {"_id": "r1", "id": "r1", "project_id": "projA",
           "company_id": "companyA", "job_number": "1234"}


# The renewal guard is a CLOSURE inside create_permit_renewal_routes, so it
# cannot be imported. It is covered two ways instead: the source assertions in
# TheRenewalGuardFailsClosed read the shipped helper's AST, and
# TheRenewalGuardBehaviour evaluates a mirror of the rule. The source
# assertions are what keep the mirror honest -- neither alone would.
#
# An earlier draft tried to reach the real closure by running the factory
# against stub routers. It did not work and was left in as dead code; removed,
# because an unused helper in a test file reads as coverage that is not there.


class TheRenewalGuardFailsClosed(unittest.TestCase):
    """Asserted on the SOURCE of the shipped helper plus its behaviour, because
    the helper is a closure inside a route factory."""

    SRC = (BACKEND / "permit_renewal.py").read_text(encoding="utf-8")

    def _helper_conditions(self):
        tree = ast.parse(self.SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_assert_renewal_access":
                return [ast.unparse(n.test) for n in ast.walk(node)
                        if isinstance(n, ast.If)]
        self.fail("_assert_renewal_access not found")

    def test_the_helper_exists(self):
        self.assertIn("def _assert_renewal_access(renewal, current_user):", self.SRC)

    def test_it_refuses_a_falsy_caller_company(self):
        """THE BYPASS. Read as CODE -- the helper's docstring quotes the old
        line, so a substring check would match the explanation."""
        conds = self._helper_conditions()
        self.assertTrue(any("not company_id" in c for c in conds), conds)

    def test_it_refuses_an_UNOWNED_renewal(self):
        """A renewal with no company_id must not become everyone's. An unowned
        record is a data defect; answering it to any caller turns one defect
        into a disclosure."""
        conds = self._helper_conditions()
        self.assertTrue(
            any("renewal_company" in c and "!=" in c for c in conds), conds)

    def test_no_conditional_company_check_survives_in_the_module(self):
        tree = ast.parse(self.SRC)
        bad = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            cond = ast.unparse(node.test)
            if re.search(r"""^company_id\s+and\s+.*\.get\(['"]company_id['"]\).*!=""", cond):
                bad.append(cond)
        self.assertEqual(bad, [])

    def test_all_six_call_sites_use_it(self):
        # COUNTED AS CALLS, not as occurrences: `def
        # _assert_renewal_access(renewal, current_user):` contains the call
        # string, so a plain count reads 7 for six call sites.
        tree = ast.parse(self.SRC)
        calls = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_assert_renewal_access")
        self.assertEqual(calls, 6)

    def test_the_reason_for_company_equality_is_recorded(self):
        """Choosing a DIFFERENT rule from the rest of the sweep needs its
        argument on the record, or the next reader 'fixes' it to match."""
        i = self.SRC.index("def _assert_renewal_access")
        body = self.SRC[i:i + 2600]
        self.assertIn("OUTLIVES its project", body)
        self.assertIn("assigned_projects", body)


class TheRenewalGuardBehaviour(unittest.TestCase):
    """The rule itself, evaluated. Mirrors the shipped predicate exactly; the
    source assertions above are what keep this mirror honest."""

    @staticmethod
    def _guard(renewal, user):
        company_id = server.get_user_company_id(user)
        renewal_company = str((renewal or {}).get("company_id") or "")
        if not company_id or renewal_company != str(company_id):
            raise HTTPException(status_code=403, detail="Access denied")

    def test_the_owner_is_allowed(self):
        self._guard(RENEWAL, MEMBER_A)          # no raise

    def test_a_cross_tenant_user_is_refused(self):
        with self.assertRaises(HTTPException):
            self._guard(RENEWAL, USER_B)

    def test_a_cross_tenant_ADMIN_is_refused(self):
        with self.assertRaises(HTTPException):
            self._guard(RENEWAL, ADMIN_B)

    def test_a_company_less_caller_is_refused(self):
        with self.assertRaises(HTTPException):
            self._guard(RENEWAL, COMPANYLESS)

    def test_an_unowned_renewal_is_refused(self):
        with self.assertRaises(HTTPException):
            self._guard({**RENEWAL, "company_id": None}, MEMBER_A)

    def test_an_ASSIGNED_user_is_still_refused(self):
        """DELIBERATELY NARROWER than project_access_ok. A CP assigned to the
        jobsite has no business in the GC's permit filings."""
        with self.assertRaises(HTTPException):
            self._guard(RENEWAL, ASSIGNED_B)


# ── The signature route ─────────────────────────────────────────────────────
# A REAL ObjectId string. The route opens with `oid = ObjectId(signin_id)` and
# returns 404 signature_not_found if that raises -- so a placeholder id never
# reaches the access check, and every guard test would have passed vacuously
# against a 404 that has nothing to do with tenancy.
SIGNIN_ID = "6a8c4acd0000000000000001"
SIGN_IN = {"_id": SIGNIN_ID, "project_id": "projA", "worker_enrollment_id": "we1"}


def _signature(user, project=PROJ_A):
    db = MagicMock()
    db.sign_ins.find_one = AsyncMock(return_value=dict(SIGN_IN))
    db.projects.find_one = AsyncMock(
        side_effect=lambda q, *a, **kw: dict(project) if project else None)
    db.daily_signatures.find_one = AsyncMock(return_value=None)
    with patch.object(server, "db", db):
        return asyncio.run(server.get_signature_image(
            signin_id=SIGNIN_ID, current_user=user))


class TheSignatureRouteIsScoped(unittest.TestCase):

    def test_a_company_less_caller_gets_403(self):
        r = _signature(COMPANYLESS)
        self.assertEqual(r.status_code, 403)

    def test_a_cross_tenant_user_gets_403(self):
        self.assertEqual(_signature(USER_B).status_code, 403)

    def test_the_owner_is_not_403(self):
        """It proceeds past the guard. The signature itself is absent in this
        fixture, so a 404 here is the CORRECT downstream answer."""
        self.assertNotEqual(_signature(MEMBER_A).status_code, 403)

    def test_the_RESPONSE_SHAPE_is_unchanged(self):
        """SignatureImage.jsx branches on err.response.status, and no consumer
        reads .error -- but the documented contract lists these bodies, and
        changing a shape for no gain is not a fix."""
        import json
        body = json.loads(_signature(USER_B).body)
        self.assertEqual(body, {"error": "forbidden"})

    def test_it_still_returns_JSONResponse_not_a_raise(self):
        r = _signature(USER_B)
        self.assertTrue(hasattr(r, "status_code"))

    def test_the_lookup_filter_is_unchanged(self):
        """Still `is_deleted`, not ACTIVE_PROJECT_FILTER -- which would turn a
        signature on a just-marked project into a 404 for the CP who needs it."""
        captured = []
        db = MagicMock()
        db.sign_ins.find_one = AsyncMock(return_value=dict(SIGN_IN))

        async def spy(q, *a, **kw):
            captured.append(q)
            return dict(PROJ_A)

        db.projects.find_one = AsyncMock(side_effect=spy)
        db.daily_signatures.find_one = AsyncMock(return_value=None)
        with patch.object(server, "db", db):
            asyncio.run(server.get_signature_image(signin_id=SIGNIN_ID, current_user=MEMBER_A))
        self.assertIn("is_deleted", captured[0])
        self.assertNotIn("marked_for_deletion", captured[0])

    def test_it_uses_project_access_ok(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_signature_image":
                conds = [ast.unparse(n.test) for n in ast.walk(node)
                         if isinstance(n, ast.If)]
                self.assertTrue(any("project_access_ok" in c for c in conds), conds)
                for c in conds:
                    self.assertIsNone(
                        re.search(r"""^company_id\s+and\s+.*\.get\(['"]company_id['"]\).*!=""", c),
                        c)
                return
        self.fail("get_signature_image not found")


class TheSweepCountWentDownBySEVEN(unittest.TestCase):

    def test_the_sweep_agrees_with_the_single_pinned_total(self):
        """NO LITERAL HERE. This class asserted exactly 25 and the very next PR
        broke it -- the same flaw this series already fixed once, reintroduced.
        The total is DESIGNED to keep falling, so it is pinned in exactly one
        place and every other file asserts agreement with it."""
        mod = __import__("test_pm_load_project_fails_closed")
        self.assertEqual(len(mod.sweep_bypass_sites()),
                         mod.TheSweepCountOnlyGoesDOWN.EXPECTED_TOTAL)

    def test_permit_renewal_contributes_nothing_to_the_sweep(self):
        """All six were in it. None should remain."""
        mod = __import__("test_pm_load_project_fails_closed")
        remaining = [h for h in mod.sweep_bypass_sites()
                     if h.startswith("permit_renewal.py")]
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    unittest.main(verbosity=2)
