"""Deterministic scheduling engine.

Consumes a ProjectModel + a SequenceGraph and produces a Schedule via
edge-type-aware topological layering. No LLM, no Socrata, no WhatsApp. `db` is
passed in per repo convention (used only for persistence helpers; the pure
engine `generate_schedule` reads nothing from it).

Pipeline (exact):
  1. Instantiate per_floor nodes 1..floors and zone_scoped nodes per zone.
  2. Expand template edges across granularities + auto-generate bottom-up
     vertical_structural edges between consecutive floors for structural nodes.
  3. Prune nodes whose `requires` is unmet, with transitive-closure edge healing.
  4. Detect cycles (AFTER healing + vertical insertion).
  5. Layer using HARD edges only for blocking in-degree; soft edges are an
     advisory within-phase ordering hint.
Determinism: canonical sort by id at every tie/order point.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.scheduling.project_model import ProjectModel
from app.scheduling.schedule_models import (
    GraphEdge,
    Phase,
    Schedule,
    SequenceGraph,
)

HARD_EDGE_TYPES = frozenset({"hard_fts", "vertical_structural"})


class ScheduleCycleError(Exception):
    """Raised when the healed + vertical-augmented graph has a hard cycle."""

    def __init__(self, node_ids: List[str]):
        self.node_ids = sorted(node_ids)
        super().__init__(f"Cycle among nodes: {self.node_ids}")


# ─────────────────────────────────────────────────────────────────────
# FLOOR IDENTITY — location #1 of 2.
# The ONLY place the 1..floors integer range is produced. To move to a named
# floor list (cellar/mezzanine/roof/PH), change this function and the vertical
# edge builder (_vertical_structural_edges, marked location #2) — nowhere else.
def _floor_range(project: ProjectModel) -> List[int]:
    return list(range(1, project.floors + 1))
# ─────────────────────────────────────────────────────────────────────


def _instance_id(template_id: str, *, floor: Optional[int] = None,
                 zone: Optional[str] = None) -> str:
    if floor is not None:
        return f"{template_id}__f{floor}"
    if zone is not None:
        return f"{template_id}__z{zone}"
    return template_id  # global (is_global gate / non-scoped)


def _granularity(node) -> str:
    if getattr(node, "per_floor", False):
        return "floor"
    if getattr(node, "zone_scoped", False):
        return "zone"
    return "global"


def _requires_met(requires: List[str], project: ProjectModel) -> bool:
    return all(bool(getattr(project, flag, False)) for flag in requires)


def _instantiate(graph: SequenceGraph, project: ProjectModel):
    """Expand templates into instances. Returns (node_kind, id_map, tmpl_of,
    requires_of)."""
    floors = _floor_range(project)
    node_kind: Dict[str, str] = {}
    id_map: Dict[str, List[str]] = {}
    tmpl_of: Dict[str, str] = {}
    requires_of: Dict[str, List[str]] = {}
    for node in graph.nodes:
        g = _granularity(node)
        if g == "floor":
            ids = [_instance_id(node.id, floor=f) for f in floors]
        elif g == "zone":
            ids = [_instance_id(node.id, zone=z.id) for z in project.zones]
        else:
            ids = [node.id]
        id_map[node.id] = ids
        requires_of[node.id] = list(node.requires)
        for iid in ids:
            node_kind[iid] = node.kind
            tmpl_of[iid] = node.id
    return node_kind, id_map, tmpl_of, requires_of


def _floors_in_zone(zone, floorset) -> List[int]:
    return sorted(f for f in zone.floors if f in floorset)


def _expand_edges(graph: SequenceGraph, project: ProjectModel,
                  id_map: Dict[str, List[str]]) -> Dict[Tuple[str, str], str]:
    """Resolve template edges into instance edges across granularities."""
    nodes_by_id = {n.id: n for n in graph.nodes}
    floors = _floor_range(project)
    floorset = set(floors)
    edges: Dict[Tuple[str, str], str] = {}

    def _add(f, t, ty):
        if f == t:
            return
        # Keep the stronger edge on collision (hard beats soft).
        prev = edges.get((f, t))
        if prev in HARD_EDGE_TYPES or ty in HARD_EDGE_TYPES:
            edges[(f, t)] = "hard_fts" if ty != "vertical_structural" else ty
            if prev in HARD_EDGE_TYPES and ty not in HARD_EDGE_TYPES:
                edges[(f, t)] = prev
        else:
            edges[(f, t)] = ty

    for e in graph.edges:
        A = nodes_by_id[e.from_node]
        B = nodes_by_id[e.to_node]
        ga, gb = _granularity(A), _granularity(B)
        ty = e.edge_type
        if ga == "floor" and gb == "floor":
            for f in floors:
                _add(_instance_id(A.id, floor=f), _instance_id(B.id, floor=f), ty)
        elif ga == "floor" and gb == "zone":
            for z in project.zones:
                for f in _floors_in_zone(z, floorset):
                    _add(_instance_id(A.id, floor=f), _instance_id(B.id, zone=z.id), ty)
        elif ga == "zone" and gb == "floor":
            for z in project.zones:
                for f in _floors_in_zone(z, floorset):
                    _add(_instance_id(A.id, zone=z.id), _instance_id(B.id, floor=f), ty)
        elif ga == "zone" and gb == "zone":
            for z in project.zones:
                _add(_instance_id(A.id, zone=z.id), _instance_id(B.id, zone=z.id), ty)
        elif ga == "global":
            for bid in id_map[B.id]:
                _add(A.id, bid, ty)
        elif gb == "global":
            for aid in id_map[A.id]:
                _add(aid, B.id, ty)
    return edges


# ─────────────────────────────────────────────────────────────────────
# FLOOR IDENTITY — location #2 of 2 (see _floor_range).
def _vertical_structural_edges(graph: SequenceGraph, project: ProjectModel,
                               edges: Dict[Tuple[str, str], str]) -> None:
    """Auto-generate bottom-up hard edges between consecutive floors for
    structural per_floor nodes (floor N depends on floor N-1). This is the ONLY
    place besides _floor_range where floor identity/order is used. NO crew or
    resource edges are generated — floor-stacking of interior trades is
    legitimate parallelism and out of scope for this spine."""
    floors = _floor_range(project)
    for node in graph.nodes:
        if getattr(node, "kind", None) == "work" and node.is_structural and node.per_floor:
            for lower, upper in zip(floors, floors[1:]):
                edges[(_instance_id(node.id, floor=lower),
                       _instance_id(node.id, floor=upper))] = "vertical_structural"
# ─────────────────────────────────────────────────────────────────────


def _prune_with_healing(node_ids: set, edges: Dict[Tuple[str, str], str],
                        to_prune: List[str]):
    """Eliminate each pruned node, forging p->s for every predecessor p and
    successor s (if absent). Healed edge is hard_fts if ANY edge on the
    collapsed p->node->s path is hard_fts or vertical_structural, else soft.
    Prune in sorted id order. Returns (survivors, edges, healed_edges)."""
    healed: Dict[Tuple[str, str], str] = {}
    for node in sorted(to_prune):
        preds = sorted(f for (f, t) in edges if t == node)
        succs = sorted(t for (f, t) in edges if f == node)
        for p in preds:
            for s in succs:
                if p == s or (p, s) in edges:
                    continue
                t1 = edges[(p, node)]
                t2 = edges[(node, s)]
                et = "hard_fts" if (t1 in HARD_EDGE_TYPES or t2 in HARD_EDGE_TYPES) \
                    else "soft_parallel_open"
                edges[(p, s)] = et
                healed[(p, s)] = et
        # Drop the node + all incident edges.
        for key in [k for k in edges if k[0] == node or k[1] == node]:
            del edges[key]
        node_ids.discard(node)
    # Only healed edges that survive between two live nodes are reported.
    healed_final = {
        k: v for k, v in healed.items()
        if k in edges and k[0] in node_ids and k[1] in node_ids
    }
    return node_ids, edges, healed_final


def _detect_cycle(node_ids: set, edges: Dict[Tuple[str, str], str]) -> None:
    """Kahn over HARD edges only. Residual nodes => a hard cycle."""
    succ = defaultdict(list)
    indeg = {n: 0 for n in node_ids}
    for (f, t), ty in edges.items():
        if ty in HARD_EDGE_TYPES and f in node_ids and t in node_ids:
            succ[f].append(t)
            indeg[t] += 1
    ready = sorted(n for n in node_ids if indeg[n] == 0)
    seen = 0
    indeg2 = dict(indeg)
    while ready:
        n = ready.pop(0)
        seen += 1
        for m in sorted(succ[n]):
            indeg2[m] -= 1
            if indeg2[m] == 0:
                bisect.insort(ready, m)
    if seen != len(node_ids):
        offenders = [n for n in node_ids if indeg2[n] > 0]
        raise ScheduleCycleError(offenders)


def _soft_rank_within(members: List[str],
                      soft_edges: List[Tuple[str, str]]) -> Dict[str, int]:
    mset = set(members)
    succ = defaultdict(list)
    indeg = {m: 0 for m in members}
    for (f, t) in soft_edges:
        if f in mset and t in mset:
            succ[f].append(t)
            indeg[t] += 1
    rank = {m: 0 for m in members}
    ready = sorted(m for m in members if indeg[m] == 0)
    while ready:  # soft cycles (rare) simply leave some ranks at 0 — never raise
        n = ready.pop(0)
        for m in sorted(succ[n]):
            rank[m] = max(rank[m], rank[n] + 1)
            indeg[m] -= 1
            if indeg[m] == 0:
                bisect.insort(ready, m)
    return rank


def _layer(node_ids: set, edges: Dict[Tuple[str, str], str],
           node_kind: Dict[str, str]) -> List[Phase]:
    """phase_index = longest HARD-path depth. Soft edges never gate a boundary;
    they only order nodes within a phase (advisory)."""
    hard_succ = defaultdict(list)
    indeg = {n: 0 for n in node_ids}
    soft_edges = []
    for (f, t), ty in edges.items():
        if ty in HARD_EDGE_TYPES:
            hard_succ[f].append(t)
            indeg[t] += 1
        else:
            soft_edges.append((f, t))

    depth = {n: 0 for n in node_ids}
    indeg2 = dict(indeg)
    ready = sorted(n for n in node_ids if indeg2[n] == 0)
    while ready:
        n = ready.pop(0)
        for m in sorted(hard_succ[n]):
            if depth[n] + 1 > depth[m]:
                depth[m] = depth[n] + 1
            indeg2[m] -= 1
            if indeg2[m] == 0:
                bisect.insort(ready, m)

    by_depth = defaultdict(list)
    for n in node_ids:
        by_depth[depth[n]].append(n)

    hard_pairs = [(f, t) for (f, t), ty in edges.items() if ty in HARD_EDGE_TYPES]
    phases: List[Phase] = []
    for d in sorted(by_depth):
        members = by_depth[d]
        rank = _soft_rank_within(members, soft_edges)
        ordered = sorted(members, key=lambda n: (rank[n], n))
        work = [n for n in ordered if node_kind.get(n) == "work"]
        gates = [n for n in ordered if node_kind.get(n) == "gate"]
        mset = set(members)
        opens = sorted({t for (f, t) in hard_pairs if f in mset and depth[t] == d + 1})
        phases.append(Phase(phase_index=d, parallel_work=work,
                            required_gates=gates, opens_next=opens))
    return phases


def generate_schedule(db, *, project: ProjectModel, graph: SequenceGraph,
                      now: Optional[datetime] = None) -> Schedule:
    ts = now or datetime.now(timezone.utc)
    node_kind, id_map, tmpl_of, requires_of = _instantiate(graph, project)
    edges = _expand_edges(graph, project, id_map)
    _vertical_structural_edges(graph, project, edges)

    all_ids = set(node_kind)
    to_prune = [iid for iid, tid in tmpl_of.items()
                if not _requires_met(requires_of[tid], project)]
    survivors, edges, healed = _prune_with_healing(all_ids, edges, to_prune)

    _detect_cycle(survivors, edges)
    phases = _layer(survivors, edges, node_kind)

    healed_edges = [
        GraphEdge(from_node=f, to_node=t, edge_type=ty)
        for (f, t), ty in sorted(healed.items())
    ]
    return Schedule(
        project_id=project.project_id,
        graph_version=graph.version,
        phases=phases,
        pruned_nodes=sorted(to_prune),
        healed_edges=healed_edges,
        generated_at=ts,
    )


# ── Warnings (unconfirmed gate-critical input) ───────────────────────
def schedule_input_warnings(project: ProjectModel) -> List[dict]:
    """Gate-critical fields still status='proposed' — surfaced so the caller
    knows the schedule rests on unconfirmed input. Never blocks generation."""
    out: List[dict] = []
    for f in ("floors", "has_gas", "has_sprinkler", "has_standpipe", "has_elevator"):
        prov = project.field_provenance.get(f)
        if prov is not None and prov.status == "proposed":
            out.append({"kind": "scalar", "field": f, "value": getattr(project, f)})
    for si in project.special_inspections:
        if si.provenance.status == "proposed":
            out.append({"kind": "special_inspection", "id": si.id,
                        "inspection_type": si.inspection_type})
    for z in project.zones:
        if z.provenance.status == "proposed":
            out.append({"kind": "zone", "id": z.id})
    return sorted(out, key=lambda w: (w["kind"], w.get("field") or w.get("id") or ""))


# ── Persistence (db passed in; upsert-only, never drop) ──────────────
async def upsert_seed_graph(db, graph: SequenceGraph) -> None:
    await db.sequence_graph.update_one(
        {"version": graph.version},
        {"$set": graph.model_dump(mode="python")},
        upsert=True,
    )


async def persist_schedule(db, schedule: Schedule) -> None:
    doc = schedule.model_dump(mode="python")
    await db.project_schedules.insert_one(doc)


async def load_latest_schedule(db, project_id: str) -> Optional[dict]:
    cur = db.project_schedules.find({"project_id": project_id})
    rows = await cur.sort("generated_at", -1).to_list(1)
    if not rows:
        return None
    row = dict(rows[0])
    row.pop("_id", None)
    return row
