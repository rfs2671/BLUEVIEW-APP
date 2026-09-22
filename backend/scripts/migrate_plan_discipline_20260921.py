"""APPLY THE 2026-09-21 DISCIPLINE MIGRATION ON 588 BOYLAND.

WHAT IT CHANGES, AND NOTHING ELSE
=================================

Ninety-six pages of project 6a5f63bc147407d3261df2c7, each listed in plan.json:

  * 94 pages: `discipline` on every plan_records row of the page (11,464 rows)
    and on its document_page_index row, set to what #648's rule gives. Rows
    are UPDATED IN PLACE: _id, created_at and every other field are kept.
  * FA-001, SP-003.00, SP-004.00: the page's plan_records are REPLACED with
    the rows #647's restructuring gives (145 -> 147), exactly as
    _write_page_records replaces a page, and the page row's
    extraction.schedules / extraction.elements (and FA-001's discipline) are
    set to match.

document_page_chunks, R2, and every other page are not touched. Chunk
`discipline` has no reader; see #648.

REFUSES, AND WRITES NOTHING, WHEN
=================================

  * a snapshot file's SHA-256 is not the one plan.json was built from
  * ANY plan page is in neither its snapshot state nor its migrated state —
    someone re-indexed or changed it since 2026-09-21 19:46Z. The plan is
    only valid against the snapshot it was computed from.

IDEMPOTENT: a page already in its migrated state is skipped, so a re-run after
an interruption finishes the rest and a re-run after success writes nothing.
Each page is re-read after its write and the run stops if it is not exactly
the target.

THE GATE IS --i-know, NOT --apply
=================================

scripts/prod_guard.py is the operator's standing rule for production writers:
`--i-know --reason --session`, and every write leaves an audit_logs row through
`audited()`. `--apply` is on its list of retired write flags and is refused
loudly. Without --i-know this is a dry run.

USAGE (from backend/)
=====================

    railway run python -m scripts.migrate_plan_discipline_20260921 --snapshot-dir <dir>
    railway run python -m scripts.migrate_plan_discipline_20260921 --snapshot-dir <dir> --i-know --reason "<why>" --session <id>
    railway run python -m scripts.migrate_plan_discipline_20260921 --snapshot-dir <dir> --verify
"""
from __future__ import annotations

import argparse
import os
import sys

from bson.raw_bson import RawBSONDocument
from pymongo import MongoClient

from scripts import plan_discipline_20260921 as P
from scripts.probe_helpers import require_fields
from scripts.prod_guard import (
    add_guard_args, audited, check_guard, refuse_legacy_flag, report_dry_run,
)

NAME = "migrate_plan_discipline_20260921"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot-dir", required=True,
                    help="folder holding snapshot/records.bson, "
                         "snapshot/pages.bson and plan.json")
    ap.add_argument("--plan", default="", help="default: <snapshot-dir>/plan.json")
    ap.add_argument("--verify", action="store_true",
                    help="read-only: exit 0 only if every plan page is migrated")
    add_guard_args(ap)
    return ap


def _client():
    url = os.environ.get("MONGO_URL")
    if not url:
        print("MONGO_URL is not set. Run this under `railway run`.")
        raise SystemExit(2)
    return MongoClient(url, document_class=RawBSONDocument)


def _write_page(db, row) -> None:
    """Bring one page to its target. Records first, the page row last, so a
    page whose row is migrated always has migrated records."""
    e = row.entry
    sel = P.record_selector(e)
    t_page, t_recs = row.target
    if e["kind"] == "discipline" and row.state == P.SNAPSHOT:
        # The ruled path: in place, so _id, created_at and every other field
        # of the 11,464 rows are untouched.
        res = db[P.RECORDS].update_many(sel, {"$set": {"discipline": e["discipline_to"]}})
        if res.matched_count != len(row.snap_recs):
            raise SystemExit(f"{e['sheet_number']}: matched {res.matched_count} "
                             f"records, expected {len(row.snap_recs)}. Stopped.")
    else:
        # A replace page, or any page a cut-off run left part-way. Every row
        # on it was checked to be a version this plan knows, so the whole set
        # is swapped for the target. A discipline page's target rows keep
        # their snapshot _id and created_at.
        now = db[P.RECORDS].count_documents(sel)
        res = db[P.RECORDS].delete_many(sel)
        if res.deleted_count != now:
            raise SystemExit(f"{e['sheet_number']}: deleted {res.deleted_count} "
                             f"records, expected {now}. Stopped.")
        db[P.RECORDS].insert_many(t_recs)
    if e["kind"] == "discipline":
        db[P.PAGES].update_one({"_id": e["page_id"]},
                               {"$set": {"discipline": e["discipline_to"]}})
    else:
        db[P.PAGES].update_one({"_id": e["page_id"]}, {"$set": e["page_set"]})


def main(argv=None, client=None) -> int:
    refuse_legacy_flag(argv)
    args = build_parser().parse_args(argv)
    plan, pages, recs = P.load(args.snapshot_dir, args.plan)
    P.with_project(plan)
    # Declared here as well as in P.load: this file counts on them below.
    require_fields(plan["pages"], "kind", "page_id")
    replaces = [e for e in plan["pages"] if e["kind"] == "replace"]
    if replaces:
        require_fields(replaces, "records")
    client = client or _client()
    # Named, not read off sys.argv: the audit row must say which script wrote
    # it however it was launched.
    db = audited(client[os.environ.get("DB_NAME", "test_database")], args, NAME)

    rows = P.survey(db, plan, pages, recs)
    before = P.collection_counts(db, plan)
    P.print_table(rows, f"BEFORE — {len(rows)} plan pages")
    states = P.summary(rows)
    print(f"\n  states: {states}")
    print("  counts: " + ", ".join(f"{k}={v}" for k, v in before.items()))

    if args.verify:
        ok = states[P.TARGET] == len(rows)
        print(f"\nVERIFY: {'every plan page is migrated' if ok else 'NOT migrated'}"
              f" ({states[P.TARGET]} of {len(rows)} in target state)")
        return 0 if ok else 1

    others = [r for r in rows if r.state == P.OTHER]
    if others:
        print(f"\nREFUSED: {len(others)} page(s) changed since the snapshot. "
              "Nothing was written.")
        for r in others:
            e = r.entry
            print(f"  {e['sheet_number']}  {e['file_name']} p{e['page_number']}")
        return 2

    todo = [r for r in rows if r.state in (P.SNAPSHOT, P.PARTIAL)]
    if not todo:
        print("\nNothing to do: every plan page is already migrated.")
        return 0
    n_disc = sum(len(r.snap_recs) for r in todo if r.entry["kind"] == "discipline")
    n_rep = [r for r in todo if r.entry["kind"] == "replace"]
    if not check_guard(args):
        report_dry_run(
            f"migrate {len(todo)} pages: set discipline on {n_disc} plan_records "
            f"in place and on their page rows; replace records on "
            f"{len(n_rep)} page(s) "
            f"({sum(len(r.snap_recs) for r in n_rep)} -> "
            f"{sum(len(r.entry['records']) for r in n_rep)})")
        return 0

    for r in todo:
        _write_page(db, r)
        cur_p, cur_r = P.read_page(db, r.entry)
        if P.state_of(cur_p, cur_r, r.snap_page, r.snap_recs,
                      r.target) != P.TARGET:
            print(f"\nSTOPPED: {r.entry['sheet_number']} is not in its target "
                  "state after its write. Pages before it are migrated; "
                  "re-running resumes from here.")
            return 3

    after_rows = P.survey(db, plan, pages, recs)
    after = P.collection_counts(db, plan)
    P.print_table(after_rows, f"AFTER — {len(after_rows)} plan pages")
    print(f"\n  states: {P.summary(after_rows)}")
    print("  counts: " + ", ".join(f"{k}={v}" for k, v in after.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
