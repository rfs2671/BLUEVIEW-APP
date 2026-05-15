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
in ``asyncio.wait_for(..., PEER_STATS_COMPUTE_TIMEOUT_SECONDS)``
(30s, matching PREWARM_TIMEOUT_SECONDS). On timeout OR
``SocrataQueryError`` the function returns a zero-peer marker
with a ``reason`` field so the score doesn't bomb. The next
recompute will retry.

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

  • ``count_own_building_events(*, bin_, bbl=None, project_id, db, now=None)``
    — project-specific own-building counts (violations, failed
    inspections, open complaints). Used by
    ``score.gather_score_inputs``. V2.3.A2: pivots from lazy
    Socrata queries to a 4-facet Mongo aggregate against
    db.dob_logs (legacy-poller-populated, covers the full DOB
    dataset list). ``project_id`` + ``db`` are now required.

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
    DATASET_DOB_PERMITS,
    DATASET_DOB_VIOLATIONS,
    DATASET_PLUTO,
    SocrataClient,
    SocrataQueryError,
)
from lib.statistical_engine.utils import normalize_bbl

# PR #14B: cohort-aware peer comparison. The cohort spec
# (lib.statistical_engine.cohort_config) and the DOB classifier
# (lib.statistical_engine.dob_classifier) are imported lazily
# below — they pull in transitively-imported modules (e.g.
# dob_now_parser) and we want to keep this file's import surface
# small.
from lib.statistical_engine.cohort_config import (
    COHORT_CONFIG,
    compute_tolerance_band,
)
from lib.statistical_engine.dob_classifier import (
    DATASET_BIS_JOB_FILINGS,
    DATASET_C_OF_O_LEGACY,
)

logger = logging.getLogger(__name__)


# ── Cache tuning constants ────────────────────────────────────────

# How many days a fully-computed cache stays "fresh" before
# compare_project_to_peers treats it as stale. After this the cache
# is still returned (we don't block the user on a refresh) but the
# Commit 5 scheduler will fire an incremental refresh.
PEER_STATS_FRESH_DAYS = 14

# PR #14B: how many days a cohort cache (the materialized
# cohort_job_numbers + cohort_filter_spec) stays valid before
# refresh_cron.py treats it as stale. Same value as
# PEER_STATS_FRESH_DAYS but named distinctly so future tuning can
# diverge.
PEER_STATS_COHORT_TTL_DAYS = 14

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
# than freeze the score endpoint. Matches PREWARM_TIMEOUT_SECONDS
# (prewarm.py) so sync + async compute budgets stay aligned —
# lazy peer-set discovery does 1 PLUTO + 3 event-dataset queries
# (chunked), realistically 3-10s in prod and occasionally longer
# under load.
PEER_STATS_COMPUTE_TIMEOUT_SECONDS = 30.0

# Socrata page size used by peer-event queries. Tuned to one round
# trip for typical Manhattan peer sets (~500 BBLs × ~5 events/BBL
# over 2 years = ~2500 rows, well under page_size).
PEER_STATS_PAGE_SIZE = 5000

# Datasets that cannot participate in BBL-keyed peer comparison
# under the V2.3 schema. dob_violations (3h2n-5cm9) ships no
# ``bbl`` column on the public Socrata schema; peer-aggregating
# its events would require N-per-BBL boro+block+lot lookups
# (deferred to a follow-up). When a dataset is in this set,
# ``_assemble_cache`` emits a degenerate cache entry of shape
# ``{"available": False, ...}`` instead of zero-filled
# percentile data — score.py's peer normalizer skips
# unavailable dimensions instead of averaging in a pinned
# value, which would systematically bias the peer subscore.
UNAVAILABLE_PEER_DATASETS = {DATASET_DOB_VIOLATIONS}

# Marker stored on every unavailable peer-cache entry so future
# engineers can grep for the PR that introduced the gate.
_PEER_DATA_DROPPED_TAG = "v2.3-schema-corrections-hotfix"
_VIOLATIONS_UNAVAILABLE_REASON = (
    "bbl_keyed_peer_set_incompatible_with_bin_keyed_dataset"
)

# Maximum peer-BBL list size we shove into a single
# ``bbl IN (...)`` clause. Socrata's URL-length limit truncates
# requests at ~2000 chars; ~250 11-char BBLs + delimiters keeps us
# safely under that. Larger peer sets are chunked across multiple
# queries and unioned.
SOQL_IN_CHUNK_SIZE = 250

# Per-tier hard caps on PLUTO peer-set discovery. Each tier
# fetches a single bounded page — we never ``query_all`` PLUTO
# from any tier, because paginating returns sets too large for
# downstream chunked event-count queries to complete inside the
# sync 30s timeout. Verified in prod against Bronx (tier 3 alone
# returns ~90k BBLs unbounded; the event-count chunking phase
# then times out long before the citywide tier-4 cap is ever
# reached).
#
# Rationale for the per-tier values:
#   • Tier 1 (borough × class × use_type) — narrowest filter,
#     real-world peer sets rarely exceed a few hundred. 5k is
#     a generous ceiling against unusual borough/class mixes.
#   • Tier 2 (borough × class) — drops use_type, sets grow.
#   • Tier 3 (borough only) — broad; Bronx is ~90k BBLs, so the
#     cap is the only thing keeping prod alive.
#   • Tier 4 (citywide, unfiltered) — ~858k BBLs.
#
# Tunable per future production observation.
TIER_1_MAX_PEERS = 5000
TIER_2_MAX_PEERS = 7500
TIER_3_MAX_PEERS = 10000
TIER_4_MAX_PEERS = 10000

# Backward-compat alias preserved so the V2.3 schema-corrections
# hotfix tests + any callers that imported the old name continue
# to resolve. Equivalent to TIER_4_MAX_PEERS.
CITYWIDE_TIER_MAX_PEERS = TIER_4_MAX_PEERS

# PR #14B: full PLUTO column set the snapshot persists. The
# pre-PR-14B set was just (bbl, borough, bldgclass, landuse,
# block, lot); PR #14 added zipcode; PR #14B adds 7 more for
# cohort-aware peer comparison:
#
#   • cd          — community district (tier-2 geography ladder)
#   • yearbuilt   — vintage filter, not currently in cohort spec
#                   but persisted for forward compat
#   • unitsres    — residential unit count (cohort
#                   dwelling_units_band axis for new_building)
#   • unitstotal  — total unit count (used by minor_alt
#                   building-class proxies)
#   • numfloors   — story count (cohort story_count_band axis)
#   • bldgarea    — building floor area
#   • lotarea     — lot area
#
# Verified against the live 64uk-42ks schema (PLUTO 24v3.1
# release) — every column above is present and queryable.
PLUTO_SELECT_FIELDS = [
    "bbl", "borough", "bldgclass", "landuse", "block", "lot",
    "zipcode",
    "cd", "yearbuilt", "unitsres", "unitstotal", "numfloors",
    "bldgarea", "lotarea",
]

# PR #14B: PLUTO snapshot is considered "complete" only when the
# 7 new fields are populated. A pre-PR-14B snapshot (lacking
# any of these) triggers a lazy refresh from
# compute_cohort_for_project. Risk 7 lock: skip the refresh for
# full_demo projects — their pluto_snapshot is FROZEN at
# project-create time to preserve pre-demolition attributes.
_PLUTO_PR14B_REQUIRED_FIELDS = (
    "cd", "yearbuilt", "unitsres", "unitstotal", "numfloors",
    "bldgarea", "lotarea",
)

# PLUTO uses 2-letter borough codes, not the upper-case full
# names Blueview stores on projects. Map at query construction
# time so the project's stored format (UPPER full name) survives
# unchanged.
_PLUTO_BOROUGH_CODE = {
    "MANHATTAN":     "MN",
    "BRONX":         "BX",
    "BROOKLYN":      "BK",
    "QUEENS":        "QN",
    "STATEN ISLAND": "SI",
}

def _pluto_borough(stored: Optional[str]) -> Optional[str]:
    """Translate Blueview's stored borough ("BROOKLYN") to PLUTO's
    2-letter code ("BK"). Returns None for unknown inputs so the
    caller can drop the filter rather than send a malformed query.
    """
    if not stored:
        return None
    return _PLUTO_BOROUGH_CODE.get(stored.strip().upper())


# DOB inspections borough translation lives in triggers.py
# (_inspection_boro_code) since that's where the borough-sweep
# query is built. Not used in baselines.py — the peer queries
# here go through PLUTO + inspections-by-BBL paths that don't
# need it.


def _yyyymmdd(dt: datetime) -> str:
    """Format a datetime as YYYYMMDD (no separators), the format
    dob_violations (3h2n-5cm9) uses for ``issue_date``. Distinct
    from ``_iso_prefix`` which produces ISO-8601 for the 311 +
    inspections datasets.
    """
    return dt.strftime("%Y%m%d")


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


def _iso_prefix(dt: datetime) -> str:
    """Format a datetime as the ISO-8601 prefix Socrata's floating-
    timestamp columns AND dob_logs's ISO-stored fields accept on
    the right-hand side of a comparator (e.g.
    ``created_date > '2024-05-08T00:00:00'``).

    Renamed from ``_iso_z`` (V2.3.A2): no ``Z`` suffix exists in
    the actual stored values (verified against dob_logs
    complaint_date + inspection_date and Socrata floating-timestamp
    convention). The previous name implied UTC-Zulu suffix which
    misled callers. Format string is unchanged."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ── Peer set fallback ladder (rewritten — lazy PLUTO via Socrata) ─


async def fetch_project_pluto_snapshot(
    socrata: SocrataClient,
    project: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Fetch the project's own row from PLUTO (64uk-42ks) keyed by
    its BBL. Returns the raw row (with ``bbl`` already normalized
    to strip the ``.00000000`` suffix), or None if no PLUTO row
    matches.

    Used by ``peer_bbls`` to discover the project's REAL NYC DOF
    building-class code (``bldgclass``, e.g. "C1"/"R6"/"S2"/"O4")
    so tier-1/tier-2 peer queries filter on the same vocabulary
    PLUTO actually stores. Without this we were passing through
    Blueview's internal ``project_class`` ("regular"/"major_a"),
    which PLUTO has no notion of — so every tier-1/tier-2 query
    returned 0 peers.

    Caller should cache the result on the project doc
    (``pluto_snapshot`` field) so repeat recomputes don't re-pay
    the round trip.
    """
    project_bbl = normalize_bbl(project.get("bbl") or project.get("nyc_bbl"))
    if not project_bbl:
        return None
    try:
        rows = await socrata.query(
            DATASET_PLUTO,
            where=f"bbl = {_soql_quote(project_bbl)}",
            # PLUTO (64uk-42ks) does NOT carry a ``bin`` column —
            # listing ``bin`` in $select returns HTTP 400 from
            # Socrata. Only request columns the dataset actually
            # exposes. (The project's BIN, if known, lives on the
            # Blueview project doc already; PLUTO is queried purely
            # for DOF building-class + landuse.)
            # PR #14B: the PLUTO snapshot now backs cohort-aware
            # peer comparison (zipcode for tier-1 geography, cd for
            # tier-2, plus structural attributes for tolerance-band
            # matching). All 14 fields below are validated against
            # the live PLUTO 64uk-42ks schema.
            select=PLUTO_SELECT_FIELDS,
            limit=1,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[baselines] PLUTO snapshot fetch for %s failed: %r",
            project_bbl, e,
        )
        return None
    if not rows:
        return None
    row = dict(rows[0])
    normalized = normalize_bbl(row.get("bbl"))
    if normalized:
        row["bbl"] = normalized
    return row


async def _bbls_matching_socrata(
    socrata: SocrataClient,
    *,
    borough: Optional[str] = None,  # already in PLUTO 2-letter form
    bldgclass: Optional[str] = None,
    landuse: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[str]:
    """Query Socrata PLUTO (64uk-42ks) for BBLs matching the
    supplied filters. None = unconstrained on that axis.

    PLUTO column conventions (verified against live Socrata API):
      • ``borough`` is a 2-letter code (``MN``/``BX``/``BK``/``QN``/
        ``SI``). The caller must pre-translate Blueview's stored
        UPPER-case full name via ``_pluto_borough``.
      • ``bldgclass`` is the NYC DOF building-class code (e.g.
        ``"C1"``, ``"R6"``, ``"S2"``, ``"O4"``). Callers must pass
        the project's REAL DOF class (from its PLUTO snapshot),
        NOT Blueview's internal ``project_class`` enum.
      • ``bbl`` values ship with a ``.00000000`` decimal suffix
        that ``normalize_bbl`` strips below.

    If ``limit`` is provided we issue a single bounded ``query()``
    instead of paginating — used by the tier-4 citywide fallback
    to cap at ``CITYWIDE_TIER_MAX_PEERS`` rather than walk the
    full ~858k-parcel city.
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
        if limit is not None:
            # Tier-4 citywide path: one bounded GET, no pagination.
            rows = await socrata.query(
                DATASET_PLUTO,
                where=where,
                select=["bbl"],
                limit=limit,
            )
        else:
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

    Schema-corrections hotfix:
      • PLUTO ``borough`` is a 2-letter code (``MN``/``BK``/...).
        Translate the project's stored UPPER-case full name via
        ``_pluto_borough`` before filtering.
      • PLUTO ``bldgclass`` is the NYC DOF building-class code,
        NOT Blueview's internal ``project_class`` enum. Fetch
        the project's own PLUTO row to discover its real
        ``bldgclass`` (cached at ``project["pluto_snapshot"]``
        if previously fetched) and filter on THAT in tiers 1-2.
      • Tier 4 (citywide) is capped at
        ``CITYWIDE_TIER_MAX_PEERS`` — paginating the whole NYC
        parcel set under the 30s sync timeout always times out.

    Returns (bbls, metadata). metadata describes which tier was
    used and the sample size — surfaced by
    ``compare_project_to_peers`` so the FE drawer can disclose
    "Compared against N projects in [borough]". The metadata
    additionally carries ``pluto_snapshot`` when one was
    discovered or reused, so the caller can persist it on the
    project doc and skip the snapshot fetch on next compute.
    """
    key = _project_peer_key(project)
    borough_stored = key.get("borough")
    borough_pluto = _pluto_borough(borough_stored)
    use_type = key.get("use_type")

    # Discover the project's REAL DOF building class for
    # tier-1/tier-2 peer queries. Read from cached snapshot if
    # present (set by a prior recompute); otherwise fetch lazily
    # and surface it back so the caller can persist.
    snapshot: Optional[Dict[str, Any]] = project.get("pluto_snapshot")
    if not snapshot:
        snapshot = await fetch_project_pluto_snapshot(socrata, project)
    dof_bldgclass = (snapshot or {}).get("bldgclass")
    snapshot_landuse = (snapshot or {}).get("landuse")
    effective_use_type = use_type or snapshot_landuse

    # Every tier passes ``limit=`` so PLUTO returns a single
    # bounded page — never ``query_all``. Without these caps the
    # tier-3 query alone (Bronx, ~90k BBLs) paginates long enough
    # that the downstream chunked event-count phase exhausts the
    # 30s sync timeout. Verified in prod hotfix #3.

    # Tier 1: borough × class × use_type. Requires both a
    # PLUTO-format borough code AND a real DOF bldgclass; if
    # either is missing we skip directly to a coarser tier.
    if borough_pluto and dof_bldgclass:
        bbls = await _bbls_matching_socrata(
            socrata,
            borough=borough_pluto,
            bldgclass=dof_bldgclass,
            landuse=effective_use_type,
            limit=TIER_1_MAX_PEERS,
        )
        if len(bbls) >= MIN_PEER_SAMPLE_SIZE:
            return bbls, {
                "tier": "borough_class_use",
                "borough": borough_stored,
                "project_class": dof_bldgclass,
                "use_type": effective_use_type,
                "sample_size": len(bbls),
                "pluto_snapshot": snapshot,
            }

    # Tier 2: borough × class (drop use_type).
    if borough_pluto and dof_bldgclass:
        bbls = await _bbls_matching_socrata(
            socrata,
            borough=borough_pluto,
            bldgclass=dof_bldgclass,
            limit=TIER_2_MAX_PEERS,
        )
        if len(bbls) >= MIN_PEER_SAMPLE_SIZE:
            return bbls, {
                "tier": "borough_class",
                "borough": borough_stored,
                "project_class": dof_bldgclass,
                "sample_size": len(bbls),
                "pluto_snapshot": snapshot,
            }

    # Tier 3: borough (drop class). The Bronx alone has ~90k
    # parcels — without TIER_3_MAX_PEERS the downstream chunked
    # event-count queries time out.
    if borough_pluto:
        bbls = await _bbls_matching_socrata(
            socrata,
            borough=borough_pluto,
            limit=TIER_3_MAX_PEERS,
        )
        if len(bbls) >= MIN_PEER_SAMPLE_SIZE:
            return bbls, {
                "tier": "borough",
                "borough": borough_stored,
                "sample_size": len(bbls),
                "pluto_snapshot": snapshot,
            }

    # Tier 4: citywide (no filters). The full ~858k-parcel scan
    # always exhausts the sync 30s timeout in prod without this
    # cap (verified during PR #4 production rollout).
    bbls = await _bbls_matching_socrata(
        socrata, limit=TIER_4_MAX_PEERS,
    )
    return bbls, {
        "tier": "citywide",
        "sample_size": len(bbls),
        "pluto_snapshot": snapshot,
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

    Schema-corrections hotfix: only datasets that actually carry
    a ``bbl`` column may be queried here (inspections + 311).
    DOB violations (3h2n-5cm9) does NOT ship ``bbl`` and is
    therefore EXCLUDED from peer counts — defensively bail and
    return zero-fill if a caller accidentally passes it.
    Violations remain available via own-building queries (which
    filter by ``bin``); peer-aggregated violations would require
    N-per-BBL boro+block+lot lookups, deferred to a follow-up.

    Implementation: ``$select=bbl,count(*) $group=bbl`` per chunk.
    BBLs that don't appear in the response have count=0 (Socrata
    omits empty groups). Chunked across the IN-list because
    Socrata URL length tops out around 2KB; we batch ~250 BBLs
    per call.
    """
    if not bbls:
        return {}
    if dataset_id == DATASET_DOB_VIOLATIONS:
        # DOB violations has no ``bbl`` column on the public
        # Socrata schema — filtering by bbl returns zero rows
        # regardless of input. Zero-fill so percentile math
        # stays correct, and don't burn a quota request.
        logger.info(
            "[baselines] skipping peer-violations aggregation "
            "(3h2n-5cm9 has no bbl column; see schema-corrections "
            "hotfix Option A)",
        )
        return {b: 0 for b in bbls}

    date_col = _DATE_FIELDS.get(dataset_id, "occurred_date")
    where_date = f"{date_col} > {_soql_quote(_iso_prefix(since))}"
    if until is not None:
        where_date += f" AND {date_col} < {_soql_quote(_iso_prefix(until))}"

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
    stays identical.

    Schema-corrections hotfix: datasets in ``UNAVAILABLE_PEER_DATASETS``
    cannot participate in BBL-keyed peer comparison under the V2.3
    schema. Their per-dataset entry emits a degenerate
    ``{"available": False, ...}`` shape (no percentile_rank, no
    project_count) instead of zero-filled stats. score.py's peer
    normalizer skips entries marked unavailable so the peer
    subscore isn't biased by a pinned percentile_rank.
    """
    proj_v, proj_i, proj_c = project_counts

    def _one_available(
        counts: Dict[str, int], project_count: int,
    ) -> Dict[str, Any]:
        """Build the full V2.3 per-dataset entry. Wrapped with
        ``available: True`` so consumers don't have to default."""
        summary = _summarize_counts(counts)
        sorted_vals = sorted(counts.values())
        return {
            "available":        True,
            **summary,
            "project_count":    int(project_count),
            "percentile_rank":  _percentile_rank(sorted_vals, project_count),
        }

    def _one_unavailable(reason: str) -> Dict[str, Any]:
        """Build the degenerate per-dataset entry for a gated
        dataset. No percentile_rank, no project_count — score.py
        skips entries flagged unavailable."""
        return {
            "available":               False,
            "unavailable_reason":      reason,
            "peer_data_dropped_in_pr": _PEER_DATA_DROPPED_TAG,
        }

    def _one_for(
        dataset_id: str,
        counts: Dict[str, int],
        project_count: int,
    ) -> Dict[str, Any]:
        if dataset_id in UNAVAILABLE_PEER_DATASETS:
            return _one_unavailable(_VIOLATIONS_UNAVAILABLE_REASON)
        return _one_available(counts, project_count)

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
            # Forward the project's PLUTO row through the cache so
            # _persist_cache can stamp it on the project doc and
            # subsequent recomputes skip the snapshot fetch.
            "pluto_snapshot":  peer_meta.get("pluto_snapshot"),
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
        "violations":          _one_for(DATASET_DOB_VIOLATIONS,  v_counts, proj_v),
        "inspections":         _one_for(DATASET_DOB_INSPECTIONS, i_counts, proj_i),
        "complaints":          _one_for(DATASET_COMPLAINTS_311,  c_counts, proj_c),
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
    *,
    project_id: Optional[str] = None,
    db: Any = None,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Project-specific own-building counts. V2.3.A2: pivots from
    lazy Socrata queries (which polled a subset of the legacy
    poller's dataset list and missed projects whose enforcement
    sits in 855j-jady / 6bgk-3dad / eabe-havv) to a single
    4-facet aggregate against db.dob_logs.

    db.dob_logs is populated every 15 min by
    run_dob_sync_for_project (server.py:15101) → _query_dob_apis
    (server.py:13192) which polls the FULL DOB dataset list:
    855j-jady (DOB NOW Safety), 3h2n-5cm9 (BIS legacy violations),
    6bgk-3dad (ECB/OATH), eabe-havv (DOB complaints), erm2-nwe9
    (311 complaints), p937-wjvj (inspections), plus the permit
    and specialty datasets (CofO, Façade FISP, Boiler, Elevator,
    SWO dedicated). Reading from dob_logs gives us coverage of all
    those sources without re-polling Socrata at score-compute
    time.

    Returns:
      {
        "violations_30d":         int,
        "violations_90d":         int,
        "inspections_failed_60d": int,
        "open_complaints_30d":    int,
      }

    Required kwargs:
      • ``project_id`` — scopes the dob_logs query.
      • ``db`` — the Motor AsyncIOMotorDatabase handle.

    Signature note (V2.3.A2): the V2.2 ``bin_`` + ``bbl`` kwargs
    have been DROPPED. They were specific to the Socrata-query
    construction path that A2 replaced. The dob_logs aggregate
    scopes by ``project_id`` instead — the project's BIN/BBL
    aren't needed because each dob_logs document is already
    project-scoped at write time.

    Schema invariants (locked Stage 1 v3 FINAL, Q1-Q9 + B1):
      • Closed-state set for violations + SWOs: ``["certified",
        "dismissed"]``  (Q1; no "paid" or "resolved" in production).
      • Closed-state set for complaints: ``["Closed", "CLOSED"]``
        (Q2; case-sensitive — both variants appear).
      • Failed-inspection discriminator: ``severity == "Action"``
        (Q3; computed at write time by
        server._determine_severity).
      • ``is_seed_transition: {$ne: True}`` (Q5; defensive — no
        production records carry this flag today but the filter
        protects future ingestion changes).
      • ``violation_date`` is stored YYYYMMDD (Q7); cutoffs
        formatted via ``_yyyymmdd``.
      • ``complaint_date`` + ``inspection_date`` stored ISO with
        millisecond suffix (B1.a, B1.b); cutoffs formatted via
        ``_iso_prefix`` — lexicographic ``$gte`` works because
        the cutoff is a valid string prefix.

    On legacy callers that forgot the project_id+db kwargs, the
    function logs a warning and returns the zero-count shape
    rather than crashing.

    On aggregate exception, same defensive shape — never block
    score compute on a dob_logs query hiccup.
    """
    out = {
        "violations_30d":         0,
        "violations_90d":         0,
        "inspections_failed_60d": 0,
        "open_complaints_30d":    0,
    }
    if not project_id or db is None:
        logger.warning(
            "[baselines] count_own_building_events called without "
            "project_id+db — returning zero counts (legacy caller "
            "or test fixture path)",
        )
        return out

    cur_now = now or datetime.now(timezone.utc)
    c30 = cur_now - timedelta(days=30)
    c60 = cur_now - timedelta(days=60)
    c90 = cur_now - timedelta(days=90)

    # Per-dataset date formats stored on dob_logs:
    #   • violation_date  → YYYYMMDD (3h2n-5cm9, 855j-jady,
    #     6bgk-3dad write through _extract_violation_fields).
    #   • complaint_date  → ISO-prefix "%Y-%m-%dT%H:%M:%S.000"
    #     (eabe-havv + erm2-nwe9).
    #   • inspection_date → ISO-prefix "%Y-%m-%dT%H:%M:%S.000"
    #     (p937-wjvj).
    # Lexicographic $gte works for both — the cutoff is a valid
    # prefix of the stored value.
    v_cut_30 = _yyyymmdd(c30)
    v_cut_90 = _yyyymmdd(c90)
    c_cut_30 = _iso_prefix(c30)
    i_cut_60 = _iso_prefix(c60)

    pipeline = [
        {"$match": {
            "project_id": project_id,
            "is_deleted": {"$ne": True},
            "is_seed_transition": {"$ne": True},
        }},
        {"$facet": {
            "violations_30d": [
                {"$match": {
                    "record_type": {"$in": ["violation", "swo"]},
                    "resolution_state": {"$nin": ["certified", "dismissed"]},
                    "violation_date": {"$gte": v_cut_30},
                }},
                {"$count": "n"},
            ],
            "violations_90d": [
                {"$match": {
                    "record_type": {"$in": ["violation", "swo"]},
                    "resolution_state": {"$nin": ["certified", "dismissed"]},
                    "violation_date": {"$gte": v_cut_90},
                }},
                {"$count": "n"},
            ],
            "inspections_failed_60d": [
                {"$match": {
                    "record_type": "inspection",
                    "severity": "Action",
                    "inspection_date": {"$gte": i_cut_60},
                }},
                {"$count": "n"},
            ],
            "open_complaints_30d": [
                {"$match": {
                    "record_type": "complaint",
                    "complaint_status": {"$nin": ["Closed", "CLOSED"]},
                    "complaint_date": {"$gte": c_cut_30},
                }},
                {"$count": "n"},
            ],
        }},
    ]

    try:
        result = await db.dob_logs.aggregate(pipeline).to_list(length=1)
    except Exception as e:
        logger.warning(
            "[baselines] count_own_building_events aggregate failed "
            "for project %s: %r", project_id, e,
        )
        return out
    if not result:
        return out
    doc = result[0]
    out["violations_30d"]         = _extract_facet_count(doc, "violations_30d")
    out["violations_90d"]         = _extract_facet_count(doc, "violations_90d")
    out["inspections_failed_60d"] = _extract_facet_count(doc, "inspections_failed_60d")
    out["open_complaints_30d"]    = _extract_facet_count(doc, "open_complaints_30d")
    return out


def _extract_facet_count(doc: Dict[str, Any], facet_key: str) -> int:
    """$facet returns each sub-pipeline's result as a list. With
    a terminal ``$count``, that list is either ``[{"n": N}]``
    (match) or ``[]`` (no match). Defensive: any unexpected shape
    collapses to 0 rather than crashing the caller."""
    bucket = doc.get(facet_key) or []
    if not bucket:
        return 0
    try:
        return int(bucket[0].get("n") or 0)
    except (TypeError, ValueError):
        return 0


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


def _parse_socrata_yyyymmdd(value: Any) -> Optional[datetime]:
    """Parse the ``issue_date`` text column from dob_violations
    (3h2n-5cm9), which is a YYYYMMDD string like ``"20171227"``.
    Returns a tz-aware UTC datetime at midnight on that date.

    Pass-through for already-parsed datetimes. Returns None on any
    other shape so date-window arithmetic in the caller can skip
    the row defensively.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime(
            int(s[:4]), int(s[4:6]), int(s[6:8]),
            tzinfo=timezone.utc,
        )
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
    to logs + (eventually) the admin diagnostics endpoint.

    Schema-corrections hotfix: each dataset entry carries
    ``available: True`` (the zero is from a failed compute, NOT
    from the dataset being structurally unavailable). score.py's
    normalizer still includes these in the mean — the all-zero
    percentile_ranks correctly contribute 0 to the peer subscore,
    so the timeout/socrata_error path produces peer_subscore=0
    as intended.
    """
    zero = {
        "available":         True,
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
        # Schema-corrections hotfix: propagate the unavailable
        # signal so score.py's peer normalizer can skip the
        # dimension instead of averaging in a pinned 0.
        # Backward-compat: a missing ``available`` field defaults
        # to True (caches written by pre-hotfix code paths use
        # the legacy "all-fields-present" shape).
        if dataset_summary.get("available", True) is False:
            out[key] = {
                "available":               False,
                "unavailable_reason":      dataset_summary.get(
                    "unavailable_reason",
                ),
                "peer_data_dropped_in_pr": dataset_summary.get(
                    "peer_data_dropped_in_pr",
                ),
            }
        else:
            out[key] = {
                "available":        True,
                "project_count":    int(dataset_summary.get("project_count") or 0),
                "peer_median":      float(dataset_summary.get("median") or 0.0),
                "peer_p75":         float(dataset_summary.get("p75") or 0.0),
                "peer_p90":         float(dataset_summary.get("p90") or 0.0),
                "percentile_rank":  float(dataset_summary.get("percentile_rank") or 0.0),
                "peer_sample_size": int(dataset_summary.get("n") or 0),
            }
    return out


async def _persist_cache(db, project: Dict[str, Any], cache: Dict[str, Any]) -> None:
    """Write ``peer_stats_cache`` back to ``db.projects``, and
    additionally persist ``pluto_snapshot`` if the cache was
    computed against a freshly-discovered snapshot. Tolerant of
    missing _id (defensive — a project without _id won't show up
    in the projects collection anyway). Errors are logged but
    don't fail the caller — the cache will be recomputed next
    time.

    Persisting the PLUTO snapshot back to the project doc avoids
    re-querying PLUTO on every peer_stats recompute — the
    project's own ``bldgclass``/``landuse`` are stable across
    PLUTO releases (quarterly cadence) for any project that hasn't
    been physically reclassified.
    """
    project_id = project.get("_id") or project.get("id")
    if not project_id:
        return
    update: Dict[str, Any] = {"peer_stats_cache": cache}
    snapshot = (cache.get("peer_criteria") or {}).get("pluto_snapshot")
    if snapshot and not project.get("pluto_snapshot"):
        update["pluto_snapshot"] = snapshot
    try:
        await db.projects.update_one(
            {"_id": project_id},
            {"$set": update},
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


# ──────────────────────────────────────────────────────────────────
# PR #14B — cohort-aware peer comparison
# ──────────────────────────────────────────────────────────────────


# Sample-size floors (Stage 2.A T1 lock).
COHORT_HIGH_CONFIDENCE_FLOOR = 100  # N≥100 → high confidence
COHORT_LOW_CONFIDENCE_FLOOR  = 30   # 30≤N<100 → low_confidence flag

# Time windows (Stage 2.A T2 lock).
COHORT_WINDOW_MONTHS_PRIMARY  = 36
COHORT_WINDOW_MONTHS_EXPANDED = 60

# Risk 8 milestone mapping (locked Stage 2.A): observed
# permit/inspection events snap completion_pct to a fixed
# fraction so the lifecycle-normalized percentile doesn't drift
# arbitrarily when expected_duration is poorly calibrated.
_MILESTONE_COMPLETION_PCT = {
    # Highest signal first — Final C of O = project complete.
    "c_of_o_final":          1.00,
    "c_of_o_temporary":      0.90,
    # Major structural milestones.
    "structural":            0.40,
    "superstructure":        0.40,
    "foundation":            0.20,
    "demolition":            0.05,
    "initial_permit_issued": 0.05,
}


# ── Lifecycle helpers (Stage 2.A T2) ──────────────────────────


def _compute_completion_pct(
    t0: datetime,
    now: datetime,
    expected_duration_days: float,
) -> float:
    """Linear time-based completion fraction.

    Returns ``(now - t0) / expected_duration_days`` clamped to
    ``[0.0, 1.0]``. Both inputs must be tz-aware datetimes.

    Uses a 365-day-per-year convention so leap-year boundaries
    don't bias the result: a calendar year of elapsed time always
    counts as 365 days, mirroring the convention used by the
    cohort duration median (which itself averages over many
    multi-year spans and therefore washes out leap-year effects).
    """
    if expected_duration_days <= 0:
        return 0.0
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Year-aware delta: count whole calendar years at 365 days
    # each, plus the residual fraction in actual days. This makes
    # "Jan 1 2024 → Jan 1 2025" = 365 days regardless of 2024's
    # leap-year status.
    if now < t0:
        return 0.0
    full_years = now.year - t0.year
    anniversary = t0.replace(year=t0.year + full_years) if full_years else t0
    if anniversary > now:
        full_years -= 1
        anniversary = t0.replace(year=t0.year + full_years) if full_years else t0
    residual_seconds = (now - anniversary).total_seconds()
    delta_days = full_years * 365.0 + residual_seconds / 86400.0

    pct = delta_days / float(expected_duration_days)
    if pct < 0.0:
        return 0.0
    if pct > 1.0:
        return 1.0
    return pct


def _cohort_duration_median(cohort_records: List[Dict[str, Any]]) -> Optional[float]:
    """Median of ``(c_o_issue_date - permit_issue_date)`` in days
    across a cohort.

    Records that don't carry both dates (or where parsing fails)
    are dropped from the median calculation. Returns ``None`` when
    no records carry a parseable duration — the caller surfaces
    that as ``lifecycle_skip_reason = "no_duration_data"``.
    """
    durations: List[float] = []
    for r in cohort_records or []:
        permit_raw = r.get("permit_issue_date") or r.get("fully_permitted")
        c_of_o_raw = r.get("c_o_issue_date")
        permit_dt = _parse_socrata_dt(permit_raw)
        c_of_o_dt = _parse_socrata_dt(c_of_o_raw)
        if not permit_dt or not c_of_o_dt:
            continue
        delta_days = (c_of_o_dt - permit_dt).total_seconds() / 86400.0
        if delta_days <= 0:
            continue
        durations.append(delta_days)
    if not durations:
        return None
    durations.sort()
    mid = len(durations) // 2
    if len(durations) % 2 == 1:
        return float(durations[mid])
    return float((durations[mid - 1] + durations[mid]) / 2.0)


def _maybe_snap_to_milestone(
    completion_pct: float,
    *,
    observed_milestones: List[str],
) -> float:
    """If any high-confidence milestone is observed, snap
    completion_pct to that milestone's mapped value.

    Per Risk 8 lock: the milestone signal dominates the time-based
    linear estimate. Order of preference: most-recent / highest
    signal wins. ``observed_milestones`` is a list of normalized
    milestone keys (e.g. ``"structural"``, ``"c_of_o_final"``).
    """
    # Iterate the milestone map in declared order — higher-signal
    # milestones are listed first.
    for key, mapped_pct in _MILESTONE_COMPLETION_PCT.items():
        if key in observed_milestones:
            return mapped_pct
    return completion_pct


# ── Cohort filter spec construction ───────────────────────────


def _stored_borough_to_lower(stored: Optional[str]) -> Optional[str]:
    """Translate Blueview's stored borough ("BROOKLYN") to the
    C-of-O legacy dataset's title-case format ("Brooklyn"). Used
    for the completion-filter join (C of O carries title case;
    BIS carries upper case).
    """
    if not stored:
        return None
    return stored.strip().title()


def _build_cohort_filter_spec(
    project: Dict[str, Any],
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """Materialize the cohort filter spec for a project — i.e.
    the concrete values pulled from the project doc + PLUTO
    snapshot that downstream BIS/C-of-O queries will filter on.

    Returns a dict whose keys correspond to ``spec["filter_fields"]``
    plus a ``tolerance_bands`` sub-dict describing the story /
    dwelling-unit windows.
    """
    snapshot = project.get("pluto_snapshot") or {}
    out: Dict[str, Any] = {
        "dob_project_type":  project.get("dob_project_type"),
        "bis_job_types":     sorted(spec.get("bis_job_types") or []),
    }

    filter_fields = spec.get("filter_fields") or []

    # Building class — for full_demo this is the FROZEN
    # pre-demolition class; for other types the current snapshot.
    if "building_class" in filter_fields:
        out["building_class"] = snapshot.get("bldgclass")
    if "building_class_demolished" in filter_fields:
        out["building_class"] = snapshot.get("bldgclass")
        out["building_class_demolished"] = snapshot.get("bldgclass")

    # Story count band — applied when the cohort spec calls for it.
    story_tol = spec.get("story_count_tolerance")
    if "story_count_band" in filter_fields and story_tol:
        try:
            stories = int(snapshot.get("numfloors") or 0)
        except (TypeError, ValueError):
            stories = 0
        if stories > 0:
            pct, min_band = story_tol
            band = compute_tolerance_band(stories, pct, min_band)
            out["story_count_band"] = list(band)
        else:
            out["story_count_band"] = None

    # Demolished story count — full_demo only, uses frozen snapshot.
    story_tol_dm = spec.get("story_count_tolerance")
    if "story_count_demolished" in filter_fields and story_tol_dm:
        try:
            stories = int(snapshot.get("numfloors") or 0)
        except (TypeError, ValueError):
            stories = 0
        if stories > 0:
            pct, min_band = story_tol_dm
            band = compute_tolerance_band(stories, pct, min_band)
            out["story_count_demolished"] = list(band)
        else:
            out["story_count_demolished"] = None

    # Dwelling units band — same shape.
    units_tol = spec.get("dwelling_units_tolerance")
    if "dwelling_units_band" in filter_fields and units_tol:
        try:
            units = int(snapshot.get("unitsres") or snapshot.get("unitstotal") or 0)
        except (TypeError, ValueError):
            units = 0
        if units > 0:
            pct, min_band = units_tol
            band = compute_tolerance_band(units, pct, min_band)
            out["dwelling_units_band"] = list(band)
        else:
            out["dwelling_units_band"] = None

    return out


# ── Geography ladder ──────────────────────────────────────────


def _project_tier_filter_values(
    project: Dict[str, Any],
    tier: str,
) -> Dict[str, Optional[str]]:
    """Return ``{borough, zipcode, cd}`` slices the geography
    ladder needs for the given tier. Each value may be None when
    the project doc lacks it.
    """
    snapshot = project.get("pluto_snapshot") or {}
    borough = project.get("borough") or snapshot.get("borough")
    zipcode = snapshot.get("zipcode") or project.get("zipcode")
    cd = snapshot.get("cd")
    return {
        "borough": borough,
        "zipcode": zipcode,
        "cd":      cd,
    }


def _bis_geography_clause(tier: str, geo: Dict[str, Any]) -> Optional[str]:
    """Build the geography slice of the BIS WHERE clause for a
    given ladder tier.

    NOTE: BIS doesn't ship a ``zipcode`` column on the public
    Socrata schema. For tier 1 + 2 + 3 we therefore use BIS's
    ``borough`` column and rely on the active project's PLUTO
    attributes (bldgclass, numfloors, unitsres) carried via the
    other filter axes. Tier names still reflect the project's own
    geographic attributes for diagnostic clarity, but the
    enforced filter narrows to borough only. A follow-up PR will
    PLUTO-join peers to enforce true zip / cd matching.
    """
    borough = geo.get("borough")
    if not borough:
        return None
    return f"borough = {_soql_quote(borough.upper())}"


# ── BIS / C-of-O queries ──────────────────────────────────────


def _bis_filter_clause(
    spec_values: Dict[str, Any],
    *,
    window_start: datetime,
    window_end: datetime,
) -> str:
    """Build the SoQL WHERE clause for the BIS job-filings query
    matching the cohort filter spec.
    """
    parts: List[str] = []

    job_types = spec_values.get("bis_job_types") or []
    if job_types:
        parts.append(_soql_in("job_type", job_types))

    bclass = spec_values.get("building_class")
    if bclass:
        parts.append(f"building_class = {_soql_quote(bclass)}")

    # Window — pre__filing_date is the BIS "filing initiated"
    # timestamp; we use it as the cohort's anchor date.
    parts.append(
        f"pre__filing_date >= {_soql_quote(_iso_prefix(window_start))}",
    )
    parts.append(
        f"pre__filing_date <= {_soql_quote(_iso_prefix(window_end))}",
    )
    return " AND ".join(parts)


def _row_within_band(
    row: Dict[str, Any],
    field: str,
    band: Optional[List[int]],
) -> bool:
    """Inclusive-on-both-sides band membership test, defensive on
    missing / unparseable values.
    """
    if not band:
        return True
    val_raw = row.get(field)
    if val_raw is None:
        return True
    try:
        val = float(val_raw)
    except (TypeError, ValueError):
        return True
    low, high = band
    return low <= val <= high


def _apply_band_filters(
    rows: List[Dict[str, Any]],
    spec_values: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Filter BIS rows post-hoc by story-count + dwelling-units
    tolerance bands. BIS doesn't carry numfloors directly — we
    use ``total_construction_floor_area`` divided by 1000 as a
    proxy when present (matches the fixture seeder which writes
    ``story_count * 1000`` into that field).
    """
    story_band = spec_values.get("story_count_band")
    if not story_band:
        story_band = spec_values.get("story_count_demolished")
    units_band = spec_values.get("dwelling_units_band")

    if not story_band and not units_band:
        return rows

    kept: List[Dict[str, Any]] = []
    for r in rows:
        if story_band:
            tcfa_raw = r.get("total_construction_floor_area")
            try:
                stories = float(tcfa_raw) / 1000.0 if tcfa_raw else None
            except (TypeError, ValueError):
                stories = None
            if stories is not None and not (
                story_band[0] <= stories <= story_band[1]
            ):
                continue
        if units_band:
            units_raw = r.get("proposed_dwelling_units")
            try:
                units = float(units_raw) if units_raw is not None else None
            except (TypeError, ValueError):
                units = None
            if units is not None and not (
                units_band[0] <= units <= units_band[1]
            ):
                continue
        kept.append(r)
    return kept


async def _fetch_bis_cohort(
    socrata,
    spec_values: Dict[str, Any],
    *,
    tier_clause: Optional[str],
    window_start: datetime,
    window_end: datetime,
) -> List[Dict[str, Any]]:
    """Run the BIS cohort query for a single tier.

    Returns the raw matching BIS rows (with band filters applied).
    """
    parts = [_bis_filter_clause(
        spec_values,
        window_start=window_start,
        window_end=window_end,
    )]
    if tier_clause:
        parts.append(tier_clause)
    where = " AND ".join(p for p in parts if p)
    try:
        rows = await socrata.query(
            DATASET_BIS_JOB_FILINGS,
            where=where,
            limit=10000,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[baselines] BIS cohort fetch failed: %r", e,
        )
        return []
    return _apply_band_filters(rows, spec_values)


async def _enrich_with_c_of_o(
    socrata,
    bis_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str]:
    """Annotate BIS rows with C-of-O Final / Temporary issue dates.

    Returns ``(annotated_rows, completion_method)`` where
    ``completion_method`` is ``"c_of_o_final"`` if at least one row
    found a Final C of O, else ``"job_status_x_or_u"`` (the BIS
    fallback per Risk 6).
    """
    if not bis_rows:
        return bis_rows, "job_status_x_or_u"

    job_numbers = [
        r.get("job__") for r in bis_rows if r.get("job__")
    ]
    if not job_numbers:
        return bis_rows, "job_status_x_or_u"

    c_of_o_by_job: Dict[str, Dict[str, Any]] = {}
    # C of O may have many more rows than IN can hold; chunk it.
    for chunk in _chunk(job_numbers, SOQL_IN_CHUNK_SIZE):
        try:
            rows = await socrata.query(
                DATASET_C_OF_O_LEGACY,
                where=_soql_in("job_number", chunk),
                limit=10000,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[baselines] C of O fetch failed: %r", e,
            )
            continue
        for r in rows:
            jn = r.get("job_number")
            if not jn:
                continue
            # Final beats Temporary; keep the strongest signal.
            existing = c_of_o_by_job.get(jn)
            new_type = (r.get("issue_type") or "").lower()
            if existing is None:
                c_of_o_by_job[jn] = r
            elif new_type == "final" and (
                (existing.get("issue_type") or "").lower() != "final"
            ):
                c_of_o_by_job[jn] = r

    has_any_final = any(
        (r.get("issue_type") or "").lower() == "final"
        for r in c_of_o_by_job.values()
    )

    annotated: List[Dict[str, Any]] = []
    for r in bis_rows:
        jn = r.get("job__")
        c_of_o = c_of_o_by_job.get(jn)
        if c_of_o:
            r = dict(r)
            r["c_o_issue_date"] = c_of_o.get("c_o_issue_date")
            r["c_o_issue_type"] = c_of_o.get("issue_type")
            r["permit_issue_date"] = (
                r.get("fully_permitted") or r.get("pre__filing_date")
            )
        annotated.append(r)

    completion_method = (
        "c_of_o_final" if has_any_final else "job_status_x_or_u"
    )
    return annotated, completion_method


# ── Lazy PLUTO refresh ────────────────────────────────────────


def _pluto_snapshot_needs_refresh(
    snapshot: Optional[Dict[str, Any]],
    *,
    dob_project_type: Optional[str],
) -> bool:
    """True iff the snapshot is missing one or more PR #14B
    fields AND the project is NOT a full_demo (Risk 7 lock —
    full_demo snapshots are FROZEN at project-create time).
    """
    if dob_project_type == "full_demo":
        return False
    if not snapshot:
        return True
    return any(
        snapshot.get(f) in (None, "")
        for f in _PLUTO_PR14B_REQUIRED_FIELDS
    )


async def _ensure_pluto_snapshot_pr14b_complete(
    socrata,
    project: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Refresh ``project["pluto_snapshot"]`` in-place when it's
    missing PR #14B fields. Returns the (possibly-updated)
    snapshot dict — caller should not assume it's not None.
    """
    snapshot = project.get("pluto_snapshot")
    if not _pluto_snapshot_needs_refresh(
        snapshot, dob_project_type=project.get("dob_project_type"),
    ):
        return snapshot
    fresh = await fetch_project_pluto_snapshot(socrata, project)
    if fresh:
        project["pluto_snapshot"] = fresh
        return fresh
    return snapshot


# ── Active-project completion_pct + milestone snapping ────────


async def _active_project_completion_pct(
    socrata,
    project: Dict[str, Any],
    *,
    cohort_median_duration_days: Optional[float],
    now: datetime,
) -> Tuple[Optional[float], List[str]]:
    """Compute the active project's completion_pct.

    Returns ``(completion_pct, observed_milestones)``. The pct is
    None when neither a milestone nor a duration estimate is
    available.
    """
    bin_ = project.get("nyc_bin")
    if not bin_:
        return (None, [])

    observed_milestones: List[str] = []
    try:
        permit_rows = await socrata.query(
            DATASET_DOB_PERMITS,
            where=f"bin = '{bin_}'",
            limit=50,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[baselines] DOB NOW permit fetch failed for milestone "
            "snap (bin=%r): %r", bin_, e,
        )
        permit_rows = []

    earliest_issued: Optional[datetime] = None
    for r in permit_rows:
        work_type = (r.get("work_type") or "").upper()
        permit_status = (r.get("permit_status") or "").upper()
        if "STRUCTURAL" in work_type and permit_status in (
            "ISSUED", "IN PROCESS",
        ):
            observed_milestones.append("structural")
        if "FOUNDATION" in work_type:
            observed_milestones.append("foundation")
        if "DEMOLITION" in work_type:
            observed_milestones.append("demolition")
        if (r.get("filing_reason") or "").upper() == "INITIAL PERMIT":
            observed_milestones.append("initial_permit_issued")
        issued_dt = _parse_socrata_dt(r.get("issued_date"))
        if issued_dt and (
            earliest_issued is None or issued_dt < earliest_issued
        ):
            earliest_issued = issued_dt

    completion_pct: Optional[float] = None
    if earliest_issued and cohort_median_duration_days:
        completion_pct = _compute_completion_pct(
            earliest_issued, now, cohort_median_duration_days,
        )

    if observed_milestones:
        base = completion_pct if completion_pct is not None else 0.0
        completion_pct = _maybe_snap_to_milestone(
            base, observed_milestones=observed_milestones,
        )

    return (completion_pct, observed_milestones)


# ── Top-level cohort builder ──────────────────────────────────


async def compute_cohort_for_project(
    socrata,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """PR #14B — compute the cohort for a project.

    The output is the full Stage 2.A T1/T2 contract:

      {
          "tier_used":                   str,
          "fallback_level":              int (1-4),
          "sample_size":                 int,
          "low_confidence_flag":         bool,
          "window_months":               int (36 or 60),
          "completion_method":           str,
          "cohort_filter_spec":          dict,
          "cohort_job_numbers":          list[str],
          "cohort_median_duration_days": float | None,
          "lifecycle_skip_reason":       str | None,
          "active_project":              {"completion_pct": float|None,
                                          "observed_milestones": list[str]},
      }

    For ``unknown`` project types — or any project type not in
    ``COHORT_CONFIG`` — returns a degenerate result with
    ``sample_size = 0`` and ``lifecycle_skip_reason = "no_spec"``.
    """
    cur_now = now or datetime.now(timezone.utc)
    dob_type = project.get("dob_project_type")
    spec = COHORT_CONFIG.get(dob_type)

    base_result: Dict[str, Any] = {
        "tier_used":                   None,
        "fallback_level":              None,
        "sample_size":                 0,
        "low_confidence_flag":         False,
        "window_months":               COHORT_WINDOW_MONTHS_PRIMARY,
        "completion_method":           None,
        "cohort_filter_spec":          {},
        "cohort_job_numbers":          [],
        "cohort_median_duration_days": None,
        "lifecycle_skip_reason":       None,
        "active_project":              {
            "completion_pct":      None,
            "observed_milestones": [],
        },
    }

    if spec is None:
        base_result["lifecycle_skip_reason"] = "no_spec"
        return base_result

    # PR #14B Risk 7: full_demo snapshots are FROZEN; everyone
    # else gets a lazy refresh when the snapshot is pre-PR-14B.
    await _ensure_pluto_snapshot_pr14b_complete(socrata, project)

    cohort_rows, tier_used, fallback_level, window_months, completion_method, spec_values = (
        await _ladder_search(socrata, project, spec, cur_now)
    )

    # Secondary fallback (major_alt_with_enlargement only).
    secondary = spec.get("secondary_fallback")
    if (
        secondary
        and len(cohort_rows) < secondary.get("trigger_below", 30)
    ):
        expands_to = secondary.get("expands_to")
        expand_spec = COHORT_CONFIG.get(expands_to)
        if expand_spec is not None:
            extra_rows, _, _, _, _, _ = await _ladder_search(
                socrata, project, expand_spec, cur_now,
            )
            # Merge — dedup by job__ so the same BIS row isn't
            # counted twice.
            seen_jobs = {r.get("job__") for r in cohort_rows}
            for r in extra_rows:
                if r.get("job__") not in seen_jobs:
                    cohort_rows.append(r)
                    seen_jobs.add(r.get("job__"))
            spec_values["secondary_fallback_applied"] = True

    # Annotate with C of O for completion-date discovery.
    cohort_rows, completion_method = await _enrich_with_c_of_o(
        socrata, cohort_rows,
    )

    sample_size = len(cohort_rows)
    low_confidence = (
        COHORT_LOW_CONFIDENCE_FLOOR <= sample_size < COHORT_HIGH_CONFIDENCE_FLOOR
    )

    cohort_job_numbers = [
        r.get("job__") for r in cohort_rows if r.get("job__")
    ]

    # Lifecycle median + skip reasons.
    if sample_size == 0:
        cohort_median = None
        lifecycle_skip_reason: Optional[str] = "empty_cohort"
    else:
        cohort_median = _cohort_duration_median(cohort_rows)
        lifecycle_skip_reason = (
            None if cohort_median is not None else "no_duration_data"
        )

    # Active project completion_pct + milestone snap.
    completion_pct, observed_milestones = await _active_project_completion_pct(
        socrata, project,
        cohort_median_duration_days=cohort_median,
        now=cur_now,
    )

    base_result.update({
        "tier_used":                   tier_used,
        "fallback_level":              fallback_level,
        "sample_size":                 sample_size,
        "low_confidence_flag":         low_confidence,
        "window_months":               window_months,
        "completion_method":           completion_method,
        "cohort_filter_spec":          spec_values,
        "cohort_job_numbers":          cohort_job_numbers,
        "cohort_median_duration_days": cohort_median,
        "lifecycle_skip_reason":       lifecycle_skip_reason,
        "active_project": {
            "completion_pct":      completion_pct,
            "observed_milestones": observed_milestones,
        },
    })
    return base_result


async def _ladder_search(
    socrata,
    project: Dict[str, Any],
    spec: Dict[str, Any],
    now: datetime,
) -> Tuple[List[Dict[str, Any]], str, int, int, str, Dict[str, Any]]:
    """Walk the 4-tier geography ladder for the given cohort spec.

    Returns ``(rows, tier_used, fallback_level, window_months,
    completion_method, spec_values)``. ``completion_method`` is
    ``"c_of_o_final"`` if any row found a Final C of O during the
    later enrichment phase — but that enrichment hasn't run yet
    at this point, so this returned value is the BIS default
    ``"job_status_x_or_u"`` and the caller may overwrite it.
    """
    ladder = spec.get("geography_ladder") or []
    spec_values = _build_cohort_filter_spec(project, spec)

    primary_start = now - timedelta(days=30 * COHORT_WINDOW_MONTHS_PRIMARY)
    expanded_start = now - timedelta(days=30 * COHORT_WINDOW_MONTHS_EXPANDED)

    last_rows: List[Dict[str, Any]] = []
    last_tier: str = ladder[-1] if ladder else "borough_type"
    last_level: int = len(ladder) or 4
    used_window_months = COHORT_WINDOW_MONTHS_PRIMARY

    for idx, tier in enumerate(ladder, start=1):
        geo = _project_tier_filter_values(project, tier)
        tier_clause = _bis_geography_clause(tier, geo)
        rows = await _fetch_bis_cohort(
            socrata, spec_values,
            tier_clause=tier_clause,
            window_start=primary_start,
            window_end=now,
        )
        # Expand window 36mo→60mo if primary window underfills.
        if len(rows) < COHORT_HIGH_CONFIDENCE_FLOOR:
            rows_expanded = await _fetch_bis_cohort(
                socrata, spec_values,
                tier_clause=tier_clause,
                window_start=expanded_start,
                window_end=now,
            )
            if len(rows_expanded) > len(rows):
                rows = rows_expanded
                used_window_months = COHORT_WINDOW_MONTHS_EXPANDED

        # Tier passes the floor → stop here.
        if len(rows) >= COHORT_LOW_CONFIDENCE_FLOOR:
            return (
                rows, tier, idx, used_window_months,
                "job_status_x_or_u", spec_values,
            )
        # Remember the last non-empty tier in case nothing beats
        # the floor — we surface that rather than emit an empty
        # result.
        if rows:
            last_rows = rows
            last_tier = tier
            last_level = idx

    return (
        last_rows, last_tier, last_level, used_window_months,
        "job_status_x_or_u", spec_values,
    )
