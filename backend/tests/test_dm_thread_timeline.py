"""scripts/dm_thread_timeline.py: one person's DM day, step by step, READ-ONLY.

Run against a fake database shaped like production's rows: an Oct 27 588
question with an answer row written BEFORE per-step timing existed, a "?"
and its answer row WITH timing. Asserted: each message is paired with its
answer row, the old row says it has no per-step times, the new row's rounds,
tools, records and first send are printed, other tools' results are not, no
phone number reaches the output or the JSON file, and nothing is written.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

import dm_thread_timeline as tl  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

PHONE = "17185550142"
CHAT = f"{PHONE}@c.us"
OTHER_WORDS = "Meilich said the foam crew is late"


def at(h, m, s=0):
    # 2026-10-27 is EDT (UTC-4)
    return datetime(2026, 10, 27, h + 4, m, s, tzinfo=timezone.utc)


def _db():
    db = FakeDb(
        users=[{"_id": "u_roy", "email": "roy@x.com", "name": "Roy", "role": "admin",
                "phone": "+" + PHONE, "company_id": "co"}],
        whatsapp_optins=[{"_id": "o1", "user_id": "u_roy", "status": "active", "phone": PHONE}],
        punch_sessions=[
            {"_id": "w1", "user_id": "u_roy", "status": "capturing", "job_name": "588 Thomas",
             "created_at": at(9, 0), "updated_at": at(10, 40)},
            {"_id": "w0", "user_id": "u_roy", "status": "sent", "job_name": "Old",
             "created_at": at(9, 0) - timedelta(days=3), "updated_at": at(9, 0) - timedelta(days=3)}],
        whatsapp_messages=[
            {"_id": "m1", "group_id": CHAT, "is_dm": True, "user_id": "u_roy", "sender": PHONE,
             "from_me": False, "body": "Spray foam on 5th floor ceiling?",
             "message_id": f"false_{CHAT}_AAA111", "created_at": at(10, 36, 5)},
            {"_id": "m2", "group_id": CHAT, "is_dm": True, "user_id": "u_roy", "sender": PHONE,
             "from_me": False, "body": "?", "message_id": f"false_{CHAT}_BBB222",
             "created_at": at(10, 42, 50)},
            {"_id": "b1", "group_id": CHAT, "is_dm": True, "sender": "bot", "from_me": True,
             "body": "Spray foam at the 5th floor ceiling: 2\" closed cell, A-501.",
             "created_at": at(10, 43, 2)},
        ],
        whatsapp_dm_answers=[
            {"_id": "a1", "user_id": "u_roy", "company_id": "co", "path": "brain",
             "question": "Spray foam on 5th floor ceiling?",
             "answer": "Spray foam at the 5th floor ceiling: 2\" closed cell, A-501.",
             "model": "m", "rounds": 3, "stop": "stop", "fallback": False, "reason": "answered",
             "usage": {"calls": 3, "seconds": 401.2, "input": 9000, "output": 900, "models": ["m"]},
             "tool_data": [
                 {"tool": "search_plans", "args": {"subject": "spray foam", "floor": "5"},
                  "result": "Records for 'spray foam'.\n- A-501: \"2 IN CLOSED CELL SPRAY FOAM\""},
                 {"tool": "search_project_history", "args": {"query": "foam"},
                  "result": OTHER_WORDS + " call " + PHONE}],
             "created_at": at(10, 43, 1)},
            {"_id": "a2", "user_id": "u_roy", "company_id": "co", "path": "brain",
             "question": "?", "answer": "Which part?", "model": "m", "rounds": 1, "stop": "stop",
             "tool_data": [{"tool": "search_plans", "args": {"subject": "roof"}, "result": "x",
                            "round": 1, "t_ms": 3100, "ms": 900,
                            "records": [{"sheet": "A-701", "file": "Arch.pdf", "page": 12,
                                         "set": "IFC", "quote": "ROOF DETAIL 4"}]}],
             "timing": {"received_at": at(10, 42, 49), "queue_ms": 4, "wa_lag_ms": 800,
                        "brain_start_ms": 120, "brain_ms": 5000,
                        "rounds": [{"round": 1, "t_ms": 200, "ms": 2900, "finish": "tool_calls",
                                    "tools": 1},
                                   {"round": 2, "t_ms": 4000, "ms": 1100, "finish": "stop",
                                    "tools": 0, "then": "verify"}],
                        "sends": [{"t_ms": 5300, "action": "send-message", "ok": True,
                                   "wait_ms": 2, "tries": 1}],
                        "first_send_ms": 5300},
             "created_at": at(10, 43, 3)},
        ],
    )
    return db


class TheTimeline(unittest.TestCase):

    def run_script(self, *extra):
        db = _db()

        class Client:
            def __init__(self, url):
                pass

            def __getitem__(self, name):
                return db
        out = io.StringIO()
        with patch.dict(os.environ, {"MONGO_URL": "mongodb://x", "DB_NAME": "d"}), \
                patch("motor.motor_asyncio.AsyncIOMotorClient", Client), \
                contextlib.redirect_stdout(out):
            code = tl.main(["--email", "roy@x.com", "--date", "2026-10-27", *extra])
        self.assertEqual(code, 0)
        return out.getvalue(), db

    def test_each_message_with_its_answer_and_deltas(self):
        text, _ = self.run_script()
        self.assertIn('IN 10:36:05 AM  "Spray foam on 5th floor ceiling?"', text)
        self.assertIn("answer row logged 10:43:01 AM (+6m56.0s after their message)", text)
        self.assertIn("timing: NONE -- this row was logged before per-step timestamps existed", text)
        self.assertIn("401.2 s in the model", text)
        self.assertIn("WALKTHROUGH that day: 588 Thomas · status capturing · started 9:00:00 AM", text)
        self.assertEqual(text.count("WALKTHROUGH that day"), 1)          # not the old one
        self.assertIn('search_plans {"subject": "spray foam", "floor": "5"}', text)
        self.assertIn('→ - A-501: "2 IN CLOSED CELL SPRAY FOAM"', text)
        # The "?" row has the clock.
        self.assertIn("FIRST SEND 5.3s", text)
        self.assertIn("round 2: at 4.0s took 1.1s · finish stop · tool calls 0 · then re-asked (verify)", text)
        self.assertIn("[r1 at 3.1s took 0.9s] search_plans", text)
        self.assertIn('A-701 · Arch.pdf · p12 · set IFC · "ROOF DETAIL 4"', text)
        # The one message out is the FIRST question's answer, though it went
        # after the "?": named as such under both, and the delta is its own.
        self.assertIn('AFTER THEIR NEXT MESSAGE: 10:43:02 AM (+6m57.0s) "Spray foam at the 5th '
                      'floor ceiling: 2" closed cell, A-501." [= the answer to their 10:36:05 AM '
                      'message]', text)
        self.assertIn("DELTA received → first message out: +6m57.0s", text)
        self.assertIn('(+12.0s) "Spray foam at the 5th floor ceiling: 2" closed cell, A-501." '
                      '[= the answer to their 10:36:05 AM message]', text)

    def test_other_peoples_words_and_phones_never_print(self):
        text, _ = self.run_script()
        self.assertEqual([w for w in (OTHER_WORDS, PHONE) if w in text], [])
        self.assertIn("result not printed (", text)
        self.assertIn("…0142", text)

    def test_the_json_file_holds_no_phone_either(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            self.run_script("--json", path)
            raw = open(path, encoding="utf-8").read()
        self.assertEqual([w for w in (OTHER_WORDS, PHONE) if w in raw], [])
        data = json.loads(raw)
        self.assertEqual([m["inbound"]["body"] for m in data["messages"]],
                         ["Spray foam on 5th floor ceiling?", "?"])
        self.assertEqual(data["messages"][1]["answer"]["timing"]["first_send_ms"], 5300)

    def test_the_json_names_whose_answer_each_outgoing_message_carries(self):
        # b1 answers the 10:36 question but went out after the "?": under the
        # first message it is mine and late, under the "?" it is someone else's.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            self.run_script("--json", path)
            data = json.load(open(path, encoding="utf-8"))
        first, second = data["messages"]
        self.assertEqual([(o["answers_mine"], o["late"]) for o in first["outbound"]], [(True, True)])
        self.assertEqual([(o["answers_mine"], o["late"]) for o in second["outbound"]], [(False, False)])

    def test_nothing_is_written(self):
        _, db = self.run_script()
        for name in ("whatsapp_messages", "whatsapp_dm_answers", "users", "whatsapp_optins"):
            coll = db[name]
            self.assertEqual(getattr(coll, "inserts", []), [], name)

    def test_the_webhook_log_gives_delivery_times_without_words(self):
        db_rows = [{"_id": "w1", "received_at": at(10, 41, 58), "raw_body_preview": json.dumps(
            {"event": "message", "data": {"message": {
                "id": {"_serialized": f"false_{CHAT}_AAA111", "fromMe": False}, "from": CHAT,
                "body": "Spray foam on 5th floor ceiling?", "type": "chat",
                "timestamp": int(at(10, 36, 1).timestamp())}}})}]
        ev = tl.wa_log_event(db_rows[0], {PHONE})
        self.assertEqual((ev["mid"], ev["chat"], ev["from_me"]), ("AAA111", "…0142", False))
        self.assertEqual(ev["wa_ts"], int(at(10, 36, 1).timestamp()))
        self.assertEqual(sorted(ev), ["at", "chat", "event", "from_me", "mid", "type", "wa_ts"])


def _in(body, t):
    return {"body": body, "created_at": t}


def _row(question, t):
    return {"question": question, "created_at": t}


class ThePairing(unittest.TestCase):
    """A message with no answer row stays unpaired (Codex on #893): the
    reminder's "yes" is stored, answered in code (_upcoming_dm_turn) and
    logs no row -- it must not take the next question's row."""

    def test_a_reminder_yes_does_not_take_the_next_questions_row(self):
        inbound = [_in("yes", at(10, 0)), _in("What's open at 588?", at(10, 1))]
        answers = [_row("What's open at 588?", at(10, 1, 20))]
        self.assertEqual(tl.pair_answers(inbound, answers), {1: 0})

    def test_and_through_the_script_the_yes_shows_no_row(self):
        db = FakeDb(
            users=[{"_id": "u_roy", "email": "roy@x.com", "name": "Roy", "role": "admin",
                    "phone": "+" + PHONE}],
            whatsapp_optins=[{"_id": "o1", "user_id": "u_roy", "status": "active", "phone": PHONE}],
            whatsapp_messages=[
                {"_id": "m1", "group_id": CHAT, "is_dm": True, "sender": PHONE, "from_me": False,
                 "body": "yes", "message_id": "x_Y1", "created_at": at(10, 0)},
                {"_id": "m2", "group_id": CHAT, "is_dm": True, "sender": PHONE, "from_me": False,
                 "body": "What's open at 588?", "message_id": "x_Q1", "created_at": at(10, 1)}],
            whatsapp_dm_answers=[{"_id": "a1", "user_id": "u_roy", "path": "brain",
                                  "question": "What's open at 588?", "answer": "2 punch items.",
                                  "created_at": at(10, 1, 20)}])

        class Client:
            def __init__(self, url):
                pass

            def __getitem__(self, name):
                return db
        out = io.StringIO()
        with patch.dict(os.environ, {"MONGO_URL": "mongodb://x", "DB_NAME": "d"}), \
                patch("motor.motor_asyncio.AsyncIOMotorClient", Client), \
                contextlib.redirect_stdout(out):
            tl.main(["--email", "roy@x.com", "--date", "2026-10-27"])
        text = out.getvalue()
        yes, question = text.split('IN 10:00:00 AM  "yes"')[1].split('IN 10:01:00 AM')
        self.assertIn("answer row: NONE paired with this message", yes)
        self.assertIn("answer row logged 10:01:20 AM (+20.0s after their message)", question)
        self.assertEqual(text.count("ANSWER ROWS NOT MATCHED"), 0)

    def test_substrings_never_pair(self):
        """"?" is inside the question before it; only the "?" row is its."""
        inbound = [_in("Spray foam on 5th floor ceiling?", at(10, 36)), _in("?", at(10, 42))]
        answers = [_row("?", at(10, 42, 30)), _row("Spray foam on 5th floor ceiling?", at(10, 43))]
        self.assertEqual(tl.pair_answers(inbound, answers), {0: 1, 1: 0})

    def test_voice_and_reply_to_forms_are_still_exact(self):
        inbound = [_in("roof details", at(11, 0)), _in("which sheet", at(11, 5))]
        answers = [_row("[voice note] roof details", at(11, 1)),
                   _row("which sheet\n\n(This is a reply to your (Levelog Assistant's) earlier "
                        "message: \"EN-001\")", at(11, 6))]
        self.assertEqual(tl.pair_answers(inbound, answers), {0: 0, 1: 1})

    def test_a_leftover_pairs_only_when_one_row_is_in_its_window(self):
        # A nudge ("same question?") logs the quoted question, not its words:
        # one row before the next message -> paired; two -> left unpaired.
        one = tl.pair_answers([_in("again?", at(12, 0)), _in("thanks", at(12, 5))],
                              [_row("what's open", at(12, 1))])
        self.assertEqual(one, {0: 0})
        two = tl.pair_answers([_in("again?", at(12, 0)), _in("thanks", at(12, 5))],
                              [_row("what's open", at(12, 1)), _row("who's on site", at(12, 2))])
        self.assertEqual(two, {})


if __name__ == "__main__":
    unittest.main()
