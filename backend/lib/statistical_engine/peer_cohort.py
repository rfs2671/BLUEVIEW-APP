"""Phase 1 Week 8 PR-B — k-NN peer cohort matcher.

For each project, find up to N=14 peer BINs from the Phase 1 Week 1
backfilled historical data using a 3-layer cascade. PR-A's
violation_taxonomy classifier provides the recent_violation_bucket
attribute at L1.

Cascade (each layer requires N=14 matches to fire; falls through
otherwise):

  Layer 1 (TIGHTEST): (borough, work_type, phase, recent_violation_bucket)
  Layer 2 (MEDIUM):   (borough, work_type, phase)
  Layer 3 (LOOSE):    (borough, work_type) + schedule_position proximity

Wildcard rule (per Stage 2.A L4): `phase = "unknown"` on EITHER side
of the comparison matches anything. Necessary while daily_log.phase
data is bootstrapping — without wildcard, supplemental BINs (no
daily_logs) would never match production projects at L1/L2.

L3 ranking: peers ordered by ascending |project.schedule_position -
peer.schedule_position|, tiebreak by BIN ascending. Deterministic;
no threshold tuning.

Module is async and DB-heavy. Imported by the
`GET /api/projects/{project_id}/peer-cohort` endpoint at request time
(no caching in this PR).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from lib.statistical_engine.live_mutation import PHASE_TO_RATIO
from lib.statistical_engine.violation_taxonomy import classify_violation

logger = logging.getLogger(__name__)


# ── Locked constants per directive ────────────────────────────────


N_PEERS = 14                            # Stage 2.A L2 — target cohort size
RECENT_VIOLATION_WINDOW_DAYS = 90       # Stage 2.A L3 — lookback window
N_VIOLATIONS_30D_WINDOW_DAYS = 30       # response field (separate from L3)
PERMITS_LOOKBACK_DAYS = 365 * 3         # Stage 2.A L6 — 3-year pool window
SCHEDULE_POSITION_CAP = 1.5             # Phase 1 Week 2 lock (Phase Helper)


# ── Helper functions ──────────────────────────────────────────────


def _resolve_phase_enum_from_ratio(ratio: Optional[float]) -> Optional[str]:
    """Inverse of PHASE_TO_RATIO. Returns the closest phase enum name
    by Euclidean distance to the locked ratio anchors. None input → None.

    Used for fallback when the active project has a schedule_position
    ratio but no daily_log.phase enum — we map the ratio back to the
    nearest enum so the L1 cascade has a phase value to compare.
    """
    if ratio is None:
        return None
    best_phase: Optional[str] = None
    best_dist: float = float("inf")
    for phase, anchor in PHASE_TO_RATIO.items():
        dist = abs(float(ratio) - anchor)
        if dist < best_dist:
            best_dist = dist
            best_phase = phase
    return best_phase


def _phase_matches(
    project_phase: Optional[str],
    peer_phase: Optional[str],
) -> bool:
    """Phase comparison with wildcard semantics per Stage 2.A L4.

    Returns True when:
      • Either side is None (defensive — treats missing data as wildcard)
      • Either side is the literal 'unknown' sentinel
      • Both sides equal

    Used by L1/L2 cascade filters. L3 doesn't call this.
    """
    if project_phase is None or peer_phase is None:
        return True
    if project_phase == "unknown" or peer_phase == "unknown":
        return True
    return project_phase == peer_phase


def _parse_yyyymmdd(s: Optional[str]) -> Optional[datetime]:
    """Parse a YYYYMMDD text date (from ECB violations) to UTC datetime.
    Returns None on malformed input."""
    if not s or not isinstance(s, str) or len(s) < 8:
        return None
    try:
        return datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]),
                        tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_iso_date(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO date prefix (from permits) to UTC datetime."""
    if not s or not isinstance(s, str) or len(s) < 10:
        return None
    try:
        return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]),
                        tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _peer_schedule_position(
    earliest_issued: Optional[datetime],
    cohort_median_days: Optional[float],
    now: datetime,
) -> Optional[float]:
    """Compute schedule_position_ratio for a peer BIN using the ACTIVE
    project's cohort_median_days as the denominator so all peers are
    measured on the same scale. None if either input is missing."""
    if earliest_issued is None or cohort_median_days is None or cohort_median_days <= 0:
        return None
    elapsed_days = (now - earliest_issued).total_seconds() / 86400.0
    elapsed_days = max(0.0, elapsed_days)
    ratio = elapsed_days / float(cohort_median_days)
    return min(ratio, SCHEDULE_POSITION_CAP)


# ── Active-project attribute resolution ───────────────────────────


async def _resolve_active_project_attrs(
    db: Any,
    project: Dict[str, Any],
    now: datetime,
) -> Dict[str, Any]:
    """Resolve the 5 attributes the cascade needs for the active project.

    Returns:
      {
        "bin": str,
        "borough": str | None,
        "work_type": str | None,
        "phase": str (enum or "unknown"),
        "schedule_position_ratio": float | None,
        "recent_violation_bucket": str | None,
        "cohort_median_days": float | None,  (denominator for peer SP)
      }
    """
    bin_id = str(project.get("nyc_bin") or "")
    borough = (project.get("borough") or "").upper().strip() or None

    # work_type: most-recent Initial Permit in 3y window for this BIN.
    work_type: Optional[str] = None
    if bin_id:
        cutoff = (now - timedelta(days=PERMITS_LOOKBACK_DAYS)).strftime(
            "%Y-%m-%dT00:00:00",
        )
        try:
            perm = await db.socrata_permits_historical.find_one(
                {
                    "bin": bin_id,
                    "filing_reason": "Initial Permit",
                    "issued_date": {"$gte": cutoff},
                },
                sort=[("issued_date", -1)],
                projection={"work_type": 1, "borough": 1},
            )
            if perm:
                work_type = (perm.get("work_type") or "").strip() or None
                if not borough:
                    borough = (perm.get("borough") or "").upper().strip() or None
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("[phase1w8] active project work_type lookup failed: %r", e)

    # phase: daily_log.phase if any, otherwise inferred from ratio anchors,
    # otherwise "unknown" sentinel.
    cache = project.get("prediction_cache") or {}
    schedule_position = cache.get("schedule_position_ratio")
    try:
        schedule_position = (
            float(schedule_position) if schedule_position is not None else None
        )
    except (TypeError, ValueError):
        schedule_position = None

    phase: str = "unknown"
    project_id = str(project.get("_id") or project.get("id") or "")
    if project_id and getattr(db, "daily_logs", None) is not None:
        try:
            log = await db.daily_logs.find_one(
                {
                    "project_id": project_id,
                    "phase": {"$nin": [None, ""]},
                    "is_deleted": {"$ne": True},
                },
                sort=[("date", -1)],
                projection={"phase": 1},
            )
            if log and log.get("phase") in PHASE_TO_RATIO:
                phase = log["phase"]
        except Exception as e:  # pragma: no cover
            logger.warning("[phase1w8] active daily_logs lookup failed: %r", e)
    if phase == "unknown":
        inferred = _resolve_phase_enum_from_ratio(schedule_position)
        # We deliberately keep phase="unknown" rather than backfilling
        # from the inferred enum. Inferred is best-effort and L4 wildcard
        # handles the matching; using the strict enum here would over-
        # constrain the cascade against peers whose phase is also unknown.

    # cohort_median_days: from peer_stats_cache.peer_criteria (PR-A)
    cohort_median_days: Optional[float] = None
    peer_criteria = (project.get("peer_stats_cache") or {}).get("peer_criteria") or {}
    raw = peer_criteria.get("cohort_median_duration_days")
    if isinstance(raw, (int, float)):
        cohort_median_days = float(raw)

    # recent_violation_bucket: most-recent ECB violation in 90d window
    # classified via PR-A classify_violation.
    recent_violation_bucket: Optional[str] = None
    if bin_id:
        cutoff_v = (now - timedelta(days=RECENT_VIOLATION_WINDOW_DAYS)).strftime(
            "%Y%m%d",
        )
        try:
            row = await db.socrata_ecb_violations_historical.find_one(
                {"bin": bin_id, "issue_date": {"$gte": cutoff_v}},
                sort=[("issue_date", -1)],
                projection={
                    "violation_type": 1, "violation_description": 1,
                    "issue_date": 1,
                },
            )
            if row:
                recent_violation_bucket = classify_violation(
                    row.get("violation_type"),
                    row.get("violation_description"),
                )
        except Exception as e:  # pragma: no cover
            logger.warning("[phase1w8] active violations lookup failed: %r", e)

    return {
        "bin":                     bin_id,
        "borough":                 borough,
        "work_type":                work_type,
        "phase":                    phase,
        "schedule_position_ratio":  schedule_position,
        "recent_violation_bucket":  recent_violation_bucket,
        "cohort_median_days":       cohort_median_days,
    }


# ── Candidate pool ────────────────────────────────────────────────


async def _build_candidate_pool(
    db: Any,
    now: datetime,
    exclude_bin: Optional[str],
) -> List[Dict[str, Any]]:
    """Build the full candidate pool: every BIN with ≥1 Initial Permit
    in the 3y window. For each BIN, attach work_type + borough +
    earliest_issued from the most-recent Initial Permit.

    Excludes the active project's own BIN (no self-match)."""
    cutoff_iso = (now - timedelta(days=PERMITS_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%dT00:00:00",
    )
    try:
        rows = await db.socrata_permits_historical.find(
            {
                "filing_reason": "Initial Permit",
                "issued_date": {"$gte": cutoff_iso},
            },
            {
                "bin": 1, "bbl": 1, "borough": 1, "work_type": 1,
                "issued_date": 1,
            },
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[phase1w8] pool fetch failed: %r", e)
        return []

    # Dedupe per BIN, keeping most-recent Initial Permit for work_type
    # AND tracking earliest_issued for schedule_position computation.
    most_recent: Dict[str, Dict[str, Any]] = {}
    earliest: Dict[str, datetime] = {}
    for r in rows or []:
        bin_id = r.get("bin")
        if not bin_id or bin_id == exclude_bin:
            continue
        issued_dt = _parse_iso_date(r.get("issued_date"))
        # earliest_issued (for schedule_position)
        if issued_dt is not None:
            cur = earliest.get(bin_id)
            if cur is None or issued_dt < cur:
                earliest[bin_id] = issued_dt
        # most-recent (for work_type)
        cur_recent = most_recent.get(bin_id)
        if cur_recent is None or (
            (r.get("issued_date") or "") > (cur_recent.get("issued_date") or "")
        ):
            most_recent[bin_id] = r

    pool: List[Dict[str, Any]] = []
    for bin_id, latest in most_recent.items():
        borough = (latest.get("borough") or "").upper().strip()
        work_type = (latest.get("work_type") or "").strip()
        if not borough or not work_type:
            continue
        pool.append({
            "bin":             bin_id,
            "bbl":             latest.get("bbl") or None,
            "borough":         borough,
            "work_type":        work_type,
            "earliest_issued":  earliest.get(bin_id),
            # phase + bucket + schedule_position filled by enrichment.
            "phase":            "unknown",
            "recent_violation_bucket": None,
            "schedule_position_ratio": None,
            "n_violations_30d": 0,
        })
    return pool


# ── Enrichment (phase + violations) ───────────────────────────────


async def _enrich_phase(
    db: Any,
    pool: List[Dict[str, Any]],
) -> None:
    """Attach phase to pool entries that have a matching db.projects
    row + daily_log.phase. Mutates pool in place."""
    bins = [p["bin"] for p in pool]
    if not bins:
        return
    projects_coll = getattr(db, "projects", None)
    daily_logs_coll = getattr(db, "daily_logs", None)
    if projects_coll is None or daily_logs_coll is None:
        return

    try:
        project_rows = await projects_coll.find(
            {"nyc_bin": {"$in": bins}, "is_deleted": {"$ne": True}},
            {"_id": 1, "nyc_bin": 1},
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover
        logger.warning("[phase1w8] enrich phase projects failed: %r", e)
        return

    bin_to_pid: Dict[str, str] = {}
    for p in project_rows or []:
        bin_id = p.get("nyc_bin")
        pid = str(p.get("_id") or "")
        if bin_id and pid:
            bin_to_pid[bin_id] = pid
    if not bin_to_pid:
        return

    try:
        log_rows = await daily_logs_coll.find(
            {
                "project_id": {"$in": list(bin_to_pid.values())},
                "phase":      {"$nin": [None, ""]},
                "is_deleted": {"$ne": True},
            },
            {"project_id": 1, "phase": 1, "date": 1},
        ).sort("date", -1).to_list(length=None)
    except Exception as e:  # pragma: no cover
        logger.warning("[phase1w8] enrich phase daily_logs failed: %r", e)
        return

    seen_projects: Set[str] = set()
    phase_by_pid: Dict[str, str] = {}
    for log in log_rows or []:
        pid = str(log.get("project_id") or "")
        if not pid or pid in seen_projects:
            continue
        phase = log.get("phase")
        if phase in PHASE_TO_RATIO:
            phase_by_pid[pid] = phase
            seen_projects.add(pid)

    pid_to_phase = phase_by_pid
    # Reverse-map BIN → phase via bin_to_pid → pid_to_phase
    for entry in pool:
        pid = bin_to_pid.get(entry["bin"])
        if pid and pid in pid_to_phase:
            entry["phase"] = pid_to_phase[pid]


async def _enrich_violations(
    db: Any,
    pool: List[Dict[str, Any]],
    now: datetime,
) -> None:
    """For each pool entry: query ECB violations in 90d window, classify
    most-recent via PR-A taxonomy, attach as recent_violation_bucket.
    Also compute n_violations_30d count for the response payload."""
    if not pool:
        return
    bins = [p["bin"] for p in pool]
    cutoff_v90 = (now - timedelta(days=RECENT_VIOLATION_WINDOW_DAYS)).strftime("%Y%m%d")
    cutoff_v30 = (now - timedelta(days=N_VIOLATIONS_30D_WINDOW_DAYS)).strftime("%Y%m%d")
    try:
        vrows = await db.socrata_ecb_violations_historical.find(
            {"bin": {"$in": bins}, "issue_date": {"$gte": cutoff_v90}},
            {
                "bin": 1, "issue_date": 1,
                "violation_type": 1, "violation_description": 1,
            },
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover
        logger.warning("[phase1w8] enrich violations failed: %r", e)
        return

    most_recent_violation: Dict[str, Dict[str, Any]] = {}
    n30: Dict[str, int] = {}
    for v in vrows or []:
        bin_id = v.get("bin")
        issue = v.get("issue_date") or ""
        if not bin_id:
            continue
        cur = most_recent_violation.get(bin_id)
        if cur is None or issue > (cur.get("issue_date") or ""):
            most_recent_violation[bin_id] = v
        if issue >= cutoff_v30:
            n30[bin_id] = n30.get(bin_id, 0) + 1

    for entry in pool:
        v = most_recent_violation.get(entry["bin"])
        if v is not None:
            entry["recent_violation_bucket"] = classify_violation(
                v.get("violation_type"), v.get("violation_description"),
            )
        entry["n_violations_30d"] = n30.get(entry["bin"], 0)


# ── Cascade filtering ─────────────────────────────────────────────


def _l1_filter(
    pool: List[Dict[str, Any]],
    *,
    borough: str,
    work_type: str,
    phase: str,
    violation_bucket: Optional[str],
) -> Tuple[List[Dict[str, Any]], bool]:
    """L1 filter — (borough, work_type, phase, violation_bucket).
    Returns (matched_peers, phase_wildcard_used).

    phase_wildcard_used = True if at least one matched peer relied on
    the wildcard branch (peer.phase = 'unknown' or project.phase =
    'unknown') rather than strict equality.
    """
    matches = []
    wildcard_used = False
    for entry in pool:
        if entry["borough"] != borough:
            continue
        if entry["work_type"] != work_type:
            continue
        if not _phase_matches(phase, entry["phase"]):
            continue
        # bucket: allow either side None to match (rare but defensive)
        e_bucket = entry["recent_violation_bucket"]
        if violation_bucket is None and e_bucket is None:
            pass  # matches
        elif violation_bucket == e_bucket:
            pass  # matches
        else:
            continue
        # Track wildcard usage
        if phase != entry["phase"] and (
            phase == "unknown" or entry["phase"] == "unknown"
        ):
            wildcard_used = True
        matches.append(entry)
    return matches, wildcard_used


def _l2_filter(
    pool: List[Dict[str, Any]],
    *,
    borough: str,
    work_type: str,
    phase: str,
) -> Tuple[List[Dict[str, Any]], bool]:
    """L2 filter — (borough, work_type, phase). Drops violation_bucket."""
    matches = []
    wildcard_used = False
    for entry in pool:
        if entry["borough"] != borough:
            continue
        if entry["work_type"] != work_type:
            continue
        if not _phase_matches(phase, entry["phase"]):
            continue
        if phase != entry["phase"] and (
            phase == "unknown" or entry["phase"] == "unknown"
        ):
            wildcard_used = True
        matches.append(entry)
    return matches, wildcard_used


def _l3_filter_and_rank(
    pool: List[Dict[str, Any]],
    *,
    borough: str,
    work_type: str,
    project_schedule_position: Optional[float],
) -> List[Dict[str, Any]]:
    """L3 filter — (borough, work_type). Ranks by schedule_position
    proximity (Euclidean distance), tiebreak by BIN ascending."""
    matches = [
        e for e in pool
        if e["borough"] == borough and e["work_type"] == work_type
    ]
    project_sp = (
        float(project_schedule_position) if project_schedule_position is not None
        else None
    )

    def _key(entry):
        peer_sp = entry.get("schedule_position_ratio")
        # When either side is missing, push to the end via large distance.
        if project_sp is None or peer_sp is None:
            return (float("inf"), entry["bin"])
        # Round to 6 decimal places to avoid float-precision artifacts
        # treating semantically-tied distances as unequal — e.g.,
        # |0.30 - 0.50| = 0.2000000000000007 vs |0.70 - 0.50| =
        # 0.19999999999999996. With rounding, both → 0.2 and the
        # BIN-ascending tiebreak fires deterministically.
        dist = round(abs(float(peer_sp) - project_sp), 6)
        return (dist, entry["bin"])

    matches.sort(key=_key)
    return matches


# ── Display helpers for disclosure_text (PR-B hotfix) ─────────────
#
# Pre-rendered disclosure_text is dropped verbatim into the FE per
# Stage 2.A L8 — must be GC-readable. Mirrors the conventions of
# frontend/src/utils/displayHelpers.js (titleCase / boroughLabel)
# so backend-rendered prose matches frontend-rendered prose elsewhere
# in the app. PR #15D.1 C5 lock + PR #37 L7 lock for MEP acronym.


def _borough_label(raw: str) -> str:
    """ALL-CAPS borough storage → title-case for prose.
    'BROOKLYN' → 'Brooklyn'. 'STATEN ISLAND' → 'Staten Island'.
    Empty/None safe — returns ''."""
    if not raw:
        return ""
    # Same idiom as frontend's titleCase(): lowercase, split on
    # whitespace, capitalize each word.
    return " ".join(
        w.capitalize() for w in str(raw).lower().split() if w
    )


def _phase_label(raw: Optional[str]) -> str:
    """Phase enum storage (lowercase) → display form.

    Special case: 'mep' renders as 'MEP' (acronym; PR #37 L7 lock).
    All other phase enums stay lowercase per the locked enum
    convention ('foundation', 'superstructure', 'interior', 'finishes',
    'closeout'). The 'unknown' sentinel also stays lowercase as it
    reads naturally in prose ('... in unknown phase').
    """
    if not raw:
        return ""
    s = str(raw).strip().lower()
    if s == "mep":
        return "MEP"
    return s


# ── Disclosure text (Stage 2.A L10) ────────────────────────────────


def _format_disclosure(
    *,
    layer: int,
    n_matches: int,
    borough: str,
    work_type: str,
    phase: Optional[str],
    phase_wildcard_expanded: bool,
    violation_bucket: Optional[str],
) -> str:
    """Pre-rendered disclosure text per L10 tiering. Applies display
    casing helpers so output is GC-readable per PR #15D.1 C5 lock."""
    borough = _borough_label(borough)
    phase = _phase_label(phase) if phase else phase
    if layer == 1:
        if phase_wildcard_expanded:
            return (
                f"Based on {n_matches} similar {borough} {work_type} "
                f"projects (phase data limited) with recent "
                f"{violation_bucket} violations"
            )
        return (
            f"Based on {n_matches} similar {borough} {work_type} "
            f"projects in {phase} phase with recent "
            f"{violation_bucket} violations"
        )
    if layer == 2:
        # Per L10 spec, L2 always references the active project's phase
        # regardless of whether peers matched via wildcard or strict
        # equality. The cohort_summary.phase_wildcard_expanded flag is
        # the transparency signal for the wildcard case.
        return (
            f"Based on {n_matches} similar {borough} {work_type} "
            f"projects in {phase} phase"
        )
    # Layer 3
    return (
        f"Based on {n_matches} similar {borough} {work_type} "
        f"projects (closest schedule position)"
    )


# ── Public driver ─────────────────────────────────────────────────


async def compute_peer_cohort(
    db: Any,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute the peer cohort for a project via the 3-layer cascade.

    Returns the response dict per Stage 2.A L8.
    """
    cur_now = now or datetime.now(timezone.utc)
    if cur_now.tzinfo is None:
        cur_now = cur_now.replace(tzinfo=timezone.utc)

    # Step 1 — resolve active project attributes.
    attrs = await _resolve_active_project_attrs(db, project, cur_now)
    borough = attrs["borough"]
    work_type = attrs["work_type"]

    # Step 2 — build + enrich candidate pool.
    pool = await _build_candidate_pool(
        db, cur_now, exclude_bin=attrs["bin"],
    )
    # Compute peer schedule_position using the active project's cohort
    # median as a shared denominator — so distances are comparable.
    cohort_median = attrs["cohort_median_days"]
    for entry in pool:
        entry["schedule_position_ratio"] = _peer_schedule_position(
            entry.get("earliest_issued"), cohort_median, cur_now,
        )
    await _enrich_phase(db, pool)
    await _enrich_violations(db, pool, cur_now)

    pool_size = len(pool)

    # Step 3 — cascade. Borough/work_type required to even attempt
    # matching; without them, all layers return empty.
    layer_used = 3
    matched: List[Dict[str, Any]] = []
    wildcard_used = False
    if borough and work_type:
        # L1
        l1_matches, l1_wildcard = _l1_filter(
            pool,
            borough=borough,
            work_type=work_type,
            phase=attrs["phase"],
            violation_bucket=attrs["recent_violation_bucket"],
        )
        if len(l1_matches) >= N_PEERS:
            layer_used = 1
            matched = l1_matches[:N_PEERS]
            wildcard_used = l1_wildcard
        else:
            # L2
            l2_matches, l2_wildcard = _l2_filter(
                pool,
                borough=borough,
                work_type=work_type,
                phase=attrs["phase"],
            )
            if len(l2_matches) >= N_PEERS:
                layer_used = 2
                matched = l2_matches[:N_PEERS]
                wildcard_used = l2_wildcard
            else:
                # L3 (terminal) — always returns best available, even
                # if <14.
                layer_used = 3
                ranked = _l3_filter_and_rank(
                    pool,
                    borough=borough,
                    work_type=work_type,
                    project_schedule_position=attrs["schedule_position_ratio"],
                )
                matched = ranked[:N_PEERS]
                wildcard_used = False  # L3 doesn't use phase

    # Step 4 — assemble response.
    disclosure = _format_disclosure(
        layer=layer_used,
        n_matches=len(matched),
        borough=borough or "",
        work_type=work_type or "",
        phase=attrs["phase"] if layer_used in (1, 2) else None,
        phase_wildcard_expanded=wildcard_used,
        violation_bucket=attrs["recent_violation_bucket"] if layer_used == 1 else None,
    )

    return {
        "layer_used":     layer_used,
        "n_matches":      len(matched),
        "cohort_summary": {
            "borough":                  borough or "",
            "work_type":                 work_type or "",
            "phase":                     attrs["phase"] if layer_used in (1, 2) else None,
            "phase_wildcard_expanded":   wildcard_used,
            "violation_bucket":          attrs["recent_violation_bucket"] if layer_used == 1 else None,
            "pool_size":                 pool_size,
        },
        "peers": [
            {
                "bin":                     e["bin"],
                "bbl":                     e.get("bbl"),
                "work_type":               e["work_type"],
                "phase":                   e["phase"] if e["phase"] != "unknown" else None,
                "schedule_position_ratio": e.get("schedule_position_ratio"),
                "n_violations_30d":        int(e.get("n_violations_30d") or 0),
            }
            for e in matched
        ],
        "disclosure_text": disclosure,
        "matched_at":      cur_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
