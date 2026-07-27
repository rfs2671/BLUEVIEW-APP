#!/usr/bin/env python3
"""READ-ONLY audit of the real account population, BEFORE any auth change.

Run this against production and read the output before the Finding 0 fix is
committed. The fix changes what role/status a new account may hold and adds
account_status enforcement to privileged routes; this script establishes who
exists today so we can prove nobody legitimate gets locked out or demoted.

  python backend/scripts/audit_account_roles.py

Requires MONGO_URL + DB_NAME, same contract as the other scripts here.

WRITES NOTHING. Reads db.users, db.companies, db.site_devices only. Safe
against production.

Prints no passwords or tokens. Emails are shown because you need to recognise
your own operator account; pass --mask to redact them for sharing.
"""

import argparse
import asyncio
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# Routes that the Finding 0 fix will put behind require_approved. An account
# that is `pending` today can reach these and will NOT be able to afterwards —
# that is the whole point, but we must know who that affects before shipping.
NEWLY_GATED = [
    "DELETE /projects/{id}/hard-delete",
    "DELETE /owner/companies/{id}",
    "PUT /projects/{id}",
]


def _mask(email, on):
    if not on or not email or "@" not in email:
        return email or "(none)"
    name, _, dom = email.partition("@")
    keep = name[:2] if len(name) > 2 else name[:1]
    return f"{keep}***@{dom}"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mask", action="store_true", help="redact emails")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    db = AsyncIOMotorClient(mongo_url)[db_name]

    users = await db.users.find(
        {"is_deleted": {"$ne": True}},
        {"email": 1, "name": 1, "role": 1, "account_status": 1,
         "company_id": 1, "company_name": 1, "created_at": 1,
         "assigned_projects": 1},
    ).to_list(length=None)

    if not users:
        print("No users found.")
        return 0

    companies = await db.companies.find({}, {"name": 1}).to_list(length=None)
    cnames = {str(c["_id"]): c.get("name") for c in companies}

    print("=" * 78)
    print("ACCOUNT POPULATION  (total non-deleted users: %d)" % len(users))
    print("=" * 78)

    by_role = Counter((u.get("role") or "(none)") for u in users)
    by_status = Counter((u.get("account_status") or "(MISSING)") for u in users)
    print("\nBy role:")
    for r, n in by_role.most_common():
        print("  %-14s %d" % (r, n))
    print("\nBy account_status:")
    for s, n in by_status.most_common():
        print("  %-14s %d" % (s, n))

    # ── The accounts the fix could affect ────────────────────────────────
    owners = [u for u in users if u.get("role") == "owner"]
    print("\n" + "-" * 78)
    print("ROLE=OWNER ACCOUNTS  (%d) — these can reach hard-delete /" % len(owners))
    print("  DELETE /owner/companies/{id} TODAY, on role alone.")
    print("-" * 78)
    for u in sorted(owners, key=lambda d: str(d.get("created_at") or "")):
        cid = str(u.get("company_id") or "")
        print("  %-32s status=%-10s company=%s" % (
            _mask(u.get("email"), args.mask),
            u.get("account_status") or "(MISSING)",
            u.get("company_name") or cnames.get(cid) or cid or "(none)",
        ))

    pending = [u for u in users if u.get("account_status") == "pending"]
    print("\n" + "-" * 78)
    print("PENDING ACCOUNTS (%d) — WOULD LOSE ACCESS to:" % len(pending))
    for r in NEWLY_GATED:
        print("    %s" % r)
    print("  If any of these is a real operator, the migration must approve")
    print("  them explicitly BEFORE the fix ships.")
    print("-" * 78)
    for u in pending:
        cid = str(u.get("company_id") or "")
        # Show the raw id when it resolves to no company — printing "(none)"
        # for a user who DOES carry a company_id would hide exactly the
        # arbitrary-company_id case this audit exists to surface.
        company = (u.get("company_name") or cnames.get(cid)
                   or (f"{cid} (UNKNOWN COMPANY)" if cid else "(none)"))
        print("  %-32s role=%-10s company=%s" % (
            _mask(u.get("email"), args.mask),
            u.get("role") or "(none)",
            company,
        ))
    if not pending:
        print("  (none — no account loses access)")

    missing = [u for u in users if not u.get("account_status")]
    print("\n" + "-" * 78)
    print("MISSING account_status (%d) — grandfathered." % len(missing))
    print("  require_approved blocks only an EXPLICIT 'pending', and the")
    print("  startup backfill sets these to 'approved'. Not locked out.")
    print("-" * 78)
    for u in missing:
        print("  %-32s role=%s" % (_mask(u.get("email"), args.mask), u.get("role")))
    if not missing:
        print("  (none — backfill already ran)")

    # ── Cross-tenant sanity: users pointing at a company that isn't there ──
    dangling = [u for u in users
                if u.get("company_id") and str(u["company_id"]) not in cnames]
    print("\n" + "-" * 78)
    print("USERS WITH A DANGLING company_id (%d)" % len(dangling))
    print("  A self-registrant CAN currently supply an arbitrary company_id;")
    print("  a value matching no company is a signal that happened.")
    print("-" * 78)
    for u in dangling:
        print("  %-32s role=%-10s company_id=%s" % (
            _mask(u.get("email"), args.mask), u.get("role"), u.get("company_id")))
    if not dangling:
        print("  (none)")

    # ── Multi-tenant shape: >1 owner in one company is normal; an owner with
    #    no company is the self-signup-before-onboarding state.
    per_company = defaultdict(list)
    for u in owners:
        per_company[str(u.get("company_id") or "(no company)")].append(u)
    orphan_owners = per_company.get("(no company)", [])
    print("\n" + "-" * 78)
    print("OWNERS WITH NO COMPANY (%d) — mid-onboarding, expected." % len(orphan_owners))
    print("-" * 78)
    for u in orphan_owners:
        print("  %-32s status=%s" % (
            _mask(u.get("email"), args.mask), u.get("account_status")))
    if not orphan_owners:
        print("  (none)")

    devices = await db.site_devices.count_documents({})
    print("\n" + "=" * 78)
    print("SITE DEVICES: %d — unaffected (require_approved bypasses site_mode;" % devices)
    print("  check-in is not touched by this fix).")
    print("=" * 78)

    print("\nREAD-ONLY: nothing was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
