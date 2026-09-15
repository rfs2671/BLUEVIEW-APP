"""Which project a WhatsApp group is for, guessed from its name.

The four cases named in the spec are the first class below. They are there
because a whole-string token_set_ratio at the 80 threshold FAILS two of them:

    "Boyland - Framing"  vs "588 Thomas S Boyland St"   58.3
    "Walworth crew"      vs "8 Walworth St"             76.2

Both are obvious to a human. Both lose, because a group name is a street plus a
crew word and an address is a number plus a street plus a suffix, so comparing
the wholes drowns the one token that means something. That measurement is why
lib/group_match.py compares fields rather than strings, and these tests are
what stop anyone from simplifying it back.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.group_match import (  # noqa: E402
    MATCH_THRESHOLD,
    house_number,
    name_tokens,
    score_project,
    street_tokens,
    suggest_project_for_group,
)

BOYLAND = {"id": "p_boyland", "name": "588 Thomas S Boyland",
           "address": "588 Thomas S Boyland St, Brooklyn NY"}
WALWORTH = {"id": "p_walworth", "name": "8 Walworth",
            "address": "8 Walworth St, Brooklyn NY"}
PROJECTS = [BOYLAND, WALWORTH]


class TheFourCasesFromTheSpec(unittest.TestCase):

    def test_boyland_framing_finds_588_thomas_s_boyland(self):
        got = suggest_project_for_group(PROJECTS, "Boyland - Framing")
        self.assertIsNotNone(got)
        self.assertEqual(got["project_id"], "p_boyland")

    def test_walworth_crew_finds_8_walworth(self):
        got = suggest_project_for_group(PROJECTS, "Walworth crew")
        self.assertIsNotNone(got)
        self.assertEqual(got["project_id"], "p_walworth")

    def test_brooklyn_jobs_finds_nothing(self):
        """A borough is a whole city of projects. After "brooklyn" and "jobs"
        are removed there is nothing left to compare, which is the right
        answer rather than an accident."""
        self.assertIsNone(suggest_project_for_group(PROJECTS, "Brooklyn jobs"))

    def test_site_chat_2_finds_nothing(self):
        self.assertIsNone(suggest_project_for_group(PROJECTS, "Site chat 2"))


class AWholeStringRatioWouldHaveFailed(unittest.TestCase):
    """The measurement that drove the design, asserted so it cannot be
    quietly undone by someone 'simplifying' the matcher."""

    def test_the_two_positives_score_below_the_threshold_as_whole_strings(self):
        try:
            from rapidfuzz import fuzz
        except ImportError:
            self.skipTest("rapidfuzz not installed")
        for group, project in (("Boyland - Framing", BOYLAND),
                               ("Walworth crew", WALWORTH)):
            with self.subTest(group=group):
                whole = fuzz.token_set_ratio(group.lower(),
                                             project["address"].lower())
                self.assertLess(whole, MATCH_THRESHOLD)

    def test_but_field_wise_they_clear_it(self):
        for group, project in (("Boyland - Framing", BOYLAND),
                               ("Walworth crew", WALWORTH)):
            with self.subTest(group=group):
                self.assertGreaterEqual(score_project(group, project),
                                        MATCH_THRESHOLD)


class TheNoiseListsEarnTheirPlace(unittest.TestCase):

    def test_crew_words_are_dropped(self):
        self.assertEqual(name_tokens("Walworth crew chat"), ["walworth"])

    def test_trade_words_are_dropped(self):
        """Several groups on ONE project differ only by trade, so a trade
        token pushes two groups at the same project instead of telling them
        apart."""
        self.assertEqual(name_tokens("Boyland framing"), ["boyland"])
        self.assertEqual(name_tokens("Boyland electrical"), ["boyland"])

    def test_two_trade_groups_on_one_job_both_resolve_to_it(self):
        for nm in ("Boyland framing", "Boyland electrical", "Boyland demo"):
            with self.subTest(group=nm):
                got = suggest_project_for_group(PROJECTS, nm)
                self.assertIsNotNone(got, nm)
                self.assertEqual(got["project_id"], "p_boyland")

    def test_place_words_are_dropped(self):
        self.assertEqual(name_tokens("Brooklyn NYC"), [])

    def test_digits_survive(self):
        """A house number is one of the strongest signals available."""
        self.assertIn("588", name_tokens("588 Boyland"))

    def test_punctuation_is_a_separator(self):
        for nm in ("Boyland - Framing", "Boyland/Framing", "Boyland, framing"):
            with self.subTest(name=nm):
                self.assertEqual(name_tokens(nm), ["boyland"])


class TheAddressIsSplitIntoItsParts(unittest.TestCase):

    def test_the_house_number_comes_off_the_street(self):
        self.assertEqual(street_tokens("588 Thomas S Boyland St"),
                         ["thomas", "boyland"])

    def test_the_house_number_is_available_separately(self):
        self.assertEqual(house_number("588 Thomas S Boyland St"), "588")

    def test_an_address_with_no_number_still_yields_a_street(self):
        self.assertEqual(street_tokens("Walworth Street"), ["walworth"])

    def test_street_suffixes_are_dropped_from_both_sides(self):
        """"Walworth St" and "Walworth" have to be one street."""
        self.assertEqual(street_tokens("8 Walworth St"), ["walworth"])
        self.assertEqual(name_tokens("Walworth St"), ["walworth"])


class AHouseNumberOnlyCountsWithAStreet(unittest.TestCase):
    """A bare number is far too weak — "8" is in a great many addresses — but
    a number AND a street agreeing is two independent signals."""

    def test_number_plus_street_clears_on_its_own(self):
        self.assertGreaterEqual(score_project("588 Boyland", BOYLAND),
                                MATCH_THRESHOLD)

    def test_a_bare_matching_number_does_not(self):
        other = {"id": "p_x", "name": "588 Other", "address": "588 Nowhere Ave"}
        self.assertLess(score_project("588 Boyland", other), MATCH_THRESHOLD)


class TheNicknameIsForTheNamesPeopleActuallyUse(unittest.TestCase):

    def test_a_nickname_match_is_enough(self):
        p = dict(BOYLAND, nickname="The Church Job")
        self.assertGreaterEqual(score_project("Church Job", p),
                                MATCH_THRESHOLD)

    def test_a_project_with_no_nickname_is_unaffected(self):
        self.assertIsNone(BOYLAND.get("nickname"))
        self.assertGreaterEqual(score_project("Boyland", BOYLAND),
                                MATCH_THRESHOLD)


class AnIdentifierIsNotAGuess(unittest.TestCase):
    """Nobody types a BIN by accident."""

    def test_a_bin_in_the_name_is_an_exact_hit(self):
        p = dict(BOYLAND, nyc_bin="3255362")
        self.assertEqual(score_project("3255362 crew", p), 100.0)

    def test_a_bbl_in_the_name_is_an_exact_hit(self):
        p = dict(BOYLAND, bbl="3034560012")
        self.assertEqual(score_project("job 3034560012", p), 100.0)

    def test_an_empty_bin_does_not_match_an_empty_token(self):
        p = dict(BOYLAND, nyc_bin="", bbl=None)
        self.assertLess(score_project("Site chat", p), MATCH_THRESHOLD)


class OneClearWinnerOrNothing(unittest.TestCase):

    def test_two_projects_over_the_threshold_produce_no_suggestion(self):
        """An ambiguous name gets an empty dropdown. A confident pre-fill that
        is wrong gets confirmed; an empty row tells the person to decide."""
        twin_a = {"id": "a", "name": "100 Walworth", "address": "100 Walworth St"}
        twin_b = {"id": "b", "name": "200 Walworth", "address": "200 Walworth St"}
        self.assertIsNone(
            suggest_project_for_group([twin_a, twin_b], "Walworth crew"))

    def test_but_a_house_number_breaks_the_tie(self):
        twin_a = {"id": "a", "name": "100 Walworth", "address": "100 Walworth St"}
        twin_b = {"id": "b", "name": "200 Walworth", "address": "200 Walworth St"}
        # Both still clear on the street, so this is still ambiguous — the tie
        # is only broken when the OTHER project stops clearing, which needs a
        # different street. Asserted so the behaviour is not mistaken for a
        # ranking: this function does not rank, it refuses.
        self.assertIsNone(
            suggest_project_for_group([twin_a, twin_b], "100 Walworth"))

    def test_an_empty_project_list_is_no_suggestion(self):
        self.assertIsNone(suggest_project_for_group([], "Boyland"))

    def test_an_empty_group_name_is_no_suggestion(self):
        for nm in ("", None, "   "):
            with self.subTest(name=nm):
                self.assertIsNone(suggest_project_for_group(PROJECTS, nm))

    def test_a_project_with_no_id_is_not_suggested(self):
        self.assertIsNone(
            suggest_project_for_group([{"name": "Boyland",
                                        "address": "588 Boyland St"}],
                                      "Boyland"))

    def test_mongo_underscore_id_is_accepted(self):
        got = suggest_project_for_group(
            [{"_id": "oid123", "address": "588 Thomas S Boyland St"}],
            "Boyland crew")
        self.assertEqual(got["project_id"], "oid123")


class TheConfidenceIsReported(unittest.TestCase):

    def test_it_is_a_fraction_not_a_percentage(self):
        got = suggest_project_for_group(PROJECTS, "Boyland - Framing")
        self.assertGreaterEqual(got["confidence"], 0.8)
        self.assertLessEqual(got["confidence"], 1.0)


class ItNeverReachesTheDatabase(unittest.TestCase):
    """The tenant scope is resolved by the CALLER, where the authenticated
    user is. This module takes a list and cannot widen it."""

    def test_the_module_imports_no_database_driver(self):
        src = (Path(__file__).resolve().parents[1]
               / "lib" / "group_match.py").read_text(encoding="utf-8")
        for banned in ("import motor", "from motor", "AsyncIOMotorClient",
                       "import server", "from server"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)

    def test_a_missing_rapidfuzz_degrades_to_no_suggestion(self):
        """Not a crash and not a wrong answer: the screen still renders and
        the dropdown is simply empty."""
        import builtins
        import lib.group_match as gm

        real_import = builtins.__import__

        def no_rapidfuzz(name, *a, **kw):
            if name.startswith("rapidfuzz"):
                raise ImportError("simulated")
            return real_import(name, *a, **kw)

        builtins.__import__ = no_rapidfuzz
        try:
            self.assertEqual(gm._ratio(["boyland"], ["boyland"]), 0.0)
            self.assertIsNone(
                gm.suggest_project_for_group(PROJECTS, "Boyland - Framing"))
        finally:
            builtins.__import__ = real_import


if __name__ == "__main__":
    unittest.main()
