"""Phase V2.2.2 — One-shot ingestion-state reset for failed datasets.

The first production V2.2 backfill silently marked
``dob_inspections`` and ``dob_permits`` as finished=True without
ever ingesting a row, due to two configuration bugs that V2.2.2
fixes:

  • BUG 1 — dob_inspections used the wrong Socrata dataset id
    (ic3t-wcy2 → 400 errors → 0 rows → marked finished).
  • BUG 2 — dob_permits used a WHERE column that doesn't exist
    on the dataset (issuance_date instead of filing_date),
    yielding clean 200s with empty bodies → marked finished.

V2.2.2 also fixes the underlying architectural bug (BUG 3) that
let "page returned 0 rows" be conflated with "dataset
exhausted". But fixing the gate doesn't un-set the
already-persisted ``backfill_finished: True`` rows for those
two datasets — the cron will skip them on the next run unless
we explicitly reset.

This script does exactly one thing: for each of
``dob_inspections`` and ``dob_permits``, set the
``ingestion_state`` row to a clean re-attempt state:

    {
        dataset:            "<dataset>",
        backfill_offset:    0,
        backfill_finished:  False,
        had_full_page:      False,
        last_page_pulled_at: None,
        last_page_size:     None,
    }

PLUTO is NOT reset here — its initial backfill returned
finished=False already (5000 rows seen, 0 upserted), so the
next admin-triggered backfill will re-attempt PLUTO naturally
once the V2.2.2 PLUTO record-id fallback ships.

Usage:
    MONGO_URL='mongodb+srv://write_user:...@...' \\
    DB_NAME='blueview' \\
    python -m backend.scripts.reset_ingestion_state_for_failed_datasets

The script:
  1. Reads MONGO_URL + DB_NAME from env (same convention as
     backend/scripts/audit_production.py + cleanup_v21_inert_data.py).
  2. Prints a PRE-RESET report of the current ingestion_state row
     for the two affected datasets.
  3. Prompts on stdin for the literal string CONFIRM. Anything
     else (or EOF) aborts cleanly with no changes made.
  4. Performs the two ingestion_state updates.
  5. Prints a POST-RESET report so the operator can verify the
     deltas before declaring victory.

Exit codes:
    0 — reset completed (or aborted by operator at the prompt)
    1 — operational error (Mongo error, env-var missing, etc.)
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    AsyncIOMotorClient = None  # type: ignore


# ── Constants ────────────────────────────────────────────────────

CONFIRMATION_TOKEN = "CONFIRM"
INGESTION_STATE_COLLECTION = "ingestion_state"

# Datasets that received `finished=True` from the broken first
# backfill due to BUG 1 / BUG 2. PLUTO is intentionally absent —
# its first backfill already produced finished=False so it
# re-runs naturally.
DATASETS_TO_RESET = (
    "dob_inspections",
    "dob_permits",
)


# ── Reports ──────────────────────────────────────────────────────


def _print_section(title: str) -> None:
    print()
    print("─" * 64)
    print(title)
    print("─" * 64)


def _format_state_doc(doc: Optional[Dict[str, Any]]) -> str:
    if doc is None:
        return "(no ingestion_state row exists)"
    keys_to_show = (
        "backfill_offset",
        "backfill_finished",
        "had_full_page",
        "last_page_pulled_at",
        "last_page_size",
        "updated_at",
    )
    parts = [
        f"{k}={doc.get(k, '<unset>')!r}" for k in keys_to_show
    ]
    return "{ " + ", ".join(parts) + " }"


async def print_pre_report(db) -> Dict[str, Any]:
    _print_section("PRE-RESET")
    print()
    print("[ingestion_state] current state for affected datasets:")
    snapshot: Dict[str, Any] = {}
    for ds in DATASETS_TO_RESET:
        doc = await db[INGESTION_STATE_COLLECTION].find_one(
            {"dataset": ds},
        )
        snapshot[ds] = doc
        print(f"  {ds}:  {_format_state_doc(doc)}")
    return snapshot


async def print_post_report(db, pre_snapshot: Dict[str, Any]) -> None:
    _print_section("POST-RESET")
    print()
    print("[ingestion_state] state after reset:")
    for ds in DATASETS_TO_RESET:
        doc = await db[INGESTION_STATE_COLLECTION].find_one(
            {"dataset": ds},
        )
        print(f"  {ds}:  {_format_state_doc(doc)}")
    # Verdict.
    print()
    print("[verdict]")
    for ds in DATASETS_TO_RESET:
        doc = await db[INGESTION_STATE_COLLECTION].find_one(
            {"dataset": ds},
        )
        if doc is None:
            print(f"  ✗ {ds}: ingestion_state row missing post-reset")
            continue
        offset_ok = int(doc.get("backfill_offset", -1) or 0) == 0
        finished_ok = doc.get("backfill_finished") is False
        if offset_ok and finished_ok:
            print(
                f"  ✓ {ds}: backfill_offset=0, backfill_finished=False "
                f"(ready for re-attempt)",
            )
        else:
            print(
                f"  ✗ {ds}: reset did NOT take effect "
                f"(offset={doc.get('backfill_offset')}, "
                f"finished={doc.get('backfill_finished')})",
            )


# ── Confirmation prompt ──────────────────────────────────────────


def prompt_for_confirmation() -> bool:
    print()
    print(
        f"About to reset ingestion_state for {list(DATASETS_TO_RESET)} "
        f"to {{backfill_offset: 0, backfill_finished: false, "
        f"had_full_page: false}}. Type {CONFIRMATION_TOKEN} to "
        f"proceed:",
    )
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        print("\n(aborted by Ctrl-C)", file=sys.stderr)
        return False
    return line.rstrip("\n") == CONFIRMATION_TOKEN


# ── Reset ────────────────────────────────────────────────────────


async def run_reset(db) -> Dict[str, Any]:
    """Execute the per-dataset reset. Idempotent — re-running on
    an already-reset dataset is a no-op."""
    summary: Dict[str, Any] = {}
    now = datetime.now(timezone.utc)
    for ds in DATASETS_TO_RESET:
        # We $set the whole reset shape so a partially-populated
        # state row gets fully cleaned. Last-run/last-page fields
        # are nulled out so a future audit doesn't see stale
        # post-bug timestamps.
        update = {
            "$set": {
                "dataset": ds,
                "backfill_offset": 0,
                "backfill_finished": False,
                "had_full_page": False,
                "last_page_pulled_at": None,
                "last_page_size": None,
                "updated_at": now,
                # Keep an audit trail of the reset itself so a
                # future operator can see this cleanup happened.
                "v2_2_2_reset_at": now,
            },
        }
        res = await db[INGESTION_STATE_COLLECTION].update_one(
            {"dataset": ds}, update, upsert=True,
        )
        summary[ds] = {
            "matched_count":  getattr(res, "matched_count", None),
            "modified_count": getattr(res, "modified_count", None),
            "upserted_id":    getattr(res, "upserted_id", None),
        }
        print(
            f"  ✓ {ds}: reset → backfill_offset=0, "
            f"backfill_finished=False, had_full_page=False",
        )
    return summary


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
        pre = await print_pre_report(db)
        if not prompt_for_confirmation():
            print()
            print(
                "Confirmation token not provided — no changes made. "
                "Re-run and type CONFIRM exactly to proceed.",
            )
            return 0
        _print_section("EXECUTING")
        print()
        try:
            await run_reset(db)
        except Exception as e:
            print(
                f"\nERROR during reset: {e!r}\n"
                f"Pre-reset state still applies; partial state "
                f"may be present. Inspect the DB before re-running.",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return 1
        await print_post_report(db, pre)
        _print_section("DONE")
        print()
        print(
            "Reset complete. Next admin-triggered "
            "POST /api/admin/risk-score/backfill will re-attempt "
            "dob_inspections and dob_permits with V2.2.2 fixed "
            "config. PLUTO is also re-attempted on that same "
            "invocation (its prior run had finished=False).",
        )
        return 0
    finally:
        client.close()


def _redact_mongo_url(url: str) -> str:
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
            "Use a WRITE Atlas connection string for this script.",
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
        f"V2.2.2 ingestion-state reset against {db_name} @ "
        f"{_redact_mongo_url(mongo_url)} "
        f"(started at {datetime.now(timezone.utc).isoformat()})",
    )
    return asyncio.run(main_async(mongo_url, db_name))


if __name__ == "__main__":
    sys.exit(main())
