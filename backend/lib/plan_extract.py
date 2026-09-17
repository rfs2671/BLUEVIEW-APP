"""Structured extraction for one page of a construction drawing set.

WHY THIS REPLACES A SINGLE PROMPT
=================================

Index version 2 asked Qwen for ten labelled free-text sections in ONE call
capped at 1500 tokens, in this order:

    SHEET_ID, SHEET_TITLE, DISCIPLINE, FLOOR, SPACES_AND_ROOMS,
    DIMENSIONS, MATERIALS_AND_SPECS, CODE_REFS, DETAIL_AND_SECTION_REFS, NOTES

Diagnosed from the stored rows for project 6a5f63bc147407d3261df2c7: the 7B
model degenerates on DIMENSIONS — the same dimension string, over and over,
until max_tokens — and every section AFTER it comes back null. Materials,
code refs, detail refs and notes were empty on every row. The index did not
contain "stucco" or "18 GA" because the model never got that far down the
page.

That failure has three separate causes and this module answers each one:

  ONE RUNAWAY STARVED EVERYTHING AFTER IT. So each section is its own call
  with its own token budget. A loop in the schedules call costs the
  schedules, and the notes call that follows starts from zero.

  NOTHING DETECTED THE LOOP. So every raw response is checked for
  repetition before it is parsed, truncated at the start of the loop, and
  FLAGGED — never silently accepted as data, never allowed to burn the
  budget of a later field.

  THE MODEL WAS READING PIXELS FOR TEXT THE PDF ALREADY HAD. A CAD-exported
  sheet carries an exact text layer. The indexer extracted it on every page
  and used it only to detect spec pages. Now it goes into every prompt as
  the authoritative source for wording and numbers, and the model's job is
  STRUCTURE: which lines are a schedule, which are notes, what a legend
  symbol means.

NUMBERS ARE CHECKED, NOT TRUSTED
================================

A count the model produces is only a count if it is PRINTED on the sheet.
`count_if_stated` is verified against the text layer (or OCR text for a
scanned page); a number that appears nowhere in the page text is kept but
marked `count_verified: false`, and the answering code will not report it.
A vision model counting drain symbols by eye is exactly the guess this
pipeline exists to stop presenting as an answer.

THIS MODULE HAS NO DATABASE AND NO NETWORK
==========================================

The model call and the OCR call are injected. That is what lets the local
harness run the SAME extraction against a PDF on disk that production runs
during indexing, and what lets the tests drive a runaway section without an
API key.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Tuple

EXTRACTION_VERSION = 3

# Separate calls, run in this order. Order no longer matters for correctness
# — each call is isolated — but title_block runs first so a page whose later
# sections all fail still has a sheet number to be found by.
#
# THIS IS THE SCANNED-PAGE PATH. A vector page makes one call — see
# extract_vector_page — because its text layer already carries everything the
# other sections would transcribe.
#
# `specs` is split out of `elements`: on A-500.00 the elements call listed 129
# dimensions, hit its cap, and never reached materials. One list per budget.
SECTIONS: Tuple[str, ...] = ("title_block", "schedules", "notes", "elements", "specs")

SECTION_MAX_TOKENS: Dict[str, int] = {
    "title_block": 500,
    "schedules": 2000,
    "notes": 1600,
    "elements": 1000,
    "specs": 1200,
}

# Raw model output kept on the row for inspection. Capped because a loop that
# ran to max_tokens is thousands of identical characters nobody needs twice.
RAW_CAP = 16000

# The text layer sent into each prompt. A dense spec-heavy sheet can carry far
# more than this; the cap is reported on the row so a truncation is visible.
TEXT_LAYER_PROMPT_CAP = 12000

# From blueview-parser's vector-vs-scanned classifier (pdf_source_classifier):
# CAD-exported pages sit well above this, pixel-only scans well below it.
VECTOR_TEXT_THRESHOLD = 100

# Six identical consecutive units is a loop. Five is not — a sheet can list the
# same dimension or the same schedule value a handful of times legitimately,
# and a threshold that eats real repeats corrupts the data it protects.
REPEAT_MIN_RUN = 6

SHEET_TYPES: FrozenSet[str] = frozenset({
    "plan", "schedule", "detail", "notes", "elevation", "section", "legend",
    "cover", "other",
})


# ══════════════════════════════════════════════════════════════════════════
# Repetition
# ══════════════════════════════════════════════════════════════════════════

_UNIT_RE = re.compile(r"[^\n,;|]+[\n,;|]?")
# A 12-120 character block repeated at least REPEAT_MIN_RUN times in a row,
# for a loop with no separators to split on.
_CHAR_LOOP_RE = re.compile(r"(.{12,120}?)(?:\1){%d,}" % (REPEAT_MIN_RUN - 1), re.DOTALL)


def _norm_unit(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip(" \t\r\n,;|\"'")).lower()


def detect_repetition(text: str, min_run: int = REPEAT_MIN_RUN) -> Tuple[str, bool]:
    """Cut a degenerate loop at its first repeat. Returns (text, looped).

    Looks for a block of 1-6 units — a unit being a line or a comma, semicolon
    or pipe separated piece — repeated `min_run` or more times consecutively,
    and keeps exactly one copy of it. Falls back to a character-level search
    for loops that carry no separators at all.

    What survives is the text UP TO the loop, which is real extraction. What
    is cut is the loop, which is not.
    """
    if not text:
        return text, False

    spans = []
    for m in _UNIT_RE.finditer(text):
        u = _norm_unit(m.group())
        if u:
            spans.append((m.start(), m.end(), u))

    n = len(spans)
    for i in range(n):
        for k in range(1, 7):
            if i + k * min_run > n:
                break
            block = [spans[i + j][2] for j in range(k)]
            reps = 1
            while (i + (reps + 1) * k <= n
                   and [spans[i + reps * k + j][2] for j in range(k)] == block):
                reps += 1
            if reps >= min_run:
                cut = spans[i + k - 1][1]
                return text[:cut].rstrip(" ,;|\n"), True

    m = _CHAR_LOOP_RE.search(text[:RAW_CAP])
    if m:
        return text[:m.start() + len(m.group(1))], True
    return text, False


def _collapse_runs(items: List[Any], min_run: int = REPEAT_MIN_RUN) -> Tuple[List[Any], bool]:
    """Collapse a run of `min_run`+ identical consecutive list items to one."""
    out: List[Any] = []
    collapsed = False
    i = 0
    while i < len(items):
        j = i + 1
        key = json.dumps(items[i], sort_keys=True, default=str)
        while j < len(items) and json.dumps(items[j], sort_keys=True, default=str) == key:
            j += 1
        run = j - i
        if run >= min_run:
            out.append(items[i])
            collapsed = True
        else:
            out.extend(items[i:j])
        i = j
    return out, collapsed


# ══════════════════════════════════════════════════════════════════════════
# JSON that a truncated model response can still yield
# ══════════════════════════════════════════════════════════════════════════

def _balanced_end(t: str) -> Optional[int]:
    depth = 0
    in_str = esc = False
    for i, ch in enumerate(t):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _close_truncated(t: str) -> str:
    """Cut a response that ran out of tokens back to its last complete value.

    The cut is made at the last comma or closer outside a string, so a partial
    trailing element — a half-written dimension, a key with no value — is
    DROPPED rather than guessed at, and the open brackets are closed after it.
    """
    stack: List[str] = []
    in_str = esc = False
    last_safe: Optional[Tuple[int, List[str]]] = None
    for i, ch in enumerate(t):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            last_safe = (i + 1, list(stack))
        elif ch == ",":
            last_safe = (i, list(stack))
    if last_safe is None:
        return t
    idx, st = last_safe
    return t[:idx] + "".join(reversed(st))


def parse_json_loose(text: str) -> Optional[dict]:
    """A JSON object out of a model response, or None.

    Tolerates markdown fences, prose before or after the object, and a
    response truncated mid-array by max_tokens."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    start = t.find("{")
    if start < 0:
        return None
    t = t[start:]
    for candidate in (t, t[:_balanced_end(t) or len(t)], _close_truncated(t)):
        try:
            obj = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


# ══════════════════════════════════════════════════════════════════════════
# Schema: every field capped, every string checked for a loop
# ══════════════════════════════════════════════════════════════════════════

def _clean_str(v: Any, cap: int, flags: List[str], field: str) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        v = json.dumps(v, default=str)
    s = str(v).strip()
    if not s or s.lower() in ("null", "none", "n/a"):
        return None
    s, looped = detect_repetition(s)
    if looped:
        flags.append(f"{field}:repetition_truncated")
    if len(s) > cap:
        s = s[:cap].rstrip()
        flags.append(f"{field}:capped")
    return s or None


def _clean_int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        n = v
    elif isinstance(v, str) and re.fullmatch(r"\s*\d{1,6}\s*", v):
        n = int(v)
    else:
        return None
    return n if 0 <= n <= 100000 else None


def _as_list(v: Any) -> List[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _clean_list(v: Any, item_fn: Callable[[Any, List[str]], Any], max_items: int,
                flags: List[str], field: str) -> List[Any]:
    items = []
    for raw in _as_list(v):
        cleaned = item_fn(raw, flags)
        if cleaned not in (None, "", [], {}):
            items.append(cleaned)
    items, collapsed = _collapse_runs(items)
    if collapsed:
        flags.append(f"{field}:repetition_collapsed")
    if len(items) > max_items:
        items = items[:max_items]
        flags.append(f"{field}:list_capped")
    return items


def _str_item(cap: int, field: str):
    def fn(raw, flags):
        return _clean_str(raw, cap, flags, field)
    return fn


def _dict_item(spec: Dict[str, Tuple[str, int]], field: str):
    """spec maps key -> ("str", cap) | ("int", 0)."""
    def fn(raw, flags):
        if not isinstance(raw, dict):
            return None
        out = {}
        for key, (kind, cap) in spec.items():
            if kind == "int":
                out[key] = _clean_int(raw.get(key))
            else:
                out[key] = _clean_str(raw.get(key), cap, flags, f"{field}.{key}")
        return out if any(x is not None for x in out.values()) else None
    return fn


def _schedule_item(raw, flags):
    if not isinstance(raw, dict):
        return None
    name = _clean_str(raw.get("name"), 120, flags, "schedules.name")
    columns = _clean_list(raw.get("columns"), _str_item(80, "schedules.columns"),
                          30, flags, "schedules.columns")
    rows = []
    for r in _as_list(raw.get("rows")):
        cells = [(_clean_str(c, 160, flags, "schedules.cell") or "")
                 for c in _as_list(r)][:30]
        if any(cells):
            rows.append(cells)
    rows, collapsed = _collapse_runs(rows)
    if collapsed:
        flags.append("schedules.rows:repetition_collapsed")
    if len(rows) > 200:
        rows = rows[:200]
        flags.append("schedules.rows:list_capped")
    if not (name or columns or rows):
        return None
    return {"name": name, "columns": columns, "rows": rows}


def validate_section(section: str, obj: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Coerce one section's parsed JSON to the schema. Returns (fields, flags)."""
    flags: List[str] = []
    o = obj if isinstance(obj, dict) else {}

    if section == "title_block":
        sheet_type = _clean_str(o.get("sheet_type"), 20, flags, "sheet_type")
        if sheet_type:
            sheet_type = sheet_type.lower()
            if sheet_type not in SHEET_TYPES:
                flags.append(f"sheet_type:unknown_value:{sheet_type[:20]}")
                sheet_type = "other"
        return {
            "sheet_number": _clean_str(o.get("sheet_number"), 40, flags, "sheet_number"),
            "sheet_title": _clean_str(o.get("sheet_title"), 200, flags, "sheet_title"),
            "discipline": _clean_str(o.get("discipline"), 40, flags, "discipline"),
            "sheet_type": sheet_type,
            "floors": _clean_list(o.get("floors"), _str_item(40, "floors"), 20, flags, "floors"),
            "revision": _clean_str(o.get("revision"), 20, flags, "revision"),
            "revision_date": _clean_str(o.get("revision_date"), 40, flags, "revision_date"),
            "contents_summary": _clean_str(o.get("contents_summary"), 900, flags, "contents_summary"),
        }, flags

    if section == "schedules":
        return {
            "schedules": _clean_list(o.get("schedules"), _schedule_item, 12, flags, "schedules"),
        }, flags

    if section == "notes":
        return {
            "notes": _clean_list(o.get("notes"), _dict_item(
                {"number": ("str", 12), "text": ("str", 1200)}, "notes"), 150, flags, "notes"),
            "legend": _clean_list(o.get("legend"), _dict_item(
                {"symbol": ("str", 60), "meaning": ("str", 200)}, "legend"), 80, flags, "legend"),
            "callouts": _clean_list(o.get("callouts"), _dict_item(
                {"text": ("str", 200), "target_sheet": ("str", 40),
                 "detail_number": ("str", 20)}, "callouts"), 150, flags, "callouts"),
        }, flags

    if section == "elements":
        return {
            "elements": _clean_list(o.get("elements"), _dict_item(
                {"name": ("str", 120), "count_if_stated": ("int", 0),
                 "location_hint": ("str", 160)}, "elements"), 150, flags, "elements"),
            "dimensions": _clean_list(o.get("dimensions"), _str_item(80, "dimensions"),
                                      200, flags, "dimensions"),
            "materials": _clean_list(o.get("materials"), _str_item(200, "materials"),
                                     200, flags, "materials"),
        }, flags

    if section == "specs":
        return {
            "dimensions": _clean_list(o.get("dimensions"), _str_item(80, "dimensions"),
                                      200, flags, "dimensions"),
            "materials": _clean_list(o.get("materials"), _str_item(200, "materials"),
                                     200, flags, "materials"),
        }, flags

    raise ValueError(f"unknown section {section!r}")


EMPTY_FIELDS: Dict[str, Any] = {
    "sheet_number": None, "sheet_title": None, "discipline": None,
    "sheet_type": None, "floors": [], "revision": None, "revision_date": None,
    "contents_summary": None, "schedules": [], "notes": [], "legend": [],
    "callouts": [], "elements": [], "dimensions": [], "materials": [],
    # Vector pages only: fraction pieces that could not be rebuilt, labels
    # counted per tag, and the blocks that are neither notes nor legend.
    "dimensions_unverified": [], "tag_counts": [], "text_blocks": [],
    # "text" when notes came from the text layer, "vision" when the notes
    # fallback read them off the image, None when there are none.
    "notes_source": None,
    # '16 OF 31' from the title block: this sheet's place in its own set. Two
    # numbers claiming the same place are one sheet reissued.
    "sheet_position": None,
}


# THE SHEET SAYS WHAT A MARK MEANS, OR NOTHING DOES. The model reads the mark
# off the image and, where the sheet prints no expansion beside it, supplies
# one from what it knows. On 588 Boyland that produced 'KE 1 = KICKER 1' and
# 'TE 1 = THERMOSTATIC EXPANSION VALVE 1' alongside the correct 'KITCHEN
# EXHAUST' and 'TOILET EXHAUST', and two of those guesses were corroborated on
# a second sheet, because the same legend is misread the same way every time.
#
# This is the counting rule applied to words: extraction may report what is
# PRINTED and nothing else. A mark whose meaning is not on the page keeps its
# mark and loses its meaning — 'KE 1' is a true record, 'KICKER 1' is not.
#
# A page with no text layer cannot be checked against itself. There the model
# IS the reader, the entries are kept, and they are marked unverified, exactly
# as a schedule read off the image is.
LEGEND_CHECKABLE_MIN_CHARS = 400


def _legend_norm(t: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", (t or "").upper()).strip()


# HOW A RECORD CAME TO BE, WHICH IS THE ONLY CONFIDENCE THERE IS. Never a
# number, never the model's opinion of itself: the tier is the extraction path.
TIER_SCHEDULE_CELL = "schedule_cell"     # a detected grid, cells from the text layer
TIER_OCR_GRID = "ocr_grid_cell"          # cell rectangle from ruling lines, glyphs from OCR
TIER_TAG_LEGEND = "tag_legend"           # a mark paired to a legend entry on its sheet
TIER_TEXT_LAYER = "text_layer"           # a value printed in a note or a spec
TIER_OCR_FREEFORM = "ocr_freeform"       # OCR of a region with no grid behind it
TIER_VISION = "vision_read"              # read off the image; lowest, never a value

# ── WHY OCR GETS TWO TIERS AND NOT ONE ─────────────────────────────────────
#
# Measured on M-200.00, 2026-09-16, one engine, one page, one resolution:
#
#   whole-schedule crop @300 dpi   ->  PTH15.3K   14.000   13.700
#   cell rectangles from the grid  ->  PTH153K    14,000   13,700   (42/42)
#
# The comma read as a period is a thousand-fold error in a capacity, produced
# with nothing to signal it. More resolution did not fix it. Scoping the read
# to a cell the RULING LINES define fixed it completely.
#
# So what predicts whether an OCR'd number is right is not that OCR ran — it
# is whether a deterministic rectangle bounded the read. TIER_OCR_GRID sits
# directly under a text-layer schedule cell because its structure is exact and
# only its glyphs are probabilistic. TIER_OCR_FREEFORM sits above vision only,
# because there a transcription error has nothing to catch it.
EVIDENCE_TIERS = (TIER_SCHEDULE_CELL, TIER_OCR_GRID, TIER_TAG_LEGEND,
                  TIER_TEXT_LAYER, TIER_OCR_FREEFORM, TIER_VISION)


def constrain_legend_to_page(entries: List[Dict[str, Any]], page_text: str
                             ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(entries, flags). A meaning the page does not print stops being a
    meaning and becomes a LABEL.

    ── WHY THE WORDS ARE KEPT AND NOT QUOTED ──────────────────────────────
    #
    # The M-sheet legends are drawn as artwork: 'PACKAGE TERMINAL AIR
    # CONDITIONER' appears on NO page's text layer on this project, and neither
    # does 'KITCHEN EXHAUST'. Both came from the vision model, and so did
    # 'KICKER' and 'THERMOSTATIC EXPANSION VALVE'. Nothing in the text can tell
    # the true readings from the invented ones, which is why none of them may
    # be a meaning.
    #
    # Dropping them outright cost real recall: PTAC-1 became a bare mark on six
    # sheets and the words "air conditioner" left the project entirely, so a
    # question about AC units had nothing to match.
    #
    # So the words are kept as `label`, at TIER_VISION. A label WIDENS WHAT THE
    # SEARCH FINDS and never becomes what the reader is shown: the words in an
    # answer come from a text-layer fact or from the sheet's own printed text.
    # `build_chunks` keeps labels out of the chunk text for that reason, and
    # test_no_vision_label_reaches_an_answer holds the line."""
    entries = entries or []
    hay = _legend_norm(page_text)
    if len(hay) < LEGEND_CHECKABLE_MIN_CHARS:
        return ([dict(e, verified=False, tier=TIER_VISION) for e in entries],
                ([f"legend_unverifiable:{len(entries)}"] if entries else []))
    out, dropped = [], 0
    for e in entries:
        mean = (e.get("meaning") or "").strip()
        if mean and _legend_norm(mean) in hay:
            out.append(dict(e, verified=True, tier=TIER_TAG_LEGEND))
            continue
        if (e.get("symbol") or "").strip():
            out.append(dict(e, meaning="", label=mean, verified=True,
                            tier=TIER_VISION if mean else TIER_TAG_LEGEND))
        dropped += 1
    return out, ([f"legend_meaning_not_printed:{dropped}"] if dropped else [])


def merge_sections(sections: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Every field present, whichever sections succeeded."""
    out = json.loads(json.dumps(EMPTY_FIELDS))
    for fields in sections.values():
        for k, v in (fields or {}).items():
            if v not in (None, [], ""):
                out[k] = v
    return out


# ══════════════════════════════════════════════════════════════════════════
# Numbers: printed on the sheet, or not reported
# ══════════════════════════════════════════════════════════════════════════

def _norm_for_numbers(t: str) -> str:
    t = (t or "").replace("″", '"').replace("′", "'")
    t = t.replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", t).lower()


def number_in_text(num: Any, text_norm: str) -> bool:
    if num is None or not text_norm:
        return False
    return re.search(r"(?<![\d.])" + re.escape(str(num)) + r"(?![\d.])", text_norm) is not None


def verify_numbers(fields: Dict[str, Any], page_text: str) -> List[str]:
    """Mark every stated count and dimension as found in the page text or not.

    Mutates `fields` in place — each element gains `count_verified` — and
    returns page-level flags."""
    text_norm = _norm_for_numbers(page_text)
    compact = text_norm.replace(" ", "")
    flags: List[str] = []
    if not text_norm.strip():
        flags.append("numbers_unverifiable:no_page_text")
        for el in fields.get("elements") or []:
            el["count_verified"] = None
        return flags

    unverified_counts = 0
    for el in fields.get("elements") or []:
        c = el.get("count_if_stated")
        if c is None:
            el["count_verified"] = None
        else:
            ok = number_in_text(c, text_norm)
            el["count_verified"] = ok
            if not ok:
                unverified_counts += 1
    if unverified_counts:
        flags.append(f"counts_not_in_page_text:{unverified_counts}")

    unverified_dims = [d for d in fields.get("dimensions") or []
                       if _norm_for_numbers(d).replace(" ", "") not in compact]
    if unverified_dims:
        flags.append(f"dimensions_not_in_page_text:{len(unverified_dims)}")

    for sch in fields.get("schedules") or []:
        bad = 0
        for row in sch.get("rows") or []:
            for cell in row:
                if cell and re.search(r"\d", cell):
                    if _norm_for_numbers(cell).replace(" ", "") not in compact:
                        bad += 1
        sch["unverified_cells"] = bad
    return flags


# ══════════════════════════════════════════════════════════════════════════
# Title-block boilerplate
# ══════════════════════════════════════════════════════════════════════════

def _norm_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "")).strip().lower()


def boilerplate_lines(page_texts: List[str], min_share: float = 0.6,
                      min_pages: int = 3) -> FrozenSet[str]:
    """Lines printed on most pages of a file — the title block, the stamp, the
    engineer's name and address.

    WHY IT MATTERS: measured on a 17-page structural set, the word "GAUGE"
    appeared on every page because the engineering firm's name is Light Gauge
    Engineering. A literal search for "post gauge" would match all seventeen
    sheets, every time, for a reason that has nothing to do with posts.

    Excluded from SEARCH text only. The raw text on the row is untouched."""
    n = len(page_texts)
    if n < min_pages:
        return frozenset()
    counts: Counter = Counter()
    for t in page_texts:
        counts.update({_norm_line(l) for l in (t or "").splitlines() if len(_norm_line(l)) >= 3})
    need = max(min_pages, math.ceil(min_share * n))
    return frozenset(line for line, c in counts.items() if c >= need)


def strip_boilerplate(text: str, lines: FrozenSet[str]) -> str:
    if not lines or not text:
        return text or ""
    return "\n".join(l for l in text.splitlines() if _norm_line(l) not in lines)


def classify_text_source(page_text: str) -> str:
    return "vector" if len((page_text or "").strip()) >= VECTOR_TEXT_THRESHOLD else "sparse"


# ══════════════════════════════════════════════════════════════════════════
# Prompts
# ══════════════════════════════════════════════════════════════════════════

_COMMON = (
    "You are extracting structured data from ONE page of a New York City "
    "construction drawing set. Return ONLY a JSON object: no prose, no markdown "
    "fences.\n"
    "RULES:\n"
    "- Copy wording and numbers EXACTLY as printed. The TEXT LAYER below is "
    "authoritative. If a number is not in it, do not invent one: use null.\n"
    "- Never list the same item twice. If you notice you are repeating "
    "yourself, stop and close the JSON object.\n"
    "- Respect every maximum. Leave items out rather than exceed it.\n"
    "- Use null or [] for anything not on this page.\n"
)

_SECTION_SPEC = {
    "title_block": (
        "Return:\n"
        '{"sheet_number": str, "sheet_title": str, "discipline": str,\n'
        ' "sheet_type": one of plan|schedule|detail|notes|elevation|section|legend|cover|other,\n'
        ' "floors": [str] (max 20), "revision": str, "revision_date": str,\n'
        ' "contents_summary": str}\n'
        "contents_summary: 2 to 4 sentences describing what this sheet shows. "
        "Name the systems, elements, schedules and details on it, so a search for "
        "any of them finds this sheet. Do not describe the title block."
    ),
    "schedules": (
        "Return:\n"
        '{"schedules": [{"name": str, "columns": [str], "rows": [[str]]}]}\n'
        "Every table on the sheet, verbatim: door, window, pile, footing, beam, "
        "fixture, finish, equipment, wall type. Max 12 tables, 30 columns, 200 "
        "rows. One row per printed row. Cells copied exactly."
    ),
    "notes": (
        "Return:\n"
        '{"notes": [{"number": str, "text": str}],\n'
        ' "legend": [{"symbol": str, "meaning": str}],\n'
        ' "callouts": [{"text": str, "target_sheet": str, "detail_number": str}]}\n'
        "notes: general notes and keyed notes, full text, max 150. legend: symbol "
        "and abbreviation definitions, max 80. callouts: detail and section "
        "references pointing to another sheet, max 150."
    ),
    "elements": (
        "Return:\n"
        '{"elements": [{"name": str, "count_if_stated": int, "location_hint": str}]}\n'
        "elements: things a builder counts or locates — piles, roof drains, PTAC "
        "units, posts, chase walls, anchors, fixtures, openings. Max 150.\n"
        "count_if_stated: ONLY a quantity PRINTED on this sheet, in a schedule, a "
        "note, or a tag such as '(4) ROOF DRAINS'. NEVER count symbols yourself. "
        "null when no quantity is printed.\n"
        "location_hint: where on the sheet, e.g. 'foundation plan', 'pile schedule'."
    ),
    "specs": (
        "Return:\n"
        '{"materials": [str], "dimensions": [str]}\n'
        "materials FIRST: products, gauges, thicknesses, ratings, e.g. '7/8\" "
        "STUCCO', '18 GA STEEL POST', '2 HR RATED'. Each once, max 200.\n"
        "dimensions: each UNIQUE dimension value once, max 200."
    ),
}


def section_prompt(section: str, text_layer: str) -> str:
    text = (text_layer or "").strip()
    layer = text if text else "(no text layer on this page: read the image)"
    return (f"{_COMMON}\n{_SECTION_SPEC[section]}\n\n"
            f"TEXT LAYER (authoritative):\n<<<\n{layer}\n>>>")


# ══════════════════════════════════════════════════════════════════════════
# The page
# ══════════════════════════════════════════════════════════════════════════

VlmCall = Callable[[str, str, int], Awaitable[Tuple[str, Optional[str]]]]


async def extract_page(*, image_b64: str, page_text: str, vlm_call: VlmCall,
                       boilerplate: FrozenSet[str] = frozenset()) -> Dict[str, Any]:
    """Run each section as its own call. One section failing costs only itself.

    `vlm_call(image_b64, prompt, max_tokens)` returns (content, finish_reason).
    """
    text_for_prompt = strip_boilerplate(page_text or "", boilerplate)
    prompt_text_truncated = len(text_for_prompt) > TEXT_LAYER_PROMPT_CAP
    text_for_prompt = text_for_prompt[:TEXT_LAYER_PROMPT_CAP]

    sections: Dict[str, Dict[str, Any]] = {}
    flags: Dict[str, List[str]] = {}
    raw: Dict[str, str] = {}

    for name in SECTIONS:
        f: List[str] = []
        try:
            content, finish = await vlm_call(image_b64, section_prompt(name, text_for_prompt),
                                             SECTION_MAX_TOKENS[name])
        except Exception as e:
            sections[name] = {}
            flags[name] = [f"call_failed:{type(e).__name__}"]
            raw[name] = ""
            continue
        content = content or ""
        raw[name] = content[:RAW_CAP]
        if finish == "length":
            f.append("hit_max_tokens")
        cut, looped = detect_repetition(content)
        if looped:
            f.append("repetition_truncated")
        obj = parse_json_loose(cut)
        if obj is None:
            f.append("unparseable")
            sections[name] = {}
        else:
            clean, vflags = validate_section(name, obj)
            sections[name] = clean
            f.extend(vflags)
        flags[name] = f

    fields = merge_sections(sections)
    # A COUNT WITH NO BASIS IS WHAT WE REMOVED EVERYWHERE ELSE. On a scanned
    # page the elements section IS the vision model — there is no text layer to
    # build them from — so they arrive with a count and no account of where it
    # came from. Thirteen of them reached production that way. They are stamped
    # here rather than left blank, so the tier can rank them last.
    for _el in fields.get("elements") or []:
        if isinstance(_el, dict) and not _el.get("count_basis"):
            _el["count_basis"] = TIER_VISION
    if fields.get("legend"):
        fields["legend"], lflags = constrain_legend_to_page(fields["legend"], page_text or "")
        flags.setdefault("notes", []).extend(lflags)
    number_flags = verify_numbers(fields, page_text or "")
    return {
        "fields": fields,
        "flags": flags,
        "number_flags": number_flags,
        "raw_vlm": raw,
        "prompt_text_chars": len(text_for_prompt),
        "prompt_text_truncated": prompt_text_truncated,
    }


# ══════════════════════════════════════════════════════════════════════════
# The vector page: text layer primary, one model call
# ══════════════════════════════════════════════════════════════════════════

TITLE_CALL_MAX_TOKENS = 600

# ── THE NOTES FALLBACK ────────────────────────────────────────────────────
#
# P-100.00's text layer is room labels and a title block — 1,393 characters on
# a 36x24 sheet — and its thirteen notes exist only as drawn geometry. The
# one-call path therefore found no notes on it. A PLAN sheet with no notes in
# its text and this little text per square inch gets the notes section run
# against the image as well. Measured on the Boyland set: every page that had
# a notes block in its text sat above this density, and P-100.00 sits at 1.61.
NOTES_FALLBACK_MAX_DENSITY = 2.0      # characters per square inch of sheet
_PT_PER_SQ_IN = 72.0 * 72.0


def text_density(layout: Dict[str, Any]) -> Optional[float]:
    area = (float(layout.get("width") or 0) * float(layout.get("height") or 0)) / _PT_PER_SQ_IN
    return len(layout.get("text") or "") / area if area else None


def needs_notes_fallback(fields: Dict[str, Any], layout: Dict[str, Any]) -> bool:
    """No notes in the text, and EITHER a thin plan sheet OR any table grid
    drawn with no text in it. A sheet whose schedules are drawn as shapes
    (M-200.00) draws the notes under them the same way."""
    from lib import plan_text as _pt
    if fields.get("notes"):
        return False
    if _pt.empty_table_grids(layout):
        return True
    density = text_density(layout)
    return (fields.get("sheet_type") == "plan"
            and density is not None and density < NOTES_FALLBACK_MAX_DENSITY)


def title_prompt(title_text: str, heading_text: str, ids: List[str]) -> str:
    """The one call a vector page makes. No text-layer cap to hit: it carries
    the title-block strip and the sheet's headings, not the notes."""
    return (
        "You are reading ONE page of a New York City construction drawing set. "
        "Return ONLY a JSON object: no prose, no markdown fences.\n"
        "Return:\n"
        '{"sheet_number": str, "sheet_title": str, "discipline": str,\n'
        ' "sheet_type": one of plan|schedule|detail|notes|elevation|section|legend|cover|other,\n'
        ' "floors": [str] (max 20), "revision": str, "revision_date": str,\n'
        ' "contents_summary": str}\n'
        "sheet_number: copy it from the title block. It is normally one of the SHEET "
        "IDS listed below. A number in a drawing list is NOT the sheet number.\n"
        "revision: the revision mark only, never a sheet id or a DOB job number.\n"
        "contents_summary: 2 to 4 sentences naming the systems, elements, schedules "
        "and details this sheet shows. Do not describe the title block.\n\n"
        f"SHEET IDS PRINTED IN THE TITLE BLOCK: {', '.join(ids) or '(none found)'}\n\n"
        f"TITLE BLOCK TEXT:\n<<<\n{title_text or '(none)'}\n>>>\n\n"
        f"HEADINGS ON THIS SHEET:\n<<<\n{heading_text or '(none)'}\n>>>"
    )


async def extract_vector_page(*, image_b64: str, layout: Dict[str, Any], vlm_call: VlmCall,
                              boilerplate: FrozenSet[str] = frozenset(),
                              tag_vocab: Optional[FrozenSet[str]] = None,
                              drawing_index: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Structure from the text layer; title, type and summary from one call.

    Same return shape as extract_page, so the writer and the harness treat the
    two paths alike."""
    from lib import plan_text as pt  # sibling, pure

    title_text = pt.title_region(layout)
    title_ids = pt.sheet_ids(title_text)
    page_ids = pt.sheet_ids(layout.get("text") or "")
    position = pt.sheet_position(title_text)
    flags: Dict[str, List[str]] = {"title_block": [], "text_layer": []}
    raw: Dict[str, str] = {"title_block": ""}
    tb: Dict[str, Any] = {}
    try:
        content, finish = await vlm_call(
            image_b64, title_prompt(title_text, pt.headings(layout), title_ids or page_ids[:12]),
            TITLE_CALL_MAX_TOKENS)
        content = content or ""
        raw["title_block"] = content[:RAW_CAP]
        if finish == "length":
            flags["title_block"].append("hit_max_tokens")
        cut, looped = detect_repetition(content)
        if looped:
            flags["title_block"].append("repetition_truncated")
        obj = parse_json_loose(cut)
        if obj is None:
            flags["title_block"].append("unparseable")
        else:
            tb, vflags = validate_section("title_block", obj)
            flags["title_block"].extend(vflags)
    except Exception as e:
        flags["title_block"].append(f"call_failed:{type(e).__name__}")

    sheet_number, sn_flag = pt.validate_sheet_number(
        tb.get("sheet_number"), title_ids, page_ids, drawing_index, position, title_text)
    if sn_flag:
        flags["title_block"].append(sn_flag)
    if tb.get("revision") and tb["revision"].upper() in {i.upper() for i in page_ids}:
        flags["title_block"].append("revision_was_a_sheet_id")
        tb["revision"] = None
    # A bare number equal to this sheet's place in the drawing list is that
    # place, not a revision. S-001.00 is number 2 in the ST list, and the model
    # returned revision "2" — the same digit it once read as the sheet number.
    rev = (tb.get("revision") or "").strip()
    if (rev.isdigit() and drawing_index and sheet_number
            and drawing_index.get(sheet_number) == int(rev)):
        flags["title_block"].append("revision_was_drawing_list_index")
        tb["revision"] = None

    text_fields = pt.fields_from_layout(layout, boilerplate, tag_vocab or pt.SEED_TAGS)
    fields = merge_sections({"title_block": tb})
    fields.update(text_fields)
    fields["sheet_number"] = sheet_number
    fields["sheet_position"] = list(position) if position else None
    fields["notes_source"] = "text" if fields.get("notes") else None

    calls = 1
    text_for_prompt = strip_boilerplate(layout.get("text") or "", boilerplate)[:TEXT_LAYER_PROMPT_CAP]

    async def _section_from_image(section: str, f: List[str]) -> Dict[str, Any]:
        """One section read from the page image. Its flags go on `f`."""
        try:
            content, finish = await vlm_call(image_b64, section_prompt(section, text_for_prompt),
                                             SECTION_MAX_TOKENS[section])
        except Exception as e:
            f.append(f"call_failed:{type(e).__name__}")
            return {}
        content = content or ""
        raw[section] = content[:RAW_CAP]
        if finish == "length":
            f.append("hit_max_tokens")
        cut, looped = detect_repetition(content)
        if looped:
            f.append("repetition_truncated")
        obj = parse_json_loose(cut)
        if obj is None:
            f.append("unparseable")
            return {}
        clean, vflags = validate_section(section, obj)
        f.extend(vflags)
        return clean

    # ── SCHEDULES DRAWN AS SHAPES ─────────────────────────────────────────
    #
    # M-200.00's ROOMS PTAC UNITS SCHEDULE (PTAC-1 x21, PTAC-2 x9, PTAC-3 x11)
    # and its fan, heater and diffuser schedules are ruled grids with no text
    # in any cell. More empty grids than schedules read from the text layer
    # means the schedules are in the image, so they are read from it. Each one
    # is marked source "vision": its numbers cannot be checked against text.
    grids = pt.empty_table_grids(layout)
    if grids and len(fields.get("schedules") or []) < grids:
        calls += 1
        f: List[str] = [f"empty_grids:{grids}"]
        clean = await _section_from_image("schedules", f)
        found = [dict(s, source="vision") for s in (clean.get("schedules") or [])]
        if found:
            fields["schedules"] = list(fields.get("schedules") or []) + found
        f.append(f"schedules_found:{len(found)}")
        flags["schedules_fallback"] = f

    if needs_notes_fallback(fields, layout):
        calls += 1
        density = text_density(layout)
        f = [f"density:{density:.2f}" if density is not None else "density:unknown"]
        if grids:
            f.append(f"empty_grids:{grids}")
        clean = await _section_from_image("notes", f)
        if clean.get("notes"):
            fields["notes"] = [dict(n, heading=None) for n in clean["notes"]]
            fields["notes_source"] = "vision"
        for k in ("legend", "callouts"):
            if clean.get(k) and not fields.get(k):
                fields[k] = clean[k]
        if fields.get("legend"):
            fields["legend"], lflags = constrain_legend_to_page(
                fields["legend"], layout.get("text") or "")
            f.extend(lflags)
        if clean or not any(x.startswith(("call_failed", "unparseable")) for x in f):
            f.append(f"notes_found:{len(clean.get('notes') or [])}")
        flags["notes_fallback"] = f

    number_flags: List[str] = []
    if text_fields["dimensions_unverified"]:
        number_flags.append(f"dimension_fragments_unverified:{len(text_fields['dimensions_unverified'])}")
    if layout.get("fractions_rebuilt"):
        flags["text_layer"].append(f"fractions_rebuilt:{layout['fractions_rebuilt']}")
    return {
        "fields": fields,
        "flags": flags,
        "number_flags": number_flags,
        "raw_vlm": raw,
        "prompt_text_chars": len(title_text),
        "prompt_text_truncated": False,
        "vlm_calls": calls,
    }


# ══════════════════════════════════════════════════════════════════════════
# Compatibility with index version 2 readers
# ══════════════════════════════════════════════════════════════════════════

_CODE_REF_RE = re.compile(
    r"\b(?:LL\s*\d+(?:/\d+)?|LOCAL\s+LAW\s+\d+|BC\s*\d{3,4}(?:\.\d+)*|IBC|"
    r"NFPA\s*\d+|ASTM\s*[A-Z]\s*\d+|UL\s*[A-Z]?\s*\d+)\b", re.IGNORECASE)
_KW_STOP = {"THE", "AND", "FOR", "PER", "WITH", "FROM", "THIS", "THAT", "ARE",
            "ALL", "SEE", "TYP", "NOT", "SHALL", "BE"}


def legacy_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """The v2 string fields, filled from the v3 structure.

    Thirteen functions read document_page_index today — retrieval, element
    search, the agent's sheet index, thumbnails. They read `materials`,
    `notes`, `summary` and friends as strings. Filling those from the new
    structure keeps every one of them working on a v3 row without a change."""
    notes_text = "\n".join(
        (f"{n['number']}. " if n.get("number") else "") + (n.get("text") or "")
        for n in fields.get("notes") or [])
    code_refs = sorted({m.group(0).upper() for m in _CODE_REF_RE.finditer(notes_text)})
    detail_refs = "; ".join(
        " ".join(x for x in (c.get("detail_number"), c.get("target_sheet"), c.get("text")) if x)
        for c in fields.get("callouts") or [])
    kw_source = " ".join(filter(None, [
        fields.get("sheet_title"),
        " ".join(e.get("name") or "" for e in fields.get("elements") or []),
        " ".join(s.get("name") or "" for s in fields.get("schedules") or []),
        " ".join(fields.get("materials") or []),
    ]))
    words = re.findall(r"[A-Za-z0-9\-]{3,}", kw_source.upper())
    keywords = sorted({w for w in words if w not in _KW_STOP})[:60]
    return {
        "sheet_number": fields.get("sheet_number"),
        "sheet_title": fields.get("sheet_title"),
        "discipline": fields.get("discipline"),
        "floor": ", ".join(fields.get("floors") or []) or None,
        "summary": fields.get("contents_summary") or "",
        "spaces": None,
        "dimensions": "; ".join(fields.get("dimensions") or []) or None,
        "materials": "; ".join(fields.get("materials") or []) or None,
        "code_refs": "; ".join(code_refs) or None,
        "detail_refs": detail_refs or None,
        "notes": notes_text or None,
        "keywords": keywords,
    }


def embedding_text(fields: Dict[str, Any]) -> str:
    parts = [fields.get("sheet_number"), fields.get("sheet_title"),
             fields.get("contents_summary")]
    parts += [e.get("name") for e in fields.get("elements") or []]
    parts += [s.get("name") for s in fields.get("schedules") or []]
    return "\n".join(p for p in parts if p)


# ══════════════════════════════════════════════════════════════════════════
# Chunks
# ══════════════════════════════════════════════════════════════════════════

NOTE_BLOCK_CHARS = 1500


def build_chunks(fields: Dict[str, Any], boilerplate: FrozenSet[str] = frozenset()
                 ) -> List[Dict[str, Any]]:
    """One chunk per schedule, per note block, per legend, per element list.

    A schedule embedded whole inside a page summary is one vector among many
    ideas on that page, and a pile schedule loses to the plan drawn around it.
    As its own chunk it is the closest thing in the index to "how many piles".
    """
    chunks: List[Dict[str, Any]] = []

    def add(kind, ordinal, text, payload):
        text = strip_boilerplate(text, boilerplate).strip()
        if text:
            chunks.append({"chunk_type": kind, "ordinal": ordinal,
                           "text": text, "payload": payload})

    for i, s in enumerate(fields.get("schedules") or []):
        lines = [s.get("name") or f"Schedule {i + 1}"]
        if s.get("columns"):
            lines.append(" | ".join(s["columns"]))
        lines += [" | ".join(r) for r in s.get("rows") or []]
        add("schedule", i, "\n".join(lines), s)

    block: List[Tuple[str, dict]] = []
    size = 0
    bi = 0
    for n in fields.get("notes") or []:
        line = (f"{n['number']}. " if n.get("number") else "") + (n.get("text") or "")
        if block and size + len(line) > NOTE_BLOCK_CHARS:
            add("notes", bi, "\n".join(l for l, _ in block), [x for _, x in block])
            bi += 1
            block, size = [], 0
        block.append((line, n))
        size += len(line)
    if block:
        add("notes", bi, "\n".join(l for l, _ in block), [x for _, x in block])

    if fields.get("legend"):
        add("legend", 0, "\n".join(f"{x.get('symbol') or ''} = {x.get('meaning') or ''}"
                                   for x in fields["legend"]), fields["legend"])
    if fields.get("callouts"):
        add("callouts", 0, "\n".join(
            " ".join(v for v in (c.get("text"), c.get("detail_number"), c.get("target_sheet")) if v)
            for c in fields["callouts"]), fields["callouts"])
    if fields.get("elements"):
        add("elements", 0, "\n".join(
            " — ".join(v for v in (
                e.get("name"),
                f"count {e['count_if_stated']}" if e.get("count_if_stated") is not None else None,
                e.get("location_hint")) if v)
            for e in fields["elements"]), fields["elements"])
    # Everything else the text layer said: plan labels, wall-type descriptions,
    # calculations. Grouped, never truncated, so a word anywhere on the sheet is
    # findable — "HELICAL PILES" on S-001.00 is a short block of its own.
    group: List[str] = []
    size = 0
    ti = 0
    for tb in fields.get("text_blocks") or []:
        t = (tb.get("text") or "").strip()
        if not t:
            continue
        if group and size + len(t) > NOTE_BLOCK_CHARS:
            add("text", ti, "\n".join(group), None)
            ti += 1
            group, size = [], 0
        group.append(t)
        size += len(t)
    if group:
        add("text", ti, "\n".join(group), None)
    if fields.get("tag_counts"):
        chunks.append({"chunk_type": "tag_counts", "ordinal": 0,
                       "text": "\n".join(f"{t['tag']} x{t['count']}" for t in fields["tag_counts"]),
                       "payload": fields["tag_counts"]})

    specs = list(fields.get("dimensions") or []) + list(fields.get("materials") or [])
    if specs:
        add("specs", 0, "\n".join(specs),
            {"dimensions": fields.get("dimensions") or [], "materials": fields.get("materials") or []})
    return chunks
# ══════════════════════════════════════════════════════════════════════════
# WHAT USED TO BE HERE
# ══════════════════════════════════════════════════════════════════════════
#
# The keyword matcher: question_kind, QUERY_SYNONYMS, ATTRIBUTE_PATTERNS,
# _one_edit_apart, question_terms, answer_count / _existence / _attribute /
# _tag_count / _named_schedule, their formatters, and answer_question over
# them. About 790 lines.
#
# It decided the SHAPE of an answer and whether to look at all, from the
# letters in the question. Every failure it had was answered by widening the
# match — typo tolerance, an AC->PTAC synonym table, a head-noun retry, plural
# stems, chunk-type ranking — and none of it generalised past the drafter it
# was tuned on. It is what produced `41 PTAC units`.
#
# Questions are now answered from typed records: lib/plan_search.py ranks them
# and server.gate_plan_answer refuses any number they cannot vouch for. The
# recorded eval scores that reader at 17 of 18 on the corpus this matcher
# built (eval/results/).
#
# What the deletion gave up, written down rather than forgotten:
# eval/migrated-from-the-matcher.md.



__all__ = [
    "EXTRACTION_VERSION", "SECTIONS", "SECTION_MAX_TOKENS", "REPEAT_MIN_RUN",
    "VECTOR_TEXT_THRESHOLD", "detect_repetition", "parse_json_loose",
    "validate_section", "merge_sections", "verify_numbers", "number_in_text",
    "constrain_legend_to_page", "EVIDENCE_TIERS", "TIER_SCHEDULE_CELL",
    "TIER_OCR_GRID", "TIER_TAG_LEGEND", "TIER_TEXT_LAYER", "TIER_OCR_FREEFORM",
    "TIER_VISION",
    "boilerplate_lines", "strip_boilerplate", "classify_text_source",
    "section_prompt", "extract_page", "extract_vector_page", "legacy_fields",
    "embedding_text", "build_chunks",
]
