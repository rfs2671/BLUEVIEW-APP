"""Read-only: per project, break down permits the way dob-summary's Option-A
`total_permits` (active) facet will. Deduped by raw_dob_id (latest status);
for each deduped permit classify:

  active    = expiration_date parses (ISO) AND >= today AND status != REVOKED
  expired   = expiration_date parses AND < today
  no_expiry = expiration_date null / unparseable (ISO)  <-- the DISCLOSURE count
              (all DOB NOW Electrical permits land here — dm9a-ab7w has no
               permit expiration_date), and would be EXCLUDED from the active
               denominator under Option A.
  revoked   = status == REVOKED (excluded regardless)

The number that decides whether the permit tile needs a visible disclosure is
**no_expiry** per project. If it's 0 on both live projects, a code comment +
followup suffices; if non-zero, the tile must disclose "N without expiry data
not counted".

Read-only. MONGO_URL / DB_NAME from env; never prints the connection string; no
writes.

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='blueview'
    python permit_active_audit.py
"""
import os
import asyncio
from datetime import datetime, timezone

def _parse_iso(v):
    """Mirror $dateFromString default (ISO-8601). Non-ISO / null -> None."""
    if not v or not isinstance(v, str):
        return None
    s = v.strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    url, dbname = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME in the environment first.")
    db = AsyncIOMotorClient(url)[dbname]

    # Same boundary the permits_expiring facet uses (UTC midnight today), so the
    # active set is a superset of expiring.
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    match = {"is_deleted": {"$ne": True}, "is_seed_transition": {"$ne": True},
             "record_type": "permit"}
    pids = await db.dob_logs.distinct("project_id", match)
    print(f"projects with permits: {len(pids)}\n" + "=" * 78)

    grand_no_expiry = 0
    for pid in pids:
        proj = await db.projects.find_one({"_id": pid}) or \
               await db.projects.find_one({"id": pid}) or {}
        name = proj.get("name") or "(unknown)"

        # dedup by raw_dob_id — keep latest (status_changed_at, detected_at)
        latest = {}
        async for r in db.dob_logs.find({**match, "project_id": pid}).sort(
                [("status_changed_at", -1), ("detected_at", -1)]):
            rid = r.get("raw_dob_id")
            if rid not in latest:
                latest[rid] = r

        total = active = expired = no_expiry = revoked = 0
        for r in latest.values():
            status = str(r.get("permit_status") or "").strip().upper()
            total += 1
            if status == "REVOKED":
                revoked += 1
                continue
            exp = _parse_iso(r.get("expiration_date"))
            if exp is None:
                no_expiry += 1
            elif exp >= today:
                active += 1
            else:
                expired += 1

        grand_no_expiry += no_expiry
        flag = "   <-- NEEDS DISCLOSURE" if no_expiry else ""
        print(f"\n{name}  (id={pid})")
        print(f"   total deduped permits : {total}")
        print(f"   active (>= today)     : {active}   <-- tile denominator")
        print(f"   expired (< today)     : {expired}")
        print(f"   REVOKED (excluded)    : {revoked}")
        print(f"   no/unparseable expiry : {no_expiry}{flag}")

    print("\n" + "=" * 78)
    print(f"TOTAL no-expiry permits across all projects: {grand_no_expiry}")
    print("If 0 on the two live projects -> code comment + followup is enough.")
    print("If non-zero -> the permit tile must disclose the excluded count.")
    AsyncIOMotorClient(url).close()


if __name__ == "__main__":
    asyncio.run(main())
