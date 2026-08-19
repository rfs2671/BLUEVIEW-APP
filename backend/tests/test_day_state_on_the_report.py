"""A day nobody worked must print as a COMPLETE record, not a negligent one."""
import server


def test_an_ordinary_day_says_nothing():
    for d in ({}, {"day_state": "worked"}, {"day_state": ""},
              {"day_state": None}, {"day_state": "junk"}, None):
        assert server._day_state_label(d) is None, (
            "the report asserted a washout nobody recorded")


def test_both_no_work_states_are_named():
    assert "Rain" in server._day_state_label({"day_state": "rain_no_work"})
    assert "Shutdown" in server._day_state_label({"day_state": "shutdown"})
    for k in ("rain_no_work", "shutdown"):
        # The POINT of the line: it says no work was performed, so a filed log
        # with crews and no activities reads as a complete record of a day
        # nobody worked rather than as a CP who signed without filling it in.
        assert "no work performed" in server._day_state_label({"day_state": k})


def test_the_day_state_is_not_an_activity_label():
    """The removed chips must not have been reinstated in the graph."""
    from app.scheduling.sequence_rules_v1 import (
        ALWAYS_AVAILABLE_ORDER, build_sequence_rules_v1,
    )
    ids = {n.id for n in build_sequence_rules_v1().nodes}
    for k in ("rain_no_work", "shutdown"):
        assert k not in ids, f"{k} is day-level and must not be a graph node"
        assert k not in ALWAYS_AVAILABLE_ORDER, f"{k} is not a chip"


def test_a_historical_log_carrying_the_removed_id_still_ranks():
    """A prior with a now-absent id is a rule miss, not a crash."""
    from app.scheduling.sequence_ranking import rank_activities
    r = rank_activities(project_id="p1", structural_system="cast_in_place",
                        prior_activity_ids=["rain_no_work"])
    assert r.chips, "a removed prior must fall back, never return nothing"
