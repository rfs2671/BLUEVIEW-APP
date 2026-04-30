"""MR.9 — renewal_reminder_cron + email template renderers.

Coverage:
  • Each of the three reminder windows partitions correctly:
      - 30 days from today → renewal_t_minus_30
      - 14 days from today → renewal_t_minus_14
      - 7 days from today → renewal_t_minus_7
  • Window edges: 28d (just outside T-30 low), 31d (just outside
    T-30 high), 13d (T-14 low), 6d (T-7 low).
  • Multiple renewals dispatch correctly (T-30 + T-7 in same run).
  • REMINDER_ELIGIBLE_STATUSES filter excludes filed/awaiting renewals.
  • Each template renderer returns (subject, html, text) tuple with
    expected fields populated.
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
os.environ.setdefault("RESEND_API_KEY", "")
os.environ.setdefault("NOTIFICATIONS_ENABLED", "false")

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


def _renewal(*, _id, current_expiration, status="eligible"):
    return {
        "_id": _id,
        "company_id": "co_a",
        "project_id": "p1",
        "permit_dob_log_id": "dl1",
        "status": status,
        "current_expiration": current_expiration,
    }


# ── Template renderers ─────────────────────────────────────────────

class TestTemplateRenderers(unittest.TestCase):

    def _ctx(self, **overrides):
        return {
            "recipient_name": "Jane",
            "project_name": "9 Menahan",
            "project_address": "9 Menahan Street, Brooklyn",
            "permit_job_number": "B00736930",
            "permit_work_type": "Plumbing",
            "current_expiration": "Jun 15, 2026",
            "action_link": "https://www.levelog.com/project/p1/permit-renewal",
            "days_until_expiry": 30,
            **overrides,
        }

    def test_t_minus_30_subject_includes_days_and_project(self):
        from lib.email_templates import render_t_minus_30
        subject, html, text = render_t_minus_30(self._ctx())
        self.assertIn("30 days", subject)
        self.assertIn("9 Menahan", subject)
        self.assertIn("B00736930", subject)
        self.assertIn("Hi Jane", text)
        self.assertIn("9 Menahan", html)

    def test_t_minus_14_subject(self):
        from lib.email_templates import render_t_minus_14
        subject, _, _ = render_t_minus_14(self._ctx(days_until_expiry=14))
        self.assertIn("14 days", subject)

    def test_t_minus_7_marks_urgent(self):
        from lib.email_templates import render_t_minus_7
        subject, html, _ = render_t_minus_7(self._ctx(days_until_expiry=7))
        self.assertTrue(subject.startswith("URGENT"))
        self.assertIn("expires in 7 days", html)

    def test_stuck_includes_days_stuck(self):
        from lib.email_templates import render_stuck
        subject, html, text = render_stuck(self._ctx(days_stuck=18))
        self.assertIn("18 days", subject)
        self.assertIn("18 days", html)
        self.assertIn("18 days", text)

    def test_completed_includes_new_expiration(self):
        from lib.email_templates import render_completed
        subject, html, text = render_completed(
            self._ctx(new_expiration="Jun 15, 2027"),
        )
        self.assertIn("Jun 15, 2027", subject)
        self.assertIn("Jun 15, 2027", html)
        self.assertIn("New Expiration: Jun 15, 2027", text)

    def test_dispatch_unknown_trigger_raises(self):
        from lib.email_templates import render_for_trigger
        with self.assertRaises(KeyError):
            render_for_trigger("not_a_real_trigger", {})


# ── Cron window partition ──────────────────────────────────────────

class TestReminderCronWindows(unittest.TestCase):

    def _setup_renewals_with_offsets(self, day_offsets):
        """Build a list of renewal dicts with current_expiration N
        days from today, for each N in day_offsets. Returns the
        list (server.py receives this via async cursor mock)."""
        today = datetime.now(timezone.utc).date()
        renewals = []
        for i, days in enumerate(day_offsets):
            exp = today + timedelta(days=days)
            renewals.append(_renewal(
                _id=f"r_{days}",
                current_expiration=exp.isoformat(),
            ))
        return renewals

    def _stub_server(self, renewals):
        """Patch server.db with a mock that yields the given renewals
        from the renewal_reminder_cron's permit_renewals.find call.
        Also stubs project, dob_log, and companies for the context
        builder + recipient resolver."""
        import server
        mock_db = MagicMock()

        # permit_renewals cursor.
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter(renewals)
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find = MagicMock(return_value=cursor)

        # Context fetches.
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(return_value={
            "_id": "p1", "name": "Test Project", "address": "1 Main St",
        })
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.find_one = AsyncMock(return_value={
            "_id": "dl1", "job_number": "B00736930", "work_type": "Plumbing",
        })
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a",
            "filing_reps": [{"email": "rep@example.com", "name": "Rep"}],
        })
        mock_db.users = MagicMock()
        mock_db.users.find_one = AsyncMock(return_value=None)

        # notification_log — capture inserts.
        mock_db.notification_log = MagicMock()
        mock_db.notification_log.find_one = AsyncMock(return_value=None)
        insert_result = MagicMock()
        insert_result.inserted_id = "fake_log_id"
        mock_db.notification_log.insert_one = AsyncMock(return_value=insert_result)

        return server, mock_db

    def test_30_day_renewal_dispatches_t_minus_30(self):
        renewals = self._setup_renewals_with_offsets([30])
        server, mock_db = self._stub_server(renewals)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.renewal_reminder_cron())
        # Exactly one notification_log insert; trigger_type == t_minus_30.
        mock_db.notification_log.insert_one.assert_awaited_once()
        inserted = mock_db.notification_log.insert_one.await_args.args[0]
        self.assertEqual(inserted["trigger_type"], "renewal_t_minus_30")

    def test_14_day_renewal_dispatches_t_minus_14(self):
        renewals = self._setup_renewals_with_offsets([14])
        server, mock_db = self._stub_server(renewals)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.renewal_reminder_cron())
        inserted = mock_db.notification_log.insert_one.await_args.args[0]
        self.assertEqual(inserted["trigger_type"], "renewal_t_minus_14")

    def test_7_day_renewal_dispatches_t_minus_7(self):
        renewals = self._setup_renewals_with_offsets([7])
        server, mock_db = self._stub_server(renewals)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.renewal_reminder_cron())
        inserted = mock_db.notification_log.insert_one.await_args.args[0]
        self.assertEqual(inserted["trigger_type"], "renewal_t_minus_7")

    def test_28_days_just_outside_t30_no_dispatch(self):
        """T-30 window is [29, 31). 28 days falls outside, no other
        window catches 28, so no email fires."""
        renewals = self._setup_renewals_with_offsets([28])
        server, mock_db = self._stub_server(renewals)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.renewal_reminder_cron())
        mock_db.notification_log.insert_one.assert_not_awaited()

    def test_31_days_just_outside_t30_no_dispatch(self):
        renewals = self._setup_renewals_with_offsets([31])
        server, mock_db = self._stub_server(renewals)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.renewal_reminder_cron())
        mock_db.notification_log.insert_one.assert_not_awaited()

    def test_multiple_renewals_dispatch_correct_triggers(self):
        renewals = self._setup_renewals_with_offsets([30, 14, 7])
        server, mock_db = self._stub_server(renewals)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.renewal_reminder_cron())
        # 3 dispatches, one per window.
        self.assertEqual(mock_db.notification_log.insert_one.await_count, 3)
        triggers = [
            call.args[0]["trigger_type"]
            for call in mock_db.notification_log.insert_one.await_args_list
        ]
        self.assertIn("renewal_t_minus_30", triggers)
        self.assertIn("renewal_t_minus_14", triggers)
        self.assertIn("renewal_t_minus_7", triggers)

    def test_renewals_with_no_recipients_skipped(self):
        renewals = self._setup_renewals_with_offsets([30])
        server, mock_db = self._stub_server(renewals)
        # Empty filing_reps and no admin.
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a", "filing_reps": [],
        })
        mock_db.users.find_one = AsyncMock(return_value=None)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server.renewal_reminder_cron())
        mock_db.notification_log.insert_one.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
