"""A crew's own history ranks tomorrow's activity chips -- and changes nothing else:
the same chips, nothing selected, nothing hidden, "Other" last."""

import unittest

from app.scheduling import crew_history as CH
from app.scheduling.sequence_ranking import rank_activities
from app.scheduling.sequence_rules_v1 import build_sequence_rules_v1, successors_by_id

SUCC = successors_by_id(build_sequence_rules_v1())


def rank(trade="Plumber", prior=()):
    return rank_activities(project_id="p", prior_activity_ids=list(prior), trade=trade)


def day(d, *ids):
    return (d, list(ids))


class CrewDays(unittest.TestCase):

    def logs(self):
        def lg(d, *rows):
            return {"date": d, "data": {"activities": [dict(r) for r in rows]}}
        pl = {"trade": "Plumber", "activity_ids": ["mep_rough_in"]}
        el = {"trade": "Electrician", "activity_ids": ["elec_pull_wire"]}
        return [lg("2026-10-14", pl, el), lg("2026-10-13", el), lg("2026-10-12", pl), lg("2026-10-15", pl)]

    def test_only_this_crew_only_before_today_newest_first(self):
        got = CH.crew_days(self.logs(), lambda r: r.get("trade") == "Plumber", "2026-10-15")
        self.assertEqual(got, [("2026-10-14", ["mep_rough_in"]), ("2026-10-12", ["mep_rough_in"])])

    def test_garbage_is_skipped_not_raised(self):
        junk = [None, {"date": "2026-10-01"}, {"date": "2026-10-02", "data": {"activities": "x"}},
                {"date": "2026-10-03", "data": {"activities": [None, 5, {"activity_ids": ["a"]}]}}]
        self.assertEqual(CH.crew_days(junk, lambda r: True, "2026-11-01"), [("2026-10-03", ["a"])])
        self.assertEqual(CH.crew_days(junk, lambda r: 1 / 0, "2026-11-01"), [])

    def test_the_limit_keeps_the_newest(self):
        logs = [{"date": f"2026-10-{d:02d}", "data": {"activities": [{"activity_ids": ["a"]}]}} for d in range(1, 21)]
        got = CH.crew_days(logs, lambda r: True, "2026-10-30", limit=3)
        self.assertEqual([d for d, _ in got], ["2026-10-20", "2026-10-19", "2026-10-18"])


class Runs(unittest.TestCase):

    def test_current_and_completed_runs(self):
        days = [day("d9", "a"), day("d8", "a"), day("d7", "a"), day("d6", "b"), day("d5", "a"), day("d4", "a"),
                day("d3", "b"), day("d2", "a")]
        cur, done = CH.runs_of(days, "a")
        self.assertEqual((cur, done), (3, [2]))          # the oldest run may have begun earlier: not counted

    def test_an_activity_not_logged_last_time_has_no_current_run(self):
        self.assertEqual(CH.runs_of([day("d2", "b"), day("d1", "a")], "a")[0], 0)


class Personalize(unittest.TestCase):

    def test_no_history_changes_nothing(self):
        r = rank()
        self.assertEqual(CH.personalize(r, [], SUCC).model_dump(), r.model_dump())
        self.assertEqual(CH.personalize(r, None, None).model_dump(), r.model_dump())

    def test_what_the_crew_is_doing_comes_first_with_its_reason(self):
        out = CH.personalize(rank(), [day("2026-10-14", "mep_rough_in"), day("2026-10-13", "mep_rough_in"),
                                      day("2026-10-12", "mep_rough_in")], SUCC)
        first = out.chips[0]
        self.assertEqual((first.id, first.band), ("mep_rough_in", "suggested"))
        self.assertIn("continuing", first.reason)
        self.assertIn("3 days running", first.reason)

    def test_the_same_chips_nothing_selected_nothing_hidden_other_last(self):
        base = rank()
        out = CH.personalize(base, [day("2026-10-14", "mep_rough_in"), day("2026-10-13", "plmb_sanitary_rough")], SUCC)
        self.assertEqual(sorted(c.id for c in out.chips), sorted(c.id for c in base.chips))
        self.assertTrue(all(c.selected is False for c in out.chips))
        self.assertEqual(out.chips[-1].band, "other")
        self.assertEqual([c.rank for c in out.chips], list(range(len(out.chips))))
        self.assertEqual(len([c for c in out.chips if c.band == "other"]), 1)

    def test_a_crew_that_moved_on_before_is_offered_the_same_move_again(self):
        # earlier on this project: sanitary rough, then vent rough; now sanitary rough again
        days = [day("d4", "plmb_sanitary_rough"), day("d3", "plmb_sanitary_rough"), day("d2", "plmb_vent_rough"),
                day("d1", "plmb_sanitary_rough")]
        out = CH.personalize(rank(), days, SUCC)
        ids = [c.id for c in out.chips[:4]]
        self.assertIn("plmb_vent_rough", ids)
        vent = next(c for c in out.chips if c.id == "plmb_vent_rough")
        self.assertIn("moved from sanitary rough to vent rough before", vent.reason)

    def test_a_crew_back_after_a_week_is_ranked_from_where_it_left_off(self):
        # the operator's case: last week's work was under-slab MEP; today the plumbers
        # are back -- the project's latest day says nothing about them
        from app.scheduling.trade_sequence import stages_for
        out = CH.personalize(rank(), [day("2026-10-06", "under_slab_mep")], SUCC, stages=stages_for(["Plumbing"]))
        ids = [c.id for c in out.chips[:5]]
        self.assertIn("mep_rough_in", ids)
        self.assertIn("plmb_sanitary_rough", ids)
        reason = next(c.reason for c in out.chips if c.id == "mep_rough_in")
        self.assertIn("next stage after under-slab MEP", reason)
        self.assertIn("last on site 2026-10-06", reason)

    def test_the_rest_of_the_current_stage_is_offered_as_concurrent_work(self):
        from app.scheduling.trade_sequence import stages_for
        out = CH.personalize(rank(), [day("d1", "mep_rough_in")], SUCC, stages=stages_for(["Plumbing"]))
        self.assertIn("same stage as MEP rough-in", next(c.reason for c in out.chips if c.id == "plmb_sanitary_rough"))
        self.assertIn("next stage after MEP rough-in", next(c.reason for c in out.chips if c.id == "plmb_domestic_water_rough"))

    def test_finished_early_stages_do_not_crowd_out_the_next_stage(self):
        # The real 588 concrete day 2026-08-26: six activities logged the day
        # before, from site prep up to foundation walls. The piles and shoring are
        # long done; vapour barrier, rebar and formwork are what is coming.
        from app.scheduling.trade_sequence import stages_for
        prev = ["site_prep", "shoring", "piles", "footings", "foundation_walls", "grade_beams"]
        stages = stages_for(["Foundation / Concrete", "Excavation", "Shoring / underpinning", "Piles / caissons"])
        out = CH.personalize(rank("Concrete / Cement"), [day("d1", *prev)], SUCC, stages=stages)
        top = [c.id for c in out.chips[:6]]
        self.assertIn("vapour_barrier", top)
        self.assertIn("foundation_walls", top)          # still being worked
        self.assertNotIn("piles", top)
        self.assertNotIn("shoring", top)

    def test_work_in_the_crews_current_stage_is_never_treated_as_finished(self):
        from app.scheduling.trade_sequence import stages_for
        out = CH.personalize(rank(), [day("d1", "mep_rough_in", "plmb_sanitary_rough")], SUCC,
                             stages=stages_for(["Plumbing"]))
        top = [c.id for c in out.chips[:3]]
        self.assertIn("mep_rough_in", top)
        self.assertIn("plmb_sanitary_rough", top)

    def test_stages_can_be_switched_off(self):
        from app.scheduling.trade_sequence import stages_for
        on = CH.personalize(rank(), [day("d1", "under_slab_mep")], SUCC, stages=stages_for(["Plumbing"]))
        off = CH.personalize(rank(), [day("d1", "under_slab_mep")], SUCC, stages=stages_for(["Plumbing"]), use_order=False)
        self.assertIn("mep_rough_in", [c.id for c in on.chips[:4]])
        self.assertNotIn("mep_rough_in", [c.id for c in off.chips[:2]])

    def test_a_schedule_hint_lifts_a_chip_even_for_a_crew_with_no_history(self):
        out = CH.personalize(rank(), [], SUCC, scheduled={"plmb_riser_install": "scheduled: Riser install (Oct 19–Oct 23)"})
        self.assertEqual(out.chips[0].id, "plmb_riser_install")
        self.assertEqual(out.chips[0].reason, "scheduled: Riser install (Oct 19–Oct 23)")
        self.assertEqual(out.chips[-1].band, "other")

    def test_the_rule_tables_successors_still_count(self):
        graph = build_sequence_rules_v1()
        out = CH.personalize(rank("Carpenter"), [day("d1", "interior_framing")], SUCC,
                             {n.id: getattr(n, "scope", n.id) for n in graph.nodes})
        top = {c.id: c.reason for c in out.chips[:4]}
        scope = next(n.scope for n in graph.nodes if n.id == "interior_framing")
        self.assertEqual(top.get("blocking"), f"next after {scope}")

    def test_a_run_as_long_as_usual_boosts_what_comes_next(self):
        days = [day("d9", "a1"), day("d8", "a1"), day("d7", "a1"), day("d6", "b"), day("d5", "a1"), day("d4", "a1"),
                day("d3", "a1"), day("d2", "b")]
        self.assertEqual(CH.runs_of(days, "a1"), (3, [3]))

    def test_an_unknown_activity_in_the_history_is_ignored_not_invented(self):
        base = rank()
        out = CH.personalize(base, [day("d1", "no_such_activity", "mep_rough_in")], SUCC)
        self.assertNotIn("no_such_activity", [c.id for c in out.chips])
        self.assertEqual(out.chips[0].id, "mep_rough_in")

    def test_bad_input_never_raises(self):
        r = rank()
        self.assertEqual(CH.personalize(r, [("d", [None, 5, {}])], SUCC).model_dump()["chips"].__len__(), len(r.chips))
        self.assertEqual(CH.personalize(r, [day("d1", "mep_rough_in")], {"x": None}).chips[-1].band, "other")


if __name__ == "__main__":
    unittest.main()


class TheBacktest(unittest.TestCase):

    def logs(self):
        def lg(d, *rows):
            return {"date": d, "data": {"activities": [dict(r) for r in rows]}}
        pl = {"trade": "Plumber", "activity_ids": ["plmb_riser_install"]}     # late in the trade's catalogue
        el = {"trade": "Electrician", "activity_ids": ["elec_pull_wire"]}
        # the plumbers come every OTHER day: on the days between, the project's
        # latest day holds no plumbing, so the old ranking has nothing to go on
        return [lg(f"2026-10-{d:02d}", pl, el) if d % 2 else lg(f"2026-10-{d:02d}", el) for d in range(1, 10)]

    def test_a_crew_that_keeps_doing_the_same_work_is_predicted_by_its_own_history(self):
        from app.scheduling.chip_backtest import backtest
        res = backtest(self.logs(), top=4)
        o = res["overall"]
        self.assertGreater(o["personalized_hits"], o["baseline_hits"])
        plumb = res["by_trade"]["Plumber"]
        self.assertEqual(plumb["crew_days"], 5)
        self.assertEqual(plumb["personalized_hits"], 4)          # every plumbing day but the first (no history)
        self.assertLess(plumb["baseline_hits"], plumb["personalized_hits"])
        self.assertGreaterEqual(o["personalized_hits"], o["baseline_hits"])

    def test_the_first_day_has_no_history_so_both_rank_alike(self):
        from app.scheduling.chip_backtest import backtest
        first = [r for r in backtest(self.logs())["rows"] if r["date"] == "2026-10-01"]
        self.assertTrue(first and all(not r["had_history"] and r["baseline_top"] == r["personalized_top"] for r in first))

    def test_garbage_logs_are_skipped(self):
        from app.scheduling.chip_backtest import backtest
        self.assertEqual(backtest([None, {}, {"date": "2026-10-01", "data": 5}])["overall"]["crew_days"], 0)


class TheBacktestDiagnostics(unittest.TestCase):

    def test_each_logged_activity_is_continuing_or_new_with_its_positions(self):
        from app.scheduling.chip_backtest import backtest, hit_rates
        pl = lambda *ids: {"trade": "Plumber", "activity_ids": list(ids)}  # noqa: E731
        logs = [{"date": f"2026-10-0{d}", "data": {"activities": [pl(*ids)]}} for d, ids in
                ((1, ["plmb_sanitary_rough"]), (2, ["plmb_sanitary_rough"]), (3, ["plmb_vent_rough"]))]
        res = backtest(logs, top=4)
        ev = res["events"]
        self.assertEqual([e["kind"] for e in ev], ["new", "continuing", "new"])
        self.assertTrue(all(set(e) >= {"baseline_pos", "personalized_pos", "no_order_pos", "previous"} for e in ev))
        h = hit_rates(ev)
        self.assertEqual(h["n"], 3)
        self.assertEqual(hit_rates(ev, "continuing")["n"], 1)
        self.assertGreaterEqual(h["personalized_pos@8"], h["personalized_pos@4"])


class LearningWhatComesNext(unittest.TestCase):
    """The history ranking could not predict an activity a crew had never logged
    on the job (48% of NEW activities in the first four chips on real data, with
    or without it). Other projects' filed logs can: after A, crews added B."""

    def project(self, seq):
        def pl(*ids):
            return {"trade": "Plumber", "activity_ids": list(ids)}
        return [{"date": f"2026-0{m}-{d:02d}", "data": {"activities": [pl(*ids)]}} for m, d, ids in seq]

    def peers(self):
        # on three other jobs the plumbers went from sanitary rough to riser install (far down the catalogue)
        seq = [(5, 1, ["plmb_sanitary_rough"]), (5, 2, ["plmb_sanitary_rough"]), (5, 3, ["plmb_riser_install"])]
        return [self.project(seq) for _ in range(3)]

    def test_counts_learn_only_added_activities(self):
        from app.scheduling.chip_backtest import Transitions
        m = Transitions()
        m.learn(self.peers()[0], {"plmb_sanitary_rough", "plmb_riser_install"})
        tk = "Plumbing"
        self.assertEqual(m.after[tk]["plmb_sanitary_rough"]["plmb_riser_install"], 1)
        self.assertEqual(m.total[tk]["plmb_sanitary_rough"], 2)
        self.assertEqual(m.scores(tk, ["plmb_sanitary_rough"]), {"plmb_riser_install": 0.5})

    def test_what_a_crew_has_never_done_here_is_predicted_from_other_jobs(self):
        from app.scheduling.chip_backtest import backtest, hit_rates
        mine = self.project([(6, 1, ["plmb_sanitary_rough"]), (6, 2, ["plmb_riser_install"])])
        with_peers = backtest(mine, top=4, other_projects=self.peers())
        alone = backtest(mine, top=4)
        h1, h0 = hit_rates(with_peers["events"], "new"), hit_rates(alone["events"], "new")
        self.assertEqual(h1["n"], 2)                     # both days are "new" for the crew
        self.assertGreater(h1["learned_pos@4"], h0["learned_pos@4"])
        self.assertGreater(h1["learned_pos@4"], h1["baseline_pos@4"])

    def test_the_learned_ranking_is_the_same_chips_other_last_nothing_selected(self):
        from app.scheduling.chip_backtest import Transitions, with_learned
        m = Transitions()
        for p in self.peers():
            m.learn(p, {"plmb_sanitary_rough", "plmb_riser_install"})
        base = rank()
        out = with_learned(base, ["plmb_sanitary_rough"], "Plumbing", m, {})
        self.assertEqual(sorted(c.id for c in out.chips), sorted(c.id for c in base.chips))
        self.assertEqual(out.chips[0].id, "plmb_riser_install")
        self.assertEqual(out.chips[-1].band, "other")
        self.assertTrue(all(c.selected is False for c in out.chips))
        self.assertEqual(with_learned(base, ["plmb_sanitary_rough"], "Plumbing", Transitions(), {}).model_dump(), base.model_dump())

    def test_the_model_keeps_counts_only(self):
        from app.scheduling.chip_backtest import Transitions
        m = Transitions()
        m.learn([{"date": "2026-01-01", "company_id": "SECRET-CO", "project_id": "SECRET-PROJ",
                  "data": {"activities": [{"trade": "Plumber", "activity_ids": ["plmb_sanitary_rough"], "company": "Acme"}]}}],
                {"plmb_sanitary_rough"})
        import re
        self.assertIsNone(re.search(r"SECRET|Acme", repr(dict(m.after)) + repr(dict(m.total))))
