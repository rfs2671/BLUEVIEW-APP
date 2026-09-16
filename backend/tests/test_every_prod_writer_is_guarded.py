"""EVERY SCRIPT THAT WRITES PRODUCTION LEAVES A ROW BEHIND.

── THE DATE THIS EARNED ────────────────────────────────────────────────────

2026-09-16, 19:07:45Z. A session ran `railway run -- python /c/tmp/writes.py`
and did two things to the production database:

    db.projects.update_one({"_id": E852}, {"$set": {"is_deleted": False}})
    db.projects.delete_one({"_id": STUB})

Both were defensible. The second counted references across thirteen collections
and found none before deleting. Both were INVISIBLE: `railway run` injects the
production environment LOCALLY, so the connection comes from the laptop and
never touches the container — no HTTP log line, no application audit row — and
the cluster is Atlas shared tier, where database auditing does not exist. A
project document left the database and the only trace was a cron error four
hours earlier that happened to name the id.

OPERATOR RULE: a production write goes through the app, which is audited, or
through a file in backend/scripts/ carrying the `--i-know` guard and writing an
audit row with actor `script:<name>`, the session and the reason.

── WHAT THIS FILE ASSERTS, AND WHY IT IS AN AST WALK ───────────────────────

A hand-kept list of "the scripts we guarded" is a check with an expiry date
nobody set: the twenty-first writer is not on it and nothing says so. So the
census is DERIVED — every .py in backend/scripts/ whose AST contains a write
call on a database handle must import the guard, gate on it, and audit.

THE FLAG IS NOT THE POINT. A flag only stops an accident, and this was not an
accident. THE AUDIT ROW IS THE POINT; `--i-know` exists so that writing one is
unavoidable, because the parser will not let you past without also supplying
the reason and the session that the row records.
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

SCRIPTS = _BACKEND / "scripts"

#: Mongo methods that change stored data.
WRITE_METHODS = frozenset({
    "update_one", "update_many", "insert_one", "insert_many",
    "delete_one", "delete_many", "bulk_write", "replace_one",
    "find_one_and_update", "find_one_and_delete", "drop",
})

#: Scripts that are NOT production writers and are exempt BY REASON, each
#: stated. Anything not here is judged by its AST.
EXEMPT = {
    # The guard itself, and the two writers built on it. `script_audit` IS an
    # insert_one; asking the guard to guard itself is a cycle, not a check.
    "prod_guard": "the guard's own audit insert",
    "reparent_project": "built on the guard; asserted separately below",
    "set_building_levels": "built on the guard; asserted separately below",
    # STATIC ANALYSERS. Their `delete_many` / `update_one` hits are string
    # literals inside their own method lists -- they read source and write
    # nothing. Measured: this mistake was made once already, and reported three
    # analysers as unguarded production writers.
    "find_reads_without_writers": "static analyser; write names are literals",
    "find_unserved_sorts": "static analyser; write names are literals",
    "audit_production": "static analyser; write names are literals",
    "audit_probe_field_discipline": "AST walk over probe scripts, no I/O",
    "probe_helpers": "pure helpers over an already-fetched list",
}


def _writes_in(tree):
    """(lineno, expression) for every write call on something named `db`."""
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in WRITE_METHODS):
            continue
        src = ast.unparse(node.func)
        head = src.split(".")[0].split("[")[0]
        if head == "db" or ".db." in src or src.startswith("db"):
            out.append((node.lineno, src))
    return out


def _scripts_that_write():
    out = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.stem in EXEMPT:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:  # a script that will not parse cannot run
            out[path.name] = ("SYNTAX ERROR", e)
            continue
        hits = _writes_in(tree)
        if hits:
            out[path.name] = hits
    return out


class TheCensusIsReal(unittest.TestCase):

    def test_the_scripts_directory_is_where_we_think(self):
        self.assertTrue(SCRIPTS.is_dir(), SCRIPTS)
        self.assertGreater(len(list(SCRIPTS.glob("*.py"))), 30)

    def test_the_walk_finds_writers(self):
        """AN EMPTY CENSUS SATISFIES EVERY ASSERTION BELOW. If the walk breaks,
        this file reports clean over twenty unguarded scripts."""
        found = _scripts_that_write()
        self.assertGreaterEqual(
            len(found), 15,
            f"only {len(found)} writers found; the walk is stale and this file "
            "is no longer checking anything")

    def test_the_walk_can_SEE_an_unguarded_writer(self):
        """The instrument, against a case known to be wrong."""
        tree = ast.parse("async def f(db):\n    await db.projects.delete_one({})\n")
        self.assertEqual([s for _, s in _writes_in(tree)],
                         ["db.projects.delete_one"])

    def test_it_does_not_fire_on_a_string_literal(self):
        """The static analysers list these method names as DATA. Reporting them
        as writers is a mistake this repo has already made once."""
        tree = ast.parse('WRITE_METHODS = ["delete_many", "update_one"]\n')
        self.assertEqual(_writes_in(tree), [])


class EveryWriterIsGuarded(unittest.TestCase):

    def setUp(self):
        self.writers = _scripts_that_write()

    def test_each_one_imports_the_guard(self):
        missing = [n for n in self.writers
                   if "prod_guard" not in (SCRIPTS / n).read_text(encoding="utf-8")]
        self.assertEqual(missing, [], "no --i-know guard imported in: "
                         + ", ".join(missing))

    def test_each_one_GATES_on_it(self):
        """Importing is not calling. A guard that is imported and never invoked
        is the failure mode a source test is blindest to."""
        missing = [n for n in self.writers
                   if "check_guard(" not in (SCRIPTS / n).read_text(encoding="utf-8")]
        self.assertEqual(missing, [], "guard imported but never called in: "
                         + ", ".join(missing))

    def test_each_one_WRITES_AN_AUDIT_ROW(self):
        """THE POINT OF THE WHOLE EXERCISE. The flag only stops an accident;
        the row is what makes an intended write traceable afterwards."""
        missing = [n for n in self.writers
                   if "script_audit(" not in (SCRIPTS / n).read_text(encoding="utf-8")]
        self.assertEqual(missing, [], "no audit row written by: "
                         + ", ".join(missing))

    def test_the_gate_is_reached_before_the_write(self):
        """Ordering, not presence. A `check_guard` call that sits AFTER the
        write reads exactly like one that protects it."""
        late = []
        for name, hits in self.writers.items():
            src = (SCRIPTS / name).read_text(encoding="utf-8")
            if "check_guard(" not in src:
                continue
            gate_line = src[:src.index("check_guard(")].count("\n") + 1
            first_write = min(ln for ln, _ in hits)
            if gate_line > first_write:
                late.append(f"{name}: gate at {gate_line}, write at {first_write}")
        self.assertEqual(late, [], "guard called after the write in: "
                         + "; ".join(late))


class TheTwoWritersBuiltOnItStayBuiltOnIt(unittest.TestCase):
    """Exempt from the census above because they are the reference
    implementation; asserted here so the exemption cannot hide a regression."""

    def test_they_gate_and_audit(self):
        for name in ("reparent_project", "set_building_levels"):
            with self.subTest(name):
                src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
                self.assertIn("check_guard(args)", src)
                self.assertIn("script_audit(", src)


class TheGuardItself(unittest.TestCase):

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))

    def test_no_flag_is_a_dry_run_and_not_an_error(self):
        """The DEFAULT is a report. That is what makes the guard cheap enough to
        comply with rather than route around."""
        from prod_guard import check_guard
        self.assertFalse(check_guard(type("A", (), {"i_know": False})()))

    def test_the_flag_alone_is_an_ERROR(self):
        """`--i-know` without a reason or a session would leave exactly the row
        this exists to prevent: a deliberate write nobody can trace."""
        from prod_guard import check_guard
        for reason, session in (("", ""), ("why", ""), ("", "sess")):
            with self.subTest(reason=reason, session=session):
                args = type("A", (), {"i_know": True, "reason": reason,
                                      "session": session})()
                with self.assertRaises(SystemExit) as cm:
                    check_guard(args)
                self.assertEqual(cm.exception.code, 2)

    def test_whitespace_is_not_a_reason(self):
        from prod_guard import check_guard
        args = type("A", (), {"i_know": True, "reason": "   ",
                              "session": "  "})()
        with self.assertRaises(SystemExit):
            check_guard(args)

    def test_a_complete_invocation_passes(self):
        from prod_guard import check_guard
        args = type("A", (), {"i_know": True, "reason": "operator ruling",
                              "session": "abc"})()
        self.assertTrue(check_guard(args))

    def test_the_actor_is_never_a_user_id(self):
        """No user did this. Attributing a machine's act to a person's id is
        worse than leaving it blank, because it reads as evidence."""
        from prod_guard import SCRIPT_ACTOR_PREFIX
        self.assertEqual(SCRIPT_ACTOR_PREFIX, "script:")

    def test_it_writes_into_the_SAME_collection_the_app_uses(self):
        """One place to read when the question is "what happened to this
        project", rather than a second log nobody remembers to check."""
        from prod_guard import AUDIT_COLLECTION
        self.assertEqual(AUDIT_COLLECTION, "audit_logs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
