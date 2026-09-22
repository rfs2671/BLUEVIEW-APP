"""THE WALL LAYER IS THE WALLS - when it validates. Otherwise, geometry.

Measured 2026-09-21 on A-103.00, A-100.01 and A-101.00: each sheet carries its
CAD layers as PDF optional content. On the wall layer there are no dimension
strings, no dashed linework, no furniture, and doorways are clean gaps. So
plan_space reads apartments from the layers first.

But a layer NAME is a claim, not a fact. Before a sheet's wall layer is used,
the fraction of its axis-aligned length that has a parallel partner face (2in
.. the legend's thickest wall) must reach PAIR_MIN. A wall layer holding mostly
single lines - dimensions, linework, anything not a two-faced wall - fails,
and the map falls back to the geometric pipeline, saying why.

The synthetic case builds a real PDF with a real "A-WALL" optional-content
layer, so it runs everywhere; the real-sheet case needs the source-PDF
fixtures (tests/fixture_pdfs.py).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

try:                                     # absent on main: tests FAIL, not error
    from lib import plan_space as PS
    from lib import plan_space_layers as PL
    from lib.plan_sheet import load_sheet
except ImportError:                      # pragma: no cover
    PS = PL = load_sheet = None

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

LEGEND = ['6" STUD, R19 BATT', '12" CONCRETE', '3.5" STUD, 2 LAYERS GYB.']


def _present():
    assert PS is not None and PL is not None, \
        "lib.plan_space / lib.plan_space_layers are not in this tree"


class LayerNamesFollowTheNationalCadStandard(unittest.TestCase):

    def test_major_groups_in_any_case(self):
        _present()
        for name, role in (("A-Wall", "wall"), ("A-WALL", "wall"),
                           ("XR FLOOR PLANS|A-Wall", "wall"),
                           ("A-WALL-FULL", "wall"), ("A-Glaz", "glaz"),
                           ("A-Door", "door"), ("S-WALL", "wall")):
            self.assertEqual(PL.role_of(name), role, name)

    def test_annotation_layers_are_not_the_thing(self):
        """A-DOOR-IDEN is the door TAGS; its geometry is not doors."""
        _present()
        for name in ("A-DOOR-IDEN", "A-WALL-TEXT", "A-DIM", "A-Text",
                     "WALL TAGS", "0", "", None, "A-HATCH"):
            self.assertIsNone(PL.role_of(name), name)


def _outline_and_legend(page):
    """Off any layer: a two-faced room outline (so the page has corners and a
    plan extent, as every real plan does) and a legend naming wall types."""
    for off in (0, 6):
        page.draw_rect((60 + off, 60 + off, 940 - off, 760 - off), width=0.5)
    for k, t in enumerate(LEGEND):
        page.insert_text((950, 100 + 20 * k), t, fontsize=8)


def _synthetic_page(tmpdir):
    """A one-page PDF: an A-WALL layer holding mostly SINGLE lines (no partner
    face within 2in..12in) - the shape of a wall layer that is really
    dimensions and linework."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=1200, height=800)
    _outline_and_legend(page)
    wall = doc.add_ocg("A-WALL", on=True)
    # six single lines, 60pt apart: no face has a partner 3pt..18pt away
    for i in range(6):
        y = 100 + i * 60
        page.draw_line((100, y), (900, y), oc=wall, width=0.5)
    # one real two-faced wall, 4in (6pt) thick - the minority
    page.draw_line((100, 700), (400, 700), oc=wall, width=0.5)
    page.draw_line((100, 706), (400, 706), oc=wall, width=0.5)
    path = os.path.join(tmpdir, "synthetic_wall_layer.pdf")
    doc.save(path)
    doc.close()
    return fitz.open(path)


class AWallLayerThatIsNotWallsFallsBack(unittest.TestCase):

    def test_validation_fails_and_the_map_falls_back_saying_why(self):
        _present()
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            doc = _synthetic_page(d)
            try:
                page = doc[0]
                sheet = load_sheet(page)
                v = PL.validate(page, sheet)
                got = PS.build_space(page, ["1A"], 56.0, sheet)
            finally:
                doc.close()
        print(f"\nsynthetic A-WALL: paired fraction {v['pair_fraction']:.2f} "
              f"-> {got['fallback_reason']}")
        self.assertTrue(v["roles"]["wall"], "the A-WALL layer was not read")
        self.assertLess(v["pair_fraction"], PL.PAIR_MIN)
        self.assertFalse(v["ok"])
        self.assertEqual(got["method"], "geometry")
        self.assertIn("failed validation", got["fallback_reason"])

    def test_no_wall_layer_falls_back(self):
        _present()
        import fitz
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            doc = fitz.open()
            page = doc.new_page(width=1200, height=800)
            _outline_and_legend(page)
            path = os.path.join(d, "no_layers.pdf")
            doc.save(path)
            doc.close()
            doc = fitz.open(path)
            try:
                got = PS.build_space(doc[0], ["1A"], 56.0)
            finally:
                doc.close()
        self.assertEqual(got["method"], "geometry")
        self.assertEqual(got["fallback_reason"], "no wall layer")


#: (file, page) of each CURRENT architectural sheet in the Boyland fixtures
REAL = {"A-103.00": ("Owners set - 6.9.26.pdf", 4),
        "A-100.01": ("AR - 8.18.26.pdf", 6),
        "A-101.00": ("Owners set - 6.9.26.pdf", 2)}


class TheRealSheetsPass(unittest.TestCase):

    def test_each_real_wall_layer_validates(self):
        """Measured 2026-09-22: 0.97 / 0.97 / 0.96."""
        _present()
        import fitz
        for sheet_no, (fn, pn) in REAL.items():
            doc = fitz.open(require_pdf(fn))
            page = doc[pn - 1]
            v = PL.validate(page, load_sheet(page))
            print(f"\n{sheet_no}: wall layers {v['layer_names'].get('wall')} "
                  f"paired fraction {v['pair_fraction']:.2f}")
            self.assertTrue(v["ok"], (sheet_no, v["why"]))
            self.assertGreaterEqual(v["pair_fraction"], 0.9, sheet_no)
            doc.close()


if __name__ == "__main__":
    unittest.main()
