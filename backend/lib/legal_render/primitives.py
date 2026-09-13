"""THE EIGHT BUILDING BLOCKS, AND THE ONE VISUAL SYSTEM THEY SHARE.

Every legal log is composed from these. The DATA decides what appears; this
file decides how it appears, and it decides it once for all fifteen types.

── WHAT THE DESIGN IS ────────────────────────────────────────────────────────

Paperwork from a professional site's physical legal logbook. Black on white,
numbered rectangular sections under light-grey header bars, thin rules, dense
tables, labels smaller than the values they name. Four type weights and no
more. No cards, no shadows, no rounded corners, no icons, no colour.

NOTHING MAY LOOK EDITABLE. There are no input boxes and no field outlines: a
box around a value on a filed record reads as a slot still waiting to be
filled, on a document whose whole point is that it already was.

── AND WHAT IT IS NOT ────────────────────────────────────────────────────────

It borrows the DOCUMENT LANGUAGE of the DOB forms it sits beside; it does not
impersonate them. No NYC logo, no Buildings mark, no seal, no form number. The
citations are ours and they are real -- they come from the type registry's
`dob_reference`. Company identity is plain text, subordinate to the record.

── SIGNATURES ARE NOT LIKE ANY OTHER VALUE ───────────────────────────────────

A captured signature is a transparent handwritten stroke laid on the paper. No
box, no background, true aspect ratio, and it may overlap the baseline as a
real one does.

AND IT SITS IN ITS LINE. UNBOXED IS NOT UNBOUNDED, which is how the first
sheet came out: the vector path capped at 140x60 and the raster path capped
width only and left height automatic, so ink drawn at a median of 88px stood
beside 10.5px text and SET the row height rather than sitting inside it. Rows
that hold only text are 16.3px; attendee rows were 91 to 104.

`_INK_MAX_H` is the cap, applied to both paths, and aspect is preserved in
both: the vector by passing it as the SVG's height bound, the raster by giving
the image a height and an automatic width. Neither draws a container -- the
height is a bound on the ink, not a box around it.

BOTH KINDS REACH THIS SHEET, AND THE FIELD DECIDES WHICH. `cp_signature` is
vector stroke paths -- 297 of 303 of them -- and renders as polylines with
`fill="none"`, transparent by construction. `data.worker_signature` is NOT:
72 of those are raster data URIs written by the gate, and the first real sheet
rendered in production was 16 rasters against one vector certification.

Reporting that census as "297 of 303 signatures are vector, zero base64" was a
field-scoped count stated as a global claim, and it is recorded as one in the
harness document. The raster path is not a fallback to tolerate; it is what
most attendee rows on a real sheet are made of.

Both are transparent in the end, for different reasons: the vector by having
no backdrop, and the raster because all 16 PNGs on that sheet carry an alpha
channel. The white box that used to sit behind a signature came from the SVG
wrapper's style string, which `boxed=False` removes -- it was never the ink.

The reconstruction is NOT duplicated here. `server._signature_paths_to_svg`
already turns stroke paths into an SVG and is used by every other renderer; it
now takes `boxed=False` and this passes it. Two copies of that geometry would
drift, and the repository has been bitten by exactly that twice.
"""

from __future__ import annotations

import html as _html
from typing import Any, Dict, List

from .formatters import FORMATTERS, NOT_RECORDED
from .schema import LABEL_SETS, ROW_FORMATTERS

# THE ATTESTATION REGISTRY IS A LEAF -- typing only, no server import -- so the
# sentence a signer was SHOWN is referenced rather than retyped.
#
# RETYPING IT IS WRONG ON THE FIRST CHARACTER. The registry text is already
# HTML-escaped and `certification` escapes what it is handed, so a copy turns
# `worker's` into `worker&#39;s` on the page. And the whole value of that
# registry is that every signature event stores the exact text the signer read,
# so a snapshot can be checked against it -- a second copy makes that check a
# comparison between two guesses.
try:
    from ..logbook.attestations import ATTESTATIONS as _ATTESTATIONS
except Exception:  # pragma: no cover - a caller without the logbook package
    _ATTESTATIONS = {}

# THE ATTESTATION REGISTRY IS A LEAF -- typing only, no server import -- so the
# sentence a signer was SHOWN is referenced rather than retyped.
#
# RETYPING IT IS WRONG ON THE FIRST CHARACTER. The registry text is already
# HTML-escaped and `certification` escapes what it is handed, so a copy turns
# `worker's` into `worker&#39;s` on the page. And the whole value of that
# registry is that every signature event stores the exact text the signer read,
# so a snapshot can be checked against it -- a second copy makes that check a
# comparison between two guesses.
try:
    from ..logbook.attestations import ATTESTATIONS as _ATTESTATIONS
except Exception:  # pragma: no cover - a caller without the logbook package
    _ATTESTATIONS = {}

# ── THE FOUR WEIGHTS. There are no others. ─────────────────────────────────
_TITLE = "font:700 20px Helvetica,Arial,sans-serif;letter-spacing:-0.01em"
_SECTION = ("font:700 10px Helvetica,Arial,sans-serif;letter-spacing:0.08em;"
            "text-transform:uppercase")
_BODY = "font:400 10.5px Helvetica,Arial,sans-serif"
_LABEL = "font:400 8px Helvetica,Arial,sans-serif;letter-spacing:0.04em;color:#555"

#: HOW TALL INK MAY BE. Body text is 10.5px and a text-only row is 16.3px, so
#: this is roughly the height of the line the signature sits in -- which is
#: where a signature sits on the paper this document imitates. Both the vector
#: and the raster path are bound by it, and both keep their aspect.
_INK_MAX_H = 22
#: The width bound, reached only by ink wider than about 6:1.
_INK_MAX_W = 140

_RULE = "1px solid #9a9a9a"
_HAIRLINE = "1px solid #c8c8c8"
_BAR = "#ececec"


def _get(rec: Any, path: str) -> Any:
    """A dotted path into a record. Missing is None, never an exception --
    a schema naming a field this record does not carry is an ordinary state
    on a form, not a crash."""
    cur = rec
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _has(rec: Any, path: str) -> bool:
    """Whether the record CARRIES the key at all, null or not.

    `_get` cannot answer this -- it returns None for both -- and for a
    signature the difference is the whole meaning. The manual-entry path writes
    `worker_signature: null`, and an acknowledgment that was asked for and left
    unsigned must say UNSIGNED. A record that never had the key was filled on a
    form that never asked, and printing UNSIGNED there would be this renderer
    making an accusation the record does not support.
    """
    parts = str(path).split(".")
    cur = rec
    for part in parts[:-1]:
        if not isinstance(cur, dict):
            return False
        cur = cur.get(part)
    return isinstance(cur, dict) and parts[-1] in cur


def _fmt(rec: Any, path: str, formatter: str) -> str:
    return FORMATTERS[formatter](_get(rec, path))


def _section_open(sec: Dict) -> str:
    """The numbered grey bar every section wears. `break-inside: avoid` on the
    wrapper and `break-after: avoid` on the bar, so a heading is never the last
    thing on a sheet with its content overleaf."""
    n = sec.get("n")
    label = f"{n}. {sec.get('title', '')}" if n else sec.get("title", "")
    return (
        '<div style="break-inside:avoid;margin:0 0 10px 0;">'
        f'<div style="{_SECTION};background:{_BAR};border:{_RULE};'
        'padding:3px 6px;break-after:avoid;page-break-after:avoid;">'
        f'{_html.escape(label)}</div>'
    )


def _section_close() -> str:
    return "</div>"


def _empty_note(text: str = "None documented.") -> str:
    """THE RESTRAINED LEGAL ENTRY. A category the record establishes as empty
    is SAID to be empty; it is not visually deleted. Removing the heading would
    make a reader count sections and get a different answer from the log."""
    return (f'<div style="{_BODY};padding:4px 6px;border:{_RULE};'
            f'border-top:none;color:#333;">{_html.escape(text)}</div>')


# ══════════════════════════════════════════════════════════════════════════
#  PRIMITIVES
# ══════════════════════════════════════════════════════════════════════════

def field_grid(sec: Dict, rec: Any, ctx: Dict) -> str:
    """Label above value, in cells, on a strict grid. Labels are smaller and
    lighter than what they name -- the value is the record."""
    fields: List = sec.get("fields") or []
    cells = ""
    per_row = sec.get("per_row", 3)
    for i in range(0, len(fields), per_row):
        chunk = fields[i:i + per_row]
        cells += "<tr>"
        for path, label, formatter in chunk:
            cells += (
                f'<td style="border:{_HAIRLINE};padding:3px 6px;'
                f'width:{100 // per_row}%;vertical-align:top;">'
                f'<div style="{_LABEL}">{_html.escape(label)}</div>'
                f'<div style="{_BODY}">{_fmt(rec, path, formatter)}</div></td>')
        # Pad so the last row's cells keep the width of the first row's.
        for _ in range(per_row - len(chunk)):
            cells += f'<td style="border:{_HAIRLINE};"></td>'
        cells += "</tr>"
    return (f'<table style="width:100%;border-collapse:collapse;'
            f'border:{_RULE};">{cells}</table>')


def cp_headcount(row: Any, ctx: Dict = None) -> str:
    """A crew row's headcount, SAYING WHERE THE NUMBER CAME FROM.

    A daily 3301.2 log carries two headcounts from two provenances: the gate
    table, computed from the check-ins, and the crew rows, which print what the
    CP typed. Until this existed the crew row never said which kind it was, so
    a number a person typed and a number a turnstile counted printed
    identically on a signed record.

    `4 (CP) - gate recorded 6` is the whole reason `gate_num_workers` is
    retained: if the CP's correction simply replaced the turnstile's number,
    nothing downstream -- an inspector, an audit, this renderer -- could tell
    that a person had changed a gate count, or what it had been.

    ABSENCE MEANS GATE. Drafts written before `num_workers_source` existed
    carry no marker and hold numbers that came from the roster; labelling
    those "(CP)" would put a false attribution on records already filed.

    AN EMPTY HEADCOUNT IS "0", NOT "not recorded". That is this document's
    existing spelling for a crew row with no number on it, and it is frozen:
    the literal zero is a count, and the phrase would be a different claim.
    """
    act = row if isinstance(row, dict) else {}
    raw = act.get("num_workers", "")
    text = str(raw).strip() if raw is not None else ""
    if text == "":
        return "0"
    if act.get("num_workers_source") != "cp":
        return _html.escape(text)
    gate = act.get("gate_num_workers")
    gate_text = str(gate).strip() if gate is not None else ""
    if gate_text == "":
        # A hand-added crew: the CP's own assertion, with no gate count to
        # stand over. It is still his number and still says so.
        return _html.escape(f"{text} (CP)")
    return _html.escape(f"{text} (CP) - gate recorded {gate_text}")


def preshift_signature(row: Any, ctx: Dict = None) -> str:
    """A worker's sign-in mark, in three states, from three keys off one row.

    THE THREE ARE DIFFERENT CLAIMS and the old renderer drew all three:

        a mark on file        the roster carries his signature
        no signature on file  he is on the roster and signed nothing
        image unavailable     a signature was recorded and cannot be shown

    THE THIRD IS NOT THE SECOND. A resolution that failed is not a man who did
    not sign, and collapsing them puts a deficiency on a filed record against
    somebody who has none.
    """
    w = row if isinstance(row, dict) else {}
    # `worker_signature` FIRST, WHICH IS WHAT THE ROSTER ACTUALLY STORES.
    # The first version read only `signature` and drew nothing: 291 marks on
    # 49 filed rosters, gone, and the word diff saw five unrelated words. The
    # branch has always read this key first and the order is its order.
    sig = (w.get("worker_signature") or w.get("signature")
           or w.get("signature_data"))
    if sig:
        # ── THE MARK ITSELF, NOT A SENTENCE ABOUT IT ────────────────────
        #
        # The first version of this returned the words "Signature on file",
        # and the old-against-new comparison caught what that cost: 291
        # signature images on the branch's sheets, ZERO on the engine's,
        # across 49 filed rosters. A man's own mark on a compliance record
        # replaced by a claim that it exists.
        #
        # AND THE WORD DIFF ALONE WOULD NOT HAVE SEEN IT -- it would have
        # reported five lost words, none of them about a signature. It was
        # found by counting image tokens, which the comparison could not do
        # until the instrument was repaired two days ago.
        # THE MARK AND THE WORDS, WHICH IS WHAT THE BRANCH PRINTS. The
        # image is the evidence; the line beneath it is the CLAIM, and a
        # reader of a filed roster needs the claim even where the ink renders.
        # Dropping it cost the phrase on 30 of 49 sheets -- caught by the same
        # comparison, one pass after it caught the images themselves.
        return (ink(sig, ctx or {}, present=True)
                + f'<div style="{_LABEL}">Signature on file</div>')
    if w.get("signin_id") or w.get("signature_unavailable"):
        # RECORDED AND NOT DRAWABLE. The resolution runs before render and
        # inlines what it found; an id with nothing behind it is a lookup that
        # came back empty, not a refusal to sign.
        return "Signature on file &mdash; image unavailable"
    return ('<span style="color:#b91c1c;">NO SIGNATURE ON FILE</span>')


def osha_cert_type(row: Any, ctx: Dict = None) -> str:
    """The certification class the card prints, and whether it could be read.

    NOTHING IS RESOLVED AT RENDER TIME. The register prints what the row
    stores; a class derived from a card's colour, or a live certificate joined
    in now, would make a filed document say something its own record does not.

    THE UNVERIFIED MARKER IS AN OBSERVATION, NOT A JUDGEMENT. It says this
    document could not read the card, which is a fact about the reading. It
    does not say the number is wrong.
    """
    r = row if isinstance(row, dict) else {}
    kind = str(r.get("certification_type") or "").strip()
    out = _html.escape(kind) if kind else NOT_RECORDED
    if r.get("unverified"):
        out += ('<br /><span style="font:400 8px Helvetica,Arial,sans-serif;'
                'letter-spacing:0.04em;color:#555;">UNVERIFIED &middot; card '
                'could not be read</span>')
    return out


#: Name -> implementation, for the narrow set a TABLE hands the whole row to.
#: See schema.ROW_FORMATTERS for why this exception exists and why it is a
#: closed named set rather than a lambda in a declaration.
ROW_FORMATTER_FNS = {"cp_headcount": cp_headcount,
                     "preshift_signature": preshift_signature,
                     "osha_cert_type": osha_cert_type}


def _row_survives(row, sec) -> bool:
    """Whether one stored row is a ROW, or a seed the CP never filled.

    ── TWO TESTS, AND THE SECOND ONE IS WHY A FAILED SLUMP STAYS ─────────

    `row_requires` tests a VALUE. The editors seed `{address: ""}`, so every
    seeded row CARRIES the key and testing presence would pass all of them
    through -- that mistake was made once already, by an agent, and caught by
    its own comparison.

    `row_requires_present` tests PRESENCE AND NOT-NULL, and it exists because
    the value test is wrong for a tri-state. A concrete slump test seeds `pass`
    as null; a recorded **False** is a FAILED TEST, and `str(False or "")` is
    empty -- so a value test drops the failure off a BC 3315 pour record while
    keeping every passing row. The branch spelled this out:

        if not t and not v and p is None:
            continue      # an untouched EMPTY_SLUMP_TEST seed

    Three keys, and the third one asked a different question.

    ── OR, NOT AND ─────────────────────────────────────────────────────

    A row survives if EITHER test finds something. That is the branch's shape:
    it drops a row only when the time is blank AND the value is blank AND the
    verdict was never recorded. A row is a claim about one event, and any one
    of its fields carrying something makes it an event somebody logged.
    """
    need = sec.get("row_requires")
    if need and any(str(_get(row, k) or "").strip() for k in need):
        return True
    need_p = sec.get("row_requires_present")
    if need_p and any(_has(row, k) and _get(row, k) is not None
                      for k in need_p):
        return True
    return not (need or need_p)


def table(sec: Dict, records: List, ctx: Dict) -> str:
    """Dense, with a REPEATING HEADER and rows that cannot split.

    `thead {display: table-header-group}` repeats the header on every page --
    measured in the production container, not assumed. `tr {break-inside:
    avoid}` is what stops a man's name landing on one sheet and his signature
    on the next.
    """
    cols: List = sec.get("columns") or []
    head = "".join(
        f'<th style="{_LABEL};color:#000;background:{_BAR};border:{_HAIRLINE};'
        f'padding:3px 6px;text-align:left;">{_html.escape(lbl)}</th>'
        for _, lbl, _f in cols)
    # ── A ROW THAT NAMES NOBODY IS NOT A ROW ────────────────────────────
    #
    # REQUESTED BY ALL THREE SCHEMA AGENTS INDEPENDENTLY, which is the signal
    # it belongs here and not in three contexts. Five hand-written branches
    # already state the rule -- the OSHA register, the toolbox roster, the
    # pre-shift sheet, fall protection and excavation all drop a row carrying
    # no identity.
    #
    # AND IT CANNOT BE LEFT TO THE DEVICE. The editors SEED empty rows and
    # `forFiling` trims them at submit -- but a draft keeps them, and a draft
    # is rendered. Without this an untouched seed row prints on a filed
    # document: a crane lift the crane never made, an attendee nobody can
    # identify, with ZERO WORDS LOST to a text diff because a blank row adds
    # no words.
    #
    # SEE `_row_survives` for why there are two tests and why they are ORed.
    if sec.get("row_requires") or sec.get("row_requires_present"):
        records = [r for r in records if _row_survives(r, sec)]

    body = ""
    for idx, rec in enumerate(records, start=1):
        body += f'<tr style="break-inside:avoid;page-break-inside:avoid;">'
        body += (f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                 f'width:22px;color:#555;">{idx}</td>')
        for path, _lbl, formatter in cols:
            if formatter == "signature_ink":
                cell = ink(_get(rec, path), ctx, present=_has(rec, path))
            elif formatter in ROW_FORMATTERS:
                # THE SUBJECT IS THE ROW. The declared path is "." and is not
                # read: this cell is computed from several keys at once.
                # ctx AS WELL AS THE ROW. A row formatter that draws a
                # SIGNATURE needs the stroke reconstruction, which arrives in
                # the context for the same reason `ink` takes it: one copy of
                # that geometry, passed in, never reimplemented.
                cell = ROW_FORMATTER_FNS[formatter](rec, ctx)
            else:
                cell = _fmt(rec, path, formatter)
            body += (f'<td style="{_BODY};border:{_HAIRLINE};'
                     f'padding:3px 6px;">{cell}</td>')
        body += "</tr>"

    # BLANK ROWS ARE VALID PAPER. A twenty-row sheet with four names on it is
    # a correct record, not a deficiency, so the rows are drawn empty rather
    # than the table being shortened to fit.
    if sec.get("empty") == "blank_rows":
        for idx in range(len(records) + 1, (sec.get("min_rows") or 0) + 1):
            body += ('<tr style="break-inside:avoid;">'
                     f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                     f'color:#555;">{idx}</td>'
                     + "".join(f'<td style="border:{_HAIRLINE};'
                               'padding:3px 6px;">&nbsp;</td>'
                               for _ in cols) + "</tr>")

    return (f'<table style="width:100%;border-collapse:collapse;'
            f'border:{_RULE};">'
            f'<thead style="display:table-header-group;"><tr>'
            f'<th style="{_LABEL};color:#000;background:{_BAR};'
            f'border:{_HAIRLINE};padding:3px 6px;text-align:left;">#</th>'
            f'{head}</tr></thead><tbody>{body}</tbody></table>')


def checklist(sec: Dict, rec: Any, ctx: Dict) -> str:
    """Real paper checkboxes, topic and mark, two pairs to a row.

    THREE STATES, NOT TWO, AND THE THIRD IS WHY THIS IS NOT JUST BOXES:

        ticked      the CP reviewed the item
        unticked    the CP answered and the answer was no
        absent      nobody was asked, and the sheet SAYS SO in the one
                    sanctioned phrase rather than drawing an empty box

    An empty box for an item the record never carried is a silent "No" the CP
    never gave, on a document an inspector reads as a statement of what was
    covered. The old renderer drew this line and a test names it. The box is a
    glyph and the absence is words on purpose: they are different KINDS of
    answer, not two values on one axis, and the one time a glyph and a word
    shared an axis here it had to be undone.

    THE LABEL SET APPLIES ONLY TO A RECORD FILLED ON THAT FORM. The kiosk keys
    this map by the item's full English sentence and carries NONE of the short
    keys; dragging the eighteen in-app items onto such a sheet would invent
    eighteen absences against a document filled on a different form. So when
    the record shares no key with the label set, only what it stores renders --
    verbatim, because title-casing a stored sentence once turned a compliance
    line into nonsense.
    """
    stored = _get(rec, sec.get("path", "")) or {}
    labels = LABEL_SETS[sec["labels"]]
    known = dict(labels)

    known_present = any(k in stored for k, _t in labels)
    items: List = list(labels) if known_present else []
    # TITLE-CASED, THE WAY `inspection_log` ALREADY DOES IT. This printed
    # the raw snake_case key, so a precaution the label set did not know
    # rendered as `gas_cylinders_secured` on an FDNY permit -- and a word diff
    # cannot see it, because `words()` splits on the underscore and finds the
    # same tokens either way. Two primitives in one file disagreeing about the
    # same question is how that survived.
    def _label_for(k):
        """Title-case an IDENTIFIER; leave a SENTENCE exactly as written.

        BOTH HALVES ARE LOAD-BEARING AND THEY COME FROM DIFFERENT FORMS.

        An FDNY precaution the label set does not know is stored as
        `gas_cylinders_secured`, and printing that raw puts a snake_case
        identifier on a 3504 permit -- invisible to a word diff, because
        `words()` splits on the underscore and finds the same tokens either
        way.

        The KIOSK keys its orientation checklist by the item's FULL ENGLISH
        SENTENCE, and title-casing that turns "Site-specific hazards and
        hazardous activities have been reviewed" into nonsense on a filed
        record. That rule predates this engine and a test names it.

        SO THE TEST IS THE SHAPE, NOT THE SOURCE: underscores or no spaces
        means an identifier; anything else is already prose. `key_label` in
        server.py has drawn exactly this line since it was written, and this
        is that rule, not a second one.
        """
        s = str(k)
        return s.replace("_", " ").title() if ("_" in s or " " not in s) else s

    items += [(k, _label_for(k)) for k in stored if k not in known]
    if not items:
        return ""

    def _mark(key: Any) -> str:
        if key not in stored:
            return NOT_RECORDED
        v = stored.get(key)
        if isinstance(v, dict):
            v = v.get("checked")
        return ('<span style="font-size:12px;">'
                + ("&#9746;" if v else "&#9744;") + "</span>")

    rows = ""
    for i in range(0, len(items), 2):
        rows += "<tr>"
        for key, text in items[i:i + 2]:
            rows += (f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                     f'width:36%;vertical-align:top;">{_html.escape(text)}</td>'
                     f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                     f'width:14%;vertical-align:top;white-space:nowrap;">'
                     f'{_mark(key)}</td>')
        for _ in range(2 - len(items[i:i + 2])):
            rows += (f'<td style="border:{_HAIRLINE};"></td>'
                     f'<td style="border:{_HAIRLINE};"></td>')
        rows += "</tr>"

    # THE HEADINGS ARE THE DOCUMENT'S, NOT THE PRIMITIVE'S.
    #
    # `Topic` / `Reviewed` was hardcoded, and on an FDNY 3504 permit "Fire
    # Watch Assigned -- Reviewed" claims the CP REVIEWED AN ITEM. The permit's
    # claim is that a fire watch WAS ASSIGNED. Four types share this primitive
    # and they do not share that sentence.
    _item_h = _html.escape(str(sec.get("item_label") or "Topic"))
    _mark_h = _html.escape(str(sec.get("mark_label") or "Reviewed"))
    head = ("".join(
        f'<th style="{_LABEL};color:#000;background:{_BAR};border:{_HAIRLINE};'
        f'padding:3px 6px;text-align:left;">{_item_h}</th>'
        f'<th style="{_LABEL};color:#000;background:{_BAR};border:{_HAIRLINE};'
        f'padding:3px 6px;text-align:left;">{_mark_h}</th>' for _ in range(2)))

    return (f'<table style="width:100%;border-collapse:collapse;'
            f'border:{_RULE};">'
            f'<thead style="display:table-header-group;"><tr>{head}</tr>'
            f'</thead><tbody>{rows}</tbody></table>')


def inspection_log(sec: Dict, rec: Any, ctx: Dict) -> str:
    """The daily inspections. A FOURTH ANSWER, WHICH IS WHY IT IS NOT A
    CHECKLIST.

    ── THE TWO PRIMITIVES ASK DIFFERENT QUESTIONS ───────────────────────

    `checklist` asks WAS THIS TOPIC REVIEWED, on one axis: a ticked box, an
    unticked box, or the not-recorded phrase in words. Its docstring argues
    that a glyph and a word are different KINDS of answer rather than two
    values on one axis, and records that mixing them had to be undone once.

    This asks WAS THIS THING WALKED AND WAS IT SATISFACTORY. Passed, failed
    with a note that always prints, walked with no result recorded, or never
    asked. Bolting that onto the checklist would put three kinds of answer on
    one axis, which is the error that docstring is about.

    THE SCOPE ARGUMENT SETTLED IT. Three more types want a checklist -- hot
    work's precautions, crane pre-operation, concrete formwork -- and not one
    of them wants a result, a fail or a note. The fail-with-note is one type's
    requirement, and a separate primitive keeps it from becoming a permanent
    branch inside the one four types share.

    ── A FAILED INSPECTION MUST NOT PRINT AS A PASSED ONE ───────────────

    Both old renderers once did `", ".join(k for k, v in chk.items() if v)`,
    which was right while the value was a tick. The value became
    {result, note}, and a dict is truthy -- so that line listed a FAILED item
    in the inspected list, identically to a passed one, and dropped the note.
    On a filed 3301-02 that is a document stating an inspection was fine when
    the CP recorded that it was not.

    ── "OTHER" IS NOT A PASS/FAIL ITEM ──────────────────────────────────

    The other eight name a specific thing to look at, so pass and fail mean
    something about that thing. "Other" names nothing, so a green
    "Passed: Other" asserts that an unnamed inspection was fine -- a claim
    with no subject. It is the CP writing WHAT he inspected, and the note is
    the record. A stored pass/fail from before that change still renders.

    ── A LEGACY RECORD KEEPS ITS OWN, THINNER CLAIM ─────────────────────

    Eleven filed records carry {key: True} and no result anywhere. They print
    as what they are: a list of the items ticked, in the device's own words,
    with no result column and no absences invented. An already-filed document
    does not acquire pass/fail semantics because the app later learned to
    record them -- and a table of PASSED rows built out of bare ticks would be
    exactly the first defect above, committed on purpose.
    """
    stored = _get(rec, sec.get("path", "")) or {}
    if not isinstance(stored, dict) or not stored:
        return ""
    labels = dict(LABEL_SETS[sec["labels"]])
    other_key = sec.get("other_key", "")

    ordered = [k for k, _t in LABEL_SETS[sec["labels"]] if k in stored]
    ordered += [k for k in stored if k not in labels]

    def _label(key):
        return labels.get(key) or str(key).replace("_", " ").title()

    # ── THE LEGACY SHAPE, RENDERED AS THE CLAIM IT ACTUALLY MAKES ───────
    if all(not isinstance(stored[k], dict) for k in ordered):
        ticked = [_label(k) for k in ordered if stored[k]]
        if not ticked:
            return ""
        return (f'<div style="{_BODY};border:{_RULE};border-top:none;'
                f'padding:5px 6px;line-height:1.45;">'
                f'{_html.escape(", ".join(ticked))}</div>')

    rows = ""
    also = []
    for key in ordered:
        value = stored[key]
        label = _label(key)
        note = ""
        if isinstance(value, dict):
            result = value.get("result")
            note = str(value.get("note") or "").strip()
            if key == other_key and not result:
                if note:
                    also.append(note)
                continue
            if result == "fail":
                verdict = ("<strong>FAILED</strong>", note or NOT_RECORDED)
            elif result == "pass":
                verdict = ("Passed", note)
            else:
                # NOT A PASS. He did not walk it, and the sheet names that so
                # its absence is visible rather than looking like an item that
                # was never on the list.
                verdict = ("Not inspected", note)
        elif value:
            # A bare tick in an otherwise-upgraded map. It says the CP looked
            # and nothing about what he found, so it is not a pass.
            verdict = ("Not inspected", "")
        else:
            verdict = (NOT_RECORDED, "")
        rows += (f'<tr style="break-inside:avoid;">'
                 f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                 f'width:30%;">{_html.escape(label)}</td>'
                 f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                 f'width:18%;white-space:nowrap;">{verdict[0]}</td>'
                 f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;">'
                 f'{_html.escape(verdict[1])}</td></tr>')

    for note in also:
        rows += (f'<tr style="break-inside:avoid;">'
                 f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;">'
                 f'Also inspected</td>'
                 f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;">'
                 f'&nbsp;</td>'
                 f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;">'
                 f'{_html.escape(note)}</td></tr>')

    if not rows:
        return ""
    head = "".join(
        f'<th style="{_LABEL};color:#000;background:{_BAR};border:{_HAIRLINE};'
        f'padding:3px 6px;text-align:left;">{t}</th>'
        for t in ("Item", "Result", "Note"))
    return (f'<table style="width:100%;border-collapse:collapse;'
            f'border:{_RULE};">'
            f'<thead style="display:table-header-group;"><tr>{head}</tr>'
            f'</thead><tbody>{rows}</tbody></table>')


def appended_photographs(rows: List) -> str:
    """Photographs added to a record AFTER it was signed.

    THE DATA ARRIVES RESOLVED AND THIS DRAWS IT. The walk is two levels deep,
    filters on a flag and converts a UTC instant to the New York day -- three
    features the engine would otherwise have to learn for one block on one
    sheet. They stay in server.py beside the Eastern-day helper they already
    use; what crosses is a list of what was appended, when and by whom.

    NOT A WARNING BANNER, AND NOT server.py's AMBER ONE. That colour came here
    on the amendment banner because twelve types still need that banner in
    that form; nothing shares this one, so it is drawn in the sheet's own type
    like everything else on the page.

    THIS DOCUMENT HAS NO PHOTOGRAPHS ON IT. The per-logbook sheet has never
    printed the pictures, only the record, so the marker cannot ride on a tile
    the way it does on the investor report. It says the thing directly: how
    many, when, and by whom. An inspector needs to know that four photographs
    were added afterwards far more than he needs to see them.
    """
    if not rows:
        return ""
    items = ""
    for i, row in enumerate(rows, start=1):
        parts = [str(x) for x in (row.get("when"), row.get("who")) if x]
        detail = (" · ".join(_html.escape(p) for p in parts)
                  if parts else "")
        items += (f'<tr><td style="{_BODY};border:{_HAIRLINE};'
                  f'padding:3px 6px;width:30%;">Photograph {i}</td>'
                  f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;">'
                  f'{detail}</td></tr>')
    return (
        f'<div style="break-inside:avoid;margin:0 0 10px 0;">'
        f'<div style="{_LABEL};color:#000;text-transform:uppercase;'
        f'border-top:{_RULE};padding:4px 6px 2px;">'
        # THE SAME WORDS THE INVESTOR REPORT USES, and the same words the
        # apparatus-marker registry names. That registry exists because this
        # exact notice rendered on the report through two rulings and zero
        # times on the legal PDF; a second wording here would put it back
        # outside the one check written to catch it.
        f'Added after filing</div>'
        f'<div style="{_BODY};padding:0 6px 4px;line-height:1.45;">'
        f'The photographs below were added to this record after it was filed '
        f'and are not part of what was attested to at signing.</div>'
        f'<table style="width:100%;border-collapse:collapse;'
        f'border:{_RULE};">{items}</table></div>')


def question_answers(sec: Dict, rec: Any, ctx: Dict) -> str:
    """A fixed list of questions and the answers AS STORED.

    -- WHY THIS IS NOT THE `checklist` PRIMITIVE ------------------------

    A shed inspection answers in WORDS. The record stores "YES", "NO" or "N/A"
    as strings, and `checklist` draws its box from the TRUTHINESS of whatever
    it is handed -- so **every failed check would draw a ticked box**, on the
    sheet an inspector reads to decide whether a sidewalk shed is safe.

    That is the same defect `inspection_log` exists to prevent, on a different
    form, which is why this is a third primitive and not a fourth mode of the
    first. A primitive that grows a mode per form is the branch chain again.

    THE ANSWER PRINTS VERBATIM. "N/A" is a third answer the inspector CHOSE,
    not a missing value, and a renderer that folds it into Yes or No is
    deciding something he decided differently.

    AN EMPTY STRING IS UNANSWERED, NOT "No". The editors seed these keys, so a
    key present and blank is a question nobody reached -- the same line
    `checklist` draws between an unticked box and an absent one, held here
    between an answer and a blank.

    UNKNOWN KEYS PRINT AFTER THE KNOWN ONES, title-cased, so a question added
    to the form and not yet to the label set still reaches the page instead of
    disappearing off a filed document.
    """
    stored = _get(rec, sec.get("path", "")) or {}
    if not isinstance(stored, dict):
        stored = {}
    labels = LABEL_SETS[sec["labels"]]
    known = dict(labels)
    items = list(labels) + [(k, str(k).replace("_", " ").title())
                            for k in stored if k not in known]
    rows = ""
    for key, text in items:
        raw = stored.get(key)
        answer = str(raw).strip() if raw is not None else ""
        cell = _html.escape(answer) if answer else NOT_RECORDED
        rows += (f'<tr style="break-inside:avoid;">'
                 f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;">'
                 f'{_html.escape(text)}</td>'
                 f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                 f'width:16%;white-space:nowrap;">{cell}</td></tr>')
    if not rows:
        return ""
    head = "".join(
        f'<th style="{_LABEL};color:#000;background:{_BAR};border:{_HAIRLINE};'
        f'padding:3px 6px;text-align:left;">{t}</th>'
        for t in ("Question", "Answer"))
    return (f'<table style="width:100%;border-collapse:collapse;'
            f'border:{_RULE};">'
            f'<thead style="display:table-header-group;"><tr>{head}</tr>'
            f'</thead><tbody>{rows}</tbody></table>')


def register(sec: Dict, subject: Any, ctx: Dict) -> str:
    """A numbered statutory register: item, citation, and what was recorded.

    THE ROWS ARRIVE RESOLVED. Which items a date requires, and what each one
    says, is decided by the caller -- see this conversion's note. Each row is
    {number, label, citation, body}, and `body` is markup the caller composed
    because for this document the markup IS the per-item rule.

    THE CITATION IS PART OF THE ITEM, not decoration. An inspector reading a
    BC 3301.13.13 log checks items against the code section each one answers,
    and a register that numbers its items without citing them is a list.
    """
    # RESOLVED FROM THE DECLARED PATH, like every other primitive. The
    # first version took its subject AS the rows -- and under `scope: context`
    # the subject is the whole context map, so iterating it yielded key
    # STRINGS, every one was skipped as "not a dict", and the register drew
    # nothing at all. Six filed sheets lost their entire statutory record and
    # the comparison caught it as 17 missing words on every one.
    rows = _get(subject, sec.get("path", "")) if sec.get("path") else subject
    out = ""
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        num = _html.escape(str(row.get("number") or ""))
        label = _html.escape(str(row.get("label") or ""))
        cite = _html.escape(str(row.get("citation") or ""))
        body = str(row.get("body") or "")
        out += (
            f'<tr style="break-inside:avoid;page-break-inside:avoid;">'
            f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
            f'width:34%;vertical-align:top;">'
            f'<strong>{num}. {label}</strong>'
            + (f'<div style="{_LABEL}">{cite}</div>' if cite else "")
            + f'</td>'
            f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
            f'vertical-align:top;">{body}</td></tr>')
    if not out:
        return ""
    head = "".join(
        f'<th style="{_LABEL};color:#000;background:{_BAR};border:{_HAIRLINE};'
        f'padding:3px 6px;text-align:left;">{t}</th>'
        for t in ("Item", "Record"))
    return (f'<table style="width:100%;border-collapse:collapse;'
            f'border:{_RULE};">'
            f'<thead style="display:table-header-group;"><tr>{head}</tr>'
            f'</thead><tbody>{out}</tbody></table>')


def filing_state(label: str, sentence: str) -> str:
    """The line under the letterhead when a record is not filed.

    A FACT, NOT A WARNING. No fill, no icon, no colour, no exclamation --
    rules above and below and the same label-and-body pairing every section of
    this sheet already uses, so it reads as part of the document rather than
    as an error stuck onto one. A draft is an ordinary state of a record.

    NOT A PRIMITIVE, and it is not in PRIMITIVE_FNS. A primitive is something
    a SCHEMA may ask for, and no schema gets to decide whether its own type
    announces that it was never filed. This is whole-document apparatus: it is
    the same statement on every sheet the engine draws, and the engine places
    it without being asked.
    """
    return (
        f'<div style="border-top:{_RULE};border-bottom:{_RULE};'
        f'padding:4px 6px;margin:0 0 10px 0;">'
        f'<span style="{_LABEL};color:#000;text-transform:uppercase;">'
        f'{_html.escape(label)}</span>'
        f'<span style="{_BODY};padding-left:10px;">'
        f'{_html.escape(sentence)}</span></div>')


def narrative(sec: Dict, rec: Any, ctx: Dict) -> str:
    """Long text, full width, flowing. The section may have rules; the text
    does not sit in a box, because a box is what an input looks like."""
    raw = _get(rec, sec.get("path", ""))
    body = FORMATTERS[sec.get("formatter", "sentence")](raw)
    return (f'<div style="{_BODY};border:{_RULE};border-top:none;'
            f'padding:5px 6px;line-height:1.45;">{body}</div>')


def ink(sig: Any, ctx: Dict, present: bool = True) -> str:
    """A signature, with NO BOUNDARY.

    No box, no background, no fixed-height container, true aspect ratio, free
    to overlap the baseline. The stroke reconstruction is the one every other
    renderer uses -- passed in through `ctx` rather than copied, because two
    copies of that geometry would drift.

    `present` is whether the record CARRIES the key, which is not the same as
    whether it holds a signature -- see `_has`, and the two tests that pin the
    two halves of it.

    ── AND THE AFFIRMATION BANNER RIDES WITH THE MARK ───────────────────

    A filed document says whether the signature under it was affirmed FOR THIS
    DOCUMENT -- green with a claimed and a server-received time, or amber
    saying no affirmation record exists for it. Every branch renderer prints
    it, through `render_signature_html`. The first version of this function did
    not, and 92 filed orientation records lost it: 89 lost an audit trail and
    79 lost a DEFICIENCY MARKER, which is the worse half. An unaffirmed
    signature with its warning removed does not look broken. It looks fine.

    THE BANNER IS NOT REIMPLEMENTED HERE. It arrives through ctx, like the
    stroke reconstruction above it and for the same reason: the function that
    composes it carries a careful argument about what this product may claim
    about a mark's origin, and a second spelling of it would be a second place
    for that argument to be half-remembered.

    NO MARK, NO BANNER. `render_signature_html` returns early on a falsy
    signature and prints no banner over nothing, and an absent signature has no
    affirmation record to report on in the first place. The UNSIGNED word below
    is a statement about the RECORD -- it was asked for -- and stands alone.
    """
    if not sig:
        # ASKED AND UNSIGNED IS NOT THE SAME AS NEVER ASKED.
        #
        # The manual-entry path writes null here, and an acknowledgment nobody
        # signed must say so on a document that certifies they did -- so a
        # PRESENT-AND-EMPTY key prints the word. A key the record does not
        # carry prints nothing at all: this renderer does not get to accuse a
        # record filled on a form that never asked.
        #
        # The old renderer drew exactly this line and a test names both sides
        # of it. The first draft of this function collapsed them, because
        # `_get` returns None for both -- a content loss that failed toward
        # looking fine, like the other four.
        if not present:
            return ""
        return ('<span style="font:700 8px Helvetica,Arial,sans-serif;'
                'letter-spacing:0.06em;color:#555;">UNSIGNED</span>')

    # THE DOCUMENT'S CLAIM ABOUT THIS MARK, composed by the one function that
    # is allowed to make it. Absent from ctx it contributes nothing, so a
    # caller that has no affirmation machinery -- a test, a preview -- renders
    # exactly what it rendered before.
    _affirm = ctx.get("signature_affirmation")
    banner = ""
    if callable(_affirm):
        try:
            banner = _affirm(sig) or ""
        except Exception:
            # A BANNER THAT CANNOT BE COMPOSED MUST NOT TAKE THE SIGNATURE WITH
            # IT. The mark is the record; the banner is a statement about it.
            banner = ""

    to_svg = ctx.get("signature_svg")
    if isinstance(sig, dict) and sig.get("paths") and to_svg:
        # THE HEIGHT IS THE BINDING CAP, and the width bound is deliberately
        # generous so it only takes over for ink wider than about 6:1 -- at
        # which point capping the width is the only way to keep it on the page.
        svg = to_svg(sig.get("paths"), boxed=False,
                     max_width=_INK_MAX_W, max_height=_INK_MAX_H)
        if svg:
            return svg + banner
    data = sig.get("data") if isinstance(sig, dict) else sig
    if isinstance(data, str) and data:
        src = data if data.startswith("data:") else f"data:image/png;base64,{data}"
        # HEIGHT FIXED, WIDTH AUTOMATIC: the browser and WeasyPrint both derive
        # the width from the image's own aspect, so this preserves it rather
        # than asserting it. `max-width` guards the 6:1 case the vector path
        # guards by its width bound.
        return (f'<img src="{src}" alt="" '
                f'style="height:{_INK_MAX_H}px;width:auto;'
                f'max-width:{_INK_MAX_W}px;display:block;" />') + banner
    # ── RECORDED, AND NOT DRAWABLE ──────────────────────────────────────
    #
    # A signature object that carries neither strokes nor an image is still a
    # signature the record asserts. The old renderer said so in words --
    # "Test CP (signed)" -- and the first version of this function returned
    # the affirmation banner over an empty signing area, which under a printed
    # name reads as NOBODY SIGNED. On 8 filed daily logs that is the opposite
    # of what the record says, and on two of them the banner directly above it
    # read AFFIRMED.
    #
    # SIGNED AND UNSIGNED ARE NOW SYMMETRICAL, in the same small-caps the
    # absence uses: one says the record carries a mark this document cannot
    # draw, the other says the record carries no mark at all. Neither is the
    # ink, and neither pretends to be.
    #
    # Caught by the old-branch-against-new-engine diff on the daily jobsite
    # conversion, which is what that diff is for.
    return ('<span style="font:700 8px Helvetica,Arial,sans-serif;'
            'letter-spacing:0.06em;color:#555;">SIGNED &mdash; no image '
            'recorded</span>') + banner


def signature(sec: Dict, rec: Any, ctx: Dict) -> str:
    """An open signing area: the ink, then a baseline, then the identity.

    The line is under the stroke and the stroke may cross it, which is what
    happens when somebody signs paper.
    """
    # ── ONE MARK, MORE THAN ONE PLACE IT MAY LIVE ───────────────────────
    #
    # The superintendent's log stores his signature on the presence block and
    # falls back to the account's; the branch reads them in that order and a
    # declaration naming only the second would print UNSIGNED over six filed
    # records that carry a mark.
    #
    # FIRST PRESENT WINS, and PRESENCE is the test, not truth -- a key present
    # and null still means "asked and unsigned" and must reach `ink` as that,
    # rather than falling through to a path that happens to hold something.
    _paths = sec.get("path", "")
    _paths = [_paths] if isinstance(_paths, str) else list(_paths)
    _p = next((p for p in _paths if _has(rec, p)), _paths[0] if _paths else "")
    sig = _get(rec, _p)
    mark = ink(sig, ctx, present=_has(rec, _p))
    who = FORMATTERS["name"](_get(rec, sec.get("name_path", "")))

    # ── TWO NAMES, STATED RATHER THAN RECONCILED ────────────────────────
    #
    # `signer_name` is stamped onto the signature object AT SIGNING TIME from
    # whatever the man typed; `name_path` is who the RECORD says the competent
    # person is. They are usually the same man and occasionally are not -- one
    # filed daily log names "2" on the record and "Michael" on the mark.
    #
    # The old renderer labelled the block with the SIGNER and this one printed
    # only the record's name, so that filed sheet lost the name attached to
    # its own signature. Both are printed when they differ, for the reason the
    # two headcounts are both printed: each is a true statement about a
    # different thing, and silently picking one deletes a fact.
    signer = ""
    if isinstance(sig, dict):
        signer = FORMATTERS["name"](
            sig.get("signer_name") or sig.get("signerName") or "")
    also = ""
    if signer and signer != who:
        also = (f'<span style="{_LABEL};padding-left:8px;">'
                f'signed by {signer}</span>')
    return (
        '<div style="break-inside:avoid;padding:6px;">'
        f'<div style="min-height:{_INK_MAX_H + 4}px;">{mark}</div>'
        f'<div style="border-top:{_RULE};padding-top:2px;">'
        f'<span style="{_BODY}">{who}</span>'
        f'<span style="{_LABEL};padding-left:8px;">'
        f'{_html.escape(sec.get("role", ""))}</span>{also}</div></div>')


def certification(sec: Dict, rec: Any, ctx: Dict) -> str:
    """The statement, the fields, and the mark -- as one block that cannot
    split. A certification broken across a fold is two half-statements, and
    neither of them is the one that was signed."""
    fields = "".join(
        f'<td style="border:{_HAIRLINE};padding:3px 6px;vertical-align:top;">'
        f'<div style="{_LABEL}">{_html.escape(lbl)}</div>'
        f'<div style="{_BODY}">{_fmt(rec, path, f)}</div></td>'
        for path, lbl, f in (sec.get("fields") or []))
    # THE SENTENCE, REFERENCED WHERE ONE EXISTS. `statement_ref` names a key
    # in the versioned attestation registry; `statement` is a literal, for a
    # document whose sentence is not versioned there. A declaration may not
    # carry both -- two sentences over one mark.
    _ref = sec.get("statement_ref")
    if _ref:
        _statement = str((_ATTESTATIONS.get(_ref) or {}).get("text") or "")
    else:
        _statement = _html.escape(sec.get("statement", ""))

    _p = sec.get("signature_path", "")
    _sig = _get(rec, _p)
    mark = ink(_sig, ctx, present=_has(rec, _p))

    # ── THE TWO-NAMES RULE `signature` LEARNED, CARRIED HERE ────────────
    #
    # `signer_name` is stamped onto the mark at signing time; the fields above
    # name whoever the RECORD says signed. Usually one man, occasionally not.
    # `signature` was taught to print both when they differ during the daily
    # jobsite conversion and THIS PRIMITIVE WAS NOT -- a fix that stopped at
    # the first of two places that needed it.
    #
    # LATENT, NOT LIVE, and measured rather than assumed: 0 of 92 filed
    # orientation records differ today. Fixed now because the next conversions
    # bind three more certifications, and because "no record differs yet" is a
    # fact with an expiry date.
    _signer = ""
    if isinstance(_sig, dict):
        _signer = FORMATTERS["name"](
            _sig.get("signer_name") or _sig.get("signerName") or "")
    _named = {FORMATTERS["name"](_get(rec, path))
              for path, _l, f in (sec.get("fields") or []) if f == "name"}
    _also = ("" if not _signer or _signer in _named else
             f'<div style="{_LABEL};padding-top:2px;">signed by {_signer}</div>')
    return (
        '<div style="break-inside:avoid;page-break-inside:avoid;">'
        f'<div style="{_BODY};border:{_RULE};border-top:none;padding:5px 6px;'
        'line-height:1.45;">'
        f'{_statement}</div>'
        f'<table style="width:100%;border-collapse:collapse;border:{_RULE};'
        'border-top:none;"><tr>'
        f'{fields}'
        f'<td style="border:{_HAIRLINE};padding:3px 6px;width:34%;'
        'vertical-align:bottom;">'
        f'<div style="{_LABEL}">Signature</div>'
        f'<div style="min-height:{_INK_MAX_H + 4}px;">{mark}</div>{_also}</td>'
        '</tr></table></div>')


#: Name -> implementation. A schema names one of these; nothing else.
PRIMITIVE_FNS = {
    "field_grid": field_grid,
    "table": table,
    "inspection_log": inspection_log,
    "question_answers": question_answers,
    "register": register,
    "checklist": checklist,
    "narrative": narrative,
    "signature": signature,
    "certification": certification,
}
