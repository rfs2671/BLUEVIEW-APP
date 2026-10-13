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
from typing import Any, Dict, List, Optional

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
          "yiddish": "yi", "yi": "yi", "hebrew": "yi", "he": "yi", "iw": "yi",
          # What Whisper often calls Yiddish it does not know: reviewed, translated.
          "german": "de", "de": "de"}


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


def yiddish_lines(voice: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """{original, english} for a Yiddish note: the words as said, and
    Whisper's direct English translation (audio -> English), else the
    translated transcript. None for any other note, or with nothing to show."""
    v = voice or {}
    if v.get("lang") != "yi":
        return None
    original = str(v.get("transcript") or "").strip()
    english = str(v.get("english_direct") or "").strip() or (
        str(v.get("english") or "").strip() if v.get("english") != v.get("transcript") else "")
    if not original:
        return None
    return {"original": original, "english": english,
            "english_source": "whisper_translation" if v.get("english_direct") else
            ("translated_transcript" if english else None)}


def forwarded(*nodes: Any) -> bool:
    """WhatsApp's "Forwarded" label on a webhook message (wweb.js:
    isForwarded, or a forwardingScore above 0, on the message or its _data)."""
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if n.get("isForwarded") is True:
            return True
        try:
            if int(n.get("forwardingScore") or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def name_matches(asked: str, *names: Any) -> bool:
    """"meilich" matches "Meilich Friedman"; every word asked is in a name."""
    words = [w for w in re.findall(r"[^\W_]+", str(asked or "").lower()) if len(w) > 1]
    if not words:
        return True
    for n in names:
        have = set(re.findall(r"[^\W_]+", str(n or "").lower()))
        if have and all(any(h.startswith(w) for h in have) for w in words):
            return True
    return False


def unreliable_note(v: Optional[Dict[str, Any]]) -> bool:
    """A note whose transcript must not be quoted as what was said: one
    Whisper's scores or words gave away, or any note flagged for review
    (Yiddish, Hebrew, German, a sender set to Yiddish, low confidence)."""
    v = v or {}
    if v.get("unreliable") or v.get("failed") == "unreliable":
        return True
    # A note that failed for another reason (too short, download) has no
    # transcript to doubt: it is "not transcribed", said as such.
    return bool(v.get("review")) and not v.get("failed")


def fact_text(row: Dict[str, Any]) -> str:
    """What a model may read of a stored message: its words, or for a voice
    note that may not be what was said, a label (and Whisper's English of the
    audio) -- never the transcript as if someone said it."""
    v = (row or {}).get("voice") or {}
    if v and unreliable_note(v):
        direct = str(v.get("english_direct") or "").strip()
        return (f"(voice note, {UNRELIABLE_TEXT[:-1].lower()}"
                + (f"; Whisper's English of the audio: {direct}" if direct else "") + ")")
    return str((row or {}).get("body") or "").strip()


def who_line(who: str, forwarded: bool) -> str:
    """"Meilich", or "forwarded by Meilich" (the words are someone else's)."""
    who = who or "Someone"
    return f"forwarded by {who}" if forwarded else who


def voice_note_lines(row: Dict[str, Any], who: str, group: str, ny: Any) -> str:
    """One voice note for the DM: "🎤 Sun Oct 11, 2:57 PM · Meilich · 588 Site"
    ("forwarded by Meilich" when forwarded), then "Said: “…”" and, when it is
    not English, "English: …". A flagged note is never quoted: "Not reliably
    transcribed — play it." and Whisper's direct English, if any."""
    v = row.get("voice") or {}
    when = ""
    if ny is not None:
        h = ny.strftime("%I").lstrip("0") or "12"
        when = f"{ny.strftime('%a %b')} {ny.day}, {h}:{ny.strftime('%M %p')}"
    head = " · ".join(p for p in (f"{QUOTE_MARK} {when}".strip(),
                                  who_line(who, bool(row.get("forwarded"))), group) if p)
    said = str(v.get("transcript") or "").strip()
    direct = str(v.get("english_direct") or "").strip()
    if unreliable_note(v):
        return "\n".join([head, UNRELIABLE_TEXT] + (
            [f"English (Whisper's translation of the audio): {direct}"] if direct else []))
    if v.get("failed") or row.get("skipped"):
        why = not_processed(v.get("failed") or str(row.get("skipped") or "").replace("voice_", ""))
        return f"{head}\n(not transcribed: {why})"
    lines = [head, f"Said: “{said}”"]
    english = str(direct or v.get("english") or "").strip()
    if english and english != said and v.get("lang") not in (None, "en"):
        lines.append(f"English: {english}")
    return "\n".join(lines)


# ── THE VOICE LOG (admin): one row per voice note ───────────────────────────

LOG_STATUSES = ("transcribed", "flagged", "not_processed")
BOT_OFF_REASON = "not transcribed: the bot was off for this group"


def log_status(voice: Optional[Dict[str, Any]], skipped: Any = None,
               error_kind: Any = None) -> Dict[str, Any]:
    """{status, reason}: not_processed (why), flagged (an unsure note: a
    Yiddish note or low confidence; why), or transcribed."""
    v = voice or {}
    failed = v.get("failed") or error_kind or (
        str(skipped).replace("voice_", "") if skipped else None)
    if failed:
        return {"status": "not_processed", "reason": not_processed(failed)}
    if v.get("review"):
        return {"status": "flagged", "reason": v.get("review_reason")}
    return {"status": "transcribed", "reason": None}


def log_row(row: Dict[str, Any], *, who: str, where: str, place: str, at: Any,
            produced: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A group voice note for the log. No phone number."""
    v = row.get("voice") or {}
    said = str(v.get("transcript") or "").strip()
    english = str(v.get("english_direct") or v.get("english") or "").strip()
    return {"id": str(row.get("_id")), "where": where, "place": place, "at": at,
            "who": who, "lang": v.get("lang"), "confidence": v.get("confidence"),
            "duration_sec": v.get("duration_sec"), "transcript": said,
            "english": english if english and english != said else "",
            **(log_status(v, row.get("skipped")) if (v or row.get("skipped")) else
               # Stored while the bot was off for the group: never transcribed.
               {"status": "not_processed", "reason": BOT_OFF_REASON}),
            "forwarded": bool(row.get("forwarded")),
            "audio": bool(v.get("audio_key")), "message_row_id": str(row.get("_id")),
            "produced": produced}


def log_row_dm(ev: Dict[str, Any], *, who: str, at: Any) -> Dict[str, Any]:
    """A DM voice note (whatsapp_voice_events) for the log: no audio is kept
    for a DM, and a DM produces no item."""
    said = str(ev.get("original_transcript") or "").strip()
    english = str(ev.get("english_transcript") or "").strip()
    st = log_status(None, None, ev.get("error_kind"))
    if st["status"] == "transcribed" and needs_review(
            ev.get("lang") or lang_code(ev.get("language_detected"), said), ev.get("confidence")):
        st = {"status": "flagged",
              "reason": review_reason(ev.get("lang") or "", ev.get("confidence"))}
    return {"id": str(ev.get("_id")), "where": "dm", "place": "DM", "at": at, "who": who,
            "lang": ev.get("lang") or (lang_code(ev.get("language_detected"), said) if said
                                       else None),
            "confidence": ev.get("confidence"), "duration_sec": ev.get("duration_sec"),
            "transcript": said, "english": english if english and english != said else "",
            **st, "forwarded": False, "audio": False, "message_row_id": None, "produced": []}


def log_keep(row: Dict[str, Any], *, sender: str = "", lang: str = "",
             status: str = "") -> bool:
    if sender and not name_matches(sender, row.get("who")):
        return False
    if lang and (row.get("lang") or "") != lang:
        return False
    if status and row.get("status") != status:
        return False
    return True


#: At this many Yiddish voice notes to review in one group on one day, they
#: are one Attention row ("5 Yiddish voice notes to review").
YIDDISH_BATCH_MIN = 3


def _ny_day(iso: Any) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    return d.astimezone(ZoneInfo("America/New_York")).date().isoformat()


def yiddish_batches(views: List[Dict[str, Any]], min_count: int = YIDDISH_BATCH_MIN):
    """(batches, the rest): open Yiddish voice items for review, grouped by
    group and New York day when there are min_count or more; each batch
    {key, group_name, day, count, label, items}, newest day first."""
    def yid(v):
        return (v.get("voice") and v.get("needs_review") and v.get("lang") == "yi"
                and v.get("status") not in ("done", "cancelled")
                and not v.get("verdict"))           # still to review
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for v in views:
        if yid(v):
            # By the group's id: two groups can share a name ("Unnamed group").
            gid = v.get("group_id") or v.get("group_name") or ""
            groups.setdefault((str(gid), _ny_day(v.get("sent_at"))), []).append(v)
    batches, batched = [], set()
    for (gid, day), vs in groups.items():
        if len(vs) < min_count:
            continue
        vs = sorted(vs, key=lambda v: v.get("sent_at") or "")
        batched |= {id(v) for v in vs}
        batches.append({"key": f"{gid}|{day}", "group_id": gid,
                        "group_name": vs[0].get("group_name") or "", "day": day,
                        "count": len(vs),
                        "label": f"{len(vs)} Yiddish voice notes to review",
                        # Where it sits in the newest-first list: its newest note.
                        "created_at": max((v.get("created_at") or "" for v in vs), default="") or None,
                        "items": vs})
    batches.sort(key=lambda b: (b["day"], b["group_id"]), reverse=True)
    return batches, [v for v in views if id(v) not in batched]


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


# ── A TRANSCRIPT THAT IS NOT WHAT WAS SAID ──────────────────────────────────
#
# 588, Oct 11, 2:57 PM: a forwarded Williamsburg Yiddish blessing came back as
# "People speaking in their native language." -- English, unflagged, and the
# DM assistant quoted it as fact. Whisper describes audio it cannot read, or
# makes up fluent words, and says so in its own scores. Any one of these and
# the note is "not reliably transcribed": kept, never extracted, chased or
# quoted as what was said.

#: Whisper's own limits for a segment it is not sure of (its decoder uses the
#: same three: logprob -1.0, no_speech 0.6 with logprob, compression 2.4).
AVG_LOGPROB_MIN = -1.0
NO_SPEECH_MAX = 0.5
COMPRESSION_MAX = 2.4

#: What Whisper writes when it describes the audio instead of transcribing it.
_TAGS = r"(?:music|applause|laughter|inaudible|silence|indistinct|background noise|" \
        r"foreign(?: language)?|speaking foreign language|no speech|crosstalk)"
_LANGUAGE = (r"(?:native|foreign|another|other|different)?\s*(?:language|tongue)|"
             r"\w+ish|\w+ese|\w+ian|hebrew|arabic|german|french|greek|dutch|hindi|urdu|"
             r"english")
_META = re.compile(
    r"\bpeople\s+(?:are\s+)?(?:speaking|talking|singing|chatting|praying)\b|"
    r"\b(?:speaking|talking)\s+in\s+(?:a\s+|their\s+|his\s+|her\s+|the\s+)?(?:"
    + _LANGUAGE + r")\b|"
    r"\bforeign\s+language\b|"
    r"[\[(]\s*" + _TAGS + r"\s*[\])]|"
    r"^\W*" + _TAGS + r"\W*$|"
    r"\bsubtitles?\s+(?:by|created|provided)\b|\bcaptions?\s+by\b|\btranscribed\s+by\b|"
    r"\bthanks?\s+(?:you\s+)?for\s+watching\b|\bplease\s+subscribe\b", re.I)


def quality_signals(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Whisper's verbose_json scores for a note: avg_logprob (weighted by
    segment length) and the lowest segment's, the highest no_speech_prob and
    compression_ratio, and the segment count. Missing scores stay None. Each
    threshold applies to every segment."""
    num = den = 0.0
    ns, cr, lp = [], [], []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        if isinstance(seg.get("avg_logprob"), (int, float)):
            w = max(float(seg.get("end") or 0) - float(seg.get("start") or 0), 0.01)
            num += float(seg["avg_logprob"]) * w
            den += w
            lp.append(float(seg["avg_logprob"]))
        if isinstance(seg.get("no_speech_prob"), (int, float)):
            ns.append(float(seg["no_speech_prob"]))
        if isinstance(seg.get("compression_ratio"), (int, float)):
            cr.append(float(seg["compression_ratio"]))
    return {"avg_logprob": round(num / den, 3) if den else None,
            # The worst segment: one unsure segment is not hidden by a long
            # sure one (Codex review on #752).
            "min_avg_logprob": round(min(lp), 3) if lp else None,
            "no_speech_prob": round(max(ns), 3) if ns else None,
            "compression_ratio": round(max(cr), 3) if cr else None,
            "segments": len(segments or [])}


def meta_transcript(text: str) -> bool:
    """The transcript describes the audio ("People speaking in their
    native language", "[Music]", "Subtitles by …") instead of saying it."""
    return bool(_META.search(str(text or "")))


def unreliable_reasons(transcript: str, q: Optional[Dict[str, Any]]) -> List[str]:
    """Why this transcript is not what was said ([] when it can be used)."""
    q = q or {}
    out = []
    lp = q.get("min_avg_logprob")
    if not isinstance(lp, (int, float)):
        lp = q.get("avg_logprob")
    if isinstance(lp, (int, float)) and lp < AVG_LOGPROB_MIN:
        out.append(f"avg_logprob {lp} < {AVG_LOGPROB_MIN}")
    if isinstance(q.get("no_speech_prob"), (int, float)) and q["no_speech_prob"] > NO_SPEECH_MAX:
        out.append(f"no_speech_prob {q['no_speech_prob']} > {NO_SPEECH_MAX}")
    if isinstance(q.get("compression_ratio"), (int, float)) \
            and q["compression_ratio"] > COMPRESSION_MAX:
        out.append(f"compression_ratio {q['compression_ratio']} > {COMPRESSION_MAX}")
    if meta_transcript(transcript):
        out.append("describes the audio instead of transcribing it")
    return out


#: Heard in these, or the sender is set to Yiddish: Whisper's direct
#: audio -> English translation too, and a review flag.
TRANSLATE_LANGS = ("yi", "he", "de")


#: What a group's "Languages spoken" may list.
GROUP_LANGS = ("en", "es", "yi")


def group_languages(value: Any) -> Optional[List[str]]:
    """A group's languages as stored: a list of en/es/yi, deduped, in that
    order. None when the value is not such a list."""
    if not isinstance(value, (list, tuple)) or any(
            str(v) not in GROUP_LANGS for v in value):
        return None
    return [l for l in GROUP_LANGS if l in {str(v) for v in value}]


def group_hint(langs: Optional[List[str]]) -> Optional[str]:
    """Whisper's language hint from the group: its one language, else none."""
    return whisper_language(langs[0]) if langs and len(langs) == 1 else None


def heard_outside(lang: Optional[str], langs: Optional[List[str]]) -> bool:
    """Heard in a language the group does not speak (only when it lists
    any). Hebrew is Yiddish here (lang_code)."""
    return bool(langs) and bool(lang) and lang not in langs


def translates_every_note(langs: Optional[List[str]]) -> bool:
    """A group that speaks Yiddish: every note also goes straight to English,
    whatever Whisper says it heard (588, Oct 11, 2:57 PM: Yiddish audio
    labeled English)."""
    return "yi" in (langs or [])


#: Under this, Whisper's English transcript and its direct English of the same
#: audio are not the same words (text-embedding-3-small cosine).
DIVERGE_MIN = 0.75
DIVERGED = "transcript and direct translation disagree"


def diverged(transcript: str, translation: Optional[str],
             similarity: Optional[float]) -> Optional[str]:
    """Why a note heard as English is not what was said, in a group that
    speaks Yiddish: no direct English for the audio, a similarity under
    DIVERGE_MIN, or none to compare (the embeddings failed). None when they
    agree."""
    if not str(translation or "").strip():
        return "no direct translation of the audio"
    if not str(transcript or "").strip():
        return DIVERGED
    if not isinstance(similarity, (int, float)):
        return "transcript and direct translation could not be compared"
    if similarity < DIVERGE_MIN:
        return f"{DIVERGED} (similarity {round(similarity, 2)} < {DIVERGE_MIN})"
    return None


def needs_direct_translation(lang: Optional[str], sender_hint: Optional[str]) -> bool:
    return (lang or "") in TRANSLATE_LANGS or (sender_hint or "") == "yi"


UNRELIABLE_TEXT = "Not reliably transcribed — play it."
#: A DM voice note that says nothing usable while a question is open: the
#: question stays open (Tue Oct 13, 11:3x AM: a 1-second note answering
#: "What's the address?" got "I couldn't find that address. Which borough?").
DM_CANT_HEAR = "I couldn't hear that voice note — can you type it?"

#: What Whisper writes for a second of silence or breath: never an answer.
SILENCE_WORDS = {"you", "thank you", "thanks", "thank you so much", "bye", "bye bye",
                 "so", "uh", "um", "hmm", "mm", "oh", "the", "thanks for watching",
                 "thank you for watching"}


def heard_nothing(transcript: Any, duration_sec: Any = None) -> bool:
    """No words in the transcript; or, from a note under MIN_SECONDS, only
    what Whisper writes for silence ("Thank you.", "you")."""
    words = " ".join(re.sub(r"[^\w\s']", " ", str(transcript or "")).lower().split())
    if not words:
        return True
    short = isinstance(duration_sec, (int, float)) and duration_sec < MIN_SECONDS
    return short and words in SILENCE_WORDS
DM_UNRELIABLE_REPLY = ("I couldn't reliably make out that voice note. "
                       "Please send it again, or type it.")


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
    "prompt_echo": "the transcript repeated Whisper's word list, not what was said",
    "unreliable": "not reliably transcribed",
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
