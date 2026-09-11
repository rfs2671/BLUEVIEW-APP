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
overlap the baseline as a real one does. 297 of 303 signatures in production
are VECTOR STROKE PATHS, so this is polylines with `fill="none"` and no
backdrop -- transparent by construction rather than by a trick.

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
                cell = ink(_get(rec, path), ctx)
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
    """Real paper checkboxes, three to a row. Not switches, not pills, not
    green ticks -- the underlying record is a set of booleans and a paper form
    is what it becomes.

    AN UNTICKED BOX AND AN ABSENT ANSWER ARE DRAWN THE SAME, deliberately: the
    stored shape cannot tell them apart, and inventing a third mark would be
    the renderer claiming to know something the record does not say.
    """
    stored = _get(rec, sec.get("path", "")) or {}
    labels = LABEL_SETS[sec["labels"]]
    cells = ""
    for i in range(0, len(labels), 3):
        cells += "<tr>"
        for key, text in labels[i:i + 3]:
            v = stored.get(key)
            if isinstance(v, dict):
                v = v.get("checked")
            # The kiosk keys this map by the item's full English sentence; the
            # in-app editor keys it by the short key. Both shapes render.
            if v is None:
                v = stored.get(text)
                if isinstance(v, dict):
                    v = v.get("checked")
            box = "&#9746;" if v else "&#9744;"
            cells += (f'<td style="{_BODY};border:{_HAIRLINE};padding:3px 6px;'
                      f'width:33%;vertical-align:top;">'
                      f'<span style="font-size:12px;">{box}</span> '
                      f'{_html.escape(text)}</td>')
        for _ in range(3 - len(labels[i:i + 3])):
            cells += f'<td style="border:{_HAIRLINE};"></td>'
        cells += "</tr>"
    return (f'<table style="width:100%;border-collapse:collapse;'
            f'border:{_RULE};">{cells}</table>')


def narrative(sec: Dict, rec: Any, ctx: Dict) -> str:
    """Long text, full width, flowing. The section may have rules; the text
    does not sit in a box, because a box is what an input looks like."""
    raw = _get(rec, sec.get("path", ""))
    body = FORMATTERS[sec.get("formatter", "sentence")](raw)
    return (f'<div style="{_BODY};border:{_RULE};border-top:none;'
            f'padding:5px 6px;line-height:1.45;">{body}</div>')


def ink(sig: Any, ctx: Dict) -> str:
    """A signature, with NO BOUNDARY.

    No box, no background, no fixed-height container, true aspect ratio, free
    to overlap the baseline. The stroke reconstruction is the one every other
    renderer uses -- passed in through `ctx` rather than copied, because two
    copies of that geometry would drift.
    """
    if not sig:
        return ""
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
    mark = ink(_get(rec, sec.get("path", "")), ctx)
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
    mark = ink(_get(rec, sec.get("signature_path", "")), ctx)
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
