"""Where a running glyph pass is, and how the last one ended (2026-10-27).

The pass (server._plan_glyph_pass -> lib.plan_glyph_pass.run_pass) runs for
most of an hour. On 2026-10-27 the owner's-set track logged nothing for
seventeen minutes: its mechanical sweeps are the filed track's, reused
through `sweeps`, and the only line the per-floor work ever logged was the
sweep's own "SWEEP CROP". This module is what the pass reports instead:

  run_pass(..., progress=tracker.callback(track)) calls the callback at
  every step; the tracker keeps the state GET .../plan-glyphs/status
  returns and logs ONE INFO LINE PER SHEET (track, stage, sheet, i/n, how
  long it took, ETA).

STEPS. A SHEET STEP is one sheet's work in one stage, in run_pass's order:
  sheet_scope  a mechanical plan with no architectural partner, counted
               on its own sheet
  floors       an architectural plan's units and membership map
  openings     its door and window tags (lib.plan_openings)
  takeoff      the floor's mechanical symbols placed - the sweep is READ
               the first time a mechanical sheet is met and REUSED by every
               later track (each timing says which)
  plan_only    a plan-only family's plan (roof drains)
Every other stage is ONE step with no sheet - door (the door schedule
widths), seeding (stair seeding), areas, voids, and, in the server,
set_health and writing - and is timed, never counted in sheets_done/total.

ETA (seconds) = for each stage, the sheets remaining in it x the mean time
of that stage's finished sheets (the same track's when it has one, else any
track's, else its kind's - a takeoff is a sweep like sheet_scope, never a
15-second floor read - else every finished sheet's), less the time the
current sheet has already taken. None until a sheet finishes. The
non-sheet stages still to come are not in it.

NEVER BREAKS THE PASS: every public method here swallows its own errors
(logged), and run_pass's `tell` swallows a raising callback too. The
callback is called from the pass's worker thread (asyncio.to_thread) while
the status route reads from the event loop: all state is under one lock.
"""
from __future__ import annotations

import functools
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

#: The stages counted in sheets_done / sheets_total, in run_pass's order.
SHEET_STAGES = ("sheet_scope", "floors", "openings", "takeoff", "plan_only")
#: Sheet steps of one kind: a stage not yet timed is estimated from its kind
#: (a takeoff from the sheet_scope sweep that came first, never from the
#: floors' 15-second reads).
SWEEP_KIND = ("sheet_scope", "takeoff", "plan_only")
READ_KIND = ("floors", "openings")
#: What the result of an aborted pass says (server._plan_glyph_pass).
ABORTED = "aborted: re-index during the pass"
ETA_BASIS = ("sum over stages of (sheets remaining x mean seconds of that stage's finished "
             "sheets: this track's, else any track's, else its kind's - sweep: sheet_scope/"
             "takeoff/plan_only, read: floors/openings - else every sheet's), less the current "
             "sheet's elapsed; the non-sheet stages (door, seeding, areas, voids, set_health, "
             "writing) are not in it")


def tell(progress: Optional[Callable[[str, Dict[str, Any]], Any]], kind: str, **info: Any) -> None:
    """Call a pass's progress callback, if it has one. A callback that raises
    is logged and the pass goes on: progress never sinks a pass."""
    if progress is None:
        return
    try:
        progress(kind, info)
    except Exception as e:                          # never the pass's problem
        try:
            log.warning("glyph pass progress callback failed (%s): %r", kind, e)
        except Exception:
            pass


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:
            try:
                log.warning("glyph pass progress %s failed: %r", fn.__name__, e)
            except Exception:
                pass
            return None
    return wrapper


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def error_fields(e: BaseException) -> Dict[str, str]:
    """The class and repr() of an exception: str() of httpx's ReadTimeout is
    empty, so a failure said with str() alone says nothing."""
    return {"error_class": type(e).__name__, "error": repr(e)[:1000]}


class PassProgress:
    """One pass's progress (see the module docstring). `clock` (monotonic
    seconds) and `now` (a UTC datetime) are injectable for tests."""

    def __init__(self, project_id: str, *, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 logger: Optional[logging.Logger] = None):
        self.project_id = str(project_id)
        self._clock, self._now = clock, now
        self._log = logger or log
        self._lock = threading.Lock()
        self.started_at = now()
        self._t0 = clock()
        self.ended_at: Optional[datetime] = None
        self._duration: Optional[float] = None
        self.result: Optional[str] = None
        self.error: Optional[Dict[str, str]] = None
        self.summary: Dict[str, Any] = {}
        self._order: List[str] = []                       # tracks, in run order
        self._planned: Dict[str, List[Tuple[str, str]]] = {}
        self._done: Dict[str, int] = {}                   # track -> sheets finished
        self._track_state: Dict[str, str] = {}            # pending / running / done
        self.track: Optional[str] = None
        self.stage: Optional[str] = None
        self.current_sheet: Optional[str] = None
        self._step: Optional[Dict[str, Any]] = None       # the open step
        self.timings: List[Dict[str, Any]] = []           # finished sheet steps
        self.stages: List[Dict[str, Any]] = []            # finished non-sheet stages

    # ── what the pass will do ────────────────────────────────────────────
    @_safe
    def plan(self, tracks: Sequence[Tuple[str, Sequence[Tuple[str, str]]]]) -> None:
        """[(track, [(stage, sheet)])] - every track's sheet steps, before the
        pass starts, so overall sheets_total is known from the first sheet."""
        with self._lock:
            for t, steps in tracks:
                self._set_plan(t, steps)

    @_safe
    def plan_tracks(self, by_track: Sequence[Tuple[str, Sequence[Dict[str, Any]]]],
                    schedules: Sequence[Dict[str, Any]] = (),
                    plan_only: Optional[Dict[str, Dict[str, Any]]] = None,
                    opening_schedules: Sequence[Dict[str, Any]] = ()) -> None:
        """plan() from the pages the server hands each track's run_pass
        (plan_glyph_pass.sheet_steps)."""
        from lib.plan_glyph_pass import sheet_steps
        self.plan([(t, sheet_steps(pages, schedules, plan_only, opening_schedules))
                   for t, pages in by_track])

    def _set_plan(self, track: str, steps) -> None:
        if track not in self._order:
            self._order.append(track)
        self._planned[track] = [(str(s), str(sh)) for s, sh in steps]
        self._done.setdefault(track, 0)
        self._track_state.setdefault(track, "pending")

    def callback(self, track: str) -> Callable[[str, Dict[str, Any]], None]:
        """The run_pass callback for one track: progress(kind, info)."""
        def cb(kind: str, info: Dict[str, Any]) -> None:
            self.event(track, kind, info)
        return cb

    # ── events ───────────────────────────────────────────────────────────
    @_safe
    def event(self, track: Optional[str], kind: str, info: Optional[Dict[str, Any]] = None) -> None:
        """kind: "plan" {steps} | "stage" {stage} | "sheet" {stage, sheet,
        i, n, sweep} | "done" {}. Any event ends the step that was open."""
        info = info or {}
        lines: List[str] = []
        with self._lock:
            if kind == "plan":
                self._set_plan(track, info.get("steps") or [])
                self._track_state[track] = "running"
                self.track = track
                return
            lines += self._close()
            if track is not None:
                if track not in self._order:
                    self._set_plan(track, [])
                self._track_state[track] = "running"
            self.track = track                  # None: a server stage, after every track
            if kind == "done":
                if track is not None:
                    self._track_state[track] = "done"
                self.stage, self.current_sheet = None, None
            elif kind in ("stage", "sheet"):
                stage = str(info.get("stage"))
                self.stage = stage
                self.current_sheet = info.get("sheet") if kind == "sheet" else None
                self._step = {"track": track, "stage": stage, "kind": kind,
                              "sheet": info.get("sheet"), "i": info.get("i"),
                              "n": info.get("n"), "sweep": info.get("sweep"),
                              "t": self._clock()}
                if kind == "stage":
                    lines.append(f"glyph pass {self.project_id}: {track or 'pass'} stage {stage} began")
        for ln in lines:
            self._log.info("%s", ln)

    def server_stage(self, stage: str) -> None:
        """A server-side stage (set_health, writing) - no track."""
        self.event(None, "stage", {"stage": stage})

    def _close(self) -> List[str]:
        """End the open step (lock held); the log line it says."""
        st, self._step = self._step, None
        if not st:
            return []
        secs = round(self._clock() - st["t"], 1)
        if st["kind"] == "stage":
            self.stages.append({"track": st["track"], "stage": st["stage"], "seconds": secs})
            return [f"glyph pass {self.project_id}: {st['track'] or 'pass'} stage {st['stage']} "
                    f"took {secs:.0f}s"]
        self.timings.append({"track": st["track"], "stage": st["stage"], "sheet": st["sheet"],
                             "seconds": secs, "sweep": st["sweep"]})
        if st["track"] in self._done and st["stage"] in SHEET_STAGES:
            self._done[st["track"]] += 1
        done, total = self._totals()
        eta = self._eta()
        sweep = f", sweep {st['sweep']}" if st["sweep"] else ""
        return [f"glyph pass {self.project_id}: track {st['track']} {st['stage']} {st['sheet']} "
                f"{st['i']}/{st['n']} took {secs:.0f}s{sweep} (sheets {done}/{total}); "
                f"ETA {self._fmt(eta)}"]

    # ── the end ──────────────────────────────────────────────────────────
    @_safe
    def finish(self, result: str, *, error: Optional[BaseException] = None,
               summary: Optional[Dict[str, Any]] = None) -> None:
        """ok / failed (with the error's class and repr) / ABORTED."""
        with self._lock:
            lines = self._close()
            self.result = result
            self.error = error_fields(error) if error is not None else None
            self.summary = dict(summary or {})
            self.ended_at = self._now()
            self._duration = round(self._clock() - self._t0, 1)
            self.stage, self.current_sheet = None, None
        for ln in lines:
            self._log.info("%s", ln)
        self._log.info("glyph pass %s ended: %s in %.0fs%s", self.project_id, result,
                       self._duration or 0, f" - {self.error['error']}" if self.error else "")

    @property
    def finished(self) -> bool:
        return self.result is not None

    # ── reading it ───────────────────────────────────────────────────────
    def _totals(self) -> Tuple[int, int]:
        return (sum(self._done.values()),
                sum(sum(1 for s, _ in v if s in SHEET_STAGES) for v in self._planned.values()))

    def _eta(self) -> Optional[float]:
        timed = [t for t in self.timings if t["stage"] in SHEET_STAGES]
        if not timed:
            return None
        overall = sum(t["seconds"] for t in timed) / len(timed)

        def mean(track, stage):
            kind = SWEEP_KIND if stage in SWEEP_KIND else READ_KIND
            for pick in (lambda t: t["track"] == track and t["stage"] == stage,
                         lambda t: t["stage"] == stage,
                         lambda t: t["stage"] in kind):
                xs = [t["seconds"] for t in timed if pick(t)]
                if xs:
                    return sum(xs) / len(xs)
            return overall
        eta = 0.0
        for track in self._order:
            planned = [s for s, _ in self._planned.get(track, []) if s in SHEET_STAGES]
            finished: Dict[str, int] = {}
            for t in timed:
                if t["track"] == track:
                    finished[t["stage"]] = finished.get(t["stage"], 0) + 1
            for stage in dict.fromkeys(planned):
                left = max(0, planned.count(stage) - finished.get(stage, 0))
                eta += left * mean(track, stage)
        st = self._step
        if st and st["kind"] == "sheet" and st["stage"] in SHEET_STAGES:
            eta -= min(self._clock() - st["t"], mean(st["track"], st["stage"]))
        return round(max(eta, 0.0), 1)

    @staticmethod
    def _fmt(eta: Optional[float]) -> str:
        if eta is None:
            return "unknown until a sheet finishes"
        return f"{eta / 60:.0f} min" if eta >= 90 else f"{eta:.0f}s"

    @_safe
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            done, total = self._totals()
            eta = None if self.finished else self._eta()
            elapsed = (self._duration if self._duration is not None
                       else round(self._clock() - self._t0, 1))
            st = self._step
            tracks = {}
            for t in self._order:
                tracks[t] = {"status": self._track_state.get(t),
                             "sheets_done": self._done.get(t, 0),
                             "sheets_total": sum(1 for s, _ in self._planned.get(t, [])
                                                 if s in SHEET_STAGES)}
            means: Dict[str, List[float]] = {}
            for t in self.timings:
                if t["stage"] in SHEET_STAGES:
                    means.setdefault(t["stage"], []).append(t["seconds"])
            return {
                "running": not self.finished,
                "track": self.track, "stage": self.stage, "current_sheet": self.current_sheet,
                "stage_sheet": ({"i": st["i"], "n": st["n"]} if st and st["kind"] == "sheet" else None),
                "current_sheet_seconds": (round(self._clock() - st["t"], 1)
                                          if st and not self.finished else None),
                "started_at": _iso(self.started_at), "elapsed_s": elapsed,
                "sheets_done": done, "sheets_total": total, "tracks": tracks,
                "eta_s": eta,
                "eta_at": _iso(self._now() + timedelta(seconds=eta)) if eta is not None else None,
                "eta_basis": ETA_BASIS,
                "mean_sheet_s": {k: round(sum(v) / len(v), 1) for k, v in means.items()},
                "timings": list(self.timings), "stages": list(self.stages),
            }

    @_safe
    def last_result(self) -> Dict[str, Any]:
        """How the pass ended, as GET .../plan-glyphs/status says it (and the
        server keeps it): result is "running" until it has ended."""
        with self._lock:
            out = {"result": self.result or "running", "started_at": _iso(self.started_at),
                   "ended_at": _iso(self.ended_at), "duration_s": self._duration,
                   "summary": dict(self.summary)}
            if self.error:
                out.update(self.error)
            return out


def reported_result(tracker: Optional[PassProgress],
                    recorded: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The last pass's result as the status route says it: this process's
    own pass when it ran one, else the one the database kept
    (server._record_glyph_pass_result). A pass recorded as running that this
    process is not running ended with its process - a redeploy or a crash -
    so its result is "unknown", never ok."""
    if tracker is not None:
        return dict(tracker.last_result() or {"result": "unknown"}, source="this process")
    if not recorded:
        return {"result": "unknown", "source": None,
                "why": "no pass has recorded a result here (results are kept from 2026-10-27)"}
    out = {k: v for k, v in recorded.items() if k not in ("_id", "project_id")}
    out["source"] = "database"
    if out.get("result") in (None, "running"):
        out["result"] = "unknown"
        out["why"] = (f"the pass started at {out.get('started_at')} recorded no result: the "
                      f"server process that ran it ended (a redeploy or a crash)")
    return out
