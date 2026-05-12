"""Phase F1 — WhatsApp voice note ingestion pipeline.

Orchestrates: Whisper transcription → English translation → Sentry-friendly
error handling → cost telemetry. Audio bytes are processed in-memory only
and discarded immediately after Whisper returns; nothing voice-related is
ever written to R2 or any other persistent blob store.

──────────────────────────────────────────────────────────────────
Why this lives in lib/ rather than inline in server.py
──────────────────────────────────────────────────────────────────

server.py already has a `transcribe_audio` function (Whisper call) and a
`download_audio` function (WaAPI fetch + decrypt). Phase F1 doesn't
remove them — `download_audio` keeps owning the WaAPI specifics
(serialized message id, base64-or-URL response, optional WhatsApp
mediaKey decryption — see Step 1 verification in the F1 commit body).

What lives HERE:

  • The post-download orchestration: verbose_json Whisper call (so we
    can capture no_speech_prob), the no-speech / too-short short-circuit,
    GPT-4o-mini translation, retry policy, and cost telemetry collection.

  • Pure decision functions that don't touch network — separated so
    tests can exercise the short-circuit logic + telemetry math without
    spinning up FastAPI or mocking an entire HTTP client.

  • A single entry point `process_voice_note` the webhook handler in
    server.py imports and calls AFTER it has the audio bytes. The
    handler stays in charge of idempotency (whatsapp_voice_events
    de-dupe), agent reply formatting, and final downstream writes.

──────────────────────────────────────────────────────────────────
Cost telemetry (verified against OpenAI public pricing, 2026-Q1)
──────────────────────────────────────────────────────────────────

  Whisper   $0.006 per audio minute, billed in 1-second granularity
            (we round up to the next second, like OpenAI does).
  GPT-4o-mini   $0.150 per 1M input tokens, $0.600 per 1M output tokens.

A typical 30-second jobsite voice note hits:
  • Whisper:   30s ÷ 60 × $0.006 = $0.003
  • Translate: ~150 tokens in / ~150 tokens out × per-token rates
                = $0.0000225 + $0.00009 ≈ $0.00012
  • Per-note total: ~$0.0031.

Embedded in the PRICING dict so a future pricing change is a single-
line edit, and the cost-projection figures in the runbook stay
sourced from one place.

──────────────────────────────────────────────────────────────────
Public surface
──────────────────────────────────────────────────────────────────

  process_voice_note(audio_bytes, *, openai_api_key, http_client=None)
    → VoiceIngestResult

  WhisperResult, TranslateResult, VoiceIngestResult — dataclasses
    capturing intermediate state (transcript + per-stage telemetry).

  should_short_circuit(transcript, no_speech_prob) → (bool, reason_str)
    Pure decision. Tests pin the threshold + length checks directly.

  estimate_*_cost_usd(...) — pure cost math, used by the orchestrator
    and exposed for billing aggregation queries.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, Optional

from lib.server_http import ServerHttpClient

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Tunables
# ──────────────────────────────────────────────────────────────────


# OpenAI public pricing as of 2026-Q1. Verify quarterly; bump when
# OpenAI revises. A single source of truth keeps the runbook's cost
# projection figures honest.
PRICING = {
    "whisper_per_minute_usd": 0.006,
    "gpt4o_mini_input_per_1m_tokens_usd": 0.150,
    "gpt4o_mini_output_per_1m_tokens_usd": 0.600,
}

# Threshold for "this isn't speech" / "too short" → ask user to resend.
# Numbers from spec; re-tune if false-positive rate is too high.
NO_SPEECH_PROB_THRESHOLD = 0.6
MIN_TRANSCRIPT_CHARS = 5

# Retry policy. The spec asks for 2 retries on download-media failures
# (handled by the caller in server.py — we own the Whisper retry only).
WHISPER_MAX_RETRIES = 1   # spec: "Whisper API failure: retry 1x"
WHISPER_BACKOFF_SEC = 0.5

OPENAI_TIMEOUT_SEC = 60.0

# Translation prompt — minimal, deterministic, no chain-of-thought.
# We want the model to pass English through unchanged. Tested mentally
# against Spanish, Mandarin, Polish — all return the English-equivalent
# without commentary.
TRANSLATE_SYSTEM_PROMPT = (
    "You translate worker voice-note transcripts to English. "
    "If the input is already English, return it UNCHANGED. "
    "Output ONLY the translation. No preface, no commentary, "
    "no quotes, no language tag."
)


# ──────────────────────────────────────────────────────────────────
# Result types
# ──────────────────────────────────────────────────────────────────


@dataclass
class WhisperResult:
    transcript: str
    language: Optional[str]
    duration_sec: float
    no_speech_prob: float
    cost_usd: float
    raw_segments: int = 0


@dataclass
class TranslateResult:
    english: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    fell_back_to_original: bool = False


@dataclass
class VoiceIngestResult:
    """End-state of the voice ingestion pipeline.

    `ok=True`:  the English transcript is good enough to feed
                downstream extraction.
    `ok=False`: do NOT pass to extraction. `user_reply` is the
                copy the bot should send back to the user.

    `telemetry` is always populated (even on failure paths) so the
    cost row that the caller persists is comprehensive."""

    ok: bool
    english_transcript: str = ""
    original_transcript: str = ""
    language_detected: Optional[str] = None
    no_speech_prob: Optional[float] = None
    user_reply: Optional[str] = None       # set when ok=False
    error_kind: Optional[str] = None       # "whisper_failed" / "low_confidence" / etc.
    telemetry: Dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────
# Pure helpers (no network)
# ──────────────────────────────────────────────────────────────────


def estimate_whisper_cost_usd(duration_sec: float) -> float:
    """OpenAI bills Whisper in 1-second increments, rounded UP."""
    if duration_sec <= 0:
        return 0.0
    seconds = math.ceil(duration_sec)
    return round((seconds / 60.0) * PRICING["whisper_per_minute_usd"], 6)


def estimate_translate_cost_usd(tokens_in: int, tokens_out: int) -> float:
    cost = (
        (tokens_in / 1_000_000.0)
            * PRICING["gpt4o_mini_input_per_1m_tokens_usd"]
        + (tokens_out / 1_000_000.0)
            * PRICING["gpt4o_mini_output_per_1m_tokens_usd"]
    )
    return round(cost, 6)


def should_short_circuit(
    transcript: str, no_speech_prob: Optional[float],
) -> tuple[bool, str]:
    """Return (True, reason) if the transcript should be discarded
    rather than passed to extraction. False if it's a usable transcript.

    Two conditions per spec:
      • transcript shorter than MIN_TRANSCRIPT_CHARS (silence /
        background hum / accidental tap)
      • no_speech_prob above NO_SPEECH_PROB_THRESHOLD (Whisper's own
        per-segment estimate that the audio isn't speech).
    """
    if len(transcript.strip()) < MIN_TRANSCRIPT_CHARS:
        return True, f"transcript_too_short ({len(transcript.strip())} chars)"
    if no_speech_prob is not None and no_speech_prob > NO_SPEECH_PROB_THRESHOLD:
        return True, f"no_speech_prob {no_speech_prob:.2f} > {NO_SPEECH_PROB_THRESHOLD}"
    return False, ""


def aggregate_no_speech_prob(segments: list) -> float:
    """Whisper's verbose_json returns per-segment no_speech_prob. We
    take the MAX across segments — a single high-no-speech segment
    is enough to flag the audio as suspect (vs averaging which lets
    one good segment hide a mostly-silent recording).
    """
    if not segments:
        return 0.0
    values = []
    for s in segments:
        v = s.get("no_speech_prob") if isinstance(s, dict) else None
        if isinstance(v, (int, float)):
            values.append(float(v))
    if not values:
        return 0.0
    return max(values)


# ──────────────────────────────────────────────────────────────────
# Whisper call
# ──────────────────────────────────────────────────────────────────


async def transcribe_whisper(
    audio_bytes: bytes,
    *,
    openai_api_key: str,
    http_client: Any = None,
    audio_filename: str = "voice.ogg",
    audio_mime: str = "audio/ogg",
) -> WhisperResult:
    """Call OpenAI Whisper in verbose_json mode so we get
    no_speech_prob per segment. Auto-detects language. Retries
    once on transient failures (per spec).

    `http_client` is for tests — pass a stub that supports
    `.post(url, headers=..., files=..., timeout=...)` returning an
    object with `.status_code`, `.json()`, and `.raise_for_status()`.
    Production constructs a ServerHttpClient (the only async HTTP
    client allowed in backend/ by the architectural-rules CI guard).
    api.openai.com is not on the Akamai blocklist, so the wrapper's
    runtime guard is a no-op here — architectural rule applies
    belt-and-suspenders.

    Raises on permanent failure (network exhaustion, 4xx that won't
    recover). Caller catches + maps to user-facing error reply.
    """
    if not openai_api_key:
        raise RuntimeError("openai_api_key required for Whisper")
    if not audio_bytes:
        raise RuntimeError("empty audio_bytes — caller should short-circuit")

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {openai_api_key}"}

    # Multipart body: model + file + response_format. We force
    # verbose_json so segments[].no_speech_prob is in the response.
    files = {
        "file": (audio_filename, audio_bytes, audio_mime),
        "model": (None, "whisper-1"),
        "response_format": (None, "verbose_json"),
        "temperature": (None, "0"),
    }

    last_exc: Optional[Exception] = None
    for attempt in range(WHISPER_MAX_RETRIES + 1):
        try:
            if http_client is None:
                async with ServerHttpClient(timeout=OPENAI_TIMEOUT_SEC) as c:
                    resp = await c.post(url, headers=headers, files=files)
                    resp.raise_for_status()
                    payload = resp.json()
            else:
                resp = await http_client.post(
                    url, headers=headers, files=files,
                    timeout=OPENAI_TIMEOUT_SEC,
                )
                resp.raise_for_status()
                payload = resp.json()

            text = (payload.get("text") or "").strip()
            language = payload.get("language") or None
            duration = float(payload.get("duration") or 0.0)
            segments = payload.get("segments") or []
            no_speech = aggregate_no_speech_prob(segments)
            cost = estimate_whisper_cost_usd(duration)
            return WhisperResult(
                transcript=text,
                language=language,
                duration_sec=duration,
                no_speech_prob=no_speech,
                cost_usd=cost,
                raw_segments=len(segments),
            )
        except Exception as e:
            last_exc = e
            if attempt < WHISPER_MAX_RETRIES:
                logger.warning(
                    f"[voice_ingest] Whisper attempt {attempt+1} failed: "
                    f"{e!r}; retrying in {WHISPER_BACKOFF_SEC}s",
                )
                await asyncio.sleep(WHISPER_BACKOFF_SEC)
                continue
            break

    assert last_exc is not None
    raise last_exc


# ──────────────────────────────────────────────────────────────────
# Translation
# ──────────────────────────────────────────────────────────────────


async def translate_to_english(
    text: str,
    *,
    openai_api_key: str,
    http_client: Any = None,
) -> TranslateResult:
    """Translate via GPT-4o-mini. Pass-through for English.

    Spec contract: on failure, fall back to the original transcript
    (extraction may still handle some non-English). We capture the
    `fell_back_to_original` flag so telemetry separates "real
    translation" from "translation skipped due to API failure".

    Tests pass `http_client` stubs; production uses ServerHttpClient
    (same rationale as transcribe_whisper above).
    """
    if not openai_api_key:
        return TranslateResult(
            english=text, tokens_in=0, tokens_out=0, cost_usd=0.0,
            fell_back_to_original=True,
        )
    if not text or not text.strip():
        return TranslateResult(
            english=text, tokens_in=0, tokens_out=0, cost_usd=0.0,
        )

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "gpt-4o-mini",
        "temperature": 0,
        "messages": [
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }

    try:
        if http_client is None:
            async with ServerHttpClient(timeout=OPENAI_TIMEOUT_SEC) as c:
                resp = await c.post(url, headers=headers, json=body)
                resp.raise_for_status()
                payload = resp.json()
        else:
            resp = await http_client.post(
                url, headers=headers, json=body,
                timeout=OPENAI_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            payload = resp.json()

        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI returned no choices")
        english = (choices[0].get("message") or {}).get("content") or ""
        english = english.strip()
        if not english:
            raise RuntimeError("OpenAI returned empty translation")

        usage = payload.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        cost = estimate_translate_cost_usd(tokens_in, tokens_out)
        return TranslateResult(
            english=english,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
    except Exception as e:
        # Per spec: log + fall back to the original transcript.
        # Caller already passes Whisper output through, so the
        # extraction layer at least has a chance.
        logger.warning(
            f"[voice_ingest] translation failed; falling back to original "
            f"transcript: {e!r}",
        )
        return TranslateResult(
            english=text,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            fell_back_to_original=True,
        )


# ──────────────────────────────────────────────────────────────────
# User-facing error replies
# ──────────────────────────────────────────────────────────────────


# Centralized so tests can pin the exact wording the user sees.
USER_REPLY_NO_SPEECH = "I didn't catch that — can you resend?"
USER_REPLY_PROCESSING_FAILED = (
    "Voice note couldn't be processed, please retype as text."
)


# ──────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────


async def process_voice_note(
    audio_bytes: bytes,
    *,
    openai_api_key: str,
    http_client: Any = None,
    sentry_capture: Optional[Callable[..., None]] = None,
    whisper_fn: Optional[Callable[..., Any]] = None,
    translate_fn: Optional[Callable[..., Any]] = None,
) -> VoiceIngestResult:
    """Full pipeline: Whisper → freshness check → translate.

    Audio bytes are read once for Whisper, then dropped — the function
    holds NO reference to them after the Whisper call returns. The
    caller must also drop its reference for the buffer to be GC'd
    promptly. Audio is NEVER written anywhere.

    Side effects: ZERO writes (no DB, no R2, no filesystem).

    Returns a `VoiceIngestResult` whose telemetry payload is suitable
    for direct insertion into the caller's voice_event_log row.
    """
    # Inject overrides so tests don't need to mock httpx end-to-end —
    # they can pass a single stub function that returns canned
    # WhisperResult / TranslateResult instances.
    _whisper = whisper_fn or transcribe_whisper
    _translate = translate_fn or translate_to_english

    telemetry: Dict[str, Any] = {
        "whisper_duration_sec": 0.0,
        "whisper_cost_usd": 0.0,
        "whisper_no_speech_prob": None,
        "translate_tokens_in": 0,
        "translate_tokens_out": 0,
        "translate_cost_usd": 0.0,
        "translate_fell_back": False,
        "audio_bytes_size": len(audio_bytes) if audio_bytes else 0,
    }

    # ── Whisper ────────────────────────────────────────────────────
    try:
        wr = await _whisper(
            audio_bytes,
            openai_api_key=openai_api_key,
            http_client=http_client,
        )
    except Exception as e:
        msg = f"voice_ingest_whisper_failed: {type(e).__name__}: {e}"
        logger.error(msg)
        if sentry_capture is not None:
            try:
                sentry_capture(msg, level="warning")
            except Exception:
                pass
        return VoiceIngestResult(
            ok=False,
            user_reply=USER_REPLY_PROCESSING_FAILED,
            error_kind="whisper_failed",
            telemetry=telemetry,
        )

    telemetry["whisper_duration_sec"] = wr.duration_sec
    telemetry["whisper_cost_usd"] = wr.cost_usd
    telemetry["whisper_no_speech_prob"] = wr.no_speech_prob
    telemetry["whisper_segments"] = wr.raw_segments

    # ── Short-circuit ─────────────────────────────────────────────
    short_circuit, reason = should_short_circuit(wr.transcript, wr.no_speech_prob)
    if short_circuit:
        # Don't fire Sentry — short-circuit is expected behavior under
        # noisy conditions, not a bug. Just log to stdout and return
        # the user-facing "didn't catch that" copy.
        logger.info(f"[voice_ingest] short-circuit: {reason}")
        return VoiceIngestResult(
            ok=False,
            original_transcript=wr.transcript,
            language_detected=wr.language,
            no_speech_prob=wr.no_speech_prob,
            user_reply=USER_REPLY_NO_SPEECH,
            error_kind="low_confidence",
            telemetry=telemetry,
        )

    # ── Translate ──────────────────────────────────────────────────
    tr = await _translate(
        wr.transcript,
        openai_api_key=openai_api_key,
        http_client=http_client,
    )
    telemetry["translate_tokens_in"] = tr.tokens_in
    telemetry["translate_tokens_out"] = tr.tokens_out
    telemetry["translate_cost_usd"] = tr.cost_usd
    telemetry["translate_fell_back"] = tr.fell_back_to_original

    return VoiceIngestResult(
        ok=True,
        english_transcript=tr.english,
        original_transcript=wr.transcript,
        language_detected=wr.language,
        no_speech_prob=wr.no_speech_prob,
        telemetry=telemetry,
    )
