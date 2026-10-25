"""Queue existing drawing PDFs for tile compilation (the deep-zoom viewer).

    railway run python scripts/backfill_sheet_tiles.py                 # what WOULD be queued
    railway run python scripts/backfill_sheet_tiles.py --apply         # queue it
    railway run python scripts/backfill_sheet_tiles.py --apply --project <project_id> --limit 50
    railway run python scripts/backfill_sheet_tiles.py --apply --file <file_id> --force

Only QUEUES: it writes `sheet_tile_jobs` rows and a `tiles` summary on the file.
The running API's sheet tile worker drains the queue (oldest first, one file at
a time), so this is safe to run while users work. The API's own sweep does the
same thing 10 files at a time every 30 minutes; this is for clearing a backlog
at once. Dry run by default.

Connection: MONGO_URL / DB_NAME from the environment (what `railway run` injects).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId  # noqa: E402

from lib import sheet_pipeline  # noqa: E402

# server.is_generated_report, kept in step by tests/test_sheet_tiles.py
_GENERATED = re.compile(r"^\s*blueview[\s_\-]*report(?![A-Za-z])", re.I)


def _is_generated(name: str) -> bool:
    return bool(_GENERATED.match(str(name or "").strip()))


def _qid(value: str):
    try:
        return ObjectId(value)
    except Exception:
        return value


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="queue the files (default: only list them)")
    ap.add_argument("--project", help="only this project id")
    ap.add_argument("--file", help="only this file id")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--force", action="store_true", help="rebuild even if tiles exist")
    args = ap.parse_args(argv)

    from motor.motor_asyncio import AsyncIOMotorClient
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name:
        print("MONGO_URL and DB_NAME must be set (use `railway run`).", file=sys.stderr)
        return 2
    db = AsyncIOMotorClient(url)[name]

    if args.force and args.file:
        rows = await db.project_files.find({"_id": _qid(args.file)}).to_list(1)
    else:
        rows = await sheet_pipeline.files_needing_tiles(
            db, project_id=args.project, file_id=args.file, limit=args.limit,
            skip=_is_generated, to_query_id=_qid)
    print(f"{len(rows)} file(s) {'to queue' if args.apply else 'would be queued'}:")
    size = 0
    for r in rows:
        size += int(r.get("size") or 0)
        print(f"  {r.get('project_id')}  {r.get('_id')}  {int(r.get('size') or 0) / 1e6:8.1f} MB  {r.get('name')}")
    print(f"total {size / 1e6:.0f} MB of source PDF")
    if not args.apply:
        print("dry run: nothing written. Add --apply to queue.")
        return 0

    counts = {}
    for r in rows:
        outcome = await sheet_pipeline.enqueue(
            db, str(r["project_id"]), str(r.get("company_id") or ""), r, source="backfill",
            to_query_id=_qid, skip=_is_generated, force=args.force)
        counts[outcome] = counts.get(outcome, 0) + 1
    print("queued:", counts)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
