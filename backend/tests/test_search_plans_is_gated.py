"""The agent composes; the gate decides whether what it composed may be sent.

WHY A CHECK ON THE OUTPUT AND NOT A LINE IN THE PROMPT
======================================================

The tool description already tells the model to use only the numbers it was
shown. That instruction is worth having and it is not a guarantee: a model
that has just been handed a schedule with 21 in it will write "about 40 units"
when the question implies a building, and the sentence reads exactly like a
measured one. On a jobsite that is the worst failure this product has.

So every number in a composed answer is checked against the records that were
actually returned, and an answer that fails is REPLACED — not edited, not
annotated — by a render of the records themselves, which can only say what the
sheets say.

THE THREE THINGS THIS FILE HOLDS
================================

  1. Tier before similarity, and never a lower tier when a higher one exists
     for the same attribute on the same sheet.
  2. A number with nothing behind it does not reach a person.
  3. A vision-read label widens the search and never becomes the answer.
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
from lib import plan_search as ps  # noqa: E402


def rec(**over):
    base = {"record_type": "text", "tier": pe.TIER_TEXT_LAYER, "source": "text_layer",
            "quote": "", "label": None, "subject_terms": [], "payload": {},
            "sheet_number": "M-200.00", "page_number": 9, "ordinal": 0,
            "file_name": "MH - 7.2.26.pdf"}
    base.update(over)
    return base


# The real shape of the M-sheet problem: the mark is printed, the words are not.
SCHEDULE = rec(record_type="schedule", tier=pe.TIER_SCHEDULE_CELL,
               quote="PTAC UNITS SCHEDULE\nUNIT NO. | QTY\nPTAC-1 | 21",
               subject_terms=["PTAC UNITS SCHEDULE"],
               payload={"rows": [["PTAC-1", "21"]]})
NOTE = rec(record_type="note", tier=pe.TIER_TEXT_LAYER,
           quote="3. PROVIDE WALL SLEEVE FOR EACH PTAC UNIT")
VISION_LEGEND = rec(record_type="legend_entry", tier=pe.TIER_VISION, source="vision",
                    quote="PTAC-1", label="PACKAGE TERMINAL AIR CONDITIONER",
                    subject_terms=["PTAC-1"])


class TierBeforeSimilarity(unittest.TestCase):

    def test_a_schedule_cell_outranks_a_perfect_match_read_off_the_image(self):
        # The vision record matches the words far better — but only through
        # its LABEL. Ranking counts printed words, on which the two tie at
        # 'ptac', and a tie goes to the stronger evidence. See
        # test_plan_search_ranks_on_what_the_sheet_says for the rule itself.
        terms = ps.search_terms("package terminal air conditioner ptac")
        ranked = ps.rank([VISION_LEGEND, SCHEDULE], terms)
        self.assertGreater(ps.match_score(VISION_LEGEND, terms),
                           ps.match_score(SCHEDULE, terms))
        self.assertEqual([r["tier"] for r in ranked],
                         [pe.TIER_SCHEDULE_CELL, pe.TIER_VISION])

    def test_a_record_that_does_not_mention_the_subject_is_not_returned(self):
        other = rec(quote="ROOF DRAIN LEADER TO RISER")
        self.assertEqual(ps.rank([other], ps.search_terms("ptac")), [])

    def test_the_subject_is_matched_word_by_word_with_no_synonym_table(self):
        # "ac units" does NOT find PTAC by letters, and nothing here invents
        # the link. The vision label is what carries it — see below.
        self.assertEqual(ps.rank([SCHEDULE], ps.search_terms("air conditioner")), [])
        self.assertEqual([r["tier"] for r in
                          ps.rank([VISION_LEGEND], ps.search_terms("air conditioner"))],
                         [pe.TIER_VISION])

    def test_intent_orders_and_never_filters(self):
        # A wrong guess about intent must cost ranking, not the answer.
        got = ps.rank([NOTE, SCHEDULE], ps.search_terms("ptac"), intent="location")
        self.assertEqual(len(got), 2)

    def test_stop_words_are_dropped_so_a_question_can_be_passed_whole(self):
        self.assertEqual(ps.search_terms("how many of the PTAC units are there"),
                         ["ptac", "units"])


class NeverALowerTierForTheSameThing(unittest.TestCase):

    def test_the_weaker_record_for_one_attribute_on_one_sheet_is_dropped(self):
        strong = rec(record_type="element", tier=pe.TIER_SCHEDULE_CELL,
                     quote="PTAC — count 21", subject_terms=["PTAC"])
        weak = rec(record_type="element", tier=pe.TIER_VISION, source="vision",
                   quote="PTAC — count 41", subject_terms=["PTAC"])
        kept = ps.best_per_attribute(ps.rank([weak, strong], ps.search_terms("ptac")))
        self.assertEqual([r["quote"] for r in kept], ["PTAC — count 21"])

    def test_the_same_thing_on_another_sheet_is_still_its_own_record(self):
        here = rec(record_type="element", quote="PTAC — count 21", subject_terms=["PTAC"])
        there = dict(here, sheet_number="M-201.00")
        kept = ps.best_per_attribute(ps.rank([here, there], ps.search_terms("ptac")))
        self.assertEqual(len(kept), 2)


class ANumberWithNothingBehindItDoesNotReachAPerson(unittest.TestCase):

    def test_a_quantity_the_schedule_prints_passes(self):
        ok, bad = ps.answer_is_grounded("The schedule lists 21 PTAC units.", [SCHEDULE])
        self.assertTrue(ok, bad)

    def test_a_quantity_nothing_printed_fails(self):
        ok, bad = ps.answer_is_grounded("There are about 41 PTAC units.", [SCHEDULE])
        self.assertFalse(ok)
        self.assertIn("41", bad)

    def test_a_cited_sheet_number_is_not_mistaken_for_a_claim(self):
        for citation in ("M-200.00", "A-105.01", "PTAC-1", "B01141294-S6"):
            with self.subTest(citation=citation):
                ok, bad = ps.answer_is_grounded(f"See {citation}.", [SCHEDULE])
                self.assertTrue(ok, f"{citation} was read as a number: {bad}")

    def test_an_answer_with_no_numbers_at_all_is_grounded(self):
        ok, _bad = ps.answer_is_grounded("PTAC units are shown on the mechanical plan.",
                                         [SCHEDULE])
        self.assertTrue(ok)

    def test_a_dimension_is_checked_as_its_numbers(self):
        dim = rec(record_type="dimension", quote='3 1/2" METAL STUD 16" O.C. 20 GAUGE')
        ok, _ = ps.answer_is_grounded('The studs are 3 1/2" at 16" O.C.', [dim])
        self.assertTrue(ok)
        ok, bad = ps.answer_is_grounded('The studs are 5 1/2" at 16" O.C.', [dim])
        self.assertFalse(ok)
        self.assertIn("5", bad)

    def test_the_inches_of_a_foot_inch_dimension_are_not_invisible(self):
        dim = rec(record_type="dimension", quote="CEILING HEIGHT 12'-6\"")
        ok, bad = ps.answer_is_grounded("The ceiling is 12'-9\".", [dim])
        self.assertFalse(ok, "the inch part was never checked")
        self.assertIn("9", bad)

    def test_a_payload_value_counts_even_when_the_quote_truncates(self):
        r = rec(record_type="schedule", tier=pe.TIER_SCHEDULE_CELL, quote="PILE SCHEDULE",
                payload={"rows": [["P1", "18"]]}, subject_terms=["PILE SCHEDULE"])
        ok, bad = ps.answer_is_grounded("The pile schedule shows 18.", [r])
        self.assertTrue(ok, bad)

    def test_with_no_records_nothing_is_supported(self):
        # The pure check says what is true: an empty evidence set supports no
        # number. Whether that should REPLACE the reply is a separate decision,
        # and gate_plan_answer makes it — a question about headcount is not a
        # plan question and must not be rewritten into one.
        ok, bad = ps.answer_is_grounded("There are 41 units.", [])
        self.assertFalse(ok)
        self.assertEqual(bad, ["41"])

    def test_a_page_number_does_not_whitelist_every_small_integer(self):
        # The record sits on page 9. "9 units" is still a claim.
        ok, bad = ps.answer_is_grounded("There are 9 PTAC units.", [SCHEDULE])
        self.assertFalse(ok)
        self.assertIn("9", bad)


class TheFallbackCanOnlySayWhatTheSheetsSay(unittest.TestCase):

    def test_it_renders_the_quote_and_the_sheet(self):
        out = ps.render_records([SCHEDULE], "ptac units")
        self.assertIn("M-200.00", out)
        self.assertIn("PTAC-1 | 21", out)

    def test_it_never_renders_a_label(self):
        out = ps.render_records([VISION_LEGEND], "ptac")
        self.assertNotIn("PACKAGE TERMINAL", out.upper())
        self.assertIn("PTAC-1", out)

    def test_a_mark_found_only_through_its_label_is_not_offered_as_the_answer(self):
        # This used to assert the opposite: 'air conditioner' rendered PTAC-1.
        # The label was never printed, but the header named the subject and
        # the line under it supplied the mark, which states the label's
        # meaning anyway. On 'kicker' that meaning was invented.
        out = ps.render_records([VISION_LEGEND], "air conditioner")
        self.assertEqual(out, "Not on the indexed drawings.")

    def test_the_renderer_reads_only_the_renderable_fields(self):
        src = inspect.getsource(ps.render_records)
        self.assertEqual(ps.RENDERABLE, ("quote",))
        self.assertNotIn('"label"', src)
        self.assertNotIn("'label'", src)

    def test_a_vision_record_says_it_was_read_off_the_drawing(self):
        self.assertIn("verify", ps.render_records([VISION_LEGEND], "ptac").lower())

    def test_nothing_found_says_so_rather_than_saying_nothing(self):
        self.assertIn("Not on the indexed drawings", ps.render_records([], "ptac"))


class ALabelWidensTheSearchAndNeverBecomesTheAnswer(unittest.TestCase):

    def test_the_label_is_what_makes_air_conditioner_findable(self):
        terms = ps.search_terms("air conditioner")
        self.assertGreater(ps.match_score(VISION_LEGEND, terms), 0)

    def test_an_answer_that_repeats_it_is_caught(self):
        leaked = ps.contains_label(
            "PTAC-1 is a package terminal air conditioner.", [VISION_LEGEND])
        self.assertEqual(leaked, ["PACKAGE TERMINAL AIR CONDITIONER"])

    def test_a_phrase_the_sheet_itself_prints_is_not_a_leak(self):
        printed = rec(record_type="legend_entry", tier=pe.TIER_TAG_LEGEND,
                      quote="KE 1 = KITCHEN EXHAUST 1")
        labelled = rec(record_type="legend_entry", tier=pe.TIER_VISION, source="vision",
                       quote="KE 1", label="KITCHEN EXHAUST 1")
        self.assertEqual(
            ps.contains_label("KE 1 is the kitchen exhaust 1.", [printed, labelled]), [])


class TheGateIsWiredToWhatGetsSent(unittest.TestCase):
    """Source-level, because the thing being asserted is that no path around
    it exists — not that one call happens to work."""

    def setUp(self):
        import server
        self.server = server

    def test_search_plans_is_a_tool_the_agent_can_call(self):
        names = [t["function"]["name"] for t in self.server._AGENT_TOOLS]
        self.assertIn("search_plans", names)

    def test_it_rides_the_same_feature_flag_as_the_other_plan_tool(self):
        # Every tool that reads the plan index rides one flag. A group that has
        # turned plan questions off must not get any of them back through
        # another door.
        #
        # ASSERTED AS A SET, NOT AS A LITERAL TUPLE. This pinned the exact
        # string '("query_plan", "search_plans")', so adding a third plan tool
        # -- check_drawing_set, the set-wide report -- failed the test for
        # naming a new tool rather than for letting one past the flag. The
        # intent is that they are ALL behind plan_queries; that is what is
        # checked now.
        src = inspect.getsource(self.server._run_group_agent)
        plan_tools = {t["function"]["name"] for t in self.server._AGENT_TOOLS
                      if t["function"]["name"] in
                      ("query_plan", "search_plans", "check_drawing_set")}
        self.assertGreaterEqual(len(plan_tools), 2, "plan tools not registered")
        guard = src[src.index("plan_queries") - 400:src.index("plan_queries")]
        for name in plan_tools:
            self.assertIn(
                f'"{name}"', guard,
                f"{name} reads the plan index but is not behind plan_queries")

    def test_the_search_returns_records_rather_than_prose(self):
        src = inspect.getsource(self.server.search_plans)
        self.assertIn("plan_search.rank(", src)
        self.assertIn("best_per_attribute", src)
        self.assertIn("-> List[dict]", inspect.getsource(self.server.search_plans)[:400])

    def test_the_search_only_reads_current_pages(self):
        src = inspect.getsource(self.server._current_record_page_ids)
        self.assertIn("_current_page_filter(", src)
        self.assertIn("_live_plan_file_ids(", src)

    def test_the_gate_replaces_rather_than_annotates(self):
        src = inspect.getsource(self.server.gate_plan_answer)
        self.assertIn("plan_search.answer_is_grounded(", src)
        self.assertIn("plan_search.contains_label(", src)
        self.assertIn("plan_search.render_records(", src)

    def test_every_reply_path_in_the_agent_loop_passes_the_gate(self):
        # A second return that sends text and skips the gate is exactly how a
        # hard gate stops being hard, so this counts the doors rather than
        # trusting the one it knows about.
        src = inspect.getsource(self.server._run_group_agent)
        composed = [ln.strip() for ln in src.split("\n")
                    if ln.strip().startswith("return ")
                    and ("content" in ln or "stripped" in ln)]
        self.assertTrue(composed, "the agent loop stopped returning composed text")
        for ln in composed:
            with self.subTest(line=ln):
                self.assertIn("_gated(", ln)

    def test_the_records_reach_the_gate_as_evidence_not_as_the_text_shown(self):
        src = inspect.getsource(self.server._dispatch_agent_tool)
        self.assertIn("record_sink", src)


class TheGateDecidesWhatIsSent(unittest.TestCase):

    def setUp(self):
        import server
        self.gate = server.gate_plan_answer

    def test_a_grounded_answer_is_sent_unchanged(self):
        text = "The PTAC schedule on M-200.00 lists 21 units."
        sent, outcome = self.gate(text, [SCHEDULE], "ptac units")
        self.assertEqual(sent, text)
        self.assertEqual(outcome, "grounded")

    def test_an_invented_number_is_replaced_by_the_records(self):
        sent, outcome = self.gate("There are 41 PTAC units.", [SCHEDULE], "ptac units")
        self.assertEqual(outcome, "ungrounded")
        self.assertNotIn("41", sent)
        self.assertIn("M-200.00", sent)

    def test_a_leaked_label_is_replaced_by_the_records(self):
        sent, outcome = self.gate("PTAC-1 is a PACKAGE TERMINAL AIR CONDITIONER.",
                                  [VISION_LEGEND, SCHEDULE], "ptac")
        self.assertEqual(outcome, "label_leak")
        self.assertNotIn("PACKAGE TERMINAL", sent.upper())

    def test_a_reply_with_no_plan_evidence_is_left_alone(self):
        sent, outcome = self.gate("There are 3 workers on site.", [], "")
        self.assertEqual(outcome, "no_records")
        self.assertIn("3 workers", sent)


if __name__ == "__main__":
    unittest.main()
