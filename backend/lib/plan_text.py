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

Everything below `page_layouts` works on plain dicts shaped like PyMuPDF's
`get_text("dict")`, so it is tested without a PDF. `page_layouts` is the only
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


def page_layouts(pdf_bytes: bytes, *, pages: Optional[Iterable[int]] = None,
                 with_tables: bool = True) -> List[Optional[Dict[str, Any]]]:
    """One layout per page (1-based `pages` limits which are built; the rest
    are None). The only function here that touches the PDF library."""
    import fitz  # PyMuPDF — imported here so the pure functions need nothing

    try:
        fitz.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass
    wanted = set(pages) if pages else None
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out: List[Optional[Dict[str, Any]]] = []
    try:
        for i, page in enumerate(doc, start=1):
            if wanted is not None and i not in wanted:
                out.append(None)
                continue
            tables: List[Dict[str, Any]] = []
            if with_tables:
                try:
                    for t in page.find_tables().tables:
                        tables.append({"bbox": [float(x) for x in t.bbox], "rows": t.extract()})
                except Exception:
                    tables = []
            # UNROTATED size. Text coordinates are in the page's own space, and
            # this set's sheets are rotated 270: page.rect reports 2592x1728
            # while the blocks run to y=2501. Using the rotated size put the
            # title block outside every edge strip on S-001.00.
            box = page.cropbox
            out.append(layout_from_dict(
                page.get_text("dict"), width=box.width, height=box.height,
                page_number=i, tables=tables))
    finally:
        doc.close()
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


def notes_from_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Numbered notes, split where the numbers are, under the heading above
    them. No length cap on a note's text: a long note is a long chunk, never a
    truncated one."""
    notes: List[Dict[str, Any]] = []
    heading = None
    for b in blocks:
        kind = classify_block(b["text"])
        if kind == "heading":
            heading = b["text"].strip().rstrip(":")
            continue
        if kind != "notes":
            continue
        current = None
        for line in b["lines"]:
            only = _NOTE_NUM_ONLY.match(line)
            inline = _NOTE_NUM_INLINE.match(line)
            if only:
                current = {"number": only.group(1), "text": "", "heading": heading}
                notes.append(current)
            elif inline:
                current = {"number": inline.group(1), "text": inline.group(2), "heading": heading}
                notes.append(current)
            elif current is not None:
                current["text"] = (current["text"] + " " + line).strip()
    return [n for n in notes if n["text"]]


def legend_from_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for b in blocks:
        if classify_block(b["text"]) == "legend":
            for line in b["lines"][1:]:
                if line.strip():
                    out.append({"symbol": "", "meaning": line.strip()[:200]})
    return out[:80]


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


def count_tags(layout: Dict[str, Any], vocab: FrozenSet[str]) -> List[Dict[str, Any]]:
    """How often each tag is PRINTED AS A LABEL on this sheet.

    Only short blocks count — a tag on a plan is a label on its own. The word
    'PTAC' inside a window-area calculation, which is where it appears on this
    set's floor plans, is not a PTAC tag and is not counted. This is a count of
    labels, never a schedule total, and it says so in its source."""
    counts: Counter = Counter()
    for b in layout.get("blocks") or []:
        if len(b["text"]) > LABEL_MAX_CHARS:
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
    text_blocks = [{"kind": classify_block(b["text"]), "text": b["text"]} for b in blocks
                   if classify_block(b["text"]) not in ("notes", "legend", "heading")]
    return {
        "schedules": schedules_from_tables(layout.get("tables") or [],
                                           layout.get("width") or 0, layout.get("height") or 0),
        "notes": notes_from_blocks(blocks),
        "legend": legend_from_blocks(blocks),
        "callouts": callouts_from_text(text),
        "elements": stated_quantities(text),
        "dimensions": dimensions_from_text(text),
        "dimensions_unverified": list(layout.get("fractions_unverified") or []),
        "materials": material_lines(blocks),
        "tag_counts": count_tags(layout, tag_vocab),
        "text_blocks": text_blocks,
    }


__all__ = [
    "normalize_glyphs", "split_stacked_fraction", "rebuild_line", "layout_from_dict",
    "page_layouts", "SHEET_ID_RE", "sheet_ids", "title_region", "validate_sheet_number",
    "headings", "classify_block", "notes_from_blocks", "legend_from_blocks",
    "callouts_from_text", "stated_quantities", "dimensions_from_text", "material_lines",
    "schedules_from_tables", "SEED_TAGS", "TAG_SOURCE", "tag_vocabulary", "count_tags",
    "fields_from_layout",
]
