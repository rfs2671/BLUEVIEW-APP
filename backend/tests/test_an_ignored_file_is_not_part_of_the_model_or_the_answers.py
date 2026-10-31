"""AN IGNORED FILE IS NOT PART OF THE MODEL OR THE ANSWERS (Roy, 10-31).

AR 8.18.26 on 588 Boyland is an unapproved prep set that was never approved.
There was no way to say so: `drawing_track` took filed / post_co only, and the
only way to drop a file was a hard delete. Now a company admin states
`ignored` through the existing audited route (PUT .../files/{id}/drawing-track)
and the file leaves the model and the answers - without being deleted:

  - the glyph pass reads none of its pages (so it writes 0 rows, 0 areas, 0
    walls, 0 stacks and raises 0 set-health items or set questions from it);
  - the page index returns none of them to a search, a sheet lookup, the
    drawing list or the sheet index (_live_plan_file_ids is the one door);
  - a superseded-by mark that names it is not applied, and the marks are
    recomputed without it (_supersede_plan_pages);
  - the takeoff export and the chat evidence read 0 rows of it.

THE DEFAULT IS UNCHANGED: a file with no stored track, or filed, or post_co, is
read exactly as before (the last class).
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

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402

PID = str(ObjectId())
CID = "c-blueview"
ADMIN = {"id": "adm-1", "role": "admin", "company_id": CID, "account_status": "approved",
         "full_name": "Roy"}
F325, F818, FGAS, FMH = (str(ObjectId()) for _ in range(4))
NAMES = {F325: "AR - 3.28.25.pdf", F818: "AR - 8.18.26.pdf",
         FGAS: "AR - 6.9.26 (Gas change).pdf", FMH: "MH - 7.2.26.pdf"}


def _run(coro):
    return asyncio.run(coro)


def _present():
    assert hasattr(server, "IGNORED_TRACK"), \
        "a file cannot be ignored in this tree: the track is filed / post_co only"


def _pages():
    spec = [(F325, 11, "A-100.00", "FIRST FLOOR PLAN"), (F325, 12, "A-101.00", "SECOND FLOOR PLAN"),
            (F325, 16, "A-105.00", "ROOF AND BULKEAD PLAN"),
            (F818, 6, "A-100.01", "FIRST FLOOR PLAN"), (F818, 7, "A-105.01", "ROOF AND BULKEAD PLAN"),
            (F818, 8, "A-200.01", "FRONT AND REAR ELEVATIONS"),
            (FGAS, 1, "A-100.00", "FIRST FLOOR PLAN"), (FGAS, 2, None, "Roof Plan"),
            (FMH, 2, "M-100.00", "HVAC FIRST FLOOR PLAN"), (FMH, 3, "M-101.00", "HVAC SECOND FLOOR PLAN"),
            (FMH, 6, "M-105.00", "HVAC ROOF PLAN")]
    return [{"_id": f"{f}#{n}", "project_id": PID, "company_id": CID, "file_id": f,
             "file_hash": f"h-{f}", "file_name": NAMES[f], "page_number": n, "sheet_number": sn,
             "sheet_title": t, "discipline": "AR" if not (sn or "").startswith("M") else "MH",
             "superseded_by": None, "is_document": False} for f, n, sn, t in spec]


def _world(track818=None):
    db = AsyncFakeDB()
    db.projects.docs.append({"_id": ObjectId(PID), "name": "588", "company_id": CID,
                             "status": "active", "is_deleted": False})
    for f, name in NAMES.items():
        doc = {"_id": ObjectId(f), "project_id": PID, "company_id": CID, "name": name,
               "is_deleted": False}
        if f == F818 and track818:
            doc["drawing_track"] = track818
        db.project_files.docs.append(doc)
    for p in _pages():
        db.document_page_index.docs.append(p)
    return db


def _put(db, file_id, track, label=None):
    body = server.DrawingTrackUpdate(track=track, label=label)
    with patch.object(server, "db", db):
        return _run(server.set_file_drawing_track(PID, file_id, body, ADMIN))


def _with(db, coro_fn):
    with patch.object(server, "db", db):
        return _run(coro_fn())


def _ids_of(file_id, ids):
    return [i for i in ids if str(i).startswith(file_id)]


class TheAdminStatesIt(unittest.TestCase):

    def test_the_route_accepts_ignored_stores_it_audits_it_and_reads_it_back(self):
        _present()
        db = _world()
        out = _put(db, F818, "ignored")
        self.assertEqual(out["track"], "ignored")
        self.assertEqual(out["previous"]["track"], "filed")
        self.assertIn("ignored", out["label"])
        stored = next(f for f in db.project_files.docs if str(f["_id"]) == F818)
        self.assertEqual(stored["drawing_track"], "ignored")
        audit = [a for a in db.audit_logs.docs if a["action"] == "project_file_drawing_track"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["details"]["to"]["track"], "ignored")
        self.assertEqual(audit[0]["details"]["from"]["track"], "filed")
        back = _with(db, lambda: server.get_file_drawing_track(PID, F818, ADMIN))
        self.assertEqual((back["track"], back["ignored"], back["live"]), ("ignored", True, False))
        self.assertEqual((back["index_pages"], back["searchable_pages"], back["pages_the_pass_reads"]),
                         (3, 0, 0))

    def test_another_track_word_is_still_refused(self):
        _present()
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            _put(_world(), F818, "obsolete")
        self.assertEqual(cm.exception.status_code, 422)

    def test_another_companys_admin_cannot_state_it(self):
        _present()
        from fastapi import HTTPException
        other = dict(ADMIN, company_id="c-other", id="adm-2")
        db = _world()
        body = server.DrawingTrackUpdate(track="ignored")
        with patch.object(server, "db", db), self.assertRaises(HTTPException) as cm:
            _run(server.set_file_drawing_track(PID, F818, body, other))
        self.assertIn(cm.exception.status_code, (403, 404))
        self.assertFalse(next(f for f in db.project_files.docs
                              if str(f["_id"]) == F818).get("drawing_track"))

    def test_it_is_reversible_the_file_is_never_deleted(self):
        _present()
        db = _world()
        _put(db, F818, "ignored")
        _put(db, F818, "filed")
        live = _with(db, lambda: server._live_plan_file_ids(PID))
        self.assertIn(F818, live)
        self.assertEqual(len([p for p in db.document_page_index.docs if p["file_id"] == F818]), 3,
                         "its index rows were never touched")
        self.assertTrue(all(not f.get("is_deleted") for f in db.project_files.docs))


class ThePassReadsNoPageOfIt(unittest.TestCase):

    def _tracks(self, db):
        return dict(_with(db, lambda: server._glyph_pages(PID))[0])

    def test_no_track_holds_a_page_of_an_ignored_file(self):
        _present()
        db = _world("ignored")
        tracks = self._tracks(db)
        self.assertEqual(sorted(tracks), ["filed"], "no third 'ignored' track either")
        self.assertEqual(_ids_of(F818, [p["_id"] for p in tracks["filed"]]), [])

    def test_the_track_split_itself_skips_it_even_when_the_file_is_called_live(self):
        """_glyph_track_pages' own guard: a caller that hands it the file in
        `live` (a degraded lookup) still gets no track made of it."""
        _present()
        files = {f: {"name": n, "drawing_track": "ignored" if f == F818 else None}
                 for f, n in NAMES.items()}
        got = dict(server._glyph_track_pages(_pages(), files, set(NAMES)))
        self.assertEqual(sorted(got), ["filed"])
        self.assertEqual(_ids_of(F818, [p["_id"] for p in got["filed"]]), [])

    def test_the_census_scope_holds_none_of_its_pages(self):
        _present()
        db = _world("ignored")
        ids = _with(db, lambda: server._glyph_page_ids(PID))
        self.assertEqual(_ids_of(F818, ids), [])
        self.assertTrue(_ids_of(F325, ids))

    def test_with_it_ignored_the_march_roof_is_current_and_the_gas_first_floor_wins_by_date(self):
        _present()
        ids = {p["_id"]: p["sheet_number"] for p in self._tracks(_world("ignored"))["filed"]}
        self.assertEqual(ids.get(f"{F325}#16"), "A-105.00")
        self.assertIn(f"{FGAS}#1", ids)
        self.assertNotIn(f"{F325}#11", ids, "March A-100.00 loses to the gas A-100.00 by date")


class TheIndexReturnsNoneOfIt(unittest.TestCase):

    def test_live_ids_leave_it_out(self):
        _present()
        live = _with(_world("ignored"), lambda: server._live_plan_file_ids(PID))
        self.assertNotIn(F818, live)
        self.assertEqual(sorted(live), sorted([F325, FGAS, FMH]))

    def test_a_search_reads_none_of_its_pages(self):
        _present()
        db = _world("ignored")
        ids = _with(db, lambda: server._current_record_page_ids(PID))
        self.assertEqual(_ids_of(F818, ids), [])
        by_sheet = _with(db, lambda: server._current_record_page_ids(PID, sheet_number="A-105"))
        self.assertEqual(_ids_of(F818, by_sheet), [])

    def test_the_marks_that_cite_it_are_not_applied_and_are_recomputed_away(self):
        """3.28.25's A-105.00 carries a stored mark 'superseded by 8.18.26'. With
        8.18.26 ignored the page is current at once (a mark counts only while its
        winner is live), and the recompute in the route clears the stored mark."""
        _present()
        db = _world()
        for p in db.document_page_index.docs:
            if p["file_id"] == F325 and p["sheet_number"] in ("A-100.00", "A-105.00"):
                p["superseded_by"] = F818
        before = _with(db, lambda: server._current_record_page_ids(PID))
        self.assertNotIn(f"{F325}#16", before, "today the mark hides it")
        out = _put(db, F818, "ignored")
        after = _with(db, lambda: server._current_record_page_ids(PID))
        self.assertIn(f"{F325}#16", after)
        self.assertIn("index_marks", out)
        marks = {p["_id"]: p["superseded_by"] for p in db.document_page_index.docs
                 if p["file_id"] == F325}
        self.assertIsNone(marks[f"{F325}#16"], "the stored mark is recomputed without the ignored file")
        self.assertEqual(marks[f"{F325}#11"], FGAS, "A-100.00 is hidden by the gas A-100.00, by date")

    def test_an_ignored_file_supersedes_nothing_when_marks_are_recomputed(self):
        _present()
        db = _world("ignored")
        _with(db, lambda: server._supersede_plan_pages(PID))
        self.assertFalse([p for p in db.document_page_index.docs if p["superseded_by"] == F818])

    def test_the_drawing_list_and_the_sheet_index_hold_none_of_its_sheets(self):
        _present()
        db = _world("ignored")
        with patch.object(server, "db", db):
            live = _run(server._live_plan_file_ids(PID))
            got = _run(db.document_page_index.find(
                {"project_id": PID, **server._current_page_filter(live)}).to_list(100))
        self.assertEqual([r for r in got if r["file_id"] == F818], [])
        self.assertTrue(got)

    def test_the_level_suggestion_ignores_it(self):
        _present()
        db = _world("ignored")
        seen = {}

        def fake_suggest(rows):
            seen["sheets"] = sorted(str(r.get("sheet_number")) for r in rows)
            return {"levels": []}
        user = {"id": "u", "role": "admin", "company_id": CID}
        import lib.plans.level_suggestion as LS
        with patch.object(server, "db", db), patch.object(LS, "suggest_levels", fake_suggest), \
                patch.object(server, "project_access_ok", lambda *a, **k: True):
            _run(server.get_suggested_building_levels(PID, user))
        self.assertNotIn("A-105.01", seen["sheets"])
        self.assertNotIn("A-200.01", seen["sheets"])


class TheOutputsReadNoRowOfIt(unittest.TestCase):

    def test_the_stored_answers_read_nothing_of_it(self):
        """A stored Q2 whose replacements name the ignored file's pages: the
        pass finds no replaced page and drops it whole (said, not applied)."""
        _present()
        db = _world("ignored")
        q2 = {"_id": "q2", "project_id": PID, "company_id": CID, "status": "answered",
              "answer": "replaces", "track": "filed", "file_id": FGAS, "code": "Q2",
              "pages": [{"page_number": 2, "sheet_number": None}],
              "replacements": [{"page_id": f"{FGAS}#2", "file_id": FGAS, "page_number": 2,
                                "sheet_number": None, "sheet_title": "Roof Plan",
                                "takes_sheet_number": "A-105.01",
                                "replaces": {"page_id": f"{F818}#7", "file_id": F818,
                                             "page_number": 7, "sheet_number": "A-105.01",
                                             "sheet_title": "ROOF AND BULKEAD PLAN"}}]}
        db["plan_set_questions"].docs.append(q2)
        notes = []

        async def go():
            raw, files, live = await server._glyph_inputs(PID)
            return server._glyph_track_pages(raw, files, live, await server._set_decisions(PID), notes)
        got = dict(_with(db, go))
        self.assertEqual(_ids_of(F818, [p["_id"] for p in got["filed"]]), [])
        self.assertEqual([n["applied"] for n in notes], [False])


class TheDefaultIsUnchanged(unittest.TestCase):

    def test_no_stored_track_filed_and_post_co_are_all_live_and_all_read(self):
        for t in (None, "filed", "post_co"):
            db = _world(t)
            live = _with(db, lambda: server._live_plan_file_ids(PID))
            self.assertEqual(sorted(live), sorted(NAMES), t)
        tracks = dict(_with(_world(), lambda: server._glyph_pages(PID))[0])
        self.assertTrue(_ids_of(F818, [p["_id"] for p in tracks["filed"]]),
                        "an ordinary file's pages are read")
        post = dict(_with(_world("post_co"), lambda: server._glyph_pages(PID))[0])
        self.assertIn("post_co", post)

    def test_the_supersession_recompute_is_what_it_was_with_nothing_ignored(self):
        db = _world()
        out = _with(db, lambda: server._supersede_plan_pages(PID))
        marks = {p["_id"]: p["superseded_by"] for p in db.document_page_index.docs}
        # 8.18.26 (dated 8.18.26) supersedes the March A-100/A-105 and the gas A-100
        self.assertEqual(marks[f"{F325}#16"], F818)
        self.assertEqual(marks[f"{FGAS}#1"], F818)
        self.assertIn("superseded", out)

    def test_the_track_words_the_route_took_before_it_still_takes(self):
        self.assertEqual(server.DRAWING_TRACKS, ("filed", "post_co"))
        db = _world()
        for t in ("post_co", "filed"):
            self.assertEqual(_put(db, F325, t)["track"], t)


if __name__ == "__main__":
    unittest.main()
