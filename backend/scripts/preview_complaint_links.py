"""READ-ONLY preview of the URL the NEW complaint link builder would emit for
every stored complaint, so you can confirm:
  • DOB complaints (eabe-havv)  -> OverviewForComplaintServlet?complaintno=<n>
  • 311 complaints  (erm2-nwe9) -> (none)  [raw_dob_id starts "311:"]

Mirrors _build_dob_link's new complaint branch. On the stored doc the 311
discriminator is the "311:" raw_dob_id prefix (equivalent to the builder's
`unique_key` guard on the raw record). Makes NO writes.

Reads MONGO_URL / DB_NAME from env; never prints the connection string.

    $env:MONGO_URL = '<production Atlas URI>'; $env:DB_NAME = 'blueview'
    python preview_complaint_links.py
"""
import os
import asyncio
import urllib.parse

OVERVIEW = "https://a810-bisweb.nyc.gov/bisweb/OverviewForComplaintServlet?complaintno="
BINLIST = "https://a810-bisweb.nyc.gov/bisweb/ComplaintsByAddressServlet?requestid=1&allbin="


def _new_link(doc):
    """Replicate the new _build_dob_link complaint branch, from a stored doc."""
    raw_id = str(doc.get("raw_dob_id") or "")
    if raw_id.startswith("311:"):
        return ""  # 311 SR — no public per-SR URL
    cn = str(doc.get("complaint_number") or "").strip()
    if cn:
        return OVERVIEW + urllib.parse.quote_plus(cn)
    binv = str(doc.get("nyc_bin") or "").strip()
    if binv:
        return BINLIST + urllib.parse.quote_plus(binv)
    return ""


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    url, dbname = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME in the environment first.")
    db = AsyncIOMotorClient(url)[dbname]

    q = {"record_type": "complaint"}
    total = await db.dob_logs.count_documents(q)
    print(f"complaint rows: {total}\n" + "=" * 78)

    n_dob, n_311, n_binfallback, n_none = 0, 0, 0, 0
    async for doc in db.dob_logs.find(q).sort("detected_at", -1):
        raw_id = str(doc.get("raw_dob_id") or "")
        src = "311 " if raw_id.startswith("311:") else "DOB "
        new = _new_link(doc)
        if src == "311 ":
            n_311 += 1
        elif "OverviewForComplaint" in new:
            n_dob += 1
        elif "ComplaintsByAddress" in new:
            n_binfallback += 1
        else:
            n_none += 1
        print(f"\n[{src}] complaint_number={doc.get('complaint_number')} "
              f"unit={doc.get('complaint_unit')} bin={doc.get('nyc_bin')} "
              f"raw_dob_id={raw_id}")
        print(f"     current: {doc.get('dob_link')}")
        print(f"     NEW    : {new or '(no button)'}")

    print("\n" + "=" * 78)
    print(f"DOB per-complaint (OverviewForComplaintServlet): {n_dob}")
    print(f"DOB BIN-list fallback (no complaint_number)   : {n_binfallback}")
    print(f"311 -> no button                              : {n_311}")
    print(f"other -> no button                            : {n_none}")
    print("Expect: eabe-havv complaints get OverviewForComplaintServlet?complaintno=,")
    print("        311 complaints get (no button).")
    AsyncIOMotorClient(url).close()


if __name__ == "__main__":
    asyncio.run(main())
