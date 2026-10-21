"""Where a plans answer came from, as a picture: the sheet, cropped to the
region, the region marked in red.

WHY
===

"Window protection details are on SSP-011.00" sends a superintendent to a
36-inch sheet to find one note. The record the answer rests on already says
where it is (plan_records rule 4, `bbox`), so the DM sends that region, boxed,
after the words. When the answer could rest on several places — the same
value printed twice, or a record read off the image and never checked — every
candidate is boxed and numbered, so the person sees what it is choosing
between instead of trusting a pick.

COORDINATES
===========

A record's `bbox` is [x0, y0, x1, y1] in PDF POINTS (1/72 inch), in DISPLAY
space: the page's /Rotate applied, origin top-left, y down (plan_page,
plan_text.page_layouts — pdfplumber's frame; plan_ocr divides a grid's box by
72 to get inches). The stored page JPEG is pdftoppm's render of the same page
at the indexer's DPI (server._render_dpi_for: 250, 300 for detail sheets), with
the rotation applied too. So a point maps to a pixel by dpi / 72 and nothing
else. `to_pixels` refuses a box that does not land on the image — a mapping
that cannot be shown to hold is not drawn, and the caller sends the whole
sheet instead.

A record with no `bbox` (notes and callouts today — plan_records KNOWN GAP)
is never given a guessed one: its sheet goes whole, and the caption says so.

PURE: records and PIL images in, decisions and PIL images out. No database,
no network, no server import.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

#: At most this many boxes on one answer's pictures, and this many pictures.
MAX_MARKS = 4
MAX_IMAGES = 2
#: The records an answer is matched against: the search's best, in its order.
POOL = 8

#: The crop is never smaller than this much of the sheet (inches): a box with
#: no surroundings cannot be found again on the paper.
MIN_CROP_IN = (6.0, 4.0)
#: Room around the marked region: half its size, never under an inch.
PAD_FRAC = 0.5
MIN_PAD_IN = 1.0
#: A box may overhang the image by this fraction of the image (rounding in the
#: render, a box drawn to the sheet edge). More than that is a wrong mapping.
EDGE_TOLERANCE = 0.02

RED = (220, 20, 20)
WHITE = (255, 255, 255)

Box = Tuple[float, float, float, float]


# ══════════════════════════════════════════════════════════════════════════
# Which records the answer rests on
# ══════════════════════════════════════════════════════════════════════════

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-./'\"]*")
_WORD_STOP = frozenset({
    "about", "above", "after", "again", "below", "between", "drawing", "drawings",
    "every", "floor", "other", "sheet", "sheets", "shall", "should", "there",
    "these", "those", "their", "where", "which", "while", "would", "under"})


def _norm(s: str) -> str:
    return re.sub(r"[,\s]+", " ", str(s or "").upper()).strip()


def _tokens(quote: str) -> Tuple[set, set]:
    """(values, words) a quote prints: tokens carrying a digit ("PTAC-2",
    "3'-6\"", "9,000"), and the longer words."""
    vals, words = set(), set()
    for t in _TOKEN_RE.findall(str(quote or "").replace(",", "")):
        t = t.strip(".-/'\"").upper()
        if len(t) < 2:
            continue
        if any(c.isdigit() for c in t):
            vals.add(t)
        elif len(t) >= 5 and t.lower() not in _WORD_STOP:
            words.add(t)
    return vals, words


def _in(token: str, text: str) -> bool:
    return re.search(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", text) is not None


def sheet_of(r: Dict[str, Any]) -> str:
    return str(r.get("sheet_number") or "").strip()


def location_key(r: Dict[str, Any]) -> tuple:
    """Where a record is: its page and its box (rounded to a point). Two
    records with no box on one page are one place - "somewhere on it"."""
    box = r.get("bbox")
    return (str(r.get("page_id") or ""),
            tuple(round(float(v)) for v in box) if box and len(box) == 4 else None)


def is_unverified(r: Dict[str, Any]) -> bool:
    """Read off the image, or never checked against the page text."""
    return r.get("verified") is False or r.get("tier") == "vision"


def pick(records: Iterable[Dict[str, Any]], answer: str, *,
         usable: Callable[[Dict[str, Any]], bool] = lambda r: True) -> Dict[str, Any]:
    """The records `answer` rests on, and whether that is one place.

    `records` are the turn's search hits, best first; `usable(r)` says the
    record's sheet has a picture to send. Returns {marks: [record, ...]
    (numbered 1.. in this order), ambiguous, unverified} - no marks when
    nothing usable was found.

    1. The sheets the answer names narrow the pool, when it names any.
    2. A record whose printed values (and words) the answer repeats is one it
       used. Records repeating the SAME things are the same fact at several
       places: that is the ambiguity. Records repeating different things are
       several facts the answer combined, each marked.
    3. Nothing repeated: the search's best record on each named sheet (or the
       best overall), and several of those is a choice the person must make.
    4. Any chosen record that is unverified widens to every candidate in the
       pool, so what it could be confused with is on the picture too.
    """
    seen, pool = set(), []
    for r in records:
        k = (r.get("page_id"), r.get("record_type"), r.get("ordinal"), r.get("quote"))
        if k in seen or not r.get("page_id") or not usable(r):
            continue
        seen.add(k)
        pool.append(r)
    # The answer is matched against EVERY search this turn (a refined second
    # search comes after the first's hits); only the fallbacks take the top
    # POOL (Codex on #836).
    if not pool:
        return {"marks": [], "ambiguous": False, "unverified": False}
    said = _norm(answer)
    named = {sheet_of(r) for r in pool if sheet_of(r) and _in(_norm(sheet_of(r)), said)}
    if named:
        pool = [r for r in pool if sheet_of(r) in named]

    hits = []
    for r in pool:
        vals, words = _tokens(r.get("quote") or "")
        hits.append(frozenset(t for t in vals | words if _in(t, said)))
    used = [(r, h) for r, h in zip(pool, hits) if h]
    if used:
        # A record whose hits are all inside another's says less than it.
        chosen = [(r, h) for r, h in used if not any(h < o for _r, o in used)]
        by_fact: Dict[frozenset, list] = {}
        for r, h in chosen:
            by_fact.setdefault(h, []).append(r)
        marks = [r for rs in by_fact.values() for r in rs]
        ambiguous = any(len({location_key(r) for r in rs}) > 1 for rs in by_fact.values())
    else:
        firsts: Dict[str, Dict[str, Any]] = {}
        for r in pool:
            firsts.setdefault(sheet_of(r) or str(r.get("page_id")), r)
        marks = list(firsts.values())[:POOL] if named else [pool[0]]
        ambiguous = len({location_key(r) for r in marks}) > 1
    unverified = any(is_unverified(r) for r in marks)
    if unverified:
        marks = marks + [r for r in pool[:POOL] if r not in marks]
    marks = distinct(marks)[:MAX_MARKS]
    ambiguous = ambiguous or (unverified and len(marks) > 1)
    return {"marks": marks, "ambiguous": ambiguous, "unverified": unverified}


def distinct(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out, keys = [], set()
    for r in records:
        k = location_key(r)
        if k not in keys:
            keys.add(k)
            out.append(r)
    return out


def by_page(marks: Sequence[Dict[str, Any]]) -> List[Tuple[str, List[Tuple[int, Dict[str, Any]]]]]:
    """[(page_id, [(number, record), ...]), ...] in order, at most
    MAX_IMAGES pages; numbers are the marks' 1-based positions."""
    pages: Dict[str, list] = {}
    for i, r in enumerate(marks, start=1):
        pid = str(r.get("page_id"))
        if pid not in pages and len(pages) >= MAX_IMAGES:
            continue
        pages.setdefault(pid, []).append((i, r))
    return list(pages.items())


def caption(sheet: str, *, numbers: Sequence[int], total: int, ambiguous: bool,
            unverified: bool, whole: bool, title: str = "", pictures: int = 1) -> str:
    """The words under one picture."""
    name = (sheet or "the sheet").strip()
    if whole:
        head = f"{name} {title}".strip() if title else name
        if ambiguous:
            return f"{head} — full sheet; the spots aren't marked in the index. Which one did you mean?"
        return f"{head} — full sheet (the exact spot isn't marked in the index)"
    which = f" (#{', #'.join(str(n) for n in numbers)})" if pictures > 1 and total > 1 else ""
    if ambiguous:
        k = len(numbers)
        spots = "1 possible spot" if k == 1 else f"{k} possible spots"
        return f"{spots} on {name}{which} — which one?"
    if total > 1:
        return f"{name}{which} — where this comes from ({len(numbers)} marked)"
    if unverified:
        return f"{name} — where this comes from (read off the image, not checked: look at it)"
    return f"{name} — where this comes from"


# ══════════════════════════════════════════════════════════════════════════
# Geometry
# ══════════════════════════════════════════════════════════════════════════

def px_per_pt(dpi: float) -> float:
    """Pixels per PDF point on a page rendered at `dpi`."""
    return float(dpi) / 72.0


def to_pixels(bbox: Any, scale: float, image_size: Tuple[int, int], *,
              tolerance: float = EDGE_TOLERANCE) -> Optional[Box]:
    """A record's bbox (PDF points, display space) as pixels on the page
    image, or None when it does not land on the image: an empty or
    malformed box, or one past the edge by more than `tolerance` of the
    image (a mapping that cannot be shown to hold is not drawn)."""
    try:
        x0, y0, x1, y1 = (float(v) * float(scale) for v in bbox)
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    w, h = image_size
    if w <= 0 or h <= 0 or x1 - x0 < 1 or y1 - y0 < 1:
        return None
    sx, sy = tolerance * w, tolerance * h
    if x0 < -sx or y0 < -sy or x1 > w + sx or y1 > h + sy:
        return None
    return (max(0.0, x0), max(0.0, y0), min(float(w), x1), min(float(h), y1))


def crop_box(boxes: Sequence[Box], image_size: Tuple[int, int], *,
             px_per_inch: float) -> Tuple[int, int, int, int]:
    """The region to send: every box, padded (PAD_FRAC of the region, never
    under MIN_PAD_IN), at least MIN_CROP_IN, inside the image. A region
    that would cross an edge is shifted, not cut, while the image allows."""
    w, h = image_size
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    pad = max(PAD_FRAC * max(x1 - x0, y1 - y0), MIN_PAD_IN * px_per_inch)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    min_w, min_h = MIN_CROP_IN[0] * px_per_inch, MIN_CROP_IN[1] * px_per_inch
    x0, x1 = _span_at_least(x0, x1, min_w, w)
    y0, y1 = _span_at_least(y0, y1, min_h, h)
    return int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))


def _span_at_least(a: float, b: float, need: float, limit: float) -> Tuple[float, float]:
    if b - a < need:
        mid = (a + b) / 2.0
        a, b = mid - need / 2.0, mid + need / 2.0
    if b - a >= limit:
        return 0.0, float(limit)
    if a < 0:
        a, b = 0.0, b - a
    if b > limit:
        a, b = a - (b - limit), float(limit)
    return max(0.0, a), min(float(limit), b)


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except Exception:                                 # pragma: no cover - old Pillow
        return ImageFont.load_default()


def render(image, boxes: Sequence[Tuple[int, Box]], *, px_per_inch: float,
           numbered: bool):
    """The crop of `image` around `boxes` ([(number, pixel box)]), each box
    outlined in thick red - and, when `numbered`, its number on a red tab
    at its top-left corner. Returns a new RGB image; `image` is untouched."""
    from PIL import ImageDraw

    left, top, right, bottom = crop_box([b for _n, b in boxes], image.size,
                                        px_per_inch=px_per_inch)
    out = image.crop((left, top, right, bottom)).convert("RGB")
    draw = ImageDraw.Draw(out)
    width = max(3, int(round(px_per_inch * 0.035)))
    gap = 2 * width                                   # the line sits clear of what it marks
    size = max(14, int(round(px_per_inch * 0.3)))
    font = _font(size) if numbered else None
    W, H = out.size
    for n, (x0, y0, x1, y1) in boxes:
        r = (max(0, x0 - left - gap), max(0, y0 - top - gap),
             min(W - 1, x1 - left + gap), min(H - 1, y1 - top + gap))
        draw.rectangle(r, outline=RED, width=width)
        if not numbered:
            continue
        label = str(n)
        tw, th = _text_size(draw, label, font)
        pad = max(4, size // 5)
        tab_w, tab_h = tw + 2 * pad, th + 2 * pad
        tx = min(max(0, r[0]), W - tab_w)
        ty = r[1] - tab_h if r[1] - tab_h >= 0 else min(r[1] + width, H - tab_h)
        draw.rectangle((tx, ty, tx + tab_w, ty + tab_h), fill=RED)
        draw.text((tx + pad, ty + pad), label, fill=WHITE, font=font)
    return out


def _text_size(draw, text: str, font) -> Tuple[int, int]:
    try:
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        return int(x1 - x0), int(y1 + max(0, y0))
    except Exception:                                 # pragma: no cover - old Pillow
        return draw.textsize(text, font=font)
