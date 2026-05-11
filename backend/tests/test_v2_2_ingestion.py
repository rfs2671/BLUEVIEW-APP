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
        # V2.2.4 Path A: dob_violations field_map now uses
        # `__derive_bbl__` sentinel — bbl is reconstructed from
        # boro/block/lot at canonicalization time because the
        # Socrata 3h2n-5cm9 dataset has no bbl column. Fixture
        # mirrors a real Socrata row shape (verified by curl
        # probe — see commit message).
        spec = ing.DATASETS["dob_violations"]
        raw = {
            "isn_dob_bis_viol": "VIOL_001",
            "bin": "1234567",
            "boro": "1",
            "block": "00847",
            "lot": "00038",
            "issue_date": "2026-04-15T00:00:00.000",
            "violation_type": "C",
            "description": "Failure to maintain",
            "disposition_comments": "open",
        }
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["record_id"], "VIOL_001")
        self.assertEqual(rec["bin"], "1234567")
        # Derived from boro/block/lot via canonical NYC BBL formula
        # (1 + block.zfill(5) + lot.zfill(4) → 10 chars).
        self.assertEqual(rec["bbl"], "1008470038")
        self.assertEqual(rec["borough"], "1")
        self.assertIsInstance(rec["occurred_date"], datetime)
        self.assertEqual(rec["dataset"], "dob_violations")
        self.assertIn("ingested_at", rec)
    def test_missing_record_id_returns_none(self):
        spec = ing.DATASETS["dob_violations"]
        raw = {"bin": "1234567", "issue_date": "2026-04-15"}
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNone(rec)

    def test_pluto_synthesizes_record_id_from_bbl(self):
        """V2.2.3: PLUTO is BBL-keyed (natural_key='bbl'). The
        Socrata 64uk-42ks dataset has no `bin` column, so the
        V2.2.2 attempt to fall back from bin→bbl was an implicit
        contract; V2.2.3 makes it explicit via `natural_key`."""
        spec = ing.DATASETS["pluto"]
        raw = {
            "bbl": "1001234567",
            "borough": "MN",
            "bldgclass": "R6",
            "yearbuilt": "1985",
        }
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["record_id"], "pluto_1001234567")
        self.assertEqual(rec["bbl"], "1001234567")

    def test_pluto_strips_bbl_decimal_suffix(self):
        """V2.2.3: PLUTO's Socrata payload returns BBL with a
        `.00000000` decimal suffix on every row. Strip it so
        record_id matches the BBL format used elsewhere."""
        spec = ing.DATASETS["pluto"]
        raw = {
            "bbl": "4061730023.00000000",
            "borough": "QN",
        }
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNotNone(rec)
        self.assertEqual(
            rec["record_id"], "pluto_4061730023",
            "PLUTO record_id must use the integer-string BBL form, "
            "not the .00000000 decimal-suffix form Socrata returns",
        )

    def test_pluto_missing_natural_key_returns_none(self):
        """When the natural_key field (bbl) is absent or empty,
        canonicalization drops the row. Used to be named
        `test_pluto_missing_bin_returns_none` pre-V2.2.3."""
        spec = ing.DATASETS["pluto"]
        raw = {"borough": "MN", "bldgclass": "R6"}  # no bbl
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


class TestConstructBblFromComponents(unittest.TestCase):
    """V2.2.4 Path A: dob_violations BBL is derived from
    boro/block/lot since Socrata 3h2n-5cm9 has no top-level bbl
    column. The cases below pin every padding shape and
    invalid-input branch the helper must handle.
    """

    def test_under_padded_normal_case(self):
        # Hypothetical row that wasn't over-padded by Socrata.
        rec = ing._construct_bbl_from_components(
            {"boro": "1", "block": "847", "lot": "38"},
        )
        self.assertEqual(rec, "1008470038")
        self.assertEqual(len(rec), 10)

    def test_socrata_row_2_actual_padding(self):
        # Verbatim shape from Socrata 3h2n-5cm9 row 2 (curl
        # probe 2026-05-10). Both block and lot zero-padded to
        # 5 chars; lot's 5th char is the over-pad we strip.
        rec = ing._construct_bbl_from_components(
            {"boro": "1", "block": "00847", "lot": "00038"},
        )
        self.assertEqual(rec, "1008470038")
        self.assertEqual(len(rec), 10)

    def test_further_over_padded(self):
        # Hypothetical 6-char inputs. lstrip + zfill normalizes
        # to canonical width without producing 11+ char BBLs.
        rec = ing._construct_bbl_from_components(
            {"boro": "1", "block": "000847", "lot": "000038"},
        )
        self.assertEqual(rec, "1008470038")
        self.assertEqual(len(rec), 10)

    def test_all_zeros_returns_none(self):
        # block=0 and lot=0 are semantically invalid (no real
        # NYC tax lot has block 0 OR lot 0). Pre-patch the
        # helper produced "1000000000" which is a fake-but-real-
        # looking 10-char BBL — that would falsely collapse every
        # invalid row onto the same record_id. Post-patch the
        # lstrip+zfill pattern strips both components to "" then
        # rejects.
        rec = ing._construct_bbl_from_components(
            {"boro": "1", "block": "0", "lot": "00"},
        )
        self.assertIsNone(rec)

    def test_invalid_boro_returns_none(self):
        # NYC boroughs are 1-5 only. Anything else is a data
        # error or a misclassified borough column.
        rec = ing._construct_bbl_from_components(
            {"boro": "6", "block": "847", "lot": "38"},
        )
        self.assertIsNone(rec)

    def test_non_numeric_components_return_none(self):
        # Defensive: Socrata occasionally serves text values in
        # numeric-typed columns. The helper rejects.
        self.assertIsNone(ing._construct_bbl_from_components(
            {"boro": "MANHATTAN", "block": "847", "lot": "38"},
        ))
        self.assertIsNone(ing._construct_bbl_from_components(
            {"boro": "1", "block": "ABC", "lot": "38"},
        ))
        self.assertIsNone(ing._construct_bbl_from_components(
            {"boro": "1", "block": "847", "lot": "X"},
        ))

    def test_missing_component_returns_none(self):
        self.assertIsNone(ing._construct_bbl_from_components(
            {"boro": "1", "block": "847"},  # no lot
        ))
        self.assertIsNone(ing._construct_bbl_from_components(
            {"block": "847", "lot": "38"},  # no boro
        ))
        self.assertIsNone(ing._construct_bbl_from_components({}))

    def test_block_too_large_returns_none(self):
        # Block can't exceed 5 significant digits.
        self.assertIsNone(ing._construct_bbl_from_components(
            {"boro": "1", "block": "100000", "lot": "38"},
        ))

    def test_lot_too_large_returns_none(self):
        # Lot can't exceed 4 significant digits.
        self.assertIsNone(ing._construct_bbl_from_components(
            {"boro": "1", "block": "847", "lot": "10000"},
        ))


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
    """Mimics ServerHttpClient — supports `async with` and
    `.get(url, params=...)`. We feed it a list-of-pages and each
    `.get` pops the next page.

    For V2.2.2 BUG 3 regression coverage, list entries can be
    either:
      • a list of rows  → returned as a 200 with that body
      • a tuple ``(status_code, body)`` → returned with that
        status (e.g. ``(400, [])`` to reproduce the
        dob_inspections wrong-dataset bug)
    """

    def __init__(self, pages):
        self._pages = list(pages)
        self.get_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a, **k):
        return None

    async def get(self, url, params=None):
        self.get_calls += 1
        if not self._pages:
            r = MagicMock()
            r.status_code = 200
            r.json = lambda: []
            r.headers = {}
            return r
        nxt = self._pages.pop(0)
        if isinstance(nxt, tuple) and len(nxt) == 2:
            status, body = nxt
            r = MagicMock()
            r.status_code = status
            r.json = lambda body=body: body
            r.headers = {}
            return r
        # Plain list → 200.
        r = MagicMock()
        r.status_code = 200
        r.json = lambda body=nxt: body
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

    def test_first_page_full_then_partial_marks_finished(self):
        """V2.2.2 BUG 3 positive regression: the new finished
        gate requires evidence of a full page (>= page_limit)
        before a partial page is allowed to mark the dataset
        finished. Replaces the pre-V2.2.2
        ``test_short_page_marks_finished`` whose single-short-
        page fixture encoded the buggy gate."""
        pages = [
            # Page 1: exactly page_limit rows → had_full_page=True.
            [
                {"isn_dob_bis_viol": f"V_full_{i}", "bin": "1234567",
                 "bbl": "1001234567", "boro": "M",
                 "issue_date": "2026-04-15"}
                for i in range(3)
            ],
            # Page 2: short (< page_limit) → natural exhaustion.
            [
                {"isn_dob_bis_viol": "V_short_1", "bin": "1234567",
                 "bbl": "1001234567", "boro": "M",
                 "issue_date": "2026-04-16"},
            ],
        ]
        db = _BackfillDb()
        client = _StubHttpClient(pages)
        summary = _run(ing.backfill_dataset(
            db, "dob_violations",
            page_limit=3,
            http_client=client,
            max_pages=10,
        ))
        self.assertTrue(
            summary["finished"],
            f"finished should be True after full→partial: {summary}",
        )
        self.assertEqual(summary["errors"], 0)
        # had_full_page persisted in ingestion_state for the
        # next-run-resume scenario.
        state = db.docs.get("dob_violations", {})
        self.assertTrue(state.get("had_full_page"))


# ──────────────────────────────────────────────────────────────────
# V2.2.2 BUG 3 — finished gating must reject error / zero-row pages
# ──────────────────────────────────────────────────────────────────


class TestBackfillFinishedGate(unittest.TestCase):
    """Pre-V2.2.2 the backfill marked a dataset finished=True any
    time a page returned < page_limit rows — including a 400-error
    page (which made the wrong-dataset BUG 1 self-camouflaging)
    and a clean-200-empty-page (which made the wrong-WHERE-column
    BUG 2 self-camouflaging). The new gate requires zero errors
    AND a prior full page AND a partial last page."""

    def test_400_response_does_not_mark_finished(self):
        """Reproducer for BUG 1: a 400 response on page 1 must
        leave the dataset NOT finished, errors > 0, and the
        cursor untouched at offset 0."""
        db = _BackfillDb()
        # Single page result: a 400 with empty body.
        client = _StubHttpClient([(400, [])])
        summary = _run(ing.backfill_dataset(
            db, "dob_inspections",
            page_limit=100,
            http_client=client,
            max_pages=10,
        ))
        self.assertFalse(
            summary["finished"],
            f"a 400 page must NOT mark finished: {summary}",
        )
        self.assertGreater(
            summary["errors"], 0,
            "a 400 page must increment errors so the operator "
            "can see the failure in the response body",
        )
        # Cursor untouched: the next operator-triggered run will
        # re-attempt the same page.
        state = db.docs.get("dob_inspections", {})
        self.assertEqual(
            int(state.get("backfill_offset", 0) or 0), 0,
            "cursor must NOT advance past a 400 page",
        )

    def test_zero_rows_first_page_does_not_mark_finished(self):
        """Reproducer for BUG 2: a 200 OK with an empty body on
        page 1 (the wrong-WHERE-column case) must leave the
        dataset NOT finished — zero rows on page 1 with no error
        is a strong schema-mismatch signal."""
        db = _BackfillDb()
        # Single page: 200 OK, empty body.
        client = _StubHttpClient([[]])
        summary = _run(ing.backfill_dataset(
            db, "dob_permits",
            page_limit=100,
            http_client=client,
            max_pages=10,
        ))
        self.assertFalse(
            summary["finished"],
            f"page 1 returning 0 rows must NOT mark finished: {summary}",
        )
        # Cursor untouched.
        state = db.docs.get("dob_permits", {})
        self.assertEqual(
            int(state.get("backfill_offset", 0) or 0), 0,
            "cursor must NOT advance past a zero-rows page 1",
        )


# ──────────────────────────────────────────────────────────────────
# V2.2.2 BUG 4 — silent row-drop visibility
# ──────────────────────────────────────────────────────────────────


class TestPlutoUpsertKeyMismatch(unittest.TestCase):
    """Pre-V2.2.2 PLUTO returned 5000 rows from Socrata that all
    silently produced 0 upserts because _to_canonical_record
    returned None on every row (the actual Socrata field name
    differed from what the field_map expected). errors=0 in the
    response made the operator think the run was clean. V2.2.2
    counts each canonicalization-drop as an error and emits an
    ERROR-level log with one truncated example payload."""

    def test_pluto_upsert_key_mismatch_logs_error(self):
        # Mock Socrata returns 5 rows whose key field is `BBL`
        # (uppercase) instead of `bbl` / `bin`. After the V2.2.2
        # fix, _to_canonical_record falls back from bin to bbl;
        # since neither lowercase field is present, the row drops
        # AND the loop counts an error AND logs an ERROR.
        rows = [
            {"BBL": f"100000000{i}", "BORO": "MN", "BLDGCLASS": "R6"}
            for i in range(5)
        ]
        db = _BackfillDb()
        client = _StubHttpClient([rows])
        # Capture log output from the ingestion logger to verify
        # the ERROR log fires with the expected dropped-row
        # diagnostic shape.
        import logging
        log_records: list = []
        handler = logging.Handler()
        handler.emit = lambda r: log_records.append(r)
        ing_logger = logging.getLogger("lib.statistical_engine.ingestion")
        ing_logger.addHandler(handler)
        prev_level = ing_logger.level
        ing_logger.setLevel(logging.DEBUG)
        try:
            summary = _run(ing.backfill_dataset(
                db, "pluto",
                page_limit=100,
                http_client=client,
                max_pages=10,
            ))
        finally:
            ing_logger.removeHandler(handler)
            ing_logger.setLevel(prev_level)

        # Each of the 5 rows was dropped at canonicalization;
        # errors must reflect that count.
        self.assertEqual(
            summary["rows_seen"], 5,
            f"all 5 rows should have been seen: {summary}",
        )
        self.assertEqual(
            summary["rows_upserted"], 0,
            f"no rows should have been upserted: {summary}",
        )
        self.assertGreaterEqual(
            summary["errors"], 5,
            f"each dropped row should count as an error: {summary}",
        )
        # And the ERROR log fired at least once with a dropped-
        # row example payload, with the dataset name embedded.
        error_lines = [
            r for r in log_records
            if r.levelno >= logging.ERROR
            and "dropped row" in r.getMessage()
            and "dataset=pluto" in r.getMessage()
        ]
        self.assertGreaterEqual(
            len(error_lines), 1,
            "expected at least one ERROR log with a dropped-row "
            "example payload from the pluto dataset",
        )


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


# ──────────────────────────────────────────────────────────────────
# V2.2.3 — field_map rebuilds from real Socrata payloads + unified
# drop-tracking. Each test name starts with "test_v22_3_" so a
# future audit can grep them out together.
# ──────────────────────────────────────────────────────────────────


class TestV22_3_DobInspectionsFieldMap(unittest.TestCase):
    """V2.2.2 fixed the dataset id (ic3t-wcy2 → p937-wjvj) but
    left the field_map referencing ic3t-wcy2's column names.
    p937-wjvj's actual columns (verified by curl):
      • bin (lowercase, NOT bin_number)
      • job_ticket_or_work_order_id (NOT id) for record_id
      • inspection_date is properly-typed; ISO comparator works
    """

    def test_v22_3_field_map_uses_real_p937wjvj_columns(self):
        spec = ing.DATASETS["dob_inspections"]
        fm = spec["field_map"]
        # The two columns that were wrong post-V2.2.2.
        self.assertEqual(fm["bin"], "bin")
        self.assertEqual(
            fm["record_id"], "job_ticket_or_work_order_id",
        )
        # And the date_field stays inspection_date (correct).
        self.assertEqual(spec["date_field"], "inspection_date")

    def test_v22_3_canonicalizes_real_p937wjvj_row(self):
        """Feed a row shaped like what p937-wjvj actually returns
        (sampled via curl 2026-05-09). Pre-V2.2.3 this row would
        drop with reason='missing_record_id' because the field_map
        looked for `id` (which doesn't exist). After V2.2.3 it
        canonicalizes cleanly."""
        spec = ing.DATASETS["dob_inspections"]
        # This raw shape was captured from
        # https://data.cityofnewyork.us/resource/p937-wjvj.json
        raw = {
            "inspection_type": "Initial",
            "job_ticket_or_work_order_id": "11670593",
            "job_id": "PC6530234",
            "bbl": "2032890025",
            "bin": "2016678",
            "borough": "Bronx",
            "inspection_date": "2010-08-30T15:23:11.000",
            "result": "Passed",
        }
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["record_id"], "11670593")
        self.assertEqual(rec["bin"], "2016678")
        self.assertEqual(rec["bbl"], "2032890025")
        self.assertEqual(rec["result"], "Passed")
        self.assertEqual(rec["job_id"], "PC6530234")


class TestV22_3_DobPermitsWhereField(unittest.TestCase):
    """V2.2.2 set date_field='filing_date' for ipu4-2q9a — but
    filing_date is a TEXT column with mixed MM/DD/YYYY +
    YYYY-MM-DD values that doesn't accept ISO comparators.
    V2.2.3 routes WHERE/ORDER through Socrata's typed system
    column `:updated_at` via the new `where_field` attribute."""

    def test_v22_3_dob_permits_uses_updated_at_for_where(self):
        spec = ing.DATASETS["dob_permits"]
        self.assertEqual(spec.get("where_field"), ":updated_at")
        # date_field stays filing_date so canonical occurred_date
        # extraction still uses the user-meaningful column.
        self.assertEqual(spec["date_field"], "filing_date")

    def test_v22_3_no_issuance_date_in_dob_permits_config(self):
        """Audit pin per the spec: 'grep the codebase for
        "issuance_date" — should be zero hits in V2.2 ingestion
        config after V2.2.3'. The dataset spec must not reference
        issuance_date anywhere — that column produces 0 rows on
        ISO WHERE due to the string-comparison gotcha."""
        spec = ing.DATASETS["dob_permits"]
        # date_field
        self.assertNotEqual(spec.get("date_field"), "issuance_date")
        # where_field
        self.assertNotEqual(spec.get("where_field"), "issuance_date")
        # field_map: any source pointing at issuance_date?
        for canonical, source in spec["field_map"].items():
            self.assertNotEqual(
                source, "issuance_date",
                f"{canonical} field maps to issuance_date — "
                f"replace with filing_date",
            )

    def test_v22_3_backfill_uses_where_field_when_present(self):
        """End-to-end: backfill_dataset on dob_permits should
        send a WHERE clause built from `:updated_at`, NOT from
        `filing_date`. We verify this by inspecting the params
        the stub HTTP client receives."""
        captured: list = []

        class _CapturingClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a, **k): return None
            async def get(self, url, params=None):
                captured.append({"url": url, "params": dict(params or {})})
                r = MagicMock()
                r.status_code = 200
                r.json = lambda: []
                r.headers = {}
                return r

        db = _BackfillDb()
        client = _CapturingClient()
        _run(ing.backfill_dataset(
            db, "dob_permits",
            page_limit=100,
            http_client=client,
            max_pages=1,
        ))
        self.assertGreater(len(captured), 0, "backfill should issue at least one HTTP request")
        params = captured[0]["params"]
        where = params.get("$where", "")
        self.assertIn(":updated_at", where,
                      f"WHERE should use :updated_at, got: {where!r}")
        self.assertNotIn("filing_date", where)
        self.assertNotIn("issuance_date", where)


class TestV22_3_PlutoBblNormalization(unittest.TestCase):
    """V2.2.3 strips PLUTO's `.00000000` decimal suffix from BBL
    so record_id matches the BBL format used elsewhere in the
    codebase (e.g. `4061730023`, not `4061730023.00000000`)."""

    def test_v22_3_normalize_natural_key_strips_decimal_zero(self):
        # Direct call to the normalizer.
        self.assertEqual(
            ing._normalize_natural_key("4061730023.00000000"),
            "4061730023",
        )
        # Already-clean BBL passes through.
        self.assertEqual(
            ing._normalize_natural_key("4061730023"),
            "4061730023",
        )
        # Empty / None.
        self.assertIsNone(ing._normalize_natural_key(None))
        self.assertIsNone(ing._normalize_natural_key(""))
        # Non-zero decimal — pass through (don't munge legit floats).
        self.assertEqual(
            ing._normalize_natural_key("3.5"),
            "3.5",
        )

    def test_v22_3_pluto_real_socrata_row_canonicalizes(self):
        """Feed a row shaped like what 64uk-42ks actually
        returns (sampled via curl 2026-05-09). Verifies the
        full integration: `bin` column absent, BBL with decimal
        suffix, record_id strips the suffix."""
        spec = ing.DATASETS["pluto"]
        raw = {
            # Captured from
            # https://data.cityofnewyork.us/resource/64uk-42ks.json?$limit=1
            "borough": "QN",
            "block": "6173",
            "lot": "23",
            "address": "214-10 35 AVENUE",
            "bldgclass": "A5",
            "landuse": "1",
            "lotarea": "2660",
            "bldgarea": "1224",
            "yearbuilt": "1950",
            "numfloors": "2.0000000",
            "bbl": "4061730023.00000000",
            "ownername": "LIU, RUI TANG",
            "zipcode": "11361",
            # Note: NO `bin` column — confirmed via curl.
        }
        rec = ing._to_canonical_record(raw, spec)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["record_id"], "pluto_4061730023")
        self.assertEqual(rec["bbl"], "4061730023.00000000")
        self.assertEqual(rec["address"], "214-10 35 AVENUE")
        self.assertEqual(rec["bldgclass"], "A5")


class TestV22_3_CanonicalizeWithReason(unittest.TestCase):
    """The new (record, drop_reason) two-step canonicalizer is
    the foundation for V2.2.3 BUG 7 Part B. Pin the reason
    strings so a future refactor doesn't silently rename them
    (drop-reason logs in production are operator-facing)."""

    def test_v22_3_canonicalize_with_reason_returns_record_on_success(self):
        spec = ing.DATASETS["dob_violations"]
        raw = {
            "isn_dob_bis_viol": "VIOL_OK",
            "bin": "1234567", "bbl": "1001234567", "boro": "M",
            "issue_date": "2026-04-15",
        }
        rec, reason = ing._canonicalize_with_reason(raw, spec)
        self.assertIsNotNone(rec)
        self.assertIsNone(reason)

    def test_v22_3_missing_record_id_reason_pinned(self):
        spec = ing.DATASETS["dob_violations"]
        raw = {"bin": "1234567"}  # no isn_dob_bis_viol
        rec, reason = ing._canonicalize_with_reason(raw, spec)
        self.assertIsNone(rec)
        self.assertEqual(reason, "missing_record_id")

    def test_v22_3_missing_natural_key_reason_pinned(self):
        spec = ing.DATASETS["pluto"]
        raw = {"borough": "MN"}  # no bbl (and no bin column on PLUTO)
        rec, reason = ing._canonicalize_with_reason(raw, spec)
        self.assertIsNone(rec)
        self.assertEqual(reason, "missing_natural_key:bbl")


class TestV22_3_DropTrackingUnified(unittest.TestCase):
    """V2.2.3 BUG 7 Part B regression test: the drop-tracking
    contract must hold for every canonicalization-failure path,
    NOT just the V2.2.2 outer-loop case. Spec test:
      'feeds a dataset 10 rows where 7 fail canonicalization
       and 3 succeed; assert errors == 7, rows_upserted == 3.'
    """

    def test_v22_3_canonicalization_drop_increments_errors(self):
        # 10 dob_violations rows. 3 valid, 7 missing record_id
        # (i.e. canonicalization will return None with reason
        # missing_record_id).
        valid_rows = [
            {"isn_dob_bis_viol": f"OK_{i}", "bin": "1234567",
             "bbl": "1001234567", "boro": "M",
             "issue_date": "2026-04-15"}
            for i in range(3)
        ]
        invalid_rows = [
            {"bin": f"BAD_{i}", "bbl": "1001234567", "boro": "M",
             "issue_date": "2026-04-15"}  # no isn_dob_bis_viol
            for i in range(7)
        ]
        page = valid_rows + invalid_rows

        db = _BackfillDb()
        client = _StubHttpClient([page])
        summary = _run(ing.backfill_dataset(
            db, "dob_violations",
            page_limit=10,
            http_client=client,
            max_pages=1,
        ))
        self.assertEqual(summary["rows_seen"], 10)
        self.assertEqual(summary["rows_upserted"], 3)
        self.assertEqual(
            summary["errors"], 7,
            f"every canonicalization-drop must increment errors: {summary}",
        )

    def test_v22_3_dropped_row_log_includes_drop_reason(self):
        """Pin: the dropped-row ERROR log must include the
        specific drop reason string (e.g. 'missing_record_id'),
        not just 'canonicalization returned None' as in V2.2.2."""
        page = [
            {"bin": "1234567", "bbl": "1001234567", "boro": "M",
             "issue_date": "2026-04-15"},  # missing isn_dob_bis_viol
        ]
        db = _BackfillDb()
        client = _StubHttpClient([page])
        import logging
        log_records: list = []
        handler = logging.Handler()
        handler.emit = lambda r: log_records.append(r)
        ing_logger = logging.getLogger("lib.statistical_engine.ingestion")
        ing_logger.addHandler(handler)
        prev_level = ing_logger.level
        ing_logger.setLevel(logging.DEBUG)
        try:
            _run(ing.backfill_dataset(
                db, "dob_violations",
                page_limit=10,
                http_client=client,
                max_pages=1,
            ))
        finally:
            ing_logger.removeHandler(handler)
            ing_logger.setLevel(prev_level)

        error_lines = [
            r for r in log_records
            if r.levelno >= logging.ERROR
            and "dropped row" in r.getMessage()
        ]
        self.assertGreaterEqual(
            len(error_lines), 1,
            "expected at least one dropped-row ERROR log",
        )
        # The reason field must appear in the message.
        joined = "\n".join(r.getMessage() for r in error_lines)
        self.assertIn(
            "reason=missing_record_id", joined,
            f"drop reason not in log message: {joined!r}",
        )

    def test_v22_3_forward_to_v22_logs_drop_reason(self):
        """V2.2.3 BUG 7 Part B: forward_to_v22 was previously
        silent on canonicalization-drop. Now it emits an ERROR
        log so a poller-side bug becomes visible."""
        db = _BackfillDb()
        # Missing record_id source.
        bad_raw = {"bin": "1234567", "issue_date": "2026-04-15"}
        import logging
        log_records: list = []
        handler = logging.Handler()
        handler.emit = lambda r: log_records.append(r)
        ing_logger = logging.getLogger("lib.statistical_engine.ingestion")
        ing_logger.addHandler(handler)
        prev_level = ing_logger.level
        ing_logger.setLevel(logging.DEBUG)
        try:
            ok = _run(ing.forward_to_v22(db, "dob_violations", bad_raw))
        finally:
            ing_logger.removeHandler(handler)
            ing_logger.setLevel(prev_level)

        self.assertFalse(ok, "drop should produce False return")
        error_lines = [
            r for r in log_records
            if r.levelno >= logging.ERROR
            and "forward_to_v22" in r.getMessage()
            and "dropped row" in r.getMessage()
        ]
        self.assertGreaterEqual(
            len(error_lines), 1,
            "forward_to_v22 must log on canonicalization-drop "
            "(was silent pre-V2.2.3)",
        )


if __name__ == "__main__":
    unittest.main()
