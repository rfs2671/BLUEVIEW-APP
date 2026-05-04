"""MR.14 commit 5 — soft-delete the 24 stranded needs_insurance renewals.

Why this exists
───────────────
The MR.13 eligibility-bypass smoke test left 24 permit_renewal docs
with status='needs_insurance' in the operator's production DB. They
were artifacts of `ELIGIBILITY_BYPASS_DAYS_REMAINING=365` (set
during MR.13 testing, never reverted) opening the 30-day renewal
window so the dispatcher would emit reminders for permits it
otherwise wouldn't have looked at. After MR.14 commit 4a removed
the bypass setting + restored the hard-coded 30-day window, those
records are stale: nothing surfaces them in the v1 monitoring UI
(the dispatcher won't re-emit them outside the 30-day window) but
they still appear in admin listing endpoints + would re-emit
reminder emails if the notification system is re-enabled.

This script soft-deletes them (sets is_deleted=true + deleted_at)
rather than hard-deleting so:
  • `db.permit_renewals.find({is_deleted: {$ne: true}})` is the
    canonical "live" view going forward.
  • An operator can audit + un-delete (set is_deleted=false) later
    if any of the 24 turn out to be legitimate.
  • Hard delete is a future operation; reversibility is the
    safer default for a one-shot cleanup.

Idempotent: target query excludes already-deleted docs. Re-runs
find zero candidates and exit clean.

Run modes
─────────
    # Dry-run — count + list. No writes. Required first step.
    python -m backend.scripts.migrate_clean_stranded_renewals --dry-run

    # Live — perform the soft-delete.
    python -m backend.scripts.migrate_clean_stranded_renewals --execute

The two modes are mutually exclusive and one is required (no
implicit-live; explicit-only).

Verification after `--execute`
───────────────────────────────
    db.permit_renewals.countDocuments({
      status: 'needs_insurance',
      is_deleted: {$ne: true},
    })
should match the renewals legitimately surfacing today (not the
24 bypass-era stragglers).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


# Targeting heuristic
# ───────────────────
# We can't perfectly identify the bypass-era stragglers without a
# created_at timestamp pre-dating MR.13's revert. The closest proxy
# is the combination of:
#   • status == 'needs_insurance' (the bypass surfaced these
#     because it disabled the time-window check);
#   • days_until_expiry > 30 (the post-revert dispatcher would not
#     have surfaced them).
# That predicate matches the 24-record cohort in the operator's prod
# DB. If you re-run this on a fresh deploy that doesn't have the
# bypass-era stragglers, target_count will be 0 and the script
# exits clean.
#
# The schema heuristic we use:
#   needs_insurance + days_until_expiry > 30 + is_deleted != true
#
# Operator should always run --dry-run first to confirm the cohort
# matches what they expect.


async def main(*, dry_run: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print(
            "ERROR: MONGO_URL and DB_NAME env vars required",
            file=sys.stderr,
        )
        return 2

    mode_label = "DRY-RUN" if dry_run else "LIVE"
    print(
        f"=== Soft-delete stranded needs_insurance renewals -- {mode_label} ===\n"
    )

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    target_query = {
        "status": "needs_insurance",
        "days_until_expiry": {"$gt": 30},
        "is_deleted": {"$ne": True},
    }

    candidates = await db.permit_renewals.count_documents(target_query)
    overall = await db.permit_renewals.count_documents(
        {"is_deleted": {"$ne": True}}
    )
    print(
        f"Stranded renewals (needs_insurance + days_until_expiry > 30): "
        f"{candidates} (out of {overall} non-deleted total)\n"
    )

    if candidates == 0:
        print("Nothing to migrate — no stranded renewals match the predicate.")
        return 0

    # Per-doc breakdown so the operator can audit before --execute.
    sample = (
        db.permit_renewals.find(
            target_query,
            {
                "_id": 1,
                "company_id": 1,
                "project_id": 1,
                "permit_dob_log_id": 1,
                "status": 1,
                "days_until_expiry": 1,
                "current_expiration": 1,
                "job_number": 1,
            },
        )
        .limit(40)
    )
    print(
        f"Sample (first 40 of {candidates} stranded renewals; "
        "company_id, days_until_expiry, current_expiration, job_number):"
    )
    async for r in sample:
        rid = str(r.get("_id"))[-8:]
        cid = str(r.get("company_id") or "")[-6:]
        d = r.get("days_until_expiry")
        cx = r.get("current_expiration") or "—"
        jn = r.get("job_number") or "—"
        print(f"  {rid}  co={cid}  days={d}  exp={cx}  job={jn}")
    if candidates > 40:
        print(f"  ... and {candidates - 40} more")
    print()

    if dry_run:
        print(
            f"DRY-RUN: would soft-delete {candidates} renewal doc(s). "
            f"Re-run with --execute to apply."
        )
        return 0

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    result = await db.permit_renewals.update_many(
        target_query,
        {
            "$set": {
                "is_deleted": True,
                "deleted_at": now,
                "deleted_reason": "mr14_5_stranded_needs_insurance_cleanup",
                "updated_at": now,
            },
        },
    )
    print(
        f"Soft-deleted: matched={result.matched_count} "
        f"modified={result.modified_count}\n"
    )
    print("Done. Verification query:")
    print(
        "  db.permit_renewals.countDocuments({"
        "status:'needs_insurance', is_deleted:{$ne:true}, "
        "days_until_expiry:{$gt:30}}) // expected 0"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Soft-delete the stranded needs_insurance renewals left "
            "behind by the MR.13 ELIGIBILITY_BYPASS_DAYS_REMAINING smoke."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="Count + list. No writes.")
    mode.add_argument("--execute", action="store_true",
                      help="Perform the soft-delete.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
