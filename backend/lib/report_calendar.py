"""The working-day basis of a progress report: which days could the site
have been worked.

THE DEFECT THIS REPLACES. The period report counted "possible working days"
as every weekday up to today (plus any weekend day somebody worked). A
holiday therefore read as a day the site did not work, a month before the
job started counted as days missed, and a report for last quarter said
"worked 41 of 64 days" with no basis a lender could check. A number a reader
cannot reproduce is a number they discount.

THE RULE. A day is a *working day* when it is Monday to Friday, is not a U.S.
federal holiday (observed on the weekday the federal calendar moves it to),
and falls on or after the first day anything was recorded on the job (its
first gate check-in or filed daily log) and on or before the report's last
day or today, whichever is earlier. Any day on which the site WAS worked
counts as possible regardless (a Saturday pour, a holiday shift).

This is a stated basis, not a legal holiday calendar: NYC construction on a
holiday is allowed only under an after-hours variance, which is why holidays
are left out of the denominator, but a project that works them still gets
them counted. The report prints the basis in its footnote ("weekdays,
excluding U.S. federal holidays, from the first recorded activity") so a
reader can re-derive the figure.

Pure: no I/O.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Set

BASIS_NOTE = "weekdays, excluding U.S. federal holidays, from the first recorded activity"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th `weekday` (Mon=0) of the month."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """A fixed-date federal holiday on a weekend is observed on the nearest
    weekday (Saturday -> Friday, Sunday -> Monday)."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def holidays(year: int) -> Dict[date, str]:
    """The U.S. federal holidays observed in `year`, {date: name}. The
    observed date of a holiday that falls on the next year's first weekend
    (Jan 1 on a Saturday is observed Dec 31) belongs to the year it lands in,
    so `holidays_between` reads three years."""
    out: Dict[date, str] = {}

    def put(d: date, name: str) -> None:
        out[d] = name

    put(_observed(date(year, 1, 1)), "New Year's Day")
    put(_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day")
    put(_nth_weekday(year, 2, 0, 3), "Presidents' Day")
    put(_last_weekday(year, 5, 0), "Memorial Day")
    put(_observed(date(year, 6, 19)), "Juneteenth")
    put(_observed(date(year, 7, 4)), "Independence Day")
    put(_nth_weekday(year, 9, 0, 1), "Labor Day")
    put(_nth_weekday(year, 10, 0, 2), "Columbus Day")
    put(_observed(date(year, 11, 11)), "Veterans Day")
    put(_nth_weekday(year, 11, 3, 4), "Thanksgiving")
    put(_observed(date(year, 12, 25)), "Christmas Day")
    return out


def holidays_between(start: date, end: date) -> Dict[date, str]:
    out: Dict[date, str] = {}
    for y in range(start.year - 1, end.year + 2):
        out.update(holidays(y))
    return {d: n for d, n in out.items() if start <= d <= end}


def working_days(start: date, end: date, *, first_activity: Optional[date] = None,
                 worked: Iterable[date] = ()) -> List[date]:
    """The days the site could have been worked in [start, end]: weekdays
    that are not federal holidays, on or after `first_activity` (when known),
    plus every day in `worked` inside the range."""
    if end < start:
        return []
    lo = max(start, first_activity) if first_activity else start
    hol = holidays_between(lo, end) if lo <= end else {}
    days: Set[date] = set()
    d = lo
    while d <= end:
        if d.weekday() < 5 and d not in hol:
            days.add(d)
        d += timedelta(days=1)
    days.update(w for w in worked if start <= w <= end)
    return sorted(days)


def holiday_names(start: date, end: date) -> List[str]:
    """"Labor Day (Sep 7)" for each holiday in the range, for the footnote."""
    return [f"{n} ({d.strftime('%b')} {d.day})"
            for d, n in sorted(holidays_between(start, end).items()) if d.weekday() < 5]
