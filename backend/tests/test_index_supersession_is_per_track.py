"""THE INDEX SUPERSEDES WITHIN A DRAWING TRACK, NEVER ACROSS ONE (Roy, 10-31).

The filed original and its filed amendments are ONE track; the post-CO set
(on 588 Boyland, the Owner's set) is its own. A later post-CO sheet never
hides a filed sheet and a filed sheet never hides a post-CO one: after-CO
sheets are separate records of changes, not replacements of anything
approved (the hard rule of 10-30). An ignored file takes no part.

Found by MARKS_EFFECT: once AR 8.18.26 was ignored, the Owner's set (title
block 6/9/26) beat the gas change (6/8/26) and AR 3.28.25 in the page index,
so search offered only the owner's post-CO A-100.00 / A-105.00 - the reverse
of the hard rule.

Both tracks stay searchable and LABELLED; default retrieval returns the FILED
sheet, and the owner's only when the question concerns the owner's set.
Every rule below has a mutation (role_prs/mutate_suptrack.py).
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
from lib import plan_sources  # noqa: E402

PID = str(ObjectId())
CID = "c-blueview"
F325, F818, FGAS, FOWN, FMH, FNEW = (str(ObjectId()) for _ in range(6))
NAMES = {F325: "AR - 3.28.25.pdf", F818: "AR - 8.18.26.pdf",
         FGAS: "AR - 6.9.26 (Gas change).pdf", FOWN: "Owners set - 6.9.26.pdf",
         FMH: "MH - 7.2.26.pdf", FNEW: "AR - 9.1.26.pdf"}
TRACK = {FOWN: "post_co"}


def _run(coro):
    return asyncio.run(coro)


def _present():
    assert hasattr(server, "_supersession_winners_in_one_track"), \
        "the index still compares revisions across drawing tracks in this tree"


# (file, page, sheet, title, title-block revision) - 588 Boyland as the index holds it.
SPEC = [
    (F325, 1, "T-001.00", "COVER", None),
    (F325, 11, "A-100.00", "FIRST FLOOR PLAN", "03/28/2025"),
    (F325, 12, "A-101.00", "SECOND FLOOR PLAN", "03/28/2025"),
    (F325, 16, "A-105.00", "ROOF AND BULKHEAD PLAN", "03/28/2025"),
    (F325, 17, "A-200.00", "ELEVATIONS", None),
    (F818, 1, "T-001.01", "COVER", None),
    (F818, 6, "A-100.01", "FIRST FLOOR PLAN", None),
    (F818, 7, "A-105.01", "ROOF AND BULKHEAD PLAN", None),
    (F818, 8, "A-200.01", "ELEVATIONS", None),
    (FGAS, 1, "A-100.00", "FIRST FLOOR PLAN", "06/08/2026"),
    (FGAS, 2, None, "Roof Plan", None),
    (FOWN, 1, "A-100.00", "FIRST FLOOR PLAN - OWNERS", "06/09/2026"),
    (FOWN, 2, "A-101.00", "SECOND FLOOR PLAN", "06/09/2026"),
    (FOWN, 6, "A-105.00", "ROOF PLAN", "06/09/2026"),
    (FOWN, 7, "A-302.00", "WALL SECTIONS", "06/09/2026"),     # only the owner's set prints it
    (FMH, 2, "M-100.00", "HVAC FIRST FLOOR PLAN", None),
]


def _pages(spec=SPEC):
    return [{"_id": f"{f}#{n}", "project_id": PID, "company_id": CID, "file_id": f,
             "file_hash": f"h-{f}", "file_name": NAMES[f], "page_number": n,
             "sheet_number": sn, "sheet_title": t, "revision_date": rev,
             "sheet_position": None, "discipline": "AR", "superseded_by": None,
             "is_document": False, "page_jpeg_r2_key": f"k-{f}-{n}"} for f, n, sn, t, rev in spec]


def _files(tracks=None, only=None):
    tracks = dict(TRACK, **(tracks or {}))
    out = []
    for i, (f, name) in enumerate(NAMES.items()):
        if only is not None and f not in only:
            continue
        doc = {"_id": f, "name": name, "created_at": f"2026-08-27T12:28:{i:02d}"}
        if tracks.get(f):
            doc["drawing_track"] = tracks[f]
        out.append(doc)
    return out


def _winners(tracks=None, only=None, spec=SPEC):
    files = _files(tracks, only)
    ids = {f["_id"] for f in files}
    rows = [r for r in _pages(spec) if r["file_id"] in ids]
    return server._supersession_winners(rows, files, PID)


def _marks(tracks=None, only=None):
    w = _winners(tracks, only)
    return {k: v for k, v in w.items()}


def _world(tracks=None, spec=SPEC):
    """A fake database whose project_files.find APPLIES the projection, so a
    field the route forgets to ask for is missing, as in Mongo."""
    tracks = dict(TRACK, **(tracks or {}))
    db = AsyncFakeDB()
    db.projects.docs.append({"_id": ObjectId(PID), "name": "588", "company_id": CID,
                             "status": "active", "is_deleted": False})
    for f, name in NAMES.items():
        doc = {"_id": ObjectId(f), "project_id": PID, "company_id": CID, "name": name,
               "is_deleted": False, "created_at": f"2026-08-27T12:28:{len(db.project_files.docs):02d}"}
        if tracks.get(f):
            doc["drawing_track"] = tracks[f]
        db.project_files.docs.append(doc)
    for p in _pages(spec):
        db.document_page_index.docs.append(p)
    coll = db.project_files
    real_find = coll.find

    def find(flt=None, projection=None, **kw):
        cur = real_find(flt, projection, **kw)
        if not projection:
            return cur
        keep = {k for k, v in projection.items() if v} | {"_id"}

        class _P:
            async def to_list(self, n=None):
                rows = await cur.to_list(n)
                return [{k: v for k, v in r.items() if k in keep} for r in rows]
        return _P()
    coll.find = find
    return db


def _with(db, fn):
    with patch.object(server, "db", db):
        return _run(fn())


# ═══════════════════════════════════════════════════════════════════════════
class ATrackNeverHidesTheOther(unittest.TestCase):

    def test_a_later_post_co_sheet_does_not_hide_a_filed_one(self):
        """The Owner's set (6/9/26) is later than every filed sheet and hides
        none of them."""
        w = _winners()
        for pid in (f"{F325}#11", f"{F325}#12", f"{F325}#16", f"{FGAS}#1"):
            self.assertNotEqual(w.get(pid), FOWN, f"{pid} is hidden by the post-CO set")
        self.assertNotIn(f"{F325}#12", w, "filed A-101.00 stays current beside the owner's A-101.00")

    def test_a_filed_sheet_does_not_hide_a_post_co_one(self):
        """A filed set LATER than the owner's (AR 9.1.26) hides none of the
        owner's sheets."""
        spec = SPEC + [(FNEW, 1, "A-100.00", "FIRST FLOOR PLAN", None),
                       (FNEW, 2, "A-101.00", "SECOND FLOOR PLAN", None)]
        w = _winners(spec=spec)
        self.assertNotIn(f"{FOWN}#1", w)
        self.assertNotIn(f"{FOWN}#2", w)
        # ... while inside the filed track the later set still wins.
        self.assertEqual(w.get(f"{F325}#12"), FNEW)

    def test_inside_the_filed_track_the_amendment_still_supersedes(self):
        """The gas change (6/9/26) replaces 3.28.25's A-100.00, by date, in
        the filed track."""
        w = _winners(tracks={F818: "ignored"})
        self.assertEqual(w.get(f"{F325}#11"), FGAS)

    def test_inside_the_post_co_track_the_later_issue_still_supersedes(self):
        later = "6adf0000000000000000beef"
        NAMES[later] = "Owners set - 7.1.26.pdf"
        try:
            spec = SPEC + [(later, 1, "A-100.00", "FIRST FLOOR PLAN", None)]
            files = _files(only=set(NAMES) - {later}) + [
                {"_id": later, "name": NAMES[later], "created_at": "2026-08-27T12:30:00",
                 "drawing_track": "post_co"}]
            rows = [r for r in _pages(spec) if r["file_id"] in {f["_id"] for f in files}]
            w = server._supersession_winners(rows, files, PID)
        finally:
            NAMES.pop(later)
        self.assertEqual(w.get(f"{FOWN}#1"), later)
        self.assertNotIn(f"{later}#1", w)

    def test_no_stored_track_is_filed_and_post_co_is_its_own(self):
        # With the Owner's set read as FILED (no stored track) it supersedes
        # the older filed sheets, as it always did: the partition is the track.
        w = _winners(tracks={FOWN: None})
        self.assertEqual(w.get(f"{F325}#12"), FOWN)
        self.assertEqual(_winners().get(f"{F325}#12"), None)

    def test_the_index_marks_are_written_per_track(self):
        """_supersede_plan_pages reads each file's track (the projection asks
        for it) and writes no mark across tracks."""
        db = _world()
        _with(db, lambda: server._supersede_plan_pages(PID))
        marks = {p["_id"]: p["superseded_by"] for p in db.document_page_index.docs}
        named = {k: v for k, v in marks.items() if v}
        self.assertNotIn(FOWN, named.values(), "a mark names the post-CO set")
        self.assertFalse([k for k in named if k.startswith(FOWN)], "a post-CO page carries a mark")
        self.assertEqual(named[f"{F325}#11"], F818, "inside the filed track the later set wins")
        self.assertIsNone(marks[f"{F325}#12"])
        self.assertIsNone(marks[f"{FOWN}#1"])


class AnIgnoredFileTakesNoPart(unittest.TestCase):

    def test_an_ignored_file_neither_wins_nor_loses_in_either_track(self):
        w = _winners(tracks={F818: "ignored"})
        self.assertFalse([k for k, v in w.items() if v == F818], "the ignored file hides a page")
        self.assertFalse([k for k in w if k.startswith(F818)], "the ignored file's page is hidden")
        # an ignored POST-CO-looking later file hides nothing either
        spec = SPEC + [(FNEW, 1, "A-101.00", "SECOND FLOOR PLAN", None)]
        w2 = _winners(tracks={FNEW: "ignored"}, spec=spec)
        self.assertFalse([k for k, v in w2.items() if v == FNEW])
        self.assertFalse([k for k in w2 if k.startswith(FNEW)])

    def test_two_ignored_files_do_not_supersede_each_other(self):
        """Ignored files are not a track of their own: neither of two ignored
        issues of one sheet is marked."""
        w = _winners(tracks={F325: "ignored", F818: "ignored"})
        self.assertFalse([k for k in w if k.startswith((F325, F818))])
        self.assertFalse([k for k, v in w.items() if v in (F325, F818)])

    def test_marks_recomputed_without_the_ignored_file_are_the_per_track_rule(self):
        """The ignore call's marks (AR 8.18.26 ignored): 3.28.25 A-100.00 is
        hidden by the gas A-100.00 (filed track) and NOTHING is hidden by the
        Owner's set; 3.28.25 A-105.00 stays current."""
        db = _world(tracks={F818: "ignored"})
        _with(db, lambda: server._supersede_plan_pages(PID))
        marks = {p["_id"]: p["superseded_by"] for p in db.document_page_index.docs if p["superseded_by"]}
        self.assertEqual(marks, {f"{F325}#11": FGAS})


class BothTracksAreSearchableAndLabelled(unittest.TestCase):

    def _ids(self, db, **kw):
        return set(_with(db, lambda: server._current_record_page_ids(PID, **kw)))

    def _world_marked(self):
        db = _world(tracks={F818: "ignored"})
        _with(db, lambda: server._supersede_plan_pages(PID))
        return db

    def test_both_tracks_stay_current_and_searchable(self):
        _present()
        ids = self._ids(self._world_marked())
        for pid in (f"{FGAS}#1", f"{F325}#12", f"{F325}#16", f"{FOWN}#1", f"{FOWN}#2", f"{FOWN}#6"):
            self.assertIn(pid, ids)
        self.assertNotIn(f"{F325}#11", ids, "the filed amendment supersedes the filed original")
        self.assertFalse([i for i in ids if i.startswith(F818)], "an ignored file is not searchable")

    def test_default_retrieval_returns_the_filed_sheet(self):
        _present()
        ids = self._ids(self._world_marked(), retrieval=True)
        self.assertIn(f"{FGAS}#1", ids)
        self.assertIn(f"{F325}#12", ids)
        self.assertIn(f"{F325}#16", ids)
        for hidden in (f"{FOWN}#1", f"{FOWN}#2", f"{FOWN}#6"):
            self.assertNotIn(hidden, ids, "the owner's page of a filed sheet is not offered by default")
        self.assertIn(f"{FOWN}#7", ids, "an owner's sheet the filed set does not print is still found")

    def test_the_owners_set_question_returns_both_tracks(self):
        _present()
        ids = self._ids(self._world_marked(), retrieval=True, owner_set=True)
        for pid in (f"{FGAS}#1", f"{F325}#12", f"{FOWN}#1", f"{FOWN}#2", f"{FOWN}#6", f"{FOWN}#7"):
            self.assertIn(pid, ids)

    def test_the_census_scope_is_every_current_page_of_every_track(self):
        """No retrieval flag (the glyph census, the read-back): nothing left out."""
        _present()
        ids = self._ids(self._world_marked())
        self.assertIn(f"{FOWN}#1", ids)
        self.assertIn(f"{FGAS}#1", ids)

    def test_a_named_sheet_is_the_filed_one_unless_the_owners_set_is_asked(self):
        _present()
        db = self._world_marked()
        got = _with(db, lambda: server._find_named_sheet(PID, "A-100"))
        self.assertEqual([r["_id"] for r in got], [f"{FGAS}#1"])
        got = _with(db, lambda: server._find_named_sheet(PID, "A-100", owner_set=True))
        self.assertEqual([r["_id"] for r in got], [f"{FOWN}#1"])
        # a number only the owner's set prints is found from it either way
        for flag in (False, True):
            got = _with(db, lambda: server._find_named_sheet(PID, "A-302", owner_set=flag))
            self.assertEqual([r["_id"] for r in got], [f"{FOWN}#7"])
        # the owner's set asked about a sheet only the filed set prints: the filed one
        got = _with(db, lambda: server._find_named_sheet(PID, "M-100", owner_set=True))
        self.assertEqual([r["_id"] for r in got], [f"{FMH}#2"])

    def test_the_pure_rule_leaves_nothing_out_for_an_owners_set_question(self):
        pages = [{"_id": "f", "file_id": "F", "sheet_number": "A-100.00"},
                 {"_id": "o", "file_id": "O", "sheet_number": "A-100.01"},
                 {"_id": "x", "file_id": "O", "sheet_number": "A-302.00"},
                 {"_id": "n", "file_id": "O", "sheet_number": None}]
        tr = {"O": "post_co"}
        self.assertEqual(plan_sources.default_track_hidden(pages, tr), {"o"},
                         "same sheet (a reissue suffix aside) in both tracks: the filed one")
        self.assertEqual(plan_sources.default_track_hidden(pages, tr, owner_set=True), set())

    def test_each_page_is_cited_with_its_own_set(self):
        _present()
        db = self._world_marked()
        src = _with(db, lambda: server._plan_file_sources(PID, [FOWN, FGAS]))
        self.assertEqual(plan_sources.cite_with_set("A-100.00", src[FOWN]), "A-100.00 (owner's set)")
        self.assertEqual(plan_sources.cite_with_set("A-100.00", src[FGAS]), "A-100.00")

    def test_the_sheet_index_and_levels_and_drawing_list_name_one_title_per_number(self):
        _present()
        db = self._world_marked()
        db.document_page_index.docs.reverse()          # the owner's page is met first
        lines = _with(db, lambda: server._sheet_index_lines(PID))
        self.assertEqual([ln for ln in lines if ln.startswith("A-100.00")],
                         ["A-100.00 — FIRST FLOOR PLAN"], "the filed set's title, not the owner's")
        self.assertTrue(any(ln.startswith("A-302.00") for ln in lines))
        rows = _with(db, lambda: server._level_rows(PID))
        self.assertNotIn(f"{FOWN}#2", {str(r["_id"]) for r in rows})
        self.assertIn(f"{F325}#12", {str(r["_id"]) for r in rows})


class TheOwnersSetQuestionIsRouted(unittest.TestCase):

    def test_the_words_that_ask_for_the_owners_set(self):
        for text in ("what does the owner's set show on A-100", "owners set roof plan",
                     "per the owner's post-CO set, how many doors", "post-CO changes to the roof",
                     "what changed after CO", "the Owners plans for the first floor",
                     "Owners set - 6.9.26"):
            self.assertTrue(plan_sources.asks_owner_set(text), text)
        for text in ("how many doors on the first floor", "show me A-100", "the gas change roof",
                     "who is the owner of the building", "what is the PTAC model",
                     "the approval from the owner", ""):
            self.assertFalse(plan_sources.asks_owner_set(text), text)
        self.assertFalse(plan_sources.asks_owner_set(None, ""))

    def test_each_phrase_Roy_named_is_read_in_any_case(self):
        for text in ("owner drawings for the roof", "OWNER PLANS A-100", "the Owner Set", "owner's set",
                     "owners plans", "post co changes", "POST-CO", "Post CO", "what changed after C/O",
                     "after c/o", "AFTER CO", "the CO set roof", "CO SET", "co sets"):
            self.assertTrue(plan_sources.asks_owner_set(text), text)

    def test_ordinary_words_do_not_trigger_it(self):
        for text in ("the owner", "owner approved it", "owners of the units", "company set up the roof",
                     "CO2 sensor count", "co-ordinate with the GC", "coat set", "cost set", "after company",
                     "after coordination", "after CO2 alarm", "postcode", "post col", "echo set", "disco set", "taco sets",
                     "a company set of plans", "who is the owner?", "per the owner"):
            self.assertFalse(plan_sources.asks_owner_set(text), text)

    def test_search_plans_reads_the_question_and_passes_it_to_retrieval(self):
        _present()
        seen = []

        async def fake_ids(project_id, **kw):
            seen.append(kw)
            return []

        async def fake_interpret(project_id, subject, floor, attribute, intent, interp, **kw):
            return subject, floor, []

        async def go(*args, **kw):
            with patch.object(server, "_current_record_page_ids", fake_ids), \
                 patch.object(server, "_interpret_query", fake_interpret):
                return await server.search_plans(PID, *args, **kw)

        _run(go("first floor plan sheet", intent="attribute"))
        self.assertTrue(seen[-1].get("retrieval"))
        self.assertFalse(seen[-1].get("owner_set"))
        _run(go("what does the owner's set show on the first floor plan"))
        self.assertTrue(seen[-1].get("owner_set"))
        _run(go("first floor plan", owner_set=True))          # the caller's own words said it
        self.assertTrue(seen[-1].get("owner_set"))

    def test_a_named_sheet_request_reads_the_users_words(self):
        """`_handle_plan_query` hands _find_named_sheet the user's words."""
        _present()
        import inspect
        src = inspect.getsource(server._handle_plan_query)
        self.assertIn("_find_named_sheet(\n            project_id, named, owner_set=plan_sources.asks_owner_set(route_text))", src)


if __name__ == "__main__":
    unittest.main()
