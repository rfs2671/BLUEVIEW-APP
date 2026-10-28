"""PLUMBING STACKS: where each riser and stack is, in architectural coordinates.

Roy's spec (lane T4, 2026-10-28): "locate stacks (circles at leader ends,
split-circle tags) on P plans, register to A by title-level pairing, cross-
check against the riser diagram counts." The output feeds clash v1 (lane C1:
a stack footprint inside a shear-wall or braced-frame polygon).

── WHAT A STACK IS ON A PLUMBING PLAN ────────────────────────────────────

A SPLIT-CIRCLE TAG - a circle cut by its horizontal diameter, the system
letter above (S sanitary, V vent, ST storm, W water) and the stack number
below - with a LEADER drawn from its rim to an arrowhead. The stack is the
PIPE CIRCLE at the leader's end: a closed circle drawn on a pipe layer
(P-Pipe-*), the pipe seen end-on. One tag may carry several leaders (W-4 on
P-103.00 points at two risers), so a tag is one ID and one or more stacks.

Only the plumbing sheet's OWN drawing is read: a layer bound from an xref
(AutoCAD's "|" in the layer name, or XREF / X- prefixed) is the architectural
underlay or a pasted notes block - the legend's sample tag lives there and
is never a stack.

── THE TAG TEXT IS SHX STROKES, NOT TEXT ─────────────────────────────────

The letters are vector strokes. Each half is drawn from its own strokes onto
a clean canvas and read by the OCR engine (lib.plan_ocr, not changed here).
One read of a lone SHX digit is unreliable - measured 2026-10-28 on P-204.00
a "3" read as 5 and a "2" as 7. So reads are VOTED BY GLYPH: the same glyph
of one font at one size is the same strokes, so every half with identical
strokes (its `signature`) is one glyph, and its label is the reading that
wins at least twice the votes of any other AND at least half of the
renderings tried. Otherwise the half is UNREAD, and so is the tag - never
the likeliest guess.

── WHICH ARCHITECTURAL PLAN, AND WHERE ON IT ─────────────────────────────

FLOOR IDENTITY COMES ONLY FROM THE SHEET NUMBER AND THE TITLE LEVEL, NEVER
FROM REGISTRATION FIT (operator rule 2026-10-26; the pairing matrix found no
fit measure that separates floors). `pair_by_title_level`: both titles must
parse to the same single level, and the series' number offset (P-2xx = A+1,
P-1xx = A+0) must be the one a strict majority of the series' level-matched
sheets hold; a sheet that breaks it, or whose title does not parse, REFUSES.

Registration is used ONLY for the offset of a pair already decided, and only
when it passes `registration_usable` - plan_sheet.register's own conditions
(best peak, count, spread, residuals) AND no second peak holding half the
best's anchors (an alignment another offset nearly matches is ambiguous).

Pure: no database, no network. Pages come in as lib.plan_page.PlanPage (or
anything with `.drawings`), page dicts as the index rows.
"""
from __future__ import annotations

import io
import math
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

#: the collection C1 reads (design: one document per stack, per track; see
#: `stack_rows`). Nothing in this module writes it.
COLLECTION = "plan_stacks"
ROW_VERSION = 1

# ── what the sheet's own drawing is ────────────────────────────────────────

#: An xref-bound layer: "X-FLOOR PLANS 6.16.2026|A-Stairs", "XREF",
#: "X-(24X36)-(P-200) Sanitary & Storm Notes|P-TEXT".
_XREF_LAYER = re.compile(r"\||^XREF\b|^X-", re.I)
#: The pipe a stack is: a circle on one of these is the pipe seen end-on.
PIPE_LAYER = re.compile(r"^P-PIPE-", re.I)

#: What the pipe layer says the pipe carries. First match wins.
_LAYER_SYSTEM = (
    (re.compile(r"SSWR-VENT", re.I), "vent"),
    (re.compile(r"SSWR", re.I), "sanitary"),
    (re.compile(r"STRM", re.I), "storm"),
    (re.compile(r"DOMH-RCRC", re.I), "hot water return"),
    (re.compile(r"DOMH", re.I), "hot water"),
    (re.compile(r"DOMC|-CW-", re.I), "cold water"),
    (re.compile(r"NGAS|GAS", re.I), "gas"),
)
#: What the tag's letter says the stack is (P-001.00's legend; on the PL
#: set W is the domestic HOT water riser group - P-300.00 pairs every W-n
#: with a CW-n - and each W tag's leaders reach hot water and its return).
TAG_SYSTEM = {"S": "sanitary", "V": "vent", "ST": "storm", "W": "hot water",
              "CW": "cold water", "G": "gas"}
#: Which pipe systems a tag letter may point at.
TAG_POINTS_AT = {"S": {"sanitary"}, "V": {"vent"}, "ST": {"storm"},
                 "W": {"hot water", "hot water return"}, "CW": {"cold water"},
                 "G": {"gas"}}

# ── geometry (points; 1/4" = 1'-0" -> 1.5pt per real inch) ─────────────────

#: a circle is closed beziers whose end points all sit this close (as a
#: fraction of the radius) to one radius about the bounding box's centre
CIRCLE_ROUND_FRAC = 0.08
#: A tag holds two lines of lettering, so it is larger than any pipe drawn
#: end-on; a pipe circle is at most a 12in pipe (18pt) across.
TAG_MIN_DIAMETER_PT = 12.0
TAG_MAX_DIAMETER_PT = 48.0
PIPE_MAX_DIAMETER_PT = 18.0
#: two points of one drawn line meet when this close (CAD writes them equal;
#: this is float noise, not a tolerance on the drawing)
JOIN_PT = 0.6
#: A leader may leave the rim with a gap: the pen lifts at the rim (3.0pt
#: on P-103.00's W-4). Half the tag's radius - past that the line is
#: not the tag's.
LEADER_GAP_FRAC = 0.5
#: An arrowhead is a closed triangle of at most this side (6in at 1/4"):
#: larger is a drawn shape, not a leader's head. Measured heads on the PL
#: set are ~6pt long.
ARROW_MAX_PT = 9.0
#: a pipe circle is one stack with every circle sharing its centre (a vent
#: drawn over the drain it rises from) - within float noise
SAME_CENTRE_PT = 0.3

# ── OCR voting ─────────────────────────────────────────────────────────────

#: (px per pt, stroke px): the renderings each half is read at
RENDERINGS = ((6, 2), (10, 3), (16, 4), (24, 5))
#: a glyph's strokes are compared on this lattice (pt) - or, scaled to its
#: own box, on a grid this many cells a side
SIGNATURE_LATTICE_PT = 0.25
SIGNATURE_GRID = 16

_TOP = re.compile(r"^[A-Z]{1,2}$")
_BOTTOM = re.compile(r"^\d{1,2}(?:-\d{1,2})?$")
_SIZE = re.compile(r"(\d{1,2}(?:\s*-?\s*\d/\d)?|\d/\d)\s*[\"”“'’]{1,2}")


def is_own_layer(name: Optional[str]) -> bool:
    return not _XREF_LAYER.search(str(name or ""))


def layer_system(name: Optional[str]) -> Optional[str]:
    for rx, sysname in _LAYER_SYSTEM:
        if rx.search(str(name or "")):
            return sysname
    return None


# ── primitives ─────────────────────────────────────────────────────────────

def _bezier_points(it, n: int = 8) -> List[Tuple[float, float]]:
    p0, c1, c2, p3 = it[1:5]
    out = []
    for k in range(n + 1):
        t = k / n
        out.append(tuple((1 - t) ** 3 * p0[i] + 3 * (1 - t) ** 2 * t * c1[i]
                         + 3 * (1 - t) * t * t * c2[i] + t ** 3 * p3[i] for i in (0, 1)))
    return out


def polyline(it) -> List[Tuple[float, float]]:
    """A drawing item as points: a line's two ends, a curve flattened."""
    if it[0] == "l":
        return [tuple(it[1]), tuple(it[2])]
    return _bezier_points(it)


def fit_circle(pts: Sequence[Tuple[float, float]]) -> Optional[Tuple[float, float, float]]:
    """Least-squares circle (Kasa) through the points, or None when they
    are not round: every point within CIRCLE_ROUND_FRAC of the radius."""
    n = len(pts)
    if n < 3:
        return None
    sx = sum(p[0] for p in pts) / n
    sy = sum(p[1] for p in pts) / n
    u = [(p[0] - sx, p[1] - sy) for p in pts]
    suu = sum(a * a for a, _ in u)
    svv = sum(b * b for _, b in u)
    suv = sum(a * b for a, b in u)
    rhs1 = (sum(a ** 3 for a, _ in u) + sum(a * b * b for a, b in u)) / 2
    rhs2 = (sum(b ** 3 for _, b in u) + sum(b * a * a for a, b in u)) / 2
    det = suu * svv - suv * suv
    if abs(det) < 1e-12:
        return None
    uc = (rhs1 * svv - rhs2 * suv) / det
    vc = (suu * rhs2 - suv * rhs1) / det
    cx, cy = uc + sx, vc + sy
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    if r <= 0 or any(abs(math.dist(p, (cx, cy)) - r) > CIRCLE_ROUND_FRAC * r for p in pts):
        return None
    return cx, cy, r


def _swept(pts, cx, cy) -> List[Tuple[float, float]]:
    """The angle intervals (radians, start < end) the points walk through."""
    out = []
    for a, b in zip(pts, pts[1:]):
        t0 = math.atan2(a[1] - cy, a[0] - cx)
        dt = (math.atan2(b[1] - cy, b[0] - cx) - t0 + math.pi) % (2 * math.pi) - math.pi
        out.append((t0, t0 + dt) if dt >= 0 else (t0 + dt, t0))
    return out


def circle_of(d: dict) -> Optional[Tuple[float, float, float]]:
    """(cx, cy, r) when the path is ONE CLOSED CIRCLE of four or more curves
    - how every split-circle tag is drawn. Else None."""
    items = d.get("items") or ()
    if len(items) < 4 or any(it[0] != "c" for it in items):
        return None
    if math.dist(items[0][1], items[-1][4]) > JOIN_PT:
        return None
    pts = [items[0][1]] + [it[4] for it in items]
    return fit_circle(pts)


#: an arc is at least this much of a turn - less is a bend in a pipe run
ARC_MIN_SWEEP = math.pi / 4
#: a pipe seen end-on is drawn round at least this much of a turn, in one
#: arc or several (three-quarter "open" circles: a riser turning down,
#: P-103.00), or as two arcs facing each other across the centre (_opposite);
#: a 90-degree elbow is neither
PIPE_MIN_COVER = math.pi


def arcs_of(d: dict) -> List[Dict[str, Any]]:
    """Every round run in a path: consecutive pieces (curves flattened,
    straight pieces as they are) whose points fit one circle no larger
    than a pipe, sweeping at least ARC_MIN_SWEEP. A riser drawn in one path
    with the pipe leaving it (P-100.00: a 33-sided circle and its tail) is
    a round run and a straight one."""
    items = d.get("items") or ()
    runs, cur = [], []
    for it in items:
        if cur and math.dist(cur[-1][-1], it[1]) > 0.05:
            runs.append(cur)
            cur = []
        cur.append(it)
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        # grow a round window forward from each start, as long as it stays
        # round and pipe-sized; keep it when it turned far enough
        i = 0
        while i < len(run):
            best, pts, j = None, [], i
            while j < len(run):
                pl = polyline(run[j])
                cand = pts + (pl if not pts else pl[1:])
                if len(cand) >= 4:
                    fit = fit_circle(cand)
                    if not fit or 2 * fit[2] > PIPE_MAX_DIAMETER_PT:
                        break
                    iv = _swept(cand, fit[0], fit[1])
                    if sum(b - a for a, b in iv) >= ARC_MIN_SWEEP:
                        best = (j + 1, fit, iv)
                pts = cand
                j += 1
            if best is None:
                i += 1
                continue
            j, (cx, cy, r), iv = best
            out.append({"x": cx, "y": cy, "r": r, "intervals": iv})
            i = j
    return out


def _cover(intervals) -> float:
    """How much of a turn the intervals cover (radians, overlaps once)."""
    bins = [False] * 360
    for a, b in intervals:
        k0 = int(math.floor(math.degrees(a)))
        k1 = int(math.ceil(math.degrees(b)))
        for k in range(k0, max(k1, k0 + 1)):
            bins[k % 360] = True
    return math.radians(sum(bins))


def _opposite(members: Sequence[dict]) -> bool:
    """Two arcs of one centre facing each other across it (their middles
    half a turn apart, within 30 degrees): a circle trimmed by the pipe
    that runs through it - P-104.00 draws its risers as a top and a bottom
    88-degree arc, 176 degrees in all."""
    mids = []
    for m in members:
        a = min(iv[0] for iv in m["intervals"])
        b = max(iv[1] for iv in m["intervals"])
        mids.append((a + b) / 2)
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            d = abs((mids[i] - mids[j] + math.pi) % (2 * math.pi) - math.pi)
            if d >= math.pi - math.radians(30):
                return True
    return False


def pipe_rounds(arcs: Sequence[dict]) -> List[Dict[str, Any]]:
    """Arcs of one centre and radius joined into one pipe circle; kept when
    they cover PIPE_MIN_COVER. `closed` when they go all the way round."""
    groups: List[Dict[str, Any]] = []
    for a in arcs:
        for g in groups:
            if math.dist((g["x"], g["y"]), (a["x"], a["y"])) <= max(SAME_CENTRE_PT, 0.1 * a["r"]) \
                    and abs(g["r"] - a["r"]) <= 0.15 * max(g["r"], a["r"]) \
                    and g["layer"] == a["layer"]:
                g["intervals"] += a["intervals"]
                g["members"].append(a)
                break
        else:
            groups.append(dict(a, intervals=list(a["intervals"]), members=[a]))
    out = []
    for g in groups:
        cov = _cover(g["intervals"])
        if cov < PIPE_MIN_COVER and not _opposite(g["members"]):
            continue
        n = len(g["members"])
        out.append({"x": sum(m["x"] for m in g["members"]) / n,
                    "y": sum(m["y"] for m in g["members"]) / n,
                    "r": sum(m["r"] for m in g["members"]) / n,
                    "layer": g["layer"], "closed": cov >= math.radians(350),
                    "cover_deg": round(math.degrees(cov))})
    return out


def triangle_of(d: dict) -> Optional[List[Tuple[float, float]]]:
    """The three corners when the path is one closed triangle of straight
    pieces no longer than ARROW_MAX_PT: an arrowhead. Else None."""
    items = d.get("items") or ()
    if len(items) != 3 or any(it[0] != "l" for it in items):
        return None
    a, b, c = items[0][1], items[1][1], items[2][1]
    if not (_near(items[0][2], b) and _near(items[1][2], c) and _near(items[2][2], a)):
        return None
    sides = (math.dist(a, b), math.dist(b, c), math.dist(c, a))
    if max(sides) > ARROW_MAX_PT or min(sides) <= 0:
        return None
    area = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2
    if area <= 0.05:
        return None
    return [tuple(a), tuple(b), tuple(c)]


class Sheet:
    """The plumbing sheet's own drawing, read once: segments with their
    layer, every closed circle (tag candidates), every pipe circle, every
    own-layer stroke as a polyline, every arrowhead - inside the drawing
    area only (left of the title block's rule, plan_cells.title_block_edge:
    the title block's logo is a circle with a line through it)."""

    def __init__(self, page):
        from lib.plan_cells import title_block_edge
        self.segs: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []
        self.circles: List[Dict[str, Any]] = []
        self.pipes: List[Dict[str, Any]] = []
        #: (points, layer, path index): a tag's lettering is told from its
        #: own circle by the path it was drawn in, not by distance
        self.strokes: List[Tuple[List[Tuple[float, float]], str, int]] = []
        self.arrows: List[Dict[str, Any]] = []
        #: indices into segs that are an arrowhead's sides - never a leader
        self.arrow_segs: set = set()
        allsegs = [(it[1][0], it[1][1], it[2][0], it[2][1]) for d in page.drawings
                   for it in d["items"] if it[0] == "l"]
        self.edge = title_block_edge(allsegs, page.width, page.height)
        arcs = []
        for pid, d in enumerate(page.drawings):
            layer = d.get("layer") or ""
            if not is_own_layer(layer) or d["rect"][0] >= self.edge:
                continue
            c = circle_of(d)
            if c is not None:
                self.circles.append({"x": c[0], "y": c[1], "r": c[2], "layer": layer, "pid": pid})
            if PIPE_LAYER.search(layer):
                arcs += [dict(a, layer=layer) for a in arcs_of(d)]
            tri = triangle_of(d)
            if tri is not None:
                self.arrows.append({"corners": tri, "layer": layer})
            for it in d["items"]:
                pl = polyline(it)
                self.strokes.append((pl, layer, pid))
                if it[0] == "l":
                    if tri is not None:
                        self.arrow_segs.add(len(self.segs))
                    self.segs.append((tuple(it[1]), tuple(it[2]), layer))
        self.pipes = [dict(c, system=layer_system(c["layer"])) for c in pipe_rounds(arcs)]


# ── split-circle tags ──────────────────────────────────────────────────────

def _diameter_line(sheet: Sheet, c: dict) -> Optional[int]:
    """Index of the own-layer horizontal segment that IS the circle's
    diameter (both ends on the rim, through the centre), or None."""
    cx, cy, r = c["x"], c["y"], c["r"]
    for i, (p, q, _l) in enumerate(sheet.segs):
        if abs(p[1] - cy) > JOIN_PT or abs(q[1] - cy) > JOIN_PT:
            continue
        a, b = sorted((p[0], q[0]))
        if abs(a - (cx - r)) <= JOIN_PT and abs(b - (cx + r)) <= JOIN_PT:
            return i
    return None


def _inside(pl, cx, cy, r) -> bool:
    """Every point of the stroke within the circle, its rim included: a
    "2" printed against the rim (the 1-2 of a combined vent) keeps its
    foot. Measured 2026-10-28: cut at the rim, that 2 lost its bottom bar
    and read "7" in every rendering."""
    return all(math.dist(p, (cx, cy)) <= r + JOIN_PT for p in pl)


def split_circle_tags(sheet: Sheet) -> List[Dict[str, Any]]:
    """Every split-circle tag: an own-layer circle TAG_MIN..TAG_MAX across,
    cut by its horizontal diameter, with strokes in BOTH halves."""
    out = []
    for c in sheet.circles:
        if not TAG_MIN_DIAMETER_PT <= 2 * c["r"] <= TAG_MAX_DIAMETER_PT:
            continue
        dl = _diameter_line(sheet, c)
        if dl is None:
            continue
        cx, cy, r = c["x"], c["y"], c["r"]
        halves = {"top": [], "bottom": []}
        for pl, _layer, pid in sheet.strokes:
            if pid == c.get("pid") or not _inside(pl, cx, cy, r):
                continue
            if all(p[1] < cy - 0.3 for p in pl):
                halves["top"].append(pl)
            elif all(p[1] > cy + 0.3 for p in pl):
                halves["bottom"].append(pl)
        if halves["top"] and halves["bottom"]:
            out.append({"x": cx, "y": cy, "r": r, "layer": c["layer"],
                        "diameter_seg": dl, "top": halves["top"],
                        "bottom": halves["bottom"]})
    return out


# ── leaders ────────────────────────────────────────────────────────────────

def _near(a, b, tol=JOIN_PT) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _point_seg(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    L2 = (bx - ax) ** 2 + (by - ay) ** 2
    if L2 == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / L2))
    return math.dist(p, (ax + t * (bx - ax), ay + t * (by - ay)))


def arrowhead_at(sheet: Sheet, e: Tuple[float, float], layer: str
                 ) -> Optional[Dict[str, Any]]:
    """The arrowhead (on the leader's layer) a leader ends on: a triangle
    with the end ON one of its sides. Its tip is the corner farthest from
    the end; its length, end to tip."""
    best = None
    for a in sheet.arrows:
        if a["layer"] != layer:
            continue
        k = a["corners"]
        if min(_point_seg(e, k[i], k[(i + 1) % 3]) for i in range(3)) > JOIN_PT:
            continue
        tip = max(k, key=lambda q: math.dist(q, e))
        L = math.dist(tip, e)
        if L > JOIN_PT and (best is None or L > best["length"]):
            best = {"tip": tip, "length": L,
                    "dir": ((tip[0] - e[0]) / L, (tip[1] - e[1]) / L)}
    return best


def trace_leaders(sheet: Sheet, tag: dict, tags: Sequence[dict] = ()
                  ) -> List[Dict[str, Any]]:
    """[{"path": [points], "end", "tip", "dir", "arrow_len", "layer"}]: every
    LEADER of the tag - a run of own-layer segments on one layer that
    starts at the tag's diameter height (on the diameter inside the circle,
    or at most LEADER_GAP_FRAC of the radius past the rim) and ENDS ON AN
    ARROWHEAD. Branches are followed to each end. A run that ends on no
    arrowhead is not a leader (a note's letter beside the tag starts at the
    same height); `tag["unterminated"]` counts them, so a leader drawn
    without an arrowhead is visible, not silently dropped."""
    cx, cy, r = tag["x"], tag["y"], tag["r"]
    gap = LEADER_GAP_FRAC * r
    lettering = set()
    for t in list(tags) + [tag]:
        for i, (p, q, _l) in enumerate(sheet.segs):
            if math.dist(p, (t["x"], t["y"])) < t["r"] + JOIN_PT \
                    and math.dist(q, (t["x"], t["y"])) < t["r"] + JOIN_PT:
                lettering.add(i)
    skip = lettering | sheet.arrow_segs | {tag.get("diameter_seg")}
    starts = []
    for i, (p, q, layer) in enumerate(sheet.segs):
        if i in skip:
            continue
        for a, b in ((p, q), (q, p)):
            if abs(a[1] - cy) <= JOIN_PT and abs(a[0] - cx) <= r + gap \
                    and math.dist(b, (cx, cy)) > r + JOIN_PT \
                    and math.dist(b, (cx, cy)) > math.dist(a, (cx, cy)):
                starts.append((i, a, b, layer))
    out, dead = [], 0
    for i0, a0, b0, layer in starts:
        stack = [([a0, b0], {i0})]
        while stack:
            path, used = stack.pop()
            e = path[-1]
            fwd = []
            for j, (p, q, l2) in enumerate(sheet.segs):
                if j in used or j in skip or l2 != layer:
                    continue
                f = q if _near(p, e) else p if _near(q, e) else None
                if f is None or math.dist(f, e) <= JOIN_PT:
                    continue
                if math.dist(f, (cx, cy)) <= r + JOIN_PT:
                    continue
                fwd.append((j, f))
            if fwd:
                for j, f in fwd:
                    stack.append((path + [f], used | {j}))
                continue
            arrow = arrowhead_at(sheet, e, layer)
            if arrow is None:
                dead += 1
                continue
            out.append({"path": path, "end": e, "tip": arrow["tip"], "dir": arrow["dir"],
                        "arrow_len": arrow["length"], "layer": layer})
    tag["unterminated"] = dead
    uniq: List[Dict[str, Any]] = []
    for lead in out:
        if not any(_near(lead["tip"], u["tip"]) for u in uniq):
            uniq.append(lead)
    return uniq


def pipe_circles(sheet: Sheet) -> List[Dict[str, Any]]:
    """Every pipe drawn end-on on a pipe layer (Sheet.pipes)."""
    return list(sheet.pipes)


#: The pen lands within one real inch of the pipe it points at: P-102.00's
#: arrow to a cold-water riser passes 1.1pt (0.7in) wide of its rim.
AIM_SLOP_PT = 1.5


def _ray_entry(tip, u, c) -> Optional[float]:
    """How far past the tip the ray tip + t*u reaches circle c - its rim
    widened by AIM_SLOP_PT (0 when the tip is already there) - or None
    when the ray passes wider than that."""
    R = c["r"] + AIM_SLOP_PT
    fx, fy = c["x"] - tip[0], c["y"] - tip[1]
    if math.hypot(fx, fy) <= R:
        return 0.0
    along = fx * u[0] + fy * u[1]
    off2 = fx * fx + fy * fy - along * along
    if along <= 0 or off2 > R ** 2:
        return None
    return along - math.sqrt(R ** 2 - off2)


def stack_at(lead: dict, pipes: Sequence[dict]
             ) -> Tuple[Optional[Dict[str, Any]], str]:
    """(stack, why): the pipe circle the ARROW POINTS AT - the first one its
    line enters within one arrowhead's own length past the tip (or the one
    the tip is in) - with every pipe circle sharing that centre. None, with
    why, when the arrow enters none, or two different centres equally
    early (the arrow does not say which)."""
    tip, u, reach = lead["tip"], lead["dir"], lead.get("arrow_len") or 0.0
    hits = []
    for c in pipes:
        t = _ray_entry(tip, u, c)
        if t is not None and t <= reach:
            # ranked by how close the arrow's line passes the centre, then
            # how soon: the widened rims of two neighbours both catch a ray
            fx, fy = c["x"] - tip[0], c["y"] - tip[1]
            along = fx * u[0] + fy * u[1]
            off = math.sqrt(max(fx * fx + fy * fy - along * along, 0.0)) if along > 0 \
                else math.hypot(fx, fy)
            hits.append((t, c, off))
    if not hits:
        near = min(pipes, key=lambda c: math.dist(tip, (c["x"], c["y"])), default=None)
        d = (f"; nearest pipe circle's rim "
             f"{abs(math.dist(tip, (near['x'], near['y'])) - near['r']):.1f}pt from the tip"
             if near else "; the sheet draws no pipe circle")
        return None, f"the arrow points at no pipe circle{d}"
    t0 = min(h[0] for h in hits)
    first = [h for h in hits if h[0] - t0 <= JOIN_PT]
    first.sort(key=lambda h: h[2])
    _t, c0, off0 = first[0]
    k = (c0["x"], c0["y"])
    rivals = [c for _t2, c, off in first[1:]
              if math.dist((c["x"], c["y"]), k) > SAME_CENTRE_PT and off - off0 <= JOIN_PT]
    if rivals:
        return None, f"the arrow reaches {len(rivals) + 1} pipe circles at once, not one centre"
    group = [c for c in pipes if math.dist((c["x"], c["y"]), k) <= SAME_CENTRE_PT]
    return {"x": k[0], "y": k[1], "r": max(c["r"] for c in group),
            "layers": sorted({c["layer"] for c in group}),
            "systems": sorted({c["system"] for c in group if c["system"]}),
            "drawn": "closed" if any(c["closed"] for c in group) else "open",
            "entry_pt": round(t0, 2), "aim_off_pt": round(off0, 2)}, "the arrow points at it"


# ── reading the tags ───────────────────────────────────────────────────────

def signature(polys: Sequence[Sequence[Tuple[float, float]]], scaled: bool = False) -> frozenset:
    """The glyph's strokes relative to their own box, on a lattice: two
    halves with the same signature are the same glyph of the same font.

    `scaled`: the box is stretched to a unit square first (SIGNATURE_GRID
    cells a side), so one glyph printed narrower is still that glyph - a
    three-character tag compresses its digits (the "2" of V-1-2 on P-301.00
    alone read "7" in every rendering; pooled with the set's other 2s it is
    a 2)."""
    pts = [p for pl in polys for p in pl]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    w = max(p[0] for p in pts) - x0
    h = max(p[1] for p in pts) - y0
    if scaled:
        sx = max(w, 0.3 * h, 1e-6) / SIGNATURE_GRID
        sy = max(h, 0.3 * w, 1e-6) / SIGNATURE_GRID
    else:
        sx = sy = SIGNATURE_LATTICE_PT
    out = set()
    for pl in polys:
        k = tuple((round((x - x0) / sx), round((y - y0) / sy)) for x, y in pl)
        out.add(min(k, k[::-1]))
    return frozenset(out)


def _box(polys):
    pts = [p for pl in polys for p in pl]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


#: two strokes are one character when their x-extents come this close (pt);
#: SHX lettering on the PL set spaces its characters 1.6pt apart
CHAR_JOIN_PT = 0.5


def characters(polys) -> List[List[Sequence[Tuple[float, float]]]]:
    """The half's strokes grouped into characters, left to right: strokes
    whose x-extents overlap or come within CHAR_JOIN_PT are one character."""
    items = sorted(polys, key=lambda pl: min(p[0] for p in pl))
    out: List[List] = []
    hi = None
    for pl in items:
        x0, x1 = min(p[0] for p in pl), max(p[0] for p in pl)
        if out and x0 <= hi + CHAR_JOIN_PT:
            out[-1].append(pl)
            hi = max(hi, x1)
        else:
            out.append([pl])
            hi = x1
    return out


def is_dash(char, height: float) -> bool:
    """One straight horizontal stroke, narrower than the lettering is tall,
    in its middle band: the dash in "1-2" (one vent through the roof for
    stacks 1 and 2). Read from the strokes - OCR drops it (measured: V-1-2
    on P-205.00 read "12" in every rendering)."""
    if len(char) != 1 or len(char[0]) != 2:
        return False
    (x0, y0), (x1, y1) = char[0]
    return abs(y1 - y0) <= 0.05 * height and 0 < abs(x1 - x0) < height


def _layout(top, bottom_chars, h):
    """Where each glyph goes on the composed line: the top half, then each
    character of the bottom half, wide apart so each reads as its own box."""
    gap = 1.6 * h
    slots, ox = [], h
    bt = _box(top)
    slots.append(("top", top, bt, ox))
    ox += (bt[2] - bt[0]) + gap
    for i, ch in enumerate(bottom_chars):
        bb = _box(ch)
        slots.append((i, ch, bb, ox))
        ox += max(bb[2] - bb[0], 0.4 * h) + gap
    return slots, ox + h


def compose(top, bottom_chars, scale: float, width: int, h: float):
    """PNG of the tag on ONE line - the top half, then every non-dash
    character of the bottom half - and each slot's x range (px)."""
    from PIL import Image, ImageDraw
    slots, total = _layout(top, bottom_chars, h)
    img = Image.new("L", (int(total * scale) + 1, int(3 * h * scale) + 1), 255)
    dr = ImageDraw.Draw(img)
    ranges = []
    for key, polys, bb, ox in slots:
        for pl in polys:
            pts = [((x - bb[0] + ox) * scale, (y - bb[1] + h + (h - (bb[3] - bb[1])) / 2) * scale)
                   for x, y in pl]
            dr.line(pts, fill=0, width=width)
        w = max(bb[2] - bb[0], 0.4 * h)
        ranges.append((key, (ox - 0.8 * h) * scale, (ox + w + 0.8 * h) * scale))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), ranges


def _assign(reads, ranges) -> Dict[Any, str]:
    """{slot: text}. A read of one character goes to the slot its centre
    is in. A read of several - OCR joining boxes ("V12", "12") - is split
    one character per slot only when its letters and digits match the
    slots exactly (letters to the top, one digit per character slot);
    anything else is dropped, never guessed into a slot."""
    out: Dict[Any, str] = {}
    digit_slots = [k for k, _lo, _hi in ranges if k != "top"]
    for x, _y, text, _score in reads:
        t = re.sub(r"[\s\-_~一—–]+", "", str(text)).upper()
        if not t:
            continue
        inside = [k for k, lo, hi in ranges if lo <= x <= hi]
        m = re.fullmatch(r"([A-Z]*)(\d*)", t)
        if m and len(m.group(2)) > 1 and len(m.group(2)) == len(digit_slots):
            if m.group(1):
                out["top"] = m.group(1)
            for k, c in zip(digit_slots, m.group(2)):
                out[k] = c
            continue
        if len(inside) == 1 and (inside[0] == "top" or len(t) == 1):
            out[inside[0]] = t
    return out


def vote(readings: Sequence[Optional[str]], attempts: int) -> Tuple[Optional[str], str]:
    """(label, why): the reading that is a MAJORITY of the readings that
    read anything, with at least twice the votes of any other and at least
    two; else (None, the tally). Renderings that read nothing are reported,
    not counted against it - pooled over every instance of a glyph, they
    are many (a lone SHX 3 is often not seen at all)."""
    c = Counter(r for r in readings if r)
    read = sum(c.values())
    tally = ", ".join(f"{k} x{v}" for k, v in c.most_common()) or "nothing read"
    if not c:
        return None, f"unread ({tally} of {attempts} renderings)"
    (best, n), *rest = c.most_common()
    second = rest[0][1] if rest else 0
    if n >= 2 and n >= 2 * second and 2 * n > read:
        return best, f"{tally} of {attempts} renderings"
    return None, f"contested ({tally} of {attempts} renderings)"


_CHAR = re.compile(r"^[0-9]$")

#: Two digits are one glyph when their strokes, each drawn into its own
#: box, overlap this much (intersection over union). Measured 2026-10-28 on
#: every digit of every PL tag: one digit's variants overlap 0.89-1.00, two
#: different digits at most 0.64 - this sits in the gap, and the gap is
#: reported, not tuned: a set whose digits fall inside it pools nothing new.
GLYPH_SAME_IOU = 0.8


def _raster(polys, w: int = 24, h: int = 36):
    from PIL import Image, ImageDraw
    import numpy as np
    x0, y0, x1, y1 = _box(polys)
    sx, sy = max(x1 - x0, 0.3 * (y1 - y0), 1e-6), max(y1 - y0, 1e-6)
    im = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(im)
    for pl in polys:
        dr.line([((x - x0) / sx * (w - 5) + 2, (y - y0) / sy * (h - 5) + 2) for x, y in pl],
                fill=255, width=3)
    return np.asarray(im) > 0


def glyph_groups(examples: Dict[Any, Sequence]) -> Dict[Any, Any]:
    """{key: group}: digits whose rasters overlap GLYPH_SAME_IOU or more are
    one group (joined transitively), so every instance of a digit votes
    together however its strokes round."""
    keys = list(examples)
    ras = {k: _raster(examples[k]) for k in keys}
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            inter = (ras[a] & ras[b]).sum()
            union = (ras[a] | ras[b]).sum()
            if union and inter / union >= GLYPH_SAME_IOU:
                parent[find(a)] = find(b)
    return {k: find(k) for k in keys}


def read_tags(tags: Sequence[dict], reader: Optional[Callable[[bytes], list]] = None
              ) -> None:
    """Fill each tag's "id", "letter", "number", "read_why" in place.

    THE LETTER is voted per top half, THE NUMBER per CHARACTER: each digit
    is a glyph, and every instance of that glyph in the set votes on it
    (pass every tag of the set at once). A dash is read from its stroke
    (is_dash), never from OCR. A tag is read only when its letter and every
    one of its digits is decided.

    `reader(png) -> [(cx, cy, text, score)]` is lib.plan_ocr._boxes by
    default; a test hands in its own."""
    if reader is None:
        from lib import plan_ocr
        reader = plan_ocr._boxes
    votes: Dict[Tuple[str, frozenset], List[Optional[str]]] = defaultdict(list)
    tries: Counter = Counter()
    examples: Dict[Any, Sequence] = {}
    for t in tags:
        h = max(_box(t["top"])[3] - _box(t["top"])[1], _box(t["bottom"])[3] - _box(t["bottom"])[1], 1.0)
        chars = characters(t["bottom"])
        layout = [("-" if is_dash(c, h) else c) for c in chars]
        digits = [c for c in layout if c != "-"]
        t["_keys"] = {"top": ("top", signature(t["top"])),
                      "chars": [("-", None) if c == "-" else ("char", signature(c, scaled=True))
                                for c in layout]}
        for c, key in zip(layout, t["_keys"]["chars"]):
            if key[0] == "char":
                examples.setdefault(key, c)
        for scale, width in RENDERINGS:
            png, ranges = compose(t["top"], digits, scale, width, h)
            got = _assign(reader(png), ranges)
            top = got.get("top")
            votes[t["_keys"]["top"]].append(top if top and _TOP.fullmatch(top) else None)
            tries[t["_keys"]["top"]] += 1
            k = 0
            for key in t["_keys"]["chars"]:
                if key[0] == "-":
                    continue
                txt = got.get(k)
                votes[key].append(txt if txt and _CHAR.fullmatch(txt) else None)
                tries[key] += 1
                k += 1
    # every variant of one digit votes together (glyph_groups)
    group = glyph_groups(examples)
    pooled: Dict[Any, List[Optional[str]]] = defaultdict(list)
    ptries: Counter = Counter()
    for k, v in votes.items():
        g = group.get(k, k)
        pooled[g] += v
        ptries[g] += tries[k]
    decided = {k: vote(pooled[group.get(k, k)], ptries[group.get(k, k)]) for k in votes}
    for t in tags:
        letter, why_l = decided[t["_keys"]["top"]]
        parts, whys, ok = [], [], True
        for key in t["_keys"]["chars"]:
            if key[0] == "-":
                parts.append("-")
                continue
            ch, why = decided[key]
            whys.append(why)
            ok = ok and ch is not None
            parts.append(ch or "?")
        number = "".join(parts) if ok and parts else None
        if number and not _BOTTOM.fullmatch(number):
            ok, number = False, None
        t["letter"], t["number"] = letter, number
        t["id"] = f"{letter}-{number}" if letter and number else None
        t["read_why"] = f"letter: {why_l}; number {''.join(parts)}: " + " / ".join(whys)
        del t["_keys"]


# ── the annotation printed beside a tag (size, UP / DN) ────────────────────

#: how far beside the tag its note may run (pt): the longest printed on
#: Boyland ("4" UP (72 GPM)") is ~90pt
NOTE_REACH_PT = 140.0


def note_strokes(sheet: Sheet, tag: dict, leaders: Sequence[dict], tags: Sequence[dict]
                 ) -> Dict[str, List[List[Tuple[float, float]]]]:
    """{"left": polys, "right": polys}: own-layer, non-pipe strokes inside the
    tag's band (its diameter high), beside it, that are not a leader and not
    inside any tag - the note the tag prints ("1" DHW UP&DN")."""
    cx, cy, r = tag["x"], tag["y"], tag["r"]
    lead_pts = [p for ld in leaders for p in ld["path"]]
    out = {"left": [], "right": []}
    for pl, layer, _pid in sheet.strokes:
        if PIPE_LAYER.search(layer):
            continue
        if any(_inside(pl, t["x"], t["y"], t["r"] + JOIN_PT) for t in tags):
            continue
        if not all(cy - r <= p[1] <= cy + r for p in pl):
            continue
        if len(pl) == 2 and any(_near(p, q) for p in pl for q in lead_pts):
            continue
        xs = [p[0] for p in pl]
        if all(cx + r < x <= cx + r + NOTE_REACH_PT for x in xs):
            out["right"].append(pl)
        elif all(cx - r - NOTE_REACH_PT <= x < cx - r for x in xs):
            out["left"].append(pl)
    return out


def read_note(polys, reader=None, scale: float = 10, width: int = 3) -> str:
    if not polys:
        return ""
    if reader is None:
        from lib import plan_ocr
        reader = plan_ocr._boxes
    from PIL import Image, ImageDraw
    pts = [p for pl in polys for p in pl]
    x0, y0 = min(p[0] for p in pts) - 4, min(p[1] for p in pts) - 4
    x1, y1 = max(p[0] for p in pts) + 4, max(p[1] for p in pts) + 4
    img = Image.new("L", (int((x1 - x0) * scale) + 1, int((y1 - y0) * scale) + 1), 255)
    dr = ImageDraw.Draw(img)
    for pl in polys:
        dr.line([((x - x0) * scale, (y - y0) * scale) for x, y in pl], fill=0, width=width)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    mid = img.height / 2.0
    # line by line: the note beside a split circle prints a line by each half
    return " ".join(str(t) for _x, _y, t, _s in sorted(reader(buf.getvalue()),
                                                       key=lambda r: (r[1] > mid, r[0])))


def printed_size(note: str) -> Optional[str]:
    """The pipe size a note prints ('4" UP' -> '4"'), or None."""
    m = _SIZE.search(str(note or "").replace("”", '"').replace("“", '"'))
    return (re.sub(r"\s+", " ", m.group(1)).strip() + '"') if m else None


# ── one sheet ──────────────────────────────────────────────────────────────

def locate(page, *, tags_only: bool = False) -> Dict[str, Any]:
    """{"tags": [...], "pipes": n} for one plumbing sheet: each split-circle
    tag with its leaders and, for each leader, the stack at its end or why
    none. Tag text is NOT read here (read_tags, over the whole set)."""
    sheet = Sheet(page)
    tags = split_circle_tags(sheet)
    pipes = pipe_circles(sheet)
    for t in tags:
        t["leaders"] = []
        if tags_only:
            continue
        for ld in trace_leaders(sheet, t, tags):
            st, why = stack_at(ld, pipes)
            t["leaders"].append({"path": ld["path"], "tip": ld["tip"], "layer": ld["layer"],
                                 "stack": st, "why": why})
        t["note_polys"] = note_strokes(sheet, t, [{"path": l["path"]} for l in t["leaders"]], tags)
    return {"tags": tags, "pipes": len(pipes), "sheet": sheet}


def tag_system_check(tag: dict) -> List[str]:
    """Where a tag's letter and the pipe its leader reaches disagree: the
    letter says V, the circle is on the sanitary layer. A finding, kept on
    the row - never resolved by picking one."""
    out = []
    want = TAG_POINTS_AT.get(tag.get("letter") or "")
    for ld in tag.get("leaders") or []:
        st = ld.get("stack")
        if not st or want is None:
            continue
        if not set(st["systems"]) & want:
            out.append(f"{tag.get('id')} points at a {'/'.join(st['systems']) or 'pipe'} "
                       f"circle ({', '.join(st['layers'])})")
    return out


# ── P/A pairing by title level ─────────────────────────────────────────────

#: an NCS sheet number: discipline letter(s), series digit, two-digit
#: sequence, revision suffix
_SHEET = re.compile(r"^([A-Z]{1,2})-(\d)(\d\d)(?:\.(\d\d))?$")


def title_level(title: Optional[str]) -> Tuple[Optional[str], str]:
    """(level token, why) - ONE level the title names, or None with why.

    Read by the set's level table (lib.plans.level_suggestion.tokens_in),
    and a numbered floor must ALSO be the one ordinal plan_derive.
    title_ordinal reads: tokens_in reads "FIRST & SECOND FLOOR" as the
    second floor alone, and a title naming two floors is no one level."""
    from lib.plans.level_suggestion import floor_number, tokens_in
    from lib.plan_derive import title_ordinal
    toks, _ = tokens_in(title or "")
    if not toks:
        return None, f"title {title!r} names no level"
    if len(toks) > 1:
        return None, f"title {title!r} names {len(toks)} levels ({', '.join(sorted(toks))})"
    tok = toks[0]
    n = floor_number(tok)
    if n is not None and title_ordinal(title) != n:
        return None, f"title {title!r} does not name one floor"
    return tok, "parsed"


def _series(num: str) -> Optional[Tuple[str, str, int]]:
    m = _SHEET.match(str(num or "").strip().upper())
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def is_plan(page: dict) -> bool:
    return bool(re.search(r"\bPLANS?\b", str(page.get("sheet_title") or ""), re.I))


def is_riser_diagram(page: dict) -> bool:
    return bool(re.search(r"\bRISER\s+DIAGRAM\b", str(page.get("sheet_title") or ""), re.I))


def pair_by_title_level(others: Iterable[dict], arch: Iterable[dict]) -> Dict[str, Any]:
    """{"pairs": [(other, arch, offset)], "refused": [(other, why)],
    "series": {"P-2": {"offset", "held_by", "of"}}}.

    `others` are the discipline's plan pages (P or S), `arch` the track's
    architectural plan pages, each with sheet_number and sheet_title.

    A sheet pairs with the architectural plan whose title parses to the
    SAME single level - and only if the sheet-number offset of that pair
    (other sequence - arch sequence) is the offset a strict majority of its
    series' level-matched sheets hold. Refused, each with why: a number out
    of the plan series, a title naming no level or several, no
    architectural plan at that level or two of them, an offset that breaks
    the series', and every sheet of a series with no majority offset."""
    arch_by_level: Dict[str, List[dict]] = defaultdict(list)
    for a in arch:
        s = _series(a.get("sheet_number"))
        if not s or s[1] != "1" or not is_plan(a):
            continue
        lvl, _w = title_level(a.get("sheet_title"))
        if lvl:
            arch_by_level[lvl].append(a)
    refused: List[Tuple[dict, str]] = []
    cand: Dict[str, List[Tuple[dict, dict, int]]] = defaultdict(list)
    for p in others:
        num = p.get("sheet_number")
        s = _series(num)
        if not s:
            refused.append((p, f"{num}: not an NCS sheet number"))
            continue
        lvl, why = title_level(p.get("sheet_title"))
        if not lvl:
            refused.append((p, f"{num}: {why}"))
            continue
        match = arch_by_level.get(lvl) or []
        if len(match) != 1:
            refused.append((p, f"{num}: {len(match)} architectural plans titled at level "
                               f"{lvl}" + (f" ({', '.join(a['sheet_number'] for a in match)})"
                                           if match else "")))
            continue
        a = match[0]
        cand[f"{s[0]}-{s[1]}"].append((p, a, s[2] - _series(a["sheet_number"])[2]))
    pairs: List[Tuple[dict, dict, int]] = []
    series: Dict[str, Dict[str, Any]] = {}
    for key, rows in sorted(cand.items()):
        c = Counter(off for _p, _a, off in rows)
        off, n = c.most_common(1)[0]
        if 2 * n <= len(rows):
            series[key] = {"offset": None, "held_by": n, "of": len(rows),
                           "offsets": dict(c)}
            for p, a, o in rows:
                refused.append((p, f"{p['sheet_number']}: series {key}xx has no majority "
                                   f"offset ({dict(c)}); not paired"))
            continue
        series[key] = {"offset": off, "held_by": n, "of": len(rows)}
        for p, a, o in rows:
            if o == off:
                pairs.append((p, a, o))
            else:
                refused.append((p, f"{p['sheet_number']}: titled at the level of "
                                   f"{a['sheet_number']}, but that is offset {o:+d} and "
                                   f"series {key}xx runs {off:+d}; not paired"))
    return {"pairs": pairs, "refused": refused, "series": series}


# ── registration used only for the offset ─────────────────────────────────

def registration_usable(reg: dict, second: Optional[int] = None) -> Tuple[bool, List[str]]:
    """(usable, why not): plan_sheet.register's own verdict, AND the best
    peak must hold at least twice the anchors of any other offset (the
    second peak) - the same "half" comparison register makes between its
    offset and the best. Both can fail: a test feeds each its failing case."""
    if second is None:
        second = reg.get("second_peak_anchors")
    why = []
    if not reg.get("usable"):
        why.append(f"register refused: {reg.get('refused')}")
    best = reg.get("best_peak_anchors") or 0
    if second is None:
        why.append("second peak not measured")
    elif 2 * second > best:
        why.append(f"a second offset holds {second} anchors, over half the best "
                   f"peak's {best}: the alignment is ambiguous")
    return (not why), why


def to_arch(x: float, y: float, reg: dict) -> Tuple[float, float]:
    """A point on the other sheet in the architectural sheet's frame
    (register returns other = arch + (dx, dy))."""
    return x - reg["dx"], y - reg["dy"]


# ── which space a stack is in ──────────────────────────────────────────────

#: how far either side of a wall a stack in it is probed for the space it
#: serves (plan_takeoff.PROBE_MAX_IN, the host-wall probe's own reach)
WALL_PROBE_IN = 24.0


def where(units, x: float, y: float) -> Tuple[Optional[str], str]:
    """(space, how) for an architectural point, on plan_takeoff.Units.

    A stack is a pipe in a wall more often than not, and a wet wall between
    two bathrooms serves BOTH: so a point in a wall is probed along the
    wall's normal BOTH WAYS, and the answer names both sides ("wall: 4C |
    4D") - never the nearer one, never the side the unit tags lean to (the
    equipment probe's rule, which picks one). A point in free space is that
    space (Units._space: a unit, a named non-unit room, or refused)."""
    from lib.plan_takeoff import PPI
    g = units.st.get("grid")
    if g is None:
        return None, "no membership map"
    r0, c0 = units.cell(x, y)
    h, w = g.shape
    if not (0 <= r0 < h and 0 <= c0 < w):
        return None, "off the plan"
    if not g[r0, c0]:
        if units._outdoors(r0, c0):
            return None, "outdoors"
        u, why = units._space(r0, c0)
        return (u, "inside") if u else (None, why)
    lim = int(WALL_PROBE_IN * PPI / units.c) + 1

    def run(dr, dc):
        n = 0
        for sg in (1, -1):
            k = 1
            while k <= 4 * lim:
                rr, cc = r0 + sg * dr * k, c0 + sg * dc * k
                if not (0 <= rr < h and 0 <= cc < w) or not g[rr, cc]:
                    break
                k += 1
            n += k - 1
        return n
    dr, dc = (1, 0) if run(0, 1) >= run(1, 0) else (0, 1)
    sides = []
    for sg in (1, -1):
        got = None
        for k in range(1, lim + 1):
            rr, cc = r0 + sg * dr * k, c0 + sg * dc * k
            if not (0 <= rr < h and 0 <= cc < w):
                break
            if not g[rr, cc]:
                if units._outdoors(rr, cc):
                    got = "outdoors"
                else:
                    u, why = units._space(rr, cc)
                    got = u or "unresolved"
                break
        sides.append(got or f"nothing within {WALL_PROBE_IN:.0f}in")
    how = f"in a wall; probed both ways along its normal ({'N-S' if dr else 'E-W'})"
    if sides[0] == sides[1] and not sides[0].startswith(("nothing", "unresolved", "outdoors")):
        return sides[0], how + ": the same space both sides"
    return "wall: " + " | ".join(sides), how


# ── riser diagram cross-check ──────────────────────────────────────────────

def expand_id(tag_id: Optional[str]) -> List[str]:
    """'V-1-2' (one vent through the roof for stacks 1 and 2) -> ['V-1',
    'V-2']; 'S-3' -> ['S-3']; unread -> []."""
    m = re.fullmatch(r"([A-Z]{1,2})-(\d{1,2})(?:-(\d{1,2}))?", str(tag_id or ""))
    if not m:
        return []
    return [f"{m.group(1)}-{m.group(2)}"] + ([f"{m.group(1)}-{m.group(3)}"] if m.group(3) else [])


def crosscheck(plans: Dict[str, List[Optional[str]]], risers: Dict[str, List[Optional[str]]]
               ) -> Dict[str, Any]:
    """Every stack ID the plans tag against every ID the riser diagrams tag.

    `plans`: sheet -> the tag ids it prints (None = unread); `risers`: riser
    sheet -> its tag ids. A combined riser tag (V-1-2) names each stack it
    joins. Mismatches, every one listed:
      on_plans_not_riser   an ID a plan tags that no riser diagram does
      on_riser_not_plans   an ID a riser diagram tags that no plan does
      unread               a tag on either whose text was not decided
    plus per ID the sheets that tag it and how many tags each prints."""
    on_plans: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    on_riser: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unread = []
    for src, store in ((plans, on_plans), (risers, on_riser)):
        for sheet, ids in src.items():
            for i in ids:
                if not i:
                    unread.append(sheet)
                    continue
                for e in expand_id(i):
                    store[e][sheet] += 1
    ids = sorted(set(on_plans) | set(on_riser), key=_id_key)
    # [sheet, tags] pairs, not {sheet: n}: a sheet number has a dot in it,
    # and a stored document's keys should not
    return {"ids": {i: {"plans": sorted([k, v] for k, v in on_plans.get(i, {}).items()),
                        "risers": sorted([k, v] for k, v in on_riser.get(i, {}).items())}
                    for i in ids},
            "on_plans_not_riser": [i for i in ids if i in on_plans and i not in on_riser],
            "on_riser_not_plans": [i for i in ids if i in on_riser and i not in on_plans],
            "unread": sorted(Counter(unread).items())}


def _id_key(i: str):
    m = re.fullmatch(r"([A-Z]+)-(\d+)", i)
    return (m.group(1), int(m.group(2))) if m else (i, 0)


# ── the rows C1 reads ──────────────────────────────────────────────────────

def stack_rows(track: str, p_page: dict, a_page: Optional[dict], tags: Sequence[dict],
               reg: Optional[dict], usable: bool, why_not: Sequence[str],
               placed: Optional[Callable[[float, float], Tuple[Optional[str], str]]] = None,
               refused: Optional[str] = None) -> List[Dict[str, Any]]:
    """One row per stack (a leader end at a pipe circle), plus one per tag
    or leader that found none - never a silent miss.

    A row's footprint is in ARCHITECTURAL page points only when the pair
    was decided by title level AND the registration is usable; otherwise
    `at_arch` is None and `placement_refused` says why. C1 tests
    `footprint_arch` (centre + radius, a circle) against a polygon in the
    same architectural sheet's frame."""
    rows = []
    base = {"record_type": "stack", "row_version": ROW_VERSION, "track": track,
            "plumbing_sheet": p_page.get("sheet_number"), "plumbing_page_id": p_page.get("page_id"),
            "plumbing_file": p_page.get("file_name"), "plumbing_page": p_page.get("page_number"),
            "arch_sheet": (a_page or {}).get("sheet_number"),
            "arch_page_id": (a_page or {}).get("page_id"),
            "arch_file": (a_page or {}).get("file_name"),
            "arch_page": (a_page or {}).get("page_number"),
            # the same page reference lib.plan_structural (lane T3) writes:
            # clash v1 joins the two on (track, a_sheet.page_id), and both
            # trades' geometry is in that A page's display points
            "a_sheet": None if not a_page else {k: a_page.get(k) for k in (
                "page_id", "file_id", "file_name", "page_number", "sheet_number",
                "sheet_title", "file_hash")},
            "registration": None if not reg else {
                "dx": round(reg["dx"], 3), "dy": round(reg["dy"], 3), "anchors": reg.get("anchors"),
                "best_peak_anchors": reg.get("best_peak_anchors"),
                "second_peak_anchors": reg.get("second_peak_anchors"),
                "rms_in": round(reg.get("rms_in", 0.0), 3), "max_in": round(reg.get("max_in", 0.0), 3),
                "usable": usable, "why_not": list(why_not) or None}}
    for t in tags:
        tbase = dict(base, tag_id=t.get("id"), tag_letter=t.get("letter"),
                     tag_number=t.get("number"), tag_read=t.get("read_why"),
                     tag_at=(round(t["x"], 2), round(t["y"], 2)),
                     tag_system=TAG_SYSTEM.get(t.get("letter") or ""),
                     # the note's OCR, as evidence only: NO SIZE IS STORED.
                     # Measured 2026-10-28: the SHX inch mark reads as 17,
                     # 99, 7J; a size came out on 13 of 117 plan tags and at
                     # least two were wrong (P-101.00 W-1's 3/4" read 4").
                     note_ocr=t.get("note"),
                     findings=tag_system_check(t) or None)
        if not t.get("leaders"):
            rows.append(dict(tbase, stack_at=None, footprint_arch=None, at_arch=None,
                             status="no_leader", reason="the tag has no leader leaving its rim"))
            continue
        for ld in t["leaders"]:
            st = ld.get("stack")
            if not st:
                rows.append(dict(tbase, stack_at=None, footprint_arch=None, at_arch=None,
                                 leader_tip=(round(ld["tip"][0], 2), round(ld["tip"][1], 2)),
                                 status="no_stack", reason=ld.get("why")))
                continue
            row = dict(tbase, stack_at=(round(st["x"], 2), round(st["y"], 2)),
                       stack_radius_pt=round(st["r"], 2), pipe_layers=st["layers"],
                       pipe_systems=st["systems"], pipe_drawn=st.get("drawn"),
                       leader_tip=(round(ld["tip"][0], 2), round(ld["tip"][1], 2)),
                       aim_off_pt=st.get("aim_off_pt"), status="located")
            if refused:
                row.update(at_arch=None, footprint_arch=None, placement_refused=refused)
            elif not usable:
                row.update(at_arch=None, footprint_arch=None,
                           placement_refused="registration not usable: " + "; ".join(why_not))
            else:
                ax, ay = to_arch(st["x"], st["y"], reg)
                row.update(at_arch=(round(ax, 2), round(ay, 2)),
                           footprint_arch={"type": "circle", "x": round(ax, 2), "y": round(ay, 2),
                                           "r": round(st["r"], 2), "frame": "arch_page_pt"},
                           placement_refused=None)
                if placed is not None:
                    where, how = placed(ax, ay)
                    row.update(space=where, space_how=how)
            rows.append(row)
    return rows


def continuity(rows: Sequence[dict], tol_in: float = 6.0) -> List[Dict[str, Any]]:
    """Per (track, stack ID): the floors it is located on and whether every
    floor puts it at the same architectural location within tol_in (a
    stack is a vertical pipe; the A sheets of one set share a frame only if
    the architect's sheets do - so this compares, it does not assume)."""
    from lib.plan_sheet import inches
    by: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in rows:
        if r.get("status") == "located" and r.get("at_arch") and r.get("tag_id"):
            by[(r["track"], r["tag_id"])].append(r)
    out = []
    for (track, tid), rs in sorted(by.items(), key=lambda kv: (kv[0][0], _id_key(kv[0][1]))):
        pts = [r["at_arch"] for r in rs]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        spread = max(inches(math.dist(p, (cx, cy))) for p in pts)
        out.append({"track": track, "id": tid,
                    "floors": sorted({r["plumbing_sheet"] for r in rs}),
                    "stacks": len(rs), "max_from_mean_in": round(spread, 1),
                    "same_place": spread <= tol_in})
    return out


__all__ = [
    "COLLECTION", "ROW_VERSION", "Sheet", "fit_circle", "arcs_of", "pipe_rounds", "circle_of", "split_circle_tags", "trace_leaders",
    "arrowhead_at", "pipe_circles", "stack_at", "signature", "compose", "vote",
    "read_tags", "locate", "tag_system_check", "title_level",
    "pair_by_title_level", "registration_usable",
    "to_arch", "expand_id", "crosscheck", "stack_rows", "continuity",
    "is_plan", "is_riser_diagram", "where", "printed_size", "read_note", "note_strokes",
]


# ── the pass ───────────────────────────────────────────────────────────────

def _is_p(page: dict) -> bool:
    return str(page.get("sheet_number") or "").strip().upper().startswith("P-")


def sheet_row(track: str, p_page: dict, status: str, reason: str) -> Dict[str, Any]:
    """A row about a whole plumbing sheet: no tags on it, or it failed."""
    return {"record_type": "stack_sheet", "row_version": ROW_VERSION, "track": track,
            "plumbing_sheet": p_page.get("sheet_number"), "plumbing_page_id": p_page.get("page_id"),
            "status": status, "reason": reason}


def run_stacks(tracks: Sequence[Tuple[str, List[dict]]], open_page: Callable,
               reader: Optional[Callable[[bytes], list]] = None,
               door_inches: Optional[float] = None, place: bool = True) -> Dict[str, Any]:
    """Every stack of the set, per drawing track, in architectural points.

    `tracks`: [(track, page dicts)] as the glyph pass builds them (sheet_number,
    sheet_title, page_id, file_id, page_number). A plumbing sheet belongs to
    no track - the filed track holds it, as it holds the mechanical sheets -
    and is read ONCE; each track pairs it with its own architectural plans
    by title level and places its stacks there.

    Returns {"rows", "crosscheck", "continuity", "pairing", "summary"}. Every
    stack is a row; a tag or leader that reaches no stack is a row; a sheet
    with no tags is a row; a sheet that cannot be paired keeps its stacks as
    rows with placement refused - nothing is dropped silently."""
    from lib import plan_derive as derive
    from lib.plan_sheet import load_sheet, register
    tracks = list(tracks)
    filed = next((pp for t, pp in tracks if t == "filed"), [])
    p_pages = [p for p in filed if _is_p(p) and (is_plan(p) or is_riser_diagram(p))]
    located: Dict[str, Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []
    for p in p_pages:
        key = str(p.get("page_id"))
        try:
            got = locate(open_page(p), tags_only=is_riser_diagram(p))
        except Exception as e:                      # one sheet never sinks the pass
            rows.append(sheet_row("filed", p, "failed", f"{type(e).__name__}: {e}"))
            continue
        got.pop("sheet", None)
        located[key] = got
    every = [t for g in located.values() for t in g["tags"]]
    if every:
        read_tags(every, reader)
    for t in every:
        polys = t.pop("note_polys", None) or {}
        note = {side: read_note(pl, reader) for side, pl in polys.items() if pl}
        t["note"] = note or None
    plans = [p for p in p_pages if is_plan(p) and str(p.get("page_id")) in located]
    risers = [p for p in p_pages if is_riser_diagram(p) and str(p.get("page_id")) in located]
    pairing: Dict[str, Any] = {}
    for track, pages in tracks:
        arch = [p for p in pages if str(p.get("sheet_number") or "").upper().startswith("A")]
        pr = pair_by_title_level(plans, arch)
        pairing[track] = {"series": pr["series"],
                          "pairs": [(p["sheet_number"], a["sheet_number"], o) for p, a, o in pr["pairs"]],
                          "refused": [(p["sheet_number"], w) for p, w in pr["refused"]]}
        for p, why in pr["refused"]:
            tags = located[str(p["page_id"])]["tags"]
            rows += (stack_rows(track, p, None, tags, None, False, [], refused=why) if tags
                     else [sheet_row(track, p, "no_tags", "the sheet prints no split-circle tag")])
        for p, a, _off in pr["pairs"]:
            tags = located[str(p["page_id"])]["tags"]
            if not tags:
                rows.append(sheet_row(track, p, "no_tags", "the sheet prints no split-circle tag"))
                continue
            try:
                arch_pg = open_page(a)
                A, O = load_sheet(arch_pg), load_sheet(open_page(p))
                reg = register(A, O)
                ok, why = registration_usable(reg)
                placed = None
                if ok and place:
                    placed = _membership(arch_pg, A, door_inches)
                rows += stack_rows(track, p, a, tags, reg, ok, why, placed)
            except Exception as e:
                rows += stack_rows(track, p, a, tags, None, False, [],
                                   refused=f"placement failed: {type(e).__name__}: {e}")
    cc = crosscheck({p["sheet_number"]: [t.get("id") for t in located[str(p["page_id"])]["tags"]]
                     for p in plans},
                    {p["sheet_number"]: [t.get("id") for t in located[str(p["page_id"])]["tags"]]
                     for p in risers})
    summary = {"plumbing_sheets": len(p_pages), "plans": len(plans), "risers": len(risers),
               "tags": len(every), "unread_tags": sum(1 for t in every if not t.get("id")),
               "rows": len(rows),
               "located": sum(1 for r in rows if r.get("status") == "located"),
               "placed": sum(1 for r in rows if r.get("footprint_arch"))}
    return {"rows": rows, "crosscheck": cc, "pairing": pairing, "summary": summary,
            "riser_tags": [{"sheet": p["sheet_number"],
                            "ids": [t.get("id") for t in located[str(p["page_id"])]["tags"]]}
                           for p in risers]}


def _membership(arch_pg, sheet: dict, door_inches: Optional[float]):
    """where() over the architectural plan's membership map (the glyph
    pass's own: plan_derive.unit_tags + plan_space.build_space), or None
    when the plan names no units to seed it."""
    from lib import plan_derive as derive
    from lib.plan_space import build_space
    from lib.plan_takeoff import Units
    units = derive.unit_tags(sheet["words"], sheet["corners"])
    tags = units.get("tags")
    if tags is None:
        return lambda x, y: (None, f"the plan's units are unread: {units.get('why') or 'no tags'}")
    space = build_space(arch_pg, tags, door_inches, sheet)
    u = Units(space["units"], space["lo"], space["cell_pt"], space["refused"], space, space["tags"])
    return lambda x, y: where(u, x, y)


def unavailable(error: BaseException, when) -> Dict[str, Any]:
    """The one row a failed stack pass writes: never an empty collection
    that reads as "no stacks" (the set-health rule, 2026-10-26)."""
    return {"record_type": "stack_pass", "row_version": ROW_VERSION, "status": "unavailable",
            "reason": f"stack pass unavailable: {type(error).__name__}, as of {when.isoformat()}"}


def crosscheck_row(result: Dict[str, Any]) -> Dict[str, Any]:
    """The pass's set-wide row: the riser cross-check, the pairing (with
    every refusal) and the counts - stored beside the stack rows."""
    return {"record_type": "stack_crosscheck", "row_version": ROW_VERSION,
            "crosscheck": result.get("crosscheck"), "pairing": result.get("pairing"),
            "riser_tags": result.get("riser_tags"), "summary": result.get("summary")}
