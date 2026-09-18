"""A recorded eval result is only a record if the run was valid.

A rate from a corpus that moved during the run, or from a corpus that is not
the one the suite was written for, is a number with nothing behind it. These
checks keep one from being committed as if it were a result.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_eval as ev  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
RESULTS = BACKEND / "eval" / "results"


def recorded():
    return sorted(RESULTS.glob("*.json"))


class EveryRecordedResultIsAValidRun(unittest.TestCase):

    def test_there_is_at_least_one(self):
        self.assertTrue(recorded(), "no recorded results")

    def test_each_was_valid_and_its_corpus_did_not_move(self):
        for path in recorded():
            with self.subTest(result=path.name):
                r = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(r["valid"])
                self.assertEqual(r["corpus_before"], r["corpus_after"])

    def test_each_names_the_project_its_suite_names(self):
        for path in recorded():
            with self.subTest(result=path.name):
                r = json.loads(path.read_text(encoding="utf-8"))
                suite = ev.load_suite(str(BACKEND / r["suite"]))
                self.assertEqual(r["project"], suite["project"]["id"])

    def test_a_result_from_an_earlier_corpus_still_says_which_one(self):
        """THE CORPUS MOVES, AND A RECORD IS A RECORD OF ITS OWN RUN.

        This asserted every recorded result against TODAY'S baseline, which
        held only while the corpus never changed. The re-index of 2026-09-18
        took the project from 15,369 records to 15,536, and three perfectly
        valid records of the old corpus failed a test about the new one.

        What is actually required of an old result is that it says what it ran
        against and that its corpus did not move DURING the run. Whether
        today's suite describes it is a question about the suite, not a fault
        in the record."""
        for path in recorded():
            with self.subTest(result=path.name):
                r = json.loads(path.read_text(encoding="utf-8"))
                for k in ("pages", "current_pages", "records"):
                    self.assertIn(k, r["corpus_before"],
                                  "a result that cannot say what it ran against "
                                  "is not a record of anything")
                self.assertEqual(r["corpus_before"], r["corpus_after"])

    def test_the_summary_is_what_the_results_add_up_to(self):
        # Recomputed, not trusted: a hand-edited rate would not survive this.
        for path in recorded():
            with self.subTest(result=path.name):
                r = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(ev.summarise(r["results"]), r["summary"])

    def test_every_case_the_run_carried_was_scored(self):
        # `suite_cases` is the case set the run itself carried. A result
        # written before that field existed is checked against the suite as it
        # stands, minus cases added since — which is what a subset means here.
        for path in recorded():
            with self.subTest(result=path.name):
                r = json.loads(path.read_text(encoding="utf-8"))
                scored = {x["id"] for x in r["results"]}
                if "suite_cases" in r:
                    self.assertEqual(set(r["suite_cases"]), scored)
                else:
                    current = {c["id"] for c in
                               ev.load_suite(str(BACKEND / r["suite"]))["cases"]}
                    self.assertTrue(scored <= current,
                                    f"scored cases the suite no longer has: "
                                    f"{sorted(scored - current)}")

    def test_the_suite_as_it_stands_has_been_run(self):
        """THE GATE. Cases are added when a failure is observed and the corpus
        changes when it is re-indexed; a suite with a case no recorded run has
        answered, or a baseline no recorded run was measured against, is a
        suite that has not been run.

        BOTH HALVES MATTER. Checking only the case set would let a result from
        the pre-re-index corpus stand in for one from the corpus the suite now
        describes — 15,369 records answering for 15,536."""
        suite = ev.load_suite(str(BACKEND / "eval/boyland.json"))
        current = {c["id"] for c in suite["cases"]}
        baseline = suite["project"]["baseline"]
        covered = []
        for p in recorded():
            r = json.loads(p.read_text(encoding="utf-8"))
            if {x["id"] for x in r["results"]} != current:
                continue
            if ev.check_baseline(baseline, r["corpus_before"]):
                continue
            covered.append(p.name)
        self.assertTrue(covered,
                        "no recorded result covers every case in eval/boyland.json "
                        "against the baseline it names; re-run scripts/plan_eval "
                        "and record it")

    def test_the_boyland_record_is_the_one_reported(self):
        r = json.loads((RESULTS / "boyland-2026-09-17-d3e80a43.json")
                       .read_text(encoding="utf-8"))
        s = r["summary"]
        self.assertEqual((s["scored"], s["passed"], s["stale"]), (18, 17, 2))
        self.assertEqual(s["failed_in_known_classes"], 1)


if __name__ == "__main__":
    unittest.main()
