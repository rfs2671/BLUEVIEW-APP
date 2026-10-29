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
  * ruling 116 is pending: P-204's V-4 jogs 23.8 in onto SW 1's line between
    the 3rd and 4th floors. It is flagged at the position drawn.

Pure: no database, no network, no rendering. The overlay crops are drawn by
scripts/clash_report.py from these flags.
"""
from __future__ import annotations

import hashlib
import math
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

#: the structural elements a pipe is checked against (Roy: "a shear wall or
#: braced frame"); a bearing wall is not one
FRAME_ELEMENTS = ("shear_wall", "braced_frame")

#: the side-of-wall tolerance (plan_registration: "WHICH SIDE OF THE WALL /
#: DOES THIS PENETRATE IT"), applied to the hold-down zone and to stacks
TOL_IN = reg.TOL_WALL_SIDE_IN

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
                                   "second_peak_anchors", "margin", "usable")}


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


def _base(kind: str, frame: dict, prow: dict, tol_in: float) -> dict:
    return {"record_type": "clash_flag", "emit_version": EMIT_VERSION, "label": FLAG_LABEL,
            "kind": kind, "track": frame["track"], "level": frame["level"],
            "a_sheet": frame["a_sheet"], "frame": {k: frame[k] for k in (
                "label", "element", "tag", "polygon_a", "s_sheet", "registration", "schedule",
                "hold_down_zones", "hold_down_note")},
            "plumbing": _plumbing_ref(prow),
            "registration_margins": {
                "s_to_a": (frame.get("registration") or {}).get("margin"),
                "p_to_a": ((prow.get("registration") or {}).get("margin"))},
            "structure_note": frame.get("structure_note"), "tolerance_in": tol_in}


def check(structure: Iterable[dict], plumbing: Iterable[dict], *,
          tol_in: float = TOL_IN) -> Dict[str, Any]:
    """{"flags", "not_checked", "skipped", "summary"} - the whole of clash v1.

    flags        one per (track, level, frame, plumbing sheet, pipe system) for
                 pipe pieces through a frame (KIND_PIPE), the same group's
                 pieces within tol_in of an end post (KIND_HOLD_DOWN), and
                 one per (track, level, frame) for stacks inside / crossing /
                 within tol_in of it (KIND_STACK). Each says FLAG_LABEL.
    not_checked  every refused placement, with its reason: a frame or a
                 hold-down zone without a polygon, a plumbing sheet's pipes
                 without an A placement, a stack without a footprint, and a
                 frame on an A plan no plumbing sheet was placed on.
    skipped      frames drawn below (not this level's structure).
    """
    tol = pts(tol_in)
    fb = frames_by_page(structure)
    frames = fb["frames"]
    not_checked = list(fb["not_checked"])
    flags: List[dict] = []
    prow_pages: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    stacks_pages: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in plumbing:
        rt = r.get("record_type")
        if rt == "pipe_segments":
            if r.get("segments") is None and r.get("curves") is None:
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
                not_checked.append(_not_checked(
                    "stack", f"{r.get('plumbing_sheet')} {r.get('tag_id') or 'tag unread'}",
                    r.get("track"), None, _sheet(r.get("a_sheet")),
                    "the stack has no footprint on an architectural plan: "
                    + str(r.get("placement_refused") or r.get("reason") or r.get("status")),
                    plumbing_sheet=r.get("plumbing_sheet"), status=r.get("status")))
                continue
            stacks_pages[(r.get("track"), _a_page_id(r))].append(r)
        elif rt == "stack_sheet" and r.get("status") == "failed":
            not_checked.append(_not_checked(
                "plumbing sheet", r.get("plumbing_sheet"), r.get("track"), None, None,
                "the stack pass failed on this sheet: " + str(r.get("reason")),
                plumbing_sheet=r.get("plumbing_sheet")))
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
    for key, fs in frames.items():
        for f in fs:
            poly = f["polygon_a"]
            for prow in prow_pages.get(key, []):
                groups: Dict[Any, List[dict]] = defaultdict(list)
                for kind, i, ptsl, system in _pieces(prow):
                    if path_poly_dist(ptsl, poly) > 0:
                        continue
                    hd = [(path_poly_dist(ptsl, z["polygon_a"]), z.get("end"))
                          for z in f["hold_down_zones"]]
                    d, end = min(hd, key=lambda t: t[0]) if hd else (None, None)
                    groups[system or "unknown"].append({
                        "piece": kind, "index": i,
                        "points": [[round(p[0], 2), round(p[1], 2)] for p in ptsl],
                        "hold_down_in": None if d is None else round(inches(d), 2),
                        "hold_down_end": end if d is not None and d <= tol else None})
                for system, pieces in sorted(groups.items()):
                    base = _base(KIND_PIPE, f, prow, tol_in)
                    base["system"] = system
                    gid = (f["track"], key[1], f["label"], prow.get("plumbing_sheet"), system)
                    flags.append(dict(base, flag_id=_flag_id(KIND_PIPE, *gid), pieces=pieces,
                                      counts=_counts(pieces, tol_in)))
                    hd_pieces = [p for p in pieces if p["hold_down_end"]]
                    if hd_pieces:
                        hb = _base(KIND_HOLD_DOWN, f, prow, tol_in)
                        hb["system"] = system
                        flags.append(dict(hb, flag_id=_flag_id(KIND_HOLD_DOWN, *gid),
                                          pieces=hd_pieces, counts=_counts(hd_pieces, tol_in)))
            near = []
            for s in stacks_pages.get(key, []):
                fp = s["footprint_arch"]
                rel, gap = circle_relation(fp["x"], fp["y"], fp["r"], poly)
                if rel == "outside" and gap > tol:
                    continue
                hd = [(circle_relation(fp["x"], fp["y"], fp["r"], z["polygon_a"])[1], z.get("end"))
                      for z in f["hold_down_zones"]]
                hdd, hend = min(hd, key=lambda t: t[0]) if hd else (None, None)
                near.append({"tag_id": s.get("tag_id"), "plumbing_sheet": s.get("plumbing_sheet"),
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
                             "p_to_a": _margin_view(s.get("registration"))})
            if near:
                near.sort(key=lambda s: (str(s["plumbing_sheet"]), str(s["tag_id"]), s["y"], s["x"]))
                prs = {s["plumbing_sheet"] for s in near}
                base = {"record_type": "clash_flag", "emit_version": EMIT_VERSION,
                        "label": FLAG_LABEL, "kind": KIND_STACK, "track": f["track"],
                        "level": f["level"], "a_sheet": f["a_sheet"],
                        "frame": {k: f[k] for k in ("label", "element", "tag", "polygon_a", "s_sheet",
                                                    "registration", "schedule", "hold_down_zones",
                                                    "hold_down_note")},
                        "plumbing": {"sheet_number": ", ".join(sorted(prs))},
                        "registration_margins": {
                            "s_to_a": (f.get("registration") or {}).get("margin"),
                            "p_to_a": {s["plumbing_sheet"]: (s["p_to_a"] or {}).get("margin")
                                       for s in sorted(near, key=lambda s: str(s["plumbing_sheet"]))}},
                        "structure_note": f.get("structure_note"), "tolerance_in": tol_in}
                flags.append(dict(base, flag_id=_flag_id(KIND_STACK, f["track"], key[1], f["label"]),
                                  stacks=near, counts={"stacks": len(near)}))
    flags.sort(key=_flag_order)
    return {"flags": flags, "not_checked": not_checked, "skipped": fb["skipped"],
            "summary": summarize(flags, not_checked, fb["skipped"])}


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
            str((f.get("frame") or {}).get("label")), KINDS.index(f["kind"]),
            str((f.get("plumbing") or {}).get("sheet_number")), str(f.get("system")))


def summarize(flags: Sequence[dict], not_checked: Sequence[dict], skipped: Sequence[dict]) -> dict:
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
            for r in list(result.get("flags") or []) + list(result.get("not_checked") or [])]


__all__ = [
    "EMIT_VERSION", "COLLECTION", "FLAG_LABEL", "KIND_PIPE", "KIND_HOLD_DOWN", "KIND_STACK",
    "KINDS", "FRAME_ELEMENTS", "TOL_IN", "check", "frames_by_page", "summarize", "describe", "margins_text",
    "review_items", "rows_for_store", "point_in_poly", "seg_poly_dist", "path_poly_dist",
    "circle_relation", "segs_intersect", "bbox", "inches", "pts",
]
