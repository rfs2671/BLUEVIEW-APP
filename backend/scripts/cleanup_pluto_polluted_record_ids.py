"""Phase V2.2.3 — One-shot cleanup of polluted PLUTO record_ids.

Pre-V2.2.3 the PLUTO canonicalizer synthesized record_id directly
from the raw Socrata BBL value (e.g. ``"4061730023.00000000"``),
producing record_ids like ``pluto_4061730023.00000000``. V2.2.3
added ``_normalize_natural_key`` to strip the trailing ``.0+``
suffix so new rows use the clean ``pluto_4061730023`` form. The
pre-V2.2.3 rows still sit in ``nyc_pluto`` with their polluted
record_ids — they will never collide with the new clean rows
(different record_id strings) but they ARE orphan duplicates of
the same physical lot, and they bloat the collection.

This script removes them. The match is a regex against record_id:
``\\.0+$`` — i.e. a literal dot followed by one or more zeros at
the end of the string. Clean V2.2.3 record_ids don't match
because the suffix is stripped before insertion; pre-V2.2.3 PLUTO
record_ids do match because they all carried ``.00000000``.
Other datasets (event collections) are unaffected because they
key on Socrata-provided IDs (e.g. ``isn_dob_bis_viol``) that
don't end in dot-zeros.

Designed as a one-shot operational script, not a scheduled job.
Run it once (after V2.2.3 has been live long enough for the
backfill to repopulate ``nyc_pluto`` with clean record_ids).
Then delete the file in a follow-up commit.

Usage:
    MONGO_URL='mongodb+srv://write_user:...@...' \\
    DB_NAME='blueview' \\
    python -m backend.scripts.cleanup_pluto_polluted_record_ids

The script:
  1. Reads MONGO_URL + DB_NAME from env (same convention as
     audit_production.py + cleanup_v21_inert_data.py +
     reset_ingestion_state_for_failed_datasets.py).
  2. Prints a PRE-CLEANUP count of polluted docs.
  3. Prompts on stdin for the literal string CONFIRM.
     Anything else (or EOF) aborts cleanly with no changes.
  4. Executes ``db.nyc_pluto.delete_many({record_id:
     {$regex: /\\.0+$/}})``.
  5. Prints POST-CLEANUP count (must be 0 to declare victory).

Exit codes:
    0 — cleanup completed (or aborted by operator at the prompt)
    1 — operational error (Mongo error, env-var missing, etc.)
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Optional

# Motor import deferred so the module can be syntax-checked in
# environments without the dep.
try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    AsyncIOMotorClient = None  # type: ignore


# ── Constants ────────────────────────────────────────────────────

CONFIRMATION_TOKEN = "CONFIRM"
PLUTO_COLLECTION = "nyc_pluto"
# Anchored-end regex: matches PLUTO record_ids whose BBL was not
# normalized (V2.2.2 era). Pre-V2.2.3 PLUTO always wrote a
# trailing ``.00000000``. Post-V2.2.3 writes have the suffix
# stripped before insertion.
POLLUTED_RECORD_ID_REGEX = r"\.0+$"


# ── Reports ──────────────────────────────────────────────────────


def _print_section(title: str) -> None:
    print()
    print("─" * 64)
    print(title)
    print("─" * 64)


async def count_polluted(db) -> int:
    """Count nyc_pluto docs whose record_id matches the polluted
    regex. Returns 0 if the collection doesn't exist."""
    names = await db.list_collection_names()
    if PLUTO_COLLECTION not in names:
        return 0
    return await db[PLUTO_COLLECTION].count_documents({
        "record_id": {"$regex": POLLUTED_RECORD_ID_REGEX},
    })


async def count_total(db) -> int:
    """Count total nyc_pluto docs (clean + polluted) — useful
    context for the operator before deletion."""
    names = await db.list_collection_names()
    if PLUTO_COLLECTION not in names:
        return 0
    return await db[PLUTO_COLLECTION].count_documents({})


async def print_pre_report(db) -> int:
    """Print PRE-CLEANUP report. Returns the polluted count so
    the confirmation prompt can quote it."""
    _print_section("PRE-CLEANUP")
    print()
    print(f"[{PLUTO_COLLECTION}] document counts:")
    total = await count_total(db)
    polluted = await count_polluted(db)
    clean = total - polluted
    if total == 0:
        print(f"  (collection {PLUTO_COLLECTION!r} does not exist or is empty)")
    else:
        print(f"  total docs:    {total:>10,}")
        print(f"  clean         {clean:>10,}")
        print(f"  polluted      {polluted:>10,}  (record_id matches /{POLLUTED_RECORD_ID_REGEX}/)")
    return polluted


async def print_post_report(db) -> None:
    _print_section("POST-CLEANUP")
    print()
    print(f"[{PLUTO_COLLECTION}] document counts:")
    total = await count_total(db)
    polluted = await count_polluted(db)
    clean = total - polluted
    print(f"  total docs:    {total:>10,}")
    print(f"  clean         {clean:>10,}")
    print(f"  polluted      {polluted:>10,}")
    print()
    print("[verdict]")
    if polluted == 0:
        print("  ✓ no polluted record_ids remain in nyc_pluto")
    else:
        print(
            f"  ✗ {polluted:,} polluted record_ids STILL present — "
            f"delete_many did not match expected set; investigate",
        )


# ── Confirmation prompt ──────────────────────────────────────────


def prompt_for_confirmation(polluted_count: int) -> bool:
    """Print the confirmation prompt (with N filled in from the
    pre-cleanup count) and read a single line from stdin. Return
    True iff the input was exactly the CONFIRMATION_TOKEN."""
    print()
    print(
        f"Type {CONFIRMATION_TOKEN} to delete {polluted_count:,} "
        f"polluted PLUTO docs (V2.2.2 era pre-normalization):",
    )
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        print("\n(aborted by Ctrl-C)", file=sys.stderr)
        return False
    return line.rstrip("\n") == CONFIRMATION_TOKEN


# ── Cleanup ──────────────────────────────────────────────────────


async def run_cleanup(db) -> int:
    """Execute the delete_many. Returns deleted_count."""
    res = await db[PLUTO_COLLECTION].delete_many({
        "record_id": {"$regex": POLLUTED_RECORD_ID_REGEX},
    })
    deleted = getattr(res, "deleted_count", 0) or 0
    print(
        f"  ✓ db.{PLUTO_COLLECTION}.delete_many "
        f"{{record_id: {{$regex: /{POLLUTED_RECORD_ID_REGEX}/}}}} → "
        f"deleted_count = {deleted:,}",
    )
    return deleted


# ── Main entry ───────────────────────────────────────────────────


async def main_async(mongo_url: str, db_name: str) -> int:
    if AsyncIOMotorClient is None:
        print(
            "ERROR: motor is not installed in this environment.",
            file=sys.stderr,
        )
        return 1
    client = AsyncIOMotorClient(mongo_url)
    try:
        db = client[db_name]
        polluted = await print_pre_report(db)
        if polluted == 0:
            print()
            print(
                "Nothing to clean up — 0 polluted record_ids match the "
                "regex. Exiting without prompting.",
            )
            return 0
        if not prompt_for_confirmation(polluted):
            print()
            print(
                "Confirmation token not provided — no changes made. "
                f"Re-run and type {CONFIRMATION_TOKEN} exactly to "
                f"proceed.",
            )
            return 0
        _print_section("EXECUTING")
        print()
        try:
            await run_cleanup(db)
        except Exception as e:
            print(
                f"\nERROR during cleanup: {e!r}\n"
                f"Pre-cleanup state still applies; partial state "
                f"may be present. Inspect the DB before re-running.",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return 1
        await print_post_report(db)
        _print_section("DONE")
        print()
        print(
            "Cleanup complete. Run this script ONCE — file should "
            "be deleted in a follow-up commit (no use after first "
            "successful run).",
        )
        return 0
    finally:
        client.close()


def _redact_mongo_url(url: str) -> str:
    """Strip credentials from a mongodb:// URL for safe logging."""
    try:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            _creds, host = rest.split("@", 1)
            return f"{scheme}://***@{host}"
        return url
    except Exception:
        return "<unparseable>"


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url:
        print(
            "ERROR: MONGO_URL environment variable required.\n"
            "Use a WRITE Atlas connection string for this script "
            "(deletes documents).",
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
    print(
        f"V2.2.3 PLUTO polluted-record_id cleanup against "
        f"{db_name} @ {_redact_mongo_url(mongo_url)} "
        f"(started at {datetime.now(timezone.utc).isoformat()})",
    )
    return asyncio.run(main_async(mongo_url, db_name))


if __name__ == "__main__":
    sys.exit(main())
