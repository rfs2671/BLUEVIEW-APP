"""scripts/plan_sheet_text.py: one sheet's stored records and its PDF text
layer, exactly as they are, READ-ONLY.

A fake database shaped like production's rows (a project, its file, two
indexed pages numbered A-302.00 -- one current, one from a deleted file --
and their plan_records) and a fake R2 that hands back a real PDF drawn with
reportlab, read by the indexer's own lib/plan_text. Asserted: the records
holding the term print with type, bbox and the WHOLE quote; the PDF's block
around the term prints word for word with its detail bubble; a page off a
deleted file says so; nothing is written; R2 is asked for the file's own key.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

import plan_sheet_text as st  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

PID = "p588"
QUOTE = ("ROOF ASSEMBLY:\nEPDM MEMBRANE ON 1/2\" COVER BOARD\n"
         "TAPERED POLYISO INSULATION R-30 MIN.")
PDF_LINE = "2 1/2\" CLOSED CELL SPRAY FOAM AT UNDERSIDE OF DECK"


def _pdf() -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(1296, 864))
    c.setFont("Helvetica", 10)
    c.drawString(60, 740, "4")                         # the detail bubble, its own block
    c.drawString(120, 700, "ROOF ASSEMBLY DETAIL")
    c.drawString(120, 686, PDF_LINE)
    c.drawString(120, 640, "SEE STRUCTURAL FOR DECK")  # nearby: printed as around it
    c.drawString(1000, 100, "UNRELATED TITLE BLOCK TEXT")
    c.showPage()
    c.save()
    return buf.getvalue()


def _db():
    page = {"project_id": PID, "sheet_number": "A-302.00", "sheet_title": "WALL SECTIONS",
            "page_number": 1, "indexed_at": "2026-10-26T18:30:00Z"}
    return FakeDb(
        projects=[{"_id": PID, "name": "588 Thomas S Boyland Street, Brooklyn"},
                  {"_id": "p9", "name": "120 Atlantic Ave"}],
        project_files=[{"_id": "f1", "project_id": PID, "name": "AR - 3.28.25.pdf", "r2_key": "k/ar.pdf"},
                       {"_id": "f0", "project_id": PID, "name": "old.pdf", "r2_key": "k/old.pdf",
                        "is_deleted": True}],
        document_page_index=[
            dict(page, _id="pg1", file_id="f1", file_name="AR - 3.28.25.pdf",
                 raw_text="GENERAL NOTES\n4\nROOF ASSEMBLY DETAIL\n" + PDF_LINE + "\nSCALE 1 1/2\"=1'-0\""),
            dict(page, _id="pg0", file_id="f0", file_name="old.pdf", raw_text="")],
        plan_records=[
            {"_id": "r1", "project_id": PID, "page_id": "pg1", "record_type": "note", "ordinal": 3,
             "tier": "text_layer", "source": "text_layer", "bbox": [100, 150, 400, 190],
             "quote": QUOTE, "label": None},
            {"_id": "r2", "project_id": PID, "page_id": "pg1", "record_type": "dimension",
             "ordinal": 1, "tier": "text_layer", "source": "text_layer", "bbox": None,
             "quote": "12'-0\""}],
    )


class TheSheetText(unittest.TestCase):

    def run_script(self, **kw):
        db = _db()
        asked, lines = [], []
        pdf = _pdf()

        def fetch(key):
            asked.append(key)
            return (pdf, None) if key == "k/ar.pdf" else (None, "NoSuchKey")
        a = argparse.Namespace(project_name="boyland", project_id="", sheet="a-302.00",
                               contains="ROOF ASSEMBLY", detail="4", near=st.NEAR_PT,
                               all_blocks=False)
        for k, v in kw.items():
            setattr(a, k, v)
        code = asyncio.run(st.run(db, a, out=lines.append, fetch=fetch))
        return code, "\n".join(lines), db, asked

    def test_records_print_whole_with_type_and_bbox(self):
        code, text, _, _ = self.run_script()
        self.assertEqual(code, 0)
        self.assertIn("STORED RECORDS (plan_records): 1 of 2 on this page hold the term", text)
        self.assertIn("- note #3 · tier text_layer · source text_layer · bbox [100.0, 150.0, 400.0, 190.0]",
                      text)
        for line in QUOTE.splitlines():
            self.assertIn("      | " + line, text)

    def test_the_pdf_block_prints_word_for_word_with_its_bubble(self):
        code, text, _, asked = self.run_script()
        self.assertEqual(asked, ["k/ar.pdf", "k/old.pdf"])   # each file once, by its own key
        pdf = text.split("PDF TEXT LAYER")[1]
        self.assertEqual(pdf.count("[MATCH] block"), 2)       # the title block and the bubble
        self.assertIn("      | ROOF ASSEMBLY DETAIL\n      | " + PDF_LINE + "\n", pdf)
        self.assertIn("      | 4\n", pdf)
        self.assertIn("[WITHIN 72pt] block", pdf)
        self.assertIn("      | SEE STRUCTURAL FOR DECK", pdf)
        self.assertNotIn("| UNRELATED TITLE BLOCK TEXT", text)

    def test_the_stored_page_text_around_the_term(self):
        _, text, _, _ = self.run_script()
        self.assertIn("    | ROOF ASSEMBLY DETAIL", text)
        self.assertIn("    | " + PDF_LINE, text)

    def test_current_and_not_current_pages_are_named(self):
        _, text, _, _ = self.run_script()
        self.assertIn("· CURRENT", text)
        self.assertIn("NOT CURRENT (file deleted or not searched)", text)
        self.assertIn("could not download k/old.pdf: NoSuchKey", text)

    def test_a_sheet_with_other_punctuation_is_found_and_said(self):
        _, text, _, _ = self.run_script(sheet="A302.00")
        self.assertIn("No page is numbered exactly A302.00; the same letters and digits: A-302.00", text)

    def test_an_ambiguous_project_name_lists_the_choices(self):
        code, text, _, _ = self.run_script(project_name="a")
        self.assertEqual(code, 2)
        self.assertIn("2 projects match -- pass --project-id:", text)

    def test_nothing_is_written(self):
        _, _, db, _ = self.run_script()
        for name in ("projects", "project_files", "document_page_index", "plan_records"):
            self.assertEqual(len(db[name].rows), {"projects": 2, "project_files": 2,
                                                  "document_page_index": 2, "plan_records": 2}[name])
        self.assertEqual(db.plan_records.rows[0]["quote"], QUOTE)


if __name__ == "__main__":
    unittest.main()
