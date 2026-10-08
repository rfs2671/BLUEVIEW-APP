"""Morning brief — the pure parts (no database, no network).

One WhatsApp DM a day to each opted-in Admin (all company jobs) and PM
(assigned jobs): what needs action today, then who is on site so far.

DETERMINISTIC. Every line comes from a stored record, with that record's own
number, date and status. Nothing is inferred and no urgency is invented: a
record without the value a line needs is left out, never filled in.

  🔴  new violation / complaint / stop-work order since the last brief
  🟡  another DOB status change DOB marks as needing action
  🟠  permit expiring within 14 days, or expired in the last 30
  (inspections: no stored scheduled date exists, so there is no 🔴 line for
   them — none is guessed)

Sort: DOB/regulatory, then permits. At most 7 items in all.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib import wa_gc

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


def is_due(now_utc: datetime, brief_time: Optional[str], saturday: bool) -> bool:
    """Is it this person's brief time today (New York), on a brief day?"""
    if brief_time not in BRIEF_TIMES or brief_time == "off":
        return False
    now = local_now(now_utc)
    wd = now.weekday()  # Mon 0 … Sun 6
    if wd == 6 or (wd == 5 and not saturday):
        return False
    hour = int(brief_time[:2])
    return hour <= now.hour < hour + CATCHUP_HOURS


def clean_settings(stored: Any) -> Dict[str, Any]:
    """{brief_time, brief_saturday} from whatever is stored; defaults
    (7 AM, no Saturday) for anything missing or ill-typed."""
    s = stored if isinstance(stored, dict) else {}
    t = s.get("brief_time")
    return {"brief_time": t if t in BRIEF_TIMES else DEFAULT_TIME,
            "brief_saturday": s.get("brief_saturday") is True}


def header(now_utc: datetime) -> str:
    now = local_now(now_utc)
    return f"Morning — {now.strftime('%a %b')} {now.day}"


# ── What ────────────────────────────────────────────────────────────────────

MAX_ITEMS = 7
PERMIT_SOON_DAYS = 14
EXPIRED_RECENT_DAYS = 30
# "New" also needs DOB's own issue date to be recent: a project's first DOB
# scan stores years of history at once, and none of that is new today.
NEW_ISSUED_WITHIN_DAYS = 30

RANK_REGULATORY = 1
RANK_PERMIT = 2

_CLOSED = ("certified", "dismissed", "paid", "resolved", "closed", "rescinded",
           "resolve", "close")

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
        v = _text(r.get(k)).lower()
        if v and any(v.startswith(c) for c in _CLOSED):
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


def job_items(rows: Iterable[Dict[str, Any]], since: datetime,
              now_utc: datetime) -> List[Dict[str, Any]]:
    """The items one job has today: [{rank, order, text}]. Pure."""
    today = wa_gc.today_et(now_utc)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    items: List[Dict[str, Any]] = []
    for rid, hist in group_records(rows).items():
        first, latest = hist[0], hist[-1]
        rt = _text(latest.get("record_type")).lower()

        # 🔴 new violation / complaint / stop-work order
        if rt in _NEW_KINDS:
            label, num_f, date_f, verb = _NEW_KINDS[rt]
            seen = _detected(first)
            if (seen and seen > since and not first.get("is_seed_transition")
                    and first.get("previous_status") is None):
                num = _text(latest.get(num_f))
                issued = wa_gc.parse_dob_date(latest.get(date_f))
                status = _status(latest)
                if (num and issued and status and not _is_closed(latest)
                        and timedelta(0) <= today - issued
                        <= timedelta(days=NEW_ISSUED_WITHIN_DAYS)):
                    items.append({
                        "rank": RANK_REGULATORY, "order": (0, -issued.toordinal()),
                        "text": f"🔴 New {label} {num}, {verb} {_md(issued)}, {status}. DOB."})
                    continue

        # 🟠 permit expiring / expired
        if rt == "permit":
            if _text(latest.get("permit_status")).upper() == "REVOKED":
                continue
            exp = wa_gc.parse_dob_date(latest.get("expiration_date"))
            num = _text(latest.get("job_number"))
            if not exp or not num:
                continue
            days = (exp - today).days
            work = _text(latest.get("work_type"))
            name = f"Permit {num}" + (f" ({work})" if work else "")
            if 0 <= days <= PERMIT_SOON_DAYS:
                when = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''}"
                items.append({"rank": RANK_PERMIT, "order": (days,),
                              "text": f"🟠 {name} expires {_md(exp)} ({when}). DOB."})
            elif -EXPIRED_RECENT_DAYS <= days < 0:
                ago = -days
                items.append({"rank": RANK_PERMIT, "order": (days,),
                              "text": f"🟠 {name} expired {_md(exp)} "
                                      f"({ago} day{'s' if ago != 1 else ''} ago). DOB."})
            continue

        # 🟡 another status change DOB marks as needing action
        if (len(hist) > 1 and latest.get("previous_status") is not None
                and not latest.get("is_seed_transition")
                and _text(latest.get("severity")) == "Action"
                and _stamp(latest) > since and not _is_closed(latest)):
            num = _text(latest.get(_NUMBER_FIELD.get(rt, "")))
            before = _text(latest.get("previous_status"))
            after = _text(latest.get("current_status"))
            if num and before and after and before != after:
                changed = local_now(_stamp(latest)).date()
                items.append({
                    "rank": RANK_REGULATORY, "order": (1, -changed.toordinal()),
                    "text": f"🟡 {_KIND_LABEL.get(rt, 'Record')} {num} changed "
                            f"{before} → {after} on {_md(changed)}. DOB."})
    items.sort(key=lambda i: (i["rank"], i["order"]))
    return items


# ── Who is on site ──────────────────────────────────────────────────────────

MAX_COMPANIES = 5
NO_COMPANY = "No company"
NO_CHECKINS = "No check-ins yet."


def headcount_line(checkins: Iterable[Dict[str, Any]]) -> str:
    """'On site so far: 12 — ABC Concrete 6, XYZ Plumbing 4, GC 2'. Each
    worker counted once, under the company of their first check-in today."""
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
    if not by_worker:
        return NO_CHECKINS
    counts: Dict[str, int] = {}
    for c in by_worker.values():
        counts[c] = counts.get(c, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    shown = ", ".join(f"{name} {n}" for name, n in ordered[:MAX_COMPANIES])
    more = len(ordered) - MAX_COMPANIES
    tail = f", +{more} more" if more > 0 else ""
    return f"On site so far: {len(by_worker)} — {shown}{tail}"


# ── The message ─────────────────────────────────────────────────────────────

NOTHING_TODAY = "Good morning. No action needed today."


def compose(now_utc: datetime, jobs: List[Dict[str, Any]]) -> str:
    """jobs: [{label, items, headcount}] in display order. At most MAX_ITEMS
    items across all jobs, the most pressing first. A job with items or
    check-ins gets its own block (address, items, headcount); jobs with
    neither are named together: "No check-ins yet: 8 Walworth, 8 Prescott." """
    ranked: List[Tuple[Tuple, int, str]] = []
    for j_idx, job in enumerate(jobs):
        for it in job.get("items") or []:
            ranked.append(((it["rank"], it["order"], j_idx), j_idx, it["text"]))
    ranked.sort(key=lambda t: t[0])
    kept = ranked[:MAX_ITEMS]
    extra = len(ranked) - len(kept)
    per_job: Dict[int, List[str]] = {}
    for _k, j_idx, text in kept:
        per_job.setdefault(j_idx, []).append(text)

    # A job with nothing to do AND nobody on site is not a block of its own:
    # those are named together in one line at the end.
    quiet = [j for j in range(len(jobs))
             if j not in per_job and jobs[j]["headcount"] == NO_CHECKINS]
    lines = [header(now_utc) if kept else NOTHING_TODAY]
    # Jobs with something to do first (in order of their most pressing
    # item), then the rest that have someone on site.
    with_items = sorted(per_job, key=lambda j: min(
        r[0] for r in kept if r[1] == j))
    order = with_items + [j for j in range(len(jobs))
                          if j not in per_job and j not in quiet]
    for j in order:
        lines += ["", jobs[j]["label"]] + per_job.get(j, []) + [jobs[j]["headcount"]]
    if quiet:
        lines += ["", "No check-ins yet: "
                  + ", ".join(jobs[j]["label"] for j in quiet) + "."]
    if extra > 0:
        lines += ["", f"+{extra} more in the Levelog app."]
    return "\n".join(lines)
