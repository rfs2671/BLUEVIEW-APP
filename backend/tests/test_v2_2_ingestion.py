"""Phase V2.2 — Commit 2 ingestion engine tests.

Pin the contracts the ingestion engine promises:

  • DATASETS registry — 7 entries (6 event datasets + PLUTO).
  • Each dataset spec has the fields the backfill / weekly-delta
    code reads (collection, socrata_id, field_map, date_field).
  • Field mapping: a raw Socrata row converts cleanly to a
    canonical record; missing record_id → None.
  • PLUTO synthesizes record_id from bin (since PLUTO has no
    natural record_id field).
  • Datetime parsing handles common Socrata formats.
  • Upsert is idempotent — second call with same record_id
    doesn't insert a duplicate.
  • Backfill is resumable — `ingestion_state` tracks the
    `backfill_offset` so a crash mid-run picks up where it
    stopped.
  • Weekly delta uses a 7-day filter and skips PLUTO (snapshot,
    not event stream).
  • forward_to_v22 hook converts + upserts a single raw row.
  • server.py wires the weekly cron at Sunday 2 AM ET.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.statistical_engine import ingestion as ing  # noqa: E402
from lib.statistical_engine import schema as se_schema  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────────
# Dataset registry
# ──────────────────────────────────────────────────────────────────


class TestDatasetsRegistry(unittest.TestCase):

    def test_seven_datasets(self):
        # 6 BIN-keyed event datasets + PLUTO.
        self.assertEqual(len(ing.DATASETS), 7)

    def test_dob_violations_present(self):
        self.assertIn("dob_violations", ing.DATASETS)
        spec = ing.DATASETS["dob_violations"]
        self.assertEqual(spec["collection"],
                         se_schema.NYC_VIOLATIONS_COLLECTION)
        self.assertEqual(spec["socrata_id"], "3h2n-5cm9")
        self.assertEqual(spec["date_field"], "issue_date")

    def test_dob_inspections_present(self):
        self.assertIn("dob_inspections", ing.DATASETS)
        spec = ing.DATASETS["dob_inspections"]
        self.assertEqual(spec["collection"],
                         se_schema.NYC_INSPECTIONS_COLLECTION)

    def test_dob_permits_present(self):
        self.assertIn("dob_permits", ing.DATASETS)
        spec = ing.DATASETS["dob_permits"]
        self.assertEqual(spec["collection"],
                         se_schema.NYC_PERMITS_COLLECTION)

    def test_complaints_311_present(self):
        self.assertIn("complaints_311", ing.DATASETS)
        spec = ing.DATASETS["complaints_311"]
        self.assertEqual(spec["collection"],
                         se_schema.NYC_COMPLAINTS_311_COLLECTION)

    def test_ecb_violations_present(self):
        self.assertIn("ecb_violations", ing.DATASETS)
        spec = ing.DATASETS["ecb_violations"]
        self.assertEqual(spec["collection"],
                         se_schema.NYC_ECB_VIOLATIONS_COLLECTION)

    def test_hpd_violations_present(self):
        self.assertIn("hpd_violations", ing.DATASETS)
        spec = ing.DATASETS["hpd_violations"]
        self.assertEqual(spec["collection"],
                         se_schema.NYC_HPD_VIOLATIONS_COLLECTION)

    def test_pluto_present_and_no_date_field(self):
        self.assertIn("pluto", ing.DATASETS)
        spec = ing.DATASETS["pluto"]
        self.assertEqual(spec["collection"],
                         se_schema.NYC_PLUTO_COLLECTION)
        self.assertIsNone(spec["date_field"],
                          "PLUTO is a snapshot — no date_field")

    def test_every_event_dataset_has_record_id_in_field_map(self):
        # PLUTO doesn't (it synthesizes from bin); every other one
        # MUST have an explicit record_id mapping.
        for dataset, spec in ing.DATASETS.items():
            if dataset == "pluto":
                continue
            self.assertIn("record_id", spec["field_map"],
                          f"{dataset} missing record_id mapping")

    def test_constants_pinned(self):
        self.assertEqual(ing.BACKFILL_YEARS, 2)
        self.assertEqual(ing.WEEKLY_DELTA_DAYS, 7)
        self.assertEqual(ing.SOCRATA_PAGE_LIMIT, 5000)


# ──────────────────────────────────────────────────────────────────
# Field normalization
# ──────────────────────────────────────────────────────────────────


class TestCanonicalRecord(unittest.TestCase):

    def test_dob_violation_row_normalized(self):
        spec = ing.DATASETS["dob_violations"]
        raw = {
            "isn_dob_bis_viol": "VIOL_001",
            "bin": "1234567",
            "bbl": "1001234567",
            "boro": "M",
            "issue_date": "2026-04-15T00:00:00.000",
            "violation_type": "C",
            "description": "Failure to maintain",
            "disposition_comments": "open",
        }
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["record_id"], "VIOL_001")
        self.assertEqual(rec["bin"], "1234567")
        self.assertEqual(rec["bbl"], "1001234567")
        self.assertEqual(rec["borough"], "M")
        self.assertIsInstance(rec["occurred_date"], datetime)
        self.assertEqual(rec["dataset"], "dob_violations")
        self.assertIn("ingested_at", rec)

    def test_missing_record_id_returns_none(self):
        spec = ing.DATASETS["dob_violations"]
        raw = {"bin": "1234567", "issue_date": "2026-04-15"}
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNone(rec)

    def test_pluto_synthesizes_record_id_from_bin(self):
        spec = ing.DATASETS["pluto"]
        raw = {
            "bin": "1234567",
            "bbl": "1001234567",
            "borough": "MN",
            "bldgclass": "R6",
            "yearbuilt": "1985",
        }
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["record_id"], "pluto_1234567")
        self.assertEqual(rec["bin"], "1234567")

    def test_pluto_missing_bin_returns_none(self):
        spec = ing.DATASETS["pluto"]
        raw = {"borough": "MN", "bldgclass": "R6"}
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNone(rec)

    def test_complaints_311_normalized(self):
        spec = ing.DATASETS["complaints_311"]
        raw = {
            "unique_key": "311_42",
            "bin": "5555555",
            "bbl": "5005555555",
            "borough": "QUEENS",
            "created_date": "2026-05-01T12:00:00.000",
            "complaint_type": "Construction",
            "descriptor": "After Hours Work",
            "agency": "DOB",
            "status": "Open",
        }
        rec = ing._to_canonical_record(raw, spec)
        self.assertEqual(rec["record_id"], "311_42")
        self.assertEqual(rec["agency"], "DOB")
        self.assertEqual(rec["status"], "Open")


class TestDatetimeParsing(unittest.TestCase):

    def test_parses_iso_with_milliseconds(self):
        dt = ing._parse_socrata_datetime("2026-05-08T14:30:00.000")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 5)
        self.assertEqual(dt.day, 8)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parses_iso_with_z_suffix(self):
        dt = ing._parse_socrata_datetime("2026-05-08T14:30:00Z")
        self.assertIsNotNone(dt)

    def test_parses_date_only(self):
        dt = ing._parse_socrata_datetime("2026-05-08")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.day, 8)

    def test_returns_none_on_garbage(self):
        self.assertIsNone(ing._parse_socrata_datetime(""))
        self.assertIsNone(ing._parse_socrata_datetime(None))
        self.assertIsNone(ing._parse_socrata_datetime("not a date"))

    def test_passes_through_existing_datetime(self):
        existing = datetime(2026, 5, 8, tzinfo=timezone.utc)
        self.assertEqual(ing._parse_socrata_datetime(existing), existing)


# ──────────────────────────────────────────────────────────────────
# Upsert idempotency
# ──────────────────────────────────────────────────────────────────


class _StubCollection:
    """Mimics the motor collection update_one + insert_one API
    well enough to test the idempotency contract."""

    def __init__(self):
        self.records: dict = {}
        self.update_one_calls = 0

    async def update_one(self, filter_, update, upsert=False):
        self.update_one_calls += 1
        rid = filter_.get("record_id")
        was_present = rid in self.records
        # Apply the $set + $setOnInsert merge.
        new_doc = dict(self.records.get(rid, {}))
        if "$set" in update:
            new_doc.update(update["$set"])
        if "$setOnInsert" in update and not was_present:
            new_doc.update(update["$setOnInsert"])
        self.records[rid] = new_doc
        result = MagicMock()
        result.upserted_id = None if was_present else rid
        result.matched_count = 1 if was_present else 0
        result.modified_count = 1 if was_present else 0
        return result


class _StubDb:
    """Mimics motor.database for collection access via __getitem__."""

    def __init__(self):
        self._collections: dict = {}
        # State collection used by ingestion-state cursor.
        self.ingestion_state_records: list = []

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _StubCollection()
        return self._collections[name]


class TestUpsertIdempotency(unittest.TestCase):

    def test_first_upsert_is_new(self):
        db = _StubDb()
        rec = {"record_id": "R1", "bin": "1234567"}
        new = _run(ing.upsert_record(db, "nyc_violations", rec))
        self.assertTrue(new)

    def test_second_upsert_same_id_is_noop(self):
        db = _StubDb()
        rec = {"record_id": "R1", "bin": "1234567"}
        _run(ing.upsert_record(db, "nyc_violations", rec))
        again = _run(ing.upsert_record(db, "nyc_violations", rec))
        self.assertFalse(again, "second upsert must report no-op")

    def test_missing_record_id_skipped(self):
        db = _StubDb()
        rec = {"bin": "1234567"}
        result = _run(ing.upsert_record(db, "nyc_violations", rec))
        self.assertFalse(result)


# ──────────────────────────────────────────────────────────────────
# Ingestion-state cursor (resumability)
# ──────────────────────────────────────────────────────────────────


class _StateOnlyDb:
    """Tiny stub for the ingestion_state path only — pretends to
    store one doc per dataset and supports find_one + update_one
    upsert."""

    def __init__(self):
        self.docs: dict = {}

    def __getitem__(self, name):
        if name != se_schema.INGESTION_STATE_COLLECTION:
            raise KeyError(name)
        outer = self

        class _Coll:
            async def find_one(_self, q):
                return outer.docs.get(q.get("dataset"))

            async def update_one(_self, q, update, upsert=False):
                ds = q.get("dataset")
                doc = outer.docs.get(ds, {"dataset": ds})
                if "$set" in update:
                    doc.update(update["$set"])
                outer.docs[ds] = doc
                r = MagicMock()
                r.upserted_id = ds if upsert and ds not in outer.docs else None
                return r

        return _Coll()


class TestIngestionState(unittest.TestCase):

    def test_get_returns_empty_doc_when_missing(self):
        db = _StateOnlyDb()
        doc = _run(ing.get_ingestion_state(db, "dob_violations"))
        self.assertEqual(doc.get("dataset"), "dob_violations")

    def test_set_and_get_round_trip(self):
        db = _StateOnlyDb()
        _run(ing.set_ingestion_state(
            db, "dob_violations",
            backfill_offset=1500,
            backfill_finished=False,
        ))
        doc = _run(ing.get_ingestion_state(db, "dob_violations"))
        self.assertEqual(doc["backfill_offset"], 1500)
        self.assertFalse(doc["backfill_finished"])
        self.assertIn("updated_at", doc)


# ──────────────────────────────────────────────────────────────────
# Backfill orchestrator (with a stub HTTP client)
# ──────────────────────────────────────────────────────────────────


class _StubHttpClient:
    """Mimics ServerHttpClient — ServerHttpClient supports `async
    with`, .get(url, params=...). We feed it a list-of-pages and
    each .get pops the next page."""

    def __init__(self, pages):
        # pages: list of list-of-rows (raw Socrata shape).
        self._pages = list(pages)
        self.get_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a, **k):
        return None

    async def get(self, url, params=None):
        self.get_calls += 1
        page = self._pages.pop(0) if self._pages else []
        r = MagicMock()
        r.status_code = 200
        r.json = lambda: page
        r.headers = {}
        return r


class _BackfillDb(_StateOnlyDb):
    """State + per-collection upsert tracking."""

    def __init__(self):
        super().__init__()
        self._colls: dict = {}

    def __getitem__(self, name):
        if name == se_schema.INGESTION_STATE_COLLECTION:
            return super().__getitem__(name)
        if name not in self._colls:
            self._colls[name] = _StubCollection()
        return self._colls[name]


class TestBackfillResumability(unittest.TestCase):

    def test_records_offset_after_each_page(self):
        # Two-page fixture, then an empty terminator.
        pages = [
            [
                {"isn_dob_bis_viol": f"V{i}", "bin": "1234567",
                 "bbl": "1001234567", "boro": "M",
                 "issue_date": "2026-04-15"}
                for i in range(3)
            ],
            [
                {"isn_dob_bis_viol": f"V{i}", "bin": "1234567",
                 "bbl": "1001234567", "boro": "M",
                 "issue_date": "2026-04-16"}
                for i in range(3, 5)
            ],
        ]
        db = _BackfillDb()
        client = _StubHttpClient(pages)
        # page_limit=3 matches page 1 exactly (no short-circuit on
        # page 1) and is larger than page 2 (short-circuit triggers
        # after page 2). Both pages drain → 5 rows seen.
        summary = _run(ing.backfill_dataset(
            db, "dob_violations",
            page_limit=3,
            http_client=client,
            max_pages=10,
        ))
        self.assertEqual(summary["rows_seen"], 5)
        self.assertEqual(summary["rows_upserted"], 5)
        # Offset advanced.
        state = db.docs.get("dob_violations", {})
        self.assertEqual(state.get("backfill_offset"), 5)

    def test_resumes_from_existing_offset(self):
        # Pre-seed state with offset=10 so backfill resumes from
        # there rather than 0.
        db = _BackfillDb()
        db.docs["dob_violations"] = {
            "dataset": "dob_violations",
            "backfill_offset": 10,
            "backfill_finished": False,
        }
        # No new pages — verify the call stack gets to the
        # request site with the correct offset.
        client = _StubHttpClient([])  # immediately empty
        _run(ing.backfill_dataset(
            db, "dob_violations",
            page_limit=10,
            http_client=client,
            max_pages=1,
        ))
        # If we'd reset to 0, that would be the surprise. State
        # offset must remain at 10 because no new data came in.
        state = db.docs.get("dob_violations", {})
        self.assertEqual(state.get("backfill_offset"), 10)

    def test_short_page_marks_finished(self):
        # One page with fewer rows than page_limit triggers
        # finished=True.
        pages = [
            [
                {"isn_dob_bis_viol": "V1", "bin": "1234567",
                 "bbl": "1001234567", "boro": "M",
                 "issue_date": "2026-04-15"}
            ],
        ]
        db = _BackfillDb()
        client = _StubHttpClient(pages)
        summary = _run(ing.backfill_dataset(
            db, "dob_violations",
            page_limit=100,
            http_client=client,
            max_pages=10,
        ))
        # rows_seen < pages * page_limit  →  finished = True.
        self.assertTrue(summary["finished"])


# ──────────────────────────────────────────────────────────────────
# Weekly delta
# ──────────────────────────────────────────────────────────────────


class TestWeeklyDelta(unittest.TestCase):

    def test_pluto_skipped(self):
        # PLUTO has no date_field — weekly delta is a no-op.
        db = _BackfillDb()
        client = _StubHttpClient([])
        summary = _run(ing.weekly_delta_dataset(
            db, "pluto",
            http_client=client,
        ))
        self.assertIn("skipped", summary)

    def test_event_dataset_processes_one_window(self):
        pages = [
            [
                {"isn_dob_bis_viol": "DELTA1", "bin": "1234567",
                 "bbl": "1001234567", "boro": "M",
                 "issue_date": "2026-05-05"}
            ],
        ]
        db = _BackfillDb()
        client = _StubHttpClient(pages)
        summary = _run(ing.weekly_delta_dataset(
            db, "dob_violations",
            page_limit=100,
            http_client=client,
        ))
        self.assertEqual(summary["rows_seen"], 1)
        self.assertEqual(summary["rows_upserted"], 1)


# ──────────────────────────────────────────────────────────────────
# forward_to_v22 hook
# ──────────────────────────────────────────────────────────────────


class TestForwardToV22(unittest.TestCase):

    def test_forwards_violation_record(self):
        db = _BackfillDb()
        raw = {
            "isn_dob_bis_viol": "FW1", "bin": "9999999",
            "bbl": "1009999999", "boro": "M",
            "issue_date": "2026-05-08",
        }
        ok = _run(ing.forward_to_v22(db, "dob_violations", raw))
        self.assertTrue(ok)

    def test_forwards_311_record(self):
        db = _BackfillDb()
        raw = {
            "unique_key": "FW311", "bin": "9999999",
            "bbl": "1009999999", "borough": "MANHATTAN",
            "created_date": "2026-05-08",
            "complaint_type": "Construction",
        }
        ok = _run(ing.forward_to_v22(db, "complaints_311", raw))
        self.assertTrue(ok)

    def test_unknown_dataset_returns_false(self):
        db = _BackfillDb()
        ok = _run(ing.forward_to_v22(db, "not_a_dataset", {}))
        self.assertFalse(ok)


# ──────────────────────────────────────────────────────────────────
# server.py weekly cron wiring
# ──────────────────────────────────────────────────────────────────


class TestServerCronWiring(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_weekly_ingest_tick_registered(self):
        self.assertIn("v2_2_weekly_ingest", self.text)

    def test_cron_at_sunday_2am_et(self):
        # Sunday 2 AM ET = day_of_week='sun' hour=2 minute=0
        # America/New_York. The CronTrigger spec is one literal
        # block — pin it.
        self.assertIn(
            "day_of_week='sun', hour=2, minute=0,\n"
            "            timezone=\"America/New_York\"",
            self.text,
        )

    def test_tick_calls_weekly_delta_all_datasets(self):
        # Locate the tick coroutine and assert the payload.
        s = self.text.find("async def _v22_weekly_ingest_tick")
        self.assertGreater(s, 0)
        e = self.text.find("scheduler.add_job", s)
        slice_ = self.text[s:e]
        self.assertIn("weekly_delta_all_datasets", slice_)


# ──────────────────────────────────────────────────────────────────
# Package re-exports for Commit 2
# ──────────────────────────────────────────────────────────────────


class TestPackageReExportsCommit2(unittest.TestCase):

    def test_ingestion_api_reexported(self):
        from lib import statistical_engine as stat_engine
        self.assertTrue(hasattr(stat_engine, "DATASETS"))
        self.assertTrue(hasattr(stat_engine, "BACKFILL_YEARS"))
        self.assertTrue(hasattr(stat_engine, "weekly_delta_all_datasets"))
        self.assertTrue(hasattr(stat_engine, "backfill_all_datasets"))
        self.assertTrue(hasattr(stat_engine, "forward_to_v22"))


if __name__ == "__main__":
    unittest.main()
