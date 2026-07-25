"""READ-ONLY diagnosis: why GET /projects/dob-summary returned open_violations=0
for 588 Boyland while the DOB Compliance screen shows "1 VIOLATION".

The screen tile is a resolution-BLIND raw ROW count
(dob-logs.jsx: allLogs.filter(record_type in {violation,swo}).length, no
resolution_state filter, no dedup). The endpoint dedups by raw_dob_id and
counts OPEN only (resolution_state NOT in {certified,dismissed,paid,resolved}),
with NO detected_at window. The window can only make the endpoint see MORE
rows, never fewer — so the 0 comes from the resolution_state filter or a
raw_dob_id dedup collapse.

This script decides which by (1) dumping every Boyland violation/swo row with
the fields that matter, (2) computing the screen-equivalent count, and (3)
replaying the endpoint's dedup+open logic to show which raw_dob_id survives and
its winning resolution_state, then printing a VERDICT:

  (A) endpoint CORRECT — the violation is CLOSED; the screen miscounts it.
  (B) endpoint WRONG — an open/null group was dropped, or a null raw_dob_id
      collapsed rows.

SAFETY: find() + aggregate() + count_documents() only. No writes. Reads
MONGO_URL / DB_NAME from the environment and NEVER prints the connection string.

Usage (PowerShell):
    $env:MONGO_URL = '<production Atlas URI>'
    $env:DB_NAME   = 'blueview'
    python backend/scripts/diag_boyland_violations.py
"""

import os
import asyncio
from datetime import datetime, timezone, timedelta

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:  # pragma: no cover
    raise SystemExit("motor is required: pip install motor")

PID = "6a5f63bc147407d3261df2c7"   # 588 Boyland
CLOSED = {"certified", "dismissed", "paid", "resolved"}   # endpoint's closed set


async def main():
    url = os.environ.get("MONGO_URL")
    dbname = os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME first.")

    db = AsyncIOMotorClient(url)[dbname]
    now = datetime.now(timezone.utc)
    win30 = now - timedelta(days=30)

    # 1. Every violation/swo row for Boyland (no filters), requested fields.
    rows = await db.dob_logs.find(
        {"project_id": PID, "record_type": {"$in": ["violation", "swo"]}},
        {"raw_dob_id": 1, "record_type": 1, "resolution_state": 1,
         "current_status": 1, "violation_date": 1, "detected_at": 1,
         "status_changed_at": 1, "is_seed_transition": 1, "is_deleted": 1},
    ).to_list(None)

    print(f"=== Boyland violation/swo rows: {len(rows)} ===")
    for r in rows:
        rs = r.get("resolution_state")
        print(f"  raw_dob_id={r.get('raw_dob_id')!r} type={r.get('record_type')} "
              f"resolution_state={rs!r} current_status={r.get('current_status')!r}\n"
              f"      violation_date={r.get('violation_date')!r} "
              f"detected_at={r.get('detected_at')} status_changed_at={r.get('status_changed_at')}\n"
              f"      is_seed_transition={r.get('is_seed_transition')} "
              f"is_deleted={r.get('is_deleted')}  "
              f"-> closed_per_endpoint={str(rs).lower() in CLOSED}")
        if not r.get("raw_dob_id"):
            print("      !! raw_dob_id is null/empty — dedup-collapse risk")

    # 2. Screen-equivalent count: record_type filter within the /dob-logs
    #    defaults (is_deleted!=true, is_seed_transition!=true, detected_at>=now-30d).
    screen_n = await db.dob_logs.count_documents({
        "project_id": PID, "record_type": {"$in": ["violation", "swo"]},
        "is_deleted": {"$ne": True}, "is_seed_transition": {"$ne": True},
        "detected_at": {"$gte": win30}})
    print(f"\nscreen-equivalent raw count (30d/notseed/notdeleted): {screen_n}")

    # 3. Endpoint dedup+open replay: which raw_dob_id survives, and its winning state.
    dedup = {"raw_dob_id": 1, "status_changed_at": -1, "detected_at": -1}
    surviving = await db.dob_logs.aggregate([
        {"$match": {"project_id": PID, "is_deleted": {"$ne": True},
                    "is_seed_transition": {"$ne": True},
                    "record_type": {"$in": ["violation", "swo"]}}},
        {"$sort": dedup},
        {"$group": {"_id": "$raw_dob_id",
                    "winning_resolution_state": {"$first": "$resolution_state"},
                    "winning_status_changed_at": {"$first": "$status_changed_at"},
                    "rows_collapsed": {"$sum": 1}}},
    ]).to_list(None)
    print(f"\nendpoint dedup groups: {len(surviving)}")
    open_ct = 0
    for g in surviving:
        rs = str(g.get("winning_resolution_state")).lower()
        is_open = rs not in CLOSED
        open_ct += is_open
        print(f"  raw_dob_id={g['_id']!r} rows_collapsed={g['rows_collapsed']} "
              f"winning_resolution_state={g.get('winning_resolution_state')!r} "
              f"-> counts_open={is_open}")
    print(f"\nendpoint open_violations = {open_ct}")

    print("\n=== VERDICT ===")
    if open_ct == 0 and surviving and all(
            str(g.get("winning_resolution_state")).lower() in CLOSED for g in surviving):
        print("  (A) endpoint CORRECT — Boyland's violation is CLOSED "
              "(resolution_state in the closed set); the screen tile is "
              "resolution-blind and miscounts it as open.")
    elif open_ct == 0:
        print("  (B) endpoint WRONG — a group with an OPEN/null winning "
              "resolution_state was not counted, OR a null raw_dob_id collapsed "
              "rows. Inspect the dump above (dedup-collapse / winning-row).")
    else:
        print(f"  endpoint now counts {open_ct} open — re-run verify_dob_summary.py.")


if __name__ == "__main__":
    asyncio.run(main())
