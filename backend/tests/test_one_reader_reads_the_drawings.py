"""Every plan question is answered from records, by one reader, under the gate.

── WHY THE OTHER READER IS GONE FROM THE ANSWER PATH ──────────────────────

`query_plan` used to answer. Given a question it ran the keyword matcher over
chunks and, failing that, sent a picture of a 36-inch sheet to a vision model
and repeated what came back. That pipeline is what produced `41 PTAC units`:
a number no cell on the sheet prints, summed off an image, with nothing able
to tell it from a measured one.

The recorded eval (eval/results/boyland-2026-09-17-d3e80a43.json) scores the
record reader at 17 of 18 on the corpus that pipeline built.

So there is ONE reader now. `query_plan` sends the sheet — which is the thing
a crew actually wants on their phone — and, when it carries a question, it
fetches records and hands them back for the agent to compose under the gate.
Exactly the path `search_plans` uses, so a number is checked in one place.
"""

import ast
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402


def _query_plan_branch() -> str:
    src = inspect.getsource(server._dispatch_agent_tool)
    i = src.index('if name == "query_plan"')
    j = src.index('if name == "start_permit_renewal"', i)
    return src[i:j]


class QueryPlanSendsSheetsAndDoesNotAnswer(unittest.TestCase):

    def test_it_never_asks_a_vision_model_a_question(self):
        branch = _query_plan_branch()
        self.assertNotIn("VQA", branch)
        self.assertNotIn("Qwen will answer", branch)

    def test_the_handler_is_told_not_to_answer(self):
        # _handle_plan_query still sends images; it is handed no question.
        branch = _query_plan_branch()
        self.assertIn("question=None", branch)
        self.assertIn('dict(parsed_override, question=None)', branch)

    def test_a_question_is_answered_from_records(self):
        branch = _query_plan_branch()
        self.assertIn("await search_plans(", branch)
        self.assertIn("_render_records_for_model(found, question)", branch)

    def test_those_records_reach_the_gate_as_evidence(self):
        # Same sink search_plans uses, so gate_plan_answer checks this answer
        # against the same records the agent was shown.
        self.assertIn("record_sink.append", _query_plan_branch())

    def test_the_sheet_is_still_sent_either_way(self):
        branch = _query_plan_branch()
        self.assertIn("_handle_plan_query(", branch)
        self.assertLess(branch.index("_handle_plan_query("),
                        branch.index("await search_plans("))

    def test_the_tool_says_it_sends_rather_than_reads(self):
        spec = [t for t in server._AGENT_TOOLS
                if t["function"]["name"] == "query_plan"][0]
        desc = spec["function"]["description"]
        self.assertIn("search_plans", desc)
        self.assertNotIn("visually analyzed", desc)


class AQuestionDoesNotEndTheTurn(unittest.TestCase):
    """A fire-and-forget tool ends the agent's turn, because its own handler
    sends the reply. query_plan with a question does not send one — the agent
    still has to write the answer — so it must not short-circuit."""

    def _speaks_for_itself(self, name, args_json):
        """Run the agent loop's own predicate, lifted out of it verbatim."""
        lines = inspect.getsource(server._run_group_agent).splitlines()
        start = next(i for i, l in enumerate(lines)
                     if l.strip().startswith("def _speaks_for_itself"))
        end = next(i for i, l in enumerate(lines[start:], start)
                   if l.strip().startswith("_async_calls ="))
        block = textwrap.dedent("\n".join(lines[start:end]))
        ns = {"async_dispatch_tools": {"query_plan", "start_checklist"}}
        exec(compile(ast.parse(block), "<predicate>", "exec"), ns)
        return ns["_speaks_for_itself"](
            {"function": {"name": name, "arguments": args_json}})

    def test_a_sheet_request_still_speaks_for_itself(self):
        self.assertTrue(self._speaks_for_itself("query_plan", '{"sheet_number": "A-101"}'))

    def test_a_question_does_not(self):
        self.assertFalse(self._speaks_for_itself(
            "query_plan", '{"question": "how many roof drains"}'))

    def test_a_blank_question_is_no_question(self):
        self.assertTrue(self._speaks_for_itself("query_plan", '{"question": "   "}'))

    def test_unparsable_arguments_fall_back_to_the_safe_side(self):
        # Rather than run an LLM round that may double-reply.
        self.assertTrue(self._speaks_for_itself("query_plan", "not json"))

    def test_the_other_async_tool_is_untouched(self):
        self.assertTrue(self._speaks_for_itself("start_checklist", "{}"))

    def test_a_synchronous_tool_is_not_async(self):
        self.assertFalse(self._speaks_for_itself("search_plans", '{"subject": "x"}'))


class OneReaderOnly(unittest.TestCase):

    def test_search_plans_is_what_reads_records(self):
        src = inspect.getsource(server._dispatch_agent_tool)
        self.assertEqual(src.count("await search_plans("), 2)  # both branches

    def test_both_paths_feed_the_same_gate(self):
        # One sink, one gate: whichever tool fetched the records, the composed
        # answer is checked against them.
        #
        # THE GATE IS REACHED THROUGH `gate_and_warrant` NOW, not called
        # directly. That indirection is not cosmetic: the warrant that runs
        # after the gate has to be reachable from the benchmark harness, which
        # lives outside the repo and cannot call a closure. This assertion
        # names the shared callable so the property it protects — every
        # composed answer meets the gate — still holds through it.
        src = inspect.getsource(server._run_group_agent)
        self.assertIn("plan_evidence", src)
        self.assertIn("gate_and_warrant(", src)
        self.assertIn("record_sink=plan_evidence", src)

    def test_the_prompt_sends_questions_to_the_reader(self):
        self.assertIn("search_plans FIRST", server._AGENT_SYSTEM_PROMPT_BASE)


if __name__ == "__main__":
    unittest.main()
