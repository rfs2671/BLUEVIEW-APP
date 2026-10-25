"""The DM brain's off switch (flag dm_brain_off), for one company or everyone.

The brain answers every company's WhatsApp DMs by default. This switches a
company -- or everyone -- back to the old DM pipeline, and back on again.

    railway run python scripts/dm_brain_flag.py --show
    railway run python scripts/dm_brain_flag.py --email you@company.com --off      # dry run
    railway run python scripts/dm_brain_flag.py --email you@company.com --off \
        --i-know --reason "why" --session <id>
    railway run python scripts/dm_brain_flag.py --email you@company.com --on ...   # back on
    railway run python scripts/dm_brain_flag.py --everyone --off ...                # kill switch
    railway run python scripts/dm_brain_flag.py --everyone --on ...                 # undo it

Writes the feature_flags row and a feature_flag_audit_log row, as the admin
endpoint does; every write is also recorded in audit_logs with actor
"script:dm_brain_flag" (prod_guard). The brain also needs QWEN_API_KEY
(DeepInfra) on the service; without it everyone gets the old pipeline.
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
FLAG = "dm_brain_off"


def plan(row, *, on: bool, everyone: bool, company: str = ""):
    """(off for everyone, companies switched off, refusal) after this change.
    One company can't be switched back on while the kill switch holds
    everyone off -- the global switch wins, so "ON" would be untrue."""
    off_all = bool((row or {}).get("enabled_globally"))
    companies = [str(c) for c in (row or {}).get("enabled_for_companies") or []]
    if everyone:
        return (not on), companies, None
    if on and off_all:
        return off_all, companies, ("The DM brain is OFF for everyone (kill switch). Turn it back on with "
                                    "--everyone --on first; one company can't be on while it holds.")
    if on:
        companies = [c for c in companies if c != company]
    elif company not in companies:
        companies.append(company)
    return off_all, companies, None


async def run(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    apply = check_guard(a)
    db = audited(AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]], a, NAME)
    row = await db.feature_flags.find_one({"flag": FLAG})
    if a.show:
        if not row:
            print("DM brain: ON for every company (no off switch set).")
        elif row.get("enabled_globally"):
            print("DM brain: OFF for everyone (kill switch on).")
        else:
            off = row.get("enabled_for_companies") or []
            print(f"DM brain: ON, except {len(off)} compan{'y' if len(off) == 1 else 'ies'} switched off: {off}")
        return 0
    company = a.company
    if not a.everyone and a.email:
        user = await db.users.find_one({"email": a.email.strip().lower(), "is_deleted": {"$ne": True}})
        if not user:
            sys.exit("No user with that email.")
        company = str(user.get("company_id") or "")
    if not a.everyone and not company:
        sys.exit("Give --email, --company or --everyone.")
    off_all, companies, refused = plan(row, on=bool(a.on), everyone=bool(a.everyone), company=company)
    if refused:
        sys.exit(refused)
    what = "everyone" if a.everyone else company
    if not apply:
        report_dry_run(f"set {FLAG} enabled_globally = {off_all}, enabled_for_companies = {companies}")
        return 0
    now = datetime.now(timezone.utc)
    doc = {"flag": FLAG, "enabled_globally": off_all, "enabled_for_companies": companies,
           "enabled_for_users": (row or {}).get("enabled_for_users") or [],
           "enabled_percentage": 0,
           "description": "WhatsApp DM brain OFF switch: companies here (or everyone) get the old DM pipeline.",
           "updated_at": now}
    await db.feature_flags.update_one({"flag": FLAG}, {"$set": doc, "$setOnInsert": {"created_at": now}},
                                      upsert=True)
    await db.feature_flag_audit_log.insert_one({
        "flag": FLAG, "action": "updated" if row else "created",
        "before": {k: v for k, v in (row or {}).items() if k != "_id"} or None,
        "after": doc, "changed_by_user_id": f"script:{NAME}", "changed_at": now})
    print(f"DM brain {'OFF' if a.off else 'ON'} for {what}.")
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
    ap.add_argument("--everyone", action="store_true", help="the kill switch: every company")
    add_guard_args(ap)
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
