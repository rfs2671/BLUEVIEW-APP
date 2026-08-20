"""D6 — colour-first card classification.

WHY COLOUR LEADS, from the operator's field experience. These are the facts the
model is built on and every test below traces back to one of them:

  * A 40-HOUR SST WORKER CARD CARRIES NO CLASS TEXT. It is the most common card
    on a NYC site and OCR has nothing to read on it. Text cannot lead a signal
    it does not have.
  * TEXT WASHES OFF worn cards; card stock does not change colour.
  * PURPLE CARDS READ AS REGULAR SST TODAY — confidently wrong on a compliance
    record. That is the defect this replaces.

THE HARD CONSTRAINT: colour PROPOSES, never ASSERTS. "Cannot determine class
from this photo" is a first-class answer and better than a guess. A wrong class
on a compliance record is worse than an unknown one.

THE MAP (operator + DOB sources):
    BLUE   → SST_FULL         40-hour worker, the common card
    YELLOW → SST_SUPERVISOR   62-hour
    RED    → SST_TEMPORARY    10-hour OSHA course, SIX MONTHS, not five years
    PURPLE → NOT AN SST CARD  Worker Wallet — a different product entirely

Run:  python -m pytest backend/tests/test_d6_colour_first_class.py -q
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)
SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


def ocr(**kw):
    d = {
        "name": "Jane", "sst_number": "SST1", "card_type": "SST",
        "card_class": None, "issued": None, "expiration": "06/01/2029",
        "card_dominant_color": None, "card_color_confidence": None,
        "card_color_conditions": [],
    }
    d.update(kw)
    return d


def build(**kw):
    certs, _ = server.build_worker_certifications([], ocr(**kw), "SST1", "img", NOW)
    return certs


def one(**kw):
    certs = build(**kw)
    assert len(certs) == 1, f"expected one cert row, got {len(certs)}"
    return certs[0]


class TheMap(unittest.TestCase):

    def test_blue_is_the_forty_hour_worker_card(self):
        c = one(card_dominant_color="BLUE", card_color_confidence="high")
        self.assertEqual(c["type"], "SST_FULL")

    def test_yellow_is_supervisor(self):
        c = one(card_dominant_color="YELLOW", card_color_confidence="high")
        self.assertEqual(c["type"], "SST_SUPERVISOR")

    def test_red_is_temporary(self):
        c = one(card_dominant_color="RED", card_color_confidence="high")
        self.assertEqual(c["type"], "SST_TEMPORARY")

    def test_an_unmapped_colour_is_unknown_not_a_guess(self):
        """GREEN is not in the map. That is 'a card this app does not know',
        which is an answer — not a reason to fall back to text-wins."""
        c = one(card_dominant_color="GREEN", card_color_confidence="high",
                card_class="Supervisor")
        self.assertEqual(c["type"], server.SST_UNSPECIFIED)
        self.assertEqual(c["review_reason"], "CLASS_UNVERIFIED")


class PurpleIsTheWrongCard(unittest.TestCase):
    """THE DEFECT THIS REPLACES. A purple card is a Worker Wallet, not an SST
    credential of any class."""

    def test_no_certification_row_is_created_at_all(self):
        self.assertEqual(build(card_dominant_color="PURPLE",
                               card_color_confidence="high"), [])

    def test_not_even_sst_unspecified(self):
        """SST_UNSPECIFIED means 'an SST card whose class we could not read',
        and RECOGNIZED_SST_TYPES lets it satisfy the OSHA baseline. A Worker
        Wallet is not an SST card, so writing that would assert one exists."""
        for c in build(card_dominant_color="PURPLE", card_color_confidence="high"):
            self.assertNotIn(str(c.get("type")), server.RECOGNIZED_SST_TYPES)

    def test_sst_wording_on_a_purple_card_does_not_rescue_it(self):
        """The exact production failure: purple stock, SST-looking text. Text
        must not be able to talk the card back into being an SST card."""
        self.assertEqual(build(card_dominant_color="PURPLE",
                               card_color_confidence="high",
                               card_class="Worker"), [])

    def test_the_resolver_names_it_so_the_worker_can_be_told(self):
        r = server.resolve_card_class(ocr(card_dominant_color="PURPLE",
                                          card_color_confidence="high"))
        self.assertEqual(r["not_sst"], server.CARD_NOT_SST_WORKER_WALLET)
        self.assertEqual(r["review_reason"], "CARD_NOT_SST")
        self.assertIsNone(r["sst_type"])


class ColourProposesNeverAsserts(unittest.TestCase):

    def test_colour_alone_is_never_confirmed(self):
        c = one(card_dominant_color="BLUE", card_color_confidence="high")
        self.assertEqual(c["class_source"], "color_only")
        self.assertTrue(c["needs_review"])
        self.assertEqual(c["review_reason"], "CLASS_FROM_COLOR_UNCONFIRMED")

    def test_colour_alone_cannot_make_a_credential_valid(self):
        """THE CONSTRAINT, ENFORCED RATHER THAN DOCUMENTED. A future expiry and
        a named class would previously read `valid`; a colour-proposed class
        must read `unknown` until something confirms it."""
        c = one(card_dominant_color="BLUE", card_color_confidence="high")
        self.assertEqual(server._sst_cert_state(c, NOW), "unknown")

    def test_colour_and_text_agreeing_is_the_one_confirmed_state(self):
        c = one(card_dominant_color="YELLOW", card_color_confidence="high",
                card_class="Supervisor")
        self.assertEqual(c["class_source"], "color_and_text")
        self.assertFalse(c["needs_review"])
        self.assertEqual(server._sst_cert_state(c, NOW), "valid")

    def test_text_alone_keeps_the_verdict_it_always_had(self):
        """THE SCOPE OF THE DEMOTION, and a mistake worth recording.

        My first version demoted everything except colour-and-text, which swept
        up `text_only` — and until the client sends a colour, text_only is EVERY
        card. That turned "colour proposes" into "nothing is valid any more" and
        broke four existing tests that were right to break.

        Reading a class off the card was valid before this work and the ruling
        did not overturn it. What the ruling changed is that COLOUR may not do
        the same on its own. So the demotion is scoped to the colour-derived
        sources, and text_only is still marked as single-signal for a reviewer
        without being denied.
        """
        c = one(card_class="Worker")
        self.assertEqual(c["class_source"], "text_only")
        self.assertIsNone(c["review_reason"],
                          'a reason on an unflagged row is a complaint about a clean scan')
        self.assertEqual(server._sst_cert_state(c, NOW), "valid")

    def test_rows_predating_colour_keep_their_old_verdict(self):
        """No class_source means the row is older than this work. Treating
        absence as 'unconfirmed' would silently invalidate every historical
        row, which is a migration, not a gate rule."""
        legacy = {"type": "SST_FULL", "expiration_date": datetime(2029, 1, 1, tzinfo=timezone.utc)}
        self.assertEqual(server._sst_cert_state(legacy, NOW), "valid")


class CannotDetermineIsAFirstClassAnswer(unittest.TestCase):

    def test_a_sleeve_or_cast_disqualifies_the_colour(self):
        """The model is asked for card_color_conditions precisely so this
        branch exists rather than being inferred from a confidence number."""
        for cond in (["SLEEVE"], ["GLARE"], ["COLOR_CAST"], ["SHADE"]):
            with self.subTest(cond=cond):
                c = one(card_dominant_color="BLUE", card_color_confidence="high",
                        card_color_conditions=cond)
                self.assertEqual(c["type"], server.SST_UNSPECIFIED)
                self.assertEqual(c["review_reason"], "CLASS_UNVERIFIED")

    def test_low_or_medium_confidence_does_not_classify(self):
        for conf in ("low", "medium", "", None):
            with self.subTest(conf=conf):
                c = one(card_dominant_color="BLUE", card_color_confidence=conf)
                self.assertEqual(c["type"], server.SST_UNSPECIFIED)

    def test_nothing_read_at_all(self):
        c = one()
        self.assertEqual(c["type"], server.SST_UNSPECIFIED)
        self.assertEqual(c["review_reason"], "CLASS_UNVERIFIED")
        self.assertIsNone(c["class_source"])


class WhenColourAndTextDisagree(unittest.TestCase):
    """NEITHER WINS. 'Colour leads' governs which signal is trusted when the
    other is ABSENT; it does not settle a contradiction."""

    def test_the_type_is_neither_candidate(self):
        c = one(card_dominant_color="BLUE", card_color_confidence="high",
                card_class="Supervisor")
        self.assertEqual(c["type"], server.SST_UNSPECIFIED)
        self.assertNotEqual(c["type"], "SST_FULL")
        self.assertNotEqual(c["type"], "SST_SUPERVISOR")

    def test_it_has_its_own_reason_distinct_from_unverified(self):
        """'We could not read it' and 'two things disagree' send a reviewer
        looking for different things. A conflict may be a reissue, a lookalike,
        someone else's sleeve, or a forgery."""
        c = one(card_dominant_color="BLUE", card_color_confidence="high",
                card_class="Supervisor")
        self.assertEqual(c["review_reason"], "CLASS_CONFLICTED")
        self.assertEqual(c["class_source"], "conflict")

    def test_both_candidates_are_retained_for_the_reviewer(self):
        c = one(card_dominant_color="BLUE", card_color_confidence="high",
                card_class="Supervisor")
        self.assertEqual(c["card_color_seen"], "BLUE")

    def test_a_conflict_is_never_valid(self):
        c = one(card_dominant_color="BLUE", card_color_confidence="high",
                card_class="Supervisor")
        self.assertEqual(server._sst_cert_state(c, NOW), "unknown")


class RedExpiresInSixMonths(unittest.TestCase):
    """RED's SECOND CONSEQUENCE. A temporary card is issued on a 10-hour OSHA
    course and lives SIX MONTHS from issue, not five years."""

    def test_a_five_year_expiry_on_a_temporary_card_is_suppressed(self):
        """Against the flat 7-year ceiling this cleared silently, and the card
        would have read valid for years past its life."""
        c = one(card_dominant_color="RED", card_color_confidence="high",
                issued="01/01/2026", expiration="01/01/2031")
        self.assertIsNone(c["expiration_date"])
        self.assertEqual(c["review_reason"], "EXPIRY_IMPLAUSIBLE")
        self.assertEqual(c["expiration_raw_rejected"], "01/01/2031")

    def test_a_four_month_expiry_is_kept(self):
        c = one(card_dominant_color="RED", card_color_confidence="high",
                issued="01/01/2026", expiration="05/01/2026")
        self.assertIsNotNone(c["expiration_date"])

    def test_the_tight_ceiling_applies_ONLY_to_temporary(self):
        """A five-year expiry on an ordinary worker card is normal and must not
        be suppressed. Tightening the bound on a card we cannot identify would
        break the common case."""
        c = one(card_dominant_color="BLUE", card_color_confidence="high",
                issued="01/01/2026", expiration="01/01/2031")
        self.assertIsNotNone(c["expiration_date"])
        self.assertNotEqual(c["review_reason"], "EXPIRY_IMPLAUSIBLE")

    def test_the_bound_is_named_not_inlined(self):
        self.assertEqual(server.SST_TEMPORARY_VALID_MONTHS, 6)


class LimitedIsADeadScheme(unittest.TestCase):
    """30-hour transitional card; ceased to be valid August 2020. If one
    appears it is an INVALID card, not a class."""

    def test_it_is_recognised_and_flagged_not_silently_accepted(self):
        c = one(card_class="Limited")
        self.assertEqual(c["review_reason"], "CLASS_EXPIRED_SCHEME")
        self.assertTrue(c["needs_review"])

    def test_a_future_expiry_does_not_revive_it(self):
        c = one(card_class="Limited")
        self.assertEqual(server._sst_cert_state(c, NOW), "unknown")


class TheMapperReadsTheWordOnTheCard(unittest.TestCase):

    def test_worker_maps_to_the_forty_hour_class(self):
        """The accepted vocabulary was FULL / COMPLETE / LIMIT / SUPERV, and the
        40-hour credential is printed 'Worker' — so a correctly-read worker card
        matched nothing and fell to SST_UNSPECIFIED."""
        self.assertEqual(server._map_sst_class("Worker"), "SST_FULL")
        self.assertEqual(server._map_sst_class("SST WORKER"), "SST_FULL")

    def test_the_existing_words_still_map(self):
        self.assertEqual(server._map_sst_class("Supervisor"), "SST_SUPERVISOR")
        self.assertEqual(server._map_sst_class("Temporary"), "SST_TEMPORARY")
        self.assertEqual(server._map_sst_class("Full"), "SST_FULL")
        self.assertEqual(server._map_sst_class("Limited"), "SST_LIMITED")
        self.assertEqual(server._map_sst_class("nonsense"), server.SST_UNSPECIFIED)


class TheMapIsNotInThePrompt(unittest.TestCase):
    """Structural. A colour→class table in the prompt would let the model work
    backwards from a class it read, would be a rule no test can assert against,
    and would make the MODEL the thing that decides the class."""

    def _prompt(self):
        i = SRC.index("extraction_prompt = (")
        return SRC[i:SRC.index("\n\n", i)]

    def test_the_prompt_asks_for_colour(self):
        p = self._prompt()
        self.assertIn("card_dominant_color", p)
        self.assertIn("card_color_confidence", p)
        self.assertIn("card_color_conditions", p)

    def test_the_prompt_names_no_class_and_no_mapping(self):
        p = self._prompt()
        for forbidden in ("SST_FULL", "SST_SUPERVISOR", "SST_TEMPORARY",
                          "Worker Wallet", "WORKER_WALLET"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, p)

    def test_the_prompt_forbids_inferring_colour_from_words(self):
        """Load-bearing for the purple case: a Training Connect card with
        legible SST wording is exactly where a model would report the colour it
        expects rather than the one it sees."""
        self.assertIn("Do NOT infer the colour from any", self._prompt())

    def test_the_map_lives_in_python(self):
        self.assertEqual(
            server._CARD_COLOR_CLASS_MAP,
            {"BLUE": "SST_FULL", "YELLOW": "SST_SUPERVISOR", "RED": "SST_TEMPORARY"})
        self.assertNotIn("PURPLE", server._CARD_COLOR_CLASS_MAP,
                         "purple must not map to any SST class")


if __name__ == "__main__":
    unittest.main(verbosity=2)
