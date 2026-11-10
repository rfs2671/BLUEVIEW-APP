"""THE CHAIN ON REAL DATA: 588 Thomas S. Boyland St, offline.

plans + logs + photos -> location -> activity -> work progress -> dependency
state -> schedule -> question -> SIMULATED answer -> attested item -> the model
re-built with it -> the schedule re-run, for the top 3 questions and every
answer branch.

The real data lives OUTSIDE the repo (env INTEL588_DATA, default
C:/Users/asddd/bv-worktrees/intel588-data) and never enters git, so this test
SKIPS wherever it is absent (CI). It reads files only: no database, no network,
nothing sent. The run takes a few minutes (every branch re-runs the schedule in
three scenarios)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret")

DATA = Path(os.environ.get("INTEL588_DATA", "C:/Users/asddd/bv-worktrees/intel588-data"))
NEEDED = ("records/588_records.jsonl", "drawings/building.json", "model/588_model.json",
          "public/dob_now_inspections_588.json", "public/status_reconciliation.json", "public/588_public_timeline.json")
HAVE = all((DATA / p).exists() for p in NEEDED)


@unittest.skipUnless(HAVE, f"588 real data not present under {DATA} (never committed)")
class Chain588(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import intel_588_questions as Q
        from lib import site_questions as SQ
        cls.Q, cls.SQ = Q, SQ
        cls.doc = Q.run(DATA)
        cls.asked = [q for qs in cls.doc["by_person"].values() for q in qs]

    def test_at_most_three_a_role_a_day_and_role_slots_only(self):
        for role, qs in self.doc["by_person"].items():
            self.assertIn(role, self.SQ.ROLE_SLOTS)
            self.assertLessEqual(len(qs), 3, role)
        self.assertTrue(self.asked, "588 yields questions today")

    def test_what_dob_verified_is_not_asked(self):
        ids = {s["id"]: s["reason"] for s in self.doc["suppressed"]}
        self.assertEqual(ids.get("gate:gate_plumbing_rough:FLOOR_3"), "answered_by_records",
                         "DOB 7755632 passed Floor 3 plumbing rough on 11-05")

    def test_no_permit_question_goes_to_a_field_role(self):
        for q in self.asked:
            if q["topic"] in ("permit", "agency_record", "subcontract"):
                self.assertIn(q["recipient"], ("pm", "admin"), q["id"])

    def test_the_top_three_run_the_whole_chain_for_every_branch(self):
        demo = self.doc["chain_demo"]
        self.assertEqual(len(demo), 3)
        for c in demo:
            t = c["trace"]
            for step in ("plans", "logs_and_photos", "work_progress", "dependency_state", "schedule"):
                self.assertIn(step, t, c["question"])
            self.assertTrue(c["text_en"] and c["text_es"], c["question"])
            for r in c["branches"]:
                self.assertTrue(r["SIMULATED_reply"], c["question"])
                ev = r["evidence_item"]
                self.assertIsNotNone(ev, f"{c['question']} {r['branch']}")
                self.assertEqual(ev["kind"], "attested", f"{c['question']} {r['branch']}: never verified")
                after = str(r["model_cell"]["after"])
                self.assertFalse(after.endswith("_verified") and after != r["model_cell"]["before"],
                                 f"{c['question']} {r['branch']}: an answer cannot make a cell verified")
                self.assertTrue(r["schedule"]["agrees_with_the_question_branch"],
                                f"{c['question']} {r['branch']}: the chain's re-run differs from the branch")

    def test_dont_know_changes_nothing_on_real_data(self):
        for c in self.doc["chain_demo"]:
            dk = [r for r in c["branches"] if r["branch"] == "dont_know"]
            self.assertEqual(len(dk), 1, c["question"])
            r = dk[0]
            self.assertEqual(r["evidence_item"]["claim"], "dont_know")
            self.assertEqual(r["model_cell"]["before"], r["model_cell"]["after"])
            self.assertEqual(set(r["schedule"]["tco_delta_wd"].values()), {0})

    def test_the_report_says_simulated(self):
        text = self.Q.readme(self.doc)
        self.assertTrue("every answer below is SIMULATED" in text, "the report labels its answers")


if __name__ == "__main__":
    unittest.main()
