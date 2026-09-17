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

# ── PRODUCTION WRITE GUARD ──────────────────────────────────────────────────
# Every write below goes through `audited(...)`, which records it in audit_logs
# with actor "script:backfill_deleted_at", the session and the reason. Without
# --i-know the handle is unwrapped and nothing is written. See prod_guard.
#
# A PYMONGO HANDLE. `audited` decides sync-or-async from what the driver hands
# back, so the wrap reads identically here and in the motor scripts.
import argparse                                                 # noqa: E402
import os as _g_os                                              # noqa: E402
import sys as _g_sys                                            # noqa: E402
_g_sys.path.insert(0, _g_os.path.dirname(_g_os.path.abspath(__file__)))
from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag,
)

NAME = "backfill_deleted_at"

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


def main(args):
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("Set MONGO_URL and DB_NAME in the environment first.")
        sys.exit(1)
    # --i-know IS THE GATE NOW. This script used to read its own argv for
    # "--execute"; that string no longer authorises anything (refuse_legacy_flag
    # has already stopped an operator who typed it). Binding the guard to the
    # SAME local the branches below already test means none of them change.
    execute = check_guard(args)

    client = MongoClient(mongo_url)
    db = audited(client[db_name], args, NAME)
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
    # BEFORE THE PARSER, so `--execute` is refused by name rather than dying as
    # an unrecognised argument. An operator reading "unrecognized arguments:
    # --execute" learns the flag is gone; he does not learn what replaced it.
    refuse_legacy_flag()
    _ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_guard_args(_ap)
    _args = _ap.parse_args()
    # VALIDATED FIRST. `--i-know` with no reason is an argument error, and an
    # argument error should not have to wait behind a missing MONGO_URL to be
    # reported -- the operator fixing one is not the operator fixing the other.
    check_guard(_args)
    main(_args)
