"""WhatsApp Phase 1 — foundations, tested without a database or WaAPI.

  * No proactive direct message without an ACTIVE opt-in, enforced inside the
    send function: calling it directly is refused.
  * START from anyone but a company admin / PM gets no opt-in and a neutral
    reply; STOP / PARAR opts out and nothing proactive follows.
  * The scheduler lease runs a job once when two runners fire it together.
  * The WaAPI disconnect monitor emails once per incident and once on
    recovery.
  * Mentions, quotes and from_me are stored; bot rows carry the binding.
  * The identity resolver is company-scoped and refuses @lid.
  * DM sends are paced and retried on transient errors; groups are not.
  * Retention TTLs and preferences.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import notification_preferences as nprefs  # noqa: E402
from lib import scheduler_lease, wa_dm, waapi_monitor  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO_A, CO_B = "co_a", "co_b"
ADMIN_PHONE = "15550001001"
PM_PHONE = "15550001002"
CP_PHONE = "15550001003"
SUPER_PHONE = "15550001004"
UNKNOWN_PHONE = "15550009999"
GROUP = "120363000000000777@g.us"


def _users():
    return [
        {"_id": "u_admin", "company_id": CO_A, "role": "admin",
         "phone": "+" + ADMIN_PHONE, "name": "Ada Admin", "email": "a@a"},
        {"_id": "u_pm", "company_id": CO_A, "role": "pm",
         "phone": "+" + PM_PHONE, "name": "Pat PM", "email": "p@a",
         "assigned_projects": ["proj_a"]},
        {"_id": "u_cp", "company_id": CO_A, "role": "cp",
         "phone": "+" + CP_PHONE, "name": "Cal CP"},
        {"_id": "u_super", "company_id": CO_A, "role": "superintendent",
         "phone": "+" + SUPER_PHONE, "name": "Sue Super"},
        {"_id": "u_b", "company_id": CO_B, "role": "admin",
         "phone": "+15550002001", "name": "Bea B"},
    ]


def _db(**extra):
    return FakeDb(
        unique={server.WA_OPTINS: ("phone",)},
        users=_users(),
        projects=[{"_id": "proj_a", "company_id": CO_A, "name": "A"},
                  {"_id": "proj_b", "company_id": CO_B, "name": "B"}],
        **extra,
    )


def _run(coro):
    return asyncio.run(coro)


class _Wire:
    """Captures WaAPI posts; no network."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    async def post_raw(self, url, payload, headers):
        self.calls.append(payload)
        if self.responses:
            return self.responses.pop(0)
        return 200, {"status": "success"}, None


def _patches(db, wire):
    return [
        patch.object(server, "db", db),
        patch.object(server, "WAAPI_INSTANCE_ID", "inst"),
        patch.object(server, "WAAPI_TOKEN", "tok"),
        patch.object(server, "_waapi_post_raw", wire.post_raw),
        patch.object(wa_dm, "DM_MIN_INTERVAL_SECONDS", 0.0),
        patch.object(wa_dm, "DM_BACKOFF_SECONDS", (0.0, 0.0, 0.0)),
    ]


class _Ctx:
    def __init__(self, db=None, wire=None):
        self.db = db or _db()
        self.wire = wire or _Wire()
        self._ps = _patches(self.db, self.wire)

    def __enter__(self):
        for p in self._ps:
            p.start()
        return self

    def __exit__(self, *a):
        for p in reversed(self._ps):
            p.stop()


def _start(phone):
    """START the way it arrives: the inbound message opens the reply window,
    then the handler runs and its intro rides that window."""
    _run(server._open_dm_reply_window(phone))
    _run(server._handle_dm_start(phone))


def _dm_payload(phone, body, msg_id="D1"):
    return {"event": "message", "data": {"message": {
        "id": {"id": msg_id, "fromMe": False}, "from": f"{phone}@c.us",
        "body": body, "type": "chat"}}}


# ══════════════════════════════════════════════════════════════════════════
# No DM without opt-in — enforced in the send function itself
# ══════════════════════════════════════════════════════════════════════════

class NoDirectMessageWithoutOptIn(unittest.TestCase):

    def test_a_direct_call_to_send_whatsapp_message_is_refused(self):
        with _Ctx() as c:
            out = _run(server.send_whatsapp_message(
                f"{ADMIN_PHONE}@c.us", "hello"))
        self.assertIsNone(out)
        self.assertEqual(c.wire.calls, [])

    def test_a_proactive_send_is_refused_without_optin(self):
        with _Ctx() as c:
            out = _run(server.send_whatsapp_dm(
                "u_admin", "summary", kind="summary", window="2026-10-07",
                project_id="proj_a"))
        self.assertIsNone(out)
        self.assertEqual(c.wire.calls, [])

    def test_dm_meta_alone_grants_nothing(self):
        with _Ctx() as c:
            out = _run(server.send_whatsapp_message(
                f"{ADMIN_PHONE}@c.us", "x",
                dm_meta={"user_id": "u_admin", "kind": "summary",
                         "window": "w"}))
        self.assertIsNone(out)
        self.assertEqual(c.wire.calls, [])

    def test_a_reply_window_does_not_cover_a_proactive_send(self):
        with _Ctx() as c:
            _run(server._open_dm_reply_window(ADMIN_PHONE))
            out = _run(server.send_whatsapp_dm(
                "u_admin", "x", kind="summary", window="w"))
        self.assertIsNone(out)
        self.assertEqual(c.wire.calls, [])

    def test_groups_are_not_gated(self):
        with _Ctx() as c:
            out = _run(server.send_whatsapp_message(GROUP, "hi group"))
        self.assertIsNotNone(out)
        self.assertEqual(len(c.wire.calls), 1)

    def test_an_opted_in_user_gets_one_ledgered_send_per_key(self):
        with _Ctx() as c:
            _start(ADMIN_PHONE)
            c.wire.calls.clear()
            first = _run(server.send_whatsapp_dm(
                "u_admin", "summary", kind="summary", window="2026-10-07",
                project_id="proj_a"))
            second = _run(server.send_whatsapp_dm(
                "u_admin", "summary", kind="summary", window="2026-10-07",
                project_id="proj_a"))
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(c.wire.calls), 1)
        rows = c.db[server.WA_LEDGER].rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_id"], "u_admin:proj_a:summary:2026-10-07")
        self.assertEqual(rows[0]["status"], "sent")

    def test_a_project_of_another_company_is_refused(self):
        with _Ctx() as c:
            _start(ADMIN_PHONE)
            c.wire.calls.clear()
            out = _run(server.send_whatsapp_dm(
                "u_admin", "x", kind="summary", window="w", project_id="proj_b"))
        self.assertIsNone(out)
        self.assertEqual(c.wire.calls, [])

    def test_a_changed_phone_ends_the_optin(self):
        with _Ctx() as c:
            _start(ADMIN_PHONE)
            c.wire.calls.clear()
            c.db.users.rows[0]["phone"] = "+15550004444"
            out = _run(server.send_whatsapp_dm(
                "u_admin", "x", kind="summary", window="w"))
        self.assertIsNone(out)
        self.assertEqual(c.wire.calls, [])

    def test_preferences_gate_the_kind(self):
        with _Ctx() as c:
            _start(ADMIN_PHONE)
            c.db.notification_preferences.rows.append({
                "user_id": "u_admin", "project_id": "proj_a",
                "whatsapp": {"summary_frequency": "off"}})
            c.wire.calls.clear()
            out = _run(server.send_whatsapp_dm(
                "u_admin", "x", kind="summary", window="w", project_id="proj_a"))
            alert = _run(server.send_whatsapp_dm(
                "u_admin", "x", kind="reply_alert", window="w",
                project_id="proj_a"))
        self.assertIsNone(out)
        self.assertIsNotNone(alert)


# ══════════════════════════════════════════════════════════════════════════
# START / STOP
# ══════════════════════════════════════════════════════════════════════════

class StartAndStop(unittest.TestCase):

    def _process(self, c, phone, body, msg_id="D1"):
        with patch.object(server, "classify_intent", self._no_classify):
            _run(server._process_whatsapp_message(_dm_payload(phone, body, msg_id)))

    @staticmethod
    async def _no_classify(body):
        raise AssertionError("START/STOP must not reach intent classification")

    def test_start_from_an_admin_opts_in_and_introduces(self):
        with _Ctx() as c:
            self._process(c, ADMIN_PHONE, "START")
        rows = c.db[server.WA_OPTINS].rows
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["user_id"], rows[0]["status"]),
                         ("u_admin", "active"))
        self.assertEqual([p["message"] for p in c.wire.calls], [wa_dm.INTRO_TEXT])

    def test_start_from_a_pm_opts_in(self):
        with _Ctx() as c:
            self._process(c, PM_PHONE, "start")
        self.assertEqual(c.db[server.WA_OPTINS].rows[0]["user_id"], "u_pm")

    def test_start_from_cp_super_or_unknown_gets_no_optin_and_a_neutral_reply(self):
        for phone in (CP_PHONE, SUPER_PHONE, UNKNOWN_PHONE):
            with self.subTest(phone=phone), _Ctx() as c:
                self._process(c, phone, "START")
                self.assertEqual(c.db[server.WA_OPTINS].rows, [])
                self.assertEqual([p["message"] for p in c.wire.calls],
                                 [wa_dm.NOT_ELIGIBLE_TEXT])

    def test_start_from_a_worker_only_phone_gets_no_optin(self):
        db = _db(workers=[{"_id": "w1", "company_id": CO_A,
                           "phone": "555-000-1005"}])
        with _Ctx(db) as c:
            self._process(c, "15550001005", "START")
        self.assertEqual(c.db[server.WA_OPTINS].rows, [])
        self.assertEqual([p["message"] for p in c.wire.calls],
                         [wa_dm.NOT_ELIGIBLE_TEXT])

    def test_a_number_on_two_users_is_ambiguous(self):
        db = _db()
        db.users.rows.append({"_id": "u_dup", "company_id": CO_B,
                              "role": "admin", "phone": ADMIN_PHONE})
        with _Ctx(db) as c:
            self._process(c, ADMIN_PHONE, "START")
        self.assertEqual(c.db[server.WA_OPTINS].rows, [])

    def test_start_in_a_sentence_is_not_a_command(self):
        self.assertIsNone(wa_dm.parse_dm_command("start the pour at 7"))
        self.assertEqual(wa_dm.parse_dm_command(" Stop. "), "stop")
        self.assertEqual(wa_dm.parse_dm_command("PARAR"), "stop")

    def test_stop_and_parar_opt_out_and_nothing_follows(self):
        for word in ("STOP", "PARAR"):
            with self.subTest(word=word), _Ctx() as c:
                self._process(c, ADMIN_PHONE, "START", "D1")
                self._process(c, ADMIN_PHONE, word, "D2")
                row = c.db[server.WA_OPTINS].rows[0]
                self.assertEqual(row["status"], "opted_out")
                self.assertEqual(c.wire.calls[-1]["message"],
                                 wa_dm.STOP_CONFIRM_TEXT)
                c.wire.calls.clear()
                out = _run(server.send_whatsapp_dm(
                    "u_admin", "x", kind="summary", window="w"))
                # Even inside the reply window STOP opened, nothing proactive.
                out2 = _run(server.send_whatsapp_message(
                    f"{ADMIN_PHONE}@c.us", "x",
                    dm_meta={"user_id": "u_admin", "kind": "k", "window": "w"}))
                self.assertIsNone(out)
                self.assertIsNone(out2)
                self.assertEqual(c.wire.calls, [])

    def test_stop_from_an_unknown_number_is_recorded(self):
        with _Ctx() as c:
            self._process(c, UNKNOWN_PHONE, "STOP")
        row = c.db[server.WA_OPTINS].rows[0]
        self.assertEqual((row["phone"], row["status"], row["user_id"]),
                         (UNKNOWN_PHONE, "opted_out", None))

    def test_the_intro_text_is_the_operators(self):
        self.assertEqual(wa_dm.INTRO_TEXT, (
            "Blueview here. You'll get: chat summaries for your projects, "
            "alerts when someone needs your answer, inspection and permit "
            "reminders, and new DOB violations. Change settings in the app. "
            "Reply STOP to turn off."))


# ══════════════════════════════════════════════════════════════════════════
# Scheduler lease
# ══════════════════════════════════════════════════════════════════════════

class TheLeaseRunsAJobOnce(unittest.TestCase):

    def test_two_concurrent_runners_execute_once(self):
        db = FakeDb()
        runs = []

        async def job():
            runs.append(1)
            await asyncio.sleep(0)

        a = scheduler_lease.leased("j", 900, job, lambda: db)
        b = scheduler_lease.leased("j", 900, job, lambda: db)

        async def both():
            await asyncio.gather(a(), b())

        _run(both())
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(db.scheduler_leases.rows), 1)

    def test_the_next_slot_runs_again(self):
        db = FakeDb()
        t0 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(_run(scheduler_lease.try_acquire(db, "j", 900, now=t0)))
        self.assertFalse(_run(scheduler_lease.try_acquire(
            db, "j", 900, now=t0 + timedelta(minutes=7))))
        self.assertTrue(_run(scheduler_lease.try_acquire(
            db, "j", 900, now=t0 + timedelta(minutes=15))))

    def test_a_replica_a_few_seconds_early_shares_the_cron_slot(self):
        t = datetime(2026, 10, 7, 3, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(
            scheduler_lease.slot_key("c", 60, t),
            scheduler_lease.slot_key("c", 60, t - timedelta(seconds=4)))

    def test_an_unreachable_lock_skips_the_run(self):
        class Broken:
            def __getitem__(self, name):
                raise RuntimeError("down")
        runs = []

        async def job():
            runs.append(1)

        _run(scheduler_lease.leased("j", 60, job, lambda: Broken())())
        self.assertEqual(runs, [])

    def test_every_async_job_added_with_an_id_is_wrapped(self):
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger
        cls = scheduler_lease.make_leased_scheduler_class(
            AsyncIOScheduler, lambda: FakeDb())
        s = cls()

        async def tick():
            return None

        s.add_job(tick, IntervalTrigger(minutes=15), id="a")
        s.add_job(tick, CronTrigger(hour=3, minute=0), id="b")
        s.add_job(tick, CronTrigger(minute="*"), id="c")
        self.assertEqual(s.get_job("a").func.__lease_slot_seconds__, 900)
        self.assertEqual(s.get_job("b").func.__lease_slot_seconds__, 3600)
        self.assertEqual(s.get_job("c").func.__lease_slot_seconds__, 30)

    def test_the_server_scheduler_is_the_leased_one(self):
        self.assertEqual(type(server.scheduler).__name__,
                         "LeasedAsyncIOScheduler")

    def test_the_server_registers_its_jobs_through_add_job(self):
        """All 25 existing registrations plus the monitor go through
        scheduler.add_job with an id, so every one is wrapped."""
        src = (Path(server.__file__)).read_text(encoding="utf-8")
        start = src.index("async def startup_event")
        body = src[start:]
        self.assertEqual(body.count("scheduler.add_job("), 26)


# ══════════════════════════════════════════════════════════════════════════
# Disconnect monitor
# ══════════════════════════════════════════════════════════════════════════

class TheDisconnectMonitorEmailsOncePerIncident(unittest.TestCase):

    def test_one_alert_per_incident_and_one_recovery(self):
        db = _db()
        db.users.rows.append({"_id": "op", "is_platform_operator": True,
                              "email": "ops@levelog.com"})
        db.users.rows.append({"_id": "fake", "role": "admin",
                              "email": "not-op@x.com"})
        readings = iter([
            ("up", "ready"), ("down", "qr"), ("down", "qr"), ("down", "qr"),
            ("unknown", "http 502"), ("up", "ready"), ("up", "ready"),
            ("down", "qr"), ("down", "qr"),
        ])
        sent = []

        async def read():
            return next(readings)

        async def notify(_db, **kw):
            sent.append((kw["trigger_type"], kw["recipient"],
                         kw["permit_renewal_id"]))
            return {}

        actions = []
        with patch.object(server, "db", db), \
                patch.object(server, "_waapi_read_status", read), \
                patch("lib.notifications.send_notification", notify):
            for _ in range(9):
                actions.append(_run(server._waapi_instance_monitor_tick()))
        self.assertEqual(actions, [
            "none", "none", "alert_down", "none", "none",
            "alert_recovered", "none", "none", "alert_down"])
        triggers = [s[0] for s in sent]
        self.assertEqual(triggers, ["waapi_disconnected", "waapi_reconnected",
                                    "waapi_disconnected"])
        self.assertEqual({s[1] for s in sent}, {"ops@levelog.com"})
        # The two incidents are distinct ids.
        self.assertNotEqual(sent[0][2], sent[2][2])
        self.assertEqual(sent[0][2], sent[1][2])

    def test_an_unconfigured_instance_is_silent(self):
        with patch.object(server, "WAAPI_INSTANCE_ID", ""), \
                patch.object(server, "db", _db()):
            self.assertIsNone(_run(server._waapi_instance_monitor_tick()))

    def test_status_is_found_in_either_shape(self):
        self.assertEqual(waapi_monitor.find_status(
            {"clientStatus": {"instanceStatus": "ready"}, "status": "success"}),
            "ready")
        self.assertEqual(waapi_monitor.find_status({"status": "success"}), None)
        self.assertEqual(waapi_monitor.classify("qr"), "down")
        self.assertEqual(waapi_monitor.classify(None), "unknown")


# ══════════════════════════════════════════════════════════════════════════
# Mentions, quotes, from_me persisted; bot rows carry the binding
# ══════════════════════════════════════════════════════════════════════════

class WhoAMessageIsForIsKept(unittest.TestCase):

    def _db(self):
        cfg = server._default_bot_config()
        cfg["features"]["material_detection"] = False
        return _db(whatsapp_groups=[{
            "_id": "g1", "wa_group_id": GROUP, "company_id": CO_A,
            "project_id": "proj_a", "active": True,
            "linked_at": datetime.now(timezone.utc) - timedelta(days=1),
            "bot_config": cfg}])

    def test_mentions_and_the_quote_are_stored(self):
        payload = {"event": "message", "data": {"message": {
            "id": {"id": "M9", "fromMe": False, "_serialized": "x"},
            "from": GROUP, "author": f"{PM_PHONE}@c.us",
            "body": "@15550001001 can you confirm the pour?", "type": "chat",
            "mentionedIds": [f"{ADMIN_PHONE}@c.us", "123456789012345@lid"],
            "contextInfo": {"stanzaId": "Q1", "participant": f"{CP_PHONE}@c.us"},
            "quotedMsg": {"body": "pour friday?", "type": "chat"},
        }}}

        async def agent(**kw):
            return None

        with _Ctx(self._db()) as c, \
                patch.object(server, "_run_group_agent", agent):
            _run(server._process_whatsapp_message(payload))
        rows = [r for r in c.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["mentioned_jids"],
                         [f"{ADMIN_PHONE}@c.us", "123456789012345@lid"])
        self.assertEqual(row["quoted_message_id"], "Q1")
        self.assertEqual(row["quoted_author"], f"{CP_PHONE}@c.us")
        self.assertIs(row["from_me"], False)

    def test_bot_rows_carry_company_and_project(self):
        with _Ctx(self._db()) as c:
            _run(server.send_whatsapp_message(GROUP, "answer"))
        bot = [r for r in c.db.whatsapp_messages.rows if r.get("sender") == "bot"]
        self.assertEqual(len(bot), 1)
        self.assertEqual((bot[0]["company_id"], bot[0]["project_id"],
                          bot[0]["from_me"]), (CO_A, "proj_a", True))

    def test_a_bot_row_for_an_unbound_group_gets_no_guess(self):
        with _Ctx(_db()) as c:
            _run(server.send_whatsapp_message(GROUP, "answer"))
        bot = c.db.whatsapp_messages.rows[0]
        self.assertNotIn("company_id", bot)
        self.assertNotIn("project_id", bot)


# ══════════════════════════════════════════════════════════════════════════
# Identity resolver
# ══════════════════════════════════════════════════════════════════════════

class TheResolverIsCompanyScoped(unittest.TestCase):

    def _resolve(self, jid, company):
        with patch.object(server, "db", _db()):
            return _run(server.resolve_wa_identity(jid, company))

    def test_a_phone_in_the_company_resolves(self):
        out = self._resolve(f"{PM_PHONE}@c.us", CO_A)
        self.assertEqual((out["resolved"], out["user_id"], out["role"]),
                         (True, "u_pm", "pm"))

    def test_the_same_phone_from_another_company_does_not(self):
        out = self._resolve(f"{PM_PHONE}@c.us", CO_B)
        self.assertEqual((out["resolved"], out["reason"]),
                         (False, "no_user_in_company"))

    def test_a_lid_is_unresolvable(self):
        out = self._resolve("153906327875707@lid", CO_A)
        self.assertEqual((out["resolved"], out["reason"]),
                         (False, "lid_unmapped"))

    def test_no_company_resolves_nothing(self):
        out = self._resolve(f"{PM_PHONE}@c.us", "")
        self.assertFalse(out["resolved"])


# ══════════════════════════════════════════════════════════════════════════
# DM pacing and retry; groups unchanged
# ══════════════════════════════════════════════════════════════════════════

class DirectMessagesRetryTransientErrors(unittest.TestCase):

    def test_a_503_then_200_is_one_send(self):
        wire = _Wire([(503, {}, None), (200, {"ok": 1}, None)])
        with _Ctx(wire=wire) as c:
            _run(server._open_dm_reply_window(ADMIN_PHONE))
            out = _run(server.send_whatsapp_message(f"{ADMIN_PHONE}@c.us", "hi"))
        self.assertEqual(out, {"ok": 1})
        self.assertEqual(len(c.wire.calls), 2)

    def test_a_400_is_not_retried(self):
        wire = _Wire([(400, {}, None), (200, {}, None)])
        with _Ctx(wire=wire) as c:
            _run(server._open_dm_reply_window(ADMIN_PHONE))
            out = _run(server.send_whatsapp_message(f"{ADMIN_PHONE}@c.us", "hi"))
        self.assertIsNone(out)
        self.assertEqual(len(c.wire.calls), 1)

    def test_attempts_are_bounded(self):
        wire = _Wire([(502, {}, None)] * 10)
        with _Ctx(wire=wire) as c:
            _run(server._open_dm_reply_window(ADMIN_PHONE))
            _run(server.send_whatsapp_message(f"{ADMIN_PHONE}@c.us", "hi"))
        self.assertEqual(len(c.wire.calls), wa_dm.DM_SEND_ATTEMPTS)

    def test_a_group_send_is_one_attempt(self):
        wire = _Wire([(503, {}, None), (200, {}, None)])
        with _Ctx(wire=wire) as c:
            out = _run(server.send_whatsapp_message(GROUP, "hi"))
        self.assertIsNone(out)
        self.assertEqual(len(c.wire.calls), 1)

    def test_a_failed_proactive_send_is_marked_failed_in_the_ledger(self):
        wire = _Wire([(200, {}, None)] + [(500, {}, None)] * 5)
        with _Ctx(wire=wire) as c:
            _start(ADMIN_PHONE)   # intro: 200
            out = _run(server.send_whatsapp_dm(
                "u_admin", "x", kind="reminder", window="w"))
        self.assertIsNone(out)
        self.assertEqual(c.db[server.WA_LEDGER].rows[0]["status"], "failed")

    def test_the_reply_window_is_bounded(self):
        with _Ctx() as c:
            _run(server._open_dm_reply_window(UNKNOWN_PHONE))
            for _ in range(wa_dm.REPLY_WINDOW_MAX_SENDS + 2):
                _run(server.send_whatsapp_message(f"{UNKNOWN_PHONE}@c.us", "x"))
        self.assertEqual(len(c.wire.calls), wa_dm.REPLY_WINDOW_MAX_SENDS)

    def test_an_expired_window_allows_nothing(self):
        with _Ctx() as c:
            c.db[server.WA_DM_WINDOWS].rows.append({
                "_id": UNKNOWN_PHONE, "sends_left": 3,
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
            out = _run(server.send_whatsapp_message(f"{UNKNOWN_PHONE}@c.us", "x"))
        self.assertIsNone(out)
        self.assertEqual(c.wire.calls, [])


# ══════════════════════════════════════════════════════════════════════════
# Retention TTLs, indexes
# ══════════════════════════════════════════════════════════════════════════

class RetentionIsInCode(unittest.TestCase):

    def test_the_ttls(self):
        db = FakeDb()
        with patch.object(server, "db", db):
            _run(server.ensure_whatsapp_phase1_indexes())
        by_name = {}
        for coll in db._c.values():
            for ix in coll.indexes:
                by_name[ix["name"]] = (coll.name, ix)
        coll, ix = by_name["whatsapp_webhook_log_ttl_30d"]
        self.assertEqual((coll, ix["keys"], ix["expireAfterSeconds"]),
                         ("whatsapp_webhook_log", [("received_at", 1)], 30 * 86400))
        coll, ix = by_name["whatsapp_messages_ttl_24m"]
        self.assertEqual((coll, ix["keys"], ix["expireAfterSeconds"]),
                         ("whatsapp_messages", [("created_at", 1)], 730 * 86400))
        self.assertTrue(by_name["whatsapp_optins_phone_unique"][1]["unique"])
        for name in ("scheduler_leases_ttl", "whatsapp_dm_reply_windows_ttl",
                     "whatsapp_notification_ledger_ttl"):
            self.assertEqual(by_name[name][1]["expireAfterSeconds"], 0)


# ══════════════════════════════════════════════════════════════════════════
# Preferences
# ══════════════════════════════════════════════════════════════════════════

class WhatsAppPreferences(unittest.TestCase):

    def test_defaults_are_all_on(self):
        self.assertEqual(nprefs.default_whatsapp_prefs(), {
            "enabled": True, "summary_frequency": "daily",
            "reply_alerts": True, "reminders": True})

    def test_project_overrides_global_overrides_default(self):
        out = nprefs.effective_whatsapp_prefs(
            {"whatsapp": {"reminders": False}},
            {"whatsapp": {"summary_frequency": "weekly", "reminders": True,
                          "enabled": "yes"}})
        self.assertEqual(out, {"enabled": True, "summary_frequency": "weekly",
                               "reply_alerts": True, "reminders": False})

    def test_the_patch_is_validated(self):
        clean, errs = nprefs.validate_whatsapp_prefs_patch(
            {"summary_frequency": "biweekly", "reply_alerts": False})
        self.assertEqual((clean, errs), (
            {"summary_frequency": "biweekly", "reply_alerts": False}, []))
        _, errs = nprefs.validate_whatsapp_prefs_patch(
            {"summary_frequency": "hourly", "x": 1, "enabled": "no"})
        self.assertEqual(len(errs), 3)

    def test_eligibility(self):
        self.assertTrue(wa_dm.is_dm_eligible({"role": "Admin", "company_id": "c"}))
        self.assertTrue(wa_dm.is_dm_eligible({"role": "pm", "company_id": "c"}))
        for role in ("cp", "superintendent", "worker", "owner", "demo", ""):
            self.assertFalse(wa_dm.is_dm_eligible({"role": role, "company_id": "c"}))
        self.assertFalse(wa_dm.is_dm_eligible({"role": "admin", "company_id": ""}))


if __name__ == "__main__":
    unittest.main()
