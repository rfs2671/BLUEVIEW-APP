"""Phase 1 Week 1 — pre-backfill Atlas index creation (Gate 2).

Idempotent: `create_index` is itself idempotent on Mongo (returns the
existing index name if one with the same spec already exists), so
re-running this script multiple times is safe — no drops, no rebuilds.

Run BEFORE invoking socrata_3year_backfill.py --execute. The unique
indexes act as a second-line guard against duplicate inserts even if
the backfill script's upsert filter logic is wrong.

Collections + indexes:

  socrata_ecb_violations_historical
    • { bin: 1 }                                            (lookup)
    • { boro: 1, issue_date: 1 }                            (compound)
    • { severity: 1 }                                       (filter)
    • { ecb_violation_number: 1 }  UNIQUE                   (dedupe key)

  socrata_permits_historical
    • { bbl: 1 }                                            (lookup)
    • { borough: 1, filing_reason: 1 }                      (compound)
    • { approved_date: 1 }                                  (range)
    • { permit_si_no: 1 }          UNIQUE                   (dedupe key)
      OPEN QUESTION: see socrata_3year_backfill.py for the natural-key
      rationale. If the operator switches the backfill to a composite
      key (job_filing_number, work_permit), this index must be dropped
      and re-created on the new fields before the next run.

  socrata_complaints_historical
    • { bin: 1, date_entered: 1 }                           (compound)
    • { community_board: 1, date_entered: 1 }               (compound)
    • { complaint_number: 1 }      UNIQUE                   (dedupe key)

Usage:
    MONGO_URL='mongodb+srv://...' DB_NAME='blueview' \
        python -m scripts._create_backfill_indexes

    # Plan-only (no writes) — prints what would be created
    python -m scripts._create_backfill_indexes --dry-run

Exit codes:
  0 — all indexes ensured (or already present)
  1 — Mongo error (unreachable, permission denied, conflict with an
      existing index that has the same name but different spec)
  2 — bad invocation (missing env vars)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


@dataclass(frozen=True)
class IndexSpec:
    """One index to ensure on one collection."""
    collection: str
    keys: List[Tuple[str, int]]
    name: str                      # explicit name so an accidental
                                   # rename later can't fork the index
    unique: bool = False
    sparse: bool = False

    def keys_doc(self) -> List[Tuple[str, int]]:
        return list(self.keys)

    def kwargs(self) -> Dict[str, Any]:
        kw: Dict[str, Any] = {"name": self.name}
        if self.unique:
            kw["unique"] = True
        if self.sparse:
            kw["sparse"] = True
        return kw


# Sparse on unique indexes: yes. Rows missing the natural key are
# logged + skipped by the backfill driver (so they shouldn't appear),
# but if a malformed row ever does land in the collection, a non-sparse
# unique index would error on the second null. Sparse keeps the unique
# guarantee for present-key rows without blowing up on absent-key rows.

INDEX_SPECS: List[IndexSpec] = [
    # ─── socrata_ecb_violations_historical (6bgk-3dad) ────────────
    IndexSpec(
        collection="socrata_ecb_violations_historical",
        keys=[("bin", 1)],
        name="ecb_bin_1",
    ),
    IndexSpec(
        collection="socrata_ecb_violations_historical",
        keys=[("boro", 1), ("issue_date", 1)],
        name="ecb_boro_1_issue_date_1",
    ),
    IndexSpec(
        collection="socrata_ecb_violations_historical",
        keys=[("severity", 1)],
        name="ecb_severity_1",
    ),
    IndexSpec(
        collection="socrata_ecb_violations_historical",
        keys=[("ecb_violation_number", 1)],
        name="ecb_violation_number_unique",
        unique=True,
        sparse=True,
    ),

    # ─── socrata_permits_historical (rbx6-tga4) ───────────────────
    IndexSpec(
        collection="socrata_permits_historical",
        keys=[("bbl", 1)],
        name="permits_bbl_1",
    ),
    IndexSpec(
        collection="socrata_permits_historical",
        keys=[("borough", 1), ("filing_reason", 1)],
        name="permits_borough_1_filing_reason_1",
    ),
    IndexSpec(
        collection="socrata_permits_historical",
        keys=[("approved_date", 1)],
        name="permits_approved_date_1",
    ),
    IndexSpec(
        collection="socrata_permits_historical",
        keys=[("permit_si_no", 1)],
        name="permits_permit_si_no_unique",
        unique=True,
        sparse=True,
    ),

    # ─── socrata_complaints_historical (eabe-havv) ────────────────
    IndexSpec(
        collection="socrata_complaints_historical",
        keys=[("bin", 1), ("date_entered", 1)],
        name="complaints_bin_1_date_entered_1",
    ),
    IndexSpec(
        collection="socrata_complaints_historical",
        keys=[("community_board", 1), ("date_entered", 1)],
        name="complaints_community_board_1_date_entered_1",
    ),
    IndexSpec(
        collection="socrata_complaints_historical",
        keys=[("complaint_number", 1)],
        name="complaints_complaint_number_unique",
        unique=True,
        sparse=True,
    ),
]


def _build_db():
    from motor.motor_asyncio import AsyncIOMotorClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise SystemExit(
            "MONGO_URL and DB_NAME environment variables are required."
        )
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


def _format_spec(spec: IndexSpec) -> str:
    keys = ", ".join(f"{k}: {v}" for k, v in spec.keys)
    flags = []
    if spec.unique:
        flags.append("UNIQUE")
    if spec.sparse:
        flags.append("sparse")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    return f"{spec.collection}.{spec.name} = {{ {keys} }}{flag_str}"


async def ensure_indexes(db: Any, dry_run: bool = False) -> Dict[str, int]:
    """Ensure every IndexSpec exists on `db`. Returns a count summary.

    Per-spec behavior:
      • If an index with `name` already exists and matches the spec
        → log "EXISTING" and skip (motor's create_index is idempotent
        for matching specs).
      • If an index with `name` already exists with a DIFFERENT spec
        → motor raises pymongo.errors.OperationFailure. We let it
        surface as an error — operator must resolve the conflict
        manually rather than have the script silently drop+rebuild.
      • Otherwise → log "CREATING" and create.

    Dry-run: walk the same flow but skip the actual call.
    """
    counts = {"created_or_existing": 0, "errored": 0, "dry_run_planned": 0}

    # Group by collection for tidier output.
    by_coll: Dict[str, List[IndexSpec]] = {}
    for s in INDEX_SPECS:
        by_coll.setdefault(s.collection, []).append(s)

    for coll_name, specs in by_coll.items():
        print(f"\n=== Collection: {coll_name} ===", flush=True)

        if dry_run:
            existing_names: set = set()
        else:
            try:
                existing = await db[coll_name].list_indexes().to_list(length=None)
                existing_names = {i.get("name") for i in existing}
            except Exception as e:
                print(f"  ! list_indexes failed: {e!r}", flush=True)
                counts["errored"] += len(specs)
                continue

        for spec in specs:
            label = _format_spec(spec)
            if dry_run:
                print(f"  PLAN     {label}", flush=True)
                counts["dry_run_planned"] += 1
                continue

            if spec.name in existing_names:
                print(f"  EXISTING {label}", flush=True)
                counts["created_or_existing"] += 1
                continue

            try:
                created_name = await db[coll_name].create_index(
                    spec.keys_doc(),
                    **spec.kwargs(),
                )
                print(f"  CREATED  {label} (name={created_name})",
                      flush=True)
                counts["created_or_existing"] += 1
            except Exception as e:
                print(f"  ERROR    {label}: {e!r}", flush=True)
                counts["errored"] += 1

    return counts


async def _amain(args: argparse.Namespace) -> int:
    if args.dry_run:
        print("DRY-RUN: no writes will be made.", flush=True)
        counts = await ensure_indexes(db=None, dry_run=True)  # type: ignore[arg-type]
        print(f"\nPlanned: {counts['dry_run_planned']} indexes.",
              flush=True)
        return 0

    db = _build_db()
    counts = await ensure_indexes(db, dry_run=False)
    print(
        f"\nSummary: created_or_existing={counts['created_or_existing']} "
        f"errored={counts['errored']}",
        flush=True,
    )
    return 1 if counts["errored"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print planned indexes without touching Mongo.",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
