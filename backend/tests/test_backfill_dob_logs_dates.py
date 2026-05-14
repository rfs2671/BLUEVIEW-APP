"""PR #9 — backfill script tests for the heterogeneous date format fix.

Targets ``backend/scripts/backfill_dob_logs_dates.py`` (NEW —
Stage 3 implementation). Stage 2 RED PHASE: all tests fail with
``self.fail(...)`` from the import guard because the module does
not yet exist.

Public API expected by these tests (Stage 3 contract):

  • ``run_backfill(db, *, execute=False, socrata_get=None,
    logger=None) -> Dict[str, int]`` — top-level async driver.
    Returns stats dict per Stage 2 design Branches 4.1 + 4.2.

  • ``_detect_pattern(raw_dob_id: str) -> Optional[str]`` — returns
    one of 'aeuhaz' / 'll629' / 'vio_ftf_pl' / None.

  • ``_parse_raw_dob_id_date(raw_dob_id: str) -> Optional[str]`` —
    dispatches internally based on pattern, returns YYYYMMDD or
    None.

Stats dict shape:
  {
    "mdy_scanned", "mdy_normalized", "mdy_skipped_already_iso",
    "null_scanned", "null_recovered_from_socrata",
    "null_recovered_from_raw_dob_id", "null_unrecoverable",
    "null_not_in_socrata", "null_network_failures",
  }

Rollback fields per Stage 2 amendment:
  • ``_original_complaint_date`` stamped on every MDY-normalized
    complaint record before write.
  • ``_original_closed_date`` stamped when closed_date is also
    normalized.

Failure markers per Stage 2 T7 + T1 resolutions:
  • ``_date_extraction_failed: True`` — neither Socrata nor
    raw_dob_id parse produced a date.
  • ``_record_not_in_socrata: True`` — Socrata returned no record;
    fallback to raw_dob_id parse was attempted.
  • ``_recovered_from_raw_dob_id: True`` — date came from
    raw_dob_id parse (not Socrata authoritative source).
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.run(coro)


# ─── Backfill module imports — graceful fail until Stage 3 lands ──

try:
    from scripts.backfill_dob_logs_dates import (  # type: ignore
        run_backfill,
        _detect_pattern,
        _parse_raw_dob_id_date,
    )
    HAS_BACKFILL = True
except ImportError:
    run_backfill = None  # type: ignore
    _detect_pattern = None  # type: ignore
    _parse_raw_dob_id_date = None  # type: ignore
    HAS_BACKFILL = False


_PROJECT_ID = "test_project_X"


# ──────────────────────────────────────────────────────────────────
# Minimal Mongo stubs — same pattern as test_v2_3_baselines._StubDb
# but scoped to the dob_logs surface backfill touches.
# ──────────────────────────────────────────────────────────────────


class _StubDobLogsAsyncCursor:
    """async-iterable + .to_list(...) cursor compatible with the
    backfill's ``find().to_list(None)`` or ``async for doc in find()``
    consumption patterns."""

    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()

    async def to_list(self, length=None):
        return list(self._docs)


class _StubDobLogsCollection:
    """In-memory dob_logs stub. Backfill uses ``find()`` (with
    arbitrary filters) and ``update_one()``. Filter matching here
    is intentionally narrow — supports just the regex + null-check
    filters the backfill issues."""

    def __init__(self, docs: List[Dict[str, Any]] = None):
        self._docs = list(docs or [])
        self.update_calls: List[Dict[str, Any]] = []

    def seed(self, docs: List[Dict[str, Any]]):
        self._docs = [dict(d) for d in docs]

    def find(self, query: Dict[str, Any], projection=None):
        matched = [d for d in self._docs if self._matches(d, query)]
        return _StubDobLogsAsyncCursor(matched)

    async def update_one(self, filter_doc, update_doc, **kwargs):
        self.update_calls.append({"filter": filter_doc, "update": update_doc})
        target_id = filter_doc.get("_id")
        for d in self._docs:
            if d.get("_id") == target_id:
                set_clause = update_doc.get("$set", {})
                for k, v in set_clause.items():
                    d[k] = v
        r = MagicMock()
        r.matched_count = 1
        r.modified_count = 1
        return r

    def _matches(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for key, criterion in query.items():
            if key == "$or":
                if not any(self._matches(doc, sub) for sub in criterion):
                    return False
                continue
            actual = doc.get(key)
            if isinstance(criterion, dict):
                for op, expected in criterion.items():
                    if op == "$regex":
                        import re
                        if actual is None or not re.search(expected, str(actual)):
                            return False
                    elif op == "$in":
                        if actual not in expected:
                            return False
                    elif op == "$nin":
                        if actual in expected:
                            return False
                    elif op == "$ne":
                        if actual == expected:
                            return False
                    elif op == "$exists":
                        present = key in doc
                        if expected and not present:
                            return False
                        if not expected and present:
                            return False
                    elif op == "$eq":
                        if actual != expected:
                            return False
                    else:
                        # Unknown op — treat as miss to surface stub gaps
                        return False
            else:
                if actual != criterion:
                    return False
        return True


class _StubDb:
    def __init__(self, dob_logs=None):
        self.dob_logs = _StubDobLogsCollection(dob_logs or [])


# ──────────────────────────────────────────────────────────────────
# Socrata mock — async callable per backfill's expected DI shape
# ──────────────────────────────────────────────────────────────────


class _MockSocrataGet:
    """Routes the backfill's Socrata re-query calls to a canned
    response per (slug, id_field, raw_id) key. Returns one of:

      • dict   — record found, fields available to the extractor
      • None   — record not found (404 / empty list semantics)
      • raises — network/5xx error (the backfill's exception path)
    """

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self._responses: Dict[tuple, Any] = {}
        self._raise: Dict[tuple, Exception] = {}

    def set_response(self, slug: str, id_field: str, raw_id: str, response):
        self._responses[(slug, id_field, raw_id)] = response

    def set_raises(self, slug: str, id_field: str, raw_id: str, exc: Exception):
        self._raise[(slug, id_field, raw_id)] = exc

    async def __call__(self, slug: str, id_field: str, raw_id: str):
        self.calls.append(
            {"slug": slug, "id_field": id_field, "raw_id": raw_id}
        )
        key = (slug, id_field, raw_id)
        if key in self._raise:
            raise self._raise[key]
        return self._responses.get(key)


# ──────────────────────────────────────────────────────────────────
# 14-16. Backfill driver behavior — MDY complaint normalization
# ──────────────────────────────────────────────────────────────────


class TestBackfillMdyComplaintNormalization(unittest.TestCase):
    """Branch 4.1 — 50 MDY complaints (all DOB path per Stage 1.5
    Query B). Tests 14-16 + 20 cover the MDY pass."""

    def _require_backfill(self):
        if not HAS_BACKFILL:
            self.fail(
                "backend/scripts/backfill_dob_logs_dates.py not yet "
                "implemented (Stage 3). Expected exports: run_backfill, "
                "_detect_pattern, _parse_raw_dob_id_date."
            )

    def _seed_mixed_complaints(self) -> _StubDb:
        db = _StubDb()
        db.dob_logs.seed([
            # 2 MDY complaints (in scope for normalization)
            {
                "_id":             "id_mdy_a",
                "record_type":     "complaint",
                "raw_dob_id":      "5042113",  # DOB path
                "project_id":      _PROJECT_ID,
                "complaint_date":  "06/04/2025",
                "closed_date":     "06/15/2025",
            },
            {
                "_id":             "id_mdy_b",
                "record_type":     "complaint",
                "raw_dob_id":      "5042114",  # DOB path
                "project_id":      _PROJECT_ID,
                "complaint_date":  "5/21/2025",
                "closed_date":     None,
            },
            # 1 already-ISO complaint (should be skipped — idempotency)
            {
                "_id":             "id_iso",
                "record_type":     "complaint",
                "raw_dob_id":      "5042115",
                "project_id":      _PROJECT_ID,
                "complaint_date":  "2025-06-10T14:22:00.000",
                "closed_date":     None,
            },
        ])
        return db

    def test_14_dry_run_reports_correct_change_set_no_writes(self):
        """Test 14 — dry-run reports the 2 MDY records as planned
        normalizations and the 1 ISO record as skipped. ZERO update
        calls made to dob_logs."""
        self._require_backfill()
        db = self._seed_mixed_complaints()
        stats = _run(run_backfill(db, execute=False))
        self.assertEqual(stats["mdy_scanned"], 2)
        self.assertEqual(stats["mdy_normalized"], 2)
        self.assertEqual(
            len(db.dob_logs.update_calls), 0,
            f"Dry-run made writes! update_calls={db.dob_logs.update_calls!r}",
        )

    def test_15_execute_normalizes_mdy_in_place_with_rollback_field(self):
        """Test 15 — --execute mutates dob_logs. Each updated record
        gets the ISO ``complaint_date`` AND a preserved
        ``_original_complaint_date`` rollback field.

        Per Stage 2 amendment: rollback fields capture pre-fix
        values so a rollback can restore them without re-querying
        Socrata.
        """
        self._require_backfill()
        db = self._seed_mixed_complaints()
        stats = _run(run_backfill(db, execute=True))
        self.assertEqual(stats["mdy_normalized"], 2)
        # Verify the in-place mutation produced ISO output
        # AND the rollback field on each modified record.
        for doc_id, original in (("id_mdy_a", "06/04/2025"),
                                  ("id_mdy_b", "5/21/2025")):
            doc = next(d for d in db.dob_logs._docs if d["_id"] == doc_id)
            self.assertTrue(
                doc["complaint_date"].startswith(
                    "2025-06-04" if doc_id == "id_mdy_a" else "2025-05-21"
                ),
                f"Doc {doc_id} complaint_date not normalized to ISO: "
                f"{doc.get('complaint_date')!r}",
            )
            self.assertEqual(
                doc.get("_original_complaint_date"), original,
                f"Doc {doc_id} missing or wrong rollback field: "
                f"{doc.get('_original_complaint_date')!r}",
            )

    def test_16_idempotent_second_run_is_noop(self):
        """Test 16 — running --execute twice. First run normalizes
        the 2 MDY records. Second run finds zero MDY records (the
        regex pre-check skips ISO-shaped values) and reports 0
        normalized."""
        self._require_backfill()
        db = self._seed_mixed_complaints()
        _run(run_backfill(db, execute=True))
        update_calls_after_first = len(db.dob_logs.update_calls)
        # Second run
        stats_second = _run(run_backfill(db, execute=True))
        self.assertEqual(
            stats_second["mdy_normalized"], 0,
            f"Second run normalized records that should already be "
            f"ISO. Stats: {stats_second!r}",
        )
        # No new update calls beyond the first run
        self.assertEqual(
            len(db.dob_logs.update_calls), update_calls_after_first,
            "Second run made additional writes — backfill is not idempotent.",
        )


# ──────────────────────────────────────────────────────────────────
# 17-19. Backfill driver behavior — null violation re-query
# ──────────────────────────────────────────────────────────────────


class TestBackfillNullViolationReQuery(unittest.TestCase):
    """Branch 4.2 — 13 null violation records (all pre-A2 per
    Stage 1.5 Query A). Tests 17-19 cover the three Socrata
    outcome classes from Stage 2 design."""

    def _require_backfill(self):
        if not HAS_BACKFILL:
            self.fail(
                "backend/scripts/backfill_dob_logs_dates.py not yet "
                "implemented (Stage 3)."
            )

    def _seed_null_violation(self, raw_dob_id: str = "022217AEUHAZ100357"):
        """Single null-date violation with an AEUHAZ-pattern raw_dob_id
        (pre-A2 era, BIS legacy slug)."""
        db = _StubDb()
        db.dob_logs.seed([
            {
                "_id":             "id_null_viol",
                "record_type":     "violation",
                "raw_dob_id":      raw_dob_id,
                "project_id":      _PROJECT_ID,
                "violation_date":  None,
                # No `dataset` field — pre-A2 per Query A
            },
        ])
        return db

    def test_17_socrata_404_falls_back_to_raw_dob_id_parse(self):
        """Test 17 — Socrata returns None (404 / empty list). Backfill
        falls back to raw_dob_id parse. Doc gets:
          • ``violation_date`` from raw_dob_id parse (YYYYMMDD)
          • ``_record_not_in_socrata: True``
          • ``_recovered_from_raw_dob_id: True``
        """
        self._require_backfill()
        db = self._seed_null_violation("022217AEUHAZ100357")
        socrata = _MockSocrataGet()
        # 3h2n-5cm9 → isn_dob_bis_viol → 022217AEUHAZ100357
        socrata.set_response(
            "3h2n-5cm9", "isn_dob_bis_viol", "022217AEUHAZ100357", None
        )
        stats = _run(run_backfill(db, execute=True, socrata_get=socrata))
        self.assertEqual(stats["null_recovered_from_raw_dob_id"], 1)
        self.assertEqual(stats["null_not_in_socrata"], 1)
        doc = db.dob_logs._docs[0]
        # AEUHAZ "022217..." → MM=02 DD=22 YY=17 → 20170222
        self.assertEqual(doc["violation_date"], "20170222")
        self.assertIs(doc.get("_record_not_in_socrata"), True)
        self.assertIs(doc.get("_recovered_from_raw_dob_id"), True)

    def test_18_socrata_returns_record_with_null_date_marks_extraction_failed(self):
        """Test 18 — Socrata returns a record but all 4 fallback
        date fields are null AND raw_dob_id parse also fails (use
        a non-pattern-matching raw_dob_id). Doc gets:
          • ``violation_date`` remains None
          • ``_date_extraction_failed: True``
        """
        self._require_backfill()
        # Use a raw_dob_id that doesn't match any of the 3 patterns
        db = self._seed_null_violation("UNPARSEABLE_RAW_ID_XYZ")
        socrata = _MockSocrataGet()
        # Routing logic: unparseable pattern → sequential try-all
        # (operator's hybrid T1 resolution). Configure all 3 slugs
        # to return source-null records.
        empty_record = {
            "issue_date": None,
            "violation_date": None,
            "issued_date": None,
            "infraction_date": None,
        }
        for slug, field in [
            ("855j-jady", "violation_number"),
            ("3h2n-5cm9", "isn_dob_bis_viol"),
            ("6bgk-3dad", "ecb_violation_number"),
        ]:
            socrata.set_response(slug, field, "UNPARSEABLE_RAW_ID_XYZ", empty_record)
        stats = _run(run_backfill(db, execute=True, socrata_get=socrata))
        self.assertEqual(stats["null_unrecoverable"], 1)
        doc = db.dob_logs._docs[0]
        self.assertIsNone(doc.get("violation_date"))
        self.assertIs(doc.get("_date_extraction_failed"), True)

    def test_19_socrata_5xx_skips_without_marker(self):
        """Test 19 — Network/5xx exception. Backfill logs warning,
        skips this record, does NOT stamp any marker. Stats:
        ``null_network_failures`` is incremented. Per Stage 2
        amendment (simple always-retry, no time-based suppression):
        next run retries without any quiet-period suppression."""
        self._require_backfill()
        db = self._seed_null_violation("022217AEUHAZ100357")
        socrata = _MockSocrataGet()
        socrata.set_raises(
            "3h2n-5cm9", "isn_dob_bis_viol", "022217AEUHAZ100357",
            ConnectionError("simulated 503"),
        )
        stats = _run(run_backfill(db, execute=True, socrata_get=socrata))
        self.assertEqual(stats["null_network_failures"], 1)
        doc = db.dob_logs._docs[0]
        self.assertIsNone(doc.get("violation_date"))
        # No markers — retry on next run.
        self.assertNotIn("_date_extraction_failed", doc)
        self.assertNotIn("_record_not_in_socrata", doc)
        self.assertNotIn("_recovered_from_raw_dob_id", doc)


# ──────────────────────────────────────────────────────────────────
# 20. Pre-A2 filter — defensive scope
# ──────────────────────────────────────────────────────────────────


class TestBackfillScope(unittest.TestCase):
    """Stage 2 amendment +20 — defensive filter ensures the null-
    violation branch (4.2) only re-queries pre-A2 records (no
    ``dataset`` stamp). A2-era records that somehow show null
    violation_date would NOT be in scope for this backfill."""

    def _require_backfill(self):
        if not HAS_BACKFILL:
            self.fail(
                "backend/scripts/backfill_dob_logs_dates.py not yet "
                "implemented (Stage 3)."
            )

    def test_20_only_processes_pre_a2_records(self):
        """Test 20 — fixture with one pre-A2 null-date record and
        one A2-era null-date record (carries ``dataset: "3h2n-5cm9"``
        stamp). Backfill processes only the pre-A2 record."""
        self._require_backfill()
        db = _StubDb()
        db.dob_logs.seed([
            # Pre-A2 — no `dataset` field
            {
                "_id":             "id_pre_a2",
                "record_type":     "violation",
                "raw_dob_id":      "022217AEUHAZ100357",
                "project_id":      _PROJECT_ID,
                "violation_date":  None,
            },
            # A2-era — has `dataset` stamp, SHOULD BE SKIPPED
            {
                "_id":             "id_a2_era",
                "record_type":     "violation",
                "raw_dob_id":      "VIO-FTF-PL-PER-202506-1234567",
                "project_id":      _PROJECT_ID,
                "violation_date":  None,
                "dataset":         "855j-jady",
            },
        ])
        socrata = _MockSocrataGet()
        socrata.set_response(
            "3h2n-5cm9", "isn_dob_bis_viol", "022217AEUHAZ100357", None
        )
        stats = _run(run_backfill(db, execute=True, socrata_get=socrata))
        self.assertEqual(
            stats["null_scanned"], 1,
            f"Backfill should only process pre-A2 records "
            f"(no dataset stamp). Got null_scanned={stats.get('null_scanned')}.",
        )
        # A2-era record untouched (no Socrata call for it)
        a2_calls = [c for c in socrata.calls if c["raw_id"] == "VIO-FTF-PL-PER-202506-1234567"]
        self.assertEqual(
            len(a2_calls), 0,
            f"Backfill made a Socrata call for an A2-era record: "
            f"{a2_calls!r}",
        )


# ──────────────────────────────────────────────────────────────────
# 21-23. Hybrid T1 — raw_dob_id pattern parsers + precedence
# ──────────────────────────────────────────────────────────────────


class TestRawDobIdPatternParser(unittest.TestCase):
    """Hybrid T1 resolution — pattern-detect raw_dob_id → route to
    correct slug → fall back to in-id date parse when Socrata can't
    help. Tests 21-22 exercise the parser directly; test 23 exercises
    the precedence rule."""

    def _require_backfill(self):
        if not HAS_BACKFILL:
            self.fail(
                "backend/scripts/backfill_dob_logs_dates.py not yet "
                "implemented (Stage 3)."
            )

    def test_21_parses_aeuhaz_pattern_for_legacy_dates(self):
        """Test 21 — AEUHAZ pattern: first 6 chars = MMDDYY.
        Year cutoff per operator's hybrid resolution: ≤30 → 20xx,
        >30 → 19xx. Output: YYYYMMDD."""
        self._require_backfill()
        # Detection
        self.assertEqual(_detect_pattern("022217AEUHAZ100357"), "aeuhaz")
        # Parse: 02/22/17 → 2017 (17 ≤ 30) → "20170222"
        self.assertEqual(_parse_raw_dob_id_date("022217AEUHAZ100357"), "20170222")
        # Edge: year exactly 30 — operator's rule is ≤30 → 20xx
        # so "30" → 2030
        self.assertEqual(_parse_raw_dob_id_date("010130AEUHAZ999"), "20300101")
        # Edge: year 31 — > 30 → 1931
        self.assertEqual(_parse_raw_dob_id_date("010131AEUHAZ999"), "19310101")

    def test_22_parses_ll629_pattern_for_legacy_dates(self):
        """Test 22 — LL629 pattern: same MMDDYY parser as AEUHAZ
        (different prefix, same parse logic). LL629 records are
        1993-2001 era per operator's sample. Year cutoff rule
        applies identically."""
        self._require_backfill()
        # Detection
        self.assertEqual(_detect_pattern("022701LL629116468"), "ll629")
        # Parse: 02/27/01 → 2001 (01 ≤ 30) → "20010227"
        self.assertEqual(_parse_raw_dob_id_date("022701LL629116468"), "20010227")
        # 1993 case: 12/15/93 → > 30 → 1993 → "19931215"
        self.assertEqual(_parse_raw_dob_id_date("121593LL629999"), "19931215")

    def test_23_prefers_socrata_authoritative_date_over_raw_dob_id_parse(self):
        """Test 23 — Precedence rule. When Socrata returns a record
        with a usable date, the Socrata value wins. The raw_dob_id
        parse is the FALLBACK, not the source of truth.

        Implicit coverage of VIO-FTF-PL pattern: detection + parse
        exercised here (would-be fallback) while the assertion pins
        Socrata precedence. If this test passes for both the
        precedence assertion AND the underlying parse, VIO-FTF-PL
        coverage is satisfied.
        """
        self._require_backfill()
        # VIO-FTF-PL pattern: detection works
        self.assertEqual(
            _detect_pattern("VIO-FTF-PL-PER-202412-0191848"),
            "vio_ftf_pl",
        )
        # Underlying parse: YYYYMM in middle segment, day defaults
        # to 01 → "20241201"
        self.assertEqual(
            _parse_raw_dob_id_date("VIO-FTF-PL-PER-202412-0191848"),
            "20241201",
        )

        # Now the precedence integration test. Fixture: VIO-FTF-PL
        # record. Socrata returns a record with issue_date != the
        # raw_dob_id parse output. Backfill must apply Socrata's
        # value AND NOT mark `_recovered_from_raw_dob_id`.
        db = _StubDb()
        db.dob_logs.seed([
            {
                "_id":             "id_vio_ftf_pl",
                "record_type":     "violation",
                "raw_dob_id":      "VIO-FTF-PL-PER-202412-0191848",
                "project_id":      _PROJECT_ID,
                "violation_date":  None,
            },
        ])
        socrata = _MockSocrataGet()
        # 855j-jady → violation_number → record with issue_date that
        # DIFFERS from the raw_dob_id parse output ("20241201").
        socrata.set_response(
            "855j-jady",
            "violation_number",
            "VIO-FTF-PL-PER-202412-0191848",
            {
                "issue_date":       "20250115",
                "violation_date":   None,
                "issued_date":      None,
                "infraction_date":  None,
            },
        )
        stats = _run(run_backfill(db, execute=True, socrata_get=socrata))
        self.assertEqual(stats["null_recovered_from_socrata"], 1)
        doc = db.dob_logs._docs[0]
        self.assertEqual(
            doc["violation_date"], "20250115",
            f"Socrata authoritative date must win over raw_dob_id "
            f"parse. Got: {doc.get('violation_date')!r}",
        )
        self.assertNotIn(
            "_recovered_from_raw_dob_id", doc,
            f"Marker only set when raw_dob_id parse provided the "
            f"date. Doc: {doc!r}",
        )
        self.assertNotIn("_record_not_in_socrata", doc)
        self.assertNotIn("_date_extraction_failed", doc)


if __name__ == "__main__":
    unittest.main()
