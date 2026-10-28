"""A plumbing stack is the pipe its split-circle tag's leader points at, placed
on the architectural plan its sheet is paired with BY TITLE LEVEL (lane T4,
Roy 2026-10-28; lib.plan_stacks).

  * LOCATE: a split-circle tag (a circle cut by its horizontal diameter,
    lettering in both halves) on the sheet's OWN layers; each leader leaving
    it at the diameter's height and ending on an arrowhead; the stack is the
    pipe circle on a P-Pipe-* layer the arrow points at - a closed circle,
    an open three-quarter one (a riser turning down), or two arcs facing
    each other across the pipe that trims them. An arrow that points at no
    pipe circle is a row that says so; a tag with no leader is a row; the
    legend's sample tag (an xref layer) is not a tag.
  * READ: the lettering is SHX strokes. Reads are voted per glyph (same
    strokes, same glyph): a label needs twice any rival's votes and half
    the renderings, else the tag is unread - never the likeliest guess.
  * PAIR: floor identity from the sheet number and the title level ONLY
    (operator rule 2026-10-26). Same single level in both titles, and the
    series' majority number offset; a sheet that breaks it, or whose title
    names no level or two, refuses.
  * REGISTER: the offset of a decided pair, used only when register()
    accepts it AND no second offset holds half the best peak's anchors.
  * PLACE: a stack in a wall names BOTH sides; the footprint is a circle in
    architectural page points, the form clash v1 (lane C1) reads.
  * CROSS-CHECK: every ID the plans tag against every ID the riser diagrams
    tag; each mismatch listed.

WRITTEN TO FAIL BY ASSERTION ON A TREE WITHOUT THE CHANGE: every test
reaches lib.plan_stacks through `_ps()`, which turns a missing module or
name into an AssertionError.
"""
from __future__ import annotations

import importlib
import math
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

K = 0.5522847498


def _ps(*names):
    try:
        mod = importlib.import_module("lib.plan_stacks")
    except ImportError as e:
        raise AssertionError(f"lib.plan_stacks is not importable: {e}")
    for n in names:
        assert hasattr(mod, n), f"lib.plan_stacks has no {n}"
    return mod


# ── a drawing, built the way pypdfium hands one to lib.plan_page ──────────

def _rect(items):
    pts = [p for it in items for p in it[1:]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _path(items, layer):
    return {"items": items, "layer": layer, "rect": _rect(items), "colour": (0, 0, 0)}


def _arc(cx, cy, r, a0, a1):
    """One cubic for a quarter (or less) of a turn, a0 -> a1 radians."""
    k = 4 / 3 * math.tan((a1 - a0) / 4)
    p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
    p3 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
    c1 = (p0[0] - k * r * math.sin(a0), p0[1] + k * r * math.cos(a0))
    c2 = (p3[0] + k * r * math.sin(a1), p3[1] - k * r * math.cos(a1))
    return ("c", p0, c1, c2, p3)


def _circle(cx, cy, r, layer, quarters=4, start=0.0):
    q = math.pi / 2
    return _path([_arc(cx, cy, r, start + i * q, start + (i + 1) * q) for i in range(quarters)], layer)


def _line(a, b, layer):
    return _path([("l", a, b)], layer)


def _poly(pts, layer):
    return _path([("l", a, b) for a, b in zip(pts, pts[1:])], layer)


class _Page:
    def __init__(self, drawings, width=2592.0, height=1728.0):
        self.drawings = drawings
        self.width, self.height = width, height


R = 11.3          # the tag's radius on the PL set (22.6pt across)


def _tag(cx, cy, layer="P-TEXT", letter_strokes=None, number_strokes=None):
    """A split circle with a V above the diameter and a 3 below, as strokes."""
    top = letter_strokes or [_poly([(cx - 2, cy - 8), (cx, cy - 2.5), (cx + 2, cy - 8)], layer)]
    bot = number_strokes or [_poly([(cx - 2, cy + 2.5), (cx + 2, cy + 2.5), (cx, cy + 5),
                                    (cx + 2, cy + 7.5), (cx - 2, cy + 8.5)], layer)]
    return [_circle(cx, cy, R, layer), _line((cx - R, cy), (cx + R, cy), layer)] + top + bot


def _leader(start, corner, end, layer="10 TEXT", head=6.0):
    """A leader start -> corner -> a point level with `end` -> end, and an
    arrowhead whose BASE sits on `end` and whose tip is `head` further
    along the last (horizontal) run."""
    bend = (corner[0], end[1])
    ux, uy = (1.0 if end[0] >= bend[0] else -1.0), 0.0
    tip = (end[0] + head * ux, end[1])
    b1, b2 = (end[0], end[1] - 1.2), (end[0], end[1] + 1.2)
    return [_poly([start, corner, bend, end], layer), _poly([b1, tip, b2, b1], layer)], tip


def _sheet_with_one_stack(gap=1.0, aim=(0.0, 0.0), arrow=True, pipe_layer="P-Pipe-Sswr-Vent",
                          pipe=None):
    """A tag at (400, 400); its leader leaves the rim at the diameter's
    height, runs right and down to an arrow at a 4.5pt vent circle at
    (470, 350) (plus `aim`, to make the arrow miss)."""
    cx, cy = 400.0, 400.0
    pc = (470.0, 350.0)
    end = (pc[0] - 2.25 - 6.0, pc[1])                    # the head's tip on the rim
    lead, _tip = _leader((cx + R + gap, cy), (430.0, cy), (end[0] + aim[0], end[1] + aim[1]))
    if not arrow:
        lead = lead[:1]
    pipes = pipe if pipe is not None else [_circle(pc[0], pc[1], 2.25, pipe_layer)]
    return _Page(_tag(cx, cy) + lead + pipes), pc


# ── locate ─────────────────────────────────────────────────────────────────

class LocateTheStack(unittest.TestCase):

    def test_the_stack_is_the_pipe_circle_the_arrow_points_at(self):
        PS = _ps("locate")
        page, pc = _sheet_with_one_stack()
        got = PS.locate(page)
        self.assertEqual(len(got["tags"]), 1)
        (ld,) = got["tags"][0]["leaders"]
        self.assertIsNotNone(ld["stack"], ld["why"])
        self.assertAlmostEqual(ld["stack"]["x"], pc[0], places=1)
        self.assertAlmostEqual(ld["stack"]["y"], pc[1], places=1)
        self.assertEqual(ld["stack"]["systems"], ["vent"])

    def test_a_leader_may_leave_the_rim_with_the_pens_gap(self):
        PS = _ps("locate")
        page, _pc = _sheet_with_one_stack(gap=3.0)          # W-4 on P-103.00: 3.0pt
        (t,) = PS.locate(page)["tags"]
        self.assertEqual(len(t["leaders"]), 1)

    def test_an_arrow_that_misses_every_pipe_says_so(self):
        PS = _ps("locate")
        page, _pc = _sheet_with_one_stack(aim=(0.0, -15.0))
        (t,) = PS.locate(page)["tags"]
        (ld,) = t["leaders"]
        self.assertIsNone(ld["stack"])
        self.assertIn("points at no pipe circle", ld["why"])

    def test_a_line_with_no_arrowhead_is_not_a_leader_and_is_counted(self):
        PS = _ps("locate")
        page, _pc = _sheet_with_one_stack(arrow=False)
        (t,) = PS.locate(page)["tags"]
        self.assertEqual(t["leaders"], [])
        self.assertEqual(t["unterminated"], 1)

    def test_a_circle_on_a_layer_that_is_not_a_pipe_is_not_a_stack(self):
        PS = _ps("locate")
        page, _pc = _sheet_with_one_stack(pipe_layer="P-Fixt-Text")
        (t,) = PS.locate(page)["tags"]
        self.assertIsNone(t["leaders"][0]["stack"])

    def test_the_legends_sample_tag_on_an_xref_layer_is_not_a_tag(self):
        PS = _ps("locate")
        page = _Page(_tag(300, 300, layer="X-(24X36)-(P-200) Sanitary & Storm Notes|P-TEXT"))
        self.assertEqual(PS.locate(page)["tags"], [])

    def test_a_circle_without_its_diameter_is_not_a_split_circle_tag(self):
        PS = _ps("locate")
        drawn = [d for d in _tag(300, 300) if not (len(d["items"]) == 1
                                                   and d["items"][0][1][1] == 300
                                                   and d["items"][0][2][1] == 300)]
        self.assertEqual(PS.locate(_Page(drawn))["tags"], [])

    def test_a_tag_in_the_title_block_is_not_a_tag(self):
        PS = _ps("locate")
        rule = _line((2300.0, 20.0), (2300.0, 1700.0), "0")      # the title block's rule
        page = _Page(_tag(2400, 100) + [rule])
        self.assertEqual(PS.locate(page)["tags"], [])

    def test_one_tag_with_two_leaders_is_two_stacks(self):
        PS = _ps("locate")
        cx, cy = 400.0, 400.0
        a, _ = _leader((cx + R, cy), (430.0, cy), (470 - 2.25 - 6, 350.0), layer="P-TEXT - CW")
        b, _ = _leader((cx + R, cy), (430.0, cy), (470 - 2.25 - 6, 450.0), layer="P-TEXT - CW")
        pipes = [_circle(470, 350, 2.25, "P-Pipe-Domc-Sply"), _circle(470, 450, 2.25, "P-Pipe-Domh-Sply")]
        (t,) = PS.locate(_Page(_tag(cx, cy) + a + b + pipes))["tags"]
        got = sorted((round(l["stack"]["y"]), l["stack"]["systems"][0]) for l in t["leaders"])
        self.assertEqual(got, [(350, "cold water"), (450, "hot water")])


class APipeSeenEndOn(unittest.TestCase):

    def _stack(self, pipe):
        PS = _ps("locate")
        page, pc = _sheet_with_one_stack(pipe=pipe)
        (t,) = PS.locate(page)["tags"]
        return t["leaders"][0]["stack"], pc

    def test_an_open_three_quarter_circle_is_a_riser_turning_down(self):
        st, pc = self._stack([_circle(470, 350, 2.25, "P-Pipe-Domh-Sply", quarters=3, start=math.pi / 2)])
        self.assertIsNotNone(st)
        self.assertEqual(st["drawn"], "open")

    def test_two_arcs_facing_each_other_are_a_circle_trimmed_by_its_pipe(self):
        q = math.pi / 2
        top = _path([_arc(470, 350, 2.25, -q - 0.75, -q + 0.75)], "P-Pipe-Domc-Sply")
        bot = _path([_arc(470, 350, 2.25, q - 0.75, q + 0.75)], "P-Pipe-Domc-Sply")
        st, _pc = self._stack([top, bot])
        self.assertIsNotNone(st)

    def test_a_ninety_degree_bend_is_not_a_pipe_seen_end_on(self):
        st, _pc = self._stack([_path([_arc(470, 350, 2.25, math.pi / 2, math.pi)], "P-Pipe-Sswr-Dran")])
        self.assertIsNone(st)

    def test_a_polygon_circle_with_its_pipe_in_one_path_is_a_riser(self):
        # P-100.00: 33 straight pieces round, and the pipe leaving it, one path
        n = 33
        ring = [(470 + 2.25 * math.cos(2 * math.pi * i / n), 350 + 2.25 * math.sin(2 * math.pi * i / n))
                for i in range(n + 1)]
        tail = [(472.25, 350.0), (480.0, 350.0)]
        st, _pc = self._stack([_poly(ring + tail, "P-Pipe-Domc-Sply")])
        self.assertIsNotNone(st)


# ── read ───────────────────────────────────────────────────────────────────

def _width(png):
    import io
    from PIL import Image
    return Image.open(io.BytesIO(png)).width


class ReadTheTag(unittest.TestCase):

    def test_a_label_needs_twice_any_rival_and_half_the_renderings(self):
        PS = _ps("vote")
        self.assertEqual(PS.vote(["3", "3", "3", "5", None, "7", "3", None], 8)[0], "3")
        self.assertIsNone(PS.vote(["3", "5", "3", "5"], 4)[0])            # contested
        self.assertIsNone(PS.vote(["3", None, None, None, None], 5)[0])    # too few reads

    def test_halves_with_the_same_strokes_vote_together(self):
        PS = _ps("locate", "read_tags")
        a = PS.locate(_Page(_tag(300, 300)))["tags"]
        b = PS.locate(_Page(_tag(900, 700)))["tags"]
        calls = {"n": 0}

        def reader(png):
            # the first tag's four renderings read 3; the second's read 5, 5,
            # nothing, 3 - alone it would be V-5 (2 votes to 1), but it prints
            # the same 3 as the first, and pooled the 3 wins (5 to 2)
            calls["n"] += 1
            n = calls["n"]
            w = _width(png)        # the letter's slot, then the digit's (plan_stacks._layout)
            digit = {5: "5", 6: "5", 7: None}.get(n, "3")
            return [(0.2 * w, 10, "V", 0.9)] + ([(0.55 * w, 10, digit, 0.6)] if digit else [])
        PS.read_tags(a + b, reader)
        self.assertEqual([t["id"] for t in a + b], ["V-3", "V-3"])

    def test_a_contested_glyph_leaves_the_tag_unread(self):
        PS = _ps("locate", "read_tags")
        tags = PS.locate(_Page(_tag(300, 300)))["tags"]
        flip = iter(["3", "5", "3", "5"])
        PS.read_tags(tags, lambda png: [(0.2 * _width(png), 10, "V", 0.9),
                                        (0.55 * _width(png), 10, next(flip), 0.6)])
        self.assertIsNone(tags[0]["id"])
        self.assertIn("contested", tags[0]["read_why"])

    def test_a_dash_is_read_from_its_stroke_not_from_ocr(self):
        """V-1-2 (one vent through the roof for stacks 1 and 2): OCR reads
        the bottom "12" whatever it is shown; the dash is a stroke."""
        PS = _ps("locate", "read_tags")
        cx, cy = 300.0, 300.0
        one = _poly([(cx - 6, cy + 3.5), (cx - 5, cy + 2.5), (cx - 5, cy + 8.5)], "P-TEXT")
        dash = _line((cx - 2.5, cy + 5.5), (cx + 1.5, cy + 5.5), "P-TEXT")
        two = _poly([(cx + 3, cy + 3), (cx + 6, cy + 3), (cx + 3, cy + 8.5), (cx + 6, cy + 8.5)], "P-TEXT")
        tags = PS.locate(_Page(_tag(cx, cy, number_strokes=[one, dash, two])))["tags"]
        PS.read_tags(tags, lambda png: [(0.1 * _width(png), 10, "V", 0.9),
                                        (0.6 * _width(png), 10, "12", 0.9)])
        self.assertEqual(tags[0]["id"], "V-1-2")

    def test_a_size_is_read_off_the_note(self):
        PS = _ps("printed_size")
        self.assertEqual(PS.printed_size('4" UP (72 GPM)'), '4"')
        self.assertEqual(PS.printed_size("1” DHW UP&DN"), '1"')
        self.assertIsNone(PS.printed_size("UP&DN"))


# ── pair ───────────────────────────────────────────────────────────────────

def _pg(num, title):
    return {"sheet_number": num, "sheet_title": title, "page_id": num}


ARCH = [_pg("A-100.01", "FIRST FLOOR PLAN"), _pg("A-101.00", "SECOND FLOOR PLAN"),
        _pg("A-102.00", "THIRD FLOOR PLAN"), _pg("A-103.00", "FOURTH FLOOR PLAN"),
        _pg("A-104.00", "MEZZANINE PLAN"), _pg("A-105.01", "ROOF AND BULKHEAD PLAN")]
P2 = [_pg("P-201.00", "FIRST FLOOR SANITARY & STORM PLAN"),
      _pg("P-202.00", "SECOND FLOOR SANITARY & STORM PLAN"),
      _pg("P-203.00", "THIRD FLOOR SANITARY & STORM PLAN"),
      _pg("P-204.00", "FOURTH FLOOR SANITARY & STORM PLAN"),
      _pg("P-205.00", "MEZZANINE FLOOR SANITARY & STORM PLAN")]


class PairByTitleLevel(unittest.TestCase):

    def test_p204_pairs_with_the_fourth_floor_not_with_a104(self):
        PS = _ps("pair_by_title_level")
        got = PS.pair_by_title_level(P2, ARCH)
        pairs = {p["sheet_number"]: (a["sheet_number"], o) for p, a, o in got["pairs"]}
        self.assertEqual(pairs["P-204.00"], ("A-103.00", 1))
        self.assertEqual(got["series"]["P-2"]["offset"], 1)
        self.assertEqual(len(pairs), 5)

    def test_a_sheet_that_breaks_the_series_offset_refuses(self):
        PS = _ps("pair_by_title_level")
        odd = P2[:3] + [_pg("P-204.00", "THIRD FLOOR SANITARY & STORM PLAN")] + P2[4:]
        got = PS.pair_by_title_level(odd[:3] + odd[4:] + [odd[3]], ARCH)
        refused = dict((p["sheet_number"], w) for p, w in got["refused"])
        # P-203 and P-204 both claim the third floor: P-203 holds +1, P-204 is +2
        self.assertIn("P-204.00", refused)
        self.assertIn("+2", refused["P-204.00"])
        self.assertNotIn("P-204.00", [p["sheet_number"] for p, _a, _o in got["pairs"]])

    def test_a_title_naming_no_level_or_two_refuses(self):
        PS = _ps("pair_by_title_level")
        # P-202 titled for two floors: the level table alone reads it as the
        # SECOND floor, and the series offset (+1 to A-101) would hold
        two = [p if p["sheet_number"] != "P-202.00"
               else _pg("P-202.00", "FIRST & SECOND FLOOR SANITARY & STORM PLAN") for p in P2]
        got = PS.pair_by_title_level(
            [_pg("P-200.00", "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN")] + two, ARCH)
        refused = dict((p["sheet_number"], w) for p, w in got["refused"])
        self.assertIn("names no level", refused["P-200.00"])
        self.assertIn("does not name one floor", refused["P-202.00"])
        self.assertEqual(len(got["pairs"]), 4)

    def test_a_level_no_architectural_plan_is_titled_at_refuses(self):
        PS = _ps("pair_by_title_level")
        got = PS.pair_by_title_level(P2 + [_pg("P-207.00", "BULKHEAD SANITARY & STORM PLAN")], ARCH)
        refused = dict((p["sheet_number"], w) for p, w in got["refused"])
        self.assertIn("0 architectural plans titled at level BULKHEAD", refused["P-207.00"])

    def test_a_series_with_no_majority_offset_refuses_every_sheet(self):
        PS = _ps("pair_by_title_level")
        two = [_pg("P-201.00", "FIRST FLOOR SANITARY PLAN"), _pg("P-203.00", "SECOND FLOOR SANITARY PLAN")]
        got = PS.pair_by_title_level(two, ARCH)
        self.assertEqual(got["pairs"], [])
        self.assertEqual(len(got["refused"]), 2)

    def test_registration_fit_never_enters_the_pairing(self):
        PS = _ps("pair_by_title_level")
        import inspect
        src = inspect.getsource(PS.pair_by_title_level)
        self.assertNotIn("register", src.split('"""')[2])


# ── register ───────────────────────────────────────────────────────────────

class RegistrationThatCanFail(unittest.TestCase):

    def _reg(self, **kw):
        base = {"usable": True, "refused": None, "best_peak_anchors": 1700, "dx": 10.0, "dy": -20.0}
        base.update(kw)
        return base

    def test_usable_when_register_accepts_and_the_peak_stands_alone(self):
        PS = _ps("registration_usable")
        self.assertTrue(PS.registration_usable(self._reg(), 400)[0])

    def test_refused_when_register_refuses(self):
        PS = _ps("registration_usable")
        ok, why = PS.registration_usable(self._reg(usable=False, refused="only 3 anchors"), 400)
        self.assertFalse(ok)
        self.assertIn("only 3 anchors", why[0])

    def test_refused_when_a_second_offset_holds_half_the_best(self):
        PS = _ps("registration_usable")
        ok, why = PS.registration_usable(self._reg(), 851)
        self.assertFalse(ok)
        self.assertIn("ambiguous", why[0])

    def test_refused_when_the_second_peak_was_not_measured(self):
        PS = _ps("registration_usable")
        self.assertFalse(PS.registration_usable(self._reg(), None)[0])


class RegisterReportsItsSecondPeak(unittest.TestCase):
    """register() records how nearly ANOTHER offset fits; the stack pass
    refuses an offset another one nearly matches. Both on a synthetic pair:
    200 corners at the true offset, a decoy set of k of them again 30pt off."""

    def _pair(self, k):
        import numpy as np
        rng = np.random.default_rng(11)
        A = np.round(rng.uniform([0, 0], [1200, 700], size=(200, 2)), 2)
        true = np.array([40.0, -30.0])
        B = np.vstack([A + true, A[:k] + true + np.array([30.0, 0.0])])
        att = [((A[:, 0].min(), A[:, 1].min(), A[:, 0].max(), A[:, 1].max()), "A-WALL")]
        return {"corners": A, "att": att}, {"corners": B, "att": []}

    def test_a_lone_peak_is_usable(self):
        PS = _ps("registration_usable")
        from lib import plan_sheet
        reg = plan_sheet.register(*self._pair(40))
        self.assertIn("second_peak_anchors", reg)
        self.assertGreaterEqual(reg["second_peak_anchors"], 40)
        self.assertLess(reg["second_peak_anchors"], 100)
        self.assertTrue(PS.registration_usable(reg)[0], reg)

    def test_a_decoy_holding_over_half_the_best_refuses(self):
        PS = _ps("registration_usable")
        from lib import plan_sheet
        reg = plan_sheet.register(*self._pair(150))
        self.assertTrue(reg["usable"], "register() alone accepts it")
        ok, why = PS.registration_usable(reg)
        self.assertFalse(ok)
        self.assertIn("ambiguous", why[0])


# ── rows ───────────────────────────────────────────────────────────────────

def _located_tag(PS, letter="V", number="3"):
    page, pc = _sheet_with_one_stack()
    (t,) = PS.locate(page)["tags"]
    t.update(letter=letter, number=number, id=f"{letter}-{number}", read_why="test")
    return t, pc


class TheRowsC1Reads(unittest.TestCase):

    def test_a_placed_stack_is_a_circle_in_architectural_points(self):
        PS = _ps("stack_rows", "locate")
        t, pc = _located_tag(PS)
        reg = {"dx": -25.5, "dy": -66.0, "anchors": 1719, "best_peak_anchors": 1719,
               "second_peak_anchors": 413, "rms_in": 0.07, "max_in": 0.8}
        (row,) = PS.stack_rows("filed", _pg("P-204.00", "x"), _pg("A-103.00", "y"), [t], reg, True, [])
        self.assertEqual(row["status"], "located")
        fp = row["footprint_arch"]
        self.assertEqual(fp["type"], "circle")
        self.assertAlmostEqual(fp["x"], pc[0] + 25.5, places=1)
        self.assertAlmostEqual(fp["y"], pc[1] + 66.0, places=1)
        self.assertAlmostEqual(fp["r"], 2.25, places=1)
        self.assertEqual(row["arch_sheet"], "A-103.00")
        self.assertEqual(row["tag_id"], "V-3")

    def test_an_unusable_registration_keeps_the_stack_and_refuses_its_place(self):
        PS = _ps("stack_rows", "locate")
        t, _pc = _located_tag(PS)
        (row,) = PS.stack_rows("filed", _pg("P-204.00", "x"), _pg("A-103.00", "y"), [t],
                               {"dx": 0, "dy": 0}, False, ["a second offset holds 900 anchors"])
        self.assertEqual(row["status"], "located")
        self.assertIsNone(row["footprint_arch"])
        self.assertIn("900 anchors", row["placement_refused"])

    def test_an_unpaired_sheet_keeps_its_stacks_and_says_why(self):
        PS = _ps("stack_rows", "locate")
        t, _pc = _located_tag(PS)
        (row,) = PS.stack_rows("filed", _pg("P-207.00", "x"), None, [t], None, False, [],
                               refused="P-207.00: 0 architectural plans titled at level BULKHEAD")
        self.assertIsNone(row["footprint_arch"])
        self.assertIn("BULKHEAD", row["placement_refused"])

    def test_a_tag_with_no_stack_is_a_row(self):
        PS = _ps("stack_rows", "locate")
        page, _pc = _sheet_with_one_stack(aim=(0.0, -15.0))
        (t,) = PS.locate(page)["tags"]
        t.update(letter="S", number="4", id="S-4", read_why="test")
        (row,) = PS.stack_rows("filed", _pg("P-201.00", "x"), _pg("A-100.01", "y"), [t],
                               {"dx": 0, "dy": 0}, True, [])
        self.assertEqual(row["status"], "no_stack")
        self.assertIsNotNone(row["leader_tip"])

    def test_a_letter_that_disagrees_with_the_pipe_is_a_finding(self):
        PS = _ps("stack_rows", "locate")
        t, _pc = _located_tag(PS, letter="S", number="1")      # S on a vent circle
        (row,) = PS.stack_rows("filed", _pg("P-204.00", "x"), _pg("A-103.00", "y"), [t],
                               {"dx": 0, "dy": 0}, True, [])
        self.assertTrue(row["findings"])


class ThePassKeepsWhatItCannotPlace(unittest.TestCase):

    def test_a_sheet_whose_title_names_no_level_keeps_its_stacks_with_the_reason(self):
        PS = _ps("run_stacks")
        page, _pc = _sheet_with_one_stack()
        p = {"sheet_number": "P-200.00", "sheet_title": "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN",
             "page_id": "p200", "file_name": "PL.pdf", "page_number": 8}
        a = {"sheet_number": "A-100.01", "sheet_title": "FIRST FLOOR PLAN", "page_id": "a100"}
        w = _width

        def reader(png):
            return [(0.2 * w(png), 10, "V", 0.9), (0.55 * w(png), 10, "3", 0.9)]
        got = PS.run_stacks([("filed", [p, a])], lambda pg: page, reader=reader, place=False)
        (row,) = [r for r in got["rows"] if r.get("record_type") == "stack"]
        self.assertEqual(row["status"], "located")
        self.assertIsNone(row["footprint_arch"])
        self.assertIn("names no level", row["placement_refused"])
        self.assertEqual(row["tag_id"], "V-3")


class AStackInAWallNamesBothSides(unittest.TestCase):

    def test_a_wet_wall_between_two_units_is_both_units(self):
        PS = _ps("where")
        import numpy as np
        from lib.plan_takeoff import Units
        g = np.zeros((40, 40), dtype=bool)
        g[:, 19:21] = True                                  # a wall down the middle
        left = np.zeros_like(g)
        left[:, :19] = True
        right = np.zeros_like(g)
        right[:, 21:] = True
        st = {"grid": g, "closed_lab": None, "public": None, "outdoors": set()}
        u = Units({"4C": left, "4D": right}, (0.0, 0.0), 3.0, (), st,
                  {"4C": (10.0, 60.0), "4D": (110.0, 60.0)})
        where, how = PS.where(u, 60.0, 60.0)               # cell column 20: in the wall
        self.assertEqual(where, "wall: 4D | 4C")
        self.assertIn("both ways", how)
        self.assertEqual(PS.where(u, 10.0, 60.0)[0], "4C")


# ── cross-check ────────────────────────────────────────────────────────────

class RiserCrossCheck(unittest.TestCase):

    def test_every_mismatch_is_listed(self):
        PS = _ps("crosscheck")
        got = PS.crosscheck({"P-203.00": ["S-1", "V-1", "V-3", None], "P-204.00": ["S-1", "V-3"]},
                            {"P-301.00": ["S-1", "V-2", "V-1-2"]})
        self.assertEqual(got["on_plans_not_riser"], ["V-3"])
        self.assertEqual(got["on_riser_not_plans"], ["V-2"])
        self.assertEqual(got["unread"], [("P-203.00", 1)])
        self.assertEqual(got["ids"]["S-1"]["plans"], [["P-203.00", 1], ["P-204.00", 1]])

    def test_a_combined_vent_tag_names_each_stack(self):
        PS = _ps("expand_id")
        self.assertEqual(PS.expand_id("V-1-2"), ["V-1", "V-2"])
        self.assertEqual(PS.expand_id("ST-1"), ["ST-1"])
        self.assertEqual(PS.expand_id(None), [])


if __name__ == "__main__":
    unittest.main()


# ── the glyph pass writes them ─────────────────────────────────────────────

class TheGlyphPassWritesThem(unittest.TestCase):
    """The caller: server._plan_glyph_pass (POST .../plan-glyphs/run, an
    operator action) runs lib.plan_stacks.run_stacks while the PDFs are
    fetched and writes its rows to their own collection. A failure writes
    one marker row - an empty collection never reads as "no stacks"."""

    def _pass(self, run_stacks):
        _ps("run_stacks", "COLLECTION")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "smoke_test")
        os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
        from unittest.mock import patch
        import asyncio
        import server
        from async_fake_mongo import AsyncFakeDB
        from tests.test_two_drawing_tracks import _raw
        from bson import ObjectId
        db = AsyncFakeDB()
        proj = ObjectId()
        raw, files = _raw()
        for k, f in files.items():
            db.project_files.docs.append(dict(f, _id=k, project_id=str(proj), is_deleted=False))
        for pg in raw:
            db.document_page_index.docs.append(dict(pg, project_id=str(proj)))

        def fake_pass(pages, open_page, schedules, door_pages, track="filed", sweeps=None,
                      plan_only=None):
            return {"rows": [], "summary": {}}

        async def live(_pid):
            return list(files)

        async def write(_pid, rows):
            return len(rows)
        seen = {}

        def spy(tracks, open_page, reader=None, door_inches=None, place=True):
            seen["tracks"] = [t for t, _p in tracks]
            return run_stacks()
        with patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live),                 patch("lib.plan_glyph_pass.run_pass", fake_pass),                 patch.object(server, "_glyph_set_health", lambda *a, **k: []),                 patch.object(server, "_write_glyph_records", write),                 patch("lib.plan_stacks.run_stacks", spy):
            summary = asyncio.run(server._plan_glyph_pass(str(proj)))
        from lib.plan_stacks import COLLECTION
        return summary, db[COLLECTION].docs, seen, str(proj)

    def test_every_track_is_handed_over_and_the_rows_are_stored(self):
        row = {"record_type": "stack", "tag_id": "V-3", "status": "located",
               "footprint_arch": {"type": "circle", "x": 1630.3, "y": 736.3, "r": 2.25}}
        summary, docs, seen, pid = self._pass(lambda: {"rows": [row], "crosscheck": {}, "pairing": {},
                                                       "summary": {}, "riser_tags": []})
        self.assertEqual(seen.get("tracks"), ["filed", "post_co"])
        self.assertEqual(summary.get("stacks_written"), 2)
        kinds = sorted(d["record_type"] for d in docs)
        self.assertEqual(kinds, ["stack", "stack_crosscheck"])
        self.assertTrue(all(d["project_id"] == pid for d in docs))

    def test_a_failed_stack_pass_writes_one_marker(self):
        def boom():
            raise RuntimeError("tag read failed")
        summary, docs, _seen, _pid = self._pass(boom)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["status"], "unavailable")
        self.assertIn("stack pass unavailable: RuntimeError", docs[0]["reason"])


# ── on the 588 Boyland set (fixture PDFs; skipped, with where it looked, without them) ──

#: the production index's titles (find()-only probe 2026-10-28)
BOYLAND_A_FILED = [_pg("A-100.01", "FIRST FLOOR PLAN"), _pg("A-101.00", "SECOND FLOOR PLAN"),
                   _pg("A-102.00", "THIRD FLOOR PLAN"), _pg("A-103.00", "FOURTH FLOOR PLAN"),
                   _pg("A-104.00", "MEZZANINE PLAN"), _pg("A-105.01", "ROOF AND BULKEAD PLAN")]
BOYLAND_P2 = [_pg("P-200.00", "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN")] + P2 + [
    _pg("P-206.00", "ROOF SANITARY & STORM PLAN"), _pg("P-207.00", "BULKHEAD SANITARY & STORM PLAN")]


class OnTheBoylandSet(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from tests.fixture_pdfs import require as require_pdf
        cls.pl = str(require_pdf("PL - 6.29.26.pdf"))
        cls.ar = str(require_pdf("AR - 3.28.25.pdf"))

    def _locate(self, page):
        PS = _ps("locate")
        from lib.plan_page import PlanPage
        pg = PlanPage(self.pl, page)
        try:
            return PS.locate(pg)
        finally:
            pg.close()

    def test_p204_locates_a_stack_at_every_leader(self):
        got = self._locate(12)
        tags = got["tags"]
        self.assertEqual(len(tags), 10)
        stacks = [l["stack"] for t in tags for l in t["leaders"]]
        self.assertEqual(len(stacks), 10)
        self.assertTrue(all(stacks), [l["why"] for t in tags for l in t["leaders"]])

    def test_p204s_wet_wall_vents_are_where_sw1_stands(self):
        """The C1 benchmark: the vent stacks at the 4C/4D bath wet wall, on
        the vent layer, at the points the 2026-10-10 overlay found inside
        SW 1's braced frame."""
        got = self._locate(12)
        at = {(round(l["stack"]["x"], 1), round(l["stack"]["y"], 1)): l["stack"]["systems"]
              for t in got["tags"] for l in t["leaders"]}
        self.assertEqual(at.get((1604.8, 670.3)), ["vent"])
        self.assertEqual(at.get((1607.9, 744.2)), ["vent"])

    def test_an_arrow_at_a_pipe_run_is_a_leader_with_no_stack(self):
        got = self._locate(9)              # P-201.00: S-4 points at the drain line
        misses = [(round(t["x"]), round(t["y"])) for t in got["tags"] for l in t["leaders"]
                  if not l["stack"]]
        self.assertEqual(misses, [(1669, 819)])

    def test_the_bulkhead_plan_prints_no_tag(self):
        self.assertEqual(self._locate(15)["tags"], [])

    def test_the_sanitary_series_pairs_by_title_level(self):
        PS = _ps("pair_by_title_level")
        got = PS.pair_by_title_level(BOYLAND_P2, BOYLAND_A_FILED)
        pairs = {p["sheet_number"]: a["sheet_number"] for p, a, _o in got["pairs"]}
        self.assertEqual(pairs, {"P-201.00": "A-100.01", "P-202.00": "A-101.00",
                                 "P-203.00": "A-102.00", "P-204.00": "A-103.00",
                                 "P-205.00": "A-104.00", "P-206.00": "A-105.01"})
        refused = {p["sheet_number"] for p, _w in got["refused"]}
        self.assertEqual(refused, {"P-200.00", "P-207.00"})
        self.assertEqual(got["series"]["P-2"], {"offset": 1, "held_by": 6, "of": 6})

    def test_p204_registers_to_a103_by_a_test_that_could_fail(self):
        PS = _ps("registration_usable", "to_arch")
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet, register
        pa, pp = PlanPage(self.ar, 14), PlanPage(self.pl, 12)
        try:
            reg = register(load_sheet(pa), load_sheet(pp))
        finally:
            pa.close()
            pp.close()
        ok, why = PS.registration_usable(reg)
        self.assertTrue(ok, why)
        self.assertGreater(reg["best_peak_anchors"], 2 * reg["second_peak_anchors"])
        ax, ay = PS.to_arch(1604.8, 670.3, reg)
        self.assertAlmostEqual(ax, 1604.8 + 25.5, delta=1.0)
        self.assertAlmostEqual(ay, 670.3 + 66.0, delta=1.0)
