"""sequence_rules_v1 — activity sequence rules as data (RANKING input only).

=====================================================================
RULE CONTENT PROVENANCE — the activity set and edge directions below
were approved by the operator via direct instruction. There is NO
signed sign-off document for this content. The shape (SequenceGraph /
WorkPackage / GraphEdge from schedule_models.py) is the stable part;
these contents are data and change when the operator changes them.
=====================================================================

WHAT THIS IS
------------
A ranking input for the daily-log activity chips. Consumed by
sequence_ranking.rank_activities. It ORDERS chips and nothing else:

  * it NEVER pre-selects a chip (ActivityChip.selected is Literal[False],
    so a pre-selected chip is unconstructible, not merely discouraged);
  * it NEVER blocks an entry — a CP can log any activity, including one
    with no rule edge at all, and "Other" is always available;
  * it NEVER writes to a record — this module and sequence_ranking are pure.

Every edge is `soft_parallel_open`. schedule_models.py:9 defines that type as
"advisory sibling ordering; does NOT gate a phase", and engine.py:254-258 only
counts HARD_EDGE_TYPES toward blocking in-degree. So even if this graph were
handed to the layering engine, no edge here could gate anything. That is the
mechanical guarantee behind "rules never block".

Self-edges and mutual pairs are deliberate and legitimate here: they encode
"continue this activity" (excavation) and "these run concurrently, both stay
offered" (interior framing <-> MEP rough-in). engine._expand_edges skips
from == to (engine.py:113-114) and _soft_rank_within tolerates soft cycles
without raising (engine.py:236), so neither is hazardous downstream.

STRUCTURAL SYSTEM BRANCHING
---------------------------
Cast-in-place-only nodes carry requires=[FLAG_CAST_IN_PLACE]; cold-formed-steel
only nodes carry requires=[FLAG_CFS]. sequence_ranking resolves those flags:
"cast_in_place" -> 3A only, "cfs" -> 3B only, "unknown" -> BOTH loops offered.

NOT WIRED TO generate_schedule. The engine's _requires_met (engine.py:72-74)
resolves `requires` against ProjectModel attributes, and ProjectModel has no
structural-system field today (project_model.py:95-113). Feeding this graph to
generate_schedule would therefore prune every branch node. Ranking resolves the
flags itself; do not pass this graph to generate_schedule until ProjectModel
carries the field.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from app.scheduling.schedule_models import (
    GraphEdge,
    SequenceGraph,
    WorkPackage,
)

RULES_VERSION = "sequence_rules_v1"

# ── Structural system ────────────────────────────────────────────────
SYSTEM_CAST_IN_PLACE = "cast_in_place"
SYSTEM_CFS = "cfs"
SYSTEM_UNKNOWN = "unknown"
STRUCTURAL_SYSTEMS: Tuple[str, ...] = (
    SYSTEM_CAST_IN_PLACE, SYSTEM_CFS, SYSTEM_UNKNOWN,
)

# `requires` flags marking a node as belonging to one superstructure loop.
FLAG_CAST_IN_PLACE = "structural_cast_in_place"
FLAG_CFS = "structural_cfs"

# Branch entry points — the first activity of each superstructure loop. Used by
# the ranker and by tests to assert that an unknown system offers BOTH loops.
BRANCH_ENTRY_CAST_IN_PLACE = "columns_shearwall_rebar"
BRANCH_ENTRY_CFS = "cfs_wall_panels"

# ── "Other" ──────────────────────────────────────────────────────────
# Deliberately NOT a member of ALWAYS_AVAILABLE_IDS. Always-available chips sit
# in a pinned band; "Other" must be the LAST chip overall, so the ranker appends
# it separately and no band ordering can bury it.
OTHER_ACTIVITY_ID = "other"
# Chip id prefix for a remembered free-text "Other" entry, e.g. "other:tank pull".
OTHER_ENTRY_PREFIX = "other:"

# ── Cold start ───────────────────────────────────────────────────────
# Project start with no history. (An EXISTING project instead has its current
# state set once by the CP at setup; the rules then run forward from it, so the
# ranker only falls back to these when it has no recognized prior activity.)
COLD_START_IDS: Tuple[str, ...] = (
    "excavation", "shoring", "underpinning", "piles", "site_prep",
)

# ── Always available — never sequence-gated ──────────────────────────
# Order is the approved order and is the order the ranker emits.
ALWAYS_AVAILABLE_ORDER: Tuple[str, ...] = (
    "site_cleanup", "material_delivery", "hoisting", "scaffold_erection",
    "scaffold_dismantle", "sidewalk_shed_work", "dewatering", "survey_layout",
    "inspection", "safety_meeting", "rain_no_work", "shutdown",
)
ALWAYS_AVAILABLE_IDS = frozenset(ALWAYS_AVAILABLE_ORDER)


def _wp(node_id, trade, scope, *, branch=None) -> WorkPackage:
    return WorkPackage(
        id=node_id, trade=trade, scope=scope,
        requires=[branch] if branch else [],
    )


# All rule edges are advisory. `_e` takes no edge_type so no caller can
# accidentally introduce a blocking edge into this graph.
SOFT = "soft_parallel_open"


def _e(a: str, b: str) -> GraphEdge:
    return GraphEdge(from_node=a, to_node=b, edge_type=SOFT)


def build_sequence_rules_v1() -> SequenceGraph:
    """The approved activity sequence, as a SequenceGraph of soft edges.

    Node declaration order below is the construction order the ranker uses as
    its stable secondary sort, so keep new nodes in sequence position.
    """
    nodes: List[WorkPackage] = [
        # ── cold start / sitework ────────────────────────────────────
        _wp("site_prep", "sitework", "site prep"),
        _wp("excavation", "excavation", "excavation"),
        _wp("shoring", "foundation", "shoring"),
        _wp("underpinning", "foundation", "underpinning"),
        _wp("piles", "foundation", "piles"),

        # ── foundation ───────────────────────────────────────────────
        _wp("pile_caps", "concrete", "pile caps"),
        _wp("pile_cutoff", "foundation", "pile cut-off"),
        _wp("footings", "concrete", "footings"),
        _wp("foundation_walls", "concrete", "foundation walls"),
        _wp("grade_beams", "concrete", "grade beams"),
        _wp("waterproofing", "waterproofing", "waterproofing"),
        _wp("drainage_board", "waterproofing", "drainage board / filter fabric"),
        _wp("protection_board", "waterproofing", "protection board"),
        _wp("backfill", "excavation", "backfill"),
        _wp("compaction", "excavation", "compaction"),
        _wp("underground_plumbing", "plumbing", "underground plumbing"),
        _wp("under_slab_mep", "mep", "under-slab MEP"),
        _wp("vapour_barrier", "concrete", "vapour barrier"),
        _wp("cellar_slab_rebar", "concrete", "cellar slab rebar"),
        _wp("pour_cellar_slab", "concrete", "pour cellar slab"),

        # ── 3A superstructure — cast-in-place concrete ───────────────
        # NOTE: columns_shearwall_rebar is also the "columns rebar" successor of
        # footings/pile caps in the foundation rules. It is one activity, and it
        # belongs to the cast-in-place loop, so it is branch-tagged here.
        _wp("columns_shearwall_rebar", "concrete", "columns / shear wall rebar",
            branch=FLAG_CAST_IN_PLACE),
        _wp("columns_shearwall_formwork", "concrete",
            "columns / shear wall formwork", branch=FLAG_CAST_IN_PLACE),
        _wp("pour_columns_shearwalls", "concrete", "pour columns / shear walls",
            branch=FLAG_CAST_IN_PLACE),
        _wp("strip_column_formwork", "concrete", "strip column formwork",
            branch=FLAG_CAST_IN_PLACE),
        _wp("slab_shoring_formwork", "concrete", "slab shoring and formwork",
            branch=FLAG_CAST_IN_PLACE),
        _wp("slab_rebar", "concrete", "slab rebar", branch=FLAG_CAST_IN_PLACE),
        _wp("edge_forms", "concrete", "edge forms", branch=FLAG_CAST_IN_PLACE),
        _wp("mep_sleeves_embeds", "mep", "MEP sleeves and embeds",
            branch=FLAG_CAST_IN_PLACE),
        _wp("post_tension_tendons", "concrete", "post-tension tendons",
            branch=FLAG_CAST_IN_PLACE),
        _wp("pour_slab", "concrete", "pour slab", branch=FLAG_CAST_IN_PLACE),
        _wp("curing_slab", "concrete", "curing", branch=FLAG_CAST_IN_PLACE),
        _wp("strip_formwork", "concrete", "strip formwork",
            branch=FLAG_CAST_IN_PLACE),
        _wp("reshore", "concrete", "reshore", branch=FLAG_CAST_IN_PLACE),
        _wp("patching", "concrete", "patching", branch=FLAG_CAST_IN_PLACE),

        # ── 3B superstructure — cold-formed steel ────────────────────
        _wp("cfs_wall_panels", "cfs", "load-bearing CFS wall panels / studs",
            branch=FLAG_CFS),
        _wp("bracing", "cfs", "bracing", branch=FLAG_CFS),
        _wp("floor_joists_decking", "cfs",
            "floor joists / corrugated metal decking", branch=FLAG_CFS),
        _wp("subfloor_sheathing", "cfs", "subfloor / structural sheathing",
            branch=FLAG_CFS),
        _wp("mep_floor_penetrations", "mep", "MEP floor penetrations / sleeves",
            branch=FLAG_CFS),
        _wp("pour_topping_slab", "concrete", "pour concrete topping slab",
            branch=FLAG_CFS),
        _wp("curing_topping_slab", "concrete", "curing (topping slab)",
            branch=FLAG_CFS),

        # ── 3C both branches ─────────────────────────────────────────
        _wp("crane_jump", "crane", "crane jump"),
        _wp("hoist_jump", "hoisting", "hoist jump"),

        # ── topping out + envelope ───────────────────────────────────
        _wp("top_floor_structure_complete", "gc", "top floor structure complete"),
        _wp("temporary_roof", "roofing", "temporary roof / weatherproofing"),
        _wp("parapets", "masonry", "parapets"),
        _wp("bulkhead", "gc", "bulkhead"),
        _wp("elevator_overrun", "gc", "elevator overrun"),
        _wp("finished_roofing", "roofing", "finished roofing"),
        _wp("flashing", "roofing", "flashing"),
        _wp("roof_mep", "mep", "roof MEP"),
        _wp("masonry", "masonry", "masonry"),
        _wp("facade", "facade", "facade"),
        _wp("window_install", "glazing", "window install"),
        _wp("facade_closeout", "facade", "facade close-out"),

        # ── interior fit-out ─────────────────────────────────────────
        _wp("building_envelope_closed", "gc", "building envelope closed"),
        _wp("interior_framing", "carpentry", "framing (layout, track and studs)"),
        _wp("insulation_prep", "insulation", "insulation prep"),
        _wp("mep_rough_in", "mep", "MEP rough-in"),
        _wp("blocking", "carpentry", "blocking"),
        _wp("firestopping", "firestopping", "firestopping"),
        _wp("insulation", "insulation", "insulation"),
        _wp("drywall", "drywall", "drywall"),
        _wp("taping", "drywall", "taping"),
        _wp("finishes", "finishes", "finishes"),
        _wp("flooring", "flooring", "flooring"),
        _wp("paint", "painting", "paint"),
        _wp("millwork", "carpentry", "millwork"),
        _wp("fixtures", "mep", "fixtures"),
        _wp("punch_list", "gc", "punch list"),
        _wp("final_inspection", "gc", "final inspection"),

        # ── always available — never sequence-gated ──────────────────
        _wp("site_cleanup", "gc", "site clean-up"),
        _wp("material_delivery", "gc", "material delivery"),
        _wp("hoisting", "hoisting", "hoisting"),
        _wp("scaffold_erection", "scaffold", "scaffold erection"),
        _wp("scaffold_dismantle", "scaffold", "scaffold dismantle"),
        _wp("sidewalk_shed_work", "scaffold", "sidewalk shed work"),
        _wp("dewatering", "excavation", "dewatering"),
        _wp("survey_layout", "survey", "survey / layout"),
        _wp("inspection", "gc", "inspection"),
        _wp("safety_meeting", "safety", "safety meeting"),
        _wp("rain_no_work", "gc", "rain - no work"),
        _wp("shutdown", "gc", "shutdown"),

        # ── the escape hatch — always LAST chip ──────────────────────
        _wp(OTHER_ACTIVITY_ID, "gc", "Other"),
    ]

    edges: List[GraphEdge] = [
        # ── foundation ───────────────────────────────────────────────
        _e("excavation", "shoring"),
        _e("excavation", "piles"),
        _e("excavation", "footings"),
        _e("excavation", "waterproofing"),
        _e("excavation", "excavation"),          # continue excavation
        _e("shoring", "excavation"),
        _e("shoring", "piles"),
        _e("shoring", "footings"),
        _e("underpinning", "excavation"),
        _e("underpinning", "piles"),
        _e("underpinning", "footings"),
        _e("piles", "pile_caps"),
        _e("piles", "footings"),
        _e("piles", "pile_cutoff"),
        _e("footings", "foundation_walls"),
        _e("footings", "grade_beams"),
        _e("footings", "columns_shearwall_rebar"),
        _e("pile_caps", "foundation_walls"),
        _e("pile_caps", "grade_beams"),
        _e("pile_caps", "columns_shearwall_rebar"),
        _e("foundation_walls", "waterproofing"),
        _e("foundation_walls", "grade_beams"),
        _e("waterproofing", "drainage_board"),
        _e("waterproofing", "protection_board"),
        _e("drainage_board", "backfill"),
        _e("drainage_board", "protection_board"),
        _e("backfill", "underground_plumbing"),
        _e("backfill", "under_slab_mep"),
        _e("backfill", "compaction"),
        _e("underground_plumbing", "under_slab_mep"),
        _e("underground_plumbing", "vapour_barrier"),
        _e("underground_plumbing", "inspection"),
        _e("under_slab_mep", "vapour_barrier"),
        _e("under_slab_mep", "cellar_slab_rebar"),
        _e("vapour_barrier", "cellar_slab_rebar"),
        _e("cellar_slab_rebar", "pour_cellar_slab"),
        # "cellar slab -> 1st floor superstructure": the 1st-floor superstructure
        # activity is the branch entry of whichever loop the project runs.
        _e("pour_cellar_slab", BRANCH_ENTRY_CAST_IN_PLACE),
        _e("pour_cellar_slab", BRANCH_ENTRY_CFS),

        # ── 3A cast-in-place concrete ────────────────────────────────
        _e("columns_shearwall_rebar", "columns_shearwall_formwork"),
        _e("columns_shearwall_formwork", "pour_columns_shearwalls"),
        _e("pour_columns_shearwalls", "strip_column_formwork"),
        _e("pour_columns_shearwalls", "slab_shoring_formwork"),
        _e("slab_shoring_formwork", "slab_rebar"),
        _e("slab_shoring_formwork", "edge_forms"),
        _e("slab_rebar", "mep_sleeves_embeds"),
        _e("slab_rebar", "post_tension_tendons"),
        _e("slab_rebar", "inspection"),
        _e("mep_sleeves_embeds", "pour_slab"),
        # pour slab (floor N) -> ... -> FLOOR N+1 columns/shear wall rebar
        _e("pour_slab", "curing_slab"),
        _e("pour_slab", "strip_formwork"),
        _e("pour_slab", "reshore"),
        _e("pour_slab", "columns_shearwall_rebar"),
        _e("curing_slab", "strip_formwork"),
        _e("curing_slab", "reshore"),
        _e("strip_formwork", "reshore"),
        _e("strip_formwork", "patching"),
        _e("strip_formwork", "columns_shearwall_rebar"),   # floor N+1 activities
        _e("reshore", "columns_shearwall_rebar"),          # floor N+1 activities
        _e("reshore", "masonry"),
        _e("reshore", "mep_rough_in"),                     # MEP rough-in on floor N

        # ── 3B cold-formed steel ─────────────────────────────────────
        _e("cfs_wall_panels", "floor_joists_decking"),
        _e("cfs_wall_panels", "bracing"),
        _e("floor_joists_decking", "subfloor_sheathing"),
        _e("subfloor_sheathing", "mep_floor_penetrations"),
        # ... -> pour concrete topping slab OR CFS wall panels floor N+1
        _e("mep_floor_penetrations", "pour_topping_slab"),
        _e("mep_floor_penetrations", "cfs_wall_panels"),
        _e("pour_topping_slab", "curing_topping_slab"),
        _e("pour_topping_slab", "cfs_wall_panels"),
        _e("curing_topping_slab", "cfs_wall_panels"),

        # ── 3C both branches ─────────────────────────────────────────
        # "any floor structure complete" = pour_slab (3A), and for 3B the floor
        # is complete at subfloor sheathing or after the topping slab pour.
        _e("pour_slab", "crane_jump"),
        _e("pour_slab", "hoist_jump"),
        _e("pour_slab", "hoisting"),                       # material hoisting
        _e("subfloor_sheathing", "crane_jump"),
        _e("subfloor_sheathing", "hoist_jump"),
        _e("subfloor_sheathing", "hoisting"),
        _e("pour_topping_slab", "crane_jump"),
        _e("pour_topping_slab", "hoist_jump"),
        _e("pour_topping_slab", "hoisting"),
        # crane/hoist jump -> resume floor N+1 superstructure activities
        _e("crane_jump", BRANCH_ENTRY_CAST_IN_PLACE),
        _e("crane_jump", BRANCH_ENTRY_CFS),
        _e("hoist_jump", BRANCH_ENTRY_CAST_IN_PLACE),
        _e("hoist_jump", BRANCH_ENTRY_CFS),

        # ── topping out + envelope ───────────────────────────────────
        # DERIVED (not verbatim in the approved rules): the approved rules name
        # "top floor structure complete" as a source but give it no predecessor.
        # These two edges only OFFER the top-out chip after a floor structure is
        # poured; the CP decides whether the building is actually topped out.
        _e("pour_slab", "top_floor_structure_complete"),
        _e("pour_topping_slab", "top_floor_structure_complete"),
        _e("top_floor_structure_complete", "temporary_roof"),
        _e("top_floor_structure_complete", "parapets"),
        _e("top_floor_structure_complete", "bulkhead"),
        _e("top_floor_structure_complete", "elevator_overrun"),
        _e("temporary_roof", "finished_roofing"),
        _e("temporary_roof", "parapets"),
        _e("temporary_roof", "roof_mep"),
        _e("finished_roofing", "parapets"),
        _e("finished_roofing", "flashing"),
        _e("finished_roofing", "roof_mep"),
        # "any floor stripped and reshored / CFS floor complete -> masonry,
        # facade, window install, framing"
        _e("reshore", "facade"),
        _e("reshore", "window_install"),
        _e("reshore", "interior_framing"),
        _e("subfloor_sheathing", "masonry"),
        _e("subfloor_sheathing", "facade"),
        _e("subfloor_sheathing", "window_install"),
        _e("subfloor_sheathing", "interior_framing"),
        _e("pour_topping_slab", "masonry"),
        _e("pour_topping_slab", "facade"),
        _e("pour_topping_slab", "window_install"),
        _e("pour_topping_slab", "interior_framing"),
        _e("masonry", "window_install"),
        _e("masonry", "waterproofing"),
        _e("masonry", "flashing"),
        _e("facade", "window_install"),
        _e("facade", "waterproofing"),
        _e("facade", "flashing"),
        _e("window_install", "facade_closeout"),
        _e("window_install", "interior_framing"),

        # ── interior fit-out ─────────────────────────────────────────
        # DERIVED (not verbatim in the approved rules): "building envelope
        # closed" is named as a source with no predecessor. Facade close-out is
        # what closes the envelope, so it offers the chip; nothing is asserted
        # about whether the envelope IS closed.
        _e("facade_closeout", "building_envelope_closed"),
        _e("building_envelope_closed", "interior_framing"),
        _e("building_envelope_closed", "insulation_prep"),
        # framing <-> MEP rough-in is CONCURRENT: the mutual pair keeps both
        # offered whichever one was logged.
        _e("interior_framing", "mep_rough_in"),
        _e("interior_framing", "blocking"),
        _e("interior_framing", "inspection"),
        _e("mep_rough_in", "firestopping"),
        _e("mep_rough_in", "inspection"),
        _e("mep_rough_in", "interior_framing"),            # continue framing
        _e("firestopping", "inspection"),
        _e("firestopping", "insulation"),
        _e("insulation", "drywall"),
        _e("insulation", "inspection"),
        _e("drywall", "taping"),
        _e("drywall", "finishes"),
        _e("drywall", "flooring"),
        _e("drywall", "paint"),
        _e("taping", "paint"),
        _e("taping", "flooring"),
        _e("taping", "millwork"),
        _e("finishes", "fixtures"),
        _e("finishes", "punch_list"),
        _e("finishes", "final_inspection"),
        _e("flooring", "fixtures"),
        _e("flooring", "punch_list"),
        _e("flooring", "final_inspection"),
        _e("paint", "fixtures"),
        _e("paint", "punch_list"),
        _e("paint", "final_inspection"),
    ]
    return SequenceGraph(version=RULES_VERSION, nodes=nodes, edges=edges)


# ── Derived lookups (built once from the graph above) ────────────────
def successors_by_id(graph: SequenceGraph) -> Dict[str, List[str]]:
    """from_node -> successor ids, in the graph's edge order, de-duplicated."""
    out: Dict[str, List[str]] = {}
    for e in graph.edges:
        bucket = out.setdefault(e.from_node, [])
        if e.to_node not in bucket:
            bucket.append(e.to_node)
    return out
