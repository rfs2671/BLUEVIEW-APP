"""COMMIT 2 — delete the mislabeled DOHMH Rodent Inspection (p937-wjvj) rows
from dob_logs. These were ingested as record_type="inspection" (rat inspections
mislabeled as DOB inspections); the ingest was removed in COMMIT 1, so no new
rows arrive and this clears the existing ones.

Reads MONGO_URL / DB_NAME from the environment; NEVER prints the connection
string.

SAFETY:
  • DRY-RUN by default. `--i-know` is what actually deletes.
  • Before deleting, verifies every record_type=="inspection" row is sourced
    from p937-wjvj (or is unstamped null/absent). If ANY foreign dataset is
    found, it PRINTS the offenders and EXITS WITHOUT DELETING — so this can
    never catch a future correct DOB inspection record.
  • Deletes with deleteMany({record_type:"inspection"}); never drop().
  • Writes an audit row: what, how many, who ran it, why.

── `--execute` NO LONGER DELETES, AND THAT IS DELIBERATE ───────────────────

This is the only script in the directory whose whole purpose is a mass delete,
so it is the one where a silent change of meaning would cost the most. The old
documented command was `--execute`; it is now refused by name, pointing at
`--i-know`, rather than either honouring it (which would make the guard
decoration) or quietly doing nothing (which would tell an operator a migration
ran when it did not).

    # dry-run (default) — counts only, no writes
    $env:MONGO_URL = '<production Atlas URI>'; $env:DB_NAME = 'blueview'
    python delete_rodent_inspections.py

    # execute the delete
    python delete_rodent_inspections.py --i-know \
        --reason 'DOHMH rodent rows mislabeled as DOB inspections' \
        --session <session id>
"""
import os
import sys
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prod_guard import (  # noqa: E402
    add_guard_args, check_guard, refuse_legacy_flag, report_dry_run,
    script_audit,
)

NAME = "delete_rodent_inspections"

INSPECTION = {"record_type": "inspection"}
# Correct DOB inspection sources — verified untouched after the delete.
CORRECT_TYPES = ["boiler", "elevator", "facade_fisp", "cofo"]
# The only dataset (plus unstamped legacy rows) that may back an inspection row.
ALLOWED_DATASETS = {"p937-wjvj", None}


async def main(args) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    url = os.environ.get("MONGO_URL")
    dbname = os.environ.get("DB_NAME")
    if not url or not dbname:
        print("Set MONGO_URL and DB_NAME in the environment first.")
        return 2
    client = AsyncIOMotorClient(url)
    db = client[dbname]

    # THE SAFETY SWEEP BELOW RUNS EITHER WAY. The guard decides whether
    # anything is deleted; it must never decide whether the check that says
    # deleting is SAFE gets to run, or a dry run would report on a rule the
    # real run never applied.
    execute = check_guard(args)
    print(f"=== delete_rodent_inspections — "
          f"{'EXECUTE' if execute else 'DRY-RUN'} ===")

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
        report_dry_run(
            f"delete {to_delete} dob_logs rows matching "
            f"{{record_type:'inspection'}} (datasets: {datasets})")
        client.close()
        return 0

    # ── DELETE (never drop) ──────────────────────────────────────────────
    result = await db.dob_logs.delete_many(INSPECTION)
    print(f"\ndeleted_count: {result.deleted_count}")

    # ONE ROW FOR THE RUN, not one per deleted document: nobody is ever going
    # to ask about an individual mislabeled rodent inspection, and 500 audit
    # rows would bury every other entry in the collection. The selector, the
    # count and the datasets are what a person asks of a mass delete.
    await script_audit(
        db, "dob_logs_rodent_inspections_deleted", "collection", "dob_logs",
        {
            "selector": INSPECTION,
            "datasets_present": datasets,
            "counted_before": to_delete,
            "deleted_count": result.deleted_count,
        },
        args, name=NAME,
    )
    print(f"audit row written, actor script:{NAME}")

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
    # BEFORE THE PARSER, so `--execute` is refused by name rather than dying as
    # an unrecognised argument. An operator reading "unrecognized arguments:
    # --execute" learns that the flag is gone; he does not learn what replaced
    # it, and this script is the one where guessing is most expensive.
    refuse_legacy_flag()
    _ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_guard_args(_ap)
    _args = _ap.parse_args()
    # VALIDATED BEFORE ANYTHING ELSE. `--i-know` with no reason is an argument
    # error, and an argument error should not have to wait behind a missing
    # environment variable to be reported -- the operator fixing one is not the
    # operator fixing the other.
    check_guard(_args)
    sys.exit(asyncio.run(main(_args)))
