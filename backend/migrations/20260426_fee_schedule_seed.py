"""Seed the `fee_schedule` collection with the two date-windowed rules
covering DOB permit-renewal fees from 2020 forward.

Step 3 of the permit-renewal-v3 migration sequence
(~/.claude/plans/permit-renewal-v3.md).

Schema per entry:
    {
      "effective_from":         datetime,        # UTC, inclusive
      "effective_until":        datetime | None, # UTC, inclusive; None = no upper bound
      "applies_to":             list[str],       # ["ALL"] or specific work_types
      "min_renewal_fee_cents":  int,
      "split_rules":            dict,
      "notes":                  str,             # citation
      "created_at":             datetime,
      "updated_at":             datetime,
    }

Idempotency: keyed by `effective_from` (each rule has a unique start date).
Re-running matches an existing entry on `effective_from` and updates the
other fields in place — safe to re-run after editing the seed payload.

Index: (effective_from ASC, effective_until ASC). Created always (cheap,
idempotent on duplicate calls).

Run:
    # dry-run — show what would be inserted/updated, no writes
    python migrations/20260426_fee_schedule_seed.py --dry-run

    # live
    python migrations/20260426_fee_schedule_seed.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


# ── Seed payload — keep `notes` populated. When LL129 (or whatever)
#    supersedes LL128, you'll want to know what authority drove the
#    prior rule before adding the next one. ──

SEED: list[dict] = [
    {
        "effective_from":  datetime(2020, 1, 1, tzinfo=timezone.utc),
        "effective_until": datetime(2025, 12, 20, 23, 59, 59, tzinfo=timezone.utc),
        "applies_to":      ["ALL"],
        "min_renewal_fee_cents": 10_000,  # $100 pre-LL128 minimum
        "notes": (
            "DOB pre-LL128 schedule. $100 minimum across all work types, "
            "100% due at filing."
        ),
        "split_rules": {
            "all": {
                "at_filing_pct": 100,
                "before_issuance_pct": 0,
            }
        },
    },
    {
        "effective_from":  datetime(2025, 12, 21, tzinfo=timezone.utc),
        "effective_until": None,
        "applies_to":      ["ALL"],
        "min_renewal_fee_cents": 13_000,  # $130 LL128 minimum
        "notes": (
            "Local Law 128 of 2024, NYC Admin Code §28-112.2. "
            "Raised minimum permit fee $100 -> $130 effective 2025-12-21. "
            "Introduced split-payment rules: 50/50 for non-electrical work "
            "with CO change, 100% at filing for non-electrical without CO "
            "change, 50/50 for electrical with $130 minimum at filing."
        ),
        "split_rules": {
            "non_electrical_co_change": {
                "at_filing_pct": 50,
                "before_issuance_pct": 50,
            },
            "non_electrical_no_co_change": {
                "at_filing_pct": 100,
                "before_issuance_pct": 0,
            },
            "electrical": {
                "at_filing_pct": 50,
                "before_inspection_pct": 50,
                "min_at_filing_cents": 13_000,
            },
        },
    },
]


async def main(dry_run: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"=== Step 3 fee_schedule seed — {mode} ===\n")

    now = datetime.now(timezone.utc)

    def _norm(value):
        """Normalize for diff comparison so a re-run after BSON round-trip
        doesn't see phantom changes. Mongo's default client returns
        tz-naive datetimes (UTC); seed payload uses tz-aware. Coerce
        both to tz-aware UTC before comparing.
        """
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return value

    def _eq(a, b) -> bool:
        if isinstance(a, datetime) or isinstance(b, datetime):
            if a is None or b is None:
                return a is b
            return _norm(a) == _norm(b)
        return a == b

    inserts = []
    updates = []
    unchanged = []
    for entry in SEED:
        existing = await db.fee_schedule.find_one(
            {"effective_from": entry["effective_from"]}
        )
        if existing is None:
            inserts.append(entry)
        else:
            diff_fields = [
                k for k, v in entry.items()
                if not _eq(existing.get(k), v)
            ]
            if diff_fields:
                updates.append((existing["_id"], entry, diff_fields))
            else:
                unchanged.append(entry)

    print(f"Plan: insert={len(inserts)}, update={len(updates)}, "
          f"unchanged={len(unchanged)}\n")

    for e in inserts:
        print(f"  INSERT  effective_from={e['effective_from'].date()}  "
              f"fee=${e['min_renewal_fee_cents']/100:.0f}  "
              f"notes={e['notes'][:60]!r}")
    for _id, e, diff in updates:
        print(f"  UPDATE  effective_from={e['effective_from'].date()}  "
              f"fields={diff}")
    for e in unchanged:
        print(f"  KEEP    effective_from={e['effective_from'].date()}  "
              f"(no change)")

    print("\nIndex plan: (effective_from ASC, effective_until ASC)")

    if dry_run:
        print("\nDRY-RUN: no writes performed.")
        return 0

    # ── LIVE ──
    for entry in inserts:
        entry_with_meta = {**entry, "created_at": now, "updated_at": now}
        await db.fee_schedule.insert_one(entry_with_meta)
        print(f"  inserted effective_from={entry['effective_from'].date()}")

    for _id, entry, _diff in updates:
        await db.fee_schedule.update_one(
            {"_id": _id},
            {"$set": {**entry, "updated_at": now}},
        )
        print(f"  updated  effective_from={entry['effective_from'].date()}")

    # Index — idempotent.
    index_name = await db.fee_schedule.create_index(
        [("effective_from", 1), ("effective_until", 1)],
        name="fee_schedule_window",
    )
    print(f"\nIndex ensured: {index_name}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan only, no writes.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
