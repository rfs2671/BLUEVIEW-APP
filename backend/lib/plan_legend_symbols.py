"""Counting a sheet's legend symbols: each swatch, matched to every drawing.

    count_sheet(page, ...) -> {"rows": [...], "legends": [...]}

The legend prints a swatch beside its meaning; the plan places that drawing
wherever the thing is. This lifts each swatch off the legend's own table and
compares it with EVERY connected object on the sheet, under translation,
scale, the four right-angle rotations and a mirror. Nothing is a model's
reading of a picture, and a swatch that does not resolve to exactly one
drawing - or that another row of the same legend also draws - is refused,
never guessed.

It is the second legend matcher in the repo, and the reason is the frame.
lib/plan_glyphs compares a cluster's segment set on a lattice of ITS OWN box,
x and y scaled apart: exact, fast, blind to rotation and mirror, and blind to
a letter inside a frame (S, V and ST in a stack circle are one aspect-free
signature away from each other). The stack symbols on JPW's P plans are
inserted mirrored and rotated, and are told apart ONLY by the letter.

HOW A CONNECTED OBJECT IS FORMED
================================

  1. Strokes: one per pen-down run of a painted path (lib.plan_page, display
     space). A Bezier is flattened to 8 points.
  2. A stroke longer than CAP_PT in either direction is structure - a wall, a
     pipe run, a table rule - and joins nothing.
  3. TOUCH: two strokes of ONE PEN (the same colour AND the same CAD layer)
     whose ink comes within LINK_PT are one object. The pen matters: on
     P-202.00 the stack circle (layer P-TEXT) is touched by its leader
     (layer 10 TEXT) and the leader by the vent pipe; joined, "the object"
     was the circle plus 50pt of pipe and it matched nothing.
  4. INSIDE: an object whose box lies wholly inside a bigger object's box,
     same pen, joins the smallest such object - the letter and the number
     inside a stack circle are the circle's.
  Each object keeps its PARTS (the touch-connected pieces of step 3), and the
  parts are what the score is made of.
  5. ONE-PLACE PIECES: a leader drawn in the symbol's OWN pen (P-101.00's
     W/5, layer P-TEXT - CW) touches it in one place. Every contact within
     ONE_PLACE_PT of one spot is cut, and each side - with the parts inside
     its box - is a candidate too. A diameter meets its circle a diameter
     apart, two places, and is never cut off.

WHAT IS NOT A CANDIDATE
=======================

  * the legend tables themselves (their boxes are excluded) - so a swatch
    never counts itself;
  * the title block (lib.plan_cells.title_block_edge);
  * schedules and details: the CALLER picks the sheets. A plan's own symbols
    are counted on plans (count_sheet is called with plan pages only), and a
    riser diagram or a detail sheet is not a plan.

THE MATCH
=========

Both drawings are centred on their boxes and scaled by their longer side (a
uniform scale: an aspect ratio is part of a shape). Each of the eight
transforms of the candidate is tried. EVERY PART IS SCORED AT ITS OWN SIZE:
the 95th-percentile distance from a part's ink to the other drawing's ink,
divided by the part's extent. Scored as one cloud, a 22pt circle outweighs
the 6pt letter inside it and S, V and ST all fit each other (measured
P-202.00: 0.07-0.08 for all three on every stack); per part, a true match
scores <= 0.02 and the nearest impostor 0.145.

A '#' in a swatch is the PRINTED placeholder for a number (STACK NO.): four
straight strokes, two horizontal, two parallel. Its slot is ignored in both
drawings, so S/1, S/2 and S/12 are all the sanitary stack.

A swatch with a real-text mark inside it (RCP-001.00's double square with
A, S, EX, D, P) is that mark's: a candidate counts only with the same mark
inside it. Two rows of one legend that draw the same thing and cannot be
told apart that way are both refused.

NOT A COUNTING SOURCE FOR THE CHAT GATE
=======================================

Counts bind in plan_search only from counting sources (COUNTING_BASES:
schedule QTY at its scope; located tallies checked against a census; printed
figures). A count here is one sheet's matches, unscoped, and its basis
`legend_symbol` is deliberately not one of them - exactly as `glyph_match`
is not (operator ruling 2026-10-07). See legend_count_rows for the rows a
pass would store; nothing here writes.
"""
from __future__ import annotations

import io
import math
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.spatial import cKDTree

#: A stroke longer than this (pt, either direction) is structure, never a symbol.
CAP_PT = 72.0
#: Two strokes of one pen this close (pt) touch.
LINK_PT = 0.5
#: A match: every part's 95th-percentile distance, over its own size, at most this.
TOL = 0.10
#: Reported beside the matches, never counted: scores up to NEAR_FACTOR * TOL.
NEAR_FACTOR = 2.0
#: Candidate box aspect (short/long side) within this fraction of the swatch's.
ASPECT_TOL = 0.20
#: Candidate size over swatch size, inclusive.
SCALE_MIN, SCALE_MAX = 0.33, 3.0
#: A part's own size, for scoring it, is never taken below this (of the object).
PART_FLOOR = 0.15
#: Cheap first look: coarse occupancy cover required both ways.
OCC_N, OCC_NEED = 16, 0.85
#: Two matches whose boxes agree within this (pt) are one drawing drawn twice.
TWICE_PT = 1.0

#: The eight transforms: four rotations, and each mirrored.
DIHEDRAL = [np.array(m, dtype=float) for m in (
    [[1, 0], [0, 1]], [[0, -1], [1, 0]], [[-1, 0], [0, -1]], [[0, 1], [-1, 0]],
    [[-1, 0], [0, 1]], [[0, 1], [1, 0]], [[1, 0], [0, -1]], [[0, -1], [-1, 0]])]
DIHEDRAL_NAMES = ["r0", "r90", "r180", "r270", "m", "m_r90", "m_r180", "m_r270"]

Box = Tuple[float, float, float, float]


# ══════════════════════════════════════════════════════════════════════════
# Strokes and connected objects
# ══════════════════════════════════════════════════════════════════════════

def _bez(p0, p1, p2, p3, n: int = 8) -> np.ndarray:
    t = np.linspace(0, 1, n)[:, None]
    a, b, c, d = map(np.asarray, (p0, p1, p2, p3))
    return ((1 - t) ** 3) * a + 3 * ((1 - t) ** 2) * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d


def _stroke(pts: np.ndarray, colour, layer, segs) -> Dict[str, Any]:
    return {"pts": pts, "colour": colour, "layer": layer or "",
            "box": (float(pts[:, 0].min()), float(pts[:, 1].min()),
                    float(pts[:, 0].max()), float(pts[:, 1].max())),
            "segs": segs}


def strokes_from_drawings(drawings: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One stroke per pen-down run of a painted path: {"pts", "colour",
    "layer", "box", "segs"}. `segs` lists each piece, a straight one as
    (p, q) and a curve as None (the '#' test reads it)."""
    out: List[Dict[str, Any]] = []
    for d in drawings:
        run: List[np.ndarray] = []
        segs: list = []
        for it in d["items"]:
            piece = (np.array([it[1], it[2]], dtype=float) if it[0] == "l"
                     else _bez(*it[1:5]))
            if run and np.abs(run[-1][-1] - piece[0]).max() > 1e-6:
                out.append(_stroke(np.vstack(run), d.get("colour"), d.get("layer"), segs))
                run, segs = [], []
            run.append(piece if not run else piece[1:])
            segs.append((tuple(piece[0]), tuple(piece[-1])) if it[0] == "l" else None)
        if run:
            out.append(_stroke(np.vstack(run), d.get("colour"), d.get("layer"), segs))
    return out


def _extent(b: Box) -> float:
    return max(b[2] - b[0], b[3] - b[1])


def _inside(b: Box, box: Box, pad: float = 0.0) -> bool:
    return (box[0] - pad <= b[0] and box[1] - pad <= b[1]
            and b[2] <= box[2] + pad and b[3] <= box[3] + pad)


def _dense(pts: np.ndarray, step: float) -> np.ndarray:
    out = [pts[:1]]
    for a, b in zip(pts[:-1], pts[1:]):
        k = max(1, int(math.ceil(float(np.hypot(*(b - a))) / step)))
        out.append(a + (b - a) * np.linspace(0, 1, k + 1)[1:, None])
    return np.vstack(out)


def _length(s: Dict[str, Any]) -> float:
    P = s["pts"]
    return float(np.hypot(*np.diff(P, axis=0).T).sum()) if len(P) > 1 else 0.0


def _pen(s: Dict[str, Any]):
    return (s["colour"], s["layer"])


def objects(strk: Sequence[Dict[str, Any]], cap: float = CAP_PT, link: float = LINK_PT,
            keep: Optional[Callable[[Dict[str, Any]], bool]] = None) -> List[Dict[str, Any]]:
    """Connected objects (module docstring, steps 2-4): {"members" (stroke
    indices), "parts" (lists of them), "box", "pen"}."""
    idx = [i for i, s in enumerate(strk)
           if _extent(s["box"]) <= cap and (keep is None or keep(s))]
    n = len(idx)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    dense = [_dense(strk[i]["pts"], 0.25) for i in idx]
    cell = 12.0
    grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for k, i in enumerate(idx):
        x0, y0, x1, y1 = strk[i]["box"]
        for gx in range(int((x0 - link) // cell), int((x1 + link) // cell) + 1):
            for gy in range(int((y0 - link) // cell), int((y1 + link) // cell) + 1):
                grid[(gx, gy)].append(k)
    trees: Dict[int, cKDTree] = {}
    checked = set()
    edges: Dict[Tuple[int, int], Optional[Tuple[float, float]]] = {}
    for members in grid.values():
        for ai, a in enumerate(members):
            for b in members[ai + 1:]:
                key = (a, b) if a < b else (b, a)
                if key in checked:
                    continue
                checked.add(key)
                sa, sb = strk[idx[a]], strk[idx[b]]
                if _pen(sa) != _pen(sb):
                    continue
                A, B = sa["box"], sb["box"]
                if (A[0] - link > B[2] or B[0] - link > A[2]
                        or A[1] - link > B[3] or B[1] - link > A[3]):
                    continue
                if b not in trees:
                    trees[b] = cKDTree(dense[b])
                d, _ = trees[b].query(dense[a], k=1, distance_upper_bound=link + 1e-9)
                hit = np.isfinite(d)
                if hit.any():
                    parent[find(b)] = find(a)
                    # IN HOW MANY PLACES: a diameter meets its circle twice; a
                    # leader meets the circle once.
                    c = dense[a][hit]
                    spread = float(np.hypot(*(c.max(0) - c.min(0))))
                    edges[(idx[a], idx[b])] = (None if spread > ONE_PLACE_PT
                                               else tuple(c.mean(0)))
    comps: Dict[int, List[int]] = defaultdict(list)
    for k in range(n):
        comps[find(k)].append(idx[k])
    objs = []
    for members in comps.values():
        bx = np.array([strk[i]["box"] for i in members])
        objs.append({"members": members, "pen": _pen(strk[members[0]]),
                     "box": (float(bx[:, 0].min()), float(bx[:, 1].min()),
                             float(bx[:, 2].max()), float(bx[:, 3].max()))})
    area = [(o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1]) for o in objs]
    cgrid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for j, o in enumerate(objs):
        x0, y0, x1, y1 = o["box"]
        for gx in range(int(x0 // 24), int(x1 // 24) + 1):
            for gy in range(int(y0 // 24), int(y1 // 24) + 1):
                cgrid[(gx, gy)].append(j)
    into: Dict[int, int] = {}
    for i, o in enumerate(objs):
        best = None
        for j in cgrid[(int(o["box"][0] // 24), int(o["box"][1] // 24))]:
            c = objs[j]
            if j == i or c["pen"] != o["pen"] or area[j] <= area[i]:
                continue
            if _inside(o["box"], c["box"], 0.1) and (best is None or area[j] < area[best]):
                best = j
        if best is not None:
            into[i] = best

    def root(i):
        for _ in range(64):
            if i not in into:
                break
            i = into[i]
        return i
    final: Dict[int, List[int]] = defaultdict(list)
    for i in range(len(objs)):
        final[root(i)].append(i)
    out = [{"members": [m for p in parts for m in objs[p]["members"]],
            "parts": [objs[p]["members"] for p in parts],
            "box": objs[r]["box"], "pen": objs[r]["pen"]}
           for r, parts in final.items()]
    adj: Dict[int, Dict[int, Optional[Tuple[float, float]]]] = defaultdict(dict)
    for (a, b), where in edges.items():
        adj[a][b] = adj[b][a] = where
    for o in out:
        o["pieces"] = _pieces(strk, o, adj) if len(o["members"]) <= MAX_PIECE_STROKES else []
    return out


#: Contacts within this (pt) of each other are ONE place. P-103.00's CW/2:
#: the leader enters the circle and ends on the diameter, 3.4pt from where it
#: crosses the circle. A diameter meets its circle a whole diameter apart.
ONE_PLACE_PT = 4.0
#: An object of more strokes than this is not cut into pieces (a pipe network).
MAX_PIECE_STROKES = 40


def _box_of(strk, members) -> Box:
    bx = np.array([strk[i]["box"] for i in members])
    return (float(bx[:, 0].min()), float(bx[:, 1].min()), float(bx[:, 2].max()), float(bx[:, 3].max()))


def _pieces(strk, o, adj) -> List[Dict[str, Any]]:
    """The pieces an object falls into when it is cut at ONE PLACE: a leader
    drawn in the symbol's own pen (P-101.00's W/5: layer P-TEXT - CW, the
    leader ending where the diameter meets the circle) or a pipe stub touches
    the symbol in one place. Every contact at that place is cut; each side,
    with the parts lying inside that side's box, is a candidate too, and the
    whole object stays one. A diameter meets its circle in two places, and
    two places are never one cut."""
    out = []
    for part in o["parts"]:
        if len(part) < 2:
            continue
        ps = set(part)
        places: List[Tuple[Tuple[float, float], List[Tuple[int, int]]]] = []
        for u in part:
            for v, where in adj[u].items():
                if v in ps and u < v and where is not None:
                    for k, (c, es) in enumerate(places):
                        if math.dist(c, where) <= ONE_PLACE_PT:
                            es.append((u, v))
                            break
                    else:
                        places.append((where, [(u, v)]))
        for _c, cut in places:
            gone = set(cut) | {(v, u) for u, v in cut}
            seen: set = set()
            sides = []
            for u0 in part:
                if u0 in seen:
                    continue
                side, todo = {u0}, [u0]
                while todo:
                    u = todo.pop()
                    for v in adj[u]:
                        if v in ps and v not in side and (u, v) not in gone:
                            side.add(v)
                            todo.append(v)
                seen |= side
                sides.append(sorted(side))
            if len(sides) < 2:
                continue
            for side in sides:
                box = _box_of(strk, side)
                inner = [p for p in o["parts"] if p is not part
                         and _inside(_box_of(strk, p), box, 0.5)]
                out.append({"members": side + [m for p in inner for m in p],
                            "parts": [side] + inner, "box": box, "pen": o["pen"],
                            "piece": True})
    return out


# ══════════════════════════════════════════════════════════════════════════
# The shape and the score
# ══════════════════════════════════════════════════════════════════════════

def norm_points(strk, members, box: Box) -> np.ndarray:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    s = max(_extent(box), 1e-6)
    pts = np.vstack([_dense(strk[i]["pts"], s / 120.0) for i in members])
    return (pts - (cx, cy)) / s


def norm_parts(strk, parts, box: Box) -> List[Tuple[np.ndarray, float]]:
    """[(points, own size)] per part, all in the object's normalised frame."""
    out = []
    for p in parts:
        P = norm_points(strk, p, box)
        out.append((P, max(float(max(np.ptp(P[:, 0]), np.ptp(P[:, 1]))), PART_FLOOR)))
    return out


def is_hash(strk, members) -> bool:
    """'#', the printed placeholder for a number: exactly four straight
    strokes, two horizontal and two parallel non-horizontal ones."""
    segs = []
    for i in members:
        ss = strk[i]["segs"]
        if len(ss) != 1 or ss[0] is None:
            return False
        segs.append(ss[0])
    if len(segs) != 4:
        return False
    ang = [math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180 for p, q in segs]
    hor = [a for a in ang if a < 12 or a > 168]
    oth = [a for a in ang if not (a < 12 or a > 168)]
    return len(hor) == 2 and len(oth) == 2 and abs(oth[0] - oth[1]) < 8


def _outside(P: np.ndarray, wild) -> np.ndarray:
    keep = np.ones(len(P), bool)
    for (x0, y0, x1, y1) in wild:
        keep &= ~((P[:, 0] >= x0) & (P[:, 0] <= x1) & (P[:, 1] >= y0) & (P[:, 1] <= y1))
    return P[keep]


def _occ(P: np.ndarray) -> np.ndarray:
    g = np.zeros((OCC_N, OCC_N), bool)
    ij = np.clip(((P + 0.5) * OCC_N).astype(int), 0, OCC_N - 1)
    g[ij[:, 1], ij[:, 0]] = True
    return g


def _dilate(g: np.ndarray) -> np.ndarray:
    d = g.copy()
    d[1:, :] |= g[:-1, :]
    d[:-1, :] |= g[1:, :]
    d[:, 1:] |= g[:, :-1]
    d[:, :-1] |= g[:, 1:]
    return d


def transforms(mirror: bool = True) -> List[int]:
    """The dihedral indices tried. `mirror=False` is the four rotations only
    (kept as a parameter so the test can show what mirroring buys)."""
    return list(range(8)) if mirror else list(range(4))


def coarse_ok(T: np.ndarray, C: np.ndarray, wild=None, mirror: bool = True) -> bool:
    """Cheap first look: under some transform, does each drawing's 16x16
    occupancy cover the other's within one cell? Only a pass is scored."""
    gT = _occ(T)
    dT = _dilate(gT)
    for k in transforms(mirror):
        Q = C @ DIHEDRAL[k].T
        if wild:
            Q = _outside(Q, wild)
        if len(Q) < 2:
            continue
        gC = _occ(Q)
        if ((gT & _dilate(gC)).sum() >= OCC_NEED * gT.sum()
                and (gC & dT).sum() >= OCC_NEED * gC.sum()):
            return True
    return False


def match_score(Tparts, Cparts, wild=None, mirror: bool = True) -> Tuple[float, int]:
    """(score, dihedral index): the worst part's 95th-percentile distance to
    the other drawing's ink over that part's own size, at the best transform.
    `wild` boxes (a '#' slot) are ignored in both drawings."""
    T = np.vstack([P for P, _s in Tparts])
    tT = cKDTree(T)
    best = (9.0, -1)
    for k in transforms(mirror):
        Cp = []
        for P, sz in Cparts:
            Q = P @ DIHEDRAL[k].T
            if wild:
                Q = _outside(Q, wild)
            if len(Q) >= 2:
                Cp.append((Q, sz))
        if not Cp:
            continue
        tC = cKDTree(np.vstack([Q for Q, _s in Cp]))
        worst = 0.0
        for Q, sz in Cp:
            worst = max(worst, float(np.percentile(tT.query(Q, k=1)[0], 95)) / sz)
            if worst >= best[0]:
                break
        if worst < best[0]:
            for P, sz in Tparts:
                worst = max(worst, float(np.percentile(tC.query(P, k=1)[0], 95)) / sz)
                if worst >= best[0]:
                    break
        if worst < best[0]:
            best = (worst, k)
    return best


# ══════════════════════════════════════════════════════════════════════════
# The legend: its table, its rows, its swatches
# ══════════════════════════════════════════════════════════════════════════

#: Row rules group into one table when both ends agree within this (pt): a
#: rounded border's top and bottom rules stop short of its corners.
CORNER_PT = 12.0
#: A legend is a table this narrow at most (pt); rooms make grids too.
LEGEND_MAX_W = 800.0
LEGEND_TITLE = re.compile(r"(?i)\b(LEGEND|SYMBOLS?)\b")


def _rules(drawings):
    H, V = [], []
    for d in drawings:
        for it in d["items"]:
            if it[0] != "l":
                continue
            (x0, y0), (x1, y1) = it[1], it[2]
            if abs(y1 - y0) < 0.3 and abs(x1 - x0) >= 30:
                H.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2))
            elif abs(x1 - x0) < 0.3 and abs(y1 - y0) >= 6:
                V.append(((x0 + x1) / 2, min(y0, y1), max(y0, y1)))
    return H, V


def _dedupe(vals, tol: float = 1.5):
    out: List[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def grids(drawings, page_w: float, min_rows: int = 3) -> List[Dict[str, Any]]:
    """Ruled tables in display space: {"bbox", "rows": [y], "bands": [[x] per
    band]}. A column rule is a RULE OF THE TABLE: it divides at least three
    bands or runs through a row rule (a valve's stem inside one swatch cell
    is as tall as its band and divides nothing)."""
    H, V = _rules(drawings)
    H.sort(key=lambda h: -(h[1] - h[0]))
    groups: List[Dict[str, Any]] = []
    for x0, x1, y in H:
        for g in groups:
            if abs(g["x0"] - x0) <= CORNER_PT and abs(g["x1"] - x1) <= CORNER_PT:
                g["ys"].append(y)
                break
        else:
            groups.append({"x0": x0, "x1": x1, "ys": [y]})
    out = []
    for gr in groups:
        rows = _dedupe(gr["ys"])
        x0, x1 = gr["x0"], gr["x1"]
        if len(rows) < min_rows + 1 or x1 - x0 > 0.6 * page_w:
            continue
        per_band = [_dedupe([x for x, v0, v1 in V if x0 + 2 < x < x1 - 2
                             and min(v1, yb) - max(v0, ya) >= 0.7 * (yb - ya)])
                    for ya, yb in zip(rows[:-1], rows[1:])]
        crossed: Dict[float, int] = {}
        for x, v0, v1 in V:
            if x0 + 2 < x < x1 - 2:
                n = sum(1 for y in rows[1:-1] if v0 + 1 < y < v1 - 1)
                crossed[round(x)] = max(crossed.get(round(x), 0), n)
        seen = Counter(round(x) for xs in per_band for x in {round(v) for v in xs})
        rule = {x for x in seen if seen[x] >= 3 or crossed.get(x, 0) >= 1}
        bands = [[x0] + [x for x in xs if round(x) in rule] + [x1] for xs in per_band]
        out.append({"bbox": (x0, rows[0], x1, rows[-1]), "rows": rows, "bands": bands})
    return [g for g in out if not any(
        h is not g and h["bbox"] != g["bbox"] and _inside(g["bbox"], h["bbox"], 1.0)
        for h in out)]


def legend_candidate(g: Dict[str, Any]) -> bool:
    """Worth reading as a legend: three or more bands split into cells, and
    narrow enough to be a table."""
    return (sum(1 for xs in g["bands"] if len(xs) > 2) >= 3
            and g["bbox"][2] - g["bbox"][0] <= LEGEND_MAX_W)


def cells_text(g: Dict[str, Any], words: Sequence[Tuple[str, float, float]]) -> Dict[Tuple[int, int], str]:
    """{(band, cell): text} from (text, x, y) word centres, in reading order."""
    rows, bands = g["rows"], g["bands"]
    cells: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    for t, x, y in sorted(words, key=lambda w: (round(w[2]), w[1])):
        for r, (ya, yb) in enumerate(zip(rows[:-1], rows[1:])):
            if ya <= y < yb:
                xs = bands[r]
                for c, (xa, xb) in enumerate(zip(xs[:-1], xs[1:])):
                    if xa <= x < xb:
                        cells[(r, c)].append(t)
                break
    return {k: " ".join(v) for k, v in cells.items()}


def ocr_words(page, box: Box, dpi: int = 300) -> List[Tuple[str, float, float]]:
    """(text, x, y) read off a render of `box` by lib.plan_ocr's engine - for
    a legend whose text is drawn as vectors (JPW's SHX). Empty when the
    engine is unavailable, which leaves the rows without meanings."""
    from lib import plan_ocr
    img = page.render(box, dpi)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    s = dpi / 72.0
    return [(t, box[0] + px / s, box[1] + py / s)
            for px, py, t, _sc in plan_ocr._boxes(buf.getvalue())]


def legend_rows(g: Dict[str, Any], text: Dict[Tuple[int, int], str]):
    """([{meaning, cell}], why). A legend is a ruled table titled LEGEND or
    ...SYMBOL(S). Its rows start after the band reading SYMBOL and
    DESCRIPTION (or, with no such band, at the first band split into cells)
    and are PAIRS of cells, a narrow swatch then its wider meaning. The first
    band with another cell count ends it (P-001.00 stacks its ABBREVIATIONS
    table under the same rules)."""
    rows, bands = g["rows"], g["bands"]
    if not LEGEND_TITLE.search(" ".join(text.values())):
        return None, "no LEGEND/SYMBOL title"
    start = None
    for r in range(len(rows) - 1):
        t = " ".join(text.get((r, c), "") for c in range(len(bands[r]) - 1))
        if re.search(r"(?i)SYMBOL", t) and re.search(r"(?i)DESCRIPTION", t):
            start = r + 1
            break
    if start is None:
        start = next((r for r in range(len(rows) - 1) if len(bands[r]) > 2), None)
    if start is None or start >= len(rows) - 1:
        return None, "no swatch column"
    n0 = len(bands[start]) - 1
    if n0 < 2 or n0 % 2:
        return None, f"{n0} cells per row, not swatch/meaning pairs"
    out = []
    for r in range(start, len(rows) - 1):
        xs = bands[r]
        if len(xs) - 1 != n0:
            break
        for sc in range(0, n0, 2):
            if xs[sc + 1] - xs[sc] >= xs[sc + 2] - xs[sc + 1]:
                continue
            out.append({"meaning": text.get((r, sc + 1), "").strip(),
                        "cell": (xs[sc], rows[r], xs[sc + 1], rows[r + 1])})
    return out, ""


def lift_swatch(strk, cell: Box):
    """(template, why not). Every stroke wholly inside the swatch cell, made
    into objects as the plan's are. EXACTLY ONE drawing, or nothing."""
    x0, y0, x1, y1 = cell
    inner = (x0 + 0.8, y0 + 0.8, x1 - 0.8, y1 - 0.8)
    mine = [i for i, s in enumerate(strk) if _inside(s["box"], inner)]
    if not mine:
        return None, "no drawn swatch in the cell"
    sub = [strk[i] for i in mine]
    # A LINE TYPE IS NOT A SYMBOL: a run across the cell, whole or dashed,
    # that is most of the ink in it.
    flat = [s for s in sub if (s["box"][3] - s["box"][1]) <= 1.0
            and (s["box"][2] - s["box"][0]) > 1.0]
    if flat:
        reach = max(s["box"][2] for s in flat) - min(s["box"][0] for s in flat)
        # most of the cell's width, or most of its ink (DHWR's line carries
        # its letters, and they are most of the ink)
        if reach >= 0.75 * (x1 - x0) or (
                reach >= 0.6 * (x1 - x0)
                and sum(_length(s) for s in flat) >= 0.5 * sum(_length(s) for s in sub)):
            return None, "a line type (a run drawn across the cell), not a placed symbol"
    objs = objects(sub, cap=1e9)
    if len(objs) > 1:
        # A FILL IS NOT A SECOND DRAWING (RCP-001.00 shades its double square
        # grey or white): another pen's shape inside the outline of the pen
        # with the most ink is dropped.
        dom = max(objs, key=lambda o: sum(_length(sub[k]) for k in o["members"]))
        objs = [o for o in objs if o is dom or o["pen"] == dom["pen"]
                or not _inside(o["box"], dom["box"], 0.5)]
    if len(objs) != 1:
        return None, f"{len(objs)} separate drawings in the swatch cell"
    o = objs[0]
    parts = [[mine[k] for k in p] for p in o["parts"]]
    hashes = [p for p in parts if is_hash(strk, p)]
    box = o["box"]
    cx, cy, sz = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, _extent(box)
    wild = []
    for h in hashes:
        # The slot a number fills: the '#' widened by twice its own width
        # each side (P-104.00 numbers stacks 1-4, three characters wide), a
        # small pad in y.
        hb = np.array([strk[i]["box"] for i in h])
        hx0, hx1 = (hb[:, 0].min() - cx) / sz, (hb[:, 2].max() - cx) / sz
        hy0, hy1 = (hb[:, 1].min() - cy) / sz, (hb[:, 3].max() - cy) / sz
        hw = hx1 - hx0
        wild.append((hx0 - 2 * hw, hy0 - 0.02, hx1 + 2 * hw, hy1 + 0.02))
    tparts = []
    for p in parts:
        if any(p is h for h in hashes):
            continue
        (P, psz), = norm_parts(strk, [p], box)
        P = _outside(P, wild) if wild else P
        if len(P):
            tparts.append((P, psz))
    if not tparts:
        return None, "the swatch is only a placeholder"
    return {"box": box, "T": tparts, "wild": wild, "size": sz,
            "bare": len(tparts) == 1 and is_bare_outline(tparts[0][0]),
            "aspect": (box[2] - box[0]) / max(box[3] - box[1], 1e-6),
            "n_strokes": len(o["members"])}, ""


#: Refusal for a swatch that is one convex outline with nothing inside it.
BARE = ("a bare outline (one convex shape, nothing inside): every square or "
        "circle of its proportions on the sheet is the same drawing")
#: Ink within this (of the drawing's size) of its convex hull is "on the outline".
#: P-001.00 draws the PRV square's sides as 0.36pt filled slivers: the inner
#: edge sits 0.030 of the square inside the hull.
BARE_HULL = 0.06


def is_bare_outline(P: np.ndarray) -> bool:
    """One part whose every point lies on its own convex hull: a plain square
    or circle. P-001.00's PRESSURE RELIEF VALVE is a bare square, and on the
    P plans the railing posts and the valve boxes are squares too (P-100.00:
    11 matches, none a PRV). The mark rule below rescues a bare
    outline that prints a mark inside it; with no mark it is refused."""
    from scipy.spatial import ConvexHull
    if len(P) < 4:
        return True
    try:
        hull = ConvexHull(P)
    except Exception:
        return True                          # degenerate: a line or a point
    eq = hull.equations                      # a x + b y + c <= 0 inside
    d = np.min(np.abs(P @ eq[:, :2].T + eq[:, 2]), axis=1)
    return bool((d <= BARE_HULL).all())


def cell_drawings(strk, cell: Box, words=()) -> List[Tuple[list, str]]:
    """[(parts, mark)] - every drawing in a swatch cell, a refused row's too,
    as lift_swatch forms it (fills dropped), each with the mark inside it."""
    x0, y0, x1, y1 = cell
    inner = (x0 + 0.8, y0 + 0.8, x1 - 0.8, y1 - 0.8)
    mine = [i for i, s in enumerate(strk) if _inside(s["box"], inner)]
    if not mine:
        return []
    sub = [strk[i] for i in mine]
    objs = objects(sub, cap=1e9)
    if len(objs) > 1:
        dom = max(objs, key=lambda o: sum(_length(sub[k]) for k in o["members"]))
        objs = [o for o in objs if o is dom or o["pen"] == dom["pen"]
                or not _inside(o["box"], dom["box"], 0.5)]
    out = []
    for o in objs:
        if _extent(o["box"]) < 1.0:
            continue
        parts = [[mine[k] for k in p] for p in o["parts"]]
        out.append((norm_parts(strk, parts, o["box"]), _text_in(o["box"], words)))
    return out


def _text_in(box: Box, words) -> str:
    return " ".join(t for t, x, y in sorted(words, key=lambda w: (round(w[2]), w[1]))
                    if box[0] <= x <= box[2] and box[1] <= y <= box[3]).strip()


def dedupe(ms: List[Dict[str, Any]], tol: float = TWICE_PT):
    """(kept, drawn twice). One drawing drawn twice - the sheet xrefs two
    issues of one floor plan, or a block is inserted twice - is one object."""
    kept: List[Dict[str, Any]] = []
    twice = 0
    for m in sorted(ms, key=lambda m: m["score"]):
        if any(all(abs(a - b) <= tol for a, b in zip(m["box"], k["box"])) for k in kept):
            twice += 1
            continue
        cx, cy = (m["box"][0] + m["box"][2]) / 2, (m["box"][1] + m["box"][3]) / 2
        if any(_inside((cx, cy, cx, cy), k["box"]) for k in kept):
            continue                        # an object and its piece: one drawing
        kept.append(m)
    return kept, twice


# ══════════════════════════════════════════════════════════════════════════
# One sheet
# ══════════════════════════════════════════════════════════════════════════

def read_legends(page, drawings=None, words=None, ocr: Optional[Callable] = None):
    """([{meaning, cell, text_src}], [legend boxes]) - the sheet's own legends.
    Text is the page's real words inside the table, else `ocr(page, box)`
    (default: ocr_words) when the table holds none."""
    drawings = page.drawings if drawings is None else drawings
    words = list(page.words) if words is None else words
    ocr = ocr_words if ocr is None else ocr
    rows, boxes = [], []
    for g in grids(drawings, page.width):
        if not legend_candidate(g):
            continue
        x0, y0, x1, y1 = g["bbox"]
        mine = [w for w in words if x0 <= w[1] <= x1 and y0 <= w[2] <= y1]
        src = "text"
        if not mine:
            mine, src = ocr(page, g["bbox"]), "ocr"
        got, _why = legend_rows(g, cells_text(g, mine))
        if got:
            rows += [dict(r, text_src=src) for r in got]
            boxes.append(g["bbox"])
    return rows, boxes


def count_sheet(page, legends: Sequence[Dict[str, Any]] = (), *, own: bool = True,
                title_edge: Optional[float] = None, mirror: bool = True,
                ocr: Optional[Callable] = None) -> Dict[str, Any]:
    """Every legend row matched against every connected object on `page`.

    `legends` are extra rows from ANOTHER sheet, each {meaning, cell, sheet,
    strokes, words}: P-001.00's SYMBOLS LIST, which its note 1 makes
    "applicable to all drawings marked P". With `own`, the sheet's own
    legends are read too (and excluded as candidates).

    Returns {"rows": [{meaning, src, refused | matches, near, twice, mark}],
             "legend_boxes": [...]}."""
    drawings = page.drawings
    words = list(page.words)
    strk = strokes_from_drawings(drawings)
    own_rows, boxes = (read_legends(page, drawings, words, ocr) if own else ([], []))
    if title_edge is None:
        from lib import plan_cells as pc
        from lib.plan_sheet import display_segments
        title_edge = pc.title_block_edge(display_segments(page), page.width, page.height)

    def keep(s):
        b = s["box"]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return cx <= title_edge and not any(_inside((cx, cy, cx, cy), e) for e in boxes)
    objs = objects(strk, keep=keep)
    cands = objs + [p for o in objs for p in o.get("pieces") or ()]
    rows_in = [dict(r, sheet=None, strokes=strk, words=words) for r in own_rows] + list(legends)
    lifted = []
    for row in rows_in:
        tmpl, why = lift_swatch(row["strokes"], row["cell"])
        if tmpl is not None:
            tmpl["mark"] = _text_in(tmpl["box"], row.get("words") or ())
            if tmpl["bare"] and not tmpl["mark"]:
                tmpl, why = None, BARE
        lifted.append((row, tmpl, why))
    # ONE DRAWING, TWO MEANINGS: a swatch that is ALSO drawn in another row's
    # cell of the same legend - that row's template, or one of the drawings
    # of a row refused for holding two (P-001.00's YARD DRAIN is the drawing
    # in ROOF DRAIN & OVERFLOW ROOF DRAIN's cell, and on P-206.00 it "found"
    # the five roof drain glyphs) - stands only if each prints its own mark.
    drawn = [cell_drawings(row["strokes"], row["cell"], row.get("words") or ())
             for row, _t, _w in lifted]
    same: Dict[int, Dict[int, str]] = defaultdict(dict)
    for i, (ri, ti, _w) in enumerate(lifted):
        if ti is None:
            continue
        for j, (rj, _tj, _w2) in enumerate(lifted):
            if j == i or ri.get("sheet") != rj.get("sheet"):
                continue
            for parts, mark in drawn[j]:
                if match_score(ti["T"], parts, mirror=mirror)[0] <= TOL:
                    same[i][j] = mark
                    break
    # THE SHEET'S OWN LEGEND WINS (ruling 75): a row of another sheet's legend
    # (P-001.00's SYMBOLS LIST) that the sheet's own legend also prints - the
    # same meaning, or the same drawing - is counted from the sheet's own row
    # only, never twice.
    own_idx = [j for j, (r, _t, _w) in enumerate(lifted) if r.get("sheet") is None]
    superseded: Dict[int, str] = {}
    for i, (ri, ti, _w) in enumerate(lifted):
        if ri.get("sheet") is None:
            continue
        for j in own_idx:
            rj, tj, _w2 = lifted[j]
            if (_norm(ri["meaning"]) and _norm(ri["meaning"]) == _norm(rj["meaning"])) or (
                    ti is not None and tj is not None
                    and match_score(ti["T"], tj["T"], mirror=mirror)[0] <= TOL):
                superseded[i] = rj["meaning"]
                break
    out = []
    for i, (row, tmpl, why) in enumerate(lifted):
        if i in superseded:
            tmpl, why = None, (f"{SUPERSEDED}: {superseded[i][:48]}")
        rec: Dict[str, Any] = {"meaning": row["meaning"], "cell": list(row["cell"]),
                               "src": row.get("sheet") or "own legend",
                               "text_src": row.get("text_src")}
        if tmpl is not None and same[i]:
            marks = list(same[i].values()) + [tmpl["mark"]]
            if not tmpl["mark"] or len(set(marks)) != len(marks):
                why = ("ambiguous swatch: the same drawing as "
                       + "; ".join(lifted[j][0]["meaning"][:40] for j in sorted(same[i]))
                       + ", and no printed mark inside it tells them apart")
                tmpl = None
        if tmpl is None:
            rec["refused"] = why
            out.append(rec)
            continue
        rec.update(mark=tmpl["mark"], swatch_box=list(tmpl["box"]), placeholder=bool(tmpl["wild"]))
        a0 = min(tmpl["aspect"], 1 / tmpl["aspect"])
        Tall = np.vstack([P for P, _s in tmpl["T"]])
        found, near = [], []
        for o in cands:
            b = o["box"]
            w, h = b[2] - b[0], b[3] - b[1]
            if w <= 0 or h <= 0 or abs(min(w / h, h / w) - a0) > ASPECT_TOL * max(a0, 0.05):
                continue
            sc = _extent(b) / tmpl["size"]
            if not SCALE_MIN <= sc <= SCALE_MAX:
                continue
            if "_parts" not in o:
                o["_parts"] = norm_parts(strk, o["parts"], b)
                o["_all"] = np.vstack([P for P, _s in o["_parts"]])
            if not coarse_ok(Tall, o["_all"], tmpl["wild"], mirror=mirror):
                continue
            if tmpl["mark"] and _text_in(b, words) != tmpl["mark"]:
                continue                    # the family's drawing, another member's mark
            score, k = match_score(tmpl["T"], o["_parts"], tmpl["wild"], mirror=mirror)
            m = {"box": [round(v, 1) for v in b], "score": round(score, 4),
                 "transform": DIHEDRAL_NAMES[k], "scale": round(sc, 3)}
            if score <= TOL:
                found.append(m)
            elif score <= NEAR_FACTOR * TOL:
                near.append(m)
        rec["matches"], rec["twice"] = dedupe(found)
        rec["near"], _ = dedupe(near)
        out.append(rec)
    res = {"rows": out, "legend_boxes": [list(b) for b in boxes], "objects": len(objs)}
    if not rows_in:
        # NOT ZERO OF ANYTHING: a sheet with no legend read has no swatch,
        # so every symbol on it is refused - and says so, once.
        res["refused"] = NO_LEGEND
    return res


def set_legend(page, sheet: str, ocr: Optional[Callable] = None) -> List[Dict[str, Any]]:
    """The legend rows of a SYMBOLS LIST sheet (P-001.00), carrying their own
    strokes and words, ready to hand to count_sheet for another sheet."""
    drawings = page.drawings
    words = list(page.words)
    rows, _boxes = read_legends(page, drawings, words, ocr)
    strk = strokes_from_drawings(drawings)
    return [dict(r, sheet=sheet, strokes=strk, words=words) for r in rows]


# ══════════════════════════════════════════════════════════════════════════
# The rows a pass would store (designed; NOT written by anything)
# ══════════════════════════════════════════════════════════════════════════

#: A row of another sheet's legend that the sheet's own legend also prints.
SUPERSEDED = "the sheet's own legend prints this symbol and counts it"
#: Where a pass would store the rows (its own collection, like lib.plan_areas):
#: no plan record, so search never returns them.
COLLECTION = "plan_legend_counts"


def _norm(s: str) -> str:
    """Meanings compared as letters and digits: OCR spaces differ by sheet
    (STORMSTACK/STACK NO. against STORM STACK/STACK NO.)."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


#: The sheet-level refusal when no legend was read on it (and none was handed in).
NO_LEGEND = "no legend on the sheet: no swatch to match, every symbol refused"
#: How the count was made. NOT in plan_search.COUNTING_BASES.
COUNT_BASIS = "legend_symbol"
#: record_type of the would-be rows.
RECORD_TYPE = "legend_symbol_count"


def legend_count_rows(result: Dict[str, Any], page_meta: Dict[str, Any], *,
                      track: Optional[str] = None) -> List[Dict[str, Any]]:
    """One row per legend row on one sheet: the count and where every match
    is, or the refusal and why. `page_meta` carries the citation fields
    (project_id, file_id, page_id, page_number, sheet_number, file_name).

    Scope is the SHEET: the count is what this sheet draws, never a floor's
    or the building's - floor identity comes from the sheet number and its
    printed title level, which the caller resolves (and no drawing set is
    picked here: `track` is the caller's). The row is a takeoff line's
    candidate, not a chat count: `count_basis` is COUNT_BASIS."""
    out = []
    cite = {k: page_meta.get(k) for k in ("project_id", "file_id", "page_id",
                                          "page_number", "sheet_number", "file_name")}
    if result.get("refused"):
        return [dict(cite, record_type=RECORD_TYPE, count_basis=COUNT_BASIS, ordinal=0,
                     label=None, scope="sheet", track=track, status="refused",
                     refused=result["refused"], count=None)]
    for i, r in enumerate(result.get("rows") or []):
        base = dict(cite)
        base.update(record_type=RECORD_TYPE, count_basis=COUNT_BASIS, ordinal=i,
                    label=r["meaning"], scope="sheet", track=track,
                    legend_src=r.get("src"), legend_cell=r.get("cell"))
        if "refused" in r:
            base.update(status="refused", refused=r["refused"], count=None)
        else:
            base.update(status="counted", count=len(r["matches"]), mark=r.get("mark") or None,
                        positions=[m["box"] for m in r["matches"]],
                        scores=[m["score"] for m in r["matches"]],
                        transforms=[m["transform"] for m in r["matches"]],
                        drawn_twice=r.get("twice", 0), near_misses=len(r.get("near") or []))
        out.append(base)
    return out


# ══════════════════════════════════════════════════════════════════════════
# Scoring against a benchmark (ruling 81): per sheet, or per floor
# ══════════════════════════════════════════════════════════════════════════

def _row_for(result: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """The row a benchmark key names on one sheet: `mark:X`, or a meaning
    compared as letters and digits - the sheet's own legend first (ruling 75)."""
    rows = sorted(result.get("rows") or [], key=lambda r: r.get("src") != "own legend")
    for r in rows:
        if key.startswith("mark:") and r.get("mark") == key[5:]:
            return r
        if not key.startswith("mark:") and _norm(r.get("meaning")) == _norm(key):
            if "refused" in r and str(r["refused"]).startswith(SUPERSEDED):
                continue
            return r
    return None


def _score(found: int, exp: int, fp_boxes) -> Dict[str, Any]:
    if fp_boxes is not None:
        fp = len(fp_boxes)
        tp, basis = found - fp, "per instance"
    else:
        tp = min(found, exp)
        fp, basis = found - tp, "per count (an upper bound)"
    fn = max(exp - tp, 0)
    return {"found": found, "expected": exp, "tp": tp, "fp": fp, "fn": fn, "basis": basis,
            "p": round(tp / found, 3) if found else None,
            "r": round(tp / exp, 3) if exp else None}


def evaluate(results: Dict[str, Dict[str, Any]], benchmark: Dict[str, Any],
             titles: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """P/R of `results` ({sheet number: count_sheet result}) against WHICHEVER
    benchmark is loaded, and whose it is (`source`, `kind`).

    `benchmark["sheets"]`: {sheet: {meaning | "mark:X": {"expected"[,
    "false_positive_boxes"]}}}. `benchmark["floors"]`: {printed level ("SECOND
    FLOOR"): {meaning | "mark:X": {"expected"}}} - a sub bid's per-floor
    quantity. A floor is matched to sheets ONLY by the level their printed
    title names (`titles`: {sheet: title}; plan_search._title_level, the
    gate's own reading), and the floor's figure is the sum over those sheets.
    A level no sheet's title names - FIRST UNDERGROUND FLOOR reads as no
    level - is unresolved and said, never guessed. A refused row is reported
    as refused, never scored as zero found."""
    from lib.plan_search import _title_level
    out: List[Dict[str, Any]] = []
    for sheet, wants in sorted((benchmark.get("sheets") or {}).items()):
        res = results.get(sheet)
        for key, e in wants.items():
            row = _row_for(res, key) if res else None
            rec = {"scope": "sheet", "where": sheet, "symbol": key}
            if row is None:
                rec["status"] = "not in any legend read" if res else "sheet not measured"
            elif "refused" in row:
                rec.update(status="refused", why=row["refused"])
            else:
                rec.update(status="scored", **_score(len(row["matches"]), int(e["expected"]),
                                                      e.get("false_positive_boxes")))
            out.append(rec)
    levels = {s: _title_level(t) for s, t in (titles or {}).items()}
    for label, wants in sorted((benchmark.get("floors") or {}).items()):
        lvl = _title_level(label) or _title_level(f"{label} floor")
        on = sorted(s for s, l in levels.items() if lvl is not None and l == lvl and s in results)
        for key, e in wants.items():
            rec = {"scope": "floor", "where": label, "symbol": key, "sheets": on}
            if not on:
                rec.update(status="unresolved",
                           why=f"no measured sheet's printed title names {label!r}")
                out.append(rec)
                continue
            rows = [r for r in (_row_for(results[s], key) for s in on) if r is not None]
            counted = [r for r in rows if "refused" not in r]
            if not counted:
                rec.update(status="refused" if rows else "not in any legend read",
                           why="; ".join(sorted({str(r["refused"]) for r in rows})))
            else:
                rec.update(status="scored", **_score(sum(len(r["matches"]) for r in counted),
                                                      int(e["expected"]), None))
            out.append(rec)
    sc = [r for r in out if r["status"] == "scored"]
    tp, fp, fn = (sum(r[k] for r in sc) for k in ("tp", "fp", "fn"))
    return {"source": benchmark.get("source"), "kind": benchmark.get("kind"), "rows": out,
            "totals": {"tp": tp, "fp": fp, "fn": fn,
                       "p": round(tp / (tp + fp), 3) if tp + fp else None,
                       "r": round(tp / (tp + fn), 3) if tp + fn else None}}


__all__ = [
    "CAP_PT", "LINK_PT", "TOL", "NEAR_FACTOR", "ASPECT_TOL", "SCALE_MIN", "SCALE_MAX",
    "PART_FLOOR", "DIHEDRAL_NAMES", "COUNT_BASIS", "RECORD_TYPE",
    "strokes_from_drawings", "objects", "norm_parts", "is_hash", "coarse_ok",
    "match_score", "grids", "legend_candidate", "cells_text", "legend_rows",
    "lift_swatch", "dedupe", "read_legends", "count_sheet", "set_legend",
    "legend_count_rows", "transforms", "evaluate", "SUPERSEDED", "COLLECTION",
]
