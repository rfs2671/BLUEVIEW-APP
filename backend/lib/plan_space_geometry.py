"""Apartment membership from GEOMETRY ALONE - the fallback when a sheet has
no usable CAD wall layer (see plan_space).

This is the pipeline that was frozen on 2026-09-21 and scored on A-103.00,
A-100.01 and A-101.00; it is ported unchanged in behaviour. In short:
dashed chains out before the 6in collinear merge; a wall is a face with a
partner 2-12in away; a run carrying a feet-inch label is a dimension string;
the band between partner faces is filled solid; pinholes bordered only by wall
bodies and narrower than the legend's thickest wall are wall; doors closed
along their closing radius (directional test, drawn-threshold tie-break) for
the public fill; public = a closed-door region with no tag whose door arcs
join >= 2 unit-tag regions; unit fills stop at public; enclosed pockets go to
the one unit around them; a region holding other than one tag is refused.

Its known limit, and the reason it is the fallback: on A-101.00 two entrance
doors are drawn at 45 degrees and two more have jamb stubs under the wall
filter, the units merge, and every item is REFUSED (never assigned).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Dict, Sequence

import numpy as np
from scipy import ndimage

from lib import plan_cells as pc
from lib.plan_sheet import (CELL_IN, PT_PER_INCH, fill, net_by_tag,
                            plan_unit_tags, rasterise, room_names,
                            thickest_legend_wall_in)

log = logging.getLogger(__name__)

WALL_MIN_FT = 2.0             # shorter than this is not a wall run
AXIS_TOL_PT = 1.0             # long_walls' own axis test, reused
FACE_GAP_IN = (2.0, 12.0)     # 2.5in stud + 2 x 5/8 gyp = 3.75in is the thinnest
MIN_COVER = 0.5               # partner spans must cover this much of the run
DIM_TEXT = re.compile(r"^\d+'-\d+")   # 12'-0"  7'-8"  2'-7"
DIM_REACH_IN = 6.0            # a dimension label sits ON its line
DOOR_RADIUS_IN = (18.0, 42.0) # 1'-6" closet leaf .. 3'-6" entrance
JAMB_IN = 12.0                # the closing radius is carried across a jamb stub
SEG_TOL_PT = 2.0              # drawn threshold: within 2pt of the radius line,
SEG_ANG_DEG = 2.0             # parallel within 2 deg,
SEG_MIN_COVER = 0.5           # covering half the radius


# ── dashed chains (removed before the collinear merge) ────────────────────

def lines(segs):
    """{(axis, coord): [(lo, hi)]} for axis-aligned pieces, grouped collinear."""
    raw = defaultdict(list)
    for x1, y1, x2, y2 in segs:
        if abs(x2 - x1) < AXIS_TOL_PT and abs(y2 - y1) < AXIS_TOL_PT:
            # a dot: zero-length piece; axis unknown, record on both
            raw[("h", y1)].append((x1, x1))
            raw[("v", x1)].append((y1, y1))
        elif abs(x2 - x1) < AXIS_TOL_PT:
            raw[("v", x1)].append((min(y1, y2), max(y1, y2)))
        elif abs(y2 - y1) < AXIS_TOL_PT:
            raw[("h", y1)].append((min(x1, x2), max(x1, x2)))
    out = {}
    for ax in ("h", "v"):
        keys = sorted(c for a, c in raw if a == ax)
        groups, cur = [], []
        for c in keys:
            if cur and c - cur[-1] > pc.WALL_COLLINEAR_TOL_PT:
                groups.append(cur); cur = []
            cur.append(c)
        if cur:
            groups.append(cur)
        for g in groups:
            ps = sorted(p for c in g for p in raw[(ax, c)])
            # pieces that touch or overlap are one solid piece
            merged = []
            for a, b in ps:
                # below coordinate precision a gap is not a gap: solid line
                if merged and a - merged[-1][1] <= pc.WALL_COLLINEAR_TOL_PT:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            out[(ax, float(np.mean(g)))] = [tuple(m) for m in merged]
    return out

def regular(P, p):
    """Is the piece window P regular with period p? (spreads, ok)"""
    L = [b - a for a, b in P]
    G = [P[i + 1][0] - P[i][1] for i in range(len(P) - 1)]
    if not G or min(G) <= 0:
        return None, False
    # SCOPE: only chains the 6in merge would join into one run matter.
    if max(G) > pc.WALL_MERGE_GAP_IN * 1.5:
        return None, False
    gmin = min(G)
    sl = max(np.ptp(L[k::p]) for k in range(p))
    sg = max(np.ptp(G[k::p]) if len(G[k::p]) else 0.0 for k in range(p))
    return (sl, sg, gmin), (sl < gmin and sg < gmin)

def chains(pieces):
    out, i = [], 0
    while i < len(pieces):
        best = None
        # period up to 4: the A-300 section cut is dash, dot, dot (3 lengths)
        for p, need in ((1, 3), (2, 4), (3, 6), (4, 8)):
            j = i + need
            if j > len(pieces) or not regular(pieces[i:j], p)[1]:
                continue
            while j < len(pieces) and regular(pieces[i:j + 1], p)[1]:
                j += 1
            if best is None or j - i > best[1] - best[0]:
                best = (i, j, p)
        if best:
            i0, j0, p = best
            out.append((pieces[i0:j0], p))
            i = j0
        else:
            i += 1
    return out

def chain_members(segs):
    """Indices into `segs` of every segment that is part of a dashed chain.

    Same grouping and the same detector as the census, carried back to the
    raw segments so they can be removed BEFORE the collinear merge.
    """
    raw = defaultdict(list)
    for i, (x1, y1, x2, y2) in enumerate(segs):
        if abs(x2 - x1) < AXIS_TOL_PT and abs(y2 - y1) < AXIS_TOL_PT:
            raw[("h", y1)].append((x1, x1, i))
            raw[("v", x1)].append((y1, y1, i))
        elif abs(x2 - x1) < AXIS_TOL_PT:
            raw[("v", x1)].append((min(y1, y2), max(y1, y2), i))
        elif abs(y2 - y1) < AXIS_TOL_PT:
            raw[("h", y1)].append((min(x1, x2), max(x1, x2), i))
    out = set()
    for ax in ("h", "v"):
        keys = sorted(c for a, c in raw if a == ax)
        groups, cur = [], []
        for c in keys:
            if cur and c - cur[-1] > pc.WALL_COLLINEAR_TOL_PT:
                groups.append(cur); cur = []
            cur.append(c)
        if cur:
            groups.append(cur)
        for g in groups:
            ps = sorted(p for c in g for p in raw[(ax, c)])
            merged = []
            for a, b, i in ps:
                if merged and a - merged[-1][1] <= pc.WALL_COLLINEAR_TOL_PT:
                    merged[-1][1] = max(merged[-1][1], b); merged[-1][2].append(i)
                else:
                    merged.append([a, b, [i]])
            pieces = [(a, b) for a, b, _ in merged]
            members = {(a, b): ids for a, b, ids in merged}
            for P, _p in chains(pieces):
                for piece in P:
                    out.update(members[piece])
    return out


# ── walls: two faces, dimension strings, bodies ───────────────────────────

def _covered(a, b, spans):
    """Length of [a, b] covered by the union of `spans`."""
    iv = sorted((max(a, s), min(b, e)) for s, e in spans
                if min(b, e) > max(a, s))
    tot, cur_s, cur_e = 0.0, None, None
    for s, e in iv:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                tot += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        tot += cur_e - cur_s
    return tot

def two_faces(runs, ppi, gap_in=FACE_GAP_IN, min_cover=MIN_COVER):
    """Split runs (c, lo, hi) into (walls, singles) by the partner test."""
    lo_pt, hi_pt = gap_in[0] * ppi, gap_in[1] * ppi
    cs = np.array([r[0] for r in runs]) if runs else np.zeros(0)
    walls, singles = [], []
    for c, a, b in runs:
        d = np.abs(cs - c)
        idx = np.nonzero((d >= lo_pt) & (d <= hi_pt))[0]
        cov = _covered(a, b, [(runs[i][1], runs[i][2]) for i in idx])
        (walls if cov >= min_cover * (b - a) else singles).append((c, a, b))
    return walls, singles

def dimension_runs(runs, words, ppi, vertical):
    """Runs carrying a feet-inch label: dimension strings, not walls.

    THE TWO-FACES TEST CANNOT SEE THESE. A dimension string drawn ~11in
    inside a wall pairs with the wall's face and passes; the strip between
    is lost to every fill (4A's "12'-0" under the bedroom cost ~1.5ft of
    depth across the unit). The drawing marks its own dimensions - the
    text rides the line - so the label decides, not the geometry.
    """
    reach = DIM_REACH_IN * ppi
    dims = [(x, y) for t, x, y in words if DIM_TEXT.match(t)]
    out = set()
    for i, (c, a, b) in enumerate(runs):
        for x, y in dims:
            along, off = (y, x) if vertical else (x, y)
            if a <= along <= b and abs(off - c) <= reach:
                out.add(i)
                break
    return out

def bodies(runs, ppi, vertical, gap_in=FACE_GAP_IN):
    """Solid rectangles between each wall face and its partners.

    A WALL IS NOT TWO LINES WITH AIR BETWEEN. Rasterised as two lines, its
    body is free space; the end caps at door jambs are shorter than the
    wall filter, so every wall is an open tube at every doorway, and CAD's
    trimmed crossings (4C/4D demising x 8in wall, an open 8x6in square)
    join the tubes. The fills walked through walls. The band between a
    face and its partner is filled over the span where BOTH exist, so a
    doorway, where both faces stop, stays open.
    Returned as (x0, y0, x1, y1) rectangles in display space.
    """
    lo_pt, hi_pt = gap_in[0] * ppi, gap_in[1] * ppi
    out = []
    for i, (c, a, b) in enumerate(runs):
        for c2, a2, b2 in runs[i + 1:]:
            if lo_pt <= abs(c2 - c) <= hi_pt:
                s, e = max(a, a2), min(b, b2)
                if e > s:
                    lo_c, hi_c = min(c, c2), max(c, c2)
                    out.append((lo_c, s, hi_c, e) if vertical
                               else (s, lo_c, e, hi_c))
    return out

def as_segments(v, h):
    return [(x, y0, x, y1) for x, y0, y1 in v] + \
           [(x0, y, x1, y) for y, x0, x1 in h]

def wall_segments(segs, min_ft, ppi, report=False, words=None):
    # FIX a (operator ruling 2026-09-21): dashed chains out BEFORE the merge.
    # The 6in merge otherwise bridges dash gaps into continuous "walls":
    # 1B's soffit, the A-300 section cut across 1D, dashed stair treads.
    if True:
        drop = chain_members(segs)
        if report:
            log.info(f"dashed-chain segments removed before the merge: {len(drop)}")
        segs = [s for i, s in enumerate(segs) if i not in drop]
    v, h = pc.long_walls(segs, min_ft * 12 * ppi,
                         pc.WALL_MERGE_GAP_IN * ppi)
    vw, vs = two_faces(v, ppi)
    hw, hs = two_faces(h, ppi)
    if words is not None:
        dv = dimension_runs(vw, words, ppi, True)
        dh = dimension_runs(hw, words, ppi, False)
        vs += [r for i, r in enumerate(vw) if i in dv]
        hs += [r for i, r in enumerate(hw) if i in dh]
        vw = [r for i, r in enumerate(vw) if i not in dv]
        hw = [r for i, r in enumerate(hw) if i not in dh]
        if report:
            log.info(f"dimension strings passing two-faces: {len(dv)} v / "
                  f"{len(dh)} h")
    if report:
        log.info(f"runs >= {min_ft}ft: {len(v)} v / {len(h)} h  ->  "
              f"walls {len(vw)} v / {len(hw)} h, "
              f"singles dropped {len(vs)} v / {len(hs)} h")
    if words is not None:
        return (as_segments(vw, hw), as_segments(vs, hs),
                bodies(vw, ppi, True) + bodies(hw, ppi, False))
    return as_segments(vw, hw), as_segments(vs, hs)


# ── doors ──────────────────────────────────────────────────────────────────

def _centre(p0, c1, c2, p3):
    t0, t1 = c1 - p0, p3 - c2            # tangents at the two ends
    n0, n1 = np.array([-t0[1], t0[0]]), np.array([-t1[1], t1[0]])
    M = np.column_stack([n0, -n1])
    if abs(np.linalg.det(M)) < 1e-9:
        return None
    s, _ = np.linalg.solve(M, p3 - p0)
    return p0 + s * n0

def segment_cover(C, E, segs_arr):
    """Fraction of radius C->E covered by drawn segments lying along it."""
    S = segs_arr
    V = S[:, 2:] - S[:, :2]
    Lv = np.hypot(V[:, 0], V[:, 1])
    ok = Lv > 0
    S, V, Lv = S[ok], V[ok], Lv[ok]
    Vu = V / Lv[:, None]
    R = np.linalg.norm(E - C)
    u = (E - C) / R
    nrm = np.array([-u[1], u[0]])
    par = np.abs(Vu @ nrm) < np.sin(np.radians(SEG_ANG_DEG))
    d1 = np.abs((S[:, :2] - C) @ nrm)
    d2 = np.abs((S[:, 2:] - C) @ nrm)
    m = par & (d1 <= SEG_TOL_PT) & (d2 <= SEG_TOL_PT)
    t1 = (S[m, :2] - C) @ u
    t2 = (S[m, 2:] - C) @ u
    iv = sorted((max(0, min(a, b)), min(R, max(a, b))) for a, b in zip(t1, t2)
                if min(R, max(a, b)) > max(0, min(a, b)))
    tot, cs, ce = 0.0, None, None
    for s_, e_ in iv:
        if ce is None or s_ > ce:
            if ce is not None:
                tot += ce - cs
            cs, ce = s_, e_
        else:
            ce = max(ce, e_)
    if ce is not None:
        tot += ce - cs
    return tot / R

def _extend(C, P, by):
    u = (P - C) / np.linalg.norm(P - C)
    a, b = C - u * by, P + u * by
    return (a[0], a[1], b[0], b[1])

def door_closures(page, ppi, grid, lo, cell_pt, report=None, segs=None):
    """[(x1,y1,x2,y2)] in display space, plus the swing count.

    Pairs per swing: (closing radius carried JAMB_IN past both ends, leaf).

    WHICH RADIUS CLOSES IS DECIDED BY DIRECTION (operator ruling 2026-09-21).
    Carry each radius past its far end for JAMB_IN and count barrier cells on
    the wall grid: the closed leaf's line continues into the strike jamb's
    wall; the open leaf's tip continues into room or outdoor space. The old
    test - nearest wall point in ANY direction - flipped on two A-100.01
    exterior doors once dashed headers were removed, and closed them along
    the open leaf. A tie is reported, not guessed (the leaf is used, since
    closing it is the one that does no harm: it is already drawn).

    THE CLOSING RADIUS IS CARRIED 12in PAST BOTH ENDS: the hinge sits on a
    jamb stub shorter than the 2ft wall filter. Only the closing radius is
    extended: extending the open leaf could cut a 4ft corridor in two.
    """
    rm = page.rotation_matrix
    h, w = grid.shape
    reach = JAMB_IN * ppi

    def wall_run(C, E):
        u = (E - C) / np.linalg.norm(E - C)
        n = 0
        for t in np.arange(cell_pt / 2, reach, cell_pt / 2):
            p = E + u * t
            r, c = int((p[1] - lo[1]) / cell_pt), int((p[0] - lo[0]) / cell_pt)
            if 0 <= r < h and 0 <= c < w and grid[r, c]:
                n += 1
        return n

    segs_arr = None if segs is None else np.asarray(segs, dtype=float)
    out, n_sw = [], 0
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] != "c":
                continue
            p0, c1, c2, p3 = (np.array(tuple(q * rm)) for q in it[1:5])
            C = _centre(p0, c1, c2, p3)
            if C is None:
                continue
            r0, r3 = np.linalg.norm(p0 - C), np.linalg.norm(p3 - C)
            if abs(r0 - r3) > 0.1 * max(r0, r3):
                continue                  # not circular
            v0, v3 = (p0 - C) / r0, (p3 - C) / r3
            if abs(float(v0 @ v3)) > 0.2:
                continue                  # not a quarter turn
            if not (DOOR_RADIUS_IN[0] * ppi <= r0 <= DOOR_RADIUS_IN[1] * ppi):
                continue
            n_sw += 1
            s0, s3 = wall_run(C, p0), wall_run(C, p3)
            cov = None
            if s0 == s3:
                k, how = None, "TIE"
                # TIE-BREAK ONLY (operator ruling 2026-09-21): when the wall
                # test ties 0/0 and exactly ONE radius has a drawn segment
                # along it, close along that radius - the drawn threshold /
                # wall face across the doorway (A-100.01 exterior doors).
                # Resolved doors never reach this branch.
                if s0 == 0 and segs_arr is not None:
                    cov = (segment_cover(C, p0, segs_arr),
                           segment_cover(C, p3, segs_arr))
                    hit = [i for i, c in enumerate(cov) if c >= SEG_MIN_COVER]
                    if len(hit) == 1:
                        k, how = hit[0], "seg"
            else:
                k, how = (0, "dir") if s0 > s3 else (1, "dir")
            ends = [p0, p3]
            if k is None:
                shut, leaf = None, None
            else:
                shut, leaf = ends[k], ends[1 - k]
            if report is not None:
                report.append(dict(C=C, ends=(p0, p3), score=(s0, s3), shut=k,
                                   how=how, cover=cov))
            if shut is None:
                continue                  # reported; nothing closed
            out += [_extend(C, shut, JAMB_IN * ppi),
                    (C[0], C[1], leaf[0], leaf[1])]
    return out, n_sw


# ── regions ────────────────────────────────────────────────────────────────

def absorb_pockets(grid, public, regions, reach=2):
    """Give each enclosed pocket to the ONE apartment that surrounds it.

    Treads, tub rims, counters and closet doors enclose free pockets that
    no seed reaches. A pocket whose only labelled neighbour across one
    barrier line is apartment U is inside U. Touching two units, the public
    core or the outside (anything reaching the grid edge) leaves it
    unassigned - that is a demising wall's interior, or the core's.
    Topology, no threshold. Repeats until nothing moves, so a pocket
    behind a pocket is reached.

    AND IT MUST LIE INSIDE THE UNIT'S ENVELOPE - the bounding box of what
    the seed reached. Without that, absorption chains OUTWARD through the
    exterior wall's layer pockets into the band between building face and
    lot line: 4C gained 60 sq ft of sidewalk.
    """
    from scipy import ndimage
    env = {}
    for t, r in regions.items():
        if r is not None:
            ys, xs = np.nonzero(r)
            env[t] = (ys.min(), ys.max(), xs.min(), xs.max())
    # Label in the space the unit fills ran in: walls AND the public core
    # are barriers. On the open-door grid alone, corridor and units are one
    # component and "public" overwrote every unit's owner.
    free = ~(grid | public)
    lab, n = ndimage.label(free)
    edge = set(np.unique(np.concatenate(
        [lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    owner = {}
    for t, r in regions.items():
        if r is not None:
            for L in np.unique(lab[r]):
                owner[L] = t
    pub_ring = ndimage.binary_dilation(public, np.ones((3, 3), bool)) & free
    for L in np.unique(lab[pub_ring]):
        owner.setdefault(L, "public")
    for L in edge:
        owner.setdefault(L, "outside")
    st = np.ones((2 * reach + 1, 2 * reach + 1), bool)
    objs = ndimage.find_objects(lab)
    moved, rounds = True, 0
    while moved:
        moved, rounds = False, rounds + 1
        for L in range(1, n + 1):
            if L in owner or objs[L - 1] is None:
                continue
            sl = objs[L - 1]
            y0, y1 = max(0, sl[0].start - reach), sl[0].stop + reach
            x0, x1 = max(0, sl[1].start - reach), sl[1].stop + reach
            sub = lab[y0:y1, x0:x1]
            ring = ndimage.binary_dilation(sub == L, st) & (sub != L)
            nb = {owner[k] for k in np.unique(sub[ring]) if k and k in owner}
            u = next(iter(nb)) if len(nb) == 1 else None
            # ENVELOPE CHECK REMOVED (operator ruling 2026-09-21, after fix c):
            # it tested a bounding box, and an L-shaped unit's box contains
            # its neighbour. Outward chaining through exterior-wall layer
            # pockets is now stopped by fix c, which walls those pockets.
            if u in regions:
                owner[L] = u
                moved = True
    out = {}
    for t, r in regions.items():
        if r is None:
            out[t] = None
            continue
        ls = [L for L, o in owner.items() if o == t]
        out[t] = np.isin(lab, ls)
    log.debug(f"pockets: {n} free components, absorbed in {rounds} rounds")
    return out

def region_status(regions, tags, on_barrier, to_cell, words):
    """THE POLYGON STEP'S VERDICT, not a print (operator ruling 2026-09-21).

    A-101.00 merged all four units into one region and the takeoff assigned
    all 18 items to "2D": build() returned the regions whatever they held, the
    "NOT EXACTLY ONE" check was only a print in main(), and nothing downstream
    could see the merge. Now:
      - a region holding other than exactly one tag is NOT a unit; every
        point in it is refused, with the tags it holds as the reason;
      - a tag whose region is empty, or which sits on a barrier, makes the
        sheet's per-unit split unavailable, naming the tag and why;
      - where NET is printed, area/NET per unit is reported (informational).
    """
    def holds(mask):
        out = []
        for u, (x, y) in tags.items():
            r, c = to_cell(x, y)
            if 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and mask[r, c]:
                out.append(u)
        return sorted(out)

    units, refused, incomplete = {}, [], {}
    for t in sorted(regions):
        m = regions[t]
        if t in on_barrier:
            incomplete[t] = "tag sits on a barrier cell - no region can be seeded"
            continue
        if m is None or not m.any():
            owner = [u for u in sorted(regions) if u != t and regions[u] is not None
                     and regions[u].any() and t in holds(regions[u])]
            incomplete[t] = ("region empty - its tag lies in the region seeded "
                             f"from {owner[0]}" if owner else "region empty")
            continue
        h = holds(m)
        if h == [t]:
            units[t] = m
        else:
            refused.append((m, h))
            incomplete[t] = f"its region holds {len(h)} tags {h}"
    net = net_by_tag(words, tags)
    ratio = {t: (int(units[t].sum()) * CELL_IN ** 2 / 144, net.get(t))
             for t in units}
    return {"units": units, "refused": refused, "incomplete": incomplete,
            "ratio": ratio, "net": net}

def outdoor_labels(lab, tags, to_cell):
    """Closed-door regions that are the OUTDOORS / unenclosed space: they touch
    the grid edge, or their bounding box contains every unit tag (they
    surround the building). Never an answer (operator ruling 2026-09-21)."""
    from scipy import ndimage as _nd
    h, w = lab.shape
    out = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0],
                                        lab[:, -1]]))) - {0}
    cells = [to_cell(x, y) for x, y in tags.values()]
    if cells:
        rs_ = [r for r, _c in cells]; cs_ = [c for _r, c in cells]
        for L, sl in enumerate(_nd.find_objects(lab), 1):
            if sl is None:
                continue
            if (sl[0].start <= min(rs_) and sl[0].stop > max(rs_) and
                    sl[1].start <= min(cs_) and sl[1].stop > max(cs_)):
                if not any(lab[r, c] == L for r, c in cells):
                    out.add(L)
    return {int(L) for L in out}


def build(page, sheet: dict, unit_tags: Sequence[str]) -> dict:
    """Membership map for one architectural page, from geometry alone."""
    segs, corners, words = sheet["segs"], sheet["corners"], sheet["words"]
    lo = corners.min(0) - 20
    hi = corners.max(0) + 20
    cell_pt = CELL_IN * PT_PER_INCH
    walls, _, bods = wall_segments(segs, WALL_MIN_FT, PT_PER_INCH, False, words)
    grid = rasterise(walls, lo, hi, cell_pt)
    body = np.zeros_like(grid)
    for x0, y0, x1, y1 in bods:
        c0, r0 = int((x0 - lo[0]) / cell_pt), int((y0 - lo[1]) / cell_pt)
        c1, r1 = int((x1 - lo[0]) / cell_pt), int((y1 - lo[1]) / cell_pt)
        body[max(r0, 0):r1 + 1, max(c0, 0):c1 + 1] = True
    grid |= body
    # PINHOLES ARE WALL: a free component bordered ONLY by wall-body cells and
    # narrower than the legend's thickest wall is inside a wall (a CAD-trimmed
    # junction square), not a room.
    thick_in = thickest_legend_wall_in(words)
    lab_f, _nf = ndimage.label(~grid)
    cross = ndimage.generate_binary_structure(2, 1)
    for L, sl in enumerate(ndimage.find_objects(lab_f), 1):
        if sl is None:
            continue
        hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if min(hh, ww) * CELL_IN >= thick_in:
            continue
        y0_, x0_ = max(sl[0].start - 1, 0), max(sl[1].start - 1, 0)
        sub = lab_f[y0_:sl[0].stop + 1, x0_:sl[1].stop + 1] == L
        edge_ = ndimage.binary_dilation(sub, cross) & ~sub
        if body[y0_:sl[0].stop + 1, x0_:sl[1].stop + 1][edge_].all():
            grid[y0_:sl[0].stop + 1, x0_:sl[1].stop + 1] |= sub

    def to_cell(x, y):
        return (int((y - lo[1]) / cell_pt), int((x - lo[0]) / cell_pt))

    # PUBLIC BY DOORS: every door closed; a region is public iff it holds no
    # unit tag AND its door arcs join it to >= 2 distinct unit-tag regions.
    closures, nd = door_closures(page, PT_PER_INCH, grid, lo, cell_pt, None,
                                 segs)
    closed = grid | rasterise(closures, lo, hi, cell_pt)
    lab, _n = ndimage.label(~closed)
    tags = plan_unit_tags(corners, words, unit_tags)

    def _lab(x, y):
        r, c = to_cell(x, y)
        return lab[r, c] if 0 <= r < lab.shape[0] and 0 <= c < lab.shape[1] else 0
    tag_lab = {_lab(x, y): t for t, (x, y) in tags.items()}
    nb: Dict[int, set] = {}
    for i in range(0, len(closures), 2):
        x1, y1, x2, y2 = closures[i]
        m = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
        u = np.array([x2 - x1, y2 - y1]) / np.hypot(x2 - x1, y2 - y1)
        nrm = np.array([-u[1], u[0]])
        sides = []
        for sgn in (1, -1):
            got = 0
            for d in np.arange(1.0, 31.0, 1.0):
                got = _lab(*(m + sgn * nrm * d * PT_PER_INCH))
                if got:
                    break
            sides.append(got)
        a_, b_ = sides
        if a_ and b_ and a_ != b_:
            nb.setdefault(a_, set()).add(b_)
            nb.setdefault(b_, set()).add(a_)
    pub_labels = [L for L, ns in nb.items() if L not in tag_lab
                  and len({tag_lab[k] for k in ns if k in tag_lab}) >= 2]
    public = np.isin(lab, pub_labels)

    regions = {}
    for t, (x, y) in sorted(tags.items()):
        regions[t] = fill(grid, to_cell(x, y), blocked=public)
    on_barrier = sorted(t for t, f in regions.items() if f is None)
    regions = absorb_pockets(grid, public, regions)
    status = region_status(regions, tags, on_barrier, to_cell, words)
    status.update({"method": "geometry", "closed_lab": lab, "public": public,
                   "grid": grid, "names": room_names(lab, words, to_cell),
                   "outdoors": outdoor_labels(lab, tags, to_cell),
                   "door_rooms": set(), "lo": lo, "cell_pt": cell_pt,
                   "tags": tags, "door_swings": nd})
    return status
