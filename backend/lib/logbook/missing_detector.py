"""Phase V2.0 — missing daily-log detector.

For each active project, walks the configured date range and
diffs `db.daily_logs` (the operator-recorded source of truth)
against the expected-workday set (Mon-Fri by default, or every
day for projects flagged `weekend_work=true`).

Days in the expected set without a daily_logs row get a
logbook_entries upsert with:

    category="daily_log", status="missing",
    source="auto_detected"

Idempotent — the (project_id, entry_date, category) unique
index makes the upsert a no-op when the row already exists.
Re-running the detector on the same day produces no duplicates.

Designed to run from the daily 3 AM ET scheduler tick AND from
ad-hoc admin endpoints. Both code paths share the same async API.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from lib.logbook.schema import (
    CATEGORY_DAILY_LOG,
    SOURCE_AUTO_DETECTED,
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

    # ── Collect the dates that already have a daily_log ────────────
    have_dates: set = set()
    cursor = db.daily_logs.find(
        {
            "project_id": project_id,
            "is_deleted": {"$ne": True},
            "date": {
                "$gte": date_to_str(start_date),
                "$lte": date_to_str(end_date),
            },
        },
        {"date": 1},
    )
    async for doc in cursor:
        d = str_to_date(doc.get("date"))
        if d is not None:
            have_dates.add(d)

    # ── Walk the expected set; upsert missing ones ─────────────────
    written: List[Dict[str, Any]] = []
    for expected in iter_expected_dates(start_date, end_date, weekend_work=weekend_work):
        if expected in have_dates:
            continue
        entry = {
            "company_id": company_id,
            "project_id": project_id,
            "entry_date": date_to_str(expected),
            "category": CATEGORY_DAILY_LOG,
            "status": STATUS_MISSING,
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
