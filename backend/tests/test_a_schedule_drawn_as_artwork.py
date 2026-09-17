"""M-200.00 prints seven schedules and gives the text layer none of them.

It is NOT a scan. 8,046 vector paths, 0 images, 982 characters — and every one
of those characters is the title block, the sheet number and the engineer's
disclaimer. Zero fall inside any of the seven schedule grids. The mechanical
engineer exports with text converted to curves: the letterforms are outlines
and the character codes are gone.

Measured across the 588 Boyland sets, 2026-09-16: 15 of 56 schedule-shaped
grids are invisible this way, and it is PER-CONSULTANT. JPW flattens; the
architect does not. That is why an entire discipline was unanswerable while
its title blocks read fine.

THE FOUR RULES THIS FILE HOLDS

  1. The grid comes from the ruling lines, not from a model. A value cannot
     land in the wrong column.
  2. A grid the text layer CAN read is never OCR'd, and the test for that is a
     character count, not a judgement.
  3. An OCR'd cell is tiered `ocr_grid_cell` — below a text-layer schedule
     cell, above a legend pairing — and never marked verified.
  4. A page indexes exactly as it does today when no engine is installed.
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

from lib import plan_extract as pe  # noqa: E402
from lib import plan_ocr  # noqa: E402
from lib import plan_records as pr  # noqa: E402
from lib import plan_text as pt  # noqa: E402


class FakePage:
    """The parts of a pdfplumber page `ruled_grids` reads."""

    def __init__(self, edges, chars=()):
        self.edges = edges
        self.chars = list(chars)


def h(x0, x1, top):
    return {"orientation": "h", "x0": x0, "x1": x1, "top": top, "bottom": top,
            "width": x1 - x0, "height": 0.0}


def v(x, top, bottom):
    return {"orientation": "v", "x0": x, "x1": x, "top": top, "bottom": bottom,
            "width": 0.0, "height": bottom - top}


def ch(x0, top):
    return {"x0": x0, "x1": x0 + 4, "top": top, "bottom": top + 6}


def a_grid(x0=60.0, x1=960.0, ys=(50.0, 90.0, 140.0, 190.0),
           xs=(60.0, 300.0, 600.0, 960.0), chars=()):
    edges = [h(x0, x1, y) for y in ys]
    edges += [v(x, ys[0], ys[-1]) for x in xs]
    # The letterforms: hundreds of short edges that are not rules.
    edges += [h(x0 + i, x0 + i + 3, ys[1] + 5) for i in range(0, 60, 3)]
    edges += [v(x0 + i, ys[1] + 2, ys[1] + 8) for i in range(0, 60, 3)]
    return FakePage(edges, chars)


class TheGridComesFromTheRulingLines(unittest.TestCase):

    def test_a_schedule_with_no_characters_in_it_is_found(self):
        got = pt.ruled_grids(a_grid())
        self.assertEqual(len(got), 1)
        g = got[0]
        self.assertEqual(g["chars"], 0)
        self.assertEqual(len(g["rows"]) - 1, 3)
        self.assertEqual(len(g["cols"]) - 1, 3)

    def test_letterform_edges_do_not_become_rules(self):
        # 40 short edges sit inside the grid. The row count must not move.
        self.assertEqual(len(pt.ruled_grids(a_grid())[0]["rows"]) - 1, 3)

    def test_a_grid_the_text_layer_can_read_reports_its_characters(self):
        g = pt.ruled_grids(a_grid(chars=[ch(100, 100), ch(120, 100)]))[0]
        self.assertEqual(g["chars"], 2)

    def test_the_sheet_frame_is_not_the_biggest_table_on_the_page(self):
        # A border enclosing the schedule. It must be dropped, or every page
        # reports one giant grid and the real ones are never seen.
        inner = a_grid()
        frame = FakePage(
            inner.edges
            + [h(10, 2560, y) for y in (10.0, 600.0, 1200.0, 1700.0)]
            + [v(x, 10.0, 1700.0) for x in (10.0, 900.0, 1800.0, 2560.0)])
        boxes = [tuple(round(x) for x in g["bbox"]) for g in pt.ruled_grids(frame)]
        self.assertIn((60, 50, 960, 190), boxes)
        self.assertNotIn((10, 10, 2560, 1700), boxes)

    def test_a_page_with_no_long_rules_has_no_grids(self):
        self.assertEqual(pt.ruled_grids(FakePage([h(10, 20, 5)])), [])

    def test_page_layout_at_publishes_only_the_blind_ones(self):
        src = inspect.getsource(pt.page_layout_at)
        self.assertIn('g["chars"] == 0', src)


class NothingIsRenderedBeforeItIsWorthRendering(unittest.TestCase):

    def test_a_thirty_six_inch_box_is_a_drawing_not_a_schedule(self):
        ok, why = plan_ocr.grid_is_readable(
            {"bbox": [0, 0, 2592, 1728], "rows": [0, 100], "cols": [0, 100]})
        self.assertFalse(ok)
        self.assertIn("drawing", why)

    def test_a_real_schedule_passes(self):
        ok, why = plan_ocr.grid_is_readable(
            {"bbox": [60, 50, 960, 190], "rows": [50, 90, 140, 190],
             "cols": [60, 300, 600, 960]})
        self.assertTrue(ok, why)

    def test_a_grid_with_more_cells_than_a_schedule_has_is_refused(self):
        ok, why = plan_ocr.grid_is_readable(
            {"bbox": [0, 0, 700, 700], "rows": list(range(0, 700, 10)),
             "cols": list(range(0, 700, 10))})
        self.assertFalse(ok)
        self.assertIn("cells", why)


class EachBoxGoesToTheCellThatContainsIt(unittest.TestCase):

    GRID = {"bbox": [60.0, 50.0, 960.0, 190.0],
            "rows": [50.0, 90.0, 140.0, 190.0],
            "cols": [60.0, 300.0, 600.0, 960.0]}

    def px(self, x_pt, y_pt, dpi=400):
        """A box centre in render pixels, measured from the grid's origin."""
        s = dpi / 72.0
        return ((x_pt - self.GRID["cols"][0]) * s,
                (y_pt - self.GRID["rows"][0]) * s)

    def test_a_value_lands_in_its_own_column(self):
        x, y = self.px(700, 160)
        table, strays = plan_ocr.place_in_grid([(x, y, "21")], self.GRID)
        self.assertEqual(table[2][2], "21")
        self.assertEqual(strays, 0)

    def test_two_boxes_in_one_cell_join_left_to_right(self):
        a = self.px(320, 60)
        b = self.px(360, 60)
        table, _ = plan_ocr.place_in_grid([(a[0], a[1], "UNIT"),
                                           (b[0], b[1], "NO.")], self.GRID)
        self.assertEqual(table[0][1], "UNIT NO.")

    def test_a_box_outside_the_grid_is_a_stray_and_not_forced_into_a_cell(self):
        table, strays = plan_ocr.place_in_grid(
            [(-50.0, -50.0, "SEE NOTES")], self.GRID)
        self.assertEqual(strays, 1)
        self.assertEqual([c for row in table for c in row if c], [])


class ThreeShapesAPrintedScheduleTakes(unittest.TestCase):
    """All three are on M-200.00, and an earlier version dropped three of its
    seven schedules by assuming only the first."""

    GRID = {"bbox": [60.0, 50.0, 960.0, 190.0]}

    def test_a_title_row_then_a_header_then_data(self):
        s = plan_ocr.schedule_from_table(
            [["ROOMS", "PTAC", "UNITS"],
             ["UNIT NO.", "QTY", "MAKE"],
             ["PTAC-1", "21", "AMANA"]], self.GRID)
        self.assertEqual(s["name"], "ROOMS PTAC UNITS")
        self.assertEqual(s["columns"], ["UNIT NO.", "QTY", "MAKE"])
        self.assertEqual(s["rows"], [["PTAC-1", "21", "AMANA"]])

    def test_a_two_tier_header_merges_rather_than_becoming_a_row(self):
        # FAN SCHEDULE prints 'MOTOR DATA' over HP / VOLTS.
        s = plan_ocr.schedule_from_table(
            [["FAN", "SCHEDULE", ""],
             ["TAG", "MOTOR DATA", ""],
             ["", "HP", "VOLTS"],
             ["SAF-1", "1/3", "208"]], self.GRID)
        self.assertEqual(s["rows"], [["SAF-1", "1/3", "208"]])
        self.assertEqual(s["columns"], ["TAG", "MOTOR DATA HP", "VOLTS"])

    def test_a_schedule_with_no_column_headings_keeps_its_row(self):
        # C408 MAINTENANCE prints one row under its title and no headings.
        s = plan_ocr.schedule_from_table(
            [["C408", "MAINTENANCE INFORMATION", "", "", "", ""],
             ["C408.2", "SYSTEM COMMISSIONING", "TOTAL 445.6 KBTU", "", "", ""]],
            self.GRID)
        self.assertEqual(s["columns"], [])
        self.assertEqual(s["rows"][0][0], "C408.2")

    def test_a_blank_band_between_the_title_and_the_header_is_skipped(self):
        s = plan_ocr.schedule_from_table(
            [["EXHAUST FAN SCHEDULE", "", ""], ["", "", ""],
             ["TAG", "CFM", "SP"], ["EF-1", "50", "0.3"]], self.GRID)
        self.assertEqual(s["columns"], ["TAG", "CFM", "SP"])
        self.assertEqual(s["rows"], [["EF-1", "50", "0.3"]])

    def test_an_empty_table_yields_nothing_rather_than_an_empty_schedule(self):
        self.assertIsNone(plan_ocr.schedule_from_table([["", ""], ["", ""]], self.GRID))


class AnOcrdCellSaysWhereItCameFrom(unittest.TestCase):

    PAGE = {"sheet_number": "M-200.00", "page_number": 9}

    def records(self, sched):
        fields = dict(pe.EMPTY_FIELDS, sheet_number="M-200.00", schedules=[sched])
        fields["elements"] = pt.elements_from_evidence([], [sched], [])
        return pr.build_records(fields, page=self.PAGE, raw_text="")

    OCR = {"name": "ROOMS PTAC UNITS SCHEDULE", "columns": ["UNIT NO.", "QTY"],
           "rows": [["PTAC-1", "21"]], "bbox": [63, 53, 958, 211],
           "source": "ocr_grid"}

    def test_the_tier_sits_under_a_text_layer_schedule_cell(self):
        r = [x for x in self.records(self.OCR) if x["record_type"] == "schedule"][0]
        self.assertEqual(r["tier"], pe.TIER_OCR_GRID)
        self.assertEqual(r["source"], "ocr_grid")
        self.assertLess(pr.tier_rank(pe.TIER_SCHEDULE_CELL),
                        pr.tier_rank(pe.TIER_OCR_GRID))
        self.assertLess(pr.tier_rank(pe.TIER_OCR_GRID),
                        pr.tier_rank(pe.TIER_TAG_LEGEND))

    def test_freeform_ocr_sits_above_vision_and_below_the_text_layer(self):
        self.assertLess(pr.tier_rank(pe.TIER_TEXT_LAYER),
                        pr.tier_rank(pe.TIER_OCR_FREEFORM))
        self.assertLess(pr.tier_rank(pe.TIER_OCR_FREEFORM),
                        pr.tier_rank(pe.TIER_VISION))

    def test_it_is_never_marked_verified_and_never_gets_a_span(self):
        # The page prints no text there — that is why it was OCR'd. A span
        # would be a claim that the text layer confirms it.
        r = [x for x in self.records(self.OCR) if x["record_type"] == "schedule"][0]
        self.assertFalse(r["verified"])
        self.assertIsNone(r["quote_span"])

    def test_a_table_finder_schedule_is_still_the_stronger_tier(self):
        plain = dict(self.OCR)
        plain.pop("source")
        r = [x for x in self.records(plain) if x["record_type"] == "schedule"][0]
        self.assertEqual(r["tier"], pe.TIER_SCHEDULE_CELL)
        self.assertEqual(r["source"], "table_finder")
        self.assertTrue(r["verified"])

    def test_a_quantity_read_by_ocr_says_so_in_its_basis(self):
        els = [x for x in self.records(self.OCR) if x["record_type"] == "element"]
        self.assertTrue(els)
        self.assertEqual(els[0]["payload"]["count_basis"], "ocr_schedule_qty")
        self.assertEqual(els[0]["tier"], pe.TIER_OCR_GRID)

    def test_the_same_quantity_from_the_text_layer_keeps_the_stronger_basis(self):
        plain = dict(self.OCR)
        plain.pop("source")
        els = [x for x in self.records(plain) if x["record_type"] == "element"]
        self.assertEqual(els[0]["payload"]["count_basis"], "schedule_qty")

    def test_every_basis_this_pipeline_writes_has_a_tier(self):
        for basis in ("schedule_qty", "ocr_schedule_qty", "tag_occurrences",
                      "glyph_match", pe.TIER_VISION):
            with self.subTest(basis=basis):
                self.assertIn(pr.BASIS_TIERS[basis], pr.TIER_ORDER)


class NoEngineIsAWorkingState(unittest.TestCase):

    def test_reading_without_an_engine_returns_nothing_and_does_not_raise(self):
        saved = plan_ocr._engine, plan_ocr._engine_failed
        try:
            plan_ocr._engine, plan_ocr._engine_failed = None, "pretend it is absent"
            self.assertFalse(plan_ocr.available())
            self.assertIsNone(plan_ocr.read_grid(b"not an image",
                                                 {"bbox": [0, 0, 10, 10],
                                                  "rows": [0, 10], "cols": [0, 10]}))
        finally:
            plan_ocr._engine, plan_ocr._engine_failed = saved

    def test_the_indexer_says_so_rather_than_failing_the_page(self):
        import server
        src = inspect.getsource(server._ocr_blind_grids)
        self.assertIn("ocr_engine_absent", src)
        self.assertIn("plan_ocr.available()", src)


class TheIndexerReadsThemAndKeepsWhatElseItFound(unittest.TestCase):

    def setUp(self):
        import server
        self.server = server

    def test_the_blind_grids_are_read_during_a_page_index(self):
        src = inspect.getsource(self.server._index_single_page)
        self.assertIn("_ocr_blind_grids(", src)

    def test_a_failed_read_never_fails_the_page(self):
        src = inspect.getsource(self.server._index_single_page)
        i = src.index("_ocr_blind_grids(")
        self.assertIn("except Exception", src[i:i + 2500])

    def test_rebuilding_the_elements_does_not_drop_the_drawn_ones(self):
        # elements_from_evidence derives from schedules, so calling it again
        # after OCR would silently erase every glyph count on any sheet that
        # also carries a schedule.
        src = inspect.getsource(self.server._index_single_page)
        i = src.index("_ocr_blind_grids(")
        after = src[i:i + 1800]
        self.assertIn('count_basis") == "glyph_match"', after)
        self.assertIn("+ drawn", after)

    def test_the_crop_is_rendered_by_the_binary_the_indexer_already_uses(self):
        src = inspect.getsource(self.server._render_pdf_crop)
        self.assertIn("pdftoppm", src)
        for flag in ("-x", "-y", "-W", "-H"):
            with self.subTest(flag=flag):
                self.assertIn(f'"{flag}"', src)

    def test_nothing_renders_the_whole_sheet_at_ocr_resolution(self):
        # A 36x24 page at 400 dpi is over 400 MB of RGB, on the container that
        # already restarted mid-reindex over 250 dpi full pages.
        src = inspect.getsource(self.server._ocr_blind_grids)
        # Every renderer this function names, rather than a banned substring:
        # the crop is passed to to_thread by reference, so there is no paren
        # to anchor on and a bare assertNotIn would be satisfied by accident.
        self.assertEqual(set(re.findall(r"_render_pdf_\w+", src)),
                         {"_render_pdf_crop"})


if __name__ == "__main__":
    unittest.main()
