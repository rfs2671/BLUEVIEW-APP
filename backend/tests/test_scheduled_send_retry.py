"""One retry policy for every scheduled message (Wed Oct 14 follow-up).

The morning brief's WaAPI 500 at 8:05 was never tried again. The same was
true of every other scheduled send: a punch reminder or a group summary that
failed was gone; a DOB / DOT alert was re-posted on every run with no
backoff and nobody told; an Upcoming DM was blocked for good by its failed
ledger row. Now each failed scheduled send goes on the shared queue
(_retry_later) and is tried again after 5, 15, then every 30 minutes
(lib/send_retry) until its window closes; never sent twice; the last
failure alerts an operator. Over Shabbos / Yom Tov a retry waits for after.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import shabbos, wa_dm  # noqa: E402
from tests import test_whatsapp_gc_alerts as G  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, _Ctx, _Wire  # noqa: E402
from tests.test_whatsapp_dm_assistant import _optin  # noqa: E402

WED = G.NOON                       # Wed Oct 7 2026, 11 AM New York: no quiet
FAIL = (500, {"_text": "Internal Server Error"}, None)


def _ny(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=shabbos.NY).astimezone(timezone.utc)


def _queue(db):
    return sorted(db[server.WA_QUIET_QUEUE].rows, key=lambda r: r["seq"])


class _Base(unittest.TestCase):

    def setUp(self):
        self.db = G._world()
        self.alerts = []

    def ctx(self, *responses):
        async def alert(kind, key, **kw):
            self.alerts.append((kind, kw))
        c = _Ctx(self.db, wire=_Wire(list(responses)))
        c._ps.append(patch.object(server, "_send_failed_alert", alert))
        return c

    def post(self, text, at):
        return G._run(server._quiet_or_send({"via": "chat", "chat_id": G.G_GC, "message": text},
                                            company_id=G.CO_A, project_id="proj_a",
                                            kind="punch_remind", now=at))

    def tick(self, at):
        return G._run(server._quiet_queue_tick(at))


class AScheduledGroupMessage(_Base):

    def test_a_failed_send_goes_out_5_minutes_later_once(self):
        with self.ctx(FAIL) as c:          # a group post is one try per send
            self.assertEqual(self.post("Your walkthrough draft isn't sent yet.", WED), "retrying")
            row = _queue(self.db)[0]
            self.assertEqual((row["retry"], row["attempts"], row["deliver_after"]),
                             (True, 1, WED + timedelta(minutes=5)))
            self.assertEqual(self.tick(WED + timedelta(minutes=3))["due"], 0)   # not yet
            self.assertEqual(self.tick(WED + timedelta(minutes=5))["sent"], 1)
            self.assertEqual(self.tick(WED + timedelta(minutes=30))["due"], 0)  # never twice
        texts = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertEqual(texts, ["Your walkthrough draft isn't sent yet."] * 2)
        self.assertEqual(self.alerts, [])

    def test_backoff_5_15_30_then_final_and_one_operator_alert(self):
        tries = []
        with self.ctx(*[FAIL] * 200) as c:
            self.post("summary", WED)
            tries.append(0)
            for m in range(5, 200, 5):
                before = len(c.wire.calls)
                self.tick(WED + timedelta(minutes=m))
                if len(c.wire.calls) > before:
                    tries.append(m)
        self.assertEqual(tries, [0, 5, 20, 50, 80])
        self.assertEqual(_queue(self.db)[0]["status"], "failed")
        self.assertEqual(len(self.alerts), 1)
        kind, kw = self.alerts[0]
        self.assertEqual((kind, kw["attempts"]), ("punch_remind", 5))
        self.assertEqual(kw["first_at"], WED)

    def test_a_retry_due_over_shabbos_waits_for_after(self):
        fri = _ny(2026, 10, 9, 17, 0)              # 5:00 PM; quiet from 5:08 PM
        with self.ctx(FAIL):
            self.assertEqual(self.post("summary", fri), "retrying")
            self.tick(fri + timedelta(minutes=10))  # 5:10 PM: Shabbos
            self.assertEqual(_queue(self.db)[0]["status"], "queued")
            sat_night = _ny(2026, 10, 10, 20, 30)
            self.assertEqual(self.tick(sat_night)["sent"], 1)

    def test_the_real_operator_alert(self):
        self.db.users.rows.append({"_id": "op", "is_platform_operator": True, "email": "ops@x.test"})
        emails = []

        async def email(db, **kw):
            emails.append(kw)
            return {"status": "sent"}
        with _Ctx(self.db), patch("lib.notifications.send_notification", email), \
                self.assertLogs(server.logger, "ERROR") as logs:
            G._run(server._send_failed_alert("gc_violation", "q1", company_id=G.CO_A,
                                             error="http 500 (send-message): chat 15550001234@c.us",
                                             first_at=WED, attempts=5, now=WED))
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0]["permit_renewal_id"], "send_failed:gc_violation:q1")
        self.assertNotIn("15550001234", emails[0]["text"])
        self.assertTrue(any("[send-failed] gc_violation" in m for m in logs.output))
        row = self.db[server.SEND_FAILURES].rows[0]
        self.assertEqual((row["kind"], row["attempts"]), ("gc_violation", 5))


class TheDeadline(_Base):
    """Codex on #792: never sent after its window closed."""

    def test_a_failure_too_close_to_the_deadline_is_final_at_once(self):
        late = _ny(2026, 10, 7, 23, 57)            # tonight's day-before DM, 11:57 PM
        with self.ctx():
            out = G._run(server._retry_later(
                {"via": "dm", "user_id": "u_admin", "message": "Tomorrow: inspection",
                 "kind": "upcoming_day_before", "window": "2026-10-08"},
                company_id=G.CO_A, project_id=None, kind="upcoming_day_before",
                deadline=server._ny_day_end(late), now=late))
        self.assertEqual(out, "failed")
        self.assertEqual(_queue(self.db), [])
        self.assertEqual([k for k, _ in self.alerts], ["upcoming_day_before"])

    def test_a_late_worker_never_sends_an_expired_retry(self):
        with self.ctx(FAIL) as c:
            self.post("summary", WED)                          # deadline WED + 2 h
            rep = self.tick(WED + timedelta(hours=3))           # the worker was down
        self.assertEqual(rep["sent"], 0)
        self.assertEqual(len([p for p in c.wire.calls if "message" in p]), 1)  # the first try only
        self.assertEqual(_queue(self.db)[0]["status"], "failed")
        self.assertEqual(len(self.alerts), 1)


class AnUpcomingDm(_Base):

    def test_a_failed_reminder_is_retried_and_sent_once(self):
        _optin(self.db, "u_admin", ADMIN_PHONE)
        with self.ctx(*[FAIL] * wa_dm.DM_SEND_ATTEMPTS) as c:
            sent = G._run(server.send_whatsapp_dm("u_admin", "Reminder: inspection",
                                                  kind="upcoming_reminder", window="r1"))
            self.assertIsNone(sent)
            self.assertTrue(G._run(server._dm_retry_if_failed(
                "u_admin", "Reminder: inspection", kind="upcoming_reminder", window="r1",
                company_id=G.CO_A, now=WED)))
            self.assertEqual(self.tick(WED + timedelta(minutes=5))["sent"], 1)
            self.assertEqual(self.tick(WED + timedelta(minutes=40))["due"], 0)
        key = wa_dm.ledger_key("u_admin", None, "upcoming_reminder", "r1")
        led = next(r for r in self.db[server.WA_LEDGER].rows if r["_id"] == key)
        self.assertEqual(led["status"], "sent")
        delivered = [p for p in c.wire.calls if "message" in p]
        self.assertEqual(len(delivered), wa_dm.DM_SEND_ATTEMPTS + 1)

    def test_a_refusal_is_not_retried(self):
        # No opt-in: send_whatsapp_dm refused; there is nothing to retry.
        with self.ctx():
            self.assertFalse(G._run(server._dm_retry_if_failed(
                "u_admin", "Reminder", kind="upcoming_reminder", window="r2",
                company_id=G.CO_A, now=WED)))
        self.assertEqual(_queue(self.db), [])


class ADobAlert(_Base):

    def test_a_failed_alert_retries_on_the_schedule_and_never_posts_twice(self):
        with self.ctx(FAIL) as c, G._no_ai():
            G._confirm()
            G._run(server._gc_alerts_tick(G.NOON))                 # baseline
            self.db.dob_logs.rows.append(G._violation("2"))
            at = G.NOON + timedelta(hours=1)
            self.assertEqual(G._run(server._gc_alerts_tick(at))["failed"], 1)
            lid = _queue(self.db)[0]["send"]["gc_ledger_id"]

            def status():
                return next(r for r in self.db[server.WA_LEDGER].rows if r["_id"] == lid)["status"]
            self.assertEqual(status(), "retrying")
            # The alerts run does not post it again while it waits.
            G._run(server._gc_alerts_tick(at + timedelta(minutes=2)))
            self.assertEqual(self.tick(at + timedelta(minutes=5))["sent"], 1)
            self.assertEqual(status(), "sent")
            G._run(server._gc_alerts_tick(at + timedelta(minutes=30)))
        posts = [p for p in c.wire.calls if "Violation" in str(p.get("message"))]
        self.assertEqual(len(posts), 2)        # the failed one, then the one that went out

    def test_switched_off_while_waiting_never_posts(self):
        # Codex on #792 (P1): the retry re-checks the group's bot switch.
        with self.ctx(FAIL) as c, G._no_ai():
            G._confirm()
            G._run(server._gc_alerts_tick(G.NOON))
            self.db.dob_logs.rows.append(G._violation("3"))
            at = G.NOON + timedelta(hours=1)
            G._run(server._gc_alerts_tick(at))
            lid = _queue(self.db)[0]["send"]["gc_ledger_id"]
            for g in self.db.whatsapp_groups.rows:
                if g.get("wa_group_id") == G.G_GC:
                    g["bot_config"] = {**(g.get("bot_config") or {}), "bot_enabled": False}
            rep = self.tick(at + timedelta(minutes=5))
        self.assertEqual((rep["sent"], rep.get("bot_off")), (0, 1))
        self.assertEqual(len([p for p in c.wire.calls if "Violation" in str(p.get("message"))]), 1)
        led = next(r for r in self.db[server.WA_LEDGER].rows if r["_id"] == lid)
        self.assertEqual(led["status"], "seen_while_off")


if __name__ == "__main__":
    unittest.main()
