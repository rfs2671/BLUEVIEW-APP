"""The progress report as a document: HTML for WeasyPrint.

DESIGN RULES (they are the product's credibility, not decoration)
  * Page 1 answers, in 60 seconds: how much activity, what changed since the
    previous period, who is on site, what is at risk, what is coming, and
    whether a schedule and financials are verified.
  * Sections that have nothing to say are LEFT OUT (no empty "None" pages);
    what is missing is said once, briefly, where a reader would look for it
    (the schedule and financial cards on page 1, the basis page at the end).
  * Every statement carries a small source tag -- G gate check-ins, L filed
    daily logs, R DOB/DOT record, S schedule, F financials -- and the last
    page indexes the sources, so a reader can tell a record from a figure the
    engine calculated.
  * Photographs are real photographs from the filed daily logs, each with the
    sub, the date, the location as written and the sub's own work line. No
    generated imagery, and no before/after pairing.
  * Charts show data the engine holds, directly labelled, in one hue family
    plus a muted comparison; colour is never the only encoding.
  * The status by floor (the larger report) is lib/project_progress.py's model,
    the one the assistant answers from: a mark's SHAPE is the cell's strongest
    record, an EMPTY cell is unknown (never not done), one legend line says
    every mark, and LeveLog's estimates stay inside their own labelled box.

Pure: no I/O. `images` maps a photo's key to a data URI the server fetched.
"""

from __future__ import annotations

import hashlib
import html
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from lib import progress_report as P
from lib import project_report as base
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
table.wf td:first-child { white-space: nowrap; }
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
.strip-row { page-break-inside: avoid; margin-top: 10px; }
.strip-row h4 { margin: 0 0 4px; font-size: 9.5pt; }
.photo { display: inline-block; vertical-align: top; width: 19%; margin: 0 1% 6px 0; page-break-inside: avoid; font-size: 9pt; }
.photo .frame { height: 1.9in; background: #eef1f5; border-radius: 3px; display: flex; align-items: center; justify-content: center; }
.photo img { max-width: 100%; max-height: 100%; width: auto; height: auto; object-fit: contain; display: block; }
.photo .cap { font-size: 8pt; margin-top: 3px; }
.photo .cap b { font-size: 8.5pt; }
.strip { border-radius: 5px; padding: 5px 9px; font-size: 8.3pt; margin: 4px 0 8px; background: #eef3fa; }
.strip.warn { background: #fdf3e3; }
.legend { font-size: 7.5pt; color: #5b6676; margin-top: 6px; }
.chart { display: block; margin: 4px 0; }
.foot { font-size: 7.5pt; color: #5b6676; margin-top: 10px; }
.mk { vertical-align: -1px; }
.mlegend { white-space: nowrap; font-size: 7pt; }
.mlegend .lg { margin-right: 9px; }
.fs ul.tight, .estbox ul.tight { font-size: 8.4pt; }
.fs ul.tight li { margin-bottom: 2px; }
.nw { white-space: nowrap; }
.fn { margin-top: 2px; }
.wb { margin: 2px 0 8px; }
.wb h4 { margin-bottom: 2px; }
.wbi { display: inline-block; margin: 0 16px 3px 0; font-size: 8.5pt; }
table.lvl { margin: 3px 0 4px; }
table.lvl td { padding: 2px 5px; font-size: 8.3pt; }
table.lvl td.lv { white-space: nowrap; font-weight: 700; width: 12%; }
table.lvl td.sn { font-weight: 700; width: 24%; }
.estbox { border: 1.2px dashed #9aa5b4; border-radius: 6px; padding: 6px 10px; margin-top: 8px; background: #fafbfd; }
.estbox h4 { color: #12263F; }
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
                out.append(f'<text x="{cx:.1f}" y="{base_y - h - 3:.1f}" font-size="8" text-anchor="middle" '
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


def _schedule_card(rep: Dict[str, Any]) -> str:
    plan = rep["schedule"]
    if not (plan and plan.get("usable")):
        return ("<div class='card na'><h4>Schedule</h4><div class='big'>Not provided</div>"
                "<div class='muted'>No confirmed schedule is on file, so completion and milestone status "
                "are not reported.</div></div>")
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
    return (f"<div class='card'><h4>Schedule {_tag('S')}</h4>" + "<br>".join(lines)
            + f"<div class='muted'>{asof}</div></div>")


def _finance_card(rep: Dict[str, Any]) -> str:
    f = rep["financials"]
    if not f:
        return ("<div class='card na'><h4>Financial</h4><div class='big'>Not provided</div>"
                "<div class='muted'>No confirmed budget, change-order or draw data is on file.</div></div>")
    figs = f["figures"]
    pick = [("revised_contract", "Revised contract"), ("contract_value", "Contract"),
            ("billed_to_date", "Billed to date"), ("cost_to_complete", "Cost to complete")]
    shown = [f"{lbl}: <b>${figs[k]:,.0f}</b>" for k, lbl in pick if k in figs][:3]
    return (f"<div class='card'><h4>Financial {_tag('F')}</h4>" + "<br>".join(shown)
            + f"<div class='muted'>As of {_e(_fmt(f['as_of'], '%b %-d, %Y'))} · {_e(f['source'])}</div></div>")


def _coming_block(rep: Dict[str, Any]) -> str:
    up = rep["upcoming"][:5]
    if not up:
        return ""
    return ("<div><h4>Coming up (next 30 days)</h4><ul class='tight'>"
            + "".join(f"<li><b>{_e(_fmt(u['date'], '%a %b %-d'))}</b> — {_e(u['what'])}{_tag(u['src'])}</li>"
                      for u in up) + "</ul></div>")


_LABELS = ("Reported work", "Regulatory", "Schedule", "Financial")


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
    legend = ("<div class='legend'><span class='dot' style='background:#5b6676'></span>On site"
              + ("&nbsp;&nbsp;<svg width='8' height='8' viewBox='0 0 8 8'><circle cx='4' cy='4' r='3' fill='#fff' "
                 f"stroke='{NAVY}'/></svg> Photo in this report" if photo_days else "") + "</div>")
    return (f"<section class='pg'><h2>Schedule progress {_tag('G')}{_tag('L')}</h2>"
            "<p class='muted'>Who worked when, and what they reported, from site check-ins and filed daily logs. "
            "A bar is days on site, not measured completion.</p>"
            f"<table class='gantt'><tr><td class='who'></td><td class='bar'>{_gantt_axis(start, end, ticks)}</td><td class='n'></td></tr>"
            f"{''.join(rows)}</table>{legend}{_sub_status(rep)}</section>")


# ── STATUS BY FLOOR (lib/project_progress.py: the assistant's model) ────────
#
# Every mark is the cell's evidence.status(), read off the SAME model the
# assistant answers from (server._project_progress), never computed here. The
# SHAPE says the rung (filled = a done statement, hollow or a dash = work in
# progress, a cross = failed); an EMPTY cell is unknown: nothing on record,
# either way. No percent is drawn; one appears only where a source states it.

#: More levels or steps than this, and the matrix becomes a list per level.
FLOOR_MAX_LEVELS = 12
FLOOR_MAX_STEPS = 22

#: (mark, legend words), strongest first.
MARKS = (("verified", "Verified (DOB / agency)"),
         ("confirmed", "Confirmed (signed)"),
         ("attested", "Stated done (named person)"),
         ("observed", "Photo: in progress"),
         ("reported", "Reported: in progress"),
         ("failed", "Failed"))
UNKNOWN_NOTE = ("An empty cell is unknown: nothing is on record either way, so it is shown neither as done nor as "
                "not done.")
UNKNOWN_NOTE_LIST = ("Unknown means nothing is on record either way: such a step is shown neither as done nor as "
                     "not done.")
NO_SCHEDULE_LINE = "No confirmed schedule is on file, so no planned date is compared and nothing is estimated."
FAIL_RED = "#B42318"

#: Short column names; anything else is the model's own label.
_SHORT = {"framing": "Framing", "rough_dwv": "DWV rough", "rough_duct": "Duct rough",
          "rough_sprinkler": "Sprinkler rough", "rough_water": "Water rough", "rough_gas": "Gas rough",
          "rough_electric": "Electric rough", "rough_lowvolt": "Fire alarm / LV", "gate_plumbing_rough": "Plumbing rough",
          "gate_sprinkler_hydro": "Sprinkler hydro", "gate_electrical_rough": "Electrical rough",
          "gate_firestopping": "Firestopping", "gate_nycecc_insulation": "Energy code", "drywall": "Drywall",
          "ceiling_drop": "Ceilings", "prime": "Prime / paint", "finishes": "Finishes", "mep_trim": "MEP trim",
          "zone_final": "Zone final", "gas_pressure_test": "Gas pressure test", "superstructure": "Structure",
          "facade_envelope": "Facade", "windows": "Windows", "standpipe": "Standpipe", "demolition": "Demolition",
          "excavation_soe": "Excavation / SOE", "foundation": "Foundation", "roofing": "Roofing",
          "elevator": "Elevator", "site_utilities": "Site utilities"}
_GROUPS = ("Structure", "Framing and rough-in", "Inspections", "Close-in and finish")
#: Always on the whole-building line, on record or not.
_BUILDING_ALWAYS = ("demolition", "excavation_soe", "foundation")


def mark_of(status: Optional[str]) -> Optional[str]:
    """The mark for a cell's evidence.status(); None is unknown (an empty cell)."""
    s = str(status or "unknown")
    if s.startswith("done_"):
        return s[5:]
    if s.startswith("failed_"):
        return "failed"
    return {"in_progress_observed": "observed", "reported": "reported"}.get(s)


def _mark_shape(kind: Optional[str], cx: float, cy: float, r: float = 4.6) -> str:
    if kind == "verified":
        return f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" fill="{NAVY}"/>'
    if kind == "confirmed":
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{NAVY}"/>'
    if kind == "attested":
        return (f'<polygon points="{cx:.1f},{cy - r - 0.6:.1f} {cx + r + 0.6:.1f},{cy + r - 0.4:.1f} '
                f'{cx - r - 0.6:.1f},{cy + r - 0.4:.1f}" fill="{NAVY}"/>')
    if kind == "observed":
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r - 0.8:.1f}" fill="#fff" stroke="{NAVY}" stroke-width="1.5"/>'
    if kind == "reported":
        return f'<rect x="{cx - r:.1f}" y="{cy - 1.3:.1f}" width="{2 * r:.1f}" height="2.6" rx="1" fill="{MUTED}"/>'
    if kind == "failed":
        return (f'<path d="M{cx - r + 0.6:.1f},{cy - r + 0.6:.1f} L{cx + r - 0.6:.1f},{cy + r - 0.6:.1f} '
                f'M{cx + r - 0.6:.1f},{cy - r + 0.6:.1f} L{cx - r + 0.6:.1f},{cy + r - 0.6:.1f}" '
                f'stroke="{FAIL_RED}" stroke-width="2" stroke-linecap="round"/>')
    return ""


def mark_svg(kind: Optional[str], size: int = 11) -> str:
    """One mark inline in a line of text; unknown is an empty box."""
    c = size / 2
    inner = _mark_shape(kind, c, c, r=size * 0.4) if kind else (
        f'<rect x="0.5" y="0.5" width="{size - 1}" height="{size - 1}" fill="#f1f4f8" stroke="#c4ccd8" stroke-width="0.8"/>')
    return (f'<svg class="mk" xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">{inner}</svg>')


def floor_legend() -> str:
    """The one-line legend every status visual carries (an empty cell is
    said under the matrix, where there are empty cells)."""
    bits = "".join(f"<span class='lg'>{mark_svg(k, 10)}&nbsp;{_e(w)}</span>" for k, w in MARKS)
    return f"<div class='legend mlegend'>{bits}</div>"


def _large(rep: Dict[str, Any]) -> bool:
    return (rep["end"] - rep["start"]).days + 1 >= GANTT_MIN_DAYS


def _model(rep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return rep.get("progress_model") if _large(rep) else None


def _short(model: Dict[str, Any], node: str) -> str:
    if node in _SHORT:
        return _SHORT[node]
    from lib import project_progress as PPG
    label = PPG._step_label(model, node)
    return label[:1].upper() + label[1:]


def _group_of(step: Dict[str, Any]) -> int:
    if step.get("source") == "work_nodes":
        return 0
    if step["gate"] or step["id"].endswith("_test"):
        return 2
    if step["id"] == "framing" or step["id"].startswith("rough_"):
        return 1
    return 3


def floor_columns(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The matrix's steps: every step with a record on any level, and the
    standard interior steps (graph_v1's, not the ones only some buildings
    have), grouped in sequence order."""
    has = {n for (_lv, n), c in model["cells"].items() if c["bucket"] != "unknown"}
    seq = model["frame"]["steps"]
    cols = [s for s in seq if s["id"] in has or (s.get("source") == "graph_v1" and not s.get("conditional"))]
    order = {s["id"]: k for k, s in enumerate(seq)}
    return sorted(cols, key=lambda s: (_group_of(s), order[s["id"]]))


def _levels_top_first(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(reversed(model["frame"]["levels"]))


def _text_w(text: str, size: float) -> float:
    return len(text) * size * 0.6           # DejaVu Sans, the PDF's fallback face, is the widest


def floor_matrix_svg(model: Dict[str, Any], cols: List[Dict[str, Any]], width: int = 700) -> str:
    levels = _levels_top_first(model)
    label_w = max(64.0, max((_text_w(lv["label"], 8.5) for lv in levels), default=0) + 10)
    gap, row_h, group_h = 8.0, 19.0, 15.0
    groups: List[Tuple[int, List[Dict[str, Any]]]] = []
    for s in cols:
        g = _group_of(s)
        if not groups or groups[-1][0] != g:
            groups.append((g, []))
        groups[-1][1].append(s)
    avail = width - label_w - gap * (len(groups) - 1) - 4
    col_w = max(16.0, min(30.0, avail / max(1, len(cols))))
    head_h = max(_text_w(_short(model, s["id"]), 7.5) for s in cols) + 8 if cols else 20
    x, out_cols, heads = label_w, [], []
    for g, members in groups:
        name = _GROUPS[g]
        span = max(len(members) * col_w, _text_w(name, 7) + 6)
        pad = (span - len(members) * col_w) / 2
        heads.append((name, x, span))
        for k, s in enumerate(members):
            out_cols.append((s, x + pad + k * col_w))
        x += span + gap
    total_w = x - gap + 2
    top = group_h + head_h
    height = top + row_h * len(levels) + 2
    o = [f'<svg class="chart fm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.0f} {height:.0f}" '
         f'width="{total_w:.0f}" height="{height:.0f}" font-family="Helvetica, Arial, sans-serif">']
    for name, gx, span in heads:
        o.append(f'<text x="{gx + span / 2:.1f}" y="9" font-size="7" font-weight="700" letter-spacing="0.4" '
                 f'text-anchor="middle" fill="{MUTED}">{_e(name.upper())}</text>')
        o.append(f'<line x1="{gx:.1f}" y1="12.5" x2="{gx + span:.1f}" y2="12.5" stroke="{MUTED}" stroke-width="0.8"/>')
    for s, cx in out_cols:
        tx, ty = cx + col_w / 2 + 2.6, top - 4
        o.append(f'<text transform="translate({tx:.1f},{ty:.1f}) rotate(-90)" font-size="7.5" fill="{INK}">'
                 f'{_e(_short(model, s["id"]))}</text>')
    for r, lv in enumerate(levels):
        y = top + r * row_h
        o.append(f'<text x="0" y="{y + row_h / 2 + 3:.1f}" font-size="8.5" font-weight="700" fill="{INK}">'
                 f'{_e(lv["label"])}</text>')
        for s, cx in out_cols:
            c = model["cells"][(lv["level"], s["id"])]
            o.append(f'<rect x="{cx + 1:.1f}" y="{y + 1:.1f}" width="{col_w - 2:.1f}" height="{row_h - 2:.1f}" '
                     f'fill="#f1f4f8"/>')
            kind = mark_of(c["status"])
            if kind:
                o.append(_mark_shape(kind, cx + col_w / 2, y + row_h / 2))
    o.append("</svg>")
    return "".join(o)


def _per_level_list(model: Dict[str, Any], cols: List[Dict[str, Any]]) -> str:
    """The matrix as a list, for a job too tall or too varied for one page."""
    rows = []
    for lv in _levels_top_first(model):
        cs = [(s, model["cells"][(lv["level"], s["id"])]) for s in cols]
        on = [(s, c) for s, c in cs if mark_of(c["status"])]
        got = " &nbsp;".join(f"<span class='nw'>{mark_svg(mark_of(c['status']))}&nbsp;{_e(_short(model, s['id']))}</span>"
                             for s, c in on)
        rest = len(cs) - len(on)
        tail = (f"<span class='muted'>{' · ' if on else ''}{rest} {'other ' if on else ''}step{'s' if rest != 1 else ''}"
                ": nothing on record (unknown)</span>") if rest else ""
        rows.append(f"<tr><td class='lv'>{_e(lv['label'])}</td><td>{got}{tail}</td></tr>")
    return f"<table class='lvl'>{''.join(rows)}</table>"


def _day_y(d: Any) -> str:
    return _fmt(d, "%b %-d, %Y") if isinstance(d, date) else ""


def _building_note(c: Dict[str, Any]) -> str:
    """What decided a whole-building cell, as printed beside its mark."""
    from lib import project_progress as PPG
    if c["bucket"] == "unknown":
        return "no record"
    d = c.get("decided_by") or {}
    if d.get("source") == "dob_logs":
        when = _day_y(d.get("on")) or "sign-off date not on the stored record"
        return f"DOB sign-off, {when} (filing {d.get('ref')})"
    if d:
        who = PPG._who(d)
        return f"{'done' if c['bucket'] == 'done' else 'failed'}, {d['kind']} {who}, {_day_y(d.get('on'))}".rstrip(", ")
    words = {"in_progress_observed": "photographed in progress", "reported": "reported in progress"}
    span = PPG._span(c)
    return words.get(c["status"], c["status"].replace("_", " ")) + (f", {span}" if span else "")


def _whole_building(model: Dict[str, Any]) -> str:
    cells = [c for c in model.get("building") or () if c["node"] in _BUILDING_ALWAYS or c["bucket"] != "unknown"]
    cells.sort(key=lambda c: (_BUILDING_ALWAYS.index(c["node"]) if c["node"] in _BUILDING_ALWAYS else 9))
    if not cells:
        return ""
    bits = "".join(f"<div class='wbi'>{mark_svg(mark_of(c['status']))}&nbsp;<b>{_e(_short(model, c['node']))}</b> "
                   f"<span class='muted'>{_e(_building_note(c))}</span></div>" for c in cells)
    return f"<div class='wb'><h4>Whole building</h4>{bits}</div>"


def _open_words(model: Dict[str, Any], level: str) -> str:
    """Open on the record, from the model's bottleneck: never a cause."""
    b = model["by_level"][level]["bottleneck"]
    from lib import project_progress as PPG
    bits = []
    if b["earliest_open"]:
        more = len(b["open_work"]) - 1
        bits.append(f"earliest step with no done record: {PPG._step_label(model, b['earliest_open'])}"
                    + (f" (and {more} more at the same point in the sequence)" if more else ""))
    failed = [g["label"] for g in b["gates"] if g["bucket"] == "failed"]
    unknown = [g for g in b["gates"] if g["bucket"] == "unknown"]
    if failed:
        bits.append("inspection failed on record: " + ", ".join(failed))
    if unknown:
        bits.append(f"{len(unknown)} inspection{'s' if len(unknown) != 1 else ''} with no record")
    text = "; ".join(bits)
    return text[:1].upper() + text[1:]


def _open_on_record(model: Dict[str, Any]) -> str:
    rows, quiet = [], []
    for lv in _levels_top_first(model):
        c = model["by_level"][lv["level"]]["counts"]
        if c.get("unknown", 0) == len(model["frame"]["steps"]):
            quiet.append(lv["label"])
            continue
        rows.append(f"<tr><td class='lv'>{_e(lv['label'])}</td><td>{_e(_open_words(model, lv['level']))}</td></tr>")
    if not rows and not quiet:
        return ""
    q = (f"<div class='muted'>Nothing on record for: {_e(', '.join(quiet))}.</div>" if quiet else "")
    return ("<h3>Open on the record, by level</h3><div class='muted'>By the standard sequence: the earliest step "
            "with no done record whose earlier steps all have one, and inspections with no record or a failure. "
            f"No cause is stated.</div><table class='lvl'>{''.join(rows)}</table>{q}")


def _disagree(model: Dict[str, Any]) -> str:
    cs = model.get("conflicts") or []
    if not cs:
        return ""
    shown = "".join(f"<li>{_e(c['what'])} <span class='muted'>(records {_e(', '.join(c['refs']))})</span></li>"
                    for c in cs[:6])
    more = (f"<div class='muted'>{len(cs) - 6} more in the report's stored snapshot.</div>" if len(cs) > 6 else "")
    return (f"<h3>Records that disagree ({len(cs)})</h3><div class='muted'>To confirm with the field; neither "
            f"record is taken over the other.</div><ul class='tight'>{shown}</ul>{more}")


def _outside(model: Dict[str, Any]) -> str:
    cs = model.get("outside_frame") or []
    if not cs:
        return ""
    from lib import work_state as WS
    said = "; ".join(f"{WS.node_label(c['node'])} on {WS.level_label(c['level'])}" for c in cs[:6])
    return f"<div class='muted'>Also on record, outside the standard steps: {_e(said)}.</div>"


def _status_by_floor(rep: Dict[str, Any]) -> str:
    if not _large(rep):
        return ""
    if rep.get("progress_unavailable"):
        return ("<section class='pg'><h2>Status by floor</h2><p class='none'>The progress records could not be read "
                "for this report, so no status by floor is shown. This is not a statement that nothing is on "
                "record.</p></section>")
    model = _model(rep)
    if not model:
        return ""
    cols = floor_columns(model)
    levels = model["frame"]["levels"]
    note = UNKNOWN_NOTE
    if not levels or not cols:
        body = "<p class='none'>No level of this job is on record, so there is no status by floor.</p>"
    elif len(levels) > FLOOR_MAX_LEVELS or len(cols) > FLOOR_MAX_STEPS:
        body, note = _per_level_list(model, cols), UNKNOWN_NOTE_LIST
    else:
        body = floor_matrix_svg(model, cols)
    asof = _fmt(model["today"], "%b %-d, %Y")
    subs = "" if rep["subs"] else _sub_status(rep)
    sched = "" if rep.get("forecast") else f"<p class='muted'>{_e(NO_SCHEDULE_LINE)}</p>"
    return (f"<section class='pg fs'><h2>Status by floor</h2><p class='muted'>The strongest record for each level and "
            f"work step, from every source on file, as of {_e(asof)}. Steps are the standard sequence laid over "
            "each level, not this job's schedule. No percent complete is calculated.</p>"
            f"{_whole_building(model)}{body}{floor_legend()}<div class='foot fn'>{mark_svg(None, 10)}&nbsp;{_e(note)}</div>"
            f"{_outside(model)}{_open_on_record(model)}{_disagree(model)}{subs}{sched}</section>")


def _levels_words(levels: List[str]) -> str:
    """Bottom to top: "Cellar, Floors 1–3, Roof"."""
    from lib import project_progress as PPG
    from lib import work_state as WS
    from lib.plans import level_suggestion as LS
    out, run = [], []

    def flush() -> None:
        if run:
            out.append(f"Floor {run[0]}" if len(run) == 1 else f"Floors {run[0]}–{run[-1]}")
            run.clear()
    for lv in sorted(levels, key=PPG.level_order):
        n = LS.floor_number(lv)
        if n is not None and (not run or n == run[-1] + 1):
            run.append(n)
            continue
        flush()
        if n is not None:
            run.append(n)
        else:
            out.append(WS.level_label(lv))
    flush()
    return ", ".join(out)


def _sub_status(rep: Dict[str, Any]) -> str:
    """Per sub: the floors and work it has records on, and the strongest
    record of each, from the model's subs."""
    model = _model(rep)
    if not model or not model.get("subs"):
        return ""
    outside = {(c["level"], c["node"]): c for c in model.get("outside_frame") or ()}
    rank = {k: n for n, (k, _w) in enumerate(MARKS)}
    rows, idle = [], []
    subs = sorted(model["subs"].values(), key=lambda s: (s["first"] or date.max, s["sub"]))
    for s in subs:
        if not s["work"]:
            idle.append(s["sub"])
            continue
        by_node: Dict[str, Dict[Optional[str], List[str]]] = {}
        for w in s["work"]:
            c = model["cells"].get((w["level"], w["node"])) or outside.get((w["level"], w["node"])) or {}
            by_node.setdefault(w["node"], {}).setdefault(mark_of(c.get("status")), []).append(w["level"])
        parts = []
        for node, marks in by_node.items():
            bits = " ".join(f"<span class='nw'>{mark_svg(k)}&nbsp;{_e(_levels_words(lv))}</span>"
                            for k, lv in sorted(marks.items(), key=lambda kv: rank.get(kv[0], 99)))
            parts.append(f"<span class='nw'><b>{_e(_short(model, node))}</b>:</span> {bits}")
        rows.append(f"<tr><td class='sn'>{_e(s['sub'])}</td><td>{' &nbsp;·&nbsp; '.join(parts)}</td></tr>")
    if not rows and not idle:
        return ""
    tail = (f"<div class='muted'>On site with no work step on record: {_e(', '.join(idle))}.</div>" if idle else "")
    return ("<div class='keep'><h3>What the records show, by subcontractor</h3><div class='muted'>The floors and work "
            "each sub has records on, with the strongest record for each (the same marks as the status by floor).</div>"
            f"<table class='lvl subst'>{''.join(rows)}</table>{floor_legend()}{tail}</div>")


def _forecast_section(rep: Dict[str, Any]) -> str:
    """lib/forecast.py's four groups, when a confirmed schedule is on file;
    LeveLog's estimates only inside their own labelled box."""
    sec = rep.get("forecast") if _large(rep) else None
    if not sec:
        return ""
    heads = {"verified": "Verified (start and done markers, attested or stronger)",
             "file": "The schedule file (its own dates and logic: a plan, not evidence of work)",
             "reported": "Reported in daily logs (never a start or a finish)"}
    by = {g["key"]: g for g in sec["groups"]}

    def lines(key: str, cap: int = 6) -> str:
        got = [ln[2:] if ln.startswith("- ") else ln for ln in by[key]["lines"]]
        more = len(got) - cap
        got = got[:cap] + ([f"…and {more} more in the report's stored snapshot."] if more > 0 else [])
        return "<ul class='tight'>" + "".join(f"<li>{_e(ln.strip())}</li>" for ln in got) + "</ul>"
    parts = "".join(f"<h3>{_e(heads[k])}</h3>{lines(k)}" for k in ("verified", "file", "reported") if k in by)
    est = (f"<div class='estbox'><h4>Estimates: computed by LeveLog, not verified</h4><div class='muted'>Each with "
           f"its basis and the number of levels it rests on; never a schedule date.</div>{lines('estimate', 10)}</div>"
           if "estimate" in by else "")
    return (f"<section class='keep fs'><h2>Schedule status against the confirmed file {_tag('S')}</h2><p class='muted'>"
            "Four kinds of statement, kept apart: verified markers, the file's own dates, what the logs reported, "
            f"and estimates. No cause of delay is stated.</p>{parts}{est}</section>")


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
    rows = ("".join(mrow(m, "COMPLETE", "new") for m in ms["completed_in_period"][:6])
            + "".join(mrow(m, "PAST DUE", "crit") for m in ms["overdue"][:6])
            + "".join(mrow(m, "UPCOMING", "adv") for m in ms["upcoming"][:6])
            + "".join(mrow(m, "NOT UPDATED", "soft") for m in ms["unconfirmed"][:4]))
    mtable = ("<h3>Milestones</h3><table class='keep'><tr><th>Milestone</th><th class='n'>Original</th>"
              "<th class='n'>Current / actual</th><th>Status</th></tr>" + rows + "</table>") if rows else ""
    dev = ""
    if plan["deviations"]:
        dev = ("<h3>Schedule changes shown in the file</h3><table class='keep'><tr><th>Activity</th><th class='n'>Original</th>"
               "<th class='n'>Current</th><th class='n'>Shift</th></tr>"
               + "".join(f"<tr><td>{_e(d['name'])}</td><td class='n'>{_e(_fmt(base._d(d['baseline']), '%b %-d'))}</td>"
                         f"<td class='n'>{_e(_fmt(base._d(d['current']), '%b %-d'))}</td>"
                         f"<td class='n'>{'+' if d['days'] > 0 else ''}{d['days']} d</td></tr>"
                         for d in plan["deviations"][:6]) + "</table>"
               "<div class='muted'>Dates as they appear in the schedule file; no cause is inferred.</div>")
    planned = ""
    if plan["scheduled_in_period"]:
        planned = ("<h3>Scheduled for this period vs. reported</h3><div class='two'><div><h4>Scheduled in the schedule</h4>"
                   "<ul class='tight'>" + "".join(f"<li>{_e(a['name'])} <span class='muted'>({_e(_fmt(base._d(a['start']), '%b %-d'))}"
                                                 f"–{_e(_fmt(base._d(a['finish']), '%b %-d'))})</span></li>"
                                                 for a in plan["scheduled_in_period"][:4]) + "</ul></div>"
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
        fl = plan["floors"][:14]
        floors = ("<h3>By floor (activities named for a floor)</h3><table class='keep'><tr><th>Floor</th>"
                  + "".join(f"<th class='n'>{_e(f['floor'])}</th>" for f in fl) + "</tr><tr><td>Activities complete</td>"
                  + "".join(f"<td class='n'>{f['complete']} of {f['total']}</td>" for f in fl) + "</tr></table>")
    pct = (f"<p class='lead'>The schedule file reports the project at <b>{proj['reported_percent']:g}% complete</b>.</p>"
           if proj.get("reported_percent") is not None else "")
    head = (f"Per {_e(plan.get('source_name') or 'the imported schedule')}"
            + (f", data date {_e(_fmt(plan['as_of'], '%b %-d, %Y'))}" if plan.get("as_of") else "")
            + (f", confirmed by {_e(plan['confirmed_by'])}" if plan.get("confirmed_by") else "") + ".")
    stale = (f"<div class='strip warn'>This schedule is {plan['stale_days']} days older than the end of this "
             "period; progress after its data date is not reflected.</div>"
             if plan.get("stale_days") and plan["stale_days"] > 21 else "")
    return (f"<section><h2>Schedule and completion {_tag('S')}</h2><p class='muted'>{head} Completion figures are "
            f"those the schedule itself reports; Levelog does not estimate completion.</p>{stale}{pct}"
            f"{mtable}{dev}{planned}{groups}{floors}</section>")


def _photos(rep: Dict[str, Any], images: Dict[str, str]) -> str:
    """One ROW per subcontractor: up to five photographs in date order, so the
    row reads as progress over the period. Whole photographs (object-fit:
    contain), portrait or landscape, never cropped."""
    shown = [p for p in rep["photos"] if images.get(p["key"])]
    if not shown:
        return ""
    order = {s["key"]: n for n, s in enumerate(rep.get("subs") or [])}
    by_sub: Dict[str, List[Dict[str, Any]]] = {}
    for p in shown:
        by_sub.setdefault(P.company_key(p["sub"]) or p["sub"], []).append(p)
    rows = []
    for key, group in sorted(by_sub.items(), key=lambda kv: (order.get(kv[0], 99), kv[1][0]["sub"])):
        group = sorted(group, key=lambda p: (str(p["date"]), p["key"]))
        cells = []
        for p in group:
            see = f"<br><span class='muted'>{_e(p['caption'])}</span>" if p.get("caption") else ""
            cells.append(f"<div class='photo'><div class='frame'><img src='{images[p['key']]}'/></div>"
                         f"<div class='cap'>{_e(_fmt(p['date'], '%b %-d'))}"
                         f"{' · ' + _e(p['where']) if p.get('where') else ''}{see}</div></div>")
        trade = f" <span class='muted'>· {_e(group[0]['trade'])}</span>" if group[0].get("trade") else ""
        rows.append(f"<div class='strip-row'><h4>{_e(group[0]['sub'])}{trade}</h4>"
                    f"<div class='photos'>{''.join(cells)}</div></div>")
    return (f"<section class='pg'><h2>Visual progress {_tag('L')}</h2><p class='muted'>Up to five photographs per "
            "subcontractor from the filed daily logs, in date order across the period, chosen for installed work that is "
            "clearly visible. Sub, date and location are as filed and are not independently verified; the words under "
            "each photograph describe the picture only (automated).</p>"
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
    state = ("<span class='chip crit'>OPEN</span> " if r.get("closed") is False and r["type"] in
             ("violation", "swo", "complaint", "dot_violation") else
             "<span class='chip soft'>CLOSED</span> " if r.get("closed") else "")
    return (f"<tr><td>{_e(r['kind'])}</td><td>{_e(r['number']) or '—'}</td><td class='n'>{issued}</td>"
            f"<td>{state}{_e(status)}{note}</td><td>{_tag('R', (r.get('ref_id') or '')[1:])}</td></tr>")


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
        if len(rows) > 14:
            parts.append(f"<div class='muted'>{len(rows) - 14} more records are listed in the evidence index.</div>")
    elif cov["state"] in ("verified", "partial"):
        parts.append("<p>No DOB or DOT violations, stop-work orders or complaints were open at the end of the "
                     "period, and none were issued during it.</p>")
    if reg["uncertain"]:
        parts.append(f"<div class='muted'>{_n(reg['uncertain'], 'record')} could not be classified as open or closed "
                     "as of the end of this period (its status was first refreshed after the period).</div>")
    insp = rep["inspections"]
    if insp["walked"]:
        failed = (" Failed: " + _e(", ".join(f"{f['item']} ({_fmt(f['date'], '%b %-d')})" for f in insp["failed_items"]))
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


def _financial(rep: Dict[str, Any]) -> str:
    f = rep["financials"]
    if not f:
        return ""
    labels = [("contract_value", "Original contract"), ("approved_changes", "Approved changes"),
              ("revised_contract", "Revised contract"), ("budget", "Budget"),
              ("billed_to_date", "Billed to date"), ("paid_to_date", "Paid to date"),
              ("retainage", "Retainage held"), ("cost_to_complete", "Estimated cost to complete"),
              ("contingency_remaining", "Contingency remaining")]
    rows = "".join(f"<tr><td>{lbl}</td><td class='n'>${f['figures'][k]:,.0f}</td></tr>"
                   for k, lbl in labels if k in f["figures"])
    ds = f"<p><b>Draw / payment status:</b> {_e(f['draw_status'])}</p>" if f.get("draw_status") else ""
    return (f"<section><h2>Financial overview {_tag('F')}</h2><p class='muted'>Figures as provided and confirmed "
            f"({_e(f['source'])}), as of {_e(_fmt(f['as_of'], '%b %-d, %Y'))}. Levelog does not calculate or "
            f"estimate financial figures.</p><table class='keep'>{rows}</table>{ds}</section>")


def _basis(rep: Dict[str, Any], report_id: str) -> str:
    notes = "".join(f"<li>{_e(n)}</li>" for n in rep["data_notes"])
    lim = "".join(f"<li>{_e(n)}</li>" for n in rep["limitations"])
    ev = []
    for e in rep["evidence"]:
        if e["kind"] == "daily_logs":
            refs = ", ".join(f"{_fmt(r['date'], '%b %-d')} ({r['id'][-6:]}{', amended' if r['amended'] else ''})"
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
              "<b>Measurable</b> — counts or a percent exactly as a confirmed schedule file states them"
              f"{'' if rep.get('schedule') else ' (none on file for this report)'}. "
              "<b>Verified physical progress</b> — not claimed: nothing here is independently verified on site, and no "
              "completion percentage is calculated from headcount, log wording or photographs.</div>")
    return (f"<section class='keep'><h2>Basis, data notes and evidence</h2>{levels}"
            f"<div class='two'><div><h4>What this report does not contain</h4><ul class='tight'>{lim}</ul></div>"
            f"<div><h4>Data notes</h4><ul class='tight'>{notes or '<li>No discrepancies to note.</li>'}</ul></div></div>"
            f"<h3>Evidence index</h3><table class='ev'><tr><th>ID</th><th>Source</th><th>Detail</th></tr>{''.join(ev)}</table>"
            f"<div class='legend'><b>G</b> site check-ins · <b>L</b> filed daily logs · <b>R</b> DOB/DOT record · "
            f"<b>S</b> project schedule · <b>F</b> financial figures</div>"
            f"<div class='foot'>Generated {_e(_fmt(rep['generated'].astimezone(P.NY), '%B %-d, %Y %-I:%M %p'))} ET "
            f"· engine {_e(rep['engine'])} · reference {stamp}{' · report ' + _e(report_id[:8]) if report_id else ''}. "
            f"The facts printed here are stored with the report.</div></section>")


# ── THE DOCUMENT ─────────────────────────────────────────────────────────────

def render_html(reps: List[Dict[str, Any]], *, gc: str = "", title: str = "", now: Optional[datetime] = None,
                images: Optional[Dict[str, str]] = None, report_id: str = "") -> str:
    """The PDF's HTML: per job the executive overview first, then the sections
    that have something to say (progress, schedule, photographs, workforce,
    regulatory, financial) and the basis page."""
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
                      f"<div style='display:flex;gap:8px'>{_schedule_card(rep)}{_finance_card(rep)}</div></div></section>"
                    + "<div style='page-break-after:always'></div>"
                    + _progress(rep, images) + _status_by_floor(rep) + _schedule_section(rep) + _forecast_section(rep)
                    + _workforce(rep) + _photos(rep, images)
                    + _regulatory(rep) + _financial(rep) + _basis(rep, report_id))
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(title)}</title>"
            f"<style>{css}</style></head><body>{''.join(body)}</body></html>")


def title_for(reps: List[Dict[str, Any]]) -> str:
    if len(reps) == 1:
        return f"Progress report — {reps[0]['job']} — {reps[0]['period']}"
    return f"Progress report — {len(reps)} jobs — {reps[0]['period']}"
