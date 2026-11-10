"""lib/construction_inference.py: rules that connect evidence with how THIS
building is built.

EVERY FIXTURE HERE IS SYNTHETIC: a made-up two-storey + mezzanine CFS building
on a slab on grade, made-up subs ("Plumber Co", "Insul Co"), made-up refs and
dates. No real record is in this file.

What is held:
  * the model is read from a building.json-shaped dict (levels, slab on grade,
    CFS, which levels carry plumbing, what is on the roof);
  * one source is never an inference; two independent ones can be;
  * confidence is a word from a mechanical rule, stepped down by contradictions;
  * a passed rough inspection IMPLIES the inspected rough-in (verified, with
    implied_by) and nothing else; an inference never decides status();
  * slab-on-grade rules run only where the model has a slab on grade;
  * impossible floors, pours without a cast slab, work out of order and
    log-vs-gate headcounts are contradictions, never resolved by a guess;
  * closure prerequisites with no record are unknown, never "not done".
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import construction_inference as CI  # noqa: E402
from lib import evidence as E  # noqa: E402

PID = "synthetic"
D = date(2026, 3, 1)

SYNTHETIC_BUILDING = {
    "structure": {"system": {"value": "Cold-formed steel (CFS) load-bearing stud walls and C-joist floors."},
                  "foundation": {"value": {"type": "Spread footings with a 6\" slab-on-grade first floor; no piles"}}},
    "derived_quantities_per_floor": {"value": {
        "FIRST": {"baths": 2}, "SECOND": {"baths": 2}, "MEZZANINE": {"baths": 1},
        "ROOF": {"notes": "roof drains (AD) x2; HWH room"}}},
    "plumbing": {"gas": {"value": "Gas meter at the first floor, gas riser G-1, roof HWH ROOM"}},
    "fire_protection_electrical_vertical": {"sprinkler": {"value": "NFPA 13R wet sprinkler"},
                                            "elevator": {"value": "NONE. Two stairs."}},
    "unit_schedule": {"value": [{"id": "1A", "floor": 1}, {"id": "2A", "floor": 2, "upper_mezz_net_sf": 100}]},
}
MODEL = CI.model_from_building(SYNTHETIC_BUILDING, name="synthetic")


def d(m, day):
    return date(2026, m, day)


def rep(ref, node, levels, on, sub="Plumber Co", quote="synthetic row", note=""):
    return E.item("reported", "in_progress", source="logbooks", ref=ref, project_id=PID, node=node, levels=levels,
                  sub=sub, on=on, quote=quote, shared=len(levels) > 1, note=note)


def photo(ref, node, levels, on, sub="Insul Co"):
    return E.item("observed", "in_progress", source="photo_index", ref=ref, project_id=PID, node=node,
                  levels=levels, sub=sub, on=on, quote="synthetic caption")


def run(items, as_of=D, **kw):
    return CI.infer(items, MODEL, as_of=as_of, project_id=PID, **kw)


def inf_on(out, level, system="plumbing"):
    got = [i for i in out["inferences"] if i["node"] == f"rough_{system}" and i["levels"] == [level]]
    return got[0] if got else None


class TheModel(unittest.TestCase):

    def test_it_reads_this_buildings_facts(self):
        self.assertEqual(MODEL["levels"], ["FLOOR_1", "FLOOR_2", "MEZZANINE", "ROOF"])
        self.assertTrue(MODEL["slab_on_grade"])
        self.assertEqual(MODEL["superstructure"], "cfs")
        self.assertEqual(MODEL["cast_concrete_levels"], ["FLOOR_1"])
        self.assertEqual(MODEL["plumbing_levels"], ["FLOOR_1", "FLOOR_2", "MEZZANINE", "ROOF"])
        self.assertIs(MODEL["piles_drawn"], False)
        self.assertTrue(MODEL["systems"]["gas"])
        self.assertIs(MODEL["systems"]["elevator"], False)
        self.assertEqual(MODEL["units"]["MEZZANINE"], ["2A"])

    def test_an_unstated_fact_stays_unknown(self):
        m = CI.model_from_building({"derived_quantities_per_floor": {"value": {"FIRST": {"baths": 1}}}})
        self.assertFalse(m["slab_on_grade"])
        self.assertEqual(m["cast_concrete_levels"], [])
        self.assertIsNone(m["piles_drawn"])


class RoughInPlace(unittest.TestCase):

    def test_one_source_is_not_an_inference(self):
        out = run([rep("L1", "rough_plumbing", ["FLOOR_2"], d(2, 1)), rep("L2", "rough_water", ["FLOOR_2"], d(2, 3))])
        self.assertIsNone(inf_on(out, "FLOOR_2"))

    def test_a_gate_checkin_is_not_a_place_signal(self):
        ck = E.item("reported", "present", source="checkins", ref="C1", project_id=PID, sub="Gate Person", on=d(2, 1),
                    node="rough_plumbing", levels=["FLOOR_2"])
        out = run([rep("L1", "rough_plumbing", ["FLOOR_2"], d(2, 1)), ck])
        self.assertIsNone(inf_on(out, "FLOOR_2"))

    def test_two_crews_shared_statements_infer_low(self):
        out = run([rep("L1", "rough_plumbing", ["FLOOR_1", "FLOOR_2"], d(2, 1)),
                   rep("L2", "insulation", ["FLOOR_1", "FLOOR_2"], d(2, 10), sub="Insul Co")])
        i = inf_on(out, "FLOOR_2")
        self.assertEqual(i["kind"], "inferred")
        self.assertEqual(i["claim"], "done")                 # a later stage closes over it
        self.assertEqual(i["confidence"], "low")
        self.assertEqual(i["confidence_rule"], CI.CONFIDENCE_RULES["low"])
        self.assertIn("not narrowed", i["basis"])
        self.assertTrue(i["disproof"])
        self.assertEqual(i["unlocks"], ["gate_plumbing_rough on FLOOR_2 (the rough inspection can be requested)"])

    def test_a_photo_filed_for_one_floor_narrows_that_floor_only(self):
        out = run([rep("L1", "rough_plumbing", ["FLOOR_1", "FLOOR_2"], d(2, 1)),
                   photo("P1", "rough_plumbing", ["FLOOR_1"], d(2, 5))])
        f1, f2 = inf_on(out, "FLOOR_1"), inf_on(out, "FLOOR_2")
        self.assertEqual(f1["claim"], "in_progress")         # nothing closes over it yet
        self.assertEqual(f1["confidence"], "medium")
        self.assertIn("P1", f1["note"])
        self.assertIsNone(f2)                                 # the photo is not about floor 2

    def test_three_independent_sources_one_alone_one_observed_is_high(self):
        out = run([rep("L1", "rough_plumbing", ["FLOOR_1", "FLOOR_2"], d(2, 1)),
                   photo("P1", "rough_plumbing", ["FLOOR_2"], d(2, 5)),
                   rep("L2", "insulation", ["FLOOR_1", "FLOOR_2"], d(2, 10), sub="Insul Co")])
        i = inf_on(out, "FLOOR_2")
        self.assertEqual((i["claim"], i["confidence"]), ("done", "high"))
        self.assertEqual(E.independent_sources(i["signals"]), 3)
        self.assertTrue(all(s["source"] and s["ref"] and s["kind"] for s in i["signals"]))

    def test_a_contradiction_on_the_subject_steps_confidence_down(self):
        rows = [rep("L1", "rough_plumbing", ["FLOOR_1", "FLOOR_2"], d(2, 1)),
                photo("P1", "rough_plumbing", ["FLOOR_2"], d(2, 5)),
                rep("L2", "insulation", ["FLOOR_1", "FLOOR_2"], d(2, 10), sub="Insul Co")]
        con = {"kind": "synthetic", "what": "x", "refs": ["P1"], "levels": [], "node": None, "on": None}
        i = CI.rough_in(rows, MODEL, "FLOOR_2", "plumbing", as_of=D, project_id=PID, cons=[con])
        self.assertEqual(i["confidence"], "medium")
        self.assertEqual(i["contradictions"], [con])

    def test_one_author_naming_two_subs_is_one_source(self):
        # Review 2, C1: the CP's daily log names the plumber and the concrete
        # crew; one person typed and signed both rows.
        cp = "GC daily log (CP)"
        rows = [E.item("reported", "in_progress", source="logbooks", ref="U1", project_id=PID,
                       node=CI.UNDERGROUND["plumbing"], levels=["FLOOR_1"], sub="Plumber Co", on=d(1, 5), by=cp),
                E.item("reported", "in_progress", source="logbooks", ref="S1", project_id=PID, node=CI.SLAB_ON_GRADE,
                       levels=["FLOOR_1"], sub="Concrete Co", on=d(1, 12), by=cp, quote="pour slab")]
        self.assertEqual([x for x in run(rows)["inferences"] if x["node"] == "underground_plumbing"], [])
        gate = E.item("reported", "present", source="logbooks", ref="V1", project_id=PID, node=CI.UNDERGROUND_GATE,
                      levels=["FLOOR_1"], on=d(1, 10), by="DOB inspector's visit noted by the super")
        self.assertEqual(len([x for x in run(rows + [gate])["inferences"] if x["node"] == "underground_plumbing"]), 1)

    def test_an_amendment_and_its_original_are_one_event(self):
        cp = "GC daily log (CP)"
        a = E.item("reported", "in_progress", source="logbooks", ref="A1", project_id=PID, node="rough_plumbing",
                   levels=["FLOOR_2"], sub="Plumber Co", on=d(2, 1), by=cp)
        b = dict(a, ref="A2")                                    # the amended document's copy of the row
        self.assertEqual([s["ref"] for s in CI.one_per_record([CI.signal(a, "x"), CI.signal(b, "x")])], ["A1"])

    def test_one_record_is_never_two_signals(self):
        rows = [rep("R9:first:rough_plumbing", "rough_plumbing", ["FLOOR_2"], d(2, 1)),
                rep("R9:last:rough_plumbing", "rough_plumbing", ["FLOOR_2"], d(2, 8)),
                rep("L2", "insulation", ["FLOOR_2"], d(2, 10), sub="Insul Co")]
        i = inf_on(run(rows), "FLOOR_2")
        self.assertEqual([s["ref"] for s in i["signals"]], ["R9:first:rough_plumbing", "L2"])

    def test_an_inference_never_decides_status(self):
        rows = [rep("L1", "rough_plumbing", ["FLOOR_2"], d(2, 1)),
                rep("L2", "insulation", ["FLOOR_2"], d(2, 10), sub="Insul Co")]
        i = inf_on(run(rows), "FLOOR_2")
        self.assertEqual(i["claim"], "done")
        self.assertEqual(E.status([r for r in rows if r["node"] == "rough_plumbing"] + [i]), "reported")

    def test_records_after_as_of_are_not_read(self):
        rows = [rep("L1", "rough_plumbing", ["FLOOR_2"], d(2, 1)),
                rep("L2", "insulation", ["FLOOR_2"], d(4, 10), sub="Insul Co")]
        self.assertIsNone(inf_on(run(rows, as_of=d(3, 1)), "FLOOR_2"))
        self.assertIsNotNone(inf_on(run(rows, as_of=d(4, 10)), "FLOOR_2"))

    def test_roofing_closes_over_roof_drains_only_where_the_model_has_them(self):
        rows = [rep("L1", "rough_plumbing", ["ROOF"], d(2, 1)), rep("L2", "roofing", [], d(2, 9), sub="Roof Co")]
        self.assertEqual(inf_on(run(rows), "ROOF")["claim"], "done")
        bare = dict(MODEL, roof_plumbing=[])
        self.assertIsNone(CI.rough_in(rows, bare, "ROOF", "plumbing", as_of=D, project_id=PID))


class VerifiedImplications(unittest.TestCase):

    def test_a_passed_rough_inspection_implies_the_inspected_rough_in_only(self):
        gate = E.item("verified", "done", source="dob_now_inspections", ref="G1", project_id=PID,
                      node="gate_plumbing_rough", levels=["FLOOR_2"], on=d(2, 20))
        out = run([gate, rep("L1", "rough_plumbing", ["FLOOR_2"], d(2, 1)),
                   rep("L2", "insulation", ["FLOOR_2"], d(2, 10), sub="Insul Co")])
        imp = out["implications"]
        self.assertEqual(sorted(i["node"] for i in imp), ["rough_dwv", "rough_gas", "rough_water"])
        self.assertTrue(all(i["kind"] == "verified" and i["implied_by"] == "G1" and i["on"] == d(2, 20) for i in imp))
        self.assertEqual(E.status([i for i in imp if i["node"] == "rough_water"]), "done_verified")
        self.assertIsNone(inf_on(out, "FLOOR_2"))            # a fact, so no inference is drawn
        self.assertIsNone(inf_on(out, "FLOOR_2", "electrical"))

    def test_an_attested_pass_is_support_not_an_implication(self):
        said = E.item("attested", "done", source="whatsapp", ref="W1", project_id=PID, node="gate_plumbing_rough",
                      on=d(2, 20), by="someone")
        out = run([said, rep("L1", "rough_plumbing", ["FLOOR_2"], d(2, 1))])
        self.assertEqual(out["implications"], [])
        i = inf_on(out, "FLOOR_2")
        self.assertEqual(i["claim"], "done")
        self.assertIn("W1", [s["ref"] for s in i["signals"]])


class SlabOnGrade(unittest.TestCase):

    def rows(self):
        return [rep("U1", CI.UNDERGROUND["plumbing"], ["FLOOR_1"], d(1, 5)),
                rep("U2", CI.UNDERGROUND["plumbing"], ["FLOOR_1"], d(1, 8)),
                rep("S1", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 12), sub="Concrete Co", quote="pour slab")]

    def test_under_slab_work_is_in_place_by_the_pour(self):
        out = run(self.rows())
        i = [x for x in out["inferences"] if x["node"] == "underground_plumbing"][0]
        self.assertEqual((i["claim"], i["on"], i["levels"]), ("done", d(1, 12), ["FLOOR_1"]))
        self.assertEqual(i["space"], "below the ground slab")

    def test_under_slab_work_after_the_pour_is_a_contradiction(self):
        out = run(self.rows() + [rep("U3", CI.UNDERGROUND["plumbing"], ["FLOOR_1"], d(1, 20))])
        kinds = [c["kind"] for c in out["contradictions"]]
        self.assertIn("under_slab_after_pour", kinds)

    def test_a_pour_listed_before_the_sub_base_is_not_the_slab(self):
        # A chip list on day 1 names "pour slab" before the gravel / vapour
        # barrier went down: a slab on grade is poured over its prepared
        # sub-base, so the slab pour is the one after the last preparation.
        rows = [rep("X1", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 1), sub="Concrete Co",
                    quote="Foundation pile, pour cellar slab, pour columns / shear walls"),
                rep("U1", CI.UNDERGROUND["plumbing"], ["FLOOR_1"], d(1, 5)),
                rep("G1", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 9), sub="Concrete Co", quote="Slab gravel"),
                rep("V1", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 10), sub="Concrete Co", quote="Vapour barrier, mesh"),
                rep("S1", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 12), sub="Concrete Co", quote="pour slab")]
        self.assertEqual(CI.slab_pour(rows, MODEL)["ref"], "S1")
        out = run(rows)
        self.assertEqual([x["on"] for x in out["inferences"] if x["node"] == "underground_plumbing"], [d(1, 12)])
        kinds = [c["kind"] for c in out["contradictions"]]
        self.assertNotIn("under_slab_after_pour", kinds)
        merged = [c for c in out["contradictions"] if c["kind"] == "foundation_words_not_in_the_model"][0]
        self.assertIn("concrete_frame_in_a_cfs_building", merged["parts"])

    def test_no_slab_on_grade_no_rule(self):
        m = dict(MODEL, slab_on_grade=False)
        self.assertEqual(CI.under_slab(self.rows(), m, "plumbing", as_of=D, project_id=PID), (None, []))

    def test_a_pour_on_a_cfs_upper_floor_is_a_contradiction(self):
        out = run([rep("S2", "superstructure", ["FLOOR_2"], d(2, 1), sub="Concrete Co", quote="pour slab 2nd fl")])
        self.assertEqual([c["kind"] for c in out["contradictions"]], ["pour_without_a_cast_slab"])

    def test_framing_before_the_ground_slab_is_out_of_order(self):
        # Review 2, M6: compared with THE pour, not with the first slab-word
        # row (a chip dump the same day as the framing hid it), and each row
        # classified by its own words.
        chips = rep("X1", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 2), sub="Concrete Co", quote="pour cellar slab")
        gravel = rep("G1", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 9), sub="Concrete Co", quote="Slab gravel")
        out = run(self.rows() + [chips, gravel, rep("F1", "framing", ["FLOOR_1"], d(1, 2), sub="Frame Co",
                                                     quote="Framing (layout, track and studs)"),
                                 rep("F2", "framing", ["FLOOR_1"], d(1, 3), sub="Frame Co",
                                     quote="Wall framing, sheathing")])
        c = [c for c in out["contradictions"] if c["kind"] == "framing_before_slab_pour"]
        self.assertEqual(c[0]["levels"], ["FLOOR_1"])
        self.assertIn("1 row(s) name exterior / perimeter wall framing; 1 do not say where", c[0]["what"])
        self.assertIn("S1", c[0]["refs"])
        inf = [x for x in out["inferences"] if x["node"] == "underground_plumbing"][0]
        self.assertIn("framing_before_slab_pour", [k["kind"] for k in inf["contradictions"]])

    def test_an_elevator_in_a_building_without_one(self):
        out = run([E.item("observed", "present", source="photo_index", ref="W1", project_id=PID, on=d(2, 1),
                          quote="Elevator beam pockets", note="punch-walk photo; floor tag 'roof' set by the person")])
        self.assertEqual(out["contradictions"][0]["kind"], "walk_does_not_fit_this_building")
        self.assertEqual(out["contradictions"][0]["parts"], ["names_an_elevator"])

    def test_one_walks_impossibles_are_one_issue_and_counts_are_records(self):
        walk = [E.item("observed", "present", source="photo_index", ref=f"W{n}", project_id=PID, on=d(2, 1),
                       candidates=[lv], quote=q, note="punch-walk photo; floor tag set by the person")
                for n, (lv, q) in enumerate((("FLOOR_5", "stairs"), ("FLOOR_7", "Compound and sheetrock not done")))]
        chips = [rep("R7:foundation", "foundation", [], d(1, 1), quote="Pile caps, pour cellar slab"),
                 rep("R7:slab_on_grade", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 1), quote="Pile caps, pour cellar slab")]
        cons = run(walk + chips)["contradictions"]
        kinds = sorted(c["kind"] for c in cons)
        self.assertEqual(kinds, ["foundation_words_not_in_the_model", "walk_does_not_fit_this_building"])
        merged = [c for c in cons if c["kind"] == "foundation_words_not_in_the_model"][0]
        self.assertTrue(merged["what"].startswith("1 foundation-phase record(s)"), merged["what"])
        self.assertEqual(merged["parts"], ["names_a_cellar", "piles_not_on_drawings"])
        walk_issue = [c for c in cons if c["kind"] == "walk_does_not_fit_this_building"][0]
        self.assertIn("sheetrock / compound while no board is on record", walk_issue["what"])

    def test_a_gas_rough_pass_implies_gas_rough_only(self):
        gate = E.item("verified", "done", source="dob_now_inspections", ref="7755632:001:GAS ROUGH", project_id=PID,
                      node="gate_plumbing_rough", levels=["FLOOR_1"], on=d(2, 20), quote="GAS ROUGH PASSED (floor 001)")
        self.assertEqual([i["node"] for i in run([gate])["implications"]], ["rough_gas"])


class Contradictions(unittest.TestCase):

    def test_a_floor_the_building_does_not_have(self):
        walk = E.item("observed", "present", source="photo_index", ref="W7", project_id=PID, candidates=["FLOOR_7"],
                      on=d(2, 1))
        c = run([walk])["contradictions"]
        self.assertEqual((c[0]["kind"], c[0]["levels"], c[0]["refs"]), ("impossible_level", ["FLOOR_7"], ["W7"]))

    def test_a_cellar_and_piles_on_a_slab_on_grade_building(self):
        out = run([rep("C1", CI.SLAB_ON_GRADE, ["FLOOR_1"], d(1, 2), quote="Cellar slab rebar"),
                   rep("C2", "foundation", [], d(1, 1), quote="Pile caps, footings")])
        [c] = out["contradictions"]
        self.assertEqual((c["kind"], c["parts"]), ("foundation_words_not_in_the_model",
                                                   ["names_a_cellar", "piles_not_on_drawings"]))
        self.assertTrue(c["what"].startswith("2 foundation-phase record(s)"))

    def test_work_naming_the_roof_filed_on_floors(self):
        row = rep("R1", "rough_plumbing", ["ROOF"], d(2, 1), quote="Roof MEP",
                  note=f"{CI.FILED_LOCATION}floors 1–2; trade: Plumber")
        c = run([row])["contradictions"]
        self.assertEqual([x["kind"] for x in c], ["work_names_another_level"])

    def test_log_vs_gate_headcount(self):
        c = run([], headcounts=[{"date": d(2, 1), "sub": "Plumber Co", "log_count": 5, "gate_count": 4,
                                 "refs": ["L1", "G1"]}])["contradictions"]
        self.assertEqual(c[0]["kind"], "headcount_log_vs_gate")
        self.assertEqual(run([], headcounts=[{"date": d(2, 1), "sub": "x", "log_count": 4, "gate_count": 4}])
                         ["contradictions"], [])


class Closure(unittest.TestCase):

    def test_open_prerequisites_are_unknown_not_not_done(self):
        out = run([rep("L1", "rough_plumbing", ["FLOOR_2"], d(2, 1)),
                   rep("L2", "insulation", ["FLOOR_2"], d(2, 10), sub="Insul Co")])
        cl = out["closure"]["FLOOR_2"]
        self.assertEqual(cl["closing_first"], "2026-02-10")
        self.assertIn("gate_plumbing_rough", cl["open_on_record"])
        self.assertIn("gate_sprinkler_hydro", cl["open_on_record"])
        self.assertIn("unknown, not 'not done'", cl["words"])
        row = [r for r in cl["prerequisites"] if r["gate"] == "gate_plumbing_rough"][0]
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["rough_in"], {"inferred": "done", "confidence": "medium"})


if __name__ == "__main__":
    unittest.main()
