"""WHAT A LOG DECLARES, AND WHAT A DECLARATION MAY NOT CONTAIN.

Fifteen legal log types are not fifteen designs. They are fifteen SCHEMAS
rendered by one engine: the data decides what appears, the design system decides
how. A schema is an ordered list of sections, each naming a PRIMITIVE, binding
to a dotted path in a record, and naming a FORMATTER from the closed set in
formatters.py.

── A DECLARATION MAY NOT CONTAIN A CALLABLE, AND THAT IS THE DECISION ────────

`validate` refuses one anywhere in the tree, at import time. Not because a
lambda would fail to work -- it would work, once, and then the next author
would add another, and the declaration would become the renderer again. That is
precisely how one `if log_type ==` acquired thirteen branches and 1145 lines.

The formatter registry is the escape hatch and it is a CLOSED NAMED SET.
Widening it is a deliberate act in a reviewed file; a schema author cannot do
it inline.

── THE SOURCE IS PART OF THE SCHEMA ──────────────────────────────────────────

Some sheets are one filed record. Some are many: an orientation is filed ONE
DOCUMENT PER WORKER -- 85 records in 22 project-and-date groups on production
today -- while the paper it becomes lists every attendee under one
certification. And the daily jobsite log and the superintendent's log are two
separately signed records that print as ONE SHEET.

So `source` is declared per type: `one`, `group`, or `combined`. Getting this
into the schema now is the difference between a mechanism and a special case
waiting to happen, because the combined sheet then needs no engine change.

── EMPTY IS DECLARED, NEVER INFERRED ─────────────────────────────────────────

A section that says nothing about its empty state gets one by accident.
`validate` requires `empty` on every section that can be empty, and the three
values are the three kinds this product already distinguishes:

    omit             the section does not apply to this record at all
    none_documented  it applies, the record establishes none, and the document
                     says so in a restrained legal entry rather than deleting
                     the category
    blank_rows       the paper has empty rows and is still valid; a roster with
                     four names on a twenty-row sheet is not a deficiency
"""

from __future__ import annotations

from typing import Any, Dict, List

SOURCE_KINDS = ("one", "group", "combined")
EMPTY_KINDS = ("omit", "none_documented", "blank_rows")

#: Primitive names a section may claim. The engine holds the implementations;
#: this list is what a schema is allowed to ask for.
PRIMITIVES = ("field_grid", "table", "checklist", "narrative", "signature",
              "certification")

#: Named label sets a checklist may point at, so the sentences a worker agreed
#: to live in ONE place rather than in each schema that shows them.
LABEL_SETS: Dict[str, List[tuple]] = {
    # frontend/app/logbooks/subcontractor_orientation.jsx ORIENTATION_SECTIONS,
    # and backend/server.py's ORIENTATION_ITEMS, which must agree with it.
    "orientation_items": [
        ("hard_hats", "Hard hats required at all times on site"),
        ("safety_boots", "Safety boots required (steel toe, ANSI rated)"),
        ("safety_glasses", "Safety glasses / eye protection required"),
        ("high_vis", "High-visibility vest required near traffic"),
        ("no_horseplay", "No horseplay, running, or unsafe behavior"),
        ("report_hazards", "Report all hazards to CP immediately"),
        ("fall_protection_required", "Fall protection required at 6 ft and above"),
        ("harness_inspection", "Inspect harness before each use"),
        ("ladder_safety", "Three-point contact on ladders at all times"),
        ("scaffold_rules", "Only use scaffold as erected — no modifications"),
        ("emergency_exits", "Emergency exit locations reviewed"),
        ("first_aid", "First aid kit location reviewed"),
        ("emergency_contact", "Emergency contact numbers provided"),
        ("incident_reporting", "All incidents must be reported immediately"),
        ("no_drugs_alcohol", "Zero tolerance for drugs and alcohol on site"),
        ("sign_in_out", "Must sign in and out every day"),
        ("authorized_areas", "Only enter authorized work areas"),
        ("housekeeping", "Keep work area clean at all times"),
    ],
}


class SchemaError(ValueError):
    """A declaration this engine refuses to render."""


def _walk(node: Any, path: str, out: List[str]) -> None:
    if callable(node):
        out.append(path)
        return
    if isinstance(node, dict):
        for k, v in node.items():
            _walk(v, f"{path}.{k}", out)
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]", out)


def callables_in(decl: Any) -> List[str]:
    """Every path in a declaration that holds something callable.

    The whole point of the shape, so it is a function rather than a line
    inside `validate`: a test can call it directly and show it refusing.
    """
    out: List[str] = []
    _walk(decl, "", out)
    return out


def validate(log_type: str, decl: Dict[str, Any]) -> None:
    """Refuse a declaration rather than render it badly. Raises SchemaError."""
    from .formatters import FORMATTERS

    bad = callables_in(decl)
    if bad:
        raise SchemaError(
            f"{log_type}: a schema may not contain a callable. A declaration "
            f"that holds code is a renderer, and this engine exists because one "
            f"of those grew thirteen branches. Found at: {bad}")

    src = decl.get("source") or {}
    if src.get("kind") not in SOURCE_KINDS:
        raise SchemaError(
            f"{log_type}: source.kind must be one of {SOURCE_KINDS}, not "
            f"{src.get('kind')!r}. A sheet that does not say how its records "
            f"are selected cannot be one sheet or many.")
    if src["kind"] == "group" and not src.get("by"):
        raise SchemaError(f"{log_type}: source kind 'group' must say what it "
                          f"groups BY")
    if src["kind"] == "combined" and not src.get("types"):
        raise SchemaError(f"{log_type}: source kind 'combined' must name the "
                          f"types it draws on")

    if not decl.get("sections"):
        raise SchemaError(f"{log_type}: a schema with no sections renders an "
                          f"empty sheet, which is worse than no sheet")

    for i, sec in enumerate(decl["sections"]):
        where = f"{log_type} section {i}"
        if sec.get("primitive") not in PRIMITIVES:
            raise SchemaError(f"{where}: unknown primitive "
                              f"{sec.get('primitive')!r}; known: {PRIMITIVES}")
        if sec.get("empty") not in EMPTY_KINDS:
            raise SchemaError(
                f"{where}: must declare `empty` as one of {EMPTY_KINDS}. A "
                f"section that says nothing about its empty state gets one by "
                f"accident, and on a compliance document the three kinds of "
                f"empty are not interchangeable.")
        for col in (sec.get("fields") or []) + (sec.get("columns") or []):
            if len(col) != 3:
                raise SchemaError(f"{where}: a field is (path, label, formatter)")
            if col[2] not in FORMATTERS:
                raise SchemaError(
                    f"{where}: unknown formatter {col[2]!r}. The set is closed "
                    f"on purpose -- add one to formatters.py and name it here. "
                    f"Known: {sorted(FORMATTERS)}")
        if sec.get("primitive") == "checklist" and sec.get("labels") not in LABEL_SETS:
            raise SchemaError(f"{where}: unknown label set {sec.get('labels')!r}")


# ══════════════════════════════════════════════════════════════════════════
#  THE SCHEMAS
# ══════════════════════════════════════════════════════════════════════════

SCHEMAS: Dict[str, Dict[str, Any]] = {

    # ── SITE SAFETY ORIENTATION ─────────────────────────────────────────────
    #
    # ONE SHEET PER (PROJECT, DATE), NOT PER WORKER. The app files one document
    # per worker -- 85 of them in 22 groups on production, the largest group 16
    # -- and the paper it becomes is one sheet listing every attendee under one
    # certification. The records are NOT merged: each stays its own separately
    # signed row, and each attendee line carries that worker's own signature,
    # which is what the paper does and what the data supports.
    "subcontractor_orientation": {
        "title": "Site Safety Orientation Record",
        "subtitle": "To be maintained on site for inspection",
        "cite": "BC 3301.13.13",
        "source": {"kind": "group", "by": ["project_id", "date"]},
        "sections": [
            {
                "n": 1, "title": "Site Information", "primitive": "field_grid",
                "scope": "project", "empty": "omit",
                "fields": [
                    ("address", "Job Address", "text"),
                    ("bbl", "Borough", "bbl_borough"),
                    ("nyc_bin", "BIN", "text"),
                    ("bbl", "Block", "bbl_block"),
                    ("bbl", "Lot", "bbl_lot"),
                    ("company_name", "General Contractor", "name"),
                ],
            },
            {
                "n": 2, "title": "Orientation Information",
                "primitive": "field_grid", "scope": "first", "empty": "omit",
                "fields": [
                    ("date", "Date", "date_long"),
                    ("data.completed_at", "Time", "time_of_day"),
                    ("cp_name", "Conducted By", "name"),
                    ("data.language_provided", "Language Provided", "text"),
                ],
            },
            {
                "n": 3, "title": "Topics Covered", "primitive": "checklist",
                "scope": "first", "path": "data.checklist",
                "labels": "orientation_items", "empty": "none_documented",
            },
            {
                # THE ATTENDEE TABLE IS THE SHEET. One row per filed record,
                # each carrying that worker's OWN signature -- the reason the
                # records are drawn together rather than merged.
                "n": 4, "title": "Attendees", "primitive": "table",
                "scope": "each", "empty": "blank_rows", "min_rows": 10,
                "columns": [
                    ("data.worker_name", "Name (Print)", "name"),
                    ("data.worker_company", "Company", "name"),
                    ("data.worker_trade", "Trade", "name"),
                    ("data.worker_signature", "Signature", "text"),
                    ("date", "Date", "date_long"),
                ],
            },
            {
                "n": 5, "title": "Certification", "primitive": "certification",
                "scope": "first", "empty": "none_documented",
                "statement": (
                    "I certify that the above individuals received a site "
                    "safety orientation in accordance with BC 3301.13.13 and "
                    "that the information provided was reviewed and understood."
                ),
                "fields": [
                    ("cp_name", "Name (Print)", "name"),
                    ("data.completed_at", "Time", "time_of_day"),
                    ("date", "Date", "date_long"),
                ],
                "signature_path": "cp_signature",
            },
        ],
    },
}


#: THE PER-TYPE SWITCH, AND THE ROLLBACK. `generate_single_logbook_html`
#: consults this first and falls through to its existing branch for anything
#: not named here. Removing a name is a one-line revert.
#:
#: A CONVERTED TYPE'S OLD BRANCH IS DELETED IN THE FOLLOWING CHANGE, once it
#: has rendered in production and been read. Required, not optional: "we will
#: delete it later" is how thirteen branches came to exist, and a converted
#: type whose old branch survives is exactly the drift this engine ends.
CONVERTED_TYPES = frozenset(SCHEMAS)

for _t, _d in SCHEMAS.items():
    validate(_t, _d)
