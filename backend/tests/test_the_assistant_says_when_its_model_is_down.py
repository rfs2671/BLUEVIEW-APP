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
    with patch.object(server, "db", db), patch.object(server, "LLM_API_KEY", "k"), \
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
        self.assertIn("balance exhausted", alerts[0]["subject"])
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



class EveryUserFacingCallerAlerts(unittest.TestCase):
    """Every OpenAI call a person is waiting on (the census in the PR body):
    a forced 429 credit_balance_exhausted raises the same hourly alert,
    naming where it was seen, and the caller then does exactly what it did
    before (its own fallback)."""

    def _forced(self, call):
        self.assertTrue(hasattr(server, "_alert_if_model_refused"), "no refusal check (main)")
        status, body = QUOTA

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

            async def post(self, *a, **k):
                return _Resp()

        alerts = []

        async def _notify(db, **kw):
            alerts.append(kw)
            return {}

        db = _db()
        db.users.rows.append({"_id": "op1", "email": "ops@example.com", "is_platform_operator": True})

        async def _scope(*a, **k):
            return True

        with patch.object(server, "db", db), patch.object(server, "LLM_API_KEY", "k"), \
                patch.object(server, "ServerHttpClient", _Client), \
                patch.object(server, "_bot_project_scope", _scope), \
                patch.object(server.punch_brain, "user_message", lambda state, said: "x"), \
                patch("lib.notifications.send_notification", _notify), TestCaseLogs() as logs:
            out = _run(call())
        return out, alerts, logs.lines

    def _check(self, call, where, expect):
        out, alerts, logs = self._forced(call)
        self.assertEqual(out, expect, where)
        self.assertEqual(len(alerts), 1, where)
        self.assertIn(f"First seen this hour in: {where}.", alerts[0]["text"])
        self.assertTrue(any(f"in {where}" in line and "[agent-model-down] billing" in line for line in logs), logs)

    def test_dm_routing(self):
        from lib import wa_assistant
        self._check(lambda: server._dm_scope("hmm what about tomorrow then"),
                    "DM question routing", wa_assistant.SCOPE_PROJECT)

    def test_dm_answer(self):
        self._check(lambda: server._dm_llm("system", "question"), "DM answer", None)

    def test_dm_subs(self):
        self._check(lambda: server._dm_subs_model([{"role": "user", "content": "q"}], "auto"),
                    "DM subs question", None)

    def test_dm_project_history(self):
        self._check(lambda: server._memory_llm([{"role": "user", "content": "q"}]),
                    "DM project-history answer", None)

    def test_dm_action(self):
        self._check(lambda: server._dm_action_model("remind me tomorrow", ["588"]), "DM action reading", None)

    def test_punch_walkthrough(self):
        self._check(lambda: server._punch_brain_model({}, "next"), "punch walkthrough", None)
        self._check(lambda: server._punch_batch_model("batch 2"), "punch walkthrough (batch)", None)
        self._check(lambda: server._punch_loc_model("4th floor 4A"), "punch walkthrough (location)", None)

    def test_checklist_from_a_conversation(self):
        self._check(lambda: server._extract_whatsapp_checklist("proj_w", "1@g.us", "make a checklist",
                                                               company_id=CO_A),
                    "checklist from a group conversation", None)

    def test_a_voice_note(self):
        # lib/voice_ingest's Whisper call, the pipeline's first model call:
        # its hook raises the alert; the note still fails as before.
        from lib import voice_ingest as vi
        status, body = QUOTA

        class _Resp:
            status_code = status
            text = str(body)

            def json(self):
                return body

            def raise_for_status(self):
                import httpx
                raise httpx.HTTPStatusError("429", request=None, response=self)

        class _Http:
            async def post(self, *a, **k):
                return _Resp()

        seen = []

        async def hook(st, b):
            seen.append((st, b))
        with patch.object(vi, "WHISPER_BACKOFF_SEC", 0):
            with self.assertRaises(Exception):
                _run(vi.transcribe_whisper(b"\x1aE\xdf\xa3" + b"0" * 64, openai_api_key="k",
                                           http_client=_Http(), model_refused=hook))
        self.assertTrue(seen)
        self.assertEqual(seen[0], (429, body))
        out, alerts, logs = self._forced(lambda: server._voice_model_refused(*QUOTA))
        self.assertEqual(len(alerts), 1)
        self.assertIn("First seen this hour in: voice note transcription.", alerts[0]["text"])


if __name__ == "__main__":
    unittest.main()
