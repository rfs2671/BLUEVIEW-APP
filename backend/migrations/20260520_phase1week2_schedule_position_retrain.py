"""Phase 1 Week 2 — post-deploy retrain for schedule_position_ratio rollout.

After the feature rename + per-(member, day) compute lands, every
existing ``prediction_models`` doc carries ``beta_coefficients``,
``panel_mu``, and ``panel_sigma`` dicts keyed by the OLD feature name
(``derived_lifecycle_stage_pct``). Those keys must be regenerated with
the new name (``schedule_position_ratio``) and re-fit against the new
per-(member, day) panel data.

This script wraps ``nightly_refit_for_all_projects`` (the same code
path that runs every night at 1:30 AM ET) and invokes it once
synchronously post-deploy. Concurrency stays at 2 per PR #15B.3 Site 4
lock — parallel refit-tick calls against live ``dob_logs`` aggregates
exposed a race condition that surfaced None/NaN x_now values.

Idempotency:
  Each project's refit overwrites its own ``prediction_models`` doc.
  Re-running the script is safe — the per-project work is short
  (~30s) and key-overwrite semantics. Interrupted runs can be
  resumed by simply re-invoking; no per-project progress is tracked.

Estimated wall-clock:
  27 projects × ~30s / concurrency=2 ≈ 7-8 minutes. Add 1-2 minutes
  for Atlas connection + cohort cold-load. Plan ~10 minutes.

Usage:
    # Dry-run — counts active projects, no writes
    MONGO_URL='mongodb+srv://...' DB_NAME='blueview' \\
        python -m migrations.20260520_phase1week2_schedule_position_retrain --dry-run

    # Live (post-deploy)
    MONGO_URL='mongodb+srv://...' DB_NAME='blueview' \\
        python -m migrations.20260520_phase1week2_schedule_position_retrain

Exit codes:
  0 — all 27 projects refit successfully (n_failed == 0)
  1 — one or more project refits failed (per-project errors logged)
  2 — bad invocation (missing env vars)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from lib.server_http import ServerHttpClient  # noqa: E402
from lib.statistical_engine.live_mutation import (  # noqa: E402
    nightly_refit_for_all_projects,
)
from lib.statistical_engine.socrata_client import SocrataClient  # noqa: E402


logger = logging.getLogger(__name__)


async def _amain(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required",
              file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    if args.dry_run:
        # Count active projects without touching them.
        try:
            n = await db.projects.count_documents({})
        except Exception as e:
            print(f"ERROR: db.projects count failed: {e!r}",
                  file=sys.stderr)
            return 1
        print("=" * 60)
        print("DRY-RUN — schedule_position_ratio retrain")
        print("=" * 60)
        print(f"  Mongo DB:           {db_name}")
        print(f"  Projects to refit:  {n}")
        print(f"  Concurrency:        {args.concurrency} "
              f"(PR #15B.3 Site 4 lock)")
        print(f"  Est. wall-clock:    "
              f"{int((n * 30) / max(1, args.concurrency))}s + 1-2 min overhead")
        print()
        print("No writes performed. To execute, re-run without --dry-run.")
        return 0

    print("=" * 60)
    print("Phase 1 Week 2 — schedule_position_ratio retrain")
    print("=" * 60)
    print(f"  Mongo DB:    {db_name}")
    print(f"  Concurrency: {args.concurrency}")
    print()

    async with ServerHttpClient(timeout=30.0) as http:
        socrata = SocrataClient(http)
        result = await nightly_refit_for_all_projects(
            db, socrata, concurrency_limit=args.concurrency,
        )

    print("\n" + "=" * 60)
    print(
        f"Retrain complete: n_succeeded={result['n_succeeded']} "
        f"n_failed={result['n_failed']}"
    )
    print("=" * 60)
    if result.get("errors"):
        print("\nPer-project errors:")
        for err in result["errors"]:
            print(f"  {err}")
    return 0 if result["n_failed"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count projects without writing.",
    )
    parser.add_argument(
        "--concurrency", type=int, default=2,
        help=(
            "Parallel project refits (default: 2 per PR #15B.3 lock). "
            "Higher values increase Socrata pressure."
        ),
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
