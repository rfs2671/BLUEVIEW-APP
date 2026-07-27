#!/usr/bin/env python3
"""Backfill account_status: null/missing -> "approved".  DRY-RUN BY DEFAULT.

Accounts created before account_status existed carry no value. require_approved
currently admits them via ALLOW_LEGACY_NULL_STATUS, which is a temporary hole:
while it is open, ANY path that creates a user without an explicit status
produces an account that bypasses the gate. This script closes the gap in the
data so that flag can be turned off.

  python backend/scripts/backfill_account_status.py            # DRY RUN
  python backend/scripts/backfill_account_status.py --apply    # writes

Requires MONGO_URL + DB_NAME, same contract as the other scripts here.

ORDER MATTERS:
  1. this script --apply                       (null -> approved)
  2. audit_account_roles.py                    (confirm 0 MISSING)
  3. flip ALLOW_LEGACY_NULL_STATUS to False    (null now fails closed)

Deliberately narrow, so it cannot cause an outage:
  • touches ONLY docs where account_status is missing or null
  • never downgrades: an explicit "pending" is LEFT ALONE, because approving a
    pending account here would silently grant access an admin never granted
  • never deletes, never touches role, company_id, or any other field
  • idempotent: a second run reports 0 candidates

NOTE the server already runs run_account_status_startup_migration() on every
boot, which performs the same {"$exists": False} -> approved update. If this
script reports candidates, that startup migration is either not running or not
reaching these docs (e.g. account_status explicitly set to null rather than
absent — $exists does not match a null-VALUED field the way absence does).
Report that rather than assuming the backfill simply had not run.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# Absent OR explicitly null. The startup migration only covers absence.
CANDIDATE_QUERY = {
    "$or": [
        {"account_status": {"$exists": False}},
        {"account_status": None},
    ],
    "is_deleted": {"$ne": True},
}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is a dry run)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    db = AsyncIOMotorClient(mongo_url)[db_name]

    total = await db.users.count_documents({"is_deleted": {"$ne": True}})
    candidates = await db.users.find(
        CANDIDATE_QUERY, {"email": 1, "role": 1, "company_id": 1},
    ).to_list(length=None)
    explicit_pending = await db.users.count_documents(
        {"account_status": "pending", "is_deleted": {"$ne": True}},
    )
    approved = await db.users.count_documents(
        {"account_status": "approved", "is_deleted": {"$ne": True}},
    )

    print("Users (non-deleted):        %d" % total)
    print("  already approved:        %d" % approved)
    print("  explicit 'pending':      %d  (LEFT ALONE — see below)" % explicit_pending)
    print("  null/missing status:     %d  <- candidates" % len(candidates))
    print()

    if candidates:
        print("Would set account_status='approved' on:")
        for u in candidates:
            print("  %-36s role=%-8s company=%s" % (
                u.get("email") or "(no email)",
                u.get("role") or "(none)",
                u.get("company_id") or "(none)",
            ))
        print()

    if explicit_pending:
        print("NOT TOUCHED: %d account(s) are explicitly 'pending'." % explicit_pending)
        print("  Those are real pending signups awaiting admin approval. This")
        print("  script will not approve them — that decision belongs to")
        print("  PATCH /admin/users/{id}/approve. If one of them is YOUR")
        print("  operator account, approve it there BEFORE enforcement ships,")
        print("  or you will 403 yourself on the newly-gated routes.")
        print()

    if not args.apply:
        print("DRY RUN — nothing written. Re-run with --apply to commit.")
        return 0

    if not candidates:
        print("Nothing to do.")
        return 0

    res = await db.users.update_many(
        CANDIDATE_QUERY, {"$set": {"account_status": "approved"}},
    )
    print("APPLIED: matched=%d modified=%d" % (res.matched_count, res.modified_count))

    remaining = await db.users.count_documents(CANDIDATE_QUERY)
    print("Remaining null/missing after write: %d" % remaining)
    if remaining:
        print("  NON-ZERO — do NOT flip ALLOW_LEGACY_NULL_STATUS yet.")
        return 1
    print("\nNext: run audit_account_roles.py to confirm, then flip")
    print("ALLOW_LEGACY_NULL_STATUS to False so null fails closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
