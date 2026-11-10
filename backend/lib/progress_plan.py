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

NO PRODUCTION RATE, NO ESTIMATE (owner ruling, 2026-11-09). Activity dates, a
crew reported on one floor and then another, and how often photos were taken
are NOT proof of a production rate, so none is computed here and no date is
derived from one. (A days-per-level rate from "levels the crew moved on from"
lived here and was removed by that ruling.) What the lookahead states is
VERIFIED FACTS ONLY, kept apart in the data and in the words:
  * the file's dates: planned (current, else baseline, and which) and the
    file's own stated actual start / finish;
  * the file's own logic: each activity's predecessors as the confirmed file
    links them (`depends_on`), None when the file carries no logic (unknown,
    never "no dependencies"), and how many links could not be resolved;
  * reported: the first and last day a filed log names that work on that level.
Nothing is estimated, so there is no estimate field; one added later must be
its own field, labelled "estimate, not verified", never mixed into these.

A PROPOSED SEQUENCE is what to do where no baseline exists: graph_v1's order, for
the levels the logs name, in the order the logs first name them. It is the
template laid over the job's levels, so it is labelled PROPOSED in every answer
and is never written to project_schedules. It stays PROPOSED after a person
approves it: approval makes it the sequence they agreed to, not a schedule file.
"""

from __future__ import annotations

import heapq
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.scheduling.graph_v1 import build_graph_v1
from lib import work_state as W
from lib.plans import level_suggestion as LS

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


# ── LOOKAHEAD ──────────────────────────────────────────────────────────────

def _planned_span(a: Dict[str, Any]) -> Tuple[Optional[date], Optional[date], str]:
    s, f = _iso(a.get("current_start")), _iso(a.get("current_finish"))
    if s or f:
        return s, f, "current"
    return _iso(a.get("baseline_start")), _iso(a.get("baseline_finish")), "baseline"


def depends_on(a: Dict[str, Any], by_id: Dict[str, Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """This activity's predecessors AS THE CONFIRMED FILE LINKS THEM: the
    project's own logic, never the standard template's. None: the file
    carries no logic for it (unknown, not "no dependencies"); []: the file
    lists none. Each link: the predecessor's id and name, the link's type and
    lag as the file states them (None where it states none), and the
    predecessor's actual finish if the file states one."""
    links = a.get("predecessors")
    if not isinstance(links, list):
        return None
    out = []
    for link in links:
        p = by_id.get(str(link.get("id"))) or {}
        out.append({"id": link.get("id"), "name": p.get("name") or str(link.get("id")), "type": link.get("type"),
                    "lag": link.get("lag"), "lag_unit": link.get("lag_unit"),
                    "finished_per_file": p.get("actual_finish")})
    return out


def lookahead(schedule: Dict[str, Any], rows: Sequence[Row], *, today: date, days: int) -> Dict[str, Any]:
    """Activities the CONFIRMED file plans in the next 7 or 14 days. Any `days`
    other than 14 is read as 7. Facts only: the file's dates, the file's own
    links, and the reported days; no rate and no estimated date."""
    days = 14 if days == 14 else 7
    until = today + timedelta(days=days)
    items: List[Dict[str, Any]] = []
    undated = 0
    by_id = {str(a.get("id")): a for a in (schedule or {}).get("activities") or []}
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
        items.append({"id": a.get("id"), "name": a.get("name"), "kind": a.get("kind"),
                      # the file's dates, as stated in it
                      "planned_start": start, "planned_finish": finish, "planned_source": source,
                      "started_per_file": bool(a.get("actual_start")), "actual_start_per_file": a.get("actual_start"),
                      # the file's own logic
                      "depends_on": depends_on(a, by_id),
                      "depends_unresolved": int(a.get("predecessors_unresolved") or 0),
                      # what the filed logs report
                      "first_reported": report_days[0] if report_days else None,
                      "last_reported": report_days[-1] if report_days else None,
                      "report_days": len(report_days)})
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
        started = f"; actual start per the file {i['actual_start_per_file']}" if i["actual_start_per_file"] else ""
        rep = (f"reported in the logs {_day(i['first_reported'])} to {_day(i['last_reported'])}, {i['report_days']} day(s)"
               if i["first_reported"] else "no report in the logs read")
        out.append(f"- {i['name']} ({i['id']}). FILE: planned {when}{started}. LOGIC: {_depends_words(i)}. "
                   f"REPORTED: {rep}.")
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
    out.append(LOOKAHEAD_RULE)
    return "\n".join(out)


#: The lookahead's closing line. lib/forecast.py replaces it, whole, when it
#: adds a labelled estimate after the lookahead.
LOOKAHEAD_RULE = ("FILE dates and LOGIC are the confirmed schedule's own; REPORTED is the filed logs. Keep them apart. "
                  "No production rate or estimated finish is made: activity dates, a crew moving between floors and photo "
                  "counts are not proof of a rate. Do not give a forecast, a rate, a percent complete, a delay or a cause: "
                  "none is on record.")


_LAG_UNITS = {"days": "working days", "edays": "calendar days", "percent": "%"}


def _depends_words(i: Dict[str, Any]) -> str:
    """The file's links into one activity, in words."""
    deps = i["depends_on"]
    if deps is None:
        return "the file carries no predecessor logic for it (unknown, not 'no dependencies')"
    if not deps and not i["depends_unresolved"]:
        return "the file lists no predecessor"
    bits = []
    for d in deps[:6]:
        link = d["type"] or "type not stated"
        if d["lag"] is not None:
            link += f", lag {d['lag']:g} {_LAG_UNITS.get(str(d['lag_unit']), '')}".rstrip()
        done = f", actual finish per the file {d['finished_per_file']}" if d["finished_per_file"] else ""
        bits.append(f"{d['name']} ({link}{done})")
    more = f" and {len(deps) - 6} more" if len(deps) > 6 else ""
    lost = (f"; {i['depends_unresolved']} more link(s) in the file could not be matched, so this list is not complete"
            if i["depends_unresolved"] else "")
    return "after " + "; ".join(bits) + more + lost if bits else lost.lstrip("; ")


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
