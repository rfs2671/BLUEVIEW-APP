"""Project Attention Engine v1 — the pure parts (no database, no network).

SHADOW MODE. The engine reads stored group messages and records what needs
someone's attention (a question, a request, a commitment, an issue, a
decision) into `attention_items`. It posts NOTHING, anywhere. An admin
reviews the items in the app (Correct / Wrong / Dismiss) so precision can be
measured before any of it is ever shown to a group.

What lives here, each a plain function tested without a server:

  * the cheap filter: which messages are worth a model call at all
  * the model request and the parsing of its answer
  * EVIDENCE OR SILENCE: an item's quote must be an exact piece of the
    message it cites, checked here in code; otherwise the item is dropped
  * the due date: kept exactly as said; a date is set only when the code
    itself can read one from that text (never from the model)
  * importance: the model's label, raised (never lowered) by safety words
  * the dedupe key, and precision per type from the admin's verdicts

What the model never decides: who owns an item (resolved in code from the
@mention / reply author / sender), a due date, or whether anything is posted.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

try:  # zoneinfo is stdlib; tzdata may be absent on a slim image
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None

PROMPT_VERSION = "att-v1.0"
MODEL = "gpt-4o-mini"

TYPES = ("question", "request", "commitment", "issue", "decision")
IMPORTANCE = ("low", "normal", "high")
VERDICTS = ("correct", "wrong", "dismissed")
STATUSES = ("open", "possibly_resolved", "dismissed")

# How many earlier messages of the same group the model sees with one message.
CONTEXT_MESSAGES = 10
# Items with the same key inside this many days are one item.
DEDUPE_DAYS = 7
MAX_QUOTE_CHARS = 300
MAX_ITEMS_PER_MESSAGE = 3


# ── 1. THE CHEAP FILTER ─────────────────────────────────────────────────────
#
# A model call only for a message that shows a sign of needing someone: a
# question mark, an @mention, a reply, or a commitment / issue / decision
# word. The same rule as the report's query 6b, so the measured pass rate is
# the cost that is actually paid.

FILTER_WORDS_RE = re.compile(
    r"\b(will|i'll|we'll|gonna|tomorrow|by (mon|tue|wed|thu|fri|sat|sun|eod|end of)"
    r"|deadline|inspection|rfi|submittal|leak|crack|broken|unsafe|violation"
    r"|stop work|decided|approved|go with)\b", re.IGNORECASE)

MIN_BODY_CHARS = 6


def filter_reason(msg: Dict[str, Any]) -> Optional[str]:
    """Why this stored message is worth a model call, or None to skip it."""
    body = str(msg.get("body") or "").strip()
    if len(body) < MIN_BODY_CHARS:
        return None
    if str(msg.get("sender") or "") == "bot" or msg.get("from_me"):
        return None
    if msg.get("skipped"):
        return None
    if msg.get("mentioned_jids"):
        return "mention"
    if str(msg.get("quoted_message_id") or "").strip():
        return "reply"
    if "?" in body:
        return "question_mark"
    if FILTER_WORDS_RE.search(body):
        return "keyword"
    return None


# ── 2. WHO A STORED SENDER IS ───────────────────────────────────────────────
#
# Rows written before sender_jid existed carry the digits only, so the kind is
# read from the length: phones are up to 13 digits, WhatsApp privacy ids
# (@lid) are 14 or more.

def sender_jid(msg: Dict[str, Any]) -> str:
    """The sender as a JID: the stored one, else rebuilt from the digits."""
    jid = str(msg.get("sender_jid") or "").strip()
    if "@" in jid:
        return jid
    digits = re.sub(r"\D", "", str(msg.get("sender") or ""))
    if not digits:
        return ""
    return f"{digits}@lid" if len(digits) >= 14 else f"{digits}@c.us"


def jid_kind(jid: str) -> str:
    raw = str(jid or "")
    domain = raw.split("@", 1)[1].lower() if "@" in raw else ""
    if domain == "lid":
        return "lid"
    if domain in ("c.us", "s.whatsapp.net"):
        return "phone"
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return "none"
    return "lid" if len(digits) >= 14 else "phone"


# ── 3. THE MODEL REQUEST ────────────────────────────────────────────────────

SYSTEM_PROMPT = """You read one WhatsApp message from a NYC construction project group, with the messages before it for context.

Find what in THE MESSAGE needs someone's attention. Types:
- question: asks something that needs an answer
- request: asks someone to do or send something
- commitment: someone says they will do something
- issue: a problem on site (leak, damage, safety, delay, failed inspection)
- decision: something was decided or approved

Rules:
- Only the message marked >>>. The context is for understanding only.
- "quote" must be copied EXACTLY, character for character, from the >>> message. Never paraphrase. Short is fine.
- "owner_text": the name or role exactly as written in the message, if one is named as the person to act. Otherwise null. Never guess.
- "due_text": the time words exactly as written (e.g. "by Friday", "tomorrow morning"). Otherwise null.
- importance: high only for safety, stop work, inspections, leaks or anything blocking work; low for small talk-level items; else normal.
- Greetings, thanks, jokes, photos with no ask, and plain status updates are NOT items.
- At most 3 items. None is a fine answer.

Return JSON: {"items": [{"type": "...", "quote": "...", "summary": "under 15 words", "owner_text": null, "due_text": null, "importance": "normal", "tags": ["..."]}]}"""


def _line(m: Dict[str, Any]) -> str:
    who = "bot" if str(m.get("sender") or "") == "bot" else (
        "…" + str(m.get("sender") or "")[-4:])
    return f"{who}: {str(m.get('body') or '')[:500]}"


def build_messages(msg: Dict[str, Any], context: Iterable[Dict[str, Any]],
                   quoted: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """The chat request for one message. Senders are shown by their last four
    digits only: the model needs to tell people apart, not who they are."""
    lines = [_line(c) for c in list(context)[-CONTEXT_MESSAGES:]]
    parts = []
    if lines:
        parts.append("Earlier messages:\n" + "\n".join(lines))
    if quoted and quoted.get("body"):
        parts.append("The message being replied to:\n" + _line(quoted))
    parts.append(">>> " + _line(msg))
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)}]


def parse_items(content: Any) -> List[Dict[str, Any]]:
    """The model's items, shape-checked. Anything malformed is dropped."""
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except Exception:
        return []
    raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out = []
    for it in raw:
        if len(out) >= MAX_ITEMS_PER_MESSAGE:
            break
        if not isinstance(it, dict):
            continue
        typ = str(it.get("type") or "").strip().lower()
        quote = it.get("quote")
        if typ not in TYPES or not isinstance(quote, str) or not quote.strip():
            continue
        imp = str(it.get("importance") or "normal").strip().lower()
        tags = it.get("tags") if isinstance(it.get("tags"), list) else []
        out.append({
            "type": typ,
            "quote": quote.strip(),
            "summary": str(it.get("summary") or "").strip()[:200],
            "owner_text": _opt_text(it.get("owner_text")),
            "due_text": _opt_text(it.get("due_text")),
            "importance": imp if imp in IMPORTANCE else "normal",
            "tags": [str(t).strip().lower()[:30] for t in tags[:5]
                     if isinstance(t, str) and t.strip()],
        })
    return out


def _opt_text(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v or v.lower() in ("null", "none", "n/a", "unknown"):
        return None
    return v[:120]


# ── 4. EVIDENCE OR SILENCE ──────────────────────────────────────────────────
#
# The quote is checked against the stored body of the message it cites. Only
# typography is forgiven (curly quotes, dashes, runs of spaces, case); a single
# changed word fails. The stored quote is the slice of the REAL body, so what
# an admin reads is what was written, never the model's copy of it.

_TYPO = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                       "–": "-", "—": "-", " ": " "})


def _norm_with_map(text: str):
    """Normalised text, and for each of its characters the index in `text`."""
    out, idx = [], []
    prev_space = False
    for i, ch in enumerate(text.translate(_TYPO)):
        if ch.isspace():
            if prev_space:
                continue
            ch, prev_space = " ", True
        else:
            prev_space = False
        out.append(ch.lower())
        idx.append(i)
    return "".join(out), idx


def verify_quote(quote: str, body: str) -> Optional[str]:
    """The exact slice of `body` the quote matches, or None."""
    q, _ = _norm_with_map(str(quote or "").strip())
    q = q.strip().strip('"').strip()
    if len(q) < 3:
        return None
    b, idx = _norm_with_map(str(body or ""))
    at = b.find(q)
    if at < 0:
        return None
    start, end = idx[at], idx[at + len(q) - 1] + 1
    return str(body)[start:end][:MAX_QUOTE_CHARS]


def text_in_body(text: Optional[str], body: str) -> Optional[str]:
    """`text` if it appears in the body (same forgiveness as the quote)."""
    if not text:
        return None
    return verify_quote(text, body)


# ── 5. THE DUE DATE ─────────────────────────────────────────────────────────
#
# due_text is kept as said (and only if it is in the message). due_at is set
# only when this code can read a date from it: today / tonight / EOD,
# tomorrow, a weekday ("by Friday" = the next Friday, today excluded), or
# M/D[/YY] and "Oct 15". Anything else ("next week", "ASAP", "soon") has no
# date. Read in New York time from the moment the message was sent.

_WEEKDAYS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
             "wed": 2, "weds": 2, "wednesday": 2, "thu": 3, "thur": 3,
             "thurs": 3, "thursday": 3, "fri": 4, "friday": 4, "sat": 5,
             "saturday": 5, "sun": 6, "sunday": 6}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
     "nov", "dec"])}


def _local_date(ts: datetime) -> date:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_ET).date() if _ET else ts.date()


def parse_due(due_text: Optional[str], sent_at: datetime) -> Optional[date]:
    if not due_text:
        return None
    t = due_text.lower()
    today = _local_date(sent_at)
    if re.search(r"\bnext week\b|\bnext month\b|\basap\b|\bsoon\b", t):
        return None
    if re.search(r"\b(today|tonight|eod|end of (the )?day|this afternoon|this morning)\b", t):
        return today
    if re.search(r"\b(tomorrow|tmrw|tmr)\b", t):
        return today + timedelta(days=1)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else None
        if yr is not None and yr < 100:
            yr += 2000
        return _resolve_md(today, mo, d, yr)
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m:
        return _resolve_md(today, _MONTHS[m.group(1)], int(m.group(2)), None)
    m = re.search(r"\b(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b", t)
    if m:
        wd = _WEEKDAYS[m.group(1)]
        ahead = (wd - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    return None


def _resolve_md(today: date, mo: int, d: int, yr: Optional[int]) -> Optional[date]:
    try:
        if yr is not None:
            return date(yr, mo, d)
        cand = date(today.year, mo, d)
        # A date more than two months back is next year's ("1/5" said in Dec).
        if cand < today - timedelta(days=60):
            cand = date(today.year + 1, mo, d)
        return cand
    except ValueError:
        return None


# ── 6. IMPORTANCE ───────────────────────────────────────────────────────────

SAFETY_RE = re.compile(
    r"\b(leak\w*|unsafe|crack\w*|collaps\w*|fell|fall|injur\w*|hurt|fire|smoke"
    r"|gas|stop work|swo|violation|inspector|inspection|flood\w*|electrocut\w*"
    r"|scaffold\w*|asbestos)\b", re.IGNORECASE)


def importance(model_label: str, body: str) -> Dict[str, str]:
    """{importance, importance_source}. Safety words make it high; the model
    alone never takes it below what the rules say."""
    label = model_label if model_label in IMPORTANCE else "normal"
    if SAFETY_RE.search(body or ""):
        return {"importance": "high", "importance_source":
                "model" if label == "high" else "rule"}
    return {"importance": label, "importance_source": "model"}


# ── 7. DEDUPE ───────────────────────────────────────────────────────────────

_STOP = set("""a an the and or but if then so to of in on at by for with from
is are was were be been am i im i'm we you he she they it this that these those
my our your his her their me us them do does did done have has had will would
can could should shall may might must not no yes ok okay pls please thanks
just get got go going gonna there here what when where who why how which
""".split())


def subject_terms(quote: str, limit: int = 6) -> List[str]:
    words = re.findall(r"[a-z0-9]+", (quote or "").lower().translate(_TYPO))
    terms = sorted({w for w in words if w not in _STOP and len(w) > 2})
    return terms[:limit]


def dedupe_key(group_id: str, typ: str, owner_key: str, quote: str) -> str:
    raw = "|".join([str(group_id), typ, owner_key or "-",
                    " ".join(subject_terms(quote))])
    return hashlib.sha1(raw.encode()).hexdigest()


# ── 8. THE OWNER RULE ───────────────────────────────────────────────────────
#
# Which identity, if any, the item points at. Resolution to a person happens
# in the server (users of the company, then workers who checked in at the
# project); this only picks the JID to resolve, deterministically.

def owner_candidate(typ: str, msg: Dict[str, Any]) -> Dict[str, str]:
    """{jid, source} or {} when the message names nobody to act."""
    mentions = [str(j) for j in (msg.get("mentioned_jids") or []) if j]
    if typ == "commitment":
        jid = sender_jid(msg)
        return {"jid": jid, "source": "sender"} if jid else {}
    if typ in ("question", "request"):
        if len(mentions) == 1:
            return {"jid": mentions[0], "source": "mention"}
        if len(mentions) > 1:
            return {}
        qa = str(msg.get("quoted_author") or "").strip()
        if qa:
            return {"jid": qa, "source": "reply_author"}
        return {}
    if typ == "issue" and len(mentions) == 1:
        return {"jid": mentions[0], "source": "mention"}
    return {}


def requester_candidate(typ: str, msg: Dict[str, Any]) -> Dict[str, str]:
    if typ in ("question", "request"):
        jid = sender_jid(msg)
        return {"jid": jid, "source": "sender"} if jid else {}
    return {}


# ── 9. NOTHING FROM HERE IS POSTED ──────────────────────────────────────────

def postable(item: Dict[str, Any]) -> bool:
    """v1 is shadow mode: nothing is ever posted, whatever the item says."""
    return False


# ── 10. PRECISION AND THE WEEKLY LINE ───────────────────────────────────────

def precision(items: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per type: correct, wrong, dismissed, unreviewed, and
    precision = correct / (correct + wrong), or None before any verdict.
    Dismissed is "not worth tracking", not "wrong", so it is not counted."""
    out: Dict[str, Dict[str, Any]] = {}
    for it in items:
        typ = it.get("type") or "other"
        row = out.setdefault(
            typ, {"correct": 0, "wrong": 0, "dismissed": 0, "unreviewed": 0})
        verdict = (it.get("review") or {}).get("verdict")
        row[verdict if verdict in VERDICTS else "unreviewed"] += 1
    for row in out.values():
        judged = row["correct"] + row["wrong"]
        row["precision"] = round(row["correct"] / judged, 3) if judged else None
    return out


# gpt-4o-mini list price, USD per million tokens. Used only for the log line.
PRICE_IN_PER_M = 0.15
PRICE_OUT_PER_M = 0.60


def iso_week(ts: datetime) -> str:
    y, w, _ = (ts.astimezone(_ET) if (_ET and ts.tzinfo) else ts).isocalendar()
    return f"{y}-W{w:02d}"


def cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return round(prompt_tokens / 1e6 * PRICE_IN_PER_M
                 + completion_tokens / 1e6 * PRICE_OUT_PER_M, 4)


def weekly_line(row: Dict[str, Any]) -> str:
    """One group's week: items, filter pass %, calls, tokens, cost."""
    msgs = int(row.get("messages") or 0)
    passed = int(row.get("passed") or 0)
    pin = int(row.get("prompt_tokens") or 0)
    pout = int(row.get("completion_tokens") or 0)
    pct = f"{round(100 * passed / msgs)}%" if msgs else "n/a"
    gid = str(row.get("group_id") or "")
    label = gid if gid == "ALL" else "…" + gid.split("@")[0][-6:]
    return (f"week={row.get('week')} group={label} messages={msgs} "
            f"passed={passed} pass_rate={pct} calls={int(row.get('calls') or 0)} "
            f"items={int(row.get('items') or 0)} tokens_in={pin} tokens_out={pout} "
            f"cost_usd={cost_usd(pin, pout):.4f}")


# ── 11. THE PARTICIPANT PROBE (step 0) ──────────────────────────────────────
#
# Does WaAPI's get-group-info list the members, and as phones or privacy ids?
# Answered from the logs with COUNTS ONLY: nothing here returns or logs an id.

def participant_counts(payload: Any) -> Dict[str, int]:
    """{found, total, phone, lid, other, admins} from a get-group-info body.
    found=0 when no participant list was present."""
    plist = _find_participants(payload)
    out = {"found": 1 if plist is not None else 0, "total": 0, "phone": 0,
           "lid": 0, "other": 0, "admins": 0}
    for p in plist or []:
        jid = ""
        if isinstance(p, dict):
            pid = p.get("id")
            if isinstance(pid, dict):
                jid = str(pid.get("_serialized") or "") or (
                    f"{pid.get('user') or ''}@{pid.get('server') or ''}")
            else:
                jid = str(pid or "")
            if p.get("isAdmin") or p.get("isSuperAdmin"):
                out["admins"] += 1
        elif isinstance(p, str):
            jid = p
        out["total"] += 1
        domain = jid.split("@", 1)[1].lower() if "@" in jid else ""
        if domain in ("c.us", "s.whatsapp.net"):
            out["phone"] += 1
        elif domain == "lid":
            out["lid"] += 1
        else:
            out["other"] += 1
    return out


def _find_participants(node: Any, depth: int = 0) -> Optional[list]:
    if depth > 6 or node is None:
        return None
    if isinstance(node, dict):
        v = node.get("participants")
        if isinstance(v, list):
            return v
        for child in node.values():
            got = _find_participants(child, depth + 1)
            if got is not None:
                return got
    elif isinstance(node, list):
        for child in node[:20]:
            got = _find_participants(child, depth + 1)
            if got is not None:
                return got
    return None
