"""Whisper defaults to openai/whisper-large-v3 (operator ruling 2026-10-27).

Measured 2026-10-26/27 on DeepInfra, through production's own calls
(lib/voice_ingest) on ten construction phrases: openai/whisper-large-v3-turbo,
the model #879 chose, returned EMPTY text for 6 of 10 with the prompt a 588
group note carries, and its translations endpoint returned the source
language unchanged; whisper-large-v3 heard 10 of 10 with that prompt (6.3%
word error) and translated. Production switched by the WHISPER_MODEL
variable; this makes it the default, so a deploy without the variable does
not fall back to the model that drops notes.

Each test fails by assertion on the branch before this change.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import llm_provider, voice_ingest  # noqa: E402

LARGE_V3 = "openai/whisper-large-v3"


def _default_whisper():
    """llm_provider.WHISPER_MODEL as read with no WHISPER_MODEL variable."""
    env = {k: v for k, v in os.environ.items() if k != "WHISPER_MODEL"}
    try:
        with patch.dict(os.environ, env, clear=True):
            return importlib.reload(llm_provider).WHISPER_MODEL
    finally:
        importlib.reload(llm_provider)


class _Client:
    def __init__(self, answer):
        self.answer, self.sent = answer, []

    async def post(self, url, headers=None, files=None, **k):
        self.sent.append({"url": url, "files": files})
        return SimpleNamespace(status_code=200, json=lambda: self.answer, raise_for_status=lambda: None)


class WhisperIsLargeV3(unittest.TestCase):

    def test_the_default_is_large_v3(self):
        self.assertEqual(_default_whisper(), LARGE_V3)

    def test_a_note_is_transcribed_by_the_default(self):
        c = _Client({"text": "The pour is pushed to Tuesday.", "language": "en", "duration": 2.0,
                     "segments": [{"no_speech_prob": 0.0, "avg_logprob": -0.1}]})
        with patch.object(llm_provider, "WHISPER_MODEL", _default_whisper()):
            asyncio.run(voice_ingest.transcribe_whisper(b"OggS" + b"\0" * 40, openai_api_key="k",
                                                        http_client=c, prompt="glossary"))
        (req,) = c.sent
        self.assertEqual(req["url"], llm_provider.TRANSCRIBE_URL)
        self.assertEqual(req["files"]["model"], (None, LARGE_V3))

    def test_a_note_is_translated_by_the_default(self):
        c = _Client({"text": "Tomorrow the rebar arrives for the third floor."})
        with patch.object(llm_provider, "WHISPER_MODEL", _default_whisper()):
            asyncio.run(voice_ingest.translate_whisper(b"OggS" + b"\0" * 40, openai_api_key="k",
                                                       http_client=c))
        (req,) = c.sent
        self.assertEqual(req["url"], llm_provider.TRANSLATE_URL)
        self.assertEqual(req["files"]["model"], (None, LARGE_V3))


if __name__ == "__main__":
    unittest.main()
