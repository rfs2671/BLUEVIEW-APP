"""ONE STATUS OF THE WHOLE BUILDING, FROM THE EVIDENCE.

    "How is 588 doing overall?"    "Where is Arkon at?"    "How is floor 3?"

Pure: no database, no network. The caller hands in evidence items in the shape
of lib/evidence.py (THE CONTRACT: its ladder, its `status`), the job's levels,
optionally the confirmed schedule and design quantities by level. Nothing here
loads or stores anything, so there is no second copy of the record to drift.

THE SCOPE FRAME is levels x work. The LEVELS are the job's own, each with where
it came from: the project's fields (`building_stories`, `has_*`), the plan
sheets' level tokens, or only because some evidence names it. The WORK is the
standard sequence (app/scheduling/graph_v1.py, the operator-approved template,
per-level steps only, as lib/progress_plan.py lays it over a level) plus any
site / structure steps lib/work_nodes.py defines when that module exists. The
frame is a template over this job: every answer says so, and it is never this
job's own schedule.

ONE CELL is one level and one step. Its status is evidence.status() of its
items, never anything computed here. Its BUCKET is what the answer counts:

  done            done_attested or stronger. Nothing below attested says done.
  failed          a failure stated at attested or stronger is the newest word.
  underway        reported or photographed in progress within RECENT_DAYS.
  not_shown_done  it has records, none says done, none is recent.
  unknown         NO ITEMS. Unknown is not "not done": it is nothing on record,
                  either way, and it is never counted or worded as outstanding.

NO PERCENT is computed, anywhere. Overall is a COUNT of level-and-work cells
with the frame's source. A percent appears only where a source states one, and
always with that source's name ("schedule file states 40%"). Design scope from
the takeoff is shown beside a cell as "design scope"; the installed quantity is
unknown unless a source states one.

ESTIMATES ARE NEVER FACTS. An estimate item never decides a status, never is a
supporting item, never is counted; it is carried apart, labelled with its basis.

A BOTTLENECK is stated as "open on the record": the earliest work in sequence
on a level whose prior steps all have done records and which itself has none,
and the inspections there with no record or a failure on record. It never
names a cause.

CONFLICTS are records that disagree, for the confirmations lane to ask about:
done stated and a later failure; work recorded before a prerequisite
inspection has any record; a photo described as showing work on a level whose
logs name nobody there that day.
"""

from __future__ import annotations

import heapq
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.scheduling.graph_v1 import build_graph_v1
from lib import evidence as E
from lib import progress_plan as PP
from lib import work_state as W
from lib.plans import level_suggestion as LS

try:  # Site and structure steps, from a parallel lane. Absent: graph_v1 alone.
    from lib import work_nodes as _WORK_NODES  # type: ignore
except ImportError:  # pragma: no cover - depends on what is merged
    _WORK_NODES = None

RECENT_DAYS = W.REPORTED_RECENT_DAYS
BUCKETS = ("done", "failed", "underway", "not_shown_done", "unknown")
DONE_KINDS = ("verified", "confirmed", "attested")
MAX_TEXT_LEVELS = 12
MAX_ITEMS_PER_CELL = 6

FRAME_SOURCE = ("the standard sequence (graph_v1, an operator-approved template laid over each level), "
                "not this job's own schedule")
LEVEL_SOURCES = {"project_fields": "project fields", "plan_sheets": "plan sheets",
                 "evidence": "named only by the records"}
SOURCE_WORDS = {"checkins": "gate check-ins", "logbooks": "filed daily logs", "photo_index": "daily-log photos",
                "whatsapp": "WhatsApp", "inspection_reports": "inspection reports"}
UNKNOWN_WORDS = "no record (unknown means nothing is on record, either way)"
NO_PERCENT = "No percent complete is on record, so none is given."
GUARD = ("Say what is on record and what is unknown. Unknown means nothing is on record, either way. Give no "
         "percent unless a line above says which source states it, no cause, and no date that is not printed here.")


# ── LEVELS ─────────────────────────────────────────────────────────────────

def _valid_level(token: Any) -> bool:
    return isinstance(token, str) and (token in LS.LABELS or LS.floor_number(token) is not None)


def level_order(token: str) -> Tuple[int, int]:
    """Bottom of the building to the top."""
    n = LS.floor_number(token)
    if n is not None:
        return (1, n)
    if token in LS.BELOW:
        return (0, LS.BELOW.index(token))
    return (2, LS.ABOVE.index(token) if token in LS.ABOVE else 99)


_LEVEL_FIELDS = (("has_sub_cellar", LS.SUB_CELLAR), ("has_cellar", LS.CELLAR),
                 ("has_mezzanine", LS.MEZZANINE), ("has_roof_bulkhead", LS.ROOF))


def job_levels(project: Optional[Dict[str, Any]] = None, plan_tokens: Iterable[str] = (),
               items: Iterable[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """[{"level", "label", "sources": [...]}] bottom to top. A `has_*` field
    that is None is nobody said: it adds nothing (it does not assert absence)."""
    found: Dict[str, List[str]] = {}

    def add(token: str, source: str) -> None:
        if _valid_level(token) and source not in found.setdefault(token, []):
            found[token].append(source)

    p = project or {}
    try:
        stories = int(p.get("building_stories") or 0)
    except (TypeError, ValueError):
        stories = 0
    for n in range(1, min(stories, LS.MAX_SUGGESTED_STORIES) + 1):
        add(f"{LS.FLOOR_PREFIX}{n}", "project_fields")
    for field, token in _LEVEL_FIELDS:
        if p.get(field) is True:
            add(token, "project_fields")
    for token in plan_tokens or ():
        add(token, "plan_sheets")
    for i in items or ():
        if i.get("kind") == "estimate":
            continue
        for lv in i.get("levels") or ():
            add(lv, "evidence")
    return [{"level": t, "label": W.level_label(t), "sources": found[t]} for t in sorted(found, key=level_order)]


# ── THE WORK: graph_v1 per level, plus site / structure steps if defined ───

def _gate_label(node: Any) -> str:
    return W._GATE_WORDS.get(node.inspection_type, node.inspection_type.replace("_", " "))


def _extra_steps() -> Tuple[List[Dict[str, Any]], str]:
    """lib/work_nodes.py's steps, read by duck type: a NODES list or a nodes()
    callable of {"id", "label"?, "after"?, "gate"?, "trade"?}. Anything else is
    ignored and said so."""
    if _WORK_NODES is None:
        return [], "absent"
    raw = getattr(_WORK_NODES, "NODES", None)
    if raw is None and callable(getattr(_WORK_NODES, "nodes", None)):
        try:
            raw = _WORK_NODES.nodes()
        except Exception:  # noqa: BLE001 - another lane's module never stops a status
            raw = None
    out = []
    for n in raw or ():
        if isinstance(n, dict) and n.get("id"):
            out.append({"id": str(n["id"]), "label": str(n.get("label") or str(n["id"]).replace("_", " ")),
                        "gate": bool(n.get("gate")), "conditional": bool(n.get("requires")),
                        "trade": str(n.get("trade") or ""), "after": [str(a) for a in n.get("after") or ()],
                        "source": "work_nodes"})
    return out, ("read" if out else "no steps read")


def steps(flags: Optional[Dict[str, Any]] = None, extra: Optional[Sequence[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The frame's work in dependency order: [{"id", "label", "gate",
    "conditional", "trade", "after": [direct prior steps], "source"}]."""
    g = build_graph_v1()
    per = PP._per_level_nodes(flags)
    ids = {n.id for n in per}
    before: Dict[str, List[str]] = defaultdict(list)
    for e in g.edges:
        if e.from_node in ids and e.to_node in ids:
            before[e.to_node].append(e.from_node)
    graph = [{"id": n.id, "label": _gate_label(n) if W._is_gate(n) else W.node_label(n.id), "gate": W._is_gate(n),
              "conditional": bool(n.requires), "trade": "inspection" if W._is_gate(n) else n.trade,
              "after": list(before.get(n.id, [])), "source": "graph_v1"} for n in per]
    extra = list(_extra_steps()[0] if extra is None else extra)
    known = {s["id"] for s in graph}
    extra = [s for s in extra if s["id"] not in known]
    every = extra + graph
    rank = {s["id"]: i for i, s in enumerate(every)}
    waiting = {s["id"]: sum(1 for a in s["after"] if a in rank) for s in every}
    after_me: Dict[str, List[str]] = defaultdict(list)
    for s in every:
        for a in s["after"]:
            if a in rank:
                after_me[a].append(s["id"])
    ready = [(rank[i], i) for i, c in waiting.items() if c == 0]
    heapq.heapify(ready)
    order: List[str] = []
    while ready:
        _r, i = heapq.heappop(ready)
        order.append(i)
        for j in after_me[i]:
            waiting[j] -= 1
            if waiting[j] == 0:
                heapq.heappush(ready, (rank[j], j))
    order += [s["id"] for s in every if s["id"] not in order]   # a cycle in another lane's data: kept, unordered
    by_id = {s["id"]: s for s in every}
    return [by_id[i] for i in order]


# ── ONE CELL ───────────────────────────────────────────────────────────────

def _on(i: Dict[str, Any]) -> Optional[date]:
    v = i.get("on")
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def strongest_first(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strongest rung first, newest first within a rung. Estimates never."""
    return sorted((i for i in items if i["kind"] != "estimate"),
                  key=lambda i: (E.rank(i["kind"]), -(_on(i).toordinal() if _on(i) else 0), str(i.get("ref"))))


def bucket(status: str, facts: Sequence[Dict[str, Any]], today: date) -> str:
    if status.startswith("done_"):
        return "done"
    if status.startswith("failed_"):
        return "failed"
    if not facts:
        return "unknown"
    for i in facts:
        d = _on(i)
        if (i["kind"] in ("reported", "observed") and i["claim"] in ("in_progress", "started")
                and d and 0 <= (today - d).days <= RECENT_DAYS):
            return "underway"
    return "not_shown_done"


def deciding_item(status: str, facts: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The item evidence.status() read its done / failed from."""
    if not (status.startswith("done_") or status.startswith("failed_")):
        return None
    claim, kind = status.split("_", 1)
    mine = [i for i in facts if i["kind"] == kind and i["claim"] in ("done", "failed")]
    mine.sort(key=lambda i: _on(i).toordinal() if _on(i) else 0)
    return mine[-1] if mine and mine[-1]["claim"] == claim else None


def _brief(i: Dict[str, Any]) -> Dict[str, Any]:
    keep = ("kind", "claim", "source", "ref", "on", "by", "sub", "quote", "shared", "levels", "stated_percent", "note")
    return {k: i.get(k) for k in keep}


def _schedule_for(schedule: Optional[Dict[str, Any]], node: str, level: str) -> List[Dict[str, Any]]:
    """The confirmed file's activities naming this work on this level, as the
    file states them (work_state's reading)."""
    if not schedule:
        return []
    return [{"id": a.get("id"), "name": a.get("name"), "planned_finish": W.planned_finish(a),
             "actual_finish": a.get("actual_finish"), "percent_complete": a.get("percent_complete")}
            for a in W._schedule_rows(schedule, node, level)[:3]]


def cell(items: Sequence[Dict[str, Any]], level: str, node: str, today: date, *,
         design: Sequence[Dict[str, Any]] = (), schedule: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    mine = [i for i in items if i.get("node") == node and level in (i.get("levels") or ())]
    facts = [i for i in mine if i["kind"] != "estimate"]
    status = E.status(facts)
    days = sorted({d for d in (_on(i) for i in facts) if d})
    ordered = strongest_first(facts)
    dec = deciding_item(status, facts)
    stated = [{"percent": i["stated_percent"], "source": i["source"], "ref": i["ref"]}
              for i in facts if i.get("stated_percent") is not None]
    sched = _schedule_for(schedule, node, level)
    stated += [{"percent": a["percent_complete"], "source": "schedule file", "ref": str(a["id"])}
               for a in sched if a.get("percent_complete") is not None]
    return {
        "level": level, "node": node, "status": status, "bucket": bucket(status, facts, today),
        "items": [_brief(i) for i in ordered[:MAX_ITEMS_PER_CELL]], "item_count": len(facts),
        "decided_by": _brief(dec) if dec else None,
        "first": days[0] if days else None, "last": days[-1] if days else None,
        "subs": sorted({i["sub"] for i in facts if i.get("sub")}),
        "kinds": sorted({i["kind"] for i in facts}, key=E.rank),
        # True when every record names several places together ("floors 1-4").
        "shared_only": bool(facts) and all(i.get("shared") or len(i.get("levels") or ()) > 1 for i in facts),
        "estimates": [{"basis": i["basis"], "claim": i["claim"], "on": i.get("on"), "note": i.get("note"),
                       "label": "estimate, not a fact"} for i in mine if i["kind"] == "estimate"],
        "design_scope": [dict(d) for d in design],
        "installed": None,                       # no source states an installed quantity
        "stated_percents": stated,
        "schedule": sched,
    }


# ── THE WHOLE BUILDING ─────────────────────────────────────────────────────

def _design_index(design: Iterable[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for d in design or ():
        if d.get("node") and d.get("level") and d.get("qty") is not None:
            out[(str(d["node"]), str(d["level"]))].append(
                {"qty": d["qty"], "unit": d.get("unit") or "", "item": d.get("item") or "", "source": d.get("source") or "takeoff"})
    return out


def design_from_takeoff(lines: Iterable[Any], trade_nodes: Dict[str, str]) -> List[Dict[str, Any]]:
    """Design quantities by level from lib/plan_takeoff_export Lines: only a
    verified Floor-scope line whose trade the CALLER maps to a step. No mapping
    is assumed here: a takeoff trade is not a step of the sequence by itself."""
    out = []
    for ln in lines or ():
        node = trade_nodes.get(getattr(ln, "trade", ""))
        if not node or getattr(ln, "qty", None) is None or getattr(ln, "scope", "") != "Floor":
            continue
        levels = LS.tokens_in(getattr(ln, "level", ""))[0]   # the plan readers' own level reader
        if len(levels) == 1:
            out.append({"node": node, "level": levels[0], "qty": ln.qty, "unit": ln.unit,
                        "item": f"{ln.item} {ln.tag}".strip(), "source": f"takeoff, {ln.sheets}"})
    return out


def build(items: Sequence[Dict[str, Any]], *, today: date, project: Optional[Dict[str, Any]] = None,
          plan_tokens: Iterable[str] = (), schedule: Optional[Dict[str, Any]] = None,
          design: Iterable[Dict[str, Any]] = (), flags: Optional[Dict[str, Any]] = None,
          extra_steps: Optional[Sequence[Dict[str, Any]]] = None, job: str = "") -> Dict[str, Any]:
    """The status of the whole building from `items` (lib/evidence.py shape)."""
    items = [i for i in items if i.get("kind") in E.KINDS]
    levels = job_levels(project, plan_tokens, items)
    seq = steps(flags, extra_steps)
    dix = _design_index(design)
    cells = {(lv["level"], s["id"]): cell(items, lv["level"], s["id"], today, design=dix.get((s["id"], lv["level"]), ()),
                                         schedule=schedule)
             for lv in levels for s in seq}
    frame_ids = {s["id"] for s in seq}
    outside = sorted({(lv, i["node"]) for i in items if i.get("node") and i["node"] not in frame_ids
                      and i["kind"] != "estimate" for lv in i.get("levels") or ()}, key=lambda k: (level_order(k[0]), k[1]))
    model = {
        "job": job, "today": today,
        "frame": {"levels": levels, "steps": seq, "cells": len(cells), "source": FRAME_SOURCE,
                  "work_nodes": "read" if any(s["source"] == "work_nodes" for s in seq) else _extra_steps()[1]},
        "cells": cells,
        "outside_frame": [cell(items, lv, n, today) for lv, n in outside],
        "counts": dict(Counter(c["bucket"] for c in cells.values())),
        "status_counts": dict(Counter(c["status"] for c in cells.values())),
        "has_schedule": bool(schedule),
    }
    model["by_level"] = {lv["level"]: _level_summary(model, lv["level"]) for lv in levels}
    model["subs"] = subs(items, model)
    model["conflicts"] = conflicts(items, model)
    model["timeline"] = timeline(items, model)
    model["estimates"] = sum(1 for i in items if i["kind"] == "estimate")
    return model


def _cells_on(model: Dict[str, Any], level: str) -> List[Dict[str, Any]]:
    return [model["cells"][(level, s["id"])] for s in model["frame"]["steps"]]


def bottleneck(model: Dict[str, Any], level: str) -> Dict[str, Any]:
    """Open on the record, never a cause: the work in sequence order whose
    prior steps all have done records and which itself has none (earliest
    first), and the inspections on this level with no record or a failure."""
    seq = model["frame"]["steps"]
    done = {s["id"] for s in seq if model["cells"][(level, s["id"])]["bucket"] == "done"}
    open_work = [s["id"] for s in seq if not s["gate"] and s["id"] not in done
                 and all(a in done for a in s["after"])]
    gates = [{"node": s["id"], "label": s["label"], "bucket": model["cells"][(level, s["id"])]["bucket"],
              "conditional": s["conditional"]}
             for s in seq if s["gate"] and model["cells"][(level, s["id"])]["bucket"] in ("unknown", "failed")]
    return {"level": level, "earliest_open": open_work[0] if open_work else None, "open_work": open_work, "gates": gates}


def _level_summary(model: Dict[str, Any], level: str) -> Dict[str, Any]:
    cs = _cells_on(model, level)
    return {"counts": dict(Counter(c["bucket"] for c in cs)), "bottleneck": bottleneck(model, level)}


# ── BY SUBCONTRACTOR ───────────────────────────────────────────────────────

_FAMILY = {"plumbing": "plumbing", "plumbing_gas": "plumbing", "mechanical": "mechanical", "electrical": "electrical",
           "electrical_lv": "electrical", "fire_protection": "fire_protection", "carpentry": "carpentry",
           "drywall": "drywall", "painting": "painting", "finishes": "finishes"}
_TRIM_FAMILIES = {"plumbing", "mechanical", "electrical", "fire_protection"}


def _sub_key(name: Any) -> str:
    return " ".join(str(name or "").lower().split())


def subs(items: Sequence[Dict[str, Any]], model: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{display name: what the records hold about that sub}. Never a percent."""
    seq = model["frame"]["steps"]
    by_id = {s["id"]: s for s in seq}
    order = {s["id"]: k for k, s in enumerate(seq)}
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    names: Dict[str, str] = {}
    for i in items:
        if i["kind"] == "estimate" or not _sub_key(i.get("sub")):
            continue
        k = _sub_key(i["sub"])
        names.setdefault(k, " ".join(str(i["sub"]).split()))
        groups[k].append(i)
    out = {}
    for k, mine in groups.items():
        work = sorted({(lv, i["node"]) for i in mine if i.get("node") for lv in i.get("levels") or ()},
                      key=lambda w: (level_order(w[0]), order.get(w[1], len(order)), w[1]))
        days = sorted({d for d in (_on(i) for i in mine) if d})
        present = sorted({d for d in (_on(i) for i in mine if i["claim"] == "present") if d})
        nodes = sorted({n for _lv, n in work}, key=lambda n: (order.get(n, len(order)), n))
        out[names[k]] = {
            "sub": names[k], "work": [{"level": lv, "node": n,
                                       "bucket": (model["cells"].get((lv, n)) or {}).get("bucket", "outside_frame"),
                                       "status": (model["cells"].get((lv, n)) or {}).get("status")} for lv, n in work],
            "levels": sorted({lv for lv, _n in work}, key=level_order), "nodes": nodes,
            "first": days[0] if days else None, "last": days[-1] if days else None,
            "presence_days": len(present), "present_first": present[0] if present else None,
            "present_last": present[-1] if present else None,
            "presence_sources": sorted({i["source"] for i in mine if i["claim"] == "present"}),
            "next": _next_for(model, nodes),
        }
    return out


def _next_for(model: Dict[str, Any], nodes: Sequence[str]) -> List[Dict[str, Any]]:
    """By the standard sequence, per level: the first step of the sub's own
    trade(s) that is not shown done. A template's order, not an assignment."""
    seq = model["frame"]["steps"]
    by_id = {s["id"]: s for s in seq}
    fams = {_FAMILY.get(by_id[n]["trade"]) for n in nodes if n in by_id} - {None}
    if not fams:
        return []
    mine = [s["id"] for s in seq if not s["gate"] and (s["id"] in nodes or _FAMILY.get(s["trade"]) in fams
                                                       or (s["id"] == "mep_trim" and fams & _TRIM_FAMILIES))]
    out = []
    for lv in model["frame"]["levels"]:
        for n in mine:
            c = model["cells"][(lv["level"], n)]
            if c["bucket"] != "done":
                out.append({"level": lv["level"], "node": n, "bucket": c["bucket"]})
                break
    return out


def find_subs(model: Dict[str, Any], name: Any) -> List[str]:
    """Subs whose name holds these words, by whole word ("Arkon" -> "Arkon Builders")."""
    words = [w for w in re.split(r"\W+", str(name or "")) if w]
    if not words:
        return []
    rx = [re.compile(rf"(?<!\w){re.escape(w)}(?!\w)", re.I) for w in words]
    exact = [s for s in model["subs"] if _sub_key(s) == _sub_key(name)]
    return exact or [s for s in model["subs"] if all(r.search(s) for r in rx)]


# ── CONFLICTS, FOR THE CONFIRMATIONS LANE ──────────────────────────────────

def conflicts(items: Sequence[Dict[str, Any]], model: Dict[str, Any]) -> List[Dict[str, Any]]:
    seq = model["frame"]["steps"]
    by_id = {s["id"]: s for s in seq}
    facts = [i for i in items if i["kind"] != "estimate"]
    out: List[Dict[str, Any]] = []
    for (lv, n), _c in model["cells"].items():
        mine = [i for i in facts if i.get("node") == n and lv in (i.get("levels") or ())]
        if not mine:
            continue
        label, where = by_id[n]["label"], W.level_label(lv)
        # 1. done stated at attested or stronger, then a failure stated after it
        dones = [i for i in mine if i["claim"] == "done" and i["kind"] in DONE_KINDS and _on(i)]
        for d in dones:
            later = [i for i in mine if i["claim"] == "failed" and _on(i) and _on(i) > _on(d)]
            if later:
                f = max(later, key=lambda i: _on(i))
                out.append({"type": "done_then_failed", "level": lv, "node": n, "refs": [d["ref"], f["ref"]],
                            "what": f"{label} on {where}: stated done ({d['kind']}, {_who(d)}, {_day(_on(d))}), "
                                    f"then stated failed ({f['kind']}, {_who(f)}, {_day(_on(f))})."})
                break
        # 2. work recorded before a prerequisite inspection has any record
        first = min((_on(i) for i in mine if _on(i)), default=None)
        if first and not by_id[n]["gate"]:
            missing = []
            for g in by_id[n]["after"]:
                if not by_id.get(g, {}).get("gate"):
                    continue
                gfirst = min((_on(i) for i in facts if i.get("node") == g and lv in (i.get("levels") or ()) and _on(i)),
                             default=None)
                if gfirst is None or gfirst > first:
                    missing.append(by_id[g]["label"] + (" (no record)" if gfirst is None else f" (first record {_day(gfirst)})"))
            if missing:
                out.append({"type": "before_inspection_record", "level": lv, "node": n,
                            "refs": [i["ref"] for i in strongest_first(mine)[:3]],
                            "what": f"{label} on {where} first recorded {_day(first)}, before any record of: "
                                    + "; ".join(missing) + "."})
    # 3. a photo of work on a level whose logs name nobody there that day
    logged = {(lv, _on(i)) for i in facts if i["kind"] == "reported" and i["claim"] != "present"
              for lv in i.get("levels") or ()}
    seen = set()
    for i in facts:
        if i["kind"] != "observed" or not i.get("node") or not _on(i):
            continue
        for lv in i.get("levels") or ():
            if (lv, _on(i)) not in logged and (lv, _on(i), i["ref"]) not in seen:
                seen.add((lv, _on(i), i["ref"]))
                label = (by_id.get(i["node"]) or {}).get("label") or W.node_label(i["node"])
                out.append({"type": "photo_without_log", "level": lv, "node": i["node"], "refs": [i["ref"]],
                            "what": f"Photo {i['ref']} ({_day(_on(i))}) is described as showing {label} on "
                                    f"{W.level_label(lv)}; no filed log names anyone on {W.level_label(lv)} that day."})
    out.sort(key=lambda c: (level_order(c["level"]), c["type"], c["node"]))
    return out


# ── THE TIMELINE ───────────────────────────────────────────────────────────

def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def timeline(items: Sequence[Dict[str, Any]], model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per week (Monday): the cells whose evidence.status() changed that week,
    from what to what, and the items dated that week that moved it. Status
    only: a cell going quiet is not a change of evidence."""
    facts = [i for i in items if i["kind"] != "estimate" and i.get("node") and _on(i)]
    if not facts:
        return []
    by_cell: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for i in facts:
        for lv in i.get("levels") or ():
            if (lv, i["node"]) in model["cells"]:
                by_cell[(lv, i["node"])].append(i)
    weeks: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
    for key, mine in by_cell.items():
        prev = "unknown"
        for wk in sorted({_monday(_on(i)) for i in mine}):
            end = wk + timedelta(days=6)
            now = E.status([i for i in mine if _on(i) <= end])
            if now != prev:
                moved = [i for i in mine if wk <= _on(i) <= end]
                weeks[wk].append({"level": key[0], "node": key[1], "from": prev, "to": now,
                                  "refs": [i["ref"] for i in strongest_first(moved)[:4]],
                                  "kinds": sorted({i["kind"] for i in moved}, key=E.rank)})
                prev = now
    return [{"week": wk, "changes": sorted(ch, key=lambda c: (level_order(c["level"]), c["node"]))}
            for wk, ch in sorted(weeks.items())]


# ── AS WORDS ───────────────────────────────────────────────────────────────

def _day(d: Any) -> str:
    return f"{d:%b} {d.day}" if isinstance(d, date) else str(d or "")


def _who(i: Dict[str, Any]) -> str:
    src = SOURCE_WORDS.get(str(i.get("source")), i.get("source"))
    return " ".join(x for x in (f"by {i['by']}" if i.get("by") else "", f"via {src}") if x)


def _span(c: Dict[str, Any]) -> str:
    if not c["first"]:
        return ""
    return _day(c["first"]) if c["first"] == c["last"] else f"{_day(c['first'])} to {_day(c['last'])}"


def _pct(p: Any) -> str:
    try:
        return f"{float(p):g}%"
    except (TypeError, ValueError):
        return f"{p}%"


def cell_words(c: Dict[str, Any], label: str) -> str:
    st, b = c["status"], c["bucket"]
    if b == "unknown":
        bits = [f"{label}: {UNKNOWN_WORDS}"]
    elif b in ("done", "failed"):
        d = c["decided_by"] or {}
        bits = [f"{label}: {'done' if b == 'done' else 'failed'}, {st.split('_', 1)[1]} {_who(d)} on {_day(d.get('on'))}"]
    else:
        how = {"reported": "reported in the logs", "in_progress_observed": "photographed in progress"}.get(st, st.replace("_", " "))
        when = "the last 7 days" if b == "underway" else "earlier"
        bits = [f"{label}: {how} {_span(c)}" + (" (underway: recorded in " + when + ")" if b == "underway"
                                                 else " (not shown done)")]
    if c["subs"]:
        bits.append("sub(s) on record: " + ", ".join(c["subs"]))
    if c["shared_only"]:
        bits.append("filed for several floors together")
    for s in c["stated_percents"]:
        bits.append(f"{s['source']} states {_pct(s['percent'])}")
    for d in c["design_scope"]:
        bits.append(f"design scope {d['qty']:g} {d['unit']} {d['item']} ({d['source']}); installed quantity not stated by any source".replace("  ", " "))
    return "; ".join(bits)


def _counts_words(counts: Dict[str, int]) -> str:
    parts = [(counts.get("done", 0), "done (attested or stronger)"),
             (counts.get("underway", 0), f"underway (reported or photographed in the last {RECENT_DAYS} days)"),
             (counts.get("not_shown_done", 0), "with earlier records, none shown done"),
             (counts.get("failed", 0), "failed on record"),
             (counts.get("unknown", 0), "unknown (no record; unknown means nothing is on record, either way)")]
    return ", ".join(f"{n} {w}" for n, w in parts if n)


def _step_label(model: Dict[str, Any], node: str) -> str:
    for s in model["frame"]["steps"]:
        if s["id"] == node:
            return s["label"]
    return W.node_label(node)


def _bottleneck_words(model: Dict[str, Any], level: str) -> str:
    b = model["by_level"][level]["bottleneck"]
    bits = []
    if b["earliest_open"]:
        more = len(b["open_work"]) - 1
        first = next(s for s in model["frame"]["steps"] if s["id"] == b["earliest_open"])
        said = (f"{first['label']}, the first step of the standard sequence, has no done record" if not first["after"]
                else f"{first['label']} has no done record, and every step before it in the standard sequence has one")
        bits.append(f"open on the record: {said}" + (f" ({more} more step(s) at the same point)" if more else ""))
    failed = [g["label"] for g in b["gates"] if g["bucket"] == "failed"]
    unknown = [g for g in b["gates"] if g["bucket"] == "unknown"]
    if failed:
        bits.append("inspection failed on record: " + ", ".join(failed))
    if unknown:
        bits.append(f"{len(unknown)} inspection(s) with no record")
    return "; ".join(bits)


def _frame_words(model: Dict[str, Any]) -> List[str]:
    f = model["frame"]
    by_src: Dict[str, List[str]] = defaultdict(list)
    for src in LEVEL_SOURCES:
        for lv in f["levels"]:
            if src in lv["sources"] and (src != "evidence" or lv["sources"] == ["evidence"]):
                by_src[src].append(lv["label"])
    where = "; ".join(f"{LEVEL_SOURCES[s]}: {', '.join(v)}" for s, v in by_src.items())
    return [f"Frame: {len(f['levels'])} level(s) x {len(f['steps'])} step(s) = {f['cells']} level-and-work cells. "
            f"Levels from {where or 'nothing (no level is on record)'}. Steps: {f['source']}."]


def _overall_text(model: Dict[str, Any]) -> str:
    head = f"{model['job'] or 'This job'}, from the record as of {_day(model['today'])}. {NO_PERCENT}"
    out = [head] + _frame_words(model)
    out.append("Cells: " + (_counts_words(model["counts"]) or "none") + ".")
    lines = []
    for lv in model["frame"]["levels"][:MAX_TEXT_LEVELS]:
        s = model["by_level"][lv["level"]]
        c = s["counts"]
        if c.get("unknown", 0) == len(model["frame"]["steps"]):
            lines.append(f"- {lv['label']}: {UNKNOWN_WORDS}.")
            continue
        got = ", ".join(f"{c[k]} {w}" for k, w in (("done", "done"), ("underway", "underway"),
                                                  ("not_shown_done", "earlier, not shown done"),
                                                  ("failed", "failed"), ("unknown", "no record")) if c.get(k))
        bw = _bottleneck_words(model, lv["level"])
        lines.append(f"- {lv['label']}: {got}." + (f" {bw[0].upper()}{bw[1:]}." if bw else ""))
    out += ["By level:"] + lines
    if model["outside_frame"]:
        out.append("Also on record, outside the frame: " + "; ".join(
            f"{W.node_label(c['node'])} on {W.level_label(c['level'])} ({c['status'].replace('_', ' ')})"
            for c in model["outside_frame"][:6]) + ".")
    if model["conflicts"]:
        out.append(f"Records that disagree ({len(model['conflicts'])}), to confirm with the field:")
        out += [f"- {c['what']}" for c in model["conflicts"][:4]]
    if not model["has_schedule"]:
        out.append("No confirmed schedule is on file, so no planned date can be stated.")
    out.append(GUARD)
    return "\n".join(out)


def _sub_text(model: Dict[str, Any], name: str) -> str:
    s = model["subs"][name]
    out = []
    if s["work"]:
        by_node: Dict[str, List[str]] = defaultdict(list)
        for w in s["work"]:
            by_node[w["node"]].append(W.level_label(w["level"]))
        where = "; ".join(f"{_step_label(model, n)} on {', '.join(v)}" for n, v in by_node.items())
        out.append(f"{name}: records of {where}, from {_day(s['first'])} to {_day(s['last'])}.")
    else:
        out.append(f"{name}: no record of a step in the frame.")
    if s["presence_days"]:
        src = ", ".join(SOURCE_WORDS.get(x, x) for x in s["presence_sources"])
        out.append(f"Present on {s['presence_days']} day(s) ({src}), {_day(s['present_first'])} to {_day(s['present_last'])}.")
    else:
        out.append("No presence record (check-in) for them.")
    for w in s["work"][:10]:
        c = model["cells"].get((w["level"], w["node"]))
        if c:
            out.append("- " + cell_words(c, f"{_step_label(model, w['node'])}, {W.level_label(w['level'])}"))
    if s["next"]:
        out.append("Next for them by the standard sequence (a template's order, not a schedule or an assignment): "
                   + "; ".join(f"{W.level_label(n['level'])}: {_step_label(model, n['node'])}"
                               + (" (no record)" if n["bucket"] == "unknown" else f" ({n['bucket'].replace('_', ' ')})")
                               for n in s["next"][:MAX_TEXT_LEVELS]) + ".")
    out.append(GUARD)
    return "\n".join(out)


def _level_text(model: Dict[str, Any], level: str) -> str:
    label = W.level_label(level)
    out = [f"{label} on {model['job'] or 'this job'}, from the record as of {_day(model['today'])}. {NO_PERCENT}",
           f"Steps: {model['frame']['source']}."]
    unknown = []
    for s in model["frame"]["steps"]:
        c = model["cells"][(level, s["id"])]
        if c["bucket"] == "unknown":
            unknown.append(s["label"] + ("*" if s["conditional"] else ""))
        else:
            out.append("- " + cell_words(c, s["label"]))
        for e in c["estimates"]:
            out.append(f"  ({s['label']}: {e['label']}, basis: {e['basis']})")
    if unknown:
        out.append(f"{UNKNOWN_WORDS[0].upper()}{UNKNOWN_WORDS[1:]}: " + ", ".join(unknown) + ". (* if the building has this system)")
    bw = _bottleneck_words(model, level)
    if bw:
        out.append(bw[0].upper() + bw[1:] + ".")
    mine = [c for c in model["conflicts"] if c["level"] == level]
    if mine:
        out.append("Records that disagree, to confirm with the field:")
        out += [f"- {c['what']}" for c in mine[:4]]
    out.append(GUARD)
    return "\n".join(out)


def as_text(model: Dict[str, Any], scope: str = "overall", name: Any = None) -> str:
    """For the WhatsApp assistant: overall, by sub, or by floor. Every figure it
    may repeat is printed here."""
    scope = str(scope or "overall").lower()
    if scope == "sub":
        found = find_subs(model, name)
        if not found:
            known = ", ".join(sorted(model["subs"])) or "none"
            return f"No sub named \"{name}\" is on the record for {model['job'] or 'this job'}. Subs on record: {known}."
        if len(found) > 1:
            return "More than one sub matches: " + ", ".join(found) + ". Which one?"
        return _sub_text(model, found[0])
    if scope in ("floor", "level"):
        token = W.level_asked(name)
        if not token:
            return "Name one level: a floor number, roof, or cellar."
        if token not in {lv["level"] for lv in model["frame"]["levels"]}:
            return f"{W.level_label(token)} is not a level of {model['job'] or 'this job'} on the record."
        return _level_text(model, token)
    return _overall_text(model)


# ── FOR THE API ────────────────────────────────────────────────────────────

def to_json(v: Any) -> Any:
    """Dates as ISO strings, tuple keys as "LEVEL|node"."""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {("|".join(k) if isinstance(k, tuple) else str(k)): to_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_json(x) for x in v]
    return v
