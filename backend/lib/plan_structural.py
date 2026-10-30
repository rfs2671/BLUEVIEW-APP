"""Structural elements of a set, as polygons in the ARCHITECTURAL plan's frame.

From the S-1xx framing plans of a set: shear walls (SW tags joined to the
shear wall schedule), braced frames, bearing walls, beams and headers,
joists (direction, spacing, size), posts, and the hold-down zone at each end
of a shear wall - each a polygon in the S sheet's display space AND, once the
S sheet is paired to an A plan and registered, in that A plan's display
space. That second polygon is what clash v1 joins against the other trades:
a plumbing stack footprint registered to the same A page is in the same frame.

Pure: no database, no network. The caller hands in the track's index rows
and a page opener (the contract plan_glyph_pass.run_pass takes).

── FLOOR IDENTITY IS THE TITLE, NEVER THE FIT (operator, 2026-10-26) ─────────

    "floor identity comes ONLY from sheet number + title level, NEVER from
    registration fit (matrix: no fit measure separates floors). P/S pairing
    is by parsed title level: both sheets' titles must parse to the same
    level AND the set-wide series offset (e.g. every S = A+1) must hold for
    every sheet in that series; a sheet that breaks the offset or whose
    title doesn't parse REFUSES rather than pairs."

Measured (bv-worktrees/pairing_matrix.json, 2026-10-26): every wrong-floor
S/A pair registers "usable", and A-103.00 holds MORE anchors against S-105
(271) than against its own floor's S-104 (209). So registration here is used
for ONE thing - the offset between two sheets already paired by title -
through the one rule every discipline pair uses (plan_sheet.register_offset:
the offset is the exact census' single best peak, >= MIN_ANCHORS; margin
reported, never thresholded), PLUS an S-only check that reads something else:
whether the structure's walls then stand on the architect's (`wall_check`).

── WHAT THE FRAMING PLANS DRAW (ST - 7.29.26, S-101..S-106; measured) ───────

  walls       closed rectangles on a WALL layer (X-REF|SET_CONCRETE_COLUMN_WALL);
              on the roof plan the walls are drawn DASHED on a ..._BELOW layer
  hatch       inside each wall, on a HATCH layer: diagonals both ways = a CFS
              BRACED FRAME (legend 5, "SEE S-301"); ticks across the wall = a
              STUD BEARING WALL (legend 6)
  SW n        real PDF text beside a braced frame; S-301's CFS SHEAR WALL
              SCHEDULE gives, per floor and per wall, end members, studs, top
              and bottom members and diagonals
  posts       6"x6" built-up post symbols (an H in a square), sized by a
              leader to "(2) 6J18 CFS BUILT UP POST", else (legend 7) by the
              shear wall schedule
  beams       double dash-dot lines (box beams, legend 4 "(2) 800S162-118 BOX
              BEAM U.O.N."), sized by a parallel label ("(2) 10SW10") where one
              is printed; a beam inside a wall is a HEADER
  joists      span symbols (a dash-dot line with a hook at each end) marked
              with the legend's mark ("1" = 8J12 @ 16" O.C.)
  hold-downs  NOT drawn on the plans. S-302 detail B: "S/HD8S HOLDOWN AT EACH
              END MEMBER" - so the zone is each end member of each shear wall
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from lib import plan_registration as reg
from lib import plan_sheet as PS
from lib.plan_derive import title_ordinal
from lib.plans.level_suggestion import tokens_in

#: the stored rows' shape; bump when a row's meaning changes
EMIT_VERSION = 1
#: where a pass would write them (designed, not written - see `rows_for_store`)
COLLECTION = "plan_structural"

# ══════════════════════════════════════════════════════════════════════════
# 1. Pairing: title level + set-wide series offset
# ══════════════════════════════════════════════════════════════════════════

#: an NCS sheet number: discipline, type digit (1 = plans; plumbing draws its
#: sanitary plans as 2xx), sequence; the revision suffix is ignored
PLAN_SERIES = re.compile(r"^([A-Z])-(\d)(\d\d)(?:\.(\d\d))?$")


def title_level(title: Optional[str]) -> Optional[str]:
    """The ONE level a sheet title names - FLOOR_<n>, MEZZANINE, ROOF,
    BULKHEAD - or None.

    Read by the closed token table every level reader in this codebase uses
    (plans.level_suggestion.tokens_in). A numbered floor must ALSO be the
    title's single printed ordinal (plan_derive.title_ordinal): tokens_in
    reads "FIRST AND SECOND FLOOR PLANS" as FLOOR_2, which is not one level.
    Two levels ("ROOF AND BULKHEAD PLAN"), none ("FLOOR PLAN") or a below-
    grade title ("FIRST UNDERGROUND FLOOR") is None: the sheet refuses."""
    toks, _ = tokens_in(str(title or ""))
    if len(toks) != 1:
        return None
    lv = toks[0]
    if lv.startswith("FLOOR_") and title_ordinal(title) != int(lv[6:]):
        return None
    return lv


def plan_index(sheet_number: Optional[str], series: str = "1") -> Optional[Tuple[str, int]]:
    """("S", 4) for S-104.00: discipline and position in the `series`xx
    sheets (1xx plans by default)."""
    m = PLAN_SERIES.match(str(sheet_number or "").strip().upper())
    return (m.group(1), int(m.group(3))) if m and m.group(2) == series else None


def pair_by_level(pages: Sequence[dict], *, disc: str = "S", arch: str = "A",
                  series: str = "1") -> Dict[str, Any]:
    """{"offset": k | None, "pairs": [{"s", "a", "level"}], "refused":
    [{"page", "reason"}]} for every `disc` plan in the track.

    THE RULE (operator 2026-10-26), applied as written:
      - a sheet's level is its title's (`title_level`); unparsed -> refused
      - its partner is THE architectural plan titled the same level; none,
        or more than one -> refused (never picked between)
      - the set-wide offset k (S index = A index + k) is the one MORE THAN
        HALF of the level-matched sheets agree on; a sheet whose partner sits
        at another offset breaks it -> refused. No majority -> every sheet
        refuses: the set does not state one series rule.
    Two pages of one sheet number in the track (two revisions) -> refused.
    `series` is the `disc` sheets' type digit (the A side is always its 1xx
    plans): T4 pairs plumbing's P-2xx sanitary plans with series="2"."""
    plans = defaultdict(list)
    for p in pages:
        sn = p.get("sheet_number")
        ix = plan_index(sn, series) if str(sn or "").upper().startswith(disc) else plan_index(sn)
        if ix:
            plans[ix[0]].append((ix[1], p))
    refused: List[dict] = []
    a_by_level: Dict[str, List[Tuple[int, dict]]] = defaultdict(list)
    for i, p in plans.get(arch, []):
        lv = title_level(p.get("sheet_title"))
        if lv:
            a_by_level[lv].append((i, p))
    numbers = defaultdict(int)
    for i, p in plans.get(disc, []):
        numbers[i] += 1
    matched = []
    for i, p in sorted(plans.get(disc, []), key=lambda t: t[0]):
        sn, title = p.get("sheet_number"), p.get("sheet_title")
        if numbers[i] > 1:
            refused.append({"page": p, "reason": f"{numbers[i]} pages of {sn} in this track: "
                                                 "which one governs is not decided here"})
            continue
        lv = title_level(title)
        if lv is None:
            refused.append({"page": p, "reason": f"{sn}'s title {title!r} does not name one level"})
            continue
        cands = a_by_level.get(lv, [])
        if not cands:
            refused.append({"page": p, "reason": f"no architectural plan in this track is titled "
                                                 f"{lv} ({sn} {title!r})"})
            continue
        if len(cands) > 1:
            refused.append({"page": p, "reason": f"{len(cands)} architectural plans are titled {lv}: "
                                                 + ", ".join(str(c[1].get('sheet_number')) for c in cands)})
            continue
        matched.append((i - cands[0][0], p, cands[0][1], lv))
    votes = defaultdict(int)
    for k, *_ in matched:
        votes[k] += 1
    offset = next((k for k, v in votes.items() if 2 * v > len(matched)), None)
    pairs = []
    for k, s, a, lv in matched:
        if offset is None:
            refused.append({"page": s, "reason": "the set states no series offset: "
                                                 + ", ".join(f"{v} sheet(s) at {k:+d}" for k, v in sorted(votes.items()))})
        elif k != offset:
            refused.append({"page": s, "reason": f"{s.get('sheet_number')} ({lv}) would pair with "
                                                 f"{a.get('sheet_number')}, {k:+d} in the series; the set's "
                                                 f"offset is {offset:+d}"})
        else:
            pairs.append({"s": s, "a": a, "level": lv})
    return {"offset": offset, "pairs": pairs, "refused": refused}


# ══════════════════════════════════════════════════════════════════════════
# 2. Registration: only the offset, and a check that can fail
# ══════════════════════════════════════════════════════════════════════════

#: the census and the one offset rule live in plan_sheet (operator ruling
#: 2026-10-28: ONE function for every discipline pair); these names stay so
#: callers of this module read them here too
peak_census = PS.peak_census


def register_pair(arch: dict, struct: dict, *, coarse_pt: Optional[float] = None,
                  span_pt: float = 360.0) -> dict:
    """plan_sheet.register_offset - the shared rule (R1 the offset is the
    exact census' best peak, R2 that peak is single, R3 MIN_ANCHORS), with
    the margin reported. The S-only wall check is `wall_check`, applied by
    run_track once the sheet's walls are read."""
    return PS.register_offset(arch, struct, coarse_pt=coarse_pt, span_pt=span_pt)


#: a structural wall face lies ON an architectural wall line within this
#: (operator 2026-10-28: "within 2pt")
WALL_ON_PT = 2.0
#: S wall faces are sampled every this many pt; the share is of LENGTH
FACE_STEP_PT = 1.0
WALL_ELEMENTS = ("shear_wall", "bearing_wall")


def _arch_wall_points(arch_sheet: dict) -> np.ndarray:
    """Points every 0.5pt along the A plan's WALL-layer lines (plan_space_layers)."""
    from lib.plan_space_layers import role_of
    pts = []
    for (x1, y1, x2, y2), layer in arch_sheet.get("att") or ():
        if role_of(layer) != "wall":
            continue
        n = max(int(math.hypot(x2 - x1, y2 - y1) / 0.5), 1)
        t = np.linspace(0.0, 1.0, n + 1)
        pts.append(np.stack([x1 + t * (x2 - x1), y1 + t * (y2 - y1)], 1))
    return np.vstack(pts) if pts else np.zeros((0, 2))


def _wall_faces(elements: Sequence[dict]) -> np.ndarray:
    """Points every FACE_STEP_PT along the two long faces of every S shear
    and bearing wall (S display pt)."""
    pts = []
    for e in elements:
        if e["element"] not in WALL_ELEMENTS:
            continue
        x0, y0, x1, y1 = _bbox(e["polygon"])
        if (y1 - y0) >= (x1 - x0):
            ys = np.arange(y0, y1 + 1e-9, FACE_STEP_PT)
            pts += [np.stack([np.full_like(ys, x), ys], 1) for x in (x0, x1)]
        else:
            xs = np.arange(x0, x1 + 1e-9, FACE_STEP_PT)
            pts += [np.stack([xs, np.full_like(xs, y)], 1) for y in (y0, y1)]
    return np.vstack(pts) if pts else np.zeros((0, 2))


def wall_share(faces: np.ndarray, arch_walls: np.ndarray, d) -> float:
    """Share of the S wall-face length that lies within WALL_ON_PT of an A
    wall line once moved into A by -d."""
    if not len(faces) or not len(arch_walls):
        return 0.0
    from scipy.spatial import cKDTree
    dist, _ = cKDTree(arch_walls).query(faces - np.asarray(d, dtype=float),
                                        distance_upper_bound=WALL_ON_PT)
    return float(np.isfinite(dist).mean())


def with_wall_check(registration: dict, wc: dict) -> dict:
    """The S pair's verdict: the shared offset rule AND the wall check.
    A copy; the shared function's own fields are kept as they were."""
    rg = dict(registration, wall_share_best=wc["wall_share_best"],
              wall_share_second=wc["wall_share_second"], wall_length_pt=wc["wall_length_pt"],
              wall_check=wc["ok"])
    if not wc["ok"]:
        rg["refused"] = "; ".join(x for x in (rg.get("refused"), f"wall check: {wc['why']}") if x)
        rg["usable"] = False
    return rg


def wall_check(elements: Sequence[dict], arch_sheet: dict, registration: dict) -> dict:
    """THE S-ONLY INDEPENDENT CHECK (operator 2026-10-28): "after the offset,
    the share of S shear+bearing wall length lying on A-Wall lines (within
    2pt) ... refuse a pair where the runner-up peak's offset scores as well
    as the best. No tuned ratio threshold."

    A different reading from the anchor count: corners vote for an offset;
    this asks whether the STRUCTURE's walls then stand on the ARCHITECT'S
    walls, at the chosen offset and at the census' runner-up peak.
    {"wall_share_best", "wall_share_second", "wall_length_pt", "ok", "why"}."""
    faces = _wall_faces(elements)
    aw = _arch_wall_points(arch_sheet)
    out = {"wall_length_pt": round(len(faces) * FACE_STEP_PT, 1), "wall_share_best": None,
           "wall_share_second": None, "ok": False, "why": None}
    if registration.get("dx") is None or registration.get("second_peak") is None:
        out["why"] = "no registration to check"
        return out
    if not len(faces):
        out["why"] = "the S sheet has no shear or bearing wall to check"
        return out
    if not len(aw):
        out["why"] = "the A plan has no wall layer to check against"
        return out
    best = wall_share(faces, aw, (registration["dx"], registration["dy"]))
    second = wall_share(faces, aw, registration["second_peak"])
    out.update(wall_share_best=round(best, 4), wall_share_second=round(second, 4))
    if second >= best:
        out["why"] = (f"the runner-up peak ({registration['second_peak'][0]:.1f}, "
                      f"{registration['second_peak'][1]:.1f}) puts {second:.1%} of the S wall "
                      f"length on A walls, the offset {best:.1%}: the walls do not choose it")
    else:
        out["ok"] = True
    return out


# ══════════════════════════════════════════════════════════════════════════
# 3. Elements, in the S sheet's display space
# ══════════════════════════════════════════════════════════════════════════

AXIS_TOL_PT = 0.2          # a segment is horizontal/vertical within this
DASH_GAP_PT = 20.0         # a dash-dot line's gap: 18pt dash to dash across its dot (measured)
POST_MIN_PT, POST_MAX_PT = 6.0, 12.0   # a 4"-8" post at 1/4" = 1'-0"
TAG_REACH_PT = 24.0        # an SW tag beside its frame: measured 8-10pt; 16in
LEADER_REACH_PT = 9.0      # a leader stops at its arrowhead's base, ~7pt short of the post
LABEL_REACH_PT = 40.0      # a leader's far end to the size word of its label


def _bare(layer: str) -> str:
    return str(layer or "").split("|")[-1].upper()


def _is_wall_layer(layer):
    return "WALL" in _bare(layer)


def _is_hatch_layer(layer):
    return "HATCH" in _bare(layer)


def _is_beam_layer(layer, xref_only=True):
    b = _bare(layer)
    return ("JOIST" in b or "BEAM" in b) and (not xref_only or "|" in str(layer))


def _rect_poly(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _bbox(poly):
    a = np.asarray(poly, dtype=float)
    return float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max())


def _inside(r, x, y, pad=0.0):
    return r[0] - pad <= x <= r[2] + pad and r[1] - pad <= y <= r[3] + pad


def plan_extent(page) -> Optional[Tuple[float, float, float, float]]:
    """The framing plan's box: where its GRID LINES run - the MEDIAN start
    and end of the long grid lines each way - and above the view title
    printed under the plan ("4TH FLOOR FRAMING PLAN").

    The median, not the extreme: on S-106 one grid-layer line runs on down
    past the plan to a second, small view (the bulkhead's framing), and an
    extreme would take that view's beams and posts as the roof's. The
    legend's sample symbols (a wall rectangle on layer "Ext. Wall", a box
    beam, a hatch) sit below the view title."""
    segs = _axis_segments(page.drawings, lambda d: "GRID" in _bare(d["layer"]))
    lines = defaultdict(list)
    for o, c, lo, hi, _l in segs:
        lines[(o, round(c))].append((lo, hi))
    merged = {"h": [], "v": []}
    for (o, c), iv in lines.items():
        iv.sort()
        cur = list(iv[0])
        for lo, hi in iv[1:]:
            if lo <= cur[1] + DASH_GAP_PT:
                cur[1] = max(cur[1], hi)
            else:
                merged[o].append(tuple(cur))
                cur = [lo, hi]
        merged[o].append(tuple(cur))
    span = {}
    for o in ("h", "v"):
        if not merged[o]:
            return None
        top = max(hi - lo for lo, hi in merged[o])
        longs = [(lo, hi) for lo, hi in merged[o] if hi - lo >= 0.5 * top]
        span[o] = (float(np.median([lo for lo, _ in longs])), float(np.median([hi for _, hi in longs])))
    (x0, x1), (y0, y1) = span["h"], span["v"]
    from lib import plan_cells as pc
    tb = pc.title_block_edge(PS.display_segments(page), page.width, page.height)
    under = [y for t, x, y, *_r in page.directed_words
             if t.upper() == "FRAMING" and x < tb and y > y0]
    if under:
        y1 = min(y1, min(under) - 10.0)
    return x0, y0, min(x1, tb), y1


def _axis_segments(drawings, keep):
    """[(orient, c, lo, hi, layer)] for every axis-aligned straight item."""
    out = []
    for d in drawings:
        if not keep(d):
            continue
        for it in d["items"]:
            if it[0] != "l":
                continue
            (x1, y1), (x2, y2) = it[1], it[2]
            if abs(y1 - y2) <= AXIS_TOL_PT and abs(x2 - x1) > AXIS_TOL_PT:
                out.append(("h", (y1 + y2) / 2, min(x1, x2), max(x1, x2), d["layer"]))
            elif abs(x1 - x2) <= AXIS_TOL_PT and abs(y2 - y1) > AXIS_TOL_PT:
                out.append(("v", (x1 + x2) / 2, min(y1, y2), max(y1, y2), d["layer"]))
    return out


def bands(segs, gap_pt: float, min_sep: float, max_sep: float):
    """Pairs of parallel lines -> rectangles. Collinear pieces (a dashed or
    dash-dot line) merge across gaps up to `gap_pt`; each merged line pairs
    with its NEAREST parallel line `min_sep`..`max_sep` away that overlaps
    it, over the overlap. [(x0, y0, x1, y1, orient)]."""
    lines = defaultdict(list)
    for o, c, lo, hi, _l in segs:
        lines[(o, round(c * 2) / 2)].append((lo, hi))
    merged = []
    for (o, c), iv in lines.items():
        iv.sort()
        cur = list(iv[0])
        for lo, hi in iv[1:]:
            if lo <= cur[1] + gap_pt:
                cur[1] = max(cur[1], hi)
            else:
                merged.append((o, c, cur[0], cur[1]))
                cur = [lo, hi]
        merged.append((o, c, cur[0], cur[1]))
    out, used = [], set()
    for i, (o, c, lo, hi) in enumerate(merged):
        if i in used:
            continue
        best = None
        for j, (o2, c2, lo2, hi2) in enumerate(merged):
            if j == i or j in used or o2 != o or not (min_sep <= c2 - c <= max_sep):
                continue
            ov = min(hi, hi2) - max(lo, lo2)
            if ov <= 0:
                continue
            if best is None or c2 - c < best[0]:
                best = (c2 - c, j, max(lo, lo2), min(hi, hi2))
        if best:
            _, j, a, b = best
            used |= {i, j}
            c2 = merged[j][1]
            out.append((a, c, b, c2, "h") if o == "h" else (c, a, c2, b, "v"))
    return out


def _closed_rects(drawings, keep, ext):
    """Closed axis-aligned rectangles (a wall outline path), inside `ext`."""
    out = []
    for d in drawings:
        if not keep(d) or len(d["items"]) < 4:
            continue
        x0, y0, x1, y1 = d["rect"]
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        if ext and not (_inside(ext, x0, y0, 30) and _inside(ext, x1, y1, 30)):
            continue
        first, last = d["items"][0][1], d["items"][-1][-1]
        if math.dist(first, last) > 0.5:
            continue
        if all(it[0] == "l" and (abs(it[1][0] - it[2][0]) <= AXIS_TOL_PT
                                 or abs(it[1][1] - it[2][1]) <= AXIS_TOL_PT) for it in d["items"]):
            out.append((x0, y0, x1, y1, d["layer"]))
    return out


def _hatch_kind(rect, hatch_segs):
    """'braced_frame' (diagonals both ways), 'bearing_wall' (ticks across the
    wall), or None (no hatch) - by the hatch strokes whose midpoint is inside."""
    x0, y0, x1, y1 = rect
    vertical = (y1 - y0) > (x1 - x0)
    diag = {45: 0, 135: 0}
    across = along = 0
    for (ax, ay, bx, by) in hatch_segs:
        mx, my = (ax + bx) / 2, (ay + by) / 2
        if not _inside(rect, mx, my, 0.3):
            continue
        ang = round(math.degrees(math.atan2(by - ay, bx - ax))) % 180
        if 30 <= ang <= 60:
            diag[45] += 1
        elif 120 <= ang <= 150:
            diag[135] += 1
        elif (ang <= 5 or ang >= 175):
            across += vertical
            along += not vertical
        elif 85 <= ang <= 95:
            across += not vertical
            along += vertical
    if diag[45] >= 2 and diag[135] >= 2 and diag[45] + diag[135] > across:
        return "braced_frame", diag[45] + diag[135]
    if across >= 2:
        return "bearing_wall", across
    return None, 0


def _words_near_line(words, rect, orient, reach):
    """Words beside a band, parallel to it: projected inside its length and
    within `reach` of it."""
    x0, y0, x1, y1 = rect
    out = []
    for t, x, y, *_ in words:
        if orient == "v" and y0 <= y <= y1 and (x0 - reach <= x <= x1 + reach):
            out.append((t, x, y))
        if orient == "h" and x0 <= x <= x1 and (y0 - reach <= y <= y1 + reach):
            out.append((t, x, y))
    return out


_SW = re.compile(r"^SW-?(\d+)$")


def sw_tags(directed_words, ext) -> List[Tuple[str, float, float]]:
    """[("SW 1", x, y)] - "SW 1" (two words) or "SW-1", inside the plan."""
    out, w = [], list(directed_words)
    for i, (t, x, y, *_r) in enumerate(w):
        if ext and not _inside(ext, x, y, 30):
            continue
        m = _SW.match(t.upper())
        if m and m.group(1):
            out.append((f"SW {m.group(1)}", x, y))
        elif t.upper() == "SW" and i + 1 < len(w) and re.fullmatch(r"\d+", w[i + 1][0]) \
                and math.dist((x, y), w[i + 1][1:3]) < 20:
            nx, ny = w[i + 1][1:3]
            out.append((f"SW {w[i + 1][0]}", (x + nx) / 2, (y + ny) / 2))
    return out


def _dist_to_rect(r, x, y):
    dx = max(r[0] - x, 0, x - r[2])
    dy = max(r[1] - y, 0, y - r[3])
    return math.hypot(dx, dy)


def legend_entries(directed_words) -> List[dict]:
    """The plan legend's numbered items: [{"n", "text", "mark", "x", "y"}].
    An item is "<n>. ... INDICATES <text>" on one line; its `mark` is a
    word printed in its sample symbol, between the number and INDICATES
    ("1" in the joist sample, "*" in the panel sample)."""
    w = list(directed_words)
    out = []
    for i, (t, x, y, *_r) in enumerate(w):
        if t.upper() != "INDICATES":
            continue
        line = [z for z in w if abs(z[2] - y) < 4.0 and z[1] < x and x - z[1] < 100]
        num = next((z for z in sorted(line, key=lambda z: z[1]) if re.fullmatch(r"\d+\.", z[0])), None)
        # a mark is a digit or a symbol ("1", "*"), never a word of a note
        # that runs past the sample ("TO")
        marks = [z[0] for z in w if num and num[1] < z[1] < x and abs(z[2] - y) < 14
                 and z[0] != num[0] and re.fullmatch(r"\d{1,2}|[^\w\s]", z[0])]
        txt = []
        for z in w[i + 1:i + 30]:
            if abs(z[2] - y) > 4.0 or z[1] < x:
                break
            if re.fullmatch(r"\d+\.", z[0]) and txt:
                break
            txt.append(z[0])
        out.append({"n": int(num[0][:-1]) if num else None, "text": " ".join(txt),
                    "mark": marks[0] if marks else None, "x": x, "y": y})
    return out


_POST_SIZE = re.compile(r"^\d+(?:J|SW)\d+$")
_BEAM_SIZE = re.compile(r"^\d+(?:J|SW|S)\d+(?:-\d+)?$")


def _posts(page, ext, exclude_layers):
    """Post symbols: clusters of small all-orthogonal paths whose union is a
    6"-8" square. [{"rect", "layer"}]."""
    small = []
    for d in page.drawings:
        L = d["layer"]
        if exclude_layers(L):
            continue
        x0, y0, x1, y1 = d["rect"]
        if x1 - x0 > POST_MAX_PT or y1 - y0 > POST_MAX_PT:
            continue
        if ext and not _inside(ext, (x0 + x1) / 2, (y0 + y1) / 2, 30):
            continue
        if not all(it[0] == "l" and (abs(it[1][0] - it[2][0]) <= AXIS_TOL_PT
                                     or abs(it[1][1] - it[2][1]) <= AXIS_TOL_PT)
                   for it in d["items"]):
            continue
        small.append([x0, y0, x1, y1, L, len(d["items"])])
    # union overlapping boxes per layer
    groups: List[list] = []
    for b in small:
        hit = [g for g in groups if g[4] == b[4] and not (b[0] > g[2] + 0.5 or b[2] < g[0] - 0.5
                                                          or b[1] > g[3] + 0.5 or b[3] < g[1] - 0.5)]
        if not hit:
            groups.append(list(b))
            continue
        g = hit[0]
        for o in hit[1:]:
            g[0], g[1], g[2], g[3] = min(g[0], o[0]), min(g[1], o[1]), max(g[2], o[2]), max(g[3], o[3])
            g[5] += o[5]
            groups.remove(o)
        g[0], g[1], g[2], g[3] = min(g[0], b[0]), min(g[1], b[1]), max(g[2], b[2]), max(g[3], b[3])
        g[5] += b[5]
    return [{"rect": tuple(g[:4]), "layer": g[4]} for g in groups
            if POST_MIN_PT <= g[2] - g[0] <= POST_MAX_PT and POST_MIN_PT <= g[3] - g[1] <= POST_MAX_PT
            and g[5] >= 10]


def _leaders(page, ext, layer_ok):
    """Open polylines (leader lines) on annotation layers: [(start, end)]."""
    out = []
    for d in page.drawings:
        if not layer_ok(d["layer"]):
            continue
        its = [it for it in d["items"] if it[0] == "l"]
        if not its:
            continue
        a, b = its[0][1], its[-1][-1]
        if math.dist(a, b) < 12:
            continue
        if ext and not (_inside(ext, *a, 60) and _inside(ext, *b, 60)):
            continue
        out.append((tuple(a), tuple(b)))
    return out


def _label_block(words, x, y, reach=LABEL_REACH_PT):
    """The size token printed at a leader's far end: nearest post/beam size
    word within `reach`, with the multiplier "(2)" before it."""
    best = None
    for i, (t, wx, wy, *_r) in enumerate(words):
        if _POST_SIZE.match(t) and math.dist((wx, wy), (x, y)) <= reach:
            d = math.dist((wx, wy), (x, y))
            if best is None or d < best[0]:
                prev = words[i - 1][0] if i and re.fullmatch(r"\(\d+\)", words[i - 1][0]) else None
                best = (d, f"{prev} {t}" if prev else t)
    return best[1] if best else None


def _joist_symbols(page, ext):
    """Span symbols: two hooks (an axis stroke + a ~43deg stroke) on one
    line, joined by its dashes. [{"a", "b", "orient", "layer"}]."""
    hooks = []
    for d in page.drawings:
        if not _is_beam_layer(d["layer"], xref_only=False) or "|" in d["layer"]:
            continue
        its = [it for it in d["items"] if it[0] == "l"]
        if len(its) != 2:
            continue
        x0, y0, x1, y1 = d["rect"]
        if ext and not _inside(ext, (x0 + x1) / 2, (y0 + y1) / 2, 10):
            continue
        ax = [it for it in its if abs(it[1][0] - it[2][0]) <= AXIS_TOL_PT or abs(it[1][1] - it[2][1]) <= AXIS_TOL_PT]
        dg = [it for it in its if it not in ax]
        if len(ax) != 1 or len(dg) != 1:
            continue
        (p, q) = ax[0][1], ax[0][2]
        orient = "v" if abs(p[0] - q[0]) <= AXIS_TOL_PT else "h"
        # the hook's tip: the axis stroke's end the diagonal meets (a half
        # arrowhead); its other end runs on toward the symbol's middle
        tip = min((p, q), key=lambda e: min(math.dist(e, dg[0][1]), math.dist(e, dg[0][2])))
        inner = q if tip is p else p
        hooks.append({"orient": orient, "c": p[0] if orient == "v" else p[1], "tip": tip,
                      "inner": inner, "layer": d["layer"]})
    out, used = [], set()
    for i, h in enumerate(hooks):
        if i in used:
            continue
        for j, g in enumerate(hooks):
            if j <= i or j in used or g["orient"] != h["orient"] or abs(g["c"] - h["c"]) > 0.5:
                continue
            k = 1 if h["orient"] == "v" else 0
            if math.dist(h["tip"], g["tip"]) > 200:   # one bay; never 2 symbols chained
                continue
            # the two hooks face each other: the tips are the symbol's ends
            if abs(h["tip"][k] - g["tip"][k]) < abs(h["inner"][k] - g["inner"][k]):
                continue
            used |= {i, j}
            out.append({"a": h["tip"], "b": g["tip"], "orient": h["orient"], "layer": h["layer"]})
            break
    return out


def _ray_bay(mid, supports, ext):
    """The rectangle between the nearest supports left/right/up/down of
    `mid`. None when a side meets nothing inside the plan."""
    x, y = mid
    left = [r[2] for r in supports if r[2] <= x and r[1] <= y <= r[3]]
    right = [r[0] for r in supports if r[0] >= x and r[1] <= y <= r[3]]
    up = [r[3] for r in supports if r[3] <= y and r[0] <= x <= r[2]]
    down = [r[1] for r in supports if r[1] >= y and r[0] <= x <= r[2]]
    if not (left and right and up and down):
        return None
    return (max(left), max(up), min(right), min(down))


def read_elements(page) -> Dict[str, Any]:
    """Every structural element on one framing plan, in ITS display space.
    `page` is a lib.plan_page.PlanPage. Returns {"elements": [...],
    "unassigned_tags": [...], "evidence": {...}} - an element is
    {"element", "polygon", "tag", "attrs", "evidence"}."""
    ext = plan_extent(page)
    words = list(page.directed_words)
    els: List[dict] = []
    hatch = [(it[1][0], it[1][1], it[2][0], it[2][1]) for d in page.drawings
             if _is_hatch_layer(d["layer"]) for it in d["items"] if it[0] == "l"]
    # ── walls: closed outlines; else dashed (drawn below) bands ─────────
    walls = []
    for x0, y0, x1, y1, L in _closed_rects(page.drawings, lambda d: _is_wall_layer(d["layer"]), ext):
        kind, n = _hatch_kind((x0, y0, x1, y1), hatch)
        walls.append({"rect": (x0, y0, x1, y1), "layer": L, "kind": kind, "hatch": n,
                      "drawn_as": "below" if "BELOW" in _bare(L) else "at_level"})
    dashed = [s for s in _axis_segments(page.drawings, lambda d: _is_wall_layer(d["layer"])
                                        and "BELOW" in _bare(d["layer"]))
              if not ext or _inside(ext, (s[2] + s[3]) / 2 if s[0] == "h" else s[1],
                                    s[1] if s[0] == "h" else (s[2] + s[3]) / 2, 30)]
    for x0, y0, x1, y1, o in bands(dashed, DASH_GAP_PT, 3.0, 15.0):
        if any(_inside(w["rect"], (x0 + x1) / 2, (y0 + y1) / 2) for w in walls):
            continue
        walls.append({"rect": (x0, y0, x1, y1), "layer": dashed[0][4], "kind": None, "hatch": 0,
                      "drawn_as": "below"})
    # ── SW tags -> the nearest wall beside them ─────────────────────────
    # ONE TAG, ONE FRAME: a wall two tags reach is refused for both (the
    # roof plan draws the A-line walls below as one dashed run, and SW 4 and
    # SW 6 both sit beside it - where one ends is not drawn)
    tags = sw_tags(words, ext)
    unassigned = []
    claims: Dict[int, list] = defaultdict(list)
    for t, x, y in tags:
        cands = sorted(((_dist_to_rect(w["rect"], x, y), k) for k, w in enumerate(walls)))
        cands = [(d, k) for d, k in cands if d <= TAG_REACH_PT
                 and (walls[k]["kind"] in ("braced_frame", None))]
        if not cands:
            unassigned.append({"tag": t, "x": x, "y": y, "why": "no braced frame within "
                                                                 f"{TAG_REACH_PT:.0f}pt"})
            continue
        claims[cands[0][1]].append((t, x, y))
    for k, got in claims.items():
        if len({t for t, *_ in got}) > 1:
            for t, x, y in got:
                unassigned.append({"tag": t, "x": x, "y": y, "why": "one wall, tags "
                                   + " and ".join(sorted({g[0] for g in got}))
                                   + ": where one ends is not drawn"})
            continue
        t, x, y = got[0]
        walls[k]["tag"], walls[k]["tag_xy"] = t, (x, y)
    for w in walls:
        r = w["rect"]
        if w.get("tag"):
            element = "shear_wall"
        elif w["kind"] == "braced_frame":
            element = "braced_frame"
        elif w["kind"] == "bearing_wall":
            element = "bearing_wall"
        else:
            element = "wall"
        els.append({"element": element, "polygon": _rect_poly(*r), "tag": w.get("tag"),
                    "attrs": {"system": "cfs_braced_frame" if w["kind"] == "braced_frame" else w["kind"],
                              "drawn_as": w["drawn_as"],
                              "length_in": round(PS.inches(max(r[2] - r[0], r[3] - r[1])), 1),
                              "thickness_in": round(PS.inches(min(r[2] - r[0], r[3] - r[1])), 1)},
                    "evidence": {"layer": w["layer"], "hatch_strokes": w["hatch"],
                                 "label_xy": list(w["tag_xy"]) if w.get("tag") else None}})
    # ── posts, sized by leader ──────────────────────────────────────────
    hatch_or_wall = lambda L: _is_hatch_layer(L) or _is_wall_layer(L) or "GRID" in _bare(L) \
        or "DIMENSION" in _bare(L) or "STAIR" in _bare(L)          # noqa: E731
    posts = _posts(page, ext, hatch_or_wall)
    leaders = _leaders(page, ext, lambda L: "TEXT" in _bare(L) and "|" not in L)
    for p in posts:
        r = p["rect"]
        size, via = None, None
        for a, b in leaders:
            for near, far in ((a, b), (b, a)):
                if _dist_to_rect(r, *near) <= LEADER_REACH_PT:
                    s = _label_block(words, *far)
                    if s:
                        size, via = s, "leader"
            if size:
                break
        els.append({"element": "post", "polygon": _rect_poly(*r), "tag": None,
                    "attrs": {"size": size, "size_from": via},
                    "evidence": {"layer": p["layer"]}})
    # ── beams and headers ───────────────────────────────────────────────
    legend = legend_entries(words)
    beam_default = next((e["text"] for e in legend if "BEAM" in e["text"].upper()), None)
    bsegs = _axis_segments(page.drawings, lambda d: _is_beam_layer(d["layer"]))
    if ext:
        bsegs = [s for s in bsegs if _inside(ext, (s[2] + s[3]) / 2 if s[0] == "h" else s[1],
                                             s[1] if s[0] == "h" else (s[2] + s[3]) / 2, 30)]
    beams = bands(bsegs, DASH_GAP_PT, 3.0, 12.0)
    for x0, y0, x1, y1, o in beams:
        r = (x0, y0, x1, y1)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # a HEADER lies along a wall, inside it end to end; a beam that only
        # ends in a wall bears on it
        host = next((w for w in walls if _inside(w["rect"], x0, y0, 0.5)
                     and _inside(w["rect"], x1, y1, 0.5)), None)
        near = [t for t, *_ in _words_near_line(words, r, o, 14.0) if _BEAM_SIZE.match(t)]
        size = near[0] if near else None
        els.append({"element": "header" if host else "beam", "polygon": _rect_poly(*r), "tag": None,
                    "attrs": {"size": size, "size_from": "label" if size else
                              ("legend U.O.N." if beam_default else None),
                              "default": beam_default, "orient": o,
                              "length_in": round(PS.inches(max(x1 - x0, y1 - y0)), 1)},
                    "evidence": {"layer": bsegs[0][4] if bsegs else None}})
    # ── joists: span symbols, the legend's mark, the bay they span ──────
    supports = [w["rect"] for w in walls] + [b[:4] for b in beams]
    for s in _joist_symbols(page, ext):
        (ax, ay), (bx, by) = s["a"], s["b"]
        mid = ((ax + bx) / 2, (ay + by) / 2)
        mark = None
        for t, x, y, *_r in words:
            if len(t) <= 2 and math.dist((x, y), mid) < 30 and (
                    (s["orient"] == "v" and abs(x - ax) < 12) or (s["orient"] == "h" and abs(y - ay) < 12)):
                mark = t
                break
        spec = next((e for e in legend if mark and e["mark"] == mark), None)
        spec_txt = spec["text"] if spec else None
        m = re.search(r"(\d+J\d+(?:\([^)]*\))?)", spec_txt or "")
        sp = re.search(r"@\s*(\d+)\"?\s*O\.C\.", spec_txt or "")
        bay = _ray_bay(mid, supports, ext)
        poly = _rect_poly(*bay) if bay else [[ax, ay], [bx, by]]
        els.append({"element": "joist_bay" if bay else "joist_span",
                    "polygon": poly, "tag": mark,
                    "attrs": {"direction": "vertical" if s["orient"] == "v" else "horizontal",
                              "span_line": [list(s["a"]), list(s["b"])],
                              "size": m.group(1) if m else None,
                              "spacing_in": int(sp.group(1)) if sp else None,
                              "legend": spec_txt},
                    "evidence": {"layer": s["layer"], "bay": "supports either side" if bay else
                                 "no support found on every side: the span line only"}})
    return {"elements": els, "unassigned_tags": unassigned,
            "evidence": {"plan_extent": ext, "legend": legend}}


def hold_down_zones(elements: List[dict], spec: Optional[List[dict]] = None) -> List[dict]:
    """One zone per END of every shear wall: the post drawn there (inside or
    touching the wall's end), else the wall's end square (its thickness by
    its thickness). Hold-downs are not drawn on the plans; S-302 detail B
    puts one "AT EACH END MEMBER"."""
    posts = [e for e in elements if e["element"] == "post"]
    out = []
    for w in elements:
        if w["element"] != "shear_wall":
            continue
        x0, y0, x1, y1 = _bbox(w["polygon"])
        vertical = (y1 - y0) > (x1 - x0)
        t = min(x1 - x0, y1 - y0)
        ends = ([(x0, y0, x1, y0 + t), (x0, y1 - t, x1, y1)] if vertical
                else [(x0, y0, x0 + t, y1), (x1 - t, y0, x1, y1)])
        for k, e in enumerate(ends):
            ex, ey = (e[0] + e[2]) / 2, (e[1] + e[3]) / 2
            p = min(posts, key=lambda p: math.dist(((_bbox(p["polygon"])[0] + _bbox(p["polygon"])[2]) / 2,
                                                    (_bbox(p["polygon"])[1] + _bbox(p["polygon"])[3]) / 2),
                                                   (ex, ey)), default=None)
            use_post = p is not None and _dist_to_rect(_bbox(p["polygon"]), ex, ey) <= t
            poly = p["polygon"] if use_post else _rect_poly(*e)
            out.append({"element": "hold_down", "polygon": poly, "tag": w["tag"],
                        "attrs": {"end": ("top" if k == 0 else "bottom") if vertical else
                                  ("left" if k == 0 else "right"),
                                  "zone_from": "post at the end member" if use_post else "wall end square",
                                  "spec": spec or None},
                        "evidence": {"of": w["tag"], "rule": "S-302 detail: hold-down at each end member"}})
    return out


# ══════════════════════════════════════════════════════════════════════════
# 4. The shear wall schedule (a ruled table) and the hold-down notes
# ══════════════════════════════════════════════════════════════════════════

def read_shear_wall_schedule(page) -> Dict[str, Any]:
    """{"rows": {(level, "SW n"): {field: text}}, "evidence"} from a ruled
    table headed FLOOR | SHEAR WALL n (END MEMBERS, STUDS, TOP AND BOTTOM
    MEMBERS, DIAGONALS). A merged cell (no rule between rows in its column)
    applies to every row it spans - the drawn rules decide, not the text."""
    words = list(page.directed_words)
    floor = next(((x, y) for t, x, y, *_r in words if t.upper() == "FLOOR"
                  and any(z[0].upper() == "SHEAR" and abs(z[2] - y) < 40 and z[1] > x for z in words)), None)
    if not floor:
        return {"rows": {}, "evidence": "no FLOOR | SHEAR WALL table"}
    H, V = [], []
    for d in page.drawings:
        for it in d["items"]:
            if it[0] != "l":
                continue
            (x1, y1), (x2, y2) = it[1], it[2]
            if abs(y1 - y2) <= AXIS_TOL_PT and abs(x2 - x1) > 5:
                H.append((y1, min(x1, x2), max(x1, x2)))
            elif abs(x1 - x2) <= AXIS_TOL_PT and abs(y2 - y1) > 5:
                V.append((x1, min(y1, y2), max(y1, y2)))
    fx, fy = floor
    # the table: vertical rules that cross the FLOOR header's row
    xs = sorted({round(x, 1) for x, lo, hi in V if lo - 2 <= fy <= hi + 2})
    left = max((x for x in xs if x < fx), default=None)
    if left is None:
        return {"rows": {}, "evidence": "no rule left of FLOOR"}
    top = min(lo for x, lo, hi in V if round(x, 1) == left)
    bottom = max(hi for x, lo, hi in V if round(x, 1) == left)
    # the table's own rules end where it ends; a title block's run on
    cols = sorted({round(x, 1) for x, lo, hi in V if x >= left - 0.1
                   and lo >= top - 2 and hi <= bottom + 2 and lo - 2 <= fy <= hi + 2})
    inside = lambda t: cols[0] - 1 <= t[1] <= cols[-1] + 1 and top - 1 <= t[2] <= bottom + 1  # noqa: E731
    tw = [w for w in words if inside(w)]

    def bands_at(xc):
        ys = sorted({round(y, 1) for y, lo, hi in H if lo - 1 <= xc <= hi + 1 and top - 1 <= y <= bottom + 1})
        return list(zip(ys, ys[1:]))

    def col_of(x):
        for i, (a, b) in enumerate(zip(cols, cols[1:])):
            if a <= x <= b:
                return i
        return None

    def cell_text(ci, band):
        a, b = cols[ci], cols[ci + 1]
        got = [w for w in tw if a <= w[1] <= b and band[0] <= w[2] <= band[1]]
        got.sort(key=lambda w: (round(w[2]), w[1]))
        return " ".join(w[0] for w in got)

    # row labels: column 0's bands below the header
    head = [z for z in tw if z[0].upper() == "SHEAR" and col_of(z[1]) is not None]
    # a group header spans its sub-columns: each sub-column takes the group to its left
    group_x = sorted(((z[1], f"SW {tw[tw.index(z) + 2][0]}") for z in head
                      if tw.index(z) + 2 < len(tw) and tw[tw.index(z) + 1][0].upper() == "WALL"
                      and re.fullmatch(r"\d+", tw[tw.index(z) + 2][0])))
    fields = {}
    rows_by_level = {}
    for band in bands_at((cols[0] + cols[1]) / 2):
        txt = cell_text(0, band)
        lv = title_level(txt) or (txt.upper() if txt.upper() in ("ROOF", "BULKHEAD", "MEZZANINE") else None)
        if lv:
            rows_by_level[lv] = band
    out: Dict[Tuple[str, str], Dict[str, str]] = defaultdict(dict)
    first_row = min((b[0] for b in rows_by_level.values()), default=None)
    for ci in range(1, len(cols) - 1):
        cx = (cols[ci] + cols[ci + 1]) / 2
        if not group_x or first_row is None:
            continue
        # a group header ("SHEAR WALL n") is centred over its sub-columns
        grp = min(group_x, key=lambda g: abs(g[0] - cx))[1]
        cb = bands_at(cx)
        hb = next((b for b in cb if abs(b[1] - first_row) <= 1.0), None)
        sub = cell_text(ci, hb) if hb else ""
        fields[ci] = sub
        for lv, (ry0, ry1) in rows_by_level.items():
            rc = (ry0 + ry1) / 2
            b = next((b for b in cb if b[0] <= rc <= b[1]), None)
            if b is None:
                continue
            t = cell_text(ci, b)
            if t:
                out[(lv, grp)][sub] = t
    return {"rows": dict(out), "evidence": {"columns": len(cols) - 1, "levels": list(rows_by_level),
                                            "walls": sorted({g for _x, g in group_x}),
                                            "fields": sorted(set(fields.values()))}}


def read_hold_down_notes(page) -> List[dict]:
    """The hold-down callouts a detail sheet prints: [{"text", "detail", "x",
    "y"}] - the whole callout block (the lines run on 11pt apart) around a
    line holding HOLD DOWN / HOLDOWN, and the detail title nearest below it
    ("DETAIL A"). S-302: "SIMPSON TENSION TIE S/HD8S HOLDOWN AT EACH END
    MEMBER" (detail B, at the footing) and "SIMPSON STORNGTIE SHDU 11
    TENSIONS HOLD DOWN TYP. CONNECT TO EACH STUD IN END MEMBER" (detail A,
    at a floor)."""
    w = list(page.directed_words)
    out = []
    for i, (t, x, y, *_r) in enumerate(w):
        if not (t.upper() in ("HOLDOWN", "HOLD-DOWN") or (t.upper() == "HOLD" and i + 1 < len(w)
                                                          and w[i + 1][0].upper().startswith("DOWN"))):
            continue
        near = [z for z in w if abs(z[1] - x) < 120]
        ys = sorted({round(z[2], 1) for z in near})
        block = [round(y, 1)]
        for step in (-1, 1):
            cur = round(y, 1)
            for _ in range(3):
                nxt = [v for v in ys if 0 < (v - cur) * step <= 13.0]
                if not nxt:
                    break
                cur = min(nxt, key=lambda v: abs(v - cur))
                block.append(cur)
        lines = []
        for v in sorted(block):
            lines += sorted((z for z in near if abs(z[2] - v) < 1.0), key=lambda z: z[1])
        det = [(z[2] - y, w[k + 1][0]) for k, z in enumerate(w[:-1]) if z[0].upper() == "DETAIL"
               and 0 < z[2] - y < 700 and abs(z[1] - x) < 400 and re.fullmatch(r"[A-Z]", w[k + 1][0])]
        out.append({"text": " ".join(z[0] for z in lines),
                    "detail": f"DETAIL {min(det)[1]}" if det else None, "x": x, "y": y})
    return out


# ══════════════════════════════════════════════════════════════════════════
# 5. A track: pair, register, read, move into the A frame, rows
# ══════════════════════════════════════════════════════════════════════════

def size_posts_from_schedule(els: List[dict]) -> None:
    """LEGEND 7: "BUILT UP POST, SEE SHEAR WALL SCHEDULE FOR SIZE, U.O.N. ON
    PLAN" - a post with no label of its own, standing in a shear wall, is
    that wall's scheduled END MEMBERS at this level. Anywhere else the
    schedule names no size for it, and none is given. In place."""
    for e in els:
        if e["element"] != "post":
            continue
        cx = sum(x for x, _ in e["polygon"]) / len(e["polygon"])
        cy = sum(y for _, y in e["polygon"]) / len(e["polygon"])
        host = next((w for w in els if w["element"] == "shear_wall"
                     and _inside(_bbox(w["polygon"]), cx, cy, 0.5)), None)
        e["attrs"]["in_shear_wall"] = host["tag"] if host else None
        if e["attrs"].get("size") or not host:
            continue
        sched = host["attrs"].get("schedule") or {}
        em = next((v for k, v in sched.items() if k.upper().startswith("END")), None)
        if em:
            e["attrs"].update(size=em, size_from=f"shear wall schedule, {host['tag']} end members")


def to_arch(polygon, registration) -> Optional[List[List[float]]]:
    """S display pt -> A display pt (S = A + d, so A = S - d), or None when
    the registration is not usable."""
    if not registration or not registration.get("usable"):
        return None
    dx, dy = registration["dx"], registration["dy"]
    return [[round(x - dx, 2), round(y - dy, 2)] for x, y in polygon]


def _page_ref(p: dict) -> dict:
    return {k: p.get(k) for k in ("page_id", "file_id", "file_name", "page_number",
                                  "sheet_number", "sheet_title", "file_hash")}


def run_track(pages: Sequence[dict], open_page: Callable[[dict], Any], *,
              track: Optional[str] = None, borrowed_from: Optional[str] = None) -> Dict[str, Any]:
    """Every structural element of one drawing track, as rows. `pages` are
    the track's index rows (sheet_number, sheet_title, page_id, ...) and
    `open_page(row)` a PlanPage - plan_glyph_pass.run_pass's contract.

    A PAIR IS USABLE when the shared offset rule holds (plan_sheet.
    register_offset) AND the S-only wall check does (`wall_check`).

    `borrowed_from` names the track the S sheets came from when this
    track has none of its own (`run_tracks`): every row then says so.

    THE ENTRY POINT. Nothing in the server calls it yet: it writes nothing,
    and a pass that stores its rows waits for the operator (see the PR)."""
    pairing = pair_by_level(pages)
    rows: List[dict] = []
    schedule: Dict[Tuple[str, str], dict] = {}
    hold_notes: List[dict] = []
    for p in pages:
        sn = str(p.get("sheet_number") or "")
        title = str(p.get("sheet_title") or "").upper()
        if sn.startswith("S-") and "SHEAR WALL" in title and "SCHEDULE" in title:
            pg = open_page(p)
            try:
                got = read_shear_wall_schedule(pg)
                for k, v in got["rows"].items():
                    schedule.setdefault(k, dict(v, _sheet=sn))
                for h in read_hold_down_notes(pg):
                    hold_notes.append(dict(h, sheet=sn))
            finally:
                pg.close()
    summary = {"track": track, "offset": pairing["offset"], "pairs": [], "refused": [],
               "schedule_rows": len(schedule)}
    for r in pairing["refused"]:
        summary["refused"].append({"sheet": r["page"].get("sheet_number"), "reason": r["reason"]})
    for pr in pairing["pairs"]:
        s, a, lv = pr["s"], pr["a"], pr["level"]
        spg, apg = open_page(s), open_page(a)
        try:
            ssheet, asheet = PS.load_sheet(spg), PS.load_sheet(apg)
            rg = dict(register_pair(asheet, ssheet))
            got = read_elements(spg)
            wc = wall_check(got["elements"], asheet, rg)
        finally:
            spg.close()
            apg.close()
        rg = with_wall_check(rg, wc)
        els = got["elements"]
        els += hold_down_zones(els, [{"text": h["text"], "detail": h["detail"], "sheet": h["sheet"]}
                                     for h in hold_notes])
        for e in els:
            if e["element"] == "shear_wall":
                e["attrs"]["schedule"] = schedule.get((lv, e["tag"]))
        size_posts_from_schedule(els)
        summary["pairs"].append({"s": s.get("sheet_number"), "a": a.get("sheet_number"), "level": lv,
                                 "registration": rg, "elements": len(els),
                                 "unassigned_tags": got["unassigned_tags"]})
        for e in els:
            pa = to_arch(e["polygon"], rg)
            rows.append({"emit_version": EMIT_VERSION, "track": track, "level": lv,
                         "element": e["element"], "tag": e["tag"],
                         "label": f"{s.get('sheet_number')} {e['tag'] or e['element']}"
                                  + (f" ({e['element'].replace('_', ' ')})" if e["tag"] else ""),
                         "s_sheet": _page_ref(s), "a_sheet": _page_ref(a),
                         "polygon_s": [[round(x, 2), round(y, 2)] for x, y in e["polygon"]],
                         "polygon_a": pa,
                         "placement": "placed" if pa is not None else "refused",
                         "refused": None if pa is not None else (rg.get("refused") or "not registered"),
                         "registration": {k: rg.get(k) for k in (
                             "dx", "dy", "anchors", "best_peak_anchors", "second_peak_anchors", "margin",
                             "wall_share_best", "wall_share_second", "usable")},
                         "structure_note": structure_note(s, track, borrowed_from),
                         "attrs": e["attrs"], "evidence": e["evidence"]})
    return {"rows": rows, "summary": summary, "schedule": {f"{k[0]}|{k[1]}": v for k, v in schedule.items()},
            "hold_down_notes": hold_notes}


#: what every row borrowed into the owner's set says (operator, 2026-10-28,
#: verbatim but for the sheet number): "structure per filed set S-1xx; the
#: owner's set has no structural sheets"
OWNER_SET_NOTE = "structure per filed set {sheet}; the owner's set has no structural sheets"


def structure_note(s_page: dict, track: Optional[str], borrowed_from: Optional[str]) -> Optional[str]:
    """None for a track's own structure; the borrowed-structure label else."""
    if not borrowed_from:
        return None
    sheet = s_page.get("sheet_number")
    if track == "post_co" and borrowed_from == "filed":
        return OWNER_SET_NOTE.format(sheet=sheet)
    return (f"structure per {borrowed_from} set {sheet}; the {track} set has no "
            f"structural sheets")


def _structural_pages(pages: Sequence[dict]) -> List[dict]:
    return [p for p in pages if str(p.get("sheet_number") or "").upper().startswith("S-")]


def run_tracks(tracks: Sequence[Tuple[str, List[dict]]], open_page: Callable[[dict], Any],
               *, source: str = "filed") -> Dict[str, Dict[str, Any]]:
    """run_track per drawing track (server._glyph_pages' (track, pages)).

    A TRACK WITH NO STRUCTURAL SHEETS USES `source`'S (operator 2026-10-28):
    the owner's post-CO set prints no S sheet, so its plans are read against
    the filed set's S-1xx - and every row says "structure per filed set
    S-1xx; the owner's set has no structural sheets"."""
    by = {t: list(ps) for t, ps in tracks}
    out = {}
    for t, ps in tracks:
        own = _structural_pages(ps)
        if own or t == source or source not in by:
            out[t] = run_track(ps, open_page, track=t)
        else:
            borrowed = [p for p in _structural_pages(by[source])
                        if str(p.get("page_id")) not in {str(q.get("page_id")) for q in ps}]
            out[t] = run_track(list(ps) + borrowed, open_page, track=t, borrowed_from=source)
    return out


def _plain(v):
    """A row as BSON takes it: numpy scalars and tuples become Python ones."""
    return json.loads(json.dumps(v, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def rows_for_store(rows: Iterable[dict], *, project_id: str, company_id: Optional[str]) -> List[dict]:
    """The stored shape (collection COLLECTION, one document per element):
    {record_type: "structure", project_id, company_id, ...row}. The join key
    for clash is (track, a_sheet.page_id) and polygon_a's frame is that A
    page's display space - the frame every other trade's registered rows
    use."""
    return [_plain(dict(r, record_type=RECORD_STRUCTURE, project_id=str(project_id),
                        company_id=company_id)) for r in rows]


#: one stored row per structural element, one per track saying what the
#: track's pairing and registrations were (never silent: a track with no
#: pair says why), and one marker when the step failed
RECORD_STRUCTURE = "structure"
RECORD_TRACK = "structure_track"
RECORD_UNAVAILABLE = "structure_unavailable"


def track_row(track: str, result: Dict[str, Any], *, project_id: str,
              company_id: Optional[str]) -> dict:
    """What one track's structure step did: its pairs (registration with the
    margin and the wall check), its refusals, its row count, and - for a
    track that borrowed its structure - the label every row carries."""
    s = result.get("summary") or {}
    notes = sorted({r.get("structure_note") for r in result.get("rows") or [] if r.get("structure_note")})
    return _plain({"record_type": RECORD_TRACK, "project_id": str(project_id), "company_id": company_id,
                   "emit_version": EMIT_VERSION, "track": track, "offset": s.get("offset"),
                   "pairs": [{"s": p["s"], "a": p["a"], "level": p["level"],
                              "elements": p["elements"], "unassigned_tags": p["unassigned_tags"],
                              "registration": {k: (p["registration"] or {}).get(k) for k in (
                                  "dx", "dy", "anchors", "best_peak_anchors", "second_peak_anchors",
                                  "margin", "wall_share_best", "wall_share_second", "usable", "refused")}}
                             for p in s.get("pairs") or []],
                   "refused": s.get("refused") or [], "rows": len(result.get("rows") or []),
                   "structure_notes": notes})


def pass_rows(tracks: Sequence[Tuple[str, List[dict]]], open_page: Callable[[dict], Any], *,
              project_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
    """THE GLYPH PASS'S STRUCTURE STEP (server._plan_glyph_pass): every
    track's rows as stored, plus one track row each. Pure; the server
    replaces the project's COLLECTION with them."""
    out = run_tracks(tracks, open_page)
    rows: List[dict] = []
    for t, _pages in tracks:
        res = out.get(t) or {}
        rows += rows_for_store(res.get("rows") or [], project_id=project_id, company_id=company_id)
        rows.append(track_row(t, res, project_id=project_id, company_id=company_id))
    return {"rows": rows, "by_track": {t: len((out.get(t) or {}).get("rows") or []) for t, _ in tracks}}


def unavailable(error: BaseException, when, *, project_id: str) -> dict:
    """The one row a failed structure step writes: the pass's other rows
    stand, and the collection says the structure was not read - an empty
    collection only ever means "not yet run"."""
    return {"record_type": RECORD_UNAVAILABLE, "project_id": str(project_id),
            "emit_version": EMIT_VERSION, "error": f"{type(error).__name__}: {error}"[:500],
            "at": when}


__all__ = [
    "EMIT_VERSION", "COLLECTION", "title_level", "plan_index", "pair_by_level",
    "peak_census", "register_pair", "read_elements", "hold_down_zones",
    "read_shear_wall_schedule", "read_hold_down_notes", "size_posts_from_schedule",
    "to_arch", "run_track", "run_tracks", "plan_extent", "wall_check", "wall_share", "with_wall_check",
    "structure_note", "OWNER_SET_NOTE", "pass_rows", "track_row", "unavailable",
    "RECORD_STRUCTURE", "RECORD_TRACK", "RECORD_UNAVAILABLE",
    "rows_for_store", "bands", "legend_entries", "sw_tags",
]
