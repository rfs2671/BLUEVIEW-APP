"""One-shot migration — lift list-typed project fields to []
where they're missing or null.

Why this exists
───────────────
Third instance of the "Pydantic default protects reads but not
writes" trap (after redis package missing, then
filing_reps.credentials default missing). Same shape, same fix.

Specifically: ProjectCreate declares
    gates: Optional[List[ProjectGate]] = None
which carries through `model_dump()` as `{"gates": None}`. The
create_project endpoint inserts that dict directly into Mongo, so
projects landed with `gates: null` on disk. ProjectResponse —
declared as `gates: List[Dict[str, Any]] = []` — rejects None on
construction with ValidationError, escaping the middleware as a
500 (which the browser further disguised as a CORS failure
because the unhandled exception bypassed the CORS response).

Three production project docs are stranded in this state today
(operator's failed create attempts on 2026-05-03; same name
"638 Lafayette Avenue, Brooklyn, NY, USA" — all three landed
in Mongo, none could be read back). Without this migration,
GET /projects/{id} 500s on each of them.

The fix in backend/server.py also handles this defensively at
read time via _lift_project_list_defaults(), so this migration
is NOT strictly required for correctness — but it cleans up the
schema so any future code path that reads project list fields
without going through the helper gets a consistent shape, AND it
removes the "wait, why are these three docs returning fields
that don't exist on disk?" surprise for any future operator
inspecting Mongo directly.

Same shape as MR.10's migrate_filing_reps_credentials_init.py.

Fields lifted (mirror of _PROJECT_LIST_DEFAULT_FIELDS in
backend/server.py — single source of truth):
  • gates                   (the trigger; 3 production docs null)
  • report_email_list       (defensive; 22 docs missing)
  • site_device_subfolders  (defensive; 23 docs missing)
  • trade_assignments       (defensive; 22 docs missing)
  • required_logbooks       (defensive; 1 doc missing)
  • nfc_tags                (defensive; 0 docs missing today)

Idempotent: re-runs are safe. Already-populated fields pass
through untouched. Soft-deleted projects are excluded — same
"don't resurrect them" rule as the other migrations.

Run modes
─────────
    # Dry-run — count what WOULD change. No writes. Required.
    python scripts/migrate_project_list_defaults.py --dry-run

    # Live — perform the $set updates. Required.
    python scripts/migrate_project_list_defaults.py --execute

The two modes are mutually exclusive and one is required (no
implicit-live; explicit-only to prevent accidental runs). Same
env-var contract as the other migration scripts: MONGO_URL +
DB_NAME required.

Verification after `--execute`
───────────────────────────────
The script prints `lifted=N docs_touched=M` summarizing the
work. Cross-check that no project has a null or missing list
field:

    db.projects.aggregate([
      { $match: { is_deleted: { $ne: true } } },
      { $project: {
          gates_bad:                   { $eq: ['$gates', null] },
          report_email_list_bad:       { $eq: ['$report_email_list', null] },
          site_device_subfolders_bad:  { $eq: ['$site_device_subfolders', null] },
          trade_assignments_bad:       { $eq: ['$trade_assignments', null] },
          required_logbooks_bad:       { $eq: ['$required_logbooks', null] },
          nfc_tags_bad:                { $eq: ['$nfc_tags', null] }
      }},
      { $match: { $or: [
          { gates_bad: true },
          { report_email_list_bad: true },
          { site_device_subfolders_bad: true },
          { trade_assignments_bad: true },
          { required_logbooks_bad: true },
          { nfc_tags_bad: true }
      ]}},
      { $count: 'still_bad' }
    ])

Should return `still_bad: 0` (or no documents).
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


# Mirror of backend/server.py:_PROJECT_LIST_DEFAULT_FIELDS. Kept
# in sync manually — both lists need to match for the lift behavior
# to be coherent. If you add a list field to the Project model,
# add it here too.
PROJECT_LIST_DEFAULT_FIELDS = (
    "gates",
    "report_email_list",
    "site_device_subfolders",
    "trade_assignments",
    "required_logbooks",
    "nfc_tags",
)


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
    print(f"=== Lift project list-fields -> [] -- {mode_label} ===\n")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Per-field counts for visibility. We split null-vs-missing so
    # the operator can see exactly which docs are broken (null is
    # the production-500 trigger; missing is the defensive cleanup).
    overall = await db.projects.count_documents(
        {"is_deleted": {"$ne": True}}
    )
    print(f"Total non-deleted projects: {overall}\n")

    print(f"{'field':<28} {'null':>6} {'missing':>9} {'array':>7}")
    print(f"{'-'*28} {'-'*6} {'-'*9} {'-'*7}")
    per_field = {}
    for fld in PROJECT_LIST_DEFAULT_FIELDS:
        null_count = await db.projects.count_documents({
            "is_deleted": {"$ne": True},
            fld: {"$type": 10},  # 10 = null
        })
        missing_count = await db.projects.count_documents({
            "is_deleted": {"$ne": True},
            fld: {"$exists": False},
        })
        array_count = await db.projects.count_documents({
            "is_deleted": {"$ne": True},
            fld: {"$type": "array"},
        })
        per_field[fld] = {
            "null": null_count,
            "missing": missing_count,
            "array": array_count,
        }
        print(
            f"{fld:<28} {null_count:>6} {missing_count:>9} {array_count:>7}"
        )
    print()

    # Sample the docs that have at least one null list field so the
    # operator can confirm they match the expected pre-fix state.
    null_query = {
        "is_deleted": {"$ne": True},
        "$or": [
            {fld: {"$type": 10}} for fld in PROJECT_LIST_DEFAULT_FIELDS
        ],
    }
    null_count_total = await db.projects.count_documents(null_query)
    print(
        f"Docs with at least one null list-field "
        f"(production-500 trigger): {null_count_total}"
    )
    if null_count_total > 0:
        print("Sample (up to 10):")
        cursor = db.projects.find(null_query, {"_id": 1, "name": 1}).limit(10)
        async for p in cursor:
            print(f"  _id={p['_id']}  name={(p.get('name') or '')[:60]!r}")
        print()

    total_to_change = sum(
        per_field[fld]["null"] + per_field[fld]["missing"]
        for fld in PROJECT_LIST_DEFAULT_FIELDS
    )
    if total_to_change == 0:
        print(
            "Nothing to migrate — every project already has all "
            "list fields as arrays."
        )
        return 0

    if dry_run:
        print(
            f"DRY-RUN: would lift {total_to_change} field-instance(s) "
            f"across the {overall} non-deleted projects. "
            f"Re-run with --execute to apply."
        )
        return 0

    # Live update. For each field, run two updates:
    #   1. $set: <field>: [] WHERE <field> is type:null  (the trigger case)
    #   2. $set: <field>: [] WHERE <field> doesn't exist  (defensive)
    # Both update_many calls are idempotent and safe to re-run.
    print("Applying lifts...")
    total_lifted = 0
    docs_touched_ids = set()
    for fld in PROJECT_LIST_DEFAULT_FIELDS:
        # Null case
        null_filter = {
            "is_deleted": {"$ne": True},
            fld: {"$type": 10},
        }
        # Capture _ids first for visibility
        null_ids = [
            p["_id"]
            async for p in db.projects.find(null_filter, {"_id": 1})
        ]
        if null_ids:
            res = await db.projects.update_many(
                null_filter, {"$set": {fld: []}}
            )
            print(
                f"  {fld:<28} null   → []  modified={res.modified_count}"
            )
            total_lifted += res.modified_count
            docs_touched_ids.update(str(x) for x in null_ids)

        # Missing case
        missing_filter = {
            "is_deleted": {"$ne": True},
            fld: {"$exists": False},
        }
        missing_ids = [
            p["_id"]
            async for p in db.projects.find(missing_filter, {"_id": 1})
        ]
        if missing_ids:
            res = await db.projects.update_many(
                missing_filter, {"$set": {fld: []}}
            )
            print(
                f"  {fld:<28} missing → [] modified={res.modified_count}"
            )
            total_lifted += res.modified_count
            docs_touched_ids.update(str(x) for x in missing_ids)

    print()
    print(
        f"Updated: lifted={total_lifted} field-instance(s)  "
        f"docs_touched={len(docs_touched_ids)}"
    )
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Lift project list-typed fields to [] where they are "
            "null or missing (MR.5+ third Pydantic-default-on-write "
            "regression cleanup)."
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
