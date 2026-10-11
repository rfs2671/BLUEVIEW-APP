"""Whisper is told what to expect (588, Oct 11: "I'll send the window shop
drawings tomorrow" was heard as "Windows sharp drive"): a construction
glossary and the job's own names, as Whisper's `prompt`, under its limit.
Also the eval's measure (word error rate) and the Attention card's audio
flag."""

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
from lib import voice_glossary as vg  # noqa: E402
from lib import voice_ingest  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_voice_group_silent import _Base, _ok  # noqa: E402

PHRASES = Path(server.__file__).parent / "scripts" / "voice_eval" / "construction_phrases.json"


def _run(coro):
    return asyncio.run(coro)


class ThePrompt(unittest.TestCase):

    def test_the_glossary_is_always_there(self):
        p = vg.build_prompt()
        for t in ("shop drawings", "submittal", "calcs", "core drill", "rebar", "sheetrock",
                  "sleeves", "risers", "fire stopping", "SST", "DOB", "TCO", "punch list",
                  "inspection", "pour", "formwork", "scaffolding", "window"):
            self.assertIn(t, p)
        self.assertLessEqual(vg.estimate_tokens(p), vg.MAX_TOKENS)

    def test_the_jobs_terms_follow_in_order(self):
        p = vg.build_prompt(job=["588 Atlantic Ave"], subs=["Rivera Electric"],
                            people=["Meilich Friedman", "Dave"])
        self.assertTrue(p.endswith("Job: 588 Atlantic Ave. Subs: Rivera Electric. "
                                   "People: Meilich Friedman, Dave."), p)

    def test_a_long_roster_is_cut_never_the_glossary(self):
        people = [f"Person Number{i} Lastname{i}" for i in range(200)]
        subs = [f"Subcontractor Company {i} LLC" for i in range(50)]
        p = vg.build_prompt(job=["588 Atlantic Ave"], subs=subs, people=people)
        self.assertLessEqual(vg.estimate_tokens(p), vg.MAX_TOKENS)
        self.assertIn(vg.build_prompt(), p.split(" Job:")[0] + "")   # glossary first, whole
        self.assertIn("588 Atlantic Ave", p)
        self.assertIn("Subcontractor Company 0 LLC", p)              # the first ones kept

    def test_the_estimate_is_an_upper_bound(self):
        # Whisper (GPT-2 BPE) splits English at roughly 4+ letters a token;
        # the estimate never counts fewer pieces than there are words.
        p = vg.build_prompt(job=["588 Atlantic Ave"], people=["Meilich", "מאיר"])
        words = len(p.split())
        self.assertGreaterEqual(vg.estimate_tokens(p), words)
        self.assertEqual(vg.estimate_tokens("מאיר"), 8)              # 2 per Hebrew letter
        try:
            import tiktoken
            n = len(tiktoken.get_encoding("gpt2").encode(p))
        except Exception:
            return                                                   # offline: no encoding
        self.assertLessEqual(n, vg.estimate_tokens(p))
        self.assertLess(n, 224)

    def test_names_are_deduped_and_cleaned(self):
        p = vg.build_prompt(job=["588 Atlantic"], subs=["Rivera, Electric\\n", "rivera electric"],
                            people=["Dave", "dave", "", "x", "Rebar"])
        self.assertEqual(p.count("Dave") + p.count("dave"), 1)
        self.assertNotIn("\n", p)
        self.assertEqual(p.count("rebar"), 1)                        # already in the glossary


class WordErrorRate(unittest.TestCase):

    def test_the_live_miss(self):
        self.assertEqual(vg.wer("I'll send the window shop drawings tomorrow",
                                "I'll send the window shop drawings tomorrow."), 0.0)
        self.assertEqual(vg.wer("I'll send the window shop drawings tomorrow",
                                "Windows sharp drive"), 1.0)
        self.assertAlmostEqual(vg.wer("pour is friday", "the pour is friday"), 1 / 3)

    def test_the_eval_has_ten_phrases_and_a_language_guard(self):
        import json
        spec = json.loads(PHRASES.read_text())
        self.assertEqual(len(spec["phrases"]), 10)
        self.assertEqual(spec["phrases"][0]["text"], "I'll send the window shop drawings tomorrow")
        self.assertTrue(all(g["lang"] == "spanish" for g in spec["language_guard"]))
        self.assertLessEqual(vg.estimate_tokens(vg.build_prompt(**spec["job"])), vg.MAX_TOKENS)


class WhisperGetsIt(unittest.TestCase):

    class _Http:
        def __init__(self):
            self.files = []

        async def post(self, url, headers=None, files=None, timeout=None):
            import httpx
            self.files.append(files)
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "text": "I'll send the window shop drawings tomorrow", "language": "english",
                "duration": 3.0, "segments": [{"avg_logprob": -0.2, "no_speech_prob": 0.01}]})

    def test_the_prompt_is_a_form_field(self):
        http = self._Http()
        _run(voice_ingest.transcribe_whisper(b"OggS" + b"\0" * 40, openai_api_key="k",
                                             http_client=http, prompt="Terms: shop drawings."))
        self.assertEqual(http.files[0]["prompt"], (None, "Terms: shop drawings."))
        _run(voice_ingest.transcribe_whisper(b"OggS" + b"\0" * 40, openai_api_key="k",
                                             http_client=http))
        self.assertNotIn("prompt", http.files[1])

    def test_process_voice_note_passes_it_only_when_there_is_one(self):
        seen = []

        async def whisper(audio, *, openai_api_key, http_client=None, **kw):
            seen.append(kw)
            return voice_ingest.WhisperResult(transcript="pour friday", language="english",
                                              duration_sec=3.0, no_speech_prob=0.0,
                                              cost_usd=0.0, raw_segments=1)

        async def translate(text, **kw):
            raise AssertionError("English is not translated")

        r = _run(voice_ingest.process_voice_note(b"OggS" + b"\0" * 400, openai_api_key="k",
                                                 whisper_fn=whisper, translate_fn=translate,
                                                 prompt="P"))
        _run(voice_ingest.process_voice_note(b"OggS" + b"\0" * 400, openai_api_key="k",
                                             whisper_fn=whisper, translate_fn=translate))
        self.assertEqual(seen, [{"prompt": "P"}, {}])
        self.assertTrue(r.telemetry["whisper_prompt"])


class TheJobsTerms(unittest.TestCase):

    def _db(self):
        now = datetime.now(timezone.utc)
        return FakeDb(
            projects=[{"_id": "p588", "company_id": "co1", "name": "588 Atlantic",
                       "address": "588 Atlantic Ave, Brooklyn",
                       "trade_assignments": [
                           {"company": "Rivera Electric", "trade": "electrical"},
                           {"company": "Old Sub", "status": "inactive"},
                           {"company": "Kings Plumbing"}]}],
            whatsapp_groups=[{"wa_group_id": "g588@g.us", "project_id": "p588",
                              "company_id": "co1", "active": True}],
            whatsapp_messages=[
                {"group_id": "g588@g.us", "sender": "1", "sender_jid": "1@lid",
                 "sender_name": "M F", "created_at": now},
                {"group_id": "g588@g.us", "sender": "2", "sender_jid": "2@c.us",
                 "sender_name": "Carlos 🔨", "created_at": now - timedelta(minutes=1)},
                {"group_id": "g588@g.us", "sender": "bot", "sender_name": "Levelog",
                 "created_at": now}],
            whatsapp_sender_map=[{"company_id": "co1", "sender_jid": "1@lid",
                                  "person_name": "Meilich Friedman"}])

    def test_the_job_its_subs_and_its_people(self):
        with patch.object(server, "db", self._db()), patch.dict(server._VOICE_PROMPTS, clear=True):
            p = _run(server._voice_prompt("co1", "p588"))
        tail = p.split("permit.")[-1]
        self.assertIn("Job: 588 Atlantic Ave Brooklyn, 588 Atlantic.", tail)
        self.assertIn("Subs: Rivera Electric, Kings Plumbing.", tail)
        self.assertNotIn("Old Sub", tail)
        self.assertNotIn("GC team", tail)
        self.assertIn("People: Meilich Friedman", tail)              # the name set in People
        self.assertIn("Carlos.", tail)                                # no emoji
        self.assertNotIn("Levelog", tail)                             # never the bot

    def test_cached_and_switchable(self):
        db = self._db()
        with patch.object(server, "db", db), patch.dict(server._VOICE_PROMPTS, clear=True):
            a = _run(server._voice_prompt("co1", "p588"))
            db.projects.rows[0]["address"] = "Changed"
            self.assertEqual(_run(server._voice_prompt("co1", "p588")), a)   # 10 min cache
            with patch.dict(os.environ, {"VOICE_WHISPER_PROMPT": "0"}):
                self.assertIsNone(_run(server._voice_prompt("co1", "p999")))

    def test_a_dm_gets_the_glossary_and_a_broken_read_still_answers(self):
        with patch.object(server, "db", FakeDb()), patch.dict(server._VOICE_PROMPTS, clear=True):
            self.assertEqual(_run(server._voice_prompt(None, None)), vg.build_prompt())
            self.assertEqual(_run(server._voice_prompt("co1", "nope")), vg.build_prompt())


class TheGroupNoteIsPrompted(_Base):

    def test_the_group_path_sends_the_jobs_prompt(self):
        calls = []

        async def prompt(company_id, project_id):
            calls.append((str(company_id), str(project_id)))
            return "PROMPT"
        with patch.object(server, "_voice_prompt", prompt):
            self.run_note([_ok()])
        self.assertEqual(calls, [("co_a", "proj_a")])
        self.assertEqual(self.kw[0].get("prompt"), "PROMPT")


class TheCardKnowsTheAudio(unittest.TestCase):

    def test_the_list_says_which_voice_items_can_play(self):
        db = FakeDb(
            users=[{"_id": "u1", "id": "u1", "role": "admin", "company_id": "co1",
                    "account_status": "approved"}],
            projects=[{"_id": "p1", "company_id": "co1"}],
            whatsapp_messages=[{"_id": "m1", "company_id": "co1", "voice": {"audio_key": "k1"}},
                               {"_id": "m2", "company_id": "co1", "voice": {"audio_key": None}}],
            attention_items=[
                {"_id": "a1", "project_id": "p1", "company_id": "co1", "status": "open",
                 "review": None, "type": "request", "created_at": datetime.now(timezone.utc),
                 "evidence": {"kind": "voice", "message_row_id": "m1"}},
                {"_id": "a2", "project_id": "p1", "company_id": "co1", "status": "open",
                 "review": None, "type": "request", "created_at": datetime.now(timezone.utc),
                 "evidence": {"kind": "voice", "message_row_id": "m2"}},
                {"_id": "a3", "project_id": "p1", "company_id": "co1", "status": "open",
                 "review": None, "type": "request", "created_at": datetime.now(timezone.utc),
                 "evidence": {"kind": "text", "message_row_id": "m3"}}])

        async def admin(project_id, user):
            return "co1"
        with patch.object(server, "db", db), \
                patch.object(server, "_attention_admin_project", admin):
            out = _run(server.get_project_attention("p1", "open", current_user={}))
        by = {i["id"]: i["audio"] for i in out["items"]}
        self.assertEqual(by, {"a1": True, "a2": False, "a3": False})


if __name__ == "__main__":
    unittest.main()
