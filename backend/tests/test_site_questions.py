"""SITE QUESTIONS on a SYNTHETIC job (hand-made network, no real data).

Every assertion names the case it is about. The job: one floor of interior
work behind a long facade, a verified plumbing rough, an un-recorded
low-voltage sub, a shed permit 12 days from expiry, a GC permit 71 days out,
a high-float roof coping, a second floor placed only by a multi-floor photo,
and a sprinkler test with no recorded pipe. Tue Nov 10 2026.

SYNTHETIC: the chain test at the bottom runs the whole chain on this fixture;
the real-data chain on 588 is tests/test_site_questions_588_chain.py."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret")

from lib import confirmation_queue as CQ  # noqa: E402
from lib import schedule_generator as G  # noqa: E402
from lib import site_questions as SQ  # noqa: E402

TODAY = date(2026, 11, 10)
IA = "industry-assumption"


def _a(aid, f, n, c, faster="lower"):
    return G.assumption(aid, aid, "working days", IA, f, n, c, faster=faster, basis="synthetic")


ASSUMPTIONS = [
    _a("holidays", [], [], []), _a("mobilization", 0, 5, 10),
    _a("remaining_operator_done", 0.05, 0.1, 0.2), _a("remaining_inferred_done", 0.1, 0.2, 0.3),
    _a("remaining_in_progress", 0.3, 0.5, 0.7), _a("remaining_unknown", 0.6, 0.8, 1.0),
    _a("d_frame", 2, 3, 4), _a("d_elec", 4, 6, 8), _a("d_elec2", 4, 6, 8), _a("d_lv", 1, 4, 6),
    _a("d_board", 6, 8, 10), _a("d_facade", 10, 80, 120), _a("d_coping", 2, 3, 4), _a("d_sprk", 3, 4, 5),
    _a("lead_elec", 5, 8, 15), _a("lead_tco", 10, 20, 30), _a("lead_sprk", 2, 3, 5),
    _a("dur_permit_renewal", 1, 1, 2), _a("max_trades_per_floor", 4, 4, 4, "higher"), _a("sf_per_worker", 200, 200, 200),
]


def _w(aid, zone, dur, company=None, **kw):
    return dict({"id": aid, "name": aid.replace("_", " "), "kind": "work", "zone": zone, "family": aid,
                 "rule": "fixed", "dur": dur, "company": company, "mobilize": True}, **kw)


ACTS = [
    _w("framing_close_L1", "L1", "d_frame", "FramerCo"),
    _w("elec_rough_L1", "L1", "d_elec", "SparkCo"),
    _w("elec_rough_L2", "L2", "d_elec2", "SparkCo"),
    _w("lv_rough_L1", "L1", "d_lv", "LowVoltCo"),
    _w("sprinkler_rough_L1", "L1", "d_sprk", "SprinkCo"),
    _w("board_hang_L1", "L1", "d_board", "FramerCo"),
    _w("plumbing_rough_L1", "L1", "d_frame", "PlumbCo"),
    _w("eifs_sides", "ENVELOPE", "d_facade", "StuccoCo"),
    _w("roof_coping", "ROOF", "d_coping", "RoofCo"),
    _w("ptac_sleeves_L1", "L1", "d_frame", "SleeveCo"),
    _w("insulation_L1", "L1", "d_frame", "InsulCo"),
    {"id": "gate_elec_rough_L1", "name": "DOB electrical rough inspection, Floor 1", "kind": "inspection_gate",
     "zone": "L1", "family": "gate_elec_rough", "rule": "lead", "lead": "lead_elec", "authority": "DOB Electrical",
     "gate_of": ["elec_rough_L1", "lv_rough_L1"]},
    {"id": "gate_sprinkler_hydro_L1", "name": "sprinkler hydro, Floor 1", "kind": "inspection_gate", "zone": "L1",
     "family": "gate_sprinkler_hydro", "rule": "lead", "lead": "lead_sprk",
     "authority": "Licensed sprinkler contractor test (NFPA 13R)", "gate_of": ["sprinkler_rough_L1"]},
    {"id": "renew_permit_shed", "name": "Renew shed permit", "kind": "regulatory", "zone": "SITE",
     "family": "permit_renewal", "rule": "fixed", "dur": "dur_permit_renewal", "deadline": "2026-11-22"},
    {"id": "renew_permits_gc", "name": "Renew GC permit", "kind": "regulatory", "zone": "SITE",
     "family": "permit_renewal", "rule": "fixed", "dur": "dur_permit_renewal", "deadline": "2027-01-20"},
    {"id": "gate_tco", "name": "TCO", "kind": "inspection_gate", "zone": "SITE", "family": "gate_tco", "rule": "lead",
     "lead": "lead_tco", "authority": "DOB"},
]


def _l(a, b, kind="prerequisite"):
    return {"from": a, "to": b, "type": "FS", "lag": 0, "kind": kind, "why": "synthetic", "scenarios": list(G.SCENARIOS)}


LINKS = [_l("framing_close_L1", "elec_rough_L1"), _l("elec_rough_L1", "gate_elec_rough_L1"),
         _l("lv_rough_L1", "gate_elec_rough_L1"), _l("gate_elec_rough_L1", "board_hang_L1"),
         _l("plumbing_rough_L1", "board_hang_L1"), _l("plumbing_rough_L1", "sprinkler_rough_L1"),
         _l("sprinkler_rough_L1", "gate_sprinkler_hydro_L1"),
         _l("gate_sprinkler_hydro_L1", "board_hang_L1"), _l("board_hang_L1", "gate_tco"),
         _l("eifs_sides", "gate_tco"), _l("roof_coping", "gate_tco"), _l("elec_rough_L1", "elec_rough_L2", "resource"),
         _l("ptac_sleeves_L1", "insulation_L1"), _l("insulation_L1", "board_hang_L1"),
         _l("renew_permit_shed", "eifs_sides")]

ST = G.state_entry
STATE = {
    "framing_close_L1": ST("done", "verified_public_record", "framing inspection (synthetic)"),
    "elec_rough_L1": ST("in_progress", "reported_log", "synthetic log"),
    "elec_rough_L2": ST("in_progress", "reported_log", "synthetic multi-floor photo"),
    "lv_rough_L1": ST("unknown", "no_record", "no record"),
    "sprinkler_rough_L1": ST("unknown", "no_record", "no record"),
    "board_hang_L1": ST("not_started", "inferred", "no board on record"),
    "plumbing_rough_L1": ST("done", "verified_public_record", "DOB rough pass (synthetic)"),
    "eifs_sides": ST("in_progress", "reported_log", "synthetic photo"),
    "ptac_sleeves_L1": ST("in_progress", "reported_log", "synthetic log"),
    "insulation_L1": ST("unknown", "no_record", "no record"),
    "roof_coping": ST("unknown", "no_record", "no record"),
}
#: A model current_state: Floor 2 electrical is placed only by a multi-floor photo.
MODEL = {"levels": {"FLOOR_2": {"work": {"rough_electric": {"status": "in_progress_observed", "refs": ["S9:rough_electric"],
                                                            "shared_only": True}}}}}


def _net():
    return {"activities": [dict(a) for a in ACTS], "links": [dict(l) for l in LINKS]}


def _ctx(**kw):
    sched = SQ.Rescheduler(_net(), STATE, ASSUMPTIONS, TODAY)
    ctx = {"today": TODAY, "sched": sched, "model": MODEL,
           "records": {"S9": {"date": "2026-11-03", "company": "SparkCo", "location": "floors 1-3",
                              "text": "Electrical work installed", "class": "original"}},
           "people": [{"role": r} for r in SQ.ROLE_SLOTS], "permits": {}, "permit_words": {}, "permit_why": {},
           "not_public": {"DOB Electrical": "not public (synthetic)"}, "utilities": [], "levers": [], "given": [],
           "sub_last_original": {"LowVoltCo": None, "GoneCo": date(2026, 9, 1)}, "answered_by_records": [],
           "answers": [], "history": []}
    ctx.update(kw)
    return ctx


def _asked(doc):
    return [q for qs in doc["by_person"].values() for q in qs]


def _find(doc, qid):
    return next((q for q in _asked(doc) if q["id"] == qid), None)


def _sup(doc, qid):
    return next((s for s in doc["suppressed"] if s["id"] == qid), None)


class SiteQuestionsSynthetic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = _ctx()
        cls.doc = SQ.generate(cls.ctx)
        cls.full = {q["id"]: q for q in cls.doc.pop("_asked")}

    # ── what a question carries ──

    def test_each_question_has_both_languages_who_why_trigger_branches_and_a_stated_value(self):
        qs = _asked(self.doc)
        self.assertTrue(qs, "the synthetic job yields questions")
        for q in qs:
            self.assertTrue(q["text_en"].strip() and q["text_es"].strip(), q["id"])
            self.assertIn(q["recipient"], SQ.ROLE_SLOTS, q["id"])
            self.assertTrue(q["why_it_matters"] and q["evidence"] and q["triggers"], q["id"])
            self.assertTrue(all(e.get("ref") for e in q["evidence"]), q["id"])
            for b in q["branches"]:
                self.assertEqual(set(b["schedule_effect"]["tco_delta_wd"]), set(G.SCENARIOS), q["id"])
            t = q["value"]["terms"]
            self.assertAlmostEqual(q["value"]["score"], round((t["T"] + t["N"] + t["D"]) * t["U"] * t["G"] * t["C"], 2),
                                   msg=q["id"])
            self.assertEqual(q["value"]["formula"], SQ.VALUE_FORMULA)

    def test_spanish_is_written_not_copied(self):
        q = _find(self.doc, "work:elec_rough_L1")
        self.assertIsNotNone(q, "electrical rough Floor 1 is asked (fast-critical, in the window)")
        self.assertEqual(q["text_en"], "Did electrical rough-in finish on Floor 1, or is part of it still pending?")
        self.assertEqual(q["text_es"], "¿Se terminó la instalación eléctrica en bruto (rough-in) en el piso 1, o todavía "
                                       "falta una parte?")

    def test_the_recipient_is_a_role_never_a_name(self):
        for q in _asked(self.doc):
            self.assertTrue(q["answerer"].split(" (")[0] in SQ.ROLE_SLOTS or "subcontractor" in q["answerer"], q["id"])

    # ── answers: attested at most, don't know is never a no ──

    def test_a_branch_can_only_create_attested_or_dont_know(self):
        for q in _asked(self.doc):
            for b in q["branches"]:
                self.assertIn(b["category"], ("attested", "dont_know"), q["id"])
        with self.assertRaises(ValueError):
            SQ.branch("passed", "passed", "pasó", category="verified")

    def test_dont_know_changes_nothing_and_is_kept_as_dont_know(self):
        q = self.full["work:elec_rough_L1"]
        dk = next(b for b in q["branches"] if b["key"] == "dont_know")
        self.assertEqual(dk["schedule_effect"]["tco_delta_wd"], {s: 0 for s in G.SCENARIOS})
        ans = SQ.read_reply(q, "no sé")
        self.assertEqual(ans["answer"], "dont_know")
        item = SQ.answer_evidence(q, ans, answer_id="a1", person="superintendent", on=TODAY, project_id="p")
        self.assertEqual((item["kind"], item["claim"]), ("attested", "dont_know"))
        self.assertEqual(CQ.facts([item], TODAY), [], "don't know is not a fact, so never a no")

    def test_an_inspection_result_from_a_person_stays_attested(self):
        q = SQ.evaluate(self.ctx, next(g for g in SQ._gate_questions(self.ctx) if g["id"] == "gate:gate_elec_rough"))
        self.assertEqual({s for b in q["branches"] if b["key"] == "passed"
                          for s in b["schedule_effect"]["tco_delta_wd"].values()}, {0},
                         "an unverified pass stays pending in the schedule: the word alone moves nothing")
        passed = next(b for b in q["branches"] if b["key"] == "passed")
        self.assertTrue(passed["verified_when"], "says what would verify it")
        self.assertEqual({v["evidence"] for v in passed["change"]["state"].values()}, {"operator_statement"})
        ans = SQ.read_reply(q, "passed")
        item = SQ.answer_evidence(q, ans, answer_id="a2", person="superintendent", on=TODAY, project_id="p")
        self.assertEqual(item["kind"], "attested")

    # ── the schedule is re-run per branch ──

    def test_a_branch_delta_is_the_generator_rerun(self):
        q = self.full["work:elec_rough_L1"]
        done = next(b for b in q["branches"] if b["key"] == "done")
        st = dict(self.ctx["sched"].state)
        st.update(done["change"]["state"])
        for scn in G.SCENARIOS:
            base = G.schedule_scenario(_net(), self.ctx["sched"].state, ASSUMPTIONS, scn, TODAY)
            alt = G.schedule_scenario(_net(), st, ASSUMPTIONS, scn, TODAY)
            self.assertEqual(done["schedule_effect"]["tco_delta_wd"][scn],
                             alt["tco_working_days"] - base["tco_working_days"], scn)
        self.assertLess(done["schedule_effect"]["tco_delta_wd"]["fast"], 0,
                        "in fast the interior chain is critical: finishing it moves the TCO")

    def test_an_attested_done_is_done_in_the_generator_itself(self):
        """schedule_generator: reported done is done. An answer "done" over an
        open predecessor does not wait for it (the generator, not a local
        patch), and the open predecessor is reported as a contradiction."""
        st = dict(STATE, framing_close_L1=G.state_entry("in_progress", "reported_log", "synthetic log"))
        S = SQ.Rescheduler(_net(), st, ASSUMPTIONS, TODAY)
        done = {"state": {"elec_rough_L1": SQ.stated("done", "finished")}}
        eff = S.effect(done, ["elec_rough_L1"])
        self.assertLess(eff["tco_delta_wd"]["fast"], 0)
        raw = dict(st, elec_rough_L1=done["state"]["elec_rough_L1"])
        self.assertEqual(G.schedule_scenario(_net(), raw, ASSUMPTIONS, "fast", TODAY)["tco_working_days"] -
                         S.base["fast"]["tco_wd"], eff["tco_delta_wd"]["fast"], "the delta is the plain generator's")
        self.assertEqual(eff["contradictions_created"],
                         [{"done": "elec_rough_L1", "open_prerequisite": "framing_close_L1"}])

    def test_a_recorded_done_over_open_work_becomes_a_question_about_the_open_work(self):
        st = dict(STATE, insulation_L1=G.state_entry("done", "operator_statement", "a super said done"))
        ctx = _ctx(sched=SQ.Rescheduler(_net(), st, ASSUMPTIONS, TODAY))
        self.assertEqual([(c["done"], c["open"]) for c in SQ.done_over_open(ctx)], [("insulation_L1", "ptac_sleeves_L1")])
        doc = SQ.generate(ctx)
        q = next(x for x in doc["_asked"] if x["id"] == "work:ptac_sleeves_L1")
        self.assertIn("contradiction", q["triggers"])
        self.assertGreaterEqual(q["value"]["terms"]["D"], 1.0)

    def test_a_question_naming_an_activity_the_network_lost_is_skipped_not_a_crash(self):
        gone = SQ.question("work:eifs_gone", triggers=["unknown_state"], subject="eifs", aspect="state",
                           place="ENVELOPE", text_en="gone?", text_es="¿ya no?", answerers=["superintendent"],
                           topic="progress", why="synthetic", evidence=[SQ.evid("x", "S1", TODAY, "x", "x")],
                           branches=[SQ.branch("done", "yes", "sí",
                                               change={"state": {"eifs_gone": SQ.stated("done", "x")}}),
                                     SQ.dont_know()], activities=["eifs_gone"], gap="unknown", cost="look")
        doc = SQ.generate(_ctx(given=[gone]))
        self.assertEqual(_sup(doc, "work:eifs_gone")["reason"], "activity_missing")

    def test_a_permit_lapse_stops_the_work_under_way_that_needs_it(self):
        q = self.full["permit:2026-11-22"]
        lapse = next(b for b in q["branches"] if b["key"] == "not_yet")
        self.assertIn("eifs_sides", lapse["change"]["holds"], "the facade under way stops at the expiry")
        self.assertGreater(lapse["schedule_effect"]["tco_delta_wd"]["normal"], 0,
                           "the facade is critical in normal: a stoppage moves the finish")

    def test_n_counts_only_crew_work_and_gates_moved_next_week(self):
        q = self.full["work:elec_rough_L1"]
        for b in q["branches"]:
            for m in b["schedule_effect"].get("next_week_crew_moves") or []:
                self.assertIn(self.ctx["sched"].by_id[m["id"]]["kind"], ("work", "inspection_gate"))
                self.assertNotIn(m["id"], q["activities"])
        nw = max(b["schedule_effect"].get("next_week_crew_move_weighted") or 0 for b in q["branches"])
        self.assertEqual(q["value"]["terms"]["N"], round(0.5 * min(20, nw), 2))
        for b in q["branches"]:
            for m in b["schedule_effect"].get("next_week_crew_moves") or []:
                self.assertAlmostEqual(m["weight"], 1 / (1 + max(0, m["min_float_wd"]) / 10), places=3)

    def test_n_ignores_a_far_successor_and_values_next_week_crews(self):
        """The first 588 run ranked "steel stairs started?" (it moves a TR1
        paperwork close-out with months of float) above "did Floor 1 rough-in
        finish?". N now counts only crew work and gates starting next week."""
        far = SQ.evaluate(self.ctx, SQ.work_question(self.ctx, "eifs_sides"))
        moved_far = [b["schedule_effect"]["next_activity"] for b in far["branches"]
                     if (b["schedule_effect"].get("next_activity") or {}).get("move_wd")]
        self.assertTrue(moved_far, "the facade's answer moves its far successor (the TCO gate)")
        self.assertEqual(far["value"]["terms"]["N"], 0, "a far successor is not next week's crew plan")
        near = self.full["work:elec_rough_L1"]
        self.assertGreater(near["value"]["terms"]["N"], 0, "Floor 1 rough-in moves next week's inspection request")

    def test_facade_activities_are_found_by_role(self):
        net = {"activities": [{"id": "eifs_side_known", "family": "eifs"}, {"id": "eifs_side_other", "family": "eifs"},
                              {"id": "eifs_front_rear", "family": "eifs"}, {"id": "brick_veneer", "family": "brick_veneer"},
                              {"id": "eifs_bulkhead", "family": "eifs"}]}
        r = SQ.facade_roles(net)
        self.assertEqual(r["side"], ["eifs_side_known", "eifs_side_other"])
        self.assertEqual((r["front_rear"], r["bulkhead"], r["brick"]), (["eifs_front_rear"], ["eifs_bulkhead"],
                                                                          ["brick_veneer"]))

    def test_a_permit_lapse_is_an_assumed_hold_and_labelled(self):
        q = self.full["permit:2026-11-22"]
        lapse = next(b for b in q["branches"] if b["key"] == "not_yet")
        self.assertIn("q_hold_permit_lapse", lapse["model_update"])
        self.assertEqual(set(lapse["change"]["holds"]["renew_permit_shed"]), set(G.SCENARIOS))

    # ── who is asked, how many ──

    def test_a_permit_question_is_refused_for_the_super_and_goes_to_the_pm_or_admin(self):
        q = _find(self.doc, "permit:2026-11-22")
        self.assertIn(q["recipient"], ("pm", "admin"))
        refused = [r["answerer"] for r in q["refused_roles"]]
        self.assertEqual(refused, ["superintendent"])
        self.assertTrue(q["refused_roles"][0]["refusal"].startswith("REFUSED for their role (superintendent)"))

    def test_at_most_three_a_person_a_day_ranked_by_value(self):
        many = []
        for k in range(8):
            many.append(SQ.question(f"extra:{k}", triggers=["contradiction"], subject=f"s{k}", aspect="state",
                                    place="L1", text_en=f"q{k}?", text_es=f"¿q{k}?", answerers=["superintendent"],
                                    topic="progress", why="synthetic", evidence=[SQ.evid("x", f"S{k}", TODAY, "x", "x")],
                                    branches=[SQ.branch("done", "yes", "sí"), SQ.dont_know()],
                                    activities=["roof_coping"], gap="unknown", cost="look",
                                    decision_weight=float(k + 1)))
        doc = SQ.generate(_ctx(given=many))
        doc.pop("_asked")
        for role, qs in doc["by_person"].items():
            self.assertLessEqual(len(qs), SQ.MAX_PER_PERSON, role)
            self.assertEqual([q["value"]["score"] for q in qs], sorted((q["value"]["score"] for q in qs), reverse=True))
        capped = [s for s in doc["suppressed"] if s["reason"] == "daily_cap"]
        self.assertTrue(capped, "the overflow is shown, with its reason")
        placed = {q["id"] for q in _asked(doc)}
        self.assertIn("extra:7", placed, "the highest-value extra is placed")
        self.assertIn("extra:0", {s["id"] for s in capped}, "the lowest-value extra waits")

    def test_field_roles_are_shadow_only(self):
        for q in _asked(self.doc):
            self.assertTrue(q["delivery"].startswith("SHADOW"), q["id"])
            if q["recipient"] in ("superintendent", "cp"):
                self.assertTrue("never messaged first" in q["delivery"], q["id"])

    # ── suppression, each with its reason ──

    def test_what_a_verified_record_answers_is_not_asked(self):
        s = _sup(self.doc, "work:plumbing_rough_L1")
        self.assertEqual(s["reason"], "answered_by_records")

    def test_what_a_person_already_answered_is_not_asked(self):
        ans = {"kind": "attested", "claim": "done", "node": "rough_electric", "levels": ["FLOOR_1"],
               "on": TODAY - timedelta(days=1), "by": "superintendent", "source": "confirmation_answers", "ref": "x"}
        doc = SQ.generate(_ctx(answers=[ans]))
        self.assertEqual(_sup(doc, "work:elec_rough_L1")["reason"], "answered_by_records")

    def test_a_dont_know_answer_does_not_suppress_the_question(self):
        ans = {"kind": "attested", "claim": "dont_know", "node": "rough_electric", "levels": ["FLOOR_1"],
               "on": TODAY - timedelta(days=1), "by": "superintendent", "source": "confirmation_answers", "ref": "x"}
        doc = SQ.generate(_ctx(answers=[ans]))
        self.assertIsNotNone(_find(doc, "work:elec_rough_L1"))

    def test_redundant_same_subject_aspect_place(self):
        def q(qid, w):
            return SQ.question(qid, triggers=["contradiction"], subject="coping", aspect="binding", place="ROOF",
                               text_en="again?", text_es="¿otra vez?", answerers=["superintendent"], topic="progress",
                               why="synthetic", evidence=[SQ.evid("x", "S1", TODAY, "x", "x")],
                               branches=[SQ.branch("done", "yes", "sí"), SQ.dont_know()], activities=["roof_coping"],
                               gap="unknown", cost="look", decision_weight=w)
        doc = SQ.generate(_ctx(given=[q("dupA", 1.0), q("dupB", 2.0)]))
        self.assertEqual(_sup(doc, "dupA")["reason"], "redundant")
        self.assertNotEqual((_sup(doc, "dupB") or {}).get("reason"), "redundant")

    def test_a_worded_state_question_covers_the_generated_ones_for_its_activities(self):
        worded = SQ.question("worded:elec_L1", triggers=["unknown_state"], subject="elec_rough_worded", aspect="state",
                             place="L1", text_en="worded?", text_es="¿redactada?", answerers=["superintendent"],
                             topic="progress", why="synthetic", evidence=[SQ.evid("x", "S1", TODAY, "x", "x")],
                             branches=[SQ.branch("done", "yes", "sí", change={"state": {
                                 "elec_rough_L1": SQ.stated("done", "x")}}), SQ.dont_know()],
                             activities=["elec_rough_L1"], gap="in_progress", cost="look")
        doc = SQ.generate(_ctx(given=[worded]))
        s = _sup(doc, "work:elec_rough_L1")
        self.assertEqual((s["reason"], s["detail"]), ("redundant", "covered by the worded question worded:elec_L1"))

    def test_one_floor_per_trade_a_day(self):
        def q(fl, w):
            return SQ.question(f"work:trade_{fl}", triggers=["unknown_state"], subject="trade", aspect="state", place=fl,
                               text_en=f"{fl}?", text_es=f"¿{fl}?", answerers=["pm"], topic="progress",
                               why="synthetic", evidence=[SQ.evid("x", "S1", TODAY, "x", "x")],
                               branches=[SQ.branch("done", "yes", "sí"), SQ.dont_know()], activities=["roof_coping"],
                               gap="unknown", cost="look", decision_weight=w)
        doc = SQ.generate(_ctx(given=[q("L1", 2.0), q("L2", 1.0)]))
        s = _sup(doc, "work:trade_L2")
        self.assertEqual(s["reason"], "redundant")
        self.assertTrue(s["detail"].startswith("one floor per trade a day: work:trade_L1"), s["detail"])
        self.assertIsNotNone(_find(doc, "work:trade_L1"))

    def test_an_answer_that_changes_no_decision_is_not_asked(self):
        self.assertEqual(_sup(self.doc, "work:roof_coping")["reason"], "no_decision")

    def test_a_floor_is_narrowed_only_when_it_matters(self):
        s = _sup(self.doc, "work:elec_rough_L2")
        self.assertEqual(s["reason"], "floor_does_not_matter")
        self.assertIsNotNone(_find(self.doc, "work:elec_rough_L1"), "Floor 1 matters in fast and is asked")

    def test_a_deadline_beyond_the_horizon_waits(self):
        self.assertEqual(_sup(self.doc, "permit:2027-01-20")["reason"], "outside_horizon")

    def test_a_test_of_pipe_nobody_recorded_is_not_asked(self):
        self.assertEqual(_sup(self.doc, "gate:gate_sprinkler_hydro")["reason"], "premise_not_established")

    def test_asked_recently_waits(self):
        doc = SQ.generate(_ctx(history=[{"thing": "work:elec_rough_L1", "day": "2026-11-08"}]))
        self.assertEqual(_sup(doc, "work:elec_rough_L1")["reason"], "asked_recently")

    def test_not_permitted_when_no_role_may_answer(self):
        q = SQ.question("approve:seq", triggers=["acceleration_lever"], subject="sequence", aspect="approval",
                        place="SITE", text_en="approve?", text_es="¿aprobar?", answerers=["superintendent", "cp"],
                        topic="schedule_approval", why="synthetic", evidence=[SQ.evid("x", "S1", TODAY, "x", "x")],
                        branches=[SQ.branch("done", "yes", "sí"), SQ.dont_know()], activities=["roof_coping"],
                        gap="unknown", cost="office", decision_weight=2.0)
        doc = SQ.generate(_ctx(given=[q]))
        self.assertEqual(_sup(doc, "approve:seq")["reason"], "not_permitted")

    def test_a_stale_sub_is_a_trigger_on_its_work_and_otherwise_shown(self):
        q = _find(self.doc, "work:lv_rough_L1")
        self.assertIsNotNone(q, "the un-recorded low-voltage sub's Floor 1 rough is asked")
        self.assertIn("stale_sub", q["triggers"])
        self.assertEqual(_sup(self.doc, "stale:GoneCo")["reason"], "no_decision")

    # ── the chain, on the synthetic job ──

    def test_synthetic_chain_question_to_answer_to_attested_item_to_rerun(self):
        """SYNTHETIC chain: progress state -> dependency -> schedule -> question ->
        SIMULATED reply -> fixed-rule reading -> attested item -> the state it
        sets -> the schedule re-run, equal to the branch's own prediction."""
        S = self.ctx["sched"]
        q = self.full["work:elec_rough_L1"]
        self.assertEqual(S.state["elec_rough_L1"]["status"], "in_progress")               # progress
        self.assertIn("gate_elec_rough_L1", S.successors(["elec_rough_L1"]))            # dependency
        self.assertTrue(S.base["fast"]["acts"]["elec_rough_L1"]["critical"])            # schedule
        for reply, key in (("done", "done"), ("todavía no", "not_yet"), ("blocked: no power", "blocked"),
                           ("no sé", "dont_know")):
            ans = SQ.read_reply(q, reply)                                                # SIMULATED reply
            b = SQ.branch_for(q, ans)
            self.assertEqual(b["key"], key, reply)
            item = SQ.answer_evidence(q, ans, answer_id=f"syn-{key}", person="superintendent", on=TODAY,
                                      project_id="p")
            self.assertEqual(item["kind"], "attested", reply)                            # never verified
            eff = S.effect(b["change"], q["activities"]) if b["category"] != "dont_know" else None
            if eff:
                self.assertEqual(eff["tco_delta_wd"], b["schedule_effect"]["tco_delta_wd"], reply)
            else:
                self.assertEqual(b["schedule_effect"]["tco_delta_wd"], {s: 0 for s in G.SCENARIOS})


if __name__ == "__main__":
    unittest.main()
