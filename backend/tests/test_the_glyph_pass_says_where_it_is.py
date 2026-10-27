"""The glyph pass says where it is, and how the last one ended (2026-10-27).

Roy's pass on 588 Boyland ran 48 minutes, and the owner's-set track logged
nothing for seventeen of them: its mechanical sweeps are the filed track's,
reused, and the only line the per-floor work ever logged was the sweep's own
"SWEEP CROP". GET .../plan-glyphs/status said only running: true. Now:

- run_pass takes an optional progress callback (lib.plan_pass_progress) and
  calls it at every step, on every track; one INFO line a sheet is logged;
- the status route reports the running pass's track, stage, sheets done and
  total, current sheet, started_at, per-sheet timings and an ETA from them;
- after the pass ends it reports the result: ok, failed (the error's class
  and repr - str() of a ReadTimeout is empty), or aborted by a re-index;
- a callback that raises never breaks the pass, and the rows are the same
  with a callback or without one;
- every key the status route returned before is still there.

Control on main fails by assertion (_present).
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
import threading
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "smoke_test"),
             ("JWT_SECRET", "smoke_test_secret"), ("APP_BASE_URL", "https://app.levelog.com")):
    os.environ.setdefault(k, v)

import server  # noqa: E402
from lib import plan_derive as D  # noqa: E402
from lib import plan_glyph_pass as G  # noqa: E402
# IMPORTED BEFORE ANY PATCH: plan_takeoff (and plan_space) bind plan_sheet.load_sheet
# at import, so a module first imported inside _fast() would keep its stub for
# every later test in the process - the real end-to-end passes then read no
# geometry (found when this file ran first, before test_the_owners_set_...).
from lib import plan_only, plan_openings, plan_space, plan_takeoff  # noqa: E402,F401
from tests.async_fake_mongo import AsyncFakeDB  # noqa: E402

PID = "proj-progress"
ADMIN = {"_id": "u1", "role": "admin", "company_id": "co1"}
OLD_KEYS = ("running", "last_written_at", "rows", "set_health_items", "reindex_in_flight")


def _present():
    assert importlib.util.find_spec("lib.plan_pass_progress") is not None, \
        "the glyph pass reports no progress in this tree (main)"
    from lib import plan_pass_progress
    return plan_pass_progress


# ── a two-track set the pass runs in milliseconds ─────────────────────────
def _pg(pid, num, title, fid, n):
    return {"page_id": pid, "_id": pid, "file_id": fid, "page_number": n, "sheet_number": num,
            "sheet_title": title, "file_name": f"{fid}.pdf"}


M101 = _pg("pm101", "M-101.00", "SECOND FLOOR HVAC PLAN", "mech", 2)
FILED = [_pg("pm106", "M-106.00", "BULKHEAD HVAC PLANS", "mech", 6),
         _pg("pa101", "A-101.00", "SECOND FLOOR PLAN", "ar", 1), M101,
         _pg("pa102", "A-102.00", "THIRD FLOOR PLAN", "ar", 2),
         _pg("pm102", "M-102.00", "THIRD FLOOR HVAC PLAN", "mech", 3),
         _pg("pp206", "P-206.00", "ROOF SANITARY & STORM PLAN", "plumb", 1)]
OWNER = [_pg("po101", "A-101.00", "SECOND FLOOR PLAN", "own", 1), M101]
SCHED = [{"name": "SUPPLY AIR FAN SCHEDULE", "tier": "ocr_grid_cell", "sheet_number": "M-200.00",
          "columns": [{"header": "MARK", "role": "identifier"}], "rows": [["SAF-1"]]}]
DOORS = [{"name": "DOOR SCHEDULE", "tier": "ocr_grid_cell", "sheet_number": "A-400.00",
          "columns": [{"header": "MARK", "role": "identifier"}], "rows": [["D1"], ["D2"]]}]
PLAN_ONLY = {"ROOF DRAINS": {"tags": ["RD-1"]}}
#: the sheet steps of each track, in run_pass's order
FILED_STEPS = [("sheet_scope", "M-106.00"), ("floors", "A-101.00"), ("floors", "A-102.00"),
               ("openings", "A-101.00"), ("openings", "A-102.00"),
               ("takeoff", "A-101.00|M-101.00"), ("takeoff", "A-102.00|M-102.00"),
               ("plan_only", "P-206.00 (ROOF DRAINS)")]
OWNER_STEPS = [("floors", "A-101.00"), ("openings", "A-101.00"), ("takeoff", "A-101.00|M-101.00")]


class _Page:
    directed_words = []


def _takeoff(arch_page, mech_page, tags, *a, unplaced_reason=None, **k):
    return {"records": [{"tag": tags[0], "unit": None, "glyph_status": "resolved",
                         "placement": "refused", "reason": unplaced_reason, "how": unplaced_reason,
                         "label_text": tags[0]}],
            "method": None, "registration": {"usable": False}}


def _fast(stack, takeoff=_takeoff):
    """The OCR, the sheet geometry and the unit reading stubbed: every floor
    names no units, so each is counted at sheet scope."""
    stack.enter_context(patch.object(D, "unit_tags", lambda w, c: {"tags": None, "why": "no units"}))
    stack.enter_context(patch("lib.plan_sheet.load_sheet",
                              lambda pg: {"words": [], "corners": [], "segs": []}))
    stack.enter_context(patch("lib.plan_takeoff.sweep", lambda *a, **k: []))
    stack.enter_context(patch("lib.plan_takeoff.run_takeoff", takeoff))
    stack.enter_context(patch("lib.plan_openings.floor_records", lambda *a, **k: {
        "records": {}, "orphans": [], "legend": [], "untagged": 0, "unreadable": []}))


def _both_tracks(progress_of=lambda t: None):
    out, sweeps = {}, {}
    with ExitStack() as st:
        _fast(st)
        for t, ps in (("filed", FILED), ("post_co", OWNER)):
            kw = {"progress": progress_of(t)} if progress_of(t) is not None else {}
            out[t] = G.run_pass(ps, lambda p: _Page(), SCHED, [], track=t, sweeps=sweeps,
                                plan_only=PLAN_ONLY, opening_schedules=DOORS, **kw)
    return out


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ── 1. progress advances per sheet, on both tracks ────────────────────────
class ProgressAdvancesPerSheetOnBothTracks(unittest.TestCase):

    def test_every_sheet_step_of_both_tracks_is_told(self):
        _present()
        seen = []
        _both_tracks(lambda t: (lambda kind, info: seen.append((t, kind, dict(info)))))
        sheets = [(t, i["stage"], i["sheet"]) for t, k, i in seen if k == "sheet"]
        self.assertEqual(sheets, [("filed", s, sh) for s, sh in FILED_STEPS]
                         + [("post_co", s, sh) for s, sh in OWNER_STEPS])
        plans = {t: [tuple(x) for x in i["steps"]] for t, k, i in seen if k == "plan"}
        self.assertEqual(plans, {"filed": FILED_STEPS, "post_co": OWNER_STEPS})
        self.assertEqual([t for t, k, _ in seen if k == "done"], ["filed", "post_co"])
        stages = [i["stage"] for t, k, i in seen if k == "stage" and t == "post_co"]
        self.assertEqual(stages, ["door", "seeding", "areas", "voids"])

    def test_the_owners_takeoff_says_its_sweep_is_reused(self):
        """Why the owner's track logged nothing: its mechanical sheet was
        swept by the filed track, and only a sweep ever logged."""
        _present()
        seen = []
        _both_tracks(lambda t: (lambda kind, info: seen.append((t, kind, dict(info)))))
        sweep = {(t, i["sheet"]): i.get("sweep") for t, k, i in seen
                 if k == "sheet" and i["stage"] == "takeoff"}
        self.assertEqual(sweep, {("filed", "A-101.00|M-101.00"): "read",
                                 ("filed", "A-102.00|M-102.00"): "read",
                                 ("post_co", "A-101.00|M-101.00"): "reused"})

    def test_the_tracker_counts_them_and_logs_a_line_a_sheet(self):
        P = _present()
        tr = P.PassProgress(PID)
        tr.plan([("filed", G.sheet_steps(FILED, SCHED, PLAN_ONLY, DOORS)),
                 ("post_co", G.sheet_steps(OWNER, SCHED, PLAN_ONLY, DOORS))])
        snap0 = tr.snapshot()
        self.assertEqual((snap0["sheets_done"], snap0["sheets_total"]), (0, 11))
        with self.assertLogs("lib.plan_pass_progress", level="INFO") as logs:
            _both_tracks(tr.callback)
        snap = tr.snapshot()
        self.assertEqual((snap["sheets_done"], snap["sheets_total"]), (11, 11))
        self.assertEqual(snap["tracks"], {"filed": {"status": "done", "sheets_done": 8, "sheets_total": 8},
                                          "post_co": {"status": "done", "sheets_done": 3, "sheets_total": 3}})
        self.assertEqual([(t["track"], t["stage"], t["sheet"]) for t in snap["timings"]],
                         [("filed", s, sh) for s, sh in FILED_STEPS]
                         + [("post_co", s, sh) for s, sh in OWNER_STEPS])
        per_sheet = [r.getMessage() for r in logs.records if "ETA" in r.getMessage()]
        self.assertEqual(len(per_sheet), 11)
        self.assertIn("track post_co takeoff A-101.00|M-101.00 1/1 took", per_sheet[-1])
        self.assertIn("sweep reused", per_sheet[-1])
        self.assertIn("(sheets 11/11)", per_sheet[-1])
        self.assertIn("track filed sheet_scope M-106.00 1/1 took", per_sheet[0])


# ── 2. the ETA is computed from the timings ───────────────────────────────
class TheEtaComesFromTheTimings(unittest.TestCase):

    def _tracker(self):
        P = _present()
        clock = _Clock()
        t0 = datetime(2026, 10, 27, 18, 33, 30, tzinfo=timezone.utc)
        tr = P.PassProgress(PID, clock=clock, now=lambda: t0 + timedelta(seconds=clock.t - 1000))
        tr.plan([("filed", [("takeoff", f"A-10{i}|M-10{i}") for i in range(3)]),
                 ("post_co", [("takeoff", f"A-10{i}|M-10{i}") for i in range(2)])])
        return tr, clock, t0

    def _sheet(self, tr, track, i, n=3):
        tr.callback(track)("sheet", {"stage": "takeoff", "sheet": f"A-10{i}|M-10{i}", "i": i + 1,
                                     "n": n, "sweep": "read"})

    def test_none_until_a_sheet_finishes(self):
        tr, clock, _ = self._tracker()
        self._sheet(tr, "filed", 0)
        clock.t += 50
        self.assertIsNone(tr.snapshot()["eta_s"])

    def test_mean_seconds_times_the_sheets_remaining(self):
        tr, clock, t0 = self._tracker()
        self._sheet(tr, "filed", 0)
        clock.t += 100
        self._sheet(tr, "filed", 1)               # sheet 0 took 100s
        snap = tr.snapshot()
        # 4 sheets left (sheet 1 open, sheet 2, and the owner's 2) x 100s
        self.assertEqual(snap["eta_s"], 400.0)
        self.assertEqual(snap["eta_at"], (t0 + timedelta(seconds=500)).isoformat())
        clock.t += 60                             # the open sheet's 60s are spent
        self.assertEqual(tr.snapshot()["eta_s"], 340.0)
        clock.t += 140
        self._sheet(tr, "filed", 2)               # sheet 1 took 200s: mean 150
        self.assertEqual(tr.snapshot()["eta_s"], 450.0)
        self.assertEqual(tr.snapshot()["mean_sheet_s"], {"takeoff": 150.0})

    def test_a_track_uses_its_own_timings_once_it_has_one(self):
        tr, clock, _ = self._tracker()
        for i in range(3):
            self._sheet(tr, "filed", i)
            clock.t += 300
        self._sheet(tr, "post_co", 0, n=2)        # the filed sheets took 300s each
        clock.t += 30
        self._sheet(tr, "post_co", 1, n=2)        # the owner's first took 30s (sweep reused)
        self.assertEqual(tr.snapshot()["eta_s"], 30.0)

    def test_an_untimed_stage_is_estimated_from_its_kind(self):
        """On Boyland the floors read in 15s each and the first sweep took
        131s: the takeoffs still to come are sweeps, not floor reads."""
        P = _present()
        clock = _Clock()
        tr = P.PassProgress(PID, clock=clock)
        tr.plan([("filed", [("sheet_scope", "M-106.00"), ("floors", "A-101.00"),
                            ("floors", "A-102.00"), ("takeoff", "A-101.00|M-101.00"),
                            ("takeoff", "A-102.00|M-102.00")])])
        cb = tr.callback("filed")
        for stage, sheet, secs in (("sheet_scope", "M-106.00", 120), ("floors", "A-101.00", 10),
                                   ("floors", "A-102.00", 10)):
            cb("sheet", {"stage": stage, "sheet": sheet, "i": 1, "n": 1})
            clock.t += secs
        cb("stage", {"stage": "seeding"})
        self.assertEqual(tr.snapshot()["eta_s"], 240.0)       # 2 takeoffs x 120s, not x 46.7s


# ── 3-4. the status route, while it runs and after it ends ────────────────
def _status():
    return asyncio.run(server.plan_glyph_pass_status(PID, current_user=ADMIN))


class _Route(unittest.TestCase):

    def setUp(self):
        server._GLYPH_PASS_RUNNING.discard(PID)
        getattr(server, "_GLYPH_PASS_PROGRESS", {}).pop(PID, None)
        self.db = AsyncFakeDB()

    tearDown = setUp

    def _server_pass(self, st, takeoff=_takeoff):
        """The real _plan_glyph_pass and run_pass on FILED + OWNER, with the
        OCR, R2, the database reads and the three writers stubbed. Returns
        {rows, health, areas}: what each writer was handed."""
        async def pages(pid):           # every file has an R2 key: open_page reaches the stub
            return [("filed", FILED), ("post_co", OWNER)], {
                f: {"r2_key": f"k/{f}"} for f in ("mech", "ar", "own", "plumb")}

        async def opening_schedules(pid, ids):
            return DOORS

        written = {}

        def writer(name):
            async def w(pid, rows):
                written[name] = len(rows)
                return len(rows)
            return w

        class _R2:
            def get_object(self, **k):
                return {"Body": type("B", (), {"read": lambda self: b""})()}

        self.db[server.PLAN_RECORDS].docs.extend(
            {"_id": f"s{i}", "project_id": PID, "record_type": "schedule", "page_id": "pm101",
             "sheet_number": s["sheet_number"], "tier": s["tier"],
             "payload": {"name": s["name"], "columns": s["columns"], "rows": s["rows"]}}
            for i, s in enumerate(SCHED))
        _fast(st, takeoff)
        st.enter_context(patch.object(server, "db", self.db))
        st.enter_context(patch.object(server, "_glyph_pages", pages))
        st.enter_context(patch.object(server, "_opening_schedules", opening_schedules))
        st.enter_context(patch("lib.plan_only.record_query", lambda pid, ids: {"project_id": pid,
                                                                              "record_type": "-"}))
        st.enter_context(patch("lib.plan_only.families", lambda recs: PLAN_ONLY))
        st.enter_context(patch.object(server, "_glyph_set_health", lambda *a, **k: []))
        st.enter_context(patch.object(server, "_r2_client", _R2()))
        st.enter_context(patch("lib.plan_page.PlanPage", lambda path, n: _Page()))
        for n, fn in (("rows", "_write_glyph_records"), ("health", "_write_set_health"),
                      ("areas", "_write_area_records")):
            st.enter_context(patch.object(server, fn, writer(n)))
        return written

    def _run_route(self, fake_pass):
        """POST .../plan-glyphs/run with the pass faked; waits for it to end."""
        async def go():
            out = await server.run_plan_glyph_pass(PID, current_user=ADMIN)
            for _ in range(500):
                if PID not in server._GLYPH_PASS_RUNNING:
                    break
                await asyncio.sleep(0.01)
            return out, await server.plan_glyph_pass_status(PID, current_user=ADMIN)
        with patch.object(server, "db", self.db), patch.object(server, "_plan_glyph_pass", fake_pass):
            return asyncio.run(go())


class TheStatusSaysWhereARunningPassIs(_Route):
    """The real _plan_glyph_pass and run_pass (OCR stubbed) on both tracks;
    the first floor's takeoff waits until the status has been read."""

    def test_while_running_and_after(self):
        _present()
        entered, release = threading.Event(), threading.Event()

        calls = []

        def takeoff(*a, **k):           # the 2nd: M-106.00 (sheet scope) was the 1st
            calls.append(1)
            if len(calls) == 2:
                entered.set()
                release.wait(20)
            return _takeoff(*a, **k)

        async def go():
            await server.run_plan_glyph_pass(PID, current_user=ADMIN)
            for _ in range(1000):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            during = await server.plan_glyph_pass_status(PID, current_user=ADMIN)
            release.set()
            for _ in range(1000):
                if PID not in server._GLYPH_PASS_RUNNING:
                    break
                await asyncio.sleep(0.01)
            return during, await server.plan_glyph_pass_status(PID, current_user=ADMIN)

        with ExitStack() as st:
            written = self._server_pass(st, takeoff)
            during, after = asyncio.run(go())

        for k in ("progress", "last_result"):
            self.assertIn(k, during)
        prog = during["progress"]
        self.assertIsNotNone(prog, "no progress while the pass runs")
        self.assertTrue(during["running"])
        self.assertEqual((prog["track"], prog["stage"], prog["current_sheet"]),
                         ("filed", "takeoff", "A-101.00|M-101.00"))
        self.assertEqual(prog["stage_sheet"], {"i": 1, "n": 2})
        # sheet_scope, 2 floors, 2 openings finished; 8 + 3 in all
        self.assertEqual((prog["sheets_done"], prog["sheets_total"]), (5, 11))
        self.assertEqual(prog["tracks"]["post_co"], {"status": "pending", "sheets_done": 0,
                                                     "sheets_total": 3})
        self.assertTrue(prog["started_at"])
        self.assertEqual(len(prog["timings"]), 5)
        self.assertIsNotNone(prog["eta_s"])
        self.assertEqual(during["last_result"]["result"], "running")

        self.assertFalse(after["running"])
        self.assertEqual(after["last_result"]["result"], "ok")
        self.assertEqual(after["last_result"]["summary"],
                         {"written": written["rows"], "set_health": written["health"],
                          "areas_written": written["areas"]})
        self.assertTrue(after["last_result"]["ended_at"])
        self.assertIsNotNone(after["last_result"]["duration_s"])
        self.assertEqual((after["progress"]["sheets_done"], after["progress"]["sheets_total"]), (11, 11))
        self.assertIsNone(after["progress"]["eta_s"])


class TheStatusSaysHowTheLastPassEnded(_Route):

    def test_ok_with_its_counts(self):
        _present()

        async def fake(pid, progress=None):
            return {"written": 459, "set_health": 3, "areas_written": 153, "tracks": {}}
        _out, st = self._run_route(fake)
        self.assertIn("last_result", st)
        r = st["last_result"]
        self.assertEqual((r["result"], r["summary"]),
                         ("ok", {"written": 459, "set_health": 3, "areas_written": 153}))
        self.assertTrue(r["started_at"] and r["ended_at"])
        self.assertNotIn("error", r)

    def test_failed_with_the_class_and_repr_of_an_empty_error(self):
        _present()
        import httpx

        async def fake(pid, progress=None):
            raise httpx.ReadTimeout("")
        _out, st = self._run_route(fake)
        self.assertIn("last_result", st)
        r = st["last_result"]
        self.assertEqual((r["result"], r["error_class"], r["error"]),
                         ("failed", "ReadTimeout", "ReadTimeout('')"))

    def test_a_reindex_during_the_pass_is_aborted_not_ok(self):
        """The real _plan_glyph_pass: a re-index arrives while it reads."""
        _present()
        db = self.db

        async def pages(pid):
            now = datetime.now(timezone.utc)
            db[server.PLAN_INDEX_JOBS].docs.append({
                "_id": "file-ar328", "project_id": PID, "file_name": "AR - 3.28.25.pdf",
                "status": "running", "enqueued_at": now, "started_at": now})
            return [], {}

        async def go():
            await server.run_plan_glyph_pass(PID, current_user=ADMIN)
            for _ in range(500):
                if PID not in server._GLYPH_PASS_RUNNING:
                    break
                await asyncio.sleep(0.01)
            return await server.plan_glyph_pass_status(PID, current_user=ADMIN)
        with patch.object(server, "db", db), patch.object(server, "_glyph_pages", pages):
            st = asyncio.run(go())
        self.assertIn("last_result", st)
        self.assertEqual(st["last_result"]["result"], "aborted: re-index during the pass")
        self.assertEqual([j["file_name"] for j in st["last_result"]["summary"]["reindex"]],
                         ["AR - 3.28.25.pdf"])

    def test_the_result_outlives_the_process_and_a_dead_pass_is_unknown(self):
        _present()

        async def fake(pid, progress=None):
            return {"written": 459, "set_health": 3, "areas_written": 153}
        self._run_route(fake)
        server._GLYPH_PASS_PROGRESS.pop(PID, None)          # a redeploy
        with patch.object(server, "db", self.db):
            st = _status()
        self.assertEqual((st["last_result"]["result"], st["last_result"]["source"]), ("ok", "database"))
        self.assertIsNone(st["progress"])
        # a pass that started and never ended (its process died mid-pass)
        doc = self.db["plan_glyph_pass_runs"].docs[0]
        doc.update(result="running", ended_at=None)
        with patch.object(server, "db", self.db):
            st = _status()
        self.assertEqual(st["last_result"]["result"], "unknown")
        self.assertIn("recorded no result", st["last_result"]["why"])

    def test_no_pass_ever_is_unknown_not_ok(self):
        _present()
        with patch.object(server, "db", self.db):
            st = _status()
        self.assertIn("last_result", st)
        self.assertEqual(st["last_result"]["result"], "unknown")


# ── 5. a raising callback never breaks the pass ───────────────────────────
class ARaisingCallbackDoesNotBreakThePass(unittest.TestCase):

    @staticmethod
    def _rows(out):
        return {t: (o["rows"], o["opening_rows"], o["areas"], o["summary"]) for t, o in out.items()}

    def test_the_rows_are_the_same_with_it_or_without_it(self):
        _present()

        def boom(kind, info):
            raise RuntimeError("progress is broken")
        with self.assertLogs("lib.plan_pass_progress", level="WARNING") as logs:
            raised = _both_tracks(lambda t: boom)
        plain = _both_tracks()
        self.assertEqual(self._rows(raised), self._rows(plain))
        self.assertTrue(any("progress callback failed" in r.getMessage() for r in logs.records))

    def test_a_tracker_whose_logger_raises_does_not_break_it(self):
        P = _present()

        class Bad(logging.Logger):
            def info(self, *a, **k):
                raise OSError("disk full")
        tr = P.PassProgress(PID, logger=Bad("bad"))
        out = _both_tracks(tr.callback)
        self.assertEqual(self._rows(out), self._rows(_both_tracks()))


class ABrokenTrackerDoesNotFailTheServerPass(_Route):

    def test_a_tracker_whose_logging_raises_everywhere(self):
        """The server calls the tracker itself (plan_tracks, server_stage,
        finish): every one of those logs, and none may raise into the pass."""
        P = _present()

        async def go():
            await server.run_plan_glyph_pass(PID, current_user=ADMIN)
            for _ in range(1000):
                if PID not in server._GLYPH_PASS_RUNNING:
                    break
                await asyncio.sleep(0.01)
        with ExitStack() as st:
            written = self._server_pass(st)
            st.enter_context(patch.object(P.log, "info", side_effect=OSError("disk full")))
            asyncio.run(go())
        self.assertEqual(server._GLYPH_PASS_PROGRESS[PID].last_result()["result"], "ok")
        self.assertEqual(set(written), {"rows", "health", "areas"})
        self.assertGreater(written["rows"], 0)


# ── 6. every key the status returned before ───────────────────────────────
class TheExistingStatusKeysAreUnchanged(unittest.TestCase):

    def test_the_old_keys_and_their_values_beside_the_new(self):
        _present()
        db = AsyncFakeDB()
        when = datetime(2026, 10, 27, 19, 21, 25, tzinfo=timezone.utc)
        db[server.PLAN_RECORDS].docs.extend(
            {"_id": f"r{i}", "project_id": PID, "record_type": "glyph", "created_at": when}
            for i in range(3))
        from lib.plan_set_health import COLLECTION
        db[COLLECTION].docs.append({"_id": "h1", "project_id": PID})
        server._GLYPH_PASS_RUNNING.discard(PID)
        with patch.object(server, "db", db):
            st = _status()
        self.assertEqual({k: st[k] for k in OLD_KEYS},
                         {"running": False, "last_written_at": when, "rows": 3,
                          "set_health_items": 1, "reindex_in_flight": []})
        self.assertEqual(set(st) - set(OLD_KEYS), {"progress", "last_result"})


if __name__ == "__main__":
    unittest.main()
