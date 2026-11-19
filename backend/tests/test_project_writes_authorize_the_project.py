"""A ROUTE THAT TAKES A {project_id} AND WRITES MUST AUTHORIZE THAT PROJECT.

`POST /projects/{project_id}/repair-file-names` carried only
`Depends(get_admin_user)` — which admits any role in ("admin", "owner"), and
`register` gives every self-serve signup `role = "owner"`. It had no
`require_project_access` on the decorator and no `_assert_project_access` in the
body, so the path `project_id` went straight into the query and any account
that had registered could name ANOTHER TENANT'S project and drive R2
`copy_object` + `delete_object` against its files.

Its own comment asserted the missing check as a fact:

    # ... the caller already matched project_id which is scope enough.

Nothing matched it. That is a comment citing a guarantee nobody implemented —
`docs/audits/check-harness.md` §8 — on a write to object storage. A leaked read
is recoverable; a delete is not.

THE FIX IS THE DEPENDENCY THE NEXT ROUTE IN THE FILE ALREADY CARRIES.
`POST /projects/{project_id}/reindex-document`, forty lines below, is declared
`dependencies=[Depends(require_approved), Depends(require_project_access)]`.
The correct pattern was adjacent the whole time — the ported-fix shape, applied
to the route somebody was reading.

── WHY A CENSUS RATHER THAN ONE ASSERTION ──────────────────────────────────

Three instances of the tenant-filter defect in one file, two fixed, taught the
lesson: an assertion about one route says nothing about the next one added.
This walks EVERY mutating route with a `{project_id}` path parameter and
requires that each one authorizes the project — by the dependency, or by
calling `_assert_project_access` / `user_can_act_on_project` in its body, or by
being a NAMED exception carrying its reason.

The census is what stops a fourth instance. The single assertion below it is
what proves this particular route is fixed.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import textwrap
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)

_MUTATING = {"post", "put", "patch", "delete"}

#: Authorizations that are as good as the dependency, in the body OR on the
#: decorator. THE LIST WAS INCOMPLETE ON ITS FIRST RUN and reported three false
#: positives, which is worse than useless on a security check: the reader
#: learns to skim the output. What it missed, and why each counts —
#:
#:   require_operator_404           a STRONGER gate than project access; the
#:                                  caller must be the platform operator
#:                                  (everyone else gets 404), and
#:                                  hard_delete_project also compares the
#:                                  caller's company to the project's and 403s
#:   _can_caller_modify_user_in_project
#:                                  project-aware by construction: it takes the
#:                                  project_id and the TARGET user and answers
#:                                  whether this caller may act on that pair
#:
#: Adding a name here is a claim that the function authorizes the project. Do
#: not add one without reading it.
_BODY_GUARDS = (
    "_assert_project_access",
    "require_project_access",
    "require_operator_404",
    "user_can_act_on_project",
    "_can_caller_modify_user_in_project",
    "_same_company_or_403",
)


#: The project gates FastAPI resolves from the path's {project_id}. Either may
#: sit on the decorator (`dependencies=[Depends(...)]`) or be a PARAMETER of
#: the handler (`_proj = Depends(...)`); FastAPI runs both the same way.
_PROJECT_DEPENDENCIES = ("require_project_access", "require_project_admin_access")


def _parameter_dependency(fn):
    """The project gate declared as a handler PARAMETER, or None.

    THE CENSUS USED TO MISS THIS SHAPE. It looked for the gate on the
    decorator, then for a CALL `require_project_access(` in the body -- and a
    parameter default reads `Depends(require_project_access)`, the name followed
    by `)`, not `(`. So `_proj = Depends(require_project_access)`, which is used
    on 21 handlers in server.py, was reported as "no authorization" the first
    time it appeared on a mutating route (#1049, late-arrivals).

    READ FROM THE AST, NOT THE TEXT: only a default that IS a `Depends(<gate>)`
    call counts. A comment or a string naming the gate is not a dependency, and
    the classifier tests below hold that.
    """
    args = fn.args
    for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
        if not (isinstance(default, ast.Call) and isinstance(default.func, ast.Name)
                and default.func.id == "Depends" and default.args):
            continue
        target = default.args[0]
        if isinstance(target, ast.Name) and target.id in _PROJECT_DEPENDENCIES:
            return target.id
    return None


def _project_write_routes(tree=None):
    """(function name, path, line, how it authorizes or None)."""
    out = []
    for fn in ast.walk(_TREE if tree is None else tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in fn.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            if not (isinstance(f, ast.Attribute) and f.attr in _MUTATING):
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            path = dec.args[0].value
            if not isinstance(path, str) or "{project_id}" not in path:
                continue
            decorator_src = ast.unparse(dec)
            body_src = ast.unparse(fn)
            how = None
            # require_project_admin_access (2026-10-24) IS a project gate:
            # project_access_ok for everyone but the platform operator, who
            # is admitted only with an audit row
            # (tests/test_operator_project_admin_access.py proves the 403s).
            if ("require_project_access" in decorator_src
                    or "require_project_admin_access" in decorator_src):
                how = "dependency"
            elif _parameter_dependency(fn):
                how = f"parameter:{_parameter_dependency(fn)}"
            else:
                for g in _BODY_GUARDS:
                    if g in decorator_src:
                        how = f"decorator:{g}"
                        break
                    if g + "(" in body_src:
                        how = f"body:{g}"
                        break
            out.append((fn.name, path, fn.lineno, how))
    return out


#: Mutating {project_id} routes that authorize some other way, each with the
#: reason. NAMED, not silent: a count cannot tell a deliberate exception from a
#: missed one, which is how three tenant filters came to be missing at once.
_EXEMPT: dict[str, str] = {}


class EveryProjectWriteAuthorizesTheProject(unittest.TestCase):

    def test_the_walk_found_routes(self):
        """A census that matched nothing passes every assertion below."""
        routes = _project_write_routes()
        self.assertGreaterEqual(
            len(routes), 15,
            f"only {len(routes)} mutating {{project_id}} routes found; the "
            "walk is stale")

    def test_every_one_of_them_authorizes(self):
        unguarded = [
            f"server.py:{ln} {name} {path}"
            for name, path, ln, how in _project_write_routes()
            if how is None and name not in _EXEMPT
        ]
        self.assertEqual(
            unguarded, [],
            "a caller who names another tenant's project id can write to it "
            "through: " + "; ".join(unguarded))

    def test_repair_file_names_is_authorized_by_the_dependency(self):
        """The route this file was written for, named so the fix cannot be
        reverted quietly while the census still passes on the others."""
        hit = [r for r in _project_write_routes() if r[0] == "repair_file_names"]
        self.assertEqual(len(hit), 1, "the route vanished")
        self.assertEqual(hit[0][3], "dependency")

    def test_and_it_still_does_not_filter_the_ROWS_by_company(self):
        """THE HALF OF THE OLD COMMENT THAT WAS TRUE. Legacy rows may carry no
        `company_id`, so filtering the rows on it would skip exactly the ones
        needing repair. Scoping belongs on the CALLER; this asserts the fix did
        not "improve" the row query and quietly narrow the repair."""
        i = _SRC.index("async def repair_file_names(")
        j = _SRC.index("\n@api_router", i)
        body = _SRC[i:j]
        code = "\n".join(l for l in body.split("\n")
                         if not l.lstrip().startswith("#"))
        self.assertIn('{"project_id": project_id, "is_deleted": {"$ne": True}}',
                      code)
        self.assertNotIn('query["company_id"]', code)

    def test_the_false_premise_is_gone_from_the_comment(self):
        """It asserted the check that did not exist. A fixed defect with its
        own justification still on the page is the next reader's trap."""
        i = _SRC.index("async def repair_file_names(")
        j = _SRC.index("\n@api_router", i)
        self.assertNotIn("which is scope enough", _SRC[i:j])

    def test_the_exemptions_each_state_why(self):
        for name, reason in _EXEMPT.items():
            with self.subTest(name):
                self.assertGreater(len(reason), 60,
                                   "an exemption without a reason is a hole")


class TheParameterDependencyIsReadFromTheAst(unittest.TestCase):
    """The classifier, on handlers written for it. A census that learned a new
    pattern has to be shown still refusing the shapes that are NOT that
    pattern, or it has only learned to say yes."""

    @staticmethod
    def _how(src):
        routes = _project_write_routes(ast.parse(textwrap.dedent(src)))
        assert len(routes) == 1, routes
        return routes[0][3]

    def test_a_parameter_dependency_is_authorization(self):
        self.assertEqual(self._how('''
            @api_router.post("/p/{project_id}/x")
            async def h(project_id: str, current_user = Depends(get_current_user),
                        _proj = Depends(require_project_access)):
                pass
        '''), "parameter:require_project_access")

    def test_the_admin_variant_is_authorization_too(self):
        self.assertEqual(self._how('''
            @api_router.put("/p/{project_id}/x")
            async def h(project_id: str, *, p = Depends(require_project_admin_access)):
                pass
        '''), "parameter:require_project_admin_access")

    def test_only_authentication_is_NOT(self):
        self.assertIsNone(self._how('''
            @api_router.post("/p/{project_id}/x")
            async def h(project_id: str, current_user = Depends(get_admin_user)):
                pass
        '''))

    def test_naming_the_gate_in_a_string_or_comment_is_NOT(self):
        self.assertIsNone(self._how('''
            @api_router.post("/p/{project_id}/x")
            async def h(project_id: str, current_user = Depends(get_current_user),
                        note: str = "Depends(require_project_access)"):
                # _proj = Depends(require_project_access)
                pass
        '''))

    def test_late_arrivals_is_authorized_by_its_parameter(self):
        """The route that exposed the gap. That the dependency really refuses
        another tenant is proved with requests in
        test_late_arrivals_tenancy.py; this pins that the census sees it."""
        hit = [r for r in _project_write_routes()
               if r[0] == "sync_daily_jobsite_late_arrivals"]
        self.assertEqual(len(hit), 1, "the route vanished")
        self.assertEqual(hit[0][3], "parameter:require_project_access")


class TheGuardItselfIsRealAndReachable(unittest.TestCase):
    """A dependency that authorized nothing would satisfy the census."""

    def test_require_project_access_delegates_to_the_real_check(self):
        i = _SRC.index("async def require_project_access(")
        j = _SRC.index("\n\n", i)
        self.assertIn("_assert_project_access", _SRC[i:j])

    def test_and_the_sibling_route_it_was_copied_from_still_has_it(self):
        """The proof the pattern existed. If `reindex-document` ever loses it,
        the argument in the docstring above stops being true."""
        self.assertRegex(
            _SRC,
            re.compile(r'reindex-document",\s*dependencies=\[[^\]]*'
                       r'require_project_access', re.S))


if __name__ == "__main__":
    unittest.main(verbosity=2)
