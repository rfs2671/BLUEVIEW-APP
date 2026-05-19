"""Phase 1 Week 1 — select the 5,000-BIN target list for backfill (Gate 3).

The 3-year backfill is scoped to a curated 5k-BIN list rather than
city-wide, both to keep Atlas storage growth predictable and to make
the backfilled dataset directly useful (overwhelmingly tracking
projects that currently exist or recently completed).

Selection logic (per Phase 1 Week 1 directive):

  Tier A — Active projects
    All non-deleted projects in db.projects with status='active'.
    Pulls the project's `nyc_bin` field (canonical BIN storage; some
    older docs may also have a sibling `bin` field — we read whichever
    is present and de-dupe).

  Tier B — Recently completed
    Non-deleted projects with status != 'active' whose updated_at OR
    completed_at falls within the last 18 months. completed_at is the
    primary completion signal; updated_at is the fallback because most
    existing project docs predate the completed_at convention.

  Tier C — Supplemental random sample (only if A+B < 5,000)
    Random sample from rbx6-tga4 (DOB permits) of recent major-work
    filings citywide, scoped to the last 18 months. "Major work" is
    operationalized as filing_reason='Initial Permit' (mirrors the
    statistical_engine actuarial denominator convention). Only used
    to reach the 5k target — never overrides Tiers A/B.

Output: backend/scripts/_backfill_target_bins.json
  {
    "generated_at":        "<iso timestamp>",
    "selection_criteria":  "<description>",
    "total_count":         <int>,
    "active_projects":     [<bin>, ...],
    "recently_completed":  [<bin>, ...],
    "supplemental_random": [<bin>, ...]
  }

The three lists are pre-deduplicated against each other in
priority order (A before B before C) so the final list has exactly
total_count unique BINs.

Logs (stdout): per-tier counts + final total. Operator reviews
the output file before Gate 4 authorization.

Usage:
    # Dry-run (no Socrata call for tier C — uses placeholder count)
    python -m scripts._select_backfill_target_bins --dry-run

    # Real run — writes _backfill_target_bins.json
    MONGO_URL='...' DB_NAME='...' \
        python -m scripts._select_backfill_target_bins

Exit codes:
  0 — file written (or dry-run completed)
  1 — Mongo / Socrata error
  2 — bad invocation
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.server_http import ServerHttpClient  # noqa: E402
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_DOB_PERMITS,
    SocrataClient,
    SocrataQueryError,
)


OUTPUT_PATH = _HERE / "_backfill_target_bins.json"

TARGET_TOTAL = 5_000
RECENT_COMPLETION_WINDOW_DAYS = 18 * 30  # ~18 months
SUPPLEMENTAL_SAMPLE_CAP = 18_000         # ~16k needed at 31% dedupe ratio
                                         # + 12% margin to reach 5k unique BINs


def _normalize_bin(value: Any) -> Optional[str]:
    """Return a stripped BIN string, or None if the input is empty
    or non-numeric. Defensive against the historical `nyc_bin` storage
    variants (string, int, occasional `'1000000'` placeholder)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Filter obvious placeholders / non-BIN content. NYC BINs are
    # 7-digit numeric. Don't reject 6-digit BINs in case there are
    # legacy short BINs in the data — but reject all-zero placeholders.
    if not s.isdigit():
        return None
    if int(s) == 0:
        return None
    return s


def _read_project_bin(doc: Dict[str, Any]) -> Optional[str]:
    """Read the BIN from a project doc, preferring `nyc_bin` (canonical
    storage) over `bin` (sometimes present on older docs)."""
    return _normalize_bin(doc.get("nyc_bin")) or _normalize_bin(doc.get("bin"))


async def _select_active(db: Any) -> List[str]:
    """All non-deleted, status='active' projects with a usable BIN."""
    cursor = db.projects.find(
        {"is_deleted": {"$ne": True}, "status": "active"},
        {"_id": 1, "nyc_bin": 1, "bin": 1},
    )
    docs = await cursor.to_list(length=None)
    bins: List[str] = []
    for d in docs:
        b = _read_project_bin(d)
        if b is not None:
            bins.append(b)
    return bins


async def _select_recently_completed(db: Any) -> List[str]:
    """Non-deleted, non-active projects whose updated_at OR completed_at
    falls in the last RECENT_COMPLETION_WINDOW_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=RECENT_COMPLETION_WINDOW_DAYS,
    )
    cursor = db.projects.find(
        {
            "is_deleted": {"$ne": True},
            "status": {"$ne": "active"},
            "$or": [
                {"completed_at": {"$gte": cutoff}},
                {"updated_at":   {"$gte": cutoff}},
            ],
        },
        {"_id": 1, "nyc_bin": 1, "bin": 1, "completed_at": 1, "updated_at": 1},
    )
    docs = await cursor.to_list(length=None)
    bins: List[str] = []
    for d in docs:
        b = _read_project_bin(d)
        if b is not None:
            bins.append(b)
    return bins


async def _select_supplemental(
    needed: int,
    socrata: Optional[SocrataClient],
) -> List[str]:
    """Random sample of BINs from rbx6-tga4 major-work filings in the
    last 18 months. `needed` is the max BINs to return (caller already
    subtracted out tier A+B).

    Strategy: pull up to SUPPLEMENTAL_SAMPLE_CAP rows, dedupe by BIN,
    truncate to `needed`. We don't pre-shuffle — Socrata returns rows
    in whatever order $order specifies; we $order by issued_date DESC
    so newer permits come first (likeliest to still be active sites)."""
    if needed <= 0 or socrata is None:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(
        days=RECENT_COMPLETION_WINDOW_DAYS,
    )
    cutoff_str = cutoff.strftime("%Y-%m-%dT00:00:00")
    sample_size = min(SUPPLEMENTAL_SAMPLE_CAP, needed * 5)  # over-pull
                                                            # to absorb
                                                            # BIN dedupe
    rows = await socrata.query(
        DATASET_DOB_PERMITS,
        where=(
            f"issued_date >= '{cutoff_str}' AND "
            f"filing_reason = 'Initial Permit'"
        ),
        select=["bin", "issued_date", "borough", "filing_reason"],
        order="issued_date DESC",
        limit=sample_size,
    )
    seen: set = set()
    out: List[str] = []
    for r in rows:
        b = _normalize_bin(r.get("bin"))
        if b is None or b in seen:
            continue
        seen.add(b)
        out.append(b)
        if len(out) >= needed:
            break
    return out


def _dedupe_layered(
    active: List[str],
    completed: List[str],
    supplemental: List[str],
) -> tuple[List[str], List[str], List[str]]:
    """Strip later-tier BINs that already appear in an earlier tier.
    Earlier tier wins — active before completed before supplemental.

    Within a tier, preserve first-seen order to keep the JSON readable
    + reproducible across runs (Mongo cursor order is stable when
    backed by an _id-ordered scan)."""
    seen: set = set()
    def _filter(src: List[str]) -> List[str]:
        out: List[str] = []
        for b in src:
            if b not in seen:
                seen.add(b)
                out.append(b)
        return out
    a = _filter(active)
    c = _filter(completed)
    s = _filter(supplemental)
    return (a, c, s)


def _build_db():
    from motor.motor_asyncio import AsyncIOMotorClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise SystemExit(
            "MONGO_URL and DB_NAME environment variables are required."
        )
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


async def select_target_bins(
    db: Any,
    socrata: Optional[SocrataClient],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """End-to-end selection. Returns the dict that gets written to
    _backfill_target_bins.json (or printed in dry-run)."""
    active_raw = await _select_active(db)
    completed_raw = await _select_recently_completed(db)
    print(
        f"Tier A (active):              {len(active_raw)} raw BINs",
        flush=True,
    )
    print(
        f"Tier B (recently_completed):  {len(completed_raw)} raw BINs",
        flush=True,
    )

    # First-pass dedupe so we know how many supplemental BINs we need.
    active, completed, _ = _dedupe_layered(active_raw, completed_raw, [])
    have = len(active) + len(completed)
    need = max(0, TARGET_TOTAL - have)
    print(
        f"After Tier A+B dedupe: {have} unique → need {need} from Tier C",
        flush=True,
    )

    if need > 0 and not dry_run:
        supplemental_raw = await _select_supplemental(need, socrata)
    elif need > 0 and dry_run:
        # In dry-run, skip the Socrata call but log what we WOULD pull.
        print(
            f"  [dry-run] would query rbx6-tga4 for ~{need} supplemental "
            f"BINs (filing_reason='Initial Permit', last 18mo)",
            flush=True,
        )
        supplemental_raw = []
    else:
        supplemental_raw = []

    active, completed, supplemental = _dedupe_layered(
        active_raw, completed_raw, supplemental_raw,
    )
    total = len(active) + len(completed) + len(supplemental)

    print(
        f"Tier C (supplemental_random): {len(supplemental)} unique BINs",
        flush=True,
    )
    print(f"FINAL TOTAL: {total} BINs (target was {TARGET_TOTAL})",
          flush=True)
    if total < TARGET_TOTAL:
        print(
            f"  NOTE: total < target. Backfill scope is whatever this "
            f"list contains — operator can re-run with broader Tier C "
            f"criteria if needed.",
            flush=True,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_criteria": (
            "Tier A: db.projects status='active' && !is_deleted. "
            "Tier B: status!=active && (completed_at OR updated_at) "
            f"within last {RECENT_COMPLETION_WINDOW_DAYS} days. "
            "Tier C: random sample from rbx6-tga4 "
            f"filing_reason='Initial Permit' last "
            f"{RECENT_COMPLETION_WINDOW_DAYS} days, ordered by "
            "issued_date DESC, up to target total."
        ),
        "total_count": total,
        "active_projects": active,
        "recently_completed": completed,
        "supplemental_random": supplemental,
    }


async def _amain(args: argparse.Namespace) -> int:
    if args.dry_run:
        print("DRY-RUN: Mongo reads happen; Socrata Tier C is mocked; "
              "no file written.", flush=True)
        db = _build_db()
        payload = await select_target_bins(db, None, dry_run=True)
        print("\n--- payload preview (lists truncated) ---", flush=True)
        preview = dict(payload)
        for k in ("active_projects", "recently_completed",
                  "supplemental_random"):
            v = preview.get(k, [])
            preview[k] = f"<{len(v)} bins; first 5: {v[:5]}>"
        print(json.dumps(preview, indent=2), flush=True)
        return 0

    db = _build_db()
    try:
        async with ServerHttpClient(timeout=30.0) as http:
            socrata = SocrataClient(http)
            payload = await select_target_bins(db, socrata, dry_run=False)
    except SocrataQueryError as e:
        print(f"ERROR: Socrata query failed: {e!r}", file=sys.stderr,
              flush=True)
        return 1
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)",
          flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Read Mongo but skip Socrata + file write.",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
