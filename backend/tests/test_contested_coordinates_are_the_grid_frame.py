"""`contested_cells` ROW/COL DO NOT INDEX `rows`. THEY INDEX THE OCR GRID.

A schedule record carries two tables of different shapes:

    A.4.0    rows 1 x 14    cell_scores 7 x 14    contested max r6 c6
    FA-001   rows 6 x 12    cell_scores 9 x 12    contested max r7 c0
    M-200.00 rows 3 x 16    cell_scores 5 x 16    contested max r3 c1

`rows` is the RESTRUCTURED table - heading rows merged, empty rows dropped.
`cell_scores` is the OCR grid as read, and `contested_cells` row/col are in
that frame. `r6` exists in a 7-row grid and not in a 1-row table.

MEASURED on the 92 contested cells of the 173-page corpus, indexing `rows`
by those coordinates:

    24 landed on the marker
     1 landed on a cell holding one of the readings
    41 landed on UNRELATED CONTENT - r0c0 holding a triangle glyph where the
       readings were '48'/'48 AFF'; r4c0 holding 'PIPE DIAMETER' where they
       were '8 & LARGER'
    26 landed outside the table

So two thirds of a coordinate-indexed lookup silently returns the wrong
cell, and 41 of those return a cell that EXISTS and looks like an answer.
That is the failure mode worth a test: not a crash, a plausible wrong cell.

WHAT THIS PINS. Nothing in the repo does this today. The test exists so that
the first thing to try it fails here rather than in a human-facing queue,
where the consequence is showing someone the wrong cell of a drawing and
asking them to adjudicate it.

THE CORRECT FRAME IS USABLE, verified by cropping two cells from
`payload["bbox"]` divided by the `cell_scores` shape and looking at them:
FA-001 r6c0 lands on a cell printing `6` (readings '6 SPRK...' / '9 SPRK...')
and M-200.00 r3c1 on one printing `9` (readings '6' / '9'). Even division is
APPROXIMATE - the second crop sat about half a row high - so a crop for a
person needs padding, but it lands on the cell.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

BACKEND = Path(__file__).resolve().parents[1]
SOURCES = [BACKEND / "server.py"] + sorted((BACKEND / "lib").glob("plan_*.py"))


class NothingIndexesRowsWithAContestedCoordinate(unittest.TestCase):
    """The guard, as a source scan. A runtime test cannot reach code that
    does not exist yet, and this defect's whole shape is that the wrong
    lookup succeeds."""

    def _functions_touching_contested(self, tree):
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            src = ast.unparse(node)
            if "contested_cells" in src:
                out.append((node.name, src))
        return out

    def test_no_function_subscripts_rows_near_a_contested_cell(self):
        offenders = []
        for path in SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for name, src in self._functions_touching_contested(tree):
                # `rows[` next to contested_cells is the shape of the bug:
                # taking row/col from one table and applying it to the other.
                if "rows[" in src:
                    offenders.append(f"{path.name}:{name}")
        self.assertEqual(
            offenders, [],
            "these read contested_cells AND subscript rows in the same "
            f"function: {offenders}. contested_cells row/col are in the "
            "cell_scores frame; indexing rows with them returns a plausible "
            "wrong cell 41 times in 92. Crop from payload['bbox'] divided by "
            "the cell_scores shape instead.")

    def test_the_scan_can_actually_find_something(self):
        """PROVE THE PROBE CAN RETURN A KNOWN NON-ZERO. An empty offender
        list means nothing if the scan cannot see any function at all - the
        same clean-zero trap that produced three false readings while this
        defect was being measured."""
        seen = []
        for path in SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            seen += [n for n, _ in self._functions_touching_contested(tree)]
        self.assertTrue(
            seen, "the scan found no function mentioning contested_cells at "
            "all, so its empty result proves nothing")


class TheTwoFramesAreDocumentedInTheRecord(unittest.TestCase):
    """A synthetic payload of the shape the corpus actually stores, so the
    asymmetry is stated in code rather than only in a comment."""

    PAYLOAD = {
        "name": "SPRINKLER SCHEDULE",
        # The restructured table: one row survived the heading merge.
        "rows": [["MARK", "QTY", "TYPE"]],
        # The OCR grid as read: three rows, same width.
        "cell_scores": [[0.9, 0.9, 0.9], [0.8, -1.0, 0.9], [0.7, 0.9, 0.9]],
        "contested_cells": [
            {"row": 2, "col": 0, "mark": "",
             "readings": ["6 SPRK", "9 SPRK"], "scores": [0.86, 0.96]},
        ],
        "bbox": [100.0, 200.0, 300.0, 400.0],
    }

    def test_the_contested_row_is_out_of_range_for_the_stored_table(self):
        p = self.PAYLOAD
        row = p["contested_cells"][0]["row"]
        self.assertGreaterEqual(row, len(p["rows"]),
                                "this fixture no longer shows the mismatch")
        self.assertLess(row, len(p["cell_scores"]),
                        "the grid must contain the coordinate")

    def test_a_cell_rect_comes_from_the_bbox_and_the_grid_shape(self):
        """What a queue should compute. Asserted as arithmetic so the
        intended frame is unambiguous."""
        p = self.PAYLOAD
        c = p["contested_cells"][0]
        x0, y0, x1, y1 = p["bbox"]
        nrows = len(p["cell_scores"])
        ncols = max(len(r) for r in p["cell_scores"])
        cw = (x1 - x0) / ncols
        ch = (y1 - y0) / nrows
        rect = (x0 + c["col"] * cw, y0 + c["row"] * ch,
                x0 + (c["col"] + 1) * cw, y0 + (c["row"] + 1) * ch)
        # bbox 200x200, a 3x3 grid, the cell at row 2 col 0: the left third
        # of the width, the bottom third of the height.
        for got, want in zip(rect, (100.0, 333.333333, 166.666667, 400.0)):
            self.assertAlmostEqual(got, want, places=4)

    def test_dividing_by_the_stored_table_would_give_a_different_rect(self):
        """The same arithmetic against `rows` - 1 row here - puts the cell
        off the bottom of the grid entirely. Stated so the two are visibly
        not interchangeable."""
        p = self.PAYLOAD
        c = p["contested_cells"][0]
        x0, y0, x1, y1 = p["bbox"]
        ch_wrong = (y1 - y0) / len(p["rows"])
        self.assertGreater(y0 + c["row"] * ch_wrong, y1,
                           "the wrong divisor should overshoot the grid")

    def test_the_grid_is_never_smaller_than_the_coordinates_it_carries(self):
        """The invariant a reader may rely on: a contested coordinate is
        always inside `cell_scores`. It is NOT always inside `rows`."""
        p = self.PAYLOAD
        nrows = len(p["cell_scores"])
        ncols = max(len(r) for r in p["cell_scores"])
        for c in p["contested_cells"]:
            self.assertLess(c["row"], nrows)
            self.assertLess(c["col"], ncols)


if __name__ == "__main__":
    unittest.main()
