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
         _l("eifs_sides", "gate_tco"), _l("roof_coping", "gate_tco"), _l("elec_rough_L1", "elec_rough_L2", "resource")]

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
        q = self.full["gate:gate_elec_rough"]
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

    def test_an_attested_done_does_not_wait_to_start_behind_an_open_predecessor(self):
        """The generator keeps an FS prerequisite binding on anything not in
        progress; an answer "done" means the work is at least under way, so its
        open predecessor bounds its finish (FF), as for started work."""
        st = dict(STATE, framing_close_L1=G.state_entry("in_progress", "reported_log", "synthetic log"))
        S = SQ.Rescheduler(_net(), st, ASSUMPTIONS, TODAY)
        done = {"state": {"elec_rough_L1": SQ.stated("done", "finished")}}
        self.assertLess(S.effect(done, ["elec_rough_L1"])["tco_delta_wd"]["fast"], 0)
        raw = dict(st, elec_rough_L1=done["state"]["elec_rough_L1"])
        self.assertEqual(G.schedule_scenario(_net(), raw, ASSUMPTIONS, "fast", TODAY)["tco_working_days"],
                         S.base["fast"]["tco_wd"], "without the retained logic the answer would move nothing")

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
        dup = SQ.question("dup:elec_L1", triggers=["contradiction"], subject="elec_rough", aspect="state", place="L1",
                          text_en="again?", text_es="¿otra vez?", answerers=["superintendent"], topic="progress",
                          why="synthetic", evidence=[SQ.evid("x", "S1", TODAY, "x", "x")],
                          branches=[SQ.branch("done", "yes", "sí"), SQ.dont_know()], activities=["elec_rough_L1"],
                          gap="unknown", cost="look")
        doc = SQ.generate(_ctx(given=[dup]))
        self.assertEqual(_sup(doc, "dup:elec_L1")["reason"], "redundant")

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
