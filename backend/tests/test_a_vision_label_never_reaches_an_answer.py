"""A vision-read label widens the search. It never becomes the answer.

The M-sheet legends on 588 Boyland are drawn as artwork. Measured over the
whole re-indexed corpus, 2026-09-16: `PACKAGE TERMINAL AIR CONDITIONER`
appears on ZERO pages' text layer. So do `KITCHEN EXHAUST`, `TOILET EXHAUST`
and `SUPPLY AIR`. So do `KICKER`, `THERMOSTATIC EXPANSION VALVE` and
`SPLIT AIR`.

All six came from the vision model reading the image — three of them right and
three of them invented — and nothing in the text can tell which is which. That
is why none of them may be a meaning.

Dropping them outright cost real recall: PTAC-1 became a bare mark on six
sheets and the words "air conditioner" left the project entirely. So they are
kept as `label` at TIER_VISION, where they can be matched against and never
quoted.

The rule this file holds: THE WORDS A READER SEES COME FROM A TEXT-LAYER FACT
OR FROM THE SHEET'S OWN PRINTED TEXT. If KICKER can reach an answer, so can
every other thing the model supplied for a mark it could not read.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_extract as pe  # noqa: E402

# A page whose legend the model read off the image: the marks are printed, the
# expansions are not. One expansion is right, one is invented, and the page
# text cannot tell them apart — which is the whole point.
PAGE_TEXT = ("MECHANICAL PLAN\nAPT 1A APT 1B\nUP 16 DN 16\n"
             "PTAC-1 KE 1\n" + "GENERAL MECHANICAL NOTES. " * 24)
RAW_LEGEND = [
    {"symbol": "PTAC-1", "meaning": "PACKAGE TERMINAL AIR CONDITIONER"},
    {"symbol": "KE 1", "meaning": "KICKER 1"},
]


class WhatSurvivesTheCheck(unittest.TestCase):

    def setUp(self):
        self.entries, self.flags = pe.constrain_legend_to_page(RAW_LEGEND, PAGE_TEXT)

    def test_the_mark_survives_and_the_meaning_does_not(self):
        self.assertEqual([(e["symbol"], e["meaning"]) for e in self.entries],
                         [("PTAC-1", ""), ("KE 1", "")])

    def test_the_words_are_kept_as_a_label_at_the_vision_tier(self):
        self.assertEqual([(e["label"], e["tier"]) for e in self.entries],
                         [("PACKAGE TERMINAL AIR CONDITIONER", pe.TIER_VISION),
                          ("KICKER 1", pe.TIER_VISION)])

    def test_a_meaning_the_page_does_print_is_a_higher_tier(self):
        out, _f = pe.constrain_legend_to_page(
            [{"symbol": "KE 1", "meaning": "KITCHEN EXHAUST 1"}],
            PAGE_TEXT + "\nKE 1 KITCHEN EXHAUST 1\n")
        self.assertEqual(out[0]["tier"], pe.TIER_TAG_LEGEND)
        self.assertEqual(out[0]["meaning"], "KITCHEN EXHAUST 1")
        self.assertNotIn("label", out[0])


class NoLabelReachesAnAnswer(unittest.TestCase):
    """The composed answer, for every shape of question the dispatch makes."""

    def _chunks(self):
        entries, _f = pe.constrain_legend_to_page(RAW_LEGEND, PAGE_TEXT)
        fields = dict(pe.EMPTY_FIELDS, sheet_number="M-100.00",
                      sheet_title="HVAC PLAN", legend=entries,
                      tag_counts=[{"tag": "PTAC-1", "count": 3,
                                   "source": "text-layer tag count"}])
        chunks = pe.build_chunks(fields)
        for c in chunks:
            c["sheet_number"] = "M-100.00"
            c["file_name"] = "MH - 7.2.26.pdf"
            c["page_number"] = 1
        return chunks

    BANNED = ("PACKAGE TERMINAL", "AIR CONDITIONER", "KICKER")

    def test_the_label_is_not_in_any_chunk_text(self):
        # build_chunks renders `meaning`, never `label`. This is the mechanism,
        # not a filter applied later that someone could forget to apply.
        for c in self._chunks():
            for banned in self.BANNED:
                with self.subTest(chunk=c["chunk_type"], banned=banned):
                    self.assertNotIn(banned, (c.get("text") or "").upper())

    def test_it_is_still_on_the_record_for_the_search_to_use(self):
        legend = [c for c in self._chunks() if c["chunk_type"] == "legend"]
        self.assertTrue(legend, "no legend chunk was written")
        labels = [e.get("label") for e in legend[0]["payload"]]
        self.assertIn("PACKAGE TERMINAL AIR CONDITIONER", labels)

    def test_no_question_shape_can_quote_it(self):
        chunks = self._chunks()
        asked = [
            "what type of AC units are in the building",
            "how many ptac units",
            "are there ptac units",
            "Whats the PTAC-1",
            "what is KE 1",
            "how many KE 1",
            "kicker",
            "air conditioner",
        ]
        for q in asked:
            a = pe.answer_question(chunks, q, None)
            text = (a or {}).get("text", "")
            for banned in self.BANNED:
                with self.subTest(q=q, banned=banned):
                    self.assertNotIn(banned, text.upper(),
                                     f"a vision label reached the answer to {q!r}: {text!r}")

    def test_the_mark_itself_is_still_answerable(self):
        # The point is not to make the record unreachable — it is to make the
        # WORDS unquotable. PTAC-1 is printed on the sheet and may be said.
        a = pe.answer_question(self._chunks(), "are there ptac units", None)
        self.assertIsNotNone(a)
        self.assertIn("PTAC-1", a["text"].upper())


class AVisionCountSaysSo(unittest.TestCase):

    def test_an_element_with_no_basis_is_stamped_rather_than_left_blank(self):
        import inspect
        src = inspect.getsource(pe.extract_page)
        self.assertIn('_el["count_basis"] = TIER_VISION', src)

    def test_the_tier_names_are_a_closed_set(self):
        self.assertEqual(pe.EVIDENCE_TIERS,
                         (pe.TIER_SCHEDULE_CELL, pe.TIER_TAG_LEGEND,
                          pe.TIER_TEXT_LAYER, pe.TIER_VISION))
        self.assertEqual(pe.TIER_VISION, "vision_read")

    def test_no_confidence_number_anywhere_in_the_tier_vocabulary(self):
        for t in pe.EVIDENCE_TIERS:
            with self.subTest(tier=t):
                self.assertFalse(any(ch.isdigit() for ch in t),
                                 "a tier is how a record was extracted, not a score")


if __name__ == "__main__":
    unittest.main()
