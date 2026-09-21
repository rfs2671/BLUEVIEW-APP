"""THE CLOSED SET IS THE ERROR CORRECTION, AND IT MUST NOT ABSORB.

Every case below was produced by running this on M-103.00 and M-200.00 of
the Boyland set. The failures are real OCR output, not invented noise, and
the negatives are real text off the same sheet.

Two of these cases were caught by the known-answer test BEFORE the code was
allowed to decide anything, which is the reason they are here rather than in
a post-mortem:

  EF-7        absorbed into EF-1 at edit distance 1 - a tag NOT in the
              schedule being invented into it
  REFRIGERANT normalises to EFR1GERANT, whose EFR+1 is one edit from EF-1,
              so three note fragments snapped to a schedule tag
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_symbols as ps  # noqa: E402
from lib.plan_extract import TIER_REGISTERED_GLYPH  # noqa: E402
from lib.plan_records import TIER_ORDER, tier_rank  # noqa: E402

EF = ("EF-1", "EF-2")


class ARealOcrReadSnapsToTheSchedule(unittest.TestCase):
    """Left column is verbatim OCR output from M-103.00."""

    def test_clean_reads(self):
        for text, want in (("EF-1", "EF-1"), ("EF-2", "EF-2"),
                           ("EF-1(50)", "EF-1"), ("EF-2(100)", "EF-2")):
            self.assertEqual(ps.snap(text, EF)[0], want, text)

    def test_character_confusions_the_drawing_actually_produced(self):
        for text, want in (("6g 40 FF-1(50)", "EF-1"),   # F read for E
                           ("40 EF|1(50)", "EF-1"),      # hyphen read as pipe
                           ("EF-l", "EF-1"),             # letter l for one
                           ("EF-I", "EF-1"),             # capital I for one
                           ("Q EF-2(100)", "EF-2")):
            self.assertEqual(ps.snap(text, EF)[0], want, text)

    def test_a_label_with_something_in_front_of_it(self):
        """`40 EF-1(50)` is a duct size and then the tag. An earlier
        normaliser stripped spaces, glued `40` to `EF`, and the token
        boundary then rejected a perfectly good label."""
        self.assertEqual(ps.snap("40 EF-1(50)", EF)[0], "EF-1")

    def test_spacing_inside_the_tag(self):
        self.assertEqual(ps.snap("EF - 1", EF)[0], "EF-1")
        self.assertEqual(ps.snap("EF1", EF)[0], "EF-1")

    def test_one_prefix_substitution_is_corrected(self):
        self.assertEqual(ps.snap("EP-1", EF)[0], "EF-1")


class WhatMustNotSnap(unittest.TestCase):
    """The absorbing failures. Each of these returning a tag would invent
    schedule membership that the sheet does not print."""

    def test_a_tag_outside_the_closed_set(self):
        """CAUGHT BY THIS TEST BEFORE THE CODE RAN. `EF-7` is one edit from
        EF-1 and is not in the schedule. One substitution in the DIGIT is
        ambiguous between an OCR slip and a different fan; guessing there
        invents a fan."""
        for text in ("EF-7", "EF-3", "EF-9"):
            self.assertIsNone(ps.snap(text, EF)[0], text)

    def test_prose_containing_the_letters(self):
        """Real note text from M-103.00. REFRIGERANT -> EFR1GERANT."""
        for text in ("REFRIGERANT",
                     "EFRIGERANT HOT GAS PIPING LAYOUT AND PIP",
                     "REFRIGERANT LINES ON F ROOF LATION NAS P",
                     "NOTES: OCATION OF EACH HVAC EQU OUTING O"):
            self.assertIsNone(ps.snap(text, EF)[0], text)

    def test_other_equipment_on_the_same_sheet(self):
        for text in ("PTAC-1", "SA-1", "TE 2", "KE", "APT 4D", "WALL", ""):
            self.assertIsNone(ps.snap(text, EF)[0], text)

    def test_a_different_closed_set_changes_the_answer(self):
        """The set is a parameter. PTAC-1 is noise against the fan schedule
        and a hit against the PTAC schedule."""
        self.assertIsNone(ps.snap("PTAC-1", EF)[0])
        self.assertEqual(ps.snap("PTAC-1", ("PTAC-1", "PTAC-3"))[0], "PTAC-1")


class TheClosedSetComesFromTheSchedulesOwnHeaders(unittest.TestCase):
    """Verbatim from M-200.00's EXHAUST FAN SCHEDULE and ROOMS PTAC UNITS
    SCHEDULE, both extracted by the existing pipeline."""

    EF_HEAD = ["TAG", "SERVING", "MANUF.", "MODEL", "CFM", "DRIVE"]
    EF_ROWS = [["EF-1", "APARTMENTS BATHROOMS EXHAUST", "NUTONE", "AEN110",
                "50", "DIRECT"],
               ["EF-2", "APARTMENTS KITCHEN EXHAUST", "BROAN", "BRN503",
                "100", "DIRECT"]]

    def test_the_tag_column_is_found_by_its_printed_header(self):
        tags, corr = ps.closed_set_from_schedule(self.EF_HEAD, self.EF_ROWS)
        self.assertEqual(tags, ["EF-1", "EF-2"])

    def test_the_rating_column_corroborates(self):
        _t, corr = ps.closed_set_from_schedule(self.EF_HEAD, self.EF_ROWS)
        self.assertEqual(corr, {"EF-1": "50", "EF-2": "100"})

    def test_a_schedule_with_no_rating_column_is_supported(self):
        """PTAC's schedule has UNIT NO. | QTY | MAKE | MODEL and no rating.
        The snap then stands on the tag alone - a supported outcome, not a
        degraded one, and the record has to say which it was."""
        head = ["UNIT NO.", "QTY", "MAKE", "MODEL", "ARRANGEMENT"]
        rows = [["PTAC-1", "21", "AMANA", "PTH093K", "WALL"],
                ["PTAC-3", "11", "AMANA", "PTH123K", "WALL"]]
        tags, corr = ps.closed_set_from_schedule(head, rows)
        self.assertEqual(tags, ["PTAC-1", "PTAC-3"])
        self.assertEqual(corr, {})

    def test_a_schedule_with_no_identifier_column_yields_nothing(self):
        """Nothing is inferred from the cells: a column of codes is not a tag
        column unless its printed header says so."""
        tags, corr = ps.closed_set_from_schedule(
            ["DESCRIPTION", "VALUE"], [["EF-1", "50"]])
        self.assertEqual((tags, corr), ([], {}))

    def test_corroborating_role_is_named_once(self):
        self.assertEqual(ps.corroborating_role("CFM"), "rating")
        self.assertEqual(ps.corroborating_role("CAPACITY (KW)"), "rating")
        self.assertIsNone(ps.corroborating_role("SERVING"))
        self.assertIsNone(ps.corroborating_role("MODEL"))


class TheRatingIsPartOfTheSameLabel(unittest.TestCase):
    """`EF-2(100)` carries the tag and the rating. Reading either is reading
    the label. Requiring the tag token and discarding a resolved rating left
    a fan unread over a hyphen misread as `=`."""

    CORR = {"EF-1": "50", "EF-2": "100"}

    def test_the_rating_resolves_when_the_tag_does_not(self):
        self.assertIsNone(ps.snap("EF=2(100) APT", EF)[0])
        self.assertEqual(ps.corroborated_tag(["EF=2(100) APT"], self.CORR),
                         "EF-2")

    def test_an_ambiguous_rating_resolves_to_nothing(self):
        self.assertIsNone(
            ps.corroborated_tag(["EF-1(50) and EF-2(100)"], self.CORR))

    def test_no_rating_column_means_no_corroboration(self):
        self.assertIsNone(ps.corroborated_tag(["PTAC-1"], {}))

    def test_50_inside_100_does_not_corroborate_ef1(self):
        """A digit boundary, or `(100)` would also read as a `50` hit in
        schedules where one rating is a substring of another."""
        self.assertEqual(ps.corroborated_tag(["EF-2(100)"], self.CORR), "EF-2")


class TwoTemplatesClaimingOnePlaceAreOneObject(unittest.TestCase):
    """Suppression used to run WITHIN each template, so a second template
    redetected the first's glyphs 12.5in away and a union counted each fan
    twice - reporting 2 per unit when it had found 1 twice."""

    def test_the_better_score_wins_the_location(self):
        dets = [(0.72, (100.0, 100.0), "t2"), (0.95, (105.0, 100.0), "t1")]
        kept, dropped = ps.dedup(dets, nms_pt=36.0)
        self.assertEqual([k[2] for k in kept], ["t1"])
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0][3], "t1")

    def test_distinct_objects_survive(self):
        dets = [(0.9, (0.0, 0.0), "t1"), (0.9, (500.0, 0.0), "t1")]
        kept, _d = ps.dedup(dets, nms_pt=36.0)
        self.assertEqual(len(kept), 2)

    def test_the_real_double_count(self):
        """The four EF-1 glyphs, each redetected by the EF-2 template 12.5in
        away. Eight detections, four objects."""
        pairs = [(1047.5, 664.0), (1047.5, 798.5), (1639.8, 657.2),
                 (1635.0, 798.5)]
        dets = []
        for x, y in pairs:
            dets.append((0.90, (x, y), "EF-1"))
            dets.append((0.77, (x + 18.75, y + 21.0), "EF-2"))   # ~12.5in
        kept, dropped = ps.dedup(dets, nms_pt=24.0 * 1.5)
        self.assertEqual(len(kept), 4)
        self.assertEqual(len(dropped), 4)
        self.assertTrue(all(d[2] == "EF-2" for d in dropped))


class TheTierSaysHowTheAnswerWasReached(unittest.TestCase):

    def test_it_is_below_printed_text_and_above_free_ocr(self):
        """The sheet never prints "there is an EF-1 in 4A" - that sentence is
        assembled. But the OCR behind it is doubly constrained, by the glyph
        for WHERE and the schedule for WHAT, which free OCR is not."""
        self.assertLess(tier_rank("text_layer"),
                        tier_rank(TIER_REGISTERED_GLYPH))
        self.assertLess(tier_rank(TIER_REGISTERED_GLYPH),
                        tier_rank("ocr_freeform"))
        self.assertLess(tier_rank(TIER_REGISTERED_GLYPH),
                        tier_rank("vision_read"))

    def test_it_is_in_the_order_exactly_once(self):
        self.assertEqual(TIER_ORDER.count(TIER_REGISTERED_GLYPH), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
