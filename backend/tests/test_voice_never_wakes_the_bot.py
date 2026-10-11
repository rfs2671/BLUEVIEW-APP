"""A voice note never speaks for the bot in a group (588, Sun Oct 11 2:51 PM).

A 4-second note ("I'll send the window shop drawings Tuesday") got the bot's
"I'm here — say 'levelog' or reply to one of my messages and I'll answer."
posted in the group: the transcript was read as a typed message, found
unaddressed and question-shaped, and the once-a-day hint went out.

Pinned here:
1. The Whisper prompt never carries the bot's name; a transcript that is the
   prompt read back (prompt echo) is a failed transcription: a silent
   "Voice note not processed" review row, never a message.
2. A transcript never wakes the bot in a group: not by saying "levelog", not
   by a question, not in loose mode, not inside a live session. Only a voice
   note sent as a WhatsApp reply to one of the bot's messages reaches it.
   Typed text is unchanged.
3. The Flagged precision counts a flagged voice item's own verdict.
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
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")

import server  # noqa: E402
from lib import voice_glossary, voice_ingest, wa_attention_state, wa_voice  # noqa: E402
from tests.test_voice_group_silent import GROUP, PM_PHONE, _Base, _ok, _payload  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx, _run  # noqa: E402

SAID = "I'll send the window shop drawings Tuesday"
PROMPT = voice_glossary.build_prompt(job=["588 Atlantic Ave"], subs=["Rivera Electric"],
                                     people=["Meilich", "Dave"])


class ThePrompt(unittest.TestCase):

    def test_the_glossary_never_names_the_bot(self):
        self.assertFalse(voice_glossary.names_the_bot(" ".join(voice_glossary.GLOSSARY)))
        p = voice_glossary.build_prompt(
            job=["588 Atlantic Ave", "Levelog test job"],
            subs=["Rivera Electric", "LeveLog Assistant"],
            people=["Meilich", "levelog", "Levelog Bot", "Dave"])
        self.assertNotIn("levelog", p.lower())
        for kept in ("588 Atlantic Ave", "Rivera Electric", "Meilich", "Dave"):
            self.assertIn(kept, p)

    def test_echo(self):
        for t in ("Construction site voice note.",
                  "Construction site voice note. Terms: shop drawings, submittal",
                  "Shop drawings, submittal, calcs, core drill.",
                  "Rebar, sheetrock, sleeves",
                  "sidewalk shed, hoist, CMU, slab",
                  "People: Meilich, Dave."):
            self.assertTrue(voice_glossary.prompt_echo(t, PROMPT), t)

    def test_speech_that_names_terms_is_not_an_echo(self):
        for t in (SAID, "The rebar is here, sheetrock tomorrow",
                  "Who is doing the core drill for the sprinkler sleeves on 3?",
                  "Rivera Electric", "pour friday"):
            self.assertFalse(voice_glossary.prompt_echo(t, PROMPT), t)
        self.assertFalse(voice_glossary.prompt_echo("Rebar, sheetrock, sleeves", None))

    def test_process_voice_note_fails_an_echo(self):
        async def whisper(audio, **kw):
            return voice_ingest.WhisperResult(
                transcript="Shop drawings, submittal, calcs, core drill.", language="english",
                duration_sec=4.0, no_speech_prob=0.05, confidence=0.9, cost_usd=0.0004)
        r = asyncio.run(voice_ingest.process_voice_note(
            b"OggS" + b"\0" * 64, openai_api_key="k", prompt=PROMPT, whisper_fn=whisper))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "prompt_echo")
        self.assertEqual(r.telemetry["rejected_reason"], "prompt_echo")
        self.assertNotIn("prompt_echo", wa_voice.RETRYABLE)     # same prompt, same echo

    def test_the_same_words_without_a_prompt_are_speech(self):
        async def whisper(audio, **kw):
            return voice_ingest.WhisperResult(
                transcript="Rebar, sheetrock, sleeves", language="english",
                duration_sec=4.0, no_speech_prob=0.05, confidence=0.9, cost_usd=0.0004)
        r = asyncio.run(voice_ingest.process_voice_note(
            b"OggS" + b"\0" * 64, openai_api_key="k", whisper_fn=whisper))
        self.assertTrue(r.ok)


def _reply_to_bot(msg_id="3A5F0C1E9B2E"):
    p = _payload(msg_id=msg_id, seconds="4")
    p["data"]["message"]["hasQuotedMsg"] = True
    p["data"]["message"]["_data"]["quotedMsg"] = {
        "type": "chat", "fromMe": True, "body": "Who's handling the window shop drawings?"}
    p["data"]["message"]["_data"]["quotedStanzaID"] = "BOTMSG01"
    return p


class _Group(_Base):
    """The live group path, with the agent and the address mode observable."""

    mode = "loose"

    def _db(self):
        db = super()._db()
        db.whatsapp_groups.rows[0]["bot_config"]["features"]["address_mode"] = self.mode
        return db

    def run_note(self, results, payload=None, session=False):
        self.agent_calls = []

        async def agent(**kw):
            self.agent_calls.append(kw)
            return "On it — Rivera has the window shop drawings for Tuesday."

        async def live(group_id, sender):
            return session

        with patch.object(server, "_is_in_bot_session", live):
            return self._run(results, payload, agent)

    def _run(self, results, payload, agent):
        heard = []
        results = list(results)

        async def transcribe(audio_bytes, **kw):
            heard.append(audio_bytes)
            r = results.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        def upload(data, key, ctype="application/octet-stream"):
            return f"https://r2/{key}"

        from tests.test_voice_group_silent import _WaapiDownload
        ps = [patch.object(server, "ServerHttpClient", _WaapiDownload),
              patch.object(voice_ingest, "process_voice_note", transcribe),
              patch.object(server, "_run_group_agent", agent),
              patch.object(server, "_upload_to_r2", upload),
              patch.object(wa_voice, "RETRY_SECONDS", 0)]
        self.db = self._db()
        with _Ctx(self.db) as c:
            for p in ps:
                p.start()
            try:
                _run(self._deliver(payload or _payload(seconds="4")))
            finally:
                for p in ps:
                    p.stop()
        self.c = c
        return heard


class ATranscriptNeverWakesTheBot(_Group):

    def test_the_live_note_gets_no_reply(self):
        """2:51 PM: stored, read by nobody in the group, answered by nobody."""
        heard = self.run_note([_ok(text=SAID, seconds=4.0)])
        self.assertEqual(len(heard), 1)
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.group_posts(), [])
        (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        self.assertEqual(row["body"], SAID)                    # kept for Attention

    def test_the_live_2_51_pm_question_gets_no_bot_message(self):
        """588, Oct 11 2:51 PM, as transcribed: a question to a person."""
        self.run_note([_ok(text="Is there any inspection coming up for electricity?",
                           seconds=4.0)])
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.group_posts(), [])
        self.assertFalse([r for r in self.db.whatsapp_conversation_state.rows
                          if r.get("kind") == "nudge"])

    def test_a_question_shaped_transcript_gets_no_hint(self):
        self.run_note([_ok(text="Who is doing the core drill on 3?", seconds=4.0)])
        self.assertEqual(self.group_posts(), [])
        self.assertFalse([r for r in self.db.whatsapp_conversation_state.rows
                          if r.get("kind") == "nudge"])

    def test_saying_levelog_does_not_wake_it(self):
        self.run_note([_ok(text="Levelog, who is on site today?", seconds=4.0)])
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.group_posts(), [])

    def test_a_live_session_does_not_carry_a_voice_note(self):
        self.run_note([_ok(text="and what about the roof?", seconds=4.0)], session=True)
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.group_posts(), [])

    def test_done_n_by_voice_is_not_a_checklist_command(self):
        self.run_note([_ok(text="done 2", seconds=4.0)])
        self.assertEqual(self.group_posts(), [])

    def test_a_voice_reply_to_the_bot_reaches_it(self):
        self.run_note([_ok(text=SAID, seconds=4.0)], payload=_reply_to_bot())
        (call,) = self.agent_calls
        self.assertEqual(call["body"], SAID)
        self.assertFalse(call["explicit_mention"])             # NOREPLY stays open
        posts = self.group_posts()
        self.assertEqual(len(posts), 1)

    def test_a_prompt_echo_is_a_silent_review_row(self):
        echo = voice_ingest.VoiceIngestResult(
            ok=False, original_transcript="Shop drawings, submittal, calcs, core drill.",
            user_reply=voice_ingest.USER_REPLY_PROCESSING_FAILED, error_kind="prompt_echo",
            duration_sec=4.0, telemetry={"rejected_reason": "prompt_echo"})
        heard = self.run_note([echo])
        self.assertEqual(len(heard), 1)                        # not retried
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.group_posts(), [])
        (rev,) = self.reviews()
        self.assertEqual(rev["voice_failure"], "prompt_echo")
        self.assertIn("repeated Whisper's word list", rev["summary"])


class StrictToo(ATranscriptNeverWakesTheBot):
    mode = "strict"


def _typed(body, msg_id="3A5F0C1E9C01", reply_to_bot=False):
    p = _payload(msg_id=msg_id)
    m = p["data"]["message"]
    m.update({"type": "chat", "body": body, "hasMedia": False})
    m["_data"] = {"type": "chat", "body": body, "notifyName": "Roy"}
    if reply_to_bot:
        m["hasQuotedMsg"] = True
        m["_data"]["quotedMsg"] = {"type": "chat", "fromMe": True,
                                   "body": "Checklist for today: 1. Sleeves 2. Fire stopping"}
        m["_data"]["quotedStanzaID"] = "BOTMSG02"
    return p


class TypedInTheGroup(_Group):
    """Typed text: the bot answers its name or a reply to it, nothing else."""

    def test_a_typed_question_between_people_gets_nothing(self):
        self.run_note([], payload=_typed("Is there any inspection coming up for electricity?"))
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.group_posts(), [])

    def test_a_follow_up_in_a_session_gets_nothing(self):
        self.run_note([], payload=_typed("and the roof?"), session=True)
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.group_posts(), [])

    def test_the_wake_word_reaches_the_agent(self):
        self.run_note([], payload=_typed("levelog any inspection coming up for electricity?"))
        (call,) = self.agent_calls
        self.assertTrue(call["explicit_mention"])
        self.assertEqual(len(self.group_posts()), 1)

    def test_a_typed_reply_to_the_bot_reaches_the_agent(self):
        self.run_note([], payload=_typed("what about the roof", reply_to_bot=True))
        self.assertEqual(len(self.agent_calls), 1)

    def test_done_n_without_the_wake_word_or_a_reply_says_nothing(self):
        self.run_note([], payload=_typed("done 2"))
        self.assertEqual(self.group_posts(), [])


class MaterialRequestsAndTheChecklistCommand(_Group):
    """Approved Oct 11: a material request is recorded silently with a ✅ on
    the message; "!checklist" is a command, addressed by itself."""

    def _with_material(self, payload, results=()):
        reactions = []

        async def detect(body, pid, cid):
            return {"items": [{"name": "rebar #5", "quantity_requested": 40, "unit": "pcs"}]}

        async def create(*a, **k):
            return {"_id": "mr1"}

        async def react(chat, mid, emoji):
            reactions.append((mid, emoji))
            return True
        self.db_features = {"material_detection": True}
        with patch.object(server, "_detect_material_request", detect), \
                patch.object(server, "_create_material_request", create), \
                patch.object(server, "_react_to_message", react):
            self.run_note(list(results), payload=payload)
        return reactions

    def _db(self):
        db = super()._db()
        db.whatsapp_groups.rows[0]["bot_config"]["features"].update(
            getattr(self, "db_features", {}))
        return db

    def test_typed_request_is_recorded_with_a_check_and_no_text(self):
        reactions = self._with_material(_typed("Need 40 pcs of #5 rebar on 3 by Tuesday"))
        self.assertEqual([e for _, e in reactions], ["✅"])
        self.assertEqual(self.group_posts(), [])

    def test_a_spoken_request_too(self):
        reactions = self._with_material(
            _payload(seconds="4"), [_ok(text="Need 40 pcs of #5 rebar on 3 by Tuesday", seconds=4.0)])
        self.assertEqual([e for _, e in reactions], ["✅"])
        self.assertEqual(self.group_posts(), [])

    def test_bang_checklist_is_addressed(self):
        async def mark(g, s):
            return None
        with patch.object(server, "_mark_bot_session", mark):
            self.assertTrue(asyncio.run(server._is_bot_addressed(
                "!checklist", "15165494475", False, group_id="1203@g.us", sender="1",
                mode="strict")))
            self.assertFalse(asyncio.run(server._is_bot_addressed(
                "!checklist", "15165494475", True, group_id="1203@g.us", sender="1",
                mode="strict")))


class TypedInAStrictGroup(TypedInTheGroup):
    mode = "strict"


class TheRule(unittest.TestCase):
    """The addressing test itself: typed text wakes the bot by its name or a
    reply to it; a voice note only by a reply to it."""

    def addressed(self, body, *, voice=False, mode="loose", quoted_from_bot=False,
                  session=False):
        async def live(g, s):
            return session

        async def mark(g, s):
            return None
        with patch.object(server, "_is_in_bot_session", live), \
                patch.object(server, "_mark_bot_session", mark):
            return asyncio.run(server._is_bot_addressed(
                body, "15165494475", voice, group_id="1203@g.us", sender="1718",
                mode=mode, quoted_from_bot=quoted_from_bot))

    def test_typed(self):
        self.assertTrue(self.addressed("levelog who is on site", mode="strict"))
        self.assertTrue(self.addressed("Done 2", mode="strict", quoted_from_bot=True))
        # Oct 11 ruling: a question between people, or a follow-up riding a
        # session, is not for the bot -- in either mode.
        for mode in ("strict", "loose"):
            self.assertFalse(self.addressed("Is there any inspection coming up for electricity?",
                                            mode=mode))
            self.assertFalse(self.addressed("and the roof?", mode=mode, session=True))

    def test_spoken(self):
        for mode in ("strict", "loose"):
            self.assertFalse(self.addressed("levelog who is on site", voice=True, mode=mode))
            self.assertFalse(self.addressed("who is on site", voice=True, mode=mode))
            self.assertFalse(self.addressed("and the roof?", voice=True, mode=mode,
                                            session=True))
            self.assertTrue(self.addressed("the drawings go out Tuesday", voice=True,
                                           mode=mode, quoted_from_bot=True))


class TheFlaggedCounter(unittest.TestCase):
    """A flagged (unsure) voice item: the app shows one Correct / Wrong, the
    item's. The Flagged line counts that verdict."""

    def _item(self, verdict, row="row1", flag_row="row1", flag_verdict=None):
        return {"type": "commitment", "evidence": {"message_row_id": row},
                "review": {"verdict": verdict} if verdict else None,
                "history": [
                    {"kind": "created", "to": "open", "message_row_id": row},
                    {"kind": "flag", "by": "voice", "to": "open", "message_row_id": flag_row,
                     "review": {"verdict": flag_verdict} if flag_verdict else None}]}

    def test_the_items_verdict_is_the_flags(self):
        sp = wa_attention_state.state_precision(
            [self._item("correct"), self._item("wrong"), self._item(None)])
        self.assertEqual({k: sp["flag"][k] for k in ("correct", "wrong", "unreviewed")},
                         {"correct": 1, "wrong": 1, "unreviewed": 1})
        self.assertEqual(sp["flag"]["precision"], 0.5)

    def test_dismissed_is_not_counted(self):
        sp = wa_attention_state.state_precision([self._item("dismissed"), self._item("correct")])
        self.assertEqual((sp["flag"]["correct"], sp["flag"]["unreviewed"]), (1, 0))

    def test_another_messages_voice_flag_keeps_its_own_verdict(self):
        sp = wa_attention_state.state_precision(
            [self._item("correct", flag_row="row2"),
             self._item("correct", flag_row="row2", flag_verdict="wrong")])
        self.assertEqual((sp["flag"]["correct"], sp["flag"]["wrong"], sp["flag"]["unreviewed"]),
                         (0, 1, 1))

    def test_the_endpoint_reads_the_items_row(self):
        """The stats projection carries evidence.message_row_id."""
        import inspect
        src = inspect.getsource(server.get_project_attention)
        self.assertIn('"evidence.message_row_id": 1', src)


if __name__ == "__main__":
    unittest.main()
