"""The progress report as a document: HTML for WeasyPrint.

DESIGN RULES (they are the product's credibility, not decoration)
  * Page 1 answers, in 60 seconds: how much activity, what changed since the
    previous period, who is on site, what is at risk, what is coming, and how
    far each kind of work has got (estimated from the daily logs).
  * Sections that have nothing to say are LEFT OUT (no empty "None" pages,
    no "Not provided" cards: ruled 2026-11-18, a card a user has no way to
    fill is not shown).
  * Every statement carries a small source tag -- G gate check-ins, L filed
    daily logs, R DOB/DOT record, S schedule -- and the last page indexes the
    sources, so a reader can tell a record from a figure the engine
    calculated. An ESTIMATE says so where it is printed.
  * Photographs are real photographs from the filed daily logs, each with the
    sub, the date, the location as written and the sub's own work line. No
    generated imagery, and no before/after pairing.
  * Charts show data the engine holds, directly labelled, in one hue family
    plus a muted comparison; colour is never the only encoding.

Pure: no I/O. `images` maps a photo's key to a data URI the server fetched.
"""

from __future__ import annotations

import hashlib
import html
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from lib import progress_report as P
from lib import progress_stages as ST
from lib import project_report as base
from lib import report_regulatory as _REG
from lib import schedule_plan as _SP
from lib.datefmt import strftime as _fmt

NAVY, INK, MUTED, LINE = "#12263F", "#1c2430", "#5b6676", "#e3e7ee"
LEVEL_COLOR = {"critical": "#B42318", "high": "#C2410C", "watch": "#B54708", "ok": "#067647"}

CSS = """
@page { size: Letter; margin: 0.6in 0.6in 0.75in;
  @top-left { content: "HEADER"; font: 7.5pt Helvetica, Arial, sans-serif; color: #7a8599; }
  @bottom-left { content: "SOURCE"; font: 7pt Helvetica, Arial, sans-serif; color: #7a8599; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages);
                  font: 7.5pt Helvetica, Arial, sans-serif; color: #7a8599; } }
@page :first { @top-left { content: none; } }
* { box-sizing: border-box; }
body { font: 9.4pt/1.42 Helvetica, Arial, sans-serif; color: #1c2430; margin: 0; }
.mast { background: #12263F; color: #fff; margin: 0 0 8px; padding: 0.15in 0.3in 8px; border-radius: 6px; }
.mast .brand { font-size: 7.5pt; letter-spacing: 3px; font-weight: 700; opacity: .75; }
.mast h1 { font-size: 21pt; line-height: 1.1; margin: 6px 0 2px; font-weight: 700; }
.mast .addr { font-size: 9.5pt; opacity: .82; }
.mast .row { display: flex; justify-content: space-between; align-items: flex-start; }
.mast .row > div:first-child { flex: 1 1 auto; min-width: 0; padding-right: 14px; }
.mast .right { text-align: right; flex: 0 0 auto; white-space: nowrap; }
.mast .period { font-size: 13pt; font-weight: 700; }
.mast .meta { font-size: 8pt; opacity: .8; margin-top: 2px; }
.flag { display: inline-block; font-size: 8pt; font-weight: 700; padding: 2px 9px; border-radius: 10px;
        margin-top: 6px; color: #fff; }
h2 { font-size: 12.5pt; color: #12263F; margin: 0 0 6px; padding-bottom: 3px; border-bottom: 1.5px solid #12263F;
     page-break-after: avoid; }
h3 { font-size: 9.5pt; margin: 10px 0 3px; color: #12263F; page-break-after: avoid; }
h4 { font-size: 8pt; letter-spacing: 1.2px; text-transform: uppercase; color: #5b6676; margin: 0 0 4px; }
section { margin-top: 8px; }
section.pg { page-break-before: always; margin-top: 0; }
.keep { page-break-inside: avoid; }
p { margin: 0 0 6px; }
p.lead { font-size: 10.4pt; line-height: 1.5; margin-bottom: 7px; }
.kpis { display: flex; gap: 8px; margin: 2px 0 8px; }
.kpis > div { flex: 1; border: 1px solid #d8dee8; border-radius: 6px; padding: 7px 9px; }
.kpis b { display: block; font-size: 17pt; line-height: 1.1; color: #12263F; }
.kpis .lbl { font-size: 7.5pt; color: #5b6676; display: block; margin-top: 2px; }
.kpis b i { font-style: normal; font-size: 10pt; color: #5b6676; font-weight: 400; }
.kpis small { font-size: 7.5pt; color: #067647; font-weight: 700; }
.kpis small.dn { color: #B54708; }
.two { display: flex; gap: 16px; }
.two ul.tight { font-size: 8.9pt; }
.two > div { flex: 1; min-width: 0; }
ul.tight { margin: 0; padding: 0; list-style: none; }
ul.tight li { margin: 0 0 4px; padding-left: 11px; position: relative; }
ul.tight li:before { content: ""; position: absolute; left: 0; top: 6px; width: 5px; height: 5px;
                     border-radius: 50%; background: #12263F; }
ul.risk li:before { background: var(--c, #12263F); }
sup.tag { font-size: 6.2pt; font-weight: 700; color: #5b6676; border: .6px solid #c4ccd8; border-radius: 3px;
          padding: 0 2px; margin-left: 3px; vertical-align: super; line-height: 1; }
.card { border: 1px solid #d8dee8; border-radius: 6px; padding: 7px 10px; flex: 1; }
.card h4 { margin-bottom: 3px; }
.card.na { background: #f6f8fb; border-style: dashed; }
.card .big { font-weight: 700; color: #12263F; }
.muted { color: #5b6676; font-size: 8pt; }
.none { color: #5b6676; font-style: italic; }
table { border-collapse: collapse; width: 100%; margin: 4px 0 8px; }
th { text-align: left; font-size: 7.5pt; letter-spacing: .6px; text-transform: uppercase; color: #5b6676;
     border-bottom: 1px solid #12263F; padding: 3px 5px; font-weight: 700; }
td { padding: 4px 5px; border-bottom: 1px solid #e3e7ee; vertical-align: top; }
td.n, th.n { text-align: right; white-space: nowrap; }
tr { page-break-inside: avoid; }
table.wf { table-layout: fixed; }
table.wf th:nth-child(1) { width: 27%; } table.wf th:nth-child(2) { width: 13%; } table.wf th:nth-child(3) { width: 14%; }
table.wf th:nth-child(4) { width: 12%; } table.wf th:nth-child(5) { width: 9%; } table.wf th:nth-child(6) { width: 9%; }
table.wf th:nth-child(7) { width: 9%; } table.wf th:nth-child(8) { width: 7%; }
table.wf th { letter-spacing: .2px; }
table.wf td, table.wf th { overflow-wrap: break-word; word-wrap: break-word; }
table.wf th.n, table.wf td.n { white-space: normal; }
table.ev td { padding: 2px 5px; font-size: 8pt; }
table.ev td:nth-child(1) { width: 5%; } table.ev td:nth-child(2) { width: 27%; }
.chip { display: inline-block; font-size: 7pt; font-weight: 700; padding: 1px 6px; border-radius: 8px;
        color: #fff; background: #5b6676; vertical-align: 1px; }
.chip.new { background: #067647; } .chip.adv { background: #1F6FEB; } .chip.warn { background: #B54708; }
.chip.crit { background: #B42318; } .chip.soft { background: #e8edf5; color: #12263F; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 5px; }
.sub { border-top: 1px solid #e3e7ee; padding: 4px 0; page-break-inside: avoid; }
.sub .name { font-weight: 700; }
.sub .meta { color: #5b6676; font-size: 8pt; }
.sub ul { margin: 3px 0 0 14px; padding: 0; }
table.gantt { table-layout: fixed; }
table.gantt td { border: 0; border-top: 1px solid #e3e7ee; padding: 5px 0; vertical-align: middle; }
table.gantt tr:first-child td { border-top: 0; padding: 0; }
table.gantt tr { page-break-inside: avoid; }
table.gantt td.who { width: 34%; padding-right: 10px; }
table.gantt td.bar { width: 410px; }
table.gantt td.n { width: 7%; text-align: right; color: #5b6676; font-size: 8pt; white-space: nowrap; }
table.gantt .name { font-weight: 700; }
table.gantt .meta { color: #5b6676; font-size: 8pt; }
table.gantt .what { font-size: 8pt; color: #5b6676; }
table.floors { width: auto; }
table.floors td, table.floors th { width: 26px; min-width: 26px; }
table.floors td.name { width: auto; min-width: 150px; }
table.floors td { text-align: center; padding: 2px 0; font-size: 7pt; border: 1px solid #fff; height: 16px; }
table.floors th { text-align: center; padding: 2px 0; font-size: 7pt; }
table.floors td.name { text-align: left; white-space: nowrap; padding-right: 8px; font-size: 8pt; border: 0;
                       border-bottom: 1px solid #e3e7ee; }
.photos { font-size: 0; }
.strip-row { margin-top: 10px; }
.strip-row h4 { margin: 0 0 4px; font-size: 9.5pt; page-break-after: avoid; }
.photo { display: inline-block; vertical-align: top; width: 24%; margin: 0 1% 6px 0; page-break-inside: avoid; font-size: 9pt; }
.photo .frame { height: 1.9in; background: #eef1f5; border-radius: 3px; display: flex; align-items: center; justify-content: center; }
.photo img { max-width: 100%; max-height: 100%; width: auto; height: auto; object-fit: contain; display: block; }
.photo .cap { font-size: 8pt; margin-top: 3px; }
.photo .cap b { font-size: 8.5pt; }
.strip { border-radius: 5px; padding: 5px 9px; font-size: 8.3pt; margin: 4px 0 8px; background: #eef3fa; }
.strip.warn { background: #fdf3e3; }
.legend { font-size: 7.5pt; color: #5b6676; margin-top: 6px; }
.chart { display: block; margin: 4px 0; }
.foot { font-size: 7.5pt; color: #5b6676; margin-top: 10px; }
table.board { table-layout: fixed; }
table.board th { text-align: center; padding: 2px 1px; font-size: 7pt; border-bottom: 1px solid #12263F; }
table.board th.work { text-align: left; width: 30%; }
table.board th.est, table.board td.est { width: 17%; text-align: left; }
table.board th.trend, table.board td.trend { width: 12%; }
table.board td { padding: 2px 1px; border-bottom: 1px solid #fff; vertical-align: middle; page-break-inside: avoid; }
table.board td.work { font-size: 8.3pt; padding-right: 6px; border-bottom: 1px solid #e3e7ee; }
table.board td.work .who { display: block; font-size: 7.3pt; color: #5b6676; }
table.board td.cell { text-align: center; font-size: 6.6pt; font-weight: 700; border-left: 1.5px solid #fff; }
td.st-done { background: #12263F; color: #fff; }
td.st-active { background: #2A7F8E; color: #fff; }
td.st-started { background: #cfe0ef; color: #12263F; }
td.st-none { background: #f3f5f8; color: #9aa4b2; font-weight: 400; }
td.est .bar { height: 7px; background: #e3e7ee; border-radius: 3px; margin-top: 2px; }
td.est .bar i { display: block; height: 7px; background: #2A7F8E; border-radius: 3px; }
td.est b { font-size: 9pt; color: #12263F; }
.card .prow { font-size: 8.2pt; margin: 1px 0; display: flex; align-items: center; gap: 6px; }
.card .prow span { flex: 1 1 auto; min-width: 0; }
.card .prow .bar { flex: 0 0 52px; height: 5px; background: #e3e7ee; border-radius: 3px; }
.card .prow .bar i { display: block; height: 5px; background: #2A7F8E; border-radius: 3px; }
table.est { table-layout: fixed; }
table.est th.work { width: 36%; text-align: left; } table.est th.est { width: 20%; text-align: left; }
table.est th.trend { width: 14%; text-align: left; } table.est th.else { text-align: left; }
table.est td { vertical-align: middle; padding: 3px 5px; }
table.est td.work { font-size: 8.3pt; } table.est td.work .who { display: block; font-size: 7.3pt; color: #5b6676; }
table.est td.else { font-size: 8pt; color: #5b6676; }
.bandhead { page-break-after: avoid; font-size: 7.5pt; color: #5b6676; letter-spacing: .6px; text-transform: uppercase;
            margin: 8px 0 1px; font-weight: 700; }
table.band { table-layout: fixed; margin: 0 0 6px; page-break-inside: avoid; }
table.band th { text-align: center; padding: 2px 0; font-size: 6.6pt; letter-spacing: 0; border-bottom: 1px solid #12263F; }
table.band th.work { text-align: left; padding-left: 5px; }
table.band td { padding: 2px 0; border-bottom: 1px solid #fff; vertical-align: middle; }
table.band td.work { font-size: 7.6pt; padding: 2px 6px 2px 5px; border-bottom: 1px solid #e3e7ee; overflow-wrap: break-word;
                     word-wrap: break-word; }
table.band td.cell { text-align: center; font-size: 6.6pt; font-weight: 700; border-left: 1.5px solid #fff; }
table.band td.pad { background: none; }
table.byfloor { table-layout: fixed; }
table.byfloor th, table.byfloor td { padding: 3px 2px; }
table.byfloor th.n, table.byfloor td.n { white-space: normal; font-size: 8pt; }
ul.plain { margin: 0 0 6px; padding-left: 14px; font-size: 8.9pt; }
ul.plain li { margin: 0 0 3px; }
.photos { page-break-inside: avoid; }
.floorhead { page-break-after: avoid; font-size: 7.5pt; color: #5b6676; letter-spacing: .6px; text-transform: uppercase; margin: 2px 0 2px; }
"""


#: Record numbers of the report being rendered (summonses, permits): they print
#: as filed, never as a scrubbed phone number. Set by render_html.
_KEEP: frozenset = frozenset()


def _record_numbers(reps: List[Dict[str, Any]]) -> frozenset:
    out = set()
    for rep in reps:
        reg = rep.get("regulatory") or {}
        for lst in ("swo_active", "open", "swo_lifted", "issued", "changed", "expiring"):
            for r in reg.get(lst) or []:
                out.add(str(r.get("number") or ""))
                out.update(str(m) for m in r.get("members") or [])
    out.discard("")
    return frozenset(out)


def _host(link: str) -> str:
    return urlsplit(str(link)).netloc or str(link)


def _e(v: Any) -> str:
    return html.escape(base.no_phone(v, _KEEP))


def _tag(src: str, ref: str = "") -> str:
    return f"<sup class='tag'>{html.escape(src)}{html.escape(ref)}</sup>"


def _src_tag(item: Dict[str, Any], refs: Dict[str, str]) -> str:
    """The source tag of a change or risk: its kind, and for DOB/DOT records
    the evidence ids (R1, R3) so a reader can find the record."""
    ids = [refs[r] for r in item.get("refs") or [] if r in refs]
    return _tag(item["src"], "") if not ids else _tag(",".join(ids), "")


def _ref_map(rep: Dict[str, Any]) -> Dict[str, str]:
    return {e["record"]: e["id"] for e in rep["evidence"] if e["kind"] == "regulatory"}


def _hex_to_rgba(h: str, a: float) -> str:
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


def _delta_chip(cur: float, prev: float, days: int) -> str:
    if not days or not prev:
        return ""
    d = cur - prev
    if abs(d) < 0.05:
        return "<small>unchanged</small>"
    return (f"<small class='{'dn' if d < 0 else ''}'>{'▲' if d > 0 else '▼'} {abs(d):g} vs previous "
            f"({prev:g})</small>")


def workforce_svg(rep: Dict[str, Any], width: int = 700, height: int = 190, compact: bool = False) -> str:
    """Workers on site: one bar per day / week / month (the average on the
    days worked), the previous period as hollow markers on the same position,
    gridlines at round numbers, bar values labelled when there is room."""
    cur, prev, grain = rep["site"]["series"], rep["site"]["prev_series"], rep["grain"]
    if not cur or not any(b["days"] for b in cur):
        return ""
    top = max([b["avg"] for b in cur] + [b["avg"] for b in prev] + [1])
    step = 5 if top <= 30 else 10 if top <= 80 else 25
    ymax = (int(top // step) + 1) * step
    left, right, base_y, plot_h = 34, 8, height - 22, height - 40
    n = len(cur)
    slot = (width - left - right) / n
    bw = max(4.0, min(slot * 0.62, 34.0))
    out = [f'<svg class="chart" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" font-family="Helvetica, Arial, sans-serif">']
    for v in range(0, ymax + 1, step):
        y = base_y - plot_h * v / ymax
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e3e7ee"/>')
        out.append(f'<text x="{left - 5}" y="{y + 3:.1f}" font-size="8" text-anchor="end" fill="#5b6676">{v}</text>')
    for i, b in enumerate(cur):
        cx = left + slot * (i + 0.5)
        if b["days"]:
            h = plot_h * b["avg"] / ymax
            out.append(f'<rect x="{cx - bw / 2:.1f}" y="{base_y - h:.1f}" width="{bw:.1f}" height="{h:.1f}" '
                       f'rx="1.5" fill="{NAVY}"/>')
            if n <= 16 and not (compact and n > 12):
                # above the bar AND above the previous period's marker when the two
                # are close (the marker was drawn through the number)
                top_y = base_y - h
                if i < len(prev) and prev[i]["days"]:
                    mark_y = base_y - plot_h * prev[i]["avg"] / ymax - 1.2
                    if -11 < mark_y - top_y < 3:
                        top_y = min(top_y, mark_y)
                out.append(f'<text x="{cx:.1f}" y="{max(8.0, top_y - 3):.1f}" font-size="8" text-anchor="middle" '
                           f'fill="#1c2430">{b["avg"]:g}</text>')
        if i < len(prev) and prev[i]["days"]:
            py = base_y - plot_h * prev[i]["avg"] / ymax
            out.append(f'<rect x="{cx - bw / 2 - 1:.1f}" y="{py - 1.2:.1f}" width="{bw + 2:.1f}" height="2.4" '
                       f'fill="#E8710A"/>')
        lab = (_fmt(b["start"], "%-m/%-d") if grain == "day" else _fmt(b["start"], "%b %-d") if grain == "week"
               else _fmt(b["start"], "%b"))
        if n <= 16 or i % max(1, n // 12) == 0:
            out.append(f'<text x="{cx:.1f}" y="{base_y + 12}" font-size="7.5" text-anchor="middle" '
                       f'fill="#5b6676">{lab}</text>')
    out.append(f'<line x1="{left}" y1="{base_y}" x2="{width - right}" y2="{base_y}" stroke="#9aa5b4"/>')
    out.append("</svg>")
    unit = {"day": "per working day", "week": "weekly average", "month": "monthly average"}[grain]
    legend = (f"<div class='legend'><span class='dot' style='background:{NAVY}'></span>Workers on site, {unit}"
              + ("&nbsp;&nbsp;<span class='dot' style='background:#E8710A;height:3px;vertical-align:3px'></span>"
                 "Same position in the previous period" if any(b["days"] for b in prev) else "") + "</div>")
    return "".join(out) + legend


# ── PAGE 1 ───────────────────────────────────────────────────────────────────

def _mast(rep: Dict[str, Any]) -> str:
    st = rep["status"]
    kind = {"daily": "Daily", "weekly": "Weekly", "biweekly": "Bi-weekly", "monthly": "Monthly",
            "quarterly": "Quarterly"}.get(rep["kind"], "Custom period")
    return (f"<div class='mast'><div class='brand'>LEVELOG · CONSTRUCTION PROGRESS REPORT</div>"
            f"<div class='row'><div><h1>{_e(rep['job'])}</h1><div class='addr'>{_e(rep['address'])}"
            f"{' · ' + _e(rep['gc']) if rep['gc'] else ''}</div></div>"
            f"<div class='right'><div class='period'>{_e(rep['period'])}</div>"
            f"<div class='meta'>{kind} · prepared {_e(_fmt(rep['generated'].astimezone(P.NY), '%b %-d, %Y'))}</div>"
            + (f"<div class='meta'>Period in progress · records through {_e(_fmt(rep['through'], '%b %-d'))}</div>"
               if rep.get("in_progress") and rep.get("through") else "") +
            f"<span class='flag' style='background:{LEVEL_COLOR[st['level']]}'>{_e(st['label'])}</span></div>"
            f"</div></div>")


def _kpis(rep: Dict[str, Any]) -> str:
    site, prev = rep["site"], rep["prev"]
    subs = rep["subs"]
    tiles = []
    if site["worked"]:
        tiles = [
            (f"{site['worked']}<i> / {site['possible']}</i>",
             "Working days with site activity", ""),
            (f"{site['avg']:g}", "Average workers on site per day", _delta_chip(site["avg"], prev["avg"], prev["days"])),
            (f"{site['peak']}", f"Peak workforce · {_day(site['peak_day'])}", ""),
            (f"{len(subs)}", "Subcontractors on site",
             (f"<small>{len(rep['mobilization']['new'])} new</small>" if rep["mobilization"]["new"] else "")),
        ]
    if not tiles:
        return ""
    return "<div class='kpis'>" + "".join(f"<div><b>{v}</b><span class='lbl'>{_e(lbl)}</span>{extra}</div>"
                                          for v, lbl, extra in tiles) + "</div>"


def _day(d: Optional[date]) -> str:
    return _fmt(d, "%b %-d") if d else ""


def _changes_block(rep: Dict[str, Any]) -> str:
    ch, refs = rep["changes"], _ref_map(rep)
    body = ("<ul class='tight'>" + "".join(f"<li>{_e(c['text'])}{_src_tag(c, refs)}</li>" for c in ch) + "</ul>") \
        if ch else ("<p class='none'>No material change from the previous period."
                    if rep["prev"]["days"] else
                    "<p class='none'>No previous period on record to compare against.") + "</p>"
    return f"<div><h4>Changes since the previous period</h4>{body}</div>"


def _risks_block(rep: Dict[str, Any]) -> str:
    rk, refs = rep["risks"], _ref_map(rep)
    cov = rep["regulatory"]["coverage"]
    if rk:
        body = "<ul class='tight risk'>" + "".join(
            f"<li style='--c:{LEVEL_COLOR[r['level']]}'><b style='color:{LEVEL_COLOR[r['level']]}'>"
            f"{r['level'].upper() if r['level'] != 'watch' else 'WATCH'}</b> {_e(r['text'])}{_src_tag(r, refs)}</li>"
            for r in rk) + "</ul>"
    elif cov["state"] in ("verified", "partial"):
        body = "<p class='none'>No material risks flagged from the records.</p>"
    else:
        body = ("<p class='none'>No risks flagged from site records; regulatory records could not be verified "
                "for this period.</p>")
    return f"<div><h4>Risks and watch items</h4>{body}</div>"


def _est_words(n: Optional[int]) -> str:
    return f"about {n}%" if n is not None else "—"


def _progress_card(rep: Dict[str, Any]) -> str:
    """Page 1: the kinds of work of this period and their estimate, with the
    word ESTIMATED on it. Nothing when the logs name no work."""
    board = rep.get("progress") or {}
    trades = board.get("trades") or {}
    keys = [k for k in (board.get("worked_in_period") or list(trades)) if trades[k].get("estimate") is not None][:4]
    if not keys:
        return ""
    rows = "".join(f"<div class='prow'><span>{_e(trades[k]['label'])} — <b>{_est_words(trades[k]['estimate'])}</b></span>"
                   f"<div class='bar'><i style='width:{trades[k]['estimate']}%'></i></div></div>" for k in keys)
    return (f"<div class='card'><h4>Progress (estimated) {_tag('L')}</h4>{rows}"
            "<div class='muted'>Estimated from the filed daily logs; see the progress page.</div></div>")


def _schedule_card(rep: Dict[str, Any]) -> str:
    plan = rep["schedule"]
    if not (plan and plan.get("usable")):
        return ""
    proj, ms, c = plan["project"], plan["milestones"], plan["counts"]
    lines = [f"<span class='big'>{c['complete']} of {c['activities']}</span> activities complete "
             "<span class='muted'>(count, not a percent)</span>"]
    if proj.get("reported_percent") is not None:
        lines.insert(0, f"<span class='big'>{proj['reported_percent']:g}% complete</span> "
                        "<span class='muted'>as reported in the schedule file</span>")
    if ms["overdue"]:
        lines.append(f"<b style='color:#C2410C'>{len(ms['overdue'])} milestone"
                     f"{'s' if len(ms['overdue']) != 1 else ''} past due</b>")
    if proj.get("forecast_finish") and proj.get("baseline_finish"):
        v = proj.get("variance_days")
        lines.append(f"Finish {_e(_fmt(proj['forecast_finish'], '%b %-d, %Y'))} vs original "
                     f"{_e(_fmt(proj['baseline_finish'], '%b %-d, %Y'))}"
                     + (f" ({'+' if v > 0 else ''}{v} days)" if v is not None else ""))
    asof = f"Per schedule data date {_e(_fmt(plan['as_of'], '%b %-d, %Y'))}" if plan.get("as_of") else "Per imported schedule"
    if P.schedule_date_words(plan):
        asof += f" — {_e(P.schedule_date_words(plan))}"
    return (f"<div class='card'><h4>Schedule {_tag('S')}</h4>" + "<br>".join(lines)
            + f"<div class='muted'>{asof}</div></div>")


def _coming_block(rep: Dict[str, Any]) -> str:
    up = rep["upcoming"][:5]
    if not up:
        return ""
    return ("<div><h4>Coming up (next 30 days)</h4><ul class='tight'>"
            + "".join(f"<li><b>{_e(_fmt(u['date'], '%a %b %-d'))}</b> — {_e(u['what'])}{_tag(u['src'])}</li>"
                      for u in up) + "</ul></div>")


_LABELS = ("Reported work", "Regulatory", "Schedule", "Progress")


def _lead(text: str) -> str:
    """"Regulatory — ..." with its lead-in in bold."""
    for lab in _LABELS:
        if text.startswith(lab + " — "):
            return f"<b>{lab}</b> — {_e(text[len(lab) + 3:])}"
    return _e(text)


def _overview(rep: Dict[str, Any]) -> str:
    paras = "".join(f"<p class='lead'>{_lead(p)}</p>" for p in rep["overview"][:1])
    rest = "".join(f"<p>{_lead(p)}</p>" for p in rep["overview"][1:])
    chart = workforce_svg(rep, width=700, height=104, compact=True)
    chart_html = ("<h4 style='margin-top:6px'>Workers on site</h4>" + chart) if chart else ""
    return f"<section class='first'><h2>Overview</h2>{paras}{rest}{chart_html}</section>"


# ── LATER SECTIONS ───────────────────────────────────────────────────────────

#: The schedule chart is for a report over a span of work, not a day or two.
GANTT_MIN_DAYS = 7
_GANTT_WIDTH = 400


def _work_words(work: Optional[Dict[str, Any]]) -> str:
    """One line: what a sub reported, then the floors it was on."""
    items = (work or {}).get("items") or []
    if not items:
        return "No work description in the daily logs."
    # Floors follow only the work they belong to: "Ductwork rough · floors 1–4
    # · roof MEP", never a roof item in front of a floor range.
    on_floors = [i for i in items if i["floors"]]
    elsewhere = [i for i in items if not i["floors"]]

    def joined(rows: List[Dict[str, Any]]) -> str:
        return ", ".join(P.lc_first(i["work"]) for i in rows)
    parts = []
    if on_floors:
        parts += [joined(on_floors), P.floors_label({f for i in on_floors for f in i["floors"]})]
    if elsewhere:
        parts.append(joined(elsewhere))
    text = " · ".join(parts)
    amended = " (amended log)" if any(i["amended"] for i in items) else ""
    return text[:1].upper() + text[1:] + amended


def _gantt_bars(days: List[date]) -> List[List[date]]:
    """[[first, last], ...]: a run of worked days is one bar. A weekend between
    two worked days does not break it; a working day with nobody there does."""
    bars: List[List[date]] = []
    for d in sorted(days):
        if bars:
            gap = [date.fromordinal(n) for n in range(bars[-1][1].toordinal() + 1, d.toordinal())]
            if all(x.weekday() >= 5 for x in gap):
                bars[-1][1] = d
                continue
        bars.append([d, d])
    return bars


def _gantt_ticks(start: date, end: date) -> List[date]:
    """Where the axis is labelled: each Monday, or each month's first for a long report."""
    days = [date.fromordinal(n) for n in range(start.toordinal(), end.toordinal() + 1)]
    if len(days) > 120:
        return [d for d in days if d.day == 1]
    return [d for d in days if d.weekday() == 0]


def _gantt_row(s: Dict[str, Any], start: date, end: date, photo_days: set, ticks: List[date]) -> str:
    n = (end - start).days + 1
    width, height = _GANTT_WIDTH, 18
    slot = width / n
    x = lambda d: (d - start).days * slot
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">']
    out += [f'<line x1="{x(t):.1f}" y1="0" x2="{x(t):.1f}" y2="{height}" stroke="{LINE}"/>' for t in ticks]
    for first, last in _gantt_bars([d for d in s["days"] if start <= d <= end]):
        out.append(f'<rect x="{x(first) + 0.5:.1f}" y="4" width="{max(2.0, ((last - first).days + 1) * slot - 1):.1f}" '
                   f'height="10" rx="2" fill="{s["color"]}"/>')
    for d in sorted(photo_days):
        out.append(f'<circle cx="{x(d) + slot / 2:.1f}" cy="9" r="2.6" fill="#fff" stroke="{NAVY}" stroke-width="1"/>')
    out.append("</svg>")
    return "".join(out)


def _gantt_axis(start: date, end: date, ticks: List[date]) -> str:
    n = (end - start).days + 1
    width = _GANTT_WIDTH
    slot = width / n
    fmt = "%b" if n > 120 else "%b %-d"
    # The period's first day is named too, unless a tick is about to be.
    shown = ([start] if not ticks or (ticks[0] - start).days * slot >= 40 else []) + ticks
    labels = "".join(f'<text x="{(t - start).days * slot:.1f}" y="10" font-size="8" fill="{MUTED}">{_e(_fmt(t, fmt))}</text>'
                     for t in shown)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 14" width="{width}" height="14" '
            f'font-family="Helvetica, Arial, sans-serif">{labels}</svg>')


def _progress(rep: Dict[str, Any], images: Optional[Dict[str, str]] = None) -> str:
    """One line per sub: who, what they reported, and -- on a report over a
    span of work -- WHEN, as a bar across the period. The bars are days on
    site (check-ins and filed logs); nothing here is a percent complete."""
    if not rep["subs"]:
        return ""
    by = {w["key"]: w for w in rep["work"]}
    start, end = rep["start"], rep["end"]
    if (end - start).days + 1 < GANTT_MIN_DAYS:
        rows = "".join(
            f"<div class='sub'><span class='name'>{_e(s['name'])}</span>"
            + (f" <span class='meta'>{_e(s['trade'])}</span>" if s["trade"] else "")
            + f"<div>{_e(_work_words(by.get(s['key'])))}</div></div>" for s in rep["subs"])
        return ("<section><h2>Reported work</h2><p class='muted'>What each subcontractor reported in the filed daily "
                f"logs. Not measured completion.</p>{rows}</section>")
    photo_days: Dict[str, set] = {}
    for p in rep.get("photos") or []:
        if (images or {}).get(p["key"]):
            day = base._d(p["date"])
            if day:
                photo_days.setdefault(P.company_key(p["sub"]) or p["sub"], set()).add(day)
    ticks = _gantt_ticks(start, end)
    rows = []
    for s in sorted(rep["subs"], key=lambda s: (s["first"], -len(s["days"]), s["name"])):
        trade = f" <span class='meta'>{_e(s['trade'])}</span>" if s["trade"] else ""
        count = len(s["days"])
        rows.append(f"<tr><td class='who'><span class='name'>{_e(s['name'])}</span>{trade}"
                    f"<div class='what'>{_e(_work_words(by.get(s['key'])))}</div></td>"
                    f"<td class='bar'>{_gantt_row(s, start, end, photo_days.get(s['key'], set()), ticks)}</td>"
                    f"<td class='n'>{count}&nbsp;{'day' if count == 1 else 'days'}</td></tr>")
    legend = ("<div class='legend'>A coloured bar: days on site, in the subcontractor's colour. A weekend between two "
              "worked days does not break the bar; a working day with nobody there does."
              + ("&nbsp;&nbsp;<svg width='8' height='8' viewBox='0 0 8 8'><circle cx='4' cy='4' r='3' fill='#fff' "
                 f"stroke='{NAVY}'/></svg> Photo in this report" if photo_days else "") + "</div>")
    return (f"<section class='pg'><h2>Crews on site, day by day {_tag('G')}{_tag('L')}</h2>"
            "<p class='muted'>Who worked when, and what they reported, from site check-ins and filed daily logs. "
            "A bar is days on site, not measured completion.</p>"
            f"<table class='gantt'><tr><td class='who'></td><td class='bar'>{_gantt_axis(start, end, ticks)}</td><td class='n'></td></tr>"
            f"{''.join(rows)}</table>{legend}</section>")


_STAGE_CLS = {ST.DONE: "st-done", ST.ACTIVE: "st-active", ST.STARTED: "st-started", ST.NONE: "st-none"}
_STAGE_SHORT = {ST.DONE: "Done", ST.ACTIVE: "Active", ST.STARTED: "Started", ST.NONE: "–"}


def _trend_svg(points: List[Optional[int]], width: int = 64, height: int = 16) -> str:
    """The estimate week by week, as a small line from 0 to 100."""
    pts = [(i, v) for i, v in enumerate(points) if v is not None]
    if len(pts) < 2:
        return ""
    n = max(len(points) - 1, 1)
    xy = " ".join(f"{1 + i * (width - 2) / n:.1f},{height - 1 - v * (height - 2) / 100:.1f}" for i, v in pts)
    lx, ly = xy.split(" ")[-1].split(",")
    return (f"<svg class='chart' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>"
            f"<line x1='0' y1='{height - 1}' x2='{width}' y2='{height - 1}' stroke='{LINE}' stroke-width='1'/>"
            f"<polyline points='{xy}' fill='none' stroke='#2A7F8E' stroke-width='1.4'/>"
            f"<circle cx='{lx}' cy='{ly}' r='1.8' fill='#2A7F8E'/></svg>")


#: The board prints as ONE table (stage words in the cells) while it has at most
#: this many floor columns; a taller building is printed in bands of floors.
#: MEASURED 2026-11-22: at 9 columns the words "Started" / "Active" ran over
#: their cells, and at 42 floors every cell overprinted its neighbours (a
#: fixed-layout table shares 41% of the page between all floor columns).
BOARD_ONE_TABLE_MAX = 7
#: A band of floors holds at most this many columns with the stage as a WORD,
#: or this many with the stage as a LETTER (D / A / S).
BAND_WORDS_MAX = 10
BAND_LETTERS_MAX = 30
_STAGE_LETTER = {ST.DONE: "D", ST.ACTIVE: "A", ST.STARTED: "S", ST.NONE: "·"}
_PAD_CELL = "<td class='pad'></td>"


def board_bands(floors: List[Any]) -> List[List[Any]]:
    """The floors of the board, in bands that each fit the page: one band up
    to BAND_LETTERS_MAX floors, otherwise the fewest bands, of equal length
    (42 floors -> 21 + 21, 60 -> 30 + 30, 61 -> 21 + 20 + 20)."""
    floors = list(floors)
    if not floors:
        return []
    n = -(-len(floors) // BAND_LETTERS_MAX)
    per = -(-len(floors) // n)
    return [floors[i:i + per] for i in range(0, len(floors), per)]


def _board_legend(letters: bool = False) -> str:
    items = (("#12263F", "D", "Done — appears complete"), ("#2A7F8E", "A", "Active — worked in the last 7 days"),
             ("#cfe0ef", "S", "Started — worked earlier"), ("#f3f5f8", "·", "Not reported on that floor"))
    return ("<div class='legend'>" + "&nbsp;&nbsp;".join(
        f"<span class='dot' style='background:{c}'></span>{('<b>' + k + '</b> ') if letters else ''}{_e(lbl)}"
        for c, k, lbl in items) + "</div>")


def _est_cell(t: Dict[str, Any]) -> str:
    est = t.get("estimate")
    return (f"<b>{_est_words(est)}</b><div class='bar'><i style='width:{est}%'></i></div>" if est is not None
            else "<span class='muted'>not tied to a floor</span>")


def _board_one_table(trades: Dict[str, Any], order: List[str], floors: List[Any], hist: List[Dict[str, Any]],
                     other: bool) -> str:
    head = ("<tr><th class='work'>Kind of work</th>" + "".join(f"<th>Fl {f}</th>" for f in floors)
            + ("<th>Other</th>" if other else "") + "<th class='est'>Estimate</th>"
            + ("<th class='trend'>Week by week</th>" if len(hist) > 1 else "") + "</tr>")
    rows = []
    for k in order:
        t = trades[k]
        cells = "".join(f"<td class='cell {_STAGE_CLS[t['cells'][f]['stage']]}'>{_STAGE_SHORT[t['cells'][f]['stage']]}</td>"
                        for f in floors)
        if other:
            ew = t.get("elsewhere")
            cells += (f"<td class='cell {_STAGE_CLS[ew['stage']]}'>{_STAGE_SHORT[ew['stage']]}</td>" if ew
                      else "<td class='cell st-none'>–</td>")
        trend = (f"<td class='trend'>{_trend_svg([h['estimates'].get(k) for h in hist])}</td>" if len(hist) > 1 else "")
        who = f"<span class='who'>{_e(', '.join(t['companies']))}</span>" if t.get("companies") else ""
        rows.append(f"<tr><td class='work'>{_e(t['label'])}{who}</td>{cells}<td class='est'>{_est_cell(t)}</td>{trend}</tr>")
    return f"<table class='board'>{head}{''.join(rows)}</table>{_board_legend()}"


def _board_banded(trades: Dict[str, Any], order: List[str], floors: List[Any], hist: List[Dict[str, Any]]) -> str:
    """A building of many floors: the estimate of each kind of work in one
    table, then the floors in bands that fit the page, the same kinds of work
    in the same order in every band. No cell is ever narrower than its text."""
    trend_col = len(hist) > 1
    other = any(trades[k].get("elsewhere") for k in order)
    erows = []
    for k in order:
        t = trades[k]
        who = f"<span class='who'>{_e(', '.join(t['companies']))}</span>" if t.get("companies") else ""
        ew = t.get("elsewhere")
        ew_html = ""
        if other:
            words = (ST.STAGE_LABEL[ew["stage"]] + " at " + (" and ".join(ew.get("places") or [])
                                                              or "areas not tied to a floor")) if ew else "—"
            ew_html = f"<td class='else'>{_e(words)}</td>"
        trend = (f"<td class='trend'>{_trend_svg([h['estimates'].get(k) for h in hist])}</td>" if trend_col else "")
        erows.append(f"<tr><td class='work'>{_e(t['label'])}{who}</td><td class='est'>{_est_cell(t)}</td>{trend}{ew_html}</tr>")
    est_table = ("<table class='board est'><tr><th class='work'>Kind of work</th><th class='est'>Estimate</th>"
                 + ("<th class='trend'>Week by week</th>" if trend_col else "")
                 + ("<th class='else'>Not tied to a floor</th>" if other else "") + f"</tr>{''.join(erows)}</table>")
    on_floors = [k for k in order if any(c["stage"] != ST.NONE for c in trades[k]["cells"].values())]
    bands = board_bands(floors)
    if not on_floors or not bands:
        return est_table
    per = max(len(b) for b in bands)
    letters = per > BAND_WORDS_MAX
    short = _STAGE_LETTER if letters else _STAGE_SHORT
    work_w = 24.0
    col_w = (100.0 - work_w) / per
    cols = f"<col style='width:{work_w:g}%'>" + f"<col style='width:{col_w:.3f}%'>" * per
    out = []
    for band in bands:
        pad = per - len(band)
        head = "<tr><th class='work'>Floor</th>" + "".join(f"<th>{f}</th>" for f in band) + "<th></th>" * pad + "</tr>"
        rows = []
        for k in on_floors:
            t = trades[k]
            cells = "".join(f"<td class='cell {_STAGE_CLS[t['cells'][f]['stage']]}'>{short[t['cells'][f]['stage']]}</td>"
                            for f in band)
            rows.append(f"<tr><td class='work'>{_e(t['label'])}</td>{cells}{_PAD_CELL * pad}</tr>")
        label = f"Floors {band[0]}–{band[-1]}" if len(band) > 1 else f"Floor {band[0]}"
        out.append(f"<div class='keep'><div class='bandhead'>{label}</div>"
                   f"<table class='board band'><colgroup>{cols}</colgroup>{head}{''.join(rows)}</table></div>")
    return est_table + "".join(out) + _board_legend(letters)


def _board_section(rep: Dict[str, Any]) -> str:
    """THE PROGRESS PAGE: in plain English, then the stage of each kind of
    work on each floor, its estimate and how the estimate has moved week by
    week. Everything here is read from the filed daily logs by the fixed rules
    of lib/progress_stages, and printed as an estimate.

    Up to BOARD_ONE_TABLE_MAX floor columns it is one table. Above that it is
    the estimate table and the floors in bands (`_board_banded`): the single
    table overprinted its own cells on any building taller than that."""
    board = rep.get("progress") or {}
    trades = board.get("trades") or {}
    if not trades:
        return ""
    floors = board.get("floors") or []
    order = list(board.get("worked_in_period") or []) + [k for k in trades if k not in (board.get("worked_in_period") or [])]
    hist = board.get("history") or []
    def _counts(t: Dict[str, Any]) -> str:
        w = ST.counts_words(t)
        return f" <span class='muted'>{_e(w[:1].upper() + w[1:])}.</span>" if w else ""
    plain = "".join(f"<li>{_e(ST.sentence(trades[k], floors))}{_counts(trades[k])}</li>" for k in order)
    other = any(trades[k].get("elsewhere") for k in order)
    if len(floors) + (1 if other else 0) <= BOARD_ONE_TABLE_MAX:
        table = _board_one_table(trades, order, floors, hist, other)
    else:
        table = _board_banded(trades, order, floors, hist)
    span = (f" Week by week: the estimate at the end of each of the last {len(hist)} weeks, read from the logs "
            "filed up to that day." if len(hist) > 1 else "")
    return (f"<section class='pg'><h2>Progress by trade and floor (estimated) {_tag('L')}</h2>"
            f"<p class='muted'>How far each kind of work has got on each floor, read from the filed daily logs "
            f"up to {_e(_fmt(rep.get('through') or rep['end'], '%b %-d, %Y'))}.{(' ' + _e(span)) if span else ''}</p>"
            f"<ul class='plain'>{plain}</ul>{table}"
            f"<div class='strip'><b>How the estimate is made.</b> {_e(ST.BASIS)} {_e(ST.floors_basis(board))}</div></section>")


def _schedule_section(rep: Dict[str, Any]) -> str:
    plan = rep["schedule"]
    if not (plan and plan.get("usable")):
        return ""
    ms, proj, c = plan["milestones"], plan["project"], plan["counts"]

    def mrow(m: Dict[str, Any], status: str, cls: str) -> str:
        fin = (base._d(m.get("actual_finish")) or base._d(m.get("current_finish")) or base._d(m.get("date"))
               or base._d(m.get("baseline_finish")))
        base_f = base._d(m.get("baseline_finish"))
        return (f"<tr><td>{_e(m.get('name'))}</td><td class='n'>{_e(_fmt(base_f, '%b %-d, %Y')) if base_f else '—'}</td>"
                f"<td class='n'>{_e(_fmt(fin, '%b %-d, %Y')) if fin else '—'}</td>"
                f"<td><span class='chip {cls}'>{status}</span></td></tr>")
    shown = (("completed_in_period", "COMPLETE", "new", 6, "completed in the period"), ("overdue", "PAST DUE", "crit", 6, "past due"),
             ("upcoming", "UPCOMING", "adv", 6, "upcoming"), ("unconfirmed", "NOT UPDATED", "soft", 4, "not updated"))
    rows = "".join(mrow(m, status, cls) for key, status, cls, most, _w in shown for m in ms[key][:most])
    cut = [f"{len(ms[key]) - most} more {words}" for key, _s, _c, most, words in shown if len(ms[key]) > most]
    mtable = ("<h3>Milestones</h3><table class='keep'><tr><th>Milestone</th><th class='n'>Original</th>"
              "<th class='n'>Current, or actual if complete</th><th>Status</th></tr>" + rows + "</table>"
              + (f"<div class='muted'>Not listed here: {_e(', '.join(cut))}. They are in the schedule file.</div>"
                 if cut else "")) if rows else ""
    dev = ""
    if plan["deviations"]:
        dev = ("<h3>Schedule changes shown in the file</h3><table class='keep'><tr><th>Activity</th><th class='n'>Original</th>"
               "<th class='n'>Current</th><th class='n'>Shift</th></tr>"
               + "".join(f"<tr><td>{_e(d['name'])}</td><td class='n'>{_e(_fmt(base._d(d['baseline']), '%b %-d'))}</td>"
                         f"<td class='n'>{_e(_fmt(base._d(d['current']), '%b %-d'))}</td>"
                         f"<td class='n'>{'+' if d['days'] > 0 else ''}{d['days']} d</td></tr>"
                         for d in plan["deviations"][:6]) + "</table>"
               "<div class='muted'>"
               + (f"The {min(6, len(plan['deviations']))} largest of {plan['deviations_total']} shifts in the file. "
                  if (plan.get("deviations_total") or 0) > 6 else "")
               + f"Finish or start dates {_SP.DEVIATION_MIN_DAYS} days or more later than the original; smaller shifts "
               "are in the milestone table and the schedule file. Dates as they appear in the schedule file; no cause is inferred.</div>")
    planned = ""
    if plan["scheduled_in_period"]:
        planned = ("<h3>Scheduled for this period vs. reported</h3><div class='two'><div><h4>Scheduled in the schedule</h4>"
                   "<ul class='tight'>" + "".join(f"<li>{_e(a['name'])} <span class='muted'>({_e(_fmt(base._d(a['start']), '%b %-d'))}"
                                                 f"–{_e(_fmt(base._d(a['finish']), '%b %-d'))})</span></li>"
                                                 for a in plan["scheduled_in_period"][:4])
                   + (f"<li class='muted'>and {(plan.get('scheduled_total') or len(plan['scheduled_in_period'])) - 4} more "
                      "scheduled in this period</li>"
                      if (plan.get("scheduled_total") or len(plan["scheduled_in_period"])) > 4 else "") + "</ul></div>"
                   "<div><h4>Reported in daily logs</h4><ul class='tight'>"
                   + "".join(f"<li>{_e(w['name'])}: {_e(w['items'][0]['work'])}</li>" for w in rep["work"] if w["items"])
                   + "</ul></div></div><div class='muted'>Shown side by side for comparison; the report draws no "
                   "conclusion from differences in wording.</div>")
    groups = ""
    if plan["groups"]:
        groups = ("<h3>By work package</h3><table class='keep'><tr><th>Package</th><th class='n'>Activities complete</th>"
                  "<th class='n'>Reported % complete</th></tr>"
                  + "".join(f"<tr><td>{_e(g['name'])}</td><td class='n'>{g['complete']} of {g['total']}</td>"
                            f"<td class='n'>{('%g%%' % g['percent']) if g['percent'] is not None else '—'}</td></tr>"
                            for g in plan["groups"][:10]) + "</table>")
    floors = ""
    if plan["floors"]:
        per = 14
        cols = "<col style='width:16%'>" + f"<col style='width:{84.0 / per:.3f}%'>" * per
        floors = "<h3>By floor (activities named for a floor)</h3>"
        for i in range(0, len(plan["floors"]), per):
            fl = plan["floors"][i:i + per]
            pad = per - len(fl)
            floors += (f"<table class='keep byfloor'><colgroup>{cols}</colgroup><tr><th>Floor</th>"
                       + "".join(f"<th class='n'>{_e(f['floor'])}</th>" for f in fl) + "<th></th>" * pad
                       + "</tr><tr><td>Complete</td>"
                       + "".join(f"<td class='n'>{f['complete']} of {f['total']}</td>" for f in fl) + "<td></td>" * pad
                       + "</tr></table>")
    pct = (f"<p class='lead'>The schedule file reports the project at <b>{proj['reported_percent']:g}% complete</b>.</p>"
           if proj.get("reported_percent") is not None else "")
    head = (f"Per {_e(plan.get('source_name') or 'the imported schedule')}"
            + (f", data date {_e(_fmt(plan['as_of'], '%b %-d, %Y'))}" if plan.get("as_of") else "")
            + (f", confirmed by {_e(plan['confirmed_by'])}" if plan.get("confirmed_by") else "") + ".")
    stale = (f"<div class='strip warn'>This schedule is {plan['stale_days']} days older than the end of this "
             "period; progress after its data date is not reflected.</div>"
             if plan.get("stale_days") and plan["stale_days"] > 21 else "")
    if (plan.get("after_period_days") or 0) > 0:
        stale += (f"<div class='strip warn'>The schedule on file is dated {_e(_fmt(plan['as_of'], '%b %-d, %Y'))}, "
                  f"{plan['after_period_days']} day{'' if plan['after_period_days'] == 1 else 's'} after this period "
                  "ended. Its activity counts, percent complete and forecast finish are as of that later date, not as "
                  "of the period's last day. Milestones are placed by their own dates.</div>")
    if (plan.get("after_today_days") or 0) > 0:
        stale += ("<div class='strip warn'>The schedule's data date is after the day this report was prepared; the "
                  "status date in the file should be checked.</div>")
    return (f"<section><h2>Schedule and completion {_tag('S')}</h2><p class='muted'>{head} Completion figures are "
            f"those the schedule itself reports; Levelog does not estimate completion.</p>{stale}{pct}"
            f"{mtable}{dev}{planned}{groups}{floors}</section>")


def _photo_cell(p: Dict[str, Any], images: Dict[str, str]) -> str:
    see = f"<br><span class='muted'>{_e(p['caption'])}</span>" if p.get("caption") else ""
    return (f"<div class='photo'><div class='frame'><img src='{images[p['key']]}'/></div>"
            f"<div class='cap'>{_e(_fmt(p['date'], '%b %-d'))}"
            f"{' · ' + _e(p['where']) if p.get('where') else ''}{see}</div></div>")


def _photo_rows(ps: List[Dict[str, Any]], images: Dict[str, str], per: int = 4) -> str:
    """Photographs four to a row, each row its own block, so a page can break
    between rows (one block of eight left a blank page under its heading)."""
    return "".join(f"<div class='photos'>{''.join(_photo_cell(p, images) for p in ps[i:i + per])}</div>"
                   for i in range(0, len(ps), per))


def _photos(rep: Dict[str, Any], images: Dict[str, str]) -> str:
    """One block per subcontractor AND kind of work: up to eight photographs,
    grouped by the floor they were filed on, each floor in date order. Whole
    photographs (object-fit: contain), portrait or landscape, never cropped."""
    shown = [p for p in rep["photos"] if images.get(p["key"])]
    if not shown:
        return ""
    order = {s["key"]: n for n, s in enumerate(rep.get("subs") or [])}
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for p in shown:
        groups.setdefault((P.company_key(p["sub"]) or p["sub"], p.get("family") or ""), []).append(p)

    def gkey(kv):
        (sub, fam), group = kv
        return (order.get(sub, 99), group[0]["sub"], ST.ORDER.get(fam, 99))
    rows = []
    for (sub, fam), group in sorted(groups.items(), key=gkey):
        by_place: Dict[str, List[Dict[str, Any]]] = {}
        for p in sorted(group, key=lambda p: (P._floor_order(p), str(p["date"]), p["key"])):
            by_place.setdefault(str(p.get("where") or ""), []).append(p)
        # A heading per floor only when each photo is filed on ONE floor: "floors
        # 1-4", "floors 2-4" and "floor 4" as headings say nothing (588's logs).
        one_floor = all(len(ps[0].get("floors") or []) == 1 for ps in by_place.values())
        if len(by_place) > 1 and one_floor:
            body = "".join(f"<div class='floorhead'>{_e(w or 'Location not given')}</div>{_photo_rows(ps, images)}"
                           for w, ps in by_place.items())
        else:
            body = _photo_rows(sorted(group, key=lambda p: (str(p["date"]), p["key"])), images)
        label = group[0].get("family_label") or ST.LABEL.get(fam, "") or group[0].get("trade") or ""
        what = f" <span class='muted'>· {_e(label)}</span>" if label else ""
        rows.append(f"<div class='strip-row'><h4>{_e(group[0]['sub'])}{what}</h4>{body}</div>")
    return (f"<section class='pg'><h2>Visual progress {_tag('L')}</h2><p class='muted'>Up to eight photographs per "
            "subcontractor and kind of work from the filed daily logs, grouped by floor and in date order, chosen for "
            "installed work that is clearly visible. Sub, date and location are as filed and are not independently "
            "verified; the words under a photograph describe the picture only (automated).</p>"
            f"{''.join(rows)}</section>")


def _workforce(rep: Dict[str, Any]) -> str:
    if not rep["site"]["worked"]:
        return ""
    mob, prev = rep["mobilization"], rep["prev"]
    rows = []
    for s in rep["subs"]:
        tag = ""
        if mob["comparable"] and s["prev_days"] == 0:
            tag = "<div class='muted' style='margin-left:13px'>first period on site</div>"
        note = f" <span class='muted'>({s['log_days']} from log)</span>" if s["log_days"] else ""
        prev_days = str(s["prev_days"]) if s["prev_days"] else "—"
        prev_avg = f"{s['prev_avg']:g}" if s["prev_days"] else "—"
        fl = sorted({f for w in rep["work"] if w["key"] == s["key"] for i in w["items"] for f in i["floors"]})
        rows.append(f"<tr><td><span class='dot' style='background:{s['color']}'></span>{_e(s['name'])}{tag}</td>"
                    f"<td>{_e(s['trade'])}</td><td>{_e(P.floors_label(fl) or '—')}</td>"
                    f"<td class='n'>{len(s['days'])}{note}</td>"
                    f"<td class='n'>{prev_days}</td><td class='n'>{s['avg']:g}</td>"
                    f"<td class='n'>{prev_avg}</td><td class='n'>{s['max']}</td></tr>")
    callouts = []
    if mob["comparable"]:
        for g in mob["gone"][:3]:
            callouts.append(f"{g['name']} not on site this period (last seen {_fmt(g['last'], '%b %-d')}).")
    call = ("<h3>Not on site this period</h3><ul class='tight'>" + "".join(f"<li>{_e(c)}{_tag('G')}</li>" for c in callouts)
            + "</ul>") if callouts else ""
    return (f"<section class='keep'><h2>Workforce and site activity {_tag('G')}</h2><p class='muted'>Workers counted once per day from "
            f"site check-ins; working days are {_e(rep['site']['basis'])}.</p>{call}"
            "<table class='keep wf'><tr><th>Subcontractor</th><th>Trade</th><th>Floors reported</th><th class='n'>Days on site</th>"
            "<th class='n'>Previous</th><th class='n'>Avg workers</th><th class='n'>Previous avg</th>"
            "<th class='n'>Peak</th></tr>" + "".join(rows) + "</table></section>")


def _reg_row(r: Dict[str, Any], note: str = "") -> str:
    issued = _e(_fmt(r["issued"], "%b %-d, %Y")) if r.get("issued") else "—"
    status = r["status"] or "not stated"
    word = ("OPEN" if r.get("closed") is False and r["type"] in ("violation", "swo", "complaint", "dot_violation")
            else "CLOSED" if r.get("closed") else "")
    state = (f"<span class='chip {'crit' if word == 'OPEN' else 'soft'}'>{word}</span> " if word else "")
    # the city's own status word beside ours: "OPEN ACTIVE" and "CLOSED CLOSED" read as a stutter
    city = ("" if word and status.strip().upper() in (word, "ACTIVE" if word == "OPEN" else "RESOLVED")
            else (f"<span class='muted'>city status:</span> {_e(status)}" if word else _e(status)))
    return (f"<tr><td>{_e(r['kind'])}</td><td>{_e(r['number']) or '—'}</td><td class='n'>{issued}</td>"
            f"<td>{state}{city}{note}</td><td>{_tag('R', (r.get('ref_id') or '')[1:])}</td></tr>")


def _regulatory(rep: Dict[str, Any]) -> str:
    reg = rep["regulatory"]
    cov = reg["coverage"]
    cls = "strip" if cov["state"] == "verified" else "strip warn"
    parts = [f"<div class='{cls}'>{_e(cov['note'])}</div>"]
    seen, rows = set(), []

    def add(lst: List[Dict[str, Any]], note_fn=None) -> None:
        for r in lst:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            rows.append(_reg_row(r, note_fn(r) if note_fn else ""))
    add(reg["swo_active"], lambda r: " <span class='muted'>— active stop-work/vacate order</span>")
    add(reg["open"])
    add(reg["swo_lifted"], lambda r: f" <span class='muted'>— lifted {_e(_fmt(r['changed_on'], '%b %-d, %Y'))}</span>")
    add(reg["issued"])
    add(reg["changed"], lambda r: f" <span class='muted'>— was {_e(r.get('changed_from') or 'n/a')}, changed "
                                  f"{_e(_fmt(r['changed_on'], '%b %-d, %Y'))}</span>")
    add(reg["expiring"], lambda r: f" <span class='muted'>— expires {_e(_fmt(r['expires'], '%b %-d, %Y'))}</span>")
    if rows:
        parts.append("<table class='keep'><tr><th>Record</th><th>Number</th><th class='n'>Issued</th>"
                     "<th>Status at period end</th><th></th></tr>" + "".join(rows[:14]) + "</table>")
        parts.append("<div class='muted'>Listed: records open at the end of the period, records issued or changed "
                     f"during it, and permits that expire within {_REG.EXPIRY_HORIZON_DAYS} days of its end. A permit in force "
                     "that expires later is not listed.</div>")
        if len(rows) > 14:
            parts.append(f"<div class='muted'>{len(rows) - 14} more record{' is' if len(rows) == 15 else 's are'} "
                         "listed in the evidence index.</div>")
    elif cov["state"] in ("verified", "partial"):
        parts.append("<p>No DOB or DOT violations, stop-work orders or complaints were open at the end of the "
                     "period, and none were issued during it.</p>")
    if reg["uncertain"]:
        parts.append(f"<div class='muted'>{_n(reg['uncertain'], 'record')} could not be classified as open or closed "
                     "as of the end of this period (its status was first refreshed after the period).</div>")
    insp = rep["inspections"]
    if insp["walked"]:
        more = insp["failed"] - len(insp["failed_items"])
        failed = (" Failed: " + _e(", ".join(f"{f['item']} ({_fmt(f['date'], '%b %-d')})" for f in insp["failed_items"]))
                  + (f" and {more} earlier in the period" if more > 0 else "")
                  + "." if insp["failed"] else " None failed.")
        parts.append(f"<h3>Daily site inspections {_tag('L')}</h3><p>{insp['walked']} inspection items were walked on "
                     f"{insp['days']} days; {insp['passed']} passed, {insp['failed']} failed.{failed}</p>")
    up = rep["upcoming"][5:]            # the first five are on page 1 ("Coming up")
    if up:
        parts.append("<h3>Further deadlines</h3><ul class='tight'>" + "".join(
            f"<li><b>{_e(_fmt(u['date'], '%a %b %-d, %Y'))}</b> — {_e(u['what'])}{_tag(u['src'])}</li>" for u in up) + "</ul>")
    return f"<section class='keep'><h2>Regulatory and material risks {_tag('R')}</h2>{''.join(parts)}</section>"


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _short_id(log_id: Any) -> str:
    """The short form of a log's id in the evidence index: its last six
    characters when the id is a plain token (a database id), otherwise a
    six-character digest of it. An id that ends in a date ("log-2026-11-05")
    printed as "(-11-05)", which reads as a broken date."""
    s = str(log_id or "")
    tail = s[-6:]
    if len(tail) == 6 and tail.isalnum() and not tail.isdigit():
        return tail
    return hashlib.sha1(s.encode()).hexdigest()[:6] if s else "no id"


def _basis(rep: Dict[str, Any], report_id: str) -> str:
    notes = "".join(f"<li>{_e(n)}</li>" for n in rep["data_notes"])
    lim = "".join(f"<li>{_e(n)}</li>" for n in rep["limitations"])
    ev = []
    for e in rep["evidence"]:
        if e["kind"] == "daily_logs":
            refs = ", ".join(f"{_fmt(r['date'], '%b %-d')} ({_short_id(r['id'])}{', amended' if r['amended'] else ''})"
                             for r in e["refs"][:24]) + (f" … +{len(e['refs']) - 24} more" if len(e["refs"]) > 24 else "")
            ev.append(f"<tr><td><b>{e['id']}</b></td><td>{_e(e['label'])}</td><td>{_e(e['detail'])}"
                      f"<div class='muted'>{_e(refs)}</div></td></tr>")
        elif e["kind"] == "regulatory":
            # a clickable link showing only its host: the full address is in the
            # stored snapshot, and two wrapped URL lines per record cost a page
            link = (f" <a class='muted' href='{html.escape(e['link'], quote=True)}'>{html.escape(_host(e['link']))}</a>"
                    if e.get("link") else "")
            ev.append(f"<tr><td><b>{e['id']}</b></td><td>{_e(e['label'])}</td><td>{_e(e['detail'])}{link}</td></tr>")
        else:
            ev.append(f"<tr><td><b>{e['id']}</b></td><td>{_e(e['label'])}</td><td>{_e(e['detail'])}</td></tr>")
    stamp = hashlib.sha256(f"{report_id}|{rep['engine']}|{rep['generated'].isoformat()}".encode()).hexdigest()[:10]
    levels = ("<div class='strip'><b>How to read the progress in this report.</b> "
              "<b>Documented</b> — work the subs reported in daily logs. "
              "<b>Estimated</b> — the stages and percentages on the progress page, read from those logs by the "
              "fixed rules printed there. "
              "<b>Measurable</b> — counts or a percent exactly as a confirmed schedule file states them"
              f"{'' if rep.get('schedule') else ' (none on file for this report)'}. "
              "<b>Verified physical progress</b> — not claimed: nothing here is independently verified on site, and "
              "no figure is calculated from headcount.</div>")
    return (f"<section class='keep'><h2>Basis, data notes and evidence</h2>{levels}"
            f"<div class='two'><div><h4>What this report does not contain</h4><ul class='tight'>{lim}</ul></div>"
            f"<div><h4>Data notes</h4><ul class='tight'>{notes or '<li>No discrepancies to note.</li>'}</ul></div></div>"
            f"<h3>Evidence index</h3><table class='ev'><tr><th>ID</th><th>Source</th><th>Detail</th></tr>{''.join(ev)}</table>"
            f"<div class='legend'><b>G</b> site check-ins · <b>L</b> filed daily logs · <b>R</b> DOB/DOT record · "
            f"<b>S</b> project schedule</div>"
            f"<div class='foot'>Generated {_e(_fmt(rep['generated'].astimezone(P.NY), '%B %-d, %Y %-I:%M %p'))} ET "
            f"· engine {_e(rep['engine'])} · reference {stamp}{' · report ' + _e(report_id[:8]) if report_id else ''}. "
            f"The facts printed here are stored with the report.</div></section>")


# ── THE DOCUMENT ─────────────────────────────────────────────────────────────

def render_html(reps: List[Dict[str, Any]], *, gc: str = "", title: str = "", now: Optional[datetime] = None,
                images: Optional[Dict[str, str]] = None, report_id: str = "") -> str:
    """The PDF's HTML: per job the executive overview first, then the sections
    that have something to say (progress board, crews, schedule, workforce,
    photographs, regulatory) and the basis page."""
    global _KEEP
    _KEEP = _record_numbers(reps)
    images = images or {}
    head = f"{reps[0]['job']} · {reps[0]['period']}" if len(reps) == 1 else title
    css = (CSS.replace('"HEADER"', '"' + head.replace('"', "'") + '"')
           .replace('"SOURCE"', '"' + P.SOURCE_LINE + '"'))
    body = []
    for n, rep in enumerate(reps):
        first = (f"<div style='page-break-before:always'></div>" if n else "")
        body.append(first + _mast(rep) + _kpis(rep) + _overview(rep)
                    + f"<section class='keep'><div class='two'>{_changes_block(rep)}{_risks_block(rep)}</div></section>"
                    + f"<section class='keep'><div class='two'>{_coming_block(rep) or '<div></div>'}"
                      f"<div style='display:flex;gap:8px'>{_progress_card(rep)}{_schedule_card(rep)}</div></div></section>"
                    + "<div style='page-break-after:always'></div>"
                    + _board_section(rep) + _progress(rep, images) + _schedule_section(rep) + _workforce(rep)
                    + _photos(rep, images) + _regulatory(rep) + _basis(rep, report_id))
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(title)}</title>"
            f"<style>{css}</style></head><body>{''.join(body)}</body></html>")


def title_for(reps: List[Dict[str, Any]]) -> str:
    if len(reps) == 1:
        return f"Progress report — {reps[0]['job']} — {reps[0]['period']}"
    return f"Progress report — {len(reps)} jobs — {reps[0]['period']}"
