"""Ten project-scoped reads fail closed.

Each checked tenancy with

    if company_id and project.get("company_id") != company_id:

which short-circuits, so a caller whose company_id is falsy never reached the
comparison and the 403 could not fire. /auth/register sets
user_dict["company_id"] = None on every self-serve signup, so that is the
DEFAULT until onboarding attaches a company.

    GET /projects/{project_id}
    GET /projects/{project_id}/prediction
    GET /projects/{project_id}/required-logbooks
    GET /projects/{project_id}/dropbox-subfolders
    GET /projects/{project_id}/dropbox-files
    GET /projects/{project_id}/dropbox-file-url
    GET /projects/{project_id}/daily-headcount
    GET /projects/{project_id}/dob-config
    GET /projects/{project_id}/dob-logs
        _verify_dob_log_access                     (helper, 2 callers)

THE DELETION FILTER IS UNCHANGED ON ALL TEN, per the operator's ruling and for
the reason that held in the three previous PRs: authorization is what was
missing, and a CP losing a read on a project an admin has just marked for
deletion is worse than the alternative.

FOUR OF THEM NEVER HAD A DELETION FILTER AT ALL -- the Dropbox routes look up
`{"_id": to_query_id(project_id)}` with no is_deleted clause. Applying the
ruling literally means leaving that alone too. Named here rather than silently
"improved", because tightening existence semantics inside an authorization fix
is exactly the kind of change that gets blamed on the wrong PR later.

    python backend/tests/test_project_path_reads_fail_closed.py
"""

import ast
import io
import os
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8-sig")
TREE = ast.parse(SRC)

FIXED = [
    "get_project",
    "get_project_prediction",
    "get_project_required_logbooks",
    "list_dropbox_subfolders",
    "get_project_dropbox_files",
    "get_dropbox_file_url",
    "get_project_daily_headcount",
    "get_dob_config",
    "get_dob_logs",
    "_verify_dob_log_access",
]

# The four whose lookup has NEVER carried a deletion filter. Left alone by the
# ruling; named so the absence is a recorded decision rather than an oversight.
NO_DELETION_FILTER = {
    "list_dropbox_subfolders",
    "get_project_dropbox_files",
    "get_dropbox_file_url",
}

BYPASS = re.compile(r"""^\w*company_id\s+and\s+.*\.get\(['"]company_id['"]\).*!=""")


def _fn(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in server.py")


def _conditions(name):
    return [ast.unparse(n.test) for n in ast.walk(_fn(name)) if isinstance(n, ast.If)]


class EveryOneOfTheTenFailsClosed(unittest.TestCase):
    """Read as CODE. The replacement comments quote the removed line so a
    reader knows what changed, and a substring check would match that prose --
    see the practice note in followups.md."""

    def test_none_of_them_keeps_a_conditional_company_check(self):
        for name in FIXED:
            with self.subTest(fn=name):
                for cond in _conditions(name):
                    self.assertIsNone(BYPASS.search(cond), f"{name}: {cond}")

    def test_all_of_them_use_the_shared_rule(self):
        for name in FIXED:
            with self.subTest(fn=name):
                conds = _conditions(name)
                self.assertTrue(
                    any("project_access_ok" in c for c in conds),
                    f"{name} does not call project_access_ok: {conds}")

    def test_the_call_is_negated(self):
        """`if project_access_ok(...)` instead of `if not project_access_ok(...)`
        would invert the guard and let exactly the wrong people through, while
        every other assertion here still passed."""
        for name in FIXED:
            with self.subTest(fn=name):
                guard = [c for c in _conditions(name) if "project_access_ok" in c]
                self.assertTrue(guard, name)
                for c in guard:
                    self.assertTrue(c.startswith("not "), f"{name}: {c}")

    def test_all_ten_are_accounted_for(self):
        """If the list shrinks, the sweep total stops meaning what it says."""
        self.assertEqual(len(FIXED), 10)
        self.assertEqual(len(set(FIXED)), 10)


class TheDeletionFilterIsUntouched(unittest.TestCase):
    """The ruling: keep each route's existing lookup. Authorization was what
    was missing."""

    def _lookup_kwargs(self, name):
        """The keys of the dict passed to db.projects.find_one inside this fn.

        A `**SPREAD` entry has a None key in ast.Dict.keys -- `ast.unparse(None)`
        raises, which is what an earlier version of this helper did on
        get_project, whose lookup is `{"_id": ..., **ACTIVE_PROJECT_FILTER}`.
        The spread is reported under its own name so the filter it carries is
        visible rather than swallowed.
        """
        for node in ast.walk(_fn(name)):
            if not isinstance(node, ast.Call):
                continue
            if not ast.unparse(node.func).endswith("projects.find_one"):
                continue
            if not (node.args and isinstance(node.args[0], ast.Dict)):
                continue
            keys = set()
            for k, v in zip(node.args[0].keys, node.args[0].values):
                if k is None:                       # **SPREAD
                    keys.add("**" + ast.unparse(v))
                else:
                    keys.add(ast.unparse(k).strip("'\""))
            return keys
        return None

    # WHAT EACH LOOKUP HELD BEFORE THIS PR, verified against main. The ruling
    # is "keep the existing lookup", so the assertion is that each is
    # UNCHANGED -- not that they all look alike. They do not.
    EXPECTED_LOOKUP = {
        # ALREADY STRICTER, and left that way. get_project has used
        # **ACTIVE_PROJECT_FILTER (is_deleted AND marked_for_deletion) since
        # before this series. It is the one of the ten with a reason to differ,
        # and the reason is that it already differed: loosening it here to
        # match its nine siblings would be a behaviour change smuggled into an
        # authorization fix, in the direction of showing MORE.
        "get_project": "spread",
        "get_project_prediction": "is_deleted",
        "get_project_required_logbooks": "is_deleted",
        "get_project_daily_headcount": "is_deleted",
        "get_dob_config": "is_deleted",
        "get_dob_logs": "is_deleted",
        "_verify_dob_log_access": "is_deleted",
        # NEVER HAD ONE. Named, not "improved" -- tightening existence
        # semantics inside an auth fix is how a later breakage gets blamed on
        # the wrong commit.
        "list_dropbox_subfolders": "none",
        "get_project_dropbox_files": "none",
        "get_dropbox_file_url": "none",
    }

    def test_every_lookup_is_exactly_what_it_was(self):
        for name, expected in self.EXPECTED_LOOKUP.items():
            with self.subTest(fn=name):
                keys = self._lookup_kwargs(name)
                self.assertIsNotNone(keys, name)
                if expected == "spread":
                    self.assertIn("**ACTIVE_PROJECT_FILTER", keys, name)
                elif expected == "is_deleted":
                    self.assertIn("is_deleted", keys, name)
                    self.assertNotIn("**ACTIVE_PROJECT_FILTER", keys, name)
                    self.assertNotIn("marked_for_deletion", keys, name)
                else:
                    self.assertEqual(keys, {"_id"}, name)

    def test_no_route_NEWLY_adopted_the_stricter_filter(self):
        """The ruling, stated as the thing that must not have happened: nine of
        the ten still cannot exclude a marked-for-deletion project, so a CP does
        not lose a read to an admin action."""
        for name in set(self.EXPECTED_LOOKUP) - {"get_project"}:
            with self.subTest(fn=name):
                keys = self._lookup_kwargs(name)
                self.assertNotIn("**ACTIVE_PROJECT_FILTER", keys, name)
                self.assertNotIn("marked_for_deletion", keys, name)

    def test_the_ten_are_the_ten(self):
        self.assertEqual(set(self.EXPECTED_LOOKUP), set(FIXED))

    def test_the_dropbox_routes_still_have_NO_deletion_filter(self):
        """NAMED, NOT FIXED. These three never filtered on is_deleted, and this
        PR is about authorization. Tightening existence semantics inside an
        auth fix is how a later breakage gets blamed on the wrong commit."""
        for name in NO_DELETION_FILTER:
            with self.subTest(fn=name):
                keys = self._lookup_kwargs(name)
                self.assertIsNotNone(keys, name)
                self.assertNotIn("is_deleted", keys, name)
                self.assertNotIn("marked_for_deletion", keys, name)

    def test_server_still_defines_ACTIVE_PROJECT_FILTER_for_the_routes_that_want_it(self):
        """It is correct elsewhere -- _assert_project_access uses it. This is
        about not applying it HERE."""
        self.assertTrue(hasattr(server, "ACTIVE_PROJECT_FILTER"))
        self.assertIn("marked_for_deletion", server.ACTIVE_PROJECT_FILTER)


class NoOrphanedLocalsWereLeftBehind(unittest.TestCase):
    """Removing the conditional left `company_id = get_user_company_id(...)`
    unused in seven of the ten. Dead locals are how a reader concludes a check
    still exists."""

    def test_no_fixed_function_assigns_company_id_without_reading_it(self):
        for name in FIXED:
            with self.subTest(fn=name):
                node = _fn(name)
                assigns = [n for n in ast.walk(node) if isinstance(n, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == "company_id"
                                   for t in n.targets)]
                reads = [n for n in ast.walk(node) if isinstance(n, ast.Name)
                         and n.id == "company_id" and isinstance(n.ctx, ast.Load)]
                if assigns:
                    self.assertTrue(
                        reads, f"{name} assigns company_id and never reads it")


class TheHelperCoversItsCallers(unittest.TestCase):

    def test_verify_dob_log_access_has_two_callers(self):
        calls = sum(
            1 for n in ast.walk(TREE)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_verify_dob_log_access")
        self.assertEqual(calls, 2)

    def test_both_callers_also_carry_the_dependency(self):
        """Belt and braces, and worth knowing: this helper was NOT the only
        control on either caller, unlike _pm_load_project_or_403. Fixing it is
        still right -- the next caller may not carry the dependency.

        READ FROM THE CALLERS' DECORATORS. A character window after the helper
        counted 3, because it ran past the two callers into an unrelated route.
        """
        callers = [
            node for node in ast.walk(TREE)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_verify_dob_log_access"
                    for n in ast.walk(node))
        ]
        self.assertEqual(len(callers), 2)
        for fn in callers:
            deco = " ".join(ast.unparse(d) for d in fn.decorator_list)
            self.assertIn("require_project_access", deco, fn.name)


class TheSweepAgrees(unittest.TestCase):

    def test_the_sweep_matches_the_single_pinned_total(self):
        mod = __import__("test_pm_load_project_fails_closed")
        self.assertEqual(len(mod.sweep_bypass_sites()),
                         mod.TheSweepCountOnlyGoesDOWN.EXPECTED_TOTAL)

    def test_none_of_the_ten_is_still_in_the_sweep(self):
        """MAPPED BY AST, not by a line window. A 60-line window ran backwards
        past one function into the previous one and reported
        get_project_required_logbooks as still bypassed when the hit actually
        belonged to the DELETE route below it -- a false positive that would
        have sent the next reader hunting a fix that was already in."""
        mod = __import__("test_pm_load_project_fails_closed")
        owner = {}
        for node in ast.walk(TREE):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end = getattr(node, "end_lineno", node.lineno)
            for ln in range(node.lineno, end + 1):
                owner[ln] = node.name
        for hit in mod.sweep_bypass_sites():
            name, lineno = hit.split(":")
            if name != "server.py":
                continue
            self.assertNotIn(owner.get(int(lineno)), FIXED,
                             f"{owner.get(int(lineno))} is still in the sweep")

    def test_what_REMAINS_is_reported_not_absorbed(self):
        """NO LITERAL. This asserted exactly 15 and the next PR lowered it to
        12 -- the third time in this series a duplicated total broke a sibling
        file. The number is pinned in ONE place.

        What remains is the belt-and-braces sites on already-guarded routes,
        plus the group-D routes that fit no dependency: the /admin/site-devices
        LIST filter (a `continue` in a loop, not a 403 -- it leaks rather than
        refuses) and the WhatsApp group config write. All reported; none
        silently absorbed by this sweep.
        """
        mod = __import__("test_pm_load_project_fails_closed")
        self.assertGreater(mod.TheSweepCountOnlyGoesDOWN.EXPECTED_TOTAL, 0)
        self.assertEqual(len(mod.sweep_bypass_sites()),
                         mod.TheSweepCountOnlyGoesDOWN.EXPECTED_TOTAL)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    unittest.main(verbosity=2)
