"""AN OPEN-TO-BELOW VOID JOINS THE UNIT BENEATH IT.

The filed mezzanine A-104.00 (AR 3.28.25) walls off four bays open to the
bedrooms below; M-104.00 hangs a PTAC-1 on the wall of each, and all four
were refused ("unnamed, doorless non-unit region"), so the filed track had no
PTAC figure for 4A-4D.

Ruling 2026-10-24: a region is MARKED open-to-below if EITHER (a) text
inside it reads OPEN TO BELOW / OPEN BELOW / O.T.B. / VOID, or (b) an X -
two diagonals joining its opposite corners, within registration tolerance -
is drawn on a layer whose name contains BELOW, OPEN or VOID. NOT a void: an
X on any other layer or none; SHAFT / CHASE / ELEV text; an X that does not
span the region. Then: registration to the floor below usable, exactly one
unit beneath, the symbol assigned to that unit.

Measured 2026-10-24 on every A-1xx plan of both tracks: the filed A-104.00
draws 14 X's, all on "XR FLOOR PLANS|A-BELOW"; 4 span their own region - the
four bays, 97% over 4A, 4B, 4C and 4D - and 10 sit inside 4A-4D's own
regions; the light shaft's A-BELOW X has no unit beneath it. Every other X
is on A-ABOVE, A-Wall or SECTION CUT.
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

from lib import plan_glyph_pass as G  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

BELOW = "XR FLOOR PLANS|A-BELOW"
CELL = 3.0                                   # 2 in at 1/4" = 1'-0"
VOID = (10, 60, 51, 80)                      # the void's cells: cols 10-59, rows 51-79
BOX = (VOID[0] * CELL, VOID[2] * CELL, VOID[1] * CELL, VOID[3] * CELL)   # (30, 153, 180, 240)


def _present():
    assert hasattr(G, "assign_voids"), "no open-to-below void joins a unit in this tree"


def _x(layer=BELOW, box=BOX, diagonals=2):
    x0, y0, x1, y1 = box
    segs = [((x0, y0, x1, y1), layer), ((x0, y1, x1, y0), layer)]
    return segs[:diagonals]


def _upper(*, words=(), att=None, tags=("4A",)):
    """A-104.00: 4A above the wall row 50, the walled void below it."""
    lab = np.zeros((100, 100), int)
    lab[0:50, :] = 1
    c0, c1, r0, r1 = VOID
    lab[r0:r1, c0:c1] = 2
    units = {"4A": lab == 1} if "4A" in tags else {}
    space = {"closed_lab": lab, "lo": (0.0, 0.0), "cell_pt": CELL, "units": units,
             "public": np.zeros_like(lab, bool), "outdoors": []}
    return {"arch_p": {"sheet_number": "A-104.00", "sheet_title": "MEZZANINE PLAN"},
            "a_sheet": "A-104.00", "space": space,
            "data": {"words": list(words), "att": _x() if att is None else att},
            "units": {"tags": list(tags), "multi_level": {}}}


def _lower(beneath=("4A",)):
    """A-103.00: what lies under the void - one unit, two, or none."""
    lab = np.zeros((100, 100), int)
    lab[0:50, :] = 1
    lab[51:100, 0:35] = 2
    lab[51:100, 35:100] = 3
    units = {}
    if beneath == ("4A",):
        units = {"4A": lab > 0}
    elif beneath == ("4A", "4B"):
        units = {"4A": (lab == 1) | (lab == 2), "4B": lab == 3}
    space = {"closed_lab": lab, "lo": (0.0, 0.0), "cell_pt": CELL, "units": units,
             "public": np.zeros_like(lab, bool) if units else lab > 0, "outdoors": []}
    return {"arch_p": {"sheet_number": "A-103.00", "sheet_title": "FOURTH FLOOR PLAN"},
            "a_sheet": "A-103.00", "space": space, "data": {"words": [], "att": []},
            "units": {"tags": list(beneath), "multi_level": {}}}


def _assign(upper, lower=None, usable=True):
    lower = lower or _lower()
    with patch("lib.plan_sheet.register",
               lambda a, b: {"dx": 0.0, "dy": 0.0, "usable": usable,
                             "refused": None if usable else "under half the best peak"}):
        notes = G.assign_voids([lower, upper])
    void = upper["space"]["closed_lab"] == 2
    joined = bool(upper["space"]["units"].get("4A", np.zeros_like(void))[void].all())
    return joined, notes


class MarkedOpenToBelow(unittest.TestCase):

    def test_b_an_x_on_a_below_layer_joins_the_unit_beneath(self):
        _present()
        up = _upper()
        joined, notes = _assign(up)
        self.assertTrue(joined, notes)
        (v,) = up["units"]["voids"]["4A"]
        self.assertEqual((v["marked_by"], v["below"]), ("x", "A-103.00"))

    def test_b_open_and_void_layers_count_too(self):
        _present()
        for layer in ("A-OPEN", "Z-VOID-HATCH"):
            joined, notes = _assign(_upper(att=_x(layer)))
            self.assertTrue(joined, (layer, notes))

    def test_a_text_inside_the_region_joins_it(self):
        _present()
        for text in (["OPEN", "TO", "BELOW"], ["OPEN", "BELOW"], ["O.T.B."], ["VOID"]):
            words = [(w, 60.0 + 20 * i, 200.0) for i, w in enumerate(text)]
            up = _upper(words=words, att=[])
            joined, notes = _assign(up)
            self.assertTrue(joined, (text, notes))
            self.assertEqual(up["units"]["voids"]["4A"][0]["marked_by"], "text")


class NotAVoid(unittest.TestCase):
    """Each refuses on its own: the region stays out of every unit."""

    def test_an_x_on_another_layer(self):
        _present()
        joined, notes = _assign(_upper(att=_x("XR FLOOR PLANS|A-ABOVE")))
        self.assertFalse(joined, notes)
        self.assertTrue(any("no BELOW/OPEN/VOID layer" in n for n in notes), notes)

    def test_an_x_on_no_layer_and_no_text(self):
        _present()
        joined, notes = _assign(_upper(att=_x("")))
        self.assertFalse(joined, notes)

    def test_shaft_chase_or_elev_text(self):
        _present()
        for word in ("SHAFT", "CHASE", "ELEV."):
            joined, notes = _assign(_upper(words=[(word, 100.0, 200.0)]))
            self.assertFalse(joined, (word, notes))
            self.assertTrue(any("not a void" in n for n in notes), notes)

    def test_one_diagonal_only(self):
        _present()
        joined, notes = _assign(_upper(att=_x(diagonals=1)))
        self.assertFalse(joined, notes)

    def test_an_x_that_stops_short_of_the_corners(self):
        _present()
        x0, y0, x1, y1 = BOX
        joined, notes = _assign(_upper(att=_x(box=(x0 + 20, y0 + 12, x1 - 20, y1 - 12))))
        self.assertFalse(joined, notes)

    def test_no_room_map(self):
        _present()
        up = _upper()
        up["space"]["closed_lab"] = None
        with patch("lib.plan_sheet.register", lambda a, b: {"dx": 0, "dy": 0, "usable": True}):
            self.assertEqual(G.assign_voids([_lower(), up]), [])


class TheFloorBelow(unittest.TestCase):

    def test_registration_unusable(self):
        _present()
        joined, notes = _assign(_upper(), usable=False)
        self.assertFalse(joined, notes)
        self.assertTrue(any("does not register" in n for n in notes), notes)

    def test_two_units_beneath(self):
        _present()
        joined, notes = _assign(_upper(), _lower(("4A", "4B")))
        self.assertFalse(joined, notes)
        self.assertTrue(any("lie 4A, 4B - exactly one unit" in n for n in notes), notes)

    def test_no_unit_beneath(self):
        _present()
        joined, notes = _assign(_upper(), _lower(()))
        self.assertFalse(joined, notes)
        self.assertTrue(any("lie no unit" in n for n in notes), notes)

    def test_a_unit_this_sheet_does_not_name(self):
        _present()
        up = _upper(tags=("4B",))
        up["space"]["units"] = {"4B": up["space"]["closed_lab"] == 1}
        with patch("lib.plan_sheet.register", lambda a, b: {"dx": 0.0, "dy": 0.0, "usable": True}):
            notes = G.assign_voids([_lower(), up])
        self.assertNotIn("voids", up["units"])
        self.assertTrue(any("names no 4A" in n for n in notes), notes)


# ── the filed sheets ──────────────────────────────────────────────────────

class OnTheFiledMezzanine(unittest.TestCase):
    """The filed A-103.00 and A-104.00 (AR 3.28.25 p14, p15) through the
    pass's own pre-pass and assign_voids, then M-104.00 (MH 7.2.26 p6)
    placed against the result: the four PTAC-1 the bays hold are 4A-4D's."""

    def test_the_four_bays_and_their_ptacs(self):
        _present()
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet
        from lib.plan_space import build_space
        from lib.plan_takeoff import Units, run_takeoff
        from lib import plan_derive as D
        ar, mh = str(require_pdf("AR - 3.28.25.pdf")), str(require_pdf("MH - 7.2.26.pdf"))
        pages = []
        try:
            floors = []
            for n, sheet, title in ((14, "A-103.00", "FOURTH FLOOR PLAN"),
                                    (15, "A-104.00", "MEZZANINE PLAN")):
                pg = PlanPage(ar, n)
                pages.append(pg)
                data = load_sheet(pg)
                u = D.unit_tags(data["words"], data["corners"])
                sp = build_space(pg, u["tags"], 56.0, data)
                floors.append({"arch_p": {"sheet_number": sheet, "sheet_title": title},
                               "a_sheet": sheet, "data": data, "space": sp, "page": pg,
                               "units": dict(u, multi_level={})})
            notes = G.assign_voids(floors)
            a104 = floors[1]
            voids = a104["units"].get("voids") or {}
            self.assertEqual(sorted(voids), ["4A", "4B", "4C", "4D"], notes)
            for u, (v,) in voids.items():
                self.assertEqual((v["marked_by"], v["below"]), ("x", "A-103.00"), u)
                self.assertGreaterEqual(v["beneath_pct"], 95, u)
            self.assertTrue(any("lie no unit" in n for n in notes), notes)   # the light shaft
            m104 = PlanPage(mh, 6)
            pages.append(m104)
            sp = a104["space"]
            res = run_takeoff(a104["page"], m104, ["PTAC-1", "PTAC-2", "PTAC-3"], {},
                              sorted(sp["units"]), 56.0, space=sp)
            ptac1 = sorted(r["unit"] or "-" for r in res["records"] if r["tag"] == "PTAC-1")
            self.assertEqual(ptac1, ["4A", "4B", "4C", "4D"], res.get("unavailable"))
        finally:
            for pg in pages:
                pg.close()


if __name__ == "__main__":
    unittest.main()
