"""The vector-page text layer, rebuilt and structured without a model.

Every fixture is a synthetic span dict shaped like PyMuPDF's get_text("dict").
The shapes are the ones measured on a real set — a stacked fraction as a
smaller span of joined digits, a title strip that glues a drawing-list index
to the sheet id, a floor plan whose only "PTAC" is inside a calculation — but
no real project's text is committed here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import plan_text as pt  # noqa: E402


def span(text, size=10.6):
    return {"text": text, "size": size}


def block(lines, bbox=(100, 100, 400, 200)):
    return {"type": 0, "bbox": bbox,
            "lines": [{"spans": [span(t) if isinstance(t, str) else t for t in
                                 (l if isinstance(l, list) else [l])]} for l in lines]}


class StackedFractionsAreRebuilt(unittest.TestCase):

    def test_the_digits_of_a_stacked_fraction(self):
        cases = {"12": "1/2", "78": "7/8", "58": "5/8", "34": "3/4", "316": "3/16",
                 "1516": "15/16", "116": "1/16", "764": "7/64"}
        for digits, want in cases.items():
            with self.subTest(digits=digits):
                self.assertEqual(pt.split_stacked_fraction(digits), want)

    def test_digits_that_are_no_drawing_fraction_are_left_alone(self):
        for digits in ("24", "44", "10", "7", "12345", "9"):
            with self.subTest(digits=digits):
                self.assertIsNone(pt.split_stacked_fraction(digits))

    def test_a_small_span_between_a_whole_number_and_the_inch_mark(self):
        """The measured shape: '3 ' 10.6pt, '12' 7.4pt, '" METAL STUD' 10.6pt."""
        text, fixed = pt.rebuild_line([span("3 "), span("12", 7.4), span('" METAL STUD')])
        self.assertEqual(text, '3 1/2" METAL STUD')
        self.assertEqual(fixed, 1)

    def test_a_fraction_with_no_whole_number(self):
        text, fixed = pt.rebuild_line([span("78", 7.1), span('" STUCCO')])
        self.assertEqual(text, '7/8" STUCCO')

    def test_same_size_digits_are_a_number_not_a_fraction(self):
        text, fixed = pt.rebuild_line([span("12"), span('" CONCRETE')])
        self.assertEqual((text, fixed), ('12" CONCRETE', 0))

    def test_unicode_fraction_glyphs(self):
        self.assertEqual(pt.normalize_glyphs("3½″ STUD"), '3 1/2" STUD')
        self.assertEqual(pt.normalize_glyphs("5⁄8″"), '5/8"')

    def test_a_lone_fraction_piece_is_kept_as_unverified_not_dropped(self):
        d = {"blocks": [
            block(["WALL SECTION NOTES FOR THE EXTERIOR STUD WALL"]),
            block([[span("7", 7.1)]], bbox=(10, 10, 20, 20)),
            block(["R-11.5 EPS INSULATION WITH STUCCO FINISH"]),
        ]}
        L = pt.layout_from_dict(d, width=2592, height=1728, page_number=24)
        self.assertEqual(L["fractions_unverified"], ["7"])
        self.assertIn("7", L["text"].split("\n"))


class TheSheetNumberComesFromThePrintedIds(unittest.TestCase):

    def test_a_drawing_list_index_glued_to_the_id(self):
        self.assertEqual(pt.sheet_ids("2S-001.00GENERAL NOTES 3S-002.00"), ["S-001.00", "S-002.00"])

    def test_an_id_glued_to_its_page_count(self):
        self.assertEqual(pt.sheet_ids("A-500.0024 OF 31"), ["A-500.00"])

    def test_a_ul_system_is_not_a_sheet(self):
        self.assertEqual(pt.sheet_ids("UL System No. C-AJ-2086"), [])

    def test_the_model_reading_2_is_corrected(self):
        """S-001.00, measured: the model returned "2"."""
        sn, flag = pt.validate_sheet_number("2", ["S-001.00", "S-400", "NY-112"], ["S-001.00"])
        self.assertEqual((sn, flag), ("S-001.00", "sheet_number_corrected"))

    def test_a_correct_reading_is_kept(self):
        self.assertEqual(pt.validate_sheet_number("a-500.00", ["A-500.00"], []), ("A-500.00", None))

    def test_no_model_reading_uses_the_title_block(self):
        self.assertEqual(pt.validate_sheet_number(None, ["P-100.00"], []),
                         ("P-100.00", "sheet_number_from_text"))

    def test_the_title_strip_is_the_one_with_the_decimal_id(self):
        """The notes strip says SHEET and DRAWING more often and cites S-400."""
        d = {"blocks": [
            block(["SEE SHEET S-400 AND DRAWING S-401. THIS DRAWING AND SHEET GOVERN."],
                  bbox=(2200, 100, 2590, 900)),
            block(["S-001.00", "GENERAL NOTES"], bbox=(100, 1600, 900, 1700)),
        ]}
        L = pt.layout_from_dict(d, width=2592, height=1728, page_number=2)
        self.assertEqual(pt.sheet_ids(pt.title_region(L)), ["S-001.00"])


class NotesComeStraightFromTheText(unittest.TestCase):

    def test_numbered_notes_under_their_heading_with_no_length_cap(self):
        long_text = "ALL WORK SHALL CONFORM. " * 100
        blocks = [
            {"bbox": [0, 0, 1, 1], "lines": ["GENERAL CONDITIONS:"], "text": "GENERAL CONDITIONS:"},
            {"bbox": [0, 0, 1, 1], "lines": ["1.", long_text], "text": "1.\n" + long_text},
            {"bbox": [0, 0, 1, 1], "lines": ["8.5.", "STRUCTURAL LUMBER.", "8.6.",
                                              "SUPPORT OF EXCAVATION AND PILES."],
             "text": "8.5.\nSTRUCTURAL LUMBER.\n8.6.\nSUPPORT OF EXCAVATION AND PILES."},
        ]
        notes = pt.notes_from_blocks(blocks)
        self.assertEqual([n["number"] for n in notes], ["1", "8.5", "8.6"])
        self.assertEqual(notes[0]["heading"], "GENERAL CONDITIONS")
        self.assertEqual(len(notes[0]["text"]), len(long_text.strip()))
        self.assertEqual(notes[2]["text"], "SUPPORT OF EXCAVATION AND PILES.")

    def test_a_short_block_on_its_own_is_still_in_the_text(self):
        """'HELICAL PILES (BB # 2014-020)' is a 40-character block on S-001.00."""
        d = {"blocks": [block(["HELICAL PILES (BB # 2014-020)", "BC 1705.9"])]}
        L = pt.layout_from_dict(d, width=2592, height=1728, page_number=2)
        f = pt.fields_from_layout(L)
        self.assertIn("HELICAL PILES (BB # 2014-020)",
                      "\n".join(b["text"] for b in f["text_blocks"]))


class StatedQuantitiesAreReadNotCounted(unittest.TestCase):

    def test_a_printed_quantity(self):
        self.assertEqual(pt.stated_quantities("(4) ROOF DRAINS\n"),
                         [{"name": "ROOF DRAINS", "count_if_stated": 4,
                           "location_hint": "text layer", "count_verified": True}])

    def test_a_number_ending_one_line_does_not_count_the_next(self):
        self.assertEqual(pt.stated_quantities("720.1 (3)\nR-11.5 EPS"), [])


class TagCountsAreLabelsOnly(unittest.TestCase):

    def _layout(self):
        d = {"blocks": [
            block(["PTAC"]), block(["PTAC"]), block(["W1"]),
            block(["TOTAL WALL AREA OF THIS STORY IS 700 SF", "PTAC UNIT 3'-8\" X 1'-6\" = 5.5'"]),
            block(["R-19"]),
        ]}
        return pt.layout_from_dict(d, width=2592, height=1728, page_number=11)

    def test_a_tag_inside_a_calculation_is_not_counted(self):
        tags = {t["tag"]: t["count"] for t in pt.count_tags(self._layout(), pt.SEED_TAGS | {"W1"})}
        self.assertEqual(tags, {"PTAC": 2, "W1": 1})

    def test_the_source_says_what_it_is(self):
        tags = pt.count_tags(self._layout(), pt.SEED_TAGS)
        self.assertEqual({t["source"] for t in tags}, {"text-layer tag count"})

    def test_the_vocabulary_takes_marks_a_schedule_defines_and_not_r_values(self):
        d = {"blocks": [block(["W1 EXTERIOR STUD WALL WITH STUCCO", "R-19 BATT INSULATION IN STUDS"])]}
        L = pt.layout_from_dict(d, width=2592, height=1728, page_number=24)
        vocab = pt.tag_vocabulary([L])
        self.assertIn("W1", vocab)
        self.assertNotIn("R-19", vocab)


class TablesThatAreNotSchedulesAreDropped(unittest.TestCase):

    def test_the_title_block_frame_and_an_empty_grid(self):
        tables = [
            {"bbox": [16, 18, 2576, 1711], "rows": [["NOTES", "A"], ["B", "C"]]},
            {"bbox": [100, 100, 300, 300], "rows": [["", "", ""], ["", "", "x"], ["", "", ""]]},
            {"bbox": [100, 100, 600, 400], "rows": [["PILE SCHEDULE", "", ""],
                                                   ["MARK", "TYPE", "QTY"], ["P1", "HELICAL", "30"]]},
        ]
        s = pt.schedules_from_tables(tables, 2592, 1728)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["name"], "PILE SCHEDULE")
        self.assertEqual(s[0]["columns"], ["MARK", "TYPE", "QTY"])
        self.assertEqual(s[0]["rows"], [["P1", "HELICAL", "30"]])


class ThePdfLibraryIsImportedInOnePlace(unittest.TestCase):

    def test_only_page_layouts_imports_it(self):
        import inspect
        src = inspect.getsource(pt)
        self.assertEqual(src.count("import fitz"), 1)
        self.assertIn("import fitz", inspect.getsource(pt.page_layouts))


if __name__ == "__main__":
    unittest.main()
