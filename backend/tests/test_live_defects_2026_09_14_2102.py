"""Live test, 2026-09-14 21:02, group "588 Boyland tets" — defects 2 through 5.

Defect 1, the session window, has its own file
(test_conversation_state_holds_more_than_one_row.py) because its cause was an
index and its proof is a key-set argument.

  2. Replies arrived out of order and quoted nothing, so with two questions in
     flight there was no way to tell which answer belonged to which.
  3. "show me <element>" shipped the top two keyword-ranked sheets, which is a
     guess wearing the costume of an answer.
  4. "Need anything else?" survived a prompt that explicitly bans it.
  5. Plan Q&A took about sixty seconds and nothing on the path was timed.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402

SRC = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")


def _code_only(fn):
    return "\n".join(l for l in inspect.getsource(fn).split("\n")
                     if not l.lstrip().startswith("#"))


# ══════════════════════════════════════════════════════════════════
# 2. Every reply quotes the message it answers
# ══════════════════════════════════════════════════════════════════

class ARepyQuotesItsQuestion(unittest.TestCase):

    def test_the_sender_takes_a_reply_to(self):
        self.assertIn("reply_to",
                      inspect.signature(server.send_whatsapp_message).parameters)

    def test_it_becomes_waapis_replyToMessageId(self):
        """The vendor's parameter name and format: the SERIALIZED id,
        {fromMe}_{chatId}_{messageId}, which is what the parser already
        returns as message_id_serialized."""
        self.assertIn("replyToMessageId", _code_only(server.send_whatsapp_message))

    def test_the_serialized_id_is_persisted_on_the_stored_message(self):
        """It was parsed and thrown away, so a reply composed after the
        webhook had been forgotten could not quote anything."""
        self.assertIn(
            '"message_id_serialized": parsed.get("message_id_serialized")', SRC,
            "the quotable message id is no longer stored on the message row, "
            "so a reply composed later cannot quote the question it answers")

    def test_it_is_threaded_to_every_frame_that_answers(self):
        """The plan answer is precisely the reply that lands far from its
        question, and it is dispatched three frames from the message."""
        for fn in (server._handle_plan_query, server._dispatch_agent_tool,
                   server._run_group_agent):
            with self.subTest(fn=fn.__name__):
                self.assertIn("reply_to", inspect.signature(fn).parameters)

    def test_no_send_inside_the_plan_pipeline_is_unquoted(self):
        """The slow path. An unquoted send here is the defect as reported."""
        tree = ast.parse(SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "_handle_plan_query")
        bad = [n.lineno for n in ast.walk(fn)
               if isinstance(n, ast.Call)
               and getattr(n.func, "id", "") == "send_whatsapp_message"
               and "reply_to" not in {k.arg for k in n.keywords}]
        self.assertEqual(bad, [], f"unquoted send at line(s) {bad}")

    def test_a_missing_id_sends_unquoted_rather_than_not_at_all(self):
        """A quote that cannot be formed is a message that reads worse, not a
        message that must not be sent."""
        code = _code_only(server.send_whatsapp_message)
        self.assertIn("if reply_to:", code)


# ══════════════════════════════════════════════════════════════════
# 3. An image is only ever sent for a named sheet
# ══════════════════════════════════════════════════════════════════

class ShowMeAnElementIsNotAShowMeASheet(unittest.TestCase):

    NAMES_A_SHEET = ["show me ST-201", "show me A-301", "show me ME-401",
                     "pull up S102", "SP-1.2 please"]
    NAMES_NO_SHEET = ["show me the sprinkler riser", "show me the roof plan",
                      "show me sheet 4", "call me on 917", "show me the stairs"]

    def test_a_sheet_id_is_recognised(self):
        for q in self.NAMES_A_SHEET:
            with self.subTest(q=q):
                self.assertTrue(server._names_a_sheet(q))

    def test_an_element_is_not_mistaken_for_one(self):
        for q in self.NAMES_NO_SHEET:
            with self.subTest(q=q):
                self.assertFalse(server._names_a_sheet(q))

    def test_a_bare_number_is_not_a_sheet(self):
        """Without the prefix list, "on 4" and "by 12" match the shape and
        every message looks like a sheet request."""
        for q in ("are there sprinklers on 4", "we poured 12 yards"):
            with self.subTest(q=q):
                self.assertFalse(server._names_a_sheet(q))

    def test_the_image_branch_is_gated_on_the_sheet_not_the_verb(self):
        """The reported defect exactly: the branch used to turn on
        _looks_like_show_verb alone."""
        code = _code_only(server._handle_plan_query)
        i = code.index("wants_image")
        window = code[i:i + 400]
        self.assertIn("_names_a_sheet", window)
        self.assertIn("sheet_number", window)
        self.assertIn("offer_only", window)

    def test_the_element_path_sends_no_ranked_guess(self):
        """Bounded by CODE landmarks; _code_only has already stripped the
        comments, so a boundary that lives in one cannot be found.

        The image sent on this path comes from _pages_with_element, never from
        the RRF candidate list — that list is always populated and therefore
        can never say the thing is not there."""
        code = _code_only(server._handle_plan_query)
        start = code.index("if offer_only:")
        end = code.index("if not effective_question:", start)
        block = code[start:end]
        self.assertIn("_pages_with_element", block)
        self.assertNotIn("candidates[", block,
                         "the element path is reaching into the ranked list again")

    def test_it_answers_rather_than_asking_back(self):
        """A superintendent who typed "show me the roof drains" has already
        said what he wants. Answering a request with a request is what the
        sixty-second latency makes unbearable."""
        code = _code_only(server._handle_plan_query)
        self.assertNotIn("Want them?", code)
        self.assertIn("_send_plan_image", code)

    def test_nothing_found_says_so(self):
        self.assertIn("Not found on indexed drawings.",
                      _code_only(server._handle_plan_query))

    def test_the_offer_machinery_is_gone(self):
        """Removed with the behaviour it served, rather than left dormant."""
        for name in ("_maybe_answer_plan_offer", "_AFFIRMATIVE_RE",
                     "PLAN_OFFER_TTL_SECONDS"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(server, name))
        # ANCHORED, because a bare word against the whole file bans a
        # SUBSTRING: "plan_offers" would satisfy it and an unrelated
        # identifier containing the letters would break it. Every site that
        # touched this row wrote or filtered it as a `kind`, so that is the
        # shape worth forbidding.
        self.assertNotIn('"kind": "plan_offer"', SRC,
                         "a plan_offer row is still written or read somewhere")
        self.assertNotIn('"kind":       "plan_offer"', SRC,
                         "a plan_offer row is still being stored")


class ASheetIsSentOnlyWhenItMentionsTheThing(unittest.TestCase):
    """The hard rule: never a best-keyword guess.

    _retrieve_plan_candidates fuses a vector rank and a keyword rank and
    returns its top three. Its top three are ALWAYS populated, so it cannot
    return nothing — which makes it incapable of saying "not on the drawings".
    _pages_with_element asks the literal question instead."""

    def test_the_search_runs_over_extracted_text_only(self):
        """`embedding` is a guess by construction and `file_name` is about the
        upload, not the drawing."""
        for f in ("keywords", "summary", "materials", "spaces", "notes"):
            with self.subTest(field=f):
                self.assertIn(f, server._ELEMENT_TEXT_FIELDS)
        for f in ("embedding", "file_name", "file_hash"):
            with self.subTest(field=f):
                self.assertNotIn(f, server._ELEMENT_TEXT_FIELDS)

    def test_every_field_it_searches_is_one_the_indexer_writes(self):
        idx = inspect.getsource(server._index_single_page)
        written = set(re.findall(r'^\s+"([a-z_]+)":', idx, re.M))
        stray = [f for f in server._ELEMENT_TEXT_FIELDS if f not in written]
        self.assertEqual(stray, [],
                         f"searching fields nothing writes: {stray}")

    def test_every_term_has_to_appear(self):
        """An OR over the terms would match a page that mentions "roof" and
        knows nothing about drains."""
        code = _code_only(server._pages_with_element)
        self.assertIn('"$and"', code)

    def test_stopwords_are_stripped_from_the_element(self):
        """"the" is on every page ever indexed."""
        terms = server._element_terms("show me the roof drains", {})
        self.assertNotIn("the", terms)
        self.assertNotIn("show", terms)
        self.assertIn("roof", terms)

    def test_the_parsers_keywords_win_when_it_has_them(self):
        """It has already read the sentence and pulled out the subject."""
        terms = server._element_terms("show me the thing",
                                      {"keywords": ["roof drain"]})
        self.assertEqual(terms, ["roof drain"])

    def test_an_empty_element_finds_nothing_rather_than_everything(self):
        """A query that reduces to no terms must not turn into an unfiltered
        scan that matches every page in the project."""
        import asyncio
        self.assertEqual(asyncio.run(server._pages_with_element("p1", [])), [])
        self.assertEqual(asyncio.run(server._pages_with_element("", ["roof"])), [])

    def test_a_plural_finds_the_singular(self):
        """MEASURED, not assumed. Against a stubbed index, "show me the roof
        drains" found the roof plan and MISSED the riser diagram, whose summary
        reads "roof drain leaders to riser" — so the answer said one sheet when
        the truth was two. A literal search that cannot see past an "s" is a
        literal search that lies by omission."""
        code = _code_only(server._pages_with_element)
        self.assertIn('endswith("s")', code)
        self.assertIn('endswith("es")', code)

    def test_the_stem_is_not_a_stemmer(self):
        """A real stemmer turns "gas" into "ga" and matches everything. The
        length guard is what keeps short words whole."""
        code = _code_only(server._pages_with_element)
        self.assertIn("len(needle) > 3", code)

    def test_a_page_the_indexer_thought_was_about_it_is_sent_first(self):
        """The difference between sending the riser diagram and sending a page
        that says "see riser diagram"."""
        code = _code_only(server._pages_with_element)
        self.assertIn("keywords", code)
        self.assertIn("rows.sort", code)

    def test_the_lookup_is_timed_like_every_other_stage(self):
        code = _code_only(server._handle_plan_query)
        self.assertIn('_mark("element_lookup")', code)
        self.assertIn('"element_not_found"', code)
        self.assertIn('"element_answered"', code)


# ══════════════════════════════════════════════════════════════════
# 4. The ban is enforced after the model, not asked of it
# ══════════════════════════════════════════════════════════════════

class TheGenericOfferIsStrippedNotRequested(unittest.TestCase):

    EATEN = [
        "4 on site today.\nNeed anything else?",
        "4 on site.\n\nAnything else I can help you with?",
        "Done.\nLet me know if you need anything",
        "PL-4412 expires in 12 days.\nHappy to help!",
        "3 open items.\nHope this helps.",
        "Filed.\nFeel free to ask.",
    ]
    KEPT = [
        "Sprinkler riser shows up on ST-201, ST-202.\nWant them?",
        "PL-4412 expires in 12 days.\nWant me to start renewal for PL-4412?",
        "Nobody on site today.",
        "2 violations open.\nWant the filing details?",
    ]

    def test_the_reported_line_is_removed(self):
        out = server._strip_generic_offer("4 on site today.\nNeed anything else?")
        self.assertEqual(out, "4 on site today.")

    def test_every_contentless_form_is_removed(self):
        for t in self.EATEN:
            with self.subTest(t=t.split("\n")[-1]):
                out = server._strip_generic_offer(t)
                self.assertNotEqual(out, t)
                self.assertTrue(out.strip())

    def test_an_offer_that_names_a_thing_survives(self):
        """This is the point. The specific next-step question does real work
        and the prompt still asks for it."""
        for t in self.KEPT:
            with self.subTest(t=t.split("\n")[-1]):
                self.assertEqual(server._strip_generic_offer(t), t)

    def test_a_message_that_is_only_an_offer_is_left_alone(self):
        """An empty send is a bot that looks broken, and silence is never the
        better repair for a badly-shaped reply."""
        self.assertEqual(server._strip_generic_offer("Anything else?"),
                         "Anything else?")

    def test_it_runs_inside_the_sender_so_nothing_routes_around_it(self):
        """Thirty call sites send text. A stripper bolted to one of them is a
        stripper the next one forgets."""
        self.assertIn("_strip_generic_offer",
                      _code_only(server.send_whatsapp_message))

    def test_the_prompt_ban_is_still_there_too(self):
        """Belt and braces: the prompt should still ask, because a model that
        does not emit the line is better than one whose line gets cut."""
        self.assertIn("NEVER end with a generic offer",
                      server._AGENT_SYSTEM_PROMPT_BASE)


# ══════════════════════════════════════════════════════════════════
# 5. Measurement, before any latency change
# ══════════════════════════════════════════════════════════════════

class ThePlanPathIsTimed(unittest.TestCase):

    def test_every_stage_is_marked(self):
        code = _code_only(server._handle_plan_query)
        for stage in ('"parse"', '"retrieval"', '"candidates"',
                      'f"fetch{_vqa_n}"', 'f"vqa{_vqa_n}"'):
            with self.subTest(stage=stage):
                self.assertIn(stage, code)

    def test_both_outcomes_log(self):
        """A path that only logs when it answers reports nothing about the
        slowest case, which is the one that runs every candidate."""
        code = _code_only(server._handle_plan_query)
        self.assertIn('_log_plan_timing(group_id, query, _stage, "answered")', code)
        self.assertIn('_log_plan_timing(group_id, query, _stage, "not_found")', code)

    def test_the_line_is_greppable_and_carries_a_total(self):
        code = _code_only(server._log_plan_timing)
        self.assertIn("plan timing", code)
        self.assertIn("total=", code)

    def test_it_logs_at_warning_so_it_survives_the_default_level(self):
        """An info line in a production log nobody raised the level for is a
        measurement that was never taken."""
        self.assertIn("logger.warning", _code_only(server._log_plan_timing))


class ThePoolStopsCarryingItsVectors(unittest.TestCase):

    def test_both_pool_loads_are_projected(self):
        code = _code_only(server._retrieve_plan_candidates)
        self.assertEqual(code.count("_PAGE_FIELDS"), 2,
                         "a pool load without a projection is back")

    def test_the_projection_excludes_the_embedding(self):
        self.assertNotIn("embedding", server._PAGE_FIELDS)

    def test_it_covers_every_field_the_pipeline_reads(self):
        """A projection typo does not raise. It silently drops a field and
        makes matching quietly worse — which is what happened on the first
        draft of this, where the names were guessed from the INDEXING PROMPT
        (MATERIALS_AND_SPECS) rather than from what the writer stores
        (`materials`)."""
        used = set()
        for fn in (server._retrieve_plan_candidates, server._handle_plan_query,
                   server._fetch_page_jpeg, server._send_plan_image):
            src = inspect.getsource(fn)
            used |= set(re.findall(
                r'\b(?:rec|p|r|page_rec|row|hit|c)\.get\("([a-z_]+)"', src))
            used |= set(re.findall(
                r'\b(?:rec|p|r|page_rec|row|hit|c)\["([a-z_]+)"\]', src))
        missing = sorted(used - set(server._PAGE_FIELDS) - {"embedding"})
        self.assertEqual(missing, [],
                         f"projection drops fields the pipeline reads: {missing}")

    def test_the_projection_matches_what_indexing_writes(self):
        """Pinned against the writer, not against the prompt."""
        idx = inspect.getsource(server._index_single_page)
        written = set(re.findall(r'^\s+"([a-z_]+)":', idx, re.M))
        stray = sorted(f for f in server._PAGE_FIELDS
                       if f not in written and f not in {
                           "_id", "page_jpeg_r2_key", "page_base_r2_key",
                           "is_spec_page"})
        self.assertEqual(stray, [],
                         f"projected fields nothing writes: {stray}")

    def test_the_vectors_are_fetched_for_the_pass_that_needs_them(self):
        code = _code_only(server._retrieve_plan_candidates)
        self.assertIn('{"embedding": 1}', code)

    def test_a_failed_vector_fetch_costs_the_rank_not_the_answer(self):
        code = _code_only(server._retrieve_plan_candidates)
        i = code.index('{"embedding": 1}')
        self.assertIn("except Exception", code[i:i + 500])


if __name__ == "__main__":
    unittest.main()
