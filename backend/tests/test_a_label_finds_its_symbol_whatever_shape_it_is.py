"""DENSITY FINDS ONE SYMBOL. THE LABEL FINDS ANY SYMBOL.

The first candidate finder scored corner density and worked perfectly on the
only equipment type it had ever seen. Measured on M-103.00 of the Boyland
set, when a second type was tried:

    EF-1 exhaust fan   29 corners within 14in
    PTAC wall unit      6 corners within 60in

No density threshold finds both. PTAC cannot pass "12 corners in 14in" at
any radius, because it does not have 12 corners — it is a rectangle at the
wall. The OCR read all eight PTAC labels perfectly and the registration was
unchanged at RMS 0.047in; the only thing that failed was the assumption that
a symbol is corner-rich, and that assumption was invisible while one symbol
was the whole world.

Anchoring on the printed label removes it: the sheet says where its
equipment is by printing a tag beside it.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_symbols as ps  # noqa: E402

PPI = 1.5
EF = ("EF-1", "EF-2")
PTAC = ("PTAC-1", "PTAC-3")


def _ring(cx, cy, n, r_pt):
    import math
    return [(cx + r_pt * math.cos(2 * math.pi * i / n),
             cy + r_pt * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _rect(cx, cy, w_pt, h_pt):
    return [(cx - w_pt, cy - h_pt), (cx + w_pt, cy - h_pt),
            (cx + w_pt, cy + h_pt), (cx - w_pt, cy + h_pt)]


class ALabelFindsARectangleAsWellAsAFan(unittest.TestCase):

    def test_a_corner_rich_glyph(self):
        """The EF shape: many corners in a small radius."""
        pts = _ring(1000.0, 1000.0, 29, 10.0)
        got, n = ps.symbol_at_label((1030.0, 1000.0), pts,
                                    search_pt=60 * PPI, symbol_pt=20 * PPI)
        self.assertIsNotNone(got)
        self.assertEqual(n, 29)
        self.assertAlmostEqual(got[0], 1000.0, places=6)

    def test_a_four_cornered_rectangle(self):
        """The PTAC shape. THIS IS THE CASE THE DENSITY FINDER CANNOT SEE."""
        pts = _rect(1000.0, 1000.0, 25.0, 6.0)
        got, n = ps.symbol_at_label((1060.0, 1000.0), pts,
                                    search_pt=90 * PPI, symbol_pt=60 * PPI)
        self.assertIsNotNone(got)
        self.assertEqual(n, 4)
        self.assertAlmostEqual(got[0], 1000.0, places=6)

    def test_nothing_beside_the_label_returns_nothing(self):
        got, n = ps.symbol_at_label((1000.0, 1000.0), [(5000.0, 5000.0)],
                                    search_pt=60 * PPI, symbol_pt=20 * PPI)
        self.assertIsNone(got)

    def test_a_second_symbol_further_off_does_not_drag_the_centre(self):
        """The cluster grows from the point NEAREST the label, so a tag a few
        feet from its own symbol still lands on it rather than on the
        midpoint between two."""
        pts = _rect(1000.0, 1000.0, 20.0, 6.0) + _rect(1400.0, 1000.0, 20.0, 6.0)
        got, _n = ps.symbol_at_label((1040.0, 1000.0), pts,
                                     search_pt=600.0, symbol_pt=60.0)
        self.assertLess(abs(got[0] - 1000.0), 30.0)

    def test_a_lone_stray_point_is_not_a_symbol(self):
        got, n = ps.symbol_at_label((1000.0, 1000.0), [(1005.0, 1000.0)],
                                    search_pt=60.0, symbol_pt=20.0)
        self.assertIsNone(got)
        self.assertEqual(n, 1)


class LabelsAreFoundByTheSchedulesClosedSet(unittest.TestCase):

    def test_reads_that_snap_become_labels(self):
        reads = [("EF-1(50)", 100.0, 100.0), ("REFRIGERANT", 200.0, 200.0),
                 ("PTAC-1", 300.0, 300.0), ("NOTES:", 400.0, 400.0)]
        self.assertEqual(ps.labels_in(reads, EF), [("EF-1", 100.0, 100.0)])
        self.assertEqual(ps.labels_in(reads, PTAC),
                         [("PTAC-1", 300.0, 300.0)])

    def test_the_same_label_read_twice_is_one_label(self):
        """A tiled sweep overlaps, so one printed tag is read more than
        once. Two positions inches apart are one label, not two symbols."""
        reads = [("EF-1", 100.0, 100.0), ("EF-1", 105.0, 102.0)]
        self.assertEqual(len(ps.labels_in(reads, EF, merge_pt=30.0)), 1)

    def test_two_real_instances_stay_two(self):
        reads = [("EF-1", 100.0, 100.0), ("EF-1", 900.0, 100.0)]
        self.assertEqual(len(ps.labels_in(reads, EF, merge_pt=30.0)), 2)

    def test_the_eight_ptac_labels_measured_on_the_sheet(self):
        """Verbatim positions from the OCR sweep of M-103.00."""
        reads = [("PTAC-3", 783.1, 508.4), ("PTAC-1", 782.4, 666.3),
                 ("PTAC-1", 782.4, 820.0), ("PTAC-3", 782.9, 968.7),
                 ("PTAC-3", 1923.2, 507.6), ("PTAC-1", 1922.6, 660.9),
                 ("PTAC-1", 1922.5, 813.3), ("PTAC-3", 1923.1, 967.4)]
        found = ps.labels_in(reads, PTAC)
        self.assertEqual(len(found), 8)
        self.assertEqual(sorted({t for t, _x, _y in found}),
                         ["PTAC-1", "PTAC-3"])


class TheDensityFinderIsKeptButItsLimitIsWrittenDown(unittest.TestCase):

    def test_its_threshold_cannot_see_a_four_corner_symbol(self):
        """Not a criticism of the constant - a demonstration that no value of
        it works, which is why the label anchor exists."""
        self.assertGreater(ps.SYMBOL_MIN_CORNERS, 4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
