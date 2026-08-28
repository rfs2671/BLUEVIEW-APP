"""THE DAILY RECORD IS THE CP'S DAILY JOBSITE LOGBOOK.

Both compliance detectors used to read `db.daily_logs`, and
`missing_detector`'s own docstring called it "the operator-recorded source of
truth". It is not, and it never was in production: 92 rows, every one written
between 2026-04-03 and 2026-04-16 by "TEST" and "Roy Fishman", and nothing
since. It was the operator's April testing of a kiosk screen.

Meanwhile the CP files a `daily_jobsite` logbook on every working day, signs it,
and that is the document a DOB inspector asks for under §3301.2. The detectors
were reading the wrong collection for their entire life, and the consequences
ran in opposite directions:

    missing_detector   minted a `status: missing` row for every working day on
                       every project -- 285 false claims that a required daily
                       log was not filed.
    deficiency         had nothing to scan, so it found nothing, and "no
                       deficiencies" reads as CLEAN. The worse direction for a
                       compliance check to fail in.

This module is the single definition of what they read now, so the two cannot
drift apart again.

THE FILTER, and why each clause is there:

    log_type: "daily_jobsite"     the daily narrative, not the other ten types
    status: "submitted"           a DRAFT IS NOT A FILED RECORD. Counting one
                                  as present would let an unsigned draft
                                  satisfy a compliance check, which is the same
                                  class of error as the false flag.
    is_amendment: {$ne: True}     an amendment shares (project, type, date)
                                  with its locked original; it is a correction
                                  of that day, not a second filing of it
    is_deleted: {$ne: True}

NOT `is_locked`, deliberately. An END_OF_DAY log is submitted-and-unlocked
until the overnight sweep freezes it, so keying on the lock would flag every
day as missing until 3am and then silently un-flag it -- a detector whose
answer depends on what time you ask.

DAILY_LOGS IS NOT UNIONED IN. On today's data it would add nothing, and it
would carry April test rows into a compliance answer permanently. If the kiosk
daily log becomes a live product, adding it back is one clause here and nowhere
else -- which is the reason this module exists rather than two copies of a
query.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

LOG_TYPE = "daily_jobsite"


def daily_jobsite_filter(project_id: str, *, start: Optional[str] = None,
                         end: Optional[str] = None) -> Dict[str, Any]:
    """The one query. `start`/`end` are inclusive YYYY-MM-DD strings."""
    query: Dict[str, Any] = {
        "project_id": str(project_id),
        "log_type": LOG_TYPE,
        "status": "submitted",
        "is_amendment": {"$ne": True},
        "is_deleted": {"$ne": True},
    }
    if start or end:
        date_clause: Dict[str, str] = {}
        if start:
            date_clause["$gte"] = start
        if end:
            date_clause["$lte"] = end
        query["date"] = date_clause
    return query


def _joined(parts) -> str:
    return "; ".join(p for p in (str(x or "").strip() for x in parts) if p)


def as_daily_log_row(logbook: Dict[str, Any]) -> Dict[str, Any]:
    """Project a daily_jobsite logbook into the flat shape the deficiency rules
    already read.

    AN ADAPTER RATHER THAN A REWRITE, and that is a decision worth stating. The
    rule engine encodes what a DOB inspector looks for -- manpower, weather,
    trade work, sub insurance -- and every rule and every one of its tests is
    written against `daily_log.get("work_performed")` and friends. Feeding it a
    logbook document directly would not fail: every rule would simply find
    nothing and fire, turning one silent wrong answer into 285 loud ones. So the
    shape is translated in one reviewable place and the rules are untouched.

    The mappings that are not one-to-one, and why:

      worker_count        sum of the crews' `num_workers`. That is the number
                          the filed record PRINTS. `gate_num_workers` is the
                          turnstile's count and is deliberately not used here:
                          the rule asks whether the CP reported manpower, not
                          whether the gate agreed with him.
      work_performed      `general_description` -- the sentence the CP attests
                          to -- falling back to the crews' own work
                          descriptions. The rule only asks whether the trade
                          work is described at all, and a log with three crews
                          and their chips has described it.
      notes               the observations' descriptions, joined. This feeds the
                          no-work-day waiver in rule_missing_manpower, and "no
                          work" on a jobsite log is written as an observation.
      subcontractor_cards the crew rows. `company` is already the key the COI
                          rule reads first.

    `weather`, `weather_temp` and `weather_wind` keep their names -- the daily
    jobsite editor happens to store them identically -- so the weather rule
    needs no translation at all.
    """
    data = logbook.get("data") or {}
    activities = [a for a in (data.get("activities") or []) if isinstance(a, dict)]
    observations = [o for o in (data.get("observations") or []) if isinstance(o, dict)]

    worker_count = 0
    for a in activities:
        try:
            worker_count += int(a.get("num_workers") or 0)
        except (TypeError, ValueError):
            continue

    work_performed = str(data.get("general_description") or "").strip()
    if not work_performed:
        work_performed = _joined(a.get("work_description") for a in activities)

    return {
        "_id": logbook.get("_id"),
        "id": logbook.get("id"),
        "project_id": logbook.get("project_id"),
        "date": logbook.get("date"),
        "worker_count": worker_count,
        "work_performed": work_performed,
        "notes": _joined(o.get("description") for o in observations),
        "weather": data.get("weather"),
        "weather_temp": data.get("weather_temp"),
        "weather_wind": data.get("weather_wind"),
        "weather_condition": data.get("weather_condition"),
        "subcontractor_cards": [
            {
                "company": a.get("company"),
                "company_name": a.get("company"),
                "trade": a.get("trade"),
            }
            for a in activities
            if str(a.get("company") or "").strip()
        ],
        # Provenance, so a deficiency row can be traced back to the document it
        # was raised from rather than to a collection that no longer feeds this.
        "source_log_type": LOG_TYPE,
    }


async def submitted_dates(db, project_id: str, *, start: str, end: str) -> set:
    """The dates in [start, end] that have a filed daily jobsite log."""
    out = set()
    cursor = db.logbooks.find(
        daily_jobsite_filter(project_id, start=start, end=end),
        {"date": 1},
    )
    async for doc in cursor:
        d = str(doc.get("date") or "")[:10]
        if d:
            out.add(d)
    return out


async def submitted_logs(db, project_id: str, *, start: str,
                         end: Optional[str] = None) -> List[Dict[str, Any]]:
    """The filed daily jobsite logs in the window, already adapted."""
    rows: List[Dict[str, Any]] = []
    cursor = db.logbooks.find(daily_jobsite_filter(project_id, start=start, end=end))
    async for doc in cursor:
        rows.append(as_daily_log_row(doc))
    return rows
