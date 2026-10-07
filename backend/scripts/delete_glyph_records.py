"""Remove a project's glyph rows - the rows the equipment-placement pass wrote.

    railway run python -m scripts.delete_glyph_records \\
        --project <id> --expect <n>                                  (dry run)
    railway run python -m scripts.delete_glyph_records \\
        --project <id> --expect <n> --i-know --reason '<why>' --session <id>

WHY THIS EXISTS (2026-10-06). The pass (#660) wrote 84 `record_type: "glyph"`
rows for 588 Boyland, read back identical to the reviewed local run. Then a
read-only probe found the count gate binding a PARTIAL count as a total:
search_plans returns 8 records, glyph rows rank below printed ones, and
glyph_tallies counted the 2 of 16 EF-1 rows that came back - so "There are 2
EF-1." was allowed. The rows are correct; the reader is not yet safe with
them. Operator ruling: remove them until the reader is fixed. They are
rebuilt by re-running the pass.

WHAT IT CAN TOUCH, AND NOTHING ELSE:
  - one collection, plan_records;
  - one filter, every clause required: the project, record_type "glyph",
    tier "registered_glyph", source "plan_takeoff" - the rows plan_emit
    writes and no other writer produces;
  - --expect is required, and a count that is not EXACTLY that refuses
    before anything is deleted: a surprise count is a question, not a delete;
  - ONE delete_many;
  - the project's other records are counted before and after, and a move is
    a failure, reported loudly.

Dry run by default. --i-know needs --reason and --session (scripts.prod_guard),
and the handle is wrapped by audited(), so the delete leaves an audit row.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from scripts.probe_helpers import require_fields
from scripts.prod_guard import (
    add_guard_args, audited, check_guard, refuse_legacy_flag, report_dry_run,
    script_name,
)

#: exit codes, so a runbook can tell a refusal from a broken delete
OK, REFUSED, FAILED = 0, 3, 4


def glyph_filter(project_id: str) -> dict:
    """The rows the placement pass writes - and only those."""
    return {"project_id": str(project_id), "record_type": "glyph",
            "tier": "registered_glyph", "source": "plan_takeoff"}


def other_filter(project_id: str) -> dict:
    """Every other record on the project: what must not move."""
    return {"project_id": str(project_id), "record_type": {"$ne": "glyph"}}


def run(db, project_id: str, expect: int, write: bool) -> int:
    pid = str(project_id)
    f = glyph_filter(pid)
    n = db.plan_records.count_documents(f)
    other_before = db.plan_records.count_documents(other_filter(pid))
    rows = list(db.plan_records.find(f, {"sheet_number": 1}))
    if rows:
        # PROVE THE FIELD BEFORE COUNTING ON IT (probe_helpers): a renamed or
        # unprojected field would read as None on every row, silently.
        require_fields(rows, "sheet_number")
    by_sheet = Counter(r.get("sheet_number") or "?" for r in rows)
    print(f"project {pid}")
    print(f"  glyph rows matching the filter: {n}   (expected {expect})")
    print(f"  other records on the project:   {other_before}")
    print(f"  glyph rows by sheet: {dict(sorted(by_sheet.items()))}")
    if n != expect:
        print(f"\nREFUSED: {n} glyph rows match, --expect says {expect}. "
              f"Nothing was deleted.")
        return REFUSED
    if not write:
        report_dry_run(f"delete {n} glyph rows on project {pid} "
                       f"(plan_records, {f})")
        return OK
    res = db.plan_records.delete_many(f)
    left = db.plan_records.count_documents(f)
    other_after = db.plan_records.count_documents(other_filter(pid))
    print(f"\nDELETED {res.deleted_count}")
    print(f"  glyph rows left:              {left}")
    print(f"  other records before / after: {other_before} / {other_after}")
    if res.deleted_count != expect or left != 0 or other_after != other_before:
        print("\nFAILED: the delete did not do exactly what was checked - "
              "STOP and read the numbers above.")
        return FAILED
    return OK


def main() -> int:
    refuse_legacy_flag()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, help="the project id")
    ap.add_argument("--expect", type=int, required=True,
                    help="the exact number of glyph rows expected; any other "
                         "count refuses before deleting")
    add_guard_args(ap)
    args = ap.parse_args()
    write = check_guard(args)
    url = os.environ.get("MONGO_URL")
    if not url:
        print("MONGO_URL is not set. Run this under `railway run`.")
        return 2
    from pymongo import MongoClient
    client = MongoClient(url)
    db = audited(client[os.environ.get("DB_NAME", "test_database")], args,
                 script_name())
    return run(db, args.project, args.expect, write)


if __name__ == "__main__":
    sys.exit(main())
