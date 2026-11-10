"""lib/project_timeline.py: what LeveLog would have believed on a day.

SYNTHETIC fixtures only (made-up building, subs, refs, dates).
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import evidence as E  # noqa: E402
from lib import project_timeline as T  # noqa: E402
from tests.test_construction_inference import MODEL, PID, photo, rep  # noqa: E402


def d(m, day):
    return date(2026, m, day)


ROWS = [rep("L1", "rough_plumbing", ["FLOOR_1", "FLOOR_2"], d(2, 1)),
        photo("P1", "rough_plumbing", ["FLOOR_2"], d(2, 5)),
        rep("L2", "insulation", ["FLOOR_1", "FLOOR_2"], d(2, 10), sub="Insul Co"),
        E.item("reported", "present", source="checkins", ref="C1", project_id=PID, sub="Plumber Co", on=d(2, 1))]


class Visible(unittest.TestCase):

    def test_only_what_was_on_record(self):
        late_said = E.item("attested", "done", source="whatsapp", ref="W1", project_id=PID, node="framing",
                           levels=["FLOOR_1"], on=d(1, 1), said_at=datetime(2026, 3, 1, 9, 0))
        undated = E.item("reported", "in_progress", source="logbooks", ref="X", project_id=PID)
        got = {i["ref"] for i in T.visible(ROWS + [late_said, undated], d(2, 5))}
        self.assertEqual(got, {"L1", "P1", "C1"})


class AsOf(unittest.TestCase):

    def test_hindsight_never_improves_an_earlier_day(self):
        early = T.as_of(ROWS, MODEL, d(2, 6), project_id=PID)
        late = T.as_of(ROWS, MODEL, d(2, 11), project_id=PID)
        self.assertEqual(early["levels"]["FLOOR_2"]["systems"]["plumbing"]["state"], "inferred_in_progress_medium")
        self.assertEqual(late["levels"]["FLOOR_2"]["systems"]["plumbing"]["state"], "inferred_done_high")
        self.assertEqual(early["levels"]["MEZZANINE"]["systems"]["plumbing"]["state"], "unknown")

    def test_a_cell_says_what_the_facts_say(self):
        snap = T.as_of(ROWS, MODEL, d(2, 11), project_id=PID)
        cell = snap["levels"]["FLOOR_1"]["work"]["rough_plumbing"]
        self.assertEqual((cell["status"], cell["shared_only"], cell["refs"]), ("reported", True, ["L1"]))

    def test_sub_current_activity(self):
        snap = T.as_of(ROWS, MODEL, d(2, 11), project_id=PID)
        self.assertTrue(snap["subs"]["Insul Co"]["current_activity_determinable"])
        self.assertEqual(snap["subs"]["Insul Co"]["current_activity"]["nodes"], ["insulation"])
        self.assertEqual(snap["subs"]["Plumber Co"]["gate_days"], 1)
        far = T.as_of(ROWS, MODEL, d(4, 1), project_id=PID)
        self.assertFalse(far["subs"]["Plumber Co"]["current_activity_determinable"])
        self.assertIn("more than 14 days", far["subs"]["Plumber Co"]["why_not"])

    def test_weekly_snapshots_end_on_the_end_day(self):
        snaps = T.weekly(ROWS, MODEL, d(2, 1), d(2, 20), project_id=PID)
        self.assertEqual([s["as_of"] for s in snaps], ["2026-02-01", "2026-02-08", "2026-02-15", "2026-02-20"])
        self.assertNotIn("_facts", T.public(snaps[-1]))


if __name__ == "__main__":
    unittest.main()
