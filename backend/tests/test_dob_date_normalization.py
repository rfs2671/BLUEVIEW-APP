"""PR #9 — heterogeneous date format fix at the extractor layer.

Unit tests for:

  • ``server._normalize_dob_date_to_iso`` (shared helper, NEW) —
    MDY → ISO normalization with ms suffix, ISO passthrough +
    canonicalization, malformed warn+None per Stage 2 T2.C.

  • ``server._extract_complaint_fields`` (eabe-havv path) — must
    call the helper on ``date_entered`` so MDY inputs become ISO
    on the persisted document.

  • ``server._build_311_doc`` (extracted from
    ``_ingest_311_for_project``'s inline dict construction per
    Stage 2 T6.B refactor) — must call the helper on
    ``created_date`` AND ``closed_date``.

  • ``server._extract_violation_fields`` — characterization of
    the existing 4-field fallback chain; per Stage 2 T4.A the
    extraction-time path does NOT stamp a marker on all-null
    inputs (backfill-only marker).

Stage 2 RED PHASE: these tests target code not yet implemented.
Helper-dependent tests fail with `self.fail(...)` carrying an
implementation hint. Behavior tests on the existing extractor
fail with AssertionError when the call site doesn't yet invoke
the helper.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ─── Imports — graceful fail when symbols don't exist yet ─────────

try:
    from server import _normalize_dob_date_to_iso  # type: ignore
    HAS_NORMALIZER = True
except ImportError:
    _normalize_dob_date_to_iso = None  # type: ignore
    HAS_NORMALIZER = False

try:
    from server import _build_311_doc  # type: ignore
    HAS_BUILD_311_DOC = True
except ImportError:
    _build_311_doc = None  # type: ignore
    HAS_BUILD_311_DOC = False

# These already exist in server.py — no try/except needed.
from server import _extract_complaint_fields, _extract_violation_fields  # noqa: E402


# ──────────────────────────────────────────────────────────────────
# 1-7. Helper unit tests — _normalize_dob_date_to_iso
# ──────────────────────────────────────────────────────────────────


class TestNormalizeDobDateToIso(unittest.TestCase):
    """Pins the shared MDY → ISO helper contract.

    Output canonical form: ``"%Y-%m-%dT%H:%M:%S.000"`` (B1.a/B1.b
    locked format). MDY inputs land at midnight (no time info in
    source). ISO inputs are canonicalized: missing ms suffix appended,
    date-only inputs expanded to midnight. Malformed inputs warn +
    return None per Stage 2 T2.C.
    """

    def _require_normalizer(self):
        if not HAS_NORMALIZER:
            self.fail(
                "server._normalize_dob_date_to_iso not implemented. "
                "Stage 2 design: add helper to server.py near line "
                "14380 (adjacent to _extract_swo_fields), per "
                "operator decision (b)."
            )

    def test_1_mdy_zero_padded(self):
        """Test 1 — '06/04/2025' → ISO midnight, ms suffix."""
        self._require_normalizer()
        self.assertEqual(
            _normalize_dob_date_to_iso("06/04/2025"),
            "2025-06-04T00:00:00.000",
        )

    def test_2_mdy_single_digit(self):
        """Test 2 — '6/4/2025' → ISO midnight (no zero-padding
        requirement on input)."""
        self._require_normalizer()
        self.assertEqual(
            _normalize_dob_date_to_iso("6/4/2025"),
            "2025-06-04T00:00:00.000",
        )

    def test_3_iso_with_ms_passthrough(self):
        """Test 3 — '2025-06-04T12:30:45.000' → unchanged. Idempotency
        on already-canonical inputs."""
        self._require_normalizer()
        self.assertEqual(
            _normalize_dob_date_to_iso("2025-06-04T12:30:45.000"),
            "2025-06-04T12:30:45.000",
        )

    def test_4_iso_no_ms_appends_suffix(self):
        """Test 4 — '2025-06-04T12:30:45' → append .000. Canonicalizes
        ISO-without-ms inputs (preserves the time component, does NOT
        zero it out)."""
        self._require_normalizer()
        self.assertEqual(
            _normalize_dob_date_to_iso("2025-06-04T12:30:45"),
            "2025-06-04T12:30:45.000",
        )

    def test_5_iso_date_only_expands(self):
        """Test 5 — '2025-06-04' → '2025-06-04T00:00:00.000'. Date-only
        ISO inputs expand to midnight + ms suffix."""
        self._require_normalizer()
        self.assertEqual(
            _normalize_dob_date_to_iso("2025-06-04"),
            "2025-06-04T00:00:00.000",
        )

    def test_6_null_empty_whitespace(self):
        """Test 6 — None / "" / whitespace → None. No exception."""
        self._require_normalizer()
        self.assertIsNone(_normalize_dob_date_to_iso(None))
        self.assertIsNone(_normalize_dob_date_to_iso(""))
        self.assertIsNone(_normalize_dob_date_to_iso("   "))

    def test_7_malformed_warns_and_returns_none(self):
        """Test 7 — Stage 2 T2.C resolution. Malformed input
        emits a WARNING-level log line that includes the raw value,
        and returns None. Strict-but-visible: garbage stays out of
        dob_logs AND operator gets surface signal that a new source
        format showed up."""
        self._require_normalizer()
        with self.assertLogs(level="WARNING") as cm:
            result = _normalize_dob_date_to_iso("not-a-date")
        self.assertIsNone(result)
        # At least one warning line must reference the raw input value
        # so operator grep'ing for the bad value is sufficient triage.
        self.assertTrue(
            any("not-a-date" in line for line in cm.output),
            f"Warning log must reference the raw input value 'not-a-date'. "
            f"Got: {cm.output!r}",
        )


# ──────────────────────────────────────────────────────────────────
# 8-9. Extractor behavior — _extract_complaint_fields
# ──────────────────────────────────────────────────────────────────


class TestComplaintExtractCallsNormalizer(unittest.TestCase):
    """Pins that the DOB-path complaint extractor (eabe-havv at
    ``_query_dob_apis``) runs ``date_entered`` through the shared
    normalizer before assigning to ``complaint_date``.

    Reproduces the production bug: MDY ``date_entered`` from
    eabe-havv must be normalized to ISO so the aggregate's
    lexicographic ``$gte`` filter can compare correctly.
    """

    def _make_rec(self, **overrides):
        rec = {
            "complaint_number": "5042113",
            "status":           "ACTIVE",
            "complaint_category": "21",
        }
        rec.update(overrides)
        return rec

    def test_8_mdy_date_entered_normalized_to_iso(self):
        """Test 8 — MDY input on the DOB complaint path becomes ISO
        on the persisted document.

        RED-PHASE expected failure: current extractor (server.py:14621)
        does ``rec.get("date_entered") or None`` with no normalization,
        so ``complaint_date`` round-trips MDY as-is.
        """
        rec = self._make_rec(date_entered="06/04/2025")
        result = _extract_complaint_fields(rec)
        self.assertEqual(
            result["complaint_date"],
            "2025-06-04T00:00:00.000",
            f"DOB-path complaint extractor must normalize MDY "
            f"date_entered to ISO. Got: {result.get('complaint_date')!r}",
        )

    def test_9_iso_no_ms_date_entered_appends_suffix(self):
        """Test 9 — ISO-without-ms input gets the .000 suffix appended.

        RED-PHASE expected failure: current extractor passes input
        through unchanged. Post-fix, the helper canonicalizes.
        """
        rec = self._make_rec(date_entered="2025-06-10T14:22:00")
        result = _extract_complaint_fields(rec)
        self.assertEqual(
            result["complaint_date"],
            "2025-06-10T14:22:00.000",
            f"DOB-path complaint extractor must canonicalize ISO "
            f"inputs via the helper. Got: {result.get('complaint_date')!r}",
        )


# ──────────────────────────────────────────────────────────────────
# 10. 311 doc construction — _build_311_doc (T6.B refactor target)
# ──────────────────────────────────────────────────────────────────


class TestBuild311DocCallsNormalizer(unittest.TestCase):
    """Pins that the 311 doc-construction (T6.B refactor target)
    runs BOTH ``created_date`` AND ``closed_date`` through the
    shared normalizer.

    Per Stage 2 T6.B: the inline document dict at
    ``_ingest_311_for_project:14063-14093`` is extracted into a
    pure ``_build_311_doc(rec, project, now)`` helper so it can
    be tested in isolation (operator approved). No behavior
    change beyond date normalization.

    Per Stage 1.5 Query B: zero production MDY records on the 311
    path today. Test 10 pins DEFENSIVE behavior — if NYC changes
    erm2-nwe9's source format in the future, the helper still
    normalizes correctly.
    """

    def _require_build_311_doc(self):
        if not HAS_BUILD_311_DOC:
            self.fail(
                "server._build_311_doc not implemented. Stage 2 "
                "T6.B refactor: extract the inline dict construction "
                "from _ingest_311_for_project (server.py:14063-14093) "
                "into a pure function `_build_311_doc(rec, project, "
                "now) -> dict`. No behavior change beyond date "
                "normalization via _normalize_dob_date_to_iso."
            )

    def test_10_normalizes_complaint_date_and_closed_date(self):
        """Test 10 — Both 311 date fields land in ISO format
        regardless of source format."""
        self._require_build_311_doc()
        rec = {
            "unique_key":      "67890124",
            "complaint_type":  "Construction",
            "created_date":    "06/12/2025",  # MDY (defensive case)
            "closed_date":     "06/18/2025",  # MDY (defensive case)
            "incident_address": "100 Main St",
            "city":            "Brooklyn",
            "status":          "Closed",
            "descriptor":      "Noise",
            "agency":          "DOB",
            "agency_name":     "Department of Buildings",
            "resolution_description": "Closed by inspector",
        }
        project = {
            "_id":        "test_project_X",
            "company_id": "company_X",
            "nyc_bin":    "1234567",
        }
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        doc = _build_311_doc(rec, project, now)
        self.assertEqual(
            doc["complaint_date"],
            "2025-06-12T00:00:00.000",
            f"_build_311_doc must normalize MDY created_date. "
            f"Got: {doc.get('complaint_date')!r}",
        )
        self.assertEqual(
            doc["closed_date"],
            "2025-06-18T00:00:00.000",
            f"_build_311_doc must normalize MDY closed_date. "
            f"Got: {doc.get('closed_date')!r}",
        )


# ──────────────────────────────────────────────────────────────────
# 11. Violation extractor fallback chain — characterization
# ──────────────────────────────────────────────────────────────────


class TestViolationExtractFallbackChain(unittest.TestCase):
    """Characterizes the existing 4-field fallback chain in
    ``_extract_violation_fields``. Per Stage 1.5 Query A, all 13
    null-violation_date records are pre-A2 (no ``dataset`` stamp).
    The chain is adequate for fresh A2-era ingestion — no
    extension needed.

    Stage 2 T4.A: extraction-time path does NOT stamp
    ``_date_extraction_failed`` on all-null inputs. That marker
    is reserved for the backfill script (per Branch 4.2 design).
    """

    def _make_rec(self, **dates):
        rec = {
            "issue_date":       None,
            "violation_date":   None,
            "issued_date":      None,
            "infraction_date":  None,
            "violation_number": "test_id",
        }
        rec.update(dates)
        return rec

    def test_11a_uses_primary_issue_date(self):
        """11a — issue_date (primary) wins even when later fallback
        fields are also populated."""
        rec = self._make_rec(issue_date="20250520", violation_date="20250101")
        result = _extract_violation_fields(rec)
        self.assertEqual(result["violation_date"], "20250520")

    def test_11b_falls_back_to_violation_date(self):
        """11b — secondary fallback when primary missing."""
        rec = self._make_rec(violation_date="20250515")
        result = _extract_violation_fields(rec)
        self.assertEqual(result["violation_date"], "20250515")

    def test_11c_falls_back_to_issued_date(self):
        """11c — tertiary fallback when primary + secondary missing."""
        rec = self._make_rec(issued_date="20250512")
        result = _extract_violation_fields(rec)
        self.assertEqual(result["violation_date"], "20250512")

    def test_11d_falls_back_to_infraction_date(self):
        """11d — quaternary fallback when first three missing."""
        rec = self._make_rec(infraction_date="20250510")
        result = _extract_violation_fields(rec)
        self.assertEqual(result["violation_date"], "20250510")

    def test_11e_all_null_returns_none_without_marker(self):
        """11e — all 4 fields null. Per Stage 2 T4.A: NO
        ``_date_extraction_failed`` marker at extraction time.
        That marker is backfill-only."""
        rec = self._make_rec()
        result = _extract_violation_fields(rec)
        self.assertIsNone(result["violation_date"])
        # T4.A: no extraction-time marker
        self.assertNotIn("_date_extraction_failed", result)


if __name__ == "__main__":
    unittest.main()
