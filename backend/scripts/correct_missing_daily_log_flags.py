"""One-off: correct the missing-daily-log flags written against the wrong source.

DRY RUN BY DEFAULT. Nothing is written without --execute.

    python -m backend.scripts.correct_missing_daily_log_flags
    python -m backend.scripts.correct_missing_daily_log_flags --execute

WHAT WENT WRONG. `missing_detector` diffed the expected-workday set against
`db.daily_logs` and called it "the operator-recorded source of truth". That
collection holds 92 rows, all written in a fortnight in April by "TEST" and
"Roy Fishman", and nothing since — it was the operator's testing of a kiosk
screen. Meanwhile the CP files a `daily_jobsite` logbook and signs it. So every
expected day on every project was diffed against an empty set and flagged: 285
rows asserting a required daily log had not been filed.

It then compounded that with scope. The driver iterated
`{"status": "active", ...}`, and `projects.status` is written once at creation
and never changed, so it matched every project that ever existed — dead ones,
duplicates, one marked for deletion, and one nobody had ever worked through the
gate.

THREE OUTCOMES, and the middle one is why this is not a delete:

    complete            a signed daily_jobsite log exists for that day. The
                        flag was simply wrong.
    no_site_activity    nobody was on site: no check-in, no sign-in, no log.
                        NOT "complete" — the log was not filed, and saying it
                        was is the same false claim in the other direction.
    left standing       a crew was on site and no log was filed. A real gap,
                        and the only rows worth a customer's attention.

NOTHING IS DELETED. These rows are what the system asserted about a customer's
compliance; some were surfaced. Deleting the evidence that it made a false
claim is the wrong instinct for a compliance product, and it is the only
irreversible option here. Every touched row keeps its original status in
`superseded_status` and says why in `superseded_reason`.

IDEMPOTENT. It only ever reads rows still at status "missing", so a second run
finds only what the first left standing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from lib.logbook.daily_jobsite_source import daily_jobsite_filter  # noqa: E402
from lib.logbook.schema import (  # noqa: E402
    CATEGORY_DAILY_LOG,
    STATUS_COMPLETE,
    STATUS_MISSING,
    STATUS_NO_SITE_ACTIVITY,
)

REASON_FILED = "a signed daily jobsite log exists for this day"
REASON_NO_ACTIVITY = "no site activity: no check-in, no sign-in and no log"


async def _day_had_gate_activity(db, project_id: str, day: str) -> bool:
    """Was anyone on this project that calendar day, by either path?

    Eastern, because that is the day boundary every other date in this product
    uses and the one the entry_date string was written on. A UTC comparison
    would move a 20:00 check-in to the next day.
    """
    for coll, field in (("checkins", "check_in_time"), ("sign_ins", "timestamp")):
        try:
            hit = await db[coll].find_one(
                {
                    "project_id": project_id,
                    "$expr": {
                        "$eq": [
                            {"$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": f"${field}",
                                "timezone": "America/New_York",
                            }},
                            day,
                        ],
                    },
                },
                {"_id": 1},
            )
        except Exception as e:  # pragma: no cover
            print(f"  ! {coll} lookup failed for {project_id} {day}: {e!r}")
            # FAIL TOWARDS LEAVING THE ROW ALONE. An unreadable answer is not
            # evidence that nobody was on site, and marking a real gap as
            # phantom is the one outcome here that loses information.
            return True
        if hit:
            return True
    return False


async def run(db, execute: bool) -> Counter:
    counts: Counter = Counter()
    now = datetime.now(timezone.utc)

    cursor = db.logbook_entries.find({
        "status": STATUS_MISSING,
        "category": CATEGORY_DAILY_LOG,
    })
    async for row in cursor:
        project_id = str(row.get("project_id") or "")
        day = str(row.get("entry_date") or "")[:10]
        if not project_id or not day:
            counts["skipped_malformed"] += 1
            continue

        filed = await db.logbooks.find_one(
            {**daily_jobsite_filter(project_id, start=day, end=day)}, {"_id": 1},
        )
        if filed:
            outcome, reason = STATUS_COMPLETE, REASON_FILED
        elif not await _day_had_gate_activity(db, project_id, day):
            outcome, reason = STATUS_NO_SITE_ACTIVITY, REASON_NO_ACTIVITY
        else:
            counts["left_standing"] += 1
            print(f"  GAP  {project_id} {day}  crew on site, no log filed")
            continue

        counts[outcome] += 1
        if execute:
            await db.logbook_entries.update_one(
                {"_id": row["_id"]},
                {"$set": {
                    "status": outcome,
                    # WHAT IT USED TO SAY, kept on the row itself. The audit
                    # trail of a false compliance claim is the row, not a log
                    # line nobody will read in a year.
                    "superseded_status": row.get("status"),
                    "superseded_reason": reason,
                    "corrected_at": now,
                    "updated_at": now,
                }},
            )
    return counts


async def main_async(execute: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME must be set")
        return 2
    client = AsyncIOMotorClient(mongo_url)
    try:
        counts = await run(client[db_name], execute)
    finally:
        client.close()

    print()
    print("DRY RUN — nothing written" if not execute else "EXECUTED")
    print(f"  flipped to complete          {counts[STATUS_COMPLETE]}")
    print(f"  marked no_site_activity      {counts[STATUS_NO_SITE_ACTIVITY]}")
    print(f"  left standing (real gaps)    {counts['left_standing']}")
    if counts["skipped_malformed"]:
        print(f"  skipped, malformed row       {counts['skipped_malformed']}")
    if not execute:
        print("\n  re-run with --execute to write")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="write the corrections (default is a dry run)")
    args = ap.parse_args()
    return asyncio.run(main_async(args.execute))


if __name__ == "__main__":
    sys.exit(main())
