"""The order each trade's work is normally done in, as STAGES. Rank input only.

WHY. The rule graph (sequence_rules_v1) carries edges for a few dozen activities
and none for most trades' own work, so a crew returning to site could not be told
what comes after what it did last: after underground plumbing, MEP rough-in; after
rough-in, the risers and domestic water; then testing; then fixtures. The first
backtest on a real job (588 Thomas S Boyland) found 52% of a crew's NEW activities
outside the first four chips, and the misses were exactly these steps.

A STAGE is a set of activities done in the same phase (concurrent work stays
together: sanitary, vent and rough-in are one stage). A crew's position is the
furthest stage it has logged recently; the likely next work is the rest of that
stage and the stage after it.

THE SAME GUARANTEES AS EVERY OTHER RANKING HERE: this only orders chips. It never
selects, hides or blocks one, "Other" stays last, and it says nothing about how
much work is complete.

CONTENT. Written from how these trades sequence on a NYC job and checked against the
real 588 sequence (plumbers: MEP rough-in, then domestic water rough, with fixtures
and the water heater alongside; framers: structural framing, then wall framing and
sheathing). Soft by construction: a crew that does something out of order loses
nothing. tests/test_trade_sequence.py pins that every id exists in its trade.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["TRADE_STAGES", "TRADE_ORDER", "stages_for", "position", "next_work"]

TRADE_STAGES: Dict[str, List[List[str]]] = {
    "Excavation": [
        ["site_prep", "exc_clearing"],
        ["excavation", "exc_mass", "dewatering", "exc_trenching"],
        ["exc_soil_export"],
        ["backfill", "compaction", "exc_grading"],
    ],
    "Shoring / underpinning": [
        ["shor_sheeting", "shor_soldier_piles", "shoring"],
        ["shor_tiebacks", "bracing"],
        ["underpinning"],
        ["shor_monitoring_wells", "shor_vibration_monitoring"],
    ],
    "Piles / caissons": [
        ["pile_driving", "pile_auger_cast", "pile_caissons", "piles"],
        ["pile_load_testing"],
        ["pile_cutoff"],
        ["pile_caps"],
    ],
    "Foundation / Concrete": [
        ["footings", "conc_footing_rebar"],
        ["foundation_walls", "grade_beams", "conc_dowels"],
        ["vapour_barrier", "conc_mesh", "cellar_slab_rebar", "mep_sleeves_embeds"],
        ["pour_cellar_slab", "conc_slab_on_grade"],
        ["columns_shearwall_rebar", "columns_shearwall_formwork", "conc_embed_plates", "conc_anchor_bolts",
         "conc_blockouts"],
        ["pour_columns_shearwalls"],
        ["strip_column_formwork"],
        ["slab_shoring_formwork", "slab_rebar", "edge_forms", "post_tension_tendons", "mep_floor_penetrations"],
        ["pour_slab"],
        ["curing_slab"],
        ["strip_formwork", "reshore"],
        ["pour_topping_slab", "pour_bulkhead_slab"],
        ["curing_topping_slab", "strip_bulkhead_formwork", "conc_finishing", "patching"],
    ],
    "Wood framing": [
        ["framing_structural", "wood_sill_plates", "wood_floor_joists", "wood_subfloor", "wood_wall_framing",
         "wood_roof_framing", "framing_floor_penetrations"],
        ["wood_sheathing", "bracing"],
    ],
    "CFS (cold-formed steel)": [
        ["framing_structural", "cfs_wall_panels", "floor_joists_decking", "subfloor_sheathing",
         "framing_floor_penetrations"],
        ["bracing", "cfs_roof_framing_deck", "cfs_bulkheads_parapets"],
    ],
    "Interior framing": [
        ["interior_framing", "iframe_shaft_walls", "iframe_door_bucks"],
        ["blocking", "furring"],
        ["iframe_ceiling_drops", "iframe_soffits_bulkheads"],
    ],
    "Plumbing": [
        ["underground_plumbing"],
        ["under_slab_mep"],
        ["mep_rough_in", "plmb_sanitary_rough", "plmb_vent_rough"],
        ["plmb_domestic_water_rough", "plmb_riser_install", "plmb_gas_piping", "plmb_water_heater"],
        ["hydrostatic_test", "fixtures", "plmb_fixture_set", "plmb_booster_pump"],
        ["plmb_trim_out"],
    ],
    "Electrical": [
        ["elec_temp_power", "elec_underground_conduit"],
        ["under_slab_mep", "elec_slab_conduit"],
        ["mep_rough_in", "elec_panel_rough", "elec_branch_rough_in", "elec_device_boxes"],
        ["elec_pull_wire", "elec_switchgear"],
        ["fixtures", "elec_fixture_install", "elec_panel_termination"],
        ["elec_devices_trim", "elec_generator"],
        ["elec_testing_energizing"],
    ],
    "HVAC": [
        ["under_slab_mep"],
        ["hvac_sleeves_penetrations", "mep_rough_in"],
        ["hvac_ductwork_rough", "hvac_riser_duct", "hvac_refrigerant_piping", "hvac_condensate_piping"],
        ["hvac_equipment_set", "hvac_rooftop_unit", "hvac_vrf_split", "roof_mep"],
        ["hvac_grilles_diffusers"],
        ["hvac_balancing"],
        ["hvac_startup_commissioning"],
    ],
    "Drywall": [
        ["dry_hang_board", "drywall", "dry_ceiling_board"],
        ["dry_corner_bead", "taping"],
        ["dry_skim_coat", "patching"],
        ["dry_sand"],
    ],
}

#: When a roster string resolves to several trades (a concrete crew also does the
#: foundation phase), their stages are joined in the order the work is done.
TRADE_ORDER: Tuple[str, ...] = (
    "Excavation", "Shoring / underpinning", "Piles / caissons", "Foundation / Concrete",
    "Wood framing", "CFS (cold-formed steel)", "Interior framing",
    "Plumbing", "Electrical", "HVAC", "Drywall",
)


def stages_for(trades: Iterable[str]) -> List[List[str]]:
    """The joined stages of the taxonomy trades a roster string resolves to,
    in work order; [] for trades with no sequence written."""
    have = set(trades or [])
    out: List[List[str]] = []
    for t in TRADE_ORDER:
        if t in have:
            out += [list(s) for s in TRADE_STAGES[t]]
    return out


def position(stages: Sequence[Sequence[str]], ids: Iterable[str]) -> int:
    """The furthest stage any of `ids` is in; -1 when none is in the sequence."""
    ids = set(ids or [])
    best = -1
    for n, stage in enumerate(stages):
        if ids & set(stage):
            best = n
    return best


def next_work(stages: Sequence[Sequence[str]], last_ids: Iterable[str]) -> List[Tuple[str, str, str]]:
    """[(activity id, "same" | "next", anchor id)] for the crew whose most recent
    worked day held `last_ids`: the rest of the stage it is in, then the stage
    after it. The anchor is the activity (of the crew's last day) it follows."""
    last = [i for i in (last_ids or []) if i]
    at = position(stages, last)
    if at < 0:
        return []
    anchor = next((i for i in last if i in stages[at]), last[0])
    out: List[Tuple[str, str, str]] = []
    for i in stages[at]:
        if i not in last:
            out.append((i, "same", anchor))
    if at + 1 < len(stages):
        for i in stages[at + 1]:
            if i not in last:
                out.append((i, "next", anchor))
    return out
