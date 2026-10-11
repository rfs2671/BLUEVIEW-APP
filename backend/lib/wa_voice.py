"""Group voice notes, the rules in pure code.

A voice note in a project group is transcribed (lib/voice_ingest.py: Whisper,
language detected) and then IS the message: attention, state changes,
Upcoming, memory search and the chase stop-rules read the transcript exactly
as they read typed text. What this module decides:

  lang_code(label, text)   Whisper's language name -> "en" | "es" | "yi" | …
                           (Hebrew script is Yiddish: crews do not speak
                           Hebrew on site).
  needs_review(lang, conf) A Yiddish voice note, or any transcript Whisper
                           was not sure of (confidence below
                           VOICE_CONFIDENCE_MIN), is read but never trusted
                           alone: what it creates is flagged for an admin's
                           review, is never chased, and never closes, moves
                           or cancels anything by itself.
  audio_key(...)           where the audio is kept in R2, under the project
                           (so the project's delete sweeps it).
  row_fields(...)          what the message row stores: the transcript as
                           said, its language, confidence, duration, the
                           audio key, and the English for the group
                           assistant's replies (replies stay English).
  log_line(...)            "[voice] {...}" -- one line per note, for cost
                           and the per-language counts.

The daily cap (VOICE_DAILY_CAP per company, New York day) is enforced in
server.py with one counter row per company per day.

A NOTE THAT CANNOT BE READ IS NEVER ANSWERED IN THE GROUP (Oct 11, live: a
3-second note in 588 got "Voice note couldn't be processed, please retype as
text" posted to the whole group). In a group the bot stays silent: a failed
download or transcription is retried once after RETRY_SECONDS; if that fails
too -- or the note is under MIN_SECONDS, or no words were heard -- the note
is kept (its audio when there is any) and an admin finds it in Attention as
"Voice note not processed" with the reason. Only a DM may ask the sender to
retype.

  playable(b)          the bytes are audio a transcriber can read (Ogg/Opus,
                       MP3, WAV, M4A, WebM) -- not WhatsApp's encrypted .enc
                       blob, which is what a raw media URL returns.
  media_key(raw)       the note's mediaKey from the webhook, to decrypt one.
  not_processed(kind)  why, in words, for the review item.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from lib import multilang

QUOTE_MARK = "🎤"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


VOICE_CONFIDENCE_MIN = _env_float("VOICE_CONFIDENCE_MIN", 0.55)
VOICE_DAILY_CAP = _env_int("VOICE_DAILY_CAP", 200)
DAILY = "voice_daily"           # {_id: "<company>|<day>", count, lang: {..}, review}

_LANGS = {"english": "en", "en": "en", "spanish": "es", "es": "es", "castilian": "es",
          "yiddish": "yi", "yi": "yi", "hebrew": "yi", "he": "yi", "iw": "yi"}


def lang_code(label: Optional[str], text: str = "") -> str:
    """Whisper's language name as a short code. Hebrew script is Yiddish."""
    if text and re.search(r"[֐-׿]", text):
        return "yi"
    k = str(label or "").strip().lower()
    if k in _LANGS:
        return _LANGS[k]
    if not k:
        guess = multilang.detect(text)
        return "en" if guess == "mixed" else guess
    return k[:12]


def needs_review(lang: str, confidence: Optional[float]) -> bool:
    """Yiddish voice, or a transcript below the confidence floor (or with no
    confidence at all): flagged, never chased, never closes anything."""
    if lang == "yi":
        return True
    return confidence is None or confidence < VOICE_CONFIDENCE_MIN


def review_reason(lang: str, confidence: Optional[float]) -> Optional[str]:
    if lang == "yi":
        return "yiddish_voice"
    if confidence is None or confidence < VOICE_CONFIDENCE_MIN:
        return "low_confidence_voice"
    return None


def _safe(v: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(v or ""))[:80] or "x"


def audio_key(project_id: Any, group_id: Any, message_id: Any, ext: str = "ogg") -> str:
    return f"wa-audio/{_safe(project_id)}/{_safe(group_id)}/{_safe(message_id)}.{ext}"


def row_fields(transcript: str, english: str, lang: str, confidence: Optional[float],
               duration_sec: Optional[float], key: Optional[str]) -> Dict[str, Any]:
    """The voice block on the message row. `body` is the transcript AS SAID
    (quotes stay verbatim in the original language); `voice.english` is what
    the group assistant answers from."""
    return {"voice": {
        "transcript": transcript,
        "english": english or transcript,
        "lang": lang,
        "confidence": confidence,
        "duration_sec": round(float(duration_sec), 1) if duration_sec else None,
        "audio_key": key or None,
        "review": needs_review(lang, confidence),
        "review_reason": review_reason(lang, confidence),
    }}


def is_voice(row: Dict[str, Any]) -> bool:
    return bool((row or {}).get("voice"))


def unsure(row: Dict[str, Any]) -> bool:
    """A message whose words may be wrong: never trusted to change state."""
    v = (row or {}).get("voice") or {}
    return bool(v) and bool(v.get("review"))


def mark(quote: str, row: Dict[str, Any]) -> str:
    """"🎤 …" for a quote from a voice note."""
    return f"{QUOTE_MARK} {quote}" if is_voice(row) and quote else quote


def log_line(**kw: Any) -> str:
    return "[voice] " + json.dumps(kw, default=str, sort_keys=True)


# ── A NOTE THAT CANNOT BE READ ───────────────────────────────────────────────

#: Under this long, a note is not transcribed (nothing to read; it bills).
MIN_SECONDS = 2.0
#: A failed download or transcription is tried once more after this long.
RETRY_SECONDS = _env_int("VOICE_RETRY_SECONDS", 60)
#: Failures worth a second try (the network, WaAPI, OpenAI); a short or
#: silent note is what it is.
RETRYABLE = ("download_failed", "not_audio", "whisper_failed")
REVIEW_TYPE = "voice_review"

_REASONS = {
    "download_failed": "the audio could not be downloaded from WhatsApp",
    "not_audio": "WhatsApp sent the audio still encrypted (not playable)",
    "whisper_failed": "transcription failed",
    "too_short": "shorter than 2 seconds",
    "low_confidence": "no words were heard",
    "empty": "no words were heard",
    "audio_too_long": "longer than the voice note limit",
}


def not_processed(kind: Optional[str]) -> str:
    """Why a note was not processed, for the review item."""
    return _REASONS.get(str(kind or ""), "it could not be read")


def playable(b: Optional[bytes]) -> Optional[str]:
    """The container of real audio bytes ("ogg", "mp3", "wav", "m4a",
    "webm"), or None (empty, or WhatsApp's AES-encrypted .enc blob)."""
    if not b or len(b) < 12:
        return None
    if b.startswith(b"OggS"):
        return "ogg"
    # An MPEG audio frame: 11 sync bits, any version, Layer I-III (not the
    # reserved layer 00, which is also where AAC/ADTS sits).
    if b.startswith(b"ID3") or (b[0] == 0xFF and (b[1] & 0xE0) == 0xE0 and b[1] & 0x06):
        return "mp3"
    if b.startswith(b"RIFF") and b[8:12] == b"WAVE":
        return "wav"
    if b[4:8] == b"ftyp":
        return "m4a"
    if b.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return None


_AUDIO_TYPES = {"ogg": ("ogg", "audio/ogg"), "mp3": ("mp3", "audio/mpeg"),
                "wav": ("wav", "audio/wav"), "m4a": ("m4a", "audio/mp4"),
                "webm": ("webm", "audio/webm")}


def audio_type(b: Optional[bytes]) -> tuple:
    """(file extension, mime) for what the bytes are; Ogg (a WhatsApp voice
    note) when they say nothing. The Whisper upload and the kept copy in R2
    are both named by it."""
    return _AUDIO_TYPES[playable(b) or "ogg"]


def media_key(raw: Any, depth: int = 0) -> Optional[str]:
    """The note's mediaKey (base64, 32 bytes decoded) from the webhook
    payload, wherever WaAPI nests it (message._data.mediaKey, media…)."""
    if depth > 8 or raw is None:
        return None
    if isinstance(raw, dict):
        v = raw.get("mediaKey")
        if isinstance(v, str) and len(v) >= 40:
            return v
        for x in raw.values():
            got = media_key(x, depth + 1)
            if got:
                return got
    elif isinstance(raw, list):
        for x in raw:
            got = media_key(x, depth + 1)
            if got:
                return got
    return None


def seconds(raw: Any, depth: int = 0) -> Optional[float]:
    """The note's length as the webhook states it (`duration` / `seconds`),
    before anything is downloaded; None when it does not say."""
    if depth > 8 or not isinstance(raw, (dict, list)):
        return None
    items = raw.values() if isinstance(raw, dict) else raw
    if isinstance(raw, dict):
        for k in ("duration", "seconds"):
            v = raw.get(k)
            try:
                if v not in (None, "") and float(v) >= 0:
                    return float(v)
            except (TypeError, ValueError):
                pass
    for x in items:
        got = seconds(x, depth + 1)
        if got is not None:
            return got
    return None



# ── THE SENDER'S LANGUAGE (People) ───────────────────────────────────────────
# An admin or PM can say what a sender speaks on People: English, Spanish,
# Yiddish, or auto (Whisper detects it, as before). When set, it is Whisper's
# `language` hint: a short or noisy note is not heard as the wrong language.
# Kept per company and sender, apart from who they are (a language can be set
# before a name is): SENDER_LANG_COLLECTION.

SENDER_LANG_COLLECTION = "whatsapp_sender_language"
#: People choice -> Whisper's ISO-639-1 code (None: detect).
SENDER_LANGS = {"auto": None, "en": "en", "es": "es", "yi": "yi"}
SENDER_LANG_LABELS = {"auto": "Auto", "en": "English", "es": "Spanish", "yi": "Yiddish"}


def sender_language(value: Any) -> str:
    """The stored choice ("auto", "en", "es", "yi"), or ValueError."""
    v = str(value or "auto").strip().lower()
    if v not in SENDER_LANGS:
        raise ValueError("Pick English, Spanish, Yiddish or Auto.")
    return v


def whisper_language(value: Any) -> Optional[str]:
    """Whisper's language hint for a stored choice; None for auto/unknown."""
    return SENDER_LANGS.get(str(value or "").strip().lower())


def phone_sender_jid(phone: Any) -> Optional[str]:
    """The sender key for a person on file (a user, a worker) from their
    phone: "12125551234@c.us"; None without a usable number. Unknown senders
    are keyed by the jid their messages came from."""
    from lib import wa_mention
    n = wa_mention.phone(phone)
    return f"{n}@c.us" if n else None
