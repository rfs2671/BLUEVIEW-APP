"""Both compliance detectors read the document the CP actually files.

They read `db.daily_logs`, and `missing_detector` called it "the
operator-recorded source of truth" in its own docstring. Production holds 92
rows there, every one written between 2026-04-03 and 2026-04-16 by "TEST" and
"Roy Fishman", and nothing since — the operator's April testing of a kiosk
screen. The CP has been filing and signing a `daily_jobsite` logbook every
working day the whole time.

The two detectors failed in opposite directions off the same mistake:

    missing_detector   285 rows asserting a required daily log was not filed
    deficiency         nothing to scan, so nothing found, and "no deficiencies"
                       reads as CLEAN

And missing_detector had no un-flag path at all: it only ever touched the
absent days, so a date flagged on Monday and filed on Tuesday kept its false
`missing` row for the life of the project.
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

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib.logbook import daily_jobsite_source as src  # noqa: E402
from lib.logbook import deficiency, missing_detector  # noqa: E402
from lib.logbook import schema as logbook_schema  # noqa: E402


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


FILED = {
    "_id": "lb1",
    "project_id": "proj_a",
    "date": "2026-05-04",
    "log_type": "daily_jobsite",
    "status": "submitted",
    "data": {
        "general_description": "Framing and electrical rough-in.",
        "weather": "Clear",
        "weather_temp": "68F",
        "activities": [
            {"company": "Arkon Builders", "trade": "Framers", "num_workers": 5,
             "work_description": "wall framing"},
            {"company": "Power Direct", "trade": "Electrician", "num_workers": 6,
             "work_description": "rough-in"},
        ],
        "observations": [{"description": "Housekeeping corrected at 2pm"}],
    },
}


class TheFilterNamesTheRightDocument(unittest.TestCase):
    def test_it_reads_the_filed_daily_jobsite_log(self):
        q = src.daily_jobsite_filter("proj_a")
        self.assertEqual(q["log_type"], "daily_jobsite")
        self.assertEqual(q["status"], "submitted")
        self.assertEqual(q["is_amendment"], {"$ne": True})
        self.assertEqual(q["is_deleted"], {"$ne": True})

    def test_a_draft_is_not_a_filed_record(self):
        """Counting an unsigned draft as present would let it satisfy a
        compliance check — the same class of error as the false flag."""
        self.assertEqual(src.daily_jobsite_filter("p")["status"], "submitted")

    def test_it_does_NOT_key_on_is_locked(self):
        """An END_OF_DAY log is submitted-and-unlocked until the overnight
        sweep. Keying on the lock would flag every day as missing until 3am and
        then silently un-flag it — an answer that depends on what time you
        ask."""
        self.assertNotIn("is_locked", src.daily_jobsite_filter("p"))

    def test_neither_detector_reads_daily_logs_any_more(self):
        """AST, not a text search: both modules DESCRIBE the collection they
        used to read, at length and deliberately, and a grep cannot tell that
        prose from a call."""
        import ast
        for name in ("missing_detector", "deficiency"):
            tree = ast.parse((BACKEND / "lib" / "logbook" / f"{name}.py")
                             .read_text(encoding="utf-8"))
            hits = [
                f"{name}.py:{n.lineno}" for n in ast.walk(tree)
                if isinstance(n, ast.Attribute)
                and n.attr == "daily_logs"
                and isinstance(n.value, ast.Name) and n.value.id == "db"
            ]
            self.assertEqual(hits, [], f"{name} still touches db.daily_logs")

    def test_daily_logs_is_not_unioned_back_in(self):
        """On today's data it adds nothing, and it would carry April test rows
        into a compliance answer permanently."""
        self.assertNotIn("daily_logs", str(src.daily_jobsite_filter("p")))


class TheAdapterMapsTheShape(unittest.TestCase):
    def setUp(self):
        self.row = src.as_daily_log_row(FILED)

    def test_worker_count_sums_the_crews(self):
        self.assertEqual(self.row["worker_count"], 11)

    def test_work_performed_prefers_the_attested_sentence(self):
        self.assertEqual(self.row["work_performed"], "Framing and electrical rough-in.")

    def test_work_performed_falls_back_to_the_crews_own_words(self):
        no_desc = {**FILED, "data": {**FILED["data"], "general_description": ""}}
        row = src.as_daily_log_row(no_desc)
        self.assertIn("wall framing", row["work_performed"])
        self.assertIn("rough-in", row["work_performed"])

    def test_notes_come_from_the_observations(self):
        self.assertIn("Housekeeping", self.row["notes"])

    def test_weather_needs_no_translation(self):
        self.assertEqual(self.row["weather"], "Clear")
        self.assertEqual(self.row["weather_temp"], "68F")

    def test_the_crews_become_subcontractor_cards(self):
        names = sorted(c["company"] for c in self.row["subcontractor_cards"])
        self.assertEqual(names, ["Arkon Builders", "Power Direct"])

    def test_a_crew_with_no_company_is_not_a_subcontractor(self):
        blank = {**FILED, "data": {**FILED["data"],
                                   "activities": [{"company": "", "num_workers": 2}]}}
        self.assertEqual(src.as_daily_log_row(blank)["subcontractor_cards"], [])

    def test_an_empty_log_does_not_raise(self):
        row = src.as_daily_log_row({"date": "2026-05-04", "data": {}})
        self.assertEqual(row["worker_count"], 0)
        self.assertEqual(row["work_performed"], "")

    def test_the_adapted_row_satisfies_the_rules_it_feeds(self):
        """The rules are untouched by this change, so the proof the adapter
        works is that they return what they should on a real filed log."""
        self.assertIsNone(deficiency.rule_missing_manpower(self.row))
        self.assertIsNone(deficiency.rule_missing_weather(self.row))
        self.assertIsNone(deficiency.rule_missing_trade_work(self.row))

    def test_and_still_fire_on_a_log_that_is_missing_them(self):
        bare = src.as_daily_log_row({"date": "2026-05-04", "data": {}})
        self.assertIsNotNone(deficiency.rule_missing_manpower(bare))
        self.assertIsNotNone(deficiency.rule_missing_weather(bare))
        self.assertIsNotNone(deficiency.rule_missing_trade_work(bare))


def _db(filed_dates=(), manual_dates=()):
    db = MagicMock()
    db.logbooks = MagicMock()
    db.logbooks.find = MagicMock(return_value=_Cursor([
        {**FILED, "date": d} for d in filed_dates
    ]))
    db.logbook_entries = MagicMock()
    db.logbook_entries.find = MagicMock(return_value=_Cursor([
        {"entry_date": d} for d in manual_dates
    ]))
    db.logbook_entries.update_one = AsyncMock(
        return_value=MagicMock(matched_count=0, upserted_id="x"))
    return db


PROJECT = {"_id": "proj_a", "company_id": "co_a",
           "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc)}


class TheUnflagPath(unittest.TestCase):
    """The half that did not exist: a present day is recorded as present."""

    def _written(self, filed, manual=()):
        db = _db(filed_dates=filed, manual_dates=manual)
        return db, _run(missing_detector.detect_missing_for_project(
            db, project=PROJECT,
            start_date=date(2026, 5, 4), end_date=date(2026, 5, 8),
            now=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc),
        ))

    def test_a_filed_day_is_written_complete(self):
        _db_, written = self._written(["2026-05-04", "2026-05-06"])
        done = sorted(e["entry_date"] for e in written
                      if e["status"] == logbook_schema.STATUS_COMPLETE)
        self.assertEqual(done, ["2026-05-04", "2026-05-06"])

    def test_an_unfiled_day_is_still_missing(self):
        _db_, written = self._written(["2026-05-04", "2026-05-06"])
        gaps = sorted(e["entry_date"] for e in written
                      if e["status"] == logbook_schema.STATUS_MISSING)
        self.assertEqual(gaps, ["2026-05-05", "2026-05-07", "2026-05-08"])

    def test_a_week_of_filed_logs_produces_no_missing_row_at_all(self):
        """The 285 false flags, in one assertion."""
        _db_, written = self._written([
            "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"])
        self.assertEqual(
            [e for e in written if e["status"] == logbook_schema.STATUS_MISSING], [])

    def test_a_manual_row_is_not_overwritten(self):
        """`source` exists so a person's ruling outranks the detector's."""
        db, written = self._written([], manual=["2026-05-05"])
        touched = sorted(e["entry_date"] for e in written)
        self.assertNotIn("2026-05-05", touched)
        for call in db.logbook_entries.update_one.call_args_list:
            self.assertNotEqual(call[0][0].get("entry_date"), "2026-05-05")

    def test_the_upsert_key_is_still_the_unique_index(self):
        """A `source` clause in the FILTER would not match the manual row,
        upsert would try to insert a second one, and the unique index would
        reject it — a protection turned into a nightly duplicate-key error."""
        db, _written = self._written([])
        filter_arg = db.logbook_entries.update_one.call_args_list[0][0][0]
        self.assertEqual(sorted(filter_arg.keys()),
                         ["category", "entry_date", "project_id"])


class TheDeficiencyScannerHasSomethingToScan(unittest.TestCase):
    def test_it_scans_the_filed_logs(self):
        db = _db(filed_dates=["2026-05-04"])
        db.projects = MagicMock()
        db.projects.find = MagicMock(return_value=_Cursor([PROJECT]))
        db.subcontractors = MagicMock()
        db.subcontractors.find = MagicMock(return_value=_Cursor([]))
        summary = _run(deficiency.run_deficiency_detector_for_all_projects(
            db, now=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)))
        self.assertEqual(summary["logs_scanned"], 1)
        self.assertEqual(summary["errors"], 0)

    def test_a_complete_log_raises_no_deficiency(self):
        db = _db(filed_dates=["2026-05-04"])
        db.projects = MagicMock()
        db.projects.find = MagicMock(return_value=_Cursor([PROJECT]))
        db.subcontractors = MagicMock()
        db.subcontractors.find = MagicMock(return_value=_Cursor([]))
        summary = _run(deficiency.run_deficiency_detector_for_all_projects(
            db, now=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)))
        self.assertEqual(summary["deficiencies_written"], 0)


if __name__ == "__main__":
    unittest.main()
