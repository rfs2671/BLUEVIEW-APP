"""GC group alerts — the pure parts (no database, no network).

The GC group is the one WhatsApp group per project that Levelog posts DOB
alerts into: new violations and permit expiry reminders. Everything here is a
plain function so it is tested without a server:

  * which linked group is the GC group (auto-pick, trade words excluded)
  * whether now is inside the posting window (7 AM – 7 PM ET)
  * which permit reminder threshold is due (30 / 14 / 7 / 1 days)
  * reading DOB's dates
  * the violation message: an AI-written plain-language summary is used ONLY
    if every number, date, amount and code in it appears in the DOB record;
    otherwise a fixed template. The violation number and DOB link are always
    appended from the record, never from the model.
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


# ── When to post ────────────────────────────────────────────────────────────

POST_START_HOUR = 7    # 7 AM ET
POST_END_HOUR = 19     # 7 PM ET (exclusive)


def in_post_window(now_utc: datetime) -> bool:
    """True from 7:00 AM to 6:59 PM America/New_York. Outside it nothing is
    posted and nothing is marked, so the next run inside the window posts it.
    Fail closed: no time zone data, no posting."""
    if _ET is None:
        return False
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    h = now_utc.astimezone(_ET).hour
    return POST_START_HOUR <= h < POST_END_HOUR


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


def permit_message(*, project_name: str, permit: Dict[str, Any],
                   expires: date, today: date) -> str:
    what = " ".join(p for p in (str(permit.get("work_type") or "").strip(),
                                "permit") if p)
    num = str(permit.get("job_number") or permit.get("permit_number")
              or permit.get("raw_dob_id") or "").strip()
    when = f"{expires:%b} {expires.day}, {expires.year}"
    days_left = (expires - today).days
    lead = ("expires today" if days_left <= 0
            else "expires tomorrow" if days_left == 1
            else f"expires in {days_left} days")
    lines = [f"Levelog: a {what} on {project_name} {lead} ({when})."]
    if num:
        lines.append(f"Permit: {num}")
    link = str(permit.get("dob_link") or "").strip()
    if link:
        lines.append(f"DOB: {link}")
    return "\n".join(lines)


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
_ALLOWED_WORDS = {"levelog", "dob", "nyc", "ok"}


def _tokens(text: str) -> set:
    return {_norm(t) for t in _TOKEN_RE.findall(text or "") if _norm(t)}


def check_summary(text: str, facts: Dict[str, str]) -> bool:
    """True only if every number, date, amount and code in `text` is a token
    of the DOB record's facts — whole tokens, so an invented "$200" does not
    pass because the record says "$1,200". A date may be re-spelled: its
    year, month and day each count as record tokens."""
    allowed = set()
    for v in facts.values():
        allowed |= _tokens(v)
        d = parse_dob_date(v)
        if d:
            allowed |= {str(d.year), str(d.month), f"{d.month:02d}",
                        str(d.day), f"{d.day:02d}", d.isoformat(),
                        _norm(d.strftime("%m/%d/%Y"))}
    for t in _tokens(text):
        if t in _ALLOWED_WORDS or t in allowed:
            continue
        return False
    return True


def violation_template(*, project_name: str, facts: Dict[str, str]) -> str:
    """The fixed message when the AI summary is missing or fails the check.
    Only record values, copied verbatim."""
    parts = [f"Levelog: a new DOB violation was issued for {project_name}."]
    if facts.get("description"):
        parts.append(f"What it says: {facts['description']}")
    if facts.get("violation_date"):
        d = parse_dob_date(facts["violation_date"])
        parts.append(f"Issued: {d.isoformat() if d else facts['violation_date']}")
    if facts.get("status"):
        parts.append(f"Status: {facts['status']}")
    return "\n".join(parts)


def violation_message(*, summary: str, facts: Dict[str, str],
                      dob_link: str) -> str:
    """The posted text: the (checked) summary, then the violation number and
    DOB link straight from the record. Never a fine the record does not
    carry — the summary is checked, and nothing else adds an amount."""
    lines = [summary.strip()]
    if facts.get("violation_number"):
        lines.append(f"Violation #: {facts['violation_number']}")
    if dob_link:
        lines.append(f"DOB: {dob_link}")
    return "\n".join(lines)


SUMMARY_SYSTEM_PROMPT = (
    "You write one or two short plain-English sentences for a construction "
    "crew's WhatsApp group about a NYC DOB violation. Use ONLY the facts "
    "given. Do not add any number, date, dollar amount, code or law that is "
    "not in the facts. Do not guess a fine. Do not include the violation "
    "number or a link (they are added separately). Start with "
    "'Levelog: a new DOB violation'."
)


# ── Bookkeeping keys (the notification ledger) ──────────────────────────────

def ledger_id(project_id: str, kind: str, item: str) -> str:
    """One ledger row per thing posted to a GC group, ever."""
    return f"gc:{project_id}:{kind}:{item}"


def baseline_id(project_id: str) -> str:
    return f"gc:{project_id}:baseline"
