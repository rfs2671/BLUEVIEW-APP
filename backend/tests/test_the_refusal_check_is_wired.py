"""THE CORE WAS TESTED. THIS TESTS THAT IT IS REACHED.

`lib/plan_refusal.py` has 15 tests and none of them proves the check ever
runs. A pure function that nothing calls is the same as no function, and the
gap between "built" and "wired" is where this sat for a day.

So these are wiring tests, and they assert the three things a reader would
otherwise have to take on trust:

  1. the gate is async and AWAITED at every call site - an un-awaited
     coroutine is falsy-but-not-None and would have shipped the string
     "<coroutine object>" or silently dropped the reply
  2. the trigger is `classify_reply`, the SAME instrument the benchmark counts
     with, so what fires the check and what measures it cannot drift
  3. every failure path lets the refusal stand

── WHY (3) IS THE LOAD-BEARING ONE ──────────────────────────────────────────

The check exists to overturn a refusal that was wrong. If it throws, times
out, gets a 503, finds no candidate sheet, or the model returns something
unparseable, the crew must get exactly what they get today. A check that
cannot run is not a reason to change what anyone is told.
"""

from __future__ import annotations

import asyncio
import ast
import inspect
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import plan_eval, plan_refusal, plan_search  # noqa: E402


class TheGateAwaitsIt(unittest.TestCase):

    def setUp(self):
        self.src = inspect.getsource(server._run_group_agent)

    def test_the_gate_is_async(self):
        self.assertIn("async def _gated", self.src)

    def test_every_call_site_awaits_it(self):
        """An un-awaited coroutine is truthy and is not a string. Missing one
        of these would send a coroutine repr to a superintendent."""
        calls = self.src.count("_gated(")
        awaited = self.src.count("await _gated(")
        self.assertEqual(
            calls - 1, awaited,  # -1 for the `async def _gated(` line itself
            f"{calls - 1} call site(s), {awaited} awaited")

    def test_the_gate_is_reached_through_the_shared_callable(self):
        """`_gated` must not run its own gate-then-warrant sequence. It had
        one, inline, and that is how the benchmark came to measure a path with
        no warrant in it — see TheMeasurementRunsTheSameSequence below."""
        self.assertIn("await gate_and_warrant(", self.src)
        self.assertNotIn("gate_plan_answer(", self.src)

    def test_the_question_uses_the_users_words(self):
        """`body`, not `subject`. The subject is the model's paraphrase and it
        is the thing that just failed to find anything."""
        self.assertIn("body or subject", self.src)


class TheMeasurementRunsTheSameSequence(unittest.TestCase):
    """THE BENCHMARK MUST BE ABLE TO RUN WHAT SHIPS.

    The warrant was first wired inside `_gated`, the only caller of
    `gate_plan_answer` in the repo. That looked like a chokepoint and was not
    one: `_gated` is a closure inside `_run_group_agent`, and the 40-question
    harness lives outside the repo and calls `gate_plan_answer` directly,
    because a closure cannot be called from outside its function. The
    benchmark would have measured the feature as changing nothing.

    A test over in-repo callers cannot catch that — the harness is not in the
    repo. What can be enforced here is that a reachable callable exists and
    that nothing in the repo runs the gate without it."""

    def setUp(self):
        self.tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))

    def test_the_shared_callable_is_module_level_and_async(self):
        """Module level, so the harness can import it; async, because the
        warrant is."""
        node = next((n for n in self.tree.body
                     if isinstance(n, ast.AsyncFunctionDef)
                     and n.name == "gate_and_warrant"), None)
        self.assertIsNotNone(node, "gate_and_warrant must be importable")
        self.assertTrue(callable(getattr(server, "gate_and_warrant", None)))

    def test_nothing_else_in_the_repo_calls_the_bare_gate(self):
        """One caller, and it is the shared callable. A second one added later
        would silently skip the warrant — the same shape as the arity bug that
        no test entered."""
        callers = []
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name)
                        and sub.func.id == "gate_plan_answer"):
                    callers.append(node.name)
        self.assertEqual(
            callers, ["gate_and_warrant"],
            f"gate_plan_answer is called by {callers}; every caller must go "
            f"through gate_and_warrant or the warrant is skipped")

    def test_the_trigger_is_the_measured_instrument(self):
        """Not a fresh regex. The split has already been measured by three
        incomparable instruments; a second definition of 'refusal' here would
        make a fourth."""
        src = inspect.getsource(server.gate_and_warrant)
        self.assertIn("classify_reply(sent, outcome)", src)

    def test_no_project_means_the_gate_alone(self):
        """The suite and most tests have no project. They must get exactly the
        behaviour they had before the warrant existed."""
        sent, outcome = asyncio.run(server.gate_and_warrant(
            "PTAC-1: 21 units [M-200.00].",
            [{"quote": "PTAC-1 21", "sheet_number": "M-200.00"}],
            "ptac"))
        self.assertEqual(outcome, "grounded")
        self.assertEqual(sent, "PTAC-1: 21 units [M-200.00].")


class EveryFailurePathLetsTheRefusalStand(unittest.TestCase):

    def _run(self, **patches):
        saved = {k: getattr(server, k) for k in patches}
        for k, v in patches.items():
            setattr(server, k, v)
        try:
            return asyncio.run(server.check_refusal_against_the_sheet(
                "p1", "how tall is the parapet",
                [{"sheet_number": "A-101.00"}]))
        finally:
            for k, v in saved.items():
                setattr(server, k, v)

    def test_no_candidate_sheet(self):
        got = asyncio.run(server.check_refusal_against_the_sheet(
            "p1", "anything", [{"quote": "x"}]))
        self.assertIsNone(got)

    def test_no_records_at_all(self):
        self.assertIsNone(asyncio.run(
            server.check_refusal_against_the_sheet("p1", "anything", [])))

    def test_no_vision_key_configured(self):
        self.assertIsNone(self._run(QWEN_API_KEY=""))

    def test_the_page_cannot_be_found(self):
        async def no_pages(*a, **k):
            return []
        self.assertIsNone(self._run(QWEN_API_KEY="k",
                                    _current_record_page_ids=no_pages))

    def test_anything_raising_is_swallowed(self):
        async def boom(*a, **k):
            raise RuntimeError("the database went away")
        self.assertIsNone(self._run(QWEN_API_KEY="k",
                                    _current_record_page_ids=boom))


class ItMayContradictButNeverSupply(unittest.TestCase):
    """The asymmetry that makes this safe, asserted on the parse."""

    def test_a_no_leaves_the_refusal_alone(self):
        verdict, _where = plan_refusal.parse_verdict("NO")
        self.assertEqual(verdict, "no")

    def test_a_value_in_the_location_is_stripped(self):
        """Asked not to write the value, this model answered `YES | 2/27/2025`.
        The prompt is an instruction; the strip is the enforcement."""
        verdict, where = plan_refusal.parse_verdict("YES | 2/27/2025")
        self.assertEqual(verdict, "yes")
        self.assertEqual(where, "")

    def test_the_replacement_names_only_our_own_sheet(self):
        """The sheet number comes from OUR record. Only the location phrase is
        the model's, and only when it carries no digits."""
        said = plan_refusal.found_but_unreadable("A-101.00", "title block")
        self.assertIn("A-101.00", said)
        self.assertIn("title block", said)
        self.assertNotIn("2/27", said)

    def test_an_unparseable_reply_is_not_a_yes(self):
        for junk in ("", "I think so?", "MAYBE", "The date is 2/27/2025"):
            verdict, _ = plan_refusal.parse_verdict(junk)
            self.assertNotEqual(verdict, "yes", f"{junk!r} read as YES")


class TheCallIsCountedLikeEveryOtherOne(unittest.TestCase):

    def test_it_has_its_own_metered_endpoint(self):
        """Its volume is the REFUSAL rate, not the question rate, so it cannot
        share a name with the calls whose trigger is a question."""
        from lib import vision_meter as vm
        self.assertIn(vm.VISION_REFUSAL_CHECK, vm.VISION_ENDPOINTS)
        src = inspect.getsource(server.check_refusal_against_the_sheet)
        self.assertIn("VISION_REFUSAL_CHECK", src)

    def test_it_is_recorded_before_the_call_not_after(self):
        """A call that fails still cost money. Metering after the response
        would undercount exactly the failures worth knowing about."""
        src = inspect.getsource(server.check_refusal_against_the_sheet)
        self.assertLess(src.index("record_vision_call"),
                        src.index("chat/completions"))

    def test_the_output_is_bounded(self):
        src = inspect.getsource(server.check_refusal_against_the_sheet)
        self.assertIn("plan_refusal.MAX_OUTPUT_TOKENS", src)
        self.assertLessEqual(plan_refusal.MAX_OUTPUT_TOKENS, 60)


class TheInstrumentAgreesWithItself(unittest.TestCase):
    """If `classify_reply` stopped calling these refusals, the check would
    stop firing and nothing else would notice."""

    def test_the_shape_the_system_actually_emits_is_a_refusal(self):
        """TAKEN FROM `render_records`, not invented. The first draft of this
        test asserted on "No records matched." - a phrasing nothing in this
        system produces, which `classify_reply` calls a hedge because
        `_REPLY_REFUSAL` is anchored and matches "no match", not "no records".
        Asserting on a guessed string tests the guess."""
        from lib import plan_search
        emitted = plan_search.render_records([], "parapet height")
        self.assertEqual(plan_eval.classify_reply(emitted), "refusal",
                         f"the empty render {emitted!r} no longer reads as a "
                         f"refusal, so the check would stop firing")

    def test_the_other_shapes_it_produces_are_refusals_too(self):
        for text in ("Not found.",
                     "I couldn't find that on the drawings.",
                     "Nothing found for that."):
            self.assertEqual(plan_eval.classify_reply(text), "refusal",
                             f"{text!r} no longer reads as a refusal")

    def test_the_replacement_scores_as_a_refusal_that_names_a_sheet(self):
        """ASSERT THE BUCKET BY NAME, not a negative. This was written as
        `assertNotEqual(..., "refusal")` when the observed behaviour was
        `cited`, so it passed while the classifier was scoring the warrant's
        own output as an answer — a negative assertion is satisfied by every
        wrong value, so it pinned nothing.

        The bucket is `refusal` on purpose: nothing was read and no value was
        delivered, so the refusal rate must not fall because the warrant
        fired. What changed is that the refusal now names a sheet worth
        opening, and the feature is counted from the outcome
        (`refusal_overturned`), not from a bucket moving."""
        said = plan_refusal.found_but_unreadable("A-101.00", "title block")
        self.assertEqual(plan_eval.classify_reply(said), "refusal")
        self.assertNotEqual(said, plan_search.NOT_FOUND)
        self.assertIn("A-101.00", said)


if __name__ == "__main__":
    unittest.main()
