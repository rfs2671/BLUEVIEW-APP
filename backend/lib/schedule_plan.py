"""Plan versus actual, from an imported schedule document, and nothing more.

`assess(doc, period_start=, period_end=)` takes the normalised document of
lib/schedule_import.py and returns only facts the schedule FILE itself
supports, to be shown beside what the daily logs report. It never works out
how much of the building is done, and never says why anything is late.

The rules (each is a test):

  * No physical-completion percentage is ever computed -- not from dates, not
    from counts, not from manpower, logs or photos. `project.reported_percent`
    is the percent_complete of the project summary row when the FILE has one
    (a single level-0 summary row that has rows beneath it) and that row
    carries a percent; otherwise None. Activity percents are never averaged.
    A group's percent is its own summary row's reported percent, else None.
    A percent belongs to the file and `as_of` (its data date); with no data
    date a limitation says it cannot be dated.
  * `counts` are counts of ACTIVITIES (every non-summary row, milestones
    included), never a percent of work: complete = has an actual finish or a
    reported 100%; in_progress = has an actual start, not complete; the rest
    not_started. `groups` and `floors` carry the same counts.
  * `as_of` = the file's data date. `stale_days` = period_end - data_date in
    days (positive: the schedule is older than the period's end). With no data
    date nothing is said to be overdue: dated-before-period-end milestones that
    are not complete go to "unconfirmed" (the file has no status for them).
  * Milestones (kind == "milestone"), each shown once:
      completed_in_period  actual_finish inside [period_start, period_end]
      overdue              not complete, due < min(period_end, data_date)
      unconfirmed          not complete, min(period_end, data_date) <= due <=
                           period_end -- the file's status stops at its data
                           date, so it cannot say whether these happened
      upcoming             not complete, due in (period_end, period_end + 30d]
    where due = current_finish, else baseline_finish (never invented).
  * project baseline_finish = the latest baseline_finish, forecast_finish = the
    latest current_finish / actual_finish, over non-summary activities; the
    project summary row's own values win where it has them. variance_days is
    given only when both come from the file (forecast - baseline, days). If
    baseline dates cover only some activities, a limitation says so.
  * scheduled_in_period: non-summary activities whose current dates (else
    baseline dates when there are no current dates) overlap the period; at
    most 25, earliest start first. A side-by-side with the logs, not a claim
    that the work happened.
  * deviations: only where the file itself shows it, >= 7 days:
      finish_slip            current_finish (else actual_finish) later than
                             baseline_finish
      finish_slip_milestone  the same, for a milestone
      late_start             actual_start later than baseline_start
    the 8 largest. No cause, ever.
  * groups: top-level summary rows (children of the project row when there is
    one) that contain activities; percent only if that row reports one.
  * floors: only when >= 3 activities carry exactly one floor token in the NAME
    (floor 3, fl 3, 3rd floor, level 3, L3); a name with two different floors
    ("floor 3 and 4", "floors 3-5") is skipped. Counts only, never percent.
  * limitations: plain-English reasons something is omitted or weak (no data
    date, no baseline, no reported percent, PDF-extracted, stale, nothing
    dated). `usable` is False when there is no dated non-summary activity.

Outputs hold `datetime.date` objects (not strings); `to_jsonable()` turns
them into ISO strings for storage. Input dates are ISO strings.

Pure: no I/O.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

#: A slip smaller than this many days is not reported as a deviation.
DEVIATION_MIN_DAYS = 7
#: How far past the period's end a milestone still counts as "upcoming".
UPCOMING_DAYS = 30
MAX_SCHEDULED = 25
MAX_DEVIATIONS = 8
MAX_GROUPS = 12
MIN_FLOOR_ACTIVITIES = 3
#: A data date this many days (or more) before period_end is called stale.
STALE_DAYS = 7
#: A data date this far before today may mean the file was superseded.
OLD_FOR_TODAY_DAYS = 14


def _d(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    if isinstance(v, str) and len(v) >= 10:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def to_jsonable(obj: Any) -> Any:
    """`obj` with every date as an ISO string (dicts, lists and tuples walked)."""
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def _complete(a: Dict[str, Any]) -> bool:
    return bool(a.get("actual_finish")) or a.get("percent_complete") == 100


def _in_progress(a: Dict[str, Any]) -> bool:
    return not _complete(a) and bool(a.get("actual_start"))


def _any_date(a: Dict[str, Any]) -> bool:
    return any(
        a.get(k) for k in ("baseline_start", "baseline_finish", "current_start",
                           "current_finish", "actual_start", "actual_finish")
    )  # fmt: skip


def _counts(acts: List[Dict[str, Any]]) -> Dict[str, int]:
    c = sum(1 for a in acts if _complete(a))
    p = sum(1 for a in acts if _in_progress(a))
    return {"activities": len(acts), "complete": c, "in_progress": p, "not_started": len(acts) - c - p}


def _project_row(acts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The single level-0 summary row that has rows beneath it, if the file has one."""
    top = [a for a in acts if a.get("level", 0) == 0]
    if len(top) == 1 and top[0].get("kind") == "summary" and len(acts) > 1:
        return top[0]
    return None


_FLOOR_PATTERNS = [
    re.compile(r"(?<![A-Za-z])(?:floor|flr|fl|level|lvl|lv)\.?\s*#?\s*(\d{1,2})(?!\d)(?!\s*(?:[-–,&/]|to\b|and\b)\s*\d)", re.I),
    re.compile(r"(?<![A-Za-z0-9])(\d{1,2})(?:st|nd|rd|th)?\s*(?:floor|flr|fl)\b(?!s)", re.I),
    re.compile(r"(?<![A-Za-z0-9])L(\d{1,2})(?![A-Za-z0-9])"),
]  # fmt: skip


def _floor_of(name: str) -> Optional[int]:
    found = {int(m.group(1)) for p in _FLOOR_PATTERNS for m in p.finditer(name or "")}
    found = {f for f in found if 0 <= f <= 99}
    return next(iter(found)) if len(found) == 1 else None


def _milestone_item(a: Dict[str, Any], when: Optional[date]) -> Dict[str, Any]:
    return {
        "id": a.get("id"), "name": a.get("name"), "wbs": a.get("wbs"), "date": when,
        "baseline_finish": _d(a.get("baseline_finish")), "current_finish": _d(a.get("current_finish")),
        "actual_finish": _d(a.get("actual_finish")),
    }  # fmt: skip


def _span(a: Dict[str, Any]) -> Optional[Tuple[date, date]]:
    """The (start, finish) a row is scheduled for: current dates, else baseline."""
    for s_key, f_key in (("current_start", "current_finish"), ("baseline_start", "baseline_finish")):
        s, f = _d(a.get(s_key)), _d(a.get(f_key))
        if s or f:
            s, f = s or f, f or s  # one date: a point in time
            assert s is not None and f is not None
            return (s, f) if s <= f else (f, s)
    return None


def assess(
    doc: Dict[str, Any],
    *,
    period_start: date,
    period_end: date,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Facts the schedule file supports for the period (module docstring).

    `today` only feeds one limitation (a data date long before today).
    """
    all_acts: List[Dict[str, Any]] = list(doc.get("activities") or [])
    acts = [a for a in all_acts if a.get("kind") != "summary"]
    data_date = _d(doc.get("data_date"))
    stale = (period_end - data_date).days if data_date else None
    limits: List[str] = []
    out: Dict[str, Any] = {
        "as_of": data_date,
        "stale_days": stale,
        "usable": False,
        "limitations": limits,
        "project": {"baseline_finish": None, "forecast_finish": None, "variance_days": None,
                    "reported_percent": None},  # fmt: skip
        "counts": {"activities": 0, "complete": 0, "in_progress": 0, "not_started": 0},
        "milestones": {"completed_in_period": [], "upcoming": [], "overdue": [], "unconfirmed": []},
        "scheduled_in_period": [],
        "deviations": [],
        "groups": [],
        "floors": [],
    }
    if not any(_any_date(a) for a in acts):
        limits.append("The imported schedule has no dated activities, so no schedule facts are shown.")
        return out
    out["usable"] = True

    if doc.get("confidence") == "extracted":
        limits.append(
            "This schedule was extracted from a PDF and has not been verified; "
            "a person must confirm it before it is relied on."
        )
    if data_date is None:
        limits.append(
            "The schedule file does not state a status/data date, so what is overdue or "
            "behind cannot be determined and any reported percent cannot be dated."
        )
    else:
        if stale is not None and stale >= STALE_DAYS:
            limits.append(
                f"The schedule's data date ({data_date.isoformat()}) is {stale} days before the "
                "end of this period; the file says nothing about progress after it."
            )
        elif stale is not None and stale < 0:
            limits.append(
                f"The schedule's data date ({data_date.isoformat()}) is after the end of this period."
            )
        if today and (today - data_date).days >= OLD_FOR_TODAY_DAYS:
            limits.append(
                f"The schedule's data date is {(today - data_date).days} days before today; a "
                "newer schedule may exist."
            )

    n_base = sum(1 for a in acts if a.get("baseline_finish") or a.get("baseline_start"))
    if n_base == 0:
        limits.append(
            "The schedule file has no baseline/original plan dates, so slippage against "
            "the original plan is not shown."
        )
    elif n_base < len(acts) * 0.9:
        limits.append(
            f"Baseline dates are present for only {n_base} of {len(acts)} activities; slippage "
            "is shown only for those."
        )
    if not any(a.get("percent_complete") is not None for a in all_acts):
        limits.append("The schedule file reports no percent complete, so none is shown.")

    # --- project -------------------------------------------------------
    proj_row = _project_row(all_acts)
    base_f = max((d for d in (_d(a.get("baseline_finish")) for a in acts) if d), default=None)
    fore_f = max(
        (d for a in acts for d in (_d(a.get("current_finish")), _d(a.get("actual_finish"))) if d),
        default=None,
    )
    reported: Optional[float] = None
    if proj_row is not None:
        base_f = _d(proj_row.get("baseline_finish")) or base_f
        fore_f = _d(proj_row.get("current_finish")) or _d(proj_row.get("actual_finish")) or fore_f
        reported = proj_row.get("percent_complete")
    if reported is not None and data_date is None:
        pass  # the limitation above already says it cannot be dated
    out["project"] = {
        "baseline_finish": base_f,
        "forecast_finish": fore_f,
        "variance_days": (fore_f - base_f).days if base_f and fore_f else None,
        "reported_percent": reported,
    }

    out["counts"] = _counts(acts)

    # --- milestones ----------------------------------------------------
    cutoff = min(period_end, data_date) if data_date else None
    horizon = period_end + timedelta(days=UPCOMING_DAYS)
    ms = out["milestones"]
    for a in acts:
        if a.get("kind") != "milestone":
            continue
        if _complete(a):
            af = _d(a.get("actual_finish"))
            if af and period_start <= af <= period_end:
                ms["completed_in_period"].append(_milestone_item(a, af))
            continue
        due = _d(a.get("current_finish")) or _d(a.get("baseline_finish"))
        if due is None:
            continue
        if cutoff is not None and due < cutoff:
            ms["overdue"].append(_milestone_item(a, due))
        elif due <= period_end:
            ms["unconfirmed"].append(_milestone_item(a, due))
        elif due <= horizon:
            ms["upcoming"].append(_milestone_item(a, due))
    for lst in ms.values():
        lst.sort(key=lambda m: (m["date"], str(m["name"])))

    # --- scheduled in the period --------------------------------------
    sched = []
    for a in acts:
        span = _span(a)
        if span and span[0] <= period_end and span[1] >= period_start:
            sched.append({
                "id": a.get("id"), "name": a.get("name"), "wbs": a.get("wbs"),
                "start": span[0], "finish": span[1], "percent_complete": a.get("percent_complete"),
            })  # fmt: skip
    sched.sort(key=lambda s: (s["start"], s["finish"], str(s["name"])))
    out["scheduled_in_period"] = sched[:MAX_SCHEDULED]

    # --- deviations ----------------------------------------------------
    devs: List[Dict[str, Any]] = []
    for a in acts:
        is_ms = a.get("kind") == "milestone"
        bf, cf = _d(a.get("baseline_finish")), _d(a.get("current_finish")) or _d(a.get("actual_finish"))
        if bf and cf and (cf - bf).days >= DEVIATION_MIN_DAYS:
            devs.append({"id": a.get("id"), "name": a.get("name"),
                         "kind": "finish_slip_milestone" if is_ms else "finish_slip",
                         "baseline": bf, "current": cf, "days": (cf - bf).days})  # fmt: skip
        bs, ast = _d(a.get("baseline_start")), _d(a.get("actual_start"))
        if not is_ms and bs and ast and (ast - bs).days >= DEVIATION_MIN_DAYS:
            devs.append({"id": a.get("id"), "name": a.get("name"), "kind": "late_start",
                         "baseline": bs, "current": ast, "days": (ast - bs).days})  # fmt: skip
    devs.sort(key=lambda x: (-x["days"], str(x["name"])))
    out["deviations"] = devs[:MAX_DEVIATIONS]

    # --- groups: top-level summary rows and the activities under them ---
    group_level = 1 if proj_row is not None else 0
    groups: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for a in all_acts:
        lvl = a.get("level", 0)
        if a.get("kind") == "summary":
            if lvl <= group_level:
                if cur is not None and cur["_members"]:
                    groups.append(cur)
                cur = {"name": a.get("name"), "percent": a.get("percent_complete"), "_members": []} \
                    if lvl == group_level else None
            continue
        if cur is not None:
            cur["_members"].append(a)
    if cur is not None and cur["_members"]:
        groups.append(cur)
    for g in groups[:MAX_GROUPS]:
        c = _counts(g.pop("_members"))
        out["groups"].append({"name": g["name"], "percent": g["percent"],
                              "complete": c["complete"], "total": c["activities"]})  # fmt: skip

    # --- floors --------------------------------------------------------
    by_floor: Dict[int, List[Dict[str, Any]]] = {}
    for a in acts:
        f = _floor_of(a.get("name") or "")
        if f is not None:
            by_floor.setdefault(f, []).append(a)
    if sum(len(v) for v in by_floor.values()) >= MIN_FLOOR_ACTIVITIES:
        out["floors"] = [
            {"floor": f, "complete": sum(1 for a in v if _complete(a)), "total": len(v)}
            for f, v in sorted(by_floor.items())
        ]
    return out
