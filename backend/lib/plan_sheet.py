"""One architectural or mechanical sheet, read from its PDF page.

Everything the space and takeoff steps need from a page, in DISPLAY space
(the page rotation applied - get_drawings() returns unrotated coordinates):
segments, segments with their PDF attributes (layer, width, dash, colour),
perpendicular corners, the plan viewport, words, and the unit tags printed on
the plan. Plus the raster helpers both space builders share, and the
corner-matching registration between an architectural and a mechanical sheet.

No database access: the caller hands in the page and the unit tags.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict, deque
from typing import Dict, Sequence, Tuple

import numpy as np
from scipy.spatial import cKDTree

from lib import plan_cells as pc
from lib import plan_registration as reg

log = logging.getLogger(__name__)

#: 1/4" = 1'-0": one real inch is 1.5pt.
PT_PER_INCH = 72.0 / (12.0 * reg.PLAN_SCALE_DENOM)
#: raster resolution of every space grid
CELL_IN = 2.0
#: wall materials the legend names after a thickness (6" STUD, 12" CONCRETE)
WALL_WORDS = ("STUD", "STUD,", "CONCRETE", "CMU", "BRICK", "BLOCK")


def _pts(inch: float) -> float:
    return inch * PT_PER_INCH


def inches(pt: float) -> float:
    return pt / PT_PER_INCH


def display_segments(page):
    """Segments in DISPLAY space, after the page rotation is applied."""
    m = page.rotation_matrix
    out = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                p1, p2 = it[1] * m, it[2] * m
                out.append((p1.x, p1.y, p2.x, p2.y))
            elif it[0] == "re":
                r = it[1] * m
                out += [(r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1),
                        (r.x1, r.y1, r.x0, r.y1), (r.x0, r.y1, r.x0, r.y0)]
    return out

def attributed_segments(page):
    """Same list, same order as reg_scan.display_segments, plus attributes."""
    m = page.rotation_matrix
    out = []
    for d in page.get_drawings():
        a = (d.get("layer") or "", round(float(d.get("width") or 0.0), 2),
             str(d.get("dashes")), tuple(round(c, 2) for c in (d.get("color") or ())))
        for it in d["items"]:
            if it[0] == "l":
                p1, p2 = it[1] * m, it[2] * m
                out.append(((p1.x, p1.y, p2.x, p2.y), a))
            elif it[0] == "re":
                r = it[1] * m
                for s in ((r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1),
                          (r.x1, r.y1, r.x0, r.y1), (r.x0, r.y1, r.x0, r.y0)):
                    out.append((s, a))
    return out

def corners(segs, min_len_pt=1.5, snap=0.25):
    """Endpoints where two segments meet near-perpendicular."""
    inc = defaultdict(list)
    for x1, y1, x2, y2 in segs:
        if math.hypot(x2 - x1, y2 - y1) < min_len_pt:
            continue
        a = math.atan2(y2 - y1, x2 - x1)
        inc[(round(x1 / snap), round(y1 / snap))].append(a)
        inc[(round(x2 / snap), round(y2 / snap))].append(
            math.atan2(y1 - y2, x1 - x2))
    out = []
    for (kx, ky), angs in inc.items():
        if len(angs) < 2:
            continue
        found = False
        for i in range(len(angs)):
            for j in range(i + 1, len(angs)):
                d = abs(angs[i] - angs[j]) % math.pi
                d = min(d, math.pi - d)
                if math.radians(70) <= d <= math.radians(110):
                    found = True
                    break
            if found:
                break
        if found:
            out.append((kx * snap, ky * snap))
    return np.array(out, dtype=float)

def legend_wall_thicknesses(words):
    """[(inches, 'next word')] for tokens like 12" followed by a wall material."""
    toks = [t for t, _x, _y in words]
    out = []
    for i, t in enumerate(toks[:-1]):
        m = re.fullmatch(r'(\d+(?:\.\d+)?)"', t)
        if m and toks[i + 1].upper() in WALL_WORDS:
            out.append((float(m.group(1)), toks[i + 1]))
    return out

def thickest_legend_wall_in(words):
    t = legend_wall_thicknesses(words)
    if not t:
        raise ValueError("no wall types found in the sheet legend")
    return max(v for v, _ in t)

def rasterise(segs, lo, hi, cell_pt):
    """Boolean barrier grid. True where a wall passes."""
    w = int((hi[0] - lo[0]) / cell_pt) + 1
    h = int((hi[1] - lo[1]) / cell_pt) + 1
    g = np.zeros((h, w), dtype=bool)
    for x1, y1, x2, y2 in segs:
        n = int(max(abs(x2 - x1), abs(y2 - y1)) / (cell_pt * 0.5)) + 2
        for t in np.linspace(0.0, 1.0, n):
            px = int((x1 + t * (x2 - x1) - lo[0]) / cell_pt)
            py = int((y1 + t * (y2 - y1) - lo[1]) / cell_pt)
            if 0 <= px < w and 0 <= py < h:
                g[py, px] = True
    return g

def fill(grid, seed, blocked=None):
    """4-connected flood from `seed`, stopped by grid and by `blocked`."""
    h, w = grid.shape
    sy, sx = seed
    if not (0 <= sy < h and 0 <= sx < w) or grid[sy, sx]:
        return None
    seen = np.zeros_like(grid)
    q = deque([(sy, sx)])
    seen[sy, sx] = True
    n = 0
    while q:
        y, x = q.popleft()
        n += 1
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] \
                    and not grid[ny, nx] \
                    and (blocked is None or not blocked[ny, nx]):
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen

def net_by_tag(words, tag_pos):
    """{tag: printed NET sq ft} from the sheet's own NET boxes, or {}.

    Each "NET:" word takes the next numeric token as its value and belongs to
    the plan tag nearest to it (the NET box is printed beside its APT tag).
    """
    import re as _re
    out, best = {}, {}
    for i, (t, x, y) in enumerate(words):
        if t.upper() != "NET:":
            continue
        val = next((w[0] for w in words[i + 1:i + 4]
                    if _re.fullmatch(r"[\d,]+", w[0])), None)
        if val is None or not tag_pos:
            continue
        tag, (tx, ty) = min(tag_pos.items(),
                            key=lambda kv: (kv[1][0] - x) ** 2 + (kv[1][1] - y) ** 2)
        d = (tx - x) ** 2 + (ty - y) ** 2
        if tag not in best or d < best[tag]:
            best[tag], out[tag] = d, int(val.replace(",", ""))
    return out

def room_names(lab, words, to_cell):
    """{closed-door region label: its printed room name} - the first line of
    purely alphabetic words inside the region (e.g. "BIKE ROOM")."""
    import re as _re
    per = {}
    for t, x, y in words:
        # A ROOM LABEL IS PURELY ALPHABETIC: no digits, no punctuation.
        # "No." (from "No. 586", a neighbouring-building note) named the
        # outdoors "NO" on A-101.00 (operator ruling 2026-09-21).
        if not _re.fullmatch(r"[A-Z]{2,}", t.upper()):
            continue
        r, c = to_cell(x, y)
        if 0 <= r < lab.shape[0] and 0 <= c < lab.shape[1] and lab[r, c]:
            per.setdefault(int(lab[r, c]), []).append((y, x, t.upper()))
    out = {}
    for L, ws in per.items():
        ws.sort()
        y0 = ws[0][0]
        out[L] = " ".join(t for y, x, t in sorted(w for w in ws
                                                    if abs(w[0] - y0) <= 2.0)
                          if True)
    return out

def edge_regions(lab):
    """OUTDOORS = the regions connected to the page edge. Nothing else
    (operator ruling 2026-09-22). The bounding-box clause (a region whose box
    holds every unit tag) classified A-100.01's lobby as outdoors because the
    lobby wraps all four studios."""
    return {int(L) for L in np.unique(np.concatenate(
        [lab[0], lab[-1], lab[:, 0], lab[:, -1]]))} - {0}

def best_translation(A, B, coarse_pt=4.0, span_pt=360.0, radius_in=1.0):
    """Exhaustive (dx, dy) by match count. Coarse pass, then 1pt refine."""
    tree = cKDTree(B)
    r = _pts(radius_in)

    def count(dx, dy):
        d, _ = tree.query(A + np.array([dx, dy]), distance_upper_bound=r)
        return int(np.isfinite(d).sum())

    # seed the search on the offset between bounding-box centres, which is
    # within a few feet even when the annotation differs
    seed = (B.min(0) + B.max(0)) / 2 - (A.min(0) + A.max(0)) / 2
    best, bxy = -1, (seed[0], seed[1])
    steps = int(span_pt / coarse_pt)
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            dx, dy = seed[0] + i * coarse_pt, seed[1] + j * coarse_pt
            c = count(dx, dy)
            if c > best:
                best, bxy = c, (dx, dy)
    # THE REFINE STEP IS THE RESIDUAL FLOOR. A 0.75pt grid is 0.5 real
    # inches, so a coarse refine makes the reported RMS a measurement of the
    # SEARCH rather than of the drawings. Two passes: 0.75pt to place it,
    # then 0.05pt (0.033in) so the grid is an order of magnitude finer than
    # anything being reported.
    for step, rng_ in ((0.75, 7), (0.05, 16)):
        for i in range(-rng_, rng_ + 1):
            for j in range(-rng_, rng_ + 1):
                dx, dy = bxy[0] + i * step, bxy[1] + j * step
                c = count(dx, dy)
                if c > best:
                    best, bxy = c, (dx, dy)
    # ── COUNT DOES NOT LOCALISE THE TRANSLATION. ────────────────────────
    #
    # Maximising matches is FLAT inside the capture radius: a translation
    # that is 0.8in off catches the same anchors as the exact one, so the
    # grid search stops anywhere in that basin. The tell was p50 == p90 ==
    # p99 in the first run — every pair sharing one residual is one constant
    # offset, not a distribution of disagreement.
    #
    # So close it with a least-squares translation on the matched set: take
    # the MEAN RESIDUAL VECTOR and subtract it, then re-match. That is a
    # different objective (minimise residual, not maximise count) and it is
    # the one the reported number is supposed to answer.
    bxy = np.array(bxy, dtype=float)
    for _ in range(12):
        d, jj = tree.query(A + bxy, distance_upper_bound=r)
        ok = np.isfinite(d)
        if ok.sum() < 3:
            break
        shift = (B[jj[ok]] - (A[ok] + bxy)).mean(0)
        if np.hypot(*shift) < 1e-4:
            break
        bxy = bxy + shift
    d, jj = tree.query(A + bxy, distance_upper_bound=r)
    ok = np.isfinite(d)
    return tuple(bxy), A[ok], B[jj[ok]], d[ok]


def viewport(pts_arr, page_w, segs, page_h):
    """The plan viewport: drop the title strip, at the edge the sheet draws
    (plan_cells.title_block_edge), never a fixed fraction of the page."""
    pts_arr = np.asarray(pts_arr, dtype=float).reshape(-1, 2)   # none -> (0, 2)
    cut = pc.title_block_edge(segs, page_w, page_h)
    return pts_arr[pts_arr[:, 0] < cut]


def load_sheet(page) -> dict:
    """segs, attributed segs, viewport corners, words and page size, all in
    display space."""
    import fitz
    segs = display_segments(page)
    rm = page.rotation_matrix
    words = []
    for w in page.get_text("words"):
        p = fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) * rm
        words.append((w[4], p.x, p.y))
    return {"segs": segs, "att": attributed_segments(page),
            "corners": viewport(corners(segs), page.rect.width, segs,
                                page.rect.height),
            "words": words, "page": (page.rect.width, page.rect.height),
            "rotation": page.rotation}


def plan_unit_tags(corners_arr, words, unit_tags: Sequence[str]
                   ) -> Dict[str, Tuple[float, float]]:
    """The unit tags ON THE PLAN, not in the occupancy table.

    A-103.00 prints 4A-4D twice: on the plan and in the LIGHT & AIR /
    OCCUPANCY tables. The first occurrence inside the plan's corner extent
    (1st-99th percentile) is the plan's. A dict comprehension once kept the
    LAST - the table - and every placement came back 491-782in off.
    """
    lo, hi = np.percentile(corners_arr, [1, 99], axis=0)
    wanted = set(unit_tags)
    out: Dict[str, Tuple[float, float]] = {}
    for t, x, y in words:
        if t in wanted and lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1]:
            out.setdefault(t, (x, y))
    return out


def register(arch: dict, mech: dict) -> dict:
    """Translation arch->mech by corner matching, and whether room membership
    may be decided on it (plan_registration tolerances, never changed here)."""
    (dx, dy), _a, _b, dist = best_translation(
        arch["corners"], mech["corners"], radius_in=reg.ANCHOR_MATCH_RADIUS_IN)
    res = (np.array([inches(x) for x in dist]) if len(dist)
           else np.array([np.inf]))
    rms, mx = float(math.sqrt((res ** 2).mean())), float(res.max())
    usable = reg.usable_for("room_membership", rms, max_residual_in=mx)
    return {"dx": float(dx), "dy": float(dy), "anchors": int(len(dist)),
            "rms_in": rms, "max_in": mx, "usable": bool(usable)}
