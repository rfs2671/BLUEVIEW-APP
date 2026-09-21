"""THREE WAYS A CONTAINMENT TEST GETS THE RIGHT-LOOKING WRONG ANSWER.

Each class below pins a failure that was measured on A-103.00 and M-103.00
of the Boyland set, not one imagined while writing the code.

The synthetic plan used here is the real one's shape: a rectangle split by a
vertical core wall and a horizontal demising wall into four units, with the
demising wall drawn in COLLINEAR PIECES because that is how the drawing
draws it.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_cells as pc  # noqa: E402
from lib import plan_registration as reg  # noqa: E402

PPI = 1.5                     # pt per real inch at 1/4" = 1'-0"
FT = 12 * PPI                 # pt per foot


def _plan(demising_in_pieces=True):
    """A 40ft x 30ft floor: exterior box, a vertical core at x=20ft, and a
    horizontal demising wall at y=15ft. Four units, labelled at the centres.
    """
    W, H = 40 * FT, 30 * FT
    segs = [(0, 0, W, 0), (0, H, W, H), (0, 0, 0, H), (W, 0, W, H),
            (20 * FT, 0, 20 * FT, H)]
    if demising_in_pieces:
        # ten collinear pieces of 4ft with hairline gaps. FOUR FEET IS THE
        # POINT: each piece is under the 6ft wall filter, so unmerged the
        # demising wall does not exist and the cell swallows two units -
        # which is exactly what happened on A-103.00.
        for i in range(10):
            x0 = i * 4 * FT + 0.5
            segs.append((x0, 15 * FT, x0 + 4 * FT - 1.0, 15 * FT))
    else:
        segs.append((0, 15 * FT, W, 15 * FT))
    labels = {"A": (10 * FT, 22 * FT), "B": (10 * FT, 7 * FT),
              "C": (30 * FT, 22 * FT), "D": (30 * FT, 7 * FT)}
    return segs, labels


class ACollinearWallIsStillAWall(unittest.TestCase):
    """MEASURED: the 4A/4B demising wall on A-103.00 is plainly visible in
    the render and no single segment of it reaches 6ft. A length filter over
    raw segments ran straight through it and returned one 31.8ft cell
    holding two apartments."""

    def test_pieces_merge_into_one_run(self):
        runs = pc.merge_runs([(100.0, 0.0, 50.0), (100.0, 51.0, 100.0),
                              (100.0, 100.5, 150.0)], max_gap_pt=9.0)
        self.assertEqual(len(runs), 1)
        self.assertAlmostEqual(runs[0][1], 0.0)
        self.assertAlmostEqual(runs[0][2], 150.0)

    def test_a_door_sized_gap_is_not_merged(self):
        """Six inches bridges a line-join artifact. A 3ft opening is a real
        gap and must stay one."""
        runs = pc.merge_runs([(100.0, 0.0, 50.0), (100.0, 104.0, 150.0)],
                             max_gap_pt=pc.WALL_MERGE_GAP_IN * PPI)
        self.assertEqual(len(runs), 2)

    def test_the_fragmented_wall_separates_the_units(self):
        segs, labels = _plan(demising_in_pieces=True)
        # a point in unit A, well clear of everything
        got, ft, edge = pc.unit_of(10 * FT, 22 * FT, segs, labels, PPI)
        self.assertEqual(got, "A")

    def test_without_merging_it_would_not(self):
        """The same point, with the merge gap set to zero so the pieces stay
        separate: the cell swallows the demising wall and holds two labels,
        and the rule correctly refuses rather than picking."""
        segs, labels = _plan(demising_in_pieces=True)
        v, h = pc.long_walls(segs, 6 * FT, merge_gap_pt=0.0)
        cell = pc.cell_of(10 * FT, 22 * FT, v, h)
        hits = [t for t in labels if pc.contains(cell, *labels[t])]
        self.assertGreater(len(hits), 1)


class AnExteriorWallHasOnlyOneSide(unittest.TestCase):
    """MEASURED: four kitchenette fans refused at 6.5in from a boundary that
    rendering showed to be the BUILDING ENVELOPE, with the correct unit label
    in the same cell and no other unit label anywhere beyond it."""

    def test_a_point_against_the_exterior_wall_is_still_placed(self):
        """FOUR INCHES from the envelope, and placed - because the nearest
        boundary with another unit behind it is the core wall 10ft away.
        Under the old rule this refused at 4in and lost the answer."""
        segs, labels = _plan()
        px, py = 10 * FT, 30 * FT - 4 * PPI
        got, ft, edge = pc.unit_of(px, py, segs, labels, PPI)
        self.assertEqual(got, "A")
        self.assertAlmostEqual(edge / 12, 10.0, places=6)   # to the core wall
        self.assertGreaterEqual(edge, reg.ROOM_EDGE_EXCLUSION_IN)

    def test_a_point_against_the_demising_wall_is_refused(self):
        """The same 4in, but from the wall with unit B behind it. Here the
        exclusion is protecting against exactly what it exists for."""
        segs, labels = _plan()
        px, py = 10 * FT, 15 * FT + 4 * PPI
        got, _ft, _edge = pc.unit_of(px, py, segs, labels, PPI)
        self.assertIsNone(got)

    def test_the_distance_ignores_edges_with_nobody_behind_them(self):
        """At (10ft, 28ft) the top edge is 2ft away and EXTERIOR, so it does
        not count. What counts is the core wall 10ft right (C and D behind
        it) and the demising wall 13ft below (B and D behind it), so the
        answer is 10ft - and emphatically not the 2ft to the envelope."""
        segs, labels = _plan()
        v, h = pc.long_walls(segs, 6 * FT)
        cell = pc.cell_of(10 * FT, 28 * FT, v, h)
        d = pc.risky_edge_distance_pt(10 * FT, 28 * FT, cell, labels, "A")
        self.assertAlmostEqual(d / PPI / 12, 10.0, places=6)
        plain = min(10 * FT - cell[0], cell[1] - 10 * FT,
                    28 * FT - cell[2], cell[3] - 28 * FT)
        self.assertAlmostEqual(plain / PPI / 12, 2.0, places=6)


class TheRuleReportsWhatDecidedIt(unittest.TestCase):

    def test_it_returns_the_threshold_and_the_edge(self):
        """A caller must be able to see whether an answer sat on a plateau or
        a knife edge, and a record written from it carries both."""
        segs, labels = _plan()
        got, ft, edge = pc.unit_of(10 * FT, 22 * FT, segs, labels, PPI)
        self.assertEqual(got, "A")
        self.assertIn(ft, pc.UNIT_SWEEP_FT)
        self.assertIsNotNone(edge)

    def test_an_unbounded_point_cannot_be_placed(self):
        segs, labels = _plan()
        got, ft, edge = pc.unit_of(-50 * FT, -50 * FT, segs, labels, PPI)
        self.assertEqual((got, ft, edge), (None, None, None))

    def test_the_exclusion_comes_from_the_committed_tolerances(self):
        self.assertEqual(pc.unit_of.__defaults__[-1],
                         reg.ROOM_EDGE_EXCLUSION_IN)


class ContainmentNotNearestLabel(unittest.TestCase):
    """MEASURED: room labels sit at room centres, so a fixture near a
    boundary is often closer to the NEIGHBOUR's label. All eight fans on
    M-103.00 came back BEDROOM by nearest-label, including the four at
    kitchenettes, and all eight were then tagged EF-1."""

    def test_a_label_outside_the_cell_is_not_returned(self):
        segs, _l = _plan()
        pts = [("KITCHENETTE", 30 * FT, 22 * FT),   # in unit C
               ("BEDROOM", 10 * FT, 22 * FT)]       # in unit A
        hits, ft = pc.containing_label(
            10 * FT, 22 * FT, segs, pts,
            ("KITCHENETTE", "BEDROOM"), PPI)
        self.assertEqual(hits, ["BEDROOM"])

    def test_every_word_in_the_cell_is_returned_not_one(self):
        """A cell that swept up the whole floor plate must be visible as
        that, so the caller can decline rather than take the first word."""
        segs, _l = _plan()
        pts = [("KITCHENETTE", 10 * FT, 22 * FT),
               ("BEDROOM", 12 * FT, 24 * FT)]
        hits, _ft = pc.containing_label(
            11 * FT, 23 * FT, segs, pts, ("KITCHENETTE", "BEDROOM"), PPI)
        self.assertEqual(hits, ["BEDROOM", "KITCHENETTE"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
