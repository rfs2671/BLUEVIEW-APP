"""MR.8 — DOB approval watcher tests.

Coverage:
  • happy path: dob_log.expiration_date jumped past renewal.current_expiration
    → renewal transitions to completed, FilingJob audit_log gets
    renewal_confirmed_in_dob event, FilingJob.status flips to completed.
  • stuck-at-DOB: renewal.created_at older than 14 days AND no
    expiration jump yet → stuck_at_dob audit event appended exactly
    once on the FilingJob (re-running the watcher is a no-op).
  • no-change: expiration unchanged AND created_at recent → no audit
    appended, no transition.
  • missing dob_log: warning logged, renewal skipped (no transition).
  • per-renewal exception: one bad row's exception is caught; the
    cycle continues processing the rest.
  • no FilingJob present: renewal still transitions to completed, but
    the audit-append branch silently no-ops (legacy renewals are OK).
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
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


def _async_iter(items):
    async def gen(self):
        for it in items:
            yield it
    return gen


def _stub_renewal(
    *,
    _id="r1",
    permit_dob_log_id="dl1",
    current_expiration="2026-04-01",
    created_days_ago=2,
    company_id="co_a",
):
    return {
        "_id": _id,
        "permit_dob_log_id": permit_dob_log_id,
        "current_expiration": current_expiration,
        "created_at": datetime.now(timezone.utc) - timedelta(days=created_days_ago),
        "company_id": company_id,
        "status": "awaiting_dob_approval",
    }


def _build_db_mock(*, renewals, dob_log=None, filing_job=None):
    """Build a Mongo mock that supports the two find calls the watcher
    makes per renewal: dob_logs.find_one and filing_jobs.find_one
    (with sort kwarg). filing_jobs.update_one and permit_renewals.
    update_one are AsyncMocks so we can assert on call args."""
    mock_db = MagicMock()
    cursor = MagicMock()
    cursor.__aiter__ = _async_iter(renewals)
    mock_db.permit_renewals = MagicMock()
    mock_db.permit_renewals.find = MagicMock(return_value=cursor)
    mock_db.permit_renewals.update_one = AsyncMock()
    mock_db.dob_logs = MagicMock()
    mock_db.dob_logs.find_one = AsyncMock(return_value=dob_log)
    mock_db.filing_jobs = MagicMock()
    mock_db.filing_jobs.find_one = AsyncMock(return_value=filing_job)
    mock_db.filing_jobs.update_one = AsyncMock()
    return mock_db


# ── happy path ─────────────────────────────────────────────────────

class TestHappyPath(unittest.TestCase):

    def test_expiration_jumped_renewal_transitions_and_filing_job_updates(self):
        import server
        renewal = _stub_renewal(current_expiration="2026-04-01")
        new_dob_log = {"_id": "dl1", "expiration_date": "2027-04-01"}
        filing_job = {
            "_id": "fj1",
            "permit_renewal_id": "r1",
            "audit_log": [],
            "status": "filed",
        }
        mock_db = _build_db_mock(
            renewals=[renewal], dob_log=new_dob_log, filing_job=filing_job,
        )
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())

        # Renewal flipped to completed with new_expiration_date set.
        mock_db.permit_renewals.update_one.assert_awaited_once()
        ren_update = mock_db.permit_renewals.update_one.await_args.args[1]["$set"]
        self.assertEqual(ren_update["status"], "completed")
        self.assertEqual(ren_update["new_expiration_date"], "2027-04-01")
        self.assertIn("completed_at", ren_update)

        # FilingJob got the renewal_confirmed_in_dob event AND status=completed.
        mock_db.filing_jobs.update_one.assert_awaited_once()
        fj_update = mock_db.filing_jobs.update_one.await_args.args[1]
        self.assertEqual(fj_update["$set"]["status"], "completed")
        event = fj_update["$push"]["audit_log"]
        self.assertEqual(event["event_type"], "renewal_confirmed_in_dob")
        self.assertEqual(event["actor"], "dob_approval_watcher")
        self.assertEqual(event["metadata"]["old_expiration"], "2026-04-01")
        self.assertEqual(event["metadata"]["new_expiration"], "2027-04-01")

    def test_legacy_renewal_without_filing_job_still_transitions(self):
        """Renewals filed via the pre-MR.6 path don't have a FilingJob.
        The renewal should still transition; the FilingJob update path
        should silently no-op."""
        import server
        renewal = _stub_renewal()
        new_dob_log = {"_id": "dl1", "expiration_date": "2027-04-01"}
        mock_db = _build_db_mock(
            renewals=[renewal], dob_log=new_dob_log, filing_job=None,
        )
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())
        mock_db.permit_renewals.update_one.assert_awaited_once()
        # No FilingJob → no $push happened.
        mock_db.filing_jobs.update_one.assert_not_awaited()


# ── stuck-at-DOB ───────────────────────────────────────────────────

class TestStuckAtDob(unittest.TestCase):

    def test_stuck_event_appended_after_14_days(self):
        import server
        renewal = _stub_renewal(
            current_expiration="2026-04-01",
            created_days_ago=20,  # > 14
        )
        # dob_log expiration unchanged (DOB hasn't processed yet).
        same_dob_log = {"_id": "dl1", "expiration_date": "2026-04-01"}
        filing_job = {
            "_id": "fj1",
            "permit_renewal_id": "r1",
            "audit_log": [{"event_type": "filed", "timestamp": "2026-04-01"}],
            "status": "filed",
        }
        mock_db = _build_db_mock(
            renewals=[renewal], dob_log=same_dob_log, filing_job=filing_job,
        )
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())

        # Renewal NOT transitioned (still awaiting).
        mock_db.permit_renewals.update_one.assert_not_awaited()
        # FilingJob got the stuck_at_dob event.
        mock_db.filing_jobs.update_one.assert_awaited_once()
        ev = mock_db.filing_jobs.update_one.await_args.args[1]["$push"]["audit_log"]
        self.assertEqual(ev["event_type"], "stuck_at_dob")
        self.assertGreaterEqual(ev["metadata"]["days_stuck"], 14)

    def test_stuck_event_idempotent_on_second_run(self):
        """Running the watcher twice should NOT duplicate the
        stuck_at_dob event. The second run sees the existing event
        in audit_log and short-circuits."""
        import server
        renewal = _stub_renewal(created_days_ago=20)
        same_dob_log = {"_id": "dl1", "expiration_date": "2026-04-01"}
        # Simulate state AFTER first run: stuck event already in audit_log.
        filing_job_after_first_run = {
            "_id": "fj1",
            "permit_renewal_id": "r1",
            "audit_log": [
                {"event_type": "filed", "timestamp": "2026-04-01"},
                {"event_type": "stuck_at_dob", "timestamp": "2026-04-15"},
            ],
            "status": "filed",
        }
        mock_db = _build_db_mock(
            renewals=[renewal], dob_log=same_dob_log,
            filing_job=filing_job_after_first_run,
        )
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())
        # No new $push happened.
        mock_db.filing_jobs.update_one.assert_not_awaited()


# ── no-change ──────────────────────────────────────────────────────

class TestNoChange(unittest.TestCase):

    def test_recent_renewal_no_audit_appended(self):
        import server
        renewal = _stub_renewal(created_days_ago=3)  # under 14d threshold
        same_dob_log = {"_id": "dl1", "expiration_date": "2026-04-01"}
        filing_job = {
            "_id": "fj1", "permit_renewal_id": "r1",
            "audit_log": [], "status": "filed",
        }
        mock_db = _build_db_mock(
            renewals=[renewal], dob_log=same_dob_log, filing_job=filing_job,
        )
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())
        mock_db.permit_renewals.update_one.assert_not_awaited()
        mock_db.filing_jobs.update_one.assert_not_awaited()


# ── missing dob_log / unparseable dates ────────────────────────────

class TestSkipPaths(unittest.TestCase):

    def test_missing_dob_log_skipped_with_warning(self):
        import server
        renewal = _stub_renewal()
        mock_db = _build_db_mock(renewals=[renewal], dob_log=None)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())
        mock_db.permit_renewals.update_one.assert_not_awaited()
        mock_db.filing_jobs.update_one.assert_not_awaited()

    def test_renewal_without_permit_dob_log_id_skipped(self):
        import server
        renewal = _stub_renewal(permit_dob_log_id=None)
        mock_db = _build_db_mock(renewals=[renewal])
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())
        mock_db.permit_renewals.update_one.assert_not_awaited()

    def test_unparseable_expiration_skipped_no_transition(self):
        """If either expiration is malformed, the watcher skips
        rather than guessing."""
        import server
        renewal = _stub_renewal(current_expiration="not-a-date")
        garbage_dob_log = {"_id": "dl1", "expiration_date": "also-garbage"}
        mock_db = _build_db_mock(renewals=[renewal], dob_log=garbage_dob_log)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())
        mock_db.permit_renewals.update_one.assert_not_awaited()


# ── per-renewal exception isolation ────────────────────────────────

class TestPerRenewalExceptionIsolation(unittest.TestCase):

    def test_one_bad_row_doesnt_kill_cycle(self):
        """If processing one renewal raises, the next renewal in the
        cursor still gets processed."""
        import server
        bad_renewal = _stub_renewal(_id="r_bad")
        good_renewal = _stub_renewal(
            _id="r_good", current_expiration="2026-04-01"
        )
        new_dob_log = {"_id": "dl1", "expiration_date": "2027-04-01"}
        good_filing_job = {
            "_id": "fj_good", "permit_renewal_id": "r_good",
            "audit_log": [], "status": "filed",
        }

        mock_db = MagicMock()
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter([bad_renewal, good_renewal])
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find = MagicMock(return_value=cursor)
        mock_db.permit_renewals.update_one = AsyncMock()
        mock_db.dob_logs = MagicMock()
        # First call (for r_bad) raises; second call (r_good) succeeds.
        mock_db.dob_logs.find_one = AsyncMock(
            side_effect=[RuntimeError("boom"), new_dob_log],
        )
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find_one = AsyncMock(return_value=good_filing_job)
        mock_db.filing_jobs.update_one = AsyncMock()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.dob_approval_watcher())

        # The good renewal still got transitioned despite the bad one.
        mock_db.permit_renewals.update_one.assert_awaited_once()
        good_set = mock_db.permit_renewals.update_one.await_args.args[1]["$set"]
        self.assertEqual(good_set["status"], "completed")


# ── _safe_parse_date helper ────────────────────────────────────────

class TestSafeParseDate(unittest.TestCase):

    def test_iso_string(self):
        from server import _safe_parse_date
        result = _safe_parse_date("2026-04-01")
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 4)
        self.assertEqual(result.day, 1)

    def test_us_format(self):
        from server import _safe_parse_date
        result = _safe_parse_date("4/1/2026")
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2026)

    def test_garbage_returns_none(self):
        from server import _safe_parse_date
        self.assertIsNone(_safe_parse_date("not-a-date"))

    def test_none_returns_none(self):
        from server import _safe_parse_date
        self.assertIsNone(_safe_parse_date(None))

    def test_passthrough_datetime(self):
        from server import _safe_parse_date
        dt = datetime(2026, 4, 1)
        self.assertEqual(_safe_parse_date(dt), dt)


if __name__ == "__main__":
    unittest.main()
