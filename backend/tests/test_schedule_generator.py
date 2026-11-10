"""The schedule generator (lib/schedule_generator.py): a remaining-work ESTIMATE
built from a building model, a state and labelled assumptions.

EVERY FIXTURE HERE IS SYNTHETIC: a made-up two-floor CFS building, made-up
check-in summaries and a made-up inspection record. No real project data is
read (the 588 data stays outside the repo; backend/scripts/intel_588_schedule.py
reads it locally).

What is pinned:
  * CPM: forward/backward pass, total float, driving path, calendars (weekends,
    holidays, weather capacity), SS/FF links, cycle detection;
  * scenario ordering: fast <= normal <= conservative, for the finish and for
    every activity;
  * nothing starts before a true prerequisite finishes;
  * inspections are their own gate activities and gate the work they cover; a
    passed plumbing ROUGH is never the plumbing FINAL;
  * an estimate never becomes a baseline, a schedule-file date or a fact item;
  * the network comes from the building (no elevator, no gas, no sprinkler ->
    no such activities);
  * crew SIZE is measured with its sample; every assumption carries a tag.
"""

from __future__ import annotations

import copy
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import evidence as E  # noqa: E402
from lib import forecast as F  # noqa: E402
from lib import schedule_generator as G  # noqa: E402

DATA_DATE = date(2030, 3, 4)  # a Monday; SYNTHETIC


def synthetic_building(*, gas=True, sprinkler=True, elevators=0, mezz=False):
    """SYNTHETIC two-floor CFS walk-up in the drawings lane's building.json shape."""
    floor = {"slab_gross_sf": 2000.0, "units": 2, "baths": 2, "kitchenettes": 2, "apartment_net_sf": [600, 600],
             "wall_LF_filed": {"W1": 60.0, "W2": 120.0, "P1": 40.0, "P2": 60.0, "P3": 50.0, "P4": 20.0}}
    dq = {"FIRST": dict(floor), "SECOND": copy.deepcopy(floor),
          "ROOF": {"roof_gross_sf": "2000 footprint", "bulkhead_gross_sf": "100 (old) / 150 (new)"},
          "BUILDING": {"units": 4, "baths": 4, "ptacs": 8, "stairs": 1, "elevators": elevators,
                       "door_window_totals_filed": {"A": 10, "B": 6, "D1": 1, "W1": 12}}}
    if mezz:
        dq["MEZZANINE"] = {"slab_gross_sf": 600.0, "units": 0, "baths": 1, "kitchenettes": 0,
                           "wall_LF_filed": dict(floor["wall_LF_filed"])}
    return {
        "derived_quantities_per_floor": {"value": dq},
        "fire_protection_electrical_vertical": {
            "sprinkler": {"value": "Whole-building wet sprinkler system NFPA 13R" if sprinkler else "none"},
            "standpipe": {"value": "None required"}},
        "plumbing": {"gas": {"value": "Gas meter at the first floor, riser G-1" if gas else "all electric"}},
        "site_safety_soe": {"sewer_connection_hold": {"value": "Roof detention (blue roof) 400 cf"}},
        "project_type": {"classification": {"value": "NEW BUILDING (synthetic)"}},
    }


def _summary(company, avg, peak, days, period="2030-02-17..2030-03-01"):
    return {"id": f"S-{company}", "type": "checkin_aggregate", "origin": "synthetic", "company": company,
            "fields": {"kind": "sub_period_summary", "avg_workers": avg, "peak": peak, "days_on_site": days,
                       "period": period}}


def synthetic_records():
    """SYNTHETIC roster, check-in period summaries and log phrases."""
    roster = [("Frame Co", "Framers"), ("Volt Co", "Electrician"), ("Pipe Co", "Plumber"), ("Air Co", "HVAC / Mechanical"),
              ("Skin Co", "Stucco"), ("Top Co", "Roofing"), ("Glass Co", "Window Installation"),
              ("Fluff Co", "Insulation"), ("Main Co", "Water Main"), ("Rack Co", "Scaffolding"),
              ("Spray Co", "Fire Protection")]
    out = [{"id": f"R-{c}", "type": "project_meta", "origin": "synthetic", "company": c, "trade": t,
            "fields": {"kind": "roster_row_trade_assignment"}} for c, t in roster]
    out += [_summary("Frame Co", 8.0, 11, 10), _summary("Volt Co", 5.0, 7, 9), _summary("Pipe Co", 4.0, 5, 10),
            _summary("Air Co", 2.0, 3, 6), _summary("Top Co", 3.0, 4, 4), _summary("Glass Co", 3.0, 5, 3),
            _summary("Fluff Co", 3.0, 4, 5), _summary("Main Co", 2.0, 3, 3), _summary("Rack Co", 4.0, 5, 3)]
    out.append({"id": "S-Skin", "type": "checkin_aggregate", "origin": "synthetic", "company": "Skin Co",
                "fields": {"kind": "sub_period_summary", "period": "2030-02-17..2030-03-01",
                           "raw_row": "Skin Co NEW Stucco floors 1–2 5 — 2.0 — 3"}})
    out.append({"id": "W1", "type": "daily_log_activity", "origin": "synthetic", "company": "Frame Co",
                "quote": "Interior framing — floors 1–2 (Feb 17–Mar 1)",
                "fields": {"kind": "period_work_item", "period": "2030-02-17..2030-03-01"}})
    out.append({"id": "W2", "type": "daily_log_activity", "origin": "synthetic", "company": "Skin Co",
                "quote": "Stucco — floors 1–2 (Feb 20–Mar 1)",
                "fields": {"kind": "period_work_item", "period": "2030-02-17..2030-03-01"}})
    return out


def synthetic_inspections():
    """SYNTHETIC public inspection record: plumbing rough passed on both floors and the roof."""
    passed = {"WS ROUGH": "PASSED", "ST DRN ROUGH": "PASSED", "GAS ROUGH": "PASSED"}
    return {"plumbing_permit_X": {
        "floor_results_table_UNDATED": {"001": dict(passed, **{"WS UND GRND": "CERTIFIED"}), "002": dict(passed),
                                        "ROF": dict(passed)},
        "completed_inspections": [{"id": "900", "result": "Pass", "resulted": "2030-02-28T10:00",
                                   "status_history": [["Pending", "TBD", "2030-02-19 12:00"],
                                                      ["Pass", "2030-02-28 10:00", "2030-02-28 10:01"]]}]}}


def _gen(**kw):
    b = synthetic_building(**{k: v for k, v in kw.items() if k in ("gas", "sprinkler", "elevators", "mezz")})
    ins = synthetic_inspections()
    # the generator reads the plumbing record under this key
    ins["plumbing_permit_B01141294-S5-PL"] = ins.pop("plumbing_permit_X")
    return G.generate(b, synthetic_records(), data_date=DATA_DATE, inspections=ins, timeline=(),
                      extras=kw.get("extras", False))


class CPMIsCorrect(unittest.TestCase):
    """SYNTHETIC textbook network: A(3) -> B(2), A -> C(4), B -> D(1), C -> D."""

    def setUp(self):
        self.acts = [{"id": "A", "effort": 3}, {"id": "B", "effort": 2}, {"id": "C", "effort": 4},
                     {"id": "D", "effort": 1}]
        self.links = [{"from": "A", "to": "B", "type": "FS", "lag": 0}, {"from": "A", "to": "C", "type": "FS", "lag": 0},
                      {"from": "B", "to": "D", "type": "FS", "lag": 0}, {"from": "C", "to": "D", "type": "FS", "lag": 0}]

    def test_forward_backward_and_float(self):
        r = G.cpm(self.acts, self.links)
        got = {k: (v["es"], v["ef"], v["ls"], v["lf"], v["tf"]) for k, v in r.items()}
        self.assertEqual(got, {"A": (0, 3, 0, 3, 0), "B": (3, 5, 5, 7, 2), "C": (3, 7, 3, 7, 0), "D": (7, 8, 7, 8, 0)})

    def test_driving_path_is_the_zero_float_chain(self):
        r = G.cpm(self.acts, self.links)
        self.assertEqual(G.driving_path(r, "D"), ["A", "C", "D"])

    def test_lag_ss_and_ff(self):
        acts = [{"id": "X", "effort": 4}, {"id": "Y", "effort": 2}, {"id": "Z", "effort": 1}, {"id": "W", "effort": 1}]
        links = [{"from": "X", "to": "Y", "type": "SS", "lag": 1}, {"from": "X", "to": "Z", "type": "FF", "lag": 0},
                 {"from": "X", "to": "W", "type": "FS", "lag": 2}]
        r = G.cpm(acts, links)
        self.assertEqual((r["Y"]["es"], r["Y"]["ef"]), (1, 3))
        self.assertEqual((r["Z"]["es"], r["Z"]["ef"]), (3, 4))
        self.assertEqual((r["W"]["es"], r["W"]["ef"]), (6, 7))
        self.assertEqual(r["X"]["tf"], 0)

    def test_a_cycle_is_refused(self):
        links = self.links + [{"from": "D", "to": "A", "type": "FS", "lag": 0}]
        with self.assertRaises(ValueError):
            G.cpm(self.acts, links)

    def test_weather_capacity_stretches_and_retreat_inverts(self):
        half = lambda _i: 0.5  # noqa: E731
        self.assertEqual(G.advance(0, 2, half), 4)
        self.assertEqual(G.retreat(4, 2, half), 0)
        self.assertEqual(G.advance(5, 0, half), 5)

    def test_calendar_skips_weekends_and_holidays(self):
        cal = G.Calendar(date(2030, 3, 2), [date(2030, 3, 5)])  # SYNTHETIC: a Saturday start, a Tuesday holiday
        self.assertEqual(cal.origin, date(2030, 3, 4))
        self.assertEqual(cal.date(1), date(2030, 3, 6))
        self.assertEqual(cal.date(4), date(2030, 3, 11))
        self.assertEqual(cal.index(date(2030, 3, 9)), 4)


class ScenariosAreOrdered(unittest.TestCase):
    def setUp(self):
        self.doc = _gen()

    def test_completion_fast_le_normal_le_conservative(self):
        c = self.doc["completion"]
        self.assertLessEqual(c["fast"]["tco"], c["normal"]["tco"])
        self.assertLessEqual(c["normal"]["tco"], c["conservative"]["tco"])
        self.assertLessEqual(c["normal"]["final_co"], c["conservative"]["final_co"])

    def test_every_activity_finish_is_ordered_before_levelling(self):
        """Pure CPM is monotone in its inputs, so EVERY activity is ordered.
        Floor-plate levelling is a greedy heuristic that may reorder work with
        float between scenarios; for it the finishes are pinned (above)."""
        b = synthetic_building()
        ins = {"plumbing_permit_B01141294-S5-PL": synthetic_inspections()["plumbing_permit_X"]}
        p = G.prepare(b, synthetic_records(), ins, ())
        runs = {s: G.schedule_scenario(p["net"], p["provisional"], p["assumptions"], s, DATA_DATE, level=False)
                for s in G.SCENARIOS}
        for aid in runs["normal"]["activities"]:
            f = [runs[s]["activities"][aid]["ef"] for s in G.SCENARIOS]
            self.assertTrue(f[0] <= f[1] <= f[2], f"{aid}: {f}")
        for s in G.SCENARIOS:
            self.assertGreaterEqual(self.doc["completion"][s]["tco_working_days"], runs[s]["tco_working_days"])

    def test_interior_ready_is_ordered(self):
        c = self.doc["completion"]
        self.assertLessEqual(c["fast"]["interior_ready"], c["normal"]["interior_ready"])
        self.assertLessEqual(c["normal"]["interior_ready"], c["conservative"]["interior_ready"])

    def test_every_assumption_is_tagged_and_ordered(self):
        for a in self.doc["assumptions"]:
            self.assertIn(a["tag"], G.TAGS, a["id"])
            self.assertTrue(G.monotone(a), a["id"])
            self.assertTrue(a["basis"], a["id"])

    def test_an_unordered_assumption_is_caught(self):
        bad = G.assumption("x", "x", "d", "industry-assumption", 9, 5, 7, faster="lower", basis="synthetic")
        self.assertFalse(G.monotone(bad))


class NothingBeforeItsPrerequisites(unittest.TestCase):
    def test_true_prerequisites_hold_in_every_scenario(self):
        doc = _gen()
        rows = {a["id"]: a for a in doc["network"]["activities"]}
        checked = 0
        for s in G.SCENARIOS:
            for l in doc["network"]["links"]:
                if l["kind"] != "prerequisite" or s not in l["scenarios"]:
                    continue
                p, q = rows[l["from"]]["scenarios"][s], rows[l["to"]]["scenarios"][s]
                if p["start"] is None or q["start"] is None:
                    continue
                lag = l["lag"] if isinstance(l["lag"], int) else 0
                started = rows[l["to"]]["state"]["status"] == "in_progress"
                if l["type"] == "FS" and not started:
                    self.assertGreaterEqual(q["es"], p["ef"] + lag, f"{s}: {l['from']} -> {l['to']}")
                elif l["type"] in ("FS", "FF"):
                    self.assertGreaterEqual(q["ef"], p["ef"] + (lag if l["type"] == "FF" else 0),
                                            f"{s}: {l['from']} -> {l['to']} (retained logic)")
                else:
                    self.assertGreaterEqual(q["es"], p["es"] + lag)
                checked += 1
        self.assertGreater(checked, 300)

    def test_floor_plate_limit_holds_for_work_not_already_under_way(self):
        doc = _gen()
        for s in G.SCENARIOS:
            for z, v in doc["concurrency"][s]["per_floor_peak"].items():
                started = [a for a in v["activities"] if next(x for x in doc["network"]["activities"]
                                                                if x["id"] == a)["state"]["status"] == "in_progress"]
                if not started:
                    self.assertLessEqual(v["trades"], v["limit_trades"], f"{s} {z}")


class InspectionsAreGates(unittest.TestCase):
    def setUp(self):
        self.doc = _gen()
        self.acts = {a["id"]: a for a in self.doc["network"]["activities"]}
        self.links = self.doc["network"]["links"]

    def _preds(self, aid, kind="prerequisite"):
        return {l["from"] for l in self.links if l["to"] == aid and l["kind"] == kind}

    def test_gates_are_their_own_activities_with_an_authority_and_no_crew(self):
        gates = [a for a in self.acts.values() if a["kind"] == "inspection_gate"]
        self.assertGreater(len(gates), 20)
        for g in gates:
            self.assertTrue(g["authority"], g["id"])
            self.assertIsNone(g["crew"], g["id"])

    def test_board_waits_for_every_pre_board_gate(self):
        for z in ("L1", "L2"):
            need = {f"gate_plumbing_rough_{z}", f"gate_elec_rough_{z}", f"gate_sprinkler_hydro_{z}",
                    f"gate_firestop_{z}", f"gate_tr8_insulation_{z}"}
            self.assertTrue(need <= self._preds(f"board_hang_{z}"), z)
            self.assertIn(f"gate_fire_rated_{z}", self._preds(f"tape_{z}"))

    def test_a_passed_plumbing_rough_is_not_the_plumbing_final(self):
        self.assertEqual(self.acts["gate_plumbing_rough_L1"]["state"]["status"], "done")
        self.assertEqual(self.acts["gate_plumbing_rough_L1"]["state"]["evidence"], "verified_public_record")
        final = self.acts["gate_plumbing_final"]
        self.assertNotEqual(final["state"]["status"], "done")
        self.assertIsNotNone(final["scenarios"]["normal"]["start"])
        self.assertIn("plumb_trim_L2", self._preds("gate_plumbing_final"))

    def test_electrical_rough_inspection_unknown_is_never_done(self):
        for z in ("L1", "L2"):
            self.assertEqual(self.acts[f"gate_elec_rough_{z}"]["state"]["status"], "unknown")
            self.assertGreater(self.acts[f"gate_elec_rough_{z}"]["scenarios"]["fast"]["effort_days"], 0)

    def test_regulatory_chains(self):
        self.assertIn("gate_detention_cert", self._preds("dep_connection_permit"))
        self.assertIn("dep_connection_permit", self._preds("dot_opening_permit"))
        self.assertIn("dot_opening_permit", self._preds("house_sewer_connection"))
        self.assertIn("gas_authorization", self._preds("ng_meter_on"))
        self.assertIn("ng_meter_on", self._preds("dhw_startup"))
        self.assertIn("dhw_startup", self._preds("gate_plumbing_final"))
        for g in ("gate_plumbing_final", "gate_dob_elec_final", "gate_sprinkler_final", "gate_fdny_fa"):
            self.assertIn(g, self._preds("gate_tco"))

    def test_ptac_sleeves_are_in_before_the_air_barrier_is_inspected(self):
        self.assertIn("ptac_sleeves_L1", self._preds("gate_air_barrier_front_rear"))
        self.assertIn("gate_air_barrier_front_rear", self._preds("eifs_front_rear"))


class AnEstimateIsNeverABaseline(unittest.TestCase):
    def setUp(self):
        self.doc = _gen()

    def test_the_document_says_estimate(self):
        self.assertEqual(self.doc["kind"], "schedule_estimate")
        self.assertIs(self.doc["is_baseline"], False)
        G.check_not_a_baseline(self.doc)

    def test_no_schedule_file_field_anywhere_in_the_network(self):
        keys = set(G._keys(self.doc["network"]))
        self.assertEqual(sorted(k for k in keys if k.startswith(G.FILE_FIELD_PREFIXES)), [])

    def test_a_tampered_document_is_refused(self):
        bad = copy.deepcopy(self.doc)
        bad["network"]["activities"][0]["baseline_finish"] = "2030-05-01"
        with self.assertRaises(ValueError):
            G.check_not_a_baseline(bad)
        bad2 = dict(self.doc, is_baseline=True)
        with self.assertRaises(ValueError):
            G.check_not_a_baseline(bad2)

    def test_the_file_readers_find_no_dates_in_it(self):
        rows = F.plan_vs_actual({"activities": self.doc["network"]["activities"]}, [], [], today=DATA_DATE)
        self.assertTrue(rows)
        self.assertTrue(all(r["file"]["planned_finish"] is None and r["file"]["planned_start"] is None for r in rows))

    def test_dates_leave_only_as_estimate_items_never_markers(self):
        items = G.estimate_items(self.doc, "synthetic-project")
        self.assertEqual(len(items), 3)
        for i in items:
            self.assertEqual(i["kind"], "estimate")
            self.assertTrue(i["basis"])
        m = F.markers(items)
        self.assertIsNone(m["start"])
        self.assertIsNone(m["done"])
        self.assertEqual(E.status(items), "unknown")


class TheNetworkIsThisBuilding(unittest.TestCase):
    def test_systems_the_drawings_lack_have_no_activities(self):
        doc = _gen(gas=False, sprinkler=False)
        ids = {a["id"] for a in doc["network"]["activities"]}
        self.assertFalse(any(i.startswith(("sprinkler_", "gate_sprinkler")) for i in ids))
        self.assertFalse({"gas_authorization", "ng_meter_on", "hwh_room"} & ids)
        na = {x["id"] for x in doc["network"]["not_applicable"]}
        self.assertIn("elevator", na)
        self.assertIn("standpipe", na)

    def test_quantities_come_from_the_drawing(self):
        doc = _gen()
        acts = {a["id"]: a for a in doc["network"]["activities"]}
        # SYNTHETIC: partitions 40+60+50+20 = 170 LF
        self.assertEqual(acts["framing_close_L1"]["scope"]["quantity"], 170.0)
        # board: (60+120)*1 + (40+60)*4 + 50*2 + 20*3 = 740 LF-faces x 9 ft + 2000 x 0.9
        self.assertEqual(acts["board_hang_L1"]["scope"]["quantity"], 740 * 9 + 1800)
        self.assertEqual(acts["ptac_sleeves_L1"]["scope"]["quantity"] + acts["ptac_sleeves_L2"]["scope"]["quantity"], 8)

    def test_an_inflated_small_level_is_scaled_and_said(self):
        doc = _gen(mezz=True)
        mez = next(z for z in doc["facts"]["zones"] if z["id"] == "MEZ")
        self.assertIn("scaled", mez["lf_source"])
        self.assertTrue(any("inflated" in n for n in doc["notes"]))

    def test_superstructure_cycles_are_not_invented_for_a_cfs_frame(self):
        sc = _gen()["superstructure_cycles"]
        self.assertIs(sc["relevant"], False)
        self.assertIn("cold-formed steel", " ".join(sc["why"]))


class MeasuredIsMeasured(unittest.TestCase):
    def test_crew_sizes_with_sample(self):
        crews = G.measured_crews(synthetic_records())
        self.assertEqual((crews["Frame Co"]["avg"], crews["Frame Co"]["peak"], crews["Frame Co"]["days"]), (8.0, 11, 10))
        self.assertEqual((crews["Skin Co"]["avg"], crews["Skin Co"]["peak"], crews["Skin Co"]["days"]), (2.0, 3.0, 5))
        self.assertEqual(crews["Spray Co"]["avg"], None)
        self.assertEqual(crews["Frame Co"]["role"], "framing")
        self.assertEqual(crews["Main Co"]["role"], "site_utility")
        a = {x["id"]: x for x in G.measured_assumptions(crews, {})}
        self.assertEqual(a["crew_frame_co"]["tag"], "measured")
        self.assertEqual(a["crew_frame_co"]["sample"]["n_days"], 10)
        self.assertNotIn("crew_spray_co", a)

    def test_inspection_lead_is_measured_from_the_record(self):
        lead = G.measured_inspection_leads(synthetic_inspections())
        self.assertEqual(lead["dob_plumbing"]["working_days"], 7)
        self.assertEqual(lead["dob_plumbing"]["n"], 1)

    def test_an_unmeasured_trade_mobilizes(self):
        doc = _gen()
        acts = {a["id"]: a for a in doc["network"]["activities"]}
        self.assertTrue(acts["tape_L1"]["mobilize"])
        self.assertEqual(acts["tape_L1"]["scenarios"]["normal"]["not_before_days"], 5)


class StateAndBranches(unittest.TestCase):
    def test_model_state_is_laid_over_without_lowering_verified(self):
        doc = _gen()
        net = {"activities": doc["network"]["activities"]}
        base = {a["id"]: a["state"] for a in doc["network"]["activities"]}
        model = {"current_state": {"levels": {
            "FLOOR_1": {"work": {"gate_plumbing_rough": {"status": "reported"}},
                        "systems": {"electrical": {"state": "inferred_done_medium"}}}}}}
        st, notes = G.state_from_model(model, net, base)
        self.assertEqual(st["gate_plumbing_rough_L1"]["evidence"], "verified_public_record")
        self.assertEqual((st["elec_rough_L1"]["status"], st["elec_rough_L1"]["evidence"]), ("done", "inferred"))
        self.assertTrue(notes)

    def test_unknowns_are_reported_as_branches(self):
        doc = _gen(extras=True)
        ids = {b["id"] for b in doc["branches"]}
        self.assertTrue({"electrical_rough", "sprinkler_rough", "ptac_sleeves", "all_state_branches"} <= ids)
        for b in doc["branches"]:
            self.assertLessEqual(b["tco_if_a"], b["tco_if_b"], b["id"])
        self.assertTrue(doc["acceleration_levers"])


if __name__ == "__main__":
    unittest.main()
