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

  DRAWN ON A LAYER NAMED TO REMOVE (queue item 25, ruling 2026-10-28). The
  owner's A-100.00 draws 1A's post-CO bedroom door F, closet G and lower W1
  on `XR FLOOR PLANS|TO REMOVE`: offered that layer's ink beside A-Door /
  A-Glaz, symbol_at_label picks the removal ink for exactly those three tags
  (measured on every sheet of both tracks: TO REMOVE is on the owner's
  A-100.00 - A-102.00 and A-104.00 only; on A-101/A-102 it is a bedroom
  partition no tag reaches, and the mezzanine's carries no tag at all). Such
  a tag is a SET-HEALTH FLAG (removal_layer_health), never a binding: the
  rows are what they were.

  REMOVAL-LAYER FOLLOW-UPS (rulings 37-40, 2026-10-28). A removal layer is
  TO REMOVE or a CAD -DEMO layer, never an EXISTING one - one predicate,
  plan_space_layers.is_removal_layer. Ink on it that no tag names is a
  SHEET-level item (removal_layer_ink_health): on the owner's set, A-104.00
  80 objects, A-101.00 and A-102.00 12 each, A-100.00 13 beside the three
  tagged openings. Both items are written for the plans read under a set
  question too. Neither refuses an answer.

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
from lib.plan_space_layers import REMOVAL_LAYER as _REMOVAL_LAYER, is_removal_layer

log = logging.getLogger(__name__)

#: rows of this pass carry payload.kind = KIND; the gate keeps them apart
#: from the mechanical symbols' (plan_search.opening_books)
KIND = "opening"
#: payload.opening_version: what an opening row records. 1 (2026-10-26).
#: 2 (2026-10-27, ruling 21): a plan whose membership of the set is not
#: decided is READ, its rows marked with its question (lib.plan_set_questions).
OPENING_VERSION = 2

#: a schedule of doors or windows, by its printed name
SCHEDULE_NAME = re.compile(r"\b(DOOR|WINDOW)S?\b.*\bSCHEDULE\b", re.I)
#: the opening-tag layers: NCS A-DOOR-IDEN / A-WINDOW-IDEN, xref-prefixed
IDEN_LAYER = re.compile(r"(?i)(?:^|\|)A-(DOOR|WINDOW|GLAZ)-IDEN$")
#: the opening-symbol layers: A-Door, A-Glaz (and A-GLAZ-SILL ...), never a
#: text/annotation layer (plan_symbols.is_text_layer)
SYMBOL_LAYER = re.compile(r"(?i)(?:^|\|)A-(DOOR|GLAZ)(?:-[A-Z0-9]+)*$")
#: a layer whose name says its ink is to be removed: TO REMOVE, or the CAD
#: status suffix -DEMO; never an EXISTING layer (ruling 38). ONE predicate,
#: lib.plan_space_layers.is_removal_layer, shared with every other reading.
REMOVAL_LAYER = _REMOVAL_LAYER
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


def removal_layer_tags(page, fams: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{"text", "at", "box", "layer", "drawn_at"}] - each schedule tag whose
    drawn opening is on a REMOVAL_LAYER: symbol_at_label, offered that
    layer's ink beside the door/window layers' (the same search floor_records
    runs), seeds on the removal ink. A tag the removal ink merely sits near
    - a partition, the swing of a door that is its own - is not one: the
    nearest drawn object decides. Reads the page; changes nothing."""
    from lib.plan_sheet import _pts, symbol_objects

    family_of = {t for f in fams.values() for t in f.get("tags") or []}
    objs = symbol_objects(page)
    rm = [o for o in objs if o.get("points") and is_removal_layer(o.get("layer"))]
    if not rm:
        return []
    # A-DOOR-DEMO is a door layer by name and a removal layer by status: its
    # ink is offered as removal ink, never as an opening's own symbol
    sym = [o for o in objs if o.get("points") and _symbol_kind(o.get("layer"))
           and not is_removal_layer(o.get("layer"))]
    rm_boxes = {tuple(psym._bbox(o["points"])): o["layer"] for o in rm}
    sym_boxes = {tuple(psym._bbox(o["points"])) for o in sym}
    out = []
    for t in read_tags(page):
        if t["legend"] or t["text"] not in family_of:
            continue
        rep: Dict[str, Any] = {}
        pos, _n = psym.symbol_at_label((t["x"], t["y"]), sym + rm, _pts(LABEL_SEARCH_IN),
                                       _pts(SYMBOL_SPAN_IN), label_boxes=[t["box"]],
                                       report=rep)
        seed = tuple(rep["seed"]) if rep.get("seed") is not None else None
        if pos is None or seed not in rm_boxes or seed in sym_boxes:
            continue
        out.append({"text": t["text"], "at": (t["x"], t["y"]), "box": t["box"],
                    "layer": rm_boxes[seed], "drawn_at": tuple(pos),
                    "drawn_box": tuple(rep["bbox"]) if rep.get("bbox") else None})
    return out


#: a removal path wholly inside a named tag's drawn opening (its box, this
#: much slack for the stroke) is that tag's ink
DRAWN_BOX_SLACK_PT = 1.0


def removal_layer_ink(page, hits: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{layer: {"objects", "tagged", "untagged", "box"}} - every path drawn on a
    removal layer of one page (an object is one path as the PDF draws it,
    plan_page's drawings), split by whether it is a NAMED TAG'S INK: wholly
    inside the drawn opening (`drawn_box`) of a removal_layer_tags hit on the
    same layer. "box" is the untagged paths' extent. Reads only."""
    out: Dict[str, Dict[str, Any]] = {}
    boxes: Dict[str, List[Tuple[float, ...]]] = {}
    for h in hits or ():
        if h.get("drawn_box"):
            b = h["drawn_box"]
            boxes.setdefault(h["layer"], []).append(
                (b[0] - DRAWN_BOX_SLACK_PT, b[1] - DRAWN_BOX_SLACK_PT,
                 b[2] + DRAWN_BOX_SLACK_PT, b[3] + DRAWN_BOX_SLACK_PT))
    for d in page.drawings:
        layer = d.get("layer") or ""
        if not is_removal_layer(layer):
            continue
        r = d.get("rect") or (0.0, 0.0, 0.0, 0.0)
        mine = any(b[0] <= r[0] and b[1] <= r[1] and r[2] <= b[2] and r[3] <= b[3]
                   for b in boxes.get(layer, ()))
        e = out.setdefault(layer, {"objects": 0, "tagged": 0, "untagged": 0, "box": None})
        e["objects"] += 1
        if mine:
            e["tagged"] += 1
            continue
        e["untagged"] += 1
        bx = e["box"]
        e["box"] = tuple(r) if bx is None else (min(bx[0], r[0]), min(bx[1], r[1]),
                                                 max(bx[2], r[2]), max(bx[3], r[3]))
    return out


def removal_layer_health(page, sheet: str, fams: Dict[str, Dict[str, Any]], *,
                         track: str, label: Optional[str] = None, units=None,
                         records: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                         hits: Optional[List[Dict[str, Any]]] = None,
                         question: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """One set-health item (lib.plan_set_health.DRAWN_ON_REMOVAL_LAYER) per
    removal layer of one plan whose ink is the drawn opening of a tag:

      "A-100.00 (the owner's post-CO set, 6/9/26): 1A's F, G and a W1 are
       drawn on layer TO REMOVE; their symbols are not on the door/window
       layers"

    The unit is the membership map's for the removal ink (`units`, a
    plan_takeoff.Units, when the floor has one). "a W1" when the unit has
    more of that tag than the removal layer draws (`records`, floor_records'
    rows for the plan: the unit's placed tags). A flag only: it is appended
    to the track's set health, and no row is read or written by it."""
    from lib.plan_set_health import DRAWN_ON_REMOVAL_LAYER

    hits = [dict(h) for h in (removal_layer_tags(page, fams) if hits is None else hits)]
    if not hits:
        return []
    for h in hits:
        unit = None
        if units is not None:
            unit, _how = units.unit_of_normal(*h["drawn_at"])
        h["unit"] = unit if unit and not unit.startswith("non-unit:") else None
    placed: Dict[Tuple[Any, str], int] = {}
    hit_at = {(round(h["at"][0], 1), round(h["at"][1], 1)) for h in hits}
    for recs in (records or {}).values():
        for r in recs:
            at = r.get("label_at")
            if not r.get("tag") or not r.get("unit") or (
                    at and (round(at[0], 1), round(at[1], 1)) in hit_at):
                continue
            placed[(r["unit"], r["tag"])] = placed.get((r["unit"], r["tag"]), 0) + 1
    where = _where(sheet, track, label, question)
    out = []
    for layer in sorted({h["layer"] for h in hits}):
        mine = sorted((h for h in hits if h["layer"] == layer),
                      key=lambda h: (h["unit"] or "~", h["text"], h["at"][1], h["at"][0]))
        groups: List[str] = []
        for unit in sorted({h["unit"] for h in mine}, key=lambda u: u or "~"):
            texts = [h["text"] for h in mine if h["unit"] == unit]
            words = []
            for tx in sorted(set(texts), key=texts.index):
                k = texts.count(tx)
                n = k + placed.get((unit, tx), 0)
                words.append(tx if k == n == 1 else f"a {tx}" if k == 1
                             else f"{k} {tx}" if k == n else f"{k} of its {n} {tx}")
            phrase = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
            groups.append(f"{unit}'s {phrase}" if unit else f"tag {phrase}" if len(texts) == 1
                          else f"tags {phrase}")
        one = len(mine) == 1
        leaf = layer.split("|")[-1]
        out.append({"kind": DRAWN_ON_REMOVAL_LAYER, "sheet": sheet, "subject": leaf,
                    "track": track, "layer": layer,
                    "tags": [{"tag": h["text"], "unit": h["unit"],
                              "at": [round(h["at"][0], 1), round(h["at"][1], 1)],
                              "drawn_at": [round(h["drawn_at"][0], 1), round(h["drawn_at"][1], 1)]}
                             for h in mine],
                    "detail": f"{where}: {'; '.join(groups)} {'is' if one else 'are'} drawn on "
                              f"layer {leaf}; {'its symbol is' if one else 'their symbols are'} "
                              f"not on the door/window layers"})
        _mark(out[-1], question)
    return out


def _where(sheet: str, track: str, label: Optional[str],
           question: Optional[Dict[str, Any]]) -> str:
    """'A-100.00 (the owner's post-CO set, 6/9/26)'; a plan read under an open
    set question says so: 'A.1.3 (filed set; the A.1.x plans, an open set
    question)'."""
    q = f"; {question['short']}, an open set question" if question else ""
    return f"{sheet} ({label or (track + ' set')}{q})"


def _mark(item: Dict[str, Any], question: Optional[Dict[str, Any]]) -> None:
    """An item of a plan read under an open set question carries the
    question, as that plan's rows do (lib.plan_set_questions.ROW_KEY)."""
    if question:
        from lib import plan_set_questions as psq
        item.update({psq.ROW_KEY: question["id"], psq.ROW_LABEL: question["short"]})


def removal_layer_ink_health(page, sheet: str, *, track: str, label: Optional[str] = None,
                             hits: Sequence[Dict[str, Any]] = (),
                             question: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """One SHEET-level set-health item (lib.plan_set_health.REMOVAL_LAYER_INK,
    ruling 37) per removal layer of one plan that draws ink no door/window
    tag names - every path on the layer that is not a named tag's drawn
    opening (removal_layer_ink, over `hits`, removal_layer_tags' for the
    same page):

      "A-104.00 (the owner's post-CO set, 6/9/26): 80 objects are drawn on
       layer TO REMOVE and no door or window tag names them"

    "more objects" when the same layer also draws a named tag's opening
    (that tag is drawn_on_removal_layer's item). `question` is the open set
    question the plan is read under (lib.plan_set_questions), named in the
    item. A flag only: it refuses nothing (ruling 40)."""
    from lib.plan_set_health import REMOVAL_LAYER_INK

    where = _where(sheet, track, label, question)
    out = []
    for layer, e in sorted(removal_layer_ink(page, hits).items()):
        n = e["untagged"]
        if not n:
            continue
        leaf = layer.split("|")[-1]
        more = "more " if e["tagged"] else ""
        what = (f"1 {more}object is drawn on layer {leaf} and no door or window tag names it"
                if n == 1 else
                f"{n} {more}objects are drawn on layer {leaf} and no door or window tag "
                f"names them")
        item = {"kind": REMOVAL_LAYER_INK, "sheet": sheet, "subject": leaf, "track": track,
                "layer": layer, "objects": n, "tagged_objects": e["tagged"],
                "box": [round(v, 1) for v in e["box"]], "detail": f"{where}: {what}"}
        _mark(item, question)
        out.append(item)
    return out


def removal_layer_items(page, sheet: str, fams: Dict[str, Dict[str, Any]], *, track: str,
                        label: Optional[str] = None, units=None,
                        records: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                        question: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every removal-layer item of one plan: the tags drawn on a removal layer
    (removal_layer_health) and the ink no tag names (removal_layer_ink_health),
    the page's removal ink read once. Called for every floor of the pass AND
    every plan read under a set question (ruling 39). Flags only."""
    hits = removal_layer_tags(page, fams)
    out = removal_layer_health(page, sheet, fams, track=track, label=label, units=units,
                               records=records, hits=hits, question=question)
    return out + removal_layer_ink_health(page, sheet, track=track, label=label, hits=hits,
                                          question=question)


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
                 answers: Optional[Dict[str, str]] = None,
                 progress: Optional[Callable[[str, Dict[str, Any]], Any]] = None) -> Dict[str, Any]:
    """Every opening row of one drawing track.

    `floors` are plan_glyph_pass's floors (each architectural plan with its
    units, membership map, stair links and voids, already read). `refused`
    are the plan-titled architectural pages the pairing refused, with why.

    THE SYSTEM NEVER DECIDES WHICH DRAWINGS BELONG TO A SET (ruling 21,
    lib.plan_set_questions). A refused plan whose number is not in the plan
    series (A.1.1 ... A.1.7, an unnumbered roof plan) is a question, one per
    file, and `answers` ({question id: include | exclude}, the stored
    answers) decides it on this pass:
      exclude   its pages are left out: no row;
      include   they are read at sheet scope, ordinary rows of the track;
      open      they are read at sheet scope, every row (and the refusal of
                a page that could not be read) marked with the question, so
                the gate counts the set with them and without them.
    Any other refused plan (two current A-101s; an A-1xx with no mechanical
    partner) carries tags this pass did not read: a refusal row that blocks
    its track's building figures (and its floor's, when it has one).
    A track with no door or window schedule reconciled writes nothing.
    `progress` is plan_glyph_pass.run_pass's (one "openings" step a floor;
    the set-question pages before them are the stage "set_questions")."""
    from lib import plan_set_questions as psq
    from lib.plan_pass_progress import tell
    from lib.plan_takeoff import Units

    run = {n: f for n, f in fams.items() if f["tags"]}
    rows: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {"track": track, "families": {n: f["tags"] for n, f in run.items()},
                               "floors": [], "refused": [], "set_questions": []}
    health: List[Dict[str, Any]] = []
    if not run:
        return {"rows": rows, "summary": summary, "health": health, "questions": []}
    door = widest_door or {"inches": None}
    answers = answers or {}

    def tagged(rs):
        for r in rs:
            r["payload"]["kind"] = KIND
            r["payload"]["opening_version"] = OPENING_VERSION
            r["payload"]["track"] = track
        return rs

    project_id = next((p.get("project_id") for p, _w in refused if p.get("project_id")), None)
    questions = psq.detect(project_id, track, refused)
    q_of = {str(pg.get("page_id")): q for q in questions for pg in q["pages"]}
    for page, why in refused:
        sheet = page.get("sheet_number") or f"{page.get('file_name')} p{page.get('page_number')}"
        if str(page.get("page_id")) in q_of:
            continue
        rows += tagged([emit.sheet_refusal(page, f"doors and windows not read: {why}",
                                           pass_key=f"openings|{sheet}", role=KIND)])
        summary["refused"].append([sheet, why])
    if questions:
        tell(progress, "stage", stage="set_questions")
    for q in questions:
        ans = answers.get(q["id"])
        summary["set_questions"].append({"id": q["id"], "label": q["label"],
                                         "applied": ans or "open"})
        if ans == psq.EXCLUDE:
            continue
        mark = {} if ans == psq.INCLUDE else {psq.ROW_KEY: q["id"], psq.ROW_LABEL: q["short"]}
        for page, why in refused:
            if q_of.get(str(page.get("page_id"))) is not q:
                continue
            sheet = page.get("sheet_number") or f"{page.get('file_name')} p{page.get('page_number')}"
            out: List[Dict[str, Any]] = []
            try:
                pg = open_page(page)
                got = floor_records(pg, run, None,
                                    f"refused: {sheet}: {why}: counted at sheet scope, not placed")
            except Exception as e:                  # one page never sinks the pass
                log.exception("openings %s failed: %r", sheet, e)
                got = None
                out = [emit.sheet_refusal(page, f"doors and windows not read: "
                                                f"{type(e).__name__}",
                                          pass_key=f"openings|{sheet}", role=KIND)]
            if got is not None and got["unreadable"]:
                out = [emit.sheet_refusal(
                    page, f"doors and windows not read: {len(got['unreadable'])} tag "
                          f"outline(s) with no readable tag", pass_key=f"openings|{sheet}",
                    role=KIND)]
            elif got is not None:
                # DRAWN ON A REMOVAL LAYER, on a plan under a set question
                # too (ruling 39): flags, marked with the question when open
                try:
                    health += removal_layer_items(
                        pg, sheet, run, track=track, label=page.get("drawing_track_label"),
                        records=got["records"], question=None if mark == {} else q)
                except Exception as e:
                    log.exception("openings %s removal layer not read: %r", sheet, e)
                for t in got["orphans"]:
                    health.append({"kind": "plan_tag_not_in_schedule", "sheet": sheet,
                                   "subject": t["text"], "track": track,
                                   "detail": f"{t['text']} is printed in a door/window tag on "
                                             f"{sheet} ({track} set) but no door or window "
                                             f"schedule lists it"})
                for name, recs in got["records"].items():
                    if not recs:
                        continue
                    res = {"records": recs, "method": "sheet_scope", "fallback_reason": None,
                           "registration": {"dx": 0.0, "dy": 0.0, "usable": True,
                                            "anchors": None, "refused": None},
                           "refused_tags": []}
                    out += emit.glyph_rows(res, mech=page, arch=page, family=name,
                                           pass_key=f"{sheet}|openings|{name}",
                                           units={"tags": [], "method": "sheet_scope",
                                                  "zero_units": False, "multi_level": {}},
                                           widest_door=door, mech_count=len(recs))
            for r in tagged(out):
                r["payload"].update(mark)
            rows += out
    located: set = set()
    for i, f in enumerate(floors, 1):
        arch_p, a_sheet = f["arch_p"], f["a_sheet"]
        tell(progress, "sheet", stage="openings", sheet=a_sheet, i=i, n=len(floors))
        units_ = f.get("units") or {}
        space = f.get("space")
        floor = {"arch": a_sheet, "families": {}}
        member = None
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
        # DRAWN ON A REMOVAL LAYER (queue item 25): a flag, after the rows
        # are read - it never changes one, and never sinks the floor.
        try:
            health += removal_layer_items(
                pg, a_sheet, run, track=track, label=arch_p.get("drawing_track_label"),
                units=member, records=got["records"])
        except Exception as e:
            log.exception("openings %s removal layer not read: %r", a_sheet, e)
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
    return {"rows": rows, "summary": summary, "health": health, "questions": questions}
