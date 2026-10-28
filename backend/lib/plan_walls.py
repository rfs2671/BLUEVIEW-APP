"""Walls by type: linear feet of each wall type, read from the plan's own wall
layer, the wall-type tags, and the viewport's VERIFIED scale.

Operator's spec (Roy, 2026-10-28): "Walls by type: length (LF) per wall type
per apartment/floor/building from the A-Wall layer + wall-type tags +
verified scale, reconciled with the partition types on A-500. Refuse where
scale doesn't verify or a wall carries no type. Render every wall colored by
type for by-eye check."

    floor_walls(page, scale_sheet=..., space=..., widest_door_in=...)
                                  one plan: every wall, its type or refusal
    partition_types(words)        the wall / partition types A-500 defines
    reconcile(plan_tags, table)   the plans' tags against that table
    floor_of(title)               the level a plan's title names, or None
    render(page, result, path)    every wall coloured by type (by-eye check)

MEASURED ON 588 BOYLAND, 2026-10-28 (bv-worktrees/T1_walls_measure.md), all
A plans of AR 3.28.25, AR 8.18.26, the owner's post-CO set and SET_UPDATED:

  A WALL IS TWO FACES. The wall layer (NCS major group WALL, the same layer
  plan_space_layers validates) draws each wall as two parallel face lines,
  its hatch as diagonals, and an exterior wall's skins (EPS, sheathing) as
  extra lines under an inch apart against its outer face. So along each axis,
  at every stretch where the set of covering lines is constant, the lines
  are walked across the axis: a line within LAYER_GAP_IN of the previous one
  is the same face's skin; the next line beyond is the far face, and the two
  are a wall when MIN_T_IN <= thickness <= the legend's thickest wall plus
  THICK_MARGIN_IN. The wall's length is the stretch's length: measured along
  the wall, between faces, never a centreline guessed through a corner.

  ONE WALL ACROSS A JOINT. Collinear pieces of one thickness are one wall
  (a RUN) across a gap the drawing explains - a T junction (a perpendicular
  wall's band fills the gap), one face running on through it, a doorway
  (door or glazing geometry in a gap no wider than the widest scheduled
  door) or a drafting gap under an inch. Nothing else joins two pieces: a
  corridor between two walls on one line is not a wall.

  THE TAG IS A DIAMOND WITH A LEADER. Wall-type tags (W1, P3, ...) are the
  words inside a diamond drawn on the WALL TAGS layer; the diamond's leader
  - an axis-aligned line from one of its corners - runs to the wall it names
  and ends on that wall's far face. A tag names the wall its leader ends in
  (or crosses); a tag with no leader names the one wall its diamond touches.
  A tag that names no wall, or two, is unattached and listed.

  A RUN TAKES ITS TAG'S TYPE. Two tags of different types on one run (the
  stair wall P1 that continues past the stair as corridor wall P2) cut it
  at the ONE joint between them; if more than one joint lies between them,
  where the type changes is not on the drawing and the pieces between are
  refused (AMBIGUOUS), never split by a guess.

  REFUSED, NEVER COUNTED:
    * a wall in a viewport whose scale did not verify (plan_scale) - no
      length can be stated for it at all;
    * a wall no tag reaches (UNTYPED): listed, with its length and where it
      is, and counted in no type - "untyped" is not a type;
    * a wall between two differently-typed tags with no single joint to cut
      at (AMBIGUOUS).

  A PIECE SHORTER THAN IT IS THICK is a jamb or a junction square: it joins
  the run whose END it touches (its first or last stretch); touching none,
  two, or a joint inside a run, it is listed as a short piece and counted
  nowhere.

The lengths in a run's figure:
    drawn_lf     where both faces are drawn
    joint_lf     the explained joints inside it (T junctions, one-face
                 stretches, drafting gaps) and its absorbed end pieces
    opening_lf   doorways bridged inside it - reported, NOT in lf
    lf           drawn_lf + joint_lf
A CORNER IS WHAT THE FACES SAY. Where both walls stop at the other's
face (A-101.00's four corners), the square has one face per axis, no band:
it is in neither figure. Where one wall's both faces run into the square
(A-100.00's east corners, where the side wall begins below an opening), it
is that wall's end: W2 there is 70'-0" less ONE W1 = 69'-2". A wall abutting
another stops at its face; a wall running through a T keeps the square.

Pure of the database and of R2. Nothing here writes.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from lib.plan_space_layers import role_of

# ── constants (inches are REAL inches, converted by the viewport's scale) ──

#: A face line shorter than this is hatch or a symbol stroke, not a wall face.
#: The exterior walls' stucco hatch is 1.7" strokes; the thinnest wall's end
#: cap (P3, 4") is 4".
MIN_FACE_IN = 2.0
#: The thinnest wall (plan_space_layers.pair_fraction uses the same floor).
MIN_T_IN = 2.0
#: Lines closer than this to the previous one are one face's skins: the
#: exterior walls draw EPS / sheathing / finish 0.3"-0.8" apart. The thinnest
#: wall core on A-500 (P3, 2 1/2" studs) is far wider.
LAYER_GAP_IN = 1.0
#: The thickest wall is the legend's thickest plus this (a drawn 12" concrete
#: wall with its finish).
THICK_MARGIN_IN = 2.0
#: Two pieces are one wall's when their centres and thicknesses agree this
#: closely (the drawing is exact: measured spread 0.0" on every Boyland run).
CENTER_TOL_IN = 0.5
THICK_TOL_IN = 0.5
#: A gap no wider than this is a drafting gap.
SMALL_GAP_IN = 1.0
#: How far beyond a face the apartment on that side is read, and how often.
SIDE_PROBE_IN = 3.0
SAMPLE_STEP_IN = 6.0
#: A coordinate equal within this many points is the same line.
EPS_PT = 0.05

#: A-500's heading sits right of its diamond (measured: 67pt) and 13pt above
#: the diamond's centre.
HEAD_REACH_PT = 100.0
HEAD_DROP_PT = 20.0
#: A cell with no tag to its right ends this far from its diamond (A-500's
#: cells are 324pt wide).
CELL_FALLBACK_PT = 320.0

WALL_TAG_LAYER = re.compile(r"(?i)(?:^|\|)(?:[A-Z]-)?WALL[ _-]?TAGS?$")
TAG_TEXT = re.compile(r"^[A-Z]{1,2}\d{1,2}[A-Z]?$")

TYPED, UNTYPED, AMBIGUOUS = "typed", "untyped", "ambiguous"
INTERIOR, DEMISING, PERIMETER, NO_APARTMENT = "interior", "demising", "perimeter", "no apartment"


# ── geometry ───────────────────────────────────────────────────────────────

@dataclass
class Piece:
    """A stretch of one wall: band [s, e] across the axis, span [a, b] along
    it, in points. axis "h" runs along x (band in y); "v" along y."""
    axis: str
    s: float
    e: float
    a: float
    b: float
    vp: int = -1

    @property
    def c(self) -> float:
        return (self.s + self.e) / 2

    @property
    def t(self) -> float:
        return self.e - self.s

    @property
    def length(self) -> float:
        return self.b - self.a

    def rect(self) -> Tuple[float, float, float, float]:
        return (self.a, self.s, self.b, self.e) if self.axis == "h" else (self.s, self.a, self.e, self.b)


def wall_lines(page) -> Dict[str, List[Tuple[float, float, float]]]:
    """{"h": [(y, x0, x1)], "v": [(x, y0, y1)]} - the axis-aligned straight
    segments on every wall-role layer (plan_space_layers.role_of)."""
    out: Dict[str, List[Tuple[float, float, float]]] = {"h": [], "v": []}
    for d in page.drawings:
        if role_of(d.get("layer")) != "wall":
            continue
        for it in d["items"]:
            if it[0] != "l":
                continue
            (x1, y1), (x2, y2) = it[1], it[2]
            if abs(x2 - x1) < 0.1 and abs(y2 - y1) > 0:
                out["v"].append((x1, min(y1, y2), max(y1, y2)))
            elif abs(y2 - y1) < 0.1 and abs(x2 - x1) > 0:
                out["h"].append((y1, min(x1, x2), max(x1, x2)))
    return out


def bands(lines: Sequence[Tuple[float, float, float]], ppi: float,
          max_t_in: float) -> List[Tuple[float, float, float, float]]:
    """[(s, e, a, b)] wall pieces along one axis (see the module note)."""
    L = [(c, a, b) for c, a, b in lines if b - a >= MIN_FACE_IN * ppi - EPS_PT]
    if not L:
        return []
    arr = np.array(L, dtype=float)
    bps = np.unique(np.round(np.concatenate([arr[:, 1], arr[:, 2]]), 3))
    gap, lo_t, hi_t = LAYER_GAP_IN * ppi, MIN_T_IN * ppi, max_t_in * ppi
    raw = []
    for u, v in zip(bps[:-1], bps[1:]):
        if v - u < EPS_PT:
            continue
        m = (arr[:, 1] <= u + EPS_PT) & (arr[:, 2] >= v - EPS_PT)
        cs = np.unique(np.round(arr[m, 0], 2))
        i, n = 0, len(cs)
        while i < n:
            start = last = cs[i]
            j = i + 1
            while j < n and cs[j] - last < gap:
                last = cs[j]
                j += 1
            if j >= n:
                break
            far = cs[j]
            if lo_t <= far - start <= hi_t:
                end, k = far, j + 1
                while k < n and cs[k] - end < gap:
                    end = cs[k]
                    k += 1
                raw.append((float(start), float(end), float(u), float(v)))
                i = k
            else:
                i = j
    raw.sort(key=lambda r: (round(r[0], 1), round(r[1], 1), r[2]))
    out: List[List[float]] = []
    for s, e, u, v in raw:
        if out and abs(out[-1][0] - s) < 0.1 and abs(out[-1][1] - e) < 0.1 \
                and u - out[-1][3] <= 2 * EPS_PT:
            out[-1][3] = v
        else:
            out.append([s, e, u, v])
    return [tuple(x) for x in out]


def opening_boxes(page) -> List[Tuple[float, float, float, float]]:
    """The bounding box of every door / glazing SUBPATH. A CAD path operator
    holds thousands of unrelated strokes; its drawing rect can span the sheet
    (it joined two bedroom walls 29 feet apart across the stair, measured)."""
    from lib.plan_sheet import symbol_objects
    out = []
    for o in symbol_objects(page):
        if role_of(o.get("layer")) in ("door", "glaz") and o.get("points"):
            xs = [p[0] for p in o["points"]]
            ys = [p[1] for p in o["points"]]
            out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


# ── tags ───────────────────────────────────────────────────────────────────

def read_tags(page) -> List[Dict[str, Any]]:
    """[{"text", "x", "y", "box", "leader", "end"}] - every diamond drawn on
    a WALL TAGS layer, the words inside it (joined: "W 1" is W1) and its
    leader: the longest axis-aligned line on that layer that starts at one of
    the diamond's corners and ends outside it. `end` is the leader's far end;
    both None when the diamond has no leader."""
    diag, axial = [], []
    for d in page.drawings:
        if not WALL_TAG_LAYER.search(d.get("layer") or ""):
            continue
        for it in d["items"]:
            if it[0] != "l":
                continue
            (x1, y1), (x2, y2) = it[1], it[2]
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            if dx > 2 and dy > 2 and abs(dx - dy) < 0.15 * max(dx, dy):
                diag.append((x1, y1, x2, y2))
            elif (dx < 0.1) != (dy < 0.1) and max(dx, dy) > 1:
                axial.append((x1, y1, x2, y2))
    parent = list(range(len(diag)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    ends = defaultdict(list)
    for i, (x1, y1, x2, y2) in enumerate(diag):
        for p in ((x1, y1), (x2, y2)):
            ends[(round(p[0]), round(p[1]))].append(i)
    for (kx, ky), ids in ends.items():
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                for j in ends.get((kx + ddx, ky + ddy), ()):
                    parent[find(j)] = find(ids[0])
    groups = defaultdict(list)
    for i in range(len(diag)):
        groups[find(i)].append(diag[i])
    words = list(page.words)
    tags = []
    for g in groups.values():
        xs = [v for s in g for v in (s[0], s[2])]
        ys = [v for s in g for v in (s[1], s[3])]
        box = (min(xs), min(ys), max(xs), max(ys))
        if len(g) < 4 or box[2] - box[0] < 8 or box[3] - box[1] < 8:
            continue
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        hw = (box[2] - box[0]) / 2
        inside = sorted((w for w in words if abs(w[1] - cx) + abs(w[2] - cy) <= hw * 1.02),
                        key=lambda w: w[1])
        text = re.sub(r"\s+", "", "".join(w[0] for w in inside)).upper()
        corners = [(cx, box[1]), (cx, box[3]), (box[0], cy), (box[2], cy)]
        leader = end = None
        best = 0.0
        for x1, y1, x2, y2 in axial:
            for (px, py), (qx, qy) in (((x1, y1), (x2, y2)), ((x2, y2), (x1, y1))):
                outside = not (box[0] - 1 <= qx <= box[2] + 1 and box[1] - 1 <= qy <= box[3] + 1)
                if outside and any(abs(px - vx) < 1.0 and abs(py - vy) < 1.0 for vx, vy in corners):
                    ln = abs(qx - px) + abs(qy - py)
                    if ln > best:
                        best, leader, end = ln, (px, py, qx, qy), (qx, qy)
        tags.append({"text": text, "x": cx, "y": cy, "box": box, "leader": leader, "end": end})
    tags.sort(key=lambda t: (round(t["y"], 1), round(t["x"], 1)))
    return tags


def attach(tag: Dict[str, Any], pieces: Sequence[Piece]) -> Tuple[Optional[int], str]:
    """(index of the piece the tag names, how) or (None, why not)."""
    tol = 1.0
    if tag.get("leader"):
        px, py, qx, qy = tag["leader"]
        vertical = abs(qx - px) < 0.1
        axis = "h" if vertical else "v"          # a leader runs ACROSS its wall
        coord, along = (qy, qx) if vertical else (qx, qy)
        hits = [i for i, p in enumerate(pieces) if p.axis == axis
                and p.s - tol <= coord <= p.e + tol and p.a - tol <= along <= p.b + tol]
        if len(hits) == 1:
            return hits[0], "leader ends in it"
        if len(hits) > 1:
            return None, f"its leader ends in {len(hits)} walls"
        lo, hi = sorted((py, qy)) if vertical else sorted((px, qx))
        hits = [i for i, p in enumerate(pieces) if p.axis == axis
                and p.e >= lo - tol and p.s <= hi + tol and p.a - tol <= along <= p.b + tol]
        if len(hits) == 1:
            return hits[0], "leader crosses it"
        return None, (f"its leader reaches {len(hits)} walls" if hits else "its leader reaches no wall")
    x0, y0, x1, y1 = tag["box"]
    hits = []
    for i, p in enumerate(pieces):
        r = p.rect()
        if r[0] <= x1 and r[2] >= x0 and r[1] <= y1 and r[3] >= y0:
            hits.append(i)
    if len(hits) == 1:
        return hits[0], "diamond on it"
    return None, f"no leader, and the diamond touches {len(hits)} walls"


# ── runs ───────────────────────────────────────────────────────────────────

def join_runs(pieces: Sequence[Piece], ppi: float, openings: Sequence[tuple],
              lines: Dict[str, Sequence[tuple]], max_t_in: float,
              widest_door_in: Optional[float]) -> Tuple[List[int], List[Tuple[int, int, str, float]]]:
    """(run id per piece, joints [(i, j, why, gap_in)]): collinear pieces of
    one thickness joined across the gaps the drawing explains."""
    n = len(pieces)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    ctol, ttol, small = CENTER_TOL_IN * ppi, THICK_TOL_IN * ppi, SMALL_GAP_IN * ppi

    def face_covers(ax, c, g0, g1):
        for lc, la, lb in lines.get(ax, ()):
            if abs(lc - c) <= 0.25 and la <= g0 + 0.25 and lb >= g1 - 0.25:
                return True
        return False
    joints = []
    for x, p in enumerate(pieces):
        best = None
        for y, q in enumerate(pieces):
            if y == x or q.axis != p.axis or abs(q.c - p.c) > ctol or abs(q.t - p.t) > ttol \
                    or q.a < p.b - EPS_PT:
                continue
            if best is None or q.a < pieces[best].a:
                best = y
        if best is None:
            continue
        q = pieces[best]
        g0, g1 = p.b, q.a
        lo_s, hi_e = min(p.s, q.s), max(p.e, q.e)
        why = None
        if g1 - g0 <= small:
            why = "drafting gap"
        elif face_covers(p.axis, p.s, g0, g1) or face_covers(p.axis, p.e, g0, g1):
            why = "one face continues"
        elif g1 - g0 <= (max_t_in + THICK_TOL_IN) * ppi:
            for r in pieces:
                if r.axis != p.axis and r.s <= g0 + ctol and r.e >= g1 - ctol \
                        and r.a - ctol <= hi_e and r.b + ctol >= lo_s:
                    why = "junction"
                    break
        if why is None and widest_door_in and g1 - g0 <= (widest_door_in + 2.0) * ppi:
            gr = (g0, lo_s, g1, hi_e) if p.axis == "h" else (lo_s, g0, hi_e, g1)
            for b in openings:
                if b[0] < gr[2] and b[2] > gr[0] and b[1] < gr[3] and b[3] > gr[1]:
                    why = "opening"
                    break
        if why:
            parent[find(best)] = find(x)
            joints.append((x, best, why, (g1 - g0) / ppi))
    return [find(i) for i in range(n)], joints


def absorb_short(short: Sequence[Piece], pieces: Sequence[Piece], run_of: Sequence[int],
                 ppi: float) -> Tuple[List[Tuple[Piece, int]], List[Piece]]:
    """A piece shorter than it is thick touching an END of exactly one run -
    the run's first or last stretch, beyond it - its band inside that run's
    band widened by half a thickness, is that run's end (a jamb, a wall
    turning into a corner). One inside a run's extent is a joint's square,
    already in the run's joint length: left over, never counted twice.
    -> ([(short piece, index of the run's piece it ends)], left over)."""
    small = SMALL_GAP_IN * ppi
    ext: Dict[int, Tuple[float, float]] = {}
    for i, p in enumerate(pieces):
        lo, hi = ext.get(run_of[i], (p.a, p.b))
        ext[run_of[i]] = (min(lo, p.a), max(hi, p.b))
    got, left = [], []
    for q in short:
        hit: Dict[int, int] = {}
        for i, p in enumerate(pieces):
            if p.axis != q.axis:
                continue
            if not (q.s >= p.s - p.t / 2 - 0.25 and q.e <= p.e + p.t / 2 + 0.25):
                continue
            lo, hi = ext[run_of[i]]
            at_end = abs(q.a - p.b) <= small and abs(p.b - hi) <= EPS_PT
            at_start = abs(p.a - q.b) <= small and abs(p.a - lo) <= EPS_PT
            if at_end or at_start:
                hit[run_of[i]] = i
        if len(hit) == 1:
            got.append((q, next(iter(hit.values()))))
        else:
            left.append(q)
    return got, left


def split_types(ids: Sequence[int], pieces: Sequence[Piece], joints, tags_on: Dict[int, List[str]]
                ) -> List[Tuple[List[int], Optional[List[str]]]]:
    """[(piece ids, types)] - a run cut where its type changes (see the
    module note). types None: between two types with no single joint."""
    order = sorted(ids, key=lambda i: pieces[i].a)
    pos = {i: k for k, i in enumerate(order)}
    after = {}
    for i, j, why, _g in joints:
        if i in pos and j in pos:
            after[min(pos[i], pos[j])] = why
    tagged = sorted((pos[i], t) for i, ts in tags_on.items() if i in pos for t in ts)
    cuts, refused = set(), set()
    for (k1, t1), (k2, t2) in zip(tagged, tagged[1:]):
        if t1 == t2:
            continue
        cand = [k for k in range(k1, k2) if after.get(k) and after[k] != "drafting gap"]
        if len(cand) == 1:
            cuts.add(cand[0])
        else:
            refused.update(range(k1 + 1, k2))
            cuts.update({k1, k2 - 1})
    out, start = [], 0
    for c in sorted(cuts) + [len(order) - 1]:
        part = order[start:c + 1]
        start = c + 1
        if not part:
            continue
        if all(pos[i] in refused for i in part):
            out.append((part, None))
        else:
            out.append((part, sorted({t for i in part for t in tags_on.get(i, ())})))
    return out


# ── apartments ─────────────────────────────────────────────────────────────

def _unit_at(space, x, y):
    lo, cp = space["lo"], space["cell_pt"]
    r, c = int((y - lo[1]) / cp), int((x - lo[0]) / cp)
    for t, mask in sorted((space.get("units") or {}).items()):
        if 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and mask[r, c]:
            return t
    return None


def scope_of(u1: Optional[str], u2: Optional[str]) -> Tuple[str, List[str]]:
    """Which apartments a wall belongs to, by what lies on its two sides."""
    if u1 and u1 == u2:
        return INTERIOR, [u1]
    if u1 and u2:
        return DEMISING, sorted([u1, u2])
    if u1 or u2:
        return PERIMETER, [u1 or u2]
    return NO_APARTMENT, []


def apportion(space, ps: Sequence[Piece], ppi: float) -> Dict[str, float]:
    """{"interior|2A": fraction, "demising|2A+2B": ..., ...} of the pieces'
    drawn length, read SIDE_PROBE_IN beyond each face every SAMPLE_STEP_IN.
    The membership map (plan_space) is the apartment; a wall runs past
    several, so it is split, never given to the one it mostly bounds."""
    acc: Counter = Counter()
    off = SIDE_PROBE_IN * ppi
    tot = 0.0
    for q in ps:
        n = max(1, int(math.ceil(q.length / (SAMPLE_STEP_IN * ppi))))
        w = q.length / n
        for k in range(n):
            m = q.a + (k + 0.5) * w
            if q.axis == "h":
                u1, u2 = _unit_at(space, m, q.s - off), _unit_at(space, m, q.e + off)
            else:
                u1, u2 = _unit_at(space, q.s - off, m), _unit_at(space, q.e + off, m)
            sc, us = scope_of(u1, u2)
            acc[sc + "|" + "+".join(us)] += w
            tot += w
    return {k: v / tot for k, v in sorted(acc.items())} if tot else {}


# ── one plan ───────────────────────────────────────────────────────────────

def floor_walls(page, *, scale_sheet=None, space=None, widest_door_in: Optional[float] = None,
                legend_thickest_in: Optional[float] = None) -> Dict[str, Any]:
    """Every wall on one plan with its type, length and apartments, or the
    reason it has none. `page` is a lib.plan_page.PlanPage; `scale_sheet`
    its plan_scale.Sheet (read when None); `space` its plan_space map (no
    apartments when None); `widest_door_in` the door schedule's widest door
    (plan_derive.widest_door_in; None: no doorway joins two pieces)."""
    from lib import plan_scale
    from lib.plan_sheet import thickest_legend_wall_in

    out: Dict[str, Any] = {"refusal": None, "viewports": [], "walls": [], "by_type": {},
                           "untyped_lf": 0.0, "ambiguous_lf": 0.0, "tags": [], "unattached": [],
                           "short_pieces": [], "refused_viewports": [], "off_viewport_pt": 0.0}
    lines = wall_lines(page)
    if not lines["h"] and not lines["v"]:
        out["refusal"] = "no wall layer on this sheet"
        return out
    if legend_thickest_in is None:
        try:
            legend_thickest_in = thickest_legend_wall_in(page.words)
        except ValueError:
            out["refusal"] = "no wall legend on this sheet to bound a wall's thickness"
            return out
    max_t_in = legend_thickest_in + THICK_MARGIN_IN
    sheet = scale_sheet if scale_sheet is not None else plan_scale.read_sheet(page)
    by_vp: Dict[int, Dict[str, list]] = {}
    for ax, ls in lines.items():
        for c, a, b in ls:
            x, y = ((a + b) / 2, c) if ax == "h" else (c, (a + b) / 2)
            v = sheet.at(x, y)
            if v is None:
                out["off_viewport_pt"] += b - a
                continue
            by_vp.setdefault(sheet.viewports.index(v), {"h": [], "v": []})[ax].append((c, a, b))
    out["off_viewport_pt"] = round(out["off_viewport_pt"], 1)
    openings = opening_boxes(page)
    tags = read_tags(page)
    out["tags"] = [{"text": t["text"], "x": round(t["x"], 1), "y": round(t["y"], 1)} for t in tags]
    claimed = set()
    for k in sorted(by_vp):
        v = sheet.viewports[k]
        paper = sum(b - a for ax in "hv" for _c, a, b in by_vp[k][ax])
        out["viewports"].append({"title": v.title, "scale": v.scale_text, "verified": bool(v.verified),
                                 "refusal": v.refusal, "wall_line_paper_pt": round(paper, 1)})
        if not v.verified or not v.pt_per_in:
            out["refused_viewports"].append({
                "title": v.title, "bbox": [round(z, 1) for z in v.drawing_bbox],
                "why": "scale not verified: " + (v.refusal or "no verified scale"),
                "wall_line_paper_pt": round(paper, 1)})
            continue
        ppi = v.pt_per_in
        pieces = [Piece(ax, s, e, a, b, vp=k) for ax in ("h", "v")
                  for s, e, a, b in bands(by_vp[k][ax], ppi, max_t_in)]
        short = [p for p in pieces if p.length < p.t]
        pieces = [p for p in pieces if p.length >= p.t]
        run_of, joints = join_runs(pieces, ppi, openings, by_vp[k], max_t_in, widest_door_in)
        ends, short = absorb_short(short, pieces, run_of, ppi)
        out["short_pieces"] += [{"axis": q.axis, "rect": [round(z, 1) for z in q.rect()],
                                 "length_in": round(q.length / ppi, 1)} for q in short]
        tags_on: Dict[int, List[str]] = defaultdict(list)
        for ti, t in enumerate(tags):
            if ti in claimed:
                continue
            x0, y0, x1, y1 = v.drawing_bbox
            if not (x0 <= t["x"] <= x1 and y0 <= t["y"] <= y1):
                continue
            claimed.add(ti)
            i, how = attach(t, pieces)
            if i is None:
                out["unattached"].append({"text": t["text"], "x": round(t["x"], 1),
                                          "y": round(t["y"], 1), "why": how})
            else:
                tags_on[i].append(t["text"])
        runs: Dict[int, List[int]] = defaultdict(list)
        for i, r in enumerate(run_of):
            runs[r].append(i)
        for r in sorted(runs, key=lambda r: (pieces[runs[r][0]].axis, round(pieces[runs[r][0]].c, 1),
                                             min(pieces[i].a for i in runs[r]))):
            for part, types in split_types(runs[r], pieces, joints, tags_on):
                out["walls"].append(_wall(part, types, pieces, joints, ends, ppi, v, space, tags_on))
    for ti, t in enumerate(tags):
        if ti not in claimed:
            out["unattached"].append({"text": t["text"], "x": round(t["x"], 1), "y": round(t["y"], 1),
                                      "why": "outside every drawing with a verified scale"})
    by_type: Counter = Counter()
    for w in out["walls"]:
        if w["status"] == TYPED:
            by_type[w["type"]] += w["lf"]
        elif w["status"] == UNTYPED:
            out["untyped_lf"] += w["lf"]
        elif w["status"] == AMBIGUOUS:
            out["ambiguous_lf"] += w["lf"]
    out["by_type"] = {k: round(by_type[k], 2) for k in sorted(by_type)}
    out["untyped_lf"] = round(out["untyped_lf"], 2)
    out["ambiguous_lf"] = round(out["ambiguous_lf"], 2)
    out["figures"] = figures(out["by_type"], out["untyped_lf"], out["ambiguous_lf"])
    out["types_on_plan"] = sorted({t["text"] for t in tags if t["text"]})
    for i, w in enumerate(out["walls"], 1):
        w["id"] = i
    return out


def figures(by_type: Dict[str, float], untyped_lf: float, ambiguous_lf: float
            ) -> Dict[str, Dict[str, float]]:
    """THE FIGURES, AS RULED (Roy, 2026-10-28, question 52): each type is its
    TAGGED length, and every type's figure carries the untyped and ambiguous
    length of the same scope beside it - a wall no tag reaches may be any
    type, so no type's figure is ever said without it. There is NO all-walls
    total: one would fold the untyped walls into a sum that hides them.
    {type: {"tagged_lf", "untyped_lf_beside", "ambiguous_lf_beside"}}."""
    return {t: {"tagged_lf": round(lf, 2), "untyped_lf_beside": round(untyped_lf, 2),
                "ambiguous_lf_beside": round(ambiguous_lf, 2)}
            for t, lf in sorted(by_type.items())}


def _wall(part, types, pieces, joints, ends, ppi, v, space, tags_on) -> Dict[str, Any]:
    ps = [pieces[i] for i in part]
    inside = set(part)
    joint_in = Counter()
    for i, j, why, g in joints:
        if i in inside and j in inside:
            joint_in[why] += g
    end_in = sum(q.length / ppi for q, i in ends if i in inside)
    drawn = sum(q.length for q in ps) / ppi / 12
    joint = (joint_in["junction"] + joint_in["one face continues"] + joint_in["drafting gap"]
             + end_in) / 12
    w = {"axis": ps[0].axis, "center_pt": round(ps[0].c, 1),
         "from_pt": round(min(q.a for q in ps), 1), "to_pt": round(max(q.b for q in ps), 1),
         "thick_in": round(sum(q.t * q.length for q in ps) / sum(q.length for q in ps) / ppi, 2),
         "pieces": [[round(z, 1) for z in q.rect()] for q in ps],
         "drawn_lf": round(drawn, 2), "joint_lf": round(joint, 2),
         "opening_lf": round(joint_in["opening"] / 12, 2), "lf": round(drawn + joint, 2),
         "tags": sorted(t for i in part for t in tags_on.get(i, ())),
         "viewport": v.title}
    if types is None:
        w.update(status=AMBIGUOUS, type=None,
                 why="between two tags of different types, with no single joint to cut at")
    elif len(types) == 1:
        w.update(status=TYPED, type=types[0], why="")
    elif not types:
        w.update(status=UNTYPED, type=None, why="no wall-type tag reaches this wall")
    else:                                  # unreachable: split_types cuts every change
        w.update(status=AMBIGUOUS, type=None, why="tags of different types: " + ", ".join(types))
    if space is not None:
        w["apartments"] = {k: round(f * w["lf"], 2) for k, f in apportion(space, ps, ppi).items()}
    return w


# ── the level a plan is ────────────────────────────────────────────────────

def floor_of(sheet_title: Optional[str]) -> Optional[str]:
    """The ONE level the plan's title names (FLOOR_2, MEZZANINE, ROOF), or
    None. Floor identity comes from the sheet number and its title, never a
    registration fit (Roy's rule): a title that names no level - SET_UPDATED
    titles every plan "FLOOR PLAN" - or two, gives no floor."""
    from lib.plans.level_suggestion import tokens_in
    toks, _left = tokens_in(sheet_title or "")
    toks = sorted(set(toks))
    return toks[0] if len(toks) == 1 else None


# ── A-500: the types the set defines ───────────────────────────────────────

def _headings(ws):
    """[(kind, number, text, x, y)] for every "WALL TYPE <n>" / "PARTITION
    TYPE <n>" printed on one line."""
    out = []
    for t, x, y in ws:
        if t.upper() not in ("WALL", "PARTITION"):
            continue
        line = sorted((w for w in ws if abs(w[2] - y) <= 2 and x < w[1] <= x + 90), key=lambda w: w[1])
        if len(line) >= 2 and line[0][0].upper() == "TYPE" and re.fullmatch(r"\d{1,2}", line[1][0]):
            out.append((t.upper(), int(line[1][0]), f"{t.upper()} TYPE {line[1][0]}", x, y))
    return out


def partition_types(words: Sequence[Tuple[str, float, float]]) -> Dict[str, Dict[str, Any]]:
    """{tag: {"heading", "kind", "number", "description", "consistent"}} -
    every tag word (W1, P3) on a wall-type sheet with a heading "<WALL |
    PARTITION> TYPE <n>" beside it (to its right, within HEAD_REACH_PT
    across and HEAD_DROP_PT up or down: A-500 centres its diamond on the
    heading's three lines), and the line under that heading. `consistent`:
    the tag's letter and number agree with its heading (W - WALL,
    P - PARTITION). A tag with no heading beside it is not read."""
    ws = [(str(t), float(x), float(y)) for t, x, y in words]
    heads = _headings(ws)
    out: Dict[str, Dict[str, Any]] = {}
    for t, x, y in ws:
        tag = t.upper()
        if not TAG_TEXT.match(tag):
            continue
        near = sorted((math.hypot(hx - x, hy - y), k) for k, (_kd, _n, _tx, hx, hy) in enumerate(heads)
                      if 0 < hx - x <= HEAD_REACH_PT and abs(hy - y) <= HEAD_DROP_PT)
        if not near:
            continue
        kind, num, txt, hx, hy = heads[near[0][1]]
        # the cell: from the diamond to the next tag on its row
        nxt = [u[1] for u in ws if TAG_TEXT.match(u[0].upper()) and abs(u[2] - y) <= 4 and u[1] > x + 1]
        right = min(nxt) if nxt else x + CELL_FALLBACK_PT
        below = sorted((w for w in ws if 6 <= w[2] - hy <= 16 and x + 10 <= w[1] < right - 10),
                       key=lambda w: w[1])
        letter, digits = re.match(r"^([A-Z]+)(\d+)", tag).groups()
        out[tag] = {"heading": txt, "kind": kind.lower(), "number": num,
                    "description": " ".join(w[0] for w in below),
                    "consistent": int(digits) == num and letter[0] == kind[0]}
    return dict(sorted(out.items()))


def reconcile(plan_tags: Dict[str, Iterable[str]], table: Dict[str, Any]) -> Dict[str, Any]:
    """The plans' wall-type tags against the types a wall-type sheet defines.
    `plan_tags` {sheet label: tags read on it}. Every tag on a plan must be a
    type in the table, and every type in the table should be drawn somewhere
    - each is listed either way, never dropped."""
    on = defaultdict(set)
    for sheet, ts in plan_tags.items():
        for t in ts:
            if t:
                on[t].add(sheet)
    defined = set(table)
    return {"matched": sorted(set(on) & defined),
            "on_plans_not_in_table": {t: sorted(on[t]) for t in sorted(set(on) - defined)},
            "in_table_not_on_plans": sorted(defined - set(on)),
            "unreadable_tags_on": sorted({s for s, ts in plan_tags.items() if "" in set(ts)})}


# ── the by-eye check ───────────────────────────────────────────────────────

#: Colours a reader can tell apart; types beyond the palette cycle it.
PALETTE = [(20, 40, 140), (0, 120, 255), (0, 150, 0), (255, 140, 0), (170, 0, 220), (0, 190, 190),
           (150, 90, 40), (255, 0, 160), (0, 90, 60), (120, 120, 0), (90, 0, 90), (60, 60, 60)]
UNTYPED_RGB, AMBIGUOUS_RGB, REFUSED_RGB, SHORT_RGB = (230, 0, 0), (0, 0, 0), (170, 170, 170), (255, 220, 0)


def colours(types: Iterable[str]) -> Dict[str, Tuple[int, int, int]]:
    """One colour per type, by the type's sorted position: the same type has
    the same colour on every sheet rendered with the same list."""
    return {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(sorted(set(types)))}


def render(page, result: Dict[str, Any], path: str, *, title: str = "", dpi: int = 100,
           types: Optional[Iterable[str]] = None) -> str:
    """Every wall of `result` (floor_walls) on the faded sheet, filled in its
    type's colour; UNTYPED red, AMBIGUOUS black, walls of a refused viewport
    grey (their raw wall-layer lines: no scale, no wall), short pieces
    yellow; each tag outlined in its type's colour with its leader, an
    unattached tag in red. A key with each type's LF is drawn top left."""
    from PIL import Image, ImageDraw, ImageFont
    k = dpi / 72.0
    im = page.render((0, 0, page.width, page.height), dpi).convert("RGB")
    im = Image.blend(im, Image.new("RGB", im.size, "white"), 0.75)
    d = ImageDraw.Draw(im)
    col = colours(list(types or []) + [w["type"] for w in result["walls"] if w.get("type")])

    def box(r, fill):
        d.rectangle([r[0] * k, r[1] * k, r[2] * k, r[3] * k], fill=fill)
    for v in result.get("refused_viewports") or []:
        x0, y0, x1, y1 = v["bbox"]
        for ax, ls in wall_lines(page).items():
            for c, a, b in ls:
                xm, ym = ((a + b) / 2, c) if ax == "h" else (c, (a + b) / 2)
                if x0 <= xm <= x1 and y0 <= ym <= y1:
                    seg = [(a * k, c * k), (b * k, c * k)] if ax == "h" else [(c * k, a * k), (c * k, b * k)]
                    d.line(seg, fill=REFUSED_RGB, width=2)
    for w in result["walls"]:
        fill = (col.get(w["type"]) if w["status"] == TYPED else
                UNTYPED_RGB if w["status"] == UNTYPED else AMBIGUOUS_RGB)
        for r in w["pieces"]:
            box(r, fill)
    for q in result.get("short_pieces") or []:
        box(q["rect"], SHORT_RGB)
    bad = {(u["x"], u["y"]) for u in result.get("unattached") or []}
    for t in read_tags(page):
        x0, y0, x1, y1 = t["box"]
        c = UNTYPED_RGB if (round(t["x"], 1), round(t["y"], 1)) in bad else col.get(t["text"], UNTYPED_RGB)
        d.polygon([(t["x"] * k, y0 * k), (x1 * k, t["y"] * k), (t["x"] * k, y1 * k), (x0 * k, t["y"] * k)],
                  outline=c, width=3)
        if t["leader"]:
            a, b, cc, e = t["leader"]
            d.line([(a * k, b * k), (cc * k, e * k)], fill=c, width=3)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    y = 20
    d.text((20, y), title or "walls by type", fill=(0, 0, 0), font=font)
    y += 30
    rows = [(t, col[t], f"{t}: {lf:.1f} LF tagged (+{result['untyped_lf']:.1f} LF untyped on this plan)")
            for t, lf in result["by_type"].items()]
    rows += [("", UNTYPED_RGB, f"UNTYPED (no tag reaches it): {result['untyped_lf']:.1f} LF"),
             ("", AMBIGUOUS_RGB, f"AMBIGUOUS (type change not drawn): {result['ambiguous_lf']:.1f} LF"),
             ("", REFUSED_RGB, f"REFUSED (scale not verified): {len(result.get('refused_viewports') or [])} viewport(s)"),
             ("", SHORT_RGB, f"short pieces, counted nowhere: {len(result.get('short_pieces') or [])}")]
    for _t, c, text in rows:
        d.rectangle([20, y, 50, y + 20], fill=c)
        d.text((60, y), text, fill=(0, 0, 0), font=font)
        y += 26
    im.save(path)
    return path


# ── stored rows (the glyph pass's `walls` step; plan_glyph_pass) ──────────

#: Its own collection, like plan_areas: a wall row is no plan record, so
#: search never ranks it and the eval's record baseline does not move.
COLLECTION = "plan_walls"
RECORD_TYPE = "wall"
#: 1 (2026-10-28): first version.
WALLS_VERSION = 1
#: payload.kind of a row
WALL, REFUSED_VIEWPORT, REFUSED_SHEET, UNATTACHED_TAG = (
    "wall", "refused_viewport", "refused_sheet", "unattached_tag")
REFUSED, UNATTACHED = "refused", "unattached"
#: The page fields every row cites (plan_areas.CITE).
CITE = ("project_id", "company_id", "file_id", "file_hash", "file_name",
        "page_id", "page_number", "sheet_number", "sheet_title", "discipline")


def _in_box(x: float, y: float, b) -> bool:
    return b[0] <= x <= b[2] and b[1] <= y <= b[3]


def wall_rows(result: Dict[str, Any], page: Dict[str, Any], *,
              track: Optional[str] = None) -> List[Dict[str, Any]]:
    """The rows one plan writes (floor_walls' result, the page it cites):

      wall              one per wall (a run, or its part where the type
                        changes): status typed / untyped / ambiguous, its
                        type, lf (drawn + joints), drawn / joint / opening
                        LF, thickness, where it is, its tags, its apartments
      refused_viewport  one per drawing whose scale did not verify: no wall
                        in it has a length; the tags drawn in it are named
                        on this row, not one row each
      refused_sheet     the plan as a whole (no wall layer, no wall legend)
      unattached_tag    a tag that names no wall, in a drawing that verified

    Every row says its track and the plan's floor - the ONE level its title
    names (floor_of), or None. Nothing here is a total: a floor's or the
    building's figure is the sum of its typed rows, with its untyped rows'
    LF beside it (ruling 52)."""
    floor = floor_of(page.get("sheet_title"))
    base = {k: page.get(k) for k in CITE}

    def row(kind, status, **payload):
        return {**base, "record_type": RECORD_TYPE, "unit": None, "status": status,
                "payload": {"kind": kind, "track": track, "floor": floor,
                            "drawing_track": page.get("drawing_track"),
                            "drawing_track_label": page.get("drawing_track_label"),
                            "walls_version": WALLS_VERSION, **payload}}
    out: List[Dict[str, Any]] = []
    if result.get("refusal"):
        out.append(row(REFUSED_SHEET, REFUSED, why=result["refusal"]))
    scale = {v["title"]: v["scale"] for v in result.get("viewports") or []}
    for w in result.get("walls") or []:
        xs = [r[0] for r in w["pieces"]] + [r[2] for r in w["pieces"]]
        ys = [r[1] for r in w["pieces"]] + [r[3] for r in w["pieces"]]
        out.append(row(WALL, w["status"], wall_type=w.get("type"), lf=w["lf"],
                       drawn_lf=w["drawn_lf"], joint_lf=w["joint_lf"], opening_lf=w["opening_lf"],
                       thick_in=w["thick_in"], axis=w["axis"],
                       rect=[min(xs), min(ys), max(xs), max(ys)], pieces=w["pieces"],
                       tags=w["tags"], apartments=w.get("apartments"),
                       viewport=w.get("viewport"), scale_text=scale.get(w.get("viewport"), ""),
                       why=w.get("why") or ""))
    refused = result.get("refused_viewports") or []
    in_refused: Dict[int, List[str]] = defaultdict(list)
    for u in result.get("unattached") or []:
        k = next((i for i, v in enumerate(refused) if _in_box(u["x"], u["y"], v["bbox"])), None)
        if k is not None:
            in_refused[k].append(u["text"])
            continue
        out.append(row(UNATTACHED_TAG, UNATTACHED, tag=u["text"], at=[u["x"], u["y"]], why=u["why"]))
    for k, v in enumerate(refused):
        out.append(row(REFUSED_VIEWPORT, REFUSED, viewport=v["title"], rect=v["bbox"], why=v["why"],
                       wall_line_paper_pt=v["wall_line_paper_pt"],
                       tags_in_it=sorted(in_refused.get(k, []))))
    for i, r in enumerate(out):
        r["ordinal"] = i
    return out


__all__ = ["MIN_FACE_IN", "MIN_T_IN", "LAYER_GAP_IN", "THICK_MARGIN_IN", "CENTER_TOL_IN", "THICK_TOL_IN",
           "SMALL_GAP_IN", "TYPED", "UNTYPED", "AMBIGUOUS", "Piece", "wall_lines", "bands",
           "opening_boxes", "read_tags", "attach", "join_runs", "absorb_short", "split_types", "scope_of",
           "apportion", "floor_walls", "figures", "floor_of", "wall_rows", "COLLECTION", "RECORD_TYPE",
           "WALLS_VERSION", "WALL", "REFUSED_VIEWPORT", "REFUSED_SHEET", "UNATTACHED_TAG", "REFUSED", "UNATTACHED", "partition_types", "reconcile", "colours", "render"]
