"""Upcoming v1 — the pure parts (no database, no network).

What is coming up on a job, from three places, each with its own evidence:

  CITY      ECB/OATH hearing dates (DOB + DOT) and DOB/DOT permit
            expirations, from the records already synced. No confirmation:
            the city's own date is the evidence.
  CHAT      explicit future dated events in a linked project group --
            inspections (DOB, Con Ed, FDNY, DEP, National Grid), deliveries,
            crane picks, pours, utility appointments, hearings. EVIDENCE OR
            SILENCE, as for attention items: every event cites the message it
            came from, by a quote that is an exact piece of it, checked here
            in code. A later message that moves it ("Con Ed moved to Dec 4")
            moves it and keeps the old date in its history; one that calls it
            off ("Con Ed cancelled") closes it. Shown "from chat", one tap to
            dismiss.
  DM        "remind me …" in a DM to the assistant, confirmed once.

THE DATE IS READ HERE, NEVER TAKEN FROM THE MODEL. The model only copies
the date words as written ("Dec 4", "next Tue at 9am", "in 3 weeks"); this
code turns them into a day in New York time, counted from when the message
was sent. Anything it cannot pin to one day is skipped, never guessed:
  vague       "next week", "soon", "end of the month", "TBD"
  ambiguous   "the 5th" (which month?), "Tue 10/7" when 10/7 is a Wednesday,
              two different days in one phrase, a weekday said on that same
              weekday ("Tuesday" / "this Tuesday", sent on a Tuesday), and
              "next <weekday>" said Monday–Thursday (this week's or the one
              after? people split on it). Said Friday–Sunday, "next Tue" is
              the coming Tuesday; a bare or "this" weekday is always the
              coming one.
  past        a day before the message was sent

What lives here, each a plain function tested without a server: the date
resolver, the model request and the parsing of its answer, the per-action
checks (decide), the city rows to events, the brief section, the day-before
DM, the ICS feed, and the DM "remind me" parser.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from lib.wa_attention import verify_quote

try:  # zoneinfo is stdlib; tzdata may be absent on a slim image
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None

PROMPT_VERSION = "upc-v1.0"
MODEL = "gpt-4o-mini"

KINDS = ("inspection", "delivery", "crane_pick", "pour", "utility", "hearing")
CITY_KINDS = ("hearing", "permit_expiration")
SOURCES = ("city", "chat", "dm")
STATUSES = ("open", "cancelled", "dismissed")
ACTIONS = ("new", "reschedule", "cancel")

CONTEXT_MESSAGES = 8
MAX_EVENTS_PER_MESSAGE = 3
MAX_QUOTE_CHARS = 300
BRIEF_MAX = 5
BRIEF_DAYS = 7
UNLINKED_HORIZON_DAYS = 400      # a date further out than this is not "upcoming"


def disabled(env: Dict[str, Any]) -> bool:
    """The kill switch: UPCOMING_DISABLED=1 stops every part of it (the city
    sync, the chat worker, the brief section, the DMs, the feed)."""
    return str((env or {}).get("UPCOMING_DISABLED", "")).strip().lower() in (
        "1", "true", "yes", "on")


# ── 1. THE DATE ──────────────────────────────────────────────────────────────

_WEEKDAYS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
             "wed": 2, "weds": 2, "wednesday": 2, "thu": 3, "thur": 3,
             "thurs": 3, "thursday": 3, "fri": 4, "friday": 4, "sat": 5,
             "saturday": 5, "sun": 6, "sunday": 6}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
            "twelve": 12, "fourteen": 14, "thirty": 30}
_WD = r"(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\.?"
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"

_VAGUE = re.compile(
    r"\b(soon|asap|sometime|some time|later|eventually|tbd|tba|at some point|shortly"
    r"|end of (?:the )?(?:week|month|year)|eow|eom|early|mid|late|beginning of"
    r"|couple (?:of )?(?:days|weeks)|few (?:days|weeks)|next (?:month|year))\b")
_NEXT_WEEK = re.compile(r"\bnext week\b")
_ISO = re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")
_MDY = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_MONTH_DAY = re.compile(_MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MON + r"(?:,?\s+(20\d\d))?")
_BARE_ORDINAL = re.compile(r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b")
_IN_N = re.compile(r"\bin\s+(\d{1,2}|" + "|".join(_NUMBERS) + r")\s+(day|week)s?\b")
_WEEKDAY = re.compile(r"\b(?:(next|this|on|coming)\s+)?" + _WD + r"(?!\w)")
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)(?!\w)|\b(\d{1,2}):(\d{2})\b|\b(noon)\b")


def local_date(ts: datetime) -> date:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_ET).date() if _ET else ts.date()


def _md(today: date, mo: int, d: int, yr: Optional[int]) -> Optional[date]:
    """A month and day; with no year, this year's -- or next year's when this
    year's is more than two months back ("1/5" said in December)."""
    try:
        if yr is not None:
            return date(yr if yr >= 100 else 2000 + yr, mo, d)
        cand = date(today.year, mo, d)
        if cand < today - timedelta(days=60):
            cand = date(today.year + 1, mo, d)
        return cand
    except ValueError:
        return None


def _time_of(t: str) -> Optional[str]:
    """"9am" -> "09:00", "1:30pm" -> "13:30", "7:30" -> "07:30" (a work day:
    1-6 o'clock without am/pm is the afternoon), "noon" -> "12:00"."""
    m = _TIME.search(t)
    if not m:
        return None
    if m.group(6):
        return "12:00"
    if m.group(1):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).replace(".", "")
        if not (1 <= h <= 12) or mi > 59:
            return None
        h = (h % 12) + (12 if ap == "pm" else 0)
        return f"{h:02d}:{mi:02d}"
    h, mi = int(m.group(4)), int(m.group(5))
    if h > 23 or mi > 59:
        return None
    if 1 <= h <= 6:
        h += 12
    return f"{h:02d}:{mi:02d}"


def resolve_when(date_text: Optional[str], sent_at: datetime) -> Dict[str, Any]:
    """{"date": date, "time": "HH:MM"|None} for words that name one day, else
    {"skip": "vague"|"ambiguous"|"past"|"no_date"}. Read in New York time,
    counted from when the message was sent."""
    t = " ".join(str(date_text or "").lower().replace("’", "'").split())
    if not t:
        return {"skip": "no_date"}
    today = local_date(sent_at)
    t_nodate = _TIME.sub(" ", t)
    days: List[date] = []

    for m in _ISO.finditer(t):
        d = _md(today, int(m.group(2)), int(m.group(3)), int(m.group(1)))
        days.append(d) if d else None
    for m in _MDY.finditer(_ISO.sub(" ", t)):
        yr = int(m.group(3)) if m.group(3) else None
        d = _md(today, int(m.group(1)), int(m.group(2)), yr)
        if d is None:
            return {"skip": "ambiguous"}
        days.append(d)
    for rx, mi, di, yi in ((_MONTH_DAY, 1, 2, 3), (_DAY_MONTH, 2, 1, 3)):
        for m in rx.finditer(t):
            d = _md(today, _MONTHS[m.group(mi)[:3]], int(m.group(di)),
                    int(m.group(yi)) if m.group(yi) else None)
            if d is None:
                return {"skip": "ambiguous"}
            days.append(d)
    explicit = bool(days)
    if not explicit and _BARE_ORDINAL.search(t_nodate):
        return {"skip": "ambiguous"}          # "the 5th": of which month?

    rel: List[date] = []
    if re.search(r"\bday after tomorrow\b", t):
        rel.append(today + timedelta(days=2))
    elif re.search(r"\b(tomorrow|tmrw|tmr|tomm?orow)\b", t):
        rel.append(today + timedelta(days=1))
    elif re.search(r"\b(today|tonight|this (?:morning|afternoon|evening))\b", t):
        rel.append(today)
    m = _IN_N.search(t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1)]
        rel.append(today + timedelta(days=n * (7 if m.group(2) == "week" else 1)))

    wd_hits = list(_WEEKDAY.finditer(t))
    wd_day: Optional[date] = None
    if wd_hits:
        if len({_WEEKDAYS[w.group(2)] for w in wd_hits}) > 1:
            return {"skip": "ambiguous"}      # "Tue or Wed"
        w = wd_hits[0]
        wd, lead = _WEEKDAYS[w.group(2)], (w.group(1) or "")
        if explicit:
            if any(d.weekday() != wd for d in days):
                return {"skip": "ambiguous"}  # "Tue 10/7" and 10/7 is a Wednesday
        elif _NEXT_WEEK.search(t):
            # "Tuesday next week": that weekday in the week after this one.
            monday_next = today - timedelta(days=today.weekday()) + timedelta(days=7)
            wd_day = monday_next + timedelta(days=wd)
        else:
            ahead = (wd - today.weekday()) % 7
            if lead == "next":
                # "next Tue" said Mon–Thu: this week's or the one after? People
                # split on it, so it is skipped. Said Fri–Sun the week is over:
                # the coming one ("next Friday" on a Friday: a week out).
                if today.weekday() < 4:
                    return {"skip": "ambiguous"}
                ahead = ahead or 7
            elif ahead == 0:
                # "Tuesday" / "this Tuesday", said on a Tuesday: today, or a
                # week out? Skipped.
                return {"skip": "ambiguous"}
            wd_day = today + timedelta(days=ahead)
    elif _NEXT_WEEK.search(t) and not explicit:
        return {"skip": "vague"}

    cands = set(days) | set(rel) | ({wd_day} if wd_day else set())
    if not cands:
        if _VAGUE.search(t):
            return {"skip": "vague"}
        return {"skip": "no_date"}
    if len(cands) > 1:
        return {"skip": "ambiguous"}
    if _VAGUE.search(t) and not explicit:
        return {"skip": "vague"}              # "early next Tue"? not one day
    day = cands.pop()
    if day < today:
        return {"skip": "past"}
    if day > today + timedelta(days=UNLINKED_HORIZON_DAYS):
        return {"skip": "ambiguous"}
    return {"date": day, "time": _time_of(t)}


# ── 2. THE MODEL REQUEST ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """You read one message from a construction project's WhatsApp group and list the FUTURE, DATED events it states — or changes.

Events (kind):
- inspection: DOB, Con Ed, FDNY, DEP, National Grid, special inspector, elevator, plumbing, electrical inspections
- delivery: a delivery to the site
- crane_pick: a crane pick, hoist or lift
- pour: a concrete pour
- utility: a utility appointment (Con Ed, National Grid, DEP water/sewer, gas, meter set, service cut-in)
- hearing: an ECB / OATH / court hearing

Actions:
- new: the message states an event with a day.
- reschedule: the message moves one of the OPEN EVENTS listed below to another day ("Con Ed moved to Dec 4"). Give its event_id.
- cancel: the message calls off one of the OPEN EVENTS ("Con Ed cancelled", "pour is off"). Give its event_id.

Rules:
- Only the message marked >>>. The context is for understanding only.
- "quote": copied EXACTLY, character for character, from the >>> message. Never paraphrase.
- "date_text": the day words EXACTLY as written in the message, with the time if one is given ("Dec 4", "next Tue at 9am", "tomorrow 7am", "in 3 weeks"). Never compute a date yourself. Never write a date that is not in the message.
- "title": under 8 words, what it is ("Con Ed meter set", "DOB plumbing inspection", "Rebar delivery").
- "agency": DOB, DOT, Con Ed, FDNY, DEP, National Grid, OATH, or null.
- Skip anything with no day or only a vague one ("next week", "soon", "sometime"). Skip what already happened ("poured this morning"). Skip questions that do not state a day ("when is the inspection?").
- A reschedule or cancel must name an event from OPEN EVENTS by its event_id. If none fits, use "new" for a move with a day, and skip a cancel.
- At most 3 events. None is a fine answer.

Return JSON: {"events": [{"action": "new", "event_id": null, "kind": "inspection", "agency": "Con Ed", "title": "...", "date_text": "...", "quote": "..."}]}"""

FILTER_RE = re.compile(
    r"\b(inspect\w*|inspector|delivery|deliveries|deliver\w*|crane|pick|hoist|pour\w*|concrete"
    r"|con ?ed|coned|national grid|fdny|dep|dob|dot|oath|ecb|hearing|meter|gas|utility|utilities"
    r"|appointment|appt|scheduled|moved|move[sd]?|resched\w*|push(?:ed)?|cancel\w*|called off"
    r"|postponed)\b", re.IGNORECASE)
_DAYISH = re.compile(
    r"\b(today|tonight|tomorrow|tmrw|tmr|mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday"
    r"|thursday|friday|saturday|sunday|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|week|weeks"
    r"|days|cancel\w*|called off|off|postponed)\b|\d{1,2}/\d{1,2}|\b20\d\d-\d"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b", re.IGNORECASE)


def worth_a_call(body: Any) -> bool:
    """The cheap filter: an event word AND a day word, or an event word and
    any cancel phrase the checks accept ("Rebar delivery scrapped")."""
    b = str(body or "")
    return bool(FILTER_RE.search(b) and (_DAYISH.search(b) or _CANCEL_WORDS.search(b)))


def _line(m: Dict[str, Any]) -> str:
    who = "…" + str(m.get("sender") or "")[-4:]
    return f"{who}: {str(m.get('body') or '')[:500]}"


def build_messages(msg: Dict[str, Any], context: Iterable[Dict[str, Any]],
                   open_events: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The chat request for one message: a few earlier messages, the
    project's OPEN EVENTS (id, title, day), then the message. Senders by
    their last four digits only."""
    parts = []
    lines = [_line(c) for c in list(context)[-CONTEXT_MESSAGES:]]
    if lines:
        parts.append("Earlier messages:\n" + "\n".join(lines))
    if open_events:
        parts.append("OPEN EVENTS:\n" + "\n".join(
            f"- event_id={e['id']}: {e.get('title') or e.get('kind')} on {e.get('date')}"
            for e in list(open_events)[:30]))
    parts.append(">>> " + _line(msg))
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)}]


def _opt(v: Any, n: int = 120) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v[:n] if v and v.lower() not in ("null", "none", "n/a", "unknown") else None


def parse_events(content: Any) -> List[Dict[str, Any]]:
    """The model's events, shape-checked. Anything malformed is dropped."""
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except Exception:
        return []
    raw = data.get("events") if isinstance(data, dict) else None
    out = []
    for it in raw if isinstance(raw, list) else []:
        if len(out) >= MAX_EVENTS_PER_MESSAGE:
            break
        if not isinstance(it, dict):
            continue
        action = str(it.get("action") or "new").strip().lower()
        kind = str(it.get("kind") or "").strip().lower().replace(" ", "_")
        quote = _opt(it.get("quote"), MAX_QUOTE_CHARS)
        if action not in ACTIONS or not quote:
            continue
        out.append({"action": action, "event_id": _opt(it.get("event_id"), 64),
                    "kind": kind, "agency": _opt(it.get("agency"), 40),
                    "title": _opt(it.get("title"), 80), "date_text": _opt(it.get("date_text")),
                    "quote": quote})
    return out


# ── 3. THE CHECKS ────────────────────────────────────────────────────────────

_CANCEL_WORDS = re.compile(
    r"\b(cancel\w*|called off|call(?:ing)? (?:it )?off|is off|are off|not happening"
    r"|not going to happen|won'?t happen|isn'?t happening|not coming|postponed"
    r"|pushed indefinitely|on hold indefinitely|until further notice|scrap(?:ped)?"
    r"|scratch(?:ed)?|nixed|no longer)\b", re.IGNORECASE)
_AGENCIES = {"dob": "DOB", "dot": "DOT", "con ed": "Con Ed", "coned": "Con Ed",
             "con edison": "Con Ed", "fdny": "FDNY", "dep": "DEP", "national grid": "National Grid",
             "oath": "OATH", "ecb": "OATH"}


def agency_of(v: Optional[str]) -> Optional[str]:
    k = " ".join(str(v or "").lower().split())
    return _AGENCIES.get(k) or (str(v).strip()[:40] if v else None)


def title_of(kind: str, agency: Optional[str], model_title: Optional[str]) -> str:
    if model_title:
        return model_title
    base = {"crane_pick": "Crane pick", "pour": "Concrete pour", "delivery": "Delivery",
            "utility": "Utility appointment", "inspection": "Inspection",
            "hearing": "Hearing"}.get(kind, kind.replace("_", " ").title())
    return f"{agency} {base.lower()}" if agency else base


def event_key(project_id: str, kind: str, agency: Optional[str], day: date) -> str:
    """Two chat events on one job, of one kind, for one agency, on one day
    are one event (several messages, several quotes)."""
    raw = f"{project_id}|{kind}|{(agency or '').lower()}|{day.isoformat()}"
    return "chat:" + hashlib.sha1(raw.encode()).hexdigest()[:16]


# The quote check, a little looser than verify_quote: case, curly quotes,
# dashes, punctuation and spacing are forgiven ("…in 3 weeks." for "…in 3
# weeks", "10 am" for "10am"); a changed or missing WORD still fails. What is
# kept is the slice of the real message, never the model's copy.
_LOOSE_DROP = set(".,!?;:'\"()[]{}*_`~")


def _loose_with_map(text: str):
    out, idx = [], []
    for i, ch in enumerate(str(text or "").translate(_TYPO_MAP)):
        if ch.isspace() or ch in _LOOSE_DROP:
            continue
        out.append(ch.lower())
        idx.append(i)
    return "".join(out), idx


_TYPO_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def match_quote(quote: str, body: str) -> Optional[str]:
    """The slice of `body` the quote is, or None."""
    exact = verify_quote(quote or "", body or "")
    if exact:
        return exact
    q, _ = _loose_with_map(quote)
    if len(q) < 6:
        return None
    b, idx = _loose_with_map(body)
    at = b.find(q)
    if at < 0:
        return None
    return str(body)[idx[at]:idx[at + len(q) - 1] + 1][:MAX_QUOTE_CHARS]


def _words_of(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
            if w not in ("the", "and", "for", "with", "inspection", "event")}


def match_open(quote: str, open_events: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The one open event a move or a cancel without a usable event_id is
    about, by the words it shares with the event's title and kind ("the pour
    is off" -> the pour). None unless exactly one event shares the most."""
    words = _words_of(quote)
    scored = []
    for e in open_events:
        tw = _words_of(f"{e.get('title') or ''} {str(e.get('kind') or '').replace('_', ' ')}")
        tw |= {w[:-1] for w in tw if w.endswith("s")}
        n = len(words & tw) + len({w[:-1] for w in words if w.endswith("s")} & tw)
        if n:
            scored.append((n, e))
    if not scored:
        return None
    best = max(n for n, _ in scored)
    top = [e for n, e in scored if n == best]
    return top[0] if len(top) == 1 else None


def decide(ev: Dict[str, Any], msg: Dict[str, Any], open_events: Sequence[Dict[str, Any]],
           now: Optional[datetime] = None) -> Dict[str, Any]:
    """One model event -> one action, checked in code:
      {"op": "create", "kind", "agency", "title", "date", "time", "quote", "date_text"}
      {"op": "reschedule", "event_id", "date", "time", "quote", "date_text"}
      {"op": "cancel", "event_id", "quote"}
      {"op": "skip", "reason": ...}
    `msg`: {"body", "sent_at"}. The quote must be an exact piece of the body,
    the date words must be inside the quote, and the date is read by
    resolve_when -- never the model's."""
    body = str(msg.get("body") or "")
    quote = match_quote(ev.get("quote") or "", body)
    if not quote:
        return {"op": "skip", "reason": "quote_not_in_message"}
    by_id = {str(e["id"]): e for e in open_events}
    action = ev.get("action")
    if action == "cancel":
        # By its id; else the one open event the words name ("the pour is off").
        target = by_id.get(str(ev.get("event_id") or "")) or match_open(quote, open_events)
        if not target:
            return {"op": "skip", "reason": "cancel_of_unknown_event"}
        if not _CANCEL_WORDS.search(quote):
            return {"op": "skip", "reason": "no_cancel_words"}
        return {"op": "cancel", "event_id": target["id"], "quote": quote}

    date_text = ev.get("date_text")
    if not date_text or not match_quote(date_text, quote):
        return {"op": "skip", "reason": "date_not_in_quote"}
    when = resolve_when(date_text, msg["sent_at"])
    if "skip" in when:
        return {"op": "skip", "reason": when["skip"]}
    if now is not None and when["date"] < local_date(now):
        return {"op": "skip", "reason": "past"}
    if action == "reschedule":
        target = by_id.get(str(ev.get("event_id") or "")) or match_open(quote, open_events)
        if target:
            return {"op": "reschedule", "event_id": target["id"], "date": when["date"],
                    "time": when["time"], "quote": quote, "date_text": date_text}
        # A move of something not on the list: an event in its own right.
    kind = ev.get("kind") or ""
    if kind not in KINDS:
        return {"op": "skip", "reason": "not_an_event_kind"}
    agency = agency_of(ev.get("agency"))
    return {"op": "create", "kind": kind, "agency": agency,
            "title": title_of(kind, agency, ev.get("title")), "date": when["date"],
            "time": when["time"], "quote": quote, "date_text": date_text}


def history_entry(action: str, at: datetime, **kw: Any) -> Dict[str, Any]:
    row = {"action": action, "at": at}
    row.update({k: (v.isoformat() if isinstance(v, date) and not isinstance(v, datetime) else v)
                for k, v in kw.items() if v is not None})
    return row


# ── 4. CITY RECORDS ──────────────────────────────────────────────────────────

def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return local_date(v)
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def city_event(kind: str, agency: str, ref: str, day_value: Any, title: str,
               today: date, detail: str = "") -> Optional[Dict[str, Any]]:
    """A city record's date as an event, or None when it has no readable
    day or the day has passed. `ref` is the record's own id: one record is
    one event, its date updated in place when the city changes it."""
    day = _day(day_value)
    if day is None or day < today:
        return None
    return {"source": "city", "kind": kind, "agency": agency, "key": f"city:{kind}:{ref}",
            "title": title[:120], "date": day.isoformat(), "time": None,
            "detail": detail[:200], "source_ref": ref}


# ── 5. WHAT PEOPLE READ ──────────────────────────────────────────────────────

def day_label(d: Any) -> str:
    """"Thu Dec 4"."""
    dd = _day(d)
    if dd is None:
        return ""
    return f"{dd.strftime('%a')} {dd.strftime('%b')} {dd.day}"


def time_label(t: Optional[str]) -> str:
    if not t:
        return ""
    h, m = (int(x) for x in t.split(":"))
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{':%02d' % m if m else ''}{ap}"


def source_chip(ev: Dict[str, Any]) -> str:
    return {"city": "city record", "chat": "from chat", "dm": "your reminder"}.get(
        ev.get("source") or "", "")


def event_line(ev: Dict[str, Any], with_project: bool = True) -> str:
    """"Thu Dec 4, 9am — Con Ed meter set · 120 Atlantic (from chat)"."""
    when = day_label(ev.get("date"))
    if ev.get("time"):
        when += f", {time_label(ev['time'])}"
    proj = f" · {ev['project_name']}" if with_project and ev.get("project_name") else ""
    chip = source_chip(ev)
    return f"{when} — {ev.get('title') or ''}{proj}" + (f" ({chip})" if chip else "")


def sort_key(ev: Dict[str, Any]):
    return (str(ev.get("date") or ""), str(ev.get("time") or "99:99"), str(ev.get("title") or ""))


def this_week(events: Iterable[Dict[str, Any]], today: date,
              days: int = BRIEF_DAYS, limit: int = BRIEF_MAX) -> List[Dict[str, Any]]:
    """Open events from today through the next `days` days, date-sorted,
    at most `limit`."""
    end = (today + timedelta(days=days)).isoformat()
    t = today.isoformat()
    keep = [e for e in events if e.get("status", "open") == "open"
            and t <= str(e.get("date") or "") <= end]
    return sorted(keep, key=sort_key)[:limit]


def brief_section(events: Iterable[Dict[str, Any]], today: date) -> List[str]:
    """The morning brief's "Upcoming this week" lines (empty: no section)."""
    rows = this_week(events, today)
    return ["Upcoming this week"] + [f"• {event_line(e)}" for e in rows] if rows else []


def day_before_dm(events: Sequence[Dict[str, Any]], tomorrow: date) -> str:
    """One DM for everything tomorrow (the day-before reminder, batched)."""
    rows = sorted([e for e in events if str(e.get("date")) == tomorrow.isoformat()],
                  key=sort_key)
    if not rows:
        return ""
    return "\n".join([f"Tomorrow, {day_label(tomorrow)}:"]
                     + ["• " + _tomorrow_line(e) for e in rows])


def _tomorrow_line(e: Dict[str, Any]) -> str:
    t = f"{time_label(e['time'])} — " if e.get("time") else ""
    proj = f" · {e['project_name']}" if e.get("project_name") else ""
    chip = source_chip(e)
    return f"{t}{e.get('title') or ''}{proj}" + (f" ({chip})" if chip else "")


# ── 6. THE CALENDAR FEED ─────────────────────────────────────────────────────

def _ics_escape(s: str) -> str:
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets are folded."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > 75:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def ics_feed(events: Iterable[Dict[str, Any]], name: str, now: datetime) -> str:
    """A VCALENDAR of open events: an all-day event when there is no time,
    else a one-hour event at that New York time. UIDs are stable, so a moved
    event moves in the subscriber's calendar instead of duplicating."""
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Levelog//Upcoming//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_escape(name)}",
             "X-WR-TIMEZONE:America/New_York"]
    for e in sorted(events, key=sort_key):
        if e.get("status", "open") != "open":
            continue
        d = _day(e.get("date"))
        if d is None:
            continue
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@levelog-upcoming", f"DTSTAMP:{stamp}"]
        if e.get("time"):
            h, m = (int(x) for x in e["time"].split(":"))
            start = datetime(d.year, d.month, d.day, h, m)
            end = start + timedelta(hours=1)
            lines += [f"DTSTART;TZID=America/New_York:{start.strftime('%Y%m%dT%H%M%S')}",
                      f"DTEND;TZID=America/New_York:{end.strftime('%Y%m%dT%H%M%S')}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}"]
        summary = e.get("title") or ""
        if e.get("project_name"):
            summary += f" · {e['project_name']}"
        desc = [source_chip(e)]
        if e.get("quote"):
            desc.append(f"“{e['quote']}”")
        if e.get("detail"):
            desc.append(e["detail"])
        lines += [_fold(f"SUMMARY:{_ics_escape(summary)}"),
                  _fold(f"DESCRIPTION:{_ics_escape(' — '.join(x for x in desc if x))}"),
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ── 7. "REMIND ME …" IN A DM ─────────────────────────────────────────────────

_REMIND = re.compile(r"^\s*(?:pls |please |hey |can you |could you )*remind me\b\s*(.*)$",
                     re.IGNORECASE | re.DOTALL)
_YES = re.compile(r"^\s*(y|yes|yep|yeah|yup|ok|okay|confirm|sure|correct|👍)\s*[.!]*\s*$",
                  re.IGNORECASE)
_NO = re.compile(r"^\s*(n|no|nope|cancel|never ?mind|nvm|stop)\s*[.!]*\s*$", re.IGNORECASE)


def is_remind_request(text: Any) -> bool:
    return bool(_REMIND.match(str(text or "")))


def is_yes(text: Any) -> bool:
    return bool(_YES.match(str(text or "")))


def is_no(text: Any) -> bool:
    return bool(_NO.match(str(text or "")))


_WHEN_WORDS = re.compile(
    r"(?:\b(?:on|by|at|for)\s+)?(?:\b(?:next|this|coming)\s+)?"
    r"(?:" + _WD + r"(?:,?\s+next week)?|" + _MON + r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d\d)?"
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?|20\d\d-\d{1,2}-\d{1,2}|day after tomorrow|tomorrow|tmrw|today"
    r"|tonight|in\s+(?:\d{1,2}|" + "|".join(_NUMBERS) + r")\s+(?:day|week)s?|next week"
    r"|the\s+\d{1,2}(?:st|nd|rd|th))"
    r"(?:\s+(?:at\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|noon|\d{1,2}:\d{2}))?",
    re.IGNORECASE)


def parse_reminder(text: Any, sent_at: datetime) -> Dict[str, Any]:
    """"remind me Dec 4 to call the inspector" -> {"what", "date", "time",
    "date_text"}; or {"skip": reason, "what"} when the day cannot be pinned
    (the reply asks for one)."""
    m = _REMIND.match(str(text or ""))
    rest = (m.group(1) if m else str(text or "")).strip()
    found = [w for w in _WHEN_WORDS.finditer(rest) if w.group(0).strip()]
    date_text = " ".join(w.group(0).strip() for w in found)
    what = rest
    for w in sorted(found, key=lambda x: -x.start()):
        what = what[:w.start()] + what[w.end():]
    what = re.sub(r"^\s*(?:to|that|about)\s+", "", " ".join(what.split()), flags=re.IGNORECASE)
    what = what.strip(" .,;:-") or "Reminder"
    if not date_text:
        return {"skip": "no_date", "what": what}
    when = resolve_when(date_text, sent_at)
    if "skip" in when:
        return {"skip": when["skip"], "what": what, "date_text": date_text}
    return {"what": what[:120], "date": when["date"], "time": when["time"],
            "date_text": date_text}


def confirm_text(r: Dict[str, Any], project_name: str = "") -> str:
    t = f", {time_label(r['time'])}" if r.get("time") else ""
    proj = f" ({project_name})" if project_name else ""
    return (f"Remind you {day_label(r['date'])}{t}: {r['what']}{proj}?\n"
            f"Reply YES to save it, or NO.")


SKIP_REPLY = {
    "no_date": "When? Say the day, e.g. \"remind me Dec 4 to call the inspector\".",
    "vague": "I need one day, e.g. \"remind me Tue Dec 9 at 8am to …\". \"Next week\" or \"soon\" isn't one.",
    "ambiguous": "Which day exactly? Give the month too, e.g. \"Dec 5\".",
    "past": "That day has passed. Give me a day from today on.",
}
