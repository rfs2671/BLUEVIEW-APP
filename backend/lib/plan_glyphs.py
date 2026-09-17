"""Counting a symbol by the strokes that draw it.

WHAT THIS ANSWERS THAT NOTHING ELSE DOES
========================================

"How many roof drains." The legend prints a glyph beside its meaning, the plan
places that glyph wherever the thing is, and until now nothing in the pipeline
could see it. A schedule quantity covers equipment somebody scheduled; a tag
count covers marks somebody lettered. A drain drawn as a square with an X in
it and tagged `AD` was countable only by a vision model looking at a picture,
which is how `41` happened.

Measured on A-105.01 (588 Boyland, AR - 8.18.26 p7), 13,845 vector paths:

    FLOOR/AREA/ROOF DRAIN template lifted at 6.72pt
    3 exact matches: the legend key, and two on the plan drawn at 9.00pt
    each sitting inside four converging SLOPE DN arrows, each tagged AD
    next best score anywhere on the sheet: 0.067

The two `AD` words on the sheet say the same thing independently. The 0.067
runner-up is the EXHAUST FAN glyph, which is ALSO a square with an X in it and
is indistinguishable at thumbnail size; it is rejected on stroke count.

HOW THE MATCH WORKS
===================

Cluster paths whose boxes touch. Describe each cluster as the set of its
strokes normalised to its own bounding box and quantised to a lattice — so the
same symbol drawn at any scale produces an IDENTICAL set. Compare by Jaccard.
No model, no training, no raster, and nothing to tune.

THE TWO RULES THAT KEEP IT HONEST
=================================

1. SHAPE IDENTIFIES THE FAMILY. THE TEXT IN THE BOX IDENTIFIES THE MEMBER.
   On the same sheet the WINDOW TAG template's next-best score is 0.870 — the
   same hexagon with a different digit inside. A shape match counts WINDOW
   TAGS, not W1 tags. So a match whose box contains text is a MEMBER count and
   says which member; a match whose box contains nothing is a FAMILY count and
   says so. It is never quietly reported as a member count, because that is
   exactly the shape of the failure `41` was.

2. AN AMBIGUOUS TEMPLATE IS NOT LIFTED. Lifting the glyph off the legend is
   the fragile step, not matching it — on this sheet EXIT SIGN, DOOR TAG and
   WINDOW TAG print as one merged text block, and a fixed offset grabs a
   neighbour's strokes. When the legend row does not resolve to exactly one
   cluster, this emits NOTHING rather than a bad template. A wrong template
   produces a confident wrong count.

WHERE IT DOES NOT APPLY
=======================

Vector pages only. 104 of the 111 current pages on Boyland qualify; the other
7 are `sparse` or `none` and have no paths to cluster. Those keep the vision
path and its tier. Raster template matching is a different and much weaker
instrument and is deliberately not offered here under the same name.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# A symbol is small. A wall is one long stroke, and clustering it would union
# the whole floor plate into one blob.
MAX_SYMBOL_PT = 60.0
TOUCH_GAP_PT = 2.0
LATTICE = 16              # quantisation of a cluster's own bounding box
MIN_SEGMENTS = 6          # below this a "shape" is a tick and matches anything
MAX_CLUSTERS = 6000       # a page denser than this is not worth the seconds

Box = Tuple[float, float, float, float]


def _pts(obj: Dict[str, Any]) -> List[Tuple[float, float]]:
    pts = obj.get("pts") or []
    out = []
    for p in pts:
        try:
            out.append((float(p[0]), float(p[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def _box(pts: Sequence[Tuple[float, float]]) -> Box:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def page_objects(page) -> List[Dict[str, Any]]:
    """Drawn things small enough to be a symbol, each with its points.

    pdfplumber, not PyMuPDF: the indexer already opens every page with
    pdfplumber and production carries no other PDF library."""
    out = []
    for kind in ("lines", "curves", "rects"):
        try:
            objs = getattr(page, kind)
        except Exception:
            continue
        for o in objs:
            pts = _pts(o)
            if len(pts) < 2:
                # A rect carries no pts; its corners are its shape.
                try:
                    x0, x1 = float(o["x0"]), float(o["x1"])
                    y0, y1 = float(o["y0"]), float(o["y1"])
                except (KeyError, TypeError, ValueError):
                    continue
                pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            b = _box(pts)
            w, h = b[2] - b[0], b[3] - b[1]
            if w > MAX_SYMBOL_PT or h > MAX_SYMBOL_PT or (w + h) <= 1.0:
                continue
            out.append({"pts": pts, "box": b})
    return out


def cluster(objs: Sequence[Dict[str, Any]], gap: float = TOUCH_GAP_PT
            ) -> List[List[Dict[str, Any]]]:
    """Paths whose boxes touch are one drawn thing. Bucketed by grid cell so
    this is linear in practice rather than quadratic in the page."""
    n = len(objs)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    cell = MAX_SYMBOL_PT
    grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for i, o in enumerate(objs):
        x0, y0, x1, y1 = o["box"]
        for gx in range(int(x0 // cell), int(x1 // cell) + 1):
            for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                grid[(gx, gy)].append(i)
    for (gx, gy), idxs in grid.items():
        near: List[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                near += grid.get((gx + dx, gy + dy), ())
        for i in idxs:
            ax0, ay0, ax1, ay1 = objs[i]["box"]
            ax0, ay0, ax1, ay1 = ax0 - gap, ay0 - gap, ax1 + gap, ay1 + gap
            for j in near:
                if j <= i:
                    continue
                bx0, by0, bx1, by1 = objs[j]["box"]
                if ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1:
                    ra, rb = find(i), find(j)
                    if ra != rb:
                        parent[rb] = ra
    groups: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(objs[i])
    return list(groups.values())


def signature(group: Sequence[Dict[str, Any]], q: int = LATTICE
              ) -> Tuple[Optional[FrozenSet], Box]:
    """(segments, box). Scale-free, position-free, and direction-free: each
    segment's endpoints are sorted, so path order and stroke direction cannot
    make two drawings of one symbol look different."""
    boxes = [o["box"] for o in group]
    b = (min(x[0] for x in boxes), min(x[1] for x in boxes),
         max(x[2] for x in boxes), max(x[3] for x in boxes))
    w, h = b[2] - b[0], b[3] - b[1]
    if w <= 0.5 or h <= 0.5:
        return None, b
    segs = set()
    for o in group:
        pts = o["pts"]
        norm = [(max(0, min(q, round((p[0] - b[0]) / w * q))),
                 max(0, min(q, round((p[1] - b[1]) / h * q)))) for p in pts]
        for a, c in zip(norm, norm[1:]):
            if a != c:
                segs.add((a, c) if a < c else (c, a))
    if len(segs) < MIN_SEGMENTS:
        return None, b
    return frozenset(segs), b


def similarity(a: Optional[FrozenSet], b: Optional[FrozenSet]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def describe_page(page) -> List[Dict[str, Any]]:
    """Every symbol-sized cluster on the page, with its shape and its box."""
    objs = page_objects(page)
    if not objs:
        return []
    out = []
    for g in cluster(objs):
        sig, box = signature(g)
        if sig is not None:
            out.append({"sig": sig, "box": box, "strokes": len(g)})
        if len(out) >= MAX_CLUSTERS:
            break
    return out


# ══════════════════════════════════════════════════════════════════════════
# Lifting a template off the legend — the fragile half
# ══════════════════════════════════════════════════════════════════════════

TEMPLATE_REACH_PT = 44.0     # how far left of a label its glyph may sit
TEMPLATE_SLACK_PT = 7.0      # vertical slack around the label's own band


def lift_template(clusters: Sequence[Dict[str, Any]], label_box: Box
                  ) -> Tuple[Optional[Dict[str, Any]], str]:
    """(template, why not). EXACTLY ONE cluster beside the label, or nothing.

    Nothing is the correct answer surprisingly often and it is not a failure:
    a template lifted off the wrong strokes counts the wrong thing everywhere
    on the sheet, confidently, and no downstream check would catch it.

    ── WHY THE TEST IS 'HOW MANY GLYPHS', NOT 'HOW MANY LINES' ────────────
    #
    # A105.01 prints EXIT SIGN, DOOR TAG and WINDOW TAG as one merged text
    # block — three legend rows, three glyphs, one block. It also prints
    # SMOKE/CARBON MONOXIDE DETECTOR as one row wrapped over two lines, with
    # one glyph. Counting lines refuses both; counting glyphs refuses the
    # first and accepts the second, and the glyph count is the actual
    # evidence about how many marks the label is claiming."""
    lx0, ly0, lx1, ly1 = label_box
    bx0, by0 = lx0 - TEMPLATE_REACH_PT, ly0 - TEMPLATE_SLACK_PT
    bx1, by1 = lx0 - 0.5, ly1 + TEMPLATE_SLACK_PT
    hits = [c for c in clusters
            if c["box"][0] <= bx1 and bx0 <= c["box"][2]
            and c["box"][1] <= by1 and by0 <= c["box"][3]]
    if not hits:
        return None, "no drawn glyph beside the label"
    if len(hits) > 1:
        return None, f"{len(hits)} clusters beside the label"
    return hits[0], ""


# ══════════════════════════════════════════════════════════════════════════
# Counting — and the guard
# ══════════════════════════════════════════════════════════════════════════

MEMBER_TEXT_MAX = 6          # 'W1', 'AD', 'EF-2'. Longer is a caption, not a mark.


def text_inside(box: Box, words: Sequence[Dict[str, Any]]) -> str:
    """The mark printed INSIDE a symbol, which is what names the member.

    Strictly inside its own box — not "nearby". A word beside the symbol is a
    caption, a dimension or the next symbol's mark, and treating it as the
    member's name is the same mistake as reading a meaning off proximity.

    It also has to LOOK like a mark. `looks_like_a_tag` is the same test the
    tag counter uses, and it is here for the same reason: seeding a count from
    a single letter had '1' counted 138 times across 11 sheets."""
    from lib.plan_text import looks_like_a_tag
    got = []
    for w in words:
        try:
            cx = (float(w["x0"]) + float(w["x1"])) / 2
            cy = (float(w["top"]) + float(w["bottom"])) / 2
        except (KeyError, TypeError, ValueError):
            continue
        if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
            got.append((float(w["x0"]), str(w.get("text") or "")))
    got.sort()
    joined = "".join(t for _x, t in got).strip()
    if not joined or len(joined) > MEMBER_TEXT_MAX or not looks_like_a_tag(joined):
        return ""
    return joined


def count_symbols(clusters: Sequence[Dict[str, Any]],
                  legend_rows: Sequence[Dict[str, Any]],
                  words: Sequence[Dict[str, Any]]) -> Tuple[List[dict], List[str]]:
    """(elements, flags). One element per (legend meaning, member) actually
    drawn on the sheet.

    `legend_rows` are {meaning, box, lines}. Each yields a template or nothing.
    Matches are exact — Jaccard 1.0 — because on the measured sheet the gap
    between a real match and the nearest impostor is 1.000 against 0.067, and
    a threshold below that buys nothing and risks the 0.870 case."""
    out: List[dict] = []
    flags: List[str] = []
    seen_rows = set()
    for row in legend_rows:
        meaning = (row.get("meaning") or "").strip()
        box = row.get("box")
        if not meaning or not box:
            continue
        key = (meaning, tuple(round(float(v), 1) for v in box))
        if key in seen_rows:
            continue
        seen_rows.add(key)
        tmpl, why = lift_template(clusters, box)
        if tmpl is None:
            flags.append(f"glyph_template_skipped:{meaning[:28]}:{why}")
            continue
        hits = [c for c in clusters
                if c is not tmpl and similarity(tmpl["sig"], c["sig"]) >= 1.0]
        if not hits:
            continue
        by_member: Dict[str, List[Box]] = defaultdict(list)
        for c in hits:
            by_member[text_inside(c["box"], words)].append(c["box"])
        for member, boxes in sorted(by_member.items()):
            # THE GUARD. No text in the box means the shape is all we have,
            # and the shape names the family.
            scope = "member" if member else "family"
            out.append({
                "name": meaning,
                "tag": member,
                "count_if_stated": len(boxes),
                "count_basis": "glyph_match",
                "glyph_scope": scope,
                "location_hint": (
                    f"{member} symbols counted on the sheet" if member
                    else "symbols matching the legend mark, no mark inside them"),
                # The first is the record's region; the rest travel in the
                # payload so an answer can say where all of them are.
                "bbox": [round(v, 1) for v in boxes[0]],
                "positions": [[round(v, 1) for v in b] for b in boxes[:60]],
            })
    return out, flags


def legend_rows_from_fields(legend: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The legend rows whose MARK IS DRAWN rather than lettered.

    `legend_from_blocks` pairs a printed symbol with a printed meaning. A row
    like `FLOOR/AREA/ROOF DRAIN` has no printed symbol at all — the mark is a
    glyph — so it arrives with an empty `symbol` and its meaning's own box.
    Those are exactly the rows that need a template; a row that already has a
    lettered mark is counted by `count_tags` and does not need one."""
    rows = []
    for e in legend or []:
        meaning = (e.get("meaning") or "").strip()
        if (e.get("symbol") or "").strip() or not meaning:
            continue
        box = e.get("meaning_bbox") or e.get("bbox")
        if not box or len(box) != 4:
            continue
        rows.append({"meaning": meaning, "box": tuple(float(v) for v in box)})
    return rows


def symbols_on_page(page, legend_rows: Sequence[Dict[str, Any]]
                    ) -> Tuple[List[dict], List[str]]:
    """The whole pass for one pdfplumber page. Empty for a page with no paths,
    which is what a scan is."""
    try:
        clusters = describe_page(page)
    except Exception as e:
        logger.warning("glyph clustering failed: %r", e)
        return [], ["glyph_cluster_failed"]
    if not clusters:
        return [], []
    try:
        words = page.extract_words()
    except Exception:
        words = []
    return count_symbols(clusters, legend_rows, words)


__all__ = ["page_objects", "cluster", "signature", "similarity", "describe_page",
           "lift_template", "text_inside", "count_symbols", "symbols_on_page",
           "legend_rows_from_fields",
           "MAX_SYMBOL_PT", "LATTICE", "MIN_SEGMENTS", "MEMBER_TEXT_MAX"]
