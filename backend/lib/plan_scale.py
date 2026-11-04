"""The scale of each drawing on a sheet, read per viewport and checked.

Operator's rule (Roy, 2026-10-26): "Scale per drawing: detect each viewport
(boundary, title bar, scale note inside it); scale from the note inside the
viewport, never the nearest note; verify against >=3 printed dimensions
measured on that viewport; refuse a viewport that doesn't verify."

Every answer that turns a length on paper into a length in the building (an
apartment's area, a run of wall) needs this. The plan reader so far assumes
1/4" = 1'-0" everywhere (plan_registration.PLAN_SCALE_DENOM); this module is
what replaces the assumption. Its readers: lib.plan_areas (each A floor
plan's own verified scale), and the glyph pass's record of each mechanical
plan's scale, borrowed from its architectural partner (`borrow`).

── WHAT WENT WRONG BEFORE, AND THE RULE EACH ONE GAVE ─────────────────────

Matchline's sheet_scale on 588 Boyland (read-only, 2026-10-24):

  * A-100.01 took "PTAC UNIT 3'-8" X 1'-6" = 5.5'" as a scale of 1:11. That
    line is arithmetic in a code note. A scale note is a PAPER length in
    inches equal to a REAL length in feet-inches (1/4" = 1'-0", 1" = 20'-0");
    nothing else is parsed as one (`parse_scale_note`).
  * S-106.00 prints 1/4" = 1'-0" under the roof framing plan and
    1/8" = 1'-0" under the bulkhead roof; a per-sheet scale has no answer.
    So the unit is the VIEWPORT, not the sheet.
  * Taking the nearest note to a point carries a note across the boundary of
    the drawing it belongs to. So a viewport is found first, and only the
    note in ITS OWN title bar can scale it.

── A VIEWPORT ─────────────────────────────────────────────────────────────

None of these sheets draws a frame around a view, so the boundary is read
from the ink. Everything drawn left of the title block is rasterised at
CELL_PT and pieces closer than MERGE_GAP_PT are joined: a drawing is one
connected body of ink, its dimension strings tied to it by their extension
lines (which stop 1/16" short of the object, well inside the gap), and two
drawings on a sheet are separated by white space wider than the gap.

A TITLE BAR is a scale note in the text layer with the view's title on the
line above it (`find_scale_notes`). It labels the drawing it sits UNDER:

  * if the title bar's own body of ink extends more than an inch above it,
    the bar was drawn close enough to join its drawing, and that body is the
    view;
  * otherwise the view is the first drawing-sized body (an inch or more each
    way) directly above the bar, overlapping it horizontally.

A drawing claimed by two title bars whose notes differ is refused for both:
which note governs is exactly the question that cannot be guessed. A drawing
no title bar claims is reported as a viewport with no scale.

── VERIFIED, OR REFUSED ───────────────────────────────────────────────────

The note is a claim the drawing has to back. Every dimension string inside
the viewport's body is MEASURED (`measure_dimension`): its dimension line,
then the terminators at each end - ticks, arrow tips, extension lines - and
the distance between the outermost two, in points. That length over the
printed value is the scale that dimension implies.

A viewport is VERIFIED when at least MIN_AGREEING of its dimensions agree
with its note within AGREE_TOL, at least MIN_DISTINCT different printed
values are among those (copies count, ruling 2026-10-27), and no other
scale is implied by more of them than the note's is. Otherwise it is
refused, with the reason.

AGREE_TOL is set from what the error is made of, not from a pass rate (see
the constant). A sheet whose scale text is drawn as vectors (SHX text: the
eight P sheets) has no note in the text layer and is refused for that,
whatever its drawing measures.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from lib import plan_dimensions as pdim
from lib.plan_cells import title_block_edge

# ── constants ──────────────────────────────────────────────────────────────

#: A dimension agrees with a note when the scale it implies is within this
#: fraction of the note's. FROM THE ERROR BUDGET, NOT FROM A PASS RATE:
#:   - a printed dimension is rounded, normally to the nearest 1/2" (half a
#:     unit of error is 1/4"); on a 1'-0" dimension that is 2.1%, on 2'-0"
#:     1.0%, and on anything longer smaller still;
#:   - the drawn geometry is exact: on 588 Boyland 1,174 of the 1,466
#:     dimensions measured inside a titled viewport sit within 0.1% of their
#:     own note and 1,245 within 0.5% (L1_scale_measure.md);
#:   - the CLOSEST pair of standard scales (3/16 vs 1/4, 3/32 vs 1/8, 3/8 vs
#:     1/2) differ by 25% to 33%; the tolerance must be far inside half of
#:     that so one dimension can never agree with two standard scales.
#: 3% covers the rounding of a 1'-0" dimension with margin and is under a
#: tenth of the gap to the next scale. Measured sensitivity, not tuning:
#: every Boyland verdict is the same for any value from 0.5% to 5%; the
#: first change is at 8%, and at 10% three SET_UPDATED elevations whose
#: drawing is 9.7% larger than their 3/16" note would wrongly verify.
#: With MIN_DISTINCT (2026-10-27, Q10_scale_distinct_measure.md) every
#: verdict is the same from 2.1% to 7%; under 2.05% GN-004.00's FIRST FLOOR
#: EGRESS PLAN loses its only second value (30'-5", drawn 2.05% short), and
#: those three elevations, which print one value (10'-0"), no longer verify
#: at 10%.
AGREE_TOL = 0.03

#: Dimensions that must agree before a viewport's note is accepted.
MIN_AGREEING = 3

#: ...and how many DIFFERENT printed values must be among them (ruling,
#: Roy 2026-10-27: "copies count, but the >=3 must include >=2 distinct
#: dimension values"). Eight 3'-0" door widths on an egress plan, or six
#: 10'-0" floor-to-floor heights on an elevation, are one length drawn eight
#: or six times - often one block copied - so they check the note at one
#: length only. Copies still count toward MIN_AGREEING; a value is the
#: printed length (36" and 3'-0" are one value), and only agreeing ones count.
MIN_DISTINCT = 2

#: Raster cell for finding the bodies of ink, in points.
CELL_PT = 3.0

#: Ink closer than this is one body. A quarter inch: extension lines stop
#: 1/16" to 1/8" short of what they dimension, and drawings on one sheet
#: are separated by more than this.
MERGE_GAP_PT = 18.0

#: A body of ink at least this wide AND tall can be a drawing (one inch).
DRAWING_MIN_PT = 72.0

#: A title bar is joined to its drawing when its body extends at least this
#: far beyond the bar (one inch).
JOINED_PT = 72.0

#: The sheet border is a long straight line this close to the page edge.
BORDER_MARGIN_PT = 108.0

#: Paper inches per real foot of the standard architectural scales, and the
#: real feet per paper inch of the engineering ones. Used ONLY to read
#: "5 3/16" = 1'-0"" - a detail bubble numbered 5 beside a 3/16" note - as
#: 3/16", and "1 1/2" = 1'-0"" as 1 1/2". Any other parse stands as printed.
_STANDARD_PAPER_IN_PER_FT = {Fraction(1, 32), Fraction(1, 16), Fraction(3, 32),
                             Fraction(1, 8), Fraction(3, 16), Fraction(1, 4),
                             Fraction(3, 8), Fraction(1, 2), Fraction(3, 4),
                             Fraction(1), Fraction(3, 2), Fraction(3)}

_Q = "\"”″"
_F = "'’′"

#: A scale note: a PAPER length in inches = a REAL length in feet[-inches].
#: Never a bare ratio, never "= 5.5'": that is how a code note's arithmetic
#: ("PTAC UNIT 3'-8" X 1'-6" = 5.5'") became a scale of 1:11.
_SCALE_RE = re.compile(
    rf"(?<![\d/.])(?:(?P<w>\d{{1,2}})\s+)?(?P<n>\d{{1,2}})(?:/(?P<d>\d{{1,3}}))?\s*[{_Q}]"
    rf"\s*=\s*(?P<ft>\d{{1,4}})\s*[{_F}]\s*(?:-?\s*(?P<inch>\d{{1,2}})\s*[{_Q}]?)?",
    re.I)

#: A note that says there is no scale.
_NTS_RE = re.compile(
    r"\bSCALE\s*:?\s*(?:N\.?\s*T\.?\s*S\.?|NONE|AS\s+(?:NOTED|INDICATED|SHOWN))"
    r"|\bN\.T\.S\.?|\bNTS\b|\bNOT\s+TO\s+SCALE\b", re.I)

#: A word that is a whole dimension and nothing else: 8'-0", 10'-4 1/2",
#: 36", 5'. Not an elevation (+60'-0", 33.37'), not a note.
_DIM_WORD_RE = re.compile(
    rf"^(?:\d{{1,3}}\s*[{_F}]\s*-?\s*\d{{1,2}}(?:\s+\d{{1,2}}/\d{{1,2}})?\s*[{_Q}]?"
    rf"|\d{{1,3}}(?:\s+\d{{1,2}}/\d{{1,2}})?\s*[{_Q}]"
    rf"|\d{{1,3}}\s*[{_F}])$")


# ── the scale note ─────────────────────────────────────────────────────────

def parse_scale_note(text: str) -> Optional[dict]:
    """{"pt_per_in": paper points per real inch, "ratio": real/paper,
    "text": the note} for the first scale note in `text`; {"nts": True, ...}
    when it says there is no scale; None when it is not a scale note."""
    text = text or ""
    for m in _SCALE_RE.finditer(text):
        n = Fraction(int(m.group("n")), int(m.group("d"))) if m.group("d") else Fraction(int(m.group("n")))
        paper = n + (int(m.group("w")) if m.group("w") else 0)
        real_in = int(m.group("ft")) * 12 + int(m.group("inch") or 0)
        if real_in <= 0 or paper <= 0:
            continue
        if m.group("w") and real_in == 12 and paper not in _STANDARD_PAPER_IN_PER_FT \
                and n in _STANDARD_PAPER_IN_PER_FT:
            paper = n                       # "5 3/16" = 1'-0"": bubble 5, scale 3/16"
        ratio = Fraction(real_in) / paper
        return {"pt_per_in": float(72 / ratio), "ratio": float(ratio),
                "text": m.group(0).strip(), "span": m.span(), "nts": False}
    m = _NTS_RE.search(text)
    if m:
        return {"pt_per_in": None, "ratio": None, "text": m.group(0).strip(),
                "span": m.span(), "nts": True}
    return None


@dataclass
class ScaleNote:
    text: str
    bbox: Tuple[float, float, float, float]
    pt_per_in: Optional[float]          # None: the note says not to scale
    ratio: Optional[float]
    nts: bool
    title: str = ""
    title_bbox: Optional[Tuple[float, float, float, float]] = None
    word_ids: Tuple[int, ...] = ()


def _union(boxes):
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def text_lines(boxes: Sequence[tuple]) -> List[dict]:
    """Left-to-right words joined into lines by position: the same baseline
    (centres within 40% of the height) and a gap under 1.5 heights."""
    idx = [i for i, b in enumerate(boxes) if b[5] == "ltr"]
    idx.sort(key=lambda i: boxes[i][1])          # left to right
    lines: List[List[int]] = []
    buckets: Dict[int, List[List[int]]] = {}     # baseline band -> lines
    for i in idx:
        t, x0, y0, x1, y1, _d = boxes[i]
        h, cy = y1 - y0, (y0 + y1) / 2
        best, key = None, int(cy // 4)
        for k in (key - 1, key, key + 1):
            for L in buckets.get(k, ()):
                _, a0, b0, a1, b1, _ = boxes[L[-1]]
                hh = max(h, b1 - b0)
                if abs((b0 + b1) / 2 - cy) <= 0.4 * hh and -0.5 * hh <= x0 - a1 <= 1.5 * hh:
                    best = L
                    break
            if best is not None:
                break
        if best is None:
            best = [i]
            lines.append(best)
            buckets.setdefault(key, []).append(best)
        else:
            best.append(i)
    out = []
    for L in lines:
        L.sort(key=lambda i: boxes[i][1])
        text, spans, pos = "", [], 0
        for i in L:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(boxes[i][0]), i))
            text += boxes[i][0]
        out.append({"text": text, "ids": L, "spans": spans,
                    "bbox": _union(boxes[i][1:5] for i in L)})
    return out


def find_scale_notes(boxes: Sequence[tuple], right_edge: float = math.inf) -> List[ScaleNote]:
    """Every scale note in the text layer left of `right_edge` (the title
    block), with the view title printed on the line above it."""
    lines = [L for L in text_lines(boxes) if L["bbox"][2] <= right_edge]
    notes = []
    for L in lines:
        p = parse_scale_note(L["text"])
        if not p:
            continue
        a, b = p["span"]
        ids = tuple(i for s, e, i in L["spans"] if s < b and e > a)
        bb = _union(boxes[i][1:5] for i in ids)
        h = bb[3] - bb[1]
        # the title: the nearest line above, overlapping the note across
        above = [M for M in lines if M is not L and M["bbox"][3] <= bb[1] + 0.25 * h
                 and M["bbox"][3] >= bb[1] - 3.0 * max(h, M["bbox"][3] - M["bbox"][1])
                 and M["bbox"][0] < bb[2] + 2 * h and M["bbox"][2] > bb[0] - 2 * h
                 and not parse_scale_note(M["text"])]
        title = max(above, key=lambda M: M["bbox"][3]) if above else None
        notes.append(ScaleNote(text=p["text"], bbox=bb, pt_per_in=p["pt_per_in"],
                               ratio=p["ratio"], nts=p["nts"],
                               title=title["text"] if title else "",
                               title_bbox=title["bbox"] if title else None,
                               word_ids=ids))
    return notes


# ── measuring one dimension ────────────────────────────────────────────────

def _segments(page) -> Tuple[np.ndarray, np.ndarray]:
    """(n x 4 array of x0, y0, x1, y1; n layer ids) for every straight piece."""
    segs, layers, names = [], [], {}
    for d in page.drawings:
        lid = names.setdefault(d["layer"], len(names))
        for it in d["items"]:
            if it[0] == "l":
                segs.append((it[1][0], it[1][1], it[2][0], it[2][1]))
                layers.append(lid)
    return (np.asarray(segs, dtype=float).reshape(-1, 4),
            np.asarray(layers, dtype=int))


@dataclass
class Dimension:
    text: str
    inches: float
    bbox: Tuple[float, float, float, float]
    measured_pt: Optional[float] = None
    why_not: str = ""

    @property
    def implied_pt_per_in(self) -> Optional[float]:
        return self.measured_pt / self.inches if self.measured_pt else None


def dimension_words(boxes: Sequence[tuple], skip: frozenset = frozenset()) -> List[Tuple[int, str, float]]:
    """(word index, text read the right way round, inches) for each word
    that is a whole dimension."""
    out = []
    for i, (t, *_rest) in enumerate(boxes):
        if i in skip:
            continue
        cand = t.strip()
        if not _DIM_WORD_RE.match(cand):
            un = pdim.unreverse(t)
            if un == t:
                continue
            cand = un.split("  ")[-1].strip()
            if not _DIM_WORD_RE.match(cand):
                continue
        f = pdim.find(cand)
        if len(f) != 1 or len(f[0].dims) != 1 or f[0].dims[0].unit != "in":
            continue
        inches = float(f[0].dims[0].value)
        if inches > 0:
            out.append((i, cand, inches))
    return out


def _axis_pieces(S: np.ndarray, horizontal: bool):
    """Indices of the pieces that run along the axis (within 0.1 degree)."""
    dx, dy = S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]
    along, across = (np.abs(dx), np.abs(dy)) if horizontal else (np.abs(dy), np.abs(dx))
    return np.nonzero((along > 1.0) & (across <= np.maximum(0.05, 0.002 * along)))[0]


def measure_dimension(box: tuple, S: np.ndarray, lay: np.ndarray,
                      pieces: Dict[bool, np.ndarray]) -> Tuple[Optional[float], str]:
    """The drawn length of the dimension whose text is `box`, in points, or
    (None, why).

    THE LINE. A dimension's text sits on its line: above it (most CAD), or
    in a gap the line breaks around (Revit). The line is a piece parallel to
    the text that runs past both ends of it, nearest the text's foot; or two
    collinear pieces that stop either side of the text.

    THE ENDS. Where the line's terminators cross it: ticks, arrow tips and
    extension lines on the line's own layer. The OUTERMOST on each side,
    within the line, or beyond its end when the stroke touches that end - an
    arrow's tip lies past the line, which stops at the arrow's base.
    """
    _t, x0, y0, x1, y1, d = box
    horiz = d in ("ltr", "rtl")
    if horiz:
        tlo, thi, plo, phi = x0, x1, y0, y1
        foot = y1 if d == "ltr" else y0
    else:
        tlo, thi, plo, phi = y0, y1, x0, x1
        foot = x1 if d == "btt" else x0
    h = phi - plo
    if h <= 0:
        return None, "no text height"
    mid = (plo + phi) / 2
    P = pieces[horiz]
    if not len(P):
        return None, "no line"
    seg = S[P]
    if horiz:
        lo, hi, c = np.minimum(seg[:, 0], seg[:, 2]), np.maximum(seg[:, 0], seg[:, 2]), (seg[:, 1] + seg[:, 3]) / 2
    else:
        lo, hi, c = np.minimum(seg[:, 1], seg[:, 3]), np.maximum(seg[:, 1], seg[:, 3]), (seg[:, 0] + seg[:, 2]) / 2
    near = np.nonzero((c >= plo - 0.6 * h) & (c <= phi + 0.6 * h) & (hi >= tlo - 2 * h) & (lo <= thi + 2 * h))[0]
    m = 0.25 * h
    cands = []                                   # (rank, lo, hi, c, layer)
    for k in near:
        if lo[k] <= tlo - m and hi[k] >= thi + m:
            off = abs(c[k] - foot)
            if off <= 0.6 * h:
                cands.append(((0, off), lo[k], hi[k], c[k], lay[P[k]]))
    for k in near:                               # broken around the text
        if not (tlo - h <= hi[k] <= tlo + m):
            continue
        for j in near:
            if j != k and lay[P[j]] == lay[P[k]] and abs(c[j] - c[k]) <= 0.3 \
                    and thi - m <= lo[j] <= thi + h and plo - 0.25 * h <= c[k] <= phi + 0.25 * h:
                cands.append(((1, abs(c[k] - mid)), lo[k], hi[j], (c[k] + c[j]) / 2, lay[P[k]]))
    if not cands:
        return None, "no dimension line"
    _r, L0, L1, cc, layer = min(cands, key=lambda z: z[0])
    # terminators: same-layer strokes that cross the line's axis
    on = S[lay == layer]
    if horiz:
        a_ax, b_ax, a_al, b_al = on[:, 1], on[:, 3], on[:, 0], on[:, 2]
    else:
        a_ax, b_ax, a_al, b_al = on[:, 0], on[:, 2], on[:, 1], on[:, 3]
    span = b_ax - a_ax
    cross = (np.minimum(a_ax, b_ax) <= cc + 1.0) & (np.maximum(a_ax, b_ax) >= cc - 1.0) & (np.abs(span) > 0.05)
    k = np.nonzero(cross)[0]
    if not len(k):
        return None, "no terminators"
    t = np.clip((cc - a_ax[k]) / span[k], 0.0, 1.0)
    pos = a_al[k] + t * (b_al[k] - a_al[k])
    inside = (pos >= L0 - 1.0) & (pos <= L1 + 1.0)
    beyond = ~inside & (pos >= L0 - h) & (pos <= L1 + h)
    if beyond.any():
        end = np.where(pos < L0, L0, L1)
        ex = (end, np.full_like(end, cc)) if horiz else (np.full_like(end, cc), end)
        da = np.hypot(on[k, 0] - ex[0], on[k, 1] - ex[1])
        db = np.hypot(on[k, 2] - ex[0], on[k, 3] - ex[1])
        beyond &= np.minimum(da, db) <= 1.5
    marks = pos[inside | beyond]
    centre = (tlo + thi) / 2
    left, right = marks[marks < centre], marks[marks > centre]
    if not len(left) or not len(right):
        return None, "terminator missing on one side"
    return float(right.max() - left.min()), ""


# ── the bodies of ink ──────────────────────────────────────────────────────

def _bodies(page, S: np.ndarray, boxes: Sequence[tuple], right_edge: float,
            clear: Sequence[Tuple[float, float, float, float]] = ()):
    """(label grid, n): every body of ink left of the title block, pieces
    within MERGE_GAP_PT joined. The sheet border is not ink, and neither is
    a title bar (`clear`): a bar sits between the drawing it labels and
    whatever is below, and as ink it would join the two."""
    from scipy import ndimage
    W, H = page.width, page.height
    nx, ny = int(math.ceil(W / CELL_PT)) + 1, int(math.ceil(H / CELL_PT)) + 1
    ink = np.zeros((ny, nx), dtype=bool)
    if len(S):
        dx, dy = S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]
        length = np.hypot(dx, dy)
        M = BORDER_MARGIN_PT
        xs_, ys_ = S[:, [0, 2]], S[:, [1, 3]]
        hugs_edge = ((ys_ <= M).all(1) | (ys_ >= H - M).all(1)
                     | (xs_ <= M).all(1) | (xs_ >= W - M).all(1))
        border = hugs_edge & (length >= 0.4 * min(W, H))
        S2, L2 = S[~border], length[~border]
        n = np.maximum(1, np.ceil(L2 / (CELL_PT * 0.75))).astype(int)
        cnt = n + 1
        rep = np.repeat(np.arange(len(S2)), cnt)
        starts = np.repeat(np.cumsum(cnt) - cnt, cnt)
        frac = (np.arange(int(cnt.sum())) - starts) / np.repeat(n, cnt)
        xs = S2[rep, 0] + frac * (S2[rep, 2] - S2[rep, 0])
        ys = S2[rep, 1] + frac * (S2[rep, 3] - S2[rep, 1])
        ok = (xs >= 0) & (xs < right_edge - 1.0) & (ys >= 0) & (ys < H)
        ink[(ys[ok] / CELL_PT).astype(int), (xs[ok] / CELL_PT).astype(int)] = True
    for _t, x0, y0, x1, y1, _d in boxes:
        if x1 >= right_edge - 1.0:
            continue
        ink[int(max(y0, 0) / CELL_PT):int(min(y1, H) / CELL_PT) + 1,
            int(max(x0, 0) / CELL_PT):int(min(x1, W) / CELL_PT) + 1] = True
    for x0, y0, x1, y1 in clear:
        ink[int(max(y0, 0) / CELL_PT):int(min(y1, H) / CELL_PT) + 1,
            int(max(x0, 0) / CELL_PT):int(min(x1, W) / CELL_PT) + 1] = False
    r = int(math.ceil(MERGE_GAP_PT / 2 / CELL_PT))
    grown = ndimage.binary_dilation(ink, structure=np.ones((2 * r + 1, 2 * r + 1), bool))
    lab, n = ndimage.label(grown, structure=np.ones((3, 3), bool))
    lab = np.where(ink, lab, 0)                  # a body is its ink, not its halo
    return lab, n


def _bbox_of(lab, n):
    from scipy import ndimage
    out = {}
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        ys, xs = sl
        out[i] = (xs.start * CELL_PT, ys.start * CELL_PT, xs.stop * CELL_PT, ys.stop * CELL_PT)
    return out


# ── viewports ──────────────────────────────────────────────────────────────

@dataclass
class Viewport:
    bbox: Tuple[float, float, float, float]          # the drawing and its title bar
    drawing_bbox: Tuple[float, float, float, float]
    title: str = ""
    note: Optional[ScaleNote] = None
    dimensions: List[Dimension] = field(default_factory=list)
    agreeing: int = 0
    verified: bool = False
    pt_per_in: Optional[float] = None                # set ONLY when verified or borrowed
    refusal: str = ""
    body: int = 0                                    # label of its ink in Sheet.labels
    #: set ONLY by `borrow`: where the scale came from. `verified` stays False
    #: - the drawing's own dimensions did not back a note - and a borrowed
    #: scale is never lent on (`borrow` lends only a viewport's own).
    borrowed: Optional[dict] = None

    @property
    def scale_text(self) -> str:
        return self.note.text if self.note else ""

    def real_inches(self, pt: float) -> float:
        """A paper length in points as real inches. Refuses a viewport with
        no verified and no borrowed scale by raising: there is no scale to
        use."""
        if not self.pt_per_in or not (self.verified or self.borrowed):
            raise ValueError(f"no verified scale for this viewport: {self.refusal}")
        return pt / self.pt_per_in


def verify(note: Optional[ScaleNote], dims: Sequence[Dimension]) -> Tuple[bool, int, str]:
    """(verified, agreeing, refusal) for a note against measured dimensions."""
    if note is None:
        return False, 0, "no scale note in the text layer inside this viewport"
    if note.nts or not note.pt_per_in:
        return False, 0, f"the note says there is no scale ({note.text})"
    measured = [d for d in dims if d.implied_pt_per_in]
    imp = [d.implied_pt_per_in for d in measured]
    agree = [d for d in measured if abs(d.implied_pt_per_in / note.pt_per_in - 1) <= AGREE_TOL]
    if len(agree) < MIN_AGREEING:
        return False, len(agree), (f"{len(agree)} of {len(imp)} measured dimensions agree with "
                                   f"{note.text} (need {MIN_AGREEING})")
    # Copies count, but not as different evidence: this viewport's OWN
    # agreeing dimensions must print at least MIN_DISTINCT different values.
    values = {round(d.inches * 16) for d in agree}      # to 1/16": 36" == 3'-0"
    if len(values) < MIN_DISTINCT:
        return False, len(agree), (f"{len(agree)} dimensions agree with {note.text} but all read "
                                   f"{agree[0].text}; {MIN_DISTINCT} different values needed")
    rival = 0
    for v in imp:
        if abs(v / note.pt_per_in - 1) <= 2 * AGREE_TOL:
            continue
        rival = max(rival, sum(1 for u in imp if abs(u / v - 1) <= AGREE_TOL))
    if rival > len(agree):
        return False, len(agree), (f"{rival} measured dimensions imply another scale, more than "
                                   f"the {len(agree)} that agree with {note.text}")
    return True, len(agree), ""


@dataclass
class Sheet:
    viewports: List[Viewport]
    labels: np.ndarray
    width: float
    height: float

    def at(self, x: float, y: float) -> Optional[Viewport]:
        """The viewport whose drawing holds (x, y): the ink there, or failing
        that the drawing whose box holds it. None outside every drawing - a
        point is never scaled by a neighbouring view."""
        i, j = int(y / CELL_PT), int(x / CELL_PT)
        if 0 <= i < self.labels.shape[0] and 0 <= j < self.labels.shape[1]:
            body = int(self.labels[i, j])
            for v in self.viewports:
                if body and v.body == body:
                    return v
        hits = [v for v in self.viewports
                if v.drawing_bbox[0] <= x <= v.drawing_bbox[2] and v.drawing_bbox[1] <= y <= v.drawing_bbox[3]]
        return hits[0] if len(hits) == 1 else None


def claimed_viewport(drawing_bbox, notes: Sequence[ScaleNote], dims: Sequence[Dimension],
                     body: int = 0) -> Viewport:
    """The viewport for one drawing and the title bars that claim it. Bars
    that print different scales refuse it: which note governs the drawing is
    the question that cannot be guessed. Bars that print the same scale (two
    views drawn close enough to join) give one viewport at that scale."""
    bars = [_union([x.bbox] + ([x.title_bbox] if x.title_bbox else [])) for x in notes]
    vbox = _union([drawing_bbox] + bars)
    title = " / ".join(x.title for x in notes)
    distinct = {round(x.pt_per_in, 6) if x.pt_per_in else None for x in notes}
    if len(distinct) > 1:
        return Viewport(bbox=vbox, drawing_bbox=drawing_bbox, title=title, note=notes[0],
                        dimensions=list(dims), body=body,
                        refusal="claimed by title bars with different scales: "
                        + "; ".join(x.text for x in notes))
    ok, agree, why = verify(notes[0], dims)
    return Viewport(bbox=vbox, drawing_bbox=drawing_bbox, title=title, note=notes[0],
                    dimensions=list(dims), agreeing=agree, verified=ok,
                    pt_per_in=notes[0].pt_per_in if ok else None, refusal=why, body=body)


def bar_zone(nt: ScaleNote) -> Tuple[float, float, float, float]:
    """The title bar around a note: the note, its title, the underline
    between them and the numbered bubble at their left."""
    boxes = [nt.bbox] + ([nt.title_bbox] if nt.title_bbox else [])
    x0, y0, x1, y1 = _union(boxes)
    h = max(b[3] - b[1] for b in boxes)
    return (x0 - 3.0 * h, y0 - 0.75 * h, x1 + 0.5 * h, y1 + 0.75 * h)


def read_sheet(page) -> Sheet:
    """Every viewport on a PlanPage, each with its note, its measured
    dimensions, and a verified scale or the reason there is none."""
    S, lay = _segments(page)
    boxes = page.directed_word_boxes
    segs_list = [tuple(r) for r in S]
    right = title_block_edge(segs_list, page.width, page.height) if len(S) else page.width
    notes = find_scale_notes(boxes, right_edge=right)
    note_words = frozenset(i for n in notes for i in n.word_ids)
    zones = {id(nt): bar_zone(nt) for nt in notes}
    lab, n = _bodies(page, S, boxes, right, clear=list(zones.values()))
    bb = _bbox_of(lab, n)

    def body_at(x, y):
        i, j = int(y / CELL_PT), int(x / CELL_PT)
        if 0 <= i < lab.shape[0] and 0 <= j < lab.shape[1]:
            return int(lab[i, j])
        return 0

    def body_of_box(b):
        votes = Counter()
        for yy in np.arange(b[1], b[3] + 0.1, CELL_PT):
            for xx in np.arange(b[0], b[2] + 0.1, CELL_PT):
                k = body_at(xx, yy)
                if k:
                    votes[k] += 1
        return votes.most_common(1)[0][0] if votes else 0

    def drawing_sized(k):
        x0, y0, x1, y1 = bb[k]
        return x1 - x0 >= DRAWING_MIN_PT and y1 - y0 >= DRAWING_MIN_PT

    # Which drawing each title bar labels: the first drawing-sized body met
    # going straight UP from the bar, across the bar's width. Never sideways
    # and never down, and never by distance to a note.
    claims: Dict[int, List[ScaleNote]] = {}
    unclaimed_notes: List[ScaleNote] = []
    for nt in notes:
        z = zones[id(nt)]
        j0, j1 = max(int(z[0] / CELL_PT), 0), min(int(z[2] / CELL_PT) + 1, lab.shape[1])
        target = 0
        for i in range(min(int(z[1] / CELL_PT), lab.shape[0]) - 1, -1, -1):
            row = Counter(int(k) for k in lab[i, j0:j1] if k and drawing_sized(int(k)))
            if row:
                target = row.most_common(1)[0][0]
                break
        if target:
            claims.setdefault(target, []).append(nt)
        else:
            unclaimed_notes.append(nt)

    dims_all = dimension_words(boxes, skip=note_words)
    pieces = {True: _axis_pieces(S, True), False: _axis_pieces(S, False)} if len(S) else {True: np.zeros(0, int), False: np.zeros(0, int)}
    by_body: Dict[int, List[Dimension]] = {}
    measured_cache = {}
    for i, text, inches in dims_all:
        b = boxes[i]
        k = body_of_box(b[1:5])
        if not k:
            continue
        by_body.setdefault(k, [])
        if i not in measured_cache:
            measured_cache[i] = measure_dimension(b, S, lay, pieces) if len(S) else (None, "no linework")
        mpt, why = measured_cache[i]
        by_body[k].append(Dimension(text=text, inches=inches, bbox=b[1:5], measured_pt=mpt, why_not=why))

    vps: List[Viewport] = []
    for k, nts in claims.items():
        vps.append(claimed_viewport(bb[k], nts, by_body.get(k, []), body=k))
    claimed = set(claims)
    for k in sorted(bb):
        if k in claimed or not drawing_sized(k):
            continue
        vps.append(Viewport(bbox=bb[k], drawing_bbox=bb[k], dimensions=by_body.get(k, []),
                            refusal="no title bar with a scale note in the text layer labels this drawing",
                            body=k))
    for nt in unclaimed_notes:
        vps.append(Viewport(bbox=_union([nt.bbox] + ([nt.title_bbox] if nt.title_bbox else [])),
                            drawing_bbox=nt.bbox, title=nt.title, note=nt,
                            refusal="no drawing found above this title bar"))
    vps.sort(key=lambda v: (v.bbox[1], v.bbox[0]))
    return Sheet(viewports=vps, labels=lab, width=page.width, height=page.height)


# ── a borrowed scale (Roy, ruling 5, 2026-10-28) ─────────────────────────
#
# "M/P borrow the A sheet's verified scale only when registration to it is
# usable." The M and P plans of 588 Boyland carry the architectural plan as
# a screened underlay and print almost no dimension of their own (M-100 to
# M-106: 0 to 6 measured, none agreeing), so their own note never verifies.
# A registration is a TRANSLATION ONLY (plan_registration: the underlay is
# the same drawing placed twice), so hundreds of corners matching within an
# inch after a pure shift ARE the evidence that the two sheets share a paper
# scale - the scale the architectural viewport's own dimensions verified.
#
# What makes it a borrow and not an assumption, each a condition that fails:
#   1. only M or P borrows, and only from A (sheet numbers);
#   2. the registration is USABLE BY THE ONE OFFSET RULE (Roy, ruling 63:
#      "one function, T3's rule (single best peak agreeing with the exact
#      1pt search, >=8 anchors) for all pairs, with each pair's margin shown
#      on its row"): plan_sheet.register_offset - R1 the offset is within one
#      match radius of the exact census' best peak, R2 no second peak ties
#      it, R3 >= MIN_ANCHORS. A registration that register_offset did not
#      judge (no census peaks on it) lends nothing. The roof's old wrong
#      peak (108 of 239, 32pt from the best) and M-106 on A-105.01 (9pt from
#      its best peak) are refused by R1. Its margin rides in the provenance;
#   3. the lender viewport VERIFIED ON ITS OWN DIMENSIONS - never a borrowed
#      scale, never an unverified one (A-105.x's 3/32" BULKHEAD PLAN);
#   4. more than half of the matched anchors join ONE lender viewport to ONE
#      viewport of the borrower: that is the drawing that borrows;
#   5. the shift bounds the scale: two anchors D apart that both match within
#      r after a pure shift differ in scale by at most 2r/D. That bound, over
#      the anchors of the joined views, must be inside AGREE_TOL;
#   6. a note the borrower prints in its text layer must agree with the
#      lent scale (a contradiction refuses), and a note that says there is
#      no scale refuses. A borrower with no note in its text layer (the P
#      sheets' SHX title bars) borrows: that is the case the ruling is for.
# A borrower viewport that verified on its own keeps its own scale.

BORROWERS = ("M", "P")
LENDERS = ("A",)


def _discipline(sheet_number: str) -> str:
    m = re.match(r"^\s*([A-Z]+)[-.]", (sheet_number or "").upper())
    return m.group(1) if m else ""


def _vp_brief(v: Optional[Viewport]) -> Optional[dict]:
    if v is None:
        return None
    return {"title": v.title, "note": v.scale_text, "verified": v.verified,
            "agreeing": v.agreeing, "pt_per_in": v.pt_per_in}


def borrow(borrower_number: str, borrower: Sheet, lender_number: str, lender: Sheet,
           registration: dict, lender_pts, borrower_pts) -> Tuple[Optional[Viewport], dict]:
    """(the borrower's scaled viewport or None, the scale result).

    `registration` is plan_sheet.register_offset(lender's sheet, borrower's
    sheet) - the one offset rule (ruling 63);
    `lender_pts` / `borrower_pts` are its matched anchors, pairwise
    (plan_sheet.matched_anchors). The result always names the sheet, the
    status - "own" | "borrowed" | "refused" - and why not, and for a borrow
    the provenance: the lender's sheet and viewport and the registration's
    evidence. The rules are the block above, in order."""
    from lib.plan_registration import ANCHOR_MATCH_RADIUS_IN
    reg_keys = ("dx", "dy", "anchors", "best_peak_anchors", "best_peak",
                "second_peak_anchors", "second_peak", "margin", "offset_from_best_pt",
                "rms_in", "max_in", "sweep", "usable", "refused")
    out: Dict[str, object] = {
        "sheet": borrower_number, "status": "refused", "pt_per_in": None, "viewport": None,
        "from": {"sheet": lender_number, "viewport": None},
        "registration": {k: registration.get(k) for k in reg_keys}, "why": ""}

    def refuse(why):
        out["why"] = why
        return None, out

    # 1
    if _discipline(borrower_number) not in BORROWERS or _discipline(lender_number) not in LENDERS:
        return refuse(f"only {'/'.join(BORROWERS)} sheets borrow, and only from "
                      f"{'/'.join(LENDERS)}: {borrower_number} from {lender_number}")
    # 2
    if "offset_from_best_pt" not in registration or "second_peak_anchors" not in registration:
        return refuse(f"the registration to {lender_number} was not judged by the one offset "
                      f"rule (plan_sheet.register_offset): no exact-census peaks on it")
    if not registration.get("usable"):
        return refuse(f"the registration to {lender_number} is not usable: "
                      f"{registration.get('refused') or 'refused'}")
    A = np.asarray(lender_pts, dtype=float).reshape(-1, 2)
    B = np.asarray(borrower_pts, dtype=float).reshape(-1, 2)
    if not len(A) or len(A) != len(B):
        return refuse("no matched anchors to place the borrow")
    # 4: which drawing joins which
    keys = []
    vps = {}
    for (ax, ay), (bx, by) in zip(A, B):
        va, vb = lender.at(float(ax), float(ay)), borrower.at(float(bx), float(by))
        if va is None or vb is None:
            keys.append(None)
            continue
        vps[id(va)], vps[id(vb)] = va, vb
        keys.append((id(va), id(vb)))
    pairs = Counter(k for k in keys if k is not None)
    if not pairs:
        return refuse("no matched anchor lies in a drawing on both sheets")
    (ka, kb), n = pairs.most_common(1)[0]
    va, vb = vps[ka], vps[kb]
    out["viewport"] = _vp_brief(vb)
    out["from"] = {"sheet": lender_number, "viewport": _vp_brief(va)}
    out["anchors_in_view"], out["anchors_matched"] = n, len(A)
    if 2 * n <= len(A):
        return refuse(f"the matched anchors do not join one drawing to one: the most, {n} of "
                      f"{len(A)}, join {va.title or 'an untitled view'} to "
                      f"{vb.title or 'an untitled view'}")
    if vb.verified:
        out.update(status="own", pt_per_in=vb.pt_per_in)
        return vb, out
    # 3
    if not va.verified or va.borrowed or not va.pt_per_in:
        return refuse(f"{lender_number}'s {va.title or 'untitled view'} has no scale of its own "
                      f"to lend: {va.refusal or 'its scale is borrowed'}")
    # 5
    sel = np.array([k == (ka, kb) for k in keys])
    a_in, b_in = A[sel], B[sel]
    shift = np.array([registration.get("dx", 0.0), registration.get("dy", 0.0)], dtype=float)
    r_pt = max(float(np.hypot(*(b_in - (a_in + shift)).T).max()), 1e-9)
    span = float((a_in.max(0) - a_in.min(0)).max())
    bound = 2 * r_pt / span if span else math.inf
    out["scale_bound"] = round(bound, 5)
    if bound > AGREE_TOL:
        return refuse(f"the shift bounds the scale only to {bound:.1%} (worst anchor "
                      f"{r_pt:.2f}pt over {span:.0f}pt); {AGREE_TOL:.0%} needed")
    # 6
    if vb.note is not None:
        if vb.note.nts or not vb.note.pt_per_in:
            return refuse(f"{borrower_number}'s view says it has no scale ({vb.note.text})")
        if vb.note.pt_per_in and abs(vb.note.pt_per_in / va.pt_per_in - 1) > AGREE_TOL:
            return refuse(f"{borrower_number} prints {vb.note.text}; {lender_number}'s "
                          f"{va.title or 'view'} verifies {va.scale_text}: they contradict")
    prov = {"sheet": lender_number, "viewport": va.title, "note": va.scale_text,
            "agreeing": va.agreeing, "anchors_in_view": n, "anchors_matched": len(A),
            "margin": registration.get("margin"),
            "scale_bound": out["scale_bound"], "match_radius_in": ANCHOR_MATCH_RADIUS_IN,
            "registration": out["registration"]}
    lent = replace(vb, pt_per_in=va.pt_per_in, borrowed=prov)
    out.update(status="borrowed", pt_per_in=va.pt_per_in)
    return lent, out


__all__ = ["BORROWERS", "LENDERS", "borrow", "AGREE_TOL", "MIN_AGREEING", "MIN_DISTINCT", "ScaleNote", "Dimension", "Viewport", "Sheet",
           "parse_scale_note", "find_scale_notes", "text_lines", "dimension_words",
           "measure_dimension", "verify", "claimed_viewport", "read_sheet"]
