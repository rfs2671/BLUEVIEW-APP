"""The vector-page text layer, rebuilt and structured without a model.

Every fixture is a synthetic span dict (the shape page_dict_from_chars builds
from pdfplumber characters) or a synthetic character list.
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
        notes, used = pt.notes_from_blocks(blocks)
        self.assertEqual(used, {0, 1, 2})
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


def B(text, bbox):
    lines = text.split("\n")
    return {"bbox": list(bbox), "lines": lines, "text": text}


class ANumberThatEndsTheBlockBeforeItsText(unittest.TestCase):
    """S-001.00 as pdfplumber characters give it: '8.2.' closes the block that
    holds 8.1's text, and 8.2's text is the next block down."""

    def test_the_number_starts_the_note_that_follows(self):
        blocks = [
            B("8. SHOP DRAWINGS FOR THE FOLLOWING:\n8.1.", (1140, 625, 1637, 668)),
            B("STRUCTURAL STEEL.\n8.2.", (1153, 659, 1283, 680)),
            B("STRUCTURAL CONCRETE.", (1153, 670, 1306, 691)),
        ]
        notes, used = pt.notes_from_blocks(blocks)
        self.assertEqual([(n["number"], n["text"]) for n in notes],
                         [("8", "SHOP DRAWINGS FOR THE FOLLOWING:"),
                          ("8.1", "STRUCTURAL STEEL."), ("8.2", "STRUCTURAL CONCRETE.")])

    def test_a_far_block_does_not_continue_a_note(self):
        blocks = [B("1. ALL WORK PER CODE.", (100, 100, 400, 110)),
                  B("KITCHENETTE", (1500, 900, 1560, 910))]
        notes, used = pt.notes_from_blocks(blocks)
        self.assertEqual(notes[0]["text"], "ALL WORK PER CODE.")
        self.assertEqual(used, {0})


class UnnumberedNotesUnderANotesHeader(unittest.TestCase):

    def test_short_all_caps_blocks_near_the_header_are_notes(self):
        blocks = [
            B("PLUMBING NOTES:", (2000, 100, 2100, 110)),
            B("EXACT LOCATION OF EACH FIXTURE SHALL BE FIELD VERIFIED.", (2000, 125, 2300, 135)),
            B("COLD & HOT WATER SHALL BE COPPER TYPE L.", (2000, 150, 2250, 160)),
            B("KITCHENETTE", (900, 700, 960, 710)),
            B("Drawn by hand", (2000, 175, 2100, 185)),
        ]
        notes, used = pt.notes_from_blocks(blocks)
        self.assertEqual([n["text"] for n in notes],
                         ["EXACT LOCATION OF EACH FIXTURE SHALL BE FIELD VERIFIED.",
                          "COLD & HOT WATER SHALL BE COPPER TYPE L."])
        self.assertEqual({n["number"] for n in notes}, {None})
        self.assertEqual(used, {0, 1, 2})

    def test_without_a_header_all_caps_text_is_not_a_note(self):
        notes, _ = pt.notes_from_blocks([B("ADJACENT 2 STORY BRICK", (100, 100, 300, 110))])
        self.assertEqual(notes, [])


class TheLegendIsFoundByWhereItIs(unittest.TestCase):
    """A-100.00: 'LEGEND' is its own object and its entries are written
    interleaved with unrelated labels."""

    def test_entries_beside_and_below_the_word(self):
        blocks = [
            B("TOTAL OCCUPANTS PER STORY", (847, 1359, 979, 1370)),
            B("6\" STUD, R19 BATT-R11.5 RIGID INSU.,\nSTUCCO FINISH", (1977, 1308, 2100, 1324)),
            B("LEGEND", (1752, 1249, 1778, 1257)),
            B("A", (1755, 1360, 1759, 1368)),
            B("FLOOR/AREA/ROOF DRAIN", (1773, 1275, 1859, 1283)),
            B("SMOKE/CARBON MONOXIDE\nDETECTOR", (1773, 1313, 1867, 1329)),
            B("W1", (1752, 1400, 1763, 1408)),
            B("PLOT PLAN NOTES ABOVE", (1760, 1000, 1900, 1010)),
        ]
        entries, used = pt.legend_from_blocks(blocks)
        meanings = [e["meaning"] for e in entries]
        self.assertIn("FLOOR/AREA/ROOF DRAIN", meanings)
        self.assertIn("SMOKE/CARBON MONOXIDE DETECTOR", meanings)
        self.assertIn('6" STUD, R19 BATT-R11.5 RIGID INSU., STUCCO FINISH', meanings)
        self.assertNotIn("TOTAL OCCUPANTS PER STORY", meanings)
        self.assertNotIn("PLOT PLAN NOTES ABOVE", meanings, "above the word is not the legend")
        self.assertNotIn(3, used, "a bare mark is not an entry")
        self.assertNotIn(6, used)

    def test_legend_entries_are_not_counted_as_tags_on_the_plan(self):
        d = {"blocks": [block(["LEGEND"], bbox=(100, 100, 130, 110)),
                        block(["PTAC UNIT"], bbox=(100, 130, 160, 140)),
                        block(["PTAC"], bbox=(900, 900, 930, 910))]}
        L = pt.layout_from_dict(d, width=2592, height=1728, page_number=11)
        f = pt.fields_from_layout(L)
        self.assertEqual({t["tag"]: t["count"] for t in f["tag_counts"]}, {"PTAC": 1})
        self.assertEqual([e["meaning"] for e in f["legend"]], ["PTAC UNIT"])


class TheDrawingListIndex(unittest.TestCase):

    def test_the_number_written_before_the_id(self):
        blocks = []
        for n, sid in enumerate(["T-001.00", "S-001.00", "S-002.00", "S-003.00", "S-101.00"], start=1):
            blocks.append(B(str(n), (134, 767 + 18 * n, 139, 776 + 18 * n)))
            blocks.append(B(sid, (276, 767 + 18 * n, 315, 776 + 18 * n)))
        blocks.append(B("7S-301.00", (276, 900, 330, 909)))
        L = {"blocks": blocks, "text": "\n".join(b["text"] for b in blocks)}
        idx = pt.drawing_list_index([L])
        self.assertEqual(idx["S-001.00"], 2)
        self.assertEqual(idx["S-301.00"], 7)

    def test_a_page_that_is_not_a_drawing_list_gives_nothing(self):
        blocks = [B("2", (0, 0, 5, 5)), B("S-001.00", (10, 0, 50, 5))]
        L = {"blocks": blocks, "text": "2\nS-001.00"}
        self.assertEqual(pt.drawing_list_index([L]), {})


class LinesFollowTheDrawingOrder(unittest.TestCase):
    """pdfminer's geometric grouping put '3 1' of '3 1/2"' in another box."""

    def _ch(self, text, x0, size=10.6, top=100.0):
        w = size * 0.5
        return {"text": text, "size": size, "x0": x0, "x1": x0 + w, "top": top,
                "bottom": top + size, "matrix": (1, 0, 0, 1, x0, 0)}

    def test_a_stacked_fraction_stays_on_its_line_and_is_rebuilt(self):
        chars = [self._ch("3", 100), self._ch(" ", 105.3),
                 self._ch("1", 110.6, 7.4, top=96), self._ch("2", 112.0, 7.4, top=104),
                 self._ch('"', 116.0), self._ch(" ", 121.3)]
        x = 126.6
        for c in "METAL STUD":
            chars.append(self._ch(c, x))
            x += 5.3
        page = pt.page_dict_from_chars(chars)
        self.assertEqual(len(page["blocks"]), 1)
        L = pt.layout_from_dict(page, width=2592, height=1728, page_number=24)
        self.assertEqual(L["text"], '3 1/2" METAL STUD')
        self.assertEqual(L["fractions_rebuilt"], 1)

    def test_a_far_character_starts_a_new_block(self):
        chars = [self._ch("A", 100), self._ch("B", 105.3), self._ch("C", 900, top=700)]
        page = pt.page_dict_from_chars(chars)
        self.assertEqual(len(page["blocks"]), 2)


class ACombinedSetIsRecognised(unittest.TestCase):
    """The shape measured on 588 THOMAS BOYLAND ST SET_UPDATED.pdf: 44 vector
    pages, 6 with a title-block sheet number, text showing A- sheets (and an
    'OC-' code that is not a discipline)."""

    PROFILE = {"vector_pages": 44, "title_id_pages": 6,
               "title_prefixes": ["A"], "text_prefixes": ["A"]}

    def test_the_profile_ignores_codes_that_look_like_sheet_ids(self):
        page = {"width": 2592, "height": 1728, "text": "x" * 120 + "\nOC-202 NY-112 A-300",
                # Mid-sheet, inside no edge strip: this is body text, not a title block.
                "blocks": [B("x" * 120 + "\nOC-202 NY-112 A-300", (800, 800, 1400, 900))]}
        p = pt.file_sheet_profile([page, None])
        self.assertEqual((p["vector_pages"], p["title_id_pages"]), (1, 0))
        self.assertEqual(p["text_prefixes"], ["A"])

    def test_covered_by_the_discipline_sets_is_skipped_with_a_reason(self):
        d = pt.combined_set_decision(self.PROFILE, {"AR - 3.28.25.pdf": ["A", "GN", "RCP", "T", "Z"],
                                                    "PL - 6.29.26.pdf": ["P"]})
        self.assertEqual(d["covered_by"], ["AR - 3.28.25.pdf"])
        self.assertEqual(d["disciplines"], ["A"])
        self.assertIn("38 of 44 pages have no sheet number in the title block", d["reason"])

    def test_a_discipline_nobody_else_covers_is_indexed(self):
        profile = dict(self.PROFILE, text_prefixes=["A", "E"])
        self.assertIsNone(pt.combined_set_decision(profile, {"AR.pdf": ["A"]}))

    def test_a_file_whose_pages_carry_sheet_numbers_is_not_a_combined_set(self):
        profile = dict(self.PROFILE, title_id_pages=30)
        self.assertFalse(pt.looks_combined(profile))
        self.assertIsNone(pt.combined_set_decision(profile, {"AR.pdf": ["A"]}))

    def test_a_one_or_two_page_file_is_not_a_combined_set(self):
        """The as-built survey and the shed drawing were each one page."""
        for pages in (1, 2):
            with self.subTest(pages=pages):
                self.assertFalse(pt.looks_combined(
                    {"vector_pages": pages, "title_id_pages": 0,
                     "title_prefixes": [], "text_prefixes": ["A"]}))
        self.assertTrue(pt.looks_combined(
            {"vector_pages": 3, "title_id_pages": 0, "title_prefixes": [], "text_prefixes": ["A"]}))

    def test_a_file_with_no_readable_disciplines_is_indexed(self):
        profile = dict(self.PROFILE, text_prefixes=[])
        self.assertIsNone(pt.combined_set_decision(profile, {"AR.pdf": ["A"]}))


def _make_pdf(pages):
    """A real, minimal PDF with one Helvetica text line per list item per page.
    Offsets are computed, so pdfplumber and poppler both accept it."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        ops = " ".join(f"({line}) Tj 0 -16 Td" for line in lines)
        stream = f"BT /F1 12 Tf 72 700 Td {ops} ET"
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                     f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>").encode())
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode())
    out = b"%PDF-1.4\n"
    offsets = []
    for k, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class TheFileIsReadOnePageAtATime(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "set.pdf")
        Path(self.path).write_bytes(_make_pdf([
            ["GENERAL NOTES", "1. ALL PILES SHALL BE HELICAL PILES."],
            ["FOUNDATION PLAN", "PTAC"],
            ["ROOF PLAN"],
        ]))

    def test_the_whole_file_pass_keeps_each_pages_text(self):
        ctx = pt.file_context(self.path)
        self.assertEqual(ctx["page_count"], 3)
        self.assertIn("1. ALL PILES SHALL BE HELICAL PILES.", ctx["texts"][0])
        self.assertIn("FOUNDATION PLAN", ctx["texts"][1])
        self.assertEqual(set(ctx["profile"]), {"vector_pages", "title_id_pages",
                                                "title_prefixes", "text_prefixes"})
        self.assertIn("PTAC", ctx["tag_vocab"])

    def test_one_page_is_parsed_on_its_own(self):
        L = pt.page_layout_at(self.path, 2)
        self.assertEqual(L["page_number"], 2)
        self.assertIn("FOUNDATION PLAN", L["text"])
        self.assertNotIn("HELICAL", L["text"])

    def test_every_page_is_released_as_it_is_read(self):
        import inspect
        self.assertIn("page.close()", inspect.getsource(pt.file_context))
        self.assertIn("page.close()", inspect.getsource(pt.page_layout_at))


class ThePdfLibraryIsImportedInOnePlace(unittest.TestCase):

    def test_only_the_open_helper_imports_it(self):
        import inspect
        src = inspect.getsource(pt)
        self.assertEqual(src.count("import pdfplumber"), 1)
        self.assertIn("import pdfplumber", inspect.getsource(pt._open_pdf))
        for fn in (pt.page_layouts, pt.file_context, pt.page_layout_at):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_open_pdf(", inspect.getsource(fn))

    def test_no_agpl_pdf_library(self):
        """PyMuPDF is AGPL-3.0 and was ruled out for a hosted product."""
        import inspect
        src = inspect.getsource(pt)
        self.assertNotIn("import fitz", src)
        req = (Path(__file__).resolve().parents[2] / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("PyMuPDF==", req)


if __name__ == "__main__":
    unittest.main()
