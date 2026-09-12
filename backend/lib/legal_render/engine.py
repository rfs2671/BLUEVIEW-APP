"""ONE ENGINE. THE SCHEMA SAYS WHAT APPEARS; THIS SAYS HOW.

Turning from an orientation log to a pre-shift log to a daily log should feel
like turning to a different form inside one professionally printed legal
logbook -- not like opening a different product. That is the whole requirement,
and it is met by there being exactly one of this file.

── THE PAGE SHELL ────────────────────────────────────────────────────────────

US Letter, portrait, white. A restrained head: the contractor in plain text on
the left over `PROJECT RECORD`, the document's classification and its real
citation on the right, a thin black rule, then the large title. Date and page
information right-aligned.

NO LOGO, NO SEAL, NO FORM NUMBER. The citations are ours and they are real.

── PAGINATION IS CONTENT-DRIVEN, AND THE DOCUMENT NEVER SCALES ───────────────

Four rules, and each was MEASURED in the production container rather than
assumed -- WeasyPrint 70.0, on the largest real orientation group there: 16
filed records, three pages.

  a table header repeats           thead{display:table-header-group}
  a page says which it is          @bottom-right counter(page)/counter(pages)
  a later page names its subject   position:running() in @top-left
  a heading is never orphaned      break-after:avoid on the section bar

What the laid-out pages actually said: the attendee header reprinted on pages
2 and 3, every page carried `Page N of 3`, every page carried the continuation
header naming the record and the job, and the masthead appeared on page 1 only.
The container's version is read at the top of that probe rather than recalled;
an earlier note in this file said 69.0, which was already out of date.

A row never splits and a certification never splits, both by `break-inside:
avoid` on the element itself rather than on a wrapper -- a section taller than
a page cannot honour a wrapper's request, and WeasyPrint answers that by moving
the whole block to a fresh sheet and leaving the previous one blank.

── DENSITY IS HELD UNDER EMPTY DATA ──────────────────────────────────────────

Three records and thirty records render at the same scale. Nothing is centred
vertically, no type grows, no filler appears. A legal form is allowed to be
half empty; a form that redesigns itself when the day was quiet is telling the
reader something the record does not say.
"""

from __future__ import annotations

import html as _html
from typing import Any, Dict, List, Optional

from .primitives import (PRIMITIVE_FNS, _empty_note, _get, _has,
                         _section_close, _section_open)
from .schema import SCHEMAS

_PAGE_CSS = """
@page {
  size: Letter portrait;
  margin: 0.55in 0.5in 0.6in 0.5in;
  @top-left   { content: element(contheader);
                font: 400 8px Helvetica,Arial,sans-serif; color: #555; }
  @bottom-left{ content: element(contfooter);
                font: 400 8px Helvetica,Arial,sans-serif; color: #555; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages);
                  font: 400 8px Helvetica,Arial,sans-serif; color: #555; }
}
/* A CONTINUATION HEADER, not a repeat of the masthead. A reader who picks up
   page 4 needs to know which record and which job it belongs to; they do not
   need the title block again. */
.contheader { position: running(contheader); }
.contfooter { position: running(contfooter); }
body { margin: 0; color: #111; background: #fff;
       font: 400 10.5px Helvetica,Arial,sans-serif; }
table { border-collapse: collapse; }
tr { break-inside: avoid; page-break-inside: avoid; }
thead { display: table-header-group; }
"""


def _is_empty(sec: Dict, records: List, ctx: Dict) -> bool:
    """Whether this section has nothing to show.

    DELIBERATELY NARROW. A section is empty when the records it draws on are
    absent, not when its values happen to be blank: a field grid whose every
    cell reads "Not recorded" is a record that was filed and left blank, which
    is a different fact from a section that does not apply, and the document
    must be able to tell a reader which.
    """
    if sec.get("scope") == "each":
        return not records
    if sec.get("scope") == "project":
        return not ctx.get("project")
    if sec.get("primitive") == "signature":
        # ASKED AND UNSIGNED IS NOT THE SAME AS NEVER ASKED, AT SECTION SCALE.
        #
        # `ink` already draws that line inside a cell. Here it decides whether
        # the section exists: a heading reading "Worker Acknowledgment" over an
        # empty signing area is itself a claim that an acknowledgment was asked
        # for. The old renderer wrapped the whole block in `if
        # "worker_signature" in data`, and a test names both halves.
        #
        # PRESENCE, NOT TRUTH -- `_has`, not `_get`. A key present and null is
        # NOT empty here; it renders, and prints UNSIGNED.
        return not _has(records[0] if records else {}, sec.get("path", ""))
    if sec.get("primitive") == "checklist":
        # THE ONE EXCEPTION, AND IT IS ABOUT MEANING RATHER THAN VALUES. A
        # checklist with no stored map has no items to draw three states over,
        # so drawing it would print an empty grid the label set invented. The
        # record establishes that no topics were documented, and the section
        # SAYS that -- which is what `none_documented` is for.
        return not (_get(records[0] if records else {},
                         sec.get("path", "")) or {})
    return not records


def _subject(sec: Dict, records: List, ctx: Dict):
    scope = sec.get("scope", "first")
    if scope == "project":
        return ctx.get("project") or {}
    if scope == "each":
        return records
    return records[0] if records else {}


def _head(ctx: Dict, decl: Dict) -> str:
    contractor = _html.escape(str(ctx.get("contractor") or "").strip())
    title = _html.escape(str(decl.get("title") or ""))
    subtitle = _html.escape(str(decl.get("subtitle") or ""))
    cite = _html.escape(str(decl.get("cite") or ""))
    klass = _html.escape(str(decl.get("classification") or title).upper())
    date_line = _html.escape(str(ctx.get("date_line") or ""))
    return f"""
<table style="width:100%;border-collapse:collapse;margin:0 0 6px 0;"><tr>
  <td style="vertical-align:top;">
    <div style="font:700 12px Helvetica,Arial,sans-serif;">{contractor}</div>
    <div style="font:400 8px Helvetica,Arial,sans-serif;letter-spacing:0.12em;
                color:#555;">PROJECT RECORD</div>
  </td>
  <td style="vertical-align:top;text-align:right;">
    <div style="font:700 8px Helvetica,Arial,sans-serif;letter-spacing:0.08em;">
      {klass}</div>
    <div style="font:400 8px Helvetica,Arial,sans-serif;color:#555;">{cite}</div>
  </td>
</tr></table>
<div style="border-top:1px solid #111;margin:0 0 8px 0;"></div>
<table style="width:100%;border-collapse:collapse;margin:0 0 12px 0;"><tr>
  <td style="vertical-align:bottom;">
    <div style="font:700 20px Helvetica,Arial,sans-serif;
                letter-spacing:-0.01em;">{title}</div>
    <div style="font:400 8px Helvetica,Arial,sans-serif;color:#555;">
      {subtitle}</div>
  </td>
  <td style="vertical-align:bottom;text-align:right;
             font:400 9px Helvetica,Arial,sans-serif;color:#333;">
    {date_line}</td>
</tr></table>
"""


def render(log_type: str, records: List[Dict], ctx: Dict) -> Optional[str]:
    """The whole sheet, or None if this type has no schema.

    RETURNS None RATHER THAN RAISING for an unconverted type: the caller's job
    is to fall through to its existing branch, and an exception here would turn
    "not converted yet" into a failed document.
    """
    decl = SCHEMAS.get(log_type)
    if not decl:
        return None

    ctx = dict(ctx or {})
    body = []
    for sec in decl["sections"]:
        empty_kind = sec.get("empty")
        if _is_empty(sec, records, ctx):
            if empty_kind == "omit":
                continue
            body.append(_section_open(sec)
                        + _empty_note(sec.get("none_text", "None documented."))
                        + _section_close())
            continue
        fn = PRIMITIVE_FNS[sec["primitive"]]
        body.append(_section_open(sec)
                    + fn(sec, _subject(sec, records, ctx), ctx)
                    + _section_close())

    cont = _html.escape(
        f"{decl.get('title', '')} — {ctx.get('address', '')} — "
        f"{ctx.get('date', '')}".strip(" —"))
    foot = _html.escape(
        f"Project Record • {ctx.get('address', '')} • {ctx.get('date', '')}")

    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>{_PAGE_CSS}</style></head><body>"
        f'<div class="contheader">{cont}</div>'
        f'<div class="contfooter">{foot}</div>'
        + _head(ctx, decl)
        + "".join(body)
        + "</body></html>"
    )
