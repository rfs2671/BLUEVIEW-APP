"""One-off dry-run of the shadow sweep against live prod data.

Runs the same comparison the cron would but DOESN'T write to
`eligibility_shadow` — just prints a per-permit summary so we can
sanity-check before flipping ELIGIBILITY_REWRITE_MODE on Railway.

Run:
    python scripts/eligibility_shadow_dry_run.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


async def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    from lib import eligibility_v2, eligibility_shadow
    from permit_renewal import _check_renewal_eligibility_legacy_inner

    today = datetime.now(timezone.utc)
    tracked = await db.projects.find(
        {"track_dob_status": True, "is_deleted": {"$ne": True}}
    ).to_list(500)

    print(f"DRY-RUN shadow sweep — {len(tracked)} tracked project(s)")
    print(f"now: {today.isoformat()}\n")

    cat_counts = Counter()
    strategy_dist = Counter()
    eff_kind_dist = Counter()
    cat1_examples = []
    cat3_examples = []
    cat5_examples = []
    n = 0

    for project in tracked:
        cid = project.get("company_id")
        company = (
            await db.companies.find_one(
                {"_id": cid if isinstance(cid, type(project["_id"])) else cid,
                 "is_deleted": {"$ne": True}}
            )
            if cid else {}
        ) or {}

        permits = await db.dob_logs.find({
            "project_id": str(project["_id"]),
            "record_type": "permit",
            "is_deleted": {"$ne": True},
        }).to_list(500)

        for permit in permits:
            n += 1
            try:
                async def _legacy(p, pj, c, t, _name=None):
                    name = (
                        _name or (c.get("gc_business_name") if c else None)
                        or (c.get("name") if c else "") or ""
                    )
                    return await _check_renewal_eligibility_legacy_inner(
                        db, p, pj, name, c, today=t,
                    )

                async def _v2(d, p, pj, c, t):
                    return await eligibility_v2.evaluate(d, p, pj, c or {}, today=t)

                doc = await eligibility_shadow.run_one(
                    db,
                    legacy_callable=_legacy,
                    v2_callable=_v2,
                    permit=permit,
                    project=project,
                    company=company,
                    today=today,
                )

                for div in (doc.get("divergences") or []):
                    cat_counts[div.get("category")] += 1
                    if div.get("category") == "identity":
                        cat1_examples.append((str(permit["_id"]), div))
                    elif div.get("category") == "severity":
                        cat3_examples.append((str(permit["_id"]), div))
                    elif div.get("category") == "crash":
                        cat5_examples.append((str(permit["_id"]), div))
                    elif div.get("category") == "expected":
                        if div.get("field") == "renewal_strategy":
                            v = div.get("new_value")
                            if v:
                                strategy_dist[v] += 1
                        elif div.get("field") == "effective_expiry":
                            eff_kind_dist[div.get("kind", "?")] += 1

                # One-line summary per permit
                new = doc.get("new_result") or {}
                lim = (new.get("limiting_factor") or {})
                print(
                    f"  permit={str(permit['_id'])[:24]:24s} "
                    f"job={permit.get('job_number','-'):20s} "
                    f"strat={new.get('renewal_strategy','-'):24s} "
                    f"limit={lim.get('kind','-'):14s} "
                    f"eff={new.get('effective_expiry','-')!s:32s} "
                    f"old_ms={doc.get('old_latency_ms',0):.1f} "
                    f"new_ms={doc.get('new_latency_ms',0):.1f}"
                )
            except Exception as e:
                print(f"  permit={permit.get('_id')} — DRY RUN ERROR: {type(e).__name__}: {e}")

    print(f"\n{'─'*60}")
    print(f"Totals across {n} permits:")
    for cat in ("identity", "expected", "severity", "crash"):
        print(f"  Category — {cat}: {cat_counts[cat]}")
    print()
    print("Strategy distribution (Cat 2 'renewal_strategy' rows):")
    for k, v in strategy_dist.most_common():
        print(f"  {k:30s} {v}")
    print()
    print("effective_expiry sub-class distribution:")
    for k, v in eff_kind_dist.most_common():
        print(f"  {k:30s} {v}")
    if cat1_examples:
        print("\nCat 1 IDENTITY DIFFS (must be 0 to cut over):")
        for pid, div in cat1_examples[:10]:
            print(f"  {pid}: {div}")
    if cat3_examples:
        print("\nCat 3 SEVERITY (review individually):")
        for pid, div in cat3_examples[:10]:
            print(f"  {pid}: {div.get('direction')} {div.get('old_value')} -> {div.get('new_value')}")
    if cat5_examples:
        print("\nCat 5 CRASHES (must be 0 to cut over):")
        for pid, div in cat5_examples[:10]:
            print(f"  {pid}: side={div.get('side')} {div.get('exception',{}).get('type')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
