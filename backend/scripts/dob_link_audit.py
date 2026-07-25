"""Read-only DOB link audit. For every project that has dob_logs, reports —
per record_type — how many records carry a working dob_link vs. an empty one,
and prints up to 3 DISTINCT real URLs per type so you can click a sample of
each (permit, violation, complaint, swo, inspection, job_status) and confirm
none dead-ends.

Reads MONGO_URL / DB_NAME from the environment; NEVER prints the connection
string. Makes no writes. Run against production:

    # PowerShell
    $env:MONGO_URL = '<production Atlas URI>'
    $env:DB_NAME   = 'blueview'
    python dob_link_audit.py
"""
import os, asyncio
from collections import defaultdict

TYPES = ["permit", "violation", "complaint", "swo", "inspection", "job_status"]
SAMPLES_PER_TYPE = 3


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    url = os.environ.get("MONGO_URL")
    dbname = os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME in the environment first.")
    client = AsyncIOMotorClient(url)
    db = client[dbname]

    # Projects that actually have DOB logs.
    pids = await db.dob_logs.distinct("project_id")
    print(f"Projects with dob_logs: {len(pids)}\n" + "=" * 72)

    for pid in pids:
        proj = await db.projects.find_one({"_id": pid}) or \
               await db.projects.find_one({"id": pid}) or {}
        name = proj.get("name") or proj.get("address") or "(unknown project)"
        binv = proj.get("nyc_bin") or proj.get("bin") or "—"
        total = await db.dob_logs.count_documents({"project_id": pid})
        print(f"\nPROJECT: {name}  (id={pid}, BIN={binv})  — {total} records")

        for rt in TYPES:
            q = {"project_id": pid, "record_type": rt}
            n = await db.dob_logs.count_documents(q)
            if n == 0:
                print(f"  {rt:11s}: 0 records")
                continue
            # split by link presence
            with_link = await db.dob_logs.count_documents(
                {**q, "dob_link": {"$nin": [None, ""]}})
            without = n - with_link
            # collect up to N distinct non-empty links
            seen = []
            cursor = db.dob_logs.find(
                {**q, "dob_link": {"$nin": [None, ""]}},
                {"dob_link": 1, "raw_dob_id": 1}
            ).limit(200)
            async for doc in cursor:
                link = (doc.get("dob_link") or "").strip()
                if link and link not in [s[0] for s in seen]:
                    seen.append((link, doc.get("raw_dob_id")))
                if len(seen) >= SAMPLES_PER_TYPE:
                    break
            flag = "  <-- SOME EMPTY LINKS" if without else ""
            print(f"  {rt:11s}: {n} records | {with_link} linked | {without} empty{flag}")
            for link, rid in seen:
                print(f"       [{rid}] {link}")
            if with_link == 0:
                print(f"       (!) NO record of type '{rt}' has a dob_link")

    # Cross-project distinct-link sample per type (guarantees >=1 URL per type
    # even if a single project lacks a type).
    print("\n" + "=" * 72 + "\nONE DISTINCT SAMPLE PER TYPE ACROSS ALL PROJECTS:")
    for rt in TYPES:
        doc = await db.dob_logs.find_one(
            {"record_type": rt, "dob_link": {"$nin": [None, ""]}},
            {"dob_link": 1, "raw_dob_id": 1, "project_id": 1})
        if doc:
            print(f"  {rt:11s}: {doc.get('dob_link')}   (raw_dob_id={doc.get('raw_dob_id')})")
        else:
            anyrec = await db.dob_logs.find_one({"record_type": rt})
            print(f"  {rt:11s}: NO LINKED RECORD"
                  + (" (type exists but all links empty)" if anyrec else " (no records of this type)"))

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
