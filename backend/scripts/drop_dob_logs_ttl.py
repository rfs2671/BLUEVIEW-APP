"""Drop the two `dob_logs` TTL indexes — `dob_logs_ttl_short` (90d) and
`dob_logs_ttl_long` (365d).

Runbook step 3 of docs/runbooks/dob-logs-ttl-removal-2026-07-24.md. Both
indexes were keyed on `detected_at`, a backfill/sync timestamp rather than an
event date, so the TTL clock measured time-since-first-sync and would have
deleted a project's entire DOB compliance history 90/365 days after onboarding.

SAFETY PROPERTIES
  • Allowlist only — drops indexes by EXACT name from TARGET_INDEXES. There is
    no pattern matching, so no other index can be dropped by this script.
  • Refuses to run if dob_logs carries any OTHER TTL index (an index with
    expireAfterSeconds whose name is not in TARGET_INDEXES). That is an
    unexpected state — the operator decides, not this script. Nothing is
    dropped in that case.
  • Idempotent — indexes already gone are reported as SKIP, not an error, so
    the script is safe to re-run after a partial failure.
  • Dry-run by DEFAULT (repo convention, cf. scripts/backfill_dob_logs_dates.py).
    Pass --execute to actually drop.
  • Never prints the connection string.
  • Touches NO documents. dropIndex is a metadata-only catalog operation: it
    removes the index structure and stops the TTL monitor considering that key.
    No document is read, rewritten, or deleted.

Usage (PowerShell):
    $env:MONGO_URL = '<production Atlas URI>'   # needs read-WRITE for --execute
    $env:DB_NAME   = 'blueview'
    python backend/scripts/drop_dob_logs_ttl.py             # dry-run: show plan
    python backend/scripts/drop_dob_logs_ttl.py --execute   # perform the drops

NOTE: dropping these indexes is only durable once the code that created them
is deployed-removed — `_ensure_index_resilient` re-creates TTL indexes at
startup. Runbook step 1 MUST precede this step.

Exit codes: 0 ok / 2 refused (unexpected TTL index) / 3 one or more drops failed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import OperationFailure
except ImportError:  # pragma: no cover
    sys.exit("motor/pymongo are required: pip install motor")

# The ONLY index names this script will ever drop. Exact match, no globbing.
TARGET_INDEXES = ("dob_logs_ttl_short", "dob_logs_ttl_long")


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="Drop the dob_logs TTL indexes (dry-run unless --execute)."
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="Actually drop. Without this the script only prints the plan.",
    )
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        # Deliberately does not echo any value.
        sys.exit("Set MONGO_URL and DB_NAME in the environment first.")

    client = AsyncIOMotorClient(mongo_url)
    coll = client[db_name].dob_logs

    # db_name is not a credential; the URI is never printed.
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"db={db_name}  collection=dob_logs  mode={mode}\n")

    # ── Inspect current state ─────────────────────────────────────────
    existing: dict[str, dict] = {}
    async for ix in coll.list_indexes():
        existing[ix.get("name", "?")] = ix

    # Refuse if dob_logs carries a TTL index we were not told about.
    unexpected = sorted(
        name
        for name, ix in existing.items()
        if ix.get("expireAfterSeconds") is not None and name not in TARGET_INDEXES
    )
    if unexpected:
        print("REFUSING TO RUN - unexpected TTL index on dob_logs:")
        for name in unexpected:
            ttl = existing[name].get("expireAfterSeconds")
            print(f"  {name}  (expireAfterSeconds={ttl})")
        print(
            "\nThis script only drops "
            + ", ".join(TARGET_INDEXES)
            + ".\nNothing was dropped. Investigate the index above first - a TTL"
            "\nkeyed on detected_at must never be reintroduced (see"
            "\ndocs/runbooks/dob-logs-ttl-removal-2026-07-24.md)."
        )
        client.close()
        return 2

    present = [name for name in TARGET_INDEXES if name in existing]
    absent = [name for name in TARGET_INDEXES if name not in existing]

    print("-- plan --")
    for name in present:
        ttl = existing[name].get("expireAfterSeconds")
        print(f"  DROP  {name}  (expireAfterSeconds={ttl})")
    for name in absent:
        print(f"  SKIP  {name}  (not present - already dropped)")

    if not present:
        print("\nNothing to do; both target indexes are already absent.")
        client.close()
        return 0

    if not args.execute:
        print("\nDry-run only. Re-run with --execute to perform the drops.")
        client.close()
        return 0

    # ── Execute ───────────────────────────────────────────────────────
    print("\n-- executing --")
    failures = []
    for name in present:
        try:
            await coll.drop_index(name)  # exact name; touches no documents
            print(f"  DROPPED  {name}")
        except OperationFailure as e:
            failures.append(name)
            print(f"  FAILED   {name}: {e!r}")

    # ── Confirm ───────────────────────────────────────────────────────
    print("\n-- verification --")
    remaining = []
    async for ix in coll.list_indexes():
        if ix.get("name") in TARGET_INDEXES:
            remaining.append(ix.get("name"))
    if remaining:
        print(f"  STILL PRESENT: {', '.join(sorted(remaining))}")
        print("  Re-run this script (it is idempotent) or see the runbook rollback.")
    else:
        print("  OK - neither target index remains on dob_logs.")
        print("  Next: runbook step 5 - restart the service and re-list to")
        print("  confirm they do NOT return (proves the code removal deployed).")

    client.close()
    return 3 if (failures or remaining) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
