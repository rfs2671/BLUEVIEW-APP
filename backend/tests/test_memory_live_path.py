"""Project memory on the LIVE path (588, Oct 11).

DM 10:08 AM Sun: "what did we decide about the core drill?" -> 588 -> "I
can't find that in the project history." The group held the question about
the core drill, never a decision.

  * A message that arrives through the WhatsApp webhook (the real
    _process_whatsapp_message, a WaAPI-shaped payload) is indexed by the
    memory tick and found by search -- not only rows seeded by the evals.
  * A row stored AFTER the cursor moved past its created_at (a voice note's
    Whisper call runs between the two) is still indexed.
  * Nothing answers it but the subject was mentioned: "No decision found.
    Last mention: Meilich asked '…' (Sat 3:12 PM)." -- never a bare
    NO_SOURCE over on-topic records.
"""

from __future__ import annotations

import asyncio
import json
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
from lib import project_memory as pm  # noqa: E402
from scripts import memory_dry_run as dry  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx, _db  # noqa: E402

CO = "co_a"
JOB = "proj_a"
GROUP = "120363000000000588@g.us"
MEILICH = "15550007788"   # not in People: the WhatsApp name shows
# Sat Oct 10 2026, 3:12 PM in New York.
SAT_312PM = datetime(2026, 10, 10, 19, 12, tzinfo=timezone.utc)
QUESTION = "Who is doing the core drill for the sprinkler sleeves on 3?"


def _run(coro):
    return asyncio.run(coro)


async def _embed(texts):
    return [dry.hashed_vector(t) for t in texts]


def _payload(msg_id, body, at=SAT_312PM, author=MEILICH, name="Meilich"):
    """What WaAPI posts for a group text (message event, wweb.js shape)."""
    return {"event": "message", "instanceId": "inst", "data": {"message": {
        "id": {"fromMe": False, "remote": GROUP, "id": msg_id,
               "participant": f"{author}@c.us",
               "_serialized": f"false_{GROUP}_{msg_id}_{author}@c.us"},
        "from": GROUP, "to": "15550000000@c.us", "author": f"{author}@c.us",
        "body": body, "type": "chat", "timestamp": int(at.timestamp()),
        "notifyName": name, "_data": {"notifyName": name},
        "hasMedia": False, "fromMe": False, "isForwarded": False,
        "mentionedIds": [], "hasQuotedMsg": False}}}


def _world():
    cfg = server._default_bot_config()
    for k in ("material_detection",):
        cfg["features"][k] = False
    return _db(whatsapp_groups=[{
        "_id": "g588", "wa_group_id": GROUP, "company_id": CO, "project_id": JOB,
        "group_name": "588 – Site", "active": True,
        "linked_at": SAT_312PM - timedelta(days=30), "bot_config": cfg}])


class _Live:
    """The webhook, the memory tick and the search on one fake database."""

    def __init__(self):
        self.ctx = _Ctx(_world())
        self.extra = [patch.object(server, "_memory_embed_many", _embed),
                      patch.object(server, "MEMORY_EMBED_PAUSE", 0),
                      patch.dict(server._MEMORY_ATLAS, {"ok": False, "retry_at": None})]

    def __enter__(self):
        self.ctx.__enter__()
        for p in self.extra:
            p.start()
        return self

    def __exit__(self, *a):
        for p in reversed(self.extra):
            p.stop()
        self.ctx.__exit__(*a)

    @property
    def db(self):
        return self.ctx.db

    def webhook(self, payload):
        async def agent(**kw):
            return None
        with patch.object(server, "_run_group_agent", agent):
            _run(server._process_whatsapp_message(payload))

    def tick(self, now=None):
        return _run(server._memory_index_tick(now or SAT_312PM + timedelta(hours=1)))


class AWebhookMessageIsSearchable(unittest.TestCase):

    def test_webhook_then_tick_then_search_finds_it(self):
        with _Live() as w:
            w.webhook(_payload("M588A", QUESTION))
            stored = [r for r in w.db.whatsapp_messages.rows if r.get("sender") != "bot"]
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["project_id"], JOB)
            self.assertEqual(str(stored[0]["company_id"]), CO)
            rep = w.tick()
            self.assertEqual(rep["messages"], 1)
            self.assertEqual(rep["embedded"], 1)
            doc = w.db.project_memory.rows[0]
            self.assertEqual((doc["project_id"], doc["company_id"]), (JOB, CO))
            self.assertTrue(doc["embedded"])
            rows = _run(server._memory_search(CO, JOB, "what did we decide about the core drill?"))
            self.assertEqual([r["text"] for r in rows], [QUESTION])
            # Scoped: another company, or another job, finds nothing.
            self.assertEqual(_run(server._memory_search("co_b", JOB, "core drill")), [])
            self.assertEqual(_run(server._memory_search(CO, "proj_b", "core drill")), [])

    def test_the_dm_answer_quotes_the_question_when_nothing_was_decided(self):
        async def no_claims(messages):
            return json.dumps({"claims": []})     # what gpt-4o said: no decision
        with _Live() as w:
            w.webhook(_payload("M588A", QUESTION))
            w.tick()
            got = _run(server._memory_answer(
                CO, JOB, "what did we decide about the core drill?", llm=no_claims))
        self.assertEqual(got["claims"], [])
        self.assertNotEqual(got["text"], pm.NO_SOURCE)
        self.assertEqual(
            got["text"],
            f"No decision found. Last mention: Meilich asked '{QUESTION}' (Sat 3:12 PM).")
        self.assertEqual(got["texts"]["full"], got["text"])

    def test_a_row_stored_after_the_cursor_passed_is_still_indexed(self):
        with _Live() as w:
            # A voice note: created_at taken at 3:12:00, stored after Whisper.
            # Meanwhile a text at 3:12:20 is stored and a tick runs.
            w.webhook(_payload("M588B", "Concrete truck at the gate", at=SAT_312PM))
            w.db.whatsapp_messages.rows[-1]["created_at"] = SAT_312PM + timedelta(seconds=20)
            w.tick()
            late = dict(w.db.whatsapp_messages.rows[-1], _id="late1", message_id="M588C",
                        body=QUESTION, created_at=SAT_312PM, timestamp=SAT_312PM)
            w.db.whatsapp_messages.rows.append(late)
            rep = w.tick()
            self.assertEqual(rep.get("late"), 1)
            self.assertIn("wa:late1", {d["_id"] for d in w.db.project_memory.rows})
            # The cursor did not go back.
            state = w.db.project_memory_state.rows[0]
            self.assertEqual(state["wa_at"].replace(tzinfo=timezone.utc),
                             SAT_312PM + timedelta(seconds=20))
            # And a third tick does not read it again.
            self.assertIsNone(w.tick().get("late"))


    def test_a_late_row_past_the_first_page_of_the_window_is_found(self):
        with _Live() as w:
            w.webhook(_payload("M588B", "Concrete truck at the gate", at=SAT_312PM))
            base = w.db.whatsapp_messages.rows[-1]
            base["created_at"] = SAT_312PM + timedelta(minutes=5)
            # A busy window: five indexed rows before the late one.
            for i in range(5):
                w.db.whatsapp_messages.rows.append(dict(
                    base, _id=f"busy{i}", message_id=f"B{i}", body=f"Truck {i} unloading",
                    created_at=SAT_312PM + timedelta(seconds=i)))
            w.tick()
            w.db.whatsapp_messages.rows.append(dict(
                base, _id="late2", message_id="M588D", body=QUESTION,
                created_at=SAT_312PM + timedelta(minutes=1)))
            with patch.object(server, "MEMORY_SCAN_PER_RUN", 2):
                rep = w.tick()
            self.assertEqual(rep.get("late"), 1)
            self.assertIn("wa:late2", {d["_id"] for d in w.db.project_memory.rows})


class LastMention(unittest.TestCase):

    def _src(self, text, who="Meilich", at=SAT_312PM, source="whatsapp"):
        ny = at.astimezone(server._MEMORY_NY)
        return {"sid": "S1", "source": source, "text": text, "who": who, "ny": ny,
                "at": at, "day_label": f"{ny:%b} {ny.day}"}

    def test_off_topic_records_leave_no_source(self):
        srcs = [self._src("Drill bits are in the gang box"),
                self._src("We decided to pour Friday")]
        self.assertEqual(pm.last_mention_line("what did we decide about the core drill?", srcs), "")

    def test_the_newest_on_topic_mention_wins_and_a_statement_is_said(self):
        srcs = [self._src(QUESTION),
                self._src("Rivera's guys will core drill Tuesday. Bring the water vac.",
                          who="Dave", at=SAT_312PM + timedelta(minutes=40))]
        self.assertEqual(
            pm.last_mention_line("what did we decide about the core drill?", srcs),
            "No decision found. Last mention: Dave said \"Rivera's guys will core drill Tuesday.\""
            .replace('"', "'") + " (Sat 3:52 PM).")

    def test_not_a_decision_question(self):
        line = pm.last_mention_line("who has the core drilling?", [self._src(QUESTION)])
        self.assertTrue(line.startswith("No answer found. Last mention:"))

    def test_finally_is_not_a_decision_question(self):
        line = pm.last_mention_line("what finally happened with the core drill?",
                                    [self._src(QUESTION)])
        self.assertTrue(line.startswith("No answer found."), line)
        self.assertTrue(pm.last_mention_line("final call on the core drill?",
                                             [self._src(QUESTION)]).startswith("No decision found."))

    def test_a_multiline_message_quotes_the_line_that_names_it(self):
        text = ("Morning all\n" + "Lots of deliveries today, gate is busy " * 6
                + "\nWho is doing the core drill on 3")
        line = pm.last_mention_line("what did we decide about the core drill?",
                                    [self._src(text)])
        self.assertIn("asked 'Who is doing the core drill on 3'", line)

    def test_daily_report(self):
        line = pm.last_mention_line("core drill decision?", [self._src(
            "Core drill on 3 postponed, waiting on sleeves", who="", source="daily_report")])
        self.assertEqual(line, "No decision found. Last mention: the daily report noted "
                               "'Core drill on 3 postponed, waiting on sleeves' (Oct 10).")


if __name__ == "__main__":
    unittest.main()
