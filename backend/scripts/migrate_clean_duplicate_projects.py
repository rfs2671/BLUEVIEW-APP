"""MR.14 commit 5 — soft-delete duplicate "638 Lafayette" projects.

Why this exists
───────────────
Three production project docs were created on 2026-05-03 from the
operator's failed create attempts (the gates=null Pydantic-default
write trap, fixed in commit 4a's project_list_defaults migration).
All three carry the same name `"638 Lafayette Avenue, Brooklyn, NY,
USA"`. Two of them are stranded — they were never used past the
broken create. The third is the operator's actual project.

This script identifies the cohort and, given an operator-supplied
`--keep <project_id>` argument, soft-deletes the other two. Without
`--keep`, it dry-runs only and prints the IDs the operator can
choose between — no destructive default.

Idempotent: target query excludes already-deleted projects. Running
the script after a successful soft-delete finds the kept project
alone (one doc) and exits clean.

Run modes
─────────
    # Dry-run (default — no --keep means no execute possible).
    # Lists candidates so the operator can pick which to keep.
    python -m backend.scripts.migrate_clean_duplicate_projects --dry-run

    # Live — operator picks which project to keep + commits.
    python -m backend.scripts.migrate_clean_duplicate_projects \
        --keep 6809a25c4e1f0a7d8e8c2cba --execute

Verification after `--execute`
───────────────────────────────
    db.projects.find({
      name: '638 Lafayette Avenue, Brooklyn, NY, USA',
      is_deleted: {$ne: true},
    }).count()
should return 1.
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

# Hard-coded as the documented 4a/test_project_list_defaults
# anchor name. Operator can override via --name if a different
# duplicate cohort surfaces in the future.
DEFAULT_DUPLICATE_NAME = "638 Lafayette Avenue, Brooklyn, NY, USA"


async def main(
    *,
    dry_run: bool,
    keep_id: str | None,
    name: str,
) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print(
            "ERROR: MONGO_URL and DB_NAME env vars required",
            file=sys.stderr,
        )
        return 2

    mode_label = "DRY-RUN" if dry_run else "LIVE"
    print(f"=== Clean duplicate '{name}' projects -- {mode_label} ===\n")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    target_query = {
        "name": name,
        "is_deleted": {"$ne": True},
    }

    candidates = []
    async for p in db.projects.find(target_query, {
        "_id": 1, "name": 1, "address": 1, "company_id": 1,
        "created_at": 1, "gates": 1,
    }):
        candidates.append(p)

    print(f"Found {len(candidates)} non-deleted project(s) named '{name}':\n")
    for c in candidates:
        cid = str(c.get("_id"))
        co = str(c.get("company_id") or "")
        ca = c.get("created_at") or "—"
        gates = c.get("gates")
        gates_state = (
            "null" if gates is None
            else f"len={len(gates)}" if isinstance(gates, list)
            else type(gates).__name__
        )
        print(f"  _id={cid}  company={co}  created_at={ca}  gates={gates_state}")
    print()

    if len(candidates) == 0:
        print("Nothing to migrate — no live duplicates found.")
        return 0
    if len(candidates) == 1:
        print(
            "Only one project remains; nothing to dedupe. Operator may "
            "have already cleaned manually."
        )
        return 0

    if dry_run:
        if keep_id:
            other_ids = [
                str(c["_id"])
                for c in candidates
                if str(c["_id"]) != keep_id
            ]
            if not other_ids:
                print(
                    f"WARNING: keep_id={keep_id} doesn't match any "
                    "candidate. Pick one of the IDs listed above."
                )
                return 2
            print(
                f"DRY-RUN: would keep {keep_id} and soft-delete "
                f"{len(other_ids)} other(s): {other_ids}\n"
                "Re-run with --execute (and the same --keep) to apply."
            )
        else:
            print(
                "DRY-RUN: pick one of the _id values above as --keep, "
                "then re-run with --execute."
            )
        return 0

    if not keep_id:
        print(
            "ERROR: --execute requires --keep <project_id> so the script "
            "knows which doc to preserve. See the dry-run output for "
            "the available IDs."
        )
        return 2

    candidate_ids = {str(c["_id"]) for c in candidates}
    if keep_id not in candidate_ids:
        print(
            f"ERROR: keep_id={keep_id!r} doesn't match any candidate. "
            f"Pick one of: {sorted(candidate_ids)}"
        )
        return 2

    other_ids = [cid for cid in candidate_ids if cid != keep_id]
    print(
        f"Keeping {keep_id}; soft-deleting {len(other_ids)} other(s)..."
    )

    from datetime import datetime, timezone
    from bson import ObjectId
    now = datetime.now(timezone.utc)

    def _to_oid(s: str):
        try:
            return ObjectId(s)
        except Exception:
            return s

    result = await db.projects.update_many(
        {"_id": {"$in": [_to_oid(o) for o in other_ids]}},
        {
            "$set": {
                "is_deleted": True,
                "deleted_at": now,
                "deleted_reason": (
                    "mr14_5_duplicate_project_cleanup; "
                    f"kept sibling={keep_id}"
                ),
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
        f"  db.projects.find({{name:'{name}', "
        "is_deleted:{$ne:true}}).count() // expected 1"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Soft-delete duplicate '638 Lafayette' projects "
            "(MR.14 commit 5 cleanup)."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="List candidates. No writes.")
    mode.add_argument("--execute", action="store_true",
                      help="Soft-delete the duplicates (requires --keep).")
    parser.add_argument(
        "--keep", default=None, type=str,
        help="The _id (string) of the project to preserve.",
    )
    parser.add_argument(
        "--name", default=DEFAULT_DUPLICATE_NAME, type=str,
        help=(
            "Override the duplicate-project name. Defaults to the "
            "documented 4a anchor."
        ),
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(main(
            dry_run=args.dry_run, keep_id=args.keep, name=args.name,
        ))
    )
