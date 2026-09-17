"""One record per thing a sheet says, with how we came to know it.

The chunk collection stores STRINGS, and every fix for "the letters did not
line up" widened the match — typo tolerance, AC->PTAC synonyms, head-noun
fallback, plural stems, chunk-type ranking. None of it generalises.

A record carries the printed words, where they are on the sheet, and the path
that produced them. The four rules this file holds:

  1. `quote` is what the sheet prints; `quote_span` locates it in the page text
  2. `label` is what a model supplied and is NEVER the quote
  3. `tier` is the extraction path, never a model's opinion of itself
  4. `bbox` says where on the sheet
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
from lib import plan_records as pr  # noqa: E402

PAGE = {"sheet_number": "M-200.00", "page_number": 9, "file_name": "MH - 7.2.26.pdf",
        "filing_id": "B01141294-S6", "issued_date": "7/2/2026",
        "document_type": "subsequent"}
RAW = "AD = AREA DRAIN\nROOMS PTAC UNITS SCHEDULE\n3 1/2\" METAL STUD 16\" O.C. 20 GAUGE MIN."


def records(**over):
    fields = dict(pe.EMPTY_FIELDS, sheet_number="M-200.00", **over)
    return pr.build_records(fields, page=PAGE, raw_text=RAW)


class TheTierIsTheExtractionPath(unittest.TestCase):

    def test_a_schedule_read_from_a_grid_outranks_one_read_from_the_image(self):
        grid = records(schedules=[{"name": "PILE SCHEDULE", "columns": ["MARK", "QTY"],
                                   "rows": [["P1", "18"]], "bbox": [1, 2, 3, 4]}])[0]
        seen = records(schedules=[{"name": "PTAC UNITS SCHEDULE", "columns": ["UNIT NO.", "QTY"],
                                   "rows": [["PTAC-1", "21"]], "source": "vision"}])[0]
        self.assertEqual(grid["tier"], pe.TIER_SCHEDULE_CELL)
        self.assertEqual(seen["tier"], pe.TIER_VISION)
        self.assertLess(pr.tier_rank(grid["tier"]), pr.tier_rank(seen["tier"]))
        self.assertEqual(pr.better_tier(seen["tier"], grid["tier"]), pe.TIER_SCHEDULE_CELL)

    def test_an_element_is_tiered_by_what_its_count_rests_on(self):
        want = {"schedule_qty": pe.TIER_SCHEDULE_CELL,
                "tag_occurrences": pe.TIER_TAG_LEGEND,
                "not_stated": pe.TIER_TEXT_LAYER,
                "vision_read": pe.TIER_VISION}
        for basis, tier in want.items():
            with self.subTest(basis=basis):
                r = records(elements=[{"name": "ROOF DRAIN", "count_basis": basis}])[0]
                self.assertEqual(r["tier"], tier)

    def test_notes_read_off_the_image_are_not_text_layer(self):
        r = records(notes=[{"number": "1", "text": "PROVIDE WALL SLEEVE"}],
                    notes_source="vision")[0]
        self.assertEqual(r["tier"], pe.TIER_VISION)
        self.assertEqual(r["source"], "vision")
        self.assertFalse(r["verified"])

    def test_no_tier_is_a_number_and_none_is_a_confidence(self):
        for t in pr.TIER_ORDER:
            with self.subTest(tier=t):
                self.assertFalse(any(c.isdigit() for c in t))
        import inspect
        src = inspect.getsource(pr)
        for banned in ("confidence", "probability", "score"):
            with self.subTest(banned=banned):
                self.assertNotIn(f"{banned}=", src)

    def test_an_unknown_tier_sorts_last_and_is_not_a_value(self):
        self.assertEqual(pr.tier_rank(None), len(pr.TIER_ORDER))
        self.assertEqual(pr.tier_rank("made up"), len(pr.TIER_ORDER))


class ALabelIsNeverAQuote(unittest.TestCase):

    def test_the_words_the_model_supplied_stay_out_of_the_quote(self):
        r = records(legend=[{"symbol": "PTAC-1", "meaning": "",
                             "label": "PACKAGE TERMINAL AIR CONDITIONER",
                             "tier": pe.TIER_VISION}])[0]
        self.assertEqual(r["quote"], "PTAC-1")
        self.assertEqual(r["label"], "PACKAGE TERMINAL AIR CONDITIONER")
        self.assertNotIn("PACKAGE", r["quote"])

    def test_a_meaning_the_page_prints_is_the_quote_and_carries_no_label(self):
        r = records(legend=[{"symbol": "AD", "meaning": "AREA DRAIN",
                             "tier": pe.TIER_TAG_LEGEND}])[0]
        self.assertEqual(r["quote"], "AD = AREA DRAIN")
        self.assertIsNone(r["label"])

    def test_the_label_is_still_reachable_for_a_search(self):
        r = records(legend=[{"symbol": "PTAC-1", "meaning": "",
                             "label": "PACKAGE TERMINAL AIR CONDITIONER",
                             "tier": pe.TIER_VISION}])[0]
        self.assertEqual(r["label"], "PACKAGE TERMINAL AIR CONDITIONER")
        self.assertEqual(r["tier"], pe.TIER_VISION)


class WhereTheWordsAre(unittest.TestCase):

    def test_a_quote_the_page_prints_is_located_in_it(self):
        r = records(legend=[{"symbol": "AD", "meaning": "AREA DRAIN",
                             "tier": pe.TIER_TAG_LEGEND}])[0]
        self.assertEqual(RAW[r["quote_span"][0]:r["quote_span"][1]], "AD = AREA DRAIN")

    def test_a_vision_record_gets_no_span_because_the_page_cannot_confirm_it(self):
        r = records(schedules=[{"name": "PTAC UNITS SCHEDULE", "columns": ["QTY"],
                                "rows": [["21"]], "source": "vision"}])[0]
        self.assertIsNone(r["quote_span"])

    def test_bbox_travels_where_the_extractor_knows_it(self):
        r = records(schedules=[{"name": "PILE SCHEDULE", "columns": ["MARK"],
                                "rows": [["P1"]], "bbox": [10, 20, 300, 120]}])[0]
        self.assertEqual(r["bbox"], [10.0, 20.0, 300.0, 120.0])

    def test_an_empty_box_is_no_box_rather_than_a_corner(self):
        r = records(schedules=[{"name": "S", "columns": ["A"], "rows": [["1"]],
                                "bbox": [0, 0, 0, 0]}])[0]
        self.assertIsNone(r["bbox"])


class WhatASheetKnowsAboutItself(unittest.TestCase):

    def test_every_record_repeats_the_page_so_a_search_needs_no_join(self):
        for r in records(tag_counts=[{"tag": "AD", "count": 2}]):
            self.assertEqual(r["sheet_number"], "M-200.00")
            self.assertEqual(r["filing_id"], "B01141294-S6")
            self.assertEqual(r["document_type"], "subsequent")

    def test_approval_status_is_not_stored_anywhere(self):
        # Statements only. The module docstring names the field to say why it
        # is absent, which is the opposite of storing it.
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(pr))
        doc_nodes = set()
        for n in ast.walk(tree):
            body = getattr(n, "body", None)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and body:
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    doc_nodes.add(id(first.value))
        for lit in [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in doc_nodes]:
            self.assertNotIn("approval_status", lit,
                             "approval status changes without the drawing changing")
        self.assertNotIn("approval_status", [k for r in records() for k in r])

    def test_the_authority_read_off_a_title_block(self):
        got = pr.page_authority(
            "DOB JOB # B01141294-P5 DATE ISSUE OR REVISION 8/18/2026 SEAL AND SIGNATURE")
        self.assertEqual(got["filing_id"], "B01141294-P5")
        self.assertEqual(got["issued_date"], "8/18/2026")
        self.assertEqual(got["document_type"], "post_approval_amendment")

    def test_a_sheet_with_no_filing_says_so_rather_than_guessing(self):
        got = pr.page_authority("SEWER INFORMATION CERTIFIED REVIEW UNIT")
        self.assertIsNone(got["filing_id"])
        self.assertIsNone(got["document_type"])


class WhatAScheduleColumnIs(unittest.TestCase):

    def test_roles_come_from_the_printed_header(self):
        want = {"UNIT NO.": "identifier", "QTY": "quantity", "MAKE": "make",
                "MODEL": "model", "REMARKS": "remarks",
                "NET COOLING CAPACITY (BTUH)": None}
        for header, role in want.items():
            with self.subTest(header=header):
                self.assertEqual(pr.column_role(header), role)

    def test_a_column_of_numbers_is_not_a_quantity_column(self):
        self.assertIsNone(pr.column_role("ELEC. VOLTS"))
        self.assertIsNone(pr.column_role("NET WEIGHT LBS"))


class TheWriterIsOneCallSite(unittest.TestCase):

    def test_records_and_chunks_cannot_disagree_about_which_pages_exist(self):
        import inspect
        import server
        src = inspect.getsource(server._write_page_chunks)
        self.assertIn("_write_page_records(", src)

    def test_the_new_writer_never_fails_the_page(self):
        import inspect
        import server
        src = inspect.getsource(server._write_page_chunks)
        i = src.index("_write_page_records(")
        self.assertIn("except Exception", src[i:i + 900])


if __name__ == "__main__":
    unittest.main()
