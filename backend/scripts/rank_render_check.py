"""READ-ONLY render check for the proposed DOB severity ranking.

Applies the proposed severity-rank to a project's ACTUAL dob_logs rows and
prints the sorted order. Writes NOTHING — find() + print only. The point is to
confirm, on REAL data (not a synthetic fixture), that the real Stop-Work record
sorts to the TOP and is not misclassified as resolved by its own description
text.

It reads each row's STORED classifier outputs (resolution_state,
violation_subtype, notice_type, description, current_status) — the same fields
the ingest already computed — so the ranking it prints is exactly what the app
would render once the display fix lands.

  USAGE (BIN 3048298 = 8 Walworth):
    MONGO_URL='...' DB_NAME='blueview' python scripts/rank_render_check.py --bin 3048298
    # or address a project directly:
    MONGO_URL='...' DB_NAME='blueview' python scripts/rank_render_check.py --project-id <pid>
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

CLOSED_STATES = {"certified", "dismissed", "paid", "resolved"}
STOP_WORK_SUBTYPES = {"SWO_FULL", "SWO_PARTIAL"}
ORDER_SUBTYPES = {"VACATE_FULL", "VACATE_PARTIAL", "COMM_ORDER"}
# Proposed fix: broaden stop-work detection to DOB's REAL phrasing. The current
# classifier only matches "FULL STOP WORK", so 8 Walworth's code-C order
# ("…ORDERED ALL WORK STOPPED…") is missed and ranks as a mere COMM_ORDER.
STOP_WORK_TEXT = ("stop work", "work stopped", "work shall not resume", "work shall stop", "cease all work")


def _is_stop_work(log: dict) -> bool:
    """PROMOTION signal only — reads text to RAISE severity, never to lower it.
    (Demotion to resolved is decided separately, from the status field.)"""
    if str(log.get("record_type") or "").lower() == "swo":
        return True
    if str(log.get("violation_subtype") or "").upper() in STOP_WORK_SUBTYPES:
        return True
    blob = f"{log.get('violation_type') or ''} {log.get('description') or ''}".lower()
    return any(t in blob for t in STOP_WORK_TEXT)


def _rank(log: dict):
    """Return (tier, label). Tier 0 sorts to the TOP. Resolved is ALWAYS last,
    regardless of type — and resolution is read from the STORED resolution_state
    (a status-field derivation), NEVER from description text."""
    rt = str(log.get("record_type") or "").lower()
    res = str(log.get("resolution_state") or "").lower()
    sub = str(log.get("violation_subtype") or "").upper()
    notice = str(log.get("notice_type") or "").lower()

    # Resolved / dismissed / closed → demoted to the very bottom, any type.
    # Checked FIRST and off the STATUS-derived resolution_state, so a rescinded
    # SWO drops here but wording like "until resolved" in an OPEN SWO cannot.
    if res in CLOSED_STATES:
        return (4, f"RESOLVED/CLOSED ({res})")

    # Tier 0 — Stop Work: swo record type, a stop-work subtype, OR DOB's real
    # "…WORK STOPPED…" phrasing. Floats the real SWO to the top even when it
    # lives in the violations dataset as a code-C order.
    if _is_stop_work(log):
        return (0, "STOP WORK")
    # Tier 2 — orders/notices (Commissioner's, vacate, padlock, deficiency).
    if sub in ORDER_SUBTYPES or notice:
        return (2, "ORDER / NOTICE")
    # Tier 1 — open violations (incl. ECB, boiler/elevator flagged as violations).
    if rt in ("violation", "boiler", "elevator") or sub == "ECB":
        return (1, "OPEN VIOLATION")
    # Tier 3 — open complaints.
    if rt == "complaint":
        return (3, "OPEN COMPLAINT")
    return (3, f"OTHER ({rt})")


def _date(log: dict) -> str:
    return str(
        log.get("violation_date") or log.get("complaint_date")
        or log.get("detected_at") or ""
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only DOB ranking render check.")
    ap.add_argument("--bin", dest="nyc_bin", default=None)
    ap.add_argument("--project-id", dest="project_id", default=None)
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2
    if not args.nyc_bin and not args.project_id:
        print("ERROR: pass --bin <bin> or --project-id <pid>", file=sys.stderr)
        return 2

    db = AsyncIOMotorClient(mongo_url)[db_name]

    project_id = args.project_id
    if not project_id:
        proj = await db.projects.find_one(
            {"nyc_bin": args.nyc_bin, "is_deleted": {"$ne": True}}, {"_id": 1, "name": 1}
        )
        if not proj:
            print(f"No project found with nyc_bin={args.nyc_bin!r}")
            return 1
        project_id = str(proj["_id"])
        print(f"Project: {proj.get('name')}  (_id={project_id}, bin={args.nyc_bin})\n")

    cursor = db.dob_logs.find({
        "project_id": project_id,
        "is_deleted": {"$ne": True},
        "is_seed_transition": {"$ne": True},
    })
    rows = await cursor.to_list(2000)

    # Dedup by raw_dob_id — newest state wins (matches the summary endpoint).
    def _sort_key(r):
        return (str(r.get("raw_dob_id")), r.get("status_changed_at") or r.get("detected_at") or datetime.min.replace(tzinfo=timezone.utc))
    latest = {}
    for r in sorted(rows, key=_sort_key):
        latest[str(r.get("raw_dob_id"))] = r
    deduped = list(latest.values())

    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)

    ranked = sorted(deduped, key=lambda l: (_rank(l)[0], _neg_date(l)))

    print(f"=== {len(deduped)} DOB records for project (deduped by raw_dob_id) ===")
    print("(rank 0 = top. 'HIDDEN@30d' = dropped by the CURRENT default window; the fix removes it.)\n")
    for l in ranked:
        tier, label = _rank(l)
        det = l.get("detected_at")
        hidden = "HIDDEN@30d" if (isinstance(det, datetime) and det < cutoff_30d) else "shown"
        print(f"[T{tier} {label:<20}] {str(l.get('record_type')):<10} "
              f"res={str(l.get('resolution_state')):<14} "
              f"cur_status={str(l.get('current_status'))!r:<14} "
              f"vtype={str(l.get('violation_type'))!r:<16} "
              f"date={_date(l)[:10]:<10} {hidden}")
        desc = l.get("description")
        print(f"        desc: {str(desc)[:160] if desc else '(none — dropped at ingest)'}")
        # Prove item 2 on real data: does the description contain a resolved-ish
        # word while resolution_state is NOT closed? If so, ranking ignored it.
        dl = str(desc or "").lower()
        if any(w in dl for w in ("resolved", "no work", "closed")) and str(l.get("resolution_state") or "").lower() not in CLOSED_STATES:
            print("        NOTE: description contains 'resolved/closed/no work' but "
                  "resolution_state is NOT closed → wording did NOT demote it. [item 2 OK]")
    print()
    top = ranked[0] if ranked else None
    if top:
        print(f"TOP RECORD → tier {_rank(top)[0]} ({_rank(top)[1]}), "
              f"record_type={top.get('record_type')}, resolution_state={top.get('resolution_state')}")
    return 0


def _neg_date(log: dict):
    d = log.get("violation_date") or log.get("complaint_date") or log.get("detected_at")
    if isinstance(d, datetime):
        return -d.timestamp()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
