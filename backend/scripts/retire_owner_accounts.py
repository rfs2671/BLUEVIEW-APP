"""RETIRE THE SELF-SERVE OWNER ACCOUNTS. Audited, guarded, dry-run by default.

── THE RULING ──────────────────────────────────────────────────────────────

"Owner" is no longer a role anyone holds; self-serve sign-up is demo-only. The
operator ruled what happens to each account the old sign-up created:

    test@ios.com                    -> demo, KEEP   (the App Store reviewer)
    yero151218vi@gmail.com          -> lead         (a demo record: name, email,
                                                     typed company, created_at)
    triage.1789494908@example.com   -> delete
    company "Blueview llc"          -> delete       (yero's, and empty)

plus a check the ruling asked for:

    Michael Cespedes                -> backfill DOB licence 32299 onto his user
                                       field IF STILL EMPTY

rfs2671@gmail.com is NOT touched. It keeps `is_platform_operator`, and its
`role` still reads "owner"; moving that to "admin" was ruled "report before
writing" and is not in this run. Every swept gate admits the operator on the
flag, so the stale string locks nothing.

── WHAT "DELETE" MEANS HERE ────────────────────────────────────────────────

A USER IS SOFT-DELETED, the way DELETE /admin/users/{id} does it: the handler
says "SOFT delete, and never anything harder", because a hard delete severs
`signature_events.signer.user_id` from the account that signed. The triage
account has signed nothing, but a one-off script is not the place to invent a
second meaning of delete.

THE COMPANY IS REMOVED, the way DELETE /owner/companies/{id} removes one -- and
only after the same refusal that route applies: nothing may still point at it.
Users, projects, workers and filed logbooks are counted, and any non-zero count
refuses the whole company step. yero is unlinked FIRST in this run, so on an
execute the count is taken after that write, never before it.

── "LEAD" IS DATA ONLY, TODAY ──────────────────────────────────────────────

The owner-panel Leads section is step 4 of the demo ruling and is not built. So
this converts yero to the record the ruling defines -- role demo, no company
link, name / email / typed company / created_at kept -- and nothing more. Until
the section exists the lead is in the database and on no screen.

    python backend/scripts/retire_owner_accounts.py                 # dry run
    python backend/scripts/retire_owner_accounts.py --i-know \\
        --reason '<why>' --session <id>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag, report_dry_run,
)

NAME = "retire_owner_accounts"

REVIEWER = "test@ios.com"
LEAD = "yero151218vi@gmail.com"
DELETE_USER = "triage.1789494908@example.com"
DELETE_COMPANY_NAME = "Blueview llc"
MICHAEL = "michaelcespedes99@gmail.com"
MICHAEL_LICENCE = "32299"
OPERATOR = "rfs2671@gmail.com"


def _line(msg: str) -> None:
    print(msg, flush=True)


async def _user(db, email):
    return await db.users.find_one({"email": email})


async def _company_references(db, company_id: str, *, excluding_user=None) -> dict:
    """Everything that would be left pointing at the company.

    `excluding_user` is the account this same run unlinks before the company
    step; on a DRY run nothing has been written yet, so the count is taken as
    it WILL be, and says so.
    """
    user_q = {"company_id": company_id, "is_deleted": {"$ne": True}}
    if excluding_user is not None:
        user_q["_id"] = {"$ne": excluding_user}
    return {
        "users": await db.users.count_documents(user_q),
        "projects": await db.projects.count_documents(
            {"company_id": company_id}),
        "workers": await db.workers.count_documents(
            {"company_id": company_id}),
        "filed_logbooks": await db.logbooks.count_documents(
            {"company_id": company_id,
             "$or": [{"status": "submitted"}, {"is_locked": True}]}),
    }


async def main() -> int:
    refuse_legacy_flag()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_guard_args(ap)
    args = ap.parse_args()
    check_guard(args)

    import server  # noqa: E402 -- the SAME role vocabulary the app uses

    execute = check_guard(args)
    db = audited(server.db, args, NAME)
    now = datetime.now(timezone.utc)
    planned: list[str] = []

    _line(f"=== {NAME} -- {'EXECUTE' if execute else 'DRY RUN'} ===\n")

    # ── the operator: read, never written ────────────────────────────────────
    op = await _user(db, OPERATOR)
    _line(f"[operator] {OPERATOR}: role={op.get('role')!r} "
          f"is_platform_operator={op.get('is_platform_operator')!r} "
          f"-- NOT touched in this run" if op else
          f"[operator] {OPERATOR}: NOT FOUND -- stopping")
    if not op:
        return 3

    # ── 1. Michael: backfill only if empty ──────────────────────────────────
    m = await _user(db, MICHAEL)
    have = str((m or {}).get("dob_superintendent_number") or "").strip()
    if not m:
        _line(f"[michael] {MICHAEL}: NOT FOUND -- skipped")
    elif have:
        _line(f"[michael] dob_superintendent_number already {have!r} -- "
              f"nothing to backfill")
    else:
        _line(f"[michael] dob_superintendent_number is empty -> "
              f"{MICHAEL_LICENCE!r}")
        planned.append("michael backfill")
        if execute:
            await db.users.update_one(
                {"_id": m["_id"], "dob_superintendent_number": {"$in": [None, ""]}},
                {"$set": {"dob_superintendent_number": MICHAEL_LICENCE,
                          "updated_at": now}})

    # ── 2. the App Store reviewer -> demo, kept ─────────────────────────────
    r = await _user(db, REVIEWER)
    if not r:
        _line(f"[reviewer] {REVIEWER}: NOT FOUND -- skipped")
    elif r.get("role") == server.ROLE_DEMO:
        _line(f"[reviewer] already demo -- nothing to do")
    else:
        _line(f"[reviewer] {REVIEWER}: role {r.get('role')!r} -> "
              f"{server.ROLE_DEMO!r}; account KEPT; company_id "
              f"{r.get('company_id')!r} left as is")
        planned.append("reviewer -> demo")
        if execute:
            await db.users.update_one(
                {"_id": r["_id"], "role": r.get("role")},
                {"$set": {"role": server.ROLE_DEMO, "updated_at": now}})

    # ── 3. yero -> lead (demo, unlinked, contact kept) ──────────────────────
    y = await _user(db, LEAD)
    yero_id = None
    blueview_id = None
    if not y:
        _line(f"[lead] {LEAD}: NOT FOUND -- skipped")
    else:
        yero_id = y["_id"]
        blueview_id = y.get("company_id")
        _line(f"[lead] {LEAD}: role {y.get('role')!r} -> "
              f"{server.ROLE_DEMO!r}; company_id {blueview_id!r} -> None")
        _line(f"       kept: name={y.get('name')!r} "
              f"company_name={y.get('company_name')!r} "
              f"created_at={str(y.get('created_at'))[:19]} "
              f"phone={'set' if y.get('phone') else 'none'}")
        if y.get("role") != server.ROLE_DEMO or blueview_id:
            planned.append("yero -> lead")
            if execute:
                await db.users.update_one(
                    {"_id": yero_id},
                    {"$set": {"role": server.ROLE_DEMO, "company_id": None,
                              "updated_at": now}})

    # ── 4. triage -> soft-deleted ────────────────────────────────────────────
    t = await _user(db, DELETE_USER)
    if not t:
        _line(f"[delete] {DELETE_USER}: NOT FOUND -- skipped")
    elif t.get("is_deleted") is True:
        _line(f"[delete] already soft-deleted -- nothing to do")
    else:
        tid = t["_id"]
        owned = {
            "projects_created": await db.projects.count_documents(
                {"created_by": str(tid)}),
            "logbooks_created": await db.logbooks.count_documents(
                {"created_by": str(tid)}),
            "signatures": await db.signature_events.count_documents(
                {"signer.user_id": str(tid)}),
        }
        _line(f"[delete] {DELETE_USER}: soft-delete (is_deleted=True). "
              f"owned: {owned}")
        if any(owned.values()):
            _line("         REFUSED: the account owns records. Not deleting.")
            return 4
        planned.append("triage soft-delete")
        if execute:
            await db.users.update_one(
                {"_id": tid, "is_deleted": {"$ne": True}},
                {"$set": {"is_deleted": True, "deleted_at": now,
                          "updated_at": now}})

    # ── 5. Blueview llc -> removed, only if nothing points at it ────────────
    comp = await db.companies.find_one({"name": DELETE_COMPANY_NAME})
    if not comp:
        _line(f"[company] {DELETE_COMPANY_NAME!r}: NOT FOUND -- skipped")
    else:
        cid = str(comp["_id"])
        if blueview_id and str(blueview_id) != cid:
            _line(f"[company] REFUSED: {LEAD} belongs to {blueview_id}, not "
                  f"{cid} -- the name matched a different company. Stopping.")
            return 5
        # On a dry run yero is not yet unlinked, so exclude him from the count;
        # on an execute he was unlinked above and is simply not counted.
        refs = await _company_references(
            db, cid, excluding_user=None if execute else yero_id)
        _line(f"[company] {DELETE_COMPANY_NAME!r} ({cid}): references "
              f"{'now' if execute else 'after the lead step'}: {refs}")
        if any(refs.values()):
            _line("          REFUSED: something still points at this company.")
            return 6
        planned.append("Blueview llc removed")
        if execute:
            await db.companies.delete_one({"_id": comp["_id"]})

    _line("")
    if not execute:
        report_dry_run("; ".join(planned) or "nothing")
        return 0

    _line(f"applied: {'; '.join(planned) or 'nothing'}")
    _line(f"audit rows written by the audited handle, actor script:{NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
