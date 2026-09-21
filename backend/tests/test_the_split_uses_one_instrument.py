"""THE 40-QUESTION SPLIT HAS BEEN MEASURED WITH THREE DIFFERENT INSTRUMENTS.

It is the number this project steers by, and the third instrument was WRONG in
a way that flattered the result. It scored a reply CITED when the text named a
sheet and contained a digit — and a sheet number contains digits. So

    "Not found. Closest: M-200.00."

counted as a citation. Twenty-four refusals were scored as answers and the run
reported 87.5% cited against a known baseline of 20%.

The implausibility is what caught it. Without a prior number to disbelieve,
it would have shipped, and the next arc would have been planned against a
reader that appeared to answer seven questions in eight.

That was the fifth time in one session a PROXY was measured and reported as
the thing: "has a digit" for "states a value", record COUNT for "found the
answer", a regex over extracted text for "what the drawing says", document
frequency for "discriminating power", an unpatched script for "the fix is
applied". So the instrument lives in the library with tests, and changing it
is a visible edit to a tested function rather than a fresh classifier written
at the bottom of a scratch script.

BASELINE, measured with THIS function: cited 30.0%, refusal 65.0%, hedge
2.5%, fallback 2.5% on the 173-page corpus of 2026-09-20. The same questions
on the 129-page corpus — before the combined set's 44 pages were indexed —
re-derive to 27.5% cited, so the corpus is worth +2.5 points.

That run was first reported as 25.0%, from a stored bucket computed by a
version of this function that required three surviving words and scored
`AMANA PTH093K [M-200.00].` a hedge. A bucket in a data file is a reading,
not a measurement: re-derive from the reply text when this function changes.

The earlier "20.0% cited" came from an instrument that no longer exists.
It is history, not a baseline, and so is the 87.5%.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_refusal  # noqa: E402
from lib.plan_eval import classify_reply  # noqa: E402


class ARefusalIsNotACitation(unittest.TestCase):
    """The defect that produced 87.5%."""

    def test_a_refusal_that_names_the_closest_sheet(self):
        """The sheet is a courtesy, not an answer — and it supplies the digits
        that fooled the first classifier."""
        self.assertEqual(
            classify_reply("Not found. Closest: M-200.00.", "grounded"),
            "refusal")

    def test_every_way_the_reader_reports_not_finding(self):
        for text in ("Not found.",
                     "I couldn't find that in the drawings I've indexed.",
                     "I couldn't find that — closest is A-101.00.",
                     "Nothing found for ceiling height.",
                     "No match for that.",
                     "I didn't find a ceiling height."):
            self.assertEqual(classify_reply(text, "grounded"), "refusal", text)


class ACitationStatesAValue(unittest.TestCase):

    def test_a_quantity(self):
        self.assertEqual(
            classify_reply("PTAC-1: 21 units [M-200.00].", "grounded"),
            "cited")

    def test_a_short_answer_is_still_an_answer(self):
        """AMANA PTH093K is two words and a complete answer. An earlier
        version required three and scored it a hedge."""
        self.assertEqual(
            classify_reply("AMANA PTH093K [M-200.00].", "grounded"), "cited")

    def test_a_non_numeric_value(self):
        self.assertEqual(
            classify_reply("Apartment entrance door: Insulated [A-400.00].",
                           "grounded"), "cited")

    def test_a_mark_is_not_a_sheet_number(self):
        """`PTAC-1` must not be stripped as a citation. Without the word
        boundary the sheet pattern matched `TAC-1` inside it, leaving
        "P : 21 units" and turning a citation into a hedge."""
        self.assertEqual(
            classify_reply("PTAC-1: 21 units [M-200.00].", "grounded"),
            "cited")


class APointerIsNotAnAnswer(unittest.TestCase):
    """A hedge is not shorter than an answer — it is made of pointer words."""

    def test_pointing_at_a_sheet_is_a_hedge(self):
        for text in ("See the details on M-200.00.",
                     "Refer to sheet A-400.00 for this.",
                     "[M-200.00]"):
            self.assertEqual(classify_reply(text, "grounded"), "hedge", text)

    def test_an_empty_reply_is_a_hedge_not_a_citation(self):
        self.assertEqual(classify_reply("", "no_records"), "hedge")
        self.assertEqual(classify_reply("   ", "grounded"), "hedge")


class AGateSubstitutionIsItsOwnOutcome(unittest.TestCase):
    """The crew gets facts, but no composed answer — and the text alone
    cannot tell that from an answer, which is why `outcome` is a parameter."""

    def test_a_replaced_answer_is_a_fallback(self):
        self.assertEqual(
            classify_reply("WATER BOOSTER SCHEDULE SYMBOL WBP-1", "ungrounded"),
            "fallback")
        self.assertEqual(
            classify_reply("PTAC-1 [M-200.00] 21 units", "label_leak"),
            "fallback")

    def test_but_a_refusal_is_read_first(self):
        """A gate that refused an empty composition still produced a refusal,
        and calling it a fallback would hide the refusal rate."""
        self.assertEqual(
            classify_reply("I couldn't find that in the drawings I've indexed.",
                           "no_records_refused"), "refusal")


class AnUnusableCitationIsNotACitation(unittest.TestCase):
    """Recorded rather than smoothed over, because it is a real defect
    surfacing in the measurement."""

    def test_a_page_position_is_not_a_sheet(self):
        """`[1 OF 3]` is where the page sits in a file, not which sheet it is.
        The reader emits it for the six current pages that carry no sheet
        number. The VALUE is real and the citation cannot be acted on — a
        superintendent cannot open "1 OF 3" — so it scores as a hedge, and
        that keeps the unnumbered-page gap visible in the split instead of
        being counted as an answer."""
        self.assertEqual(
            classify_reply('2" combined water service [1 OF 3].', "grounded"),
            "hedge")


class TheWarrantMustNotPayTheInstrument(unittest.TestCase):
    """A FEATURE THAT SCORES ITSELF IS WORSE THAN ONE THAT DOES NOT WORK.

    The refusal check replaces a refusal with "It's on A-101.00 — I couldn't
    read it off the sheet". That names a sheet and survives the citation test
    with enough non-pointer words, so it scored CITED: wiring the warrant
    would have appeared to RAISE the answer rate while delivering no value,
    and the benchmark would have rewarded the system for pointing.

    IT SCORES AS A REFUSAL. Every overturned refusal emits this sentence, so
    whichever bucket it lands in becomes the warrant's output bucket — and in
    `hedge` the refusal rate would fall by exactly the overturn count, making
    the headline read as the warrant converting refusals into something
    better. It does not. Nothing was read; the refusal is the same refusal
    with a sheet attached. The feature is counted from the OUTCOME
    (`refusal_overturned`), never from a bucket shrinking."""

    def test_the_pointer_is_a_refusal_not_a_citation(self):
        self.assertEqual(
            classify_reply(plan_refusal.found_but_unreadable(
                "A-101.00", "schedule top right"), "refusal_overturned"),
            "refusal")

    def test_with_no_location_too(self):
        self.assertEqual(
            classify_reply(plan_refusal.found_but_unreadable("A-101.00"),
                           "refusal_overturned"), "refusal")

    def test_the_refusal_rate_cannot_fall_because_the_warrant_fired(self):
        """The property the bucket choice exists to protect, stated as the
        thing that must not move: a run of pure overturns has the same refusal
        count as a run of pure refusals."""
        dark = ["Not found. Closest: A-101.00."] * 5
        lit = [plan_refusal.found_but_unreadable("A-101.00")] * 5
        self.assertEqual(
            sum(1 for r in dark if classify_reply(r, "grounded") == "refusal"),
            sum(1 for r in lit
                if classify_reply(r, "refusal_overturned") == "refusal"))

    def test_a_real_citation_is_untouched(self):
        """THE NUMBER THAT SHOULD NOT MOVE. Measured on all 40 stored replies
        of the split: this branch fires on 0 of them, so every baseline taken
        before it stays comparable."""
        self.assertEqual(
            classify_reply("PTAC-1: 21 units [M-200.00].", "grounded"),
            "cited")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
