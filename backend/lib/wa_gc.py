"""GC group alerts — the pure parts (no database, no network).

The GC group is the one WhatsApp group per project that Levelog posts DOB
alerts into: new violations and permit expiry reminders. Everything here is a
plain function so it is tested without a server:

  * which linked group is the GC group (auto-pick, trade words excluded)
  * which permit reminder threshold is due (30 / 14 / 7 / 1 days)
  * reading DOB's dates
  * the record checker (check_summary): an AI-written sentence is used ONLY
    if every number, date, amount and code in it appears in the record. The
    messages themselves are built in lib/wa_alerts.py.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

try:  # zoneinfo is stdlib; tzdata may be absent on a slim image
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - fallback keeps the window fail-closed
    _ET = None

# ── GC group auto-pick ──────────────────────────────────────────────────────

# A group whose name carries one of these is a trade's group (the plumbers',
# the electricians'), not the GC's. Matched as whole words, case-insensitive.
TRADE_WORDS = (
    "plumbing", "plumber", "plumbers",
    "electric", "electrical", "electrician", "electricians",
    "hvac", "mechanical", "sprinkler", "sprinklers", "fire alarm",
    "concrete", "steel", "ironwork", "ironworks", "framing", "framers",
    "roofing", "roofer", "roofers", "drywall", "masonry", "mason", "masons",
    "carpentry", "carpenter", "carpenters", "excavation", "demo",
    "demolition", "painting", "painters", "flooring", "tile", "glazing",
    "windows", "elevator", "insulation", "waterproofing", "scaffold",
    "scaffolding", "landscaping", "paving", "fencing",
)
_TRADE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(TRADE_WORDS, key=len, reverse=True))
    + r")\b", re.IGNORECASE)


def has_trade_word(name: Optional[str]) -> bool:
    return bool(_TRADE_RE.search(str(name or "")))


def pick_gc_group(groups: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The project's GC group, or None when it is not obvious.

    `groups` are the project's ACTIVE linked groups ({wa_group_id,
    group_name}). Groups whose name has a trade word are dropped; exactly one
    left is the pick. None left, or more than one, means the admin picks."""
    rest = [g for g in groups
            if g.get("wa_group_id") and not has_trade_word(g.get("group_name"))]
    return rest[0] if len(rest) == 1 else None


# ── Confirm-by-DM replies ───────────────────────────────────────────────────

def parse_confirm_reply(body: Optional[str]) -> Optional[str]:
    """'yes' for "1" / "yes", 'no' for "2" / "no", else None. The whole
    message must be the answer."""
    word = re.sub(r"[^\w]+", "", str(body or "")).lower()
    if word in ("1", "yes", "y"):
        return "yes"
    if word in ("2", "no", "n"):
        return "no"
    return None


# ── When to send (per project, the admin's choice) ──────────────────────────
#
# "anytime" (the default): as soon as something is found. "work_hours": 7 AM
# to 7 PM New York time. "custom": the admin's start and end (HH:MM, New York
# time; an end before the start runs overnight). Outside the window nothing is
# sent and nothing is marked, so the first run inside it sends what waited.

SEND_ANYTIME = "anytime"
SEND_WORK_HOURS = "work_hours"
SEND_CUSTOM = "custom"
SEND_MODES = (SEND_ANYTIME, SEND_WORK_HOURS, SEND_CUSTOM)
WORK_HOURS = ("07:00", "19:00")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def default_send_window() -> Dict[str, Any]:
    return {"mode": SEND_ANYTIME, "start": WORK_HOURS[0], "end": WORK_HOURS[1]}


def clean_send_window(value: Any) -> Optional[Dict[str, Any]]:
    """A valid window dict, or None when `value` is not one."""
    if not isinstance(value, dict):
        return None
    mode = value.get("mode")
    if mode not in SEND_MODES:
        return None
    out = default_send_window()
    out["mode"] = mode
    if mode == SEND_CUSTOM:
        start, end = value.get("start"), value.get("end")
        if not (isinstance(start, str) and _HHMM.match(start)
                and isinstance(end, str) and _HHMM.match(end)) or start == end:
            return None
        out["start"], out["end"] = start, end
    return out


def work_start(window: Any) -> Optional[str]:
    """When this project's work day starts ("HH:MM", New York), from its
    alert timing: the custom start, 07:00 for work hours, None when alerts
    go anytime (no work hours set)."""
    w = clean_send_window(window)
    if not w or w["mode"] == SEND_ANYTIME:
        return None
    return w["start"] if w["mode"] == SEND_CUSTOM else WORK_HOURS[0]


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_send_window(now_utc: datetime, window: Any) -> bool:
    """May an alert go out now under this project's window? Anything that is
    not a valid window means anytime (the default). Fail closed only where a
    window IS set and New York time cannot be told."""
    w = clean_send_window(window) or default_send_window()
    if w["mode"] == SEND_ANYTIME:
        return True
    start, end = (WORK_HOURS if w["mode"] == SEND_WORK_HOURS
                  else (w["start"], w["end"]))
    if _ET is None:
        return False
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    local = now_utc.astimezone(_ET)
    t = local.hour * 60 + local.minute
    a, b = _minutes(start), _minutes(end)
    return a <= t < b if a < b else (t >= a or t < b)


# ── Today, in New York ──────────────────────────────────────────────────────
# Permit reminder thresholds (days left) are counted on the New York calendar.

def today_et(now_utc: datetime) -> date:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(_ET).date() if _ET else now_utc.date()


# ── Dates as DOB stores them ────────────────────────────────────────────────

def parse_dob_date(value: Any) -> Optional[date]:
    """A date from the shapes DOB datasets use: ISO ('2026-11-03',
    '2026-11-03T00:00:00.000'), US ('11/03/2026'), compact ('20261103'), or
    a datetime. None for anything else."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt, cut in (("%Y-%m-%d", 10), ("%m/%d/%Y", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(s[:cut], fmt).date()
        except ValueError:
            continue
    return None


# ── Permit expiry reminders ─────────────────────────────────────────────────

PERMIT_THRESHOLDS = (30, 14, 7, 1)


def permit_threshold_due(expires: Optional[date], today: date) -> Optional[int]:
    """The reminder threshold this permit is inside today, or None.

    The smallest threshold days-left has reached: 30 days out → 30, 9 days
    out → 14 (inside 14, not yet 7), 1 or 0 days out → 1. Expired (days-left
    < 0) or more than 30 days out → None. Each (permit, threshold) posts once
    (the ledger), so a run that misses a day still posts the threshold it
    lands in — and never the larger ones it has passed."""
    if expires is None:
        return None
    days_left = (expires - today).days
    if days_left < 0 or days_left > PERMIT_THRESHOLDS[0]:
        return None
    due = None
    for t in PERMIT_THRESHOLDS:          # 30, 14, 7, 1
        if days_left <= t:
            due = t
    return due


def thresholds_passed(expires: Optional[date], today: date) -> List[int]:
    """Every threshold already reached today — for the no-backfill baseline:
    all of them are recorded as seen on the first run."""
    if expires is None:
        return []
    days_left = (expires - today).days
    return [t for t in PERMIT_THRESHOLDS if days_left <= t]


# ── New violation messages ──────────────────────────────────────────────────

# The record fields the summary may draw on. Nothing else is shown to the
# model, and the checker compares against exactly these values.
VIOLATION_FACT_FIELDS = (
    "violation_number", "violation_type", "violation_category",
    "violation_date", "description", "penalty_amount", "status",
    "respondent", "compliance_deadline", "notice_type",
)


def violation_facts(dob_log: Dict[str, Any]) -> Dict[str, str]:
    return {k: str(dob_log.get(k)).strip() for k in VIOLATION_FACT_FIELDS
            if dob_log.get(k) not in (None, "")}


def _norm(s: str) -> str:
    t = re.sub(r"[\s,$]", "", s).lower().rstrip(".")
    return t[:-3] if t.endswith(".00") else t


# Tokens a summary must not invent: anything with a digit (numbers, dates,
# amounts, codes like "B123" or "BC 3301.2"), and all-caps codes of 2+ letters.
_TOKEN_RE = re.compile(r"\$?\d[\d,./:-]*\d|\$?\d|[A-Za-z]+\d[\w-]*|\b[A-Z]{2,}[A-Z0-9-]*\b")
_ALLOWED_WORDS = {"levelog", "assistant", "dob", "nyc", "ok"}


def _tokens(text: str) -> set:
    return {_norm(t) for t in _TOKEN_RE.findall(text or "") if _norm(t)}


_MONTHS = {m: i + 1 for i, m in enumerate((
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december"))}
_MONTH_ALT = "|".join(sorted({m for m in _MONTHS} | {m[:3] for m in _MONTHS}
                             | {"sept"}, key=len, reverse=True))
_MONTH_RE = re.compile(r"\b(" + _MONTH_ALT + r")\b\.?", re.IGNORECASE)
# "October 1, 2026", "Oct. 1 2026", "October 1st" ...
_MD_Y_RE = re.compile(
    r"\b(" + _MONTH_ALT + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4})\b)?",
    re.IGNORECASE)
# "1 October 2026", "1st of October"
_D_MY_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MONTH_ALT + r")\b\.?(?:,?\s+(\d{4})\b)?",
    re.IGNORECASE)


def _month_no(word: str) -> int:
    w = word.lower().rstrip(".")
    return _MONTHS.get(w) or next(
        (n for m, n in _MONTHS.items() if m.startswith(w[:3])), 0)


def check_summary(text: str, facts: Dict[str, str]) -> bool:
    """True only if every number, date, amount and code in `text` is one the
    DOB record carries.

    Whole tokens: an invented "$200" does not pass because the record says
    "$1,200". Whole DATES: a date in the text, however it is spelled, must be
    one of the record's dates — its year, month and day are never accepted
    one by one, so "October 1, 2026" does not pass against a record date of
    2026-01-10. A month named alone must be the month of a record date."""
    record_dates = set()
    allowed = set()
    for v in facts.values():
        allowed |= _tokens(v)
        d = parse_dob_date(v)
        if d:
            record_dates.add(d)
    record_months = {d.month for d in record_dates}

    def date_ok(month: int, day: int, year: Optional[str]) -> bool:
        return any(d.month == month and d.day == day
                   and (year is None or d.year == int(year))
                   for d in record_dates)

    rest = text or ""
    for rx, m_i, d_i in ((_MD_Y_RE, 1, 2), (_D_MY_RE, 2, 1)):
        for m in rx.finditer(rest):
            if not date_ok(_month_no(m.group(m_i)), int(m.group(d_i)), m.group(3)):
                return False
        rest = rx.sub(" ", rest)
    for m in _MONTH_RE.finditer(rest):
        if m.group(1).lower() == "may":
            continue  # "you may need to" — only a dated "May 3" is a claim
        if _month_no(m.group(1)) not in record_months:
            return False
    for raw in _TOKEN_RE.findall(rest):
        t = _norm(raw)
        if not t or t in _ALLOWED_WORDS or t in allowed:
            continue
        d = parse_dob_date(raw.strip("$")) if re.search(r"[-/]", raw) or len(t) == 8 else None
        if d is not None:
            if d not in record_dates:
                return False
            continue
        return False
    return True


# ── Bookkeeping keys (the notification ledger) ──────────────────────────────

def ledger_id(project_id: str, kind: str, item: str) -> str:
    """One ledger row per thing posted to a GC group, ever."""
    return f"gc:{project_id}:{kind}:{item}"


def baseline_id(project_id: str) -> str:
    return f"gc:{project_id}:baseline"
