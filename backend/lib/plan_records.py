"""Typed records: one row per thing a sheet says, not one blob per section.

WHY THIS REPLACES CHUNKS
========================

`document_page_chunks` stores STRINGS. A question about "AC units" finds
M-200.00 only if the letters line up, and every fix for that has widened the
match — typo tolerance, AC->PTAC synonyms, head-noun fallback, plural stems,
chunk-type ranking. None of it generalises: the next project says "split
system", "fan coil", "RTU", and it starts over.

A record stores what the sheet SAYS, with how we came to know it. Retrieval can
then rank on evidence before similarity, and an answer can point at the region
of the sheet it came from.

THE FOUR RULES THE SHAPE ENFORCES
=================================

1. CITATION. `quote` is the exact printed string and `quote_span` locates it in
   the page's raw text. A record with neither is not quotable.

2. LABEL IS NOT QUOTE. Words the vision model supplied for a mark it could not
   read live in `label`, never in `quote`. They widen what a search finds; they
   are never what a reader is shown. On this project PACKAGE TERMINAL AIR
   CONDITIONER and KICKER came from the same place, and nothing in the text
   distinguishes them.

3. TIER IS THE EXTRACTION PATH, never a model's opinion of itself. There is no
   confidence number anywhere in this module.

4. PROVENANCE TO THE REGION. `bbox` is where on the sheet, in the page's own
   coordinates, so an answer can say where to look on a 36-inch drawing.

   KNOWN GAP: notes and callouts carry no bbox today. They come back from the
   VLM sections as text with no coordinates, and the page's line boxes are not
   matched to them. Those records store null rather than the page corner or
   the whole page — a box that says "somewhere on this sheet" is worse than no
   box, because it renders as a location and points at nothing. The next
   extraction pass closes it by matching each note line to the line_bboxes
   layout_from_dict already produces.

WHAT IS NOT HERE
================

`approval_status`. It is not printed on any sheet, and it changes without the
drawing changing — a P filing pending today is approved next month over a
byte-identical PDF. `filing_id` is stored and dob_logs is the join.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from lib.plan_extract import (
    TIER_OCR_FREEFORM, TIER_OCR_GRID, TIER_SCHEDULE_CELL, TIER_TAG_LEGEND,
    TIER_TEXT_LAYER, TIER_VISION, strip_boilerplate,
)

RECORD_VERSION = 1

# Ranked best first. Retrieval ranks on this before similarity, and an answer
# never cites a lower tier when a higher one exists for the same attribute on
# the same sheet.
TIER_ORDER = (TIER_SCHEDULE_CELL, TIER_OCR_GRID, TIER_TAG_LEGEND,
              TIER_TEXT_LAYER, TIER_OCR_FREEFORM, TIER_VISION)

RECORD_TYPES = ("schedule", "element", "note", "legend_entry", "callout",
                "dimension", "tag", "text")

# A cell that identifies the row, and one that says how many. Everything else
# is data the answer does not lead with.
_ROLE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("quantity", r"^(qty|quantity|count|no\.?|number|total)$"),
    ("identifier", r"^(unit\s*no\.?|unit|mark|tag|type|symbol|designation|item)$"),
    ("make", r"^(make|manufacturer|mfr)$"),
    ("model", r"^(model|model\s*no\.?|cat\.?\s*no\.?)$"),
    ("size", r"^(size|dimensions?|nk\.?\s*size|panel\s*size)$"),
    ("remarks", r"^(remarks?|notes?)$"),
)


def column_role(header: str) -> Optional[str]:
    """What a schedule column IS, from its printed header. Nothing inferred
    from the cells: a column of numbers is not a quantity column."""
    h = re.sub(r"\s+", " ", (header or "").strip().lower())
    for role, pat in _ROLE_PATTERNS:
        if re.match(pat, h):
            return role
    if "qty" in h or "quantity" in h:
        return "quantity"
    return None


def tier_rank(tier: Optional[str]) -> int:
    """Lower is better. An untiered record sorts last and is not a value."""
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)


def better_tier(a: Optional[str], b: Optional[str]) -> Optional[str]:
    return a if tier_rank(a) <= tier_rank(b) else b


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _span(haystack: str, needle: str) -> Optional[List[int]]:
    """Where the quote sits in the page's raw text, or None when it does not.

    A quote the page does not contain is the thing this whole layer exists to
    refuse, so the span is not guessed at."""
    if not haystack or not needle:
        return None
    i = haystack.find(needle)
    if i < 0:
        flat_h = re.sub(r"\s+", " ", haystack)
        flat_n = re.sub(r"\s+", " ", needle)
        i = flat_h.find(flat_n)
        return [i, i + len(flat_n)] if i >= 0 else None
    return [i, i + len(needle)]


def _bbox(v: Any) -> Optional[List[float]]:
    try:
        box = [float(x) for x in (v or [])]
    except (TypeError, ValueError):
        return None
    return box if len(box) == 4 and any(box) else None


# A count is only as strong as what it rests on, and `count_basis` names that.
# `glyph_match` sits with `tag_legend` because both are an occurrence counted
# on the sheet itself — one by the mark's letters, one by the symbol's strokes.
BASIS_TIERS = {
    "schedule_qty": TIER_SCHEDULE_CELL,
    "ocr_schedule_qty": TIER_OCR_GRID,
    "tag_occurrences": TIER_TAG_LEGEND,
    "glyph_match": TIER_TAG_LEGEND,
    TIER_VISION: TIER_VISION,
}

# ── TIER FOLLOWS SOURCE, ALWAYS ────────────────────────────────────────────
#
# Found in the 2026-09-17 corpus: M-200.00 carried `PTAC-1 count 21` TWICE —
# once at ocr_grid_cell from the OCR'd grid, and once at SCHEDULE_CELL, the
# strongest tier in the system, derived from a schedule the VISION MODEL read
# off the image. `elements_from_evidence` mapped every non-ocr_grid source to
# `schedule_qty`, so a number a model saw in a picture arrived wearing the
# badge of a cell the text layer handed over. `best_per_attribute` would then
# have preferred the vision copy over the real one.
#
# The number happened to be right. That is not the point: it is the same
# machinery that produced 41, and nothing downstream could tell.
#
# So each source declares the BEST tier it may ever claim. A source may sit
# lower — a text-layer line is text_layer, not tag_legend — but never higher.
# `emit` enforces it rather than trusting every call site to get it right,
# because the call site is exactly what got it wrong.
SOURCE_FLOOR = {
    "table_finder": TIER_SCHEDULE_CELL,
    "ocr_grid": TIER_OCR_GRID,
    # A mark paired to its legend, or a symbol counted by its strokes. Both are
    # an occurrence on the sheet itself, neither is a printed value.
    "glyph_match": TIER_TAG_LEGEND,
    "text_layer": TIER_TAG_LEGEND,
    # The floor and the ceiling. Nothing a model read off an image may outrank
    # anything a person could check against the page.
    "vision": TIER_VISION,
}

# What produced an element's count, hence what its record may claim.
BASIS_SOURCES = {
    "schedule_qty": "table_finder",
    "ocr_schedule_qty": "ocr_grid",
    "tag_occurrences": "text_layer",
    "glyph_match": "glyph_match",
    TIER_VISION: "vision",
}


def _element_tier(basis: Optional[str]) -> str:
    return BASIS_TIERS.get(basis or "", TIER_TEXT_LAYER)


def _element_source(basis: Optional[str]) -> str:
    return BASIS_SOURCES.get(basis or "", "text_layer")


def tier_for_source(tier: Optional[str], source: Optional[str]) -> str:
    """The tier a record may actually carry, given where it came from.

    Never raises and never silently improves anything: a tier that outranks
    its source is pulled DOWN to what the source can support."""
    floor = SOURCE_FLOOR.get(source or "")
    if floor is None:
        return tier or TIER_TEXT_LAYER
    if tier_rank(tier) < tier_rank(floor):
        return floor
    return tier or floor


def build_records(fields: Dict[str, Any], *, page: Dict[str, Any],
                  raw_text: str = "", boilerplate=frozenset()) -> List[Dict[str, Any]]:
    """Every record one page yields. Pure: no database, no network.

    `page` carries what the whole sheet knows — sheet_number, sheet_title,
    page_number, discipline, floors, file_name, filing_id, issued_date,
    document_type, page_image_ref — and every record repeats it, so a search
    can filter without a join.
    """
    out: List[Dict[str, Any]] = []
    notes_from_vision = (fields.get("notes_source") == "vision")

    def emit(record_type: str, ordinal: int, quote: str, payload: Dict[str, Any],
             tier: str, source: str, bbox=None, label: str = "",
             verified: Optional[bool] = None, subject_terms=None):
        quote = strip_boilerplate(_clean(quote), boilerplate).strip()
        if not quote and not label:
            return
        # A tier that outranks its source is pulled down to what the source
        # supports. Enforced here rather than trusted at each call site.
        tier = tier_for_source(tier, source)
        rec = dict(page)
        rec.update({
            "record_type": record_type,
            "ordinal": ordinal,
            "quote": quote,
            "quote_span": _span(raw_text, quote) if source != "vision" else None,
            # NEVER quoted. See rule 2.
            "label": _clean(label) or None,
            "tier": tier,
            "source": source,
            "verified": verified,
            "bbox": _bbox(bbox),
            "payload": payload,
            "subject_terms": subject_terms or [],
            "record_version": RECORD_VERSION,
        })
        out.append(rec)

    # ── schedules ────────────────────────────────────────────────────────
    for i, s in enumerate(fields.get("schedules") or []):
        via_vision = (s.get("source") == "vision")
        via_ocr = (s.get("source") == "ocr_grid")
        cols = [str(c or "") for c in (s.get("columns") or [])]
        payload = dict(s, columns=[{"header": c, "role": column_role(c)} for c in cols])
        lines = [s.get("name") or f"Schedule {i + 1}"]
        if cols:
            lines.append(" | ".join(cols))
        lines += [" | ".join(str(c or "") for c in r) for r in (s.get("rows") or [])]
        # An OCR'd grid is NOT quotable against the page text — the page has no
        # text there, which is why it was OCR'd at all. `_span` returns None
        # for it; `source` says where it came from so nothing has to infer it.
        tier = (TIER_VISION if via_vision
                else TIER_OCR_GRID if via_ocr else TIER_SCHEDULE_CELL)
        emit("schedule", i, "\n".join(lines), payload, tier,
             "vision" if via_vision else "ocr_grid" if via_ocr else "table_finder",
             bbox=s.get("bbox"), verified=not (via_vision or via_ocr),
             subject_terms=[_clean(s.get("name"))] if s.get("name") else [])

    # ── notes ────────────────────────────────────────────────────────────
    for i, n in enumerate(fields.get("notes") or []):
        text = (f"{n['number']}. " if n.get("number") else "") + _clean(n.get("text"))
        emit("note", i, text, n,
             TIER_VISION if notes_from_vision else TIER_TEXT_LAYER,
             "vision" if notes_from_vision else "text_layer",
             bbox=n.get("bbox"), verified=not notes_from_vision)

    # ── legend entries ───────────────────────────────────────────────────
    for i, e in enumerate(fields.get("legend") or []):
        sym, mean = _clean(e.get("symbol")), _clean(e.get("meaning"))
        label = _clean(e.get("label"))
        # The tier the extractor already decided, or derived the same way.
        tier = e.get("tier") or (TIER_VISION if label and not mean else TIER_TAG_LEGEND)
        quote = " = ".join(x for x in (sym, mean) if x) if (sym or mean) else ""
        emit("legend_entry", i, quote, e, tier,
             "vision" if tier == TIER_VISION else "text_layer",
             bbox=e.get("bbox"), label=label, verified=e.get("verified"),
             subject_terms=[x for x in (sym, mean) if x])

    # ── elements ─────────────────────────────────────────────────────────
    for i, el in enumerate(fields.get("elements") or []):
        basis = el.get("count_basis")
        name = _clean(el.get("name"))
        # An unpaired mark is named by the mark. The sheet's nearby words
        # travel as a description and are never rendered as a meaning.
        desc = _clean(el.get("described_by"))
        quote = " — ".join(x for x in (
            name,
            f"count {el['count_if_stated']}" if el.get("count_if_stated") is not None else "",
            _clean(el.get("location_hint"))) if x)
        # The SOURCE follows the basis too. An element counted off an OCR'd
        # grid is not a text-layer fact, and one counted off a picture is not
        # a schedule cell — which is exactly what M-200.00 shipped.
        emit("element", i, quote, el, _element_tier(basis),
             _element_source(basis),
             bbox=el.get("bbox"), verified=(basis != TIER_VISION),
             subject_terms=[x for x in (name, _clean(el.get("tag")), desc) if x])

    # ── callouts, tags, dimensions, leftover text ────────────────────────
    for i, c in enumerate(fields.get("callouts") or []):
        quote = " ".join(x for x in (_clean(c.get("text")), _clean(c.get("detail_number")),
                                     _clean(c.get("target_sheet"))) if x)
        emit("callout", i, quote, c, TIER_TEXT_LAYER, "text_layer", verified=True)

    for i, t in enumerate(fields.get("tag_counts") or []):
        emit("tag", i, f"{t.get('tag')} x{t.get('count')}", t,
             TIER_TAG_LEGEND, "text_layer", verified=True,
             subject_terms=[_clean(t.get("tag"))])

    for i, d in enumerate(fields.get("dimensions") or []):
        emit("dimension", i, _clean(d), {"value_text": _clean(d)},
             TIER_TEXT_LAYER, "text_layer", verified=True)
    for i, m in enumerate(fields.get("materials") or []):
        emit("dimension", 1000 + i, _clean(m), {"value_text": _clean(m), "material": True},
             TIER_TEXT_LAYER, "text_layer", verified=True)
    # Kept unverified and separate: a fraction piece with nothing to say which
    # fraction it belongs to is not a dimension, it is a digit.
    for i, u in enumerate(fields.get("dimensions_unverified") or []):
        emit("dimension", 2000 + i, _clean(u), {"value_text": _clean(u), "unverified": True},
             TIER_TEXT_LAYER, "text_layer", verified=False)

    for i, tb in enumerate(fields.get("text_blocks") or []):
        emit("text", i, _clean(tb.get("text")), {"kind": tb.get("kind")},
             TIER_TEXT_LAYER, "text_layer", bbox=tb.get("bbox"), verified=True)

    return out


def page_authority(raw_text: str, title_text: str = "", file_name: str = ""
                   ) -> Dict[str, Any]:
    """The sheet's filing, its issue date and the type derived from them.

    Read from the TITLE BLOCK where there is one, falling back to the page —
    the filing number is printed in the title block and nowhere else, but a
    page whose title strip did not extract still has it in its text."""
    from lib import plan_text as pt
    hay = title_text or raw_text or ""
    filing = pt.filing_id(hay) or pt.filing_id(raw_text or "")
    return {
        "filing_id": filing,
        "issued_date": pt.issue_date(hay) or pt.issue_date(raw_text or ""),
        "document_type": pt.document_type(filing, file_name),
    }


__all__ = ["build_records", "page_authority", "column_role", "tier_rank",
           "better_tier", "TIER_ORDER", "RECORD_TYPES", "RECORD_VERSION",
           "BASIS_TIERS", "BASIS_SOURCES", "SOURCE_FLOOR", "tier_for_source"]
