"""A WALLED OPEN-TO-BELOW VOID BELONGS TO THE UNIT BENEATH IT.

The filed mezzanine A-104.00 (AR 3.28.25) walls four bays off from 4A-4D:
open to the bedroom below, unnamed, doorless. M-104.00 hangs a PTAC-1 on the
wall of each, so all four were refused ("unnamed, doorless non-unit region")
and the filed track could give no PTAC figure for 4A-4D.

Ruling 2026-10-24 (operator). A region is MARKED open-to-below if EITHER
  (a) text inside it reads OPEN TO BELOW, OPEN BELOW, O.T.B. or VOID; or
  (b) an X spans it: two diagonals joining opposite corners of the enclosed
      region (within registration tolerance), drawn on a layer whose name
      contains BELOW, OPEN or VOID.
NOT a void - refused as before:
  - an X on any other layer, or a layerless PDF with no text;
  - a region whose text says SHAFT, CHASE or ELEV;
  - an X that does not span the region corner to corner.
And a marked void joins unit U only if the registration to the floor below
is usable and EXACTLY ONE UNIT lies beneath it - the symbol is then U's.

Measured 2026-10-24, every A-1xx plan of both tracks (12 sheets, every X
found by room and by geometry): the filed A-104.00 draws 14 X's, all on
"XR FLOOR PLANS|A-BELOW"; 4 span their own enclosed region - the four bays,
over 4A, 4B, 4C and 4D (97% of each bay's cells; the rest wall) - and 10 sit
inside 4A-4D's own regions. The light shaft between the core and C/D carries
an A-BELOW X too, with no unit beneath it: refused. Every other X on every
sheet is on A-ABOVE, A-Wall or SECTION CUT. The owner's set has no void bays.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from lib.plan_registration import ANCHOR_MATCH_RADIUS_IN
from lib.plan_sheet import CELL_IN

#: (a): the words that mark a region open to below.
MARK_TEXT = re.compile(r"\bOPEN\s+TO\s+BELOW\b|\bOPEN\s+BELOW\b|(?<![A-Z.])O\.T\.B\.?(?![A-Z])"
                       r"|\bVOID\b", re.I)
#: A region that says it is a shaft, chase or elevator is never a void.
NOT_VOID = re.compile(r"\b(?:SHAFT|CHASE|ELEV)", re.I)
#: (b): the layers an open-to-below X is drawn on.
MARK_LAYER = re.compile(r"BELOW|OPEN|VOID", re.I)
#: Of each diagonal: drawn along this much of it, and run through the
#: region's own cells this much (an X drawn across a sliver's bounding box
#: crosses the room beside it, not the sliver).
COVER, INSIDE = 0.8, 0.8


def _box(lab: np.ndarray, L: int, lo, cell: float) -> Tuple[float, float, float, float]:
    ys, xs = np.nonzero(lab == L)
    return (lo[0] + xs.min() * cell, lo[1] + ys.min() * cell,
            lo[0] + (xs.max() + 1) * cell, lo[1] + (ys.max() + 1) * cell)


def _diagonal(att, a, b, tol: float, layer_ok) -> Tuple[float, float]:
    """(how much of the segment a->b is drawn on a layer `layer_ok` accepts,
    the larger gap between that drawing and either end), in pt."""
    (ax, ay), (bx, by) = a, b
    L = float(np.hypot(bx - ax, by - ay))
    ux, uy = (bx - ax) / L, (by - ay) / L
    cov = np.zeros(400, bool)
    for (sx, sy, ex, ey), layer in att:
        if not layer_ok(layer):
            continue
        if abs((sx - ax) * uy - (sy - ay) * ux) > tol or abs((ex - ax) * uy - (ey - ay) * ux) > tol:
            continue
        t1, t2 = sorted((((sx - ax) * ux + (sy - ay) * uy) / L, ((ex - ax) * ux + (ey - ay) * uy) / L))
        if t2 < 0 or t1 > 1:
            continue
        cov[max(int(t1 * 400), 0):min(int(np.ceil(t2 * 400)), 400)] = True
    if not cov.any():
        return 0.0, L
    idx = np.nonzero(cov)[0]
    return float(cov.mean()), max(idx[0] / 400 * L, (1 - (idx[-1] + 1) / 400) * L)


def _through(lab, L, lo, cell, a, b) -> float:
    """The share of the segment a->b that runs through region L's cells."""
    h, w = lab.shape
    hit = 0
    ts = np.linspace(0.02, 0.98, 60)
    for t in ts:
        x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        r, c = int((y - lo[1]) / cell), int((x - lo[0]) / cell)
        win = lab[max(r - 1, 0):min(r + 2, h), max(c - 1, 0):min(c + 2, w)]
        hit += bool((win == L).any())
    return hit / len(ts)


def x_across(att, lab, L, lo, cell, tol, layer_ok) -> bool:
    """Both diagonals of region L's box drawn corner to corner on layers
    `layer_ok` accepts, through the region itself."""
    x0, y0, x1, y1 = _box(lab, L, lo, cell)
    for a, b in (((x0, y0), (x1, y1)), ((x0, y1), (x1, y0))):
        cover, gap = _diagonal(att, a, b, tol, layer_ok)
        if cover < COVER or gap > tol or _through(lab, L, lo, cell, a, b) < INSIDE:
            return False
    return True


def marked_voids(space: Dict[str, Any], sheet: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """([{"room", "how": "text" | "x", "box"}], notes) for every region of the
    sheet's room map that no unit holds and is marked open to below. A sheet
    with no room map (no CAD wall layer) gives none."""
    lab = space.get("closed_lab")
    if lab is None:
        return [], []
    lo, cell = space["lo"], space["cell_pt"]
    ppi = cell / CELL_IN
    # one grid cell (the region's edge is quantised to it) and the registration
    # match radius - "within registration tolerance"
    tol = (CELL_IN + ANCHOR_MATCH_RADIUS_IN) * ppi
    held = set()
    for m in (space.get("units") or {}).values():
        held |= set(np.unique(lab[m]).tolist())
    public = space.get("public")
    if public is not None:
        held |= set(np.unique(lab[public]).tolist())
    outdoors = set(space.get("outdoors") or [])
    text: Dict[int, List[str]] = {}
    h, w = lab.shape
    for word, x, y in sheet.get("words") or []:
        r, c = int((y - lo[1]) / cell), int((x - lo[0]) / cell)
        if 0 <= r < h and 0 <= c < w and lab[r, c] > 0:
            text.setdefault(int(lab[r, c]), []).append(str(word))
    att = sheet.get("att") or []
    out, notes = [], []
    for L in sorted(int(v) for v in np.unique(lab)):
        if L == 0 or L in held or L in outdoors:
            continue
        ys, xs = np.nonzero(lab == L)
        box = _box(lab, L, lo, cell)
        if box[2] - box[0] < 4 * tol or box[3] - box[1] < 4 * tol:
            continue                # a sliver: no X can span it
        words = re.sub(r"\s+", " ", " ".join(text.get(L, [])))
        at = f"region at ({round((box[0] + box[2]) / 2)}, {round((box[1] + box[3]) / 2)})"
        if NOT_VOID.search(words):
            if MARK_TEXT.search(words) or x_across(att, lab, L, lo, cell, tol, lambda _l: True):
                notes.append(f"{at}: says {NOT_VOID.search(words).group(0)} - not a void")
            continue
        if MARK_TEXT.search(words):
            out.append({"room": L, "how": "text", "box": [round(v, 1) for v in box],
                        "mark": MARK_TEXT.search(words).group(0)})
        elif x_across(att, lab, L, lo, cell, tol, lambda l: bool(MARK_LAYER.search(l or ""))):
            out.append({"room": L, "how": "x", "box": [round(v, 1) for v in box]})
        elif x_across(att, lab, L, lo, cell, tol, lambda _l: True):
            notes.append(f"{at}: an X spans it on no BELOW/OPEN/VOID layer - not a void")
    return out, notes


def beneath(lab: np.ndarray, L: int, lo, cell: float, below: Dict[str, Any],
            dx: float, dy: float) -> Tuple[Dict[Optional[str], int], int]:
    """({unit or None: cells}, wall cells) - region L's cells carried onto
    the floor below by (dx, dy): the unit each lands in, None for a room no
    unit holds, and how many land on a wall or off the map."""
    blab = below.get("closed_lab")
    units = below.get("units") or {}
    blo, bcell = below["lo"], below["cell_pt"]
    bh, bw = (blab.shape if blab is not None else next(iter(units.values())).shape)
    hits: Dict[Optional[str], int] = {}
    wall = 0
    ys, xs = np.nonzero(lab == L)
    for y, x in zip(lo[1] + (ys + 0.5) * cell, lo[0] + (xs + 0.5) * cell):
        r, c = int((y + dy - blo[1]) / bcell), int((x + dx - blo[0]) / bcell)
        if not (0 <= r < bh and 0 <= c < bw) or (blab is not None and blab[r, c] == 0):
            wall += 1
            continue
        u = next((t for t, m in units.items() if m[r, c]), None)
        hits[u] = hits.get(u, 0) + 1
    return hits, wall
