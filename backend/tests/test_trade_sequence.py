"""The order each trade's work is normally done in: ids real, stages sane, next work right."""

import unittest
from datetime import date

from app.scheduling import trade_sequence as S
from app.scheduling import trade_taxonomy_v1 as T
from app.scheduling.schedule_hints import hints_for


class TheTablesAreReal(unittest.TestCase):

    def test_every_stage_id_belongs_to_its_trade(self):
        for trade, stages in S.TRADE_STAGES.items():
            allowed = set(T.TRADES[trade])
            for stage in stages:
                for i in stage:
                    self.assertIn(i, allowed, f"{i} is not in {trade}")

    def test_no_activity_twice_in_one_trade(self):
        for trade, stages in S.TRADE_STAGES.items():
            flat = [i for st in stages for i in st]
            self.assertEqual(len(flat), len(set(flat)), trade)

    def test_every_trade_with_a_sequence_is_in_the_work_order(self):
        self.assertEqual(sorted(S.TRADE_STAGES), sorted(S.TRADE_ORDER))

    def test_the_foundation_phase_comes_before_the_concrete(self):
        stages = S.stages_for(["Foundation / Concrete", "Piles / caissons", "Excavation", "Shoring / underpinning"])
        self.assertLess(S.position(stages, ["site_prep"]), S.position(stages, ["shoring"]))
        self.assertLess(S.position(stages, ["shoring"]), S.position(stages, ["piles"]))
        self.assertLess(S.position(stages, ["piles"]), S.position(stages, ["footings"]))
        self.assertLess(S.position(stages, ["footings"]), S.position(stages, ["pour_slab"]))


class NextWork(unittest.TestCase):

    def test_after_under_slab_mep_the_plumbers_rough_in(self):
        got = S.next_work(S.stages_for(["Plumbing"]), ["under_slab_mep"])
        nxt = [i for i, kind, _ in got if kind == "next"]
        self.assertEqual(nxt, ["mep_rough_in", "plmb_sanitary_rough", "plmb_vent_rough"])

    def test_the_rest_of_the_stage_is_concurrent_work(self):
        got = S.next_work(S.stages_for(["Plumbing"]), ["mep_rough_in"])
        self.assertEqual([i for i, k, _ in got if k == "same"], ["plmb_sanitary_rough", "plmb_vent_rough"])
        self.assertIn("plmb_domestic_water_rough", [i for i, k, _ in got if k == "next"])

    def test_the_real_588_plumbing_sequence_is_predicted(self):
        # MEP rough-in, then domestic water rough, then fixtures and the water heater
        st = S.stages_for(["Plumbing"])
        self.assertIn("plmb_domestic_water_rough", [i for i, k, _ in S.next_work(st, ["mep_rough_in"])])
        after = S.next_work(st, ["plmb_domestic_water_rough"])
        self.assertIn(("fixtures", "next"), [(i, k) for i, k, _ in after])
        self.assertIn(("plmb_water_heater", "same"), [(i, k) for i, k, _ in after])

    def test_framing_goes_structural_then_interior_then_ceiling_drops(self):
        st = S.stages_for(["Wood framing", "Interior framing"])
        self.assertIn("interior_framing", [i for i, k, _ in S.next_work(st, ["wood_sheathing"]) if k == "next"])
        self.assertIn("iframe_ceiling_drops", [i for i, k, _ in S.next_work(st, ["blocking"]) if k == "next"])

    def test_an_unknown_activity_or_trade_gives_nothing(self):
        self.assertEqual(S.next_work(S.stages_for(["Plumbing"]), ["no_such_thing"]), [])
        self.assertEqual(S.next_work([], ["mep_rough_in"]), [])
        self.assertEqual(S.stages_for(["Roofing"]), [])
        self.assertEqual(S.stages_for(None), [])

    def test_the_last_stage_has_no_next(self):
        got = S.next_work(S.stages_for(["Plumbing"]), ["plmb_trim_out"])
        self.assertEqual([k for _, k, _ in got], [])


class Chip:
    def __init__(self, i, label):
        self.id, self.label = i, label


class ScheduleHints(unittest.TestCase):
    PLAN = [
        {"name": "Pour slab - floor 2", "current_start": "2026-10-19", "current_finish": "2026-10-21", "kind": "task"},
        {"name": "Metal stud framing floor 2", "current_start": "2026-10-12", "current_finish": "2026-10-23"},
        {"name": "Riser install floors 1-4", "current_start": "2026-11-20", "current_finish": "2026-12-01"},
        {"name": "Fixtures", "current_start": "2026-10-01", "current_finish": "2026-10-10", "actual_finish": "2026-10-09"},
        {"name": "Project", "kind": "summary", "current_start": "2026-01-01", "current_finish": "2027-03-01"},
    ]
    CHIPS = [Chip("pour_slab", "pour slab"), Chip("interior_framing", "interior framing"),
             Chip("plmb_riser_install", "riser install"), Chip("fixtures", "fixtures"), Chip("other", "other")]

    def test_a_chip_matches_only_when_its_words_are_in_the_activity_name(self):
        got = hints_for(self.PLAN, "2026-10-20", self.CHIPS)
        self.assertEqual(sorted(got), ["pour_slab"])
        self.assertEqual(got["pour_slab"], "scheduled: Pour slab - floor 2 (Oct 19–Oct 21)")

    def test_finished_future_and_summary_rows_do_not_count(self):
        self.assertNotIn("fixtures", hints_for(self.PLAN, "2026-10-09", self.CHIPS))          # actually finished
        self.assertNotIn("plmb_riser_install", hints_for(self.PLAN, "2026-10-20", self.CHIPS))  # a month away
        self.assertIn("plmb_riser_install", hints_for(self.PLAN, "2026-11-18", self.CHIPS))   # within 3 days of its start

    def test_garbage_is_not_a_hint(self):
        self.assertEqual(hints_for(None, "2026-10-20", self.CHIPS), {})
        self.assertEqual(hints_for(self.PLAN, "not a date", self.CHIPS), {})
        self.assertEqual(hints_for([None, 5, {"name": "x"}], "2026-10-20", self.CHIPS), {})


if __name__ == "__main__":
    unittest.main()
