"""A REFUSAL SPELLED WITH A SMART APOSTROPHE WAS SCORED AS A CITATION.

Every pattern in this system that spells an English contraction wrote it as
`n[o']?t`, which matches the STRAIGHT apostrophe and nothing else. There were
four such spellings across two files: `_REPLY_REFUSAL` in lib/plan_eval.py and
`_ABSENCE_RE` in server.py.

MEASURED BEFORE THE FIX, on `classify_reply`:

    "I couldn't find that - closest is A-101.00."   ->  refusal
    "I couldn't find that in the drawings."         ->  refusal
    "I couldn[U+2019]t find that - closest is A-101.00."  ->  CITED
    "I couldn[U+2019]t find that in the drawings."        ->  hedge

The `cited` case is the dangerous one, and it is not a new defect: it is the
87.5% defect, unfixed for one spelling of the word. That instrument scored
`Not found. Closest: M-200.00.` as a citation because a refusal naming its
closest sheet satisfies the citation test. The fix anchored a refusal opener
at the front of the reply — and a curly apostrophe walks past the anchor into
the same fallthrough. The door was closed for `couldn't` and left open for
the other spelling.

WHAT IT MEANT FOR THE BASELINE. 30.0% rested on an assumption nobody had
stated: that the agent model types a straight apostrophe. It does, in all 40
replies across all four stored runs — but that is a property of one model's
output on one corpus, not of the instrument. Had the spelling ever changed,
the cited rate would have risen on its own and read as a corpus or ranking
win. A silent upward drift in the number the project steers by, from something
nobody would think to look at.

NORMALISED, NOT WIDENED. Spelling the variants into the character class would
have fixed the sentence we happened to look at and left the next pattern in
the file. One `normalise_quotes` in front of all of them cannot drift out of
step with any of them.

THESE ASSERT THE BUCKET BY NAME. An `assertNotEqual(..., "cited")` would pass
for `hedge` as readily as for `refusal`, and a negative assertion is satisfied
by every wrong value - which is how a test in this very area stayed green
through the defect it was written to catch.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as ps  # noqa: E402
from lib.plan_eval import classify_reply  # noqa: E402

# Built from code points, never pasted. A test about characters that are
# indistinguishable by eye must not contain them as literals - a reviewer
# could not tell STRAIGHT from CURLY below, and neither could a diff.
STRAIGHT = "couldn" + chr(0x27) + "t"
CURLY = "couldn" + chr(0x2019) + "t"
WITH_SHEET = " find that - closest is A-101.00."
NO_SHEET = " find that in the drawings."


class BothSpellingsAreRefusals(unittest.TestCase):

    def test_straight_with_a_sheet(self):
        self.assertEqual(
            classify_reply("I " + STRAIGHT + WITH_SHEET, "no_records"),
            "refusal")

    def test_curly_with_a_sheet(self):
        """THE ONE THAT SCORED CITED. It names a sheet and states no value, so
        once the anchored opener misses it, the citation test takes it."""
        self.assertEqual(
            classify_reply("I " + CURLY + WITH_SHEET, "no_records"),
            "refusal")

    def test_straight_with_no_sheet(self):
        self.assertEqual(
            classify_reply("I " + STRAIGHT + NO_SHEET, "no_records"),
            "refusal")

    def test_curly_with_no_sheet(self):
        """Scored `hedge` before — wrong, but in the harmless direction. Both
        directions are pinned so a partial fix cannot pass."""
        self.assertEqual(
            classify_reply("I " + CURLY + NO_SHEET, "no_records"),
            "refusal")

    def test_the_two_spellings_agree_with_each_other(self):
        """The property, stated once rather than implied by four cases: how
        the apostrophe is typed must not change the bucket."""
        for tail in (WITH_SHEET, NO_SHEET):
            self.assertEqual(
                classify_reply("I " + STRAIGHT + tail, "no_records"),
                classify_reply("I " + CURLY + tail, "no_records"),
                "the spelling changed the bucket")


class TheProductPathToo(unittest.TestCase):
    """`_ABSENCE_RE` in server.py carried the identical spelling, and there the
    consequence is on the crew rather than on a benchmark: an absence that is
    not recognised falls through to the assertion test and can be scored a
    CLAIM about the drawings, then replaced."""

    def setUp(self):
        import server
        self.server = server

    def test_an_absence_is_not_a_claim_in_either_spelling(self):
        for word in (STRAIGHT, CURLY):
            self.assertFalse(
                self.server._asserts_about_the_drawings(
                    "I " + word + " find that on the drawings.", "parapet"),
                "an absence was read as a claim about the drawings")


class NormalisationIsForMatchingOnly(unittest.TestCase):
    """The failure mode of this fix is folding a character in text that gets
    SHOWN. A drawing's dimensions must reach the crew as the sheet prints
    them."""

    def test_an_ascii_dimension_round_trips_unchanged(self):
        dim = "9" + chr(0x27) + "-2" + chr(0x22)
        self.assertEqual(ps.normalise_quotes(dim), dim)

    def test_every_row_of_the_table_folds_to_what_it_claims(self):
        """The table is invisible by eye, so it is asserted by code point."""
        for cp in (0x2018, 0x2019, 0x02BC, 0x02B9, 0x2032, 0x00B4, 0x0060):
            self.assertEqual(ps.normalise_quotes(chr(cp)), chr(0x27),
                             f"U+{cp:04X} did not fold to an apostrophe")
        for cp in (0x201C, 0x201D, 0x2033):
            self.assertEqual(ps.normalise_quotes(chr(cp)), chr(0x22),
                             f"U+{cp:04X} did not fold to a quote")

    def test_it_is_a_pure_function_of_its_argument(self):
        self.assertEqual(ps.normalise_quotes(""), "")
        self.assertEqual(ps.normalise_quotes(None), "")
        plain = "PTAC-1: 21 units [M-200.00]."
        self.assertEqual(ps.normalise_quotes(plain), plain)


class TheThingsThatMustNotHaveMoved(unittest.TestCase):
    """A FIX REPORTS WHAT SHOULD NOT HAVE CHANGED. Normalisation runs in front
    of every branch of the classifier, so every other bucket is exposed to
    it."""

    def test_a_real_citation_is_still_cited(self):
        self.assertEqual(
            classify_reply("PTAC-1: 21 units [M-200.00].", "grounded"),
            "cited")

    def test_a_short_answer_is_still_cited(self):
        """Two words can be a complete answer. Re-deriving the 129-page run
        with a version that required three cost 2.5 points of a baseline."""
        self.assertEqual(
            classify_reply("AMANA PTH093K [M-200.00].", "grounded"), "cited")

    def test_a_fallback_is_still_a_fallback(self):
        self.assertEqual(
            classify_reply("Some replacement text.", "ungrounded"),
            "fallback")

    def test_the_warrants_pointer_is_still_a_refusal(self):
        from lib import plan_refusal
        self.assertEqual(
            classify_reply(plan_refusal.found_but_unreadable("A-101.00"),
                           "refusal_overturned"),
            "refusal")

    def test_an_empty_reply_is_still_a_hedge(self):
        self.assertEqual(classify_reply("", ""), "hedge")


if __name__ == "__main__":
    unittest.main()
