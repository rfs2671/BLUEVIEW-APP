"""THE RENDER PRINTS NO EMPTY PER-UNIT LIST.

On 588 Boyland the first floor's six WH-1 all sit outside the apartments, so
every unit's count is zero, and the render printed "WH-1 6; per unit ; none
placed in 1A, 1B, 1C, 1D" - a list with nothing in it. A zero is never
printed as a figure, so with nothing to list there is no list.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as S  # noqa: E402
from tests.test_a_located_count_is_complete_or_refused import (  # noqa: E402
    _census, _floor, _numbered, _pages)
from tests.test_a_sheet_it_cannot_place_still_counts import WH  # noqa: E402


def _line(placed):
    rows = _numbered(_floor("102", WH, placed))
    recs = rows + _census(rows, _pages(rows), {WH: ["WH-1"]})
    return next(l for l in S.render_glyph_evidence(recs).splitlines()
                if l.startswith("- ") and "THIRD FLOOR" in l)


class NoEmptyPerUnitList(unittest.TestCase):

    def test_every_unit_zero(self):
        line = _line([("WH-1", "non-unit:CORRIDOR")] * 6)
        self.assertNotIn("per unit ;", line)
        self.assertIn("WH-1 6; none placed in 3A, 3B, 3C, 3D", line)

    def test_a_unit_with_one_still_lists(self):
        line = _line([("WH-1", "3A")] + [("WH-1", "non-unit:CORRIDOR")] * 5)
        self.assertIn("per unit 3A 1; none placed in 3B, 3C, 3D", line)


if __name__ == "__main__":
    unittest.main()
