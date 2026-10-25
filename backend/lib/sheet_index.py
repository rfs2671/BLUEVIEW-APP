"""The spatial index of one sheet: every word where it sits, and the detail callouts.

WHY THIS EXISTS
===============

Search in the old viewer ran inside pdf.js in a WebView (pdfSearchScript.js): it
needed the whole document parsed on the device, and its highlight boxes arrived
over a bridge. Here the text layer is read ONCE on the server, in the same display
frame the tiles are drawn in, and shipped as a small JSON next to them. The client
searches it in memory (0 ms, across every page) and draws the hits on the same
canvas, in the same transform, as the tiles.

COORDINATES
===========

DISPLAY space, normalized: x / page width and y / page height, both in [0, 1],
origin top-left, y down - the frame the tiles are in, so a box is drawn at
(x * level_width, y * level_height) at ANY zoom with no further maths. The page's
/Rotate is applied (pdfplumber's frame, as in plan_page / plan_text / plan_crop).

WHAT IS IN IT
=============

words           [{text, bbox:[x0,y0,x1,y1], line}] in reading order. `line` groups
                words of one text line so a multi-word phrase can be matched.
callouts        a detail reference to ANOTHER place: "3/A-402", or the stacked form a
                CAD export draws (the detail number over the sheet number, in a
                circle). {label, detail, sheet, sheet_key, bbox}. The TARGET
                (which file and page, and where the detail sits there) is resolved
                from the project's sheet registry when the index is served, because
                the target page may not exist yet when this one is read.
detail_markers  the same pair when its sheet number is THIS sheet's own: the detail's
                title bubble. {detail, sheet, bbox, crop, crop_exact}. `crop` is an
                APPROXIMATE viewport (the title's neighbours bound it); `crop_exact`
                is False until it has been validated on real sheets. A client uses it
                to frame a portal and never presents it as the detail's true border.

NOTHING IS GUESSED INTO A BOX. A callout the text layer does not contain is not
invented; a sheet number that is in no registry resolves to nothing.

PURE EXCEPT `build_page_index`, the one function that opens a PDF (lazily).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["SCHEMA", "MAX_WORDS", "sheet_key", "group_lines", "find_callouts", "detail_markers_of",
           "approximate_crops", "normalize_words", "rotated_words", "resolve_callouts", "build_page_index"]

SCHEMA = 1
MAX_WORDS = 60000              # a page with more text than this is truncated (and says so)

#: a sheet number as drawn: A-402, ME-401, SSP-011.00, A402, S-101.1
_SHEET = r"[A-Z]{1,3}\s?-?\s?\d{2,4}(?:\.\d{1,2})?"
_SHEET_WORD = re.compile(rf"^{_SHEET}$")
_DETAIL_WORD = re.compile(r"^(?:\d{1,2}|[A-Z])$")
#: "3/A-402" or "3 / A402": a detail number, a slash, a sheet number
_INLINE = re.compile(rf"(?<![A-Z0-9])(\d{{1,2}}|[A-Z])\s*/\s*({_SHEET})(?![A-Z0-9])")


def sheet_key(value: Any) -> str:
    """The comparable form of a sheet number: upper case, no spaces, hyphens or
    underscores, and a trailing ".00" dropped, so "A-402", "A402" and "A-402.00" agree."""
    s = re.sub(r"[\s_-]+", "", str(value or "").upper())
    return re.sub(r"\.0+$", "", s)


# ── words and lines (pure) ───────────────────────────────────────────────────

def normalize_words(raw: Iterable[Dict[str, Any]], width: float, height: float) -> List[Dict[str, Any]]:
    """pdfplumber words ({text, x0, x1, top, bottom, size?}) -> [{text, bbox, size}]
    with every coordinate normalized to the page and clamped to [0, 1]. Words with
    no text or no area are dropped."""
    out: List[Dict[str, Any]] = []
    if width <= 0 or height <= 0:
        return out
    for w in raw:
        text = str(w.get("text") or "").strip()
        if not text:
            continue
        try:
            x0, x1, y0, y1 = float(w["x0"]), float(w["x1"]), float(w["top"]), float(w["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        if x1 <= x0 or y1 <= y0:
            continue
        box = [min(1.0, max(0.0, x0 / width)), min(1.0, max(0.0, y0 / height)),
               min(1.0, max(0.0, x1 / width)), min(1.0, max(0.0, y1 / height))]
        out.append({"text": text, "bbox": [round(v, 5) for v in box], "size": float(w.get("size") or (y1 - y0))})
    return out


def group_lines(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The words, in reading order, each given a `line` number. Words belong to one
    line when their vertical centres are within 55 % of the taller word's height."""
    hinted = [w for w in words if w.get("hint") is not None]
    words = [w for w in words if w.get("hint") is None]
    ordered = sorted(words, key=lambda w: ((w["bbox"][1] + w["bbox"][3]) / 2, w["bbox"][0]))
    lines: List[List[Dict[str, Any]]] = []
    for w in ordered:
        cy = (w["bbox"][1] + w["bbox"][3]) / 2
        h = w["bbox"][3] - w["bbox"][1]
        placed = False
        for line in reversed(lines[-6:]):            # a word joins one of the nearest lines only
            ref = line[0]
            rcy = (ref["bbox"][1] + ref["bbox"][3]) / 2
            rh = ref["bbox"][3] - ref["bbox"][1]
            if abs(cy - rcy) <= 0.55 * max(h, rh):
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])
    out: List[Dict[str, Any]] = []
    for n, line in enumerate(lines):
        for w in sorted(line, key=lambda w: w["bbox"][0]):
            out.append({"text": w["text"], "bbox": w["bbox"], "line": n, "size": w.get("size", 0.0)})
    # Text that does not run left to right (vertical, upside-down, diagonal) was
    # grouped along ITS OWN direction by rotated_words(); its lines follow the rest.
    base = len(lines)
    for w in sorted(hinted, key=lambda w: (w["hint"], w.get("order", 0))):
        out.append({"text": w["text"], "bbox": w["bbox"], "line": base + int(w["hint"]), "size": w.get("size", 0.0)})
    return out


def rotated_words(chars: Iterable[Dict[str, Any]], width: float, height: float) -> List[Dict[str, Any]]:
    """Words for characters that do NOT read left to right (pdfplumber's
    `upright` is False): vertical and upside-down text, diagonal notes.

    pdfplumber hands such text back one character at a time, so a vertical
    "FIRE RATED WALL" could not be searched. Each character's `matrix` carries
    its reading direction (in the PDF's y-up frame, page rotation applied); the
    characters are grouped by that direction, clustered into lines across it,
    ordered along it, and split into words at spaces and at gaps wider than
    0.3 em. Returns [{text, bbox, size, hint, order}] with normalized boxes;
    `hint` is the line number among the rotated lines."""
    import math
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for c in chars:
        text = c.get("text")
        m = c.get("matrix")
        if text is None or not m or len(m) < 4:
            continue
        a, b = float(m[0]), float(m[1])
        if math.hypot(a, b) < 1e-9:
            continue
        ang = int(round(math.degrees(math.atan2(-b, a)) / 5.0)) * 5        # reading angle in the y-down display frame
        try:
            x0, x1, y0, y1, size = float(c["x0"]), float(c["x1"]), float(c["top"]), float(c["bottom"]), float(c.get("size") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        groups.setdefault(ang, []).append({"t": text, "x0": x0, "x1": x1, "y0": y0, "y1": y1, "size": size or abs(y1 - y0)})
    out: List[Dict[str, Any]] = []
    hint = 0
    for ang in sorted(groups):
        ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))        # along the reading direction
        vx, vy = -uy, ux                                                           # across it
        cs = groups[ang]
        for ch in cs:
            cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["y0"] + ch["y1"]) / 2
            ch["s"], ch["u"] = cx * ux + cy * uy, cx * vx + cy * vy
        lines: List[List[Dict[str, Any]]] = []
        for ch in sorted(cs, key=lambda c: c["u"]):
            if lines and abs(ch["u"] - lines[-1][0]["u"]) <= 0.55 * max(ch["size"], lines[-1][0]["size"]):
                lines[-1].append(ch)
            else:
                lines.append([ch])
        for line in lines:
            line.sort(key=lambda c: c["s"])
            word: List[Dict[str, Any]] = []
            order = 0

            def flush() -> None:
                nonlocal word, order
                text = "".join(c["t"] for c in word).strip()
                if text and width > 0 and height > 0:
                    box = [min(c["x0"] for c in word) / width, min(c["y0"] for c in word) / height,
                           max(c["x1"] for c in word) / width, max(c["y1"] for c in word) / height]
                    box = [round(min(1.0, max(0.0, v)), 5) for v in box]
                    if box[2] > box[0] and box[3] > box[1]:
                        out.append({"text": text, "bbox": box, "size": max(c["size"] for c in word),
                                    "hint": hint, "order": order})
                        order += 1
                word = []

            for ch in line:
                if not ch["t"].strip():
                    flush()
                    continue
                if word and ch["s"] - word[-1]["s"] > 1.25 * max(word[-1]["size"], ch["size"]) * 0.6 + 0.3 * ch["size"]:
                    flush()
                word.append(ch)
            flush()
            hint += 1
    return out


# ── callouts (pure) ──────────────────────────────────────────────────────────

def _union(boxes: Sequence[Sequence[float]]) -> List[float]:
    return [round(min(b[0] for b in boxes), 5), round(min(b[1] for b in boxes), 5),
            round(max(b[2] for b in boxes), 5), round(max(b[3] for b in boxes), 5)]


def _inline_callouts(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """"3/A-402" typed on one line, matched across the words of that line."""
    by_line: Dict[int, List[Dict[str, Any]]] = {}
    for w in words:
        by_line.setdefault(w["line"], []).append(w)
    out = []
    for line_words in by_line.values():
        text, spans = "", []
        for w in line_words:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(w["text"]), w))
            text += w["text"].upper()
        for m in _INLINE.finditer(text):
            hit = [w for a, b, w in spans if a < m.end() and b > m.start()]
            if hit:
                out.append({"detail": m.group(1), "sheet": re.sub(r"\s+", "", m.group(2)),
                            "bbox": _union([w["bbox"] for w in hit])})
    return out


def _stacked_callouts(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The detail number drawn over the sheet number (a CAD callout circle): a short
    token directly above a sheet-number token, centred on it, about the same size."""
    small = [w for w in words if _DETAIL_WORD.match(w["text"].upper())]
    sheets = [w for w in words if _SHEET_WORD.match(w["text"].upper())]
    out = []
    used = set()
    for d in small:
        dx = (d["bbox"][0] + d["bbox"][2]) / 2
        dh = d["bbox"][3] - d["bbox"][1]
        best = None
        for s in sheets:
            if id(s) in used:
                continue
            sx = (s["bbox"][0] + s["bbox"][2]) / 2
            sh = s["bbox"][3] - s["bbox"][1]
            gap = s["bbox"][1] - d["bbox"][3]
            if (-0.25 * dh <= gap <= 1.2 * max(dh, sh)
                    and abs(sx - dx) <= 0.6 * max(d["bbox"][2] - d["bbox"][0], s["bbox"][2] - s["bbox"][0])
                    and 0.5 <= (sh / dh if dh else 0) <= 2.0):
                if best is None or gap < best[0]:
                    best = (gap, s)
        if best:
            used.add(id(best[1]))
            out.append({"detail": d["text"].upper(), "sheet": re.sub(r"\s+", "", best[1]["text"].upper()),
                        "bbox": _union([d["bbox"], best[1]["bbox"]])})
    return out


def find_callouts(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every detail reference in the text layer, inline or stacked, each once:
    [{label, detail, sheet, sheet_key, bbox}] in reading order."""
    found = _inline_callouts(words) + _stacked_callouts(words)
    seen, out = set(), []
    for c in sorted(found, key=lambda c: (round(c["bbox"][1], 3), c["bbox"][0])):
        k = (c["detail"], sheet_key(c["sheet"]), tuple(round(v, 3) for v in c["bbox"]))
        if k in seen:
            continue
        seen.add(k)
        out.append({"label": f"{c['detail']}/{c['sheet']}", "detail": c["detail"], "sheet": c["sheet"],
                    "sheet_key": sheet_key(c["sheet"]), "bbox": c["bbox"]})
    return out


def detail_markers_of(callouts: List[Dict[str, Any]], own_sheet: Optional[str]) -> List[Dict[str, Any]]:
    """The callouts that name THIS sheet: the detail title bubbles. With no known
    sheet number there are none: a marker is never guessed."""
    own = sheet_key(own_sheet)
    if not own:
        return []
    return [{"detail": c["detail"], "sheet": c["sheet"], "bbox": c["bbox"]} for c in callouts
            if c["sheet_key"] == own]


def approximate_crops(markers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give each marker an APPROXIMATE viewport, bounded by its neighbours.

    A detail's title sits at the bottom-left of its drawing. So the viewport runs
    from the title's left edge to the next title on the same row (or the page's
    right margin), and from the lowest title above it that it overlaps (or the top
    margin) down to just under its own title. `crop_exact` is always False: this is
    where the detail probably is, not a measured border."""
    margin = 0.01
    out = []
    for m in markers:
        x0, y0, x1, y1 = m["bbox"]
        h = max(y1 - y0, 1e-4)
        row = [o for o in markers if o is not m and abs(((o["bbox"][1] + o["bbox"][3]) - (y0 + y1)) / 2) <= 1.5 * h
               and o["bbox"][0] > x1]
        right = min([o["bbox"][0] for o in row] + [1.0 - margin])
        above = [o for o in markers if o is not m and o["bbox"][3] < y0 - h
                 and o["bbox"][0] < right and o["bbox"][2] > x0]
        top = max([o["bbox"][3] + h for o in above] + [margin])
        left = max(margin, x0 - h)
        bottom = min(1.0 - margin, y1 + 2.5 * h)
        if right - left < 4 * h or bottom - top < 4 * h:      # a degenerate window is no window
            crop = None
        else:
            crop = [round(left, 5), round(top, 5), round(right - h * 0.5, 5), round(bottom, 5)]
        out.append({**m, "crop": crop, "crop_exact": False})
    return out


# ── callout targets (pure) ───────────────────────────────────────────────────

def resolve_callouts(callouts: List[Dict[str, Any]], file_id: str, page_number: int,
                     registry: Iterable[Dict[str, Any]],
                     page_callouts: Any) -> List[Dict[str, Any]]:
    """Each callout with its TARGET, from the project's sheet registry.

    registry       rows of {sheet_number, file_id, page_number (1-based)}: the
                   plan index's `document_page_index`.
    page_number    the page these callouts are on (1-based).
    page_callouts  (file_id, page_number) -> that page's stored callouts, or None
                   when the page has no index yet (a callable or a dict).

    The target is {file_id, page, sheet, same_sheet, marker_bbox, crop, crop_exact}
    or None when the sheet number is in no registry row. When one sheet number is
    on several files (a revision set), the callout's OWN file wins. `marker_bbox` is
    the detail's title on the target page when that page's text layer has it;
    otherwise None, and the client opens the sheet without a framed detail. A detail
    number is never invented."""
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for row in registry:
        k = sheet_key(row.get("sheet_number"))
        if k and row.get("file_id") is not None and row.get("page_number") is not None:
            by_key.setdefault(k, []).append(row)
    get = page_callouts if callable(page_callouts) else (lambda f, p: (page_callouts or {}).get((f, p)))
    out = []
    for c in callouts:
        rows = by_key.get(c.get("sheet_key") or sheet_key(c.get("sheet")))
        target = None
        if rows:
            row = next((r for r in rows if str(r["file_id"]) == str(file_id)), rows[0])
            tf, tp = str(row["file_id"]), int(row["page_number"])
            marker = None
            stored = get(tf, tp)
            if stored:
                own = detail_markers_of(stored, row.get("sheet_number"))
                match = [m for m in approximate_crops(own) if str(m["detail"]).upper() == str(c["detail"]).upper()
                         and not (tf == str(file_id) and m["bbox"] == c["bbox"])]
                marker = match[0] if match else None
            target = {"file_id": tf, "page": tp, "sheet": row.get("sheet_number") or c.get("sheet"),
                      "same_sheet": tf == str(file_id) and tp == int(page_number),
                      "marker_bbox": marker["bbox"] if marker else None,
                      "crop": marker["crop"] if marker else None,
                      "crop_exact": False}
        out.append({**c, "target": target})
    return out


# ── one page ─────────────────────────────────────────────────────────────────

def build_page_index(source: Any, page_index: int, own_sheet: Optional[str] = None) -> Dict[str, Any]:
    """The index of one page (0-based `page_index`) of a PDF path / bytes / file.
    The only function here that imports a PDF library."""
    import pdfplumber
    with pdfplumber.open(source) as pdf:
        if not 0 <= page_index < len(pdf.pages):
            raise IndexError(f"page {page_index} is not in a {len(pdf.pages)}-page document")
        page = pdf.pages[page_index]
        width, height = float(page.width), float(page.height)
        upright = page.filter(lambda o: o.get("object_type") != "char" or o.get("upright", True))
        raw = upright.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"])
        sideways = [c for c in page.chars if not c.get("upright", True)]
    truncated = len(raw) > MAX_WORDS
    words = normalize_words(raw[:MAX_WORDS], width, height) + rotated_words(sideways, width, height)
    truncated = truncated or len(words) > MAX_WORDS
    words = group_lines(words[:MAX_WORDS])
    callouts = find_callouts(words)
    markers = approximate_crops(detail_markers_of(callouts, own_sheet))
    return {"schema": SCHEMA, "page": page_index + 1, "width_pt": width, "height_pt": height,
            "own_sheet": own_sheet or None, "truncated": truncated,
            "words": [{"text": w["text"], "bbox": w["bbox"], "line": w["line"]} for w in words],
            "callouts": callouts, "detail_markers": markers}
