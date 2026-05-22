"""PR #15B — Predictive Inference Engine Phase 1: live mutation engine.

This module hosts both the nightly batch refit pipeline AND the
intra-day live-mutation hot path. Stage 3.A lands ONLY the pure
helper functions; Stage 3.B implements the stateful database /
Socrata-touching surface.

Locked design (Stage 2.A):
  L1  sklearn approved as new dep (scikit-learn==1.7.0)
  L2  Live x_now winsorized to ±3σ from panel_mu; log on clip.
  L3  validation_audit_sweep refuses to overwrite non-null
      observed_outcome (soft-fail with warning log, Q4 placement).
  L4  Borough actuarial uses 12-month window (Stage 3.B).
  L5  Cron schedules: nightly 2:45 AM ET, audit 4:15 AM ET (Stage 3.B).
  L6  Ensemble trigger: (modern_brier - legacy_brier) / legacy_brier > 0.15
  L7  Live mutation refresh threshold: 5 minutes.
  L8  Anchored baseline label format:
      f"{borough} {project_type} macro baseline"
  L9  ALL_PR15B_INDEX_SPECS aggregator + startup loop in server.py.
  L10 Cold-start fallback when peer_stats_cache.sample_size < 30.
  L11 Live mutation non-blocking: returns cached prediction
      immediately, refresh runs as background task (Stage 3.B).
  L12 Cron failures touch ONLY the new collections (daily_panels,
      prediction_models, prediction_validation_ledger,
      prediction_cache field). NEVER peer_stats_cache or
      risk_score_log.

Stage 3.A scope:
  • Pure helpers (no I/O, no async): winsorize_x_now, sigmoid,
    model_coefficients_hash, is_prediction_cache_valid,
    is_prediction_cache_stale, should_use_cold_start_fallback,
    cohort_confidence_tier, format_anchored_baseline_label,
    build_prediction_cache, build_cold_start_prediction_cache.

Stage 3.B scope (deferred):
  • compute_x_now_for_project, compute_borough_actuarial_hazard,
    fit_project_panel, predict_for_project_nightly,
    predict_for_project_live, nightly_refit_for_all_projects,
    validation_audit_sweep,
    serve_prediction_cache_with_optional_refresh.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── PR #15B constants ─────────────────────────────────────────────

# Schema version stamp on every prediction_cache write. Mirrors the
# peer_stats_cache schema_version pattern at baselines.py:1950 so a
# future schema-shape change invalidates stale caches automatically.
PR15B_PREDICTION_CACHE_SCHEMA_VERSION = "pr15b_v1"

# L7 — live mutation cache staleness threshold.
PREDICTION_CACHE_STALE_THRESHOLD_SECONDS = 300

# L10 — cold-start sample-size floor. Below this, the cohort is too
# sparse to fit a reliable logistic hazard; fall back to the borough
# actuarial baseline. Boundary value: sample_size=30 stays in the
# modeled path (with low_confidence_flag); sample_size=29 triggers
# cold-start.
COLD_START_SAMPLE_SIZE_FLOOR = 30

# T6 triple-boundary thresholds for cohort confidence tier labeling.
# Returned by ``cohort_confidence_tier`` and stamped onto
# prediction_cache.cohort_tier_utilized when not overridden by an
# ensemble or cold-start branch.
LOW_CONFIDENCE_SAMPLE_SIZE_FLOOR  = 30
HIGH_CONFIDENCE_SAMPLE_SIZE_FLOOR = 100

# PR #15D.2 — removed unused ensemble scaffolding (ENSEMBLE_MODERN_WEIGHT,
# ENSEMBLE_LEGACY_WEIGHT, ENSEMBLE_BRIER_DIVERGENCE_THRESHOLD plus the
# matching should_fire_ensemble / combine_ensemble_probs helpers). Spec
# audit §3.5 confirmed they were exported but never called from
# fit_project_panel / predict_for_project_nightly / predict_for_project_live.
# Phase 1 inference uses a single sklearn LogisticRegression over rows
# weighted by SAMPLE_WEIGHT_MODERN / SAMPLE_WEIGHT_LEGACY — no separate
# legacy fit, no p_legacy, no legacy_brier.

# Lock B — sample weights threaded through sklearn fit at Stage 3.B.
# Exposed here as constants so tests can pin the values.
SAMPLE_WEIGHT_MODERN = 1.0
SAMPLE_WEIGHT_LEGACY = 0.4

# Canonical 5-feature state vector order. ALL functions in this
# module that traffic in x-vectors use this order, including the
# winsorization clip and the standardize+dot-product sigmoid path.
STATE_VECTOR_FEATURES: Tuple[str, ...] = (
    "active_swo_flag",
    "complaint_velocity_14d",
    "days_since_last_violation",
    "schedule_position_ratio",
    "district_caseload_proxy_days",
)


# Phase 1 Week 3 PR-A — manual phase enum → schedule_position_ratio
# mapping. Values are finer-grained cousins of the existing
# _MILESTONE_COMPLETION_PCT constants from baselines.py.
#
# Note: closeout caps at 0.97, NOT 1.0. Only INFERRED ratios can exceed
# 1.0 (up to the 1.5 cap) to surface overruns. Manual closeout means
# "C of O pending" — bounded below 1.0 by design.
PHASE_TO_RATIO: Dict[str, float] = {
    "foundation":     0.10,
    "superstructure": 0.35,
    "interior":       0.55,
    "mep":            0.70,
    "finishes":       0.85,
    "closeout":       0.97,
}


# ── PR #15B.1 — pure helpers (B3, B6, T1, T2) ─────────────────────


def _extract_project_type(project: Dict[str, Any]) -> str:
    """PR #15B.1 B3 + Q3 — extract project_type from Atlas project
    doc. Replaces PR #15B's broken `project.get('dob_type_classification')`
    lookup at 2 call sites.

    Source priority (Stage 1 Probe C confirmed shape on 5 real
    projects):
      1. project['dob_project_type']                         (top-level)
      2. project['peer_stats_cache']['peer_criteria']['dob_project_type']
      3. 'New Building' (default)
    """
    top = project.get("dob_project_type")
    if top:
        return str(top)
    pc = (project.get("peer_stats_cache") or {}).get("peer_criteria") or {}
    nested = pc.get("dob_project_type")
    if nested:
        return str(nested)
    return "New Building"


def derive_borough(project: Dict[str, Any]) -> Optional[str]:
    """PR #15B.1 B6 — extract full-uppercase borough name from Atlas
    project doc. Source priority:

      1. project['borough']                                  (top-level)
      2. _normalize_borough_to_full_name(pluto_snapshot.borough)
         ("BK" → "BROOKLYN" per PR #14I)
      3. bbl_to_borough(bbl or nyc_bbl)
         (bbl[0] prefix; PR #15B.1 B6)

    Returns None when none resolve — caller decides default (usually
    "BROOKLYN" with a warning, or skip the borough actuarial call).

    Stage 1 Probe C confirmed all 5 production projects carry
    borough=None at top-level — PR #15B's code defaulted EVERY project
    to "BROOKLYN", including the 2 Bronx projects.
    """
    # Lazy import to avoid module-level cycle.
    from lib.statistical_engine.baselines import (
        _normalize_borough_to_full_name,
        bbl_to_borough,
    )
    direct = project.get("borough")
    if direct and isinstance(direct, str) and direct.strip():
        return direct.upper().strip()
    pluto = project.get("pluto_snapshot") or {}
    pluto_b = pluto.get("borough") if isinstance(pluto, dict) else None
    if pluto_b:
        normalized = _normalize_borough_to_full_name(pluto_b)
        if normalized:
            return normalized
    bbl = project.get("bbl") or project.get("nyc_bbl")
    return bbl_to_borough(bbl)


def compute_cohort_baseline_rate(
    panel_rows: List[Dict[str, Any]],
) -> float:
    """PR #15B.1 T2 — mean of outcome_violation_d_to_d_plus_7 across
    panel rows with non-None outcome. Replaces PR #15B's use of
    training_brier_score as the anchored_baseline_prob_14d proxy.

    Brier score measures prediction accuracy, not base rate; cohort
    mean outcome IS the base rate. Drops right-censored trailing-7
    rows per PR #15A T5. Returns 0.0 for empty / all-censored input
    so the anchored baseline degrades gracefully.
    """
    if not panel_rows:
        return 0.0
    vals = [
        r.get("outcome_violation_d_to_d_plus_7")
        for r in panel_rows
        if r.get("outcome_violation_d_to_d_plus_7") is not None
    ]
    if not vals:
        return 0.0
    return float(sum(1 if v else 0 for v in vals)) / len(vals)


def _discrete_time_hazard_horizons(
    prob_7d: float,
) -> Tuple[float, float, float]:
    """PR #15B.1 T1 — discrete-time hazard math.

    Replaces PR #15B's Poisson extrapolation (`prob_n = prob_7 * n/7`),
    which over-fires alerts for moderate-risk projects (prob_7=0.3 →
    Poisson 30d clamps to 1.0; DTH gives 0.78).

    Formula:
        daily = 1 - (1 - p_7) ** (1/7)
        p_n   = 1 - (1 - daily) ** n

    Input clipped to [0, 1] defensively (sigmoid may produce
    1.0000001 due to float precision). Special-cases 0.0 and 1.0
    to avoid pow() edge-case rounding.
    """
    p_7 = max(0.0, min(1.0, float(prob_7d)))
    if p_7 == 0.0:
        return (0.0, 0.0, 0.0)
    if p_7 == 1.0:
        return (1.0, 1.0, 1.0)
    daily = 1.0 - (1.0 - p_7) ** (1.0 / 7.0)
    prob_14d = 1.0 - (1.0 - daily) ** 14
    prob_30d = 1.0 - (1.0 - daily) ** 30
    return (
        p_7,
        max(0.0, min(1.0, prob_14d)),
        max(0.0, min(1.0, prob_30d)),
    )


# ── PR #15D — UX hazard ratio + confidence badge helpers ─────────


def hazard_ratio_to_color_tier(
    ratio: Optional[float],
) -> str:
    """PR #15D L6, T8' — map a per-horizon hazard ratio to a
    5-tier color tier. Returns one of: 'green', 'yellow', 'amber',
    'orange', 'red', 'neutral'.

    Hazard ratio = project_prob_<horizon> / cohort_baseline_prob_<horizon>.

    Tier thresholds (Lock L6):
      ratio < 0.75       → 'green'    (below cohort risk)
      0.75 <= r < 1.5    → 'yellow'   (around cohort risk)
      1.5  <= r < 3.0    → 'amber'    (elevated risk)
      3.0  <= r < 4.0    → 'orange'   (high risk)
      ratio >= 4.0       → 'red'      (critical risk)

    Null / NaN / inf / non-numeric / negative → 'neutral' (frontend
    renders a neutral grey when the ratio can't be computed).

    F2 + T8' locks: the frontend ports this logic byte-for-byte in
    ``frontend/src/utils/hazardRatioColor.js``. Backend stays the
    canonical source; frontend mirrors. Tests live on backend side
    per F2 (no frontend test infrastructure in this repo).
    """
    if ratio is None:
        return "neutral"
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return "neutral"
    if math.isnan(r) or math.isinf(r):
        return "neutral"
    if r < 0:
        return "neutral"  # mathematically impossible — defensive
    if r < 0.75:
        return "green"
    if r < 1.5:
        return "yellow"
    if r < 3.0:
        return "amber"
    if r < 4.0:
        return "orange"
    return "red"


def compute_confidence_badge(
    prediction_cache: Optional[Dict[str, Any]],
) -> Optional[str]:
    """PR #15D L8, B-SERIALIZE, Q3 — derive confidence badge from
    prediction_cache flags.

    Returns: 'cold_start' | 'limited_peer_sample' | None

    Precedence (L8):
      is_cold_start = True            → 'cold_start'
      low_confidence_flag = True      → 'limited_peer_sample'
      otherwise                       → None

    Q3 lock: missing flags default to False (conservative — no badge
    surfaced when the cache schema is incomplete OR flags carry
    explicit None values). Only ``is True`` matches trigger a badge.

    B-SERIALIZE lock: computed at API serialization time
    (server.serialize_prediction_cache_to_response). NOT persisted
    in prediction_cache itself — derivable from existing flags, so
    no schema migration needed.
    """
    if not prediction_cache or not isinstance(prediction_cache, dict):
        return None
    if prediction_cache.get("is_cold_start") is True:
        return "cold_start"
    if prediction_cache.get("low_confidence_flag") is True:
        return "limited_peer_sample"
    return None


# ── Pure helpers (PR #15B) ────────────────────────────────────────


def _sigmoid(z: float) -> float:
    """Standard logistic with overflow protection. Returns a value
    in [0.0, 1.0]. For |z| > 30, saturates to 0.0 or 1.0 — avoids
    math.exp(>700) OverflowError when β-x_now drifts wildly during
    live mutation (winsorization should prevent this, but the
    sigmoid stays defensive)."""
    if z < -30.0:
        return 0.0
    if z > 30.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _model_coefficients_hash(
    beta: Dict[str, float],
    mu: Dict[str, float],
    sigma: Dict[str, float],
) -> str:
    """SHA1 hex of canonical JSON-serialized β + μ + σ.

    Used as:
      • prediction_models.model_coefficients_hash — index key
      • prediction_validation_ledger.model_coefficients_hash —
        join key for cohort-of-fit audit
      • prediction_cache.model_coefficients_hash — lookup key for
        live mutation engine.

    Keys are sorted to keep the hash stable across Python dict
    insertion order. Float formatting uses repr() (not str()) to
    preserve full precision.
    """
    payload = {
        "beta":  {k: repr(beta.get(k))  for k in sorted(beta or {})},
        "mu":    {k: repr(mu.get(k))    for k in sorted(mu or {})},
        "sigma": {k: repr(sigma.get(k)) for k in sorted(sigma or {})},
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def winsorize_x_now(
    x_now: Dict[str, float],
    mu: Dict[str, float],
    sigma: Dict[str, float],
    *,
    k: float = 3.0,
) -> Tuple[Dict[str, float], List[str]]:
    """L2 lock — clip each feature to ``mu[k] ± k*sigma[k]``.

    Returns a tuple of (clipped_x_now_dict, list_of_fields_clipped).
    Logs a structured warning for each field that was clipped, so
    the live-mutation refresh log can surface out-of-distribution
    x_now values for audit.

    Edge cases:
      • Missing mu[k] or sigma[k]: feature is passed through
        un-clipped (defensive — better to skip clipping than crash
        when a feature is new and the panel hasn't been refit yet).
      • sigma[k] == 0: feature is passed through un-clipped (no
        meaningful clip band).
    """
    clipped: Dict[str, float] = {}
    fields_clipped: List[str] = []
    for key, raw_val in x_now.items():
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            clipped[key] = raw_val
            continue
        feat_mu    = mu.get(key)
        feat_sigma = sigma.get(key)
        if feat_mu is None or feat_sigma is None or feat_sigma == 0:
            clipped[key] = val
            continue
        lo = feat_mu - k * feat_sigma
        hi = feat_mu + k * feat_sigma
        if val < lo:
            clipped[key] = lo
            fields_clipped.append(key)
            logger.info(
                "[pr15b] live x_now winsorized: feat=%s, raw=%.4f, "
                "clipped=%.4f, mu=%.4f, sigma=%.4f",
                key, val, lo, feat_mu, feat_sigma,
            )
        elif val > hi:
            clipped[key] = hi
            fields_clipped.append(key)
            logger.info(
                "[pr15b] live x_now winsorized: feat=%s, raw=%.4f, "
                "clipped=%.4f, mu=%.4f, sigma=%.4f",
                key, val, hi, feat_mu, feat_sigma,
            )
        else:
            clipped[key] = val
    return clipped, fields_clipped


def is_prediction_cache_valid(
    prediction_cache: Optional[Dict[str, Any]],
) -> bool:
    """True iff the cache exists AND carries the current
    schema_version. Mirrors compare_project_to_peers'
    peer_stats_cache schema-version invalidation at
    baselines.py:1950 — a stale-shape cache is treated as absent
    so a future schema bump triggers automatic recompute without
    needing a deploy-time ``$unset`` migration.
    """
    if not prediction_cache:
        return False
    if not isinstance(prediction_cache, dict):
        return False
    schema_version = prediction_cache.get("schema_version")
    return schema_version == PR15B_PREDICTION_CACHE_SCHEMA_VERSION


def is_prediction_cache_stale(
    prediction_cache: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    threshold_seconds: int = PREDICTION_CACHE_STALE_THRESHOLD_SECONDS,
) -> bool:
    """L7 lock — cache is stale when
    ``now - last_validated_timestamp > threshold_seconds`` (strict
    >, 300s default). Boundary: 299s old returns False; 301s old
    returns True.

    Returns True (stale → refresh) when:
      • cache is None or empty
      • last_validated_timestamp missing or malformed
      • age strictly exceeds threshold_seconds

    Defensive — better to refresh on uncertain state than serve
    a possibly-stale cache.
    """
    if not prediction_cache:
        return True
    ts = prediction_cache.get("last_validated_timestamp")
    if not isinstance(ts, datetime):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    cur_now = now or datetime.now(timezone.utc)
    age_seconds = (cur_now - ts).total_seconds()
    return age_seconds > threshold_seconds


def should_use_cold_start_fallback(
    peer_stats_cache: Optional[Dict[str, Any]],
) -> bool:
    """L10 lock — cold-start fallback fires when:
      • peer_stats_cache is None or empty
      • peer_stats_cache.status != "ready"
      • peer_criteria.cohort_unavailable is True
      • peer_criteria.sample_size < 30 (boundary: 29 cold-start,
        30 NOT cold-start)

    Accepts the FULL peer_stats_cache shape (with the wrapping
    ``peer_criteria`` sub-dict) OR a flat dict carrying
    ``sample_size`` directly — tests use the latter for
    convenience. The branching prefers the full shape when both
    keys are present.
    """
    if not peer_stats_cache:
        return True
    if not isinstance(peer_stats_cache, dict):
        return True

    # Full peer_stats_cache shape (preferred).
    criteria = peer_stats_cache.get("peer_criteria")
    if isinstance(criteria, dict):
        if criteria.get("cohort_unavailable") is True:
            return True
        sample_size = criteria.get("sample_size")
        if not isinstance(sample_size, (int, float)):
            return True
        if sample_size < COLD_START_SAMPLE_SIZE_FLOOR:
            return True
        # Note: status="pending" / "failed" should not surface here;
        # the caller short-circuits in those branches. If they DO
        # leak through, the explicit cohort_unavailable / sample
        # checks above still pull us through to a cold-start path.
        return False

    # Flat-shape: {"sample_size": N, ...}
    sample_size = peer_stats_cache.get("sample_size")
    if isinstance(sample_size, (int, float)):
        return sample_size < COLD_START_SAMPLE_SIZE_FLOOR
    return True


def cohort_confidence_tier(sample_size: int) -> str:
    """T6 — return one of {"cold_start", "low_confidence",
    "high_confidence"} based on the cohort sample_size boundaries.

    Boundaries (pinned by test_pr15b_borough_actuarial_fallback
    + test_pr15b_live_mutation_engine):
      • sample_size < 30           → "cold_start"
      • 30 <= sample_size < 100    → "low_confidence"
      • sample_size >= 100         → "high_confidence"
    """
    if sample_size is None:
        return "cold_start"
    try:
        n = int(sample_size)
    except (TypeError, ValueError):
        return "cold_start"
    if n < LOW_CONFIDENCE_SAMPLE_SIZE_FLOOR:
        return "cold_start"
    if n < HIGH_CONFIDENCE_SAMPLE_SIZE_FLOOR:
        return "low_confidence"
    return "high_confidence"


def format_anchored_baseline_label(
    borough: str,
    project_type: str,
) -> str:
    """L8 lock — exact format ``f"{borough} {project_type} macro
    baseline"``. Drives UX copy in PR #15D. Tests pin the exact
    string; do not freeform.

    Inputs are passed through unchanged — caller is responsible
    for borough-normalization (e.g. "BROOKLYN" not "BK") and
    project_type formatting ("New Building" not "new_building").
    """
    return f"{borough} {project_type} macro baseline"


def build_prediction_cache(
    *,
    prob_7d: Optional[float] = None,
    prob_14d: Optional[float] = None,
    prob_30d: Optional[float] = None,
    anchored_baseline_prob_14d: Optional[float] = None,
    # PR #15D G2 — 7d + 30d anchored baselines. Computed server-side
    # via DTH math from anchored_baseline_prob_14d so the frontend
    # can render per-horizon hazard-ratio coloring without re-doing
    # the math. Default None for legacy fits pre-G2; serializer
    # handles missing fields gracefully.
    anchored_baseline_prob_7d: Optional[float] = None,
    anchored_baseline_prob_30d: Optional[float] = None,
    anchored_baseline_label: Optional[str] = None,
    cohort_tier_utilized: str = "low_confidence",
    cohort_sample_size: int = 0,
    low_confidence_flag: bool = False,
    is_cold_start: bool = False,
    schedule_position_ratio: Optional[float] = None,
    district_caseload_proxy_days: Optional[float] = None,
    model_coefficients_hash: Optional[str] = None,
    fit_at: Optional[datetime] = None,
    last_validated_timestamp: Optional[datetime] = None,
    now: Optional[datetime] = None,
    # NOTE: build_prediction_cache also accepts beta_coefficients,
    # x_now_standardized, mu, sigma, cohort_segment_mix kwargs for
    # caller ergonomics — they are NOT stamped onto the cache
    # itself (those live on prediction_models). Ignored when passed.
    beta_coefficients: Optional[Dict[str, float]] = None,
    x_now_standardized: Optional[Dict[str, float]] = None,
    mu: Optional[Dict[str, float]] = None,
    sigma: Optional[Dict[str, float]] = None,
    cohort_segment_mix: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Pure construction of the prediction_cache sub-document
    written onto ``project.prediction_cache``. Returns all 15
    required fields per Task 5 design.

    Schema version stamped at write time — survives the
    is_prediction_cache_valid check at next read.
    """
    cur_now = now or datetime.now(timezone.utc)
    return {
        # 3-horizon probability suite
        "prob_violation_7d":   prob_7d,
        "prob_violation_14d":  prob_14d,
        "prob_violation_30d":  prob_30d,

        # UX anchor
        "anchored_baseline_prob_14d":  anchored_baseline_prob_14d,
        # PR #15D G2 — 7d + 30d horizon baselines (DTH-derived
        # from 14d). May be None for legacy fits pre-G2 write.
        "anchored_baseline_prob_7d":   anchored_baseline_prob_7d,
        "anchored_baseline_prob_30d":  anchored_baseline_prob_30d,
        "anchored_baseline_label":     anchored_baseline_label,

        # Cohort context
        "cohort_tier_utilized":  cohort_tier_utilized,
        "cohort_sample_size":    cohort_sample_size,
        "low_confidence_flag":   low_confidence_flag,
        "is_cold_start":         is_cold_start,

        # Lifecycle + caseload proxy snapshots
        "schedule_position_ratio":       schedule_position_ratio,
        "district_caseload_proxy_days":  district_caseload_proxy_days,

        # Validation linkage
        "model_coefficients_hash":  model_coefficients_hash,
        "fit_at":                   fit_at,
        "last_validated_timestamp": last_validated_timestamp or cur_now,

        # Schema versioning
        "schema_version":  PR15B_PREDICTION_CACHE_SCHEMA_VERSION,
    }


def build_cold_start_prediction_cache(
    *,
    borough: str,
    project_type: str,
    borough_baseline_probs: Dict[str, float],
    cohort_sample_size: int = 0,
    schedule_position_ratio: Optional[float] = None,
    district_caseload_proxy_days: Optional[float] = None,
    fit_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Cold-start variant of build_prediction_cache —
    cohort_tier_utilized="borough_baseline", is_cold_start=True,
    model_coefficients_hash=None, anchored_baseline_label is
    formatted via format_anchored_baseline_label(borough,
    project_type).

    The borough_baseline_probs dict must carry keys "7d", "14d",
    "30d" matching what compute_borough_actuarial_hazard returns.
    Missing horizons get None (defensive).
    """
    label = format_anchored_baseline_label(borough, project_type)
    return build_prediction_cache(
        prob_7d=  borough_baseline_probs.get("7d"),
        prob_14d= borough_baseline_probs.get("14d"),
        prob_30d= borough_baseline_probs.get("30d"),
        anchored_baseline_prob_14d=  borough_baseline_probs.get("14d"),
        # PR #15D G2 — cold-start case: predicted prob IS the
        # borough baseline (hazard ratio = 1.0 by definition).
        # Forward all 3 horizons so the frontend renders a yellow
        # "at cohort average" tier; the disclaimer explains the
        # absolute-risk caveat.
        anchored_baseline_prob_7d=   borough_baseline_probs.get("7d"),
        anchored_baseline_prob_30d=  borough_baseline_probs.get("30d"),
        anchored_baseline_label=     label,
        cohort_tier_utilized="borough_baseline",
        cohort_sample_size=cohort_sample_size,
        low_confidence_flag=True,
        is_cold_start=True,
        schedule_position_ratio=schedule_position_ratio,
        district_caseload_proxy_days=district_caseload_proxy_days,
        model_coefficients_hash=None,
        fit_at=fit_at,
        now=now,
    )


# ──────────────────────────────────────────────────────────────────
# Stage 3.B — stateful database / Socrata-touching surface
# ──────────────────────────────────────────────────────────────────

import asyncio

# SWO closed/resolved states — match the existing triggers.py
# convention. Production dob_logs rows use these strings (case-
# sensitive) to mark a SWO no longer in force.
_SWO_CLOSED_STATES: Tuple[str, ...] = (
    "CLOSED", "RESCINDED", "VACATED", "RESOLVED",
)

# Severe ECB severities — mirror PR #15A T4 lock.
_SEVERE_ECB_SEVERITIES: Tuple[str, ...] = (
    "CLASS - 1", "CLASS - 2", "Hazardous",
)


async def _compute_schedule_position_live(
    db: Any,
    project: Dict[str, Any],
    cur_now: datetime,
) -> Optional[float]:
    """Phase 1 Week 2 — compute schedule_position_ratio for the
    active project at request time.

    Reads earliest Initial Permit from socrata_permits_historical
    (Phase 1 Week 1 backfill) and cohort_median_duration_days from
    the latest prediction_models doc. Returns None when either
    lookup is empty, when the project's BIN isn't in the 5k-BIN
    backfill scope, or when the helper's guards kick in.

    Caller (compute_x_now_for_project) chains the fallback:
      live compute → prediction_cache.schedule_position_ratio →
      panel_mu (via existing _substitute_panel_mu_for_nones path).
    """
    # Lazy import to avoid module-level cycle.
    from lib.statistical_engine.baselines import (
        _schedule_position_for_member_on_day,
    )

    bin_ = project.get("nyc_bin")
    if not bin_:
        return None

    permits_coll = getattr(db, "socrata_permits_historical", None)
    if permits_coll is None:
        return None

    try:
        rows = await permits_coll.find(
            {"bin": str(bin_), "filing_reason": "Initial Permit"},
            {"bin": 1, "issued_date": 1},
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[phase1w2] permits_historical lookup failed for bin=%r: %r",
            bin_, e,
        )
        return None

    earliest: Optional[datetime] = None
    for r in rows or []:
        issued_raw = r.get("issued_date")
        issued_dt: Optional[datetime] = None
        if isinstance(issued_raw, datetime):
            issued_dt = (issued_raw if issued_raw.tzinfo
                         else issued_raw.replace(tzinfo=timezone.utc))
        elif isinstance(issued_raw, str) and len(issued_raw) >= 10:
            # ISO "YYYY-MM-DDTHH:MM:SS..." or "YYYY-MM-DD"
            try:
                issued_dt = datetime(
                    int(issued_raw[0:4]),
                    int(issued_raw[5:7]),
                    int(issued_raw[8:10]),
                    tzinfo=timezone.utc,
                )
            except (ValueError, TypeError):
                issued_dt = None
        if issued_dt is None:
            continue
        if earliest is None or issued_dt < earliest:
            earliest = issued_dt

    if earliest is None:
        return None

    # Read cohort_median_duration_days from the latest prediction_models
    # doc. If absent (cold-start projects), the helper returns None.
    cohort_median: Optional[float] = None
    models_coll = getattr(db, "prediction_models", None)
    if models_coll is not None:
        project_id = str(project.get("_id") or project.get("id") or "")
        try:
            doc = await models_coll.find_one(
                {"project_id": project_id},
                sort=[("fit_at", -1)],
            )
            if doc:
                v = doc.get("cohort_median_duration_days")
                if isinstance(v, (int, float)):
                    cohort_median = float(v)
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                "[phase1w2] prediction_models lookup failed for "
                "project=%r: %r", project_id, e,
            )

    # Fall back to peer_stats_cache.peer_criteria if prediction_models
    # path didn't yield a value (e.g., project never fit yet).
    if cohort_median is None:
        criteria = (
            (project.get("peer_stats_cache") or {})
            .get("peer_criteria") or {}
        )
        v = criteria.get("cohort_median_duration_days")
        if isinstance(v, (int, float)):
            cohort_median = float(v)

    return _schedule_position_for_member_on_day(
        earliest_issued=earliest,
        cohort_median_duration_days=cohort_median,
        target_date=cur_now,
    )


async def _resolve_schedule_position(
    db: Any,
    project: Dict[str, Any],
    cur_now: datetime,
) -> Optional[float]:
    """Phase 1 Week 3 PR-A + PR #48 — resolve schedule_position_ratio
    with a 4-tier priority chain:

      1. ai_inferred_phase.phase → PHASE_TO_RATIO lookup
         (PR #48 — weekly Gemini inference, highest confidence)
      2. Most recent daily_log.phase → PHASE_TO_RATIO lookup
         (legacy manual signal — backward-compat for projects with
         existing manually-entered phase data)
      3. Live inferred ratio (Phase 1 Week 2 path:
         _compute_schedule_position_live)
      4. None — downstream paths (cache fallback + panel_mu)
         handle the substitution

    The AI-inferred phase dominates because it's recomputed weekly from
    the full last-7-days log corpus; the legacy manual daily_log.phase
    is kept as a fallback so projects entered before PR #48 still
    resolve. The inferred ratio is a cohort-derived proxy that's
    accurate but least authoritative.

    Defensive guards:
      • Deleted logs (is_deleted=True) excluded.
      • Phase values not in PHASE_TO_RATIO (typos, future enum
        additions, stale AI output) fall through to the next tier
        rather than crashing or defaulting to 0.0.
      • Missing project_id falls through directly to inferred.
    """
    # Tier 1 — PR #48 AI-inferred phase. Read from the project doc
    # directly (persisted by the weekly cron); no extra DB round-trip.
    ai_inferred = project.get("ai_inferred_phase")
    if isinstance(ai_inferred, dict):
        ai_phase = ai_inferred.get("phase")
        if ai_phase in PHASE_TO_RATIO:
            return PHASE_TO_RATIO[ai_phase]
        if ai_phase:
            logger.info(
                "[pr48] unknown ai_inferred_phase.phase=%r for "
                "project=%r; falling back to daily_log.phase.",
                ai_phase, project.get("_id"),
            )

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
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                "[phase1w3] daily_logs lookup failed for project=%r: %r",
                project_id, e,
            )
            log = None
        if log:
            phase = log.get("phase")
            if phase in PHASE_TO_RATIO:
                return PHASE_TO_RATIO[phase]
            # Unknown phase value — log a one-time-ish warning and
            # fall through to inferred. Helps surface frontend bugs
            # or stale enum values without crashing inference.
            logger.info(
                "[phase1w3] unknown daily_log.phase=%r for project=%r; "
                "falling back to inferred ratio.",
                phase, project_id,
            )

    return await _compute_schedule_position_live(db, project, cur_now)


def _yyyymmdd(dt: datetime) -> str:
    """Format a datetime as YYYYMMDD for the dob_logs violation_date
    field (numeric text). Mirrors triggers.py:_yyyymmdd."""
    return dt.strftime("%Y%m%d")


def _parse_yyyymmdd(raw: Any) -> Optional[datetime]:
    """Parse YYYYMMDD numeric text to a tz-aware UTC datetime."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str) or len(raw.strip()) != 8:
        return None
    s = raw.strip()
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]),
                        tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _standardize(
    x: Dict[str, float],
    mu: Dict[str, float],
    sigma: Dict[str, float],
) -> Dict[str, float]:
    """Z-score standardize x_now using mu/sigma maps. Missing or
    zero sigma → pass through (defensive)."""
    out: Dict[str, float] = {}
    for k, v in x.items():
        m = mu.get(k)
        s = sigma.get(k)
        try:
            val = float(v)
        except (TypeError, ValueError):
            out[k] = 0.0
            continue
        if m is None or s is None or s == 0:
            out[k] = val
        else:
            out[k] = (val - m) / s
    return out


def _validate_x_now_with_fallback(
    x_now: Dict[str, Any],
    mu: Optional[Dict[str, float]],
    project_id: str,
) -> Dict[str, Any]:
    """PR #15B.3 Site 3 — validate x_now features and fall back to
    panel_mu when a feature is None / NaN / inf.

    Without this guard, invalid feature values propagate through
    ``_standardize`` (which silently maps None → 0.0 via its
    TypeError catch but does NOT log) and into the discrete-time
    hazard math, where Python's ``min(1.0, NaN)`` quirk produces
    degenerate 1.0 output. Explicit detection + warning surfaces
    the data-quality issue rather than masking it.

    Fallback strategy:
      • Invalid value → use ``mu[feature]`` (the training mean — a
        sensible neutral value)
      • If ``mu`` is None or missing the feature → fall back to 0.0
        (cohort-naive default)
      • Emit a ``[pr15b3]`` warning log per invalid feature

    Returns a NEW dict with invalid values replaced. Original dict
    is not mutated. Callers can compare ``out is x_now`` to detect
    whether any fallback fired.
    """
    out = dict(x_now)
    mu_safe = mu or {}
    for k in STATE_VECTOR_FEATURES:
        v = out.get(k)
        is_invalid = (
            v is None
            or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
        )
        if is_invalid:
            fallback = mu_safe.get(k, 0.0)
            logger.warning(
                "[pr15b3] x_now[%r] invalid (got %r) for project=%s; "
                "falling back to panel_mu=%r",
                k, v, project_id, fallback,
            )
            out[k] = fallback
    return out


def _apply_beta_to_x_now(
    beta: Dict[str, float],
    x_now_standardized: Dict[str, float],
) -> float:
    """Compute β · x_now_standardized + intercept, return sigmoid.

    Returns a probability in [0, 1]. Uses STATE_VECTOR_FEATURES
    order for the dot product; intercept is the named ``intercept``
    coefficient.

    PR #15B.3 Site 2 — defensive logit clip to [-10, +10]. Existing
    ``_sigmoid`` clips at |z|>30 to avoid math.exp overflow; the
    tighter ±10 clip here caps OUTPUT to [sigmoid(-10), sigmoid(10)]
    = [4.54e-5, 0.99995] so out-of-distribution inputs never produce
    degenerate exactly-0 or exactly-1 predictions (which surface in
    the UI as meaningless "0%" or "100%" risk).
    """
    z = float(beta.get("intercept", 0.0))
    for k in STATE_VECTOR_FEATURES:
        z += float(beta.get(k, 0.0)) * float(x_now_standardized.get(k, 0.0))
    # PR #15B.3 Site 2 — tighter clip than _sigmoid's ±30.
    z = max(-10.0, min(10.0, z))
    return _sigmoid(z)


# ── Step 1 — compute_x_now_for_project ────────────────────────────


async def compute_x_now_for_project(
    db,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, float]:
    """Compute the 5-feature ``x_now`` vector for the ACTIVE project.

    Sources:
      • active_swo_flag           — dob_logs aggregate (BIN-keyed
                                    most-recent-disposition wins)
      • complaint_velocity_14d    — dob_logs $count of complaints in
                                    last 14 days
      • days_since_last_violation — max(violation_date) clamped
                                    [0, 90]
      • schedule_position_ratio → Phase 1 Week 3 PR-A: resolved with
                                   priority chain — (1) most recent
                                   daily_log.phase mapped via
                                   PHASE_TO_RATIO, (2) Phase 1 Week 2
                                   inferred ratio (earliest Initial
                                   Permit / cohort_median_duration_days),
                                   (3) prediction_cache.schedule_position_
                                   ratio (last nightly value), (4)
                                   panel_mu via _substitute_panel_mu_
                                   for_nones downstream.
      • district_caseload_proxy_days → cached on project.prediction_cache.
                                       0.0 when absent.

    Latency budget: <50ms p99 via a single dob_logs ``$facet``
    aggregate combining all 3 derived features.
    """
    cur_now = now or datetime.now(timezone.utc)
    project_id = str(project.get("_id") or project.get("id") or "")
    cache = project.get("prediction_cache") or {}

    # Phase 1 Week 3 PR-A — resolve schedule_position_ratio with
    # priority chain: manual daily_log.phase → inferred ratio →
    # cache → panel_mu. _resolve_schedule_position handles the
    # first two; cache + panel_mu fallback happens below + at
    # _substitute_panel_mu_for_nones downstream.
    schedule_position_live = await _resolve_schedule_position(
        db, project, cur_now,
    )
    if schedule_position_live is None:
        cached_sp = cache.get("schedule_position_ratio")
        schedule_position_value = (
            float(cached_sp) if cached_sp is not None else 0.0
        )
    else:
        schedule_position_value = schedule_position_live

    out: Dict[str, float] = {
        "active_swo_flag":              0.0,
        "complaint_velocity_14d":       0.0,
        "days_since_last_violation":    90.0,
        "schedule_position_ratio":      schedule_position_value,
        "district_caseload_proxy_days": float(cache.get("district_caseload_proxy_days") or 0.0),
    }

    if not project_id or getattr(db, "dob_logs", None) is None:
        return out

    cut_14 = _yyyymmdd(cur_now - timedelta(days=14))
    pipeline = [
        {"$match": {
            "project_id": project_id,
            "is_deleted": {"$ne": True},
        }},
        {"$facet": {
            "active_swo": [
                {"$match": {
                    "record_type": "swo",
                    "resolution_state": {"$nin": list(_SWO_CLOSED_STATES)},
                }},
                {"$count": "n"},
            ],
            "complaints_14d": [
                {"$match": {
                    "record_type": "complaint",
                    "violation_date": {"$gte": cut_14},
                }},
                {"$count": "n"},
            ],
            "last_violation": [
                {"$match": {"record_type": "violation"}},
                {"$group": {"_id": None,
                            "max_date": {"$max": "$violation_date"}}},
            ],
        }},
    ]

    try:
        result = await db.dob_logs.aggregate(pipeline).to_list(length=1)
    except Exception as e:
        logger.warning(
            "[pr15b] compute_x_now dob_logs aggregate failed for "
            "%s: %r", project_id, e,
        )
        return out

    if not result:
        return out
    facet = result[0]

    # active_swo_flag — present iff any unclosed SWO row
    active_rows = facet.get("active_swo") or []
    n_active = (active_rows[0].get("n", 0) if active_rows else 0)
    out["active_swo_flag"] = 1.0 if n_active > 0 else 0.0

    # complaint_velocity_14d — raw count, T2 lock (no ageing here)
    vel_rows = facet.get("complaints_14d") or []
    out["complaint_velocity_14d"] = float(
        (vel_rows[0].get("n", 0) if vel_rows else 0)
    )

    # days_since_last_violation — clamp [0, 90]
    last_rows = facet.get("last_violation") or []
    if last_rows:
        max_date = last_rows[0].get("max_date")
        parsed = _parse_yyyymmdd(max_date) if max_date else None
        if parsed is not None:
            age_days = (cur_now - parsed).total_seconds() / 86400.0
            out["days_since_last_violation"] = max(
                0.0, min(90.0, float(age_days))
            )

    return out


# ── Step 2 — compute_borough_actuarial_hazard ────────────────────


async def compute_borough_actuarial_hazard(
    socrata,
    *,
    borough: str,
    project_type: str = "New Building",
    horizon_days: int = 7,
    now: Optional[datetime] = None,
) -> float:
    """L4 lock — 12-month-window borough+project_type actuarial
    hazard.

    Numerator: severe ECB issuances (CLASS-1/CLASS-2/Hazardous)
    in the borough over the last 12 months.
    Denominator: count of distinct permits (rbx6-tga4) for the
    same borough+project_type over the same 12 months.

    Returns ``annual_hazard * horizon_days/365.0``. Returns 0.0
    when denominator is 0 (avoid div-by-zero — cold-start projects
    in low-activity boroughs get a 0.0 baseline rather than NaN).

    PR #15B.1 B2a/b/c — 6bgk-3dad corrections per Stage 1 probes:
      • B2a: WHERE clause uses ``boro = '<numeric>'`` (BIS code via
        _BIS_BORO_CODES); PR #15B's ``borough = ...`` returned 400.
      • B2b: SELECT uses ``ecb_violation_number`` (PR #15B's
        ``ecb_number`` doesn't exist on this dataset).
      • B2c: server-side ``issue_date > 'YYYYMMDD'`` filter — verified
        safe at Probe E.2 because YYYYMMDD lex-sorts correctly
        (unlike MM/DD/YYYY per PR #14F).

    rbx6-tga4 denominator query unchanged — that dataset uses full
    uppercase borough names per PR #14I.
    """
    from lib.statistical_engine.socrata_client import (
        borough_to_boro_code,
    )
    cur_now = now or datetime.now(timezone.utc)
    cut_start = cur_now - timedelta(days=365)
    cutoff_yyyymmdd = cut_start.strftime("%Y%m%d")

    # ── Numerator: severe ECB violations in last 12 months ─
    # PR #15B.1 B2a: convert borough to BIS numeric code. If we
    # can't resolve a code, log + return 0.0 (avoid sending a
    # query that we know will 400).
    boro_code = borough_to_boro_code(borough)
    if boro_code is None:
        logger.warning(
            "[pr15b] borough actuarial: cannot map borough=%r to BIS "
            "boro code; skipping 6bgk-3dad query (returns 0.0)",
            borough,
        )
        return 0.0

    severities_clause = ", ".join(
        f"'{s}'" for s in _SEVERE_ECB_SEVERITIES
    )
    ecb_where = (
        f"boro = '{boro_code}' "
        f"AND severity IN ({severities_clause}) "
        f"AND issue_date > '{cutoff_yyyymmdd}'"
    )
    try:
        ecb_rows = await socrata.query(
            "6bgk-3dad",
            where=ecb_where,
            select=["bin", "ecb_violation_number", "severity", "issue_date"],
            limit=5000,
        )
    except Exception as e:
        logger.warning(
            "[pr15b] borough actuarial ECB fetch failed for "
            "borough=%s (boro=%s): %r", borough, boro_code, e,
        )
        return 0.0
    # B2c: server-side filter narrowed to ~12mo window. Still apply
    # a defensive client-side date check (handles MockSocrata that
    # may not understand the server-side WHERE perfectly, and
    # belt-and-suspenders against malformed issue_date values).
    n_severe = 0
    for r in ecb_rows:
        sev = r.get("severity")
        if sev not in _SEVERE_ECB_SEVERITIES:
            continue
        issued_dt = _parse_yyyymmdd(r.get("issue_date"))
        if issued_dt is None:
            continue
        if issued_dt < cut_start or issued_dt > cur_now:
            continue
        n_severe += 1

    # ── Denominator: rbx6-tga4 permits in last 12 months ───
    try:
        permit_rows = await socrata.query(
            "rbx6-tga4",
            where=f"borough = '{borough}'",
            select=["bin", "work_type", "filing_reason", "issued_date"],
            limit=5000,
        )
    except Exception as e:
        logger.warning(
            "[pr15b] borough actuarial permit fetch failed for "
            "borough=%s: %r", borough, e,
        )
        return 0.0
    seen_bins: set = set()
    for r in permit_rows:
        # Filter on filing_reason="Initial Permit" only for project
        # newness, per Stage 3 spec.
        if r.get("filing_reason") != "Initial Permit":
            continue
        issued_raw = r.get("issued_date") or r.get("approved_date")
        # rbx6-tga4 issued_date is ISO YYYY-MM-DD; parse defensively.
        issued_dt: Optional[datetime] = None
        if isinstance(issued_raw, str) and len(issued_raw) >= 10:
            try:
                issued_dt = datetime(
                    int(issued_raw[0:4]),
                    int(issued_raw[5:7]),
                    int(issued_raw[8:10]),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                issued_dt = None
        if issued_dt is None:
            continue
        if issued_dt < cut_start or issued_dt > cur_now:
            continue
        bin_ = r.get("bin")
        if bin_:
            seen_bins.add(bin_)

    n_permits = len(seen_bins)
    if n_permits == 0:
        return 0.0

    annual_hazard = n_severe / n_permits
    return float(annual_hazard * (horizon_days / 365.0))


# ── Step 3 — fit_project_panel (sklearn) ──────────────────────────


async def fit_project_panel(
    db,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Fit a sklearn LogisticRegression on the project's daily_panels
    rows, persist into prediction_models, return the fit dict.

    Drops right-censored rows (outcome_violation_d_to_d_plus_7 is
    None) and rows missing x_features. Returns None when:
      • daily_panels has zero usable rows for this project, OR
      • outcome column is single-valued (sklearn requires both
        classes present for binary fit).

    Lock B sample weights: cohort_segment="modern" → 1.0,
    cohort_segment="legacy" → 0.4. Anything else → 1.0 default.
    """
    cur_now = now or datetime.now(timezone.utc)
    raw_pid = project.get("_id") or project.get("id")
    project_id = str(raw_pid) if raw_pid else ""
    if not project_id or getattr(db, "daily_panels", None) is None:
        return None

    # PR #15B.2 — daily_panels rows are written by PR #15A's
    # compute_daily_panel with project_id = project["_id"] (ObjectId).
    # PR #15B's read sites used str() which matched 0 rows in
    # production. $in filter matches both shapes; backward-compatible
    # with any future write that uses the string form.
    pid_filter = {"$in": [raw_pid, project_id]} if raw_pid else project_id
    try:
        rows = await db.daily_panels.find({
            "project_id": pid_filter,
        }).to_list(length=None)
    except Exception as e:
        logger.warning(
            "[pr15b] fit_project_panel daily_panels fetch failed "
            "for %s: %r", project_id, e,
        )
        return None

    # Drop right-censored + malformed rows.
    train_rows = [
        r for r in rows
        if r.get("outcome_violation_d_to_d_plus_7") is not None
        and isinstance(r.get("x_features"), dict)
    ]
    if len(train_rows) < 30:
        logger.info(
            "[pr15b] fit_project_panel insufficient training rows "
            "for %s: n=%d (need >=30)", project_id, len(train_rows),
        )
        return None

    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import brier_score_loss, log_loss
    except ImportError:
        logger.error(
            "[pr15b] scikit-learn not installed — fit_project_panel "
            "cannot proceed. Stage 3 deploy gate: install "
            "scikit-learn==1.7.0."
        )
        return None

    weight_map = {
        "modern": SAMPLE_WEIGHT_MODERN,
        "legacy": SAMPLE_WEIGHT_LEGACY,
    }
    X = []
    y = []
    w = []
    mix_modern = 0
    mix_legacy = 0
    for r in train_rows:
        feats = r["x_features"]
        X.append([float(feats.get(k, 0.0)) for k in STATE_VECTOR_FEATURES])
        y.append(1 if r["outcome_violation_d_to_d_plus_7"] else 0)
        seg = r.get("cohort_segment", "modern")
        w.append(weight_map.get(seg, 1.0))
        if seg == "modern":
            mix_modern += 1
        elif seg == "legacy":
            mix_legacy += 1

    if len(set(y)) < 2:
        logger.info(
            "[pr15b] fit_project_panel single-valued outcome for %s "
            "(y=%r) — cannot fit binary classifier", project_id, y[0],
        )
        return None

    X_arr = np.asarray(X, dtype=float)
    y_arr = np.asarray(y, dtype=int)
    w_arr = np.asarray(w, dtype=float)

    # Compute mu/sigma per feature for z-score standardization.
    mu_arr = X_arr.mean(axis=0)
    sigma_arr = X_arr.std(axis=0)

    # PR #15B.3 Site 1 — zero-variance feature detection.
    # Any feature whose training-row std < 1e-6 is effectively
    # constant. sklearn fits a coefficient for it anyway (using
    # whatever direction the residual loss minimization happens to
    # land on), but at predict time multiplying by a future
    # standardized deviation produces nonsense. We:
    #   (a) substitute panel_sigma=1.0 (sentinel — _standardize
    #       returns the raw value unchanged for that feature)
    #   (b) zero the learned coefficient post-fit to neutralize the
    #       contribution at prediction time
    # Both are observable post-fit: predict_for_project_live can
    # check beta[feat]==0 to know the feature was uninformative.
    ZERO_VARIANCE_THRESHOLD = 1e-6
    zero_variance_features: List[str] = []
    for i, k in enumerate(STATE_VECTOR_FEATURES):
        if sigma_arr[i] < ZERO_VARIANCE_THRESHOLD:
            zero_variance_features.append(k)
            sigma_arr[i] = 1.0
    if zero_variance_features:
        logger.warning(
            "[pr15b3] zero-variance features detected for project=%s: "
            "%s. Setting panel_sigma=1.0 and forcing learned "
            "coefficients to 0 post-fit.",
            project_id, zero_variance_features,
        )

    # Replace any remaining zero sigmas with 1.0 (defense-in-depth;
    # the threshold check above should have caught everything).
    sigma_safe = np.where(sigma_arr == 0, 1.0, sigma_arr)
    X_std = (X_arr - mu_arr) / sigma_safe

    clf = LogisticRegression(max_iter=1000, random_state=42, solver="lbfgs")
    clf.fit(X_std, y_arr, sample_weight=w_arr)

    beta = {
        "intercept": float(clf.intercept_[0]),
    }
    for i, k in enumerate(STATE_VECTOR_FEATURES):
        beta[k] = float(clf.coef_[0][i])

    # PR #15B.3 Site 1 — neutralize coefficients for zero-variance
    # features so live mutation doesn't multiply by an arbitrary
    # noise coefficient. Math: beta[feat]=0 means feature
    # contributes 0 to the logit regardless of x_now value.
    for k in zero_variance_features:
        beta[k] = 0.0

    mu_dict    = {k: float(mu_arr[i])    for i, k in enumerate(STATE_VECTOR_FEATURES)}
    sigma_dict = {k: float(sigma_arr[i]) for i, k in enumerate(STATE_VECTOR_FEATURES)}

    p_pred = clf.predict_proba(X_std)[:, 1]
    # PR #15B.1 T3 — sklearn.metrics.brier_score_loss (math identical
    # to np.mean((p_pred - y_arr) ** 2) for binary, but more
    # semantically clear + library-validated for edge cases).
    training_brier = float(brier_score_loss(y_arr, p_pred))
    try:
        training_log_loss = float(log_loss(y_arr, p_pred, labels=[0, 1]))
    except Exception:
        training_log_loss = None

    coeff_hash = _model_coefficients_hash(beta, mu_dict, sigma_dict)

    doc = {
        "project_id":                    project_id,
        "fit_at":                        cur_now,
        "beta_coefficients":             beta,
        "panel_mu":                      mu_dict,
        "panel_sigma":                   sigma_dict,
        "cohort_segment_mix":            {"modern": mix_modern, "legacy": mix_legacy},
        "sample_weights_applied":        {"modern": SAMPLE_WEIGHT_MODERN,
                                          "legacy": SAMPLE_WEIGHT_LEGACY},
        "training_n_observations":       len(train_rows),
        "training_brier_score":          training_brier,
        "training_log_loss":             training_log_loss,
        "model_coefficients_hash":       coeff_hash,
        "is_cold_start_fallback":        False,
        "borough_baseline_p_7d":         None,
        "borough_baseline_p_14d":        None,
        "borough_baseline_p_30d":        None,
        "panel_schema_version":          "pr15a_v1",
        "model_schema_version":          "pr15b_v1",
    }
    try:
        await db.prediction_models.insert_one(doc)
    except Exception as e:
        logger.warning(
            "[pr15b] prediction_models insert failed for %s: %r",
            project_id, e,
        )
    return doc


# ── Step 4 — refit_project_cold_start ─────────────────────────────


async def refit_project_cold_start(
    db,
    project: Dict[str, Any],
    socrata,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Cold-start fallback writer (L10 — sample_size < 30).

    Computes borough actuarial hazard for 7d / 14d / 30d horizons
    and writes a prediction_models doc flagged with
    ``is_cold_start_fallback=True``.
    """
    cur_now = now or datetime.now(timezone.utc)
    project_id = str(project.get("_id") or project.get("id") or "")
    # PR #15B.1 B6 — derive borough from pluto/bbl, NOT top-level
    # which is NULL on all 5 production projects.
    borough = derive_borough(project)
    if not borough:
        logger.warning(
            "[pr15b] refit_cold_start: borough unresolvable for "
            "project=%s; defaulting to BROOKLYN", project_id,
        )
        borough = "BROOKLYN"
    # PR #15B.1 B3 — read dob_project_type, NOT dob_type_classification.
    project_type = _extract_project_type(project)

    p_7d  = await compute_borough_actuarial_hazard(
        socrata, borough=borough, project_type=project_type,
        horizon_days=7, now=cur_now,
    )
    p_14d = await compute_borough_actuarial_hazard(
        socrata, borough=borough, project_type=project_type,
        horizon_days=14, now=cur_now,
    )
    p_30d = await compute_borough_actuarial_hazard(
        socrata, borough=borough, project_type=project_type,
        horizon_days=30, now=cur_now,
    )

    doc = {
        "project_id":                project_id,
        "fit_at":                    cur_now,
        "beta_coefficients":         None,
        "panel_mu":                  None,
        "panel_sigma":               None,
        "cohort_segment_mix":        {"modern": 0, "legacy": 0},
        "sample_weights_applied":    {"modern": SAMPLE_WEIGHT_MODERN,
                                      "legacy": SAMPLE_WEIGHT_LEGACY},
        "training_n_observations":   0,
        "training_brier_score":      None,
        "training_log_loss":         None,
        "model_coefficients_hash":   None,
        "is_cold_start_fallback":    True,
        "borough_baseline_p_7d":     p_7d,
        "borough_baseline_p_14d":    p_14d,
        "borough_baseline_p_30d":    p_30d,
        "panel_schema_version":      "pr15a_v1",
        "model_schema_version":      "pr15b_v1",
    }
    try:
        await db.prediction_models.insert_one(doc)
    except Exception as e:
        logger.warning(
            "[pr15b] cold-start prediction_models insert failed "
            "for %s: %r", project_id, e,
        )
    return doc


# ── Step 5 — predict_for_project_nightly ──────────────────────────


def _read_cohort_sample_size(project: Dict[str, Any]) -> int:
    """Defensive extractor for peer_stats_cache.peer_criteria.sample_size."""
    cache = project.get("peer_stats_cache") or {}
    criteria = cache.get("peer_criteria") or {}
    sample_size = criteria.get("sample_size")
    try:
        return int(sample_size)
    except (TypeError, ValueError):
        return 0


async def predict_for_project_nightly(
    db,
    socrata,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Full nightly prediction flow for one project.

    Branches:
      • peer_stats_cache pending/failed → skip (returns None)
      • should_use_cold_start_fallback → cold-start path
      • else → fit_project_panel + compute_x_now + apply β

    L12 lock: this function NEVER writes to peer_stats_cache or
    risk_score_log — only daily_panels (already written by PR #15A),
    prediction_models, prediction_validation_ledger, and
    project.prediction_cache.
    """
    cur_now = now or datetime.now(timezone.utc)
    project_id = str(project.get("_id") or project.get("id") or "")
    if not project_id:
        return None

    cache = project.get("peer_stats_cache")
    if cache and cache.get("status") in ("pending", "failed"):
        logger.info(
            "[pr15b] skipping %s: peer_stats %s",
            project_id, cache.get("status"),
        )
        return None

    sample_size = _read_cohort_sample_size(project)
    use_cold_start = should_use_cold_start_fallback(cache)

    # PR #15B.1 B6 — derive borough from pluto/bbl, not top-level.
    borough = derive_borough(project)
    if not borough:
        logger.warning(
            "[pr15b] predict_nightly: borough unresolvable for %s; "
            "defaulting to BROOKLYN", project_id,
        )
        borough = "BROOKLYN"
    # PR #15B.1 B3 — read dob_project_type (top-level then nested).
    project_type = _extract_project_type(project)

    if use_cold_start:
        model_doc = await refit_project_cold_start(
            db, project, socrata, now=cur_now,
        )
        baseline_probs = {
            "7d":  model_doc.get("borough_baseline_p_7d"),
            "14d": model_doc.get("borough_baseline_p_14d"),
            "30d": model_doc.get("borough_baseline_p_30d"),
        }
        cache_doc = build_cold_start_prediction_cache(
            borough=borough,
            project_type=project_type,
            borough_baseline_probs=baseline_probs,
            cohort_sample_size=sample_size,
            now=cur_now,
        )
        x_now = None
    else:
        # PR #15B.1 B1 inline backstop — if daily_panels is empty for
        # this project, build the panel inline before fitting. The
        # 1:30 AM ET pr15a_nightly_panel_build cron is the primary
        # producer; this backstop is defense-in-depth so a per-project
        # build failure in that cron doesn't cascade into a wrong
        # cold-start fallback here.
        #
        # PR #15B.2 — $in filter handles both ObjectId-keyed rows
        # (PR #15A's actual write shape) and string-keyed rows.
        _raw_pid = project.get("_id") or project.get("id")
        _pid_filter = (
            {"$in": [_raw_pid, project_id]} if _raw_pid else project_id
        )
        try:
            existing_panels = await db.daily_panels.count_documents(
                {"project_id": _pid_filter}
            )
        except Exception:
            existing_panels = 0
        if existing_panels == 0:
            logger.info(
                "[pr15b] backstop fired — building panel inline for "
                "project=%s (daily_panels empty)", project_id,
            )
            try:
                # daily_panel.compute_daily_panel signature is
                # (project, db, socrata, ...) — argument order flipped
                # from this function's (db, socrata, project) convention.
                from lib.statistical_engine.daily_panel import (
                    compute_daily_panel,
                )
                await compute_daily_panel(project, db, socrata, now=cur_now)
            except Exception as e:
                logger.warning(
                    "[pr15b] backstop compute_daily_panel failed for "
                    "%s: %r — proceeding to cold-start fallback",
                    project_id, e,
                )
        model_doc = await fit_project_panel(db, project, now=cur_now)
        if not model_doc:
            # Fall back to cold-start if fit fails (insufficient
            # rows, single-class outcome, etc.)
            logger.info(
                "[pr15b] fit_project_panel returned None for %s; "
                "falling back to cold-start", project_id,
            )
            model_doc = await refit_project_cold_start(
                db, project, socrata, now=cur_now,
            )
            baseline_probs = {
                "7d":  model_doc.get("borough_baseline_p_7d"),
                "14d": model_doc.get("borough_baseline_p_14d"),
                "30d": model_doc.get("borough_baseline_p_30d"),
            }
            cache_doc = build_cold_start_prediction_cache(
                borough=borough,
                project_type=project_type,
                borough_baseline_probs=baseline_probs,
                cohort_sample_size=sample_size,
                now=cur_now,
            )
            x_now = None
        else:
            x_now = await compute_x_now_for_project(db, project, now=cur_now)
            # PR #15B.3 Site 3 — defensive validation: invalid x_now
            # features (None/NaN/inf from Socrata partial responses
            # or upstream bugs) get substituted with panel_mu before
            # standardization. Surfaces data-quality issues via
            # [pr15b3] warning.
            x_now = _validate_x_now_with_fallback(
                x_now, model_doc.get("panel_mu"), project_id,
            )
            x_std = _standardize(
                x_now,
                model_doc["panel_mu"],
                model_doc["panel_sigma"],
            )
            beta = model_doc["beta_coefficients"]
            prob_7d_raw = _apply_beta_to_x_now(beta, x_std)
            # PR #15B.1 T1 — discrete-time hazard math replaces
            # Poisson extrapolation. See _discrete_time_hazard_horizons
            # docstring for the formula + edge-case handling.
            prob_7d, prob_14d, prob_30d = _discrete_time_hazard_horizons(
                prob_7d_raw,
            )

            # PR #15B.1 T2 — anchored baseline = cohort mean outcome
            # rate (NOT training_brier_score which measures accuracy
            # not base rate). Read panel rows used for fitting and
            # compute the empirical rate.
            #
            # PR #15B.2 — $in filter handles both ObjectId-keyed
            # rows (PR #15A's write shape) and string-keyed rows.
            _raw_pid = project.get("_id") or project.get("id")
            _pid_filter = (
                {"$in": [_raw_pid, project_id]} if _raw_pid else project_id
            )
            try:
                _train_rows = await db.daily_panels.find(
                    {"project_id": _pid_filter}
                ).to_list(length=None)
            except Exception:
                _train_rows = []
            anchored_baseline = compute_cohort_baseline_rate(_train_rows)

            # PR #15D G2 — expand 14d cohort baseline into 7d + 30d
            # via DTH math. Same daily hazard used as the underlying
            # quantity, then re-projected per horizon. Keeps frontend
            # stateless: hazard ratio = project_prob_<n>d /
            # anchored_baseline_prob_<n>d for each horizon.
            if anchored_baseline is None or anchored_baseline <= 0.0:
                anchored_baseline_p7  = 0.0
                anchored_baseline_p30 = 0.0
            elif anchored_baseline >= 1.0:
                anchored_baseline_p7  = 1.0
                anchored_baseline_p30 = 1.0
            else:
                _daily = 1.0 - (1.0 - anchored_baseline) ** (1.0 / 14.0)
                anchored_baseline_p7  = 1.0 - (1.0 - _daily) ** 7
                anchored_baseline_p30 = 1.0 - (1.0 - _daily) ** 30

            label = format_anchored_baseline_label(borough, project_type)
            cache_doc = build_prediction_cache(
                prob_7d=prob_7d, prob_14d=prob_14d, prob_30d=prob_30d,
                anchored_baseline_prob_14d=anchored_baseline,
                anchored_baseline_prob_7d=anchored_baseline_p7,
                anchored_baseline_prob_30d=anchored_baseline_p30,
                anchored_baseline_label=label,
                cohort_tier_utilized=cohort_confidence_tier(sample_size),
                cohort_sample_size=sample_size,
                low_confidence_flag=(sample_size < HIGH_CONFIDENCE_SAMPLE_SIZE_FLOOR),
                is_cold_start=False,
                # Phase 1 Week 2 — read live-computed value from x_now,
                # NOT cohort-cached peer_criteria value. daily_panel.py
                # persists None at peer_criteria because the live path
                # is the source of truth (Stage 2.A D3). Initial Stage 3
                # implementation read from peer_criteria, silently
                # discarding the live-computed value.
                schedule_position_ratio=(x_now or {}).get(
                    "schedule_position_ratio"
                ),
                district_caseload_proxy_days=(x_now or {}).get(
                    "district_caseload_proxy_days"
                ),
                model_coefficients_hash=model_doc["model_coefficients_hash"],
                fit_at=cur_now,
                last_validated_timestamp=cur_now,
                now=cur_now,
            )

    # Persist prediction_cache onto project doc.
    if getattr(db, "projects", None) is not None:
        try:
            await db.projects.update_one(
                {"_id": project["_id"]},
                {"$set": {"prediction_cache": cache_doc}},
            )
        except Exception as e:
            logger.warning(
                "[pr15b] project prediction_cache write failed for "
                "%s: %r", project_id, e,
            )

    # Upsert validation_ledger entry (T7).
    try:
        from lib.statistical_engine.daily_panel import (
            _upsert_validation_ledger_entry,
        )
        await _upsert_validation_ledger_entry(
            db,
            project_id=project_id,
            calendar_date=cur_now.date().isoformat(),
            prediction_timestamp=cur_now,
            predicted_probability=cache_doc.get("prob_violation_14d") or 0.0,
            x_features_snapshot=x_now or {},
            model_coefficients_hash=cache_doc.get("model_coefficients_hash") or "",
            cohort_segment_mix=(model_doc or {}).get(
                "cohort_segment_mix", {"modern": 0, "legacy": 0}
            ),
            target_horizon_days=14,
            observed_outcome=None,
        )
    except Exception as e:
        logger.warning(
            "[pr15b] validation_ledger upsert failed for %s: %r",
            project_id, e,
        )

    return cache_doc


# ── Step 6 — predict_for_project_live (intra-day refresh) ─────────


async def predict_for_project_live(
    db,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Intra-day live mutation refresh.

    Reads project.prediction_cache + prediction_models.beta, applies
    fresh x_now via compute_x_now_for_project, runs winsorize +
    sigmoid, updates prediction_cache + validation_ledger.

    Returns ``None`` (no-op) when:
      • prediction_cache absent or schema-invalid
      • prediction_cache.is_cold_start=True (no recompute)
      • prediction_models doc absent (no fit yet)

    Latency budget: <100ms p99.
    """
    cur_now = now or datetime.now(timezone.utc)
    project_id = str(project.get("_id") or project.get("id") or "")
    if not project_id:
        return None

    cache = project.get("prediction_cache")
    if not is_prediction_cache_valid(cache):
        logger.info(
            "[pr15b] no model for %s, skipping live mutation "
            "(prediction_cache absent/invalid)", project_id,
        )
        return None

    # Cold-start projects can't be live-recomputed — return existing
    # cache unchanged so the UI keeps showing the borough baseline.
    if cache.get("is_cold_start"):
        return cache

    # Look up latest prediction_models for this project.
    if getattr(db, "prediction_models", None) is None:
        return None
    try:
        model_doc = await db.prediction_models.find_one(
            {"project_id": project_id},
            sort=[("fit_at", -1)],
        )
    except Exception as e:
        logger.warning(
            "[pr15b] prediction_models lookup failed for %s: %r",
            project_id, e,
        )
        return None

    if not model_doc or not model_doc.get("beta_coefficients"):
        return None

    x_now = await compute_x_now_for_project(db, project, now=cur_now)
    mu = model_doc.get("panel_mu") or {}
    sigma = model_doc.get("panel_sigma") or {}
    # PR #15B.3 Site 3 — fall back to panel_mu for invalid features
    # BEFORE winsorize/standardize. See predict_for_project_nightly
    # for the same guard pattern.
    x_now = _validate_x_now_with_fallback(x_now, mu, project_id)
    clipped, _fields_clipped = winsorize_x_now(x_now, mu, sigma)
    x_std = _standardize(clipped, mu, sigma)
    beta = model_doc["beta_coefficients"]
    prob_7d_raw = _apply_beta_to_x_now(beta, x_std)
    # PR #15B.1 T1 — discrete-time hazard math (same as
    # predict_for_project_nightly above).
    prob_7d, prob_14d, prob_30d = _discrete_time_hazard_horizons(
        prob_7d_raw,
    )

    # Update prediction_cache in place — mutate the relevant fields,
    # preserving the rest.
    updated_cache = dict(cache)
    updated_cache["prob_violation_7d"]  = prob_7d
    updated_cache["prob_violation_14d"] = prob_14d
    updated_cache["prob_violation_30d"] = prob_30d
    updated_cache["last_validated_timestamp"] = cur_now

    if getattr(db, "projects", None) is not None:
        try:
            await db.projects.update_one(
                {"_id": project["_id"]},
                {"$set": {"prediction_cache": updated_cache}},
            )
        except Exception as e:
            logger.warning(
                "[pr15b] project prediction_cache live update failed "
                "for %s: %r", project_id, e,
            )

    # Upsert validation_ledger — same calendar_date, replaces
    # predicted_probability; preserves target_horizon_at if the
    # entry already exists.
    try:
        from lib.statistical_engine.daily_panel import (
            _upsert_validation_ledger_entry,
        )
        await _upsert_validation_ledger_entry(
            db,
            project_id=project_id,
            calendar_date=cur_now.date().isoformat(),
            prediction_timestamp=cur_now,
            predicted_probability=prob_14d,
            x_features_snapshot=x_now,
            model_coefficients_hash=model_doc.get("model_coefficients_hash") or "",
            cohort_segment_mix=model_doc.get(
                "cohort_segment_mix", {"modern": 0, "legacy": 0}
            ),
            target_horizon_days=14,
            observed_outcome=None,
        )
    except Exception as e:
        logger.warning(
            "[pr15b] live ledger upsert failed for %s: %r",
            project_id, e,
        )

    return updated_cache


# ── Step 7 — serve_prediction_cache_with_optional_refresh ─────────


async def serve_prediction_cache_with_optional_refresh(
    db,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[asyncio.Task]]:
    """L11 lock — non-blocking UI hot path.

    Returns the current prediction_cache IMMEDIATELY. If the cache
    is stale (>5min per L7), also schedules a
    ``predict_for_project_live`` refresh as an asyncio.create_task
    so the next read sees fresh values.

    Returns ``(cached_dict, refresh_task_or_None)`` — caller can
    ``await refresh_task`` if it wants to block on completion
    (tests do this), but production UI does not.
    """
    cur_now = now or datetime.now(timezone.utc)
    cache = project.get("prediction_cache")
    if not cache:
        return None, None
    refresh_task: Optional[asyncio.Task] = None
    if is_prediction_cache_stale(cache, now=cur_now):
        try:
            refresh_task = asyncio.create_task(
                predict_for_project_live(db, project, now=cur_now)
            )
        except RuntimeError:
            # No event loop available — caller is sync; skip
            # background refresh and return cache as-is.
            refresh_task = None
    return cache, refresh_task


# ── Step 8 — nightly_refit cron entry points ──────────────────────


async def nightly_refit_for_all_projects(
    db,
    socrata,
    *,
    now: Optional[datetime] = None,
    concurrency_limit: int = 2,
) -> Dict[str, Any]:
    """Cron entry point — iterates active projects and runs
    predict_for_project_nightly per project with a concurrency
    semaphore to bound Socrata throughput.

    PR #15B.3 Site 4 — concurrency reduced from 5 → 2. The refit
    cron calls compute_x_now_for_project which hits live dob_logs
    aggregates; parallel calls across 5 projects exposed a race
    condition where Socrata rate-limiting / network jitter produced
    partial results (None/NaN values surfaced by Site 3 fallback).
    Sequential-ish processing (sem=2) ~doubles cron duration but
    eliminates the contamination risk. nightly_panel_build keeps
    semaphore=5 because compute_daily_panel writes daily_panels with
    no live x_now contamination.

    L12 lock: NEVER touches peer_stats_cache or risk_score_log.
    Per-project failures are logged but do not cascade.
    """
    cur_now = now or datetime.now(timezone.utc)
    if getattr(db, "projects", None) is None:
        return {"n_succeeded": 0, "n_failed": 0, "errors": []}

    try:
        projects = await db.projects.find({}).to_list(length=None)
    except Exception as e:
        logger.warning("[pr15b] active projects fetch failed: %r", e)
        return {"n_succeeded": 0, "n_failed": 0, "errors": [repr(e)]}

    n_succeeded = 0
    n_failed = 0
    errors: List[str] = []
    sem = asyncio.Semaphore(concurrency_limit)

    async def _one(p: Dict[str, Any]) -> None:
        nonlocal n_succeeded, n_failed
        pid = str(p.get("_id") or p.get("id") or "")
        async with sem:
            try:
                await predict_for_project_nightly(db, socrata, p, now=cur_now)
                n_succeeded += 1
            except Exception as e:
                logger.exception(
                    "[pr15b] refit failed for project=%s: %r", pid, e,
                )
                n_failed += 1
                errors.append(f"{pid}: {e!r}")

    await asyncio.gather(*(_one(p) for p in projects), return_exceptions=True)
    return {
        "n_succeeded": n_succeeded,
        "n_failed":    n_failed,
        "errors":      errors,
    }


# Alias the cron tick name used in tests.
nightly_refit_tick = nightly_refit_for_all_projects


# ── Step 9 — validation_audit_sweep ──────────────────────────────


async def validation_audit_sweep(
    db,
    socrata,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """4:15 AM ET audit cron — walks ledger entries whose horizon
    has passed and scores observed_outcome from severe ECB.

    L3 lock + Q4 soft-fail: refuses to overwrite a non-null
    observed_outcome (logs warning, continues).
    L12 lock: per-entry exceptions are logged but never propagate
    out to the cron framework (so a bad row doesn't kill the sweep).
    """
    cur_now = now or datetime.now(timezone.utc)
    if getattr(db, "prediction_validation_ledger", None) is None:
        return {"n_scored": 0, "n_skipped_already_scored": 0, "errors": []}

    try:
        # Pull broad; filter client-side so the stub's $match handler
        # doesn't need to support every operator we'd use server-side.
        all_entries = await db.prediction_validation_ledger.find({}).to_list(length=None)
    except Exception as e:
        logger.warning(
            "[pr15b] validation_audit_sweep ledger fetch failed: %r", e,
        )
        return {"n_scored": 0, "n_skipped_already_scored": 0,
                "errors": [repr(e)]}

    n_scored = 0
    n_skipped = 0
    errors: List[str] = []

    for entry in all_entries:
        horizon_at = entry.get("target_horizon_at")
        if not isinstance(horizon_at, datetime):
            continue
        if horizon_at.tzinfo is None:
            horizon_at = horizon_at.replace(tzinfo=timezone.utc)
        # Skip entries whose horizon hasn't yet passed.
        if horizon_at >= cur_now:
            continue

        # L3 + Q4 — refuse to overwrite a non-null outcome.
        if entry.get("observed_outcome") is not None:
            logger.warning(
                "[validation_audit] refusing overwrite for %s %s: "
                "outcome already %r",
                entry.get("project_id"), entry.get("calendar_date"),
                entry.get("observed_outcome"),
            )
            n_skipped += 1
            continue

        snapshot = entry.get("x_features_snapshot")
        if not isinstance(snapshot, dict) or not snapshot.get("bin"):
            logger.warning(
                "[validation_audit] skipping malformed entry for %s "
                "%s: missing x_features_snapshot.bin",
                entry.get("project_id"), entry.get("calendar_date"),
            )
            continue

        bin_ = snapshot["bin"]
        target_days = entry.get("target_horizon_days") or 14
        window_start = horizon_at - timedelta(days=target_days)

        # Query 6bgk-3dad for severe ECBs in the horizon window.
        try:
            ecb_rows = await socrata.query(
                "6bgk-3dad",
                where=f"bin = '{bin_}'",
                select=["bin", "ecb_violation_number", "severity", "issue_date"],
                limit=200,
            )
        except Exception as e:
            logger.warning(
                "[validation_audit] ECB query failed for %s %s: %r",
                entry.get("project_id"), entry.get("calendar_date"), e,
            )
            errors.append(f"{entry.get('project_id')}: {e!r}")
            continue

        hit = False
        for r in ecb_rows:
            if r.get("severity") not in _SEVERE_ECB_SEVERITIES:
                continue
            issued_dt = _parse_yyyymmdd(r.get("issue_date"))
            if issued_dt is None:
                continue
            if window_start <= issued_dt <= horizon_at:
                hit = True
                break

        predicted_prob = float(entry.get("predicted_probability") or 0.0)
        observed_int = 1 if hit else 0
        brier_delta = (observed_int - predicted_prob) ** 2

        try:
            await db.prediction_validation_ledger.update_one(
                {"project_id": entry.get("project_id"),
                 "calendar_date": entry.get("calendar_date")},
                {"$set": {
                    "observed_outcome":  hit,
                    "brier_score_delta": brier_delta,
                    "scored_at":         cur_now,
                }},
            )
            n_scored += 1
        except Exception as e:
            logger.warning(
                "[validation_audit] ledger update failed for %s %s: %r",
                entry.get("project_id"), entry.get("calendar_date"), e,
            )
            errors.append(f"{entry.get('project_id')}: {e!r}")

    return {
        "n_scored":                  n_scored,
        "n_skipped_already_scored":  n_skipped,
        "errors":                    errors,
    }
