"""A vector drawing's own text layer, rebuilt at span level and structured.

WHY THIS EXISTS
===============

On a CAD-exported sheet every word and number is already in the PDF, exactly.
Index version 3 first sent that text to a vision model to transcribe back into
JSON, and on 588 Thomas S Boyland St that failed three ways in one run: the
notes section ran out of tokens on a 25,000-character general-notes sheet and
returned nothing, the model read the drawing-list index number "2" as the sheet
number, and a 12,000-character prompt cap cut the rest off before it was seen.

So for a vector page the text layer IS the extraction. Notes, schedules,
legends, callouts, stated quantities, dimensions, materials and tag counts are
read from it here, with no model. The vision model is asked only for what a
text layer cannot say: the sheet type and a short summary, plus a title-block
reading that is then checked against the sheet ids actually printed.

FRACTIONS
=========

pypdf flattened a stacked fraction into its digits: 3 1/2" came out as '3 12"'
and 7/8" as '78"'. At span level the fraction is visible — a smaller-font span
of joined digits between the whole number and the inch mark:

    '3 ' size 10.6 | '12' size 7.4 | '" METAL STUD' size 10.6

`rebuild_line` turns that back into '3 1/2" METAL STUD'. A small digit span
that stands alone, with nothing in its line to say which fraction it belongs
to, is not guessed at: it is kept as an UNVERIFIED dimension fragment.

PURE EXCEPT ONE FUNCTION
========================

Everything except `page_layouts` works on plain dicts — pdfplumber characters,
or the blocks/lines/spans shape built from them — so it is tested without a PDF. `page_layouts` is the only
function that imports the PDF library, lazily.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from statistics import median
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════
# Fractions
# ══════════════════════════════════════════════════════════════════════════

VULGAR_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6",
    "⅚": "5/6", "⅐": "1/7", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8",
    "⅞": "7/8", "⅑": "1/9", "⅒": "1/10",
}
DENOMINATORS = (64, 32, 16, 8, 4, 2)
# A span this much smaller than the largest span in its line is set as a
# superscript/subscript — which is how CAD fonts draw a stacked fraction.
SMALL_RATIO = 0.8


def normalize_glyphs(text: str) -> str:
    """Unicode fractions and primes to the ASCII a search can match."""
    if not text:
        return text or ""
    out = []
    for i, ch in enumerate(text):
        frac = VULGAR_FRACTIONS.get(ch)
        if frac:
            if out and out[-1][-1:].isdigit():
                out.append(" ")
            out.append(frac)
        elif ch == "⁄":
            out.append("/")
        elif ch == "′":
            out.append("'")
        elif ch == "″":
            out.append('"')
        else:
            out.append(ch)
    return "".join(out)


def split_stacked_fraction(digits: str) -> Optional[str]:
    """'12' -> '1/2', '78' -> '7/8', '316' -> '3/16', '1516' -> '15/16'.

    None when no reading is a proper, reduced fraction with a drawing
    denominator — '24' would be 2/4, which no drawing prints, so it is not a
    fraction and is left alone."""
    d = (digits or "").strip()
    if not d.isdigit() or not 2 <= len(d) <= 4:
        return None
    for den in DENOMINATORS:
        s = str(den)
        if d.endswith(s) and len(d) > len(s):
            num = int(d[:-len(s)])
            if 0 < num < den and math.gcd(num, den) == 1:
                return f"{num}/{den}"
    return None


def rebuild_line(spans: List[Dict[str, Any]]) -> Tuple[str, int]:
    """Join a line's spans, restoring stacked fractions. (text, fractions_fixed)."""
    sizes = [float(s.get("size") or 0) for s in spans if (s.get("text") or "").strip()]
    big = max(sizes) if sizes else 0.0
    out: List[str] = []
    fixed = 0
    for i, s in enumerate(spans):
        t = s.get("text") or ""
        core = t.strip()
        if big and core.isdigit() and float(s.get("size") or 0) <= SMALL_RATIO * big:
            frac = split_stacked_fraction(core)
            nxt = (spans[i + 1].get("text") or "") if i + 1 < len(spans) else ""
            prev = "".join(out)
            if frac and (nxt.lstrip()[:1] in ('"', "'", "″", "′")
                         or re.search(r"\d\s*$", prev)):
                if re.search(r"\d$", prev):
                    out.append(" ")
                out.append(frac)
                fixed += 1
                continue
        out.append(t)
    return normalize_glyphs("".join(out)), fixed


# ══════════════════════════════════════════════════════════════════════════
# Page layout
# ══════════════════════════════════════════════════════════════════════════

def layout_from_dict(page_dict: Dict[str, Any], *, width: float, height: float,
                     page_number: int, tables: Optional[List[Dict[str, Any]]] = None
                     ) -> Dict[str, Any]:
    """Blocks of rebuilt lines, the page text, and the fraction bookkeeping."""
    page = page_dict
    raw_blocks = [b for b in page_dict.get("blocks") or [] if b.get("type", 0) == 0]
    all_sizes = [float(s.get("size") or 0)
                 for b in raw_blocks for l in b.get("lines") or []
                 for s in l.get("spans") or [] if (s.get("text") or "").strip()]
    body = median(all_sizes) if all_sizes else 0.0

    blocks: List[Dict[str, Any]] = []
    fixed_total = 0
    unverified: List[str] = []
    for b in raw_blocks:
        lines: List[str] = []
        line_bboxes: List[List[float]] = []
        for l in b.get("lines") or []:
            spans = [s for s in l.get("spans") or [] if s.get("text")]
            if not spans:
                continue
            txt, fixed = rebuild_line(spans)
            fixed_total += fixed
            core = txt.strip()
            if not core:
                continue
            biggest = max(float(s.get("size") or 0) for s in spans)
            if (not fixed and body and re.fullmatch(r"\d{1,4}", core)
                    and biggest <= SMALL_RATIO * body):
                # A fraction piece on its own. Kept, not guessed, not dropped.
                unverified.append(core)
            lines.append(core)
            line_bboxes.append([float(v) for v in (l.get("bbox") or b.get("bbox")
                                                   or (0, 0, 0, 0))])
        if lines:
            blocks.append({"bbox": [float(x) for x in b.get("bbox") or (0, 0, 0, 0)],
                           "lines": lines, "line_bboxes": line_bboxes,
                           "text": "\n".join(lines)})
    return {
        "page_number": page_number,
        "width": float(width), "height": float(height),
        "text": "\n".join(b["text"] for b in blocks),
        "blocks": blocks,
        "tables": tables or [],
        "fractions_rebuilt": fixed_total,
        "fractions_unverified": unverified[:200],
        "lines_mirrored": int(page.get("lines_mirrored") or 0),
        "lines_dropped_mirrored": int(page.get("lines_dropped_mirrored") or 0),
    }


# ── LINES ARE BUILT FROM CHARACTERS IN DRAWING ORDER ──────────────────────
#
# pdfminer's own line grouping is geometric, and a stacked fraction is
# geometrically NOT on its line: the numerator sits above the baseline and the
# denominator below it. Measured on A-500.00, pdfminer returned '2" METAL STUD'
# with the '3 1' of '3 1/2"' filed in a different box. CAD writes a label's
# characters in order, so following the drawing order and breaking only on a
# real jump keeps the fraction with its label.
_LINE_ALONG_MAX = 1.6      # x size: farther along the text direction is a new line
_LINE_ALONG_BACK = 0.6     # x size: stepping back more than this is a new line
_LINE_PERP_MAX = 0.75      # x size: a fraction's offset stays under this
_SPACE_GAP = 0.25          # x size: a gap this wide between glyphs is a space
_BLOCK_PERP_MAX = 2.4      # x size: the next line of the same label
_SIZE_TOL = 0.3


def _char_dir(ch: Dict[str, Any]) -> Tuple[float, float]:
    m = ch.get("matrix") or (1, 0, 0, 1, 0, 0)
    a, b = float(m[0]), float(m[1])
    n = math.hypot(a, b) or 1.0
    # pdfplumber's top/bottom run downward; the PDF matrix's y runs upward.
    return (a / n, -b / n)


def _char_center(ch: Dict[str, Any]) -> Tuple[float, float]:
    return ((float(ch["x0"]) + float(ch["x1"])) / 2, (float(ch["top"]) + float(ch["bottom"])) / 2)


def _char_extent(ch: Dict[str, Any], d: Tuple[float, float]) -> float:
    return abs((float(ch["x1"]) - float(ch["x0"])) * d[0]) + abs((float(ch["bottom"]) - float(ch["top"])) * d[1])


def page_dict_from_chars(chars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """pdfplumber characters -> the blocks/lines/spans shape layout_from_dict
    reads. Pure: a character is a dict with text, size, x0, x1, top, bottom
    and matrix, exactly as pdfplumber's page.chars gives it."""
    lines: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for ch in chars:
        text = ch.get("text") or ""
        if not text:
            continue
        size = float(ch.get("size") or 0) or 1.0
        d = _char_dir(ch)
        c = _char_center(ch)
        ext = _char_extent(ch, d)
        joined = False
        if cur is not None and (d[0] * cur["d"][0] + d[1] * cur["d"][1]) > 0.98:
            vx, vy = c[0] - cur["last_c"][0], c[1] - cur["last_c"][1]
            along = vx * d[0] + vy * d[1]
            # Offset from the LINE, not from the previous glyph: a numerator
            # sits above the baseline and its denominator below it, so glyph to
            # glyph they are nearly a full small-size apart while each is well
            # within a fraction's offset of the line itself.
            sx, sy = c[0] - cur["start_c"][0], c[1] - cur["start_c"][1]
            perp = abs(-sx * d[1] + sy * d[0])
            big = max(cur["max_size"], size)
            if -_LINE_ALONG_BACK * big <= along <= _LINE_ALONG_MAX * big + cur["last_ext"] and \
                    perp <= _LINE_PERP_MAX * big:
                gap = along - (cur["last_ext"] + ext) / 2
                if gap > _SPACE_GAP * min(cur["last_size"], size) and text != " " \
                        and not cur["chars"][-1]["text"].endswith(" "):
                    cur["chars"].append({"text": " ", "size": cur["last_size"]})
                # WHICH WAY THE LINE IS BEING WRITTEN. A page rotated in the
                # PDF can emit its glyphs right to left along the same text
                # direction, and the line comes out mirrored: 'GNIDLIUB' for
                # BUILDING. _LINE_ALONG_BACK allows a step backwards, because a
                # stacked fraction needs one, so the join itself cannot refuse.
                cur["back" if along < 0 else "fwd"] += 1
                joined = True
        if not joined:
            cur = {"d": d, "chars": [], "max_size": size, "start_c": c,
                   "x0": float(ch["x0"]), "x1": float(ch["x1"]),
                   "top": float(ch["top"]), "bottom": float(ch["bottom"]),
                   "fwd": 0, "back": 0}
            lines.append(cur)
        cur["chars"].append({"text": text, "size": size})
        cur["last_c"], cur["last_ext"], cur["last_size"] = c, ext, size
        cur["max_size"] = max(cur["max_size"], size)
        cur["x0"] = min(cur["x0"], float(ch["x0"]))
        cur["x1"] = max(cur["x1"], float(ch["x1"]))
        cur["top"] = min(cur["top"], float(ch["top"]))
        cur["bottom"] = max(cur["bottom"], float(ch["bottom"]))

    def spans_of(line_chars):
        spans: List[Dict[str, Any]] = []
        for c in line_chars:
            if spans and (abs(spans[-1]["size"] - c["size"]) <= _SIZE_TOL or c["text"] == " "):
                spans[-1]["text"] += c["text"]
            else:
                spans.append({"text": c["text"], "size": c["size"]})
        return spans

    # A MIRRORED LINE IS NOT A LINE. Every step backwards and none forwards is
    # a line written right to left: reverse it and it reads. Steps in BOTH
    # directions is a line whose reading order cannot be recovered from the
    # order the glyphs were drawn in, and it is dropped rather than quoted — a
    # reversed string inside a citation is a fabrication that looks verified,
    # and nothing downstream can tell it from a real quote.
    mirrored = dropped = 0
    kept: List[Dict[str, Any]] = []
    for ln in lines:
        real = [c for c in ln["chars"] if (c["text"] or "").strip()]
        if ln["back"] > 0 and len(real) > 1:
            if ln["fwd"] == 0:
                ln["chars"] = list(reversed(ln["chars"]))
                mirrored += 1
            elif ln["back"] > ln["fwd"]:
                dropped += 1
                continue
        kept.append(ln)
    lines = kept

    blocks: List[Dict[str, Any]] = []
    prev = None
    for ln in lines:
        bbox = [ln["x0"], ln["top"], ln["x1"], ln["bottom"]]
        # A LEGEND CELL IS A LINE, NOT A BLOCK. Three stacked labels arrive as
        # one block, and pairing whole blocks produced 'A = EXIT SIGN DOOR TAG
        # WINDOW TAG'. The line keeps its own box so a legend can be read row
        # by row.
        entry = {"spans": spans_of(ln["chars"]), "bbox": list(bbox)}
        same_block = False
        if prev is not None and (ln["d"][0] * prev["d"][0] + ln["d"][1] * prev["d"][1]) > 0.98:
            vx = ln["start_c"][0] - prev["start_c"][0]
            vy = ln["start_c"][1] - prev["start_c"][1]
            along = vx * ln["d"][0] + vy * ln["d"][1]
            perp = abs(-vx * ln["d"][1] + vy * ln["d"][0])
            size = max(ln["max_size"], prev["max_size"])
            length = abs((prev["x1"] - prev["x0"]) * ln["d"][0]) + abs((prev["bottom"] - prev["top"]) * ln["d"][1])
            if 0.5 * size <= perp <= _BLOCK_PERP_MAX * size and abs(along) <= length + size:
                same_block = True
        if same_block:
            b = blocks[-1]
            b["lines"].append(entry)
            b["bbox"] = [min(b["bbox"][0], bbox[0]), min(b["bbox"][1], bbox[1]),
                         max(b["bbox"][2], bbox[2]), max(b["bbox"][3], bbox[3])]
        else:
            blocks.append({"type": 0, "bbox": bbox, "lines": [entry]})
        prev = ln
    return {"blocks": blocks, "lines_mirrored": mirrored,
            "lines_dropped_mirrored": dropped}


def page_layouts(pdf_bytes: bytes, *, pages: Optional[Iterable[int]] = None,
                 with_tables: bool = True) -> List[Optional[Dict[str, Any]]]:
    """One layout per page (1-based `pages` limits which are built; the rest
    are None). The only function here that touches the PDF library.

    pdfplumber (MIT). Its coordinates are the page box as drawn in the file —
    this set's sheets carry /Rotate 270 and pdfplumber reports them 2592x1728
    with the title block on the right, which is what the edge strips expect."""
    import io as _io

    wanted = set(pages) if pages else None
    out: List[Optional[Dict[str, Any]]] = []
    with _open_pdf(_io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            if wanted is not None and i not in wanted:
                out.append(None)
                continue
            tables: List[Dict[str, Any]] = []
            if with_tables:
                try:
                    for t in page.find_tables():
                        tables.append({"bbox": [float(x) for x in t.bbox], "rows": t.extract()})
                except Exception:
                    tables = []
            out.append(layout_from_dict(
                page_dict_from_chars(page.chars), width=float(page.width),
                height=float(page.height), page_number=i, tables=tables))
            try:
                page.close()
            except Exception:
                pass
    return out


# ── ONE PAGE IN MEMORY AT A TIME ──────────────────────────────────────────
#
# page_layouts above parses a whole file and returns every layout. Indexing
# no longer uses it: on 588 Thomas S Boyland St three files at once, each held
# whole, plus their page rasters, took the container down. Indexing reads a
# file from disk, keeps only what the whole file is needed for — each page's
# text, the sheet profile, the tag vocabulary, the drawing-list index — and
# parses a page's full layout again only when that page is being indexed.

def _open_pdf(source):
    """A path, or a binary stream. The one place the PDF library is imported."""
    import logging as _logging

    import pdfplumber  # imported here so the pure functions need nothing

    _logging.getLogger("pdfminer").setLevel(_logging.ERROR)
    return pdfplumber.open(source)


def file_context(pdf_path: str) -> Dict[str, Any]:
    """Whole-file facts from a PDF on disk, one page parsed and released at a
    time. Tables are not read here (they are read per page at index time).

    THE FILE IS REOPENED FOR EVERY PAGE. Measured peak memory over the text
    pass, closing each page inside ONE open file vs reopening per page:
    588 Boyland SET_UPDATED 130 MB vs 22 MB, AR 391 MB vs 287 MB. pdfplumber
    keeps parser state across pages of an open document that page.close()
    does not release; reopening costs no measurable time."""
    texts: List[str] = []
    vector = title_pages = 0
    title_prefixes: set = set()
    text_prefixes: set = set()
    vocab: set = set(SEED_TAGS)
    drawing_index: Dict[str, int] = {}
    with _open_pdf(pdf_path) as pdf:
        count = len(pdf.pages)
    for i in range(1, count + 1):
        with _open_pdf(pdf_path) as pdf:
            page = pdf.pages[i - 1]
            try:
                L = layout_from_dict(page_dict_from_chars(page.chars), width=float(page.width),
                                     height=float(page.height), page_number=i)
            finally:
                page.close()
            texts.append(L["text"])
            p = file_sheet_profile([L])
            vector += p["vector_pages"]
            title_pages += p["title_id_pages"]
            title_prefixes |= set(p["title_prefixes"])
            text_prefixes |= set(p["text_prefixes"])
            vocab |= tag_vocabulary([L])
            for sid, n in drawing_list_index([L]).items():
                drawing_index.setdefault(sid, n)
            del L
    return {
        "page_count": count,
        "texts": texts,
        "profile": {"vector_pages": vector, "title_id_pages": title_pages,
                    "title_prefixes": sorted(title_prefixes), "text_prefixes": sorted(text_prefixes)},
        "tag_vocab": frozenset(vocab),
        "drawing_index": drawing_index,
    }


# ══════════════════════════════════════════════════════════════════════════
# A grid the text layer cannot read
# ══════════════════════════════════════════════════════════════════════════
#
# M-200.00 prints seven schedules and gives the text layer NOT ONE CHARACTER
# from any of them. It is not a scan — the page has 8,046 vector paths and no
# images. The mechanical engineer exports with text converted to curves, so
# every letterform is an outline and every character code is gone.
#
# The RULING LINES are ordinary strokes and they survive. Measured inside the
# PTAC schedule's box, 2026-09-16:
#
#     3,576 edges, 0 characters
#     horizontal: 6 rules of width 894pt, everything else <= 100pt
#     vertical:   2 outer edges 157pt tall, column rules at 44.9pt and 24.6pt,
#                 everything else <= 10pt
#
# A rule is LONG and a letter stroke is SHORT, and on this page that is a
# clean separation rather than a tuned one. pdfplumber's own `lines` strategy
# drowns in the glyph edges and reports a 3x4 table where a 6x16 is printed,
# which is why this does not just raise its tolerance.
#
# This function finds the RECTANGLES. It does not read anything: rendering and
# OCR live in lib/plan_ocr.py, and the split is deliberate — the geometry is
# exact and testable, the reading is not.

_RULE_MIN_H = 150.0     # pt: a row rule spans most of a schedule
_RULE_MIN_V = 20.0      # pt: a column rule spans at least the header band
_RULE_TOL = 1.5         # pt: two rules this close are one rule drawn twice


def _dedupe_rules(vals: List[float], tol: float = _RULE_TOL) -> List[float]:
    out: List[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def ruled_grids(page, min_rows: int = 2, min_cols: int = 3) -> List[Dict[str, Any]]:
    """Every ruled grid on the page, with the characters printed inside it.

    A grid with `chars` of 0 is a schedule the text layer cannot read. Nothing
    here decides what to do about that — `page_layout_at` marks them and the
    indexer decides whether OCR is available."""
    try:
        edges = page.edges
    except Exception:
        return []
    hs = [e for e in edges if e.get("orientation") == "h"
          and float(e.get("width") or 0) >= _RULE_MIN_H]
    if not hs:
        return []
    # Rules that share a span belong to the same table. Rounding to 5pt keeps
    # a table whose rules differ by a hairline together without merging two
    # tables that happen to sit in the same columns.
    spans: Dict[Tuple[int, int], List[Any]] = {}
    for e in hs:
        spans.setdefault((round(float(e["x0"]) / 5), round(float(e["x1"]) / 5)),
                         []).append(e)
    vs_all = [e for e in edges if e.get("orientation") == "v"
              and float(e.get("height") or 0) >= _RULE_MIN_V]
    out: List[Dict[str, Any]] = []
    for es in spans.values():
        rows = _dedupe_rules([float(e["top"]) for e in es])
        if len(rows) < min_rows + 1:
            continue
        x0 = min(float(e["x0"]) for e in es)
        x1 = max(float(e["x1"]) for e in es)
        y0, y1 = rows[0], rows[-1]
        cols = _dedupe_rules([float(e["x0"]) for e in vs_all
                              if x0 - 3 <= float(e["x0"]) <= x1 + 3
                              and float(e["top"]) >= y0 - 3
                              and float(e["bottom"]) <= y1 + 3])
        if len(cols) < min_cols + 1:
            continue
        chars = sum(1 for c in page.chars
                    if x0 <= float(c["x0"]) and float(c["x1"]) <= x1
                    and y0 <= float(c["top"]) and float(c["bottom"]) <= y1)
        out.append({"bbox": [x0, y0, x1, y1], "rows": rows, "cols": cols,
                    "chars": chars})
    # A grid that CONTAINS another is a border or a title block, not a
    # schedule. The sheet frame encloses everything and would otherwise be
    # reported as the biggest table on every page.
    leaves = []
    for g in out:
        gx0, gy0, gx1, gy1 = g["bbox"]
        if any(h is not g and gx0 <= h["bbox"][0] and h["bbox"][2] <= gx1
               and gy0 <= h["bbox"][1] and h["bbox"][3] <= gy1 for h in out):
            continue
        leaves.append(g)
    leaves.sort(key=lambda g: (g["bbox"][1], g["bbox"][0]))
    return leaves


def page_layout_at(pdf_path: str, page_number: int, with_tables: bool = True) -> Dict[str, Any]:
    """One page's full layout, tables included, from a PDF on disk.

    `ocr_grids` are the ruled grids with no characters inside them — printed
    schedules the text layer cannot read. They carry rectangles only; nothing
    has been read off them yet."""
    with _open_pdf(pdf_path) as pdf:
        page = pdf.pages[page_number - 1]
        try:
            tables: List[Dict[str, Any]] = []
            blind: List[Dict[str, Any]] = []
            if with_tables:
                try:
                    for t in page.find_tables():
                        tables.append({"bbox": [float(x) for x in t.bbox], "rows": t.extract()})
                except Exception:
                    tables = []
                try:
                    blind = [g for g in ruled_grids(page) if g["chars"] == 0]
                except Exception:
                    blind = []
            L = layout_from_dict(page_dict_from_chars(page.chars), width=float(page.width),
                                 height=float(page.height), page_number=page_number,
                                 tables=tables)
            L["ocr_grids"] = blind
            # The drawn symbols, described once while the page is open. The
            # LEGEND is not known yet — fields_from_layout pairs these with it
            # — so this carries shapes and boxes and decides nothing.
            L["glyph_clusters"], L["mark_words"] = _glyph_inputs(page)
            return L
        finally:
            page.close()


def _glyph_inputs(page) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(clusters, short words). Both are what lib/plan_glyphs needs and neither
    means anything on its own. A page with no paths — a scan — yields nothing,
    which is how the 7 non-vector pages on this project opt out."""
    from lib import plan_glyphs
    try:
        clusters = plan_glyphs.describe_page(page)
    except Exception:
        return [], []
    if not clusters:
        return [], []
    words = []
    try:
        for w in page.extract_words():
            t = str(w.get("text") or "")
            # Only a mark can name a member, and a mark is short. Carrying the
            # whole page's words here would be most of the text layer again.
            if 0 < len(t) <= plan_glyphs.MEMBER_TEXT_MAX:
                words.append({"text": t, "x0": float(w["x0"]), "x1": float(w["x1"]),
                              "top": float(w["top"]), "bottom": float(w["bottom"])})
    except Exception:
        words = []
    return clusters, words


# ══════════════════════════════════════════════════════════════════════════
# Sheet ids and the title block
# ══════════════════════════════════════════════════════════════════════════

# 'S-001.00', 'A-500', 'SSP-004.00'. A hyphen or letter may not precede, so
# 'C-AJ-2086' (a UL system) yields nothing; digits may, because pypdf-style
# text glues a drawing-list index to the id ('2S-001.00GENERAL NOTES').
SHEET_ID_RE = re.compile(r"(?<![A-Z\-])([A-Z]{1,3}-\d{3}(?:\.\d{2}|(?!\d)))")
_TITLE_WORDS = re.compile(
    r"\b(SHEET|DRAWING|TITLE|SCALE|DATE|PROJECT|DRAWN|CHECKED|SEAL|JOB|REVISION|ISSUE|DWG)\b",
    re.I)


def sheet_ids(text: str) -> List[str]:
    seen: List[str] = []
    for m in SHEET_ID_RE.finditer((text or "").upper()):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def title_region(layout: Dict[str, Any], cap: int = 3000) -> str:
    """The edge strip that reads most like a title block. Pages arrive rotated
    either way, so all four edges are scored rather than assuming the right."""
    W, H = layout.get("width") or 0, layout.get("height") or 0
    blocks = layout.get("blocks") or []
    if not (W and H and blocks):
        return ""
    strips = {
        "right": [b for b in blocks if b["bbox"][0] >= 0.8 * W],
        "left": [b for b in blocks if b["bbox"][2] <= 0.2 * W],
        "bottom": [b for b in blocks if b["bbox"][1] >= 0.85 * H],
        "top": [b for b in blocks if b["bbox"][3] <= 0.15 * H],
    }
    # A decimal sheet id outranks title words. Measured on S-001.00: the strip
    # holding its general notes says SHEET and DRAWING more often than the
    # title block does, and cites S-400/S-401 — scoring words first picked it.
    best, best_score = "", (-1, -1)
    for bl in strips.values():
        text = "\n".join(b["text"] for b in bl)
        score = (sum(1 for i in sheet_ids(text) if "." in i), len(_TITLE_WORDS.findall(text)))
        if bl and score > best_score:
            best, best_score = text, score
    return best[:cap]


# A SHEET'S PLACE IN ITS OWN SET, printed in the title block: '16 OF 31'.
# Two numbers that claim the same place are the same sheet — A-105.00 in the
# June owners set and A-105.01 in the August reissue both read '16 OF 31'.
# NOT THE TAIL OF THE SHEET NUMBER. The plumbing set prints
# 'P-202.00 of 19' — the number, then how many sheets there are, with no
# index at all. Without the dot in this lookbehind the '00' of P-202.00
# reads as position zero, and the id found in front of it is 'P-202'.
_SHEET_POSITION_RE = re.compile(r"(?<![\d.])(\d{1,3})\s*OF\s*(\d{1,3})(?!\d)", re.I)

# What a sheet number looks like. Everything else in a project's files — a
# DOB form numbered 'Page 2 of 2', a survey numbered '0', an attachment
# numbered 'F' — is a document, not a drawing.
_SHEET_NUMBER_RE = re.compile(r"^[A-Z]{1,4}-?\d{1,4}[A-Z]?(?:\.\d{1,2})?$")


def _position_match(text: str):
    """The '16 OF 31' match, once it makes sense as a place in a set."""
    for m in _SHEET_POSITION_RE.finditer(text or ""):
        n, of = int(m.group(1)), int(m.group(2))
        if 0 < n <= of:
            return m
    return None


# ── WHICH FILING THIS SHEET BELONGS TO ────────────────────────────────────
#
# Measured on 588 Boyland: the title blocks carry NO document type and NO
# approval status. 'ISSUED FOR', 'PAA', 'FOR FILING', 'NOT FOR CONSTRUCTION'
# and 'PRELIMINARY' appear on zero pages. "PE'S APPROVAL" and "SEAL AND
# SIGNATURE" are printed CAPTIONS beside empty boxes — on 43 pages the text
# immediately after "DRAWING BY" is literally "SEAL AND SIGNATURE".
#
# What they do carry is the DOB job number with its filing suffix, and it
# varies by file along exactly the axis that matters:
#
#   AR - 3.28.25   I1      Owners set     I1      ST   S2
#   PL - 6.29.26   S5      MH - 7.2.26    S6      SP   S7
#   AR - 8.18.26   P5   <- the .01 reissue is a different filing class
#
# dob_logs already tracks these same identifiers (raw_dob_id B01141294-P8,
# signal_kind filing_pending), which is why APPROVAL STATUS IS NOT STORED
# HERE: it changes without the drawing changing, and a status frozen at index
# time is a lie with a date on it. The filing id is the join.
_FILING_RE = re.compile(r"\b(B\d{6,9})\s*-\s*([A-Z]{1,2}\d{1,3})\b", re.I)
_ISSUE_RE = re.compile(
    r"DATE\s+ISSUE\s+OR\s+REVISION\s+(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})", re.I)
# I = initial filing, S = a subsequent filing, P = a post-approval amendment.
# Derived, never read: no sheet prints these words.
_FILING_KIND = {"I": "initial", "S": "subsequent", "P": "post_approval_amendment"}


def filing_id(text: str) -> Optional[str]:
    """'B01141294-P5', or None. Seven of sixteen files on this project carry
    none at all, and that absence is itself an authority signal."""
    m = _FILING_RE.search(text or "")
    return f"{m.group(1).upper()}-{m.group(2).upper()}" if m else None


def document_type(filing: Optional[str], file_name: str = "") -> Optional[str]:
    """Derived from the filing suffix, plus the one thing a name can say."""
    if re.search(r"\bAS[\s_-]?BUILT\b", file_name or "", re.I):
        return "as_built"
    if not filing:
        return None
    suffix = filing.rsplit("-", 1)[-1]
    return _FILING_KIND.get(suffix[:1].upper())


def issue_date(text: str) -> Optional[str]:
    """The date beside 'DATE ISSUE OR REVISION'. Cleaner than the file name's:
    AR - 3.28.25.pdf prints 2/27/2025."""
    m = _ISSUE_RE.search(re.sub(r"\s+", " ", text or ""))
    return m.group(1) if m else None


def sheet_position(text: str) -> Optional[Tuple[int, int]]:
    """'16 OF 31' -> (16, 31), or None when the title block does not say."""
    m = _position_match(text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def looks_like_a_sheet_number(value: Optional[str]) -> bool:
    return bool(_SHEET_NUMBER_RE.fullmatch(re.sub(r"\s+", "", (value or "")).upper()))


def _id_beside_position(title_text: str) -> Optional[str]:
    """The sheet id printed immediately before '16 OF 31', if there is one.

    The title block prints the number and the place together; a section bubble
    prints a number and a detail digit. On the roof plan in the June gas-change
    set the title block is not in the text layer at all, and the only ids in
    the edge strips are the bubbles — which is how that sheet came to be filed
    as A-300, the sheet it points AT, colliding with the real A-300.00."""
    m = _position_match(title_text)
    if not m:
        return None
    before = (title_text or "")[max(0, m.start() - 60):m.start()]
    found = sheet_ids(before)
    return found[-1] if found else None


def validate_sheet_number(model_value: Optional[str], title_ids: List[str],
                          page_ids: List[str],
                          drawing_index: Optional[Dict[str, int]] = None,
                          position: Optional[Tuple[int, int]] = None,
                          title_text: str = "",
                          ) -> Tuple[Optional[str], Optional[str]]:
    """(sheet_number, flag). The TITLE BLOCK decides, and nothing else names
    the sheet.

    The case this exists for: S-001.00's title strip reads '2S-001.00' — its
    position in the drawing list glued to its id — and the model returned "2".

    ── WHAT `page_ids` NO LONGER DOES ─────────────────────────────────────
    #
    # There used to be a branch here that accepted the model's reading when it
    # appeared anywhere in the page's text. On the roof plan in
    # 'AR - 6.9.26 (Gas change).pdf' the title strip yielded nothing, and the
    # only sheet ids on the page were the five its section bubbles point AT:
    # A-200, A-201, A-202, A-300, A-301. The model answered "A-300", the branch
    # confirmed it against a callout, and the roof plan was filed as A-300 —
    # colliding with the real A-300.00, LONGITUDINAL SECTIONS.
    #
    # A callout bubble cannot be told apart from a title-block id by looking at
    # the text: '16 A-105.00' in a title strip and '1 A-300' in a bubble are
    # the same shape, and on this project 26 of 113 pages print their own
    # number that way. So the body text does not get a vote at all. When the
    # title block yields nothing, the drawing list gets one chance, and then
    # the page is left UNNUMBERED and flagged. A wrong sheet number is worse
    # than none: none is a gap, wrong is a sheet that hides another one.
    #
    # `page_ids` stays in the signature — callers pass it, and it is still the
    # right thing to show the model in the prompt.
    """
    def norm(s):
        return re.sub(r"\s+", "", s or "").upper()

    v = norm(model_value)
    by_norm = {norm(i): i for i in title_ids}

    # THE ID PRINTED NEXT TO THE PLACE IS THE SHEET'S OWN. Every title block in
    # this set reads '... DRAWING NO. SHEET NO. <address> A-105.01 16 OF 31
    # ROOF AND BULKEAD PLAN'. The bubbles never carry a place.
    own = _id_beside_position(title_text)
    if own:
        return own, (None if v == norm(own) else "sheet_number_corrected")

    decimal = [i for i in title_ids if "." in i]
    if len(decimal) == 1:
        return decimal[0], (None if v == norm(decimal[0])
                            else ("sheet_number_corrected" if v else "sheet_number_from_text"))
    if len(decimal) > 1:
        # Several full ids in the strip: the model picking one of them is a
        # choice between printed candidates, which is what it is good at.
        return (by_norm.get(v) or decimal[0]), "sheet_number_ambiguous"
    if len(title_ids) == 1:
        return title_ids[0], (None if v == norm(title_ids[0])
                              else ("sheet_number_corrected" if v else "sheet_number_from_text"))
    # NOTHING IN THE TITLE BLOCK. The drawing list is the one other place that
    # names this sheet without guessing: the set's own index says which sheet
    # is number 16, and the title block says this page is 16 of 31.
    if position and drawing_index:
        at = sorted({s for s, n in drawing_index.items() if n == position[0]})
        if len(at) == 1:
            return at[0], "sheet_number_from_drawing_list"
    return None, ("sheet_number_ambiguous" if title_ids else "sheet_number_unresolved")


def headings(layout: Dict[str, Any], limit: int = 40, cap: int = 1500) -> str:
    """Short uppercase lines that name what is on the sheet — context for the
    one summary call, in place of the whole text layer."""
    kw = re.compile(r"PLAN|SCHEDULE|DETAIL|SECTION|ELEVATION|NOTES?|TYPES?|LEGEND|"
                    r"DIAGRAM|RISER|CONDITIONS|INSPECTION|REQUIREMENTS|:$")
    out: List[str] = []
    for b in layout.get("blocks") or []:
        for line in b["lines"]:
            s = line.strip()
            if 3 <= len(s) <= 60 and s.upper() == s and re.search(r"[A-Z]{3}", s) and kw.search(s):
                if s not in out:
                    out.append(s)
            if len(out) >= limit:
                break
    return "\n".join(out)[:cap]


# ══════════════════════════════════════════════════════════════════════════
# Structure from text
# ══════════════════════════════════════════════════════════════════════════

LABEL_MAX_CHARS = 40
_NOTE_NUM_ONLY = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.$")
_NOTE_NUM_INLINE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.\s+(.+)$")
_NOTE_HEADING = re.compile(
    r"\b(NOTES?|CONDITIONS|REQUIREMENTS|SPECIFICATIONS?|INSPECTIONS?|WARRANTY)\b", re.I)


def classify_block(text: str) -> str:
    """notes | heading | legend | label | text"""
    lines = (text or "").split("\n")
    first = lines[0].strip()
    if "LEGEND" in first.upper():
        return "legend"
    if _NOTE_NUM_ONLY.match(first) or _NOTE_NUM_INLINE.match(first):
        return "notes"
    if len(lines) == 1 and first.endswith(":") and _NOTE_HEADING.search(first) and len(first) <= 60:
        return "heading"
    if len(text) <= LABEL_MAX_CHARS:
        return "label"
    return "text"


def _bbox_gap(a: List[float], b: List[float]) -> float:
    """Distance between two boxes; 0 when they touch or overlap."""
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3])
    return max(dx, dy)


# A numbered note continues into the next block when that block is this close:
# CAD writes a note's number as its own text object, and on S-001.00 the
# number of note 8.2 ends the block that holds the text of 8.1.
NOTE_CHAIN_GAP = 40.0
# Unnumbered notes are taken only this close to the NOTES header or the last
# note taken, and never from above the header.
UNNUMBERED_NOTE_GAP = 60.0
_NOTES_HEADER = re.compile(r"^(?:[A-Z0-9&/().,'\-]+\s+){0,5}NOTES?\s*:?$")


def _caps_sentence(s: str) -> bool:
    return (not re.search(r"[a-z]", s) and bool(re.search(r"[A-Z]{3,}", s))
            and len(s.split()) >= 2 and len(s) <= 400)


def notes_from_blocks(blocks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], set]:
    """(notes, indices of the blocks they came from).

    Read as a stream of lines, because a block is a drawing object, not a note:
    one block can hold a heading and three notes, and a number can end the
    block before its own text. Numbered notes split where the numbers are.
    Under a NOTES header, short all-caps blocks with no numbers are notes too,
    one per block. No length cap: a long note is a long chunk, never a
    truncated one."""
    notes: List[Dict[str, Any]] = []
    consumed: set = set()
    heading = None
    current = None
    last_bbox = None
    header_bbox = None          # the NOTES header unnumbered notes hang from
    chain_bbox = None           # the last block taken as an unnumbered note
    for bi, b in enumerate(blocks):
        near = last_bbox is not None and _bbox_gap(last_bbox, b["bbox"]) <= NOTE_CHAIN_GAP
        if not near or (current is not None and current["number"] is None):
            current = None
        used = False
        for raw in b["lines"]:
            s = raw.strip()
            if not s:
                continue
            upper_only = s.upper() == s
            if upper_only and len(s) <= 60 and (
                    (s.endswith(":") and _NOTE_HEADING.search(s)) or _NOTES_HEADER.match(s)):
                heading = s.rstrip(":").strip()
                current = None
                used = True
                if _NOTES_HEADER.match(s):
                    header_bbox, chain_bbox = b["bbox"], b["bbox"]
                continue
            only = _NOTE_NUM_ONLY.match(s)
            inline = _NOTE_NUM_INLINE.match(s)
            if only or inline:
                current = {"number": (only or inline).group(1),
                           "text": inline.group(2) if inline else "", "heading": heading}
                notes.append(current)
                used = True
                continue
            if current is not None:
                current["text"] = (current["text"] + " " + s).strip()
                used = True
                continue
            if (header_bbox is not None and _caps_sentence(s)
                    and b["bbox"][1] >= header_bbox[1] - 2
                    and _bbox_gap(chain_bbox, b["bbox"]) <= UNNUMBERED_NOTE_GAP):
                current = {"number": None, "text": s, "heading": heading}
                notes.append(current)
                chain_bbox = b["bbox"]
                used = True
        if used:
            consumed.add(bi)
            last_bbox = b["bbox"]
    return [n for n in notes if n["text"]], consumed


# Legend entries are separate drawing objects beside the word LEGEND. On
# A-100.00 they sit up to ~200pt away, below and to the right, and the file
# writes them interleaved with unrelated labels — so they are found by where
# they are, not by what came next.
LEGEND_RADIUS = 260.0


# A legend is TWO COLUMNS: the mark, and what it means, on the same row.
# Radius-based pairing ignored that, and on the architectural sheets it matched
# symbols from one column to wall-type text from another — 'EXIT SIGN = 2.5"
# STUD, 1 LAYER GYB.' and 'EXHAUST FAN = 6" STUD, R19 BATT-R11.5 RIGID INSU.,
# STUCCO FINISH', both corroborated on two sheets because the same legend block
# is extracted the same wrong way every time it appears.
SYMBOL_MAX_CHARS = 14        # a mark is short: 'PTAC-1', 'RD OD', 'DHW&R'
LEGEND_ROW_TOL = 0.60        # share of a row's height two blocks may differ by
LEGEND_HEIGHT_RATIO = 1.6    # a taller text is a label that wrapped, not this row
LEGEND_GAP_RATIO = 8.0       # a text further right than this is another column


def _row_overlap(a: List[float], b: List[float]) -> float:
    """Vertical overlap of two bboxes as a share of the shorter one."""
    top, bot = max(a[1], b[1]), min(a[3], b[3])
    short = min(a[3] - a[1], b[3] - b[1]) or 1.0
    return max(0.0, bot - top) / short


# What a MARK looks like, as opposed to a short phrase. 'RD OD', 'PTAC-1',
# 'DHW&R', 'W1' and 'A' are marks; 'PTAC UNIT', 'EXIT SIGN' and 'EXHAUST FAN'
# are what a mark MEANS, and reading them as marks is how a symbol column got
# paired to the wrong text. Every token has to be mark-shaped: short, or
# carrying a digit or a connector.
_SYMBOL_TOKEN = re.compile(r"[A-Z0-9&/.\-\"']+")


# WHAT MAY BECOME A COUNTABLE TAG. Seeding the tag vocabulary from every
# legend symbol put 'A', 'F', 'N', 'T', 'W' and '1' into it, and '1' was then
# counted 138 times across 11 sheets — which is not a tag, it is the digit one.
# A tag is a MARK: letters with an optional number, two characters at least,
# two tokens at most. A bare letter is a callout bubble or a column head.
def looks_like_a_tag(text: str) -> bool:
    """A mark a plan prints as a label, as opposed to a letter in a bubble.

    The FIRST token carries the letters and is at least two characters; a
    following token may be the instance number. 'W1', 'AD', 'PTAC-1', 'RD OD',
    'KE 1' and 'DHW&R' are marks. 'A', 'F', 'N', 'T', 'W' and '1' are not, and
    seeding them from the legend had '1' counted 138 times over 11 sheets."""
    t = (text or "").strip().upper()
    toks = t.split()
    if not t or len(t) > 12 or len(toks) > 2:
        return False
    head = toks[0]
    if len(head) < 2 or not re.fullmatch(r"[A-Z][A-Z&/]{0,3}-?\d{0,2}[A-Z]?", head):
        return False
    if len(toks) == 2 and not re.fullmatch(r"\d{1,2}|[A-Z]{1,3}\d{0,2}", toks[1]):
        return False
    return True


def _looks_like_a_symbol(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > SYMBOL_MAX_CHARS:
        return False
    toks = t.split()
    if not toks or len(toks) > 2:
        return False
    return all(_SYMBOL_TOKEN.fullmatch(tok)
               and (len(tok) <= 3 or re.search(r"[0-9&/]", tok)) for tok in toks)


def legend_from_blocks(blocks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], set]:
    """(entries, indices of the blocks they came from).

    A mark is paired with the text on ITS OWN ROW, to its right, and ONLY when
    the geometry leaves no choice: one mark, one text, similar heights, a small
    gap. Anything else is reported unpaired.

    ── WHY IT REFUSES ─────────────────────────────────────────────────────
    #
    # Radius matching gave 'EXIT SIGN = 2.5" STUD, 1 LAYER GYB.' and 'EXHAUST
    # FAN = 6" STUD, R19 BATT-R11.5 RIGID INSU., STUCCO FINISH' — symbols from
    # one column against wall types from another, on two sheets each, because
    # the same legend is misread the same way every time it appears.
    #
    # Row matching alone is not enough either. A-100.00 stacks SD and CM
    # against ONE label that wraps over two lines, and pairing by row gives
    # 'SD = SMOKE/CARBON MONOXIDE' and 'CM = DETECTOR': two records, both
    # wrong, both looking exactly like the right answer. The wrapped label is
    # twice the height of the mark beside it, and that is the tell.
    #
    # An unpaired mark and an unpaired text are both true records of what is
    # printed. A wrong pair is not, and nothing downstream can catch it."""
    out: List[Dict[str, str]] = []
    consumed: set = set()
    for i, b in enumerate(blocks):
        first = b["lines"][0].strip().upper()
        if "LEGEND" not in first or len(first) > 40:
            continue
        consumed.add(i)
        hb = b["bbox"]
        if len(b["lines"]) > 1:
            for line in b["lines"][1:]:
                if line.strip():
                    out.append({"symbol": "", "meaning": line.strip()[:200],
                                "pair": "same_block"})
            continue
        cells = []
        for j, o in enumerate(blocks):
            if j == i or j in consumed:
                continue
            text = " ".join(l.strip() for l in o["lines"] if l.strip())
            if not text or len(text) > 200 or "LEGEND" in text.upper():
                continue
            if _bbox_gap(hb, o["bbox"]) > LEGEND_RADIUS or o["bbox"][1] < hb[1] - 2:
                continue
            cells.append((j, [float(v) for v in o["bbox"]], text))
        used: set = set()
        for idx, (j, bb, text) in enumerate(cells):
            if idx in used or not _looks_like_a_symbol(text):
                continue
            h = max(1.0, bb[3] - bb[1])
            mates = []
            for m, (k, kb, ktext) in enumerate(cells):
                if m in used or m == idx or kb[0] < bb[2]:
                    continue                          # must sit to the RIGHT
                if _row_overlap(bb, kb) < LEGEND_ROW_TOL:
                    continue                          # must share the row
                if not re.search(r"[A-Za-z]{3,}", ktext):
                    continue
                if (kb[3] - kb[1]) > LEGEND_HEIGHT_RATIO * h:
                    continue                          # a wrapped label, not this row's
                if kb[0] - bb[2] > LEGEND_GAP_RATIO * h:
                    continue                          # too far to be its own column
                mates.append((m, k, ktext))
            if len(mates) == 1:
                m, k, ktext = mates[0]
                out.append({"symbol": text[:60], "meaning": ktext[:200], "pair": "row",
                            "bbox": [float(v) for v in bb],
                            "meaning_bbox": [float(v) for v in kb]})
                used.add(idx); used.add(m)
                consumed.add(j); consumed.add(k)
            else:
                # THE SHEET'S OWN WORDS, NOT A MEANING. A mark with nothing
                # pairable on its row is reported as the mark — but "AD" alone
                # is useless in an answer, so the nearest text the sheet does
                # print travels with it, labelled for what it is. It is NOT a
                # definition and must never be rendered as one.
                near = None
                for _m, (_k, kb, ktext) in enumerate(cells):
                    if _m in used or _m == idx or not re.search(r"[A-Za-z]{3,}", ktext):
                        continue
                    d = _bbox_gap(bb, kb)
                    if near is None or d < near[0]:
                        near = (d, ktext)
                out.append({"symbol": text[:60], "meaning": "", "pair": "unpaired",
                            "nearby": (near[1][:200] if near else ""),
                            "bbox": [float(v) for v in bb]})
                used.add(idx); consumed.add(j)
        for idx, (j, bb, text) in enumerate(cells):
            if idx in used or not re.search(r"[A-Za-z]{3,}", text):
                continue
            out.append({"symbol": "", "meaning": text[:200], "pair": "unpaired",
                        "bbox": [float(v) for v in bb]})
            consumed.add(j)
    return out[:80], consumed


def drawing_list_index(layouts: Iterable[Optional[Dict[str, Any]]]) -> Dict[str, int]:
    """sheet id -> its number in the set's drawing list.

    Read from pages that list at least five sheets. The number is either glued
    to the id ('2S-001.00') or the text object written just before it ('2',
    then 'S-001.00'). Used to recognise a model reading that number as the
    sheet's revision."""
    out: Dict[str, int] = {}
    for L in layouts:
        if not L or sum(1 for i in sheet_ids(L.get("text") or "") if "." in i) < 5:
            continue
        lines = [l.strip() for b in L.get("blocks") or [] for l in b["lines"]]
        for k, line in enumerate(lines):
            glued = re.fullmatch(r"(\d{1,3})\s*([A-Z]{1,3}-\d{3}\.\d{2})", line)
            if glued:
                out.setdefault(glued.group(2), int(glued.group(1)))
                continue
            if re.fullmatch(r"[A-Z]{1,3}-\d{3}\.\d{2}", line) and k > 0 \
                    and re.fullmatch(r"\d{1,3}", lines[k - 1]):
                out.setdefault(line, int(lines[k - 1]))
    return out


_CALLOUT_RES = (
    re.compile(r"\b(\d{1,2})\s*/\s*([A-Z]{1,3}-\d{3}(?:\.\d{2})?)"),
    re.compile(r"\bSEE\s+(?:DETAIL\s+)?(?:(\d{1,2})\s+)?(?:ON\s+)?(?:SHEET\s+)?([A-Z]{1,3}-\d{3}(?:\.\d{2})?)"),
)


def callouts_from_text(text: str) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for rx in _CALLOUT_RES:
        for m in rx.finditer(text or ""):
            key = (m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            out.append({"text": m.group(0)[:160], "detail_number": m.group(1),
                        "target_sheet": m.group(2)})
    return out[:150]


# Same line only: '(3)' closing a UL design number must not adopt the next
# line's 'R-11.5 EPS' as the thing it counts.
_STATED_QTY = re.compile(r"\((\d{1,4})\)[ \t]*([A-Z][A-Z0-9 \-/&.]{2,40}?)[ \t]*(?=$|,|;)", re.M)


def elements_from_evidence(legend: List[Dict[str, Any]],
                           schedules: List[Dict[str, Any]],
                           tag_counts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Things on the sheet that a builder counts or locates.

    ── WHY THIS IS NOT READ FROM THE PROSE ───────────────────────────────
    #
    # It used to be: a regex for '(N) SOMETHING' over the page text. On 588
    # Boyland that produced nine element records, of which seven were sentence
    # fragments — 'WORKING DAYS TO PERFORM REVIEW count=10', 'OF THE NEW YORK
    # CITY BUILDING CODE count=7', 'TWO TIMES TO SIGNAL EVACUATION count=2' —
    # each marked count_verified, because 'verified' only ever meant the digits
    # were in the text, which they were, having been taken from it.
    #
    # An element now needs something structural behind it: a legend symbol, a
    # schedule row, or a tag counted on the plan. Nothing is inferred from a
    # sentence.
    """
    out: List[Dict[str, Any]] = []
    meaning_of = {(e.get("symbol") or "").strip(): (e.get("meaning") or "").strip()
                  for e in legend or [] if (e.get("symbol") or "").strip()}
    for e in legend or []:
        sym, mean = (e.get("symbol") or "").strip(), (e.get("meaning") or "").strip()
        if not sym:
            continue
        near = (e.get("nearby") or "").strip()
        out.append({"name": mean or sym, "tag": sym, "count_if_stated": None,
                    "count_basis": "not_stated", "location_hint": "legend",
                    # Set only when the sheet did not say what the mark means.
                    "described_by": "" if mean else near,
                    "name_is_the_mark": not mean})
    for t in tag_counts or []:
        tag = (t.get("tag") or "").strip()
        if not tag:
            continue
        out.append({"name": meaning_of.get(tag) or tag, "tag": tag,
                    "count_if_stated": t.get("count"),
                    "count_basis": "tag_occurrences", "location_hint": "tags on the sheet"})
    for sc in schedules or []:
        cols = [str(c or "") for c in (sc.get("columns") or [])]
        qty = _qty_column_index(cols)
        for row in (sc.get("rows") or [])[:200]:
            mark = str((row or [""])[0] or "").strip()
            if not mark or not _looks_like_a_symbol(mark):
                continue
            n = None
            if qty is not None and qty < len(row):
                cell = str(row[qty] or "").strip()
                n = int(cell) if re.fullmatch(r"\d{1,6}", cell) else None
            # ── THE BASIS IS THE SCHEDULE'S SOURCE, NOT "IT WAS A SCHEDULE" ─
            #
            # This read `ocr_grid -> ocr_schedule_qty, everything else ->
            # schedule_qty`, and "everything else" includes a schedule the
            # VISION MODEL read off the image. On M-200.00 that put
            # `PTAC-1 count 21` at schedule_cell — the strongest tier there is
            # — on the strength of a picture. The number was right; the badge
            # was not, and nothing downstream could tell it from a cell the
            # text layer handed over.
            #
            # "vision_read" is spelled rather than imported: plan_extract
            # imports THIS module, so the constant cannot come back the other
            # way. plan_records.BASIS_TIERS is where it is mapped to a tier.
            basis = "not_stated"
            if n is not None:
                basis = {"ocr_grid": "ocr_schedule_qty",
                         "vision": "vision_read"}.get(sc.get("source"),
                                                      "schedule_qty")
            out.append({"name": meaning_of.get(mark) or mark, "tag": mark,
                        "count_if_stated": n, "count_basis": basis,
                        "location_hint": (sc.get("name") or "schedule")[:120]})
    return out[:150]


_QTY_HEADER_WORDS = ("qty", "quantity", "no.", "number", "count", "total")


def _qty_column_index(columns: List[str]) -> Optional[int]:
    for i, c in enumerate(columns or []):
        h = (c or "").strip().lower()
        if h in _QTY_HEADER_WORDS or "qty" in h or "quantity" in h:
            return i
    return None


_DIM_RE = re.compile(
    r"\d{1,3}'\s*-\s*\d{1,2}(?:\s+\d{1,2}/\d{1,2})?\"|"
    r"(?<![\d/])\d{1,2}\s+\d{1,2}/\d{1,2}\"|"
    r"(?<![\d/])\d{1,2}/\d{1,2}\"|"
    r"(?<![\d/'\-])\d{1,3}\"")

# A DRAWING SCALE IS NOT A DIMENSION. '3/4"=1'-0"' under a detail title is the
# scale the detail is drawn at. Live test 2026-09-15: "stucco thickness" was
# answered with 'FOUNDATION DETAIL STUCCO (UNEXCEVATED) Scale: 3/4"=1'-0"'.
SCALE_EXPR_RE = re.compile(
    r"\bSCALE\s*:?\s*(?:N\.?T\.?S\.?|AS\s+(?:NOTED|INDICATED|SHOWN))|"
    r"(?:\bSCALE\s*:?\s*)?(?:\d{1,2}\s+)?\d{1,2}(?:/\d{1,3})?\"\s*=\s*\d{1,3}'\s*-?\s*\d{0,2}(?:\s+\d/\d)?\"?",
    re.I)


def strip_scales(text: str) -> str:
    """Blank out scale expressions, keeping every other character's position."""
    return SCALE_EXPR_RE.sub(lambda m: " " * len(m.group(0)), text or "")


def dimensions_from_text(text: str) -> List[str]:
    out: List[str] = []
    for m in _DIM_RE.finditer(strip_scales(text or "")):
        v = re.sub(r"\s+", " ", m.group(0))
        if v not in out:
            out.append(v)
    return out[:200]


_MATERIAL_RE = re.compile(
    r"\b(\d{1,2}\s*GA\b|GAUGE|GAGE|STUCCO|GYP|GYPSUM|CONCRETE|CMU|MASONRY|STEEL|STUDS?|"
    r"INSUL|EPS|BATT|PLYWOOD|SHEATHING|MEMBRANE|FIRE\s*RATED|\d\s*HR\b|PSI|REBAR|HELICAL|"
    r"PILES?|LUMBER|DECK|BRICK|COPPER|PVC|CAST IRON)\b", re.I)


def material_lines(blocks: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for b in blocks:
        for line in b["lines"]:
            s = line.strip()
            if 4 <= len(s) <= 200 and _MATERIAL_RE.search(s) and s not in out:
                out.append(s)
    return out[:200]


def schedules_from_tables(tables: List[Dict[str, Any]], width: float, height: float
                          ) -> List[Dict[str, Any]]:
    """Tables the PDF library found, minus the ones that are not schedules.

    Measured on this set: the finder also returns the whole title-block frame
    and a sheet's note columns as 'tables'. Those cover most of the page or are
    mostly empty cells, and both are dropped here."""
    out = []
    page_area = (width or 0) * (height or 0)
    for t in tables or []:
        rows = [[re.sub(r"\s+", " ", normalize_glyphs(c or "")).strip() for c in r]
                for r in t.get("rows") or []]
        rows = [r for r in rows if any(r)]
        if len(rows) < 2 or max(len(r) for r in rows) < 2:
            continue
        x0, y0, x1, y1 = t.get("bbox") or (0, 0, 0, 0)
        if page_area and (x1 - x0) * (y1 - y0) > 0.5 * page_area:
            continue
        cells = [c for r in rows for c in r]
        if not cells or sum(1 for c in cells if c) / len(cells) < 0.4:
            continue
        first = [c for c in rows[0] if c]
        if len(first) == 1 and len(rows) > 2:
            name, columns, body = first[0], rows[1], rows[2:]
        else:
            name = next((c for c in cells if "SCHEDULE" in c.upper()), "TABLE")
            columns, body = rows[0], rows[1:]
        out.append({"name": name[:120], "columns": [c[:80] for c in columns[:30]],
                    "rows": [[c[:160] for c in r[:30]] for r in body[:200]],
                    # WHERE ON THE SHEET. The finder already knows; it was
                    # discarded here, so an answer could name a schedule and
                    # not say where to look on a 36-inch drawing.
                    "bbox": [float(v) for v in (t.get("bbox") or (0, 0, 0, 0))]})
    return out[:12]


# ══════════════════════════════════════════════════════════════════════════
# Tags
# ══════════════════════════════════════════════════════════════════════════

SEED_TAGS = frozenset({"PTAC", "RD", "FD", "AD", "CO", "FCO", "VTR", "WH", "HB", "EF", "SD", "CM"})
# No hyphen: 'R-19' is an insulation value, not a mark.
_MARK_RE = re.compile(r"^[A-Z]{1,3}\d{1,2}[A-Z]?$")
TAG_SOURCE = "text-layer tag count"


def tag_vocabulary(layouts: Iterable[Optional[Dict[str, Any]]]) -> FrozenSet[str]:
    """Tags worth counting: a fixed set of MEP abbreviations, plus every mark a
    schedule, legend or note on this set DEFINES — a line that starts with
    'W1' and goes on to describe it, or a table row keyed by 'P3'."""
    vocab = set(SEED_TAGS)
    for L in layouts:
        if not L:
            continue
        # THE SHEET'S OWN LEGEND IS THE TAG LIST. Every mark the legend column
        # prints is a mark worth counting on the plan, whether or not it is in
        # the seed set — the seed set is a dozen MEP abbreviations and cannot
        # know what this drafter uses.
        for e, _used in [legend_from_blocks(L.get("blocks") or [])]:
            for entry in e:
                sym = (entry.get("symbol") or "").strip()
                if sym and looks_like_a_tag(sym) and not SHEET_ID_RE.match(sym):
                    vocab.add(sym)
        for b in L.get("blocks") or []:
            if classify_block(b["text"]) == "label":
                continue
            for line in b["lines"]:
                words = line.split()
                if len(words) >= 3 and _MARK_RE.match(words[0]) and not SHEET_ID_RE.match(words[0]):
                    vocab.add(words[0])
        for t in L.get("tables") or []:
            for r in t.get("rows") or []:
                first = next((c for c in r if c), "") or ""
                tok = first.split()[0] if first.split() else ""
                if _MARK_RE.match(tok):
                    vocab.add(tok)
    return frozenset(vocab)


def count_tags(layout: Dict[str, Any], vocab: FrozenSet[str],
               exclude: FrozenSet[int] = frozenset()) -> List[Dict[str, Any]]:
    """How often each tag is PRINTED AS A LABEL on this sheet.

    Only short blocks count — a tag on a plan is a label on its own. The word
    'PTAC' inside a window-area calculation, which is where it appears on this
    set's floor plans, is not a PTAC tag and is not counted. This is a count of
    labels, never a schedule total, and it says so in its source."""
    counts: Counter = Counter()
    for i, b in enumerate(layout.get("blocks") or []):
        # A legend entry or a note defines a tag; it is not a tag on the plan.
        if len(b["text"]) > LABEL_MAX_CHARS or i in exclude:
            continue
        # CASE-SENSITIVE. A tag is printed in capitals. Upper-casing the block
        # first turned the sprinkler engineer's address, '128 Museum Village
        # Rd', into an RD tag, and the bot answered "RD tag appears 1 time on
        # SP-003.00" for roof drains.
        for tok in re.findall(r"[A-Za-z0-9\-]+", b["text"]):
            if tok in vocab:
                counts[tok] += 1
    return [{"tag": k, "count": v, "source": TAG_SOURCE} for k, v in counts.most_common(60)]


def empty_table_grids(layout: Dict[str, Any], max_fill: float = 0.1) -> int:
    """Tables DRAWN on the sheet whose cells carry no text.

    M-200.00 on 588 Boyland: the ROOMS PTAC UNITS SCHEDULE, the exhaust fan,
    heater and fan schedules are ruled grids whose contents are drawn as
    shapes. The table finder sees the grids and every cell is empty; the text
    layer holds only the title block. Such a grid is a schedule the text layer
    cannot read, and it is the signal to read it from the image instead.

    Not counted: a grid under 2x2, and anything over half the page (the
    title-block frame)."""
    W, H = float(layout.get("width") or 0), float(layout.get("height") or 0)
    page_area = W * H
    n = 0
    for t in layout.get("tables") or []:
        rows = t.get("rows") or []
        if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
            continue
        x0, y0, x1, y1 = t.get("bbox") or (0, 0, 0, 0)
        if page_area and (x1 - x0) * (y1 - y0) > 0.5 * page_area:
            continue
        cells = [c for r in rows for c in r]
        filled = sum(1 for c in cells if (c or "").strip())
        if cells and filled / len(cells) <= max_fill:
            n += 1
    return n


# ══════════════════════════════════════════════════════════════════════════
# Everything a vector page yields without a model
# ══════════════════════════════════════════════════════════════════════════

def _strip_lines(blocks: List[Dict[str, Any]], boilerplate: FrozenSet[str]) -> List[Dict[str, Any]]:
    if not boilerplate:
        return blocks
    out = []
    for b in blocks:
        lines = [l for l in b["lines"]
                 if re.sub(r"\s+", " ", l.strip().lower()) not in boilerplate]
        if lines:
            out.append({"bbox": b["bbox"], "lines": lines, "text": "\n".join(lines)})
    return out


def fields_from_layout(layout: Dict[str, Any], boilerplate: FrozenSet[str] = frozenset(),
                       tag_vocab: FrozenSet[str] = SEED_TAGS) -> Dict[str, Any]:
    blocks = _strip_lines(layout.get("blocks") or [], boilerplate)
    text = "\n".join(b["text"] for b in blocks)
    notes, note_blocks = notes_from_blocks(blocks)
    legend, legend_blocks = legend_from_blocks(blocks)
    used = note_blocks | legend_blocks
    text_blocks = [{"kind": classify_block(b["text"]), "text": b["text"],
                    "bbox": [float(v) for v in (b.get("bbox") or (0, 0, 0, 0))]}
                   for i, b in enumerate(blocks) if i not in used]
    tags = count_tags({"blocks": blocks}, tag_vocab, frozenset(used))
    out = {
        "schedules": schedules_from_tables(layout.get("tables") or [],
                                           layout.get("width") or 0, layout.get("height") or 0),
        "notes": notes,
        "legend": legend,
        "callouts": callouts_from_text(text),
        "elements": [],   # filled below, from structure only
        "dimensions": dimensions_from_text(text),
        "dimensions_unverified": list(layout.get("fractions_unverified") or []),
        "materials": material_lines(blocks),
        "tag_counts": tags,
        "text_blocks": text_blocks,
    }
    out["elements"] = elements_from_evidence(legend, out["schedules"], tags)
    # ── THINGS THE SHEET DRAWS RATHER THAN LETTERS ─────────────────────────
    #
    # A roof drain is a square with an X in it. Nothing above can see it: a
    # schedule quantity covers what somebody scheduled, a tag count covers
    # what somebody lettered. The glyph pass counts what somebody DREW, and
    # only where the legend resolves to exactly one mark — see plan_glyphs
    # for why an ambiguous template emits nothing at all.
    if layout.get("glyph_clusters"):
        from lib import plan_glyphs
        try:
            drawn, gflags = plan_glyphs.count_symbols(
                layout["glyph_clusters"],
                plan_glyphs.legend_rows_from_fields(legend),
                layout.get("mark_words") or [])
            out["elements"] = out["elements"] + drawn
            out["glyph_flags"] = gflags
        except Exception:
            out["glyph_flags"] = ["glyph_count_failed"]
    return out


# ══════════════════════════════════════════════════════════════════════════
# A combined set: the whole project re-issued as one PDF
# ══════════════════════════════════════════════════════════════════════════
#
# 588 Thomas S Boyland St carries "588 THOMAS BOYLAND ST SET_UPDATED.pdf" —
# 44 pages of sheets that are also uploaded as their own discipline sets, most
# with no sheet number in the title block. Indexed, it pays for every sheet
# twice, and with no sheet numbers the supersession pass cannot tell its pages
# are the same sheets, so a question can be answered from the duplicate.

COMBINED_MAX_TITLE_ID_SHARE = 0.5

# The prefixes a sheet id on a NYC set actually uses. Anything else that looks
# like an id in the text — 'NY-112', 'FO-202', 'AJ-208' — is a code, a detail
# reference or a UL system, and must not make a file look like a discipline
# nobody else covers.
DISCIPLINE_PREFIXES = frozenset({
    "A", "AR", "S", "ST", "P", "PL", "M", "MH", "ME", "E", "EL", "FA", "FP", "SP",
    "SSP", "G", "GN", "T", "Z", "C", "L", "RCP", "D", "EN", "DM", "LS",
})


def _prefix(sheet_id: str) -> str:
    return sheet_id.split("-")[0].upper()


def file_sheet_profile(layouts: Iterable[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """How much of a file carries its own sheet numbers, and which disciplines
    its text shows."""
    vector = title_pages = 0
    title_prefixes: set = set()
    text_prefixes: set = set()
    for L in layouts:
        if not L or len((L.get("text") or "").strip()) < 100:
            continue
        vector += 1
        tids = sheet_ids(title_region(L))
        if tids:
            title_pages += 1
            title_prefixes |= {_prefix(i) for i in tids}
        text_prefixes |= {_prefix(i) for i in sheet_ids(L.get("text") or "")}
    return {
        "vector_pages": vector,
        "title_id_pages": title_pages,
        "title_prefixes": sorted(p for p in title_prefixes if p in DISCIPLINE_PREFIXES),
        "text_prefixes": sorted(p for p in text_prefixes if p in DISCIPLINE_PREFIXES),
    }


# A one- or two-page file is not a re-issue of the project. On 588 Boyland the
# as-built survey (1 page) and the shed drawing (1 page) were both taken for
# combined sets because their one page had no sheet number.
COMBINED_MIN_VECTOR_PAGES = 3


def looks_combined(profile: Dict[str, Any]) -> bool:
    """Most of its pages have no sheet number in the title block, and there
    are enough of them to be a set."""
    vp = int(profile.get("vector_pages") or 0)
    return (vp >= COMBINED_MIN_VECTOR_PAGES
            and int(profile.get("title_id_pages") or 0) / vp < COMBINED_MAX_TITLE_ID_SHARE)


def combined_set_decision(profile: Dict[str, Any],
                          discipline_sets: Dict[str, Iterable[str]]) -> Optional[Dict[str, Any]]:
    """The skip, with its reason — or None, and the file is indexed.

    Skipped only when BOTH hold: most pages lack a title-block sheet number,
    and every discipline the file shows is already covered by the project's
    own discipline sets. A file whose disciplines cannot be read at all is
    indexed: nothing says it is a duplicate."""
    if not looks_combined(profile):
        return None
    disciplines = set(profile.get("text_prefixes") or [])
    if not disciplines:
        return None
    covering = {name: {p.upper() for p in prefixes}
                for name, prefixes in (discipline_sets or {}).items()}
    covering = {name: ps for name, ps in covering.items() if ps & disciplines}
    covered = set().union(*covering.values()) if covering else set()
    if not disciplines <= covered:
        return None
    vp = int(profile["vector_pages"])
    missing = vp - int(profile["title_id_pages"])
    return {
        "reason": (f"{missing} of {vp} pages have no sheet number in the title block, and "
                   f"every discipline it shows ({', '.join(sorted(disciplines))}) is already "
                   f"indexed from its own set."),
        "disciplines": sorted(disciplines),
        "covered_by": sorted(covering),
        "title_id_pages": int(profile["title_id_pages"]),
        "vector_pages": vp,
    }


__all__ = [
    "file_sheet_profile", "looks_combined", "combined_set_decision", "DISCIPLINE_PREFIXES",
    "COMBINED_MAX_TITLE_ID_SHARE",
    "normalize_glyphs", "split_stacked_fraction", "rebuild_line", "layout_from_dict",
    "page_layouts", "page_dict_from_chars", "drawing_list_index", "file_context", "page_layout_at",
    "SHEET_ID_RE", "sheet_ids", "title_region", "validate_sheet_number",
    "sheet_position", "looks_like_a_sheet_number",
    "filing_id", "document_type", "issue_date",
    "headings", "classify_block", "notes_from_blocks", "legend_from_blocks",
    "callouts_from_text", "elements_from_evidence", "dimensions_from_text", "material_lines",
    "schedules_from_tables", "ruled_grids", "SEED_TAGS", "TAG_SOURCE", "tag_vocabulary", "count_tags",
    "fields_from_layout",
]
