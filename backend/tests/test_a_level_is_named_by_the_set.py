"""A level phrase means the level THE SET names, and the answer says so.

2026-10-27: asked about the "5th floor ceiling" on a set whose numbered
floors stop at four with a mezzanine above, the search looked for 5TH, which
no sheet prints. lib.plan_levels maps the phrase to the set's levels (an
ordinal past the top numbered floor is the next level up: the mezzanine if
there is one, else the roof), says the mapping, and returns both candidates
when it is ambiguous. lib.plan_term_senses keeps a word with two
construction meanings from being read as the other one.

Fixtures are invented sheet titles, not any customer's drawings.
"""

from __future__ import annotations

import unittest

from lib import plan_levels as L
from lib import plan_term_senses as T


def _rows(titles, start=100):
    return [{"_id": f"pg{i}", "sheet_number": f"A-{start + i}.00", "sheet_title": t}
            for i, t in enumerate(titles)]


FOUR_AND_MEZZ = _rows(["FIRST FLOOR PLAN", "SECOND FLOOR PLAN", "THIRD FLOOR PLAN",
                       "FOURTH FLOOR PLAN", "MEZZANINE PLAN", "ROOF PLAN"]) + [
    # An elevation lists every level: evidence the levels exist, not the
    # sheet that draws any one of them.
    {"_id": "pgE", "sheet_number": "A-200.00", "sheet_title": "ELEVATIONS",
     "floors": ["FIRST FLOOR", "SECOND FLOOR", "THIRD FLOOR", "FOURTH FLOOR",
                "MEZZANINE", "ROOF"]},
    {"_id": "pgR", "sheet_number": "A-301.00", "sheet_title": "ROOF SECTIONS AND DETAILS"},
]
SIX_FLOORS = _rows(["FIRST FLOOR PLAN", "SECOND FLOOR PLAN", "THIRD FLOOR PLAN",
                    "FOURTH FLOOR PLAN", "FIFTH FLOOR PLAN", "SIXTH FLOOR PLAN",
                    "ROOF PLAN"])


def _one(text, rows, **kw):
    levels = L.set_levels(rows)
    got = L.map_text(text, levels, **kw)
    assert len(got) == 1, got
    return got[0], levels


class TheSetsOwnLevels(unittest.TestCase):
    def test_levels_come_from_the_titles_bottom_to_top(self):
        levels = L.set_levels(FOUR_AND_MEZZ)
        self.assertEqual([lv["token"] for lv in levels],
                         ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "MEZZANINE", "ROOF"])
        mezz = next(lv for lv in levels if lv["token"] == "MEZZANINE")
        self.assertEqual(mezz["sheets"], ["A-104.00"])          # not the elevation
        self.assertEqual(mezz["page_ids"], ["pg4"])


class AnOrdinalPastTheTopIsTheNextLevelUp(unittest.TestCase):
    def test_fifth_floor_on_four_floors_and_a_mezzanine_is_the_mezzanine(self):
        for said in ("spray foam 5th floor ceiling", "fifth floor", "floor 5", "5th fl"):
            with self.subTest(said=said):
                m, levels = _one(said, FOUR_AND_MEZZ)
                self.assertEqual([lv["token"] for lv in m["levels"]], ["MEZZANINE"])
                self.assertEqual(m["how"], "next_up")
                self.assertTrue(m["restate"])
                self.assertEqual(L.describe(m, levels),
                                 "5th floor = Mezzanine (A-104.00) on this set")

    def test_a_floor_argument_needs_no_noun(self):
        m, _ = _one("5", FOUR_AND_MEZZ, field_is_a_level=True)
        self.assertEqual([lv["token"] for lv in m["levels"]], ["MEZZANINE"])

    def test_seventh_floor_on_six_floors_is_the_roof(self):
        m, levels = _one("7th floor", SIX_FLOORS)
        self.assertEqual([lv["token"] for lv in m["levels"]], ["ROOF"])
        self.assertEqual(L.describe(m, levels), "7th floor = Roof (A-106.00) on this set")

    def test_a_floor_the_set_has_is_that_floor_and_is_not_restated(self):
        m, _ = _one("3rd floor", FOUR_AND_MEZZ)
        self.assertEqual(([lv["token"] for lv in m["levels"]], m["how"], m["restate"]),
                         (["FLOOR_3"], "same", False))

    def test_a_level_past_everything_is_said_to_be_absent(self):
        m, levels = _one("9th floor", SIX_FLOORS)
        self.assertEqual((m["levels"], m["how"]), ([], "absent"))
        self.assertTrue(L.describe(m, levels).startswith(
            "9th floor: this set has no level by that name"))


class WhenItCouldBeEither(unittest.TestCase):
    def test_top_floor_over_a_mezzanine_returns_both_and_says_both(self):
        m, levels = _one("top floor ceiling", FOUR_AND_MEZZ)
        self.assertEqual([lv["token"] for lv in m["levels"]], ["MEZZANINE", "FLOOR_4"])
        self.assertEqual(m["how"], "ambiguous")
        self.assertEqual(
            L.describe(m, levels),
            "top floor = Mezzanine (A-104.00) or 4th Floor (A-103.00) on this set"
            " - it could be either; cover both")

    def test_top_floor_with_no_mezzanine_is_the_highest_floor(self):
        m, _ = _one("top floor", SIX_FLOORS)
        self.assertEqual(([lv["token"] for lv in m["levels"]], m["how"]), (["FLOOR_6"], "top"))


class ThePhraseLeavesTheSearchedWords(unittest.TestCase):
    def test_strip(self):
        self.assertEqual(L.strip_phrases("spray foam 5th floor ceiling"), "spray foam ceiling")
        self.assertEqual(L.strip_phrases("spray foam on the fifth floor"), "spray foam")
        self.assertEqual(L.strip_phrases("5th", field_is_a_level=True), "")
        self.assertEqual(L.without_ceiling("spray foam ceiling"), "spray foam")

    def test_words_that_are_not_levels_stay(self):
        self.assertEqual(L.find_phrases("roof details"), [])
        self.assertEqual(L.find_phrases("5 units"), [])

    def test_the_roof_assembly_sheets(self):
        self.assertEqual([r["sheet_number"] for r in L.roof_assembly_sheets(FOUR_AND_MEZZ)],
                         ["A-301.00"])
        self.assertEqual(L.top_occupied(L.set_levels(FOUR_AND_MEZZ)), ["MEZZANINE", "FLOOR_4"])


class TwoMeaningsAreNeverOne(unittest.TestCase):
    def test_kitchen_soffits_are_the_interior_meaning(self):
        r = T.resolve("soffit", "kitchen soffits")
        self.assertEqual(r["meaning"], "interior soffit")
        self.assertIn("'kitchen'", r["why"])

    def test_a_roof_bulkhead_is_the_enclosure_by_context_or_by_level(self):
        self.assertEqual(T.resolve("bulkhead", "stair bulkhead door")["meaning"],
                         "rooftop bulkhead")
        self.assertEqual(T.resolve("bulkhead", "bulkhead", ["ROOF"])["meaning"],
                         "rooftop bulkhead")
        self.assertEqual(T.levels_for(T.resolve("bulkhead", "elevator bulkhead")),
                         ["ROOF", "BULKHEAD"])

    def test_a_ceiling_bulkhead_is_the_drop(self):
        self.assertEqual(T.resolve("bulkhead", "bulkhead at the corridor ceiling")["meaning"],
                         "ceiling bulkhead")

    def test_the_sheets_settle_it_when_the_question_does_not(self):
        recs = [{"quote": "GYP. BD. BULKHEAD BELOW DUCT", "sheet_number": "A-501.00"}]
        r = T.resolve("bulkhead", "bulkheads", records=recs)
        self.assertEqual(r["meaning"], "ceiling bulkhead")
        self.assertIn("A-501.00", r["why"])

    def test_unsettled_covers_each_or_asks(self):
        r = T.resolve("bulkhead", "bulkhead")
        self.assertIsNone(r["meaning"])
        line = T.describe(r)
        self.assertIn("never treat one as the other", line)
        self.assertIn("(a) rooftop bulkhead", line)
        self.assertIn("(b) ceiling bulkhead", line)
        self.assertIn("answer each meaning separately", line)
        # both ways at once is not settled either
        self.assertIsNone(T.resolve("bulkhead", "roof ceiling bulkhead")["meaning"])

    def test_terms_in(self):
        self.assertEqual(T.terms_in("kitchen soffits and pipe chases"), ["soffit", "chase"])
        self.assertEqual(T.terms_in("spray foam ceiling"), [])


if __name__ == "__main__":
    unittest.main()
