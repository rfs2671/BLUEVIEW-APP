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
from typing import Any, Callable, Dict, List, Sequence

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


def run_pass(pages: Sequence[Dict[str, Any]], open_page: Callable[[Dict[str, Any]], Any],
             schedules: Sequence[Dict[str, Any]],
             door_pages: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Every glyph row for the project, and what was done and refused."""
    from lib.plan_sheet import load_sheet
    from lib.plan_space import build_space
    from lib.plan_takeoff import run_takeoff, sweep

    rows: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {"pairs": [], "refused_sheets": [], "families": {},
                               "skipped_families": [], "door": None, "floors": []}

    paired = derive.pair_plan_sheets(pages)
    for page, why in paired["refused"]:
        rows += emit.refusal_rows([(page, why)])
        summary["refused_sheets"].append([page.get("sheet_number"), why])

    door = {"inches": None, "doors": {}, "why": "no door schedule in the set"}
    for p in door_pages:
        got = derive.widest_door_in(open_page(p).directed_words)
        if got["inches"] and (door["inches"] is None or got["inches"] > door["inches"]):
            door = dict(got, sheet=p.get("sheet_number"))
    summary["door"] = door

    fams = families(schedules)
    run_fams = {n: f for n, f in fams.items() if f["tags"]}
    summary["families"] = {n: f["tags"] for n, f in run_fams.items()}
    summary["skipped_families"] = sorted(n for n, f in fams.items() if not f["tags"])

    for arch_p, mech_p in paired["pairs"]:
        a_sheet, m_sheet = arch_p.get("sheet_number"), mech_p.get("sheet_number")
        summary["pairs"].append([a_sheet, m_sheet])
        if not run_fams:
            rows.append(emit.sheet_refusal(
                mech_p, "no equipment schedule with an identifier column",
                pass_key=f"{a_sheet}|{m_sheet}"))
            continue
        arch_pg, mech_pg = open_page(arch_p), open_page(mech_p)
        a_sheet_data = load_sheet(arch_pg)
        units = derive.unit_tags(a_sheet_data["words"], a_sheet_data["corners"])
        floor = {"arch": a_sheet, "mech": m_sheet, "units": units, "families": {}}
        summary["floors"].append(floor)
        if units["tags"] is None:
            rows.append(emit.sheet_refusal(
                mech_p, f"{a_sheet}: {units['why']}", pass_key=f"{a_sheet}|{m_sheet}"))
            continue
        mech_sheet = load_sheet(mech_pg)
        reads = sweep(mech_pg, mech_sheet["segs"])
        # one membership map per floor, whatever the family
        space = build_space(arch_pg, units["tags"], door["inches"], a_sheet_data)
        floor["method"] = space.get("method")
        floor["fallback_reason"] = space.get("fallback_reason")
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
                                  pass_key=key, units=units, widest_door=door)
            rows += got
            floor["families"][name] = {
                "rows": len(got), "total": res.get("total"),
                "per_unit": res.get("per_unit"), "unavailable": res.get("unavailable"),
                "method": res.get("method"), "fallback_reason": res.get("fallback_reason"),
                "refused": res.get("refused"),
                "labels_by_tag": res.get("labels_by_tag")}
    for i, r in enumerate(rows):
        r["ordinal"] = i
    summary["rows"] = len(rows)
    return {"rows": rows, "summary": summary}
