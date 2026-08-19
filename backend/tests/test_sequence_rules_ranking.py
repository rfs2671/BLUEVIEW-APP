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
    LABEL_ACRONYMS,
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
    """Still true, and now the stronger claim: they are reachable in EVERY
    prior state, including a bogus one, without a band of their own."""
    states = [[], ["excavation"], ["pour_slab"], ["punch_list"], ["bogus"]]
    for prior in states:
        ids = set(_ids(_rank(prior_activity_ids=prior)))
        assert set(ALWAYS_AVAILABLE_ORDER) <= ids, prior


def test_the_always_available_band_is_empty_and_the_key_survives():
    """RE-POINTED, not deleted.

    This used to assert the band held ALWAYS_AVAILABLE_ORDER in a stable order
    on every crew card. Operator ruling: a crew card offers that crew's trade
    work and nothing else — offering an HVAC crew "scaffold dismantle" and
    "site clean-up" was offering them another sub's work. The ten now flow
    through suggested/catalog by trade, and the guarantee worth holding moved
    with them (see the test below).

    THE KEY STILL EXISTS AND IS EMPTY. The frontend ships by OTA and the field
    binary cannot receive one, so a client older than this deploy must get an
    empty list rather than a missing band.
    """
    for prior in (["excavation"], ["punch_list"], [], ["bogus"]):
        assert _ids(_rank(prior_activity_ids=prior), "always_available") == [], prior


def test_the_ten_are_still_reachable_somewhere():
    """The ruling MOVED them; it did not delete them from the product.

    Removing either the subtraction or the `placed` exclusion alone would have
    made all ten unreachable — held out of `suggested` by one and out of
    `catalog` by the other. This is the assertion that catches that.
    """
    ids = set(_ids(_rank(prior_activity_ids=["excavation"])))
    missing = [a for a in ALWAYS_AVAILABLE_ORDER if a not in ids]
    assert missing == [], f"unreachable after de-special-casing: {missing}"


def test_the_ten_can_reach_the_SUGGESTED_band_not_just_the_catalogue():
    """REACHABLE IS NOT ENOUGH — they must be RANKABLE.

    Restoring `suggested -= ALWAYS_AVAILABLE_IDS` leaves them reachable, because
    `placed` no longer holds them out of the catalogue, so a reachability check
    alone stays green while the behaviour regresses: a scaffolding crew whose
    ranked work is scaffold_dismantle would find it in the expander instead of
    its primary four. Found by mutation; this is the assertion that kills it.

    Asserted as "at least one, in some state" rather than naming an id, so it
    tracks the graph rather than a fixture.
    """
    seen = set()
    for prior in ([], ["excavation"], ["pour_slab"], ["punch_list"],
                  ["scaffold_erection"], ["interior_framing"], ["mep_rough_in"]):
        seen |= set(_ids(_rank(prior_activity_ids=prior), "suggested"))
    reached = seen & set(ALWAYS_AVAILABLE_ORDER)
    assert reached, (
        "not one of the ten can be SUGGESTED — they are still held out of the "
        "ranked band and can only be found in the catalogue")


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


# ── 14. window install renamed to include exterior doors ─────────────
def test_window_chip_is_renamed_to_include_exterior_doors():
    g = build_sequence_rules_v1()
    by_id = {n.id: n for n in g.nodes}
    assert "window_install" not in by_id                 # old id is gone
    assert by_id["window_and_exterior_door_install"].scope == (
        "window and exterior door install")
    labels = {n.scope for n in g.nodes}
    assert "window install" not in labels                # old label is gone


def test_renamed_window_node_keeps_all_its_rule_edges():
    succ = _succ()
    # every "floor complete" source still offers it, and it still opens
    # facade close-out and interior framing
    for src in ("reshore", "subfloor_sheathing", "pour_topping_slab",
                "masonry", "facade"):
        assert "window_and_exterior_door_install" in succ[src], src
    assert {"facade_closeout", "interior_framing"} <= set(
        succ["window_and_exterior_door_install"])


def test_floor_complete_offers_masonry_facade_window_and_framing():
    # "any floor stripped and reshored / CFS floor complete -> masonry,
    #  facade, window and exterior door install, framing"
    succ = _succ()
    expected = {"masonry", "facade", "window_and_exterior_door_install",
                "interior_framing"}
    for src in ("reshore", "subfloor_sheathing", "pour_topping_slab"):
        assert expected <= set(succ[src]), src


# ── 15. the dried-in milestone ───────────────────────────────────────
def test_envelope_node_is_relabelled_dried_in():
    g = build_sequence_rules_v1()
    by_id = {n.id: n for n in g.nodes}
    assert by_id["building_envelope_closed"].scope == (
        "building envelope closed / dried-in")


def test_dried_in_is_offered_only_off_the_window_and_door_install():
    assert _preds("building_envelope_closed") == [
        "window_and_exterior_door_install",
    ]


def test_rejected_derived_facade_closeout_edge_is_gone():
    succ = _succ()
    assert "building_envelope_closed" not in succ.get("facade_closeout", [])


def test_window_and_door_install_offers_the_dried_in_chip():
    sug = _ids(_rank(prior_activity_ids=["window_and_exterior_door_install"]),
               "suggested")
    assert "building_envelope_closed" in sug


# ── 16. corrected interior fit-out entry rule ────────────────────────
DRIED_IN = "building_envelope_closed"


def _reachable_without_dried_in():
    """Every node reachable from the cold-start set without ever passing
    THROUGH the dried-in milestone."""
    succ = _succ()
    seen, stack = set(COLD_START_IDS), list(COLD_START_IDS)
    while stack:
        cur = stack.pop()
        if cur == DRIED_IN:          # do not traverse past the milestone
            continue
        for nxt in succ.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


# HARD REQUIREMENT 1 — framing and MEP rough-in do NOT require dried-in.
def test_framing_and_mep_rough_in_do_not_require_the_dried_in_milestone():
    reachable = _reachable_without_dried_in()
    assert "interior_framing" in reachable
    assert "mep_rough_in" in reachable
    # and dried-in no longer opens them at all
    succ = _succ()
    assert "interior_framing" not in succ[DRIED_IN]


# HARD REQUIREMENT 2 — insulation and drywall are reachable ONLY from dried-in.
def test_insulation_and_drywall_are_reachable_only_from_dried_in():
    reachable = _reachable_without_dried_in()
    assert "insulation" not in reachable
    assert "drywall" not in reachable
    # the only ways in: dried-in for both, plus insulation -> drywall, which is
    # itself only reachable through dried-in.
    assert _preds("insulation") == [DRIED_IN]
    assert _preds("drywall") == sorted([DRIED_IN, "insulation"])


def test_dried_in_opens_insulation_and_drywall_only():
    assert _succ()[DRIED_IN] == ["insulation", "drywall"]


def test_insulation_prep_node_is_deleted_and_leaves_no_reference():
    # OPERATOR RULING: the node was edgeless after the fit-out correction and
    # was deleted outright. Nothing may refer to it: not a node, not an edge
    # endpoint, and not a chip in any ranking.
    g = build_sequence_rules_v1()
    assert "insulation_prep" not in {n.id for n in g.nodes}
    endpoints = {e.from_node for e in g.edges} | {e.to_node for e in g.edges}
    assert "insulation_prep" not in endpoints
    for prior in ([], [DRIED_IN], ["interior_framing"], ["reshore"]):
        assert "insulation_prep" not in _ids(_rank(prior_activity_ids=prior)), prior


def test_firestopping_opens_inspection_only():
    # the earlier firestopping -> insulation edge was corrected away
    assert _succ()["firestopping"] == ["inspection"]


def test_corrected_interior_fit_out_chain_is_encoded_exactly():
    succ = _succ()
    assert set(succ["interior_framing"]) == {"mep_rough_in", "blocking",
                                             "inspection"}
    assert set(succ["mep_rough_in"]) == {"firestopping", "inspection",
                                         "interior_framing"}
    assert set(succ["insulation"]) == {"drywall", "inspection"}
    assert set(succ["drywall"]) == {"taping", "finishes", "flooring", "paint"}
    assert set(succ["taping"]) == {"paint", "flooring", "millwork"}
    for src in ("finishes", "flooring", "paint"):
        assert set(succ[src]) == {"fixtures", "punch_list", "final_inspection"}, src


def test_framing_before_dried_in_is_offered_in_the_ranking():
    # a CP who stripped and reshored a floor is offered framing and, once
    # framing is logged, MEP rough-in — with no dried-in entry anywhere.
    sug = _ids(_rank(prior_activity_ids=["reshore"],
                     structural_system="cast_in_place"), "suggested")
    assert "interior_framing" in sug and "mep_rough_in" in sug
    assert DRIED_IN not in sug
    assert "insulation" not in sug and "drywall" not in sug


def test_dried_in_ranking_offers_insulation_and_drywall():
    sug = _ids(_rank(prior_activity_ids=[DRIED_IN]), "suggested")
    assert {"insulation", "drywall"} <= set(sug)
    assert "interior_framing" not in sug


# ── 17. invariants re-verified after the operator corrections ────────
def test_no_hard_edge_type_was_introduced_by_the_corrections():
    g = build_sequence_rules_v1()
    assert {e.edge_type for e in g.edges} == {"soft_parallel_open"}


def test_rules_still_never_block_any_entry():
    # every node in the graph is still emitted as a chip for a mid-project
    # state, and "Other" is still last.
    g = build_sequence_rules_v1()
    r = _rank(prior_activity_ids=[DRIED_IN])
    ids = _ids(r)
    assert set(ids) == {n.id for n in g.nodes}
    assert ids[-1] == OTHER_ACTIVITY_ID
    assert all(c.selected is False for c in r.chips)


# ── 18. chip labels are lowercase house style ────────────────────────
# OPERATOR RULING: every chip label renders lowercase ("pour slab", "strip
# formwork"). The only exception is an embedded acronym, which keeps its own
# casing while the words around it stay lowercase ("under-slab MEP").
_ACRONYMS = set(LABEL_ACRONYMS)


def _offending_words(label):
    """Words in `label` that break the lowercase rule (acronyms exempted)."""
    bad = []
    for word in label.split():
        if word.strip("()/,.-") in _ACRONYMS:
            continue
        if word != word.lower():
            bad.append(word)
    return bad


def test_the_lowercase_guard_is_not_vacuous():
    # The guard must actually reject the pre-ruling spellings, and must accept
    # the acronym-bearing ones — otherwise the invariant tests below pin
    # nothing.
    assert _offending_words("Pour bulkhead / elevator overrun slab")
    assert _offending_words("Install roof framing and metal deck")
    assert _offending_words("Window and exterior door install")
    assert _offending_words("Building envelope closed / Dried-in")
    assert _offending_words("Other")
    assert _offending_words("building envelope closed / Dried-in")   # any word
    assert not _offending_words("under-slab MEP")
    assert not _offending_words("load-bearing CFS wall panels / studs")
    assert not _offending_words("pour slab")


def test_every_node_label_is_lowercase_except_for_acronyms():
    g = build_sequence_rules_v1()
    offenders = {n.id: _offending_words(n.scope)
                 for n in g.nodes if _offending_words(n.scope)}
    assert offenders == {}


def test_no_label_has_a_leading_uppercase_unless_an_acronym_demands_it():
    g = build_sequence_rules_v1()
    for n in g.nodes:
        first = n.scope.split()[0]
        if first.strip("()/,.-") in _ACRONYMS:
            continue                     # e.g. "MEP rough-in"
        assert not first[0].isupper(), (n.id, n.scope)


def test_the_four_mixed_case_labels_were_normalized():
    by_id = {n.id: n for n in build_sequence_rules_v1().nodes}
    assert by_id["pour_bulkhead_slab"].scope == (
        "pour bulkhead / elevator overrun slab")
    assert by_id["cfs_roof_framing_deck"].scope == (
        "install roof framing and metal deck")
    assert by_id["window_and_exterior_door_install"].scope == (
        "window and exterior door install")
    assert by_id["building_envelope_closed"].scope == (
        "building envelope closed / dried-in")
    assert by_id[OTHER_ACTIVITY_ID].scope == "other"


def test_acronym_labels_keep_the_acronym_and_lowercase_everything_else():
    by_id = {n.id: n for n in build_sequence_rules_v1().nodes}
    assert by_id["under_slab_mep"].scope == "under-slab MEP"
    assert by_id["mep_sleeves_embeds"].scope == "MEP sleeves and embeds"
    assert by_id["mep_floor_penetrations"].scope == (
        "MEP floor penetrations / sleeves")
    assert by_id["roof_mep"].scope == "roof MEP"
    assert by_id["mep_rough_in"].scope == "MEP rough-in"
    assert by_id["cfs_wall_panels"].scope == (
        "load-bearing CFS wall panels / studs")
    # ...and those are the ONLY labels carrying an uppercase run.
    upper = {n.id for n in build_sequence_rules_v1().nodes
             if any(ch.isupper() for ch in n.scope)}
    assert upper == {"under_slab_mep", "mep_sleeves_embeds",
                     "mep_floor_penetrations", "roof_mep", "mep_rough_in",
                     "cfs_wall_panels"}


def test_ranked_chip_labels_follow_the_house_style():
    # The rendered chip labels, not just the node scopes. Remembered "Other"
    # entries are CP free text and are preserved verbatim, so they are exempt.
    r = _rank(prior_activity_ids=["reshore"], structural_system="cast_in_place",
              remembered_other_labels=["Tank pull"])
    for c in r.chips:
        if c.band == "remembered_other":
            continue
        assert not _offending_words(c.label), (c.id, c.label)
    assert r.chips[-1].label == "other"


def test_normalizing_labels_changed_no_node_id():
    # IDs are not labels: the rename touched `scope` only.
    ids = {n.id for n in build_sequence_rules_v1().nodes}
    for nid in ("pour_bulkhead_slab", "cfs_roof_framing_deck",
                "window_and_exterior_door_install", "building_envelope_closed",
                OTHER_ACTIVITY_ID):
        assert nid in ids


def test_relabelling_broke_no_edge():
    # Dangling-endpoint and uniqueness re-check, after both operator changes.
    g = build_sequence_rules_v1()
    ids = [n.id for n in g.nodes]
    assert len(ids) == len(set(ids))
    endpoints = {e.from_node for e in g.edges} | {e.to_node for e in g.edges}
    assert endpoints <= set(ids)
    assert {e.edge_type for e in g.edges} == {"soft_parallel_open"}
