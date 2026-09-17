"""Phase V2.2 — One-shot V2.1 inert-data cleanup.

V2.2 (with V2.2.1 + V2.2.1.1 patches) filters every read of the
`risk_scores` collection by `model_version: "statistical-v1"`.
The V2.1 heuristic-v1 rows in `risk_scores` and the entire V2.1
collections `risk_score_reviews` and `risk_score_calibration`
are inert — never read, never written. This script reclaims
that storage.

Designed as a one-shot operational script, NOT a scheduled job.
Run it once (after V2.2 is stable in production) and then
delete the file in a follow-up commit. Until then, the
deletion-by-confirmation pattern keeps it from being run
accidentally.

Usage:
    MONGO_URL='mongodb+srv://write_user:...@...' \\
    DB_NAME='blueview' \\
    python -m backend.scripts.cleanup_v21_inert_data

The script:
  1. Reads MONGO_URL + DB_NAME from env (same convention as
     backend/scripts/audit_production.py).
  2. Prints a PRE-CLEANUP report of what's currently in the DB.
  3. Prompts on stdin for the literal string CONFIRM. Anything
     else (or EOF) aborts cleanly with no changes made.
  4. Runs:
       db.risk_scores.delete_many({model_version: "heuristic-v1"})
       db.risk_score_reviews.drop() if it exists
       db.risk_score_calibration.drop() if it exists
  5. Prints a POST-CLEANUP report so the operator can verify
     the deltas before declaring victory.

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
from typing import Any, Dict, List, Optional

# ── PRODUCTION WRITE GUARD ──────────────────────────────────────────────────
# Every write below goes through `audited(...)`, which records it in audit_logs
# with actor "script:cleanup_v21_inert_data", the session and the reason.
# Without --i-know the handle is unwrapped and nothing is written. See
# prod_guard.
#
# ITS EXISTING GATE WAS A TYPED CONFIRMATION READ FROM STDIN, which stops an
# accident and records nothing: after the run there is no row saying who typed
# CONFIRM or why, and this script drops two collections and deletes from a
# third. The prompt STAYS -- it is a second pair of eyes on an irreversible
# drop -- but `--i-know` now sits in front of it, so the flag is what makes the
# reason and the session unavoidable.
import argparse                                                 # noqa: E402
import os as _g_os                                              # noqa: E402
import sys as _g_sys                                            # noqa: E402
_g_sys.path.insert(0, _g_os.path.dirname(_g_os.path.abspath(__file__)))
from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag, report_dry_run,
)

NAME = "cleanup_v21_inert_data"

# Motor import deferred so the module can be syntax-checked /
# imported in environments without the dep.
try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    AsyncIOMotorClient = None  # type: ignore


# ── Constants ────────────────────────────────────────────────────

CONFIRMATION_TOKEN = "CONFIRM"
INERT_MODEL_VERSION = "heuristic-v1"
LIVE_MODEL_VERSION  = "statistical-v1"

# The two V2.1 collections to drop. They've been inert since the
# V2.2 deploy; V2.2 doesn't read or write them.
V21_COLLECTIONS_TO_DROP = (
    "risk_score_reviews",
    "risk_score_calibration",
)


# ── Pre/post reports ─────────────────────────────────────────────


async def _risk_scores_by_model_version(db) -> Dict[str, int]:
    """Group risk_scores by model_version. Uses an aggregation
    pipeline (one round-trip) — simpler than walking the cursor."""
    counts: Dict[str, int] = {}
    pipeline = [
        {"$group": {
            "_id": "$model_version",
            "count": {"$sum": 1},
        }},
    ]
    async for row in db["risk_scores"].aggregate(pipeline):
        key = row.get("_id")
        # Map None/missing to a label we can print.
        label = key if key else "<missing model_version>"
        counts[label] = int(row.get("count", 0))
    return counts


async def _collection_exists_and_count(
    db, collection_name: str,
) -> Optional[int]:
    """Return doc count if the collection exists, else None.
    `list_collection_names()` is the cheap existence check on
    Atlas Flex tier."""
    names = await db.list_collection_names()
    if collection_name not in names:
        return None
    return await db[collection_name].count_documents({})


def _print_section(title: str) -> None:
    print()
    print("─" * 64)
    print(title)
    print("─" * 64)


def _print_counts_by_model_version(counts: Dict[str, int]) -> None:
    if not counts:
        print("  (risk_scores collection is empty)")
        return
    width = max(len(k) for k in counts)
    total = 0
    for key, count in sorted(counts.items()):
        print(f"  {key.ljust(width)}  {count:>10,}")
        total += count
    print(f"  {'-' * width}  {'-' * 10}")
    print(f"  {'TOTAL'.ljust(width)}  {total:>10,}")


async def print_pre_report(db) -> Dict[str, Any]:
    """Print PRE-CLEANUP report and return the snapshot dict so
    the post-report can show deltas."""
    _print_section("PRE-CLEANUP")

    print()
    print("[risk_scores] documents grouped by model_version:")
    rs_counts = await _risk_scores_by_model_version(db)
    _print_counts_by_model_version(rs_counts)

    coll_states: Dict[str, Optional[int]] = {}
    for name in V21_COLLECTIONS_TO_DROP:
        count = await _collection_exists_and_count(db, name)
        coll_states[name] = count

    print()
    print("[V2.1 collections] presence + document count:")
    for name in V21_COLLECTIONS_TO_DROP:
        count = coll_states[name]
        if count is None:
            print(f"  {name}  (collection does not exist)")
        else:
            print(f"  {name}  {count:,} documents")

    return {
        "risk_scores_by_model_version": rs_counts,
        "v21_collection_counts": coll_states,
    }


async def print_post_report(db, pre_snapshot: Dict[str, Any]) -> None:
    """Print POST-CLEANUP report — the same shape as the pre-
    report so the operator can eyeball deltas. Specifically
    expected after a successful cleanup:
      • heuristic-v1 row count is 0 OR the key is absent.
      • The two V2.1 collections are absent.
    """
    _print_section("POST-CLEANUP")

    print()
    print("[risk_scores] documents grouped by model_version:")
    rs_counts = await _risk_scores_by_model_version(db)
    _print_counts_by_model_version(rs_counts)

    print()
    print("[V2.1 collections] presence + document count:")
    for name in V21_COLLECTIONS_TO_DROP:
        count = await _collection_exists_and_count(db, name)
        if count is None:
            print(f"  {name}  (dropped)")
        else:
            print(
                f"  {name}  STILL PRESENT — {count:,} documents "
                f"(drop did not take effect)",
            )

    # Sanity-check verdicts.
    print()
    print("[verdict]")
    heuristic_remaining = rs_counts.get(INERT_MODEL_VERSION, 0)
    if heuristic_remaining == 0:
        print(f"  ✓ no {INERT_MODEL_VERSION} rows remain in risk_scores")
    else:
        print(
            f"  ✗ {heuristic_remaining:,} {INERT_MODEL_VERSION} rows "
            f"STILL in risk_scores — investigate",
        )
    for name in V21_COLLECTIONS_TO_DROP:
        existed_before = pre_snapshot["v21_collection_counts"].get(name) is not None
        try:
            still_exists = await _collection_exists_and_count(db, name) is not None
        except Exception:
            still_exists = True
        if existed_before and not still_exists:
            print(f"  ✓ {name} dropped successfully")
        elif not existed_before and not still_exists:
            print(f"  · {name} was already absent (no-op)")
        else:
            print(f"  ✗ {name} still exists — drop did not take effect")


# ── Confirmation prompt ──────────────────────────────────────────


def prompt_for_confirmation() -> bool:
    """Print the confirmation prompt and read a single line from
    stdin. Return True iff the input was exactly the
    CONFIRMATION_TOKEN. Any other input (including EOF, empty
    line, or trailing whitespace that doesn't match) returns
    False and aborts the cleanup with no changes."""
    print()
    print(
        f"About to: deleteMany {INERT_MODEL_VERSION} from risk_scores, "
        f"drop risk_score_reviews, drop risk_score_calibration. "
        f"Type {CONFIRMATION_TOKEN} to proceed:",
    )
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        print("\n(aborted by Ctrl-C)", file=sys.stderr)
        return False
    # Strict equality — no leniency on whitespace or case.
    return line.rstrip("\n") == CONFIRMATION_TOKEN


# ── Cleanup ──────────────────────────────────────────────────────


async def run_cleanup(db) -> Dict[str, Any]:
    """Execute the three deletion operations and return a summary
    with per-operation results."""
    summary: Dict[str, Any] = {}

    # 1. delete_many heuristic-v1 from risk_scores.
    res = await db["risk_scores"].delete_many(
        {"model_version": INERT_MODEL_VERSION},
    )
    deleted = getattr(res, "deleted_count", 0) or 0
    summary["risk_scores_deleted"] = deleted
    print(
        f"  ✓ db.risk_scores.delete_many "
        f"{{model_version: \"{INERT_MODEL_VERSION}\"}} → "
        f"deleted_count = {deleted:,}",
    )

    # 2. + 3. drop the V2.1 collections (idempotent — drop is a
    #          no-op if the collection doesn't exist).
    existing = set(await db.list_collection_names())
    for name in V21_COLLECTIONS_TO_DROP:
        if name in existing:
            await db[name].drop()
            summary[f"{name}_dropped"] = True
            print(f"  ✓ db.{name}.drop() → dropped")
        else:
            summary[f"{name}_dropped"] = False
            print(f"  · db.{name}.drop() → did not exist (no-op)")

    return summary


# ── Main entry ───────────────────────────────────────────────────


async def main_async(mongo_url: str, db_name: str, args) -> int:
    if AsyncIOMotorClient is None:
        print(
            "ERROR: motor is not installed in this environment.",
            file=sys.stderr,
        )
        return 1
    client = AsyncIOMotorClient(mongo_url)
    try:
        db = audited(client[db_name], args, NAME)
        # PRE.
        pre = await print_pre_report(db)
        # --i-know IS THE OUTER GATE. Ahead of the typed confirmation, not
        # instead of it: without the flag this stops at the pre-report, which
        # is the read-only half and the useful thing to run first anyway.
        if not check_guard(args):
            report_dry_run(
                f"delete risk_scores rows with model_version "
                f"{INERT_MODEL_VERSION!r}, then drop "
                + " and ".join(V21_COLLECTIONS_TO_DROP))
            return 0
        # CONFIRM.
        if not prompt_for_confirmation():
            print()
            print(
                "Confirmation token not provided — no changes made. "
                "Re-run and type CONFIRM exactly to proceed.",
            )
            return 0
        # EXECUTE.
        _print_section("EXECUTING")
        print()
        try:
            await run_cleanup(db)
        except Exception as e:
            print(
                f"\nERROR during cleanup: {e!r}\n"
                f"Pre-cleanup report still applies; partial state "
                f"may be present. Inspect the DB before re-running.",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return 1
        # POST.
        await print_post_report(db, pre)

        _print_section("DONE")
        print()
        print(
            f"Cleanup complete. Run this script ONCE — file should "
            f"be deleted in a follow-up commit (no use after first "
            f"successful run).",
        )
        return 0
    finally:
        client.close()


def main(args) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url:
        print(
            "ERROR: MONGO_URL environment variable required.\n"
            "Use a WRITE Atlas connection string for this script "
            "(unlike audit_production.py which is read-only).",
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
        f"V2.1 inert-data cleanup against {db_name} @ "
        f"{_redact_mongo_url(mongo_url)} "
        f"(started at {datetime.now(timezone.utc).isoformat()})",
    )
    return asyncio.run(main_async(mongo_url, db_name, args))


def _redact_mongo_url(url: str) -> str:
    """Strip credentials from a mongodb:// URL for safe logging."""
    try:
        # mongodb+srv://user:pass@host/... → mongodb+srv://***@host/...
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            _creds, host = rest.split("@", 1)
            return f"{scheme}://***@{host}"
        return url
    except Exception:
        return "<unparseable>"


if __name__ == "__main__":
    # BEFORE THE PARSER, so a legacy write flag is refused by name rather than
    # dying as an unrecognised argument. This script never had one, but an
    # operator reaching for `--execute` on a delete-and-drop script should meet
    # a sentence, not "unrecognized arguments".
    refuse_legacy_flag()
    _ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_guard_args(_ap)
    _args = _ap.parse_args()
    # VALIDATED FIRST: `--i-know` with no reason is an argument error, and it
    # should not have to wait behind a missing MONGO_URL to be reported.
    check_guard(_args)
    sys.exit(main(_args))
