"""Voice notes in the DM (588, Sun Oct 11 2:58 PM).

"What was said on the last voicenote on 588 group" -> "I can't find that in
the project history." Then "U can't find any voicenotes?" -> "I can't access
voice notes directly." Both wrong: group voice notes are transcribed, stored
and indexed.

1. A group voice note is in project_memory as kind=voice (🎤), with its
   English and the forwarded mark.
2. recent_voice_notes (DM only): time, sender, transcript, English; a
   "last voice note" question is routed to it (first tool call forced).
3. Never "I can't access voice notes": the DM prompt says so, and a reply
   that claims it is replaced by the notes.
4. Forwarded (WhatsApp's label): transcribed and indexed, never a commitment
   owned by the forwarder; marked on cards and in search answers.
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
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")

import server  # noqa: E402
from lib import project_memory, wa_assistant, wa_voice  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, GROUP, _Ctx, _db, _run  # noqa: E402

PID = "proj_a"
AT = datetime(2026, 10, 11, 18, 57, tzinfo=timezone.utc)          # 2:57 PM New York


def _note(i, body, minutes, sender="15550007788", name="Meilich", lang="en",
          english=None, **extra):
    at = AT - timedelta(minutes=minutes)
    return {"_id": f"v{i}", "group_id": GROUP, "project_id": PID, "company_id": CO_A,
            "sender": sender, "sender_jid": f"{sender}@c.us", "sender_name": name,
            "body": body, "has_audio": True, "message_id": f"M{i}", "timestamp": at,
            "created_at": at, "transcribed": True,
            "voice": {"transcript": body, "english": english or body, "lang": lang,
                      "confidence": 0.9, "duration_sec": 4.0, "audio_key": None,
                      "review": lang == "yi"}, **extra}


def _world(*rows):
    return _db(whatsapp_groups=[{"_id": "g1", "wa_group_id": GROUP, "company_id": CO_A,
                                 "project_id": PID, "group_name": "588 – Site",
                                 "active": True}],
               whatsapp_messages=list(rows))


ROWS = [
    _note(1, "Concrete truck is at the gate", 179),                       # 11:58 AM
    _note(2, "Is there any inspection coming up for electricity?", 6),     # 2:51 PM
    _note(3, "מאָרגן גיסן מיר דעם פֿונדאַמענט", 0, sender="15550001234", name="Yoel",
          lang="yi", english="We pour the foundation tomorrow", forwarded=True),
]


class InTheIndex(unittest.TestCase):

    def test_a_voice_row_is_kind_voice_with_its_english(self):
        doc = server._memory_wa_doc(ROWS[2], "588 – Site")
        self.assertEqual((doc["kind"], doc["voice"], doc["lang"], doc["forwarded"]),
                         ("voice", True, "yi", True))
        self.assertEqual(doc["english"], "We pour the foundation tomorrow")
        self.assertEqual(doc["text"], ROWS[2]["body"])            # as said
        self.assertTrue(project_memory.indexable_message(ROWS[2]))
        text = server._memory_wa_doc({**ROWS[0], "voice": None}, "g")
        self.assertEqual((text["kind"], text["english"], text["forwarded"]),
                         ("text", None, False))

    def test_the_tick_indexes_all_three_notes(self):
        async def embed(texts):
            return [[0.1] * 8 for _ in texts]
        db = _world(*ROWS)
        with _Ctx(db), patch.object(server, "_memory_embed_many", embed), \
                patch.object(server, "MEMORY_EMBED_PAUSE", 0), \
                patch.dict(server._MEMORY_ATLAS, {"ok": False, "retry_at": None}):
            _run(server._memory_index_tick(AT + timedelta(hours=1)))
        docs = {d["_id"]: d for d in db.project_memory.rows}
        for r in ROWS:
            d = docs[f"wa:{r['_id']}"]
            self.assertEqual((d["kind"], d["voice"]), ("voice", True), r["_id"])

    def test_a_cite_says_forwarded_and_the_prompt_explains_it(self):
        src = {"source": "whatsapp", "who": "Yoel", "group": "588 – Site",
               "when": "Oct 11, 2:57 PM", "voice": True, "forwarded": True}
        self.assertEqual(project_memory.cite(src),
                         "Yoel (forwarded) · 588 – Site · 🎤 Oct 11, 2:57 PM")
        self.assertIn("(forwarded)", project_memory.ANSWER_PROMPT)
        view = server._memory_source_view({**src, "id": "x"})
        self.assertTrue(view["forwarded"])


class RecentVoiceNotes(unittest.TestCase):

    def _ask(self, n=3, sender=""):
        db = _world(*ROWS)
        with _Ctx(db):
            return _run(server._recent_voice_notes(CO_A, PID, n, sender))

    def test_newest_first_with_time_sender_transcript_english(self):
        got = self._ask(3)
        blocks = got.split("\n\n")
        self.assertEqual(len(blocks), 3)
        self.assertTrue(blocks[0].startswith("🎤 Sun Oct 11, 2:57 PM · Yoel · 588 – Site (forwarded)"),
                        blocks[0])
        self.assertIn("Said: “מאָרגן", blocks[0])
        self.assertIn("English: We pour the foundation tomorrow", blocks[0])
        self.assertTrue(blocks[1].startswith("🎤 Sun Oct 11, 2:51 PM · Meilich"), blocks[1])
        self.assertIn("Is there any inspection coming up for electricity?", blocks[1])
        self.assertNotIn("English:", blocks[1])                    # English already
        self.assertIn("11:58 AM", blocks[2])
        self.assertNotIn("15550007788", got)                       # no numbers

    def test_the_last_one(self):
        self.assertEqual(self._ask(1).count("🎤"), 1)

    def test_one_persons_notes(self):
        got = self._ask(5, "meilich")
        self.assertEqual(got.count("🎤"), 2)
        self.assertNotIn("Yoel", got)
        self.assertEqual(self._ask(5, "Chaim"), "No voice notes from Chaim in this job's groups.")

    def test_a_note_that_was_not_read_says_so(self):
        failed = dict(_note(9, "(voice note — not processed)", 1), skipped="voice_too_short")
        failed["voice"] = {"transcript": "", "failed": "too_short", "review": True}
        db = _world(failed)
        with _Ctx(db):
            got = _run(server._recent_voice_notes(CO_A, PID, 3))
        self.assertIn("(not transcribed: shorter than 2 seconds)", got)

    def test_no_group_or_no_notes(self):
        with _Ctx(_db()):
            self.assertEqual(_run(server._recent_voice_notes(CO_A, PID, 3)),
                             "This job has no linked WhatsApp group.")
        with _Ctx(_world()):
            self.assertEqual(_run(server._recent_voice_notes(CO_A, PID, 3)),
                             "No voice notes in this job's groups yet.")


class TheDmRoutesToIt(unittest.TestCase):

    def test_voice_note_questions(self):
        for q in ("What was said on the last voicenote on 588 group",
                  "U can't find any voicenotes?", "what did Meilich say in his voice note",
                  "any voice messages today", "qué dijo en la nota de voz"):
            self.assertTrue(wa_assistant.asks_about_voice_notes(q), q)
        for q in ("who is on site", "what did we decide about the core drill?"):
            self.assertFalse(wa_assistant.asks_about_voice_notes(q), q)

    def test_the_tool_is_offered_in_a_dm_and_forced_first(self):
        """The real agent loop, the model faked: the first call is forced to
        recent_voice_notes, the tool's answer goes to the model, the group
        never sees the tool."""
        sent = []

        class _Resp:
            def __init__(self, j):
                self._j = j

            def raise_for_status(self):
                return None

            def json(self):
                return self._j

        class _Http:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None, **k):
                sent.append(json)
                if len(sent) == 1:
                    return _Resp({"choices": [{"message": {"content": None, "tool_calls": [
                        {"id": "c1", "type": "function", "function": {
                            "name": "recent_voice_notes", "arguments": "{\"n\": 1}"}}]}}]})
                return _Resp({"choices": [{"message": {
                    "content": "Last voice note, 2:57 PM, Yoel (forwarded): we pour the "
                               "foundation tomorrow."}}]})

        async def scope(company_id, project_id):
            return {"_id": PID, "company_id": CO_A}

        async def ctx(*a, **k):
            return ""

        db = _world(*ROWS)
        with _Ctx(db), patch.object(server, "ServerHttpClient", _Http), \
                patch.object(server, "_bot_project_scope", scope), \
                patch.object(server, "_agent_context_block", ctx), \
                patch.object(server, "OPENAI_API_KEY", "k"):
            reply = _run(server._run_group_agent(
                project_id=PID, group_id="15550009999@c.us", company_id=CO_A,
                sender="15550009999", body="What was said on the last voicenote on 588 group",
                features=server._default_bot_config()["features"], explicit_mention=True,
                address_mode="loose", dm=True))
        self.assertIn("2:57 PM", reply)
        self.assertEqual(sent[0]["tool_choice"],
                         {"type": "function", "function": {"name": "recent_voice_notes"}})
        self.assertEqual(sent[1]["tool_choice"], "auto")
        names = [t["function"]["name"] for t in sent[0]["tools"]]
        self.assertIn("recent_voice_notes", names)
        tool_msg = next(m for m in sent[1]["messages"] if m.get("role") == "tool")
        self.assertIn("Yoel", tool_msg["content"])

    def test_never_in_a_group(self):
        async def scope(company_id, project_id):
            return {"_id": PID, "company_id": CO_A}
        with _Ctx(_world(*ROWS)), patch.object(server, "_bot_project_scope", scope):
            got = _run(server._dispatch_agent_tool(
                "recent_voice_notes", {}, project_id=PID, group_id=GROUP, company_id=CO_A,
                sender="1"))
        self.assertEqual(got, "Voice notes are read in a direct message only.")
        import inspect
        src = inspect.getsource(server._run_group_agent)
        self.assertIn('if name == "recent_voice_notes" and not dm:', src)


class NeverCantAccess(unittest.TestCase):

    def test_the_prompt(self):
        c = wa_assistant.DM_AGENT_CLAUSE
        self.assertIn("recent_voice_notes", c)
        self.assertIn("Never say you cannot access", c)

    def test_the_denial(self):
        for r in ("I can't access voice notes directly.", "I cannot listen to audio messages.",
                  "Sorry, I don't have access to voice recordings.",
                  "I'm unable to access the voice notes"):
            self.assertTrue(wa_assistant.denies_voice_access(r), r)
        for r in ("Last voice note, 2:57 PM: we pour tomorrow.",
                  "I can't find that in the project history."):
            self.assertFalse(wa_assistant.denies_voice_access(r), r)

    def test_a_denial_is_replaced_by_the_notes(self):
        async def agent(**kw):
            return "I can't access voice notes directly."
        db = _world(*ROWS)
        ident = {"company_id": CO_A, "user": {}, "role": "admin", "projects": []}
        with _Ctx(db), patch.object(server, "_run_group_agent", agent):
            got = _run(server._dm_answer_job(ident, {"_id": PID, "address": "588 Atlantic Ave"},
                                             "15550009999@c.us", "U can't find any voicenotes?",
                                             "MID1"))
        self.assertTrue(got.startswith("🎤 Sun Oct 11, 2:57 PM"), got)
        self.assertNotIn("can't access", got)


class Forwarded(unittest.TestCase):

    def test_the_webhook_flag(self):
        self.assertTrue(wa_voice.forwarded({"isForwarded": True}))
        self.assertTrue(wa_voice.forwarded({}, {"forwardingScore": 2}))
        self.assertFalse(wa_voice.forwarded({"isForwarded": False}, {"forwardingScore": 0}))
        self.assertFalse(wa_voice.forwarded(None, "x"))

    def test_parsed_and_stored(self):
        from tests.test_voice_group_silent import _payload
        p = _payload()
        p["data"]["message"]["isForwarded"] = True
        parsed = server.parse_inbound_message(p, vendor="waapi")
        self.assertTrue(parsed["forwarded"])
        self.assertFalse(server.parse_inbound_message(_payload(), vendor="waapi")["forwarded"])

    def test_never_a_commitment_owned_by_the_forwarder(self):
        from tests.test_whatsapp_attention import (
            T0, MIKE, _Model, _first_sight, _items, _msg, _tick)
        from tests.test_whatsapp_attention import _world as att_world
        said = {"I'll send the window shop drawings Tuesday": [
            {"type": "commitment", "quote": "I'll send the window shop drawings Tuesday",
             "summary": "Send the window shop drawings Tuesday", "owner_text": None,
             "due_text": "Tuesday", "importance": "normal", "tags": []}]}
        db = att_world()
        _first_sight(db)
        _msg(db, "I'll send the window shop drawings Tuesday", sender=MIKE, forwarded=True)
        report, sends = _tick(db, _Model(said), T0 + timedelta(hours=1))
        self.assertEqual(_items(db), [])
        self.assertEqual(report.get("dropped_forwarded"), 1)
        self.assertEqual(sends, [])
        # The same words, not forwarded: Mike's commitment.
        db = att_world()
        _first_sight(db)
        _msg(db, "I'll send the window shop drawings Tuesday", sender=MIKE)
        _tick(db, _Model(said), T0 + timedelta(hours=1))
        self.assertEqual([i["type"] for i in _items(db)], ["commitment"])

    def test_the_card_says_forwarded(self):
        it = {"_id": "a1", "type": "request", "status": "open",
              "evidence": {"message_row_id": "r1", "kind": "voice", "forwarded": True}}
        self.assertTrue(server._attention_item_view(it, {})["forwarded"])
        self.assertFalse(server._attention_item_view(
            {**it, "evidence": {"message_row_id": "r1"}}, {})["forwarded"])


class CodexReviewOn750(unittest.TestCase):

    def test_a_senders_note_past_the_first_page_is_found(self):
        """Meilich's note is older than 200 notes from Dave."""
        rows = [_note(100 + i, f"Dave note {i}", i, sender="15550004444", name="Dave")
                for i in range(200)] + [_note(9, "Rebar is on 3", 500)]
        with _Ctx(_world(*rows)):
            got = _run(server._recent_voice_notes(CO_A, PID, 1, "meilich"))
        self.assertIn("Rebar is on 3", got)

    def test_the_denial_fallback_only_for_a_voice_note_question(self):
        self.assertFalse(wa_assistant.denies_voice_access("I can't find any audio system plans."))
        self.assertFalse(wa_assistant.asks_about_voice_notes("any audio system plans?"))

        async def agent(**kw):
            return "I can't access voice notes directly."
        ident = {"company_id": CO_A, "user": {}, "role": "admin", "projects": []}
        with _Ctx(_world(*ROWS)), patch.object(server, "_run_group_agent", agent):
            got = _run(server._dm_answer_job(ident, {"_id": PID, "address": "588 Atlantic Ave"},
                                             "15550009999@c.us", "who is on site?", "MID2"))
        self.assertFalse(got.startswith("🎤"), got)       # not a voice question: left alone

    def test_a_forwarded_note_that_failed_stays_forwarded(self):
        from tests.test_voice_never_wakes_the_bot import _Group
        from tests.test_voice_group_silent import _payload as vpayload

        class G(_Group):
            def runTest(self):
                pass
        g = G()
        p = vpayload(seconds="1")                          # too short: not processed
        p["data"]["message"]["isForwarded"] = True
        g.run_note([], payload=p)
        (rev,) = g.reviews()
        self.assertTrue(rev["evidence"]["forwarded"])
        row = next(r for r in g.db.whatsapp_messages.rows
                   if str(r["_id"]) == rev["evidence"]["message_row_id"])
        self.assertTrue(row["forwarded"])
        self.assertTrue(server._attention_item_view(rev, {})["forwarded"])


if __name__ == "__main__":
    unittest.main()
