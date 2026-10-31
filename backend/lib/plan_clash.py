"""CLASH v1: plumbing against the lateral system, as a list of flags for an engineer.

Roy's spec (lane C1, 2026-10-29):

    "C1: flag both kinds, (a) pipe segments passing through a shear wall or
    braced frame (separately for those in the hold-down zone), (b) stacks/
    risers inside or within 2 in of a frame. [...] Every flag gets an overlay
    crop; label "flag for engineer review"."

    "Output a list with overlay images, labelled "flag for engineer review",
    never pass/fail."

── WHAT THIS IS, AND WHAT IT NEVER SAYS ──────────────────────────────────

The output is a LIST OF FLAGS and a LIST OF THINGS NOT CHECKED. There is no
verdict anywhere: no pass, no fail, no "clear", no "no clash". A frame with
nothing near it is simply absent from the flags - which says only that this
reading of these drawings put nothing there, not that the wall is clear. A
refused placement (a polygon or a footprint that is None) is a NOT CHECKED
entry carrying its reason, never silence: absence of a flag must never be
readable as a frame that was looked at and found clear.

Every flag says FLAG_LABEL. Whether a drawn pipe in a braced-frame line is a
real conflict (a drain in the wet-wall cavity beside the straps, or a pipe
through a chord stud) is the engineer's call, never this module's.

── INPUTS (both already in the ARCHITECTURAL page's display points) ─────────

  structure  lib.plan_structural rows (lane T3, #915): `element` shear_wall |
             braced_frame (the frames), hold_down (one per end of a shear
             wall), `polygon_a` in the A page's display pt or None with
             `placement="refused"` and `refused`; `attrs.drawn_as` at_level |
             below; `registration.margin`; `structure_note` on the owner's set
  plumbing   lib.plan_stacks rows (lane T4, #913): record_type "stack"
             (`footprint_arch` {type circle, x, y, r} or None) and
             "pipe_segments" (one per P sheet and track: `segments`
             [[x1, y1, x2, y2, system]] and `curves` [[[x, y]...], system], or
             None with `placement_refused`)

JOIN: (track, a_sheet.page_id) on both sides. Each side was paired to its A
plan by title level and series offset (S-1xx = A+1, P-2xx = A+1, P-1xx = A+0)
and registered by plan_sheet.register_offset (ruling 63); this module does
NOT re-pair or re-register - it reads both rows' A-frame geometry as given
and shows both pairs' registration margins on every flag.

── THE RULES (T3's rulings, 2026-10-28; Roy's spec) ──────────────────────────

  * the frames are shear_wall and braced_frame rows. A row drawn BELOW
    (`attrs.drawn_as == "below"`: the roof plan's dashed walls of the storey
    under it) is not this level's structure: it is skipped, and so are its
    hold-down zones - listed under "skipped", never flagged
  * S-10N's walls are the storey standing on level N - the same A plan the
    P sheet of that level pairs with, so the join already says which floor
  * (a) a pipe PIECE (one straight segment, or one curved piece as drawn)
    is flagged when any part of it lies inside or on the frame polygon
  * the HOLD-DOWN ZONE is the end-member post (T3: no buffer in the row) +
    TOL_WALL_SIDE_IN (2 in) applied here. A flagged piece within 2 in of
    an end post is ALSO listed in its own hold-down flag, with its distance
    (0 = the piece touches the post as drawn). Hold-downs are not drawn on
    the plans; each zone is the end post, S-302's details cited in `spec`
  * (b) a stack/riser footprint (a circle) inside, crossing, or within
    TOL_WALL_SIDE_IN of a frame polygon is flagged, with its distance
  * every flag on the owner's set (post_co) carries the structure rows'
    `structure_note` ("structure per filed set S-10x.00; the owner's set has
    no structural sheets")
  * RULING 116 (as-built): V-4 runs straight up; P-204's 23.8 in offset is a
    DRAFTING ERROR. When one sheet draws a stack away from where the other
    floors agree it is (more than TOL_IN from a position at least two other
    floors share, and held by fewer floors than the agreeing position), the
    stack is not a clash: it is a DRAWING INCONSISTENCY -
    "V-4 drawn 23.8 in off its stack position on P-204; other floors agree".
    The stack leaves the stack flag, and the pipe pieces that exist only
    because it was drawn off its line leave the pipe flags: those touching its
    footprint (within TOL_CLEARANCE_IN of the rim) and those that are an
    agreeing floor's piece moved by the stack's offset and not where that
    floor draws it (MATCH_PT). Both are listed on the inconsistency item,
    never dropped. The agreed
    position's relation to the frame is stated on the item. A stack whose
    floors do not agree with each other is not reclassified
  * RULING 117: there is no cellar. P-200 ("FIRST UNDERGROUND FLOOR") is the
    below-slab plumbing plan, not a storey: it is listed under "skipped" as
    a below-slab plan, never flagged and never read as a storey's clash

  * ROY'S RULING (2026-10-30, drawing tolerance): "a flag whose overlap is smaller
    than the sheet's registration residual must read "within drawing tolerance,
    verify on site", not a clash." Every flag carries its OVERLAP in inches
    and the REGISTRATION RESIDUAL of the pairs that place it, and an entry
    (a pipe piece, a stack) whose overlap is smaller than that residual is
    moved out of the flag into a separate kind, KIND_TOLERANCE, labelled
    TOLERANCE_LABEL, listing both numbers. It is never a clash flag and never
    dropped.

      OVERLAP   how far the thing reaches into the polygon its flag is about,
                in inches: the PENETRATION DEPTH, the shortest sideways move
                that takes it wholly clear of that polygon (0 when it only
                lies near it). A stack's footprint (a circle) against the
                frame: its radius plus the distance from its centre to the
                nearest face when the centre is inside, its radius less
                that distance when the centre is outside and the rim crosses
                the face. A pipe piece (a straight run, or a curved piece as
                drawn) against the frame: the least move that takes the
                piece off the frame, across the wall or out of its end. A
                hold-down entry is measured against the END POST, not the
                frame (the 2 in beside the post is the zone's own buffer, 0
                overlap). NOT the rim's clearance inside the face: a
                stack standing 1.3 in inside a face reaches 1.3 + its
                diameter in.
      RESIDUAL  how far a drawing's own registration can have moved the
                thing, in inches: the sum of the worst anchor residual
                (`max_in`) of the two registrations that place it, P->A (the
                plumbing sheet on its plan) and S->A (the frame on that
                plan). The two errors can add; a sum of the maxima is the
                bound. A row without `max_in` has no residual and the rule
                does not apply to it: it stays a flag.

Pure: no database, no network, no rendering. The overlay crops are drawn by
scripts/clash_report.py from these flags.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import plan_registration as reg
from lib.plan_sheet import PT_PER_INCH

#: the stored rows' shape; bump when a row's meaning changes
EMIT_VERSION = 1
#: where a pass would write them (designed, NOT written - see rows_for_store)
COLLECTION = "plan_clash"

#: every flag says this, verbatim (Roy, 2026-10-29)
FLAG_LABEL = "flag for engineer review"

KIND_PIPE = "pipe_through_frame"
KIND_HOLD_DOWN = "pipe_in_hold_down_zone"
KIND_STACK = "stack_at_frame"
KINDS = (KIND_PIPE, KIND_HOLD_DOWN, KIND_STACK)
#: Roy 2026-10-30: NOT a clash - an entry whose overlap is smaller than the registration residual
KIND_TOLERANCE = "within_drawing_tolerance"
TOLERANCE_LABEL = "within drawing tolerance, verify on site"
#: how the residual is made, stated on every item
RESIDUAL_RULE = "max_in(P->A) + max_in(S->A)"
#: ruling 116: NOT a clash - a stack drawn off where the other floors agree
KIND_INCONSISTENCY = "drawing_inconsistency"

#: the structural elements a pipe is checked against (Roy: "a shear wall or
#: braced frame"); a bearing wall is not one
FRAME_ELEMENTS = ("shear_wall", "braced_frame")

#: the side-of-wall tolerance (plan_registration: "WHICH SIDE OF THE WALL /
#: DOES THIS PENETRATE IT"), applied to the hold-down zone and to stacks
TOL_IN = reg.TOL_WALL_SIDE_IN

#: ruling 116: two readings of one stack agree within this; a drawn pipe piece
#: "touches" a stack's footprint within this of its rim
AGREE_IN = reg.TOL_WALL_SIDE_IN
TOUCH_IN = reg.TOL_CLEARANCE_IN

#: ruling 116: a drawn piece is "the same piece" on another floor within this (display pt;
#: one stack's pieces differ by <= 0.1 pt between floors, the measured fixture matches at 0.35)
MATCH_PT = 0.35

#: lib.plan_stacks.BELOW_SLAB, the level its below-slab rows carry
BELOW_SLAB_LEVEL = "BELOW_SLAB"
#: ruling 117: a refusal that names the below-slab plan (rows of an older pass)
_BELOW_SLAB = re.compile(r"underground|below[- ]slab|cellar", re.I)
BELOW_SLAB_NOTE = ("below-slab plumbing plan (ruling 117: there is no cellar; the first underground "
                   "floor is not a storey), not checked against a storey's lateral system")

#: a point on a boundary is ON it within this (display pt; rounding of the
#: rows is 0.01pt)
_EPS = 1e-6


# ══════════════════════════════════════════════════════════════════════════
# 1. Geometry (display pt; polygons are lists of [x, y], any simple polygon)
# ══════════════════════════════════════════════════════════════════════════

def _edges(poly: Sequence[Sequence[float]]):
    n = len(poly)
    for i in range(n):
        yield poly[i], poly[(i + 1) % n]


def point_seg_dist(p, a, b) -> float:
    ax, ay = a[0], a[1]
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    if L2 <= 0:
        return math.dist((p[0], p[1]), (ax, ay))
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.dist((p[0], p[1]), (ax + t * dx, ay + t * dy))


def point_in_poly(p, poly) -> bool:
    """Inside or ON the boundary (closed)."""
    if any(point_seg_dist(p, a, b) <= _EPS for a, b in _edges(poly)):
        return True
    x, y = p[0], p[1]
    inside = False
    for a, b in _edges(poly):
        if (a[1] > y) != (b[1] > y):
            xc = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < xc:
                inside = not inside
    return inside


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segs_intersect(p1, p2, q1, q2) -> bool:
    d1, d2 = _orient(q1, q2, p1), _orient(q1, q2, p2)
    d3, d4 = _orient(p1, p2, q1), _orient(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return True
    return (point_seg_dist(p1, q1, q2) <= _EPS or point_seg_dist(p2, q1, q2) <= _EPS
            or point_seg_dist(q1, p1, p2) <= _EPS or point_seg_dist(q2, p1, p2) <= _EPS)


def seg_poly_dist(a, b, poly) -> float:
    """0 when any part of segment ab lies inside or on the polygon; else the
    shortest distance between them."""
    if point_in_poly(a, poly) or point_in_poly(b, poly):
        return 0.0
    best = math.inf
    for q1, q2 in _edges(poly):
        if segs_intersect(a, b, q1, q2):
            return 0.0
        best = min(best, point_seg_dist(a, q1, q2), point_seg_dist(b, q1, q2),
                   point_seg_dist(q1, a, b), point_seg_dist(q2, a, b))
    return best


def path_poly_dist(points: Sequence[Sequence[float]], poly) -> float:
    """A polyline (a curved piece as drawn, its points in order) to a
    polygon: 0 when any part of it lies inside or on it."""
    pts = [p for p in points if p is not None]
    if not pts:
        return math.inf
    if len(pts) == 1:
        return 0.0 if point_in_poly(pts[0], poly) else min(
            point_seg_dist(pts[0], a, b) for a, b in _edges(poly))
    return min(seg_poly_dist(a, b, poly) for a, b in zip(pts, pts[1:]))


def boundary_dist(p, poly) -> float:
    return min(point_seg_dist(p, a, b) for a, b in _edges(poly))


def circle_relation(cx: float, cy: float, r: float, poly) -> Tuple[str, float]:
    """(relation, gap_pt) of a circle to a polygon: "inside" (wholly within),
    "crosses edge" (overlaps the boundary), or "outside" with the gap between
    the circle's rim and the polygon (0 for the first two)."""
    d = boundary_dist((cx, cy), poly)
    if point_in_poly((cx, cy), poly):
        return ("inside", 0.0) if d >= r else ("crosses edge", 0.0)
    if d <= r:
        return "crosses edge", 0.0
    return "outside", d - r


def _hull(points) -> List[Tuple[float, float]]:
    """Convex hull (monotone chain); a point or a segment comes back as itself."""
    pts_ = sorted({(float(p[0]), float(p[1])) for p in points if p is not None})
    if len(pts_) <= 2:
        return pts_

    def half(seq):
        out: List[Tuple[float, float]] = []
        for q in seq:
            while len(out) >= 2 and _orient(out[-2], out[-1], q) <= 0:
                out.pop()
            out.append(q)
        return out
    lo, up = half(pts_), half(reversed(pts_))
    return lo[:-1] + up[:-1]


def penetration_depth(points: Sequence[Sequence[float]], poly) -> float:
    """OVERLAP of a drawn piece with a polygon, in display pt: the shortest
    move that takes the piece wholly clear of it (the minimum translation
    distance, separating-axis form), 0 when they do not overlap or only touch.

    Both shapes are taken as their convex hulls: a curved piece's hull and a
    non-convex polygon's hull only ever contain more, so the depth is never
    understated (a frame is a rectangle in every row measured)."""
    a = _hull(poly)
    b = _hull(points)
    if len(a) < 3 or not b:
        return 0.0
    axes = []
    for shape in (a, b):
        n = len(shape)
        for i in range(n if n > 2 else 1):
            p, q = shape[i], shape[(i + 1) % n]
            dx, dy = q[0] - p[0], q[1] - p[1]
            L = math.hypot(dx, dy)
            if L > 0:
                axes.append((-dy / L, dx / L))
    best = math.inf
    for ax, ay in axes:
        pa = [ax * p[0] + ay * p[1] for p in a]
        pb = [ax * p[0] + ay * p[1] for p in b]
        a0, a1, b0, b1 = min(pa), max(pa), min(pb), max(pb)
        if b1 < a0 - _EPS or b0 > a1 + _EPS:
            return 0.0                       # apart on this axis
        best = min(best, a1 - b0, b1 - a0)
    return 0.0 if best is math.inf else max(0.0, best)


def circle_penetration(cx: float, cy: float, r: float, poly) -> float:
    """OVERLAP of a stack's footprint with a polygon, in display pt: its
    radius plus the distance of its centre inside the nearest face (a stack
    wholly inside reaches that far past the face), its radius less the
    distance when the centre is outside and the rim crosses the face, else 0."""
    d = boundary_dist((cx, cy), poly)
    if point_in_poly((cx, cy), poly):
        return r + d
    return max(0.0, r - d)


def bbox(poly) -> Tuple[float, float, float, float]:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def inches(pt: float) -> float:
    return pt / PT_PER_INCH


def pts(inch: float) -> float:
    return inch * PT_PER_INCH


# ══════════════════════════════════════════════════════════════════════════
# 2. The inputs, joined on (track, a_sheet.page_id)
# ══════════════════════════════════════════════════════════════════════════

def _a_page_id(row: dict) -> Optional[str]:
    a = row.get("a_sheet") or {}
    pid = a.get("page_id") or row.get("arch_page_id")
    return str(pid) if pid else None


def _sheet(ref: Optional[dict]) -> Optional[dict]:
    if not ref:
        return None
    return {k: ref.get(k) for k in ("page_id", "file_name", "page_number", "sheet_number",
                                    "sheet_title")}


def _margin_view(rg: Optional[dict]) -> Optional[dict]:
    if not rg:
        return None
    return {k: rg.get(k) for k in ("dx", "dy", "anchors", "best_peak_anchors",
                                   "second_peak_anchors", "margin", "rms_in", "max_in", "usable")}


def _is_below(row: dict) -> bool:
    return ((row.get("attrs") or {}).get("drawn_as") == "below")


def frames_by_page(structure: Iterable[dict]) -> Dict[str, Any]:
    """{"frames": {(track, a_page_id): [frame]}, "not_checked": [...],
    "skipped": [...]} - each frame with its hold-down zones attached.

    A frame drawn below is SKIPPED with its zones (T3's ruling: the roof
    plan's dashed walls are the storey under it). A frame whose polygon is
    None is NOT CHECKED, with the structure row's reason."""
    rows = list(structure)
    frames: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    not_checked, skipped = [], []
    zones: Dict[Tuple, List[dict]] = defaultdict(list)
    for r in rows:
        if r.get("element") == "hold_down":
            key = (r.get("track"), _a_page_id(r), str((r.get("s_sheet") or {}).get("page_id")),
                   r.get("tag"))
            zones[key].append(r)
    for r in rows:
        if r.get("element") not in FRAME_ELEMENTS:
            continue
        track, apid = r.get("track"), _a_page_id(r)
        spid = str((r.get("s_sheet") or {}).get("page_id"))
        if _is_below(r):
            skipped.append({"what": r.get("label"), "track": track, "level": r.get("level"),
                            "why": "drawn below: the walls of the storey under this plan "
                                   "(attrs.drawn_as=below), not this level's structure"})
            continue
        if not r.get("polygon_a"):
            not_checked.append(_not_checked(
                "frame", r.get("label"), track, r.get("level"), _sheet(r.get("a_sheet")),
                "the frame is not placed on the architectural plan: "
                + str(r.get("refused") or "no polygon in the A frame"),
                structure_note=r.get("structure_note")))
            continue
        hz = []
        for z in zones.get((track, apid, spid, r.get("tag")), []) if r.get("tag") else []:
            if not z.get("polygon_a"):
                not_checked.append(_not_checked(
                    "hold_down", z.get("label"), track, z.get("level"), _sheet(z.get("a_sheet")),
                    "the hold-down zone is not placed: " + str(z.get("refused") or "no polygon"),
                    structure_note=z.get("structure_note")))
                continue
            za = z.get("attrs") or {}
            hz.append({"end": za.get("end"), "polygon_a": z["polygon_a"],
                       "zone_from": za.get("zone_from"), "size": za.get("size"),
                       "spec": za.get("spec")})
        frames[(track, apid)].append({
            "label": r.get("label"), "element": r.get("element"), "tag": r.get("tag"),
            "level": r.get("level"), "track": track, "polygon_a": r["polygon_a"],
            "s_sheet": _sheet(r.get("s_sheet")), "a_sheet": _sheet(r.get("a_sheet")),
            "registration": _margin_view(r.get("registration")),
            "structure_note": r.get("structure_note"),
            "schedule": (r.get("attrs") or {}).get("schedule"),
            "hold_down_zones": hz,
            "hold_down_note": None if hz else (
                "no hold-down zone: an untagged braced frame has no schedule end members"
                if not r.get("tag") else "no hold-down zone placed for this wall")})
    return {"frames": dict(frames), "not_checked": not_checked, "skipped": skipped}


def _not_checked(what: str, label: Any, track: Any, level: Any, a_sheet: Optional[dict],
                 reason: str, **extra) -> dict:
    out = {"record_type": "clash_not_checked", "emit_version": EMIT_VERSION, "status": "not checked",
           "what": what, "label": label, "track": track, "level": level, "a_sheet": a_sheet,
           "reason": reason}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def page_key(ref: Optional[dict]) -> Optional[Tuple[str, int]]:
    """A sheet's identity for the residual join: (file id, page number). NOT the
    sheet name: the name is read from the title block and changes between passes
    (the gas-change first floor was A-100.01 in one and A-100.00 in the next), and
    two files can carry the same name (3.28.25 and the gas change both have an
    A-100.00). None when the ref lacks either part: such a ref matches nothing."""
    ref = ref or {}
    fid, pn = ref.get("file_id"), ref.get("page_number")
    if fid in (None, "") or pn in (None, ""):
        return None
    try:
        return (str(fid), int(pn))
    except (TypeError, ValueError):
        return None


def with_s_residuals(structure: Iterable[dict], pairs: Iterable[dict]) -> List[dict]:
    """Structure rows with their S->A registration's `rms_in` / `max_in` filled in
    from the track summary's pairs (`run_track(...)["summary"]["pairs"]`), which
    keep the whole registration while each ROW's `registration` carries only
    dx, dy, anchors, margin and the wall check. Matched on (S page, A page) where a
    page is (file id, page number) - never the sheet NAME, which is re-read between
    passes and is not unique across files. A pair that carries no page refs (a cache
    from before they were kept) matches nothing, so its rows get no residual and the
    tolerance rule is not applied to them (never softened) rather than joined on a
    name that may be another sheet. A row that already carries them, or has no
    pair, is returned as it was. Nothing else about a row changes."""
    by = {}
    for p in pairs:
        k = (page_key(p.get("s_sheet")), page_key(p.get("a_sheet")))
        if None not in k:
            by[k] = p.get("registration") or {}
    out = []
    for r in structure:
        rg = r.get("registration") or {}
        pair = by.get((page_key(r.get("s_sheet")), page_key(r.get("a_sheet"))))
        if pair and r.get("registration") is not None and rg.get("max_in") is None                 and pair.get("max_in") is not None:
            r = dict(r, registration=dict(rg, rms_in=pair.get("rms_in"), max_in=pair.get("max_in")))
        out.append(r)
    return out


def residual_for(p_to_a: Optional[dict], s_to_a: Optional[dict]) -> Optional[dict]:
    """The REGISTRATION RESIDUAL of an entry, in inches: RESIDUAL_RULE, the sum of
    the worst anchor residual of the two registrations that place it (the
    plumbing sheet on its plan, the frame on that plan), each kept beside it with
    its rms. None when either `max_in` is missing: the rule then does not apply."""
    pm = (p_to_a or {}).get("max_in")
    sm = (s_to_a or {}).get("max_in")
    if pm is None or sm is None:
        return None
    return {"rule": RESIDUAL_RULE, "residual_in": round(float(pm) + float(sm), 3),
            "p_to_a_max_in": round(float(pm), 3), "s_to_a_max_in": round(float(sm), 3),
            "p_to_a_rms_in": (p_to_a or {}).get("rms_in"), "s_to_a_rms_in": (s_to_a or {}).get("rms_in")}


def within_tolerance(overlap_in: float, residual: Optional[dict]) -> bool:
    """Roy's rule: the overlap is smaller than the registration residual."""
    return residual is not None and overlap_in < residual["residual_in"]


# ══════════════════════════════════════════════════════════════════════════
# 3. The check
# ══════════════════════════════════════════════════════════════════════════

def _pieces(prow: dict):
    """(kind, index, points, system) for every piece a pipe_segments row draws."""
    for i, s in enumerate(prow.get("segments") or []):
        yield "straight", i, [[s[0], s[1]], [s[2], s[3]]], (s[4] if len(s) > 4 else None)
    for i, c in enumerate(prow.get("curves") or []):
        yield "curved", i, [list(p) for p in c[0]], (c[1] if len(c) > 1 else None)


def _flag_id(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


def _plumbing_ref(prow: dict) -> dict:
    return {"sheet_number": prow.get("plumbing_sheet"), "page_id": prow.get("plumbing_page_id"),
            "registration": _margin_view(prow.get("registration"))}


def _numbered(item: dict, entries: Sequence[dict], residual: Optional[dict]) -> dict:
    """The two numbers Roy's rule reads, on the item itself: `overlap_in`, the
    deepest of its entries, and the `residual` (RESIDUAL_RULE, with both
    registrations' numbers) with `residual_in`. A stack item's entries come from
    sheets with their own P->A: each entry carries its own residual and the item
    shows the smallest, None when any has none."""
    item["overlap_in"] = max((e["overlap_in"] for e in entries), default=0.0)
    if residual is None and entries and "residual" in entries[0]:
        rs = [e["residual"] for e in entries]
        residual = None if any(r is None for r in rs) else min(rs, key=lambda r: r["residual_in"])
    item["residual"] = residual
    item["residual_in"] = None if residual is None else residual["residual_in"]
    for e in entries:           # both numbers on every entry, not only on the item
        r = e.get("residual", residual)
        e["residual_in"] = None if r is None else r["residual_in"]
    item["residual_rule"] = RESIDUAL_RULE if residual is not None else (
        "not applied: the frame's or the sheet's registration carries no max_in")
    return item


def _base(kind: str, frame: dict, prow: dict, tol_in: float) -> dict:
    tolerance = kind == KIND_TOLERANCE
    return {"record_type": "clash_within_tolerance" if tolerance else "clash_flag",
            "emit_version": EMIT_VERSION, "label": TOLERANCE_LABEL if tolerance else FLAG_LABEL,
            "kind": kind, "track": frame["track"], "level": frame["level"],
            "a_sheet": frame["a_sheet"], "frame": {k: frame[k] for k in (
                "label", "element", "tag", "polygon_a", "s_sheet", "registration", "schedule",
                "hold_down_zones", "hold_down_note")},
            "plumbing": _plumbing_ref(prow),
            "registration_margins": {
                "s_to_a": (frame.get("registration") or {}).get("margin"),
                "p_to_a": ((prow.get("registration") or {}).get("margin"))},
            "structure_note": frame.get("structure_note"), "tolerance_in": tol_in}


def _series(sheet: Any) -> str:
    m = re.search(r"-\s*(\d)", str(sheet or ""))
    return m.group(1) if m else ""


def stack_inconsistencies(plumbing: Iterable[dict], *, agree_in: float = AGREE_IN) -> Dict[Tuple, dict]:
    """RULING 116: {(track, plumbing_sheet, tag_id): info} for every stack one
    sheet draws away from where the other floors agree it is.

    The readings of a tag are its `footprint_arch` centres on the sheets of
    ONE series of ONE track (all in the A frame, which the floors share). A
    sheet is inconsistent when the OTHER sheets' largest group of readings
    that agree with each other (within agree_in) has no rival group of equal
    size, this sheet's reading is more than agree_in from it, and the group
    has more sheets than draw the tag where this one does (so at least two:
    one other floor is not "the floors agree"). This sheet's own position may
    be repeated on other sheets (P-205 repeats P-204's V-4) and is still
    outvoted. A tie, or floors that do not agree with each other, reclassify
    nothing. A sheet that draws the tag twice is ambiguous and is not compared."""
    tol = pts(agree_in)
    readings: Dict[Tuple, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in plumbing:
        fp = r.get("footprint_arch")
        if r.get("record_type") == "stack" and fp and r.get("tag_id"):
            readings[(r.get("track"), _series(r.get("plumbing_sheet")), r["tag_id"])][
                str(r.get("plumbing_sheet"))].append(r)
    out: Dict[Tuple, dict] = {}
    for (track, _ser, tag), by_sheet in readings.items():
        single = {sh: rs[0]["footprint_arch"] for sh, rs in by_sheet.items() if len(rs) == 1}
        for sheet, fp in single.items():
            others = sorted((sh, f) for sh, f in single.items() if sh != sheet)
            groups: List[List[Tuple[str, dict]]] = []
            for sh, f in others:
                for g in groups:
                    if math.dist((f["x"], f["y"]), (g[0][1]["x"], g[0][1]["y"])) <= tol:
                        g.append((sh, f))
                        break
                else:
                    groups.append([(sh, f)])
            if not groups:
                continue
            groups.sort(key=len, reverse=True)
            best = groups[0]
            if len(groups) > 1 and len(groups[1]) == len(best):
                continue       # the other floors split evenly: they agree on nothing
            ax = sum(f["x"] for _, f in best) / len(best)
            ay = sum(f["y"] for _, f in best) / len(best)
            off = math.dist((fp["x"], fp["y"]), (ax, ay))
            if off <= tol:
                continue
            same = sorted(sh for sh, f in others
                          if math.dist((f["x"], f["y"]), (fp["x"], fp["y"])) <= tol)
            if len(best) <= 1 + len(same):
                continue
            out[(track, sheet, tag)] = {
                "tag_id": tag, "plumbing_sheet": sheet, "track": track,
                "drawn": {"x": fp["x"], "y": fp["y"], "r": fp["r"]},
                "agreed": {"x": round(ax, 2), "y": round(ay, 2), "r": fp["r"]},
                "offset_in": round(inches(off), 1), "agree_sheets": sorted(sh for sh, _ in best),
                "repeated_on": same}
    return out


def inconsistency_message(info: dict) -> str:
    """Roy's wording (ruling 116), generalised."""
    return (f"{info['tag_id']} drawn {info['offset_in']:g} in off its stack position on "
            f"{info['plumbing_sheet']}; other floors agree")


def _touches_circle(points: Sequence[Sequence[float]], c: dict, touch_pt: float) -> bool:
    """A drawn piece lies on the stack's footprint: within touch_pt of its rim."""
    pts_ = [p for p in points if p is not None]
    if len(pts_) == 1:
        d = math.dist((pts_[0][0], pts_[0][1]), (c["x"], c["y"]))
    else:
        d = min(point_seg_dist((c["x"], c["y"]), a, b) for a, b in zip(pts_, pts_[1:]))
    return d - c["r"] <= touch_pt


def _same_piece(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]], dx: float = 0.0,
                dy: float = 0.0, tol: float = MATCH_PT) -> bool:
    """Piece a, moved by (dx, dy), is piece b (in either direction of drawing)."""
    if len(a) != len(b):
        return False
    for bb in (b, b[::-1]):
        if all(abs(p[0] + dx - q[0]) <= tol and abs(p[1] + dy - q[1]) <= tol for p, q in zip(a, bb)):
            return True
    return False


def moves_with_stack(points: Sequence[Sequence[float]], system: Any, info: dict,
                     floors: Dict[Tuple, List[Tuple[Any, list]]]) -> bool:
    """RULING 116: this piece EXISTS ONLY BECAUSE the stack was drawn off its line - it is
    one of the agreeing floors' pieces moved by the stack's offset (the whole run of
    pipework drawn around the riser), and it is not where those floors draw it. A piece
    that sits where an agreeing floor draws it is the same pipe on every floor."""
    ox = info["drawn"]["x"] - info["agreed"]["x"]
    oy = info["drawn"]["y"] - info["agreed"]["y"]
    moved = False
    for sh in info["agree_sheets"]:
        for sysm, q in floors.get((info["track"], sh), ()):
            if sysm != system:
                continue
            if _same_piece(points, q):
                return False
            if _same_piece(points, q, -ox, -oy):
                moved = True
    return moved


def _below_slab_text(*texts: Any) -> bool:
    return any(_BELOW_SLAB.search(str(t)) for t in texts if t)


def check(structure: Iterable[dict], plumbing: Iterable[dict], *,
          tol_in: float = TOL_IN) -> Dict[str, Any]:
    """{"flags", "inconsistencies", "not_checked", "skipped", "summary"} - the
    whole of clash v1.

    flags          one per (track, level, frame, plumbing sheet, pipe system) for
                   pipe pieces through a frame (KIND_PIPE), the same group's
                   pieces within tol_in of an end post (KIND_HOLD_DOWN), and
                   one per (track, level, frame) for stacks inside / crossing /
                   within tol_in of it (KIND_STACK). Each says FLAG_LABEL.
    inconsistencies ruling 116: a stack one sheet draws off where the other
                   floors agree it is, with the pipe pieces drawn on its
                   footprint - instead of a clash flag. One per (frame, stack).
    not_checked    every refused placement, with its reason: a frame or a
                   hold-down zone without a polygon, a plumbing sheet's pipes
                   without an A placement, a stack without a footprint, and a
                   frame on an A plan no plumbing sheet was placed on.
    skipped        frames drawn below (not this level's structure) and the
                   below-slab plan (ruling 117: not a storey).
    within_tolerance  Roy 2026-10-30: the entries (pipe pieces, stacks) of a flag
                   whose OVERLAP is smaller than the REGISTRATION RESIDUAL
                   (module docstring), in items of their own - same grouping as
                   the flag they left, `of_kind` naming it, label
                   TOLERANCE_LABEL, both numbers on the item and on each entry.
                   Never a clash flag, never dropped.
    """
    tol = pts(tol_in)
    plumbing = list(plumbing)
    slab: Dict[Tuple, dict] = {}

    def below_slab(r, what):
        d = slab.setdefault((r.get("track"), r.get("plumbing_sheet")), {"pipes": 0, "stacks": 0})
        d[what] += 1

    # A ROW THAT SAYS IT IS BELOW THE SLAB IS SKIPPED, PLACED OR NOT (ruling
    # 117; lib.plan_stacks writes level "BELOW_SLAB" on a below-slab plan's
    # stack and pipe_segments rows, which ARE placed on the first-floor A
    # plan for their offset). Taken out first, so neither the frame test nor
    # ruling 116's cross-floor comparison ever sees them. Rows of an older
    # pass carry no level and go by their refusal text below.
    kept = []
    for r in plumbing:
        if r.get("level") == BELOW_SLAB_LEVEL and r.get("record_type") in ("pipe_segments", "stack"):
            below_slab(r, "pipes" if r.get("record_type") == "pipe_segments" else "stacks")
        else:
            kept.append(r)
    plumbing = kept
    fb = frames_by_page(structure)
    frames = fb["frames"]
    not_checked = list(fb["not_checked"])
    skipped = list(fb["skipped"])
    flags: List[dict] = []
    incons: List[dict] = []
    tol_items: List[dict] = []
    off_stacks = stack_inconsistencies(plumbing)
    prow_pages: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    stacks_pages: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in plumbing:
        rt = r.get("record_type")
        if rt == "pipe_segments":
            if r.get("segments") is None and r.get("curves") is None:
                if _below_slab_text(r.get("placement_refused")):
                    below_slab(r, "pipes")
                    continue
                not_checked.append(_not_checked(
                    "pipes", f"{r.get('plumbing_sheet')} pipes", r.get("track"), None,
                    _sheet(r.get("a_sheet")), "the plumbing sheet's pipes are not placed on an "
                    "architectural plan: " + str(r.get("placement_refused") or "no placement"),
                    plumbing_sheet=r.get("plumbing_sheet")))
                continue
            prow_pages[(r.get("track"), _a_page_id(r))].append(r)
        elif rt == "stack":
            fp = r.get("footprint_arch")
            if not fp:
                if _below_slab_text(r.get("placement_refused"), r.get("reason")):
                    below_slab(r, "stacks")
                    continue
                not_checked.append(_not_checked(
                    "stack", f"{r.get('plumbing_sheet')} {r.get('tag_id') or 'tag unread'}",
                    r.get("track"), None, _sheet(r.get("a_sheet")),
                    "the stack has no footprint on an architectural plan: "
                    + str(r.get("placement_refused") or r.get("reason") or r.get("status")),
                    plumbing_sheet=r.get("plumbing_sheet"), stack_status=r.get("status")))
                continue
            stacks_pages[(r.get("track"), _a_page_id(r))].append(r)
        elif rt == "stack_sheet" and r.get("status") == "failed":
            if _below_slab_text(r.get("reason")):
                below_slab(r, "stacks")
                continue
            not_checked.append(_not_checked(
                "plumbing sheet", r.get("plumbing_sheet"), r.get("track"), None, None,
                "the stack pass failed on this sheet: " + str(r.get("reason")),
                plumbing_sheet=r.get("plumbing_sheet")))
    for (track, sheet), d in sorted(slab.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        skipped.append({"what": f"{sheet} " + " and ".join(
            k for k in ("pipes", "stacks") if d[k]), "track": track, "level": "below slab",
            "plumbing_sheet": sheet, "pipe_rows": d["pipes"], "stack_rows": d["stacks"],
            "why": BELOW_SLAB_NOTE})
    # every frame on a plan no plumbing sheet reached: not checked, by name
    for key, fs in frames.items():
        if key not in prow_pages and key not in stacks_pages:
            for f in fs:
                not_checked.append(_not_checked(
                    "frame", f["label"], f["track"], f["level"], f["a_sheet"],
                    "no plumbing sheet is placed on this architectural plan",
                    structure_note=f.get("structure_note")))
    for key, prs in prow_pages.items():
        if key not in frames:
            for prow in prs:
                not_checked.append(_not_checked(
                    "pipes", f"{prow.get('plumbing_sheet')} pipes", key[0], None,
                    _sheet(prow.get("a_sheet")),
                    "no shear wall or braced frame is placed on this architectural plan "
                    "(no structural sheet paired, every frame refused, or every frame drawn below)",
                    plumbing_sheet=prow.get("plumbing_sheet")))
    touch = pts(TOUCH_IN)
    floors: Dict[Tuple, List[Tuple[Any, list]]] = defaultdict(list)
    if off_stacks:
        for r in plumbing:
            if r.get("record_type") == "pipe_segments" and not (
                    r.get("segments") is None and r.get("curves") is None):
                for _k, _i, q, sysm in _pieces(r):
                    floors[(r.get("track"), str(r.get("plumbing_sheet")))].append((sysm, q))
    for key, fs in frames.items():
        for f in fs:
            poly = f["polygon_a"]
            # stacks near this frame; ruling 116 sets aside those their sheet draws off the agreed line
            near, off_here = [], []
            for s in stacks_pages.get(key, []):
                fp = s["footprint_arch"]
                rel, gap = circle_relation(fp["x"], fp["y"], fp["r"], poly)
                if rel == "outside" and gap > tol:
                    continue
                hd = [(circle_relation(fp["x"], fp["y"], fp["r"], z["polygon_a"])[1], z.get("end"))
                      for z in f["hold_down_zones"]]
                hdd, hend = min(hd, key=lambda t: t[0]) if hd else (None, None)
                entry = {"tag_id": s.get("tag_id"), "plumbing_sheet": s.get("plumbing_sheet"),
                         "plumbing_page_id": s.get("plumbing_page_id"),
                         "x": fp["x"], "y": fp["y"], "r": fp["r"],
                         "pipe_systems": s.get("pipe_systems"), "relation": rel,
                         "distance_in": round(inches(gap), 2),
                         # inside: how far the rim stands from the nearest face
                         "edge_clearance_in": (round(inches(boundary_dist((fp["x"], fp["y"]), poly)
                                                              - fp["r"]), 2)
                                               if rel == "inside" else None),
                         "hold_down_in": None if hdd is None else round(inches(hdd), 2),
                         "hold_down_end": hend if hdd is not None and hdd <= tol else None,
                         "overlap_in": round(inches(circle_penetration(fp["x"], fp["y"], fp["r"], poly)), 2),
                         "p_to_a": _margin_view(s.get("registration"))}
                entry["residual"] = residual_for(entry["p_to_a"], f.get("registration"))
                info = off_stacks.get((s.get("track"), str(s.get("plumbing_sheet")), s.get("tag_id")))
                if info:
                    off_here.append((entry, info))
                else:
                    near.append(entry)
            seen_off = set()
            for prow in prow_pages.get(key, []):
                groups: Dict[Any, List[dict]] = defaultdict(list)
                reclass: List[Tuple[dict, dict]] = []
                for kind, i, ptsl, system in _pieces(prow):
                    if path_poly_dist(ptsl, poly) > 0:
                        continue
                    hd = [(path_poly_dist(ptsl, z["polygon_a"]), z.get("end"))
                          for z in f["hold_down_zones"]]
                    d, end = min(hd, key=lambda t: t[0]) if hd else (None, None)
                    in_zone = d is not None and d <= tol
                    post = next((z["polygon_a"] for z in f["hold_down_zones"] if z.get("end") == end),
                                None) if in_zone else None
                    piece = {
                        "piece": kind, "index": i,
                        "points": [[round(p[0], 2), round(p[1], 2)] for p in ptsl],
                        "hold_down_in": None if d is None else round(inches(d), 2),
                        "hold_down_end": end if in_zone else None,
                        "overlap_in": round(inches(penetration_depth(ptsl, poly)), 2),
                        # against the end post itself (0: only within the zone's 2 in)
                        "post_overlap_in": (round(inches(penetration_depth(ptsl, post)), 2)
                                            if post else None)}
                    owner = next((inf for e, inf in off_here
                                  if e["plumbing_sheet"] == prow.get("plumbing_sheet")
                                  and (_touches_circle(ptsl, e, touch)
                                       or moves_with_stack(ptsl, system, inf, floors))), None)
                    if owner:
                        reclass.append((dict(piece, system=system or "unknown"), owner))
                        continue
                    groups[system or "unknown"].append(piece)
                resid = residual_for(_margin_view(prow.get("registration")), f.get("registration"))
                for system, pieces in sorted(groups.items()):
                    gid = (f["track"], key[1], f["label"], prow.get("plumbing_sheet"), system)
                    # the frame: each piece against the frame polygon; the hold-down
                    # zone: each piece in it against the END POST (0: only within the 2 in)
                    by_kind = ((KIND_PIPE, list(pieces)),
                               (KIND_HOLD_DOWN, [dict(p, overlap_in=p["post_overlap_in"])
                                                 for p in pieces if p["hold_down_end"]]))
                    for kind_, ps in by_kind:
                        keep = [p for p in ps if not within_tolerance(p["overlap_in"], resid)]
                        tolr = [p for p in ps if within_tolerance(p["overlap_in"], resid)]
                        for part, out_list, kd in ((keep, flags, kind_), (tolr, tol_items, KIND_TOLERANCE)):
                            if not part:
                                continue
                            base = _base(kd, f, prow, tol_in)
                            base["system"] = system
                            base["of_kind"] = kind_ if kd == KIND_TOLERANCE else None
                            fid = (_flag_id(KIND_TOLERANCE, kind_, *gid) if kd == KIND_TOLERANCE
                                   else _flag_id(kind_, *gid))
                            out_list.append(_numbered(
                                dict(base, flag_id=fid, pieces=part, counts=_counts(part, tol_in)),
                                part, resid))
                for e, info in off_here:
                    if e["plumbing_sheet"] == prow.get("plumbing_sheet") and id(info) not in seen_off:
                        seen_off.add(id(info))
                        incons.append(_inconsistency(
                            f, prow, e, info, [p for p, owner in reclass if owner is info], tol_in))
            # an off-line stack whose sheet drew no pipes here: still an inconsistency item
            for e, info in off_here:
                if id(info) not in seen_off:
                    seen_off.add(id(info))
                    incons.append(_inconsistency(
                        f, {"plumbing_sheet": e["plumbing_sheet"],
                            "plumbing_page_id": e["plumbing_page_id"]}, e, info, [], tol_in))
            near.sort(key=lambda s: (str(s["plumbing_sheet"]), str(s["tag_id"]), s["y"], s["x"]))
            keep = [s for s in near if not within_tolerance(s["overlap_in"], s["residual"])]
            tolr = [s for s in near if within_tolerance(s["overlap_in"], s["residual"])]
            for part, out_list, kd in ((keep, flags, KIND_STACK), (tolr, tol_items, KIND_TOLERANCE)):
                if not part:
                    continue
                prs = {s["plumbing_sheet"] for s in part}
                tolerance = kd == KIND_TOLERANCE
                base = {"record_type": "clash_within_tolerance" if tolerance else "clash_flag",
                        "emit_version": EMIT_VERSION,
                        "label": TOLERANCE_LABEL if tolerance else FLAG_LABEL,
                        "kind": kd, "of_kind": KIND_STACK if tolerance else None,
                        "track": f["track"], "level": f["level"], "a_sheet": f["a_sheet"],
                        "frame": {k: f[k] for k in ("label", "element", "tag", "polygon_a", "s_sheet",
                                                    "registration", "schedule", "hold_down_zones",
                                                    "hold_down_note")},
                        "plumbing": {"sheet_number": ", ".join(sorted(prs))},
                        "registration_margins": {
                            "s_to_a": (f.get("registration") or {}).get("margin"),
                            "p_to_a": {s["plumbing_sheet"]: (s["p_to_a"] or {}).get("margin")
                                       for s in sorted(part, key=lambda s: str(s["plumbing_sheet"]))}},
                        "structure_note": f.get("structure_note"), "tolerance_in": tol_in}
                fid = _flag_id(KIND_STACK, f["track"], key[1], f["label"])
                out_list.append(_numbered(
                    dict(base, flag_id=_flag_id(KIND_TOLERANCE, fid) if tolerance else fid,
                         stacks=part, counts={"stacks": len(part)}), part, None))
    flags.sort(key=_flag_order)
    incons.sort(key=_flag_order)
    tol_items.sort(key=_flag_order)
    return {"flags": flags, "inconsistencies": incons, "within_tolerance": tol_items,
            "not_checked": not_checked, "skipped": skipped,
            "summary": summarize(flags, not_checked, skipped, incons, tol_items)}


def _inconsistency(f: dict, prow: dict, e: dict, info: dict, mine: Sequence[dict],
                   tol_in: float) -> dict:
    """Ruling 116's item: a drawing inconsistency, in place of a clash flag."""
    base = _base(KIND_INCONSISTENCY, f, prow, tol_in)
    base["record_type"] = "clash_inconsistency"
    rel, gap = circle_relation(info["agreed"]["x"], info["agreed"]["y"], info["agreed"]["r"],
                               f["polygon_a"])
    pieces = sorted(mine, key=lambda p: (p["system"], p["piece"], p["index"]))
    ag_overlap = round(inches(circle_penetration(info["agreed"]["x"], info["agreed"]["y"],
                                                 info["agreed"]["r"], f["polygon_a"])), 2)
    # the agreed position is what the other floors' sheets say; this sheet's own P->A is the best
    # stand-in for the residual of that reading, shown for information, never a verdict
    ag_resid = residual_for(_margin_view(e.get("p_to_a")), f.get("registration"))
    return dict(
        base, flag_id=_flag_id(KIND_INCONSISTENCY, f["track"], (f["a_sheet"] or {}).get("page_id"),
                               f["label"], e["plumbing_sheet"], e["tag_id"]),
        message=inconsistency_message(info),
        detail=(f"{info['tag_id']} sits {info['offset_in']:g} in from the position "
                f"{', '.join(info['agree_sheets'])} agree on"
                + (f"; also drawn at this position on {', '.join(info['repeated_on'])}"
                   if info["repeated_on"] else "")
                + ". Not reported as a clash: the drawn position is the drafting error (ruling 116). "
                f"At the agreed position the stack is "
                + (f"{round(inches(gap), 2)} in outside" if rel == "outside" else rel)
                + f" {f['label']}"),
        stack=e,
        agreed=dict(info["agreed"], relation=rel, distance_in=round(inches(gap), 2),
                    sheets=info["agree_sheets"], overlap_in=ag_overlap,
                    residual_in=None if ag_resid is None else ag_resid["residual_in"]),
        offset_in=info["offset_in"], same_position_on=info["repeated_on"],
        reclassified_pieces=pieces,
        counts={"reclassified_pieces": len(pieces),
                "straight": sum(1 for p in pieces if p["piece"] == "straight"),
                "curved": sum(1 for p in pieces if p["piece"] == "curved"),
                "in_hold_down_zone": sum(1 for p in pieces if p["hold_down_end"])})


def _counts(pieces: Sequence[dict], tol_in: float) -> dict:
    return {"pieces": len(pieces),
            "straight": sum(1 for p in pieces if p["piece"] == "straight"),
            "curved": sum(1 for p in pieces if p["piece"] == "curved"),
            "in_hold_down_zone": sum(1 for p in pieces if p["hold_down_end"]),
            "touching_end_post": sum(1 for p in pieces if p["hold_down_in"] == 0)}


_LEVEL_ORDER = ("FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "MEZZANINE", "ROOF", "BULKHEAD")


def _flag_order(f: dict):
    lv = f.get("level")
    return (str(f.get("track")), _LEVEL_ORDER.index(lv) if lv in _LEVEL_ORDER else 99,
            str((f.get("frame") or {}).get("label")),
            (KINDS + (KIND_INCONSISTENCY,)).index(f.get("of_kind") or f["kind"]),
            str((f.get("plumbing") or {}).get("sheet_number")), str(f.get("system")))


def _count_by(keys) -> Dict[str, int]:
    out: Dict[str, int] = defaultdict(int)
    for k in keys:
        out[k] += 1
    return dict(out)


def summarize(flags: Sequence[dict], not_checked: Sequence[dict], skipped: Sequence[dict],
              inconsistencies: Sequence[dict] = (), within_tol: Sequence[dict] = ()) -> dict:
    """Counts per (track, level, kind), and how many flags are the SAME
    PLACE on another floor (one frame tag and system, repeated per level)
    against how many distinct places there are. Never a verdict."""
    per = defaultdict(int)
    places = defaultdict(set)
    for f in flags:
        per[f"{f['track']}|{f['level']}|{f['kind']}"] += 1
        place = (f["frame"].get("tag") or f["frame"].get("label"), f["kind"], f.get("system"))
        places[(f["track"], f["kind"])].add(place)
    by_kind = defaultdict(int)
    for f in flags:
        by_kind[f"{f['track']}|{f['kind']}"] += 1
    return {"flags": len(flags), "by_track_level_kind": dict(sorted(per.items())),
            "by_track_kind": dict(sorted(by_kind.items())),
            "distinct_places": {f"{t}|{k}": len(v) for (t, k), v in sorted(places.items())},
            "within_tolerance": len(within_tol),
            "within_tolerance_by_track_kind": dict(sorted(_count_by(
                (f"{t['track']}|{t['of_kind']}" for t in within_tol)).items())),
            "inconsistencies": len(inconsistencies),
            "reclassified_stacks": len(inconsistencies),
            "reclassified_pieces": sum(len(i.get("reclassified_pieces") or []) for i in inconsistencies),
            "not_checked": len(not_checked), "skipped": len(skipped), "label": FLAG_LABEL}


# ══════════════════════════════════════════════════════════════════════════
# 4. Review queue items and stored rows (DESIGNED, not written)
# ══════════════════════════════════════════════════════════════════════════

def margins_text(flag: dict) -> str:
    """Both pairs' registration margins (best / second peak; shown, never
    compared - ruling 63)."""
    m = flag.get("registration_margins") or {}
    p = m.get("p_to_a")
    p = ", ".join(f"{k} {v}" for k, v in p.items()) if isinstance(p, dict) else p
    return f"S->A {m.get('s_to_a')}, P->A {p}"


def describe(flag: dict) -> Dict[str, Any]:
    """from_clash's (a, b, where, detail, sheets) for one flag. `detail`
    starts with FLAG_LABEL: the queue item says what the flag is - a thing
    for an engineer to look at - and nothing more."""
    fr = flag["frame"]
    a = fr["label"] + (" hold-down zone (end posts)" if flag["kind"] == KIND_HOLD_DOWN else "")
    where = f"{(flag.get('a_sheet') or {}).get('sheet_number')} {flag.get('level')} ({flag.get('track')})"
    c = flag.get("counts") or {}
    if flag["kind"] == KIND_STACK:
        ids = ", ".join(f"{s['tag_id'] or 'unread'} ({s['relation']}, {s['distance_in']} in)"
                        for s in flag["stacks"])
        b = f"{flag['plumbing']['sheet_number']} stacks"
        detail = f"{FLAG_LABEL}: {len(flag['stacks'])} stack(s) inside or within {flag['tolerance_in']:g} in: {ids}"
    else:
        b = f"{flag['plumbing']['sheet_number']} {flag.get('system')} pipe"
        detail = (f"{FLAG_LABEL}: {c.get('pieces')} drawn piece(s) "
                  f"({c.get('straight')} straight, {c.get('curved')} curved)"
                  + (" within " + f"{flag['tolerance_in']:g} in of the end posts"
                     if flag["kind"] == KIND_HOLD_DOWN else " inside the frame's footprint")
                  + (f"; {c.get('in_hold_down_zone')} of them in the hold-down zone"
                     if flag["kind"] == KIND_PIPE and c.get("in_hold_down_zone") else ""))
    if flag.get("structure_note"):
        detail += f"; {flag['structure_note']}"
    detail += "; margins " + margins_text(flag)
    sheets = [(fr.get("s_sheet") or {}).get("sheet_number"),
              (flag.get("a_sheet") or {}).get("sheet_number")]
    sheets += [s.strip() for s in str(flag["plumbing"].get("sheet_number") or "").split(",")]
    return {"a": a, "b": b, "where": where, "detail": detail, "sheets": [s for s in sheets if s]}


def review_items(flags: Iterable[dict], company_id: Any, project_id: Any, *,
                 now: datetime) -> List[Dict[str, Any]]:
    """One review_queue item per flag, through review_queue.from_clash (#911's
    shape). Built, NOT enqueued: Roy reviews the flag images first."""
    from lib import review_queue
    out = []
    for f in flags:
        doc = review_queue.from_clash(company_id, project_id, now=now, **describe(f))
        if doc:
            out.append(doc)
    return out


def rows_for_store(result: Dict[str, Any], *, project_id: str,
                   company_id: Optional[str]) -> List[dict]:
    """The stored shape (collection COLLECTION): one document per flag and
    one per not-checked entry, {project_id, company_id, ...}. DESIGNED, NOT
    WRITTEN - nothing calls it; a pass that stores these waits for the
    operator's review of the flag images (his pattern for T3's rows)."""
    return [dict(r, project_id=str(project_id), company_id=company_id)
            for r in (list(result.get("flags") or []) + list(result.get("inconsistencies") or [])
                  + list(result.get("within_tolerance") or [])
                  + list(result.get("not_checked") or []))]


__all__ = [
    "EMIT_VERSION", "COLLECTION", "FLAG_LABEL", "KIND_PIPE", "KIND_HOLD_DOWN", "KIND_STACK",
    "KIND_INCONSISTENCY", "KIND_TOLERANCE", "TOLERANCE_LABEL", "RESIDUAL_RULE", "residual_for",
    "within_tolerance", "with_s_residuals", "penetration_depth", "circle_penetration", "AGREE_IN", "TOUCH_IN", "MATCH_PT", "moves_with_stack", "stack_inconsistencies", "inconsistency_message",
    "KINDS", "FRAME_ELEMENTS", "TOL_IN", "check", "frames_by_page", "summarize", "describe", "margins_text",
    "review_items", "rows_for_store", "point_in_poly", "seg_poly_dist", "path_poly_dist",
    "circle_relation", "segs_intersect", "bbox", "inches", "pts",
]
