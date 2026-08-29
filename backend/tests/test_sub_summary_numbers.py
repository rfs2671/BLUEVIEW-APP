"""No number reaches the sentence, and the prompt is generated from the rule.

TWO DEFECTS, ONE EDIT, because they are one defect seen from each side.

THE TRANSPOSITION HOLE. `allowed_vocabulary` admitted `str(worker_count)` and
`str(photo_count)`. The check is TOKEN MEMBERSHIP: it can say a number appears
somewhere in the payload, never that it is being used to state the fact it came
from. On a payload with worker_count 6 and photo_count 4, this PASSED:

    "4 workers continuing formwork and rebar on the 3rd floor"

A verified sentence carrying the wrong headcount to a lender. The two counts
were interchangeable and nothing could tell.

That also settles the digits-versus-number-words question by dissolving it.
Allowing "six" beside "6" would have doubled the surface; removing both closes
it. Nothing is lost: the crew table prints the headcount in its own column,
from the record.

THE PROMPT DRIFTED FROM THE VERIFIER. `worked`, `performed`, `performing` and
`carried out` were added to _CONNECTIVES to fix a real refusal -- a live payload
produced "...worked on site clean-up and material delivery" and came back
UNTRACED_TERM ['worked'] -- and the PROMPT WAS NEVER UPDATED. The model went on
being told not to write the sentences the verifier had just learned to accept.
Fourteen words were undeclared by the time anyone counted.

The prompt's allowance list is now DERIVED from _PERMITTED_CONTENT. That is the
load-bearing change here: not a wording fix, but removing the possibility of
the same bug. A wording fix would have been the third time.

The prompt also handed the model `site`, `gate`, `supervisor` and `Photographs`
-- four words the verifier refuses -- in the very labels describing the facts.
"Workers on site" is the most natural sentence available from a field called
"Workers on site", and it was refused every time.
"""

import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib.ai import sub_summary as m  # noqa: E402

# The exact payload the hole was found on. The two counts differ ON PURPOSE:
# equal counts cannot show a transposition.
ARKON = {
    "company": "Arkon Builders",
    "trade": "Concrete",
    "activities": ["formwork", "rebar"],
    "locations": ["3rd floor"],
    "worker_count": 6,
    "photo_count": 4,
}


class TheTranspositionCase(unittest.TestCase):
    """The finding, asserted with the sentence that produced it."""

    def test_the_wrong_headcount_is_now_refused(self):
        """worker_count is 6. This sentence says 4 -- the PHOTO count -- and it
        passed, because 4 was in the vocabulary and membership is all the
        verifier can check."""
        ok, reason, bad = m.verify_sentence(
            "4 workers continuing formwork and rebar on the 3rd floor", ARKON)
        self.assertFalse(ok, "a sentence stating the photo count as a headcount passed")
        self.assertEqual(reason, "UNTRACED_TERM")
        self.assertIn("4", bad)

    def test_it_is_refused_because_no_number_is_traceable_at_all(self):
        """NOT because 4 is wrong -- the verifier still cannot tell right from
        wrong. It is refused because no number can be traced to the fact it
        came from, so none is admitted. The RIGHT number is refused too, and
        that is the point rather than a side effect."""
        ok, reason, bad = m.verify_sentence(
            "6 workers continuing formwork and rebar", ARKON)
        self.assertFalse(ok)
        self.assertIn("6", bad)

    def test_the_number_word_question_is_dissolved_not_answered(self):
        """Allowing "six" beside "6" would have doubled this surface. Both are
        gone."""
        for spelling in ("Six workers continuing formwork",
                         "six workers continuing formwork"):
            ok, _, bad = m.verify_sentence(spelling, ARKON)
            self.assertFalse(ok)
            self.assertIn("six", bad)

    def test_a_sentence_stating_no_quantity_still_passes(self):
        """The fix must not make every sentence refuse to the fallback."""
        ok, reason, bad = m.verify_sentence(
            "Crew continuing formwork and rebar at the 3rd floor", ARKON)
        self.assertTrue(ok, f"{reason} {bad}")


class NoNumberIsInTheVocabulary(unittest.TestCase):
    def test_neither_count_appears(self):
        vocab = m.allowed_vocabulary(ARKON)
        self.assertNotIn("6", vocab)
        self.assertNotIn("4", vocab)

    def test_not_even_when_a_count_is_zero(self):
        """0 is falsy; the old code guarded on `is not None`, so a zero count
        was admitted too. Nothing here depends on truthiness."""
        vocab = m.allowed_vocabulary(dict(ARKON, worker_count=0, photo_count=0))
        self.assertNotIn("0", vocab)

    def test_a_number_inside_a_tapped_location_is_still_allowed(self):
        """"3rd floor" is a location the CP tapped. The narrowing removes the
        COUNTS, not every character that happens to be a digit -- a location
        the CP chose is exactly the traceable case this module exists to pass."""
        ok, reason, bad = m.verify_sentence(
            "Crew working at the 3rd floor", ARKON)
        self.assertTrue(ok, f"{reason} {bad}")


class ThePromptIsGeneratedFromTheRule(unittest.TestCase):
    """The load-bearing part: the prompt and the verifier say the same thing
    because only one of them is written down."""

    def setUp(self):
        self.prompt = m._prompt_for(ARKON)

    def test_every_permitted_word_is_declared_to_the_model(self):
        declared = set(m._PERMITTED_CONTENT_LINE.replace(",", " ").split())
        self.assertEqual(declared, set(m._PERMITTED_CONTENT))

    def test_the_declaration_reaches_the_rendered_prompt(self):
        for word in sorted(m._PERMITTED_CONTENT):
            self.assertIn(word, self.prompt,
                          f"the model is not told it may use {word!r}")

    def test_the_four_verbs_the_last_fix_added_are_declared(self):
        """The exact drift. These went into the verifier and never into the
        prompt, so the model kept being told not to write what the verifier had
        just been taught to accept."""
        for verb in ("worked", "performed", "performing", "carried"):
            self.assertIn(verb, m._PERMITTED_CONTENT)
            self.assertIn(verb, self.prompt)

    def test_the_allowance_is_not_a_hardcoded_list(self):
        """If the line is retyped in the template, it can drift again. It has
        to arrive through the format placeholder."""
        self.assertIn("{permitted}", m._PROMPT_TEMPLATE)

    def test_the_two_sets_partition_the_vocabulary(self):
        self.assertEqual(m._GRAMMAR | m._PERMITTED_CONTENT, m._CONNECTIVES)
        self.assertEqual(m._GRAMMAR & m._PERMITTED_CONTENT, frozenset())


class ThePromptNamesNoWordTheVerifierRefuses(unittest.TestCase):
    """A prompt must contain instruction words -- "write", "sentence",
    "report" -- and asserting none of them appear would be absurd. What must
    not appear is a JOBSITE NOUN: a word that reads as material for the
    sentence rather than as an instruction about it. Those are the four that
    bit us, and each was in a LABEL describing the facts."""

    FORBIDDEN = ("site", "gate", "supervisor", "superintendent",
                 "photograph", "photographs", "photo", "photos")

    def setUp(self):
        self.prompt = m._prompt_for(ARKON).lower()

    def test_no_jobsite_noun_is_handed_to_the_model(self):
        tokens = set(m._tokens(self.prompt))
        for word in self.FORBIDDEN:
            self.assertNotIn(word, tokens,
                             f"the prompt offers {word!r}, which the verifier refuses")

    def test_none_of_them_would_verify_either(self):
        """The pairing that makes the test above meaningful: these are
        forbidden in the prompt BECAUSE they are refused in a sentence."""
        for word in self.FORBIDDEN:
            ok, _, _ = m.verify_sentence(f"crew {word} today", ARKON)
            self.assertFalse(ok, f"{word} verifies -- it does not belong on this list")

    def test_neither_count_is_shown_to_the_model(self):
        self.assertNotIn("{worker_count}", m._PROMPT_TEMPLATE)
        self.assertNotIn("{photo_count}", m._PROMPT_TEMPLATE)
        self.assertNotIn("6", m._prompt_for(ARKON).split("at most 20 words")[0])

    def test_the_model_is_told_not_to_state_quantities(self):
        self.assertIn("NO QUANTITIES", m._PROMPT_TEMPLATE)
        self.assertIn("THREE ABSOLUTE RULES", m._PROMPT_TEMPLATE)


class TheFallbackStillStatesTheCount(unittest.TestCase):
    """AND THAT IS SAFE, for the reason the model's numbers were not.

    plain_facts is written by code, from the payload, on a fixed line. It
    cannot transpose two numbers because it never chooses between them. It is
    the template-insertion shape already working on the one line that needed
    it -- see the followups entry before reaching for vocabulary again.
    """

    def test_the_headcount_survives_in_the_fallback(self):
        self.assertIn("6 workers", m.plain_facts(ARKON))

    def test_the_fallback_reports_the_worker_count_not_the_photo_count(self):
        """The transposition the model could make, asserted impossible here."""
        line = m.plain_facts(ARKON)
        self.assertIn("6 workers", line)
        self.assertNotIn("4 workers", line)


class NothingElseAboutTheCheckMoved(unittest.TestCase):
    def test_completion_claims_are_still_refused_first(self):
        ok, reason, bad = m.verify_sentence(
            "Crew completed formwork and rebar today", ARKON)
        self.assertFalse(ok)
        self.assertEqual(reason, "COMPLETION_CLAIM")

    def test_an_untraced_noun_is_still_refused(self):
        ok, reason, bad = m.verify_sentence(
            "Crew continuing formwork on the slab", ARKON)
        self.assertFalse(ok)
        self.assertEqual(reason, "UNTRACED_TERM")
        self.assertIn("slab", bad)

    def test_a_sentence_of_pure_connectives_still_says_nothing(self):
        ok, reason, _ = m.verify_sentence("The crew was working today", ARKON)
        self.assertFalse(ok)
        self.assertEqual(reason, "NO_CONTENT")

    def test_an_empty_sentence_still_fails_closed(self):
        ok, reason, _ = m.verify_sentence("", ARKON)
        self.assertFalse(ok)
        self.assertEqual(reason, "EMPTY")

    def test_the_tapped_activities_are_still_traceable(self):
        vocab = m.allowed_vocabulary(ARKON)
        for word in ("formwork", "rebar", "arkon", "concrete", "floor"):
            self.assertIn(word, vocab)


if __name__ == "__main__":
    unittest.main()
