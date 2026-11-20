"""THE NEXT WEEK'S CREWS, forecast from the job's own record -- and SCORED
against that record before anybody is shown a range.

Operator, 2026-11-19: forecasts must be right "over 90%". A single number is
never right nine times in ten; a RANGE can be, and whether it is can be
measured. So this module does two things and the second is the point:

  predict(rows, as_of)   for each kind of work on site lately, the worker-days
                         expected over the next HORIZON working days, with the
                         range that should hold the real figure TARGET of the
                         time
  score(rows, end)       replays the job: stands on each past week knowing only
                         the days before it, makes that forecast, and counts
                         how often the range held what then happened

HOW THE RANGE IS MADE (no model, no tuning to this job). The expected figure
is the recent pace: the average men per working day over the last five working
days (weight 0.6) and the five before (weight 0.4), times the horizon. The
range comes from this job's own past misses: every earlier forecast whose week
has fully passed gives one miss, (actual - expected) / sqrt(expected + 1), and
the range is the band that held all but the largest and smallest
(1 - TARGET) / 2 of them. Fewer than MIN_MISSES past misses: no range at all,
and the forecast says so. A range is only ever built from days before the day
it is made on -- tests/test_crew_lookahead.py pins that the future cannot leak.

WHAT IT DOES NOT SEE. A kind of work that has not been on site in the last
LOOKBACK working days gets no forecast: one job's record cannot say when the
next trade will arrive. score() counts the labour that turned up from such
trades (`unseen`) so the blind spot has a size.

THE SCORE IS A MEASUREMENT WITH ITS OWN ERROR. `floor` is the 95% lower
confidence bound (Clopper-Pearson) on the true hit rate given the hits and
tries counted: 54 of 60 is a 90% rate that could honestly be 81%. It takes
29 tries with no miss before the floor reaches 90%.

Pure: no database, no network, no model.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib import progress_stages as PS
from lib import report_calendar
from lib import site_history as SH

HORIZON = 5
LOOKBACK = 10
TARGET = 0.90
MIN_MISSES = 30
RECENT_WEIGHT = 0.6


def window(as_of: date, horizon: int = HORIZON) -> List[date]:
    """The next `horizon` working days after `as_of` (weekdays, less federal
    holidays: nothing is known about a Saturday that has not happened)."""
    out: List[date] = []
    d = as_of
    while len(out) < horizon:
        d += timedelta(days=1)
        if report_calendar.working_days(d, d):
            out.append(d)
    return out


def _pace(series: Dict[date, float], cal: List[date], n: int) -> float:
    """Men per working day at cal[n]: the last five working days and the five before."""
    last = cal[max(0, n - 4):n + 1]
    prev = cal[max(0, n - 9):max(0, n - 4)]
    a = sum(series.get(d, 0.0) for d in last) / len(last)
    b = sum(series.get(d, 0.0) for d in prev) / len(prev) if prev else a
    return RECENT_WEIGHT * a + (1.0 - RECENT_WEIGHT) * b


def _active(series: Dict[date, float], cal: List[date], n: int) -> bool:
    return any(series.get(d, 0.0) > 0 for d in cal[max(0, n - LOOKBACK + 1):n + 1])


def _actual(series: Dict[date, float], after: date, to: date) -> float:
    return sum(v for d, v in series.items() if after < d <= to)


def _misses(by: Dict[str, Dict[date, float]], cal: List[date], n: int, horizon: int) -> List[float]:
    """Every past forecast's scaled miss whose whole week is on or before cal[n]."""
    out: List[float] = []
    for m in range(LOOKBACK - 1, n):
        win = window(cal[m], horizon)
        if win[-1] > cal[n]:
            break
        for series in by.values():
            if _active(series, cal, m):
                exp = horizon * _pace(series, cal, m)
                out.append((_actual(series, cal[m], win[-1]) - exp) / math.sqrt(exp + 1.0))
    return out


def _band(misses: List[float], target: float) -> Optional[Tuple[float, float]]:
    """The band holding `target` of the past misses, with the finite-sample
    correction of a conformal interval; None when there are too few."""
    n = len(misses)
    if n < MIN_MISSES:
        return None
    tail = (1.0 - target) / 2.0
    lo_rank = math.floor(tail * (n + 1))
    hi_rank = math.ceil((1.0 - tail) * (n + 1))
    if lo_rank < 1 or hi_rank > n:
        return None
    z = sorted(misses)
    return z[lo_rank - 1], z[hi_rank - 1]


def predict(rows: Iterable[Dict[str, Any]], as_of: date, *, horizon: int = HORIZON,
            target: float = TARGET) -> Dict[str, Any]:
    """The forecast made ON `as_of` from the rows of that day and before."""
    rows = [r for r in rows if isinstance(r.get("date"), date) and r["date"] <= as_of]
    by = SH.daily(rows, as_of)
    days = sorted({d for s in by.values() for d in s} | set(SH.site_days(rows, as_of)))
    win = window(as_of, horizon)
    out: Dict[str, Any] = {"as_of": as_of, "from": win[0], "to": win[-1], "horizon": horizon, "target": target,
                           "trades": [], "misses": 0, "ranged": False}
    if not days:
        return out
    cal = SH.calendar(days[0], as_of, days)
    n = len(cal) - 1
    misses = _misses(by, cal, n, horizon)
    band = _band(misses, target)
    out["misses"], out["ranged"] = len(misses), band is not None
    for fam in sorted(by, key=lambda f: (PS.ORDER.get(f, 99), f)):
        series = by[fam]
        if not _active(series, cal, n):
            continue
        exp = horizon * _pace(series, cal, n)
        t = {"key": fam, "label": PS.LABEL.get(fam, fam), "expected": round(exp, 1), "low": None, "high": None,
             "per_day": round(exp / horizon, 1)}
        if band:
            s = math.sqrt(exp + 1.0)
            t["low"], t["high"] = round(max(0.0, exp + band[0] * s), 1), round(max(0.0, exp + band[1] * s), 1)
        out["trades"].append(t)
    return out


def lower_bound(hits: int, tries: int, confidence: float = 0.95) -> float:
    """The lowest true hit rate that `hits` of `tries` still fits at `confidence` (Clopper-Pearson)."""
    if tries <= 0 or hits <= 0:
        return 0.0
    if hits > tries:
        hits = tries
    alpha = 1.0 - confidence

    def at_least(p: float) -> float:          # P(X >= hits) for X ~ Binomial(tries, p)
        return sum(math.comb(tries, k) * p ** k * (1.0 - p) ** (tries - k) for k in range(hits, tries + 1))
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if at_least(mid) < alpha:
            lo = mid
        else:
            hi = mid
    return lo


def score(rows: Iterable[Dict[str, Any]], end: date, *, horizon: int = HORIZON,
          target: float = TARGET) -> Dict[str, Any]:
    """Replay: one forecast every `horizon` working days (weeks that do not
    overlap), each made from the days before it only, checked against the
    week that followed. Only weeks that ended on or before `end` are scored."""
    rows = [r for r in rows if isinstance(r.get("date"), date) and r["date"] <= end]
    by = SH.daily(rows, end)
    days = sorted({d for s in by.values() for d in s} | set(SH.site_days(rows, end)))
    res: Dict[str, Any] = {"horizon": horizon, "target": target, "tries": 0, "hits": 0, "rate": None, "floor": None,
                           "weeks": 0, "unranged": 0, "width": None, "miss_share": None, "unseen": 0.0,
                           "labour": 0.0, "by_trade": {}, "cases": []}
    if not days:
        return res
    cal = SH.calendar(days[0], end, days)
    stops: List[date] = []
    n = len(cal) - 1
    while n >= LOOKBACK - 1:
        if window(cal[n], horizon)[-1] <= end:
            stops.append(cal[n])
            n -= horizon
        else:
            n -= 1
    widths: List[float] = []
    errs: List[float] = []
    for as_of in sorted(stops):
        f = predict(rows, as_of, horizon=horizon, target=target)
        seen = {t["key"] for t in f["trades"]}
        res["labour"] += sum(_actual(s, as_of, f["to"]) for s in by.values())
        res["unseen"] += sum(_actual(s, as_of, f["to"]) for k, s in by.items() if k not in seen)
        if not f["ranged"]:
            res["unranged"] += len(f["trades"])
            continue
        res["weeks"] += 1
        for t in f["trades"]:
            actual = _actual(by[t["key"]], as_of, f["to"])
            hit = t["low"] <= actual <= t["high"]
            res["tries"] += 1
            res["hits"] += int(hit)
            bt = res["by_trade"].setdefault(t["key"], {"label": t["label"], "tries": 0, "hits": 0})
            bt["tries"] += 1
            bt["hits"] += int(hit)
            widths.append(t["high"] - t["low"])
            errs.append(abs(actual - t["expected"]))
            res["cases"].append({"as_of": as_of, "key": t["key"], "expected": t["expected"], "low": t["low"],
                                 "high": t["high"], "actual": round(actual, 1), "hit": hit})
    if res["tries"]:
        res["rate"] = res["hits"] / res["tries"]
        res["floor"] = lower_bound(res["hits"], res["tries"])
        res["width"] = median(widths)
        res["miss_share"] = median(errs)
    return res
