"""Preview the NEW permit / job_status dob_link for every live record.

Mirrors _build_dob_link's permit/job_status branch after the fix: the whole
type resolves to the BIS BIN property profile (PropertyProfileOverviewServlet
?bin=<bin>, url-encoded) — the SAME form already shipped for the violation
fallback — or to NO link when the record has no BIN. For every permit and
job_status record it prints the CURRENT stored dob_link and the NEW url the
fixed builder emits, then asserts:

  * every NEW url is the clean PropertyProfileOverviewServlet form OR empty,
  * none is the generic data.cityofnewyork.us page,
  * none is malformed,
  * BIN-less records get NO link,
and reports how many permit/job_status records lack a BIN.

Read-only. Reads MONGO_URL / DB_NAME from env; never prints the connection
string; makes NO writes.

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='blueview'
    python permit_link_preview.py
"""
import os
import asyncio
from urllib.parse import quote_plus

GOOD_PREFIX = "https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet"


def bis_bin_overview_url(bin_val):
    """EXACT mirror of server._bis_bin_overview_url."""
    if not bin_val:
        return ""
    return f"{GOOD_PREFIX}?bin={quote_plus(str(bin_val))}"


def new_permit_link(rec):
    """EXACT mirror of _build_dob_link's fixed permit/job_status branch."""
    bin_val = str(rec.get("bin") or rec.get("bin__") or "").strip()
    return bis_bin_overview_url(bin_val)


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    url, dbname = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME in the environment first.")
    db = AsyncIOMotorClient(url)[dbname]

    q = {"record_type": {"$in": ["permit", "job_status"]}, "is_deleted": {"$ne": True}}
    total = await db.dob_logs.count_documents(q)
    print(f"permit/job_status records: {total}\n" + "=" * 84)

    n_overview = n_nolink = n_generic = n_malformed = n_no_bin = 0
    by_type = {}
    async for rec in db.dob_logs.find(q).sort("detected_at", -1):
        rtype = rec.get("record_type")
        by_type[rtype] = by_type.get(rtype, 0) + 1
        bin_val = str(rec.get("bin") or rec.get("bin__") or "").strip()
        jfn = rec.get("job_filing_number") or rec.get("job__") or rec.get("job_number") or ""
        cur = str(rec.get("dob_link") or "")
        new = new_permit_link(rec)

        if not bin_val:
            n_no_bin += 1
        if new == "":
            n_nolink += 1
            verdict = "NO LINK (no BIN)" if not bin_val else "NO LINK"
        elif new.startswith(GOOD_PREFIX + "?bin="):
            n_overview += 1
            verdict = "overview OK"
        elif "data.cityofnewyork.us" in new:
            n_generic += 1
            verdict = "!! GENERIC OPEN DATA"
        else:
            n_malformed += 1
            verdict = "!! MALFORMED"

        cur_flag = " [was generic]" if "data.cityofnewyork.us" in cur else ""
        print(f"[{rtype:10}] bin={bin_val or '-':9} job={str(jfn) or '-':16} {verdict}")
        print(f"      old: {cur or '(none)'}{cur_flag}")
        print(f"      new: {new or '(no link)'}")

    print("\n" + "=" * 84)
    print(f"by type: {by_type}")
    print(f"clean PropertyProfileOverviewServlet : {n_overview}")
    print(f"no link (no BIN)                     : {n_nolink}  (records lacking a BIN: {n_no_bin})")
    print(f"generic data.cityofnewyork.us        : {n_generic}   <-- must be 0")
    print(f"malformed                            : {n_malformed}   <-- must be 0")
    ok = (n_generic == 0 and n_malformed == 0
          and n_overview + n_nolink == total)
    print("\nRESULT:", "ALL CLEAN — every record is BIN overview or no-link, none generic/malformed."
          if ok else "FAIL — see flagged rows above.")
    AsyncIOMotorClient(url).close()


if __name__ == "__main__":
    asyncio.run(main())
