"""Live test, 2026-09-14 23:33-23:40, production at d83694f.

d83694f IS 528 — a squash merge, so 528's commits are not ancestors of it and
an ancestry check says "not deployed" while every marker from both commits is
present. Checked by content before anything else, because every finding below
depends on which code was running.

  0. "how many piles" sent images; "show me roof drains" sent no text line.
     One cause: the routing decision was made on the agent's REBUILT query.
  1. "stucco" and "posts" each produced two acknowledgements and two replies.
  2. An untagged follow-up 20s after a quoted bot reply got no reply, and the
     refusal left no trace in the log at all.
  3. "Unconfirmed SST approved?" was answered from the model's prior, because
     the roster carried the card state and not the CP's decision.
  4. A debug endpoint, so what the indexer stored can be read.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402


def _code_only(fn):
    return "\n".join(l for l in inspect.getsource(fn).split("\n")
                     if not l.lstrip().startswith("#"))


# ══════════════════════════════════════════════════════════════════
# 0. Route on the sentence, not on the agent's bag of keywords
# ══════════════════════════════════════════════════════════════════

class TheUsersWordsReachTheRouter(unittest.TestCase):
    """`query` is not the user's message. _dispatch_agent_tool builds it from
    structured args — discipline, floor, sheet_type, sheet_number, keywords —
    so it arrives as "structural pile". Every routing test was being run
    against that, and against that they all say False."""

    def test_the_handler_takes_the_body(self):
        self.assertIn("user_body",
                      inspect.signature(server._handle_plan_query).parameters)

    def test_the_dispatcher_takes_it_and_passes_it_on(self):
        self.assertIn("user_body",
                      inspect.signature(server._dispatch_agent_tool).parameters)
        self.assertIn("user_body=user_body",
                      _code_only(server._dispatch_agent_tool))

    def test_the_agent_hands_over_the_message_it_was_given(self):
        code = _code_only(server._run_group_agent)
        self.assertEqual(code.count("user_body=body"), 2,
                         "both dispatch branches must pass the real message")

    def test_the_router_prefers_the_body_over_the_synth(self):
        code = _code_only(server._handle_plan_query)
        self.assertIn("route_text = (user_body or \"\").strip() or query", code)

    def test_a_count_beats_a_show_verb(self):
        """"show me how many piles" is a question with a one-word answer, not
        a request for a picture — the same ordering _classify_plan_question
        already uses."""
        code = _code_only(server._handle_plan_query)
        i = code.index("asks_for_a_value")
        self.assertIn("_is_count_or_yes_no", code[i:i + 200])
        self.assertIn("not asks_for_a_value", code)

    def test_a_show_verb_with_no_sheet_reaches_the_element_path(self):
        """The case that fell through to images when the agent supplied no
        question. offer_only could only be set inside the wants_image branch,
        which needed a show verb the synth can never contain."""
        code = _code_only(server._handle_plan_query)
        tail = code[code.index("else:", code.index("wants_image")):]
        self.assertIn("_looks_like_show_verb(route_text)", tail)
        self.assertIn("offer_only = True", tail)

    def test_the_fallback_question_is_the_sentence_not_the_synth(self):
        """A bag of keywords put to a vision model is a worse prompt than the
        thing the person actually asked."""
        code = _code_only(server._handle_plan_query)
        self.assertIn("effective_question = route_text", code)
        self.assertNotIn("effective_question = query.strip()", code)

    def test_the_route_decision_is_logged(self):
        code = _code_only(server._handle_plan_query)
        self.assertIn("plan route", code)

    def test_the_image_branch_finally_logs_its_exit(self):
        """Both reported failures ended on this branch and left no line
        anywhere, so "which path handled it" was unanswerable."""
        code = _code_only(server._handle_plan_query)
        self.assertIn('_log_plan_timing(group_id, query, _stage, "image_sent")',
                      code)

    def test_every_exit_from_the_pipeline_logs(self):
        """A path that logs on three of four exits reports nothing about the
        fourth, which is where the bugs were."""
        code = _code_only(server._handle_plan_query)
        for outcome in ('"answered"', '"not_found"', '"element_answered"',
                        '"element_not_found"', '"image_sent"'):
            with self.subTest(outcome=outcome):
                self.assertIn(outcome, code)


# ══════════════════════════════════════════════════════════════════
# 1. Asked once, answered once
# ══════════════════════════════════════════════════════════════════

class OneAsyncToolPerTurn(unittest.TestCase):
    """The branch dispatched EVERY tool call. Each async handler runs its own
    pipeline and speaks for itself, so a model hedging "stucco" across two
    disciplines became two acknowledgements and two answers."""

    def test_only_the_first_async_call_is_dispatched(self):
        code = _code_only(server._run_group_agent)
        i = code.index("_async_calls")
        block = code[i:i + 1200]
        self.assertIn("_async_calls[0]", block)
        self.assertNotIn("for tc in tool_calls:", block,
                         "the loop over every tool call is back")

    def test_the_hedge_is_logged_rather_than_hidden(self):
        """A model hedging is normal and worth seeing; treating its hedge as
        two conversations is the bug."""
        self.assertIn("async tool calls", _code_only(server._run_group_agent))

    def test_the_synchronous_branch_still_runs_them_all(self):
        """Read tools return text to the model and do not speak to the user,
        so several in one round is correct there."""
        code = _code_only(server._run_group_agent)
        self.assertIn("for tc in tool_calls:", code)


class ARedeliveredWebhookIsNotASecondQuestion(unittest.TestCase):
    """The VOICE path has deduplicated on message_id since it shipped, with a
    comment saying WaAPI redelivers — so redelivery is known behaviour here,
    not a hypothesis. The text path had nothing."""

    def test_the_group_path_checks_for_a_stored_copy_first(self):
        code = _code_only(server._process_whatsapp_message)
        self.assertIn("already processed", code)

    def test_it_checks_before_the_group_is_even_looked_up(self):
        code = _code_only(server._process_whatsapp_message)
        self.assertLess(code.index("already processed"),
                        code.index('find_one({"wa_group_id"'))

    def test_it_reuses_the_row_it_was_going_to_store_anyway(self):
        """No new collection and no new write: whatsapp_messages already holds
        every processed group message."""
        code = _code_only(server._process_whatsapp_message)
        i = code.index("already processed")
        self.assertIn("whatsapp_messages.find_one", code[i - 500:i])

    def test_an_empty_message_id_is_let_through(self):
        """Some events carry no id. Refusing those would drop real messages to
        prevent a duplicate that may not exist."""
        code = _code_only(server._process_whatsapp_message)
        self.assertIn("if _mid:", code)

    def test_a_failed_check_does_not_drop_the_message(self):
        """A duplicate is an annoyance; a dropped question is the failure this
        bot is judged on."""
        code = _code_only(server._process_whatsapp_message)
        i = code.index("duplicate check failed")
        self.assertIn("logger.warning", code[i - 120:i + 40])


# ══════════════════════════════════════════════════════════════════
# 2. A refusal says why
# ══════════════════════════════════════════════════════════════════

class EveryRefusalIsNamed(unittest.TestCase):
    """The success path has logged its reason since it was written. The
    refusal path logged nothing, so "why did the bot ignore that?" — asked
    twice now about real messages — had no answer from production."""

    def test_the_refusal_logs(self):
        code = _code_only(server._is_bot_addressed)
        self.assertIn("NOT addressed", code)

    def test_the_four_causes_are_told_apart(self):
        """They want different fixes: nobody tagged it is a product decision,
        an expired session is a TTL question, and a session that was never
        written is the duplicate-key fault that ate the first miss."""
        code = _code_only(server._is_bot_addressed)
        for why in ("no_mention", "session_missing", "session_expired",
                    "strict"):
            with self.subTest(why=why):
                self.assertIn(why, code)

    def test_it_carries_the_message_so_the_row_can_be_found(self):
        code = _code_only(server._is_bot_addressed)
        self.assertIn("body=", code)

    def test_looking_up_the_reason_cannot_break_the_decision(self):
        """This runs on every unaddressed message. A raise here would turn a
        diagnostic into a dropped message."""
        tree = ast.parse(inspect.getsource(server._is_bot_addressed))
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        self.assertTrue(handlers)
        for h in handlers:
            self.assertFalse([n for n in ast.walk(h) if isinstance(n, ast.Raise)])


class TheDropSaysWhetherItHappened(unittest.TestCase):

    def test_the_drop_runs_at_boot_not_in_a_script(self):
        """Confirmed by call chain: run_whatsapp_startup_migrations is awaited
        inside the startup event, and the drop is inside it."""
        migrations = _code_only(server.run_whatsapp_startup_migrations)
        self.assertIn('drop_index("convo_state_by_group")', migrations)
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text(
            encoding="utf-8")
        self.assertIn("await run_whatsapp_startup_migrations()", src,
                      "the migration runner is no longer awaited at startup")

    def test_both_outcomes_log_at_warning(self):
        """An info line in a service nobody raised the level for is a fact
        that was never recorded — and this one was asked of production."""
        code = _code_only(server.run_whatsapp_startup_migrations)
        i = code.index('drop_index("convo_state_by_group")')
        block = code[i:i + 700]
        self.assertEqual(block.count("logger.warning"), 2)
        self.assertNotIn("pass  # never created", block)

    def test_the_index_state_is_readable_without_a_database_shell(self):
        paths = {r.path for r in server.app.routes if hasattr(r, "path")}
        self.assertIn("/api/whatsapp/debug/convo-state-indexes", paths)


# ══════════════════════════════════════════════════════════════════
# 3. The CP's decision travels with the man
# ══════════════════════════════════════════════════════════════════

class TheReviewDecisionIsOnTheRoster(unittest.TestCase):

    def test_an_approval_names_who_and_when(self):
        out = server._review_suffix({
            "review_decision": "approved", "reviewed_by_name": "Roy F",
            "reviewed_at": datetime(2026, 9, 14, tzinfo=timezone.utc)})
        self.assertIn("CP approved", out)
        self.assertIn("Roy F", out)
        self.assertIn("2026-09-14", out)

    def test_a_man_sent_home_says_so(self):
        """Not merely "unconfirmed". A CP looked at this and refused it."""
        out = server._review_suffix({"review_decision": "sent_home",
                                     "reviewed_by_name": "Roy F"})
        self.assertIn("SENT HOME", out)

    def test_the_label_does_not_stutter(self):
        """"SENT HOME by CP by Roy F" was the first draft."""
        out = server._review_suffix({"review_decision": "sent_home",
                                     "reviewed_by_name": "Roy F"})
        self.assertEqual(out.count("by"), 1)

    def test_unreviewed_renders_nothing_and_that_is_the_answer(self):
        """A card nobody has looked at is not the same as one a CP cleared,
        and that distinction is the whole question being asked."""
        for ci in ({}, {"review_decision": None}, {"review_decision": ""}):
            with self.subTest(ci=ci):
                self.assertEqual(server._review_suffix(ci), "")

    def test_the_roster_renders_it_beside_the_card(self):
        code = _code_only(server._handle_who_on_site)
        self.assertIn("_review_suffix(ci)", code)
        self.assertIn("_sst_suffix(", code)

    def test_the_tool_tells_the_agent_the_decision_is_in_there(self):
        """A handler that returns the data and a description that does not
        mention it still produces an answer from the model's prior."""
        desc = next(t["function"]["description"] for t in server._AGENT_TOOLS
                    if t["function"]["name"] == "who_on_site")
        self.assertIn("REVIEW DECISION", desc)
        self.assertIn("approved", desc.lower())

    def test_it_forbids_answering_a_review_question_from_memory(self):
        desc = next(t["function"]["description"] for t in server._AGENT_TOOLS
                    if t["function"]["name"] == "who_on_site")
        self.assertIn("from memory", desc.lower())
        self.assertIn("nobody has reviewed", desc.lower())


# ══════════════════════════════════════════════════════════════════
# 4. What the indexer actually stored, readable
# ══════════════════════════════════════════════════════════════════

class ThePageIndexIsInspectable(unittest.TestCase):
    """Stucco, posts, gauge and piles all came back "not found" on a set that
    contains them. Two explanations fit — retrieval looking in the wrong place,
    or the indexer never extracting the words — and they want opposite fixes.
    Nothing in the product could tell them apart."""

    def test_the_route_exists(self):
        paths = {r.path for r in server.app.routes if hasattr(r, "path")}
        self.assertIn("/api/whatsapp/debug/page-index", paths)

    def test_it_is_company_admin_only(self):
        """It read `role not in ("admin", "owner")` inline. The role is
        retired -- every self-serve signup received it -- and the named rule
        `is_company_admin` replaced it, which also admits the platform
        operator on his flag rather than on any role string."""
        code = _code_only(server.whatsapp_debug_page_index)
        self.assertIn("is_company_admin(current_user)", code)
        self.assertNotIn('"owner"', code)
        self.assertIn("403", code)

    def test_it_is_scoped_to_the_callers_company(self):
        """A project id in a query string is the client's input, and a debug
        endpoint is still an endpoint."""
        code = _code_only(server.whatsapp_debug_page_index)
        self.assertIn("_same_company_or_403", code)

    def test_it_excludes_the_embedding(self):
        """1536 floats no human reads, burying the text this exists to show."""
        code = _code_only(server.whatsapp_debug_page_index)
        self.assertIn('{"embedding": 0}', code)

    def test_it_shows_what_a_literal_search_would_see(self):
        """The string that decides whether "stucco" is findable at all."""
        code = _code_only(server.whatsapp_debug_page_index)
        self.assertIn("_ELEMENT_TEXT_FIELDS", code)
        self.assertIn("_searchable_text", code)


if __name__ == "__main__":
    unittest.main()
