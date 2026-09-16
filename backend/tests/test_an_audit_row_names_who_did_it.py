"""FOUR COMPANIES WERE PERMANENTLY DESTROYED AND THE LOG CANNOT SAY BY WHOM.

── THE MEASUREMENT ─────────────────────────────────────────────────────────

691 audit rows on production. 8 carry an empty `user_id`, and ALL FOUR
`company_hard_delete` rows are among them:

    2026-04-13 22:25:35  company_hard_delete  by ''  698a81182450927f5fa2b439
    2026-04-20 22:10:42  company_hard_delete  by ''  698a58789fe33d19cbecd4a6
    2026-06-17 13:28:26  company_hard_delete  by ''  69e6a477aaade43f835aeeaa
    2026-06-17 13:28:35  company_hard_delete  by ''  69e16add079abf2b78ee08ce

`hard_delete_company` deletes the company AND every user under it. Three of
those four ids are the orphaned companies whose projects are still in the
database with nothing to hang them on — 26 projects and 20 logbooks, one of
them still live.

── THE CAUSE, AND IT WAS ALREADY WRITTEN DOWN ONCE ─────────────────────────

`get_current_user` returns `serialize_id(user)`, which sets `obj["id"]` and
then DELETES `obj["_id"]`. So `user.get("_id", "")` is "" on every request that
has ever been made. `delete_logbook` carries this fix inline, with a comment
that says so in capitals — it was never made shared, so three other handlers
kept the bug and a fourth (`checkout`) was found while fixing them.

── AND THE TIMESTAMP IS NOT BROKEN ─────────────────────────────────────────

A report claimed the audit log had no timestamps because `created_at` was None
on every row. The field is `timestamp`, it is server-side UTC, and all 691 rows
carry one, from 2026-04-10 onward. Pinned below so the same wrong conclusion
cannot be drawn twice, and so nobody "fixes" it by adding a second date field.
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)


class _Rows:
    def __init__(self):
        self.rows = []

    async def insert_one(self, row):
        self.rows.append(row)
        return type("R", (), {"inserted_id": "x"})()


class Base(unittest.TestCase):
    def setUp(self):
        self._db = server.db
        self.rows = _Rows()

        class _DB:
            audit_logs = self.rows
        server.db = _DB()

    def tearDown(self):
        server.db = self._db


class TheActorIsReadFromTheKeyThatExists(unittest.TestCase):

    def test_id_wins_because_it_is_the_one_that_is_there(self):
        self.assertEqual(server.actor_id({"id": "abc"}), "abc")

    def test__id_is_a_fallback_for_a_raw_mongo_document(self):
        """Some callers hand over a document straight off the collection, which
        HAS `_id` and no `id`. Dropping that branch would break them."""
        self.assertEqual(server.actor_id({"_id": "raw"}), "raw")

    def test_id_beats__id_when_both_are_present(self):
        self.assertEqual(server.actor_id({"id": "a", "_id": "b"}), "a")

    def test_the_shape_get_current_user_ACTUALLY_returns(self):
        """THE CASE THE OLD CODE GOT WRONG, built the way the real one is."""
        row = server.serialize_id({"_id": "6a68b16ebe9c27dedf5cf47f",
                                   "name": "Michael Cespedes"})
        self.assertNotIn("_id", row, "serialize_id deletes it — that is the bug")
        self.assertEqual(server.actor_id(row), "6a68b16ebe9c27dedf5cf47f")
        # And the old expression, on the same row, for the control.
        self.assertEqual(str(row.get("_id", "")), "")

    def test_it_is_total(self):
        for bad in (None, {}, "nonsense", 7, {"id": None, "_id": None}):
            with self.subTest(repr(bad)):
                self.assertEqual(server.actor_id(bad), "")


class AnActorLessRowIsNotWrittenQuietly(Base):

    def test_it_is_marked_and_not_left_blank(self):
        """"" sorts and groups with every other blank field. `UNATTRIBUTED` is
        one query, which is the difference between a findable gap and a gap
        nobody can see."""
        asyncio.run(server.audit_log("company_hard_delete", "", "company", "c1"))
        row = self.rows.rows[0]
        self.assertEqual(row["user_id"], server.UNATTRIBUTED_ACTOR)
        self.assertIs(row["actor_missing"], True)

    def test_whitespace_is_not_an_actor(self):
        asyncio.run(server.audit_log("x", "   ", "company", "c1"))
        self.assertEqual(self.rows.rows[0]["user_id"], server.UNATTRIBUTED_ACTOR)

    def test_None_is_not_an_actor(self):
        asyncio.run(server.audit_log("x", None, "company", "c1"))
        self.assertEqual(self.rows.rows[0]["user_id"], server.UNATTRIBUTED_ACTOR)

    def test_IT_STILL_WRITES(self):
        """Refusing would mean a destructive operation with NO record at all.
        The event happened either way; the log's job is to say so."""
        asyncio.run(server.audit_log("company_hard_delete", "", "company", "c1"))
        self.assertEqual(len(self.rows.rows), 1)

    def test_a_real_actor_is_untouched_and_unmarked(self):
        asyncio.run(server.audit_log("x", "6a68b16e", "company", "c1"))
        row = self.rows.rows[0]
        self.assertEqual(row["user_id"], "6a68b16e")
        self.assertNotIn("actor_missing", row)


class EveryRowIsStamped(Base):

    def test_the_field_is_timestamp_and_it_is_server_side_utc(self):
        before = datetime.now(timezone.utc)
        asyncio.run(server.audit_log("x", "u1", "company", "c1"))
        row = self.rows.rows[0]
        self.assertIn("timestamp", row)
        self.assertIsNotNone(row["timestamp"].tzinfo)
        self.assertGreaterEqual(row["timestamp"], before)

    def test_there_is_NOT_a_second_date_field(self):
        """A reader asked these rows for `created_at`, got None on all 691 and
        reported the log as undated. The fix for that is to read `timestamp`,
        not to add a second field — two date columns on one row is how they
        drift and how a filed record ends up with two different answers."""
        asyncio.run(server.audit_log("x", "u1", "company", "c1"))
        self.assertNotIn("created_at", self.rows.rows[0])

    def test_the_caller_cannot_supply_the_timestamp(self):
        import inspect
        params = list(inspect.signature(server.audit_log).parameters)
        self.assertEqual(
            params, ["action", "user_id", "resource_type", "resource_id",
                     "details"],
            "a timestamp argument would let a caller date its own audit row")


class NoCallSiteReadsTheKeyThatIsNotThere(unittest.TestCase):
    """THE CENSUS. Derived from the AST, so a new handler written the old way
    fails on the day it is written rather than four companies later."""

    def _audit_calls(self):
        out = []
        for node in ast.walk(TREE):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name != "audit_log" or len(node.args) < 2:
                continue
            out.append((node.lineno, ast.unparse(node.args[1])))
        return out

    def test_the_census_is_not_empty(self):
        calls = self._audit_calls()
        self.assertGreaterEqual(len(calls), 15, calls)

    def test_no_actor_argument_reads__id_first(self):
        bad = [f"server.py:{ln} {expr}" for ln, expr in self._audit_calls()
               if '"_id"' in expr and expr.find('"_id"') < (
                   expr.find('"id"') if '"id"' in expr else 10 ** 6)
               and "actor_id" not in expr
               # A raw collection document genuinely has `_id` and no `id`.
               and "worker[" not in expr]
        self.assertEqual(
            bad, [],
            "`_id` is deleted by serialize_id; reading it first yields '' on "
            "every request. Use actor_id(): " + "; ".join(bad))

    def test_the_four_destructive_actions_use_the_helper(self):
        """The ones whose missing actor already cost something."""
        by_action = {}
        for node in ast.walk(TREE):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name != "audit_log" or len(node.args) < 2:
                continue
            if isinstance(node.args[0], ast.Constant):
                by_action[node.args[0].value] = ast.unparse(node.args[1])
        for action in ("company_hard_delete", "user_delete", "user_update",
                       "checkout"):
            with self.subTest(action):
                self.assertIn(action, by_action)
                self.assertIn("actor_id(", by_action[action])


if __name__ == "__main__":
    unittest.main(verbosity=2)
