"""One-shot backfill — populate v2 enrichment keys on stale
permit_renewals docs.

Why this exists
───────────────
Pre-cutover (and pre-6.2.3 writer extension `4f028d4`) `permit_renewals`
docs were written with the legacy schema — no `renewal_strategy`,
`effective_expiry`, `limiting_factor`, or `action` keys. The
dispatcher cutover to mode='live' (2026-04-29) changed the live
`/api/permit-renewals/check-eligibility` response to include these
fields, but `nightly_renewal_scan`'s idempotency guard at
`permit_renewal.py:1061-1069` skips any permit with an active
renewal record — which means stale docs cannot self-heal through
normal operation. Verified during the writer-trace investigation
2026-04-29 ("There is no code path that bulk-updates v2 keys onto
existing rows without per-permit admin action").

Net production consequence: the renewal-detail page reads stale
persisted data, the `actionRenderers` map dispatch (MR.1.5) never
matches because `renewal.action?.kind` is undefined for these rows,
and operators see fall-through default content instead of the MR.1
panel. This script closes that gap.

What it does (and what it deliberately does NOT do)
───────────────────────────────────────────────────
For every permit_renewals doc missing `renewal_strategy`:

  1. Resolves the referenced dob_log + project + company.
  2. Calls the dispatcher (`check_renewal_eligibility`) with the
     same arg shape `nightly_renewal_scan` uses.
  3. `$set` ONLY the four v2 keys + `updated_at`. Does NOT touch
     `status`, `blocking_reasons`, `insurance_flags`,
     `days_until_expiry`, or any other field. Status semantics on
     stale docs were correct relative to the legacy dispatcher;
     overwriting them here would be a separate, larger change.

The dispatcher mode must be 'live' for the backfill to be
meaningful — in mode='off' or 'shadow' the dispatcher returns the
legacy result with v2 fields = None, and the backfill would just
write None values. The script aborts if mode is not 'live'.

Run modes
─────────
    # Dry-run — report what WOULD change. No writes. Required.
    python scripts/backfill_renewal_v2_keys.py --dry-run

    # Live — perform the $set updates. Required.
    python scripts/backfill_renewal_v2_keys.py --execute

The two modes are mutually exclusive and one is required (no
implicit-live; explicit-only to prevent accidental runs).

Output
──────
- stdout: per-doc summary (action category) + final tally
  (scanned/updated/skipped with reason counts).
- backend/logs/backfill_renewal_v2_keys_<UTC-timestamp>.jsonl: one
  JSON line per processed doc with `_id`, `permit_dob_log_id`,
  before-state of the four keys, and after-state. Generated in
  both dry-run and execute modes — dry-run produces a "preview"
  log, execute produces the source-of-truth log of what was
  actually written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# Path conventions: imports below this line rely on sys.path.insert
# above. Keep them ordered after that line per the post-step-4 CI lint.
from lib.eligibility_dispatcher import get_mode  # noqa: E402
from permit_renewal import (  # noqa: E402
    RenewalStatus,
    _to_oid,
    check_renewal_eligibility,
)


SkipReason = str  # alias for the reason-string keys in the tally.


async def _resolve_refs(
    db, doc: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]],
          Optional[Dict[str, Any]], Optional[SkipReason]]:
    """Load the dob_log + project + company referenced by a renewal
    doc. Returns (permit, project, company, skip_reason). On missing
    references, populates skip_reason and the failed dependency is
    None."""
    permit_dob_log_id = doc.get("permit_dob_log_id")
    if not permit_dob_log_id:
        return None, None, None, "no_permit_dob_log_id_field"

    permit = await db.dob_logs.find_one({"_id": _to_oid(permit_dob_log_id)})
    if not permit:
        return None, None, None, "missing_permit_dob_log"

    project_id = doc.get("project_id")
    if not project_id:
        return permit, None, None, "no_project_id_field"
    project = await db.projects.find_one({"_id": _to_oid(project_id)})
    if not project:
        return permit, None, None, "missing_project"

    company_id = doc.get("company_id")
    if not company_id:
        return permit, project, None, "no_company_id_field"
    company = await db.companies.find_one({
        "_id": _to_oid(company_id),
        "is_deleted": {"$ne": True},
    })
    if not company:
        return permit, project, None, "missing_company"

    company_name = (company.get("name") or "").strip()
    if not company_name:
        return permit, project, company, "empty_company_name"

    return permit, project, company, None


def _short_id(oid) -> str:
    """Last 6 chars of an ObjectId string for compact stdout lines."""
    s = str(oid)
    return s[-6:] if len(s) > 6 else s


async def main(*, dry_run: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print(
            "ERROR: MONGO_URL and DB_NAME env vars required",
            file=sys.stderr,
        )
        return 2

    # Mode gate — if the dispatcher is in 'off' or 'shadow', the backfill
    # writes None values and is meaningless. Abort early.
    mode = get_mode()
    if mode != "live":
        print(
            f"ERROR: ELIGIBILITY_REWRITE_MODE={mode!r}, expected 'live'. "
            f"Backfill would write None values for all four v2 keys. "
            f"Aborting.",
            file=sys.stderr,
        )
        return 3

    mode_label = "DRY-RUN" if dry_run else "LIVE"
    print(f"=== Backfill v2 keys on stale permit_renewals — {mode_label} ===\n")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Target query: docs missing the renewal_strategy key entirely OR
    # carrying it with a None value. Both cases mean v2 enrichment was
    # never written (either pre-6.2.3 schema or post-6.2.3 written
    # under shadow/off mode before the cutover). Soft-deleted records
    # are excluded — same convention as nightly_renewal_scan and the
    # other permit_renewals queries.
    #
    # Terminal-status docs (RenewalStatus.COMPLETED / FAILED — values
    # "completed" / "failed" in lowercase per the enum at
    # permit_renewal.py:92-100) are also excluded. Backfilling them
    # would write today's dispatcher strategy onto a historical
    # record, which is semantically wrong for the audit trail — the
    # strategy at completion/failure time is the relevant one for
    # those rows, not "what it would be today." The renewal-detail
    # page surfaces dedicated badges for these statuses
    # ("Permit renewed successfully" / "Manual renewal required on
    # DOB NOW") rather than the actionRenderers panel, so they
    # don't need v2 keys to render correctly.
    query = {
        "is_deleted": {"$ne": True},
        "status": {"$nin": [
            RenewalStatus.COMPLETED,
            RenewalStatus.FAILED,
        ]},
        "$or": [
            {"renewal_strategy": {"$exists": False}},
            {"renewal_strategy": None},
        ],
    }
    docs = await db.permit_renewals.find(query).to_list(length=None)
    total = len(docs)
    print(f"Stale docs found (missing renewal_strategy): {total}\n")
    if total == 0:
        print("Nothing to backfill.")
        return 0

    # Open the JSONL log file. Created in both modes; dry-run gets a
    # "preview" log, execute gets the source-of-truth log of writes.
    logs_dir = _BACKEND / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = logs_dir / f"backfill_renewal_v2_keys_{ts}.jsonl"
    print(f"Per-doc JSONL log: {log_path}\n")

    tally = {
        "scanned": total,
        "updated": 0,
        "dry_run_logged": 0,
        "skipped": 0,
        "skip_reasons": {},
    }
    now = datetime.now(timezone.utc)

    with log_path.open("w", encoding="utf-8") as log_fp:
        for doc in docs:
            pid = doc["_id"]
            short = _short_id(pid)
            name = doc.get("project_name") or doc.get("job_number") or short

            permit, project, company, skip_reason = await _resolve_refs(db, doc)
            if skip_reason:
                tally["skipped"] += 1
                tally["skip_reasons"][skip_reason] = (
                    tally["skip_reasons"].get(skip_reason, 0) + 1
                )
                print(f"  {short:>6}  SKIP   {name[:50]:50s}  ({skip_reason})")
                continue

            company_name = (company.get("name") or "").strip()
            try:
                eligibility = await check_renewal_eligibility(
                    db,
                    str(doc.get("permit_dob_log_id")),
                    str(doc.get("project_id")),
                    company_name,
                    company_id=str(doc.get("company_id")),
                )
            except Exception as e:
                reason = f"dispatcher_error: {type(e).__name__}"
                tally["skipped"] += 1
                tally["skip_reasons"][reason] = (
                    tally["skip_reasons"].get(reason, 0) + 1
                )
                print(f"  {short:>6}  SKIP   {name[:50]:50s}  ({reason}: {e})")
                continue

            before = {
                "renewal_strategy": doc.get("renewal_strategy"),
                "effective_expiry": doc.get("effective_expiry"),
                "limiting_factor": doc.get("limiting_factor"),
                "action": doc.get("action"),
            }
            after = {
                "renewal_strategy": eligibility.renewal_strategy,
                "effective_expiry": eligibility.effective_expiry,
                "limiting_factor": eligibility.limiting_factor,
                "action": eligibility.action,
            }

            entry = {
                "_id": str(pid),
                "permit_dob_log_id": str(doc.get("permit_dob_log_id")),
                "before": before,
                "after": after,
            }
            log_fp.write(json.dumps(entry, default=str) + "\n")

            strategy_label = after["renewal_strategy"] or "(none)"
            action_kind = (after.get("action") or {}).get("kind") or "(none)"

            if dry_run:
                tally["dry_run_logged"] += 1
                print(
                    f"  {short:>6}  PLAN   {name[:50]:50s}  "
                    f"strategy={strategy_label} action.kind={action_kind}"
                )
            else:
                # Live $set — only the four v2 keys + updated_at. Other
                # fields (status, blocking_reasons, etc.) are deliberately
                # untouched per the script's contract.
                update_set = {
                    "renewal_strategy": after["renewal_strategy"],
                    "effective_expiry": after["effective_expiry"],
                    "limiting_factor": after["limiting_factor"],
                    "action": after["action"],
                    "updated_at": now,
                }
                await db.permit_renewals.update_one(
                    {"_id": pid},
                    {"$set": update_set},
                )
                tally["updated"] += 1
                print(
                    f"  {short:>6}  WRITE  {name[:50]:50s}  "
                    f"strategy={strategy_label} action.kind={action_kind}"
                )

    # ── Summary ──────────────────────────────────────────────────
    print()
    print("Summary:")
    print(f"  scanned        : {tally['scanned']}")
    if dry_run:
        print(f"  would update   : {tally['dry_run_logged']}")
    else:
        print(f"  updated        : {tally['updated']}")
    print(f"  skipped        : {tally['skipped']}")
    if tally["skip_reasons"]:
        print(f"  skip reasons   :")
        for reason, count in sorted(
            tally["skip_reasons"].items(), key=lambda kv: -kv[1]
        ):
            print(f"    {count:>4}  {reason}")
    print(f"  log file       : {log_path}")
    print()

    if dry_run:
        print("DRY-RUN: no writes performed. Re-run with --execute to apply.")
    else:
        print("Done.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Backfill v2 enrichment keys (renewal_strategy, "
            "effective_expiry, limiting_factor, action) onto stale "
            "permit_renewals docs by re-running the dispatcher and "
            "$setting only those four keys + updated_at."
        ),
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what WOULD change for each doc, no writes.",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="Perform the $set updates against permit_renewals.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
