"""Phase V2.2 — Statistical baseline computation.

Pre-aggregates peer-set statistics so the per-project re-stat
hot path stays fast (<500 ms target). Peer set is defined by the
spec as `(borough, project_class, use_type)` over the past 2
years. Sample-size fallback ladder: drop use_type → drop class
→ citywide.

V2.2.4 Path A: peer-comparison is BBL-keyed throughout, not
BIN-keyed. PLUTO's Socrata payload has no `bin` column, and
nyc_violations' Socrata payload has no `bbl` column (we derive
it from boro/block/lot in the canonicalizer). Switching the
join key to BBL aligns all four collections —
nyc_pluto / nyc_violations / nyc_inspections / nyc_complaints_311
— on a field they ALL populate.

Three public surfaces:

  • `peer_bbls(db, project)` — async iterator yielding the BBLs
    of projects in the same peer set. Walks PLUTO when
    available; falls back to broader peer sets if sample < 20
    (per spec).

  • `compute_baseline_for_peer_set(db, peer_set, year_month)` —
    computes the aggregated stats for one peer-set key over a
    given month. Returns a dict suitable for upsert into
    `statistical_baselines`.

  • `compare_project_to_peers(db, project, *, now)` — given a
    project, look up its peer-set baseline and the project's
    own stats over the same window, return percentile ranking,
    peer-median, and metadata (which peer set was used and
    sample size).

Plus a nightly aggregator entry point (`run_baseline_aggregator`)
that pre-computes baselines for the current month across every
distinct peer-set key seen in PLUTO. Wired in server.py at
3:30 AM ET (between the V2.0 logbook 3 AM tick and the V2.2
weekly Sunday-morning ingest).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from lib.statistical_engine.schema import (
    MIN_PEER_SAMPLE_SIZE,
)
# V2.3 Commit 1: collection-name constants moved from schema.py
# to utils.py as a transitional placement. This file's query
# logic is left untouched per the Commit 1 spec — queries hit
# the (about-to-be-dropped) local mirror collections and return
# empty. Commit 3 rewrites every db[NYC_*_COLLECTION].find(...)
# call site to a lazy Socrata GET; at that point the import line
# below is deleted entirely.
from lib.statistical_engine.utils import (
    NYC_COMPLAINTS_311_COLLECTION,
    NYC_INSPECTIONS_COLLECTION,
    NYC_PLUTO_COLLECTION,
    NYC_VIOLATIONS_COLLECTION,
    STATISTICAL_BASELINES_COLLECTION,
)

logger = logging.getLogger(__name__)


# ── Peer-set key construction ─────────────────────────────────────


def _project_peer_key(project: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Extract the canonical peer-set key from a project doc.

    Borough comes from project.borough or PLUTO lookup at score
    time. project_class is the operator-set classification
    (regular / major_a / major_b). use_type is the PLUTO
    `landuse` or `bldgclass` field — for now we use whichever
    is present; a future cleanup may normalize this.
    """
    return {
        "borough":       project.get("borough") or _bin_borough_fallback(project),
        "project_class": project.get("project_class") or "regular",
        "use_type":      project.get("use_type") or project.get("landuse"),
    }


def _bin_borough_fallback(project: Dict[str, Any]) -> Optional[str]:
    """Derive borough from BBL when the project doc doesn't
    carry an explicit borough. BBL is 10 chars: first char is
    borough (1-5)."""
    bbl = project.get("bbl") or project.get("nyc_bbl")
    if not bbl or not isinstance(bbl, str):
        return None
    boro_code = bbl[:1]
    return {
        "1": "MANHATTAN",
        "2": "BRONX",
        "3": "BROOKLYN",
        "4": "QUEENS",
        "5": "STATEN ISLAND",
    }.get(boro_code)


# ── Peer set fallback ladder ──────────────────────────────────────
#
# Spec: "Fallback only if sample < 20." If the most-specific
# peer set (borough × class × use_type) has fewer than 20 BINs,
# drop use_type and try (borough × class). If that's still under
# 20, drop class and try (borough). If even citywide-by-class
# is short, fall back to citywide (no constraint other than
# borough being NYC).


async def _bbls_matching(
    db, *, borough=None, bldgclass=None, landuse=None,
) -> List[str]:
    """Return BBL list from PLUTO matching the supplied filters.
    None = unconstrained on that axis. Empty result is fine; the
    caller decides whether to fall back.

    V2.2.4 Path A: projects PLUTO's `bbl` (not the V2.2-era
    `bin` which the field_map doesn't populate). Returned BBLs
    are the 10-char canonical form because `upsert_record`
    normalizes PLUTO's `.00000000` suffix at write time."""
    q: Dict[str, Any] = {}
    if borough is not None:
        q["borough"] = borough
    if bldgclass is not None:
        q["bldgclass"] = bldgclass
    if landuse is not None:
        q["landuse"] = landuse
    bbls: List[str] = []
    cursor = db[NYC_PLUTO_COLLECTION].find(q, {"bbl": 1})
    async for doc in cursor:
        b = doc.get("bbl")
        if b:
            bbls.append(b)
    return bbls


async def peer_bbls(
    db, project: Dict[str, Any],
) -> Tuple[List[str], Dict[str, Any]]:
    """Resolve the peer BBL list for a project, applying the
    fallback ladder if the most-specific peer set is below
    `MIN_PEER_SAMPLE_SIZE` (20).

    Returns (bbls, metadata). metadata describes which peer set
    was used and the sample size — surfaced by
    `compare_project_to_peers` so the FE drawer can disclose
    "Compared against N projects in [borough]".
    """
    key = _project_peer_key(project)
    borough = key.get("borough")
    project_class = key.get("project_class")
    use_type = key.get("use_type")

    # Tier 1: borough × class × use_type.
    bbls = await _bbls_matching(
        db, borough=borough, bldgclass=project_class, landuse=use_type,
    )
    if len(bbls) >= MIN_PEER_SAMPLE_SIZE:
        return bbls, {
            "tier": "borough_class_use",
            "borough": borough,
            "project_class": project_class,
            "use_type": use_type,
            "sample_size": len(bbls),
        }

    # Tier 2: borough × class (drop use_type).
    bbls = await _bbls_matching(
        db, borough=borough, bldgclass=project_class,
    )
    if len(bbls) >= MIN_PEER_SAMPLE_SIZE:
        return bbls, {
            "tier": "borough_class",
            "borough": borough,
            "project_class": project_class,
            "sample_size": len(bbls),
        }

    # Tier 3: borough (drop class).
    bbls = await _bbls_matching(db, borough=borough)
    if len(bbls) >= MIN_PEER_SAMPLE_SIZE:
        return bbls, {
            "tier": "borough",
            "borough": borough,
            "sample_size": len(bbls),
        }

    # Tier 4: citywide (no filters).
    bbls = await _bbls_matching(db)
    return bbls, {
        "tier": "citywide",
        "sample_size": len(bbls),
    }


# ── Per-BBL event counts ──────────────────────────────────────────


async def _count_events_for_bbls(
    db,
    collection_name: str,
    bbls: List[str],
    *,
    since: datetime,
    until: Optional[datetime] = None,
) -> Dict[str, int]:
    """Return {bbl: count} for every BBL in `bbls` over the
    [since, until) window. BBLs with zero matching events are
    included (count=0) so percentile math is correct.

    V2.2.4 Path A: keyed on `bbl` (10-char canonical) not `bin`."""
    if not bbls:
        return {}
    q: Dict[str, Any] = {
        "bbl": {"$in": bbls},
        "occurred_date": {"$gte": since},
    }
    if until is not None:
        q["occurred_date"]["$lt"] = until
    counts: Dict[str, int] = {b: 0 for b in bbls}
    cursor = db[collection_name].find(q, {"bbl": 1})
    async for doc in cursor:
        b = doc.get("bbl")
        if b in counts:
            counts[b] += 1
    return counts


# ── Aggregation helpers ───────────────────────────────────────────


def _percentile(sorted_values: List[float], pct: float) -> float:
    """Nearest-rank percentile. pct in [0, 100]. Empty list → 0."""
    if not sorted_values:
        return 0.0
    if pct <= 0:
        return float(sorted_values[0])
    if pct >= 100:
        return float(sorted_values[-1])
    # Nearest-rank index, 1-indexed convention.
    k = max(0, min(len(sorted_values) - 1,
                   int(round((pct / 100.0) * (len(sorted_values) - 1)))))
    return float(sorted_values[k])


def _summarize_counts(counts_by_key: Dict[str, int]) -> Dict[str, float]:
    """Reduce a ``{key: count}`` map to summary stats (n, mean,
    median, p75, p90, p95, max). Used by both the per-peer-set
    aggregator and the project-vs-peer comparator. Key is BBL
    after the V2.2.4 Path A rename — function logic is key-shape-
    agnostic so the parameter is generically named."""
    values = sorted(counts_by_key.values())
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": 0.0, "median": 0.0,
                "p75": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "n":      float(n),
        "mean":   sum(values) / n,
        "median": _percentile(values, 50),
        "p75":    _percentile(values, 75),
        "p90":    _percentile(values, 90),
        "p95":    _percentile(values, 95),
        "max":    float(values[-1]),
    }


# ── Per-peer-set baseline computation ─────────────────────────────


def _year_month(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


async def compute_baseline_for_peer_set(
    db,
    *,
    borough: Optional[str],
    project_class: Optional[str],
    use_type: Optional[str],
    year_month: str,
    lookback_days: int = 365 * 2,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute aggregated stats (per-BIN event counts) for one
    peer-set key over a 2-year lookback window. Returns the doc
    suitable for upsert into `statistical_baselines`.
    """
    cur_now = now or datetime.now(timezone.utc)
    since = cur_now - timedelta(days=lookback_days)

    bbls = await _bbls_matching(
        db,
        borough=borough,
        bldgclass=project_class,
        landuse=use_type,
    )

    violations = await _count_events_for_bbls(
        db, NYC_VIOLATIONS_COLLECTION, bbls, since=since,
    )
    inspections = await _count_events_for_bbls(
        db, NYC_INSPECTIONS_COLLECTION, bbls, since=since,
    )
    complaints = await _count_events_for_bbls(
        db, NYC_COMPLAINTS_311_COLLECTION, bbls, since=since,
    )

    return {
        "borough":       borough,
        "project_class": project_class,
        "use_type":      use_type,
        "year_month":    year_month,
        "computed_at":   cur_now,
        "peer_sample_size": len(bbls),
        "violations":  _summarize_counts(violations),
        "inspections": _summarize_counts(inspections),
        "complaints":  _summarize_counts(complaints),
    }


async def upsert_baseline(db, baseline: Dict[str, Any]) -> bool:
    """Upsert one baseline doc into statistical_baselines keyed
    on the peer-set tuple + year_month. Idempotent re-runs."""
    if not baseline:
        return False
    key = {
        "borough":       baseline.get("borough"),
        "project_class": baseline.get("project_class"),
        "use_type":      baseline.get("use_type"),
        "year_month":    baseline.get("year_month"),
    }
    res = await db[STATISTICAL_BASELINES_COLLECTION].update_one(
        key,
        {"$set": baseline},
        upsert=True,
    )
    return bool(res.upserted_id)


# ── Nightly aggregator ────────────────────────────────────────────


async def run_baseline_aggregator(
    db,
    *,
    now: Optional[datetime] = None,
    max_peer_sets: Optional[int] = None,
) -> Dict[str, int]:
    """Walk every distinct (borough, bldgclass, landuse) tuple
    in PLUTO and compute a baseline for the current year_month.
    Soft-fails per peer set so one bad combination doesn't kill
    the run.

    Returns a summary (peer_sets_seen, baselines_written,
    errors).
    """
    cur_now = now or datetime.now(timezone.utc)
    ym = _year_month(cur_now)

    # Distinct peer-set tuples from PLUTO. We don't use
    # aggregate() so the test stub stays simple — distinct() is
    # supported by motor and works fine.
    cursor = db[NYC_PLUTO_COLLECTION].find(
        {}, {"borough": 1, "bldgclass": 1, "landuse": 1},
    )
    seen_keys = set()
    summary = {
        "peer_sets_seen": 0,
        "baselines_written": 0,
        "errors": 0,
    }
    async for doc in cursor:
        key = (
            doc.get("borough"),
            doc.get("bldgclass"),
            doc.get("landuse"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        summary["peer_sets_seen"] += 1
        try:
            baseline = await compute_baseline_for_peer_set(
                db,
                borough=key[0],
                project_class=key[1],
                use_type=key[2],
                year_month=ym,
                now=cur_now,
            )
            if await upsert_baseline(db, baseline):
                summary["baselines_written"] += 1
        except Exception as e:
            summary["errors"] += 1
            logger.warning(
                f"[baselines] peer set {key} failed: {e!r}",
            )
        if max_peer_sets is not None and \
                summary["peer_sets_seen"] >= max_peer_sets:
            break
    logger.info(f"[baselines] aggregator complete: {summary}")
    return summary


# ── Compare-to-peer ───────────────────────────────────────────────


async def compare_project_to_peers(
    db,
    project: Dict[str, Any],
    *,
    lookback_days: int = 365 * 2,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """For a given project, compute its peer-set, count the
    project's own events over the lookback window, and report
    where the project sits relative to peer median / percentiles.

    Returns:
      {
        "peer_set":     {tier, borough, project_class, use_type,
                         sample_size},
        "violations":  {project_count, peer_median, peer_p75,
                        percentile_rank},
        "inspections": same shape,
        "complaints":  same shape,
      }
    """
    cur_now = now or datetime.now(timezone.utc)
    since = cur_now - timedelta(days=lookback_days)
    # V2.2.4 Path A: BBL-keyed throughout. The project's own BBL
    # comes from `bbl` / `nyc_bbl` (existing canonical fields on
    # the project doc) — same fallback chain used elsewhere in
    # the codebase.
    bbls, peer_meta = await peer_bbls(db, project)
    project_bbl = project.get("bbl") or project.get("nyc_bbl")

    out: Dict[str, Any] = {"peer_set": peer_meta}
    for label, coll in (
        ("violations",  NYC_VIOLATIONS_COLLECTION),
        ("inspections", NYC_INSPECTIONS_COLLECTION),
        ("complaints",  NYC_COMPLAINTS_311_COLLECTION),
    ):
        # Peer counts (excluding the project's own BBL so the
        # comparison is "us vs. peers", not "us vs. (peers + us)").
        peer_bbl_list = [b for b in bbls if b != project_bbl]
        peer_counts = await _count_events_for_bbls(
            db, coll, peer_bbl_list, since=since,
        )
        peer_summary = _summarize_counts(peer_counts)
        # Project's own count.
        proj_count = 0
        if project_bbl:
            cursor = db[coll].find({
                "bbl": project_bbl,
                "occurred_date": {"$gte": since},
            }, {"bbl": 1})
            async for _doc in cursor:
                proj_count += 1
        # Percentile rank of project among peers.
        sorted_peers = sorted(peer_counts.values())
        rank = 0
        for v in sorted_peers:
            if v <= proj_count:
                rank += 1
        percentile = (
            (rank / len(sorted_peers)) * 100
            if sorted_peers else 0.0
        )
        out[label] = {
            "project_count":    proj_count,
            "peer_median":      peer_summary["median"],
            "peer_p75":         peer_summary["p75"],
            "peer_p90":         peer_summary["p90"],
            "percentile_rank":  percentile,
            "peer_sample_size": int(peer_summary["n"]),
        }
    return out
