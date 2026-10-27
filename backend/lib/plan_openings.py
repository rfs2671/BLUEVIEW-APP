"""Doors and windows: the tags an ARCHITECTURAL plan prints, counted and
placed by the equipment machinery (lib.plan_glyph_pass, lib.plan_emit,
plan_search's located-symbol gate).

    families(schedules)                      the door/window schedules' closed sets
    read_tags(page)                          the opening tags a plan prints
    run_openings(floors, open_page, fams, track=..., refused=...)
                                             -> {"rows", "summary", "health"}

MEASURED ON 588 BOYLAND, 2026-10-26 (bv-worktrees/L2_doors_measure.md):

  THE TAG IS TEXT, INSIDE AN OUTLINE ON AN IDEN LAYER. Door tags sit in a
  circle on `*|A-DOOR-IDEN`, window tags in a hexagon on `*|A-WINDOW-IDEN`.
  A word whose centre lies inside such an outline is a tag; nothing is OCR'd.
  The layer says only "an opening tag": the exterior doors D1/D2 are tagged
  on the WINDOW-IDEN layer. WHICH family is the schedule's closed set's
  answer, matched exactly - the text is the text layer's, not a reading.
  Wall tags (W1..W6 on WALL TAGS) are never read, though A-500's wall types
  share the window's name W1.

  THE SCHEDULE IS ELEVATION-STYLE. A-400.00 draws one panel per type, headed
  "NUMBER <tag>", with no row grid and no QTY column; its records carry no
  identifier column, so the closed set is the panels' heads (panel_tags).

  A LEGEND KEY IS NOT AN OPENING. Every plan's legend prints "W1 WINDOW TAG"
  with the key on the WINDOW-IDEN layer and no window beside it.

  THE SYMBOL IS NOT THE TAG (plan_symbols.symbol_at_label), searched only
  among A-Door / A-Glaz objects: a door's leaf and swing lie in the room it
  opens into - the apartment entrance's tag sits in the doorway, on the
  corridor side, and its door swings into the apartment. A window's glazing
  is in the exterior wall, and the host-wall probe (plan_takeoff.Units)
  carries it inside, as it carries a PTAC.

  ONE SYMBOL, ONE TAG. The owner's set draws its post-CO additions on a
  layer named TO REMOVE: 1A's new bedroom door and closet have tags but no
  A-Door symbol, and the nearest A-Door object was the bath door - E's. A
  symbol whose nearest tag is another tag's is CONTESTED: the tag still
  counts on its floor (it is read, and names its type), its placement is
  refused.

  A SYMBOL NO TAG NAMES makes its floor incomplete. The owner's mezzanine
  draws four bath doors with no tag; a door of unknown type there may be any
  door type. Each is one UNREAD row of every door family (a window, of every
  window family), and the gate refuses that family's floor and building
  figures on that track (plan_search, an opening book).

Pure of the database and of R2, like plan_glyph_pass.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from lib import plan_emit as emit
from lib import plan_symbols as psym
from lib import plan_tally as ptal
from lib.plan_records import tier_rank

log = logging.getLogger(__name__)

#: rows of this pass carry payload.kind = KIND; the gate keeps them apart
#: from the mechanical symbols' (plan_search.opening_books)
KIND = "opening"
#: payload.opening_version: what an opening row records. 1 (2026-10-26).
OPENING_VERSION = 1

#: a schedule of doors or windows, by its printed name
SCHEDULE_NAME = re.compile(r"\b(DOOR|WINDOW)S?\b.*\bSCHEDULE\b", re.I)
#: the opening-tag layers: NCS A-DOOR-IDEN / A-WINDOW-IDEN, xref-prefixed
IDEN_LAYER = re.compile(r"(?i)(?:^|\|)A-(DOOR|WINDOW|GLAZ)-IDEN$")
#: the opening-symbol layers: A-Door, A-Glaz (and A-GLAZ-SILL ...), never a
#: text/annotation layer (plan_symbols.is_text_layer)
SYMBOL_LAYER = re.compile(r"(?i)(?:^|\|)A-(DOOR|GLAZ)(?:-[A-Z0-9]+)*$")
#: a tag as these schedules print it: A, F, D1, W3
TAG_SHAPE = re.compile(r"^[A-Z]{1,2}\d{0,2}$")
_PANEL_HEAD = re.compile(r"^(?:NUMBER\s+([A-Z]{1,2}\d{0,2})|([A-Z]{1,2}\d{0,2})\s+NUMBER)$")

#: the tag search and the symbol's size, as the equipment's (plan_takeoff)
LABEL_SEARCH_IN = 90.0
SYMBOL_SPAN_IN = 60.0
#: two outlines' paths this close are one outline
OUTLINE_LINK_PT = 1.0
#: a legend line: the key, then words ending in TAG, within this to its right
LEGEND_REACH_PT = 150.0
#: A-Glaz geometry this close is one window (its glazing and frame lines)
WINDOW_LINK_PT = 10.0
DOOR_LINK_PT = 1.0
#: geometry smaller than this in both directions is dust, not an opening
MIN_OPENING_PT = 6.0


def schedule_kind(name: str) -> Optional[str]:
    m = SCHEDULE_NAME.search(name or "")
    return m.group(1).lower() if m else None


def panel_tags(columns: Sequence[Any], rows: Sequence[Sequence[Any]]) -> List[str]:
    """The closed set of an ELEVATION-STYLE schedule: every printed panel head
    "NUMBER <tag>" (or "<tag> NUMBER", as a transposed read gives it), in the
    order printed. A cell that says anything else is not a head."""
    cells = [(c.get("header") if isinstance(c, dict) else c) for c in columns or []]
    for row in rows or []:
        cells += list(row or [])
    out: List[str] = []
    for c in cells:
        m = _PANEL_HEAD.match(re.sub(r"\s+", " ", str(c or "")).strip().upper())
        if m:
            t = m.group(1) or m.group(2)
            if t not in out:
                out.append(t)
    return out


def families(schedules: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """name -> {"tags", "corroborations", "tier", "sheet", "kind"} for every
    door or window schedule, read at its BEST tier (as
    plan_glyph_pass.families). The closed set is the identifier column when
    the schedule has one, else its panel heads. A tag two schedules both
    list belongs to neither (`ambiguous`): which family it counts in cannot
    be said."""
    best: Dict[str, Dict[str, Any]] = {}
    for s in schedules:
        name = (s.get("name") or "").strip().upper()
        if not name or not schedule_kind(name):
            continue
        cur = best.get(name)
        if cur is None or tier_rank(s.get("tier")) < tier_rank(cur.get("tier")):
            best[name] = s
    out: Dict[str, Dict[str, Any]] = {}
    for name, s in sorted(best.items()):
        tags, _corr = psym.closed_set_from_schedule(s.get("columns") or [], s.get("rows") or [])
        if not tags:
            tags = panel_tags(s.get("columns") or [], s.get("rows") or [])
        tags = [t for t in tags if TAG_SHAPE.match(t)]
        out[name] = {"tags": tags, "corroborations": {}, "tier": s.get("tier"),
                     "sheet": s.get("sheet_number") or s.get("sheet"),
                     "kind": schedule_kind(name)}
    owners: Dict[str, List[str]] = {}
    for name, f in out.items():
        for t in f["tags"]:
            owners.setdefault(t, []).append(name)
    shared = {t for t, ns in owners.items() if len(ns) > 1}
    for name, f in out.items():
        f["ambiguous"] = sorted(set(f["tags"]) & shared)
        f["tags"] = [t for t in f["tags"] if t not in shared]
    return out


# ── the tags a plan prints ─────────────────────────────────────────────────

def _touch(a, b, pad) -> bool:
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def _clusters(boxes: Sequence[Sequence[float]], pad: float) -> List[List[float]]:
    out: List[List[float]] = []
    for b in boxes:
        b = list(b)
        merged = True
        while merged:
            merged = False
            for o in out:
                if _touch(b, o, pad):
                    out.remove(o)
                    b = [min(b[0], o[0]), min(b[1], o[1]), max(b[2], o[2]), max(b[3], o[3])]
                    merged = True
                    break
        out.append(b)
    return out


def read_tags(page) -> List[Dict[str, Any]]:
    """[{"text", "x", "y", "box", "legend"}] - every outline drawn on an
    opening-tag layer, and the words inside it (joined, left to right; ""
    when none). `legend` marks a legend key: the line continues, within
    LEGEND_REACH_PT to the right, with a word TAG ("W1  WINDOW TAG")."""
    boxes = [d["rect"] for d in page.drawings if IDEN_LAYER.search(d.get("layer") or "")]
    words = page.words
    out = []
    for c in _clusters(boxes, OUTLINE_LINK_PT):
        inside = sorted((w for w in words
                         if c[0] - 0.5 <= w[1] <= c[2] + 0.5 and c[1] - 0.5 <= w[2] <= c[3] + 0.5),
                        key=lambda w: w[1])
        text = "".join(w[0] for w in inside).strip().upper()
        cy = (c[1] + c[3]) / 2
        right = [w for w in words if abs(w[2] - cy) <= 4 and c[2] < w[1] <= c[2] + LEGEND_REACH_PT]
        legend = any(re.sub(r"[^A-Z]", "", w[0].upper()) == "TAG" for w in right)
        out.append({"text": text, "x": (c[0] + c[2]) / 2, "y": cy, "box": tuple(c),
                    "legend": legend})
    return out


def _symbol_kind(layer: str) -> Optional[str]:
    m = SYMBOL_LAYER.search(layer or "")
    if not m or psym.is_text_layer(layer):
        return None
    return "door" if m.group(1).upper() == "DOOR" else "window"


def _dist_to_box(x, y, b) -> float:
    dx = max(b[0] - x, 0.0, x - b[2])
    dy = max(b[1] - y, 0.0, y - b[3])
    return (dx * dx + dy * dy) ** 0.5


# ── one floor ──────────────────────────────────────────────────────────────

def floor_records(page, fams: Dict[str, Dict[str, Any]], units=None,
                  unplaced_reason: Optional[str] = None) -> Dict[str, Any]:
    """Every opening on one plan: {"records": {family: [record]}, "orphans",
    "legend", "untagged", "unreadable"}. A record is plan_takeoff.run_takeoff's
    shape, so plan_emit.glyph_rows writes it. `units` is the floor's
    plan_takeoff.Units, or None - then placement is refused with
    `unplaced_reason` (the floor is counted at sheet scope)."""
    from lib.plan_sheet import _pts, symbol_objects

    family_of = {t: n for n, f in fams.items() for t in f["tags"]}
    objs = []
    for o in symbol_objects(page):
        k = _symbol_kind(o.get("layer"))
        if k and o.get("points"):
            objs.append(dict(o, kind=k))
    tags = read_tags(page)
    legend = [t for t in tags if t["legend"]]
    tags = [t for t in tags if not t["legend"]]
    unreadable = [t for t in tags if not t["text"]]
    orphans = [t for t in tags if t["text"] and t["text"] not in family_of]
    named = [t for t in tags if t["text"] in family_of]
    # the symbol beside each tag
    for t in named:
        rep: Dict[str, Any] = {}
        pos, n = psym.symbol_at_label((t["x"], t["y"]), objs, _pts(LABEL_SEARCH_IN),
                                      _pts(SYMBOL_SPAN_IN), label_boxes=[t["box"]],
                                      report=rep)
        t["symbol_at"] = tuple(pos) if pos is not None else None
        t["symbol_bbox"] = tuple(rep["bbox"]) if pos is not None and rep.get("bbox") else None
        t["symbol_pts"] = n
    # ONE SYMBOL, ONE TAG: the tag strictly nearest a symbol is its tag; a
    # tie names no owner, and every tag in it is contested
    every = [t for t in tags if t["text"]]
    for t in named:
        b = t.get("symbol_bbox")
        if b is None:
            t["owner"] = None
            continue
        ds = sorted(((_dist_to_box(u["x"], u["y"], b), i) for i, u in enumerate(every)))
        near = every[ds[0][1]]
        tie = len(ds) > 1 and ds[1][0] - ds[0][0] < 1e-6
        t["owner"] = t if (near is t and not tie) else (near if near is not t else
                                                         every[ds[1][1]])
    # symbols no tag names: A-Door objects grown by touch, A-Glaz by 10 pt
    claimed = [t["symbol_bbox"] for t in named if t.get("symbol_bbox")]
    untagged = []
    for kind, pad in (("door", DOOR_LINK_PT), ("window", WINDOW_LINK_PT)):
        boxes = [psym._bbox(o["points"]) for o in objs if o["kind"] == kind]
        for c in _clusters(boxes, pad):
            if max(c[2] - c[0], c[3] - c[1]) < MIN_OPENING_PT:
                continue
            if not any(_touch(c, b, 1.0) for b in claimed):
                untagged.append({"kind": kind, "box": [round(v, 1) for v in c]})
    recs: Dict[str, List[Dict[str, Any]]] = {n: [] for n in fams}
    for t in sorted(named, key=lambda t: (t["y"], t["x"])):
        fam = family_of[t["text"]]
        base = {"label_at": (t["x"], t["y"]), "label_box": t["box"], "label_text": t["text"],
                "symbol_at": t.get("symbol_at"), "symbol_bbox": t.get("symbol_bbox"),
                "at_arch": t.get("symbol_at")}
        if t.get("symbol_at") is None:
            # A TAG WITH NO SYMBOL BESIDE IT is not an opening the plan draws
            # (plan_takeoff's rule): unread, and its floor's figures refuse.
            recs[fam].append(dict(base, tag=None, unit=None, glyph_status=ptal.UNREAD,
                                  placement=None, how=f"no door or window symbol ({t['symbol_pts']} pts)",
                                  reason="no door or window symbol beside the tag",
                                  at_arch=None))
            continue
        if t["owner"] is not t:
            o = t["owner"]
            why = (f"refused: its nearest door/window symbol is {o['text']}'s at "
                   f"({round(o['x'])}, {round(o['y'])})")
            recs[fam].append(dict(base, tag=t["text"], unit=None, glyph_status=ptal.RESOLVED,
                                  placement="refused", how=why, reason=why))
            continue
        if units is None:
            unit, how = None, unplaced_reason or "refused: no membership map"
        else:
            unit, how = units.unit_of_normal(*t["symbol_at"])
        recs[fam].append(dict(base, tag=t["text"], unit=unit, glyph_status=ptal.RESOLVED,
                              placement=("refused" if not unit else "placed-non-unit"
                                         if unit.startswith("non-unit:") else "placed"),
                              how=how, reason=None if unit else how))
    # AN UNTAGGED SYMBOL: one unread row in every family of its kind
    for u in untagged:
        for n, f in fams.items():
            if f["kind"] == u["kind"] and f["tags"]:
                recs[n].append({"tag": None, "unit": None, "glyph_status": ptal.UNREAD,
                                "placement": None,
                                "how": f"a {u['kind']} symbol no tag names",
                                "reason": f"a {u['kind']} symbol no tag names: its type is unknown",
                                "label_at": None, "label_box": None, "label_text": "",
                                "symbol_at": ((u["box"][0] + u["box"][2]) / 2,
                                              (u["box"][1] + u["box"][3]) / 2),
                                "symbol_bbox": tuple(u["box"]), "at_arch": None})
    return {"records": recs, "orphans": orphans, "legend": legend,
            "untagged": untagged, "unreadable": unreadable}


def _refused_tags(space: Optional[Dict[str, Any]]) -> List[str]:
    """Units whose region the map refused or left incomplete (run_takeoff's)."""
    if not space:
        return []
    return sorted(({t for r in space.get("refused") or []
                    for t in (r[1] if isinstance(r, (list, tuple)) and len(r) > 1 else [])}
                   | set(space.get("incomplete") or {})) - {"UNKNOWN"})


def run_openings(floors: Sequence[Dict[str, Any]], open_page: Callable[[Dict[str, Any]], Any],
                 fams: Dict[str, Dict[str, Any]], *, track: str = "filed",
                 refused: Sequence[Tuple[Dict[str, Any], str]] = (),
                 widest_door: Optional[Dict[str, Any]] = None,
                 progress: Optional[Callable[[str, Dict[str, Any]], Any]] = None) -> Dict[str, Any]:
    """Every opening row of one drawing track.

    `floors` are plan_glyph_pass's floors (each architectural plan with its
    units, membership map, stair links and voids, already read). `refused`
    are the plan-titled architectural pages the pairing refused, with why:
    each carries tags this pass did not read, so each is a refusal row that
    blocks its track's building figures (and its floor's, when it has one).
    A track with no door or window schedule reconciled writes nothing.
    `progress` is plan_glyph_pass.run_pass's (one "openings" step a floor)."""
    from lib.plan_pass_progress import tell
    from lib.plan_takeoff import Units

    run = {n: f for n, f in fams.items() if f["tags"]}
    rows: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {"track": track, "families": {n: f["tags"] for n, f in run.items()},
                               "floors": [], "refused": []}
    health: List[Dict[str, Any]] = []
    if not run:
        return {"rows": rows, "summary": summary, "health": health}
    door = widest_door or {"inches": None}

    def tagged(rs):
        for r in rs:
            r["payload"]["kind"] = KIND
            r["payload"]["opening_version"] = OPENING_VERSION
            r["payload"]["track"] = track
        return rs

    for page, why in refused:
        sheet = page.get("sheet_number") or f"{page.get('file_name')} p{page.get('page_number')}"
        rows += tagged([emit.sheet_refusal(page, f"doors and windows not read: {why}",
                                           pass_key=f"openings|{sheet}", role=KIND)])
        summary["refused"].append([sheet, why])
    located: set = set()
    for i, f in enumerate(floors, 1):
        arch_p, a_sheet = f["arch_p"], f["a_sheet"]
        tell(progress, "sheet", stage="openings", sheet=a_sheet, i=i, n=len(floors))
        units_ = f.get("units") or {}
        space = f.get("space")
        floor = {"arch": a_sheet, "families": {}}
        summary["floors"].append(floor)
        try:
            pg = open_page(arch_p)
            if space is not None and units_.get("tags") is not None:
                member = Units(space["units"], space["lo"], space["cell_pt"],
                               space["refused"], space, space["tags"])
                got = floor_records(pg, run, member)
                units_row, refused_tags = units_, _refused_tags(space)
                method, fallback = space.get("method"), space.get("fallback_reason")
            else:
                why = units_.get("why") or "no units derivable"
                got = floor_records(pg, run, None,
                                    f"refused: {a_sheet}: {why}: counted at sheet scope, not placed")
                units_row = {"tags": [], "method": "sheet_scope", "zero_units": False,
                             "multi_level": {}}
                refused_tags, method, fallback = [], "sheet_scope", None
        except Exception as e:                      # one floor never sinks the pass
            log.exception("openings %s failed: %r", a_sheet, e)
            rows += tagged([emit.sheet_refusal(arch_p, f"doors and windows not read: "
                                               f"{type(e).__name__}",
                                               pass_key=f"openings|{a_sheet}", role=KIND)])
            floor["refused"] = type(e).__name__
            continue
        floor.update(legend=len(got["legend"]), untagged=got["untagged"],
                     orphans=[t["text"] for t in got["orphans"]])
        if got["unreadable"]:
            # AN OUTLINE WITH NO READABLE TAG is an opening of no known type:
            # the floor's opening figures refuse, every family.
            rows += tagged([emit.sheet_refusal(
                arch_p, f"doors and windows not read: {len(got['unreadable'])} tag outline(s) "
                        f"with no readable tag", pass_key=f"openings|{a_sheet}", role=KIND)])
            floor["refused"] = "unreadable tag outline"
            continue
        for t in got["orphans"]:
            health.append({"kind": "plan_tag_not_in_schedule", "sheet": a_sheet,
                           "subject": t["text"], "track": track,
                           "detail": f"{t['text']} is printed in a door/window tag on {a_sheet} "
                                     f"({track} set) but no door or window schedule lists it"})
        for name, recs in got["records"].items():
            located |= {r["tag"] for r in recs if r.get("tag")}
            result = {"records": recs, "method": method, "fallback_reason": fallback,
                      "registration": {"dx": 0.0, "dy": 0.0, "usable": True,
                                       "anchors": None, "refused": None},
                      "refused_tags": refused_tags if recs else []}
            out = emit.glyph_rows(result, mech=arch_p, arch=arch_p, family=name,
                                  pass_key=f"{a_sheet}|openings|{name}", units=units_row,
                                  widest_door=door, mech_count=len(recs))
            rows += tagged(out)
            floor["families"][name] = {
                "rows": len(out),
                "by_tag": {t: sum(1 for r in recs if r.get("tag") == t) for t in run[name]["tags"]},
                "unread": sum(1 for r in recs if r.get("glyph_status") == ptal.UNREAD),
                "unplaced": sum(1 for r in recs if r.get("tag") and not r.get("unit"))}
    for name, f in sorted(run.items()):
        for t in f["tags"]:
            if t not in located:
                health.append({"kind": "schedule_tag_not_located", "sheet": f.get("sheet"),
                               "subject": t, "family": name, "track": track,
                               "detail": f"{t} ({name}): the schedule lists it; no {track} "
                                         f"plan prints its tag"})
    for name, f in sorted(fams.items()):
        for t in f.get("ambiguous") or []:
            health.append({"kind": "tag_in_two_schedules", "sheet": f.get("sheet"),
                           "subject": t, "family": name,
                           "detail": f"{t} is listed by more than one door/window schedule; "
                                     f"it is counted in none - state no count of {t}"})
    return {"rows": rows, "summary": summary, "health": health}
