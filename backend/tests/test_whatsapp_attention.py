"""Project Attention Engine v1 — shadow mode.

  * Nothing is ever sent: no group message, no DM, no reaction.
  * Not in the webhook: a scheduled job behind a cursor per group.
  * No backfill: a group's cursor starts when the engine first sees it.
  * Groups with the bot off get no AI processing, then or later.
  * Evidence or silence: an item's quote must be in the message it cites.
  * Owner only by deterministic match (user of the company, worker who
    checked in at the project, or an opt-in's chat id); otherwise the words
    and the JID are kept and the owner is "unresolved". Never another company.
  * Due date: as said; a date only when the code reads one.
  * Dedupe, possibly-answered by reply, the participant probe (counts only),
    the weekly metrics line, the admin-only review endpoints.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from bson import ObjectId  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import wa_attention as wa  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO_A, CO_B = "co_a", "co_b"
G_A = "120363000000000301@g.us"
G_OFF = "120363000000000302@g.us"
G_B = "120363000000000401@g.us"
T0 = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)      # 10 AM ET, Thursday
MIKE = "17185550101"            # a user of company A
WORKER = "17185550202"          # checked in at proj_a
LID = "123456789012345"         # privacy id, unmapped
LID_PM = "987654321098765"      # privacy id with an opt-in (PM of A)

ADMIN = {"_id": "u_admin", "id": "u_admin", "company_id": CO_A,
         "role": "admin", "account_status": "approved"}
PM = {"_id": "u_pm", "id": "u_pm", "company_id": CO_A, "role": "pm",
      "account_status": "approved", "assigned_projects": ["proj_a"]}
ADMIN_B = {"_id": "u_b", "id": "u_b", "company_id": CO_B, "role": "admin",
           "account_status": "approved"}


def _run(coro):
    return asyncio.run(coro)


def _world(bot_off_group=True, **extra):
    groups = [
        {"_id": "g1", "wa_group_id": G_A, "group_name": "Main St Project",
         "project_id": "proj_a", "company_id": CO_A, "active": True},
        {"_id": "g3", "wa_group_id": G_B, "group_name": "B site",
         "project_id": "proj_b", "company_id": CO_B, "active": True},
    ]
    if bot_off_group:
        groups.append({"_id": "g2", "wa_group_id": G_OFF, "group_name": "Quiet",
                       "project_id": "proj_a", "company_id": CO_A, "active": True,
                       "bot_config": {"bot_enabled": False}})
    cols = dict(
        users=[{"_id": "u_mike", "company_id": CO_A, "name": "Mike Rivera",
                "phone": MIKE, "role": "pm"},
               {"_id": "u_pm", "company_id": CO_A, "name": "Pat PM",
                "phone": "17185550303", "role": "pm"},
               {"_id": "u_bob", "company_id": CO_B, "name": "Bob Other",
                "phone": "17185550404", "role": "admin"}],
        projects=[{"_id": "proj_a", "company_id": CO_A, "name": "Main St"},
                  {"_id": "proj_b", "company_id": CO_B, "name": "B"}],
        whatsapp_groups=groups,
        checkins=[{"_id": "c1", "project_id": "proj_a", "company_id": CO_A,
                   "worker_id": "w1", "worker_name": "Luis Gomez",
                   "worker_phone": "718-555-0202"}],
        whatsapp_messages=[],
    )
    cols[server.WA_OPTINS] = [{"_id": "o1", "user_id": "u_pm", "company_id": CO_A,
                               "phone": "17185550303", "chat_digits": LID_PM,
                               "status": "active"}]
    cols.update(extra)
    return FakeDb(**cols)


_seq = [0]


def _msg(db, body, group=G_A, project="proj_a", company=CO_A, sender=MIKE,
         at=None, jid=None, **kw):
    _seq[0] += 1
    row = {"_id": ObjectId(), "group_id": group, "project_id": project,
           "company_id": company, "sender": sender, "body": body,
           "message_id": f"M{_seq[0]}", "mentioned_jids": [],
           "quoted_message_id": "", "quoted_author": "", "from_me": False,
           "created_at": at or T0 + timedelta(minutes=_seq[0])}
    if jid is not None:
        row["sender_jid"] = jid
    row.update(kw)
    db.whatsapp_messages.rows.append(row)
    return row


class _Model:
    """Stands in for gpt-4o-mini. `answers` maps a phrase in the >>> line to
    the items to return; everything else returns no items."""

    def __init__(self, answers=None, fail=False):
        self.answers = answers or {}
        self.calls = []
        self.fail = fail

    async def __call__(self, messages):
        user = messages[-1]["content"]
        self.calls.append(user)
        if self.fail:
            return None
        target = user.split(">>> ", 1)[1]
        for phrase, items in self.answers.items():
            if phrase in target:
                return {"content": json.dumps({"items": items}),
                        "prompt_tokens": 1500, "completion_tokens": 150}
        return {"content": json.dumps({"items": []}),
                "prompt_tokens": 1200, "completion_tokens": 10}


def _tick(db, model, now):
    sends = []

    async def no_send(*a, **k):
        sends.append((a, k))

    with patch.object(server, "db", db), \
            patch.object(server, "send_whatsapp_message", no_send), \
            patch.object(server, "send_whatsapp_dm", no_send), \
            patch.object(server, "_waapi_post_raw", no_send), \
            patch.dict(os.environ, {"WA_ATTENTION_DISABLED": ""}):
        report = _run(server._attention_tick(now=now, llm=model, probe=False))
    return report, sends


def _items(db):
    return db[server.ATTENTION_ITEMS].rows


def _first_sight(db, model=None):
    """The run that starts the cursors (no backfill)."""
    return _tick(db, model or _Model(), T0)


# ══════════════════════════════════════════════════════════════════════════
# Pure parts
# ══════════════════════════════════════════════════════════════════════════

class TheFilter(unittest.TestCase):

    def test_signals(self):
        self.assertEqual(wa.filter_reason({"body": "can you send the RFI?"}), "question_mark")
        self.assertEqual(wa.filter_reason({"body": "ok see you all", "mentioned_jids": ["1@c.us"]}), "mention")
        self.assertEqual(wa.filter_reason({"body": "yes that works", "quoted_message_id": "Q"}), "reply")
        self.assertEqual(wa.filter_reason({"body": "I'll bring the anchors tomorrow"}), "keyword")
        self.assertEqual(wa.filter_reason({"body": "there is a leak in 3B"}), "keyword")

    def test_noise_is_skipped(self):
        for body in ("good morning", "👍", "ok", "lunch is here guys"):
            self.assertIsNone(wa.filter_reason({"body": body}), body)
        self.assertIsNone(wa.filter_reason({"body": "who is here?", "sender": "bot"}))
        self.assertIsNone(wa.filter_reason({"body": "voice note?", "skipped": "voice_disabled"}))


class TheQuoteCheck(unittest.TestCase):

    def test_exact_piece_passes_and_returns_the_real_text(self):
        body = "Mike, can  you send the RFI for the stair? thx"
        self.assertEqual(wa.verify_quote("can you send the RFI for the stair?", body),
                         "can  you send the RFI for the stair?")

    def test_typography_and_case_are_forgiven(self):
        self.assertEqual(wa.verify_quote("we’ll pour FRIDAY", "We'll pour Friday"),
                         "We'll pour Friday")

    def test_one_changed_word_fails(self):
        self.assertIsNone(wa.verify_quote("can you send the RFI for the roof?",
                                          "can you send the RFI for the stair?"))
        self.assertIsNone(wa.verify_quote("send drawings", "please send the drawings"))
        self.assertIsNone(wa.verify_quote("", "anything"))


class TheDueDate(unittest.TestCase):

    def test_dates_the_code_can_read(self):
        thu = T0
        self.assertEqual(wa.parse_due("by Friday", thu), date(2026, 10, 9))
        self.assertEqual(wa.parse_due("by thursday", thu), date(2026, 10, 15))
        self.assertEqual(wa.parse_due("tomorrow morning", thu), date(2026, 10, 9))
        self.assertEqual(wa.parse_due("EOD", thu), date(2026, 10, 8))
        self.assertEqual(wa.parse_due("10/15", thu), date(2026, 10, 15))
        self.assertEqual(wa.parse_due("Oct 20th", thu), date(2026, 10, 20))
        self.assertEqual(wa.parse_due("1/5", datetime(2026, 12, 20, tzinfo=timezone.utc)),
                         date(2027, 1, 5))

    def test_vague_is_no_date(self):
        for t in ("next week", "ASAP", "soon", "when you can", None, "", "13/45"):
            self.assertIsNone(wa.parse_due(t, T0), t)


class ImportanceAndDedupe(unittest.TestCase):

    def test_high_only_when_the_message_states_it(self):
        self.assertEqual(wa.importance("normal", "URGENT the hoist is down"),
                         {"importance": "high", "importance_source": "stated"})
        self.assertEqual(wa.importance("low", "stop work on 4, unsafe scaffold")["importance"],
                         "high")
        # Never inferred from the topic, whatever the model says.
        for body in ("there's a leak on 4", "Inspection moved to Tuesday 10am",
                     "send the invoice"):
            self.assertEqual(wa.importance("high", body),
                             {"importance": "normal", "importance_source": "capped"}, body)
        self.assertEqual(wa.importance("low", "there's a leak on 4")["importance"], "low")
        self.assertEqual(wa.importance("bogus", "send it")["importance"], "normal")

    def test_an_issue_names_a_problem(self):
        for body in ("there's a leak on 4", "pour is delayed, pump broke",
                     "we can't get into the basement", "riser is 2 inches short"):
            self.assertTrue(wa.names_a_problem(body), body)
        for body in ("Inspection moved to Tuesday 10am",
                     "Mike from the elevator company will be here Wed",
                     "concrete pour Friday 7am"):
            self.assertFalse(wa.names_a_problem(body), body)

    def test_all_stop_word_quotes_stay_apart(self):
        a = wa.dedupe_key(G_A, "request", "u", "Can you do this?")
        b = wa.dedupe_key(G_A, "request", "u", "Would you do that?")
        self.assertNotEqual(a, b)
        self.assertEqual(a, wa.dedupe_key(G_A, "request", "u", "can you do this"))

    def test_same_ask_same_key(self):
        a = wa.dedupe_key(G_A, "request", "user:u1", "send the stair RFI please")
        b = wa.dedupe_key(G_A, "request", "user:u1", "Please send the stair RFI")
        c = wa.dedupe_key(G_A, "request", "user:u2", "send the stair RFI please")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class TheModelAnswer(unittest.TestCase):

    def test_malformed_items_are_dropped(self):
        out = wa.parse_items(json.dumps({"items": [
            {"type": "question", "quote": "x?"},
            {"type": "gossip", "quote": "y"},
            {"type": "request"},
            "junk",
            {"type": "issue", "quote": "leak", "importance": "urgent", "owner_text": "null"},
        ]}))
        self.assertEqual([i["type"] for i in out], ["question", "issue"])
        self.assertEqual(out[1]["importance"], "normal")
        self.assertIsNone(out[1]["owner_text"])
        self.assertEqual(wa.parse_items("not json"), [])

    def test_senders_reach_the_model_as_last_four_only(self):
        msgs = wa.build_messages({"sender": MIKE, "body": "can you?"},
                                 [{"sender": WORKER, "body": "hi"}])
        text = msgs[-1]["content"]
        self.assertNotIn(MIKE, text)
        self.assertNotIn(WORKER, text)
        self.assertIn("…0101", text)
        self.assertIn(">>> …0101: can you?", text)

    def test_nothing_is_postable(self):
        self.assertFalse(wa.postable({"type": "issue", "importance": "high"}))


class TheProbe(unittest.TestCase):

    def test_counts_only(self):
        payload = {"data": {"participants": [
            {"id": {"_serialized": "17185550101@c.us"}, "isAdmin": True},
            {"id": {"user": "123456789012345", "server": "lid"}},
            {"id": "222@lid"}, "weird"]}}
        out = wa.participant_counts(payload)
        self.assertEqual(out, {"found": 1, "total": 4, "phone": 1, "lid": 2,
                               "other": 1, "admins": 1})
        self.assertNotIn("7185550101", json.dumps(out))
        self.assertEqual(wa.participant_counts({"subject": "x"})["found"], 0)

    def test_the_log_line_has_no_ids(self):
        db = _world()
        logged = []

        async def info(gid):
            return {"participants": [{"id": {"_serialized": f"{MIKE}@c.us"}}]}

        with patch.object(server, "db", db), \
                patch.object(server, "_waapi_group_info", info), \
                patch.object(server.logger, "info", lambda m, *a, **k: logged.append(m)), \
                patch.dict(os.environ, {"WA_ATTENTION_DISABLED": ""}):
            _run(server._attention_tick(now=T0, llm=_Model(), probe=True))
            _run(server._attention_tick(now=T0 + timedelta(hours=1), llm=_Model(),
                                        probe=True))
        probes = [m for m in logged if "[wa-probe]" in m]
        # Once a day per bot-on group (A's and B's), not every run.
        self.assertEqual(len(probes), 2)
        self.assertTrue(all(MIKE not in m and "7185550101" not in m for m in probes))
        self.assertIn("'phone': 1", probes[0])


class TheWeeklyLine(unittest.TestCase):

    def test_line(self):
        line = wa.weekly_line({"week": "2026-W41", "group_id": G_A, "messages": 200,
                               "passed": 50, "calls": 50, "items": 8,
                               "prompt_tokens": 75000, "completion_tokens": 7500})
        self.assertIn("pass_rate=25%", line)
        self.assertIn("items=8", line)
        self.assertIn("tokens_in=75000", line)
        self.assertIn("cost_usd=0.0158", line)
        self.assertNotIn("120363000000000301", line)


# ══════════════════════════════════════════════════════════════════════════
# The job
# ══════════════════════════════════════════════════════════════════════════

ASK = [{"type": "request", "quote": "can you send the stair RFI by Friday?",
        "summary": "Send stair RFI", "owner_text": "Mike", "due_text": "by Friday",
        "importance": "normal", "tags": ["rfi"]}]


class ShadowModeAndCursor(unittest.TestCase):

    def test_no_backfill_history_is_never_read(self):
        db = _world()
        _msg(db, "old test chatter: can you send the stair RFI by Friday?",
             at=T0 - timedelta(days=3))
        model = _Model({"stair RFI": ASK})
        report, sends = _first_sight(db, model)
        self.assertEqual(model.calls, [])
        self.assertEqual(_items(db), [])
        self.assertEqual(report["new_groups"], 2)
        # And on later runs too.
        _tick(db, model, T0 + timedelta(hours=1))
        self.assertEqual(model.calls, [])

    def test_a_new_message_becomes_an_item_and_nothing_is_sent(self):
        db = _world()
        _first_sight(db)
        _msg(db, "Mike can you send the stair RFI by Friday?",
             mentioned_jids=[f"{MIKE}@c.us"], sender="17185550909")
        report, sends = _tick(db, _Model({"stair RFI": ASK}), T0 + timedelta(hours=1))
        self.assertEqual(sends, [])
        self.assertEqual(len(_items(db)), 1)
        it = _items(db)[0]
        self.assertEqual(it["type"], "request")
        self.assertEqual(it["evidence"]["quote"], "can you send the stair RFI by Friday?")
        self.assertEqual((it["company_id"], it["project_id"], it["group_id"]),
                         (CO_A, "proj_a", G_A))
        self.assertEqual(it["extraction"]["source"], "live")
        self.assertEqual(it["extraction"]["filter_reason"], "mention")
        self.assertEqual(it["due"], {"due_text": "by Friday", "due_at": "2026-10-09",
                                     "due_source": "parsed"})
        self.assertEqual(it["status"], "open")
        self.assertIsNone(it["review"])

    def test_each_message_once(self):
        db = _world()
        _first_sight(db)
        _msg(db, "can you send the stair RFI by Friday?")
        model = _Model({"stair RFI": ASK})
        _tick(db, model, T0 + timedelta(hours=1))
        _tick(db, model, T0 + timedelta(hours=2))
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(_items(db)), 1)

    def test_filtered_messages_cost_no_call(self):
        db = _world()
        _first_sight(db)
        _msg(db, "good morning everyone")
        _msg(db, "lunch truck is here")
        model = _Model()
        report, _ = _tick(db, model, T0 + timedelta(hours=1))
        self.assertEqual(model.calls, [])
        self.assertEqual(report["filtered_out"], 2)

    def test_disabled_by_env(self):
        db = _world()
        with patch.object(server, "db", db), \
                patch.dict(os.environ, {"WA_ATTENTION_DISABLED": "1"}):
            report = _run(server._attention_tick(now=T0, llm=_Model(), probe=False))
        self.assertEqual(report["groups"], 0)
        self.assertEqual(db[server.ATTENTION_CURSORS].rows, [])

    def test_no_model_key_does_nothing(self):
        db = _world()
        with patch.object(server, "db", db), \
                patch.object(server, "OPENAI_API_KEY", ""), \
                patch.dict(os.environ, {"WA_ATTENTION_DISABLED": ""}):
            report = _run(server._attention_tick(now=T0, probe=False))
        self.assertTrue(report["no_model"])
        self.assertEqual(db.attention_cursors.rows, [])

    def test_due_dates_count_from_when_it_was_sent(self):
        db = _world()
        _first_sight(db)
        # Sent Thursday 11 PM ET, stored Friday 1 AM ET after a delay.
        _msg(db, "can you send the stair RFI by tomorrow?",
             timestamp=datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc),
             at=datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc))
        _tick(db, _Model({"stair RFI": [{**ASK[0], "quote": "can you send the stair RFI by tomorrow?",
                                         "due_text": "by tomorrow"}]}),
              datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(_items(db)[0]["due"]["due_at"], "2026-10-09")

    def test_a_failed_write_is_retried_not_lost(self):
        db = _world()
        _first_sight(db)
        _msg(db, "can you send the stair RFI by Friday?")
        model = _Model({"stair RFI": ASK})
        real = db.attention_items.insert_one
        calls = [0]

        async def flaky(doc):
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("primary stepped down")
            return await real(doc)

        db.attention_items.insert_one = flaky
        report, _ = _tick(db, model, T0 + timedelta(hours=1))
        self.assertEqual(report["write_failed"], 1)
        self.assertEqual(_items(db), [])
        _tick(db, model, T0 + timedelta(hours=2))
        self.assertEqual(len(_items(db)), 1)
        self.assertEqual(_items(db)[0]["also_seen"], [])

    def test_a_failed_model_call_is_retried_then_skipped(self):
        db = _world()
        _first_sight(db)
        _msg(db, "can you send the stair RFI by Friday?")
        failing = _Model(fail=True)
        for h in (1, 2):
            _tick(db, failing, T0 + timedelta(hours=h))
        self.assertEqual(len(failing.calls), 2)
        report, _ = _tick(db, failing, T0 + timedelta(hours=3))
        self.assertEqual(report["skipped_failing"], 1)
        _tick(db, failing, T0 + timedelta(hours=4))
        self.assertEqual(len(failing.calls), 3)


class BotOffGroups(unittest.TestCase):

    def test_no_ai_processing_and_no_backlog_when_turned_on(self):
        db = _world()
        _first_sight(db)
        quiet = [g for g in db.whatsapp_groups.rows if g["_id"] == "g2"][0]
        quiet["bot_config"] = {"bot_enabled": True}
        _tick(db, _Model(), T0 + timedelta(minutes=30))     # cursor starts
        quiet["bot_config"] = {"bot_enabled": False}
        _msg(db, "can you send the stair RFI by Friday?", group=G_OFF,
             at=T0 + timedelta(hours=1))
        model = _Model({"stair RFI": ASK})
        report, _ = _tick(db, model, T0 + timedelta(hours=2))
        self.assertEqual(model.calls, [])
        self.assertGreaterEqual(report["bot_off"], 1)
        quiet["bot_config"] = {"bot_enabled": True}
        _tick(db, model, T0 + timedelta(hours=3))
        self.assertEqual(model.calls, [], "what was said while off never reaches a model")
        self.assertEqual(_items(db), [])


class TheEvidenceRule(unittest.TestCase):

    def test_a_paraphrased_quote_is_dropped(self):
        db = _world()
        _first_sight(db)
        _msg(db, "can you send the stair RFI by Friday?")
        model = _Model({"stair RFI": [{**ASK[0], "quote": "please send the RFI for the stairs"}]})
        report, _ = _tick(db, model, T0 + timedelta(hours=1))
        self.assertEqual(_items(db), [])
        self.assertEqual(report["dropped_unverified"], 1)

    def test_owner_and_due_words_must_be_in_the_message(self):
        db = _world()
        _first_sight(db)
        _msg(db, "can you send the stair RFI?")
        model = _Model({"stair RFI": [{**ASK[0], "quote": "can you send the stair RFI?",
                                       "owner_text": "Jimmy", "due_text": "by Monday"}]})
        _tick(db, model, T0 + timedelta(hours=1))
        it = _items(db)[0]
        self.assertIsNone(it["owner"]["owner_text"])
        self.assertEqual(it["due"], {"due_text": None, "due_at": None, "due_source": "none"})


class OwnerResolution(unittest.TestCase):

    def _one(self, **msg):
        db = _world()
        _first_sight(db)
        _msg(db, "can you send the stair RFI by Friday?", **msg)
        _tick(db, _Model({"stair RFI": ASK}), T0 + timedelta(hours=1))
        return _items(db)[0]

    def test_a_mentioned_user_of_the_company(self):
        it = self._one(mentioned_jids=[f"{MIKE}@c.us"], sender="17185550909")
        self.assertEqual((it["owner"]["kind"], it["owner"]["id"], it["owner"]["status"],
                          it["owner"]["source"]), ("user", "u_mike", "resolved", "mention"))

    def test_a_worker_who_checked_in_at_this_project(self):
        it = self._one(mentioned_jids=[f"{WORKER}@c.us"])
        self.assertEqual((it["owner"]["kind"], it["owner"]["id"], it["owner"]["name"]),
                         ("worker", "w1", "Luis Gomez"))

    def test_an_unmapped_lid_keeps_the_jid_and_the_words(self):
        it = self._one(mentioned_jids=[f"{LID}@lid"])
        self.assertEqual(it["owner"]["status"], "unresolved")
        self.assertEqual(it["owner"]["jid"], f"{LID}@lid")
        self.assertEqual(it["owner"]["reason"], "lid_unmapped")
        self.assertIsNone(it["owner"]["id"])

    def test_a_lid_with_an_opt_in_resolves_to_that_user(self):
        it = self._one(mentioned_jids=[f"{LID_PM}@lid"])
        self.assertEqual((it["owner"]["kind"], it["owner"]["id"]), ("user", "u_pm"))

    def test_another_companys_user_is_never_matched(self):
        it = self._one(mentioned_jids=["17185550404@c.us"])
        self.assertEqual(it["owner"]["status"], "unresolved")
        self.assertIsNone(it["owner"]["id"])

    def test_a_reply_author_owns_a_question(self):
        it = self._one(quoted_author=f"{MIKE}@c.us", quoted_message_id="Q1")
        self.assertEqual((it["owner"]["id"], it["owner"]["source"]),
                         ("u_mike", "reply_author"))

    def test_a_commitment_is_owned_by_its_sender(self):
        db = _world()
        _first_sight(db)
        _msg(db, "I'll bring the anchors tomorrow", sender=LID,
             jid=f"{LID}@lid")
        _tick(db, _Model({"anchors": [{"type": "commitment",
                                       "quote": "I'll bring the anchors tomorrow",
                                       "due_text": "tomorrow"}]}),
              T0 + timedelta(hours=1))
        it = _items(db)[0]
        self.assertEqual((it["owner"]["source"], it["owner"]["jid"], it["owner"]["status"]),
                         ("sender", f"{LID}@lid", "unresolved"))

    def test_an_old_row_with_only_digits_is_read_by_length(self):
        self.assertEqual(wa.sender_jid({"sender": LID}), f"{LID}@lid")
        self.assertEqual(wa.sender_jid({"sender": MIKE}), f"{MIKE}@c.us")
        self.assertEqual(wa.sender_jid({"sender": MIKE, "sender_jid": f"{MIKE}@c.us"}),
                         f"{MIKE}@c.us")


class TenantScope(unittest.TestCase):

    def test_context_and_items_stay_inside_the_binding(self):
        db = _world()
        _first_sight(db)
        # A row in A's group stamped with another project must not be read.
        _msg(db, "SECRET can you send the B drawings?", project="proj_b", company=CO_B)
        _msg(db, "can you send the stair RFI by Friday?")
        model = _Model({"stair RFI": ASK, "B drawings": ASK})
        _tick(db, model, T0 + timedelta(hours=1))
        self.assertTrue(all("SECRET" not in c for c in model.calls))
        self.assertEqual({(i["company_id"], i["project_id"]) for i in _items(db)},
                         {(CO_A, "proj_a")})

    def test_a_duplicated_group_binding_is_skipped(self):
        db = _world(bot_off_group=False)
        db.whatsapp_groups.rows.append(
            {"_id": "g9", "wa_group_id": G_A, "project_id": "proj_b",
             "company_id": CO_B, "active": True})
        warned = []
        with patch.object(server.logger, "warning", lambda m, *a, **k: warned.append(m)):
            report, _ = _first_sight(db)
        self.assertNotIn(f"{G_A}|proj_a", [c["_id"] for c in db[server.ATTENTION_CURSORS].rows])
        # Quiet: the 5-minute job does not repeat the message path's
        # security event for a duplicated group.
        self.assertEqual(warned, [])


class DedupeAndReplies(unittest.TestCase):

    def test_the_same_ask_twice_is_one_item(self):
        db = _world()
        _first_sight(db)
        _msg(db, "can you send the stair RFI by Friday?")
        _msg(db, "again: can you send the stair RFI by Friday?")
        _tick(db, _Model({"stair RFI": ASK}), T0 + timedelta(hours=1))
        self.assertEqual(len(_items(db)), 1)
        self.assertEqual(len(_items(db)[0]["also_seen"]), 1)

    def test_a_reply_marks_possibly_resolved_never_closed(self):
        db = _world()
        _first_sight(db)
        # Times pinned: _msg's default clock follows how many rows earlier
        # tests made, which could put the ask after its own reply.
        ask = _msg(db, "can you send the stair RFI by Friday?", sender="17185550909",
                   at=T0 + timedelta(minutes=30))
        _tick(db, _Model({"stair RFI": ASK}), T0 + timedelta(hours=1))
        _msg(db, "sent it this morning", quoted_message_id=ask["message_id"],
             at=T0 + timedelta(hours=2))
        _tick(db, _Model(), T0 + timedelta(hours=3))
        it = _items(db)[0]
        # The ask named nobody, so who replied "sent" may or may not be who
        # owed it: possibly done, for an admin, with the words.
        self.assertEqual(it["status"], "possibly_done")
        self.assertEqual(it["history"][-1]["quote"], "sent it this morning")
        self.assertEqual(it["history"][-1]["link"], "reply")

    def test_the_asker_replying_to_themself_is_not_an_answer(self):
        db = _world()
        _first_sight(db)
        ask = _msg(db, "can you send the stair RFI by Friday?")
        _tick(db, _Model({"stair RFI": ASK}), T0 + timedelta(hours=1))
        _msg(db, "bump", quoted_message_id=ask["message_id"],
             at=T0 + timedelta(hours=2))
        _tick(db, _Model(), T0 + timedelta(hours=3))
        self.assertEqual(_items(db)[0]["status"], "open")


class TheMetrics(unittest.TestCase):

    def test_counters_and_weekly_line(self):
        db = _world()
        _first_sight(db)
        _msg(db, "good morning")
        _msg(db, "can you send the stair RFI by Friday?")
        _tick(db, _Model({"stair RFI": ASK}), T0 + timedelta(hours=1))
        rows = db[server.ATTENTION_METRICS].rows
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["messages"], r["passed"], r["calls"], r["items"],
                          r["prompt_tokens"], r["completion_tokens"]),
                         (2, 1, 1, 1, 1500, 150))
        logged = []
        with patch.object(server, "db", db), \
                patch.object(server.logger, "info", lambda m, *a, **k: logged.append(m)):
            lines = _run(server._attention_weekly_metrics(now=T0 + timedelta(days=7)))
        self.assertEqual(len(lines), 2)
        self.assertIn("pass_rate=50%", lines[0])
        self.assertTrue(any("group=ALL" in m for m in logged))


class TheReviewEndpoints(unittest.TestCase):

    def _db_with_item(self):
        db = _world()
        _first_sight(db)
        _msg(db, "Mike can you send the stair RFI by Friday?",
             mentioned_jids=[f"{LID}@lid"])
        _tick(db, _Model({"stair RFI": ASK}), T0 + timedelta(hours=1))
        return db

    def test_admin_sees_items_and_precision(self):
        db = self._db_with_item()
        with patch.object(server, "db", db):
            out = _run(server.get_project_attention("proj_a", current_user=ADMIN))
        self.assertTrue(out["shadow_mode"])
        self.assertEqual(len(out["items"]), 1)
        v = out["items"][0]
        self.assertEqual(v["owner"], "Mike")          # the words used
        self.assertEqual(v["owner_status"], "unresolved")
        self.assertEqual(v["group_name"], "Main St Project")
        self.assertNotIn(LID, json.dumps(v))
        self.assertNotIn(MIKE, json.dumps(v))
        self.assertEqual(out["precision"]["request"]["precision"], None)

    def test_verdicts_feed_precision_and_dismiss_leaves_the_list(self):
        db = self._db_with_item()
        item_id = str(_items(db)[0]["_id"])
        with patch.object(server, "db", db):
            v = _run(server.review_project_attention(
                "proj_a", item_id, {"verdict": "correct"}, current_user=ADMIN))
            self.assertEqual(v["verdict"], "correct")
            out = _run(server.get_project_attention("proj_a", current_user=ADMIN))
            self.assertEqual(out["items"], [])         # reviewed: off the open list
            self.assertEqual(out["precision"]["request"]["precision"], 1.0)
            _run(server.review_project_attention(
                "proj_a", item_id, {"verdict": "dismissed"}, current_user=ADMIN))
        self.assertEqual(_items(db)[0]["status"], "dismissed")

    def test_not_an_admin_or_another_company(self):
        db = self._db_with_item()
        item_id = str(_items(db)[0]["_id"])
        with patch.object(server, "db", db):
            for user, code in ((PM, 403), (ADMIN_B, 404)):
                with self.assertRaises(HTTPException) as e:
                    _run(server.get_project_attention("proj_a", current_user=user))
                self.assertEqual(e.exception.status_code, code)
                with self.assertRaises(HTTPException) as e:
                    _run(server.review_project_attention(
                        "proj_a", item_id, {"verdict": "wrong"}, current_user=user))
                self.assertEqual(e.exception.status_code, code)
            with self.assertRaises(HTTPException) as e:
                _run(server.review_project_attention(
                    "proj_a", item_id, {"verdict": "maybe"}, current_user=ADMIN))
            self.assertEqual(e.exception.status_code, 422)
        self.assertIsNone(_items(db)[0]["review"])


class Wiring(unittest.TestCase):

    def test_not_called_from_the_webhook(self):
        import inspect
        src = inspect.getsource(server._process_whatsapp_message)
        self.assertNotRegex(src, r"\b_attention_\w+\(")

    def test_scheduled(self):
        src = Path(server.__file__).read_text()
        self.assertIn("id='whatsapp_attention'", src)
        self.assertIn("id='whatsapp_attention_weekly'", src)

    def test_the_engine_has_no_send_call(self):
        import inspect
        for fn in (server._attention_tick, server._attention_process,
                   server._attention_run_group, server._attention_probe,
                   server._attention_mark_replies, server._attention_resolve):
            src = inspect.getsource(fn)
            for banned in ("send_whatsapp", "_react", "send-message"):
                self.assertNotIn(banned, src, f"{fn.__name__} mentions {banned}")


if __name__ == "__main__":
    unittest.main()
