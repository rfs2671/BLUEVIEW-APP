"""A ROOT LINK IS A DELIBERATE ACT, NOT WHAT AN EMPTY STRING FALLS THROUGH TO.

link_dropbox_to_project read its body three ways: None unlinked, and BOTH ""
and "/" linked the project to the root of the company's Dropbox scope.

"" is the value a bug produces. project/[id].jsx's Disconnect sent exactly
that, so a control labelled Disconnect stored "/" instead of clearing the
field. _sync_project_to_r2 lists with recursive=True, so the next sync would
have walked every file the company keeps in Dropbox, downloaded each one,
written it to R2 under this project's prefix and inserted a project_files row
for it. #239 closed both client paths; this closes the endpoint.

None still unlinks -- that signal was never ambiguous. Root now needs
allow_root: true, a second key no falsy fallback can produce.

    python -m pytest backend/tests/test_link_dropbox_refuses_root.py
"""

import ast
import asyncio
import os
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

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8-sig")
TREE = ast.parse(SRC)

ADMIN = {"id": "u1", "role": "admin", "company_id": "companyA"}
PID = "proj1"


def _call(body):
    """Run the handler with db.projects.update_one captured."""
    updates = []

    async def fake_update(flt, doc):
        updates.append((flt, doc))
        return MagicMock(modified_count=1)

    projects = MagicMock()
    projects.update_one = AsyncMock(side_effect=fake_update)
    with patch.object(server, "db", MagicMock(projects=projects)):
        result = asyncio.run(
            server.link_dropbox_to_project(
                project_id=PID, data=body, current_user=ADMIN
            )
        )
    return result, updates


def _call_capturing_writes(body):
    """Same, but returns the writes even when the handler raises."""
    updates = []

    async def fake_update(flt, doc):
        updates.append((flt, doc))
        return MagicMock(modified_count=1)

    projects = MagicMock()
    projects.update_one = AsyncMock(side_effect=fake_update)
    exc = None
    with patch.object(server, "db", MagicMock(projects=projects)):
        try:
            asyncio.run(
                server.link_dropbox_to_project(
                    project_id=PID, data=body, current_user=ADMIN
                )
            )
        except HTTPException as e:
            exc = e
    return exc, updates


class RootIsRefused(unittest.TestCase):
    """The shapes that all used to mean "link everything"."""

    def test_empty_string_is_refused(self):
        with self.assertRaises(HTTPException) as ctx:
            _call({"folder_path": ""})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_a_bare_slash_is_refused(self):
        with self.assertRaises(HTTPException) as ctx:
            _call({"folder_path": "/"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_whitespace_only_is_refused(self):
        """folder_path is stripped first, so three spaces reach that branch."""
        with self.assertRaises(HTTPException) as ctx:
            _call({"folder_path": "   "})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_a_refusal_writes_NOTHING(self):
        """A 400 that had already updated the document would be worse than no
        refusal at all."""
        for body in ({"folder_path": ""}, {"folder_path": "/"}):
            with self.subTest(body=body):
                exc, updates = _call_capturing_writes(body)
                self.assertIsNotNone(exc)
                self.assertEqual(updates, [])

    def test_the_message_names_BOTH_alternatives(self):
        """The admin has two legitimate intents and must be told which key each
        one needs, or the 400 is a dead end."""
        with self.assertRaises(HTTPException) as ctx:
            _call({"folder_path": ""})
        detail = ctx.exception.detail
        self.assertIn("folder_path: null", detail)
        self.assertIn("allow_root", detail)

    def test_the_message_says_what_would_have_happened(self):
        with self.assertRaises(HTTPException) as ctx:
            _call({"folder_path": ""})
        self.assertIn("entire Dropbox", ctx.exception.detail)


class AllowRootIsTheDeliberateKey(unittest.TestCase):

    def test_allow_root_true_links_root(self):
        result, updates = _call({"folder_path": "", "allow_root": True})
        self.assertEqual(result["folder_path"], "/")
        self.assertEqual(updates[0][1]["$set"]["dropbox_folder_path"], "/")

    def test_a_bare_slash_with_allow_root_links_root(self):
        result, _ = _call({"folder_path": "/", "allow_root": True})
        self.assertEqual(result["folder_path"], "/")

    def test_NO_FALSY_FALLBACK_SATISFIES_IT(self):
        """The whole point of the second key. Every one of these is something a
        client can put in allow_root by accident; none of them is a decision.
        The string "true" is included deliberately -- a form field posts text,
        and truthiness would have accepted "false" just as readily."""
        for bad in (None, False, 0, "", "false", "true", 1, "1", [], {}):
            with self.subTest(allow_root=bad):
                with self.assertRaises(HTTPException) as ctx:
                    _call({"folder_path": "", "allow_root": bad})
                self.assertEqual(ctx.exception.status_code, 400)

    def test_allow_root_does_not_affect_a_normal_path(self):
        """It is not a general override -- it only unlocks the root branch."""
        result, _ = _call({"folder_path": "/588 plans", "allow_root": True})
        self.assertEqual(result["folder_path"], "/588 plans")


class NothingElseChanged(unittest.TestCase):
    """The refusal must not have cost the paths that already worked."""

    def test_null_still_unlinks(self):
        result, updates = _call({"folder_path": None})
        self.assertIsNone(result["folder_path"])
        self.assertIn("dropbox_folder_path", updates[0][1]["$unset"])

    def test_a_missing_key_still_unlinks(self):
        """data.get() yields None, and that has always meant unlink."""
        result, _ = _call({})
        self.assertIsNone(result["folder_path"])

    def test_a_real_folder_still_links(self):
        result, _ = _call({"folder_path": "/588 plans"})
        self.assertEqual(result["folder_path"], "/588 plans")

    def test_a_leading_slash_is_still_added(self):
        result, _ = _call({"folder_path": "588 plans"})
        self.assertEqual(result["folder_path"], "/588 plans")

    def test_a_trailing_slash_is_still_stripped(self):
        result, _ = _call({"folder_path": "/588 plans/"})
        self.assertEqual(result["folder_path"], "/588 plans")

    def test_a_non_string_is_still_a_400(self):
        with self.assertRaises(HTTPException) as ctx:
            _call({"folder_path": 42})
        self.assertEqual(ctx.exception.status_code, 400)


def _fn(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


class TheRefusalIsReadAsCode(unittest.TestCase):
    """The docstring explains the empty string, the bare slash and allow_root
    at length, so every substring check here would be satisfied by the
    explanation instead of the behaviour. These read the AST."""

    def test_the_route_still_carries_its_tenancy_dependencies(self):
        """A refusal is worthless on a route anyone can reach."""
        for r in server.app.routes:
            if getattr(r, "path", "") == "/api/projects/{project_id}/link-dropbox":
                names = {d.call.__name__ for d in r.dependant.dependencies
                         if getattr(d, "call", None)}
                self.assertIn("require_project_access", names)
                self.assertIn("require_approved", names)
                return
        self.fail("link-dropbox route disappeared")

    def test_allow_root_is_compared_with_IS_TRUE_not_truthiness(self):
        """A plain truthiness check would accept the string "false"."""
        fn = _fn("link_dropbox_to_project")
        found = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.Compare):
                continue
            if not (len(node.ops) == 1
                    and isinstance(node.ops[0], (ast.Is, ast.IsNot))):
                continue
            if "allow_root" not in ast.unparse(node.left):
                continue
            if ast.unparse(node.comparators[0]) == "True":
                found = True
        self.assertTrue(found, "allow_root must be compared with `is True`")

    def test_the_handler_raises_before_its_link_write(self):
        """Read as structure, not as text: a raise precedes the linking
        update_one, so no ordering change can leave the write first."""
        fn = _fn("link_dropbox_to_project")
        raises = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Raise)]
        writes = [n.lineno for n in ast.walk(fn)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "update_one"]
        self.assertTrue(raises, "no raise in the handler")
        self.assertTrue(writes, "no update_one in the handler")
        self.assertLess(min(raises), max(writes))

    def test_the_gate_rule_is_explicitly_disclaimed(self):
        """The standing rule is "an unfilled admin form must never stop a man
        from working". It governs the check-in path, not admin configuration,
        and the reason is recorded on the handler so the rule is not invoked
        against this refusal later."""
        doc = ast.get_docstring(_fn("link_dropbox_to_project")) or ""
        self.assertIn("stop a man from working", doc)
        self.assertIn("admin", doc.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
