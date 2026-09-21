"""Find equipment symbols on a drawing and name them from its own schedule.

    schedule tag  ->  printed label  ->  glyph  ->  every instance

Nothing in that chain is a person pointing at a symbol, and nothing is a
model's impression of a picture. The schedule supplies a CLOSED SET of tags;
OCR anchored on a candidate symbol reads the label beside it; the read snaps
to the closed set or fails; the glyph standing next to a successful read
becomes the template; the template finds the rest, including instances whose
own label is unreadable.

── WHY THE CLOSED SET IS THE ERROR CORRECTION ─────────────────────────────

OCR on stroked drawing text is not clean. Measured on M-103.00: `FF-1(50)`,
`EF|1(50)`, `EF=2(100)`. A free-text reader has to believe those. A reader
holding the sheet's own schedule knows only EF-1 and EF-2 exist, so the
first two resolve and `EF-7` resolves to NOTHING rather than being absorbed
into EF-1 — which is what the first version did, at edit distance 1, before
a known-answer test caught it.

So the digit is matched EXACTLY and only the prefix is corrected. One
substitution in the digit is ambiguous between a slip and a different tag;
one in the prefix is not, because no `EP` family exists in the schedule.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lib.plan_records import column_role

#: A symbol is the corners within this of its centre.
SYMBOL_RADIUS_IN = 14.0
#: Fewer corners than this is linework, not a symbol.
SYMBOL_MIN_CORNERS = 12
#: Two detections closer than this are one glyph.
SYMBOL_NMS_IN = 24.0
#: A template corner counts as present within this of where it should be.
TEMPLATE_MATCH_TOL_IN = 1.5
#: Fraction of a template's corners that must appear for a detection.
TEMPLATE_MIN_SCORE = 0.70

#: Columns whose value can corroborate a tag read. A schedule that has none
#: is not a failure: the snap then stands on the tag alone and the record
#: says so. PTAC's schedule has no rating column at all.
_CORROBORATING_HEADERS = re.compile(
    r"^(cfm|capacity|kw|btuh?|mbh|tons?|gpm|hp|amps?|watts?)\b", re.I)


def corroborating_role(header: str) -> Optional[str]:
    """`rating` when a column's printed header names a quantity that can
    stand beside a tag in a label, else None. Named ONCE, here, so callers
    do not each invent their own idea of which column corroborates."""
    h = re.sub(r"\s+", " ", (header or "").strip())
    return "rating" if _CORROBORATING_HEADERS.match(h) else None


def closed_set_from_schedule(headers: Sequence[str],
                             rows: Sequence[Sequence[str]],
                             prefix: Optional[str] = None):
    """(tags, corroborations) from one schedule's headers and rows.

    `tags` is the ordered closed set taken from the column whose printed
    header is an identifier — `column_role` already names that, and nothing
    is inferred from the cells: a column of codes is not a tag column unless
    its header says so.

    `corroborations` maps tag -> the rating value, when a rating column
    exists. Empty when the schedule has none, which is a supported outcome
    and not a degraded one.
    """
    # THE PIPELINE ALREADY NAMED THESE COLUMNS. A stored schedule's
    # `payload["columns"]` is [{"header": ..., "role": ...}], with the role
    # computed by `column_role` at extraction. Re-deriving it here would be a
    # second definition of the same judgement, free to drift from the one in
    # the record; so a stored role wins and `column_role` is only consulted
    # when a caller passes bare header strings.
    cols = [(h.get("header", ""), h.get("role")) if isinstance(h, dict)
            else (h, None) for h in headers]
    roles = [r if r is not None else column_role(h) for h, r in cols]
    rates = [corroborating_role(h) for h, _r in cols]
    try:
        tag_col = roles.index("identifier")
    except ValueError:
        return [], {}
    rate_col = rates.index("rating") if "rating" in rates else None
    tags: List[str] = []
    corr: Dict[str, str] = {}
    for row in rows:
        if tag_col >= len(row):
            continue
        tag = str(row[tag_col] or "").strip().upper()
        if not tag or (prefix and not tag.startswith(prefix.upper())):
            continue
        if tag not in tags:
            tags.append(tag)
        if rate_col is not None and rate_col < len(row):
            v = str(row[rate_col] or "").strip()
            if v:
                corr.setdefault(tag, v)
    return tags, corr


def normalise(s: str) -> str:
    """OCR confusions that matter when the answer must be in a closed set.

    SPACES ARE KEPT. Stripping them glued tokens together — `40 EF-1(50)`
    became `40EF-1(50)` and the boundary then rejected a good label because
    a digit sat against the prefix.

    `|` IS NOT MAPPED TO A DIGIT. It appears in the real read `EF|1(50)`
    standing in for a HYPHEN; mapping it to `1` produced `EF11` and the
    token was thrown out for a double digit. The separator class absorbs it
    instead, which requires no guess about which character it was.
    """
    s = s.upper()
    s = s.replace("I", "1").replace("L", "1")
    s = s.replace("O", "0").replace("–", "-").replace("—", "-")
    return s


#: A TAG IS A WHOLE TOKEN. Without the boundaries this matched inside prose:
#: `REFRIGERANT` normalises to `EFR1GERANT`, whose `EFR`+`1` is one edit from
#: EF-1, and three note fragments on M-103.00 snapped to a schedule tag.
_TAGLIKE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{1,4})\s*[-|/]?\s*([0-9]{1,2})(?![A-Z0-9])")


def _edit(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def snap(text: str, closed_set: Sequence[str],
         max_prefix_edits: int = 1) -> Tuple[Optional[str], Optional[int]]:
    """(tag, prefix_edits) for a tag in `closed_set`, else (None, None).

    The digit is matched exactly; only the prefix is corrected.
    """
    t = normalise(text)
    wanted = {tag.upper().replace("-", ""): tag for tag in closed_set}
    best: Tuple[Optional[str], Optional[int]] = (None, None)
    for m in _TAGLIKE.finditer(t):
        prefix, digits = m.group(1), m.group(2)
        for key, tag in wanted.items():
            head = key.rstrip("0123456789")
            tail = key[len(head):]
            if tail != digits:
                continue
            d = _edit(prefix, head)
            if d <= max_prefix_edits and (best[1] is None or d < best[1]):
                best = (tag, d)
    return best


def corroborated_tag(texts: Iterable[str],
                     corroborations: Dict[str, str]) -> Optional[str]:
    """The tag implied by a rating appearing in the read, if unambiguous.

    THE RATING IS PART OF THE SAME PRINTED LABEL. `EF-2(100)` carries the tag
    and the rating; reading either is reading the label. Requiring the tag
    token and discarding a resolved rating left a fan unread over a hyphen
    misread as `=`, with `(100)` sitting there unambiguous.
    """
    if not corroborations:
        return None
    blob = " ".join(normalise(t) for t in texts)
    hits = {tag for tag, val in corroborations.items()
            if val and re.search(rf"(?<![0-9]){re.escape(normalise(val))}"
                                 rf"(?![0-9])", blob)}
    return hits.pop() if len(hits) == 1 else None


def labels_in(reads: Iterable[Tuple[str, float, float]],
              closed_set: Sequence[str],
              merge_pt: float = 30.0):
    """[(tag, x, y)] where a read snaps to a schedule tag, deduplicated.

    `reads` is (text, x, y) from any OCR pass over the sheet.
    """
    out: List[Tuple[str, float, float]] = []
    for text, x, y in reads:
        tag, _d = snap(text, closed_set)
        if not tag:
            continue
        if any(t == tag and abs(x - px) <= merge_pt and abs(y - py) <= merge_pt
               for t, px, py in out):
            continue
        out.append((tag, float(x), float(y)))
    return out


def symbol_at_label(label_xy: Tuple[float, float],
                    points, search_pt: float, symbol_pt: float,
                    min_points: int = 3):
    """((x, y), n) for the geometry standing beside a label, or (None, 0).

    LABEL-ANCHORED, NOT DENSITY-ANCHORED, AND THAT IS THE WHOLE POINT.

    `candidate_symbols` below finds symbols by corner density, which silently
    assumes a corner-rich glyph. Measured: the EF fan carries 29 corners
    within 14in; a PTAC unit is a plain rectangle at the wall with 6 corners
    within 60in. No density threshold finds both — PTAC cannot pass "12
    corners in 14in" at any radius, because it does not have 12 corners.

    Anchoring on the label removes the assumption entirely. The sheet says
    where its equipment is by printing a tag beside it, so the geometry
    nearest that tag IS the symbol, whether it has four corners or forty.

    The cluster is grown from the point NEAREST the label rather than from
    the label itself, so a tag printed a few feet from its symbol still
    lands on the symbol instead of on the midpoint between them.

    PASS ALL OF THE SHEET'S GEOMETRY, NOT A "MECHANICAL ONLY" SUBSET.
    Filtering to points with no counterpart on the registered architectural
    sheet is a scaffold for density search and it is WRONG here: measured on
    M-103.00, the four PTAC units down one side survive that filter with 6
    corners each and the four down the other do not survive it at all,
    because their rectangles coincide with architectural window and wall
    linework. The filter quietly deletes exactly the equipment that is drawn
    over something. A label does not need the filter — it already says which
    geometry is the equipment.
    """
    lx, ly = float(label_xy[0]), float(label_xy[1])
    near = [(float(p[0]), float(p[1])) for p in points
            if abs(float(p[0]) - lx) <= search_pt
            and abs(float(p[1]) - ly) <= search_pt]
    if len(near) < min_points:
        return None, len(near)
    seed = min(near, key=lambda p: (p[0] - lx) ** 2 + (p[1] - ly) ** 2)
    cluster = [p for p in near
               if (p[0] - seed[0]) ** 2 + (p[1] - seed[1]) ** 2
               <= symbol_pt ** 2]
    if len(cluster) < min_points:
        return None, len(cluster)
    cx = sum(p[0] for p in cluster) / len(cluster)
    cy = sum(p[1] for p in cluster) / len(cluster)
    return (cx, cy), len(cluster)


def dedup(detections: Sequence[Tuple[float, object, str]],
          nms_pt: float):
    """(kept, dropped) over ALL templates' detections, best score first.

    Suppression used to run WITHIN each template, so a second template
    redetected the first's glyphs 12.5in away and a union counted each object
    twice. Pooling and sorting by score makes the better-matching template
    win a contested location by construction.
    """
    kept: List[Tuple[float, object, str]] = []
    dropped: List[Tuple[float, object, str, str, float]] = []
    for score, p, lab in sorted(detections, key=lambda d: -d[0]):
        clash = None
        for k in kept:
            dx = float(p[0]) - float(k[1][0])
            dy = float(p[1]) - float(k[1][1])
            if (dx * dx + dy * dy) ** 0.5 <= nms_pt:
                clash = k
                break
        if clash is None:
            kept.append((score, p, lab))
        else:
            dx = float(p[0]) - float(clash[1][0])
            dy = float(p[1]) - float(clash[1][1])
            dropped.append((score, p, lab, clash[2], (dx * dx + dy * dy) ** 0.5))
    return kept, dropped


__all__ = [
    "SYMBOL_RADIUS_IN", "SYMBOL_MIN_CORNERS", "SYMBOL_NMS_IN",
    "TEMPLATE_MATCH_TOL_IN", "TEMPLATE_MIN_SCORE",
    "corroborating_role", "closed_set_from_schedule",
    "normalise", "snap", "corroborated_tag", "dedup",
    "labels_in", "symbol_at_label",
]
