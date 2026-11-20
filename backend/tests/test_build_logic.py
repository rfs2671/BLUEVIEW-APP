"""The build logic: a schedule made from the scope and the order construction
has to follow, and the filed logs held against it (lib/build_logic.py).

The crew rows are SYNTHETIC, shaped like the rows of 588 Boyland's daily logs.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import build_logic as B  # noqa: E402
from lib import progress_stages as S  # noqa: E402

MON = date(2026, 10, 5)            # a Monday; Oct 12 2026 is a federal holiday


def row(d, trade, work, where="1st Floor", company="Co"):
    return {"date": d, "company": company, "trade": trade, "work": work, "where": where,
            "floors": S.floors_of_text(where), "workers": 4, "photos": [], "work_trades": []}


def days(first, n):
    """`n` consecutive weekdays from `first`."""
    out, d = [], first
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def hard_before(scope, node):
    return {p for p, ln in B.network(scope)[node].preds if ln.hard}


def by_id(p):
    return {r["id"]: r for r in p["nodes"]}


CIP = B.Scope(floors=3, system="cast_in_place")
CFS = B.Scope(floors=3, system="cfs")


class TheRules(unittest.TestCase):
    def test_the_walls_cannot_close_before_what_the_operator_named(self):
        # "can't close sheetrock before insulation inspected, all vent lines connected to
        #  fans, AC drain lines connected to drain"
        need = hard_before(CIP, "drywall@2")
        for gate in ("gate_insulation@2", "check_exhaust@2", "check_condensate@2", "gate_electrical@2",
                     "gate_plumbing@2", "gate_sprinkler@2", "gate_firestop@2"):
            self.assertIn(gate, need)

    def test_the_insulation_is_inspected_after_it_is_installed_and_installed_after_the_rough_inspections(self):
        self.assertEqual(hard_before(CIP, "gate_insulation@1"), {"insulation@1"})
        self.assertLessEqual({"gate_plumbing@1", "gate_electrical@1", "windows@1"}, hard_before(CIP, "insulation@1"))

    def test_sleeves_and_rebar_are_both_in_before_the_pour(self):
        self.assertEqual(hard_before(CIP, "gate_pour@1"), {"slab_rebar@1", "sleeves@1"})
        self.assertIn("gate_pour@1", hard_before(CIP, "pour_slab@1"))

    def test_framing_starts_on_a_floor_once_its_forms_are_out(self):
        p = by_id(B.plan(CIP))
        self.assertEqual(hard_before(CIP, "framing@1"), {"structure@1"})
        self.assertEqual(p["structure@1"]["driver"], "strip@1")
        self.assertEqual(p["framing@1"]["start"], p["strip@1"]["finish"])
        self.assertEqual(p["strip@1"]["start"], p["pour_slab@1"]["finish"] + CIP.strip_days)

    def test_leaving_the_forms_in_longer_moves_the_framing_and_not_the_structure(self):
        a, b = by_id(B.plan(CIP)), by_id(B.plan(B.Scope(floors=3, system="cast_in_place", strip_days=9)))
        self.assertEqual(b["framing@1"]["start"] - a["framing@1"]["start"], 4)
        self.assertEqual(b["verticals@3"]["start"], a["verticals@3"]["start"])

    def test_the_cycle_is_the_days_from_one_floor_to_the_next(self):
        for scope, first in ((B.Scope(floors=3, system="cast_in_place", cycle_days=5), "verticals"),
                             (B.Scope(floors=3, system="cfs", cycle_days=9), "cfs_walls"),
                             (B.Scope(floors=3, system="block_plank", cycle_days=6), "cmu_walls")):
            p = by_id(B.plan(scope))
            self.assertAlmostEqual(p[f"{first}@2"]["start"] - p[f"{first}@1"]["start"], scope.cycle_days)
            self.assertAlmostEqual(p[f"{first}@3"]["start"] - p[f"{first}@2"]["start"], scope.cycle_days)

    def test_a_building_without_sprinklers_or_gas_has_none_of_their_steps(self):
        plain = B.network(B.Scope(floors=2, system="cfs", sprinkler=False))
        self.assertFalse([k for k in plain if "sprinkler" in k or "gas" in k])
        gas = B.network(B.Scope(floors=2, system="cfs", gas=True))
        self.assertIn("gate_gas@1", {p for p, ln in gas["drywall@1"].preds if ln.hard})

    def test_every_system_builds_with_no_rule_contradicting_another(self):
        for system in B.SYSTEMS:
            p = B.plan(B.Scope(floors=5, system=system, elevator=True, cellar=True, piles=True, gas=True,
                               bulkhead=True))
            self.assertEqual((p["chain"][0], p["chain"][-1]), ("site_prep", "tco"))
            self.assertLessEqual(p["fastest"], p["days"])

    def test_every_hard_rule_says_why_in_both_languages_or_is_a_plain_roll_up(self):
        for ln in B.LINKS:
            self.assertEqual(bool(ln.why), bool(ln.es), (ln.a, ln.b))
            if ln.b not in ("punch", "gate_final", "tco", "gate_elevator"):
                self.assertTrue(ln.why, (ln.a, ln.b))
        for a in B.ACTS:
            self.assertTrue(a.label and a.es, a.key)

    def test_an_unknown_system_or_no_floors_is_refused(self):
        with self.assertRaises(ValueError):
            B.network(B.Scope(floors=3, system="timber"))
        with self.assertRaises(ValueError):
            B.network(B.Scope(floors=0))

    def test_a_loop_in_the_rules_is_named_not_hung_on(self):
        edges = {"a": [("b", B._CREW)], "b": [("a", B._CREW)], "c": []}
        with self.assertRaisesRegex(ValueError, "a, b"):
            B._order(edges)


class ThePlan(unittest.TestCase):
    def test_the_finish_is_the_end_of_its_chain_and_the_chain_has_no_slack(self):
        p = B.plan(CIP)
        n = by_id(p)
        self.assertEqual(n["tco"]["finish"], p["days"])
        for a, b in zip(p["chain"], p["chain"][1:]):
            self.assertEqual(n[b]["driver"], a)
        self.assertTrue(all(n[k]["critical"] for k in p["chain"]))

    def test_one_crew_takes_the_floors_in_turn_and_a_second_crew_is_priced(self):
        # 24 apartments a floor: a floor's taping takes far longer than the structure's cycle
        big = B.Scope(floors=4, system="cfs", units_per_floor=24)
        p = B.plan(big)
        n = by_id(p)
        self.assertGreaterEqual(n["taping@2"]["start"], n["taping@1"]["finish"])
        self.assertIn("taping", [g["trade"] for g in p["second_crew"]])
        two = B.plan(B.Scope(floors=4, system="cfs", units_per_floor=24, crews={"taping": 2}))
        saved = next(g["days_saved"] for g in p["second_crew"] if g["trade"] == "taping")
        self.assertAlmostEqual(p["days"] - two["days"], saved)

    def test_a_given_duration_replaces_the_table(self):
        slow = by_id(B.plan(B.Scope(floors=3, system="cfs", days={"taping": 11})))
        self.assertEqual(slow["taping@1"]["days"], 11)

    def test_dates_skip_weekends_holidays_and_the_days_the_site_is_shut(self):
        got = B.workdays_from(date(2026, 10, 9), 3, closed=[date(2026, 10, 13)])      # Fri; Mon is Columbus Day
        self.assertEqual(got, [date(2026, 10, 9), date(2026, 10, 14), date(2026, 10, 15)])
        p = B.on_calendar(B.plan(CFS), date(2027, 1, 4))
        first = by_id(p)["site_prep"]
        self.assertEqual((first["start_date"], first["finish_date"]), (date(2027, 1, 4), date(2027, 1, 6)))
        self.assertEqual(p["finish_date"], max(r["finish_date"] for r in p["nodes"]))


def cfs_job():
    """A 3-storey steel-stud job: structure up a floor a week, then partitions and rough-ins on floor 1."""
    rows = [row(d, "Concrete / Cement", "pour slab") for d in days(date(2026, 8, 31), 2)]
    rows += [row(d, "Framers", "framing (layout, track and studs)") for d in days(MON, 5)]
    rows += [row(d, "Framers", "framing (layout, track and studs)", "2nd Floor") for d in days(date(2026, 10, 13), 4)]
    rows += [row(d, "Framers", "interior framing") for d in days(date(2026, 10, 13), 4)]
    rows += [row(d, "Framers", "framing (layout, track and studs)", "3rd Floor") for d in days(date(2026, 10, 19), 5)]
    return rows


class TheLogs(unittest.TestCase):
    END = date(2026, 11, 20)

    def states(self, scope, rows, end=None):
        return {n["id"]: n for n in B.status(scope, rows, end or self.END)["nodes"]}

    def test_on_steel_stud_framing_is_structure_until_it_reaches_the_floor_above(self):
        got = B.read_logs(CFS, cfs_job(), self.END)
        self.assertEqual((got["cfs_walls@1"]["first"], got["cfs_walls@1"]["last"]), (MON, date(2026, 10, 9)))
        self.assertEqual(got["framing@1"]["first"], date(2026, 10, 13))
        self.assertNotIn("framing@2", got)

    def test_work_logged_on_a_floor_proves_what_it_stands_on_is_behind_it(self):
        n = self.states(CFS, cfs_job())
        for k in ("excavation", "foundations", "slab_on_grade", "cfs_walls@1", "cfs_deck@1", "cfs_deck@2",
                  "structure@1"):
            self.assertEqual(n[k]["state"], "done", k)
        self.assertNotEqual(n["cfs_deck@3"]["state"], "done")
        self.assertEqual(B.status(CFS, cfs_job(), self.END)["early"], [])

    def test_the_measured_cycle_is_read_from_when_the_structure_first_reaches_each_floor(self):
        m = B.measured_cycle(CFS, cfs_job(), self.END)
        self.assertEqual(m["reached"], {1: MON, 2: date(2026, 10, 13), 3: date(2026, 10, 19)})
        self.assertEqual([s["days"] for s in m["steps"]], [5, 4])
        self.assertEqual(m["cycle"], 4.5)

    def board(self, extra=()):
        rows = cfs_job() + [row(d, "Drywall", "sheet rock") for d in days(date(2026, 11, 9), 4)]
        return rows + list(extra)

    def test_sheetrock_with_no_sprinkler_on_any_log_is_a_finding_and_names_the_floor(self):
        st = B.status(CFS, self.board(), self.END)
        e = [x for x in st["early"] if x["before"] == "sprinkler_rough"]
        self.assertEqual([(x["node"], x["kind"], x["floors"], x["date"]) for x in e],
                         [("drywall", "never", [1], date(2026, 11, 9))])
        dry = B.Scope(floors=3, system="cfs", sprinkler=False)
        self.assertFalse([x for x in B.status(dry, self.board(), self.END)["early"] if "sprinkler" in x["before"]])

    def test_sheetrock_while_the_electrician_is_still_roughing_in_is_a_finding(self):
        wire = [row(d, "Electrician", "pull wire") for d in days(date(2026, 11, 2), 10)]
        st = B.status(CFS, self.board(wire), self.END)
        e = next(x for x in st["early"] if x["before"] == "electrical_rough")
        self.assertEqual((e["kind"], e["last"]), ("still_open", date(2026, 11, 13)))

    def test_a_rough_in_that_stopped_before_the_board_started_is_not(self):
        wire = [row(d, "Electrician", "pull wire") for d in days(date(2026, 10, 26), 5)]
        st = B.status(CFS, self.board(wire), self.END)
        self.assertFalse([x for x in st["early"] if x["before"] == "electrical_rough"])

    def test_the_usual_order_is_a_choice_and_breaking_it_is_not_a_finding(self):
        # tile before primer: the usual order, not a rule. Tile before TAPING would be one.
        tape = [row(d, "Tapers", "taping") for d in days(date(2026, 11, 2), 3)]
        tile = [row(d, "Tile", "tile") for d in days(date(2026, 11, 9), 3)]
        st = B.status(CFS, cfs_job() + tape + tile, self.END)
        self.assertFalse([x for x in st["early"] if x["node"] == "tile"])
        st = B.status(CFS, cfs_job() + tile, self.END)
        self.assertEqual([x["before"] for x in st["early"] if x["node"] == "tile"], ["taping"])

    def test_one_stray_mention_is_not_a_start(self):
        stray = [row(date(2026, 10, 14), "Framers", "interior framing, sheet rock")]
        got = B.read_logs(CFS, self.board(stray), self.END)["drywall@1"]
        self.assertEqual((got["first"], got["start"]), (date(2026, 10, 14), date(2026, 11, 9)))
        only = B.status(CFS, cfs_job() + stray, self.END)
        self.assertFalse([x for x in only["early"] if x["node"] == "drywall"])

    def test_a_logged_test_passes_its_gate_and_the_unlogged_ones_are_listed_once(self):
        test = [row(date(2026, 11, 4), "Plumber", "domestic water rough, hydrostatic test")]
        st = B.status(CFS, self.board(test), self.END)
        self.assertEqual({n["id"]: n for n in st["nodes"]}["gate_plumbing@1"]["state"], "done")
        gates = {m["gate"] for m in st["not_on_record"] if m["node"] == "drywall"}
        self.assertNotIn("gate_plumbing", gates)
        self.assertLessEqual({"gate_electrical", "gate_insulation", "check_exhaust", "check_condensate",
                              "gate_firestop", "gate_sprinkler"}, gates)

    def test_fixtures_before_the_walls_are_taped_are_rough_in(self):
        tubs = [row(d, "Plumber", "fixtures") for d in days(date(2026, 10, 26), 3)]
        got = B.read_logs(CFS, cfs_job() + tubs, self.END)
        self.assertIn("plumbing_rough@1", got)
        self.assertNotIn("plumbing_finish@1", got)
        tape = [row(d, "Tapers", "taping") for d in days(date(2026, 10, 19), 3)]
        self.assertIn("plumbing_finish@1", B.read_logs(CFS, cfs_job() + tape + tubs, self.END))

    def test_under_slab_work_is_not_a_floors_rough_in(self):
        got = B.read_logs(CFS, [row(MON, "Electrician", "Electric piping under slab")], self.END)
        self.assertEqual(list(got), ["underground_plumbing"])

    def test_a_trade_that_came_late_to_a_ready_floor_is_counted_in_worked_site_days(self):
        late = [row(d, "Plumber", "MEP rough-in") for d in days(date(2026, 10, 26), 3)]
        w = [x for x in B.status(CFS, cfs_job() + late, self.END)["waited"] if x["key"] == "plumbing_rough"]
        # partitions started Oct 13; the site was worked Oct 14, 15, 16, 19-23 before the plumber came
        self.assertEqual([(x["floor"], x["ready"], x["started"], x["days"]) for x in w],
                         [(1, date(2026, 10, 13), date(2026, 10, 26), 8)])

    def test_rows_after_the_day_asked_about_are_not_read(self):
        self.assertNotIn("drywall@1", B.read_logs(CFS, self.board(), date(2026, 11, 6)))

    def test_work_under_way_cannot_finish_before_what_it_depends_on(self):
        st = B.status(CFS, self.board(), self.END)
        n = {x["id"]: x for x in st["nodes"]}
        self.assertEqual(n["drywall@1"]["state"], "active")
        self.assertGreater(n["drywall@1"]["forecast_finish"], n["gate_sprinkler@1"]["forecast_finish"])
        self.assertGreater(st["finish_date"], self.END)
        self.assertEqual(st["chain"][-1], "tco")
        dry = B.status(B.Scope(floors=3, system="cfs", sprinkler=False), self.board(), self.END)
        self.assertLessEqual(dry["finish_date"], st["finish_date"])

    def test_what_can_start_today_is_only_what_has_nothing_outstanding(self):
        st = B.status(CFS, cfs_job(), self.END)
        self.assertIn("windows@1", st["open_now"])
        self.assertNotIn("drywall@1", st["open_now"])
        self.assertNotIn("windows@3", st["open_now"])        # the third floor's deck is not proven on

    def test_the_findings_read_in_both_languages_and_name_no_cause(self):
        wire = [row(d, "Electrician", "pull wire") for d in days(date(2026, 11, 2), 10)]
        late = [row(d, "Plumber", "MEP rough-in") for d in days(date(2026, 10, 26), 3)]
        st = B.status(CFS, self.board(wire + late), self.END)
        en, es = B.findings(st), B.findings(st, es=True)
        self.assertTrue(en["early"] and en["not_on_record"] and en["waited"])
        self.assertEqual({k: len(v) for k, v in en.items()}, {k: len(v) for k, v in es.items()})
        self.assertIn("Sheetrock (close walls & ceilings) (floor 1) started Nov 9; no log shows any: "
                      "Sprinkler rough-in.", " ".join(en["early"]))
        self.assertIn("Tablaroca", " ".join(es["early"]))
        for text in en["early"] + en["waited"] + en["not_on_record"]:
            for word in ("because", "due to", "delay", "late", "fault"):
                self.assertNotIn(word, text.lower(), text)

    def test_nothing_filed_is_a_plan_from_today_not_an_error(self):
        st = B.status(CFS, [], self.END)
        self.assertEqual((st["done"], st["early"], st["waited"]), (0, [], []))
        self.assertAlmostEqual(st["days_left"], B.plan(CFS)["days"])


if __name__ == "__main__":
    unittest.main()
