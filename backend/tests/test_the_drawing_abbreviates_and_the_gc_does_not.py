"""A GC TYPES WORDS. THE DRAWING PRINTS ABBREVIATIONS. NOTHING CONNECTED THEM.

`apartment square footage` returned NOTHING while A-101.00 prints, and the
corpus stores verbatim:

    2A   1 BEDROOM APT.   NET: 482 SQ. FT.   GROSS: 537 SQ. FT.

The record matched none of `apartment`, `square` or `footage`, so it was never
in the candidate set and ranking never saw it. Six of eighteen ordinary
phrasings returned nothing for content that was extracted, stored, on a live
page and correct.

Two separate defects, fixed by two separate things, and this file keeps them
apart because conflating them is how a number moves for a reason nobody can
name:

    THE FLOOR decided WHETHER TO ANSWER. It required every query word in one
    record, so it refused. `subject_is_known` replaces that: refuse only when
    a word of the subject appears NOWHERE in the corpus.

    THE BRIDGE decides WHAT IS FOUND. `apartment` now matches `APT.`, so the
    record reaches the candidate set at all.

Measured end to end: verdicts 20/26 -> 27/27, and the answer actually present
in the returned records 2/7 -> 6/7. The floor moved the first number; the
bridge moved the second.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as ps  # noqa: E402

#: The line this whole change exists to reach.
A101 = '2A 1 BEDROOM APT. NET: 482 SQ. FT. GROSS: 537 SQ. FT.'


def matches(term: str, text: str) -> bool:
    return bool(re.search(ps.term_pattern(term), text, re.I))


class TheWordsAGcTypesReachTheSheetsAbbreviations(unittest.TestCase):

    def test_the_record_that_started_this(self):
        for word in ("apartment", "square", "feet"):
            self.assertTrue(matches(word, A101),
                            f"{word!r} still cannot reach {A101!r}")

    def test_truncations_are_derived_not_listed(self):
        """MIN is the first three letters of MINIMUM. No list needed."""
        for word, abbrev in (("minimum", "MIN."), ("maximum", "MAX."),
                             ("typical", "TYP."), ("concrete", "CONC."),
                             ("elevation", "ELEV."), ("dimension", "DIM."),
                             ("section", "SEC."), ("diameter", "DIA."),
                             ("structural", "STRUCT."), ("property", "PROP.")):
            self.assertTrue(matches(word, f"SEE {abbrev} HERE"),
                            f"{word} -> {abbrev}")
            self.assertNotIn(abbrev.rstrip(".").lower(), ps.CONVENTIONS,
                             f"{abbrev} is derivable and must not be listed")

    def test_contractions_are_listed_because_no_rule_derives_them(self):
        """APT drops the middle of APARTMENT. FT the middle of FEET."""
        for word, abbrev in (("apartment", "APT."), ("feet", "FT."),
                             ("square", "SQ."), ("quantity", "QTY.")):
            self.assertTrue(matches(word, f"SEE {abbrev} HERE"),
                            f"{word} -> {abbrev}")

    def test_the_period_is_the_signal(self):
        """Without it MIN matches MINE and SQ matches SQUID. The period is
        what says the token stands for a longer word."""
        self.assertFalse(matches("minimum", "THE MINE SHAFT"))
        self.assertFalse(matches("apartment", "APT WITHOUT A PERIOD"))
        self.assertTrue(matches("apartment", "APT. WITH ONE"))


class AnEnglishWordIsNotAnAbbreviation(unittest.TestCase):
    """`notes` generates the prefix NOT, and a sheet ending a sentence with
    "...SHALL NOT." would be bridged to it.

    The exclusion set is DERIVED, not hand-picked: each member appears ZERO
    times followed by a period in the 173-page corpus and 14-414 times bare,
    while every real abbreviation appears at least once with one.
    """

    def test_a_prose_word_does_not_bridge(self):
        self.assertNotIn("not", ps.abbreviation_forms("notes"))
        self.assertFalse(matches("notes", "THIS SHALL NOT. BE DONE"))

    def test_and_neither_does_are(self):
        self.assertNotIn("are", ps.abbreviation_forms("area"))

    def test_the_exclusion_costs_nothing(self):
        """No valid bridge is in the excluded set — that is why it is safe.
        Asserted so a future addition to _PROSE_PREFIXES has to prove the
        same thing rather than quietly removing a working bridge."""
        derivable = {"min", "max", "typ", "conc", "elev", "dim", "dia",
                     "sec", "det", "col", "prov", "corp", "prop", "struct"}
        clash = derivable & ps._PROSE_PREFIXES
        self.assertEqual(set(), clash,
                         f"excluding {clash} would break a working bridge")


class TheListIsGovernedByARule(unittest.TestCase):
    """A hand-kept list of word relationships is what rotted before. This one
    is governed: an entry earns its place by evidence, never by argument."""

    def test_every_entry_carries_its_occurrence_count(self):
        for abbrev, value in ps.CONVENTIONS.items():
            self.assertEqual(len(value), 2, abbrev)
            expansion, count = value
            self.assertIsInstance(count, int, abbrev)
            self.assertGreater(count, 0,
                               f"{abbrev} has no evidence behind it")

    def test_nothing_derivable_is_listed(self):
        """If the prefix rule reaches it, listing it is duplication — and a
        list that duplicates a rule is a list that will disagree with it."""
        for abbrev, (expansion, _n) in ps.CONVENTIONS.items():
            if " " in expansion:
                continue
            derived = [p for p in ps.abbreviation_forms(expansion)
                       if p != abbrev]
            self.assertNotIn(
                abbrev, derived,
                f"{abbrev} is a prefix of {expansion} and needs no entry")

    def test_multi_word_expansions_are_documented_but_unwired(self):
        """SF stands for the PHRASE `square feet`, not for either word. Wiring
        it per-term made `square` match `PSF.`, a bridge nobody asked for."""
        self.assertIn("sf", ps.CONVENTIONS)
        self.assertNotIn("sf", ps.abbreviation_forms("square"))
        self.assertNotIn("psf", ps.abbreviation_forms("square"))
        self.assertNotIn("sf", ps.abbreviation_forms("feet"))


class TheFloorAsksWhetherTheCorpusKnowsTheWord(unittest.TestCase):
    """It used to ask whether ONE RECORD carried every word, which is why it
    refused a question the corpus could answer."""

    KNOWN = {"apartment", "apartments", "square", "footage", "feet", "area",
             "net", "joist", "schedule", "concrete", "ceiling", "sprinkler"}

    def test_a_subject_the_corpus_uses_is_answerable(self):
        for subject in ("apartment square footage", "apartment area",
                        "net square feet", "joist schedule"):
            self.assertTrue(
                ps.subject_is_known(ps.search_terms(subject), self.KNOWN),
                subject)

    def test_a_word_the_drawings_never_use_refuses(self):
        """`solar` appears in none of 12,031 records. That is not noise to be
        dropped — it is the finding."""
        for subject in ("solar panels", "chase wall", "concrete pour schedule"):
            self.assertFalse(
                ps.subject_is_known(ps.search_terms(subject), self.KNOWN),
                subject)

    def test_a_question_with_no_subject_left_refuses(self):
        """"how many?" — every word an asking word, no subject at all.

        `floor_terms` keeps the original terms rather than stripping to
        nothing, so they are checked against the corpus and refuse. NOTHING
        is the right answer here and "the best match" is not: a question with
        no subject has nothing to be about, and any records returned would be
        chosen by a ranker with no signal to rank on. The old rule refused
        this too — requiring `how` AND `many` in one record — so the
        behaviour is unchanged and now has a reason rather than an accident.
        """
        self.assertFalse(ps.subject_is_known(["how", "many"], set()))

    def test_but_a_real_subject_beside_asking_words_survives(self):
        """The stripping must not be so eager that `how many PTAC units`
        loses its subject."""
        self.assertTrue(
            ps.subject_is_known(ps.search_terms("how many ptac units"),
                                {"ptac", "units", "unit"}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
