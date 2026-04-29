"""One-shot migration — initialize filing_reps: [] on every company
document that doesn't have the field yet.

Why this exists
───────────────
MR.2 adds a `filing_reps: List[FilingRep] = []` field to the
`Company` Pydantic model and four CRUD endpoints under
`/api/owner/companies/{id}/filing-reps`. New companies created via
POST /api/owner/companies after the MR.2 deploy carry the field
implicitly through Pydantic's default. Pre-existing company
documents in Mongo don't — they were inserted with the legacy
shape and would return `None` (not `[]`) for `filing_reps` on read.

This migration adds `filing_reps: []` to every existing company
document where the field is missing. Idempotent: docs that already
have the field (newly-created post-MR.2 OR previously migrated)
are excluded by the query. Soft-deleted records are EXCLUDED
because the migration shouldn't resurrect them; if they're
un-deleted later, the next migration re-run picks them up.

No auto-population of filing_reps[0] from existing GC license
fields. Per the §14 architectural review (concern 3 in the
pre-build surfacing), the GC license is a company attribute (one
per company); filing_reps is a roster of authorized filing
individuals (potentially many, distinct trade scopes). The
operator adds filing_reps explicitly via the admin UI.

Run modes
─────────
    # Dry-run — count what WOULD change. No writes. Required.
    python scripts/migrate_filing_reps_init.py --dry-run

    # Live — perform the $set update. Required.
    python scripts/migrate_filing_reps_init.py --execute

The two modes are mutually exclusive and one is required (no
implicit-live; explicit-only to prevent accidental runs).
Same env-var contract as backfill_renewal_v2_keys.py:
MONGO_URL + DB_NAME required.
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
    print(f"=== Migrate filing_reps init on companies — {mode_label} ===\n")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Target query: companies without the field. Idempotent — re-runs
    # are safe because already-migrated docs (or new post-MR.2 docs)
    # are excluded.
    query = {
        "is_deleted": {"$ne": True},
        "filing_reps": {"$exists": False},
    }

    total = await db.companies.count_documents(query)
    overall = await db.companies.count_documents({"is_deleted": {"$ne": True}})
    print(f"Companies needing init: {total} (out of {overall} non-deleted)\n")

    if total == 0:
        print("Nothing to migrate.")
        return 0

    if dry_run:
        # Show a quick preview of which companies would change.
        sample = await db.companies.find(query, {"_id": 1, "name": 1}).to_list(length=20)
        print("Sample (first 20):")
        for c in sample:
            short = str(c["_id"])[-6:]
            name = c.get("name") or "(unnamed)"
            print(f"  {short:>6}  {name[:60]}")
        if total > 20:
            print(f"  ... and {total - 20} more")
        print()
        print(f"DRY-RUN: {total} docs would be updated. Re-run with --execute to apply.")
        return 0

    # Live update — single $set across all matching docs.
    result = await db.companies.update_many(
        query,
        {"$set": {"filing_reps": []}},
    )
    print(f"Updated: matched={result.matched_count} modified={result.modified_count}")
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Initialize filing_reps: [] on every company document "
            "that doesn't have the field yet (MR.2 schema migration)."
        ),
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what WOULD change. No writes.",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="Perform the $set update.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
