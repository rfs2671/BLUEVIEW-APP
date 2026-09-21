"""Which room, and which unit, is a point on a plan in?

Pure geometry over a sheet's wall linework. No I/O, no model, no OCR — a
caller supplies segments and labelled points and gets a containment answer
with the reason it was reached.

── THE RULE, STATED BEFORE ANY SWEEP ──────────────────────────────────────

    The unit is the FINEST wall partition at which the point shares a cell
    with EXACTLY ONE unit label, and is at least ROOM_EDGE_EXCLUSION_IN from
    any boundary that could put it in a DIFFERENT unit.

Not "the threshold that gives the expected answer" — the first one that is
unambiguous. A caller gets back the threshold that decided it, so a result
sitting on a knife edge is visible as one.

── THREE THINGS MEASURED, EACH OF WHICH BROKE A NAIVE VERSION ─────────────

COLLINEAR FRAGMENTS. A length filter over raw segments misses every wall the
drawing draws in pieces. The 4A/4B demising wall on A-103.00 is plainly
visible and no single segment of it reaches 6ft, so the first partition ran
straight through it and returned one 31.8ft cell holding two apartments.
Runs are merged before they are measured.

NEAREST LABEL LOSES. Room labels sit at room centres, so a fixture near a
boundary is often closer to the neighbour's label than to its own: all eight
fans on M-103.00 came back BEDROOM, including the four at kitchenettes.
Containment has no such failure — a label is inside the cell or it is not.

A ONE-SIDED BOUNDARY IS NOT A RISK. The exclusion exists to stop a small
registration error carrying a point across a partition into the NEIGHBOURING
unit. At the building's exterior wall there is no neighbouring unit; beyond
it is outside. Four kitchenette fans refused at 6.5in from a boundary that
was the building envelope, with the correct unit label in the same cell and
no other unit label anywhere beyond. The distance is now measured only to
edges with another unit behind them.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lib.plan_registration import ROOM_EDGE_EXCLUSION_IN

#: Collinear pieces of one wall are joined across gaps up to this. Six inches
#: bridges line-join artifacts and hatch interruptions; a 3ft door opening is
#: a real gap and stays one.
WALL_MERGE_GAP_IN = 6.0

#: Two runs are collinear when their off-axis coordinate agrees to this.
#: A quarter point is 0.17in, tighter than any drawn wall offset.
WALL_COLLINEAR_TOL_PT = 0.25

#: Wall lengths tried, finest first. The rule takes the first that is
#: unambiguous; the list is a search order, not a set of tuned values.
UNIT_SWEEP_FT: Tuple[int, ...] = (4, 6, 8, 10, 12, 15, 18, 22, 26, 30, 36)

#: Room-label sweep, finer because a room is smaller than a unit.
ROOM_SWEEP_FT: Tuple[int, ...] = (3, 4, 6, 8, 10, 12)

Cell = Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]


def merge_runs(items: Iterable[Tuple[float, float, float]],
               max_gap_pt: float,
               tol_pt: float = WALL_COLLINEAR_TOL_PT) -> List[Tuple[float, float, float]]:
    """[(coord, lo, hi)] -> merged, joining collinear pieces along the run."""
    by_coord: Dict[int, List[Tuple[float, float]]] = {}
    for c, lo, hi in items:
        by_coord.setdefault(round(c / tol_pt), []).append((lo, hi))
    out: List[Tuple[float, float, float]] = []
    for key, spans in by_coord.items():
        c = key * tol_pt
        spans.sort()
        cur_lo, cur_hi = spans[0]
        for lo, hi in spans[1:]:
            if lo - cur_hi <= max_gap_pt:
                cur_hi = max(cur_hi, hi)
            else:
                out.append((c, cur_lo, cur_hi))
                cur_lo, cur_hi = lo, hi
        out.append((c, cur_lo, cur_hi))
    return out


def long_walls(segments: Sequence[Tuple[float, float, float, float]],
               min_len_pt: float, merge_gap_pt: Optional[float] = None,
               axis_tol_pt: float = 1.0):
    """(verticals, horizontals) at least `min_len_pt` long AFTER merging.

    Each vertical is (x, y_lo, y_hi); each horizontal is (y, x_lo, x_hi).
    """
    if merge_gap_pt is None:
        merge_gap_pt = WALL_MERGE_GAP_IN * 1.5     # pt per real inch at 1/4"
    v, h = [], []
    for x1, y1, x2, y2 in segments:
        dx, dy = x2 - x1, y2 - y1
        if abs(dx) < axis_tol_pt and abs(dy) > 0:
            v.append((x1, min(y1, y2), max(y1, y2)))
        elif abs(dy) < axis_tol_pt and abs(dx) > 0:
            h.append((y1, min(x1, x2), max(x1, x2)))
    v = [r for r in merge_runs(v, merge_gap_pt) if r[2] - r[1] >= min_len_pt]
    h = [r for r in merge_runs(h, merge_gap_pt) if r[2] - r[1] >= min_len_pt]
    return v, h


def title_block_edge(segments: Sequence[Tuple[float, float, float, float]],
                     page_width: float, page_height: float,
                     min_height_frac: float = 0.80,
                     search_from_frac: float = 0.55) -> float:
    """Where the drawing ends and the title block begins, in display points.

    DERIVED, NOT A FRACTION OF THE SHEET. A fixed 74% cut was clipping real
    plan content: on M-103.00 the building runs past x=1918 and the four PTAC
    units on its right-hand exterior wall sat at x~1922, outside the cut, so
    they were absent from every corner set and could never be found. The
    symptom looked like a detector failure and was a crop.

    A title block is ruled off by a vertical line running nearly the full
    height of the sheet. Take the LEFTMOST such line in the right-hand part
    of the page; that is the boundary the draughtsman drew. With none found,
    return the page width, which keeps everything rather than inventing an
    edge — losing drawing is the failure being fixed, and a title block left
    in costs some irrelevant corners and nothing else.
    """
    best = None
    for x1, y1, x2, y2 in segments:
        if abs(x2 - x1) >= 1.0:
            continue
        if abs(y2 - y1) < min_height_frac * page_height:
            continue
        if x1 < search_from_frac * page_width:
            continue
        best = x1 if best is None else min(best, x1)
    return best if best is not None else page_width


def cell_of(px: float, py: float, verticals, horizontals) -> Cell:
    """(left, right, below, above): the nearest bounding wall on each side
    that actually spans the point's other coordinate. None where unbounded."""
    left = max([x for x, y0, y1 in verticals
                if x <= px and y0 - 1 <= py <= y1 + 1], default=None)
    right = min([x for x, y0, y1 in verticals
                 if x >= px and y0 - 1 <= py <= y1 + 1], default=None)
    below = max([y for y, x0, x1 in horizontals
                 if y <= py and x0 - 1 <= px <= x1 + 1], default=None)
    above = min([y for y, x0, x1 in horizontals
                 if y >= py and x0 - 1 <= px <= x1 + 1], default=None)
    return left, right, below, above


def bounded(cell: Cell) -> bool:
    return all(v is not None for v in cell)


def contains(cell: Cell, x: float, y: float) -> bool:
    if not bounded(cell):
        return False
    l, r, b, a = cell
    return l <= x <= r and b <= y <= a


def risky_edge_distance_pt(px: float, py: float, cell: Cell,
                           labels: Dict[str, Tuple[float, float]],
                           own: str) -> float:
    """Distance to the nearest boundary that could yield a DIFFERENT label.

    An edge counts only when some other label lies beyond it. Where none
    does — the building envelope — no error of any size reassigns the point,
    so the exclusion has nothing to protect against and returns infinity.
    """
    if not bounded(cell):
        return 0.0
    l, r, b, a = cell
    others = [(x, y) for t, (x, y) in labels.items() if t != own]
    d: List[float] = []
    if any(x < l for x, _y in others):
        d.append(px - l)
    if any(x > r for x, _y in others):
        d.append(r - px)
    if any(y < b for _x, y in others):
        d.append(py - b)
    if any(y > a for _x, y in others):
        d.append(a - py)
    return min(d) if d else float("inf")


def unit_of(px: float, py: float,
            segments: Sequence[Tuple[float, float, float, float]],
            labels: Dict[str, Tuple[float, float]],
            pt_per_inch: float,
            sweep_ft: Sequence[int] = UNIT_SWEEP_FT,
            exclusion_in: float = ROOM_EDGE_EXCLUSION_IN):
    """(label, wall_ft, edge_in) or (None, None, None) when it cannot say.

    Returning the threshold and the edge distance is the point: a caller can
    see whether the answer sat on a plateau or on a knife edge, and a record
    written from it carries both.
    """
    for ft in sweep_ft:
        v, h = long_walls(segments, ft * 12 * pt_per_inch,
                          WALL_MERGE_GAP_IN * pt_per_inch)
        cell = cell_of(px, py, v, h)
        if not bounded(cell):
            continue
        hits = [t for t in sorted(labels) if contains(cell, *labels[t])]
        if len(hits) != 1:
            continue
        edge_pt = risky_edge_distance_pt(px, py, cell, labels, hits[0])
        edge_in = edge_pt / pt_per_inch
        if edge_in >= exclusion_in:
            return hits[0], ft, edge_in
    return None, None, None


def containing_label(px: float, py: float,
                     segments: Sequence[Tuple[float, float, float, float]],
                     points: Sequence[Tuple[str, float, float]],
                     vocabulary: Sequence[str],
                     pt_per_inch: float,
                     sweep_ft: Sequence[int] = ROOM_SWEEP_FT):
    """The vocabulary words inside the point's own cell, finest cell first.

    Used for the room, which is a CROSS-CHECK and not a decision: it returns
    every matching word in the cell rather than picking, so a caller can see
    a cell that swept up the whole floor plate for what it is.
    """
    vocab = {w.upper() for w in vocabulary}
    for ft in sweep_ft:
        v, h = long_walls(segments, ft * 12 * pt_per_inch,
                          WALL_MERGE_GAP_IN * pt_per_inch)
        cell = cell_of(px, py, v, h)
        if not bounded(cell):
            continue
        hits = sorted({t.upper() for t, x, y in points
                       if t.upper() in vocab and contains(cell, x, y)})
        if hits:
            return hits, ft
    return [], None


__all__ = [
    "WALL_MERGE_GAP_IN", "WALL_COLLINEAR_TOL_PT",
    "UNIT_SWEEP_FT", "ROOM_SWEEP_FT",
    "merge_runs", "long_walls", "title_block_edge",
    "cell_of", "bounded", "contains",
    "risky_edge_distance_pt", "unit_of", "containing_label",
]
