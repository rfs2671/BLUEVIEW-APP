"""Backfill `filing_system` and `permit_class` on every existing
`dob_logs` permit record.

Both fields are deterministic functions of values already on the
record (`job_number` for filing_system; `work_type` for permit_class),
so this is a pure shape migration — no new data fetched, no risk
to live records, idempotent (re-running yields the same result).

Run once after deploy:

    python -m migrations.20260425_dob_logs_renewal_classification

Or in a Railway ssh session:

    cd backend && python migrations/20260425_dob_logs_renewal_classification.py

Prints a summary at the end. Safe to abort with Ctrl-C — the bulk
write is broken into 1k-doc batches so partial completion just
means the next run resumes the rest.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

# Allow running from either backend/ or backend/migrations/
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


# Inlined here so the migration can run from a slim environment without
# importing the full FastAPI app (which pulls apscheduler/resend/etc.).
# Both helpers MUST stay byte-identical to the versions in server.py —
# any divergence means new records and backfilled records get different
# classification values. Covered by tests in
# tests/test_permit_classification.py.

_SHED_WORK_TYPES = {"SH"}
_FENCE_WORK_TYPES = {"FN"}
_BLDRS_PAVEMENT_WORK_TYPES = {"BL"}


def _classify_filing_system(job_number):
    if not job_number:
        return "DOB_NOW"
    s = str(job_number).strip().upper()
    if s and s[0] in ("B", "M", "Q", "X", "R"):
        return "DOB_NOW"
    if s.replace("-", "").isdigit():
        return "BIS"
    return "DOB_NOW"


def _classify_permit_class(work_type):
    if not work_type:
        return "standard"
    wt = str(work_type).strip().upper()
    if wt in _SHED_WORK_TYPES:
        return "sidewalk_shed"
    if wt in _FENCE_WORK_TYPES:
        return "fence"
    if wt in _BLDRS_PAVEMENT_WORK_TYPES:
        return "bldrs_pavement"
    return "standard"


BATCH = 1000


async def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Only target permit rows missing either field. Re-running the
    # migration after a partial pass continues where it left off.
    query = {
        "record_type": "permit",
        "is_deleted": {"$ne": True},
        "$or": [
            {"filing_system": {"$exists": False}},
            {"filing_system": None},
            {"permit_class": {"$exists": False}},
            {"permit_class": None},
        ],
    }

    total = await db.dob_logs.count_documents(query)
    print(f"dob_logs permits needing classification: {total}")
    if total == 0:
        print("Nothing to do.")
        return 0

    counts: dict[str, int] = {}
    processed = 0

    # Atlas free tier disallows noTimeout cursors. Page through with
    # find().to_list(BATCH) using the same selector — each pass picks
    # up unclassified rows because the previous pass set their fields
    # and they no longer match the filter.
    from pymongo import UpdateOne

    while True:
        page = await db.dob_logs.find(
            query,
            {"_id": 1, "job_number": 1, "work_type": 1},
        ).limit(BATCH).to_list(BATCH)
        if not page:
            break

        ops = []
        for doc in page:
            job_number: Optional[str] = doc.get("job_number")
            work_type: Optional[str] = doc.get("work_type")
            fs = _classify_filing_system(job_number)
            pc = _classify_permit_class(work_type)
            counts[f"{fs}/{pc}"] = counts.get(f"{fs}/{pc}", 0) + 1
            ops.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$set": {"filing_system": fs, "permit_class": pc}},
            ))
        if ops:
            await db.dob_logs.bulk_write(ops, ordered=False)
            processed += len(ops)
            pct = (processed * 100) // max(total, 1)
            print(f"  ... {processed}/{total} ({pct}%)")
        if len(page) < BATCH:
            break

    print()
    print(f"Done. Processed {processed} permits.")
    print("Distribution by (filing_system / permit_class):")
    for k in sorted(counts):
        print(f"  {k:40s} {counts[k]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
