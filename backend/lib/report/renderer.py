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
from typing import List, Optional, Sequence, Tuple

from .view import (ActivityRowView, AdditionalGateView, AttentionView,
                   BandView, BannerView, CardState, CardView,
                   CompletenessView, RailCell, ReportView, SafetyView,
                   SummaryView, WeatherView)

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
#
# 0.76 -> 0.606 when the header went from four stacked lines to two. MEASURED
# THE SAME WAY, on the same WeasyPrint, rather than scaled from the old value:
# 58.21px at 96dpi. Leaving it at 0.76 would have subtracted an inch and a half
# from a four-band page and given it to nothing.
BAND_HEAD_IN = 0.606
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


.body { padding: 0 0.55in; }

/* THE RAIL READS AS A MEASURE STRIP. It used to read as a spreadsheet
   header: five identical cells with a hard rule between every pair, the
   numeral and the label competing at similar weight.
     - the dividers are gone; the SPACE between cells separates them, and the
       one rule that stays is the strip's own bottom edge
     - 27px -> 31px on the numeral, so the figure leads
     - the label drops to 7px and loses a third of its tracking, so it reads
       as a caption rather than as a second headline in small caps
     - the subline gains a point and real leading */
/* ══ PAGE 1 ══════════════════════════════════════════════════════════════
   RECOMPOSED 12 SEPTEMBER against a supplied reference. Restrained,
   editorial, and printable on a mono laser: no photograph, no icon system,
   no gradient outside the hero's tonal fade.

   EVERY RULE IN THIS BLOCK IS SCOPED TO `.p1`, so pages 2 and 3 are not
   reachable from here. That is deliberate -- the redesign was ruled to page 1
   only, and a bare selector would have taken the register with it.
*/
/* THE FOOTER FLOWS, AND THE BODY HAS A FLOOR.
   The first attempt pinned the footer absolutely to a page of fixed height.
   An absolute block reserves no space, so on a sparse day the last section
   ran into its rule, and reserving the space with padding pushed the page
   over 11in instead. A MINIMUM HEIGHT does both jobs: a sparse body stretches
   to it and the footer lands at the foot of the sheet; a full body grows past
   it and the footer follows, which is the honest thing for the density system
   to then have to prevent.

   The floors below are MEASURED: 11in less the masthead, the hero at that
   density, and the footer. */
.p1 .body { padding: 0 0.55in 0.95in; }

/* ── THE WHITE MASTHEAD ─────────────────────────────────────────────── */
.p1 .mh, .p3 .mh { padding: 0.30in 0.55in 0.26in; border-bottom: 1px solid %(HAIR)s; }
.p1 table.mhg, .p3 table.mhg { width: 100%%; border-collapse: collapse; }
.p1 td.mhl, .p3 td.mhl { vertical-align: bottom; }
.p1 td.mhr, .p3 td.mhr { vertical-align: bottom; text-align: right; }
.p1 .mhmark, .p3 .mhmark { font-size: 21px; font-weight: 700; letter-spacing: 0.22em;
              color: %(NAVY)s; line-height: 1; }
.p1 .mhsub, .p3 .mhsub { font-size: 9.5px; color: %(MUTED)s; padding-top: 7px;
             letter-spacing: 0.01em; }
.p1 .mhdoc, .p3 .mhdoc { font-size: 8.5px; font-weight: 700; letter-spacing: 0.16em;
             text-transform: uppercase; color: %(NAVY)s; }
.p1 .mhwhere, .p3 .mhwhere { font-size: 7.5px; font-weight: 700; letter-spacing: 0.11em;
               color: %(MUTED)s; padding-top: 6px; }
.p1 .mhbar, .p3 .mhbar { color: %(HAIR)s; padding: 0 7px; font-weight: 400; }

/* ── THE HERO ───────────────────────────────────────────────────────────
   A navy base fading to pale at the right with two very low-contrast
   diagonal facets over it. Layered linear-gradients, no image: the document
   is emailed and rasterised, and an asset would be one more thing that can
   fail to load on a page a lender reads.
*/
.p1 .hero, .p3 .hero {
  background:
    linear-gradient(104deg, rgba(255,255,255,0) 40%%,
                            rgba(255,255,255,0.10) 40.2%%,
                            rgba(255,255,255,0.10) 58%%,
                            rgba(255,255,255,0) 58.2%%),
    linear-gradient(68deg,  rgba(255,255,255,0) 57%%,
                            rgba(255,255,255,0.085) 57.2%%,
                            rgba(255,255,255,0.085) 78%%,
                            rgba(255,255,255,0) 78.2%%),
    linear-gradient(96deg, #0A1929 0%%, #0A1929 32%%, #15273B 46%%,
                           #2E4761 58%%, #61798F 72%%, #9FB1C2 86%%,
                           #D3DAE2 100%%);
  color: #fff; padding: 0.36in 0.55in 0.38in; }
.p1 .hdoc, .p3 .hdoc { font-size: 9px; font-weight: 700; letter-spacing: 0.23em;
            text-transform: uppercase; color: #C8D6E4; }
/* THE DOMINANT ELEMENT ON THE PAGE, and it is allowed to take two lines:
   the reference sets it at a size where a long address wraps, and a wrapped
   address at this weight still reads as the subject. */
.p1 .haddr, .p3 .haddr { font-size: 35px; font-weight: 700; letter-spacing: -0.018em;
             line-height: 1.06; padding-top: 12px; max-width: 6.1in; }
.p1 .hcity, .p3 .hcity { font-size: 14px; color: #C2D0DE; padding-top: 7px; }
.p1 .hrule, .p3 .hrule { border-top: 2px solid rgba(255,255,255,0.55); width: 0.34in;
             margin: 0.20in 0 0.14in; }
.p1 .hwhen, .p3 .hwhen { font-size: 11px; color: #C2D0DE; }

/* ── THE RAIL ───────────────────────────────────────────────────────────
   Editorial, not spreadsheet columns: the figure leads, the label is a quiet
   caption, and the separators are hairlines that stop short of the cell.
*/
.p1 table.rail { width: 100%%; border-collapse: collapse;
                 border-bottom: 1px solid %(HAIR)s; }
.p1 table.rail td { width: 20%%; vertical-align: top;
                    padding: 0.21in 0.17in 0.21in 0;
                    border-left: 1px solid %(HAIR)s; }
.p1 table.rail td.first { border-left: none; padding-left: 0; }
.p1 .rv { font-size: 32px; font-weight: 700; color: %(NAVY)s; line-height: 1;
          letter-spacing: -0.025em; }
.p1 .rv.q { color: %(MUTED)s; }
.p1 .rl { font-size: 7px; font-weight: 700; letter-spacing: 0.11em;
          text-transform: uppercase; color: %(MUTED)s; padding-top: 10px; }
.p1 .rs { font-size: 9px; color: %(MUTED)s; padding-top: 6px;
          line-height: 1.5; }

/* ── EXECUTIVE SUMMARY AND THE WEATHER CARD ─────────────────────────── */
.p1 table.ex2 { width: 100%%; border-collapse: collapse; }
.p1 td.exl { width: 64%%; vertical-align: top; padding-right: 0.32in; }
.p1 td.exr { width: 36%%; vertical-align: top; }
.p1 .exec { padding: 0.20in 0 0.05in; }
.p1 .eyebrow { font-size: 7.5px; font-weight: 700; letter-spacing: 0.15em;
               text-transform: uppercase; color: %(MUTED)s; }
.p1 .ehead { font-size: 21px; font-weight: 700; color: %(NAVY)s;
             line-height: 1.18; letter-spacing: -0.012em; padding-top: 10px; }
.p1 .ebody { font-size: 11.5px; line-height: 1.62; color: %(INK)s;
             padding-top: 13px; }
.p1 .eclose { font-size: 11.5px; font-weight: 700; color: %(NAVY)s;
              padding-top: 12px; }
.p1 .wx { background: %(PANEL)s; padding: 0.18in 0.20in 0.20in;
          margin-top: 0.20in; }
.p1 .wxh { font-size: 7.5px; font-weight: 700; letter-spacing: 0.15em;
           text-transform: uppercase; color: %(MUTED)s; }
.p1 .wxrule { border-top: 2px solid %(HAIR)s; width: 0.30in;
              margin: 0.13in 0 0.15in; }
/* THE THREE VALUES, AND THE TEMPERATURE LEADS. */
.p1 .wxcond { font-size: 13px; color: %(INK)s; line-height: 1.2; }
.p1 .wxtemp { font-size: 30px; font-weight: 700; color: %(NAVY)s;
              line-height: 1; letter-spacing: -0.02em; padding-top: 6px; }
.p1 .wxwind { font-size: 12px; color: %(MUTED)s; padding-top: 9px; }
/* AND THE WHOLE-LINE MESSAGES, which have no breakdown behind them. */
.p1 .wxline { font-size: 12.5px; color: %(NAVY)s; line-height: 1.55;
              font-weight: 500; }
.p1 .exrule { border-top: 1px solid %(HAIR)s; margin-top: 0.22in; }

/* ── ACTIVITY ───────────────────────────────────────────────────────────
   Typographic blocks. The old table row is gone: a row of cells with a rule
   under it is the Excel reading the reference was drawn to replace.
*/
.p1 .sechead { font-size: 8px; font-weight: 700; letter-spacing: 0.15em;
               text-transform: uppercase; color: %(MUTED)s;
               padding: 0.19in 0 0.05in; }
.p1 .act { padding: 0.13in 0 0.12in; border-bottom: 1px solid %(HAIR)s;
           page-break-inside: avoid; break-inside: avoid; }
.p1 table.actg { width: 100%%; border-collapse: collapse; }
.p1 td.actl { vertical-align: top; }
.p1 td.actr { vertical-align: top; text-align: right; }
.p1 .actco { font-size: 17px; font-weight: 700; color: %(NAVY)s;
             line-height: 1.15; letter-spacing: -0.01em; }
.p1 .actwhere { font-size: 11px; color: %(MUTED)s; padding-top: 6px; }
.p1 .actstate { font-size: 11.5px; color: %(INK)s; }
.p1 .chip { display: inline-block; font-size: 7.5px; font-weight: 700;
            letter-spacing: 0.10em; text-transform: uppercase;
            color: %(MUTED)s; border: 1px solid %(HAIR)s;
            background: %(PANEL)s; padding: 4px 8px; margin-top: 8px; }

/* GATE WORKFORCE IS A CAPTION OF THE SECTION ABOVE IT, so it takes the
   section's label type and no rule of its own. */
.p1 table.gw { width: 100%%; border-collapse: collapse; margin-top: 0.12in; }
.p1 table.gw td { vertical-align: baseline; padding: 0; }
.p1 td.gwl { width: 1.35in; font-size: 7px; font-weight: 700;
             letter-spacing: 0.11em; text-transform: uppercase;
             color: %(MUTED)s; }
.p1 td.gwv { font-size: 11px; color: %(INK)s; }
.p1 .xg { font-size: 12px; color: %(INK)s; padding-top: 2px; }
.p1 .xg strong { color: %(NAVY)s; }
.p1 .xgn { font-size: 9.5px; color: %(MUTED)s; padding-top: 6px; }

/* ── ATTENTION AND SAFETY ───────────────────────────────────────────── */
.p1 .att { margin-top: 0.22in; border-top: 2px solid %(NAVY)s;
           padding-top: 0.18in; }
.p1 table.two { width: 100%%; border-collapse: collapse; }
.p1 .abox { border: 1px solid %(AMBER)s; background: %(AMBER_FIELD)s;
            padding: 15px 16px; }
.p1 .ahead { font-size: 16px; font-weight: 700; color: %(AMBER)s;
             line-height: 1.2; }
.p1 .aitem { font-size: 11px; color: %(INK)s; padding-top: 7px; }
.p1 .sbox { border: 1px solid %(HAIR)s; background: %(PANEL)s;
            padding: 15px 16px; }
.p1 .sval { font-size: 14px; font-weight: 700; color: %(MUTED)s;
            line-height: 1.2; }
.p1 .snote { font-size: 10px; color: %(MUTED)s; padding-top: 7px;
             line-height: 1.5; }
/* A CLEAR STATUS IS A LINE, NOT A PANEL. A large box whose whole content is
   the word "Clear" reads as emphasis on nothing. The panel is reserved for a
   status that needs explaining. */
.p1 table.sline { width: 100%%; border-collapse: collapse;
                  border-bottom: 1px solid %(HAIR)s; }
.p1 table.sline td { padding: 13px 0; vertical-align: baseline; }
.p1 table.sline td.sll { width: 1.35in; font-size: 7px; font-weight: 700;
                         letter-spacing: 0.11em; text-transform: uppercase;
                         color: %(MUTED)s; }
.p1 .sok { font-size: 14px; font-weight: 700; color: %(NAVY)s; }
.p1 .sokrow { border-top: 1px solid %(HAIR)s;
              border-bottom: 1px solid %(HAIR)s; padding: 13px 0; }

/* ── THE FOOTER ─────────────────────────────────────────────────────────
   AT THE FOOT OF THE SHEET, not after the content. A footer that flows sits
   halfway up a sparse day and reads as the place the document stopped.
*/
.p1 .ft, .p3 .ft { position: absolute; left: 0.55in; right: 0.55in; bottom: 0.30in; }
.p1 .ftrule, .p3 .ftrule { border-top: 1px solid %(NAVY)s; margin-bottom: 0.11in; }
.p1 table.ftg, .p3 table.ftg { width: 100%%; border-collapse: collapse; }
.p1 td.ftl, .p3 td.ftl { vertical-align: top; }
.p1 td.ftr, .p3 td.ftr { vertical-align: top; text-align: right; font-size: 7.5px;
             font-weight: 700; letter-spacing: 0.11em;
             text-transform: uppercase; color: %(MUTED)s;
             padding-top: 3px; }
.p1 .ftmark, .p3 .ftmark { font-size: 11px; font-weight: 700; letter-spacing: 0.20em;
              color: %(NAVY)s; line-height: 1; }
.p1 .ftwhere, .p3 .ftwhere { font-size: 7px; font-weight: 700; letter-spacing: 0.10em;
               color: %(MUTED)s; padding-top: 6px; }
.p1 .ftno, .p3 .ftno { color: %(NAVY)s; font-size: 12px;
            letter-spacing: 0; padding-left: 14px; }
.p3 .ftmeta, .p1 .ftmeta { font-size: 6.5px; color: %(FAINT)s;
            padding-top: 6px; letter-spacing: 0.02em; }

/* PAGE 3 TAKES THE TIGHTEST HEAD. Page 1 chooses its hero by how much it has
   to say; page 3 always has a register to fit and nothing to spend on a
   taller masthead. MEASURED: the head ran to 3.61in of an 11in sheet and the
   grid had 6.51in left for up to four rows and a totals line. */
.p3 .mh { padding: 0.22in 0.55in 0.20in; }
.p3 .hero { padding: 0.22in 0.55in 0.24in; }
.p3 .haddr { font-size: 24px; padding-top: 8px; }
.p3 .hcity { font-size: 12px; padding-top: 5px; }
.p3 .hrule { margin: 0.12in 0 0.09in; }
.p3 .hwhen { font-size: 10px; }

/* ── PAGE 1 ADAPTS VERTICALLY ──────────────────────────────────────────
   The rules above are the MIDDLE density, which is what a three or four
   activity day gets. The two sets below move the things that actually decide
   this page's height: the hero, the rail, the executive block, the activity
   blocks and the gap above Attention/Safety.

   `air` is for a day with almost nothing on it -- one activity, nothing
   outstanding -- where the page would otherwise stop two thirds of the way
   down the sheet. `tight` is for a day that fills it. The invariant both
   exist to hold is that PAGE 1 IS ONE SHEET, and it is measured by rendering
   rather than by arithmetic.
*/
/* THE FOOTER IS PINNED, AND THE BODY RESERVES ITS ROOM.
   THREE WAYS WERE TRIED AND THE OTHER TWO ARE WORTH RECORDING. A hand-measured
   `min-height` on the body moved the WHOLE body to a second sheet the moment
   the measurement was a tenth of an inch out. A fixed-height table shell with
   a stretching middle row does not stretch: WeasyPrint 70 laid the table out
   at its content height and the footer floated a fifth of a sheet above the
   bottom edge.

   So the footer is absolutely positioned in a page-height block, and the body
   carries the reserve as padding. Both numbers are measured, and the density
   system is what keeps content inside them -- `test_page_1_is_ONE_SHEET`
   renders every shape and counts the sheets. */
.p1 { position: relative; height: 10.96in; }
.p1.air .hero { padding: 0.41in 0.55in 0.43in; }
.p1.air table.rail td { padding: 0.24in 0.17in 0.24in 0; }
.p1.air .exec { padding: 0.25in 0 0.06in; }
.p1.air .sechead { padding: 0.23in 0 0.06in; }
.p1.air .act { padding: 0.16in 0 0.15in; }
.p1.air table.gw { margin-top: 0.15in; }
.p1.air .att { margin-top: 0.27in; padding-top: 0.22in; }
.p1.air .exrule { margin-top: 0.27in; }

/* `dense` IS THE FLOOR. Five blocks and up -- the 31 August shape, four
   activities and two outstanding records. Everything `tight` moves, this
   moves further, and nothing below it exists: past this the page is full and
   the honest answer is that it is full. */
.p1.dense .hero { padding: 0.21in 0.55in 0.23in; }
.p1.dense .hdoc { font-size: 8px; letter-spacing: 0.20em; }
.p1.dense .haddr { font-size: 24px; padding-top: 7px; }
.p1.dense .hcity { font-size: 12px; padding-top: 5px; }
.p1.dense .hrule { margin: 0.11in 0 0.08in; }
.p1.dense .hwhen { font-size: 10px; }
.p1.dense table.rail td { padding: 0.11in 0.17in 0.11in 0; }
.p1.dense .rv { font-size: 24px; }
.p1.dense .rl { font-size: 6.5px; padding-top: 6px; }
.p1.dense .rs { font-size: 7.5px; padding-top: 3px; }
.p1.dense .exec { padding: 0.12in 0 0.02in; }
.p1.dense .ehead { font-size: 16px; padding-top: 5px; }
.p1.dense .ebody { font-size: 10.5px; padding-top: 8px; line-height: 1.5; }
.p1.dense .eclose { font-size: 10.5px; padding-top: 7px; }
.p1.dense .wx { margin-top: 0.12in; padding: 0.11in 0.14in 0.12in; }
.p1.dense .wxline { font-size: 11.5px; }
.p1.dense .wxcond { font-size: 11px; }
.p1.dense .wxtemp { font-size: 22px; padding-top: 4px; }
.p1.dense .wxwind { font-size: 10px; padding-top: 5px; }
.p1.dense .wxrule { margin: 0.07in 0 0.08in; }
.p1.dense .exrule { margin-top: 0.09in; }
.p1.dense .sechead { padding: 0.11in 0 0.02in; font-size: 7.5px; }
/* THE ACTIVITY BLOCK IS WHAT SCALES WITH THE DAY, so it is where the last
   of the room comes from: every tenth of an inch here is multiplied by the
   number of activities. */
.p1.dense .act { padding: 0.055in 0 0.05in; }
.p1.dense .actco { font-size: 13px; }
.p1.dense .actwhere { font-size: 9.5px; padding-top: 3px; }
.p1.dense .actstate { font-size: 10.5px; }
.p1.dense .chip { padding: 2px 5px; margin-top: 4px; font-size: 6.5px; }
.p1.dense table.gw { margin-top: 0.07in; }
.p1.dense td.gwv { font-size: 10px; }
.p1.dense .xg { font-size: 11px; }
.p1.dense .xgn { font-size: 8.5px; padding-top: 4px; }
.p1.dense .att { margin-top: 0.10in; padding-top: 0.09in; }
.p1.dense .abox, .p1.dense .sbox { padding: 9px 10px; }
.p1.dense .ahead { font-size: 14px; }
.p1.dense .aitem { font-size: 10px; padding-top: 5px; }
.p1.dense .sval { font-size: 12px; }
.p1.dense .snote { font-size: 9px; padding-top: 5px; }
.p1.dense table.sline td { padding: 6px 0; }
.p1.dense .sokrow { padding: 6px 0; }

.p1.tight .hero { padding: 0.28in 0.55in 0.30in; }
.p1.tight .haddr { font-size: 27px; padding-top: 9px; }
.p1.tight .hrule { margin: 0.15in 0 0.11in; }
.p1.tight table.rail td { padding: 0.15in 0.17in 0.15in 0; }
.p1.tight .rv { font-size: 27px; }
.p1.tight .rl { padding-top: 8px; }
.p1.tight .rs { font-size: 8px; padding-top: 4px; }
.p1.tight .exec { padding: 0.14in 0 0.03in; }
.p1.tight .ehead { font-size: 18px; padding-top: 7px; }
.p1.tight .ebody { font-size: 11px; padding-top: 10px; line-height: 1.55; }
.p1.tight .eclose { font-size: 11px; padding-top: 9px; }
.p1.tight .wx { margin-top: 0.18in; padding: 0.15in 0.18in 0.17in; }
.p1.tight .wxline { font-size: 12.5px; }
.p1.tight .wxcond { font-size: 12px; }
.p1.tight .wxtemp { font-size: 26px; padding-top: 5px; }
.p1.tight .wxwind { font-size: 11px; padding-top: 7px; }
.p1.tight .wxrule { margin: 0.10in 0 0.11in; }
.p1.tight .exrule { margin-top: 0.18in; }
.p1.tight .sechead { padding: 0.13in 0 0.03in; }
.p1.tight .act { padding: 0.095in 0 0.09in; }
.p1.tight .actco { font-size: 14px; }
.p1.tight .actwhere { font-size: 10px; padding-top: 4px; }
.p1.tight .actstate { font-size: 11px; }
.p1.tight .chip { padding: 3px 6px; margin-top: 6px; font-size: 7px; }
.p1.tight table.gw { margin-top: 0.10in; }
.p1.tight .xg { font-size: 11.5px; }
.p1.tight .xgn { font-size: 9px; padding-top: 5px; }
.p1.tight .att { margin-top: 0.17in; padding-top: 0.15in; }
.p1.tight .abox, .p1.tight .sbox { padding: 11px 12px; }
.p1.tight .ahead { font-size: 15px; }
.p1.tight .aitem { font-size: 10.5px; padding-top: 6px; }
.p1.tight .sval { font-size: 13px; }
.p1.tight .snote { font-size: 9.5px; padding-top: 6px; }
.p1.tight table.sline td { padding: 8px 0; }
.p1.tight .sokrow { padding: 8px 0; }

/* ── WHAT MAY NOT BE SPLIT ─────────────────────────────────────────────
   THIS STYLESHEET HAD NO BREAK RULES AT ALL, and the page-two allocation was
   the only thing keeping a band whole -- which is to say, an arithmetic
   assumption. The old report made the same assumption and it failed on a
   filed document: a band header stranded at the foot of a sheet with its
   photographs overleaf, and THE HEADER IS THE ATTRIBUTION, so eight
   photographs appeared belonging to nobody.

   `break-after: avoid` ON THE HEADER, not `break-inside: avoid` on the band.
   A band taller than what is left of a page cannot honour an inside rule, and
   WeasyPrint answers an unsatisfiable one by relocating the whole block to a
   fresh sheet and leaving a hole. The header simply may not be the last thing
   on a page; that is the actual rule.
*/
.bandhead { page-break-after: avoid; break-after: avoid-page; }
table.shots td { page-break-inside: avoid; break-inside: avoid; }
table.shots tr { page-break-inside: avoid; break-inside: avoid; }
/* A RECORD IS A UNIT: its state, its evidence and its link are one
   statement. The rule lives with the rest of page 3's, on `.rec`. */
/* An activity row's company and its count statement are one row of one fact. */
table.acts tr { page-break-inside: avoid; break-inside: avoid; }
/* The two boxes at the foot of Page 1, each of which is a whole claim. */
.abox, .sbox { page-break-inside: avoid; break-inside: avoid; }
/* A section heading is never the last thing on a sheet. */
.sechead, .comph, .p2h { page-break-after: avoid; break-after: avoid-page; }

/* PAGE 2 */
.p2 { page-break-before: always; padding: 0.42in 0.55in 0.34in; }
.p2ref { font-size: 7.5px; font-weight: 700; letter-spacing: 0.12em;
         text-transform: uppercase; color: %(MUTED)s;
         border-bottom: 1px solid %(HAIR)s; padding-bottom: 8px; }
.p2h { font-size: 21px; font-weight: 700; color: %(NAVY)s;
       letter-spacing: -0.01em; padding-top: 0.18in; }
.p2sub { font-size: 9.5px; color: %(MUTED)s; padding-top: 5px; }
.bandhead { padding: 0.15in 0 0.09in; }
.bno { font-size: 9px; font-weight: 700; letter-spacing: 0.10em;
       color: %(MUTED)s; padding-right: 9px; }
.bco { font-size: 13.5px; font-weight: 700; color: %(NAVY)s;
       line-height: 1.2; }
.bwhat { font-size: 10px; color: %(MUTED)s; padding-top: 4px; }
/* WIDTH AUTO, AND LEFT. The table used to be 100%% of the page and divide
   itself into equal columns, so a photograph narrower than its column sat in
   a pale field on both sides -- 2.6in of grey either side of a 1.1in picture
   on the 31 August page. It hugs its contents now and lines up with the band
   header above it. */
table.shots { width: auto; border-collapse: separate;
              border-spacing: 0 4.5px; }
table.shots td + td { padding-left: 4.5px; }
/* NO FIXED CELL HEIGHT. It used to be set from the allocation, and the
   photograph sat inside it at whatever size its own aspect allowed -- which
   left a grey margin above and below every picture whose width ran out
   first. With the capture padding cropped the pictures are 3:4 rather than
   0.449, so width is what runs out, and the slack was visible on every cell
   of the 10 September page.

   THE ALLOCATION STILL DECIDES THE CEILING; it just stops deciding the
   floor. `max-height` on the image caps a tall photograph, the cell takes
   the height of what is actually in it, and nothing is padded to a number. */
table.shots td { text-align: center; vertical-align: middle;
                 background: %(PANEL)s; line-height: 0; }
/* CONTAIN, NEVER COVER. No object-fit, no fixed aspect on the image, no
   overflow hidden. The cell has the geometry; the photograph keeps its own,
   so a portrait leaves air at the sides and nothing is ever cut. */
table.shots img { max-width: 100%%; display: inline-block; }
/* AND THE EMPTY CELLS OF A PARTIAL ROW CARRY NO FIELD AT ALL. A grey panel
   where a photograph is not is a place-holder for something that does not
   exist. */
table.shots td.none { background: #fff; }

/* ══ PAGE 3 ══════════════════════════════════════════════════════════════
   A QUIET EDITORIAL REGISTER. The bordered cards are gone: records are
   separated by whitespace and hairlines, and the only ink on the page that
   is not type is a rule.

   EVERY RULE HERE IS SCOPED TO `.p3`, so pages 1 and 2 are not reachable.
*/
.p3 { page-break-before: always; position: relative; height: 10.96in; }
.p3 .body { padding: 0 0.55in 0.95in; }

/* The masthead, the hero and the footer are page 1's, by instruction, and
   their rules are written once under `.p1 .x, .p3 .x` above. */

h1.sec { font-size: 22px; font-weight: 700; letter-spacing: -0.012em;
         margin: 0; color: %(NAVY)s; }
.p3 .sec { padding-top: 0.22in; }
.sub { font-size: 8px; font-weight: 700; letter-spacing: 0.13em;
       text-transform: uppercase; color: %(MUTED)s; padding-top: 7px; }
.secrule { border-top: 1px solid %(NAVY)s; margin: 0.10in 0 0; }

/* ── THE GRID ───────────────────────────────────────────────────────────
   Hairlines between the columns and under every row but the last, and a
   generous gutter so the rules are a whisper rather than a table.
*/
table.grid { width: 100%%; border-collapse: collapse; }
table.grid td { width: 33.33%%; vertical-align: top;
                padding: 0.16in 0.26in 0.16in;
                border-left: 1px solid %(HAIR)s;
                border-bottom: 1px solid %(HAIR)s; }
table.grid td.first { border-left: none; padding-left: 0; }
table.grid tr.lastrow td { border-bottom: none; }

/* ── ONE RECORD ─────────────────────────────────────────────────────────
   A muted number, the title as the strongest thing in the block, the
   citation under it, the evidence, then the state as quiet metadata.
*/
.rec { page-break-inside: avoid; break-inside: avoid; }
.reclink { text-decoration: none; }
.recno { font-size: 15px; font-weight: 700; letter-spacing: 0.04em;
         color: %(FAINT)s; line-height: 1; }
/* A FIXED HEIGHT SO THE CITATIONS LINE UP ACROSS A ROW, and tall enough for
   the two-line titles. "Construction Superintendent Log" and "Subcontractor
   Safety Orientation" both wrap, and every height below is the two-line case
   measured rather than guessed: font-size x 1.25 x 2 plus the padding.
   At 36px the citation printed OVER the second line of the title. */
.rect { font-size: 13px; font-weight: 700; line-height: 1.25;
        color: %(NAVY)s; padding-top: 8px; height: 42px; }
.recc { font-size: 8.5px; color: %(MUTED)s; letter-spacing: 0.02em; }

/* THE EVIDENCE. Top-anchored and clipped, which is the behaviour that was
   already there: the card is an index entry, not a preview of the sheet. */
/* 1.50in -> 1.28in. A MISSING RECORD IS TALLER THAN A FILED ONE -- it adds
   what is absent, a rule and the state under the same empty evidence space --
   and a two-row register of them put the second row on a second sheet. The
   window is what gives way; see `page_3_density`. */
.doc { height: 1.46in; overflow: hidden; margin: 0.10in 0 0;
       background: #fff; border: 1px solid %(HAIR)s; }
.doc img { width: 100%%; display: block; }
/* AND A MISSING RECORD DRAWS NOTHING AT ALL. No dashed box, no grey panel,
   no outline of a document that was not filed -- the space is simply empty,
   and it keeps its height so the rows stay aligned. */
.doc.empty { border: none; background: transparent; }
.docmsg { font-size: 8.5px; color: %(FAINT)s; padding-top: 0.58in;
          line-height: 1.45; }

.recstate { font-size: 8px; font-weight: 700; letter-spacing: 0.10em;
            text-transform: uppercase; padding-top: 7px; }
.recstate.filed { color: %(GREEN)s; }
.recstate.missing { color: %(AMBER)s; }
.recstate.not_due { color: %(MUTED)s; }
.recnote { font-size: 9.5px; color: %(INK)s; line-height: 1.4;
           padding-top: 0.09in; }
.recrule { border-top: 2px solid %(AMBER)s; width: 0.34in;
           margin: 0.08in 0 0; }
.recrule.not_due { border-top-color: %(HAIR)s; }
.recfact { font-size: 8.5px; color: %(INK)s; padding-top: 7px;
           line-height: 1.4; }

/* ── THE DOCUMENT WINDOW SHRINKS AS THE REGISTER GROWS ──────────────────
   Eleven records is the ceiling, which is four rows. The evidence is the only
   thing that may give way: every number, title, citation and state prints at
   a readable size whatever the day holds, and a smaller thumbnail still shows
   WHICH document it is.
*/
.p3.r3 table.grid td { padding: 0.11in 0.24in 0.11in; }
.p3.r3 .doc { height: 0.72in; margin-top: 0.08in; }
.p3.r3 .docmsg { padding-top: 0.24in; }
.p3.r3 .rect { font-size: 12.5px; height: 40px; padding-top: 7px; }
.p3.r3 .recnote { padding-top: 0.07in; }
.p3.r3 .recrule { margin-top: 0.06in; }
.p3.r3 .recstate { padding-top: 6px; }

.p3.r4 table.grid td { padding: 0.075in 0.22in 0.075in; }
.p3.r4 .doc { height: 0.44in; margin-top: 0.06in; }
.p3.r4 .docmsg { padding-top: 0.11in; font-size: 7.5px; }
.p3.r4 .rect { font-size: 12px; height: 38px; padding-top: 6px; }
.p3.r4 .recno { font-size: 13px; }
.p3.r4 .recc { font-size: 8px; }
.p3.r4 .recstate { padding-top: 5px; }
.p3.r4 .recnote { padding-top: 0.06in; font-size: 9px; }
.p3.r4 .recrule { margin-top: 0.05in; }
.p3.r4 .recfact { font-size: 8px; padding-top: 4px; }

/* FIVE ROWS IS THE CEILING, and at five the window is a strip. Eleven
   records plus a totals line is what the operator set as the most the page
   must hold, and the thumbnail is the only thing that may give way. */
.p3.r5 table.grid td { padding: 0.055in 0.20in 0.055in; }
.p3.r5 .doc { height: 0.30in; margin-top: 0.05in; }
.p3.r5 .docmsg { padding-top: 0.06in; font-size: 7px; }
.p3.r5 .rect { font-size: 11.5px; height: 35px; padding-top: 5px; }
.p3.r5 .recno { font-size: 12px; }
.p3.r5 .recc { font-size: 7.5px; }
.p3.r5 .recstate { padding-top: 4px; }
.p3.r5 .recnote { padding-top: 0.05in; font-size: 8.5px; }
.p3.r5 .recrule { margin-top: 0.04in; }
.p3.r5 .recfact { font-size: 7.5px; padding-top: 3px; }
.p3.r5 .cnum { font-size: 21px; }
.p3.r5 table.cf { margin-top: 0.09in; }
.p3.r5 .cnote { padding-top: 0.09in; }

/* ── THE TOTALS LINE ────────────────────────────────────────────────────
   Horizontal, compact, and the last thing in the register rather than a
   panel beside it.
*/
.comp { margin: 0.20in 0 0; border-top: 1px solid %(NAVY)s;
        padding-top: 0.14in; }
.comp.inset { margin: 0; border: none; padding: 0; }
.comph { font-size: 7.5px; font-weight: 700; letter-spacing: 0.15em;
         text-transform: uppercase; color: %(MUTED)s; }
table.cf { width: 100%%; border-collapse: collapse; margin-top: 0.12in; }
table.cf td { vertical-align: top; padding: 0 0.18in;
              border-left: 1px solid %(HAIR)s; }
table.cf td.first { border-left: none; padding-left: 0; }
.cnum { font-size: 27px; font-weight: 700; color: %(NAVY)s; line-height: 1;
        letter-spacing: -0.022em; }
.cnum.owed { color: %(AMBER)s; }
/* ONE LINE EACH. "Required daily logs filed" wrapped at 0.10em of tracking
   inside a third of the page, and a label broken across two lines beside a
   figure reads as two labels. */
.clab { font-size: 7px; font-weight: 700; letter-spacing: 0.04em;
        text-transform: uppercase; color: %(MUTED)s; padding-top: 9px;
        line-height: 1.35; white-space: nowrap; }
.cnote { font-size: 8px; color: %(MUTED)s; padding-top: 0.13in;
         line-height: 1.5; }
.p3.r4 .cnum { font-size: 23px; }
.p3.r4 table.cf { margin-top: 0.11in; }
.p3.r4 .cnote { padding-top: 0.11in; }

""" % dict(NAVY=NAVY, INK=INK, MUTED=MUTED, FAINT=FAINT, HAIR=HAIR,
           PANEL=PANEL, AMBER=AMBER, AMBER_FIELD=AMBER_FIELD, GREEN=GREEN)


# ══════════════════════════════════════════════════════════════════════════
#  SHARED
# ══════════════════════════════════════════════════════════════════════════

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


def render_masthead(banner: BannerView) -> str:
    """THE WHITE HEAD OF PAGE 1. Editorial, and it carries no claim.

    Left is the name and what the company does; right is what the document is
    and which job it is about. The marketing line that used to sit here is
    struck rather than replaced -- a report a lender reads is not a place to
    say anything about ourselves that the pages do not prove.
    """
    return (
        '<div class="mh"><table class="mhg"><tr>'
        '<td class="mhl">'
        f'<div class="mhmark">{esc(banner.wordmark)}</div>'
        f'<div class="mhsub">{esc(banner.tagline)}</div></td>'
        '<td class="mhr">'
        f'<div class="mhdoc">{esc(banner.document_title)}</div>'
        f'<div class="mhwhere">{esc(banner.address.upper())}'
        '<span class="mhbar">|</span>'
        f'{esc(banner.city.upper())}</div></td>'
        "</tr></table></div>")


def render_hero(banner: BannerView) -> str:
    """THE PROJECT BANNER. The address is the dominant element on the page.

    The tonal facets are two very low-contrast diagonals over a navy-to-pale
    fade. No photograph, no blueprint, no cinematic effect: this has to read as
    stationery at a glance and survive being printed on a mono laser.
    """
    return (
        '<div class="hero"><div class="herob">'
        f'<div class="hdoc">{esc(banner.document_title)}</div>'
        f'<div class="haddr">{esc(banner.address.upper())}</div>'
        f'<div class="hcity">{esc(banner.city)}</div>'
        '<div class="hrule"></div>'
        f'<div class="hwhen">{esc(banner.dateline)}</div>'
        "</div></div>")


def render_weather_card(wx: WeatherView) -> str:
    """WEATHER, AS A DESIGNED PANEL RATHER THAN A ROW OF METADATA.

    THE TEMPERATURE LEADS, which is what the reference asks for and what a
    reader looks for first. The condition sits above it and the wind below.

    NOTHING IS PARSED HERE. The three values arrive resolved from
    `_weather_parts`, the same resolution that composes the line; this layer
    chooses sizes and nothing else.

    AND WHEN THERE IS NO BREAKDOWN THE PANEL PRINTS THE LINE. "Weather could
    not be retrieved" and "not recorded" are whole-line messages with no parts
    behind them, and a heading over three empty fields would say less than the
    sentence does.
    """
    if not wx.detailed:
        return (
            '<div class="wx"><div class="wxh">Weather</div>'
            '<div class="wxrule"></div>'
            f'<div class="wxline">{esc(wx.line)}</div></div>')
    wind = (f'<div class="wxwind">{esc(wx.wind_line)}</div>'
            if wx.wind_line else "")
    return (
        '<div class="wx"><div class="wxh">Weather</div>'
        '<div class="wxrule"></div>'
        + (f'<div class="wxcond">{esc(wx.condition)}</div>'
           if wx.condition else "")
        + (f'<div class="wxtemp">{esc(wx.temperature)}</div>'
           if wx.temperature else "")
        + wind
        + "</div>")


def render_activity_block(a: ActivityRowView) -> str:
    """ONE ACTIVITY, AS A TYPOGRAPHIC BLOCK.

    Company and canonical location on the left; the resolved count statement
    and the state chip on the right, both verbatim. The chip stays neutral
    whichever state it names -- green is reserved for a FILED record and
    agreement between two counts is not a filing.
    """
    return (
        '<div class="act"><table class="actg"><tr>'
        '<td class="actl">'
        f'<div class="actco">{esc(a.company)}</div>'
        f'<div class="actwhere">{esc(a.where)}</div></td>'
        '<td class="actr">'
        f'<div class="actstate">{esc(a.statement)}</div>'
        f'<div class="chip">{esc(a.chip)}</div></td>'
        "</tr></table></div>")


def render_footer(view: ReportView, numeral: str = "1",
                  meta: str = "") -> str:
    """PINNED TO THE FOOT OF THE SHEET, which is what closes the page.

    Absolutely positioned inside the page block rather than left to flow: a
    footer that follows the content sits halfway up a sparse day and reads as
    the place the document stopped.

    `meta` is the tiny line under the identity. Page 3 puts the generation
    timestamp there rather than letting it float beneath the register, where
    it read as one more entry.
    """
    return (
        '<div class="ft"><div class="ftrule"></div><table class="ftg"><tr>'
        '<td class="ftl">'
        f'<div class="ftmark">{esc(view.banner.wordmark)}</div>'
        f'<div class="ftwhere">{esc(view.banner.address.upper())}'
        '<span class="mhbar">|</span>'
        f'{esc(view.banner.city.upper())}</div>'
        + (f'<div class="ftmeta">{esc(meta)}</div>' if meta else "")
        + '</td>'
        '<td class="ftr">'
        f'{esc(view.banner.document_title)}<span class="mhbar">|</span>'
        f'{esc(view.date_long).upper()}'
        f'<span class="ftno">{esc(numeral)}</span></td>'
        "</tr></table></div>")


def page_1_density(view: ReportView) -> str:
    """How much air page 1 can afford. See this module's density note.

    COUNTED, NOT GUESSED. An activity row is the tall thing on this page; the
    additional-gate block and the outstanding-records panel are each worth
    about a row. A day with one activity and neither has three inches to give
    away, and a day with five has none.
    """
    weight = len(view.activities)
    if view.additional_gate is not None:
        weight += 1
    if view.attention is not None:
        weight += 1
    # THE BOUNDARIES MOVED WITH THE REDESIGN and are measured, not chosen:
    # the masthead and hero together are taller than the banner they replace,
    # so a day that fitted at `mid` before does not. 27 August -- three
    # activities and two outstanding records -- is the case that found it.
    if weight <= 1:
        return "air"
    if weight <= 2:
        return "mid"
    if weight <= 4:
        return "tight"
    return "dense"


def render_page_1(view: ReportView) -> str:
    acts = "".join(render_activity_block(a) for a in view.activities)

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
        f'<div class="p1 {page_1_density(view)}">'
        + render_masthead(view.banner)
        + render_hero(view.banner)
        + '<div class="body">'
        + render_rail(view.rail)
        # EXECUTIVE SUMMARY AND WEATHER SHARE A ROW. Two thirds and one third:
        # the summary is the page's argument and the panel is the conditions
        # it happened in.
        + '<table class="ex2"><tr><td class="exl">'
        + '<div class="exec">'
        + f'<div class="eyebrow">{esc(view.summary.eyebrow)}</div>'
        + f'<div class="ehead">{esc(view.summary.headline)}</div>'
        + f'<div class="ebody">{esc(view.summary.body)}</div>'
        + f'<div class="eclose">{esc(view.summary.closing)}</div></div>'
        + '</td><td class="exr">'
        + render_weather_card(view.weather)
        + "</td></tr></table>"
        + '<div class="exrule"></div>'
        + '<div class="sechead">Today&rsquo;s documented activity</div>'
        + acts
        # GATE WORKFORCE IS A CAPTION OF THE ACTIVITY SECTION, not a row of
        # its own. It says who the gate saw; the blocks above say what they
        # did.
        + '<table class="gw"><tr><td class="gwl">Gate workforce</td>'
        + f'<td class="gwv">{esc(view.workforce_line)}</td></tr></table>'
        + extra
        + render_attention_and_safety(attention, view.safety)
        + "</div>"
        + render_footer(view, "1")
        + "</div>")


def render_attention_and_safety(attention: str, safety: SafetyView) -> str:
    """THE LAST BLOCK OF PAGE 1, AND IT DOES NOT LEAVE A HOLE.

    Attention and Safety share a row: outstanding records on the left at 58%,
    the safety conclusion on the right at 42%. That is the ordering the design
    asks for -- discrepancies visible, and subordinate to what was actually
    done.

    TWO THINGS DECIDE WHAT THIS PRINTS.

    IS ANYTHING OUTSTANDING? On a day with nothing outstanding the left cell is
    empty, and a 58% empty cell is not "nothing": it indents Safety into the
    middle of the sheet under a full-width rule, which reads as a section whose
    first half failed to print. Measured on the 10 September report, where 5 of
    5 required logs were filed. So the row collapses to one full-width block --
    the same rule Page 2 follows when a day has no photographs.

    DOES THE STATUS NEED EXPLAINING? `note` is set only when the report cannot
    state a conclusion, because the superintendent's log was not filed. That
    absence is worth a panel and a sentence. "Clear" is one word, and a
    bordered box built around one word reads as emphasis on nothing -- so a
    clear day gets a status LINE. Both were measured on paper: 10 September
    ends on the word Clear in a box with room to spare beneath it; 27 August
    ends on "Status not reported" with the reason under it, and that one earns
    its weight.
    """
    head = '<div class="sechead" style="padding-top:0;">Safety</div>'

    if safety.note:
        block = head + (
            '<div class="sbox">'
            '<div class="sval">Status not reported</div>'
            f'<div class="snote">{esc(safety.note)}</div></div>')
        wide = block
    else:
        tick = f'<span class="sok">&#10003;&nbsp; {esc(safety.value)}</span>'
        # BESIDE THE OUTSTANDING RECORDS the label is the section head, because
        # a 1.35in label column inside a 42% cell leaves the value nowhere to
        # sit. Full width it is a labelled row, which matches the gate and
        # weather lines immediately above it.
        block = head + f'<div class="sokrow">{tick}</div>'
        wide = ('<table class="sline"><tr><td class="sll">Safety</td>'
                f'<td>{tick}</td></tr></table>')

    if not attention:
        return f'<div class="att">{wide}</div>'
    return (
        '<div class="att"><table class="two"><tr>'
        '<td width="58%" style="padding-right:0.22in;">'
        '<div class="sechead" style="padding-top:0;">Attention</div>'
        + attention
        + f'</td><td width="42%">{block}</td>'
        + "</tr></table></div>")


# ══════════════════════════════════════════════════════════════════════════
#  PAGE 2 — VISUAL PROGRESS
# ══════════════════════════════════════════════════════════════════════════

#: The photographs' shape, once the capture padding is off. Measured across
#: 36 production photographs on five days: min 0.737, median 0.748, max 0.749.
#: An ordinary phone portrait, which is what they are.
PHOTO_ASPECT = 0.75

#: The page's usable width: Letter less `.p2`'s 0.55in margins.
BAND_WIDTH_IN = 8.5 - 0.55 - 0.55


def photo_columns(count: int) -> int:
    """Columns for a band. NOT A FORMULA: the shapes are chosen so a band reads
    as a composition rather than a reflow.

    MEASURED SPREAD, photographs per activity row on production:
        1:11  2:17  3:10  4:13  5:11  6:3  8:1  9:2  10:1  12:1
    so every branch is reachable.

    FEWER ROWS, BECAUSE HEIGHT IS THE SCARCE THING. Four photographs used to
    go two-by-two: at the old 0.449 canvas a single row of four was a thin
    strip. Cropped to 3:4 the trade reverses -- a second row halves what every
    row gets, and four across at 1.85in wide is larger than two across at
    1.5in tall. So a band stays on one row up to five, and never exceeds five
    columns, because past that a photograph is smaller than its own caption.
    """
    if count <= 5:
        return max(1, count)
    if count <= 8:
        return 4
    return 5


def photo_rows(count: int, cols: int = 0) -> int:
    cols = cols or photo_columns(count)
    return (count + cols - 1) // cols if cols else 0


def _photo_height(cols: int, row_height_in: float) -> float:
    """What one photograph in a `cols`-wide strip would actually measure.

    Height from the row allocation, width from the column's share of the page,
    and the smaller of the two is the picture -- which is the whole point: the
    fixed table could not see which one was binding.
    """
    wide = (BAND_WIDTH_IN - GAP_IN * max(0, cols - 1)) / max(1, cols)
    capped = min(MAX_CELL_IN, max(MIN_CELL_IN, row_height_in))
    return min(capped, wide / PHOTO_ASPECT)


def _shape_score(counts: Sequence[int], cols: Sequence[int],
                 available_in: float) -> Optional[float]:
    """Total printed photograph area for one assignment, or None if it will
    not fit. Ties are broken by the caller toward fewer rows."""
    rows = [photo_rows(n, c) for n, c in zip(counts, cols)]
    total = sum(rows)
    if not total:
        return None
    heads = (BAND_HEAD_IN + TABLE_EDGE_IN) * len(counts)
    gaps = GAP_IN * max(0, len(counts) - 1)
    area = available_in - heads - gaps
    if area <= 0:
        return None
    row_h = area / total
    score = 0.0
    for n, c in zip(counts, cols):
        h = _photo_height(c, row_h)
        score += n * h * h * PHOTO_ASPECT
    return score


def plan_columns(counts: Sequence[int], available_in: float) -> List[int]:
    """Columns per band, chosen against the height the page can actually give.

    EXHAUSTIVE AND SMALL. Candidates are 1..5 columns capped at the band's own
    count, so a three-photograph band is only ever considered at one, two or
    three across. Past four bands the search is skipped and the natural shapes
    are used: the product grows, and a page carrying five band headers has no
    height to reallocate anyway.
    """
    counts = list(counts)
    if not counts:
        return []
    if len(counts) > 4:
        return [photo_columns(n) for n in counts]

    import itertools
    options = [range(1, min(5, max(1, n)) + 1) for n in counts]
    best, best_key = None, None
    for cols in itertools.product(*options):
        score = _shape_score(counts, cols, available_in)
        if score is None:
            continue
        # MORE PHOTOGRAPH FIRST, then the flatter shape.
        key = (round(score, 4), -sum(photo_rows(n, c)
                                     for n, c in zip(counts, cols)))
        if best_key is None or key > best_key:
            best, best_key = list(cols), key
    return best or [photo_columns(n) for n in counts]


def allocate_bands(counts: Sequence[int], available_in: float,
                   cols: Sequence[int] = ()) -> Tuple[List[float], List[int]]:
    """Inches of photograph area per band, IN PROPORTION TO ROWS not to count.

    Height is what is scarce. Allocating by photograph count gives a four-up
    two-by-two the same height as a four-across single row, and one of those
    needs twice the vertical space.
    """
    rows = [photo_rows(n, c) for n, c in zip(counts, cols or [0] * len(counts))]
    total = sum(rows) or 1
    heads = (BAND_HEAD_IN + TABLE_EDGE_IN) * len(counts)
    gaps = GAP_IN * max(0, len(counts) - 1)
    area = max(0.0, available_in - heads - gaps)
    return [area * r / total for r in rows], rows


def render_band(band: BandView, height_in: float, row_count: int,
                cols: int = 0) -> str:
    cols = cols or photo_columns(band.count)
    cell = min(MAX_CELL_IN,
               max(MIN_CELL_IN,
                   (height_in - GAP_IN * max(0, row_count - 1))
                   / max(1, row_count)))
    # BOUNDED ON BOTH AXES, AND THE CELL IS NEITHER. The allocation caps the
    # height; the column's share of the page caps the width. Whichever binds
    # first decides the picture's size, and the cell is then exactly that size
    # because the table hugs its contents. Nothing is padded to a number, so
    # there is no field left over to print grey.
    wide = (BAND_WIDTH_IN - GAP_IN * max(0, cols - 1)) / max(1, cols)

    cells = ""
    for r in range(row_count):
        cells += "<tr>"
        for c in range(cols):
            k = r * cols + c
            if k >= band.count:
                cells += '<td class="none"></td>'
                continue
            cells += (f'<td><img src="{esc(band.photos[k].url)}" '
                      f'style="max-height:{cell:.3f}in;'
                      f'max-width:{wide:.3f}in;" /></td>')
        cells += "</tr>"
    # TWO LINES, NOT FOUR. The header was a number, a company, a subtitle and
    # a count statement stacked -- 0.76in of caption above every band, which on
    # a four-band page came to more than three inches of the nine available,
    # taken out of the photographs. The number joins the company and the two
    # grey lines join each other; nothing is dropped, and the page got an inch
    # of picture back.
    detail = " &nbsp;&middot;&nbsp; ".join(
        x for x in (esc(band.subtitle), esc(band.statement)) if x)
    return (
        '<div class="bandhead">'
        f'<div class="bco"><span class="bno">{band.number:02d}</span>'
        f'{esc(band.company)}</div>'
        f'<div class="bwhat">{detail}</div></div>'
        f'<table class="shots">{cells}</table>')


def render_page_2(view: ReportView) -> str:
    """EVIDENCE ONLY, AND IT COLLAPSES ENTIRELY when the day has none.

    No banner: a masthead over photographs competes with them. A running
    reference line instead, naming the job and the date.
    """
    if not view.bands:
        return ""
    counts = [b.count for b in view.bands]
    cols = plan_columns(counts, PAGE2_AVAILABLE_IN)
    heights, rows = allocate_bands(counts, PAGE2_AVAILABLE_IN, cols)
    bands = "".join(render_band(b, heights[i], rows[i], cols[i])
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

#: The state each record prints, and the class that colours it.
#:
#: AMBER IS FOR A REQUIRED RECORD THAT IS OWED AND ABSENT, and for nothing
#: else. "Not due today" is not a deficiency and takes the muted ink; a filed
#: record takes green, which on this document means FILED and only that.
STATE_WORDS = {
    CardState.FILED: ("filed", "Filed"),
    CardState.MISSING: ("missing", "Not filed"),
    CardState.NOT_DUE: ("not_due", "Not due today"),
}


def render_record(card: CardView) -> str:
    """ONE RECORD IN THE REGISTER. No box, no badge, no placeholder.

    THE ORDER IS THE HIERARCHY: a muted number, the title as the strongest
    thing in the block, the citation under it in small muted ink, then the
    evidence, then the state as quiet metadata beneath the evidence.

    A MISSING RECORD LEAVES THE EVIDENCE SPACE EMPTY. Not a dashed box, not a
    grey panel, not an outline of a document that does not exist -- each of
    those draws something where nothing was filed, and on a compliance
    register that is the one thing the space must not do. The rows stay
    aligned because the empty space is the same height as a thumbnail.

    THE TITLE AND THE EVIDENCE CARRY THE LINK. The repeated "VIEW LOG" line
    under every card was the third time a reader was told the same thing.
    """
    css, words = STATE_WORDS[card.state]
    filed = card.state is CardState.FILED

    if filed and card.thumbnail:
        doc = f'<div class="doc"><img src="{esc(card.thumbnail)}" /></div>'
    elif filed:
        # THE PICTURE IS AN ILLUSTRATION, NOT THE RECORD. A thumbnail that
        # could not be rendered leaves the entry otherwise intact, and says so
        # in the same quiet ink as everything else rather than drawing a box.
        doc = ('<div class="doc empty"><div class="docmsg">'
               "Document filed &middot; preview unavailable</div></div>")
    else:
        doc = '<div class="doc empty"></div>'

    head = (f'<div class="recno">{card.number:02d}</div>'
            f'<div class="rect">{esc(card.title)}</div>'
            f'<div class="recc">{esc(card.citation)}</div>')
    if card.link:
        head = f'<a class="reclink" href="{esc(card.link)}">{head}</a>'
        doc = f'<a href="{esc(card.link)}">{doc}</a>'

    if filed:
        tail = f'<div class="recstate {css}">{words}</div>'
    else:
        # THE ABSENCE, IN THE ORDER IT READS: what is missing and for when,
        # a short rule, then the state.
        tail = (f'<div class="recnote">{esc(card.absent_note)}</div>'
                f'<div class="recrule {css}"></div>'
                f'<div class="recstate {css}">{words.upper()}</div>')

    facts = "".join(f'<div class="recfact">{esc(f)}</div>' for f in card.facts)
    return f'<div class="rec">{head}{doc}{tail}{facts}</div>'


def render_completeness(completeness: CompletenessView,
                        inset: bool = False) -> str:
    """THE TOTALS LINE, which is what closes a register.

    Three figures side by side under a small eyebrow, separated by hairlines.
    Not a panel: a panel makes the summary compete with the records it
    summarises, and this is the last line of an institutional report rather
    than a dashboard tile.

    `inset` places it beside the last record, in the columns that record does
    not use. Everything else about it is identical, which is the point --
    the same block in two positions rather than two blocks.

    ONLY THE OUTSTANDING FIGURE MAY BE AMBER, and only when it is not zero. A
    zero set in the colour that means "a record is missing" reads as an alarm
    about nothing, and a palette that cries wolf on a complete day is worth
    less on the day it matters.
    """
    shell = "comp inset" if inset else "comp"
    owed = " owed" if completeness.outstanding else ""
    return (
        f'<div class="{shell}">'
        '<div class="comph">Document completeness</div>'
        '<table class="cf"><tr>'
        f'<td class="first"><div class="cnum">'
        f'{esc(completeness.required_ratio)}</div>'
        '<div class="clab">Required daily logs filed</div></td>'
        f'<td><div class="cnum">{completeness.additional}</div>'
        '<div class="clab">Additional records filed</div></td>'
        f'<td><div class="cnum{owed}">{completeness.outstanding}</div>'
        '<div class="clab">Outstanding</div></td>'
        "</tr></table>"
        '<div class="cnote">Required and additional records have different '
        "denominators and are never combined.</div></div>")


def page_3_rows(cards: Sequence[CardView]) -> int:
    """How many rows the register needs INCLUDING the totals line.

    The totals line goes in the cells the last row does not use. When there
    are fewer than two of those it needs a row of its own, and that row costs
    the same page as a row of records -- which is why it is counted here and
    not left for the layout to discover.
    """
    rows = (len(cards) + 2) // 3
    spare = (3 - len(cards) % 3) % 3
    return rows + (0 if spare >= 2 else 1)


def page_3_density(cards: Sequence[CardView]) -> str:
    """How tall a document window the register can afford.

    THE EVIDENCE IS WHAT GIVES WAY, because it is the only thing on this page
    that can. Every record's number, title, citation and state must print at a
    readable size whatever the day holds; the thumbnail is an illustration of
    the filed document and a smaller one still shows which document it is.

    MEASURED, NOT CHOSEN. The head runs to about 3.1in of an 11in sheet and
    the footer starts at 10.12in, so the register has roughly 7in for its
    rows. Eleven records is the ceiling the operator set; with the totals line
    that is five rows, and at five rows the window is a strip that shows the
    document's title bar and little else. That is the trade the ceiling buys.
    """
    rows = page_3_rows(cards)
    if rows <= 2:
        return "r2"
    if rows == 3:
        return "r3"
    if rows == 4:
        return "r4"
    return "r5"


def render_page_3(view: ReportView) -> str:
    """THE REGISTER, AND THE TOTALS LINE INSIDE IT.

    Seven records in three columns leaves 3/3/1, and the lone last record used
    to sit beside two empty cells with the completeness block floating below
    the whole grid. The empty cells are where the totals belong: they are a
    statement ABOUT the register, and putting them there closes the page
    rather than adding to it.

    TWO FREE CELLS OR MORE. One is not enough -- a totals line squeezed into a
    single column would be a record-shaped block of numbers in a row of
    records, which is the confusion this is meant to remove -- so it falls back
    to a line under the grid, which is the same block one row down.
    """
    rows = [view.cards[i:i + 3] for i in range(0, len(view.cards), 3)]
    spare = 3 - len(rows[-1]) if rows else 0
    inset = spare >= 2

    grid = ""
    for n, chunk in enumerate(rows):
        last = n == len(rows) - 1
        rcls = ' class="lastrow"' if last else ""
        grid += f"<tr{rcls}>"
        for c, card in enumerate(chunk):
            cls = "first" if c == 0 else ""
            grid += f'<td class="{cls}">{render_record(card)}</td>'
        if inset and last:
            grid += (f'<td class="first" colspan="{spare}">'
                     + render_completeness(view.completeness, inset=True)
                     + "</td>")
        else:
            grid += '<td class="first"></td>' * (3 - len(chunk))
        grid += "</tr>"

    if not inset:
        # A ROW OF THE REGISTER, NOT A BLOCK UNDER IT. Below the grid it
        # carried its own margin, border and padding, and that was what put
        # five records on two sheets -- the register had already used the
        # page. Spanning the last row costs a third of an inch less and reads
        # as the totals of the thing above it rather than a panel after it.
        grid += ('<tr class="lastrow"><td class="first" colspan="3">'
                 + render_completeness(view.completeness, inset=True)
                 + "</td></tr>")

    return (
        f'<div class="p3 {page_3_density(view.cards)}">'
        + render_masthead(view.banner)
        + render_hero(view.banner)
        + '<div class="body">'
        + '<h1 class="sec">Project record</h1>'
        + '<div class="sub">Regulatory &nbsp;&middot;&nbsp; Safety '
          "&nbsp;&middot;&nbsp; Workforce documentation</div>"
        + '<div class="secrule"></div>'
        + f'<table class="grid">{grid}</table>'
        + "</div>"
        + render_footer(view, "3 of 3", view.generated)
        + "</div>")


# ══════════════════════════════════════════════════════════════════════════
#  THE DOCUMENT
# ══════════════════════════════════════════════════════════════════════════

def render(view: ReportView) -> str:
    """The whole report. ONE ARGUMENT, and it is the view."""
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<style>{stylesheet()}</style></head><body>"
            + render_page_1(view) + render_page_2(view) + render_page_3(view)
            + "</body></html>")
