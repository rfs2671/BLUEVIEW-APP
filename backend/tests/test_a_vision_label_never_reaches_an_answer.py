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

import inspect
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


class NoLabelIsWrittenIntoTheTextThatIsSearched(unittest.TestCase):
    """The mechanism, at the writer: a chunk's text renders `meaning`, never
    `label`, so there is nothing for a reader to find and quote."""

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

    # The two tests that asked this of every question shape went with the
    # matcher. What they held — that no shape of question can quote a label,
    # and that the printed mark is still sayable — is held below against the
    # reader that answers now, over the same legend.


class NoLabelReachesTheFallbackRender(unittest.TestCase):
    """The typed-record path's fallback, held to the same rule.

    Measured by the plan eval on 2026-09-17. Asked 'what is a kicker', search
    returned the two legend entries on M-104.00 — quotes 'KE 1' and 'KE 2',
    labels 'KICKER EXHAUST 1' and 'KICKER EXHAUST 2', both matched ONLY
    through the label. render_records printed no label and still replied

        Kicker — on the drawings:
        M-104.00 (legend_entry): KE 1 — read from the drawing image ...

    The header supplied the word, the line supplied the mark, and together they
    said the mark is a kicker. KICKER is printed on no page of this project.
    A rule that only checks whether the label string appears would pass this.
    """

    def records(self):
        from lib import plan_records as pr
        entries, _f = pe.constrain_legend_to_page(
            [{"symbol": "KE 1", "meaning": "KICKER EXHAUST 1"},
             {"symbol": "PTAC-1", "meaning": "PACKAGE TERMINAL AIR CONDITIONER"}],
            PAGE_TEXT)
        fields = dict(pe.EMPTY_FIELDS, sheet_number="M-104.00", legend=entries)
        return pr.build_records(fields, page={"sheet_number": "M-104.00",
                                              "page_number": 6},
                                raw_text=PAGE_TEXT)

    ASKED = ("what is a kicker", "kicker", "kicker exhaust",
             "air conditioner", "package terminal air conditioner")
    BANNED = ("KICKER", "PACKAGE TERMINAL", "AIR CONDITIONER")

    def test_the_ranker_still_sees_the_label(self):
        # rank() still matches on labels. What changed is that search_plans
        # then declines to OFFER a record whose only tie is the label — see
        # NoLabelOnlyMatchReachesTheComposingModel.
        from lib import plan_search as ps
        for q in ("kicker", "air conditioner"):
            with self.subTest(q=q):
                self.assertTrue(ps.rank(self.records(), ps.search_terms(q)))

    def test_no_label_is_said_in_any_form(self):
        from lib import plan_search as ps
        recs = self.records()
        for q in self.ASKED:
            found = ps.rank(recs, ps.search_terms(q))
            out = ps.render_records(found, q)
            for banned in self.BANNED:
                with self.subTest(q=q, banned=banned):
                    self.assertNotIn(banned, out.upper(),
                                     f"the fallback said {banned!r} for {q!r}: {out!r}")

    def test_a_mark_found_only_through_a_label_is_not_offered_as_the_answer(self):
        from lib import plan_search as ps
        found = ps.rank(self.records(), ps.search_terms("kicker"))
        self.assertTrue(found)
        self.assertEqual(ps.render_records(found, "kicker"),
                         "Not on the indexed drawings.")

    def test_the_mark_is_still_said_when_the_question_names_the_mark(self):
        # KE 1 is printed. Asked about KE 1, it may be shown — as a mark.
        from lib import plan_search as ps
        found = ps.rank(self.records(), ps.search_terms("KE 1"))
        out = ps.render_records(found, "KE 1")
        self.assertIn("KE 1", out)
        for banned in self.BANNED:
            with self.subTest(banned=banned):
                self.assertNotIn(banned, out.upper())


class NoLabelOnlyMatchReachesTheComposingModel(unittest.TestCase):
    """The composed path, which was believed to hold this rule and did not.

    The model is never shown a label. It IS shown the question and whatever
    search_plans returns, and for 'what is a kicker' that was 'KE 1' and
    'KE 2' — records whose only tie to the question is the label. The gate's
    contains_label looks for the label string ('KICKER EXHAUST 1') and would
    pass 'KE 1 is a kicker'. So the rule is applied where both paths draw from.
    """

    def test_search_plans_drops_label_only_matches_before_anything_sees_them(self):
        import server
        src = inspect.getsource(server.search_plans)
        self.assertIn("matched_only_through_label(", src)
        i = src.index("matched_only_through_label(")
        # After ranking, before the attribute dedupe and the limit.
        self.assertLess(src.index("plan_search.rank("), i)
        self.assertLess(i, src.index("best_per_attribute("))

    def test_what_the_model_is_shown_comes_only_from_search_plans(self):
        import server
        src = inspect.getsource(server._dispatch_agent_tool)
        i = src.index('if name == "search_plans"')
        block = src[i:i + 1500]
        self.assertIn("await search_plans(", block)
        self.assertIn("_render_records_for_model(found", block)

    def test_the_rule_itself(self):
        from lib import plan_search as ps
        ke = {"quote": "KE 1", "label": "KICKER EXHAUST 1",
              "subject_terms": ["KE 1"], "tier": pe.TIER_VISION}
        self.assertTrue(ps.matched_only_through_label(ke, ps.search_terms("kicker")))
        # Asked about the mark itself, it is a printed match.
        self.assertFalse(ps.matched_only_through_label(ke, ps.search_terms("KE 1")))
        # A record that matches on printed words is kept, whatever its label.
        both = dict(ke, quote="KE 1 KICKER")
        self.assertFalse(ps.matched_only_through_label(both, ps.search_terms("kicker")))


class AVisionCountSaysSo(unittest.TestCase):

    def test_an_element_with_no_basis_is_stamped_rather_than_left_blank(self):
        import inspect
        src = inspect.getsource(pe.extract_page)
        self.assertIn('_el["count_basis"] = TIER_VISION', src)

    def test_the_tier_names_are_a_closed_set(self):
        self.assertEqual(pe.EVIDENCE_TIERS,
                         (pe.TIER_SCHEDULE_CELL, pe.TIER_OCR_GRID,
                          pe.TIER_TAG_LEGEND, pe.TIER_TEXT_LAYER,
                          pe.TIER_OCR_FREEFORM, pe.TIER_VISION))
        self.assertEqual(pe.TIER_VISION, "vision_read")

    def test_no_confidence_number_anywhere_in_the_tier_vocabulary(self):
        for t in pe.EVIDENCE_TIERS:
            with self.subTest(tier=t):
                self.assertFalse(any(ch.isdigit() for ch in t),
                                 "a tier is how a record was extracted, not a score")


if __name__ == "__main__":
    unittest.main()
