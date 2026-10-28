"""STRUCTURE IS READ IN THE ARCHITECT'S FRAME (lib.plan_structural).

Clash v1 asks whether a plumbing stack sits inside a shear wall, so the
structural elements must be polygons in the SAME frame as the stacks: the
architectural plan of the level both are drawn for. Three things decide it:

  1. WHICH A PLAN. Floor identity is the sheet number and the title level,
     never the registration fit (operator 2026-10-26): every wrong-floor S/A
     pair registers "usable", and A-103 holds MORE anchors against S-105 than
     against its own S-104. A sheet whose title names no single level, or
     whose partner breaks the set's series offset, refuses.
  2. WHERE. The offset comes from plan_sheet.best_translation, with a usable
     check that CAN FAIL: the offset must be the exact census' best peak and
     that peak must be unique. usable_for cannot fail (its residuals are
     self-gated at one inch) - the 2.5ft-wrong S-104/A-103 offset of the old
     4pt search had max 0.95in and was called usable.
  3. WHAT. Shear walls are the braced frames (diagonal hatch) an SW tag
     names, joined to S-301's schedule by level; posts, beams/headers, joist
     bays and the hold-down zone at each end member.

Each test fails on origin/main by ASSERTION (_present), not by an import
error: the module is imported lazily.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_sheet as PS  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

try:
    from lib import plan_structural as T  # noqa: E402
except ImportError:                       # origin/main: the tests fail by assertion
    T = None


def _present():
    assert T is not None, "there is no lib.plan_structural: structure is not read at all"


def _shared():
    """The ONE offset rule every discipline pair uses (operator 2026-10-28)."""
    assert hasattr(PS, "register_offset"),         "plan_sheet has no register_offset: S->A and P->A have no shared offset rule"


# ══════════════════════════════════════════════════════════════════════════
# 1. pairing by title level + series offset
# ══════════════════════════════════════════════════════════════════════════

#: the filed track's plans exactly as the production index titles them
#: (read 2026-10-28, find() only) - A-105.01's "BULKEAD" is the architect's
BOYLAND_FILED = [
    ("A-100.01", "FIRST FLOOR PLAN"), ("A-101.00", "SECOND FLOOR PLAN"),
    ("A-102.00", "THIRD FLOOR PLAN"), ("A-103.00", "FOURTH FLOOR PLAN"),
    ("A-104.00", "MEZZANINE PLAN"), ("A-105.01", "ROOF AND BULKEAD PLAN"),
    ("S-001.00", None), ("S-002.00", "GENERAL NOTES"),
    ("S-101.00", "1ST FLOOR FRAMING PLAN"), ("S-102.00", "2ND FLOOR FRAMING PLAN"),
    ("S-103.00", "3RD FLOOR FRAMING PLAN"), ("S-104.00", "4TH FLOOR FRAMING PLAN"),
    ("S-105.00", "MEZZANINE FLOOR FRAMING PLAN"), ("S-106.00", "ROOF FRAMING PLAN"),
    ("S-301.00", "SHEAR WALL SCHEDULE AND DETAILS"),
]


def _pages(rows):
    return [{"sheet_number": n, "sheet_title": t, "page_id": n} for n, t in rows]


def _paired(out):
    return {p["s"]["sheet_number"]: p["a"]["sheet_number"] for p in out["pairs"]}


class AFloorIsItsTitleNeverItsFit(unittest.TestCase):

    def test_title_levels(self):
        _present()
        for title, want in [("4TH FLOOR FRAMING PLAN", "FLOOR_4"), ("FOURTH FLOOR PLAN", "FLOOR_4"),
                            ("MEZZANINE FLOOR FRAMING PLAN", "MEZZANINE"), ("MEZZANINE PLAN", "MEZZANINE"),
                            ("ROOF FRAMING PLAN", "ROOF"), ("1ST FLOOR FRAMING PLAN", "FLOOR_1")]:
            self.assertEqual(T.title_level(title), want, title)

    def test_a_title_naming_no_single_level_is_none(self):
        _present()
        for title in ("FLOOR PLAN", "ROOF AND BULKHEAD PLAN", "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN",
                      None, "GENERAL NOTES"):
            self.assertIsNone(T.title_level(title), title)

    def test_two_ordinals_are_not_one_level(self):
        """tokens_in reads FIRST AND SECOND FLOOR PLANS as FLOOR_2."""
        _present()
        self.assertIsNone(T.title_level("FIRST AND SECOND FLOOR PLANS"))

    def test_boyland_pairs_s_one_above_a(self):
        """S-104 (4TH) is A-103 (FOURTH): by title, never by number."""
        _present()
        out = T.pair_by_level(_pages(BOYLAND_FILED))
        self.assertEqual(out["offset"], 1)
        self.assertEqual(_paired(out), {"S-101.00": "A-100.01", "S-102.00": "A-101.00",
                                        "S-103.00": "A-102.00", "S-104.00": "A-103.00",
                                        "S-105.00": "A-104.00", "S-106.00": "A-105.01"})
        self.assertEqual(out["refused"], [])

    def test_a_sheet_that_breaks_the_offset_refuses(self):
        """Renumber the FOURTH FLOOR plan to A-104: S-104 still pairs with it
        by title, but at +0 against the set's +1 - so it refuses, and the
        sheet now numbered A-103 is never taken for it either."""
        _present()
        rows = [(n, t) for n, t in BOYLAND_FILED if n not in ("A-103.00", "A-104.00")]
        rows += [("A-104.00", "FOURTH FLOOR PLAN"), ("A-103.00", "MEZZANINE PLAN")]
        out = T.pair_by_level(_pages(rows))
        self.assertEqual(out["offset"], 1)
        got = _paired(out)
        self.assertNotIn("S-104.00", got)
        self.assertNotIn("S-105.00", got)
        why = {r["page"]["sheet_number"]: r["reason"] for r in out["refused"]}
        self.assertIn("offset is +1", why["S-104.00"])
        self.assertIn("offset is +1", why["S-105.00"])

    def test_an_unparsed_title_refuses_with_its_reason(self):
        _present()
        rows = [(n, ("FRAMING PLAN" if n == "S-104.00" else t)) for n, t in BOYLAND_FILED]
        out = T.pair_by_level(_pages(rows))
        self.assertNotIn("S-104.00", _paired(out))
        why = {r["page"]["sheet_number"]: r["reason"] for r in out["refused"]}
        self.assertIn("does not name one level", why["S-104.00"])

    def test_roof_and_bulkhead_spelled_right_refuses_the_roof(self):
        """A-105.01 pairs with S-106 only because the architect wrote BULKEAD:
        spelled right, the title names two levels and S-106 has no partner."""
        _present()
        rows = [(n, ("ROOF AND BULKHEAD PLAN" if n == "A-105.01" else t)) for n, t in BOYLAND_FILED]
        out = T.pair_by_level(_pages(rows))
        self.assertNotIn("S-106.00", _paired(out))
        self.assertEqual(len(out["pairs"]), 5)

    def test_the_same_rule_pairs_plumbings_2xx_sheets(self):
        """T4's P-2xx sanitary plans run one above A too (P-204 = FOURTH)."""
        _present()
        rows = [(n, t) for n, t in BOYLAND_FILED if n.startswith("A-")] + [
            ("P-201.00", "FIRST FLOOR SANITARY & STORM PLAN"), ("P-204.00", "FOURTH FLOOR SANITARY & STORM PLAN"),
            ("P-205.00", "MEZZANINE FLOOR SANITARY & STORM PLAN"), ("P-103.00", "FOURTH FLOOR DOMESTIC WATER PLAN"),
            ("P-200.00", "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN")]
        out = T.pair_by_level(_pages(rows), disc="P", series="2")
        self.assertEqual(_paired(out), {"P-201.00": "A-100.01", "P-204.00": "A-103.00", "P-205.00": "A-104.00"})
        self.assertEqual([r["page"]["sheet_number"] for r in out["refused"]], ["P-200.00"])

    def test_two_a_plans_of_one_level_refuse(self):
        _present()
        out = T.pair_by_level(_pages(BOYLAND_FILED + [("A-106.00", "FOURTH FLOOR PLAN")]))
        self.assertNotIn("S-104.00", _paired(out))

    def test_no_majority_offset_refuses_every_sheet(self):
        _present()
        rows = [("A-100.00", "FIRST FLOOR PLAN"), ("A-102.00", "SECOND FLOOR PLAN"),
                ("S-101.00", "1ST FLOOR FRAMING PLAN"), ("S-102.00", "2ND FLOOR FRAMING PLAN")]
        out = T.pair_by_level(_pages(rows))
        self.assertIsNone(out["offset"])
        self.assertEqual(out["pairs"], [])
        self.assertEqual(len(out["refused"]), 2)


# ══════════════════════════════════════════════════════════════════════════
# 2. registration: the offset, and a usable check that can fail
# ══════════════════════════════════════════════════════════════════════════

#: a narrow search window for the synthetic pairs (the drawings use plan_sheet's +/-360pt)
SPAN = 60.0


def _cloud(n=150, seed=3):
    rng = np.random.default_rng(seed)
    return np.round(rng.uniform([0, 0], [1200, 700], size=(n, 2)), 2)


class TheOffsetIsTheUniqueBestPeakOrRefused(unittest.TestCase):

    def test_the_true_offset_is_used(self):
        _present()
        _shared()
        A = _cloud()
        B = A + np.array([7.0, -242.0])
        r = PS.register_offset({"corners": A}, {"corners": B}, span_pt=SPAN)
        self.assertTrue(r["usable"], r["refused"])
        self.assertAlmostEqual(r["dx"], 7.0, delta=0.2)
        self.assertAlmostEqual(r["dy"], -242.0, delta=0.2)

    def test_the_census_agrees_with_plan_sheet(self):
        _present()
        _shared()
        A = _cloud()
        B = np.vstack([A + np.array([40.0, -30.0]), _cloud(60, 9)])
        c = PS.peak_census(A, B, span_pt=SPAN)
        n, xy = PS.offset_census(A, B, span_pt=SPAN)
        self.assertEqual(c["best"][0], n)
        self.assertEqual(tuple(c["best"][1]), tuple(xy))

    def test_an_offset_off_the_best_peak_is_refused(self):
        """The search returns a coincidental peak (as the 4pt grid did on
        S-104/A-103: 95 anchors, 2.5ft off; true 204): refused, though its
        residuals are under an inch."""
        _present()
        _shared()
        A = _cloud()
        true, decoy = np.array([40.0, -30.0]), np.array([75.0, 0.0])
        B = np.vstack([A + true, A[:60] + decoy])
        real = PS.best_translation

        def wrong(A_, B_, **kw):
            """the search lands on the decoy; its matches are within an inch"""
            from scipy.spatial import cKDTree
            dist, jj = cKDTree(B_).query(A_ + decoy, distance_upper_bound=PS._pts(1.0))
            ok = np.isfinite(dist)
            return tuple(decoy), A_[ok], B_[jj[ok]], dist[ok]
        try:
            PS.best_translation = wrong
            r = PS.register_offset({"corners": A}, {"corners": B}, span_pt=SPAN)
        finally:
            PS.best_translation = real
        self.assertAlmostEqual(r["dx"], decoy[0], delta=0.01)
        self.assertGreaterEqual(r["anchors"], 50)
        self.assertLess(r["max_in"], 1.0)                 # residuals cannot tell
        self.assertFalse(r["usable"])
        self.assertIn("from the best peak", r["refused"])

    def test_two_tied_peaks_are_refused(self):
        _present()
        _shared()
        A = _cloud()
        B = np.vstack([A + np.array([40.0, -30.0]), A + np.array([90.0, 0.0])])
        r = PS.register_offset({"corners": A}, {"corners": B}, span_pt=SPAN)
        self.assertFalse(r["usable"])
        self.assertIn("two peaks tie", r["refused"])

    def test_too_few_anchors_are_refused(self):
        _present()
        _shared()
        A = _cloud(12)
        B = np.vstack([A[:6] + np.array([40.0, -30.0]), _cloud(6, 5)])      # 6 match, 6 do not
        r = PS.register_offset({"corners": A}, {"corners": B}, span_pt=SPAN)
        self.assertFalse(r["usable"])
        self.assertIn("only", r["refused"])

    def test_a_polygon_moves_by_minus_d_and_not_at_all_when_refused(self):
        _present()
        _shared()
        rg = {"usable": True, "dx": 6.0, "dy": -242.0}
        self.assertEqual(T.to_arch([[10.0, 300.0]], rg), [[4.0, 542.0]])
        self.assertIsNone(T.to_arch([[10.0, 300.0]], dict(rg, usable=False)))


class TheWallsMustChooseTheOffset(unittest.TestCase):
    """S only (operator 2026-10-28): after the offset, the share of S shear +
    bearing wall length on A-Wall lines within 2pt, at the offset and at the
    runner-up peak; the pair refuses when the runner-up scores as well."""

    WALLS = [{"element": "shear_wall", "polygon": [[100, 100], [109, 100], [109, 277], [100, 277]]},
             {"element": "bearing_wall", "polygon": [[200, 300], [500, 300], [500, 309], [200, 309]]},
             {"element": "post", "polygon": [[0, 0], [9, 0], [9, 9], [0, 9]]}]

    @staticmethod
    def _arch(d, extra_d=None):
        """A-Wall lines where the S walls land at offset d (and at extra_d)."""
        att = []
        for dd in [d] + ([extra_d] if extra_d else []):
            dx, dy = dd
            for x in (100, 109):
                att.append(((x - dx, 100 - dy, x - dx, 277 - dy), "XR FLOOR PLANS|A-Wall"))
            for y in (300, 309):
                att.append(((200 - dx, y - dy, 500 - dx, y - dy), "XR FLOOR PLANS|A-Wall"))
        att.append(((0, 0, 900, 0), "A-Anno-Dims"))
        return {"att": att}

    def test_the_walls_choose_the_offset(self):
        _present()
        rg = {"dx": 6.0, "dy": -242.0, "second_peak": [6.0, -196.0], "usable": True}
        wc = T.wall_check(self.WALLS, self._arch((6.0, -242.0)), rg)
        self.assertTrue(wc["ok"], wc["why"])
        self.assertEqual(wc["wall_share_best"], 1.0)
        self.assertLess(wc["wall_share_second"], 0.5)        # a 46pt shift leaves part of one wall on its own line
        self.assertTrue(T.with_wall_check(rg, wc)["usable"])

    def test_a_runner_up_as_good_on_the_walls_refuses(self):
        """The architect's walls repeat 46pt apart: the runner-up offset puts
        the structure on walls exactly as well - the walls do not choose."""
        _present()
        rg = {"dx": 6.0, "dy": -242.0, "second_peak": [6.0, -196.0], "usable": True, "refused": None}
        wc = T.wall_check(self.WALLS, self._arch((6.0, -242.0), (6.0, -196.0)), rg)
        self.assertEqual(wc["wall_share_best"], wc["wall_share_second"])
        self.assertFalse(wc["ok"])
        got = T.with_wall_check(rg, wc)
        self.assertFalse(got["usable"])
        self.assertIn("the walls do not choose it", got["refused"])
        self.assertEqual(rg["usable"], True)          # the shared verdict is not rewritten

    def test_only_shear_and_bearing_walls_on_wall_layers_count(self):
        _present()
        rg = {"dx": 0.0, "dy": 0.0, "second_peak": [40.0, 0.0]}
        arch = {"att": [((100, 100, 100, 277), "A-Anno-Dims"), ((109, 100, 109, 277), "A-Anno-Dims")]}
        wc = T.wall_check(self.WALLS[:1], arch, rg)
        self.assertFalse(wc["ok"])
        self.assertIn("no wall layer", wc["why"])


class TheOwnersSetUsesTheFiledStructure(unittest.TestCase):
    """Operator 2026-10-28: the owner's set has no S sheets; it uses the
    filed set's, and every row says so."""

    def test_the_label(self):
        _present()
        self.assertEqual(T.structure_note({"sheet_number": "S-104.00"}, "post_co", "filed"),
                         "structure per filed set S-104.00; the owner's set has no structural sheets")
        self.assertIsNone(T.structure_note({"sheet_number": "S-104.00"}, "filed", None))

    def test_a_track_without_s_sheets_borrows_the_filed_ones(self):
        _present()
        filed = _pages(BOYLAND_FILED)
        owners = [dict(p, page_id="own-" + p["sheet_number"]) for p in _pages(BOYLAND_FILED)
                  if p["sheet_number"].startswith("A-")]
        seen = {}
        real = T.run_track
        try:
            T.run_track = lambda pages, op, track=None, borrowed_from=None: seen.setdefault(
                track, (sorted(p["sheet_number"] for p in pages), borrowed_from))
            T.run_tracks([("filed", filed), ("post_co", owners)], None)
        finally:
            T.run_track = real
        self.assertIsNone(seen["filed"][1])
        self.assertEqual(seen["post_co"][1], "filed")
        self.assertIn("S-104.00", seen["post_co"][0])
        self.assertIn("A-103.00", seen["post_co"][0])


# ══════════════════════════════════════════════════════════════════════════
# 3. elements, from a page built by hand
# ══════════════════════════════════════════════════════════════════════════

def _rect_items(x0, y0, x1, y1):
    return [("l", (x0, y0), (x1, y0)), ("l", (x1, y0), (x1, y1)),
            ("l", (x1, y1), (x0, y1)), ("l", (x0, y1), (x0, y0))]


def _d(items, layer):
    xs = [p[0] for it in items for p in it[1:]]
    ys = [p[1] for it in items for p in it[1:]]
    return {"items": items, "layer": layer, "rect": (min(xs), min(ys), max(xs), max(ys)), "colour": (0, 0, 0)}


class _Page:
    """The PlanPage surface read_elements reads: drawings, directed_words,
    width/height (the title block edge)."""

    def __init__(self, drawings, words, w=2592.0, h=1728.0):
        self.drawings, self.directed_words, self.width, self.height = drawings, words, w, h


def _frame_page(*, frame_hatch="x", tags=(("SW", 1650, 550),), extra=(), words=()):
    """A plan: grid lines, one 9x177pt wall at x 1633..1642 with a hatch, a
    tick-hatched bearing wall, a post at each end of the first wall, the
    legend's wall sample BELOW the view title."""
    W = "X-REF|SET_CONCRETE_COLUMN_WALL"
    H = "X-REF|SET_GENERAL_HATCH_LIGHT"
    dr = [_d([("l", (200, 150), (2000, 150))], "X-REF|SET_GENERAL_GRID"),
          _d([("l", (200, 880), (2000, 880))], "X-REF|SET_GENERAL_GRID"),
          _d([("l", (300, 100), (300, 900))], "X-REF|SET_GENERAL_GRID"),
          _d(_rect_items(1633.1, 460.2, 1642.1, 637.2), W),
          _d(_rect_items(1033.1, 544.2, 1279.1, 553.2), W),
          _d(_rect_items(161.8, 1276.2, 207.8, 1285.2), "Ext. Wall")]       # legend sample
    y = 462.0
    while y < 630:
        if frame_hatch == "x":
            dr.append(_d([("l", (1633.1, y), (1642.1, y + 9))], H))
            dr.append(_d([("l", (1633.1, y + 9), (1642.1, y))], H))
        else:
            dr.append(_d([("l", (1633.1, y), (1642.1, y))], H))
        y += 6.6
    for x in range(1040, 1275, 6):
        dr.append(_d([("l", (x, 544.2), (x, 553.2))], H))                   # bearing-wall ticks
    for y0 in (460.2, 627.8):                                               # end posts
        dr.append(_d([("l", (1633.3, y0), (1641.9, y0)), ("l", (1641.9, y0), (1641.9, y0 + 9)),
                      ("l", (1641.9, y0 + 9), (1633.3, y0 + 9)), ("l", (1633.3, y0 + 9), (1633.3, y0)),
                      ("l", (1637.6, y0), (1637.6, y0 + 9))], "X-REF|SET_GENERAL_TEXT"))
        dr.append(_d([("l", (1634, y0 + 1), (1637, y0 + 1)), ("l", (1634, y0 + 8), (1637, y0 + 8)),
                      ("l", (1638, y0 + 1), (1641, y0 + 1)), ("l", (1638, y0 + 8), (1641, y0 + 8)),
                      ("l", (1635, y0 + 1), (1635, y0 + 8))], "X-REF|SET_GENERAL_TEXT"))
    dr += list(extra)
    w = [("4TH", 300, 1000, "ltr"), ("FLOOR", 330, 1000, "ltr"), ("FRAMING", 370, 1000, "ltr"),
         ("PLAN", 410, 1000, "ltr")]
    for t, x, yy in tags:
        w += [(t, x, yy, "ltr"), ("1", x + 12, yy, "ltr")]
    return _Page(dr, w + list(words))


def _els(page):
    return T.read_elements(page)


class ShearWallsAreTaggedBracedFrames(unittest.TestCase):

    def test_a_tagged_braced_frame_is_a_shear_wall(self):
        _present()
        got = _els(_frame_page())
        sw = [e for e in got["elements"] if e["element"] == "shear_wall"]
        self.assertEqual([e["tag"] for e in sw], ["SW 1"])
        self.assertEqual(T._bbox(sw[0]["polygon"]), (1633.1, 460.2, 1642.1, 637.2))
        self.assertEqual(sw[0]["attrs"]["system"], "cfs_braced_frame")
        self.assertEqual([e["element"] for e in got["elements"] if e["element"] == "bearing_wall"],
                         ["bearing_wall"])

    def test_a_tag_beside_a_bearing_wall_names_nothing(self):
        """Ticks across the wall are legend 6's stud bearing wall, not a frame."""
        _present()
        got = _els(_frame_page(frame_hatch="ticks"))
        self.assertEqual([e for e in got["elements"] if e["element"] == "shear_wall"], [])
        self.assertEqual([u["tag"] for u in got["unassigned_tags"]], ["SW 1"])

    def test_the_legend_sample_below_the_view_title_is_not_a_wall(self):
        _present()
        got = _els(_frame_page())
        walls = [e for e in got["elements"] if e["element"] in ("wall", "bearing_wall", "shear_wall")]
        self.assertFalse(any(T._bbox(e["polygon"])[1] > 1000 for e in walls))

    def test_two_tags_on_one_wall_name_neither(self):
        """The roof plan draws the A-line walls below as one dashed run with
        SW 4 and SW 6 beside it: where one ends is not drawn."""
        _present()
        got = _els(_frame_page(tags=(("SW", 1650, 480),),
                               words=[("SW", 1650, 600, "ltr"), ("6", 1662, 600, "ltr")]))
        self.assertEqual([e for e in got["elements"] if e["element"] == "shear_wall"], [])
        self.assertEqual(sorted(u["tag"] for u in got["unassigned_tags"]), ["SW 1", "SW 6"])

    def test_a_hold_down_zone_at_each_end_member(self):
        _present()
        els = _els(_frame_page())["elements"]
        hd = T.hold_down_zones(els)
        self.assertEqual(len(hd), 2)
        self.assertEqual({h["attrs"]["zone_from"] for h in hd}, {"post at the end member"})
        boxes = sorted(T._bbox(h["polygon"])[1] for h in hd)
        self.assertAlmostEqual(boxes[0], 460.2, delta=0.5)
        self.assertAlmostEqual(boxes[1], 627.8, delta=0.5)

    def test_posts_are_found(self):
        _present()
        posts = [e for e in _els(_frame_page())["elements"] if e["element"] == "post"]
        self.assertEqual(len(posts), 2)


class TheViewIsTheGrid(unittest.TestCase):

    def test_one_grid_line_running_on_does_not_stretch_the_plan(self):
        """S-106: a grid-layer line runs past the roof plan to a second view
        (the bulkhead framing). The plan is where the grid lines run - the
        median of their ends, not the extreme."""
        _present()
        G = "X-REF|SET_GENERAL_GRID"
        dr = [_d([("l", (200, y), (2000, y))], G) for y in (150, 500, 880)]
        dr += [_d([("l", (x, 100), (x, 900))], G) for x in (300, 900, 1400)]
        dr.append(_d([("l", (1653, 100), (1653, 1500))], G))
        x0, y0, x1, y1 = T.plan_extent(_Page(dr, []))
        self.assertLess(y1, 1000)
        self.assertEqual(x0, 200)

    def test_an_unlabelled_post_in_a_shear_wall_is_its_end_member(self):
        """Legend 7: sized by the schedule - only inside a shear wall."""
        _present()
        els = [{"element": "shear_wall", "tag": "SW 1", "polygon": [[0, 0], [9, 0], [9, 177], [0, 177]],
                "attrs": {"schedule": {"END MEMBERS": "(2) 6J14", "STUDS": "6J12 @ 16\" O.C."}}},
               {"element": "post", "polygon": [[0, 0], [9, 0], [9, 9], [0, 9]], "attrs": {"size": None}},
               {"element": "post", "polygon": [[0, 300], [9, 300], [9, 309], [0, 309]], "attrs": {"size": None}},
               {"element": "post", "polygon": [[0, 168], [9, 168], [9, 177], [0, 177]],
                "attrs": {"size": "(2) 6J16", "size_from": "leader"}}]
        T.size_posts_from_schedule(els)
        self.assertEqual(els[1]["attrs"]["size"], "(2) 6J14")
        self.assertIsNone(els[2]["attrs"]["size"])
        self.assertEqual(els[3]["attrs"]["size"], "(2) 6J16")


class BeamsJoistsAndBands(unittest.TestCase):

    def test_dash_dot_lines_merge_and_pair(self):
        _present()
        segs = []
        for c in (1184.6, 1190.6):
            y = 242.7
            while y < 540:
                segs.append(("v", c, y, y + 18.0, "X-REF|SET_STEEL_JOIST"))
                y += 36.0                              # 18 dash, 9 gap, dot, 9 gap
        got = T.bands(segs, 20.0, 3.0, 12.0)
        self.assertEqual(len(got), 1)
        x0, y0, x1, y1, o = got[0]
        self.assertEqual((x0, x1, o), (1184.5, 1190.5, "v"))
        self.assertGreater(y1 - y0, 280)

    def test_a_beam_inside_a_wall_is_a_header_and_one_ending_in_it_is_not(self):
        _present()
        J = "X-REF|SET_STEEL_JOIST"
        extra = [_d([("l", (1080, 546.2), (1180, 546.2))], J), _d([("l", (1080, 551.2), (1180, 551.2))], J),
                 _d([("l", (700, 300), (700, 548))], J), _d([("l", (706, 300), (706, 548))], J)]
        page = _frame_page(extra=extra)
        page.drawings.append(_d(_rect_items(690, 540, 720, 556), "X-REF|SET_CONCRETE_COLUMN_WALL"))
        els = _els(page)["elements"]
        kinds = sorted(e["element"] for e in els if e["element"] in ("beam", "header"))
        self.assertEqual(kinds, ["beam", "header"])

    def test_a_joist_symbol_takes_its_legend_spec_and_its_bay(self):
        _present()
        S = "SET_STEEL_JOIST"
        sym = [_d([("l", (888.7, 451.7), (888.7, 437.0)), ("l", (872.8, 437.0), (888.7, 451.7))], S),
               _d([("l", (888.7, 335.2), (888.7, 349.9)), ("l", (904.6, 349.9), (888.7, 335.2))], S),
               _d([("l", (888.7, 366.4), (888.7, 384.4))], S)]
        page = _frame_page(extra=sym, words=[
            ("3.", 153.9, 1224.5, "ltr"), ("*", 185.7, 1224.1, "ltr"), ("INDICATES", 237.7, 1224.5, "ltr"),
            ("SPAN", 278.3, 1224.5, "ltr"), ("OF", 300, 1224.5, "ltr"), ("PANEL", 330, 1224.5, "ltr"),
            ("1", 879, 395, "btt"), ("2.", 154.0, 1177.0, "ltr"), ("1", 188.1, 1165.0, "ltr"),
            ("INDICATES", 237.7, 1177.0, "ltr"), ("SPAN", 278.3, 1177.0, "ltr"),
            ("DIRECTION", 320, 1177.0, "ltr"), ("OF", 350, 1177.0, "ltr"),
            ("8J12(800S200-97)", 400, 1177.0, "ltr"), ("JOISTS", 450, 1177.0, "ltr"),
            ('@16"', 480, 1177.0, "ltr"), ("O.C.", 500, 1177.0, "ltr")])
        J = "X-REF|SET_CONCRETE_COLUMN_WALL"
        for r in ((700, 230.7, 1100, 239.7), (700, 544.2, 1033, 553.2), (757, 239.7, 766, 544.2),
                  (1100, 239.7, 1109, 544.2)):
            page.drawings.append(_d(_rect_items(*r), J))
        js = [e for e in _els(page)["elements"] if e["element"].startswith("joist")]
        self.assertEqual(len(js), 1)
        j = js[0]
        self.assertEqual(j["element"], "joist_bay")
        self.assertEqual((j["attrs"]["size"], j["attrs"]["spacing_in"], j["attrs"]["direction"]),
                         ("8J12(800S200-97)", 16, "vertical"))
        self.assertEqual(T._bbox(j["polygon"]), (766, 239.7, 1100, 544.2))


class TheScheduleIsReadByItsRules(unittest.TestCase):

    def _table(self):
        """FLOOR | SHEAR WALL 1 (END MEMBERS, DIAGONALS), three rows; the
        DIAGONALS cell is merged over MEZZANINE and 4TH FLOOR."""
        L = "SET_GENERAL_TEXT"
        xs = [45.9, 156.0, 229.1, 302.2]
        dr = []
        for x in xs:
            dr.append(_d([("l", (x, 880.2 if x in (45.9, 302.2) else 895.7), (x, 1144.5))], L))
        dr.append(_d([("l", (45.9, 880.2), (302.2, 880.2))], L))
        dr.append(_d([("l", (156.0, 895.7), (302.2, 895.7))], L))
        dr.append(_d([("l", (45.9, 937.0), (302.2, 937.0))], L))
        dr.append(_d([("l", (45.9, 1020.3), (302.2, 1020.3))], L))
        dr.append(_d([("l", (45.9, 1090.0), (229.1, 1090.0))], L))       # NOT across DIAGONALS
        dr.append(_d([("l", (45.9, 1144.5), (302.2, 1144.5))], L))
        w = [("FLOOR", 101, 909, "ltr"), ("SHEAR", 210, 889, "ltr"), ("WALL", 240, 889, "ltr"),
             ("1", 260, 889, "ltr"), ("END", 180, 917, "ltr"), ("MEMBERS", 205, 917, "ltr"),
             ("DIAGONALS", 265, 917, "ltr"),
             ("ROOF", 101, 978, "ltr"), ("-", 192, 978, "ltr"), ("-", 265, 978, "ltr"),
             ("MEZZANINE", 101, 1055, "ltr"), ("(2)", 180, 1055, "ltr"), ("6J14", 200, 1055, "ltr"),
             ("4TH", 90, 1118, "ltr"), ("FLOOR", 110, 1118, "ltr"), ("(3)", 180, 1118, "ltr"),
             ("6J10", 200, 1118, "ltr"),
             ("12", 250, 1085, "ltr"), ("GA", 262, 1085, "ltr"), ("STRAP", 285, 1085, "ltr")]
        return _Page(dr, w)

    def test_rows_columns_and_a_merged_cell(self):
        _present()
        got = T.read_shear_wall_schedule(self._table())["rows"]
        cell = lambda lv, f: got.get((lv, "SW 1"), {}).get(f)          # noqa: E731
        self.assertEqual(cell("FLOOR_4", "END MEMBERS"), "(3) 6J10")
        self.assertEqual(cell("MEZZANINE", "END MEMBERS"), "(2) 6J14")
        self.assertEqual(cell("FLOOR_4", "DIAGONALS"), "12 GA STRAP")
        self.assertEqual(cell("MEZZANINE", "DIAGONALS"), "12 GA STRAP")
        self.assertEqual(cell("ROOF", "END MEMBERS"), "-")


# ══════════════════════════════════════════════════════════════════════════
# 4. on the Boyland drawings (fixture PDFs; skipped, and warned, without them)
# ══════════════════════════════════════════════════════════════════════════

def _page(name, n):
    from lib.plan_page import PlanPage
    return PlanPage(str(require_pdf(name)), n)


def _sheet(name, n):
    pg = _page(name, n)
    try:
        return PS.load_sheet(pg)
    finally:
        pg.close()


class OnTheBoylandSet(unittest.TestCase):
    """S-104.00 (ST 7.29.26 p8) on A-103.00 (AR 3.28.25 p14, the filed
    track's FOURTH FLOOR PLAN). Measured 2026-10-28 (T3_structural_measure)."""

    ST, A103 = ("ST - 7.29.26.pdf", 8), ("AR - 3.28.25.pdf", 14)

    def test_s104_registers_on_its_true_peak(self):
        _present()
        _shared()
        r = PS.register_offset(_sheet(*self.A103), _sheet(*self.ST))
        self.assertTrue(r["usable"], r["refused"])
        self.assertLess(np.hypot(r["dx"] - 7.0, r["dy"] + 242.5), 1.5, (r["dx"], r["dy"]))

    def test_the_old_4pt_answer_is_refused_here(self):
        """The 2.5ft-wrong offset register() reported before #743, with
        residuals under an inch: this check refuses it on its own."""
        _present()
        _shared()
        r = PS.register_offset(_sheet(*self.A103), _sheet(*self.ST), coarse_pt=4.0)
        self.assertGreater(abs(r["dy"] + 242.5), 30, (r["dx"], r["dy"]))
        self.assertLess(r["max_in"], 1.0)
        self.assertFalse(r["usable"])
        self.assertIn("from the best peak", r["refused"])

    def test_s104_walls_choose_the_offset_over_the_runner_up(self):
        _present()
        _shared()
        a, s = _sheet(*self.A103), _sheet(*self.ST)
        r = PS.register_offset(a, s)
        pg = _page(*self.ST)
        try:
            els = T.read_elements(pg)["elements"]
        finally:
            pg.close()
        wc = T.wall_check(els, a, r)
        self.assertTrue(wc["ok"], wc["why"])
        self.assertGreater(wc["wall_share_best"], wc["wall_share_second"])

    def test_s104_reads_seven_shear_walls_and_sw1(self):
        _present()
        pg = _page(*self.ST)
        try:
            got = T.read_elements(pg)
        finally:
            pg.close()
        sw = {e["tag"]: T._bbox(e["polygon"]) for e in got["elements"] if e["element"] == "shear_wall"}
        self.assertEqual(sorted(sw), [f"SW {i}" for i in range(1, 8)])
        for got_v, want in zip(sw["SW 1"], (1633.1, 460.2, 1642.1, 637.2)):
            self.assertAlmostEqual(got_v, want, delta=0.2)
        self.assertEqual(got["unassigned_tags"], [])

    def test_s301_schedule(self):
        _present()
        pg = _page("ST - 7.29.26.pdf", 11)
        try:
            rows = T.read_shear_wall_schedule(pg)["rows"]
        finally:
            pg.close()
        self.assertEqual(rows[("FLOOR_4", "SW 1")]["END MEMBERS"], "(2) 6J14")
        self.assertEqual(rows[("FLOOR_1", "SW 1")]["END MEMBERS"], "(3) 6J10")
        self.assertEqual(rows[("FLOOR_2", "SW 2")]["END MEMBERS"], "(3) 6J10")
        self.assertEqual(rows[("ROOF", "SW 3")]["END MEMBERS"], "(2) 6J14")
        self.assertEqual(rows[("ROOF", "SW 1")]["END MEMBERS"], "-")
        self.assertEqual(rows[("FLOOR_4", "SW 1")]["DIAGONALS"], '12 GA 6" WIDE STRAP EACH SIDE OF PANEL')


if __name__ == "__main__":
    unittest.main()
