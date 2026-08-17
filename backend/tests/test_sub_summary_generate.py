"""The generator, and the one thing that must be true of it.

test_sub_summary_verifier.py proves the CHECK holds against sentences a model
plausibly writes. This file proves the GENERATOR cannot get around it: that
there is no input, no response shape and no failure mode which causes an
unverified string to come back out of lib/ai/sub_summary.

The SDK is mocked at module level (lib.ai.sub_summary.genai), and
GEMINI_API_KEY is patched per test, exactly as tests/test_pr48_phase_inference
.py does it. No real API call fires from this suite.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import lib.ai.sub_summary as SS  # noqa: E402

# The same real row the verifier suite uses, so a sentence that passes there
# passes here and the two files cannot drift into disagreeing about the input.
KESTREL = {
    "company": "Kestrel Electric",
    "trade": "Electrical",
    "worker_count": 4,
    "activities": ["branch rough-in", "pull wire"],
    "locations": ["3rd floor"],
    "photo_count": 6,
}

GOOD = "Branch rough-in and pull wire continuing on the 3rd floor."


def _patch_gemini(json_text=None, raise_exc=None):
    """A stand-in genai module whose Client().models.generate_content returns a
    response with `.text`, or raises. Mirrors the phase_inference harness."""
    fake_client = mock.MagicMock()
    if raise_exc is not None:
        fake_client.models.generate_content.side_effect = raise_exc
    else:
        response = mock.MagicMock()
        response.text = json_text
        fake_client.models.generate_content.return_value = response
    fake_genai = mock.MagicMock()
    fake_genai.Client.return_value = fake_client
    return fake_genai, fake_client


def _generate(json_text=None, raise_exc=None, payload=KESTREL, key="fake-key"):
    fake_genai, fake_client = _patch_gemini(json_text, raise_exc)
    with mock.patch.object(SS, "GEMINI_API_KEY", key), \
         mock.patch.object(SS, "genai", fake_genai):
        return SS.generate_sentence(payload), fake_client


class AGoodSentenceComesBack(unittest.TestCase):
    """The control. Without it every test below would also pass on a generator
    that returned None unconditionally."""

    def test_a_sentence_that_traces_is_returned(self):
        got, _ = _generate(json_text='{"sentence": "%s"}' % GOOD)
        self.assertEqual(got, GOOD)


class TheCheckIsNotOptional(unittest.TestCase):
    """The whole point of the file. Each of these is a sentence the model
    returned successfully — well-formed JSON, no exception, nothing to log as a
    failure — and each must still be refused."""

    def test_a_completion_claim_is_refused(self):
        got, _ = _generate(
            json_text='{"sentence": "Branch rough-in complete on the 3rd floor."}')
        self.assertIsNone(got)

    def test_an_activity_nobody_tapped_is_refused(self):
        got, _ = _generate(
            json_text='{"sentence": "Panel schedule continuing on the 3rd floor."}')
        self.assertIsNone(got)

    def test_a_location_nobody_tapped_is_refused(self):
        got, _ = _generate(
            json_text='{"sentence": "Pull wire continuing in the basement."}')
        self.assertIsNone(got)

    def test_a_plausible_invention_is_refused(self):
        # Reads like a site report and is entirely made up. The class the
        # operator named, and the reason the check exists.
        got, _ = _generate(json_text=(
            '{"sentence": "Crew continuing ahead of schedule with no delays '
            'reported."}'))
        self.assertIsNone(got)

    def test_an_empty_sentence_is_refused(self):
        got, _ = _generate(json_text='{"sentence": ""}')
        self.assertIsNone(got)

    def test_a_missing_sentence_key_is_refused(self):
        got, _ = _generate(json_text='{"reasoning": "I could not comply."}')
        self.assertIsNone(got)


class AFailedSentenceIsNotRetried(unittest.TestCase):
    """A refusal is final. Re-asking a temperature-0 model the same question is
    the same question and a second charge."""

    def test_exactly_one_call_on_refusal(self):
        _, client = _generate(
            json_text='{"sentence": "Everything finished on the 3rd floor."}')
        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_exactly_one_call_on_success(self):
        _, client = _generate(json_text='{"sentence": "%s"}' % GOOD)
        self.assertEqual(client.models.generate_content.call_count, 1)


class TheCallFailsSoftly(unittest.TestCase):
    """A report is generated for a whole project. One row's model failure must
    never take the page down — it degrades that row and nothing else."""

    def test_no_api_key_returns_none_without_calling(self):
        fake_genai, fake_client = _patch_gemini(json_text='{"sentence": "x"}')
        with mock.patch.object(SS, "GEMINI_API_KEY", ""), \
             mock.patch.object(SS, "genai", fake_genai):
            self.assertIsNone(SS.generate_sentence(KESTREL))
        fake_client.models.generate_content.assert_not_called()

    def test_an_exception_returns_none(self):
        got, _ = _generate(raise_exc=RuntimeError("boom"))
        self.assertIsNone(got)

    def test_unparseable_json_returns_none(self):
        got, _ = _generate(json_text="not json at all")
        self.assertIsNone(got)

    def test_a_none_response_body_returns_none(self):
        got, _ = _generate(json_text=None)
        self.assertIsNone(got)


class TheCallIsShapedLikePhaseInference(unittest.TestCase):
    """The second AI surface must not fail in a second way. These assert the
    config the other one already proved in production."""

    def test_temperature_is_zero_and_the_schema_is_bound(self):
        _, client = _generate(json_text='{"sentence": "%s"}' % GOOD)
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.temperature, 0)
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(config.response_schema, SS.SENTENCE_RESPONSE_SCHEMA)


class ThePromptCarriesTheClosedInputSetAndNothingElse(unittest.TestCase):
    """The model may not be handed a fact the CP did not record. If a field
    reaches the prompt that is not in the payload, the check downstream becomes
    the only guard and almost every line falls back."""

    def _prompt_for(self, payload=KESTREL):
        _, client = _generate(
            json_text='{"sentence": "%s"}' % GOOD, payload=payload)
        return client.models.generate_content.call_args.kwargs["contents"]

    def test_every_input_appears(self):
        prompt = self._prompt_for()
        for fragment in ("Kestrel Electric", "Electrical", "4",
                         "branch rough-in", "pull wire", "3rd floor", "6"):
            self.assertIn(fragment, prompt)

    def test_the_two_rules_are_stated(self):
        prompt = self._prompt_for()
        self.assertIn("NO NEW NOUNS", prompt)
        self.assertIn("NO COMPLETION CLAIMS", prompt)

    def test_an_empty_field_is_named_not_omitted(self):
        # A prompt with a missing line invites the model to fill the gap.
        prompt = self._prompt_for({**KESTREL, "locations": [], "trade": ""})
        self.assertIn("(none recorded)", prompt)
        self.assertIn("(not recorded)", prompt)


class AnEmptyRowCannotProduceASentence(unittest.TestCase):
    """A row with nothing tapped has nothing to say, and the sentence that
    would 'summarise' it would be entirely invention."""

    def test_a_bare_row_refuses_whatever_comes_back(self):
        bare = {"company": "Kestrel Electric", "trade": "", "worker_count": None,
                "activities": [], "locations": [], "photo_count": 0}
        got, _ = _generate(
            json_text='{"sentence": "Work continuing on site today."}',
            payload=bare)
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()


class TestActivityVerbsTraceWithoutClaimingCompletion(unittest.TestCase):
    """THE VERIFIER WAS REFUSING ON VERBS, not on nouns.

    `working` was allowed and `worked` was not — the past tense of a word
    already in the list — so the most natural sentence about tapped chips came
    back UNTRACED_TERM ['worked']. That is literalism, not a guard.

    The tokenizer was NOT the defect, and this is worth recording because it was
    the first hypothesis: the allowed vocabulary is built by the SAME _tokens
    call as the sentence, so splitting "MEP rough-in" into mep/rough/in makes
    those words allowed. Splitting is permissive, not restrictive.
    """

    PAYLOAD = {
        "company": "Air Star Mechanical",
        "trade": "HVAC / Mechanical",
        "worker_count": 3,
        "activities": ["Sleeves and penetrations", "site clean-up",
                       "material delivery", "MEP rough-in"],
        "locations": ["1 floor"],
        "photo_count": 2,
    }

    def test_the_tokenizer_was_never_the_defect(self):
        from lib.ai.sub_summary import allowed_vocabulary, verify_sentence
        self.assertIn("mep", allowed_vocabulary(self.PAYLOAD))
        ok, reason, _ = verify_sentence(
            "Air Star Mechanical had 3 workers on MEP rough-in on 1 floor.",
            self.PAYLOAD)
        self.assertTrue(ok, reason)

    def test_activity_verbs_now_trace(self):
        from lib.ai.sub_summary import verify_sentence
        for sentence in (
            "Air Star Mechanical worked on site clean-up and material delivery.",
            "Air Star Mechanical carried out MEP rough-in on 1 floor.",
            "Air Star Mechanical performed sleeves and penetrations.",
        ):
            with self.subTest(sentence=sentence):
                ok, reason, offending = verify_sentence(sentence, self.PAYLOAD)
                self.assertTrue(ok, f"{reason} {offending}")

    def test_completion_claims_still_refuse(self):
        """The half that protects the record, untouched."""
        from lib.ai.sub_summary import verify_sentence
        for sentence, term in (
            ("Air Star Mechanical completed MEP rough-in.", "completed"),
            ("Air Star Mechanical installed ductwork on 1 floor.", "installed"),
            ("Air Star Mechanical finished site clean-up.", "finished"),
        ):
            with self.subTest(sentence=sentence):
                ok, reason, offending = verify_sentence(sentence, self.PAYLOAD)
                self.assertFalse(ok)
                self.assertEqual(reason, "COMPLETION_CLAIM")
                self.assertIn(term, offending)

    def test_loosening_the_verbs_did_not_loosen_the_trace(self):
        """The point of the whole module: a NOUN nobody tapped is still refused.
        If this ever passes, the guard is gone whatever else still works."""
        from lib.ai.sub_summary import verify_sentence
        ok, reason, offending = verify_sentence(
            "Air Star Mechanical worked on ductwork.", self.PAYLOAD)
        self.assertFalse(ok)
        self.assertEqual(reason, "UNTRACED_TERM")
        self.assertIn("ductwork", offending)

    def test_no_connective_may_ever_assert_completion(self):
        """Enforced at import, not trusted: a later addition like "finished"
        cannot quietly become a connective and walk past the completion gate."""
        from lib.ai.sub_summary import _CONNECTIVES, _COMPLETION_TERMS
        self.assertEqual(_CONNECTIVES & _COMPLETION_TERMS, frozenset())

    def test_exactly_the_five_ruled_verbs_were_added(self):
        from lib.ai.sub_summary import _CONNECTIVES
        for verb in ("worked", "performed", "performing", "carried", "out"):
            self.assertIn(verb, _CONNECTIVES)


class TestTheOutcomeNamesTheBranchItActuallyTook(unittest.TestCase):
    """The outcome string is rendered on the admin preview, so it has to be
    RIGHT — a mislabelled branch sends the operator after the wrong thing, which
    is the failure this whole line exists to end."""

    def _traced(self, *, key="k", json_text=None, raise_exc=None):
        fake_genai, _ = _patch_gemini(json_text, raise_exc)
        with mock.patch.object(SS, "GEMINI_API_KEY", key),              mock.patch.object(SS, "genai", fake_genai):
            return SS.generate_sentence_traced(KESTREL)

    def test_generated(self):
        sentence, outcome = self._traced(json_text='{"sentence": "%s"}' % GOOD)
        self.assertEqual(sentence, GOOD)
        self.assertEqual(outcome, "generated")

    def test_skipped_when_there_is_no_key(self):
        sentence, outcome = self._traced(key="")
        self.assertIsNone(sentence)
        self.assertEqual(outcome, "skipped: no key")

    def test_failed_names_the_exception_CLASS_and_not_its_message(self):
        """An exception string can carry a request id, a URL, or a fragment of
        the payload — and this string is rendered."""
        sentence, outcome = self._traced(raise_exc=RuntimeError("token abc123 leaked"))
        self.assertIsNone(sentence)
        self.assertEqual(outcome, "failed: RuntimeError")
        self.assertNotIn("abc123", outcome)

    def test_refused_carries_the_reason_and_the_offending_terms(self):
        """"Refused" alone tells nobody what to change."""
        sentence, outcome = self._traced(
            json_text='{"sentence": "Kestrel Electric installed ductwork."}')
        self.assertIsNone(sentence)
        self.assertTrue(outcome.startswith("refused: COMPLETION_CLAIM"), outcome)
        self.assertIn("installed", outcome)

    def test_the_plain_wrapper_agrees_with_the_traced_one(self):
        """One implementation. If these ever disagree, one of them is lying."""
        fake_genai, _ = _patch_gemini('{"sentence": "%s"}' % GOOD)
        with mock.patch.object(SS, "GEMINI_API_KEY", "k"),              mock.patch.object(SS, "genai", fake_genai):
            self.assertEqual(SS.generate_sentence(KESTREL),
                             SS.generate_sentence_traced(KESTREL)[0])
