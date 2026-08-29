"""The detector's scope, and the pass that corrects what it already wrote.

285 rows asserted that a required daily log had not been filed. Reading the
right collection accounted for 28 of them. The other 257 were scope: the driver
iterated `{"status": "active", ...}`, and `projects.status` is written once at
creation and never changed by anything — so it matched every project that ever
existed while reading as though it excluded something.

What it actually omitted, on live data:

  * 587 Prescott Place — marked_for_deletion, still flagged nightly, 14 rows.
    The rest of the product treats such a project as invisible and inert, and
    the comment on ACTIVE_PROJECT_FILTER says so in as many words.
  * 8 Walworth Street — 28 rows on a project with no check-in and no sign-in
    in its entire life. Every expected day was invented.

THE SKIP IS ABOUT THE PROJECT, NOT THE DAY. "No check-ins that day" would be a
detector that goes quiet exactly when the gate misses a day. "Never, in the
project's whole life" is evidence about the project — and it is counted in the
tick line rather than taken silently, because a compliance check that stops
checking without saying so is the failure this file already made once in the
other direction.
"""

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib.logbook import missing_detector, schema as logbook_schema  # noqa: E402
from lib.project_state import ACTIVE_PROJECT_FILTER  # noqa: E402

import correct_missing_daily_log_flags as correction  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()

    async def to_list(self, length=None):
        return list(self._docs)


class TheScopeFilter(unittest.TestCase):
    def test_it_is_the_shared_one(self):
        self.assertEqual(
            ACTIVE_PROJECT_FILTER,
            {"is_deleted": {"$ne": True}, "marked_for_deletion": {"$ne": True}},
        )

    def test_marked_for_deletion_is_excluded(self):
        """587 Prescott Place, flagged nightly while marked for deletion."""
        self.assertIn("marked_for_deletion", ACTIVE_PROJECT_FILTER)

    def test_status_is_not_part_of_it(self):
        """`projects.status` is written "active" at creation and never changed.
        A field that is never updated is not state, and keeping it in a filter
        suggests a lifecycle that does not exist."""
        self.assertNotIn("status", ACTIVE_PROJECT_FILTER)

    def test_the_driver_uses_it_and_not_a_local_pair(self):
        """AST, not a text search: the driver DESCRIBES the filter it used to
        carry, deliberately and at length, and a grep cannot tell that comment
        from the code."""
        import ast
        import inspect
        src = inspect.getsource(missing_detector.run_missing_detector_for_all_projects)
        self.assertIn("ACTIVE_PROJECT_FILTER", src)
        tree = ast.parse(inspect.cleandoc(src.replace("async def", "def", 1)))
        literals = [
            k.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        ]
        self.assertNotIn("status", literals,
                         "the driver still filters projects on a status field")

    def test_server_imports_the_same_constant(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn("from lib.project_state import ACTIVE_PROJECT_FILTER", src)
        self.assertNotIn("ACTIVE_PROJECT_FILTER = {", src,
                         "server.py redefines it — there are two copies again")


def _db(projects, checkins=(), sign_ins=()):
    db = MagicMock()
    db.projects = MagicMock()
    db.projects.find = MagicMock(return_value=_Cursor(projects))
    db.checkins = MagicMock()
    db.checkins.find_one = AsyncMock(side_effect=lambda q, *a, **k: next(
        (c for c in checkins if c["project_id"] == q.get("project_id")), None))
    db.sign_ins = MagicMock()
    db.sign_ins.find_one = AsyncMock(side_effect=lambda q, *a, **k: next(
        (s for s in sign_ins if s["project_id"] == q.get("project_id")), None))
    db.logbooks = MagicMock()
    db.logbooks.find = MagicMock(return_value=_Cursor([]))
    db.logbook_entries = MagicMock()
    db.logbook_entries.find = MagicMock(return_value=_Cursor([]))
    db.logbook_entries.update_one = AsyncMock(
        return_value=MagicMock(matched_count=0, upserted_id="x"))
    return db


WORKED = {"_id": "worked", "company_id": "co", "status": "active",
          "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc)}
NEVER = {"_id": "never", "company_id": "co", "status": "active",
         "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc)}


class TheNeverWorkedSkip(unittest.TestCase):
    def test_a_project_with_no_gate_activity_ever_is_skipped(self):
        """8 Walworth Street: 28 flags, no check-in and no sign-in, ever."""
        db = _db([NEVER])
        summary = _run(missing_detector.run_missing_detector_for_all_projects(
            db, now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)))
        self.assertEqual(summary["projects_skipped_no_gate_activity"], 1)
        self.assertEqual(summary["missing_entries_written"], 0)

    def test_the_skip_is_counted_not_silent(self):
        """A compliance check that stops checking without saying so is the
        failure this file already made once."""
        db = _db([NEVER])
        summary = _run(missing_detector.run_missing_detector_for_all_projects(db))
        self.assertIn("projects_skipped_no_gate_activity", summary)

    def test_a_worked_project_is_still_scanned(self):
        db = _db([WORKED], checkins=[{"project_id": "worked"}])
        summary = _run(missing_detector.run_missing_detector_for_all_projects(
            db, now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)))
        self.assertEqual(summary["projects_skipped_no_gate_activity"], 0)
        self.assertGreater(summary["missing_entries_written"], 0)

    def test_either_source_counts_as_activity(self):
        """The gate rollout runs two collections; a project may have only one."""
        db = _db([WORKED], sign_ins=[{"project_id": "worked"}])
        summary = _run(missing_detector.run_missing_detector_for_all_projects(
            db, now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)))
        self.assertEqual(summary["projects_skipped_no_gate_activity"], 0)

    def test_a_failed_lookup_does_not_skip_the_project(self):
        """An unreadable answer is not evidence the project is unworked, and
        skipping on it would silently stop checking a live jobsite."""
        db = _db([WORKED])
        db.checkins.find_one = AsyncMock(side_effect=RuntimeError("mongo down"))
        self.assertTrue(_run(
            missing_detector._has_ever_had_gate_activity(db, WORKED)))


class TheCorrectionPass(unittest.TestCase):
    """Three outcomes, and nothing is deleted."""

    def _db_with(self, rows, filed=(), activity=()):
        db = MagicMock()
        db.logbook_entries = MagicMock()
        db.logbook_entries.find = MagicMock(return_value=_Cursor(rows))
        db.logbook_entries.update_one = AsyncMock(return_value=MagicMock())
        db.logbooks = MagicMock()
        db.logbooks.find_one = AsyncMock(side_effect=lambda q, *a, **k: (
            {"_id": "lb"} if (q.get("project_id"), (q.get("date") or {}).get("$gte"))
            in filed else None))

        async def _act(q, *a, **k):
            return {"_id": "x"} if q.get("project_id") in activity else None
        coll = MagicMock()
        coll.find_one = AsyncMock(side_effect=_act)
        db.__getitem__ = MagicMock(return_value=coll)
        return db

    ROW = {"_id": "e1", "project_id": "p1", "entry_date": "2026-08-20",
           "status": "missing", "category": "daily_log"}

    def test_a_day_with_a_filed_log_flips_to_complete(self):
        db = self._db_with([self.ROW], filed={("p1", "2026-08-20")})
        counts = _run(correction.run(db, execute=True))
        self.assertEqual(counts[logbook_schema.STATUS_COMPLETE], 1)
        _q, update = db.logbook_entries.update_one.call_args[0]
        self.assertEqual(update["$set"]["status"], logbook_schema.STATUS_COMPLETE)

    def test_a_day_nobody_worked_is_marked_phantom_not_complete(self):
        """Saying "complete" would be the same false claim in the other
        direction: the log was not filed."""
        db = self._db_with([self.ROW])
        counts = _run(correction.run(db, execute=True))
        self.assertEqual(counts[logbook_schema.STATUS_NO_SITE_ACTIVITY], 1)
        _q, update = db.logbook_entries.update_one.call_args[0]
        self.assertEqual(update["$set"]["status"],
                         logbook_schema.STATUS_NO_SITE_ACTIVITY)
        self.assertIn("no site activity", update["$set"]["superseded_reason"])

    def test_a_real_gap_is_left_standing(self):
        """Crew on site, no log filed — the only rows worth a customer's
        attention, and the pass does not touch them."""
        db = self._db_with([self.ROW], activity={"p1"})
        counts = _run(correction.run(db, execute=True))
        self.assertEqual(counts["left_standing"], 1)
        db.logbook_entries.update_one.assert_not_called()

    def test_the_original_status_is_kept_on_the_row(self):
        db = self._db_with([self.ROW])
        _run(correction.run(db, execute=True))
        _q, update = db.logbook_entries.update_one.call_args[0]
        self.assertEqual(update["$set"]["superseded_status"], "missing")
        self.assertIn("corrected_at", update["$set"])

    def test_nothing_is_deleted_ever(self):
        import inspect
        src = inspect.getsource(correction)
        for destructive in ("delete_one", "delete_many", "drop("):
            self.assertNotIn(destructive, src)

    def test_dry_run_writes_nothing(self):
        db = self._db_with([self.ROW])
        counts = _run(correction.run(db, execute=False))
        self.assertEqual(counts[logbook_schema.STATUS_NO_SITE_ACTIVITY], 1)
        db.logbook_entries.update_one.assert_not_called()

    def test_it_only_reads_rows_still_missing(self):
        """Idempotent: a second run finds only what the first left standing."""
        db = self._db_with([self.ROW])
        _run(correction.run(db, execute=True))
        query = db.logbook_entries.find.call_args[0][0]
        self.assertEqual(query["status"], logbook_schema.STATUS_MISSING)

    def test_a_failed_activity_lookup_leaves_the_row_standing(self):
        """Marking a real gap as phantom is the one outcome here that loses
        information, so an unreadable answer keeps the row."""
        db = self._db_with([self.ROW])
        coll = MagicMock()
        coll.find_one = AsyncMock(side_effect=RuntimeError("mongo down"))
        db.__getitem__ = MagicMock(return_value=coll)
        counts = _run(correction.run(db, execute=True))
        self.assertEqual(counts["left_standing"], 1)


if __name__ == "__main__":
    unittest.main()
