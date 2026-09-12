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

Some sheets are one filed record. Some are many: the daily jobsite log and the
superintendent's log are two separately signed records that print as ONE SHEET.

So `source` is declared per type: `one`, `group`, or `combined`. Getting this
into the schema now is the difference between a mechanism and a special case
waiting to happen, because the combined sheet then needs no engine change.

AND IT HAS ALREADY EARNED ITS KEEP, BY BEING CHANGED. The orientation shipped
as `group` -- one sheet per project and date, every attendee under one
certification -- and that was wrong about what the document IS. A worker signs
his own orientation the first time he comes on site; it is not a register of
signatures collected at one meeting. Reversing it to `one` was ONE WORD in this
file. The engine was not touched, the per-type switch in server.py was not
touched, and no primitive learned anything new, because the group read there is
gated on this declaration. That is the whole argument for source living in the
schema, and it held the first time it was tested.

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

── VALIDATE PROVES A SCHEMA IS WELL-FORMED, NOT THAT IT IS CORRECT ───────────

These are two different questions and NEITHER SUBSTITUTES FOR THE OTHER.

`validate` answers: does this declaration have the shape the engine can read?
Named primitive, named formatter, a declared `empty`, no callable anywhere. It
is a grammar check, and it runs at import so a malformed schema cannot reach
production.

Whether the sheet carries the values the record actually holds is answered by
the RENDERER TESTS, against a real record, comparing the field set before and
after. `validate` cannot answer it: a schema may be perfectly well-formed and
still bind the wrong path, name a formatter that is real but wrong for the
value, or omit a field entirely. All three are grammatical.

THE FIRST ORIENTATION SCHEMA LOST FOUR THINGS AND validate PASSED ALL FOUR:

    the worker's gate signature, declared "text" -- a real formatter -- so it
        printed as the escaped characters of its own data URI
    the UNSIGNED marker for a worker who never signed
    the OSHA number, the orientation number, and the completion stamp
    every kiosk checklist line, because the kiosk keys that map by the item's
        full English sentence and the label set keys it by the short name

EVERY ONE OF THE FOUR FAILED TOWARD LOOKING FINE. Not one produced a stack
trace, a blank page, or a visibly broken sheet. The signature became plausible
text; the missing columns left a tidy narrower table; the dropped checklist
left a section that simply had fewer lines. A reader who had not seen the old
sheet would have had no reason to look twice at any of them.

That is not coincidence -- it is the failure mode of this whole class of
change. A restyle can only lose content quietly, because anything it loses
loudly would not have shipped. So the check that catches it cannot be "does it
render"; it has to be "does it still say the same things", asserted against
the old output, every time.
"""

from __future__ import annotations

from typing import Any, Dict, List

SOURCE_KINDS = ("one", "group", "combined")
EMPTY_KINDS = ("omit", "none_documented", "blank_rows")

#: Primitive names a section may claim. The engine holds the implementations;
#: this list is what a schema is allowed to ask for.
PRIMITIVES = ("field_grid", "table", "checklist", "narrative", "signature",
              "certification")

#: FORMATTER NAMES A PRIMITIVE HANDLES ITSELF, not value formatters.
#:
#: `signature_ink` cannot be one of those: a formatter takes a value and
#: returns a string, and ink needs the stroke reconstruction that arrives in
#: the render context. Naming it here is what lets a schema ASK for ink in a
#: table column while keeping the formatter registry honest about what it is.
#:
#: THE FIRST DRAFT OF THE ORIENTATION SCHEMA SAID "text" IN THAT COLUMN, and
#: validate accepted it because "text" is a real formatter. The worker's gate
#: signature printed as the escaped characters of its own data URI. An existing
#: test caught it -- the one that exists because that signature had already
#: been broken once.
PRIMITIVE_FORMATTERS = ("signature_ink",)

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
    """Refuse a declaration rather than render it badly. Raises SchemaError.

    A GRAMMAR CHECK, NOT A CORRECTNESS CHECK. Passing here means the engine can
    read the declaration; it says nothing about whether the sheet carries what
    the record holds. See the module docstring: four content losses passed this
    function, and all four failed toward looking fine.
    """
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
            if col[2] not in FORMATTERS and col[2] not in PRIMITIVE_FORMATTERS:
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
    # ONE SHEET PER WORKER. 92 filed records on production, and 92 sheets.
    #
    # THIS SHIPPED THE OTHER WAY ROUND, AND THE REVERSAL IS THE POINT. It was
    # `group`, keyed on project and date, drawing every attendee into one
    # roster under one certification. That reads well and is wrong about the
    # document: a worker signs his own orientation the first time he comes on
    # site, and the date two men share is where their first days happen to
    # fall, not a meeting either attended. A roster asserts the meeting.
    #
    # Reversing it also ended the only case in this product where two
    # separately filed legal records shared a page. 17 of the 23 groups held
    # more than one record; the largest held 16.
    "subcontractor_orientation": {
        "title": "Site Safety Orientation Record",
        "subtitle": "To be maintained on site for inspection",
        "cite": "BC 3301.13.13",
        "source": {"kind": "one"},
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
                # A FIELD GRID, NOT A TABLE. This was a table of attendees, and
                # on a one-worker sheet a table is one row with nine blank ones
                # ruled beneath it -- a roster inviting names that are never
                # coming, on a document about one man.
                #
                # EVERY FIELD THE RECORD CARRIES, unchanged from the columns
                # that table declared. The first draft of this schema dropped
                # `osha_number`, `orientation_number` and the completion stamp
                # and the renderer tests caught all three: APPEARANCE MAY
                # CHANGE, THE RECORDED VALUES MAY NOT. That rule is exactly
                # what makes swapping one primitive for another safe to do.
                "n": 4, "title": "Worker", "primitive": "field_grid",
                "scope": "first", "empty": "omit",
                "fields": [
                    ("data.worker_name", "Name (Print)", "name"),
                    ("data.worker_company", "Company", "name"),
                    ("data.worker_trade", "Trade", "name"),
                    ("data.osha_number", "OSHA / SST #", "raw_text"),
                    ("data.orientation_number", "Orientation #", "raw_text"),
                    ("data.completed_at", "Completed", "datetime_stamp"),
                ],
            },
            {
                # HIS OWN MARK, ON HIS OWN SHEET. `omit` and the engine's
                # signature rule together keep the distinction the old renderer
                # drew: a key present and empty says UNSIGNED, and a key the
                # record does not carry prints no section at all. A heading
                # reading "Worker Acknowledgment" over an empty box is itself a
                # claim that one was asked for.
                "n": 5, "title": "Worker Acknowledgment",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "data.worker_signature",
                "name_path": "data.worker_name",
                "role": "Worker",
            },
            {
                "n": 6, "title": "Certification", "primitive": "certification",
                "scope": "first", "empty": "none_documented",
                "statement": (
                    "I certify that the individual named above received a site "
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
