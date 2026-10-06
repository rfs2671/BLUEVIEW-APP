"""A takeoff, as records: `record_type: "glyph"` rows in plan_records.

ONE ROW PER LOCATED SYMBOL, CITED TO THE MECHANICAL SHEET - the sheet that
prints the tag. The architectural sheet that said which apartment holds it
rides in `payload.arch`.

    tier          registered_glyph - assembled, never printed (plan_extract)
    label         the tag, snapped to the schedule's closed set ("EF-2")
    quote         the label as the sheet printed it ("EF-2(100)")
    unit          "4A", "non-unit:BIKE ROOM", or None when placement refused
    glyph_status  plan_tally's vocabulary: resolved / unread / contested /
                  unsupported_unit - whether the GLYPH named itself
    bbox          the label's box on the mechanical sheet
    payload       placement (placed / placed-non-unit / refused), reason,
                  symbol box and point, the arch sheet and the point on it,
                  method, fallback_reason, registration, how the units and
                  the door width were derived

The consumer is plan_search.glyph_tallies, behind the count-answer gate. It
reads tier, label, unit and glyph_status - and nothing here may say more than
the takeoff knew:

  - a unit whose region was refused (it held other than one tag, or was
    incomplete) gets an `unsupported_unit` row: a unit that produced no row
    would read as a unit with nothing in it;
  - a SHEET the takeoff could not run on gets one `unsupported_unit` row for
    the whole sheet (unit "sheet:<number>"), with the reason. A floor with
    no derivable units, a plan with no partner, a missing schedule - never
    a floor given its neighbour's answer.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from lib.plan_extract import TIER_REGISTERED_GLYPH
from lib import plan_tally as ptal

RECORD_TYPE = "glyph"
SOURCE = "plan_takeoff"
EMIT_VERSION = 1

#: the citation fields a row carries from its page (as _write_page_records)
CITE = ("project_id", "company_id", "file_id", "file_hash", "file_name",
        "page_id", "page_number", "sheet_number", "sheet_title", "discipline")


def _cite(page: Dict[str, Any]) -> Dict[str, Any]:
    return {k: page.get(k) for k in CITE}


def _box(b) -> Optional[List[float]]:
    return [float(v) for v in b] if b else None


def _pt(p) -> Optional[List[float]]:
    return [float(v) for v in p] if p else None


def _row(page, ordinal, *, label, quote, unit, glyph_status, bbox, payload):
    return {
        **_cite(page),
        "record_type": RECORD_TYPE,
        "ordinal": ordinal,
        "quote": quote or "",
        # the tag is drawn as outlines on these sheets: it is not in the
        # page's text, so there is no span to point at
        "quote_span": None,
        "label": label,
        "tier": TIER_REGISTERED_GLYPH,
        "source": SOURCE,
        "verified": False,
        "bbox": bbox,
        "unit": unit,
        "glyph_status": glyph_status,
        "payload": {**payload, "emit_version": EMIT_VERSION},
        "dimension_defect": None,
        "subject_terms": [label] if label else [],
    }


def sheet_refusal(page: Dict[str, Any], reason: str, *, pass_key: str,
                  family: Optional[str] = None, ordinal: int = 0) -> Dict[str, Any]:
    """One row saying the takeoff did not run on this sheet, and why."""
    return _row(page, ordinal, label=None, quote="",
                unit=f"sheet:{page.get('sheet_number') or page.get('page_id')}",
                glyph_status=ptal.UNSUPPORTED_UNIT, bbox=None,
                payload={"placement": None, "refusal": reason,
                         "pass_key": pass_key, "family": family})


def glyph_rows(result: Dict[str, Any], *, mech: Dict[str, Any],
               arch: Dict[str, Any], family: str, pass_key: str,
               units: Dict[str, Any], widest_door: Dict[str, Any]
               ) -> List[Dict[str, Any]]:
    """Every row one takeoff (one family, one floor pair) emits."""
    if result.get("refused"):
        return [sheet_refusal(mech, result["refused"], pass_key=pass_key,
                              family=family)]
    arch_ref = {k: arch.get(k) for k in ("page_id", "file_id", "file_hash",
                                         "file_name", "page_number",
                                         "sheet_number")}
    common = {
        "pass_key": pass_key, "family": family, "arch": arch_ref,
        "method": result.get("method"),
        "fallback_reason": result.get("fallback_reason"),
        "registration": {k: (result.get("registration") or {}).get(k)
                         for k in ("rms_in", "max_in", "anchors", "usable")},
        "units": {k: units.get(k) for k in ("tags", "method", "zero_units")},
        "widest_door_in": widest_door.get("inches"),
    }
    rows: List[Dict[str, Any]] = []
    for r in result.get("records") or []:
        rows.append(_row(
            mech, len(rows), label=r.get("tag"), quote=r.get("label_text"),
            unit=r.get("unit"), glyph_status=r.get("glyph_status") or ptal.UNREAD,
            bbox=_box(r.get("label_box")),
            payload={**common, "placement": r.get("placement"),
                     "reason": r.get("reason"), "how": r.get("how"),
                     "label_at": _pt(r.get("label_at")),
                     "symbol_at": _pt(r.get("symbol_at")),
                     "symbol_bbox": _box(r.get("symbol_bbox")),
                     "at_arch": _pt(r.get("at_arch"))}))
    for tag in result.get("refused_tags") or []:
        rows.append(_row(
            mech, len(rows), label=None, quote="", unit=tag,
            glyph_status=ptal.UNSUPPORTED_UNIT, bbox=None,
            payload={**common, "placement": None,
                     "refusal": f"{tag}: its region on {arch.get('sheet_number')} "
                                "was refused or incomplete"}))
    return rows


def refusal_rows(refused: Iterable, *, pass_key_prefix: str = "refusal"
                 ) -> List[Dict[str, Any]]:
    """[(page, reason)] -> one sheet refusal row each."""
    return [sheet_refusal(p, why, pass_key=f"{pass_key_prefix}|{p.get('sheet_number')}")
            for p, why in refused]
