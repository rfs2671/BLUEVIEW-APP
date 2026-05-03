"""MR.14 (commit 2a) — v1 monitoring schema additions on dob_logs.

Pins:
  • _extract_dob_log_status reads the per-record_type status field.
  • _extract_job_status_fields populates filing_status from the raw
    DOB NOW Job Filings (w9ak-ipjd) record shape so diffing has a
    value to compare against.
  • DOB_RECORD_TYPE_STATUS_FIELDS map covers the six v1 record_types.

Insertion-path diffing logic (status-changed → new row vs.
status-unchanged → update existing) is exercised end-to-end against
a real Mongo via the dob_signal_diffing test class.

Cadence + TTL + track_dob_status default are pinned by separate
tests below.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ── Pure-helper tests ─────────────────────────────────────────────


class TestExtractDobLogStatus(unittest.TestCase):
    """The universal current_status extractor reads dataset-specific
    fields per record_type. Pinned here so a future commit that
    renames a status field on one of the Socrata datasets breaks
    loudly instead of silently making diffing a no-op."""

    def test_permit_reads_permit_status(self):
        from server import _extract_dob_log_status
        log = {"record_type": "permit", "permit_status": "Issued"}
        self.assertEqual(_extract_dob_log_status(log), "ISSUED")

    def test_violation_reads_status(self):
        from server import _extract_dob_log_status
        log = {"record_type": "violation", "status": "ACTIVE"}
        self.assertEqual(_extract_dob_log_status(log), "ACTIVE")

    def test_complaint_reads_complaint_status(self):
        from server import _extract_dob_log_status
        log = {"record_type": "complaint", "complaint_status": "Open"}
        self.assertEqual(_extract_dob_log_status(log), "OPEN")

    def test_inspection_reads_inspection_result(self):
        from server import _extract_dob_log_status
        log = {"record_type": "inspection", "inspection_result": "PASSED"}
        self.assertEqual(_extract_dob_log_status(log), "PASSED")

    def test_swo_reads_status(self):
        from server import _extract_dob_log_status
        # SWO is a violation subtype; same status field as violation.
        log = {"record_type": "swo", "status": "active"}
        self.assertEqual(_extract_dob_log_status(log), "ACTIVE")

    def test_job_status_reads_filing_status(self):
        from server import _extract_dob_log_status
        log = {"record_type": "job_status", "filing_status": "Approved"}
        self.assertEqual(_extract_dob_log_status(log), "APPROVED")

    def test_unknown_record_type_returns_none(self):
        from server import _extract_dob_log_status
        log = {"record_type": "weird_new_type", "status": "x"}
        self.assertIsNone(_extract_dob_log_status(log))

    def test_missing_status_field_returns_none(self):
        from server import _extract_dob_log_status
        # record_type maps to permit_status, but the field isn't set.
        log = {"record_type": "permit"}
        self.assertIsNone(_extract_dob_log_status(log))

    def test_empty_string_status_returns_none(self):
        """Strip-then-empty must coerce to None so diffing treats it
        the same as a missing field (avoids spurious ""→"ISSUED"
        transitions when a stub doc gets re-polled with real data)."""
        from server import _extract_dob_log_status
        log = {"record_type": "permit", "permit_status": "   "}
        self.assertIsNone(_extract_dob_log_status(log))


class TestExtractJobStatusFields(unittest.TestCase):
    """The new extractor for DOB NOW Job Filings (w9ak-ipjd).
    Pre-MR.14 these records inserted without an extras call; their
    filing_status was lost. Now captured + available for diffing."""

    def test_extracts_filing_status_primary_field(self):
        from server import _extract_job_status_fields
        rec = {
            "filing_status": "Approved",
            "job_filing_number": "B00123456-S1",
            "filing_date": "2026-04-01",
            "job_description": "Plumbing work",
        }
        fields = _extract_job_status_fields(rec)
        self.assertEqual(fields["filing_status"], "Approved")
        self.assertEqual(fields["job_filing_number"], "B00123456-S1")

    def test_falls_back_to_current_filing_status(self):
        """Some datasets use `current_filing_status`; cover the
        fallback chain so renamed-column drift doesn't break us."""
        from server import _extract_job_status_fields
        rec = {"current_filing_status": "Pending"}
        fields = _extract_job_status_fields(rec)
        self.assertEqual(fields["filing_status"], "Pending")

    def test_returns_none_when_no_status(self):
        from server import _extract_job_status_fields
        rec = {"job_filing_number": "B00123456-S1"}  # no status fields
        fields = _extract_job_status_fields(rec)
        self.assertIsNone(fields["filing_status"])

    def test_empty_string_coerces_to_none(self):
        from server import _extract_job_status_fields
        rec = {"filing_status": ""}
        fields = _extract_job_status_fields(rec)
        self.assertIsNone(fields["filing_status"])


class TestStatusFieldMapCoverage(unittest.TestCase):
    """The map MUST cover every record_type the rest of the system
    knows about. If a future commit adds a record_type but forgets
    to add a status field, this test catches it loudly."""

    def test_map_covers_all_known_record_types(self):
        from server import DOB_RECORD_TYPE_STATUS_FIELDS
        # The set of record_types that appear in extra_fields branching
        # in nightly_dob_scan / 311-poll. Update this set when a new
        # record_type is added.
        EXPECTED = {"permit", "violation", "complaint", "inspection", "swo", "job_status"}
        self.assertEqual(
            set(DOB_RECORD_TYPE_STATUS_FIELDS.keys()),
            EXPECTED,
            f"DOB_RECORD_TYPE_STATUS_FIELDS missing or extra entries; "
            f"expected={EXPECTED} got={set(DOB_RECORD_TYPE_STATUS_FIELDS.keys())}",
        )

    def test_every_field_value_is_a_nonempty_string(self):
        """Defensive: a None or empty value would silently disable
        diffing for that record_type."""
        from server import DOB_RECORD_TYPE_STATUS_FIELDS
        for rt, field in DOB_RECORD_TYPE_STATUS_FIELDS.items():
            with self.subTest(record_type=rt):
                self.assertIsInstance(field, str)
                self.assertTrue(field, f"empty status field for {rt}")


# ── Project model + create_project default ────────────────────────


class TestTrackDobStatusDefaultFlipped(unittest.TestCase):
    """MR.14 (commit 2a) — Operator F7: default to True on new
    project creation. Existing False docs are NOT migrated."""

    def test_project_response_default_is_true(self):
        """The Pydantic model default. Drives any path that
        constructs a ProjectResponse without an explicit value."""
        from server import ProjectResponse
        # Build with the minimum required fields; default must apply.
        resp = ProjectResponse(id="p1", name="Test")
        self.assertTrue(resp.track_dob_status)

    def test_project_response_explicit_false_survives(self):
        """If a caller passes track_dob_status=False (e.g. reading
        a legacy doc back), the value MUST round-trip — we don't
        silently coerce existing False to True."""
        from server import ProjectResponse
        resp = ProjectResponse(id="p1", name="Test", track_dob_status=False)
        self.assertFalse(resp.track_dob_status)


# ── Cadence flip ──────────────────────────────────────────────────


class TestSchedulerCadences(unittest.TestCase):
    """MR.14 (commit 2a) Operator F1: DOB-side at 15 min, 311 stays
    at 30 min. Source-level static check so a future cadence drift
    breaks loudly instead of silently changing the polling rate."""

    def test_dob_nightly_scan_at_15_min(self):
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8", errors="ignore")
        # The dob_nightly_scan job MUST use IntervalTrigger(minutes=15).
        # We require the substring to appear within ~500 chars of the
        # job id 'dob_nightly_scan' so we're not matching some other
        # 15-min trigger by accident.
        idx = text.index("id='dob_nightly_scan'")
        window = text[max(0, idx - 500):idx]
        self.assertIn(
            "IntervalTrigger(minutes=15)", window,
            "dob_nightly_scan must register at 15-min cadence",
        )

    def test_dob_approval_watcher_at_15_min(self):
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8", errors="ignore")
        idx = text.index("id='dob_approval_watcher'")
        window = text[max(0, idx - 500):idx]
        self.assertIn(
            "IntervalTrigger(minutes=15)", window,
            "dob_approval_watcher must register at 15-min cadence",
        )

    def test_311_poll_stays_at_30_min(self):
        """Operator F1 explicit: 311 stays at 30 min — pushing to
        15 min would mostly burn Socrata quota since 311 itself
        updates ~hourly."""
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8", errors="ignore")
        idx = text.index("id='dob_311_fast_poll'")
        window = text[max(0, idx - 500):idx]
        self.assertIn(
            "IntervalTrigger(minutes=30)", window,
            "dob_311_fast_poll must stay at 30-min cadence",
        )


if __name__ == "__main__":
    unittest.main()
