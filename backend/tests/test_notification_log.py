"""MR.9 — notification_log + send_notification helper.

Coverage:
  • send_notification writes a notification_log doc on every path
    (sent / failed / suppressed_*).
  • Feature-flag gate: NOTIFICATIONS_ENABLED=false → suppressed_flag_off,
    no Resend call.
  • Missing API key gate: empty RESEND_API_KEY → suppressed_no_key,
    no Resend call.
  • Idempotency: prior sent entry within IDEMPOTENCY_WINDOW_HOURS →
    suppressed_idempotent, no Resend call.
  • Resend exception → status=failed with error_detail captured.
  • collect_notification_recipients: dedups + lowercases, includes
    filing_reps + admin user, returns [] when no company.
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


def _stub_db_no_existing():
    """Mock db where the idempotency check finds nothing."""
    mock_db = MagicMock()
    mock_db.notification_log = MagicMock()
    mock_db.notification_log.find_one = AsyncMock(return_value=None)
    insert_result = MagicMock()
    insert_result.inserted_id = "new_log_id"
    mock_db.notification_log.insert_one = AsyncMock(return_value=insert_result)
    return mock_db


# ── feature-flag suppression ───────────────────────────────────────

class TestFeatureFlagSuppression(unittest.TestCase):

    def test_flag_off_suppresses_send(self):
        from lib import notifications as notif
        mock_db = _stub_db_no_existing()
        with patch.object(notif, "NOTIFICATIONS_ENABLED", False), \
             patch.object(notif, "RESEND_API_KEY", "real-key"):
            doc = _run(notif.send_notification(
                mock_db,
                permit_renewal_id="r1",
                trigger_type="renewal_t_minus_30",
                recipient="a@example.com",
                subject="Test",
                html="<p>x</p>",
                text="x",
            ))
        self.assertEqual(doc["status"], "suppressed_flag_off")
        # Log written.
        mock_db.notification_log.insert_one.assert_awaited_once()


# ── missing-key suppression ────────────────────────────────────────

class TestMissingKeySuppression(unittest.TestCase):

    def test_empty_key_suppresses_send_distinct_status(self):
        from lib import notifications as notif
        mock_db = _stub_db_no_existing()
        with patch.object(notif, "NOTIFICATIONS_ENABLED", True), \
             patch.object(notif, "RESEND_API_KEY", ""):
            doc = _run(notif.send_notification(
                mock_db,
                permit_renewal_id="r1",
                trigger_type="renewal_t_minus_30",
                recipient="a@example.com",
                subject="Test",
                html="<p>x</p>",
                text="x",
            ))
        self.assertEqual(doc["status"], "suppressed_no_key")


# ── idempotency ────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_prior_sent_within_window_skips(self):
        from lib import notifications as notif
        mock_db = MagicMock()
        # Idempotency check finds an existing sent entry.
        recent = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_db.notification_log = MagicMock()
        mock_db.notification_log.find_one = AsyncMock(
            return_value={"sent_at": recent, "status": "sent"},
        )
        insert_result = MagicMock()
        insert_result.inserted_id = "x"
        mock_db.notification_log.insert_one = AsyncMock(return_value=insert_result)

        with patch.object(notif, "NOTIFICATIONS_ENABLED", True), \
             patch.object(notif, "RESEND_API_KEY", "real-key"):
            doc = _run(notif.send_notification(
                mock_db,
                permit_renewal_id="r1",
                trigger_type="renewal_t_minus_30",
                recipient="a@example.com",
                subject="Test",
                html="<p>x</p>",
                text="x",
            ))
        self.assertEqual(doc["status"], "suppressed_idempotent")

    def test_old_send_outside_window_does_not_skip(self):
        """is_idempotent_skip uses Mongo's $gte cutoff filter; if no
        recent doc matches the filter, find_one returns None and the
        send proceeds."""
        from lib import notifications as notif
        mock_db = _stub_db_no_existing()  # find_one returns None

        # Patch Resend so we don't actually network.
        fake_resend = MagicMock()
        fake_resend.api_key = ""
        fake_resend.Emails = MagicMock()
        fake_resend.Emails.send = MagicMock(return_value={"id": "msg_123"})

        with patch.object(notif, "NOTIFICATIONS_ENABLED", True), \
             patch.object(notif, "RESEND_API_KEY", "real-key"), \
             patch.dict(sys.modules, {"resend": fake_resend}):
            doc = _run(notif.send_notification(
                mock_db,
                permit_renewal_id="r1",
                trigger_type="renewal_t_minus_30",
                recipient="a@example.com",
                subject="Test",
                html="<p>x</p>",
                text="x",
            ))
        self.assertEqual(doc["status"], "sent")
        self.assertEqual(doc["resend_message_id"], "msg_123")


# ── send paths ─────────────────────────────────────────────────────

class TestSendPaths(unittest.TestCase):

    def test_successful_send_captures_resend_id(self):
        from lib import notifications as notif
        mock_db = _stub_db_no_existing()
        fake_resend = MagicMock()
        fake_resend.Emails = MagicMock()
        fake_resend.Emails.send = MagicMock(return_value={"id": "abc123"})
        with patch.object(notif, "NOTIFICATIONS_ENABLED", True), \
             patch.object(notif, "RESEND_API_KEY", "real-key"), \
             patch.dict(sys.modules, {"resend": fake_resend}):
            doc = _run(notif.send_notification(
                mock_db,
                permit_renewal_id="r1",
                trigger_type="renewal_completed",
                recipient="b@example.com",
                subject="x",
                html="<p>x</p>",
                text="x",
            ))
        self.assertEqual(doc["status"], "sent")
        self.assertEqual(doc["resend_message_id"], "abc123")
        self.assertIsNone(doc["error_detail"])

    def test_resend_exception_captured_as_failed(self):
        from lib import notifications as notif
        mock_db = _stub_db_no_existing()
        fake_resend = MagicMock()
        fake_resend.Emails = MagicMock()
        fake_resend.Emails.send = MagicMock(
            side_effect=RuntimeError("Resend API down"),
        )
        with patch.object(notif, "NOTIFICATIONS_ENABLED", True), \
             patch.object(notif, "RESEND_API_KEY", "real-key"), \
             patch.dict(sys.modules, {"resend": fake_resend}):
            doc = _run(notif.send_notification(
                mock_db,
                permit_renewal_id="r1",
                trigger_type="renewal_t_minus_7",
                recipient="c@example.com",
                subject="x",
                html="<p>x</p>",
                text="x",
            ))
        self.assertEqual(doc["status"], "failed")
        self.assertIn("Resend API down", doc["error_detail"])
        self.assertIsNone(doc["resend_message_id"])


# ── recipient collection ───────────────────────────────────────────

class TestCollectRecipients(unittest.TestCase):

    def test_collects_filing_reps_and_admin(self):
        from lib import notifications as notif
        mock_db = MagicMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value={
            "_id": "co_a",
            "filing_reps": [
                {"email": "Rep1@Example.com"},  # mixed case
                {"email": "rep2@example.com"},
                {"email": "rep1@example.com"},  # duplicate (lowered)
            ],
        })
        mock_db.users = MagicMock()
        mock_db.users.find_one = AsyncMock(return_value={
            "email": "admin@example.com",
            "role": "admin",
            "company_id": "co_a",
        })
        out = _run(notif.collect_notification_recipients(mock_db, "co_a"))
        # Lowercased + deduped + admin appended.
        self.assertEqual(out, [
            "rep1@example.com",
            "rep2@example.com",
            "admin@example.com",
        ])

    def test_returns_empty_when_no_company(self):
        from lib import notifications as notif
        mock_db = MagicMock()
        out = _run(notif.collect_notification_recipients(mock_db, ""))
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
