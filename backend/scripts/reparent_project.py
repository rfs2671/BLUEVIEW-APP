"""MOVE A PROJECT TO ANOTHER COMPANY. Audited, guarded, one document.

── THE CASE IT WAS WRITTEN FOR ─────────────────────────────────────────────

852 East 176th Street (`69e6e6c30b6e05f281e5bb66`) is a FIXTURE that lives
under a company that no longer exists.

Only two projects in the entire database carry an indexed plan set:

    588 Thomas S Boyland Street   16 files   155 indexed pages   Blueview, LIVE
    852 East 176th Street          6 files    86 indexed pages   orphaned

So when the plan-index work needed a second plan set to test AR sheet
duplication against, there were exactly two candidates and one of them was a
customer's live job. It un-deleted 852. The `test` company has no project with
a single plan file, which is why a test-company fixture was not an option.

Its company, `69e6a477aaade43f835aeeaa`, was hard-deleted on 2026-06-17
13:28:26 — by an actor the audit row could not name, because
`hard_delete_company` read `current_user["_id"]`, a key `serialize_id` deletes.
So the project sits under a company id with no document, gets no `is_test`
coverage, and appears on the operator's project list under no card.

OPERATOR RULING: reparent it under the `test` company. No delete.

── WHY REPARENTING AND NOT A FLAG ON THE PROJECT ───────────────────────────

`is_test` lives on the COMPANY, deliberately: one row covers its projects, its
accounts, its workers and every log filed under them, and a fixture project
inherits it instead of being one more thing to remember to flag. A project-level
override would be a second place to look.

── WHAT IT DOES NOT DO ─────────────────────────────────────────────────────

It moves the PROJECT document and nothing else. Logbooks, workers, check-ins
and files are keyed by `project_id`, which does not change, so nothing is
orphaned by the move. It does not touch `company_name` on child documents,
because nothing reads one.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prod_guard import (  # noqa: E402
    add_guard_args, check_guard, report_dry_run, script_audit, script_name,
)

NAME = "reparent_project"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True, help="project _id")
    ap.add_argument("--to-company", required=True, dest="to_company",
                    help="destination company _id")
    add_guard_args(ap)
    args = ap.parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"],
                                serverSelectionTimeoutMS=30000)
    db = client[os.environ.get("DB_NAME") or "test_database"]

    from bson import ObjectId

    def oid(v):
        try:
            return ObjectId(v)
        except Exception:
            return v

    project = await db.projects.find_one({"_id": oid(args.project)})
    if not project:
        print(f"project {args.project} not found")
        return 1
    dest = await db.companies.find_one({"_id": oid(args.to_company)})
    if not dest:
        print(f"destination company {args.to_company} not found")
        return 1

    old_company = project.get("company_id")
    print(f"project : {project.get('name')!r}  [{args.project}]")
    print(f"          address={project.get('address')!r}")
    print(f"          is_deleted={project.get('is_deleted')!r} "
          f"marked_for_deletion={project.get('marked_for_deletion')!r}")
    print(f"from    : {old_company}"
          f"{'  (NO COMPANY DOCUMENT — orphan)' if not await db.companies.find_one({'_id': oid(str(old_company))}) else ''}")
    print(f"to      : {args.to_company}  {dest.get('name')!r} "
          f"is_test={dest.get('is_test')!r}")

    # WHAT MOVES WITH IT, COUNTED AND SHOWN. The move does not touch these --
    # they key on project_id -- but an operator confirming a reparent should
    # see the size of what he is moving between tenants.
    for coll in ("logbooks", "project_files", "document_page_index",
                 "checkins", "workers", "worker_project_trades"):
        try:
            n = await db[coll].count_documents({"project_id": str(args.project)})
            if n:
                print(f"          carries {n} {coll} rows (keyed on project_id, "
                      f"unchanged)")
        except Exception:
            pass

    if str(old_company) == str(args.to_company):
        print("\nalready under that company; nothing to do")
        return 0

    if not check_guard(args):
        report_dry_run(
            f"set company_id {old_company!r} -> {args.to_company!r} on "
            f"project {args.project}")
        return 0

    res = await db.projects.update_one(
        {"_id": oid(args.project)},
        {"$set": {"company_id": str(args.to_company),
                  "company_name": dest.get("name")}},
    )
    print(f"\nmatched={res.matched_count} modified={res.modified_count}")

    await script_audit(
        db, "project_reparent", "project", args.project,
        {
            "name": project.get("name"),
            "old": {"company_id": old_company,
                    "company_name": project.get("company_name")},
            "new": {"company_id": str(args.to_company),
                    "company_name": dest.get("name")},
            "old_company_document_existed": bool(
                await db.companies.find_one({"_id": oid(str(old_company))})),
        },
        args, name=NAME,
    )
    print(f"audit row written, actor script:{NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
