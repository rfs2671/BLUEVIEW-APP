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

The synthetic sheets are PDFs written byte by byte here, with a real
optional-content group (/OCProperties, /OC /MC0 BDC ... EMC) - the structure a
CAD export writes - so they run everywhere and need no PDF writer. The
real-sheet case needs the source-PDF fixtures (tests/fixture_pdfs.py).

And the reader is ours: lib/ never imports PyMuPDF (AGPL-3.0, ruled out for a
hosted product). pypdfium2 + pdfplumber only.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

try:                                     # absent on main: tests FAIL, not error
    from lib import plan_space as PS
    from lib import plan_space_layers as PL
    from lib.plan_page import PlanPage
    from lib.plan_sheet import load_sheet
except ImportError:                      # pragma: no cover
    PS = PL = PlanPage = load_sheet = None

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

LIB = Path(__file__).resolve().parents[1] / "lib"
LEGEND = ['6" STUD, R19 BATT', '12" CONCRETE', '3.5" STUD, 2 LAYERS GYB.']


def _present():
    assert PS is not None and PL is not None and PlanPage is not None, \
        "lib.plan_space / plan_space_layers / plan_page are not in this tree"


# ── a PDF, by hand ─────────────────────────────────────────────────────────

def _pdf(path, off_layer: str, on_layer: str = "", layer_name: str = "A-WALL",
         width=1200, height=800):
    """One page. `off_layer` / `on_layer` are content-stream drawing operators;
    `on_layer` is wrapped in the optional-content group `layer_name`. The
    legend is set as text so the legend's thickest wall can be read."""
    text = []
    for k, t in enumerate(LEGEND):
        esc = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text.append(f"BT /F1 8 Tf 950 {700 - 20 * k} Td ({esc}) Tj ET")
    content = "\n".join(
        ["0.5 w", off_layer]
        + ([f"/OC /MC0 BDC\n{on_layer}\nEMC"] if on_layer else [])
        + text).encode("latin-1")
    has_layer = bool(on_layer)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R"
        + (b" /OCProperties << /OCGs [6 0 R] /D << /ON [6 0 R] /Order [6 0 R] >> >>"
           if has_layer else b"") + b" >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
         f"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >>"
         + (" /Properties << /MC0 6 0 R >>" if has_layer else "")
         + " >> >>").encode("latin-1"),
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Type /OCG /Name ({layer_name}) >>".encode("latin-1"),
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    Path(path).write_bytes(bytes(out))
    return str(path)


#: off any layer: a two-faced room outline (so the page has corners and a
#: plan extent, as every real plan does)
OUTLINE = "60 40 880 700 re S\n66 46 868 688 re S"


def _line(x0, y0, x1, y1):
    return f"{x0} {y0} m {x1} {y1} l S"


class TheReaderIsNotAgpl(unittest.TestCase):

    def test_lib_never_imports_pymupdf(self):
        """PyMuPDF (fitz / pymupdf) is AGPL-3.0: ruled out for a hosted
        product. Any import of it, anywhere in lib/, at any depth."""
        bad = []
        for p in sorted(LIB.rglob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            for node in ast.walk(tree):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom)
                         else [])
                for n in names:
                    if n.split(".")[0].lower() in ("fitz", "pymupdf"):
                        bad.append(f"{p.relative_to(LIB.parent)}:{node.lineno} {n}")
        self.assertEqual(bad, [])

    def test_the_census_is_not_empty(self):
        """The scan above reads real files - not a green over nothing."""
        self.assertIn("plan_page.py", {p.name for p in LIB.rglob("*.py")})


class TheReaderReadsALayer(unittest.TestCase):
    """A real /OC group, written by hand, read back with its name."""

    def test_layer_name_and_display_frame(self):
        _present()
        with tempfile.TemporaryDirectory() as d:
            path = _pdf(Path(d) / "one.pdf", _line(10, 10, 20, 10),
                        _line(100, 700, 900, 700))
            page = PlanPage(path, 1)
            try:
                got = {dr["layer"]: dr["items"] for dr in page.drawings}
                self.assertEqual(sorted(got), ["", "A-WALL"])
                (kind, p, q), = got["A-WALL"]
                self.assertEqual(kind, "l")
                # display frame: y measured DOWN from the top of the page
                self.assertEqual((p, q), ((100.0, 100.0), (900.0, 100.0)))
                texts = [w[0] for w in page.words]
                self.assertIn('12"', texts)
                self.assertIn("CONCRETE", texts)
            finally:
                page.close()


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


class AWallLayerThatIsNotWallsFallsBack(unittest.TestCase):

    def test_validation_fails_and_the_map_falls_back_saying_why(self):
        """An A-WALL layer of mostly SINGLE lines (no partner face within
        2in..12in) - the shape of a wall layer that is really dimensions and
        linework - plus one real 4in two-faced wall, the minority."""
        _present()
        singles = [_line(100, 700 - 60 * i, 900, 700 - 60 * i) for i in range(6)]
        wall = [_line(100, 100, 400, 100), _line(100, 94, 400, 94)]
        with tempfile.TemporaryDirectory() as d:
            path = _pdf(Path(d) / "not_walls.pdf", OUTLINE,
                        "\n".join(singles + wall))
            page = PlanPage(path, 1)
            try:
                sheet = load_sheet(page)
                v = PL.validate(page, sheet)
                got = PS.build_space(page, ["1A"], 56.0, sheet)
            finally:
                page.close()
        print(f"\nsynthetic A-WALL: paired fraction {v['pair_fraction']:.2f} "
              f"-> {got['fallback_reason']}")
        self.assertEqual(v["layer_names"].get("wall"), ["A-WALL"])
        self.assertLess(v["pair_fraction"], PL.PAIR_MIN)
        self.assertFalse(v["ok"])
        self.assertEqual(got["method"], "geometry")
        self.assertIn("failed validation", got["fallback_reason"])

    def test_the_same_layer_of_real_walls_validates(self):
        """The control for the case above: the same page, the A-WALL layer
        holding two-faced walls, passes - so the failure above is the lines,
        not the harness."""
        _present()
        walls = []
        for i in range(6):
            y = 700 - 60 * i
            walls += [_line(100, y, 900, y), _line(100, y - 6, 900, y - 6)]
        with tempfile.TemporaryDirectory() as d:
            path = _pdf(Path(d) / "walls.pdf", OUTLINE, "\n".join(walls))
            page = PlanPage(path, 1)
            try:
                v = PL.validate(page, load_sheet(page))
            finally:
                page.close()
        self.assertGreaterEqual(v["pair_fraction"], PL.PAIR_MIN)
        self.assertTrue(v["ok"], v["why"])

    def test_no_wall_layer_falls_back(self):
        _present()
        with tempfile.TemporaryDirectory() as d:
            path = _pdf(Path(d) / "no_layers.pdf", OUTLINE)
            page = PlanPage(path, 1)
            try:
                got = PS.build_space(page, ["1A"], 56.0)
            finally:
                page.close()
        self.assertEqual(got["method"], "geometry")
        self.assertEqual(got["fallback_reason"], "no wall layer")


#: (file, page) of each CURRENT architectural sheet in the Boyland fixtures
REAL = {"A-103.00": ("Owners set - 6.9.26.pdf", 4),
        "A-100.01": ("AR - 8.18.26.pdf", 6),
        "A-101.00": ("Owners set - 6.9.26.pdf", 2)}


class TheRealSheetsPass(unittest.TestCase):

    def test_each_real_wall_layer_validates(self):
        """Measured 2026-09-22 on this reader: 0.95 / 0.96 / 0.95 (0.97 /
        0.97 / 0.96 on the PyMuPDF extraction, which dropped every
        rectangle drawn on a rotated sheet - see plan_page)."""
        _present()
        for sheet_no, (fn, pn) in REAL.items():
            page = PlanPage(require_pdf(fn), pn)
            try:
                v = PL.validate(page, load_sheet(page))
            finally:
                page.close()
            print(f"\n{sheet_no}: wall layers {v['layer_names'].get('wall')} "
                  f"paired fraction {v['pair_fraction']:.2f}")
            self.assertTrue(v["ok"], (sheet_no, v["why"]))
            self.assertGreaterEqual(v["pair_fraction"], 0.9, sheet_no)


if __name__ == "__main__":
    unittest.main()
