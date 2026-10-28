"""Phase F1 — WhatsApp voice note ingestion pipeline.

Orchestrates: Whisper transcription → English translation → Sentry-friendly
error handling → cost telemetry. This module processes audio bytes in
memory only and keeps nothing. (The caller decides storage: a GROUP voice
note's audio is kept in R2 under its project, wa-audio/<project>/…, so the
review screens can play it next to the transcript -- lib/wa_voice.py; a DM
voice note's audio is never stored.)

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

from lib import llm_provider

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
    confidence: Optional[float] = None
    # Per segment: start, end, avg_logprob, no_speech_prob,
    # compression_ratio (verbose_json) -- the hallucination checks read them.
    segments: list = field(default_factory=list)


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
    # How sure Whisper was (0..1, from its per-segment log probabilities)
    # and how long the note ran. None when Whisper never answered.
    confidence: Optional[float] = None
    duration_sec: Optional[float] = None
    # Whisper's own scores (wa_voice.quality_signals) and, when they or the
    # words say the transcript is not speech Whisper could read, why
    # (wa_voice.unreliable_reasons). A non-empty list: never a message.
    quality: Dict[str, Any] = field(default_factory=dict)
    unreliable: list = field(default_factory=list)


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


# ──────────────────────────────────────────────────────────────────
# The duration cap
# ──────────────────────────────────────────────────────────────────
#
# THERE WAS NO CEILING ON THIS AT ALL. process_voice_note took whatever
# bytes the caller handed it and posted them to Whisper. WhatsApp's own
# voicenote limit is measured in tens of minutes, and Whisper bills by the
# minute of audio, so one held thumb was an unbounded charge with no line
# in this file to stop it.
#
# THE GATE HAS TO BE ON BYTES, BECAUSE DURATION ARRIVES TOO LATE. Whisper
# reports `duration` in its response — that is, after the audio has been
# uploaded, transcribed and billed. A cap that reads `wr.duration_sec`
# refuses a call that has already been paid for. The only figure available
# before the spend is len(audio_bytes), so that is what the ceiling is
# written against, and MAX_AUDIO_DURATION_SEC is converted into it here.
#
# THE BITRATE IS AN ASSUMPTION AND IT IS DELIBERATELY GENEROUS. WhatsApp
# encodes voicenotes as Opus in Ogg, mono, typically 16 kbps ≈ 2 KB/s.
# ASSUMED_MAX_BITRATE_KBPS is set to twice that, so a legitimate note at
# the real bitrate is never refused for being dense. The cost of erring
# this way is that a note encoded at the true 16 kbps can reach roughly
# twice MAX_AUDIO_DURATION_SEC before the byte gate closes — the gate is a
# ceiling on spend, not a precise stopwatch, and a ceiling that rejects
# real site traffic is worse than one that is loose.
#
# AND THE TRUE DURATION IS STILL CHECKED AFTERWARDS. Whisper's own
# `duration` is compared against the cap once it comes back. That check
# cannot refund the transcription, and it is not pretending to: what it
# does is stop the translate call that would otherwise follow, and put the
# real number in telemetry next to the byte count, which is the only way
# ASSUMED_MAX_BITRATE_KBPS ever gets corrected from real traffic.
MAX_AUDIO_DURATION_SEC = 120.0
ASSUMED_MAX_BITRATE_KBPS = 32.0
MAX_AUDIO_BYTES = int(MAX_AUDIO_DURATION_SEC * ASSUMED_MAX_BITRATE_KBPS * 1000 / 8)

USER_REPLY_TOO_LONG = (
    "That voice note is too long for me to read. "
    "Send one under two minutes, or type it."
)


def should_reject_audio(n_bytes: int) -> tuple[bool, str]:
    """Return (True, reason) when a buffer is too big to send to Whisper.

    Pure, no network, and called BEFORE the model — see the note above for
    why the gate is on bytes rather than on the duration Whisper reports."""
    if n_bytes > MAX_AUDIO_BYTES:
        return True, f"audio_too_large ({n_bytes} bytes > {MAX_AUDIO_BYTES})"
    return False, ""


# ──────────────────────────────────────────────────────────────────
# The translation gate
# ──────────────────────────────────────────────────────────────────
#
# EVERY TRANSCRIPT WENT TO gpt-4o-mini, INCLUDING THE ENGLISH ONES. The
# translate prompt says "if the input is already English, return it
# UNCHANGED", which is a correct instruction and a paid round trip to
# carry it out. Whisper has already reported the language by that point
# and the field was being stored for telemetry and read by nobody.
#
# So an English transcript now skips the call and passes through. What is
# saved is a whole model round trip per English voicenote, which on a New
# York site is most of them.
#
# AND A LABEL IS NOT PROOF. Whisper mislabels short, noisy or code-switched
# audio, and site speech is all three. A wrong "english" label with no
# second check means untranslated Spanish reaching a superintendent's
# summary, which is a worse failure than the call this saves. The script
# test below is the cheap half of that guard: any run of non-Latin letters
# forces the translation regardless of the label, so a mislabelled Mandarin
# or Arabic note is still translated. A mislabelled Spanish note is NOT
# caught by it — Spanish is Latin script — and the honest statement is that
# this gate trades that case for the saving. `translate_skipped` in
# telemetry is what makes the trade measurable.
_ENGLISH_LABELS = frozenset({"en", "eng", "english"})


def _is_english(language: Optional[str], transcript: str) -> bool:
    """True only when Whisper called it English AND the text looks it."""
    if not language:
        return False                      # unknown language → translate
    if str(language).strip().lower() not in _ENGLISH_LABELS:
        return False
    # Non-Latin letters in something labelled English means the label is
    # wrong. Punctuation, digits and whitespace are ignored.
    for ch in transcript:
        if ch.isalpha() and ord(ch) > 0x024F:
            return False
    return True


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


def aggregate_confidence(segments: list) -> Optional[float]:
    """How sure Whisper was of the words, 0..1: exp of its avg_logprob,
    weighted by each segment's length. None when no segment says."""
    num = den = 0.0
    for seg in segments or []:
        if not isinstance(seg, dict) or not isinstance(seg.get("avg_logprob"), (int, float)):
            continue
        w = max(float(seg.get("end") or 0) - float(seg.get("start") or 0), 0.01)
        num += float(seg["avg_logprob"]) * w
        den += w
    if not den:
        return None
    return round(max(0.0, min(1.0, math.exp(num / den))), 3)


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

def audio_name(audio_bytes: Optional[bytes]) -> tuple:
    """(file name, mime) for the container the bytes are; Ogg (a WhatsApp
    voice note) when they say nothing."""
    from lib import wa_voice
    ext, mime = wa_voice.audio_type(audio_bytes)
    return f"voice.{ext}", mime


async def transcribe_whisper(
    audio_bytes: bytes,
    *,
    openai_api_key: str,
    http_client: Any = None,
    audio_filename: Optional[str] = None,
    audio_mime: Optional[str] = None,
    prompt: Optional[str] = None,
    language: Optional[str] = None,
    model_refused: Optional[Callable[[int, Any], Any]] = None,
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

    url = llm_provider.TRANSCRIBE_URL
    headers = {"Authorization": f"Bearer {openai_api_key}"}
    # Named for what the bytes ARE: Whisper reads the format from the file
    # name, and a forwarded MP3/M4A sent as "voice.ogg" is refused.
    name, mime = audio_name(audio_bytes)
    audio_filename = audio_filename or name
    audio_mime = audio_mime or mime

    # Multipart body: model + file + response_format. We force
    # verbose_json so segments[].no_speech_prob is in the response.
    files = {
        "file": (audio_filename, audio_bytes, audio_mime),
        "model": (None, llm_provider.WHISPER_MODEL),
        "response_format": (None, "verbose_json"),
        "temperature": (None, "0"),
    }
    if prompt:
        # The construction glossary and the job's names (lib/voice_glossary):
        # read by Whisper as text that came before the audio.
        files["prompt"] = (None, prompt)
    if language:
        # The sender's language from People (ISO-639-1): no detection.
        files["language"] = (None, language)

    last_exc: Optional[Exception] = None
    attempt = 0
    while True:
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
            confidence = aggregate_confidence(segments)
            cost = estimate_whisper_cost_usd(duration)
            return WhisperResult(
                transcript=text,
                language=language,
                duration_sec=duration,
                no_speech_prob=no_speech,
                cost_usd=cost,
                raw_segments=len(segments),
                confidence=confidence,
                segments=[{k: s.get(k) for k in ("start", "end", "avg_logprob",
                                                  "no_speech_prob", "compression_ratio")}
                          for s in segments if isinstance(s, dict)],
            )
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            # A refusal someone must fix (no credits, a bad key) is told to
            # the caller's hook, which decides whether it is one (server:
            # lib/model_outage) - the note still fails as it always did.
            if model_refused is not None and status and int(status) >= 401:
                try:
                    try:
                        refused_body = e.response.json()
                    except Exception:
                        refused_body = None
                    await model_refused(int(status), refused_body)
                except Exception:
                    pass
            if status == 400 and "language" in files:
                # A language Whisper refuses (the API's list is narrower than
                # the model's): the note is heard without the hint rather than
                # lost.
                logger.warning(f"[voice_ingest] Whisper refused language "
                               f"{files['language'][1]!r}; detecting instead")
                files.pop("language")
                last_exc = e
                continue        # not a retry: the same call, minus the hint
            # OpenAI's reason ("Invalid file format…") is in the body, not in
            # the exception's text: kept, so a failure says why.
            body = getattr(getattr(e, "response", None), "text", None)
            if body:
                e = RuntimeError(f"{type(e).__name__} {getattr(e.response, 'status_code', '')}: "
                                 f"{str(body)[:300]} (sent {audio_filename}, "
                                 f"{len(audio_bytes)} bytes, first8={audio_bytes[:8].hex()})")
            last_exc = e
            if attempt < WHISPER_MAX_RETRIES:
                logger.warning(
                    f"[voice_ingest] Whisper attempt {attempt+1} failed: "
                    f"{e!r}; retrying in {WHISPER_BACKOFF_SEC}s",
                )
                await asyncio.sleep(WHISPER_BACKOFF_SEC)
                attempt += 1
                continue
            break

    assert last_exc is not None
    raise last_exc


# ──────────────────────────────────────────────────────────────────
# Translation
# ──────────────────────────────────────────────────────────────────


async def translate_whisper(
    audio_bytes: bytes,
    *,
    openai_api_key: str,
    http_client: Any = None,
) -> str:
    """Whisper's translations endpoint: the audio straight to English text
    (whisper-1; no transcript in between). Used for Yiddish notes, whose
    card shows what was said and this. Retries once; raises on failure."""
    if not openai_api_key:
        raise RuntimeError("openai_api_key required for Whisper")
    if not audio_bytes:
        raise RuntimeError("empty audio_bytes")
    url = llm_provider.TRANSLATE_URL
    headers = {"Authorization": f"Bearer {openai_api_key}"}
    name, mime = audio_name(audio_bytes)
    files = {"file": (name, audio_bytes, mime), "model": (None, llm_provider.WHISPER_MODEL),
             "response_format": (None, "json"), "temperature": (None, "0")}
    attempt = 0
    while True:
        try:
            if http_client is None:
                async with ServerHttpClient(timeout=OPENAI_TIMEOUT_SEC) as c:
                    resp = await c.post(url, headers=headers, files=files)
                    resp.raise_for_status()
                    payload = resp.json()
            else:
                resp = await http_client.post(url, headers=headers, files=files,
                                              timeout=OPENAI_TIMEOUT_SEC)
                resp.raise_for_status()
                payload = resp.json()
            return (payload.get("text") or "").strip()
        except Exception as e:
            if attempt < WHISPER_MAX_RETRIES:
                logger.warning(f"[voice_ingest] Whisper translation attempt {attempt+1} "
                               f"failed: {e!r}; retrying in {WHISPER_BACKOFF_SEC}s")
                await asyncio.sleep(WHISPER_BACKOFF_SEC)
                attempt += 1
                continue
            raise



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

    url = llm_provider.CHAT_URL
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": llm_provider.CHAT_MODEL,
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
    prompt: Optional[str] = None,
    language: Optional[str] = None,
    model_refused: Optional[Callable[[int, Any], Any]] = None,
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
        "translate_skipped": False,
        "rejected_reason": None,
    }

    # ── Size gate, before the model, because after it the bill exists ──
    too_big, big_reason = should_reject_audio(telemetry["audio_bytes_size"])
    if too_big:
        logger.info(f"[voice_ingest] rejected: {big_reason}")
        telemetry["rejected_reason"] = big_reason
        return VoiceIngestResult(
            ok=False,
            user_reply=USER_REPLY_TOO_LONG,
            error_kind="audio_too_long",
            telemetry=telemetry,
        )

    # ── Whisper ────────────────────────────────────────────────────
    try:
        wr = await _whisper(
            audio_bytes,
            openai_api_key=openai_api_key,
            http_client=http_client,
            **({"model_refused": model_refused} if model_refused else {}),
            **({"prompt": prompt} if prompt else {}),
            **({"language": language} if language else {}),
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
    telemetry["whisper_prompt"] = bool(prompt)
    telemetry["whisper_language_hint"] = language or None
    telemetry["whisper_cost_usd"] = wr.cost_usd
    telemetry["whisper_no_speech_prob"] = wr.no_speech_prob
    telemetry["whisper_segments"] = wr.raw_segments
    telemetry["whisper_confidence"] = wr.confidence
    # Whisper's scores, and whether they (or the words) say this is not
    # speech it could read: "People speaking in their native language" for a
    # Yiddish blessing (588, Oct 11, 2:57 PM).
    from lib import wa_voice as _wv
    quality = _wv.quality_signals(getattr(wr, "segments", None) or [])
    unreliable = _wv.unreliable_reasons(wr.transcript, quality)
    telemetry["whisper_quality"] = quality
    telemetry["unreliable"] = unreliable

    # ── The prompt read back, not speech ───────────────────────────
    # (588, Oct 11, 2:51 PM.) A failed transcription: never a message.
    if prompt:
        from lib import voice_glossary
        if voice_glossary.prompt_echo(wr.transcript, prompt):
            logger.info("[voice_ingest] prompt echo: transcript repeats the Whisper prompt")
            telemetry["rejected_reason"] = "prompt_echo"
            return VoiceIngestResult(
                ok=False,
                original_transcript=wr.transcript,
                language_detected=wr.language,
                no_speech_prob=wr.no_speech_prob,
                confidence=wr.confidence,
                duration_sec=wr.duration_sec,
                user_reply=USER_REPLY_PROCESSING_FAILED,
                error_kind="prompt_echo",
                telemetry=telemetry,
            )

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
            confidence=wr.confidence,
            duration_sec=wr.duration_sec,
            user_reply=USER_REPLY_NO_SPEECH,
            error_kind="low_confidence",
            telemetry=telemetry,
        )

    # ── The true duration, now that it exists ──────────────────────
    #
    # This cannot un-bill the transcription above. It stops the translate
    # call, and it records how far past the cap the byte gate let this one
    # through — which is the measurement that tells us whether
    # ASSUMED_MAX_BITRATE_KBPS is set too high.
    if wr.duration_sec and wr.duration_sec > MAX_AUDIO_DURATION_SEC:
        logger.info(
            f"[voice_ingest] over cap after transcription: "
            f"{wr.duration_sec:.1f}s > {MAX_AUDIO_DURATION_SEC}s "
            f"({telemetry['audio_bytes_size']} bytes passed the byte gate)"
        )
        telemetry["rejected_reason"] = f"duration_over_cap ({wr.duration_sec:.1f}s)"
        return VoiceIngestResult(
            ok=False,
            original_transcript=wr.transcript,
            language_detected=wr.language,
            no_speech_prob=wr.no_speech_prob,
            confidence=wr.confidence,
            duration_sec=wr.duration_sec,
            user_reply=USER_REPLY_TOO_LONG,
            error_kind="audio_too_long",
            telemetry=telemetry,
        )

    # ── Translate, unless it is already English ────────────────────
    if _is_english(wr.language, wr.transcript):
        telemetry["translate_skipped"] = True
        telemetry["translate_fell_back"] = False
        return VoiceIngestResult(
            ok=True,
            english_transcript=wr.transcript,
            original_transcript=wr.transcript,
            language_detected=wr.language,
            no_speech_prob=wr.no_speech_prob,
            confidence=wr.confidence,
            duration_sec=wr.duration_sec,
            telemetry=telemetry,
            quality=quality,
            unreliable=unreliable,
        )

    telemetry["translate_skipped"] = False
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
        confidence=wr.confidence,
        duration_sec=wr.duration_sec,
        telemetry=telemetry,
        quality=quality,
        unreliable=unreliable,
    )
