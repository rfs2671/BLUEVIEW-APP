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
import re
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

# PR #14C schema version stamp (Stage 2.A Q4 Option B + §6.3 lock).
# Every peer_stats_cache written by PR #14C+ code carries
# ``peer_criteria.schema_version == PR14C_SCHEMA_VERSION``.
# compare_project_to_peers treats any cache lacking this value
# OR carrying a different value as a miss → forces recompute
# against the current schema. Belt-and-suspenders with the
# operator's deploy-time ``$unset peer_stats_cache`` migration
# (Q4 Option A): if a stale V2.3 cache slips through the deploy
# window (e.g., a prewarm task that fired between deploy and
# unset), the schema check catches it on the next read.
PR14C_SCHEMA_VERSION = "pr14c"

# PR #14E schema version stamp (Stage 3 §7.3 + Risk 6 lock).
# Unified Cohort architecture flips cohort source from BIS-only
# to Modern (pkdm-hqz6) primary + BIS Legacy fallback. Any cache
# carrying the older ``pr14c`` stamp must be invalidated so the
# new cohort_source_segments / target_state / cohort_member_provenance
# shape gets recomputed. compare_project_to_peers reads this constant
# at read time; deploy is paired with the operator's standard
# ``$unset peer_stats_cache`` migration for belt-and-suspenders.
PR14E_SCHEMA_VERSION = "pr14e"

# PR #14E (Q2 lock) — DOB NOW C of O dataset. The Modern cohort
# source: ships bbl + bin inline (so no PLUTO BIN→BBL bridge
# needed) + job_type + c_of_o_filing_type + c_of_o_issuance_date.
# Schema discovery (Stage 1 Task 1): job_type enum carries BOTH
# casings ("NEW BUILDING" + "New Building" — Risk 3); issuance
# date format is "MM/DD/YY HH:MM:SS AM/PM" with 1+ spaces between
# date and time (§7.7 lock).
DATASET_DOB_C_OF_O = "pkdm-hqz6"

# PR #14E Q7 lock — Modern cohort floor. When _fetch_modern_cohort
# returns fewer than this, _fetch_legacy_cohort is invoked to
# extend; merge dedups by bbl. Threshold is strict-less-than 100
# (exact 100 satisfies, 99 triggers Legacy).
PR14E_MODERN_COHORT_FLOOR = 100

# PR #14E (Q7 lock) — BIS Legacy "Golden Era" window. BIS stopped
# receiving filings 2021+ (transition to DOB NOW). Legacy queries
# restrict pre__filing_date to this window so cohort members are
# both completed AND from the era when BIS was still authoritative.
#
# PR #14F (Stage 10 widening): operator's live Socrata count probe
# showed Brooklyn C1 A1 X/U has 235+236+250+141+243 in 2014-2018
# (peak years) but only 235+134+64+7 from 2018-2021. Widening the
# start from 2018-06-30 → 2016-01-01 captures ~1700 records vs.
# ~440 — pushes Legacy floor reliably above 100 for sparse combos
# while staying within the pre-DOB-NOW authoritative era. End
# boundary stays at 2021-06-30 (BIS post-2021 has <10 records/yr).
PR14E_LEGACY_WINDOW_START_ISO = "2016-01-01"
PR14E_LEGACY_WINDOW_END_ISO = "2021-06-30"

# PR #14E (T4 lock) — Modern cohort window (months back from now).
# pkdm-hqz6 carries filings 2021+; we look back 36 months to match
# the BIS primary cohort window used in PR #14B.
PR14E_MODERN_WINDOW_MONTHS = 36

# PR #14D Q4 lock — cohort_bins are capped at this size before the
# PLUTO BIN→BBL join in compute_peer_stats_full Step 4. Some
# project types (especially minor_alt = BIS A2/A3 union at borough
# scope = ~458K records in Brooklyn) produce 50K-100K row cohorts.
# The PLUTO join chunks across SOQL_IN_CHUNK_SIZE BINs each; even
# parallelized via asyncio.gather (Fix 3), the join cost grows
# linearly with cohort size and would still dominate the 60s
# timeout budget. 500 is a defensible cap — well above the N=100
# high-confidence sample-size floor (so percentile math stays
# stable), small enough to bound PLUTO join cost at 2 chunks.
#
# When the cap fires, a diagnostic marker is emitted:
#   peer_criteria.cohort_truncation = {
#       "applied":       True,
#       "original_size": <pre-truncation length>,
#       "cap":           500,
#   }
# Per §8.5 lock the marker is sparse-by-default — absent when
# cohort_bins ≤ cap.
COHORT_MAX_PEERS_FOR_PLUTO_JOIN = 500

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
#
# PR #14D Fix 4: bumped 30→60s as defensive headroom. Fixes 2+3
# (cohort cap + parallel PLUTO join) make the path much faster
# for normal cases, but Menahan's pre-fix timeout taught us that
# unusual cohort shapes can still strain the budget. Railway
# proxy default is 300s — bump is well within bounds.
PEER_STATS_COMPUTE_TIMEOUT_SECONDS = 60.0

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

# PR #14C Q7 lock — TIER_*_MAX_PEERS constants retired alongside
# the V2.3 4-tier ladder. Cohort population is now derived from
# compute_cohort_for_project (PR #14B) which has its own
# sample-size floor (COHORT_LOW_CONFIDENCE_FLOOR=30) and tier
# advancement logic. Citywide-cap no longer needed because BIS
# filings are pre-narrowed by job_type before the geography
# clause runs.

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


# PR #14C Q7 lock — _project_peer_key + _bin_borough_fallback
# retired. Cohort discovery now reads dob_project_type directly
# from the project doc + PLUTO snapshot (cd, zipcode, bldgclass
# for tier construction) via compute_cohort_for_project.


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
    # PR #14G: PLUTO ships bbl with .00000000 suffix; normalize to
    # plain 10-digit text so downstream consumers comparing against
    # pkdm-hqz6 / BIS bbls don't mis-key.
    normalized = _normalize_pluto_bbl(row.get("bbl"))
    if normalized:
        row["bbl"] = normalized
    return row



# PR #14C Q7 lock — _bbls_matching_socrata retired alongside
# peer_bbls. The active project's PLUTO row is still fetched via
# fetch_project_pluto_snapshot; cohort BIN→BBL resolution uses
# _resolve_bbls_for_cohort_bins (the Q2/T2 batched join).


async def _resolve_bbls_for_cohort_bins(
    socrata: SocrataClient,
    bin_list: List[str],
) -> List[str]:
    """PR #14C — resolve cohort BINs to BBLs via batched PLUTO query.

    PR #14B's ``compute_cohort_for_project`` returns BIS-keyed
    metadata (``cohort_job_numbers`` + ``cohort_bins``) because BIS
    is BIN-indexed. The downstream event-count queries
    (``_count_events_for_bbls_socrata``) are BBL-keyed because the
    inspections + 311 datasets ship a ``bbl`` column but no ``bin``.
    This helper bridges the two via a single batched PLUTO join.

    Per Stage 2.A Q2/T2 lock:
      • Single batched call with ``bin IN (chunk)`` (chunk size
        from ``SOQL_IN_CHUNK_SIZE``, same as event-count chunking).
      • Output deduped, BIN→BBL collisions resolved to first hit.
      • Missing BINs (no PLUTO row) silently dropped.
      • Per-chunk SocrataQueryError logged + skipped; partial
        results returned rather than blanking everything.

    Closes the ``_bis_geography_clause`` TODO from PR #14B.
    """
    if not bin_list:
        return []

    chunks = list(_chunk(bin_list, SOQL_IN_CHUNK_SIZE))

    async def _query_one_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
        try:
            return await socrata.query(
                DATASET_PLUTO,
                where=_soql_in("bin", chunk),
                select=["bbl", "bin"],
                limit=10000,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[baselines] PLUTO BIN→BBL join chunk failed: %r", e,
            )
            return []

    # PR #14D Fix 3: parallelize PLUTO BIN→BBL chunks via
    # asyncio.gather. Pre-PR-14D each chunk fired serially (await
    # inside loop), so wall-clock = N × per-chunk latency. With
    # cohort_max=500 (Fix 2) and SOQL_IN_CHUNK_SIZE=250, that's 2
    # sequential round-trips; parallel collapses to 1 RTT in
    # wall-clock terms. Larger cohorts (pre-cap) saw exponentially
    # worse blow-up — Menahan's pre-cap minor_alt cohort would
    # have fired ~40 serial chunks at 1-2s each = 40-80s, blowing
    # the 30s timeout. Cap + parallel together close the regression.
    chunk_results = await asyncio.gather(
        *(_query_one_chunk(c) for c in chunks),
    )

    # Flatten + dedup. Order across chunks isn't significant for
    # downstream event-count queries (those re-key by BBL and the
    # peer-stats math is order-invariant).
    # PR #14G: PLUTO ships bbl with .00000000 suffix; normalize so
    # downstream BBL-keyed event queries against inspections / 311
    # (which receive plain text bbl from this list) match the
    # un-suffixed bbl format those datasets store.
    bbls_out: List[str] = []
    seen = set()
    for rows in chunk_results:
        for r in rows:
            bbl = _normalize_pluto_bbl(r.get("bbl"))
            if bbl and bbl not in seen:
                bbls_out.append(bbl)
                seen.add(bbl)
    return bbls_out



# PR #14C Q7 lock — peer_bbls retired. Cohort discovery now goes
# through compute_cohort_for_project (PR #14B).


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
    db: Any,
    *,
    lookback_days: int = PEER_STATS_LOOKBACK_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """PR #14C — cohort-aware first-time peer-stats aggregation.

    Wires the PR #14B cohort machinery into the recompute path.
    Replaces the V2.3 4-tier ``peer_bbls()`` ladder (retired per
    Q7 lock) with ``compute_cohort_for_project`` as the cohort
    source.

    Flow:
      1. Lazy PLUTO snapshot refresh (forces 14-field SELECT for
         pre-PR-14B project docs; skipped for full_demo per Risk 7).
      2. Auto-classify ``dob_project_type`` when missing (one-time
         Socrata call to DOB NOW + BIS via the classifier).
      3. Compute cohort via ``compute_cohort_for_project`` —
         returns BIS-keyed metadata (cohort_bins + cohort_job_numbers).
      4. PLUTO BIN→BBL join (Q2/T2) to get BBLs that key the
         event-count queries.
      5. Count peer events on inspections + 311 (violations stays
         gated per V2.3 hotfix — no ``bbl`` column on 3h2n-5cm9).
      6. Count project's own events.
      7. Assemble cache with PR #14B peer_criteria shape +
         schema_version stamp + lifecycle_normalized_percentile=None
         placeholders (Q1 lock; real formula deferred to PR #14D).

    Per Stage 2.A §6.1: ``db`` is a required argument (used by the
    classifier to persist the three ``dob_*`` fields on the project
    doc). All 5 call sites pass it through.

    Empty-cohort handling (Q3): when ``compute_cohort_for_project``
    returns ``sample_size=0`` (e.g., classifier returned 'unknown'),
    the cache is still written with the PR #14B shape + a
    ``cohort_unavailable=True`` sentinel. FE drawer + score
    normalizer use the sentinel to skip percentile display.

    Raises ``SocrataQueryError`` only if a query exhausts retries
    AND the caller didn't already wrap us in a timeout.
    """
    cur_now = now or datetime.now(timezone.utc)
    window_start = cur_now - timedelta(days=lookback_days)
    project_bbl = normalize_bbl(project.get("bbl") or project.get("nyc_bbl"))

    # ── Step 1: lazy PLUTO snapshot refresh ──────────────────────
    snapshot_before = project.get("pluto_snapshot")
    await _ensure_pluto_snapshot_pr14b_complete(socrata, project)
    snapshot_after = project.get("pluto_snapshot")
    pluto_snapshot_refreshed = (
        snapshot_after is not None
        and snapshot_after is not snapshot_before
    )

    # ── Step 2: auto-classify (idempotency guarded here, not in
    #            the classifier — saves a Python call frame on the
    #            hot path) ──────────────────────────────────────
    if not project.get("dob_project_type"):
        # ``maybe_classify_project_dob_type`` is bound at the
        # module bottom via a deferred import (see end of file).
        # Lives in prewarm.py, but importing it here at module top
        # would create a cycle since prewarm.py imports
        # ``compute_peer_stats_full`` from this module.
        try:
            await maybe_classify_project_dob_type(socrata, project, db)
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                "[baselines] auto-classify failed for project=%r: %r",
                project.get("_id"), e,
            )

    # ── Step 2b: PR #14F — always sync dob_extracted_scope from db
    # ──────────────────────────────────────────────────────────
    # PR #14E added a mirror inside ``maybe_classify_project_dob_type``
    # but it only fires when the classifier actually runs (i.e. when
    # ``dob_project_type`` was missing). For projects that were
    # classified in a prior compute (dob_project_type pre-set), the
    # in-memory dict lacked ``dob_extracted_scope`` so
    # ``_derive_target_state_for_project``'s Q5 hybrid would silently
    # fall through to ``pluto_fallback`` instead of using the parser
    # output. Stage 10 mongosh on Menahan reproduced this: parser had
    # already extracted story_count=4 (saved in db) yet target_state.
    # source = "pluto_fallback" / band_widened=True.
    #
    # Fix: always read fresh from db when the field is missing in
    # memory. Cheap (single find_one by _id; same call as the
    # classifier's persist path). Guards against:
    #   • pre-PR-14E persisted scope from old parser
    #   • projects classified in a different process
    #   • test harness shorthand that mutates only some fields
    if "dob_extracted_scope" not in project:
        project_id = project.get("_id") or project.get("id")
        projects_coll = getattr(db, "projects", None) if db else None
        if project_id is not None and projects_coll is not None:
            try:
                fresh = await projects_coll.find_one({"_id": project_id})
                if fresh and "dob_extracted_scope" in fresh:
                    project["dob_extracted_scope"] = fresh.get(
                        "dob_extracted_scope",
                    )
            except Exception:  # pragma: no cover — defensive
                pass

    # ── Step 3: compute cohort ───────────────────────────────────
    cohort_result = await compute_cohort_for_project(
        socrata, project, now=cur_now,
    )

    # ── Step 4: resolve cohort BINs → BBLs for event queries ────
    cohort_bins = cohort_result.get("cohort_bins") or []

    # PR #14D Fix 2 + Q4/T2 lock: cap cohort_bins BEFORE the PLUTO
    # BIN→BBL join. Some project types (notably minor_alt at
    # borough scope) produce 50K-100K BIN cohorts that even after
    # parallelization would dominate the 60s timeout budget. The
    # cap is applied here — after cohort assembly, before the
    # downstream join — so the marker reflects the true
    # pre-truncation size for diagnostics.
    cohort_truncation: Optional[Dict[str, Any]] = None
    if len(cohort_bins) > COHORT_MAX_PEERS_FOR_PLUTO_JOIN:
        cohort_truncation = {
            "applied":       True,
            "original_size": len(cohort_bins),
            "cap":           COHORT_MAX_PEERS_FOR_PLUTO_JOIN,
        }
        cohort_bins = cohort_bins[:COHORT_MAX_PEERS_FOR_PLUTO_JOIN]

    # PR #14E §7.6 lock — Modern cohort rows ship bbl inline from
    # pkdm-hqz6, so we can pull BBLs directly from
    # cohort_member_provenance and skip the BIN→BBL bridge for
    # those rows. Bridge stays in place for Legacy BIS rows
    # (which carry bin only) AND as a final cap-applier (we slice
    # cohort_bins to the cap above).
    provenance_rows = cohort_result.get("cohort_member_provenance") or []
    inline_bbls: List[str] = []
    bridge_bins: List[str] = []
    seen_provenance_bbls: set = set()
    # Trim provenance to the same prefix length as cohort_bins so
    # truncation stays consistent.
    if len(provenance_rows) > COHORT_MAX_PEERS_FOR_PLUTO_JOIN:
        provenance_rows = provenance_rows[:COHORT_MAX_PEERS_FOR_PLUTO_JOIN]
    for entry in provenance_rows:
        bbl_n = normalize_bbl(entry.get("bbl")) if entry.get("bbl") else None
        if bbl_n:
            if bbl_n not in seen_provenance_bbls:
                inline_bbls.append(bbl_n)
                seen_provenance_bbls.add(bbl_n)
        elif entry.get("bin"):
            bridge_bins.append(entry["bin"])

    bridged_bbls: List[str] = []
    if bridge_bins:
        bridged_bbls = await _resolve_bbls_for_cohort_bins(
            socrata, bridge_bins,
        )

    # Combine inline (Modern) + bridged (Legacy) BBLs; dedup.
    peer_bbl_list: List[str] = []
    seen_final: set = set()
    for bbl in list(inline_bbls) + list(bridged_bbls):
        bbl_n = normalize_bbl(bbl)
        if bbl_n and bbl_n not in seen_final:
            peer_bbl_list.append(bbl_n)
            seen_final.add(bbl_n)

    # Fall back to legacy BIN→BBL pathway when provenance is empty
    # (defensive — covers pre-PR-14E cache-recompute scenarios).
    if not peer_bbl_list and cohort_bins:
        peer_bbl_list = await _resolve_bbls_for_cohort_bins(
            socrata, cohort_bins,
        )

    # Strip the project's own BBL so the comparison is
    # "us vs. peers", not "us vs. (peers + us)".
    if project_bbl:
        peer_bbl_list = [
            b for b in peer_bbl_list if normalize_bbl(b) != project_bbl
        ]

    # ── Step 5: count peer events in parallel ───────────────────
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

    # ── Step 6: project's own counts ────────────────────────────
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

    # ── Step 7: build peer_meta from cohort result + assemble ───
    cohort_filter_spec = cohort_result.get("cohort_filter_spec") or {}
    sample_size = cohort_result.get("sample_size", 0) or 0
    peer_meta = {
        # PR #14B keys (Stage 2.A T3 hybrid: full shape + sentinel).
        "dob_project_type": (
            cohort_filter_spec.get("dob_project_type")
            or project.get("dob_project_type")
        ),
        "geography_tier_used":         cohort_result.get("tier_used"),
        "fallback_level":              cohort_result.get("fallback_level"),
        "low_confidence_flag":         cohort_result.get("low_confidence_flag", False),
        "sample_size":                 sample_size,
        "window_months":               cohort_result.get("window_months"),
        "completion_method":           cohort_result.get("completion_method"),
        "cohort_filter_spec":          cohort_filter_spec,
        "cohort_job_numbers":          cohort_result.get("cohort_job_numbers") or [],
        "cohort_bins":                 cohort_bins,
        "cohort_median_duration_days": cohort_result.get("cohort_median_duration_days"),
        "active_project":              cohort_result.get("active_project") or {},
        "lifecycle_skip_reason":       cohort_result.get("lifecycle_skip_reason"),
        # Q3 sentinel — empty cohort gets cohort_unavailable=True.
        "cohort_unavailable":          sample_size == 0,
        # PR #14E §7.3 + Risk 6 — schema version bump from
        # PR14C_SCHEMA_VERSION. compare_project_to_peers invalidates
        # any cache with schema_version != PR14E_SCHEMA_VERSION.
        "schema_version":              PR14E_SCHEMA_VERSION,
        # PR #14E surface additions (Q2 + Q5 + Q7).
        "cohort_source_segments":  cohort_result.get("cohort_source_segments") or {
            "modern_count": 0, "legacy_count": 0,
            "modern_window_months": PR14E_MODERN_WINDOW_MONTHS,
            "legacy_window_start":  PR14E_LEGACY_WINDOW_START_ISO,
            "legacy_window_end":    PR14E_LEGACY_WINDOW_END_ISO,
        },
        "target_state":             cohort_result.get("target_state") or {},
        "cohort_member_provenance": cohort_result.get(
            "cohort_member_provenance",
        ) or [],
        # Carryover keys preserved from V2.3 shape so other code
        # (incremental refresh + persistence) keeps working:
        "borough":                     project.get("borough"),
        "bbl":                         project_bbl,
        "peer_bbl_list":               peer_bbl_list,
        "pluto_snapshot":              project.get("pluto_snapshot"),
        # Q6 Latent Bug 1 fix marker — tells _persist_cache to
        # force-write the refreshed snapshot to db.projects even
        # when project.pluto_snapshot is already truthy.
        "pluto_snapshot_refreshed_at": (
            cur_now.isoformat() if pluto_snapshot_refreshed else None
        ),
    }

    # PR #14D §8.5 sparse-by-default: only emit cohort_truncation
    # marker when the cap actually fired. Reduces cache bloat for
    # the common case (cohort under cap) where no truncation
    # happened.
    if cohort_truncation is not None:
        peer_meta["cohort_truncation"] = cohort_truncation

    cache = _assemble_cache(
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

    # Q1 lock — emit lifecycle_normalized_percentile placeholders.
    # PR #14D replaces None with a calibrated stage-windowed formula
    # using cohort_median_duration_days + active_project.completion_pct.
    for label in ("inspections", "complaints"):
        if cache.get(label, {}).get("available"):
            cache[label]["lifecycle_normalized_percentile"] = None

    return cache


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

    # PR #14C: peer_criteria carries the full PR #14B vocabulary
    # from peer_meta. Pre-PR-14C this block manually populated V2.3
    # keys (project_class, use_type, tier="borough_class_use"); per
    # Q7 lock those keys retired with the V2.3 4-tier ladder.
    peer_criteria: Dict[str, Any] = {
        # PR #14B locked keys (T3 hybrid empty-cohort shape):
        "dob_project_type":            peer_meta.get("dob_project_type"),
        "geography_tier_used":         peer_meta.get("geography_tier_used"),
        "fallback_level":              peer_meta.get("fallback_level"),
        "low_confidence_flag":         peer_meta.get("low_confidence_flag", False),
        "sample_size":                 (
            peer_meta.get("sample_size")
            if peer_meta.get("sample_size") is not None
            else len(peer_bbl_list)
        ),
        "window_months":               peer_meta.get("window_months"),
        "completion_method":           peer_meta.get("completion_method"),
        "cohort_filter_spec":          peer_meta.get("cohort_filter_spec") or {},
        "cohort_job_numbers":          peer_meta.get("cohort_job_numbers") or [],
        "cohort_bins":                 peer_meta.get("cohort_bins") or [],
        "cohort_median_duration_days": peer_meta.get("cohort_median_duration_days"),
        "active_project":              peer_meta.get("active_project") or {},
        "lifecycle_skip_reason":       peer_meta.get("lifecycle_skip_reason"),
        # Q3 empty-cohort sentinel.
        "cohort_unavailable":          peer_meta.get("cohort_unavailable", False),
        # PR #14E §7.3 + Risk 6 schema bump (was PR14C_SCHEMA_VERSION).
        # Drives the cache-hit invalidation check in
        # compare_project_to_peers.
        "schema_version":              PR14E_SCHEMA_VERSION,
        # PR #14E surface additions — forward from peer_meta.
        "cohort_source_segments":  peer_meta.get("cohort_source_segments") or {},
        "target_state":            peer_meta.get("target_state") or {},
        "cohort_member_provenance": peer_meta.get(
            "cohort_member_provenance",
        ) or [],
        # Carry-forward keys (used by incremental refresh + persist):
        "borough":                     peer_meta.get("borough"),
        "bbl":                         project_bbl,
        "peer_bbl_list":               peer_bbl_list,
        "pluto_snapshot":              peer_meta.get("pluto_snapshot"),
        # Q6 Latent Bug 1 fix marker — _persist_cache reads this to
        # force-write a refreshed snapshot to db.projects.
        "pluto_snapshot_refreshed_at": peer_meta.get("pluto_snapshot_refreshed_at"),
        # Persist per-BBL counts so incremental refresh can
        # add-then-evict events without re-fetching the full lookback.
        "_peer_counts_by_dataset": {
            DATASET_DOB_VIOLATIONS:  dict(v_counts),
            DATASET_DOB_INSPECTIONS: dict(i_counts),
            DATASET_COMPLAINTS_311:  dict(c_counts),
        },
    }

    # PR #14D §8.5 sparse-by-default: forward the cohort_truncation
    # marker into peer_criteria only when present. The compute layer
    # (compute_peer_stats_full) only adds the key to peer_meta when
    # the cap actually fired; absence here means "no truncation".
    if peer_meta.get("cohort_truncation") is not None:
        peer_criteria["cohort_truncation"] = peer_meta["cohort_truncation"]

    return {
        "computed_at":       computed_at,
        "last_refreshed_at": last_refreshed_at,
        "peer_criteria":     peer_criteria,
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
    db: Any = None,
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
            socrata, project, db,
            lookback_days=lookback_days, now=cur_now,
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


# PR #14E (§7.2 + §7.7 + Risk 2 + T1 lock) — parser for pkdm-hqz6's
# c_of_o_issuance_date column. Format is ``MM/DD/YY HH:MM:SS AM/PM``
# with 1+ spaces between the date and time portions (production data
# ships both single- and double-space variants per Stage 1 Task 1
# curl probe). Distinct from ``_parse_socrata_dt`` because the latter
# expects ISO-8601, and from ``_parse_socrata_yyyymmdd`` because that
# expects an 8-digit numeric string.
_PKDM_DATE_RE = re.compile(
    r"^\s*"
    r"(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<yy>\d{2})"
    r"\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"\s+"
    r"(?P<ampm>AM|PM|am|pm)"
    r"\s*$",
)


def _parse_pkdm_date(value: Any) -> Optional[datetime]:
    """Parse pkdm-hqz6 ``c_of_o_issuance_date`` into a tz-aware UTC datetime.

    Format: ``MM/DD/YY HH:MM:SS AM/PM`` with 1+ whitespace between
    the date and time portions (§7.7 lock — production ships both
    single- and double-space variants).

    T1 Y2K cutoff: yy < 50 → 20yy; yy >= 50 → 19yy. Valid range
    1950-2049 (2049 horizon documented; the data only contains
    21st-century filings in practice).

    Returns ``None`` on:
      • non-string non-datetime input
      • empty / whitespace-only string
      • format mismatch
      • out-of-range numeric values (e.g., month=13)

    Pass-through for already-parsed ``datetime`` objects (mirrors
    ``_parse_socrata_dt`` for caller ergonomics).
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    m = _PKDM_DATE_RE.match(value)
    if not m:
        return None
    try:
        month = int(m.group("month"))
        day = int(m.group("day"))
        yy = int(m.group("yy"))
        hour12 = int(m.group("hour"))
        minute = int(m.group("minute"))
        second = int(m.group("second"))
    except (TypeError, ValueError):
        return None
    ampm = m.group("ampm").upper()
    # T1 Y2K cutoff.
    year = (2000 + yy) if yy < 50 else (1900 + yy)
    # 12-hour → 24-hour conversion: 12 AM → 00, 12 PM → 12,
    # 1-11 AM → 1-11, 1-11 PM → 13-23.
    if hour12 == 12:
        hour24 = 0 if ampm == "AM" else 12
    else:
        hour24 = hour12 if ampm == "AM" else hour12 + 12
    try:
        return datetime(
            year, month, day, hour24, minute, second,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


# PR #14F (Stage 10 lex-comparison bugfix) — parser for BIS
# pre__filing_date. BIS ic3t-wcy2 ships dates in MM/DD/YYYY text
# (4-digit year, NO Y2K cutoff needed). The trailing time portion
# is optional and may use either a space or 'T' separator. Distinct
# from _parse_pkdm_date which handles the 2-digit-year pkdm-hqz6
# format. PR #14E pushed pre__filing_date thresholds into SoQL
# WHERE clauses producing silent lex-comparison failures (e.g.
# "06/30/2018" < "2018-06-30" because '0' < '2'); PR #14F moves
# the date filter client-side using this helper.
_BIS_MDY_DATE_RE = re.compile(
    r"^\s*"
    r"(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})"
    r"(?:[\sT]+.*)?"  # optional trailing time portion (ignored)
    r"\s*$",
)


def _parse_bis_mdy_date(value: Any) -> Optional[datetime]:
    """Parse BIS ``pre__filing_date`` MM/DD/YYYY format into a
    tz-aware UTC datetime.

    BIS ic3t-wcy2 stores dates as text in ``MM/DD/YYYY`` form,
    optionally followed by whitespace or ``T`` and a time portion
    (which we discard — we only need date-level resolution for the
    Golden Era window check).

    Returns ``None`` on malformed / empty / non-string input.
    Pass-through for already-parsed ``datetime`` objects (mirrors
    ``_parse_pkdm_date`` / ``_parse_socrata_dt``).

    No Y2K cutoff needed (4-digit year). Out-of-range numeric
    values (month=13, etc.) return None via ValueError.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    m = _BIS_MDY_DATE_RE.match(value)
    if not m:
        return None
    try:
        month = int(m.group("month"))
        day = int(m.group("day"))
        year = int(m.group("year"))
    except (TypeError, ValueError):
        return None
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


# PR #14G (Stage 10 follow-up) — PLUTO's bbl column ships with a
# Socrata numeric-float ``.00000000`` suffix
# (e.g., ``"3012440018.00000000"``) while pkdm-hqz6 and BIS
# ic3t-wcy2 ship bbl as plain 10-digit text (``"3012440018"``).
# Stage 10 production verification on Menahan showed Modern cohort
# returning 0 rows because dict-lookup keys mismatched between the
# pkdm-side bbl and the un-normalized PLUTO-side bbl. A general
# ``normalize_bbl`` helper exists in utils.py; this PLUTO-specific
# sibling makes intent explicit at every PLUTO row consumption
# point and tolerates any decimal portion (not just ``.0+``) so a
# future PLUTO-side format quirk (typed float fractional) doesn't
# silently mis-key the join.
def _normalize_pluto_bbl(raw: Any) -> Optional[str]:
    """Strip the Socrata numeric-float fractional suffix from a
    PLUTO ``bbl`` value so it matches pkdm-hqz6 / BIS plain
    10-digit text format.

    Examples:
      ``"3012440018.00000000"`` → ``"3012440018"``
      ``"3012440018"``          → ``"3012440018"`` (pass-through)
      ``None`` / ``""``         → ``None``
      ``3012440018.0``          → ``"3012440018"`` (coerced via str())

    Returns ``None`` for ``None`` / empty / whitespace-only input.
    Returns the input unchanged (after str() coercion + strip) when
    no decimal point is present. Always returns a string (or None)
    so the downstream dict lookup keys are predictable.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if "." in s:
        s = s.split(".", 1)[0]
    return s


# PR #14I (Stage 10 follow-up #2) — borough name format mismatch
# between PLUTO and the DOB datasets. PLUTO 64uk-42ks stores borough
# as a 2-letter code ("BK", "MN", "BX", "QN", "SI"). The DOB datasets
# (pkdm-hqz6 / ic3t-wcy2 / rbx6-tga4) store borough as the full
# uppercase name ("BROOKLYN", "MANHATTAN", "BRONX", "QUEENS",
# "STATEN ISLAND"). PR #14E threaded the project's stored borough
# value (which arrives via project doc OR via PLUTO snapshot
# refresh) through the DOB-side WHERE clauses unconditionally. When
# the snapshot had been freshly refreshed, the value was "BK"; the
# pkdm/BIS queries received ``borough = 'BK'`` and matched zero
# rows. PR #18 SoQL log surfaced this in production.
#
# This helper expands a PLUTO code → DOB full name. Pass-through
# when the input is already a full name (defensive: same code path
# works for projects where ``borough`` arrives from the user-facing
# field, which is already "BROOKLYN"). Case-insensitive.
_BOROUGH_FULL_NAME_BY_CODE = {
    "BK": "BROOKLYN",
    "MN": "MANHATTAN",
    "BX": "BRONX",
    "QN": "QUEENS",
    "SI": "STATEN ISLAND",
}


def _normalize_borough_to_full_name(raw: Any) -> Optional[str]:
    """Expand PLUTO 2-letter borough code to full uppercase name
    for use against DOB-dataset borough columns.

    Examples:
      "BK"           → "BROOKLYN"
      "bk"           → "BROOKLYN"   (case-insensitive)
      "BROOKLYN"     → "BROOKLYN"   (pass-through)
      "brooklyn"     → "BROOKLYN"
      "STATEN ISLAND" → "STATEN ISLAND"
      None / "" / "   " → None
      "MARS"         → "MARS"       (unknown code passes through; let
                                     Socrata's empty-result surface the
                                     mismatch rather than silently
                                     coercing to a default)

    One-way only: this helper is for queries against
    pkdm-hqz6 / ic3t-wcy2 / rbx6-tga4 etc. PLUTO queries continue to
    use the 2-letter code (PLUTO's native format).
    """
    if not raw:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    return _BOROUGH_FULL_NAME_BY_CODE.get(s, s)


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
    """PR #14C — project the cache shape onto the
    ``compare_project_to_peers`` FE-facing return shape.

    Score.py's ``_factor_breakdown`` reads ``peer_set`` directly into
    the contributing-factors row's ``details``. PR #14C emits the
    PR #14B vocabulary (``dob_project_type``, ``geography_tier_used``,
    ``low_confidence_flag``) on this surface — replacing V2.3's
    tier-conditional ``project_class`` / ``use_type`` emission
    (retired per Q7 lock).

    Per-dataset ``lifecycle_normalized_percentile`` passes through
    so the FE drawer can render lifecycle-normalized comparisons.
    Per Q1 lock, this value is ``None`` until PR #14D ships the
    calibrated formula.

    The schema check in ``compare_project_to_peers`` (Q4 Option B)
    ensures this function is only called on current-schema caches.
    Pre-PR-14C caches are auto-invalidated upstream.
    """
    criteria = cache.get("peer_criteria") or {}

    peer_set: Dict[str, Any] = {
        # ``tier`` is preserved for backward-compat with any consumer
        # that walks the old key name; carries the new vocabulary
        # value (e.g. "zip_bldgclass_type").
        "tier":                 criteria.get("geography_tier_used"),
        "geography_tier_used":  criteria.get("geography_tier_used"),
        "fallback_level":       criteria.get("fallback_level"),
        "dob_project_type":     criteria.get("dob_project_type"),
        "low_confidence_flag":  criteria.get("low_confidence_flag", False),
        "sample_size":          criteria.get("sample_size") or 0,
        "borough":              criteria.get("borough"),
        "zipcode":              (criteria.get("pluto_snapshot") or {}).get("zipcode"),
        "cohort_unavailable":   criteria.get("cohort_unavailable", False),
        # PR #14E surface forwarding — FE drawer renders these.
        "cohort_source_segments":  criteria.get("cohort_source_segments") or {},
        "target_state":            criteria.get("target_state") or {},
    }

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
                # PR #14C Q1 lock — per-dataset lifecycle pass-through.
                # None until PR #14D calibration replaces.
                "lifecycle_normalized_percentile": dataset_summary.get(
                    "lifecycle_normalized_percentile",
                ),
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
    peer_criteria = cache.get("peer_criteria") or {}
    snapshot = peer_criteria.get("pluto_snapshot")
    refreshed_at = peer_criteria.get("pluto_snapshot_refreshed_at")
    # PR #14C Q6 Latent Bug 1 fix: force-write the refreshed snapshot
    # even when project.pluto_snapshot is already truthy. Pre-PR-14C
    # the guard was ``not project.get("pluto_snapshot")`` only — so
    # after _ensure_pluto_snapshot_pr14b_complete mutated the project
    # in-memory, this branch skipped the DB write and the new fields
    # never reached db.projects. The refreshed_at marker (set by
    # compute_peer_stats_full when the snapshot actually changed)
    # opens the gate.
    if snapshot and (not project.get("pluto_snapshot") or refreshed_at):
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

    # PR #14E §7.3 + Risk 6 (was PR #14C Q4 Option B + T4):
    # schema-version invalidation. If a ``status=ready`` cache
    # lacks ``schema_version`` OR carries a value other than the
    # current ``PR14E_SCHEMA_VERSION``, treat it as a miss → fall
    # through to recompute. Catches PR14C- (and earlier) shape
    # caches that survived the deploy-time ``$unset`` migration.
    #
    # Gated on ``status=ready`` because pending + failed are status
    # markers written by prewarm + refresh_cron BEFORE compute_peer_stats_full
    # ever runs — they don't carry peer_criteria at all. Invalidating
    # them here would break the race-prevention contract that lets
    # concurrent compare/prewarm calls coexist (V2.3 Commit 4).
    if cache and cache.get("status") == "ready":
        criteria = cache.get("peer_criteria") or {}
        if criteria.get("schema_version") != PR14E_SCHEMA_VERSION:
            logger.info(
                "[baselines] peer_stats_cache schema mismatch for "
                "%s (got %r, expected %r); invalidating + "
                "forcing recompute",
                project.get("_id"),
                criteria.get("schema_version"),
                PR14E_SCHEMA_VERSION,
            )
            cache = None

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
                    socrata, project, db,
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
        permit_raw = (
            r.get("permit_issue_date")
            or r.get("permit_issued_date")  # PR #14E rbx6-tga4 cross-join key
            or r.get("fully_permitted")
        )
        c_of_o_raw = r.get("c_o_issue_date") or r.get("c_of_o_issuance_date")
        # PR #14E §7.2 — try ISO parser first (V2.3 BIS path), fall
        # back to pkdm-hqz6's MM/DD/YY HH:MM:SS AM/PM format (Modern
        # path). Same dual-parse for permit dates in case rbx6-tga4
        # cross-join populated them as ISO strings.
        permit_dt = _parse_socrata_dt(permit_raw) or _parse_pkdm_date(permit_raw)
        c_of_o_dt = _parse_socrata_dt(c_of_o_raw) or _parse_pkdm_date(c_of_o_raw)
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
    # PR #14I: BIS ic3t-wcy2 stores borough as the full uppercase
    # name ("BROOKLYN"). The geo dict may carry the PLUTO 2-letter
    # code ("BK") if the project's pluto_snapshot is the source.
    # Normalize before sending to SoQL.
    borough_full = _normalize_borough_to_full_name(borough)
    if not borough_full:
        return None
    return f"borough = {_soql_quote(borough_full)}"


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


# ── PR #14E — Unified Cohort: target state derivation ────────


def _safe_int(value: Any) -> Optional[int]:
    """Best-effort int conversion. Returns None on TypeError / ValueError
    / None / empty-string. Used across target-state derivation where
    PLUTO values arrive as strings."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _derive_target_state_for_project(
    project: Dict[str, Any],
    project_type: str,
) -> Dict[str, Any]:
    """PR #14E Q5 lock — derive cohort target_state from project doc.

    Returns a dict with the shape:
      {
          "bldgclass":     str | None,
          "numfloors":     int | None,
          "numfloors_band": (low, high) | None,
          "source":        "parser" | "pluto" | "pluto_fallback" | "frozen_pluto_snapshot",
          "band_widened":  bool,
          "yearbuilt_filter_min": int | None,
          "apply_yearbuilt_filter": bool,
      }

    Project-type semantics:
      • new_building — bldgclass + numfloors from current PLUTO
        snapshot; source = ``pluto``; numfloors band = ±25%;
        yearbuilt filter enforced at >=2000 (Q3 lock).
      • major_alt_with_enlargement (A1) — bldgclass from PLUTO;
        numfloors via Q5 hybrid:
          - parser primary when ``dob_extracted_scope.story_count``
            is a confident positive int → source=``parser``,
            band=±25%.
          - PLUTO fallback otherwise → source=``pluto_fallback``,
            band=±50% (widened), ``band_widened=True``.
        No yearbuilt filter (Q3 lock — NB-only).
      • minor_alt — bldgclass from PLUTO; numfloors=None (no story
        filter for minor_alt per spec); source=``pluto``.
      • full_demo — uses FROZEN pluto_snapshot per Risk 7. source=
        ``frozen_pluto_snapshot``; bldgclass + numfloors from the
        pre-demolition snapshot.

    Returned dict feeds both ``_fetch_modern_cohort`` and
    ``_fetch_legacy_cohort``. Inclusion in peer_criteria allows the
    FE to display the cohort's matching attributes.
    """
    snapshot = project.get("pluto_snapshot") or {}
    bldgclass = snapshot.get("bldgclass")
    pluto_numfloors = _safe_int(snapshot.get("numfloors"))
    parser_scope = project.get("dob_extracted_scope") or {}
    parser_floors = _safe_int(parser_scope.get("story_count"))

    base: Dict[str, Any] = {
        "bldgclass":              bldgclass,
        "numfloors":              None,
        "numfloors_band":         None,
        "source":                 "pluto",
        "band_widened":           False,
        "yearbuilt_filter_min":   None,
        "apply_yearbuilt_filter": False,
    }

    if project_type == "new_building":
        base["numfloors"] = pluto_numfloors
        if pluto_numfloors and pluto_numfloors > 0:
            base["numfloors_band"] = list(
                compute_tolerance_band(pluto_numfloors, 0.25, 1),
            )
        base["yearbuilt_filter_min"] = 2000
        base["apply_yearbuilt_filter"] = True
        base["source"] = "pluto"
        return base

    if project_type == "major_alt_with_enlargement":
        # Q5 hybrid — parser primary, PLUTO fallback.
        if parser_floors and parser_floors > 0:
            base["numfloors"] = parser_floors
            base["numfloors_band"] = list(
                compute_tolerance_band(parser_floors, 0.25, 1),
            )
            base["source"] = "parser"
            base["band_widened"] = False
        else:
            base["numfloors"] = pluto_numfloors
            if pluto_numfloors and pluto_numfloors > 0:
                # PLUTO fallback gets a wider ±50% band per Q5 because
                # PLUTO snapshot reflects pre-enlargement state which
                # is less reliable as a proxy for post-enlargement
                # peer matching.
                base["numfloors_band"] = list(
                    compute_tolerance_band(pluto_numfloors, 0.50, 1),
                )
            base["source"] = "pluto_fallback"
            base["band_widened"] = True
        return base

    if project_type == "minor_alt":
        # No numfloors filter for minor_alt per spec.
        base["numfloors"] = None
        base["numfloors_band"] = None
        base["source"] = "pluto"
        return base

    if project_type == "full_demo":
        # T7 lock — frozen pluto_snapshot is the source of truth.
        base["numfloors"] = pluto_numfloors
        if pluto_numfloors and pluto_numfloors > 0:
            base["numfloors_band"] = list(
                compute_tolerance_band(pluto_numfloors, 0.25, 1),
            )
        base["source"] = "frozen_pluto_snapshot"
        return base

    # unknown / unmapped — return base with no narrowing applied.
    return base


# ── PR #14E — Modern cohort source (pkdm-hqz6) ───────────────


def _modern_pluto_match(
    pluto_row: Dict[str, Any],
    target: Dict[str, Any],
) -> bool:
    """Apply target-state filter (bldgclass + numfloors band +
    optional yearbuilt floor) to a single PLUTO row. Defensive on
    missing values — if a PLUTO row lacks the field, we keep it
    rather than drop (better recall than precision; sample-size
    floor downstream).
    """
    target_class = target.get("bldgclass")
    if target_class:
        row_class = pluto_row.get("bldgclass")
        if row_class and row_class != target_class:
            return False
    band = target.get("numfloors_band")
    if band:
        row_floors = _safe_int(pluto_row.get("numfloors"))
        if row_floors is not None:
            low, high = band[0], band[1]
            if not (low <= row_floors <= high):
                return False
    if target.get("apply_yearbuilt_filter"):
        ymin = target.get("yearbuilt_filter_min")
        if ymin is not None:
            row_year = _safe_int(pluto_row.get("yearbuilt"))
            if row_year is None or row_year < ymin:
                return False
    return True


async def _fetch_modern_cohort(
    socrata,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    target_state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """PR #14E §7.6 + T4 — fetch Modern cohort from pkdm-hqz6.

    Pipeline:
      1. Build WHERE: ``c_of_o_filing_type IN ('Final', 'Initial')
         AND job_type IN (<case variants>) AND borough = <upper>``.
         Returns [] when project_type has no modern_path (full_demo).
      2. Query pkdm-hqz6 (no PLUTO bridge needed — bbl + bin ship
         inline per Stage 1 Task 1).
      3. Apply 36-month window post-hoc against c_of_o_issuance_date
         (parsed with ``_parse_pkdm_date`` — pkdm-hqz6 ships dates
         in MM/DD/YY format, not ISO, so the SoQL WHERE can't filter
         by date directly without a date-coercion layer).
      4. PLUTO chunked + parallel join (Fix 3 pattern from PR #14D)
         to fetch bldgclass + numfloors + yearbuilt per cohort bbl.
      5. Apply target_state filter (bldgclass + numfloors band +
         optional yearbuilt >=2000).
      6. rbx6-tga4 chunked + parallel cross-join by BIN to enrich
         each cohort row with ``permit_issued_date`` for downstream
         lifecycle duration math (Q6 lock).
      7. Return list of dicts:
           [{bbl, bin, job_filing_name, c_of_o_issuance_date,
             permit_issued_date, source: 'modern', ...}, ...]

    Args:
        socrata: SocrataClient instance.
        project: Project doc (must carry borough + pluto_snapshot
            + optionally dob_extracted_scope + dob_project_type).
        now: Optional injection point for tests; defaults to
            ``datetime.now(timezone.utc)``.
        target_state: Pre-derived target_state dict. When not
            provided, derived inline via
            ``_derive_target_state_for_project``.

    Returns ``[]`` if:
      • project_type has no modern_path (full_demo per Q4)
      • borough missing
      • pkdm-hqz6 query fails or returns 0 rows
    """
    cur_now = now or datetime.now(timezone.utc)
    project_type = project.get("dob_project_type")
    spec = COHORT_CONFIG.get(project_type)
    if spec is None:
        return []
    modern_cfg = spec.get("modern_path")
    if not modern_cfg:
        # full_demo (Q4 lock) — no Modern path.
        return []

    target = target_state or _derive_target_state_for_project(
        project, project_type,
    )

    borough = (
        project.get("borough")
        or (project.get("pluto_snapshot") or {}).get("borough")
    )
    if not borough:
        return []
    # PR #14I (Stage 10 follow-up #2): pkdm-hqz6 stores borough as
    # the full uppercase name ("BROOKLYN"); PLUTO snapshots ship the
    # 2-letter code ("BK"). When project["borough"] is missing the
    # value falls through to pluto_snapshot["borough"]="BK" and the
    # downstream SoQL `borough = 'BK'` matches zero pkdm-hqz6 rows
    # silently. Stage 10 production logs (PR #18) confirmed this is
    # the Menahan zero-cohort root cause. Normalize to full name
    # before quoting into the WHERE.
    borough_upper = _normalize_borough_to_full_name(borough)
    if not borough_upper:
        return []

    pkdm_job_types = list(modern_cfg.get("pkdm_job_types") or ())
    if not pkdm_job_types:
        return []

    # ── Step 1+2: query pkdm-hqz6 ──────────────────────────────
    # PR #14F (Stage 10 lex-comparison bugfix): WHERE intentionally
    # excludes any ``c_of_o_issuance_date`` threshold. Pushing a
    # MM/DD/YY date threshold into SoQL would lex-compare against
    # the underlying TEXT column (Socrata stores the date as text,
    # not a typed timestamp). E.g. "06/23/21" > "05/15/23" because
    # '06' > '05' as strings — so a 2023 threshold lets 2021 rows
    # through silently. Pull the un-filtered population and apply
    # the 36mo window client-side via _parse_pkdm_date below.
    where_parts = [
        _soql_in("c_of_o_filing_type", ["Final", "Initial"]),
        _soql_in("job_type", pkdm_job_types),
        f"borough = {_soql_quote(borough_upper)}",
    ]
    where = " AND ".join(where_parts)
    try:
        pkdm_rows = await socrata.query(
            DATASET_DOB_C_OF_O,
            where=where,
            # PR #14F: bumped 10000 → 5000 is intentionally smaller
            # only for cap discipline. 5000 still safely accommodates
            # the pre-filter population for the largest single
            # borough × job_type combo (current ~4,026 for
            # Brooklyn ALTERATION TYPE 1, headroom for growth).
            limit=5000,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[baselines] pkdm-hqz6 Modern cohort fetch failed: %r", e,
        )
        return []

    if not pkdm_rows:
        return []

    # ── Step 3: 36-month CLIENT-SIDE date window (PR #14F) ────
    # Cache the parsed datetime on the row so we don't double-parse
    # downstream (Step 5 target_state filter + Step 6 cross-join
    # don't re-read it, but lifecycle median later may).
    window_start = cur_now - timedelta(days=30 * PR14E_MODERN_WINDOW_MONTHS)
    in_window: List[Dict[str, Any]] = []
    for r in pkdm_rows:
        issued_raw = r.get("c_of_o_issuance_date")
        issued_dt = _parse_pkdm_date(issued_raw) or _parse_socrata_dt(issued_raw)
        if issued_dt is None:
            # Defensive — keep undated rows rather than drop them;
            # downstream lifecycle median tolerates missing date.
            in_window.append(r)
            continue
        if issued_dt >= window_start:
            r["_parsed_issuance_dt"] = issued_dt  # cache for downstream
            in_window.append(r)
    pkdm_rows = in_window

    if not pkdm_rows:
        return []

    # ── Step 4: PLUTO chunked + parallel join ────────────────
    cohort_bbls = [
        normalize_bbl(r.get("bbl"))
        for r in pkdm_rows if r.get("bbl")
    ]
    cohort_bbls = [b for b in cohort_bbls if b]

    pluto_by_bbl: Dict[str, Dict[str, Any]] = {}
    if cohort_bbls:
        async def _query_pluto_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
            try:
                return await socrata.query(
                    DATASET_PLUTO,
                    where=_soql_in("bbl", chunk),
                    select=["bbl", "bldgclass", "numfloors", "yearbuilt"],
                    limit=10000,
                )
            except SocrataQueryError as e:
                logger.warning(
                    "[baselines] Modern cohort PLUTO chunk failed: %r",
                    e,
                )
                return []

        chunks = list(_chunk(cohort_bbls, SOQL_IN_CHUNK_SIZE))
        chunk_results = await asyncio.gather(
            *(_query_pluto_chunk(c) for c in chunks),
        )
        # PR #14G: PLUTO ships bbl with .00000000 suffix; normalize
        # before dict-keying so the lookup below (keyed on the
        # pkdm-side plain bbl) matches. Pre-fix: 0 cohort rows
        # because dict-lookup keys mismatched between sides.
        for rows in chunk_results:
            for pr in rows:
                bbl_n = _normalize_pluto_bbl(pr.get("bbl"))
                if bbl_n:
                    pluto_by_bbl[bbl_n] = pr

    # ── Step 5: target_state filter ───────────────────────────
    filtered: List[Dict[str, Any]] = []
    for r in pkdm_rows:
        # pkdm-hqz6 bbl is plain 10-digit text; normalize_bbl is a
        # no-op here. Lookup key matches the PLUTO-side normalized
        # bbl from Step 4.
        bbl_n = normalize_bbl(r.get("bbl"))
        pluto_row = pluto_by_bbl.get(bbl_n) if bbl_n else None
        if pluto_row is None:
            # No PLUTO match — drop the row; target_state filter
            # can't be applied without it.
            continue
        if not _modern_pluto_match(pluto_row, target):
            continue
        merged = dict(r)
        merged["bbl"] = bbl_n
        merged["pluto_bldgclass"] = pluto_row.get("bldgclass")
        merged["pluto_numfloors"] = pluto_row.get("numfloors")
        merged["pluto_yearbuilt"] = pluto_row.get("yearbuilt")
        merged["source"] = "modern"
        filtered.append(merged)

    if not filtered:
        return []

    # ── Step 6: rbx6-tga4 cross-join for permit_issued_date ──
    cohort_bins = [r.get("bin") for r in filtered if r.get("bin")]
    permit_by_bin: Dict[str, str] = {}
    if cohort_bins:
        async def _query_permit_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
            try:
                return await socrata.query(
                    DATASET_DOB_PERMITS,
                    where=(
                        f"{_soql_in('bin', chunk)} AND "
                        f"permit_status = {_soql_quote('Signed-off')}"
                    ),
                    select=["bin", "issued_date", "approved_date"],
                    limit=10000,
                )
            except SocrataQueryError as e:
                logger.warning(
                    "[baselines] Modern cohort rbx6-tga4 chunk failed: %r",
                    e,
                )
                return []

        bin_chunks = list(_chunk(cohort_bins, SOQL_IN_CHUNK_SIZE))
        bin_chunk_results = await asyncio.gather(
            *(_query_permit_chunk(c) for c in bin_chunks),
        )
        for rows in bin_chunk_results:
            for permit_row in rows:
                bin_id = permit_row.get("bin")
                if not bin_id:
                    continue
                # Earliest issued_date wins (first-permit-issued =
                # cohort lifecycle t_0).
                issued = (
                    permit_row.get("issued_date")
                    or permit_row.get("approved_date")
                )
                if not issued:
                    continue
                existing = permit_by_bin.get(bin_id)
                if existing is None or issued < existing:
                    permit_by_bin[bin_id] = issued

    for r in filtered:
        bin_id = r.get("bin")
        r["permit_issued_date"] = permit_by_bin.get(bin_id) if bin_id else None
        r["permit_issue_date"] = r["permit_issued_date"]  # alias for legacy
        # Promote the pkdm issuance date into the canonical c_o key
        # so _cohort_duration_median picks it up via existing dual
        # parsers.
        if "c_o_issue_date" not in r:
            r["c_o_issue_date"] = r.get("c_of_o_issuance_date")

    return filtered


# ── PR #14E — Legacy cohort source (BIS Golden Era) ──────────


async def _fetch_legacy_cohort(
    socrata,
    project: Dict[str, Any],
    *,
    target_state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """PR #14E §7.6 + Q7 — fetch Legacy cohort from BIS Golden Era.

    Queries ic3t-wcy2 with:
      • job_type IN (<bis_job_types from legacy_path>)
      • building_class = <target_state.bldgclass>
      • borough = <upper>
      • job_status IN ('X', 'U')

    Per Q7 lock — BIS stopped receiving filings 2021+; the Golden
    Era window bounds cohort members to pre-DOB-NOW filings that
    still completed.

    PR #14F (Stage 10 lex-comparison bugfix): the Golden Era window
    is enforced CLIENT-SIDE on the parsed ``pre__filing_date``, NOT
    in the SoQL WHERE clause. BIS stores pre__filing_date as TEXT
    in MM/DD/YYYY form; pushing an ISO threshold like
    ``pre__filing_date >= '2018-06-30T00:00:00'`` lex-compared
    against text would fail every row ("06/30/2018" < "2018-06-30"
    because '0' < '2'), silently returning 0. We use the
    ``_parse_bis_mdy_date`` helper to apply the window after the
    un-filtered population pull.

    target_state filter (bldgclass + optional story band) is applied
    in WHERE where possible (bldgclass), and post-hoc on the
    ``total_construction_floor_area`` proxy for story count
    (matches PR #14B band semantics).

    Returns ``[]`` if no rows match (caller drops to empty_cohort
    sentinel rather than raising). Each row is annotated with
    ``source="legacy"`` for cohort_member_provenance.
    """
    project_type = project.get("dob_project_type")
    spec = COHORT_CONFIG.get(project_type)
    if spec is None:
        return []
    legacy_cfg = spec.get("legacy_path")
    if not legacy_cfg:
        return []

    target = target_state or _derive_target_state_for_project(
        project, project_type,
    )

    borough = (
        project.get("borough")
        or (project.get("pluto_snapshot") or {}).get("borough")
    )
    if not borough:
        return []
    # PR #14I (Stage 10 follow-up #2): BIS ic3t-wcy2 stores borough
    # as the full uppercase name ("BROOKLYN"); pluto_snapshot ships
    # the 2-letter code ("BK"). Same lex-mismatch bug surfaced on
    # the Legacy path. Normalize to full name before SoQL.
    borough_full = _normalize_borough_to_full_name(borough)
    if not borough_full:
        return []

    bis_job_types = list(legacy_cfg.get("bis_job_types") or ())
    if not bis_job_types:
        return []

    # PR #14F: pre__filing_date threshold REMOVED from SoQL WHERE
    # (text-typed column would lex-compare against an ISO literal
    # and silently fail). Window is enforced client-side below.
    where_parts: List[str] = [
        _soql_in("job_type", bis_job_types),
        f"borough = {_soql_quote(borough_full)}",
        _soql_in("job_status", ["X", "U"]),
    ]
    target_class = target.get("bldgclass")
    if target_class:
        where_parts.append(
            f"building_class = {_soql_quote(target_class)}",
        )
    where = " AND ".join(where_parts)

    try:
        rows = await socrata.query(
            DATASET_BIS_JOB_FILINGS,
            where=where,
            # PR #14F: bumped 10000 → 5000 for cap discipline (matches
            # _fetch_modern_cohort). 5000 accommodates the un-filtered
            # Brooklyn A1+X/U population (~2,360 per Stage 1 reference)
            # with headroom; pre-filter pulls are bounded by the
            # client-side Golden Era window.
            limit=5000,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[baselines] Legacy BIS cohort fetch failed: %r", e,
        )
        return []

    if not rows:
        return []

    # ── PR #14F: CLIENT-SIDE Golden Era window filter ─────────
    # Parse ``pre__filing_date`` (MM/DD/YYYY text) and keep only
    # rows within [window_start, window_end] inclusive. Rows with
    # un-parseable dates are dropped here (different from Modern's
    # "keep undated" — BIS rows without a filing date are rare and
    # not statistically useful as cohort members anyway).
    window_start_iso = legacy_cfg.get(
        "window_start_iso", PR14E_LEGACY_WINDOW_START_ISO,
    )
    window_end_iso = legacy_cfg.get(
        "window_end_iso", PR14E_LEGACY_WINDOW_END_ISO,
    )
    window_start_dt = _parse_socrata_dt(window_start_iso)
    window_end_dt = _parse_socrata_dt(window_end_iso)
    in_window: List[Dict[str, Any]] = []
    for r in rows:
        filing_raw = r.get("pre__filing_date")
        filing_dt = (
            _parse_bis_mdy_date(filing_raw)
            or _parse_socrata_dt(filing_raw)
        )
        if filing_dt is None:
            continue
        if window_start_dt and filing_dt < window_start_dt:
            continue
        if window_end_dt and filing_dt > window_end_dt:
            continue
        r["_parsed_pre__filing_dt"] = filing_dt  # cache for downstream
        in_window.append(r)
    rows = in_window

    if not rows:
        return []

    # ── Post-hoc target-state band filter (numfloors via TCFA proxy) ─
    # Builds a synthetic ``spec_values`` dict so we can reuse the
    # existing PR #14B ``_apply_band_filters`` helper.
    band = target.get("numfloors_band")
    if band:
        synthetic = {"story_count_band": list(band)}
        rows = _apply_band_filters(rows, synthetic)

    # ── Annotate with bbl + provenance ────────────────────────
    # BIS rows are BIN-indexed; BBL is not always derivable inline.
    # PR #14B's compute_peer_stats_full bridges via PLUTO BIN→BBL
    # (still in use for the Legacy code path). For the Modern→Legacy
    # merge dedup, the BIN identifier serves as the join key for
    # cohort_member_provenance.
    out: List[Dict[str, Any]] = []
    for r in rows:
        merged = dict(r)
        # Best-effort BBL: trust an inline ``bbl`` column when
        # present (some BIS slices include it); otherwise leave None
        # and let downstream resolution (PLUTO BIN→BBL bridge) fill in.
        merged["bbl"] = normalize_bbl(r.get("bbl"))
        merged["bin"] = r.get("bin__") or r.get("bin")
        merged["source"] = "legacy"
        # Synthesize lifecycle date keys for downstream median math.
        merged["permit_issue_date"] = (
            r.get("fully_permitted") or r.get("pre__filing_date")
        )
        out.append(merged)

    return out


# ── PR #14E — full_demo dedicated path (T7 lock) ─────────────


async def _fetch_demo_cohort(
    socrata,
    project: Dict[str, Any],
    *,
    target_state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """PR #14E T7 lock — dedicated full_demo cohort helper.

    pkdm-hqz6 has no DEMOLITION job_type (C of O is for OCCUPANCY,
    not demolition) so full_demo cohort sources exclusively from
    BIS DM. The active project's PLUTO snapshot is FROZEN at
    project-create time per Risk 7 so we don't re-fetch a snapshot
    that no longer reflects the demolished structure's attributes.

    Implementation reuses ``_fetch_legacy_cohort`` after deriving
    target_state from the frozen snapshot.

    Returns rows with ``source="legacy"`` because semantically the
    cohort comes from the same BIS Golden Era source; the
    distinguishing feature is target_state.source =
    ``frozen_pluto_snapshot``.
    """
    if project.get("dob_project_type") != "full_demo":
        # Defensive — caller routed through _fetch_demo_cohort but
        # project isn't full_demo; fall through to legacy.
        return await _fetch_legacy_cohort(
            socrata, project, target_state=target_state,
        )
    target = target_state or _derive_target_state_for_project(
        project, "full_demo",
    )
    return await _fetch_legacy_cohort(
        socrata, project, target_state=target,
    )


# ── Top-level cohort builder ──────────────────────────────────


async def compute_cohort_for_project(
    socrata,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """PR #14E §7.6 — compute the Unified Cohort for a project.

    Architecture (Q2 + Q7 locks):
      • Modern primary  — pkdm-hqz6 (DOB NOW C of O), 2021+ filings,
        target-state-filtered. Bypasses PR #14C's PLUTO BIN→BBL
        bridge because pkdm-hqz6 ships bbl + bin inline.
      • Legacy fallback — BIS Golden Era (2018-06-30 .. 2021-06-30).
        Activates ONLY when Modern returns < 100 rows.
      • Merge rule    — Modern rows first; Legacy extension dedups
        by bbl (when both present) or by bin (when bbl missing on
        the BIS side). Caps at COHORT_MAX_PEERS_FOR_PLUTO_JOIN
        post-merge.
      • full_demo     — routes to ``_fetch_demo_cohort`` (T7 lock).
        Modern path is None (Q4 lock).

    The output extends the PR #14B contract with three new keys:

      • ``cohort_source_segments`` —
            {"modern_count": int, "legacy_count": int,
             "modern_window_months": 36,
             "legacy_window_start": "2018-06-30",
             "legacy_window_end": "2021-06-30"}
      • ``target_state``  — see ``_derive_target_state_for_project``.
      • ``cohort_member_provenance`` — list of dicts, one per cohort
        row, with ``source ∈ {"modern", "legacy"}`` plus identifying
        ``bbl``/``bin``/``job_id``.

    Existing keys (``sample_size``, ``cohort_filter_spec``,
    ``cohort_job_numbers``, ``cohort_bins``,
    ``cohort_median_duration_days``, ``active_project``, etc.) are
    preserved for backward compatibility with PR #14B/C consumers.
    """
    cur_now = now or datetime.now(timezone.utc)
    dob_type = project.get("dob_project_type")
    spec = COHORT_CONFIG.get(dob_type)

    base_result: Dict[str, Any] = {
        "tier_used":                   None,
        "fallback_level":              None,
        "sample_size":                 0,
        "low_confidence_flag":         False,
        "window_months":               PR14E_MODERN_WINDOW_MONTHS,
        "completion_method":           None,
        "cohort_filter_spec":          {},
        "cohort_job_numbers":          [],
        "cohort_bins":                 [],
        "cohort_median_duration_days": None,
        "lifecycle_skip_reason":       None,
        "active_project":              {
            "completion_pct":      None,
            "observed_milestones": [],
        },
        # PR #14E surface additions.
        "cohort_source_segments": {
            "modern_count":         0,
            "legacy_count":         0,
            "modern_window_months": PR14E_MODERN_WINDOW_MONTHS,
            "legacy_window_start":  PR14E_LEGACY_WINDOW_START_ISO,
            "legacy_window_end":    PR14E_LEGACY_WINDOW_END_ISO,
        },
        "target_state":              {},
        "cohort_member_provenance":  [],
    }

    if spec is None:
        base_result["lifecycle_skip_reason"] = "no_spec"
        return base_result

    # PR #14B Risk 7: full_demo snapshots are FROZEN; everyone
    # else gets a lazy refresh when the snapshot is pre-PR-14B.
    await _ensure_pluto_snapshot_pr14b_complete(socrata, project)

    # ── Step 1: derive target_state from project + project_type ──
    target_state = _derive_target_state_for_project(project, dob_type)

    # ── Step 2: full_demo dedicated path (T7 lock) ─────────────
    if dob_type == "full_demo":
        demo_rows = await _fetch_demo_cohort(
            socrata, project, target_state=target_state,
        )
        modern_count = 0
        legacy_count = len(demo_rows)
        cohort_rows = demo_rows
    else:
        # ── Step 3: Modern primary fetch ──────────────────────
        modern_rows = await _fetch_modern_cohort(
            socrata, project,
            now=cur_now, target_state=target_state,
        )
        modern_count = len(modern_rows)
        cohort_rows: List[Dict[str, Any]] = list(modern_rows)

        # ── Step 4: Legacy extension when Modern < floor ──────
        legacy_count = 0
        if modern_count < PR14E_MODERN_COHORT_FLOOR:
            legacy_rows = await _fetch_legacy_cohort(
                socrata, project, target_state=target_state,
            )
            # Secondary fallback (A1 → NB) for Legacy path only —
            # PR #14B T4 carry-over (Stage 2.A) preserved on the
            # Legacy side.
            legacy_cfg = spec.get("legacy_path") or {}
            secondary = legacy_cfg.get("secondary_fallback")
            if (
                secondary
                and len(legacy_rows) < secondary.get("trigger_below", 30)
            ):
                expands_to = secondary.get("expands_to")
                expand_spec = COHORT_CONFIG.get(expands_to)
                if expand_spec is not None:
                    # Build a synthetic project for the expand spec so
                    # _fetch_legacy_cohort routes through the right
                    # legacy_path.
                    expand_proj = dict(project)
                    expand_proj["dob_project_type"] = expands_to
                    extra_rows = await _fetch_legacy_cohort(
                        socrata, expand_proj, target_state=target_state,
                    )
                    seen_keys = {
                        (r.get("bin") or r.get("job__")) for r in legacy_rows
                    }
                    for r in extra_rows:
                        key = r.get("bin") or r.get("job__")
                        if key and key not in seen_keys:
                            legacy_rows.append(r)
                            seen_keys.add(key)

            # ── Step 5: dedup-merge by bbl, then bin ──────────
            # Note: the PR #14D cohort cap (500) is enforced by
            # compute_peer_stats_full when it slices cohort_bins for
            # the BIN→BBL bridge; we don't cap here so the caller
            # can record the pre-cap size in the truncation marker.
            seen_bbls = {
                normalize_bbl(r.get("bbl")) for r in cohort_rows
                if r.get("bbl")
            }
            seen_bins = {r.get("bin") for r in cohort_rows if r.get("bin")}
            for r in legacy_rows:
                bbl_n = normalize_bbl(r.get("bbl"))
                bin_id = r.get("bin")
                if bbl_n and bbl_n in seen_bbls:
                    continue
                if bin_id and bin_id in seen_bins:
                    continue
                cohort_rows.append(r)
                if bbl_n:
                    seen_bbls.add(bbl_n)
                if bin_id:
                    seen_bins.add(bin_id)
            legacy_count = len(cohort_rows) - modern_count

    sample_size = len(cohort_rows)
    low_confidence = (
        COHORT_LOW_CONFIDENCE_FLOOR <= sample_size < COHORT_HIGH_CONFIDENCE_FLOOR
    )

    # ── Step 7: derive existing PR #14B output keys ───────────
    cohort_filter_spec = _build_cohort_filter_spec(project, spec)
    cohort_filter_spec["dob_project_type"] = dob_type

    cohort_job_numbers: List[str] = []
    cohort_bins: List[str] = []
    provenance: List[Dict[str, Any]] = []
    for r in cohort_rows:
        # Stable job_id: prefer pkdm job_filing_name, then BIS job__.
        job_id = (
            r.get("job_filing_name")
            or r.get("job__")
            or r.get("application_number")
            or r.get("job_filing_number")
        )
        if job_id:
            cohort_job_numbers.append(job_id)
        bin_id = r.get("bin") or r.get("bin__")
        if bin_id:
            cohort_bins.append(bin_id)
        provenance.append({
            "job_id": job_id,
            "bbl":    normalize_bbl(r.get("bbl")) if r.get("bbl") else None,
            "bin":    bin_id,
            "source": r.get("source") or "modern",
        })

    # ── Step 8: lifecycle median ────────────────────────────
    if sample_size == 0:
        cohort_median: Optional[float] = None
        lifecycle_skip_reason: Optional[str] = "empty_cohort"
    else:
        cohort_median = _cohort_duration_median(cohort_rows)
        lifecycle_skip_reason = (
            None if cohort_median is not None else "no_duration_data"
        )

    # ── Step 9: active project completion_pct + milestone snap ─
    completion_pct, observed_milestones = await _active_project_completion_pct(
        socrata, project,
        cohort_median_duration_days=cohort_median,
        now=cur_now,
    )

    # ── Step 10: determine completion_method label ─────────
    # If Modern dominates, completion_method = "c_of_o_final"
    # (pkdm-hqz6 IS the C of O dataset). Else BIS fallback.
    completion_method = (
        "c_of_o_final" if modern_count > 0 else "job_status_x_or_u"
    )

    # tier_used / fallback_level retained as label-only for
    # backward compat — Unified Cohort doesn't ladder geographically.
    tier_used: Optional[str] = "borough_type"
    fallback_level: Optional[int] = 4

    base_result.update({
        "tier_used":                   tier_used,
        "fallback_level":              fallback_level,
        "sample_size":                 sample_size,
        "low_confidence_flag":         low_confidence,
        "window_months":               PR14E_MODERN_WINDOW_MONTHS,
        "completion_method":           completion_method,
        "cohort_filter_spec":          cohort_filter_spec,
        "cohort_job_numbers":          cohort_job_numbers,
        "cohort_bins":                 cohort_bins,
        "cohort_median_duration_days": cohort_median,
        "lifecycle_skip_reason":       lifecycle_skip_reason,
        "active_project": {
            "completion_pct":      completion_pct,
            "observed_milestones": observed_milestones,
        },
        # PR #14E surface.
        "cohort_source_segments": {
            "modern_count":         modern_count,
            "legacy_count":         legacy_count,
            "modern_window_months": PR14E_MODERN_WINDOW_MONTHS,
            "legacy_window_start":  PR14E_LEGACY_WINDOW_START_ISO,
            "legacy_window_end":    PR14E_LEGACY_WINDOW_END_ISO,
        },
        "target_state":             target_state,
        "cohort_member_provenance": provenance,
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


# ──────────────────────────────────────────────────────────────────
# PR #14C deferred-import binding
#
# Bound at module bottom (after compute_peer_stats_full is defined)
# so prewarm.py's `from baselines import compute_peer_stats_full`
# resolves successfully when prewarm.py is loaded transitively
# through this import.
#
# Python import semantics:
#   1. baselines.py begins loading; runs all top-level defs.
#   2. Reaches this import; starts loading prewarm.py.
#   3. prewarm.py's top-level `from baselines import …` sees
#      baselines partially loaded but with compute_peer_stats_full
#      already bound (step 1 completed for that name).
#   4. prewarm.py finishes loading.
#   5. baselines.py binds maybe_classify_project_dob_type and
#      finishes loading.
#
# This binding is essential for tests that patch
# ``lib.statistical_engine.baselines.maybe_classify_project_dob_type``
# (Stage 2.A T1 lock — primary spy strategy). Without it, the
# spy would have to target the prewarm module's symbol and the
# patch path would diverge from the Stage 2.A locked convention.
# ──────────────────────────────────────────────────────────────────

from lib.statistical_engine.prewarm import (  # noqa: E402
    maybe_classify_project_dob_type,
)
