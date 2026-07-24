"""READ-ONLY inspection of the `dob_logs` indexes and the `detected_at`
profile that drove the (now-removed) TTL retention.

Companion to docs/runbooks/dob-logs-ttl-removal-2026-07-24.md — used at
runbook steps 2, 4 and 5 to confirm whether `dob_logs_ttl_short` /
`dob_logs_ttl_long` are present, absent, or have returned after a restart.

SAFETY — this script performs READ operations only:
  • collection.list_indexes()
  • collection.count_documents(filter)
  • collection.find(filter, projection).sort(...).limit(1)
No create_index, no drop_index, no insert/update/delete, no aggregate.
It reads MONGO_URL + DB_NAME from the environment and NEVER prints the
connection string.

Usage (PowerShell):
    $env:MONGO_URL = '<production Atlas URI>'
    $env:DB_NAME   = 'blueview'
    python backend/scripts/check_dob_logs_indexes.py

A read-only Atlas user is sufficient and recommended.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:  # pragma: no cover
    sys.exit("motor is required: pip install motor")

# The record_types the two removed TTL indexes covered, per
# partialFilterExpression. Kept here so the report shows which rows WOULD
# have been in each bucket.
_TTL_SHORT_TYPES = ["permit", "complaint", "inspection", "job_status"]
_TTL_LONG_TYPES = ["violation", "swo"]
_ALL_TYPES = _TTL_SHORT_TYPES + _TTL_LONG_TYPES


async def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        # Deliberately does not echo any value.
        sys.exit("Set MONGO_URL and DB_NAME in the environment first.")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    coll = db.dob_logs

    # db_name is not a credential; the URI is never printed.
    print(f"db={db_name}  collection=dob_logs\n")

    # ── 1. Indexes ────────────────────────────────────────────────────
    print("-- indexes --")
    ttl_found = []
    async for ix in coll.list_indexes():
        name = ix.get("name", "?")
        ttl = ix.get("expireAfterSeconds")
        line = f"  {name:<34} key={dict(ix.get('key', {}))}"
        if ttl is not None:
            line += f"  TTL={ttl}s ({ttl / 86400:.0f}d)"
            ttl_found.append((name, ttl))
        if "partialFilterExpression" in ix:
            line += f"  partial={ix['partialFilterExpression']}"
        print(line)

    print()
    if ttl_found:
        print("  !! TTL INDEX PRESENT on dob_logs:")
        for name, ttl in ttl_found:
            print(f"       {name}  ({ttl / 86400:.0f} days)")
        print("     Expected AFTER the runbook drop: none.")
    else:
        print("  OK - no TTL index on dob_logs (expireAfterSeconds absent).")

    # ── 2. detected_at profile (what the TTL clock read) ──────────────
    print("\n-- detected_at profile --")
    total = await coll.count_documents({})
    print(f"  total docs: {total}")

    oldest = await (
        coll.find({"detected_at": {"$type": "date"}}, {"detected_at": 1})
        .sort("detected_at", 1)
        .limit(1)
        .to_list(1)
    )
    if oldest:
        d = oldest[0]["detected_at"]
        print(f"  oldest detected_at (BSON Date): {d.isoformat()}")
        print(f"    a 90d  TTL would fire ~{(d + timedelta(days=90)).date()}")
        print(f"    a 365d TTL would fire ~{(d + timedelta(days=365)).date()}")
        print("    (detected_at is a sync/backfill stamp, not an event date)")
    else:
        print("  no doc has a BSON-Date detected_at")

    # TTL never fires on non-Date values — such rows were always immune.
    non_date = await coll.count_documents(
        {"detected_at": {"$not": {"$type": "date"}}}
    )
    print(f"  docs whose detected_at is NOT a BSON Date (TTL-immune): {non_date}")

    # ── 3. Rows per record_type, with the bucket they'd have been in ──
    print("\n-- rows by record_type --")
    counted = 0
    for rt in _ALL_TYPES:
        n = await coll.count_documents({"record_type": rt})
        counted += n
        bucket = "90d" if rt in _TTL_SHORT_TYPES else "365d"
        print(f"  {rt:<12} {n:>7}   former TTL bucket: {bucket}")
    other = total - counted
    if other:
        print(f"  {'(other)':<12} {other:>7}   former TTL bucket: none")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
