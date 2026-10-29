"""One project's equipment placements, end to end: the rows plan_emit writes.

    run_pass(pages, open_page, schedules) -> {"rows", "summary"}

  pages      the project's CURRENT pages (a superseded sheet is dropped by the
             caller), each with its citation fields and sheet_number/title
  open_page  page -> lib.plan_page.PlanPage
  schedules  schedule records on mechanical sheets (plan_records rows)

Pure of the database and of R2, so the same code runs in the server and on
a workstation over the source PDFs - which is how a pass is reviewed by
render before it is ever written.

NOTHING IS GUESSED, in order:
  1. sheets are paired by number (plan_derive.pair_plan_sheets); a plan
     with no partner is one refusal row;
  2. a floor's units come from its own sheet (plan_derive.unit_tags); none
     derivable is one refusal row for the floor;
  3. the door width comes from a door schedule (plan_derive.widest_door_in);
     none means no doorway gap is closed and the space map falls back;
  4. an equipment family is a schedule with an identifier column, read at
     its BEST tier (plan_records.TIER_ORDER): a family whose best reading
     has no tag column is not run on a lower one.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from lib import plan_derive as derive
from lib import plan_emit as emit
from lib import plan_symbols as psym
from lib.plan_records import tier_rank

log = logging.getLogger(__name__)


def families(schedules: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """name -> {"tags", "corroborations", "tier", "sheet"}, best tier first.

    One schedule is often read twice (an OCR grid and a vision read). The
    best-tier reading decides; a name whose best reading has no identifier
    column is reported as skipped, not filled from a worse one - on 588
    Boyland the diffuser schedule's vision read offers A1/A2, the same
    strings the light-and-air table uses for rooms."""
    best: Dict[str, Dict[str, Any]] = {}
    for s in schedules:
        name = (s.get("name") or "").strip().upper()
        if not name:
            continue
        cur = best.get(name)
        if cur is None or tier_rank(s.get("tier")) < tier_rank(cur.get("tier")):
            best[name] = s
    out = {}
    for name, s in sorted(best.items()):
        tags, corr = psym.closed_set_from_schedule(s.get("columns") or [],
                                                   s.get("rows") or [])
        out[name] = {"tags": tags, "corroborations": corr, "tier": s.get("tier"),
                     "sheet": s.get("sheet_number") or s.get("sheet")}
    return out


#: The units a sheet counted at sheet scope carries: none, read - an empty
#: multi_level is an affirmative "no unit continues anywhere from here",
#: so the floor is not "unknown" to the gate; there is simply no unit scope.
SHEET_SCOPE_UNITS = {"tags": [], "method": "sheet_scope", "zero_units": False,
                     "multi_level": {}}


def run_pass(pages: Sequence[Dict[str, Any]], open_page: Callable[[Dict[str, Any]], Any],
             schedules: Sequence[Dict[str, Any]],
             door_pages: Sequence[Dict[str, Any]] = (), *, track: str = "filed",
             sweeps: Optional[Dict[Any, Any]] = None,
             plan_only: Optional[Dict[str, Dict[str, Any]]] = None,
             opening_schedules: Sequence[Dict[str, Any]] = (),
             set_answers: Optional[Dict[str, str]] = None,
             progress: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
             scale_sheets: Optional[Dict[Any, Any]] = None) -> Dict[str, Any]:
    """Every glyph row for the project's `track`, and what was done and
    refused.

    ONE PASS PER DRAWING TRACK (ruling 2026-10-24): the caller hands each
    track's own current pages (server._glyph_track_pages), and every row this
    pass writes says `track`. A mechanical sheet belongs to no track, so its
    sweep is read once and shared through `sweeps` (page id -> reads); each
    located row also carries `mech_count`, the labels that sweep locates for
    its family before any architectural sheet is read.

    `plan_only` is lib.plan_only.families() of the set's records: the
    plan-only families the set allows (a detail or note names the object).
    Each is located on its own plans in this track's pages (run_plan_only).

    DOORS AND WINDOWS (lib.plan_openings, 2026-10-26): the tags the
    architectural plans print, read against the door/window schedules
    (`opening_schedules`) on the SAME floors - their units, membership maps,
    stair links and voids - and returned apart, in "opening_rows", so the
    equipment rows are exactly what they were.

    `set_answers` are the stored answers to the project's drawing-set
    questions (lib.plan_set_questions, ruling 21): {question id: include |
    exclude}. The questions this track raises come back in "set_questions".

    PROGRESS (2026-10-27): `progress`, when given, is called at every step -
    progress(kind, info), kind "plan" / "stage" / "sheet" / "done" (lib.
    plan_pass_progress, whose tracker the server hands in). It is called
    from this function's thread; one that raises is logged and ignored
    (plan_pass_progress.tell). It reads nothing the pass computes with, so
    the rows are the same with it or without it.

    MECHANICAL SCALES (ruling 5, 2026-10-28): every pair's mechanical plan's
    scale - its own, or borrowed from its architectural partner (mech_scale)
    - is in the summary's "mech_scales". No row reads it. `scale_sheets`
    (page id -> plan_scale.Sheet) lets a caller share the mechanical reads
    across tracks, as `sweeps` does."""
    from lib import plan_openings as popen
    from lib.plan_pass_progress import tell
    from lib.plan_sheet import load_sheet
    from lib.plan_space import build_space
    from lib.plan_takeoff import Units, located_labels, run_takeoff, sweep

    rows: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {"track": track, "pairs": [], "refused_sheets": [],
                               "families": {}, "skipped_families": [], "door": None,
                               "floors": [], "mech_counts": {}}
    sweeps = {} if sweeps is None else sweeps
    scale_sheets = {} if scale_sheets is None else scale_sheets

    def reads_of(mech_p, mech_pg, segs):
        k = mech_p.get("page_id") or (mech_p.get("file_id"), mech_p.get("page_number"))
        if k not in sweeps:
            sweeps[k] = sweep(mech_pg, segs)
        return sweeps[k]

    def mech_count(mech_p, reads, name, fam):
        n = len(located_labels(reads, fam["tags"], fam["corroborations"]))
        summary["mech_counts"][f"{mech_p.get('sheet_number')}|{name}"] = n
        return n

    paired = derive.pair_plan_sheets(pages)
    if progress is not None:
        tell(progress, "plan", steps=sheet_steps(pages, schedules, plan_only, opening_schedules,
                                                 paired=paired))
    for page, why, role in paired["refused"]:
        rows += emit.refusal_rows([(page, why, role)])
        summary["refused_sheets"].append([page.get("sheet_number"), why, role])

    door = {"inches": None, "doors": {}, "why": "no door schedule in the set"}
    tell(progress, "stage", stage="door")
    for p in door_pages:
        got = derive.widest_door_in(open_page(p).directed_words)
        if got["inches"] and (door["inches"] is None or got["inches"] > door["inches"]):
            door = dict(got, sheet=p.get("sheet_number"))
    summary["door"] = door

    fams = families(schedules)
    run_fams = {n: f for n, f in fams.items() if f["tags"]}
    summary["families"] = {n: f["tags"] for n, f in run_fams.items()}
    summary["skipped_families"] = sorted(n for n, f in fams.items() if not f["tags"])
    ofams = popen.families(opening_schedules)
    open_run = any(f["tags"] for f in ofams.values())

    def sheet_scope(mech_p, arch_p, why):
        """COUNT WHAT CANNOT BE PLACED (operator ruling 2026-10-07). The
        symbols on a mechanical sheet are located and named on that sheet
        alone; placement is refused, with `why`. M-106.00 (no architectural
        partner) and M-104.00 (whose partner names no units) are counted
        this way - a floor total binds, and no unit scope does."""
        m_sheet = mech_p.get("sheet_number")
        a_sheet = arch_p.get("sheet_number") if arch_p else None
        floor = {"arch": a_sheet, "mech": m_sheet, "units": dict(SHEET_SCOPE_UNITS),
                 "method": "sheet_scope", "why": why, "families": {}}
        summary["floors"].append(floor)
        if not run_fams:
            rows.append(emit.sheet_refusal(
                mech_p, "no equipment schedule with an identifier column",
                pass_key=f"{a_sheet}|{m_sheet}", role=derive.ROLE_MECHANICAL))
            return
        mech_pg = open_page(mech_p)
        reads = reads_of(mech_p, mech_pg, load_sheet(mech_pg)["segs"])
        for name, fam in run_fams.items():
            key = f"{a_sheet}|{m_sheet}|{name}"
            try:
                res = run_takeoff(None, mech_pg, fam["tags"], fam["corroborations"],
                                  [], door["inches"], reads=reads,
                                  unplaced_reason=f"refused: {why}: counted at "
                                                  f"sheet scope, not placed")
            except Exception as e:                  # one sheet never sinks the pass
                log.exception("glyph pass %s failed: %r", key, e)
                res = {"refused": f"takeoff failed: {type(e).__name__}"}
            got = emit.glyph_rows(res, mech=mech_p, arch=arch_p, family=name,
                                  pass_key=key, units=SHEET_SCOPE_UNITS,
                                  widest_door=door,
                                  mech_count=mech_count(mech_p, reads, name, fam))
            rows.extend(got)
            floor["families"][name] = {"rows": len(got), "total": res.get("total"),
                                       "refused": res.get("refused"),
                                       "labels_by_tag": res.get("labels_by_tag")}

    unpaired = paired.get("unpaired_mech") or []
    for i, mech_p in enumerate(unpaired, 1):
        m_sheet = mech_p.get("sheet_number")
        tell(progress, "sheet", stage="sheet_scope", sheet=m_sheet, i=i, n=len(unpaired),
             sweep=_sweep_state(mech_p, sweeps) if run_fams else None)
        seq = (derive.PLAN_SHEET.match(str(m_sheet or "").upper()) or [None, None, "?"])[2]
        sheet_scope(mech_p, None, f"{m_sheet} has no architectural partner A-{seq}")

    # EVERY FLOOR'S UNITS AND MEMBERSHIP MAP FIRST: a stair on one floor may
    # carry its unit to another (rule (b), plan_derive.stair_target), so no
    # floor is placed before every floor has been read.
    floors_in: List[Dict[str, Any]] = []
    for i, (arch_p, mech_p) in enumerate(paired["pairs"], 1):
        f: Dict[str, Any] = {"arch_p": arch_p, "mech_p": mech_p,
                             "a_sheet": arch_p.get("sheet_number"),
                             "m_sheet": mech_p.get("sheet_number")}
        tell(progress, "sheet", stage="floors", sheet=f["a_sheet"], i=i,
             n=len(paired["pairs"]))
        floors_in.append(f)
        summary["pairs"].append([f["a_sheet"], f["m_sheet"]])
        if not run_fams and not open_run:
            continue
        arch_pg = open_page(arch_p)
        f["data"] = load_sheet(arch_pg)
        f["units"] = derive.unit_tags(f["data"]["words"], f["data"]["corners"])
        if f["units"]["tags"] is None:
            continue
        # one membership map per floor, whatever the family
        f["space"] = build_space(arch_pg, f["units"]["tags"], door["inches"], f["data"])
        # WHICH UNITS CONTINUE ON ANOTHER SHEET, read by the membership map
        # the placements use (plan_derive.multi_level_units). Written on
        # every row so the gate can refuse a whole-apartment count it cannot
        # complete - and so a row that predates the reading says nothing.
        member = Units(f["space"]["units"], f["space"]["lo"], f["space"]["cell_pt"],
                       f["space"]["refused"], f["space"], f["space"]["tags"])
        f["member"] = member
        f["units"] = dict(f["units"], multi_level=derive.multi_level_units(
            arch_pg.directed_words, member.at, f["units"]["tags"]))
        f["stairs"] = derive.unit_stairs(arch_pg.directed_words, member.at,
                                         f["units"]["tags"])
    tell(progress, "stage", stage="seeding")
    summary["stair_seeds"] = seed_from_stairs(floors_in, open_page, door["inches"])
    # AREAS (lib.plan_areas, ruling 2026-10-26): every floor's apartment and
    # room areas, checked against what the plan prints - BEFORE a void joins
    # a unit (an open-to-below bay is no floor area of the unit beside it).
    # (only where the equipment pass prepared the floors, as before doors and
    # windows: a set with door schedules and no equipment one writes no areas)
    tell(progress, "stage", stage="areas")
    areas, summary["areas"] = floor_area_rows(floors_in if run_fams else [], open_page,
                                              track=track)
    # WALLS (lib.plan_walls, ruling 62, 2026-10-28): every architectural plan
    # of this track - each paired floor, and each plan the pairing refused for
    # want of a mechanical partner - its walls by type, refused where the scale
    # does not verify. Like areas, read BEFORE a void joins a unit, and on
    # every floor whether or not the set has an equipment schedule: a wall
    # needs none. A floor with no membership map gets no apartments.
    tell(progress, "stage", stage="walls")
    walls, summary["walls"] = floor_wall_rows(
        floors_in, open_page, track=track, widest_door_in=door["inches"],
        others=[p for p, _why, role in paired["refused"] if role == derive.ROLE_ARCHITECTURAL])
    tell(progress, "stage", stage="voids")
    summary["voids"] = assign_voids(floors_in)
    opening = popen.run_openings(
        floors_in, open_page, ofams, track=track, widest_door=door,
        refused=[(p, why) for p, why, role in paired["refused"]
                 if role == derive.ROLE_ARCHITECTURAL],
        answers=set_answers, progress=progress)
    summary["openings"] = opening["summary"]

    summary["mech_scales"] = []
    for i, f in enumerate(floors_in, 1):
        arch_p, mech_p, a_sheet, m_sheet = f["arch_p"], f["mech_p"], f["a_sheet"], f["m_sheet"]
        tell(progress, "sheet", stage="takeoff", sheet=f"{a_sheet}|{m_sheet}", i=i,
             n=len(floors_in), sweep=_sweep_state(mech_p, sweeps) if run_fams else None)
        if run_fams and "data" in f:
            summary["mech_scales"].append(mech_scale(f, open_page, scale_sheets))
        if not run_fams:
            rows.append(emit.sheet_refusal(
                mech_p, "no equipment schedule with an identifier column",
                pass_key=f"{a_sheet}|{m_sheet}", role=derive.ROLE_MECHANICAL))
            continue
        units = f["units"]
        if units["tags"] is None:
            sheet_scope(mech_p, arch_p, f"{a_sheet}: {units['why']}")
            continue
        arch_pg, mech_pg = open_page(arch_p), open_page(mech_p)
        space = f["space"]
        floor = {"arch": a_sheet, "mech": m_sheet, "units": units, "families": {},
                 "method": space.get("method"),
                 "fallback_reason": space.get("fallback_reason")}
        if units.get("seeded"):
            floor["seeded"] = units["seeded"]
        if units.get("linked"):
            floor["linked"] = units["linked"]
        if units.get("voids"):
            floor["voids"] = units["voids"]
        summary["floors"].append(floor)
        mech_sheet = f.get("mech_data") or load_sheet(mech_pg)
        reads = reads_of(mech_p, mech_pg, mech_sheet["segs"])
        for name, fam in run_fams.items():
            key = f"{a_sheet}|{m_sheet}|{name}"
            try:
                res = run_takeoff(arch_pg, mech_pg, fam["tags"], fam["corroborations"],
                                  units["tags"], door["inches"], reads=reads,
                                  space=space)
            except Exception as e:                  # one floor never sinks the pass
                log.exception("glyph pass %s failed: %r", key, e)
                res = {"refused": f"takeoff failed: {type(e).__name__}"}
            got = emit.glyph_rows(res, mech=mech_p, arch=arch_p, family=name,
                                  pass_key=key, units=units, widest_door=door,
                                  mech_count=mech_count(mech_p, reads, name, fam))
            rows += got
            floor["families"][name] = {
                "rows": len(got), "total": res.get("total"),
                "per_unit": res.get("per_unit"), "unavailable": res.get("unavailable"),
                "method": res.get("method"), "fallback_reason": res.get("fallback_reason"),
                "refused": res.get("refused"),
                "labels_by_tag": res.get("labels_by_tag")}
    summary["plan_only"] = {}
    n_plan_only = sum(1 for p in pages for name in (plan_only or {})
                      if _is_family_plan(p, name))
    for name, fam in sorted((plan_only or {}).items()):
        got, note = run_plan_only(name, fam, pages, open_page, door, progress=progress,
                                  steps_before=sum(len(n["plans"])
                                                   for n in summary["plan_only"].values()),
                                  steps=n_plan_only)
        rows += got
        summary["plan_only"][name] = note
    for i, r in enumerate(rows):
        r["ordinal"] = i
        r.setdefault("payload", {})["track"] = track
    summary["rows"] = len(rows)
    tell(progress, "done")
    return {"rows": rows, "summary": summary, "areas": areas, "walls": walls,
            "opening_rows": opening["rows"], "opening_health": opening["health"],
            "set_questions": opening.get("questions") or []}


def sheet_steps(pages: Sequence[Dict[str, Any]], schedules: Sequence[Dict[str, Any]] = (),
                plan_only: Optional[Dict[str, Dict[str, Any]]] = None,
                opening_schedules: Sequence[Dict[str, Any]] = (), *,
                paired: Optional[Dict[str, Any]] = None) -> List[tuple]:
    """[(stage, sheet)] - every sheet step run_pass takes on `pages`, in its
    order (lib.plan_pass_progress): each unpaired mechanical plan
    (sheet_scope), each pair's floor read (floors), its doors and windows
    when a door/window schedule has tags (openings), its placement
    (takeoff), and each plan-only family's plans (plan_only). From the page
    list alone, so the server counts every track's sheets before it runs."""
    from lib import plan_openings as popen

    paired = paired if paired is not None else derive.pair_plan_sheets(pages)
    pairs = paired.get("pairs") or []
    steps: List[tuple] = [("sheet_scope", m.get("sheet_number"))
                          for m in paired.get("unpaired_mech") or []]
    steps += [("floors", a.get("sheet_number")) for a, _m in pairs]
    if any(f["tags"] for f in popen.families(opening_schedules).values()):
        steps += [("openings", a.get("sheet_number")) for a, _m in pairs]
    steps += [("takeoff", f"{a.get('sheet_number')}|{m.get('sheet_number')}") for a, m in pairs]
    for name in sorted(plan_only or {}):
        steps += [(ROLE_PLAN_ONLY, f"{p.get('sheet_number')} ({name})")
                  for p in pages if _is_family_plan(p, name)]
    return steps


def _is_family_plan(page: Dict[str, Any], name: str) -> bool:
    from lib import plan_only as _po
    return _po.is_family_plan(page, name)


def _sweep_state(mech_p: Dict[str, Any], sweeps: Dict[Any, Any]) -> str:
    """"reused" when an earlier track already swept this mechanical sheet
    (run_pass's reads_of key), else "read"."""
    k = mech_p.get("page_id") or (mech_p.get("file_id"), mech_p.get("page_number"))
    return "reused" if k in sweeps else "read"


def floor_area_rows(floors: List[Dict[str, Any]], open_page: Callable[[Dict[str, Any]], Any], *,
                    track: str = "filed") -> "tuple[List[Dict[str, Any]], List[str]]":
    """(area rows, a line per floor) - lib.plan_areas on every floor whose
    membership map was built. One floor that fails never sinks the pass: it
    is said, and writes no row."""
    from lib import plan_areas

    rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    for f in floors:
        sp = f.get("space")
        if not sp or (f.get("units") or {}).get("tags") is None:
            continue
        try:
            res = plan_areas.floor_areas(open_page(f["arch_p"]), sp)
        except Exception as e:                      # one floor never sinks the pass
            log.exception("area check %s failed: %r", f.get("a_sheet"), e)
            notes.append(f"{f.get('a_sheet')}: area check failed ({type(e).__name__}) - no area rows")
            continue
        got = plan_areas.area_rows(res, f["arch_p"], track=track)
        rows += got
        tally = {}
        for r in got:
            tally[r["status"]] = tally.get(r["status"], 0) + 1
        notes.append(f"{f.get('a_sheet')}: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    for n in notes:
        log.info("glyph pass areas: %s", n)
    return rows, notes


def floor_wall_rows(floors: List[Dict[str, Any]], open_page: Callable[[Dict[str, Any]], Any], *,
                    track: str = "filed", widest_door_in: Optional[float] = None,
                    others: Sequence[Dict[str, Any]] = ()) -> "tuple[List[Dict[str, Any]], List[str]]":
    """(wall rows, a line per plan) - lib.plan_walls on every floor's
    architectural plan (its membership map, when the pass built one, gives
    the apartments) and on each of `others` (plans the pairing refused: no
    apartments). Each plan once. One plan that fails never sinks the pass: it
    is said, and writes no row."""
    from lib import plan_walls

    rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    seen = set()
    todo = [(f["arch_p"], f.get("space")) for f in floors] + [(p, None) for p in others]
    for page, space in todo:
        key = page.get("page_id") or (page.get("file_id"), page.get("page_number"))
        if key in seen:
            continue
        seen.add(key)
        sheet = page.get("sheet_number")
        try:
            res = plan_walls.floor_walls(open_page(page), space=space, widest_door_in=widest_door_in)
        except Exception as e:                      # one plan never sinks the pass
            log.exception("walls %s failed: %r", sheet, e)
            notes.append(f"{sheet}: walls failed ({type(e).__name__}) - no wall rows")
            continue
        got = plan_walls.wall_rows(res, page, track=track)
        rows += got
        kinds: Dict[str, int] = {}
        for r in got:
            k = r["payload"]["kind"] + ("" if r["payload"]["kind"] != plan_walls.WALL else f":{r['status']}")
            kinds[k] = kinds.get(k, 0) + 1
        notes.append(f"{sheet}: " + (", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "no rows"))
    for n in notes:
        log.info("glyph pass walls (%s): %s", track, n)
    return rows, notes


#: A refused plan-only sheet blocks its own family, never another's total:
#: it can carry no mechanical symbol (plan_search._blocking).
ROLE_PLAN_ONLY = "plan_only"


def run_plan_only(name: str, fam: Dict[str, Any], pages: Sequence[Dict[str, Any]],
                  open_page: Callable[[Dict[str, Any]], Any], door: Dict[str, Any], *,
                  progress: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
                  steps_before: int = 0, steps: Optional[int] = None):
    """(rows, summary) for one plan-only family (lib.plan_only, ruling
    2026-10-26) on every plan of it among `pages`.

    AT SHEET SCOPE: the labels its tags snap to are located on the plan and
    the symbol beside each is found, as a mechanical sheet's are
    (plan_takeoff.run_takeoff with no architectural page); nothing is placed.
    The plain sweep comes first - on a rotated page it is the frame check
    (plan_takeoff.sweep) - then the INK-ONLY sweep (plan_takeoff.ink_only:
    the SLOPE DN arrows crossing both RD-1 labels on P-206.00 are a lighter
    pen). A label counts when either sweep reads it EXACTLY
    (plan_only.exact_label_reads), and the symbol beside it is never drawn
    in the lighter pen. Neither sweep joins the mechanical sweeps the
    set-health read scans: that read is of mechanical plans."""
    from lib import plan_only as _po
    from lib.plan_pass_progress import tell
    from lib.plan_sheet import load_sheet
    from lib.plan_takeoff import located_labels, run_takeoff, sweep

    rows: List[Dict[str, Any]] = []
    note: Dict[str, Any] = {"plans": [], "named_by": fam.get("named_by"),
                            "tags": fam.get("tags"), "located": {}}
    for p in pages:
        if not _po.is_family_plan(p, name):
            continue
        sheet = p.get("sheet_number")
        note["plans"].append(sheet)
        tell(progress, "sheet", stage=ROLE_PLAN_ONLY, sheet=f"{sheet} ({name})",
             i=steps_before + len(note["plans"]), n=steps, sweep="read")
        lab = _po.label([sheet])
        key = f"plan-only|{sheet}|{name}"
        n = None
        try:
            pg = open_page(p)
            segs = load_sheet(pg)["segs"]
            plain = sweep(pg, segs)                 # and, on a rotated page, its frame
            ink = sweep(pg, segs, ink_below=_po.INK_BELOW)
            reads = _po.exact_label_reads(plain + ink, fam["tags"])
            n = len(located_labels(reads, fam["tags"], {}))
            res = run_takeoff(None, pg, fam["tags"], {}, [], door.get("inches"), reads=reads,
                              unplaced_reason=f"refused: plan-only family, {lab}: "
                                              f"counted at sheet scope, not placed",
                              ink_below=_po.INK_BELOW)
        except Exception as e:                      # one plan never sinks the pass
            log.exception("glyph pass %s failed: %r", key, e)
            res = {"refused": f"plan-only takeoff failed: {type(e).__name__}: {str(e)[:160]}"}
        got = emit.glyph_rows(res, mech=p, arch=None, family=name, pass_key=key,
                              units=SHEET_SCOPE_UNITS, widest_door=door, mech_count=n)
        for r in got:
            pl = r.setdefault("payload", {})
            if r.get("glyph_status") == "unsupported_unit":
                pl["role"] = ROLE_PLAN_ONLY
            pl["plan_only"] = {"label": lab, "named_by": fam.get("named_by"),
                               "tag_words": fam.get("tag_words"),
                               "printed": fam.get("printed")}
        rows += got
        note["located"][str(sheet)] = res.get("labels_by_tag") or res.get("refused")
    return rows, note


def seed_from_stairs(floors: List[Dict[str, Any]], open_page: Callable[[Dict[str, Any]], Any],
                     door_in) -> List[str]:
    """A STAIR CARRIES ITS UNIT TO THE LEVEL IT REACHES (rule (b), rulings
    2026-10-11; plan_derive). For every unit holding exactly one stair label,
    the plan that stair reaches - the next in the series, confirmed against
    the title ordinals where both print one - is seeded with the unit at the
    stair's registered position, IF that plan names no units of its own and
    the two register. Its membership map is then built from the seeds as if
    they were printed tags. Both sheets' rows record the link: the source's
    stair evidence gains "reaches <sheet>", and the seeded unit's evidence
    is "seeded from <sheet>: ..." - which the gate needs to sum a duplex.

    Each seeded region's area is reported beside the unit's NET on its own
    floor (informational, as the existing ratios are); a seeded region is
    otherwise checked only by render.

    A plan that DOES name its own units is linked, not seeded (ruling
    2026-10-24): see link_refusal. Every stair between two sheets for one
    unit must pass, or there is no link - one end refusing is a
    contradiction, never outvoted by the other. Returns a line per
    decision."""
    from lib.plan_sheet import register
    from lib.plan_space import build_space

    notes: List[str] = []
    plans = [f["arch_p"] for f in floors]
    by_sheet = {f["a_sheet"]: f for f in floors}
    wanted: Dict[str, Dict[str, list]] = {}
    links: Dict[tuple, list] = {}
    regs: Dict[tuple, Dict[str, Any]] = {}

    def reg_of(a, b):
        if (a["a_sheet"], b["a_sheet"]) not in regs:
            regs[(a["a_sheet"], b["a_sheet"])] = register(a["data"], b["data"])
        return regs[(a["a_sheet"], b["a_sheet"])]
    for f in floors:
        for u, labs in (f.get("stairs") or {}).items():
            if not labs:
                continue
            if len(labs) != 1:
                notes.append(f"{f['a_sheet']} {u}: {len(labs)} stair labels in the unit - "
                             f"one stair label or no seeding: not seeded")
                continue
            lab, x, y = labs[0]
            tgt_p, why = derive.stair_target(f["arch_p"], lab, plans)
            if tgt_p is None:
                notes.append(f"{f['a_sheet']} {u}: stair {lab} not followed - {why}")
                continue
            t = by_sheet.get(tgt_p.get("sheet_number"))
            if t is None or "data" not in t:
                notes.append(f"{f['a_sheet']} {u}: {tgt_p.get('sheet_number')} was not read")
                continue
            if (t.get("units") or {}).get("tags") is not None:
                why, lands = link_refusal(f, t, u, lab, x, y, reg_of, open_page)
                links.setdefault((*sorted((f["a_sheet"], t["a_sheet"])), u), []).append(
                    (f, t, lab, x, y, lands, why))
                continue
            reg_ = register(f["data"], t["data"])
            if not reg_["usable"]:
                notes.append(f"{f['a_sheet']} {u}: {f['a_sheet']} -> {t['a_sheet']} does not "
                             f"register ({reg_.get('refused')}) - not seeded")
                continue
            wanted.setdefault(t["a_sheet"], {}).setdefault(u, []).append(
                (x + reg_["dx"], y + reg_["dy"], f, lab, x, y))

    for (_lo, _hi, u), evals in sorted(links.items(), key=lambda kv: kv[0]):
        bad = [(f, t, lab, why) for f, t, lab, _x, _y, _l, why in evals if why]
        if bad:
            for f, t, lab, why in bad:
                notes.append(f"{f['a_sheet']} {u}: {t['a_sheet']} names its own units - "
                             f"not seeded; stair {lab} not linked to its {u}: {why}")
            if len(bad) < len(evals):
                notes.append(f"{_lo} / {_hi} {u}: not linked - every stair between the two "
                             f"sheets must pass, and {len(bad)} of {len(evals)} refused")
            continue
        for f, t, lab, x, y, (lx, ly), _w in evals:
            key = f"stair label {lab} at ({round(x)}, {round(y)})"
            ml = f["units"]["multi_level"]
            ml[u] = [e + f" reaches {t['a_sheet']}" if e == key else e for e in ml.get(u, [])]
            t["units"].setdefault("multi_level", {}).setdefault(u, []).append(
                f"linked from {f['a_sheet']}: {key}")
            f["units"].setdefault("linked", {}).setdefault(u, []).append(
                {"to": t["a_sheet"], "stair": lab, "at": [round(x, 1), round(y, 1)],
                 "lands": [round(lx, 1), round(ly, 1)]})
            notes.append(f"{f['a_sheet']} {u}: linked to {t['a_sheet']}'s own {u} - stair "
                         f"{lab} at ({round(x)}, {round(y)}) lands at ({round(lx)}, "
                         f"{round(ly)}), inside it")

    for tgt, by_unit in wanted.items():
        t = by_sheet[tgt]
        one = {}
        for u, cands in sorted(by_unit.items()):
            if len(cands) != 1:
                notes.append(f"{tgt} {u}: seeded by {len(cands)} stairs - not seeded")
            else:
                one[u] = cands[0]
        if not one:
            continue
        tags = sorted(one)
        data = dict(t["data"], words=list(t["data"]["words"])
                    + [(u, sx, sy) for u, (sx, sy, *_r) in one.items()])
        space = build_space(open_page(t["arch_p"]), tags, door_in, data)
        seeded: Dict[str, Any] = {}
        multi: Dict[str, List[str]] = {}
        for u, (sx, sy, src, lab, x, y) in one.items():
            area = (space.get("ratio") or {}).get(u, (None, None))[0]
            net = ((src.get("space") or {}).get("net") or {}).get(u)
            seeded[u] = {"from": src["a_sheet"], "stair": [round(x, 1), round(y, 1)],
                         "at": [round(sx, 1), round(sy, 1)],
                         "area_sf": None if area is None else round(area),
                         "net_sf_on_own_floor": net, "net_on": src["a_sheet"],
                         "ratio": (round(area / net, 2) if area and net else None)}
            multi[u] = [f"seeded from {src['a_sheet']}: stair label {lab} at "
                        f"({round(x)}, {round(y)})"]
            key = f"stair label {lab} at ({round(x)}, {round(y)})"
            ml = src["units"]["multi_level"]
            ml[u] = [e + f" reaches {tgt}" if e == key else e for e in ml.get(u, [])]
            notes.append(f"{tgt} {u}: seeded from {src['a_sheet']}'s stair {lab} at "
                         f"({round(x)}, {round(y)}); region {seeded[u]['area_sf']} sf "
                         f"(the unit's NET on {src['a_sheet']}: {net} sf"
                         f"{'' if seeded[u]['ratio'] is None else ', ratio ' + str(seeded[u]['ratio'])})"
                         " - informational")
        t["data"], t["space"] = data, space
        t["units"] = {"tags": tags, "method": "stair_seeded", "zero_units": False,
                      "why": None, "multi_level": multi, "seeded": seeded}
    for n in notes:
        log.info("glyph pass stair seeding: %s", n)
    return notes


def assign_voids(floors: List[Dict[str, Any]]) -> List[str]:
    """A MARKED OPEN-TO-BELOW VOID JOINS THE UNIT BENEATH IT (ruling
    2026-10-24, lib.plan_voids). For every region of a floor's room map that
    no unit holds and that is marked open to below, the floor beneath - the
    next plan down the series, confirmed by the title ordinals as a stair's
    target is (plan_derive.stair_target) - must register usably, and of the
    region's cells carried onto it, those that land in a unit must all land
    in EXACTLY ONE. Cells over a wall or over space no unit holds are not a
    second unit: on the filed A-103.00 each bay's edge overhangs 4A's own
    bedroom closet by 14-16 of its ~4,000 cells - a closet whose bifold door
    the room map does not read as a doorway, so no unit holds it. That unit's
    region on THIS sheet then takes the void, so a symbol on its walls is
    that unit's.

    The unit must be one this sheet names: a void over a unit this sheet does
    not list would place a symbol in an apartment on a floor the apartment's
    other rows never reach, and its whole-apartment count would miss it.
    Returns a line per decision."""
    from lib.plan_sheet import register
    from lib import plan_voids as V

    notes: List[str] = []
    plans = [f["arch_p"] for f in floors]
    by_sheet = {f["a_sheet"]: f for f in floors}
    for f in floors:
        sp = f.get("space")
        if not sp or (f.get("units") or {}).get("tags") is None:
            continue
        found, why = V.marked_voids(sp, f["data"])
        notes += [f"{f['a_sheet']} {w}" for w in why]
        if not found:
            continue
        tgt, why_t = derive.stair_target(f["arch_p"], "DN", plans)
        g = by_sheet.get((tgt or {}).get("sheet_number"))
        if g is None or not g.get("space"):
            notes += [f"{f['a_sheet']} void at {v['box'][:2]}: no floor below to read - "
                      f"{why_t or 'it was not read'} - not assigned" for v in found]
            continue
        reg_ = register(f["data"], g["data"])
        if not reg_["usable"]:
            notes += [f"{f['a_sheet']} void at {v['box'][:2]}: {f['a_sheet']} -> {g['a_sheet']} "
                      f"does not register ({reg_.get('refused')}) - not assigned" for v in found]
            continue
        lab = sp["closed_lab"]
        for v in found:
            hits, wall = V.beneath(lab, v["room"], sp["lo"], sp["cell_pt"], g["space"],
                                   reg_["dx"], reg_["dy"])
            units = sorted(u for u in hits if u)
            where = f"{f['a_sheet']} void at ({round(v['box'][0])}, {round(v['box'][1])})"
            if len(units) != 1:
                notes.append(f"{where}: beneath it on {g['a_sheet']} lie "
                             f"{', '.join(units) or 'no unit'} - exactly one unit or not assigned")
                continue
            (u,) = units
            if u not in (sp.get("units") or {}):
                notes.append(f"{where}: over {u} on {g['a_sheet']}, but {f['a_sheet']} names "
                             f"no {u} - not assigned")
                continue
            sp["units"][u] = sp["units"][u] | (lab == v["room"])
            share = round(100 * hits[u] / (sum(hits.values()) + wall))
            f["units"].setdefault("voids", {}).setdefault(u, []).append(
                {"box": v["box"], "marked_by": v["how"], "below": g["a_sheet"],
                 "beneath_pct": share})
            notes.append(f"{where}: marked open to below ({'an X on its BELOW layer' if v['how'] == 'x' else repr(v.get('mark'))}), "
                         f"over {u} on {g['a_sheet']} ({share}% of its cells; the rest over wall or space "
                         f"no unit holds) - joins {u}")
    for n in notes:
        log.info("glyph pass voids: %s", n)
    return notes


def _level_words(f: Dict[str, Any], u: str) -> List[str]:
    """The LOWER / UPPER words printed inside unit u on floor f."""
    out = []
    for e in ((f.get("units") or {}).get("multi_level") or {}).get(u) or []:
        if e.startswith("level word "):
            w = e.split()[2]
            if w in ("LOWER", "UPPER"):
                out.append(w)
    return out


def mech_scale(f: Dict[str, Any], open_page, scale_sheets: Dict[Any, Any]) -> Dict[str, Any]:
    """The floor's mechanical plan's scale: its own where its drawing
    verifies, else BORROWED from the floor's architectural plan - only when
    their registration is usable by the one offset rule
    (plan_sheet.register_offset, ruling 63; its margin is recorded) and the
    architectural viewport verified on its own dimensions (plan_scale.borrow,
    ruling 5). The placement's own registration (register()) is untouched.
    The result names the lender and the registration's evidence, or why
    there is no scale. Recorded in the pass summary ("mech_scales"); a read
    that fails is said there and never sinks the pass."""
    from lib import plan_scale as ps
    from lib.plan_sheet import load_sheet, matched_anchors, register_offset
    a_sheet, m_sheet = f.get("a_sheet"), f.get("m_sheet")
    try:
        mech = f.get("mech_data") or load_sheet(open_page(f["mech_p"]))
        reg_ = register_offset(f["data"], mech)
        if not reg_.get("usable"):          # refused before any sheet is read
            _v, res = ps.borrow(m_sheet, None, a_sheet, None, reg_, (), ())
        else:
            if "scale_sheet" not in f:
                f["scale_sheet"] = ps.read_sheet(open_page(f["arch_p"]))
            mech_p = f["mech_p"]
            k = mech_p.get("page_id") or (mech_p.get("file_id"), mech_p.get("page_number"))
            if k not in scale_sheets:
                scale_sheets[k] = ps.read_sheet(open_page(mech_p))
            a_pts, m_pts = matched_anchors(f["data"], mech, reg_)
            _v, res = ps.borrow(m_sheet, scale_sheets[k], a_sheet, f["scale_sheet"], reg_,
                                a_pts, m_pts)
    except Exception as e:                          # one floor never sinks the pass
        log.exception("mechanical scale %s / %s failed: %r", m_sheet, a_sheet, e)
        res = {"sheet": m_sheet, "status": "refused", "pt_per_in": None,
               "from": {"sheet": a_sheet, "viewport": None},
               "why": f"scale read failed: {type(e).__name__}"}
    log.info("glyph pass mechanical scale: %s %s%s", m_sheet, res["status"],
             f" from {a_sheet}" if res["status"] == "borrowed" else
             (f" - {res.get('why')}" if res.get("why") else ""))
    return res


def _partner_registration(f: Dict[str, Any], open_page) -> Dict[str, Any]:
    """The floor's architectural sheet registered to its mechanical partner,
    read once; the partner sheet is kept for the placement that follows."""
    if "partner_reg" not in f:
        from lib.plan_sheet import load_sheet, register
        f["mech_data"] = load_sheet(open_page(f["mech_p"]))
        f["partner_reg"] = register(f["data"], f["mech_data"])
    return f["partner_reg"]


def link_refusal(src: Dict[str, Any], tgt: Dict[str, Any], u: str, lab: str,
                 x: float, y: float, reg_of, open_page):
    """(None, (lx, ly)) when the stair labelled `lab` at (x, y) in unit u on
    `src` links u to the unit tagged u on `tgt` - else (why not, None).

    A STAIR LINKS ITS UNIT TO THE SAME UNIT ON A PLAN THAT NAMES IT (ruling
    2026-10-24). The filed mezzanine A-104.00 (AR 3.28.25) prints 4A-4D
    itself, so it is not seeded, and the whole-apartment count refused. The
    stair now links u to the unit tagged u there only if ALL hold:
      1. the target is the plan the stair reaches by the seeding rule (series
         + title ordinals; the caller's plan_derive.stair_target);
      2. exactly one unit is tagged u on the target - u has a region there,
         nothing refused or incomplete, and no label u lies in another unit;
      3. registration is usable on both sheets: source -> target (which
         carries the landing point), and each sheet to its mechanical partner;
      4. the stair's registered landing point falls inside u's region there;
      5. any LOWER / UPPER words agree: the lower level's unit says LOWER or
         nothing, the upper's UPPER or nothing (UP from the source makes the
         source the lower level, DN the upper). A contradiction refuses.
    Measured 2026-10-24 on the filed set: all four of 4A-4D pass every
    condition, from both ends (A-103's UP and A-104's DN); the landings sit
    30 pt (4A, 4B) and 15 pt (4C, 4D) inside the unit's wall by the public
    stair core, by render."""
    t_sheet = tgt["a_sheet"]
    tsp, member = tgt.get("space") or {}, tgt.get("member")
    if u not in ((tgt.get("units") or {}).get("tags") or []):
        return f"{t_sheet} names no unit {u}", None
    held = {t for r in tsp.get("refused") or []
            if isinstance(r, (list, tuple)) and len(r) > 1 for t in r[1]}
    if (u not in (tsp.get("units") or {}) or u in (tsp.get("incomplete") or {})
            or u in held or member is None):
        return f"{u} has no region of its own on {t_sheet}", None
    elsewhere = sorted({member.at(wx, wy) for w, wx, wy in tgt["data"].get("words") or []
                        if w == u} - {u, ""})
    if elsewhere:
        return (f"{t_sheet} prints {u} in more than one unit "
                f"({', '.join([u] + elsewhere)})"), None
    lower, upper = (src, tgt) if lab.upper() == "UP" else (tgt, src)
    for f, want in ((lower, "LOWER"), (upper, "UPPER")):
        bad = [w for w in _level_words(f, u) if w != want]
        if bad:
            return (f"{f['a_sheet']} calls {u} {bad[0]}, but the stair makes it the "
                    f"{want.lower()} level"), None
    reg_ = reg_of(src, tgt)
    if not reg_["usable"]:
        return (f"{src['a_sheet']} -> {t_sheet} does not register "
                f"({reg_.get('refused')})"), None
    for f in (src, tgt):
        pr = _partner_registration(f, open_page)
        if not pr.get("usable"):
            return (f"{f['a_sheet']} -> {f.get('m_sheet')} does not register "
                    f"({pr.get('refused')})"), None
    lx, ly = x + reg_["dx"], y + reg_["dy"]
    at = member.at(lx, ly)
    if at != u:
        return (f"the stair lands at ({round(lx)}, {round(ly)}) on {t_sheet}, in "
                f"{at or 'no unit'}, not {u}"), None
    return None, (lx, ly)
