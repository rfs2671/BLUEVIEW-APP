"""Engine mechanics + graph_v1 integration (pure; db not used by generate)."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from app.scheduling.graph_v1 import build_graph_v1  # noqa: E402
from app.scheduling.engine import generate_schedule, ScheduleCycleError  # noqa: E402
from app.scheduling.project_model import (  # noqa: E402
    ProjectModel, Zone, SpecialInspection, FieldProvenance,
)
from app.scheduling.schedule_models import (  # noqa: E402
    WorkPackage, InspectionGate, GraphEdge, SequenceGraph,
)

FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _prov(status="confirmed"):
    return FieldProvenance(source="operator_declared", confidence="high", status=status)


def _zone(zid, floors, tco=False, status="confirmed"):
    return Zone(id=zid, floors=floors, is_tco_phase=tco, provenance=_prov(status))


def _pm(*, floors=1, zones=None, gas=True, sprinkler=True, standpipe=True,
        elevator=False, special=None, fp=None):
    if zones is None:
        zones = [_zone("A", list(range(1, floors + 1)))]
    return ProjectModel(
        project_id="p1", floors=floors, has_gas=gas, has_sprinkler=sprinkler,
        has_standpipe=standpipe, has_elevator=elevator, zones=zones,
        special_inspections=special or [], field_provenance=fp or {},
        aggregated_at=FIXED_NOW,
    )


def _gen(project, graph):
    return generate_schedule(None, project=project, graph=graph, now=FIXED_NOW)


def _depth(schedule):
    d = {}
    for ph in schedule.phases:
        for n in ph.parallel_work + ph.required_gates:
            d[n] = ph.phase_index
    return d


def _wp(i, **kw):
    return WorkPackage(id=i, trade="t", scope="s", **kw)


# ── 1. shatter / heal ────────────────────────────────────────────────
def test_shatter_heal_downstream_keeps_hard_upstream():
    g = SequenceGraph(version="t", nodes=[_wp("A"), _wp("G", requires=["has_gas"]), _wp("B")],
                      edges=[GraphEdge(from_node="A", to_node="G", edge_type="hard_fts"),
                             GraphEdge(from_node="G", to_node="B", edge_type="hard_fts")])
    s = _gen(_pm(gas=False), g)
    d = _depth(s)
    assert "G" in s.pruned_nodes
    assert d["A"] == 0
    assert d["B"] == 1                       # did NOT float to phase 0
    healed = {(e.from_node, e.to_node): e.edge_type for e in s.healed_edges}
    assert healed.get(("A", "B")) == "hard_fts"


# ── 2. healed edge type ──────────────────────────────────────────────
def test_healed_type_hard_then_soft_is_hard_soft_then_soft_is_soft():
    g = SequenceGraph(version="t", nodes=[
        _wp("A"), _wp("X", requires=["has_gas"]), _wp("B"),
        _wp("Y", requires=["has_gas"]), _wp("C"),
    ], edges=[
        GraphEdge(from_node="A", to_node="X", edge_type="hard_fts"),
        GraphEdge(from_node="X", to_node="B", edge_type="soft_parallel_open"),
        GraphEdge(from_node="A", to_node="Y", edge_type="soft_parallel_open"),
        GraphEdge(from_node="Y", to_node="C", edge_type="soft_parallel_open"),
    ])
    s = _gen(_pm(gas=False), g)
    healed = {(e.from_node, e.to_node): e.edge_type for e in s.healed_edges}
    assert healed.get(("A", "B")) == "hard_fts"          # hard-then-soft → hard
    assert healed.get(("A", "C")) == "soft_parallel_open"  # soft-then-soft → soft


# ── 3. soft parallelism ──────────────────────────────────────────────
def test_soft_edges_do_not_gate_phase():
    g = SequenceGraph(version="t", nodes=[_wp("framing"), _wp("dwv"), _wp("duct")],
                      edges=[GraphEdge(from_node="framing", to_node="dwv", edge_type="soft_parallel_open"),
                             GraphEdge(from_node="framing", to_node="duct", edge_type="soft_parallel_open")])
    s = _gen(_pm(), g)
    d = _depth(s)
    assert d["dwv"] == d["duct"] == 0
    p0 = next(ph for ph in s.phases if ph.phase_index == 0)
    assert "dwv" in p0.parallel_work and "duct" in p0.parallel_work


# ── 4. vertical structural ──────────────────────────────────────────
def test_vertical_structural_ladders_floors():
    g = SequenceGraph(version="t", nodes=[_wp("fr", per_floor=True, is_structural=True)], edges=[])
    d = _depth(_gen(_pm(floors=3), g))
    assert d["fr__f1"] == 0 and d["fr__f2"] == 1 and d["fr__f3"] == 2
    assert d["fr__f2"] > d["fr__f1"]


# ── 5. floor-stacking allowed ────────────────────────────────────────
def test_floor_stacking_rough_opens_before_lower_floor_finishes():
    s = _gen(_pm(floors=2, zones=[_zone("A", [1, 2])]), build_graph_v1())
    d = _depth(s)
    assert d["rough_dwv__f2"] == 0                    # no hard predecessor blocks it
    assert d["finishes__zA"] > d["rough_dwv__f2"]     # F2 rough open while zone in finishes


# ── 6. cycle detection after heal ────────────────────────────────────
def test_cycle_detected_after_heal():
    g = SequenceGraph(version="t", nodes=[_wp("A"), _wp("X", requires=["has_gas"]), _wp("B")],
                      edges=[GraphEdge(from_node="A", to_node="X", edge_type="hard_fts"),
                             GraphEdge(from_node="X", to_node="B", edge_type="hard_fts"),
                             GraphEdge(from_node="B", to_node="A", edge_type="hard_fts")])
    with pytest.raises(ScheduleCycleError) as ei:
        _gen(_pm(gas=False), g)
    assert {"A", "B"} <= set(ei.value.node_ids)


# ── 7. determinism ───────────────────────────────────────────────────
def test_determinism_identical_output():
    pm = _pm(floors=3, zones=[_zone("A", [1, 2, 3])])
    a = _gen(pm, build_graph_v1())
    b = _gen(pm, build_graph_v1())
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


# ── 8. per-zone gate isolation ───────────────────────────────────────
def test_per_zone_gate_isolation():
    za, zb = _zone("A", [1, 2]), _zone("B", [3, 4])
    d2 = _depth(_gen(_pm(floors=4, zones=[za, zb]), build_graph_v1()))
    d1 = _depth(_gen(_pm(floors=4, zones=[za]), build_graph_v1()))
    # Zone B's presence does not shift Zone A's drywall or TCO phase.
    assert d2["drywall__zA"] == d1["drywall__zA"]
    assert d2["tco_zone__zA"] == d1["tco_zone__zA"]


# ── 9. phased TCO ────────────────────────────────────────────────────
def test_phased_tco_zones_parallel():
    d = _depth(_gen(_pm(floors=4, zones=[_zone("A", [1, 2], tco=True), _zone("B", [3, 4], tco=True)]),
                    build_graph_v1()))
    assert d["tco_zone__zA"] == d["tco_zone__zB"]        # parallel, neither gates the other
    assert d["finishes__zB"] < d["tco_zone__zA"]         # A reaches TCO while B still finishing


# ── 10. pruning ──────────────────────────────────────────────────────
def test_pruning_removes_gas_and_sprinkler_branches():
    s = _gen(_pm(floors=2, gas=False, sprinkler=False, zones=[_zone("A", [1, 2])]), build_graph_v1())
    pruned = set(s.pruned_nodes)
    assert {"rough_gas__f1", "gas_pressure_test__f1", "gate_gas_final", "blue_card"} <= pruned
    assert "gate_sprinkler_hydro__zA" in pruned and "rough_sprinkler__f1" in pruned
    d = _depth(s)
    assert "blue_card" not in d and "gate_sprinkler_hydro__zA" not in d


# ── 11. pre-board gate ───────────────────────────────────────────────
def test_drywall_never_precedes_active_preboard_gates():
    d = _depth(_gen(_pm(floors=2, zones=[_zone("A", [1, 2])]), build_graph_v1()))
    preboard = ["gate_plumbing_rough__zA", "gate_electrical_rough__zA",
                "gate_firestopping__zA", "gate_nycecc_insulation__zA",
                "gate_sprinkler_hydro__zA"]
    for g in preboard:
        assert d[g] < d["drywall__zA"]
