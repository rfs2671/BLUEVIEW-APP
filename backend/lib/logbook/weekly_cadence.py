"""A WEEKLY LOG IS NOT DUE EVERY DAY.

── WHAT THE CP'S SCREEN WAS DOING ──────────────────────────────────────────

The logbook list renders `required_logbooks` and asks `todayLogs[type]` for
each tile's status. That read is by DATE. `toolbox_talk` is weekly, so on every
day except the one it was filed the tile said "pending" and the completion bar
counted it against him.

MEASURED ON 588 THOMAS: 33 toolbox talks filed across 35 working days. A weekly
obligation performed five times over, because a red tile every morning is an
instruction. On 857 Prescott it is 2 filings and 8 red days out of 10 -- the
same defect with the opposite outcome, a CP who learned to ignore the tile.

The SERVER already knew better: `daily_required_logbooks` keeps weekly and
as-needed types out of the nightly deficiency sweep, on the stated reasoning
that "counting them as such invents a deficiency out of a frequency." The
screen had no equivalent.

── THE WEEK IS MONDAY TO FRIDAY ────────────────────────────────────────────

Operator ruling. A talk given any day of that week satisfies it, including on a
Saturday -- the week is when the obligation falls, not when the talk may be
given.

SATURDAY AND SUNDAY BELONG TO THE WEEK THAT PRECEDES THEM, which is what
`date.weekday()` already does (Mon=0 … Sun=6), so no arithmetic decides it.

── AND A WEEKEND WORKER RE-OPENS IT ────────────────────────────────────────

Operator ruling: a worker on site Saturday or Sunday who has not attended that
week's talk makes it due. That is the case the weekly rule would otherwise
swallow -- a crew called in on Saturday for a pour, on a week whose talk was
given on Tuesday to a different crew, is a crew nobody has spoken to.

It is deliberately NOT "anybody on site who missed the talk". A worker who
joins on Wednesday is already covered by `missing_toolbox_talk`, which lists
every uncovered worker on the project and has done since before this existed.
This rule is about whether the LOG is due again, and the operator scoped it to
the weekend.

PURE. No I/O; the caller supplies the filed dates, the covered worker ids and
the weekend attendance. That is what makes the rule testable against a calendar
rather than against a database.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: Reported on the period so a client can say WHY a weekly log is open.
NOT_FILED = "NOT_FILED_THIS_WEEK"
WEEKEND_UNCOVERED = "WEEKEND_WORKER_NOT_COVERED"


def as_date(value) -> Optional[date]:
    """A date from a date, a datetime or a 'YYYY-MM-DD' string, or None.

    TOTAL. Every caller here is reading stored data whose shape has changed
    across eras, and a cadence helper that raises would take a logbook list
    down over a malformed row on one old record.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def work_week(value) -> Optional[Tuple[date, date]]:
    """(Monday, Friday) of the Mon-Fri week this day belongs to.

    Saturday and Sunday resolve to the week BEFORE them, because
    `weekday()` numbers them 5 and 6 inside the same calendar week -- the
    weekend of a working week, not the start of the next one.
    """
    day = as_date(value)
    if day is None:
        return None
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=4)


def week_span(value) -> Optional[Tuple[str, str]]:
    """The Monday and SUNDAY of that week, as ISO strings.

    THE QUERY RANGE IS SEVEN DAYS, NOT FIVE, and the difference is the point: a
    talk given on a Saturday still satisfies the Mon-Fri obligation, so the read
    that looks for one must reach the weekend even though the period does not.
    """
    wk = work_week(value)
    if wk is None:
        return None
    monday, friday = wk
    return monday.isoformat(), (friday + timedelta(days=2)).isoformat()


def is_weekend(value) -> bool:
    day = as_date(value)
    return day is not None and day.weekday() >= 5


def toolbox_period(
    on_date,
    filed_dates: Iterable = (),
    weekend_worker_ids: Iterable = (),
    covered_worker_ids: Iterable = (),
) -> Dict:
    """Is the week's toolbox talk satisfied, and if not, why.

    `filed_dates`          dates of toolbox_talk logs, any shape as_date reads
    `weekend_worker_ids`   workers who checked in on the Sat or Sun of this week
    `covered_worker_ids`   workers named as attendees on this week's talks

    Returns the row the client renders:

        {log_type, frequency, period_start, period_end, satisfied, filed_on,
         due_reason, uncovered_weekend_workers}
    """
    wk = work_week(on_date)
    if wk is None:
        # NO DATE MEANS NO PERIOD, AND NO CLAIM. Reporting "satisfied" here
        # would tell a CP his week is done on the strength of a value nobody
        # could read; reporting "due" would invent an obligation the same way.
        return {}
    monday, friday = wk
    span_end = friday + timedelta(days=2)

    filed = sorted({
        d for d in (as_date(v) for v in (filed_dates or []))
        if d is not None and monday <= d <= span_end
    })

    weekend = {str(w) for w in (weekend_worker_ids or []) if w}
    covered = {str(w) for w in (covered_worker_ids or []) if w}
    uncovered = sorted(weekend - covered)

    if not filed:
        reason = NOT_FILED
    elif uncovered:
        # THE TALK HAPPENED AND THESE MEN WERE NOT AT IT. The week is open
        # again, and the row names them so the CP knows who he is talking to
        # rather than being told to repeat a talk he has already given.
        reason = WEEKEND_UNCOVERED
    else:
        reason = None

    return {
        "log_type": "toolbox_talk",
        "frequency": "weekly",
        "period_start": monday.isoformat(),
        "period_end": friday.isoformat(),
        "satisfied": reason is None,
        "filed_on": [d.isoformat() for d in filed],
        "due_reason": reason,
        "uncovered_weekend_workers": uncovered,
    }
