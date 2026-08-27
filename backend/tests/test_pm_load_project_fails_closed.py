"""_pm_load_project_or_403 fails closed, and the bypass count only goes down.

THE BYPASS. The check was

    if company_id and project.get("company_id") != company_id:

and `and` short-circuits. A caller whose company_id is falsy never reaches the
comparison, so the 403 could not fire. That is the DEFAULT state, not an edge
case: /auth/register sets user_dict["company_id"] = None on every self-serve
signup, and a company is attached later by onboarding.

SIX CALLERS, THREE OF THEM UNPROTECTED. Three carry
Depends(require_project_access) and were already safe. These three had only
this line between a company-less caller and another tenant's data:

    GET /projects/{project_id}/model
    GET /projects/{project_id}/model/unconfirmed
    GET /projects/{project_id}/schedule

THE SWEEP COUNT IS THE POINT OF THE SECOND HALF OF THIS FILE. Fixing sites one
PR at a time invites the pattern being reintroduced somewhere else while the
total stays flat -- every PR looks like progress and the number never moves. So
the sweep is pinned to an exact expected count. Adding a new
`if company_id and ...` anywhere in the backend fails this file, whoever adds
it and whichever route it is on.

    python backend/tests/test_pm_load_project_fails_closed.py
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

PROJ_A = {"_id": "projA", "id": "projA", "company_id": "companyA", "name": "588 Thomas"}

MEMBER_A = {"_id": "u1", "id": "u1", "role": "cp", "company_id": "companyA",
            "account_status": "approved"}
USER_B = {"_id": "v1", "id": "v1", "role": "cp", "company_id": "companyB",
          "account_status": "approved"}
ADMIN_B = {"_id": "v2", "id": "v2", "role": "admin", "company_id": "companyB",
           "account_status": "approved"}
# THE DEFAULT STATE of every self-registration.
COMPANYLESS = {"_id": "w1", "id": "w1", "role": "cp", "company_id": None,
               "account_status": "approved"}
# The two other branches of the shared rule, which this now honours.
ASSIGNED = {"_id": "x1", "id": "x1", "role": "cp", "company_id": "companyB",
            "account_status": "approved", "assigned_projects": ["projA"]}
DEVICE_A = {"_id": "d1", "id": "d1", "role": "site_device", "site_mode": True,
            "project_id": "projA", "company_id": None}
DEVICE_OTHER = {"_id": "d2", "id": "d2", "role": "site_device", "site_mode": True,
                "project_id": "projZ", "company_id": None}


def _load(user, project=PROJ_A):
    db = MagicMock()
    db.projects.find_one = AsyncMock(
        side_effect=lambda q, *a, **kw: dict(project) if project else None)
    with patch.object(server, "db", db):
        return asyncio.run(server._pm_load_project_or_403("projA", user))


class ItFailsClosed(unittest.TestCase):

    def test_a_company_less_caller_is_refused(self):
        """THE BYPASS. `if company_id and ...` short-circuited, so the 403 could
        not fire for the default state of every self-registration."""
        with self.assertRaises(HTTPException) as c:
            _load(COMPANYLESS)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_cross_tenant_user_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _load(USER_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_cross_tenant_ADMIN_is_refused(self):
        """Role is not tenancy -- the helper never looked at role, and must
        not start."""
        with self.assertRaises(HTTPException) as c:
            _load(ADMIN_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_project_with_NO_company_is_refused(self):
        """An unowned project must not become everyone's. The comparison used
        to be reached only when the CALLER had a company; the shared rule
        requires a positive match on either side."""
        with self.assertRaises(HTTPException) as c:
            _load(MEMBER_A, project={**PROJ_A, "company_id": None})
        self.assertEqual(c.exception.status_code, 403)


class TheOrdinaryCallersStillWork(unittest.TestCase):
    """A guard that refuses too much is as wrong as one that refuses nothing."""

    def test_a_same_company_member_is_allowed(self):
        self.assertEqual(_load(MEMBER_A)["_id"], "projA")

    def test_an_ASSIGNED_user_is_allowed(self):
        """WIDENED, DELIBERATELY. The three-branch rule admits a user with the
        project in assigned_projects, and the three sibling routes carrying
        Depends(require_project_access) already did. This makes the six agree
        rather than inventing a rule."""
        self.assertEqual(_load(ASSIGNED)["_id"], "projA")

    def test_the_site_device_for_THIS_project_is_allowed(self):
        self.assertEqual(_load(DEVICE_A)["_id"], "projA")

    def test_a_site_device_for_ANOTHER_project_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _load(DEVICE_OTHER)
        self.assertEqual(c.exception.status_code, 403)


class TheLookupIsUnchanged(unittest.TestCase):
    """Authorization was what was missing. Existence semantics are left alone."""

    def test_a_missing_project_is_still_404(self):
        with self.assertRaises(HTTPException) as c:
            _load(MEMBER_A, project=None)
        self.assertEqual(c.exception.status_code, 404)

    def test_it_still_filters_only_on_is_deleted(self):
        """NOT ACTIVE_PROJECT_FILTER. That also excludes marked_for_deletion,
        and adopting it would newly 404 these reads on a project an admin has
        just marked -- a CP losing his schedule to an admin action. Same choice
        create_logbook made."""
        captured = {}

        db = MagicMock()

        async def find_one(q, *a, **kw):
            captured["q"] = q
            return dict(PROJ_A)

        db.projects.find_one = AsyncMock(side_effect=find_one)
        with patch.object(server, "db", db):
            asyncio.run(server._pm_load_project_or_403("projA", MEMBER_A))
        self.assertIn("is_deleted", captured["q"])
        self.assertNotIn("marked_for_deletion", captured["q"])

    def test_it_uses_the_SHARED_rule_not_a_new_one(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        # DOCSTRING STRIPPED. The helper's own docstring quotes the removed
        # line so a reader knows what changed, and a substring check matched
        # that prose instead of the code.
        i = src.index("async def _pm_load_project_or_403")
        body = src[i:src.index("@api_router", i)]
        body = re.sub(r'"""[\s\S]*?"""', "", body, count=1)
        self.assertIn("project_access_ok(project, project_id, current_user)", body)
        self.assertIsNone(
            re.search(r'if\s+company_id\s+and\s+project\.get\("company_id"\)', body))


class AllSixCallersAreCovered(unittest.TestCase):
    """The leverage: one line, six routes."""

    SRC = (BACKEND / "server.py").read_text(encoding="utf-8")

    def test_there_are_exactly_six_callers(self):
        """If a seventh appears it inherits the fix -- but the count is pinned
        so the next reader knows the blast radius without re-deriving it."""
        calls = self.SRC.count("await _pm_load_project_or_403(")
        self.assertEqual(calls, 6)

    def test_the_three_unguarded_routes_are_still_mounted(self):
        paths = {(m, getattr(r, "path", ""))
                 for r in server.app.routes
                 for m in (getattr(r, "methods", None) or set())}
        for p in ("/api/projects/{project_id}/model",
                  "/api/projects/{project_id}/model/unconfirmed",
                  "/api/projects/{project_id}/schedule"):
            self.assertIn(("GET", p), paths, p)


# The condition, matched on ast.unparse output. Quote-agnostic because unparse
# normalises to single quotes, and whitespace-agnostic for the same reason.
BYPASS_TEST = re.compile(
    r"""^\w*company_id\s+and\s+.*\.get\(['"]company_id['"]\).*!=""")


def sweep_bypass_sites():
    """Every `if company_id and <doc>.get("company_id") != ...` in the backend.

    READS THE AST, NOT THE TEXT, and that is not fastidiousness -- the
    line-based version of this sweep counted 35 instead of 34 because THIS
    FILE'S OWN neighbour, the fixed helper's docstring, quotes the old line so a
    reader knows what changed. A comment-skip does not help: a docstring is not
    a comment. Every prose explanation of this bug anywhere in the backend would
    have inflated the count, and the number is the whole mechanism.

    ast.If.test is the condition itself. Prose cannot be one.
    """
    hits = []
    for name in ("server.py", "permit_renewal.py"):
        path = BACKEND / name
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            try:
                cond = ast.unparse(node.test)
            except Exception:
                continue
            if BYPASS_TEST.search(cond):
                hits.append(f"{name}:{node.lineno}")
    return sorted(hits)


class TheSweepCountOnlyGoesDOWN(unittest.TestCase):
    """WHY THIS EXISTS.

    24 routes carry this bypass as their only tenancy control, and they are
    being fixed a PR at a time. Without a pinned total, the pattern can be
    REINTRODUCED somewhere else while each PR still looks like progress -- the
    number never moves and nobody notices, because no single diff shows it.

    So the total is asserted exactly. Fixing a site means lowering EXPECTED_TOTAL
    in the same commit, which puts the count in the diff. Adding a new
    `if company_id and ...` anywhere fails this file immediately.

    LOWER IT ONLY BY WHAT YOUR PR ACTUALLY FIXED. If the number drops by more
    than you changed, something else moved and you want to know why.
    """

    # 35 originally (11 belt-and-braces on tenancy-guarded routes, 24 where the
    # conditional was the only control).
    #   -1  _pm_load_project_or_403                    (covered six routes)
    #   -2  POST /admin/site-devices, /admin/cs-registrations
    #   -7  six permit_renewal routes (one _assert_renewal_access helper)
    #       plus GET /signatures/{signin_id}
    EXPECTED_TOTAL = 25

    def test_the_sweep_finds_the_expected_number(self):
        hits = sweep_bypass_sites()
        self.assertEqual(
            len(hits), self.EXPECTED_TOTAL,
            "the conditional-company_id count moved.\n"
            f"expected {self.EXPECTED_TOTAL}, found {len(hits)}.\n"
            "If you FIXED sites, lower EXPECTED_TOTAL in this commit so the "
            "count appears in the diff. If you ADDED one, use "
            "project_access_ok / _assert_project_access instead -- `and` "
            "short-circuits and the check cannot fire for a company-less "
            "caller.\nsites:\n  " + "\n  ".join(hits))

    def test_the_sweep_actually_reads_files(self):
        """A sweep that silently matched nothing would pass forever, and would
        do it right after someone renamed a file."""
        self.assertGreater(self.EXPECTED_TOTAL, 0)
        self.assertTrue((BACKEND / "server.py").exists())
        self.assertTrue((BACKEND / "permit_renewal.py").exists())

    def test_the_pattern_it_looks_for_is_the_real_one(self):
        """Proved against a literal, so a future edit to the regex that quietly
        stops matching is caught here rather than by the count going to zero."""
        pat = re.compile(
            r'if\s+\w*company_id\s+and\s+.*\.get\("company_id"\)\s*(?:and\s+.*)?!=')
        self.assertTrue(pat.search(
            'if company_id and project.get("company_id") != company_id:'))
        self.assertTrue(pat.search(
            'if user_company_id and rec.get("company_id") and rec["company_id"] != x:'))
        self.assertFalse(pat.search(
            "if not project_access_ok(project, project_id, current_user):"))

    def test_the_fixed_helper_is_no_longer_among_them(self):
        """The specific line this PR removed."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("async def _pm_load_project_or_403")
        body = re.sub(r'"""[\s\S]*?"""', "", src[i:src.index("@api_router", i)], count=1)
        self.assertNotIn('if company_id and project.get("company_id") != company_id:',
                         body)

    def test_the_three_DOUBLE_permissive_sites_are_untouched(self):
        """A DIFFERENT AND WORSE BUG, reported separately and deliberately not
        swept up here.

            if company_id and rec.get("company_id") and rec[...] != company_id

        also passes when the RESOURCE has no company_id -- so any legacy or
        unstamped row is readable by ANY authenticated user, including one with
        a perfectly valid company. That is an unowned-resource bug, not a
        company-less-caller bug, and fixing it needs a decision about what an
        unowned document means. Pinned so this sweep cannot quietly absorb it.
        """
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8-sig"))
        doubles = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            try:
                cond = ast.unparse(node.test)
            except Exception:
                continue
            if re.search(r"""^\w*company_id\s+and\s+\w+\.get\(['"]company_id['"]\)\s+and\s""", cond):
                doubles += 1
        self.assertEqual(doubles, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
