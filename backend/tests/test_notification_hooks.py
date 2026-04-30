"""MR.9 — watcher hooks fire notifications on stuck and completed.

Coverage:
  • dob_approval_watcher invokes _send_renewal_notification_hook with
    trigger='renewal_completed' when a renewal transitions to completed.
  • dob_approval_watcher invokes _send_renewal_notification_hook with
    trigger='filing_stuck' when a stuck_at_dob audit event is appended.
  • Hook never raises into the watcher cycle — a notification failure
    must not unset the renewal transition.
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


# ── Watcher → completed notification ───────────────────────────────

class TestCompletedHookFires(unittest.TestCase):

    def test_completed_transition_invokes_hook(self):
        import server
        renewal = {
            "_id": "r1",
            "permit_dob_log_id": "dl1",
            "current_expiration": "2026-04-01",
            "company_id": "co_a",
            "project_id": "p1",
            "created_at": datetime.now(timezone.utc) - timedelta(days=2),
        }
        new_dob_log = {"_id": "dl1", "expiration_date": "2027-04-01"}
        filing_job = {
            "_id": "fj1", "permit_renewal_id": "r1",
            "audit_log": [], "status": "filed",
        }

        mock_db = MagicMock()
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter([renewal])
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find = MagicMock(return_value=cursor)
        mock_db.permit_renewals.update_one = AsyncMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find_one = AsyncMock(return_value=new_dob_log)
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find_one = AsyncMock(return_value=filing_job)
        mock_db.filing_jobs.update_one = AsyncMock()

        hook_mock = AsyncMock()
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x), \
             patch.object(server, "_send_renewal_notification_hook", hook_mock):
            _run(server.dob_approval_watcher())

        hook_mock.assert_awaited_once()
        kwargs = hook_mock.await_args.kwargs
        self.assertEqual(kwargs["trigger_type"], "renewal_completed")
        self.assertEqual(kwargs["extra_context"]["new_expiration"], "2027-04-01")
        self.assertEqual(kwargs["extra_context"]["old_expiration"], "2026-04-01")


# ── Watcher → stuck notification ───────────────────────────────────

class TestStuckHookFires(unittest.TestCase):

    def test_stuck_event_invokes_hook(self):
        import server
        renewal = {
            "_id": "r1",
            "permit_dob_log_id": "dl1",
            "current_expiration": "2026-04-01",
            "company_id": "co_a",
            "project_id": "p1",
            "created_at": datetime.now(timezone.utc) - timedelta(days=20),
        }
        same_dob_log = {"_id": "dl1", "expiration_date": "2026-04-01"}
        filing_job = {
            "_id": "fj1", "permit_renewal_id": "r1",
            "audit_log": [], "status": "filed",
        }

        mock_db = MagicMock()
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter([renewal])
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find = MagicMock(return_value=cursor)
        mock_db.permit_renewals.update_one = AsyncMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find_one = AsyncMock(return_value=same_dob_log)
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find_one = AsyncMock(return_value=filing_job)
        mock_db.filing_jobs.update_one = AsyncMock()

        hook_mock = AsyncMock()
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x), \
             patch.object(server, "_send_renewal_notification_hook", hook_mock):
            _run(server.dob_approval_watcher())

        hook_mock.assert_awaited_once()
        kwargs = hook_mock.await_args.kwargs
        self.assertEqual(kwargs["trigger_type"], "filing_stuck")
        self.assertGreaterEqual(kwargs["extra_context"]["days_stuck"], 14)


# ── Hook failure is non-fatal ──────────────────────────────────────

class TestHookFailureNonFatal(unittest.TestCase):

    def test_hook_exception_does_not_unset_transition(self):
        import server
        renewal = {
            "_id": "r1",
            "permit_dob_log_id": "dl1",
            "current_expiration": "2026-04-01",
            "company_id": "co_a",
            "project_id": "p1",
            "created_at": datetime.now(timezone.utc) - timedelta(days=2),
        }
        new_dob_log = {"_id": "dl1", "expiration_date": "2027-04-01"}

        mock_db = MagicMock()
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter([renewal])
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find = MagicMock(return_value=cursor)
        mock_db.permit_renewals.update_one = AsyncMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find_one = AsyncMock(return_value=new_dob_log)
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find_one = AsyncMock(return_value=None)
        mock_db.filing_jobs.update_one = AsyncMock()

        # Hook raises — watcher must continue and NOT unset the
        # renewal update_one.
        async def _boom(*args, **kwargs):
            raise RuntimeError("Resend exploded")

        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x), \
             patch.object(server, "_send_renewal_notification_hook", _boom):
            _run(server.dob_approval_watcher())

        # Renewal still got transitioned despite hook failure.
        mock_db.permit_renewals.update_one.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
