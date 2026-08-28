"""Trade taxonomy — which activities belong to which trade.

PROVENANCE. This list is approved by the operator via direct instruction.
THERE IS NO SIGNED SIGN-OFF DOCUMENT FOR IT, and none is required: unlike
sequence_rules_v1, this file asserts no legal requirement and encodes no
construction precedence. It only answers "which activities should this crew be
offered", so a wrong entry offers the wrong chip — it does not misstate a
filed record. Compare sequence_rules_v1's header, which is explicitly PENDING
NYC DOB DOMAIN-EXPERT SIGN-OFF and whose contents are precedence claims.

WHY IT IS A SEPARATE FILE. sequence_rules_v1 is the signed-pending sequence
authority. Nothing here edits it — not a node, not an edge, not a `trade`
field. This module only:

  * MAPS trades to node ids that already exist there (so their EDGES survive
    untouched — the sequence loop depends on them), and
  * ADDS new nodes for activities that had none.

A node's own `trade` field therefore keeps whatever the sequence author gave
it. This map is the CP-facing grouping and is allowed to disagree: `bracing`
is `cfs` on the node and is claimed here by Shoring, CFS and Wood framing,
because all three brace things.

A NODE MAY BE CLAIMED BY SEVERAL TRADES. That is the mechanism that resolves
the eleven activity names the list reuses across trades (bracing, blocking,
patching, flashing, floor joists, layout, furring, debris removal, temporary
protection, hydrostatic test, floor penetrations). One node id, several
claimants — no duplicate ids, and no second node competing with the edged one.

NEW NODES HAVE NO EDGES, DELIBERATELY. A trade-filtered chip list is NOT a
sequenced one. A new electrical activity can be offered to an electrician but
cannot rank off what happened yesterday, because nothing declares what follows
it. Edges are precedence claims and belong to the signed sequence document.
None were invented here.

THREE CALLS THE OPERATOR HAS NOT RULED ON, made here and flagged:

  1. SPLIT ACTIVITIES REFERENCE THE EXISTING COMBINED NODE. The list splits
     "pour columns" / "pour shear walls"; the graph has one edged
     `pour_columns_shearwalls`. Creating two new nodes would orphan that edge,
     and the instruction to keep edges alive outranks the finer wording. The
     CP sees the combined label. Same for column/shear-wall rebar, column/
     shear-wall formwork, window/exterior-door install, and drainage board /
     filter fabric.
  2. THE LIST IS 39 TRADES, NOT THE 35 STATED. 6+6+5+7+11+4. All 39 are here.
  3. ROSTER STRINGS THAT SPAN TWO TRADES CLAIM BOTH — see ROSTER_TRADE_MAP.
"""

from __future__ import annotations

import re

from typing import Dict, List, Tuple

from app.scheduling.schedule_models import WorkPackage

TAXONOMY_VERSION = "trade_taxonomy_v1"

# ── New activities, as (id, label). Ids are trade-prefixed so an activity name
#    reused by two trades cannot collide. Nothing here has an edge.
_NEW: List[Tuple[str, str]] = []


def _n(node_id: str, label: str) -> str:
    _NEW.append((node_id, label))
    return node_id


# Shared new nodes — one id, claimed by several trades below.
SHARED_DEBRIS = _n("debris_removal", "debris removal")
SHARED_TEMP_PROTECTION = _n("temporary_protection", "temporary protection")
SHARED_LAYOUT = _n("trade_layout", "layout")
SHARED_FURRING = _n("furring", "furring")
SHARED_HYDRO = _n("hydrostatic_test", "hydrostatic test")
SHARED_FRAMING_PENETRATIONS = _n("framing_floor_penetrations",
                                 "floor penetrations and sleeves")

TRADES: Dict[str, List[str]] = {
    # ── SITEWORK AND FOUNDATION ──────────────────────────────────────────
    "Demolition": [
        _n("demo_interior", "interior demo"),
        _n("demo_structural", "structural demo"),
        _n("demo_abatement_support", "abatement support"),
        SHARED_DEBRIS,
        _n("demo_shoring", "shoring for demo"),
        _n("demo_protection_adjacent", "protection of adjacent"),
    ],
    "Excavation": [
        "site_prep", _n("exc_clearing", "clearing"), "excavation",
        _n("exc_mass", "mass excavation"), _n("exc_trenching", "trenching"),
        "dewatering", _n("exc_soil_export", "soil export"),
        "backfill", "compaction", _n("exc_grading", "grading"),
    ],
    "Shoring / underpinning": [
        _n("shor_sheeting", "sheeting"),
        _n("shor_soldier_piles", "soldier piles and lagging"),
        _n("shor_tiebacks", "tiebacks"),
        "bracing", "shoring", "underpinning",
        _n("shor_monitoring_wells", "monitoring wells"),
        _n("shor_vibration_monitoring", "vibration monitoring"),
    ],
    "Piles / caissons": [
        _n("pile_driving", "pile driving"),
        _n("pile_auger_cast", "auger cast piles"),
        _n("pile_caissons", "caissons"),
        "piles", "pile_cutoff", "pile_caps",
        _n("pile_load_testing", "load testing"),
    ],
    "Site utilities": [
        _n("util_water_service", "water service"),
        _n("util_sewer_connection", "sewer connection"),
        _n("util_storm_connection", "storm connection"),
        _n("util_gas_service", "gas service"),
        _n("util_vault", "utility vault"),
        _n("util_tap_connection", "tap connection"),
        _n("util_site_drainage", "site drainage"),
    ],
    "Waterproofing": [
        "waterproofing", "drainage_board", "protection_board",
        _n("wpf_below_grade_membrane", "below-grade membrane"),
        _n("wpf_elevator_pit", "elevator pit waterproofing"),
    ],

    # ── STRUCTURE ────────────────────────────────────────────────────────
    # Formwork, rebar and embeds are FOLDED IN per the operator: one company
    # does the full package on his jobs.
    "Foundation / Concrete": [
        "footings", "foundation_walls", "grade_beams",
        _n("conc_slab_on_grade", "slab on grade"),
        _n("conc_footing_rebar", "footing rebar"),
        "columns_shearwall_rebar", "slab_rebar", "cellar_slab_rebar",
        _n("conc_dowels", "dowels"), "post_tension_tendons",
        _n("conc_mesh", "mesh"),
        "columns_shearwall_formwork", "slab_shoring_formwork", "edge_forms",
        "mep_sleeves_embeds", "mep_floor_penetrations",
        _n("conc_embed_plates", "embed plates"),
        _n("conc_anchor_bolts", "anchor bolts"),
        _n("conc_blockouts", "blockouts"),
        "vapour_barrier",
        "pour_columns_shearwalls", "pour_slab", "pour_cellar_slab",
        "pour_topping_slab", "pour_bulkhead_slab",
        "curing_slab", "curing_topping_slab",
        "strip_column_formwork", "strip_formwork", "strip_bulkhead_formwork",
        "reshore", _n("conc_finishing", "finishing"), "patching",
    ],
    "Structural steel": [
        _n("steel_column_erection", "column erection"),
        _n("steel_beam_erection", "beam erection"),
        _n("steel_decking", "decking"),
        _n("steel_bolting", "bolting"),
        _n("steel_welding", "welding"),
        _n("steel_shear_studs", "shear studs"),
        _n("steel_fireproofing_prep", "fireproofing prep"),
        _n("steel_sleeves_penetrations", "steel sleeves and penetrations"),
        _n("steel_staircase", "steel staircase"),
        _n("steel_railings", "railings"),
        _n("steel_misc_structural", "miscellaneous structural"),
        _n("steel_dunnage", "dunnage"),
        _n("steel_lintels_angles", "lintels and angles"),
    ],
    "CFS (cold-formed steel)": [
        "cfs_wall_panels", "floor_joists_decking", "subfloor_sheathing",
        "bracing",
        _n("cfs_bulkheads_parapets", "CFS bulkheads and parapets"),
        "cfs_roof_framing_deck", SHARED_FRAMING_PENETRATIONS,
    ],
    "Wood framing": [
        _n("wood_sill_plates", "sill plates"),
        _n("wood_wall_framing", "wall framing"),
        _n("wood_floor_joists", "floor joists"),
        _n("wood_subfloor", "subfloor"),
        _n("wood_roof_framing", "roof framing"),
        _n("wood_sheathing", "sheathing"),
        "blocking", "bracing", SHARED_FRAMING_PENETRATIONS,
    ],
    "Carpentry (rough)": [
        SHARED_LAYOUT, _n("carpr_rough_framing", "rough framing"),
        "blocking", SHARED_FURRING, _n("carpr_backing", "backing"),
        SHARED_TEMP_PROTECTION, _n("carpr_temporary_stairs", "temporary stairs"),
    ],
    "Carpentry (finish)": [
        _n("carpf_door_install", "door install"),
        _n("carpf_door_hardware", "door hardware"),
        "millwork",
        _n("carpf_trim_base", "trim and base"),
        _n("carpf_casing", "casing"),
        _n("carpf_closet_systems", "closet systems"),
        _n("carpf_shelving", "shelving"),
    ],

    # ── ENVELOPE ─────────────────────────────────────────────────────────
    "Masonry": [
        "masonry", "parapets",
        _n("mas_cmu_block", "CMU block"),
        _n("mas_brick_veneer", "brick veneer"),
        _n("mas_parging", "parging"),
        "flashing",
        _n("mas_lintels", "lintels"),
        _n("mas_pointing", "pointing"),
        _n("mas_cleaning", "masonry cleaning"),
        _n("mas_scaffolding", "scaffolding for masonry"),
    ],
    "Facade / cladding": [
        "facade", "facade_closeout",
        _n("fac_air_barrier", "air barrier"),
        _n("fac_rigid_insulation", "rigid insulation"),
        _n("fac_metal_panel", "metal panel"),
        _n("fac_stone_veneer", "stone veneer"),
        _n("fac_stucco_eifs", "stucco / EIFS"),
        _n("fac_rainscreen", "rainscreen"),
        _n("fac_sealants_caulking", "sealants and caulking"),
    ],
    "Windows and doors": [
        "window_and_exterior_door_install",
        _n("wind_storefront", "storefront"),
        _n("wind_curtain_wall", "curtain wall"),
        _n("wind_glazing", "glazing"),
        _n("wind_perimeter_sealant", "perimeter sealant"),
    ],
    "Roofing": [
        "temporary_roof", "finished_roofing", "flashing",
        _n("roof_insulation", "roof insulation"),
        _n("roof_membrane", "membrane"),
        _n("roof_parapet_cap", "parapet cap"),
        _n("roof_drains", "roof drains"),
        _n("roof_pavers_ballast", "pavers / ballast"),
        _n("roof_green", "green roof"),
    ],
    "Exterior sheet metal": [
        _n("sheet_coping", "coping"),
        _n("sheet_gutters_leaders", "gutters and leaders"),
        _n("sheet_scuppers", "scuppers"),
        _n("sheet_counterflashing", "counterflashing"),
        _n("sheet_louvers", "louvers"),
    ],

    # ── MEP ──────────────────────────────────────────────────────────────
    # Entirely new. This is the defect: an electrician was offered drywall
    # because no electrical activity existed anywhere in the graph.
    "Electrical": [
        # Shared legacy MEP nodes — they carry edges, and all three MEP trades
        # do this work. Claimed by each so the edges stay reachable.
        "under_slab_mep", "mep_rough_in", "fixtures",
        _n("elec_temp_power", "temp power"),
        _n("elec_underground_conduit", "underground conduit"),
        _n("elec_slab_conduit", "slab conduit"),
        _n("elec_panel_rough", "panel rough"),
        _n("elec_branch_rough_in", "branch rough-in"),
        _n("elec_pull_wire", "pull wire"),
        _n("elec_device_boxes", "device boxes"),
        _n("elec_fixture_install", "fixture install"),
        _n("elec_devices_trim", "devices and trim"),
        _n("elec_panel_termination", "panel termination"),
        _n("elec_switchgear", "switchgear"),
        _n("elec_generator", "generator"),
        _n("elec_testing_energizing", "testing and energizing"),
    ],
    "Low voltage": [
        _n("lv_conduit_pathways", "conduit and pathways"),
        _n("lv_cable_pull", "cable pull"),
        _n("lv_data_telecom_rough", "data / telecom rough"),
        _n("lv_fire_alarm_rough", "fire alarm rough"),
        _n("lv_fire_alarm_devices", "fire alarm devices"),
        _n("lv_security_cameras", "security and cameras"),
        _n("lv_access_control", "access control"),
        _n("lv_intercom", "intercom"),
        _n("lv_av_rough", "AV rough"),
        _n("lv_antenna_das", "antenna / DAS"),
        _n("lv_terminations_testing", "terminations and testing"),
    ],
    "Plumbing": [
        "underground_plumbing",
        "under_slab_mep", "mep_rough_in", "fixtures",
        _n("plmb_sanitary_rough", "sanitary rough"),
        _n("plmb_vent_rough", "vent rough"),
        _n("plmb_domestic_water_rough", "domestic water rough"),
        _n("plmb_riser_install", "riser install"),
        SHARED_HYDRO,
        _n("plmb_fixture_set", "fixture set"),
        _n("plmb_trim_out", "trim out"),
        _n("plmb_water_heater", "water heater"),
        _n("plmb_booster_pump", "booster pump"),
        _n("plmb_gas_piping", "gas piping"),
    ],
    "Fire protection": [
        _n("fp_standpipe", "standpipe"),
        _n("fp_sprinkler_mains", "sprinkler mains"),
        _n("fp_branch_piping", "branch piping"),
        _n("fp_head_rough_in", "head rough-in"),
        _n("fp_head_install_trim", "head install and trim"),
        SHARED_HYDRO,
        _n("fp_fire_pump", "fire pump"),
        _n("fp_valve_inspector_test", "valve and inspector test"),
    ],
    "HVAC": [
        "under_slab_mep", "mep_rough_in", "roof_mep",
        _n("hvac_sleeves_penetrations", "sleeves and penetrations"),
        _n("hvac_ductwork_rough", "ductwork rough"),
        _n("hvac_riser_duct", "riser duct"),
        _n("hvac_equipment_set", "equipment set"),
        _n("hvac_rooftop_unit", "rooftop unit"),
        _n("hvac_condensate_piping", "condensate piping"),
        _n("hvac_refrigerant_piping", "refrigerant piping"),
        _n("hvac_vrf_split", "VRF / split install"),
        _n("hvac_grilles_diffusers", "grilles and diffusers"),
        _n("hvac_balancing", "balancing"),
        _n("hvac_startup_commissioning", "startup and commissioning"),
    ],
    "Mechanical piping": [
        _n("mech_hydronic_piping", "hydronic piping"),
        _n("mech_chilled_water", "chilled water"),
        _n("mech_steam_piping", "steam piping"),
        _n("mech_pumps", "pumps"),
        _n("mech_pipe_insulation", "insulation of piping"),
        _n("mech_valves_specialties", "valves and specialties"),
        _n("mech_pressure_test", "pressure test"),
    ],
    "Elevator": [
        _n("elev_hoistway_prep", "hoistway prep"),
        _n("elev_rail_install", "rail install"),
        _n("elev_car_assembly", "car assembly"),
        _n("elev_machine_install", "machine install"),
        _n("elev_controller", "controller"),
        _n("elev_door_operators", "door operators"),
        _n("elev_testing_inspection", "testing and inspection"),
    ],

    # ── INTERIOR FIT-OUT ─────────────────────────────────────────────────
    "Interior framing": [
        SHARED_LAYOUT, "interior_framing",
        _n("iframe_door_bucks", "door bucks"),
        _n("iframe_soffits_bulkheads", "soffits and bulkheads"),
        "blocking",
        _n("iframe_shaft_walls", "shaft walls"),
        SHARED_FURRING,
    ],
    "Insulation": [
        "insulation",
        _n("insul_batt", "batt insulation"),
        _n("insul_spray_foam", "spray foam"),
        _n("insul_rigid_board", "rigid board"),
        _n("insul_acoustic", "acoustic insulation"),
        _n("insul_vapor_barrier", "vapor barrier"),
        _n("insul_firestopping_prep", "fire-stopping prep"),
    ],
    "Firestopping": [
        "firestopping",
        _n("fstop_penetration", "penetration firestopping"),
        _n("fstop_joint", "joint firestopping"),
        _n("fstop_head_of_wall", "head-of-wall"),
        _n("fstop_sleeve_sealing", "sleeve sealing"),
        _n("fstop_labeling", "labeling"),
    ],
    "Drywall": [
        "drywall", "taping",
        _n("dry_hang_board", "hang board"),
        _n("dry_sand", "sand"),
        _n("dry_skim_coat", "skim coat"),
        _n("dry_corner_bead", "corner bead"),
        "patching",
        _n("dry_ceiling_board", "ceiling board"),
    ],
    "Flooring": [
        "flooring",
        _n("floor_prep", "floor prep"),
        _n("floor_leveling", "leveling"),
        _n("floor_underlayment", "underlayment"),
        _n("floor_tile", "tile"),
        _n("floor_hardwood", "hardwood"),
        _n("floor_lvt_vinyl", "LVT / vinyl"),
        _n("floor_carpet", "carpet"),
        _n("floor_base_transitions", "base and transitions"),
        _n("floor_polish_seal", "polish and seal"),
    ],
    "Tile and stone": [
        _n("tile_waterproofing_pan", "waterproofing / pan"),
        _n("tile_substrate_prep", "substrate prep"),
        _n("tile_wall", "wall tile"),
        _n("tile_floor", "floor tile"),
        _n("tile_stone_slab", "stone slab"),
        _n("tile_grout", "grout"),
        _n("tile_sealing", "sealing"),
    ],
    "Painting": [
        "paint",
        _n("paint_prime", "prime"),
        _n("paint_first_coat", "first coat"),
        _n("paint_finish_coat", "finish coat"),
        _n("paint_touch_up", "touch-up"),
        _n("paint_exterior", "exterior painting"),
        _n("paint_staining", "staining"),
        _n("paint_special_coatings", "special coatings"),
    ],
    "Ceilings": [
        _n("ceil_grid_install", "grid install"),
        _n("ceil_tile_drop_in", "tile drop-in"),
        _n("ceil_gypsum", "gypsum ceiling"),
        _n("ceil_acoustic_panels", "acoustic panels"),
        _n("ceil_access_panels", "access panels"),
    ],
    "Cabinetry and countertops": [
        _n("cab_install", "cabinet install"),
        _n("cab_countertop_template", "countertop template"),
        _n("cab_countertop_install", "countertop install"),
        _n("cab_backsplash", "backsplash"),
        _n("cab_hardware", "hardware"),
        _n("cab_appliance_set", "appliance set"),
    ],
    "Specialties": [
        _n("spec_bath_accessories", "bath accessories"),
        _n("spec_signage", "signage"),
        _n("spec_lockers", "lockers"),
        _n("spec_fire_ext_cabinets", "fire extinguisher cabinets"),
        _n("spec_mailboxes", "mailboxes"),
        _n("spec_window_treatments", "window treatments"),
        _n("spec_appliances", "appliances"),
    ],
    "Waterproofing (interior)": [
        _n("wpi_wet_area_membrane", "wet area membrane"),
        _n("wpi_shower_pan", "shower pan"),
        _n("wpi_balcony", "balcony waterproofing"),
        _n("wpi_planter", "planter waterproofing"),
        _n("wpi_flood_test", "flood test"),
    ],

    # ── SITE AND CLOSEOUT ────────────────────────────────────────────────
    "Landscaping / hardscape": [
        _n("land_topsoil", "topsoil"),
        _n("land_planting", "planting"),
        _n("land_irrigation", "irrigation"),
        _n("land_pavers", "pavers"),
        _n("land_sidewalk", "sidewalk"),
        _n("land_curb", "curb"),
        _n("land_fencing", "fencing"),
        _n("land_site_lighting", "site lighting"),
    ],
    "Site safety": [
        "sidewalk_shed_work", "scaffold_erection", "scaffold_dismantle",
        _n("safe_netting", "netting"),
        _n("safe_guardrails", "guardrails"),
        _n("safe_protection", "protection"),
        _n("safe_site_fencing", "site fencing"),
        _n("safe_flagging", "flagging"),
    ],
    "General conditions": [
        "site_cleanup", SHARED_DEBRIS, "material_delivery", "hoisting",
        "crane_jump", "hoist_jump", "survey_layout", SHARED_TEMP_PROTECTION,
        _n("gc_winter_protection", "winter protection"),
        # GC milestones. They carry edges and would otherwise be unreachable
        # once filtering is on.
        "top_floor_structure_complete", "bulkhead", "elevator_overrun",
        "building_envelope_closed",
    ],
    "Closeout": [
        "punch_list", "final_inspection", "finishes",
        _n("close_final_clean", "final clean"),
        _n("close_commissioning", "commissioning"),
        _n("close_testing_balancing", "testing and balancing"),
        _n("close_owner_training", "owner training"),
        _n("close_tco_inspection", "TCO inspection"),
    ],
}

# New nodes, de-duplicated (a SHARED_* id is registered once but claimed by
# several trades).
_seen: set = set()
NEW_NODES: List[WorkPackage] = []
for _id, _label in _NEW:
    if _id in _seen:
        continue
    _seen.add(_id)
    # `trade` is the taxonomy trade that first declares it, purely so the node
    # is well-formed. The AUTHORITY for grouping is TRADES above, because a
    # node may be claimed by several trades.
    NEW_NODES.append(WorkPackage(id=_id, trade="taxonomy", scope=_label))

NEW_NODE_IDS = frozenset(n.id for n in NEW_NODES)

# ── Roster string -> taxonomy trades ─────────────────────────────────────
# The roster is free text an admin typed, so this is a normalized lookup, not
# an enum. A string may claim SEVERAL trades — two of the operator's five do.
#
# NOT CLEAN, AND RULED HERE RATHER THAN GUESSED SILENTLY:
#   "Formwork"          -> Foundation / Concrete. The operator folded formwork
#                          into that trade, so a Formwork crew sees the whole
#                          concrete package including pours it may not do.
#   "HVAC / Mechanical" -> HVAC *and* Mechanical piping. The string spans both.
#   "Carpentry"         -> Carpentry (rough) *and* (finish). Same.
ROSTER_TRADE_MAP: Dict[str, List[str]] = {
    "concrete": ["Foundation / Concrete"],
    "formwork": ["Foundation / Concrete"],
    "rebar": ["Foundation / Concrete"],
    "foundation": ["Foundation / Concrete"],
    "electrical": ["Electrical"],
    "electric": ["Electrical"],
    # THE MAN, NOT THE TRADE. A roster is written by whoever is standing at
    # the gate, and he writes what a man IS. Every worker-noun below was
    # unmapped and fell back to all 86 chips.
    "electrician": ["Electrical"],
    # AND THE PLURAL, which is what a roster of five men is actually written
    # in. "Framers - 5 workers" sat on a live crew card resolving to NOTHING
    # and being offered site prep, excavation, shoring and underpinning off the
    # project's prior day, while the plumber and electrician crews beside it
    # were correct -- purely because someone had typed those two singular.
    # normalize_roster_trade lowercases and collapses whitespace and does no
    # morphology, and a single token that misses cannot be rescued by the split
    # path, which needs two parts.
    #
    # THE RULE APPLIED HERE: a plural is added where the plural is a word a
    # person writes on a roster -- every agent noun (the man), and the
    # countable things. It is NOT added to the gerunds and mass nouns
    # ("framing", "concrete", "roofing", "drywall"): nobody writes "framings",
    # and a key that cannot be typed is noise in a map whose whole risk is a
    # wrong entry looking exactly like a right one. Keys already plural
    # ("piles", "ceilings", "site utilities", "windows and doors",
    # "specialties", "general conditions") are left alone -- adding their
    # singular is SINGULARISATION, which is a separate change with its own test
    # asserting the fallback never alters an existing resolution.
    "electricians": ["Electrical"],
    "low voltage": ["Low voltage"],
    "hvac": ["HVAC", "Mechanical piping"],
    # "hvac / mechanical" and "hvac/mechanical" USED TO BE HERE, as two literal
    # keys beside this one. They were the separator problem met and patched per
    # spelling rather than fixed: `Concrete / Cement` on a live project resolved
    # to NOTHING for exactly the same reason and nobody had patched that one.
    # trades_for_roster now splits on separators, so both spellings resolve
    # through "hvac" + "mechanical". Deleting them is the test of whether the
    # rule is real — if the rule regresses, HVAC breaks loudly.
    "mechanical": ["HVAC", "Mechanical piping"],
    "plumbing": ["Plumbing"],
    "plumber": ["Plumbing"],
    "plumbers": ["Plumbing"],
    "fire protection": ["Fire protection"],
    "sprinkler": ["Fire protection"],
    "sprinklers": ["Fire protection"],
    "elevator": ["Elevator"],
    "elevators": ["Elevator"],
    "carpentry": ["Carpentry (rough)", "Carpentry (finish)"],
    "carpenter": ["Carpentry (rough)", "Carpentry (finish)"],
    "carpenters": ["Carpentry (rough)", "Carpentry (finish)"],
    "rough carpentry": ["Carpentry (rough)"],
    "finish carpentry": ["Carpentry (finish)"],
    "demolition": ["Demolition"],
    "demo": ["Demolition"],
    "excavation": ["Excavation"],
    "shoring": ["Shoring / underpinning"],
    "underpinning": ["Shoring / underpinning"],
    "piles": ["Piles / caissons"],
    "site utilities": ["Site utilities"],
    "waterproofing": ["Waterproofing", "Waterproofing (interior)"],
    "structural steel": ["Structural steel"],
    "steel": ["Structural steel"],
    # STRUCTURAL ONLY, by ruling. In NYC "ironworker" covers structural AND
    # reinforcing, and reinforcing lives inside Foundation / Concrete — so
    # claiming both would hand a rebar crew the whole concrete package:
    # footings, pours, curing, stripping. Under-mapping costs four sequenced
    # chips; over-mapping puts another trade's work in front of a crew on a
    # signed log. Not symmetric.
    "ironworker": ["Structural steel"],
    # Structural only, for the reason given directly above: the plural inherits
    # the ruling, it does not widen it.
    "ironworkers": ["Structural steel"],
    "cfs": ["CFS (cold-formed steel)"],
    "cold-formed steel": ["CFS (cold-formed steel)"],
    "wood framing": ["Wood framing"],
    "framing": ["Interior framing", "Wood framing"],
    # THE MAN WHO DOES IT, AND THERE WERE FIVE OF HIM. This is the string that
    # was on the live crew card. Both loops, exactly as "framing" claims both:
    # a crew written "Framers" has not said which, and the union is what the
    # gerund already resolves to. Narrowing it here would make the two spellings
    # of one trade resolve differently, which is the defect the split rule
    # exists to prevent.
    "framer": ["Interior framing", "Wood framing"],
    "framers": ["Interior framing", "Wood framing"],
    "masonry": ["Masonry"],
    "mason": ["Masonry"],
    "masons": ["Masonry"],
    "facade": ["Facade / cladding"],
    "cladding": ["Facade / cladding"],
    "windows and doors": ["Windows and doors"],
    "glazing": ["Windows and doors"],
    "roofing": ["Roofing"],
    "roofer": ["Roofing"],
    "roofers": ["Roofing"],
    "sheet metal": ["Exterior sheet metal"],
    "interior framing": ["Interior framing"],
    "insulation": ["Insulation"],
    "firestopping": ["Firestopping"],
    "drywall": ["Drywall"],
    "flooring": ["Flooring"],
    "tile": ["Tile and stone"],
    "stone": ["Tile and stone"],
    "painting": ["Painting"],
    "painter": ["Painting"],
    "painters": ["Painting"],
    "ceilings": ["Ceilings"],
    "cabinetry": ["Cabinetry and countertops"],
    "millwork": ["Carpentry (finish)", "Cabinetry and countertops"],
    "specialties": ["Specialties"],
    "landscaping": ["Landscaping / hardscape"],
    "hardscape": ["Landscaping / hardscape"],
    "site safety": ["Site safety"],
    "scaffold": ["Site safety"],
    "scaffolds": ["Site safety"],
    # A live roster string. The two-word form was here and the bare noun a CP
    # actually types was not.
    "safety": ["Site safety"],
    "general conditions": ["General conditions"],
    "gc": ["General conditions"],
    "general contractor": ["General conditions"],
    "closeout": ["Closeout"],
}


def normalize_roster_trade(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


# Separators an admin puts between two trades in one field. NOT the word "and":
# `Windows and doors` and `Tile and stone` are canonical TRADE NAMES, and while
# whole-string matching below catches them first, a splitter that cannot break
# them at all is safer than one that relies on the order of two checks.
_ROSTER_SEPARATOR_RE = r"[/,&+;]"


def _split_roster(key: str) -> List[str]:
    """`concrete / cement` -> ['concrete', 'cement']. Order kept, deduped."""
    out: List[str] = []
    for part in re.split(_ROSTER_SEPARATOR_RE, key):
        p = " ".join(part.split())
        if p and p not in out:
            out.append(p)
    return out


def _lookup_one(key: str) -> List[str]:
    """One already-normalized token -> trades, or []."""
    if key in ROSTER_TRADE_MAP:
        return list(ROSTER_TRADE_MAP[key])
    # A trade named exactly as the taxonomy names it.
    for trade in TRADES:
        if normalize_roster_trade(trade) == key:
            return [trade]
    return []


def trades_for_roster(value) -> List[str]:
    """Taxonomy trades a free-text roster string claims. [] when unrecognized.

    An unrecognized string is NOT an error and must never empty a crew's chip
    list — the caller falls back to the unfiltered catalogue. Offering
    everything is worse than offering the right thing, and far better than
    offering nothing.

    WHOLE STRING FIRST, THEN SPLIT. Canonical trade names contain the very
    characters used to join two trades — `Foundation / Concrete`,
    `Shoring / underpinning`, `CFS (cold-formed steel)` — so an exact match must
    win before anything is taken apart.

    WHY SPLIT AT ALL. `normalize_roster_trade` only lowercased and collapsed
    whitespace, so `Concrete` resolved to Foundation / Concrete and
    `Concrete / Cement` — the same trade, typed by a different admin on a live
    project — resolved to nothing and fell back to all 86 chips. The map had
    been patched with two literal `hvac / mechanical` spellings by someone who
    hit this and treated it as a missing synonym. It is a missing rule.

    PARTIAL MATCH WINS. `Concrete / Cement` resolves to Foundation / Concrete:
    a crew typed that way is doing concrete, and one unrecognized half must not
    discard the recognized one. `Steel / Cleaning` therefore resolves to
    Structural steel alone — cleaning is not a taxonomy trade, and the work that
    crew actually logs is in the always-available band every crew already gets.
    """
    key = normalize_roster_trade(value)
    if not key:
        return []
    whole = _lookup_one(key)
    if whole:
        return whole
    parts = _split_roster(key)
    if len(parts) < 2:
        return []                       # nothing to split; already missed above
    out: List[str] = []
    for part in parts:
        for trade in _lookup_one(part):
            if trade not in out:
                out.append(trade)
    return out


def node_ids_for_trades(trades) -> frozenset:
    """Every node id the given taxonomy trades claim."""
    out: set = set()
    for t in (trades or []):
        out.update(TRADES.get(t, ()))
    return frozenset(out)
