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


if __name__ == "__main__":
    unittest.main()
