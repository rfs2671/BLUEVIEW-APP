"""A door's JAMB RETURN is wall (lib.plan_walls; 588 Boyland A-100.00 east door D2).

Measured (bv-worktrees/wallsjamb/REPORT.md): the first-floor plan draws the
east wall's exterior door D2 with the wall's inner face running on past each
side of the doorway as a 1" stub (y 31.103-31.187 and 34.52-34.603 ft). The
face-line floor (MIN_FACE_IN, 2") dropped both, so the east wall run stopped
at the T where interior wall P2 meets it, and the doorway, the jambs and the
corner were three separate "no wall" stretches.

What this guards:

  * a face stub shorter than MIN_FACE_IN that ENDS ON A DOOR'S EDGE, beside the
    door and across its width, is a jamb return: a wall piece, joined to the
    run it continues across the T (or the doorway);
  * only that: a short stroke anywhere else (the exterior walls' 1.7" hatch)
    is still not a face;
  * a jamb return that joins no wall is listed as a short piece and counted
    nowhere - it is never a wall row of its own;
  * on the real first-floor plans (gas change, owner's set) the east W1 wall
    carries the two jamb pieces: 6 pieces, 27.0 LF, 3.33 ft of doorway.

WRITTEN TO FAIL BY ASSERTION on a tree without the fix: every test reads the
walls through floor_walls and asserts on what they say.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402
from tests.test_walls_are_measured_by_type import (  # noqa: E402
    DOOR, Q, WALL, _draw, _pw, _seg, build, h_wall, tag, typed)

#: 1 inch of paper, and the wall used below: 10" thick (15 pt), inner face X,
#: outer face X + 15.
IN = Q
X = 1000.0


def _east_wall(north_stub=True, south_stub=True, door=True, door_at=None, extra=()):
    """A vertical wall (inner face x=X, outer face x=X+15):

        y 100..400   both faces                      (the long piece)
        y 400..409   a 6" interior wall's T square: its faces end on the inner
                     face; the inner face is interrupted for its thickness
        y 409..410.5 the south jamb return (1"): inner face stub, outer continues
        y 410.5..470.5  the doorway (40"): outer face stops; the door is drawn
        y 470.5..472 the north jamb return (1")
        outer face continues to 700 (the exterior skin past the corner)
    """
    t = 10 * IN
    d = [_draw(WALL, _seg(X, 100, X, 400), _seg(X + t, 100, X + t, 410.5)),
         _draw(WALL, _seg(X + t, 470.5, X + t, 700))]
    # the T: a 6" wall's two faces ending on the inner face
    d.append(_draw(WALL, _seg(X - 300, 400, X, 400), _seg(X - 300, 409, X, 409)))
    if south_stub:
        d.append(_draw(WALL, _seg(X, 409, X, 410.5)))
    if north_stub:
        d.append(_draw(WALL, _seg(X, 470.5, X, 472)))
    if door:
        x0, ya, yb = door_at if door_at else (X - 60, 410.5, 470.5)
        # leaf at the hinge + swing: the door's box spans the doorway
        d.append(_draw(DOOR, *_box(x0, ya, X + t, yb)))
    d += list(extra)
    return d


def _box(x0, y0, x1, y1):
    """A closed outline (the door's swing box) as one connected path."""
    return [_seg(x0, y0, x1, y0), _seg(x1, y0, x1, y1), _seg(x1, y1, x0, y1), _seg(x0, y1, x0, y0)]


def _walls(drawings, words=()):
    return build(drawings, list(words), door=56.0)


def _tagged(drawings):
    dg, w = tag("W1", 900, 250, leader_to=(X + 7, 250))
    return _walls(drawings + [dg], [w])


def _rects(wall):
    return sorted(tuple(round(v, 1) for v in r) for r in wall["pieces"])


class AJambReturnIsAWallPiece(unittest.TestCase):

    def test_the_two_jamb_returns_are_pieces_of_the_wall_they_continue(self):
        res = _tagged(_east_wall())
        w1 = typed(res, "W1")
        self.assertEqual(len(w1), 1, [(w["type"], w["lf"]) for w in res["walls"]])
        rects = _rects(w1[0])
        self.assertIn((X, 409.0, X + 15.0, 410.5), rects, rects)       # south jamb
        self.assertIn((X, 470.5, X + 15.0, 472.0), rects, rects)       # north jamb
        self.assertEqual(len(rects), 3, rects)

    def test_the_run_reaches_through_the_t_and_the_doorway(self):
        res = _tagged(_east_wall())
        w = typed(res, "W1")[0]
        # 100..400 (16.667 ft) + the T square 0.5 + two 1" returns 0.1667; the 40" doorway is reported, not in lf
        self.assertEqual(w["lf"], 17.33, w)
        self.assertEqual(w["opening_lf"], 3.33, w)
        self.assertEqual(res["untyped_lf"], 16.67)               # the T wall, untagged: nothing else

    def test_without_the_jamb_stubs_nothing_is_added(self):
        # same layout, no returns drawn: the run is the long piece only (no stray piece)
        res = _tagged(_east_wall(north_stub=False, south_stub=False))
        w = typed(res, "W1")[0]
        self.assertEqual(len(w["pieces"]), 1, _rects(w))
        self.assertEqual(w["lf"], 16.67, w)


class OnlyAStubAtADoorsEdgeIsAJamb(unittest.TestCase):

    def test_a_short_stroke_that_ends_on_no_door_is_not_a_face(self):
        # the same stub, but the door is elsewhere (40" up the wall): it ends on no door's edge
        res = _tagged(_east_wall(door_at=(X - 60, 600.0, 660.0)))
        w = typed(res, "W1")[0]
        self.assertNotIn((X, 409.0, X + 15.0, 410.5), _rects(w), _rects(w))

    def test_a_stub_across_the_doors_width_but_beside_nothing_is_not_a_face(self):
        # a 1" stub whose end is on the door's edge but INSIDE the door's extent (the leaf's own line) is the door
        res = _tagged(_east_wall(south_stub=False, north_stub=False,
                                 extra=[_draw(WALL, _seg(X, 420, X, 421.5))]))
        w = typed(res, "W1")[0]
        self.assertEqual(len(w["pieces"]), 1, _rects(w))

    def test_the_exterior_walls_hatch_strokes_are_still_not_faces(self):
        # 1.7" strokes on the skins' lines, beside a door
        hatch = [_draw(WALL, *[_seg(X - 20, y, X - 20 + 1.7 * IN, y) for y in range(440, 480, 4)])]
        res = _tagged(_east_wall(extra=hatch))
        w = typed(res, "W1")[0]
        self.assertEqual(len(w["pieces"]), 3, _rects(w))


class ALoneJambReturnIsNoWall(unittest.TestCase):

    def test_a_return_that_joins_no_wall_is_a_short_piece_not_a_wall_row(self):
        # only the north return and the door: the 1" band has no wall to continue
        t = 10 * IN
        d = [_draw(WALL, _seg(X + t, 470.5, X + t, 700), _seg(X, 470.5, X, 472)),
             _draw(DOOR, *_box(X - 60, 410.5, X + t, 470.5))]
        res = _walls(d)
        self.assertEqual(res["walls"], [], res["walls"])
        self.assertEqual(len(res["short_pieces"]), 1, res["short_pieces"])
        self.assertEqual(res["untyped_lf"], 0.0)


# ── the real plans ──────────────────────────────────────────────────────────

OX, OY = 751.08, 1109.70                   # the shared A-plan frame (model_export_v06 README)


def _pt(ft_x, ft_y):
    return OX + 18 * ft_x, OY - 18 * ft_y


def _boyland(name, page):
    from lib.plan_page import PlanPage
    pw = _pw("floor_walls")
    pg = PlanPage(str(require_pdf(name)), page)
    return pw.floor_walls(pg, widest_door_in=56.0)


def _east_w1(res):
    cx = OX + 18 * 69.4165
    hits = [w for w in res["walls"] if w["axis"] == "v" and abs(w["center_pt"] - cx) < 1.0 and w["type"] == "W1"
            and any(r[1] <= _pt(0, 25.0)[1] <= r[3] for r in w["pieces"])]
    assert len(hits) == 1, [(w["center_pt"], w["lf"], w["type"]) for w in res["walls"] if w["axis"] == "v"]
    return hits[0]


class TheFirstFloorEastDoorD2(unittest.TestCase):
    """Gas change A-100.00 p1 (filed) and the owner's A-100.00 p1 (post-CO): the same east wall."""

    def _check(self, name):
        w = _east_w1(_boyland(name, 1))
        ys = sorted(round(18 * 0 + (OY - (r[1] + r[3]) / 2) / 18, 2) for r in w["pieces"])
        # six pieces: 4.27-5.77, 6.27-11.27, 11.77-19.77, 20.27-30.61 and the two 1" jamb returns
        self.assertEqual(len(w["pieces"]), 6, ys)
        self.assertTrue(any(abs(y - 31.15) < 0.05 for y in ys), ys)       # south jamb return
        self.assertTrue(any(abs(y - 34.56) < 0.05 for y in ys), ys)       # north jamb return
        self.assertEqual(w["lf"], 27.0, w)
        self.assertEqual(w["opening_lf"], 3.33, w)                        # D2's 40" doorway, reported not counted

    def test_filed_gas_change(self):
        self._check("AR - 6.9.26 (Gas change).pdf")

    def test_post_co_owners_set(self):
        self._check("Owners set - 6.9.26.pdf")


if __name__ == "__main__":
    unittest.main()
