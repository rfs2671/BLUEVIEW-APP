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


def audio_key(project_id: Any, group_id: Any, message_id: Any) -> str:
    return f"wa-audio/{_safe(project_id)}/{_safe(group_id)}/{_safe(message_id)}.ogg"


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
