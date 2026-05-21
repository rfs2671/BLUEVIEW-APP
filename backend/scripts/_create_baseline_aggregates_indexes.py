"""Phase 1 Week 3 PR-C — pre-deploy Atlas index creation for the new
violation_baseline_aggregates collection.

Idempotent: create_index returns the existing index when an
identically-shaped one is already present. Mirrors the Phase 1 Week 1
_create_backfill_indexes.py pattern.

Indexes:

  violation_baseline_aggregates
    • { borough: 1, work_type: 1, phase: 1, window_end: 1 }   (lookup —
      drives GET /api/baseline-aggregates filter combinations + the
      Phase 1 Week 8+ k-NN cohort-similarity match queries)
    • { computed_at: 1 }                                       (cleanup —
      sortable for manual TTL pruning if the collection grows beyond
      operator-acceptable size)

Usage:
    MONGO_URL='mongodb+srv://...' DB_NAME='blueview' \\
        python -m scripts._create_baseline_aggregates_indexes

    # Plan-only (no writes) — prints what would be created
    python -m scripts._create_baseline_aggregates_indexes --dry-run

Exit codes:
  0 — all indexes ensured (or already present)
  1 — Mongo error (unreachable, permission denied, etc.)
  2 — bad invocation (missing env vars)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


@dataclass(frozen=True)
class IndexSpec:
    collection: str
    keys: List[Tuple[str, int]]
    name: str

    def keys_doc(self) -> List[Tuple[str, int]]:
        return list(self.keys)

    def kwargs(self) -> Dict[str, Any]:
        return {"name": self.name}


INDEX_SPECS: List[IndexSpec] = [
    IndexSpec(
        collection="violation_baseline_aggregates",
        keys=[
            ("borough",     1),
            ("work_type",   1),
            ("phase",       1),
            ("window_end",  1),
        ],
        name="vba_borough_work_type_phase_window_end",
    ),
    IndexSpec(
        collection="violation_baseline_aggregates",
        keys=[("computed_at", 1)],
        name="vba_computed_at",
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
    return f"{spec.collection}.{spec.name} = {{ {keys} }}"


async def ensure_indexes(db: Any, dry_run: bool = False) -> Dict[str, int]:
    counts = {"created_or_existing": 0, "errored": 0, "dry_run_planned": 0}
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
                    spec.keys_doc(), **spec.kwargs(),
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
