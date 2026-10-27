"""An apartment's or a room's area binds only where the area the plan prints
for it and the area of the region the plan closes for it agree (operator's
rule, Roy 2026-10-26; lib.plan_areas): "agree binds, disagree withholds
both, like QTY."

  * AGREE: both figures bind - the printed one, and the measured one, which
    no quote prints.
  * DISAGREE: neither binds. The printed figure is in a quote the union of
    every returned number holds; it is withheld anyway.
  * NO PRINTED AREA: nothing binds. A measured figure is never said alone.
  * A REGION ON A VIEWPORT WHOSE SCALE DID NOT VERIFY (lib.plan_scale), or
    whose walls are ink of two drawings: no measured figure at all.
  * AREA_TOL is 2%, from the error budget and the measurement on 588
    Boyland (every agreement within 0.27%, the nearest disagreement +8.9%).

On 588 Boyland (measured 2026-10-26): the filed A-101.00 prints "NET: 482
SQ. FT." in 2A, whose region with its interior walls measures 481.8 at the
verified 1/4" (agrees); the Owner's set A-100.00 prints NET 338 in 1A, whose
post-CO region measures 451 (disagrees); a BEDROOM prints 96 - the 12'-0" x
8'-0" rectangle - and its closed room, closet front included, measures 104.5.

WRITTEN TO FAIL BY ASSERTION ON A TREE WITHOUT THE CHANGE: the gate tests
reach only plan_search (present on main) with area rows as plain records;
every test that needs lib.plan_areas reaches it through `_pa()`, which turns
a missing module or name into an AssertionError.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as S  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

QUARTER = 1.5               # 1/4" = 1'-0": paper points per real inch


def _pa(*names):
    try:
        mod = importlib.import_module("lib.plan_areas")
    except ImportError as e:
        raise AssertionError(f"lib.plan_areas is not importable: {e}")
    for n in names:
        assert hasattr(mod, n), f"lib.plan_areas has no {n}"
    return mod


# ── records as the pass writes them ───────────────────────────────────────

def _area(unit, status, printed, computed, *, scope="apartment", name="", sheet="A-101.00",
          track="filed", gross=None, why=""):
    diff = None if (printed is None or computed is None) else round(100 * (computed / printed - 1), 2)
    return {"project_id": "p", "page_id": f"pg-{sheet}", "sheet_number": sheet,
            "record_type": "area", "unit": unit, "status": status,
            "quote": (f"NET: {printed} SQ. FT." if scope == "apartment" else f"{name} {printed} SQ. FT.")
            if printed is not None else "",
            "payload": {"scope": scope, "name": name, "printed_sf": printed,
                        "computed_sf": computed, "diff_pct": diff, "gross_printed_sf": gross,
                        "viewport": {"note": '1/4" = 1\'-0"', "verified": True},
                        "why": why, "tolerance": 0.02, "track": track,
                        "drawing_track_label": None, "area_version": 1}}


def _note(sheet, quote):
    """The plan's own words, as the text pass records them."""
    return {"sheet_number": sheet, "record_type": "note", "tier": "text_layer", "quote": quote}


AGREE_2A = _area("2A", "agrees", 482, 481.8, gross=537)
AGREE_2C = _area("2C", "agrees", 467, 466.0)
DISAGREE_1A = _area("1A", "disagrees", 338, 451.0, sheet="A-100.00", track="post_co", gross=387)
NOPRINT_4A = _area("4A", "no_printed", None, 376.7, sheet="A-104.00", track="post_co")
REFUSED_4B = _area("4B", "refused", 160, None, sheet="A-104.00",
                   why="its viewport (MEZZANINE PLAN) is not verified: 2 of 9 measured dimensions agree")
BEDROOM_2A = _area("2A", "disagrees", 96, 104.5, scope="room", name="BEDROOM")
BIKE = _area(None, "agrees", 113, 113.3, scope="room", name="BIKE ROOM", sheet="A-100.01")

NOTES = [_note("A-101.00", "APT 2A 1 BEDROOM APT. NET: 482 SQ. FT. GROSS: 537 SQ. FT."),
         _note("A-101.00", "APT 2C 1 BEDROOM APT. NET: 467 SQ. FT. GROSS: 519 SQ. FT."),
         _note("A-100.00", "APT 1A STUDIO APT. NET: 338 SQ. FT. GROSS: 387 SQ. FT."),
         _note("A-101.00", "BEDROOM 96 SQ. FT."),
         _note("A-104.00", "APT 4B NET: 160 SQ. FT.")]
WORLD = NOTES + [AGREE_2A, AGREE_2C, DISAGREE_1A, NOPRINT_4A, REFUSED_4B, BEDROOM_2A, BIKE]


def _bound(text, records=WORLD, intent="attribute"):
    return S.answer_is_grounded(text, records, intent=intent)[0]


# ═══════════════════════════════════════════════════════════════════════════
# The gate
# ═══════════════════════════════════════════════════════════════════════════

class AgreeBinds(unittest.TestCase):
    def test_the_printed_figure_of_an_agreeing_apartment_binds(self):
        for intent in ("attribute", "count"):
            self.assertTrue(_bound("Apartment 2A is 482 sq ft [A-101.00].", intent=intent), intent)

    def test_the_measured_figure_binds_too_where_they_agree(self):
        # 2C prints 467; its region measures 466.0. No quote prints 466.
        for intent in ("attribute", "count"):
            self.assertTrue(_bound("2C measures 466 sq ft.", intent=intent), intent)

    def test_a_room_that_agrees_binds_by_its_name(self):
        self.assertTrue(_bound("The bike room is 113 sq ft."))

    def test_a_thousands_comma_is_one_figure(self):
        roof = _area(None, "agrees", 1970, 1970.5, scope="room", name="PASSIVE RECREATION",
                     sheet="A-105.01")
        self.assertTrue(_bound("The passive recreation area on the roof is 1,970 sq ft.",
                               records=[roof]))


class DisagreeWithholdsBoth(unittest.TestCase):
    def test_the_printed_figure_is_withheld_though_a_quote_prints_it(self):
        # The note on A-100.00 prints NET: 338 for 1A; the region measures 451.
        for intent in ("attribute", "count"):
            ok, bad = S.answer_is_grounded("Apartment 1A is 338 sq ft.", WORLD, intent=intent)
            self.assertFalse(ok, intent)
            self.assertIn("338", bad)

    def test_the_measured_figure_is_withheld(self):
        for intent in ("attribute", "count"):
            self.assertFalse(_bound("Apartment 1A is 451 sq ft.", intent=intent), intent)

    def test_the_gross_in_a_contradicted_box_is_withheld_with_it(self):
        self.assertFalse(_bound("Apartment 1A's gross area is 387 sq ft."))
        self.assertTrue(_bound("Apartment 2A's gross area is 537 sq ft."))

    def test_a_withheld_figure_is_not_stated_as_an_area_of_nothing_named(self):
        self.assertFalse(_bound("The apartment is 338 square feet."))

    def test_a_room_that_disagrees_withholds_its_printed_area(self):
        self.assertFalse(_bound("The bedroom in 2A is 96 sq ft."))

    def test_one_track_withholding_withholds_a_claim_naming_no_set(self):
        filed = _area("1A", "agrees", 338, 338.4, sheet="A-100.01", track="filed")
        both = NOTES + [filed, DISAGREE_1A]
        self.assertFalse(_bound("1A is 338 sq ft.", records=both))
        self.assertTrue(_bound("In the filed set 1A is 338 sq ft.", records=both))

    def test_the_fallback_render_does_not_repeat_a_withheld_figure_as_standing(self):
        text = S.render_records([NOTES[2], DISAGREE_1A], subject="apartment 1A area")
        self.assertIn("338", text)
        self.assertIn("not confirmed", text)
        self.assertNotIn("NET: 338 SQ. FT. [A-100.00]\n", text + "\n")


class NoPrintedAreaBindsNothing(unittest.TestCase):
    def test_a_measured_figure_alone_is_never_stated(self):
        for intent in ("attribute", "count"):
            self.assertFalse(_bound("4A on the mezzanine is 376.7 sq ft.", intent=intent), intent)
            self.assertFalse(_bound("4A on the mezzanine is 377 sq ft.", intent=intent), intent)


class AnUnmeasuredRegionChangesNothing(unittest.TestCase):
    """A refused row (no measured figure) neither adds nor withholds: the
    printed figure binds exactly as it did before - through a returned
    record that prints it, and not from the area row."""

    def test_a_quoted_printed_figure_still_binds(self):
        self.assertTrue(_bound("4B upper is 160 sq ft.", intent="attribute"))

    def test_the_area_row_alone_lends_it_nothing(self):
        for intent in ("attribute", "count"):
            self.assertFalse(_bound("4B upper is 160 sq ft.", records=[REFUSED_4B], intent=intent), intent)

    def test_an_unchecked_gross_is_not_lent_by_the_row(self):
        self.assertFalse(_bound("Apartment 2A's gross area is 537 sq ft.", records=[AGREE_2A]))


class NothingElseMoves(unittest.TestCase):
    def test_without_area_rows_the_gate_is_unchanged(self):
        self.assertTrue(_bound("Apartment 1A is 338 sq ft.", records=NOTES))
        self.assertFalse(_bound("Apartment 1A is 451 sq ft.", records=NOTES))

    def test_a_clause_that_is_not_about_an_area_keeps_the_union(self):
        self.assertTrue(_bound("1A is a studio and the sheet is A-100.00.", records=WORLD))
        self.assertFalse(_bound("There are 9 studios.", records=WORLD))


# ═══════════════════════════════════════════════════════════════════════════
# The check: a synthetic floor (lib.plan_areas.floor_areas)
# ═══════════════════════════════════════════════════════════════════════════

CELL = 3.0                                 # 2" at 1/4" = 1'-0"


class _Page:
    def __init__(self, boxes):
        self.directed_word_boxes = boxes


def _words(x, y, value, before="NET:"):
    """`before` <value> SQ. FT. on one line at (x, y), 8pt high."""
    out, cx = [], x
    for t in ([before] if before else []) + [str(value), "SQ.", "FT."]:
        w = 6.0 * len(t)
        out.append((t, cx, y, cx + w, y + 8.0, "ltr"))
        cx += w + 4.0
    return out


LEGEND = [('12"', 1500.0, 1400.0, 1510.0, 1408.0, "ltr"), ("STUD", 1514.0, 1400.0, 1540.0, 1408.0, "ltr")]


def _floor(*, verified=True, ppi=QUARTER, printed=None, split=False, two_bodies=False,
           room_text=None):
    """A 2A of 100 x 200 cells (16'-8" x 33'-4") inside a 3-cell wall ring,
    as plan_space returns it; the ring is ink of one viewport's drawing.
    `split`: a 2-cell wall across the middle with a doorway, two rooms of
    one apartment."""
    import numpy as np
    pa = _pa("floor_areas")
    ps = importlib.import_module("lib.plan_scale")
    H, W = 400, 500
    lab = np.zeros((H, W), int)
    lab[:, :] = 9                                      # outdoors
    lab[97:303, 97:403] = 0                            # the wall ring
    lab[100:200, 100:300] = 1                          # the apartment
    unit = lab == 1
    if split:
        lab[100:200, 199:201] = 0                      # a wall between two rooms
        lab[100:200, 201:300] = 2
        lab[140:150, 199:201] = 0
        unit = (lab == 1) | (lab == 2)
    labels = np.zeros((H, W), int)                     # plan_scale's 3pt grid: same frame
    ring = np.zeros((H, W), bool)
    ring[97:303, 97:403] = True
    ring[100:200, 100:300] = False
    labels[ring] = 7
    if two_bodies:
        labels[97:303, 97:100] = 8                     # the left wall is another drawing's
    note = ps.ScaleNote(text='1/4" = 1\'-0"', bbox=(0, 0, 1, 1), pt_per_in=ppi, ratio=48.0,
                        nts=False, title="SECOND FLOOR PLAN")
    vp = ps.Viewport(bbox=(0, 0, 1500, 1200), drawing_bbox=(0, 0, 1500, 1200),
                     title="SECOND FLOOR PLAN", note=note, verified=verified,
                     pt_per_in=ppi if verified else None, agreeing=12 if verified else 1,
                     refusal="" if verified else "1 of 9 measured dimensions agree with 1/4\" = 1'-0\" (need 3)",
                     body=7)
    sheet = ps.Sheet(viewports=[vp], labels=labels, width=1500.0, height=1200.0)
    space = {"closed_lab": lab, "lo": (0.0, 0.0), "cell_pt": CELL, "units": {"2A": unit},
             "public": np.zeros((H, W), bool)}
    boxes = list(LEGEND)
    if printed is not None:
        boxes += _words(400.0, 400.0, printed)
    if room_text:
        name, value = room_text
        boxes += [(name, 700.0, 386.0, 760.0, 394.0, "ltr")] + _words(700.0, 400.0, value, before="")
    return pa.floor_areas(_Page(boxes), space, scale_sheet=sheet)


def _apt(res):
    (r,) = [r for r in res if r["scope"] == "apartment" and r["unit"] == "2A"]
    return r


#: 100 x 200 cells of 2" = 555.6 sf; the half-cell edge (600 edges) adds 8.3:
#: 563.9 sf.
EXPECT = (100 * 200 + 0.5 * 600) * 4 / 144


class TheCheck(unittest.TestCase):
    def test_a_region_is_its_cells_and_half_a_cell_at_each_edge(self):
        pa = _pa("region_area_sf")
        import numpy as np
        m = np.zeros((10, 10), bool)
        m[2:4, 2:6] = True                                 # a 2'-0" x 4'-0" closet less its edge
        self.assertAlmostEqual(pa.region_area_sf(m, CELL, QUARTER), (8 + 0.5 * 12) * 4 / 144)

    def test_agrees_within_the_tolerance(self):
        r = _apt(_floor(printed=564))
        self.assertAlmostEqual(r["computed"], round(EXPECT, 1))
        self.assertEqual(r["status"], "agrees")
        self.assertEqual(r["printed_text"], "NET: 564 SQ. FT.")

    def test_disagrees_outside_it(self):
        self.assertEqual(_apt(_floor(printed=520))["status"], "disagrees")

    def test_the_tolerance_is_two_percent(self):
        pa = _pa("verdict", "AREA_TOL")
        self.assertEqual(pa.AREA_TOL, 0.02)
        self.assertEqual(pa.verdict(101.9, 100.0), "agrees")
        self.assertEqual(pa.verdict(98.1, 100.0), "agrees")
        self.assertEqual(pa.verdict(102.1, 100.0), "disagrees")
        self.assertEqual(pa.verdict(97.9, 100.0), "disagrees")
        # on the synthetic floor: 563.9 against 553 (+1.97%) and 552 (+2.16%)
        self.assertEqual(_apt(_floor(printed=553))["status"], "agrees")
        self.assertEqual(_apt(_floor(printed=552))["status"], "disagrees")

    def test_no_printed_area_is_no_printed_not_a_figure(self):
        r = _apt(_floor())
        self.assertEqual(r["status"], "no_printed")
        self.assertIsNone(r["printed"])

    def test_an_unverified_viewport_gives_no_computed_figure(self):
        r = _apt(_floor(verified=False, printed=564))
        self.assertIsNone(r["computed"])
        self.assertEqual(r["status"], "refused")
        self.assertIn("not verified", r["why"])

    def test_a_region_closed_at_another_scale_is_refused(self):
        r = _apt(_floor(ppi=0.75, printed=564))         # verifies at 1/8": the map assumed 1/4"
        self.assertIsNone(r["computed"])
        self.assertEqual(r["status"], "refused")

    def test_walls_of_two_drawings_refuse(self):
        r = _apt(_floor(two_bodies=True, printed=564))
        self.assertIsNone(r["computed"])
        self.assertEqual(r["status"], "refused")

    def test_the_wall_between_its_own_rooms_is_the_apartments(self):
        r = _apt(_floor(split=True, printed=564))
        self.assertAlmostEqual(r["computed"], round(EXPECT, 1))
        self.assertEqual(r["status"], "agrees")

    def test_square_inches_and_a_figure_in_a_sentence_are_not_areas(self):
        pa = _pa("printed_areas")
        boxes = [("72", 100.0, 100.0, 112.0, 108.0, "ltr"), ("SQ.", 116.0, 100.0, 134.0, 108.0, "ltr"),
                 ("IN.", 138.0, 100.0, 156.0, 108.0, "ltr"),
                 ("AREAS:", 200.0, 200.0, 236.0, 208.0, "ltr"), ("71", 240.0, 200.0, 252.0, 208.0, "ltr"),
                 ("SQ.", 256.0, 200.0, 274.0, 208.0, "ltr"), ("FT.", 278.0, 200.0, 296.0, 208.0, "ltr")]
        self.assertEqual(pa.printed_areas(boxes), [])

    def test_a_room_label_is_its_name_and_figure(self):
        pa = _pa("printed_areas")
        boxes = [("BIKE", 100.0, 86.0, 124.0, 94.0, "ltr"), ("ROOM", 128.0, 86.0, 152.0, 94.0, "ltr")] \
            + _words(100.0, 100.0, 113, before="")
        (p,) = pa.printed_areas(boxes)
        self.assertEqual((p.kind, p.value, p.name, p.text), ("room", 113.0, "BIKE ROOM", "BIKE ROOM 113 SQ. FT."))


class TheRender(unittest.TestCase):
    def test_the_model_is_told_which_figure_may_be_stated(self):
        pa = _pa("render_area_evidence")
        text = pa.render_area_evidence([AGREE_2A, DISAGREE_1A, NOPRINT_4A, REFUSED_4B])
        self.assertIn("May be stated: 482", text)
        self.assertIn("State NEITHER", text)
        self.assertIn("NOT stated", text)
        self.assertNotIn("376.7", text)                  # a measured figure alone is never shown
        self.assertIn("not checked", text)


# ═══════════════════════════════════════════════════════════════════════════
# The wiring: the pass writes area rows, search fetches them, the model sees
# them through the check
# ═══════════════════════════════════════════════════════════════════════════

class ThePassWritesThem(unittest.TestCase):
    def test_run_pass_returns_area_rows(self):
        from lib import plan_glyph_pass as G
        out = G.run_pass([], lambda p: None, [], [])
        self.assertIn("areas", out)

    def test_every_floor_with_a_map_is_checked_and_carries_its_track(self):
        from lib import plan_glyph_pass as G
        pa = _pa("floor_areas")
        self.assertTrue(hasattr(G, "floor_area_rows"), "plan_glyph_pass has no floor_area_rows")
        seen = []

        def fake(page, space, **kw):
            seen.append(space["tag"])
            return [{"scope": "apartment", "unit": "2A", "name": "", "printed": 482.0,
                     "printed_text": "NET: 482 SQ. FT.", "printed_box": None, "gross_printed": None,
                     "gross_text": "", "computed": 481.8, "viewport": None, "why": "",
                     "status": "agrees", "diff_pct": -0.04}]
        floors = [{"a_sheet": "A-101.00", "arch_p": {"sheet_number": "A-101.00", "page_id": "x"},
                   "space": {"tag": "A-101"}, "units": {"tags": ["2A"]}},
                  {"a_sheet": "A-104.00", "arch_p": {"sheet_number": "A-104.00"}, "units": {"tags": None}}]
        with patch.object(pa, "floor_areas", fake):
            rows, notes = G.floor_area_rows(floors, lambda p: None, track="post_co")
        self.assertEqual(seen, ["A-101"])
        self.assertEqual([(r["unit"], r["status"], r["payload"]["track"]) for r in rows],
                         [("2A", "agrees", "post_co")])


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return list(self.rows)


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def find(self, flt, proj=None):
        return _Cur([dict(r) for r in self.rows if all(r.get(k) == v for k, v in flt.items())])


class _Db:
    def __init__(self, areas):
        self.coll = _Coll(areas)

    def __getitem__(self, name):
        assert name == "plan_areas", name
        return self.coll


def _server():
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "test_db")
    os.environ.setdefault("JWT_SECRET", "x")
    import server
    return server


class SearchFetchesThem(unittest.TestCase):
    def _search(self, subject, intent="attribute"):
        server = _server()
        rows = [dict(r, project_id="p") for r in (AGREE_2A, DISAGREE_1A)]

        async def ids(project_id, **kw):
            return ["pg-A-101.00"]

        async def ranked(project_id, page_ids, subject, intent):
            return ([NOTES[0]], [subject])
        with patch.object(server, "db", _Db(rows)), \
                patch.object(server, "_current_record_page_ids", ids), \
                patch.object(server, "_ranked_for_subject", ranked):
            return asyncio.run(server.search_plans("p", subject, intent=intent))

    def test_an_area_question_brings_the_area_rows(self):
        got = self._search("apartment 2A square footage")
        self.assertEqual(sorted(r.get("unit") for r in got if r.get("record_type") == "area"),
                         ["1A", "2A"])

    def test_a_question_about_something_else_does_not(self):
        got = self._search("PTAC", intent="attribute")
        self.assertFalse([r for r in got if r.get("record_type") == "area"])

    def test_the_model_sees_them_through_the_check_not_as_quotes(self):
        server = _server()
        text = server._render_records_for_model([NOTES[0], AGREE_2A, DISAGREE_1A], "apartment area")
        self.assertIn("State NEITHER", text)
        self.assertNotIn("- NET: 338 SQ. FT.", text)


# ═══════════════════════════════════════════════════════════════════════════
# On the drawings (fixture PDFs)
# ═══════════════════════════════════════════════════════════════════════════

class OnBoyland(unittest.TestCase):
    """Read through the library exactly as the pass reads a floor."""

    @staticmethod
    def _floor(file, page):
        pa = _pa("floor_areas")
        from lib.plan_page import PlanPage
        from lib import plan_derive as D
        from lib.plan_sheet import load_sheet
        from lib.plan_space import build_space
        pg = PlanPage(require_pdf(file), page)
        data = load_sheet(pg)
        u = D.unit_tags(data["words"], data["corners"])
        sp = build_space(pg, u["tags"] or [], 56.0, data)
        return pa.floor_areas(pg, sp)

    def test_filed_a101_every_apartment_agrees_with_its_NET(self):
        res = self._floor("AR - 3.28.25.pdf", 12)
        apts = {r["unit"]: r for r in res if r["scope"] == "apartment"}
        self.assertEqual(sorted(apts), ["2A", "2B", "2C", "2D"])
        for u, printed in (("2A", 482), ("2B", 483), ("2C", 467), ("2D", 467)):
            self.assertEqual(apts[u]["printed"], printed, u)
            self.assertEqual(apts[u]["status"], "agrees", (u, apts[u]))
            self.assertLess(abs(apts[u]["diff_pct"]), 0.5, u)
        beds = [r for r in res if r["scope"] == "room" and r["name"] == "BEDROOM"]
        self.assertEqual(len(beds), 4)
        self.assertTrue(all(r["status"] == "disagrees" for r in beds), beds)

    def test_owners_a100_1A_prints_a_NET_its_post_CO_region_contradicts(self):
        res = self._floor("Owners set - 6.9.26.pdf", 1)
        (a,) = [r for r in res if r["scope"] == "apartment" and r["unit"] == "1A"]
        self.assertEqual(a["printed"], 338)
        self.assertEqual(a["status"], "disagrees")
        self.assertGreater(a["diff_pct"], 20)

    def test_the_roof_bulkhead_is_not_measured_and_the_roof_is(self):
        res = self._floor("AR - 8.18.26.pdf", 7)
        by = {r["name"]: r for r in res if r["scope"] == "room"}
        self.assertEqual(by["PASSIVE RECREATION"]["status"], "agrees")
        self.assertEqual(by["HWH ROOM"]["status"], "agrees")
        self.assertFalse([r for r in res if r["printed"] in (71, 72)],
                         "the STAIR AREAS note and SQ. IN. are not areas")


if __name__ == "__main__":
    unittest.main()
