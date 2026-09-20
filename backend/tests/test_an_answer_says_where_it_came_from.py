"""An answer never cites '?'.

588 Boyland, 2026-09-16: "are there chase walls" replied

    Yes — chase walls is on T-001.01, Z-001.01, A-100.01, A-105.01.
    ? (text): CONC. WALL

The '?' is a page whose sheet number could not be read. That is a deliberate
outcome — a wrong sheet number hides another sheet, so an unreadable title
block leaves the page unnumbered — but the record was still quoted, and '?'
names nothing a superintendent can open. It reads as a fault in the system
rather than a gap in the drawings, which is the same failure as a well-formed
answer with nothing behind it.

A record says where it is: its sheet number, or the file and page every record
carries. A record that can say neither is not quoted.

── WHAT CHANGED WHEN THE MATCHER WENT ─────────────────────────────────────

This was held against pe.cite and the answer_* formatters. Both are deleted.
The rule did not move: it is now inside the two renders that put a record in
front of a person or a model, checked here against each of them. Seven of the
111 current pages carry no sheet number, so this is live every day.

The other half of that live answer — 'chase walls' matching 'CONC. WALL' —
is eval case `chase-walls-absent`. CHASE is printed on no current page.
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

import server  # noqa: E402
from lib import plan_search as ps  # noqa: E402

UNNUMBERED = {
    "project_id": "p1", "page_id": "pg1", "page_number": 2,
    "sheet_number": None, "sheet_title": "Roof Plan",
    "file_name": "AR - 6.9.26 (Gas change).pdf",
    "record_type": "note", "ordinal": 0, "tier": "text_layer",
    "quote": "CHASE WALL AT SHAFT", "subject_terms": ["chase", "wall"],
}


def _record(**over):
    return dict(UNNUMBERED, **over)


class WhatTheCrewIsShown(unittest.TestCase):
    """render_records — the fallback the gate substitutes for a bad answer."""

    def test_the_sheet_number_when_there_is_one(self):
        out = ps.render_records([_record(sheet_number="A-105.01")], "chase wall")
        self.assertIn("A-105.01", out)
        self.assertNotIn("?", out)

    def test_the_file_and_page_when_there_is_not(self):
        out = ps.render_records([_record()], "chase wall")
        self.assertIn("AR - 6.9.26 (Gas change).pdf p2", out)
        self.assertNotIn("?", out)

    def test_the_page_alone_when_the_file_is_unknown(self):
        out = ps.render_records([_record(file_name=None)], "chase wall")
        self.assertIn("page 2", out)
        self.assertNotIn("?", out)

    def test_a_record_that_can_say_neither_is_not_quoted(self):
        out = ps.render_records(
            [_record(file_name=None, page_number=None)], "chase wall")
        self.assertEqual(out, "Not found.")

    def test_one_uncitable_record_does_not_take_the_citable_one_with_it(self):
        out = ps.render_records(
            [_record(file_name=None, page_number=None),
             _record(sheet_number="A-105.01", page_id="pg2")], "chase wall")
        self.assertIn("A-105.01", out)
        self.assertNotIn("?", out)

    def test_whitespace_is_not_a_sheet_number(self):
        out = ps.render_records([_record(sheet_number="   ")], "chase wall")
        self.assertIn("AR - 6.9.26 (Gas change).pdf p2", out)
        self.assertNotIn("?", out)


class WhatTheModelIsShown(unittest.TestCase):
    """_render_records_for_model — the evidence the agent composes from. It
    reads '?' the same way a person does, and a model that is shown one will
    write one."""

    def test_the_file_and_page_stand_in_for_a_missing_sheet_number(self):
        out = server._render_records_for_model([_record()], "chase wall")
        self.assertIn("AR - 6.9.26 (Gas change).pdf p2", out)
        self.assertNotIn("?", out)

    def test_a_record_that_cannot_say_where_it_is_is_not_offered(self):
        # It used to be offered as `- [pNone | note | text_layer] …`, which is
        # the '?' again one layer up. Asserted on the BULLET rather than on the
        # word None: the rule is that the record does not appear at all.
        out = server._render_records_for_model(
            [_record(file_name=None, page_number=None)], "chase wall")
        self.assertNotIn("- [", out)
        self.assertNotIn("CHASE WALL AT SHAFT", out)
        self.assertNotIn("?", out)

    def test_the_sheet_number_is_still_preferred(self):
        out = server._render_records_for_model(
            [_record(sheet_number="A-105.01")], "chase wall")
        # The line is `- <quote> [<sheet>]` now; the record type and tier
        # were machinery for a log reader, not for the model composing a
        # sentence, and a live GC got paragraphs while they were in there.
        self.assertIn("[A-105.01]", out)


class NoRenderPrintsALiteralQuestionMark(unittest.TestCase):

    def test_neither_render_carries_one(self):
        for fn in (ps.render_records, server._render_records_for_model):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                self.assertFalse(re.search(r"""or ['"]\?['"]""", src),
                                 "a render is printing '?' for a record with "
                                 "no sheet")


class TheRecordCarriesWhatTheCitationNeeds(unittest.TestCase):

    def test_the_writer_stores_the_file_name(self):
        src = inspect.getsource(server._write_page_chunks)
        self.assertIn('"file_name": file_name', src)

    def test_every_caller_passes_it(self):
        src = inspect.getsource(server._index_single_page)
        self.assertEqual(src.count("_write_page_chunks("),
                         src.count("file_name=file_name"))

    def test_the_record_writer_puts_it_on_every_record(self):
        src = inspect.getsource(server._write_page_records)
        self.assertIn('"file_name": file_name', src)

    def test_the_query_drops_no_field_it_does_not_name(self):
        # A field the writer stores and the query drops is the same bug one
        # step later, so the projection excludes rather than includes.
        src = inspect.getsource(server.search_plans)
        self.assertIn('proj = {"_id": 0, "embedding": 0}', src)


if __name__ == "__main__":
    unittest.main()
