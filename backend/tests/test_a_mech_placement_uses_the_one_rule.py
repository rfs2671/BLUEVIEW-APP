"""AN M->A PLACEMENT IS REGISTERED BY THE ONE RULE EVERY PAIR USES (ruling 107).

Ruling 63 (2026-10-28): "one function, T3's rule (single best peak agreeing
with the exact 1pt search, >=8 anchors) for all pairs". S->A and P->A use
plan_sheet.register_offset; ruling 107 (2026-10-29): "yes, separate measured
PR; stops for Roy since it changes placements" - this moves the glyph pass's
M->A registration (plan_takeoff.run_takeoff) onto it.

The case that tells the two rules apart: a mechanical sheet whose corners
match the architectural plan equally well at TWO offsets. register() takes
one (it holds the best peak's anchors, so "under half" cannot fire, and its
spread is full) and calls it usable; the one rule refuses a tie - there is
no offset to place symbols by.

Fails on origin/main by assertion (the placement registers usable).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_emit as E  # noqa: E402
from lib import plan_sheet as PS  # noqa: E402
from lib import plan_takeoff as TK  # noqa: E402


def _tie():
    """60 arch corners on a wall layer; the mech sheet holds every one of
    them at two offsets 50pt apart."""
    rng = np.random.default_rng(11)
    A = np.round(rng.uniform([0, 0], [900, 500], size=(60, 2)), 2)
    M = np.vstack([A + np.array([20.0, -10.0]), A + np.array([70.0, -10.0])])
    lo, hi = A.min(0), A.max(0)
    arch = {"corners": A, "att": [((lo[0], lo[1], hi[0], lo[1]), "A-WALL"),
                                  ((lo[0], hi[1], hi[0], hi[1]), "A-WALL")],
            "words": [], "segs": [], "page": (2592, 1728), "rotation": 0}
    mech = {"corners": M, "att": [], "words": [], "segs": [], "page": (2592, 1728), "rotation": 0}
    return arch, mech


class _Page:
    drawings = []
    width, height = 2592.0, 1728.0


def _takeoff():
    arch, mech = _tie()
    sheets = {"arch": arch, "mech": mech}
    a_pg, m_pg = _Page(), _Page()
    a_pg.name, m_pg.name = "arch", "mech"
    with patch.object(TK.plan_ocr, "probe", lambda: (True, "")), \
            patch.object(TK, "load_sheet", lambda pg: sheets[pg.name]), \
            patch.object(TK, "symbol_objects", lambda pg: []):
        return TK.run_takeoff(a_pg, m_pg, ["EF-1"], {}, [], 56.0, reads=[])


class AnMechPlacementTakesTheOneRule(unittest.TestCase):

    def test_two_equal_peaks_refuse_the_placement(self):
        """register() alone calls the tie usable - the case the two rules
        disagree on, and why this move changes placements."""
        arch, mech = _tie()
        self.assertTrue(PS.register(arch, mech)["usable"])
        r = _takeoff()["registration"]
        self.assertFalse(r["usable"], r)
        self.assertIn("two peaks tie", r.get("refused") or "")

    def test_the_row_carries_the_margin(self):
        r = _takeoff()["registration"]
        self.assertIn("margin", r)
        self.assertEqual(r.get("second_peak_anchors"), r.get("best_peak_anchors"))
        self.assertGreaterEqual(E.EMIT_VERSION, 10)


if __name__ == "__main__":
    unittest.main()
