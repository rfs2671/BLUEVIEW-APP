"""What the records say about a piece of work at a place in the building.

    "What's holding up drywall on Floor 3?"

Pure: no database, no network. The server hands in what the progress report
already loads (filed daily-log heads, DOB records, the confirmed schedule) and
the photo index. Nothing here is stored, so there is no second copy of the
evidence to drift from the logs.

A PLACE is (project, level token, optional space), using the closed token set
of lib/plans/level_suggestion.py: the one vocabulary the plan readers share. A
log row saying "floors 1-4" is evidence about four levels and is SHARED: it is
never reported as if it were about floor 3 alone.

THE FOUR WORDS ARE KEPT APART
  reported   a filed daily log says this crew did this work there
  observed   a photo filed for that place is described as showing it
  verified   a record proves it. No such record exists in Levelog today for an
             inspection or for installed work, so this is empty, and it stays
             empty until one does. A photo never verifies anything.
  unknown    nothing on record. NOT the same as not done.

NO PERCENT is ever computed: nothing in the system holds a measured scope and a
verified installed quantity. A percent is shown only when a confirmed schedule
file states one, and it is labelled as the file's.

THE SEQUENCE is the job's OWN logic when a confirmed schedule file carries
predecessors for this activity, and the answer says so. Otherwise it is
graph_v1, the operator-approved template in app/scheduling/graph_v1.py: the
"standard sequence", what normally comes first. A system the building may not
have is marked conditional, not dropped. The template is never reported as this
job's own logic, and a prerequisite with no record is never called the cause of
a delay. A file with no predecessors is UNKNOWN logic, never "no dependencies".

WORK MATCHING IS BY WHOLE WORDS, per phrase. The progress report's substring
match read "Blocking" as masonry and "Vapour barrier" as concrete.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.scheduling.graph_v1 import build_graph_v1
from lib import progress_report as P
from lib import punch
from lib.plans import level_suggestion as LS

REPORTED_RECENT_DAYS = 7
MAX_PHOTOS = 3
MIN_PHOTO_QUALITY = 4.0

# ── PLACES ─────────────────────────────────────────────────────────────────

_NAMED_LEVELS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    (LS.SUB_CELLAR, re.compile(r"\bsub[\s-]?(?:cellar|basement)\b", re.I)),
    (LS.CELLAR, re.compile(r"\b(?:cellar|basement)\b", re.I)),
    (LS.FOUNDATION, re.compile(r"\bfoundations?\b", re.I)),
    (LS.GROUND, re.compile(r"\bground\s+(?:floor|level)\b", re.I)),
    (LS.MEZZANINE, re.compile(r"\bmezz(?:anine)?\b", re.I)),
    (LS.ROOF, re.compile(r"\broof(?:top)?\b", re.I)),
    (LS.BULKHEAD, re.compile(r"\bbulkhead\b", re.I)),
)
_SUB_CELLAR_WORDS = re.compile(r"\bsub[\s-]?(?:cellar|basement)\b", re.I)


def level_label(token: str) -> str:
    if token.startswith(LS.FLOOR_PREFIX):
        return f"Floor {token[len(LS.FLOOR_PREFIX):]}"
    return LS.LABELS.get(token, token.replace("_", " ").title())


def places_in(text: Any) -> Dict[str, Any]:
    """{"levels": [tokens], "space": "3B" | None} named by free text. An unknown
    place is [] and None: it is never guessed."""
    t = str(text or "")
    levels = [f"{LS.FLOOR_PREFIX}{n}" for n in P.floors_in(t)]
    rest = _SUB_CELLAR_WORDS.sub(" ", t)
    for token, rx in _NAMED_LEVELS:
        if rx.search(t if token == LS.SUB_CELLAR else rest):
            levels.append(token)
    space = None
    read = punch.read_location(t)
    area = str(read.get("area") or "")
    if area.startswith("Apt "):
        space = area[4:]
    if not levels and str(read.get("floor") or "").isdigit():
        levels.append(f"{LS.FLOOR_PREFIX}{read['floor']}")
    return {"levels": sorted(set(levels)), "space": space}


def level_asked(text: Any) -> Optional[str]:
    """The one level a person named: "3", "floor 3", "3rd floor", "roof"."""
    t = " ".join(str(text or "").split())
    if re.fullmatch(r"\d{1,2}", t):
        return f"{LS.FLOOR_PREFIX}{int(t)}"
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)", t, re.I)
    if m:
        return f"{LS.FLOOR_PREFIX}{int(m.group(1))}"
    levels = places_in(t)["levels"]
    return levels[0] if len(levels) == 1 else None


# ── WHAT KIND OF WORK A PHRASE NAMES ───────────────────────────────────────

ROUGH_MEP = ("rough_dwv", "rough_water", "rough_duct", "rough_electric")
_MEP_CREW = re.compile(r"\b(?:plumb\w*|electric\w*|mechanical|hvac|sprinkler\w*)\b", re.I)
_TRIM = re.compile(r"\btrim(?:[\s-]?out)?\b|\bfixtures?\b|\bdevices?\b", re.I)

#: First match wins, per phrase. Node ids are graph_v1's. `insulation` has no
#: node in the template; it is carried as related work.
_SPECIFIC: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("drywall", re.compile(r"\b(?:drywall|sheet\s?rock|gypsum\s+board|gyp\s+board|taping|tape\s+and\s+spackle|spackl\w*|close\s+walls?)\b", re.I)),
    ("ceiling_drop", re.compile(r"\bceiling\s+drops?\b|\bdrop\s+ceilings?\b", re.I)),
    ("prime", re.compile(r"\bprim(?:e|er|ing)\b|\bpaint\w*\b", re.I)),
    ("insulation", re.compile(r"\binsulat\w*\b|\bspray\s+foam\b|\bvapou?r\s+barrier\b", re.I)),
    ("rough_sprinkler", re.compile(r"\bsprinklers?\b", re.I)),
    ("rough_gas", re.compile(r"\bgas\b", re.I)),
    ("rough_lowvolt", re.compile(r"\blow[\s-]?volt\w*\b|\bfire[\s-]?alarm\b", re.I)),
    ("rough_dwv", re.compile(r"\bdwv\b|\bsanitary\b|\bwaste\s+(?:and|&)\s+vent\b", re.I)),
    ("rough_water", re.compile(r"\b(?:domestic\s+)?water\s+(?:rough|pip\w+|lines?)\b|\bdomestic\s+water\b", re.I)),
    ("rough_duct", re.compile(r"\bduct(?:work|s)?\b", re.I)),
    ("rough_electric", re.compile(r"\belectric\w*\b|\bwiring\b|\bpull(?:ing)?\s+wires?\b|\bconduits?\b", re.I)),
    ("framing", re.compile(r"\bfram(?:e|es|ing)\b|\bstuds?\b|\bblocking\b|\bdoor\s+bucks?\b", re.I)),
)
_GENERIC_MEP = re.compile(r"\bmep\b", re.I)
_GENERIC_PLUMBING = re.compile(r"\bplumbing\b", re.I)


def classify(phrase: Any, crew: Any = "") -> Tuple[List[str], bool]:
    """(graph node ids, generic). `generic`: the phrase names a trade but not
    which part ("MEP rough-in", "Plumbing"), so it is weak evidence for each."""
    t = str(phrase or "")
    if _TRIM.search(t) and _MEP_CREW.search(str(crew or "")):
        return ["mep_trim"], False
    for node, rx in _SPECIFIC:
        if rx.search(t):
            return [node], False
    if _GENERIC_MEP.search(t):
        return list(ROUGH_MEP), True
    if _GENERIC_PLUMBING.search(t):
        return ["rough_dwv", "rough_water"], True
    return [], False


def evidence_rows(activities: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per PHRASE of each filed crew row (progress_report._log_activities):
    the kind of work, and where. A phrase naming its own level ("Roof MEP") is
    at that level, not on the crew row's floors."""
    out = []
    for a in activities:
        row_place = places_in(a.get("where"))
        for phrase in P.work_phrases(a.get("work")):
            own = places_in(phrase)
            place = own if own["levels"] else (row_place if row_place["levels"] else places_in(a.get("work")))
            nodes, generic = classify(phrase, f"{a.get('trade') or ''} {a.get('company') or ''}")
            out.append({"date": a["date"], "sub": a.get("company") or "", "work": phrase, "nodes": nodes,
                        "generic": generic, "levels": place["levels"], "space": place["space"],
                        "where": a.get("where") or "", "log_id": a.get("log_id") or "",
                        "amended": bool(a.get("amended"))})
    return out


def photo_rows(index_rows: Iterable[Dict[str, Any]], log_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    """The photo index, placed the same way. `log_ids`: the effective filed logs
    (an amended log's superseded original is left out)."""
    out = []
    for r in index_rows:
        if log_ids is not None and str(r.get("log_id")) not in log_ids:
            continue
        place = places_in(r.get("where"))
        crew = str(r.get("sub") or "")
        nodes: List[str] = []
        for phrase in P.work_phrases(r.get("work")):
            nodes += classify(phrase, crew)[0]
        seen, _ = classify(f"{r.get('description') or ''} {' '.join(r.get('tags') or [])}", crew)
        out.append({**r, "levels": place["levels"], "nodes": sorted(set(nodes)), "seen_nodes": seen})
    return out


def coverage(rows: Sequence[Dict[str, Any]], photos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """How much of the record the engine can use, for a job. What decides
    whether a floor-by-floor view is honest there."""
    placed = [r for r in rows if r["levels"]]
    known = [r for r in rows if r["nodes"]]
    return {
        "phrases": len(rows), "name_a_level": len(placed),
        "name_one_level": sum(1 for r in placed if len(r["levels"]) == 1),
        "match_sequence": len(known), "generic_only": sum(1 for r in known if r["generic"]),
        "levels": dict(Counter(lv for r in placed for lv in r["levels"]).most_common(20)),
        "not_matched": Counter(r["work"] for r in rows if not r["nodes"]).most_common(25),
        "not_placed": Counter(r["where"] for r in rows if not r["levels"]).most_common(15),
        "photos": len(photos), "photos_one_level": sum(1 for p in photos if len(p["levels"]) == 1),
        "photo_views": dict(Counter(str(p.get("view")) for p in photos)),
    }


# ── THE STATE OF ONE PACKAGE ───────────────────────────────────────────────

def _schedule_rows(schedule: Optional[Dict[str, Any]], node: str, level: str) -> List[Dict[str, Any]]:
    """Activities of a CONFIRMED schedule file that name this work on this level."""
    out = []
    for a in (schedule or {}).get("activities") or []:
        if a.get("kind") == "summary":
            continue
        name = str(a.get("name") or "")
        # The name is its own crew column: "Plumbing Trim" is MEP trim, not rough.
        if node in classify(name, name)[0] and level in places_in(name)["levels"]:
            out.append(a)
    return out


def planned_finish(a: Dict[str, Any]) -> Optional[str]:
    """The file's planned finish: current, else baseline (schedule_plan's rule)."""
    return a.get("current_finish") or a.get("baseline_finish")


def past_planned_no_report(a: Dict[str, Any], reported: bool, today: date, logs_from: Optional[date]) -> bool:
    """The planned finish has gone by, the file has no actual finish, and no log
    in the window read names the work. A stated fact, never a cause. With no
    window known, or a date before it, nothing can be said."""
    if reported or a.get("actual_finish") or not logs_from:
        return False
    try:
        due = date.fromisoformat(str(planned_finish(a))[:10])
    except ValueError:
        return False
    return logs_from <= due < today


def _schedule_facts(rows: List[Dict[str, Any]], today: Optional[date] = None, reported: bool = True,
                    logs_from: Optional[date] = None) -> List[Dict[str, Any]]:
    keep = ("id", "name", "baseline_start", "baseline_finish", "current_start", "current_finish",
            "actual_start", "actual_finish", "percent_complete")
    return [{**{k: a.get(k) for k in keep}, "planned_finish": planned_finish(a),
             "past_planned_no_report": bool(today) and past_planned_no_report(a, reported, today, logs_from)}
            for a in rows[:3]]


def package_state(node: str, level: str, rows: Sequence[Dict[str, Any]], photos: Sequence[Dict[str, Any]],
                  schedule: Optional[Dict[str, Any]], today: date, logs_from: Optional[date] = None) -> Dict[str, Any]:
    """What the records hold about `node` on `level`. status: reported_recent |
    reported_earlier | unknown. "reported_earlier" is not "complete"."""
    mine = [r for r in rows if node in r["nodes"] and level in r["levels"]]
    days = sorted({r["date"] for r in mine})
    only_here = [r for r in mine if r["levels"] == [level]]
    status = "unknown"
    if days:
        status = "reported_recent" if (today - days[-1]).days <= REPORTED_RECENT_DAYS else "reported_earlier"
    pics = [p for p in photos if level in p["levels"] and (node in p["nodes"] or node in p["seen_nodes"])
            and float(p.get("quality") or 0) >= MIN_PHOTO_QUALITY]
    pics.sort(key=lambda p: (str(p.get("date")), float(p.get("quality") or 0)), reverse=True)
    return {
        "node": node, "level": level, "status": status,
        "first": days[0] if days else None, "last": days[-1] if days else None, "days": len(days),
        "subs": sorted({r["sub"] for r in mine if r["sub"]}),
        # True when no row names this level alone: "floors 1-4" together.
        "shared_with_other_levels": bool(mine) and not only_here,
        "generic_only": bool(mine) and all(r["generic"] for r in mine),
        "log_ids": sorted({r["log_id"] for r in mine if r["log_id"]})[-5:],
        "photos": [{"id": p.get("short"), "date": p.get("date"), "sub": p.get("sub"), "shows": p.get("description"),
                    "only_this_level": p["levels"] == [level]} for p in pics[:MAX_PHOTOS]],
        "observed": any(node in p["seen_nodes"] for p in pics),
        "verified": None, "percent": None,
        "schedule": _schedule_facts(_schedule_rows(schedule, node, level), today, bool(days), logs_from),
    }


# ── THE SEQUENCE ───────────────────────────────────────────────────────────

_GATE_WORDS = {
    "plumbing_rough": "plumbing rough inspection", "sprinkler": "sprinkler inspection / hydro test",
    "electrical_rough": "electrical rough inspection", "firestopping": "firestopping special inspection",
    "energy_nycecc": "energy code (NYCECC insulation) special inspection",
}
_NODE_WORDS = {
    "framing": "framing", "rough_dwv": "DWV rough", "rough_duct": "duct rough", "rough_sprinkler": "sprinkler rough",
    "rough_water": "domestic water rough", "rough_gas": "gas rough", "rough_electric": "electric rough",
    "rough_lowvolt": "fire-alarm / low-voltage rough", "drywall": "drywall", "ceiling_drop": "ceiling drop",
    "prime": "prime / paint", "mep_trim": "MEP trim", "finishes": "finishes", "insulation": "insulation",
}


def node_label(node: str) -> str:
    return _NODE_WORDS.get(node, node.replace("_", " "))


def _graph(flags: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, List[Tuple[str, str]]]]:
    """(nodes by id, {node: [(prerequisite, edge type)]}). A node needing a
    system the building is KNOWN not to have is dropped; unknown is kept."""
    g = build_graph_v1()
    known = flags or {}
    nodes = {n.id: n for n in g.nodes if not any(known.get(r) is False for r in n.requires)}
    before: Dict[str, List[Tuple[str, str]]] = {}
    for e in g.edges:
        if e.from_node in nodes and e.to_node in nodes:
            before.setdefault(e.to_node, []).append((e.from_node, e.edge_type))
    return nodes, before


def _is_gate(node: Any) -> bool:
    return hasattr(node, "inspection_type")


def _prerequisites(target: str, nodes: Dict[str, Any], before: Dict[str, List[Tuple[str, str]]]) -> List[str]:
    """Every node that normally comes before `target`, nearest first."""
    order, queue = [], [p for p, _ in before.get(target, [])]
    while queue:
        n = queue.pop(0)
        if n not in order and n in nodes:
            order.append(n)
            queue += [p for p, _ in before.get(n, [])]
    return order


def _link_states(p: Dict[str, Any], level: str, rows: Sequence[Dict[str, Any]], photos: Sequence[Dict[str, Any]],
                 schedule: Optional[Dict[str, Any]], today: date, logs_from: Optional[date]) -> List[Dict[str, Any]]:
    """What the logs say about one predecessor: on the asked level if its name
    covers it, else on the one level it names. No level named: no log match."""
    nodes, _generic = classify(p.get("name"), p.get("name"))
    levels = places_in(p.get("name"))["levels"]
    at = level if level in levels else (levels[0] if len(levels) == 1 else None)
    return [package_state(n, at, rows, photos, schedule, today, logs_from) for n in nodes] if at else []


def job_logic(target: str, level: str, rows: Sequence[Dict[str, Any]], photos: Sequence[Dict[str, Any]],
              schedule: Optional[Dict[str, Any]], today: date, logs_from: Optional[date] = None) -> Dict[str, Any]:
    """{"source": "job"|"standard", "reason": ..., "activities": [...]}. "job"
    only for an activity whose predecessors the confirmed file states."""
    if not schedule:
        return {"source": "standard", "reason": "no_schedule", "activities": []}
    mine = _schedule_rows(schedule, target, level)
    if not mine:
        return {"source": "standard", "reason": "no_activity", "activities": []}
    read = [a for a in mine if isinstance(a.get("predecessors"), list)]
    if not read:
        return {"source": "standard", "reason": "no_logic_in_file", "activities": []}
    by_id = {str(a.get("id")): a for a in schedule.get("activities") or []}
    out = []
    for a in read[:3]:
        links = []
        for link in a["predecessors"]:
            p = by_id.get(str(link.get("id"))) or {}
            links.append({**link, "name": p.get("name") or str(link.get("id")), "facts": _schedule_facts([p])[0] if p else None,
                          "states": _link_states(p, level, rows, photos, schedule, today, logs_from)})
        out.append({"id": a.get("id"), "name": a.get("name"), "predecessors": links,
                    "unresolved": int(a.get("predecessors_unresolved") or 0)})
    return {"source": "job", "reason": "file_states_logic", "activities": out}


def what_holds(target: str, level: str, activities: Iterable[Dict[str, Any]], index_rows: Iterable[Dict[str, Any]],
               *, today: date, schedule: Optional[Dict[str, Any]] = None, flags: Optional[Dict[str, Any]] = None,
               log_ids: Optional[set] = None, stop_work: Optional[List[Dict[str, Any]]] = None,
               regulatory_note: str = "", relations: Optional[List[Dict[str, Any]]] = None,
               logs_from: Optional[date] = None) -> Dict[str, Any]:
    """The evidence for one question. It names what is open on the record and
    what is unknown; it never names a cause."""
    rows = evidence_rows(activities)
    photos = photo_rows(index_rows, log_ids)
    nodes, before = _graph(flags)
    work, gates = [], []
    for n in _prerequisites(target, nodes, before):
        if _is_gate(nodes[n]):
            gates.append({"id": n, "label": _GATE_WORDS.get(nodes[n].inspection_type, nodes[n].inspection_type.replace("_", " ")),
                          "status": "unknown", "requires_unconfirmed": [r for r in nodes[n].requires if (flags or {}).get(r) is None]})
        else:
            s = package_state(n, level, rows, photos, schedule, today)
            s["requires_unconfirmed"] = [r for r in nodes[n].requires if (flags or {}).get(r) is None]
            work.append(s)
    return {"target": package_state(target, level, rows, photos, schedule, today, logs_from), "level": level, "today": today,
            "known_activity": target in nodes, "work": work, "gates": gates,
            "sequence": job_logic(target, level, rows, photos, schedule, today, logs_from),
            "insulation": package_state("insulation", level, rows, photos, schedule, today),
            "has_schedule": bool(schedule), "stop_work": stop_work or [], "regulatory_note": regulatory_note,
            "relations": relations or [],
            "counts": {"log_rows": len(rows), "on_this_level": sum(1 for r in rows if level in r["levels"]),
                       "without_a_level": sum(1 for r in rows if not r["levels"])}}


# ── AS WORDS ───────────────────────────────────────────────────────────────

def _day(d: Any) -> str:
    return f"{d:%b} {d.day}" if isinstance(d, date) else str(d or "")


def state_words(s: Dict[str, Any], today: date) -> str:
    if s["status"] == "unknown":
        return "no report on this level (that does not mean it wasn't done)"
    span = _day(s["first"]) if s["first"] == s["last"] else f"{_day(s['first'])} to {_day(s['last'])}"
    bits = [f"reported {span}, {s['days']} day(s)"]
    if s["subs"]:
        bits.append("by " + ", ".join(s["subs"]))
    if s["status"] == "reported_earlier":
        bits.append(f"last report {(today - s['last']).days} days ago (not the same as finished)")
    if s["shared_with_other_levels"]:
        bits.append("filed for several floors together, not this floor alone")
    if s["generic_only"]:
        bits.append("the log names the trade only, not this part of it")
    return "; ".join(bits)


def _fact_dates(a: Dict[str, Any]) -> str:
    dates = [f"{k.replace('_', ' ')} {a[k]}" for k in ("baseline_finish", "current_finish", "actual_finish") if a.get(k)]
    pct = f"; the file states {a['percent_complete']}%" if a.get("percent_complete") is not None else ""
    return (", ".join(dates) or "no dates") + pct


def _schedule_words(s: Dict[str, Any]) -> List[str]:
    out = []
    for a in s["schedule"]:
        past = (f" | past planned finish {a['planned_finish']} with no report on this level in the logs read"
                if a.get("past_planned_no_report") else "")
        out.append(f"Schedule file, {a.get('name')}: " + _fact_dates(a) + past)
    return out


_STANDARD_NOTES = {
    "no_activity": "The confirmed schedule has no activity for this work on this level, so what follows is the standard "
                   "sequence, not this job's own logic.",
    "no_logic_in_file": "The confirmed schedule does not carry predecessor logic for this activity. That is unknown, not "
                        "'no dependencies'. What follows is the standard sequence, not this job's own logic.",
}
_LAG_UNITS = {"days": "working days", "edays": "calendar days", "percent": "%"}


def _link_words(p: Dict[str, Any]) -> str:
    bits = [p.get("type") or "type not stated"]
    if p.get("lag") is not None or p.get("lag_unit") == "percent":
        amount = "percent, amount not read" if p.get("lag") is None else f"{p['lag']:g}"
        unit = _LAG_UNITS.get(str(p.get("lag_unit")), "") if p.get("lag") is not None else ""
        bits.append(f"lag {amount} {unit}".strip())
    return ", ".join(bits)


def _job_logic_words(seq: Dict[str, Any], today: date) -> List[str]:
    out: List[str] = []
    for a in seq["activities"]:
        n = len(a["predecessors"])
        out.append(f"This job's own schedule lists no predecessor for {a['name']}." if not n and not a["unresolved"]
                   else f"This job's own logic, from its confirmed schedule file: {a['name']} has {n} predecessor(s):")
        for p in a["predecessors"][:8]:
            bits = ["; ".join(state_words(st, today) + f" ({level_label(st['level'])})" for st in p["states"])
                    or "no matching log work or no level in its name"]
            if p["facts"]:
                bits.insert(0, _fact_dates(p["facts"]))
            out.append(f"- {p['name']} ({_link_words(p)}): " + " | ".join(bits))
        if n > 8:
            out.append(f"...and {n - 8} more.")
        if a["unresolved"]:
            out.append(f"{a['unresolved']} link(s) in the file could not be matched to an activity and are left out, so this list may be short.")
    return out


def as_text(ans: Dict[str, Any]) -> str:
    """For the assistant: every figure it may repeat is printed here."""
    today, label, t = ans["today"], level_label(ans["level"]), ans["target"]
    out = [f"{node_label(t['node']).capitalize()} on {label}: {state_words(t, today)}."]
    out += _schedule_words(t)
    if ans["stop_work"]:
        out.append("OPEN STOP WORK / VACATE on this job: " + "; ".join(str(s.get("number") or s.get("kind")) for s in ans["stop_work"]) + ".")
    elif ans["regulatory_note"]:
        out.append(f"Stop-work records: {ans['regulatory_note']}")
    else:
        out.append("No open stop-work or vacate order on the DOB records.")
    seq = ans["sequence"]
    if seq["source"] == "job":
        out += _job_logic_words(seq, today)
    elif seq["reason"] in _STANDARD_NOTES:
        out.append(_STANDARD_NOTES[seq["reason"]])
    if ans["gates"]:
        out.append("Inspections that normally come before it (standard sequence, not this job's own schedule). "
                   "Levelog holds no inspection results, so each is UNKNOWN, neither passed nor failed:")
        out += [f"- {g['label']}" + (" (if the building has this system)" if g["requires_unconfirmed"] else "") for g in ans["gates"]]
    if ans["work"] and seq["source"] != "job":
        out.append("Work that normally comes first (standard sequence, not this job's own schedule):")
        for s in ans["work"]:
            out.append(f"- {node_label(s['node'])}: {state_words(s, today)}"
                       + (" (if the building has this system)" if s["requires_unconfirmed"] else "")
                       + "".join(f" | {w}" for w in _schedule_words(s)))
    if ans["insulation"]["status"] != "unknown":
        out.append(f"Related, insulation: {state_words(ans['insulation'], today)}.")
    if not ans["has_schedule"]:
        out.append("No confirmed schedule is on file, so no planned date, delay or downstream impact can be stated.")
    listed = [st for a in seq["activities"] for link in a["predecessors"] for st in link["states"]] if seq["source"] == "job" else ans["work"]
    shown = {p["id"]: p for s in [t] + listed for p in s["photos"]}
    if shown:
        out.append("Photos (ids for send_photos):")
        out += [f"- {p['id']} {p['date']} {p.get('sub') or ''}: {p['shows']}"
                + ("" if p["only_this_level"] else " (filed for several floors)") for p in list(shown.values())[:6]]
    for r in ans["relations"][:3]:
        out.append(f"AI photo comparison, unconfirmed ({r['first']} vs {r['second']}): " + "; ".join(r.get("changes") or ["no change named"]))
    c = ans["counts"]
    out.append(f"Records read: {c['log_rows']} log entries, {c['on_this_level']} naming this level, "
               f"{c['without_a_level']} naming no level at all.")
    out.append("Say what is on record and what is unknown. Do not name a cause, a percent, or a passed inspection: "
               "none of those are on record. A photo proves no inspection.")
    return "\n".join(out)
