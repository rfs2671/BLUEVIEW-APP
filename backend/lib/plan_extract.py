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
}


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

    sheet_number, sn_flag = pt.validate_sheet_number(tb.get("sheet_number"), title_ids, page_ids)
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
        "vlm_calls": 1,
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
# Answers from chunks, with no vision model
# ══════════════════════════════════════════════════════════════════════════

def _stem(term: str) -> str:
    t = (term or "").strip().lower()
    if len(t) > 3 and t.endswith("es"):
        return t[:-2]
    if len(t) > 3 and t.endswith("s"):
        return t[:-1]
    return t


def _matches(text: str, terms: List[str]) -> bool:
    low = (text or "").lower()
    stems = [_stem(t) for t in terms if t]
    return bool(stems) and all(s in low for s in stems)


_QTY_HEADERS = ("qty", "quantity", "count", "no.", "no", "number", "#", "total")


def _qty_column(columns: List[str]) -> Optional[int]:
    for i, c in enumerate(columns or []):
        h = (c or "").strip().lower()
        if h in _QTY_HEADERS or "qty" in h or "quantity" in h:
            return i
    return None


def answer_count(chunks: List[Dict[str, Any]], terms: List[str]) -> List[Dict[str, Any]]:
    """Counts that are PRINTED, with the sheet they are printed on.

    Three sources, in order of how much they can be trusted:
      elements  — a quantity printed on the sheet and verified against its text
      schedule_qty  — a schedule with a quantity column, summed over matching rows
      schedule_rows — a schedule with no quantity column: the number of rows it
                      lists, reported AS rows, because three pile types is not
                      three piles
    An element count the page text does not contain is never returned."""
    out: List[Dict[str, Any]] = []
    for ch in chunks:
        sheet = ch.get("sheet_number")
        kind = ch.get("chunk_type")
        if kind == "elements":
            for el in ch.get("payload") or []:
                if (_matches(el.get("name"), terms)
                        and el.get("count_if_stated") is not None
                        and el.get("count_verified") is True):
                    out.append({"sheet": sheet, "count": el["count_if_stated"],
                                "source": "elements", "name": el.get("name"),
                                "where": el.get("location_hint")})
        elif kind == "schedule":
            s = ch.get("payload") or {}
            cols = s.get("columns") or []
            rows = s.get("rows") or []
            # The NAME decides. A table the finder could not name ('TABLE') whose
            # header cells mention 'W2' is not a schedule of W2s.
            name = s.get("name") or ""
            named_for_it = name.upper() != "TABLE" and _matches(name, terms)
            matched = rows if named_for_it else [r for r in rows if _matches(" ".join(r), terms)]
            if not matched:
                continue
            # A ROW COUNT IS ONLY A COUNT IN A SCHEDULE OF THAT THING. Measured
            # on S-001.00: "how many piles" matched one row of SPECIAL
            # INSPECTION CATEGORIES and answered "lists 1 row". A quantity
            # column can still be summed from any table; a bare row count
            # needs the table to be named for the thing.
            if not named_for_it and _qty_column(cols) is None:
                continue
            q = _qty_column(cols)
            if q is not None:
                total = 0
                counted = 0
                for r in matched:
                    if q < len(r) and re.fullmatch(r"\s*\d{1,6}\s*", r[q] or ""):
                        total += int(r[q])
                        counted += 1
                if counted:
                    out.append({"sheet": sheet, "count": total, "source": "schedule_qty",
                                "name": s.get("name"), "rows": counted})
                    continue
            out.append({"sheet": sheet, "count": len(matched), "source": "schedule_rows",
                        "name": s.get("name")})
    return out


def answer_existence(chunks: List[Dict[str, Any]], terms: List[str]) -> List[Dict[str, Any]]:
    """Where the thing is mentioned, from notes, legend, elements, callouts and
    specs. Each hit names its sheet and carries the line that matched."""
    out: List[Dict[str, Any]] = []
    for ch in chunks:
        if ch.get("chunk_type") not in ("notes", "legend", "elements", "callouts", "specs",
                                        "schedule", "text"):
            continue
        for line in (ch.get("text") or "").splitlines():
            if _matches(line, terms):
                out.append({"sheet": ch.get("sheet_number"), "source": ch.get("chunk_type"),
                            "line": line.strip()[:200]})
                break
    return out


def format_count_answer(subject: str, hits: List[Dict[str, Any]]) -> Optional[str]:
    if not hits:
        return None
    label = (subject or "That").strip()
    label = label[:1].upper() + label[1:]
    lines = []
    for h in hits:
        where = f"{h['sheet'] or '?'}"
        if h["source"] == "schedule_rows":
            lines.append(f"{where}: {h.get('name') or 'schedule'} lists {h['count']} row(s)")
        elif h["source"] == "schedule_qty":
            lines.append(f"{where}: {h['count']} ({h.get('name') or 'schedule'}, qty column)")
        else:
            lines.append(f"{where}: {h['count']}" + (f" ({h['where']})" if h.get("where") else ""))
    return f"{label}:\n" + "\n".join(lines)


def format_existence_answer(subject: str, hits: List[Dict[str, Any]]) -> Optional[str]:
    if not hits:
        return None
    label = (subject or "That").strip()
    label = label[:1].upper() + label[1:]
    sheets = []
    for h in hits:
        if h["sheet"] and h["sheet"] not in sheets:
            sheets.append(h["sheet"])
    first = hits[0]
    return (f"Yes — {label.lower()} is on {', '.join(sheets[:4]) or 'the indexed drawings'}.\n"
            f"{first['sheet'] or '?'} ({first['source']}): {first['line']}")


# ══════════════════════════════════════════════════════════════════════════
# Which kind of answer a question wants
# ══════════════════════════════════════════════════════════════════════════
#
# Three of the seven acceptance questions are neither a count nor a yes/no:
# "pile type", "stucco thickness", "post gauge". They ask for an ATTRIBUTE of
# a thing, and on a drawing that attribute is printed on the same line as the
# thing — '18 GA STEEL POST', '7/8" STUCCO'. A literal search for both words
# fails ("thickness" is never printed next to the value), so the attribute word
# is dropped from the search terms and used instead to pick the line that
# carries a value of that shape.

_Q_COUNT = re.compile(r"\b(how many|how much|number of|count|total|quantity)\b", re.I)
_Q_EXISTS = re.compile(
    r"^(is|are|was|were|does|do|did|has|have|any)\b|\b(is there|are there|any)\b", re.I)

ATTRIBUTE_PATTERNS: Dict[str, "re.Pattern[str]"] = {
    "gauge": re.compile(r"\b\d{1,2}\s*(?:GA|GAUGE|GA\.)(?![A-Z])", re.I),
    "thickness": re.compile(
        r"(?:\d+\s+)?\d+(?:/\d+)?\s*(?:\"|”|''|IN\.?(?![A-Z])|INCH|MM(?![A-Z]))|\bTHICK", re.I),
    # No TIMBER: "STRUCTURAL LUMBER, TIMBER AND WOOD" is a material list.
    "type": re.compile(r"\bTYPE\b|\b(?:H-?PILE|HP\s*\d|PIPE PILE|HELICAL|PRECAST|"
                       r"DRILLED|AUGER|CAISSON|MICROPILE|MICRO-PILE)\b", re.I),
    "size": re.compile(r"\d+\s*(?:\"|”|'|MM)?\s*[xX×]\s*\d+|\b\d+\s*(?:\"|”|IN\b)", re.I),
    "height": re.compile(r"\d+'\s*-?\s*\d*\"?|\bHEIGHT\b|\bHT\.?\b", re.I),
    "spacing": re.compile(r"\b(?:O\.?C\.?|ON CENTER|@\s*\d+)", re.I),
    "rating": re.compile(r"\b\d\s*-?\s*(?:HR|HOUR)\b|\bRATED\b|\bUL\s*[A-Z]?\s*\d+", re.I),
}
_ATTRIBUTE_ALIASES = {
    "gauge": "gauge", "gage": "gauge", "ga": "gauge",
    "thickness": "thickness", "thick": "thickness",
    "type": "type", "types": "type", "kind": "type",
    "size": "size", "sizes": "size",
    "height": "height", "tall": "height",
    "spacing": "spacing", "spaced": "spacing",
    "rating": "rating", "rated": "rating",
}
_Q_STOP = {
    "how", "many", "much", "what", "whats", "which", "where", "is", "are", "was", "were",
    "the", "a", "an", "of", "on", "in", "at", "to", "for", "any", "there", "number",
    "count", "total", "quantity", "do", "does", "did", "we", "have", "has", "it", "its",
    "show", "me", "levelog", "plan", "plans", "drawing", "drawings", "sheet", "sheets",
    "please", "tell", "about", "they", "them", "this", "that", "and", "or", "be",
}


def question_kind(text: str) -> Tuple[Optional[str], Optional[str]]:
    """('count', None) | ('exists', None) | ('attribute', name) | (None, None)."""
    low = re.sub(r"^@?levelog\s*[:,-]?\s*", "", (text or "").strip().lower())
    if not low:
        return None, None
    if _Q_COUNT.search(low):
        return "count", None
    for w in re.findall(r"[a-z]+", low):
        if w in _ATTRIBUTE_ALIASES:
            return "attribute", _ATTRIBUTE_ALIASES[w]
    if _Q_EXISTS.search(low):
        return "exists", None
    return None, None


def question_terms(text: str, keywords: Optional[List[Any]] = None, limit: int = 2) -> List[str]:
    """The subject of the question as search words. Multi-word keywords are
    split, because "pile type" as one needle matches nothing."""
    words: List[str] = []
    for k in keywords or []:
        words.extend(re.findall(r"[a-z0-9]+", str(k).lower()))
    if not [w for w in words if w not in _Q_STOP and w not in _ATTRIBUTE_ALIASES]:
        words = re.findall(r"[a-z0-9]+", (text or "").lower())
    out: List[str] = []
    for w in words:
        if w in _Q_STOP or w in _ATTRIBUTE_ALIASES or w in out:
            continue
        # A mark like 'w1' or 'rd' is short and is the whole subject.
        if len(w) < 3 and not re.fullmatch(r"[a-z]{1,3}\d{1,2}[a-z]?|rd|fd|ad|co", w):
            continue
        out.append(w)
    return out[:limit]


_LINE_SOURCES = ("specs", "notes", "schedule", "elements", "legend", "callouts", "text")

# Another assembly's noun. A value next to one of these is ITS value: on
# A-100.00 'STUCCO FINISH 12" CONCRETE' gives 12" to the concrete, and on
# A-500.00 '...STUCCO FINISH BOARD 1 LAYERS OF 5/8" EXTERIOR DENS GLASS BOARD'
# gives 5/8" to the board. Neither is a stucco thickness.
_OTHER_ASSEMBLY = re.compile(
    r"\b(CONCRETE|GYP|GYPSUM|BOARDS?|STUDS?|INSUL\w*|BRICK|DECK\w*|PLYWOOD|SHEATHING|"
    r"BATT|EPS|GLASS|MEMBRANE|TRACK|JOISTS?|SLAB|CMU|BLOCK|LAYERS?)\b", re.I)
_NEAR_CHARS = 40


def _value_near_term(line: str, terms: List[str], rx: "re.Pattern[str]") -> bool:
    """True when a value of the attribute's shape sits within a few words of the
    thing asked about, with no other assembly between them or owning it."""
    low = line.lower()
    stems = [_stem(t) for t in terms if t]
    # (start, end-of-word) — the gap is measured from the END of the term's
    # word, so the term ('STUD') is never mistaken for another assembly.
    spans = []
    for s in stems:
        for m in re.finditer(re.escape(s), low):
            end = m.end()
            while end < len(low) and low[end].isalpha():
                end += 1
            spans.append((m.start(), end))
    if not spans:
        return False
    for m in rx.finditer(line):
        for start, end in spans:
            if end <= m.start():            # term, then value
                between = line[end:m.start()]
                owner = line[m.end():m.end() + 14].strip()
                if _OTHER_ASSEMBLY.match(owner):
                    continue                # '12" CONCRETE' — the concrete's
            elif m.end() <= start:          # value, then term
                between = line[m.end():start]
            else:
                between = ""
            if len(between) > _NEAR_CHARS or _OTHER_ASSEMBLY.search(between):
                continue
            return True
    return False


def answer_attribute(chunks: List[Dict[str, Any]], terms: List[str], attribute: str,
                     limit: int = 4) -> List[Dict[str, Any]]:
    """Lines that name the thing AND carry a value shaped like the attribute.

    A line that names the thing but carries no such value is NOT returned: a
    note that says "STUCCO SYSTEM PER SPEC" does not answer "stucco thickness",
    and returning it would read as an answer."""
    rx = ATTRIBUTE_PATTERNS.get(attribute)
    if rx is None or not terms:
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    order = {k: i for i, k in enumerate(_LINE_SOURCES)}
    for ch in sorted(chunks, key=lambda c: order.get(c.get("chunk_type"), 99)):
        if ch.get("chunk_type") not in _LINE_SOURCES:
            continue
        lines = [l.strip() for l in (ch.get("text") or "").splitlines()]
        for i, clean in enumerate(lines):
            if not clean or not _matches(clean, terms):
                continue
            # The value is often printed on the NEXT line of the same label —
            # '3 1/2" METAL STUD 16"' then 'O.C. 20 GAUGE MIN.' — so the line
            # and the one after it are read together. Same block only.
            # Only a line that is itself a spec (it carries a number) continues
            # onto the next: 'STUCCO FINISH' + '1 LAYERS OF 5/8"' is two
            # different layers, not one sentence.
            joined = (" ".join(l for l in lines[i:i + 2] if l)
                      if re.search(r"\d", clean) else clean)
            hit = clean if _value_near_term(clean, terms, rx) else (
                joined if _value_near_term(joined, terms, rx) else None)
            if not hit:
                continue
            key = re.sub(r"[^a-z0-9]+", " ", hit.lower()).strip()
            if any(key in k or k in key for k in seen):
                continue
            seen.add(key)
            out.append({"sheet": ch.get("sheet_number"), "source": ch.get("chunk_type"),
                        "line": hit[:200]})
            if len(out) >= limit:
                return out
    return out


def format_attribute_answer(subject: str, attribute: str,
                            hits: List[Dict[str, Any]]) -> Optional[str]:
    if not hits:
        return None
    label = f"{(subject or 'That').strip()} {attribute}".strip()
    label = label[:1].upper() + label[1:]
    return f"{label}:\n" + "\n".join(f"{h['sheet'] or '?'}: {h['line']}" for h in hits)


def format_not_stated(mentions: List[Dict[str, Any]]) -> str:
    """For a count nobody printed. The sheets that mention the thing are named,
    so "not stated" is still somewhere to look, and nothing is counted by eye."""
    sheets: List[str] = []
    for h in mentions:
        if h.get("sheet") and h["sheet"] not in sheets:
            sheets.append(h["sheet"])
    base = "Not stated on the indexed drawings."
    return base + (f" Mentioned on {', '.join(sheets[:4])}." if sheets else "")


TAG_SYNONYMS: Dict[str, FrozenSet[str]] = {
    "roof drain": frozenset({"RD"}), "floor drain": frozenset({"FD"}),
    "area drain": frozenset({"AD"}), "cleanout": frozenset({"CO", "FCO"}),
    "ptac": frozenset({"PTAC"}), "vent thru roof": frozenset({"VTR"}),
    "water heater": frozenset({"WH"}), "hose bibb": frozenset({"HB"}),
    "exhaust fan": frozenset({"EF"}), "smoke detector": frozenset({"SD"}),
}


def answer_tag_count(chunks: List[Dict[str, Any]], terms: List[str]) -> List[Dict[str, Any]]:
    """Label counts per sheet for the tag(s) the question names."""
    phrase = " ".join(_stem(t) for t in terms)
    cands = set()
    for k, v in TAG_SYNONYMS.items():
        if k in phrase:
            cands |= v
    for t in terms:
        cands.add(t.upper())
        cands.add(_stem(t).upper())
    out: List[Dict[str, Any]] = []
    for ch in chunks:
        if ch.get("chunk_type") != "tag_counts":
            continue
        for item in ch.get("payload") or []:
            if item.get("tag") in cands and item.get("count"):
                out.append({"sheet": ch.get("sheet_number"), "tag": item["tag"],
                            "count": int(item["count"]), "source": item.get("source")})
    return out


def format_tag_count_answer(hits: List[Dict[str, Any]]) -> Optional[str]:
    """'PTAC tag appears 24 times on A-100.00..A-201.00 (not a stated total).'

    Worded so it cannot be read as a schedule total: it is how many times the
    label is printed, and a unit shown on two plans is printed twice."""
    if not hits:
        return None
    total = sum(h["count"] for h in hits)
    tags = "/".join(sorted({h["tag"] for h in hits}))
    sheets = sorted({h["sheet"] or "?" for h in hits})
    if len(sheets) == 1:
        where = sheets[0]
    elif len(sheets) == 2:
        where = f"{sheets[0]} and {sheets[1]}"
    else:
        where = f"{sheets[0]}..{sheets[-1]}"
    times = "time" if total == 1 else "times"
    return f"{tags} tag appears {total} {times} on {where} (not a stated total)."


def answer_question(chunks: List[Dict[str, Any]], text: str,
                    keywords: Optional[List[Any]] = None) -> Optional[Dict[str, str]]:
    """The one dispatch both the WhatsApp handler and the local harness call.

    {"text", "outcome"}, or None when the text cannot answer it and the caller
    should go to the vision model (an attribute with no value line, or a
    question that is none of count / exists / attribute)."""
    kind, attribute = question_kind(text)
    if not kind or not chunks:
        return None
    terms = question_terms(text, keywords)
    if not terms:
        return None
    subject = " ".join(terms)
    if kind == "count":
        hits = answer_count(chunks, terms)
        if hits:
            return {"text": format_count_answer(subject, hits), "outcome": "chunk_count"}
        # Nothing printed. A label count is the next-best honest thing, and it
        # is worded as a label count, never as a total.
        tags = answer_tag_count(chunks, terms)
        if tags:
            return {"text": format_tag_count_answer(tags), "outcome": "chunk_tag_count"}
        return {"text": format_not_stated(answer_existence(chunks, terms)),
                "outcome": "chunk_count_not_stated"}
    if kind == "exists":
        hits = answer_existence(chunks, terms)
        if hits:
            return {"text": format_existence_answer(subject, hits), "outcome": "chunk_exists"}
        return {"text": "Not found on indexed drawings.", "outcome": "chunk_exists_not_found"}
    hits = answer_attribute(chunks, terms, attribute)
    if hits:
        return {"text": format_attribute_answer(subject, attribute, hits),
                "outcome": "chunk_attribute"}
    return None


__all__ = [
    "answer_question", "question_kind", "question_terms", "answer_attribute", "format_attribute_answer",
    "format_not_stated", "ATTRIBUTE_PATTERNS",
    "EXTRACTION_VERSION", "SECTIONS", "SECTION_MAX_TOKENS", "REPEAT_MIN_RUN",
    "VECTOR_TEXT_THRESHOLD", "detect_repetition", "parse_json_loose",
    "validate_section", "merge_sections", "verify_numbers", "number_in_text",
    "boilerplate_lines", "strip_boilerplate", "classify_text_source",
    "section_prompt", "extract_page", "legacy_fields", "embedding_text",
    "build_chunks", "answer_count", "answer_existence", "format_count_answer",
    "format_existence_answer",
]
