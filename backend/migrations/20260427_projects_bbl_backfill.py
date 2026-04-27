"""Step 9.1: rename `projects.nyc_bbl` → `projects.bbl` + add provenance metadata.

Per `~/.claude/plans/§12-design.md` §2.1 (locked 2026-04-27).

The `nyc_` prefix on the field name was redundant — BBL is by
definition NYC. Spec §12 architecture refs uniformly use `bbl`;
keeping `nyc_bbl` as the field name produces naming inconsistency
across §12 callsites.

Also: a parallel rename of `nyc_bin` → `bin` and a function rename
of `fetch_nyc_bin_from_address` (which actually fetches BOTH
identifiers) are tracked but NOT in scope for step 9.1.

Behavior per project:
  1. Project has `nyc_bbl` populated AND no `bbl`
     → COPY value to `bbl`, stamp source="address_lookup_at_creation",
       last_synced=now. Leave `nyc_bbl` in place during the deploy
       window so old reads keep working. Cleanup commit drops
       `nyc_bbl` later.
  2. Project has `bbl` already AND no `bbl_source`
     → stamp metadata only.
  3. Project has neither AND project.address is parseable
     → query PLUTO 64uk-42ks, populate `bbl` + source="pluto_lookup".
       Multi-match disambiguation: prefer the row whose `bin` matches
       project.nyc_bin if known.
  4. Project has neither AND address unparseable
     → leave unset, log unmatched.
  5. Project has `bbl_source` already populated
     → skip (idempotent re-run).

Run:
    # dry-run — show distribution + per-project plan, no writes
    python migrations/20260427_projects_bbl_backfill.py --dry-run

    # live
    python migrations/20260427_projects_bbl_backfill.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


PLUTO_URL = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
INTER_REQUEST_DELAY_S = 0.1

_BORO_NAME_TO_PLUTO = {
    "manhattan": "MN",
    "bronx":     "BX", "the bronx": "BX",
    "brooklyn":  "BK",
    "queens":    "QN",
    "staten island": "SI",
}


def parse_address(addr: str) -> Optional[Dict[str, str]]:
    """Cheap-and-cheerful NYC address parser. Returns dict or None
    if the parse is too uncertain to PLUTO-query against. Pure;
    exposed for direct testing."""
    if not addr:
        return None
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if len(parts) < 2:
        return None

    street_part = parts[0]
    boro_part = parts[1].lower().strip()

    boro = None
    for name, code in _BORO_NAME_TO_PLUTO.items():
        if name in boro_part:
            boro = code
            break
    if not boro:
        return None

    m = re.match(r"^\s*(\d+[A-Za-z]?)\s+(.+)$", street_part)
    if not m:
        return None
    house_no = m.group(1).strip()
    street_name = m.group(2).strip().upper()

    zip_code = None
    if len(parts) >= 3:
        zm = re.search(r"\b(\d{5})\b", parts[-1])
        if zm:
            zip_code = zm.group(1)

    return {
        "house_no": house_no,
        "street_name": street_name,
        "boro": boro,
        "zip": zip_code,
    }


def disambiguate_pluto_rows(
    rows: List[Dict[str, Any]],
    *,
    nyc_bin_hint: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Pick best PLUTO match. Returns (chosen_row, reason).
    Pure; exposed for direct testing."""
    if not rows:
        return (None, "no_rows")
    if len(rows) == 1:
        return (rows[0], "single_match")
    if nyc_bin_hint:
        for r in rows:
            if str(r.get("bin") or "").strip() == str(nyc_bin_hint).strip():
                return (r, "bin_match_disambiguation")
    return (rows[0], "first_of_multi")


async def query_pluto(
    client: httpx.AsyncClient,
    parsed: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Run the PLUTO query for the parsed address. Returns the raw
    rows list (possibly empty). IO; exposed for direct testing with
    a mocked client."""
    house = parsed["house_no"].replace("'", "''")
    street = parsed["street_name"].replace("'", "''")
    boro = parsed["boro"]
    where = f"borough='{boro}' AND address='{house} {street}'"
    headers = {}
    token = os.environ.get("SOCRATA_APP_TOKEN", "").strip()
    if token:
        headers["X-App-Token"] = token

    resp = await client.get(
        PLUTO_URL,
        params={
            "$where": where,
            "$limit": "5",
            "$select": "bbl,address,borough,block,lot,bin",
        },
        headers=headers,
    )
    if resp.status_code != 200:
        return []
    return resp.json() or []


async def main(dry_run: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"=== Step 9.1 BBL rename + backfill — {mode} ===\n")

    # Only touch projects where bbl_source is missing/null (idempotent).
    query = {
        "is_deleted": {"$ne": True},
        "$or": [
            {"bbl_source": {"$exists": False}},
            {"bbl_source": None},
            {"bbl_source": ""},
        ],
    }
    projects = await db.projects.find(
        query,
        {"_id": 1, "name": 1, "address": 1, "nyc_bin": 1, "bbl": 1, "nyc_bbl": 1},
    ).to_list(length=None)

    total = len(projects)
    print(f"Projects needing BBL provenance: {total}\n")
    if total == 0:
        print("Nothing to do.")
        return 0

    plans: List[Tuple[str, Dict[str, Any]]] = []
    counts = {
        "rename_legacy_bbl":   0,  # nyc_bbl exists, copy to bbl
        "stamp_existing_bbl":  0,  # bbl already exists, stamp metadata
        "pluto_match":         0,
        "pluto_multi":         0,
        "pluto_no_match":      0,
        "address_unparseable": 0,
    }
    multi_examples: List[Dict[str, Any]] = []

    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=15.0) as http:
        for p in projects:
            pid = str(p["_id"])
            name = p.get("name") or pid
            existing_bbl = (p.get("bbl") or "").strip()
            legacy_nyc_bbl = (p.get("nyc_bbl") or "").strip()

            if existing_bbl:
                plans.append((pid, {
                    "category": "stamp_existing_bbl",
                    "name": name,
                    "set": {
                        "bbl_source": "address_lookup_at_creation",
                        "bbl_last_synced": now,
                    },
                }))
                counts["stamp_existing_bbl"] += 1
                continue

            if legacy_nyc_bbl:
                plans.append((pid, {
                    "category": "rename_legacy_bbl",
                    "name": name,
                    "set": {
                        "bbl": legacy_nyc_bbl,
                        "bbl_source": "address_lookup_at_creation",
                        "bbl_last_synced": now,
                    },
                }))
                counts["rename_legacy_bbl"] += 1
                continue

            address = (p.get("address") or "").strip()
            parsed = parse_address(address)
            if not parsed:
                plans.append((pid, {
                    "category": "address_unparseable",
                    "name": name,
                    "address": address,
                }))
                counts["address_unparseable"] += 1
                continue

            rows = await query_pluto(http, parsed)
            await asyncio.sleep(INTER_REQUEST_DELAY_S)

            if not rows:
                plans.append((pid, {
                    "category": "pluto_no_match",
                    "name": name,
                    "parsed": parsed,
                }))
                counts["pluto_no_match"] += 1
                continue

            best, reason = disambiguate_pluto_rows(
                rows, nyc_bin_hint=p.get("nyc_bin"),
            )
            new_bbl = (best.get("bbl") or "").strip() if best else ""

            if len(rows) > 1:
                counts["pluto_multi"] += 1
                if len(multi_examples) < 5:
                    multi_examples.append({
                        "project_id": pid,
                        "name": name,
                        "rows": rows,
                        "chosen_bbl": new_bbl,
                        "reason": reason,
                    })
            else:
                counts["pluto_match"] += 1

            plans.append((pid, {
                "category": "pluto_match" if new_bbl else "pluto_no_match",
                "name": name,
                "set": {
                    "bbl": new_bbl,
                    "bbl_source": "pluto_lookup",
                    "bbl_last_synced": now,
                },
                "candidates": rows,
            }))

    print("Distribution:")
    for k, v in counts.items():
        print(f"  {k:24s} {v}")
    print()

    print("Per-project plan:")
    for pid, plan in plans:
        cat = plan["category"]
        if cat == "stamp_existing_bbl":
            print(f"  {pid[-6:]:>6}  STAMP   {plan['name'][:50]:50s}  -> source=address_lookup_at_creation (bbl already set)")
        elif cat == "rename_legacy_bbl":
            new_bbl = plan["set"]["bbl"]
            print(f"  {pid[-6:]:>6}  RENAME  {plan['name'][:50]:50s}  -> bbl={new_bbl}  (copied from legacy nyc_bbl)")
        elif cat == "pluto_match":
            new_bbl = plan["set"]["bbl"]
            print(f"  {pid[-6:]:>6}  PLUTO   {plan['name'][:50]:50s}  -> bbl={new_bbl}")
        elif cat == "pluto_no_match":
            print(f"  {pid[-6:]:>6}  NO-PLT  {plan['name'][:50]:50s}  (PLUTO 0 rows)")
        elif cat == "address_unparseable":
            addr = plan.get('address') or ''
            print(f"  {pid[-6:]:>6}  NO-ADR  {plan['name'][:50]:50s}  addr={addr[:40]!r}")

    if multi_examples:
        print()
        print("Multi-match examples (first 5):")
        for ex in multi_examples:
            print(f"  {ex['name']!r}: chose bbl={ex['chosen_bbl']} from {len(ex['rows'])} rows ({ex['reason']})")
            for r in ex["rows"][:3]:
                print(f"    bbl={r.get('bbl')} bin={r.get('bin')} address={r.get('address')!r}")

    if dry_run:
        print()
        print("DRY-RUN: no writes performed.")
        return 0

    # ── LIVE ──
    print()
    print("Applying writes...")
    from bson import ObjectId
    from pymongo import UpdateOne

    ops = []
    for pid, plan in plans:
        if plan["category"] in ("address_unparseable", "pluto_no_match"):
            continue
        update_set = plan.get("set") or {}
        if not update_set:
            continue
        try:
            oid = ObjectId(pid) if len(pid) == 24 else pid
        except Exception:
            oid = pid
        ops.append(UpdateOne(
            {"_id": oid},
            {"$set": update_set},
        ))

    if ops:
        result = await db.projects.bulk_write(ops, ordered=False)
        print(f"  modified={result.modified_count}  matched={result.matched_count}")

    # Index — idempotent
    try:
        await db.projects.create_index(
            [("bbl", 1)],
            name="projects_bbl_sparse",
            sparse=True,
        )
        print("  ensured sparse index on projects.bbl")
    except Exception as e:
        print(f"  index ensure: {e!r}")

    print("\nDone.")
    print()
    print("Note: legacy `nyc_bbl` field NOT removed in this migration.")
    print("Reads continue to fall back to nyc_bbl during the deploy window.")
    print("Cleanup commit drops nyc_bbl from code + Mongo after verification.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show distribution + per-project plan, no writes.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
