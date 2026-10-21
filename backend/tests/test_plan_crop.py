"""lib/plan_crop: the picture of where a plans answer came from.

A record's bbox is in PDF points on the page as displayed; the page JPEG is
the same page rendered at the indexer's DPI. These pin the mapping, the crop
(padding, minimum size, the edges), the marks, and which records an answer
is taken to rest on -- including when that is more than one place.
"""

from __future__ import annotations

import unittest

from PIL import Image

from lib import plan_crop as pc

DPI = 100                                     # 1 point = 100/72 px
S = pc.px_per_pt(DPI)


def _page(w_in=24, h_in=18):
    return Image.new("RGB", (int(w_in * DPI), int(h_in * DPI)), (255, 255, 255))


def _red(px):
    r, g, b = px[:3]
    return r > 180 and g < 80 and b < 80


def _rec(pid, quote, bbox=None, sheet="A-201", verified=True, ordinal=0, tier="text_layer"):
    return {"page_id": pid, "sheet_number": sheet, "quote": quote, "bbox": bbox,
            "verified": verified, "record_type": "text", "ordinal": ordinal, "tier": tier}


class TheMapping(unittest.TestCase):
    def test_points_become_pixels_at_dpi_over_72(self):
        self.assertAlmostEqual(pc.px_per_pt(250), 250 / 72)
        box = pc.to_pixels([72, 144, 216, 288], S, (2400, 1800))
        self.assertEqual(box, (100.0, 200.0, 300.0, 400.0))

    def test_a_box_off_the_image_is_not_drawn(self):
        """A wrong mapping is refused, not clamped into a wrong place."""
        self.assertIsNone(pc.to_pixels([1700, 0, 1800, 50], S, (2400, 1800)))   # x past 2400 px
        self.assertIsNone(pc.to_pixels([0, 0, 0, 0], S, (2400, 1800)))
        self.assertIsNone(pc.to_pixels(["x", 0, 1, 1], S, (2400, 1800)))
        self.assertIsNone(pc.to_pixels([1, 2, 3], S, (2400, 1800)))

    def test_a_hair_past_the_edge_is_clamped(self):
        box = pc.to_pixels([1700, 1250, 1735, 1300], S, (2400, 1800))   # 2409.7 px wide edge
        self.assertEqual(box[2], 2400.0)
        self.assertEqual(box[3], 1800.0)


class TheCrop(unittest.TestCase):
    def test_one_box_is_inside_with_padding_and_the_minimum_size(self):
        box = (1000, 800, 1100, 850)
        l, t, r, b = pc.crop_box([box], (2400, 1800), px_per_inch=DPI)
        self.assertLessEqual(l, box[0] - DPI)                 # at least an inch around it
        self.assertLessEqual(t, box[1] - DPI)
        self.assertGreaterEqual(r, box[2] + DPI)
        self.assertGreaterEqual(b, box[3] + DPI)
        self.assertGreaterEqual(r - l, pc.MIN_CROP_IN[0] * DPI)    # legible on a phone
        self.assertGreaterEqual(b - t, pc.MIN_CROP_IN[1] * DPI)

    def test_a_box_at_the_corner_is_shifted_not_cut(self):
        l, t, r, b = pc.crop_box([(0, 0, 50, 40)], (2400, 1800), px_per_inch=DPI)
        self.assertEqual((l, t), (0, 0))
        self.assertEqual((r, b), (int(pc.MIN_CROP_IN[0] * DPI), int(pc.MIN_CROP_IN[1] * DPI)))
        l, t, r, b = pc.crop_box([(2350, 1760, 2400, 1800)], (2400, 1800), px_per_inch=DPI)
        self.assertEqual((r, b), (2400, 1800))
        self.assertEqual(r - l, int(pc.MIN_CROP_IN[0] * DPI))

    def test_a_region_bigger_than_the_page_is_the_page(self):
        self.assertEqual(pc.crop_box([(10, 10, 2390, 1790)], (2400, 1800), px_per_inch=DPI),
                         (0, 0, 2400, 1800))

    def test_several_boxes_are_all_in(self):
        boxes = [(200, 200, 300, 260), (1500, 1200, 1600, 1250)]
        l, t, r, b = pc.crop_box(boxes, (2400, 1800), px_per_inch=DPI)
        for x0, y0, x1, y1 in boxes:
            self.assertTrue(l <= x0 and t <= y0 and r >= x1 and b >= y1)


class TheMarks(unittest.TestCase):
    def test_one_box_is_outlined_in_red_without_a_number(self):
        img = _page()
        out = pc.render(img, [(1, (1000, 800, 1100, 850))], px_per_inch=DPI, numbered=False)
        l, t, _r, _b = pc.crop_box([(1000, 800, 1100, 850)], img.size, px_per_inch=DPI)
        self.assertTrue(_red(out.getpixel((1050 - l, 800 - t - 6))))    # top edge, just outside
        self.assertFalse(_red(out.getpixel((1050 - l, 825 - t))))        # inside stays clear
        self.assertFalse(_red(out.getpixel((1050 - l, 800 - t - 40))))   # no tab above it
        self.assertEqual(img.getpixel((1050, 796)), (255, 255, 255))    # the page is untouched

    def test_several_are_numbered(self):
        img = _page()
        boxes = [(1, (500, 500, 600, 550)), (2, (1200, 900, 1300, 950))]
        out = pc.render(img, boxes, px_per_inch=DPI, numbered=True)
        l, t, _r, _b = pc.crop_box([b for _n, b in boxes], img.size, px_per_inch=DPI)
        for _n, (x0, y0, _x1, _y1) in boxes:
            # the red tab sits on the box's top-left corner, above it
            self.assertTrue(_red(out.getpixel((x0 - l + 2, y0 - t - 15))))


class WhatTheAnswerRestsOn(unittest.TestCase):
    def test_the_record_whose_value_the_answer_repeats(self):
        recs = [_rec("p1", "EF-2 FAN 1200 CFM", [10, 10, 50, 30], ordinal=0),
                _rec("p1", "EF-3 FAN 800 CFM", [100, 10, 150, 30], ordinal=1)]
        got = pc.pick(recs, "EF-3 moves 800 CFM (A-201).")
        self.assertEqual([r["ordinal"] for r in got["marks"]], [1])
        self.assertFalse(got["ambiguous"])

    def test_the_same_value_in_two_places_is_a_choice(self):
        recs = [_rec("p1", "DOOR D3 3'-0\"", [10, 10, 50, 30], ordinal=0),
                _rec("p1", "DOOR D3 3'-0\"", [400, 300, 450, 330], ordinal=1)]
        got = pc.pick(recs, "D3 is 3'-0\" wide.")
        self.assertEqual(len(got["marks"]), 2)
        self.assertTrue(got["ambiguous"])

    def test_two_facts_combined_are_both_marked_not_a_choice(self):
        recs = [_rec("p1", "PTAC-1 count 21", [10, 10, 50, 30], ordinal=0),
                _rec("p1", "PTAC-2 count 9", [100, 10, 150, 30], ordinal=1)]
        got = pc.pick(recs, "PTAC-1: 21, PTAC-2: 9.")
        self.assertEqual(len(got["marks"]), 2)
        self.assertFalse(got["ambiguous"])

    def test_the_sheet_the_answer_names_narrows_it(self):
        recs = [_rec("p1", "WINDOW SCREEN", [10, 10, 50, 30], sheet="SSP-011.00"),
                _rec("p2", "WINDOW SCREEN", [10, 10, 50, 30], sheet="SSP-012.00")]
        got = pc.pick(recs, "Window protection is on SSP-012.00.")
        self.assertEqual([r["page_id"] for r in got["marks"]], ["p2"])
        self.assertFalse(got["ambiguous"])

    def test_nothing_repeated_is_the_best_hit(self):
        recs = [_rec("p1", "ALPHA", [10, 10, 50, 30], ordinal=0),
                _rec("p1", "BRAVO", [100, 10, 150, 30], ordinal=1)]
        got = pc.pick(recs, "Yes, it's there.")
        self.assertEqual([r["ordinal"] for r in got["marks"]], [0])

    def test_an_unverified_record_shows_what_it_could_be(self):
        recs = [_rec("p1", "PTAC-2 count 6", [10, 10, 50, 30], verified=False, tier="vision"),
                _rec("p1", "PTAC-2 schedule", [100, 10, 150, 30], ordinal=1)]
        got = pc.pick(recs, "There are 6 PTAC-2.")
        self.assertTrue(got["unverified"])
        self.assertTrue(got["ambiguous"])
        self.assertEqual(len(got["marks"]), 2)

    def test_unusable_records_are_never_marked_and_the_cap_holds(self):
        recs = [_rec("p1", f"TAG T{i}", [i * 10, 0, i * 10 + 5, 5], ordinal=i) for i in range(1, 9)]
        got = pc.pick(recs, " ".join(f"T{i}" for i in range(1, 9)))
        self.assertEqual(len(got["marks"]), pc.MAX_MARKS)
        self.assertEqual(pc.pick(recs, "T1", usable=lambda r: False)["marks"], [])

    def test_pages_are_capped_and_numbers_kept(self):
        recs = [_rec(f"p{i}", "SAME 12", [0, 0, 5, 5], sheet=f"A-{i}") for i in range(1, 4)]
        groups = pc.by_page(pc.pick(recs, "12")["marks"])
        self.assertEqual(len(groups), pc.MAX_IMAGES)
        self.assertEqual([[n for n, _r in g] for _p, g in groups], [[1], [2]])


class TheCaptions(unittest.TestCase):
    def test_words(self):
        self.assertEqual(pc.caption("SSP-011.00", numbers=[1], total=1, ambiguous=False,
                                    unverified=False, whole=False),
                         "SSP-011.00 — where this comes from")
        self.assertEqual(pc.caption("A-201", numbers=[1, 2], total=2, ambiguous=True,
                                    unverified=False, whole=False),
                         "2 possible spots on A-201 — which one?")
        self.assertEqual(pc.caption("A-201", numbers=[3], total=3, ambiguous=True,
                                    unverified=False, whole=False, pictures=2),
                         "1 possible spot on A-201 (#3) — which one?")
        self.assertEqual(pc.caption("S-001", numbers=[1], total=1, ambiguous=False,
                                    unverified=False, whole=True, title="General Notes"),
                         "S-001 General Notes — full sheet (the exact spot isn't marked in the index)")


if __name__ == "__main__":
    unittest.main()
