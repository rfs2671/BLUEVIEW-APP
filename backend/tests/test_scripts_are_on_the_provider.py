"""The operator scripts call DeepInfra through lib/llm_provider, like
production (OpenAI retired 2026-10-26). Before this, nine scripts in scripts/
still called api.openai.com or checked OPENAI_API_KEY, which goes out of
Railway once production is confirmed on DeepInfra: they would refuse to run,
or (dm_eval_replay) silently measure a path production does not take.

Each test fails by assertion on the branch before this change.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "smoke_test"),
             ("JWT_SECRET", "smoke_test_secret"), ("APP_BASE_URL", "https://app.levelog.com")):
    os.environ.setdefault(k, v)

from lib import llm_provider  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
OPENAI_MARKS = ("api.openai.com", "gpt-4o", "text-embedding-3", "whisper-1", "tts-1",
                "OPENAI_API_KEY")


def _code_strings_and_names(path: Path):
    """String constants that are not docstrings, and every name or attribute
    read, in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docs.add(id(body[0].value))
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    names += [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    return strings, names


class _Capture:
    """A ServerHttpClient that records each request and answers it."""

    def __init__(self, answer):
        self.answer, self.sent = answer, []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, files=None, **k):
        self.sent.append({"url": url, "headers": headers or {}, "json": json, "files": files})
        body = self.answer
        return SimpleNamespace(status_code=200, json=lambda: body, raise_for_status=lambda: None,
                               text="", content=b"ID3audio")


def _chat(content):
    return {"choices": [{"message": {"content": content}}]}


class NoScriptCallsOpenAI(unittest.TestCase):

    def test_no_script_names_openai_or_reads_its_key(self):
        hits = []
        for path in sorted(SCRIPTS.rglob("*.py")):
            strings, names = _code_strings_and_names(path)
            hits += [f"{path.name}: {s[:60]!r}" for s in strings if any(m in s for m in OPENAI_MARKS)]
            hits += [f"{path.name}: reads OPENAI_API_KEY" for n in names if n == "OPENAI_API_KEY"]
        self.assertEqual(hits, [])


class TheRawCallsGoToTheProvider(unittest.TestCase):
    """The two scripts that post to the model themselves, rather than through
    server.py, post where production does, with the same model and key."""

    def test_the_attention_fixture_eval(self):
        from scripts import attention_fixture_eval as afe
        cap = _Capture(_chat('{"items": []}'))
        with patch("lib.server_http.ServerHttpClient", cap), \
                patch.object(afe, "ServerHttpClient", cap, create=True), \
                patch.object(llm_provider, "API_KEY", "provider-key"), \
                patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertEqual(afe.call([{"role": "user", "content": "x"}]), '{"items": []}')
        (req,) = cap.sent
        self.assertEqual(req["url"], llm_provider.CHAT_URL)
        self.assertEqual(req["json"]["model"], llm_provider.CHAT_MODEL)
        self.assertEqual(req["headers"]["Authorization"], "Bearer provider-key")

    def test_the_corpus_harness_classifier(self):
        from scripts import wa_corpus_harness as h
        cap = _Capture(_chat('{"is_request": true}'))
        rows = [{"body": "need 200 sheets of drywall on 3"}]
        with patch("lib.server_http.ServerHttpClient", cap):
            out = asyncio.run(h.classify(rows, "provider-key"))
        self.assertEqual(list(out.values()), [True])
        (req,) = cap.sent
        self.assertEqual(req["url"], llm_provider.CHAT_URL)
        self.assertEqual(req["json"]["model"], llm_provider.CHAT_MODEL)
        self.assertEqual(req["headers"]["Authorization"], "Bearer provider-key")


class TheReplayRunsTheModelPath(unittest.TestCase):

    def test_the_headcount_is_reworded_as_in_production(self):
        """Production rewords a headcount only when it has a model key
        (server.LLM_API_KEY). The replay stands in for that model, so it
        must give the server a key, or the rewording never runs."""
        import server
        from lib import wa_headcount
        from scripts import dm_eval_replay as replay
        from tests.test_whatsapp_phase1_foundations import _Ctx
        r = replay._Replay()
        with patch.object(server, "LLM_API_KEY", ""), _Ctx(db=r.db) as c:
            r.say(c, "Update on workers 588")
        self.assertIn(wa_headcount.PHRASE_PROMPT, [s for s, _ in r.llm_calls])


class TheVoiceEvalsReadDeepInfrasLanguages(unittest.TestCase):
    """DeepInfra's Whisper reports a language as a code ("es"), not OpenAI's
    name ("spanish")."""

    def test_a_spanish_note_reported_as_es_is_not_the_wrong_language(self):
        from scripts import voice_lang_eval as ev
        self.assertFalse(ev.wrong_language("es", {"text": "Mañana llega la varilla", "language": "es"}))
        self.assertFalse(ev.wrong_language("es", {"text": "x", "language": "spanish"}))
        self.assertTrue(ev.wrong_language("es", {"text": "x", "language": "en"}))
        self.assertTrue(ev.wrong_language("yi", {"text": "der Beton", "language": "yi"}))

    def test_the_matrix_is_the_providers_whisper_models(self):
        from scripts import voice_lang_eval as ev
        models = [c["model"] for c in ev.configs("off") if c["model"] != ev.TRANSLATE]
        self.assertEqual(set(models), {"openai/whisper-large-v3", "openai/whisper-large-v3-turbo"})
        self.assertEqual(models[0], llm_provider.WHISPER_MODEL)

    def test_the_second_model_is_called_at_the_provider(self):
        from scripts import voice_lang_eval as ev
        other = "openai/whisper-large-v3"
        cap = _Capture({"text": " Mañana llega la varilla.", "language": "es"})
        with patch("lib.server_http.ServerHttpClient", cap), \
                patch.object(llm_provider, "WHISPER_MODEL", "openai/whisper-large-v3-turbo"):
            got = asyncio.run(ev.transcribe(other, b"OggS" + b"\0" * 40, "provider-key", None, "es"))
        self.assertEqual(got, {"text": "Mañana llega la varilla.", "language": "es"})
        (req,) = cap.sent
        self.assertEqual(req["url"], llm_provider.TRANSCRIBE_URL)
        self.assertEqual(req["files"]["model"], (None, other))
        self.assertEqual(req["headers"]["Authorization"], "Bearer provider-key")

    def _wer_run(self, guard_language, env):
        """voice_wer_eval over one phrase and the guard notes, every
        transcript exact; returns (exit code, keys the calls used)."""
        from lib import voice_ingest
        from scripts import voice_wer_eval as ev
        spec = json.loads(ev.PHRASES.read_text())
        d = Path(tempfile.mkdtemp())
        texts = {}
        for item in spec["phrases"][:1] + spec["language_guard"]:
            (d / f"{item['id']}.ogg").write_bytes(item["id"].encode())
            texts[item["id"].encode()] = item["text"]
        keys = []

        async def whisper(audio, *, openai_api_key, prompt=None, **k):
            keys.append(openai_api_key)
            lang = "en" if texts[audio] in [p["text"] for p in spec["phrases"]] else guard_language
            return SimpleNamespace(transcript=texts[audio], language=lang)
        with patch.object(voice_ingest, "transcribe_whisper", whisper), \
                patch.object(llm_provider, "API_KEY", "provider-key"), \
                patch.dict(os.environ, env):
            code = asyncio.run(ev.main_async(SimpleNamespace(audio_dir=str(d), tts=False)))
        return code, keys

    def test_the_wer_guard_reads_a_language_code(self):
        code, _ = self._wer_run("es", {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 0, "a Spanish note reported as 'es' was called FLIPPED")

    def test_the_wer_eval_runs_on_the_provider_key(self):
        code, keys = self._wer_run("spanish", {"OPENAI_API_KEY": ""})
        self.assertEqual(code, 0)
        self.assertEqual(set(keys), {"provider-key"})

    def test_tts_reads_each_note_at_the_provider_in_its_language(self):
        """--tts with no recordings: every phrase and guard note is read
        aloud by DeepInfra's Kokoro, the Spanish notes in a Spanish voice."""
        from lib import voice_ingest
        from scripts import voice_wer_eval as ev
        spec = json.loads(ev.PHRASES.read_text())
        cap = _Capture({})

        async def whisper(audio, *, openai_api_key, prompt=None, **k):
            return SimpleNamespace(transcript="", language="es")
        with patch("lib.server_http.ServerHttpClient", cap), \
                patch.object(voice_ingest, "transcribe_whisper", whisper), \
                patch.object(llm_provider, "API_KEY", "provider-key"), \
                patch.dict(os.environ, {"OPENAI_API_KEY": "k"}):
            asyncio.run(ev.main_async(SimpleNamespace(audio_dir=tempfile.mkdtemp(), tts=True)))
        n_en, n_es = len(spec["phrases"]), len(spec["language_guard"])
        self.assertEqual([r["url"] for r in cap.sent], [f"{llm_provider.API_BASE}/audio/speech"] * (n_en + n_es))
        self.assertEqual({r["json"]["model"] for r in cap.sent}, {"hexgrad/Kokoro-82M"})
        self.assertEqual([r["json"]["voice"] for r in cap.sent], ["am_onyx"] * n_en + ["em_alex"] * n_es)
        self.assertEqual({r["headers"]["Authorization"] for r in cap.sent}, {"Bearer provider-key"})


if __name__ == "__main__":
    unittest.main()
