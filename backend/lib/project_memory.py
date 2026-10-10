"""Project memory search v1: EVIDENCE OR SILENCE. Pure rules, no database.

What a project said, found again: the WhatsApp messages of the project's
linked groups and the filed daily reports, searched by words and by meaning,
and answered only with what a source says, cited.

THE CONTRACT
  - Every claim carries a source: who (their name in People, else their
    WhatsApp name), which group, when, and the exact words (<= QUOTE_MAX).
  - Every quote is checked against the sources that were retrieved for this
    question, verbatim (spacing and curly quotes aside). A claim whose quote
    is in none of them is dropped -- not reworded, not kept "probably".
  - Nothing left: NO_SOURCE. Never an answer from the model's own knowledge.
  - Never posts in a group. DM and the app only.

The server half (indexing, retrieval, the model call, the DM tool and the
app endpoints) is in server.py, "PROJECT MEMORY".
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

COLLECTION = "project_memory"
STATE = "project_memory_state"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMS = 1536
ANSWER_MODEL = "gpt-4o"
TEXT_INDEX = "project_memory_text"
VECTOR_INDEX = "project_memory_vector"

QUOTE_MAX = 200
TEXT_MAX = 1500              # stored per source row
TOP_K = 15                   # sources the model sees for an answer
STORY_MIN, STORY_MAX = 5, 12
RRF_K = 60

NO_SOURCE = "I can't find that in the project history."

SOURCE_WHATSAPP = "whatsapp"
SOURCE_DAILY = "daily_report"
SOURCE_ATTENTION = "attention"


# ── WHAT GOES IN ─────────────────────────────────────────────────────────────

def indexable_message(row: Dict[str, Any]) -> bool:
    """A group message of a linked group, from a person, with words."""
    if not row or row.get("is_dm") or str(row.get("sender") or "") == "bot":
        return False
    if row.get("project_id") in (None, ""):
        return False
    return bool(clean(row.get("body")))


def clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def field_text(v: Any) -> str:
    """A report field as words: a checkbox group (`{'boom_crane': True,
    'compressor': False}`) is the names ticked, a list is its items joined
    -- never the Python form of either (server._log_field, the same rule)."""
    if isinstance(v, dict):
        return ", ".join(str(k).replace("_", " ") for k, on in v.items() if on)
    if isinstance(v, list):
        return ", ".join(clean(x) for x in v if clean(x))
    return clean(v)


def daily_report_entries(log: Dict[str, Any]) -> List[Dict[str, str]]:
    """The text fields of a filed daily jobsite report, one entry each:
    [{key, label, text}]. Order as the report reads."""
    data = log.get("data") or {}
    out: List[Dict[str, str]] = []

    def add(key: str, label: str, text: Any) -> None:
        t = clean(text)
        if t:
            out.append({"key": key, "label": label, "text": t[:TEXT_MAX]})

    add("general", "Work summary", data.get("general_description"))
    for i, a in enumerate(data.get("activities") or []):
        if not isinstance(a, dict):
            continue
        who = " · ".join(x for x in (clean(a.get("company")), clean(a.get("trade"))) if x)
        where = clean(a.get("work_locations") or a.get("work_location"))
        what = clean(a.get("work_description"))
        if what:
            label = f"Activity: {who}" if who else "Activity"
            add(f"activity:{i}", label, f"{what} ({where})" if where else what)
    for i, o in enumerate(data.get("observations") or []):
        if not isinstance(o, dict):
            continue
        add(f"observation:{i}", "Observation", o.get("description") or o.get("note"))
    add("visitors", "Visitors / deliveries", field_text(data.get("visitors_deliveries")))
    add("equipment", "Equipment on site", field_text(data.get("equipment_on_site")))
    add("areas", "Areas visited", field_text(data.get("areas_visited")))
    return out


# ── RETRIEVAL ────────────────────────────────────────────────────────────────

_STOP = set("""
a an the and or but if of to in on at by for with from as is are was were be been
it its this that these those there here what who whom when where why how which
did do does done we you they he she i me my our your their us them can could
would should will shall may might about any some all into out up down over
again than then so just also very not no yes ok please pls hey hi happen happened
""".split())


def terms(text: Any) -> List[str]:
    """Search words: lowercase, no stop words, simple plural stem."""
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9']*", str(text or "").lower()):
        w = w.strip("'")
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) < 2 or w in _STOP:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def lexical_score(query_terms: Sequence[str], text: str) -> float:
    """BM25-shaped: each query word found counts, rarer-in-text less padded.
    Only for the fallback (no Atlas Search)."""
    if not query_terms:
        return 0.0
    words = terms(text)
    if not words:
        return 0.0
    counts: Dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    score = 0.0
    for q in set(query_terms):
        tf = counts.get(q, 0)
        if tf:
            score += (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * len(words) / 30.0))
    return score


def cosine(a: Optional[Sequence[float]], b: Optional[Sequence[float]]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rrf(*ranked: Iterable[str], k: int = RRF_K) -> List[str]:
    """Reciprocal rank fusion of ranked id lists."""
    score: Dict[str, float] = {}
    for lst in ranked:
        for i, sid in enumerate(lst):
            score[sid] = score.get(sid, 0.0) + 1.0 / (k + i + 1)
    return [sid for sid, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))]


# ── THE MODEL'S ANSWER, CHECKED ──────────────────────────────────────────────

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‛": "'", "′": "'",
                         "“": '"', "”": '"', "‟": '"', "″": '"'})


def norm(text: Any) -> str:
    return " ".join(str(text or "").translate(_QUOTES).split()).lower()


def find_quote(quote: str, sources: Sequence[Dict[str, Any]],
               prefer: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The retrieved source whose text holds `quote` verbatim (spacing,
    case and curly quotes aside), the cited one first. None: it is in none."""
    q = norm(quote)
    if not q or len(clean(quote)) > QUOTE_MAX:
        return None
    ordered = sorted(sources, key=lambda s: s.get("sid") != prefer)
    for s in ordered:
        if q in norm(s.get("text")):
            return s
    return None


def is_full_story(query: str) -> bool:
    return bool(re.search(r"\b(what happened (with|to|on)|full story|the story|history of"
                          r"|timeline|walk me through)\b", query or "", re.IGNORECASE))


def parse_model(content: Any) -> Dict[str, Any]:
    try:
        data = json.loads(content or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def checked_claims(raw: Any, sources: Sequence[Dict[str, Any]],
                   limit: int = 12) -> List[Dict[str, Any]]:
    """The model's claims that survive the check: [{text, sid, quote, date?}].
    A quote over QUOTE_MAX, or in no retrieved source, drops its claim."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        text = clean(c.get("text"))
        quote = clean(c.get("quote")).strip('"“”')
        if not text or not quote:
            continue
        src = find_quote(quote, sources, prefer=str(c.get("source") or ""))
        if not src:
            continue
        key = (src["sid"], norm(quote))
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": text, "sid": src["sid"], "quote": quote,
                    "date": clean(c.get("date"))})
        if len(out) >= limit:
            break
    return out


# ── WHAT THE PERSON READS ────────────────────────────────────────────────────

def when(at: Any) -> str:
    """"Oct 3, 7:42 AM" in New York (the caller passes a NY-local datetime)."""
    if not isinstance(at, datetime):
        return ""
    h = at.strftime("%I").lstrip("0") or "12"
    return f"{at.strftime('%b')} {at.day}, {h}:{at.strftime('%M %p')}"


def cite(src: Dict[str, Any]) -> str:
    """"Mike Rivera · Main St Electric · Oct 3, 7:42 AM" / "Daily report · Oct 3"."""
    if src.get("source") == SOURCE_DAILY:
        parts = ["Daily report", src.get("label") or "", src.get("day_label") or ""]
    else:
        parts = [src.get("who") or "Someone", src.get("group") or "", src.get("when") or ""]
    return " · ".join(p for p in parts if p)


def format_answer(claims: Sequence[Dict[str, Any]], by_sid: Dict[str, Dict[str, Any]],
                  timeline: bool = False) -> str:
    """The reply: each claim, then its source and its exact words. NO_SOURCE
    when nothing survived."""
    if not claims:
        return NO_SOURCE
    lines = []
    for c in claims:
        src = by_sid[c["sid"]]
        head = f"{c['date']} — {c['text']}" if timeline and c.get("date") else c["text"]
        lines.append(f"• {head}\n   {cite(src)}: “{c['quote']}”")
    return "\n".join(lines)


def source_block(sources: Sequence[Dict[str, Any]]) -> str:
    """The sources as the model sees them."""
    rows = []
    for s in sources:
        rows.append(f"[{s['sid']}] {cite(s)}\n{s.get('text') or ''}")
    return "\n\n".join(rows)


ANSWER_PROMPT = """You answer questions about ONE construction project from its records: WhatsApp group messages, filed daily reports and tracked items. The records are below, each with an id like [S3].

RULES
- Use ONLY the records. Never your own knowledge, never a guess.
- Every claim needs the id of the record it comes from and an EXACT quote from that record: copied character for character, at most 200 characters, the shortest part that proves the claim.
- If the records do not answer the question, return no claims.
- Names: say who said it as the record shows (the name before the group).
- Keep each claim to one short sentence.

Return JSON: {"claims": [{"text": "...", "source": "S3", "quote": "..."}]}"""

TIMELINE_PROMPT = """You tell what happened with something on ONE construction project, from its records: WhatsApp group messages, filed daily reports and tracked items (commitments, new dates, done). The records are below, each with an id like [S3] and its date.

RULES
- Use ONLY the records. Never your own knowledge, never a guess.
- A dated timeline, oldest first, 5 to 12 entries when the records have that many (fewer is fine).
- Every entry needs the id of its record and an EXACT quote from that record: copied character for character, at most 200 characters.
- If the records say nothing about it, return no entries.

Return JSON: {"claims": [{"date": "Oct 3", "text": "...", "source": "S3", "quote": "..."}]}"""
