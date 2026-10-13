"""Shabbos / Yom Tov covers ALL bot messages, not just chasing.

For a job (or, for what belongs to no job, a company) with "Shabbos / Yom Tov
off", from one hour before New York candle-lighting to one hour after
nightfall nothing the bot sends on its own goes out:
  * it is QUEUED and delivered, in the order it was made, after the stretch;
  * the morning brief is skipped, not queued;
  * a day-before DM for an event inside the stretch (Friday 5 PM for
    Saturday) is skipped;
  * a Stop Work Order / Vacate alert still posts when the company turned on
    "Still send critical DOB alerts on Shabbos" (off by default);
  * someone who writes to the bot still gets an answer.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import shabbos, wa_alerts  # noqa: E402
from tests import test_upcoming_server as U  # noqa: E402
from tests import test_whatsapp_gc_alerts as G  # noqa: E402
from tests import test_whatsapp_morning_brief as B  # noqa: E402


def _ny(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=shabbos.NY).astimezone(timezone.utc)


# Fri Oct 9 2026: candles 6:08 PM -> quiet from 5:08 PM; Sat Oct 10:
# nightfall 7:07 PM -> quiet until 8:07 PM.
FRI_BEFORE, FRI_AFTER = _ny(2026, 10, 9, 16, 30), _ny(2026, 10, 9, 17, 30)
SAT_DAY, SAT_LATE, SAT_NIGHT = _ny(2026, 10, 10, 12), _ny(2026, 10, 10, 19, 50), _ny(2026, 10, 10, 20, 30)
# Yom Kippur, Mon Sep 21 2026 (a weekday): quiet Sun 5:40 PM to Mon ~8:39 PM.
YK_NOON, YK_TUE = _ny(2026, 9, 21, 12), _ny(2026, 9, 22, 12)


def _company(db, **wa):
    db[server.WA_COMPANY_SETTINGS].rows.append({"_id": G.CO_A, "company_id": G.CO_A,
                                                "whatsapp_company": wa})


def _queue(db):
    return sorted(db[server.WA_QUIET_QUEUE].rows, key=lambda r: r["seq"])


class TheWindow(unittest.TestCase):

    def test_friday_before_and_after_candle_lighting(self):
        self.assertIsNone(shabbos.quiet_until(FRI_BEFORE))
        end = shabbos.quiet_until(FRI_AFTER)
        self.assertEqual(end.astimezone(shabbos.NY).strftime("%a %-I:%M %p"), "Sat 8:07 PM")
        # December: candles 4:12 PM, so 3 PM still sends and 4 PM waits.
        self.assertIsNone(shabbos.quiet_until(_ny(2026, 12, 18, 15)))
        self.assertIsNotNone(shabbos.quiet_until(_ny(2026, 12, 18, 16)))

    def test_saturday_night_after_nightfall(self):
        self.assertIsNotNone(shabbos.quiet_until(SAT_LATE))      # after nightfall, < 1 h
        self.assertIsNone(shabbos.quiet_until(SAT_NIGHT))

    def test_a_yom_tov_weekday(self):
        self.assertEqual(shabbos.quiet_until(YK_NOON).astimezone(shabbos.NY).strftime("%a %-I:%M %p"),
                         "Mon 8:39 PM")
        self.assertIsNone(shabbos.quiet_until(YK_TUE))

    def test_critical(self):
        swo = {"kind": "swo", "rec": {}}
        vacate = {"kind": "violation", "rec": {"violation_subtype": "VACATE_FULL"}}
        vacate_text = {"kind": "violation", "rec": {"description": "FULL VACATE ORDER ISSUED"}}
        plain = {"kind": "violation", "rec": {"description": "Failure to maintain"}}
        lifted = {"kind": "swo_rescinded", "rec": {}}
        permit = {"kind": "permit", "rec": {"description": "stop work order"}}
        self.assertEqual([wa_alerts.is_critical(i) for i in (swo, vacate, vacate_text, plain, lifted, permit)],
                         [True, True, True, False, False, False])


class TheQueue(unittest.TestCase):
    """Queued in the order made, delivered once the stretch is over."""

    def setUp(self):
        self.db = G._world()
        self.sent = []

        async def msg(chat, text, *a, **k):
            self.sent.append(("chat", chat, text))
            return {"ok": True}

        async def dm(uid, text, **k):
            self.sent.append(("dm", uid, text))
            return {"ok": True}
        self.patches = [patch.object(server, "db", self.db),
                        patch.object(server, "send_whatsapp_message", msg),
                        patch.object(server, "send_whatsapp_dm", dm)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def send(self, text, at, project="proj_a"):
        return G._run(server._quiet_or_send({"via": "chat", "chat_id": G.G_GC, "message": text},
                                            company_id=G.CO_A, project_id=project, kind="test", now=at))

    def test_before_candle_lighting_sends_after_it_waits(self):
        self.assertEqual(self.send("Friday 4:30", FRI_BEFORE), {"ok": True})
        self.assertEqual(self.send("Friday 5:30", FRI_AFTER), "queued")
        self.assertEqual([t for _, _, t in self.sent], ["Friday 4:30"])

    def test_delivered_in_order_after_nightfall(self):
        self.send("first", FRI_AFTER)
        G._run(server._quiet_dm("u_admin", "second", company_id=G.CO_A, kind="upcoming_reminder",
                                window="r1", until=shabbos.quiet_until(SAT_DAY), now=SAT_DAY))
        self.send("third", SAT_LATE)
        self.assertEqual(len(_queue(self.db)), 3)
        self.assertEqual(G._run(server._quiet_queue_tick(SAT_LATE))["due"], 0)   # not yet
        self.assertEqual(self.sent, [])
        rep = G._run(server._quiet_queue_tick(SAT_NIGHT))
        self.assertEqual((rep["sent"], rep["failed"]), (3, 0))
        self.assertEqual([t for _, _, t in self.sent], ["first", "second", "third"])
        self.assertEqual(self.sent[1][:2], ("dm", "u_admin"))
        G._run(server._quiet_queue_tick(SAT_NIGHT))
        self.assertEqual(len(self.sent), 3)                                       # once

    def test_a_job_without_shabbos_off_sends(self):
        G._run(server._set_whatsapp_project_fields("proj_a", G.CO_A, {"chase_shabbos_off": False}))
        self.assertEqual(self.send("now", SAT_DAY), {"ok": True})
        self.assertEqual(_queue(self.db), [])

    def test_a_yom_tov_weekday(self):
        self.assertEqual(self.send("YK", YK_NOON), "queued")
        G._run(server._quiet_queue_tick(YK_NOON))
        self.assertEqual(self.sent, [])
        G._run(server._quiet_queue_tick(YK_TUE))
        self.assertEqual([t for _, _, t in self.sent], ["YK"])


class TheGcAlerts(unittest.TestCase):
    """DOB / DOT alerts queue; a Stop Work Order or Vacate posts at once only
    when the company turned that on."""

    def run_alerts(self, critical=None):
        db = G._world()
        if critical is not None:
            _company(db, shabbos_critical_alerts=critical)
        with G._Ctx(db=db) as c, G._no_ai():
            G._confirm()
            G._run(server._gc_alerts_tick(G.NOON))                  # baseline (Wed)
            db.dob_logs.rows.extend([
                G._violation("2"),
                G._violation("S1", record_type="swo", status="ACTIVE"),
                G._violation("9", violation_subtype="VACATE_FULL"),
            ])
            rep = G._run(server._gc_alerts_tick(FRI_AFTER))
            during = [p["message"] for p in G._group_sends(c)]
            G._run(server._quiet_queue_tick(SAT_DAY))
            still = len(G._group_sends(c))
            G._run(server._quiet_queue_tick(SAT_NIGHT))
            after = [p["message"] for p in G._group_sends(c)][len(during):]
            G._run(server._gc_alerts_tick(SAT_NIGHT))                # nothing twice
            total = len(G._group_sends(c))
        return rep, during, still, after, total

    def test_critical_alerts_off_by_default_everything_queues(self):
        rep, during, still, after, total = self.run_alerts()
        self.assertEqual(during, [])
        self.assertEqual(rep["shabbos_queued"], 3)
        self.assertEqual(still, 0)
        self.assertEqual(len(after), 3)
        self.assertEqual(total, 3)

    def test_critical_alerts_on_swo_and_vacate_post_now(self):
        rep, during, still, after, total = self.run_alerts(critical=True)
        self.assertEqual(len(during), 2)
        self.assertTrue(any("S1" in m or "Stop" in m for m in during), during)
        self.assertTrue(any("V9" in m for m in during), during)
        self.assertEqual(len(after), 1)
        self.assertIn("Violation #V2", after[0])
        self.assertEqual(total, 3)

    def test_before_candle_lighting_posts(self):
        db = G._world()
        with G._Ctx(db=db) as c, G._no_ai():
            G._confirm()
            G._run(server._gc_alerts_tick(G.NOON))
            db.dob_logs.rows.append(G._violation("2"))
            G._run(server._gc_alerts_tick(FRI_BEFORE))
            self.assertEqual(len(G._group_sends(c)), 1)


class TheMorningBrief(unittest.TestCase):
    """Skipped, not queued."""

    def test_saturday_and_yom_tov_skipped_then_nothing_later(self):
        db = B._world()
        B._optin(db, "u_admin", B.ADMIN_PHONE)
        B.TimeAndOnce._set(None, db, "u_admin", brief_weekend=True)
        with B._Ctx(db) as c:
            rep = B._tick(c, B.SAT_7)
            self.assertEqual(rep["shabbos_skipped"], 1)
            B._tick(c, _ny(2026, 10, 10, 21))                        # Saturday night
            G._run(server._quiet_queue_tick(_ny(2026, 10, 10, 21)))
            self.assertEqual(B._sends(c), [])
            B._tick(c, B.SUN_7)
            self.assertEqual(len(B._sends(c)), 1)                    # Sunday's, as usual
            B._tick(c, _ny(2026, 9, 21, 7, 5))                       # Yom Kippur, a Monday
            self.assertEqual(len(B._sends(c)), 1)
            B._tick(c, _ny(2026, 9, 22, 7, 5))
            self.assertEqual(len(B._sends(c)), 2)
        self.assertEqual(db[server.WA_QUIET_QUEUE].rows, [])


class TheUpcomingDms(unittest.TestCase):

    def setUp(self):
        self.db = U._city_world()
        U._with(self.db, lambda: U._run(server._upcoming_city_tick(now=U.T0)))
        pm = next(u for u in self.db.users.rows if u["_id"] == "u_pm")
        pm["assigned_projects"] = ["proj_a"]

    def tick(self, at):
        return U._with(self.db, lambda: U._run(server._upcoming_notify_tick(now=at)))

    def test_friday_5pm_for_a_saturday_event_is_skipped(self):
        U._seed_chat_event(self.db, date="2026-12-19", title="Crane pick")      # Saturday
        rep, sends = self.tick(_ny(2026, 12, 18, 17, 5))                       # Fri 5:05 PM (quiet)
        self.assertEqual((rep["shabbos_skipped"], sends.dm), (1, []))
        _, later = self.tick(_ny(2026, 12, 19, 18, 30))                        # Sat night
        self.assertEqual(later.dm, [])
        self.assertEqual(self.db[server.WA_QUIET_QUEUE].rows, [])

    def test_saturday_5pm_for_a_sunday_event_waits_for_nightfall(self):
        U._seed_chat_event(self.db, date="2026-12-20", title="Concrete pour")  # Sunday
        rep, sends = self.tick(_ny(2026, 12, 19, 17, 5))                       # Sat 5:05 PM (quiet)
        self.assertEqual((rep["shabbos_queued"], sends.dm), (1, []))
        rep, again = self.tick(_ny(2026, 12, 19, 17, 35))                      # not made twice
        self.assertEqual(len(self.db[server.WA_QUIET_QUEUE].rows), 1)
        _, out = U._with(self.db, lambda: U._run(server._quiet_queue_tick(_ny(2026, 12, 19, 18, 30))))
        (uid, text, kw), = out.dm
        self.assertEqual((uid, kw["kind"], kw["window"]), ("u_pm", "upcoming_day_before", "2026-12-20"))
        self.assertIn("Concrete pour", text)

    def test_a_friday_reminder_in_the_stretch_is_queued(self):
        self.db[server.UPCOMING].rows.append(
            {"_id": "r1", "company_id": G.CO_A, "project_id": None, "user_id": "u_pm",
             "source": "dm", "kind": "reminder", "title": "call the inspector",
             "date": "2026-12-18", "time": None, "status": "open", "history": []})
        rep, sends = self.tick(_ny(2026, 12, 18, 16, 30))
        self.assertEqual((rep["shabbos_queued"], sends.dm), (1, []))
        _, out = U._with(self.db, lambda: U._run(server._quiet_queue_tick(_ny(2026, 12, 19, 18, 30))))
        self.assertEqual([t for _, t, _ in out.dm], ["Reminder: call the inspector"])

    def test_a_company_without_shabbos_off_sends(self):
        _company(self.db, shabbos_off=False)
        U._seed_chat_event(self.db, date="2026-12-19", title="Crane pick")
        rep, sends = self.tick(_ny(2026, 12, 18, 17, 5))
        self.assertEqual(rep["day_before_sent"], 1)


class RepliesStillAnswered(unittest.TestCase):
    """Someone who writes to the bot on Shabbos chose to: answered."""

    def test_a_question_on_shabbos_is_answered(self):
        from tests.test_dm_routing_order import CHAT, _Dm, _world
        from tests.test_whatsapp_dm_assistant import _Ctx
        h = type("H", (_Dm, unittest.TestCase), {"runTest": lambda s: None})()
        h.setUp()
        try:
            db = _world()
            with _Ctx(db=db) as c, patch.object(shabbos, "quiet_until", lambda at: SAT_NIGHT), \
                    patch.object(shabbos, "is_quiet", lambda at: True):
                (r,) = h.dm(c, "what's open at 588")
            self.assertEqual(len(r), 1)
            self.assertEqual(len(h.agent_calls), 1)
            self.assertEqual(db[server.WA_QUIET_QUEUE].rows, [])
        finally:
            h.tearDown()


class EverySender(unittest.TestCase):
    """Each proactive sender goes through the Shabbos check."""

    def test_wired(self):
        import inspect
        for fn, needle in ((server._morning_brief_tick, "_shabbos_quiet("),
                           (server._upcoming_notify_tick, "_shabbos_quiet("),
                           (server._gc_alerts_tick, "_shabbos_quiet("),
                           (server._gc_propose_tick, "_shabbos_quiet("),
                           (server._punch_remind_tick, "_quiet_or_send("),
                           (server._punch_post, "_shabbos_quiet("),
                           (server._summarize_and_send_for_group, "_quiet_or_send("),
                           (server._extract_whatsapp_checklist, "_quiet_or_send(")):
            with self.subTest(fn.__name__):
                self.assertIn(needle, inspect.getsource(fn))
        self.assertIn("_quiet_queue_job", inspect.getsource(server))


if __name__ == "__main__":
    unittest.main()
