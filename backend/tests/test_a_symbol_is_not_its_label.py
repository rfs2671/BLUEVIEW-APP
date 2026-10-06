"""A SYMBOL IS THE EQUIPMENT, NOT THE TAG PRINTED BESIDE IT.

`symbol_at_label` used to answer with the CENTROID of every corner within
60in of the geometry nearest the label. On these sheets the tags are not PDF
text - `EF-2(100)` is drawn as outlines - so the nearest geometry to a label
IS the label, and the average of fan + duct + counter + background came back
on the word itself.

Measured on the Boyland set, 47 items, rendered and read one by one:

    A-100.01 EF-2(100) in 1D   the pick sat on the label's parentheses; the
                               fan is the nested square up-left of it
    A-103.00 EF-1(50) in 4B    the pick sat on the label's "1"
    A-101.00 PTAC-2 in 2C      the pick sat on the label, never on the unit

Each of those was ANSWERED CORRECTLY ANYWAY - the label is usually in the
same apartment as its equipment - which is why it survived a 47/47 score.
It is the reading that was wrong, and one of them (1D) crossed a counter
line and became 1C on the geometric fallback.

So a symbol is ONE CONNECTED OBJECT near the label, and never the label:
grown through geometry it touches, bounded by the largest symbol, taken as
the centre of its own bounding box. The three cases above are pinned here.

The real-sheet cases need the source-PDF fixtures (tests/fixture_pdfs.py).
They read geometry with pdfplumber, which is what this repo ships.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_symbols as ps  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

PPI = 1.5                      # 1/4" = 1'-0": one real inch is 1.5pt
BLACK, GREY = (0.0, 0.0, 0.0), (0.66275, 0.66275, 0.66275)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _obj(points, layer=None, colour=BLACK):
    return {"points": points, "layer": layer, "colour": colour}


class _TheRuleIsInThisTree(unittest.TestCase):
    """Absent, every case below FAILS on what it asserts - it does not error
    out of the run on a missing argument."""

    def setUp(self):
        import inspect
        sig = inspect.signature(ps.symbol_at_label).parameters
        missing = [p for p in ("label_boxes", "same_pass", "min_symbol_pt")
                   if p not in sig]
        self.assertEqual(missing, [], "plan_symbols.symbol_at_label does not "
                         "take the symbol rule's inputs in this tree")


class TheLabelIsNeverItsOwnSymbol(_TheRuleIsInThisTree):

    def test_the_tags_own_glyphs_are_excluded(self):
        """The tag is drawn as outlines, so its glyphs are geometry - and
        they are the geometry NEAREST the label, every time."""
        label = (1000.0, 1000.0)
        box = (970.0, 994.0, 1030.0, 1006.0)
        glyphs = [_obj(_rect(972.0 + 8 * i, 995.0, 977.0 + 8 * i, 1005.0))
                  for i in range(6)]
        fan = _obj(_rect(985.0, 940.0, 1015.0, 970.0))
        got, _n = ps.symbol_at_label(label, glyphs + [fan], 90 * PPI, 60 * PPI,
                                     label_boxes=[box])
        self.assertEqual([round(v) for v in got], [1000, 955])

    def test_without_the_box_the_label_wins(self):
        """The control for the case above: same geometry, no label box, and
        the answer is the word - which is what this fixes."""
        label = (1000.0, 1000.0)
        glyphs = [_obj(_rect(972.0 + 8 * i, 995.0, 977.0 + 8 * i, 1005.0))
                  for i in range(6)]
        fan = _obj(_rect(985.0, 940.0, 1015.0, 970.0))
        got, _n = ps.symbol_at_label(label, glyphs + [fan], 90 * PPI, 60 * PPI)
        self.assertLess(abs(got[1] - 1000.0), 10.0)


class ASymbolIsOneConnectedObject(_TheRuleIsInThisTree):

    def test_touching_paths_are_one_symbol(self):
        """A fan is drawn as nested squares; they are one symbol."""
        outer = _obj(_rect(1000.0, 1000.0, 1030.0, 1030.0))
        inner = _obj(_rect(1010.0, 1010.0, 1020.0, 1020.0))
        touching = _obj(_rect(1030.0, 1010.0, 1040.0, 1020.0))
        got, _n = ps.symbol_at_label((1060.0, 1015.0),
                                     [outer, inner, touching],
                                     90 * PPI, 60 * PPI)
        self.assertEqual([round(v) for v in got], [1020, 1015])

    def test_what_it_does_not_touch_is_not_part_of_it(self):
        near = _obj(_rect(1000.0, 1000.0, 1030.0, 1030.0))
        apart = _obj(_rect(1200.0, 1000.0, 1230.0, 1030.0))
        got, _n = ps.symbol_at_label((1040.0, 1015.0), [near, apart],
                                     600.0, 60 * PPI)
        self.assertEqual([round(v) for v in got], [1015, 1015])

    def test_structure_is_never_the_symbol(self):
        """A wall line or a duct run crosses the sheet. Touching one dragged
        the answer 400in away on A-103.00."""
        wall = _obj([(0.0, 1035.0), (2500.0, 1035.0)])
        unit = _obj(_rect(1000.0, 1000.0, 1060.0, 1030.0))
        got, _n = ps.symbol_at_label((1080.0, 1015.0), [wall, unit],
                                     90 * PPI, 60 * PPI)
        self.assertEqual([round(v) for v in got], [1030, 1015])

    def test_dust_is_skipped_for_the_equipment_behind_it(self):
        """A hatch fragment 0.4in across sat nearer the label than the PTAC
        unit and was answered as the symbol."""
        speck = _obj([(1070.0, 1016.0), (1070.6, 1016.1)])
        unit = _obj(_rect(1000.0, 1000.0, 1060.0, 1030.0))
        got, _n = ps.symbol_at_label((1080.0, 1015.0), [speck, unit],
                                     90 * PPI, 60 * PPI)
        self.assertEqual([round(v) for v in got], [1030, 1015])


class TheDrawingPassBreaksTiesOnly(_TheRuleIsInThisTree):

    #: label at (1000, 1000); both candidates 14.1pt from it, one either side
    GREY_RIGHT = (1010.0, 1010.0, 1040.0, 1040.0)
    BLACK_LEFT = (960.0, 1010.0, 990.0, 1040.0)
    BOX = (988.0, 994.0, 1012.0, 1006.0)

    def _glyph(self):
        return _obj(_rect(990.0, 995.0, 1010.0, 1005.0), colour=BLACK)

    def test_a_tie_goes_to_the_labels_own_pass(self):
        """The mechanical work and its tags are one pass over a background
        drawn in another; at equal distance, that is the tie-break."""
        rep = {}
        got, _n = ps.symbol_at_label(
            (1000.0, 1000.0),
            [self._glyph(), _obj(_rect(*self.GREY_RIGHT), colour=GREY),
             _obj(_rect(*self.BLACK_LEFT), colour=BLACK)],
            90 * PPI, 60 * PPI, label_boxes=[self.BOX], report=rep)
        self.assertTrue(rep["tie"])
        self.assertEqual([round(v) for v in got], [975, 1025])

    def test_a_nearer_object_still_wins(self):
        """Colour decides nothing on its own: the same grey object, with the
        label's own pass further away, is the answer."""
        rep = {}
        got, _n = ps.symbol_at_label(
            (1000.0, 1000.0),
            [self._glyph(), _obj(_rect(*self.GREY_RIGHT), colour=GREY),
             _obj(_rect(1100.0, 1010.0, 1130.0, 1040.0), colour=BLACK)],
            90 * PPI, 60 * PPI, label_boxes=[self.BOX], report=rep)
        self.assertFalse(rep["tie"])
        self.assertEqual([round(v) for v in got], [1025, 1025])


class LayersDecideWhenTheSheetHasThem(_TheRuleIsInThisTree):

    def test_text_layers_are_never_the_symbol(self):
        tag = _obj(_rect(1020.0, 1010.0, 1035.0, 1020.0), layer="M-EQPM-IDEN")
        unit = _obj(_rect(1000.0, 1000.0, 1060.0, 1030.0), layer="M-HVAC-EQPM")
        got, _n = ps.symbol_at_label((1040.0, 1015.0), [tag, unit],
                                     90 * PPI, 60 * PPI)
        self.assertEqual([round(v) for v in got], [1030, 1015])

    def test_an_equipment_layer_wins_over_anything_nearer(self):
        furniture = _obj(_rect(1036.0, 1012.0, 1048.0, 1018.0), layer="I-FURN")
        unit = _obj(_rect(1000.0, 1000.0, 1060.0, 1030.0), layer="M-EQPM")
        got, _n = ps.symbol_at_label((1050.0, 1015.0), [furniture, unit],
                                     90 * PPI, 60 * PPI)
        self.assertEqual([round(v) for v in got], [1030, 1015])


# ── the three pinned real-sheet cases ──────────────────────────────────────

#: (sheet, page, label centre, the OCR read boxes that are the label,
#:  the equipment's own extent read off the render 2026-09-22)
PINNED = {
    "A-100.01 EF-2(100) in 1D": (
        2, (1673.1, 703.9),
        [(1652.3, 698.0, 1693.9, 709.7), (1680.0, 697.7, 1693.3, 709.7),
         (1697.1, 680.2, 1708.6, 689.0)],
        (1650.0, 670.0, 1700.0, 700.0)),
    "A-103.00 EF-1(50) in 4B": (
        5, (1050.1, 832.5),
        [(1032.1, 826.3, 1068.1, 838.7)],
        (1030.0, 795.0, 1075.0, 825.0)),
    "A-101.00 PTAC-2 in 2C": (
        3, (1647.2, 470.8),
        [(1631.0, 465.9, 1663.4, 475.7)],
        (1605.0, 420.0, 1685.0, 465.0)),
}


def _objects(page):
    """Every drawn path near the plan, as (points, layer, colour). pdfplumber
    is the reader this repo ships; the M sheets carry no layers at all."""
    out = []
    for o in page.lines + page.rects + page.curves:
        pts = o.get("pts")
        if pts and o.get("object_type") == "curve":
            pts = [(float(x), float(page.height - y)) for x, y in pts]
        elif not pts:
            x0, x1 = float(o["x0"]), float(o["x1"])
            t, b = float(o["top"]), float(o["bottom"])
            pts = ([(x0, t), (x1, b)] if o["object_type"] == "line"
                   else _rect(x0, t, x1, b))
        else:
            pts = [(float(x), float(y)) for x, y in pts]
        colour = o.get("stroking_color") or o.get("non_stroking_color")
        out.append({"points": pts, "layer": None,
                    "colour": tuple(colour) if isinstance(colour, (list, tuple))
                    else (colour,)})
    return out


class ThePinnedItemsLandOnTheirEquipment(_TheRuleIsInThisTree):

    @classmethod
    def setUpClass(cls):
        cls.pdf = require_pdf("MH - 7.2.26.pdf")
        try:
            import pdfplumber  # noqa: F401
        except Exception as e:                      # pragma: no cover - env
            raise unittest.SkipTest(f"pdfplumber unavailable: {e}")

    def test_each_pinned_item(self):
        import pdfplumber
        with pdfplumber.open(self.pdf) as pdf:
            for name, (pn, label, boxes, equip) in PINNED.items():
                with self.subTest(item=name):
                    page = pdf.pages[pn - 1]
                    got, n = ps.symbol_at_label(
                        label, _objects(page), 90 * PPI, 60 * PPI,
                        label_boxes=boxes, same_pass=True)
                    print(f"\n{name}: symbol at "
                          f"{tuple(round(v, 1) for v in got)} ({n} points)")
                    self.assertIsNotNone(got, name)
                    self.assertTrue(
                        equip[0] <= got[0] <= equip[2]
                        and equip[1] <= got[1] <= equip[3],
                        f"{name}: {got} is not on the equipment {equip}")
                    for b in boxes:
                        self.assertFalse(
                            b[0] <= got[0] <= b[2] and b[1] <= got[1] <= b[3],
                            f"{name}: {got} is on the label {b}")


if __name__ == "__main__":
    unittest.main()
