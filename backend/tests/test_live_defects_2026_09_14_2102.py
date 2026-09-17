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
from lib import plan_search as ps  # noqa: E402

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

    def test_a_named_sheet_is_an_exact_lookup_and_nothing_else(self):
        """The reported defect exactly: the image branch used to turn on
        _looks_like_show_verb alone, and a miss fell through to the nearest
        neighbours. A named sheet goes to _find_named_sheet, and when that
        finds nothing the handler SAYS so instead of sending something close.
        """
        code = _code_only(server._handle_plan_query)
        i = code.index("if named:")
        window = code[i:i + 500]
        self.assertIn("_find_named_sheet(project_id, named)", window)
        self.assertIn("isn't in the indexed drawings", window)
        self.assertIn("return", window)

    def test_the_sheet_sent_is_the_sheet_the_records_are_on(self):
        """Never a ranked guess. The RRF candidate list is gone — it was
        always populated, so it could never say the thing is not there. The
        pages come from the records search_plans returned, which quote the
        thing or are not returned at all."""
        code = _code_only(server._handle_plan_query)
        start = code.index("else:")
        self.assertIn("await search_plans(", code[start:])
        self.assertIn("_pages_for_records(project_id, found)", code[start:])
        self.assertNotIn("_retrieve_plan_candidates", code)

    def test_it_answers_rather_than_asking_back(self):
        """A superintendent who typed "show me the roof drains" has already
        said what he wants. Answering a request with a request is what the
        sixty-second latency makes unbearable."""
        code = _code_only(server._handle_plan_query)
        self.assertNotIn("Want them?", code)
        self.assertIn("_send_plan_image", code)

    def test_nothing_found_says_so(self):
        """One question back, and only when there is nothing to send at all —
        which is the one case where the crew has to narrow it."""
        code = _code_only(server._handle_plan_query)
        self.assertIn("Nothing to show for that", code)

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

    _retrieve_plan_candidates fused a vector rank and a keyword rank and
    returned its top three. Its top three were ALWAYS populated, so it could
    not return nothing — which made it incapable of saying "not on the
    drawings". _pages_with_element asked the literal question instead.

    Both are gone. A record is returned when its own printed words match, and
    the sheet that is sent is a sheet those records are on, so "nothing" is
    now an ordinary outcome rather than an impossible one. What the literal
    search had to get right, the ranker still has to get right, and it is
    tested here against plan_search rather than against a source string.
    """

    def test_the_debug_view_still_searches_extracted_text_only(self):
        """`embedding` is a guess by construction and `file_name` is about the
        upload, not the drawing. _ELEMENT_TEXT_FIELDS outlived the retriever:
        whatsapp_debug_page_index uses it to show what a page carries."""
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

    def test_every_term_has_to_appear_first(self):
        """An OR over the terms matches a page that mentions "roof" and knows
        nothing about drains. The records that contain EVERY term are fetched
        in full before any record that contains only some."""
        code = _code_only(server.search_plans)
        i = code.index('"$and": [{"$or": ors} for ors in per_term]')
        j = code.index('"$or": [c for ors in per_term for c in ors]')
        self.assertLess(i, j, "the any-term query runs before the all-term one")

    def test_and_coverage_is_the_first_thing_the_ranker_sorts_on(self):
        drains = {"quote": "ROOF DRAIN LEADERS", "tier": "text_layer"}
        roof = {"quote": "ROOF PLAN", "tier": "schedule_cell"}
        ranked = ps.rank([roof, drains], ps.search_terms("roof drains"))
        self.assertEqual(ranked[0]["quote"], "ROOF DRAIN LEADERS",
                         "a higher tier that matches fewer words came first")

    def test_stopwords_are_stripped_from_the_subject(self):
        """"the" is on every page ever indexed."""
        terms = ps.search_terms("show me the roof drains")
        self.assertNotIn("the", terms)
        self.assertNotIn("show", terms)
        self.assertIn("roof", terms)

    def test_an_empty_subject_finds_nothing_rather_than_everything(self):
        """A query that reduces to no terms must not turn into an unfiltered
        scan that matches every record in the project."""
        self.assertEqual(ps.search_terms("the a of"), [])
        code = _code_only(server.search_plans)
        self.assertIn("if not (project_id and terms):", code)

    def test_a_plural_finds_the_singular(self):
        """MEASURED, not assumed. Against a stubbed index, "show me the roof
        drains" found the roof plan and MISSED the riser diagram, whose summary
        reads "roof drain leaders to riser" — so the answer said one sheet when
        the truth was two. A literal search that cannot see past an "s" is a
        literal search that lies by omission."""
        rx = re.compile(ps.term_pattern("drains"), re.I)
        self.assertTrue(rx.search("ROOF DRAIN LEADERS TO RISER"))
        self.assertTrue(re.search(ps.term_pattern("box"), "MEP BOXES", re.I))

    def test_the_stem_is_not_a_stemmer(self):
        """A real stemmer turns "gas" into "ga" and matches everything. The
        length guard is what keeps short words whole."""
        self.assertEqual(ps.term_forms("gas"), ["gas"])
        self.assertNotIn("pil", ps.term_forms("piles"))

    def test_and_a_term_is_a_word_rather_than_a_run_of_letters(self):
        """The same search that could not see past an "s" could see STAIRS
        inside a question about air."""
        self.assertFalse(re.search(ps.term_pattern("air"), "STAIRS", re.I))
        self.assertTrue(re.search(ps.term_pattern("ptac"), "PTAC-1", re.I))

    def test_the_lookup_is_timed_like_every_other_stage(self):
        code = _code_only(server._handle_plan_query)
        self.assertIn('_stage["records"]', code)
        self.assertIn('"no_match"', code)
        self.assertIn('"sent"', code)


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
        """The stages are what the path now has: which sheet was named, how
        many records answered, how many pages they pointed at, how many images
        went out. The vision stages went with the vision calls."""
        code = _code_only(server._handle_plan_query)
        for stage in ('"named"', '"records"', '"candidates"', '"sent"',
                      '"total"'):
            with self.subTest(stage=stage):
                self.assertIn(f"_stage[{stage}]", code)

    def test_every_outcome_logs(self):
        """A path that only logs when it sends something reports nothing about
        the cases worth knowing about."""
        code = _code_only(server._handle_plan_query)
        for outcome in ('"named_sheet_not_found"', '"no_match"',
                        '"sent" if sent else "send_failed"'):
            with self.subTest(outcome=outcome):
                self.assertIn(f"_log_plan_timing(group_id, query, _stage, "
                              f"{outcome})", code)

    def test_the_line_is_greppable_and_carries_a_total(self):
        code = _code_only(server._log_plan_timing)
        self.assertIn("plan timing", code)
        self.assertIn("total=", code)

    def test_it_logs_at_warning_so_it_survives_the_default_level(self):
        """An info line in a production log nobody raised the level for is a
        measurement that was never taken."""
        self.assertIn("logger.warning", _code_only(server._log_plan_timing))


class ThePageRowIsFetchedWithoutItsVectors(unittest.TestCase):
    """_PAGE_FIELDS outlived the pool it was written for. Two readers still
    load page rows — the named-sheet lookup and the pages behind the records —
    and both send an image from what they load."""

    READERS = ("_find_named_sheet", "_pages_for_records")

    def test_both_page_loads_are_projected(self):
        for name in self.READERS:
            with self.subTest(fn=name):
                code = _code_only(getattr(server, name))
                self.assertIn("_PAGE_FIELDS", code,
                              "a page load without a projection is back")

    def test_the_projection_excludes_the_embedding(self):
        self.assertNotIn("embedding", server._PAGE_FIELDS)

    def test_no_embedding_is_loaded_anywhere_on_this_path(self):
        """The vector pass is gone with the RRF fusion that needed it."""
        for name in self.READERS + ("search_plans",):
            with self.subTest(fn=name):
                self.assertNotIn('{"embedding": 1}',
                                 _code_only(getattr(server, name)))

    def test_it_covers_every_field_the_pipeline_reads(self):
        """A projection typo does not raise. It silently drops a field and
        makes matching quietly worse — which is what happened on the first
        draft of this, where the names were guessed from the INDEXING PROMPT
        (MATERIALS_AND_SPECS) rather than from what the writer stores
        (`materials`)."""
        used = set()
        for fn in (server._pages_for_records, server._handle_plan_query,
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


if __name__ == "__main__":
    unittest.main()
