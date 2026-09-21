"""AN ABSENCE NEEDS EVIDENCE THAT THE PLACE IT WOULD BE WAS LOOKED AT.

A number needs a record about its subject — `answer_is_grounded` enforces it.
A refusal passed nothing, and was the only output in this system with no
evidence behind it. This is the warrant.

MEASURED BEFORE BUILDING, on the 27 refusals of the 40-question split: 24 had
a candidate sheet, vision said the content WAS there for 6 of them, and
confirmed absence for 18, at 2,626 input and 6 output tokens per refusal.

THE 18 IS AN UPPER BOUND. Two were checked by rendering the sheet and reading
it, and one of those looked like a vision error until a phrasing probe showed
it was not. One verified case in a sample of two is not an error rate.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_refusal as pr  # noqa: E402


class StrippingIsTheEnforcement(unittest.TestCase):
    """The prompt forbids writing the value. The model writes it anyway —
    measured: asked not to, it answered `YES | 2/27/2025`. A prompt rule is
    an instruction; this is the enforcement."""

    def test_a_value_in_the_location_is_discarded(self):
        v, loc = pr.parse_verdict("YES | 2/27/2025")
        self.assertEqual(v, "yes")
        self.assertEqual(loc, "", "a digit in the location is a value escaping")

    def test_a_clean_location_survives(self):
        v, loc = pr.parse_verdict("YES | schedule top right")
        self.assertEqual((v, loc), ("yes", "schedule top right"))

    def test_a_location_naming_a_schedule_with_a_number_is_dropped(self):
        _v, loc = pr.parse_verdict("YES | PARTITION TYPE 1")
        self.assertEqual(loc, "")

    def test_an_overlong_location_is_dropped(self):
        _v, loc = pr.parse_verdict("YES | " + "x" * 80)
        self.assertEqual(loc, "")

    def test_everything_after_the_first_line_goes(self):
        v, loc = pr.parse_verdict("YES | top right\nThe value is 8 feet.")
        self.assertEqual((v, loc), ("yes", "top right"))


class TheVerdictIsReadStrictly(unittest.TestCase):

    def test_no(self):
        self.assertEqual(pr.parse_verdict("NO")[0], "no")
        self.assertEqual(pr.parse_verdict("- NO")[0], "no")

    def test_anything_unparseable_is_unknown(self):
        """An unknown verdict must not be read as either answer: warranting a
        refusal on a shrug is the failure this exists to stop."""
        for t in ("", "   ", "I think so?", "(http 429)", "MAYBE"):
            self.assertEqual(pr.parse_verdict(t)[0], "unknown", t)


class TheQuestionUsesThePersonsOwnWords(unittest.TestCase):
    """Not the retrieval subject. The subject is the model's paraphrase and
    it is what is being checked for having missed something.

    And the wording decides the verdict: measured on one sheet and one crop,
    the same model answered NO to "when was the architectural set issued" and
    YES to "the drawing date"."""

    def test_the_users_words_reach_the_prompt(self):
        p = pr.check_prompt("how tall is the sidewalk shed")
        self.assertIn("how tall is the sidewalk shed", p)

    def test_the_prompt_forbids_the_value_and_bounds_the_answer(self):
        p = pr.check_prompt("x")
        self.assertIn("do NOT write the value", p)
        self.assertIn("YES", p)
        self.assertIn("NO", p)

    def test_a_sheet_that_only_points_elsewhere_is_a_no(self):
        """S-001.00 mentions piles ten times and states nothing about them."""
        self.assertIn("only", pr.check_prompt("pile details").lower())

    def test_an_empty_question_does_not_produce_an_empty_prompt(self):
        self.assertIn("this", pr.check_prompt(""))


class WhatTheCrewIsTold(unittest.TestCase):

    def test_it_points_somewhere_and_states_nothing(self):
        out = pr.found_but_unreadable("A-101.00", "schedule top right")
        self.assertIn("A-101.00", out)
        self.assertIn("couldn't read it", out)
        for claim in ("do not specify", "does not", "not shown"):
            self.assertNotIn(claim, out.lower())

    def test_the_sheet_comes_from_our_record_not_the_model(self):
        """Only the location phrase is the model's, and only when clean."""
        self.assertIn("A-101.00", pr.found_but_unreadable("A-101.00", ""))
        self.assertEqual(pr.found_but_unreadable("", "somewhere"), "")

    def test_a_page_position_is_not_a_sheet_to_open(self):
        """`1 OF 1` is where a page sits in its file, not which sheet it is.
        MEASURED: it is the top record for "what is the lot size", so as
        written the crew would be told to open a sheet that cannot be opened —
        worse than refusing. Same class as the supersession gap: a page
        position standing in for an identity."""
        self.assertIsNone(pr.candidate_sheet([{"sheet_number": "1 OF 1"}]))
        self.assertIsNone(pr.candidate_sheet([{"sheet_number": "2 of 3"}]))
        self.assertEqual(
            pr.candidate_sheet([{"sheet_number": "1 OF 1"},
                                {"sheet_number": "A-400.00"}]),
            "A-400.00", "skip the page position, keep looking")

    def test_the_candidate_is_the_highest_ranked_record(self):
        recs = [{"sheet_number": ""}, {"sheet_number": "M-200.00"},
                {"sheet_number": "A-101.00"}]
        self.assertEqual(pr.candidate_sheet(recs), "M-200.00")
        self.assertIsNone(pr.candidate_sheet([]))
        self.assertIsNone(pr.candidate_sheet([{"sheet_number": None}]))


class TheOutputIsCapped(unittest.TestCase):

    def test_the_ceiling_is_small(self):
        """It averaged 6 output tokens in measurement. The cap is a ceiling,
        not a target, and it is what stops a value arriving as prose."""
        self.assertLessEqual(pr.MAX_OUTPUT_TOKENS, 60)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
