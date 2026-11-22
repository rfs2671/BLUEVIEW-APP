"""WHAT HAPPENED ON SITE, kind of work by kind of work, as a scheduler reads it:
when each one started, how many separate visits it took, how many men, how
long it sat idle between visits -- and where the record shows time going.

Operator, 2026-11-19: a "brain" that understands the schedule so far, says
where time is being wasted, and forecasts what is left. This module is the
measured side of that: every figure here is a count of filed daily-log lines,
so a superintendent can check any of them against the logs. Nothing in it is a
forecast (lib/crew_lookahead.py) and nothing in it says WHY a gap happened --
a gap is a fact, its cause is not in the records.

THE INPUT is the crew rows the progress report already reads
(progress_report._log_activities): one row per crew per filed day, with its
company, trade, head count, work line and floors.

HOW A ROW IS COUNTED. The kinds of work are those of
progress_stages.families_of, so this module and the progress board cannot
disagree about what a line means. A row whose line names two kinds of work
("Ceiling drops, Sheet rack": framing AND drywall) gives each an EQUAL SHARE
of its men. That is an assumption, and the only one: the log does not say how
the crew split itself.

A VISIT is a stretch of worked days with no more than GAP_DAYS working days
between them. Working days are those of report_calendar (Monday to Friday,
less federal holidays, plus any other day the site was worked).

Pure: no database, no network, no model.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib import progress_stages as PS
from lib import report_calendar

#: Working days away that are still the same visit (a Friday-to-Tuesday break is not a return trip).
GAP_DAYS = 2
#: A kind of work is "on site now" when it was worked within this many working days of the end.
NOW_DAYS = 5
#: Findings need this much record behind them before they are stated.
MIN_VISITS, MIN_THIN_DAYS = 3, 5
THIN_CREW = 1.5
#: A day is "low" when the head count is under this share of the site's recent usual.
LOW_SHARE, LOW_WINDOW, LOW_MIN_USUAL = 0.5, 10, 6
_WET = ("rain", "snow", "storm", "sleet", "wind", "ice")


def _rows(rows: Iterable[Dict[str, Any]], end: Optional[date]) -> List[Dict[str, Any]]:
    return [r for r in rows if isinstance(r.get("date"), date) and (end is None or r["date"] <= end)]


def _men(r: Dict[str, Any]) -> float:
    try:
        return max(0.0, float(r.get("workers") or 0))
    except (TypeError, ValueError):
        return 0.0


def shares(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{date, family, workers, floors, company}]: the men of each row shared
    equally among the kinds of work its line names. A row that installs nothing
    (cleaning, hauling, a line no kind of work claims) is not here."""
    out: List[Dict[str, Any]] = []
    for r in _rows(rows, None):
        fams = list(dict.fromkeys(f for f, _ph in PS.families_of(r)))
        for f in fams:
            out.append({"date": r["date"], "family": f, "workers": _men(r) / len(fams),
                        "floors": tuple(r.get("floors") or ()), "company": str(r.get("company") or "")})
    return out


def daily(rows: Iterable[Dict[str, Any]], end: Optional[date] = None) -> Dict[str, Dict[date, float]]:
    """{kind of work: {day: men}} up to `end`."""
    out: Dict[str, Dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for s in shares(_rows(rows, end)):
        out[s["family"]][s["date"]] += s["workers"]
    return {k: dict(v) for k, v in out.items()}


def site_days(rows: Iterable[Dict[str, Any]], end: Optional[date] = None) -> Dict[date, float]:
    """{day: every man any crew row logged}, installing or not."""
    out: Dict[date, float] = defaultdict(float)
    for r in _rows(rows, end):
        out[r["date"]] += _men(r)
    return dict(out)


def calendar(first: date, last: date, worked: Iterable[date]) -> List[date]:
    return report_calendar.working_days(first, last, first_activity=first, worked=worked)


def _visits(days: List[date], idx: Dict[date, int]) -> List[List[date]]:
    out: List[List[date]] = []
    for d in days:
        if out and idx[d] - idx[out[-1][-1]] - 1 <= GAP_DAYS:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def runs(rows: Iterable[Dict[str, Any]], end: date) -> Dict[str, Dict[str, Any]]:
    """Per kind of work, to `end`: first and last day, days worked, worker-days,
    the usual and the largest crew, each visit, the working days it was away
    between its first and last day, and how long ago it was last here."""
    rows = _rows(rows, end)
    by = daily(rows, end)
    who: Dict[str, Counter] = defaultdict(Counter)
    for s in shares(rows):
        if s["company"]:
            who[s["family"]][s["company"]] += s["workers"]
    all_days = sorted({d for v in by.values() for d in v} | set(site_days(rows, end)))
    if not all_days:
        return {}
    cal = calendar(all_days[0], end, all_days)
    idx = {d: n for n, d in enumerate(cal)}
    recent = cal[-2 * NOW_DAYS:]
    out: Dict[str, Dict[str, Any]] = {}
    for fam in sorted(by, key=lambda f: (PS.ORDER.get(f, 99), f)):
        days = sorted(by[fam])
        crews = [by[fam][d] for d in days]
        visits = _visits(days, idx)
        span = idx[days[-1]] - idx[days[0]] + 1
        gaps = [idx[b[0]] - idx[a[-1]] - 1 for a, b in zip(visits, visits[1:])]
        since = len(cal) - 1 - idx[days[-1]]
        out[fam] = {
            "key": fam, "label": PS.LABEL.get(fam, fam), "first": days[0], "last": days[-1],
            "days": len(days), "worker_days": round(sum(crews), 1),
            "crew": round(median(crews), 1), "crew_max": round(max(crews), 1),
            "visits": [{"first": v[0], "last": v[-1], "days": len(v),
                        "worker_days": round(sum(by[fam][d] for d in v), 1)} for v in visits],
            "visit_count": len(visits), "span": span, "away": span - len(days), "longest_gap": max(gaps, default=0),
            "since_last": since, "on_site": since < NOW_DAYS,
            "last_10": round(sum(by[fam].get(d, 0.0) for d in recent), 1),
            "companies": [c for c, _n in who[fam].most_common(2)],
        }
    return out


def _d(d: date) -> str:
    return f"{d:%b} {d.day}"


def time_lost(rows: Iterable[Dict[str, Any]], end: date,
              weather: Optional[Dict[date, str]] = None) -> List[Dict[str, Any]]:
    """Where the record shows time going, largest first. Each finding is a
    count with the days behind it and one plain sentence; none names a cause.

      return_trips  a kind of work that came back MIN_VISITS or more times and
                    was away more working days than it worked
      thin_crew     worked MIN_THIN_DAYS or more days at THIN_CREW men or fewer
      no_work_days  working days inside the job with no crew on any filed log
      low_days      worked days under LOW_SHARE of the site's recent usual
                    head count, with the logged weather of the day beside them
    """
    rows = _rows(rows, end)
    out: List[Dict[str, Any]] = []
    for fam, t in runs(rows, end).items():
        if len(t["visits"]) >= MIN_VISITS and t["away"] > t["days"]:
            out.append({"kind": "return_trips", "family": fam, "size": t["away"], "visits": len(t["visits"]),
                        "days": t["days"], "span": t["span"], "away": t["away"], "worker_days": t["worker_days"],
                        "text": (f"{t['label']}: {t['days']} worked days in {len(t['visits'])} separate visits "
                                 f"between {_d(t['first'])} and {_d(t['last'])}, away {t['away']} of those "
                                 f"{t['span']} working days ({t['worker_days']:g} worker-days in all).")})
        if t["days"] >= MIN_THIN_DAYS and t["worker_days"] / t["days"] <= THIN_CREW:
            out.append({"kind": "thin_crew", "family": fam, "size": t["days"], "days": t["days"],
                        "worker_days": t["worker_days"],
                        "text": (f"{t['label']}: {t['days']} days on site for {t['worker_days']:g} worker-days, "
                                 f"about one man at a time.")})
    site = site_days(rows, end)
    worked = sorted(d for d, n in site.items() if n > 0)
    if worked:
        cal = calendar(worked[0], end, worked)
        missing = [d for d in cal if site.get(d, 0) <= 0]
        if missing:
            out.append({"kind": "no_work_days", "size": len(missing), "days": missing, "of": len(cal),
                        "text": (f"{len(missing)} of {len(cal)} working days have no crew on any filed log: "
                                 + ", ".join(_d(d) for d in missing[:12]) + ("..." if len(missing) > 12 else "") + ".")})
        low: List[Tuple[date, float, float]] = []
        for n, d in enumerate(worked):
            before = [site[x] for x in worked[max(0, n - LOW_WINDOW):n]]
            if len(before) >= 5 and median(before) >= LOW_MIN_USUAL and site[d] < LOW_SHARE * median(before):
                low.append((d, site[d], median(before)))
        if low:
            wet = [d for d, _a, _b in low if any(w in str((weather or {}).get(d) or "").lower() for w in _WET)]
            lost = sum(b - a for _day, a, b in low)
            out.append({"kind": "low_days", "size": round(lost), "days": [d for d, _a, _b in low], "wet": wet,
                        "text": (f"{len(low)} worked days had under half the usual head count of the site "
                                 f"(about {lost:.0f} worker-days below usual); the log shows rain or wind on "
                                 f"{len(wet)} of them.")})
    out.sort(key=lambda f: -float(f.get("size") or 0))
    return out


def summary(rows: Iterable[Dict[str, Any]], end: date) -> Dict[str, Any]:
    """The job in a few numbers, and its kinds of work with the most labour first."""
    rows = _rows(rows, end)
    rr = runs(rows, end)
    total = sum(t["worker_days"] for t in rr.values())
    site = site_days(rows, end)
    worked = sorted(d for d, n in site.items() if n > 0)
    per_day: Dict[date, set] = defaultdict(set)
    for s in shares(rows):
        per_day[s["date"]].add(s["family"])
    return {
        "first": worked[0] if worked else None, "last": worked[-1] if worked else None,
        "worked_days": len(worked), "worker_days_installing": round(total, 1),
        "worker_days_all": round(sum(site.values()), 1),
        "kinds_per_day": median([len(v) for v in per_day.values()]) if per_day else 0,
        "trades": sorted(({**t, "share": (t["worker_days"] / total if total else 0.0)} for t in rr.values()),
                         key=lambda t: -t["worker_days"]),
    }
