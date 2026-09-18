"""A call that never came back is not a sheet that prints nothing.

MEASURED ON THE PRODUCTION CORPUS, 588 Thomas S Boyland Street, 2026-09-17.
Of 129 indexed pages, 19 carry at least one `call_failed:` flag — one in
seven. Seventeen of those failures are on the TITLE BLOCK: ten ReadTimeout,
seven a provider error. Eight of the pages ended with no sheet number at all.

Seven of those eight are documents — DEP cross-connection forms, an inspection
letter, an as-built survey — and a form has no sheet number to lose. The
eighth is a drawing: the roof plan reissued in `AR - 6.9.26 (Gas change).pdf`,
whose text layer opens with the same six 42" PARAPET callouts as A-105.00.

Nothing retried the call. Nothing revisited the page. The row was written
`page_complete: True` and the absence was stored as though the sheet prints no
number — and every reader downstream believed it:

  * supersession keys on sheet number, so the reissue could not be matched to
    the sheet it replaces; both stayed current and the same roof-drain count
    was carried twice. That is the "supersession gap" in full: supersession
    was handed a page with no identity and did the only thing it could.
  * a named-sheet lookup cannot find it.
  * a citation cannot name it, which is the '?' in
    test_an_answer_says_where_it_came_from.py.

Two rules, and they are the whole of this file:

  1. A failure worth asking again is asked again, once, inside the page
     budget. A timeout, a dropped connection, a 429 or a 5xx.
  2. A page that lost its title block and has no sheet number is NOT complete.
     A resume indexes it again instead of inheriting the failure.
"""

import asyncio
import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import httpx  # noqa: E402

import server  # noqa: E402
from lib import plan_extract  # noqa: E402
from tests.test_plan_index_v3 import _Db, _run  # noqa: E402

# A page whose text layer carries its own sheet number, and one that does not.
NUMBERED = {
    "page_number": 2, "width": 2592, "height": 1728, "fractions_rebuilt": 0,
    "fractions_unverified": [], "tables": [],
    "blocks": [
        {"bbox": [100, 400, 900, 800], "lines": ["1.", "ALL PILES SHALL BE HELICAL PILES."],
         "text": "1.\nALL PILES SHALL BE HELICAL PILES."},
        {"bbox": [100, 1600, 900, 1700], "lines": ["S-001.00", "GENERAL NOTES"],
         "text": "S-001.00\nGENERAL NOTES"},
    ],
}
NUMBERED["text"] = "\n".join(b["text"] for b in NUMBERED["blocks"]) + (" FILLER" * 30)

# The gas-change roof plan's shape: dimensions and legend text, no title block.
UNNUMBERED = {
    "page_number": 2, "width": 2592, "height": 1728, "fractions_rebuilt": 0,
    "fractions_unverified": [], "tables": [],
    "blocks": [
        {"bbox": [100, 400, 900, 800],
         "lines": ['42" PARAPET', '42" PARAPET', "3'-0\""],
         "text": '42" PARAPET 42" PARAPET 3\'-0"'},
        {"bbox": [100, 900, 900, 1000],
         "lines": ["LEGEND A FLOOR/AREA/ROOF DRAIN"],
         "text": "LEGEND A FLOOR/AREA/ROOF DRAIN"},
    ],
}
UNNUMBERED["text"] = "\n".join(b["text"] for b in UNNUMBERED["blocks"]) + (" FILLER" * 30)


class _Resp:
    def __init__(self, status=200, content='{"sheet_number": "A-105.01"}'):
        self.status_code = status
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content},
                             "finish_reason": "stop"}]}


def _index(layout, *, outcomes, meter=None):
    """Index one page, with `outcomes` consumed one per HTTP attempt.

    Each item is either an exception to raise or a _Resp to return.
    """
    db = _Db()
    attempts = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            attempts.append(1)
            out = outcomes[min(len(attempts) - 1, len(outcomes) - 1)]
            if isinstance(out, Exception):
                raise out
            return out

    async def noop(*a, **k):
        return "key"

    async def emb(text):
        return [0.1]

    async def metered(*a, **k):
        if meter is not None:
            meter.append(1)

    with mock.patch.object(server, "db", db), \
            mock.patch.object(server, "ServerHttpClient", _Client), \
            mock.patch.object(server, "_upload_page_jpeg_to_r2", noop), \
            mock.patch.object(server, "_upload_page_thumb_to_r2", noop), \
            mock.patch.object(server, "_upload_page_base_to_r2", noop), \
            mock.patch.object(server, "_generate_embedding", emb), \
            mock.patch.object(server, "record_vision_call", metered):
        _run(server._index_single_page(
            project_id="p1", company_id="c1", file_id="f1",
            file_name="AR - 6.9.26 (Gas change).pdf", file_hash="h",
            page_number=2, discipline="AR", page_text=layout["text"],
            page_image_bytes=b"jpeg", layout=layout))
    row = db.document_page_index.rows[0]
    return row, len(attempts)


class AFailureWorthAskingAgainIsAskedAgain(unittest.TestCase):

    def test_a_timeout_is_retried_and_the_second_answer_is_kept(self):
        """Asserted on a field only the MODEL supplies. That the call happened
        twice proves the retry; that the title reached the row proves the
        retry's answer was used rather than discarded with the first."""
        row, attempts = _index(
            NUMBERED,
            outcomes=[httpx.ReadTimeout("too slow"),
                      _Resp(content='{"sheet_number": "S-001.00", '
                                    '"sheet_title": "STRUCTURAL GENERAL NOTES"}')])
        self.assertEqual(attempts, 2)
        self.assertEqual(row.get("sheet_title"), "STRUCTURAL GENERAL NOTES",
                         "the retry's answer was thrown away")
        self.assertEqual(row.get("sheet_number"), "S-001.00")
        self.assertEqual(row.get("sections_lost"), [])
        self.assertEqual(row.get("extraction_retries"), 1)

    def test_a_number_the_page_cannot_corroborate_is_still_refused(self):
        """THE RETRY IS NOT A SECOND CHANCE TO BE BELIEVED. Asked again, the
        model may answer 'A-105.01' for a page whose text prints no such
        number anywhere, and validate_sheet_number rejects it exactly as
        before. The gas-change page carried BOTH flags in production —
        `call_failed:ReadTimeout` and `sheet_number_ambiguous` — and they are
        two different failures that happen to end in the same silence.

        This is the limit of what a retry can fix, and it is why the retry
        alone does not promise to identify that page."""
        row, attempts = _index(
            UNNUMBERED,
            outcomes=[httpx.ReadTimeout("too slow"), _Resp()])
        self.assertEqual(attempts, 2)
        self.assertEqual(row.get("sections_lost"), [],
                         "the section answered; it was the ANSWER that failed")
        self.assertIsNone(row.get("sheet_number"))

    def test_an_answer_we_could_not_verify_does_not_make_a_page_unfinished(self):
        """A page is incomplete when we never got an answer, not when we got
        one we could not corroborate. Asking a legible title block again
        returns the same unverifiable number, so marking it incomplete would
        make every resume re-index it for ever and never converge.

        The page is finished and unidentified, and the row says which: an
        empty `sections_lost` beside the title block's own verdict on the
        number — `sheet_number_unresolved` when the page prints no candidate
        for the model's answer to match, `sheet_number_ambiguous` when it
        prints several."""
        row, _a = _index(
            UNNUMBERED,
            outcomes=[httpx.ReadTimeout("too slow"), _Resp()])
        self.assertTrue(row.get("page_complete"))
        self.assertEqual(row.get("sections_lost"), [])
        title_flags = " ".join((row.get("extraction_flags") or {}).get("title_block") or [])
        self.assertIn("sheet_number_", title_flags,
                      "the row does not say why the page has no number")

    def test_a_dropped_connection_too(self):
        _row, attempts = _index(
            UNNUMBERED, outcomes=[httpx.ConnectError("reset"), _Resp()])
        self.assertEqual(attempts, 2)

    def test_and_a_provider_that_is_busy(self):
        for status in (429, 500, 503):
            with self.subTest(status=status):
                _row, attempts = _index(
                    UNNUMBERED, outcomes=[_Resp(status=status), _Resp()])
                self.assertEqual(attempts, 2)

    def test_but_not_a_request_the_provider_refused(self):
        """A 400 fails identically the second time; asking again spends the
        page's budget to learn nothing."""
        row, attempts = _index(UNNUMBERED, outcomes=[_Resp(status=400)])
        self.assertEqual(attempts, 1)
        self.assertIn("title_block", row.get("sections_lost") or [])

    def test_and_never_the_budget_itself(self):
        """BudgetExhausted IS the ceiling. Retrying it would be the page
        asking its own limit for more."""
        self.assertFalse(server._worth_asking_again(
            server.BudgetExhausted("out of time")))

    def test_at_most_one_retry(self):
        row, attempts = _index(
            UNNUMBERED, outcomes=[httpx.ReadTimeout("a"), httpx.ReadTimeout("b"),
                                  _Resp()])
        self.assertEqual(attempts, 2, "a second retry is an unbounded page")
        self.assertIn("title_block", row.get("sections_lost") or [])

    def test_every_attempt_is_metered(self):
        """A retry is a real call and a real invoice line. Counting one per
        section would put a number in the meter no bill will match."""
        meter = []
        _row, attempts = _index(
            UNNUMBERED, outcomes=[httpx.ReadTimeout("x"), _Resp()], meter=meter)
        self.assertEqual(len(meter), attempts)


class WhatTheRowSaysItLost(unittest.TestCase):

    def test_a_section_that_never_answered_is_named(self):
        row, _a = _index(UNNUMBERED, outcomes=[_Resp(status=400)])
        self.assertEqual(row.get("sections_lost"), ["title_block"])

    def test_silence_only_and_not_an_answer_we_could_not_read(self):
        """`unparseable` means the model answered and we could not read it —
        a different repair, and not this field's business."""
        self.assertEqual(server._sections_lost({"notes": ["unparseable"]}), [])
        self.assertEqual(server._sections_lost({"notes": ["hit_max_tokens"]}), [])
        self.assertEqual(
            server._sections_lost({"notes": ["call_failed:ReadTimeout"]}),
            ["notes"])

    def test_the_count_of_retries_is_on_the_row(self):
        row, _a = _index(UNNUMBERED, outcomes=[httpx.ReadTimeout("x"), _Resp()])
        self.assertEqual(row.get("extraction_retries"), 1)


class APageWithNoIdentityIsNotComplete(unittest.TestCase):

    def test_the_gas_change_roof_plan_stays_incomplete(self):
        """The measured case: title block lost, nothing in the text layer to
        fall back on, so the page has no sheet number and no identity."""
        row, _a = _index(UNNUMBERED, outcomes=[_Resp(status=400)])
        self.assertIsNone(row.get("sheet_number"))
        self.assertIn("title_block", row["sections_lost"])
        self.assertFalse(row.get("page_complete"),
                         "a page with no identity was written complete")

    def test_so_a_resume_indexes_it_again(self):
        """`page_complete` is exactly what the resume path skips on, which is
        why the failure was inherited rather than repaired."""
        row, _a = _index(UNNUMBERED, outcomes=[_Resp(status=400)])
        db = _Db()
        db.document_page_index.rows.append(dict(row, file_id="f1", file_hash="h"))
        with mock.patch.object(server, "db", db):
            done = _run(server._pages_already_indexed("f1", "h"))
        self.assertNotIn(2, done)

    def test_but_a_page_that_found_its_number_elsewhere_is_complete(self):
        """The title block failing is not the same as the page being
        unidentified: S-001.00 prints its own number in the text layer, and
        eleven of the seventeen measured failures recovered exactly that way.
        Those pages are finished and must not be indexed twice."""
        row, _a = _index(NUMBERED, outcomes=[_Resp(status=400)])
        self.assertEqual(row.get("sheet_number"), "S-001.00")
        self.assertIn("title_block", row["sections_lost"])
        self.assertTrue(row.get("page_complete"))

    def test_and_a_clean_page_is_complete_as_before(self):
        row, attempts = _index(NUMBERED, outcomes=[_Resp()])
        self.assertEqual(attempts, 1)
        self.assertEqual(row.get("sections_lost"), [])
        self.assertTrue(row.get("page_complete"))


# ══════════════════════════════════════════════════════════════════════════
# A retry must never starve a section that has not been tried
# ══════════════════════════════════════════════════════════════════════════


class EverySectionOnceThenTheFailuresAgain(unittest.TestCase):
    """MEASURED ON THE RE-INDEX OF 2026-09-18, twenty minutes in: of the first
    22 pages, 9 lost their title block, and 13 of the 22 failures were
    `BudgetExhausted` rather than a provider error. Fifteen pages retried and
    still lost something.

    The retry fired where the call failed, before the rest of the page had
    been asked at all. The 300-second page budget is shared, so one slow
    section could spend it twice while the sections behind it were refused
    without ever being asked once. The retry did not cause the timeouts; it
    multiplied what each one cost.

    So the order changed: every section is asked once, and only then is what
    is left of the budget spent re-asking the ones that came back empty."""

    SECTIONS = plan_extract.SECTIONS

    def _run_page(self, outcomes):
        """`outcomes` maps a section name to a list of results, consumed one
        per call: an exception to raise, or a JSON string to return."""
        asked = []

        # EVERY SECTION PROMPT OPENS WITH THE SAME PARAGRAPH and ENDS with the
        # page text, so neither a prefix nor a suffix tells them apart — a
        # prefix made every call look like the first section, a suffix matched
        # none. What differs is the schema each one asks for, so the marker is
        # a token that appears in exactly one section's prompt.
        prompts = {n: plan_extract.section_prompt(n, "") for n in self.SECTIONS}
        markers = {}
        for n, text in prompts.items():
            others = " ".join(v for k, v in prompts.items() if k != n)
            markers[n] = next(w for w in text.split()
                              if len(w) > 6 and w not in others)

        async def vlm(image_b64, prompt, max_tokens):
            name = next(n for n, marker in markers.items() if marker in prompt)
            asked.append(name)
            queue = outcomes.get(name) or ['{}']
            out = queue[min(len([a for a in asked if a == name]) - 1, len(queue) - 1)]
            if isinstance(out, Exception):
                raise out
            return (out, "stop")

        result = _run(plan_extract.extract_page(
            image_b64="x", page_text="A-101.00 FIRST FLOOR PLAN " + ("FILLER " * 40),
            vlm_call=vlm))
        return result, asked

    def test_every_section_is_asked_before_any_is_asked_twice(self):
        """THE RULE. The first section times out; the retry must wait until
        the last section has had its turn."""
        first = self.SECTIONS[0]
        result, asked = self._run_page({first: [httpx.ReadTimeout("slow"), '{}']})
        first_pass = asked[:len(self.SECTIONS)]
        self.assertEqual(sorted(first_pass), sorted(self.SECTIONS),
                         f"a section was asked twice before the page was done: {asked}")
        self.assertEqual(asked[len(self.SECTIONS):], [first],
                         "the retry did not happen, or happened out of turn")

    def test_a_section_that_never_answered_is_asked_again(self):
        first = self.SECTIONS[0]
        _result, asked = self._run_page({first: [httpx.ReadTimeout("slow"), '{}']})
        self.assertEqual(asked.count(first), 2)

    def test_and_the_second_answer_is_the_one_kept(self):
        notes = "notes" if "notes" in self.SECTIONS else self.SECTIONS[-1]
        result, _asked = self._run_page(
            {notes: [httpx.ReadTimeout("slow"), '{"notes": []}']})
        # Asserted on the FLAGS rather than as a substring ban: "call_failed"
        # is a prefix of every failure flag there is, and a bare-word ban is
        # satisfied or broken by anything that happens to contain it.
        still_failed = [f for f in (result["flags"].get(notes) or [])
                        if str(f).startswith("call_failed:")]
        self.assertEqual(still_failed, [],
                         "the second answer was not kept")

    def test_the_row_says_it_was_asked_twice(self):
        first = self.SECTIONS[0]
        result, _asked = self._run_page({first: [httpx.ReadTimeout("slow"), '{}']})
        self.assertTrue(any(str(f).startswith("retried_after:ReadTimeout")
                            for f in result["flags"].get(first) or []),
                        result["flags"].get(first))

    def test_a_budget_that_is_gone_is_not_asked_again(self):
        """BudgetExhausted IS the ceiling. Asking again is asking the page's
        own limit for more, and the call would be refused on arrival."""
        first = self.SECTIONS[0]
        _result, asked = self._run_page({first: [server.BudgetExhausted("gone")]})
        self.assertEqual(asked.count(first), 1)

    def test_nor_is_an_answer_we_simply_could_not_read(self):
        """`unparseable` means the model answered. Asking again usually
        returns the same shape and spends budget a section that was never
        asked could have used."""
        first = self.SECTIONS[0]
        _result, asked = self._run_page({first: ["not json at all"]})
        self.assertEqual(asked.count(first), 1)

    def test_a_clean_page_is_asked_once_per_section_and_no_more(self):
        result, asked = self._run_page({})
        self.assertEqual(len(asked), len(self.SECTIONS))
        self.assertEqual(server._retries_in(result["flags"]), 0)

    def test_the_wrapper_no_longer_retries_on_its_own(self):
        """Two retry loops would be four calls for one section, and the page
        budget would be gone twice as fast as either intended."""
        src = inspect.getsource(server._index_single_page)
        i = src.index("async def _section_call")
        block = src[i:i + 900]
        self.assertNotIn("for attempt in range", block)
        # The constant is gone, asserted on the MODULE rather than as a bare
        # word against its source — the attribute either exists or it does not.
        self.assertFalse(hasattr(server, "PLAN_INDEX_CALL_ATTEMPTS"),
                         "the wrapper still carries its own attempt count")

    def test_the_budget_is_still_the_wrappers_job(self):
        """plan_extract does not know what a budget is. It stops retrying
        because the injected call starts refusing, which is the only thing
        keeping the second pass inside the ceiling."""
        src = inspect.getsource(server._index_single_page)
        self.assertIn("BudgetExhausted", src)
        self.assertIn("PLAN_INDEX_MIN_CALL_SECONDS", src)


class TheTwoShapesOfTheRuleAgree(unittest.TestCase):
    """One rule, two shapes, and neither may drift from the other.

    `server._worth_asking_again` takes an exception and is what the card
    reader's `vision_status_is_retryable` delegates to.
    `plan_extract.flag_is_retryable` takes the flags a failed call left on the
    row, because the second pass runs after the exception is gone.

    plan_extract cannot import server — server imports plan_extract — so the
    agreement cannot be shared in code. THIS TEST IS THE LINKAGE, which is why
    it sweeps the input space instead of sampling it: a sample leaves holes
    exactly where nobody thought to look, both sides keep passing, and the row
    answers wrong on a status nobody picked. That is not hypothetical — the
    first version of the flag was `call_failed:{type name}`, which collapsed
    503 and 400 into one string, and five sampled statuses only catch that if
    two of them straddle the boundary.

    The rule's whole input space is enumerable, so it is enumerated.
    """

    @staticmethod
    def _every_httpx_error():
        """Every concrete httpx error class, not three names.

        A named list covers three of twenty and goes green for ever while the
        other seventeen drift."""
        found, stack = set(), [httpx.HTTPError]
        while stack:
            for sub in stack.pop().__subclasses__():
                found.add(sub)
                stack.append(sub)
        return sorted(found, key=lambda c: c.__name__)

    @staticmethod
    def _instance(cls):
        """An instance to ask the rule about.

        HTTPStatusError needs a request and a response; the rule only ever
        looks at the TYPE, so an uninitialised instance answers the same
        question without a fixture that would have to be maintained."""
        try:
            return cls("x")
        except TypeError:
            return cls.__new__(cls)

    def _agree(self, exc):
        """(by_exception, by_flag) for one failure."""
        return (server._worth_asking_again(exc),
                plan_extract.flag_is_retryable(
                    [plan_extract._call_failed_flag(exc)]))

    def test_every_provider_status_gets_the_same_answer(self):
        """ALL of them, 100 to 599. This is the case that bit the first
        version, and it pins the boundary exactly — 428 no, 429 yes, 430 no,
        499 no, 500 yes."""
        disagreed = []
        for status in range(100, 600):
            by_exc, by_flag = self._agree(server.ProviderStatus(status))
            if by_exc != by_flag:
                disagreed.append((status, by_exc, by_flag))
        self.assertEqual(disagreed, [], f"the two shapes disagree: {disagreed[:8]}")

    def test_and_the_boundary_is_where_it_is_meant_to_be(self):
        for status, want in ((428, False), (429, True), (430, False),
                             (499, False), (500, True), (503, True), (599, True),
                             (200, False), (400, False), (404, False)):
            with self.subTest(status=status):
                self.assertEqual(server._worth_asking_again(
                    server.ProviderStatus(status)), want)

    def test_every_httpx_error_gets_the_same_answer(self):
        classes = self._every_httpx_error()
        self.assertGreater(len(classes), 10,
                           "the sweep found almost nothing; has httpx moved?")
        disagreed = []
        for cls in classes:
            by_exc, by_flag = self._agree(self._instance(cls))
            if by_exc != by_flag:
                disagreed.append((cls.__name__, by_exc, by_flag))
        self.assertEqual(disagreed, [], f"the two shapes disagree: {disagreed}")

    def test_the_budget_is_not_a_provider_failure_in_either_shape(self):
        self.assertEqual(self._agree(server.BudgetExhausted("gone")), (False, False))

    def test_the_sweep_can_actually_fail(self):
        """AN INSTRUMENT THAT CANNOT FAIL MEASURES NOTHING. A predicate that
        returned a constant would pass a 500-case agreement test perfectly, so
        the sweep must contain both answers."""
        answers = {server._worth_asking_again(server.ProviderStatus(s))
                   for s in range(100, 600)}
        self.assertEqual(answers, {True, False})
        httpx_answers = {server._worth_asking_again(self._instance(c))
                         for c in self._every_httpx_error()}
        self.assertEqual(httpx_answers, {True, False})

    def test_the_flag_carries_what_the_decision_needs(self):
        """A flag of `call_failed:ProviderStatus` alone cannot tell a 503 from
        a 400, and those are opposite answers. The status travels with it."""
        self.assertEqual(plan_extract._call_failed_flag(server.ProviderStatus(503)),
                         "call_failed:ProviderStatus:503")
        # And it cannot tell a CloseError from a DecodingError by name alone —
        # both are httpx errors, one is worth asking again and one is not — so
        # the flag carries the ANCESTRY's verdict rather than a list of names
        # this module would have to maintain.
        self.assertEqual(plan_extract._call_failed_flag(httpx.ReadTimeout("x")),
                         "call_failed:ReadTimeout:transient")
        self.assertEqual(plan_extract._call_failed_flag(httpx.CloseError("x")),
                         "call_failed:CloseError:transient")
        self.assertEqual(plan_extract._call_failed_flag(httpx.DecodingError("x")),
                         "call_failed:DecodingError")

    def test_an_unreadable_flag_is_not_retried(self):
        """A row written by an older build, or a flag that lost its status:
        the answer is no, because guessing is the thing being removed."""
        self.assertFalse(plan_extract.flag_is_retryable(["call_failed:ProviderStatus"]))
        self.assertFalse(plan_extract.flag_is_retryable(["call_failed:ProviderStatus:x"]))

    def test_neither_name_is_the_other(self):
        """Deliberately different names: one takes an exception, one takes a
        row. Sharing a name is how the next reader edits the wrong one."""
        self.assertFalse(hasattr(plan_extract, "_worth_asking_again"))
        self.assertFalse(hasattr(server, "flag_is_retryable"))


class TheCardReadStillSharesTheRule(unittest.TestCase):
    """`vision_status_is_retryable` derives the card read's answer from
    `_worth_asking_again`. The plan index stopped calling that function when
    its retry moved, and deleting it would have broken a caller in another
    feature — silently, because nothing in the plan-index tests touches it."""

    def test_the_rule_is_still_there_and_still_shared(self):
        self.assertTrue(server.vision_status_is_retryable(429))
        self.assertTrue(server.vision_status_is_retryable(503))
        self.assertFalse(server.vision_status_is_retryable(400))
        self.assertIn("_worth_asking_again",
                      inspect.getsource(server.vision_status_is_retryable))


if __name__ == "__main__":
    unittest.main()
