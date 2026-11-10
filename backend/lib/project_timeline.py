"""WHAT LEVELOG WOULD HAVE BELIEVED ON A GIVEN DAY.

as_of(items, model, D) keeps only what was on record on D -- an item dated on
or before D and, when it says when it was said, said on or before D -- and
answers from that alone: per level and kind of work (evidence.status of the
facts, plus any inference lib/construction_inference draws), per subcontractor
(history and current activity), per activity (where and when), per unit (only
what a record names), with the refs behind every word.

Nothing dated after D is read, so the answer for D never improves with
hindsight. An item with no date and no said_at is left out of every as-of
answer (it cannot be shown to have existed on D) and counted.

STATE OF ONE SUBJECT (subject_state), strongest first:
  done_<rung> / failed_<rung>   a fact at attested or stronger
  inferred_done_<confidence>    an inference that the work is in place
  inferred_in_progress_<conf>   an inference that the work is under way
  in_progress_<rung> / reported / scheduled_<rung> ... as evidence.status says
  unknown                       nothing on record: NEVER "not done"

Pure: no database, no network.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from lib import construction_inference as CI
from lib import evidence as E

#: A sub's latest work record within this many days of D is its current activity.
CURRENT_DAYS = 14


def _on(i: Dict[str, Any]) -> Optional[date]:
    v = i.get("on")
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _said(i: Dict[str, Any]) -> Optional[date]:
    v = i.get("said_at")
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def visible(items: Iterable[Dict[str, Any]], as_of: date) -> List[Dict[str, Any]]:
    """The items on record on `as_of`."""
    out = []
    for i in items:
        d, s = _on(i), _said(i)
        if d is None and s is None:
            continue
        if (d is not None and d > as_of) or (s is not None and s > as_of):
            continue
        out.append(i)
    return out


def _iso(d: Any) -> Any:
    return d.isoformat() if isinstance(d, (date, datetime)) else d


def subject_state(facts: Sequence[Dict[str, Any]], inferences: Sequence[Dict[str, Any]]) -> str:
    st = E.status(facts)
    if st.startswith(("done_", "failed_")):
        return st
    for claim in ("done", "in_progress"):
        mine = [i for i in inferences if i.get("claim") == claim]
        if mine:
            best = min(mine, key=lambda i: E.CONFIDENCE.index(i["confidence"]) * -1)
            return f"inferred_{claim}_{best['confidence']}"
    return st


def system_state(snapshot: Dict[str, Any], level: str, system: str) -> Dict[str, Any]:
    """The state of a system's rough-in on a level as of the snapshot: the
    facts about any of its nodes or its gate's implication, and its inference."""
    nodes = set(CI.SYSTEMS[system])
    facts = [i for i in snapshot["_facts"] if i.get("node") in nodes and level in (i.get("levels") or ())]
    infs = [i for i in snapshot["inferences"] if i.get("node") == f"rough_{system}" and level in i["levels"]]
    st = subject_state(facts, infs)
    return {"level": level, "system": system, "state": st, "facts": [i["ref"] for i in facts],
            "inference": infs[0]["ref"] if infs else None,
            "confidence": infs[0]["confidence"] if infs else None}


def _brief(i: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": i["kind"], "claim": i["claim"], "node": i.get("node"), "levels": i.get("levels"),
            "sub": i.get("sub"), "on": _iso(_on(i)), "source": i.get("source"), "ref": i.get("ref"),
            "quote": (i.get("quote") or "")[:120]}


def as_of(items: Sequence[Dict[str, Any]], model: Dict[str, Any], day: date, *, project_id: Any = "",
          headcounts: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    vis = visible(items, day)
    facts = [i for i in vis if E.is_fact(i)]
    ci = CI.infer(facts, model, as_of=day, project_id=project_id,
                  headcounts=[h for h in headcounts if not isinstance(h.get("date"), date) or h["date"] <= day])
    allf = facts + ci["implications"]
    levels = list(model.get("levels") or ())
    nodes = sorted({i["node"] for i in allf if i.get("node")})
    per_level: Dict[str, Dict[str, Any]] = {}
    for lv in levels:
        cells = {}
        for n in nodes:
            mine = [i for i in allf if i.get("node") == n and lv in (i.get("levels") or ())]
            if not mine:
                continue
            ds = sorted(d for d in (_on(i) for i in mine) if d)
            cells[n] = {"status": E.status(mine), "first": _iso(ds[0]) if ds else None,
                        "last": _iso(ds[-1]) if ds else None, "refs": sorted({i["ref"] for i in mine}),
                        "subs": sorted({i["sub"] for i in mine if i.get("sub")}),
                        "shared_only": all(len(i.get("levels") or ()) > 1 for i in mine)}
        systems = {s: system_state({"_facts": allf, "inferences": ci["inferences"]}, lv, s)
                   for s in CI.SYSTEMS if s != "sprinkler" or (model.get("systems") or {}).get("sprinkler")}
        per_level[lv] = {"work": cells, "systems": systems, "stages": ci["stages"].get(lv, {})}
    # Subs: every dated record, the latest work record, presence days.
    subs: Dict[str, Dict[str, Any]] = {}
    by_sub: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for i in facts:
        if i.get("sub") and _on(i):
            by_sub[i["sub"]].append(i)
    for s, rows in sorted(by_sub.items()):
        work = sorted((i for i in rows if i.get("node") and i["claim"] in E.WORK_CLAIMS and i["claim"] != "present"),
                      key=lambda i: (_on(i), i["ref"]))
        present = sorted({_on(i) for i in rows if i.get("source") == "checkins"})
        last = work[-1] if work else None
        recent = bool(last) and (day - _on(last)).days <= CURRENT_DAYS
        cur = [i for i in work if last and _on(i) == _on(last)]
        subs[s] = {"first": _iso(min(_on(i) for i in rows)), "last": _iso(max(_on(i) for i in rows)),
                   "gate_days": len(present), "work_records": len(work),
                   "current_activity": ({"on": _iso(_on(last)), "nodes": sorted({i["node"] for i in cur}),
                                         "levels": sorted({lv for i in cur for lv in i.get("levels") or ()}),
                                         "refs": [i["ref"] for i in cur]} if recent else None),
                   "current_activity_determinable": recent,
                   "why_not": None if recent else ("no work record names this sub" if not last else
                                                   f"latest work record {_iso(_on(last))} is more than {CURRENT_DAYS} days old"),
                   "history": [_brief(i) for i in work][-40:]}
    # Activities: node -> where and when.
    acts: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        mine = [i for i in allf if i.get("node") == n and _on(i)]
        if mine:
            acts[n] = {"first": _iso(min(_on(i) for i in mine)), "last": _iso(max(_on(i) for i in mine)),
                       "levels": sorted({lv for i in mine for lv in i.get("levels") or ()}),
                       "subs": sorted({i["sub"] for i in mine if i.get("sub")}), "records": len(mine)}
    units = {lv: {"units": u, "unit_records": [i["ref"] for i in allf if i.get("space") in u]}
             for lv, u in (model.get("units") or {}).items()}
    return {"as_of": day.isoformat(), "visible_items": len(vis), "levels": per_level, "subs": subs,
            "activities": acts, "units": units, "building": _building_rows(allf),
            "inferences": ci["inferences"], "implications": ci["implications"],
            "contradictions": ci["contradictions"], "closure": ci["closure"],
            "_facts": allf}


def _building_rows(facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for n in sorted({i["node"] for i in facts if i.get("node") and not i.get("levels")}):
        mine = [i for i in facts if i.get("node") == n and not i.get("levels")]
        out[n] = {"status": E.status(mine), "refs": sorted({i["ref"] for i in mine})}
    return out


def weekly(items: Sequence[Dict[str, Any]], model: Dict[str, Any], start: date, end: date, **kw: Any) -> List[Dict[str, Any]]:
    """A snapshot every 7 days from `start`, and one on `end`."""
    days, d = [], start
    while d < end:
        days.append(d)
        d += timedelta(days=7)
    days.append(end)
    return [as_of(items, model, d, **kw) for d in days]


def public(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """The snapshot without its working list of facts (JSON-ready dates)."""
    return _jsonable({k: v for k, v in snapshot.items() if not k.startswith("_")})


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v
