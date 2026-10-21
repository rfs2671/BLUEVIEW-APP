"""Wed Oct 14, 10:11-10:13 AM DM.

  1. No morning brief arrived. A send WaAPI refused left the ledger row
     "failed", and every later tick read that as "already sent": nothing more
     that day. Now a failed (or stuck "sending") brief is tried again on the
     next tick, up to 3 times; every outcome is in brief_log with its reason
     or its whole error; "send me my brief" sends it now.
  2. brief_status: from the log only. No record -> "I can't see a brief sent
     to you today" -- never "it was sent".
  3. "Why didn't I get morning brief" is about the person: never "Which job?".
  4. "How many days has Arkon been on 588?" -> from the check-ins:
     "Arkon Builders: 23 days on site … (first Sep 14, last today), avg 10/day".
  5. The audit's tools: punch_status, follow_ups, upcoming_events; and the
     backstop when the model still says the data doesn't specify.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import wa_assistant, wa_dm, wa_facts  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx, _Wire  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, _Harness, _optin  # noqa: E402
from tests.test_whatsapp_morning_brief import (  # noqa: E402
    THU_7, WALWORTH, _run, _sends, _texts, _tick, _world,
)

NY = wa_facts.NY
# Wed Oct 14 2026, 10:12 AM New York.
WED = datetime(2026, 10, 14, 10, 12, tzinfo=NY).astimezone(timezone.utc)
THU = "2026-10-08"


def _log(db, uid="u_admin", day=THU):
    return db[wa_facts.BRIEF_LOG].rows and next(
        (r for r in db[wa_facts.BRIEF_LOG].rows if r["_id"] == f"{uid}:{day}"), None)


def _ledger(db, uid="u_admin", day=THU):
    """The whole brief's row."""
    key = wa_dm.ledger_key(uid, None, server.MORNING_BRIEF_KIND, day)
    return next((r for r in db[server.WA_LEDGER].rows if r["_id"] == key), None)


def _part(db, part, uid="u_admin", day=THU):
    """One message's row (a job's id, or wa_brief.REST)."""
    key = wa_dm.ledger_key(uid, None, server.MORNING_BRIEF_KIND,
                           server._brief_part_window(day, part))
    return next((r for r in db[server.WA_LEDGER].rows if r["_id"] == key), None)


# ══════════════════════════════════════════════════════════════════════════
# 1. The brief: a failed send is tried again; every outcome is logged
# ══════════════════════════════════════════════════════════════════════════

class TheBriefIsRetriedAndLogged(unittest.TestCase):

    def test_a_failed_send_goes_out_on_the_next_tick(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db, wire=_Wire([(400, {}, None)])) as c:
            r1 = _tick(c, THU_7)
            self.assertEqual(r1["failed"], 1)
            # The first message (8 Walworth St) failed, the second went out;
            # the brief is not "sent" until both are.
            self.assertEqual(_part(db, WALWORTH)["status"], "failed")
            self.assertEqual(_part(db, THOMAS)["status"], "sent")
            self.assertIsNone(_ledger(db))
            log = _log(db)
            self.assertEqual((log["status"], log["reason"], log["attempts"]),
                             ("failed", "send_failed", 1))
            self.assertIn("http 400", log["error"])
            # Before the fix: "already", and nothing more that day.
            r2 = _tick(c, THU_7 + timedelta(minutes=10))
        self.assertEqual((r2["sent"], r2["retried"], r2["already"]), (1, 1, 0))
        texts = _texts(c)
        self.assertEqual(len(texts), 3)             # the retry: the failed one alone
        self.assertEqual(texts[2], texts[0])
        self.assertIn("8 Walworth St", texts[2])
        self.assertEqual(_ledger(db)["status"], "sent")
        log = _log(db)
        self.assertEqual((log["status"], log["attempts"]), ("sent", 2))
        self.assertEqual([h["status"] for h in log["history"]], ["failed", "sent"])
        # And once sent, never again.
        with _Ctx(db) as c2:
            r3 = _tick(c2, THU_7 + timedelta(minutes=20))
        self.assertEqual((r3["already"], len(_sends(c2))), (1, 0))

    def test_a_send_stuck_in_sending_is_tried_again(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        key = wa_dm.ledger_key("u_admin", None, server.MORNING_BRIEF_KIND, THU)
        db[server.WA_LEDGER].rows.append({"_id": key, "status": "sending",
                                          "created_at": THU_7 - timedelta(minutes=30)})
        with _Ctx(db) as c:
            r = _tick(c, THU_7)
        self.assertEqual((r["sent"], len(_sends(c))), (1, 2))
        self.assertEqual(_ledger(db)["status"], "sent")

    def test_since_your_brief_is_its_first_message(self):
        db = _world()
        rows = [(f"{THU}:{WALWORTH}", 7), (f"{THU}:{THOMAS}", 9), (THU, 7)]
        db[server.WA_LEDGER].rows.extend(
            {"_id": f"r{m}{w}", "user_id": "u_admin", "kind": server.MORNING_BRIEF_KIND,
             "window": w, "status": "sent", "created_at": THU_7 + timedelta(minutes=m)}
            for w, m in rows)
        with _Ctx(db):
            at = _run(server._dm_brief_sent_today("u_admin", THU_7 + timedelta(hours=2)))
        self.assertEqual(at, THU_7 + timedelta(minutes=7))

    def test_a_failed_second_message_is_retried_alone(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        ok = (200, {"status": "success"}, None)
        with _Ctx(db, wire=_Wire([ok, (400, {}, None)])) as c:
            r1 = _tick(c, THU_7)
            self.assertEqual((r1["sent"], r1["failed"]), (0, 1))
            self.assertEqual(_part(db, WALWORTH)["status"], "sent")
            self.assertEqual(_part(db, THOMAS)["status"], "failed")
            self.assertIsNone(_ledger(db))           # not all out yet
            # Before its next try: nothing.
            _tick(c, THU_7 + timedelta(minutes=2))
            self.assertEqual(len(_sends(c)), 2)
            r2 = _tick(c, THU_7 + timedelta(minutes=10))
        self.assertEqual((r2["sent"], r2["retried"]), (1, 1))
        texts = _texts(c)
        self.assertEqual(len(texts), 3)
        self.assertEqual(texts[2], texts[1])         # the Thomas message, again
        self.assertIn("588 Thomas", texts[2])
        self.assertNotIn("Walworth", texts[2])
        # All out: the whole brief's row, stamped with its first message.
        row = _ledger(db)
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["created_at"], _part(db, WALWORTH)["created_at"])
        self.assertEqual(_log(db)["status"], "sent")
        with _Ctx(db) as c2:
            r3 = _tick(c2, THU_7 + timedelta(minutes=20))
        self.assertEqual((r3["already"], len(_sends(c2))), (1, 0))

    def test_new_is_since_the_last_whole_brief_not_a_message(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        yesterday = THU_7 - timedelta(days=1)
        db[server.WA_LEDGER].rows.extend([
            {"_id": "whole", "user_id": "u_admin", "kind": server.MORNING_BRIEF_KIND,
             "window": "2026-10-07", "status": "sent", "created_at": yesterday},
            {"_id": "part", "user_id": "u_admin", "kind": server.MORNING_BRIEF_KIND,
             "window": f"{THU}:{WALWORTH}", "status": "sent",
             "created_at": THU_7 - timedelta(minutes=5)}])
        with _Ctx(db):
            since = _run(server._brief_since("u_admin", THU_7))
        self.assertEqual(since, yesterday)

    def test_a_send_in_flight_is_left_alone(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        key = wa_dm.ledger_key("u_admin", None, server.MORNING_BRIEF_KIND, THU)
        db[server.WA_LEDGER].rows.append({"_id": key, "status": "sending",
                                          "created_at": THU_7 - timedelta(minutes=2)})
        with _Ctx(db) as c:
            r = _tick(c, THU_7)
        self.assertEqual((r["already"], len(_sends(c))), (1, 0))

    def test_a_silent_refusal_is_logged_with_its_reason(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        # The phone on the profile changed after START: send_whatsapp_dm
        # returned None and said nothing.
        next(u for u in db.users.rows if u["_id"] == "u_admin")["phone"] = "+15559990000"
        with _Ctx(db) as c:
            r = _tick(c, THU_7)
            text = _run(server._brief_status_for("u_admin", THU, THU_7 + timedelta(hours=2)))
        self.assertEqual((r["refused"], len(_sends(c))), (1, 0))
        self.assertEqual((_log(db)["status"], _log(db)["reason"]), ("refused", "phone_changed"))
        self.assertIn("was not sent", text)
        self.assertIn("phone on your profile changed", text)

    def test_an_error_building_it_is_logged_whole(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)

        async def boom(user, now):
            raise KeyError("due_at")
        with _Ctx(db) as c, patch.object(server, "_brief_for_user", boom), \
                self.assertLogs(server.logger, "ERROR") as logs:
            r = _tick(c, THU_7)
        self.assertEqual(r["failed"], 1)
        self.assertEqual((_log(db)["reason"], _log(db)["error"]), ("error", "KeyError: 'due_at'"))
        self.assertTrue(any("KeyError: 'due_at'" in m for m in logs.output))

    def test_the_error_survives_a_successful_retry(self):
        # Codex on #791: the history keeps each try's error.
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db, wire=_Wire([(400, {}, None)])) as c:
            _tick(c, THU_7)
            _tick(c, THU_7 + timedelta(minutes=10))
        hist = _log(db)["history"]
        self.assertEqual([(h["status"], h["error"]) for h in hist],
                         [("failed", "http 400 (send-message)"), ("sent", None)])

    def test_shabbos_skip_and_no_jobs_are_logged(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)

        async def quiet(*a, **k):
            return THU_7 + timedelta(hours=10)
        with _Ctx(db) as c, patch.object(server, "_shabbos_quiet", quiet):
            _tick(c, THU_7)
            text = _run(server._brief_status_for("u_admin", THU, THU_7))
        self.assertEqual((_log(db)["status"], _log(db)["reason"]), ("skipped", "shabbos"))
        self.assertIn("Shabbos", text)


def _ny(h, m=0):
    """Thu Oct 8 2026 (the test world's day), New York time."""
    return datetime(2026, 10, 8, h, m, tzinfo=NY).astimezone(timezone.utc)


class TheRetryPolicy(unittest.TestCase):
    """Wed Oct 14 in prod: WaAPI send-message answered 500 at 8:05; the
    ledger said "failed" and nothing more happened that day."""

    def setUp(self):
        self.db = _world()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        self.db.notification_preferences.rows.append(
            {"_id": "np", "user_id": "u_admin", "project_id": None,
             "whatsapp": {"brief_time": "08:00"}})
        self.db.users.rows.append({"_id": "op", "is_platform_operator": True,
                                   "email": "ops@levelog.test"})
        self.emails = []

    def _ticks(self, wire, times):
        async def email(db, **kw):
            self.emails.append(kw)
            return {"status": "sent"}
        tried = []
        with _Ctx(self.db, wire=wire) as c, \
                patch("lib.notifications.send_notification", email):
            for t in times:
                before = len(_sends(c))
                _tick(c, t)
                if len(_sends(c)) > before:
                    tried.append(t)
        return c, tried

    def test_the_500_at_805_goes_out_on_the_next_try_and_once(self):
        five_hundred = (500, {"_text": "<html>Internal Server Error</html>"}, None)
        c, tried = self._ticks(_Wire([five_hundred] * wa_dm.DM_SEND_ATTEMPTS),
                               [_ny(8, 5), _ny(8, 7), _ny(8, 15), _ny(8, 25), _ny(9, 0)])
        self.assertEqual(tried, [_ny(8, 5), _ny(8, 15)])   # 8:07 waits for 8:10
        self.assertEqual(_ledger(self.db)["status"], "sent")
        log = _log(self.db)
        self.assertEqual([h["status"] for h in log["history"]], ["failed", "sent"])
        # 1. which call, its status and what WaAPI said:
        self.assertEqual(log["history"][0]["error"],
                         "http 500 (send-message): {\"_text\":\"<html>Internal Server Error</html>\"}")
        self.assertEqual(self.emails, [])

    def test_backoff_5_15_30_until_the_window_closes_then_one_alert(self):
        c, tried = self._ticks(_Wire([(400, {"error": "boom"}, None)] * 40),
                               [_ny(8, 5) + timedelta(minutes=5 * i) for i in range(40)])
        self.assertEqual([wa_facts._clock(t) for t in tried],
                         ["8:05", "8:10", "8:25", "8:55", "9:25", "9:55", "10:25", "10:55"])
        log = _log(self.db)
        self.assertTrue(log["final"])
        self.assertEqual(log["attempts"], 8)
        # 4. one operator alert, a row for the owner portal, and the status:
        self.assertEqual(len(self.emails), 1)
        self.assertEqual(self.emails[0]["permit_renewal_id"], f"send_failed:morning_brief:u_admin:{THU}")
        fail = self.db[server.SEND_FAILURES].rows[0]
        self.assertEqual((fail["kind"], fail["attempts"]), ("morning_brief", 8))
        self.assertIn("http 400 (send-message)", fail["error"])
        with _Ctx(self.db):
            text = _run(server._brief_status_for("u_admin", THU, _ny(11, 30)))
        self.assertEqual(text, 'Sending failed at 8:05 (WhatsApp error). '
                               'Say "send me my brief" to try again.')

    def test_a_brief_that_cannot_be_built_follows_the_same_policy(self):
        calls = []

        async def boom(user, now):
            calls.append(now)
            raise KeyError("due_at")
        with patch.object(server, "_brief_for_user", boom), self.assertLogs(server.logger, "ERROR"):
            self._ticks(_Wire(), [_ny(8, 5), _ny(8, 7), _ny(8, 15), _ny(8, 20), _ny(8, 30)])
        self.assertEqual([wa_facts._clock(t) for t in calls], ["8:05", "8:15", "8:30"])
        self.assertEqual(_log(self.db)["reason"], "error")


class TheLedgerNeverBlocksARetry(unittest.TestCase):
    """5. Every DM: a "failed" claim (or one stuck "sending") is taken over
    by the next send; a sent one still blocks."""

    def _send(self, c):
        return _run(server.send_whatsapp_dm("u_admin", "hello", kind="morning_brief",
                                            window="2026-10-08"))

    def test_failed_then_sent_then_blocked(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db, wire=_Wire([(400, {}, None)])) as c:
            self.assertIsNone(self._send(c))
            self.assertEqual(_ledger(db)["status"], "failed")
            self.assertIsNotNone(self._send(c))
            self.assertEqual(_ledger(db)["status"], "sent")
            self.assertIsNone(self._send(c))          # never twice
        self.assertEqual(len(_sends(c)), 2)
        self.assertEqual(_ledger(db)["tries"], 1)

    def test_a_stale_sending_claim_is_taken_over(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        key = wa_dm.ledger_key("u_admin", None, "morning_brief", "2026-10-08")
        db[server.WA_LEDGER].rows.append({"_id": key, "status": "sending",
                                          "created_at": datetime.now(timezone.utc) - timedelta(hours=1)})
        with _Ctx(db) as c:
            self.assertIsNotNone(self._send(c))

    def test_a_fresh_sending_claim_blocks(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        key = wa_dm.ledger_key("u_admin", None, "morning_brief", "2026-10-08")
        db[server.WA_LEDGER].rows.append({"_id": key, "status": "sending",
                                          "created_at": datetime.now(timezone.utc)})
        with _Ctx(db) as c:
            self.assertIsNone(self._send(c))
        self.assertEqual(_sends(c), [])


class TheErrorText(unittest.TestCase):

    def test_waapi_error(self):
        from lib import send_retry
        self.assertEqual(send_retry.waapi_error("send-message", 500, {"_text": "Bad Gateway"}, None),
                         'http 500 (send-message): {"_text":"Bad Gateway"}')
        self.assertEqual(send_retry.waapi_error("send-message", 500, {}, None),
                         "http 500 (send-message)")
        self.assertEqual(send_retry.waapi_error("send-message", None, None, TimeoutError()),
                         "TimeoutError (send-message)")
        said = send_retry.waapi_error("send-message", 400,
                                      {"error": "chat 15550001234@c.us not found"}, None)
        self.assertNotIn("15550001234", said)
        self.assertIn("[number]", said)

    def test_the_schedule(self):
        from lib import send_retry
        t = _ny(8, 5)
        self.assertEqual([send_retry.next_try(n, t) - t for n in (1, 2, 3, 4, 9)],
                         [timedelta(minutes=m) for m in (5, 15, 30, 30, 30)])
        self.assertTrue(send_retry.is_final(4, _ny(10, 40), _ny(11)))
        self.assertFalse(send_retry.is_final(4, _ny(10, 25), _ny(11)))


# ══════════════════════════════════════════════════════════════════════════
# 2. brief_status: the log, or "I can't see" -- never a guess
# ══════════════════════════════════════════════════════════════════════════

class BriefStatus(unittest.TestCase):

    def test_sent_says_when(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, THU_7)
            text = _run(server._brief_status_for("u_admin", None, THU_7 + timedelta(hours=3)))
        self.assertEqual(text, "Today's brief went out at 7:05 AM.")

    def test_a_stored_time_is_utc_on_any_machine(self):
        # Oct 20: sent 8:03:50 AM ET, stored naive (Mongo) -- shown as "12:03 PM"
        # on an Eastern machine, which read it in its own zone.
        sent = datetime(2026, 10, 20, 12, 3, 50)                       # naive UTC, as stored
        now = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            if hasattr(__import__("time"), "tzset"):
                __import__("time").tzset()
            text = wa_facts.brief_status_text({"status": "sent", "at": sent}, None,
                                              {"brief_time": "08:00"}, now, date(2026, 10, 20))
        if hasattr(__import__("time"), "tzset"):
            __import__("time").tzset()
        self.assertEqual(text, "Today's brief went out at 8:03 AM.")

    def test_no_record_is_never_a_guess(self):
        s = {"brief_time": "07:00"}
        text = wa_facts.brief_status_text(None, None, s, WED, WED.astimezone(NY).date())
        self.assertTrue(text.startswith("I can't see a brief sent to you today."))
        self.assertNotIn("went out", text)

    def test_before_its_time(self):
        early = datetime(2026, 10, 14, 6, 30, tzinfo=NY).astimezone(timezone.utc)
        text = wa_facts.brief_status_text(None, None, {"brief_time": "08:00"}, early,
                                          early.astimezone(NY).date())
        self.assertEqual(text, "Your brief is set for 8:00 AM — it hasn't gone out yet today.")

    def test_the_raw_error_never_reaches_the_user(self):
        # Codex on #791: the reason in words; the error stays in the log.
        text = wa_facts.brief_status_text(
            {"status": "failed", "reason": "error", "error": "KeyError: 'due_at' at mongodb://x"},
            None, {"brief_time": "08:00"}, WED, WED.astimezone(NY).date())
        self.assertNotIn("KeyError", text)
        self.assertNotIn("mongodb", text)
        self.assertIn("could not be put together", text)

    def test_a_failed_ledger_row_alone(self):
        # The diag on Wed Oct 14: ledger failed, created 8:04:59, finished
        # 8:05:43, http 500, no brief_log row. Was "Today's brief was not
        # sent: it was not sent."
        led = {"status": "failed", "error": "http 500",
               "created_at": datetime(2026, 10, 14, 8, 4, 59, tzinfo=NY),
               "finished_at": datetime(2026, 10, 14, 8, 5, 43, tzinfo=NY)}
        text = wa_facts.brief_status_text(None, led, {"brief_time": "08:00"}, WED,
                                          WED.astimezone(NY).date())
        self.assertEqual(text, 'Sending failed at 8:05 (WhatsApp error). '
                               'Say "send me my brief" to try again.')

    def test_while_a_retry_is_pending(self):
        log = {"status": "failed", "reason": "send_failed", "attempts": 1,
               "first_failed_at": datetime(2026, 10, 14, 8, 5, tzinfo=NY),
               "next_try_at": datetime(2026, 10, 14, 8, 10, tzinfo=NY), "final": False}
        self.assertEqual(
            wa_facts.brief_status_text(log, None, {"brief_time": "08:00"}, WED, WED.astimezone(NY).date()),
            'Sending failed at 8:05 (WhatsApp error). I\'ll try again at 8:10. '
            'Say "send me my brief" to try again.')

    def test_a_refusal_without_a_reason_never_repeats_itself(self):
        text = wa_facts.brief_status_text({"status": "refused"}, None, {"brief_time": "08:00"},
                                          WED, WED.astimezone(NY).date())
        self.assertNotIn("not sent: it was not sent", text)
        self.assertTrue(text.startswith("I can't see why today's brief wasn't sent."))

    def test_off(self):
        text = wa_facts.brief_status_text(None, None, {"brief_time": "off"}, WED,
                                          WED.astimezone(NY).date())
        self.assertIn("set to Off", text)


# ══════════════════════════════════════════════════════════════════════════
# 3. Questions about the person: never "Which job?"
# ══════════════════════════════════════════════════════════════════════════

class UserLevel(_Harness, unittest.TestCase):

    def test_topics(self):
        cases = {
            "Why didnt I get morning brief": "brief",
            "why didn't I get my brief?": "brief",
            "did the brief go out": "brief",
            "where is my morning brief": "brief",
            "I never got the brief": "brief",
            "send me my brief": "send_brief",
            "resend the morning brief": "send_brief",
            "Can you send me today's brief again": "send_brief",
            "what time is my brief": "settings",
            "what are my notification settings": "settings",
            "how many days has arkon been on 588": None,
            "what did the brief say about permits": None,
            "who's on site at 588": None,
            "who came in after the brief at 588 thomas": None,
            "anyone since your 8:07 brief?": None,
        }
        for text, want in cases.items():
            with self.subTest(text):
                self.assertEqual(wa_facts.user_topic(text), want)

    def test_why_no_brief_never_asks_which_job(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        today = datetime.now(timezone.utc).astimezone(NY).date().isoformat()
        db[wa_facts.BRIEF_LOG].rows.append({
            "_id": f"u_admin:{today}", "status": "failed", "reason": "send_failed",
            "error": "http 500", "at": datetime.now(timezone.utc)})
        with _Ctx(db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "Why didnt I get morning brief")
        self.assertNotIn("Which job", reply)
        self.assertTrue(reply.startswith("Sending failed at "), reply)
        self.assertTrue(reply.endswith('Say "send me my brief" to try again.'))
        self.assertEqual(self.agent_calls, [])

    def test_no_record_says_so(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        db.notification_preferences.rows.append(
            {"_id": "np", "user_id": "u_admin", "project_id": None,
             "whatsapp": {"brief_time": "off"}})
        with _Ctx(db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "did my brief go out today?")
        self.assertTrue(reply.startswith("I can't see a brief sent to you today"))

    def test_send_me_my_brief_sends_it_now_and_once(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "send me my brief")
        self.assertIn("588 Thomas", reply)
        self.assertEqual(self.agent_calls, [])
        today = datetime.now(timezone.utc).astimezone(NY).date().isoformat()
        self.assertEqual(_log(db, day=today)["status"], "resent")
        # The morning tick finds it sent.
        self.assertEqual(_ledger(db, day=today)["status"], "sent")

    def test_send_me_my_brief_sends_every_message(self):
        # More messages than the reply window's sends: the rest go out
        # through the opt-in, each with its own ledger row.
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        n = wa_dm.REPLY_WINDOW_MAX_SENDS + 2

        async def brief(user, now):
            return [(f"p{i}", f"message {i}") for i in range(n)] + [("rest", "the rest")]
        with _Ctx(db) as c, patch.object(server, "_brief_for_user", brief):
            self._send(c, f"{ADMIN_PHONE}@c.us", "send me my brief")
            # Asked again the same day: every message again.
            self._send(c, f"{ADMIN_PHONE}@c.us", "send me my brief", mid="D2")
        texts = _texts(c)
        want = [f"message {i}" for i in range(n)] + ["the rest"]
        self.assertEqual([t for t in texts if t in want], want + want)
        today = datetime.now(timezone.utc).astimezone(NY).date().isoformat()
        self.assertEqual(_log(db, day=today)["status"], "resent")
        self.assertEqual(_ledger(db, day=today)["status"], "sent")

    def test_settings(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "what are my notification settings")
        self.assertTrue(reply.startswith("Morning brief: 7:00 AM, Mon–Fri"))
        self.assertNotIn("Which job", reply)
        self.assertNotIn("turned off", reply)

    def test_settings_say_when_whatsapp_is_off(self):
        # Codex on #791: an opt-in with the master switch off sends nothing.
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)

        async def prefs(uid, project_id=None):
            return {"enabled": False}
        with _Ctx(db) as c, patch.object(server, "get_whatsapp_prefs", prefs):
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "what are my notification settings")
        self.assertIn("WhatsApp messages are turned off in your notification settings", reply)


# ══════════════════════════════════════════════════════════════════════════
# 4. sub_attendance
# ══════════════════════════════════════════════════════════════════════════

def _arkon_rows(company="Arkon Builders"):
    """Every weekday from Mon Sep 14 to Wed Oct 14 (23 days): 10 a day, 14 on
    Oct 2, 7 on Sep 21, 9 today -> avg 10."""
    days = [date(2026, 9, 14) + timedelta(days=i) for i in range(31)]
    days = [d for d in days if d.weekday() < 5]
    count = {d: 10 for d in days}
    count[date(2026, 10, 2)], count[date(2026, 9, 21)], count[date(2026, 10, 14)] = 14, 7, 9
    rows = []
    for d, n in count.items():
        at = datetime(d.year, d.month, d.day, 7, 30, tzinfo=NY).astimezone(timezone.utc)
        for w in range(n):
            # A worker who checks in twice the same day is counted once.
            rows.append({"_id": f"{d}-{w}", "project_id": THOMAS, "company_id": CO_A,
                         "worker_id": f"w{w}", "worker_company": company, "check_in_time": at})
        rows.append({"_id": f"{d}-again", "project_id": THOMAS, "company_id": CO_A,
                     "worker_id": "w0", "worker_company": company,
                     "check_in_time": at + timedelta(hours=4)})
    rows.append({"_id": "other", "project_id": THOMAS, "company_id": CO_A, "worker_id": "x",
                 "worker_company": "Power Direct", "check_in_time": WED})
    return rows, count


class SubAttendance(unittest.TestCase):

    def test_the_answer(self):
        rows, count = _arkon_rows()
        self.assertEqual((len(count), sum(count.values()) / len(count)), (23, 10.0))
        a = wa_facts.attendance(rows, WED, "arkon")
        self.assertEqual(
            wa_facts.attendance_text(a, WED, "arkon", "588 Thomas S Boyland St"),
            "Arkon Builders: 23 days on site at 588 Thomas S Boyland St (first Sep 14, last today), "
            "avg 10/day, most 14 on Oct 2; 9 today.")

    def test_names_as_said(self):
        names = ["Arkon Builders Inc", "Power Direct", "Good Plumbing LLC"]
        for said in ("arkon", "Arkon", "ARKON BUILDERS", "arkon builders inc", "arcon"):
            with self.subTest(said):
                self.assertEqual(wa_facts.match_companies(names, said), ["Arkon Builders Inc"])
        self.assertEqual(wa_facts.match_companies(names, "plumbing"), ["Good Plumbing LLC"])
        self.assertEqual(wa_facts.match_companies(names, "zzz"), [])

    def test_two_companies_ask_which(self):
        rows = [{"worker_id": "a", "worker_company": "Arkon Plumbing", "check_in_time": WED},
                {"worker_id": "b", "worker_company": "Arkon Electric", "check_in_time": WED}]
        a = wa_facts.attendance(rows, WED, "arkon")
        self.assertIn("Which one?", wa_facts.attendance_text(a, WED, "arkon"))

    def test_unknown_sub_and_a_range(self):
        rows, _ = _arkon_rows()
        a = wa_facts.attendance(rows, WED, "acme")
        self.assertEqual(wa_facts.attendance_text(a, WED, "acme", "588"),
                         "No check-ins at 588 from a company called 'acme'.")
        a = wa_facts.attendance(rows, WED, "arkon", date(2026, 10, 1), date(2026, 10, 5))
        # Thu, Fri, Mon (no one on the weekend).
        self.assertEqual((a["days"], a["max"], a["max_day"]), (3, 14, date(2026, 10, 2)))

    def test_the_tool_reads_the_jobs_check_ins(self):
        db = _world()
        db.checkins.rows[:] = _arkon_rows()[0]
        with _Ctx(db):
            text = _run(server._facts_tool("sub_attendance", {"sub": "arkon"}, company_id=CO_A,
                                           project_id=THOMAS, group_id=f"{ADMIN_PHONE}@c.us",
                                           now=WED))
        self.assertEqual(text, "Arkon Builders: 23 days (Sep 14 → today), 230 man-days, avg 10/day, "
                               "most 14 on Oct 2; 9 today.")

    def test_another_companys_job_is_refused(self):
        db = _world()
        with _Ctx(db):
            text = _run(server._facts_tool("sub_attendance", {"sub": "arkon"}, company_id="co_b",
                                           project_id=THOMAS, group_id=f"{ADMIN_PHONE}@c.us"))
        self.assertNotIn("Arkon", text)


# ══════════════════════════════════════════════════════════════════════════
# 5. The audit: the other tools, and the backstop
# ══════════════════════════════════════════════════════════════════════════

class TheOtherTools(unittest.TestCase):

    def test_registered_and_where(self):
        names = {t["function"]["name"] for t in server._AGENT_TOOLS}
        self.assertTrue({"sub_attendance", "punch_status", "follow_ups", "upcoming_events",
                         "brief_status"} <= names)
        self.assertEqual(set(server._DM_ONLY_FACT_TOOLS), {"follow_ups", "brief_status"})

    def test_group_never_reads_follow_ups_or_the_brief(self):
        db = _world()
        with _Ctx(db):
            for name in ("follow_ups", "brief_status"):
                with self.subTest(name):
                    text = _run(server._facts_tool(name, {}, company_id=CO_A,
                                                   project_id=THOMAS, group_id="1@g.us"))
                    self.assertIn("direct message only", text)

    def test_punch(self):
        rows = [{"status": "open", "assignee": {"name": "Dave", "company": "Arkon"}, "pid": "P-1",
                 "created_at": WED - timedelta(days=5)},
                {"status": "open", "assignee": {"name": "Dave", "company": "Arkon"}, "pid": "P-2",
                 "created_at": WED - timedelta(days=1)},
                {"status": "ready_to_check", "assignee": {"name": "Sam"}, "pid": "P-3"},
                {"status": "closed", "pid": "P-4"}, {"status": "dropped", "pid": "P-5"}]
        self.assertEqual(wa_facts.punch_text(rows, WED, job="588"),
                         "Punch at 588: 2 open, 1 ready to check, 1 closed.\n"
                         "• Dave: 2 open (oldest Oct 9)\nReady to check: P-3")
        self.assertIn("No punch items at 588 for zed", wa_facts.punch_text(rows, WED, "zed", "588"))

    def test_follow_ups(self):
        items = [{"_id": "i1", "summary": "Send the sleeve shop drawings",
                  "owner": {"name": "Dave", "sub_company": "Arkon"}, "due": {"due_at": "2026-10-12"}},
                 {"_id": "i2", "summary": "Confirm Friday pour", "owner": {"name": "Ana"},
                  "due": {"due_at": "2026-10-16"}}]
        text = wa_facts.follow_ups_text(items, {"i1": WED - timedelta(days=1)}, WED, job="588")
        self.assertEqual(text, "2 open follow-ups at 588, 1 late:\n"
                               "• Dave: Send the sleeve shop drawings — ⚠️ 2 days late (chased yesterday)\n"
                               "• Ana: Confirm Friday pour — due Oct 16")
        self.assertTrue(wa_facts.follow_ups_text(items, {}, WED, "arkon").startswith("1 open"))

    def test_upcoming(self):
        ev = [{"date": "2026-10-15", "time": "9:00 AM", "title": "Plumbing inspection", "agency": "DOB"},
              {"date": "2026-10-13", "title": "past"},
              {"date": "2026-11-30", "title": "too far"},
              {"date": "2026-10-20", "title": "ECB hearing", "status": "cancelled"}]
        self.assertEqual(wa_facts.upcoming_text(ev, WED, 14, "588"),
                         "Coming up at 588:\n• Oct 15 9:00 AM: Plumbing inspection (DOB)")


class TheBackstop(unittest.TestCase):

    def _answer(self, db, body, reply):
        async def agent(**kw):
            return reply
        ident = {"company_id": CO_A, "user_id": "u_admin", "role": "admin", "user": {}}
        project = next(p for p in db.projects.rows if p["_id"] == THOMAS)
        real = server._attendance_fallback

        async def on_wed(project, body, now=None):
            # The fixture's day: "today" is Wed Oct 14 whatever the clock says
            # (CI after midnight in New York read it as "yesterday").
            return await real(project, body, now=WED)
        with _Ctx(db), patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_attendance_fallback", on_wed):
            return _run(server._dm_answer_job(ident, project, f"{ADMIN_PHONE}@c.us", body, "m1"))

    def test_doesnt_specify_is_answered_from_check_ins(self):
        db = _world()
        db.checkins.rows[:] = _arkon_rows()[0]
        out = self._answer(db, "How many days has Arkon been on 588?",
                           "The data doesn't specify how many days Arkon has been on site.")
        self.assertTrue(out.startswith("Arkon Builders: 23 days (Sep 14 → today), 230 man-days"), out)

    def test_an_invented_brief_is_replaced_by_the_log(self):
        db = _world()
        out = self._answer(db, "did 588 get anything this morning",
                           "The morning brief for 588 was sent earlier today.")
        self.assertTrue(out.startswith("I can't see a brief sent to you today")
                        or out.startswith("Your brief is set for"), out)

    def test_detectors(self):
        self.assertTrue(wa_facts.about_attendance("How many days has Arkon been on 588?"))
        self.assertTrue(wa_facts.about_attendance("when did the plumber first start"))
        self.assertFalse(wa_facts.about_attendance("who's on site"))
        self.assertTrue(wa_facts.denies_data("The data doesn't specify that."))
        self.assertTrue(wa_facts.denies_data("I can't determine how long"))
        self.assertFalse(wa_facts.denies_data("Arkon: 23 days"))
        self.assertTrue(wa_facts.claims_brief("I sent you the brief at 8"))
        self.assertFalse(wa_facts.claims_brief("Arkon has 9 on site"))

    def test_the_prompt_says_so(self):
        self.assertIn("sub_attendance", wa_assistant.DM_AGENT_CLAUSE)
        self.assertIn("brief_status", wa_assistant.DM_AGENT_CLAUSE)


if __name__ == "__main__":
    unittest.main()
