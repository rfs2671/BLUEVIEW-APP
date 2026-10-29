"""A legend symbol is counted by matching its swatch to every drawing (T2).

Roy, 2026-10-28: "vector-shape match from each sheet's legend swatch
(normalized for translation/scale/90 degree rotation/mirror) against every
connected object ... No match -> refuse."

Measured on 588 Boyland's P-202.00 (PL - 6.29.26 p10), the sheet's own
PLUMBING SYMBOLS legend against the plan:

    SANITARY STACK  4   (each S/n, drawn r0)
    VENT STACK      4   (each V/n, drawn MIRRORED - the block is flipped)
    STORM STACK     2
    every match <= 0.018, nearest impostor 0.145 (a V stack under the S swatch)

THE RULES THIS FILE HOLDS, each with the mutation that breaks it:

  1. Mirror is a normalisation: a flipped block is the same symbol
     (drop the mirrored transforms -> the mirrored flag is not counted).
  2. Every part is scored at its own size: the letter tells S from V
     (score the drawing as one cloud -> the V stack counts as sanitary).
  3. '#' is the printed placeholder for the stack number: S/1 and S/12 are
     the sanitary stack (no placeholder -> neither is).
  4. One pen is one drawing: a leader on another layer touching the circle
     is not part of the symbol (pen = colour only -> the stack is lost).
  5. An ambiguous swatch is refused, never guessed; a line type is not a
     symbol; the legend never counts itself; a drawing drawn twice is one.
  6. Not a chat count: `legend_symbol` is not a counting basis of the gate,
     and plan_search does not read these rows.
"""
from __future__ import annotations

import importlib
import math
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _ls(*names):
    """The module, or an ASSERTION (not an import error) when it is missing:
    on origin/main these tests fail by assertion."""
    try:
        mod = importlib.import_module("lib.plan_legend_symbols")
    except ImportError as e:
        raise AssertionError(f"lib.plan_legend_symbols is not importable: {e}")
    for n in names:
        assert hasattr(mod, n), f"lib.plan_legend_symbols has no {n}"
    return mod


# ── drawing a synthetic sheet ──────────────────────────────────────────────

BLACK = (0, 0, 0)
SYM = "P-TEXT"
K = 0.5523


def _path(items, layer=SYM, colour=BLACK):
    pts = [p for it in items for p in it[1:]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"items": items, "layer": layer, "colour": colour,
            "rect": (min(xs), min(ys), max(xs), max(ys))}


def poly(pts, **kw):
    return _path([("l", pts[i], pts[i + 1]) for i in range(len(pts) - 1)], **kw)


def circle(cx, cy, r, **kw):
    k = K * r
    return _path([
        ("c", (cx + r, cy), (cx + r, cy + k), (cx + k, cy + r), (cx, cy + r)),
        ("c", (cx, cy + r), (cx - k, cy + r), (cx - r, cy + k), (cx - r, cy)),
        ("c", (cx - r, cy), (cx - r, cy - k), (cx - k, cy - r), (cx, cy - r)),
        ("c", (cx, cy - r), (cx + k, cy - r), (cx + r, cy - k), (cx + r, cy)),
    ], **kw)


#: letters in a unit box, y down; each entry is one pen-down run
GLYPHS = {
    "S": [[(1, .1), (.8, 0), (.2, 0), (0, .15), (0, .4), (.2, .5), (.8, .5), (1, .6),
           (1, .85), (.8, 1), (.2, 1), (0, .9)]],
    "V": [[(0, 0), (.5, 1), (1, 0)]],
    "#": [[(0, .35), (1, .35)], [(0, .65), (1, .65)], [(.4, 0), (.3, 1)], [(.75, 0), (.65, 1)]],
    "1": [[(.3, .2), (.5, 0), (.5, 1)]],
    "2": [[(0, .2), (.3, 0), (.7, 0), (1, .2), (1, .4), (0, 1), (1, 1)]],
    "4": [[(.7, 1), (.7, 0), (0, .65), (1, .65)]],
    "-": [[(.1, .5), (.9, .5)]],
    "F": [[(1, 0), (0, 0), (0, 1)], [(0, .45), (.7, .45)]],
}


def glyph(ch, x, y, w, h, **kw):
    return [poly([(x + px * w, y + py * h) for px, py in run], **kw) for run in GLYPHS[ch]]


def stack(cx, cy, r, letter, number, **kw):
    """A stack symbol: circle, horizontal diameter, letter above, number below."""
    out = [circle(cx, cy, r, **kw), poly([(cx - r, cy), (cx + r, cy)], **kw)]
    out += glyph(letter, cx - 0.15 * r, cy - 0.8 * r, 0.3 * r, 0.55 * r, **kw)
    w = 0.3 * r
    x = cx - (w * len(number) + 0.1 * r * (len(number) - 1)) / 2
    for ch in number:
        out += glyph(ch, x, cy + 0.2 * r, w, 0.55 * r, **kw)
        x += w + 0.1 * r
    return out


def flag(x, y, s, mirror=False, rot90=False, **kw):
    """A square frame with an F in it - asymmetric, so a mirror is visible."""
    def T(px, py):
        u, v = px, py
        if mirror:
            u = 1 - u
        if rot90:
            u, v = 1 - v, u
        return (x + u * s, y + v * s)
    frame = poly([T(0, 0), T(1, 0), T(1, 1), T(0, 1), T(0, 0)], **kw)
    f = [poly([T(.25 + .5 * px, .2 + .6 * py) for px, py in run], **kw) for run in GLYPHS["F"]]
    return [frame] + f


class Page:
    """What count_sheet reads from a lib.plan_page.PlanPage."""
    width, height = 2592.0, 1728.0

    def __init__(self, drawings, words):
        self.drawings, self.words = drawings, words

    def render(self, *_a, **_k):
        raise AssertionError("a legend with real words is never sent to OCR")


def pipe(c):
    return [poly([(c[0] + 5, c[1] + 10), (c[2] - 5, c[1] + 10)])]


def legend(rows, x0=40.0, y0=1300.0, sym_w=60.0, desc_w=160.0, h=20.0):
    """A LEGEND table: title band, SYMBOL/DESCRIPTION header, one band per
    row, then two line types (as P-202.00 prints its piping). rows =
    [(meaning, drawings_fn(cell_box))]. Returns (drawings, words)."""
    rows = list(rows) + [("SANITARY PIPING", pipe), ("VENT PIPING", pipe)]
    x1 = x0 + sym_w + desc_w
    ys = [y0 + i * h for i in range(len(rows) + 3)]
    d = [poly([(x0, y), (x1, y)], layer="TABLE") for y in ys]
    d.append(poly([(x0, ys[0]), (x0, ys[-1])], layer="TABLE"))
    d.append(poly([(x1, ys[0]), (x1, ys[-1])], layer="TABLE"))
    d.append(poly([(x0 + sym_w, ys[1]), (x0 + sym_w, ys[-1])], layer="TABLE"))
    words = [("LEGEND", x0 + 80, ys[0] + h / 2), ("SYMBOL", x0 + 30, ys[1] + h / 2),
             ("DESCRIPTION", x0 + sym_w + 60, ys[1] + h / 2)]
    for i, (meaning, draw) in enumerate(rows):
        ya = ys[2 + i]
        words.append((meaning, x0 + sym_w + 60, ya + h / 2))
        d += draw((x0, ya, x0 + sym_w, ya + h))
    return d, words


def centre(cell):
    return (cell[0] + cell[2]) / 2, (cell[1] + cell[3]) / 2


def count(page, **kw):
    m = _ls("count_sheet")
    return {r["meaning"]: r for r in m.count_sheet(page, title_edge=2300.0, **kw)["rows"]}


# ── 1. mirror, rotation, scale ─────────────────────────────────────────────

class AFlippedBlockIsTheSameSymbol(unittest.TestCase):

    def page(self):
        d, w = legend([("FLAG", lambda c: flag(c[0] + 23, c[1] + 3, 14))])
        d += flag(600, 400, 14)                          # as drawn in the legend
        d += flag(700, 400, 20, mirror=True)             # flipped, and bigger
        d += flag(800, 400, 20, rot90=True)              # turned 90
        d += flag(900, 400, 20, mirror=True, rot90=True)
        return Page(d, w)

    def test_mirrored_rotated_and_scaled_instances_all_count(self):
        r = count(self.page())["FLAG"]
        self.assertNotIn("refused", r)
        self.assertEqual(len(r["matches"]), 4, r["matches"])
        self.assertIn("m", {m["transform"] for m in r["matches"]})

    def test_without_the_mirror_a_flipped_block_is_not_the_symbol(self):
        # what the normalisation buys, shown with it switched off
        r = count(self.page(), mirror=False)["FLAG"]
        self.assertEqual(len(r["matches"]), 2, r["matches"])


# ── 2. the letter tells stacks apart ───────────────────────────────────────

def stack_legend():
    return legend([
        ("SANITARY STACK/STACK NO.", lambda c: stack(*centre(c), 8, "S", "#")),
        ("VENT STACK/STACK NO.", lambda c: stack(*centre(c), 8, "V", "#")),
    ])


class TheLetterTellsTheStacksApart(unittest.TestCase):

    def test_s_and_v_stacks_are_counted_apart(self):
        d, w = stack_legend()
        d += stack(600, 400, 11.3, "S", "1") + stack(700, 400, 11.3, "S", "2")
        d += stack(800, 400, 11.3, "V", "1")
        got = count(Page(d, w))
        self.assertEqual(len(got["SANITARY STACK/STACK NO."]["matches"]), 2)
        self.assertEqual(len(got["VENT STACK/STACK NO."]["matches"]), 1)

    def test_a_letter_is_held_to_its_own_size(self):
        m = _ls("match_score", "norm_parts", "PART_FLOOR")
        self.assertLessEqual(m.PART_FLOOR, 0.2)
        d, w = stack_legend()
        d += stack(800, 400, 11.3, "V", "1")
        r = count(Page(d, w))["SANITARY STACK/STACK NO."]
        # the V stack is at best a near miss of the sanitary swatch, never a match
        self.assertEqual(r["matches"], [])


# ── 3. '#' is the number's slot ─────────────────────────────────────────────

class TheStackNumberIsAPlaceholder(unittest.TestCase):

    def test_one_two_and_three_character_numbers_are_the_same_stack(self):
        # P-104.00 numbers a stack 1-4
        d, w = stack_legend()
        d += stack(600, 400, 11.3, "S", "1") + stack(700, 400, 11.3, "S", "12")
        d += stack(800, 400, 11.3, "S", "1-4")
        r = count(Page(d, w))["SANITARY STACK/STACK NO."]
        self.assertTrue(r["placeholder"])
        self.assertEqual(len(r["matches"]), 3, r)

    def test_hash_is_four_strokes_two_level_two_parallel(self):
        m = _ls("is_hash", "strokes_from_drawings")
        strk = m.strokes_from_drawings(glyph("#", 0, 0, 3, 6) + glyph("1", 10, 0, 3, 6))
        self.assertTrue(m.is_hash(strk, [0, 1, 2, 3]))
        self.assertFalse(m.is_hash(strk, [4]))


# ── 4. one pen is one drawing ───────────────────────────────────────────────

class ALeaderIsNotPartOfTheSymbol(unittest.TestCase):

    def test_a_leader_and_a_pipe_touching_the_stack_do_not_join_it(self):
        d, w = stack_legend()
        d += stack(600, 400, 11.3, "S", "1")
        # P-202.00: the leader (another layer) runs from the circle to the pipe
        d.append(poly([(600 - 11.3, 400 + 2), (570, 425)], layer="10 TEXT"))
        d.append(poly([(560, 425), (590, 425)], layer="P-Pipe-Sswr-Vent"))
        r = count(Page(d, w))["SANITARY STACK/STACK NO."]
        self.assertEqual(len(r["matches"]), 1, r)

    def test_a_pipe_on_another_layer_crossing_the_circle_is_not_the_symbol(self):
        # the same black pen, another CAD layer: a vent run drawn straight
        # through the stack circle meets it in two places, so only the layer
        # keeps it out of the symbol
        d, w = stack_legend()
        d += stack(600, 400, 11.3, "S", "1")
        d.append(poly([(580, 404), (640, 404)], layer="P-Pipe-Sswr-Vent"))
        r = count(Page(d, w))["SANITARY STACK/STACK NO."]
        self.assertEqual(len(r["matches"]), 1, r)

    def test_a_leader_that_enters_the_circle_is_cut_off_too(self):
        # P-103.00's CW/2: two leaders cross the circle and end on its
        # diameter, 3.4pt inside - one place, not two
        d, w = stack_legend()
        d += stack(600, 400, 11.3, "S", "1")
        d.append(poly([(540, 370), (600 - 11.3 + 3.0, 400)]))
        d.append(poly([(540, 380), (600 - 11.3 + 3.0, 400)]))
        r = count(Page(d, w))["SANITARY STACK/STACK NO."]
        self.assertEqual(len(r["matches"]), 1, r)

    def test_a_leader_in_the_symbols_own_pen_is_cut_off_where_it_touches(self):
        # P-101.00's W/5: the leader is on the stack's own layer and ends
        # where the diameter meets the circle, with an arrowhead at its far end
        d, w = stack_legend()
        d += stack(600, 400, 11.3, "S", "1")
        d.append(poly([(600 - 11.3, 400), (560, 340)]))
        d.append(poly([(560, 340), (558, 344), (563, 343), (560, 340)]))
        r = count(Page(d, w))["SANITARY STACK/STACK NO."]
        self.assertEqual(len(r["matches"]), 1, r)

    def test_a_diameter_is_never_cut_off_its_circle(self):
        m = _ls("objects", "strokes_from_drawings")
        strk = m.strokes_from_drawings(stack(600, 400, 11.3, "S", "1"))
        (o,) = [o for o in m.objects(strk) if len(o["members"]) > 1]
        self.assertEqual(o["pieces"], [])


# ── 5. refusals, the legend itself, drawn twice ─────────────────────────────

class WhatIsRefused(unittest.TestCase):

    def test_a_line_type_is_not_a_symbol(self):
        d, w = legend([])
        self.assertIn("line type", count(Page(d, w))["SANITARY PIPING"]["refused"])

    def test_two_drawings_in_one_swatch_are_refused(self):
        d, w = legend([("BALL VALVE", lambda c: flag(c[0] + 5, c[1] + 4, 10) + flag(c[0] + 40, c[1] + 4, 10))])
        self.assertIn("2 separate drawings", count(Page(d, w))["BALL VALVE"]["refused"])

    def test_one_drawing_for_two_meanings_is_refused_for_both(self):
        d, w = legend([("FLOOR DRAIN", lambda c: flag(c[0] + 23, c[1] + 3, 14)),
                       ("AREA DRAIN", lambda c: flag(c[0] + 23, c[1] + 3, 14))])
        d += flag(600, 400, 14)
        got = count(Page(d, w))
        for k in ("FLOOR DRAIN", "AREA DRAIN"):
            self.assertIn("ambiguous swatch", got[k]["refused"])

    def test_a_swatch_drawn_again_in_a_refused_rows_cell_is_refused(self):
        # P-001.00: YARD DRAIN's drawing is one of the two in ROOF DRAIN &
        # OVERFLOW ROOF DRAIN's cell; matched alone it counted roof drains
        d, w = legend([("ROOF DRAIN & OVERFLOW ROOF DRAIN",
                        lambda c: flag(c[0] + 5, c[1] + 4, 12) + stack(c[0] + 45, c[1] + 10, 6, "S", "1")),
                       ("YARD DRAIN", lambda c: flag(c[0] + 23, c[1] + 3, 14))])
        d += flag(600, 400, 14)
        got = count(Page(d, w))
        self.assertIn("separate drawings", got["ROOF DRAIN & OVERFLOW ROOF DRAIN"]["refused"])
        self.assertIn("ROOF DRAIN", got["YARD DRAIN"].get("refused", ""))

    def test_a_printed_mark_inside_tells_one_drawing_apart(self):
        # RCP-001.00: one double square, a real-text mark inside each
        d, w = legend([("SWITCH", lambda c: flag(c[0] + 23, c[1] + 3, 14)),
                       ("SENSOR", lambda c: flag(c[0] + 23, c[1] + 3, 14))])
        for t, (x, y) in (("A", (73, 1350)), ("EX", (73, 1370))):
            w.append((t, x, y))
        d += flag(600, 400, 14) + flag(700, 400, 14) + flag(800, 400, 14)
        w += [("EX", 607, 407), ("EX", 707, 407), ("A", 807, 407)]
        got = count(Page(d, w))
        self.assertEqual(len(got["SENSOR"]["matches"]), 2)
        self.assertEqual(len(got["SWITCH"]["matches"]), 1)

    def test_a_bare_square_is_refused(self):
        # P-001.00's PRV is a bare square; on P-104.00 it "matched" 28
        # railing posts of the architectural background
        sq = lambda x, y, s: [poly([(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)])]
        d, w = legend([("PRESSURE RELIEF VALVE (PRV)", lambda c: sq(c[0] + 24, c[1] + 4, 12))])
        d += sq(600, 400, 6) + sq(700, 400, 6)
        self.assertIn("bare outline", count(Page(d, w))["PRESSURE RELIEF VALVE (PRV)"]["refused"])

    def test_a_bare_square_drawn_with_a_thick_pen_is_still_bare(self):
        # P-001.00 draws each side as a 0.36pt filled sliver
        sq = lambda x, y, s: [poly([(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)])]
        thick = lambda x, y, s: sq(x, y, s) + sq(x + 0.36, y + 0.36, s - 0.72)
        d, w = legend([("PRESSURE RELIEF VALVE (PRV)", lambda c: thick(c[0] + 24, c[1] + 4, 11.88))])
        self.assertIn("bare outline", count(Page(d, w))["PRESSURE RELIEF VALVE (PRV)"]["refused"])

    def test_a_bare_square_with_its_own_mark_inside_is_not_bare(self):
        sq = lambda x, y, s: [poly([(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)])]
        d, w = legend([("DAYLIGHT SENSOR", lambda c: sq(c[0] + 24, c[1] + 4, 12))])
        w.append(("D", 70, 1350))
        d += sq(600, 400, 12) + sq(700, 400, 12)
        w.append(("D", 606, 406))
        r = count(Page(d, w))["DAYLIGHT SENSOR"]
        self.assertNotIn("refused", r)
        self.assertEqual(len(r["matches"]), 1)

    def test_a_sheet_with_no_legend_is_refused_not_zero(self):
        # SET_UPDATED's A.3.x lighting plans print no legend at all
        m = _ls("count_sheet", "legend_count_rows", "NO_LEGEND")
        res = m.count_sheet(Page(stack(600, 400, 11.3, "S", "1"), []), title_edge=2300.0)
        self.assertEqual(res.get("refused"), m.NO_LEGEND)
        rows = m.legend_count_rows(res, {"sheet_number": "A.3.1"})
        self.assertEqual([(r["status"], r["count"]) for r in rows], [("refused", None)])

    def test_the_legend_never_counts_its_own_swatch(self):
        d, w = stack_legend()
        r = count(Page(d, w))["SANITARY STACK/STACK NO."]
        self.assertEqual(r["matches"], [])

    def test_a_drawing_drawn_twice_is_one(self):
        d, w = stack_legend()
        # the sheet xrefs two issues of one floor plan: the same block twice,
        # each on its own xref's layer
        d += stack(600, 400, 11.3, "S", "1")
        d += stack(600, 400, 11.3, "S", "1", layer="X-FLOOR PLANS 2.20.2025|P-TEXT")
        r = count(Page(d, w))["SANITARY STACK/STACK NO."]
        self.assertEqual(len(r["matches"]), 1)
        self.assertEqual(r["twice"], 1)


# ── 6. not a chat count; the entry point exists ─────────────────────────────

class NotACountingSourceOfTheGate(unittest.TestCase):

    def test_the_basis_is_not_a_counting_basis(self):
        m = _ls("COUNT_BASIS", "legend_count_rows")
        from lib import plan_search
        self.assertEqual(m.COUNT_BASIS, "legend_symbol")
        self.assertNotIn(m.COUNT_BASIS, plan_search.COUNTING_BASES)

    def test_the_gate_does_not_read_these_rows(self):
        _ls()
        src = (BACKEND / "lib" / "plan_search.py").read_text(encoding="utf-8")
        # word-bounded: the module, and the basis as a whole word (not as a
        # piece of some other identifier)
        self.assertNotRegex(src, r"plan_legend_symbols")
        self.assertNotRegex(src, r"legend_symbol")

    def test_the_rows_say_sheet_scope_and_carry_every_position(self):
        m = _ls("legend_count_rows", "count_sheet")
        d, w = stack_legend()
        d += stack(600, 400, 11.3, "S", "1")
        res = m.count_sheet(Page(d, w), title_edge=2300.0)
        rows = m.legend_count_rows(res, {"sheet_number": "P-202.00", "page_number": 10},
                                   track="filed")
        san = [r for r in rows if r["label"].startswith("SANITARY")][0]
        self.assertEqual((san["status"], san["count"], san["scope"]), ("counted", 1, "sheet"))
        self.assertEqual(len(san["positions"]), 1)
        self.assertEqual(san["count_basis"], "legend_symbol")


class TheEntryPointCallsIt(unittest.TestCase):

    def test_the_script_counts_with_count_sheet(self):
        _ls()
        p = BACKEND / "scripts" / "legend_symbol_counts.py"
        self.assertTrue(p.exists(), "scripts/legend_symbol_counts.py is the entry point")
        src = p.read_text(encoding="utf-8")
        self.assertIn("count_sheet(", src)
        self.assertIn("set_legend(", src)


# ── on the drawings themselves (fixture PDFs; skipped without them) ─────────

class OnTheBoylandDrawings(unittest.TestCase):

    def test_p202_stacks(self):
        m = _ls("count_sheet")
        from lib.plan_page import PlanPage
        page = PlanPage(str(require_pdf("PL - 6.29.26.pdf")), 10)
        got = {r["meaning"]: r for r in m.count_sheet(page)["rows"]}
        n = {k: len(v.get("matches") or []) for k, v in got.items()}
        self.assertEqual(n.get("SANITARY STACK/STACK NO."), 4, n)
        self.assertEqual(n.get("VENT STACK/STACK NO."), 4, n)
        self.assertEqual(n.get("STORM STACK/STACK NO."), 2, n)
        self.assertTrue(all("line type" in got[k]["refused"] for k in got if k.endswith("PIPING")))

    def test_rcp001_control_devices_by_their_marks(self):
        # one double square, five marks; 23 EX across the six views, one A
        m = _ls("count_sheet")
        from lib.plan_page import PlanPage
        page = PlanPage(str(require_pdf("AR - 3.28.25.pdf")), 25)
        got = {r.get("mark"): len(r.get("matches") or []) for r in m.count_sheet(page)["rows"]}
        self.assertEqual(got, {"A": 1, "S": 0, "EX": 23, "D": 0, "P": 0})

# ── 7. the sheet's own legend wins (ruling 75) ──────────────────────────────

def set_legend_rows(rows, sheet="P-001.00"):
    """A legend on ANOTHER page (P-001.00's SYMBOLS LIST), as count_sheet takes
    it: each row with that page's strokes and words."""
    m = _ls("strokes_from_drawings")
    d, w = legend(rows, x0=40.0, y0=1000.0)
    strk = m.strokes_from_drawings(d)
    out = []
    for i, (meaning, _f) in enumerate(rows):
        y = 1000.0 + (2 + i) * 20.0
        out.append({"meaning": meaning, "cell": (40.0, y, 100.0, y + 20.0), "sheet": sheet,
                    "strokes": strk, "words": w})
    return out


class TheSheetsOwnLegendWins(unittest.TestCase):

    def page_and_set(self):
        d, w = legend([("SANITARY STACK/STACK NO.", lambda c: stack(*centre(c), 8, "S", "#"))])
        d += stack(600, 400, 11.3, "S", "1") + stack(700, 400, 11.3, "S", "2")
        d += stack(800, 400, 11.3, "V", "1")
        extra = set_legend_rows([
            ("SANITARY STACK/STACK NO.", lambda c: stack(*centre(c), 8, "S", "#")),
            ("SOIL STACK", lambda c: stack(*centre(c), 8, "S", "#")),
            ("VENT STACK/STACK NO.", lambda c: stack(*centre(c), 8, "V", "#"))])
        return Page(d, w), extra

    def test_a_row_both_legends_print_is_counted_once_from_the_sheets_own(self):
        m = _ls("count_sheet", "SUPERSEDED")
        page, extra = self.page_and_set()
        rows = m.count_sheet(page, extra, title_edge=2300.0)["rows"]
        own = [r for r in rows if r["src"] == "own legend" and r["meaning"].startswith("SANITARY")]
        self.assertEqual(len(own[0]["matches"]), 2)
        theirs = {r["meaning"]: r for r in rows if r["src"] == "P-001.00"}
        # the same meaning, and the same drawing under another meaning
        for k in ("SANITARY STACK/STACK NO.", "SOIL STACK"):
            self.assertTrue(theirs[k].get("refused", "").startswith(m.SUPERSEDED), theirs[k])
        # a row only the set legend prints still counts
        self.assertEqual(len(theirs["VENT STACK/STACK NO."]["matches"]), 1)


# ── 8. P/R against whichever benchmark is loaded, per sheet or per floor ────

class ABenchmarkPerSheetOrPerFloor(unittest.TestCase):

    def results(self):
        def res(rows):
            return {"rows": [dict(r, src="own legend") for r in rows]}
        s4 = {"meaning": "SANITARY STACK/STACK NO.", "matches": [{"box": [0, 0, 1, 1]}] * 4}
        cw = {"meaning": "COLD WATER STACK/STACK NO.", "matches": [{"box": [0, 0, 1, 1]}] * 4}
        pipe = {"meaning": "SANITARY PIPING", "refused": "a line type"}
        return {"P-202.00": res([s4, pipe]), "P-101.00": res([cw]),
                "P-200.00": res([s4])}

    TITLES = {"P-202.00": "SECOND FLOOR SANITARY & STORM PLAN",
              "P-101.00": "SECOND FLOOR DOMESTIC WATER & GAS PLANS",
              "P-200.00": "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN"}

    def test_per_sheet(self):
        m = _ls("evaluate")
        got = m.evaluate(self.results(), {"source": "Roy's sub bid", "kind": "sub_bid",
                                          "sheets": {"P-202.00": {"SANITARY STACK/STACK NO.":
                                                                  {"expected": 5},
                                                                  "SANITARY PIPING": {"expected": 9}}}})
        self.assertEqual(got["source"], "Roy's sub bid")
        san, pipe = got["rows"]
        self.assertEqual((san["tp"], san["fn"], san["basis"]), (4, 1, "per count (an upper bound)"))
        self.assertEqual(pipe["status"], "refused")       # never scored as zero found

    def test_per_floor_by_the_printed_title_level(self):
        m = _ls("evaluate")
        got = m.evaluate(self.results(), {"floors": {
            "SECOND FLOOR": {"SANITARY STACK/STACK NO.": {"expected": 4},
                             "COLD WATER STACK/STACK NO.": {"expected": 4}},
            "FIRST UNDERGROUND": {"SANITARY STACK/STACK NO.": {"expected": 4}}}},
            titles=self.TITLES)
        by = {(r["where"], r["symbol"]): r for r in got["rows"]}
        second = by[("SECOND FLOOR", "SANITARY STACK/STACK NO.")]
        self.assertEqual(second["sheets"], ["P-101.00", "P-202.00"])
        self.assertEqual((second["found"], second["tp"]), (4, 4))
        self.assertEqual(by[("SECOND FLOOR", "COLD WATER STACK/STACK NO.")]["found"], 4)
        # a level no title names is said, never guessed onto a sheet
        self.assertEqual(by[("FIRST UNDERGROUND", "SANITARY STACK/STACK NO.")]["status"],
                         "unresolved")
        self.assertEqual(got["totals"]["tp"], 8)



if __name__ == "__main__":
    unittest.main()
