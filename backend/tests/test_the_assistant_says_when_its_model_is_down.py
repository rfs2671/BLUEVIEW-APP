"""When the agent's model refuses for billing or auth, someone is told.

2026-10-26: the OpenAI account behind the WhatsApp assistant ran out of
credits. Every call answered 429 credit_balance_exhausted, _run_group_agent
logged it and returned None (NOREPLY), and the person who asked heard
nothing - nor did anyone who could fix it.

Now: an ERROR log line, one alert an hour to the platform operators through
the existing alert path, and a plain "temporarily unavailable" reply to
whoever addressed the assistant. A rate limit or a server error is not this
and keeps the old path.

Every test drives the real _run_group_agent with the model call stubbed; the
control run on main fails by assertion (main returns None and alerts no one).
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "smoke_test"),
             ("JWT_SECRET", "smoke_test_secret"), ("APP_BASE_URL", "https://app.levelog.com")):
    os.environ.setdefault(k, v)

import server  # noqa: E402
from tests.test_whatsapp_dm_assistant import _db, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A  # noqa: E402
from tests.test_whatsapp_dm_assistant import WALWORTH  # noqa: E402

QUOTA = (429, {"error": {"message": "You have no credits remaining.", "type": "insufficient_quota",
                         "param": None, "code": "credit_balance_exhausted"}})
BAD_KEY = (401, {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error",
                           "code": "invalid_api_key"}})
RATE = (429, {"error": {"message": "Rate limit reached", "type": "requests", "code": "rate_limit_exceeded"}})


def _agent(status_body, *, dm=True, explicit=True, calls=1):
    """Run the real agent `calls` times against a model that answers
    `status_body`; returns (replies, alerts, log lines)."""
    status, body = status_body

    class _Resp:
        status_code = status

        def json(self):
            return body

        def raise_for_status(self):
            raise RuntimeError(f"HTTP {status}")

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return _Resp()

    alerts = []

    async def _notify(db, **kw):
        alerts.append(kw)
        return {}

    db = _db()
    db.users.rows.append({"_id": "op1", "email": "ops@example.com", "is_platform_operator": True})
    replies = []
    with patch.object(server, "db", db), patch.object(server, "OPENAI_API_KEY", "k"), \
            patch.object(server, "ServerHttpClient", _Client), \
            patch("lib.notifications.send_notification", _notify), \
            TestCaseLogs() as logs:
        for _ in range(calls):
            replies.append(_run(server._run_group_agent(
                project_id=WALWORTH, group_id=f"{ADMIN_PHONE}@c.us" if dm else "1@g.us",
                company_id=CO_A, sender=ADMIN_PHONE, body="who's on site",
                features=server._default_bot_config()["features"],
                explicit_mention=explicit, dm=dm)))
    return replies, alerts, logs.lines


class TestCaseLogs:
    """The server logger's lines, while the block runs."""

    def __enter__(self):
        import logging
        self.lines = []
        self._h = logging.Handler()
        self._h.emit = lambda rec: self.lines.append(rec.getMessage())
        server.logger.addHandler(self._h)
        return self

    def __exit__(self, *a):
        server.logger.removeHandler(self._h)
        return False


class TheCreditsRunOut(unittest.TestCase):

    def test_the_person_who_asked_is_told(self):
        replies, _alerts, _logs = _agent(QUOTA)
        self.assertEqual(len(replies), 1)
        self.assertIsNotNone(replies[0], "silence: the person who asked heard nothing")
        self.assertIn("temporarily unavailable", replies[0])

    def test_the_operators_are_alerted_and_it_is_logged(self):
        _replies, alerts, logs = _agent(QUOTA)
        self.assertEqual([a["recipient"] for a in alerts], ["ops@example.com"])
        self.assertEqual(alerts[0]["trigger_type"], "agent_model_unavailable")
        self.assertIn("credits", alerts[0]["subject"])
        self.assertIn("credit_balance_exhausted", alerts[0]["text"])
        self.assertTrue(any("[agent-model-down]" in line and "billing" in line for line in logs), logs)

    def test_once_an_hour(self):
        # Three failures in the hour: one notification id, which the alert
        # path's own idempotency (lib/notifications) sends once.
        _replies, alerts, _logs = _agent(QUOTA, calls=3)
        self.assertEqual(len({a["permit_renewal_id"] for a in alerts}), 1)
        from lib import model_outage
        h1 = datetime(2026, 10, 26, 13, 5, tzinfo=timezone.utc)
        h1b = datetime(2026, 10, 26, 13, 55, tzinfo=timezone.utc)
        h2 = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(model_outage.alert_key("billing", h1), model_outage.alert_key("billing", h1b))
        self.assertNotEqual(model_outage.alert_key("billing", h1), model_outage.alert_key("billing", h2))
        self.assertNotEqual(model_outage.alert_key("billing", h1), model_outage.alert_key("auth", h1))

    def test_a_group_message_not_for_the_bot_stays_silent_but_alerts(self):
        replies, alerts, _logs = _agent(QUOTA, dm=False, explicit=False)
        self.assertEqual(replies, [None])
        self.assertEqual(len(alerts), 1)

    def test_addressed_in_a_group_it_answers(self):
        replies, _alerts, _logs = _agent(QUOTA, dm=False, explicit=True)
        self.assertIn("temporarily unavailable", replies[0] or "")


class AKeyItWillNotTake(unittest.TestCase):

    def test_401_alerts_as_auth(self):
        replies, alerts, logs = _agent(BAD_KEY)
        self.assertIn("temporarily unavailable", replies[0] or "")
        self.assertEqual(len(alerts), 1)
        self.assertIn("key", alerts[0]["subject"])
        self.assertTrue(any("[agent-model-down] auth" in line for line in logs), logs)


class NotThisFailure(unittest.TestCase):

    def test_a_rate_limit_keeps_the_old_path(self):
        replies, alerts, logs = _agent(RATE)
        self.assertEqual(replies, [None])
        self.assertEqual(alerts, [])
        self.assertFalse(any("[agent-model-down]" in line for line in logs))
        self.assertTrue(any("group agent error" in line for line in logs), logs)

    def test_the_classifier(self):
        self.assertTrue(hasattr(server, "model_outage"), "no outage classifier (main)")
        mo = server.model_outage
        self.assertEqual(mo.classify(*QUOTA), mo.BILLING)
        self.assertEqual(mo.classify(429, {"error": {"type": "insufficient_quota"}}), mo.BILLING)
        self.assertEqual(mo.classify(*BAD_KEY), mo.AUTH)
        self.assertEqual(mo.classify(401, None), mo.AUTH)
        self.assertIsNone(mo.classify(*RATE))
        self.assertIsNone(mo.classify(500, {"error": {"type": "server_error"}}))
        self.assertIsNone(mo.classify(400, "not json"))


if __name__ == "__main__":
    unittest.main()
