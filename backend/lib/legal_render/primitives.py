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
box, no background, no fixed-height container, true aspect ratio, and it may
overlap the baseline as a real one does.

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
from .schema import LABEL_SETS

# ── THE FOUR WEIGHTS. There are no others. ─────────────────────────────────
_TITLE = "font:700 20px Helvetica,Arial,sans-serif;letter-spacing:-0.01em"
_SECTION = ("font:700 10px Helvetica,Arial,sans-serif;letter-spacing:0.08em;"
            "text-transform:uppercase")
_BODY = "font:400 10.5px Helvetica,Arial,sans-serif"
_LABEL = "font:400 8px Helvetica,Arial,sans-serif;letter-spacing:0.04em;color:#555"

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
    body = ""
    for idx, rec in enumerate(records, start=1):
        body += f'<tr style="break-inside:avoid;page-break-inside:avoid;">'
        body += (f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                 f'width:22px;color:#555;">{idx}</td>')
        for path, _lbl, formatter in cols:
            if formatter == "signature_ink":
                cell = ink(_get(rec, path), ctx, present=_has(rec, path))
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
    items += [(k, str(k)) for k in stored if k not in known]
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

    head = ("".join(
        f'<th style="{_LABEL};color:#000;background:{_BAR};border:{_HAIRLINE};'
        f'padding:3px 6px;text-align:left;">Topic</th>'
        f'<th style="{_LABEL};color:#000;background:{_BAR};border:{_HAIRLINE};'
        f'padding:3px 6px;text-align:left;">Reviewed</th>' for _ in range(2)))

    return (f'<table style="width:100%;border-collapse:collapse;'
            f'border:{_RULE};">'
            f'<thead style="display:table-header-group;"><tr>{head}</tr>'
            f'</thead><tbody>{rows}</tbody></table>')


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
    to_svg = ctx.get("signature_svg")
    if isinstance(sig, dict) and sig.get("paths") and to_svg:
        svg = to_svg(sig.get("paths"), boxed=False)
        if svg:
            return svg
    data = sig.get("data") if isinstance(sig, dict) else sig
    if isinstance(data, str) and data:
        src = data if data.startswith("data:") else f"data:image/png;base64,{data}"
        return (f'<img src="{src}" alt="" '
                'style="max-width:190px;height:auto;display:block;" />')
    return ""


def signature(sec: Dict, rec: Any, ctx: Dict) -> str:
    """An open signing area: the ink, then a baseline, then the identity.

    The line is under the stroke and the stroke may cross it, which is what
    happens when somebody signs paper.
    """
    _p = sec.get("path", "")
    mark = ink(_get(rec, _p), ctx, present=_has(rec, _p))
    who = FORMATTERS["name"](_get(rec, sec.get("name_path", "")))
    return (
        '<div style="break-inside:avoid;padding:6px;">'
        f'<div style="min-height:38px;">{mark}</div>'
        f'<div style="border-top:{_RULE};padding-top:2px;">'
        f'<span style="{_BODY}">{who}</span>'
        f'<span style="{_LABEL};padding-left:8px;">'
        f'{_html.escape(sec.get("role", ""))}</span></div></div>')


def certification(sec: Dict, rec: Any, ctx: Dict) -> str:
    """The statement, the fields, and the mark -- as one block that cannot
    split. A certification broken across a fold is two half-statements, and
    neither of them is the one that was signed."""
    fields = "".join(
        f'<td style="border:{_HAIRLINE};padding:3px 6px;vertical-align:top;">'
        f'<div style="{_LABEL}">{_html.escape(lbl)}</div>'
        f'<div style="{_BODY}">{_fmt(rec, path, f)}</div></td>'
        for path, lbl, f in (sec.get("fields") or []))
    _p = sec.get("signature_path", "")
    mark = ink(_get(rec, _p), ctx, present=_has(rec, _p))
    return (
        '<div style="break-inside:avoid;page-break-inside:avoid;">'
        f'<div style="{_BODY};border:{_RULE};border-top:none;padding:5px 6px;'
        'line-height:1.45;">'
        f'{_html.escape(sec.get("statement", ""))}</div>'
        f'<table style="width:100%;border-collapse:collapse;border:{_RULE};'
        'border-top:none;"><tr>'
        f'{fields}'
        f'<td style="border:{_HAIRLINE};padding:3px 6px;width:34%;'
        'vertical-align:bottom;">'
        f'<div style="{_LABEL}">Signature</div>'
        f'<div style="min-height:34px;">{mark}</div></td>'
        '</tr></table></div>')


#: Name -> implementation. A schema names one of these; nothing else.
PRIMITIVE_FNS = {
    "field_grid": field_grid,
    "table": table,
    "checklist": checklist,
    "narrative": narrative,
    "signature": signature,
    "certification": certification,
}
