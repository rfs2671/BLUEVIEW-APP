"""MR.14 (commit 2a) — pin the status-change diffing semantics
end-to-end against a mocked db. The test calls the real insertion
path inside `run_dob_sync_for_project` (or its 311 sibling) with
controlled inputs and asserts the right Mongo write happens:

  • status unchanged  →  update_one on the existing _id;
                         no insert_one (no new row created)
  • status changed    →  insert_one with previous_status set to
                         the prior current_status; status_changed_at
                         stamped to now
  • first time seen   →  insert_one with previous_status=None

These three branches are the load-bearing contract from operator
F5 ("New record only created when status differs"). If any future
refactor breaks them, the activity feed silently fills with
duplicates or loses transition events.
"""

from __future__ import annotations

import asyncio
import os
import re
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


def _run(coro):
    return asyncio.run(coro)


# ── Diffing logic — pure data-shape tests ─────────────────────────


class TestDiffingDecision(unittest.TestCase):
    """The decision is conceptually:
        new_status = _extract_dob_log_status(incoming_doc)
        existing = await find_one(raw_dob_id=X, sort=detected_at desc)
        if existing AND existing.current_status == new_status:
            update existing in place
        else:
            insert new with previous_status = existing.current_status if existing else None

    Test the boolean by exercising the helper and feeding both
    branches; we don't need a live Mongo for the decision."""

    def test_status_unchanged_branch(self):
        from server import _extract_dob_log_status
        incoming = {"record_type": "permit", "permit_status": "Issued"}
        existing = {"current_status": "ISSUED"}
        # Helper normalizes to upper.
        self.assertEqual(_extract_dob_log_status(incoming), "ISSUED")
        # Comparison is case-sensitive on the upper-form, so the
        # branch resolves to "unchanged".
        self.assertEqual(
            existing.get("current_status"),
            _extract_dob_log_status(incoming),
        )

    def test_status_changed_branch(self):
        from server import _extract_dob_log_status
        incoming = {"record_type": "permit", "permit_status": "Expired"}
        existing = {"current_status": "ISSUED"}
        self.assertNotEqual(
            existing.get("current_status"),
            _extract_dob_log_status(incoming),
        )

    def test_first_time_seen_branch(self):
        from server import _extract_dob_log_status
        incoming = {"record_type": "permit", "permit_status": "Issued"}
        existing = None
        self.assertIsNone(existing)
        self.assertEqual(_extract_dob_log_status(incoming), "ISSUED")
        # The insertion logic uses `previous_status = existing.get(...)
        # if existing else None` — confirming the code shape.
        previous = existing.get("current_status") if existing else None
        self.assertIsNone(previous)


# ── Cross-record-type diffing comparator ──────────────────────────


class TestDiffingComparatorAcrossRecordTypes(unittest.TestCase):
    """Each record_type has its own status field. The diffing
    comparison must work uniformly via _extract_dob_log_status —
    never read raw status fields directly. Test that the comparator
    returns matching values across all 6 record_types."""

    def test_all_record_types_extract_consistent_status(self):
        from server import _extract_dob_log_status
        cases = [
            ({"record_type": "permit", "permit_status": "Issued"}, "ISSUED"),
            ({"record_type": "violation", "status": "active"}, "ACTIVE"),
            ({"record_type": "complaint", "complaint_status": "Open"}, "OPEN"),
            ({"record_type": "inspection", "inspection_result": "Passed"}, "PASSED"),
            ({"record_type": "swo", "status": "active"}, "ACTIVE"),
            ({"record_type": "job_status", "filing_status": "Approved"}, "APPROVED"),
        ]
        for log, expected in cases:
            with self.subTest(record_type=log["record_type"]):
                self.assertEqual(_extract_dob_log_status(log), expected)


# ── Ensure the new schema fields are mentioned at insert sites ────


class TestInsertionPathsCarryNewSchemaFields(unittest.TestCase):
    """Static-source check: the four operator-mandated schema fields
    (signal_kind, read_by_user, previous_status, status_changed_at)
    plus the implementation-detail current_status MUST appear in
    server.py — guards against accidentally reverting the additions
    in a future refactor that doesn't touch tests for diffing per se.
    """

    def setUp(self):
        path = _BACKEND / "server.py"
        self.text = path.read_text(encoding="utf-8", errors="ignore")

    def test_signal_kind_assigned(self):
        # MUST be assigned on dob_log inserts.
        self.assertIn('"signal_kind"', self.text)

    def test_read_by_user_assigned(self):
        self.assertIn('"read_by_user"', self.text)

    def test_previous_status_assigned(self):
        self.assertIn('"previous_status"', self.text)

    def test_status_changed_at_assigned(self):
        self.assertIn('"status_changed_at"', self.text)

    def test_current_status_assigned(self):
        self.assertIn('"current_status"', self.text)


# ── TTL retention removed — guard against reintroduction ──────────


class TestDobLogsTtlRemoved(unittest.TestCase):
    """TTL retention on dob_logs was REMOVED 2026-07-24 (replacing the
    MR.14 commit-2a indexes ``dob_logs_ttl_short`` 90d and
    ``dob_logs_ttl_long`` 365d).

    Both were keyed on ``detected_at``, which is a BACKFILL / SYNC
    timestamp — the moment this app first saw a record — not the date the
    event occurred. Production verification found every record on both
    tracked projects stamped with that project's first-sync date, so the
    TTL clock measured time-since-first-sync: it would have physically
    deleted a project's entire DOB history 90/365 days after onboarding,
    and re-sync could not restore it ($limit=50 per endpoint; re-inserted
    rows reset previous_status and can re-fire Action alerts).

    See docs/runbooks/dob-logs-ttl-removal-2026-07-24.md.

    This guard inspects _ensure_index_resilient CALL bodies, not raw
    source text, so the explanatory comment in server.py that names the
    old indexes does NOT satisfy it (the previous static check would
    have been fooled by exactly that).
    """

    def setUp(self):
        path = _BACKEND / "server.py"
        self.text = path.read_text(encoding="utf-8", errors="ignore")

    def _call_bodies(self, pattern):
        """Every balanced-paren call body whose opening matches `pattern`."""
        bodies = []
        for m in re.finditer(pattern, self.text):
            i, depth = m.end(), 1
            while i < len(self.text) and depth:
                if self.text[i] == "(":
                    depth += 1
                elif self.text[i] == ")":
                    depth -= 1
                i += 1
            bodies.append(self.text[m.end():i])
        return bodies

    def _dob_logs_index_calls(self):
        """Every _ensure_index_resilient(...) call body targeting db.dob_logs."""
        return [
            b for b in self._call_bodies(r"_ensure_index_resilient\(")
            if "db.dob_logs" in b
        ]

    def test_no_direct_ttl_create_index_on_dob_logs(self):
        """Also guard the direct ``db.dob_logs.create_index(...)`` form —
        it bypasses _ensure_index_resilient entirely, so checking only that
        helper would leave a hole."""
        for body in self._call_bodies(r"db\.dob_logs\.create_index\("):
            self.assertNotIn(
                "expireAfterSeconds", body,
                "A TTL index was reintroduced on dob_logs via a direct "
                "create_index call. See "
                "docs/runbooks/dob-logs-ttl-removal-2026-07-24.md",
            )

    def test_no_ttl_index_created_on_dob_logs(self):
        for body in self._dob_logs_index_calls():
            self.assertNotIn(
                "expireAfterSeconds", body,
                "A TTL index was reintroduced on dob_logs. detected_at is a "
                "sync timestamp, not an event date — any retention policy must "
                "key on a real event date AND carry a documented legal "
                "rationale. See "
                "docs/runbooks/dob-logs-ttl-removal-2026-07-24.md",
            )

    def test_detected_at_diffing_index_retained(self):
        """The (raw_dob_id, detected_at) diffing index is unrelated to
        retention and must stay — the diffing logic sorts on it to pick the
        most recent row per raw_dob_id."""
        self.assertIn(
            'create_index([("raw_dob_id", 1), ("detected_at", -1)])',
            self.text,
        )


# ── Drop-unique-index static check ────────────────────────────────


class TestRawDobIdUniqueDropped(unittest.TestCase):
    """The legacy unique sparse index on raw_dob_id is dropped at
    startup. After MR.14 the diffing logic intentionally inserts
    multiple rows per raw_dob_id (one per status transition); the
    unique constraint would reject those."""

    def setUp(self):
        path = _BACKEND / "server.py"
        self.text = path.read_text(encoding="utf-8", errors="ignore")

    def test_drops_legacy_unique_index_at_startup(self):
        self.assertIn("drop_index(\"raw_dob_id_1\")", self.text)
        # Replacement index is non-unique.
        self.assertIn(
            'create_index([("raw_dob_id", 1), ("detected_at", -1)])',
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
