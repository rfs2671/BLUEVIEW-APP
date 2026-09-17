"""search_plans ranking: four rules, each stated on its own terms.

These are written from the rules, not from the eval's cases, and use none of
the eval's subjects. A ranking tuned until a fixed set of questions passes has
learned the questions; these hold the behaviour the questions were meant to
probe.

  1. A term is a WORD. 'air' does not match STAIRS. A plural is the same word.
  2. SIMILARITY FIRST. How much of the question a record's PRINTED words
     contain decides; tier breaks ties; a label never lifts a record.
  3. The same words printed twice on one page are ONE record.
  4. A stronger tier displaces a weaker one only for the SAME attribute on the
     SAME page — and the database's candidate cap never decides what is ranked.
"""

import inspect
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_extract as pe  # noqa: E402
from lib import plan_search as ps  # noqa: E402

SC, OCR, TL, TXT, VIS = (pe.TIER_SCHEDULE_CELL, pe.TIER_OCR_GRID,
                         pe.TIER_TAG_LEGEND, pe.TIER_TEXT_LAYER, pe.TIER_VISION)


def rec(quote, tier=TXT, rtype="text", page="p1", ordinal=0, **kw):
    r = {"quote": quote, "tier": tier, "record_type": rtype, "page_id": page,
         "ordinal": ordinal, "sheet_number": kw.pop("sheet", "X-1"),
         "subject_terms": kw.pop("terms", []), "label": kw.pop("label", None),
         "payload": kw.pop("payload", {})}
    r.update(kw)
    return r


def ranked_quotes(records, subject, intent=None):
    return [r["quote"] for r in ps.rank(records, ps.search_terms(subject), intent)]


class ATermIsAWord(unittest.TestCase):

    def match(self, term, text):
        return bool(re.search(ps.term_pattern(term), text, re.I))

    def test_a_term_inside_a_longer_word_does_not_match(self):
        for term, text in (("air", "STAIRS"), ("air", "REPAIR"),
                           ("ac", "SPACE"), ("ac", "EACH"),
                           ("unit", "COMMUNITY"), ("pump", "PUMPKIN"),
                           ("gas", "GASKET"), ("cap", "LANDSCAPE")):
            with self.subTest(term=term, text=text):
                self.assertFalse(self.match(term, text))

    def test_a_term_standing_on_its_own_matches(self):
        for term, text in (("air", "AIR HANDLER"), ("air", "SUPPLY AIR"),
                           ("pump", "SUMP PUMP"), ("sp", "SP-1")):
            with self.subTest(term=term, text=text):
                self.assertTrue(self.match(term, text))

    def test_hyphens_slashes_and_quote_marks_are_boundaries(self):
        for term, text in (("sp", "SP-104"), ("fd", "FD/SD"),
                           ('36"', '36" GUARDRAIL'), ("cab", "(CAB)")):
            with self.subTest(term=term, text=text):
                self.assertTrue(self.match(term, text))

    def test_a_plural_is_the_same_word_both_ways(self):
        for term, text in (("pump", "PUMPS"), ("pumps", "SUMP PUMP"),
                           ("box", "BOXES"), ("switches", "SWITCH"),
                           ("valve", "VALVES")):
            with self.subTest(term=term, text=text):
                self.assertTrue(self.match(term, text))

    def test_the_plural_rule_is_not_a_stemmer(self):
        # PILES is PILE + S. Stripping ES would invent PIL. GAS is not a
        # plural of GA.
        self.assertNotIn("pil", ps.term_forms("piles"))
        self.assertFalse(self.match("gas", "20 GA STEEL"))
        self.assertFalse(self.match("valve", "VALVED"))

    def test_the_database_uses_the_same_pattern(self):
        import server
        src = inspect.getsource(server.search_plans)
        self.assertIn("plan_search.term_pattern(t)", src)
        self.assertNotIn('re.escape(t), "$options"', src)

    def test_a_record_found_only_inside_another_word_is_not_ranked(self):
        self.assertEqual(ranked_quotes([rec("STAIR 2 NOTES")], "air"), [])


class SimilarityFirstTierBreaksTies(unittest.TestCase):

    def test_a_full_match_at_a_lower_tier_beats_a_one_word_overlap_at_a_higher_one(self):
        partial = rec("PIT DETAIL SCHEDULE", tier=SC, rtype="schedule")
        full = rec("SUMP PUMP IN ELEVATOR PIT", tier=TXT, page="p2")
        self.assertEqual(ranked_quotes([partial, full], "sump pump pit"),
                         ["SUMP PUMP IN ELEVATOR PIT", "PIT DETAIL SCHEDULE"])

    def test_ties_on_coverage_go_to_the_stronger_tier(self):
        weak = rec("SUMP PUMP", tier=VIS, source="vision", ordinal=1)
        mid = rec("SUMP PUMP", tier=TXT, page="p2")
        strong = rec("SUMP PUMP SP-1 | 1", tier=SC, rtype="schedule", page="p3")
        got = ps.rank([weak, mid, strong], ps.search_terms("sump pump"))
        self.assertEqual([r["tier"] for r in got], [SC, TXT, VIS])

    def test_more_of_the_question_beats_a_stronger_tier_with_less(self):
        one = rec("PUMP SCHEDULE", tier=SC, rtype="schedule")
        two = rec("SUMP PUMP", tier=VIS, source="vision", page="p2")
        got = ps.rank([one, two], ps.search_terms("sump pump"))
        self.assertEqual(got[0]["quote"], "SUMP PUMP")

    def test_a_label_admits_a_record_and_never_lifts_it(self):
        # Both print only 'pump'. The first also carries a label that spells
        # out the whole question; that must not move it ahead of a stronger
        # tier — it is words the sheet does not print.
        labelled = rec("P-1 PUMP", tier=VIS, source="vision",
                       label="SUMP PUMP IN PIT")
        plain = rec("PUMP P-2", tier=SC, rtype="schedule", page="p2")
        got = ps.rank([labelled, plain], ps.search_terms("sump pump pit"))
        self.assertEqual(got[0]["quote"], "PUMP P-2")

    def test_the_printed_score_ignores_the_label(self):
        r = rec("P-1", label="SUMP PUMP")
        terms = ps.search_terms("sump pump")
        self.assertGreater(ps.match_score(r, terms), 0)
        self.assertEqual(ps.printed_score(r, terms)[0], 0)

    def test_density_only_orders_records_that_tie_on_coverage_and_tier(self):
        short = rec("SUMP PUMP", ordinal=2)
        long = rec("PROVIDE SUMP PUMP WITH ALARM AND CHECK VALVE PER DETAIL "
                   "4 ON THIS SHEET AND COORDINATE WITH ELECTRICAL", ordinal=1)
        self.assertEqual(ranked_quotes([long, short], "sump pump")[0], "SUMP PUMP")

    def test_intent_still_only_orders(self):
        a = rec("SUMP PUMP", rtype="note", ordinal=1)
        b = rec("SUMP PUMP", rtype="callout", page="p2")
        got = ps.rank([a, b], ps.search_terms("sump pump"), intent="location")
        self.assertEqual([r["record_type"] for r in got], ["callout", "note"])
        self.assertEqual(len(got), 2)


class TheSameWordsOnOnePageAreOneRecord(unittest.TestCase):

    def test_repeats_on_one_page_collapse(self):
        repeats = [rec('36" GUARDRAIL', ordinal=i) for i in range(6)]
        other = rec('36" GUARDRAIL', page="p2", sheet="X-2")
        got = ps.rank(repeats + [other], ps.search_terms("guardrail"))
        self.assertEqual(len(got), 2)
        self.assertEqual({r["page_id"] for r in got}, {"p1", "p2"})

    def test_the_same_words_on_two_pages_are_two_citations(self):
        a = rec("SUMP PUMP", page="p1")
        b = rec("SUMP PUMP", page="p2")
        self.assertEqual(len(ps.dedupe_quotes([a, b])), 2)

    def test_the_copy_kept_is_the_strongest_then_the_most_structured(self):
        text = rec("SP-1", rtype="text", ordinal=0)
        tag = rec("SP-1", rtype="tag", ordinal=1)
        seen = rec("SP-1", rtype="element", tier=VIS, ordinal=2)
        kept = ps.dedupe_quotes([text, tag, seen])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["record_type"], "tag")

    def test_whitespace_and_case_do_not_make_a_different_line(self):
        self.assertEqual(len(ps.dedupe_quotes(
            [rec("SUMP  PUMP"), rec("sump pump", ordinal=1)])), 1)

    def test_pages_with_no_sheet_number_are_still_separate_pages(self):
        a = rec("SUMP PUMP", page=None, sheet=None, file_name="A.pdf", page_number=1)
        b = rec("SUMP PUMP", page=None, sheet=None, file_name="A.pdf", page_number=2)
        self.assertEqual(len(ps.dedupe_quotes([a, b])), 2)

    def test_it_happens_inside_rank(self):
        self.assertIn("dedupe_quotes(", inspect.getsource(ps.rank))


class AStrongerTierDisplacesOnlyTheSameAttribute(unittest.TestCase):

    def test_the_same_mark_on_the_same_page_keeps_only_the_stronger(self):
        strong = rec("SP-1 count 2", tier=SC, rtype="element",
                     payload={"tag": "SP-1"}, ordinal=0)
        weak = rec("SP-1 count 5", tier=VIS, rtype="element",
                   payload={"tag": "SP-1"}, ordinal=1)
        kept = ps.best_per_attribute(ps.rank([weak, strong], ps.search_terms("sp-1")))
        self.assertEqual([r["quote"] for r in kept], ["SP-1 count 2"])

    def test_unrelated_notes_on_one_page_are_not_the_same_attribute(self):
        # The old key was (sheet, type, "") for anything without a mark, so a
        # vision-read note vanished whenever the sheet had ANY text-layer note.
        mine = rec("1. SUMP PUMP BY PLUMBER", rtype="note", tier=TXT, ordinal=0)
        other = rec("2. SUMP PIT LINER BY OTHERS", rtype="note", tier=VIS,
                    source="vision", ordinal=1)
        kept = ps.best_per_attribute(ps.rank([mine, other], ps.search_terms("sump")))
        self.assertEqual(len(kept), 2)

    def test_the_same_mark_on_another_page_is_its_own_attribute(self):
        a = rec("SP-1 count 2", tier=SC, rtype="element", payload={"tag": "SP-1"})
        b = rec("SP-1 count 5", tier=VIS, rtype="element", payload={"tag": "SP-1"},
                page="p2")
        self.assertEqual(len(ps.best_per_attribute(
            ps.rank([a, b], ps.search_terms("sp-1")))), 2)

    def test_the_rank_order_is_kept(self):
        ranked = ps.rank([rec("SUMP PUMP", ordinal=1),
                          rec("SUMP PUMP SCHEDULE", tier=SC, rtype="schedule",
                              payload={"name": "SUMP PUMP SCHEDULE"}, page="p2")],
                         ps.search_terms("sump pump"))
        self.assertEqual(ps.best_per_attribute(ranked), ranked)

    def test_a_weaker_copy_is_dropped_even_when_it_ranks_first(self):
        # Ranking is no longer tier-ordered, so the strongest tier per
        # attribute is found before anything is dropped.
        weak = rec("SP-1 SUMP PUMP", tier=VIS, rtype="legend_entry",
                   payload={"symbol": "SP-1"}, ordinal=0)
        strong = rec("SP-1", tier=TL, rtype="legend_entry",
                     payload={"symbol": "SP-1"}, ordinal=1)
        kept = ps.best_per_attribute([weak, strong])
        self.assertEqual([r["tier"] for r in kept], [TL])


class TheCapDoesNotDecideWhatIsRanked(unittest.TestCase):

    def setUp(self):
        import server
        self.server = server
        self.src = inspect.getsource(server.search_plans)

    def test_records_with_every_term_are_fetched_before_the_rest(self):
        i_all = self.src.index('"$and": [{"$or": ors} for ors in per_term]')
        i_any = self.src.index('"$or": [c for ors in per_term for c in ors]')
        self.assertLess(i_all, i_any)

    def test_the_ceiling_is_far_above_the_commonest_word(self):
        # 'floor' matched 578 records on 588 Boyland; the old cap was 400.
        self.assertGreaterEqual(self.server.SEARCH_PLANS_CANDIDATES, 2000)
        self.assertNotIn(".limit(400).to_list(400)", self.src)

    def test_hitting_it_is_logged(self):
        self.assertIn("candidate cap", self.src)


if __name__ == "__main__":
    unittest.main()
