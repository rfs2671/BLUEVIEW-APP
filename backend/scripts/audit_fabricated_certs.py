"""Repair the certification rows the check-in writer produced while it was buggy.

Three defects, confirmed 100% on the live workers (see the cert-capture audit):
  1. A fabricated OSHA row was created from the SST card, stamped with the SST
     card's number (osha_number). No OSHA card was scanned.
  2. Every SST row's class was hardcoded SST_LIMITED — the real class was never
     read, so a SUPERVISOR card is stored as LIMITED. No existing row's class
     can be trusted.
  3. Fishman's SST expiry is 2022-03-11 from a card expiring 2029 — an OCR
     misread stored with no sanity gate.

This script REPORTS by default and writes NOTHING. With --apply it makes three
row-level edits only. It NEVER deletes a worker or a whole certifications array;
it rewrites the array in place with the offending rows removed/flagged.

  NOTE (2026-07-29): Roey Fishman Shelly was hard-deleted by hand in mongosh
  (full cascade), so the expectations below dropped by one from what the
  original commit documented. Two workers remain (Jose David Hernandez Pena,
  Jhonatan Tipantuna). Historical counts before the deletion are shown in
  parentheses.

  --apply performs, per worker:
    (1) Drop every OSHA row whose card_number equals an SST row's card_number on
        the same worker (the fabricated-from-SST rows). Expect 2 (was 3).
    (2) Set needs_review=true, review_reason="CLASS_UNVERIFIED" on EVERY SST row
        (the class was hardcoded and cannot be trusted). Expect 2 (was 3).
    (3) For any SST row whose expiration_date is before its capture date (proxy:
        worker.created_at), clear expiration_date to None, set
        needs_review=true, review_reason="EXPIRY_IMPLAUSIBLE", and retain the
        old value in expiration_raw_rejected. Expect 0 (was 1) — Fishman's row
        was the only instance and that worker is deleted; any other matching row
        is still reported.

Requires MONGO_URL + DB_NAME, same contract as the other scripts here.

  DRY RUN:  MONGO_URL='...' DB_NAME='blueview' python scripts/audit_fabricated_certs.py
  APPLY:    MONGO_URL='...' DB_NAME='blueview' python scripts/audit_fabricated_certs.py --apply
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

RECOGNIZED_SST_PREFIX = "SST"
OSHA_PREFIX = "OSHA"


def _as_aware(dt):
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if isinstance(dt, datetime):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return None


def plan_for_worker(worker: dict):
    """Pure: return (new_certs, actions[]) for one worker. No I/O, no mutation
    of the input — so it is unit-testable and the dry run and apply share it."""
    certs = [dict(c) for c in (worker.get("certifications") or [])]
    actions = []
    capture_proxy = _as_aware(worker.get("created_at"))

    sst_numbers = {
        str(c.get("card_number"))
        for c in certs
        if str(c.get("type", "")).startswith(RECOGNIZED_SST_PREFIX) and c.get("card_number")
    }

    kept = []
    for c in certs:
        ctype = str(c.get("type", ""))
        # (1) fabricated OSHA row sharing an SST card number → drop the row
        if ctype.startswith(OSHA_PREFIX) and c.get("card_number") and str(c.get("card_number")) in sst_numbers:
            actions.append(("drop_fabricated_osha", ctype, c.get("card_number")))
            continue  # dropped (row-level; array is rewritten, never dropped whole)
        kept.append(c)

    for c in kept:
        ctype = str(c.get("type", ""))
        if not ctype.startswith(RECOGNIZED_SST_PREFIX):
            continue
        # (3) implausible stored expiry (before capture proxy) → clear + flag
        exp = _as_aware(c.get("expiration_date"))
        if exp is not None and capture_proxy is not None and exp < capture_proxy:
            c["expiration_raw_rejected"] = (
                c["expiration_date"].isoformat() if isinstance(c.get("expiration_date"), datetime)
                else str(c.get("expiration_date"))
            )
            c["expiration_date"] = None
            c["needs_review"] = True
            c["review_reason"] = "EXPIRY_IMPLAUSIBLE"
            actions.append(("clear_implausible_expiry", ctype, c["expiration_raw_rejected"]))
        else:
            # (2) class was hardcoded — cannot be trusted on ANY existing row
            c["needs_review"] = True
            if not c.get("review_reason"):
                c["review_reason"] = "CLASS_UNVERIFIED"
            actions.append(("flag_class_unverified", ctype, c.get("card_number")))

    return kept, actions


async def main() -> int:
    ap = argparse.ArgumentParser(description="Repair buggy certification rows (dry-run by default).")
    ap.add_argument("--apply", action="store_true", help="Write changes. Without this, reports only.")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    db = AsyncIOMotorClient(mongo_url)[db_name]
    mode = "APPLY" if args.apply else "DRY RUN (no writes)"
    print(f"=== audit_fabricated_certs — {mode} ===\n")

    totals = {"drop_fabricated_osha": 0, "flag_class_unverified": 0, "clear_implausible_expiry": 0}
    workers_touched = 0

    cursor = db.workers.find({"is_deleted": {"$ne": True}, "certifications": {"$exists": True, "$ne": []}})
    async for w in cursor:
        before = w.get("certifications") or []
        new_certs, actions = plan_for_worker(w)
        if not actions:
            continue
        workers_touched += 1
        for a, _t, _v in actions:
            totals[a] = totals.get(a, 0) + 1

        name = w.get("name") or "(no name)"
        print(f"WORKER {w.get('_id')}  {name}")
        print(f"  BEFORE: {[{'type': c.get('type'), 'card_number': c.get('card_number'), 'expiration_date': str(c.get('expiration_date'))} for c in before]}")
        for a, t, v in actions:
            print(f"    - {a}: type={t} value={v}")
        print(f"  AFTER : {[{'type': c.get('type'), 'card_number': c.get('card_number'), 'expiration_date': str(c.get('expiration_date')), 'needs_review': c.get('needs_review'), 'review_reason': c.get('review_reason')} for c in new_certs]}")

        if args.apply:
            await db.workers.update_one(
                {"_id": w["_id"]},
                {"$set": {"certifications": new_certs, "updated_at": datetime.now(timezone.utc)}},
            )
            print("  WROTE.")
        print()

    print("=== SUMMARY ===")
    print(f"  workers affected            : {workers_touched}")
    print(f"  (1) fabricated OSHA dropped  : {totals['drop_fabricated_osha']}   (expect 2; was 3 before Fishman deleted)")
    print(f"  (2) SST rows flagged class   : {totals['flag_class_unverified']}   (expect 2; was 3 before Fishman deleted)")
    print(f"  (3) implausible expiry cleared: {totals['clear_implausible_expiry']}   (expect 0; was 1 — Fishman deleted; any other reported)")
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to make these changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
