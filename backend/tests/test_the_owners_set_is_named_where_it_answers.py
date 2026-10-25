"""THE OWNER'S SET IS NAMED WHERE IT ANSWERS.

On 588 Boyland the filed AR set governs; the Owner's set (6/9/26) is a
separate track - the owner's post-CO additions, off the DOB record - not a
revision of it. The index treats it as one, so floors 2 to the mezzanine are
placed against the Owner's set (measured 2026-10-24: 64 rows, units 2A-4D).

Rulings (operator, 2026-10-24):
  - the track is a field on the FILE, set through an audited admin endpoint;
  - the glyph pass copies it onto every row placed against the file
    (EMIT_VERSION 6);
  - every per-apartment answer resting on the owner's set NAMES it in the
    render - label, don't refuse - for all 12 units, not just 4A-4D;
  - floor and building totals rest on the mechanical sheets and carry no label.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from bson import ObjectId  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.test_a_stair_carries_its_unit_to_the_level_it_reaches import _seeded  # noqa: E402

CO_A, CO_B = "co-a", "co-b"
PROJ = ObjectId()
FILE = ObjectId()
ADMIN_A = {"id": "adm-a", "role": "admin", "company_id": CO_A, "account_status": "approved"}
ADMIN_B = {"id": "adm-b", "role": "admin", "company_id": CO_B, "account_status": "approved"}
LABEL = "the owner's post-CO set, 6/9/26"


def _present():
    assert hasattr(server, "set_file_drawing_track"), \
        "a drawing set's track cannot be stated in this tree"


def _db():
    db = AsyncFakeDB()
    db.projects.docs.append({"_id": PROJ, "company_id": CO_A, "status": "active", "is_deleted": False})
    db.project_files.docs.append({"_id": FILE, "project_id": str(PROJ), "company_id": CO_A,
                                  "name": "Owners set - 6.9.26.pdf", "is_deleted": False})
    return db


def _set(db, actor, track, label=None, file_id=None, project_id=None):
    body = server.DrawingTrackUpdate(track=track, label=label)
    with patch.object(server, "db", db):
        try:
            return 200, asyncio.run(server.set_file_drawing_track(
                project_id or str(PROJ), file_id or str(FILE), body, actor))
        except server.HTTPException as e:
            return e.status_code, None


class TheTrackIsSetOnTheFileAndAudited(unittest.TestCase):

    def test_the_owning_company_admin_sets_it_and_an_audit_row_says_from_and_to(self):
        _present()
        db = _db()
        st, out = _set(db, ADMIN_A, "post_co", LABEL)
        self.assertEqual(st, 200)
        f = db.project_files.docs[0]
        self.assertEqual((f["drawing_track"], f["drawing_track_label"]), ("post_co", LABEL))
        (a,) = [r for r in db.audit_logs.docs if r["action"] == "project_file_drawing_track"]
        self.assertEqual(a["details"]["from"], {"track": "filed", "label": None})
        self.assertEqual(a["details"]["to"], {"track": "post_co", "label": LABEL})

    def test_a_post_co_set_with_no_label_is_named_by_its_file(self):
        _present()
        db = _db()
        _set(db, ADMIN_A, "post_co")
        self.assertIn("Owners set - 6.9.26.pdf", db.project_files.docs[0]["drawing_track_label"])

    def test_another_companys_admin_is_refused_and_nothing_changes(self):
        _present()
        db = _db()
        self.assertEqual(_set(db, ADMIN_B, "post_co")[0], 403)
        self.assertNotIn("drawing_track", db.project_files.docs[0])
        self.assertEqual(db.audit_logs.docs, [])

    def test_an_unknown_track_or_file_is_refused(self):
        _present()
        self.assertEqual(_set(_db(), ADMIN_A, "governing")[0], 422)
        self.assertEqual(_set(_db(), ADMIN_A, "post_co", file_id=str(ObjectId()))[0], 404)
        self.assertEqual(_set(_db(), ADMIN_A, "post_co", project_id=str(ObjectId()))[0], 404)

    def test_the_route_carries_the_project_gate_and_the_admin_gate(self):
        _present()

        def deps(d):
            out = set()
            for x in d.dependencies:
                out.add(getattr(x.call, "__name__", type(x.call).__name__))
                out |= deps(x)
            return out
        (route,) = [r for r in server.app.routes if isinstance(r, APIRoute)
                    and r.path == "/api/projects/{project_id}/files/{file_id}/drawing-track"]
        d = deps(route.dependant)
        self.assertTrue({"require_approved", "require_project_access", "get_admin_user"} <= d, d)


class ThePassCarriesItOntoEveryRow(unittest.TestCase):

    def test_every_page_handed_to_the_pass_says_its_track(self):
        _present()
        db = _db()
        db.project_files.docs[0].update(drawing_track="post_co", drawing_track_label=LABEL)
        other = ObjectId()
        db.project_files.docs.append({"_id": other, "project_id": str(PROJ), "company_id": CO_A,
                                      "name": "AR - 8.18.26.pdf", "is_deleted": False})
        for fid, n in ((FILE, 4), (other, 6)):
            db.document_page_index.docs.append({"_id": ObjectId(), "project_id": str(PROJ),
                                                "file_id": str(fid), "page_number": n,
                                                "sheet_number": "A-10%d.00" % n, "superseded_by": None})
        seen = {}

        def fake_pass(pages, open_page, schedules, door_pages):
            seen["pages"] = pages
            return {"rows": [], "summary": {}}

        async def live(_pid):
            return [str(FILE), str(other)]

        async def write(_pid, rows):
            return 0
        with patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live), \
                patch("lib.plan_glyph_pass.run_pass", fake_pass), \
                patch.object(server, "_write_glyph_records", write):
            asyncio.run(server._plan_glyph_pass(str(PROJ)))
        got = {p["file_id"]: (p["drawing_track"], p["drawing_track_label"]) for p in seen["pages"]}
        self.assertEqual(got, {str(FILE): ("post_co", LABEL), str(other): ("filed", None)})

    def test_the_row_carries_it(self):
        self.assertGreaterEqual(E.EMIT_VERSION, 6)
        page = {"project_id": "p", "page_id": "m", "page_number": 1, "sheet_number": "M-103.00"}
        arch = {"page_id": "a", "sheet_number": "A-103.00", "file_name": "Owners set - 6.9.26.pdf",
                "drawing_track": "post_co", "drawing_track_label": LABEL}
        (row,) = E.glyph_rows({"records": [{"tag": "EF-1", "unit": "4A", "glyph_status": "resolved",
                                            "placement": "placed", "label_text": "EF-1"}]},
                              mech=page, arch=arch, family="EXHAUST FAN SCHEDULE", pass_key="k",
                              units={}, widest_door={})
        self.assertEqual((row["payload"]["arch"]["drawing_track"],
                          row["payload"]["arch"]["drawing_track_label"]), ("post_co", LABEL))


def _tracked(owner_floors=("101", "102", "103", "104"), version=True):
    recs = _seeded()
    for r in recs:
        a = (r.get("payload") or {}).get("arch")
        if not a:
            continue
        k = str(a.get("sheet_number") or "")[2:5]
        if version:
            post = k in owner_floors
            a["drawing_track"] = "post_co" if post else "filed"
            a["drawing_track_label"] = LABEL if post else None
    return recs


class EveryAnswerRestingOnTheOwnersSetNamesIt(unittest.TestCase):

    def _lines(self, recs):
        return [l for l in S.render_glyph_evidence(recs).splitlines() if l.startswith("- ")]

    def test_all_owners_set_floors_are_labelled_and_the_filed_floor_is_not(self):
        _present()
        lines = self._lines(_tracked())
        for l in lines:
            if "Whole building" in l or "per unit" not in l and "each unit" not in l:
                self.assertNotIn(LABEL, l, l)          # totals rest on the M sheets
            elif "FIRST FLOOR" in l:
                self.assertNotIn(LABEL, l, l)          # placed against the filed set
            else:
                self.assertIn(f"per {LABEL}", l, l)

    def test_a_duplex_is_labelled_when_any_of_its_floors_is_the_owners(self):
        _present()
        lines = self._lines(_tracked(owner_floors=("104",)))
        fourth = next(l for l in lines if "FOURTH FLOOR" in l and "EF-1" in l)
        self.assertIn(f"per {LABEL}", fourth)
        third = next(l for l in lines if "THIRD FLOOR" in l and "EF-1" in l)
        self.assertNotIn(LABEL, third)

    def test_label_dont_refuse_the_gate_binds_the_same(self):
        _present()
        a, b = S.glyph_book(_tracked()), S.glyph_book(_tracked(version=False))
        for clause in ("4A has 3 exhaust fans.", "2B has 2 exhaust fans.",
                       "Each unit on the fourth floor has 3 exhaust fans.",
                       "There are 36 exhaust fans.", "The mezzanine has 4 EF-1."):
            self.assertEqual(S.glyph_values(clause, a), S.glyph_values(clause, b), clause)
            self.assertTrue(S.glyph_values(clause, a), clause)

    def test_rows_written_before_the_track_was_read_say_nothing(self):
        _present()
        self.assertNotIn(LABEL, S.render_glyph_evidence(_tracked(version=False)))


# ── the real pass, on the real sheets, with the track set - no stub ───────

class TheRealPassCarriesTheTrack(unittest.TestCase):
    """run_pass end to end on A-101.00 (Owners set, marked post_co) and
    M-101.00, with A-400.00's door schedule: the CAD-layer space map, the OCR
    sweep, placement and emit all run for real. Every row placed against the
    Owner's set says so, and the render names it on the second floor - whose
    apartments sit on one sheet, so it prints a per-apartment figure (the
    fourth floor's duplexes need the mezzanine linked to print one)."""

    def test_rows_and_render(self):
        _present()
        from lib.plan_page import PlanPage
        from lib import plan_glyph_pass as G
        from tests.fixture_pdfs import require as require_pdf
        pid = "6a5f63bc147407d3261df2c7"

        def page(fname, n, sheet, title, disc, track=None, label=None):
            return {"project_id": pid, "company_id": "c1", "file_id": fname, "file_hash": None,
                    "file_name": fname, "page_id": f"{fname}#{n}", "page_number": n,
                    "sheet_number": sheet, "sheet_title": title, "discipline": disc,
                    "drawing_track": track or "filed", "drawing_track_label": label}
        a101 = page("Owners set - 6.9.26.pdf", 2, "A-101.00", "SECOND FLOOR PLAN", "AR",
                    "post_co", LABEL)
        m101 = page("MH - 7.2.26.pdf", 3, "M-101.00", "SECOND FLOOR HVAC PLANS", "ME")
        a400 = page("AR - 3.28.25.pdf", 23, "A-400.00", "WINDOW SCHEDULE", "AR")
        # M-200.00's EXHAUST FAN SCHEDULE as production stores its OCR-grid
        # reading (the CFM ratings corroborate the labels, EF-1(50), EF-2(100))
        sched = [{"name": "EXHAUST FAN SCHEDULE", "tier": "ocr_grid_cell", "sheet_number": "M-200.00",
                  "columns": [{"header": "TAG", "role": "identifier"}, {"header": "MANUF.", "role": None},
                              {"header": "MODEL", "role": "model"}, {"header": "CFM", "role": None}],
                  "rows": [["EF-1", "NUTONE", "AEN110", "50"], ["EF-2", "BROAN", "BRN503", "100"]]}]
        opened = {}

        def open_page(p):
            k = (p["file_name"], p["page_number"])
            if k not in opened:
                opened[k] = PlanPage(str(require_pdf(p["file_name"])), p["page_number"])
            return opened[k]
        try:
            out = G.run_pass([a101, m101], open_page, sched, [a400])
        finally:
            for pg in opened.values():
                pg.close()
        located = [r for r in out["rows"] if r.get("label")]
        self.assertEqual(len(located), 8, out["summary"])          # 4 EF-1 + 4 EF-2
        for r in located:
            self.assertEqual(r["payload"]["emit_version"], E.EMIT_VERSION)
            self.assertEqual((r["payload"]["arch"]["drawing_track"],
                              r["payload"]["arch"]["drawing_track_label"]), ("post_co", LABEL))
        rows = out["rows"]
        pages = sorted({r["page_id"] for r in rows})
        c = S.glyph_census("family", pid, pages, 0, family="EXHAUST FAN SCHEDULE", tags=["EF-1", "EF-2"])
        census = [S.glyph_census("family", pid, pages, sum(S.glyph_in_census(r, c) for r in rows),
                                 family="EXHAUST FAN SCHEDULE", tags=["EF-1", "EF-2"])]
        c = S.glyph_census("refusals", pid, pages, 0)
        census.append(S.glyph_census("refusals", pid, pages, sum(S.glyph_in_census(r, c) for r in rows)))
        line = next(l for l in S.render_glyph_evidence(rows + census).splitlines()
                    if "SECOND FLOOR" in l)
        self.assertIn(f"per {LABEL}", line)


if __name__ == "__main__":
    unittest.main()
