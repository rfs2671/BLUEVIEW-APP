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

#: WHOSE DATA A SECTION DRAWS.
#:
#:   project   the project document, from the render context
#:   first     the first filed record on the sheet
#:   each      every filed record on the sheet, as a list
#:   rows      a REPEATING GROUP INSIDE one record, named by `path`
#:
#: `rows` is the one the forms actually needed. `table` was written against
#: sibling FILED RECORDS -- the orientation drew a roster that way before it
#: became one sheet per worker -- and every ordinary form instead holds its
#: repeating groups in its own `data`: the daily log's crews and its safety
#: observations, and the same shape on most of the eleven types after it.
SCOPES = ("project", "first", "each", "rows", "context")
EMPTY_KINDS = ("omit", "none_documented", "blank_rows")

#: Primitive names a section may claim. The engine holds the implementations;
#: this list is what a schema is allowed to ask for.
PRIMITIVES = ("field_grid", "table", "checklist", "narrative", "signature",
              "certification", "inspection_log", "question_answers",
              "register")

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

#: FORMATTERS THAT ARE HANDED THE WHOLE ROW, not one value.
#:
#: `signature_ink` above established that a primitive may handle a named
#: formatter itself. This is the same escape hatch for the same reason and it
#: is kept just as narrow: a formatter takes ONE VALUE and returns a string,
#: and the daily log's headcount cell reads THREE keys off its row --
#: `num_workers`, `num_workers_source` and `gate_num_workers` -- to print
#: `4 (CP) - gate recorded 6`.
#:
#: THE ALTERNATIVE WAS A LAMBDA IN THE DECLARATION, which `validate` refuses
#: on the first line of its body, for the reason this module is named after. A
#: closed named set implemented in a reviewed file is the whole difference.
#:
#: The column's path is written "." and ignored: the subject IS the row.
ROW_FORMATTERS = ("cp_headcount", "preshift_signature", "osha_cert_type")

#: Named label sets a checklist may point at, so the sentences a worker agreed
#: to live in ONE place rather than in each schema that shows them.
LABEL_SETS: Dict[str, List[tuple]] = {
    # frontend/app/logbooks/subcontractor_orientation.jsx ORIENTATION_SECTIONS,
    # and backend/server.py's ORIENTATION_ITEMS, which must agree with it.
    # backend/server.py SCAFFOLD_QUESTIONS -- nineteen questions a shed
    # inspection answers in WORDS, not ticks. See  for why
    # that distinction is load-bearing.
    # ── THE THREE ITEM LISTS THE LAST SIX CONVERSIONS NEED ──────────────────
    #
    # LIFTED VERBATIM FROM THE BRANCHES, key and label and ORDER. Each of these
    # was a tuple list inside its own arm of the per-type chain, and the label
    # is the sentence the CP tapped on the screen and the inspector reads on
    # the sheet. Those two have to be the same words: the FDNY permit editor
    # once said "(35ft)" and "Covered/Protected" where every reader printed
    # "(35 ft)" and "Covered / Protected", so the CP ticked one sentence and
    # the inspector read another.
    #
    # frontend/src/utils/portedFormPayloads.test.cjs asserts the device's list
    # against these, key for key and word for word, and reads them through
    # `labelSet()` -- so a label edited on one side and not the other fails
    # rather than shipping.
    "hot_work_precautions": [
        ("area_cleared", "Area Cleared of Combustibles (35 ft)"),
        ("fire_extinguisher_present", "Fire Extinguisher Present"),
        ("sprinklers_operational", "Sprinklers Operational"),
        ("combustibles_covered", "Combustibles Covered / Protected"),
        ("fire_watch_assigned", "Fire Watch Assigned"),
        ("ventilation_adequate", "Ventilation Adequate"),
        ("permit_posted", "Permit Posted at Location"),
    ],
    "crane_pre_operation": [
        ("wire_ropes", "Wire Ropes Inspected"),
        ("hooks_latches", "Hooks & Latches Secure"),
        ("brakes", "Brakes Functional"),
        ("outriggers", "Outriggers Deployed"),
        ("load_chart", "Load Chart Available"),
        ("boom_condition", "Boom Condition OK"),
        ("anti_two_block", "Anti Two-Block Device"),
        ("fire_extinguisher", "Fire Extinguisher Present"),
        ("signals_reviewed", "Signals Reviewed"),
        ("area_barricaded", "Area Barricaded"),
        ("wind_speed_checked", "Wind Speed Checked"),
        ("power_lines_clear", "Power Lines Clear"),
        ("load_weight_known", "Load Weight Known"),
        ("rigging_inspected", "Rigging Inspected"),
        ("swing_radius_clear", "Swing Radius Clear"),
    ],
    "concrete_formwork": [
        ("shores_plumb", "Shores Plumb"),
        ("bracing_adequate", "Bracing Adequate"),
        ("formwork_clean", "Formwork Clean"),
        ("no_gaps", "No Gaps"),
    ],
    "scaffold_maintenance_questions": [
        ("signs_on_parapets", "Are the signs on the parapets?"),
        ("base_plates_mudsills", "Are the base plates and mudsills secured?"),
        ("scaffold_pins_bolts", "Are the scaffold pins and bolts installed?"),
        ("legs_poles_plumb",
         "Are the legs and poles plumb, braced and not displaced?"),
        ("tie_ins_spaced",
         "Are tie-ins correctly spaced, properly secured and the correct amount?"),
        ("cross_braces",
         "Are cross braces fully attached, not bent, and not missing?"),
        ("pipe_clamps_tight", "Are pipe clamps tight?"),
        ("window_jacks_tight", "Are window jacks tight?"),
        ("planks_secured", "Are all the planks secured?"),
        ("decking_planks_condition", "Are decking and planks in good condition?"),
        ("deck_fully_planked", "Is deck fully planked?"),
        ("gaps_open_spaces", "Are there gaps or open spaces on decking?"),
        ("guardrails_toe_boards",
         "Are the guardrails and toe boards secured at all places where required?"),
        ("netting_extension", "Is the netting extension of full length and height?"),
        ("netting_secured", "Is the netting secured?"),
        ("parapet_height", "Is the parapet the proper height and secured?"),
        ("lights_working", "Are the lights working?"),
        ("deck_clean", "Is the deck clean and free of debris?"),
        ("drawings_on_site", "Drawings on site for inspection?"),
    ],

    # backend/server.py INSPECTION_ORDER, which is the order the device shows
    # them in and therefore the order the man walked them.
    #
    # `other_checklist` IS LAST AND IS NOT A PASS/FAIL ITEM. The other eight
    # name a specific thing to look at, so pass and fail mean something about
    # that thing. "Other" names nothing, so a green "Passed: Other" on a filed
    # 3301-02 asserts that an unnamed inspection was fine -- a claim with no
    # subject. A section declares which key it is; the primitive prints the
    # CP's note as the record instead.
    "inspection_items": [
        # THE WORDS `_inspection_label` PRODUCES, not better ones. Eleven
        # filed records render through the legacy path as a list of these
        # labels; "Neighbouring property" would be an improvement to a
        # document that has already been signed.
        ("street_frontage", "Street Frontage"),
        ("fire_safety", "Fire Safety"),
        ("perimeter_fence", "Perimeter Fence"),
        ("fall_protections", "Fall Protections"),
        ("neighbors_property", "Neighbors Property"),
        ("license_spot_check", "License Spot Check"),
        ("plans", "Plans"),
        ("permits", "Permits"),
        ("other_checklist", "Other Checklist"),
    ],
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
        if sec.get("scope") is not None and sec.get("scope") not in SCOPES:
            raise SchemaError(f"{where}: unknown scope {sec.get('scope')!r}; "
                              f"known: {SCOPES}")
        if sec.get("primitive") not in PRIMITIVES:
            raise SchemaError(f"{where}: unknown primitive "
                              f"{sec.get('primitive')!r}; known: {PRIMITIVES}")
        if sec.get("empty") not in EMPTY_KINDS:
            raise SchemaError(
                f"{where}: must declare `empty` as one of {EMPTY_KINDS}. A "
                f"section that says nothing about its empty state gets one by "
                f"accident, and on a compliance document the three kinds of "
                f"empty are not interchangeable.")
        _sp = sec.get("path")
        if isinstance(_sp, (list, tuple)):
            if not _sp or not all(isinstance(x, str) and x for x in _sp):
                raise SchemaError(
                    f"{where}: a list `path` is a non-empty list of dotted "
                    f"paths, first present wins; got {_sp!r}")
            if sec.get("primitive") != "signature":
                raise SchemaError(
                    f"{where}: only a signature may name more than one path")

        for col in (sec.get("fields") or []) + (sec.get("columns") or []):
            if len(col) != 3:
                raise SchemaError(f"{where}: a field is (path, label, formatter)")
            if (col[2] not in FORMATTERS
                    and col[2] not in PRIMITIVE_FORMATTERS
                    and col[2] not in ROW_FORMATTERS):
                raise SchemaError(
                    f"{where}: unknown formatter {col[2]!r}. The set is closed "
                    f"on purpose -- add one to formatters.py and name it here. "
                    f"Known: {sorted(FORMATTERS)}")
            if col[2] in ROW_FORMATTERS and sec.get("primitive") != "table":
                raise SchemaError(
                    f"{where}: {col[2]!r} is handed the whole ROW, which only "
                    f"a table has. A field grid's subject is a record.")
        if (sec.get("primitive") in ("checklist", "inspection_log")
                and sec.get("labels") not in LABEL_SETS):
            raise SchemaError(f"{where}: unknown label set {sec.get('labels')!r}")

        # ── A SECTION MAY SAY WHICH OF ITS OWN PATHS MAKE IT EXIST ───────
        #
        # `_is_empty` answers from the RECORDS by default, and deliberately: a
        # grid whose every cell reads "not recorded" is a record that was
        # filed blank, which is a different fact from a section that does not
        # apply. Some sections need the other answer -- the daily log's
        # working hours are two keys nothing has written since the picker
        # work, and declaring them without this would print two "not
        # recorded" cells on all 59 filed records, reinstating the permanent
        # N/A that branch deliberately removed.
        # ── TWO KEYS THAT SAY WHEN A SECTION EXISTS, AND ONE THAT SAYS
        #    WHEN A ROW DOES ─────────────────────────────────────────────
        for key in ("requires", "requires_present"):
            r = sec.get(key)
            if r is not None and (
                    not isinstance(r, (list, tuple)) or not r
                    or not all(isinstance(x, str) and x for x in r)):
                raise SchemaError(
                    f"{where}: `{key}` is a non-empty list of dotted paths, "
                    f"got {r!r}")

        for _rk in ("row_requires", "row_requires_present"):
            _rv = sec.get(_rk)
            if _rv is not None and (
                    not isinstance(_rv, (list, tuple)) or not _rv
                    or not all(isinstance(x, str) and x for x in _rv)):
                raise SchemaError(
                    f"{where}: `{_rk}` is a non-empty list of row keys")
            if _rv is not None and sec.get("primitive") != "table":
                raise SchemaError(
                    f"{where}: `{_rk}` filters ROWS and only a table has any")

        rr = sec.get("row_requires")
        if rr is not None:
            if sec.get("primitive") != "table":
                raise SchemaError(f"{where}: `row_requires` filters ROWS, "
                                  f"which only a table has")
            if (not isinstance(rr, (list, tuple)) or not rr
                    or not all(isinstance(x, str) and x for x in rr)):
                raise SchemaError(
                    f"{where}: `row_requires` is a non-empty list of keys, "
                    f"got {rr!r}")

        if sec.get("statement") and sec.get("statement_ref"):
            raise SchemaError(
                f"{where}: a certification may name `statement_ref` OR carry a "
                f"literal `statement`, not both -- two sentences over one mark")

        if sec.get("statement") and sec.get("statement_ref"):
            raise SchemaError(
                f"{where}: a certification may name `statement_ref` OR carry a "
                f"literal `statement`, not both -- two sentences over one mark")

        req = sec.get("requires")
        if req is not None:
            if (not isinstance(req, (list, tuple)) or not req
                    or not all(isinstance(x, str) and x for x in req)):
                raise SchemaError(
                    f"{where}: `requires` is a non-empty list of dotted "
                    f"paths, got {req!r}")

        # ── A TABLE OVER ROWS INSIDE ONE RECORD MUST SAY WHICH ROWS ──────
        if sec.get("scope") == "rows" and not sec.get("path"):
            raise SchemaError(
                f"{where}: scope 'rows' draws a list held INSIDE one record "
                f"and must name the path to it")


# ══════════════════════════════════════════════════════════════════════════
#  THE SCHEMAS
# ══════════════════════════════════════════════════════════════════════════

SCHEMAS: Dict[str, Dict[str, Any]] = {

    "preshift_signin": {
        "title": "Pre-Shift Sign-In",
        "subtitle": "Daily sign-in with all workers",
        "cite": "OSHA 1926.21",
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
                # LOCATION IS THE CP'S OWN WORDS AND STAYS BESIDE THE PROJECT
                # ADDRESS ABOVE, NOT INSTEAD OF IT. They disagree on filed
                # records -- one sheet reads "Bronx, NY" over a project whose
                # address is a Brooklyn street -- and both are true statements
                # about different things: one is where the project is, the
                # other is what the CP wrote on the roster that morning.
                # Reconciling them would delete a fact, the same way picking
                # one of the daily log's two headcounts would.
                #
                # TOTAL WORKERS IS THE FILED NUMBER, not a recount of the rows.
                # The old branch fell back to `len(workers)` when the key was
                # absent; measured on the 49 filed records the key is present
                # on all 49, including the two that say 0, so the fallback has
                # never fired and re-deriving it here would be this renderer
                # counting where the record already states.
                "n": 2, "title": "Sign-In Information",
                "primitive": "field_grid", "scope": "first", "empty": "omit",
                "per_row": 2,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("data.company", "Company", "name"),
                    ("data.project_location", "Location", "text"),
                    ("data.total_count", "Total Workers", "text"),
                ],
            },
            {
                # `row_requires` ON `name`, WHICH IS THE OLD BRANCH'S GUARD AND
                # NOT A NEW RULE. A seed row the CP never filled printed as a
                # blank line carrying an injury answer and a PPE answer -- a
                # man who was asked two safety questions on a signed roster and
                # cannot be identified by anybody reading it.
                #
                # THE ANSWER COLUMNS ARE `answer`, NOT `yes_no`, AND THIS IS
                # THE ONE THAT WOULD HAVE SHIPPED QUIETLY. The stored domain is
                # the lowercase strings 'yes' and 'no'; `yes_no` takes
                # `bool(v)`, and `bool("no")` is True. Every man who reported
                # NO INJURY would have printed "Yes" under a column headed
                # Injury, on 49 filed compliance records, and the document
                # would have looked entirely normal.
                #
                # `raw_text` ON OSHA #, NOT `text`. The row is the record here:
                # a man with no card number has a blank cell, and
                # "— Not recorded" in that slot is a finding against him.
                "n": 3, "title": "Workers", "primitive": "table",
                "scope": "rows", "path": "data.workers",
                "empty": "none_documented",
                "none_text": "No workers were recorded on this roster.",
                "row_requires": ["name"],
                "columns": [
                    ("name", "Name", "raw_name"),
                    ("company", "Company", "raw_name"),
                    ("osha_number", "OSHA #", "raw_text"),
                    ("had_injury", "Injury", "answer"),
                    ("inspected_ppe", "PPE", "answer"),
                    (".", "Signature", "preshift_signature"),
                ],
            },
            {
                # A FACT ABOUT A RECORD KEPT SOMEWHERE ELSE, WHICH IS WHY IT IS
                # A COUNT AND NOT A COLUMN. The Signature column above gave up
                # the affirmation claim deliberately: an affirmation beside a
                # named man's row is an assertion the stored roster does not
                # carry. The count is a statement about the affirmation
                # records, not about anyone on this sheet, and it is safe in a
                # way the per-row mark was not.
                #
                # SCOPE `context`. The number comes from an async query over
                # two collections, resolved above the dispatch; it is on the
                # record nowhere, and it must not be written onto the record to
                # get here.
                #
                # `requires` OMITS THE SECTION WHEN THE COUNT IS ABSENT. The
                # old footer printed nothing at zero -- 24 of the 49 filed
                # records carry no line at all -- and a heading over "0
                # affirmations are on record" would turn a silence into a
                # finding.
                "n": 4, "title": "Affirmation Records",
                "primitive": "narrative", "scope": "context",
                "path": "preshift_affirmation_count",
                "formatter": "affirmation_note",
                "requires": ["preshift_affirmation_count"],
                "empty": "omit",
            },
            {
                # A CERTIFICATION, AND HERE THE SWORN SENTENCE IS REAL. Unlike
                # the daily jobsite log, this document HAS an attestation: it
                # is printed above the CP's mark today and its exact wording is
                # stored, versioned, in every signature event this sheet
                # produces.
                #
                # `statement_ref`, NEVER `statement`. The text lives in
                # lib/logbook/attestations.py, append-only and keyed by version,
                # BECAUSE A STORED SNAPSHOT MUST BE CHECKABLE AGAINST WHAT THE
                # SIGNER WAS SHOWN. Retyping it here would be a second copy of a
                # sentence whose whole value is that there is one -- and the
                # copy would be wrong on its first character, because the
                # registry's text is already HTML-escaped and `certification`
                # escapes what it is handed.
                "n": 5, "title": "Certification", "primitive": "certification",
                "scope": "first", "empty": "omit",
                "statement_ref": "preshift_signin",
                "fields": [
                    ("cp_name", "Name (Print)", "name"),
                ],
                "signature_path": "cp_signature",
                "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── OSHA / SST CERTIFICATION REGISTER ───────────────────────────────────
    #
    # A REGISTER, AND ITS OWN RULE FOLLOWS FROM THAT: the row is the record and
    # there is no unanswered form field. An entry with no card number has a
    # BLANK cell, never "— Not recorded", because nobody was asked a question
    # and left it unanswered -- the man simply holds no card of that kind. Both
    # the Card #, Expiration and Signed columns are declared on that rule, and
    # it is the reason two of them use `raw_text` rather than `text`.
    #
    # 39 filed records; 37 carry at least one entry and 2 carry none.
    #
    # THE REVIEW COLUMN IS NOT HERE AND MUST NOT BE. The combined report adds
    # one by joining each row back to the worker's LIVE certifications. This
    # document renders one STORED snapshot, and a register whose Cert Type or
    # Review column reads differently on two renderings of one filed document
    # cannot be validated against a single moment -- which is the thing
    # Bulletin 2024-007 sec V.6 asks of a signature.,

    "osha_log": {
        # THE NAME ON THE FILED DOCUMENT, NOT THE NAME IN THE APP.
        #
        # LOGBOOK_TYPE_REGISTRY labels this "OSHA Log Book" and the branch has
        # printed "OSHA / SST Certification Log" at the head of every filed
        # record there has ever been. The two have disagreed since before this
        # conversion; taking the registry's word would have renamed 39 filed
        # documents, and the one an inspector asks for by name is the one on
        # the paper.
        #
        # THE DISAGREEMENT ITSELF IS RECORDED, not resolved here: which name
        # the app's own screens should use is a product question, and a
        # restyle is not the place to answer it.
        "title": "OSHA / SST Certification Log",
        "subtitle": "Worker certifications register",
        "cite": "OSHA 1926",
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
                # `row_requires` ON `worker_name` AND NOTHING ELSE, which is
                # the branch's own guard verbatim. It used to read five fields
                # any-of and printed a row carrying only a card number -- a
                # certification on a signed register belonging to nobody named.
                #
                # THE UNVERIFIED MARKER RIDES IN THE CERT TYPE CELL because it
                # is a statement about the class, not about the worker: a row
                # reading "SST Unspecified" with nothing beside it asserts a
                # credential on file that the gate could not actually read. It
                # is on 5 of the 39 filed records and it is the half of this
                # column that fails toward looking fine if it is dropped.
                #
                # THE SIGNED COLUMN IS A TICK OR NOTHING. `yes_no` would print
                # "No" against every unticked row, which on a register is the
                # CP asserting that a signature is NOT on file -- a finding he
                # never made. The old branch's empty cell is the whole claim.
                "n": 2, "title": "Certifications Recorded",
                "primitive": "table", "scope": "rows", "path": "data.entries",
                "empty": "none_documented",
                "none_text": "No certifications were recorded on this register.",
                "row_requires": ["worker_name"],
                "columns": [
                    ("worker_name", "Worker", "raw_name"),
                    ("company", "Company", "raw_name"),
                    (".", "Cert Type", "osha_cert_type"),
                    ("card_number", "Card #", "raw_text"),
                    ("expiration", "Expiration", "raw_text"),
                    ("signed", "Signed", "tick_or_blank"),
                ],
            },
            {
                # THE SAME `statement_ref` ARGUMENT AS THE PRE-SHIFT SHEET, and
                # the same registry. This one carries the sentence that says
                # what the CP's mark does and does not attest to -- that the
                # register is a true copy of what the system held, and NOT that
                # the physical cards were inspected. A conversion that dropped
                # it would leave his signature over a register with no stated
                # limit on what it claims.
                "n": 3, "title": "Certification", "primitive": "certification",
                "scope": "first", "empty": "omit",
                "statement_ref": "osha_log",
                "fields": [
                    ("cp_name", "Name (Print)", "name"),
                ],
                "signature_path": "cp_signature",
                "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── SCAFFOLD MAINTENANCE LOG ────────────────────────────────────────────
    #
    # THE SIDEWALK-SHED DAILY INSPECTION. 9 filed records, all submitted, none
    # amended.
    #
    # `question_answers` AND NOT `checklist`, AND THE DIFFERENCE IS NOT
    # COSMETIC. The 19 checks are answered with the STRINGS 'YES', 'NO' and
    # 'N/A'. `checklist` draws a ticked or unticked box from the truth of the
    # stored value, and the string "NO" is truthy in Python -- so every failed
    # check on a shed inspection would have printed as a ticked box, on the
    # document a DOB inspector reads to find out whether the shed is safe.
    # `inspection_log` is wrong for a different reason: it asks pass / fail
    # with a note, and there is no note here and no fourth answer.
    #
    # AN N/A THE CP CHOSE IS A REAL ANSWER and renders as chosen. An unanswered
    # question reads "— Not recorded" and never a silent NO.,

    "scaffold_maintenance": {
        "title": "Scaffold Maintenance Log",
        "subtitle": "NYC DOB — Daily while scaffold is up",
        "cite": "§3314",
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
                # `requires` NAMES ALL NINE, AND THE FIELDS NAME THE SAME NINE
                # PATHS. That is the daily jobsite conversion's mistake written
                # down: its gate said `data.time_in` and its field said
                # `time_in`, so the section appeared with every cell reading
                # "not recorded". Read this list against the one below it.
                #
                # ALL NINE PRINT ONCE ANY ONE OF THEM DOES, which is the old
                # branch's rule and the right one for a permit block: the
                # labels are on the form either way, so a silent omission would
                # hide which of them the CP left blank.
                #
                # `phone` IS EMPTY ON ALL 9 FILED RECORDS and prints
                # "— Not recorded" on every one. That is NOT the daily log's
                # `areas_visited` case and it is not dropped for it: there is a
                # live control for it on the screen, the census is nine
                # records, and removing a permit contact from a filed shed
                # inspection on that evidence is a decision for the operator.
                # Recorded in the report instead.
                #
                # THE DATES STAY AS FILED, `text` AND NOT `date_long`. The
                # installation and expiration dates are read against a DOB
                # permit, and the word-level diff that guards this whole
                # conversion CANNOT SEE DIGITS -- a date reformatted here would
                # be the one change on the sheet that no check could catch.
                "n": 2, "title": "Scaffold", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 3,
                "requires": [
                    "data.general_info.scaffold_erector",
                    "data.general_info.renters_name",
                    "data.general_info.permit_number",
                    "data.general_info.phone",
                    "data.general_info.installation_date",
                    "data.general_info.expiration_date",
                    "data.general_info.scaffold_height",
                    "data.general_info.num_platforms",
                    "data.general_info.shed_type",
                ],
                "fields": [
                    ("data.general_info.scaffold_erector",
                     "Scaffold Erector", "name"),
                    ("data.general_info.renters_name", "Renter", "name"),
                    ("data.general_info.permit_number", "Permit #", "text"),
                    ("data.general_info.phone", "Phone #", "text"),
                    ("data.general_info.installation_date",
                     "Installation Date", "text"),
                    ("data.general_info.expiration_date", "Expiration", "text"),
                    ("data.general_info.scaffold_height",
                     "Scaffold Height", "text"),
                    ("data.general_info.num_platforms",
                     "Platforms Decked", "text"),
                    ("data.general_info.shed_type", "Shed Type", "text"),
                ],
            },
            {
                # THE LABEL SET IS THE SENTENCE HE ANSWERED. A shed inspection
                # is 19 questions in the order the CP walks them, and a sheet
                # that asked a slightly better-worded question of an
                # already-filed answer would be wrong about what he said.
                #
                # `requires` ON THE MAP ITSELF, for the reason the daily log's
                # inspections carry one: without it a record holding no answers
                # renders a numbered section bar with nothing beneath it,
                # because emptiness otherwise asks whether any record was filed
                # and one was.
                "n": 3, "title": "Inspection Checklist",
                "primitive": "question_answers", "scope": "first",
                "path": "data.answers",
                "labels": "scaffold_maintenance_questions",
                "requires": ["data.answers"],
                "empty": "none_documented",
                "none_text": "No inspection answers were recorded.",
            },
            {
                # NOT A CERTIFICATION, AND THE TEST IS THE ATTESTATION
                # REGISTRY. Nine of the twelve types print no sentence above
                # their signature and this is one of them --
                # lib/logbook/attestations.py records that as
                # NONE_ON_DOCUMENT rather than leaving it absent, so the
                # question has already been answered for this type by the code
                # that writes its signature events. Inventing a sentence here
                # would put words on a signed §3314 record that the signer
                # never said, and would contradict every snapshot already
                # stored against it.
                "n": 4, "title": "Competent Person Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── CONSTRUCTION SUPERINTENDENT LOG ─────────────────────────────────────
    #
    # SIX FILED RECORDS, and the only type whose register is DATE-DEPENDENT:
    # which items BC 3301.13.13 requires is `cs_applicable_items(date)`. Those
    # rows are resolved by the caller and drawn by `register` -- see
    # `_cs_register_rows` for why that rule is not restated here.
    #
    # `source` IS `one`, NOT `combined`, AND THAT IS THIS CHANGE'S SCOPE. This
    # log and the daily jobsite log are meant to print as one sheet eventually;
    # all six of these records share a (project, date) with a daily log, so the
    # path is exercisable. But `combined` changes WHICH RECORDS APPEAR on a
    # document, and an old-against-new comparison of a sheet that grew a second
    # record is not a comparison -- the two sides would not be about the same
    # thing. The combined sheet is its own change, with its own comparison.
    "site_superintendent_log": {
        "title": "Construction Superintendent Log",
        "subtitle": "BC 3301.13.13 \u2014 to be maintained on site for inspection",
        "cite": "BC 3301.13.13",
        "source": {"kind": "one"},
        "sections": [
            {
                "n": 1, "title": "Site Information", "primitive": "field_grid",
                "scope": "project", "empty": "none_documented",
                "none_text": ("The project this record names is not on file, "
                              "so the site could not be identified."),
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
                # THE SUPERINTENDENT AND HIS HOURS. `printed_name` is what he
                # typed on this record; `cp_name` is the account that filed it,
                # and the branch prefers the first. Both are declared so the
                # sheet does not lose the distinction the branch drew.
                "n": 2, "title": "The Day", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 2,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("data.presence.printed_name", "Superintendent", "name"),
                    ("data.presence.arrived_at", "On site from", "time_of_day"),
                    ("data.presence.departed_at", "Until", "time_of_day"),
                ],
            },
            {
                # THE STATUTORY REGISTER. Rows arrive resolved under
                # `scope: context` because the item list depends on the date
                # and each body carries its own provenance line.
                "n": 3, "title": "Record of the Day",
                "primitive": "register", "scope": "context",
                "path": "register_rows", "requires": ["register_rows"],
                "empty": "none_documented",
                "none_text": "No items were required on this date.",
            },
            {
                # THE ATTESTATION, REFERENCED. `site_superintendent_log`
                # is in the versioned registry, so the sentence printed over
                # his mark is the one every signature event stored -- not a
                # retyped copy that would differ on its first escaped
                # character.
                "n": 4, "title": "Certification",
                "primitive": "certification", "scope": "first",
                "empty": "none_documented",
                "statement_ref": "site_superintendent_log",
                "fields": [
                    ("data.presence.printed_name", "Name (Print)", "name"),
                    ("date", "Date", "date_long"),
                ],
                "signature_path": "cp_signature",
                "note": None,
            },
            {
                # HOW THE SUPERINTENDENT WAS MATCHED TO THIS FILING, carried
                # verbatim. The sentence describes the match "by licence
                # number" and the DOB card carries a REGISTRATION number --
                # defect A2, reported and not corrected inside a conversion.
                "n": 5, "title": "Attribution", "primitive": "narrative",
                "scope": "context", "path": "cs_attribution_sentence",
                "formatter": "sentence",
                "requires": ["cs_attribution_sentence"], "empty": "omit",
            },
            {
                "n": 6, "title": "Superintendent Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": ["data.presence.signature", "cp_signature"],
                "name_path": "data.presence.printed_name",
                "role": "Construction Superintendent",
            },
        ],
    },

    # ── HOT WORK PERMIT ─────────────────────────────────────────────────────
    #
    # ZERO PRODUCTION RECORDS, and that is a fact about this conversion rather
    # than a gap in the baseline. There is nothing to diff, so the evidence is
    # backend/tests/fixtures/filed_sheets/fixtures_checklist_cluster.py
    # rendered through BOTH renderers -- the branch is still in server.py, so
    # the old side is the old renderer and not a reconstruction of it.
    #
    # THE FIXTURE'S `partial` RECORD IS THE ONE THAT MATTERS. Two of the seven
    # precautions answered and five ABSENT: a sheet that draws five empty
    # boxes there is a permit asserting that sprinklers, ventilation and the
    # fire watch were each considered and declined. `checklist` draws the
    # third state in words, which is the whole reason it is not just boxes.
    "hot_work": {
        # THE REGISTRY'S LABEL, NOT THE BRANCH'S. The branch printed "Hot Work
        # Permit"; every other surface in the product says "Hot Work Permit
        # Log", because the document is the LOG and the permit is the FDNY
        # paper the admin holds. This sheet has never been the permit.
        "title": "Hot Work Permit Log",
        "subtitle": "Welding, cutting and brazing — to be maintained on site "
                    "for inspection",
        "cite": "FC §3504",
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
                # NO `requires`. Every field here is a question the permit
                # form asks, so a grid of absences on a record filed blank is
                # the truth about that record -- which is exactly the case
                # `_is_empty` is documented as deliberately NOT collapsing.
                "n": 2, "title": "The Work", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 3,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("data.work_type", "Work Type", "text"),
                    ("data.location", "Location", "name"),
                    ("data.worker_name", "Worker", "name"),
                    # An FDNY certificate-of-fitness number is an identifier.
                    ("data.worker_cert_number", "Worker Cert #", "text"),
                    ("data.start_time", "Start Time", "time_of_day"),
                    ("data.end_time", "End Time", "time_of_day"),
                    ("data.fire_watch_name", "Fire Watch", "name"),
                    # PENDING `derived_time`. THIS VALUE IS NOT A RECORDED
                    # TIME: hotWorkModel.calcFireWatchEnd derives it as work
                    # end + 30 minutes and the editor captures no real
                    # fire-watch end at all. The branch prints the qualifier
                    # "(default: work end + 30 min)" beside it for that reason
                    # -- FDNY can require 60 -- and `time_of_day` prints the
                    # bare number, which reads as a watch-until somebody set.
                    # See the request filed with this declaration.
                    ("data.fire_watch_end_time", "Fire Watch Until",
                     "fire_watch_default"),
                    # THE CP'S NAME IS A FIELD, NOT ONLY A SIGNATURE
                    # CAPTION. The branch printed "CP: <name>" whenever
                    # `cp_name` was set and independently of the mark; bound
                    # only to the signature section it vanishes with that
                    # section on a record that never carried a `cp_signature`
                    # key. The daily log declares it in both places.
                    ("cp_name", "Competent Person", "name"),
                ],
            },
            {
                # THE EXISTING `checklist`, PLUS A LABEL SET. No result, no
                # fail, no note -- `inspection_log` exists for the daily
                # jobsite register's fourth answer and is not reached for here.
                #
                # `none_documented` RATHER THAN `omit`: the precautions are
                # the permit. A hot work sheet that simply has no precautions
                # section reads as a form that did not ask, and this one asks.
                "n": 3, "title": "Pre-Work Precautions",
                "primitive": "checklist", "scope": "first",
                "path": "data.precautions", "labels": "hot_work_precautions",
                # THE PERMIT'S OWN WORDS. The branch printed
                # `Precaution | Confirmed`; the primitive's default is
                # `Topic | Reviewed`, and "Fire Watch Assigned -- Reviewed"
                # claims the CP reviewed an item when what the permit asserts
                # is that a fire watch WAS ASSIGNED.
                "item_label": "Precaution", "mark_label": "Confirmed",
                "empty": "none_documented",
                "none_text": "No precautions documented.",
            },
            {
                "n": 4, "title": "Competent Person Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── CRANE OPERATIONS ────────────────────────────────────────────────────
    #
    # ZERO PRODUCTION RECORDS. See the hot work note above for what stands in
    # for a baseline and why.
    #
    # THE CHECKLIST AND THE LIFT LOG ARE TWO DIFFERENT KINDS OF SECTION and
    # the order is the branch's: the pre-operation checks come BEFORE the
    # lifts, because that is the order they happened in and the checklist is
    # what licenses the lifts.
    "crane_operations": {
        "title": "Crane Operations Log",
        "subtitle": "Pre-operation inspection and load log — to be maintained "
                    "on site for inspection",
        "cite": "§3319",
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
                "n": 2, "title": "The Crane", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 3,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("data.crane_type", "Crane Type", "name"),
                    # A manufacturer's or operator's marking, not prose.
                    ("data.crane_id", "Crane ID", "text"),
                    ("data.operator_name", "Operator", "name"),
                    ("data.operator_license", "Operator License", "text"),
                    # THE CP'S NAME IS A FIELD, NOT ONLY A SIGNATURE
                    # CAPTION. The branch printed "CP: <name>" whenever
                    # `cp_name` was set and independently of the mark; bound
                    # only to the signature section it vanishes with that
                    # section on a record that never carried a `cp_signature`
                    # key. The daily log declares it in both places.
                    ("cp_name", "Competent Person", "name"),
                ],
            },
            {
                # FIFTEEN ITEMS, AND STEP 2 IS INCOMPLETE UNTIL ALL FIFTEEN
                # ARE ANSWERED (craneOperationsModel.incompleteSteps). A
                # half-walked checklist is precisely what the device's pip
                # exists to show, so the sheet must not flatten the unanswered
                # ones into unticked boxes.
                "n": 3, "title": "Pre-Operation Checklist",
                "primitive": "checklist", "scope": "first",
                "path": "data.pre_operation_checklist",
                "labels": "crane_pre_operation", "empty": "none_documented",
                # `Item | Confirmed`, which is what the branch printed. Four
                # types share this primitive and they do not share a sentence.
                "item_label": "Item", "mark_label": "Confirmed",
                "none_text": "No pre-operation checks documented.",
            },
            {
                # `text` AND `sentence`, NOT `raw_text`, AND THE DAILY LOG
                # SETTLED IT. A lift row exists because a lift happened, so
                # every cell on it is a question that was asked -- the same
                # reading the crew table takes, which prints `sentence` for a
                # description and `text` for a location. The toolbox roster
                # takes the other reading for the opposite reason.
                #
                # NO UNITS. load_weight and radius are stored as the operator
                # typed them and the editor captures no unit; adding one here
                # would be a fabrication on a §3319 record.
                #
                # PENDING `row_requires`: the branch drops a row with none of
                # time / description / load_weight / radius set, and this
                # table cannot. An untouched EMPTY_LOAD_ENTRY printing here is
                # a lift the crane never made.
                "n": 4, "title": "Lift Log", "primitive": "table",
                "scope": "rows", "path": "data.load_entries",
                # AN UNTOUCHED SEED IS NOT A LIFT. `EMPTY_LOAD_ENTRY` carries
                # all four keys blank, and the branch dropped it; without this
                # the sheet printed a numbered row and four empty cells on a
                # crane log where nothing was lifted.
                "row_requires": ["time", "description", "load_weight",
                                 "radius"],
                "empty": "none_documented",
                "none_text": "No lifts recorded.",
                "columns": [
                    ("time", "Time", "text"),
                    ("description", "Description", "sentence"),
                    ("load_weight", "Load Weight", "text"),
                    ("radius", "Radius", "text"),
                ],
            },
            {
                "n": 5, "title": "Competent Person Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── CONCRETE OPERATIONS ─────────────────────────────────────────────────
    #
    # ZERO PRODUCTION RECORDS. See the hot work note above.
    #
    # A CONCRETE SAFETY MANAGER INSTRUMENT, which is why it is major-building
    # only and carries no site-condition toggle. The citation is the
    # registry's corrected pair -- it used to carry §3310.4, the SITE SAFETY
    # COORDINATOR's section, on the CSM's log.
    "concrete_operations": {
        "title": "Concrete Operations Log",
        "subtitle": "Slump tests and formwork inspection — to be maintained "
                    "on site for inspection",
        "cite": "§3310.10 / §3315",
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
                # `weather_conditions` IS THE CHIP THE CP TAPPED, NOT A FETCH.
                # It is one of seven stored words (concreteOperationsModel
                # WEATHER_OPTIONS) and has nothing to do with the daily log's
                # `weather` map, so `weather_line` -- which reads a fetch state
                # and a temperature off a map -- is the wrong formatter and
                # would print the whole-line "could not be retrieved" message
                # over a word the CP chose.
                #
                # volume_ordered and temperature are UNIT-LESS as entered.
                "n": 2, "title": "The Pour", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 3,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("data.pour_location", "Pour Location", "name"),
                    ("data.concrete_supplier", "Supplier", "name"),
                    ("data.mix_design", "Mix Design", "text"),
                    ("data.volume_ordered", "Volume Ordered", "text"),
                    ("data.weather_conditions", "Weather", "text"),
                    ("data.temperature", "Temperature", "text"),
                    # THE CP'S NAME IS A FIELD, NOT ONLY A SIGNATURE
                    # CAPTION. The branch printed "CP: <name>" whenever
                    # `cp_name` was set and independently of the mark; bound
                    # only to the signature section it vanishes with that
                    # section on a record that never carried a `cp_signature`
                    # key. The daily log declares it in both places.
                    ("cp_name", "Competent Person", "name"),
                ],
            },
            {
                # PENDING `pass_fail`. `pass` IS TRI-STATE -- EMPTY_SLUMP_TEST
                # seeds it null -- and the branch prints Pass, Fail, or
                # nothing, never a Fail the CP did not record. `yes_no` is the
                # closest existing formatter and it prints the WRONG TWO
                # WORDS: "Yes" where a filed §3315 record says "Pass". See the
                # request filed with this declaration.
                #
                # PENDING `row_requires`: the branch drops a row with no time,
                # no value and a null verdict. An untouched EMPTY_SLUMP_TEST
                # printing here is a slump test nobody performed.
                "n": 3, "title": "Slump Tests", "primitive": "table",
                "scope": "rows", "path": "data.slump_tests",
                # AN UNTOUCHED `EMPTY_SLUMP_TEST` IS NOT A TEST -- and a
                # RECORDED FAILURE IS. `pass` is tri-state and seeded null, so
                # the value test alone would drop every failed slump off a BC
                # 3315 pour record while keeping the passes: `str(False or "")`
                # is empty. The branch tested all three and asked a different
                # question of the third.
                "row_requires": ["time", "value"],
                "row_requires_present": ["pass"],
                "empty": "none_documented",
                "none_text": "No slump tests recorded.",
                "columns": [
                    ("time", "Time", "text"),
                    ("value", "Slump", "text"),
                    # `pass_fail`, WHICH THE DECLARATION ASKED FOR AND
                    # WHICH NOW EXISTS. Its docstring names this column: a
                    # FAILED slump on a filed BC 3315 record printed "No"
                    # under a heading reading Result. "Fail" and "No" are not
                    # the same word on a compliance document -- one is a
                    # verdict on a test, the other an answer to a question --
                    # and the comparison reported `pass` and `fail` as words
                    # the old sheet had and the new one did not.
                    ("pass", "Result", "pass_fail"),
                ],
            },
            {
                "n": 4, "title": "Formwork Inspection",
                "primitive": "checklist", "scope": "first",
                "path": "data.formwork_checklist",
                "labels": "concrete_formwork", "empty": "none_documented",
                "item_label": "Item", "mark_label": "Confirmed",
                "none_text": "No formwork inspection documented.",
            },
            {
                "n": 5, "title": "Competent Person Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── EXCAVATION MONITORING ───────────────────────────────────────────────
    #
    # ZERO PRODUCTION RECORDS, AND THAT IS THE HARD PART RATHER THAN THE EASY
    # ONE. Every other conversion can be checked against filed documents; this
    # one cannot, now or ever. So the evidence is
    # backend/tests/fixtures/legal_render/excavation_monitoring.json, which
    # exercises all 23 paths the old branch read, and the substitute for a
    # field census is the SCREEN: every path declared below is written by
    # `excavationMonitoringModel.draftBody`, which is the one place the payload
    # shape is decided, so no field here can be the next `areas_visited`.
    #
    # TITLE, SUBTITLE AND CITE ARE THE REGISTRY'S, not the branch's. The branch
    # printed "Excavation Monitoring"; the registry entry has carried the word
    # Log, the subtitle and §3304 all along, and the letterhead has three slots
    # for exactly those three fields.
    "excavation_monitoring": {
        "title": "Excavation Monitoring Log",
        "subtitle": "Adjacent building monitoring & vibration",
        "cite": "§3304",
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
                # THE COMPETENT PERSON'S NAME DOES NOT HANG OFF HIS SIGNATURE,
                # AND THE DIFF IS WHY THIS SECTION EXISTS. The branch printed
                # `CP: <name>` as a line of its own, independent of any mark.
                # The first draft of this schema printed his name only inside
                # the signature block -- which is `empty: omit` and disappears
                # when the record carries no `cp_signature` key at all -- so on
                # three of the eight fixture cases the competent person's name
                # fell off the document entirely. A filed §3304 record naming
                # nobody is the loss this whole comparison exists to catch, and
                # it failed toward looking fine: a tidy sheet, one section
                # shorter.
                #
                # The daily jobsite log already carries his name in a field
                # grid for the same reason; this is that section's shape.
                "n": 2, "title": "The Day", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 2,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("cp_name", "Competent Person", "name"),
                ],
            },
            {
                # `requires_present`, NOT `requires`, AND THE DIFFERENCE IS
                # TWO ANSWERS A PERSON GAVE. The two condition switches are
                # ordinary booleans seeded false -- draftBody writes `!!value`
                # on every save -- so `requires` would test `str(False or "")`,
                # find nothing, and delete a section carrying five labelled
                # answers from any record that answered No to everything. The
                # branch asks the other question through `has()`, which counts
                # a bool as present whatever its value.
                #
                # THE PATHS ARE THE FIELDS' OWN PATHS, all five of them. The
                # daily jobsite log shipped with `requires` naming `data.x` and
                # its field naming `x`, so the section appeared with every cell
                # reading "not recorded" -- the permanent N/A it existed to
                # avoid, reached from the other side.
                "n": 3, "title": "Excavation", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 3,
                "requires_present": [
                    "data.excavation_depth", "data.soil_type",
                    "data.protection_system", "data.groundwater_observed",
                    "data.atmospheric_testing",
                ],
                "fields": [
                    # A RAW NUMBER, AND NO UNIT IS ADDED. The editor captures
                    # none, and a document that supplies one is asserting a
                    # measurement nobody made.
                    ("data.excavation_depth", "Excavation Depth", "text"),
                    ("data.soil_type", "Soil Type", "text"),
                    ("data.protection_system", "Protection System", "text"),
                    # `yes_no`, NOT a checklist: these two have two states and
                    # both are answers. The screen's own comment says so.
                    ("data.groundwater_observed", "Groundwater Observed", "yes_no"),
                    ("data.atmospheric_testing", "Atmospheric Testing", "yes_no"),
                ],
            },
            {
                # `requires` HERE, AND `requires_present` ABOVE, BECAUSE THE
                # TWO SECTIONS ASK DIFFERENT QUESTIONS. The branch gates this
                # block on a READING existing -- `if v_thr or v_cur` -- not on
                # the keys being carried, because with neither reading there is
                # no vibration to annotate and the whole block is dropped.
                # Both paths named are field paths.
                #
                # THE STATUS IS BOUND TO `data`, the way the daily log's
                # weather is: `vibration_status` reads the threshold, the
                # current reading and the derived flag, and is still a
                # formatter of one value because the value is the map. The
                # over-threshold flag is only meaningful ALONGSIDE both
                # readings -- `isOverThreshold` returns false when either is
                # unparseable, which is not the claim "within threshold".
                "n": 4, "title": "Vibration", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 3,
                "requires": ["data.vibration_threshold",
                             "data.vibration_current"],
                "fields": [
                    ("data.vibration_threshold", "Threshold", "text"),
                    ("data.vibration_current", "Current", "text"),
                    ("data", "Status", "vibration_status"),
                ],
            },
            {
                # A MONITORING POINT IS A BUILDING, and `row_requires` is the
                # declaration of that rule. A row carrying a baseline and a
                # current reading with NO ADDRESS is vibration data attributed
                # to no structure: it names no building to inspect, no owner to
                # notify and no work to stop, and the whole purpose of this log
                # is telling the DOB which adjacent building moved.
                #
                # IT CANNOT BE LEFT TO THE DEVICE. `buildingsForFiling` drops
                # these rows at SUBMIT and a DRAFT keeps them, and a draft is
                # rendered.
                #
                # THE READINGS ARE `raw_text`, NOT `text`. A half-taken
                # measurement -- an address and a baseline, no current yet --
                # is a real row, and "— Not recorded" in the empty cell is a
                # finding against a reading nobody has taken yet. The branch
                # leaves it blank and so does this.
                "n": 5, "title": "Adjacent-Structure Monitoring Points",
                "primitive": "table", "scope": "rows",
                "path": "data.adjacent_buildings",
                "row_requires": ["address"],
                "empty": "none_documented",
                "none_text": "No adjacent-structure monitoring points recorded.",
                "columns": [
                    ("address", "Location", "name"),
                    ("baseline_reading", "Baseline", "raw_text"),
                    ("current_reading", "Current", "raw_text"),
                    # DERIVED, NEVER TYPED. `calcDelta` yields '' when either
                    # reading is unparseable, because "no reading" and "no
                    # movement" are opposite findings on an excavation record.
                    ("delta", "Movement (Δ)", "raw_text"),
                ],
            },
            {
                # NOT A CERTIFICATION. The branch printed his name and his mark
                # and asserted nothing on his behalf; inventing an attestation
                # here would put words on a signed §3304 record the signer
                # never said.
                "n": 6, "title": "Competent Person Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── FALL PROTECTION EQUIPMENT LOG ───────────────────────────────────────
    #
    # ZERO PRODUCTION RECORDS. The evidence is
    # backend/tests/fixtures/legal_render/fall_protection.json, exercising all
    # 24 paths the branch read; every row key declared below is in
    # `fallProtectionModel.ROW_KEYS` and set by a control on the screen.
    #
    # NO `cite`, AND THE ABSENCE IS THE POINT. The registry entry carries no
    # `dob_reference` because OSHA 1926.502(d)(21) mandates the INSPECTION and
    # not a written record of it; the documented periodic inspection comes from
    # ANSI Z359, an industry consensus standard, which is not law. The key is
    # absent rather than "" so that nothing can print an empty citation, and
    # this declaration keeps that shape: a missing key, not an empty one.
    "fall_protection": {
        "title": "Fall Protection Equipment Log",
        "subtitle": "Equipment inspection — industry standard, not DOB-required",
        "source": {"kind": "one"},
        # WHAT THE DOCUMENT IS NOT, BELOW THE SIGNATURE. server.py:4820 draws
        # the distinction: a SCOPE line qualifies a document the reader has
        # already read and belongs in the footer; an ATTESTATION says what the
        # signature claims and belongs above it. This is the first, so it is a
        # declaration key rather than a section -- numbered under a grey bar it
        # would read as part of the record, and attached to the signature
        # section it would read as part of the attestation.
        #
        # THE SAME WORDS AS server.FALL_PROTECTION_NOTICE, which is one
        # constant precisely so the app cannot say two different things about
        # what this log is. The engine cannot import server; if this sentence
        # and that constant are ever to differ, the difference must be a
        # decision and not a copy going stale.
        "footer_notice": (
            "OSHA 1926.502(d)(21) requires that this equipment be inspected "
            "before each use. It does not require a written record of each "
            "inspection. This log follows ANSI Z359, an industry consensus "
            "standard, and is not a DOB or OSHA filing."
        ),
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
                # HIS NAME IS NOT PART OF HIS SIGNATURE. Same finding as the
                # excavation log's section 2, found the same way: the signature
                # block is `empty: omit` and vanishes with the key, taking the
                # only printing of `cp_name` with it.
                "n": 2, "title": "The Day", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 2,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("cp_name", "Competent Person", "name"),
                ],
            },
            {
                # THE ROWS LIVE UNDER `activities` and that name is not
                # decoration: `get_logbook_activity_photo` -- the one
                # production read of a logbook photo -- indexes
                # `data.activities[ai].photos[pi]`. Binding anywhere else would
                # mean a second photo reader, and a second reader is how a
                # record and its photographs drift apart.
                #
                # `row_requires` ON `worker_name`: the claim a row makes is
                # that a named man's fall-arrest equipment was inspected, so a
                # nameless row asserts it about somebody the record cannot
                # identify. `rowsForFiling` drops these at submit and a draft
                # keeps them, so the sheet has to draw the line itself.
                "n": 3, "title": "Equipment Inspections",
                "primitive": "table", "scope": "rows",
                "path": "data.activities",
                "row_requires": ["worker_name"],
                "empty": "none_documented",
                "none_text": "No equipment inspections recorded.",
                "columns": [
                    ("worker_name", "Worker", "name"),
                    # `sub_company`, AND THE BRANCH DOES NOT DO THIS -- IT IS
                    # A DEFECT THIS CONVERSION CLOSES BY BINDING THE RULE THAT
                    # ALREADY EXISTS. `buildRowsFromCheckins` copies `company`
                    # straight off the gate check-in, and register_and_checkin
                    # stamps the literal "UNASSIGNED" onto a check-in whose sub
                    # was not on the project roster (server.py:15908). The
                    # branch prints it through `_capitalize_first`, so a filed
                    # fall-protection register can name a worker's firm as
                    # UNASSIGNED -- which is precisely the sentinel-read-as-a-
                    # company that `_display_sub_company` was written to stop
                    # on the daily log, applied to one renderer and not this
                    # one. Reported separately; the formatter is bound here
                    # because the rule is the product's, not this sheet's.
                    #
                    # THE COST IS NAMED: a hand-added row whose company the CP
                    # simply left blank now reads "Pending assignment" rather
                    # than blank, which is a slightly stronger claim than the
                    # record makes. It is the lesser of the two: a pending row
                    # is better than a false firm.
                    ("company", "Company", "sub_company"),
                    ("equipment_type", "Equipment", "name"),
                    # THE MANUFACTURER'S MARKING AND THE DATE AS ENTERED, both
                    # identifiers. Blank is blank: a row whose serial was never
                    # legible is not a row with an unrecorded field.
                    ("equipment_id", "ID / Serial", "raw_text"),
                    ("manufacture_date", "Mfg Date", "raw_text"),
                    # SEEDED NULL, AND A NULL IS NOT A PASS. `inspection_result`
                    # also keeps "Removed from service" as its own verdict:
                    # a failed component on the rack and one taken out of use
                    # are different facts, and collapsing them would be this
                    # renderer grading equipment.
                    ("result", "Result", "inspection_result"),
                    # ABSENT IS NOT NO. 1926.502(d)(19) makes an impact-loaded
                    # component mandatory to remove from service, so a silent
                    # "No" is the answer that keeps it in use.
                    ("impact_loaded", "Impact Loaded", "yes_no"),
                    # `raw_name`, NOT `sentence`. On a row graded Pass
                    # there was nothing to find; "— Not recorded" in that cell
                    # is a finding against a row that has none.
                    ("defect_found", "Defect", "raw_name"),
                    ("action_taken", "Action Taken", "raw_name"),
                    # `raw_name`, NOT `name`. Not every item on this
                    # register has an anchor -- a harness does not -- so a
                    # blank cell is a column that does not apply to the row,
                    # and "— Not recorded" there would be a finding against it.
                    # `raw_text` was the first binding and the diff caught it:
                    # "Roof davit, east parapet" came back lowercase, because
                    # raw_text does not raise the first letter and the branch's
                    # `_capitalize_first` does.
                    ("anchor_point", "Anchor", "raw_name"),
                ],
            },
            {
                "n": 4, "title": "Competent Person Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── SSC / SSM DAILY SAFETY LOG ──────────────────────────────────────────
    #
    # ZERO PRODUCTION RECORDS. The evidence is
    # backend/tests/fixtures/legal_render/ssc_daily_safety_log.json, exercising
    # all 22 paths the branch read. The payload is thirteen frozen top-level
    # keys and `sscDailySafetyLogModel.draftBody` writes every one of them on
    # every save, so no path below can go missing and none can be unwritten.
    #
    # THE WEATHER IS `text`, NOT `weather_line`, AND THAT IS A DECISION. This
    # log's weather is one of seven chips the coordinator taps; the daily
    # jobsite log's is FETCHED, and every rule `weather_line` holds -- the
    # fetch state overriding the values, wind appended -- is a rule about a
    # reading this form never takes. Declaring it here would assert this log
    # fetches weather, and would blank a chip somebody actually tapped the day
    # a `weather_fetch_state` key ever appeared in this payload. See the
    # report: on every payload `draftBody` can produce the two render
    # identically today, so this is a choice about meaning, not appearance.
    "ssc_daily_safety_log": {
        "title": "SSC/SSM Daily Safety Log",
        "subtitle": "Site Safety Coordinator/Manager daily report",
        "cite": "§3310.4/§3310.5",
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
                # THE SIGNER'S NAME, NOT HANGING OFF HIS MARK. Same finding as
                # the other two logs. It is separate from section 3 as well as
                # from the signature: section 3 is gated on four payload keys,
                # so a log whose site block was never filled would otherwise
                # print no name either.
                "n": 2, "title": "The Day", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 2,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("cp_name", "SSC / SSM", "name"),
                ],
            },
            {
                # THE PAYLOAD'S OWN ADDRESS, NOT THE PROJECT'S, AND BOTH ARE ON
                # THE SHEET. `prefillFromProject` copies the address and the
                # SSP number onto the record at creation; the project document
                # can be edited afterwards and this one cannot. Section 1 says
                # where the job is now, this says what the coordinator signed.
                # Reconciling them would delete one of two true statements.
                #
                # PLAIN `requires`, because all four are strings: an empty
                # string here is a key nothing wrote, which is the question
                # `requires` already asks. The branch's `has()` agrees on
                # strings and only diverges on booleans, which are section 3.
                "n": 3, "title": "Site", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 2,
                # `requires_present`, NOT `requires`. The value test reads
                # `str(0 or "")` as empty, so a site with a RECORDED ZERO men
                # on it deleted this whole section -- address, safety plan
                # number and weather with it -- and the sheet numbered itself
                # 1, 2, 4. A count of zero is an answer.
                "requires_present": ["data.project_address", "data.ssp_number",
                                     "data.weather",
                                     "data.workers_on_site_count"],
                "fields": [
                    ("data.project_address", "Project Address", "text"),
                    ("data.ssp_number", "Site Safety Plan #", "text"),
                    ("data.weather", "Weather", "text"),
                    ("data.workers_on_site_count", "Workers on Site", "text"),
                ],
            },
            {
                # FIVE BOOLEANS SEEDED FALSE, so `requires_present` for the
                # same reason excavation's switches need it: `requires` would
                # delete this section from a record that answered No five
                # times, which is a record with five answers on it.
                #
                # A FIELD GRID, NOT A CHECKLIST, AND THE PRIMITIVE'S OWN
                # DOCSTRING IS WHY. `checklist` draws THREE states over a
                # stored map at one path; these are five flat top-level keys
                # with two states each, and a tickbox would put "answered No"
                # and "never asked" on one axis -- the error that primitive
                # records having had to undo once.
                #
                # THE CAVEAT IS THE SECTION'S, NOT THE DOCUMENT'S. A rendered
                # "No" here may be an untouched default rather than a
                # deliberate negative finding, and on a DOB record a bare "No"
                # beside "Fire Protection in Place" read as an affirmative
                # safety-violation attestation is a finding nobody made.
                "n": 4, "title": "Compliance", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 3,
                "requires_present": [
                    "data.incidents_reported", "data.safety_meetings_held",
                    "data.fire_protection_in_place",
                    "data.housekeeping_satisfactory", "data.ppe_compliance",
                ],
                "note": ('Compliance items default to "No" if not explicitly '
                         'set by the reviewer.'),
                "fields": [
                    # THE LABELS ARE COMPLIANCE_FLAGS', WORD FOR WORD.
                    # portedFormPayloads.test.cjs pins the device's list
                    # against this renderer's; a better wording here would be
                    # an improvement to a document that has been signed.
                    ("data.incidents_reported", "Incidents Reported", "yes_no"),
                    ("data.safety_meetings_held", "Safety Meetings Held", "yes_no"),
                    ("data.fire_protection_in_place", "Fire Protection in Place", "yes_no"),
                    ("data.housekeeping_satisfactory", "Housekeeping Satisfactory", "yes_no"),
                    ("data.ppe_compliance", "PPE Compliance", "yes_no"),
                ],
            },
            {
                # THE GATE NAMES A PATH THAT IS NOT A FIELD, DELIBERATELY, AND
                # THIS IS THE ONE PLACE IN THESE THREE SCHEMAS THAT DOES IT.
                # The branch's rule is `show_incident or any(has(...))`: once
                # an incident is REPORTED the three prompts are accounted for
                # whether or not they were written, because an unanswered
                # prompt on a day something happened is an unanswered question
                # rather than silence. Dropping `data.incidents_reported` from
                # this list would lose three labelled absences on exactly the
                # days they matter most.
                #
                # NOT THE daily-jobsite TRAP. That was `data.time_in` in the
                # gate and `time_in` in the field -- one path spelled two ways,
                # so the section appeared with every cell reading "not
                # recorded". Here the three field paths are all in the list and
                # spelled identically; the fourth is a condition, not a field.
                #
                # PER ROW 1. Prose the coordinator typed, full width, the way
                # the daily log's visitors line is -- these are prompts with
                # answers, not an essay, and `narrative` binds one path.
                "n": 5, "title": "Narrative", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 1,
                "requires": ["data.site_conditions",
                             "data.safety_violations_observed",
                             "data.corrective_actions_taken",
                             "data.incidents_reported"],
                "fields": [
                    ("data.site_conditions", "Site Conditions", "sentence"),
                    ("data.safety_violations_observed",
                     "Safety Violations Observed", "sentence"),
                    ("data.corrective_actions_taken",
                     "Corrective Actions Taken", "sentence"),
                ],
            },
            {
                # ON THE SHEET ONLY WHEN AN INCIDENT WAS REPORTED, and then
                # ALWAYS -- "— Not recorded" here is the unanswered question
                # the branch insists on. `requires` on a boolean is exactly an
                # is-true test: `str(True or "")` is truthy and
                # `str(False or "")` is not.
                #
                # `incident_details` IS CARRIED WHETHER OR NOT THE FLAG IS SET
                # -- draftBody says so, so it is not deleted when somebody
                # un-ticks the flag by mistake -- and this section is why that
                # detail stays off the page until the flag says it belongs.
                "n": 6, "title": "Incident", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 1,
                "requires": ["data.incidents_reported"],
                "fields": [
                    ("data.incident_details", "Incident Details", "sentence"),
                ],
            },
            {
                # THE ROLE IS THE SIGNER'S, NOT THE COMPETENT PERSON'S. The
                # branch labels this block "SSC / SSM Signature" and that is
                # who signs a §3310.4 log; printing "Competent Person" would
                # name the wrong office on a filed record.
                "n": 7, "title": "SSC / SSM Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "SSC / SSM",
            },
        ],
    },

    # ── TOOL BOX TALK ───────────────────────────────────────────────────────
    #
    # 63 FILED RECORDS, 393 ATTENDEE ROWS, AND IT IS THE SUITE'S WHOLE-DOCUMENT
    # SPECIMEN. Six test files render a toolbox talk to assert something about
    # the document SHELL rather than about this type -- the frozen marker, the
    # letterhead, the status line. Converting it moves what those tests are
    # looking at, so each one is repointed at a type the branch still renders
    # rather than deleted; a shell assertion that stops running is a gate that
    # reports "fine" because it no longer asks.
    "toolbox_talk": {
        "title": "Tool Box Talk",
        # THE REGISTRY'S OWN WORDS. The branch's title was the bare label and
        # its subtitle existed nowhere; the registry keeps a label, a subtitle
        # and a citation, which is what the letterhead has slots for.
        "subtitle": "OSHA 29 CFR 1926.21 — weekly per company, "
                    "to be maintained on site for inspection",
        "cite": "OSHA 1926.21",
        "source": {"kind": "one"},
        "sections": [
            {
                "n": 1, "title": "Site Information", "primitive": "field_grid",
                # `none_documented`, NOT `omit`, FOR THE REASON THE DAILY LOG
                # LEARNED IT: a project-scoped section is "empty" when the
                # record names a site that is not in the projects collection,
                # and under `omit` those sheets simply have no Site Information
                # on them. A reader cannot tell a dropped section from a site
                # nobody recorded. All 63 of these resolve today; A18 is the
                # mechanism that makes that a fact about today.
                "scope": "project", "empty": "none_documented",
                "none_text": ("The project this record names is not on file, "
                              "so the site could not be identified."),
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
                # `location` IS KEPT BESIDE THE JOB ADDRESS, NOT FOLDED INTO
                # IT. On 55 of the 63 filed records the two are the same
                # string, which is exactly why dropping it looks safe -- but it
                # is a free-text field the CP types to say WHERE ON THE SITE
                # the talk was held, and on the sheets where it differs that is
                # the only thing on the document that says so.
                "n": 2, "title": "The Talk", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 2,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("data.meeting_time", "Time", "time_of_day"),
                    ("data.location", "Location", "name"),
                    ("data.company_name", "Company", "name"),
                    ("data.performed_by", "Performed By", "name"),
                    # THE CP'S NAME IS A FIELD, NOT ONLY A SIGNATURE CAPTION,
                    # AND THE COMPARISON IS WHY. The branch printed "CP: <name>"
                    # whenever `cp_name` was set and INDEPENDENTLY of the mark;
                    # bound only to the signature section it disappears with
                    # that section on any record that never carried a
                    # `cp_signature` key -- and one filed toolbox record in the
                    # baseline prints "CP: Roy fishman" with no signature block
                    # at all. The daily log declares it in both places for the
                    # same reason.
                    #
                    # IT IS NOT THE SAME FIELD AS `performed_by`. Usually the
                    # same man, occasionally not: one filed record names the
                    # CP and a different person as having given the talk.
                    ("cp_name", "Competent Person", "name"),
                ],
            },
            {
                # A SENTENCE, NOT A CHECKLIST, AND THAT IS THE DAILY LOG'S
                # UNRULED HALF REACHED AGAIN. The 21 topic keys ARE a fixed set
                # (toolboxTalkModel.js TOPICS) so a label set could exist and a
                # checklist would be the more honest rendering -- it would
                # close the gap where a stored `false` is indistinguishable
                # from never having been asked, and it would print the words
                # the CP actually tapped instead of the key-derived ones.
                #
                # IT WOULD ALSO VISIBLY CHANGE 63 FILED DOCUMENTS, from "these
                # topics were covered" into "here are 21 topics and here is
                # which ones were". That is a change of substance and it is the
                # operator's call, not a restyle's. `toggle_list` prints
                # exactly what the branch printed -- the truthy keys,
                # title-cased from the key -- so the choice stays open and
                # nothing moves.
                #
                # `covid19` IS WHY THE LABEL SET CANNOT SIMPLY BE ADOPTED
                # EITHER: the key was removed from TOPICS by an operator ruling
                # and filed records still carry it true. A label set keyed on
                # today's 21 would drop it from the sheets that hold it.
                #
                # FIVE OF THE 63 CARRY AN EMPTY MAP and the branch prints None
                # for them. That is a seeded form the CP ticked nothing on, and
                # `toggle_list` had been folding it in with the absent one --
                # see the note on that function, and the 32 daily records it
                # had already cost.
                "n": 3, "title": "Topics Covered", "primitive": "narrative",
                "scope": "first", "path": "data.checked_topics",
                "formatter": "toggle_list", "empty": "none_documented",
            },
            {
                # THE ROSTER, AND THE §3301.12.3 FIELDS ARE ITS COLUMNS: name,
                # title, company, time. Nothing is added to them -- `signed`
                # and `gate_confirmed` are stored on every row and the branch
                # deliberately stopped printing them as columns, because
                # neither is an attestation and two tick columns beside the
                # CP's signature invite the reading that signature forecloses.
                #
                # `row_requires` ON `name`, WHICH IS THE BRANCH'S OWN GUARD.
                # Three of the 393 filed rows have no name: a seed row the CP
                # never filled, printing as a blank line on a signed attendance
                # record -- a man who was at the talk and cannot be identified
                # by anybody reading it. The branch drops them and so does
                # this. Same rule the pre-shift sheet and the OSHA register
                # already carry.
                "n": 4, "title": "Attendance", "primitive": "table",
                "scope": "rows", "path": "data.attendees",
                "row_requires": ["name"],
                "empty": "none_documented",
                "none_text": "No attendees recorded.",
                "columns": [
                    ("name", "Name", "name"),
                    # `raw_name`, WHICH IS THE ONE WRITTEN FOR THIS COLUMN --
                    # its docstring names the toolbox attendee. The ROW is the
                    # record here, so a man whose trade the CP did not type is
                    # blank on the paper rather than carrying a finding against
                    # himself; 21 filed rows have no title and 14 no company.
                    #
                    # AND IT CAPITALISES, WHICH `raw_text` DOES NOT. The branch
                    # ran `_capitalize_first` over both, so a row read "Foreman"
                    # and under `raw_text` it read "foreman". The word diff
                    # cannot see that -- `words()` lowercases both sides before
                    # it compares -- and a unit test caught it instead. Fourth
                    # time an instrument has been narrower than its subject.
                    ("title", "Title", "raw_name"),
                    ("company", "Company", "raw_name"),
                    # NEW YORK, NOT UTC. 221 of the 393 rows hold an anchored
                    # instant the gate wrote, and printing its digits put a man
                    # at the gate four hours after he walked through it. The
                    # conversion lives in `formatters` now for exactly this
                    # reason -- the engine cannot import server.py, and a
                    # second copy of the rule beside the first is how the four
                    # hours got written in the first place.
                    ("time", "In", "roster_clock"),
                    # THE PROVENANCE IN WORDS, FROM A CLOSED SET. `text` would
                    # print the stored token, so a filed attendance record
                    # would read `weekly_gap` under a column headed "Added by".
                    ("added_from", "Added by", "attendee_source"),
                ],
            },
            {
                # HIS MARK OVER THE WHOLE ROSTER, which is the only legal
                # attestation on this document. `omit` plus the engine's
                # signature rule keep the branch's own line: a record carrying
                # the key and no mark says UNSIGNED, and a record that never
                # carried it prints no section.
                "n": 5, "title": "Competent Person Signature",
                "primitive": "signature", "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "Competent Person",
            },
        ],
    },

    # ── DAILY JOBSITE LOG ───────────────────────────────────────────────────
    #
    # THE LARGEST, THE MOST READ, AND THE ONE THAT WILL EVENTUALLY DECLARE
    # `combined` WITH THE SUPERINTENDENT LOG. 59 filed records across 6
    # projects; 39 of them carry one crew and the tail runs to eight.
    #
    # TITLE, SUBTITLE AND CITE COME FROM LOGBOOK_TYPE_REGISTRY rather than
    # being retyped. The old branch welded the form number into the name --
    # "Daily Jobsite Log (NYC DOB 3301-02)" -- and the registry already keeps
    # the name, the form number and the code section as three fields, which is
    # what the letterhead has three slots for.
    #
    # `areas_visited` IS NOT HERE, and its absence is the point. It was
    # carried on 50 of 59 records, non-empty on none of 360 including the
    # deleted ones, and printed "Areas Visited: N/A" on every filed daily log
    # ever rendered. It is gone from the screen, the payload and this
    # declaration together: the log does not record where a person visited, it
    # records where the WORK is, and the crew rows already carry that.
    "daily_jobsite": {
        "title": "Daily Jobsite Log",
        # THE FORM NUMBER STAYS ON THE SHEET. The old title welded it into the
        # name -- "Daily Jobsite Log (NYC DOB 3301-02)" -- and the first draft
        # of this schema dropped it for the code section alone. The diff caught
        # it on 58 of 59 records: an inspector asks for the 3301-02 by that
        # number, and a document that does not carry it is harder to file
        # against. The registry keeps both, so the sheet does too.
        "subtitle": "NYC DOB 3301-02 — to be maintained on site for inspection",
        "cite": "§3301.2",
        "source": {"kind": "one"},
        "sections": [
            {
                "n": 1, "title": "Site Information", "primitive": "field_grid",
                # `none_documented`, NOT `omit`, AND THE DIFFERENCE IS REAL.
                #
                # A project-scoped section is "empty" when the render context
                # has no project. For this type that is not a section which
                # does not apply -- it is a filed record naming a site that is
                # not in the projects collection. Two of the 59 do, and 9 of
                # 317 across four types, and under `omit` those sheets had no
                # Site Information at all: a reader cannot tell a dropped
                # section from a site nobody recorded.
                #
                # FOUND BY THE BRANCH-DELETION PROOF, which counted how many
                # records carried the engine's own markers and got 57 of 59.
                # The local old-against-new diff could NOT see it: that corpus
                # stored only the projects that RESOLVED, so both renderers
                # were handed a project and the two orphans silently borrowed
                # one. A comparison corpus that drops what it cannot resolve
                # hides precisely the records worth looking at.
                "scope": "project", "empty": "none_documented",
                "none_text": ("The project this record names is not on file, "
                              "so the site could not be identified."),
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
                # THE WEATHER FIELD IS BOUND TO `data` ITSELF, not to a key.
                # `weather_line` reads four of them -- condition, temperature,
                # wind and the fetch state that overrides all three -- and it
                # is still a formatter of ONE VALUE, because the value it is
                # handed is the map.
                #
                # THE DESCRIPTION IS A FIELD, NOT A NARRATIVE. Measured on the
                # 59 records: non-empty on 52, median 20 characters, longest
                # 79. A full-width flowing block for twenty characters is a
                # design asserting an essay that nobody wrote.
                "n": 2, "title": "The Day", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 2,
                "fields": [
                    ("date", "Date", "date_long"),
                    ("data", "Weather", "weather_line"),
                    ("cp_name", "Competent Person", "name"),
                    ("data.general_description", "Description", "sentence"),
                ],
            },
            {
                # DECLARED WITH `requires`, WHICH IS WHY IT IS SAFE TO DECLARE
                # AT ALL. Nothing has written these two keys since the picker
                # work; without `requires` this section would print two "not
                # recorded" cells on all 59 filed records, reinstating the
                # permanent N/A the old branch deliberately removed.
                #
                # CONDITIONAL RATHER THAN DELETED, and the difference matters
                # on a signed record: a log filed BEFORE that rebuild may
                # carry real times, and deleting the section outright would
                # remove them from a document that has already been read.
                "n": 3, "title": "Working Hours", "primitive": "field_grid",
                "scope": "first", "empty": "omit", "per_row": 2,
                "requires": ["data.time_in", "data.time_out"],
                "fields": [
                    # THE SAME PATHS `requires` NAMES. The first draft wrote
                    # these two relative to the record and the `requires`
                    # relative to its data map, so the section appeared and
                    # both cells read "not recorded" -- the permanent N/A this
                    # section exists to avoid, reached from the other side.
                    ("data.time_in", "Time In", "time_of_day"),
                    ("data.time_out", "Time Out", "time_of_day"),
                ],
            },
            {
                # "CP'S COUNT", NOT "WORKERS". This number is hand-typed by
                # the competent person on the crew row; the report's headcount
                # is counted at the GATE from check-ins. They disagree -- four
                # here, three there -- and both are true statements about
                # different things. Labelled at the point of use rather than
                # reconciled, because silently picking one would delete a fact.
                #
                # `.` IS THE ROW. `cp_headcount` reads three keys off it.
                "n": 4, "title": "Crew and Work Performed",
                "primitive": "table", "scope": "rows",
                "path": "data.activities", "empty": "none_documented",
                "none_text": "No crews recorded on site.",
                "columns": [
                    ("crew_id", "Crew", "text"),
                    ("company", "Company", "sub_company"),
                    (".", "CP's count", "cp_headcount"),
                    ("work_description", "Description", "sentence"),
                    ("work_locations", "Location", "text"),
                ],
            },
            {
                # A SENTENCE, NOT A GRID, AND THAT IS THE UNRULED HALF. The
                # five keys are a fixed set the screen shows as tickboxes, so
                # the checklist primitive would be the more honest rendering
                # and would close the gap where a stored `false` is
                # indistinguishable from never having been asked. It would
                # also visibly change a filed document, which is the operator's
                # call and not a restyle's -- so this keeps exactly what the
                # sheet says today and the choice stays open.
                "n": 5, "title": "Equipment on Site", "primitive": "narrative",
                "scope": "first", "path": "data.equipment_on_site",
                "formatter": "toggle_list", "empty": "none_documented",
            },
            {
                "n": 6, "title": "Daily Inspections",
                "primitive": "inspection_log", "scope": "first",
                "path": "data.checklist_items", "labels": "inspection_items",
                "other_key": "other_checklist", "empty": "none_documented",
                "none_text": "No inspections documented.",
                # WITHOUT THIS a record carrying no checklist map rendered a
                # numbered section bar with nothing beneath it, because
                # emptiness defaults to "were any records filed" and one was.
                "requires": ["data.checklist_items"],
            },
            {
                # `corrected_immediately` IS NOT A COLUMN HERE. It is recorded
                # on 5 observations, true on 1, and printed by nothing -- a
                # live defect (A16), not something a conversion gets to fix on
                # its own. Adding a column to a filed document is a change of
                # substance and it is recorded rather than taken.
                "n": 7, "title": "Safety Observations", "primitive": "table",
                "scope": "rows", "path": "data.observations",
                "empty": "none_documented",
                "none_text": "No safety observations recorded.",
                "columns": [
                    ("description", "Observation", "sentence"),
                    ("responsible_party", "Responsible", "name"),
                    ("remedy", "Remedy", "sentence"),
                ],
            },
            {
                # Non-empty on 31 of 59, longest 55 characters. A field, for
                # the same reason the description is one.
                "n": 8, "title": "Visitors and Deliveries",
                "primitive": "field_grid", "scope": "first", "empty": "omit",
                "requires": ["data.visitors_deliveries"], "per_row": 1,
                "fields": [
                    ("data.visitors_deliveries", "Recorded", "sentence"),
                ],
            },
            {
                # NOT A CERTIFICATION, and the distinction is deliberate. The
                # orientation sheet ends with a sworn sentence over the CP's
                # mark because that document carries one. This one does not:
                # the old branch printed his name, his signature and the
                # superintendent's, and asserted nothing on his behalf.
                # Inventing an attestation sentence here would put words on a
                # signed 3301.2 record that the signer never said.
                "n": 9, "title": "Competent Person Signature",
                "primitive": "signature",
                "scope": "first", "empty": "omit",
                "path": "cp_signature", "name_path": "cp_name",
                "role": "Competent Person",
            },
            {
                # ABSENT ON ALL 59 RECORDS, so `omit` and the engine's
                # signature rule drop it exactly as the old branch did --
                # `render_signature_html` returns "" on a falsy signature.
                # Declared anyway, because the combined sheet will need it and
                # a section that renders nothing costs nothing.
                "n": 10, "title": "Superintendent Signature",
                "primitive": "signature",
                "scope": "first", "empty": "omit",
                "path": "data.superintendent_signature",
                "name_path": "data.superintendent_name",
                "role": "Superintendent",
            },
        ],
    },

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
