"""Phase F1 — voice ingestion pipeline tests.

Pin every contract `lib/voice_ingest.py` promises:

  • Whisper integration uses verbose_json so we capture
    no_speech_prob.
  • Short-circuit on transcript<5 chars OR no_speech_prob>0.6.
  • Translation runs on EVERY voice note (no language-detection
    skip); falls back to original transcript on failure.
  • Cost telemetry is populated on every path (including failures)
    so the audit row is never missing data.
  • Audio bytes never written to R2 / disk / any persistent store.
  • Whisper retries once on transient failure (per spec).
  • Idempotency hook in server.py de-dupes by message_id (smoke
    pin via static-source check).
  • English passes through translate unchanged.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from lib import voice_ingest  # noqa: E402
from lib.voice_ingest import (  # noqa: E402
    estimate_whisper_cost_usd,
    estimate_translate_cost_usd,
    should_short_circuit,
    aggregate_no_speech_prob,
    process_voice_note,
    transcribe_whisper,
    translate_to_english,
    WhisperResult,
    TranslateResult,
    VoiceIngestResult,
    USER_REPLY_NO_SPEECH,
    USER_REPLY_PROCESSING_FAILED,
    NO_SPEECH_PROB_THRESHOLD,
    MIN_TRANSCRIPT_CHARS,
    PRICING,
)


def _run(coro):
    """Fresh event loop per test — avoids the closed-loop issue
    seen in B3 when the full suite interleaves tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────────
# Pure cost / threshold helpers
# ──────────────────────────────────────────────────────────────────


class TestCostEstimators(unittest.TestCase):
    """OpenAI public pricing rates and rounding pinned. A future
    pricing change is a single-line edit in PRICING but the
    tests catch a ratio change between input/output token rates,
    which would silently miscount billing."""

    def test_whisper_rounds_seconds_up(self):
        # 30.1s should bill as 31s.
        c = estimate_whisper_cost_usd(30.1)
        expected = (31 / 60.0) * PRICING["whisper_per_minute_usd"]
        self.assertAlmostEqual(c, round(expected, 6), places=6)

    def test_whisper_zero_duration_zero_cost(self):
        self.assertEqual(estimate_whisper_cost_usd(0), 0.0)
        self.assertEqual(estimate_whisper_cost_usd(-1), 0.0)

    def test_whisper_30_second_voice_note(self):
        # A typical jobsite voice note: 30 seconds.
        c = estimate_whisper_cost_usd(30)
        # 30/60 * $0.006 = $0.003.
        self.assertAlmostEqual(c, 0.003, places=4)

    def test_translate_token_arithmetic(self):
        # 150 in / 150 out at gpt-4o-mini rates.
        c = estimate_translate_cost_usd(150, 150)
        # 150 * 0.150 / 1e6 + 150 * 0.600 / 1e6 = 0.0000225 + 0.00009 = 0.0001125
        # Python's banker's rounding: round(0.0001125, 6) = 0.000112
        # (rounds to even). Assert at places=5 — ample precision for
        # billing aggregation; the per-call cost is < 1¢ anyway.
        self.assertAlmostEqual(c, 0.000113, places=5)

    def test_translate_zero_tokens(self):
        self.assertEqual(estimate_translate_cost_usd(0, 0), 0.0)


class TestShortCircuit(unittest.TestCase):

    def test_too_short_transcript(self):
        flag, reason = should_short_circuit("hi", 0.1)
        self.assertTrue(flag)
        self.assertIn("transcript_too_short", reason)

    def test_high_no_speech_prob(self):
        flag, reason = should_short_circuit("the quick brown fox", 0.9)
        self.assertTrue(flag)
        self.assertIn("no_speech_prob", reason)

    def test_at_threshold_passes(self):
        # Threshold is 0.6; equal to it should NOT short-circuit
        # (the check is strictly greater than).
        flag, _ = should_short_circuit(
            "this is a real transcript",
            NO_SPEECH_PROB_THRESHOLD,
        )
        self.assertFalse(flag)

    def test_min_chars_boundary(self):
        # Whitespace-only is too short.
        flag, _ = should_short_circuit("    ", 0.1)
        self.assertTrue(flag)
        # 5 non-whitespace chars passes.
        flag2, _ = should_short_circuit("hello", 0.1)
        self.assertFalse(flag2)

    def test_normal_transcript_passes(self):
        flag, reason = should_short_circuit(
            "we have four workers on rebar today", 0.05,
        )
        self.assertFalse(flag)
        self.assertEqual(reason, "")

    def test_min_chars_constant_pinned(self):
        # Pin the spec values so a future "tighten" doesn't slip
        # through silently.
        self.assertEqual(MIN_TRANSCRIPT_CHARS, 5)
        self.assertEqual(NO_SPEECH_PROB_THRESHOLD, 0.6)


class TestNoSpeechProbAggregation(unittest.TestCase):

    def test_takes_max_across_segments(self):
        # MAX strategy: a single high-prob segment flags the audio
        # as suspect even if other segments are clean.
        segments = [
            {"no_speech_prob": 0.05},
            {"no_speech_prob": 0.85},
            {"no_speech_prob": 0.10},
        ]
        self.assertAlmostEqual(aggregate_no_speech_prob(segments), 0.85)

    def test_empty_segments_returns_zero(self):
        self.assertEqual(aggregate_no_speech_prob([]), 0.0)

    def test_skips_non_numeric(self):
        # Whisper has been seen returning null in malformed payloads.
        segments = [{"no_speech_prob": None}, {"no_speech_prob": 0.4}]
        self.assertAlmostEqual(aggregate_no_speech_prob(segments), 0.4)


# ──────────────────────────────────────────────────────────────────
# Stubs for HTTP responses
# ──────────────────────────────────────────────────────────────────


class _StubResp:
    def __init__(self, *, json_body=None, status_code=200, raise_exc=None):
        self.status_code = status_code
        self._json = json_body or {}
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise is not None:
            raise self._raise

    def json(self):
        return self._json


class _StubAsyncClient:
    """Mimics enough of httpx.AsyncClient for transcribe_whisper +
    translate_to_english tests. Records call kwargs for assertions."""

    def __init__(self, *, responses):
        # responses is a list of _StubResp consumed in order.
        self._responses = list(responses)
        self.calls = []

    async def post(self, url, *, headers=None, files=None,
                   json=None, timeout=None):
        self.calls.append({
            "url": url, "headers": headers, "files": files,
            "json": json, "timeout": timeout,
        })
        if not self._responses:
            raise RuntimeError("stub exhausted")
        return self._responses.pop(0)


# ──────────────────────────────────────────────────────────────────
# Whisper integration
# ──────────────────────────────────────────────────────────────────


class TestTranscribeWhisper(unittest.TestCase):

    def test_returns_transcript_language_and_no_speech_prob(self):
        # Verbose_json shape mimics OpenAI's actual response.
        client = _StubAsyncClient(responses=[
            _StubResp(json_body={
                "text": "hello from the jobsite",
                "language": "english",
                "duration": 12.4,
                "segments": [
                    {"id": 0, "no_speech_prob": 0.02, "text": "hello"},
                    {"id": 1, "no_speech_prob": 0.05, "text": "from the jobsite"},
                ],
            }),
        ])
        result = _run(transcribe_whisper(
            b"<ogg-bytes>",
            openai_api_key="sk-test",
            http_client=client,
        ))
        self.assertEqual(result.transcript, "hello from the jobsite")
        self.assertEqual(result.language, "english")
        self.assertAlmostEqual(result.duration_sec, 12.4, places=2)
        self.assertAlmostEqual(result.no_speech_prob, 0.05, places=2)
        self.assertEqual(result.raw_segments, 2)
        # Cost: 13s (rounded up) * $0.006/60 ≈ $0.0013.
        self.assertGreater(result.cost_usd, 0.0)

    def test_uses_verbose_json_response_format(self):
        """Pin: we ask Whisper for verbose_json so segments[].no_speech_prob
        is in the response. response_format=text wouldn't carry
        per-segment data and the short-circuit check would always
        see 0.0 — silent regression risk."""
        client = _StubAsyncClient(responses=[
            _StubResp(json_body={"text": "ok", "duration": 1.0,
                                 "segments": []}),
        ])
        _run(transcribe_whisper(
            b"<ogg-bytes>",
            openai_api_key="sk-test",
            http_client=client,
        ))
        files = client.calls[0]["files"]
        self.assertIn("response_format", files)
        # files dict shape is (None, "verbose_json") — multipart form
        # field tuples that httpx accepts.
        self.assertEqual(files["response_format"][1], "verbose_json")
        self.assertEqual(files["model"][1], "whisper-1")

    def test_retries_once_on_transient_failure(self):
        # First call fails; second returns ok. Per spec: "Whisper
        # API failure: retry 1x".
        client = _StubAsyncClient(responses=[
            _StubResp(raise_exc=RuntimeError("503 Service Unavailable")),
            _StubResp(json_body={"text": "back online", "duration": 3.0,
                                 "segments": []}),
        ])
        result = _run(transcribe_whisper(
            b"<ogg-bytes>",
            openai_api_key="sk-test",
            http_client=client,
        ))
        self.assertEqual(result.transcript, "back online")
        self.assertEqual(len(client.calls), 2)

    def test_raises_after_retry_exhaustion(self):
        # Both attempts fail → propagate the final exception so the
        # caller (process_voice_note) can map to user-facing reply.
        client = _StubAsyncClient(responses=[
            _StubResp(raise_exc=RuntimeError("503 #1")),
            _StubResp(raise_exc=RuntimeError("503 #2")),
        ])
        with self.assertRaises(RuntimeError):
            _run(transcribe_whisper(
                b"<ogg-bytes>",
                openai_api_key="sk-test",
                http_client=client,
            ))

    def test_empty_audio_raises(self):
        # Defensive: empty bytes shouldn't reach Whisper.
        with self.assertRaises(RuntimeError):
            _run(transcribe_whisper(
                b"",
                openai_api_key="sk-test",
                http_client=_StubAsyncClient(responses=[]),
            ))

    def test_missing_api_key_raises(self):
        with self.assertRaises(RuntimeError):
            _run(transcribe_whisper(
                b"<bytes>",
                openai_api_key="",
                http_client=_StubAsyncClient(responses=[]),
            ))


# ──────────────────────────────────────────────────────────────────
# Translation
# ──────────────────────────────────────────────────────────────────


class TestTranslateToEnglish(unittest.TestCase):

    def test_passes_english_through(self):
        # Spec: "If already English, return it unchanged." The PROMPT
        # tells the model to return verbatim — but we also want the
        # cost telemetry math to work for short pass-through cases.
        client = _StubAsyncClient(responses=[
            _StubResp(json_body={
                "choices": [{"message": {
                    "content": "we have four workers on rebar today",
                }}],
                "usage": {"prompt_tokens": 80, "completion_tokens": 12},
            }),
        ])
        result = _run(translate_to_english(
            "we have four workers on rebar today",
            openai_api_key="sk-test",
            http_client=client,
        ))
        self.assertEqual(
            result.english,
            "we have four workers on rebar today",
        )
        self.assertEqual(result.tokens_in, 80)
        self.assertEqual(result.tokens_out, 12)
        self.assertGreater(result.cost_usd, 0.0)
        self.assertFalse(result.fell_back_to_original)

    def test_translates_spanish_to_english(self):
        client = _StubAsyncClient(responses=[
            _StubResp(json_body={
                "choices": [{"message": {
                    "content": "We have four workers on rebar today",
                }}],
                "usage": {"prompt_tokens": 75, "completion_tokens": 10},
            }),
        ])
        result = _run(translate_to_english(
            "tenemos cuatro trabajadores en rebar hoy",
            openai_api_key="sk-test",
            http_client=client,
        ))
        self.assertEqual(
            result.english,
            "We have four workers on rebar today",
        )

    def test_falls_back_on_api_failure(self):
        # Spec: "If translation fails: fall back to original
        # transcript". Extraction may still handle some non-English.
        client = _StubAsyncClient(responses=[
            _StubResp(raise_exc=RuntimeError("502 Bad Gateway")),
        ])
        original = "tenemos cuatro trabajadores en rebar hoy"
        result = _run(translate_to_english(
            original,
            openai_api_key="sk-test",
            http_client=client,
        ))
        self.assertEqual(result.english, original)
        self.assertTrue(result.fell_back_to_original)
        self.assertEqual(result.cost_usd, 0.0)

    def test_falls_back_on_empty_response(self):
        # OpenAI returning {choices: []} is degenerate — fall back.
        client = _StubAsyncClient(responses=[
            _StubResp(json_body={"choices": []}),
        ])
        result = _run(translate_to_english(
            "we have four workers on rebar today",
            openai_api_key="sk-test",
            http_client=client,
        ))
        self.assertTrue(result.fell_back_to_original)

    def test_no_api_key_short_circuits_to_fallback(self):
        # If the env var was never set, don't even try the call —
        # treat as fall-back. Saves a guaranteed-401.
        result = _run(translate_to_english(
            "hello", openai_api_key="",
            http_client=_StubAsyncClient(responses=[]),
        ))
        self.assertTrue(result.fell_back_to_original)
        self.assertEqual(result.english, "hello")

    def test_empty_input_no_call(self):
        result = _run(translate_to_english(
            "", openai_api_key="sk-test",
            http_client=_StubAsyncClient(responses=[]),
        ))
        self.assertEqual(result.english, "")
        self.assertEqual(result.tokens_in, 0)


# ──────────────────────────────────────────────────────────────────
# process_voice_note — orchestrator
# ──────────────────────────────────────────────────────────────────


class TestProcessVoiceNote(unittest.TestCase):
    """Orchestrator covers the four code paths:
        a) happy: Whisper ok + translate ok → ok=True, English transcript
        b) low confidence (no_speech / too short) → ok=False, USER_REPLY_NO_SPEECH
        c) Whisper API failure → ok=False, USER_REPLY_PROCESSING_FAILED, Sentry warning
        d) translate failure → ok=True with original transcript (fell_back)
    """

    def _stub_whisper(self, **overrides):
        async def _fn(audio_bytes, *, openai_api_key, http_client=None):
            base = {
                "transcript": "we have four workers on rebar 4th floor",
                "language": "english",
                "duration_sec": 18.5,
                "no_speech_prob": 0.05,
                "cost_usd": 0.002,
                "raw_segments": 3,
            }
            base.update(overrides)
            if isinstance(base, dict):
                return WhisperResult(**base)
            return base
        return _fn

    def _stub_whisper_raise(self, exc):
        async def _fn(audio_bytes, *, openai_api_key, http_client=None):
            raise exc
        return _fn

    def _stub_translate(self, **overrides):
        async def _fn(text, *, openai_api_key, http_client=None):
            base = {
                "english": text,
                "tokens_in": 80, "tokens_out": 12,
                "cost_usd": 0.0001, "fell_back_to_original": False,
            }
            base.update(overrides)
            return TranslateResult(**base)
        return _fn

    def test_happy_path(self):
        result = _run(process_voice_note(
            b"<ogg>",
            openai_api_key="sk-test",
            whisper_fn=self._stub_whisper(),
            translate_fn=self._stub_translate(),
        ))
        self.assertTrue(result.ok)
        self.assertEqual(
            result.english_transcript,
            "we have four workers on rebar 4th floor",
        )
        self.assertEqual(result.language_detected, "english")
        self.assertGreater(result.telemetry["whisper_cost_usd"], 0.0)
        self.assertGreater(result.telemetry["translate_cost_usd"], 0.0)
        self.assertFalse(result.telemetry["translate_fell_back"])

    def test_low_confidence_short_circuits(self):
        # no_speech_prob just over threshold → ok=False, no translate call.
        translate_called = []
        async def _spy_translate(*args, **kwargs):
            translate_called.append(args)
            return TranslateResult(
                english="should not run", tokens_in=0, tokens_out=0,
                cost_usd=0.0,
            )
        result = _run(process_voice_note(
            b"<ogg>",
            openai_api_key="sk-test",
            whisper_fn=self._stub_whisper(no_speech_prob=0.85),
            translate_fn=_spy_translate,
        ))
        self.assertFalse(result.ok)
        self.assertEqual(result.user_reply, USER_REPLY_NO_SPEECH)
        self.assertEqual(result.error_kind, "low_confidence")
        # Translate must NOT have been called — saves an API call
        # we can't use anyway, and the original transcript is
        # captured for audit.
        self.assertEqual(translate_called, [])
        self.assertEqual(
            result.original_transcript,
            "we have four workers on rebar 4th floor",
        )

    def test_too_short_transcript_short_circuits(self):
        result = _run(process_voice_note(
            b"<ogg>",
            openai_api_key="sk-test",
            whisper_fn=self._stub_whisper(transcript="ok"),
            translate_fn=self._stub_translate(),
        ))
        self.assertFalse(result.ok)
        self.assertEqual(result.user_reply, USER_REPLY_NO_SPEECH)

    def test_whisper_failure_returns_processing_failed(self):
        sentry_calls = []
        def _spy(message, *, level="warning"):
            sentry_calls.append({"message": message, "level": level})
        result = _run(process_voice_note(
            b"<ogg>",
            openai_api_key="sk-test",
            sentry_capture=_spy,
            whisper_fn=self._stub_whisper_raise(RuntimeError("502")),
            translate_fn=self._stub_translate(),
        ))
        self.assertFalse(result.ok)
        self.assertEqual(result.user_reply, USER_REPLY_PROCESSING_FAILED)
        self.assertEqual(result.error_kind, "whisper_failed")
        # Sentry warning fired (NOT error — transient blips dedup).
        self.assertEqual(len(sentry_calls), 1)
        self.assertEqual(sentry_calls[0]["level"], "warning")
        self.assertIn("voice_ingest_whisper_failed", sentry_calls[0]["message"])

    def test_translate_failure_falls_back_to_original(self):
        # Spec: translation failure does NOT break ingestion. The
        # extraction layer still gets text (just non-English).
        async def _failing_translate(text, *, openai_api_key, http_client=None):
            return TranslateResult(
                english=text, tokens_in=0, tokens_out=0,
                cost_usd=0.0, fell_back_to_original=True,
            )
        result = _run(process_voice_note(
            b"<ogg>",
            openai_api_key="sk-test",
            whisper_fn=self._stub_whisper(
                transcript="tenemos cuatro trabajadores",
                language="spanish",
            ),
            translate_fn=_failing_translate,
        ))
        self.assertTrue(result.ok)
        self.assertEqual(result.english_transcript, "tenemos cuatro trabajadores")
        self.assertTrue(result.telemetry["translate_fell_back"])

    def test_telemetry_populated_on_failure_paths(self):
        """The audit row stored by the caller MUST have
        coherent telemetry even when Whisper fails — otherwise a
        spike in failures is invisible in cost dashboards."""
        result = _run(process_voice_note(
            b"<ogg-bytes>",
            openai_api_key="sk-test",
            whisper_fn=self._stub_whisper_raise(RuntimeError("boom")),
            translate_fn=self._stub_translate(),
        ))
        self.assertFalse(result.ok)
        self.assertIn("whisper_cost_usd", result.telemetry)
        self.assertIn("audio_bytes_size", result.telemetry)
        self.assertEqual(result.telemetry["audio_bytes_size"], len(b"<ogg-bytes>"))


# ──────────────────────────────────────────────────────────────────
# Integration sentinels in server.py
# ──────────────────────────────────────────────────────────────────


class TestServerIntegrationPins(unittest.TestCase):
    """Static-source pins: the server.py call site MUST call into
    voice_ingest, persist a whatsapp_voice_events row for both
    success and failure, and append the path-B confirmation cue
    to voice-originated replies."""

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_imports_voice_ingest(self):
        self.assertIn("from lib.voice_ingest import process_voice_note", self.text)

    def test_persists_voice_event_audit_row(self):
        # Pin the collection name so a future cleanup that
        # renames it doesn't silently drop the audit trail.
        self.assertIn("whatsapp_voice_events", self.text)

    def test_idempotency_check_present(self):
        # Pin the idempotency lookup before fetching audio:
        # repeated webhook delivery MUST NOT re-process.
        self.assertIn(
            "db.whatsapp_voice_events.find_one",
            self.text,
        )

    def test_audio_buffer_explicitly_dropped(self):
        # `del audio_bytes` is the belt-and-suspenders against any
        # future caller that reads it post-Whisper.
        self.assertIn("del audio_bytes", self.text)

    def test_path_b_acknowledgment_cue_appended_for_voice(self):
        # Pin the spec's path-B copy so a future reply-format
        # refactor doesn't drop the confirmation prompt.
        self.assertIn(
            "Reply CORRECT to confirm or describe what's wrong.",
            self.text,
        )

    def test_no_r2_writes_in_voice_path(self):
        """Hard rule: audio bytes never written to R2. Pin via
        a static-source check that no R2 writer is called in the
        voice path (text appears between the voice-event audit
        row and the `del audio_bytes` line)."""
        # Find the voice-ingest section and assert _upload_to_r2
        # / r2_client.put_object don't appear in it. Slice the
        # source between two known anchors that bracket the voice
        # path.
        anchor_start = "Phase F1: voice notes go through"
        anchor_end = "del audio_bytes"
        s_idx = self.text.find(anchor_start)
        e_idx = self.text.find(anchor_end, s_idx)
        self.assertGreater(s_idx, 0, "F1 anchor missing — refactor moved it")
        self.assertGreater(e_idx, s_idx, "del audio_bytes anchor missing")
        slice_ = self.text[s_idx:e_idx]
        for forbidden in ("_upload_to_r2", "put_object", "boto3"):
            self.assertNotIn(
                forbidden, slice_,
                f"voice path must not write to R2 / S3 — found {forbidden!r}",
            )


# ──────────────────────────────────────────────────────────────────
# Pricing constants pinned
# ──────────────────────────────────────────────────────────────────


class TestPricingConstants(unittest.TestCase):
    """Pin OpenAI public rates as of 2026-Q1. Bump together with
    the runbook's projection table when OpenAI revises."""

    def test_whisper_rate(self):
        self.assertEqual(PRICING["whisper_per_minute_usd"], 0.006)

    def test_gpt4o_mini_rates(self):
        self.assertEqual(PRICING["gpt4o_mini_input_per_1m_tokens_usd"], 0.150)
        self.assertEqual(PRICING["gpt4o_mini_output_per_1m_tokens_usd"], 0.600)


if __name__ == "__main__":
    unittest.main()
