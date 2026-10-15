"""A project report for a period: what happened on the job, from its records.

On request ("send me a report for 588 for the last 2 weeks", "monthly report
588", "report all jobs September") and on a schedule (per job: off,
bi-weekly Monday 8 AM, monthly on the 1st at 8 AM). A PDF, a five-line
WhatsApp summary, and a no-login link good for 30 days.

EVIDENCE ONLY. Every number in it is counted here from the rows the server
read for the job and the period -- check-ins, DOB/DOT records, upcoming
events, commitments, punch items, daily logs. Nothing is estimated, and a
section with nothing in it is left out rather than filled. Phone numbers are
never shown (names only; any digits that look like a phone are masked).

Sections (each omitted when empty):
  1 Summary     dates, man-days, avg crew, open issues, changes vs the period before
  2 Manpower    day x sub table, totals, a chart of the daily headcount
  3 Subs        days on site, man-days, first / last day in the period
  4 DOB / DOT   new violations, complaints, permits, hearings -- number + status
  5 Upcoming    inspections, pours, hearings in the next 2 weeks
  6 Commitments made, done, late, still open -- by person
  7 Punch       opened, closed, ready to check, open by assignee, avg days to close
  8 Daily logs  days logged vs days worked, notable entries
  9 Safety      SST cards on file vs unverified (counts)

Pure: no I/O. compute() turns rows into numbers; summary_lines() and
render_html() turn numbers into words.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
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

def _manpower(checkins: List[dict], start: date, end: date) -> Dict[str, Any]:
    days = att.by_day(checkins, start, end)
    table = []
    sub_md: Dict[str, int] = defaultdict(int)
    sub_days: Dict[str, List[date]] = defaultdict(list)
    for d in sorted(days):
        row = {c: len(w) for c, w in days[d].items()}
        for c, n in row.items():
            sub_md[c] += n
            sub_days[c].append(d)
        table.append({"day": d, "by_sub": row, "total": sum(row.values())})
    if not table:
        return {}
    totals = [r["total"] for r in table]
    top = max(totals)
    subs = sorted(sub_md, key=lambda c: (-sub_md[c], c))
    return {
        "days_worked": len(table), "man_days": sum(totals),
        "avg": round(sum(totals) / len(totals), 1), "max": top,
        "max_day": next(r["day"] for r in table if r["total"] == top),
        "table": table, "subs": subs,
        "sub_rows": [{"name": c, "days": len(sub_days[c]), "man_days": sub_md[c],
                      "first": min(sub_days[c]), "last": max(sub_days[c])} for c in subs],
    }


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


def _done_at(it: dict) -> Optional[date]:
    for e in reversed(it.get("history") or []):
        if e.get("to") == "done":
            return _d(e.get("at"))
    return _d(it.get("updated_at")) if it.get("status") == "done" else None


def _commitments(items: List[dict], start: date, end: date) -> Dict[str, Any]:
    made = [i for i in items if _in(_d(i.get("created_at")), start, end)]
    done = [i for i in items if _in(_done_at(i), start, end)]
    still = [i for i in items if i.get("status") in _OPEN and (_d(i.get("created_at")) or date.min) <= end]

    def late(i):
        due = _d((i.get("due") or {}).get("due_at"))
        return due is not None and due < end and i.get("status") in _OPEN
    lates = [i for i in still if late(i)]
    if not (made or done or still):
        return {}
    people: Dict[str, Dict[str, int]] = defaultdict(lambda: {"made": 0, "done": 0, "late": 0, "open": 0})

    def who(i):
        o = i.get("owner") or {}
        return no_phone(o.get("name") or o.get("sub_company") or "No owner yet")
    for key, group in (("made", made), ("done", done), ("late", lates), ("open", still)):
        for i in group:
            people[who(i)][key] += 1
    return {"made": len(made), "done": len(done), "late": len(lates), "open": len(still),
            "by_person": sorted(({"name": k, **v} for k, v in people.items()),
                                key=lambda p: (-p["open"], -p["late"], p["name"]))}


def _punch(items: List[dict], start: date, end: date) -> Dict[str, Any]:
    live = [i for i in items if i.get("status") in ("open", "ready_to_check", "closed")]
    opened = [i for i in live if _in(_d(i.get("assigned_at") or i.get("created_at")), start, end)]
    closed = [i for i in live if i.get("status") == "closed" and _in(_d(i.get("closed_at")), start, end)]
    ready = [i for i in live if i.get("status") == "ready_to_check"]
    still = [i for i in live if i.get("status") == "open"]
    if not (opened or closed or ready or still):
        return {}
    spans = []
    for i in closed:
        a, b = _d(i.get("assigned_at") or i.get("created_at")), _d(i.get("closed_at"))
        if a and b and b >= a:
            spans.append((b - a).days)
    by: Dict[str, int] = defaultdict(int)
    for i in still:
        by[no_phone((i.get("assignee") or {}).get("name") or "Unassigned")] += 1
    return {"opened": len(opened), "closed": len(closed), "ready": len(ready), "open": len(still),
            "avg_days_to_close": round(sum(spans) / len(spans), 1) if spans else None,
            "by_assignee": sorted(({"name": k, "open": v} for k, v in by.items()),
                                  key=lambda x: (-x["open"], x["name"]))}


# Daily logs are the CP's filed daily_jobsite logbooks, adapted by
# lib.logbook.daily_jobsite_source.as_daily_log_row: its observations arrive
# joined in `notes`, and they are the day's notable entries.
_NOTABLE = (("notes", "Observation"),)


def _logs(logs: List[dict], worked: List[date], start: date, end: date) -> Dict[str, Any]:
    logged = sorted({d for d in (_d(lg.get("date")) for lg in logs) if _in(d, start, end)})
    if not logged and not worked:
        return {}
    notable = []
    for lg in sorted(logs, key=lambda x: str(x.get("date") or "")):
        d = _d(lg.get("date"))
        if not _in(d, start, end):
            continue
        for k, label in _NOTABLE:
            v = no_phone(lg.get(k))
            if v and v.lower() not in ("n/a", "na", "none", "no"):
                notable.append({"date": d, "kind": label, "text": v[:240]})
    return {"logged": len(logged), "worked": len(worked),
            "missing": [d for d in worked if d not in set(logged)], "notable": notable[:12]}


def _safety(checkins: List[dict], start: date, end: date) -> Dict[str, Any]:
    latest: Dict[str, Tuple[datetime, str]] = {}
    for r in checkins:
        d = att.local_day(r.get("check_in_time"))
        if not _in(d, start, end):
            continue
        k = att.worker_key(r)
        at = r.get("check_in_time")
        if k not in latest or at > latest[k][0]:
            latest[k] = (at, str(r.get("sst_status") or "missing"))
    if not latest:
        return {}
    on_file = sum(1 for _, s in latest.values() if s in ("valid", "expiring_soon"))
    return {"workers": len(latest), "on_file": on_file, "unverified": len(latest) - on_file}


def compute(*, job: str, address: str, gc: str, start: date, end: date, now: datetime,
            checkins: Iterable[dict] = (), records: Iterable[dict] = (),
            events: Iterable[dict] = (), commitments: Iterable[dict] = (),
            punch_items: Iterable[dict] = (), daily_logs: Iterable[dict] = (),
            prev_checkins: Optional[Iterable[dict]] = None) -> Dict[str, Any]:
    """Every number of one job's report for [start, end]."""
    checkins, events = list(checkins), list(events)
    mp = _manpower(checkins, start, end)
    upcoming_from = max(end, att.local_day(now) or end) + timedelta(days=1)
    rep = {
        "job": job, "address": address, "gc": gc, "start": start, "end": end,
        "period": period_label(start, end), "generated": now,
        "manpower": mp,
        "records": _records(list(records), start, end),
        "hearings": [e for e in _events(events, start, end) if "hearing" in e["kind"].lower()],
        "upcoming": _events(events, upcoming_from, upcoming_from + timedelta(days=UPCOMING_DAYS - 1)),
        "commitments": _commitments(list(commitments), start, end),
        "punch": _punch(list(punch_items), start, end),
        "logs": _logs(list(daily_logs), [r["day"] for r in mp.get("table", [])], start, end),
        "safety": _safety(checkins, start, end),
    }
    if prev_checkins is not None:
        length = (end - start).days + 1
        pmp = _manpower(list(prev_checkins), start - timedelta(days=length), start - timedelta(days=1))
        rep["previous"] = {"man_days": pmp.get("man_days", 0), "avg": pmp.get("avg", 0),
                           "days_worked": pmp.get("days_worked", 0)}
    return rep


# ── WORDS ────────────────────────────────────────────────────────────────────

def _n(x: Any) -> str:
    return str(int(x)) if isinstance(x, float) and x.is_integer() else str(x)


def _change(now_v: float, before: float) -> str:
    if not before:
        return ""
    d = now_v - before
    if d == 0:
        return " (same as the period before)"
    pct = round(100 * d / before)
    return f" ({'+' if d > 0 else ''}{_n(round(d, 1))}, {'+' if pct > 0 else ''}{pct}% vs the period before)"


def open_issues(rep: Dict[str, Any]) -> int:
    return (sum(1 for r in rep["records"] if r["open"]) + rep["commitments"].get("open", 0)
            + rep["punch"].get("open", 0))


def summary_lines(rep: Dict[str, Any]) -> List[str]:
    """Five lines for WhatsApp, every number from the report."""
    mp, prev = rep["manpower"], rep.get("previous") or {}
    head = f"{rep['job']} · {rep['period']}"
    if mp:
        l1 = (f"{head}: {mp['days_worked']} days worked, {mp['man_days']} man-days, "
              f"avg crew {_n(mp['avg'])}{_change(mp['man_days'], prev.get('man_days', 0))}.")
        top = ", ".join(f"{s['name']} {s['man_days']}" for s in mp["sub_rows"][:3])
        l2 = f"Busiest: {_wday(mp['max_day'])} ({mp['max']}). Subs (man-days): {top}."
    else:
        l1, l2 = f"{head}: no check-ins in this period.", "Manpower: nothing recorded."
    recs = rep["records"]
    if recs:
        kinds: Dict[str, int] = defaultdict(int)
        for r in recs:
            kinds[r["kind"]] += 1
        l3 = "DOB/DOT: " + ", ".join(f"{n} new {k}{'s' if n != 1 else ''}"
                                     for k, n in sorted(kinds.items())) + "."
    else:
        l3 = "DOB/DOT: nothing new."
    c, p = rep["commitments"], rep["punch"]
    oc, op = c.get("open", 0), p.get("open", 0)
    late = " ({} late)".format(c["late"]) if c.get("late") else ""
    ready = ", {} ready to check".format(p["ready"]) if p.get("ready") else ""
    l4 = (f"Open: {oc} commitment{'s' if oc != 1 else ''}{late}, "
          f"{op} punch item{'s' if op != 1 else ''}{ready}.")
    lg = rep["logs"]
    l5 = (f"Daily logs: {lg['logged']} of {lg['worked']} worked days."
          if lg else "Daily logs: none in this period.")
    return [l1, l2, l3, l4, l5]


# ── THE PDF (HTML for WeasyPrint) ────────────────────────────────────────────

def _e(v: Any) -> str:
    return html.escape(no_phone(v))


def chart_svg(table: List[Dict[str, Any]], width: int = 680, height: int = 120) -> str:
    """The daily headcount as bars (inline SVG): one bar a day, its count on top."""
    if not table:
        return ""
    top = max(r["total"] for r in table) or 1
    n = len(table)
    gap = 4
    bw = max(4, (width - 30 - gap * n) // n)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height + 34}" '
             f'viewBox="0 0 {width} {height + 34}" class="chart">']
    for i, r in enumerate(table):
        h = round((height - 20) * r["total"] / top)
        x = 24 + i * (bw + gap)
        y = height - h
        parts.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{h}" fill="#1F3A5F"/>')
        parts.append(f'<text x="{x + bw / 2}" y="{y - 4}" font-size="9" text-anchor="middle" '
                     f'fill="#1F3A5F">{r["total"]}</text>')
        if n <= 31:
            parts.append(f'<text x="{x + bw / 2}" y="{height + 14}" font-size="8" text-anchor="middle" '
                         f'fill="#555">{_fmt(r["day"], "%-m/%-d")}</text>')
    parts.append(f'<line x1="20" y1="{height}" x2="{width}" y2="{height}" stroke="#999" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)


CSS = """
@page { size: Letter; margin: 0.6in 0.55in 0.75in;
  @bottom-left { content: "SOURCE"; font: 8pt Helvetica, Arial, sans-serif; color: #666; }
  @bottom-center { content: "GENERATED"; font: 8pt Helvetica, Arial, sans-serif; color: #666; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 8pt Helvetica, Arial, sans-serif; color: #666; } }
body { font: 9.5pt/1.35 Helvetica, Arial, sans-serif; color: #1a1a1a; }
.mast { display: flex; justify-content: space-between; align-items: baseline;
        border-bottom: 2px solid #1F3A5F; padding-bottom: 6px; margin-bottom: 10px; }
.brand { font-weight: 800; letter-spacing: 1px; color: #1F3A5F; font-size: 15pt; }
.gc { font-weight: 700; font-size: 11pt; }
h1 { font-size: 15pt; margin: 4px 0 2px; } .sub { color: #555; margin-bottom: 12px; }
h2 { font-size: 11.5pt; color: #1F3A5F; border-bottom: 1px solid #ccd; padding-bottom: 2px;
     margin: 16px 0 6px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 4px 0 8px; }
th, td { border: 1px solid #d6d9e0; padding: 3px 5px; text-align: left; font-size: 8.5pt; }
th { background: #eef1f6; } td.n, th.n { text-align: right; }
tr.total td { font-weight: 700; background: #f6f7fa; }
ul { margin: 2px 0 6px 16px; padding: 0; } li { margin: 1px 0; }
.kpi { display: flex; gap: 10px; margin: 6px 0; } .kpi div { border: 1px solid #d6d9e0; padding: 6px 8px;
       border-radius: 4px; min-width: 90px; } .kpi b { display: block; font-size: 13pt; color: #1F3A5F; }
.job { page-break-before: always; } .job.first { page-break-before: auto; }
.keep { break-inside: avoid; page-break-inside: avoid; }
thead { display: table-header-group; } tr { page-break-inside: avoid; }
.muted { color: #666; }
"""


def _section_summary(rep: Dict[str, Any]) -> str:
    mp, prev = rep["manpower"], rep.get("previous") or {}
    k = []
    if mp:
        k += [("Days worked", mp["days_worked"]), ("Man-days", mp["man_days"]),
              ("Avg crew", _n(mp["avg"])), ("Busiest", f"{mp['max']} · {_day(mp['max_day'])}")]
    k.append(("Open issues", open_issues(rep)))
    kpis = "".join(f"<div><b>{_e(v)}</b>{_e(lbl)}</div>" for lbl, v in k)
    changes = []
    if mp and prev.get("man_days"):
        changes.append(f"Man-days {mp['man_days']} vs {prev['man_days']} the period before"
                       f"{_change(mp['man_days'], prev['man_days']).replace(' vs the period before', '')}.")
        changes.append(f"Average crew {_n(mp['avg'])} vs {_n(prev['avg'])}.")
    elif mp and prev and not prev.get("man_days"):
        changes.append("No check-ins in the period before.")
    if rep["records"]:
        changes.append(f"{len(rep['records'])} new DOB/DOT record{'s' if len(rep['records']) != 1 else ''}.")
    if rep["punch"].get("closed"):
        changes.append(f"{rep['punch']['closed']} punch item{'s' if rep['punch']['closed'] != 1 else ''} closed.")
    ch = ("<ul>" + "".join(f"<li>{_e(c)}</li>" for c in changes) + "</ul>") if changes else ""
    return f"<h2>1. Summary</h2><div class='kpi'>{kpis}</div>{ch}"


def _section_manpower(rep: Dict[str, Any]) -> str:
    mp = rep["manpower"]
    if not mp:
        return ""
    subs = mp["subs"]
    head = "<tr><th>Day</th>" + "".join(f"<th class='n'>{_e(s)}</th>" for s in subs) + "<th class='n'>Total</th></tr>"
    rows = []
    for r in mp["table"]:
        rows.append(f"<tr><td>{_e(_wday(r['day']))}</td>"
                    + "".join(f"<td class='n'>{r['by_sub'].get(s, '') or ''}</td>" for s in subs)
                    + f"<td class='n'>{r['total']}</td></tr>")
    tot = ("<tr class='total'><td>Total man-days</td>"
           + "".join(f"<td class='n'>{sr['man_days']}</td>" for sr in mp["sub_rows"])
           + f"<td class='n'>{mp['man_days']}</td></tr>")
    return (f"<h2>2. Manpower</h2>{chart_svg(mp['table'])}"
            f"<table>{head}{''.join(rows)}{tot}</table>"
            f"<div class='muted'>Workers counted once per day from check-ins. "
            f"{mp['days_worked']} days worked, {mp['man_days']} man-days, average crew {_n(mp['avg'])}.</div>")


def _section_subs(rep: Dict[str, Any]) -> str:
    mp = rep["manpower"]
    if not mp:
        return ""
    rows = "".join(f"<tr><td>{_e(s['name'])}</td><td class='n'>{s['days']}</td>"
                   f"<td class='n'>{s['man_days']}</td><td>{_e(_day(s['first']))}</td>"
                   f"<td>{_e(_day(s['last']))}</td></tr>" for s in mp["sub_rows"]) 
    return ("<div class='keep'><h2>3. Subs</h2><table><tr><th>Sub</th><th class='n'>Days on site</th>"
            f"<th class='n'>Man-days</th><th>First day</th><th>Last day</th></tr>{rows}</table></div>")


def _section_dob(rep: Dict[str, Any]) -> str:
    recs, hear = rep["records"], rep["hearings"]
    if not recs and not hear:
        return ""
    out = ["<h2>4. DOB / DOT</h2>"]
    if recs:
        out.append("<table><tr><th>Type</th><th>Number</th><th>Date</th><th>Status</th></tr>"
                   + "".join(f"<tr><td>{_e(r['kind'])}</td><td>{_e(r['number'])}</td>"
                             f"<td>{_e(_day(r['date']))}</td><td>{_e(r['status'])}</td></tr>" for r in recs)
                   + "</table>")
    if hear:
        out.append("<b>Hearings in the period</b><ul>"
                   + "".join(f"<li>{_e(_wday(h['date']))} {_e(h['time'])} — {_e(h['title'])}"
                             f"{(' (' + _e(h['agency']) + ')') if h['agency'] else ''}</li>" for h in hear)
                   + "</ul>")
    return "".join(out)


def _section_upcoming(rep: Dict[str, Any]) -> str:
    up = rep["upcoming"]
    if not up:
        return ""
    return ("<h2>5. Upcoming (next 2 weeks)</h2><ul>"
            + "".join(f"<li>{_e(_wday(e['date']))}{(' ' + _e(e['time'])) if e['time'] else ''} — "
                      f"{_e(e['title'])}{(' (' + _e(e['agency']) + ')') if e['agency'] else ''}</li>" for e in up)
            + "</ul>")


def _section_commitments(rep: Dict[str, Any]) -> str:
    c = rep["commitments"]
    if not c:
        return ""
    rows = "".join(f"<tr><td>{_e(p['name'])}</td><td class='n'>{p['made']}</td><td class='n'>{p['done']}</td>"
                   f"<td class='n'>{p['late']}</td><td class='n'>{p['open']}</td></tr>" for p in c["by_person"])
    return ("<div class='keep'><h2>6. Commitments</h2>"
            f"<div>{c['made']} made, {c['done']} done, {c['late']} late, {c['open']} still open.</div>"
            "<table><tr><th>Person</th><th class='n'>Made</th><th class='n'>Done</th>"
            f"<th class='n'>Late</th><th class='n'>Open</th></tr>{rows}</table></div>")


def _section_punch(rep: Dict[str, Any]) -> str:
    p = rep["punch"]
    if not p:
        return ""
    avg = (f" Average {_n(p['avg_days_to_close'])} days to close."
           if p.get("avg_days_to_close") is not None else "")
    rows = "".join(f"<tr><td>{_e(a['name'])}</td><td class='n'>{a['open']}</td></tr>" for a in p["by_assignee"])
    table = (f"<table><tr><th>Assignee</th><th class='n'>Open</th></tr>{rows}</table>" if rows else "")
    return (f"<div class='keep'><h2>7. Punch</h2><div>{p['opened']} opened, {p['closed']} closed, {p['ready']} ready to "
            f"check, {p['open']} open.{avg}</div>{table}</div>")


def _section_logs(rep: Dict[str, Any]) -> str:
    lg = rep["logs"]
    if not lg:
        return ""
    miss = (f" Not logged: {_e(', '.join(_day(d) for d in lg['missing'][:20]))}"
            f"{'…' if len(lg['missing']) > 20 else ''}." if lg["missing"] else "")
    notes = ("<ul>" + "".join(f"<li>{_e(_day(n['date']))} · {_e(n['kind'])}: {_e(n['text'])}</li>"
                              for n in lg["notable"]) + "</ul>") if lg["notable"] else ""
    return f"<h2>8. Daily logs</h2><div>{lg['logged']} of {lg['worked']} worked days logged.{miss}</div>{notes}"


def _section_safety(rep: Dict[str, Any]) -> str:
    s = rep["safety"]
    if not s:
        return ""
    return (f"<div class='keep'><h2>9. Safety</h2><div>{s['workers']} workers checked in: SST card on file for "
            f"{s['on_file']}, unverified for {s['unverified']}.</div></div>")


def render_job(rep: Dict[str, Any], first: bool = True) -> str:
    return (f"<section class='job{' first' if first else ''}'>"
            f"<h1>{_e(rep['job'])}</h1><div class='sub'>{_e(rep['address'])} · {_e(rep['period'])}</div>"
            + _section_summary(rep) + _section_manpower(rep) + _section_subs(rep) + _section_dob(rep)
            + _section_upcoming(rep) + _section_commitments(rep) + _section_punch(rep)
            + _section_logs(rep) + _section_safety(rep) + "</section>")


def render_html(reports: List[Dict[str, Any]], *, gc: str, title: str, now: datetime) -> str:
    """The whole PDF's HTML: the Levelog masthead with the GC's name, one
    section per job, page numbers, the generated time and the source line."""
    gen = _fmt(now.astimezone(NY), "Generated %b %-d, %Y %-I:%M %p ET")
    css = CSS.replace('"SOURCE"', f'"{SOURCE_LINE}"').replace('"GENERATED"', f'"{gen}"')
    cover = ""
    if len(reports) > 1:
        rows = "".join(
            f"<tr><td>{_e(r['job'])}</td><td class='n'>{r['manpower'].get('days_worked', 0)}</td>"
            f"<td class='n'>{r['manpower'].get('man_days', 0)}</td><td class='n'>{open_issues(r)}</td></tr>"
            for r in reports)
        cover = ("<h2>All jobs</h2><table><tr><th>Job</th><th class='n'>Days worked</th>"
                 f"<th class='n'>Man-days</th><th class='n'>Open issues</th></tr>{rows}</table>")
    body = "".join(render_job(r, first=(i == 0 and not cover)) for i, r in enumerate(reports))
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(title)}</title>"
            f"<style>{css}</style></head><body>"
            f"<div class='mast'><span class='brand'>LEVELOG</span><span class='gc'>{_e(gc)}</span></div>"
            f"<div class='sub'>{_e(title)}</div>{cover}{body}</body></html>")


def title_for(reports: List[Dict[str, Any]]) -> str:
    if len(reports) == 1:
        return f"Project report — {reports[0]['job']} — {reports[0]['period']}"
    return f"Project report — {len(reports)} jobs — {reports[0]['period']}"


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
