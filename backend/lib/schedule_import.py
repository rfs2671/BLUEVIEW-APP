"""Schedule import: a project schedule file -> ONE normalised document.

LeveLog's progress report has no schedule of its own. This module reads the
schedule a project already has (Primavera P6 XER, MS Project XML, Excel,
CSV, or a text-based PDF table) and turns it into the same plain dict, so
lib/schedule_plan.py can state plan-versus-actual facts from it. It is a
reader, not an author: it never works anything out that the file does not say.

The rules this module keeps (they are why it looks the way it does):

  * Nothing is invented. A field the file does not carry is None. Current
    dates are never copied into the baseline, actual dates never into current
    dates, and an unreadable value becomes a warning, never a guess.
  * `percent_complete` is ONLY a number the file itself reports for that row
    (and for a P6 file only its *physical* percent; see below). It is never
    computed -- not from dates, durations, manpower, logs or photos.
  * `baseline_*` is the ORIGINAL plan, and only when the file has an explicit
    baseline / original column (MS Project: Baseline 0; Excel/CSV: a header
    containing Baseline / Original). The single exception is P6, below.
  * Imported schedules are untrusted drafts: every parse is bounded (size,
    activity count, PDF pages, zip expansion), XML with a DOCTYPE/ENTITY is
    refused, nothing is executed (Excel is read with cached values only) and
    nothing is fetched from the network.
  * PDF is `confidence="extracted"` (a person must confirm it); every other
    format is "structured".

The document:

    {"format": "xer"|"msp_xml"|"xlsx"|"csv"|"pdf", "source_name", "sha256",
     "data_date": "YYYY-MM-DD"|None, "project_name": str|None,
     "confidence": "structured"|"extracted",
     "activities": [{"id", "wbs", "name", "level", "kind", "baseline_start",
                     "baseline_finish", "current_start", "current_finish",
                     "actual_start", "actual_finish", "percent_complete",
                     "duration_days"}, ...],
     "warnings": [str, ...]}

`level` is 0 for the shallowest row in the file (a project summary row, when
the file has one, is level 0) and counts outline depth below it. `kind` is
"summary" for a row that has a deeper block of rows after it (or that the file
flags as a summary), "milestone" for a row the file flags as one or that has
zero duration with start == finish, else "task". Duration is in working days;
hours are divided by the file's own hours-per-day (P6 calendar day_hr_cnt, MS
Project MinutesPerDay, else 8).

FIELD MAPPING, Primavera P6 XER (TASK / PROJWBS / PROJECT tables):

  id <- task_code; name <- task_name.
  kind: task_type TT_Mile / TT_FinMile -> milestone; TT_WBS -> summary.
  baseline_* <- target_start_date / target_end_date. An XER carries no separate
      baseline project, and P6's "target" dates are the plan the activity was
      measured against, so they are the best original-plan figure the file has;
      each such file gets the warning "P6 target dates used as the original
      plan". (If the target dates are unrelated to a baseline the user needs to
      know: that is why a person confirms the import.)
  current_* <- early_start_date / early_end_date, else restart_date /
      reend_date (P6 forecasts for what is left). Never the target dates.
  actual_* <- act_start_date / act_end_date.
  percent_complete <- phys_complete_pct, and ONLY for an activity whose
      complete_pct_type is CP_Phys (or the column is absent); for CP_Phys with
      an empty phys_complete_pct, complete_pct. Duration- and units-based P6
      percents are calculations from remaining hours, not a figure the file
      reports, and phys_complete_pct on such rows is a default 0: all of them
      are left None (one warning says how many).
  duration_days <- target_drtn_hr_cnt / the activity calendar's day_hr_cnt.
  Hierarchy: each PROJWBS node that has activities below it becomes a
      "summary" row (id "WBS:<wbs_id>", name wbs_name, no dates, no percent --
      P6 stores none on a WBS node), its activities follow it, level = WBS
      depth (the root node is level 0, so it is the project row); wbs <- the
      dotted wbs_short_name path below the root.
  data_date <- PROJECT.last_recalc_date (P6's data date, the date the schedule
      was last calculated to). plan_start_date is NOT used: it is when the work
      is planned to begin, not a status date. project_name <- the root WBS
      node's name (what P6 shows as the project name), else proj_short_name.
  Several projects in one XER: the one with the most activities, with a warning.

FIELD MAPPING, MS Project XML (namespace http://schemas.microsoft.com/project):

  id <- UID; wbs <- WBS; name <- Name; level <- OutlineLevel (UID 0, the
  project summary task, is level 0); kind from Milestone / Summary flags;
  current_* <- Start / Finish; actual_* <- ActualStart / ActualFinish;
  baseline_* <- Baseline Number=0 Start / Finish only; duration_days <-
  Duration (ISO 8601) / hours per day; percent_complete <- PhysicalPercentComplete
  ONLY (MS Project's "% Physical Complete", a number a person enters). Its
  PercentComplete is duration-based -- actual duration over planned -- and
  says nothing about how much was built, so it is NOT read as completion: it
  is ignored with one warning, and activities still count as complete from
  their ActualFinish. data_date <- Project/StatusDate (CurrentDate is the
  save time, not a status date, so it is not used); project_name <- Title,
  else Name.

EXCEL / CSV / PDF TABLES: a header row is found in the first 30 rows by
synonym ("Task Name / Activity / Description / Name", "ID / Activity ID / Task
ID", "WBS", "Start / Planned Start / Scheduled Start", "Finish / End",
"Baseline|Original Start|Finish", "Actual Start|Finish", "% Complete /
Percent Complete / Progress", "Milestone", "Type", "Duration", "Outline
Level"). A bare "Start"/"Finish" is the CURRENT schedule. Headers with extra
qualifiers (Late Start, Start Variance, Remaining Duration...) are not
guessed at; they are listed in a warning. Levels come from an outline-level
column, else from indentation (leading spaces or Excel's cell indent), else
from the depth of dotted WBS numbers. A row with a deeper block after it is a
summary. Dates may be real cells or text; for numeric d/m/y text the order is
read from the data (a value whose first part is above 12 proves day/month, one
whose second part is above 12 proves month/day); when nothing settles it
month/day (US) is assumed and a warning says so. Two-digit years are 20yy.
A percent column of plain numbers is read as 0-100 as written (Excel cells
formatted as % are read as the percent they show); a column of plain numbers
that are all <= 1 gets a warning because it may be fractions. A data date is
read only from a labelled cell above the table ("Data Date", "Status Date",
"As of"). Excel formulas are not evaluated (cached values only).

Pure: no I/O, no network, no LLM.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

#: Limits: an imported file is untrusted input.
MAX_BYTES = 20 * 1024 * 1024
MAX_ACTIVITIES = 20_000
MAX_PDF_PAGES = 40
#: Sum of the uncompressed sizes of an .xlsx's parts (zip-bomb guard).
MAX_XLSX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_XLSX_PARTS = 5_000
#: Rows read from one sheet / csv before giving up (activities are capped too).
MAX_ROWS = 200_000
#: Where a table's header row may be.
HEADER_SCAN_ROWS = 30
#: A PDF is believed only with this many dated rows.
MIN_PDF_ROWS = 5

PDF_REFUSAL = (
    "This PDF does not contain a readable schedule table; "
    "export to Excel/MS Project XML/P6 XER"
)

_EARLIEST_YEAR, _LATEST_YEAR = 1990, 2100


class ScheduleImportError(ValueError):
    """The file holds no usable schedule. str(e) is safe to show the user."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _clean(v: Any) -> str:
    """Text of a cell: whitespace collapsed, control characters dropped."""
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = re.sub(r"\s+", " ", str(v))
    return _CTRL.sub("", s).strip()


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _ok_year(d: date) -> bool:
    return _EARLIEST_YEAR <= d.year <= _LATEST_YEAR


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        out = date(y, m, d)
    except (ValueError, OverflowError):
        return None
    return out if _ok_year(out) else None


def _year(s: str) -> int:
    n = int(s)
    return 2000 + n if len(s) <= 2 else n


_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_WEEKDAY = re.compile(r"^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+", re.I)
_TIME_TAIL = re.compile(
    r"[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:\s*[ap]\.?m\.?)?(?:\s*(?:z|[+-]\d{2}:?\d{2}))?\s*$",
    re.I,
)
_ISO_D = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")
_NUM_D = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})$")
_DMON_Y = re.compile(r"^(\d{1,2})[ \-]([A-Za-z]{3,9})\.?[ \-,]+(\d{4}|\d{2})$")
_MON_D_Y = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}|\d{2})$")


def _norm_date_text(v: Any) -> str:
    s = _clean(v)
    s = _WEEKDAY.sub("", s)
    s = _TIME_TAIL.sub("", s)
    # P6 prints an "A" after an actual date, some exports a "*" after an estimate.
    s = re.sub(r"\s*\*$|\s+A$", "", s)
    return s.strip()


def _detect_order(texts: List[str]) -> Tuple[str, Optional[str]]:
    """("mdy"|"dmy", warning|None) for the numeric d/m/y dates in `texts`."""
    dm = md = amb = False
    for t in texts:
        m = _NUM_D.match(_norm_date_text(t))
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            dm = True
        elif b > 12 >= a:
            md = True
        elif a <= 12 and b <= 12 and a != b:
            amb = True
    if dm and md:
        return "mdy", (
            "The file mixes day/month and month/day dates; month/day (US) was assumed "
            "for the numeric ones. Check the dates."
        )
    if dm:
        return "dmy", None
    if md:
        return "mdy", None
    if amb:
        return "mdy", (
            "Dates such as 3/4/26 could be day/month or month/day and nothing in the "
            "file settles it; month/day (US) was assumed. Check the dates."
        )
    return "mdy", None


def _parse_date(v: Any, order: str = "mdy") -> Optional[date]:
    """A date from a cell value (date, datetime or text), else None."""
    if isinstance(v, datetime):
        d = v.date()
        return d if _ok_year(d) else None
    if isinstance(v, date):
        return v if _ok_year(v) else None
    if v is None or isinstance(v, (bool, int, float)):
        return None  # a bare number is never read as an Excel serial: not guessed
    s = _norm_date_text(v)
    if not s:
        return None
    m = _ISO_D.match(s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _NUM_D.match(s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        return _safe_date(y, b, a) if order == "dmy" else _safe_date(y, a, b)
    m = _DMON_Y.match(s)
    if m and m.group(2)[:3].lower() in _MONTHS:
        return _safe_date(_year(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    m = _MON_D_Y.match(s)
    if m and m.group(1)[:3].lower() in _MONTHS:
        return _safe_date(_year(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    return None


def _iso_dt(s: Any) -> Optional[date]:
    """A date from an ISO timestamp ('2026-10-05T08:00:00', '2026-10-05 08:00')."""
    t = _clean(s)
    if len(t) < 10:
        return None
    try:
        d = date.fromisoformat(t[:10])
    except ValueError:
        return None
    return d if _ok_year(d) else None


def _num(v: Any) -> Optional[float]:
    """A finite number from a number or numeric text; booleans are not numbers."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        s = _clean(v).replace(",", "")
        if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?|[-+]?\.\d+", s):
            return None
        f = float(s)
    return f if math.isfinite(f) else None


def _pct(v: Any) -> Optional[float]:
    """A reported percent, 0-100; text like '45%' is read, anything else is None."""
    if isinstance(v, str):
        v = _clean(v).rstrip("%").strip()
    f = _num(v)
    if f is None:
        return None
    return max(0.0, min(100.0, f))


_DUR = re.compile(r"^([-+]?\d+(?:\.\d+)?)\s*([a-z]*)\??$", re.I)
_DUR_PER_DAY = {
    "": 1.0, "d": 1.0, "day": 1.0, "days": 1.0, "ed": 1.0, "edays": 1.0, "eday": 1.0,
    "w": 5.0, "wk": 5.0, "wks": 5.0, "week": 5.0, "weeks": 5.0,
    "mo": 20.0, "mon": 20.0, "mos": 20.0, "month": 20.0, "months": 20.0,
}  # fmt: skip
_DUR_HOURS = {"h", "hr", "hrs", "hour", "hours"}
_DUR_MINS = {"m", "min", "mins", "minute", "minutes"}


def _duration_days(v: Any, hours_per_day: float = 8.0) -> Optional[float]:
    """Working days from a number (days) or text such as '5 days', '40h', '2w'."""
    f = _num(v)
    if f is not None:
        return f if f >= 0 else None
    m = _DUR.match(_clean(v).replace(",", ""))
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower()
    if n < 0:
        return None
    if unit in _DUR_HOURS:
        return round(n / hours_per_day, 4)
    if unit in _DUR_MINS:
        return round(n / 60.0 / hours_per_day, 4)
    if unit in _DUR_PER_DAY:
        return round(n * _DUR_PER_DAY[unit], 4)
    return None


def _truthy(v: Any) -> Optional[bool]:
    s = _clean(v).lower()
    if s in {"y", "yes", "true", "1", "x", "t"}:
        return True
    if s in {"n", "no", "false", "0", "f"}:
        return False
    return None


def _raw(**kw: Any) -> Dict[str, Any]:
    """An activity before normalisation; every field the file lacks is None."""
    base: Dict[str, Any] = {
        "id": None, "wbs": None, "name": "", "level": 0, "hint": None,
        "bs": None, "bf": None, "cs": None, "cf": None, "as_": None, "af": None,
        "pct": None, "dur": None,
    }  # fmt: skip
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Normalisation shared by every format
# ---------------------------------------------------------------------------


def _finish(
    fmt: str,
    name: str,
    sha: str,
    raws: List[Dict[str, Any]],
    warnings: List[str],
    *,
    data_date: Optional[date],
    project_name: Optional[str],
    confidence: str = "structured",
) -> Dict[str, Any]:
    if len(raws) > MAX_ACTIVITIES:
        raise ScheduleImportError(
            f"This schedule has more than {MAX_ACTIVITIES:,} activities, which is more than "
            "can be imported. Export a smaller part of it."
        )
    if raws:
        shift = min(int(r["level"] or 0) for r in raws)
    else:
        shift = 0

    acts: List[Dict[str, Any]] = []
    seen: Dict[str, Dict[str, Any]] = {}
    synth_ids = dups = dropped = 0
    afin_low: List[str] = []
    for i, r in enumerate(raws, 1):
        nm = _clean(r["name"])[:300]
        if not nm:
            continue
        rid = _clean(r["id"])[:100]
        if not rid:
            rid = f"row{i}"
            synth_ids += 1
        cs, cf, bs, bf = r["cs"], r["cf"], r["bs"], r["bf"]
        hint = r["hint"]
        if hint == "summary":
            kind = "summary"
        elif hint == "milestone":
            kind = "milestone"
        elif r["dur"] == 0 and ((cs and cs == cf) or (not (cs or cf) and bs and bs == bf)):
            kind = "milestone"
        else:
            kind = "task"
        pct = r["pct"]
        if r["af"] and pct is not None and pct < 100:
            afin_low.append(rid)  # reported as is: never "fixed"
        rec = {
            "id": rid,
            "wbs": _clean(r["wbs"])[:100] or None,
            "name": nm,
            "level": max(0, int(r["level"] or 0) - shift),
            "kind": kind,
            "baseline_start": _iso(bs),
            "baseline_finish": _iso(bf),
            "current_start": _iso(cs),
            "current_finish": _iso(cf),
            "actual_start": _iso(r["as_"]),
            "actual_finish": _iso(r["af"]),
            "percent_complete": pct,
            "duration_days": r["dur"],
        }
        if rid in seen:
            if seen[rid] == rec:
                dropped += 1
                continue
            dups += 1
        else:
            seen[rid] = rec
        acts.append(rec)

    if synth_ids:
        warnings.append(
            f"{synth_ids} rows had no id; they were numbered by their row (row<n>)."
        )
    if dropped:
        warnings.append(f"{dropped} exact duplicate rows were dropped.")
    if dups:
        warnings.append(f"{dups} rows reuse an id that another, different row already has.")
    if afin_low:
        warnings.append(
            f"{len(afin_low)} activities have an actual finish but a reported percent "
            f"below 100 (e.g. {', '.join(afin_low[:3])}); both are left as the file has them."
        )
    if not acts:
        raise ScheduleImportError("No activities were found in this file.")
    dated = ("baseline_start", "baseline_finish", "current_start", "current_finish",
             "actual_start", "actual_finish")  # fmt: skip
    if not any(a[k] for a in acts for k in dated):
        raise ScheduleImportError("No activity in this file has a readable date.")
    return {
        "format": fmt,
        "source_name": _clean(name)[:200],
        "sha256": sha,
        "data_date": _iso(data_date),
        "project_name": _clean(project_name)[:200] or None,
        "confidence": confidence,
        "activities": acts,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Primavera P6 XER
# ---------------------------------------------------------------------------


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _xer_tables(text: str) -> Dict[str, List[Dict[str, str]]]:
    tables: Dict[str, List[Dict[str, str]]] = {}
    fields: List[str] = []
    cur: Optional[str] = None
    for line in text.splitlines():
        if line.startswith("%T"):
            parts = line.split("\t")
            cur = parts[1].strip() if len(parts) > 1 else None
            fields = []
            if cur:
                tables.setdefault(cur, [])
        elif line.startswith("%F"):
            fields = [f.strip() for f in line.split("\t")[1:]]
        elif line.startswith("%R") and cur:
            vals = line.split("\t")[1:]
            vals += [""] * (len(fields) - len(vals))
            tables[cur].append(dict(zip(fields, vals)))
        elif line.startswith("%E"):
            cur = None
    return tables


def _parse_xer(name: str, data: bytes, sha: str) -> Dict[str, Any]:
    t = _xer_tables(_decode_text(data))
    tasks_all = t.get("TASK") or []
    if not tasks_all:
        raise ScheduleImportError("This P6 file has no activities (no TASK table).")
    warnings: List[str] = []

    # One project: the one with the most activities.
    counts: Dict[str, int] = {}
    for r in tasks_all:
        counts[r.get("proj_id", "")] = counts.get(r.get("proj_id", ""), 0) + 1
    proj_id = max(counts, key=lambda k: counts[k])
    if len(counts) > 1:
        warnings.append(
            f"The file holds {len(counts)} projects; only the one with the most activities "
            "was imported."
        )
    tasks = [r for r in tasks_all if r.get("proj_id", "") == proj_id]
    proj = next((p for p in t.get("PROJECT", []) if p.get("proj_id") == proj_id), None)

    hrs: Dict[str, float] = {}
    for c in t.get("CALENDAR", []):
        h = _num(c.get("day_hr_cnt"))
        if h and h > 0:
            hrs[c.get("clndr_id", "")] = h

    data_date = _iso_dt(proj.get("last_recalc_date")) if proj else None
    if data_date is None:
        warnings.append("The file does not state a data date (PROJECT.last_recalc_date).")

    wbs = {w["wbs_id"]: w for w in t.get("PROJWBS", []) if w.get("proj_id") == proj_id and w.get("wbs_id")}
    children: Dict[str, List[str]] = {}
    roots: List[str] = []
    for wid, w in wbs.items():
        par = w.get("parent_wbs_id", "")
        (children.setdefault(par, []) if par in wbs else roots).append(wid)

    def _seq(wid: str) -> Tuple[float, str]:
        return (_num(wbs[wid].get("seq_num")) or 0.0, _clean(wbs[wid].get("wbs_name")))

    used_target = bad_pct = 0
    by_wbs: Dict[str, List[Dict[str, Any]]] = {}
    orphans: List[Dict[str, Any]] = []
    for r in tasks:
        ttype = _clean(r.get("task_type"))
        hint = {"TT_Mile": "milestone", "TT_FinMile": "milestone", "TT_WBS": "summary"}.get(ttype)
        bs, bf = _iso_dt(r.get("target_start_date")), _iso_dt(r.get("target_end_date"))
        if bs or bf:
            used_target += 1
        cs = _iso_dt(r.get("early_start_date")) or _iso_dt(r.get("restart_date"))
        cf = _iso_dt(r.get("early_end_date")) or _iso_dt(r.get("reend_date"))
        ctype = _clean(r.get("complete_pct_type"))
        pct: Optional[float] = None
        if not ctype or ctype == "CP_Phys":
            pct = _pct(r.get("phys_complete_pct")) if _clean(r.get("phys_complete_pct")) else None
            if pct is None and _clean(r.get("complete_pct")):
                pct = _pct(r.get("complete_pct"))
        else:
            bad_pct += 1
        h = hrs.get(r.get("clndr_id", ""), 8.0)
        hours = _num(r.get("target_drtn_hr_cnt"))
        rec = _raw(
            id=r.get("task_code"), name=r.get("task_name", ""), hint=hint,
            bs=bs, bf=bf, cs=cs, cf=cf,
            as_=_iso_dt(r.get("act_start_date")), af=_iso_dt(r.get("act_end_date")),
            pct=pct, dur=round(hours / h, 4) if hours is not None and hours >= 0 else None,
        )  # fmt: skip
        wid = r.get("wbs_id", "")
        (by_wbs.setdefault(wid, []) if wid in wbs else orphans).append(rec)
    if used_target:
        warnings.append("P6 target dates used as the original plan")
    if bad_pct:
        warnings.append(
            f"{bad_pct} activities use a duration- or units-based P6 percent complete; "
            "that is a calculation, not a reported physical percent, so no percent is shown for them."
        )

    raws: List[Dict[str, Any]] = []
    project_name: Optional[str] = None

    def _has_tasks(wid: str) -> bool:
        return bool(by_wbs.get(wid)) or any(_has_tasks(c) for c in children.get(wid, []))

    def _path(wid: str) -> str:
        parts: List[str] = []
        seen = set()
        while wid in wbs and wid not in seen:
            seen.add(wid)
            w = wbs[wid]
            if w.get("parent_wbs_id", "") in wbs:  # the root node is not part of the code
                parts.append(_clean(w.get("wbs_short_name")) or _clean(w.get("wbs_name")))
            wid = w.get("parent_wbs_id", "")
        return ".".join(reversed(parts))

    def _walk(wid: str, depth: int, guard: int = 0) -> None:
        if guard > 200 or not _has_tasks(wid):
            return
        w = wbs[wid]
        code = _path(wid) or None
        raws.append(_raw(id=f"WBS:{wid}", wbs=code, name=w.get("wbs_name") or w.get("wbs_short_name") or "",
                         level=depth, hint="summary"))  # fmt: skip
        for rec in by_wbs.get(wid, []):
            rec["wbs"], rec["level"] = code, depth + 1
            raws.append(rec)
        for c in sorted(children.get(wid, []), key=_seq):
            _walk(c, depth + 1, guard + 1)

    for root in sorted(roots, key=_seq):
        if project_name is None:
            project_name = wbs[root].get("wbs_name") or None
        _walk(root, 0)
    if orphans:
        if wbs:
            warnings.append(f"{len(orphans)} activities are not under any WBS node.")
        raws.extend(orphans)
    if not wbs:
        warnings.append("The file has no WBS hierarchy (PROJWBS); activities are listed flat.")
    if not project_name and proj:
        project_name = proj.get("proj_short_name") or None
    return _finish("xer", name, sha, raws, warnings, data_date=data_date, project_name=project_name)


# ---------------------------------------------------------------------------
# MS Project XML
# ---------------------------------------------------------------------------


def _safe_xml_root(data: bytes) -> ET.Element:
    """Parse XML that carries no DTD and no entities (no expansion, no external loads)."""
    head = data[:4096]
    if head.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in head[:8]:
        text = data.decode("utf-16", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")
    low = text.lower()
    if "<!doctype" in low or "<!entity" in low:
        raise ScheduleImportError(
            "This XML file contains a DOCTYPE/entity declaration and was not opened."
        )
    try:
        from defusedxml import ElementTree as DET  # type: ignore

        return DET.fromstring(data, forbid_dtd=True)
    except ImportError:
        pass
    except Exception:
        raise ScheduleImportError("This XML file could not be read.")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise ScheduleImportError("This XML file could not be read.")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_msp(name: str, data: bytes, sha: str) -> Dict[str, Any]:
    root = _safe_xml_root(data)
    if _local(root.tag) != "Project" or "schemas.microsoft.com/project" not in root.tag:
        raise ScheduleImportError(
            "This XML file is not an MS Project export (File > Save As > XML Format)."
        )
    kids = {_local(c.tag): c for c in root if _local(c.tag) != "Tasks"}
    texts = {k: _clean(v.text) for k, v in kids.items() if len(v) == 0}
    mpd = _num(texts.get("MinutesPerDay")) or 480.0
    hpd = mpd / 60.0 if mpd > 0 else 8.0
    warnings: List[str] = []
    data_date = _iso_dt(texts.get("StatusDate"))
    if data_date is None:
        warnings.append("The file does not state a status date (Project/StatusDate).")
    tasks_el = next((c for c in root if _local(c.tag) == "Tasks"), None)
    if tasks_el is None:
        raise ScheduleImportError("This MS Project file has no tasks.")

    dur_re = re.compile(
        r"^P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
    )

    def _dur(s: str) -> Optional[float]:
        m = dur_re.match(s)
        if not m or not any(m.groups()):
            return None
        d, h, mi, se = (float(x) if x else 0.0 for x in m.groups())
        return round(d + (h + mi / 60.0 + se / 3600.0) / hpd, 4)

    raws: List[Dict[str, Any]] = []
    bad = 0
    duration_only = 0
    for t in tasks_el:
        if _local(t.tag) != "Task":
            continue
        f: Dict[str, str] = {}
        base: Dict[str, Any] = {}
        for c in t:
            ln = _local(c.tag)
            if ln == "Baseline":
                bf = {_local(x.tag): _clean(x.text) for x in c}
                if bf.get("Number") == "0":
                    base = bf
            elif len(c) == 0:
                f[ln] = _clean(c.text)
        if f.get("Null") == "1" or not f.get("Name"):
            continue
        hint = "summary" if f.get("Summary") == "1" else ("milestone" if f.get("Milestone") == "1" else None)
        phys = f.get("PhysicalPercentComplete")
        pct = _pct(phys) if phys and _num(phys) else None
        if f.get("PercentComplete") and not (phys and _num(phys)):
            duration_only += 1
        lvl = _num(f.get("OutlineLevel"))
        if phys and _num(phys) and pct is None:
            bad += 1
        raws.append(_raw(
            id=f.get("UID") or f.get("ID"), wbs=f.get("WBS") or None, name=f["Name"],
            level=int(lvl) if lvl is not None and lvl >= 0 else 0, hint=hint,
            bs=_iso_dt(base.get("Start")), bf=_iso_dt(base.get("Finish")),
            cs=_iso_dt(f.get("Start")), cf=_iso_dt(f.get("Finish")),
            as_=_iso_dt(f.get("ActualStart")), af=_iso_dt(f.get("ActualFinish")),
            pct=pct, dur=_dur(f["Duration"]) if f.get("Duration") else None,
        ))  # fmt: skip
        if len(raws) > MAX_ACTIVITIES:
            break
    if bad:
        warnings.append(f"{bad} PhysicalPercentComplete values were not numbers and were ignored.")
    if duration_only:
        warnings.append("MS Project's PercentComplete is duration-based, not physical progress; it was not "
                        "used. Activities count as complete from their actual finish dates.")
    return _finish(
        "msp_xml", name, sha, raws, warnings, data_date=data_date,
        project_name=texts.get("Title") or texts.get("Name") or None,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# Tables: Excel, CSV, PDF
# ---------------------------------------------------------------------------

_NOISE = {
    "variance", "var", "float", "slack", "remaining", "rem", "total", "free", "critical",
    "predecessor", "predecessors", "successor", "successors", "resource", "resources",
    "cost", "costs", "constraint", "deadline",
}  # fmt: skip
_QUALIFIERS = {"planned", "scheduled", "schedule", "current", "forecast", "early", "plan", "date", "revised"}
_NAME_H = {"task name", "activity name", "name", "activity", "description", "task", "title",
           "activity description", "task description", "item name", "work item"}  # fmt: skip
_ID_H = {"id", "activity id", "task id", "uid", "unique id", "task code", "activity code", "code",
         "no", "number", "item", "ref", "#", "task no", "activity no", "id number"}  # fmt: skip
_WBS_H = {"wbs", "wbs code", "wbs id", "wbs number", "outline number", "wbs no"}
_LEVEL_H = {"outline level", "outline", "indent", "indent level", "wbs level"}
_DATE_FIELDS = {"baseline_start", "baseline_finish", "current_start", "current_finish",
                "actual_start", "actual_finish"}  # fmt: skip


def _classify(header: Any) -> Optional[str]:
    """Which field a column header names, or None. Strict: no fuzzy guessing."""
    h = re.sub(r"[^a-z0-9%#\s]", " ", _clean(header).lower())
    h = re.sub(r"\s+", " ", h).strip()
    if not h:
        return None
    w = set(h.split())
    if w & _NOISE:
        return None
    base = w & {"baseline", "original", "orig", "bl", "bl0"}
    if "duration" in w or h in {"dur", "orig dur"}:
        return None if (w & {"baseline", "actual", "bl"}) else "duration"
    if "%" in h or w & {"percent", "pct", "progress"} or h == "complete":
        return None if base else "percent"
    is_s, is_f = bool(w & {"start", "begin"}), bool(w & {"finish", "end", "completion"})
    if base:
        if is_s != is_f:
            return "baseline_start" if is_s else "baseline_finish"
        return None
    if w & {"actual", "act"}:
        if is_s != is_f:
            return "actual_start" if is_s else "actual_finish"
        return None
    if is_s != is_f:
        rest = w - {"start", "begin", "finish", "end", "completion"} - _QUALIFIERS
        if rest:
            return None  # e.g. "late start": not the current schedule, not guessed
        return "current_start" if is_s else "current_finish"
    if h in _LEVEL_H:
        return "level"
    if h in {"milestone", "is milestone", "milestone y n", "milestone yes no", "ms"}:
        return "milestone"
    if h in {"type", "activity type", "task type"}:
        return "type"
    if h in {"summary", "is summary"}:
        return "summary"
    if h in _WBS_H:
        return "wbs"
    if h in _ID_H:
        return "id"
    if h in _NAME_H:
        return "name"
    return None


def _map_columns(row: List[Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, cell in enumerate(row):
        f = _classify(cell)
        if f and f not in out:
            out[f] = i
    return out


_META_DATE = re.compile(r"^(?:data|status|as[ -]?of)(?:\s*date)?\s*[:\-]?\s*(.*)$", re.I)
_META_PROJ = re.compile(r"^project(?:\s*name)?\s*[:\-]\s*(.*)$|^project name\s*(.*)$", re.I)


def _scan_meta(rows: List[List[Any]]) -> Tuple[Any, Optional[str]]:
    """(raw data-date value, project name) from labelled cells above the table."""
    dd: Any = None
    pn: Optional[str] = None
    for row in rows:
        for i, cell in enumerate(row):
            txt = _clean(cell)
            if not txt or isinstance(cell, (datetime, date)):
                continue
            m = _META_DATE.match(txt) if re.match(r"(?i)^(data date|status date|as[ -]?of)\b", txt) else None
            if m and dd is None:
                rest = m.group(1).strip()
                if rest:
                    dd = rest
                else:
                    dd = next((c for c in row[i + 1:] if _clean(c)), None)
                continue
            m = _META_PROJ.match(txt)
            if m and pn is None:
                rest = (m.group(1) or m.group(2) or "").strip()
                if not rest:
                    rest = _clean(next((c for c in row[i + 1:] if _clean(c)), ""))
                pn = rest or None
    return dd, pn


def _leading_indent(s: Any) -> int:
    if not isinstance(s, str):
        return 0
    body = s.replace(" ", " ").replace("\t", "    ")
    return len(body) - len(body.lstrip(" "))


def _table_to_raws(
    rows: List[List[Any]],
    indents: Optional[List[List[float]]],
    *,
    need_both_dates: bool,
) -> Optional[Tuple[List[Dict[str, Any]], List[str], Optional[date], Optional[str], int]]:
    """(raws, warnings, data_date, project_name, rows_with_dates) or None (no header)."""
    best: Optional[Tuple[int, Dict[str, int]]] = None
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        m = _map_columns(row)
        if "name" not in m or not (m.keys() & _DATE_FIELDS):
            continue
        if need_both_dates and not {"current_start", "current_finish"} <= m.keys():
            continue
        if best is None or len(m) > len(best[1]):
            best = (i, m)
    if best is None:
        return None
    hi, cols = best
    warnings: List[str] = []
    header = rows[hi]
    unknown = [_clean(c) for j, c in enumerate(header) if _clean(c) and j not in cols.values()]
    if unknown:
        shown = ", ".join(f'"{u[:40]}"' for u in unknown[:10])
        more = f" and {len(unknown) - 10} more" if len(unknown) > 10 else ""
        warnings.append(f"Columns not recognised and ignored: {shown}{more}.")

    body = rows[hi + 1:]
    body_ind = indents[hi + 1:] if indents else None
    date_cols = [cols[f] for f in _DATE_FIELDS if f in cols]
    meta_dd, project_name = _scan_meta(rows[:hi])
    texts = [_clean(r[c]) for r in body for c in date_cols if c < len(r) and isinstance(r[c], str)]
    if isinstance(meta_dd, str):
        texts.append(meta_dd)
    order, order_warn = _detect_order(texts)
    if order_warn:
        warnings.append(order_warn)
    data_date = _parse_date(meta_dd, order) if meta_dd is not None else None

    def cell(r: List[Any], f: str) -> Any:
        c = cols.get(f)
        return r[c] if c is not None and c < len(r) else None

    name_hdr = _clean(header[cols["name"]]).lower()
    raws: List[Dict[str, Any]] = []
    indent_of: List[float] = []
    outline: List[Optional[int]] = []
    bad_dates: Dict[str, int] = {}
    bad_pct = bad_dur = no_name = 0
    pct_plain: List[float] = []
    pct_marked = False
    for ri, r in enumerate(body):
        if not any(_clean(c) for c in r):
            continue
        raw_name = cell(r, "name")
        nm = _clean(raw_name)
        if not nm:
            no_name += 1
            continue
        if nm.lower() == name_hdr:  # a header repeated on each PDF page / print block
            continue
        rec = _raw(name=nm, id=_clean(cell(r, "id")) or None, wbs=_clean(cell(r, "wbs")) or None)
        for f, key in (("baseline_start", "bs"), ("baseline_finish", "bf"), ("current_start", "cs"),
                       ("current_finish", "cf"), ("actual_start", "as_"), ("actual_finish", "af")):  # fmt: skip
            v = cell(r, f)
            if _clean(v) == "":
                continue
            d = _parse_date(v, order)
            if d is None:
                bad_dates[f] = bad_dates.get(f, 0) + 1
            rec[key] = d
        pv = cell(r, "percent")
        if _clean(pv) != "":
            p = _pct(pv)
            if p is None:
                bad_pct += 1
            else:
                rec["pct"] = p
                if isinstance(pv, str) and "%" in pv:
                    pct_marked = True
                elif not isinstance(pv, str):
                    pct_plain.append(p)
        dv = cell(r, "duration")
        if _clean(dv) != "":
            dd = _duration_days(dv)
            if dd is None:
                bad_dur += 1
            rec["dur"] = dd
        # kind hints
        ms, ty, sm = _truthy(cell(r, "milestone")), _clean(cell(r, "type")).lower(), _truthy(cell(r, "summary"))
        if sm or "summary" in ty or ty == "wbs":
            rec["hint"] = "summary"
        elif ms or "milestone" in ty:
            rec["hint"] = "milestone"
        # level sources
        ind = _leading_indent(raw_name)
        if body_ind and ri < len(body_ind) and cols["name"] < len(body_ind[ri]):
            ind += int(round((body_ind[ri][cols["name"]] or 0) * 2))
        indent_of.append(ind)
        lv = _num(cell(r, "level"))
        outline.append(int(lv) if lv is not None and lv >= 0 else None)
        raws.append(rec)

    for f, n in bad_dates.items():
        warnings.append(f"{n} values in the {f.replace('_', ' ')} column could not be read as dates and were ignored.")
    if bad_pct:
        warnings.append(f"{bad_pct} percent complete values were not numbers and were ignored.")
    if pct_plain and not pct_marked and max(pct_plain) <= 1 and max(pct_plain) > 0:
        warnings.append(
            "The percent complete column holds plain numbers that are all 1 or less; they are read "
            "as percent as written (0.5 = 0.5%). If they are fractions, they are wrong."
        )
    if bad_dur:
        warnings.append(f"{bad_dur} duration values could not be read and were ignored.")
    if no_name:
        warnings.append(f"{no_name} rows without an activity name were ignored.")

    # Levels: outline column > indentation > dotted WBS depth.
    if any(o is not None for o in outline):
        for rec, o in zip(raws, outline):
            rec["level"] = o if o is not None else 0
    elif len(set(indent_of)) > 1:
        rank = {v: k for k, v in enumerate(sorted(set(indent_of)))}
        for rec, ind in zip(raws, indent_of):
            rec["level"] = rank[ind]
    elif any(r["wbs"] and "." in r["wbs"] for r in raws):
        for rec in raws:
            rec["level"] = len(rec["wbs"].strip(".").split(".")) - 1 if rec["wbs"] else 0
    # A row with a deeper block after it is a summary (the file's own flag wins).
    for i in range(len(raws) - 1):
        if raws[i]["hint"] is None and raws[i + 1]["level"] > raws[i]["level"]:
            raws[i]["hint"] = "summary"
    # No id column: the WBS number is the file's own identifier.
    if "id" not in cols and "wbs" in cols:
        for rec in raws:
            rec["id"] = rec["wbs"]
    dated = sum(1 for x in raws if x["cs"] or x["cf"] or x["bs"] or x["bf"])
    return raws, warnings, data_date, project_name, dated


def _parse_rows(
    fmt: str, name: str, sha: str, candidates: List[Tuple[str, Any]],
) -> Dict[str, Any]:
    """Pick the best of several (label, parsed-table) candidates and finish it."""
    best = max(candidates, key=lambda c: c[1][4])
    label, (raws, warnings, data_date, project_name, _n) = best
    if len(candidates) > 1:
        warnings.insert(0, f'Sheet "{label}" was imported; the other sheets were ignored.')
    return _finish(fmt, name, sha, raws, warnings, data_date=data_date, project_name=project_name)


def _check_zip(data: bytes) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ScheduleImportError("This file is not a valid Excel workbook.")
    infos = zf.infolist()
    if len(infos) > MAX_XLSX_PARTS or sum(i.file_size for i in infos) > MAX_XLSX_UNCOMPRESSED:
        raise ScheduleImportError("This Excel file expands to more than can be imported.")
    if "xl/workbook.xml" not in {i.filename for i in infos}:
        raise ScheduleImportError("This file is not an Excel workbook.")


def _xlsx_cell_value(c: Any) -> Any:
    v = getattr(c, "value", None)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and "%" in (getattr(c, "number_format", "") or ""):
        return f"{v * 100:.6g}%"  # a % formatted cell is the percent it shows
    return v


def _parse_xlsx(name: str, data: bytes, sha: str) -> Dict[str, Any]:
    _check_zip(data)
    try:
        import openpyxl  # type: ignore
    except ImportError:  # pragma: no cover - deployment error, not user error
        raise ScheduleImportError("Excel import is not available on this server.")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    except Exception:
        raise ScheduleImportError("This Excel file could not be read.")
    cands: List[Tuple[str, Any]] = []
    try:
        for ws in wb.worksheets[:12]:
            rows: List[List[Any]] = []
            inds: List[List[float]] = []
            empty_run = 0
            for row in ws.iter_rows():
                vals = [_xlsx_cell_value(c) for c in row]
                if not any(_clean(v) for v in vals):
                    empty_run += 1
                    if empty_run > 1000:
                        break
                else:
                    empty_run = 0
                rows.append(vals)
                try:
                    inds.append([float(getattr(c.alignment, "indent", 0) or 0) for c in row[:8]])
                except Exception:
                    inds.append([])
                if len(rows) >= MAX_ROWS:
                    break
            res = _table_to_raws(rows, inds, need_both_dates=False)
            if res is not None:
                cands.append((ws.title, res))
    finally:
        wb.close()
    if not cands:
        raise ScheduleImportError(
            "No schedule table was found in this workbook: it needs a header row with an "
            "activity/task name column and at least one date column (Start / Finish)."
        )
    return _parse_rows("xlsx", name, sha, cands)


def _parse_csv(name: str, data: bytes, sha: str) -> Dict[str, Any]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    if "\x00" in text[:2048]:
        raise ScheduleImportError("This file is not a text schedule.")
    sample = "\n".join(text.splitlines()[:50])
    if name.lower().endswith(".tsv"):
        delim = "\t"
    else:
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delim = max(",;\t|", key=sample.count)
    rows: List[List[Any]] = []
    for r in csv.reader(io.StringIO(text), delimiter=delim):
        rows.append(r)
        if len(rows) >= MAX_ROWS:
            break
    res = _table_to_raws(rows, None, need_both_dates=False)
    if res is None:
        raise ScheduleImportError(
            "No schedule table was found in this file: it needs a header row with an "
            "activity/task name column and at least one date column (Start / Finish)."
        )
    return _parse_rows("csv", name, sha, [("csv", res)])


def _parse_pdf(name: str, data: bytes, sha: str) -> Dict[str, Any]:
    try:
        import pdfplumber  # type: ignore
    except ImportError:  # pragma: no cover
        raise ScheduleImportError("PDF import is not available on this server.")
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception:
        raise ScheduleImportError(PDF_REFUSAL)
    try:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise ScheduleImportError(
                f"This PDF has more than {MAX_PDF_PAGES} pages; export the schedule to "
                "Excel/MS Project XML/P6 XER instead."
            )
        head_lines: List[List[Any]] = []
        try:
            for pg in pdf.pages[:2]:
                head_lines.extend([[ln] for ln in (pg.extract_text() or "").splitlines()[:40]])
        except Exception:
            head_lines = []
        res = None
        for settings in (None, {"vertical_strategy": "text", "horizontal_strategy": "text"}):
            rows: List[List[Any]] = []
            try:
                for pg in pdf.pages:
                    for tb in (pg.extract_tables(settings) if settings else pg.extract_tables()):
                        rows.extend([[c or "" for c in r] for r in tb])
            except Exception:
                continue
            if len(rows) > MAX_ROWS:
                rows = rows[:MAX_ROWS]
            r = _table_to_raws(rows, None, need_both_dates=True)
            if r is not None and r[4] >= MIN_PDF_ROWS:
                res = r
                break
    finally:
        pdf.close()
    if res is None:
        raise ScheduleImportError(PDF_REFUSAL)
    raws, warnings, data_date, project_name, n = res
    if data_date is None:  # the table's own header block is not in `rows`; look at the page text
        dd, pn = _scan_meta(head_lines)
        if dd is not None:
            data_date = _parse_date(dd, "mdy")
        project_name = project_name or pn
    warnings.insert(
        0,
        "This schedule was extracted from a PDF; the extraction must be confirmed by a person "
        "before it is relied on.",
    )
    return _finish("pdf", name, sha, raws, warnings, data_date=data_date, project_name=project_name,
                   confidence="extracted")  # fmt: skip


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _sniff(name: str, data: bytes) -> str:
    head = data[:2048].lstrip(b"\xef\xbb\xbf")
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if head.startswith(b"ERMHDR"):
        return "xer"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    if head.lstrip().startswith(b"<") or head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "msp_xml"
    if ext in {"mpp", "xls", "xlsb", "doc", "docx"}:
        raise ScheduleImportError(
            "This file type cannot be imported; save it as MS Project XML, Excel (.xlsx) or "
            "P6 XER and upload that."
        )
    if ext == "xer":
        return "xer"
    if ext in {"csv", "tsv", "txt"}:
        return "csv"
    raise ScheduleImportError(
        "Unsupported file. Upload a P6 XER, MS Project XML, Excel (.xlsx), CSV or a PDF schedule table."
    )


def parse_schedule(name: str, data: bytes) -> Dict[str, Any]:
    """Parse a schedule file into the normalised document (module docstring).

    Raises ScheduleImportError (message safe to show) when the file is too big,
    is not a schedule, or holds nothing usable. Never returns a partial guess.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ScheduleImportError("The file is empty.")
    data = bytes(data)
    if len(data) > MAX_BYTES:
        raise ScheduleImportError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    name = name or "schedule"
    sha = hashlib.sha256(data).hexdigest()
    fmt = _sniff(name, data)
    parser = {"xer": _parse_xer, "msp_xml": _parse_msp, "xlsx": _parse_xlsx,
              "csv": _parse_csv, "pdf": _parse_pdf}[fmt]  # fmt: skip
    try:
        return parser(name, data, sha)
    except ScheduleImportError:
        raise
    except Exception:
        raise ScheduleImportError(f"This file could not be read as a {fmt.replace('_', ' ')} schedule.")
