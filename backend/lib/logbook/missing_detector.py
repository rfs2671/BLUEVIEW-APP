"""Phase V2.0 — missing daily-log detector.

For each active project, walks the configured date range and diffs the filed
DAILY JOBSITE LOGBOOKS against the expected-workday set (Mon-Fri by default, or
every day for projects flagged `weekend_work=true`).

IT USED TO READ `db.daily_logs`, AND CALLED IT "the operator-recorded source of
truth" right here. It was not: 92 rows, all written in a fortnight in April by
"TEST" and "Roy Fishman", nothing since. Every working day on every project was
therefore diffed against an empty set and flagged -- 285 rows asserting that a
required daily log had not been filed, while the CP was filing one and signing
it. See lib/logbook/daily_jobsite_source.py for the filter and why each clause
is in it.

Both outcomes are now written:

    present  category="daily_log", status="complete"
    absent   category="daily_log", status="missing"

THE `complete` WRITE IS THE UN-FLAG PATH, AND IT DID NOT EXIST. The old loop
only ever touched the absent days: a date that was flagged on Monday and filled
on Tuesday kept its `missing` row for the life of the project, because nothing
in this file could ever look at a present day and say so. A detector that can
only accuse is not a detector.

Idempotent — the (project_id, entry_date, category) unique index makes the
upsert a no-op when the row already says the same thing. Re-running the
detector on the same day produces no duplicates.

Designed to run from the daily 3 AM ET scheduler tick AND from
ad-hoc admin endpoints. Both code paths share the same async API.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from lib.logbook.daily_jobsite_source import submitted_dates
from lib.logbook.schema import (
    CATEGORY_DAILY_LOG,
    SOURCE_AUTO_DETECTED,
    SOURCE_MANUAL,
    STATUS_COMPLETE,
    STATUS_MISSING,
    date_to_str,
    iter_expected_dates,
    str_to_date,
)

logger = logging.getLogger(__name__)


# Default lookback window for the daily detector tick — 30 days is
# generous enough to catch a project that was paused and restarted
# without re-scanning years of history. Admin-triggered runs can
# override.
DEFAULT_LOOKBACK_DAYS = 30


async def detect_missing_for_project(
    db,
    *,
    project: Dict[str, Any],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Find dates with no daily_log for one project. Writes
    logbook_entries rows for each gap. Returns the list of
    written entries (or already-present entries — read-after-
    write so the caller can render them immediately).

    `start_date` / `end_date` default to (today-LOOKBACK, yesterday).
    Today's missing log isn't a gap yet — operators typically write
    daily logs at end of day. We don't fault them at 3 AM on the
    same day.
    """
    project_id = str(project.get("_id") or project.get("id") or "")
    if not project_id:
        raise ValueError("project missing _id / id")
    company_id = str(project.get("company_id") or "")
    weekend_work = bool(project.get("weekend_work") or False)
    project_created_at = project.get("created_at")

    cur_now = now or datetime.now(timezone.utc)
    today = cur_now.date()
    if end_date is None:
        end_date = today - timedelta(days=1)
    if start_date is None:
        start_date = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    # Don't scan before project creation — every day pre-creation
    # would be flagged as "missing" which is meaningless noise.
    if isinstance(project_created_at, datetime):
        created_date = project_created_at.date()
        if start_date < created_date:
            start_date = created_date

    if start_date > end_date:
        return []

    # ── Collect the dates that already have a FILED daily jobsite log ──
    have: set = set()
    for d_str in await submitted_dates(
        db, project_id,
        start=date_to_str(start_date), end=date_to_str(end_date),
    ):
        d = str_to_date(d_str)
        if d is not None:
            have.add(d)

    # Dates a person has already ruled on, read once for the window.
    manual_dates: set = set()
    try:
        cursor = db.logbook_entries.find(
            {
                "project_id": project_id,
                "category": CATEGORY_DAILY_LOG,
                "source": SOURCE_MANUAL,
                "entry_date": {
                    "$gte": date_to_str(start_date),
                    "$lte": date_to_str(end_date),
                },
            },
            {"entry_date": 1},
        )
        async for doc in cursor:
            if doc.get("entry_date"):
                manual_dates.add(str(doc["entry_date"]))
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            f"[missing_detector] manual-row lookup failed for project={project_id}: {e!r}",
        )

    # ── Walk the expected set; record BOTH outcomes ────────────────
    written: List[Dict[str, Any]] = []
    for expected in iter_expected_dates(start_date, end_date, weekend_work=weekend_work):
        present = expected in have
        entry = {
            "company_id": company_id,
            "project_id": project_id,
            "entry_date": date_to_str(expected),
            "category": CATEGORY_DAILY_LOG,
            "status": STATUS_COMPLETE if present else STATUS_MISSING,
            "source": SOURCE_AUTO_DETECTED,
            "linked_dob_log_ids": [],
            "deficiency_reason": None,
            "attestation_data": None,
            "updated_at": cur_now,
        }
        # Upsert keyed on the unique (project_id, entry_date, category)
        # index. $setOnInsert keeps created_at stable across re-runs;
        # $set updates updated_at every tick so dashboards can show
        # "last verified".
        if entry["entry_date"] in manual_dates:
            # A HUMAN'S ROW IS NOT OVERWRITTEN. `source` exists so a manual or
            # attested entry can outrank an automatic one, and an auto-detector
            # that stamps over a person's entry is a worse defect than the one
            # this file fixes.
            #
            # SKIPPED HERE RATHER THAN FILTERED IN THE UPSERT. Adding
            # `source: {$ne: manual}` to the update filter looks tidier and is
            # wrong: the filter would not match the manual row, `upsert=True`
            # would try to INSERT a second one, and the unique index on
            # (project_id, entry_date, category) would reject it -- turning a
            # protection into a duplicate-key exception on every tick, for every
            # day anyone had ever attested by hand.
            continue
        try:
            await db.logbook_entries.update_one(
                {
                    "project_id": project_id,
                    "entry_date": entry["entry_date"],
                    "category": CATEGORY_DAILY_LOG,
                },
                {
                    "$set": {
                        **entry,
                    },
                    "$setOnInsert": {
                        "created_at": cur_now,
                        "created_by_user_id": None,
                    },
                },
                upsert=True,
            )
            written.append(entry)
        except Exception as e:
            # A race between two simultaneous detector ticks can
            # produce a transient duplicate-key error; the upsert
            # is still effectively complete (the OTHER tick won).
            # Log + continue.
            logger.warning(
                f"[missing_detector] upsert failed for project={project_id} "
                f"date={entry['entry_date']}: {e!r}",
            )

    return written


async def run_missing_detector_for_all_projects(
    db,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Cron-tick entry point. Iterates every active, non-deleted
    project and runs the missing detector with default windows.

    Returns a summary dict for telemetry / runbook visibility:

        {
          "projects_scanned": int,
          "missing_entries_written": int,
          "errors": int,
        }
    """
    summary = {
        "projects_scanned": 0,
        "missing_entries_written": 0,
        "errors": 0,
    }
    cursor = db.projects.find({
        "status": "active",
        "is_deleted": {"$ne": True},
    })
    async for project in cursor:
        summary["projects_scanned"] += 1
        try:
            written = await detect_missing_for_project(
                db, project=project, now=now,
            )
            summary["missing_entries_written"] += len(written)
        except Exception as e:
            summary["errors"] += 1
            logger.warning(
                f"[missing_detector] project failed "
                f"(_id={project.get('_id')}): {e!r}",
            )
    logger.info(
        f"[missing_detector] tick complete: {summary}",
    )
    return summary
