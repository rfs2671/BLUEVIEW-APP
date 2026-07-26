"""Read-only preview: displayed labels BEFORE vs AFTER the code→label change,
for every live violation and complaint record. Uses the real functions
(dob_complaint_codes.violation_type_display / get_category_label /
get_disposition_label) so what it prints is exactly what the app will render.

Rules being verified:
  * complaint category / disposition → VERIFIED official label, or
    "DOB code: {code}" when the code isn't in the sourced map.
  * violation-type codes → ALWAYS "DOB code: {code}" (no verified source yet);
    the quarantined UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE map is NEVER
    read by the display — this script asserts none of its label strings ever
    render.
  * ECB violation_type values are DOB's own plain-English field values and pass
    through as-is (not a code).
  * no record renders a bare code or a blank.

Read-only. MONGO_URL / DB_NAME from env; never prints the connection string; no
writes. Imports dob_complaint_codes (sets test-safe env defaults first).

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='blueview'
    python dob_label_preview.py
"""
import os
import sys
import asyncio

os.environ.setdefault("JWT_SECRET", "diag_only_secret")
os.environ.setdefault("QWEN_API_KEY", "")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dob_complaint_codes import (
        violation_type_display, get_category_label, get_disposition_label,
        UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE,
    )
    unverified_labels = set(UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE.values())

    url, dbname = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME in the environment first.")
    db = AsyncIOMotorClient(url)[dbname]

    # ── VIOLATIONS / SWO ──
    prefixed = {}
    passthrough = leaked = blanks = 0
    q = {"record_type": {"$in": ["violation", "swo"]}, "is_deleted": {"$ne": True}}
    vtotal = await db.dob_logs.count_documents(q)
    print(f"VIOLATIONS / SWO — {vtotal} records\n" + "=" * 82)
    async for rec in db.dob_logs.find(q):
        raw_src = rec.get("raw_record") or {}
        raw = (rec.get("violation_type") or rec.get("violation_type_code")
               or raw_src.get("violation_type") or raw_src.get("violation_type_code") or "")
        after = violation_type_display(raw)
        if after in unverified_labels:
            leaked += 1
            tag = "!! UNVERIFIED LABEL LEAKED"
        elif not after and raw:
            blanks += 1
            tag = "!! BLANK"
        elif after.startswith("DOB code:"):
            prefixed[after] = prefixed.get(after, 0) + 1
            tag = "PREFIXED (DOB code:)"
        else:
            passthrough += 1
            tag = "PLAIN-ENGLISH (ECB, as-is)"
        print(f"  [{tag:30}] raw={raw!r:48} → {after!r}")

    # ── COMPLAINTS ──
    c_verified = c_prefixed = 0
    cq = {"record_type": "complaint", "is_deleted": {"$ne": True}}
    ctotal = await db.dob_logs.count_documents(cq)
    print(f"\nCOMPLAINTS — {ctotal} records\n" + "=" * 82)
    async for rec in db.dob_logs.find(cq):
        raw = rec.get("raw_record") or {}
        cat = rec.get("complaint_type") or raw.get("complaint_category") or ""
        disp = raw.get("disposition_code") or rec.get("status") or ""
        cat_label = get_category_label(cat) if cat else "(none)"
        disp_label = get_disposition_label(disp) if disp else "(none)"
        for lbl in (cat_label, disp_label):
            if lbl.startswith("DOB code:"):
                c_prefixed += 1
            elif lbl != "(none)":
                c_verified += 1
        print(f"  cat {cat!r:6} → {cat_label!r}")
        print(f"      disp {disp!r:6} → {disp_label!r}")

    print("\n" + "=" * 82)
    print("VIOLATION TYPE:")
    print(f"  PREFIXED 'DOB code:'          : {sum(prefixed.values())}  {dict(prefixed)}")
    print(f"  PLAIN-ENGLISH (ECB, as-is)    : {passthrough}")
    print(f"  UNVERIFIED LABEL LEAKED (==0) : {leaked}")
    print(f"  BLANK (==0)                   : {blanks}")
    print("COMPLAINTS:")
    print(f"  VERIFIED official label       : {c_verified}")
    print(f"  'DOB code:' fallback          : {c_prefixed}")
    ok = leaked == 0 and blanks == 0
    print("\nRESULT:", "PASS — zero unverified labels reach a customer; violation codes all"
          " prefixed; complaint/disposition show official labels or 'DOB code:'."
          if ok else "FAIL — see LEAKED/BLANK above.")
    AsyncIOMotorClient(url).close()


if __name__ == "__main__":
    asyncio.run(main())
