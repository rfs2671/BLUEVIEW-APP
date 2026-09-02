"""GET /projects/{project_id}/document-index-status is scoped to the project.

WHAT WAS OPEN. The route was declared

    @api_router.get("/projects/{project_id}/document-index-status")
    async def get_document_index_status(
        project_id: str,
        current_user=Depends(get_current_user),
    ):

with `get_current_user` and nothing else -- no `require_project_access`, and no
lookup of the project at all. Its only tenancy term was the conditional filter

    company_id = get_user_company_id(current_user)
    query: Dict[str, Any] = {"project_id": project_id}
    if company_id:
        query["company_id"] = company_id

which is the falsy short-circuit this codebase has been closing a PR at a time.
`/auth/register` sets `company_id = None` on every self-serve signup, so the
company term is DROPPED for the default state of a new account, and the query
degenerates to `{"project_id": <whatever the caller typed>}`.

WHY IT MATTERS MORE THAN A LISTING. This route serves no file bytes, no r2_key
and no link. It returns the NAME of every PDF on the project and each one's
`file_id` -- and `stream_project_file` takes a `file_id`. The index is the map.

A SECOND HOLE THE COMPANY FILTER COULD NOT HAVE CLOSED EITHER. `project_files`
rows are written `company_id = company_id or project.get("company_id")`, which
resolves to None for an unowned row, and `{"company_id": None}` is a MATCHING
filter in Mongo, not an empty one. So even a caller WITH a company could read
unowned rows on another tenant's project. Scoping the PROJECT, not the rows, is
what actually fixes this -- which is why the fix is the shared dependency and
not a stricter query.

THE FIX IS THE SIBLING PATTERN, NOT A NEW ONE. The three other routes on this
same resource already read

    dependencies=[Depends(require_approved), Depends(require_project_access)]

    POST /projects/{project_id}/reindex-document      (:37313)
    POST /projects/{project_id}/reindex-all           (:37369)
    POST /projects/{project_id}/debug/test-plan-image-send

and `reindex-document` is called from the SAME screen, by the same component,
against the same file_id this route hands out.

THE DELETION FILTER, CHECKED AND NOT ASSUMED. `require_project_access` resolves
through `_assert_project_access`, which applies ACTIVE_PROJECT_FILTER and so
404s a project an admin has marked for deletion. The ruling in
test_project_path_reads_fail_closed.py was to PRESERVE each route's existing
lookup rather than newly adopt that filter. This route is not one of those ten
and the ruling does not reach it: it has NO project lookup to preserve, and its
only caller cannot reach a marked-for-deletion project anyway --
`frontend/app/projects/[id]/whatsapp-groups.jsx:127` calls it inside the same
`Promise.all` as `projectsAPI.getById(projectId)`, which is GET
/projects/{project_id}, which has used **ACTIVE_PROJECT_FILTER since before this
series. The screen is already 404 for such a project, and the index call is
wrapped `.catch(() => null)`.

SITE DEVICES STILL REACH IT, which matters because a branch in flight
(feat/site-device-per-file-visibility) adds a `site_visible` read filter to this
same handler and needs the device to get here. `require_approved` returns early
for site_mode, and `project_access_ok` branch 1 admits a device on the ONE
project it was provisioned for. Both are asserted below so the two changes
compose rather than fight.

    python backend/tests/test_document_index_status_project_access.py
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
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

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8-sig")
TREE = ast.parse(SRC)

ROUTE = "/api/projects/projB/document-index-status"

# ── Two tenants ─────────────────────────────────────────────────────────────
# projB belongs to companyB. Everything below asks for projB.
PROJ_B = {"_id": "projB", "id": "projB", "company_id": "companyB",
          "name": "588 Thomas"}

# The file rows on projB. THE SECOND ONE IS UNOWNED -- company_id None -- which
# is the shape the conditional filter could never have excluded for a caller
# who HAS a company, because {"company_id": None} matches it.
FILES_B = [
    {"_id": "f1", "name": "A-101 Foundation Plan.pdf",
     "company_id": "companyB", "project_id": "projB", "r2_key": ""},
    {"_id": "f2", "name": "S-201 Shoring Sequence.pdf",
     "company_id": None, "project_id": "projB", "r2_key": ""},
]

INTRUDER_COMPANY_A = {
    "_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
    "account_status": "approved", "full_name": "Admin of another tenant",
    "assigned_projects": [],
}

# THE DEFAULT STATE OF A SELF-SERVE SIGNUP. /auth/register writes
# company_id = None, and this is what the conditional filter waved through.
INTRUDER_NO_COMPANY = {
    "_id": "u2", "id": "u2", "role": "cp", "company_id": None,
    "account_status": "approved", "full_name": "Freshly registered",
    "assigned_projects": [],
}

# ── The people who must still be served ─────────────────────────────────────
SAME_COMPANY = {
    "_id": "u3", "id": "u3", "role": "admin", "company_id": "companyB",
    "account_status": "approved", "full_name": "Admin of companyB",
    "assigned_projects": [],
}

# Branch 3: no company match, but explicitly assigned. A superintendent or CP.
ASSIGNED_USER = {
    "_id": "u4", "id": "u4", "role": "cp", "company_id": "companyC",
    "account_status": "approved", "full_name": "Assigned CP",
    "assigned_projects": ["projB"],
}

SITE_DEVICE_ON_PROJ_B = {
    "_id": "d1", "id": "d1", "role": "site_device", "site_mode": True,
    "company_id": "companyB", "project_id": "projB",
    "full_name": "Gate tablet",
}

SITE_DEVICE_ELSEWHERE = {
    "_id": "d2", "id": "d2", "role": "site_device", "site_mode": True,
    "company_id": "companyB", "project_id": "projOTHER",
    "full_name": "Another job's tablet",
}


# ── A fake Mongo just wide enough for this handler ──────────────────────────
class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return list(self._docs)[: (n or len(self._docs))]


class _Collection:
    def __init__(self, name, db):
        self.name = name
        self.db = db

    def find(self, query=None, *a, **k):
        return _Cursor(self.db.rows_for(self.name, query or {}))

    async def find_one(self, query=None, *a, **k):
        rows = self.db.rows_for(self.name, query or {})
        return rows[0] if rows else None

    async def count_documents(self, query=None, *a, **k):
        return len(self.db.rows_for(self.name, query or {}))


class _FakeDb:
    """Honours the two query terms this test actually depends on: the project
    lookup's `_id` + deletion filter, and project_files' `project_id`."""

    def __init__(self, *, project=PROJ_B, files=None):
        self.project = project
        self.files = FILES_B if files is None else files
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._c.setdefault(n, _Collection(n, self))

    def rows_for(self, name, query):
        if name == "projects":
            p = self.project
            if p is None:
                return []
            if "_id" in query and str(query["_id"]) != str(p.get("_id")):
                return []
            # ACTIVE_PROJECT_FILTER, applied the way Mongo would
            for field in ("is_deleted", "marked_for_deletion"):
                if field in query and p.get(field) is True:
                    return []
            return [p]
        if name == "project_files":
            out = []
            for r in self.files:
                if "project_id" in query and r.get("project_id") != query["project_id"]:
                    continue
                if "company_id" in query and r.get("company_id") != query["company_id"]:
                    continue
                out.append(r)
            return out
        return []


def _call(user, *, db=None, route=ROUTE):
    """Only get_current_user is overridden. require_approved and
    require_project_access are the REAL ones -- overriding them would test
    nothing."""
    async def _fake_user():
        return dict(user)

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db or _FakeDb()), \
                patch.object(server, "_r2_client", None):
            return TestClient(server.app).get(route)
    finally:
        server.app.dependency_overrides.clear()


class TheCrossTenantRefusal(unittest.TestCase):
    """The one that matters: company A must not read company B's index."""

    def test_an_admin_of_company_A_is_refused_company_Bs_project(self):
        resp = _call(INTRUDER_COMPANY_A)
        self.assertEqual(
            resp.status_code, 403,
            "an admin of another tenant read projB's document index: "
            f"{resp.status_code} {resp.text[:400]}")

    def test_the_refusal_discloses_no_file_name(self):
        """A 200 is the bug; a 403 whose body still carried the names would be
        the same bug wearing a status code."""
        body = _call(INTRUDER_COMPANY_A).text
        for f in FILES_B:
            self.assertNotIn(f["name"], body, f"{f['name']} leaked in the refusal")

    def test_no_file_id_leaks_either(self):
        """The file_id is the half that matters -- stream_project_file takes
        one."""
        body = _call(INTRUDER_COMPANY_A).text
        self.assertNotIn("f1", body)
        self.assertNotIn("f2", body)

    def test_a_company_less_caller_is_refused(self):
        """THE DEFAULT STATE. /auth/register sets company_id = None, so this is
        every self-serve signup until onboarding attaches a company. Under the
        conditional filter this caller was served the whole index."""
        resp = _call(INTRUDER_NO_COMPANY)
        self.assertEqual(
            resp.status_code, 403,
            "a caller with company_id None read projB's document index: "
            f"{resp.status_code} {resp.text[:400]}")

    def test_a_company_less_caller_sees_no_names(self):
        body = _call(INTRUDER_NO_COMPANY).text
        for f in FILES_B:
            self.assertNotIn(f["name"], body)

    def test_an_unknown_project_is_not_a_way_in(self):
        resp = _call(INTRUDER_COMPANY_A, db=_FakeDb(project=None))
        self.assertIn(resp.status_code, (403, 404), resp.text[:400])


class TheLegitimateCallersAreStillServed(unittest.TestCase):
    """Asserted as hard as the refusals. A gate that only refuses is easy."""

    def test_the_same_company_admin_is_served(self):
        resp = _call(SAME_COMPANY)
        self.assertEqual(resp.status_code, 200, resp.text[:400])
        names = {f["file_name"] for f in resp.json()["files"]}
        self.assertIn("A-101 Foundation Plan.pdf", names)

    def test_the_ASSIGNED_user_is_served_though_his_company_differs(self):
        """project_access_ok branch 3. A superintendent or CP assigned to the
        job whose own company_id does not match the project's -- historical
        rows predate validate_assignable_projects, and the branch stays."""
        resp = _call(ASSIGNED_USER)
        self.assertEqual(
            resp.status_code, 200,
            "an explicitly assigned user lost a read he had: "
            f"{resp.status_code} {resp.text[:400]}")
        names = {f["file_name"] for f in resp.json()["files"]}
        self.assertIn("A-101 Foundation Plan.pdf", names)

    def test_the_unowned_row_is_reachable_by_the_people_who_own_the_project(self):
        """The scoping moved to the PROJECT, so a project_files row with
        company_id None is no longer invisible to its own tenant -- and no
        longer readable by everyone else. Both halves are the point."""
        resp = _call(SAME_COMPANY)
        names = {f["file_name"] for f in resp.json()["files"]}
        self.assertIn("S-201 Shoring Sequence.pdf", names)

    def test_the_qwen_flag_still_comes_back(self):
        self.assertIn("qwen_configured", _call(SAME_COMPANY).json())


class TheSiteDeviceStillReachesIt(unittest.TestCase):
    """feat/site-device-per-file-visibility adds a `site_visible` filter INSIDE
    this handler. It is only reachable if the device gets past the gate."""

    def test_a_device_reaches_the_project_it_was_provisioned_for(self):
        resp = _call(SITE_DEVICE_ON_PROJ_B)
        self.assertEqual(
            resp.status_code, 200,
            "the gate tablet lost its own project: "
            f"{resp.status_code} {resp.text[:400]}")

    def test_a_device_is_refused_any_OTHER_project(self):
        resp = _call(SITE_DEVICE_ELSEWHERE)
        self.assertEqual(resp.status_code, 403, resp.text[:400])

    def test_require_approved_does_not_catch_a_device(self):
        """A site device carries no account_status. require_approved returns
        early for site_mode; if that ever changed, check-in-adjacent screens
        would start 403ing and this says which dependency did it."""
        self.assertIsNone(SITE_DEVICE_ON_PROJ_B.get("account_status"))
        self.assertEqual(_call(SITE_DEVICE_ON_PROJ_B).status_code, 200)


class ThePendingAccountIsRefused(unittest.TestCase):
    """require_approved, the other half of the sibling pattern. This route does
    an R2 GET and a full pypdf parse per file, up to 500 files, in the request
    -- it is resource-bearing, which is what that dependency is for."""

    def test_a_pending_account_of_the_owning_company_is_refused(self):
        pending = dict(SAME_COMPANY, account_status="pending")
        resp = _call(pending)
        self.assertEqual(resp.status_code, 403, resp.text[:400])
        self.assertIn("account_pending", resp.text)


DEBUG_ROUTE = "/api/projects/projB/debug/indexed-pages"


class TheTwinIsFixedToo(unittest.TestCase):
    """GET /projects/{project_id}/debug/indexed-pages, forty lines above, held
    the identical defect: `if company_id:` and a ROLE gate mistaken for a
    tenant gate.

    "owner" is the role every self-serve signup receives and /auth/register
    sets company_id = None, so the default state of a brand-new account passed
    the role check AND skipped the company term. Leaving it while fixing its
    twin would be fixing one of a matched pair."""

    OWNER_NO_COMPANY = {
        "_id": "u9", "id": "u9", "role": "owner", "company_id": None,
        "account_status": "approved", "full_name": "Freshly registered owner",
        "assigned_projects": [],
    }

    def test_the_default_self_serve_owner_is_refused(self):
        resp = _call(self.OWNER_NO_COMPANY, route=DEBUG_ROUTE)
        self.assertEqual(
            resp.status_code, 403,
            "a company-less owner read projB's page index: "
            f"{resp.status_code} {resp.text[:400]}")

    def test_an_admin_of_another_company_is_refused(self):
        resp = _call(INTRUDER_COMPANY_A, route=DEBUG_ROUTE)
        self.assertEqual(resp.status_code, 403, resp.text[:400])

    def test_the_owning_companys_admin_is_still_served(self):
        resp = _call(SAME_COMPANY, route=DEBUG_ROUTE)
        self.assertEqual(resp.status_code, 200, resp.text[:400])

    def test_the_ROLE_gate_is_kept_not_replaced(self):
        """Who may run a diagnostic is a different question from which project
        it may run against. A CP assigned to the job passes
        require_project_access and must STILL be refused here."""
        resp = _call(ASSIGNED_USER, route=DEBUG_ROUTE)
        self.assertEqual(resp.status_code, 403, resp.text[:400])
        self.assertIn("Admin access required", resp.text)

    def test_it_carries_the_same_pair(self):
        for node in ast.walk(TREE):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == "debug_indexed_pages":
                deco = " ".join(ast.unparse(d) for d in node.decorator_list)
                self.assertIn(
                    "Depends(require_approved), Depends(require_project_access)",
                    deco)
                return
        raise AssertionError("debug_indexed_pages not found")


class ItIsDeclaredTheWayItsSiblingsAre(unittest.TestCase):
    """Read as CODE, not as text -- this file's own docstring quotes the old
    declaration, and a substring check would match the prose."""

    SIBLINGS = [
        "reindex_project_document",
        "reindex_all_project_files",
    ]

    def _decorator_src(self, name):
        for node in ast.walk(TREE):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == name:
                return " ".join(ast.unparse(d) for d in node.decorator_list)
        raise AssertionError(f"{name} not found in server.py")

    def test_it_carries_both_dependencies(self):
        deco = self._decorator_src("get_document_index_status")
        self.assertIn("require_project_access", deco)
        self.assertIn("require_approved", deco)

    def test_the_pair_and_the_ORDER_match_the_siblings_on_this_resource(self):
        """Not a style point. require_approved is the cheaper check and the
        one whose 403 is actionable by the user ('your account is pending');
        running it first is what the siblings do."""
        mine = self._decorator_src("get_document_index_status")
        for sib in self.SIBLINGS:
            with self.subTest(sibling=sib):
                sib_src = self._decorator_src(sib)
                self.assertIn("Depends(require_approved), Depends(require_project_access)",
                              sib_src, f"{sib} is not the pattern this claims to match")
        self.assertIn("Depends(require_approved), Depends(require_project_access)", mine)

    def test_it_is_still_a_GET_on_the_same_path(self):
        paths = {(m, getattr(r, "path", ""))
                 for r in server.app.routes
                 for m in (getattr(r, "methods", None) or set())}
        self.assertIn(
            ("GET", "/api/projects/{project_id}/document-index-status"), paths)

    def test_the_handler_no_longer_carries_a_conditional_company_filter(self):
        """The dead local is how a reader concludes a check still exists."""
        fn = None
        for node in ast.walk(TREE):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == "get_document_index_status":
                fn = node
        self.assertIsNotNone(fn)
        assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "company_id"
                           for t in n.targets)]
        reads = [n for n in ast.walk(fn) if isinstance(n, ast.Name)
                 and n.id == "company_id" and isinstance(n.ctx, ast.Load)]
        if assigns:
            self.assertTrue(
                reads, "get_document_index_status assigns company_id and never reads it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
