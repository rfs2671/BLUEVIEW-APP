"""Apartment membership from the PDF's own CAD LAYERS - the primary path.

Measured 2026-09-21/22 on A-103.00, A-100.01 and A-101.00: every sheet carries
its CAD layers as PDF optional content, and the wall layer is the walls - no
dimension strings, no dashed linework, no furniture on it - with doorways as
clean gaps. Scored against render-read truth on 47 items: 47 correct, 0 wrong
(the geometric pipeline: 29 correct, 0 wrong, 18 refused on A-101.00).

1. LAYERS by National CAD Standard name: a discipline letter, a dash, the
   major group WALL / GLAZ / DOOR in any case, optional minor groups - except
   annotation modifiers (A-DOOR-IDEN is door TAGS, not doors).
2. VALIDATION per sheet: the fraction of axis-aligned wall-layer length with a
   parallel partner face between 2in and the legend's thickest wall must reach
   PAIR_MIN. No wall layer, or below it: the caller falls back to geometry.
3. BARRIERS = wall-layer + glazing-layer lines (the walls' own hatch included).
4. DOORWAYS = gaps in a wall-layer face line no wider than the widest door on
   the set's door schedule, confirmed by door-layer geometry IN the gap
   (overlapping its span and crossing its line - a door's arc and leaf start
   at the hinge on the jamb). The two faces' gaps are paired and sealed.
5. PINHOLES: an enclosed free region narrower than the legend's thickest wall
   is barrier - the strip between a window's glass lines was a doorless
   0.8 sq ft "room" that 19 PTAC units resolved to before this rule.
6. ROOMS = regions with every doorway sealed; the GRAPH joins them through
   doorways. OUTDOORS = regions connected to the page edge, nothing else.
   COMMON = a room with no tag that a doorway joins to >= 2 unit rooms, or
   that prints CORRIDOR / LOBBY / STAIR. Without common and outdoor rooms, a
   connected group holding one unit's tag is that unit; two or more -> every
   room in it UNKNOWN (refused); none -> non-unit.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Optional, Sequence

import numpy as np
from scipy import ndimage

from lib import plan_cells as pc
from lib.plan_sheet import (CELL_IN, PT_PER_INCH, edge_regions, net_by_tag,
                            plan_unit_tags, rasterise, room_names,
                            thickest_legend_wall_in)

log = logging.getLogger(__name__)

PAIR_MIN = 0.5            # validation: half the wall-layer length has a partner
COMMON_WORDS = ("CORRIDOR", "LOBBY", "STAIR", "STAIRS", "STAIRWAY", "VESTIBULE")
ANNOTATION = {"IDEN", "TEXT", "DIMS", "DIM", "NOTE", "NOTES", "ANNO", "PATT"}

def role_of(layer_name):
    """'wall' / 'glaz' / 'door' / None for an NCS layer name."""
    short = (layer_name or "").split("|")[-1].strip()
    m = re.fullmatch(r"([A-Za-z])-(WALL|GLAZ|DOOR)((?:-[A-Za-z0-9]+)*)", short,
                     re.I)
    if not m:
        return None
    minors = {x.upper() for x in m.group(3).split("-") if x}
    if minors & ANNOTATION:
        return None
    return m.group(2).lower()

def pair_fraction(segs, ppi, thick_in):
    """Fraction of axis-aligned wall length with a parallel face 2in..thick."""
    lo_pt, hi_pt = 2.0 * ppi, thick_in * ppi
    runs = {"v": [], "h": []}
    for x1, y1, x2, y2 in segs:
        if abs(x2 - x1) < 0.5 and abs(y2 - y1) > 0:
            runs["v"].append((x1, min(y1, y2), max(y1, y2)))
        elif abs(y2 - y1) < 0.5 and abs(x2 - x1) > 0:
            runs["h"].append((y1, min(x1, x2), max(x1, x2)))
    tot = cov = 0.0
    for ax, rr in runs.items():
        rr.sort()
        cs = np.array([r[0] for r in rr])
        for c, a, b in rr:
            tot += b - a
            i0, i1 = np.searchsorted(cs, c - hi_pt), np.searchsorted(cs, c + hi_pt)
            spans = sorted((max(a, s), min(b, e)) for c2, s, e in rr[i0:i1]
                           if lo_pt <= abs(c2 - c) <= hi_pt and min(b, e) > max(a, s))
            cur = None
            for s, e in spans:
                if cur is None or s > cur[1]:
                    if cur: cov += cur[1] - cur[0]
                    cur = [s, e]
                else:
                    cur[1] = max(cur[1], e)
            if cur: cov += cur[1] - cur[0]
    return (cov / tot if tot else 0.0), tot / ppi / 12

def face_gaps(segs, max_pt):
    """[(axis, coord, a, b)] gaps (0 < b-a <= max_pt) in wall-layer face lines."""
    lines = defaultdict(list)
    for x1, y1, x2, y2 in segs:
        if abs(x2 - x1) < 0.5 and abs(y2 - y1) > 0:
            lines[("v", round(x1 / pc.WALL_COLLINEAR_TOL_PT))].append(
                (x1, min(y1, y2), max(y1, y2)))
        elif abs(y2 - y1) < 0.5 and abs(x2 - x1) > 0:
            lines[("h", round(y1 / pc.WALL_COLLINEAR_TOL_PT))].append(
                (y1, min(x1, x2), max(x1, x2)))
    out = []
    for (ax, _k), rr in lines.items():
        rr.sort(key=lambda r: r[1])
        c = float(np.mean([r[0] for r in rr]))
        end = rr[0][2]
        for _c, a, b in rr[1:]:
            if a - end > pc.WALL_COLLINEAR_TOL_PT and a - end <= max_pt:
                out.append((ax, c, end, a))
            end = max(end, b)
    return out

def pair_doorways(gaps, thick_pt, door_boxes, reach_pt):
    """Pair face gaps across one wall; keep those with door-layer geometry.

    Returns ([doorway rect (x0,y0,x1,y1)], confirmed_gaps, unconfirmed_gaps).
    """
    used, doors, conf, unconf = set(), [], [], []
    def has_door(ax, c0, c1, a, b):
        # DOOR-LAYER GEOMETRY IN THE GAP (the stated rule): it overlaps the
        # gap's span AND crosses the gap's line. A real door's arc and leaf
        # start at the hinge on the jamb, so they always cross it. The first
        # version accepted anything within 56in of the line, and the 1B
        # bathroom's own door arc - 44in away - "confirmed" an 8in gap in the
        # bathroom's far wall, joining it to 1A (A-100.01, 2026-09-22).
        t = reach_pt
        for x0, y0, x1, y1 in door_boxes:
            if ax == "h":
                if x1 >= a - 1 and x0 <= b + 1 and y1 >= c0 - t and y0 <= c1 + t:
                    return True
            else:
                if y1 >= a - 1 and y0 <= b + 1 and x1 >= c0 - t and x0 <= c1 + t:
                    return True
        return False
    for i, (ax, c, a, b) in enumerate(gaps):
        if i in used:
            continue
        best = None
        for j, (ax2, c2, a2, b2) in enumerate(gaps):
            if j == i or j in used or ax2 != ax:
                continue
            if 0 < abs(c2 - c) <= thick_pt and min(b, b2) - max(a, a2) > 0.5 * min(b - a, b2 - a2):
                if best is None or abs(c2 - c) < abs(gaps[best][1] - c):
                    best = j
        if best is not None:
            c2, a2, b2 = gaps[best][1], gaps[best][2], gaps[best][3]
            lo_c, hi_c = min(c, c2), max(c, c2)
            aa, bb = min(a, a2), max(b, b2)
            if has_door(ax, lo_c, hi_c, aa, bb):
                used |= {i, best}
                doors.append((aa, lo_c, bb, hi_c) if ax == "h" else (lo_c, aa, hi_c, bb))
                conf += [gaps[i], gaps[best]]
                continue
        if has_door(ax, c, c, a, b):
            used.add(i)
            doors.append((a, c, b, c) if ax == "h" else (c, a, c, b))
            conf.append(gaps[i])
        else:
            unconf.append(gaps[i])
    return doors, conf, unconf


def validate(page, sheet: dict) -> dict:
    """Layer roles on the page and the validation verdict, no raster work."""
    roles = defaultdict(list)
    names = defaultdict(set)
    for s, a in sheet["att"]:
        r = role_of(a[0])
        if r:
            roles[r].append(s)
            names[r].add(a[0].split("|")[-1])
    door_boxes = []
    for d in page.get_drawings():
        if role_of(d.get("layer")) == "door":
            names["door"].add((d.get("layer") or "").split("|")[-1])
            r = d["rect"] * page.rotation_matrix
            door_boxes.append((min(r.x0, r.x1), min(r.y0, r.y1),
                               max(r.x0, r.x1), max(r.y0, r.y1)))
    thick_in = thickest_legend_wall_in(sheet["words"])
    frac, wall_ft = pair_fraction(roles["wall"], PT_PER_INCH, thick_in)
    ok = bool(roles["wall"]) and frac >= PAIR_MIN
    why = None if ok else ("no wall layer" if not roles["wall"]
                           else f"wall layer failed validation "
                                f"(paired fraction {frac:.2f} < {PAIR_MIN})")
    return {"ok": ok, "why": why, "pair_fraction": frac, "wall_ft": wall_ft,
            "roles": roles, "door_boxes": door_boxes, "thick_in": thick_in,
            "layer_names": {k: sorted(v) for k, v in names.items()}}


def build(page, sheet: dict, unit_tags: Sequence[str],
          widest_door_in: Optional[float]) -> dict:
    """Membership map from layers, or {"fallback": reason} when they fail."""
    v = validate(page, sheet)
    if not v["ok"]:
        return {"fallback": v["why"], "validation": v}
    if not widest_door_in:
        return {"fallback": "no door-schedule width to bound a doorway",
                "validation": v}
    roles, door_boxes, thick_in = v["roles"], v["door_boxes"], v["thick_in"]
    words, corners = sheet["words"], sheet["corners"]
    ppi = PT_PER_INCH
    lo, hi = corners.min(0) - 20, corners.max(0) + 20
    cell_pt = CELL_IN * ppi
    grid = rasterise(roles["wall"] + roles["glaz"], lo, hi, cell_pt)
    gaps = face_gaps(roles["wall"], widest_door_in * ppi)
    doors, _conf, unconf = pair_doorways(gaps, thick_in * ppi, door_boxes,
                                         CELL_IN * ppi)   # crosses the line
    for x0, y0, x1, y1 in doors:
        c0, r0 = int((x0 - lo[0]) / cell_pt), int((y0 - lo[1]) / cell_pt)
        c1, r1 = int((x1 - lo[0]) / cell_pt), int((y1 - lo[1]) / cell_pt)
        grid[max(r0, 0):r1 + 1, max(c0, 0):c1 + 1] = True
    # pinholes are wall
    labf, _nf = ndimage.label(~grid)
    edge_l = set(np.unique(np.concatenate(
        [labf[0], labf[-1], labf[:, 0], labf[:, -1]]))) - {0}
    filled = 0
    for L, sl in enumerate(ndimage.find_objects(labf), 1):
        if sl is None or L in edge_l:
            continue
        hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if min(hh, ww) * CELL_IN >= thick_in:
            continue
        grid[sl] |= labf[sl] == L
        filled += 1

    def to_cell(x, y):
        return int((y - lo[1]) / cell_pt), int((x - lo[0]) / cell_pt)
    lab, n = ndimage.label(~grid)
    h, w = lab.shape

    def lab_at(x, y):
        r, c = to_cell(x, y)
        return int(lab[r, c]) if 0 <= r < h and 0 <= c < w else 0

    edges = set()
    for x0, y0, x1, y1 in doors:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        horiz = (x1 - x0) >= (y1 - y0)            # doorway along x -> step in y
        half = ((y1 - y0) if horiz else (x1 - x0)) / 2
        sides = []
        for sgn in (1, -1):
            got = 0
            for dd in np.arange(half + cell_pt, half + 30 * ppi, cell_pt / 2):
                got = lab_at(mx, my + sgn * dd) if horiz else lab_at(mx + sgn * dd, my)
                if got:
                    break
            sides.append(got)
        if sides[0] and sides[1] and sides[0] != sides[1]:
            edges.add(tuple(sorted(sides)))
    adj = defaultdict(set)
    for a_, b_ in edges:
        adj[a_].add(b_)
        adj[b_].add(a_)

    tags = plan_unit_tags(corners, words, unit_tags)
    tag_room = {t: lab_at(x, y) for t, (x, y) in tags.items()}
    room_tags = defaultdict(list)
    for t, L in tag_room.items():
        if L:
            room_tags[L].append(t)
    rnames = room_names(lab, words, to_cell)
    outdoors = edge_regions(lab)
    common = set()
    for L in range(1, n + 1):
        if L in room_tags or L in outdoors:
            continue
        units_adj = {t for k in adj.get(L, ()) for t in room_tags.get(k, [])}
        nm = rnames.get(L, "")
        if len(units_adj) >= 2 or any(wd in nm.split() for wd in COMMON_WORDS):
            common.add(L)

    seen, groups = set(), []
    for L in range(1, n + 1):
        if L in seen or L in common or L in outdoors:
            continue
        stack, comp = [L], []
        seen.add(L)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v_ in adj.get(u, ()):
                if v_ not in seen and v_ not in common and v_ not in outdoors:
                    seen.add(v_)
                    stack.append(v_)
        groups.append(comp)
    units, refused, incomplete, member = {}, [], {}, {}
    for comp in groups:
        tg = sorted({t for L in comp for t in room_tags.get(L, [])})
        if len(tg) == 1:
            for L in comp:
                member[L] = tg[0]
        elif len(tg) >= 2:
            refused.append((np.isin(lab, comp), ["UNKNOWN"] + tg))
            for t in tg:
                incomplete[t] = (f"UNKNOWN - its rooms reach "
                                 f"{[u for u in tg if u != t]} without passing "
                                 "through common area")
    for t in tags:
        if not tag_room.get(t):
            incomplete[t] = "tag sits on a barrier cell - no room"
    for t in sorted(tags):
        rooms = [L for L, u in member.items() if u == t]
        if rooms:
            units[t] = np.isin(lab, rooms)
    net = net_by_tag(words, tags)
    ratio = {t: (int(m.sum()) * CELL_IN ** 2 / 144, net.get(t))
             for t, m in units.items()}
    return {"method": "layers", "units": units, "refused": refused,
            "incomplete": incomplete, "ratio": ratio, "net": net,
            "closed_lab": lab, "public": np.isin(lab, sorted(common)),
            "grid": grid, "names": rnames, "outdoors": outdoors,
            "door_rooms": {int(x) for e in edges for x in e},
            "lo": lo, "cell_pt": cell_pt, "tags": tags, "validation": v,
            "doorways": len(doors), "unconfirmed_gaps": len(unconf),
            "pinholes_filled": filled, "common": sorted(common)}
