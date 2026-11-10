"""lib/location_binder on real 588 Thomas S. Boyland strings the matcher got
wrong (eval: intel588-data/eval/binder_score.md and the v2 dev split).

THE RULE THESE HOLD: a wrong single-floor claim is the worst outcome. A text
naming several floors is bound to ALL of them or to none; never to a strict
subset. When the reading is uncertain the binder abstains.

588: floors 1-4, mezzanine (at floor 4), roof; no cellar; first floor at grade.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib import evidence_sources as ES  # noqa: E402
from lib import location_binder as B  # noqa: E402
from lib import work_state as W  # noqa: E402

F = ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "MEZZANINE", "ROOF"]
F588 = {"levels": F, "spaces": {}, "ground_level": "FLOOR_1"}
NO_FLAG = {"levels": F, "spaces": {}}
WITH_CELLAR = {"levels": ["CELLAR"] + F, "spaces": {}}


def floors(*ns):
    return [f"FLOOR_{n}" for n in ns]


class EveryFloorTheTextNamesOrNone(unittest.TestCase):
    """Real 588 strings (daily-log location fields and a WhatsApp line)."""

    CASES = (
        ("1-2-3rd floor", floors(1, 2, 3)),
        ("1st/2nd 3rd fl", floors(1, 2, 3)),
        ("1st, 2nd & 3rd floors", floors(1, 2, 3)),
        ("floors 2 thru 4", floors(2, 3, 4)),
        ("2nd and 3rd", floors(2, 3)),
        ("3rd floor and 4th", floors(3, 4)),
        ("3rd fl & 4th", floors(3, 4)),
        ("first and second floor", floors(1, 2)),
        ("1st floor to 4th", floors(1, 2, 3, 4)),
        # Spanish, already read before, must keep working.
        ("pisos 2 y 3", floors(2, 3)),
        ("pisos 1 al 3", floors(1, 2, 3)),
        ("segundo piso", floors(2)),
        # Spanish lists the old code narrowed to the last floor.
        ("segundo y tercer piso", floors(2, 3)),
        ("del primer al tercer piso", floors(1, 2, 3)),
        ("2do piso", floors(2)),
        ("3ro y 4to piso", floors(3, 4)),
    )

    def test_ordinals_that_are_not_a_list_abstain(self):
        # Spaces alone do not join ordinals ("Nov 4th 3rd floor" is a date and
        # a floor); a floor list does not run on into a noun ("2nd coat"). The
        # old code claimed FLOOR_3 for each.
        for text in ("Nov 4th 3rd floor", "2nd 3rd 4th floor", "2nd coat on the 3rd floor", "3rd floor and 2nd coat"):
            r = B.bind(text, F)
            self.assertEqual((r["certainty"], r["reason"]), (B.NONE, B.R_UNREAD), text)
        self.assertEqual(B.bind("2/3", F)["levels"], [])     # a date as often as two floors

    def test_lists_and_ranges(self):
        for text, want in self.CASES:
            r = B.bind(text, F)
            cert = B.EXACT if len(want) == 1 else B.CONSTRAINED
            self.assertEqual((r["certainty"], r["levels"]), (cert, want), text)

    def test_a_progression_abstains_rather_than_narrows(self):
        # "All of the above is for 3rd floor moving up to 4th now": the old
        # code claimed FLOOR_3 alone. Whether the 4th is in the work is not
        # settled by the words, so no floor is claimed.
        for text in ("All of the above is for 3rd floor moving up to 4th now", "3rd floor moving up to 4th"):
            r = B.bind(text, F)
            self.assertEqual((r["certainty"], r["levels"]), (B.NONE, []), text)
            self.assertEqual(r["reason"], B.R_UNREAD, text)
            self.assertEqual(r["candidates"], floors(3, 4), text)

    def test_never_a_strict_subset(self):
        """Every floor number the text names as an ordinal is in the answer,
        or there is no answer."""
        import re
        texts = [t for t, _ in self.CASES] + ["3rd floor moving up to 4th", "2nd coat on the 3rd floor",
                                              "1st-2nd fl, 3rd", "1/2/3rd floor", "Floors 1st 2nd 3rd"]
        for t in texts:
            r = B.bind(t, F)
            named = {f"FLOOR_{int(n)}" for n in re.findall(r"(\d{1,2})\s*(?:st|nd|rd|th)\b", t, re.I)}
            if r["certainty"] != B.NONE:
                self.assertFalse(named - set(r["levels"]), (t, r["levels"]))


class GroundFloorIsFirstOnlyWhenTheFrameSaysSo(unittest.TestCase):
    def test_588_frame_maps_ground_floor(self):
        for text in ("Ground floor", "Ground Floor", "planta baja", "ground fl"):
            r = B.place(text, F588)
            self.assertEqual(r["levels"], floors(1), text)
            b = B.bind(text, F, ground_level="FLOOR_1")
            self.assertEqual((b["certainty"], b["levels"], b["reason"]), (B.EXACT, floors(1), B.R_GROUND), text)

    def test_ground_level_and_grade_are_not_mapped(self):
        # "Ground level" / "grade" name the site as often as the floor (the
        # labels call "Ground level" ambiguous): never placed on floor 1.
        for text in ("Ground level", "grade", "at grade", "Foundation grade"):
            self.assertEqual(B.place(text, F588)["levels"], [], text)

    def test_no_flag_keeps_abstaining(self):
        r = B.bind("Ground floor", F)
        self.assertEqual((r["certainty"], r["reason"]), (B.NONE, B.R_NOT_IN_PROJECT))
        self.assertEqual(B.place("Ground floor", NO_FLAG)["levels"], [])

    def test_a_project_with_a_cellar_keeps_abstaining(self):
        self.assertEqual(B.place("Ground floor", WITH_CELLAR)["levels"], [])
        # A flag that names a level the frame lacks maps nothing.
        self.assertEqual(B.bind("Ground floor", F, ground_level="FLOOR_0")["levels"], [])

    def test_a_frame_with_its_own_ground_level_is_unchanged(self):
        self.assertEqual(B.bind("Ground Floor", F + ["GROUND"], ground_level="FLOOR_1")["levels"], ["GROUND"])

    def test_frame_from_sets_the_flag_only_on_explicit_facts(self):
        at_grade = {"building_stories": 4, "has_cellar": False, "has_sub_cellar": False, "first_floor_at_grade": True}
        f = B.frame_from(at_grade)
        self.assertEqual(f["ground_level"], "FLOOR_1")
        self.assertEqual(f["ground_basis"], ["has_cellar=False", "has_sub_cellar=False", "first_floor_at_grade"])
        self.assertNotIn("GROUND", f["levels"])       # a mapping, not a level of its own
        for change in ({"has_cellar": True}, {"has_cellar": None}, {"has_sub_cellar": None},
                       {"first_floor_at_grade": None}, {"first_floor_at_grade": False}):
            self.assertIsNone(B.frame_from({**at_grade, **change})["ground_level"], change)
        # A cellar the plan sheets name overrides a missing has_cellar flag.
        pages = [{"sheet_number": "A-100", "sheet_title": "CELLAR PLAN"}]
        self.assertIsNone(B.frame_from(at_grade, pages)["ground_level"])

    def test_places_in_carries_it(self):
        self.assertEqual(W.places_in("Ground floor", F588)["levels"], floors(1))
        self.assertEqual(W.places_in("Ground floor", NO_FLAG)["levels"], [])

    def test_dob_ground_floor(self):
        # DOB "Work on Floor(s)" is read by evidence_sources.dob_levels and held
        # against the frame by bind_levels, not by location_binder.bind.
        self.assertEqual(ES.dob_levels("Ground Floor"), ["GROUND"])
        self.assertEqual(ES.bind_levels(ES.dob_levels("Ground Floor"), F588)[0], floors(1))
        kept, cands, _note = ES.bind_levels(ES.dob_levels("Ground Floor"), NO_FLAG)
        self.assertEqual((kept, cands), ([], ["GROUND"]))


HEADLINE = "HEADLINE: Framers on the 3rd–4th floors, Plumber on the 1st–4th, HVAC / Mechanical on the 1st–2nd."


class SeveralTradesOnSeveralFloors(unittest.TestCase):
    """The 588 report headline. The record export turned its en dashes into
    U+FFFD; the engine's own text has the dash, which is what is tested here."""

    def test_the_whole_sentence_abstains(self):
        # The union (every trade on floors 1-4) would put framers on floor 1.
        r = B.bind(HEADLINE, F)
        self.assertEqual((r["certainty"], r["levels"], r["reason"]), (B.NONE, [], B.R_TRADES))
        self.assertEqual(B.place(HEADLINE, F588)["levels"], [])

    def test_each_clause_is_bound(self):
        got = [(c["trade_text"], c["levels"], c["certainty"]) for c in B.bind_clauses(HEADLINE, F588)]
        self.assertEqual(got, [("Framers", floors(3, 4), B.CONSTRAINED),
                               ("Plumber", floors(1, 2, 3, 4), B.CONSTRAINED),
                               ("HVAC / Mechanical", floors(1, 2), B.CONSTRAINED)])

    def test_one_trade_per_floor(self):
        got = [(c["trade_text"], c["levels"]) for c in B.bind_clauses("Framing 3rd floor; plumbing 1st floor", F588)]
        self.assertEqual(got, [("Framing", floors(3)), ("plumbing", floors(1))])
        self.assertEqual(B.bind("Framing 3rd floor; plumbing 1st floor", F)["reason"], B.R_TRADES)

    def test_one_place_with_several_trades_is_not_split(self):
        for text, want in (("Framers and plumbers on the 3rd floor", floors(3)),
                           ("Framing 3rd floor, plumbing 3rd floor", floors(3)),
                           ("1st, 2nd & 3rd floors", floors(1, 2, 3)),
                           ("2nd-3rd floor, Roof protection", floors(2, 3) + ["ROOF"])):
            self.assertEqual(B.bind(text, F)["levels"], want, text)

    def test_a_clause_with_no_place(self):
        cl = B.bind_clauses("Framers on the 3rd floor, cleanup crew", F588)
        self.assertEqual([(c["trade_text"], c["levels"], c["certainty"]) for c in cl],
                         [("Framers", floors(3), B.EXACT), ("cleanup crew", [], B.NONE)])

    def test_the_exported_headline_with_its_dashes_lost(self):
        # The record export holds U+FFFD where the en dash was. "1st?4th" is a
        # span or a list; read either way it could narrow, so nothing is read.
        garbled = HEADLINE.replace("–", "�")
        r = B.bind(garbled, F)
        self.assertEqual((r["certainty"], r["levels"]), (B.NONE, []))
        self.assertTrue(all(c["certainty"] == B.NONE for c in B.bind_clauses(garbled, F588)))

    def test_a_daily_report_paragraph(self):
        text = ("Arkon Builders (13) worked on framing (layout, track and studs) on the 3rd and 4th floors. "
                "Quality Plumbing (5) worked on MEP rough-in, Plumbing on the 1st through 4th floors. "
                "BreezCo (4) worked on ductwork rough, Duct work on the 1st and 2nd floors. "
                "The toolbox talk at 8:00 AM had 22 attendees.")
        self.assertEqual(B.bind(text, F)["reason"], B.R_TRADES)
        placed = [(c["levels"], c["certainty"]) for c in B.bind_clauses(text, F588)]
        self.assertEqual(placed, [(floors(3, 4), B.CONSTRAINED), (floors(1, 2, 3, 4), B.CONSTRAINED),
                                  (floors(1, 2), B.CONSTRAINED), ([], B.NONE)])
        self.assertIn("framing", B.bind_clauses(text, F588)[0]["trade_text"])

    def test_no_frame(self):
        self.assertTrue(all(c["certainty"] == B.NONE for c in B.bind_clauses(HEADLINE, {"levels": []})))


if __name__ == "__main__":
    unittest.main()
