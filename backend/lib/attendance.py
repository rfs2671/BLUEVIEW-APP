"""Who was on site, from the check-ins -- every number counted here.

Questions it answers (the DM assistant's sub_attendance and site_headcount):
  "how many days has arkon been on 588"
      -> "Arkon Builders: 23 days (Sep 14 → today), 241 man-days, avg 10/day."
  "how many guys were on site each day last week"  -> a short per-day list
  "who was on site on Oct 3"                        -> the subs and their counts
  "busiest day this month"                          -> the date and the count

EVIDENCE ONLY. A worker counts once per day (two check-ins the same day are
one); a man-day is one worker on one day; nothing is estimated, rounded up
or filled in. No check-ins in the range: it says so.

Pure: no I/O. The server reads the job's check-ins; these count them.
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from lib.datefmt import strftime as _fmt
from lib.wa_facts import checkin_company, match_companies, _core, _fold

NY = ZoneInfo("America/New_York")

#: More lines than this in chat: the first ones, and the offer of a report.
CHAT_LINES = 8
FULL_REPORT_OFFER = "Want the full report? Say \"report for {job}\"."


def local_day(at: Any) -> Optional[date]:
    if not isinstance(at, datetime):
        return None
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return at.astimezone(NY).date()


def worker_key(row: Dict[str, Any]) -> str:
    return str(row.get("worker_id") or row.get("worker_phone") or row.get("worker_name")
               or row.get("_id"))


# ── THE RANGE, AS SAID ───────────────────────────────────────────────────────

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9
_MON = r"(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = re.compile(r"\b(?P<m>" + _MON + r")\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s*(?P<y>\d{4}))?"
                  r"|\b(?P<m2>\d{1,2})/(?P<d2>\d{1,2})(?:/(?P<y2>\d{2,4}))?\b", re.IGNORECASE)
_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "a": 1, "an": 1}


def _a_day(m: "re.Match", today: date) -> Optional[date]:
    try:
        if m.group("m"):
            mon = _MONTHS[m.group("m").lower().rstrip(".")]
            y = int(m.group("y")) if m.group("y") else today.year
            d = date(y, mon, int(m.group("d")))
        else:
            y = m.group("y2")
            y = (2000 + int(y) if y and len(y) == 2 else int(y)) if y else today.year
            d = date(y, int(m.group("m2")), int(m.group("d2")))
    except (ValueError, KeyError):
        return None
    if not (m.group("y") if m.group("m") else m.group("y2")) and d > today:
        d = d.replace(year=d.year - 1)               # "Dec 3" said in October: last year's
    return d


def parse_range(text: Any, now: datetime) -> Tuple[Optional[date], Optional[date], str]:
    """(first day, last day, how it reads) from the words: "last week",
    "this week", "this month", "last month", "September", "since Oct 1",
    "from Oct 1 to Oct 9", "on Oct 3", "yesterday", "today", "last 2 weeks",
    "past 10 days". Nothing said: (None, None, "") -- the whole job."""
    t = " ".join(str(text or "").lower().split())
    today = local_day(now) or now.date()
    if not t:
        return None, None, ""
    days = [d for d in (_a_day(m, today) for m in _DAY.finditer(t)) if d]
    if re.search(r"\b(?:from|between)\b", t) and len(days) >= 2:
        a, b = sorted(days[:2])
        return a, b, f"{_label(a, today)} → {_label(b, today)}"
    if re.search(r"\b(?:since|after|starting)\b", t) and days:
        return days[0], today, f"since {_label(days[0], today)}"
    if re.search(r"\b(?:until|through|before|thru)\b", t) and days:
        return None, days[0], f"through {_label(days[0], today)}"
    if days:
        return days[0], days[0], _label(days[0], today)
    if re.search(r"\btoday\b", t):
        return today, today, "today"
    if re.search(r"\byesterday\b", t):
        y = today - timedelta(days=1)
        return y, y, "yesterday"
    m = re.search(r"\b(?:last|past|previous)\s+(\d{1,3}|" + "|".join(_NUM) + r")\s+(day|week|month)s?\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM[m.group(1)]
        span = {"day": n, "week": 7 * n, "month": 30 * n}[m.group(2)]
        return today - timedelta(days=span - 1), today, f"the last {n} {m.group(2)}{'s' if n != 1 else ''}"
    monday = today - timedelta(days=today.weekday())
    if re.search(r"\bthis\s+week\b", t):
        return monday, today, "this week"
    if re.search(r"\blast\s+week\b", t):
        a = monday - timedelta(days=7)
        return a, a + timedelta(days=6), "last week"
    if re.search(r"\bthis\s+month\b", t):
        return today.replace(day=1), today, "this month"
    if re.search(r"\blast\s+month\b", t):
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end, "last month"
    m = (re.search(r"\b(?:in|during|for|of)\s+(" + _MON + r")\b(?!\s+\d)", t)
         or re.search(r"\b(" + "|".join(n.lower() for n in calendar.month_name if n and n != "May")
                      + r")\b(?!\s+\d)", t))
    if m:
        mon = _MONTHS[m.group(1).rstrip(".")]
        y = today.year if mon <= today.month else today.year - 1
        a = date(y, mon, 1)
        b = date(y, mon, calendar.monthrange(y, mon)[1])
        return a, min(b, today), calendar.month_name[mon]
    return None, None, ""


def _label(d: date, today: date) -> str:
    if d == today:
        return "today"
    if d == today - timedelta(days=1):
        return "yesterday"
    return _fmt(d, "%b %-d") + ("" if d.year == today.year else f", {d.year}")


def _weekday(d: date, today: date) -> str:
    return _fmt(d, "%a %b %-d") if d.year == today.year else _fmt(d, "%a %b %-d, %Y")


# ── COUNTING ─────────────────────────────────────────────────────────────────

def by_day(rows: Iterable[Dict[str, Any]], date_from: Optional[date] = None,
           date_to: Optional[date] = None) -> Dict[date, Dict[str, set]]:
    """{day: {company: {worker, ...}}} -- each worker once per day."""
    out: Dict[date, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in rows:
        d = local_day(r.get("check_in_time"))
        if d is None or (date_from and d < date_from) or (date_to and d > date_to):
            continue
        out[d][checkin_company(r) or "No company"].add(worker_key(r))
    return out


def pick_sub(rows: List[Dict[str, Any]], sub: str) -> Dict[str, Any]:
    """The company a sub as said means: {"companies": [...]} or
    {"ambiguous": [...]} or {"companies": []} (no such company)."""
    matched = match_companies({checkin_company(r) for r in rows}, sub)
    if len(matched) > 1 and len({_core(m) for m in matched}) > 1:
        return {"ambiguous": matched, "companies": []}
    return {"companies": matched}


def summary(rows: Iterable[Dict[str, Any]], now: datetime, sub: Optional[str] = None,
            date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict[str, Any]:
    """A sub's (or the whole job's) days on site: {"companies", "ambiguous",
    "days": [dates], "per_day": {date: workers}, "first", "last",
    "man_days", "avg", "max", "max_day", "today"}."""
    rows = list(rows)
    out: Dict[str, Any] = {"companies": [], "ambiguous": [], "days": [], "per_day": {}}
    if sub:
        got = pick_sub(rows, sub)
        if got.get("ambiguous"):
            return {**out, "ambiguous": got["ambiguous"]}
        if not got["companies"]:
            return {**out, "no_such": True}
        keep = {_fold(c) for c in got["companies"]}
        rows = [r for r in rows if _fold(checkin_company(r)) in keep]
        out["companies"] = got["companies"]
    days = by_day(rows, date_from, date_to)
    per = {d: sum(len(w) for w in days[d].values()) for d in sorted(days)}
    if not per:
        return out
    top = max(per.values())
    today = local_day(now)
    out.update(days=list(per), per_day=per, first=min(per), last=max(per),
               man_days=sum(per.values()), avg=round(sum(per.values()) / len(per), 1), max=top,
               max_day=min(d for d, n in per.items() if n == top), today=per.get(today, 0))
    return out


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def sub_text(s: Dict[str, Any], now: datetime, sub: Optional[str], job: str = "",
             range_label: str = "") -> str:
    """"Arkon Builders: 23 days (Sep 14 → today), 241 man-days, avg 10/day."
    -- with the busiest day when it stands out, and today's count."""
    today = local_day(now)
    at = f" at {job}" if job else ""
    when = f" {range_label}" if range_label else ""
    if s.get("ambiguous"):
        return f"More than one company matches {sub!r}: " + ", ".join(s["ambiguous"]) + ". Which one?"
    if s.get("no_such"):
        return f"No check-ins{at} from a company called {sub!r}."
    who = ", ".join(s.get("companies") or []) or "Everyone"
    if not s.get("days"):
        return f"No check-ins{at} for {who if sub else 'anyone'}{when}."
    n = len(s["days"])
    span = (_label(s["first"], today) if s["first"] == s["last"]
            else f"{_label(s['first'], today)} → {_label(s['last'], today)}")
    line = (f"{who}: {n} day{'s' if n != 1 else ''}{when} ({span}), "
            f"{s['man_days']} man-day{'s' if s['man_days'] != 1 else ''}, avg {_num(s['avg'])}/day")
    if n > 1 and s["max"] > s["avg"]:
        line += f", most {s['max']} on {_label(s['max_day'], today)}"
    if s["last"] == today:
        line += f"; {s['today']} today"
    return line + "."


def _subs_line(day: Dict[str, set]) -> str:
    parts = sorted(((c, len(w)) for c, w in day.items()), key=lambda cw: (-cw[1], cw[0]))
    return ", ".join(f"{c} {n}" for c, n in parts)


def per_day_text(rows: Iterable[Dict[str, Any]], now: datetime, date_from: Optional[date],
                 date_to: Optional[date], job: str = "", range_label: str = "",
                 limit: int = CHAT_LINES) -> str:
    """"Last week at 588 — 5 days, 98 man-days:" then one line a day, newest
    first: "• Fri Oct 9: 21 (Arkon Builders 12, Power Direct 9)". Longer than
    `limit`: the first lines and the offer of the full report."""
    today = local_day(now)
    days = by_day(rows, date_from, date_to)
    at = f" at {job}" if job else ""
    head = (range_label[:1].upper() + range_label[1:]) if range_label else "On site"
    if not days:
        return f"No check-ins{at}{(' ' + range_label) if range_label else ''}."
    total = sum(len(w) for d in days.values() for w in d.values())
    lines = [f"{head}{at} — {len(days)} day{'s' if len(days) != 1 else ''}, "
             f"{total} man-day{'s' if total != 1 else ''}:"]
    order = sorted(days, reverse=True)
    for d in order[:limit]:
        n = sum(len(w) for w in days[d].values())
        lines.append(f"• {_weekday(d, today)}: {n} ({_subs_line(days[d])})")
    if len(order) > limit:
        lines.append(f"…and {len(order) - limit} more day{'s' if len(order) - limit != 1 else ''}. "
                     + FULL_REPORT_OFFER.format(job=job or "this job"))
    return "\n".join(lines)


def one_day_text(rows: Iterable[Dict[str, Any]], now: datetime, day: date, job: str = "") -> str:
    """"Thu Oct 3 at 588: 18 on site — Arkon Builders 10, Power Direct 8.\""""
    today = local_day(now)
    days = by_day(rows, day, day)
    at = f" at {job}" if job else ""
    if not days:
        return f"No check-ins{at} on {_weekday(day, today)}."
    n = sum(len(w) for w in days[day].values())
    return f"{_weekday(day, today)}{at}: {n} on site — {_subs_line(days[day])}."


def busiest_text(rows: Iterable[Dict[str, Any]], now: datetime, date_from: Optional[date],
                 date_to: Optional[date], job: str = "", range_label: str = "") -> str:
    """"Busiest day this month at 588: Thu Oct 2 — 24 on site (Arkon
    Builders 14, Power Direct 10).\""""
    today = local_day(now)
    days = by_day(rows, date_from, date_to)
    at = f" at {job}" if job else ""
    when = f" {range_label}" if range_label else ""
    if not days:
        return f"No check-ins{at}{when}."
    totals = {d: sum(len(w) for w in v.values()) for d, v in days.items()}
    top = max(totals.values())
    best = sorted(d for d, n in totals.items() if n == top)
    tie = f" (tied with {', '.join(_weekday(d, today) for d in best[1:])})" if len(best) > 1 else ""
    return (f"Busiest day{when}{at}: {_weekday(best[0], today)} — {top} on site "
            f"({_subs_line(days[best[0]])}){tie}.")


# ── THE TOOLS ────────────────────────────────────────────────────────────────

_RANGE_ARG = {"type": "string", "description": (
    "The period exactly as the user said it (\"last week\", \"since Oct 1\", \"this month\", "
    "\"on Oct 3\", \"September\"); omit for the whole job.")}

SUB_ATTENDANCE_TOOL = {"type": "function", "function": {
    "name": "sub_attendance",
    "description": (
        "Days a subcontractor (or the whole job) has been ON SITE, from the check-ins: distinct "
        "days, the first and last day, man-days, average and most workers per day, today's "
        "count. USE THIS for 'how many days has Arkon been on 588', 'when did the plumber "
        "start', 'how many guys does X usually send'. The sub's name as the user said it (short "
        "or misspelled names are matched). Every number comes from the check-ins: never answer "
        "that the data does not say."),
    "parameters": {"type": "object", "properties": {
        "sub": {"type": "string", "description": "The company as the user said it; omit for the whole job."},
        "range": _RANGE_ARG,
        "date_from": {"type": "string", "description": "Optional first day, YYYY-MM-DD."},
        "date_to": {"type": "string", "description": "Optional last day, YYYY-MM-DD."}},
        "additionalProperties": False}}}

SITE_HEADCOUNT_TOOL = {"type": "function", "function": {
    "name": "site_headcount",
    "description": (
        "Workers on site per day, by sub, from the check-ins. view=\"per_day\" for 'how many guys "
        "were on site each day last week'; view=\"day\" for 'who was on site on Oct 3'; "
        "view=\"busiest\" for 'busiest day this month'. Every number comes from the check-ins."),
    "parameters": {"type": "object", "properties": {
        "view": {"type": "string", "enum": ["per_day", "day", "busiest"]},
        "range": _RANGE_ARG,
        "date_from": {"type": "string", "description": "Optional first day, YYYY-MM-DD."},
        "date_to": {"type": "string", "description": "Optional last day, YYYY-MM-DD."}},
        "required": ["view"], "additionalProperties": False}}}


def _iso(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v).strip()[:10]) if v else None
    except ValueError:
        return None


def resolve_range(args: Dict[str, Any], question: str, now: datetime
                  ) -> Tuple[Optional[date], Optional[date], str]:
    """The period: the words as said (the tool's "range", else the question
    itself) win over model-computed dates -- dates the model works out are
    used only when the words name no period."""
    for words in (args.get("range"), question):
        a, b, label = parse_range(words, now)
        if a or b:
            return a, b, label
    a, b = _iso(args.get("date_from")), _iso(args.get("date_to"))
    today = local_day(now)
    if a and b and a == b:
        return a, b, _label(a, today)
    if a or b:
        return a, b, " → ".join(_label(d, today) for d in (a or b, b or today))
    return None, None, ""


def answer(tool: str, args: Dict[str, Any], rows: List[Dict[str, Any]], now: datetime,
           job: str = "", question: str = "") -> str:
    """The tool's answer, from the rows (the job's check-ins)."""
    a, b, label = resolve_range(args or {}, question, now)
    if tool == "sub_attendance":
        sub = str((args or {}).get("sub") or "").strip() or None
        return sub_text(summary(rows, now, sub, a, b), now, sub, job, label)
    view = (args or {}).get("view") or "per_day"
    if view == "day" or (a and a == b and view != "busiest"):
        return one_day_text(rows, now, a or local_day(now), job)
    if view == "busiest":
        return busiest_text(rows, now, a, b, job, label)
    return per_day_text(rows, now, a, b, job, label)


# ── WHICH QUESTION ───────────────────────────────────────────────────────────

_ATTEND = re.compile(
    r"\bhow\s+(?:many|long)\s+(?:days?|weeks?)\b|\bdays?\s+on\s+(?:site|the\s+job)\b|\bman[-\s]?days?\b|"
    r"\bbeen\s+(?:on|at)\b|\bwhen\s+did\b.*\b(?:start|first)\b|\b(?:usually|on\s+average)\s+send\b",
    re.IGNORECASE)
_HEADCOUNT = re.compile(
    r"\bhow\s+many\s+(?:guys|men|workers|people|crew)\b|\b(?:who|anyone)\s+(?:was|were)\s+(?:on\s+site|here|there)\b|"
    r"\bbusiest\s+day\b|\beach\s+day\b|\bper\s+day\b|\bheadcount\b|\bmanpower\b", re.IGNORECASE)


def kind_of(question: Any) -> Optional[str]:
    """"sub_attendance", "busiest", "day", "per_day" or None."""
    t = str(question or "")
    if re.search(r"\bbusiest\s+day\b", t, re.I):
        return "busiest"
    if _ATTEND.search(t):
        return "sub_attendance"
    if _HEADCOUNT.search(t):
        if re.search(r"\b(?:who|anyone)\s+(?:was|were)\b", t, re.I) or re.search(r"\bon\s+" + _MON, t, re.I):
            return "day"
        return "per_day"
    return None


def is_history(question: Any, now: Optional[datetime] = None) -> bool:
    """About days other than today ("each day last week", "on Oct 3",
    "busiest day", "how many days has Arkon been"): the attendance tools,
    never today's headcount."""
    t = str(question or "")
    k = kind_of(t)
    if k in ("sub_attendance", "busiest"):
        return True
    if re.search(r"\b(?:each|every|per)\s+day\b|\bdaily\b", t, re.I):
        return True
    now = now or datetime.now(timezone.utc)
    a, b, _ = parse_range(t, now)
    today = local_day(now)
    return bool((a or b) and not (a == b == today))
