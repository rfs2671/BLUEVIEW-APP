"""One-shot migration — initialize `credentials: []` on every
filing_rep that doesn't already have the field.

Why this exists
───────────────
MR.6 added `credentials: List[FilingRepCredential] = []` to the
FilingRep Pydantic model. The default is a *read-side* default —
Pydantic supplies `[]` when reads land on docs that lack the field.
Pydantic does NOT write through to MongoDB on inserts of dict-shaped
documents, so reps inserted by MR.2's `add_filing_rep` between
MR.2's ship and MR.10's forward-fix in `add_filing_rep` (commit
that ships this migration) lack the field on disk entirely.

The MR.10 endpoint `add_filing_rep_credential` runs an `$set` on
`filing_reps.$[rep].credentials.$[cred].superseded_at` with
`array_filters` selecting credentials where `superseded_at` is None.
When `credentials` is absent (not just empty — the key doesn't
exist), MongoDB raises `PathNotViable` because the array path
can't be traversed. The endpoint had no try/except around the
update, so the operator saw a 500 (which the browser further
disguised as a CORS failure because the 500 escaped middleware).

The MR.10 endpoint already has a defensive guard that lifts the
field to `[]` on the fly per-request, so this migration is NOT
strictly required for correctness — but it cleans up the schema
so any future code path that reads `rep.credentials` without
going through Pydantic gets a consistent shape.

Idempotent: re-runs are safe. Already-initialized reps are
filtered out via `$exists: False` on the matching predicate.
Soft-deleted companies are excluded for the same reason as
migrate_filing_reps_init.py — don't resurrect them.

Run modes
─────────
    # Dry-run — count what WOULD change. No writes. Required.
    python scripts/migrate_filing_reps_credentials_init.py --dry-run

    # Live — perform the $set update. Required.
    python scripts/migrate_filing_reps_credentials_init.py --execute

The two modes are mutually exclusive and one is required (no
implicit-live; explicit-only to prevent accidental runs). Same
env-var contract as the other migration scripts: MONGO_URL +
DB_NAME required.

Verification after `--execute`
───────────────────────────────
The script prints `matched=N modified=M` from the bulk update.
Cross-check that no reps remain without the field:

    db.companies.aggregate([
      { $match: { is_deleted: { $ne: true } } },
      { $unwind: '$filing_reps' },
      { $match: { 'filing_reps.credentials': { $exists: false } } },
      { $count: 'still_missing' }
    ])

Should return `still_missing: 0` (or no documents).
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
    print(f"=== Lift filing_reps[].credentials -> [] -- {mode_label} ===\n")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Target query: companies that have at least one filing_rep
    # without the credentials field. We use $elemMatch to scope
    # the $exists check to a single array element rather than the
    # whole array (which would only match if EVERY element lacked
    # the field — wrong semantic).
    target_query = {
        "is_deleted": {"$ne": True},
        "filing_reps": {
            "$elemMatch": {"credentials": {"$exists": False}},
        },
    }

    candidates = await db.companies.count_documents(target_query)
    overall = await db.companies.count_documents({"is_deleted": {"$ne": True}})
    print(
        f"Companies with at least one un-initialized rep: "
        f"{candidates} (out of {overall} non-deleted)\n"
    )

    if candidates == 0:
        print("Nothing to migrate — every rep already has credentials field.")
        return 0

    # Per-doc breakdown so the operator can see which company gets
    # touched. Limit to first 20 for screen sanity.
    sample_cursor = db.companies.find(
        target_query, {"_id": 1, "name": 1, "filing_reps": 1}
    ).limit(20)
    print("Sample (first 20 affected companies + per-rep status):")
    total_reps_to_lift = 0
    async for c in sample_cursor:
        cid_short = str(c["_id"])[-6:]
        cname = c.get("name") or "(unnamed)"
        reps = c.get("filing_reps") or []
        missing = [r for r in reps if "credentials" not in r]
        total_reps_to_lift += len(missing)
        print(f"  {cid_short:>6}  {cname[:60]:<60} "
              f"reps={len(reps)} missing={len(missing)}")
    if candidates > 20:
        print(f"  ... and {candidates - 20} more companies")
    print()

    if dry_run:
        print(
            f"DRY-RUN: would touch {candidates} company doc(s); "
            f"sample shows >= {total_reps_to_lift} reps need the lift. "
            f"Re-run with --execute to apply."
        )
        return 0

    # Live update. We can't do a single bulk update_many because
    # the positional `$` operator only updates ONE matching array
    # element per doc, and a single rep update wouldn't catch every
    # missing rep on a company that has multiple legacy reps. Loop
    # per-doc; for each doc, loop until no rep is missing the field.
    # Idempotency makes the inner loop safe.
    total_companies_modified = 0
    total_reps_lifted = 0
    cursor = db.companies.find(target_query, {"_id": 1, "filing_reps": 1})
    async for c in cursor:
        company_id = c["_id"]
        # Repeat until no more reps lack the field on this doc.
        while True:
            result = await db.companies.update_one(
                {
                    "_id": company_id,
                    "filing_reps": {
                        "$elemMatch": {"credentials": {"$exists": False}},
                    },
                },
                {"$set": {"filing_reps.$.credentials": []}},
            )
            if result.modified_count == 0:
                break
            total_reps_lifted += 1
        total_companies_modified += 1

    print(
        f"Updated: companies_touched={total_companies_modified} "
        f"reps_lifted={total_reps_lifted}"
    )
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Initialize `credentials: []` on every filing_rep that "
            "lacks the field (MR.10 schema cleanup)."
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
        help="Perform the $set updates.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
