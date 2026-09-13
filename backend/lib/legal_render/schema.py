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
