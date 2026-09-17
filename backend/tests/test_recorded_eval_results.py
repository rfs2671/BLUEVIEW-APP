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

    def test_each_ran_against_the_corpus_its_suite_names(self):
        for path in recorded():
            with self.subTest(result=path.name):
                r = json.loads(path.read_text(encoding="utf-8"))
                suite = ev.load_suite(str(BACKEND / r["suite"]))
                self.assertEqual(r["project"], suite["project"]["id"])
                self.assertEqual(
                    ev.check_baseline(suite["project"]["baseline"], r["corpus_before"]),
                    [])

    def test_the_summary_is_what_the_results_add_up_to(self):
        # Recomputed, not trusted: a hand-edited rate would not survive this.
        for path in recorded():
            with self.subTest(result=path.name):
                r = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(ev.summarise(r["results"]), r["summary"])

    def test_every_case_in_the_suite_was_scored(self):
        for path in recorded():
            with self.subTest(result=path.name):
                r = json.loads(path.read_text(encoding="utf-8"))
                suite = ev.load_suite(str(BACKEND / r["suite"]))
                self.assertEqual({c["id"] for c in suite["cases"]},
                                 {x["id"] for x in r["results"]})

    def test_the_boyland_record_is_the_one_reported(self):
        r = json.loads((RESULTS / "boyland-2026-09-17-d3e80a43.json")
                       .read_text(encoding="utf-8"))
        s = r["summary"]
        self.assertEqual((s["scored"], s["passed"], s["stale"]), (18, 17, 2))
        self.assertEqual(s["failed_in_known_classes"], 1)


if __name__ == "__main__":
    unittest.main()
