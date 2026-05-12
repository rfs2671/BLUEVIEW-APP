"""Phase V2.3 — Lazy peer-comparison engine.

V2.2 used a local Mongo mirror (``nyc_pluto`` + ``nyc_violations``
+ ``nyc_inspections`` + ``nyc_complaints_311``) with a nightly
``statistical_baselines`` pre-aggregation cron. V2.3 throws away
both: peer stats are now computed lazily against the live Socrata
API at score-recompute time, then cached on the project document
itself with a 14-day staleness window.

Per-project lifecycle:

  1. New project — ``peer_stats_cache`` field is absent.
  2. First risk-score compute calls ``compare_project_to_peers``
     which detects the missing cache, runs
     ``compute_peer_stats_full`` (PLUTO peer-set discovery + 3
     event-dataset queries with the project's peer BBLs), persists
     the resulting cache back to ``db.projects``, and returns the
     comparison.
  3. Subsequent computes within 14 days read the cache directly —
     no Socrata roundtrips.
  4. After 14 days, the cache is stale. ``compare_project_to_peers``
     returns the cached values immediately and (in Commit 5) fires
     a background ``refresh_peer_stats_incremental``. Commit 3
     ships the refresh function but does NOT schedule it — Commit
     5 wires the staleness-driven scheduler.

Critical fall-back: the synchronous on-demand compute is wrapped
in ``asyncio.wait_for(..., 5s)``. On timeout OR ``SocrataQueryError``
the function returns a zero-peer marker with a ``reason`` field so
the score doesn't bomb. The next recompute will retry.

PUBLIC SURFACE PRESERVED FROM V2.2:

  • ``peer_bbls(socrata, project)`` — fallback ladder PLUTO query.
    Now lazy-Socrata-backed. Signature added ``socrata`` first arg
    in place of ``db`` (PLUTO is no longer mirrored locally).

  • ``compare_project_to_peers(db, project, *, socrata=None, ...)``
    — same return shape as V2.2. ``db`` is preserved as first
    arg because the function still reads + writes ``db.projects``
    for cache persistence. ``socrata`` is keyword-optional so
    callers that don't have a SocrataClient handy can pass None
    and the function constructs one inline.

NEW IN V2.3:

  • ``compute_peer_stats_full`` — first-compute aggregation.
    Returns a ``peer_stats_cache`` dict ready to persist on the
    project doc.

  • ``refresh_peer_stats_incremental`` — 14-day delta refresh.
    Same peer BBL list (no PLUTO re-query); pulls only events
    in [last_refreshed_at, now], adds to cached per-BBL counts,
    drops events older than the 2-year window, recomputes
    summary stats.

  • ``count_own_building_events(socrata, *, bin_, since, until=None)``
    — project-specific own-building counts (violations, failed
    inspections, open complaints). Used by ``score.gather_score_inputs``.

DELETED in V2.3 Commit 3 (the V2.2 baseline-aggregator cron was
removed in Commit 1; these helpers wrote to the now-dropped
``statistical_baselines`` collection):

  • ``compute_baseline_for_peer_set``
  • ``upsert_baseline``
  • ``run_baseline_aggregator``
  • ``_year_month``
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from lib.server_http import ServerHttpClient
from lib.statistical_engine.schema import MIN_PEER_SAMPLE_SIZE
from lib.statistical_engine.socrata_client import (
    DATASET_COMPLAINTS_311,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_VIOLATIONS,
    DATASET_PLUTO,
    SocrataClient,
    SocrataQueryError,
)
from lib.statistical_engine.utils import normalize_bbl

logger = logging.getLogger(__name__)


# ── Cache tuning constants ────────────────────────────────────────

# How many days a fully-computed cache stays "fresh" before
# compare_project_to_peers treats it as stale. After this the cache
# is still returned (we don't block the user on a refresh) but the
# Commit 5 scheduler will fire an incremental refresh.
PEER_STATS_FRESH_DAYS = 14

# How long a ``status="failed"`` marker suppresses retry attempts
# from the synchronous compute path in ``compare_project_to_peers``.
# Within this window, returning the zero-peer marker avoids burning
# Socrata quota retrying a query that just failed. After the
# window elapses, the next sync compute call attempts a retry —
# this is the V2.3 Commit 4 "24h retry escape hatch" so permanently-
# stuck projects aren't permanently broken.
PEER_STATS_FAILED_RETRY_TTL_HOURS = 24

# Lookback window for the event datasets. Same 2-year span the V2.2
# aggregator used so percentile distributions are comparable.
PEER_STATS_LOOKBACK_DAYS = 365 * 2

# Hard wall-clock cap on the on-demand-compute fallback. If
# Socrata is misbehaving we'd rather return a zero-peer marker
# than freeze the score endpoint.
PEER_STATS_COMPUTE_TIMEOUT_SECONDS = 5.0

# Socrata page size used by peer-event queries. Tuned to one round
# trip for typical Manhattan peer sets (~500 BBLs × ~5 events/BBL
# over 2 years = ~2500 rows, well under page_size).
PEER_STATS_PAGE_SIZE = 5000

# Maximum peer-BBL list size we shove into a single
# ``bbl IN (...)`` clause. Socrata's URL-length limit truncates
# requests at ~2000 chars; ~250 11-char BBLs + delimiters keeps us
# safely under that. Larger peer sets are chunked across multiple
# queries and unioned.
SOQL_IN_CHUNK_SIZE = 250


# ── Peer-set key construction (pure logic, untouched from V2.2) ───


def _project_peer_key(project: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Extract the canonical peer-set key from a project doc.

    Borough comes from project.borough or PLUTO-fallback via BBL.
    project_class is the operator-set classification
    (regular / major_a / major_b). use_type is the PLUTO
    ``landuse`` or ``bldgclass`` field — for now we use whichever
    is present.
    """
    return {
        "borough":       project.get("borough") or _bin_borough_fallback(project),
        "project_class": project.get("project_class") or "regular",
        "use_type":      project.get("use_type") or project.get("landuse"),
    }


def _bin_borough_fallback(project: Dict[str, Any]) -> Optional[str]:
    """Derive borough from BBL when the project doc doesn't carry
    an explicit borough. BBL is 10 chars: first char is borough
    (1-5)."""
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


# ── SoQL helpers ──────────────────────────────────────────────────


def _soql_quote(value: str) -> str:
    """Wrap a value in single quotes and escape internal quotes for
    SoQL inclusion. The Socrata datasets we query don't contain
    single quotes in any of our peer-key fields (borough names are
    uppercase, project_class is an enum, landuse codes are short
    strings), but defensive escaping costs nothing and prevents a
    future field from breaking the WHERE clause."""
    return "'" + str(value).replace("'", "''") + "'"


def _soql_in(field: str, values: List[str]) -> str:
    """Build ``field IN ('v1','v2',...)`` from a Python list."""
    if not values:
        # Socrata rejects ``IN ()`` as a syntax error. Caller should
        # short-circuit before invoking this, but guard anyway.
        return f"{field} IN ('')"
    quoted = ",".join(_soql_quote(v) for v in values)
    return f"{field} IN ({quoted})"


def _chunk(seq: List[str], n: int) -> List[List[str]]:
    """Split a list into chunks of up to n items."""
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def _iso_z(dt: datetime) -> str:
    """Format a datetime in the ISO-8601-Z form Socrata's floating-
    timestamp columns accept on the right-hand side of a comparator
    (e.g. ``occurred_date > '2024-05-08T00:00:00'``).
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ── Peer set fallback ladder (rewritten — lazy PLUTO via Socrata) ─


async def _bbls_matching_socrata(
    socrata: SocrataClient,
    *,
    borough: Optional[str] = None,
    bldgclass: Optional[str] = None,
    landuse: Optional[str] = None,
) -> List[str]:
    """Query Socrata PLUTO (64uk-42ks) for BBLs matching the
    supplied filters. None = unconstrained on that axis.

    PLUTO is a snapshot dataset (re-released quarterly); a single
    Socrata query returns the current full set for our peer-key
    filters. We page just in case the borough-only fallback tier
    returns >5000 BBLs.

    Returns the normalized 10-char canonical BBL list. PLUTO's
    Socrata payload ships ``bbl`` values with a ``.00000000``
    decimal suffix (e.g. ``"4061730023.00000000"``); the
    canonicalizer strips that via ``normalize_bbl``.
    """
    where_parts: List[str] = []
    if borough is not None:
        where_parts.append(f"borough = {_soql_quote(borough)}")
    if bldgclass is not None:
        where_parts.append(f"bldgclass = {_soql_quote(bldgclass)}")
    if landuse is not None:
        where_parts.append(f"landuse = {_soql_quote(landuse)}")
    where = " AND ".join(where_parts) if where_parts else None

    try:
        rows = await socrata.query_all(
            DATASET_PLUTO,
            where=where,
            select=["bbl"],
            page_size=PEER_STATS_PAGE_SIZE,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[baselines] PLUTO peer fetch failed: %r", e,
        )
        return []

    out: List[str] = []
    for r in rows:
        normalized = normalize_bbl(r.get("bbl"))
        if normalized:
            out.append(normalized)
    return out


async def peer_bbls(
    socrata: SocrataClient,
    project: Dict[str, Any],
) -> Tuple[List[str], Dict[str, Any]]:
    """Resolve the peer BBL list for a project, applying the
    fallback ladder if the most-specific peer set is below
    ``MIN_PEER_SAMPLE_SIZE`` (20).

    V2.3 signature change: takes ``SocrataClient`` instead of
    ``db`` (PLUTO is no longer mirrored locally).

    Returns (bbls, metadata). metadata describes which tier was
    used and the sample size — surfaced by
    ``compare_project_to_peers`` so the FE drawer can disclose
    "Compared against N projects in [borough]".
    """
    key = _project_peer_key(project)
    borough = key.get("borough")
    project_class = key.get("project_class")
    use_type = key.get("use_type")

    # Tier 1: borough × class × use_type.
    bbls = await _bbls_matching_socrata(
        socrata,
        borough=borough, bldgclass=project_class, landuse=use_type,
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
    bbls = await _bbls_matching_socrata(
        socrata, borough=borough, bldgclass=project_class,
    )
    if len(bbls) >= MIN_PEER_SAMPLE_SIZE:
        return bbls, {
            "tier": "borough_class",
            "borough": borough,
            "project_class": project_class,
            "sample_size": len(bbls),
        }

    # Tier 3: borough (drop class).
    bbls = await _bbls_matching_socrata(socrata, borough=borough)
    if len(bbls) >= MIN_PEER_SAMPLE_SIZE:
        return bbls, {
            "tier": "borough",
            "borough": borough,
            "sample_size": len(bbls),
        }

    # Tier 4: citywide (no filters).
    bbls = await _bbls_matching_socrata(socrata)
    return bbls, {
        "tier": "citywide",
        "sample_size": len(bbls),
    }


# ── Per-BBL event counts (rewritten — lazy Socrata, chunked IN) ───


# Per-dataset SoQL column name for the canonical event date.
# Socrata column names are not consistent across the 3 datasets
# we query for peer/own-building events — pre-V2.3 the local
# mirror canonicalized them to ``occurred_date`` at write time;
# without the mirror we now reference each source's actual column.
_DATE_FIELDS = {
    DATASET_DOB_VIOLATIONS:  "issue_date",
    DATASET_DOB_INSPECTIONS: "inspection_date",
    DATASET_COMPLAINTS_311:  "created_date",
}


async def _count_events_for_bbls_socrata(
    socrata: SocrataClient,
    dataset_id: str,
    bbls: List[str],
    *,
    since: datetime,
    until: Optional[datetime] = None,
) -> Dict[str, int]:
    """Return ``{bbl: count}`` for every BBL in ``bbls`` over the
    ``[since, until)`` window. BBLs with zero matching events are
    included (count=0) so percentile math stays correct.

    Implementation: ``$select=bbl,count(*) $group=bbl`` per chunk.
    BBLs that don't appear in the response have count=0 (Socrata
    omits empty groups). Chunked across the IN-list because
    Socrata URL length tops out around 2KB; we batch ~250 BBLs
    per call.
    """
    if not bbls:
        return {}
    date_col = _DATE_FIELDS.get(dataset_id, "occurred_date")
    where_date = f"{date_col} > {_soql_quote(_iso_z(since))}"
    if until is not None:
        where_date += f" AND {date_col} < {_soql_quote(_iso_z(until))}"

    counts: Dict[str, int] = {b: 0 for b in bbls}

    for chunk in _chunk(bbls, SOQL_IN_CHUNK_SIZE):
        where = f"{_soql_in('bbl', chunk)} AND {where_date}"
        try:
            rows = await socrata.query_all(
                dataset_id,
                where=where,
                select=["bbl", "count(*) AS n"],
                group="bbl",
                page_size=PEER_STATS_PAGE_SIZE,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[baselines] event count for %s failed: %r", dataset_id, e,
            )
            # Partial-failure tolerance: zero-fill the chunk, keep
            # going on the next. Better to under-report one chunk
            # than blank the whole peer summary.
            continue
        for r in rows:
            b = normalize_bbl(r.get("bbl"))
            if not b or b not in counts:
                continue
            # Socrata returns count() as a string. Be defensive
            # against future format changes (e.g. typed JSON).
            n_raw = r.get("n") or r.get("count_bbl") or r.get("count")
            try:
                counts[b] = int(float(n_raw))
            except (TypeError, ValueError):
                counts[b] = 0
    return counts


# ── Summary stat helpers (pure math, untouched from V2.2) ─────────


def _percentile(sorted_values: List[float], pct: float) -> float:
    """Nearest-rank percentile. pct in [0, 100]. Empty list → 0."""
    if not sorted_values:
        return 0.0
    if pct <= 0:
        return float(sorted_values[0])
    if pct >= 100:
        return float(sorted_values[-1])
    k = max(0, min(len(sorted_values) - 1,
                   int(round((pct / 100.0) * (len(sorted_values) - 1)))))
    return float(sorted_values[k])


def _summarize_counts(counts_by_key: Dict[str, int]) -> Dict[str, float]:
    """Reduce a ``{key: count}`` map to summary stats (n, mean,
    median, p75, p90, p95, max)."""
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


def _percentile_rank(sorted_peer_counts: List[int], project_count: int) -> float:
    """Project's percentile rank among sorted peer counts. Standard
    "≤-rank" definition: fraction of peers whose count is ≤ the
    project's count, scaled to 0-100."""
    if not sorted_peer_counts:
        return 0.0
    rank = sum(1 for v in sorted_peer_counts if v <= project_count)
    return (rank / len(sorted_peer_counts)) * 100.0


# ── Full peer-stats compute (first-time aggregation) ──────────────


async def compute_peer_stats_full(
    socrata: SocrataClient,
    project: Dict[str, Any],
    *,
    lookback_days: int = PEER_STATS_LOOKBACK_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """First-time peer-stats aggregation for a project. Returns a
    fully-populated ``peer_stats_cache`` dict ready to persist on
    the project doc.

    Cost: 1 PLUTO query for peer-BBL discovery (with up to 3 more
    if the fallback ladder kicks in) + 3 event-dataset queries
    (chunked for large peer sets). Expected wall-clock for a
    typical Manhattan peer set: 500ms-2s.

    Raises ``SocrataQueryError`` only if a query exhausts retries
    AND the caller didn't already wrap us in a timeout — most
    failure modes are tolerated internally (returning zero counts
    for the affected dataset) so a single bad shard doesn't blank
    the whole cache.
    """
    cur_now = now or datetime.now(timezone.utc)
    window_start = cur_now - timedelta(days=lookback_days)

    bbls, peer_meta = await peer_bbls(socrata, project)
    project_bbl = normalize_bbl(project.get("bbl") or project.get("nyc_bbl"))

    # Exclude the project's own BBL from the peer count so the
    # comparison is "us vs. peers", not "us vs. (peers + us)".
    peer_bbl_list = [b for b in bbls if b and b != project_bbl]

    # Pull the three event counts in parallel — independent
    # Socrata calls, no need to serialize.
    v_task = _count_events_for_bbls_socrata(
        socrata, DATASET_DOB_VIOLATIONS, peer_bbl_list,
        since=window_start, until=cur_now,
    )
    i_task = _count_events_for_bbls_socrata(
        socrata, DATASET_DOB_INSPECTIONS, peer_bbl_list,
        since=window_start, until=cur_now,
    )
    c_task = _count_events_for_bbls_socrata(
        socrata, DATASET_COMPLAINTS_311, peer_bbl_list,
        since=window_start, until=cur_now,
    )
    v_counts, i_counts, c_counts = await asyncio.gather(
        v_task, i_task, c_task,
    )

    # Project's own counts in the same window (1 query per dataset,
    # filtered by BBL = own).
    proj_v, proj_i, proj_c = 0, 0, 0
    if project_bbl:
        own_counts = await asyncio.gather(
            _count_events_for_bbls_socrata(
                socrata, DATASET_DOB_VIOLATIONS, [project_bbl],
                since=window_start, until=cur_now,
            ),
            _count_events_for_bbls_socrata(
                socrata, DATASET_DOB_INSPECTIONS, [project_bbl],
                since=window_start, until=cur_now,
            ),
            _count_events_for_bbls_socrata(
                socrata, DATASET_COMPLAINTS_311, [project_bbl],
                since=window_start, until=cur_now,
            ),
        )
        proj_v = own_counts[0].get(project_bbl, 0)
        proj_i = own_counts[1].get(project_bbl, 0)
        proj_c = own_counts[2].get(project_bbl, 0)

    return _assemble_cache(
        peer_meta=peer_meta,
        project_bbl=project_bbl,
        peer_bbl_list=peer_bbl_list,
        v_counts=v_counts, i_counts=i_counts, c_counts=c_counts,
        project_counts=(proj_v, proj_i, proj_c),
        window_start=window_start,
        window_end=cur_now,
        computed_at=cur_now,
        last_refreshed_at=cur_now,
    )


def _assemble_cache(
    *,
    peer_meta: Dict[str, Any],
    project_bbl: Optional[str],
    peer_bbl_list: List[str],
    v_counts: Dict[str, int],
    i_counts: Dict[str, int],
    c_counts: Dict[str, int],
    project_counts: Tuple[int, int, int],
    window_start: datetime,
    window_end: datetime,
    computed_at: datetime,
    last_refreshed_at: datetime,
) -> Dict[str, Any]:
    """Build the ``peer_stats_cache`` dict from raw counts. Shared
    by full-compute and incremental-refresh so the persisted shape
    stays identical."""
    proj_v, proj_i, proj_c = project_counts

    def _one(counts: Dict[str, int], project_count: int) -> Dict[str, Any]:
        summary = _summarize_counts(counts)
        sorted_vals = sorted(counts.values())
        return {
            **summary,
            "project_count":    int(project_count),
            "percentile_rank":  _percentile_rank(sorted_vals, project_count),
        }

    tier_to_fallback_level = {
        "borough_class_use": 1,
        "borough_class":     2,
        "borough":           3,
        "citywide":          4,
    }

    return {
        "computed_at":       computed_at,
        "last_refreshed_at": last_refreshed_at,
        "peer_criteria": {
            "borough":         peer_meta.get("borough"),
            "project_class":   peer_meta.get("project_class"),
            "use_type":        peer_meta.get("use_type"),
            "bbl":             project_bbl,
            "sample_size":     len(peer_bbl_list),
            "fallback_level":  tier_to_fallback_level.get(
                peer_meta.get("tier"), 4,
            ),
            "tier":            peer_meta.get("tier"),
            # Persist the BBL list so incremental refresh can reuse
            # it without re-running the PLUTO peer-discovery query.
            "peer_bbl_list":   peer_bbl_list,
            # Persist per-BBL counts so incremental refresh can
            # add-then-evict events in the sliding window without
            # re-fetching the full lookback.
            "_peer_counts_by_dataset": {
                DATASET_DOB_VIOLATIONS:  dict(v_counts),
                DATASET_DOB_INSPECTIONS: dict(i_counts),
                DATASET_COMPLAINTS_311:  dict(c_counts),
            },
        },
        "events_window_start": window_start,
        "events_window_end":   window_end,
        "violations":          _one(v_counts, proj_v),
        "inspections":         _one(i_counts, proj_i),
        "complaints":          _one(c_counts, proj_c),
        "status":              "ready",
        "error_message":       None,
    }


# ── Incremental refresh (14-day delta) ────────────────────────────


async def refresh_peer_stats_incremental(
    socrata: SocrataClient,
    project: Dict[str, Any],
    *,
    lookback_days: int = PEER_STATS_LOOKBACK_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Incrementally refresh a project's ``peer_stats_cache``.

    Strategy:
      1. Reuse the cached peer BBL list — peer set is stable
         enough over 14 days that re-running PLUTO would be wasted
         work. (Annual PLUTO releases + this refresh's call site
         being driven by a 14-day stagger means the worst-case
         drift is small.)
      2. Pull new events in ``[last_refreshed_at, now]`` for each
         dataset matching the cached peer BBLs.
      3. Add those counts to the cached per-BBL counts.
      4. Drop events older than (now - lookback_days). Since the
         cache only persists counts, not individual events, we
         can't precisely evict old events — instead we re-pull
         counts for the FULL lookback for any BBL whose count
         changed. (Cheap because we're only re-querying the small
         set of BBLs that gained new events.) See
         ``_evict_aged_out_for_changed_bbls`` for the math.
      5. Recompute summary stats from updated counts.
      6. Bump ``last_refreshed_at``; ``computed_at`` is preserved
         so the FE can show "first computed N days ago".

    If the cached peer-BBL list is missing or empty (cache was
    written by a non-V2.3 code path), this function falls back to
    a full recompute via ``compute_peer_stats_full``.
    """
    cur_now = now or datetime.now(timezone.utc)
    cache = project.get("peer_stats_cache") or {}
    criteria = cache.get("peer_criteria") or {}
    cached_bbls = criteria.get("peer_bbl_list") or []
    cached_counts = criteria.get("_peer_counts_by_dataset") or {}
    last_refreshed_at = cache.get("last_refreshed_at")

    if not cached_bbls or not last_refreshed_at or not cached_counts:
        # Cache doesn't carry the data we need to do a delta
        # refresh — fall back to a full recompute.
        return await compute_peer_stats_full(
            socrata, project, lookback_days=lookback_days, now=cur_now,
        )

    window_start = cur_now - timedelta(days=lookback_days)
    project_bbl = normalize_bbl(project.get("bbl") or project.get("nyc_bbl"))

    async def _delta_for(dataset_id: str) -> Dict[str, int]:
        """Add new events since last refresh, then re-pull full
        counts for any BBL whose count changed (so events that
        aged out of the lookback window get evicted)."""
        current = dict(cached_counts.get(dataset_id, {}))

        # Step A: pull new events since last_refreshed_at.
        new_counts = await _count_events_for_bbls_socrata(
            socrata, dataset_id, cached_bbls,
            since=last_refreshed_at, until=cur_now,
        )
        changed_bbls = [b for b, n in new_counts.items() if n > 0]

        # Step B: for BBLs that gained new events, re-pull their
        # full lookback count so we naturally drop events that
        # aged out the other end of the window.
        if changed_bbls:
            refreshed = await _count_events_for_bbls_socrata(
                socrata, dataset_id, changed_bbls,
                since=window_start, until=cur_now,
            )
            for b in changed_bbls:
                # refreshed already reflects [window_start, now] so
                # it replaces (not adds-to) the stored count.
                current[b] = refreshed.get(b, 0)

        # Ensure every cached BBL has a key (zero-fill is required
        # for correct percentile math).
        for b in cached_bbls:
            current.setdefault(b, 0)
        return current

    v_counts, i_counts, c_counts = await asyncio.gather(
        _delta_for(DATASET_DOB_VIOLATIONS),
        _delta_for(DATASET_DOB_INSPECTIONS),
        _delta_for(DATASET_COMPLAINTS_311),
    )

    # Project's own counts — re-pull the full lookback since the
    # window slid.
    proj_v, proj_i, proj_c = 0, 0, 0
    if project_bbl:
        own = await asyncio.gather(
            _count_events_for_bbls_socrata(
                socrata, DATASET_DOB_VIOLATIONS, [project_bbl],
                since=window_start, until=cur_now,
            ),
            _count_events_for_bbls_socrata(
                socrata, DATASET_DOB_INSPECTIONS, [project_bbl],
                since=window_start, until=cur_now,
            ),
            _count_events_for_bbls_socrata(
                socrata, DATASET_COMPLAINTS_311, [project_bbl],
                since=window_start, until=cur_now,
            ),
        )
        proj_v = own[0].get(project_bbl, 0)
        proj_i = own[1].get(project_bbl, 0)
        proj_c = own[2].get(project_bbl, 0)

    # Reuse the existing peer_meta + criteria.tier + sample_size
    # — the peer set didn't change, only the events did.
    peer_meta = {
        "tier":           criteria.get("tier"),
        "borough":        criteria.get("borough"),
        "project_class":  criteria.get("project_class"),
        "use_type":       criteria.get("use_type"),
        "sample_size":    criteria.get("sample_size") or len(cached_bbls),
    }

    return _assemble_cache(
        peer_meta=peer_meta,
        project_bbl=project_bbl,
        peer_bbl_list=cached_bbls,
        v_counts=v_counts, i_counts=i_counts, c_counts=c_counts,
        project_counts=(proj_v, proj_i, proj_c),
        window_start=window_start,
        window_end=cur_now,
        computed_at=cache.get("computed_at") or cur_now,
        last_refreshed_at=cur_now,
    )


# ── Own-building event counter (used by score.py) ─────────────────


async def count_own_building_events(
    socrata: SocrataClient,
    *,
    bin_: Optional[str],
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Project-specific own-building counts. Replaces the three
    direct ``db[NYC_*_COLLECTION].find()`` calls score.py made in
    V2.2.

    Returns the same shape ``score.gather_score_inputs`` builds
    today:

      {
        "violations_30d":         int,
        "violations_90d":         int,
        "inspections_failed_60d": int,
        "open_complaints_30d":    int,
      }

    Empty ``bin_`` → all zeros. Socrata query failures soft-fail
    per-dataset (zero for the affected key, others still
    populated). This preserves the V2.2 behavior of degrading
    gracefully on partial-data outages.
    """
    out = {
        "violations_30d":         0,
        "violations_90d":         0,
        "inspections_failed_60d": 0,
        "open_complaints_30d":    0,
    }
    if not bin_:
        return out
    cur_now = now or datetime.now(timezone.utc)
    c30 = cur_now - timedelta(days=30)
    c60 = cur_now - timedelta(days=60)
    c90 = cur_now - timedelta(days=90)

    bin_q = _soql_quote(str(bin_))

    # Violations — last 90 days, then split into 30d / 90d.
    try:
        rows = await socrata.query_all(
            DATASET_DOB_VIOLATIONS,
            where=(
                f"bin = {bin_q} AND issue_date > "
                f"{_soql_quote(_iso_z(c90))}"
            ),
            select=["issue_date"],
            page_size=PEER_STATS_PAGE_SIZE,
        )
        for r in rows:
            occ_raw = r.get("issue_date")
            occ = _parse_socrata_dt(occ_raw)
            if occ is None:
                continue
            if occ >= c30:
                out["violations_30d"] += 1
            if occ >= c90:
                out["violations_90d"] += 1
    except SocrataQueryError as e:
        logger.warning("[baselines] own violations failed: %r", e)

    # Failed inspections — last 60 days. Socrata column is `result`
    # on p937-wjvj; we substring-match "fail" or "violation" to
    # preserve V2.2 semantics.
    try:
        rows = await socrata.query_all(
            DATASET_DOB_INSPECTIONS,
            where=(
                f"bin = {bin_q} AND inspection_date > "
                f"{_soql_quote(_iso_z(c60))}"
            ),
            select=["result"],
            page_size=PEER_STATS_PAGE_SIZE,
        )
        for r in rows:
            res = (r.get("result") or "").lower()
            if "fail" in res or "violation" in res:
                out["inspections_failed_60d"] += 1
    except SocrataQueryError as e:
        logger.warning("[baselines] own inspections failed: %r", e)

    # Open 311 — last 30 days, status != "closed".
    try:
        rows = await socrata.query_all(
            DATASET_COMPLAINTS_311,
            where=(
                f"bin = {bin_q} AND created_date > "
                f"{_soql_quote(_iso_z(c30))}"
            ),
            select=["status"],
            page_size=PEER_STATS_PAGE_SIZE,
        )
        for r in rows:
            status = (r.get("status") or "").lower()
            if status != "closed":
                out["open_complaints_30d"] += 1
    except SocrataQueryError as e:
        logger.warning("[baselines] own 311 failed: %r", e)

    return out


def _parse_socrata_dt(value: Any) -> Optional[datetime]:
    """Parse a Socrata floating-timestamp value into a tz-aware
    UTC datetime. Handles both string ISO-8601 (the default JSON
    serialization) and pre-parsed datetime objects (in case the
    httpx layer ever auto-converts)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        # Socrata floating timestamps look like "2024-05-08T00:00:00.000"
        # (no offset). Treat as UTC for our windowing purposes.
        s = value.rstrip("Z")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


# ── Compare-to-peer (cache-aware) ─────────────────────────────────


def _is_cache_stale(
    cache: Dict[str, Any],
    *,
    now: datetime,
    fresh_days: int = PEER_STATS_FRESH_DAYS,
) -> bool:
    """True if ``last_refreshed_at`` is more than ``fresh_days``
    in the past. Cache without a ``last_refreshed_at`` is treated
    as stale (defensive)."""
    ts = cache.get("last_refreshed_at")
    if not isinstance(ts, datetime):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts) > timedelta(days=fresh_days)


def _zero_peer_marker(reason: str) -> Dict[str, Any]:
    """Return shape compatible with V2.2 ``compare_project_to_peers``
    that produces 0 for the peer subscore. ``reason`` is surfaced
    to logs + (eventually) the admin diagnostics endpoint."""
    zero = {
        "project_count":     0,
        "peer_median":       0.0,
        "peer_p75":          0.0,
        "peer_p90":          0.0,
        "percentile_rank":   0.0,
        "peer_sample_size":  0,
    }
    return {
        "peer_set":      {"sample_size": 0, "reason": reason},
        "violations":    dict(zero),
        "inspections":   dict(zero),
        "complaints":    dict(zero),
    }


def _v22_shape_from_cache(cache: Dict[str, Any]) -> Dict[str, Any]:
    """Project the V2.3 cache shape onto the V2.2
    ``compare_project_to_peers`` return shape so score.py reads
    the same keys. The internal cache carries extras (per-BBL
    counts, peer_bbl_list, etc.) that the score consumer doesn't
    need; we strip them here.

    Tier-conditional ``peer_set`` emission for byte-for-byte
    parity with V2.2: ``peer_bbls()`` historically omitted keys
    that didn't apply at the resolved tier (tier-3 emits no
    ``project_class`` / ``use_type``; tier-4 emits only ``tier``
    + ``sample_size``). Mirroring that here so existing
    consumers — including any FE drawer that walks the dict —
    don't see phantom ``None``-valued fields they wouldn't have
    seen pre-V2.3.

    The integer ``fallback_level`` (1-4, populated by
    ``_assemble_cache``) drives the conditional. The output
    ``peer_set["tier"]`` is the V2.2 string (``"borough_class_use"``
    etc.) for value parity.
    """
    criteria = cache.get("peer_criteria") or {}
    level = criteria.get("fallback_level") or 4

    peer_set: Dict[str, Any] = {
        "tier":        criteria.get("tier"),
        "sample_size": criteria.get("sample_size") or 0,
    }
    if level in (1, 2, 3):  # tiers 1-3 are borough-scoped
        peer_set["borough"] = criteria.get("borough")
    if level in (1, 2):  # tiers 1-2 carry project_class
        peer_set["project_class"] = criteria.get("project_class")
    if level == 1:  # only tier 1 carries use_type
        peer_set["use_type"] = criteria.get("use_type")

    out: Dict[str, Any] = {"peer_set": peer_set}
    for key in ("violations", "inspections", "complaints"):
        dataset_summary = cache.get(key) or {}
        out[key] = {
            "project_count":    int(dataset_summary.get("project_count") or 0),
            "peer_median":      float(dataset_summary.get("median") or 0.0),
            "peer_p75":         float(dataset_summary.get("p75") or 0.0),
            "peer_p90":         float(dataset_summary.get("p90") or 0.0),
            "percentile_rank":  float(dataset_summary.get("percentile_rank") or 0.0),
            "peer_sample_size": int(dataset_summary.get("n") or 0),
        }
    return out


async def _persist_cache(db, project: Dict[str, Any], cache: Dict[str, Any]) -> None:
    """Write ``peer_stats_cache`` back to ``db.projects``. Tolerant
    of missing _id (defensive — a project without _id won't show up
    in the projects collection anyway). Errors are logged but
    don't fail the caller — the cache will be recomputed next
    time."""
    project_id = project.get("_id") or project.get("id")
    if not project_id:
        return
    try:
        await db.projects.update_one(
            {"_id": project_id},
            {"$set": {"peer_stats_cache": cache}},
        )
    except Exception as e:
        logger.warning(
            "[baselines] persist peer_stats_cache failed for %s: %r",
            project_id, e,
        )


async def compare_project_to_peers(
    db,
    project: Dict[str, Any],
    *,
    socrata: Optional[SocrataClient] = None,
    lookback_days: int = PEER_STATS_LOOKBACK_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """V2.3 cache-aware peer comparison.

    Decision tree:
      1. Cache + ``status == "ready"`` → return cached values
         immediately. Hot path: zero Socrata calls. (Staleness
         beyond 14 days is currently still served from cache;
         Commit 5 wires a background refresh.)
      2. Cache + ``status == "pending"`` → V2.3 Commit 4: a
         ``prewarm_peer_stats`` task is in flight. Return the
         zero-peer marker with ``reason="pending"`` to avoid
         racing the background task with a synchronous compute
         that would write the same data twice.
      3. Cache + ``status == "failed"`` → V2.3 Commit 4:
            - if ``failed_at`` is within the last 24 hours,
              return the zero-peer marker with
              ``reason="failed"`` (don't burn Socrata quota
              re-running the same failing query).
            - if ``failed_at`` is older than 24 hours (the retry
              escape hatch), fall through to the synchronous
              compute path for a retry. Prevents permanently-
              stuck projects from being permanently broken.
            - if ``failed_at`` is missing (defensive — a
              malformed cache or pre-Commit-4 failed marker),
              return the zero-peer marker (better safe than
              quota-burning).
      4. Cache absent → synchronous on-demand compute, wrapped
         in ``asyncio.wait_for(..., 5s)``. Persist the result to
         ``db.projects``. On timeout or Socrata failure, return
         a zero-peer marker with a ``reason``.

    Return shape is the same as V2.2 ``compare_project_to_peers``
    so ``score.py`` consumes it unchanged.
    """
    cur_now = now or datetime.now(timezone.utc)
    cache = project.get("peer_stats_cache")

    if cache:
        status = cache.get("status")
        if status == "ready":
            # Cache hit — fresh or stale, we still serve from it.
            return _v22_shape_from_cache(cache)
        if status == "pending":
            # V2.3 Commit 4: background prewarm in flight. Don't
            # race it — return zero-peer marker; the next score
            # recompute (after prewarm completes) will hit the
            # ready branch above.
            return _zero_peer_marker("pending")
        if status == "failed":
            # V2.3 Commit 4: 24-hour retry escape hatch. Within
            # the window, surface the failed state without
            # retrying. Past the window, fall through to sync
            # compute as a retry attempt.
            failed_at = cache.get("failed_at")
            if isinstance(failed_at, datetime):
                if failed_at.tzinfo is None:
                    failed_at = failed_at.replace(tzinfo=timezone.utc)
                age = cur_now - failed_at
                if age < timedelta(hours=PEER_STATS_FAILED_RETRY_TTL_HOURS):
                    return _zero_peer_marker("failed")
                # else: past the TTL → fall through to sync retry
                logger.info(
                    "[baselines] peer_stats for %s failed %.1fh "
                    "ago; retrying via sync compute",
                    project.get("_id"), age.total_seconds() / 3600,
                )
            else:
                # No failed_at timestamp — defensive: don't retry
                # without knowing when the failure happened.
                return _zero_peer_marker("failed")

    # Cache absent OR (status=="failed" past the 24h TTL) → do
    # the synchronous compute.
    inline_http: Optional[ServerHttpClient] = None
    try:
        if socrata is None:
            inline_http = ServerHttpClient(timeout=10.0)
            await inline_http.__aenter__()
            socrata = SocrataClient(inline_http)

        try:
            new_cache = await asyncio.wait_for(
                compute_peer_stats_full(
                    socrata, project,
                    lookback_days=lookback_days, now=cur_now,
                ),
                timeout=PEER_STATS_COMPUTE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[baselines] peer_stats compute timed out for %s",
                project.get("_id"),
            )
            return _zero_peer_marker("timeout")
        except SocrataQueryError as e:
            logger.warning(
                "[baselines] peer_stats compute failed for %s: %r",
                project.get("_id"), e,
            )
            return _zero_peer_marker("socrata_error")

        # Persist back to db.projects so next call hits the cache.
        await _persist_cache(db, project, new_cache)
        return _v22_shape_from_cache(new_cache)
    finally:
        if inline_http is not None:
            await inline_http.__aexit__(None, None, None)
