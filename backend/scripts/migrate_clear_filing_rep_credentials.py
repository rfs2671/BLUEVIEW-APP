"""MR.14 commit 4b — backfill: $unset companies.filing_reps[].credentials.

Why this exists
───────────────
MR.14 commit 4b removes the `credentials` field from the FilingRep
Pydantic model + every code path that read or wrote it. Production
companies docs that already had ciphertext stored in
`filing_reps[i].credentials` carry that ciphertext as orphan data.

This script strips the field off every existing rep so:
  • The credentials cleartext can never accidentally come back through
    a future code path that reads `rep.credentials` (the field is gone
    from the schema; Pydantic now rejects unknown extras only via
    explicit config, but the safer bet is "remove from disk").
  • Operators can verify removal with a single Mongo query post-deploy.
  • The dead ciphertext (RSA-wrapped + AES-GCM-encrypted) is not
    decryptable without the worker's private key, but it's better
    practice to delete encrypted secrets at rest once they have no
    use, in case the operator's key material ever leaks.

Idempotent — re-runs are safe. Re-running after a successful execute
finds zero candidates and exits clean.

Run modes
─────────
    # Dry-run — count what WOULD change. No writes. Required.
    python -m backend.scripts.migrate_clear_filing_rep_credentials --dry-run

    # Live — perform the $unset. Required.
    python -m backend.scripts.migrate_clear_filing_rep_credentials --execute

The two modes are mutually exclusive and one is required. Same env-var
contract as the other migration scripts: MONGO_URL + DB_NAME required.

Output reports:
  • number of company docs touched
  • number of filing_rep entries cleared
  • approximate bytes of ciphertext freed (sum of len(b64 string) over
    all stripped credential entries)

Verification after `--execute`
───────────────────────────────
Run the same query the script uses for its candidate scan:

    db.companies.find({"filing_reps.credentials": {$exists: true}}).count()

Should return 0.

Operator can also drop the now-orphaned `agent_public_keys` collection:

    db.agent_public_keys.drop()
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


def _credentials_byte_size(creds: list) -> int:
    """Sum of len(encrypted_ciphertext) across credential entries on
    one filing_rep. Approximation — base64 chars not bytes — but
    accurate enough for an operator-facing 'how much we freed' report."""
    total = 0
    for c in creds or []:
        ct = c.get("encrypted_ciphertext") or ""
        total += len(ct)
    return total


async def main(*, dry_run: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print(
            "ERROR: MONGO_URL and DB_NAME env vars required",
            file=sys.stderr,
        )
        return 2

    mode_label = "DRY-RUN" if dry_run else "LIVE"
    print(
        f"=== Clear filing_reps[].credentials -- {mode_label} ===\n"
    )

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Target: company docs with at least one filing_rep that still
    # has the credentials field. We use a top-level dotted-path
    # $exists check — Mongo's positional semantics make this match
    # if ANY rep has the field, which is what we want.
    target_query = {
        "is_deleted": {"$ne": True},
        "filing_reps.credentials": {"$exists": True},
    }

    candidates = await db.companies.count_documents(target_query)
    overall = await db.companies.count_documents({"is_deleted": {"$ne": True}})
    print(
        f"Companies with at least one rep carrying credentials: "
        f"{candidates} (out of {overall} non-deleted)\n"
    )

    if candidates == 0:
        print("Nothing to migrate — no rep has the credentials field.")
        return 0

    # Per-doc breakdown so the operator can audit which company gets
    # touched + the rough size of ciphertext that will be deleted.
    sample_cursor = db.companies.find(
        target_query, {"_id": 1, "name": 1, "filing_reps": 1},
    ).limit(20)

    print("Sample (first 20 affected companies + rep credential counts):")
    total_creds_to_clear = 0
    total_bytes_to_free = 0
    async for c in sample_cursor:
        cid_short = str(c["_id"])[-6:]
        cname = c.get("name") or "(unnamed)"
        reps = c.get("filing_reps") or []
        with_creds = [
            r for r in reps if r.get("credentials")
        ]
        creds_count = sum(len(r.get("credentials") or []) for r in with_creds)
        bytes_count = sum(
            _credentials_byte_size(r.get("credentials") or [])
            for r in with_creds
        )
        total_creds_to_clear += creds_count
        total_bytes_to_free += bytes_count
        print(
            f"  {cid_short:>6}  {cname[:50]:<50} "
            f"reps={len(reps)} reps_with_creds={len(with_creds)} "
            f"cred_entries={creds_count} bytes={bytes_count}"
        )
    if candidates > 20:
        print(f"  ... and {candidates - 20} more companies")
    print()

    if dry_run:
        print(
            f"DRY-RUN: would touch {candidates} company doc(s). "
            f"Sample shows >= {total_creds_to_clear} credential entries "
            f"and >= {total_bytes_to_free} bytes of ciphertext to free. "
            f"Re-run with --execute to apply."
        )
        return 0

    # Live update. $unset on the dotted path
    # `filing_reps.$[].credentials` clears the field on every entry of
    # the array in one shot. Standard Mongo `update_many` works because
    # `$[]` is an all-positional operator (no array_filters needed).
    # Idempotent — re-runs match nothing because the predicate scopes
    # to docs where the field still exists.
    total_companies_modified = 0
    total_creds_cleared = 0
    total_bytes_freed = 0

    cursor = db.companies.find(target_query, {"_id": 1, "filing_reps": 1})
    async for c in cursor:
        company_id = c["_id"]
        reps = c.get("filing_reps") or []
        # Tally what's about to be cleared on this doc, before we
        # blow it away.
        cleared_on_doc = sum(len(r.get("credentials") or []) for r in reps)
        bytes_on_doc = sum(
            _credentials_byte_size(r.get("credentials") or []) for r in reps
        )

        result = await db.companies.update_one(
            {"_id": company_id},
            {"$unset": {"filing_reps.$[].credentials": ""}},
        )
        if result.modified_count > 0:
            total_companies_modified += 1
            total_creds_cleared += cleared_on_doc
            total_bytes_freed += bytes_on_doc

    print(
        f"Updated: companies_touched={total_companies_modified} "
        f"credentials_entries_cleared={total_creds_cleared} "
        f"bytes_of_ciphertext_freed={total_bytes_freed}"
    )
    print()
    print(
        "Done. Operator follow-up: drop agent_public_keys collection:\n"
        "    db.agent_public_keys.drop()"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Strip the dead `credentials` field off every filing_rep "
            "(MR.14 commit 4b backfill)."
        ),
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what WOULD change. No writes.",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="Perform the $unset.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
