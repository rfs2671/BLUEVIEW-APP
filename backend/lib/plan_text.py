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
        if lines:
            blocks.append({"bbox": [float(x) for x in b.get("bbox") or (0, 0, 0, 0)],
                           "lines": lines, "text": "\n".join(lines)})
    return {
        "page_number": page_number,
        "width": float(width), "height": float(height),
        "text": "\n".join(b["text"] for b in blocks),
        "blocks": blocks,
        "tables": tables or [],
        "fractions_rebuilt": fixed_total,
        "fractions_unverified": unverified[:200],
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
                joined = True
        if not joined:
            cur = {"d": d, "chars": [], "max_size": size, "start_c": c,
                   "x0": float(ch["x0"]), "x1": float(ch["x1"]),
                   "top": float(ch["top"]), "bottom": float(ch["bottom"])}
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

    blocks: List[Dict[str, Any]] = []
    prev = None
    for ln in lines:
        entry = {"spans": spans_of(ln["chars"])}
        bbox = [ln["x0"], ln["top"], ln["x1"], ln["bottom"]]
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
    return {"blocks": blocks}


def page_layouts(pdf_bytes: bytes, *, pages: Optional[Iterable[int]] = None,
                 with_tables: bool = True) -> List[Optional[Dict[str, Any]]]:
    """One layout per page (1-based `pages` limits which are built; the rest
    are None). The only function here that touches the PDF library.

    pdfplumber (MIT). Its coordinates are the page box as drawn in the file —
    this set's sheets carry /Rotate 270 and pdfplumber reports them 2592x1728
    with the title block on the right, which is what the edge strips expect."""
    import io as _io
    import logging as _logging

    import pdfplumber  # imported here so the pure functions need nothing

    _logging.getLogger("pdfminer").setLevel(_logging.ERROR)
    wanted = set(pages) if pages else None
    out: List[Optional[Dict[str, Any]]] = []
    with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf:
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


def validate_sheet_number(model_value: Optional[str], title_ids: List[str],
                          page_ids: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """(sheet_number, flag). The printed ids decide; the model's reading is
    kept only when it is one of them.

    The case this exists for: S-001.00's title strip reads '2S-001.00' — its
    position in the drawing list glued to its id — and the model returned "2".
    """
    def norm(s):
        return re.sub(r"\s+", "", s or "").upper()

    v = norm(model_value)
    by_norm = {norm(i): i for i in title_ids}
    if v and v in by_norm:
        return by_norm[v], None
    decimal = [i for i in title_ids if "." in i]
    preferred = decimal or title_ids
    if len(preferred) == 1:
        return preferred[0], ("sheet_number_corrected" if v else "sheet_number_from_text")
    if v and v in {norm(i) for i in page_ids}:
        return model_value.strip().upper(), "sheet_number_not_in_title_block"
    if preferred:
        return preferred[0], "sheet_number_ambiguous"
    return (model_value.strip() if model_value else None), ("sheet_number_unverified" if v else None)


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


def legend_from_blocks(blocks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], set]:
    """(entries, indices of the blocks they came from)."""
    out: List[Dict[str, str]] = []
    consumed: set = set()
    for i, b in enumerate(blocks):
        first = b["lines"][0].strip().upper()
        if "LEGEND" not in first or len(first) > 40:
            continue
        consumed.add(i)
        if len(b["lines"]) > 1:
            for line in b["lines"][1:]:
                if line.strip():
                    out.append({"symbol": "", "meaning": line.strip()[:200]})
            continue
        hb = b["bbox"]
        for j, o in enumerate(blocks):
            if j == i or j in consumed:
                continue
            text = " ".join(l.strip() for l in o["lines"] if l.strip())
            if (_bbox_gap(hb, o["bbox"]) <= LEGEND_RADIUS and o["bbox"][1] >= hb[1] - 2
                    and len(text) <= 80 and re.search(r"[A-Za-z]{3,}", text)
                    and "LEGEND" not in text.upper()):
                out.append({"symbol": "", "meaning": text[:200]})
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


def stated_quantities(text: str) -> List[Dict[str, Any]]:
    """'(4) ROOF DRAINS' — a quantity PRINTED on the sheet. Verified by
    construction: it was read from the text, not from a picture."""
    out = []
    for m in _STATED_QTY.finditer(text or ""):
        out.append({"name": m.group(2).strip()[:120], "count_if_stated": int(m.group(1)),
                    "location_hint": "text layer", "count_verified": True})
    return out[:150]


_DIM_RE = re.compile(
    r"\d{1,3}'\s*-\s*\d{1,2}(?:\s+\d{1,2}/\d{1,2})?\"|"
    r"(?<![\d/])\d{1,2}\s+\d{1,2}/\d{1,2}\"|"
    r"(?<![\d/])\d{1,2}/\d{1,2}\"|"
    r"(?<![\d/'\-])\d{1,3}\"")


def dimensions_from_text(text: str) -> List[str]:
    out: List[str] = []
    for m in _DIM_RE.finditer(text or ""):
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
                    "rows": [[c[:160] for c in r[:30]] for r in body[:200]]})
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
        for tok in re.findall(r"[A-Z0-9\-]+", b["text"].upper()):
            if tok in vocab:
                counts[tok] += 1
    return [{"tag": k, "count": v, "source": TAG_SOURCE} for k, v in counts.most_common(60)]


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
    text_blocks = [{"kind": classify_block(b["text"]), "text": b["text"]}
                   for i, b in enumerate(blocks) if i not in used]
    return {
        "schedules": schedules_from_tables(layout.get("tables") or [],
                                           layout.get("width") or 0, layout.get("height") or 0),
        "notes": notes,
        "legend": legend,
        "callouts": callouts_from_text(text),
        "elements": stated_quantities(text),
        "dimensions": dimensions_from_text(text),
        "dimensions_unverified": list(layout.get("fractions_unverified") or []),
        "materials": material_lines(blocks),
        "tag_counts": count_tags({"blocks": blocks}, tag_vocab, frozenset(used)),
        "text_blocks": text_blocks,
    }


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


def looks_combined(profile: Dict[str, Any]) -> bool:
    """Most of its pages have no sheet number in the title block."""
    vp = int(profile.get("vector_pages") or 0)
    return vp > 0 and int(profile.get("title_id_pages") or 0) / vp < COMBINED_MAX_TITLE_ID_SHARE


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
    "page_layouts", "page_dict_from_chars", "drawing_list_index",
    "SHEET_ID_RE", "sheet_ids", "title_region", "validate_sheet_number",
    "headings", "classify_block", "notes_from_blocks", "legend_from_blocks",
    "callouts_from_text", "stated_quantities", "dimensions_from_text", "material_lines",
    "schedules_from_tables", "SEED_TAGS", "TAG_SOURCE", "tag_vocabulary", "count_tags",
    "fields_from_layout",
]
