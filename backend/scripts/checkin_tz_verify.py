"""Check-in timezone FIX verification. Injects the TWO boundary check-ins that
exercise NYC-local day bucketing in both directions, in one run:

  R1  8:30pm EDT  (summer, offset -4)  -> 00:30 UTC the NEXT calendar day.
      The rollover case: old UTC-midnight bucketing put this on the wrong
      (next) compliance-log day; the fix keeps it on the Eastern day.
  R2  12:30am EST (winter, offset -5)  -> 05:30 UTC the SAME calendar day.
      The reverse/lower-boundary case: confirms an early-morning Eastern
      check-in stays on its own Eastern day and is NOT shifted a day earlier
      (guards against over-correcting past the 05:00-UTC start boundary).

Both records use DST-guaranteed dates (Jul 15 / Jan 15 of the current year) so
the "EDT" / "EST" labels are always accurate, whatever day you run this.

For each record it reports:
  (1) stored check_in_time (aware UTC — what Mongo holds) and its tzinfo,
  (2) the NYC day it buckets into via get_day_range_est() vs. what the OLD
      UTC-midnight bucketing would have given, with a PASS/FAIL assertion that
      the fixed bucketing lands on the record's Eastern calendar day, and
  (3) the UI-displayed wall-clock time (must read 8:30 PM / 12:30 AM).
Then, per record, it runs BOTH ON SITE definitions windowed to that record's
NYC day — dashboard (company-scoped distinct worker_id, checked_in) and the
project tile (project-scoped count, checked_in) — and asserts the record is
counted by BOTH (neither drops it on date handling); it prints both numbers.

Finally it DELETES only the two records it created (by their exact ids, guarded
on the marker). Nothing else is touched. Safe against production.

  $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='blueview'
  python checkin_tz_verify.py                     # inject 2 -> report -> delete 2
  python checkin_tz_verify.py --project-id <id>   # attach to a specific project
  python checkin_tz_verify.py --keep              # leave both for UI inspection
  python checkin_tz_verify.py --cleanup           # ONLY remove left-behind test records

Reads MONGO_URL / DB_NAME from env; never prints the connection string.
"""
import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
MARKER = "CHECKIN_TZ_VERIFY"  # unique field; cleanup is guarded on this


def get_day_range_est(date_str):
    """Mirror server.get_day_range_est() — the FIXED bucketing."""
    midnight_e = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=EASTERN)
    start_utc = midnight_e.astimezone(timezone.utc)
    return start_utc, start_utc + timedelta(hours=24)


def _old_utc_day_range(date_str):
    """The OLD buggy bucketing: report date parsed as UTC midnight."""
    start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


async def cleanup_marker(db):
    res = await db.checkins.delete_many({"_tz_test_marker": MARKER})
    print(f"[cleanup] deleted {res.deleted_count} test check-in(s) carrying marker {MARKER!r}.")


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    argv = sys.argv[1:]
    keep = "--keep" in argv
    cleanup = "--cleanup" in argv
    project_id = argv[argv.index("--project-id") + 1] if "--project-id" in argv else None

    url, dbname = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME in the environment first.")
    client = AsyncIOMotorClient(url)
    db = client[dbname]

    if cleanup:
        await cleanup_marker(db)
        client.close()
        return

    # ---- pick a real project so the project-scoped tile query can see the rows ----
    if project_id:
        proj = await db.projects.find_one({"id": project_id}) or \
               await db.projects.find_one({"_id": project_id})
    else:
        proj = await db.projects.find_one({"is_deleted": {"$ne": True}})
    if not proj:
        raise SystemExit("No project found — pass --project-id <id> for an existing project.")
    pid = proj.get("id") or str(proj.get("_id"))
    company_id = proj.get("company_id")
    print(f"target project: {proj.get('name') or '(unnamed)'}  id={pid}  company_id={company_id}\n"
          + "=" * 76)

    year = datetime.now(EASTERN).year
    # (label, Eastern-local wall time) — dates chosen to guarantee the DST offset.
    cases = [
        ("R1 8:30pm EDT (rollover)", datetime(year, 7, 15, 20, 30, tzinfo=EASTERN)),
        ("R2 12:30am EST (lower boundary)", datetime(year, 1, 15, 0, 30, tzinfo=EASTERN)),
    ]

    created_ids = []
    all_pass = True
    for label, checkin_e in cases:
        checkin_utc = checkin_e.astimezone(timezone.utc)   # aware UTC — what we store
        est_day = checkin_e.strftime("%Y-%m-%d")
        utc_day = checkin_utc.strftime("%Y-%m-%d")
        doc_id = f"tztest-{uuid.uuid4().hex[:12]}"
        worker_id = f"TZTEST-{uuid.uuid4().hex[:8]}"
        await db.checkins.insert_one({
            "id": doc_id,
            "project_id": pid,
            "company_id": company_id,
            "worker_id": worker_id,
            "worker_name": "TZ Verify Worker (DELETE ME)",
            "check_in_time": checkin_utc,
            "status": "checked_in",
            "is_deleted": False,
            "_tz_test_marker": MARKER,
        })
        created_ids.append(doc_id)

        stored = await db.checkins.find_one({"id": doc_id})
        scit = stored["check_in_time"]
        scit_aware = scit if scit.tzinfo else scit.replace(tzinfo=timezone.utc)

        print(f"\n{'-'*76}\n{label}")
        print("(1) STORED check_in_time")
        print(f"    inserted (aware UTC): {checkin_utc.isoformat()}")
        print(f"    read from Mongo     : {scit}   tzinfo={scit.tzinfo}  "
              "(BSON stores UTC; naive-on-read = UTC by convention)")
        print(f"    Eastern wall time   : {checkin_e.strftime('%Y-%m-%d %H:%M %Z')}"
              f"   |  Eastern day={est_day}  UTC day={utc_day}"
              + ("  <-- differ (rollover)" if est_day != utc_day else "  (same day)"))

        ns, ne = get_day_range_est(est_day)
        in_new = ns <= scit_aware < ne
        os_, oe = _old_utc_day_range(est_day)
        in_old = os_ <= scit_aware < oe
        new_day = est_day if in_new else "(not in Eastern-day window!)"
        old_day = est_day if in_old else utc_day
        ok = in_new and new_day == est_day
        all_pass = all_pass and ok
        print("(2) DAY BUCKETING")
        print(f"    FIXED get_day_range_est({est_day}) -> buckets into {new_day}"
              f"   [{ok and 'PASS' or 'FAIL'}: expected {est_day}]")
        print(f"    OLD  UTC-midnight({est_day})       -> buckets into {old_day}"
              f"   [{'same as fixed' if in_old else 'WRONG day — this is the bug the fix corrects'}]")

        disp = scit_aware.astimezone(EASTERN)
        print("(3) UI-DISPLAYED TIME")
        print(f"    check_in_time in Eastern = {disp.strftime('%I:%M %p %Z').lstrip('0')}"
              f"   [expected {checkin_e.strftime('%I:%M %p').lstrip('0')}]")

        # ON SITE: both definitions windowed to THIS record's NYC day; both must see it.
        day_start, day_end = ns, ne
        dash_q = {"is_deleted": {"$ne": True}, "status": "checked_in",
                  "check_in_time": {"$gte": day_start, "$lt": day_end}}
        if company_id:
            dash_q["company_id"] = company_id
        tile_q = {"is_deleted": {"$ne": True}, "status": "checked_in", "project_id": pid,
                  "check_in_time": {"$gte": day_start, "$lt": day_end}}
        dash_workers = await db.checkins.distinct("worker_id", dash_q)
        tile_count = await db.checkins.count_documents(tile_q)
        seen_dash = worker_id in dash_workers
        seen_tile = tile_count >= 1 and worker_id in await db.checkins.distinct("worker_id", tile_q)
        both = seen_dash and seen_tile
        all_pass = all_pass and both
        print("(4) ON SITE (both definitions windowed to this NYC day)")
        print(f"    dashboard distinct(worker_id | company, checked_in) = {len(dash_workers)}"
              f"   record present? {seen_dash}")
        print(f"    tile      count(project, checked_in)                = {tile_count}"
              f"   record present? {seen_tile}")
        print(f"    -> both count this record identically? {both}"
              f"   [{'PASS' if both else 'FAIL'}]")

    print("\n" + "=" * 76)
    print(f"OVERALL: {'ALL PASS' if all_pass else 'FAIL — see above'}")

    if keep:
        print(f"\n[--keep] Both records left in place (marker={MARKER!r}). Inspect in the UI,"
              " then remove with:  python checkin_tz_verify.py --cleanup")
    else:
        res = await db.checkins.delete_many({"_tz_test_marker": MARKER,
                                             "id": {"$in": created_ids}})
        print(f"[cleanup] deleted {res.deleted_count} of the {len(created_ids)} records "
              "this run created (matched by exact id + marker).")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
