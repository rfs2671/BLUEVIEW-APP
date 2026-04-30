"""One-shot migration — provision indexes on the filing_jobs
collection introduced in MR.6.

Why this exists
───────────────
MR.6 adds a new top-level collection `filing_jobs` (cloud-side state
machine for queued/in-flight DOB NOW filings; see backend/server.py
for FilingJob / FilingJobStatus / FilingJobEvent). The collection is
created implicitly by the first insert from the enqueue endpoint,
but the access patterns benefit from explicit indexes BEFORE
production traffic lands:

  1. (permit_renewal_id, status)
       — Dedup gate at enqueue time; list-jobs-for-renewal endpoint.
  2. (company_id, status)
       — Tenant scoping in the admin observability surface.
  3. (claimed_by_worker_id, claimed_at)
       — Stale-claim watchdog scan (every 5 min).
  4. (status, created_at)
       — Default sort path for /api/admin/filing-jobs.

All four are non-unique compound indexes; the natural _id is the
primary key already. We don't add a unique index on permit_renewal_id
because dedup is enforced at the application layer (a renewal can
have multiple terminal-status jobs over time — the dedup check
filters on non-terminal status).

Run modes
─────────
    # Dry-run — show what indexes WOULD be created. No writes. Required.
    python scripts/migrate_filing_jobs_init.py --dry-run

    # Live — actually create the indexes. Required.
    python scripts/migrate_filing_jobs_init.py --execute

Idempotent: create_index is a no-op when the index already exists,
so re-runs are safe. Same env-var contract as the other migration
scripts: MONGO_URL + DB_NAME required.
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


# Compound indexes (name, key-spec). Names are explicit so the
# migration is reversible (drop_index by name without re-deriving).
FILING_JOBS_INDEXES = [
    # 1. Dedup + per-renewal listing.
    (
        "permit_renewal_id_status_idx",
        [("permit_renewal_id", 1), ("status", 1)],
    ),
    # 2. Tenant scoping for admin filtering by company_id.
    (
        "company_id_status_idx",
        [("company_id", 1), ("status", 1)],
    ),
    # 3. Stale-claim watchdog scans by worker + claim time.
    (
        "claimed_by_worker_id_claimed_at_idx",
        [("claimed_by_worker_id", 1), ("claimed_at", 1)],
    ),
    # 4. Default sort path for admin observability list.
    (
        "status_created_at_idx",
        [("status", 1), ("created_at", -1)],
    ),
]


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
    print(f"=== Migrate filing_jobs indexes — {mode_label} ===\n")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Show what's already there. Helpful when an operator runs the
    # migration twice and wants to confirm idempotency.
    try:
        existing = await db.filing_jobs.index_information()
    except Exception as e:  # collection might not exist yet
        existing = {}
        print(f"(filing_jobs index_information unavailable: {e!r})")

    print(f"Existing indexes on filing_jobs: {sorted(existing.keys())}\n")

    for name, keys in FILING_JOBS_INDEXES:
        already_present = name in existing
        action = "SKIP (already present)" if already_present else (
            "CREATE" if not dry_run else "WOULD CREATE"
        )
        keys_str = ", ".join(f"{k}={d}" for k, d in keys)
        print(f"  [{action}] {name}  ({keys_str})")

        if dry_run or already_present:
            continue
        await db.filing_jobs.create_index(keys, name=name)

    print()
    if dry_run:
        print("DRY-RUN complete. Re-run with --execute to apply.")
    else:
        print("Done.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Create the four compound indexes on the filing_jobs "
            "collection introduced in MR.6."
        ),
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what indexes WOULD be created. No writes.",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="Create the indexes.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
