"""EVERY CONDITIONAL TENANT FILTER CARRIES ITS REFUSAL.

The shape, found thirteen times in one file:

    company_id = get_user_company_id(current_user)
    if company_id:
        query["company_id"] = company_id
    # ... and NOTHING in the else

A caller whose `company_id` is falsy skipped the filter and read every tenant's
rows. `company_id = None` is the DEFAULT account state — `register` sets it and
a company is attached later by `POST /onboarding/company` — so this was the
ordinary path for a fresh account, not an edge case.

THREE OF THEM WERE FOUND AND FIXED ONE AT A TIME BEFORE THIS FILE EXISTED, and
that is the argument for it. `get_workers` was fixed after a leak and its
comment argues the whole case; `get_project_roster` was written with the guard;
`get_company_roster` still had the pre-fix form when someone looked. Fixing the
one you are reading says nothing about the next. Eleven more went in together
with this census, which is what stops a fourteenth.

THE REQUIRED SHAPE:

    if company_id:
        query["company_id"] = company_id
    elif not is_platform_operator(user):
        query["_id"] = None

`_id: None` is UNSATISFIABLE, so there is one code path and one response shape:
a caller who owns nobody gets what a company with no rows gets.
`company_id: None` would be worse than the bug — it matches precisely the
orphan rows, i.e. every other un-onboarded signup, and cross-links strangers.

THE CARVE-OUT IS THE FLAG, NEVER THE ROLE. `role == "owner"` is what every
self-serve signup receives, so a role test is satisfied by having registered.
`GET /admin/users` made exactly that mistake and leaked every user's email and
phone to every customer owner, always — not only to a company-less one.

── WHY THIS CHECK IS NARROW ON PURPOSE ─────────────────────────────────────

It finds one shape — an `if <name>:` whose body assigns `…["company_id"]` — and
then asks a question about the WHOLE FUNCTION: does anything in it, or on its
route, refuse the company-less caller? It does not try to judge whether a
function is "tenant-scoped" in general.

THAT COARSENESS WAS BOUGHT WITH A FALSE-POSITIVE RUN. The first draft asked
whether THAT `if` had an `orelse` mentioning `is_platform_operator`, and it
flagged twelve correct sites — ones whose operator check is an enclosing
branch, ones that alias the call into a local, and ones scoped by
`require_project_access` on the route rather than by a filter at all. The
sibling census in test_project_writes_authorize_the_project.py did the same
thing on its first run, from a guard list missing two real guards.

    On a security check a false positive is worse than useless: the reader
    learns to skim the output, and then the true positive scrolls past.

So the rule is the weaker one that is actually true, and everything it cannot
judge is a NAMED exemption rather than a guess.

AND THE WALK ITSELF FAILED SILENTLY FIRST. `ast.unparse` emits single quotes,
so the initial check — written against the source spelling `["company_id"]` —
matched nothing and the census reported a clean tree over an empty walk. The
non-empty guard caught it, which is why that is the first assertion in the file
and not the last.
"""

from __future__ import annotations

import ast
import os
import sys
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

#: Sites that set `…["company_id"]` under a conditional but are NOT a tenant
#: read, each with its reason. Named rather than silent: a count cannot tell a
#: deliberate exception from a missed one.
_EXEMPT: dict[str, str] = {
    "get_current_user":
        "not a query filter at all -- it STAMPS the resolved company onto the "
        "auth context for a site device (`device_data['company_id'] = "
        "project.get('company_id')`), so there is no caller to refuse and "
        "nothing is read cross-tenant",
    "create_checklist":
        "a WRITE stamping the new row with the creator's company, not a read "
        "filter; a falsy company writes a company-less row, which is the "
        "pre-existing behaviour and not a cross-tenant read",
}


def _route_decorators():
    out = {}
    for fn in ast.walk(_TREE):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[fn.name] = " ".join(ast.unparse(d) for d in fn.decorator_list)
    return out


def _conditional_company_filters():
    """(function, [lines], refused) for every `if x: q["company_id"] = x`.

    JUDGED PER FUNCTION, NOT PER `if`. A first draft asked whether THAT `if`
    had an `orelse` mentioning `is_platform_operator`, and it flagged twelve
    CORRECT sites: ones whose operator check is an enclosing branch, ones that
    alias the call into a local, and ones scoped by `require_project_access` on
    the route instead of by a filter at all. A security check that cries wolf
    on twelve correct sites is a check nobody reads.

    The property that actually matters is coarser and true: SOMETHING in this
    function, or on its route, refuses the company-less caller.
    """
    decs = _route_decorators()
    out = []
    for fn in ast.walk(_TREE):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        hits = []
        for node in ast.walk(fn):
            if not (isinstance(node, ast.If) and isinstance(node.test, ast.Name)):
                continue
            body = "\n".join(ast.unparse(b) for b in node.body)
            if "['company_id']" not in body or "=" not in body:
                continue
            if "==" in body or "!=" in body:
                continue
            hits.append(node.lineno)
        if not hits:
            continue
        whole = ast.unparse(fn)
        refused = ("is_platform_operator" in whole
                   or "require_project_access" in decs.get(fn.name, ""))
        out.append((fn.name, hits, refused))
    return out


class EveryConditionalFilterRefusesTheCompanylessCaller(unittest.TestCase):

    def test_the_census_is_not_empty(self):
        """A walk that matched nothing satisfies every assertion below, and
        this file's whole value is the count."""
        found = _conditional_company_filters()
        self.assertGreaterEqual(
            len(found), 12,
            f"only {len(found)} functions with a conditional company filter "
            "found; the walk is "
            "stale and this file is no longer checking anything")

    def test_every_one_of_them_carries_its_refusal(self):
        missing = [f"server.py:{lns} {name}"
                   for name, lns, ok in _conditional_company_filters()
                   if not ok and name not in _EXEMPT]
        self.assertEqual(
            missing, [],
            "a caller with no company reads every tenant's rows through: "
            + "; ".join(missing))

    def test_the_refusal_is_id_None_and_never_company_id_None(self):
        """`company_id: None` matches precisely the orphan rows — every other
        un-onboarded signup — so it cross-links strangers instead of scoping
        the caller to nobody. Worse than the bug it would be fixing."""
        for fn in ast.walk(_TREE):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.If) and node.orelse):
                    continue
                orelse = "\n".join(ast.unparse(b) for b in node.orelse)
                if "is_platform_operator" not in orelse:
                    continue
                with self.subTest(f"{fn.name}:{node.lineno}"):
                    self.assertNotIn("['company_id'] = None", orelse)

    def test_the_three_fixed_before_this_file_still_carry_it(self):
        """They are the reason it exists; a regression on any of them would
        otherwise only show as a number changing."""
        by_fn = {}
        for name, _lns, ok in _conditional_company_filters():
            by_fn.setdefault(name, []).append(ok)
        for name in ("get_workers", "get_company_roster"):
            with self.subTest(name):
                self.assertIn(name, by_fn, "the site vanished")
                self.assertTrue(all(by_fn[name]))

    def test_the_exemptions_each_state_why(self):
        for name, reason in _EXEMPT.items():
            with self.subTest(name):
                self.assertGreater(len(reason), 60,
                                   "an exemption without a reason is a hole")


class TheRoleIsNeverTheCarveOut(unittest.TestCase):
    """`role == "owner"` is what every self-serve signup receives. A tenant
    decision made on it is satisfied by having registered."""

    def test_admin_users_decides_on_the_flag(self):
        i = _SRC.index("async def get_admin_users(")
        j = _SRC.index("USER_LIST_FIELDS = {", i)
        code = "\n".join(l for l in _SRC[i:j].split("\n")
                         if not l.lstrip().startswith("#"))
        self.assertIn("is_platform_operator(current_user)", code)
        self.assertNotIn('"role"', code)

    def test_is_platform_operator_reads_a_flag_and_not_a_role(self):
        i = _SRC.index("def is_platform_operator(")
        j = _SRC.index("\nasync def require_platform_operator", i)
        body = _SRC[i:j]
        self.assertIn("is_platform_operator", body)
        self.assertNotIn('get("role")', body)


class TheOperatorGateIsEnvironmentDependent(unittest.TestCase):
    """RECORDED, NOT ASSERTED AWAY. `require_platform_operator` only REFUSES
    while PLATFORM_GATES_ENFORCED is set; it defaults to "false", in which mode
    it logs and returns the caller. Production sets it to true (verified
    2026-09-05 against the deployed environment).

    This matters to the sibling census in
    test_project_writes_authorize_the_project.py, which accepts that dependency
    as a guard: in an environment without the variable it is not one. The route
    it guards there, `hard_delete_project`, also compares the caller's company
    to the project's and 403s, so it does not stand alone.
    """

    def test_the_shadow_mode_still_exists_and_is_documented(self):
        i = _SRC.index("async def require_platform_operator(")
        j = _SRC.index("\nasync def ", i + 10)
        body = _SRC[i:j]
        self.assertIn("PLATFORM_GATES_ENFORCED", body)
        self.assertIn("return current_user", body,
                      "shadow mode is gone — update this test and the sibling "
                      "census's caveat, which both describe it")

    def test_hard_delete_does_not_rely_on_that_gate_alone(self):
        i = _SRC.index("async def hard_delete_project(")
        j = _SRC.index("\n@api_router", i)
        body = _SRC[i:j]
        self.assertIn("is_platform_operator", body)
        self.assertIn("403", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
