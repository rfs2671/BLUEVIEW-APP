"""Turn the DM brain (flag dm_brain_v2) on or off for one company.

    railway run python scripts/dm_brain_flag.py --email you@company.com --on
    railway run python scripts/dm_brain_flag.py --company <company_id> --off
    railway run python scripts/dm_brain_flag.py --show

Writes the feature_flags row (enabled_for_companies) and an audit row in
feature_flag_audit_log, as the admin endpoint does. Nothing else changes:
companies not on the list keep the old DM pipeline. The brain also needs
ANTHROPIC_API_KEY on the service; without it everyone gets the old one.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

FLAG = "dm_brain_v2"


async def run(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
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
    now = datetime.now(timezone.utc)
    before = dict(row) if row else None
    companies = [str(c) for c in (row or {}).get("enabled_for_companies") or []]
    if a.on and company not in companies:
        companies.append(company)
    if a.off:
        companies = [c for c in companies if c != company]
    doc = {"flag": FLAG, "enabled_globally": False, "enabled_for_companies": companies,
           "enabled_for_users": (row or {}).get("enabled_for_users") or [],
           "enabled_percentage": 0,
           "description": "WhatsApp DM brain: one model with tools answers every free-text DM.",
           "updated_at": now}
    await db.feature_flags.update_one({"flag": FLAG}, {"$set": doc, "$setOnInsert": {"created_at": now}},
                                      upsert=True)
    await db.feature_flag_audit_log.insert_one({
        "flag": FLAG, "action": "updated" if row else "created",
        "before": {k: v for k, v in (before or {}).items() if k != "_id"} or None,
        "after": doc, "changed_by_user_id": "script:dm_brain_flag", "changed_at": now})
    print(f"{FLAG}: on for {len(companies)} compan{'y' if len(companies) == 1 else 'ies'}"
          f" ({'including' if company in companies else 'not'} {company}).")
    print("The server caches flags for a short while; the change applies within a minute.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    g.add_argument("--show", action="store_true")
    ap.add_argument("--email")
    ap.add_argument("--company")
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
