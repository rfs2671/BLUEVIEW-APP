"""THE THREE PAGES. LAYOUT AND TYPOGRAPHY, AND NOTHING ELSE.

── THE INPUT CONTRACT ────────────────────────────────────────────────────────

`render` takes ONE argument: a `ReportView`. Not a view and a model, not a view
and "the logbook, just for the photographs". If both were available somebody
would reach around the view layer within a month, and the boundary would be a
comment rather than a fact.

The same rule runs downward. EVERY HELPER IN THIS FILE TAKES A VIEW OBJECT OR A
PRIMITIVE DISPLAY VALUE -- a string, a number, a count. None takes an activity
document, a check-in row, or a database anything, and a test walks this
module's signatures and refuses one that does.

── WHAT THIS FILE MAY DECIDE ────────────────────────────────────────────────

Column count. Band height. Font size. When a section collapses. Whether four
photographs go two-by-two or four across. Where a page break lands.

── WHAT IT MAY NOT ──────────────────────────────────────────────────────────

Whether zero means missing. Whether counts align. Whether sitewide is an area.
Whether a trade is real. Whether a row is empty. Whether safety is clear. Which
logs are required. Who was inside the gate day.

Every one of those arrives already decided. If this file ever starts to feel
interesting, it has taken one of them back.

── THE PALETTE, WHICH IS A LANGUAGE AND NOT A DECORATION ────────────────────

    NAVY   project and progress facts
    GREY   source differences, unavailable information, anything not reported
    AMBER  a record that is owed and absent -- and nothing else
    GREEN  a record that is filed -- and nothing else

A variance is grey. Twenty-five of eighty-nine comparable activity rows on
production disagree between the log and the gate, and an amber box a third of
the time teaches a reader to ignore amber. Agreement is grey too: green already
means FILED on Page 3, and spending it on a second idea would cost the only
unambiguous colour in the system.
"""

from __future__ import annotations

import html as _html
from typing import List, Sequence, Tuple

from .view import (AdditionalGateView, AttentionView, BandView, BannerView,
                   CardState, CardView, CompletenessView, RailCell,
                   ReportView, SafetyView, SummaryView)

# ── INK ────────────────────────────────────────────────────────────────────
NAVY = "#0A1929"
INK = "#1B2A38"
MUTED = "#5C6B7A"
FAINT = "#8D9AA7"
HAIR = "#D8DEE4"
PANEL = "#F4F6F8"
AMBER = "#8A5A00"
AMBER_FIELD = "#FFF8EC"
GREEN = "#1B6B3A"

# ── PAGE 2 GEOMETRY, MEASURED RATHER THAN ASSUMED ─────────────────────────
#
# The band header was first guessed at 0.46in and Page 2 spilled onto a fourth
# sheet: WeasyPrint lays the block out at 0.557in of content plus 0.20in of
# padding, and three bands turned a 0.26in error into 0.78in. These come from
# reading `box.height` off a rendered page.
BAND_HEAD_IN = 0.76
TABLE_EDGE_IN = 0.10
GAP_IN = 0.09
MIN_CELL_IN = 0.95
#: AND A CEILING, WHICH THE SPARSE DAY FOUND. One photograph was handed 8.69in
#: and the cell became a grey slab the height of the page with a landscape
#: frame floating in it. Unused height is left white instead.
MAX_CELL_IN = 4.40
#: Letter, less the page padding and the measured header block.
PAGE2_AVAILABLE_IN = 11.0 - 0.42 - 0.34 - 0.69


def esc(text: str) -> str:
    return _html.escape(str(text or ""))


# ══════════════════════════════════════════════════════════════════════════
#  THE STYLESHEET
# ══════════════════════════════════════════════════════════════════════════

def stylesheet() -> str:
    return """
@page { size: Letter portrait; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; color: %(INK)s; background: #fff;
       font-family: Helvetica, Arial, sans-serif; }

/* THE BANNER. Pages 1 and 3 carry it at the SAME size; Page 2 does not,
   because Page 2 is evidence and a masthead over photographs competes with
   the only thing that page is for. */
.banner { background: %(NAVY)s; color: #fff; padding: 0.40in 0.55in 0.30in; }
.mark { font-size: 26px; font-weight: 700; letter-spacing: 0.30em; line-height: 1; }
.tag { font-size: 8px; letter-spacing: 0.24em; text-transform: uppercase;
       color: #9FB3C8; padding-top: 10px; }
.brule { border-top: 1px solid rgba(255,255,255,0.20); margin: 0.19in 0 0.15in; }
.dtitle { font-size: 9.5px; font-weight: 700; letter-spacing: 0.22em;
          text-transform: uppercase; color: #C8D6E4; }
.addr { font-size: 22px; font-weight: 700; letter-spacing: -0.015em;
        line-height: 1.12; padding-top: 8px; }
.city { font-size: 12px; color: #9FB3C8; padding-top: 3px; }
.when { font-size: 10px; color: #9FB3C8; padding-top: 11px; }

.body { padding: 0 0.55in; }

table.rail { width: 100%%; border-collapse: collapse;
             border-bottom: 1px solid %(HAIR)s; }
table.rail td { width: 20%%; vertical-align: top;
                padding: 0.17in 10px 0.17in 0; border-left: 1px solid %(HAIR)s; }
table.rail td.first { border-left: none; padding-left: 0; }
.rv { font-size: 27px; font-weight: 700; color: %(NAVY)s; line-height: 1;
      letter-spacing: -0.02em; }
.rv.q { color: %(MUTED)s; }
.rl { font-size: 7.5px; font-weight: 700; letter-spacing: 0.15em;
      text-transform: uppercase; color: %(MUTED)s; padding-top: 8px; }
.rs { font-size: 8px; color: %(FAINT)s; padding-top: 4px; line-height: 1.4; }

.exec { padding: 0.21in 0 0.19in; border-bottom: 1px solid %(HAIR)s; }
.eyebrow { font-size: 7.5px; font-weight: 700; letter-spacing: 0.18em;
           text-transform: uppercase; color: %(MUTED)s; }
.ehead { font-size: 17px; font-weight: 700; color: %(NAVY)s; line-height: 1.2;
         letter-spacing: -0.01em; padding-top: 7px; }
.ebody { font-size: 11px; line-height: 1.55; color: %(INK)s; padding-top: 10px;
         max-width: 6.4in; }
.eclose { font-size: 11px; font-weight: 700; color: %(NAVY)s; padding-top: 9px; }

.sechead { font-size: 8px; font-weight: 700; letter-spacing: 0.18em;
           text-transform: uppercase; color: %(MUTED)s;
           padding: 0.17in 0 0.08in; }
table.acts { width: 100%%; border-collapse: collapse; }
table.acts td { vertical-align: top; border-bottom: 1px solid %(HAIR)s;
                padding: 0.10in 0; }
.aco { font-size: 14px; font-weight: 700; color: %(NAVY)s; line-height: 1.2; }
.awhat { font-size: 10px; color: %(MUTED)s; padding-top: 4px; }
.avar { font-size: 10.5px; color: %(MUTED)s; }
.chip { display: inline-block; font-size: 7px; font-weight: 700;
        letter-spacing: 0.13em; text-transform: uppercase; color: %(MUTED)s;
        border: 1px solid %(HAIR)s; background: %(PANEL)s;
        padding: 3px 6px; margin-top: 6px; }
.xg { font-size: 11.5px; color: %(INK)s; padding-top: 2px; }
.xg strong { color: %(NAVY)s; }
.xgn { font-size: 9px; color: %(MUTED)s; padding-top: 5px; }

table.strip { width: 100%%; border-collapse: collapse; margin-top: 0.13in; }
table.strip td { padding: 7px 0; border-bottom: 1px solid %(HAIR)s;
                 vertical-align: baseline; }
table.strip td.sl { width: 1.35in; font-size: 7.5px; font-weight: 700;
                    letter-spacing: 0.15em; text-transform: uppercase;
                    color: %(MUTED)s; }
table.strip td.sv { font-size: 11px; color: %(INK)s; }
table.strip td.sv strong { color: %(NAVY)s; }

.att { margin-top: 0.18in; border-top: 2px solid %(NAVY)s; padding-top: 0.16in; }
table.two { width: 100%%; border-collapse: collapse; }
.abox { border: 1px solid %(AMBER)s; background: %(AMBER_FIELD)s;
        padding: 11px 12px; }
.ahead { font-size: 15px; font-weight: 700; color: %(AMBER)s; line-height: 1.2; }
.aitem { font-size: 10.5px; color: %(INK)s; padding-top: 6px; }
.sbox { border: 1px solid %(HAIR)s; background: %(PANEL)s; padding: 11px 12px; }
.sval { font-size: 13px; font-weight: 700; color: %(MUTED)s; line-height: 1.2; }
.snote { font-size: 9.5px; color: %(MUTED)s; padding-top: 6px; line-height: 1.45; }
.gen { font-size: 6.5px; color: #93A1AE; padding-top: 0.12in; line-height: 1.5; }

/* PAGE 2 */
.p2 { page-break-before: always; padding: 0.42in 0.55in 0.34in; }
.p2ref { font-size: 7.5px; font-weight: 700; letter-spacing: 0.16em;
         text-transform: uppercase; color: %(MUTED)s;
         border-bottom: 1px solid %(HAIR)s; padding-bottom: 7px; }
.p2h { font-size: 21px; font-weight: 700; color: %(NAVY)s;
       letter-spacing: -0.01em; padding-top: 0.16in; }
.p2sub { font-size: 8.5px; color: %(MUTED)s; padding-top: 4px; }
.bandhead { padding: 0.13in 0 0.07in; }
.bno { font-size: 7.5px; font-weight: 700; letter-spacing: 0.16em;
       color: %(MUTED)s; }
.bco { font-size: 13px; font-weight: 700; color: %(NAVY)s; line-height: 1.2;
       padding-top: 2px; }
.bwhat { font-size: 9.5px; color: %(MUTED)s; padding-top: 3px; }
.bcount { font-size: 9.5px; color: %(MUTED)s; padding-top: 2px; }
table.shots { width: 100%%; border-collapse: separate;
              border-spacing: 4.5px 4.5px; }
table.shots td { text-align: center; vertical-align: middle;
                 background: %(PANEL)s; }
/* CONTAIN, NEVER COVER. No object-fit, no fixed aspect on the image, no
   overflow hidden. The cell has the geometry; the photograph keeps its own,
   so a portrait leaves air at the sides and nothing is ever cut. */
table.shots img { max-width: 100%%; display: inline-block; }

/* PAGE 3 */
.p3 { page-break-before: always; }
h1.sec { font-size: 21px; font-weight: 700; letter-spacing: -0.01em; margin: 0;
         color: %(NAVY)s; }
.sub { font-size: 8px; font-weight: 700; letter-spacing: 0.18em;
       text-transform: uppercase; color: %(MUTED)s; padding-top: 5px; }
.secrule { border-top: 1px solid %(NAVY)s; margin: 0.10in 0 0.13in; }
table.grid { width: 100%%; border-collapse: separate; border-spacing: 8px 8px; }
table.grid td { width: 33.33%%; vertical-align: top; }
/* FIXED HEIGHT, so the register reads as a register. Content used to decide
   each card's bottom edge and three cards in a row ended at three heights. */
.card { border: 1px solid %(HAIR)s; padding: 8px 9px 9px; height: 2.00in; }
.card .no { font-size: 8px; font-weight: 700; letter-spacing: 0.16em;
            color: %(MUTED)s; }
.card .t { font-size: 11.5px; font-weight: 700; line-height: 1.25;
           color: %(NAVY)s; padding-top: 3px; height: 29px; }
.card .c { font-size: 8.5px; color: %(MUTED)s; }
.state { font-size: 8px; font-weight: 700; letter-spacing: 0.13em;
         text-transform: uppercase; padding-top: 6px; }
.state.filed { color: %(GREEN)s; }
.state.missing { color: %(AMBER)s; }
.state.not_due { color: %(MUTED)s; }
.win { height: 0.74in; overflow: hidden; border: 1px solid %(HAIR)s;
       margin: 6px 0 0; background: #fff; }
.win img { width: 100%%; display: block; }
.nowin { height: 0.74in; border: 1px dashed %(HAIR)s; margin: 6px 0 0;
         background: %(PANEL)s; }
.nowin .msg { font-size: 8.5px; color: %(MUTED)s; padding: 0.21in 10px 0;
              text-align: center; line-height: 1.45; }
.fact { font-size: 8px; color: %(INK)s; padding-top: 5px; line-height: 1.38; }
.go { font-size: 8px; font-weight: 700; letter-spacing: 0.13em;
      text-transform: uppercase; color: %(NAVY)s; padding-top: 6px; }
.go a { color: %(NAVY)s; text-decoration: none; }
.comp { margin: 0.12in 0 0; border-top: 2px solid %(NAVY)s; padding-top: 0.14in; }
.comph { font-size: 8px; font-weight: 700; letter-spacing: 0.18em;
         text-transform: uppercase; color: %(MUTED)s; }
table.cf { width: 100%%; border-collapse: collapse; margin-top: 9px; }
table.cf td { vertical-align: top; padding-right: 0.35in; }
.cnum { font-size: 24px; font-weight: 700; color: %(NAVY)s; line-height: 1;
        letter-spacing: -0.02em; }
.cnum.owed { color: %(AMBER)s; }
.clab { font-size: 7.5px; font-weight: 700; letter-spacing: 0.15em;
        text-transform: uppercase; color: %(MUTED)s; padding-top: 7px; }
""" % dict(NAVY=NAVY, INK=INK, MUTED=MUTED, FAINT=FAINT, HAIR=HAIR,
           PANEL=PANEL, AMBER=AMBER, AMBER_FIELD=AMBER_FIELD, GREEN=GREEN)


# ══════════════════════════════════════════════════════════════════════════
#  SHARED
# ══════════════════════════════════════════════════════════════════════════

def render_banner(banner: BannerView) -> str:
    return (
        '<div class="banner">'
        f'<div class="mark">{esc(banner.wordmark)}</div>'
        f'<div class="tag">{esc(banner.tagline)}</div>'
        '<div class="brule"></div>'
        f'<div class="dtitle">{esc(banner.document_title)}</div>'
        f'<div class="addr">{esc(banner.address.upper())}</div>'
        f'<div class="city">{esc(banner.city)}</div>'
        f'<div class="when">{esc(banner.dateline)}</div>'
        "</div>")


def render_rail(cells: Sequence[RailCell]) -> str:
    out = ""
    for i, cell in enumerate(cells):
        quiet = " q" if cell.value in ("—", "Sitewide") else ""
        notes = "".join(f'<div class="rs">{esc(n)}</div>' for n in cell.notes)
        out += (f'<td class="{"first" if i == 0 else ""}">'
                f'<div class="rv{quiet}">{esc(cell.value)}</div>'
                f'<div class="rl">{esc(cell.label)}</div>{notes}</td>')
    return f'<table class="rail"><tr>{out}</tr></table>'


# ══════════════════════════════════════════════════════════════════════════
#  PAGE 1 — EXECUTIVE BRIEF
# ══════════════════════════════════════════════════════════════════════════

def render_page_1(view: ReportView) -> str:
    rows = "".join(
        '<tr><td width="42%">'
        f'<div class="aco">{esc(a.company)}</div>'
        f'<div class="awhat">{esc(a.where)}</div></td>'
        '<td width="58%" align="right">'
        f'<div class="avar">{esc(a.statement)}</div>'
        f'<div class="chip">{esc(a.chip)}</div></td></tr>'
        for a in view.activities)

    extra = ""
    if view.additional_gate is not None:
        extra = ('<div class="sechead">Additional gate workforce</div>'
                 f'<div class="xg">{esc(view.additional_gate.line)}</div>'
                 f'<div class="xgn">{esc(view.additional_gate.note)}</div>')

    attention = ""
    if view.attention is not None:
        items = "".join(f'<div class="aitem">&#9651;&nbsp; {esc(n)}</div>'
                        for n in view.attention.names)
        attention = ('<div class="abox">'
                     f'<div class="ahead">{esc(view.attention.headline)}</div>'
                     f'{items}</div>')

    return (
        render_banner(view.banner)
        + '<div class="body">'
        + render_rail(view.rail)
        + '<div class="exec">'
        + f'<div class="eyebrow">{esc(view.summary.eyebrow)}</div>'
        + f'<div class="ehead">{esc(view.summary.headline)}</div>'
        + f'<div class="ebody">{esc(view.summary.body)}</div>'
        + f'<div class="eclose">{esc(view.summary.closing)}</div></div>'
        + '<div class="sechead">Today&rsquo;s documented activity</div>'
        + f'<table class="acts">{rows}</table>'
        + extra
        + '<table class="strip">'
        + '<tr><td class="sl">Gate workforce</td>'
        + f'<td class="sv">{esc(view.workforce_line)}</td></tr>'
        + '<tr><td class="sl">Weather</td>'
        + f'<td class="sv">{esc(view.weather_line)}</td></tr></table>'
        + '<div class="att"><table class="two"><tr>'
        + '<td width="58%" style="padding-right:0.22in;">'
        + ('<div class="sechead" style="padding-top:0;">Attention</div>'
           + attention if attention else "")
        + '</td><td width="42%">'
        + '<div class="sechead" style="padding-top:0;">Safety</div>'
        + '<div class="sbox">'
        + f'<div class="sval">{esc(view.safety.value if view.safety.note == "" else "Status not reported")}</div>'
        + (f'<div class="snote">{esc(view.safety.note)}</div>'
           if view.safety.note else "")
        + "</div></td></tr></table></div></div>")


# ══════════════════════════════════════════════════════════════════════════
#  PAGE 2 — VISUAL PROGRESS
# ══════════════════════════════════════════════════════════════════════════

def photo_columns(count: int) -> int:
    """Columns for a band. NOT A FORMULA: the shapes are chosen so a band reads
    as a composition rather than a reflow.

    MEASURED SPREAD, photographs per activity row on production:
        1:11  2:17  3:10  4:13  5:11  6:3  8:1  9:2  10:1  12:1
    so every branch is reachable, and four is the most common non-trivial case,
    which is why it is two-by-two rather than a thin strip.
    """
    if count <= 1:
        return 1
    if count == 2:
        return 2
    if count == 3:
        return 3
    if count == 4:
        return 2
    if count <= 9:
        return 3
    return 4


def photo_rows(count: int) -> int:
    cols = photo_columns(count)
    return (count + cols - 1) // cols if cols else 0


def allocate_bands(counts: Sequence[int],
                   available_in: float) -> Tuple[List[float], List[int]]:
    """Inches of photograph area per band, IN PROPORTION TO ROWS not to count.

    Height is what is scarce. Allocating by photograph count gives a four-up
    two-by-two the same height as a four-across single row, and one of those
    needs twice the vertical space.
    """
    rows = [photo_rows(n) for n in counts]
    total = sum(rows) or 1
    heads = (BAND_HEAD_IN + TABLE_EDGE_IN) * len(counts)
    gaps = GAP_IN * max(0, len(counts) - 1)
    area = max(0.0, available_in - heads - gaps)
    return [area * r / total for r in rows], rows


def render_band(band: BandView, height_in: float, row_count: int) -> str:
    cols = photo_columns(band.count)
    cell = min(MAX_CELL_IN,
               max(MIN_CELL_IN,
                   (height_in - GAP_IN * max(0, row_count - 1))
                   / max(1, row_count)))
    cells = ""
    for r in range(row_count):
        cells += "<tr>"
        for c in range(cols):
            k = r * cols + c
            if k >= band.count:
                cells += '<td style="background:#fff;"></td>'
                continue
            cells += (f'<td style="height:{cell:.3f}in;">'
                      f'<img src="{esc(band.photos[k].url)}" '
                      f'style="max-height:{cell - 0.06:.3f}in;" /></td>')
        cells += "</tr>"
    return (
        '<div class="bandhead">'
        f'<div class="bno">{band.number:02d}</div>'
        f'<div class="bco">{esc(band.company)}</div>'
        f'<div class="bwhat">{esc(band.subtitle)}</div>'
        f'<div class="bcount">{esc(band.statement)}</div></div>'
        f'<table class="shots">{cells}</table>')


def render_page_2(view: ReportView) -> str:
    """EVIDENCE ONLY, AND IT COLLAPSES ENTIRELY when the day has none.

    No banner: a masthead over photographs competes with them. A running
    reference line instead, naming the job and the date.
    """
    if not view.bands:
        return ""
    heights, rows = allocate_bands([b.count for b in view.bands],
                                   PAGE2_AVAILABLE_IN)
    bands = "".join(render_band(b, heights[i], rows[i])
                    for i, b in enumerate(view.bands))
    return (
        '<div class="p2">'
        f'<div class="p2ref">{esc(view.banner.address)} &nbsp;&middot;&nbsp; '
        f'{esc(view.date_long)} &nbsp;&middot;&nbsp; Page 2 of 3</div>'
        '<div class="p2h">Visual progress</div>'
        f'<div class="p2sub">{esc(view.evidence_subtitle)}</div>'
        f"{bands}</div>")


# ══════════════════════════════════════════════════════════════════════════
#  PAGE 3 — PROJECT RECORD
# ══════════════════════════════════════════════════════════════════════════

STATE_WORDS = {
    CardState.FILED: ("filed", "&#10003;&nbsp; Filed"),
    CardState.MISSING: ("missing", "&#9651;&nbsp; Not filed"),
    CardState.NOT_DUE: ("not_due", "&mdash;&nbsp; Not due today"),
}


def render_card(card: CardView) -> str:
    css, words = STATE_WORDS[card.state]
    if card.state is CardState.FILED and card.thumbnail:
        window = f'<div class="win"><img src="{esc(card.thumbnail)}" /></div>'
    elif card.state is CardState.FILED:
        # THE PICTURE IS AN ILLUSTRATION, NOT THE RECORD. A thumbnail that
        # could not be rendered leaves the card otherwise intact.
        window = ('<div class="nowin"><div class="msg">Document filed<br />'
                  "preview unavailable</div></div>")
    else:
        # NOT A FAKE PAGE. An empty document outline reads as a filing that
        # rendered badly; this says what is absent and for which date.
        window = ('<div class="nowin"><div class="msg">'
                  f'{esc(card.absent_note)}</div></div>')
    facts = "".join(f'<div class="fact">{esc(f)}</div>' for f in card.facts)
    link = (f'<div class="go"><a href="{esc(card.link)}">View log &rarr;</a>'
            "</div>" if card.link else "")
    return (f'<div class="card"><div class="no">{card.number:02d}</div>'
            f'<div class="t">{esc(card.title)}</div>'
            f'<div class="c">{esc(card.citation)}</div>'
            f'<div class="state {css}">{words}</div>'
            f"{window}{facts}{link}</div>")


def render_completeness(completeness: CompletenessView) -> str:
    return (
        '<div class="comp"><div class="comph">Document completeness</div>'
        '<table class="cf"><tr>'
        f'<td><div class="cnum">{esc(completeness.required_ratio)}</div>'
        '<div class="clab">Required daily logs filed</div></td>'
        f'<td><div class="cnum">{completeness.additional}</div>'
        '<div class="clab">Additional records filed</div></td>'
        # AMBER ONLY WHEN THERE IS SOMETHING OWED. A zero set in the colour
        # that means "a record is missing" reads as an alarm about nothing,
        # and a palette that cries wolf on a complete day is worth less on
        # the day it matters.
        + f'<td><div class="cnum{" owed" if completeness.outstanding else ""}">'
        + f'{completeness.outstanding}</div>'
        + '<div class="clab">Outstanding</div></td>'
        "</tr></table>"
        '<div class="gen">Required and additional records have different '
        "denominators and are never combined.</div></div>")


def render_page_3(view: ReportView) -> str:
    grid = ""
    for i in range(0, len(view.cards), 3):
        chunk = view.cards[i:i + 3]
        grid += ("<tr>" + "".join(f"<td>{render_card(c)}</td>" for c in chunk)
                 + "<td></td>" * (3 - len(chunk)) + "</tr>")
    return (
        '<div class="p3">' + render_banner(view.banner)
        + '<div class="body"><div style="padding-top:0.14in;"></div>'
        + '<h1 class="sec">Project record</h1>'
        + '<div class="sub">Regulatory &nbsp;&middot;&nbsp; Safety '
          "&nbsp;&middot;&nbsp; Workforce documentation</div>"
        + '<div class="secrule"></div>'
        + f'<table class="grid">{grid}</table>'
        + render_completeness(view.completeness)
        + f'<div class="gen">{esc(view.generated)}</div>'
        + "</div></div>")


# ══════════════════════════════════════════════════════════════════════════
#  THE DOCUMENT
# ══════════════════════════════════════════════════════════════════════════

def render(view: ReportView) -> str:
    """The whole report. ONE ARGUMENT, and it is the view."""
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<style>{stylesheet()}</style></head><body>"
            + render_page_1(view) + render_page_2(view) + render_page_3(view)
            + "</body></html>")
