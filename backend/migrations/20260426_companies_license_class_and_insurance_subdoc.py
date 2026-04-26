"""Backfill `license_class` (+ siblings) on every company doc, and
stamp `source: "manual_entry"` on every legacy insurance subdoc.

Step 2 of the permit-renewal-v3 migration sequence
(~/.claude/plans/permit-renewal-v3.md).

NOTE — backfill assumption:
    Pre-this-deploy `gc_insurance_records[*]` rows whose `source` field
    is missing or null are stamped `"manual_entry"`.

    This is semantically correct because BIS auto-fetch was disabled
    BEFORE any code shipped that could write to `gc_insurance_records`
    via a non-manual path. The only way a legacy record could exist is
    through the `PUT /api/admin/company/insurance/manual` Settings flow.

    If a future audit ever finds a record that should have been
    `coi_ocr` or `dob_now_portal` but got stamped `manual_entry` here,
    that means a non-manual code path leaked records into prod before
    this migration ran — a separate bug, not a backfill mistake.

Run:
    # dry-run (counts + distribution, no writes)
    python migrations/20260426_companies_license_class_and_insurance_subdoc.py --dry-run

    # live
    python migrations/20260426_companies_license_class_and_insurance_subdoc.py

Idempotent: re-running after a complete pass finds nothing to update.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


# Inlined — must stay byte-identical to the equivalent live-write logic
# in server.py / permit_renewal.py. If either drifts, new docs and
# backfilled docs disagree on classification.

def classify_license(company: dict) -> dict:
    """Return the four license_* fields for a company doc.

    Rule:
      gc_license_number non-empty  -> GC_LICENSED / DOB / auto
      hic_license_number non-empty -> HIC        / DCWP / auto  (future)
      neither                      -> NONE       / null / auto
    """
    gc = (company.get("gc_license_number") or "").strip()
    hic = (company.get("hic_license_number") or "").strip()
    if gc:
        return {
            "license_class": "GC_LICENSED",
            "license_authority": "DOB",
            "license_class_source": "auto",
        }
    if hic:
        return {
            "license_class": "HIC",
            "license_authority": "DCWP",
            "license_class_source": "auto",
        }
    return {
        "license_class": "NONE",
        "license_authority": None,
        "license_class_source": "auto",
    }


async def main(dry_run: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"=== Step 2 backfill — {mode} ===\n")

    # ── Part A: top-level license_class on companies ──
    company_query = {
        "is_deleted": {"$ne": True},
        "$or": [
            {"license_class": {"$exists": False}},
            {"license_class": None},
        ],
    }

    total_companies = await db.companies.count_documents(company_query)
    print(f"Companies needing license_class classification: {total_companies}")

    company_dist: dict[str, int] = {}
    company_ops = []  # only used when not dry_run
    cursor = db.companies.find(
        company_query,
        {"_id": 1, "name": 1, "gc_license_number": 1, "hic_license_number": 1},
    )
    docs = await cursor.to_list(length=None)
    for doc in docs:
        cls = classify_license(doc)
        key = f"{cls['license_class']} ({cls['license_authority'] or '—'})"
        company_dist[key] = company_dist.get(key, 0) + 1
        if not dry_run:
            from pymongo import UpdateOne
            company_ops.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$set": cls},
            ))
        print(f"  - {doc.get('name')!r:50s} -> {cls['license_class']}")

    print()
    if total_companies:
        print("Company distribution:")
        for k in sorted(company_dist):
            print(f"  {k:30s} {company_dist[k]}")
    print()

    # ── Part B: source stamping on existing insurance subdocs ──
    # We pull every company that has any gc_insurance_records, then
    # check each subdoc for a missing/null source. Mongo's array-elem
    # update with arrayFilters lets us flip only the offending rows.
    # The match here is intentionally broad — the per-element update
    # filters on the arrayFilter, so docs with all-good subdocs result
    # in a no-op.
    ins_query = {
        "is_deleted": {"$ne": True},
        "gc_insurance_records": {"$exists": True, "$ne": []},
    }
    ins_companies = await db.companies.find(
        ins_query,
        {"_id": 1, "name": 1, "gc_insurance_records": 1},
    ).to_list(length=None)

    subdocs_needing_source = 0
    subdoc_companies_touched = 0
    for c in ins_companies:
        records = c.get("gc_insurance_records") or []
        legacy = [
            r for r in records
            if isinstance(r, dict) and not r.get("source")
        ]
        if legacy:
            subdoc_companies_touched += 1
            subdocs_needing_source += len(legacy)
            print(
                f"  - {c.get('name')!r:50s} "
                f"{len(legacy)} subdoc(s) -> source='manual_entry'"
            )

    print()
    print(f"Insurance subdocs needing source stamp: {subdocs_needing_source} "
          f"across {subdoc_companies_touched} company(ies)")
    print()

    if dry_run:
        print("DRY-RUN: no writes performed.")
        print("Re-run without --dry-run to apply.")
        return 0

    # ── LIVE: apply ──
    if company_ops:
        from pymongo import UpdateOne  # noqa: F401
        await db.companies.bulk_write(company_ops, ordered=False)
        print(f"Wrote license_class on {len(company_ops)} companies.")

    if subdocs_needing_source:
        # arrayFilters update: stamp source on every subdoc where
        # source is missing/null.
        result = await db.companies.update_many(
            {"is_deleted": {"$ne": True}, "gc_insurance_records": {"$exists": True}},
            {"$set": {"gc_insurance_records.$[elem].source": "manual_entry"}},
            array_filters=[
                {"$or": [
                    {"elem.source": {"$exists": False}},
                    {"elem.source": None},
                ]}
            ],
        )
        print(f"Stamped source='manual_entry' on subdocs across "
              f"{result.modified_count} company doc(s).")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print counts + distribution, perform no writes.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
