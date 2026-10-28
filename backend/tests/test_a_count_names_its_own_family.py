"""A COUNT NAMES ITS OWN FAMILY (ruling 71, 2026-10-28).

Measured on production 2026-10-28 (read-only): with the evidence a question
about WH-1 returns (server._glyph_evidence(pid, "WH-1")), the count gate
bound BOTH "There are 9 WH-1." and "There are 9 water heaters." - HEATER is
a word of the WALL ELECTRIC UNIT HEATER SCHEDULE, and one shared word was
all a clause needed to name the family. WH-1 is a wall electric unit
heater, not a water heater.

Ruling 71: "a count binds only if its noun matches the family's own
schedule description or tag (WH-1 = 'wall electric unit heater'; 'water
heater' refuses). Use the schedule title/description text, no hand list."

So every phrase of a clause that holds a family's word or tag must hold
only the family's own words (its schedule's printed name, read in either
number or abbreviated by term_pattern; its tags; a plan-only family's
object, tag words and printed names) - and words a schedule name shares
with every count question (unit, type). "Water heaters", "WH-1 water
heaters", "W1 doors" and "DH-1 water heater" refuse; "WH-1", "wall heaters",
"WH-1 unit heaters", "type B doors", "overflow roof drains" still bind.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as S  # noqa: E402
from tests import test_a_door_is_counted_by_its_tag as D  # noqa: E402
from tests import test_roof_drains_count_per_tag as R  # noqa: E402
from tests import test_two_drawing_tracks as T  # noqa: E402

WH = "WALL ELECTRIC UNIT HEATER SCHEDULE"
DH = "DUCT ELECTRIC HEATER"


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


def _heaters(dh=False):
    """WH-1 as a question about it returns it: 3 on the first floor, placed
    outside the apartments, and its census (schedule QTY 3). With `dh`, the
    duct heater's census too: QTY 1, none located."""
    rows = T._numbered(T._rows("filed", "100", [("WH-1", "non-unit:PUBLIC")] * 3, family=WH))
    pages = sorted({r["page_id"] for r in rows})
    c = T._gc("family", pages, 0, "filed", family=WH, tags=["WH-1"])
    recs = list(rows) + [T._gc("family", pages, sum(S.glyph_in_census(r, c) for r in rows),
                               "filed", family=WH, tags=["WH-1"], qty={"WH-1": "3"}),
                         T._gc("refusals", pages, 0, "filed")]
    if dh:
        recs.append(T._gc("family", pages, 0, "filed", family=DH, tags=["DH-1"],
                          qty={"DH-1": "1"}))
    return recs


class AWaterHeaterIsNotAWallElectricUnitHeater(unittest.TestCase):

    def test_a_wrong_noun_refuses(self):
        recs = _heaters()
        for wrong in ("There are 3 water heaters.", "water heaters: 3.",
                      "There are 3 WH-1 water heaters.", "Water heater WH-1: 3.",
                      "There are 3 WH-1 fans.", "The first floor has 3 water heaters.",
                      "There are 3 WH-1 air conditioners."):
            self.assertFalse(_ok(wrong, recs), wrong)

    def test_its_own_words_and_its_tag_still_bind(self):
        recs = _heaters()
        for right in ("There are 3 WH-1.", "WH-1: 3.", "There are 3 wall heaters.",
                      "There are 3 wall electric unit heaters.", "There are 3 WH-1 heaters.",
                      "There are 3 WH-1 unit heaters.", "There are 3 WH-1 units.",
                      "The first floor has 3 WH-1 wall heaters.", "There are 3 heaters."):
            self.assertTrue(_ok(right, recs), right)

    def test_the_figure_is_still_checked(self):
        recs = _heaters()
        self.assertFalse(_ok("There are 4 WH-1.", recs))
        self.assertFalse(_ok("There are 4 wall heaters.", recs))


class APrintedCountNamesItsOwnThing(unittest.TestCase):
    """The schedule's QTY, which binds where nothing is located (DH-1: QTY
    1, none located) - from the census and from the schedule's own row."""

    SCHED = {"record_type": "schedule", "sheet_number": "M-200.00", "tier": "ocr_grid_cell",
             "project_id": T.PID, "page_id": "pg-m200", "file_name": "MH.pdf", "page_number": 9,
             "quote": "DUCT ELECTRIC HEATER", "payload": {
                 "name": DH, "columns": [{"header": "SYMBOL", "role": "identifier"},
                                         {"header": "QTY", "role": "quantity"}],
                 "rows": [["DH-1", "1"]]}}

    def test_from_the_census(self):
        recs = _heaters(dh=True)
        self.assertTrue(_ok("There is 1 DH-1.", recs))
        self.assertTrue(_ok("There is 1 DH-1 duct heater.", recs))
        self.assertFalse(_ok("There is 1 DH-1 water heater.", recs))

    def test_from_the_schedules_row(self):
        recs = [self.SCHED]
        self.assertTrue(_ok("There is 1 DH-1.", recs))
        self.assertTrue(_ok("There is 1 DH-1 electric heater.", recs))
        self.assertFalse(_ok("There is 1 DH-1 water heater.", recs))


class AWindowIsNotADoor(unittest.TestCase):

    def test_by_its_schedule(self):
        recs = D._world(D._second_floor("filed"), tracks=("filed",))
        self.assertTrue(_ok("The second floor has 8 W1.", recs))
        self.assertTrue(_ok("The second floor has 8 W1 windows.", recs))
        self.assertFalse(_ok("The second floor has 8 W1 doors.", recs))
        self.assertTrue(_ok("The second floor has 4 type B doors.", recs))
        self.assertTrue(_ok("The second floor has 4 type B interior doors.", recs))
        self.assertFalse(_ok("The second floor has 4 type B windows.", recs))


class APlanOnlyFamilyByItsOwnWords(unittest.TestCase):
    """RD-1 / RD-2 (lib.plan_only): its object, its tags' words ('overflow')
    and the names its note prints ('J.R. Smith', 'detention')."""

    def test_its_words_bind_and_another_object_does_not(self):
        recs = R._records()
        for right in ("There are 2 RD-1.", "There are 2 RD-1 roof drains.",
                      "There are 2 overflow roof drains.", "There are 2 overflow drains.",
                      "There are 2 J.R. Smith roof drains."):
            self.assertTrue(_ok(right, recs), right)
        for wrong in ("There are 2 RD-1 floor drains.", "There are 2 RD-2 area drains.",
                      "There are 2 RD-1 water heaters.", "There are 2 overflow area drains."):
            self.assertFalse(_ok(wrong, recs), wrong)


class TheNounIsThePhraseAroundTheFamilysWords(unittest.TestCase):

    def test_foreign_words(self):
        own, f = S._own_text(WH, ["WH-1"]), S.foreign_words
        self.assertEqual(f("There are 9 water heaters on the roof", own), ["water"])
        self.assertEqual(f("There are 9 WH-1 water heaters", own), ["water"])
        self.assertEqual(f("WH-1: 9", own), [])
        self.assertEqual(f("The roof has 3 WH-1 per the filed set", own), [])
        # a sheet or a unit says where, never what
        self.assertEqual(f("WH-1 on A-100.01: 6", own), [])
        self.assertEqual(f("4A has 0 WH-1 units", own), [])
        # a phrase holding none of the family's words is not its noun
        self.assertEqual(f("There are 9 water coolers", own), [])
        # a level word the family's text holds is never its noun's hit ...
        rd = S._own_text("ROOF DRAINS", ["RD-1", "RD-2"],
                         {"object": "roof drain", "tag_words": {"RD-2": ["overflow"]}})
        self.assertEqual(f("The roof level has 2 RD-1", rd), [])
        self.assertEqual(f("There are 2 roof area drains", rd), ["area"])
        # ... and a phrase running straight into its figure ends at its last own word
        self.assertEqual(f("The overflow drains number 2", rd), [])
        self.assertEqual(f("There are 2 overflow drains number", rd), ["number"])


if __name__ == "__main__":
    unittest.main()
