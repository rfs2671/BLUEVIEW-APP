"""A TAG WITH NO REGION MARKS THE SHEET INCOMPLETE - AND THE PLAN'S TAG IS
READ, NOT THE TABLE'S.

Measured 2026-10-24 over every architectural plan sheet with unit tags (22
read, 15 tagged): on the filed mezzanine A-104.00 (AR 3.28.25 p15) and the
second set's A.1.5, the occupancy table sits inside the plan's corner extent
and comes first, so plan_unit_tags "placed" 4A-4D in table cells outside the
building. Those 8 tags then got NO region and the sheet said nothing: not
refused, not incomplete. The fail-safe covered a tag on a wall, a merged
region and an empty one, but not a tag whose label lies outdoors, nor one the
plan never prints.

Rulings (operator, 2026-10-24):
  1. a tag with no region marks the sheet incomplete, saying why;
  2. the plan's tag over a table cell: an occurrence in a room of the plan is
     preferred; with none, the first in the extent stands, as before.

On Boyland's production sheets every tag was already the plan's, so the
rows do not change (the local pass reproduces expected_rows_v5.json).
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
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_sheet as PS, plan_derive as D  # noqa: E402
from lib import plan_space  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

TAGS = ["4A", "4B", "4C", "4D"]


def _present():
    assert hasattr(plan_space, "no_silent_miss"), \
        "a tag with no region still vanishes silently in this tree"


class ThePlansTagOverATablesCell(unittest.TestCase):

    CORNERS = np.array([[0, 0], [1000, 0], [0, 1400], [1000, 1400]] * 30, dtype=float)
    # the table's "4A" comes first in reading order, both inside the extent
    WORDS = [("4A", 300.0, 1300.0), ("4A", 500.0, 500.0)]

    def test_an_occurrence_in_a_room_is_preferred(self):
        _present()
        got = PS.plan_unit_tags(self.CORNERS, self.WORDS, ["4A"],
                                inside=lambda x, y: y < 1000)
        self.assertEqual(got, {"4A": (500.0, 500.0)})

    def test_with_no_room_map_the_first_stands(self):
        self.assertEqual(PS.plan_unit_tags(self.CORNERS, self.WORDS, ["4A"]),
                         {"4A": (300.0, 1300.0)})

    def test_with_no_occurrence_in_a_room_the_first_stands(self):
        _present()
        got = PS.plan_unit_tags(self.CORNERS, self.WORDS, ["4A"], inside=lambda x, y: False)
        self.assertEqual(got, {"4A": (300.0, 1300.0)})


class NoTagGoesMissingSilently(unittest.TestCase):

    def _space(self, **kw):
        return dict({"units": {"4A": np.ones((2, 2), bool)}, "refused": [], "incomplete": {},
                     "tags": {"4A": (1, 1), "4B": (900, 1300)}}, **kw)

    def test_a_tag_whose_label_is_in_no_room(self):
        _present()
        out = plan_space.no_silent_miss(self._space(), ["4A", "4B"])
        self.assertIn("4B", out["incomplete"])
        self.assertIn("in no room of the plan", out["incomplete"]["4B"])
        self.assertNotIn("4A", out["incomplete"])

    def test_a_tag_the_plan_never_prints(self):
        _present()
        out = plan_space.no_silent_miss(self._space(), ["4A", "4C"])
        self.assertIn("not printed on the plan", out["incomplete"]["4C"])

    def test_a_tag_already_refused_or_incomplete_keeps_its_reason(self):
        _present()
        out = plan_space.no_silent_miss(
            self._space(refused=[(np.ones((2, 2), bool), ["UNKNOWN", "4B"])],
                        incomplete={"4C": "tag sits on a barrier cell - no room"}),
            ["4A", "4B", "4C"])
        self.assertNotIn("4B", out["incomplete"])
        self.assertEqual(out["incomplete"]["4C"], "tag sits on a barrier cell - no room")

    def test_build_space_applies_it_on_both_paths(self):
        _present()
        bare = {"units": {}, "refused": [], "incomplete": {}, "tags": {}}
        with patch.object(plan_space.layers, "build", lambda *a, **k: dict(bare)):
            got = plan_space.build_space(None, ["4A"], 56.0, sheet={"x": 1})
        self.assertIn("4A", got["incomplete"])
        with patch.object(plan_space.geometry, "build", lambda *a, **k: dict(bare)):
            got = plan_space.build_space(None, ["4A"], 56.0, sheet={"x": 1}, force_geometry=True)
        self.assertIn("4A", got["incomplete"])


def _build(pdf, page):
    from lib.plan_page import PlanPage
    pg = PlanPage(str(require_pdf(pdf)), page)
    try:
        s = PS.load_sheet(pg)
        u = D.unit_tags(s["words"], s["corners"])
        return u, plan_space.build_space(pg, u["tags"], 56.0, s)
    finally:
        pg.close()


class OnTheRealSheets(unittest.TestCase):

    def test_the_filed_mezzanine_reads_its_plan_tags(self):
        _present()
        u, sp = _build("AR - 3.28.25.pdf", 15)
        self.assertEqual(u["tags"], TAGS)
        self.assertEqual({t: (round(x), round(y)) for t, (x, y) in sp["tags"].items()},
                         {"4A": (1127, 559), "4B": (1127, 990), "4C": (1639, 559), "4D": (1639, 990)})
        self.assertEqual(sorted(sp["units"]), TAGS)
        self.assertEqual(sp["incomplete"], {})

    def test_the_second_sets_mezzanine_reads_its_plan_tags(self):
        _present()
        u, sp = _build("588 THOMAS BOYLAND ST SET_UPDATED.pdf", 15)
        self.assertEqual(sorted(sp["units"]), TAGS)
        self.assertEqual(sp["incomplete"], {})

    def test_productions_sheets_pick_what_they_picked(self):
        """Every tag on the sheets production places against was already the
        plan's: the positions are unchanged."""
        _present()
        from lib.plan_page import PlanPage
        for pdf, page in (("AR - 8.18.26.pdf", 6), ("Owners set - 6.9.26.pdf", 2),
                          ("Owners set - 6.9.26.pdf", 3), ("Owners set - 6.9.26.pdf", 4)):
            pg = PlanPage(str(require_pdf(pdf)), page)
            try:
                s = PS.load_sheet(pg)
                u = D.unit_tags(s["words"], s["corners"])
                before = PS.plan_unit_tags(s["corners"], s["words"], u["tags"])
                sp = plan_space.build_space(pg, u["tags"], 56.0, s)
            finally:
                pg.close()
            self.assertEqual(sp["tags"], before, f"{pdf} p{page}")
            self.assertEqual(sp["incomplete"], {}, f"{pdf} p{page}")


if __name__ == "__main__":
    unittest.main()
