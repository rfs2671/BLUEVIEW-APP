"""ROLL BACK THE 2026-09-21 DISCIPLINE MIGRATION, PAGE BY PAGE, FROM THE
SNAPSHOT.

For every page in plan.json that is in its MIGRATED state, the page row is
replaced with its snapshot document and the page's plan_records are replaced
with the snapshot rows — the raw BSON as read on 2026-09-21, so _id,
created_at, field order and types come back byte for byte.

A page still in its snapshot state is skipped. A page in ANY other state
(changed since the migration) makes it refuse and write nothing: restoring
over a newer re-index would destroy it.

Same gate as every production writer: --i-know --reason --session; without it
this is a dry run. Every write leaves an audit_logs row.

USAGE (from backend/)
=====================

    railway run python -m scripts.rollback_plan_discipline_20260921 --snapshot-dir <dir>
    railway run python -m scripts.rollback_plan_discipline_20260921 --snapshot-dir <dir> --i-know --reason "<why>" --session <id>
"""
from __future__ import annotations

import argparse
import os
import sys

from bson.raw_bson import RawBSONDocument
from pymongo import MongoClient

from scripts import plan_discipline_20260921 as P
from scripts.prod_guard import (
    add_guard_args, audited, check_guard, refuse_legacy_flag, report_dry_run,
)

NAME = "rollback_plan_discipline_20260921"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot-dir", required=True)
    ap.add_argument("--plan", default="")
    add_guard_args(ap)
    return ap


def raw_equal(db, row) -> bool:
    """Byte-for-byte: the stored page row and records are the snapshot's."""
    e = row.entry
    page = db[P.PAGES].find_one({"_id": e["page_id"]})
    recs = sorted(db[P.RECORDS].find(P.record_selector(e)), key=lambda d: d["_id"])
    snap = sorted(row.snap_recs, key=lambda d: d["_id"])
    return (page is not None and page.raw == row.snap_page.raw
            and [d.raw for d in recs] == [d.raw for d in snap])


def main(argv=None, client=None) -> int:
    refuse_legacy_flag(argv)
    args = build_parser().parse_args(argv)
    plan, pages, recs = P.load(args.snapshot_dir, args.plan)
    P.with_project(plan)
    if client is None:
        url = os.environ.get("MONGO_URL")
        if not url:
            print("MONGO_URL is not set. Run this under `railway run`.")
            return 2
        client = MongoClient(url, document_class=RawBSONDocument)
    # Named, not read off sys.argv: the audit row must say which script wrote
    # it however it was launched.
    db = audited(client[os.environ.get("DB_NAME", "test_database")], args, NAME)

    rows = P.survey(db, plan, pages, recs)
    P.print_table(rows, f"BEFORE ROLLBACK — {len(rows)} plan pages")
    print(f"\n  states: {P.summary(rows)}")
    print("  counts: " + ", ".join(f"{k}={v}" for k, v in
                                   P.collection_counts(db, plan).items()))

    others = [r for r in rows if r.state == P.OTHER]
    if others:
        print(f"\nREFUSED: {len(others)} page(s) are neither migrated nor in "
              "their snapshot state. Restoring would overwrite newer data. "
              "Nothing was written.")
        for r in others:
            e = r.entry
            print(f"  {e['sheet_number']}  {e['file_name']} p{e['page_number']}")
        return 2

    todo = [r for r in rows if r.state in (P.TARGET, P.PARTIAL)]
    if not todo:
        print("\nNothing to roll back: every plan page is in its snapshot state.")
        return 0
    if not check_guard(args):
        report_dry_run(f"restore {len(todo)} pages and their "
                       f"{sum(len(r.snap_recs) for r in todo)} snapshot "
                       f"records from the snapshot")
        return 0

    for r in todo:
        e = r.entry
        # Records first, the page row last: a page whose row is restored
        # always has restored records, so a cut-off run leaves `partial`.
        db[P.RECORDS].delete_many(P.record_selector(e))
        if r.snap_recs:
            db[P.RECORDS].insert_many(list(r.snap_recs))
        db[P.PAGES].replace_one({"_id": e["page_id"]}, r.snap_page)
        if not raw_equal(db, r):
            print(f"\nSTOPPED: {e['sheet_number']} is not byte-identical to "
                  "the snapshot after restoring. Re-running resumes.")
            return 3

    after = P.survey(db, plan, pages, recs)
    P.print_table(after, f"AFTER ROLLBACK — {len(after)} plan pages")
    print(f"\n  states: {P.summary(after)}")
    print("  counts: " + ", ".join(f"{k}={v}" for k, v in
                                   P.collection_counts(db, plan).items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
