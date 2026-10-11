"""A transcript that is not what was said (588, Sun Oct 11 2:57 PM).

A forwarded voice note -- Williamsburg Hasidic Yiddish, a blessing for
someone's new house -- was stored as "People speaking in their native
language.", labeled English, unflagged, and the DM assistant quoted it as
fact.

Pinned here, with that exact clip shape (Whisper's verbose_json: language
"english", one fluent segment that describes the audio):
1. Whisper's scores (avg_logprob, no_speech_prob, compression_ratio per
   segment) and the words themselves ("people speaking", "[Music]",
   "Subtitles by …") flag a note: silent review, kept with its audio and
   Whisper's direct English, never extracted, chased, indexed as words or
   quoted as what was said.
2. Heard as Yiddish, Hebrew or German, or a sender set to Yiddish: the
   direct audio -> English translation too, and a review flag.
3. Search answers and recent_voice_notes show a flagged note as "Not
   reliably transcribed — play it." with that English, never as a quote; a
   forwarded note says "forwarded by X".
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")

import server  # noqa: E402
from lib import project_memory, voice_ingest, wa_voice  # noqa: E402
from tests.test_voice_never_wakes_the_bot import _Group  # noqa: E402
from tests.test_voice_group_silent import _payload  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx, _run  # noqa: E402

HALLUCINATION = "People speaking in their native language."
BLESSING_EN = "Mazel tov on the new house, may you live in it with health and joy."

#: What Whisper's verbose_json answered for the 2:57 PM note: English, one
#: fluent segment, scores that look fine. The words give it away.
CLIP_257 = {
    "text": HALLUCINATION, "language": "english", "duration": 14.2,
    "segments": [{"id": 0, "start": 0.0, "end": 14.2, "text": " " + HALLUCINATION,
                  "avg_logprob": -0.48, "no_speech_prob": 0.21,
                  "compression_ratio": 0.93, "temperature": 0.0}]}


class _Http:
    """OpenAI's transcription endpoint, answering with a verbose_json body."""

    def __init__(self, body):
        self.body, self.sent = body, []

    async def post(self, url, headers=None, files=None, timeout=None):
        import httpx
        self.sent.append(url)
        return httpx.Response(200, request=httpx.Request("POST", url), json=self.body)


async def _whisper_async(body):
    return await voice_ingest.transcribe_whisper(
        b"OggS" + b"\0" * 64, openai_api_key="k", http_client=_Http(body))


def _whisper(body):
    return asyncio.run(_whisper_async(body))


class TheSignals(unittest.TestCase):

    def test_the_257_clip_is_unreliable_by_its_words(self):
        wr = _whisper(CLIP_257)
        self.assertEqual(wr.language, "english")
        self.assertEqual(wr.segments[0]["compression_ratio"], 0.93)
        q = wa_voice.quality_signals(wr.segments)
        self.assertEqual(q, {"avg_logprob": -0.48, "min_avg_logprob": -0.48,
                             "no_speech_prob": 0.21, "compression_ratio": 0.93, "segments": 1})
        self.assertEqual(wa_voice.unreliable_reasons(wr.transcript, q),
                         ["describes the audio instead of transcribing it"])

    def test_each_score_on_its_own(self):
        seg = {"start": 0, "end": 4, "avg_logprob": -0.3, "no_speech_prob": 0.1,
               "compression_ratio": 1.2}
        ok = wa_voice.quality_signals([seg])
        self.assertEqual(wa_voice.unreliable_reasons("pour friday", ok), [])
        for k, v, want in (("avg_logprob", -1.2, "avg_logprob"),
                           ("no_speech_prob", 0.55, "no_speech_prob"),
                           ("compression_ratio", 2.6, "compression_ratio")):
            q = wa_voice.quality_signals([dict(seg, **{k: v})])
            (r,) = wa_voice.unreliable_reasons("pour friday", q)
            self.assertTrue(r.startswith(want), r)

    def test_one_unsure_segment_is_not_hidden_by_a_sure_one(self):
        """Codex review on #752: a short -1.2 segment and a long -0.2 one
        average above -1.0; each segment is held to the limit."""
        q = wa_voice.quality_signals([
            {"start": 0, "end": 1, "avg_logprob": -1.2, "no_speech_prob": 0.1,
             "compression_ratio": 1.0},
            {"start": 1, "end": 12, "avg_logprob": -0.2, "no_speech_prob": 0.1,
             "compression_ratio": 1.0}])
        self.assertGreater(q["avg_logprob"], -1.0)
        self.assertEqual(wa_voice.unreliable_reasons("pour friday", q),
                         ["avg_logprob -1.2 < -1.0"])

    def test_the_words_that_describe_audio(self):
        for t in (HALLUCINATION, "[Music]", "(inaudible)", "Foreign language.",
                  "Subtitles by the Amara.org community", "Thanks for watching!",
                  "speaking in Yiddish", "MUSIC"):
            self.assertTrue(wa_voice.meta_transcript(t), t)
        for t in ("I'll send the window shop drawings Tuesday", "We need music stands",
                  "He was speaking in the meeting", "Is there any inspection coming up?"):
            self.assertFalse(wa_voice.meta_transcript(t), t)

    def test_process_voice_note_carries_them(self):
        async def whisper(audio, **kw):
            return await _whisper_async(CLIP_257)
        r = asyncio.run(voice_ingest.process_voice_note(
            b"OggS" + b"\0" * 64, openai_api_key="k", whisper_fn=whisper))
        self.assertTrue(r.ok)                                   # a transcript exists...
        self.assertEqual(r.unreliable, ["describes the audio instead of transcribing it"])
        self.assertEqual(r.telemetry["whisper_quality"]["avg_logprob"], -0.48)


class The257NoteInTheGroup(_Group):
    """The webhook, Whisper's real parsing, the 2:57 PM answer."""

    def _deliver(self, whisper_body=CLIP_257, forwarded=True, sender_lang=None):
        self.translations = []

        async def whisper(audio, **kw):
            return await _whisper_async(whisper_body)

        async def translate(audio, **kw):
            self.translations.append(audio[:4])
            return BLESSING_EN

        async def lang(company_id, jids):
            return sender_lang

        real = voice_ingest.process_voice_note

        async def process(audio, **kw):
            kw.pop("whisper_fn", None)
            return await real(audio, whisper_fn=whisper, **kw)

        p = _payload(seconds="14")
        if forwarded:
            p["data"]["message"]["isForwarded"] = True
            p["data"]["message"]["_data"]["isForwarded"] = True
        self.agent_calls = []
        heard = []

        async def agent(**kw):
            self.agent_calls.append(kw)
            return "x"

        def upload(data, key, ctype="application/octet-stream"):
            return f"https://r2/{key}"

        from tests.test_voice_group_silent import _WaapiDownload
        ps = [patch.object(server, "ServerHttpClient", _WaapiDownload),
              patch.object(voice_ingest, "process_voice_note", process),
              patch.object(voice_ingest, "translate_whisper", translate),
              patch.object(server, "_sender_whisper_language", lang),
              patch.object(server, "_run_group_agent", agent),
              patch.object(server, "_upload_to_r2", upload),
              patch.object(wa_voice, "RETRY_SECONDS", 0)]
        self.db = self._db()
        with _Ctx(self.db) as c:
            for x in ps:
                x.start()
            try:
                _run(_Group._deliver(self, p))
            finally:
                for x in ps:
                    x.stop()
        self.c = c
        return heard

    def test_kept_for_review_silently_never_as_words(self):
        self._deliver()
        self.assertEqual(self.group_posts(), [])
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.translations, [b"OggS"])           # the audio's own English
        (rev,) = self.reviews()
        self.assertEqual(rev["voice_failure"], "unreliable")
        self.assertIn("describes the audio", rev["summary"])
        self.assertNotIn("People speaking", rev["evidence"]["quote"])
        self.assertIn(wa_voice.UNRELIABLE_TEXT, rev["evidence"]["quote"])
        self.assertTrue(rev["evidence"]["forwarded"])
        row = next(r for r in self.db.whatsapp_messages.rows
                   if str(r["_id"]) == rev["evidence"]["message_row_id"])
        self.assertEqual(row["skipped"], "voice_unreliable")
        self.assertEqual(row["voice"]["english_direct"], BLESSING_EN)
        self.assertEqual(row["voice"]["transcript"], HALLUCINATION)   # kept for the reviewer
        # Never a commitment, request, question or event from it.
        from lib import wa_attention
        self.assertIsNone(wa_attention.filter_reason(row))
        # Indexed only as Whisper's English, marked; never the transcript.
        self.assertTrue(project_memory.indexable_message(row))
        doc = server._memory_wa_doc(row, "588 – Site")
        self.assertEqual((doc["text"], doc["unreliable"], doc["forwarded"]),
                         (BLESSING_EN, True, True))
        # What a model reads of it.
        self.assertNotIn("People speaking", wa_voice.fact_text(row))

    def test_the_dm_reads_it_as_not_reliably_transcribed(self):
        self._deliver()
        with _Ctx(self.db):
            got = _run(server._recent_voice_notes(CO_A, "proj_a", 1))
        self.assertIn("forwarded by", got)
        self.assertIn(wa_voice.UNRELIABLE_TEXT, got)
        self.assertIn(BLESSING_EN, got)
        self.assertNotIn("People speaking", got)
        self.assertNotIn("Said:", got)

    def test_a_clean_english_note_is_untouched(self):
        clean = {"text": "Concrete truck is at the gate", "language": "english",
                 "duration": 4.0,
                 "segments": [{"start": 0, "end": 4, "text": " Concrete truck is at the gate",
                               "avg_logprob": -0.21, "no_speech_prob": 0.02,
                               "compression_ratio": 1.1}]}
        self._deliver(clean, forwarded=False)
        self.assertEqual(self.reviews(), [])
        self.assertEqual(self.translations, [])
        (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        self.assertFalse(row["voice"]["review"])
        self.assertEqual(row["voice"]["quality"]["avg_logprob"], -0.21)

    def test_a_sender_set_to_yiddish_gets_the_translation_and_a_flag(self):
        clean = {"text": "Concrete truck is at the gate", "language": "english",
                 "duration": 4.0,
                 "segments": [{"start": 0, "end": 4, "avg_logprob": -0.21,
                               "no_speech_prob": 0.02, "compression_ratio": 1.1}]}
        self._deliver(clean, forwarded=False, sender_lang="yi")
        self.assertEqual(self.translations, [b"OggS"])
        (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        self.assertTrue(row["voice"]["review"])
        self.assertEqual(row["voice"]["review_reason"], "sender_yiddish")
        self.assertEqual(row["voice"]["english_direct"], BLESSING_EN)

    def test_heard_as_german_or_hebrew(self):
        for lang, text in (("german", "Morgen gießen wir das Fundament"),
                           ("hebrew", "מחר יוצקים את היסודות")):
            with self.subTest(lang=lang):
                body = {"text": text, "language": lang, "duration": 4.0,
                        "segments": [{"start": 0, "end": 4, "avg_logprob": -0.3,
                                      "no_speech_prob": 0.05, "compression_ratio": 1.0}]}

                async def tr(t, **kw):
                    return voice_ingest.TranslateResult(english="We pour tomorrow",
                                                        tokens_in=1, tokens_out=1, cost_usd=0)
                with patch.object(voice_ingest, "translate_to_english", tr):
                    self._deliver(body, forwarded=False)
                self.assertEqual(self.translations, [b"OggS"])
                (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
                self.assertTrue(row["voice"]["review"])


class InAnswers(unittest.TestCase):

    def test_a_cite_never_presents_it_as_said(self):
        src = {"source": "whatsapp", "who": "Yoel", "group": "588 – Site",
               "when": "Oct 11, 2:57 PM", "voice": True, "forwarded": True, "unreliable": True}
        self.assertEqual(project_memory.cite(src),
                         "forwarded by Yoel · 588 – Site · 🎤 Oct 11, 2:57 PM · "
                         + project_memory.UNRELIABLE_CITE)
        self.assertIn('"not reliably transcribed"', project_memory.ANSWER_PROMPT)

    def test_no_last_mention_from_it(self):
        from datetime import datetime, timezone
        at = datetime(2026, 10, 11, 18, 57, tzinfo=timezone.utc)
        src = {"source": "whatsapp", "text": "the new house blessing", "who": "Yoel",
               "ny": at, "at": at, "unreliable": True}
        self.assertEqual(project_memory.last_mention_line("what about the new house?", [src]), "")

    def test_the_dm_path_answers_nothing_from_it(self):
        import inspect
        src = inspect.getsource(server._process_whatsapp_message)
        self.assertIn("wa_voice.DM_UNRELIABLE_REPLY", src)
        self.assertIn('getattr(vresult, "unreliable", None)', src)
        # A redelivered webhook replays the reply, not the rejected words
        # (Codex review on #752): the ledger keeps no usable transcript.
        self.assertIn('"english_transcript": "",', src)
        self.assertIn('"user_reply": wa_voice.DM_UNRELIABLE_REPLY', src)


class TheStoredRowIsReflagged(unittest.TestCase):
    """The 2:57 PM row was stored before the rules: scripts/voice_reflag.py."""

    def test_dry_run_then_apply(self):
        from datetime import datetime, timezone
        from tests.test_voice_notes_in_dm import _note, _world
        row = _note(257, HALLUCINATION, 0, sender="15550001234", name="Yoel", forwarded=True)
        ok_row = _note(251, "Is there any inspection coming up for electricity?", 6)
        db = _world(row, ok_row)
        db.projects.rows.append({"_id": "proj_a", "name": "588 Atlantic", "company_id": CO_A})
        db.project_memory.rows.append({"_id": "wa:v257", "text": HALLUCINATION})
        db.attention_items.rows.append({"_id": "a1", "type": "commitment",
                                        "evidence": {"message_row_id": "v257"}})
        # An older item the bad note marked done, and events it made / moved.
        db.attention_items.rows.append({
            "_id": "a2", "type": "commitment", "status": "done",
            "evidence": {"message_row_id": "other"},
            "history": [{"kind": "created", "message_row_id": "other"},
                        {"kind": "state", "from": "open", "to": "done",
                         "message_row_id": "v257"}]})
        db.upcoming_events.rows.extend([
            {"_id": "e1", "status": "open", "source_ref": "v257", "history": []},
            {"_id": "e2", "status": "open", "source_ref": "other",
             "history": [{"kind": "rescheduled", "message_id": "M257"}]},
            {"_id": "e3", "status": "open", "source_ref": "x", "history": []}])
        from scripts import voice_reflag
        with _Ctx(db):
            # The database is handed in: never a client of its own.
            voice_reflag.main(["--project", "proj_a", "--since", "2026-10-11"], db=db)
            self.assertNotIn("skipped", db.whatsapp_messages.rows[0])        # dry run
            with self.assertRaises(SystemExit):                    # the old flag: refused
                voice_reflag.main(["--project", "proj_a", "--since", "2026-10-11", "--apply"], db=db)
            self.assertNotIn("skipped", db.whatsapp_messages.rows[0])
            voice_reflag.main(["--project", "proj_a", "--since", "2026-10-11", "--i-know",
                               "--reason", "Oct 11 2:57 PM note", "--session", "s1"], db=db)
        r = db.whatsapp_messages.rows[0]
        self.assertEqual(r["skipped"], "voice_unreliable")
        self.assertEqual(r["voice"]["unreliable"],
                         ["describes the audio instead of transcribing it"])
        self.assertNotIn("skipped", db.whatsapp_messages.rows[1])            # a real question
        self.assertEqual(db.project_memory.rows, [])
        self.assertTrue(db.attention_items.rows[0]["needs_review"])
        # Codex review on #752: what it changed, and the events.
        self.assertTrue(db.attention_items.rows[1]["needs_review"])
        self.assertEqual(db.attention_items.rows[1]["status"], "done")   # listed, not undone
        ev = {e["_id"]: e for e in db.upcoming_events.rows}
        self.assertEqual((ev["e1"]["status"], ev["e1"]["dismissed_reason"]),
                         ("dismissed", "voice_unreliable"))
        self.assertTrue(ev["e2"]["needs_review"])
        self.assertEqual(ev["e3"]["status"], "open")
        self.assertNotIn("needs_review", ev["e3"])
        # Every write audited, attributed.
        audits = db.audit_logs.rows
        self.assertTrue(audits)
        self.assertTrue(all("voice_reflag" in str(r) and "Oct 11 2:57 PM note" in str(r)
                            for r in audits))


if __name__ == "__main__":
    unittest.main()
