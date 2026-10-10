"""AN UNREAD MECHANICAL PLAN IS VISIBLE, NOT ABSENT.

The pairing recognises a mechanical plan only by its number in the NCS plan
series (M-1xx.yy). A mechanical plan numbered any other way - M101, M1.01,
unnumbered - was SKIPPED: no glyph row and no refusal row. A whole set
numbered that way would produce nothing and say nothing, and a building total
could read as complete over sheets nobody looked at.

Rule (operator, 2026-10-10): such a sheet produces a refusal row naming it,
with the role MECHANICAL - it may carry symbols, so no building total stands
without it.

Measured first on 588 Boyland's current pages: every mechanical plan is
M-1xx.yy, and the other mechanical sheets (notes and symbol list, schedules,
details) never say PLAN - so ZERO sheets newly get a refusal there, and the
rebuilt rows are unchanged.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_derive as D  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.test_a_placement_is_stored_not_just_computed import BOYLAND, _pages  # noqa: E402
from tests.test_a_located_count_is_complete_or_refused import PID  # noqa: E402


def _present():
    assert hasattr(D, "looks_like_a_mechanical_plan"), \
        "an unread mechanical plan is still skipped in this tree"


def _page(num, title, disc="ME", i=0):
    return {"sheet_number": num, "sheet_title": title, "discipline": disc, "page_id": f"x{i}"}


def _refused(pages):
    return {(p.get("sheet_number"), role): why
            for p, why, role in D.pair_plan_sheets(pages)["refused"]}


class AMechanicalPlanNumberedAnotherWayIsRefusedByName(unittest.TestCase):

    def test_m101_and_m1_01_and_unnumbered(self):
        _present()
        got = _refused([_page("M101", "FIRST FLOOR HVAC PLAN", i=1),
                        _page("M1.01", "SECOND FLOOR MECHANICAL PLAN", i=2),
                        _page(None, "ROOF HVAC PLAN", i=3)])
        self.assertEqual(set(got), {("M101", D.ROLE_MECHANICAL), ("M1.01", D.ROLE_MECHANICAL),
                                    (None, D.ROLE_MECHANICAL)})
        self.assertIn("M101 (FIRST FLOOR HVAC PLAN) looks like a mechanical plan",
                      got[("M101", D.ROLE_MECHANICAL)])
        self.assertIn("not in the plan series M-1xx.yy", got[("M101", D.ROLE_MECHANICAL)])

    def test_an_unnumbered_hvac_plan_is_mechanical_not_architectural(self):
        """It was refused as ARCHITECTURAL before, which a building total does
        not wait for - though the sheet may carry every symbol on its level."""
        _present()
        self.assertEqual(set(_refused([_page(None, "ROOF HVAC PLAN")])),
                         {(None, D.ROLE_MECHANICAL)})


class WhatIsNotAMechanicalPlanStaysUnrefused(unittest.TestCase):

    def test_notes_schedules_and_details(self):
        _present()
        pages = [_page("M001", "GENERAL NOTES, HVAC NOTES AND SYMBOL LIST", i=1),
                 _page("M200", "HVAC SCHEDULES AND DETAILS", i=2),
                 _page("M201", "HVAC DETAILS", i=3),
                 _page("P-101.00", "SECOND FLOOR DOMESTIC WATER & GAS PLANS", "PL", 4),
                 _page("FA-007", "ROOF FIRE ALARM PLAN", "FA", 5)]
        self.assertEqual(_refused(pages), {})

    def test_boyland_gets_no_new_refusal(self):
        """The measurement, held: the same refusals as before - the second
        set's A.1.x and the unnumbered architectural roof plan - and none
        mechanical."""
        _present()
        got = _refused(_pages(BOYLAND))
        self.assertEqual(set(got), {("A.1.1", D.ROLE_ARCHITECTURAL),
                                    ("A.1.4", D.ROLE_ARCHITECTURAL),
                                    (None, D.ROLE_ARCHITECTURAL)})


class ThePassWritesItAndTheBuildingWaitsForIt(unittest.TestCase):

    def test_a_refusal_row_with_the_mechanical_role(self):
        _present()
        from lib import plan_glyph_pass as G

        class Page:
            directed_words = []
        schedules = [{"name": "EXHAUST FAN SCHEDULE", "tier": "ocr_grid_cell",
                      "sheet_number": "M-200.00",
                      "columns": [{"header": "TAG", "role": "identifier"}],
                      "rows": [["EF-1"]]}]
        pages = [_page("M101", "FIRST FLOOR HVAC PLAN", i=1)]
        with patch("lib.plan_takeoff.run_takeoff") as takeoff:
            out = G.run_pass(pages, lambda p: Page(), schedules, [])
        takeoff.assert_not_called()
        (row,) = out["rows"]
        self.assertEqual((row["sheet_number"], row["payload"]["role"]), ("M101", D.ROLE_MECHANICAL))
        self.assertIn("looks like a mechanical plan", row["payload"]["refusal"])

    def test_a_building_total_waits_for_it(self):
        _present()
        from tests.test_a_sheet_it_cannot_place_still_counts import _boyland, QTY
        # without it, the building total stands (only architectural refusals)
        self.assertTrue(S.answer_is_grounded("There are 36 exhaust fans.",
                                             _boyland(qty=QTY), intent="count")[0])
        page = {"project_id": PID, "page_id": "pg-M101", "page_number": 3,
                "sheet_number": "M101", "sheet_title": "FIRST FLOOR HVAC PLAN"}
        refusal = E.sheet_refusal(page, "M101 looks like a mechanical plan, but its number "
                                        "is not in the plan series M-1xx.yy",
                                  pass_key="refusal|M101", role=D.ROLE_MECHANICAL)
        recs = _boyland(qty=QTY, refusals=[refusal])
        self.assertFalse(S.answer_is_grounded("There are 36 exhaust fans.", recs,
                                              intent="count")[0])


if __name__ == "__main__":
    unittest.main()
