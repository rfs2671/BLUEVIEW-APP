"""READ-ONLY audit of the mislabeled Rodent Inspection (p937-wjvj) records in
dob_logs, ahead of deletion. Makes NO writes. Proves that a delete filter of
{record_type: "inspection"} targets ONLY p937-wjvj-sourced rodent rows and
cannot catch the correct DOB inspection sources (boiler/elevator/facade, which
carry their own record_types).

Reads MONGO_URL / DB_NAME from the environment; never prints the connection
string.

    $env:MONGO_URL = '<production Atlas URI>'; $env:DB_NAME = 'blueview'
    python rodent_inspection_audit.py
"""
import os, asyncio
from datetime import datetime, timezone, timedelta

# The correct DOB inspection sources — must NEVER be caught by the delete filter.
CORRECT_INSPECTION_TYPES = ["boiler", "elevator", "facade_fisp", "cofo"]


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    url, dbname = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME in the environment first.")
    db = AsyncIOMotorClient(url)[dbname]
    INSPECTION = {"record_type": "inspection"}

    # (1) Distinct `dataset` values among record_type=="inspection".
    #     Expectation: only "p937-wjvj" and/or null/unstamped (forward-only
    #     stamping means pre-V2.3.A2 rows have no dataset). ANY other value is
    #     a red flag that the filter would over-delete — investigate before use.
    datasets = await db.dob_logs.distinct("dataset", INSPECTION)
    print("=" * 72)
    print("(1) distinct `dataset` values among record_type=='inspection':")
    for d in datasets:
        n = await db.dob_logs.count_documents({**INSPECTION, "dataset": d})
        print(f"      {repr(d):20s} -> {n}")
    unstamped = await db.dob_logs.count_documents(
        {**INSPECTION, "dataset": {"$in": [None]}})
    unstamped += await db.dob_logs.count_documents(
        {**INSPECTION, "dataset": {"$exists": False}})
    foreign = [d for d in datasets if d not in (None, "p937-wjvj")]
    print(f"    unstamped (null/absent dataset): {unstamped}")
    if foreign:
        print(f"    !!! UNEXPECTED non-p937 datasets on inspection rows: {foreign}")
        print("    !!! DO NOT delete by record_type alone — investigate these first.")
    else:
        print("    OK: every inspection row is p937-wjvj or unstamped — "
              "delete-by-record_type is precise.")

    # (2) Totals + the stamped-vs-unstamped gap (why record_type is the safe key).
    total = await db.dob_logs.count_documents(INSPECTION)
    stamped = await db.dob_logs.count_documents({**INSPECTION, "dataset": "p937-wjvj"})
    print("\n(2) counts:")
    print(f"    record_type=='inspection' TOTAL .............. {total}")
    print(f"      of which dataset=='p937-wjvj' (stamped) .... {stamped}")
    print(f"      of which unstamped (legacy, no dataset) .... {total - stamped}")
    print("    -> {record_type:'inspection'} catches ALL of them;")
    print("       {dataset:'p937-wjvj'} alone would MISS the unstamped ones.")

    # (3) Cross-check: the CORRECT inspection sources are NOT caught.
    print("\n(3) correct DOB inspection sources (must be untouched by the filter):")
    for rt in CORRECT_INSPECTION_TYPES:
        n = await db.dob_logs.count_documents({"record_type": rt})
        print(f"      record_type=='{rt}' .......... {n}  (NOT matched by inspection filter)")

    # (4) Per-project breakdown (name + BIN + how many rodent rows).
    print("\n(4) per-project rodent inspection rows:")
    pids = await db.dob_logs.distinct("project_id", INSPECTION)
    for pid in pids:
        proj = await db.projects.find_one({"_id": pid}) or \
               await db.projects.find_one({"id": pid}) or {}
        name = proj.get("name") or proj.get("address") or "(unknown)"
        binv = proj.get("nyc_bin") or proj.get("bin") or "-"
        n = await db.dob_logs.count_documents({**INSPECTION, "project_id": pid})
        print(f"      {name[:32]:32s} BIN={binv:9s} pid={pid} -> {n} rows")

    # (5) Live risk-score delta: inspections_failed_60d contribution per project.
    #     Facet = {record_type:'inspection', severity:'Action', inspection_date >= now-60d}.
    #     Score adds 12 points per such row (OWN_BUILDING_WEIGHT_INSPECTIONS_FAILED_60D).
    now = datetime.now(timezone.utc)
    cut60 = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S.000")
    print(f"\n(5) risk-score delta — inspections_failed_60d (window >= {cut60[:10]}):")
    action_total = await db.dob_logs.count_documents({**INSPECTION, "severity": "Action"})
    print(f"    total failed (severity=='Action') rodent rows, all-time: {action_total}")
    for pid in pids:
        q = {**INSPECTION, "project_id": pid, "severity": "Action",
             "inspection_date": {"$gte": cut60}}
        n = await db.dob_logs.count_documents(q)
        print(f"      pid={pid}: inspections_failed_60d = {n}  -> {n * 12} risk points removed on delete")
    print("    (other score facets — violations_30d/90d, open_complaints_30d — are")
    print("     UNAFFECTED: they filter record_type in violation/swo/complaint, not inspection.)")

    # (6) Sample rows so a human can eyeball that these are rat inspections.
    print("\n(6) sample rodent rows (first 6):")
    async for r in db.dob_logs.find(INSPECTION, {
            "raw_dob_id": 1, "dataset": 1, "record_type": 1, "severity": 1,
            "inspection_date": 1, "ai_summary": 1}).limit(6):
        s = (r.get("ai_summary") or "")[:60]
        print(f"      raw_dob_id={r.get('raw_dob_id')}  dataset={r.get('dataset')}  "
              f"sev={r.get('severity')}  date={r.get('inspection_date')}")
        print(f"          summary: {s}")

    AsyncIOMotorClient(url).close()


if __name__ == "__main__":
    asyncio.run(main())
