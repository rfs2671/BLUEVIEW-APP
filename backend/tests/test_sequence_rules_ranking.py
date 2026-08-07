"""sequence_rules_v1 data integrity + sequence_ranking behaviour guarantees.

Pure; no db, no HTTP. These tests exist to pin the four non-negotiables:
rank-order-only (never pre-select), "Other" always last, both loops under an
unknown structural system, and a rule miss that neither raises nor blocks.
"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from app.scheduling.schedule_models import ActivityChip  # noqa: E402
from app.scheduling.sequence_ranking import (  # noqa: E402
    other_entry_chip_id,
    rank_activities,
    resolve_structural_system,
)
from app.scheduling.sequence_rules_v1 import (  # noqa: E402
    ALWAYS_AVAILABLE_ORDER,
    BRANCH_ENTRY_CAST_IN_PLACE,
    BRANCH_ENTRY_CFS,
    COLD_START_IDS,
    FLAG_CAST_IN_PLACE,
    FLAG_CFS,
    OTHER_ACTIVITY_ID,
    RULES_VERSION,
    build_sequence_rules_v1,
    successors_by_id,
)


def _succ():
    return successors_by_id(build_sequence_rules_v1())


def _preds(target):
    return sorted({e.from_node for e in build_sequence_rules_v1().edges
                   if e.to_node == target})


def _rank(**kw):
    kw.setdefault("project_id", "p1")
    return rank_activities(**kw)


def _ids(ranking, band=None):
    return [c.id for c in ranking.chips if band is None or c.band == band]


# ── 1. never pre-selects ─────────────────────────────────────────────
def test_ranking_never_pre_selects_any_chip():
    for kw in (
        {},
        {"prior_activity_ids": ["excavation"]},
        {"prior_activity_ids": ["pour_slab"], "structural_system": "cast_in_place"},
        {"prior_activity_ids": ["subfloor_sheathing"], "structural_system": "cfs"},
        {"prior_activity_ids": ["bogus"], "remembered_other_labels": ["tank pull"]},
    ):
        r = _rank(**kw)
        assert r.chips, kw
        assert all(c.selected is False for c in r.chips), kw


def test_pre_selected_chip_is_unconstructible():
    # The guarantee is structural, not conventional: the model rejects it.
    with pytest.raises(ValidationError):
        ActivityChip(id="excavation", label="excavation", rank=0,
                     band="suggested", selected=True)


# ── 2. ranking is an ORDER — rank is dense, 0-based, ascending ───────
def test_rank_is_dense_zero_based_and_matches_position():
    r = _rank(prior_activity_ids=["drywall"])
    assert [c.rank for c in r.chips] == list(range(len(r.chips)))


# ── 3. "Other" is always present and always last ─────────────────────
def test_other_is_always_present_and_always_last():
    cases = [
        {},
        {"prior_activity_ids": []},
        {"prior_activity_ids": ["excavation"]},
        {"prior_activity_ids": ["pour_slab"], "structural_system": "cast_in_place"},
        {"prior_activity_ids": ["cfs_wall_panels"], "structural_system": "cfs"},
        {"prior_activity_ids": ["unknown_activity"]},
        {"remembered_other_labels": ["tank pull", "vault demo"]},
        {"prior_activity_ids": ["paint"], "remembered_other_labels": ["tank pull"]},
    ]
    for kw in cases:
        r = _rank(**kw)
        ids = _ids(r)
        assert ids.count(OTHER_ACTIVITY_ID) == 1, kw       # present exactly once
        assert ids[-1] == OTHER_ACTIVITY_ID, kw            # and never buried
        assert r.chips[-1].band == "other", kw


def test_other_is_never_emitted_inside_another_band():
    r = _rank(prior_activity_ids=["excavation"])
    for band in ("suggested", "remembered_other", "always_available", "catalog"):
        assert OTHER_ACTIVITY_ID not in _ids(r, band)


# ── 4. unknown structural system offers BOTH loops ───────────────────
def test_unknown_structural_system_offers_both_loops():
    for value in (None, "", "unknown", "  ", "typo", 7, ["cfs"]):
        r = _rank(prior_activity_ids=["pour_cellar_slab"], structural_system=value)
        assert r.structural_system == "unknown", value
        # The caller can state the system is not set.
        assert r.structural_system_set is False, value
        ids = _ids(r)
        assert BRANCH_ENTRY_CAST_IN_PLACE in ids, value
        assert BRANCH_ENTRY_CFS in ids, value
        # ...and both are actively suggested off the cellar slab.
        sug = _ids(r, "suggested")
        assert BRANCH_ENTRY_CAST_IN_PLACE in sug and BRANCH_ENTRY_CFS in sug


def test_set_structural_system_offers_only_its_own_loop():
    g = build_sequence_rules_v1()
    cip_only = {n.id for n in g.nodes if FLAG_CAST_IN_PLACE in n.requires}
    cfs_only = {n.id for n in g.nodes if FLAG_CFS in n.requires}
    assert cip_only and cfs_only and not (cip_only & cfs_only)

    cip = set(_ids(_rank(structural_system="cast_in_place")))
    assert cip_only <= cip and not (cfs_only & cip)
    assert _rank(structural_system="cast_in_place").structural_system_set is True

    cfs = set(_ids(_rank(structural_system="cfs")))
    assert cfs_only <= cfs and not (cip_only & cfs)


def test_resolve_structural_system_normalizes_without_raising():
    assert resolve_structural_system("Cast_In_Place ") == "cast_in_place"
    assert resolve_structural_system("CFS") == "cfs"
    for bad in (None, "", "steel", 0, object(), {"a": 1}):
        assert resolve_structural_system(bad) == "unknown"


# ── 5. a rule miss never raises and never blocks ─────────────────────
def test_rule_miss_never_raises_and_never_blocks():
    bad_inputs = [
        ["no_such_activity"],
        ["no_such_activity", "still_not_a_rule"],
        [None, 3, "", "   "],
        "not_a_list",
        None,
        [],
    ]
    baseline = set(_ids(_rank()))
    for bad in bad_inputs:
        r = _rank(prior_activity_ids=bad)              # must not raise
        ids = set(_ids(r))
        # Nothing was removed from the offer: a miss narrows nothing.
        assert ids == baseline, bad
        assert OTHER_ACTIVITY_ID in ids


def test_unrecognized_priors_are_reported_and_degrade_to_cold_start():
    r = _rank(prior_activity_ids=["zzz_unknown", "excavation"])
    assert r.unrecognized_prior_ids == ["zzz_unknown"]
    # The recognized prior still drives the suggestion; the miss is inert.
    assert "shoring" in _ids(r, "suggested")

    r2 = _rank(prior_activity_ids=["zzz_unknown"])
    assert r2.unrecognized_prior_ids == ["zzz_unknown"]
    # Every prior was a miss -> cold start, not an empty or error state.
    assert set(_ids(r2, "suggested")) == set(COLD_START_IDS)


# ── 6. cold start ────────────────────────────────────────────────────
def test_cold_start_suggests_the_project_start_set():
    assert set(_ids(_rank(), "suggested")) == set(COLD_START_IDS)


# ── 7. concurrency — both stay offered ───────────────────────────────
def test_concurrent_framing_and_mep_rough_in_both_stay_offered():
    a = _ids(_rank(prior_activity_ids=["interior_framing"]), "suggested")
    assert "interior_framing" in a and "mep_rough_in" in a
    b = _ids(_rank(prior_activity_ids=["mep_rough_in"]), "suggested")
    assert "interior_framing" in b and "mep_rough_in" in b


def test_multiple_activities_in_one_day_are_all_honoured():
    r = _rank(prior_activity_ids=["drywall", "taping"])
    sug = set(_ids(r, "suggested"))
    assert {"drywall", "taping"} <= sug          # both priors stay offered
    assert {"finishes", "flooring", "paint"} <= sug   # drywall's successors
    assert "millwork" in sug                          # taping's successor


# ── 8. remembered "Other" entries come back as chips ─────────────────
def test_remembered_other_entry_appears_as_its_own_chip_next_day():
    r = _rank(prior_activity_ids=["excavation"],
              remembered_other_labels=["Tank pull", "tank pull", "Vault demo"])
    band = [c for c in r.chips if c.band == "remembered_other"]
    # Case-insensitive de-dupe, first spelling kept, deterministic order.
    assert [c.label for c in band] == ["Tank pull", "Vault demo"]
    assert [c.id for c in band] == [other_entry_chip_id("Tank pull"),
                                    other_entry_chip_id("Vault demo")]
    # Remembered entries are chips like any other — never pre-selected, and
    # they do not displace the literal "Other" chip from last position.
    assert all(c.selected is False for c in band)
    assert _ids(r)[-1] == OTHER_ACTIVITY_ID


# ── 9. always-available chips are never sequence-gated ───────────────
def test_always_available_chips_present_for_every_state():
    states = [[], ["excavation"], ["pour_slab"], ["punch_list"], ["bogus"]]
    for prior in states:
        ids = set(_ids(_rank(prior_activity_ids=prior)))
        assert set(ALWAYS_AVAILABLE_ORDER) <= ids, prior


def test_always_available_band_order_is_stable_across_states():
    a = _ids(_rank(prior_activity_ids=["excavation"]), "always_available")
    b = _ids(_rank(prior_activity_ids=["punch_list"]), "always_available")
    assert a == b == list(ALWAYS_AVAILABLE_ORDER)


# ── 10. determinism ──────────────────────────────────────────────────
def test_determinism_identical_output():
    kw = dict(prior_activity_ids=["pour_slab", "reshore"],
              structural_system="cast_in_place",
              remembered_other_labels=["tank pull"])
    a = _rank(**kw)
    b = _rank(**kw)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


# ── 11. graph data integrity ─────────────────────────────────────────
def test_every_rule_edge_is_advisory_and_cannot_gate():
    g = build_sequence_rules_v1()
    assert g.version == RULES_VERSION
    assert {e.edge_type for e in g.edges} == {"soft_parallel_open"}


def test_no_edge_points_at_a_missing_node():
    g = build_sequence_rules_v1()
    ids = {n.id for n in g.nodes}
    dangling = sorted({e.from_node for e in g.edges} | {e.to_node for e in g.edges})
    assert [d for d in dangling if d not in ids] == []


def test_node_ids_are_unique_and_other_is_a_node():
    g = build_sequence_rules_v1()
    ids = [n.id for n in g.nodes]
    assert len(ids) == len(set(ids))
    assert OTHER_ACTIVITY_ID in ids


def test_every_chip_id_in_the_ranking_is_a_graph_node_or_a_remembered_other():
    g = build_sequence_rules_v1()
    ids = {n.id for n in g.nodes}
    r = _rank(prior_activity_ids=["excavation"], remembered_other_labels=["tank pull"])
    for c in r.chips:
        assert c.id in ids or c.id == other_entry_chip_id("tank pull"), c.id


def test_ranking_covers_every_offered_node_exactly_once():
    # Ordering, not filtering: with the system unset the whole catalogue is on
    # offer and no chip is duplicated.
    g = build_sequence_rules_v1()
    r = _rank(prior_activity_ids=["excavation"])
    ids = _ids(r)
    assert len(ids) == len(set(ids))
    assert set(ids) == {n.id for n in g.nodes}


# ── 12. topping out (3A) — the concrete bulkhead branch ──────────────
def test_bulkhead_slab_is_the_cast_in_place_route_to_top_out():
    succ = _succ()
    assert "pour_bulkhead_slab" in succ["pour_slab"]
    assert "pour_bulkhead_slab" in succ["strip_formwork"]
    assert succ["pour_bulkhead_slab"] == ["strip_bulkhead_formwork",
                                          "top_floor_structure_complete"]


def test_rejected_derived_top_out_edges_are_gone():
    succ = _succ()
    assert "top_floor_structure_complete" not in succ["pour_slab"]
    assert "top_floor_structure_complete" not in succ.get("pour_topping_slab", [])


def test_bulkhead_nodes_are_tagged_to_the_cast_in_place_branch():
    g = build_sequence_rules_v1()
    by_id = {n.id: n for n in g.nodes}
    bulkhead = {"pour_bulkhead_slab", "strip_bulkhead_formwork"}
    for nid in bulkhead:
        assert by_id[nid].requires == [FLAG_CAST_IN_PLACE]
    # ...so a CFS project is never offered them, and a concrete one always is.
    assert not (bulkhead & set(_ids(_rank(structural_system="cfs"))))
    assert bulkhead <= set(_ids(_rank(structural_system="cast_in_place")))


def test_pouring_a_slab_offers_the_bulkhead_pour_next():
    sug = _ids(_rank(prior_activity_ids=["pour_slab"],
                     structural_system="cast_in_place"), "suggested")
    assert "pour_bulkhead_slab" in sug
    assert "top_floor_structure_complete" not in sug


# ── 13. topping out (3B) — the CFS roof framing branch ───────────────
def test_roof_framing_deck_is_the_cfs_route_to_top_out():
    succ = _succ()
    assert "cfs_roof_framing_deck" in succ["cfs_wall_panels"]
    assert succ["cfs_roof_framing_deck"] == ["top_floor_structure_complete"]


def test_roof_framing_deck_is_tagged_to_the_cfs_branch():
    g = build_sequence_rules_v1()
    by_id = {n.id: n for n in g.nodes}
    assert by_id["cfs_roof_framing_deck"].requires == [FLAG_CFS]
    assert "cfs_roof_framing_deck" not in _ids(
        _rank(structural_system="cast_in_place"))
    assert "cfs_roof_framing_deck" in _ids(_rank(structural_system="cfs"))


def test_top_out_has_exactly_the_two_operator_supplied_predecessors():
    assert _preds("top_floor_structure_complete") == [
        "cfs_roof_framing_deck", "pour_bulkhead_slab",
    ]


def test_cfs_wall_panels_offers_the_roof_deck_next():
    sug = _ids(_rank(prior_activity_ids=["cfs_wall_panels"],
                     structural_system="cfs"), "suggested")
    assert "cfs_roof_framing_deck" in sug
