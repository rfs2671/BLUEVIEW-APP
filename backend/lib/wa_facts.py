"""Answers the assistant used to say it could not give (Wed Oct 14, 588).

Live, 10:11-10:13 AM DM:
  * "How many days has Arkon been on 588?" -> "the data doesn't specify",
    though every check-in carries the worker's company.
  * "Why didn't I get morning brief" -> "Which job?", then "The morning brief
    for 588 was sent earlier today" -- invented.

The audit (every "I can't / the data doesn't" against what is stored) found
these with data and no tool:
  check-ins over time   -> sub_attendance (days on site, first / last, crew)
  punch items           -> punch_status (open / ready to check, by assignee)
  open follow-ups       -> follow_ups (who owes what, due, late, last chased)
  upcoming              -> upcoming_events (inspections, hearings, deliveries)
  the morning brief     -> brief_status (sent at / skipped why / failed)
Already covered: today's site (who_on_site), roster (list_workers), a day's
log (daily_log), DOB (dob_status, active_permits), materials, plans, the
group's history (search_project_history), subs (find_sub / list_subs).

Pure: no I/O. The server reads the rows; these turn them into the answer.
Every number comes from the rows given -- with none, the answer says so.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from lib.datefmt import strftime as _fmt

NY = ZoneInfo("America/New_York")


def local_day(at: Any) -> Optional[date]:
    """The New York day of a stored time."""
    if not isinstance(at, datetime):
        return None
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return at.astimezone(NY).date()


def day_label(d: date, today: date) -> str:
    """"today", "yesterday", "Sep 14" (with the year when not this one)."""
    if d == today:
        return "today"
    if d == today - timedelta(days=1):
        return "yesterday"
    return _fmt(d, "%b %-d") + ("" if d.year == today.year else f", {d.year}")


def _fold(s: Any) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower()).strip()


_TAIL = {"inc", "llc", "corp", "corporation", "co", "company", "ltd", "group", "builders",
         "construction", "contracting", "contractors", "contractor", "services", "the"}


def _core(s: Any) -> str:
    words = [w for w in _fold(s).split() if w not in _TAIL]
    return " ".join(words) or _fold(s)


def match_companies(names: Iterable[str], query: str) -> List[str]:
    """The company names a sub as said means ("arkon" -> "Arkon Builders"):
    exact, then the name without its Inc/LLC/Builders, then a word start,
    then close spellings. Several equally good: all of them (the caller
    asks which)."""
    names = sorted({str(n).strip() for n in names if str(n or "").strip()})
    q, qc = _fold(query), _core(query)
    if not q:
        return []
    for test in (lambda n: _fold(n) == q,
                 lambda n: _core(n) == qc,
                 lambda n: any(w.startswith(qc) for w in _core(n).split()) and len(qc) >= 3,
                 lambda n: qc in _core(n) and len(qc) >= 3):
        hit = [n for n in names if test(n)]
        if hit:
            return hit
    close = [n for n in names
             if difflib.SequenceMatcher(None, qc, _core(n)).ratio() >= 0.8
             or any(difflib.SequenceMatcher(None, qc, w).ratio() >= 0.85 for w in _core(n).split())]
    return close


# ── CHECK-INS OVER TIME ──────────────────────────────────────────────────────

def checkin_company(row: Dict[str, Any]) -> str:
    for k in ("worker_company", "company", "company_name"):
        if row.get(k):
            return str(row[k]).strip()
    return ""


def _who(row: Dict[str, Any]) -> str:
    return str(row.get("worker_id") or row.get("worker_phone") or row.get("worker_name") or row.get("_id"))


def attendance(rows: Iterable[Dict[str, Any]], now: datetime, sub: Optional[str] = None,
               date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict[str, Any]:
    """Days on site from check-ins: {"companies": [matched names], "days",
    "first", "last", "avg", "max", "max_day", "today", "ambiguous": [...]}.
    `sub`: a company as said; none -- the whole job."""
    rows = list(rows)
    today = local_day(now)
    matched: Optional[List[str]] = None
    if sub:
        matched = match_companies({checkin_company(r) for r in rows}, sub)
        if len(matched) > 1 and len({_core(m) for m in matched}) > 1:
            return {"companies": [], "ambiguous": matched}
        if not matched:
            return {"companies": [], "ambiguous": [], "days": 0}
        keep = {_fold(m) for m in matched}
        rows = [r for r in rows if _fold(checkin_company(r)) in keep]
    per_day: Dict[date, set] = defaultdict(set)
    for r in rows:
        d = local_day(r.get("check_in_time"))
        if d is None or (date_from and d < date_from) or (date_to and d > date_to):
            continue
        per_day[d].add(_who(r))
    if not per_day:
        return {"companies": matched or [], "ambiguous": [], "days": 0}
    days = sorted(per_day)
    counts = [len(per_day[d]) for d in days]
    top = max(counts)
    return {"companies": matched or [], "ambiguous": [], "days": len(days), "first": days[0],
            "last": days[-1], "avg": round(sum(counts) / len(counts), 1), "max": top,
            "max_day": next(d for d in days if len(per_day[d]) == top),
            "today": len(per_day.get(today, set()))}


def attendance_text(a: Dict[str, Any], now: datetime, sub: Optional[str], job: str = "") -> str:
    """"Arkon Builders: 23 days on site (first Sep 14, last today), avg 10/day,
    most 14 on Oct 2; 9 today." -- or what the check-ins do not show."""
    today = local_day(now)
    if a.get("ambiguous"):
        return (f"More than one company matches {sub!r}: " + ", ".join(a["ambiguous"])
                + ". Which one?")
    who = ", ".join(a.get("companies") or []) or (sub or "This job")
    at = f" at {job}" if job else ""
    if not a.get("days"):
        if sub and not a.get("companies"):
            return f"No check-ins{at} from a company called {sub!r}."
        return f"No check-ins{at} for {who} in that time."
    avg = a["avg"]
    avg_s = str(int(avg)) if float(avg).is_integer() else str(avg)
    line = (f"{who}: {a['days']} day{'s' if a['days'] != 1 else ''} on site{at} "
            f"(first {day_label(a['first'], today)}, last {day_label(a['last'], today)}), "
            f"avg {avg_s}/day")
    if a["max"] > avg:
        line += f", most {a['max']} on {day_label(a['max_day'], today)}"
    line += f"; {a['today']} today." if a["last"] == today else "; none today."
    return line


SUB_ATTENDANCE_TOOL = {"type": "function", "function": {
    "name": "sub_attendance",
    "description": (
        "Days a subcontractor (or the whole job) has been ON SITE, from the check-ins: how "
        "many distinct days, the first and last day, the average and the most workers per "
        "day, and today's count. USE THIS for 'how many days has Arkon been on site', 'when "
        "did the plumber start', 'how many guys does X usually send', 'how many workers "
        "were here last week'. The sub's name as the user said it (a short or misspelled "
        "name is matched). Never answer that the data does not say: the check-ins do."),
    "parameters": {"type": "object", "properties": {
        "sub": {"type": "string", "description": "The company as the user said it; omit for the whole job."},
        "date_from": {"type": "string", "description": "Optional first day, YYYY-MM-DD."},
        "date_to": {"type": "string", "description": "Optional last day, YYYY-MM-DD."}},
        "additionalProperties": False}}}


# ── PUNCH ────────────────────────────────────────────────────────────────────

def punch_text(rows: Iterable[Dict[str, Any]], now: datetime, assignee: Optional[str] = None,
               job: str = "") -> str:
    """Open and ready-to-check punch items, by assignee, with the oldest;
    then how the last list went out (shadow mode: nothing was sent)."""
    today = local_day(now)
    rows = [r for r in rows if r.get("status") in ("open", "ready_to_check", "closed")]
    last = last_list_line(rows, now)
    if assignee:
        a = _fold(assignee)
        rows = [r for r in rows if a and (a in _fold((r.get("assignee") or {}).get("name"))
                                          or a in _fold((r.get("assignee") or {}).get("company")))]
    at = f" at {job}" if job else ""
    if not rows:
        return f"No punch items{at}" + (f" for {assignee}." if assignee else ".") + \
            (f"\n{last}" if last else "")
    open_ = [r for r in rows if r.get("status") == "open"]
    ready = [r for r in rows if r.get("status") == "ready_to_check"]
    closed = [r for r in rows if r.get("status") == "closed"]
    lines = [f"Punch{at}: {len(open_)} open, {len(ready)} ready to check, {len(closed)} closed."]
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in open_:
        by[((r.get("assignee") or {}).get("name") or "Unassigned").strip()].append(r)
    for who, rs in sorted(by.items(), key=lambda kv: -len(kv[1]))[:8]:
        old = min((local_day(r.get("assigned_at") or r.get("created_at")) or today) for r in rs)
        lines.append(f"• {who}: {len(rs)} open (oldest {day_label(old, today)})")
    if ready:
        lines.append("Ready to check: " + ", ".join(str(r.get("pid") or "?") for r in ready[:10])
                     + (" …" if len(ready) > 10 else ""))
    if last:
        lines.append(last)
    return "\n".join(lines)


def last_list_line(rows: Iterable[Dict[str, Any]], now: datetime) -> str:
    """How the latest walk's list went out (Thu 9:03 AM: "Was it sent to
    the GC team group chat?"): "Last list: 47 items, today 9:01 AM — shadow
    mode, nothing was actually sent (it would have been posted in the job's
    group chat)." "" when no row says how it was sent."""
    sent = [r for r in rows if r.get("walk_id") and r.get("sent_via")]
    if not sent:
        return ""
    def at(r):
        v = r.get("created_at")
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)) if isinstance(v, datetime) else None
    newest = max(sent, key=lambda r: at(r) or datetime.min.replace(tzinfo=timezone.utc))
    walk = [r for r in sent if r.get("walk_id") == newest.get("walk_id")]
    when = at(newest)
    stamp = (f"{day_label(when.astimezone(NY).date(), local_day(now))} "
             f"{_fmt(when.astimezone(NY), '%-I:%M %p')}") if when else ""
    via = {r.get("sent_via") for r in walk}
    people = sorted({str((r.get("assignee") or {}).get("name") or "").strip() for r in walk
                     if r.get("sent_via") == "dm"} - {""})
    where = []
    if via & {"group", "group_list"}:
        where.append("posted in the job's group chat")
    if "dm" in via:
        where.append("DM'd to " + (", ".join(people) if people else "one person"))
    where_s = " and ".join(where) or "sent"
    n = len(walk)
    head = f"Last list: {n} item{'s' if n != 1 else ''}" + (f", {stamp}" if stamp else "")
    if any(r.get("send_mode") == "live" for r in walk):
        return f"{head} — {where_s}."
    return (f"{head} — shadow mode: nothing was actually sent "
            f"(it would have been {where_s}).")


PUNCH_STATUS_TOOL = {"type": "function", "function": {
    "name": "punch_status",
    "description": (
        "The job's punch list: how many items are open, ready to check (the sub says done) "
        "and closed, who has how many open and since when. Optionally for one assignee "
        "(a person or their company). Also how the last list went out: posted in the "
        "group chat or DM'd, and whether sends were in shadow mode (nothing sent). USE THIS "
        "for any punch-list question, \"was it sent?\" included."),
    "parameters": {"type": "object", "properties": {
        "assignee": {"type": "string", "description": "Optional: a person or company as said."}},
        "additionalProperties": False}}}


# ── FOLLOW-UPS AND THE CHASE ─────────────────────────────────────────────────

def follow_ups_text(items: Iterable[Dict[str, Any]], chased: Dict[str, datetime], now: datetime,
                    owner: Optional[str] = None, job: str = "") -> str:
    """Open requests and commitments: who owes what, due, late, when last
    chased."""
    today = local_day(now)
    items = list(items)
    if owner:
        o = _fold(owner)
        items = [i for i in items if o and (o in _fold((i.get("owner") or {}).get("name"))
                                            or o in _fold((i.get("owner") or {}).get("sub_company")))]
    at = f" at {job}" if job else ""
    if not items:
        return f"Nothing open{at}" + (f" for {owner}." if owner else ".")

    def due_of(i):
        v = (i.get("due") or {}).get("due_at")
        try:
            return date.fromisoformat(str(v)[:10]) if v else None
        except ValueError:
            return None
    items.sort(key=lambda i: (due_of(i) or date.max, str(i.get("summary") or "")))
    late = sum(1 for i in items if due_of(i) and due_of(i) < today)
    lines = [f"{len(items)} open follow-up{'s' if len(items) != 1 else ''}{at}"
             + (f", {late} late" if late else "") + ":"]
    for i in items[:12]:
        who = ((i.get("owner") or {}).get("name") or "no owner yet").strip()
        d = due_of(i)
        due = "" if not d else (f" — ⚠️ {(today - d).days} day{'s' if (today - d).days != 1 else ''} late"
                                if d < today else f" — due {day_label(d, today)}")
        last = chased.get(str(i.get("_id")))
        ch = f" (chased {day_label(local_day(last), today)})" if last else ""
        lines.append(f"• {who}: {str(i.get('summary') or '')[:90]}{due}{ch}")
    if len(items) > 12:
        lines.append(f"…and {len(items) - 12} more.")
    return "\n".join(lines)


FOLLOW_UPS_TOOL = {"type": "function", "function": {
    "name": "follow_ups",
    "description": (
        "What people owe on this job: open requests and commitments from the job's WhatsApp "
        "group, who owns each, when it's due, how late, and when the chase last nudged them. "
        "Optionally for one owner (person or company). USE THIS for 'what's outstanding', "
        "'what does X owe', 'what's late', 'who have we been chasing'."),
    "parameters": {"type": "object", "properties": {
        "owner": {"type": "string", "description": "Optional: a person or company as said."}},
        "additionalProperties": False}}}


# ── UPCOMING ─────────────────────────────────────────────────────────────────

def upcoming_text(events: Iterable[Dict[str, Any]], now: datetime, days: int = 14,
                  job: str = "") -> str:
    today = local_day(now)
    end = today + timedelta(days=days)
    rows = []
    for e in events:
        try:
            d = date.fromisoformat(str(e.get("date"))[:10])
        except ValueError:
            continue
        if today <= d <= end and e.get("status", "open") == "open":
            rows.append((d, str(e.get("time") or ""), e))
    at = f" at {job}" if job else ""
    if not rows:
        return f"Nothing coming up{at} in the next {days} days."
    rows.sort(key=lambda t: (t[0], t[1]))
    lines = [f"Coming up{at}:"]
    for d, t, e in rows[:15]:
        when = day_label(d, today) + (f" {t}" if t else "")
        what = str(e.get("title") or e.get("kind") or "").strip()
        agency = str(e.get("agency") or "").strip()
        lines.append(f"• {when}: {what}" + (f" ({agency})" if agency and agency.lower() not in what.lower() else ""))
    return "\n".join(lines)


UPCOMING_TOOL = {"type": "function", "function": {
    "name": "upcoming_events",
    "description": (
        "What is coming up on this job: inspections, DOB/ECB hearings, permit expirations, "
        "deliveries and dated events from the job's group, from today on. USE THIS for "
        "'what's coming up', 'any inspections this week', 'when is the hearing'."),
    "parameters": {"type": "object", "properties": {
        "days": {"type": "integer", "description": "How many days ahead (default 14, at most 60)."}},
        "additionalProperties": False}}}


# ── THE MORNING BRIEF, AS SENT ───────────────────────────────────────────────

BRIEF_LOG = "brief_log"

#: Why a brief was not sent, in words.
REASONS = {
    "not_eligible": "your account isn't an admin or PM account that gets DMs",
    "no_optin": "WhatsApp messages from Levelog aren't turned on for your number (reply START to turn them on)",
    "phone_changed": "the phone on your profile changed since you turned WhatsApp on (reply START again)",
    "prefs_off": "WhatsApp messages are turned off in your notification settings",
    "brief_off": "your morning brief is set to Off",
    "no_jobs": "you have no jobs in Levelog to brief",
    "shabbos": "it was Shabbos / Yom Tov",
    "weekend": "it's the weekend and your brief is weekdays only",
    "send_failed": "WhatsApp did not accept the message",
    "error": "the brief could not be put together",
    "duplicate": "it was already claimed as sent",
}


def _clock(at: Any) -> str:
    """"8:05" (New York), or "" for no time."""
    if not isinstance(at, datetime):
        return ""
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return _fmt(at.astimezone(NY), "%-I:%M")


def brief_status_text(log: Optional[Dict[str, Any]], ledger: Optional[Dict[str, Any]],
                      settings: Dict[str, Any], now: datetime, day: date) -> str:
    """From the send log only: "Today's brief went out at 8:05 AM.",
    "Sending failed at 8:05 (WhatsApp error). …", "…was not sent: <why>.",
    or that there is no record -- never a guess."""
    is_today = day == local_day(now)
    which = "Today's brief" if is_today else f"The brief for {_fmt(day, '%a %b %-d')}"
    log = dict(log or {})
    status = log.get("status")
    at = log.get("sent_at") or log.get("at")
    if not status and ledger:
        # The ledger alone (a send before brief_log existed).
        lst = ledger.get("status")
        status = {"sending": "failed", "skipped_shabbos": "skipped"}.get(lst, lst)
        at = ledger.get("finished_at") or ledger.get("created_at")
        log["reason"] = {"failed": "send_failed", "sending": "send_failed",
                         "skipped_shabbos": "shabbos"}.get(lst)
    if status in ("sent", "resent"):
        t = _fmt(at.astimezone(NY), "%-I:%M %p") if isinstance(at, datetime) else ""
        return f"{which} went out" + (f" at {t}." if t else ".")
    if status == "failed":
        t = _clock(log.get("first_failed_at") or at)
        when = f" at {t}" if t else ""
        if not is_today:
            return f"{which} failed to send{when}."
        nxt = log.get("next_try_at")
        retry = (f" I'll try again at {_clock(nxt)}."
                 if isinstance(nxt, datetime) and not log.get("final") else "")
        if log.get("reason") == "error":
            head = f"Today's brief could not be put together{when} — the team has been told."
        else:
            head = f"Sending failed{when} (WhatsApp error)."
        return f"{head}{retry} Say \"send me my brief\" to try again."
    if status in ("refused", "skipped"):
        why = REASONS.get(log.get("reason") or "")
        tail = " Say \"send me my brief\" and I'll send it now." if is_today else ""
        if not why:
            return f"I can't see why {which[0].lower() + which[1:]} wasn't sent.{tail}"
        return f"{which} was not sent: {why}.{tail}"
    t = settings.get("brief_time")
    if is_today and t and t != "off":
        due = now.astimezone(NY).replace(hour=int(t[:2]), minute=0, second=0, microsecond=0)
        if now.astimezone(NY) < due:
            return f"Your brief is set for {_fmt(due, '%-I:%M %p')} — it hasn't gone out yet today."
    if t == "off":
        return f"I can't see a brief sent to you {('today' if is_today else 'that day')}: your brief is set to Off."
    return (f"I can't see a brief sent to you {('today' if is_today else 'that day')}."
            + (" Say \"send me my brief\" and I'll send it now." if is_today else ""))


BRIEF_STATUS_TOOL = {"type": "function", "function": {
    "name": "brief_status",
    "description": (
        "Whether THIS user's morning brief was sent, from the send log: when it went out, "
        "or why it was skipped or failed. USE THIS for any question about the brief having "
        "been sent or received. Never say a brief was sent without it."),
    "parameters": {"type": "object", "properties": {
        "date": {"type": "string", "description": "YYYY-MM-DD; omit for today."}},
        "additionalProperties": False}}}


# ── A QUESTION ABOUT THE USER'S OWN THINGS (never "Which job?") ─────────────

_BRIEF_WORDS = r"(?:morning\s+)?(?:brief(?:ing)?|daily\s+(?:summary|update|report)|morning\s+(?:summary|update|report|message))"
_SEND_BRIEF = re.compile(
    r"(?:\b(?:re-?send|send)|^\s*(?:(?:can|could|would)\s+you\s+|please\s+|pls\s+)?(?:give|show|get))"
    r"\s+(?:it\s+)?(?:to\s+)?(?:me\s+)?(?:my\s+|the\s+|today'?s\s+|this\s+morning'?s\s+)*"
    + _BRIEF_WORDS + r"(?:\s+(?:again|now|today))*\b", re.IGNORECASE)
_BRIEF_Q = re.compile(r"\b" + _BRIEF_WORDS + r"\b", re.IGNORECASE)
#: Was it sent / did it come -- not what it said.
_BRIEF_STATUS = re.compile(
    r"\b(?:get|got|gotten|receive[d]?|sent|send|arrive[d]?|came|come|go\s+out|went\s+out|"
    r"miss(?:ed|ing)?|where(?:'?s|\s+is)?|why|didn'?t|no|not|never)\b", re.IGNORECASE)
_MY_THINGS = re.compile(
    r"\b(?:my|me)\b.*\b(?:reminders?|settings?|notifications?|messages?|alerts?|dms?)\b"
    r"|\b(?:reminders?|settings?|notifications?)\b.*\b(?:my|me|i)\b", re.IGNORECASE)


_BRIEF_AS_TIME = re.compile(
    r"\b(?:since|after|before|from|till|until)\s+(?:the\s+|my\s+|your\s+|this\s+morning'?s\s+)?"
    r"(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+)?" + _BRIEF_WORDS, re.IGNORECASE)
_ABOUT_SITE = re.compile(
    r"\b(?:who|workers?|guys|crew|checked\s+in|check-?ins?|on\s+site|came\s+in|showed\s+up)\b",
    re.IGNORECASE)


def user_topic(text: Any) -> Optional[str]:
    """"send_brief" (send it now), "brief" (about it), "settings" (their
    brief time / reminders / notifications), or None. These are about the
    person, never a job."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    if _BRIEF_AS_TIME.search(t) or _ABOUT_SITE.search(t):
        # "who came in after the brief", "since your 8:07 brief": the brief
        # is a time there; the question is about the job.
        return None
    if _SEND_BRIEF.search(t):
        return "send_brief"
    if _BRIEF_Q.search(t) and _BRIEF_STATUS.search(t):
        return "brief"
    if _BRIEF_Q.search(t) and re.search(r"\b(?:time|when|settings?|turn|set)\b", t, re.I) \
            and not re.search(r"\b(?:get|got|sent|send|receive|arrive|came|come)\b", t, re.I):
        return "settings"
    if _MY_THINGS.search(t) and not re.search(r"\b(?:sub|subs|worker|crew|permit|punch|job)\b", t, re.I):
        return "settings"
    return None


def settings_text(settings: Dict[str, Any], optin: bool, enabled: bool = True) -> str:
    t = settings.get("brief_time") or "off"
    when = "Off" if t == "off" else _fmt(datetime.strptime(t, "%H:%M"), "%-I:%M %p")
    days = "every day" if settings.get("brief_weekend") else "Mon–Fri"
    lines = [f"Morning brief: {when}" + ("" if t == "off" else f", {days} (New York time).")]
    lines.append("5 PM \"Tomorrow\" reminders: " + ("on." if settings.get("upcoming_reminders") else "off."))
    if not optin:
        lines.append("WhatsApp messages from Levelog are off for your number — reply START to turn them on.")
    elif not enabled:
        lines.append("But WhatsApp messages are turned off in your notification settings, so none of "
                     "these are sent — turn them on in the app: Settings → WhatsApp.")
    lines.append("Change them in the app: Settings → WhatsApp.")
    return "\n".join(lines)


# ── THE BACKSTOP: "the data doesn't specify" when it does ───────────────────

_ATTEND_Q = re.compile(
    r"\bhow\s+(?:many|long)\s+(?:days?|weeks?)\b|\bdays?\s+on\s+(?:site|the\s+job)\b|"
    r"\bbeen\s+(?:on|at)\b|\bwhen\s+did\b.*\b(?:start|first)\b|\bhow\s+many\s+(?:guys|men|workers)\s+"
    r"(?:does|do|did)\b|\b(?:usually|on\s+average)\s+send\b", re.IGNORECASE)
_DENIES = re.compile(
    r"\b(?:doesn'?t|does\s+not|don'?t|do\s+not)\s+(?:specify|say|show|include|have|contain)\b|"
    r"\b(?:no|not\s+enough)\s+(?:data|information|records?)\b|\bnot\s+(?:available|specified|recorded)\b|"
    r"\b(?:can'?t|cannot|unable\s+to|not\s+able\s+to)\s+(?:tell|determine|see|find|check|access|say)\b",
    re.IGNORECASE)


def about_attendance(text: Any) -> bool:
    """"How many days has Arkon been on 588?" -- a check-ins question."""
    return bool(_ATTEND_Q.search(str(text or "")))


def denies_data(reply: Any) -> bool:
    """The reply claims the data does not say, or that it cannot tell."""
    return bool(_DENIES.search(str(reply or "")))


def sub_in_question(text: Any, names: Iterable[str]) -> Optional[str]:
    """The company a question names, from the check-ins' company names:
    any word of the question that matches one ("arkon")."""
    names = list(names)
    for w in re.findall(r"[A-Za-z][A-Za-z'&.-]{2,}", str(text or "")):
        if w.lower() in ("how", "many", "days", "has", "have", "been", "the", "on", "site", "job",
                         "long", "when", "did", "start", "first", "workers", "guys", "men"):
            continue
        hit = match_companies(names, w)
        if hit:
            return w
    return None


_CLAIMS_BRIEF = re.compile(
    r"\b(?:brief(?:ing)?|morning\s+(?:summary|update|report))\b[^.?!]{0,60}\b(?:was|were|has\s+been|got|went)\s+"
    r"(?:sent|delivered|out|skipped)\b|\b(?:sent|delivered)\s+(?:you\s+)?(?:the\s+|your\s+|today'?s\s+)?"
    r"(?:morning\s+)?brief", re.IGNORECASE)


def claims_brief(reply: Any) -> bool:
    """The reply says a brief was sent / delivered / skipped."""
    return bool(_CLAIMS_BRIEF.search(str(reply or "")))
