"""The glyph pass's `walls` step (ruling 62, Roy 2026-10-28: "build the
plan_walls pass step; the pass waits for Roy, as usual").

What this guards:

  * Every architectural plan of a track - each paired floor, and each plan
    the pairing refused for want of a mechanical partner - is read once, and
    writes its rows to `plan_walls`, each saying its track and its floor.
  * The rows are of four kinds: a wall (typed / untyped / ambiguous), a
    drawing whose scale did not verify, a plan refused as a whole, and a tag
    that names no wall. Tags drawn inside a refused drawing are named on
    that drawing's row - SET_UPDATED's 39 tags on A.1.2 are one row, not 39.
  * No row is a total (ruling 52).
  * One plan that fails never sinks the pass: it is said, and writes no row.
  * The writer is idempotent per project and track: the same pass twice
    leaves the same rows; another project's rows are untouched; a track the
    set no longer has keeps none.
  * The server writes the rows after the pass, never during a re-index
    (tests/test_the_glyph_pass_waits_for_reindex.py), and the run's result
    reports walls_written.

WRITTEN TO FAIL BY ASSERTION ON A TREE WITHOUT THE STEP: every name is
reached through `_need()`, which turns a missing module or name into an
AssertionError rather than an ImportError at collection.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "smoke_test"),
             ("JWT_SECRET", "smoke_test_secret"), ("APP_BASE_URL", "https://app.levelog.com")):
    os.environ.setdefault(k, v)

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

PAGE = {"project_id": "p1", "company_id": "c1", "file_id": "f1", "file_hash": "h1",
        "file_name": "AR - 3.28.25.pdf", "page_id": "pg12", "page_number": 12,
        "sheet_number": "A-101.00", "sheet_title": "SECOND FLOOR PLAN", "discipline": "A",
        "drawing_track": "filed", "drawing_track_label": None}


def _need(module, *names):
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        raise AssertionError(f"{module} is not importable: {e}")
    for n in names:
        assert hasattr(mod, n), f"{module} has no {n}"
    return mod


def _result():
    """A floor_walls result: a typed wall, an untyped one, a refused drawing
    with two tags in it, and one tag that names no wall in the verified one."""
    return {
        "refusal": None,
        "viewports": [{"title": "SECOND FLOOR PLAN", "scale": '1/4" = 1\'-0"', "verified": True,
                       "refusal": "", "wall_line_paper_pt": 900.0},
                      {"title": "BULKHEAD PLAN", "scale": '3/32" = 1\'-0"', "verified": False,
                       "refusal": "0 of 0", "wall_line_paper_pt": 300.0}],
        "walls": [
            {"axis": "h", "center_pt": 104.5, "from_pt": 100.0, "to_pt": 280.0, "thick_in": 6.0,
             "pieces": [[100.0, 100.0, 280.0, 109.0]], "drawn_lf": 10.0, "joint_lf": 0.0,
             "opening_lf": 0.0, "lf": 10.0, "tags": ["P2"], "viewport": "SECOND FLOOR PLAN",
             "status": "typed", "type": "P2", "why": "", "id": 1,
             "apartments": {"demising|2A+2B": 10.0}},
            {"axis": "v", "center_pt": 603.0, "from_pt": 100.0, "to_pt": 172.0, "thick_in": 4.0,
             "pieces": [[600.0, 100.0, 606.0, 172.0]], "drawn_lf": 4.0, "joint_lf": 0.0,
             "opening_lf": 0.0, "lf": 4.0, "tags": [], "viewport": "SECOND FLOOR PLAN",
             "status": "untyped", "type": None, "why": "no wall-type tag reaches this wall", "id": 2}],
        "by_type": {"P2": 10.0}, "untyped_lf": 4.0, "ambiguous_lf": 0.0,
        "figures": {"P2": {"tagged_lf": 10.0, "untyped_lf_beside": 4.0, "ambiguous_lf_beside": 0.0}},
        "tags": [{"text": "P2", "x": 150.0, "y": 160.0}, {"text": "W1", "x": 1500.0, "y": 50.0},
                 {"text": "W2", "x": 1550.0, "y": 60.0}, {"text": "P3", "x": 400.0, "y": 400.0}],
        "unattached": [{"text": "W1", "x": 1500.0, "y": 50.0, "why": "outside every drawing with a verified scale"},
                       {"text": "W2", "x": 1550.0, "y": 60.0, "why": "outside every drawing with a verified scale"},
                       {"text": "P3", "x": 400.0, "y": 400.0, "why": "its leader reaches no wall"}],
        "short_pieces": [],
        "refused_viewports": [{"title": "BULKHEAD PLAN", "bbox": [1400.0, 0.0, 1700.0, 200.0],
                               "why": "scale not verified: 0 of 0", "wall_line_paper_pt": 300.0}],
        "off_viewport_pt": 0.0, "types_on_plan": ["P2", "P3", "W1", "W2"],
    }


class TheRowsOfOnePlan(unittest.TestCase):

    def setUp(self):
        W = _need("lib.plan_walls", "wall_rows", "COLLECTION", "WALLS_VERSION")
        self.W = W
        self.rows = W.wall_rows(_result(), PAGE, track="filed")

    def kinds(self):
        return [(r["payload"]["kind"], r["status"]) for r in self.rows]

    def test_four_kinds_each_with_its_status(self):
        self.assertEqual(self.kinds(), [("wall", "typed"), ("wall", "untyped"),
                                        ("unattached_tag", "unattached"),
                                        ("refused_viewport", "refused")])

    def test_tags_inside_a_refused_drawing_are_named_on_its_row_not_one_row_each(self):
        rv = [r for r in self.rows if r["payload"]["kind"] == "refused_viewport"]
        self.assertEqual(rv[0]["payload"]["tags_in_it"], ["W1", "W2"])
        self.assertEqual([r["payload"]["tag"] for r in self.rows
                          if r["payload"]["kind"] == "unattached_tag"], ["P3"])

    def test_every_row_cites_its_page_and_says_its_track_and_floor(self):
        for r in self.rows:
            self.assertEqual(r["record_type"], "wall")
            self.assertEqual((r["sheet_number"], r["page_id"], r["file_hash"]), ("A-101.00", "pg12", "h1"))
            self.assertEqual(r["payload"]["track"], "filed")
            self.assertEqual(r["payload"]["floor"], "FLOOR_2")
            self.assertEqual(r["payload"]["walls_version"], self.W.WALLS_VERSION)
        self.assertEqual(self.W.COLLECTION, "plan_walls")

    def test_a_wall_row_carries_its_figure_and_where_it_is(self):
        w = self.rows[0]["payload"]
        self.assertEqual((w["wall_type"], w["lf"], w["thick_in"], w["axis"]), ("P2", 10.0, 6.0, "h"))
        self.assertEqual(w["rect"], [100.0, 100.0, 280.0, 109.0])
        self.assertEqual(w["apartments"], {"demising|2A+2B": 10.0})
        self.assertEqual(w["scale_text"], '1/4" = 1\'-0"')
        self.assertIsNone(self.rows[1]["payload"]["wall_type"])

    def test_no_row_is_a_total(self):
        for r in self.rows:
            self.assertFalse([k for k in r["payload"] if "total" in k.lower()], r["payload"])

    def test_a_plan_refused_as_a_whole_says_why(self):
        rows = self.W.wall_rows({"refusal": "no wall legend on this sheet to bound a wall's thickness"},
                                dict(PAGE, sheet_title="FLOOR PLAN"), track="filed")
        self.assertEqual([(r["payload"]["kind"], r["status"], r["payload"]["floor"]) for r in rows],
                         [("refused_sheet", "refused", None)])
        self.assertIn("legend", rows[0]["payload"]["why"])


class TheStepReadsEveryPlanOnce(unittest.TestCase):

    def test_floors_and_refused_plans_once_each_and_a_failure_is_said(self):
        G = _need("lib.plan_glyph_pass", "floor_wall_rows")
        W = _need("lib.plan_walls", "floor_walls")
        a101 = dict(PAGE)
        a102 = dict(PAGE, page_id="pg13", page_number=13, sheet_number="A-102.00",
                    sheet_title="THIRD FLOOR PLAN")
        a11 = dict(PAGE, page_id="su12", page_number=12, sheet_number="A.1.2", sheet_title="FLOOR PLAN",
                   file_name="588 THOMAS BOYLAND ST SET_UPDATED.pdf")
        opened, spaces = [], []

        def fake_floor_walls(page, *, space=None, widest_door_in=None, **k):
            spaces.append((page, space, widest_door_in))
            if page == "A-102.00":
                raise RuntimeError("bad page")
            return _result()
        orig = W.floor_walls
        W.floor_walls = fake_floor_walls
        try:
            def open_page(p):
                opened.append(p["sheet_number"])
                return p["sheet_number"]
            rows, notes = G.floor_wall_rows(
                [{"arch_p": a101, "space": {"units": {}}}, {"arch_p": a102}, {"arch_p": a101}],
                open_page, track="post_co", widest_door_in=56.0, others=[a11])
        finally:
            W.floor_walls = orig
        self.assertEqual(opened, ["A-101.00", "A-102.00", "A.1.2"])
        self.assertEqual([(p, s is not None, d) for p, s, d in spaces],
                         [("A-101.00", True, 56.0), ("A-102.00", False, 56.0), ("A.1.2", False, 56.0)])
        self.assertEqual({r["sheet_number"] for r in rows}, {"A-101.00", "A.1.2"})
        self.assertTrue(all(r["payload"]["track"] == "post_co" for r in rows))
        self.assertTrue(any(n.startswith("A-102.00: walls failed (RuntimeError)") for n in notes), notes)
        self.assertEqual({r["payload"]["floor"] for r in rows if r["sheet_number"] == "A.1.2"}, {None})


class TheWriterIsIdempotentPerProjectAndTrack(unittest.TestCase):

    def _server(self):
        server = _need("server", "_write_wall_records")
        from tests.async_fake_mongo import AsyncFakeDB
        return server, AsyncFakeDB()

    def _rows(self, track, n):
        return [{"project_id": "p1", "record_type": "wall", "status": "typed",
                 "payload": {"kind": "wall", "track": track, "lf": float(i)}} for i in range(n)]

    def test_twice_is_once_and_other_projects_are_untouched(self):
        from unittest.mock import patch
        server, db = self._server()
        db["plan_walls"].docs.append({"project_id": "p2", "payload": {"track": "filed"}})
        rows = self._rows("filed", 3) + self._rows("post_co", 2)
        with patch.object(server, "db", db):
            n1 = asyncio.run(server._write_wall_records("p1", [dict(r) for r in rows]))
            first = [(d["payload"]["track"], d["payload"]["lf"], d["ordinal"])
                     for d in db["plan_walls"].docs if d["project_id"] == "p1"]
            n2 = asyncio.run(server._write_wall_records("p1", [dict(r) for r in rows]))
            second = [(d["payload"]["track"], d["payload"]["lf"], d["ordinal"])
                      for d in db["plan_walls"].docs if d["project_id"] == "p1"]
        self.assertEqual((n1, n2), (5, 5))
        self.assertEqual(first, second)
        self.assertEqual(len([d for d in db["plan_walls"].docs if d["project_id"] == "p2"]), 1)

    def test_a_track_the_set_no_longer_has_keeps_no_rows(self):
        from unittest.mock import patch
        server, db = self._server()
        with patch.object(server, "db", db):
            asyncio.run(server._write_wall_records("p1", self._rows("filed", 3) + self._rows("post_co", 2)))
            asyncio.run(server._write_wall_records("p1", self._rows("filed", 3)))
        self.assertEqual({d["payload"]["track"] for d in db["plan_walls"].docs}, {"filed"})
        self.assertEqual(len(db["plan_walls"].docs), 3)


# ── 588 Boyland, from the fixture PDFs ─────────────────────────────────────

class OnBoyland(unittest.TestCase):

    def _rows(self, name, page, sheet, title):
        G = _need("lib.plan_glyph_pass", "floor_wall_rows")
        from lib.plan_page import PlanPage
        path = str(require_pdf(name))
        p = dict(PAGE, file_name=name, page_number=page, sheet_number=sheet, sheet_title=title)
        rows, _notes = G.floor_wall_rows([], lambda q: PlanPage(path, q["page_number"]),
                                         track="filed", widest_door_in=56.0, others=[p])
        return rows

    def test_the_filed_second_floor(self):
        rows = self._rows("AR - 3.28.25.pdf", 12, "A-101.00", "SECOND FLOOR PLAN")
        kinds = {}
        for r in rows:
            k = (r["payload"]["kind"], r["status"])
            kinds[k] = kinds.get(k, 0) + 1
        self.assertEqual(kinds, {("wall", "typed"): 26, ("wall", "untyped"): 10,
                                 ("unattached_tag", "unattached"): 1})
        p2 = sorted(r["payload"]["lf"] for r in rows if r["payload"].get("wall_type") == "P2"
                    and r["payload"]["axis"] == "h")
        self.assertEqual(p2, [28.0, 28.33])

    def test_set_updated_is_one_refused_drawing_carrying_its_tags(self):
        rows = self._rows("588 THOMAS BOYLAND ST SET_UPDATED.pdf", 12, "A.1.2", "FLOOR PLAN")
        self.assertEqual([(r["payload"]["kind"], r["status"]) for r in rows],
                         [("refused_viewport", "refused")])
        self.assertEqual(len(rows[0]["payload"]["tags_in_it"]), 39)
        self.assertIsNone(rows[0]["payload"]["floor"])


if __name__ == "__main__":
    unittest.main()
