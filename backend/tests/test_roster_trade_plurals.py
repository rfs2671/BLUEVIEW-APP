"""A roster of five men is written in the plural.

"Framers - 5 workers" sat on a live crew card resolving to NOTHING. An
unresolved trade is not an error and does not empty the chip list -- it falls
back to the UNFILTERED catalogue, ranked off the project's prior day -- so the
framing crew was offered site prep, excavation, shoring and underpinning while
the plumber and electrician crews beside it were correct. Those two were
correct by luck: someone had typed them singular, and the map happened to hold
the singular agent noun for both.

`normalize_roster_trade` lowercases and collapses whitespace and does no
morphology, and a single token that misses cannot be rescued by `_split_roster`,
which needs two parts. So every plural missed, and every agent noun nobody had
thought to add missed.

WHAT THIS FILE PINS, and the shape of it matters more than the list:

  1. the strings from the live card now resolve, and resolve to the same thing
     as the spelling that already worked;
  2. nothing that resolved before resolves differently -- the whole map is
     compared against the trades each key claimed before, so a plural added
     next to the wrong entry fails here;
  3. the additions are the RULE stated in the map's comment -- agent nouns and
     countable things -- and the gerunds are deliberately absent, because a key
     nobody can type is noise in a map whose entire risk is a wrong entry
     looking exactly like a right one.

Singularisation is NOT here. It is a separate change with its own test asserting
that a morphological fallback never alters an existing resolution.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from app.scheduling.trade_taxonomy_v1 import (  # noqa: E402
    ROSTER_TRADE_MAP, TRADES, trades_for_roster,
)


# The live card, 2026-08-28. Arkon Builders read "Framers - 5 workers", the
# trade printed on the crew row, and the chips under it were the project's
# substructure phase.
class TheStringOnTheLiveCard(unittest.TestCase):
    def test_framers_resolves(self):
        self.assertEqual(trades_for_roster("Framers"),
                         ["Interior framing", "Wood framing"])

    def test_framers_resolves_to_what_framing_resolves_to(self):
        """Two spellings of one trade must not resolve differently -- that is
        the defect `_split_roster` was written to end, in a new place."""
        self.assertEqual(trades_for_roster("Framers"), trades_for_roster("framing"))
        self.assertEqual(trades_for_roster("Framer"), trades_for_roster("framing"))

    def test_the_capitalisation_on_the_card_is_irrelevant(self):
        for typed in ("Framers", "framers", "  FRAMERS ", "Framer"):
            with self.subTest(typed=typed):
                self.assertTrue(trades_for_roster(typed), f"{typed!r} resolved to nothing")

    def test_the_two_crews_that_worked_by_luck_still_work(self):
        self.assertEqual(trades_for_roster("Plumber"), ["Plumbing"])
        self.assertEqual(trades_for_roster("Electrician"), ["Electrical"])

    def test_and_now_they_work_typed_the_way_a_roster_is_written(self):
        self.assertEqual(trades_for_roster("Plumbers"), trades_for_roster("Plumber"))
        self.assertEqual(trades_for_roster("Electricians"), trades_for_roster("Electrician"))


class EveryPluralAddedResolvesLikeItsSingular(unittest.TestCase):
    """The rule, asserted rather than described: each added key claims exactly
    what the key it was derived from claims. A plural pasted next to the wrong
    trade is the one mistake this change could make, and it fails here."""

    PAIRS = [
        ("electricians", "electrician"),
        ("plumbers", "plumber"),
        ("sprinklers", "sprinkler"),
        ("elevators", "elevator"),
        ("carpenters", "carpenter"),
        ("ironworkers", "ironworker"),
        ("masons", "mason"),
        ("roofers", "roofer"),
        ("painters", "painter"),
        ("scaffolds", "scaffold"),
        ("framers", "framing"),
        ("framer", "framing"),
    ]

    def test_each_plural_claims_what_its_singular_claims(self):
        for plural, singular in self.PAIRS:
            with self.subTest(plural=plural):
                self.assertEqual(trades_for_roster(plural), trades_for_roster(singular))

    def test_each_added_key_claims_only_real_taxonomy_trades(self):
        for plural, _ in self.PAIRS:
            for trade in ROSTER_TRADE_MAP[plural]:
                with self.subTest(plural=plural, trade=trade):
                    self.assertIn(trade, TRADES)

    def test_ironworkers_stays_structural_only(self):
        """Inherits the ruling above the singular: in NYC the word covers
        structural AND reinforcing, and claiming both would hand a rebar crew
        the whole concrete package."""
        self.assertEqual(trades_for_roster("Ironworkers"), ["Structural steel"])


class TheGerundsAreDeliberatelyAbsent(unittest.TestCase):
    """A key nobody can type is not free: this map's whole risk is an entry that
    looks right and is wrong, and every line in it has to be readable as a thing
    a person wrote on a roster."""

    def test_no_pluralised_gerunds_or_mass_nouns(self):
        for junk in ("framings", "concretes", "roofings", "drywalls",
                     "plumbings", "masonries", "demolitions", "excavations"):
            with self.subTest(junk=junk):
                self.assertNotIn(junk, ROSTER_TRADE_MAP)

    def test_keys_that_are_already_plural_kept_their_singular_out(self):
        """Adding these would be singularisation, which is a separate change."""
        for singular in ("pile", "ceiling", "site utility", "specialty",
                         "window and door", "general condition"):
            with self.subTest(singular=singular):
                self.assertNotIn(singular, ROSTER_TRADE_MAP)


class NothingThatResolvedBeforeResolvesDifferently(unittest.TestCase):
    """The do-not-regress half, and it is the whole map rather than a sample.

    Every key present before this change is asserted to claim exactly what it
    claimed -- so a plural inserted into the wrong entry, or a stray edit to a
    neighbouring line, fails here rather than on a crew card.
    """

    # Captured from the map as it stood before the plurals were added.
    BEFORE = {
        "concrete": ["Foundation / Concrete"],
        "formwork": ["Foundation / Concrete"],
        "rebar": ["Foundation / Concrete"],
        "foundation": ["Foundation / Concrete"],
        "electrical": ["Electrical"],
        "electric": ["Electrical"],
        "electrician": ["Electrical"],
        "low voltage": ["Low voltage"],
        "hvac": ["HVAC", "Mechanical piping"],
        "mechanical": ["HVAC", "Mechanical piping"],
        "plumbing": ["Plumbing"],
        "plumber": ["Plumbing"],
        "fire protection": ["Fire protection"],
        "sprinkler": ["Fire protection"],
        "elevator": ["Elevator"],
        "carpentry": ["Carpentry (rough)", "Carpentry (finish)"],
        "carpenter": ["Carpentry (rough)", "Carpentry (finish)"],
        "rough carpentry": ["Carpentry (rough)"],
        "finish carpentry": ["Carpentry (finish)"],
        "demolition": ["Demolition"],
        "demo": ["Demolition"],
        "excavation": ["Excavation"],
        "shoring": ["Shoring / underpinning"],
        "underpinning": ["Shoring / underpinning"],
        "piles": ["Piles / caissons"],
        "site utilities": ["Site utilities"],
        "waterproofing": ["Waterproofing", "Waterproofing (interior)"],
        "structural steel": ["Structural steel"],
        "steel": ["Structural steel"],
        "ironworker": ["Structural steel"],
        "cfs": ["CFS (cold-formed steel)"],
        "cold-formed steel": ["CFS (cold-formed steel)"],
        "wood framing": ["Wood framing"],
        "framing": ["Interior framing", "Wood framing"],
        "masonry": ["Masonry"],
        "mason": ["Masonry"],
        "facade": ["Facade / cladding"],
        "cladding": ["Facade / cladding"],
        "windows and doors": ["Windows and doors"],
        "glazing": ["Windows and doors"],
        "roofing": ["Roofing"],
        "roofer": ["Roofing"],
        "sheet metal": ["Exterior sheet metal"],
        "interior framing": ["Interior framing"],
        "insulation": ["Insulation"],
        "firestopping": ["Firestopping"],
        "drywall": ["Drywall"],
        "flooring": ["Flooring"],
        "tile": ["Tile and stone"],
        "stone": ["Tile and stone"],
        "painting": ["Painting"],
        "painter": ["Painting"],
        "ceilings": ["Ceilings"],
        "cabinetry": ["Cabinetry and countertops"],
        "millwork": ["Carpentry (finish)", "Cabinetry and countertops"],
        "specialties": ["Specialties"],
        "landscaping": ["Landscaping / hardscape"],
        "hardscape": ["Landscaping / hardscape"],
        "site safety": ["Site safety"],
        "scaffold": ["Site safety"],
        "safety": ["Site safety"],
        "general conditions": ["General conditions"],
        "gc": ["General conditions"],
        "general contractor": ["General conditions"],
        "closeout": ["Closeout"],
    }

    def test_every_pre_existing_key_still_claims_exactly_what_it_claimed(self):
        for key, trades in self.BEFORE.items():
            with self.subTest(key=key):
                self.assertEqual(trades_for_roster(key), trades)

    def test_no_pre_existing_key_was_removed(self):
        missing = sorted(k for k in self.BEFORE if k not in ROSTER_TRADE_MAP)
        self.assertEqual(missing, [], f"keys disappeared from the map: {missing}")

    def test_the_split_rule_still_works(self):
        """`Concrete / Cement` is the string that proved the rule; it must not
        be collateral of an edit to the map it splits into."""
        self.assertEqual(trades_for_roster("Concrete / Cement"),
                         trades_for_roster("Concrete"))
        self.assertEqual(trades_for_roster("HVAC / Mechanical"),
                         ["HVAC", "Mechanical piping"])

    def test_junk_still_resolves_to_nothing_without_raising(self):
        for junk in (None, "", 7, [], "   ", "Cleaning"):
            with self.subTest(junk=junk):
                self.assertEqual(trades_for_roster(junk), [])


if __name__ == "__main__":
    unittest.main()
