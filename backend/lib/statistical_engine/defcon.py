"""Phase 1 Week 11-12 PR-A — Defcon 3-tier urgency engine.

User-facing payoff for the Phase 1 backend foundation. For each project,
computes a single urgency tier (NORMAL / ELEVATED / IMMEDIATE) by
combining:

  - prediction_cache.prob_violation_14d + anchored_baseline_prob_14d
    (Phase 1 Week 1-2 — canonical hazard_ratio computed here)
  - dob_logs active SWO state + duration
  - socrata_ecb_violations_historical recent severity (Phase 1 Week 1)
  - socrata_complaints_historical recent clustering
  - daily_logs.phase (Phase 1 Week 3 PR-A)

Tier precedence (Stage 2.A L1, first-match-wins):

  1. Active SWO + demolition phase                → IMMEDIATE
  2. Active SWO > 30 days                         → IMMEDIATE
  3. CLASS-1 / Hazardous violation in last 7d     → IMMEDIATE
  4. HR_14d ≥ 4.0                                 → IMMEDIATE
  5. Any active SWO                               → ELEVATED (minimum)
  6. CLASS-2 violation in last 14d                → ELEVATED
  7. HR_14d ≥ 1.5                                 → ELEVATED
  8. ≥3 complaints in last 30d                    → ELEVATED
  9. Default                                      → NORMAL

Phase override (Stage 2.A L2): after rule 7 fires, closeout phase +
HR_14d ∈ [1.5, 2.0) demotes back to NORMAL. Closeout HR ratios reflect
punch-list inspection backlog, not active site risk.

Module structure:

  • `_apply_tier_precedence(inputs)` — pure logic, directly unit-testable.
  • `_format_primary_reason(tier, factors, inputs)` — pure prose builder.
  • `compute_defcon_status(db, project)` — integration; resolves inputs
    from DB and calls the pure functions.

No backend caching (Stage 2.A L8). Sub-100ms latency target met via
indexed reads; SWO state changes intra-day so freshness matters.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Tier constants ────────────────────────────────────────────────


TIER_NORMAL = "NORMAL"
TIER_ELEVATED = "ELEVATED"
TIER_IMMEDIATE = "IMMEDIATE"
TIERS: Tuple[str, ...] = (TIER_NORMAL, TIER_ELEVATED, TIER_IMMEDIATE)

# Defcon → theme color. Aligns with PR #15D L6 5-tier palette
# collapsed to 3 buckets per Phase 1 Week 11 directive.
TIER_TO_COLOR: Dict[str, str] = {
    TIER_NORMAL:    "green",
    TIER_ELEVATED:  "amber",
    TIER_IMMEDIATE: "red",
}


# ── Locked thresholds (Stage 2.A L3-L7) ───────────────────────────


SEVERITY_TOP: Tuple[str, ...] = ("CLASS - 1", "Hazardous")
SEVERITY_ELEVATED: Tuple[str, ...] = ("CLASS - 2",)
# Excluded from escalation per L7: CLASS-3, Non-Hazardous, Unknown.

WINDOW_CLASS_1_DAYS = 7
WINDOW_CLASS_2_DAYS = 14
WINDOW_COMPLAINTS_DAYS = 30
COMPLAINT_CLUSTER_THRESHOLD = 3
SWO_LONG_RUNNING_DAYS = 30
HR_ELEVATED_THRESHOLD = 1.5
HR_IMMEDIATE_THRESHOLD = 4.0
# Closeout-phase demotion band (Stage 2.A L2).
CLOSEOUT_DEMOTE_MAX = 2.0


# ── Display helpers ───────────────────────────────────────────────


def _borough_label(raw: str) -> str:
    """Same idiom as peer_cohort._borough_label. ALL-CAPS → title-case.
    BROOKLYN → Brooklyn, STATEN ISLAND → Staten Island."""
    if not raw:
        return ""
    return " ".join(w.capitalize() for w in str(raw).lower().split() if w)


def _bucket_label(bucket: Optional[str]) -> str:
    """Render the violation_taxonomy bucket name for prose. Replaces
    underscores with spaces. 'safety_hazards' → 'safety hazard'.
    Singularizes trivially. Falls back to 'violation' for None."""
    if not bucket:
        return "violation"
    return str(bucket).replace("_", " ").rstrip("s") or "violation"


# ── PR #50 — GC-voice pre-rendering ───────────────────────────────
#
# The Defcon detail screen must read plain-English strings only; no
# engineering vocabulary (hazard ratio, cohort, n_peer_matches) reaches
# the GC. These helpers pre-render the strings backend-side, matching
# the PR #15D.1 disclosure_text single-source-of-truth pattern.


def _cohort_comparison_text(
    hazard_ratio: Optional[float],
    borough: Optional[str],
    work_type: Optional[str],
) -> str:
    """Map the 14-day hazard ratio to a GC-voice comparison sentence.

    Thresholds mirror the PR #15D.1 C3/C4 5-tier verdict mapping. The
    raw ratio is NEVER surfaced — only the plain-English band. None /
    non-numeric ratio → "Comparison not yet available".
    """
    if hazard_ratio is None or not isinstance(hazard_ratio, (int, float)):
        return "Comparison not yet available"

    borough_label = _borough_label(borough or "")
    work_type_label = (work_type or "").strip()
    # Build the site descriptor. Avoid the "projects projects" double
    # when work_type is the default sentinel.
    if borough_label and work_type_label and work_type_label != "projects":
        site_descriptor = f"{borough_label} {work_type_label} projects"
    elif borough_label:
        site_descriptor = f"{borough_label} projects"
    else:
        site_descriptor = "similar sites"

    if hazard_ratio < 0.75:
        return f"Lower than typical for {site_descriptor}"
    if hazard_ratio < 1.10:
        return f"Tracking with {site_descriptor}"
    if hazard_ratio < 1.50:
        return f"Slightly above typical for {site_descriptor}"
    if hazard_ratio < 3.00:
        return f"Above typical for {site_descriptor}"
    if hazard_ratio < 4.00:
        return f"Notably elevated compared to {site_descriptor}"
    return f"Significantly above typical for {site_descriptor}"


def _contributing_factors_to_text(
    factors: List[Dict[str, Any]],
) -> List[str]:
    """Translate the internal {factor, weight, evidence} dicts into
    GC-voice sentences (one per factor, order preserved).

    Hazard-ratio factors are rendered ratio-free — their evidence
    strings carry "N.N× cohort baseline (threshold: ...)" which must
    not reach the GC, so they get fixed plain-English sentences instead.
    Other factors reuse their evidence (already GC-readable) with a
    GC-voice override for the SWO + violation cases.
    """
    sentences: List[str] = []
    for f in factors or []:
        factor_type = f.get("factor", "")
        evidence = f.get("evidence", "") or ""

        if factor_type == "swo_demolition_phase":
            sentences.append(
                "An active stop-work order is open during demolition"
            )
        elif factor_type == "swo_long_running":
            sentences.append(
                "A stop-work order has been open more than 30 days"
            )
        elif factor_type == "swo_active":
            sentences.append("An active stop-work order is open")
        elif factor_type == "class_1_violation_recent":
            sentences.append(
                "A serious DOB violation (Class 1) was issued in the "
                "last 7 days"
            )
        elif factor_type == "class_2_violation_recent":
            sentences.append(
                "A DOB violation (Class 2) was issued in the last 14 days"
            )
        elif factor_type in ("hazard_ratio_immediate", "hazard_ratio_elevated"):
            # Ratio-free — never leak the multiplier or "cohort baseline".
            sentences.append(
                "DOB violations here are happening more often than at "
                "similar sites"
            )
        elif factor_type == "complaint_clustering":
            # Evidence is already GC-readable ("4 complaints filed in
            # last 30 days"); reuse it, else a generic fallback.
            sentences.append(evidence or "Multiple complaints filed recently")
        elif factor_type == "closeout_phase_demotion":
            sentences.append(
                "Adjusted down — elevated readings reflect closeout "
                "inspections, not active site risk"
            )
        else:
            # Unknown factor type — fall back to evidence only if it's
            # free of engineering tokens; otherwise skip silently.
            low = evidence.lower()
            if evidence and "×" not in evidence and "cohort" not in low \
                    and "baseline" not in low and "threshold" not in low:
                sentences.append(evidence)
    return sentences


# ── Pure logic: tier precedence ───────────────────────────────────


def _apply_tier_precedence(
    inputs: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Pure tier-resolution. Returns (tier, contributing_factors_list).

    `inputs` shape (defaults applied by caller; all keys expected):
      swo_active:                 bool
      swo_days_open:              Optional[int]
      hr_14d:                     Optional[float]
      recent_class_1_count:       int
      recent_class_2_count:       int
      recent_complaints_count:    int
      phase:                      str (one of PHASE_TO_RATIO keys,
                                  'demolition', 'closeout', or 'unknown')
      most_recent_class_1_days_ago: Optional[int]
      most_recent_class_1_bucket:   Optional[str]
      most_recent_class_2_days_ago: Optional[int]
      most_recent_class_2_bucket:   Optional[str]
      borough:                    str
      work_type:                  str

    Returns:
      tier:    one of TIERS
      factors: List of {factor, weight, evidence} dicts in
               precedence-firing order. Multiple factors may fire;
               the tier reflects the highest-precedence one.
    """
    factors: List[Dict[str, Any]] = []
    tier = TIER_NORMAL

    swo_active = bool(inputs.get("swo_active"))
    swo_days = inputs.get("swo_days_open")
    hr = inputs.get("hr_14d")
    c1 = int(inputs.get("recent_class_1_count") or 0)
    c2 = int(inputs.get("recent_class_2_count") or 0)
    complaints = int(inputs.get("recent_complaints_count") or 0)
    phase = (inputs.get("phase") or "unknown").lower()

    # Rule 1 — SWO + demolition phase → IMMEDIATE
    if swo_active and phase == "demolition":
        factors.append({
            "factor": "swo_demolition_phase",
            "weight": 1.0,
            "evidence": (
                "Active stop-work order during demolition phase"
            ),
        })
        tier = TIER_IMMEDIATE

    # Rule 2 — SWO > 30d → IMMEDIATE
    if (
        swo_active
        and isinstance(swo_days, (int, float))
        and swo_days > SWO_LONG_RUNNING_DAYS
        and tier != TIER_IMMEDIATE
    ):
        factors.append({
            "factor": "swo_long_running",
            "weight": 1.0,
            "evidence": (
                f"Active stop-work order open for {int(swo_days)} days "
                f"(threshold: {SWO_LONG_RUNNING_DAYS} days)"
            ),
        })
        tier = TIER_IMMEDIATE

    # Rule 3 — CLASS-1 / Hazardous in last 7d → IMMEDIATE
    if c1 > 0:
        days_ago = inputs.get("most_recent_class_1_days_ago")
        bucket = inputs.get("most_recent_class_1_bucket")
        factors.append({
            "factor": "class_1_violation_recent",
            "weight": 1.0,
            "evidence": (
                f"CLASS-1 violation in last {WINDOW_CLASS_1_DAYS} days"
                + (f" ({_bucket_label(bucket)})" if bucket else "")
                + (f", {days_ago} days ago" if days_ago is not None else "")
            ),
        })
        if tier != TIER_IMMEDIATE:
            tier = TIER_IMMEDIATE

    # Rule 4 — HR ≥ 4.0 → IMMEDIATE
    if isinstance(hr, (int, float)) and hr >= HR_IMMEDIATE_THRESHOLD:
        factors.append({
            "factor": "hazard_ratio_immediate",
            "weight": 1.0,
            "evidence": (
                f"14-day violation rate {float(hr):.1f}× cohort baseline "
                f"(threshold: {HR_IMMEDIATE_THRESHOLD}×)"
            ),
        })
        if tier != TIER_IMMEDIATE:
            tier = TIER_IMMEDIATE

    # Rule 5 — Active SWO alone → ELEVATED (minimum)
    if swo_active and tier == TIER_NORMAL:
        factors.append({
            "factor": "swo_active",
            "weight": 0.7,
            "evidence": (
                f"Active stop-work order"
                + (
                    f" (open {int(swo_days)} days)"
                    if isinstance(swo_days, (int, float))
                    else ""
                )
            ),
        })
        tier = TIER_ELEVATED
    elif swo_active and tier == TIER_ELEVATED:
        # Defensive — SWO is also a contributing factor at ELEVATED
        factors.append({
            "factor": "swo_active",
            "weight": 0.7,
            "evidence": "Active stop-work order",
        })

    # Rule 6 — CLASS-2 in last 14d → ELEVATED
    if c2 > 0:
        days_ago = inputs.get("most_recent_class_2_days_ago")
        bucket = inputs.get("most_recent_class_2_bucket")
        factors.append({
            "factor": "class_2_violation_recent",
            "weight": 0.6,
            "evidence": (
                f"CLASS-2 violation in last {WINDOW_CLASS_2_DAYS} days"
                + (f" ({_bucket_label(bucket)})" if bucket else "")
                + (f", {days_ago} days ago" if days_ago is not None else "")
            ),
        })
        if tier == TIER_NORMAL:
            tier = TIER_ELEVATED

    # Rule 7 — HR ∈ [1.5, 4.0) → ELEVATED
    if (
        isinstance(hr, (int, float))
        and HR_ELEVATED_THRESHOLD <= hr < HR_IMMEDIATE_THRESHOLD
    ):
        factors.append({
            "factor": "hazard_ratio_elevated",
            "weight": 0.5,
            "evidence": (
                f"14-day violation rate {float(hr):.1f}× cohort baseline "
                f"(threshold: {HR_ELEVATED_THRESHOLD}×)"
            ),
        })
        if tier == TIER_NORMAL:
            tier = TIER_ELEVATED

    # Rule 8 — ≥3 complaints in last 30d → ELEVATED
    if complaints >= COMPLAINT_CLUSTER_THRESHOLD:
        factors.append({
            "factor": "complaint_clustering",
            "weight": 0.4,
            "evidence": (
                f"{complaints} complaints filed in last "
                f"{WINDOW_COMPLAINTS_DAYS} days"
            ),
        })
        if tier == TIER_NORMAL:
            tier = TIER_ELEVATED

    # Phase override (Stage 2.A L2) — closeout phase + HR in [1.5, 2.0)
    # demotes the HR-driven escalation. SWO + CLASS-1 escalations are
    # NOT demoted (active site risk indicators).
    if (
        tier == TIER_ELEVATED
        and phase == "closeout"
        and isinstance(hr, (int, float))
        and HR_ELEVATED_THRESHOLD <= hr < CLOSEOUT_DEMOTE_MAX
        and not swo_active
        and c1 == 0
        and c2 == 0
        and complaints < COMPLAINT_CLUSTER_THRESHOLD
    ):
        # Demote — record the demotion as a factor for transparency.
        factors.append({
            "factor": "closeout_phase_demotion",
            "weight": -0.5,
            "evidence": (
                "Closeout phase context — HR ratio reflects punch-list "
                "inspection backlog, not active site risk"
            ),
        })
        tier = TIER_NORMAL

    return tier, factors


# ── Pure logic: primary_reason formatter ──────────────────────────


def _format_primary_reason(
    tier: str,
    factors: List[Dict[str, Any]],
    inputs: Dict[str, Any],
) -> str:
    """Pre-rendered GC-voice reason per Stage 2.A L8 templates.

    Picks the highest-priority factor (first IMMEDIATE-tier rule, else
    first ELEVATED-tier rule, else NORMAL default) and formats it with
    borough/work_type/days/hr interpolations.
    """
    borough = _borough_label(inputs.get("borough") or "")
    work_type = inputs.get("work_type") or "projects"
    hr = inputs.get("hr_14d")
    phase = (inputs.get("phase") or "unknown").lower()

    if tier == TIER_IMMEDIATE:
        # Pick the first IMMEDIATE-eligible factor.
        for f in factors:
            name = f.get("factor", "")
            if name == "swo_demolition_phase":
                return "Active stop-work order during demolition phase"
            if name == "swo_long_running":
                d = inputs.get("swo_days_open")
                if d is not None:
                    return (
                        f"Active stop-work order open for {int(d)} days"
                    )
                return "Active stop-work order — long-running"
            if name == "class_1_violation_recent":
                days_ago = inputs.get("most_recent_class_1_days_ago")
                bucket = _bucket_label(
                    inputs.get("most_recent_class_1_bucket"),
                )
                if days_ago is not None:
                    return (
                        f"CLASS-1 violation issued {days_ago} days ago "
                        f"for {bucket} hazard"
                    )
                return f"Recent CLASS-1 violation ({bucket})"
            if name == "hazard_ratio_immediate":
                if isinstance(hr, (int, float)):
                    return (
                        f"Violation rate {float(hr):.1f}× typical for "
                        f"{borough} {work_type} projects"
                    )
        return "High-priority risk indicators present"

    if tier == TIER_ELEVATED:
        for f in factors:
            name = f.get("factor", "")
            if name == "swo_active":
                d = inputs.get("swo_days_open")
                if d is not None:
                    return (
                        f"Active stop-work order open for {int(d)} days"
                    )
                return "Active stop-work order"
            if name == "class_2_violation_recent":
                days_ago = inputs.get("most_recent_class_2_days_ago")
                bucket = _bucket_label(
                    inputs.get("most_recent_class_2_bucket"),
                )
                if days_ago is not None:
                    return (
                        f"CLASS-2 violation issued {days_ago} days ago "
                        f"for {bucket}"
                    )
                return f"Recent CLASS-2 violation ({bucket})"
            if name == "hazard_ratio_elevated":
                if isinstance(hr, (int, float)):
                    return (
                        f"Violation rate {float(hr):.1f}× typical for "
                        f"{borough} {work_type} projects"
                    )
            if name == "complaint_clustering":
                n = int(inputs.get("recent_complaints_count") or 0)
                return (
                    f"{n} complaints filed in past "
                    f"{WINDOW_COMPLAINTS_DAYS} days"
                )
        return f"Elevated risk indicators for {borough} {work_type}"

    # NORMAL
    return "All indicators within typical range for similar projects"


# ── DB integration helpers ────────────────────────────────────────


def _hazard_ratio_14d(cache: Dict[str, Any]) -> Optional[float]:
    """Canonical hazard ratio derivation. Exposed on the response per
    Stage 2.A L9 — single backend source-of-truth."""
    p = cache.get("prob_violation_14d")
    b = cache.get("anchored_baseline_prob_14d")
    try:
        p = float(p) if p is not None else None
        b = float(b) if b is not None else None
    except (TypeError, ValueError):
        return None
    if p is None or b is None or b <= 0:
        return None
    return p / b


async def _resolve_swo_state(
    db: Any,
    project_id: str,
    now: datetime,
) -> Dict[str, Any]:
    """Return {is_active: bool, days_open: Optional[int]} for the
    project's SWO state. Mirrors compute_x_now_for_project's
    dob_logs aggregate but ALSO captures the earliest open SWO's
    detected_at to compute days-open."""
    out: Dict[str, Any] = {"is_active": False, "days_open": None}
    dob_logs = getattr(db, "dob_logs", None)
    if dob_logs is None or not project_id:
        return out

    # Import here to avoid module-cycle issues
    from lib.statistical_engine.live_mutation import _SWO_CLOSED_STATES

    try:
        active = await dob_logs.find(
            {
                "project_id":       project_id,
                "is_deleted":       {"$ne": True},
                "record_type":      "swo",
                "resolution_state": {"$nin": list(_SWO_CLOSED_STATES)},
            },
            {"detected_at": 1, "violation_date": 1},
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[phase1w11] SWO state lookup failed for %s: %r",
            project_id, e,
        )
        return out

    if not active:
        return out
    out["is_active"] = True

    # Earliest open SWO determines days_open. Prefer detected_at;
    # fall back to violation_date (YYYYMMDD text). Both fields may
    # coexist on dob_logs depending on ingestion path.
    earliest: Optional[datetime] = None
    for row in active:
        d = row.get("detected_at")
        if isinstance(d, datetime):
            dt = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            if earliest is None or dt < earliest:
                earliest = dt
            continue
        vd = row.get("violation_date")
        if isinstance(vd, str) and len(vd) >= 8 and vd.isdigit():
            try:
                dt = datetime(
                    int(vd[0:4]), int(vd[4:6]), int(vd[6:8]),
                    tzinfo=timezone.utc,
                )
                if earliest is None or dt < earliest:
                    earliest = dt
            except (ValueError, TypeError):
                continue
    if earliest is not None:
        days = (now - earliest).total_seconds() / 86400.0
        out["days_open"] = int(max(0, days))
    return out


async def _resolve_recent_violations(
    db: Any,
    bin_id: str,
    now: datetime,
) -> Dict[str, Any]:
    """Pull recent ECB violations split by severity / window. Returns:

      {
        "class_1_count":               int (in last WINDOW_CLASS_1_DAYS),
        "most_recent_class_1_days":    Optional[int],
        "most_recent_class_1_bucket":  Optional[str] (via classify_violation),
        "class_2_count":               int (in last WINDOW_CLASS_2_DAYS),
        "most_recent_class_2_days":    Optional[int],
        "most_recent_class_2_bucket":  Optional[str],
      }

    Per Stage 2.A L7 severity mapping: 'CLASS - 1' AND 'Hazardous' both
    fold into class_1_count. 'CLASS - 2' folds into class_2_count.
    Other severity values are excluded.
    """
    out: Dict[str, Any] = {
        "class_1_count": 0, "most_recent_class_1_days": None,
        "most_recent_class_1_bucket": None,
        "class_2_count": 0, "most_recent_class_2_days": None,
        "most_recent_class_2_bucket": None,
    }
    coll = getattr(db, "socrata_ecb_violations_historical", None)
    if coll is None or not bin_id:
        return out

    # Wider window to cover both class-1 (7d) and class-2 (14d) in a
    # single query. Filter at Python level for the per-severity counts.
    max_window = max(WINDOW_CLASS_1_DAYS, WINDOW_CLASS_2_DAYS)
    cutoff_yyyymmdd = (now - timedelta(days=max_window)).strftime("%Y%m%d")
    try:
        rows = await coll.find(
            {"bin": str(bin_id), "issue_date": {"$gte": cutoff_yyyymmdd}},
            {
                "severity": 1, "issue_date": 1,
                "violation_type": 1, "violation_description": 1,
            },
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover
        logger.warning(
            "[phase1w11] recent_violations lookup failed for bin=%r: %r",
            bin_id, e,
        )
        return out

    # Import classify_violation lazily to avoid cycle (PR-A taxonomy
    # module).
    from lib.statistical_engine.violation_taxonomy import (
        classify_violation,
    )

    cutoff_c1_yyyymmdd = (
        now - timedelta(days=WINDOW_CLASS_1_DAYS)
    ).strftime("%Y%m%d")

    best_c1: Optional[Dict[str, Any]] = None
    best_c2: Optional[Dict[str, Any]] = None
    for r in rows or []:
        sev = r.get("severity") or ""
        issue = r.get("issue_date") or ""
        if not issue:
            continue
        if sev in SEVERITY_TOP:
            # CLASS-1 / Hazardous — counts only if within 7d.
            if issue >= cutoff_c1_yyyymmdd:
                out["class_1_count"] += 1
                if best_c1 is None or issue > (best_c1.get("issue_date") or ""):
                    best_c1 = r
        elif sev in SEVERITY_ELEVATED:
            # CLASS-2 — within 14d window (full max_window).
            out["class_2_count"] += 1
            if best_c2 is None or issue > (best_c2.get("issue_date") or ""):
                best_c2 = r

    if best_c1 is not None:
        out["most_recent_class_1_days"] = _days_between_yyyymmdd(
            best_c1.get("issue_date"), now,
        )
        out["most_recent_class_1_bucket"] = classify_violation(
            best_c1.get("violation_type"),
            best_c1.get("violation_description"),
        )
    if best_c2 is not None:
        out["most_recent_class_2_days"] = _days_between_yyyymmdd(
            best_c2.get("issue_date"), now,
        )
        out["most_recent_class_2_bucket"] = classify_violation(
            best_c2.get("violation_type"),
            best_c2.get("violation_description"),
        )
    return out


async def _resolve_recent_complaints_count(
    db: Any,
    bin_id: str,
    now: datetime,
) -> int:
    """Count complaints against this BIN in the last
    WINDOW_COMPLAINTS_DAYS days. socrata_complaints_historical stores
    date_entered as MM/DD/YYYY text (per PR #33 fix); to filter
    correctly we use the same substring-reorder trick at query time.
    For simplicity, pull all and filter in Python — the per-BIN result
    set is small."""
    coll = getattr(db, "socrata_complaints_historical", None)
    if coll is None or not bin_id:
        return 0
    try:
        rows = await coll.find(
            {"bin": str(bin_id)},
            {"date_entered": 1},
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover
        logger.warning(
            "[phase1w11] complaints count lookup failed for bin=%r: %r",
            bin_id, e,
        )
        return 0
    cutoff = now - timedelta(days=WINDOW_COMPLAINTS_DAYS)
    n = 0
    for r in rows or []:
        d = r.get("date_entered")
        if not isinstance(d, str) or len(d) < 10:
            continue
        # MM/DD/YYYY → datetime
        try:
            dt = datetime(
                int(d[6:10]), int(d[0:2]), int(d[3:5]),
                tzinfo=timezone.utc,
            )
        except (ValueError, TypeError):
            continue
        if dt >= cutoff:
            n += 1
    return n


def _days_between_yyyymmdd(yyyymmdd: Optional[str], now: datetime) -> Optional[int]:
    """Days between a YYYYMMDD text date and `now`. None on parse fail."""
    if not yyyymmdd or len(yyyymmdd) < 8 or not yyyymmdd.isdigit():
        return None
    try:
        dt = datetime(
            int(yyyymmdd[0:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]),
            tzinfo=timezone.utc,
        )
    except (ValueError, TypeError):
        return None
    days = (now - dt).total_seconds() / 86400.0
    return int(max(0, days))


async def _resolve_project_phase(
    db: Any,
    project: Dict[str, Any],
) -> str:
    """Read the project's most-recent daily_log.phase. Returns the
    enum string ('foundation' | ... | 'closeout') or 'unknown' if no
    daily_log with a phase exists. 'demolition' may appear too — the
    directive's tier rules recognize it as a string override even though
    it's not in PHASE_TO_RATIO."""
    project_id = str(project.get("_id") or project.get("id") or "")
    daily_logs = getattr(db, "daily_logs", None)
    if not project_id or daily_logs is None:
        return "unknown"
    try:
        log = await daily_logs.find_one(
            {
                "project_id": project_id,
                "phase":      {"$nin": [None, ""]},
                "is_deleted": {"$ne": True},
            },
            sort=[("date", -1)],
            projection={"phase": 1},
        )
    except Exception as e:  # pragma: no cover
        logger.warning(
            "[phase1w11] daily_logs phase lookup failed for %s: %r",
            project_id, e,
        )
        return "unknown"
    if log and log.get("phase"):
        return str(log["phase"])
    return "unknown"


# ── Public driver ─────────────────────────────────────────────────


async def compute_defcon_status(
    db: Any,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """End-to-end Defcon status computation.

    Resolves all inputs from DB, applies the pure tier-precedence
    logic, builds the response dict per Stage 2.A L8.

    Caching: none. Sub-100ms with indexed reads; SWO state changes
    intra-day so per-request freshness is the priority.
    """
    cur_now = now or datetime.now(timezone.utc)
    if cur_now.tzinfo is None:
        cur_now = cur_now.replace(tzinfo=timezone.utc)

    project_id = str(project.get("_id") or project.get("id") or "")
    bin_id = str(project.get("nyc_bin") or "") or ""
    borough = (project.get("borough") or "").upper().strip()
    cache = project.get("prediction_cache") or {}
    hr_14d = _hazard_ratio_14d(cache)

    # Resolve SWO state
    swo_state = await _resolve_swo_state(db, project_id, cur_now)

    # Resolve phase
    phase = await _resolve_project_phase(db, project)

    # Resolve recent violations (split by severity / window)
    violations = await _resolve_recent_violations(db, bin_id, cur_now)

    # Resolve recent complaints count
    n_complaints = await _resolve_recent_complaints_count(
        db, bin_id, cur_now,
    )

    # work_type: most-recent Initial Permit per BIN. Cheap lookup.
    work_type = "projects"
    permits = getattr(db, "socrata_permits_historical", None)
    if permits is not None and bin_id:
        try:
            perm = await permits.find_one(
                {"bin": bin_id, "filing_reason": "Initial Permit"},
                sort=[("issued_date", -1)],
                projection={"work_type": 1, "borough": 1},
            )
            if perm:
                work_type = (perm.get("work_type") or "projects").strip()
                if not borough:
                    borough = (perm.get("borough") or "").upper().strip()
        except Exception:  # pragma: no cover
            pass

    inputs = {
        "swo_active":                   bool(swo_state.get("is_active")),
        "swo_days_open":                swo_state.get("days_open"),
        "hr_14d":                       hr_14d,
        "recent_class_1_count":         violations["class_1_count"],
        "recent_class_2_count":         violations["class_2_count"],
        "recent_complaints_count":      n_complaints,
        "phase":                        phase,
        "most_recent_class_1_days_ago": violations["most_recent_class_1_days"],
        "most_recent_class_1_bucket":   violations["most_recent_class_1_bucket"],
        "most_recent_class_2_days_ago": violations["most_recent_class_2_days"],
        "most_recent_class_2_bucket":   violations["most_recent_class_2_bucket"],
        "borough":                      borough or "",
        "work_type":                    work_type,
    }

    tier, factors = _apply_tier_precedence(inputs)
    primary_reason = _format_primary_reason(tier, factors, inputs)

    # PR #50 — pre-render GC-voice strings. The frontend renders these
    # directly; the raw contributing_factors + cohort_context dicts stay
    # in the response for engineering debug only.
    cohort_comparison_text = _cohort_comparison_text(
        hr_14d, borough, work_type,
    )
    contributing_factors_text = _contributing_factors_to_text(factors)

    return {
        "tier":               tier,
        "tier_color":         TIER_TO_COLOR.get(tier, "green"),
        "primary_reason":     primary_reason,
        "contributing_factors": factors,
        "contributing_factors_text": contributing_factors_text,
        "cohort_comparison_text":    cohort_comparison_text,
        "last_evaluated_at":  cur_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cohort_context": {
            "cohort_baseline_rate": cache.get("anchored_baseline_prob_14d"),
            "project_rate_ratio":   hr_14d,
            "n_peer_matches":       cache.get("cohort_sample_size"),
        },
    }
