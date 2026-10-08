"""WhatsApp UX after the Phase 2 test.

  * Group names are WhatsApp subjects, fetched and stored; a raw …@g.us id is
    never returned for display ("Unnamed group" instead).
  * One config, read the same way by the app and the bot.
  * A switch that is off removes the facts from the agent's context too.
  * Per-project send window: Anytime (default) / Work hours / Custom; outside
    it alerts and the GC-group question wait for its start.
  * Reactions instead of filler: ✅ for "done N", 👍 for a discarded
    checklist, 🙏 / ❤️ for thanks / praise, 👀 on a slow answer. A failed
    reaction falls back to the old text; never both.
  * The bot names a job by its address; only linkers may unlink.
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

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import wa_gc, wa_groups, wa_react  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_phase0_security import (  # noqa: E402
    BOT_NUMBER, CO_A, GROUP, PROJ_A, _Db, _group_row, _payload,
)
from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    ADMIN, NOON, PM, _Ctx, _confirm, _group_sends, _no_ai, _run as _arun,
    _violation, _world,
)


def _run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════
# Group names
# ══════════════════════════════════════════════════════════════════════════

class GroupNames(unittest.TestCase):

    def test_an_id_is_never_a_name(self):
        for raw in ("120363424969499174@g.us", "120363424969499174", "", None,
                    "  ", "15551234567@c.us"):
            self.assertFalse(wa_groups.is_real_name(raw), raw)
            self.assertEqual(wa_groups.display_name(raw), "Unnamed group")
        self.assertEqual(wa_groups.display_name(" Main St GC "), "Main St GC")

    def _db(self, **row):
        return FakeDb(whatsapp_groups=[{"_id": "g1", "wa_group_id": GROUP,
                                         "project_id": "proj_a", "company_id": CO_A,
                                         "active": True, **row}],
                      whatsapp_messages=[
                          {"group_id": GROUP, "sender": "15550001111", "body": "hi"},
                          {"group_id": GROUP, "sender": "bot", "body": "hello"}])

    def test_a_missing_name_is_fetched_stored_and_shown(self):
        db = self._db()
        calls = []

        async def subject(gid):
            calls.append(gid)
            return "Main St GC"
        with patch.object(server, "db", db), \
                patch.object(server, "_fetch_group_subject", subject):
            out = _run(server.whatsapp_get_groups(
                "proj_a", {"id": "u", "company_id": CO_A, "role": "admin"}))
        self.assertEqual(calls, [GROUP])
        self.assertEqual((out[0]["group_name"], out[0]["has_name"]), ("Main St GC", True))
        self.assertEqual(db.whatsapp_groups.rows[0]["group_name"], "Main St GC")
        self.assertEqual(out[0]["message_count"], 1)          # the bot's row is not counted

    def test_unknown_subject_shows_unnamed_and_is_not_retried_within_the_hour(self):
        db = self._db(group_name=GROUP)                       # an id stored as the name
        calls = []

        async def nothing(gid):
            calls.append(gid)
            return ""
        with patch.object(server, "db", db), \
                patch.object(server, "_fetch_group_subject", nothing):
            out = _run(server.whatsapp_get_groups(
                "proj_a", {"id": "u", "company_id": CO_A, "role": "admin"}))
            _run(server.whatsapp_get_groups(
                "proj_a", {"id": "u", "company_id": CO_A, "role": "admin"}))
        self.assertEqual(out[0]["group_name"], "Unnamed group")
        self.assertNotIn("@g.us", out[0]["group_name"])
        self.assertEqual(len(calls), 1)                       # once an hour, not every read

    def test_lookups_per_read_are_capped(self):
        rows = [{"wa_group_id": f"{i}@g.us"} for i in range(25)]
        calls = []

        async def subject(gid):
            calls.append(gid)
            return ""
        with patch.object(server, "db", FakeDb()), \
                patch.object(server, "_fetch_group_subject", subject):
            _run(server._ensure_group_names(rows))
        self.assertEqual(len(calls), wa_groups.NAME_FETCH_LIMIT)

    def test_an_unnamed_group_is_never_the_auto_pick(self):
        db = _world()
        db.whatsapp_groups.rows[0]["group_name"] = ""          # "Main St Project" unknown
        with _Ctx(db=db):
            async def nothing(gid):
                return ""
            with patch.object(server, "_fetch_group_subject", nothing):
                r = _run(server._gc_propose_tick(NOON))
        self.assertEqual(r["asked"], 0)


# ══════════════════════════════════════════════════════════════════════════
# One config for app and bot
# ══════════════════════════════════════════════════════════════════════════

class OneConfig(unittest.TestCase):

    def test_a_partial_features_dict_reads_like_the_app_shows(self):
        cfg = server._effective_bot_config({"features": {"who_on_site": False}})
        self.assertEqual(cfg["features"]["who_on_site"], False)
        self.assertEqual(cfg["features"]["plan_queries"], True)      # was False in the bot
        self.assertEqual(cfg["features"]["address_mode"], "loose")   # was "strict" in the bot
        self.assertNotIn("cross_project_summary", cfg)

    def test_the_dead_key_is_accepted_and_ignored(self):
        db = FakeDb(whatsapp_groups=[_group_row(CO_A, "proj_a", _id="g1")])
        with patch.object(server, "db", db):
            out = _run(server.whatsapp_update_group_config(
                "g1", {"bot_enabled": True, "cross_project_summary": True},
                {"id": "u", "company_id": CO_A, "role": "admin"}))
        self.assertNotIn("cross_project_summary", out["bot_config"])
        self.assertNotIn("bot_config.cross_project_summary",
                         str(db.whatsapp_groups.rows[0]))


class TheContextFollowsTheSwitches(unittest.TestCase):

    def _ctx(self, features):
        db = _Db(projects=[PROJ_A], companies=[{"_id": CO_A, "name": "A GC"}])
        with patch.object(server, "db", db):
            return _run(server._agent_context_block(
                "proj_a", features, "loose", company_id=CO_A))

    def test_off_means_the_facts_are_gone_too(self):
        on = self._ctx({"who_on_site": True, "open_items": True, "dob_status": True})
        off = self._ctx({"who_on_site": False, "open_items": False, "dob_status": False})
        self.assertIn("OPEN ITEMS", on)
        self.assertIn("PERMITS", on)
        for word in ("ROSTER", "LAST WORKING DAY", "OPEN ITEMS", "PERMITS"):
            self.assertNotIn(word, off)
        self.assertIn("PROJECT:", off)


# ══════════════════════════════════════════════════════════════════════════
# Send window
# ══════════════════════════════════════════════════════════════════════════

def ET(h, m=0):
    """h:m New York time (EDT, UTC-4) on 2026-10-07."""
    return datetime(2026, 10, 7, tzinfo=timezone.utc) + timedelta(hours=h + 4, minutes=m)


class TheSendWindow(unittest.TestCase):

    def test_modes(self):
        self.assertTrue(wa_gc.in_send_window(ET(3), None))                    # default anytime
        self.assertTrue(wa_gc.in_send_window(ET(3), {"mode": "anytime"}))
        work = {"mode": "work_hours"}
        self.assertFalse(wa_gc.in_send_window(ET(6, 59), work))
        self.assertTrue(wa_gc.in_send_window(ET(7), work))
        self.assertTrue(wa_gc.in_send_window(ET(18, 59), work))
        self.assertFalse(wa_gc.in_send_window(ET(19), work))
        night = {"mode": "custom", "start": "22:00", "end": "06:00"}
        self.assertTrue(wa_gc.in_send_window(ET(23), night))
        self.assertTrue(wa_gc.in_send_window(ET(5, 59), night))
        self.assertFalse(wa_gc.in_send_window(ET(12), night))

    def test_validation(self):
        self.assertIsNone(wa_gc.clean_send_window({"mode": "custom", "start": "07:00",
                                                   "end": "07:00"}))
        self.assertIsNone(wa_gc.clean_send_window({"mode": "custom", "start": "25:00",
                                                   "end": "07:00"}))
        self.assertIsNone(wa_gc.clean_send_window({"mode": "soon"}))
        self.assertEqual(wa_gc.clean_send_window({"mode": "work_hours", "start": "x"})["mode"],
                         "work_hours")

    def test_alerts_wait_for_the_window_then_go(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._set_whatsapp_project_fields(
                "proj_a", CO_A, {"send_window": {"mode": "work_hours"}}))
            _arun(server._gc_alerts_tick(ET(12)))                 # baseline
            db.dob_logs.rows.append(_violation("50"))
            r = _arun(server._gc_alerts_tick(ET(22)))             # 10 PM: held
            self.assertEqual((r["held"], len(_group_sends(c))), (1, 0))
            self.assertIsNone(_run(db[server.WA_LEDGER].find_one(
                {"_id": wa_gc.ledger_id("proj_a", "violation", "50")})))
            _arun(server._gc_alerts_tick(ET(7) + timedelta(days=1)))   # 7 AM
            self.assertEqual(len(_group_sends(c)), 1)

    def test_the_question_waits_too(self):
        from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, _start
        with _Ctx(db=_world()) as c:
            _start(ADMIN_PHONE)
            _run(server._set_whatsapp_project_fields(
                "proj_a", CO_A, {"send_window": {"mode": "custom",
                                                  "start": "08:00", "end": "17:00"}}))
            self.assertEqual(_run(server._gc_propose_tick(ET(20)))["asked"], 0)
            self.assertEqual(_run(server._gc_propose_tick(ET(8)))["asked"], 1)

    def test_the_setting_is_admin_only_and_validated(self):
        with _Ctx(db=_world()):
            out = _run(server.patch_project_whatsapp_alerts(
                "proj_a", {"send_window": {"mode": "custom", "start": "06:30",
                                           "end": "15:00"}}, ADMIN))
            self.assertEqual(out["send_window"],
                             {"mode": "custom", "start": "06:30", "end": "15:00"})
            for bad in ({"send_window": {"mode": "custom", "start": "06:30",
                                          "end": "06:30"}},
                        {"send_window": "anytime"}):
                with self.assertRaises(HTTPException) as e:
                    _run(server.patch_project_whatsapp_alerts("proj_a", bad, ADMIN))
                self.assertEqual(e.exception.status_code, 422)
            with self.assertRaises(HTTPException) as e:
                _run(server.patch_project_whatsapp_alerts(
                    "proj_a", {"send_window": {"mode": "anytime"}}, PM))
            self.assertEqual(e.exception.status_code, 403)
            fresh = _run(server.get_project_whatsapp_settings("proj_a", ADMIN))
            self.assertEqual(fresh["send_window"]["mode"], "custom")


# ══════════════════════════════════════════════════════════════════════════
# Reactions instead of filler
# ══════════════════════════════════════════════════════════════════════════

class Reactions(unittest.TestCase):

    def test_the_map_is_fixed(self):
        self.assertEqual(wa_react.REACTIONS, {
            "done": "👍", "complete": "✅", "saved": "📌", "working": "👀",
            "thanks": "🙏", "praise": "❤️"})

    def test_only_a_bare_thanks_or_compliment_counts(self):
        for body, want in (("thanks", "thanks"), ("Thank you Levelog!", "thanks"),
                           ("great job", "praise"), ("you're the best", "praise"),
                           ("thanks, who's on site?", None),
                           ("great, now send A-101", None), ("ok", None),
                           ("who is on site", None)):
            self.assertEqual(wa_react.social_reaction(body), want, body)

    def _process(self, db, body, *, react_ok=True, agent_reply="answer",
                 agent_delay=0.0, msg_id="M1"):
        sent, reactions, agent_calls = [], [], []

        async def send(chat, text, reply_to=None, **kw):
            sent.append(text)
            return {"ok": True}

        async def react(chat, mid, emoji):
            reactions.append((mid, emoji))
            return react_ok

        async def agent(**kw):
            agent_calls.append(kw)
            if agent_delay:
                await asyncio.sleep(agent_delay)
            return agent_reply

        async def no_detect(*a, **k):
            return None
        with patch.object(server, "db", db), \
                patch.object(server, "send_whatsapp_message", send), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_detect_material_request", no_detect), \
                patch.object(wa_react, "WORKING_AFTER_SECONDS", 0.05), \
                patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": BOT_NUMBER}):
            _run(server._process_whatsapp_message(_payload(body, msg_id=msg_id)))
        return sent, reactions, agent_calls

    def _db(self, **extra):
        return _Db(projects=[PROJ_A], whatsapp_groups=[_group_row(CO_A, "proj_a")],
                   **extra)

    def _checklist_db(self):
        return self._db(whatsapp_checklists=[{
            "_id": "cl1", "group_id": GROUP, "company_id": CO_A,
            "project_id": "proj_a", "generated_at": datetime.now(timezone.utc),
            "items": [{"text": "Clean up"}, {"text": "Order rebar"}]}])

    def test_done_n_reacts_with_a_check_and_sends_no_text(self):
        db = self._checklist_db()
        sent, reactions, _ = self._process(db, "done 2")
        self.assertEqual(reactions, [(f"false_{GROUP}_M1", "✅")])
        self.assertEqual(sent, [])
        self.assertTrue(db.whatsapp_checklists.rows[0]["items"][1]["completed"])

    def test_a_failed_reaction_falls_back_to_the_text_never_both(self):
        sent, reactions, _ = self._process(self._checklist_db(), "done 2", react_ok=False)
        self.assertEqual(len(reactions), 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("marked complete", sent[0])

    def test_missing_info_is_text_not_a_reaction(self):
        sent, reactions, _ = self._process(self._checklist_db(), "done 9")
        self.assertEqual(reactions, [])
        self.assertIn("not found", sent[0])

    def test_thanks_gets_a_prayer_and_no_text_or_agent(self):
        sent, reactions, agent = self._process(self._db(), "thanks levelog")
        self.assertEqual(reactions, [(f"false_{GROUP}_M1", "🙏")])
        self.assertEqual((sent, agent), ([], []))

    def test_praise_gets_a_heart_once_a_day_per_person(self):
        db = self._db()
        _, r1, _ = self._process(db, "levelog great job", msg_id="P1")
        _, r2, _ = self._process(db, "levelog great job", msg_id="P2")
        self.assertEqual(r1, [(f"false_{GROUP}_P1", "❤️")])
        self.assertEqual(r2, [])

    def test_unaddressed_thanks_gets_nothing(self):
        sent, reactions, _ = self._process(
            _Db(projects=[PROJ_A], whatsapp_groups=[_group_row(
                CO_A, "proj_a", features={**server._default_bot_config()["features"],
                                          "address_mode": "strict"})]),
            "thanks")
        self.assertEqual((sent, reactions), ([], []))

    def test_a_quick_answer_gets_text_only(self):
        sent, reactions, _ = self._process(self._db(), "levelog who is on site")
        self.assertEqual((sent, reactions), (["answer"], []))

    def test_a_slow_answer_gets_eyes_first_then_the_text(self):
        sent, reactions, _ = self._process(self._db(), "levelog who is on site",
                                           agent_delay=0.2)
        self.assertEqual(reactions, [(f"false_{GROUP}_M1", "👀")])
        self.assertEqual(sent, ["answer"])

    def test_eyes_are_taken_back_when_no_answer_comes(self):
        sent, reactions, _ = self._process(self._db(), "levelog who is on site",
                                           agent_delay=0.2, agent_reply=None)
        self.assertEqual([e for _, e in reactions], ["👀", ""])
        self.assertEqual(sent, [])

    def test_the_reaction_call_is_waapi_react_to_message(self):
        calls = []

        async def post(url, payload, headers):
            calls.append((url, payload))
            return 200, {"status": "success"}, None
        with patch.object(server, "WAAPI_INSTANCE_ID", "inst"), \
                patch.object(server, "WAAPI_TOKEN", "tok"), \
                patch.object(server, "_waapi_post_raw", post):
            ok = _run(server._react_to_message(GROUP, "false_x_M1", "✅"))
        self.assertTrue(ok)
        self.assertTrue(calls[0][0].endswith("/client/action/react-to-message"))
        self.assertEqual(calls[0][1], {"messageId": "false_x_M1", "reaction": "✅"})


# ══════════════════════════════════════════════════════════════════════════
# The job's address, and who may unlink
# ══════════════════════════════════════════════════════════════════════════

class AddressAndRoles(unittest.TestCase):

    def test_the_bot_names_the_job_by_its_address(self):
        self.assertEqual(wa_groups.project_label(
            {"name": "Church", "address": "12 Main St", "nickname": "The Church Job"}),
            "12 Main St")
        self.assertEqual(wa_groups.project_label({"name": "Church"}), "Church")

    def test_gc_alerts_use_the_address(self):
        db = _world()
        db.projects.rows[0]["address"] = "12 Main St"
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _arun(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("60"))
            _arun(server._gc_alerts_tick(NOON))
            self.assertIn("12 Main St", _group_sends(c)[0]["message"])

    def test_only_linkers_may_unlink(self):
        db = FakeDb(whatsapp_groups=[_group_row(CO_A, "proj_a", _id="g1")])
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as e:
                _run(server.whatsapp_unlink_group(
                    "g1", {"id": "u", "company_id": CO_A, "role": "superintendent"}))
            self.assertEqual(e.exception.status_code, 403)
            self.assertTrue(db.whatsapp_groups.rows[0]["active"])
            _run(server.whatsapp_unlink_group(
                "g1", {"id": "u", "company_id": CO_A, "role": "admin"}))
            self.assertFalse(db.whatsapp_groups.rows[0]["active"])


if __name__ == "__main__":
    unittest.main()
