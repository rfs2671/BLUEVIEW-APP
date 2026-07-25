"""COMMIT 2 — delete the mislabeled DOHMH Rodent Inspection (p937-wjvj) rows
from dob_logs. These were ingested as record_type="inspection" (rat inspections
mislabeled as DOB inspections); the ingest was removed in COMMIT 1, so no new
rows arrive and this clears the existing ones.

Reads MONGO_URL / DB_NAME from the environment; NEVER prints the connection
string.

SAFETY:
  • DRY-RUN by default. Pass --execute to actually delete.
  • Before deleting, verifies every record_type=="inspection" row is sourced
    from p937-wjvj (or is unstamped null/absent). If ANY foreign dataset is
    found, it PRINTS the offenders and EXITS WITHOUT DELETING — so this can
    never catch a future correct DOB inspection record.
  • Deletes with deleteMany({record_type:"inspection"}); never drop().

    # dry-run (default) — counts only, no writes
    $env:MONGO_URL = '<production Atlas URI>'; $env:DB_NAME = 'blueview'
    python delete_rodent_inspections.py

    # execute the delete
    python delete_rodent_inspections.py --execute
"""
import os
import sys
import asyncio

INSPECTION = {"record_type": "inspection"}
# Correct DOB inspection sources — verified untouched after the delete.
CORRECT_TYPES = ["boiler", "elevator", "facade_fisp", "cofo"]
# The only dataset (plus unstamped legacy rows) that may back an inspection row.
ALLOWED_DATASETS = {"p937-wjvj", None}


async def main(execute: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    url = os.environ.get("MONGO_URL")
    dbname = os.environ.get("DB_NAME")
    if not url or not dbname:
        print("Set MONGO_URL and DB_NAME in the environment first.")
        return 2
    client = AsyncIOMotorClient(url)
    db = client[dbname]

    mode = "EXECUTE" if execute else "DRY-RUN"
    print(f"=== delete_rodent_inspections — {mode} ===")

    # ── SAFETY GUARD ─────────────────────────────────────────────────────
    # Every record_type=="inspection" row must be p937-wjvj or unstamped.
    datasets = await db.dob_logs.distinct("dataset", INSPECTION)
    foreign = [d for d in datasets if d not in ALLOWED_DATASETS]
    print(f"distinct `dataset` on record_type=='inspection': {datasets}")
    if foreign:
        print("ABORT: found inspection rows with a NON-p937-wjvj dataset:")
        for d in foreign:
            n = await db.dob_logs.count_documents({**INSPECTION, "dataset": d})
            print(f"    {d!r}: {n} rows")
        print("Refusing to delete — {record_type:'inspection'} would catch a "
              "record that is NOT rodent-sourced. Investigate before proceeding.")
        client.close()
        return 3

    # ── COUNT ────────────────────────────────────────────────────────────
    to_delete = await db.dob_logs.count_documents(INSPECTION)
    print(f"records matching {{record_type:'inspection'}} to delete: {to_delete}")

    if not execute:
        print("\nDRY-RUN — no records deleted. Re-run with --execute to delete.")
        client.close()
        return 0

    # ── DELETE (never drop) ──────────────────────────────────────────────
    result = await db.dob_logs.delete_many(INSPECTION)
    print(f"\ndeleted_count: {result.deleted_count}")

    # ── POST-DELETE VERIFICATION ─────────────────────────────────────────
    remaining = await db.dob_logs.count_documents(INSPECTION)
    print(f"remaining record_type=='inspection': {remaining}  (expect 0)")
    print("correct DOB inspection sources (expect UNCHANGED):")
    for rt in CORRECT_TYPES:
        n = await db.dob_logs.count_documents({"record_type": rt})
        print(f"    record_type=='{rt}': {n}")

    client.close()
    return 0 if remaining == 0 else 4


if __name__ == "__main__":
    _execute = "--execute" in sys.argv[1:]
    sys.exit(asyncio.run(main(_execute)))
