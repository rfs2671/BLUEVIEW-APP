"""A COMPANY LITERALLY NAMED "test" HAS BEEN FEEDING THE ALERTING.

── THE MEASURED STATE ──────────────────────────────────────────────────────

Production holds three companies:

    6a32a11051c7a54c476d2149  'test'                      2 projects, 4 accounts
    6a5e153cc7ac7a6451aa2d32  'BLUEVIEW CONSTRUCTION INC' 2 projects
    6a9ebab885757b18bb7a0ec5  'Blueview llc'              1 empty project

and NOTHING in the code distinguished the first from the second. No is_test, no
is_demo, no environment marker -- not on projects, not on companies, not on
users. The seeder identifies its own fixtures by the name string "Test Project
- ESB", which is not a flag and does not cover 857 Prescott. All four test
accounts are `approved`.

So 857 Prescott's data went into the nightly compliance sweep, the report
emails, the DOB scans and the cross-project statistics real numbers are
computed against. Four injuries were recorded against it on one afternoon in
August by an account called `2`, and an injury on a filed pre-shift sheet is
the kind of thing somebody acts on.

── WHAT THE FLAG DOES, AND THE HALF IT MUST NOT DO ─────────────────────────

`is_test` lives on the COMPANY, because that is where the boundary is: one row
covers its projects, accounts, workers, check-ins and every log filed under it,
and a new fixture project inherits it rather than being one more thing to
remember.

IT IS NOT A VISIBILITY RULE. A test account still sees its own projects, files
its own logs and reads its own screens. The flag governs only the machinery
that acts with NOBODY ASKING. That distinction is asserted below, because the
cheap implementation -- folding the exclusion into ACTIVE_PROJECT_FILTER --
would have hidden a test company's projects from its own users and looked
exactly like a bug to the person it happened to.

── THE CENSUS IS DERIVED, NOT LISTED ───────────────────────────────────────

A hand-written list of "the sweeps we fixed" is a check with an expiry date
nobody set: the seventh scheduled job added next month is not on it and nothing
says so. So the test walks the AST, finds every function registered with
`scheduler.add_job`, follows one level into the module-level functions those
call, and asserts that every `db.projects.find` / `db.companies.find` it
reaches goes through the exclusion. A new unattended sweep fails this file on
the day it is written.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

SRC_PATH = _BACKEND / "server.py"
SRC = SRC_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SRC)

#: The two wrappers. A sweep is covered when its query argument is built by one
#: of these, or when it already constrains `company_id` itself (a sweep scoped
#: to one company has already answered the question).
WRAPPERS = ("unattended_project_filter", "drop_test_companies")


def _module_functions(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


FUNCS = _module_functions(TREE)


def _scheduled_job_names(tree):
    """Every function handed to scheduler.add_job as its first argument."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "add_job"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name):
            names.add(first.id)
        elif isinstance(first, ast.Attribute):
            names.add(first.attr)
    return names


def _calls_in(node):
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            out.add(sub.func.id)
    return out


def _sweep_calls(node):
    """(collection, call_node) for every db.<projects|companies>.find here."""
    found = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        if not (isinstance(f, ast.Attribute) and f.attr in ("find", "count_documents")):
            continue
        owner = f.value
        if not (isinstance(owner, ast.Attribute)
                and owner.attr in ("projects", "companies")):
            continue
        if not (isinstance(owner.value, ast.Name) and owner.value.id == "db"):
            continue
        found.append((owner.attr, sub))
    return found


#: The exclusion's own reader. It is the thing that answers "which companies
#: are fixtures", so it cannot be asked to exclude them.
EXEMPT_FUNCTIONS = ("test_company_ids",)


def _wrapped_find_nodes(node):
    """find() calls that are an ARGUMENT to one of the wrappers.

    `drop_test_companies(await db.companies.find({...}), ids)` reads as an
    unfiltered find at the call site and is in fact the covered shape -- the
    filtering happens to the result rather than in the query. Without this the
    census reports the one sweep that IS excluded and misses the point."""
    out = set()
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)):
            continue
        if sub.func.id not in WRAPPERS:
            continue
        for inner in ast.walk(sub):
            if isinstance(inner, ast.Call):
                out.add(id(inner))
    return out


def _is_covered(call, wrapped=()):
    """Does this find() go through the exclusion, or scope itself already?"""
    if id(call) in wrapped:
        return True
    if not call.args:
        return True          # find() with no filter reads nothing meaningful
    arg = call.args[0]
    # await unattended_project_filter({...})
    inner = arg.value if isinstance(arg, ast.Await) else arg
    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
        if inner.func.id in WRAPPERS:
            return True
    # A literal filter that constrains company_id has already scoped itself.
    if isinstance(inner, ast.Dict):
        for k in inner.keys:
            if isinstance(k, ast.Constant) and k.value == "company_id":
                return True
    # A variable filter built elsewhere -- reported, not guessed at.
    if isinstance(inner, ast.Name):
        return None
    return False


class TheFlagExists(unittest.TestCase):
    def test_the_company_model_carries_it(self):
        import server
        self.assertIn("is_test", server.Company.model_fields)
        self.assertIs(server.Company.model_fields["is_test"].default, False)

    def test_it_is_accepted_at_create(self):
        """A fixture tenant declared on the way in, rather than discovered
        months later by reading a company's name."""
        import server
        self.assertIn("is_test", server.CompanyCreate.model_fields)

    def test_the_default_is_false_and_not_none(self):
        """None would make "nobody said" and "a real company" the same value in
        a `$nin`, and the whole point is that the real ones are the default."""
        import server
        self.assertIs(server.CompanyCreate(name="x").is_test, False)


class TheExclusionIsNotAVisibilityRule(unittest.TestCase):
    """THE HALF THAT MUST NOT HAPPEN.

    A test company's own users keep seeing their own data. If this had been
    folded into ACTIVE_PROJECT_FILTER -- the obvious cheap place -- a test
    account would have opened the app to an empty project list."""

    def test_ACTIVE_PROJECT_FILTER_is_untouched(self):
        from lib.project_state import ACTIVE_PROJECT_FILTER
        self.assertNotIn("company_id", ACTIVE_PROJECT_FILTER)
        self.assertNotIn("is_test", str(ACTIVE_PROJECT_FILTER))

    def test_a_scoped_sweep_keeps_its_own_scope(self):
        """A caller that already names a company gets its own filter back
        unchanged -- replacing it with a `$nin` would WIDEN a one-company sweep
        to every tenant on the platform."""
        import asyncio
        import server
        got = asyncio.run(server.unattended_project_filter(
            {"company_id": "c1", "status": "active"}))
        self.assertEqual(got, {"company_id": "c1", "status": "active"})

    def test_it_fails_open(self):
        """If the companies read breaks, every sweep runs exactly as it did
        before this existed. A missed exclusion is one wrong alert; a raise
        here would stop the nightly compliance check for every real project."""
        import asyncio
        import server

        class _Boom:
            def find(self, *a, **k):
                raise RuntimeError("no mongo")

        class _DB:
            companies = _Boom()

        old = server.db
        try:
            server.db = _DB()
            self.assertEqual(asyncio.run(server.test_company_ids()), set())
            self.assertEqual(
                asyncio.run(server.unattended_project_filter({"status": "active"})),
                {"status": "active"})
        finally:
            server.db = old


class TheCensusOfUnattendedSweeps(unittest.TestCase):
    """DERIVED FROM scheduler.add_job, NOT FROM A LIST SOMEBODY MAINTAINS."""

    def setUp(self):
        self.jobs = _scheduled_job_names(TREE)
        # One level in: a job that delegates its query to a module-level
        # helper is still an unattended sweep.
        reachable = set(self.jobs)
        for name in list(self.jobs):
            node = FUNCS.get(name)
            if node is not None:
                reachable |= (_calls_in(node) & set(FUNCS))
        self.reachable = reachable

    def test_the_scheduler_actually_registers_jobs(self):
        """THE INSTRUMENT ITSELF. If add_job were renamed or the walk broke,
        every assertion below would pass over an empty set and report clean."""
        self.assertGreater(len(self.jobs), 10, sorted(self.jobs))
        self.assertIn("nightly_compliance_check", self.jobs)
        self.assertIn("check_and_send_reports", self.jobs)

    def test_every_unattended_project_sweep_is_excluded(self):
        offenders = []
        unknown = []
        for name in sorted(self.reachable):
            if name in EXEMPT_FUNCTIONS:
                continue
            node = FUNCS.get(name)
            if node is None:
                continue
            wrapped = _wrapped_find_nodes(node)
            for coll, call in _sweep_calls(node):
                verdict = _is_covered(call, wrapped)
                where = f"{name} -> db.{coll}.find (server.py:{call.lineno})"
                if verdict is False:
                    offenders.append(where)
                elif verdict is None:
                    unknown.append(where)
        self.assertEqual(offenders, [], "unattended sweeps with no exclusion")
        # A filter built in a variable cannot be judged from the call site. It
        # is REPORTED rather than absorbed: this is the one shape that could
        # hide a new sweep, and a silent pass here is how the check rots.
        self.assertEqual(
            unknown, [],
            "sweeps whose filter is a variable -- inline it or wrap it")

    def test_the_six_known_sweeps_are_named(self):
        """Belt and braces on the derived census. These are the six that were
        acting on 857 Prescott when this was written; if a refactor moves one
        out of a scheduled job, the census above stops seeing it and this
        notices."""
        for fn in ("nightly_compliance_check", "check_and_send_reports"):
            with self.subTest(fn):
                node = FUNCS[fn]
                sweeps = _sweep_calls(node)
                self.assertTrue(sweeps, f"{fn} no longer sweeps projects")
                wrapped = _wrapped_find_nodes(node)
                for _coll, call in sweeps:
                    self.assertIsNot(_is_covered(call, wrapped), False)

    def test_the_wrappers_are_used_at_least_as_often_as_they_are_named(self):
        """A wrapper imported and never called is the failure mode a source
        test is blindest to."""
        for w in WRAPPERS:
            with self.subTest(w):
                self.assertGreaterEqual(SRC.count(w), 2)


class TheCrossTenantStatisticsAreScopedToo(unittest.TestCase):
    """THE ONE THE CENSUS ABOVE COULD NOT SEE, AND THE WORST OF THEM.

    server.py's scheduled jobs delegate the panel builds into
    lib/statistical_engine/, so an AST walk of server.py alone reports clean
    while the actual query lives one import away. Both of these read

        db.projects.find({})

    -- EVERY project on the platform, every tenant, deleted or not -- and the
    panels they build are what real projects are SCORED AGAINST. A company
    named "test" with two click-through projects was in the peer set.

    This is the "its data must never mix into real metrics" half, and it needs
    its own assertions because the mechanism is different: the filter is
    applied to the RESULT rather than to the query, deliberately, so that a
    failure in the fixture read cannot change which projects the panel sees.
    """

    ENGINE = (
        ("daily_panel.py", "_pr15a_nightly_panel_build_tick"),
        ("live_mutation.py", "_pr15b_nightly_refit_tick"),
    )

    def _src(self, name):
        return (_BACKEND / "lib" / "statistical_engine" / name).read_text(
            encoding="utf-8")

    def test_each_unfiltered_read_is_followed_by_the_drop(self):
        for name, _job in self.ENGINE:
            with self.subTest(name):
                src = self._src(name)
                self.assertIn("db.projects.find({})", src,
                              "the read kept its shape on purpose")
                self.assertIn("fixture_company_ids(db)", src)
                self.assertIn("drop_fixture_rows(projects, _fixtures)", src)
                # ORDER, not just presence. A drop before the read filters
                # nothing and would pass a presence check.
                self.assertLess(src.index("fixture_company_ids(db)"),
                                src.index("drop_fixture_rows(projects"))

    def test_the_shared_helper_is_imported_and_not_re_implemented(self):
        """Two definitions of "which tenants are fixtures" is how the
        compliance detectors ended up with a project filter of their own that
        was wrong on live data for weeks."""
        for name, _job in self.ENGINE:
            with self.subTest(name):
                src = self._src(name)
                self.assertIn("from lib.project_state import", src)
                self.assertNotIn('{"is_test": True}', src)

    def test_the_helper_fails_open(self):
        import asyncio
        from lib.project_state import drop_fixture_rows, fixture_company_ids

        class _Boom:
            def find(self, *a, **k):
                raise RuntimeError("no mongo")

        class _DB:
            companies = _Boom()

        self.assertEqual(asyncio.run(fixture_company_ids(_DB())), set())
        rows = [{"company_id": "a"}, {"company_id": "b"}]
        self.assertEqual(drop_fixture_rows(rows, set()), rows)

    def test_the_drop_actually_drops(self):
        """The instrument, against a case known to be wrong: the production
        shape, with the fixture company present."""
        from lib.project_state import drop_fixture_rows
        FIXTURE = "6a32a11051c7a54c476d2149"      # the company named 'test'
        REAL = "6a5e153cc7ac7a6451aa2d32"         # BLUEVIEW CONSTRUCTION INC
        rows = [
            {"_id": "p1", "company_id": REAL, "name": "588 Thomas"},
            {"_id": "p2", "company_id": FIXTURE, "name": "857 Prescott Pl"},
            {"_id": "p3", "company_id": FIXTURE, "name": "587 Prescott Place"},
            {"_id": "p4", "company_id": None, "name": "no company"},
        ]
        kept = drop_fixture_rows(rows, {FIXTURE})
        self.assertEqual([r["name"] for r in kept], ["588 Thomas", "no company"])

    def test_a_company_row_is_dropped_on_its_own_id(self):
        from lib.project_state import drop_fixture_rows
        rows = [{"_id": "c1"}, {"_id": "c2"}]
        self.assertEqual(drop_fixture_rows(rows, {"c2"}, key="_id"),
                         [{"_id": "c1"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
