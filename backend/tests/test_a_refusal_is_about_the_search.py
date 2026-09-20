"""A REFUSAL REPORTS THE SEARCH. IT NEVER CLAIMS WHAT THE DRAWINGS CONTAIN.

"The drawings do not specify the ceiling height" is a claim about the
building, and it was the only output in this system with no evidence behind
it. Every number passes `answer_is_grounded`, which demands a record about its
subject. A refusal passed nothing.

WHAT IT COSTS, measured 2026-09-20. `search_plans("apartment square footage")`
returns ZERO records. A-101.00 prints, and the corpus stores verbatim:

    2A  1 BEDROOM APT.   NET: 482 SQ. FT.   GROSS: 537 SQ. FT.

The relevance floor requires every query term to appear in one record. The
sheet writes `APT.` and `SQ. FT.`; the GC writes "apartment" and "square
footage". Six of eighteen ordinary phrasings return nothing for content that
is extracted, stored, on a live page and correct. Each one was answered with a
claim about the drawings.

A superintendent who opens A-101.00, sees 482 SQ. FT., and remembers being
told the drawings do not state it has learned the tool lies. He is right, and
nothing else it says will be believed afterwards.

── THE DISTINCTION ─────────────────────────────────────────────────────────

    knowable      "I couldn't find that"            a fact about the search
    NOT knowable  "the drawings do not specify it"  a fact about the building

The system can establish the first and cannot establish the second. This file
pins that separation in three places: the words themselves, the instruction
the model is given, and the gate that refuses the claim when the instruction
is ignored.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as ps  # noqa: E402

SRC = (Path(__file__).resolve().parents[1] / "server.py").read_text(
    encoding="utf-8")

#: Every way of asserting absence that is a claim about the building.
ABOUT_THE_DRAWINGS = [
    "The drawings do not specify the ceiling height.",
    "The drawings do not state the ceiling height.",
    "The plans do not show a ceiling height.",
    "The ceiling height is not specified on the drawings.",
    "The sheet does not indicate the ceiling height.",
    "No ceiling height is listed on the drawings.",
]

#: Every way of reporting the search, which is knowable.
ABOUT_THE_SEARCH = [
    "I couldn't find that in the drawings I've indexed.",
    "I couldn't find a ceiling height.",
    "Not found.",
    "No match for that.",
    "Nothing found for ceiling height.",
    "I didn't find a ceiling height.",
]


class TheWordsThemselves(unittest.TestCase):

    def test_the_refusal_does_not_mention_the_drawings_contents(self):
        text = ps.NOT_FOUND.lower()
        for claim in ("do not specify", "does not specify", "do not state",
                      "not shown on", "do not show", "not specified"):
            self.assertNotIn(claim, text, ps.NOT_FOUND)

    def test_it_says_what_it_actually_knows(self):
        self.assertIn("couldn't find", ps.NOT_FOUND.lower())

    def test_nothing_found_still_says_something(self):
        """Silence is not an improvement on a false claim."""
        self.assertTrue(ps.render_records([], "ptac").strip())
        self.assertEqual(ps.render_records([], "ptac"), ps.NOT_FOUND)

    def test_a_named_sheet_is_offered_when_one_can_be_warranted(self):
        self.assertIn("A-101.00", ps.not_found_text("A-101.00"))
        self.assertIn("couldn't find", ps.not_found_text("A-101.00").lower())

    def test_and_no_sheet_is_invented_when_there_is_none(self):
        self.assertEqual(ps.not_found_text(""), ps.NOT_FOUND)
        self.assertEqual(ps.not_found_text("   "), ps.NOT_FOUND)


class TheInstructionTheModelIsGiven(unittest.TestCase):
    """The worst of the sites, because it TOLD the model to make the claim.

    It read: "If no line carries a number, say the drawings do not state it".

    EVERY ASSERTION HERE CARRIES ITS OWN MESSAGE. `SRC` is the whole of
    server.py, and unittest prints the haystack on failure — the first version
    of this file emitted 2.7MB for one wrong literal. The message is also the
    only part a reader of the failure can act on.

    The literals are checked contiguous-in-source: an instruction split across
    adjacent string literals is one string to the model and several to `in`.
    """

    def _present(self, needle, msg):
        self.assertIn(needle, SRC, msg)

    def test_it_no_longer_tells_the_model_to_claim_what_the_drawings_say(self):
        self.assertNotIn(
            "say the drawings do not state it", SRC,
            "the agent instruction still tells the model to assert what the "
            "drawings contain")

    def test_it_forbids_the_claim_explicitly(self):
        self._present(
            "NEVER write that the drawings do not specify",
            "the agent instruction no longer forbids the unwarrantable claim")

    def test_and_says_why_rather_than_only_what(self):
        """A rule a model is told the reason for is followed more often, and
        the reason is the part a future editor needs."""
        self._present(
            "which is a fact about the search and not about the ",
            "the instruction forbids the claim without saying why, which is "
            "what a future editor deletes")


class TheGateRefusesTheClaimWhenTheInstructionIsIgnored(unittest.TestCase):
    """Belt is the instruction. These are the braces.

    `_ABSENCE_RE` used to admit "the drawings do not specify" as an honest
    absence, which is exactly how the claim reached the group: the gate saw an
    absence report and waved it through. Narrowed so that a claim about the
    drawings is treated as an assertion and replaced.
    """

    def gate(self, text, records=(), subject="ceiling height"):
        import server
        return server.gate_plan_answer(text, list(records), subject)

    def test_a_claim_about_the_drawings_is_refused_when_nothing_was_found(self):
        for claim in ABOUT_THE_DRAWINGS:
            sent, outcome = self.gate(claim)
            self.assertEqual(outcome, "no_records_refused", claim)
            self.assertEqual(sent, ps.NOT_FOUND, claim)

    def test_reporting_the_search_is_left_alone(self):
        for honest in ABOUT_THE_SEARCH:
            sent, outcome = self.gate(honest)
            self.assertEqual(outcome, "no_records", honest)
            self.assertEqual(sent, honest, honest)

    def test_a_reply_about_something_else_is_still_left_alone(self):
        """The check must not fire on every sentence that reaches it. A roster
        answer arrives here whenever a plan search ran in the same turn."""
        sent, outcome = self.gate("There are 3 workers on site.", [], "")
        self.assertEqual(outcome, "no_records")
        self.assertIn("3 workers", sent)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
