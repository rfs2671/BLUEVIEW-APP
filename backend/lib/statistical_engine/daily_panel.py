"""PR #15A — Predictive Inference Engine Phase 1.

Daily panel builder + validation ledger helpers + cohort-derived
milestone calibration + district caseload proxy.

The nightly cron materializes a ``daily_panels`` collection: one
row per ``(cohort_member, day_in_lifecycle)`` tuple for every
active project's peer cohort. Each row carries:

  • 5-feature state vector x_d
        x[0] active_swo_flag                  (int 0|1, BIN-keyed)
        x[1] complaint_velocity_14d           (raw count, BIN+BBL)
        x[2] days_since_last_violation        (clamped [0, 90])
        x[3] derived_lifecycle_stage_pct      (cohort-calibrated)
        x[4] district_caseload_proxy_days     (CD-keyed rolling 30d)

  • Outcome columns
        outcome_violation_d                   (bool — severe ECB on day d)
        outcome_violation_d_to_d_plus_7       (bool | None — None for
                                              trailing 7 days per T5)

  • Sample weight (Lock B: Modern=1.0, Legacy=0.4)
  • Cohort segment marker (Lock B propagation)

Locked design (Stage 2.A):
  T1 hybrid — panel snapshots active_swo_flag per (BIN, day) via
              last-disposition-wins walk of full history.
  T2 raw    — complaint_velocity_14d at panel build is integer
              count; Lock C ageing applied at x_now (PR #15B).
  T3 cache  — caseload_proxy cached per community_board across
              projects in the same nightly run.
  T4 SoQL   — severity IN ('CLASS - 1', 'CLASS - 2', 'Hazardous').
  T5 None   — trailing 7 days right-censored.
  T6 hash   — SHA1 of sorted provenance.bbl list; skip rebuild on
              match.
  T7 upsert — one canonical validation_ledger entry per
              (project_id, calendar_date).
  T8 split  — active project EXCLUDED from cohort panel
              (train/eval separation).
  Lock 1.2  — cohort-derived milestone pct overrides hardcoded
              defaults when N>=30 contributors per milestone.
  Lock B    — sample weights Modern=1.0, Legacy=0.4.
  Chapter 33 — Safety Cliff floor applied in baselines.
              _derive_target_state_for_project (see baselines.py).

Source datasets (curl-validated in Stage 1):
  • 6bgk-3dad   ECB Violations    issue_date YYYYMMDD numeric
  • eabe-havv   DOB Complaints    date_entered MM/DD/YYYY text
  • erm2-nwe9   311 Complaints    created_date ISO with .000
  • rbx6-tga4   DOB NOW Permits   approved/issued_date ISO
  • pkdm-hqz6   DOB NOW C of O    c_of_o_issuance_date MM/DD/YY
                                  HH:MM:SS AM/PM
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from lib.statistical_engine.socrata_client import (
    DATASET_COMPLAINTS_311,
    DATASET_DOB_PERMITS,
    SocrataClient,
    SocrataQueryError,
)
from lib.statistical_engine.baselines import (
    _MILESTONE_COMPLETION_PCT,
    _parse_bis_mdy_date,
    _parse_pkdm_date,
    _parse_socrata_dt,
    _parse_socrata_yyyymmdd,
    _soql_in,
    _soql_quote,
    _chunk,
    SOQL_IN_CHUNK_SIZE,
    normalize_bbl,
)

logger = logging.getLogger(__name__)


# ── PR #15A constants ─────────────────────────────────────────────

# Locked source dataset IDs (curl-validated in Stage 1).
DATASET_DOB_ECB_VIOLATIONS = "6bgk-3dad"
DATASET_DOB_COMPLAINTS     = "eabe-havv"

# Locked severity filter — only severe ECB violations count toward
# outcome_violation_d. Stage 1 verified the enum exactly:
# {CLASS - 1, CLASS - 2, Hazardous, CLASS - 3, Non-Hazardous, Unknown}.
SEVERE_ECB_SEVERITIES = ("CLASS - 1", "CLASS - 2", "Hazardous")

# SWO state-machine disposition codes (Stage 2.A T1 lock).
SWO_ACTIVATING_CODES   = ("A8", "A1")   # close work / issue work-stop
SWO_DEACTIVATING_CODES = ("A9", "B1")   # vacate / rescind
ALL_SWO_CODES          = SWO_ACTIVATING_CODES + SWO_DEACTIVATING_CODES

# Rolling 30-day window for district caseload proxy.
CASELOAD_PROXY_WINDOW_DAYS = 30

# Cohort minimum contributors floor for milestone calibration —
# below this, fall back to hardcoded _MILESTONE_COMPLETION_PCT.
COHORT_MILESTONE_MIN_CONTRIBUTORS = 30

# Schema version stamp on every daily_panels row (mirror pattern
# of PR14E_SCHEMA_VERSION).
PR15A_PANEL_SCHEMA_VERSION = "pr15a_v1"

# Default panel build window — 540 days covers a typical 18-month
# A1 alteration lifecycle plus headroom.
DEFAULT_PANEL_WINDOW_DAYS = 540

# Per-CD caseload proxy cache. Cleared per nightly cron run.
# Keyed on community_board string; value is the rolling-30d median
# disposition lag (float days).
_caseload_proxy_cache: Dict[str, float] = {}


# ── Provenance checksum (T6) ──────────────────────────────────────


def _provenance_checksum(
    cohort_member_provenance: List[Dict[str, Any]],
) -> str:
    """PR #15A T6 lock — SHA1 of sorted ``bbl`` values from the
    cohort provenance list. Nightly cron compares incoming
    checksum vs persisted ``daily_panel_provenance_checksum`` and
    skips rebuild when unchanged.

    Sorting ensures order-independent identity (PR #14E's modern→
    legacy merge order isn't deterministic). Strips ``.0+`` suffix
    on each bbl via ``normalize_bbl`` so PLUTO-format mismatches
    don't produce phantom rebuilds.
    """
    bbls = sorted(
        normalize_bbl(entry.get("bbl"))
        for entry in (cohort_member_provenance or [])
        if entry.get("bbl")
    )
    payload = "|".join(b for b in bbls if b)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


# ── ECB date parser ───────────────────────────────────────────────

_ECB_DATE_RE = re.compile(r"^\s*(\d{4})(\d{2})(\d{2})\s*$")


def _parse_ecb_yyyymmdd_date(raw: Any) -> Optional[datetime]:
    """Parse 6bgk-3dad ``issue_date`` (YYYYMMDD 8-digit numeric
    text) into a tz-aware UTC datetime. Distinct from
    ``_parse_socrata_yyyymmdd`` because that helper is in
    baselines.py — re-implemented here so PR #15A's panel code
    can import a single PR15A-owned date helper.

    Examples:
      "20240115" → datetime(2024, 1, 15, tz=UTC)
      None/""/malformed → None
    """
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    m = _ECB_DATE_RE.match(raw)
    if not m:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


# ── SWO state machine (T1) ────────────────────────────────────────


async def _classify_swo_disposition_codes_per_bin(
    socrata,
    *,
    bin_list: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Query eabe-havv for SWO-relevant disposition events keyed
    by BIN. Returns per-BIN list of events sorted by
    disposition_date.

    SWO codes (Stage 2.A T1):
      A8 — close work (active SWO issued)
      A1 — issue work-stop (active SWO issued)
      A9 — vacate (clears SWO)
      B1 — rescind (clears SWO)
    """
    out: Dict[str, List[Dict[str, Any]]] = {b: [] for b in bin_list}
    if not bin_list:
        return out

    where_template = " AND ".join([
        _soql_in("bin", []),                              # placeholder, replaced
        _soql_in("disposition_code", list(ALL_SWO_CODES)),
    ])

    async def _query_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
        try:
            return await socrata.query(
                DATASET_DOB_COMPLAINTS,
                where=" AND ".join([
                    _soql_in("bin", chunk),
                    _soql_in("disposition_code", list(ALL_SWO_CODES)),
                ]),
                select=[
                    "bin", "complaint_number", "date_entered",
                    "disposition_code", "disposition_date",
                ],
                limit=10000,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[daily_panel] eabe-havv SWO chunk failed: %r", e,
            )
            return []

    chunks = list(_chunk(bin_list, SOQL_IN_CHUNK_SIZE))
    chunk_results = await asyncio.gather(
        *(_query_chunk(c) for c in chunks),
    )
    for rows in chunk_results:
        for r in rows:
            b = r.get("bin")
            if not b or b not in out:
                continue
            disp_dt = _parse_bis_mdy_date(
                r.get("disposition_date") or r.get("date_entered"),
            )
            if disp_dt is None:
                continue
            out[b].append({
                "disposition_date": disp_dt,
                "disposition_code": r.get("disposition_code"),
                "complaint_number": r.get("complaint_number"),
            })
    # Sort each BIN's events chronologically.
    for b in out:
        out[b].sort(key=lambda e: e["disposition_date"])
    return out


def _compute_active_swo_timeline_per_bin(
    disposition_events: List[Dict[str, Any]],
    lifecycle_start: datetime,
    lifecycle_end: datetime,
) -> List[Tuple[datetime, int]]:
    """Walk per-BIN disposition events; emit (date, active_flag)
    transition list. Last-disposition-wins per T1.

    Returns sorted list of state transitions covering
    [lifecycle_start, lifecycle_end]. Initial state at
    lifecycle_start is determined by the most recent disposition
    BEFORE lifecycle_start (if any).
    """
    # Initial state: scan dispositions before lifecycle_start;
    # last one wins.
    initial_state = 0
    for ev in disposition_events:
        if ev["disposition_date"] < lifecycle_start:
            if ev["disposition_code"] in SWO_ACTIVATING_CODES:
                initial_state = 1
            elif ev["disposition_code"] in SWO_DEACTIVATING_CODES:
                initial_state = 0

    transitions: List[Tuple[datetime, int]] = [
        (lifecycle_start, initial_state),
    ]
    current_state = initial_state
    for ev in disposition_events:
        if ev["disposition_date"] < lifecycle_start:
            continue
        if ev["disposition_date"] > lifecycle_end:
            break
        if ev["disposition_code"] in SWO_ACTIVATING_CODES:
            new_state = 1
        elif ev["disposition_code"] in SWO_DEACTIVATING_CODES:
            new_state = 0
        else:
            continue
        if new_state != current_state:
            transitions.append((ev["disposition_date"], new_state))
            current_state = new_state
    return transitions


def _active_swo_flag_on_day(
    transitions: List[Tuple[datetime, int]],
    target_day: datetime,
) -> int:
    """Look up the active_swo_flag value at target_day given a
    sorted transition list. Returns the flag in effect on
    target_day (most recent transition <= target_day)."""
    flag = 0
    for ts, state in transitions:
        if ts > target_day:
            break
        flag = state
    return flag


# ── Complaint velocity (T2) ───────────────────────────────────────


def _combined_complaint_velocity(
    bin_complaint_dates: List[datetime],
    bbl_complaint_dates: List[datetime],
    *,
    target_date: datetime,
    window_days: int = 14,
) -> int:
    """Raw count of (BIN eabe-havv) ∪ (BBL erm2-nwe9) complaints
    within (target_date - window_days, target_date]. Per Stage 2.A
    T2 lock — raw count, not aged. Lock C ageing applied later at
    x_now (PR #15B).
    """
    window_start = target_date - timedelta(days=window_days)
    count = 0
    for d in bin_complaint_dates:
        if window_start < d <= target_date:
            count += 1
    for d in bbl_complaint_dates:
        if window_start < d <= target_date:
            count += 1
    return count


# ── days_since_last_violation clamp (x[2]) ────────────────────────


def _compute_days_since_last_violation_clamped(
    violation_dates: List[datetime],
    target_date: datetime,
    clamp_max: int = 90,
) -> int:
    """Days since most recent severe violation, clamped to
    [0, clamp_max]. If no prior violation, returns clamp_max."""
    prior = [d for d in violation_dates if d <= target_date]
    if not prior:
        return clamp_max
    most_recent = max(prior)
    delta = (target_date - most_recent).days
    return max(0, min(clamp_max, delta))


# ── District Caseload Proxy (T3) ──────────────────────────────────


async def compute_caseload_proxy_for_cd(
    socrata,
    *,
    cd: Optional[str] = None,
    community_board: Optional[str] = None,
    now: Optional[datetime] = None,
    cache: Optional[Dict[str, float]] = None,
) -> float:
    """PR #15A Stage 2.A T3 lock — rolling-30d median
    (disposition_date - date_entered) per community_board.

    Caches per-CD into the module-level ``_caseload_proxy_cache``
    (or the caller's ``cache`` dict if provided) so multiple
    project panel builds in the same nightly run hit the cache
    rather than re-querying eabe-havv.

    Drops rows where disposition_date is null (in-flight cases)
    per Lock C fallback pattern.

    Returns float median lag in days. Returns 7.0 (a sane default)
    when no rows are available — avoids NaN propagation into the
    panel x_features.
    """
    # Accept either keyword to be ergonomic.
    cd_value = cd if cd is not None else community_board
    if not cd_value:
        return 7.0
    cd_value = str(cd_value).strip()
    if not cd_value:
        return 7.0

    cache_to_use = cache if cache is not None else _caseload_proxy_cache
    if cd_value in cache_to_use:
        return cache_to_use[cd_value]

    cur_now = now or datetime.now(timezone.utc)
    window_start = cur_now - timedelta(days=CASELOAD_PROXY_WINDOW_DAYS)

    # Pull broad — apply both window + null-filter client-side
    # (eabe-havv date_entered is MM/DD/YYYY text, can't push a
    # date threshold into SoQL without the lex-comparison bug
    # surfaced in PR #14F).
    try:
        rows = await socrata.query(
            DATASET_DOB_COMPLAINTS,
            where=f"community_board = {_soql_quote(cd_value)}",
            select=[
                "complaint_number", "date_entered", "disposition_date",
            ],
            limit=5000,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[daily_panel] caseload_proxy fetch for cb=%s failed: %r",
            cd_value, e,
        )
        cache_to_use[cd_value] = 7.0
        return 7.0

    lags: List[float] = []
    dropped_null = 0
    for r in rows:
        entered_dt = _parse_bis_mdy_date(r.get("date_entered"))
        disposed_dt = _parse_bis_mdy_date(r.get("disposition_date"))
        if entered_dt is None:
            continue
        # Lock C fallback — drop null disposition_date rows.
        if disposed_dt is None:
            dropped_null += 1
            continue
        if entered_dt < window_start:
            continue
        if entered_dt > cur_now:
            continue
        lag_days = (disposed_dt - entered_dt).total_seconds() / 86400.0
        if lag_days < 0:
            continue
        lags.append(lag_days)

    if dropped_null > 0:
        logger.info(
            "[caseload_proxy] cb=%s dropped %d rows missing "
            "disposition_date", cd_value, dropped_null,
        )

    if not lags:
        cache_to_use[cd_value] = 7.0
        return 7.0
    median_lag = float(statistics.median(lags))
    cache_to_use[cd_value] = median_lag
    return median_lag


# ── Cohort-derived milestone calibration (Lock 1.2) ───────────────


async def derive_cohort_milestone_pct(
    socrata,
    *,
    cohort_bbls: List[str],
    cohort_bins: Optional[List[str]] = None,
    n_floor: int = COHORT_MILESTONE_MIN_CONTRIBUTORS,
) -> Dict[str, Any]:
    """Lock 1.2 — derive milestone completion percentages from the
    cohort itself rather than hardcoded defaults.

    For each cohort member:
      1. T_0    = earliest rbx6-tga4 ``approved_date`` with
                  filing_reason='Initial Permit' (scope-carrying
                  work_type).
      2. T_fnd  = earliest rbx6-tga4 approved_date with
                  work_type='Foundation'.
      3. T_str  = earliest rbx6-tga4 approved_date with
                  work_type='Structural'.
      4. T_end  = latest pkdm-hqz6 c_of_o_issuance_date with
                  c_of_o_filing_type='Final'.

      foundation_pct = (T_fnd - T_0) / (T_end - T_0)
      structural_pct = (T_str - T_0) / (T_end - T_0)

    Median across contributing members yields cohort_pct per
    milestone. Members lacking a milestone are dropped from THAT
    milestone's median (but still contribute to others if records
    are present).

    When n_contributors < n_floor for a milestone, returns
    _MILESTONE_COMPLETION_PCT hardcoded value with
    source="hardcoded_fallback". Otherwise source="cohort_derived".
    """
    if not cohort_bbls:
        return {
            "source":     "hardcoded_fallback",
            **{k: v for k, v in _MILESTONE_COMPLETION_PCT.items()},
            "foundation_n_contributors": 0,
            "structural_n_contributors": 0,
        }

    # Fetch all permits + C of Os for the cohort in chunked queries.
    permit_rows_by_bbl: Dict[str, List[Dict[str, Any]]] = {}
    co_rows_by_bbl: Dict[str, List[Dict[str, Any]]] = {}

    async def _fetch_permits(chunk: List[str]) -> List[Dict[str, Any]]:
        try:
            return await socrata.query(
                DATASET_DOB_PERMITS,
                where=_soql_in("bbl", chunk),
                select=[
                    "bbl", "bin", "work_type", "filing_reason",
                    "approved_date", "issued_date", "permit_status",
                ],
                limit=10000,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[milestone] rbx6-tga4 fetch failed: %r", e,
            )
            return []

    async def _fetch_cos(chunk: List[str]) -> List[Dict[str, Any]]:
        try:
            return await socrata.query(
                "pkdm-hqz6",  # DATASET_DOB_C_OF_O — local string to avoid
                            # circular import w/ baselines constant
                where=" AND ".join([
                    _soql_in("bbl", chunk),
                    _soql_in("c_of_o_filing_type", ["Final"]),
                ]),
                select=[
                    "bbl", "bin", "c_of_o_issuance_date",
                    "c_of_o_filing_type",
                ],
                limit=10000,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[milestone] pkdm-hqz6 fetch failed: %r", e,
            )
            return []

    bbl_chunks = list(_chunk(list(cohort_bbls), SOQL_IN_CHUNK_SIZE))
    permits_results, cos_results = await asyncio.gather(
        asyncio.gather(*(_fetch_permits(c) for c in bbl_chunks)),
        asyncio.gather(*(_fetch_cos(c) for c in bbl_chunks)),
    )
    for rows in permits_results:
        for r in rows:
            bbl_n = normalize_bbl(r.get("bbl"))
            if not bbl_n:
                continue
            permit_rows_by_bbl.setdefault(bbl_n, []).append(r)
    for rows in cos_results:
        for r in rows:
            bbl_n = normalize_bbl(r.get("bbl"))
            if not bbl_n:
                continue
            co_rows_by_bbl.setdefault(bbl_n, []).append(r)

    # Per-member milestone ratio derivation.
    foundation_ratios: List[float] = []
    structural_ratios: List[float] = []

    for bbl in cohort_bbls:
        bbl_n = normalize_bbl(bbl) or bbl
        permits = permit_rows_by_bbl.get(bbl_n, [])
        cos = co_rows_by_bbl.get(bbl_n, [])

        t_0 = _earliest_initial_permit_date(permits)
        t_end = _latest_final_co_date(cos)
        if t_0 is None or t_end is None:
            continue
        duration_total = (t_end - t_0).total_seconds()
        if duration_total <= 0:
            continue

        t_fnd = _earliest_permit_date_for_work_type(permits, "Foundation")
        if t_fnd is not None and t_fnd >= t_0:
            ratio = (t_fnd - t_0).total_seconds() / duration_total
            if 0.0 <= ratio <= 1.0:
                foundation_ratios.append(ratio)

        t_str = _earliest_permit_date_for_work_type(permits, "Structural")
        if t_str is not None and t_str >= t_0:
            ratio = (t_str - t_0).total_seconds() / duration_total
            if 0.0 <= ratio <= 1.0:
                structural_ratios.append(ratio)

    n_foundation = len(foundation_ratios)
    n_structural = len(structural_ratios)

    # Log per-milestone contributor skip counts for visibility.
    if n_foundation < len(cohort_bbls):
        logger.info(
            "[milestone] foundation skipped for %d cohort members "
            "(no permit record)",
            len(cohort_bbls) - n_foundation,
        )
    if n_structural < len(cohort_bbls):
        logger.info(
            "[milestone] structural skipped for %d cohort members "
            "(no permit record)",
            len(cohort_bbls) - n_structural,
        )

    # If EITHER milestone has too few contributors, fall back
    # to hardcoded defaults. (Per Lock 1.2 — the alert layer
    # downstream uses ``source`` to decide whether to flag
    # low-confidence.)
    use_fallback = (
        n_foundation < n_floor or n_structural < n_floor
    )
    if use_fallback:
        return {
            "source":                    "hardcoded_fallback",
            **{k: v for k, v in _MILESTONE_COMPLETION_PCT.items()},
            "foundation_n_contributors": n_foundation,
            "structural_n_contributors": n_structural,
        }

    out: Dict[str, Any] = {
        "source":                    "cohort_derived",
        "foundation":                float(statistics.median(foundation_ratios)),
        "structural":                float(statistics.median(structural_ratios)),
        "foundation_n_contributors": n_foundation,
        "structural_n_contributors": n_structural,
    }
    # Inherit hardcoded values for milestones we don't compute
    # here (c_of_o_final, c_of_o_temporary, demolition,
    # initial_permit_issued) so downstream consumers don't need to
    # branch on missing keys.
    for k, v in _MILESTONE_COMPLETION_PCT.items():
        if k not in out:
            out[k] = v
    return out


def _earliest_initial_permit_date(
    permits: List[Dict[str, Any]],
) -> Optional[datetime]:
    """T_0 — earliest approved_date among permits flagged
    ``filing_reason='Initial Permit'`` with a scope-carrying
    work_type. Falls back to issued_date when approved_date is
    absent.
    """
    candidates: List[datetime] = []
    scope_carrying = {"General Construction", "Foundation", "Structural"}
    for p in permits:
        if (p.get("filing_reason") or "") != "Initial Permit":
            continue
        wt = p.get("work_type") or ""
        if wt not in scope_carrying:
            continue
        dt = (
            _parse_socrata_dt(p.get("approved_date"))
            or _parse_socrata_dt(p.get("issued_date"))
        )
        if dt:
            candidates.append(dt)
    return min(candidates) if candidates else None


def _earliest_permit_date_for_work_type(
    permits: List[Dict[str, Any]],
    work_type: str,
) -> Optional[datetime]:
    """Earliest approved_date among permits matching ``work_type``."""
    candidates: List[datetime] = []
    for p in permits:
        if (p.get("work_type") or "") != work_type:
            continue
        dt = (
            _parse_socrata_dt(p.get("approved_date"))
            or _parse_socrata_dt(p.get("issued_date"))
        )
        if dt:
            candidates.append(dt)
    return min(candidates) if candidates else None


def _latest_final_co_date(
    cos: List[Dict[str, Any]],
) -> Optional[datetime]:
    """T_end — latest c_of_o_issuance_date among Final C of Os."""
    candidates: List[datetime] = []
    for r in cos:
        if (r.get("c_of_o_filing_type") or "") != "Final":
            continue
        dt = (
            _parse_pkdm_date(r.get("c_of_o_issuance_date"))
            or _parse_socrata_dt(r.get("c_of_o_issuance_date"))
        )
        if dt:
            candidates.append(dt)
    return max(candidates) if candidates else None


# ── Validation ledger helpers (T7) ────────────────────────────────


async def _upsert_validation_ledger_entry(
    db,
    *,
    project_id: Any,
    calendar_date: str,
    prediction_timestamp: Optional[datetime] = None,
    predicted_probability: float = 0.0,
    x_features_snapshot: Optional[Dict[str, Any]] = None,
    model_coefficients_hash: str = "",
    cohort_segment_mix: Optional[Dict[str, int]] = None,
    target_horizon_days: int = 7,
    observed_outcome: Optional[bool] = None,
    brier_score_delta: Optional[float] = None,
) -> None:
    """PR #15A T7 — UPSERT one canonical entry per
    (project_id, calendar_date). Intra-day re-predictions
    overwrite the same document; never insert duplicates.
    """
    ts = prediction_timestamp or datetime.now(timezone.utc)
    set_doc: Dict[str, Any] = {
        "prediction_timestamp":    ts,
        "target_horizon_days":     target_horizon_days,
        "target_horizon_at":       ts + timedelta(days=target_horizon_days),
        "predicted_probability":   predicted_probability,
        "x_features_snapshot":     x_features_snapshot or {},
        "model_coefficients_hash": model_coefficients_hash,
        "cohort_segment_mix":      cohort_segment_mix or {},
    }
    if observed_outcome is not None:
        set_doc["observed_outcome"]  = observed_outcome
        set_doc["scored_at"]         = ts + timedelta(days=target_horizon_days)
        set_doc["brier_score_delta"] = brier_score_delta

    ledger = getattr(db, "prediction_validation_ledger", None)
    if ledger is None:
        logger.warning(
            "[validation_ledger] db.prediction_validation_ledger "
            "missing — skipping upsert for project=%r date=%s",
            project_id, calendar_date,
        )
        return
    try:
        await ledger.update_one(
            {"project_id": project_id, "calendar_date": calendar_date},
            {"$set": set_doc},
            upsert=True,
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[validation_ledger] upsert failed for project=%r "
            "date=%s: %r", project_id, calendar_date, e,
        )


async def compute_rolling_30d_brier(
    db,
    *,
    project_id: Any,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """PR #15A — rolling 30-day Brier mean per project.

    Aggregation: $match scored_at >= now-30d AND observed_outcome
    != None; $group $avg(brier_score_delta).

    Returns ``{brier_mean: float, n: int}``. Empty result yields
    ``{brier_mean: 0.0, n: 0}`` to keep downstream alert logic
    None-free.
    """
    cur_now = now or datetime.now(timezone.utc)
    window_start = cur_now - timedelta(days=30)
    ledger = getattr(db, "prediction_validation_ledger", None)
    if ledger is None:
        return {"brier_mean": 0.0, "n": 0}

    pipeline = [
        {"$match": {
            "project_id":       project_id,
            "scored_at":        {"$gte": window_start},
            "observed_outcome": {"$ne": None},
        }},
        {"$group": {
            "_id":        None,
            "brier_mean": {"$avg": "$brier_score_delta"},
            "n":          {"$sum": 1},
        }},
    ]
    try:
        cursor = ledger.aggregate(pipeline)
        rows = await cursor.to_list(length=10) if hasattr(cursor, "to_list") else []
        if not rows:
            # Fall back to async iteration for non-Motor backends.
            rows = []
            async for r in cursor:
                rows.append(r)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[brier] rolling-30d aggregation failed: %r", e,
        )
        return {"brier_mean": 0.0, "n": 0}

    if not rows:
        return {"brier_mean": 0.0, "n": 0}
    row = rows[0]
    return {
        "brier_mean": float(row.get("brier_mean") or 0.0),
        "n":          int(row.get("n") or 0),
    }


# ── Cohort event-history fetchers ─────────────────────────────────


async def _fetch_ecb_violations_for_cohort_bins(
    socrata,
    *,
    bin_list: List[str],
    severities: Tuple[str, ...] = SEVERE_ECB_SEVERITIES,
) -> Dict[str, List[datetime]]:
    """Query 6bgk-3dad for severe ECB violations per BIN.
    Returns ``{bin: [issue_dt, ...]}`` with the locked severity
    filter applied at SoQL WHERE (T4).
    """
    out: Dict[str, List[datetime]] = {b: [] for b in bin_list}
    if not bin_list:
        return out

    async def _query_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
        try:
            return await socrata.query(
                DATASET_DOB_ECB_VIOLATIONS,
                where=" AND ".join([
                    _soql_in("bin", chunk),
                    _soql_in("severity", list(severities)),
                ]),
                select=[
                    "bin", "ecb_violation_number", "issue_date",
                    "severity", "violation_type",
                ],
                limit=10000,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[daily_panel] 6bgk-3dad chunk failed: %r", e,
            )
            return []

    chunks = list(_chunk(bin_list, SOQL_IN_CHUNK_SIZE))
    chunk_results = await asyncio.gather(
        *(_query_chunk(c) for c in chunks),
    )
    for rows in chunk_results:
        for r in rows:
            b = r.get("bin")
            if not b or b not in out:
                continue
            dt = _parse_ecb_yyyymmdd_date(r.get("issue_date"))
            if dt:
                out[b].append(dt)
    return out


async def _fetch_eabe_complaints_for_cohort_bins(
    socrata,
    *,
    bin_list: List[str],
) -> Dict[str, List[datetime]]:
    """Query eabe-havv for all complaints per BIN (any
    disposition). Returns ``{bin: [date_entered_dt, ...]}``."""
    out: Dict[str, List[datetime]] = {b: [] for b in bin_list}
    if not bin_list:
        return out

    async def _query_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
        try:
            return await socrata.query(
                DATASET_DOB_COMPLAINTS,
                where=_soql_in("bin", chunk),
                select=["bin", "complaint_number", "date_entered"],
                limit=10000,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[daily_panel] eabe-havv chunk failed: %r", e,
            )
            return []

    chunks = list(_chunk(bin_list, SOQL_IN_CHUNK_SIZE))
    chunk_results = await asyncio.gather(
        *(_query_chunk(c) for c in chunks),
    )
    for rows in chunk_results:
        for r in rows:
            b = r.get("bin")
            if not b or b not in out:
                continue
            dt = _parse_bis_mdy_date(r.get("date_entered"))
            if dt:
                out[b].append(dt)
    return out


async def _fetch_311_complaints_for_cohort_bbls(
    socrata,
    *,
    bbl_list: List[str],
) -> Dict[str, List[datetime]]:
    """Query erm2-nwe9 (311) for complaints per BBL. Returns
    ``{bbl: [created_dt, ...]}``. Filters to DOB-routed
    complaints (most relevant for construction inspection
    arrival prediction)."""
    out: Dict[str, List[datetime]] = {b: [] for b in bbl_list}
    if not bbl_list:
        return out

    async def _query_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
        try:
            return await socrata.query(
                DATASET_COMPLAINTS_311,
                where=" AND ".join([
                    _soql_in("bbl", chunk),
                    "agency = 'DOB'",
                ]),
                select=[
                    "unique_key", "bbl", "created_date",
                    "complaint_type",
                ],
                limit=10000,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[daily_panel] erm2-nwe9 chunk failed: %r", e,
            )
            return []

    chunks = list(_chunk(bbl_list, SOQL_IN_CHUNK_SIZE))
    chunk_results = await asyncio.gather(
        *(_query_chunk(c) for c in chunks),
    )
    for rows in chunk_results:
        for r in rows:
            b = normalize_bbl(r.get("bbl"))
            if not b or b not in out:
                continue
            dt = _parse_socrata_dt(r.get("created_date"))
            if dt:
                out[b].append(dt)
    return out


# ── Top-level panel builder ────────────────────────────────────────


async def compute_daily_panel(
    project: Dict[str, Any],
    db: Any,
    socrata: Any,
    *,
    panel_window_days: int = DEFAULT_PANEL_WINDOW_DAYS,
    now: Optional[datetime] = None,
    force_rebuild: bool = False,
) -> List[Dict[str, Any]]:
    """PR #15A — main panel orchestrator.

    Steps (Stage 2.A locks in parens):
      1. Extract cohort_member_provenance from peer_stats_cache.
      2. Compute provenance_checksum (T6).
      3. Check existing daily_panel_provenance_checksum on
         peer_criteria; skip rebuild on match (T6 / Lock D).
      4. EXCLUDE active project bbl/bin from cohort (T8 #7).
      5. Build cohort_bbls + cohort_bins from filtered provenance.
      6. Fetch event histories (ECB violations, SWO dispositions,
         eabe + 311 complaints) — chunked + parallel.
      7. Compute cohort_derived_milestone_pct (Lock 1.2).
      8. Compute caseload_proxy per CD (cached per-CD per T3).
      9. Per-member × per-day row emission:
         x_features + outcome_violation_d + right-censored
         outcome_violation_d_to_d_plus_7 (T5).
      10. Bulk insert into db.daily_panels.
      11. Persist provenance_checksum + cohort_derived_milestone_pct
          + derived_lifecycle_stage_pct hint back to project
          peer_stats_cache via db.projects.update_one.
      12. Return inserted rows (caller can assert + telemetry).
    """
    cur_now = now or datetime.now(timezone.utc)
    project_id = project.get("_id") or project.get("id")
    active_bbl = normalize_bbl(
        project.get("bbl") or project.get("nyc_bbl")
    )
    active_bin = project.get("nyc_bin")

    # Step 1 — Provenance extraction.
    cache = project.get("peer_stats_cache") or {}
    criteria = cache.get("peer_criteria") or {}
    provenance = criteria.get("cohort_member_provenance") or []
    segments_meta = criteria.get("cohort_source_segments") or {}

    # Step 2 — Checksum.
    incoming_checksum = _provenance_checksum(provenance)

    # Step 3 — Rebuild gate.
    persisted_checksum = criteria.get("daily_panel_provenance_checksum")
    if (
        not force_rebuild
        and persisted_checksum
        and persisted_checksum == incoming_checksum
    ):
        logger.info(
            "[daily_panel] checksum match for project=%r — "
            "skipping rebuild (T6)",
            project_id,
        )
        return []

    # Step 4 — Exclude active project from cohort (#7 lock).
    filtered_provenance = []
    for entry in provenance:
        entry_bbl = normalize_bbl(entry.get("bbl"))
        entry_bin = entry.get("bin")
        if active_bbl and entry_bbl == active_bbl:
            continue
        if active_bin and entry_bin == active_bin:
            continue
        filtered_provenance.append(entry)

    if not filtered_provenance:
        logger.info(
            "[daily_panel] empty cohort after active-project exclusion "
            "for project=%r", project_id,
        )
        # Still persist checksum so we don't repeatedly attempt rebuild.
        await _persist_panel_meta(
            db, project,
            provenance_checksum=incoming_checksum,
            cohort_derived_milestone_pct={
                "source": "hardcoded_fallback",
                **_MILESTONE_COMPLETION_PCT,
            },
            derived_lifecycle_stage_pct=None,
        )
        return []

    # Step 5 — Cohort id lists.
    cohort_bbls = [
        normalize_bbl(e.get("bbl"))
        for e in filtered_provenance if e.get("bbl")
    ]
    cohort_bbls = [b for b in cohort_bbls if b]
    cohort_bins = [
        e.get("bin") for e in filtered_provenance if e.get("bin")
    ]

    # Step 6 — Event histories (parallel).
    ecb_task = _fetch_ecb_violations_for_cohort_bins(
        socrata, bin_list=cohort_bins,
    )
    swo_task = _classify_swo_disposition_codes_per_bin(
        socrata, bin_list=cohort_bins,
    )
    eabe_task = _fetch_eabe_complaints_for_cohort_bins(
        socrata, bin_list=cohort_bins,
    )
    n311_task = _fetch_311_complaints_for_cohort_bbls(
        socrata, bbl_list=cohort_bbls,
    )
    ecb_by_bin, swo_by_bin, eabe_by_bin, n311_by_bbl = await asyncio.gather(
        ecb_task, swo_task, eabe_task, n311_task,
    )

    # Step 7 — Cohort-derived milestone calibration.
    milestone_pct = await derive_cohort_milestone_pct(
        socrata,
        cohort_bbls=cohort_bbls,
        cohort_bins=cohort_bins,
    )

    # Step 8 — Per-CD caseload proxy (cached per-CD).
    cohort_cds: Set[str] = set()
    snapshot = project.get("pluto_snapshot") or {}
    active_cd = snapshot.get("cd") or snapshot.get("community_board")
    if active_cd:
        cohort_cds.add(str(active_cd))
    # Pre-warm the cache for the active project's CD.
    # Per-cohort-member CD discovery deferred — for PR #15A scope the
    # x[4] feature uses the active project's CD on every row.
    caseload_proxy_value = 7.0
    if active_cd:
        caseload_proxy_value = await compute_caseload_proxy_for_cd(
            socrata, cd=str(active_cd), now=cur_now,
        )

    # Step 9 — Per-member × per-day row emission.
    lifecycle_start = cur_now - timedelta(days=panel_window_days - 1)
    panel_rows: List[Dict[str, Any]] = []
    target_class = (criteria.get("target_state") or {}).get("bldgclass")
    foundation_pct_value = (
        milestone_pct.get("foundation")
        if isinstance(milestone_pct.get("foundation"), (int, float))
        else _MILESTONE_COMPLETION_PCT.get("foundation", 0.20)
    )

    for entry in filtered_provenance:
        bbl_n = normalize_bbl(entry.get("bbl"))
        bin_id = entry.get("bin")
        segment = entry.get("source") or "modern"
        sample_weight = 1.0 if segment == "modern" else 0.4

        bin_violations = ecb_by_bin.get(bin_id, []) if bin_id else []
        bin_swo_events = swo_by_bin.get(bin_id, []) if bin_id else []
        bin_complaints = eabe_by_bin.get(bin_id, []) if bin_id else []
        bbl_complaints = n311_by_bbl.get(bbl_n, []) if bbl_n else []

        # Pre-compute the SWO transition timeline once per member.
        swo_transitions = _compute_active_swo_timeline_per_bin(
            bin_swo_events, lifecycle_start, cur_now,
        )

        for day_offset in range(panel_window_days):
            day_dt = lifecycle_start + timedelta(days=day_offset)
            day_calendar_date = day_dt.strftime("%Y-%m-%d")

            active_swo = _active_swo_flag_on_day(swo_transitions, day_dt)
            velocity = _combined_complaint_velocity(
                bin_complaints, bbl_complaints,
                target_date=day_dt, window_days=14,
            )
            days_since_violation = _compute_days_since_last_violation_clamped(
                bin_violations, day_dt, clamp_max=90,
            )

            # outcome_violation_d — did a severe violation issue on day d?
            outcome_d = any(
                _same_calendar_day(v, day_dt)
                for v in bin_violations
            )

            # outcome_violation_d_to_d_plus_7 — None for trailing
            # 7 days per T5 (right-censoring).
            if day_offset >= panel_window_days - 7:
                outcome_d_to_d7 = None
            else:
                window_end = day_dt + timedelta(days=7)
                outcome_d_to_d7 = any(
                    day_dt < v <= window_end for v in bin_violations
                )

            row = {
                "project_id":           project_id,
                "cohort_member_bbl":    bbl_n,
                "cohort_member_bin":    bin_id,
                "cohort_segment":       segment,
                "sample_weight":        sample_weight,
                "day_in_lifecycle":     day_offset,
                "day_calendar_date":    day_calendar_date,
                "x_features": {
                    "active_swo_flag":              int(active_swo),
                    "complaint_velocity_14d":       int(velocity),
                    "days_since_last_violation":    int(days_since_violation),
                    "derived_lifecycle_stage_pct":  float(foundation_pct_value),
                    "district_caseload_proxy_days": float(caseload_proxy_value),
                },
                "outcome_violation_d":              bool(outcome_d),
                "outcome_violation_d_to_d_plus_7":  (
                    None if outcome_d_to_d7 is None else bool(outcome_d_to_d7)
                ),
                "built_at":             cur_now,
                "panel_schema_version": PR15A_PANEL_SCHEMA_VERSION,
            }
            panel_rows.append(row)

    # Step 10 — Persist panel rows.
    if panel_rows and getattr(db, "daily_panels", None) is not None:
        try:
            await db.daily_panels.insert_many(panel_rows)
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                "[daily_panel] insert_many failed for project=%r: %r",
                project_id, e,
            )

    # Step 11 — Persist provenance meta on project (peer_stats_cache).
    await _persist_panel_meta(
        db, project,
        provenance_checksum=incoming_checksum,
        cohort_derived_milestone_pct=milestone_pct,
        derived_lifecycle_stage_pct=foundation_pct_value,
    )

    return panel_rows


def _same_calendar_day(dt: datetime, target: datetime) -> bool:
    """True iff dt and target are on the same UTC calendar day."""
    return (
        dt.year == target.year
        and dt.month == target.month
        and dt.day == target.day
    )


async def _persist_panel_meta(
    db: Any,
    project: Dict[str, Any],
    *,
    provenance_checksum: str,
    cohort_derived_milestone_pct: Dict[str, Any],
    derived_lifecycle_stage_pct: Optional[float],
) -> None:
    """Write the 3 new peer_criteria keys back to the project doc
    via db.projects.update_one. Defensive on missing _id / db /
    projects collection.

    Also mutates the in-memory project["peer_stats_cache"][
    "peer_criteria"] so test fixtures observe the change without
    re-reading from the stub.
    """
    project_id = project.get("_id") or project.get("id")
    cache = project.setdefault("peer_stats_cache", {}) or {}
    project["peer_stats_cache"] = cache
    criteria = cache.setdefault("peer_criteria", {}) or {}
    cache["peer_criteria"] = criteria
    criteria["daily_panel_provenance_checksum"] = provenance_checksum
    criteria["derived_lifecycle_stage_pct"] = derived_lifecycle_stage_pct
    criteria["cohort_derived_milestone_pct"] = cohort_derived_milestone_pct

    if project_id is None or db is None:
        return
    projects = getattr(db, "projects", None)
    if projects is None:
        return
    try:
        await projects.update_one(
            {"_id": project_id},
            {"$set": {
                "peer_stats_cache.peer_criteria."
                "daily_panel_provenance_checksum": provenance_checksum,
                "peer_stats_cache.peer_criteria."
                "derived_lifecycle_stage_pct": derived_lifecycle_stage_pct,
                "peer_stats_cache.peer_criteria."
                "cohort_derived_milestone_pct": cohort_derived_milestone_pct,
            }},
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[daily_panel] peer_criteria persist failed for "
            "project=%r: %r", project_id, e,
        )
