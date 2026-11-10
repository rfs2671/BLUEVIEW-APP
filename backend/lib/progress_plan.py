"""Plan versus actual, a 7/14-day lookahead, and a PROPOSED sequence.

Pure: no database, no network. The server hands in the CONFIRMED schedule
document (lib/schedule_import.py) and the rows of work_state.evidence_rows. The
vocabulary of work_state holds here too: reported is what a filed log says, and
nothing below says what is finished, how far along anything is, or why anything
moved. No percent is computed anywhere in this module.

PLANNED DATES are the file's: current_* and baseline_* side by side, with the
planned finish being current_finish, else baseline_finish (the rule
lib/schedule_plan.py uses).

"PAST PLANNED FINISH WITH NO REPORT" is a sentence about two records: the file's
date has gone by, and no log in the window read names that work on that level.
It is only ever said for a date inside the window (an older date could have
been reported before the logs read begin), for an activity that maps to a kind
of work and a level, and with no cause.

THE RATE. Logs name a floor, not a quantity, so a rate is days per level and
needs levels that were plainly left behind. A level counts only when every row
for that work there names it alone (a "floors 1-4" row or a trade-only row
spoils it), and the crew has since been reported on another level, and its last
report is older than work_state.REPORTED_RECENT_DAYS. That is NOT completion: it
is the only signal the logs hold, and it is called a rate, never a finish. With
fewer than MIN_RATE_LEVELS such levels the rate is unknown and says so.

A PROPOSED SEQUENCE is what to do where no baseline exists: graph_v1's order, for
the levels the logs name, in the order the logs first name them. It is the
template laid over the job's levels, so it is labelled PROPOSED in every answer
and is never written to project_schedules. It stays PROPOSED after a person
approves it: approval makes it the sequence they agreed to, not a schedule file.
"""

from __future__ import annotations

import heapq
import statistics
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.scheduling.graph_v1 import build_graph_v1
from lib import work_state as W
from lib.plans import level_suggestion as LS

MIN_RATE_LEVELS = 3
LOOKAHEAD_DAYS = (7, 14)
MAX_LOOKAHEAD_ITEMS = 12
MAX_PAST_ITEMS = 8

Row = Dict[str, Any]


def _iso(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _day(d: Optional[date]) -> str:
    return f"{d:%b} {d.day}" if d else ""


def activity_place(a: Dict[str, Any]) -> Dict[str, Any]:
    """(node, level) of a schedule activity, by the same whole-word readers the
    logs go through, on its NAME alone."""
    nodes, generic = W.classify(a.get("name"), a.get("name"))
    return {"nodes": nodes, "levels": W.places_in(a.get("name"))["levels"], "generic": generic}


def _activities(schedule: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [a for a in (schedule or {}).get("activities") or [] if a.get("kind") != "summary"]


def _reports(rows: Sequence[Row], place: Dict[str, Any]) -> List[Row]:
    return [r for r in rows if set(r["nodes"]) & set(place["nodes"]) and set(r["levels"]) & set(place["levels"])]


# ── PLAN VERSUS ACTUAL ─────────────────────────────────────────────────────

def plan_vs_actual(schedule: Optional[Dict[str, Any]], rows: Sequence[Row], *, today: date, logs_from: date) -> Dict[str, Any]:
    """One row per activity that names a kind of work and a level: the file's
    planned and actual dates beside the first and last dates the logs report."""
    out: List[Dict[str, Any]] = []
    unmapped = 0
    for a in _activities(schedule):
        place = activity_place(a)
        if not place["nodes"] or not place["levels"]:
            unmapped += 1
            continue
        days = sorted({r["date"] for r in _reports(rows, place)})
        out.append({"id": a.get("id"), "name": a.get("name"), "nodes": place["nodes"], "levels": place["levels"],
                    "baseline_start": a.get("baseline_start"), "baseline_finish": a.get("baseline_finish"),
                    "current_start": a.get("current_start"), "current_finish": a.get("current_finish"),
                    "planned_finish": W.planned_finish(a),
                    "file_actual_start": a.get("actual_start"), "file_actual_finish": a.get("actual_finish"),
                    "first_reported": days[0] if days else None, "last_reported": days[-1] if days else None,
                    "report_days": len(days),
                    "past_planned_no_report": W.past_planned_no_report(a, bool(days), today, logs_from)})
    return {"rows": out, "unmapped": unmapped, "data_date": (schedule or {}).get("data_date"), "logs_from": logs_from}


# ── THE RATE ───────────────────────────────────────────────────────────────

def production_rate(node: str, rows: Sequence[Row], today: date) -> Dict[str, Any]:
    """{"levels": n, "days_per_level": int|None}: None is an unknown rate."""
    mine = [r for r in rows if node in r["nodes"] and r["levels"]]
    spoiled = {lv for r in mine if r["generic"] or len(r["levels"]) > 1 for lv in r["levels"]}
    by_level: Dict[str, set] = {}
    for r in mine:
        if len(r["levels"]) == 1 and r["levels"][0] not in spoiled:
            by_level.setdefault(r["levels"][0], set()).add(r["date"])
    done: Dict[str, int] = {}
    for level, days in by_level.items():
        last = max(days)
        moved_on = any(d > last for other, ds in by_level.items() if other != level for d in ds)
        if moved_on and (today - last).days > W.REPORTED_RECENT_DAYS:
            done[level] = len(days)
    if len(done) < MIN_RATE_LEVELS:
        return {"levels": len(done), "days_per_level": None}
    return {"levels": len(done), "days_per_level": int(statistics.median(done.values()) + 0.5)}


def _add_workdays(start: date, days: int) -> date:
    """`days` working days counting `start` (Mon-Fri; the file's calendar is
    not carried here)."""
    d = start
    while d.weekday() >= 5:
        d += timedelta(days=1)
    left = days - 1
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


# ── LOOKAHEAD ──────────────────────────────────────────────────────────────

def _planned_span(a: Dict[str, Any]) -> Tuple[Optional[date], Optional[date], str]:
    s, f = _iso(a.get("current_start")), _iso(a.get("current_finish"))
    if s or f:
        return s, f, "current"
    return _iso(a.get("baseline_start")), _iso(a.get("baseline_finish")), "baseline"


def _rate_for(a: Dict[str, Any], place: Dict[str, Any], rows: Sequence[Row], start: Optional[date], today: date) -> Dict[str, Any]:
    """The rate line for one activity, and the date it implies when it can be
    stated. Beside the file's date, never instead of it."""
    unknown = {"rate": None, "finish_at_rate": None, "rate_words": "Rate unknown."}
    if place["generic"] or len(place["nodes"]) != 1 or len(place["levels"]) != 1:
        return unknown
    rate = production_rate(place["nodes"][0], rows, today)
    if rate["days_per_level"] is None:
        return {**unknown, "rate_words": f"Rate unknown ({rate['levels']} level(s) reported alone; needs {MIN_RATE_LEVELS})."}
    n, k = rate["days_per_level"], rate["levels"]
    words = f"Reported rate about {n} crew day(s) per level, over {k} levels."
    first = min((r["date"] for r in _reports(rows, place)), default=None)
    begun = _iso(a.get("actual_start")) or first or start
    if begun is None:
        return {"rate": rate, "finish_at_rate": None, "rate_words": words + " No start date to apply it to."}
    at_rate = _add_workdays(begun, n)
    if at_rate < today:
        return {"rate": rate, "finish_at_rate": None,
                "rate_words": words + " At that rate the date is already past, and nothing on record says it finished, so no date is given."}
    return {"rate": rate, "finish_at_rate": at_rate,
            "rate_words": words + f" At that rate, about {_day(at_rate)}. An estimate from the logs, not the file's date."}


def lookahead(schedule: Dict[str, Any], rows: Sequence[Row], *, today: date, days: int) -> Dict[str, Any]:
    """Activities the CONFIRMED file plans in the next 7 or 14 days. Any `days`
    other than 14 is read as 7."""
    days = 14 if days == 14 else 7
    until = today + timedelta(days=days)
    items: List[Dict[str, Any]] = []
    undated = 0
    for a in _activities(schedule):
        if a.get("actual_finish"):
            continue
        start, finish, source = _planned_span(a)
        if not start and not finish:
            undated += 1
            continue
        low, high = start or finish, finish or start
        if low > until or high < today:
            continue
        place = activity_place(a)
        reports = _reports(rows, place) if place["nodes"] and place["levels"] else []
        report_days = sorted({r["date"] for r in reports})
        items.append({"id": a.get("id"), "name": a.get("name"), "kind": a.get("kind"), "planned_start": start,
                      "planned_finish": finish, "planned_source": source, "started_per_file": bool(a.get("actual_start")),
                      "first_reported": report_days[0] if report_days else None,
                      "last_reported": report_days[-1] if report_days else None,
                      **_rate_for(a, place, rows, start, today)})
    items.sort(key=lambda i: (i["planned_start"] or i["planned_finish"], str(i["name"])))
    data_date = _iso((schedule or {}).get("data_date"))
    return {"days": days, "from": today, "until": until, "items": items, "undated": undated,
            "data_date": data_date, "file_age_days": (today - data_date).days if data_date else None}


def lookahead_text(schedule: Dict[str, Any], rows: Sequence[Row], *, today: date, days: int, logs_from: date) -> str:
    """For the assistant: every figure it may repeat is printed here."""
    la = lookahead(schedule, rows, today=today, days=days)
    pva = plan_vs_actual(schedule, rows, today=today, logs_from=logs_from)
    head = (f"From the confirmed schedule file, data date {la['data_date'].isoformat()} ({la['file_age_days']} days old)."
            if la["data_date"] else "From the confirmed schedule file, which states no data date.")
    out = [head, f"Planned in the next {la['days']} days, through {_day(la['until'])}:"]
    if not la["items"]:
        out.append("Nothing in the file is planned in that window.")
    for i in la["items"][:MAX_LOOKAHEAD_ITEMS]:
        when = f"{i['planned_source']} {i['planned_start'] or 'no start'} to {i['planned_finish'] or 'no finish'}"
        rep = (f"reported {_day(i['first_reported'])} to {_day(i['last_reported'])}" if i["first_reported"]
               else "no report in the logs read")
        out.append(f"- {i['name']} ({i['id']}): {when}; {'started per the file; ' if i['started_per_file'] else ''}{rep}. {i['rate_words']}")
    if len(la["items"]) > MAX_LOOKAHEAD_ITEMS:
        out.append(f"...and {len(la['items']) - MAX_LOOKAHEAD_ITEMS} more.")
    if la["undated"]:
        out.append(f"{la['undated']} activities in the file have no planned date and are not listed.")
    past = [r for r in pva["rows"] if r["past_planned_no_report"]]
    if past:
        out.append(f"Past the file's planned finish with no report of that work on that level in the logs read since {_day(logs_from)}:")
        out += [f"- {r['name']} ({r['id']}): planned finish {r['planned_finish']}" for r in past[:MAX_PAST_ITEMS]]
        if len(past) > MAX_PAST_ITEMS:
            out.append(f"...and {len(past) - MAX_PAST_ITEMS} more.")
    out.append("State the dates as the file's. Do not give a percent complete, a delay or a cause: none is on record.")
    return "\n".join(out)


# ── A PROPOSED SEQUENCE ────────────────────────────────────────────────────

def _level_order(level: str) -> Tuple[int, int]:
    """Bottom of the building to the top."""
    named = {LS.SUB_CELLAR: 0, LS.CELLAR: 1, LS.FOUNDATION: 2, LS.GROUND: 3}
    if level in named:
        return named[level], 0
    if level.startswith(LS.FLOOR_PREFIX):
        return 4, int(level[len(LS.FLOOR_PREFIX):])
    return {LS.MEZZANINE: 5, LS.ROOF: 6, LS.BULKHEAD: 7}.get(level, 8), 0


def _per_level_nodes(flags: Optional[Dict[str, Any]]) -> List[Any]:
    """graph_v1's nodes that happen on a level, in dependency order. Whole-
    building gates and the TCO cluster are not a floor's work. A system the
    building is not KNOWN to lack is kept."""
    g = build_graph_v1()
    known = flags or {}
    keep = [n for n in g.nodes if not (W._is_gate(n) and n.is_global) and n.id != "tco_zone"
            and not n.id.startswith("gate_ls_") and not any(known.get(r) is False for r in n.requires)]
    rank = {n.id: i for i, n in enumerate(keep)}
    after: Dict[str, List[str]] = {i: [] for i in rank}
    waiting = {i: 0 for i in rank}
    for e in g.edges:
        if e.from_node in rank and e.to_node in rank:
            after[e.from_node].append(e.to_node)
            waiting[e.to_node] += 1
    ready = [(rank[i], i) for i, c in waiting.items() if c == 0]
    heapq.heapify(ready)
    ordered: List[str] = []
    while ready:
        _r, i = heapq.heappop(ready)
        ordered.append(i)
        for j in after[i]:
            waiting[j] -= 1
            if waiting[j] == 0:
                heapq.heappush(ready, (rank[j], j))
    by_id = {n.id: n for n in keep}
    return [by_id[i] for i in ordered]


def propose_sequence(rows: Iterable[Row], flags: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """{"graph_version", "levels": [{"level", "label", "first_reported",
    "steps": [{"id", "label", "gate", "conditional", "first_reported"}]}]}.
    Levels are the ones the logs name, earliest report first; dates are ISO
    strings so the document can be stored as it is."""
    rows = list(rows)
    firsts: Dict[str, date] = {}
    step_first: Dict[Tuple[str, str], date] = {}
    for r in rows:
        for lv in r["levels"]:
            firsts[lv] = min(firsts.get(lv, r["date"]), r["date"])
            for n in r["nodes"]:
                step_first[(lv, n)] = min(step_first.get((lv, n), r["date"]), r["date"])
    nodes = _per_level_nodes(flags)
    levels = []
    for lv in sorted(firsts, key=lambda x: (firsts[x], _level_order(x))):
        steps = []
        for n in nodes:
            gate = W._is_gate(n)
            label = W._GATE_WORDS.get(n.inspection_type, n.inspection_type.replace("_", " ")) if gate else W.node_label(n.id)
            seen = step_first.get((lv, n.id))
            steps.append({"id": n.id, "label": label, "gate": gate, "conditional": bool(n.requires),
                          "first_reported": seen.isoformat() if seen else None})
        levels.append({"level": lv, "label": W.level_label(lv), "first_reported": firsts[lv].isoformat(), "steps": steps})
    return {"graph_version": build_graph_v1().version, "levels": levels}


def proposed_text(doc: Dict[str, Any], job: str) -> str:
    """One short message: what the sequence is, and how to approve it. Every
    answer says PROPOSED, including after approval."""
    levels = doc.get("levels") or []
    if not levels:
        return "PROPOSED sequence: the logs do not name a level yet, so there is nothing to propose."
    approved = doc.get("status") == "approved"
    head = f"PROPOSED sequence for {job}, built from the standard sequence and the levels your logs name. It is not a schedule."
    if approved:
        when = _iso(doc.get("approved_at"))
        by = doc.get("approved_by_name")
        head += " Approved" + (f" by {by}" if by else "") + (f" on {_day(when)}." if when else ".")
    order = " > ".join(s["label"] + ("*" if s["conditional"] else "") for s in levels[0]["steps"])
    where = ", ".join(f"{lv['label']} ({_day(_iso(lv['first_reported']))})" for lv in levels[:30])
    lines = [head, f"Order on each level: {order}.", "* if the building has this system.",
             f"Levels, in the order the logs first name them: {where}."]
    if not approved:
        lines.append('Not approved. To approve it, say "approve the sequence".')
    return "\n".join(lines)


def history_entry(action: str, by: str, role: Optional[str], at: Any, replaced: Optional[list] = None) -> Dict[str, Any]:
    """One line of the append-only history. A rebuild keeps what it replaced."""
    entry: Dict[str, Any] = {"action": action, "by": by, "role": role, "at": at}
    if replaced is not None:
        entry["replaced_levels"] = replaced
    return entry
