"""Walls by type (operator's spec, Roy 2026-10-28; lib.plan_walls): LF per
wall type from the wall layer, the wall-type tags and the VERIFIED scale,
reconciled with A-500. Refused where the scale does not verify or a wall
carries no type.

What this guards, each from the measurement on 588 Boyland
(bv-worktrees/T1_walls_measure.md):

  * A wall is two faces; an exterior wall's skins (EPS, sheathing) are lines
    under an inch from its face and are not a second wall.
  * A wall in a viewport whose scale did not verify has no length: refused,
    in no type and in no figure.
  * A wall no tag reaches is UNTYPED: listed with its length, counted in no
    type. "Untyped" is never a type.
  * A tag names the wall its leader ends in, not the nearest wall.
  * Two pieces on one line are one wall only across a joint the drawing
    explains (a doorway with a door in it, a T junction); a corridor between
    them is not a wall.
  * The stair wall P1 continues past the stair as corridor wall P2: a run
    tagged with two types is cut at the one joint between them, and refused
    (AMBIGUOUS) where more than one joint lies between - never split by a
    guess.
  * The plans' tags reconcile with A-500's table both ways.
  * A plan's floor is the level its title names; "FLOOR PLAN" names none.

WRITTEN TO FAIL BY ASSERTION ON A TREE WITHOUT THE MODULE: every test reaches
lib.plan_walls through `_pw()`, which turns a missing module or name into an
AssertionError rather than an ImportError at collection.
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

#: 1/4" = 1'-0": 1.5pt of paper per real inch.
Q = 1.5
WALL = "XR FLOOR PLANS|A-Wall"
TAGS = "XR FLOOR PLANS|WALL TAGS"
DOOR = "XR FLOOR PLANS|A-Door"


def _pw(*names):
    try:
        mod = importlib.import_module("lib.plan_walls")
    except ImportError as e:
        raise AssertionError(f"lib.plan_walls is not importable: {e}")
    for n in names:
        assert hasattr(mod, n), f"lib.plan_walls has no {n}"
    return mod


# ── a synthetic page ───────────────────────────────────────────────────────

def _seg(x1, y1, x2, y2):
    return ("l", (x1, y1), (x2, y2))


def _draw(layer, *segs):
    xs = [v for s in segs for v in (s[1][0], s[2][0])]
    ys = [v for s in segs for v in (s[1][1], s[2][1])]
    return {"layer": layer, "items": list(segs), "rect": (min(xs), min(ys), max(xs), max(ys)),
            "colour": None}


def h_wall(y, x0, x1, t_in, skins=()):
    """A horizontal wall: faces at y and y + t (inches -> points), plus skin
    lines `skins` inches inside the top face."""
    t = t_in * Q
    segs = [_seg(x0, y, x1, y), _seg(x0, y + t, x1, y + t)]
    segs += [_seg(x0, y + k * Q, x1, y + k * Q) for k in skins]
    return _draw(WALL, *segs)


def v_wall(x, y0, y1, t_in):
    t = t_in * Q
    return _draw(WALL, _seg(x, y0, x, y1), _seg(x + t, y0, x + t, y1))


def tag(text, cx, cy, leader_to=None, half=10.0):
    """A diamond centred at (cx, cy) on the WALL TAGS layer, its text a word
    at the centre, and a leader from its bottom/top/left/right corner to
    `leader_to` (an axis-aligned point)."""
    segs = [_seg(cx, cy - half, cx + half, cy), _seg(cx + half, cy, cx, cy + half),
            _seg(cx, cy + half, cx - half, cy), _seg(cx - half, cy, cx, cy - half)]
    if leader_to:
        lx, ly = leader_to
        if abs(lx - cx) < 0.01:
            start = (cx, cy - half) if ly < cy else (cx, cy + half)
        else:
            start = (cx - half, cy) if lx < cx else (cx + half, cy)
        segs.append(_seg(start[0], start[1], lx, ly))
    return _draw(TAGS, *segs), (text, cx, cy)


class Page:
    def __init__(self, drawings, words=(), width=2000.0, height=1500.0):
        self.drawings = list(drawings)
        self.words = list(words)
        self.width, self.height = width, height


class VP:
    def __init__(self, bbox, verified=True, pt_per_in=Q, title="SECOND FLOOR PLAN", refusal=""):
        self.drawing_bbox = bbox
        self.bbox = bbox
        self.verified = verified
        self.pt_per_in = pt_per_in if verified else None
        self.title = title
        self.scale_text = '1/4" = 1\'-0"'
        self.refusal = refusal


class Sheet:
    def __init__(self, *vps):
        self.viewports = list(vps)

    def at(self, x, y):
        hits = [v for v in self.viewports
                if v.drawing_bbox[0] <= x <= v.drawing_bbox[2] and v.drawing_bbox[1] <= y <= v.drawing_bbox[3]]
        return hits[0] if len(hits) == 1 else None


def build(drawings, words=(), sheet=None, door=None):
    pw = _pw("floor_walls")
    page = Page(drawings, words)
    sheet = sheet or Sheet(VP((0, 0, 2000, 1500)))
    return pw.floor_walls(page, scale_sheet=sheet, legend_thickest_in=12.0, widest_door_in=door)


def typed(res, t):
    return [w for w in res["walls"] if w["status"] == "typed" and w["type"] == t]


# ── the rules, on synthetic drawings ───────────────────────────────────────

class AWallIsTwoFaces(unittest.TestCase):

    def test_two_faces_six_inches_apart_are_one_wall_of_its_length(self):
        d, w = tag("P2", 150, 160, leader_to=(150, 100 + 6 * Q))
        res = build([h_wall(100, 100, 100 + 120 * Q, 6), d], [w])
        self.assertEqual(res["by_type"], {"P2": 10.0})       # 120" of wall = 10 LF
        self.assertEqual(typed(res, "P2")[0]["thick_in"], 6.0)

    def test_an_exterior_walls_skins_are_not_a_second_wall(self):
        # faces 10" apart, three skin lines within 0.8" of the outer face
        d, w = tag("W1", 300, 60, leader_to=(300, 100 + 10 * Q))
        res = build([h_wall(100, 100, 100 + 240 * Q, 10, skins=(0.3, 0.5, 0.8)), d], [w])
        self.assertEqual(len(res["walls"]), 1, res["walls"])
        self.assertEqual(res["walls"][0]["thick_in"], 10.0)
        self.assertEqual(res["by_type"], {"W1": 20.0})

    def test_lines_further_apart_than_the_thickest_wall_are_no_wall(self):
        # 12" legend + 2" margin: faces 20" apart are two lone lines
        res = build([h_wall(100, 100, 400, 20)])
        self.assertEqual(res["walls"], [])

    def test_short_hatch_strokes_are_not_faces(self):
        strokes = [_seg(100, 100 + k * 1.14, 100 + 1.7 * Q, 100 + k * 1.14) for k in range(40)]
        res = build([_draw(WALL, *strokes)])
        self.assertEqual(res["walls"], [])


class RefusedWhereTheScaleDoesNotVerify(unittest.TestCase):

    def test_a_wall_in_an_unverified_viewport_has_no_length(self):
        d, w = tag("P2", 300, 160, leader_to=(300, 100 + 6 * Q))
        sheet = Sheet(VP((0, 0, 2000, 1500), verified=False, refusal="2 of 9 measured dimensions agree"))
        res = build([h_wall(100, 100, 400, 6), d], [w], sheet=sheet)
        self.assertEqual(res["walls"], [])
        self.assertEqual(res["by_type"], {})
        self.assertEqual(len(res["refused_viewports"]), 1)
        self.assertIn("scale not verified", res["refused_viewports"][0]["why"])
        self.assertIn("2 of 9", res["refused_viewports"][0]["why"])

    def test_each_viewport_is_judged_on_its_own(self):
        d, w = tag("P2", 150, 160, leader_to=(150, 100 + 6 * Q))
        sheet = Sheet(VP((0, 0, 900, 1500)), VP((1000, 0, 2000, 1500), verified=False, title="BULKHEAD"))
        res = build([h_wall(100, 100, 100 + 120 * Q, 6), h_wall(100, 1100, 1400, 6), d], [w], sheet=sheet)
        self.assertEqual(res["by_type"], {"P2": 10.0})
        self.assertEqual([v["title"] for v in res["refused_viewports"]], ["BULKHEAD"])


class AWallWithNoTypeIsRefused(unittest.TestCase):

    def test_an_untyped_wall_is_listed_and_counted_in_no_type(self):
        d, w = tag("P2", 150, 160, leader_to=(150, 100 + 6 * Q))
        res = build([h_wall(100, 100, 100 + 120 * Q, 6), h_wall(600, 100, 100 + 48 * Q, 4), d], [w])
        self.assertEqual(res["by_type"], {"P2": 10.0})
        un = [x for x in res["walls"] if x["status"] == "untyped"]
        self.assertEqual(len(un), 1)
        self.assertEqual(un[0]["lf"], 4.0)
        self.assertEqual(res["untyped_lf"], 4.0)
        self.assertIsNone(un[0]["type"])
        self.assertIn("no wall-type tag", un[0]["why"])


class ATagNamesTheWallItsLeaderEndsIn(unittest.TestCase):

    def test_the_leader_not_the_nearest_wall(self):
        # the diamond sits 20pt from wall A and its leader runs 60pt to wall B
        a = h_wall(100, 100, 400, 4)                    # y 100..106
        b = h_wall(200, 100, 400, 6)                    # y 200..209
        d, w = tag("P2", 250, 130, leader_to=(250, 209))
        res = build([a, b, d], [w])
        p2 = typed(res, "P2")
        self.assertEqual(len(p2), 1)
        self.assertEqual(p2[0]["center_pt"], 204.5)
        self.assertEqual([x["center_pt"] for x in res["walls"] if x["status"] == "untyped"], [103.0])

    def test_a_tag_that_reaches_no_wall_is_listed_unattached(self):
        d, w = tag("W2", 250, 400)
        res = build([h_wall(100, 100, 400, 6), d], [w])
        self.assertEqual(res["by_type"], {})
        self.assertEqual([u["text"] for u in res["unattached"]], ["W2"])

    def test_the_words_in_the_diamond_are_joined(self):
        pw = _pw("read_tags")
        d, _w = tag("W1", 250, 400)
        page = Page([d], [("W", 247.0, 400.0), ("1", 253.0, 400.0)])
        self.assertEqual([t["text"] for t in pw.read_tags(page)], ["W1"])


class OneWallOnlyAcrossAnExplainedJoint(unittest.TestCase):

    def _two(self, door):
        # two collinear 4" pieces with a 36" gap
        left = h_wall(100, 100, 100 + 60 * Q, 4)
        right = h_wall(100, 100 + 96 * Q, 100 + 156 * Q, 4)
        d, w = tag("P3", 150, 160, leader_to=(150, 100 + 4 * Q))
        drawings = [left, right, d]
        if door:
            # the leaf starts at its hinge, in the wall's band
            drawings.append(_draw(DOOR, _seg(100 + 62 * Q, 103, 100 + 62 * Q, 103 + 36 * Q)))
        return build(drawings, [w], door=56.0)

    def test_a_doorway_with_a_door_in_it_joins_the_pieces(self):
        res = self._two(door=True)
        self.assertEqual(res["by_type"], {"P3": 10.0})            # 60" + 60", the door not in it
        self.assertEqual(typed(res, "P3")[0]["opening_lf"], 3.0)
        self.assertEqual(res["untyped_lf"], 0.0)

    def test_a_gap_with_nothing_in_it_does_not(self):
        res = self._two(door=False)
        self.assertEqual(res["by_type"], {"P3": 5.0})
        self.assertEqual(res["untyped_lf"], 5.0)

    def test_a_t_junction_joins_and_its_square_is_counted_once(self):
        # a 6" wall broken where a 4" wall meets it from below
        top_l = h_wall(100, 100, 300, 6)
        top_r = h_wall(100, 306, 500, 6)
        stem = v_wall(300, 109, 400, 4)
        d, w = tag("P2", 150, 60, leader_to=(150, 100))
        res = build([top_l, top_r, stem, d], [w])
        p2 = typed(res, "P2")
        self.assertEqual(len(p2), 1)
        self.assertEqual(p2[0]["lf"], round(400 / Q / 12, 2))      # 100..500, junction included


class ARunTaggedWithTwoTypesIsCutWhereTheTypeChanges(unittest.TestCase):

    def test_one_joint_between_the_tags_is_the_boundary(self):
        # P2 stub | stair wall P1, across one T junction (as on A-100.00)
        a = h_wall(100, 100, 200, 6)
        b = h_wall(100, 209, 600, 6)
        stem = v_wall(200, 109, 300, 6)
        d1, w1 = tag("P2", 150, 60, leader_to=(150, 100))
        d2, w2 = tag("P1", 400, 60, leader_to=(400, 100))
        res = build([a, b, stem, d1, d2], [w1, w2])
        self.assertEqual(len(typed(res, "P2")), 1)
        self.assertEqual(len(typed(res, "P1")), 1)
        self.assertEqual(res["ambiguous_lf"], 0.0)

    def test_two_joints_between_them_refuse_the_middle(self):
        a = h_wall(100, 100, 200, 6)
        b = h_wall(100, 209, 400, 6)
        c = h_wall(100, 409, 700, 6)
        s1, s2 = v_wall(200, 109, 300, 6), v_wall(400, 109, 300, 6)
        d1, w1 = tag("P2", 150, 60, leader_to=(150, 100))
        d2, w2 = tag("P1", 600, 60, leader_to=(600, 100))
        res = build([a, b, c, s1, s2, d1, d2], [w1, w2])
        amb = [x for x in res["walls"] if x["status"] == "ambiguous"]
        self.assertEqual(len(amb), 1)
        self.assertEqual(amb[0]["from_pt"], 209.0)
        self.assertGreater(res["ambiguous_lf"], 0)
        self.assertNotIn(amb[0]["lf"], [x["lf"] for x in typed(res, "P1") + typed(res, "P2")])


class ThePlansReconcileWithTheTypeTable(unittest.TestCase):

    def test_both_ways(self):
        pw = _pw("reconcile")
        r = pw.reconcile({"A-101.00": ["P1", "P2", "W1"], "A-102.00": ["P7"]},
                         {"P1": {}, "P2": {}, "W1": {}, "W6": {}})
        self.assertEqual(r["matched"], ["P1", "P2", "W1"])
        self.assertEqual(r["on_plans_not_in_table"], {"P7": ["A-102.00"]})
        self.assertEqual(r["in_table_not_on_plans"], ["W6"])

    def test_the_table_is_read_from_its_headings(self):
        pw = _pw("partition_types")
        words = [("P1", 85.0, 979.0), ("PARTITION", 140.0, 966.0), ("TYPE", 188.0, 966.0), ("1", 200.0, 966.0),
                 ("INTERIOR", 130.0, 976.0), ("STUD", 170.0, 976.0),
                 ("P2", 409.0, 979.0), ("PARTITION", 464.0, 966.0), ("TYPE", 512.0, 966.0), ("2", 524.0, 966.0),
                 ("W9", 900.0, 500.0)]
        t = pw.partition_types(words)
        self.assertEqual(sorted(t), ["P1", "P2"])
        self.assertEqual(t["P1"]["heading"], "PARTITION TYPE 1")
        self.assertEqual(t["P1"]["description"], "INTERIOR STUD")
        self.assertTrue(t["P2"]["consistent"])


class AFloorIsWhatItsTitleNames(unittest.TestCase):

    def test_titles(self):
        pw = _pw("floor_of")
        self.assertEqual(pw.floor_of("SECOND FLOOR PLAN"), "FLOOR_2")
        self.assertEqual(pw.floor_of("MEZZANINE PLAN"), "MEZZANINE")
        self.assertIsNone(pw.floor_of("FLOOR PLAN"))
        self.assertIsNone(pw.floor_of(""))


# ── 588 Boyland, from the fixture PDFs ─────────────────────────────────────

_CACHE = {}


def _boyland(name, page):
    key = (name, page)
    if key not in _CACHE:
        pw = _pw("floor_walls")
        from lib.plan_page import PlanPage
        pg = PlanPage(str(require_pdf(name)), page)
        _CACHE[key] = (pw.floor_walls(pg, widest_door_in=56.0), pg)
    return _CACHE[key][0]


class FiledSecondFloor(unittest.TestCase):
    """AR 3.28.25 A-101.00 (page 12): every check is a printed dimension."""

    def setUp(self):
        self.r = _boyland("AR - 3.28.25.pdf", 12)

    def test_the_plan_verifies_and_nothing_is_refused(self):
        self.assertTrue(all(v["verified"] for v in self.r["viewports"]), self.r["viewports"])
        self.assertEqual(self.r["refused_viewports"], [])

    def test_the_side_walls_are_the_building_depth_less_the_long_walls(self):
        # printed 35'-8" BUILDING, less two W2 walls drawn 11" thick
        w1 = typed(self.r, "W1")
        self.assertEqual(len(w1), 2)
        for w in w1:
            self.assertAlmostEqual(w["lf"], 35 + 8 / 12 - 2 * 11 / 12, delta=0.05)
            self.assertEqual(w["thick_in"], 10.0)

    def test_the_long_walls_are_the_building_length_less_the_side_walls(self):
        # printed 70'-0" BUILDING, less two W1 walls drawn 10" thick
        w2 = typed(self.r, "W2")
        self.assertEqual(len(w2), 2)
        for w in w2:
            self.assertAlmostEqual(w["lf"], 70 - 2 * 10 / 12, delta=0.05)

    def test_the_demising_wall_is_its_printed_28_4(self):
        p2 = [w for w in typed(self.r, "P2") if w["axis"] == "h"]
        self.assertEqual([round(w["lf"], 2) for w in p2], [28.33, 28.0])

    def test_the_bath_wall_is_two_8_0_rooms_the_wall_between_and_its_heads(self):
        # 8'-0" bath + 6" P2 + 8'-0" bath = 16'-6" between the rooms' faces,
        # and at each end the 4" head it carries between the bath and the
        # bedroom doors (by eye, T1/ov_a101_bathtop.png): 16'-6" + 2 x 4"
        p3v = sorted(round(w["lf"], 2) for w in typed(self.r, "P3") if w["axis"] == "v" and w["lf"] > 10)
        self.assertEqual(p3v, [17.17, 17.17])

    def test_a_bedroom_wall_stops_at_its_door_and_never_crosses_the_stair(self):
        # each bedroom's P3 wall runs 11'-2" from the W1 face to its door; a
        # door object's whole-path rectangle once joined it to the far
        # bedroom's, 29 feet away across the stair
        p3h = [w["lf"] for w in typed(self.r, "P3") if w["axis"] == "h"]
        self.assertEqual(p3h.count(11.17), 4, p3h)
        self.assertLess(max(p3h), 12)

    def test_the_stairs_middle_wall_carries_no_tag_and_is_refused(self):
        un = [w for w in self.r["walls"] if w["status"] == "untyped"]
        self.assertIn(12.5, [w["lf"] for w in un])
        self.assertNotIn(None, self.r["by_type"])
        self.assertGreater(self.r["untyped_lf"], 0)

    def test_every_tag_on_the_plan_is_an_a500_type(self):
        pw = _pw("partition_types", "reconcile")
        from lib.plan_page import PlanPage
        table = pw.partition_types(PlanPage(str(require_pdf("AR - 3.28.25.pdf")), 24).words)
        self.assertEqual(sorted(table), ["P1", "P2", "P3", "P4", "P5", "P6",
                                         "W1", "W2", "W3", "W4", "W5", "W6"])
        rec = pw.reconcile({"A-101.00": self.r["types_on_plan"]}, table)
        self.assertEqual(rec["on_plans_not_in_table"], {})
        self.assertEqual(rec["matched"], ["P1", "P2", "P3", "P4", "W1", "W2"])


class OwnersThirdFloor(unittest.TestCase):
    """The owner's post-CO A-102.00 prints only the exterior walls' tags: its
    interior partitions are untyped, never given a type."""

    def test_only_w1_and_w2_are_typed(self):
        r = _boyland("Owners set - 6.9.26.pdf", 3)
        self.assertEqual(sorted(r["by_type"]), ["W1", "W2"])
        self.assertGreater(r["untyped_lf"], 200)


if __name__ == "__main__":
    unittest.main()
