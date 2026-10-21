"""Morning brief — the pure parts (no database, no network).

WhatsApp DMs once a day to each opted-in Admin (all company jobs) and PM
(assigned jobs), one message per job: what needs action today, then who is
on site so far.

DETERMINISTIC. Every line comes from a stored record, with that record's own
number, date and status. Nothing is inferred and no urgency is invented: a
record without the value a line needs is left out, never filled in.

  🔴  new violation / complaint / stop-work order since the last brief
  🔴  new DOT summons since the last brief
  🟠  an OATH hearing still to come on a DOT summons (its hearing_date)
  🟡  a DOB status change: permit issued / expired / revoked, stop-work order
      rescinded, or any change DOB marks as needing action
  🟠  DOB or DOT permit expiring within 14 days, or expired in the last 30
  (inspections: no stored scheduled date exists, so there is no 🔴 line for
   them — none is guessed)

Sort: DOB/regulatory, then permits. At most 7 items per job.

THE LAYOUT is a fixed template (compose_messages, at the bottom): one
message per job, in this order, WhatsApp *bold* headers, one line per item,
a blank line between sections, an empty section left out --

  📅 Today · 🏛 DOB / DOT · 📋 Open violations (Mondays) · ✅ You ·
  ⏳ Waiting on others · 🔍 Check · 👷 who is on site · 📆 Later this week

  You: open items due today / late / ASAP that the recipient owns, as the
      item's stored summary ("Send calcs — ⚠️ 2 days late"); the quote is
      for search and the app
  Waiting on others: what they asked someone else for, and open punch per
      assignee ("Chris: 4 punch items (oldest 2 days)"); punch assigned to
      the recipient is under You ("3 punch items (oldest 2 days)"). Punch
      counts only items of walks sent live, never a shadow walk's.
  Today / Later this week: Upcoming events, today's under Today
  Open violations: Mondays (New York) only, the job's DOB violations,
      stop-work orders and DOT summonses still open (open_items); at most
      8, none repeated from a 🔴 New line

A last short message holds the recipient's own reminders, the quiet jobs
("No check-ins yet: A, B.") and "No action needed today." when no job has
anything to say.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib import dot_sync, source_sync, wa_alerts, wa_gc

try:  # zoneinfo is stdlib; tzdata may be absent on a slim image
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None

# ── When ────────────────────────────────────────────────────────────────────

BRIEF_TIMES = ("off", "07:00", "08:00", "09:00")
DEFAULT_TIME = "07:00"
# A brief missed at its hour (a restart, a deploy) still goes out within
# this many hours; after that the day is skipped rather than sent at noon.
CATCHUP_HOURS = 3


def local_now(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(_ET) if _ET else now_utc


def is_due(now_utc: datetime, brief_time: Optional[str], weekend: bool) -> bool:
    """Is it this person's brief time today (New York), on a brief day?
    Weekdays always; Saturday and Sunday only with `weekend` on."""
    if brief_time not in BRIEF_TIMES or brief_time == "off":
        return False
    now = local_now(now_utc)
    wd = now.weekday()  # Mon 0 … Sun 6
    if wd >= 5 and not weekend:
        return False
    hour = int(brief_time[:2])
    return hour <= now.hour < hour + CATCHUP_HOURS


def clean_settings(stored: Any) -> Dict[str, Any]:
    """{brief_time, brief_weekend, brief_saturday} from whatever is stored;
    defaults (7 AM, weekdays only) for anything missing or ill-typed.

    brief_weekend (Saturday and Sunday) replaced brief_saturday. A row the
    startup migration has not reached yet still counts its brief_saturday,
    and brief_saturday is returned as a copy of brief_weekend for app
    versions that still read it."""
    s = stored if isinstance(stored, dict) else {}
    t = s.get("brief_time")
    weekend = (s.get("brief_weekend") is True if "brief_weekend" in s
               else s.get("brief_saturday") is True)
    return {"brief_time": t if t in BRIEF_TIMES else DEFAULT_TIME,
            "brief_weekend": weekend, "brief_saturday": weekend}


# ── What ────────────────────────────────────────────────────────────────────

MAX_ITEMS = 7
PERMIT_SOON_DAYS = 14
EXPIRED_RECENT_DAYS = 30
# "New" also needs DOB's own issue date to be recent: a project's first DOB
# scan stores years of history at once, and none of that is new today.
NEW_ISSUED_WITHIN_DAYS = 30

RANK_REGULATORY = 1
RANK_PERMIT = 2

_NEW_KINDS = {
    "violation": ("violation", "violation_number", "violation_date", "issued"),
    "complaint": ("complaint", "complaint_number", "complaint_date", "filed"),
    "swo": ("stop-work order", "stop_work_order_number", "violation_date", "issued"),
}

_NUMBER_FIELD = {
    "violation": "violation_number",
    "complaint": "complaint_number",
    "swo": "stop_work_order_number",
    "permit": "job_number",
    "job_status": "job_number",
    "cofo": "job_number",
    "facade_fisp": "filing_number",
    "boiler": "tracking_number",
    "elevator": "device_number",
}
_KIND_LABEL = {
    "violation": "Violation", "complaint": "Complaint", "swo": "Stop-work order",
    "permit": "Permit", "job_status": "Job", "cofo": "C of O",
    "facade_fisp": "Facade filing", "boiler": "Boiler filing",
    "elevator": "Elevator device",
}


def _stamp(r: Dict[str, Any]) -> datetime:
    v = r.get("status_changed_at") or r.get("detected_at")
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _detected(r: Dict[str, Any]) -> Optional[datetime]:
    v = r.get("detected_at")
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _text(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _md(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _status(r: Dict[str, Any]) -> str:
    """The record's own status words, as stored."""
    for k in ("resolution_state", "complaint_status", "status", "current_status",
              "permit_status"):
        v = _text(r.get(k))
        if v:
            return v.lower() if k == "resolution_state" else v
    return ""


def _is_closed(r: Dict[str, Any]) -> bool:
    for k in ("resolution_state", "complaint_status", "status", "current_status"):
        # Whole words, negation-aware (wa_alerts.status_is_closed): UNPAID and
        # NOT CERTIFIED are OPEN states, which a prefix test read as closed.
        if wa_alerts.status_is_closed(r.get(k)):
            return True
    return bool(_text(r.get("closed_date")))


def group_records(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Rows per raw_dob_id, oldest first."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        rid = _text(r.get("raw_dob_id"))
        if rid:
            out.setdefault(rid, []).append(r)
    for v in out.values():
        v.sort(key=_stamp)
    return out


def record_key(source: str, rid: Any) -> str:
    """'dob:<raw_dob_id>' / 'dot:<raw_id>': one record, whichever list it is in."""
    return f"{source}:{_text(rid)}"


def _expiry_item(r: Dict[str, Any], num_field: str, source: str, today: date,
                 *, work: str = "", label: str = "Permit") -> Optional[Dict[str, Any]]:
    """🟠 a permit expiring within 14 days, or expired in the last 30."""
    exp = wa_gc.parse_dob_date(r.get("expiration_date"))
    num = _text(r.get(num_field))
    if not exp or not num:
        return None
    days = (exp - today).days
    name = f"{label} {num}" + (f" ({work})" if work else "")
    if 0 <= days <= PERMIT_SOON_DAYS:
        when = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''}"
        return {"rank": RANK_PERMIT, "order": (days,),
                "text": f"🟠 {name} expires {_md(exp)} ({when}). {source}."}
    if -EXPIRED_RECENT_DAYS <= days < 0:
        ago = -days
        return {"rank": RANK_PERMIT, "order": (days,),
                "text": f"🟠 {name} expired {_md(exp)} "
                        f"({ago} day{'s' if ago != 1 else ''} ago). {source}."}
    return None


def job_items(rows: Iterable[Dict[str, Any]], since: datetime,
              now_utc: datetime,
              dot_rows: Iterable[Dict[str, Any]] = (),
              synced: Optional[Dict[str, datetime]] = None) -> List[Dict[str, Any]]:
    """The items one job has today: [{rank, order, text}]. Pure. `dot_rows`
    are the job's dot_logs rows (DOT summonses and permits).

    `synced` is {source: first_synced_at} (lib/source_sync.first_synced).
    When given, a source not in it gives no item at all, and nothing its
    first sync stored is "new" or a "change"."""
    today = wa_gc.today_et(now_utc)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    def _cutoff(rt: str) -> Optional[datetime]:
        """`since`, moved up to the source's first sync; None: skip the row."""
        src = source_sync.RECORD_SOURCE.get(rt)
        if synced is None or src is None:
            return since
        first = synced.get(src)
        return None if first is None else max(since, first)

    items: List[Dict[str, Any]] = []
    for rid, hist in group_records(rows).items():
        first, latest = hist[0], hist[-1]
        rt = _text(latest.get("record_type")).lower()
        cutoff = _cutoff(rt)
        if cutoff is None:
            continue

        # 🔴 new violation / complaint / stop-work order
        if rt in _NEW_KINDS:
            label, num_f, date_f, verb = _NEW_KINDS[rt]
            seen = _detected(first)
            if (seen and seen > cutoff and not first.get("is_seed_transition")
                    and first.get("previous_status") is None):
                # A stop-work order found by text in a violation dataset is
                # stored with the violation's fields: its number is there.
                num = _text(latest.get(num_f)) or (
                    _text(latest.get("violation_number")) if rt == "swo" else "")
                issued = wa_gc.parse_dob_date(latest.get(date_f))
                status = _status(latest)
                if (num and issued and status and not _is_closed(latest)
                        and timedelta(0) <= today - issued
                        <= timedelta(days=NEW_ISSUED_WITHIN_DAYS)):
                    items.append({
                        "rank": RANK_REGULATORY, "order": (0, -issued.toordinal()),
                        "record": record_key("dob", rid),
                        "text": f"🔴 New {label} {num}, {verb} {_md(issued)}, {status}. DOB."})
                    continue

        # 🟠 permit expiring / expired (not for a revoked permit)
        if rt == "permit" and _text(latest.get("permit_status")).upper() != "REVOKED":
            item = _expiry_item(latest, "job_number", "DOB", today,
                                work=_text(latest.get("work_type")))
            if item:
                items.append(item)

        # 🟡 a status change: a permit issued / expired / revoked, a
        # stop-work order rescinded, or any change DOB marks as needing action
        before = _text(latest.get("previous_status"))
        after = _text(latest.get("current_status"))
        # A permit changes by a NEW row; a violation or stop-work order is
        # refreshed IN PLACE (one row, its status_history grows) -- so a
        # change is either more than one row or more than one history entry.
        changed_row = len(hist) > 1 or len(latest.get("status_history") or []) > 1
        if (changed_row and before and after and before != after
                and not latest.get("is_seed_transition") and _stamp(latest) > cutoff):
            up = after.upper()
            permit_change = rt == "permit" and any(
                w in up for w in ("ISSUED", "EXPIRED", "REVOKED"))
            rescinded = rt == "swo" and (("RESCIND" in up or "LIFTED" in up)
                                         or wa_alerts.status_is_closed(after))
            action = (_text(latest.get("severity")) == "Action"
                      and not _is_closed(latest))
            if permit_change or rescinded or action:
                num = _text(latest.get(_NUMBER_FIELD.get(rt, ""))) or (
                    _text(latest.get("violation_number")) if rt == "swo" else "")
                if num:
                    changed = local_now(_stamp(latest)).date()
                    items.append({
                        "rank": RANK_REGULATORY, "order": (1, -changed.toordinal()),
                        "text": f"🟡 {_KIND_LABEL.get(rt, 'Record')} {num} changed "
                                f"{before} → {after} on {_md(changed)}. DOB."})

    # DOT (dot_logs: one row per record, already matched to this job)
    for r in dot_rows:
        rt = _text(r.get("record_type")).lower()
        cutoff = _cutoff(rt)
        if cutoff is None:
            continue
        if rt == "dot_violation":
            seen = _detected(r)
            num = _text(r.get("number"))
            issued = wa_gc.parse_dob_date(r.get("issue_date"))
            if (seen and seen > cutoff and num and issued and not _is_closed(r)
                    and timedelta(0) <= today - issued
                    <= timedelta(days=NEW_ISSUED_WITHIN_DAYS)):
                status = _text(r.get("status"))
                items.append({
                    "rank": RANK_REGULATORY, "order": (0, -issued.toordinal()),
                    "record": record_key("dot", r.get("raw_id") or num),
                    "text": f"🔴 New DOT summons {num}, issued {_md(issued)}"
                            + (f", {status}" if status else "") + ". DOT."})
        elif rt == "dot_permit" and dot_sync.permit_is_active(r.get("status")):
            item = _expiry_item(r, "number", "DOT", today, label="DOT permit")
            if item:
                items.append(item)
        if rt == "dot_violation":
            # An OATH hearing still to come, from the record's hearing_date.
            hearing = wa_gc.parse_dob_date(r.get("hearing_date"))
            num = _text(r.get("number"))
            if hearing and num and hearing >= today:
                items.append({
                    "rank": RANK_REGULATORY, "order": (0, hearing.toordinal()),
                    "text": f"🟠 OATH hearing {_md(hearing)} · ticket #{num} · DOT."})
    items.sort(key=lambda i: (i["rank"], i["order"]))
    return items


# ── Open violations: Mondays ────────────────────────────────────────────────
#
# A new violation is a 🔴 line once, on the first brief after it is found.
# On Mondays each job's message also lists the violations still open, so
# they are looked at once a week. Which are open is wa_alerts'
# open_dob_violations / open_dot_summonses -- the rule the app's
# open-violation count uses. One line each, from the record's own stored
# values; a value not stored is left out of the line, never filled in.

MAX_OPEN = 8


def is_review_day(now_utc: datetime) -> bool:
    """Monday in New York: the day the brief lists open violations."""
    return local_now(now_utc).weekday() == 0


def _amount(v: Any) -> str:
    """'$2,500' / '$312.50' from a stored amount; '' for none or zero."""
    try:
        n = float("".join(ch for ch in str(v or "") if ch.isdigit() or ch in ".-") or "x")
    except ValueError:
        return ""
    if n <= 0:
        return ""
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"


def open_items(rows: Iterable[Dict[str, Any]], dot_rows: Iterable[Dict[str, Any]],
               today: date, skip: Iterable[str] = (),
               synced: Optional[Dict[str, datetime]] = None) -> List[str]:
    """The job's open violations, one line each: ['• DOB 35123456 · issued
    Sep 2 · penalty $2,500 · hearing Nov 4', ...]. Pure.

    Stop-work orders first, then the oldest issued first; at most MAX_OPEN,
    then '+N more open in the Levelog app.'. `skip`: record_key()s already
    shown today as new. `synced` as in job_items: a source not yet through
    its first sync gives no line. A record without its number has no line."""
    skip = set(skip)

    def _ready(rt: str) -> bool:
        src = source_sync.RECORD_SOURCE.get(rt)
        return synced is None or src is None or src in synced

    found: List[Tuple[Tuple, str]] = []
    for r in wa_alerts.open_dob_violations(rows):
        rt = _text(r.get("record_type")).lower()
        if not _ready(rt) or record_key("dob", r.get("raw_dob_id")) in skip:
            continue
        num = _text(r.get(_NUMBER_FIELD[rt])) or _text(r.get("violation_number"))
        if not num:
            continue
        issued = wa_gc.parse_dob_date(r.get("violation_date"))
        hearing = wa_gc.parse_dob_date(r.get("hearing_date"))
        parts = [f"Stop-work order {num}" if rt == "swo" else f"DOB {num}"]
        parts += [f"issued {_md(issued)}"] if issued else []
        penalty = _amount(r.get("penalty_amount"))
        parts += [f"penalty {penalty}"] if penalty else []
        parts += [f"hearing {_md(hearing)}"] if hearing and hearing >= today else []
        found.append(((0 if rt == "swo" else 1, issued or date.max, num), " · ".join(parts)))
    for r in wa_alerts.open_dot_summonses(dot_rows):
        if not _ready("dot_violation") or record_key(
                "dot", r.get("raw_id") or r.get("number")) in skip:
            continue
        num = _text(r.get("number"))
        issued = wa_gc.parse_dob_date(r.get("issue_date"))
        hearing = wa_gc.parse_dob_date(r.get("hearing_date"))
        parts = [f"DOT {num}"]
        parts += [f"issued {_md(issued)}"] if issued else []
        due = _amount(r.get("balance_due"))
        parts += [f"{due} due"] if due else []
        parts += [f"hearing {_md(hearing)}"] if hearing and hearing >= today else []
        found.append(((1, issued or date.max, num), " · ".join(parts)))
    found.sort(key=lambda f: f[0])
    lines = [f"• {line}" for _k, line in found[:MAX_OPEN]]
    if len(found) > MAX_OPEN:
        lines.append(f"+{len(found) - MAX_OPEN} more open in the Levelog app.")
    return lines


# ── Follow-ups: You / Waiting on others / Check ─────────────────────────────

_LIVE = ("open", "rescheduled")
MAX_TASKS = 6          # per section, per job; the rest are "+N more in the app"
TASK_CHARS = 60


def _last10(v: Any) -> str:
    d = "".join(ch for ch in str(v or "").split("@")[0] if ch.isdigit())
    return d[-10:] if len(d) >= 10 else ""


def is_me(person: Any, me: Dict[str, Any]) -> bool:
    """A stored person (owner / requester) is the recipient: their user id,
    or their WhatsApp number."""
    p = person if isinstance(person, dict) else {}
    if p.get("kind") == "user" and p.get("id") and str(p["id"]) == str(me.get("user_id")):
        return True
    d = _last10(p.get("jid"))
    return bool(d) and d in (me.get("digits") or set())


def _asked_by(item: Dict[str, Any], me: Dict[str, Any]) -> bool:
    if is_me(item.get("requester"), me):
        return True
    ev = item.get("evidence") or {}
    # A request or question: whoever wrote it asked for it.
    return (item.get("type") in ("request", "question")
            and _last10(ev.get("sender")) in (me.get("digits") or set())
            and bool(_last10(ev.get("sender"))))


def _day_label(d: date) -> str:
    return f"{d.strftime('%a %b')} {d.day}"


def _due_day(item: Dict[str, Any]) -> Optional[date]:
    try:
        return date.fromisoformat(str((item.get("due") or {}).get("due_at") or "")[:10])
    except ValueError:
        return None


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _words(item: Dict[str, Any]) -> str:
    """The item's own words: the quote it was read from."""
    q = item.get("chase_quote") or {}
    text = q.get("quote") if q.get("quote") else (item.get("evidence") or {}).get("quote")
    return " ".join(str(text or "").split())


def task_text(item: Dict[str, Any]) -> str:
    """What to do, short: the item's stored summary ("Send calcs"). The
    quote is for search and the app; only an item stored without a summary
    shows a short piece of it, in quotes."""
    summary = " ".join(str(item.get("summary") or "").split()).rstrip(" .")
    if summary:
        return _clip(summary[0].upper() + summary[1:], TASK_CHARS)
    words = _words(item)
    return f"“{_clip(words, TASK_CHARS - 12)}”" if words else ""


def lateness(d: date, today: date, asap: bool = False) -> str:
    """' — ⚠️ 2 days late' / ' · today' / ' · ASAP'."""
    if asap:
        return " · ASAP"
    late = (today - d).days
    if late <= 0:
        return " · today"
    return f" — ⚠️ {late} day{'s' if late != 1 else ''} late"


def first_names(names: Iterable[str]) -> Dict[str, str]:
    """Each full name as its first name, unless two share one."""
    names = [n for n in dict.fromkeys(names) if n]
    firsts: Dict[str, int] = {}
    for n in names:
        firsts[n.split()[0].lower()] = firsts.get(n.split()[0].lower(), 0) + 1
    return {n: (n.split()[0] if firsts[n.split()[0].lower()] == 1 else n) for n in names}


def _more(lines: List[str], n: int) -> List[str]:
    return lines[:MAX_TASKS] + ([f"• +{n - MAX_TASKS} more in the Levelog app"]
                                if n > MAX_TASKS else [])


def task_sections(items: Iterable[Dict[str, Any]], today: date,
                  me: Dict[str, Any]) -> Tuple[List[str], List[Tuple[Tuple, str, str]]]:
    """Open items due today, overdue or ASAP that the recipient owns (You)
    or asked someone else for (Waiting on others). You: ['• Send calcs —
    ⚠️ 2 days late']; waiting: [(sort key, who, '<task><when>')] for
    waiting_lines to name. Punch items are not here (punch_sections)."""
    you, waiting = [], []
    for it in items:
        if it.get("status") not in _LIVE or "punch" in (it.get("tags") or []):
            continue
        if it.get("needs_review") or (it.get("review") or {}).get("verdict") in (
                "wrong", "dismissed"):
            continue
        d = _due_day(it)
        task = task_text(it)
        if not d or d > today or not task:
            continue
        asap = str((it.get("due") or {}).get("due_text") or "").strip().upper() == "ASAP"
        key = (0 if d < today and not asap else 1, d.toordinal(), task.lower())
        line = task + lateness(d, today, asap)
        if is_me(it.get("owner"), me):
            you.append((key, f"• {line}"))
        elif _asked_by(it, me):
            owner = it.get("owner") or {}
            who = owner.get("name") if owner.get("status") == "resolved" and owner.get("name") \
                else ""
            waiting.append((key, who, line))
    you.sort(key=lambda r: r[0])
    return _more([r[1] for r in you], len(you)), waiting


def _age(d: date, today: date) -> str:
    n = (today - d).days
    return "today" if n <= 0 else f"{n} day{'s' if n != 1 else ''}"


def sent_punch(r: Dict[str, Any]) -> bool:
    """The item really went out: its walk was sent live. A walk sent while
    the project's "Punch sends" was shadow (the default) stores its items
    with send_mode "shadow" -- open, but nobody was ever told about them --
    so no brief counts them (server.py stores send_mode on each row when
    the walk is sent)."""
    return r.get("send_mode") == "live"


def _punch_day(r: Dict[str, Any], today: date) -> date:
    at = r.get("assigned_at") or r.get("created_at")
    if isinstance(at, datetime):
        return local_now(at if at.tzinfo else at.replace(tzinfo=timezone.utc)).date()
    return today


def punch_sections(rows: Iterable[Dict[str, Any]], today: date,
                   me: Optional[Dict[str, Any]] = None
                   ) -> Tuple[Dict[str, List[date]], List[str]]:
    """Open punch per assignee ({name: [assigned days]}), and the Check
    line: '• 1 punch item ready to check'. Only items of walks sent live
    (sent_punch); the recipient's own items (`me`) are theirs to do, not
    waited on (own_punch_lines)."""
    by: Dict[str, List[date]] = {}
    ready = 0
    for r in rows:
        if not sent_punch(r):
            continue
        st = r.get("status")
        if st == "ready_to_check":
            ready += 1
            continue
        if st != "open" or (me and is_me(r.get("assignee"), me)):
            continue
        who = ((r.get("assignee") or {}).get("name") or "").strip() or "Unassigned"
        by.setdefault(who, []).append(_punch_day(r, today))
    check = [f"• {ready} punch item{'s' if ready != 1 else ''} ready to check"] if ready else []
    return by, check


def own_punch_lines(rows: Iterable[Dict[str, Any]], today: date,
                    me: Dict[str, Any]) -> List[str]:
    """The You line for open punch assigned to the recipient (by user id,
    or their WhatsApp number): ['• 3 punch items (oldest 2 days)']."""
    days = [_punch_day(r, today) for r in rows
            if sent_punch(r) and r.get("status") == "open" and is_me(r.get("assignee"), me)]
    if not days:
        return []
    n, age = len(days), _age(min(days), today)
    return [f"• {n} punch item{'s' if n != 1 else ''} "
            + (f"(oldest {age})" if n > 1 else f"({age})")]


def waiting_lines(tasks: List[Tuple[Tuple, str, str]], punch: Dict[str, List[date]],
                  today: date) -> List[str]:
    """'• Mike: Send calcs — ⚠️ 2 days late', then '• Chris: 4 punch items
    (oldest 2 days)'. People by first name unless two share it."""
    short = first_names([w for _k, w, _l in tasks] + [w for w in punch if w != "Unassigned"])
    out = []
    for _k, who, line in sorted(tasks, key=lambda t: t[0]):
        out.append(f"• {short.get(who, who) or 'No owner yet'}: {line}")
    out = _more(out, len(out))
    for who, days in sorted(punch.items(), key=lambda kv: (min(kv[1]), kv[0].lower())):
        n = len(days)
        age = _age(min(days), today)
        out.append(f"• {short.get(who, who)}: {n} punch item{'s' if n != 1 else ''} "
                   + (f"(oldest {age})" if n > 1 else f"({age})"))
    return out


# ── Who is on site ──────────────────────────────────────────────────────────

MAX_COMPANIES = 5
NO_COMPANY = "No company"
NO_CHECKINS = "No check-ins yet."
_COMPANY_TAIL = {"inc", "llc", "corp", "corporation", "co", "company", "ltd", "group",
                 "construction", "contracting", "contractors", "contractor", "builders",
                 "services", "plumbing", "electric", "electrical", "mechanical",
                 "enterprises", "nyc", "ny"}


def short_company(name: str) -> str:
    """'Quality Plumbing Corp.' -> 'Quality'; never down to nothing."""
    if name == NO_COMPANY:
        return name
    words = [w for w in str(name or "").replace(",", " ").split()]
    while len(words) > 1 and words[-1].strip(".").lower() in _COMPANY_TAIL:
        words.pop()
    return " ".join(words) or str(name or "")


def _on_site(checkins: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """{worker: company}: each worker once, under their first check-in's company."""
    by_worker: Dict[str, str] = {}
    for ci in sorted(checkins, key=lambda c: str(c.get("check_in_time") or "")):
        wid = _text(ci.get("worker_id")) or _text(ci.get("worker_phone")) \
            or _text(ci.get("_id"))
        if not wid or wid in by_worker:
            continue
        company = ""
        for k in ("worker_company", "company", "company_name"):
            if ci.get(k):
                company = _text(ci.get(k))
                break
        by_worker[wid] = company or NO_COMPANY
    return by_worker


def headcount_line(checkins: Iterable[Dict[str, Any]]) -> str:
    """'👷 24 on site · Arkon 11 · Quality 6 · Power Direct 5 · MQ 2', or
    NO_CHECKINS. Each worker counted once."""
    by_worker = _on_site(checkins)
    if not by_worker:
        return NO_CHECKINS
    counts: Dict[str, int] = {}
    for c in by_worker.values():
        counts[c] = counts.get(c, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    shown = ordered[:MAX_COMPANIES]
    short = [short_company(name) for name, _n in shown]
    # Two companies that shorten alike ('ABC Plumbing', 'ABC Electrical')
    # keep their full names.
    clash = {x for x in short if short.count(x) > 1}
    parts = [f"{name if s in clash else s} {n}"
             for (name, n), s in zip(shown, short)]
    more = len(ordered) - MAX_COMPANIES
    if more > 0:
        parts.append(f"+{more} more")
    return " · ".join([f"👷 {len(by_worker)} on site"] + parts)


# ── Events (Upcoming): Today / Later this week ──────────────────────────────

MAX_LATER = 5


def _time(t: Optional[str]) -> str:
    if not t:
        return ""
    try:
        h, m = (int(x) for x in str(t).split(":")[:2])
    except ValueError:
        return ""
    return f"{h % 12 or 12}{':%02d' % m if m else ''}{'am' if h < 12 else 'pm'}"


def _event_key(e: Dict[str, Any]) -> Tuple[str, str, str]:
    return (str(e.get("date") or ""), str(e.get("time") or "99:99"), str(e.get("title") or ""))


def _event_day(e: Dict[str, Any]) -> Optional[date]:
    try:
        return date.fromisoformat(str(e.get("date"))[:10])
    except ValueError:
        return None


def event_sections(events: Iterable[Dict[str, Any]], today: date
                   ) -> Tuple[List[str], List[str]]:
    """Today: ['• 7am Concrete pour']; Later this week: ['• Thu 9am
    Electrical inspection']. Events in date and time order. Later events
    are capped at MAX_LATER; the rest are '+N more'."""
    now_, later, extra = [], [], 0
    for e in sorted(events, key=_event_key):
        d = _event_day(e)
        title = " ".join(str(e.get("title") or "").split())
        if d is None or not title or d < today:
            continue
        t = _time(e.get("time"))
        if d == today:
            now_.append(" ".join(x for x in ("•", t, title) if x))
        elif len(later) < MAX_LATER:
            later.append(" ".join(x for x in ("•", d.strftime("%a"), t, title) if x))
        else:
            extra += 1
    return now_, later + ([f"• +{extra} more in the Levelog app"] if extra > 0 else [])


def events_by_job(events: Iterable[Dict[str, Any]], today: date
                  ) -> Dict[Optional[str], Tuple[List[str], List[str]]]:
    """{project_id (None for one's own reminders): (today, later)}. Each
    job's Later this week holds at most MAX_LATER events, the soonest
    first; a job with events cut says '+N more'."""
    groups: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for e in events:
        pid = e.get("project_id")
        groups.setdefault(str(pid) if pid else None, []).append(e)
    return {k: event_sections(v, today) for k, v in groups.items()}


# ── The messages: a fixed template ──────────────────────────────────────────
#
# One WhatsApp message per job that has something to say:
#
#   *Tue Oct 13* · *588 Thomas S Boyland*
#
#   📅 *Today*            events today
#   🏛 *DOB / DOT*        new violations, status changes, permits, hearings
#   📋 *Open violations*  Mondays only: the job's violations still open
#   ✅ *You*              your items due today / late
#   ⏳ *Waiting on others* what you asked for, and open punch per person
#   🔍 *Check*            punch items ready to check
#   👷 24 on site · …     who checked in
#   📆 *Later this week*  events after today
#
# then, when there is any, one last short message: "No action needed
# today." (no job had anything to act on), the recipient's own reminders,
# and "No check-ins yet: A, B." for the quiet jobs.
#
# One line per item, a blank line between sections, an empty section left
# out. Every line is a stored record's own values; nothing is written by a
# model here.

NOTHING_TODAY = "No action needed today."
H_TODAY, H_DOB, H_YOU = "📅 *Today*", "🏛 *DOB / DOT*", "✅ *You*"
H_OPEN = "📋 *Open violations*"
H_WAITING, H_CHECK, H_LATER = "⏳ *Waiting on others*", "🔍 *Check*", "📆 *Later this week*"
#: The part key of the last message (reminders, quiet jobs, nothing today);
#: a job's message is keyed by the job's id.
REST = "rest"


def header(now_utc: datetime) -> str:
    now = local_now(now_utc)
    return f"*{now.strftime('%a %b')} {now.day}*"


def job_sections(job: Dict[str, Any], dob: List[str]) -> List[str]:
    """One job's non-empty sections, a blank line between them; [] when it
    has nothing to say."""
    sections = [
        [H_TODAY] + list(job.get("today") or []) if job.get("today") else [],
        [H_DOB] + dob if dob else [],
        [H_OPEN] + list(job.get("open") or []) if job.get("open") else [],
        [H_YOU] + list(job.get("you") or []) if job.get("you") else [],
        [H_WAITING] + list(job.get("waiting") or []) if job.get("waiting") else [],
        [H_CHECK] + list(job.get("check") or []) if job.get("check") else [],
        [job["headcount"]] if job.get("headcount") and job["headcount"] != NO_CHECKINS else [],
        [H_LATER] + list(job.get("later") or []) if job.get("later") else [],
    ]
    out: List[str] = []
    for sec in (sec for sec in sections if sec):
        out += ([""] if out else []) + sec
    return out


def compose_messages(now_utc: datetime, jobs: List[Dict[str, Any]],
                     own: Optional[Dict[str, List[str]]] = None) -> List[Tuple[str, str]]:
    """[(part, text)]: one message per job with something to say (part: the
    job's id), then at most one more (part REST). jobs: [{id, label, items,
    open, today, you, waiting, check, headcount, uses_checkins, later}] in display
    order; `own`: {today, later} for the recipient's own reminders (no job).

    Each job shows at most MAX_ITEMS DOB / DOT lines, the most pressing
    first, and says '+N more' for the rest. Jobs with DOB / DOT lines come
    first, the most pressing first; then the others in display order. A job
    that uses check-ins with nothing at all is named in the last message's
    'No check-ins yet: A, B.'; any other job is left out. The last message
    also holds the reminders, and "No action needed today." when no job has
    anything to act on (a headcount alone is not)."""
    day = header(now_utc)
    msgs: List[Tuple[Tuple, str, str]] = []
    quiet = []
    for j, job in enumerate(jobs):
        items = sorted(job.get("items") or [], key=lambda i: (i["rank"], i["order"]))
        dob = [it["text"] for it in items[:MAX_ITEMS]]
        body = job_sections(job, dob)
        if not body:
            if job.get("uses_checkins", True):
                quiet.append(job["label"])
            continue
        if len(items) > MAX_ITEMS:
            body += ["", f"+{len(items) - MAX_ITEMS} more DOB / DOT in the Levelog app."]
        key = (0, items[0]["rank"], items[0]["order"], j) if dob else (1, j)
        part = str(job.get("id") or j)
        msgs.append((key, part, "\n".join([f"{day} · *{job['label']}*", ""] + body)))
    msgs.sort(key=lambda m: m[0])
    out = [(part, text) for _k, part, text in msgs]

    mine = job_sections({"today": (own or {}).get("today"),
                         "later": (own or {}).get("later")}, [])
    acting = bool(mine) or any(job.get(k) for job in jobs for k in
                               ("items", "open", "today", "you", "waiting", "check",
                                "later"))
    rest = [] if acting else [NOTHING_TODAY]
    if mine:
        rest += ([""] if rest else []) + ["*Your reminders*"] + mine
    if quiet:
        rest += ([""] if rest else []) + ["No check-ins yet: " + ", ".join(quiet) + "."]
    if rest:
        out.append((REST, "\n".join([day] + ([""] if acting else []) + rest)))
    return out
