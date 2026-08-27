"""An unowned document is refused, not admitted.

THE DOUBLE-PERMISSIVE BUG. Three sites read

    if company_id and rec.get("company_id") and rec["company_id"] != company_id:

which has TWO ways to fall through:

  * a falsy CALLER company -- the short-circuit closed everywhere else in this
    series, and the DEFAULT state of a self-serve signup;
  * a falsy DOCUMENT company -- a property of the DATA, not the account. Any
    unowned row was readable, writable or deletable by ANY authenticated user,
    including one with a perfectly valid company.

The second is why this was split out of the sweep. You cannot find it by
auditing users, and closing it needs a decision the other PRs never had to
make: what an unowned document means.

    17048  GET    /projects/{id}/files/{file_id}/content   project_files
    17101  DELETE /projects/{id}/files/{file_id}           project_files
    32910  PUT    /whatsapp-checklists/{id}/items/{i}      whatsapp_checklists

"" IS ABSENT, NOT A VALUE, and it is the case a careless audit misses. The
whatsapp_checklists writers stamp it deliberately --
`"company_id": company_id or ""` -- so an unowned checklist is PRESENT and
EMPTY. A guard or a count query testing `$exists` would have read clean while
every item on every such row was toggleable by anyone. project_files can hold
null instead. Absent, null and "" are ONE state, and each is tested separately
below: a test covering only null would pass while "" still bypassed.

PREVENTION ONLY. Production held zero unowned rows in both collections
(project_files: 10, all string; whatsapp_checklists: empty), so nothing becomes
unreachable and no backfill is needed.

    python backend/tests/test_unowned_documents_fail_closed.py
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

MEMBER_A = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
            "account_status": "approved"}
USER_B = {"_id": "v1", "id": "v1", "role": "admin", "company_id": "companyB",
          "account_status": "approved"}
COMPANYLESS = {"_id": "w1", "id": "w1", "role": "admin", "company_id": None,
               "account_status": "approved"}

# THE THREE FACES OF UNOWNED. Each is tested on its own: one that covered only
# `null` would pass while "" still bypassed, which is the whole point.
OWNED = {"company_id": "companyA"}
UNOWNED_NULL = {"company_id": None}
UNOWNED_EMPTY = {"company_id": ""}          # what whatsapp_checklists writes
UNOWNED_MISSING = {}                        # no key at all
UNOWNED_BLANK = {"company_id": "   "}       # whitespace is not ownership


class TheHelper(unittest.TestCase):
    """_same_company_or_403 is the rule; the routes below are its callers."""

    def _call(self, doc, user):
        server._same_company_or_403(doc, user)

    def test_a_matching_company_is_allowed(self):
        self._call(OWNED, MEMBER_A)              # no raise

    def test_a_different_company_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            self._call(OWNED, USER_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_a_company_less_CALLER_is_refused(self):
        """The short-circuit half."""
        with self.assertRaises(HTTPException):
            self._call(OWNED, COMPANYLESS)

    def test_a_NULL_document_company_is_refused(self):
        with self.assertRaises(HTTPException):
            self._call(UNOWNED_NULL, MEMBER_A)

    def test_an_EMPTY_STRING_document_company_is_refused(self):
        """THE ONE AN $exists AUDIT MISSES. whatsapp_checklists writes
        `company_id or ""`, so this is the shape an unowned row actually has."""
        with self.assertRaises(HTTPException):
            self._call(UNOWNED_EMPTY, MEMBER_A)

    def test_a_MISSING_document_company_is_refused(self):
        with self.assertRaises(HTTPException):
            self._call(UNOWNED_MISSING, MEMBER_A)

    def test_a_WHITESPACE_document_company_is_refused(self):
        with self.assertRaises(HTTPException):
            self._call(UNOWNED_BLANK, MEMBER_A)

    def test_a_whitespace_CALLER_company_is_refused(self):
        with self.assertRaises(HTTPException):
            self._call(OWNED, {**MEMBER_A, "company_id": "   "})

    def test_None_document_is_refused_not_a_crash(self):
        with self.assertRaises(HTTPException):
            self._call(None, MEMBER_A)

    def test_it_does_not_admit_on_a_TYPE_mismatch(self):
        """Both sides are coerced to str, so an ObjectId-vs-str comparison
        cannot silently refuse a legitimate owner -- nor admit a stranger."""
        with self.assertRaises(HTTPException):
            self._call({"company_id": "companyAA"}, MEMBER_A)

    def test_there_is_no_assigned_projects_branch(self):
        """DELIBERATELY NARROWER than project_access_ok. A per-project
        assignment says nothing about a company-level document."""
        assigned = {**USER_B, "assigned_projects": ["projA"]}
        with self.assertRaises(HTTPException):
            self._call(OWNED, assigned)


# ── The three routes ────────────────────────────────────────────────────────
FILE_ID = "6a8c4acd0000000000000002"


def _file_route(fn, rec, user):
    db = MagicMock()
    db.project_files.find_one = AsyncMock(
        side_effect=lambda q, *a, **kw: dict(rec) if rec is not None else None)
    db.project_files.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()), \
         patch.object(server, "_r2_client", None):
        return asyncio.run(fn(project_id="projA", file_id=FILE_ID, current_user=user))


def _checklist(doc, user):
    db = MagicMock()
    db.whatsapp_checklists.find_one = AsyncMock(
        side_effect=lambda q, *a, **kw: dict(doc) if doc is not None else None)
    db.whatsapp_checklists.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    with patch.object(server, "db", db):
        return asyncio.run(server.update_whatsapp_checklist_item(
            checklist_id="c1", item_index=0, body={"completed": True},
            current_user=user))


FILE_OWNED = {"_id": FILE_ID, "project_id": "projA", "company_id": "companyA",
              "r2_key": "k/1", "filename": "A-101.pdf"}
CHECKLIST_OWNED = {"_id": "c1", "company_id": "companyA",
                   "items": [{"text": "x", "completed": False}]}


class StreamProjectFileIsScoped(unittest.TestCase):

    def _refused(self, rec, user=MEMBER_A):
        with self.assertRaises(HTTPException) as c:
            _file_route(server.stream_project_file, rec, user)
        self.assertEqual(c.exception.status_code, 403)

    def test_an_unowned_NULL_file_is_refused(self):
        self._refused({**FILE_OWNED, "company_id": None})

    def test_an_unowned_EMPTY_file_is_refused(self):
        self._refused({**FILE_OWNED, "company_id": ""})

    def test_an_unowned_MISSING_file_is_refused(self):
        rec = {k: v for k, v in FILE_OWNED.items() if k != "company_id"}
        self._refused(rec)

    def test_a_cross_tenant_caller_is_refused(self):
        self._refused(FILE_OWNED, USER_B)

    def test_a_company_less_caller_is_refused(self):
        self._refused(FILE_OWNED, COMPANYLESS)

    def test_the_owner_gets_past_the_guard(self):
        """R2 is stubbed out, so the correct downstream answer is 404
        'File not stored in R2' -- NOT 403."""
        with self.assertRaises(HTTPException) as c:
            _file_route(server.stream_project_file, FILE_OWNED, MEMBER_A)
        self.assertEqual(c.exception.status_code, 404)


class DeleteProjectFileIsScoped(unittest.TestCase):
    """The route already carries a dependency, so this line was unreachable --
    but it was still wrong, and the next person to move this handler would have
    inherited a hole with no test naming it."""

    def _refused(self, rec, user=MEMBER_A):
        with self.assertRaises(HTTPException) as c:
            _file_route(server.delete_project_file, rec, user)
        self.assertEqual(c.exception.status_code, 403)

    def test_an_unowned_NULL_file_is_refused(self):
        self._refused({**FILE_OWNED, "company_id": None})

    def test_an_unowned_EMPTY_file_is_refused(self):
        self._refused({**FILE_OWNED, "company_id": ""})

    def test_an_unowned_MISSING_file_is_refused(self):
        self._refused({k: v for k, v in FILE_OWNED.items() if k != "company_id"})

    def test_a_cross_tenant_ADMIN_is_refused(self):
        self._refused(FILE_OWNED, USER_B)

    def test_the_role_gate_still_fires_first(self):
        """Unchanged: only owner/admin may hard-delete. A CP is refused on ROLE
        before tenancy is considered."""
        cp = {**MEMBER_A, "role": "cp"}
        with self.assertRaises(HTTPException) as c:
            _file_route(server.delete_project_file, FILE_OWNED, cp)
        self.assertEqual(c.exception.status_code, 403)
        self.assertIn("delete files", str(c.exception.detail))


class WhatsappChecklistItemIsScoped(unittest.TestCase):

    def _refused(self, doc, user=MEMBER_A):
        with self.assertRaises(HTTPException) as c:
            _checklist(doc, user)
        self.assertEqual(c.exception.status_code, 403)

    def test_an_EMPTY_company_checklist_is_refused(self):
        """THE SHAPE THIS COLLECTION ACTUALLY WRITES. Both writers stamp
        `company_id or ""`, so this is what an unowned checklist looks like --
        and it is exactly what an $exists check would have missed."""
        self._refused({**CHECKLIST_OWNED, "company_id": ""})

    def test_a_NULL_company_checklist_is_refused(self):
        self._refused({**CHECKLIST_OWNED, "company_id": None})

    def test_a_MISSING_company_checklist_is_refused(self):
        self._refused({k: v for k, v in CHECKLIST_OWNED.items() if k != "company_id"})

    def test_a_cross_tenant_caller_is_refused(self):
        self._refused(CHECKLIST_OWNED, USER_B)

    def test_a_company_less_caller_is_refused(self):
        self._refused(CHECKLIST_OWNED, COMPANYLESS)

    def test_nothing_is_written_when_refused(self):
        db = MagicMock()
        db.whatsapp_checklists.find_one = AsyncMock(
            return_value={**CHECKLIST_OWNED, "company_id": ""})
        db.whatsapp_checklists.update_one = AsyncMock()
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException):
                asyncio.run(server.update_whatsapp_checklist_item(
                    checklist_id="c1", item_index=0, body={"completed": True},
                    current_user=MEMBER_A))
        db.whatsapp_checklists.update_one.assert_not_awaited()

    def test_the_owner_may_still_toggle(self):
        out = _checklist(CHECKLIST_OWNED, MEMBER_A)
        self.assertIsNotNone(out)

    def test_the_422_still_fires_before_the_guard(self):
        """A malformed body is a client error, not a permissions one."""
        db = MagicMock()
        db.whatsapp_checklists.find_one = AsyncMock(return_value=dict(CHECKLIST_OWNED))
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as c:
                asyncio.run(server.update_whatsapp_checklist_item(
                    checklist_id="c1", item_index=0, body={},
                    current_user=USER_B))
        self.assertEqual(c.exception.status_code, 422)


class NoDoublePermissiveLineSurvives(unittest.TestCase):
    """Read as CODE -- the helper's docstring quotes the removed line."""

    SRC = (BACKEND / "server.py").read_text(encoding="utf-8-sig")

    def test_none_remain_anywhere_in_the_backend(self):
        found = []
        for name in ("server.py", "permit_renewal.py"):
            tree = ast.parse((BACKEND / name).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.If):
                    continue
                cond = ast.unparse(node.test)
                if re.search(
                        r"""^\w*company_id\s+and\s+\w+\.get\(['"]company_id['"]\)\s+and\s""",
                        cond):
                    found.append(f"{name}:{node.lineno} {cond}")
        self.assertEqual(found, [])

    def test_all_three_sites_call_the_shared_helper(self):
        tree = ast.parse(self.SRC)
        calls = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_same_company_or_403")
        self.assertEqual(calls, 3)

    def test_the_helper_treats_empty_string_as_absent(self):
        """The mechanism, not just the outcome: both sides are coerced and
        stripped, so "", "   ", None and absent collapse to one state."""
        fn = None
        for node in ast.walk(ast.parse(self.SRC)):
            if isinstance(node, ast.FunctionDef) and node.name == "_same_company_or_403":
                fn = node
        self.assertIsNotNone(fn)
        body = ast.unparse(fn)
        self.assertIn(".strip()", body)
        self.assertIn("not caller", body)
        self.assertIn("not owner", body)

    def test_the_reason_the_empty_string_matters_is_recorded(self):
        """Without it, the next reader deletes the strip() as noise."""
        i = self.SRC.index("def _same_company_or_403")
        doc = self.SRC[i:i + 2600]
        self.assertIn("whatsapp_checklists", doc)
        self.assertIn("$exists", doc)


class TheSweepIsDown(unittest.TestCase):

    def test_the_sweep_matches_the_single_pinned_total(self):
        mod = __import__("test_pm_load_project_fails_closed")
        self.assertEqual(len(mod.sweep_bypass_sites()),
                         mod.TheSweepCountOnlyGoesDOWN.EXPECTED_TOTAL)

    def test_the_total_is_now_12(self):
        mod = __import__("test_pm_load_project_fails_closed")
        self.assertEqual(mod.TheSweepCountOnlyGoesDOWN.EXPECTED_TOTAL, 12)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    unittest.main(verbosity=2)
