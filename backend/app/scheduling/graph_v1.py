"""graph_v1 — NYC residential interior construction sequence (seed template).

=====================================================================
RULE CONTENTS PENDING NYC DOB DOMAIN-EXPERT SIGN-OFF — architecture
stable, sequence VALUES PROVISIONAL. The node set, edge directions, and
gate placements below encode a standard NYC residential interior fit-out
sequence, but they have NOT been reviewed by a DOB/expediting expert.
Treat every node and edge as provisional until sign-off. The engine
(instantiation, pruning/healing, edge-type-aware layering) is the stable
part; these contents are data and are expected to change.
=====================================================================

Templates are UNINSTANTIATED: per_floor nodes are expanded once per floor
(1..floors) and zone_scoped nodes/gates once per ProjectModel zone by the
engine. Edges are template->template; the engine resolves them across
granularities. Gates are NOT global unless is_global.

Rough-ins are SOFT siblings off framing (parallel, not a linear chain). The
real hard gate before drywall is the pre-board cluster. gas/sprinkler/standpipe
branches carry `requires` flags and are pruned (with edge healing) when the
ProjectModel doesn't have that system.
"""

from __future__ import annotations

from app.scheduling.schedule_models import (
    GraphEdge,
    InspectionGate,
    SequenceGraph,
    WorkPackage,
)

GRAPH_VERSION = "graph_v1"


def _wp(node_id, trade, scope, *, per_floor=False, is_structural=False,
        zone_scoped=False, requires=None):
    return WorkPackage(
        id=node_id, trade=trade, scope=scope, per_floor=per_floor,
        is_structural=is_structural, zone_scoped=zone_scoped,
        requires=list(requires or []),
    )


def _gate(node_id, inspection_type, *, is_special_inspection=False,
          zone_scoped=False, is_global=False, requires=None):
    return InspectionGate(
        id=node_id, inspection_type=inspection_type,
        is_special_inspection=is_special_inspection, zone_scoped=zone_scoped,
        is_global=is_global, requires=list(requires or []),
    )


def _e(a, b, t):
    return GraphEdge(from_node=a, to_node=b, edge_type=t)


def build_graph_v1() -> SequenceGraph:
    nodes = [
        # ── per-floor framing (structural) ──
        _wp("framing", "carpentry", "partition + ceiling framing",
            per_floor=True, is_structural=True),

        # ── per-floor rough-ins — SOFT siblings off framing ──
        _wp("rough_dwv", "plumbing", "DWV rough", per_floor=True),
        _wp("rough_duct", "mechanical", "HVAC duct rough", per_floor=True),
        _wp("rough_sprinkler", "fire_protection", "sprinkler rough",
            per_floor=True, requires=["has_sprinkler"]),
        _wp("rough_water", "plumbing", "domestic water rough", per_floor=True),
        _wp("rough_gas", "plumbing_gas", "gas rough",
            per_floor=True, requires=["has_gas"]),
        _wp("rough_electric", "electrical", "electric rough", per_floor=True),
        _wp("rough_lowvolt", "electrical_lv", "fire-alarm / low-volt rough",
            per_floor=True),

        # ── pre-board HARD gate cluster (zone-scoped) ──
        _gate("gate_plumbing_rough", "plumbing_rough", zone_scoped=True),
        _gate("gate_sprinkler_hydro", "sprinkler", zone_scoped=True,
              requires=["has_sprinkler"]),
        _gate("gate_electrical_rough", "electrical_rough", zone_scoped=True),
        _gate("gate_firestopping", "firestopping",
              is_special_inspection=True, zone_scoped=True),
        _gate("gate_nycecc_insulation", "energy_nycecc",
              is_special_inspection=True, zone_scoped=True),

        # ── zone-scoped board→finish chain ──
        _wp("drywall", "drywall", "close walls", zone_scoped=True),
        _wp("ceiling_drop", "drywall", "ceiling drop", zone_scoped=True),
        _wp("prime", "painting", "prime", zone_scoped=True),
        _wp("finishes", "finishes", "finishes", zone_scoped=True),
        _wp("mep_trim", "mep", "MEP trim", zone_scoped=True),
        _wp("zone_final", "gc", "per-zone trade finals", zone_scoped=True),

        # ── gas branch terminal (pruned when has_gas is false) ──
        _wp("gas_pressure_test", "plumbing_gas", "gas pressure test",
            per_floor=True, requires=["has_gas"]),
        _gate("gate_gas_final", "fuel_gas_piping", is_global=True,
              requires=["has_gas"]),
        _gate("blue_card", "utility_gas_authorization", is_global=True,
              requires=["has_gas"]),

        # ── per-zone TCO + its life-safety gate cluster ──
        _gate("gate_ls_sprinkler", "sprinkler", zone_scoped=True,
              requires=["has_sprinkler"]),
        _gate("gate_ls_standpipe", "standpipe", zone_scoped=True,
              requires=["has_standpipe"]),
        _gate("gate_ls_fire_alarm", "fire_alarm", zone_scoped=True),
        _gate("gate_ls_egress", "egress", zone_scoped=True),
        _gate("gate_ls_fdny", "fdny", zone_scoped=True),
        _gate("gate_ls_energy_final", "energy_final", zone_scoped=True),
        _wp("tco_zone", "gc", "per-zone TCO", zone_scoped=True),
    ]

    S = "soft_parallel_open"
    H = "hard_fts"
    edges = [
        # framing opens the rough-in window (soft siblings).
        _e("framing", "rough_dwv", S),
        _e("framing", "rough_duct", S),
        _e("framing", "rough_sprinkler", S),
        _e("framing", "rough_water", S),
        _e("framing", "rough_gas", S),
        _e("framing", "rough_electric", S),
        _e("framing", "rough_lowvolt", S),

        # rough-ins -> pre-board gates (hard).
        _e("rough_dwv", "gate_plumbing_rough", H),
        _e("rough_water", "gate_plumbing_rough", H),
        _e("rough_sprinkler", "gate_sprinkler_hydro", H),
        _e("rough_electric", "gate_electrical_rough", H),
        _e("rough_dwv", "gate_firestopping", H),
        _e("rough_duct", "gate_firestopping", H),
        _e("rough_electric", "gate_firestopping", H),
        _e("rough_duct", "gate_nycecc_insulation", H),
        _e("rough_electric", "gate_nycecc_insulation", H),

        # ALL pre-board gates -> drywall (hard).
        _e("gate_plumbing_rough", "drywall", H),
        _e("gate_sprinkler_hydro", "drywall", H),
        _e("gate_electrical_rough", "drywall", H),
        _e("gate_firestopping", "drywall", H),
        _e("gate_nycecc_insulation", "drywall", H),

        # board -> finish chain (hard).
        _e("drywall", "ceiling_drop", H),
        _e("ceiling_drop", "prime", H),
        _e("prime", "finishes", H),
        _e("finishes", "mep_trim", H),
        _e("mep_trim", "zone_final", H),

        # gas branch terminal (hard).
        _e("rough_gas", "gas_pressure_test", H),
        _e("gas_pressure_test", "gate_gas_final", H),
        _e("gate_gas_final", "blue_card", H),

        # life-safety cluster -> per-zone TCO (hard).
        _e("mep_trim", "gate_ls_sprinkler", H),
        _e("mep_trim", "gate_ls_standpipe", H),
        _e("mep_trim", "gate_ls_fire_alarm", H),
        _e("mep_trim", "gate_ls_egress", H),
        _e("mep_trim", "gate_ls_fdny", H),
        _e("mep_trim", "gate_ls_energy_final", H),
        _e("rough_lowvolt", "gate_ls_fire_alarm", H),
        _e("zone_final", "tco_zone", H),
        _e("gate_ls_sprinkler", "tco_zone", H),
        _e("gate_ls_standpipe", "tco_zone", H),
        _e("gate_ls_fire_alarm", "tco_zone", H),
        _e("gate_ls_egress", "tco_zone", H),
        _e("gate_ls_fdny", "tco_zone", H),
        _e("gate_ls_energy_final", "tco_zone", H),
    ]
    return SequenceGraph(version=GRAPH_VERSION, nodes=nodes, edges=edges)
