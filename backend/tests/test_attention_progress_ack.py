"""'Working on it' is progress on the item it replies to, never a new item
(588, Oct 11, live: the model made it a new commitment).

  * Read by code before the model: a reply (or a quoted-body link) to an
    open item, or to its chase nudge, that only says work is under way is a
    "progress" line on THAT item's timeline -- no model call, no item.
  * The code-side guard: whatever the model makes of it, never an item.
  * It changes nothing: status, due, chase (rule 1 is not triggered; it is
    rule 2's ack), state precision.
  * Unlinked, it goes on as before.
  * The chase never nudges an item whose words are only an ack.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import wa_attention, wa_attention_state as was, wa_chase  # noqa: E402
from tests.test_whatsapp_attention import (  # noqa: E402
    CO_A, G_A, T0, MIKE, _Model, _first_sight, _items, _msg, _run, _tick, _world)

ASK = {"steel shop drawings": [{"type": "request", "quote": "can you send the steel shop drawings",
                                "summary": "Send the steel shop drawings", "owner_text": None,
                                "due_text": None, "importance": "normal", "tags": []}]}
# What gpt-4o answered live for the reply.
MISREAD = {"Working on it": [{"type": "commitment", "quote": "Working on it",
                              "summary": "Working on it", "owner_text": None, "due_text": None,
                              "importance": "normal", "tags": []}]}
OTHER = "17185550199"


def _open_item(db):
    _first_sight(db)
    ask = _msg(db, "@Mike can you send the steel shop drawings by Friday?", sender=OTHER,
               mentioned_jids=[f"{MIKE}@c.us"])
    _tick(db, _Model(ASK), T0 + timedelta(hours=1))
    items = [i for i in _items(db) if i["type"] == "request"]
    assert len(items) == 1, _items(db)
    return ask, items[0]


class TheWords(unittest.TestCase):

    def test_progress_and_not(self):
        for t in ("Working on it", "working on it 👍", "on my way", "almost done",
                  "Estoy en eso", "trabajando en eso", "casi listo jefe",
                  "ikh arbet oyf dem", "איך ארבעט אויף דעם"):
            self.assertTrue(was.progress_ack(t), t)
        for t in ("ok", "np", "Done", "Working on it, done by 3?", "Working on the rebar tomorrow",
                  "I'll send them Friday", "", "Sent this morning"):
            self.assertFalse(was.progress_ack(t), t)
        # Taking it on: progress only under a commitment (under a request it
        # IS the commitment); the chase counts it either way.
        for t in ("On it", "I'm on it boss", "will do", "ya voy"):
            self.assertFalse(was.progress_ack(t), t)
            self.assertFalse(was.progress_ack(t, "request"), t)
            self.assertTrue(was.progress_ack(t, "commitment"), t)
            self.assertTrue(was.progress_ack(t, accept=True), t)


class OnTheItemItRepliesTo(unittest.TestCase):

    def test_a_reply_is_progress_on_the_parent_and_the_model_is_not_asked(self):
        db = _world()
        ask, item = _open_item(db)
        _msg(db, "Working on it", sender=MIKE, quoted_message_id=ask["message_id"])
        model = _Model(MISREAD)
        report, sends = _tick(db, model, T0 + timedelta(hours=2))
        self.assertEqual(report["progress"], 1)
        self.assertFalse([c for c in model.calls if "Working on it" in c])
        self.assertEqual([i["type"] for i in _items(db)], ["request"])      # no new item
        it = _items(db)[0]
        prog = [h for h in it["history"] if h["kind"] == was.PROGRESS]
        self.assertEqual(len(prog), 1)
        self.assertEqual(prog[0]["quote"], "Working on it")
        self.assertEqual(it["status"], item["status"])                     # nothing else moved
        self.assertEqual(it.get("due"), item.get("due"))
        self.assertEqual(sends, [])

    def test_the_guard_drops_the_models_item_even_inside_a_longer_message(self):
        db = _world()
        ask, _ = _open_item(db)
        _msg(db, "Working on it. Also need 20 sheets of plywood Monday", sender=MIKE,
             quoted_message_id=ask["message_id"])
        model = _Model({"plywood": MISREAD["Working on it"] + [
            {"type": "request", "quote": "need 20 sheets of plywood Monday",
             "summary": "20 sheets of plywood Monday", "owner_text": None,
             "due_text": "Monday", "importance": "normal", "tags": []}]})
        report, _ = _tick(db, model, T0 + timedelta(hours=2))
        types = sorted(i["type"] for i in _items(db))
        self.assertEqual(types, ["request", "request"])          # the plywood ask, kept
        self.assertEqual(report.get("dropped_progress"), 1)
        parent = next(i for i in _items(db) if "steel" in i["summary"].lower())
        self.assertEqual([h["kind"] for h in parent["history"]].count(was.PROGRESS), 1)

    def test_a_reply_to_its_chase_nudge_counts_too(self):
        db = _world()
        _, item = _open_item(db)
        db[wa_chase.COLLECTION].rows.append({
            "_id": "n1", "group_id": G_A, "message_id": "NUDGE77", "item_ids": [str(item["_id"])],
            "at": T0 + timedelta(hours=1, minutes=30)})
        _msg(db, "working on it", sender=MIKE, quoted_message_id="NUDGE77")
        _tick(db, _Model(MISREAD), T0 + timedelta(hours=2))
        self.assertEqual(len(_items(db)), 1)
        self.assertEqual([h["kind"] for h in _items(db)[0]["history"]].count(was.PROGRESS), 1)

    def test_unlinked_it_goes_on_as_before(self):
        db = _world()
        _open_item(db)
        _msg(db, "Working on it", sender=MIKE)          # no reply, no quote
        _tick(db, _Model(MISREAD), T0 + timedelta(hours=2))
        self.assertFalse([h for i in _items(db) for h in i["history"]
                          if h["kind"] == was.PROGRESS])

    def test_progress_under_a_question_does_not_answer_it(self):
        db = _world()
        _first_sight(db)
        q = _msg(db, "who has the gang box key for the 3rd floor?", sender=OTHER)
        _tick(db, _Model({"gang box key": [{"type": "question",
                                            "quote": "who has the gang box key for the 3rd floor?",
                                            "summary": "Who has the gang box key",
                                            "owner_text": None, "due_text": None,
                                            "importance": "normal", "tags": []}]}),
              T0 + timedelta(hours=1))
        _msg(db, "Working on it", sender=MIKE, quoted_message_id=q["message_id"])
        _tick(db, _Model(MISREAD), T0 + timedelta(hours=2))
        (it,) = _items(db)
        self.assertEqual(it["status"], "open")              # not "possibly answered"
        self.assertEqual([h["kind"] for h in it["history"]].count(was.PROGRESS), 1)

    def test_a_closed_item_is_not_written_to(self):
        db = _world()
        ask, item = _open_item(db)
        db[server.ATTENTION_ITEMS].rows[0]["status"] = "done"
        _msg(db, "Working on it", sender=MIKE, quoted_message_id=ask["message_id"])
        _tick(db, _Model({}), T0 + timedelta(hours=2))
        self.assertFalse([h for h in _items(db)[0]["history"] if h["kind"] == was.PROGRESS])


class ItChangesNothing(unittest.TestCase):

    def test_not_a_chase_stop_not_precision_not_a_replay_change(self):
        first = T0 + timedelta(hours=1)
        item = {"history": [{"kind": "created", "at": T0},
                            {"kind": was.PROGRESS, "at": first + timedelta(minutes=5)}]}
        self.assertIsNone(wa_chase.stop_reason(item, [{"at": first}]))
        self.assertEqual(was.state_precision([dict(item, type="request")]), {})
        self.assertFalse(server._attention_changed_since(item, first))
        self.assertIn(was.PROGRESS, was.NO_CHANGE_KINDS)

    def test_the_prompt_says_so_and_its_version_moved(self):
        self.assertEqual(wa_attention.PROMPT_VERSION.split()[0], "att-v1.4")
        self.assertIn('"Working on it"', wa_attention.SYSTEM_PROMPT)


class TheChaseNeverNudgesAnAck(unittest.TestCase):

    def _item(self, quote, summary):
        from datetime import date
        return {"type": "commitment", "status": "open", "summary": summary,
                "evidence": {"quote": quote, "message_id": "M1"},
                "extraction": {"prompt_version": wa_attention.PROMPT_VERSION},
                "owner": {"status": "resolved", "id": "u1", "kind": "user", "jid": "1@c.us"},
                "due": {"due_text": "today", "due_at": "2026-10-11T21:00:00+00:00"}}, \
            date(2026, 10, 11)

    def test_the_live_item_is_not_chased(self):
        it, day = self._item("Working on it", "Working on it")
        self.assertEqual(wa_chase.skip_reason(it, day), wa_chase.ACK_ONLY)
        for q in ("on it", "ok", "Np", "estoy en eso", "will do"):
            it, day = self._item(q, q)
            self.assertEqual(wa_chase.skip_reason(it, day), wa_chase.ACK_ONLY, q)

    def test_a_yes_under_an_ask_is_chased_with_the_asks_words(self):
        ask = {"type": "request", "evidence": {"quote": "please send the lighting cut sheets",
                                               "message_id": "M0"}}
        it, day = self._item("on it", "Will do: Send the lighting cut sheets by Friday")
        self.assertIsNone(wa_chase.skip_reason(it, day, ask))
        self.assertEqual(wa_chase.ask_quote(it, ask)["quote"], "please send the lighting cut sheets")
        # Under anything but an ask (a commitment, an issue) or nothing: not chased.
        self.assertEqual(wa_chase.skip_reason(it, day, dict(ask, type="commitment")),
                         wa_chase.ACK_ONLY)
        self.assertEqual(wa_chase.skip_reason(it, day), wa_chase.ACK_ONLY)

    def test_real_words_are_chased_as_before(self):
        it, day = self._item("I'll send the risers today", "Send the risers")
        self.assertIsNone(wa_chase.skip_reason(it, day))
        self.assertIsNone(wa_chase.ask_quote(it, {"type": "request", "evidence": {
            "quote": "x", "message_id": "M0"}}))


if __name__ == "__main__":
    unittest.main()
