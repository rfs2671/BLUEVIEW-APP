"""Project reports: the period asked for, the schedule, and the records.

On request ("send me a report for 588 for the last 2 weeks", "monthly report
588", "report all jobs September") and on a schedule (per job: off,
bi-weekly Monday 8 AM, monthly on the 1st at 8 AM). The report itself -- what
it says and how it looks -- is lib/progress_report.py; this module is what
both it and the server share: the period (as said, or as scheduled), DOB/DOT
records new in a period, upcoming events, and whether a DM is a request.

Phone numbers are never shown (any digits that look like one are masked).

Pure: no I/O.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from lib import attendance as att
from lib.datefmt import strftime as _fmt

NY = ZoneInfo("America/New_York")

#: The next-two-weeks window of "Upcoming".
UPCOMING_DAYS = 14
#: A scheduled report's cadences (a per-job setting).
SCHEDULES = ("off", "biweekly", "monthly")
DEFAULT_SCHEDULE = "off"
SEND_HOUR = 8
#: How long the no-login link works.
LINK_DAYS = 30
SOURCE_LINE = "Source: Levelog records"

# Phone-shaped only: a US number (718-555-0100, (718) 555 0100, +1 718 555
# 0100, 7185550100) or an international one written with "+". Never a record
# number: an ECB violation (35123456), a DOB complaint (1234567) or a permit
# number is the report's evidence and must print as filed.
_PHONE = re.compile(r"(?<![\w*])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\w*])"
                    r"|\+\d[\d\s().-]{8,}\d")


def no_phone(text: Any) -> str:
    return _PHONE.sub("[number]", " ".join(str(text or "").split()))


def _d(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return v.astimezone(NY).date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _in(d: Optional[date], start: date, end: date) -> bool:
    return d is not None and start <= d <= end


def _day(d: Optional[date]) -> str:
    return _fmt(d, "%b %-d") if d else ""


def _wday(d: date) -> str:
    return _fmt(d, "%a %b %-d")


def period_label(start: date, end: date) -> str:
    """"Oct 1–14, 2026", "Sep 28 – Oct 11, 2026", "Dec 29, 2025 – Jan 11, 2026"."""
    if start.year != end.year:
        return f"{_fmt(start, '%b %-d, %Y')} – {_fmt(end, '%b %-d, %Y')}"
    if start.month == end.month:
        return f"{_fmt(start, '%b %-d')}–{end.day}, {end.year}" if start != end \
            else _fmt(start, "%b %-d, %Y")
    return f"{_fmt(start, '%b %-d')} – {_fmt(end, '%b %-d')}, {end.year}"


# ── THE PERIOD, AS ASKED ─────────────────────────────────────────────────────

def period_for(text: Any, now: datetime) -> Tuple[date, date, str]:
    """The period a request names: "last 2 weeks", "September", "since Oct
    1", "monthly" (the last full month), "bi-weekly" / nothing (the last 14
    days)."""
    t = str(text or "").lower()
    today = att.local_day(now) or now.date()
    a, b, label = att.parse_range(t, now)
    if a or b:
        return a or (b - timedelta(days=13)), b or today, label
    if re.search(r"\bmonth(?:ly)?\b", t):
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end, _fmt(end, "%B %Y")
    return today - timedelta(days=13), today, "the last 2 weeks"


def scheduled_period(kind: str, now: datetime) -> Optional[Tuple[date, date]]:
    """The period a scheduled report covers when it is due now (New York,
    8 AM hour), else None. Bi-weekly: Mondays of even ISO weeks, the 14 days
    before. Monthly: the 1st, the month before."""
    local = now.astimezone(NY)
    if local.hour != SEND_HOUR:
        return None
    today = local.date()
    if kind == "biweekly" and today.weekday() == 0 and today.isocalendar()[1] % 2 == 0:
        return today - timedelta(days=14), today - timedelta(days=1)
    if kind == "monthly" and today.day == 1:
        end = today - timedelta(days=1)
        return end.replace(day=1), end
    return None


# ── COUNTING ─────────────────────────────────────────────────────────────────

def _record_kind(r: dict) -> str:
    rt = str(r.get("record_type") or "").lower()
    return {"violation": "DOB violation", "complaint": "DOB complaint", "swo": "Stop Work Order",
            "permit": "DOB permit", "dot_violation": "DOT summons", "dot_permit": "DOT permit",
            "job_status": "DOB job status"}.get(rt, rt.replace("_", " ").capitalize() or "Record")


def _records(rows: List[dict], start: date, end: date) -> List[Dict[str, Any]]:
    """New in the period (first seen in it), never a seed of old records."""
    from lib import wa_alerts
    out = []
    for r in rows:
        if r.get("is_seed_transition"):
            continue
        seen = _d(r.get("detected_at") or r.get("created_at"))
        if not _in(seen, start, end):
            continue
        out.append({"kind": _record_kind(r), "number": wa_alerts.record_number(r) or "—",
                    "status": no_phone(wa_alerts.record_status(r) or ("Closed" if wa_alerts.is_closed(r)
                                                                        else "Open")),
                    "date": wa_alerts.record_issue_date(r) or seen,
                    "open": not wa_alerts.is_closed(r)})
    out.sort(key=lambda x: (x["date"] or date.min, x["kind"], x["number"]))
    return out


def _events(rows: List[dict], start: date, end: date) -> List[Dict[str, Any]]:
    out = []
    for e in rows:
        d = _d(e.get("date"))
        if not _in(d, start, end) or e.get("status", "open") != "open":
            continue
        out.append({"date": d, "time": str(e.get("time") or ""), "kind": str(e.get("kind") or ""),
                    "title": no_phone(e.get("title")), "agency": str(e.get("agency") or "")})
    out.sort(key=lambda x: (x["date"], x["time"]))
    return out


_OPEN = ("open", "rescheduled", "possibly_done", "possibly_resolved")


# ── A REQUEST IN THE DM ──────────────────────────────────────────────────────

_REQUEST = re.compile(
    r"\b(?:send|give|get|make|run|pull|generate|email|want|need|can\s+i\s+(?:get|have))\b[^?]{0,40}\breport\b"
    r"|\b(?:monthly|bi-?weekly|weekly|project|job|site)\s+report\b"
    r"|\breport\s+(?:for|on|all|of)\b|^\s*report\b", re.IGNORECASE)
#: Not this report: the daily log's own report, report settings, a punch report.
_OTHER_REPORT = re.compile(r"\b(?:daily|logbook|log)\s+report\b|\breport\s+settings?\b|\bpunch\s+report\b",
                           re.IGNORECASE)
_ALL_JOBS = re.compile(r"\b(?:all|every|each)\s+(?:my\s+|the\s+|of\s+my\s+)?(?:jobs?|projects?|sites?)\b",
                       re.IGNORECASE)


def is_request(text: Any) -> bool:
    """"send me a report for 588 for the last 2 weeks", "monthly report
    588", "report all jobs September"."""
    t = " ".join(str(text or "").split())
    return bool(t) and bool(_REQUEST.search(t)) and not _OTHER_REPORT.search(t)


def wants_all_jobs(text: Any) -> bool:
    return bool(_ALL_JOBS.search(str(text or "")))
