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


def _raw_handle_bindings(tree):
    """(lineno, statement) for every `<name> = <client>[<db>]` -- a database
    taken straight off a client and bound to a name, with nothing in between.

    The SUBSCRIPT is what identifies it, and it is why `audited(...)` does not
    match: `db = audited(client[name], args, NAME)` binds the result of a CALL,
    so the subscript is an argument rather than the value being assigned. There
    is no way to write the wrapped form that looks like the raw one.
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        if not isinstance(node.value, ast.Subscript):
            continue
        src = ast.unparse(node.value)
        if "Client(" in src or src.split("[")[0].endswith("client"):
            out.append((node.lineno, ast.unparse(node)))
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

    def test_the_walk_can_SEE_a_handle_taken_off_the_client(self):
        """The second instrument, against the line the 19:07:45Z session ran."""
        tree = ast.parse("client = MongoClient(url)\ndb = client[dbname]\n")
        self.assertEqual([s for _, s in _raw_handle_bindings(tree)],
                         ["db = client[dbname]"])
        tree = ast.parse("db = AsyncIOMotorClient(url)[dbname]\n")
        self.assertEqual(len(_raw_handle_bindings(tree)), 1)

    def test_the_wrapped_form_is_not_reported(self):
        """AND IT MUST NOT BE, or the check fires on every correct script and
        gets deleted by the next person who touches this file."""
        self.assertEqual(_raw_handle_bindings(ast.parse(
            "db = audited(client[dbname], args, NAME)\n")), [])
        self.assertEqual(_raw_handle_bindings(ast.parse(
            "db = audited(MongoClient(url)[dbname], args, NAME)\n")), [])

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
        the row is what makes an intended write traceable afterwards.

        TWO WAYS TO SATISFY IT, AND THE SECOND IS THE ONE TO PREFER. This
        assertion originally looked only for a hand-placed `script_audit(` call.
        The design moved to the `audited()` handle wrapper, and the reason is
        the reason this assertion is weak: a source test can only prove a call
        EXISTS, never that it RUNS when the write runs, so a hand-placed
        `script_audit(` sitting after an early return or on the dry-run branch
        reads here exactly like one that fires. Wrapping the handle makes the
        row a property of the WRITE -- `db.dob_logs.delete_many(...)` audits
        because it executed, not because somebody remembered -- which is the
        only version of this that control flow cannot get around.

        `= audited(` and not `audited(`: the guard block every retrofitted
        script carries says "goes through `audited(...)`" in a COMMENT, and
        matching that would pass a file that describes the wrapper without
        using it. Measured -- it was true of strip_inline_worker_image, which
        imported `audited`, never called it, and gated perfectly while
        recording nothing.
        """
        missing = []
        for n in self.writers:
            src = (SCRIPTS / n).read_text(encoding="utf-8")
            if "script_audit(" not in src and "= audited(" not in src:
                missing.append(n)
        self.assertEqual(missing, [], "no audit row written by: "
                         + ", ".join(missing))

    def test_no_handle_is_TAKEN_OFF_THE_CLIENT_UNWRAPPED(self):
        """The gate reaches the write, asserted structurally rather than by
        line number.

        WHAT THIS REPLACED, AND WHY IT HAD TO. This was a position check: find
        `check_guard(`, find the first write, fail if the gate came later. That
        premise died with the design. Nine of these scripts build their parser
        in `if __name__ == "__main__":` deliberately, so that `--i-know` with no
        reason is an argument error BEFORE main() runs rather than something the
        operator discovers behind a missing environment variable -- which puts
        `check_guard(` at the bottom of the file, textually after every write.
        And the writes themselves frequently sit in a helper defined ABOVE the
        function that builds the handle (`cleanup_marker(db)`, `run(db,
        execute)`), so even measuring from `db = audited(...)` reports the
        correct files as broken. A source position cannot express "this handle
        was wrapped before that call ran".

        WHAT IS CHECKABLE, AND IS THE ACTUAL FAILURE. `db = client[db_name]`
        followed by a write is the unguarded shape -- it is literally the line
        the 19:07:45Z session ran. So: in a script that writes, a database must
        never be taken off a client and bound to a name without passing through
        `audited(...)` on the way. Where the handle is built is then the only
        place it can be built, and every write in the file is reached through
        it, however many helpers deep.

        THE TWO EXEMPTED ARE THE TWO THAT AUDIT BY HAND. delete_rodent_
        inspections and reparent_project predate the wrapper and place their own
        `script_audit(` calls; they are asserted by the audit-row test above and
        by TheTwoWritersBuiltOnItStayBuiltOnIt below. A file cannot buy the
        exemption by accident -- it has to contain a real audit call.
        """
        bad = []
        for name in self.writers:
            src = (SCRIPTS / name).read_text(encoding="utf-8")
            if "script_audit(" in src:
                continue            # audits by hand; asserted separately
            for lineno, stmt in _raw_handle_bindings(ast.parse(src)):
                bad.append(f"{name}:{lineno}  {stmt}")
        self.assertEqual(bad, [], "a database handle reaches a write without "
                         "audited(): " + "; ".join(bad))


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


class _Result:
    modified_count = 2


class _FakeColl:
    def __init__(self, name, log):
        self.name, self.log = name, log

    def find_one(self, *a, **kw):        # what marks this as a collection
        return None

    def update_many(self, *a, **kw):
        self.log.append(("update_many", self.name))
        return _Result()

    def insert_one(self, doc):
        self.log.append(("insert_one", self.name, doc))
        return _Result()


class _FakeAsyncColl(_FakeColl):
    async def update_many(self, *a, **kw):
        return _FakeColl.update_many(self, *a, **kw)

    async def insert_one(self, doc):
        return _FakeColl.insert_one(self, doc)


class _FakeDb:
    COLL = _FakeColl

    def __init__(self):
        self.log = []

    def __getattr__(self, name):
        return type(self).COLL(name, self.log)

    def __getitem__(self, name):
        return type(self).COLL(name, self.log)

    def list_collection_names(self):
        return ["a", "b"]


class _FakeAsyncDb(_FakeDb):
    COLL = _FakeAsyncColl


class TheWrappedHandleActUALLYWrites(unittest.TestCase):
    """THE WRAPPER IS THE GUARD NOW, so it needs an instrument of its own.

    A source test can see that `audited(` is on the line. It cannot see that the
    wrapped call still performs the write, and that is the failure mode with the
    worst shape available: a wrapper that hands a sync caller back a coroutine
    it never awaits makes the WRITE SILENTLY NOT HAPPEN while the run reports
    success and the census test reads green. Three of the twenty scripts here
    drive PyMongo, so that is not hypothetical.
    """

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        self.args = type("A", (), {"i_know": True, "reason": "why",
                                   "session": "sess"})()

    def test_a_PYMONGO_handle_writes_and_audits(self):
        from prod_guard import audited
        db = _FakeDb()
        result = audited(db, self.args, "probe").workers.update_many({}, {})
        self.assertEqual(result.modified_count, 2, "the write did not run")
        self.assertEqual([e[:2] for e in db.log],
                         [("update_many", "workers"), ("insert_one", "audit_logs")])

    def test_a_MOTOR_handle_writes_and_audits(self):
        import asyncio
        from prod_guard import audited
        db = _FakeAsyncDb()
        result = asyncio.run(
            audited(db, self.args, "probe").workers.update_many({}, {}))
        self.assertEqual(result.modified_count, 2, "the write did not run")
        self.assertEqual([e[:2] for e in db.log],
                         [("update_many", "workers"), ("insert_one", "audit_logs")])

    def test_the_row_carries_the_reason_and_the_session(self):
        """Without these the row is a write nobody can trace, which is the
        thing the flag exists to make impossible."""
        from prod_guard import audited
        db = _FakeDb()
        audited(db, self.args, "probe").workers.update_many({}, {})
        row = db.log[1][2]
        self.assertEqual(row["user_id"], "script:probe")
        self.assertEqual(row["reason"], "why")
        self.assertEqual(row["session_id"], "sess")
        self.assertEqual(row["details"]["modified_count"], "2")

    def test_a_DATABASE_METHOD_is_not_wrapped_into_a_collection(self):
        """`db.list_collection_names()` is a method, not a collection. Wrapping
        one returns an object that is not callable, so the script dies on a READ
        it was never meant to touch -- cleanup_v21_inert_data calls exactly this
        before it drops anything."""
        from prod_guard import audited
        self.assertEqual(
            audited(_FakeDb(), self.args, "probe").list_collection_names(),
            ["a", "b"])

    def test_a_dry_run_is_handed_the_BARE_handle(self):
        """Nothing to audit when nothing is written, and a layer to step through
        while debugging a dry run is a cost with no purchase."""
        from prod_guard import audited
        db = _FakeDb()
        self.assertIs(audited(db, type("A", (), {"i_know": False})(), "p"), db)


if __name__ == "__main__":
    unittest.main(verbosity=2)
