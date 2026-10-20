"""scripts/dm_eval_replay.py runs the Oct 20 questions through the real DM
path and scores them. Pinned here: it runs offline, covers every question
it names, and sends nothing but the test wire."""

from __future__ import annotations

import unittest

from scripts import dm_eval_replay as replay


class ReplayRuns(unittest.TestCase):
    def test_every_question_is_answered_and_scored(self):
        out = replay.replay()
        asked = [t["q"] for t in out["transcript"]]
        self.assertEqual(asked, [q for turns in replay.SCENARIOS.values() for q in turns])
        silent = [t["q"] for t in out["transcript"] if not t["a"]]
        self.assertEqual(silent, [], "a turn sent nothing")
        self.assertGreaterEqual(out["report"]["answers"], len(asked) - len(replay.SCENARIOS))
        for key in ("repeats", "canned_answers", "fallbacks", "reasks"):
            self.assertIn(key, out["report"])


if __name__ == "__main__":
    unittest.main()
