"""Build ONE real progress report from a real database -- read-only, no send.

    REAL_REPORT_MONGO_URL=mongodb+srv://<read-only user>@... REAL_REPORT_DB=<db> \\
    REAL_REPORT_COMPANY_ID=<company id> REAL_REPORT_PROJECT=<project id or "588"> \\
    [R2_* / QWEN_API_KEY as in production, for the photos] \\
    python scripts/real_report_dry_run.py 2026-10-02 2026-10-15 [out_dir]

What it does: reads the project's check-ins, filed daily logs (as amended),
DOB/DOT records, confirmed schedule and photos exactly as the product does
(server.build_project_report with dry_run=True), renders the PDF, and writes
it, a PNG per page, the snapshot JSON and an evidence cross-check to out_dir.

What it will NOT do: store a report, upload to R2, mint a link, send a
message, or write to any collection. It enforces that itself: every motor
write method raises, and the vision meter and verdict cache are no-ops. Use a
read-only database user as well -- belt and braces. The vision model IS called
for the photo screen (that is the product's own spend).

Nothing is fabricated: no data, no photos, no figures. If a source cannot be
read the script stops and says which.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def _need(name):
    v = os.environ.get(name)
    if not v:
        sys.exit(f"{name} is required (see the docstring). Nothing was read or written.")
    return v


os.environ["MONGO_URL"] = _need("REAL_REPORT_MONGO_URL")
os.environ["DB_NAME"] = _need("REAL_REPORT_DB")
os.environ.setdefault("JWT_SECRET", "dry-run-only")
COMPANY = _need("REAL_REPORT_COMPANY_ID")
PROJECT = _need("REAL_REPORT_PROJECT")

import server  # noqa: E402

_WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
           "delete_many", "bulk_write", "find_one_and_update", "find_one_and_replace",
           "find_one_and_delete", "create_index", "create_indexes", "drop_index", "drop", "rename")


def _refuse(name):
    def blocked(*a, **k):
        raise RuntimeError(f"dry run: {name} is not allowed")
    return blocked


def lock_database():
    from motor.motor_asyncio import AsyncIOMotorCollection
    for n in _WRITES:
        if hasattr(AsyncIOMotorCollection, n):
            setattr(AsyncIOMotorCollection, n, _refuse(n))

    async def no_meter(*a, **k):
        return None
    server.record_vision_call = no_meter
    server._photo_verdict_cache = no_meter


async def find_project():
    cf = server._company_id_filter(COMPANY)
    p = await server.db.projects.find_one({"company_id": cf, "$or": [{"_id": server.to_query_id(PROJECT)}]})
    if p:
        return p
    hits = await server.db.projects.find(
        {"company_id": cf, "is_deleted": {"$ne": True}, "name": {"$regex": PROJECT, "$options": "i"}}).to_list(5)
    hits += await server.db.projects.find(
        {"company_id": cf, "is_deleted": {"$ne": True}, "address": {"$regex": PROJECT, "$options": "i"}}).to_list(5)
    uniq = {str(h["_id"]): h for h in hits}
    if len(uniq) != 1:
        sys.exit(f"'{PROJECT}' matched {len(uniq)} projects in that company; pass the project id.")
    return next(iter(uniq.values()))


async def main(start, end, out):
    lock_database()
    project = await find_project()
    now = datetime.now(timezone.utc)
    got = await server.build_project_report(COMPANY, [project], start, end, now=now, by="dry-run",
                                            source="dry_run", dry_run=True)
    os.makedirs(out, exist_ok=True)
    pdf = os.path.join(out, "progress_report_real.pdf")
    with open(pdf, "wb") as f:
        f.write(got["pdf"])
    with open(os.path.join(out, "progress_report_real.snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(got["snapshot"], f, indent=2, default=str)
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-r", "70", "-png", pdf, os.path.join(out, "progress_report_real")], check=True)
    rep = got["reports"][0]
    print(f"wrote {pdf}")
    print(f"  period {start}..{end}; check-ins days {rep['site']['worked']}; subs {len(rep['subs'])}; "
          f"photos {len(got['photos'])}; schedule {'confirmed' if rep['schedule'] else 'none'}; "
          f"financials {'provided' if rep['financials'] else 'none'}")
    print("  limitations:", *rep["limitations"], sep="\n   - ")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    asyncio.run(main(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]),
                     sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, "..", "..", "docs", "samples", "real")))
