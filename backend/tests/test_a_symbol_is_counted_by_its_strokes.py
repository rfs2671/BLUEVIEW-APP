"""A roof drain is a square with an X in it, and nothing else could see it.

A schedule quantity counts what somebody scheduled. A tag count counts what
somebody lettered. A drain DRAWN on the roof plan and tagged `AD` beside it
was countable only by a vision model looking at a picture — which is how `41`
happened.

Measured on A-105.01 (588 Boyland, AR - 8.18.26 p7), 2026-09-16:

    template lifted off the legend at 6.72pt
    3 exact matches: the legend key, and two on the plan drawn at 9.00pt,
      each inside four converging SLOPE DN arrows, each beside an `AD`
    next best score anywhere on the sheet: 0.067  (the EXHAUST FAN glyph,
      which is also a square with an X and is indistinguishable small)

THE TWO RULES THIS FILE HOLDS

  1. SHAPE IS THE FAMILY, TEXT IN THE BOX IS THE MEMBER. On the same sheet the
     WINDOW TAG template's next-best score is 0.870 — the same hexagon with a
     different digit inside. A match with nothing printed inside it is a
     FAMILY count and says so. It is never quietly a member count.

  2. AN AMBIGUOUS TEMPLATE IS NOT LIFTED AT ALL. Lifting is the fragile step,
     not matching. When the legend row does not resolve to exactly one drawn
     cluster, nothing is emitted — a wrong template counts the wrong thing
     everywhere on the sheet, confidently, and nothing downstream catches it.
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
from lib import plan_glyphs as pg  # noqa: E402
from lib import plan_records as pr  # noqa: E402
from lib import plan_text as pt  # noqa: E402


def boxed_x(x, y, size):
    """The drain: a square with both diagonals. Four strokes."""
    s = size
    return [
        {"pts": [(x, y), (x + s, y)], "box": (x, y, x + s, y)},
        {"pts": [(x + s, y), (x + s, y + s)], "box": (x + s, y, x + s, y + s)},
        {"pts": [(x + s, y + s), (x, y + s)], "box": (x, y + s, x + s, y + s)},
        {"pts": [(x, y + s), (x, y)], "box": (x, y, x, y + s)},
        {"pts": [(x, y), (x + s, y + s)], "box": (x, y, x + s, y + s)},
        {"pts": [(x + s, y), (x, y + s)], "box": (x, y, x + s, y + s)},
    ]


def hexagon(x, y, size):
    s = size
    pts = [(x, y + s / 2), (x + s / 4, y), (x + 3 * s / 4, y), (x + s, y + s / 2),
           (x + 3 * s / 4, y + s), (x + s / 4, y + s), (x, y + s / 2)]
    return [{"pts": pts, "box": (x, y, x + s, y + s)}]


def word(text, x0, top, w=6.0, h=6.0):
    return {"text": text, "x0": x0, "x1": x0 + w, "top": top, "bottom": top + h}


def described(group):
    sig, box = pg.signature(group)
    return {"sig": sig, "box": box, "strokes": len(group)}


class TheSameSymbolAtAnySizeIsTheSameShape(unittest.TestCase):

    def test_scale_does_not_change_the_signature(self):
        # The template was lifted at 6.72pt and matched instances at 9.00pt.
        small, _ = pg.signature(boxed_x(0, 0, 6.72))
        big, _ = pg.signature(boxed_x(900, 1700, 9.0))
        self.assertEqual(small, big)
        self.assertEqual(pg.similarity(small, big), 1.0)

    def test_position_does_not_change_it_either(self):
        a, _ = pg.signature(boxed_x(10, 10, 9))
        b, _ = pg.signature(boxed_x(2000, 1500, 9))
        self.assertEqual(a, b)

    def test_stroke_direction_does_not_change_it(self):
        fwd = boxed_x(0, 0, 9)
        rev = [dict(o, pts=list(reversed(o["pts"]))) for o in fwd]
        self.assertEqual(pg.signature(fwd)[0], pg.signature(rev)[0])

    def test_a_different_shape_does_not_match(self):
        sq, _ = pg.signature(boxed_x(0, 0, 9))
        hx, _ = pg.signature(hexagon(0, 0, 9) * 3)
        self.assertLess(pg.similarity(sq, hx), 0.5)

    def test_a_shape_too_simple_to_identify_anything_gets_no_signature(self):
        tick = [{"pts": [(0, 0), (5, 5)], "box": (0, 0, 5, 5)}]
        self.assertIsNone(pg.signature(tick)[0])

    def test_a_hairline_gets_no_signature(self):
        flat = [{"pts": [(0, 0), (9, 0)], "box": (0, 0, 9, 0)}] * 8
        self.assertIsNone(pg.signature(flat)[0])


class AnAmbiguousTemplateIsNotLifted(unittest.TestCase):

    LABEL = (1773.5, 1274.9, 1858.8, 1282.9)      # FLOOR/AREA/ROOF DRAIN

    def beside(self, dx):
        return described(boxed_x(self.LABEL[0] - dx, self.LABEL[1], 6.72))

    def test_exactly_one_glyph_beside_the_label_is_lifted(self):
        one = self.beside(12)
        tmpl, why = pg.lift_template([one], self.LABEL)
        self.assertIs(tmpl, one)
        self.assertEqual(why, "")

    def test_three_glyphs_beside_a_merged_label_lift_nothing(self):
        # EXIT SIGN / DOOR TAG / WINDOW TAG print as one text block.
        three = [self.beside(12), self.beside(20), self.beside(28)]
        tmpl, why = pg.lift_template(three, self.LABEL)
        self.assertIsNone(tmpl)
        self.assertIn("3 clusters", why)

    def test_no_glyph_beside_the_label_lifts_nothing(self):
        tmpl, why = pg.lift_template([], self.LABEL)
        self.assertIsNone(tmpl)
        self.assertIn("no drawn glyph", why)

    def test_a_glyph_too_far_away_is_not_this_row_s_glyph(self):
        far = described(boxed_x(self.LABEL[0] - 300, self.LABEL[1], 6.72))
        self.assertIsNone(pg.lift_template([far], self.LABEL)[0])

    def test_a_row_that_lifts_nothing_says_why_and_emits_no_count(self):
        rows = [{"meaning": "EXIT SIGN DOOR TAG WINDOW TAG", "box": self.LABEL}]
        three = [self.beside(12), self.beside(20), self.beside(28)]
        els, flags = pg.count_symbols(three, rows, [])
        self.assertEqual(els, [])
        self.assertTrue(any("glyph_template_skipped" in f for f in flags))


class ShapeIsTheFamilyAndTextIsTheMember(unittest.TestCase):

    LABEL = (1773.5, 1274.9, 1858.8, 1282.9)

    def setUp(self):
        self.tmpl = described(boxed_x(1761.0, 1274.9, 6.72))
        self.rows = [{"meaning": "FLOOR/AREA/ROOF DRAIN", "box": self.LABEL}]

    def test_a_symbol_with_nothing_printed_inside_it_is_a_family_count(self):
        # The sheet prints `AD` BESIDE each drain, not inside it. Beside is not
        # inside, and a family count is the honest answer.
        hits = [described(boxed_x(1010.5, 786.8, 9.0)),
                described(boxed_x(1736.5, 786.8, 9.0))]
        els, _ = pg.count_symbols([self.tmpl] + hits, self.rows,
                                  [word("AD", 1010.5, 770.0)])
        self.assertEqual(len(els), 1)
        self.assertEqual(els[0]["glyph_scope"], "family")
        self.assertEqual(els[0]["tag"], "")
        self.assertEqual(els[0]["count_if_stated"], 2)
        self.assertIn("no mark inside", els[0]["location_hint"])

    def test_a_symbol_with_its_mark_inside_is_a_member_count(self):
        hit = described(boxed_x(500.0, 500.0, 18.0))
        els, _ = pg.count_symbols([self.tmpl, hit], self.rows,
                                  [word("W3", 506.0, 506.0)])
        self.assertEqual(els[0]["glyph_scope"], "member")
        self.assertEqual(els[0]["tag"], "W3")

    def test_two_members_of_one_family_are_counted_separately(self):
        # THE 0.870 CASE. The hexagon is the same for W1 and W3; the digit is
        # the only difference, and it is text.
        a = described(boxed_x(500.0, 500.0, 18.0))
        b = described(boxed_x(600.0, 500.0, 18.0))
        c = described(boxed_x(700.0, 500.0, 18.0))
        els, _ = pg.count_symbols(
            [self.tmpl, a, b, c], self.rows,
            [word("W1", 506.0, 506.0), word("W1", 606.0, 506.0),
             word("W3", 706.0, 506.0)])
        got = {e["tag"]: e["count_if_stated"] for e in els}
        self.assertEqual(got, {"W1": 2, "W3": 1})
        self.assertTrue(all(e["glyph_scope"] == "member" for e in els))

    def test_a_word_beside_the_symbol_never_names_it(self):
        hit = described(boxed_x(500.0, 500.0, 18.0))
        els, _ = pg.count_symbols([self.tmpl, hit], self.rows,
                                  [word("AD", 460.0, 500.0)])
        self.assertEqual(els[0]["glyph_scope"], "family")

    def test_a_single_letter_inside_is_not_a_mark(self):
        # Seeding a count from a lone letter had '1' counted 138 times over 11
        # sheets. The same test the tag counter uses applies here.
        hit = described(boxed_x(500.0, 500.0, 18.0))
        els, _ = pg.count_symbols([self.tmpl, hit], self.rows,
                                  [word("A", 506.0, 506.0)])
        self.assertEqual(els[0]["glyph_scope"], "family")

    def test_the_legend_key_itself_is_not_counted_as_an_occurrence(self):
        hit = described(boxed_x(1010.5, 786.8, 9.0))
        els, _ = pg.count_symbols([self.tmpl, hit], self.rows, [])
        self.assertEqual(els[0]["count_if_stated"], 1)


class WhatAGlyphCountRestsOn(unittest.TestCase):

    def records(self, element):
        fields = dict(pe.EMPTY_FIELDS, sheet_number="A-105.01", elements=[element])
        return pr.build_records(fields, page={"sheet_number": "A-105.01",
                                              "page_number": 7}, raw_text="")

    ELEMENT = {"name": "FLOOR/AREA/ROOF DRAIN", "tag": "", "count_if_stated": 2,
               "count_basis": "glyph_match", "glyph_scope": "family",
               "location_hint": "symbols matching the legend mark, no mark inside them",
               "bbox": [1010.5, 786.8, 1019.5, 795.8],
               "positions": [[1010.5, 786.8, 1019.5, 795.8],
                             [1736.5, 786.8, 1745.5, 795.8]]}

    def test_it_is_tiered_with_a_tag_counted_on_the_sheet(self):
        r = self.records(self.ELEMENT)[0]
        self.assertEqual(r["tier"], pe.TIER_TAG_LEGEND)
        self.assertEqual(pr.BASIS_TIERS["glyph_match"], pe.TIER_TAG_LEGEND)

    def test_it_outranks_a_count_read_off_the_image(self):
        self.assertLess(pr.tier_rank(pr.BASIS_TIERS["glyph_match"]),
                        pr.tier_rank(pe.TIER_VISION))

    def test_a_family_count_says_so_in_the_words_a_reader_would_see(self):
        r = self.records(self.ELEMENT)[0]
        self.assertIn("count 2", r["quote"])
        self.assertIn("no mark inside", r["quote"])
        self.assertEqual(r["payload"]["glyph_scope"], "family")

    def test_every_position_survives_into_the_record(self):
        r = self.records(self.ELEMENT)[0]
        self.assertEqual(r["bbox"], [1010.5, 786.8, 1019.5, 795.8])
        self.assertEqual(len(r["payload"]["positions"]), 2)


class WhereItDoesNotApply(unittest.TestCase):

    def test_a_page_with_no_drawn_paths_yields_nothing(self):
        class Scan:
            lines = []
            curves = []
            rects = []

            def extract_words(self):
                return []
        els, flags = pg.symbols_on_page(Scan(), [{"meaning": "X", "box": (0, 0, 1, 1)}])
        self.assertEqual(els, [])
        self.assertEqual(flags, [])

    def test_only_rows_whose_mark_is_drawn_ask_for_a_template(self):
        # A row with a LETTERED mark is counted by count_tags and needs none.
        rows = pg.legend_rows_from_fields([
            {"symbol": "AD", "meaning": "AREA DRAIN", "bbox": [0, 0, 10, 10]},
            {"symbol": "", "meaning": "FLOOR/AREA/ROOF DRAIN", "bbox": [1, 1, 9, 9]},
            {"symbol": "", "meaning": "", "bbox": [2, 2, 8, 8]},
        ])
        self.assertEqual([r["meaning"] for r in rows], ["FLOOR/AREA/ROOF DRAIN"])

    def test_the_layout_carries_the_shapes_and_decides_nothing(self):
        import inspect
        src = inspect.getsource(pt._glyph_inputs)
        self.assertIn("describe_page(", src)
        # Anchored on the call, not the bare name: a bare literal would be
        # satisfied by anything that happens to contain it.
        self.assertNotIn("count_symbols(", src)

    def test_the_pairing_happens_where_the_legend_is_known(self):
        import inspect
        src = inspect.getsource(pt.fields_from_layout)
        self.assertIn("count_symbols(", src)
        self.assertIn("legend_rows_from_fields(", src)


if __name__ == "__main__":
    unittest.main()
