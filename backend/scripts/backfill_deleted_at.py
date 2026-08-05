"""Task 8 backfill — stamp `deleted_at` on pre-existing soft-deleted rows.

Going forward, every soft-delete in server.py stamps `deleted_at`. But rows
soft-deleted BEFORE that change have `is_deleted: true` and NO `deleted_at`, so
the purge job (which keys on `deleted_at`) would skip them forever. This script
backfills `deleted_at` on those rows.

It backfills to **now** (not the stale `updated_at`) on purpose: that way a row
soft-deleted long ago does not become instantly purge-eligible — it starts its
retention clock at backfill time, so nothing is removed until it genuinely ages
SOFT_DELETE_RETENTION_DAYS past this run. Safer than trusting `updated_at`, which
any later edit/migration could have bumped.

ONLY the purge allowlist collections are touched (the same set the purge job
acts on). Compliance/audit collections are never modified.

DRY-RUN by default — prints counts, writes nothing. Pass --execute to write.

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='<db>'
    python backfill_deleted_at.py            # dry-run: report only
    python backfill_deleted_at.py --execute  # actually stamp deleted_at

Reads MONGO_URL / DB_NAME from env; never prints the connection string.
"""
import os
import sys
from datetime import datetime, timezone

try:
    from pymongo import MongoClient
except ImportError:
    print("pymongo not importable — run inside the backend venv.")
    sys.exit(1)

# MUST match SOFT_DELETE_PURGE_COLLECTIONS in server.py — only operational,
# replaceable collections. Never add a compliance/audit collection here.
PURGE_COLLECTIONS = [
    "nfc_tags", "site_devices", "dropbox_connections",
    "checklist_assignments", "checklists",
]


def main():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("Set MONGO_URL and DB_NAME in the environment first.")
        sys.exit(1)
    execute = "--execute" in sys.argv[1:]

    client = MongoClient(mongo_url)
    db = client[db_name]
    now = datetime.now(timezone.utc)

    q = {"is_deleted": True, "deleted_at": {"$exists": False}}
    print("=" * 60)
    print(f"{'EXECUTE' if execute else 'DRY-RUN'} — backfill deleted_at = {now.isoformat()}")
    print("=" * 60)
    grand = 0
    for coll in PURGE_COLLECTIONS:
        try:
            n = db[coll].count_documents(q)
        except Exception as e:
            print(f"  {coll}: count failed ({e!r}) — skipped")
            continue
        grand += n
        if not execute:
            print(f"  {coll}: {n} row(s) would be stamped")
        else:
            if n:
                res = db[coll].update_many(q, {"$set": {"deleted_at": now}})
                print(f"  {coll}: stamped {res.modified_count} row(s)")
            else:
                print(f"  {coll}: 0 rows — nothing to do")
    print("-" * 60)
    print(f"TOTAL: {grand} row(s) {'stamped' if execute else 'would be stamped'}")
    if not execute:
        print("Re-run with --execute to write.")
    client.close()


if __name__ == "__main__":
    main()
