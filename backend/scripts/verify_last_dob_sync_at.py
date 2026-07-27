#!/usr/bin/env python3
"""READ-ONLY post-deploy check for last_dob_sync_at.

Run this after the deploy AND after at least one sync cycle has had a chance to
run (the nightly DOB scan fires at 04:00 EST; a manual "Sync Now" on any single
project also stamps that project immediately).

It answers one question: has the rolling per-project sync timestamp started
landing on real project docs, so the SYNCED column / never-synced card /
project badge show a real time instead of "Never"?

  python backend/scripts/verify_last_dob_sync_at.py

Requires MONGO_URL + DB_NAME in the environment, same contract as the other
scripts in this directory.

WRITES NOTHING. It only reads db.projects (and db.system_config for the
cross-check below). Safe to run against production.

Cross-check: system_config holds `initial_scan_done:dob:{project_id}` with a
`completed_at` that the sync path has ALWAYS refreshed on every successful run,
long before last_dob_sync_at existed. Any project whose completed_at is newer
than its last_dob_sync_at (or that has completed_at but no last_dob_sync_at)
has synced since the deploy WITHOUT stamping the new field — which would mean
the write is not on the path it should be. That is the signal to look for.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


def _age(ts):
    if not ts:
        return "—"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - ts).total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


async def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    db = AsyncIOMotorClient(mongo_url)[db_name]

    projects = await db.projects.find(
        {"track_dob_status": True, "is_deleted": {"$ne": True}},
        {"name": 1, "address": 1, "nyc_bin": 1,
         "last_dob_sync_at": 1, "first_poll_completed_at": 1},
    ).to_list(length=None)

    if not projects:
        print("No DOB-tracked projects found — nothing to verify.")
        return 0

    stamped, unstamped = [], []
    for p in projects:
        (stamped if p.get("last_dob_sync_at") else unstamped).append(p)

    print(f"DOB-tracked projects: {len(projects)}")
    print(f"  with last_dob_sync_at : {len(stamped)}")
    print(f"  without (show 'Never') : {len(unstamped)}\n")

    if stamped:
        print("STAMPED — these now render a real relative time:")
        for p in sorted(stamped, key=lambda d: d["last_dob_sync_at"], reverse=True):
            print(f"  {str(p.get('name') or p.get('address'))[:38]:<40} "
                  f"{_age(p.get('last_dob_sync_at'))}")
        print()

    if unstamped:
        print("NOT YET STAMPED — these still render 'Never':")
        for p in unstamped:
            print(f"  {str(p.get('name') or p.get('address'))[:38]:<40} "
                  f"bin={p.get('nyc_bin') or '—'}")
        print()

    # ── Cross-check against the pre-existing rolling marker ──────────────
    stale = []
    for p in projects:
        marker = await db.system_config.find_one(
            {"key": f"initial_scan_done:dob:{p['_id']}"}, {"completed_at": 1}
        )
        done_at = (marker or {}).get("completed_at")
        if not done_at:
            continue
        last = p.get("last_dob_sync_at")
        if last is None or (
            done_at.replace(tzinfo=done_at.tzinfo or timezone.utc)
            > last.replace(tzinfo=last.tzinfo or timezone.utc)
        ):
            stale.append((p, done_at, last))

    if stale:
        print("!! SYNCED SINCE DEPLOY BUT last_dob_sync_at NOT UPDATED:")
        print("   (a successful sync completed without stamping the new field —")
        print("    the write is not on the completion path it should be)")
        for p, done_at, last in stale:
            print(f"  {str(p.get('name'))[:38]:<40} "
                  f"marker={_age(done_at)}  field={_age(last)}")
        return 1

    print("OK — every project that has synced since deploy carries "
          "last_dob_sync_at.")
    if unstamped:
        print("     Projects listed as NOT YET STAMPED simply have not run a "
              "sync yet;\n     they resolve on the next nightly scan (04:00 EST) "
              "or a manual Sync Now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
