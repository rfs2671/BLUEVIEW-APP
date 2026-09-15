"""A BETTER CARD READ MUST NEVER SCORE WORSE THAN A DEGRADED ONE.

THE DEFECT, replayed against production payloads. `resolve_card_class`
returned on an unmapped colour BEFORE the text was ever consulted:

    payload                                  -> result
    'FULL' + WHITE / high / []               -> SST_UNSPECIFIED, CLASS_UNVERIFIED
    same, colour dropped                     -> SST_FULL, text_only, clean
    same, confidence 'low'                   -> SST_FULL, text_only, clean
    same, high but conditions ['GLARE']      -> SST_FULL, text_only, clean

Degrade the colour read and the man passes; read it well and he is flagged.
That inversion is the bug, and it is not a WHITE quirk: the OCR prompt
enumerates NINE colours the model may return and `_CARD_COLOR_CLASS_MAP` holds
THREE, with PURPLE handled separately as not-an-SST-card. FIVE of the nine
answers the prompt invites destroyed a correctly-read text class, and WHITE is
the first value the prompt lists.

THE RULING:
  * An unmapped colour is NO SIGNAL. It falls through to the text class.
  * Only a MAPPED colour that CONTRADICTS the text class flags.
  * A better read must never score worse than a degraded one — asserted here as
    a PROPERTY over every colour the prompt invites, not as a list of expected
    outcomes. Enumerating outcomes one by one is how the old behaviour came to
    have a passing test of its own (`test_an_unmapped_colour_is_unknown_not_a_
    guess`, in test_d6_colour_first_class.py): each row was individually
    defensible and the relation between them was never asked about.

NOTHING HERE IS HAND-LISTED THAT CAN BE DERIVED. The nine colours are parsed
out of the live extraction prompt, the colours this app has a meaning for come
from `_CARD_COLOR_CLASS_MAP` and `SST_COLOR_WORKER_WALLET`, and the class words
are checked against `_map_sst_class` and censused against `SST_CLASS_TYPES`. A
tenth colour in the prompt, or a fourth class in the vocabulary, is covered the
day it is added rather than the day someone remembers this file.

Run:  python -m pytest backend/tests/test_a_better_read_never_scores_worse.py -q
"""

from __future__ import annotations

import itertools
import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


def ocr(**kw):
    """A card that reads CLEANLY apart from whatever the test varies."""
    d = {
        "name": "Jane", "sst_number": "SST1", "card_type": "SST",
        "card_class": "FULL", "issued": None, "expiration": "06/01/2029",
        "card_dominant_color": None, "card_color_confidence": None,
        "card_color_conditions": [],
    }
    d.update(kw)
    return d


def resolve(**kw):
    return server.resolve_card_class(ocr(**kw))


# ── The nine colours, PARSED OUT OF THE LIVE PROMPT ──────────────────────────
# The prompt is the contract with the model: these are the answers the app
# ASKS FOR, so these are the answers it must survive. Reading them from the
# source means a colour added to the prompt is covered without this file being
# touched — which is the whole failure being fixed, one level up.
#
# READ FROM THE VALUE, NOT FROM THE SOURCE TEXT. This sliced
# `SRC.index("extraction_prompt = (")`, and #550 lifted that local into the
# module constant `_OSHA_EXTRACTION_PROMPT`. The slice then raised ValueError
# AT IMPORT, which is a COLLECTION error — pytest aborts the whole run, so
# ~7000 tests stopped executing on main and on every branch cut from it. Both
# PRs were green alone; only the merge was red.
#
# The prompt is a module-level string now, so ask the module for it. A rename
# cannot break this again, and if the constant disappears the failure is an
# AttributeError naming it rather than a substring nobody can find.
def _prompt_colours():
    prompt = getattr(server, "_OSHA_EXTRACTION_PROMPT", None)
    assert isinstance(prompt, str) and prompt, (
        "server._OSHA_EXTRACTION_PROMPT is missing or not a string; the OCR "
        "prompt this test derives its colour list from has moved again")
    # NO LEADING QUOTE. The old pattern was `"One of: …` because it read the
    # SOURCE, where that quote is a string-literal boundary. In the joined
    # VALUE the adjacent literals are concatenated and the quote is gone —
    # which is the second half of why reading source text is fragile: the
    # thing you anchor on may not exist in the object at all.
    m = re.search(r'One of: ([A-Z, ]+)\. ', prompt)
    assert m, "the prompt no longer enumerates the colours it invites"
    return [c.strip() for c in m.group(1).split(",") if c.strip()]


PROMPT_COLOURS = _prompt_colours()

# The colours this app actually has a meaning for. Derived, never typed: the
# three in the map, plus PURPLE, which refuses the card rather than classing it.
MEANINGFUL = set(server._CARD_COLOR_CLASS_MAP) | {server.SST_COLOR_WORKER_WALLET}

# A printed class WORD per live class. Verified against the mapper below rather
# than assumed, and censused against the vocabulary so a new class cannot slip
# past untested.
CLASS_WORDS = {"Worker": "SST_FULL",
               "Supervisor": "SST_SUPERVISOR",
               "Temporary": "SST_TEMPORARY"}

# ── The degradations, as the model actually reports them ────────────────────
# Each is a WORSE read of the same card than the clean one above it.
DEGRADED = [
    ("colour dropped", {}),
    ("confidence low", {"card_color_confidence": "low"}),
    ("confidence medium", {"card_color_confidence": "medium"}),
    ("glare", {"card_color_conditions": ["GLARE"]}),
    ("sleeve", {"card_color_conditions": ["SLEEVE"]}),
]


def severity(r) -> int:
    """HOW BAD THE OUTCOME IS FOR THE MAN HOLDING THE CARD, as one number.

    'Worse' has to be a real comparison before "never worse" can be a test.
    The ladder is the reviewer's, not the resolver's:

        0  a class, cleanly — nothing is asked of anyone
        1  a class, but flagged — someone must look
        2  NO class — the card must be re-scanned or verified by hand
        3  refused outright — this is not an SST card

    `class_source` is deliberately NOT in the ladder. color_and_text is a
    STRONGER provenance than text_only and both are clean, so folding
    provenance in here would make a confirmation register as a change in
    severity. Provenance is asserted separately.
    """
    if r["not_sst"] or r["sst_type"] is None:
        return 3
    if r["sst_type"] == server.SST_UNSPECIFIED:
        return 2
    if r["review_reason"]:
        return 1
    return 0


class TheFourReplayRows(unittest.TestCase):
    """The production payloads, by name. These four rows ARE the inversion:
    one clean read and three degraded reads of the same card, and it was the
    CLEAN one that failed."""

    def test_full_plus_white_high_and_no_conditions(self):
        r = resolve(card_dominant_color="WHITE", card_color_confidence="high")
        self.assertEqual(r["sst_type"], "SST_FULL")
        self.assertEqual(r["class_source"], "text_only")
        self.assertIsNone(r["review_reason"])

    def test_same_payload_with_the_colour_dropped(self):
        r = resolve()
        self.assertEqual(r["sst_type"], "SST_FULL")
        self.assertEqual(r["class_source"], "text_only")
        self.assertIsNone(r["review_reason"])

    def test_same_payload_at_low_confidence(self):
        r = resolve(card_dominant_color="WHITE", card_color_confidence="low")
        self.assertEqual(r["sst_type"], "SST_FULL")
        self.assertEqual(r["class_source"], "text_only")
        self.assertIsNone(r["review_reason"])

    def test_same_payload_high_but_under_glare(self):
        r = resolve(card_dominant_color="WHITE", card_color_confidence="high",
                    card_color_conditions=["GLARE"])
        self.assertEqual(r["sst_type"], "SST_FULL")
        self.assertEqual(r["class_source"], "text_only")
        self.assertIsNone(r["review_reason"])

    def test_the_four_rows_agree_with_each_other(self):
        """THE POINT OF THE FOUR, stated as the relation between them rather
        than as four separate expectations. Each row above passed on its own
        merits before the fix too — three of them did. What nothing asked was
        whether they MATCHED, and they did not."""
        rows = {
            "clean": resolve(card_dominant_color="WHITE", card_color_confidence="high"),
            "no colour": resolve(),
            "low confidence": resolve(card_dominant_color="WHITE",
                                      card_color_confidence="low"),
            "glare": resolve(card_dominant_color="WHITE", card_color_confidence="high",
                             card_color_conditions=["GLARE"]),
        }
        for label, r in rows.items():
            with self.subTest(row=label):
                self.assertEqual(severity(r), severity(rows["no colour"]),
                                 f"'{label}' scores differently from the same card "
                                 "read with no colour at all")


class TheClassWordsAreTheRealVocabulary(unittest.TestCase):
    """The crosses below are only as good as the words they cross. Checked,
    not assumed — and censused, so a fourth live class breaks this rather than
    quietly going untested."""

    def test_each_word_maps_to_the_class_it_claims(self):
        for word, want in CLASS_WORDS.items():
            with self.subTest(word=word):
                self.assertEqual(server._map_sst_class(word), want)

    def test_the_words_cover_every_live_class(self):
        live = set(server.SST_CLASS_TYPES) - set(server.SST_DEAD_CLASSES)
        self.assertEqual(set(CLASS_WORDS.values()), live,
                         "a class in the vocabulary that no word here exercises "
                         "is a class this invariant does not actually cover")

    def test_the_prompt_invites_more_colours_than_the_map_knows(self):
        """THE ARITHMETIC OF THE DEFECT, kept as a live count rather than as a
        sentence in a commit message. Five of the nine answers the prompt asks
        for are colours this app has no meaning for, and each of them used to
        destroy a read class."""
        self.assertGreater(len(PROMPT_COLOURS), len(MEANINGFUL))
        unmeaning = [c for c in PROMPT_COLOURS if c not in MEANINGFUL]
        self.assertEqual(sorted(unmeaning),
                         ["GREEN", "GREY", "ORANGE", "OTHER", "WHITE"])
        self.assertEqual(PROMPT_COLOURS[0], "WHITE",
                         "the first colour the prompt lists is one of them")


class AColourMayOnlyHurtWhenItMeansSomething(unittest.TestCase):
    """THE INVARIANT, over every colour the prompt invites crossed with every
    live class word. Asserted as a RELATION to the no-colour baseline — not as
    a table of expected outcomes, because a table is exactly what the old
    behaviour had."""

    def test_no_colour_can_make_the_outcome_worse_unless_it_means_something(self):
        for colour, word in itertools.product(PROMPT_COLOURS, CLASS_WORDS):
            with self.subTest(colour=colour, card_class=word):
                base = resolve(card_class=word)
                got = resolve(card_class=word, card_dominant_color=colour,
                              card_color_confidence="high")
                if severity(got) > severity(base):
                    self.assertIn(
                        colour, MEANINGFUL,
                        f"{colour} is not in _CARD_COLOR_CLASS_MAP and is not the "
                        "Worker Wallet colour, so it carries no information — it "
                        f"must not be able to turn a legible '{word}' card into "
                        f"{got['sst_type']} / {got['review_reason']}")

    def test_an_unmapped_colour_leaves_the_row_exactly_where_no_colour_would(self):
        """STRICTER THAN 'not worse', and it is the honest form of the ruling:
        an unmapped colour is NO SIGNAL, so the verdict must be identical, not
        merely no worse. `color` is excluded because it is the one field that
        SHOULD differ — see the next test."""
        for colour, word in itertools.product(PROMPT_COLOURS, CLASS_WORDS):
            if colour in MEANINGFUL:
                continue
            with self.subTest(colour=colour, card_class=word):
                base = resolve(card_class=word)
                got = resolve(card_class=word, card_dominant_color=colour,
                              card_color_confidence="high")
                self.assertEqual({k: v for k, v in got.items() if k != "color"},
                                 {k: v for k, v in base.items() if k != "color"})

    def test_the_unmapped_colour_is_still_recorded(self):
        """Not classifying on a colour and not recording it are different acts.
        The colour reaches the row as `card_color_seen`, so a reviewer can see
        that the model called this card WHITE even though nothing rested on it."""
        for colour in PROMPT_COLOURS:
            if colour in MEANINGFUL:
                continue
            with self.subTest(colour=colour):
                r = resolve(card_class="Worker", card_dominant_color=colour,
                            card_color_confidence="high")
                self.assertEqual(r["color"], colour)

    def test_a_clean_colour_read_never_scores_worse_than_a_degraded_one(self):
        """THE HEADLINE, DIRECTLY. For every colour and every class word, the
        best available read of the card is compared against each way the same
        read could have come back degraded. A better photograph may confirm, it
        may say nothing — it may never cost the man more than a worse one."""
        for colour, word in itertools.product(PROMPT_COLOURS, CLASS_WORDS):
            clean = resolve(card_class=word, card_dominant_color=colour,
                            card_color_confidence="high")
            if colour in MEANINGFUL:
                # A mapped colour carries real information, and information can
                # legitimately be bad news (a contradiction, or the wrong card).
                # The claim is scoped to the colours that carry none.
                continue
            for label, degradation in DEGRADED:
                with self.subTest(colour=colour, card_class=word, degraded=label):
                    # The degradation OVERRIDES the clean read's fields rather
                    # than being passed alongside them — "colour dropped" is the
                    # absence of card_dominant_color, not a second value for it.
                    kw = {"card_class": word, "card_dominant_color": colour,
                          "card_color_confidence": "high"}
                    if label == "colour dropped":
                        kw.pop("card_dominant_color")
                        kw.pop("card_color_confidence")
                    kw.update(degradation)
                    worse = resolve(**kw)
                    self.assertLessEqual(
                        severity(clean), severity(worse),
                        f"a clean {colour} read scores worse than the same card "
                        f"read with '{label}' — rewarding the worse photograph")

    def test_a_mapped_colour_that_agrees_confirms_rather_than_merely_survives(self):
        """The upside the ruling does NOT touch. Two independent signals
        agreeing is still the one confirmed state."""
        for colour, want in server._CARD_COLOR_CLASS_MAP.items():
            word = next(w for w, t in CLASS_WORDS.items() if t == want)
            with self.subTest(colour=colour):
                r = resolve(card_class=word, card_dominant_color=colour,
                            card_color_confidence="high")
                self.assertEqual(r["sst_type"], want)
                self.assertEqual(r["class_source"], "color_and_text")
                self.assertIsNone(r["review_reason"])


class AMappedColourThatContradictsStillFlags(unittest.TestCase):
    """THE OTHER HALF OF THE RULING, and the reason this is not simply
    'text always wins'. A colour the app HAS a meaning for, disagreeing with
    the printed class, is the strongest evidence available that something is
    unusual about this card. Falling through to text there would destroy it."""

    def test_every_mapped_colour_flags_against_every_class_it_is_not(self):
        for colour, proposed in server._CARD_COLOR_CLASS_MAP.items():
            for word, text_type in CLASS_WORDS.items():
                if text_type == proposed:
                    continue
                with self.subTest(colour=colour, card_class=word):
                    r = resolve(card_class=word, card_dominant_color=colour,
                                card_color_confidence="high")
                    self.assertEqual(r["sst_type"], server.SST_UNSPECIFIED)
                    self.assertEqual(r["class_source"], "conflict")
                    self.assertEqual(r["review_reason"], "CLASS_CONFLICTED")

    def test_a_conflict_scores_worse_than_the_same_card_with_no_colour(self):
        """Stated as the deliberate exception to the invariant above, so that
        the exception is itself asserted rather than merely carved out."""
        r = resolve(card_class="Worker", card_dominant_color="YELLOW",
                    card_color_confidence="high")
        self.assertGreater(severity(r), severity(resolve(card_class="Worker")))

    def test_but_only_a_USABLE_mapped_colour_may_do_it(self):
        """A contradiction reported under glare is not a contradiction; it is a
        bad look at a colour. Degrading the read must retire the flag, not
        keep it."""
        for degradation in ({"card_color_confidence": "low"},
                            {"card_color_conditions": ["SLEEVE"]}):
            with self.subTest(**degradation):
                kw = {"card_class": "Worker", "card_dominant_color": "YELLOW",
                      "card_color_confidence": "high"}
                kw.update(degradation)
                r = resolve(**kw)
                self.assertEqual(r["sst_type"], "SST_FULL")
                self.assertEqual(r["class_source"], "text_only")

    def test_purple_still_refuses_the_card_whatever_the_text_says(self):
        """PURPLE is the other meaningful colour and it is not in the map: a
        Worker Wallet is not an SST card of any class. Falling through to text
        here would reinstate the exact defect D6 was written to fix."""
        for word in CLASS_WORDS:
            with self.subTest(card_class=word):
                r = resolve(card_class=word,
                            card_dominant_color=server.SST_COLOR_WORKER_WALLET,
                            card_color_confidence="high")
                self.assertIsNone(r["sst_type"])
                self.assertEqual(r["not_sst"], server.CARD_NOT_SST_WORKER_WALLET)
                self.assertEqual(r["review_reason"], "CARD_NOT_SST")


class ADeadClassIsColourIndependent(unittest.TestCase):
    """SST_LIMITED is refused before colour is consulted at all, so no colour
    can rescue it and none can make it worse either. Asserted because the
    fall-through above moved code around this branch."""

    def test_no_colour_changes_the_verdict_on_a_limited_card(self):
        base = resolve(card_class="Limited")
        self.assertEqual(base["review_reason"], "CLASS_EXPIRED_SCHEME")
        for colour in PROMPT_COLOURS:
            if colour == server.SST_COLOR_WORKER_WALLET:
                continue  # the wrong card entirely; checked above
            with self.subTest(colour=colour):
                got = resolve(card_class="Limited", card_dominant_color=colour,
                              card_color_confidence="high")
                self.assertEqual(got["sst_type"], "SST_LIMITED")
                self.assertEqual(got["review_reason"], "CLASS_EXPIRED_SCHEME")


class NoReviewerIsToldToLookWithoutBeingToldWhatFor(unittest.TestCase):
    """THE LATENT HOLE, closed under the same letter. `derive_cert_review`
    could return needs_review=True with review_reason=None — a queue entry the
    reviewer cannot act on and cannot clear. Confirmed by execution before the
    fix:

        derive_cert_review(True, False, True, None, "text_only", None, None)
            -> (True, None, 0.5)

    ZERO ROWS IN PRODUCTION CARRY IT TODAY, so it was latent rather than live.
    It is closed anyway: the flag and its reason are derived by one function
    precisely so they cannot come apart, and 'no live rows' is a fact about
    today's inputs, not about the function.
    """

    def test_the_exact_input_that_produced_a_flag_with_no_reason(self):
        needs_review, reason, completeness = server.derive_cert_review(
            name_ok=True, number_ok=False, class_ok=True, stored_exp=None,
            class_source="text_only", gate_reason=None, resolver_reason=None)
        self.assertTrue(needs_review)
        self.assertEqual(reason, "EXTRACTION_INCOMPLETE")
        self.assertEqual(completeness, 0.5)

    def test_a_flag_always_names_a_reason_over_every_combination(self):
        """Exhaustive over the function's own inputs rather than over the
        inputs that happen to reach it today — the distinction the
        'latent, not live' note above turns on."""
        sources = [None, "color_and_text", "color_only", "text_only", "conflict"]
        gates = [None, "EXPIRY_UNPARSEABLE", "EXPIRY_IMPLAUSIBLE", "EXPIRY_CONFLICT"]
        resolvers = [None, "CLASS_UNVERIFIED", "CLASS_CONFLICTED",
                     "CLASS_FROM_COLOR_UNCONFIRMED", "CLASS_EXPIRED_SCHEME"]
        for name_ok, number_ok, class_ok, stored_exp, src, gate, res in itertools.product(
                (True, False), (True, False), (True, False), (None, "2029-06-01"),
                sources, gates, resolvers):
            needs_review, reason, _ = server.derive_cert_review(
                name_ok, number_ok, class_ok, stored_exp, src, gate, res)
            if needs_review:
                with self.subTest(name_ok=name_ok, number_ok=number_ok,
                                  class_ok=class_ok, stored_exp=stored_exp,
                                  class_source=src, gate=gate, resolver=res):
                    self.assertIsNotNone(
                        reason,
                        "flagged for review and told nothing about what to look at")

    def test_a_more_specific_reason_is_never_displaced_by_the_generic_one(self):
        """The close must not flatten the vocabulary. EXTRACTION_INCOMPLETE is
        a last resort, not a replacement."""
        for gate, res, want in (
                ("EXPIRY_IMPLAUSIBLE", None, "EXPIRY_IMPLAUSIBLE"),
                (None, "CLASS_CONFLICTED", "CLASS_CONFLICTED"),
                (None, "CLASS_FROM_COLOR_UNCONFIRMED", "CLASS_FROM_COLOR_UNCONFIRMED"),
                (None, "CLASS_EXPIRED_SCHEME", "CLASS_EXPIRED_SCHEME")):
            with self.subTest(gate=gate, resolver=res):
                _, reason, _ = server.derive_cert_review(
                    False, False, False, None, "text_only", gate, res)
                self.assertEqual(reason, want)

    def test_a_clean_row_is_still_clean_and_still_silent(self):
        """The other direction. A reason on a row that is NOT flagged is a
        complaint about a clean scan."""
        needs_review, reason, completeness = server.derive_cert_review(
            True, True, True, "2029-06-01", "text_only", None, None)
        self.assertFalse(needs_review)
        self.assertIsNone(reason)
        self.assertEqual(completeness, 1.0)

    def test_the_code_renders_as_words_rather_than_as_a_code(self):
        """A reason nothing can render is the same silence in a different
        font. The backend register names it; frontend/src/utils/sstFlagCopy.js
        and frontend/app/workers/[id].jsx carry the CP-facing wording, each with
        its own test."""
        self.assertIn("EXTRACTION_INCOMPLETE", server.OSHA_REVIEW_LABELS)
        self.assertNotEqual(server.OSHA_REVIEW_LABELS["EXTRACTION_INCOMPLETE"],
                            server.OSHA_REVIEW_LABELS["NEEDS_REVIEW"])

    def test_the_code_was_already_the_declared_vocabulary(self):
        """It is not a new word. WorkerCertification.review_reason has listed
        EXTRACTION_INCOMPLETE since the field was written; nothing emitted it."""
        i = SRC.index("class WorkerCertification(BaseModel):")
        self.assertIn("EXTRACTION_INCOMPLETE", SRC[i:i + 2500])


class TheWholeCardPathAgrees(unittest.TestCase):
    """THE RESOLVER IS NOT THE PRODUCT. The invariant has to survive the
    function that actually mints the certification row, because that is what
    reaches the worker's record and the gate."""

    def _cert(self, **kw):
        from datetime import datetime, timezone
        certs, _ = server.build_worker_certifications(
            [], ocr(**kw), "SST1", "img", datetime(2026, 8, 20, tzinfo=timezone.utc))
        self.assertEqual(len(certs), 1)
        return certs[0]

    def test_a_white_card_with_a_legible_class_is_not_flagged(self):
        c = self._cert(card_dominant_color="WHITE", card_color_confidence="high",
                       card_class="Worker")
        self.assertEqual(c["type"], "SST_FULL")
        self.assertFalse(c["needs_review"])
        self.assertIsNone(c["review_reason"])

    def test_and_it_reads_valid_at_the_gate_exactly_as_the_colourless_scan_does(self):
        from datetime import datetime, timezone
        now = datetime(2026, 8, 20, tzinfo=timezone.utc)
        white = self._cert(card_dominant_color="WHITE", card_color_confidence="high",
                           card_class="Worker")
        none = self._cert(card_class="Worker")
        self.assertEqual(server._sst_cert_state(white, now),
                         server._sst_cert_state(none, now))
        self.assertEqual(server._sst_cert_state(white, now), "valid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
