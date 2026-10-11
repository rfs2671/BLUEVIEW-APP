"""A Yiddish voice note's card: what was said, and Whisper's direct English.

- lib/voice_ingest.translate_whisper: the translations endpoint (whisper-1,
  audio -> English), one retry.
- A Yiddish group note stores voice.english_direct; any other note does not
  call it. A failed translation leaves the card the translated transcript.
- The Attention list gives a Yiddish voice item {original, english}.
- scripts/voice_lang_eval.py: the "whisper-1 translate" row, scored against
  each clip's .en.txt; the card's two lines in --verbose.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")

import server  # noqa: E402
from lib import voice_ingest, wa_voice  # noqa: E402
from tests.test_voice_never_wakes_the_bot import _Group  # noqa: E402
from tests.test_voice_group_silent import _ok  # noqa: E402

SAID = "מאָרגן גיסן מיר דעם פֿונדאַמענט"
ENGLISH = "Tomorrow we pour the foundation"


class TheTranslationsEndpoint(unittest.TestCase):

    class _Http:
        def __init__(self, fail=0):
            self.urls, self.fail = [], fail

        async def post(self, url, headers=None, files=None, timeout=None):
            import httpx
            self.urls.append((url, files["model"][1], files["file"][0]))
            req = httpx.Request("POST", url)
            if self.fail:
                self.fail -= 1
                return httpx.Response(500, request=req, text="busy")
            return httpx.Response(200, request=req, json={"text": f" {ENGLISH} "})

    def test_audio_straight_to_english(self):
        http = self._Http()
        got = asyncio.run(voice_ingest.translate_whisper(
            b"OggS" + b"\0" * 40, openai_api_key="k", http_client=http))
        self.assertEqual(got, ENGLISH)
        self.assertEqual(http.urls, [("https://api.openai.com/v1/audio/translations",
                                      "whisper-1", "voice.ogg")])

    def test_one_retry(self):
        http = self._Http(fail=1)
        with patch.object(voice_ingest, "WHISPER_BACKOFF_SEC", 0):
            self.assertEqual(asyncio.run(voice_ingest.translate_whisper(
                b"OggS" + b"\0" * 40, openai_api_key="k", http_client=http)), ENGLISH)
        self.assertEqual(len(http.urls), 2)


class TheCardLines(unittest.TestCase):

    def test_yiddish(self):
        v = {"lang": "yi", "transcript": SAID, "english": "We pour tomorrow",
             "english_direct": ENGLISH}
        self.assertEqual(wa_voice.yiddish_lines(v),
                         {"original": SAID, "english": ENGLISH,
                          "english_source": "whisper_translation"})

    def test_without_the_direct_translation_the_translated_transcript(self):
        v = {"lang": "yi", "transcript": SAID, "english": "We pour tomorrow"}
        self.assertEqual(wa_voice.yiddish_lines(v)["english"], "We pour tomorrow")
        self.assertEqual(wa_voice.yiddish_lines(dict(v, english=SAID))["english"], "")

    def test_other_languages_and_empty(self):
        self.assertIsNone(wa_voice.yiddish_lines({"lang": "es", "transcript": "mañana"}))
        self.assertIsNone(wa_voice.yiddish_lines({"lang": "yi", "transcript": ""}))
        self.assertIsNone(wa_voice.yiddish_lines(None))

    def test_the_item_view(self):
        it = {"_id": "a1", "type": "commitment", "status": "open",
              "evidence": {"message_row_id": "r1", "kind": "voice", "quote": SAID}}
        ys = {"r1": {"original": SAID, "english": ENGLISH}}
        self.assertEqual(server._attention_item_view(it, {}, set(), ys)["yiddish"], ys["r1"])
        self.assertIsNone(server._attention_item_view(it, {}, set())["yiddish"])


class AYiddishGroupNote(_Group):

    def _deliver_with(self, result, translated=ENGLISH, fail=False):
        calls = []

        async def translate(audio, **kw):
            calls.append(audio[:4])
            if fail:
                raise RuntimeError("500")
            return translated
        with patch.object(voice_ingest, "translate_whisper", translate):
            self.run_note([result])
        return calls

    def _yi(self):
        r = _ok(text=SAID, seconds=4.0)
        r.language_detected, r.english_transcript = "yiddish", "We pour tomorrow"
        return r

    def test_stores_the_direct_english(self):
        calls = self._deliver_with(self._yi())
        self.assertEqual(calls, [b"OggS"])
        (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        self.assertEqual((row["voice"]["lang"], row["voice"]["english_direct"]), ("yi", ENGLISH))
        self.assertEqual(row["voice"]["english"], "We pour tomorrow")    # the assistant's
        self.assertEqual(self.group_posts(), [])

    def test_a_failed_translation_keeps_the_note(self):
        self._deliver_with(self._yi(), fail=True)
        (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        self.assertNotIn("english_direct", row["voice"])
        self.assertEqual(wa_voice.yiddish_lines(row["voice"])["english"], "We pour tomorrow")

    def test_an_english_note_is_not_translated(self):
        calls = self._deliver_with(_ok(text="pour friday", seconds=4.0))
        self.assertEqual(calls, [])


class TheEvalsTranslationRow(unittest.TestCase):

    def test_the_row_and_its_reference(self):
        from scripts import voice_lang_eval as v
        d = Path(tempfile.mkdtemp())
        (d / "yi").mkdir()
        (d / "yi" / "01.ogg").write_bytes(b"OggS" + b"\0" * 40)
        (d / "yi" / "01.txt").write_text(SAID, encoding="utf-8")
        (d / "yi" / "01.en.txt").write_text(ENGLISH, encoding="utf-8")
        (d / "yi" / "02.ogg").write_bytes(b"OggS" + b"\0" * 40)
        (d / "yi" / "02.txt").write_text(SAID, encoding="utf-8")
        clips = v.load_clips(d)
        self.assertEqual([c.en for c in clips], [ENGLISH, None])
        cfgs = v.configs("off")
        self.assertEqual(len(cfgs), 5)                     # 2 models x prompt + translate
        self.assertEqual(cfgs[-1], {"model": v.TRANSLATE, "prompt": False, "hint": False})

        async def fake(model, audio, key, prompt, language):
            if model == v.TRANSLATE:
                return {"text": "Tomorrow we pour the foundation", "language": "english"}
            return {"text": SAID, "language": "yiddish"}

        class A:
            clips, hint, job, concurrency, verbose = str(d), "off", None, 2, True
            json = str(d / "out.json")
        os.environ.setdefault("OPENAI_API_KEY", "k")
        with patch.object(v, "transcribe", fake):
            self.assertEqual(asyncio.run(v.main_async(A)), 0)
        import json
        rows = json.loads((d / "out.json").read_text(encoding="utf-8"))
        tr = [r for r in rows if r["model"] == v.TRANSLATE]
        self.assertEqual([(r["clip"], r["ref"], r["wer"]) for r in tr],
                         [("yi/01.ogg", ENGLISH, 0.0)])     # 02 has no .en.txt: skipped
        lines = v.card_lines(clips[0], [v.Result(**r) for r in rows])
        self.assertEqual(lines, [f"Said: {SAID}", f"English: {ENGLISH}"])


if __name__ == "__main__":
    unittest.main()
