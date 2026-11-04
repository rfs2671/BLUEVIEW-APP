"""A DOOR DRAWN ON A REMOVAL LAYER IS NOT A DOOR SYMBOL.

Ruling 109 (Roy, 2026-10-29): "yes, separate PR checked by the door probe" -
to "floor_records still offers A-DOOR-DEMO ink as door symbols; a demolished
door with no tag is then an UNREAD row and refuses its family's floor
figure. Should it stop?"

Rules under test:
  - ink on a removal layer (plan_space_layers.is_removal_layer: TO REMOVE,
    *-DEMO) is never a door/window symbol in floor_records: an untagged
    A-DOOR-DEMO door is no UNREAD row, and a tag beside one does not take it
    as its own door;
  - an EXISTING door layer (A-DOOR-EXST) is still a door;
  - the rows of a plan are byte-identical with or without its -DEMO ink;
  - the gate binds the floor figure the -DEMO door used to refuse.

MEASURED ON BOYLAND (bv-worktrees/TR3/_lane): no architectural plan of either
track carries a door/window layer that is also a removal layer, so no row
changes there (the local two-track pass, main vs branch, and the L2 door probe).
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_openings as P  # noqa: E402
from lib import plan_search as S  # noqa: E402
from lib import plan_space_layers as SL  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

INT, WIN = "INTERIOR DOOR SCHEDULE", "WINDOW SCHEDULE"
FAMS = {INT: {"tags": list("ABCDEFG"), "kind": "door", "sheet": "A-400.00"},
        WIN: {"tags": ["W1", "W2", "W3"], "kind": "window", "sheet": "A-400.00"}}
DOOR, GLAZ = "XR FLOOR PLANS|A-Door", "XR FLOOR PLANS|A-Glaz"
DOOR_DEMO, GLAZ_DEMO = "XR FLOOR PLANS|A-DOOR-DEMO", "XR FLOOR PLANS|A-GLAZ-DEMO"


def _path(layer, pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"layer": layer, "items": [("l", pts[i], pts[i + 1]) for i in range(len(pts) - 1)],
            "rect": (min(xs), min(ys), max(xs), max(ys)), "colour": (0, 0, 0)}


def _box(layer, x0, y0, x1, y1):
    return _path(layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


class _Page:
    def __init__(self, drawings, words):
        self.drawings, self.words = drawings, words

    def close(self):
        pass


def _tag(text, x, y, layer="XR FLOOR PLANS|A-DOOR-IDEN"):
    return _box(layer, x - 6, y - 6, x + 6, y + 6), (text, x, y)


def _plan(extra=()):
    """E owns its door, W1 its window; `extra` drawings are added."""
    tags = [_tag("E", 200, 100), _tag("W1", 400, 100, "XR FLOOR PLANS|A-WINDOW-IDEN")]
    drawings = [d for d, _w in tags] + [_box(DOOR, 190, 115, 215, 135),
                                        _box(GLAZ, 390, 112, 410, 118)]
    return _Page(drawings + list(extra), [w for _d, w in tags])


def _unread(got):
    return [r for rs in got["records"].values() for r in rs if r.get("glyph_status") == "unread"]


def _arch():
    return {"project_id": "p1", "company_id": "c1", "file_id": "f1", "file_hash": "h",
            "file_name": "AR.pdf", "page_id": "pg-a100", "page_number": 1,
            "sheet_number": "A-100.00", "sheet_title": "FIRST FLOOR PLAN",
            "discipline": "architectural", "drawing_track": "filed",
            "drawing_track_label": None}


def _run(page):
    floors = [{"arch_p": _arch(), "a_sheet": "A-100.00",
               "units": {"tags": None, "why": "test: sheet scope"}, "space": None}]
    return P.run_openings(floors, lambda _p: page, FAMS, track="filed")


class ADemoDoorIsNoSymbol(unittest.TestCase):

    def test_an_untagged_demo_door_is_no_unread_row(self):
        got = P.floor_records(_plan([_box(DOOR_DEMO, 700, 700, 725, 720)]), FAMS, None, "t")
        self.assertEqual(got["untagged"], [], "an A-DOOR-DEMO door was read as a door symbol")
        self.assertEqual(_unread(got), [])

    def test_an_untagged_demo_window_is_no_unread_row(self):
        got = P.floor_records(_plan([_box(GLAZ_DEMO, 700, 700, 725, 706)]), FAMS, None, "t")
        self.assertEqual(got["untagged"], [], "an A-GLAZ-DEMO window was read as a symbol")
        self.assertEqual(_unread(got), [])

    def test_a_tag_beside_only_a_demo_door_does_not_take_it(self):
        """F's only nearby door is on A-DOOR-DEMO: F is read (it counts) but
        has no symbol - it is not placed on the demolished door."""
        f = _tag("F", 100, 100)
        page = _Page([f[0], _box(DOOR_DEMO, 90, 115, 115, 135)], [f[1]])
        got = P.floor_records(page, FAMS, None, "t")
        rec = [r for r in got["records"][INT] if r.get("label_text") == "F"]
        self.assertEqual(len(rec), 1, rec)
        self.assertIsNone(rec[0]["symbol_at"], "F took the A-DOOR-DEMO door as its own")

    def test_an_existing_door_layer_is_still_a_door(self):
        """-EXST is work that stays: an untagged A-DOOR-EXST door is still a
        symbol no tag names (one UNREAD row per door family)."""
        self.assertFalse(SL.is_removal_layer("XR FLOOR PLANS|A-DOOR-EXST"))
        got = P.floor_records(_plan([_box("XR FLOOR PLANS|A-DOOR-EXST", 700, 700, 725, 720)]),
                              FAMS, None, "t")
        self.assertEqual(len(got["untagged"]), 1)
        self.assertEqual(len(_unread(got)), 1)

    def test_the_rows_are_identical_with_or_without_the_demo_ink(self):
        dump = lambda x: json.dumps(x, sort_keys=True, default=str)  # noqa: E731
        a = _run(_plan())
        b = _run(_plan([_box(DOOR_DEMO, 700, 700, 725, 720), _box(GLAZ_DEMO, 800, 700, 825, 706)]))
        self.assertEqual(dump(a["rows"]), dump(b["rows"]))
        self.assertEqual(dump(a["summary"]), dump(b["summary"]))


class TheGateBindsWhatTheDemoDoorRefused(unittest.TestCase):

    def test_the_floor_figure_binds(self):
        out = _run(_plan([_box(DOOR_DEMO, 700, 700, 725, 720)]))
        rows = out["rows"]
        for i, r in enumerate(rows):
            r["ordinal"] = i
        pages = sorted({r["page_id"] for r in rows})
        recs = list(rows)
        for name in (INT, WIN):
            c = S.glyph_census("family", "p1", pages, 0, family=name, tags=FAMS[name]["tags"],
                               track="filed", scope=S.OPENING)
            c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
            recs.append(c)
        c = S.glyph_census("refusals", "p1", pages, 0, track="filed", scope=S.OPENING)
        c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
        recs.append(c)
        ok, _why = S.answer_is_grounded("There is 1 type E door.", recs, intent="count")[:2]
        self.assertTrue(ok, f"the type E door figure is refused: {_why}")
        self.assertFalse(S.answer_is_grounded("There are 2 type E doors.", recs,
                                              intent="count")[0])


# ── the drawings themselves ────────────────────────────────────────────────

def _page(name, number):
    from lib.plan_page import PlanPage
    return PlanPage(str(require_pdf(name)), number)


class OnTheBoylandSet(unittest.TestCase):

    def test_no_architectural_plan_draws_a_door_on_a_removal_layer(self):
        """Every plan both tracks' openings pass reads (and the plans under
        the set questions): no layer is both a door/window layer and a
        removal layer - so no Boyland row changes."""
        plans = [("Owners set - 6.9.26.pdf", n) for n in range(1, 7)]
        plans += [("AR - 8.18.26.pdf", 6), ("AR - 8.18.26.pdf", 7)]
        plans += [("AR - 3.28.25.pdf", n) for n in range(11, 17)]
        plans += [("588 THOMAS BOYLAND ST SET_UPDATED.pdf", n) for n in range(11, 18)]
        plans += [("AR - 6.9.26 (Gas change).pdf", 1), ("AR - 6.9.26 (Gas change).pdf", 2)]
        read = 0
        for name, number in plans:
            pg = _page(name, number)
            layers = {d.get("layer") or "" for d in pg.drawings}
            read += any(P._symbol_kind(L) for L in layers)
            both = sorted(L for L in layers if P._symbol_kind(L) and SL.is_removal_layer(L))
            self.assertEqual(both, [], (name, number))
        # every plan but A.1.7 (11 layers, no door/window layer) has door ink
        self.assertEqual(read, len(plans) - 1, "the plans were not read")


if __name__ == "__main__":
    unittest.main()
