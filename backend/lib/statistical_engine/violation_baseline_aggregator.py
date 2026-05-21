"""Phase 1 Week 3 PR-C — weekly cohort baseline aggregator.

Computes 30-day violation rates per (borough, work_type, phase) cohort
from the Phase 1 Week 1 backfilled historical data + the PR-A/PR-B
phase tracking. Writes one row per cohort per weekly run to
``violation_baseline_aggregates``.

Computation flow (Python-side grouping; no Mongo aggregate pipelines):

  1. Define window = [run_date - 30d, run_date)
  2. Pull violations in window from socrata_ecb_violations_historical
  3. Pull Initial Permits in window from socrata_permits_historical;
     dedupe to most-recent permit per BIN (work_type classifier)
  4. The set of BINs with permits in window IS the "active projects"
     denominator. BINs without permits in window don't count even if
     they have violations (a violation against an inactive site has
     no permit context to classify it).
  5. For each active BIN: optionally resolve project + most-recent
     daily_log.phase. BINs without a matching project, or with a
     project but no phase-stamped daily_log, get phase="unknown".
  6. Group active BINs by (borough, work_type, phase). Per cohort:
       n_active_projects = |BINs in cohort|
       n_violations = sum over BINs in cohort of violations against
                      that BIN in the window
       rate_per_project_day = n_violations / (n_active_projects *
                              window_days)
  7. Insert one document per cohort.

Downstream: GET /api/baseline-aggregates exposes the rows for Phase 1
Week 8+ k-NN cohort similarity (PR-A's resolver provides per-project
schedule_position_ratio; this aggregator provides per-cohort baseline
rates that ratio is compared against).

Cohort row schema (see _build_aggregate_row):

  {
    borough:                  str  (full uppercase name)
    work_type:                str  (from most-recent Initial Permit)
    phase:                    str  (foundation|...|closeout|unknown)
    window_start:             datetime UTC
    window_end:               datetime UTC
    n_violations:             int
    n_active_projects:        int
    n_projects_known_phase:   int
    n_projects_unknown_phase: int
    rate_per_project_day:     float
    computed_at:              datetime UTC
  }
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────


# socrata_ecb_violations_historical stores boro as a BIS numeric code
# ("1"–"5"). Maps back to the full uppercase borough name used in the
# aggregate row's borough field. Note: rbx6-tga4 (permits) carries the
# full text borough directly, so the aggregator reads borough from the
# permit record — this mapping is here as a defensive fallback for
# legacy / partial-data BINs.
_BIS_BORO_TO_NAME: Dict[str, str] = {
    "1": "MANHATTAN",
    "2": "BRONX",
    "3": "BROOKLYN",
    "4": "QUEENS",
    "5": "STATEN ISLAND",
}

# Phase 1 Week 3 — phase enum values that count as "known". Anything
# outside this set (including None, "", and the explicit "unknown"
# sentinel) lands in the unknown cohort.
_KNOWN_PHASES: Set[str] = {
    "foundation", "superstructure", "interior",
    "mep", "finishes", "closeout",
}


# ── Public driver ─────────────────────────────────────────────────


async def compute_baseline_aggregates(
    db: Any,
    *,
    run_date: Optional[datetime] = None,
    window_days: int = 30,
) -> Dict[str, Any]:
    """Compute and persist one set of cohort baseline aggregates.

    Args:
      db          — Motor DB handle. Reads from socrata_ecb_violations_
                    historical, socrata_permits_historical, projects,
                    daily_logs; writes to violation_baseline_aggregates.
      run_date    — Anchor for the 30d window's upper bound. Defaults
                    to now-UTC. Passed explicitly in tests for
                    determinism.
      window_days — Window length. Default 30 per Stage 2.A lock.

    Returns a summary dict suitable for cron logging:
      n_rows_written, n_cohorts_processed, window_start, window_end,
      elapsed_seconds.
    """
    t_start = time.perf_counter()
    window_end = run_date or datetime.now(timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    window_start = window_end - timedelta(days=window_days)
    # rbx6-tga4 permits store issued_date as ISO ("2026-05-13T00:00:00.000")
    # from Socrata's calendar_date type → ISO filter works.
    window_start_iso = window_start.strftime("%Y-%m-%dT%H:%M:%S")
    window_end_iso = window_end.strftime("%Y-%m-%dT%H:%M:%S")
    # 6bgk-3dad ECB violations store issue_date as YYYYMMDD text
    # ("20260518") from Socrata's text type → need YYYYMMDD bounds.
    # Lex comparison fails against ISO ("20260518" > "2026-05-21T..." at
    # position 4: '0' > '-'). 30-day baseline cron at 3am ET doesn't
    # need sub-day precision so whole-day-aligned bounds are fine.
    window_start_yyyymmdd = window_start.strftime("%Y%m%d")
    window_end_yyyymmdd = window_end.strftime("%Y%m%d")

    # Step 1 — pull violations in window.
    violations_by_bin: Dict[str, int] = defaultdict(int)
    try:
        vrows = await db.socrata_ecb_violations_historical.find(
            {
                "issue_date": {
                    "$gte": window_start_yyyymmdd,
                    "$lt":  window_end_yyyymmdd,
                },
            },
            {"bin": 1, "issue_date": 1},
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[phase1w3] violations fetch failed: %r", e,
        )
        vrows = []
    for v in vrows or []:
        bin_id = v.get("bin")
        if bin_id:
            violations_by_bin[bin_id] += 1

    # Step 2 — pull Initial Permits in window; dedupe to most-recent
    # issued_date per BIN.
    most_recent_permit: Dict[str, Dict[str, Any]] = {}
    try:
        prows = await db.socrata_permits_historical.find(
            {
                "filing_reason": "Initial Permit",
                "issued_date": {
                    "$gte": window_start_iso,
                    "$lt":  window_end_iso,
                },
            },
            {"bin": 1, "issued_date": 1, "borough": 1, "work_type": 1},
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[phase1w3] permits fetch failed: %r", e)
        prows = []
    for p in prows or []:
        bin_id = p.get("bin")
        if not bin_id:
            continue
        cur = most_recent_permit.get(bin_id)
        # issued_date is ISO text — lex-compare = chronological compare
        # for matched-format strings.
        if cur is None or (p.get("issued_date") or "") > (cur.get("issued_date") or ""):
            most_recent_permit[bin_id] = p

    if not most_recent_permit:
        # No active projects in window → no cohorts → nothing to write.
        elapsed = time.perf_counter() - t_start
        logger.info(
            "[phase1w3] aggregator: no active projects in window "
            "[%s, %s); 0 rows written.",
            window_start_iso, window_end_iso,
        )
        return {
            "n_rows_written":      0,
            "n_cohorts_processed": 0,
            "window_start":        window_start,
            "window_end":          window_end,
            "elapsed_seconds":     elapsed,
        }

    # Step 3 — resolve phase per active BIN.
    phase_by_bin = await _resolve_phase_per_bin(
        db, list(most_recent_permit.keys()),
    )

    # Step 4 — group BINs by (borough, work_type, phase). Track per-
    # cohort: BIN set + violation count.
    cohort_bins: Dict[Tuple[str, str, str], Set[str]] = defaultdict(set)
    cohort_violations: Dict[Tuple[str, str, str], int] = defaultdict(int)

    for bin_id, permit in most_recent_permit.items():
        borough = (permit.get("borough") or "").upper().strip()
        if not borough:
            # No borough on the permit — skip this BIN. Operator can
            # later add a fallback path via _BIS_BORO_TO_NAME from the
            # violation row if this becomes a real coverage gap.
            continue
        work_type = (permit.get("work_type") or "Unknown").strip() or "Unknown"
        phase = phase_by_bin.get(bin_id, "unknown")

        key = (borough, work_type, phase)
        cohort_bins[key].add(bin_id)
        cohort_violations[key] += violations_by_bin.get(bin_id, 0)

    # Step 5 — assemble + insert aggregate rows.
    now_utc = datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    for key, bins in cohort_bins.items():
        row = _build_aggregate_row(
            cohort_key=key,
            bin_set=bins,
            n_violations=cohort_violations.get(key, 0),
            window_start=window_start,
            window_end=window_end,
            window_days=window_days,
            computed_at=now_utc,
        )
        rows.append(row)

    if rows:
        try:
            await db.violation_baseline_aggregates.insert_many(rows)
        except Exception as e:  # pragma: no cover — defensive
            logger.exception(
                "[phase1w3] insert_many failed: %r", e,
            )

    elapsed = time.perf_counter() - t_start
    logger.info(
        "[phase1w3] aggregator: %d cohorts, %d rows in %.2fs "
        "(window [%s, %s))",
        len(cohort_bins), len(rows), elapsed,
        window_start_iso, window_end_iso,
    )
    return {
        "n_rows_written":      len(rows),
        "n_cohorts_processed": len(cohort_bins),
        "window_start":        window_start,
        "window_end":          window_end,
        "elapsed_seconds":     elapsed,
    }


# ── Internal helpers ──────────────────────────────────────────────


async def _resolve_phase_per_bin(
    db: Any,
    active_bins: List[str],
) -> Dict[str, str]:
    """For each active BIN, resolve its current phase:
      1. Find a matching db.projects entry by nyc_bin
      2. Find the most-recent daily_log with a non-null phase for that
         project_id
      3. If either step fails or yields no phase, fall back to "unknown"
    """
    out: Dict[str, str] = {}
    if not active_bins:
        return out

    projects_coll = getattr(db, "projects", None)
    if projects_coll is None:
        return out

    try:
        project_rows = await projects_coll.find(
            {
                "nyc_bin": {"$in": active_bins},
                "is_deleted": {"$ne": True},
            },
            {"_id": 1, "nyc_bin": 1},
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[phase1w3] projects lookup failed: %r", e,
        )
        return out

    project_id_to_bin: Dict[str, str] = {}
    for p in project_rows or []:
        bin_id = p.get("nyc_bin")
        pid = str(p.get("_id") or "")
        if bin_id and pid:
            project_id_to_bin[pid] = bin_id

    if not project_id_to_bin:
        return out

    daily_logs_coll = getattr(db, "daily_logs", None)
    if daily_logs_coll is None:
        return out

    try:
        log_rows = await daily_logs_coll.find(
            {
                "project_id": {"$in": list(project_id_to_bin.keys())},
                "phase": {"$nin": [None, ""]},
                "is_deleted": {"$ne": True},
            },
            {"project_id": 1, "phase": 1, "date": 1},
        ).sort("date", -1).to_list(length=None)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[phase1w3] daily_logs lookup failed: %r", e,
        )
        return out

    # First non-null phase per project_id wins (rows pre-sorted by date
    # descending).
    seen_projects: Set[str] = set()
    for log in log_rows or []:
        pid = str(log.get("project_id") or "")
        if not pid or pid in seen_projects:
            continue
        phase = log.get("phase")
        if phase not in _KNOWN_PHASES:
            # Defensive: unknown enum values (typos, future additions
            # not yet in this aggregator's _KNOWN_PHASES) fall through
            # to "unknown" cohort rather than getting a meaningless
            # cohort of their own.
            continue
        seen_projects.add(pid)
        bin_id = project_id_to_bin.get(pid)
        if bin_id:
            out[bin_id] = phase
    return out


def _build_aggregate_row(
    *,
    cohort_key: Tuple[str, str, str],
    bin_set: Set[str],
    n_violations: int,
    window_start: datetime,
    window_end: datetime,
    window_days: int,
    computed_at: datetime,
) -> Dict[str, Any]:
    """Construct one aggregate row dict. Pure for testability."""
    borough, work_type, phase = cohort_key
    n_active = len(bin_set)
    # n_projects_known/unknown are denormalized hints — since we
    # partition by phase already, every BIN in a cohort shares the
    # cohort's phase. So one of the two is n_active and the other is 0.
    n_known = n_active if phase in _KNOWN_PHASES else 0
    n_unknown = n_active if phase == "unknown" else 0
    rate = (
        n_violations / (n_active * window_days)
        if (n_active > 0 and window_days > 0) else 0.0
    )
    return {
        "borough":                  borough,
        "work_type":                work_type,
        "phase":                    phase,
        "window_start":             window_start,
        "window_end":               window_end,
        "n_violations":             int(n_violations),
        "n_active_projects":        int(n_active),
        "n_projects_known_phase":   int(n_known),
        "n_projects_unknown_phase": int(n_unknown),
        "rate_per_project_day":     float(rate),
        "computed_at":              computed_at,
    }
