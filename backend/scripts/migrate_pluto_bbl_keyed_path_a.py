"""Phase V2.2.4 Path A — one-shot operational migration.

Migrates the peer-comparison schema from BIN-keyed to BBL-keyed.
Three correlated mutations performed in one run; all gated by
``--execute``.

  1. ``nyc_pluto``: drop ``nyc_pluto_bin_unique`` (the DKE-storm
     cause — V2.2-era unique index on a field V2.2.3 stopped
     populating); drop the existing non-unique ``nyc_pluto_bbl``
     index; recreate ``nyc_pluto_bbl_unique`` as unique on bbl.
  2. ``nyc_pluto``: delete every doc (in production this is the
     single polluted doc that produced the DKE storm; backfill
     repopulates with ~860k clean BBL-keyed rows).
  3. ``nyc_violations`` + ``nyc_inspections``: add
     ``(bbl, occurred_date)`` index. ``nyc_complaints_311``
     already has one — no-op for that collection.
  4. ``statistical_baselines``: delete every doc (in production
     this is the single zero-peer-sample baseline produced before
     V2.2.4; the 3:30 AM ET aggregator cron will recompute fresh
     baselines once the backfill repopulates nyc_pluto).

Default mode is dry-run — prints every operation it WOULD perform
and exits 0 without touching the DB. Pass ``--execute`` to perform
writes. The dry-run/execute split mirrors the convention of
``cleanup_v21_inert_data.py`` and
``cleanup_pluto_polluted_record_ids.py``; this one differs only in
that ``--execute`` replaces the CONFIRM prompt (the operator paste-
reviews the dry-run output before passing the flag).

Usage:
    # Dry-run (always safe):
    MONGO_URL='mongodb+srv://...' DB_NAME='blueview' \\
      python -m backend.scripts.migrate_pluto_bbl_keyed_path_a

    # Execute after dry-run review:
    MONGO_URL='mongodb+srv://...' DB_NAME='blueview' \\
      python -m backend.scripts.migrate_pluto_bbl_keyed_path_a --execute

Exit codes:
    0 — completed (dry-run OR execute)
    1 — operational error (env vars missing, Mongo failure, etc.)

Rollback: index drops + creates are reversible by re-running the
inverse manually via a Mongo shell. Document collection deletions
are NOT reversible without restoring from Atlas backup — the
runbook (docs/runbooks/path_a_bbl_keyed_peer_comparison.md) calls
out the pre-migration backup requirement.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    AsyncIOMotorClient = None  # type: ignore


# ── Migration plan (declarative) ─────────────────────────────────

PLUTO_COLLECTION = "nyc_pluto"
VIOLATIONS_COLLECTION = "nyc_violations"
INSPECTIONS_COLLECTION = "nyc_inspections"
COMPLAINTS_311_COLLECTION = "nyc_complaints_311"
BASELINES_COLLECTION = "statistical_baselines"

# Indexes to drop on nyc_pluto (legacy V2.2 + the non-unique
# placeholder).
PLUTO_INDEXES_TO_DROP = (
    "nyc_pluto_bin_unique",
    "nyc_pluto_bbl",
)

# Indexes to create after the drop.
PLUTO_INDEX_TO_CREATE = {
    "keys":   [("bbl", 1)],
    "name":   "nyc_pluto_bbl_unique",
    "unique": True,
}

EVENT_BBL_DATE_INDEXES_TO_CREATE = (
    (VIOLATIONS_COLLECTION, {
        "keys": [("bbl", 1), ("occurred_date", -1)],
        "name": "nyc_violations_bbl_date",
    }),
    (INSPECTIONS_COLLECTION, {
        "keys": [("bbl", 1), ("occurred_date", -1)],
        "name": "nyc_inspections_bbl_date",
    }),
    # nyc_complaints_311 already has this — V2.2.4 schema move
    # de-duplicates by routing through _nyc_source_indexes(). The
    # migration script does NOT need to create it on production.
)


# ── Helpers ──────────────────────────────────────────────────────


def _print_section(title: str) -> None:
    print()
    print("─" * 64)
    print(title)
    print("─" * 64)


def _redact_mongo_url(url: str) -> str:
    try:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            _creds, host = rest.split("@", 1)
            return f"{scheme}://***@{host}"
        return url
    except Exception:
        return "<unparseable>"


async def _list_indexes(db, coll: str) -> List[Dict[str, Any]]:
    names = await db.list_collection_names()
    if coll not in names:
        return []
    return await db[coll].list_indexes().to_list(length=None)


async def _count(db, coll: str) -> int:
    names = await db.list_collection_names()
    if coll not in names:
        return 0
    return await db[coll].count_documents({})


# ── Pre-flight reporting ─────────────────────────────────────────


async def print_preflight(db) -> Dict[str, Any]:
    _print_section("PRE-MIGRATION STATE")
    snapshot: Dict[str, Any] = {}
    for coll in (
        PLUTO_COLLECTION, VIOLATIONS_COLLECTION,
        INSPECTIONS_COLLECTION, COMPLAINTS_311_COLLECTION,
        BASELINES_COLLECTION,
    ):
        n = await _count(db, coll)
        idxs = await _list_indexes(db, coll)
        snapshot[coll] = {"count": n, "indexes": idxs}
        print()
        print(f"  {coll}:")
        print(f"    document count: {n:,}")
        print(f"    indexes:")
        for idx in idxs:
            unique = " UNIQUE" if idx.get("unique") else ""
            print(f"      • {idx.get('name')}  keys={idx.get('key')}{unique}")
    return snapshot


# ── Planned operations (printed in both dry-run and execute) ────


async def print_plan(db) -> None:
    _print_section("PLAN (dry-run output — what WOULD happen)")
    print()
    # nyc_pluto index drops.
    print(f"  Step 1 — drop indexes on {PLUTO_COLLECTION}:")
    existing = {i.get("name") for i in await _list_indexes(db, PLUTO_COLLECTION)}
    for name in PLUTO_INDEXES_TO_DROP:
        present = name in existing
        marker = "✓ exists, will drop" if present else "· not present, skip"
        print(f"      • {name:30}  {marker}")

    # nyc_pluto delete_many.
    print()
    pluto_count = await _count(db, PLUTO_COLLECTION)
    print(
        f"  Step 2 — delete_many({{}}) on {PLUTO_COLLECTION}: "
        f"will delete {pluto_count:,} doc(s)",
    )

    # New unique index.
    print()
    print(f"  Step 3 — create index on {PLUTO_COLLECTION}:")
    print(
        f"      • {PLUTO_INDEX_TO_CREATE['name']:30}  "
        f"keys={PLUTO_INDEX_TO_CREATE['keys']}  UNIQUE",
    )

    # Event-collection bbl indexes.
    print()
    print(f"  Step 4 — create (bbl, occurred_date) indexes on event collections:")
    for coll, spec in EVENT_BBL_DATE_INDEXES_TO_CREATE:
        existing_event = {i.get("name") for i in await _list_indexes(db, coll)}
        present = spec["name"] in existing_event
        marker = "· already present, skip" if present else "✓ will create"
        print(
            f"      • {coll}:{spec['name']:30}  "
            f"keys={spec['keys']}  {marker}",
        )

    # Baseline cleanup.
    print()
    baseline_count = await _count(db, BASELINES_COLLECTION)
    print(
        f"  Step 5 — delete_many({{}}) on {BASELINES_COLLECTION}: "
        f"will delete {baseline_count:,} doc(s)",
    )


# ── Execution (only runs with --execute) ────────────────────────


async def execute_migration(db) -> Dict[str, Any]:
    _print_section("EXECUTING")
    summary: Dict[str, Any] = {}

    # Step 1: drop legacy PLUTO indexes.
    print()
    print(f"  Step 1 — dropping indexes on {PLUTO_COLLECTION}:")
    existing = {i.get("name") for i in await _list_indexes(db, PLUTO_COLLECTION)}
    summary["indexes_dropped"] = []
    for name in PLUTO_INDEXES_TO_DROP:
        if name in existing:
            try:
                await db[PLUTO_COLLECTION].drop_index(name)
                summary["indexes_dropped"].append(name)
                print(f"      ✓ dropped {name}")
            except Exception as e:
                print(f"      ✗ drop {name} failed: {e!r}", file=sys.stderr)
                raise
        else:
            print(f"      · {name} not present, skipped")

    # Step 2: delete every PLUTO doc.
    print()
    print(f"  Step 2 — delete_many({{}}) on {PLUTO_COLLECTION}:")
    res = await db[PLUTO_COLLECTION].delete_many({})
    deleted = getattr(res, "deleted_count", 0) or 0
    summary["pluto_docs_deleted"] = deleted
    print(f"      ✓ deleted_count = {deleted:,}")

    # Step 3: create unique-on-bbl index.
    print()
    print(f"  Step 3 — create_index on {PLUTO_COLLECTION}:")
    spec = PLUTO_INDEX_TO_CREATE
    try:
        await db[PLUTO_COLLECTION].create_index(
            spec["keys"], name=spec["name"], unique=spec.get("unique", False),
            background=True,
        )
        summary["pluto_index_created"] = spec["name"]
        print(f"      ✓ created {spec['name']} (unique)")
    except Exception as e:
        print(f"      ✗ create failed: {e!r}", file=sys.stderr)
        raise

    # Step 4: create event-collection (bbl, occurred_date) indexes.
    print()
    print(f"  Step 4 — create (bbl, occurred_date) indexes on event collections:")
    summary["event_indexes_created"] = []
    for coll, idx_spec in EVENT_BBL_DATE_INDEXES_TO_CREATE:
        existing_event = {i.get("name") for i in await _list_indexes(db, coll)}
        if idx_spec["name"] in existing_event:
            print(f"      · {coll}:{idx_spec['name']} already present")
            continue
        try:
            await db[coll].create_index(
                idx_spec["keys"], name=idx_spec["name"], background=True,
            )
            summary["event_indexes_created"].append((coll, idx_spec["name"]))
            print(f"      ✓ created {coll}:{idx_spec['name']}")
        except Exception as e:
            print(f"      ✗ create {coll}:{idx_spec['name']} failed: {e!r}", file=sys.stderr)
            raise

    # Step 5: delete baselines.
    print()
    print(f"  Step 5 — delete_many({{}}) on {BASELINES_COLLECTION}:")
    res = await db[BASELINES_COLLECTION].delete_many({})
    deleted = getattr(res, "deleted_count", 0) or 0
    summary["baselines_deleted"] = deleted
    print(f"      ✓ deleted_count = {deleted:,}")

    return summary


# ── Post-flight reporting ────────────────────────────────────────


async def print_postflight(db) -> None:
    _print_section("POST-MIGRATION STATE")
    for coll in (
        PLUTO_COLLECTION, VIOLATIONS_COLLECTION,
        INSPECTIONS_COLLECTION, COMPLAINTS_311_COLLECTION,
        BASELINES_COLLECTION,
    ):
        n = await _count(db, coll)
        idxs = await _list_indexes(db, coll)
        print()
        print(f"  {coll}:")
        print(f"    document count: {n:,}")
        print(f"    indexes:")
        for idx in idxs:
            unique = " UNIQUE" if idx.get("unique") else ""
            print(f"      • {idx.get('name')}  keys={idx.get('key')}{unique}")

    print()
    print("[verdict]")
    pluto_idxs = {i.get("name") for i in await _list_indexes(db, PLUTO_COLLECTION)}
    if "nyc_pluto_bbl_unique" in pluto_idxs and "nyc_pluto_bin_unique" not in pluto_idxs:
        print("  ✓ nyc_pluto: bbl unique index present, legacy bin unique removed")
    else:
        print("  ✗ nyc_pluto: index state unexpected — investigate")
    for coll, spec in EVENT_BBL_DATE_INDEXES_TO_CREATE:
        coll_idxs = {i.get("name") for i in await _list_indexes(db, coll)}
        if spec["name"] in coll_idxs:
            print(f"  ✓ {coll}: (bbl, occurred_date) index present")
        else:
            print(f"  ✗ {coll}: missing {spec['name']}")
    pluto_count = await _count(db, PLUTO_COLLECTION)
    baseline_count = await _count(db, BASELINES_COLLECTION)
    if pluto_count == 0:
        print(f"  ✓ nyc_pluto cleared (0 docs); backfill will repopulate")
    else:
        print(f"  · nyc_pluto: {pluto_count:,} docs remain (unexpected after delete_many)")
    if baseline_count == 0:
        print(f"  ✓ statistical_baselines cleared (0 docs); aggregator will recompute")
    else:
        print(f"  · statistical_baselines: {baseline_count:,} docs remain")


# ── Main entry ───────────────────────────────────────────────────


async def main_async(mongo_url: str, db_name: str, execute: bool) -> int:
    if AsyncIOMotorClient is None:
        print("ERROR: motor not installed", file=sys.stderr)
        return 1
    client = AsyncIOMotorClient(mongo_url)
    try:
        db = client[db_name]
        snapshot = await print_preflight(db)
        await print_plan(db)
        if not execute:
            _print_section("DRY-RUN COMPLETE")
            print()
            print(
                "  No writes performed. Pass --execute to apply this plan.\n"
                "  Recommended: paste this dry-run output to operator review\n"
                "  before re-running with --execute.",
            )
            return 0
        try:
            await execute_migration(db)
        except Exception as e:
            print(
                f"\nERROR during migration: {e!r}\n"
                f"Partial state may be present. Inspect with the dry-run\n"
                f"output (run without --execute) and consult the runbook\n"
                f"for the rollback path.",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return 1
        await print_postflight(db)
        _print_section("DONE")
        print()
        print(
            "  Migration complete. Next steps:\n"
            "    1. Trigger initial backfill via\n"
            "       POST /api/admin/risk-score/backfill (multiple invocations\n"
            "       until ingestion_state.backfill_finished flips True for\n"
            "       every dataset — call until response shows all green).\n"
            "    2. Wait for 3:30 AM ET v2_2_baseline_aggregator cron OR\n"
            "       manually invoke via a Railway REPL.\n"
            "    3. Spot-check 3 project risk scores via\n"
            "       POST /api/projects/{id}/risk-score/calculate; verify the\n"
            "       peer-comparison subscore has non-zero peer_sample_size.\n"
            "    4. See docs/runbooks/path_a_bbl_keyed_peer_comparison.md\n"
            "       for the full post-deploy verification sequence.",
        )
        return 0
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V2.2.4 Path A migration — flip nyc_pluto unique key "
            "from bin to bbl + clean contaminated baseline."
        ),
    )
    parser.add_argument(
        "--execute", action="store_true",
        help=(
            "Apply the migration. Without this flag the script is "
            "dry-run only and exits 0 after printing the plan."
        ),
    )
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url:
        print(
            "ERROR: MONGO_URL environment variable required.\n"
            "Use a WRITE Atlas connection string for --execute mode.",
            file=sys.stderr,
        )
        return 1
    if not db_name:
        print(
            "ERROR: DB_NAME environment variable required.\n"
            "Production database is typically `blueview`.",
            file=sys.stderr,
        )
        return 1
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(
        f"V2.2.4 Path A migration  [{mode}]  "
        f"against {db_name} @ {_redact_mongo_url(mongo_url)}  "
        f"started at {datetime.now(timezone.utc).isoformat()}",
    )
    return asyncio.run(main_async(mongo_url, db_name, args.execute))


if __name__ == "__main__":
    sys.exit(main())
