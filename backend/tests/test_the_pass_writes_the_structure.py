"""THE GLYPH PASS WRITES THE STRUCTURE (ruling 106, 2026-10-29: "approved").

lib.plan_structural reads every S-1xx framing plan into polygons in the
paired architectural plan's frame (#915). This is its step in the operator's
glyph pass (server._plan_glyph_pass), per drawing track:

  - run while the PDFs are still downloaded, after set health;
  - the owner's post-CO set, which prints no S sheet, reads the filed set's,
    every row labelled (ruling 68);
  - WHOLE-PROJECT REPLACE of its own collection (plan_structural), like the
    areas and set health: search and the count gate never read it;
  - a failure writes one marker row and never sinks the pass;
  - the run record counts what it wrote (structure_written).

Each test fails on origin/main by ASSERTION, not by an import error.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
import tests.test_the_glyph_pass_says_where_it_is as G  # noqa: E402

try:
    from lib import plan_structural as T  # noqa: E402
except ImportError:
    T = None


def _present():
    assert T is not None and hasattr(T, "pass_rows"), \
        "plan_structural has no pass step: the glyph pass cannot write the structure"
    assert hasattr(server, "_write_structural_rows"), \
        "the glyph pass has no structure writer"


def _row(i, track="filed", note=None):
    return {"record_type": "structure", "project_id": G.PID, "track": track, "element": "shear_wall",
            "tag": f"SW {i}", "polygon_a": [[1.0, 2.0]], "structure_note": note}


class ThePassWritesWhatTheStepReturns(G._Route):

    def _run(self, pass_rows):
        _present()
        got = {}

        async def write(pid, rows):
            got["rows"] = list(rows)
            return len(rows)

        async def go():
            await server.run_plan_glyph_pass(G.PID, current_user=G.ADMIN)
            for _ in range(1000):
                if G.PID not in server._GLYPH_PASS_RUNNING:
                    break
                await asyncio.sleep(0.01)
        with ExitStack() as st:
            written = self._server_pass(st)
            st.enter_context(patch.object(server, "_write_structural_rows", write))
            st.enter_context(patch.object(T, "pass_rows", pass_rows))
            asyncio.run(go())
        return got, written, server._GLYPH_PASS_PROGRESS[G.PID].last_result()

    def test_every_track_is_handed_to_the_step_and_its_rows_are_written(self):
        seen = {}

        def pass_rows(tracks, open_page, *, project_id, company_id=None):
            seen["tracks"] = [t for t, _ps in tracks]
            seen["pid"] = project_id
            return {"rows": [_row(1), _row(2, "post_co", T.OWNER_SET_NOTE.format(sheet="S-104.00"))],
                    "by_track": {}}
        got, written, last = self._run(pass_rows)
        self.assertEqual(seen["tracks"], ["filed", "post_co"])
        self.assertEqual(seen["pid"], G.PID)
        self.assertEqual([r["tag"] for r in got["rows"]], ["SW 1", "SW 2"])
        self.assertEqual(last["result"], "ok")
        self.assertEqual(last["summary"]["structure_written"], 2)
        self.assertGreater(written["rows"], 0)                    # the glyph rows still written

    def test_a_failed_step_writes_one_marker_and_the_pass_still_ends_ok(self):
        def pass_rows(*a, **k):
            raise ValueError("S-104 unreadable")
        got, written, last = self._run(pass_rows)
        self.assertEqual(len(got["rows"]), 1)
        self.assertEqual(got["rows"][0]["record_type"], "structure_unavailable")
        self.assertIn("ValueError: S-104 unreadable", got["rows"][0]["error"])
        self.assertEqual(last["result"], "ok")
        self.assertGreater(written["rows"], 0)


class TheWriterReplacesTheWholeProject(unittest.TestCase):

    def test_an_older_pass_and_another_project_are_handled_right(self):
        _present()
        from tests.async_fake_mongo import AsyncFakeDB
        db = AsyncFakeDB()
        coll = db[T.COLLECTION]
        coll.docs.extend([{"_id": "old1", "project_id": G.PID, "tag": "SW 9"},
                          {"_id": "other", "project_id": "another", "tag": "SW 1"}])
        with patch.object(server, "db", db):
            n = asyncio.run(server._write_structural_rows(G.PID, [_row(1), _row(2)]))
        self.assertEqual(n, 2)
        mine = [d for d in coll.docs if d["project_id"] == G.PID]
        self.assertEqual(sorted(d["tag"] for d in mine), ["SW 1", "SW 2"])
        self.assertEqual([d["ordinal"] for d in sorted(mine, key=lambda d: d["ordinal"])], [0, 1])
        self.assertTrue(any(d["_id"] == "other" for d in coll.docs))


class TheStoredRows(unittest.TestCase):

    def test_a_row_is_plain_bson_with_its_project(self):
        _present()
        r = T.rows_for_store([{"element": "post", "polygon_a": [[np.float64(1.5), np.float64(2.0)]],
                               "registration": {"margin": np.float64(1.92)}, "attrs": {"n": np.int64(3)},
                               "at": (1.0, 2.0)}], project_id=G.PID, company_id="co1")[0]
        self.assertEqual(r["record_type"], "structure")
        self.assertEqual((r["project_id"], r["company_id"]), (G.PID, "co1"))
        self.assertIs(type(r["polygon_a"][0][0]), float)
        self.assertIs(type(r["attrs"]["n"]), int)
        self.assertEqual(r["at"], [1.0, 2.0])

    def test_a_track_row_says_its_pairs_margins_and_label(self):
        _present()
        note = T.OWNER_SET_NOTE.format(sheet="S-104.00")
        res = {"summary": {"offset": 1, "refused": [{"sheet": "S-107.00", "reason": "x"}], "pairs": [
            {"s": "S-104.00", "a": "A-103.00", "level": "FLOOR_4", "elements": 89, "unassigned_tags": [],
             "registration": {"dx": 6.3, "dy": -242.49, "anchors": 209, "best_peak_anchors": 205,
                              "second_peak_anchors": 107, "margin": 1.916, "wall_share_best": 0.9647,
                              "wall_share_second": 0.3473, "usable": True, "refused": None}}]},
               "rows": [{"structure_note": note}] * 3}
        t = T.track_row("post_co", res, project_id=G.PID, company_id="co1")
        self.assertEqual(t["record_type"], "structure_track")
        self.assertEqual(t["rows"], 3)
        self.assertEqual(t["pairs"][0]["registration"]["margin"], 1.916)
        self.assertEqual(t["pairs"][0]["registration"]["wall_share_second"], 0.3473)
        self.assertEqual(t["refused"][0]["sheet"], "S-107.00")
        self.assertEqual(t["structure_notes"], [note])

    def test_pass_rows_gives_every_track_its_rows_and_one_track_row(self):
        _present()
        real = T.run_tracks
        try:
            T.run_tracks = lambda tracks, op: {
                "filed": {"rows": [{"tag": "SW 1"}, {"tag": "SW 2"}], "summary": {}},
                "post_co": {"rows": [{"tag": "SW 1", "structure_note": "n"}], "summary": {}}}
            out = T.pass_rows([("filed", []), ("post_co", [])], None, project_id=G.PID, company_id=None)
        finally:
            T.run_tracks = real
        kinds = [(r["record_type"], r.get("track")) for r in out["rows"]]
        self.assertEqual(kinds, [("structure", None), ("structure", None), ("structure_track", "filed"),
                                 ("structure", None), ("structure_track", "post_co")])
        self.assertEqual(out["by_track"], {"filed": 2, "post_co": 1})


if __name__ == "__main__":
    unittest.main()
