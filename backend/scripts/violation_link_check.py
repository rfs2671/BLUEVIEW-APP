"""Read-only diagnostic: are the stored violation/swo (and all DOB) links dead?

The link builder (_build_dob_link) already emits the live
PropertyProfileOverviewServlet BIN profile for tier-3 fallbacks, and the
dob-logs READ path (server.py ~18085) rebuilds dob_link from each row's
`raw_record` on every read — so a stale stored OverviewByBinServlet value is
replaced with the live URL at read time IF the row has a raw_record. A row with
NO raw_record keeps whatever was stored at ingest.

For every DOB record this prints:
  * record_type and raw_dob_id
  * the STORED dob_link (flagged if it is the dead OverviewByBinServlet)
  * whether the row has a raw_record (→ auto-heals on read)
  * the link _build_dob_link emits RIGHT NOW from the raw_record (what the UI
    actually shows), using the real server function — no reimplementation

and summarizes: how many stored links are still the dead servlet, how many of
those auto-heal on read (have raw_record) vs. are genuinely stale (no
raw_record → need a re-poll), and confirms zero OverviewByBin in the freshly
built links. Tier-1 (ISN) / tier-2 (ECB) records show their specific-record
deep link, proving that logic is intact.

Read-only. Reads MONGO_URL / DB_NAME from env; never prints the connection
string; makes NO writes. Imports the real server module (sets test-safe env
defaults first) so the emitted URL is authoritative.

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='blueview'
    python violation_link_check.py            # violation + swo only
    python violation_link_check.py --all      # every record type
"""
import os
import sys
import asyncio

os.environ.setdefault("JWT_SECRET", "diag_only_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

DEAD = "OverviewByBin"


async def main():
    import server  # real _build_dob_link — no reimplementation
    from motor.motor_asyncio import AsyncIOMotorClient

    url, dbname = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME in the environment first.")
    db = AsyncIOMotorClient(url)[dbname]

    types = None if "--all" in sys.argv[1:] else ["violation", "swo"]
    q = {"is_deleted": {"$ne": True}}
    if types:
        q["record_type"] = {"$in": types}
    total = await db.dob_logs.count_documents(q)
    print(f"records: {total}  ({'all types' if types is None else ', '.join(types)})\n"
          + "=" * 86)

    stored_dead = heals = genuinely_stale = built_dead = no_bin = 0
    async for rec in db.dob_logs.find(q).sort("detected_at", -1):
        rtype = rec.get("record_type")
        rid = rec.get("raw_dob_id") or rec.get("_id")
        stored = str(rec.get("dob_link") or "")
        raw = rec.get("raw_record") or {}
        has_raw = bool(raw)
        built = ""
        try:
            built = server._build_dob_link(raw, rtype) if has_raw else ""
        except Exception as e:  # never let one bad row abort the audit
            built = f"(builder error: {e!r})"

        stored_is_dead = DEAD in stored
        if stored_is_dead:
            stored_dead += 1
            if has_raw:
                heals += 1
            else:
                genuinely_stale += 1
        if DEAD in built:
            built_dead += 1
        if not str(rec.get("bin") or rec.get("nyc_bin") or raw.get("bin") or "").strip():
            no_bin += 1

        flags = []
        if stored_is_dead:
            flags.append("STORED=DEAD")
        if not has_raw:
            flags.append("NO raw_record")
        if DEAD in built:
            flags.append("BUILT=DEAD")
        tag = ("  <-- " + ", ".join(flags)) if flags else ""
        print(f"[{rtype:10}] {str(rid)[:34]:34}{tag}")
        print(f"      stored: {stored or '(none)'}")
        print(f"      built : {built or '(no raw_record → UI shows the stored value above)'}")

    print("\n" + "=" * 86)
    print(f"stored links that are the dead OverviewByBin servlet : {stored_dead}")
    print(f"  ...of those, auto-heal on read (have raw_record)   : {heals}")
    print(f"  ...genuinely stale (NO raw_record → need re-poll)  : {genuinely_stale}")
    print(f"freshly BUILT links containing OverviewByBin         : {built_dead}   <-- must be 0")
    print(f"records with no BIN anywhere (would get no link)     : {no_bin}")
    if built_dead == 0 and genuinely_stale == 0:
        print("\nRESULT: no live dead links — builder emits the live URL and every stored"
              "\n        dead link auto-heals on read (all rows have raw_record).")
    elif built_dead == 0:
        print(f"\nRESULT: builder is clean, but {genuinely_stale} row(s) lack a raw_record and keep"
              "\n        a stale stored link — re-poll those projects (/projects/{id}/dob-sync)"
              "\n        to regenerate dob_link. No code change fixes stored data.")
    else:
        print("\nRESULT: builder still emits OverviewByBin for some record — investigate above.")
    AsyncIOMotorClient(url).close()


if __name__ == "__main__":
    asyncio.run(main())
