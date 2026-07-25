"""READ-ONLY verification of the GET /api/projects/dob-summary pipeline.

Mirrors the endpoint's aggregation exactly (dedup by raw_dob_id; NO detected_at
filter — it is only the dedup tiebreaker; open derived from status fields, never
an event-date window) and runs it directly against Mongo for the two live
projects, so no app auth is needed. Adds a permit parse-drop diagnostic the
endpoint does not surface, to confirm the mixed-format expiration_date
(ISO-with-time / MDY / null) is handled by $dateFromString without erroring.

SAFETY: aggregate() + distinct() only. No writes. Reads MONGO_URL / DB_NAME
from the environment and NEVER prints the connection string.

Usage (PowerShell):
    $env:MONGO_URL = '<production Atlas URI>'
    $env:DB_NAME   = 'blueview'
    python backend/scripts/verify_dob_summary.py

Exit 0 always (diagnostic); prints a STOP banner if Boyland open_violations==0,
which would mean the event-date-vs-status-field issue is still present.
"""

import os
import asyncio
from datetime import datetime, timezone, timedelta

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:  # pragma: no cover
    raise SystemExit("motor is required: pip install motor")

PIDS = {
    "6a5f63a8147407d3261df2c5": "8 Walworth",
    "6a5f63bc147407d3261df2c7": "588 Boyland",
}
MODEL_VERSION = "statistical-v1"


async def main():
    url = os.environ.get("MONGO_URL")
    dbname = os.environ.get("DB_NAME")
    if not url or not dbname:
        raise SystemExit("Set MONGO_URL and DB_NAME first.")

    db = AsyncIOMotorClient(url)[dbname]
    ids = list(PIDS)
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    t30 = today + timedelta(days=30)
    dedup = {"raw_dob_id": 1, "status_changed_at": -1, "detected_at": -1}
    base = {
        "is_deleted": {"$ne": True},
        "is_seed_transition": {"$ne": True},
        "project_id": {"$in": ids},
        "record_type": {"$in": ["violation", "swo", "complaint", "permit"]},
    }

    pipeline = [{"$match": base}, {"$facet": {
        "open_violations": [
            {"$match": {"record_type": {"$in": ["violation", "swo"]}}},
            {"$sort": dedup},
            {"$group": {"_id": "$raw_dob_id", "project_id": {"$first": "$project_id"},
                        "resolution_state": {"$first": "$resolution_state"}}},
            {"$match": {"resolution_state": {"$nin": ["certified", "dismissed", "paid", "resolved"]}}},
            {"$group": {"_id": "$project_id", "n": {"$sum": 1}}}],
        "open_complaints": [
            {"$match": {"record_type": "complaint"}},
            {"$sort": dedup},
            {"$group": {"_id": "$raw_dob_id", "project_id": {"$first": "$project_id"},
                        "closed_date": {"$first": "$closed_date"},
                        "complaint_status": {"$first": "$complaint_status"}}},
            {"$match": {"$and": [
                {"$or": [{"closed_date": None}, {"closed_date": {"$exists": False}}, {"closed_date": ""}]},
                {"$or": [{"complaint_status": None},
                         {"complaint_status": {"$not": {"$regex": "closed", "$options": "i"}}}]}]}},
            {"$group": {"_id": "$project_id", "n": {"$sum": 1}}}],
        "permits_expiring": [
            {"$match": {"record_type": "permit"}},
            {"$sort": dedup},
            {"$group": {"_id": "$raw_dob_id", "project_id": {"$first": "$project_id"},
                        "expiration_date": {"$first": "$expiration_date"}}},
            {"$addFields": {"_exp": {"$dateFromString": {"dateString": "$expiration_date",
                                                         "onError": None, "onNull": None}}}},
            {"$match": {"_exp": {"$gte": today, "$lte": t30}}},
            {"$group": {"_id": "$project_id", "n": {"$sum": 1}}}],
        # DIAGNOSTIC (not in the endpoint): permit parse drop-out per project.
        "permit_parse_diag": [
            {"$match": {"record_type": "permit"}},
            {"$sort": dedup},
            {"$group": {"_id": "$raw_dob_id", "project_id": {"$first": "$project_id"},
                        "expiration_date": {"$first": "$expiration_date"}}},
            {"$addFields": {"_exp": {"$dateFromString": {"dateString": "$expiration_date",
                                                         "onError": None, "onNull": None}}}},
            {"$group": {"_id": "$project_id",
                        "total": {"$sum": 1},
                        "parsed": {"$sum": {"$cond": [{"$ne": ["$_exp", None]}, 1, 0]}}}}],
    }}]

    agg = (await db.dob_logs.aggregate(pipeline).to_list(1))[0]
    by = lambda k: {r["_id"]: r["n"] for r in agg.get(k, []) if r.get("_id")}
    ov, oc, pe = by("open_violations"), by("open_complaints"), by("permits_expiring")
    diag = {r["_id"]: r for r in agg.get("permit_parse_diag", [])}
    scored = set(await db.risk_scores.distinct(
        "project_id", {"model_version": MODEL_VERSION, "project_id": {"$in": ids}}))

    for pid, name in PIDS.items():
        d = diag.get(pid, {})
        total, parsed = d.get("total", 0), d.get("parsed", 0)
        print(f"\n=== {name} ({pid}) ===")
        print(f"  open_violations : {ov.get(pid, 0)}")
        print(f"  open_complaints : {oc.get(pid, 0)}")
        print(f"  permits_expiring: {pe.get(pid, 0)}")
        print(f"  has_risk_score  : {pid in scored}")
        print(f"  [permit parse]  total_deduped={total}  parsed={parsed}  "
              f"dropped(MDY/null)={total - parsed}")

    tot = {
        "open_violations": sum(ov.values()),
        "open_complaints": sum(oc.values()),
        "permits_expiring": sum(pe.values()),
        "projects_without_score": sum(1 for p in ids if p not in scored),
        "projects_total": len(ids),
    }
    print("\n=== TOTALS ===", tot)

    if ov.get("6a5f63bc147407d3261df2c7", 0) == 0:
        print("\n!! STOP: Boyland open_violations == 0 — the event-date vs "
              "status-field issue is still present; do not proceed.")


if __name__ == "__main__":
    asyncio.run(main())
