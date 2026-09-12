"""THE NORMALISATION TABLE IS CONSISTENT, AND IT NEVER GUESSES.

WHAT THIS FILE CAN AND CANNOT DO, because the difference matters here.

It can prove the table is well-formed: that every key is normalised, that every
token it produces can be displayed, that nothing maps to a token the order does
not carry, and that the scope token is structurally incapable of being counted
as a place.

IT CANNOT PROVE COVERAGE. Coverage is a fact about production data, which CI
does not have. So the table returns a measured coverage figure and the report
prints the unmapped strings on the page -- the alarm is on the document, in
front of a reader, rather than in a suite that cannot see the corpus. The
figure at the time of writing was 97.6% of 85 located rows, with the remaining
two being the string `J` on 857 Prescott, which carries no recoverable meaning.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.report import location_vocabulary as lv  # noqa: E402


class TheTableIsWellFormed(unittest.TestCase):

    def test_every_key_is_already_normalised(self):
        """A key that needs normalising to match can never be hit, because
        lookup normalises the INPUT and compares against the key as written."""
        for key in lv.VOCABULARY:
            self.assertEqual(
                key, " ".join(key.split()).lower(),
                f"{key!r} is not lower-cased and whitespace-collapsed, so no "
                f"recorded string can ever match it")

    def test_no_key_maps_to_nothing(self):
        for key, tokens in lv.VOCABULARY.items():
            self.assertTrue(tokens, f"{key!r} maps to an empty tuple, which is "
                                    f"neither a mapping nor an unmapped value")

    def test_every_token_produced_can_be_displayed(self):
        """THE CLOSED SET, ENFORCED. A token the order does not carry would be
        computed, counted, and then silently dropped by `rail`."""
        produced = {t for tokens in lv.VOCABULARY.values() for t in tokens}
        for token in produced:
            self.assertTrue(
                token in lv.DISPLAY_ORDER or token == lv.SCOPE,
                f"{token!r} is produced by the table but is neither in "
                f"DISPLAY_ORDER nor the scope token")

    def test_every_displayable_token_has_both_labels(self):
        for token in lv.DISPLAY_ORDER + (lv.SCOPE,):
            self.assertIn(token, lv.LABELS, token)
            rail, prose = lv.LABELS[token]
            self.assertTrue(rail and prose, token)

    def test_the_scope_token_is_not_in_the_display_order(self):
        """STRUCTURAL, NOT A CONVENTION. `rail` builds the area list by
        filtering DISPLAY_ORDER, so a scope token absent from it cannot be
        counted as an area by any call site, present or future."""
        self.assertNotIn(lv.SCOPE, lv.DISPLAY_ORDER)

    def test_the_order_has_no_repeats(self):
        self.assertEqual(len(lv.DISPLAY_ORDER), len(set(lv.DISPLAY_ORDER)))

    def test_EX_is_not_yet_labelled_excavation(self):
        """THE INFERENCE IS NOT THE LABEL. Three rows read `ex`, twice beside
        `foundation`, and that is not enough to put the word Excavation on an
        investor document. When it is confirmed this test changes with the
        label; until then it stops the word arriving by accident."""
        self.assertEqual(lv.LABELS["EX"], ("EX", "EX"))


class ItNeverGuesses(unittest.TestCase):

    def test_an_unknown_string_comes_back_verbatim(self):
        r = lv.resolve(["Zorp Deck 4"])
        self.assertEqual(r.areas, [])
        self.assertEqual(r.unmapped, ["Zorp Deck 4"])
        self.assertEqual(r.mapped, 0)
        self.assertEqual(r.located, 1)

    def test_a_near_miss_is_not_matched(self):
        """NO FUZZY MATCH, NO STEMMING, NO DISTANCE. `1st floor` is in the
        table; `1st floo` is not, and must not become L1 because it is close."""
        self.assertEqual(lv.resolve(["1st floo"]).areas, [])
        self.assertEqual(lv.resolve(["1st floor"]).areas, ["L1"])

    def test_case_and_whitespace_do_not_defeat_the_table(self):
        for spelling in ("1st floor", "1ST FLOOR", "  1st   floor  ",
                         "First Floor"):
            self.assertEqual(lv.resolve([spelling]).areas, ["L1"], spelling)

    def test_a_blank_value_is_not_a_located_row(self):
        r = lv.resolve(["", None, "   "])
        self.assertEqual((r.located, r.mapped), (0, 0))
        self.assertIsNone(r.coverage,
                          "a day with nothing to normalise reported perfect "
                          "normalisation")


class TheFourShapes(unittest.TestCase):
    """Each of these fires on a real production day; the dates are named so a
    reader can go and look."""

    def test_named_areas(self):
        r = lv.resolve(["1st floor", "Underground"])      # 2026-08-27
        self.assertEqual(r.areas, ["L1", "UG"])
        value, label, notes = r.rail()
        self.assertEqual((value, label), ("2", "Active areas"))
        self.assertEqual(notes[0], "L1 / UG")

    def test_a_span_expands_into_its_levels(self):
        r = lv.resolve(["Floors 3-5"])                    # 2026-08-16
        self.assertEqual(r.areas, ["L5", "L4", "L3"])
        self.assertEqual(r.rail()[0], "3")

    def test_scope_does_not_inflate_the_count(self):
        r = lv.resolve(["All areas", "Ground floor"])     # 2026-08-26
        self.assertEqual(r.areas, ["G"])
        value, label, notes = r.rail()
        self.assertEqual(value, "1")
        self.assertIn("Sitewide activity also recorded", notes)

    def test_scope_alone_is_not_one_area(self):
        r = lv.resolve(["T/O"])                           # 2026-03-10
        self.assertEqual(r.areas, [])
        value, label, notes = r.rail()
        self.assertEqual((value, label), ("Sitewide", "Recorded activity"))
        self.assertIn("No specific area recorded", notes)

    def test_unmapped_alone_says_LOCATION_not_ACTIVE_AREAS(self):
        """The heading is a claim. "No area recorded" under ACTIVE AREAS says
        the system knows there were none; a location WAS recorded here and the
        table could not read it."""
        r = lv.resolve(["J"])                             # 2026-08-17
        value, label, notes = r.rail()
        self.assertEqual((value, label), ("—", "Location"))
        self.assertEqual(notes, ["Unmapped source value: J"])

    def test_nothing_recorded_at_all(self):
        value, label, notes = lv.resolve([]).rail()
        self.assertEqual((value, label), ("—", "Location"))
        self.assertEqual(notes, ["No location recorded"])


class CoverageIsMeasured(unittest.TestCase):

    def test_it_counts_rows_not_distinct_strings(self):
        """Four rows of the same spelling is four mapped rows. Counting
        distinct strings would let one popular spelling hide a hundred
        unmapped ones behind a flattering percentage."""
        r = lv.resolve(["1st floor"] * 4 + ["J"])
        self.assertEqual((r.located, r.mapped), (5, 4))
        self.assertAlmostEqual(r.coverage, 80.0)


class AProjectMayOverrideTheGlobalTable(unittest.TestCase):

    def test_an_override_wins(self):
        """The one building that establishes, for itself, that its ground floor
        IS its first floor. The global table refuses to decide that; a project
        may decide it about itself."""
        r = lv.resolve(["Ground"], overrides={"Ground": ("L1",)})
        self.assertEqual(r.areas, ["L1"])
        self.assertEqual(lv.resolve(["Ground"]).areas, ["G"],
                         "the override leaked into the global table")

    def test_an_override_can_map_a_string_the_global_table_never_saw(self):
        r = lv.resolve(["J"], overrides={"J": ("L2",)})
        self.assertEqual(r.areas, ["L2"])
        self.assertEqual(r.unmapped, [])

    def test_an_override_is_normalised_like_any_other_key(self):
        r = lv.resolve(["penthouse"], overrides={"  PENTHOUSE ": ("ROOF",)})
        self.assertEqual(r.areas, ["ROOF"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
