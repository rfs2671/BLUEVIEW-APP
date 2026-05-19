"""Phase 1 Week 1 — post-backfill health validation.

Run after EACH dataset's backfill completes (Gate 4 follow-up).
Reports to stdout in human-readable markdown so the operator can
paste the output into the deployment log.

Checks:

  1. Row counts
     For each backfilled collection: estimated document count + a
     comparison against the order-of-magnitude expected for a 3-year
     × ~5k BIN backfill. Crosses a "looks reasonable" threshold or
     flags "DOES NOT LOOK RIGHT — investigate".

  2. Index presence
     Compare against the index list in _create_backfill_indexes.py
     (sourced as the single source of truth). Any missing or
     unexpected-named index is reported.

  3. Sample query latency
     Run three indexed lookups per collection (by natural key,
     by BIN/BBL, by date range) with `explain()` + wall-clock timing.
     Pass threshold: <100ms each. Slower → flagged.

  4. Spot checks
     For up to 3 known production projects (read from db.projects),
     query the corresponding *_historical collection by BIN/BBL and
     report the row count + a sample row's natural key. Confirms the
     backfill landed where the operator expects.

Usage:
    MONGO_URL='mongodb+srv://...' DB_NAME='blueview' \
        python -m scripts._validate_backfill_health

    # Validate only one collection
    python -m scripts._validate_backfill_health \
        --collection socrata_ecb_violations_historical

Exit codes:
  0 — all checks passed
  1 — any check failed (missing index, slow query, suspicious row count)
  2 — bad invocation
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# Load the index spec list from the sibling script so we don't
# duplicate the index definitions.
def _load_index_specs() -> List[Any]:
    spec_path = _HERE / "_create_backfill_indexes.py"
    spec = importlib.util.spec_from_file_location(
        "_create_backfill_indexes", spec_path,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.INDEX_SPECS)


# Per-collection expected order-of-magnitude row counts. These are
# rough — pre-backfill they're zero; post-backfill we expect:
#   • ecb_violations:  ~10k-50k for 5k BINs over 3 years
#   • permits:         ~50k-200k
#   • complaints:      ~30k-100k
# A value below the "min" or above the "max" triggers a warning,
# not a hard failure.
EXPECTED_ROW_RANGES: Dict[str, Tuple[int, int]] = {
    "socrata_ecb_violations_historical": (5_000, 100_000),
    "socrata_permits_historical":         (10_000, 300_000),
    "socrata_complaints_historical":      (10_000, 200_000),
}

# Per-collection (natural_key, secondary_lookup_field, date_field)
# tuple used to build the three latency probes.
COLLECTION_PROBES: Dict[str, Tuple[str, str, str]] = {
    "socrata_ecb_violations_historical":
        ("ecb_violation_number", "bin", "issue_date"),
    "socrata_permits_historical":
        ("permit_si_no", "bbl", "approved_date"),
    "socrata_complaints_historical":
        ("complaint_number", "bin", "date_entered"),
}

LATENCY_THRESHOLD_MS = 100.0


# ── Output formatting ─────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    timing_ms: Optional[float] = None


@dataclass
class CollectionReport:
    collection: str
    checks: List[CheckResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str,
            timing_ms: Optional[float] = None) -> None:
        self.checks.append(CheckResult(name, passed, detail, timing_ms))

    def overall_pass(self) -> bool:
        return all(c.passed for c in self.checks)

    def render_markdown(self) -> str:
        out: List[str] = []
        verdict = "OK" if self.overall_pass() else "FAIL"
        out.append(f"\n## {self.collection}  [{verdict}]\n")
        for c in self.checks:
            tag = "PASS" if c.passed else "FAIL"
            timing = f" ({c.timing_ms:.1f} ms)" if c.timing_ms is not None else ""
            out.append(f"  [{tag}] {c.name}{timing}")
            for line in c.detail.splitlines():
                out.append(f"        {line}")
        return "\n".join(out)


# ── Checks ────────────────────────────────────────────────────────


async def _check_row_count(
    db: Any, collection: str, report: CollectionReport,
) -> None:
    t0 = time.perf_counter()
    try:
        count = await db[collection].estimated_document_count()
    except Exception as e:
        report.add(
            "row count", passed=False,
            detail=f"estimated_document_count raised: {e!r}",
            timing_ms=(time.perf_counter() - t0) * 1000,
        )
        return
    timing_ms = (time.perf_counter() - t0) * 1000

    lo, hi = EXPECTED_ROW_RANGES.get(collection, (0, 10**9))
    in_range = lo <= count <= hi
    detail = (
        f"estimated_document_count = {count:,}  "
        f"(expected {lo:,}–{hi:,} for a 3y × 5k BIN backfill)"
    )
    if not in_range:
        detail += (
            "\nNOTE: out-of-range count. Could mean: (a) backfill "
            "incomplete (cursor not done), (b) BIN list smaller than "
            "expected, (c) Socrata returned more rows than projected. "
            "Cross-check the cursor file + cursor.total_inserted."
        )
    report.add("row count", passed=in_range, detail=detail,
               timing_ms=timing_ms)


async def _check_indexes(
    db: Any, collection: str, report: CollectionReport,
    all_specs: List[Any],
) -> None:
    expected = {s.name for s in all_specs if s.collection == collection}
    if not expected:
        report.add("index presence", passed=True,
                   detail="no indexes specified for this collection")
        return

    try:
        existing = await db[collection].list_indexes().to_list(length=None)
    except Exception as e:
        report.add("index presence", passed=False,
                   detail=f"list_indexes raised: {e!r}")
        return
    existing_names = {i.get("name") for i in existing}
    missing = sorted(expected - existing_names)
    extras_relevant = sorted(
        (existing_names - expected) - {"_id_"}  # exclude default
    )

    passed = not missing
    detail_parts = [f"expected={sorted(expected)}",
                    f"present={sorted(existing_names)}"]
    if missing:
        detail_parts.append(f"MISSING: {missing}")
    if extras_relevant:
        detail_parts.append(
            f"unexpected (informational, not a failure): {extras_relevant}",
        )
    report.add("index presence", passed=passed,
               detail="\n".join(detail_parts))


async def _check_latency(
    db: Any, collection: str, report: CollectionReport,
) -> None:
    probes = COLLECTION_PROBES.get(collection)
    if probes is None:
        return  # no probes configured (caller may pass a custom collection)
    natural_key, lookup_field, date_field = probes

    # Probe 1 — natural-key lookup. Pull a real key from the collection
    # so the probe hits an actual row.
    sample = await db[collection].find_one(
        {natural_key: {"$exists": True, "$ne": None}},
        {natural_key: 1},
    )
    if sample is not None:
        key_val = sample.get(natural_key)
        t0 = time.perf_counter()
        await db[collection].find_one({natural_key: key_val})
        ms = (time.perf_counter() - t0) * 1000
        report.add(
            f"probe: lookup by {natural_key}",
            passed=ms < LATENCY_THRESHOLD_MS,
            detail=f"sample value {key_val!r}",
            timing_ms=ms,
        )
    else:
        report.add(
            f"probe: lookup by {natural_key}",
            passed=False,
            detail="no rows with this field present — collection empty?",
        )

    # Probe 2 — secondary-field lookup (BIN/BBL).
    sample = await db[collection].find_one(
        {lookup_field: {"$exists": True, "$ne": None}},
        {lookup_field: 1},
    )
    if sample is not None:
        v = sample.get(lookup_field)
        t0 = time.perf_counter()
        cnt = await db[collection].count_documents({lookup_field: v}, limit=100)
        ms = (time.perf_counter() - t0) * 1000
        report.add(
            f"probe: count by {lookup_field}",
            passed=ms < LATENCY_THRESHOLD_MS,
            detail=f"{lookup_field}={v!r} matched {cnt} rows (capped at 100)",
            timing_ms=ms,
        )

    # Probe 3 — recent date-range scan.
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_str = cutoff.strftime("%Y-%m-%dT00:00:00")
    t0 = time.perf_counter()
    cnt = await db[collection].count_documents(
        {date_field: {"$gte": cutoff_str}}, limit=500,
    )
    ms = (time.perf_counter() - t0) * 1000
    report.add(
        f"probe: count by {date_field} (last 30 days)",
        passed=ms < LATENCY_THRESHOLD_MS,
        detail=f"matched {cnt} rows (capped at 500)",
        timing_ms=ms,
    )


async def _check_spot_projects(
    db: Any, collection: str, report: CollectionReport,
) -> None:
    """Pick up to 3 active projects with a BIN; for each, count
    historical rows in the collection. Confirms the backfill landed
    where the operator expects (real projects, not just a uniform
    spray of unrelated BINs)."""
    probes = COLLECTION_PROBES.get(collection)
    if probes is None:
        return
    _natural_key, lookup_field, _date_field = probes

    # Determine the BIN-or-BBL source field on the project doc.
    project_field = "nyc_bin"
    if lookup_field == "bbl":
        project_field = "bbl"

    projects = await db.projects.find(
        {
            "is_deleted": {"$ne": True},
            "status": "active",
            project_field: {"$exists": True, "$ne": None},
        },
        {"_id": 1, "name": 1, project_field: 1},
    ).limit(3).to_list(length=3)

    if not projects:
        report.add(
            "spot check: real projects",
            passed=True,
            detail=f"no active projects with {project_field} to check against",
        )
        return

    lines: List[str] = []
    any_match = False
    for p in projects:
        v = p.get(project_field)
        if not v:
            continue
        cnt = await db[collection].count_documents({lookup_field: str(v)})
        if cnt > 0:
            any_match = True
        lines.append(
            f"project {str(p['_id'])[-6:]} ({p.get('name') or '?'!r}) "
            f"{project_field}={v} → {cnt} rows in {collection}",
        )
    report.add(
        "spot check: real projects",
        passed=any_match,
        detail=("\n".join(lines)
                if lines else "no projects had a usable lookup value"),
    )


# ── Driver ────────────────────────────────────────────────────────


async def validate(db: Any, collections: List[str]) -> List[CollectionReport]:
    all_specs = _load_index_specs()
    reports: List[CollectionReport] = []
    for coll in collections:
        rpt = CollectionReport(collection=coll)
        await _check_row_count(db, coll, rpt)
        await _check_indexes(db, coll, rpt, all_specs)
        await _check_latency(db, coll, rpt)
        await _check_spot_projects(db, coll, rpt)
        reports.append(rpt)
    return reports


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


async def _amain(args: argparse.Namespace) -> int:
    db = _build_db()
    if args.collection:
        collections = [args.collection]
    else:
        collections = list(EXPECTED_ROW_RANGES.keys())

    reports = await validate(db, collections)
    print("# Backfill health validation report\n")
    print(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    for rpt in reports:
        print(rpt.render_markdown())

    any_failed = any(not r.overall_pass() for r in reports)
    print("\n---\n")
    print(f"Overall: {'FAIL' if any_failed else 'PASS'}\n")
    return 1 if any_failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection", default=None,
        help="Validate only this collection (omit to check all three).",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
