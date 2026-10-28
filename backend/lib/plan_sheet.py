"""One architectural or mechanical sheet, read from its PDF page.

Everything the space and takeoff steps need from a page, in DISPLAY space
(the page rotation applied), from lib.plan_page - never PyMuPDF (AGPL):
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
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
from scipy.spatial import cKDTree

from lib import plan_cells as pc
from lib import plan_registration as reg

log = logging.getLogger(__name__)

#: 1/4" = 1'-0": one real inch is 1.5pt.
PT_PER_INCH = 72.0 / (12.0 * reg.PLAN_SCALE_DENOM)
#: raster resolution of every space grid
CELL_IN = 2.0
#: a length compared to a threshold is equal to it within this
LEN_TOL_PT = 1e-3
#: wall materials the legend names after a thickness (6" STUD, 12" CONCRETE)
WALL_WORDS = ("STUD", "STUD,", "CONCRETE", "CMU", "BRICK", "BLOCK")


def _pts(inch: float) -> float:
    return inch * PT_PER_INCH


def inches(pt: float) -> float:
    return pt / PT_PER_INCH


def display_segments(page):
    """Every straight segment on the page, in display space (plan_page)."""
    return [(p[0], p[1], q[0], q[1]) for d in page.drawings
            for it in d["items"] if it[0] == "l" for p, q in (it[1:3],)]

def attributed_segments(page):
    """Same list, same order as display_segments, each with its CAD layer."""
    return [((p[0], p[1], q[0], q[1]), d["layer"]) for d in page.drawings
            for it in d["items"] if it[0] == "l" for p, q in (it[1:3],)]

def symbol_objects(page):
    """[{"points", "layer", "colour"}] - ONE PER SUBPATH, one pen-down run,
    for plan_symbols.symbol_at_label. A CAD export puts thousands of
    unrelated strokes in one path operator; taken whole, "the object beside
    the label" was half the sheet."""
    out = []
    for d in page.drawings:
        run = []
        for it in d["items"]:
            pts = list(it[1:])
            if run and (abs(run[-1][0] - pts[0][0]) > 1e-6
                        or abs(run[-1][1] - pts[0][1]) > 1e-6):
                out.append({"points": run, "layer": d["layer"],
                            "colour": d.get("colour")})
                run = []
            run.extend(pts if not run else pts[1:])
        if run:
            out.append({"points": run, "layer": d["layer"],
                        "colour": d.get("colour")})
    return out


def corners(segs, min_len_pt=1.5, snap=0.25):
    """Endpoints where two segments meet near-perpendicular.

    min_len_pt is 1.5pt = ONE INCH at 1/4" = 1'-0", a length CAD draws
    constantly, so segments sit exactly ON the threshold and float noise
    (1.4999999 vs 1.5000000) decided them - 593 corners on A-103.00 flipped
    between two PDF readers. Hence the tolerance: a drawn inch is kept."""
    inc = defaultdict(list)
    for x1, y1, x2, y2 in segs:
        if math.hypot(x2 - x1, y2 - y1) < min_len_pt - LEN_TOL_PT:
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

def _seed(A, B):
    """The offset between bounding-box centres, which is within a few feet
    even when the annotation differs: the centre of every search window."""
    return (B.min(0) + B.max(0)) / 2 - (A.min(0) + A.max(0)) / 2


def _match_counts(tree, A, offsets, r):
    """For each (dx, dy) in `offsets`: how many of A land within r of a
    corner of the tree's sheet. One batched query per call."""
    offsets = np.asarray(offsets, dtype=float).reshape(-1, 2)
    pts = (A[None, :, :] + offsets[:, None, :]).reshape(-1, 2)
    d, _ = tree.query(pts, distance_upper_bound=r, workers=-1)
    return np.isfinite(d).reshape(len(offsets), len(A)).sum(1)


def best_translation(A, B, coarse_pt=None, span_pt=360.0, radius_in=1.0):
    """Exhaustive (dx, dy) by match count. Coarse pass, then 1pt refine.

    THE COARSE STEP IS NEVER WIDER THAN THE MATCH RADIUS (ruling
    2026-10-10). Every peak measured on 588 Boyland is NARROW: 2pt off the
    true offset, the count falls to 4-16% of its height. A 4pt grid samples
    a peak up to 2.8pt off its top, so a sheet's true alignment lost to a
    coincidental one whenever its peak was not tall enough to win from
    there: A-105.01/M-105.00 (the roof) registered 21.8in off with 108
    anchors against the true 239, and A-103.00/S-104.00 30in off with 95
    against 204 - both reported usable. At a step of one match radius every
    offset is within the radius of a sample, so the sample nearest the true
    offset catches the anchors the true offset catches. `coarse_pt` is
    accepted only so a test can run the old step."""
    tree = cKDTree(B)
    r = _pts(radius_in)
    step = r if coarse_pt is None else coarse_pt
    seed = _seed(A, B)
    steps = int(span_pt / step)
    grid = np.arange(-steps, steps + 1) * step
    best, bxy = -1, (seed[0], seed[1])
    for gx in grid:
        offs = np.stack([np.full(len(grid), seed[0] + gx), seed[1] + grid], 1)
        c = _match_counts(tree, A, offs, r)
        k = int(np.argmax(c))
        if c[k] > best:
            best, bxy = int(c[k]), (float(offs[k, 0]), float(offs[k, 1]))
    # THE REFINE STEP IS THE RESIDUAL FLOOR. A 0.75pt grid is 0.5 real
    # inches, so a coarse refine makes the reported RMS a measurement of the
    # SEARCH rather than of the drawings. Two passes: 0.75pt to place it,
    # then 0.05pt (0.033in) so the grid is an order of magnitude finer than
    # anything being reported.
    for fine, rng_ in ((0.75, 7), (0.05, 16)):
        g = np.arange(-rng_, rng_ + 1) * fine
        offs = np.array([(bxy[0] + i, bxy[1] + j) for i in g for j in g])
        c = _match_counts(tree, A, offs, r)
        k = int(np.argmax(c))
        if c[k] > best:
            best, bxy = int(c[k]), (float(offs[k, 0]), float(offs[k, 1]))
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
    display space. `page` is a lib.plan_page.PlanPage."""
    segs = display_segments(page)
    return {"segs": segs, "att": attributed_segments(page),
            "corners": viewport(corners(segs), page.width, segs, page.height),
            "words": list(page.words), "page": (page.width, page.height),
            "rotation": page.rotation}


def plan_unit_tags(corners_arr, words, unit_tags: Sequence[str],
                   inside=None) -> Dict[str, Tuple[float, float]]:
    """The unit tags ON THE PLAN, not in the occupancy table.

    A-103.00 prints 4A-4D twice: on the plan and in the LIGHT & AIR /
    OCCUPANCY tables. The first occurrence inside the plan's corner extent
    (1st-99th percentile) is the plan's. A dict comprehension once kept the
    LAST - the table - and every placement came back 491-782in off.

    ── FIRST IN THE EXTENT WAS THE PLAN'S BY LAYOUT, NOT BY RULE ──────────

    Measured 2026-10-24 over every architectural plan sheet with unit tags
    (22 read, 15 tagged): on two - the filed mezzanine A-104.00 (AR 3.28.25)
    and the second set's A.1.5 - the occupancy table sits INSIDE the corner
    extent and comes first, so 4A-4D were "placed" in table cells outside
    the building and got no region (8 tags). So the caller that has the
    room map passes `inside(x, y)`: an occurrence in a room of the plan is
    preferred over one outdoors or on a wall. With no occurrence inside, or
    no predicate, the first in the extent stands, as before.
    """
    lo, hi = np.percentile(corners_arr, [1, 99], axis=0)
    wanted = set(unit_tags)
    first: Dict[str, Tuple[float, float]] = {}
    indoors: Dict[str, Tuple[float, float]] = {}
    for t, x, y in words:
        if t in wanted and lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1]:
            first.setdefault(t, (x, y))
            if inside is not None and t not in indoors and inside(x, y):
                indoors[t] = (x, y)
    return {t: indoors.get(t, p) for t, p in first.items()}


def census_grid(A, B, span_pt=360.0, radius_in=1.0, chunk=64):
    """(votes, seed, S): offset_census's whole vote grid - votes[i, j] are
    the anchors the offset seed + (i - S, j - S) matches."""
    A, B = np.asarray(A, dtype=float), np.asarray(B, dtype=float)
    r = _pts(radius_in)
    seed = _seed(A, B)
    S = int(span_pt)
    n = 2 * S + 1
    # a lattice cell within r of d lies between floor(d) - floor(r) and
    # floor(d) + floor(1 + r), per axis
    k = np.arange(-int(math.floor(r)), int(math.floor(1 + r)) + 1)
    offs = np.array([(i, j) for i in k for j in k])
    votes = np.zeros(n * n, dtype=np.int64)
    for s in range(0, len(A), chunk):
        a = A[s:s + chunk]
        d = B[None, :, :] - a[:, None, :] - seed
        who = np.broadcast_to(np.arange(len(a))[:, None], d.shape[:2])
        near = (np.abs(d) <= S + r + 1).all(-1)
        d, who = d[near], who[near]
        cells = np.floor(d).astype(np.int64)[:, None, :] + offs[None, :, :]
        ok = (np.hypot(*(cells - d[:, None, :]).transpose(2, 0, 1)) <= r)             & (np.abs(cells) <= S).all(-1)
        cell = (cells[..., 0] + S) * n + (cells[..., 1] + S)
        # one vote per corner per cell, however many of B it is near there
        key = np.unique(np.broadcast_to(who[:, None], ok.shape)[ok] * (n * n)
                        + cell[ok])
        votes += np.bincount(key % (n * n), minlength=n * n)
    return votes.reshape(n, n), seed, S


#: the second peak is the strongest offset more than this from the best
#: (pt): four real inches, past the best peak's own slope (every Boyland
#: peak falls to 4-16% of its height 2pt off)
SECOND_PEAK_EXCL_PT = 6.0


def second_peak(votes) -> int:
    """The anchors of the strongest offset more than SECOND_PEAK_EXCL_PT
    from the best one: how nearly ANOTHER alignment fits."""
    i, j = np.unravel_index(int(np.argmax(votes)), votes.shape)
    ii, jj = np.ogrid[:votes.shape[0], :votes.shape[1]]
    far = np.hypot(ii - i, jj - j) > SECOND_PEAK_EXCL_PT
    return int(votes[far].max()) if far.any() else 0


def offset_census(A, B, span_pt=360.0, radius_in=1.0, chunk=64):
    """(count, (dx, dy)): the best offset on a 1pt lattice over the same
    window best_translation searches, found ANOTHER WAY - each corner of A
    votes once for every lattice offset that would put it within the match
    radius of some corner of B. A cell's votes are exactly the anchors that
    offset matches; no sample is skipped, so no peak can be stepped over.

    It is the independent second reading the registration is checked
    against: a search that lands on a coincidental peak disagrees with it."""
    votes, seed, S = census_grid(A, B, span_pt, radius_in, chunk)
    n = votes.shape[0]
    top = int(np.argmax(votes))
    i, j = divmod(top, n)
    return int(votes.flat[top]), (float(seed[0] + i - S), float(seed[1] + j - S))


def plan_extent(sheet: dict):
    """(lo, hi) of the architectural sheet's WALL layer (plan_space_layers
    roles), or None when it has none.

    ANCHOR SPREAD IS MEASURED AGAINST THE PLAN, NOT THE VIEWPORT (ruling
    2026-10-10). The viewport's corners include the notes and the tables:
    against them every correct Boyland registration spanned 0.39 in y and
    plan_registration.MIN_ANCHOR_SPREAD_FRAC refused them all. Against the
    wall layer the correct pairs span 1.00 x 1.00 (the roof 1.00 x 0.68:
    A-105.01 draws the bulkhead plan beside the roof). Long segments were
    tried as a fallback and span 0.39 again - tables and dimension lines
    are long too - so a sheet with no wall layer has NO plan extent, and
    its spread is not measured (register records that; see there)."""
    from lib.plan_space_layers import role_of     # it imports this module
    walls = [s for s, layer in sheet.get("att") or () if role_of(layer) == "wall"]
    if not walls:
        return None
    a = np.asarray(walls, dtype=float).reshape(-1, 2)
    return a.min(0), a.max(0)


def register(arch: dict, mech: dict) -> dict:
    """Translation arch->mech by corner matching, and whether room membership
    may be decided on it (plan_registration tolerances, never changed here).

    A REGISTRATION IS THE BEST PEAK OR IT IS REFUSED (ruling 2026-10-10).
    Residuals cannot tell: they are taken over the anchors matched within
    ANCHOR_MATCH_RADIUS_IN, so for ANY offset the worst is under an inch, and
    the roof's wrong peak had the LOWER rms (0.03in vs 0.80in at the true
    one). So every registration records the anchors its offset holds and
    the best peak offset_census finds, and placement is refused when the
    offset holds under HALF the best - a comparison between two readings,
    not a constant fitted to the pairs measured. Count and spread
    (registration_verdict, against plan_extent) must hold too; spread is a
    condition, not the discriminator - it did not separate either failure.

    A SHEET WITH NO WALL LAYER HAS NO PLAN TO MEASURE SPREAD AGAINST, so
    spread is recorded as not measured and the other conditions still
    decide. Refusing instead would close the geometric pipeline, which
    exists for exactly those sheets and is ruled REPORTED, NOT GATED
    (operator 2026-10-06; test_a_unit_is_answered_or_refused_never_wrong)."""
    A = np.asarray(arch["corners"], dtype=float)
    B = np.asarray(mech["corners"], dtype=float)
    (dx, dy), matched, _b, dist = best_translation(
        A, B, radius_in=reg.ANCHOR_MATCH_RADIUS_IN)
    votes, seed, S = census_grid(A, B, radius_in=reg.ANCHOR_MATCH_RADIUS_IN)
    top = int(np.argmax(votes))
    i, j = divmod(top, votes.shape[0])
    best_n, best_xy = int(votes.flat[top]), (float(seed[0] + i - S), float(seed[1] + j - S))
    n = int(len(dist))
    res = (np.array([inches(x) for x in dist]) if n else np.array([np.inf]))
    rms, mx = float(math.sqrt((res ** 2).mean())), float(res.max())
    refused = []
    if 2 * n < best_n:
        refused.append(f"the offset holds {n} anchors, under half the "
                       f"{best_n} of the best peak at ({best_xy[0]:.1f}, "
                       f"{best_xy[1]:.1f})")
    extent, spread = plan_extent(arch), None
    if extent is not None:
        lo, hi = extent
        if n:
            got = (np.minimum(matched.max(0), hi) - np.maximum(matched.min(0), lo))
            spread = np.clip(got / np.maximum(hi - lo, 1e-9), 0.0, 1.0)
        else:
            spread = np.zeros(2)
    # no wall layer: spread unmeasured, so the verdict judges count and
    # residuals only (a full span stands in for the missing measurement)
    sx, sy = (1.0, 1.0) if spread is None else (float(spread[0]), float(spread[1]))
    verdict, why = reg.registration_verdict(n, sx, sy, rms, mx)
    if verdict != "registered":
        refused.extend(why)
    if not reg.usable_for("room_membership", rms, max_residual_in=mx):
        refused.append(f"RMS {rms:.2f}in over the room-membership tolerance")
    return {"dx": float(dx), "dy": float(dy), "anchors": n,
            "rms_in": rms, "max_in": mx, "usable": not refused,
            "best_peak_anchors": best_n,
            "best_peak": [float(best_xy[0]), float(best_xy[1])],
            # recorded, never applied here: lib.plan_stacks.registration_usable
            # reads it (a second offset holding half the best is ambiguous)
            "second_peak_anchors": second_peak(votes),
            "spread": None if spread is None else [float(v) for v in spread],
            "refused": "; ".join(refused) or None}


# ══════════════════════════════════════════════════════════════════════════
# ONE OFFSET RULE FOR EVERY DISCIPLINE PAIR (operator ruling 2026-10-28)
# ══════════════════════════════════════════════════════════════════════════
#
#   "one function, T3's rule (single best peak agreeing with the exact 1pt
#   search, >=8 anchors) for all pairs, with each pair's margin shown on its
#   row. ... No tuned ratio threshold."
#
# register_offset is that function, for S->A and P->A (lib.plan_structural,
# lib.plan_stacks). register() above is unchanged: the glyph pass's M->A
# placements keep the rule they were rebuilt under.

#: the second peak is the strongest cell farther than this from the best.
#: Every peak measured on Boyland is NARROW (2pt off, 4-16% of its height):
#: one peak's own shoulder lies within the match radius plus one lattice
#: cell (2.5pt), so 6pt (4 real inches) is beyond any one peak.
SECOND_PEAK_EXCL_PT = 6.0


def peak_census(A, B, span_pt: float = 360.0, radius_in: float = 1.0,
                chunk: int = 64) -> dict:
    """offset_census's exact 1pt vote grid, read for its two strongest
    SEPARATED peaks: {"best": (n, (dx, dy)), "second": (n, (dx, dy))}."""
    A, B = np.asarray(A, dtype=float), np.asarray(B, dtype=float)
    r = _pts(radius_in)
    seed = _seed(A, B)
    S = int(span_pt)
    n = 2 * S + 1
    k = np.arange(-int(math.floor(r)), int(math.floor(1 + r)) + 1)
    offs = np.array([(i, j) for i in k for j in k])
    votes = np.zeros(n * n, dtype=np.int64)
    for s in range(0, len(A), chunk):
        a = A[s:s + chunk]
        d = B[None, :, :] - a[:, None, :] - seed
        who = np.broadcast_to(np.arange(len(a))[:, None], d.shape[:2])
        near = (np.abs(d) <= S + r + 1).all(-1)
        d, who = d[near], who[near]
        cells = np.floor(d).astype(np.int64)[:, None, :] + offs[None, :, :]
        ok = (np.hypot(*(cells - d[:, None, :]).transpose(2, 0, 1)) <= r) \
            & (np.abs(cells) <= S).all(-1)
        cell = (cells[..., 0] + S) * n + (cells[..., 1] + S)
        key = np.unique(np.broadcast_to(who[:, None], ok.shape)[ok] * (n * n) + cell[ok])
        votes += np.bincount(key % (n * n), minlength=n * n)
    g = votes.reshape(n, n)
    bi, bj = np.unravel_index(int(np.argmax(g)), g.shape)
    ii, jj = np.ogrid[:n, :n]
    masked = np.where(np.hypot(ii - bi, jj - bj) > SECOND_PEAK_EXCL_PT, g, -1)
    si, sj = np.unravel_index(int(np.argmax(masked)), g.shape)

    def at(i, j):
        return (float(seed[0] + i - S), float(seed[1] + j - S))
    return {"best": (int(g[bi, bj]), at(bi, bj)),
            "second": (max(int(masked[si, sj]), 0), at(si, sj))}


def register_offset(arch: dict, other: dict, *, coarse_pt: Optional[float] = None,
                    span_pt: float = 360.0) -> dict:
    """Translation arch -> other (other = arch + d) between two sheets
    ALREADY PAIRED BY TITLE (the fit never picks a floor), and whether it
    may be used. `arch` / `other` are load_sheet dicts ("corners").

    USABLE (one rule, any discipline; operator 2026-10-28):
      R1  the offset best_translation finds IS the exact census' best peak:
          within one match radius of it (the pre-#743 4pt search put S-104
          on A-103 45pt off, residuals under an inch - refused here)
      R2  that peak is SINGLE: the strongest cell beyond SECOND_PEAK_EXCL_PT
          holds fewer anchors (a tie is two placements the drawings support
          equally)
      R3  at least plan_registration.MIN_ANCHORS anchors
    No ratio threshold: `margin` (best / second) is reported, never compared.
    Residuals are recorded and decide nothing (usable_for cannot fail: they
    are taken within ANCHOR_MATCH_RADIUS_IN).

    Returns {"dx", "dy", "anchors", "rms_in", "max_in", "best_peak_anchors",
    "best_peak": [x, y], "second_peak_anchors", "second_peak": [x, y],
    "margin", "offset_from_best_pt", "sweep", "usable", "refused"}.
    `coarse_pt` runs the old search (tests); `span_pt` narrows the window."""
    A = np.asarray(arch["corners"], dtype=float).reshape(-1, 2)
    B = np.asarray(other["corners"], dtype=float).reshape(-1, 2)
    out: Dict[str, Any] = {"dx": None, "dy": None, "anchors": 0, "usable": False,
                           "margin": None}
    if len(A) < reg.MIN_ANCHORS or len(B) < reg.MIN_ANCHORS:
        out["refused"] = f"too few corners to register ({len(A)} / {len(B)})"
        return out
    kw = {} if coarse_pt is None else {"coarse_pt": coarse_pt}
    (dx, dy), _m, _b, dist = best_translation(A, B, span_pt=span_pt,
                                              radius_in=reg.ANCHOR_MATCH_RADIUS_IN, **kw)
    c = peak_census(A, B, span_pt=span_pt, radius_in=reg.ANCHOR_MATCH_RADIUS_IN)
    (bn, bxy), (sn, sxy) = c["best"], c["second"]
    n = int(len(dist))
    res = np.array([inches(x) for x in dist]) if n else np.array([np.inf])
    off_best = float(math.hypot(dx - bxy[0], dy - bxy[1]))
    refused = []
    if off_best > _pts(reg.ANCHOR_MATCH_RADIUS_IN):
        refused.append(f"the offset ({dx:.1f}, {dy:.1f}) holds {n} anchors and is "
                       f"{off_best:.1f}pt from the best peak ({bxy[0]:.1f}, {bxy[1]:.1f}), "
                       f"which holds {bn}")
    if sn >= bn:
        refused.append(f"two peaks tie: {bn} anchors at ({bxy[0]:.1f}, {bxy[1]:.1f}) and "
                       f"{sn} at ({sxy[0]:.1f}, {sxy[1]:.1f})")
    if n < reg.MIN_ANCHORS:
        refused.append(f"only {n} anchors, need {reg.MIN_ANCHORS}")
    out.update({"dx": float(dx), "dy": float(dy), "anchors": n,
                "rms_in": float(math.sqrt((res ** 2).mean())), "max_in": float(res.max()),
                "best_peak_anchors": bn, "best_peak": [bxy[0], bxy[1]],
                "second_peak_anchors": sn, "second_peak": [sxy[0], sxy[1]],
                "margin": round(bn / sn, 3) if sn else None,
                "offset_from_best_pt": round(off_best, 2),
                "sweep": f"exact 1pt census over +/-{span_pt:.0f}pt, radius "
                         f"{reg.ANCHOR_MATCH_RADIUS_IN}in",
                "usable": not refused, "refused": "; ".join(refused) or None})
    return out
