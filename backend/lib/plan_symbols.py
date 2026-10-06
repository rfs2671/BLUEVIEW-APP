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
from collections import Counter
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
#: A point this close outside a label's text box is still the label's glyph.
LABEL_BOX_PAD_IN = 1.0
#: Two objects this close are one object (drawn as separate paths, touching).
LINK_IN = 0.5
#: Candidate objects whose distance to the label differs by less than this are
#: a tie, and the tie is broken on the drawing pass (colour).
TIE_IN = 3.0
#: Smaller than this in both directions is dust - a hatch fragment, a stroke
#: end - not a piece of equipment. The smallest symbol on these sheets is the
#: exhaust fan at 15in; the fragments that beat it to the label were 0.4in.
MIN_SYMBOL_IN = 6.0

#: NCS equipment layers: M-EQPM, M-HVAC-EQPM, xref-prefixed, any case.
_EQUIPMENT_LAYER = re.compile(r"(?i)(?:^|\|)M-(?:[A-Z0-9]+-)*EQPM(?:-[A-Z0-9]+)*$")
#: Annotation: text, tags, dimensions, notes - M-EQPM-IDEN is the equipment's
#: TAGS, so a text modifier wins over the equipment major group.
_TEXT_LAYER = re.compile(
    r"(?i)(?:^|[-|\s])(?:TEXT|TXT|ANNO|IDEN|NOTE|NOTES|DIM|DIMS|TAG|TAGS)(?:-|$)")


def is_text_layer(name: Optional[str]) -> bool:
    return bool(name) and bool(_TEXT_LAYER.search(name))


def is_equipment_layer(name: Optional[str]) -> bool:
    return (bool(name) and not is_text_layer(name)
            and bool(_EQUIPMENT_LAYER.search(name)))

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


def _printed_rating(texts: Iterable[str],
                    corroborations: Dict[str, str]) -> Optional[str]:
    """The tag whose rating appears in the LABEL'S OWN FORM, `(value)`.

    Not anywhere a number appears: `100'-0" LOT` carries a 100.
    """
    blob = " ".join(normalise(t) for t in texts)
    hits = {tag for tag, val in corroborations.items()
            if val and re.search(rf"\(\s*{re.escape(normalise(val))}"
                                 rf"(?![0-9])", blob)}
    return hits.pop() if len(hits) == 1 else None


def labels_in(reads: Iterable[Tuple[str, float, float]],
              closed_set: Sequence[str],
              merge_pt: float = 30.0,
              corroborations: Optional[Dict[str, str]] = None):
    """[(tag, x, y)] where a read snaps to a schedule tag, deduplicated.

    `reads` is (text, x, y) from any OCR pass over the sheet.

    WITH A RATING COLUMN, A NEAR MISS NEEDS THE LABEL'S OWN RATING. On
    M-103.00 the note "2 HOUR FIRE RATED ENCLOSURE" read as `F2 HOUR FIRE`,
    one prefix edit from EF-2, and counted as a fan; 4A's real kitchen fan
    read as `EF=2(1` + `2(100)`, snapped to nothing, and did not. The total
    was 8 either way - only the per-unit split showed it. So: an exact snap
    stands on the tag; a snap needing a prefix edit stands only if the reads
    within `merge_pt` print the same tag's rating as `(value)`; a read that
    snaps to nothing but itself prints a rating naming one tag is that tag.
    No rating column (PTAC) - nothing to corroborate with, nothing changes.
    """
    reads = list(reads)
    corr = corroborations or {}
    out: List[Tuple[str, float, float]] = []
    for text, x, y in reads:
        tag, d = snap(text, closed_set)
        if corr:
            if tag and d:
                near = [t for t, px, py in reads
                        if abs(x - px) <= merge_pt and abs(y - py) <= merge_pt]
                if _printed_rating(near, corr) != tag:
                    tag = None
            elif not tag:
                tag = _printed_rating([text], corr)
        if not tag:
            continue
        if any(t == tag and abs(x - px) <= merge_pt and abs(y - py) <= merge_pt
               for t, px, py in out):
            continue
        out.append((tag, float(x), float(y)))
    return out


def _obj(o):
    """(points, layer, colour) from an object given as a mapping or a tuple."""
    if isinstance(o, dict):
        return list(o.get("points") or ()), o.get("layer"), o.get("colour")
    pts = list(o[0])
    return pts, (o[1] if len(o) > 1 else None), (o[2] if len(o) > 2 else None)


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _gap(a, b):
    """Distance between two bounding boxes, 0 when they overlap."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _crosses(p1, p2, p3, p4):
    d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0])
    if abs(d) < 1e-12:
        return False
    t = ((p3[0] - p1[0]) * (p4[1] - p3[1])
         - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
    u = ((p3[0] - p1[0]) * (p2[1] - p1[1])
         - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
    return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0


def _touches(a, b, tol):
    """Two polylines touch: a vertex within `tol`, or segments crossing."""
    for x1, y1 in a:
        for x2, y2 in b:
            if abs(x1 - x2) <= tol and abs(y1 - y2) <= tol:
                return True
    for i in range(len(a) - 1):
        for k in range(len(b) - 1):
            if _crosses(a[i], a[i + 1], b[k], b[k + 1]):
                return True
    return False


def symbol_at_label(label_xy: Tuple[float, float],
                    objects, search_pt: float, symbol_pt: float,
                    min_points: int = 3,
                    label_boxes: Sequence[Tuple[float, float, float, float]] = (),
                    pad_pt: Optional[float] = None,
                    link_pt: Optional[float] = None,
                    tie_pt: Optional[float] = None,
                    same_pass: bool = False,
                    prefer_pass: bool = False,
                    min_symbol_pt: Optional[float] = None,
                    report: Optional[dict] = None):
    """((x, y), n) for the OBJECT standing beside a label, or (None, 0).

    LABEL-ANCHORED, NOT DENSITY-ANCHORED, AND THAT IS THE WHOLE POINT.

    `candidate_symbols` below finds symbols by corner density, which silently
    assumes a corner-rich glyph. Measured: the EF fan carries 29 corners
    within 14in; a PTAC unit is a plain rectangle at the wall with 6 corners
    within 60in. No density threshold finds both. Anchoring on the label
    removes the assumption: the sheet says where its equipment is by printing
    a tag beside it.

    A SYMBOL IS ONE CONNECTED OBJECT, NOT AN AVERAGE OF WHAT IS AROUND IT.
    This used to return the centroid of every corner within `symbol_pt` of
    the point nearest the label - the fan, its duct, the counter under it and
    the architectural background in one number. Measured on the Boyland set:
    A-100.01's EF-2(100) came back ON ITS OWN LABEL (143 corners averaged),
    and each PTAC came back at the middle of whatever surrounded it. So:

      - the SEED is the geometry nearest the label that is not the label:
        never inside `label_boxes` (the tag is drawn as outlines on these
        sheets, so its own glyphs are the nearest geometry there is), and
        never on a text/annotation layer;
      - the SYMBOL is the seed's object grown through geometry it TOUCHES -
        a vertex within `link_pt`, or segments crossing - out to `symbol_pt`
        from the seed, so a fan drawn as nested paths is one symbol and the
        counter it hangs over is not;
      - an object smaller than `min_symbol_pt`, or with fewer than
        `min_points` vertices, is DUST - a hatch fragment, a stroke end, a
        rule under a note - and the next candidate out is taken instead;
      - geometry longer than `symbol_pt` in either direction is STRUCTURE,
        never a symbol and never part of one: a wall line or a duct run
        crosses the whole sheet, and one of them touching the seed dragged
        the answer 400in away;
      - the POSITION is the centre of that object's bounding box: a point ON
        the object, not the mean of its parts;
      - when any object carries an NCS equipment layer (M-EQPM,
        M-HVAC-EQPM), only equipment-layer objects can be the symbol.

    THE DRAWING PASS BREAKS TIES, AND ONLY TIES. Where candidates sit within
    `tie_pt` of each other at the label, the one drawn in the same colour as
    the label's own glyphs wins: the mechanical work and its tags are one
    pass over an architectural background drawn in another. It decides
    nothing on its own - a clearly nearer object of any colour still wins.

    `objects` are {"points", "layer", "colour"} or (points, layer, colour),
    `points` being a path's vertices in order. `report`, when given, is
    filled with what was chosen and whether the tie-break fired.
    """
    lx, ly = float(label_xy[0]), float(label_xy[1])
    pad = LABEL_BOX_PAD_IN * 1.5 if pad_pt is None else float(pad_pt)
    link = LINK_IN * 1.5 if link_pt is None else float(link_pt)
    tie = TIE_IN * 1.5 if tie_pt is None else float(tie_pt)
    min_symbol = MIN_SYMBOL_IN * 1.5 if min_symbol_pt is None else float(min_symbol_pt)
    boxes = [(min(b[0], b[2]) - pad, min(b[1], b[3]) - pad,
              max(b[0], b[2]) + pad, max(b[1], b[3]) + pad)
             for b in label_boxes]

    def in_label(x, y):
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in boxes)

    near, label_colours = [], []
    for o in objects:
        pts, layer, colour = _obj(o)
        if not pts:
            continue
        if any(in_label(x, y) for x, y in pts):
            # ONLY GLYPHS, NOT WHAT CROSSES THE BOX. A hatched wall running
            # through the tag put 169,169,169 in the majority and the
            # tie-break then preferred the hatch over the equipment.
            if all(in_label(x, y) for x, y in pts):
                label_colours.append(colour)
            continue
        if is_text_layer(layer):
            continue
        if not any(abs(x - lx) <= search_pt and abs(y - ly) <= search_pt
                   for x, y in pts):
            continue
        box = _bbox(pts)
        # LONGER THAN ANY SYMBOL IS STRUCTURE, NOT SYMBOL. A wall line, a
        # duct run or a match line crosses the whole sheet; one of them
        # touching the seed made "the object beside the label" 400in wide.
        if max(box[2] - box[0], box[3] - box[1]) > symbol_pt:
            continue
        near.append((pts, layer, colour, box))
    if any(is_equipment_layer(q[1]) for q in near):
        near = [q for q in near if is_equipment_layer(q[1])]
    if report is not None:
        report.update(candidates=len(near), tie=False, objects=0, seed=None)
    if not near:
        return None, 0
    seen = Counter(c for c in label_colours if c)
    label_colour = seen.most_common(1)[0][0] if seen else None

    def to_label(q):
        return min(((x - lx) ** 2 + (y - ly) ** 2) ** 0.5 for x, y in q[0])

    dists = sorted((to_label(q), i) for i, q in enumerate(near))
    best_d, best_i = dists[0]
    tied = [i for d, i in dists if d <= best_d + tie]
    fired = False
    if len(tied) > 1 and label_colour is not None:
        same = [i for i in tied if near[i][2] == label_colour]
        if same and best_i not in same:
            best_i, fired = same[0], True
    def grow(start_i):
        """The object at `start_i`: everything it touches, out to symbol_pt
        from it and never wider than symbol_pt overall."""
        taken, frontier = [start_i], [start_i]
        box = near[start_i][3]
        while frontier:
            i = frontier.pop()
            for k, q in enumerate(near):
                if k in taken:
                    continue
                if _gap(near[i][3], q[3]) > link or _gap(near[start_i][3], q[3]) > symbol_pt:
                    continue
                if same_pass and q[2] != near[start_i][2]:
                    continue
                grown = (min(box[0], q[3][0]), min(box[1], q[3][1]),
                         max(box[2], q[3][2]), max(box[3], q[3][3]))
                # NEVER BIGGER THAN THE BIGGEST SYMBOL. A fan touches its
                # duct, the duct touches the riser, the riser runs into the
                # wall: unbounded, "one object" is the whole mechanical pass
                # and its centre is nowhere in particular.
                if max(grown[2] - grown[0], grown[3] - grown[1]) > symbol_pt:
                    continue
                if _touches(near[i][0], q[0], link):
                    taken.append(k)
                    frontier.append(k)
                    box = grown
        return taken, box

    order = [i for _d, i in dists]
    if prefer_pass and label_colour is not None:
        same = [i for i in order if near[i][2] == label_colour]
        if same:
            order = same + [i for i in order if near[i][2] != label_colour]
            fired = fired or order[0] != best_i
    elif fired:
        order = [best_i] + [i for i in order if i != best_i]
    chosen, seed = None, None
    for cand in order:
        taken, box = grow(cand)
        if chosen is None:
            chosen, seed = taken, near[cand]
        # A SYMBOL IS AT LEAST THIS BIG, AND IS NOT A LINE. Otherwise the
        # nearest geometry to a label is a hatch fragment 0.4in across, or a
        # two-point rule under a note, and that is what gets answered; the
        # next candidate out is the equipment.
        if (max(box[2] - box[0], box[3] - box[1]) >= min_symbol
                and sum(len(near[i][0]) for i in taken) >= min_points):
            chosen, seed = taken, near[cand]
            break
    pts = [p for i in chosen for p in near[i][0]]
    if report is not None:
        report.update(seed=seed[3], tie=fired, objects=len(chosen),
                      colour=seed[2], label_colour=label_colour)
    if len(pts) < min_points:
        return None, len(pts)
    x0, y0, x1, y1 = _bbox(pts)
    if report is not None:
        report.update(bbox=(x0, y0, x1, y1))
    return ((x0 + x1) / 2, (y0 + y1) / 2), len(pts)


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
    "labels_in", "symbol_at_label", "LABEL_BOX_PAD_IN",
    "LINK_IN", "TIE_IN", "MIN_SYMBOL_IN",
    "is_text_layer", "is_equipment_layer",
]
