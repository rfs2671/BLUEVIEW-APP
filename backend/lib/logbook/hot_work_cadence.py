"""A HOT-WORK DAY IS A DATE SOMEBODY DECLARED, NOT A FLAG SOMEBODY LEFT ON.

── WHAT THE CP'S SCREEN WAS DOING ──────────────────────────────────────────

`hot_work` is declared `frequency: "as_needed"` in LOGBOOK_TYPE_REGISTRY and
was gated by one persistent project boolean, `hot_work_permitted`. Nothing
answered whether the log was DUE, so the logbook list fell back to a by-DATE
read of `todayLogs["hot_work"]`, got "pending", and the completion bar counted
it. 8 Walworth has that toggle on, so its tile read Pending every morning and
would have gone on doing so forever -- welding or no welding.

This is the same defect #611 fixed for `subcontractor_orientation`. Hot work
was deliberately left alone there because nobody had defined when a hot-work
permit log is due.

── THE OPERATOR'S RULING, AND IT IS TWO FACTS ──────────────────────────────

    "Hot work: due only on days hot work happens. CP or super toggles it on
     for that day. Dated, not persistent."

    "hot_work_permitted stays as the admin's standing permit statement (the
     FDNY permit and certificate of fitness are paper he holds). The dated
     toggle is the CP/super declaring hot work happened that day, and it's
     only available on a project where the standing field is on. No permit,
     no day."

So there are two different facts and they are not stored in one place:

  * `projects.hot_work_permitted` -- THIS SITE MAY DO HOT WORK. Standing,
    admin-set, and the registry's `conditional`: it decides whether the type
    is in the required set at all. UNCHANGED by this module.
  * a `hot_work_days` row for (project, date) -- HOT WORK IS HAPPENING ON
    THIS DAY. Dated, declared by the CP or the superintendent, and what this
    module answers about.

The standing field ALONE NEVER MAKES THE LOG DUE. That is the whole defect:
permitted is a permission, not an event, and a permission left on is not a
day's work. 8 Walworth's exact shape -- permitted true, nothing declared for
today -- is `satisfied: True` here, which is the client's word for "not due".

── WHY THIS ONE HAS A PERIOD AND THE ORIENTATION DOES NOT ──────────────────

`orientation_period` sets `period_start` / `period_end` to None on purpose,
because an as-needed log has no cadence and putting today's date there would
have been that function asserting one nobody defined.

A hot-work day IS a date. The operator's ruling is literally a date -- "due
only on days hot work happens", "dated, not persistent" -- so naming the day
on the row is reporting the declaration, not inventing a cadence. It is still
not a CADENCE: nothing here says the log recurs, and two declared days in a
week are two independent facts, not a weekly rhythm.

── AND THE DAY STOPS BEING DUE WITHOUT ANYBODY REMEMBERING ─────────────────

The row is computed for the day being shown. Tomorrow's read asks about
tomorrow's date, finds no declaration for it, and answers satisfied -- so the
tile leaves the list and the denominator on its own. NOTHING HAS TO BE
SWITCHED OFF. That is the property the persistent boolean did not have, and
implementing this ruling as a CP-settable version of the same boolean would
have reproduced the exact bug: left on, Pending forever again.

PURE. No I/O; the caller supplies the declared dates. That is what makes the
rule testable against a calendar rather than against a database.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

#: Reported on the period so a client can say WHY the hot-work log is open.
#: NOT a cadence code, and not a coverage one either: the weekly rule's reasons
#: name an elapsed period and the orientation's names people. This one names an
#: act -- somebody on site said hot work is happening today.
HOT_WORK_DECLARED = "HOT_WORK_DECLARED"


def as_days(values: Iterable) -> set:
    """A set of non-empty 'YYYY-MM-DD' strings from anything iterable.

    TOTAL, and str on purpose. The declared dates arrive from Mongo documents
    and the day under test arrives from `eastern_today()`; both are day strings
    today, and a set difference across a date and a str would report every day
    undeclared and turn a tile that appears too often into one that never
    appears at all.
    """
    out = set()
    for v in (values or []):
        if v is None:
            continue
        text = str(v).strip()
        if text:
            out.add(text)
    return out


def hot_work_period(
    on_date,
    declared_dates: Iterable = (),
    declared_by: Optional[str] = None,
) -> Dict:
    """Is the hot-work log due on `on_date`, and if so because who said so.

    `on_date`         the day being shown, 'YYYY-MM-DD'
    `declared_dates`  dates this project has an ACTIVE hot-work declaration on
    `declared_by`     the name on that declaration, for the reason line only

    Returns a row shaped like `toolbox_period`'s and `orientation_period`'s, so
    the client renders it through the same `periods` channel with no new
    payload:

        {log_type, frequency, period_start, period_end, satisfied, filed_on,
         due_reason, uncovered_weekend_workers, declared, declared_by}

    `satisfied` IS ABOUT THE DECLARATION, NOT ABOUT THE FILING. A day nobody
    declared is satisfied -- there was no hot work, so there is no log to
    file. A day somebody DID declare is never satisfied, even after the log is
    filed, and that is deliberate: `cadenceStatus` gives a log filed today the
    last word, so the tile reads Done and STAYS ON THE SCREEN for the rest of
    that day. Reporting a filed day as satisfied would make the tile vanish
    the moment the CP signed it, taking with it the door he opens a second
    hot-work log through -- and hot work is `immediate`-class, so a second
    operation that afternoon is a second discrete log, never an edit.

    `uncovered_weekend_workers` is [] because it is the weekly rule's field and
    does not apply here; the one client that reads it must not find a value in
    it that means something else. There is no `uncovered_workers` key at all --
    that is the orientation's field, this row is not about people, and an empty
    list there would read as "nobody is waiting", which is a different claim.
    """
    day = str(on_date or "").strip()
    declared = bool(day) and day in as_days(declared_dates)

    return {
        "log_type": "hot_work",
        "frequency": "as_needed",
        # THE DAY, ON BOTH ENDS. See the module note: a hot-work day is a
        # date, so naming it reports the declaration rather than asserting a
        # cadence. Start and end are the same day because the period IS the
        # day -- there is no window to be inside of.
        "period_start": day or None,
        "period_end": day or None,
        "satisfied": not declared,
        # NO FILING DATES. `filed_on` is how the weekly row shows which day in
        # the week the talk was given, and a hot-work row's period is one day
        # -- the by-date read the client already has answers it exactly.
        "filed_on": [],
        "due_reason": HOT_WORK_DECLARED if declared else None,
        "uncovered_weekend_workers": [],
        # The declaration itself, so the CP's line can say whose word the log
        # is open on. `declared` is not a second copy of `not satisfied` for
        # the reader's convenience: satisfied is the client's decision word and
        # this is the fact underneath it, and the two would come apart the day
        # a second reason to open this log is added.
        "declared": declared,
        "declared_by": (str(declared_by).strip() or None) if declared and declared_by else None,
    }
