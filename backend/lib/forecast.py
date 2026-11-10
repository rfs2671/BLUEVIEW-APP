"""SCHEDULE STATUS AND FORECAST: what the record says against the confirmed file,
and estimates only where completed evidence supports one.

Pure: no database, no network. The server hands in the CONFIRMED schedule
document (lib/schedule_import.py), the evidence items (lib/evidence.py) and the
filed-log rows (work_state.evidence_rows). Four groups are kept apart in the data
and in every word said, and never mixed:

  VERIFIED   evidence at ATTESTED OR STRONGER (verified sign-off, confirmed pour /
             punch / logbook, attested statement or inspection): start and done
             markers. Nothing weaker can mark a start or a finish.
  FILE       the confirmed file's own dates (baseline and current side by side,
             never merged), its own stated actual dates and percent (labelled
             as the file's), and its own logic (FS / SS / FF / SF with lag).
  REPORTED   the first and last day a filed log names that work on that level.
             A report is never a start marker and never a finish.
  ESTIMATE   computed here, each an evidence.item of kind "estimate" with its
             basis and its assumption. Never a fact, never in the groups above.

THE OWNER'S RULINGS this module keeps (2026-11-09):
  * approved baselines stay separate from LeveLog's estimates: no estimate is
    ever written into, or shown as, a file date;
  * the project's own dependencies are the file's links, never the template's;
  * activity dates, a crew moving between floors, report frequency, check-ins,
    crew counts and photos are NOT proof of a production rate, and no date is
    derived from them. A cycle is only the days between an attested-or-stronger
    START marker and an attested-or-stronger DONE marker on the same level;
  * no completion percent, no date, no delay cause is fabricated. "Past planned
    finish with no done evidence" is two records side by side, not a delay.

ESTIMATES, and only these:
  * a successor's shifted date through the FILE's link to an activity that has
    no done evidence by its planned finish, on the stated assumption that the
    late activity finishes no earlier than today (FS and FF links with a lag
    in working or calendar days; working days are counted Monday to Friday,
    because the file's calendar is not read). SS / SF links hang off the
    start, so a late finish moves nothing through them. A link with no type, a
    percent lag or a lag with no unit gets no date. No logic in the file: the
    impact is unknown and is said so;
  * per repeated activity (one kind of work on several levels in the file): the
    observed cycle range from levels with BOTH markers, at least
    MIN_CYCLE_LEVELS of them, as min-max and median with the sample and the
    levels used; and, for a level that has a start marker and no done marker,
    its finish range from that start. A level not started on record gets none;
  * project completion: the FILE's latest planned finish is a file fact; an
    estimate is given only when a finish estimate above covers the activity
    that finishes last in the file. Otherwise there is no completion forecast.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import evidence as E
from lib import progress_plan as PP
from lib import work_state as W

#: Rungs that can mark a start or a finish.
STRONG = ("verified", "confirmed", "attested")
#: Levels with both markers needed before a cycle range is given.
MIN_CYCLE_LEVELS = 3
NOT_ENOUGH = "not enough completed evidence for an estimate"
MAX_LINES = 12
_START_CLAIMS = ("started", "in_progress")
_LAG_WORDS = {"days": "working days", "edays": "calendar days"}

Item = Dict[str, Any]


def _iso(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _day(d: Optional[date]) -> str:
    return f"{d:%b} {d.day}, {d.year}" if d else "date not stated"


def _activities(schedule: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [a for a in (schedule or {}).get("activities") or [] if a.get("kind") != "summary"]


# ── MARKERS: attested or stronger only ────────────────────────────────────

def _strong(i: Item) -> bool:
    return i.get("kind") in STRONG


def _marker(i: Optional[Item]) -> Optional[Dict[str, Any]]:
    if not i:
        return None
    return {"kind": i["kind"], "claim": i["claim"], "on": _iso(i.get("on")), "source": i.get("source"),
            "ref": i.get("ref"), "by": i.get("by"), "quote": i.get("quote"), "shared": bool(i.get("shared")),
            "levels": list(i.get("levels") or [])}


def _on(i: Item) -> int:
    d = _iso(i.get("on"))
    return d.toordinal() if d else 0


def markers(items: Iterable[Item]) -> Dict[str, Optional[Dict[str, Any]]]:
    """{"start", "done", "failed"} for ONE (work, level) from its items. Only
    attested-or-stronger items count; reported and observed items and
    estimates are ignored here whatever they claim. Done / failed follow
    evidence.status: the strongest rung that says either, its latest item."""
    strong = [i for i in items if _strong(i)]
    starts = [i for i in strong if i.get("claim") in _START_CLAIMS]
    dated = [i for i in starts if _iso(i.get("on"))]
    start = min(dated, key=_on) if dated else (starts[0] if starts else None)
    word = E.status(strong) if strong else "unknown"
    done = failed = None
    if word.startswith(("done_", "failed_")):
        rung = word.split("_", 1)[1]
        last = E.newest(i for i in strong if i["kind"] == rung and i["claim"] in ("done", "failed"))
        if last["claim"] == "done":
            done = last
        else:
            failed = last
    return {"start": _marker(start), "done": _marker(done), "failed": _marker(failed)}


def _about(items: Sequence[Item], node: str, level: str, *, alone: bool = False) -> List[Item]:
    return [i for i in items if i.get("node") == node and level in (i.get("levels") or [])
            and not (alone and i.get("shared"))]


def activity_markers(place: Dict[str, Any], items: Sequence[Item]) -> Dict[str, Any]:
    """An activity's markers over every (work, level) its name covers. It is
    DONE only when every one of them has a done marker (a generic "rough
    plumbing" is done when both parts are); its start is the earliest start."""
    pairs = [(n, lv) for n in place["nodes"] for lv in place["levels"]]
    each = [markers(_about(items, n, lv)) for n, lv in pairs]
    starts = [m["start"] for m in each if m["start"]]
    dones = [m["done"] for m in each]
    fails = [m["failed"] for m in each if m["failed"]]
    done = None
    if pairs and all(dones):
        done = max(dones, key=lambda m: m["on"].toordinal() if m["on"] else 0)
    start = min(starts, key=lambda m: m["on"].toordinal() if m["on"] else 10**9) if starts else None
    return {"start": start, "done": done, "failed": fails[0] if fails else None,
            "done_parts": sum(1 for d in dones if d), "parts": len(pairs)}


# ── 1. PLAN VERSUS ACTUAL, FACTS ONLY ──────────────────────────────────────

def _planned(a: Dict[str, Any]) -> Tuple[Optional[date], Optional[date], str]:
    """(start, finish, which): current where the file has a current date, else
    baseline, and which one it was."""
    if a.get("current_start") or a.get("current_finish"):
        return _iso(a.get("current_start")), _iso(a.get("current_finish")) or _iso(a.get("baseline_finish")), "current"
    return _iso(a.get("baseline_start")), _iso(a.get("baseline_finish")), "baseline"


def _reported_days(rows: Sequence[Dict[str, Any]], items: Sequence[Item], place: Dict[str, Any]) -> List[date]:
    days = {r["date"] for r in PP._reports(rows, place)}
    for i in items:
        if i.get("kind") == "reported" and i.get("node") in place["nodes"] \
                and set(i.get("levels") or []) & set(place["levels"]) and _iso(i.get("on")):
            days.add(_iso(i["on"]))
    return sorted(days)


def plan_vs_actual(schedule: Optional[Dict[str, Any]], items: Sequence[Item], rows: Sequence[Dict[str, Any]],
                   *, today: date) -> List[Dict[str, Any]]:
    """One row per non-summary activity: FILE dates, VERIFIED markers, REPORTED
    span. `past_planned_finish_no_done` is the stated fact: the file's planned
    finish has gone by, the file states no actual finish, and no done marker at
    attested or stronger is on record. It names no cause."""
    out = []
    for a in _activities(schedule):
        place = PP.activity_place(a)
        mapped = bool(place["nodes"] and place["levels"])
        m = activity_markers(place, items) if mapped else {"start": None, "done": None, "failed": None,
                                                           "done_parts": 0, "parts": 0}
        days = _reported_days(rows, items, place) if mapped else []
        p_start, p_finish, which = _planned(a)
        out.append({
            "id": str(a.get("id")), "name": a.get("name"), "kind": a.get("kind"), "mapped": mapped,
            "nodes": place["nodes"], "levels": place["levels"],
            "file": {"baseline_start": a.get("baseline_start"), "baseline_finish": a.get("baseline_finish"),
                     "current_start": a.get("current_start"), "current_finish": a.get("current_finish"),
                     "planned_start": p_start, "planned_finish": p_finish, "planned_source": which,
                     "actual_start": a.get("actual_start"), "actual_finish": a.get("actual_finish"),
                     "stated_percent": a.get("percent_complete")},
            "verified": {"start": m["start"], "done": m["done"], "failed": m["failed"],
                         "done_parts": m["done_parts"], "parts": m["parts"]},
            "reported": {"first": days[0] if days else None, "last": days[-1] if days else None,
                         "days": len(days)},
            "past_planned_finish_no_done": bool(p_finish and p_finish < today and not m["done"]
                                                and not a.get("actual_finish")),
        })
    return out


# ── 2. DOWNSTREAM, BY THE FILE'S OWN LOGIC ─────────────────────────────────

def has_logic(schedule: Optional[Dict[str, Any]]) -> bool:
    return any(isinstance(a.get("predecessors"), list) for a in _activities(schedule))


def _successors(schedule: Optional[Dict[str, Any]]) -> Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]]:
    out: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    for a in _activities(schedule):
        for link in a.get("predecessors") or []:
            out.setdefault(str(link.get("id")), []).append((a, link))
    return out


def _add_working_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += timedelta(days=step)
        if d.weekday() < 5:
            left -= 1
    return d


def _after_lag(d: date, lag: float, unit: Optional[str]) -> date:
    n = int(round(lag))
    return _add_working_days(d, n) if unit == "days" else d + timedelta(days=n)


def _next_working_day(d: date) -> date:
    return _add_working_days(d, 1)


def _link_words(link: Dict[str, Any]) -> str:
    t = link.get("type") or "type not stated"
    lag = link.get("lag")
    if lag is not None:
        t += f", lag {lag:g} {_LAG_WORDS.get(str(link.get('lag_unit')), '(unit not stated)')}"
    elif link.get("lag_unit") == "percent":
        t += ", lag stated as a percent"
    return t


_DEPENDS = {"FS": "its start follows {p}'s finish", "SS": "its start follows {p}'s start",
            "FF": "its finish follows {p}'s finish", "SF": "its finish follows {p}'s start"}


def downstream(schedule: Optional[Dict[str, Any]], pva: Sequence[Dict[str, Any]], *, today: date,
               project_id: Any) -> Dict[str, Any]:
    """For each activity past its planned finish with no done evidence: its
    successors as the FILE links them, and how each one's planned date hangs
    on it. A computed date is an ESTIMATE item (basis, assumption), never a
    cause and never a file date."""
    late = [r for r in pva if r["past_planned_finish_no_done"]]
    if not has_logic(schedule):
        return {"logic": False, "late": [r["id"] for r in late], "impacts": []}
    succ = _successors(schedule)
    rows = {r["id"]: r for r in pva}
    impacts = []
    for r in late:
        for b, link in succ.get(r["id"], []):
            impacts.append(_impact(r, rows.get(str(b.get("id"))) or {}, b, link, today, project_id))
    return {"logic": True, "late": [r["id"] for r in late], "impacts": impacts}


def _impact(late: Dict[str, Any], brow: Dict[str, Any], b: Dict[str, Any], link: Dict[str, Any],
            today: date, project_id: Any) -> Dict[str, Any]:
    kind = link.get("type")
    p_start, p_finish, _which = _planned(b)
    out: Dict[str, Any] = {"late_id": late["id"], "late_name": late["name"], "id": str(b.get("id")), "name": b.get("name"),
                           "link": {"type": kind, "lag": link.get("lag"), "lag_unit": link.get("lag_unit")},
                           "depends": _DEPENDS.get(kind or "", "the file does not state how").format(p=late["name"]),
                           "planned_start": p_start, "planned_finish": p_finish, "estimate": None, "no_estimate": None}
    v = brow.get("verified") or {}
    if kind in ("SS", "SF"):
        out["no_estimate"] = "the link hangs off the start, so a late finish moves nothing through it"
    elif kind not in ("FS", "FF"):
        out["no_estimate"] = "the file states no link type, and none is assumed"
    elif link.get("lag_unit") == "percent" or (link.get("lag") is not None and link.get("lag_unit") not in _LAG_WORDS):
        out["no_estimate"] = "the link's lag is not in days the file states, so no date is computed"
    elif kind == "FS" and (b.get("actual_start") or v.get("start")):
        out["no_estimate"] = "it has already started on record"
    elif kind == "FF" and (b.get("actual_finish") or v.get("done")):
        out["no_estimate"] = "it is already done on record"
    else:
        lag, unit = link.get("lag"), link.get("lag_unit")
        bound = _after_lag(today, lag, unit) if lag is not None else today
        if kind == "FS":
            bound = _next_working_day(bound)
        planned = p_start if kind == "FS" else p_finish
        which = "start" if kind == "FS" else "finish"
        lag_said = (f"plus the file's lag of {lag:g} {_LAG_WORDS[unit]}" if lag is not None
                    else "with no lag (the file states none, and none is added)")
        basis = (f"the file's {kind} link from {late['name']} ({late['id']}) to {b.get('name')} ({b.get('id')}), "
                 f"{lag_said}; working days counted Monday to Friday (the file's calendar is not read)")
        assumption = f"{late['name']} finishes no earlier than today, {_day(today)}"
        shifted = planned is None or bound > planned
        est = E.item("estimate", "scheduled", source="lib/forecast", ref=f"link:{late['id']}->{b.get('id')}",
                     project_id=project_id, node=(brow.get("nodes") or [None])[0], levels=brow.get("levels") or (),
                     on=today, basis=basis, note=assumption)
        est.update({"subject": f"{b.get('name')} ({b.get('id')})", "which": which, "not_before": bound,
                    "planned": planned, "shifted": shifted, "assumption": assumption})
        out["estimate"] = est
    return out


# ── 3. CYCLE ESTIMATES, FROM COMPLETED EVIDENCE ONLY ───────────────────────

def _repeated(schedule: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    """{work: [levels]} for one specific kind of work the file plans on two or
    more levels. A generic activity ("MEP rough") is not one kind of work."""
    out: Dict[str, set] = {}
    for a in _activities(schedule):
        place = PP.activity_place(a)
        if place["generic"] or len(place["nodes"]) != 1:
            continue
        out.setdefault(place["nodes"][0], set()).update(place["levels"])
    return {n: sorted(lv, key=PP._level_order) for n, lv in out.items() if len(lv) >= 2}


def cycles(schedule: Optional[Dict[str, Any]], items: Sequence[Item], *, today: date, project_id: Any) -> List[Dict[str, Any]]:
    """Per repeated kind of work: the levels with BOTH a start and a done
    marker at attested or stronger (each dated, each about that level alone),
    and, at MIN_CYCLE_LEVELS or more, the observed cycle range as an estimate.
    Crew counts, check-ins, reports and photos are never read here."""
    out = []
    for node, levels in sorted(_repeated(schedule).items()):
        samples = []
        open_levels = []
        for lv in levels:
            m = markers(_about(items, node, lv, alone=True))
            s, d = m["start"], m["done"]
            if s and d and s["on"] and d["on"] and d["on"] >= s["on"]:
                samples.append({"level": lv, "start": s["on"], "done": d["on"], "days": (d["on"] - s["on"]).days})
            elif s and s["on"] and not d:
                open_levels.append((lv, s))
        entry: Dict[str, Any] = {"node": node, "label": W.node_label(node), "levels": levels,
                                 "sample": len(samples), "levels_used": [x["level"] for x in samples],
                                 "samples": samples, "estimate": None, "finishes": [], "overrun": [], "no_estimate": None}
        if len(samples) < MIN_CYCLE_LEVELS:
            entry["no_estimate"] = NOT_ENOUGH
            out.append(entry)
            continue
        days = sorted(x["days"] for x in samples)
        lo, hi, med = days[0], days[-1], statistics.median(days)
        used = ", ".join(W.level_label(x["level"]) for x in samples)
        basis = (f"calendar days from the attested-or-stronger start marker to the done marker of {W.node_label(node)} "
                 f"on {len(samples)} levels ({used})")
        est = E.item("estimate", "scheduled", source="lib/forecast", ref=f"cycle:{node}", project_id=project_id,
                     node=node, levels=[x["level"] for x in samples], on=today, basis=basis,
                     note="observed spans on completed levels; not a production rate")
        est.update({"subject": f"{W.node_label(node)} cycle per level", "min_days": lo, "max_days": hi,
                    "median_days": med, "sample": len(samples), "levels_used": [x["level"] for x in samples]})
        entry["estimate"] = est
        for lv, s in open_levels:
            if s["on"] + timedelta(days=hi) < today:
                entry["overrun"].append({"level": lv, "start": s["on"], "latest": s["on"] + timedelta(days=hi)})
                continue
            f = E.item("estimate", "scheduled", source="lib/forecast", ref=f"finish:{node}:{lv}", project_id=project_id,
                       node=node, levels=[lv], on=today,
                       basis=f"its start marker ({s['kind']}, {_day(s['on'])}) plus the observed cycle range of {lo}-{hi} "
                             f"days on {len(samples)} completed levels",
                       note=f"assumes {W.level_label(lv)} goes as the completed levels went, and not before today")
            f.update({"subject": f"{W.node_label(node)} {W.level_label(lv)} finish", "level": lv,
                      "earliest": max(today, s["on"] + timedelta(days=lo)), "latest": s["on"] + timedelta(days=hi),
                      "median": max(today, s["on"] + timedelta(days=int(med + 0.5))), "sample": len(samples)})
            entry["finishes"].append(f)
        out.append(entry)
    return out


# ── 4. PROJECT COMPLETION ──────────────────────────────────────────────────

def _chain(schedule: Optional[Dict[str, Any]], last: Dict[str, Any]) -> List[str]:
    """Back from the activity that finishes last, along the FILE's FS / FF
    links, through the predecessor that finishes latest. Ids, last first."""
    by_id = {str(a.get("id")): a for a in _activities(schedule)}
    out, seen, cur = [], set(), last
    while cur and str(cur.get("id")) not in seen and len(out) < 500:
        out.append(str(cur.get("id")))
        seen.add(str(cur.get("id")))
        preds = [by_id.get(str(link.get("id"))) for link in cur.get("predecessors") or []
                 if link.get("type") in ("FS", "FF")]
        preds = [p for p in preds if p and _planned(p)[1]]
        cur = max(preds, key=lambda p: (_planned(p)[1], str(p.get("id")))) if preds else None
    return out


def completion(schedule: Optional[Dict[str, Any]], pva: Sequence[Dict[str, Any]],
               cyc: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    dated = [(r["file"]["planned_finish"], r) for r in pva if r["file"]["planned_finish"]]
    if not dated:
        return {"file_finish": None, "last": None, "chain": [], "estimate": None,
                "no_estimate": "the file states no planned finish"}
    finish, last = max(dated, key=lambda x: (x[0], x[1]["id"]))
    by_id = {str(a.get("id")): a for a in _activities(schedule)}
    chain = _chain(schedule, by_id[last["id"]]) if has_logic(schedule) else [last["id"]]
    found = None
    for c in cyc:
        for f in c["finishes"]:
            if c["node"] in last["nodes"] and len(last["nodes"]) == 1 and last["levels"] == [f["level"]]:
                found = f
    out = {"file_finish": finish, "file_finish_source": last["file"]["planned_source"], "last": last,
           "chain": chain, "estimate": None, "no_estimate": None}
    if found:
        out["estimate"] = found
    else:
        out["no_estimate"] = ("no completion forecast: the completed evidence does not cover the activity that "
                              f"finishes last in the file ({last['name']})")
    return out


# ── THE WHOLE ──────────────────────────────────────────────────────────────

def forecast(schedule: Optional[Dict[str, Any]], items: Sequence[Item], rows: Sequence[Dict[str, Any]], *,
             today: date, project_id: Any, unreadable: Iterable[str] = ()) -> Dict[str, Any]:
    """`unreadable`: sources the loader could not read (its coverage). They are
    named in every line of words: "no done marker" may only mean "not read"."""
    pva = plan_vs_actual(schedule, items, rows, today=today)
    down = downstream(schedule, pva, today=today, project_id=project_id)
    cyc = cycles(schedule, items, today=today, project_id=project_id)
    data_date = _iso((schedule or {}).get("data_date"))
    return {"today": today, "data_date": data_date, "file_age_days": (today - data_date).days if data_date else None,
            "plan_vs_actual": pva, "downstream": down, "cycles": cyc, "completion": completion(schedule, pva, cyc),
            "unreadable": sorted(set(unreadable or ()))}


def estimates(fc: Dict[str, Any]) -> List[Item]:
    """Every estimate item, in one list (and nowhere else)."""
    out = [i["estimate"] for i in fc["downstream"]["impacts"] if i["estimate"]]
    for c in fc["cycles"]:
        if c["estimate"]:
            out.append(c["estimate"])
        out += c["finishes"]
    return out


# ── 5. WORDS AND A REPORT SECTION ──────────────────────────────────────────

def _cap(lines: List[str]) -> List[str]:
    return lines if len(lines) <= MAX_LINES else lines[:MAX_LINES] + [f"...and {len(lines) - MAX_LINES} more."]


def _marker_words(m: Dict[str, Any]) -> str:
    who = f" by {m['by']}" if m.get("by") else ""
    shared = " (stated for several levels together)" if m.get("shared") else ""
    return f"{m['kind']}{who}, {_day(m['on'])}, {m['source']}{shared}"


def _verified_lines(fc: Dict[str, Any]) -> List[str]:
    out = []
    for r in fc["plan_vs_actual"]:
        v = r["verified"]
        bits = []
        if v["start"]:
            bits.append(f"start marker: {_marker_words(v['start'])}")
        if v["done"]:
            bits.append(f"done: {_marker_words(v['done'])}")
        elif v["done_parts"]:
            bits.append(f"done on {v['done_parts']} of its {v['parts']} parts, not all")
        if v["failed"]:
            bits.append(f"failed: {_marker_words(v['failed'])}")
        if bits:
            out.append(f"- {r['name']} ({r['id']}): " + "; ".join(bits) + ".")
    return _cap(out) or ["- No start or done marker at attested or stronger is on record for any activity in the file."]


def _file_lines(fc: Dict[str, Any]) -> List[str]:
    out = []
    dd = fc["data_date"]
    out.append(f"- Data date {dd.isoformat()} ({fc['file_age_days']} days old)." if dd
               else "- The file states no data date.")
    comp = fc["completion"]
    if comp["file_finish"]:
        out.append(f"- Latest planned finish in the file: {comp['file_finish'].isoformat()} "
                   f"({comp['file_finish_source']}), {comp['last']['name']} ({comp['last']['id']}).")
    late = [r for r in fc["plan_vs_actual"] if r["past_planned_finish_no_done"]]
    if late:
        out.append(f"- Past the file's planned finish with no done evidence on record ({len(late)}). Two records side "
                   "by side, not a delay and not a cause:")
        out += _cap([f"  - {r['name']} ({r['id']}): planned finish {r['file']['planned_finish'].isoformat()}"
                     + ("" if r["mapped"] else "; LeveLog cannot match evidence to this activity's name")
                     for r in late])
    else:
        out.append("- No activity is past the file's planned finish without done evidence or the file's own actual finish.")
    stated = []
    for r in fc["plan_vs_actual"]:
        f = r["file"]
        if f["actual_start"] or f["actual_finish"]:
            stated.append(f"- {r['name']} ({r['id']}): the file states actual start {f['actual_start'] or 'none'}, "
                          f"actual finish {f['actual_finish'] or 'none'}.")
        if f["stated_percent"] is not None:
            stated.append(f"- {r['name']} ({r['id']}): the file states {f['stated_percent']:g}% (the file's figure).")
        if f["baseline_finish"] and f["current_finish"] and f["baseline_finish"] != f["current_finish"]:
            stated.append(f"- {r['name']} ({r['id']}): baseline finish {f['baseline_finish']}, current finish "
                          f"{f['current_finish']} (both the file's).")
    out += _cap(stated)
    down = fc["downstream"]
    if late and not down["logic"]:
        out.append("- The file carries no predecessor logic, so the impact on later work is unknown.")
    elif late and not down["impacts"]:
        out.append("- The file links no later work to the activities above.")
    out += _cap([f"- {i['name']} ({i['id']}) follows {i['late_name']} ({i['late_id']}) by the file's link "
                 f"({_link_words(i['link'])}): {i['depends']}. Planned start "
                 f"{i['planned_start'].isoformat() if i['planned_start'] else 'not stated'}."
                 for i in down["impacts"]])
    return out


def _reported_lines(fc: Dict[str, Any]) -> List[str]:
    out = [f"- {r['name']} ({r['id']}): first reported {_day(r['reported']['first'])}, last {_day(r['reported']['last'])}, "
           f"{r['reported']['days']} day(s)." for r in fc["plan_vs_actual"] if r["reported"]["first"]]
    return _cap(out) or ["- No filed log names the work of any activity in the file."]


def _estimate_lines(fc: Dict[str, Any]) -> List[str]:
    out = []
    for i in fc["downstream"]["impacts"]:
        e = i["estimate"]
        if not e:
            out.append(f"- {i['name']} ({i['id']}): no date computed: {i['no_estimate']}.")
            continue
        planned = e["planned"].isoformat() if e["planned"] else "not stated"
        verb = ("would " + e["which"] + f" no earlier than {e['not_before'].isoformat()} (file plans {planned})"
                if e["shifted"] else f"the file's planned {e['which']} {planned} still falls after "
                                     f"{e['not_before'].isoformat()}")
        out.append(f"- ESTIMATE: {e['subject']} {verb}, IF {e['assumption']}. Basis: {e['basis']}.")
    for c in fc["cycles"]:
        if not c["estimate"]:
            out.append(f"- {c['label']}: {c['no_estimate']} ({c['sample']} of {len(c['levels'])} levels in the file have "
                       f"both a start and a done marker; {MIN_CYCLE_LEVELS} are needed).")
            continue
        e = c["estimate"]
        out.append(f"- ESTIMATE: {e['subject']}: {e['min_days']}-{e['max_days']} days, median {e['median_days']:g}, "
                   f"from {e['sample']} levels. Basis: {e['basis']}.")
        for o in c["overrun"]:
            out.append(f"- {c['label']} {W.level_label(o['level'])}: started on record {_day(o['start'])}; the longest "
                       f"observed cycle would have ended {_day(o['latest'])} and no done marker is on record, so no "
                       "finish estimate is given.")
        for f in c["finishes"]:
            out.append(f"- ESTIMATE: {f['subject']} between {f['earliest'].isoformat()} and {f['latest'].isoformat()} "
                       f"(median {f['median'].isoformat()}). Basis: {f['basis']}; {f['note']}.")
    comp = fc["completion"]
    if comp["estimate"]:
        e = comp["estimate"]
        out.append(f"- ESTIMATE, project completion: the activity that finishes last in the file, {comp['last']['name']}, "
                   f"between {e['earliest'].isoformat()} and {e['latest'].isoformat()}. Basis: {e['basis']}.")
    else:
        out.append(f"- Project completion: {comp['no_estimate'] or 'no completion forecast'}.")
    return out


GROUPS = (("verified", "VERIFIED (attested or stronger: start and done markers)"),
          ("file", "FILE (the confirmed schedule's own dates and logic; a plan, not evidence of work)"),
          ("reported", "REPORTED (filed daily logs; a report is never a start marker or a finish)"),
          ("estimate", "ESTIMATES (computed by LeveLog, NOT verified; each with its basis)"))

RULE = ("Keep these four groups apart. Only VERIFIED and FILE are facts; REPORTED is what logs say and is never a finish; "
        "an ESTIMATE line must be called an estimate with its basis and assumption. Activity dates, crew counts, a crew "
        "moving between floors, check-ins, report frequency and photos are not proof of a rate. ")
RULE_NO_ESTIMATE = RULE + "Do not give a forecast, a rate, a percent complete, a delay or a cause: none is on record."
RULE_WITH_ESTIMATE = (RULE + "Give no forecast, rate or date beyond the ESTIMATE lines; no percent complete unless "
                      "the FILE states one, as the file's; never a delay cause.")


def report_section(fc: Dict[str, Any]) -> Dict[str, Any]:
    """{"title", "groups": [{"key", "label", "lines"}], "estimates": [items]}:
    for a report, the same four groups the assistant gets, in the same order."""
    makers = {"verified": _verified_lines, "file": _file_lines, "reported": _reported_lines, "estimate": _estimate_lines}
    return {"title": "Schedule status", "groups": [{"key": k, "label": label, "lines": makers[k](fc)} for k, label in GROUPS],
            "estimates": estimates(fc), "unreadable": list(fc.get("unreadable") or ()),
            "unreadable_line": unreadable_line(fc)}


def unreadable_line(fc: Dict[str, Any]) -> Optional[str]:
    """The same words for the assistant and the report: a source that could
    not be read makes "no done marker" mean only "not read"."""
    if not fc.get("unreadable"):
        return None
    return ("Could not be read just now: " + ", ".join(s.replace("_", " ") for s in fc["unreadable"])
            + ". What they hold is unknown, so a missing start or done marker may only mean it was not read.")


def status_text(fc: Dict[str, Any], job: str = "") -> str:
    sec = report_section(fc)
    out = [f"SCHEDULE STATUS{' for ' + job if job else ''}, against the confirmed schedule file, as of {_day(fc['today'])}."]
    if sec["unreadable_line"]:
        out.append(sec["unreadable_line"])
    for g in sec["groups"]:
        out.append(g["label"] + ":")
        out += g["lines"]
    out.append(RULE_WITH_ESTIMATE if sec["estimates"] else RULE_NO_ESTIMATE)
    return "\n".join(out)


def lookahead_with_status(schedule: Dict[str, Any], items: Sequence[Item], rows: Sequence[Dict[str, Any]], *,
                          today: date, days: int, logs_from: date, project_id: Any, job: str = "",
                          unreadable: Iterable[str] = ()) -> str:
    """The lookahead (lib/progress_plan.py) with the status groups after it.
    The lookahead's closing rule forbids any forecast; when this status holds
    a labelled estimate that rule is replaced by the status's own."""
    head = PP.lookahead_text(schedule, rows, today=today, days=days, logs_from=logs_from)
    head = head.replace("\n" + PP.LOOKAHEAD_RULE, "")
    return head + "\n\n" + status_text(forecast(schedule, items, rows, today=today, project_id=project_id,
                                                unreadable=unreadable), job)


# ── ITEMS FROM WHAT IS STORED TODAY ────────────────────────────────────────

def items_from_inspection_reports(rows: Iterable[Dict[str, Any]], project_id: Any) -> List[Item]:
    """Attested inspection statements (lib/inspection_reports.py) as evidence:
    passed -> done, failed -> failed, on the gate's node. A document whose
    result could not be read, an unresolved row, a partial pass and a booking
    mark nothing, and nor does hearsay ("Joe said it passed"). The date is the
    one they said; with none, the inspection date is UNKNOWN (the day it was
    said is carried as `said_at`, for order only, never printed as the date)."""
    out = []
    for r in rows:
        if r.get("status") != "attested" or not r.get("gate") or r.get("result") not in ("passed", "failed"):
            continue
        if r.get("hearsay_from"):
            continue
        levels = [str(x) for x in r.get("levels") or []]
        if not levels:
            continue
        said = r.get("created_at") if isinstance(r.get("created_at"), datetime) else None
        out.append(E.item("attested", "done" if r["result"] == "passed" else "failed", source="inspection_reports",
                          ref=r.get("_id") or "", project_id=project_id, node=r["gate"], levels=levels,
                          on=_iso(r.get("inspected_on")), by=r.get("reporter_name") or None,
                          quote=r.get("quote"), shared=len(levels) > 1, said_at=said))
    return out
