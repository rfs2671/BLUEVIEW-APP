"""Turn the DM brain (flag dm_brain_v2) on or off for one company.

    railway run python scripts/dm_brain_flag.py --show
    railway run python scripts/dm_brain_flag.py --email you@company.com --on          # dry run
    railway run python scripts/dm_brain_flag.py --email you@company.com --on \
        --i-know --reason "DM brain for our company" --session <id>

Writes the feature_flags row (enabled_for_companies) and a
feature_flag_audit_log row, as the admin endpoint does; every write is also
recorded in audit_logs with actor "script:dm_brain_flag" (prod_guard).
Nothing else changes: companies not on the list keep the old DM pipeline.
The brain also needs ANTHROPIC_API_KEY on the service; without it everyone
gets the old one.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# ── PRODUCTION WRITE GUARD ──────────────────────────────────────────────────
# Every write below goes through `audited(...)`, which records it in audit_logs
# with actor "script:dm_brain_flag", the session and the reason. Without
# --i-know the handle is unwrapped and nothing is written. See prod_guard.
import os as _g_os                                              # noqa: E402
import sys as _g_sys                                            # noqa: E402
_g_sys.path.insert(0, _g_os.path.dirname(_g_os.path.abspath(__file__)))
from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag, report_dry_run,
)

NAME = "dm_brain_flag"
FLAG = "dm_brain_v2"


async def run(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    apply = check_guard(a)
    db = audited(AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]], a, NAME)
    row = await db.feature_flags.find_one({"flag": FLAG})
    if a.show:
        print(row or f"{FLAG}: not created (off for everyone)")
        return 0
    company = a.company
    if a.email:
        user = await db.users.find_one({"email": a.email.strip().lower(), "is_deleted": {"$ne": True}})
        if not user:
            sys.exit("No user with that email.")
        company = str(user.get("company_id") or "")
    if not company:
        sys.exit("Give --email or --company.")
    companies = [str(c) for c in (row or {}).get("enabled_for_companies") or []]
    if a.on and company not in companies:
        companies.append(company)
    if a.off:
        companies = [c for c in companies if c != company]
    if not apply:
        report_dry_run(f"set {FLAG} enabled_for_companies = {companies}")
        return 0
    now = datetime.now(timezone.utc)
    doc = {"flag": FLAG, "enabled_globally": False, "enabled_for_companies": companies,
           "enabled_for_users": (row or {}).get("enabled_for_users") or [],
           "enabled_percentage": 0,
           "description": "WhatsApp DM brain: one model with tools answers every free-text DM.",
           "updated_at": now}
    await db.feature_flags.update_one({"flag": FLAG}, {"$set": doc, "$setOnInsert": {"created_at": now}},
                                      upsert=True)
    await db.feature_flag_audit_log.insert_one({
        "flag": FLAG, "action": "updated" if row else "created",
        "before": {k: v for k, v in (row or {}).items() if k != "_id"} or None,
        "after": doc, "changed_by_user_id": f"script:{NAME}", "changed_at": now})
    print(f"{FLAG}: on for {len(companies)} compan{'y' if len(companies) == 1 else 'ies'}"
          f" ({'including' if company in companies else 'not'} {company}).")
    print("The server caches flags for up to a minute; the change applies within a minute.")
    return 0


def main(argv=None) -> int:
    refuse_legacy_flag(argv)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    g.add_argument("--show", action="store_true")
    ap.add_argument("--email")
    ap.add_argument("--company")
    add_guard_args(ap)
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
