"""The check that makes auto-approve safe, tested adversarially.

The line sends itself at the admin's daily send time whether or not a human
looked at it. So the question is not "does it pass a good sentence" — it is
"can a bad sentence get through". Every class below is a sentence a language
model plausibly produces and a bank plausibly acts on.

THE FOUR THE OPERATOR NAMED, each its own class:
  a completion claim
  an activity nobody tapped
  a location nobody tapped
  a sentence entirely plausible and entirely invented

A refusal is never nothing: plain_facts goes instead.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib.ai.sub_summary import (  # noqa: E402
    allowed_vocabulary, plain_facts, verify_sentence,
)

# One real subcontractor row, as data.activities[] carries it.
KESTREL = {
    "company": "Kestrel Electric",
    "trade": "Electrical",
    "worker_count": 4,
    "activities": ["branch rough-in", "pull wire"],
    "locations": ["3rd floor"],
    "photo_count": 6,
}


def ok_(sentence, payload=KESTREL):
    return verify_sentence(sentence, payload)[0]


def why(sentence, payload=KESTREL):
    return verify_sentence(sentence, payload)[1]


class ASentenceThatTracesIsAccepted(unittest.TestCase):
    """The control. Without it, everything below would also pass on a checker
    that refused every sentence ever written."""

    def test_the_ordinary_case(self):
        self.assertTrue(ok_("Branch rough-in and pull wire continuing on the 3rd floor."))

    def test_a_subset_of_what_was_tapped(self):
        self.assertTrue(ok_("Pull wire continuing on the 3rd floor."))

    def test_the_company_and_trade_may_be_named(self):
        self.assertTrue(ok_("Kestrel Electric continuing branch rough-in."))

    def test_the_counts_may_NOT_be_named(self):
        """INVERTED DELIBERATELY. This asserted a count could be named, and it
        was the hole: membership cannot tell WHICH fact a number states, so on
        a payload with worker_count 4 and photo_count 6 the sentence "6 workers"
        verified too. Both counts are out of the vocabulary; the crew table
        prints the headcount from the record."""
        self.assertFalse(ok_("4 workers continuing pull wire on the 3rd floor."))
        self.assertFalse(ok_("6 workers continuing pull wire on the 3rd floor."))
        self.assertTrue(ok_("Crew continuing pull wire on the 3rd floor."))

    def test_a_plural_of_a_tapped_label(self):
        """"branch rough-in" -> "rough-ins". The last token is three letters,
        which the depluraliser has to reach without mangling "was"."""
        self.assertTrue(ok_("Branch rough-ins continuing on the 3rd floor."))

    def test_ordinary_grammar_survives(self):
        self.assertTrue(ok_("The crew was working on pull wire at the 3rd floor."))


class ACompletionClaimIsRefused(unittest.TestCase):
    """ADVERSARIAL 1. Precisely what the investor is asking and precisely what
    a tap cannot answer."""

    CLAIMS = [
        "Branch rough-in complete on the 3rd floor.",
        "Pull wire finished on the 3rd floor.",
        "Branch rough-in done; pull wire continuing.",
        "Wrapping up branch rough-in on the 3rd floor.",
        "Final pull wire on the 3rd floor.",
        "Branch rough-in installed on the 3rd floor.",
        "3rd floor closed out for pull wire.",
        "Pull wire ready on the 3rd floor.",
    ]

    def test_none_of_them_send(self):
        for s in self.CLAIMS:
            with self.subTest(sentence=s):
                self.assertFalse(ok_(s))
                self.assertEqual(why(s), "COMPLETION_CLAIM")

    def test_the_claim_is_refused_even_when_every_other_word_traces(self):
        """"complete" is the ONLY untraceable word here — the check must not
        let it through on the strength of the rest of the sentence."""
        self.assertEqual(why("Branch rough-in complete."), "COMPLETION_CLAIM")

    def test_progress_language_is_still_allowed(self):
        for s in ("Branch rough-in continuing.", "Pull wire underway.",
                  "Branch rough-in ongoing on the 3rd floor."):
            with self.subTest(sentence=s):
                self.assertTrue(ok_(s))


class AnUntappedActivityIsRefused(unittest.TestCase):
    """ADVERSARIAL 2. The model naming work that was never logged."""

    def test_a_neighbouring_trade_word(self):
        s = "Branch rough-in and conduit continuing on the 3rd floor."
        self.assertEqual(why(s), "UNTRACED_TERM")
        self.assertIn("conduit", verify_sentence(s, KESTREL)[2])

    def test_a_plausible_next_step(self):
        self.assertEqual(why("Branch rough-in continuing ahead of inspection."),
                         "UNTRACED_TERM")

    def test_a_material_nobody_mentioned(self):
        self.assertEqual(why("Pulling copper on the 3rd floor."), "UNTRACED_TERM")


class AnUntappedLocationIsRefused(unittest.TestCase):
    """ADVERSARIAL 3. The right work, the wrong place."""

    def test_a_different_floor(self):
        s = "Pull wire continuing in the penthouse."
        self.assertEqual(why(s), "UNTRACED_TERM")
        self.assertIn("penthouse", verify_sentence(s, KESTREL)[2])

    def test_a_vaguer_place(self):
        self.assertEqual(why("Pull wire continuing throughout the building."),
                         "UNTRACED_TERM")

    def test_the_tapped_location_is_still_fine(self):
        self.assertTrue(ok_("Pull wire continuing on the 3rd floor."))


class APlausibleInventionIsRefused(unittest.TestCase):
    """ADVERSARIAL 4. The dangerous one: nothing about it reads wrong."""

    INVENTIONS = [
        "Preparing for the pour tomorrow.",
        "Crew mobilised early and made good progress.",
        "Electrical rough-in advancing ahead of schedule.",
        "Kestrel Electric on site as planned.",
        "Work proceeding without issues.",
    ]

    def test_none_of_them_send(self):
        for s in self.INVENTIONS:
            with self.subTest(sentence=s):
                self.assertFalse(ok_(s), f"invented sentence passed: {s}")


class ItFailsClosed(unittest.TestCase):
    def test_an_empty_sentence(self):
        for s in ("", "   ", None, "..."):
            with self.subTest(sentence=repr(s)):
                self.assertFalse(ok_(s))

    def test_a_sentence_of_pure_connectives_says_nothing(self):
        s = "The work is continuing today."
        self.assertEqual(why(s), "NO_CONTENT")

    def test_an_EMPTY_payload_accepts_almost_nothing(self):
        """With nothing tapped there is nothing to say, and the checker must
        not treat an empty input set as permission."""
        empty = {"company": "", "trade": "", "activities": [], "locations": []}
        self.assertFalse(ok_("Branch rough-in continuing.", empty))
        self.assertFalse(ok_("Work continuing on site.", empty))


class TheVocabularyIsClosed(unittest.TestCase):
    def test_it_contains_the_tapped_terms(self):
        vocab = allowed_vocabulary(KESTREL)
        for word in ("kestrel", "electric", "electrical", "branch", "rough",
                     "wire", "pull", "3rd", "floor"):
            self.assertIn(word, vocab, word)
        # "3rd" stays: it is part of a LOCATION the CP tapped. The counts do
        # not, and that is the narrowing -- not every digit, only the numbers
        # nothing can tie to the fact they came from.
        for count in ("4", "6"):
            self.assertNotIn(count, vocab,
                             f"{count} is a payload count and must not be nameable")

    def test_and_nothing_from_a_neighbouring_trade(self):
        vocab = allowed_vocabulary(KESTREL)
        for word in ("drywall", "conduit", "pour", "penthouse", "rebar"):
            self.assertNotIn(word, vocab, word)

    def test_the_connective_list_names_no_work(self):
        """Every word added to _CONNECTIVES is a word the model may use without
        tracing to a tap, so the list must stay grammar and progress only."""
        vocab = allowed_vocabulary({"company": "", "activities": []})
        for word in ("pour", "concrete", "steel", "floor", "roof", "wall",
                     "complete", "inspection", "delivery"):
            self.assertNotIn(word, vocab, f"_CONNECTIVES admits {word!r}")


class TheFallbackIsNeverNothing(unittest.TestCase):
    def test_it_states_the_facts_and_only_the_facts(self):
        line = plain_facts(KESTREL)
        for expected in ("Kestrel Electric", "Electrical", "4",
                         "branch rough-in", "pull wire", "3rd floor"):
            self.assertIn(expected, line, expected)

    def test_it_makes_no_progress_or_completion_claim(self):
        line = plain_facts(KESTREL).lower()
        for banned in ("complete", "finished", "continuing", "underway",
                       "progress", "ahead", "on track"):
            self.assertNotIn(banned, line, banned)

    def test_it_survives_an_empty_row(self):
        self.assertTrue(plain_facts({}).strip())

    def test_the_fallback_traces_entirely_EXCEPT_for_the_number_it_writes(self):
        """THE INVARIANT CHANGED, and the asymmetry is the point.

        This asserted the fallback would itself pass the checker. It no longer
        does, because it states the headcount and the model may not. That is
        not incoherence: the fallback is written BY CODE, from the payload, on
        a fixed line, and cannot transpose two numbers because it never chooses
        between them. The model's numbers were unverifiable; this one is
        guaranteed by construction.

        So the check is narrower and stronger: the fallback may be refused for
        a NUMBER and for nothing else.
        """
        ok, reason, bad = verify_sentence(plain_facts(KESTREL), KESTREL)
        self.assertFalse(ok, "the fallback stopped stating the headcount")
        self.assertEqual(reason, "UNTRACED_TERM")
        self.assertEqual(bad, ["4"], f"the fallback is untraceable beyond the count: {bad}")


class ItIsNotWiredToAnyLogbook(unittest.TestCase):
    """The investor report only. Page 2 is the legal record and the CP signs
    it; this line must never reach it."""

    _RAW = (_BACKEND / "lib" / "ai" / "sub_summary.py").read_text(encoding="utf-8")
    # CODE ONLY. The module's own docstring says "nothing here writes to
    # db.logbooks", and asserting against the raw file matched that sentence
    # instead of the code — the self-referential shape this project has now hit
    # four times. Comments and docstrings describe; only code behaves.
    SRC = re.sub(r'"""[\s\S]*?"""', "", _RAW)
    SRC = chr(10).join(
        l for l in SRC.splitlines() if not l.strip().startswith("#"))

    def test_the_module_touches_no_database(self):
        for banned in ("db.logbooks", "db.", "insert_one", "update_one"):
            self.assertNotIn(banned, self.SRC, banned)

    def test_no_model_result_can_return_without_the_check(self):
        """SUPERSEDES `test_and_makes_no_model_call_yet`, which banned the
        strings "genai" / "generate_content" / "GEMINI" outright.

        That assertion was a SEQUENCING guard and said so — the check ships
        before the call, deliberately — and it held that line until the
        generator landed. It is not the durable invariant, and keeping it would
        have meant deleting a real guard to land the feature it was guarding.

        The durable invariant is the one below: the module may call a model,
        but no model result may reach a caller without passing verify_sentence
        first. Asserted on code with docstrings and comments stripped, so this
        cannot pass by reading the paragraph that describes it.
        """
        body = self.SRC.split("def generate_sentence")[1]
        self.assertIn("generate_content", body, "the call moved out of here")
        self.assertIn("verify_sentence", body, "the generator skips the check")
        # The check must run BEFORE the only success return, not after it.
        self.assertLess(
            body.index("verify_sentence"), body.rindex("return sentence"),
            "verify_sentence runs after the sentence is already returned",
        )


if __name__ == "__main__":
    unittest.main()
