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

A record says where it is: its sheet number, or the file and page every chunk
carries. A record that can say neither is not quoted.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_extract as pe  # noqa: E402


class WhereARecordSaysItIs(unittest.TestCase):

    def test_the_sheet_number_when_there_is_one(self):
        self.assertEqual(pe.cite({"sheet": "A-105.01", "file": "AR.pdf", "page": 7}),
                         "A-105.01")

    def test_the_file_and_page_when_there_is_not(self):
        self.assertEqual(pe.cite({"sheet": None, "file": "AR - 6.9.26 (Gas change).pdf",
                                  "page": 2}),
                         "AR - 6.9.26 (Gas change).pdf p2")

    def test_the_page_alone_when_the_file_is_unknown(self):
        self.assertEqual(pe.cite({"sheet": "", "file": None, "page": 2}), "page 2")

    def test_nothing_at_all_is_not_citable(self):
        self.assertIsNone(pe.cite({"sheet": None, "file": None, "page": None}))
        self.assertEqual(pe.citable([{"sheet": None, "page": None},
                                     {"sheet": "S-001.00"}]),
                         [{"sheet": "S-001.00"}])

    def test_whitespace_is_not_a_sheet_number(self):
        self.assertEqual(pe.cite({"sheet": "   ", "page": 4}), "page 4")


class NoFormatterPrintsAQuestionMark(unittest.TestCase):

    UNNUMBERED = [{
        "project_id": "p1", "page_id": "pg1", "page_number": 2,
        "sheet_number": None, "sheet_title": "Roof Plan",
        "file_name": "AR - 6.9.26 (Gas change).pdf",
        "chunk_type": "text", "ordinal": 0,
        "text": "CONC. WALL\nCHASE WALL AT SHAFT", "payload": None,
    }]

    def test_existence(self):
        a = pe.answer_question(self.UNNUMBERED, "are there chase walls")
        self.assertIsNotNone(a)
        self.assertNotIn("?", a["text"])
        self.assertIn("AR - 6.9.26 (Gas change).pdf p2", a["text"])

    def test_an_open_question(self):
        a = pe.answer_question(self.UNNUMBERED, "Whats the chase wall")
        self.assertIsNotNone(a)
        self.assertNotIn("?", a["text"])
        self.assertIn("p2", a["text"])

    def test_not_stated_names_the_file_rather_than_dropping_it(self):
        a = pe.answer_question(self.UNNUMBERED, "chase wall thickness")
        self.assertIsNotNone(a)
        self.assertNotIn("?", a["text"])
        self.assertIn("AR - 6.9.26 (Gas change).pdf p2", a["text"])

    def test_a_count_off_an_unnumbered_schedule(self):
        chunks = [{
            "page_number": 9, "sheet_number": None, "file_name": "MH - 7.2.26.pdf",
            "chunk_type": "schedule", "ordinal": 0,
            "text": "PTAC UNITS SCHEDULE\nUNIT NO. | QTY",
            "payload": {"name": "PTAC UNITS SCHEDULE", "columns": ["UNIT NO.", "QTY"],
                        "rows": [["PTAC-1", "21"]]},
        }]
        a = pe.answer_question(chunks, "how many ptac units")
        self.assertIsNotNone(a)
        self.assertNotIn("?", a["text"])
        self.assertIn("MH - 7.2.26.pdf p9", a["text"])

    def test_no_formatter_still_carries_the_literal(self):
        import inspect
        src = inspect.getsource(pe)
        self.assertNotIn("""or '?'""", src,
                         "a formatter is printing '?' for a record with no sheet")


class TheChunkCarriesWhatTheCitationNeeds(unittest.TestCase):

    def test_the_writer_stores_the_file_name(self):
        import inspect
        import server
        src = inspect.getsource(server._write_page_chunks)
        self.assertIn('"file_name": file_name', src)

    def test_every_caller_passes_it(self):
        import inspect
        import server
        src = inspect.getsource(server._index_single_page)
        self.assertEqual(src.count("_write_page_chunks("), src.count("file_name=file_name"))


if __name__ == "__main__":
    unittest.main()
