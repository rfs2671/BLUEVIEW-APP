"""Delete derived plan data whose source file no longer exists.

WHAT THIS IS FOR
================

The 2026-09-17 re-index of 588 Boyland left 26 pages of `AR - 3.28.25.pdf` at
`index_version: 2`, `page_complete: false`, under a `file_id` with no
`project_files` row — beside the live 26-page copy of the same drawing set.
They are not current, nothing can reach them, and they sit in every census of
what the corpus contains.

WHAT IT WILL NOT TOUCH
======================

DERIVED DATA ONLY: document_page_index, document_page_chunks, plan_records.

It never deletes a `project_files` row and never deletes anything in R2. A
customer-uploaded original is not derived data and is not cleaned up by a
sweep — if an orphan's page images are still in the bucket, this REPORTS the
keys and stops. Deleting them belongs to the scrub, which is a separate piece
of work with its own confirmation.

It is also scoped to ONE project and refuses to run without `--project`.

THE GUARD IS NOT OPTIONAL HERE
=============================

This is a DELETE against production, run through `railway run`, which connects
from the laptop and reaches no container: no HTTP log, no application audit
row, and Atlas shared tier has no database auditing. That is exactly the hole
prod_guard was written to close, and on 2026-09-17 the first version of this
file was run without it — 26 rows left the database and the only trace was a
terminal that has since scrolled.

So it takes `--i-know --reason --session` like every other writer here, and
every delete goes through `audited()`.

USAGE
=====

    python -m scripts.delete_orphan_plan_pages --project <id>
    python -m scripts.delete_orphan_plan_pages --project <id> \
        --i-know --reason "<why>" --session <id>

There is no default host, no hardcoded URL and no network call: it reads
MONGO_URL from the environment, so `railway run` decides which database.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from pymongo import MongoClient

from scripts.probe_helpers import counted, describe, require_fields
from scripts.prod_guard import (
    add_guard_args, audited, check_guard, refuse_legacy_flag, report_dry_run,
    script_name,
)


def main() -> int:
    refuse_legacy_flag()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True,
                    help="project id; this script refuses to sweep everything")
    add_guard_args(ap)
    args = ap.parse_args()

    url = os.environ.get("MONGO_URL")
    if not url:
        print("MONGO_URL is not set. Run this under `railway run`.")
        return 2
    client = MongoClient(url)
    db = audited(client[os.environ.get("DB_NAME", "test_database")], args,
                 script_name())
    pid = str(args.project)

    live = {str(f["_id"]) for f in
            db.project_files.find({"project_id": pid}, {"_id": 1})}
    if not live:
        print(f"project {pid} has no project_files rows at all — refusing. "
              f"An empty file list is how a sweep deletes a whole project.")
        return 2

    pages = list(db.document_page_index.find(
        {"project_id": pid},
        {"file_id": 1, "file_name": 1, "page_number": 1, "index_version": 1,
         "sheet_number": 1, "page_image_r2_key": 1, "page_base_r2_key": 1,
         "page_thumb_r2_key": 1}))
    # ── READ THE KEYS BEFORE COUNTING ON THEM ──────────────────────────────
    #
    # This matters more here than in any probe. "Orphaned" is decided by
    # `file_id not in live` — so if `file_id` were named something else, or
    # were absent from the projection, EVERY page would read as an orphan and
    # this script would delete the whole project's index while reporting a
    # tidy number. require_fields turns that into a refusal.
    print(describe(pages, "file_id", "index_version", "file_name"))
    require_fields(pages, "file_id")

    orphans = [p for p in pages if str(p.get("file_id")) not in live]
    if not orphans:
        print(f"{len(pages)} pages, {len(live)} files, no orphans.")
        return 0
    if len(orphans) == len(pages):
        print(f"ALL {len(pages)} pages read as orphaned. That is what a broken "
              f"join looks like, not a project whose files all vanished. "
              f"Refusing.")
        return 2

    by_file = Counter(str(p.get("file_id")) for p in orphans)
    print(f"{len(pages)} pages on this project; {len(orphans)} orphaned "
          f"across {len(by_file)} missing file(s):\n")
    page_ids = [str(p["_id"]) for p in orphans]
    for fid, n in by_file.most_common():
        rows = [p for p in orphans if str(p.get("file_id")) == fid]
        names = {p.get("file_name") for p in rows}
        vers = {v: counted(rows, "index_version", lambda x, want=v: x == want)
                for v in {r.get("index_version") for r in rows}}
        sheets = sorted({str(p.get("sheet_number")) for p in rows})
        print(f"  file_id {fid}  ({n} pages)")
        print(f"     file_name on the rows : {names}")
        print(f"     index_version         : {vers}")
        print(f"     sheets                : {sheets[:8]}"
              f"{' ...' if len(sheets) > 8 else ''}")

    chunks = db.document_page_chunks.count_documents({"page_id": {"$in": page_ids}})
    recs = db.plan_records.count_documents({"page_id": {"$in": page_ids}})
    print(f"\n  derived rows that go with them:")
    print(f"     document_page_index : {len(orphans)}")
    print(f"     document_page_chunks: {chunks}")
    print(f"     plan_records        : {recs}")

    keys = sorted({k for p in orphans for k in (
        p.get("page_image_r2_key"), p.get("page_base_r2_key"),
        p.get("page_thumb_r2_key")) if k})
    print(f"\n  R2 objects these rows name: {len(keys)} — NOT deleted here. "
          f"Page images are derived data, but removing them is the scrub's "
          f"job, with its own confirmation.")
    for k in keys[:5]:
        print(f"     {k}")
    if len(keys) > 5:
        print(f"     ... and {len(keys) - 5} more")

    if not check_guard(args):
        report_dry_run(f"delete {len(orphans)} orphaned pages, {chunks} chunks "
                       f"and {recs} plan_records on project {pid}")
        return 0

    d1 = db.document_page_chunks.delete_many({"page_id": {"$in": page_ids}})
    d2 = db.plan_records.delete_many({"page_id": {"$in": page_ids}})
    d3 = db.document_page_index.delete_many(
        {"_id": {"$in": [p["_id"] for p in orphans]}})
    print(f"\nDELETED  chunks={d1.deleted_count}  records={d2.deleted_count}  "
          f"pages={d3.deleted_count}")
    left = db.document_page_index.count_documents({"project_id": pid})
    print(f"pages remaining on the project: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
