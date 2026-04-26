"""Eligibility shadow run report.

Reads `eligibility_shadow` over a configurable time window (default:
last 48 hours) and prints the cutover-decision summary defined in the
step-5 contract:

  Cat 1 (identity diffs):       <count>   ← MUST be 0 to proceed
  Cat 2 (expected divergence):
    - effective_expiry shifts:
        - shed_90d_cap, bis_31d_lookahead, limit_factor_relabel,
          awaiting_extension_window, other (with examples)
    - renewal_strategy distribution
  Cat 3 (severity escalations): <count>   ← review individually
  Cat 4 (performance):
    - p50/p95 old vs new
  Cat 5 (crashes):              <count>   ← MUST be 0 to proceed

Cutover gate:
  Cat 1 == 0 AND Cat 5 == 0 AND Cat 3 reviewed AND Cat 4 p95 within 2x

Run:
    # default — last 48hr
    python scripts/eligibility_shadow_report.py

    # custom window
    python scripts/eligibility_shadow_report.py --hours 72
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


def _format_section_header(title: str) -> str:
    return f"\n{'─' * 60}\n  {title}\n{'─' * 60}"


async def main(hours: int) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cursor = db.eligibility_shadow.find({"ran_at": {"$gte": cutoff}})
    docs = await cursor.to_list(length=None)

    print(f"\nSHADOW RUN REPORT — eligibility rewrite")
    print(f"Window: last {hours}h "
          f"({cutoff.isoformat()} → {datetime.now(timezone.utc).isoformat()})")
    print(f"Permits evaluated: {len(docs)}")

    if not docs:
        print("\nNo shadow records in window. Either ELIGIBILITY_REWRITE_MODE")
        print("isn't 'shadow', the cron isn't running, or the window is too short.")
        return 0

    # ── Category counters ───────────────────────────────────────────
    cat1_identity = []           # list[(permit_id, field, old, new)]
    cat2_eff_expiry = Counter()  # kind → count
    cat2_eff_other_examples: List[Dict[str, Any]] = []
    cat3_severity = []           # list[(permit_id, direction, old, new)]
    cat5_crashes = []            # list[(permit_id, side, exc_type, message)]
    strategy_dist = Counter()    # renewal_strategy → count
    old_lat: List[float] = []
    new_lat: List[float] = []

    for doc in docs:
        permit_id = doc.get("permit_id")
        old_lat.append(float(doc.get("old_latency_ms") or 0.0))
        new_lat.append(float(doc.get("new_latency_ms") or 0.0))

        for div in (doc.get("divergences") or []):
            cat = div.get("category")
            if cat == "identity":
                cat1_identity.append((
                    permit_id, div.get("field"),
                    div.get("old_value"), div.get("new_value"),
                ))
            elif cat == "expected":
                if div.get("field") == "effective_expiry":
                    kind = div.get("kind", "other")
                    cat2_eff_expiry[kind] += 1
                    if kind == "other" and div.get("example_detail"):
                        cat2_eff_other_examples.append({
                            "permit_id": permit_id,
                            **(div.get("example_detail") or {}),
                        })
                elif div.get("field") == "renewal_strategy":
                    val = div.get("new_value")
                    if val:
                        strategy_dist[val] += 1
            elif cat == "severity":
                cat3_severity.append((
                    permit_id,
                    div.get("direction"),
                    div.get("old_value"),
                    div.get("new_value"),
                ))
            elif cat == "crash":
                exc = div.get("exception") or {}
                cat5_crashes.append((
                    permit_id, div.get("side"),
                    exc.get("type"), exc.get("message"),
                ))

    # ── Print ───────────────────────────────────────────────────────
    print(_format_section_header("Category 1 — IDENTITY DIFFS (must be 0)"))
    print(f"  Count: {len(cat1_identity)}")
    for pid, field, old, new in cat1_identity[:20]:
        print(f"    permit={pid}  field={field}  old={old!r}  new={new!r}")
    if len(cat1_identity) > 20:
        print(f"    ... and {len(cat1_identity) - 20} more")

    print(_format_section_header("Category 2 — EXPECTED DIVERGENCES"))
    print("  effective_expiry shifts:")
    for kind, count in cat2_eff_expiry.most_common():
        print(f"    {kind:30s} {count}")
    if cat2_eff_other_examples:
        print(f"\n  'other' sub-class examples (review for missing kind):")
        for ex in cat2_eff_other_examples[:5]:
            print(f"    {ex}")
    print(f"\n  renewal_strategy distribution:")
    for strat, count in strategy_dist.most_common():
        print(f"    {strat:30s} {count}")

    print(_format_section_header("Category 3 — SEVERITY ESCALATIONS (review individually)"))
    print(f"  Count: {len(cat3_severity)}")
    direction_count = Counter(d for _, d, *_ in cat3_severity)
    for direction, count in direction_count.most_common():
        print(f"    {direction:15s} {count}")
    if cat3_severity:
        print("\n  Examples (first 10):")
        for pid, direction, old, new in cat3_severity[:10]:
            print(f"    permit={pid}  {direction:15s} {old} → {new}")

    print(_format_section_header("Category 4 — PERFORMANCE"))
    print(f"  Old logic latency:  p50={_percentile(old_lat, 50):.2f}ms  "
          f"p95={_percentile(old_lat, 95):.2f}ms  "
          f"p99={_percentile(old_lat, 99):.2f}ms")
    print(f"  New logic latency:  p50={_percentile(new_lat, 50):.2f}ms  "
          f"p95={_percentile(new_lat, 95):.2f}ms  "
          f"p99={_percentile(new_lat, 99):.2f}ms")
    if old_lat and new_lat:
        ratio = _percentile(new_lat, 95) / max(_percentile(old_lat, 95), 0.01)
        print(f"  p95 ratio (new/old): {ratio:.2f}x  "
              f"({'WITHIN' if ratio <= 2.0 else 'OVER'} 2x gate)")

    print(_format_section_header("Category 5 — CRASHES (must be 0)"))
    print(f"  Count: {len(cat5_crashes)}")
    side_count = Counter(s for _, s, *_ in cat5_crashes)
    for side, count in side_count.most_common():
        print(f"    {side:10s} {count}")
    for pid, side, etype, msg in cat5_crashes[:10]:
        print(f"    permit={pid}  side={side}  {etype}: {msg!r}")

    # ── Cutover gate ────────────────────────────────────────────────
    print(_format_section_header("CUTOVER GATE"))
    cat1_ok = len(cat1_identity) == 0
    cat5_ok = len(cat5_crashes) == 0
    p95_ok = (
        not (old_lat and new_lat)
        or _percentile(new_lat, 95) <= 2.0 * _percentile(old_lat, 95)
    )
    cat3_count = len(cat3_severity)

    print(f"  Cat 1 (identity)  = 0:           {'✅' if cat1_ok else '❌'}  ({len(cat1_identity)})")
    print(f"  Cat 5 (crashes)   = 0:           {'✅' if cat5_ok else '❌'}  ({len(cat5_crashes)})")
    print(f"  Cat 4 p95 ≤ 2x old:              {'✅' if p95_ok else '❌'}")
    print(f"  Cat 3 (severity) reviewed:       MANUAL  ({cat3_count} to review)")

    if cat1_ok and cat5_ok and p95_ok and cat3_count == 0:
        print("\n  ✅ ALL GATES GREEN — safe to flip ELIGIBILITY_REWRITE_MODE=live")
    else:
        print("\n  ⛔ NOT CUTOVER-READY — investigate items above before flipping live")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hours", type=int, default=48,
        help="Window for the report (default: 48)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(hours=args.hours)))
