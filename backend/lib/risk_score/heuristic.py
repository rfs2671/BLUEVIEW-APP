"""Phase V2.1 — heuristic risk-score model v1.

Pure scoring math (no DB access) lives in `score_from_inputs`,
`bootstrap_confidence_interval`, and `top_contributing_factors`.
The async `gather_inputs` helper does the DB work; the orchestrator
in `orchestrator.py` ties everything together and writes results.

────────────────────────────────────────────────────────────────────
Domain expert weighting
────────────────────────────────────────────────────────────────────

These are INITIAL weights from public-source DOB violation data
analysis (NYC OpenData violations + permit history, MR.14 sample
of 1,200 sites cross-referenced with year-over-year incidents).
They are NOT calibrated against ex-DOB-inspector ground truth yet.

Ex-DOB inspector consultation is pending. After ≥100 inspector
reviews land in `risk_score_reviews`, the operator should:

  1. Run `compute_calibration_stats(...)` to get the Brier score
     and ROC-AUC.
  2. Inspect the per-factor distribution of misclassifications
     (`scripts/risk_score_calibration_audit.py`, planned).
  3. Manually adjust this WEIGHTS dict — DO NOT auto-update from
     the calibration loop. A bad signal ("inspector marks site
     OK because they like the GC") would otherwise corrupt the
     model.
  4. Bump MODEL_VERSION in schema.py so the new weights aren't
     compared against scores produced by the old weights.

Each factor's weight reflects:
  • how directly it triggers a DOB inspector citation,
  • how observable it is in our existing data,
  • how responsive it is to operator action.

The weights sum to 100 by design — a project that's maxed out on
every input scores exactly 100. Each input contributes
`weight * normalized_value` where normalized_value ∈ [0, 1].
────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Input keys (canonical order) ──────────────────────────────────

INPUT_KEY_ACTIVE_DOB_VIOLATIONS         = "active_dob_violations"
INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION     = "permit_days_to_expiration"
INPUT_KEY_INSPECTION_COMPLIANCE_MISSED  = "inspection_compliance_missed"
INPUT_KEY_DEFICIENCY_COUNT_30D          = "deficiency_count_30d"
INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP   = "subcontractor_insurance_expirations"
INPUT_KEY_MISSING_LOGS_30D              = "missing_logs_30d"
INPUT_KEY_SST_EXPIRATIONS_NEXT_30D      = "sst_expirations_next_30d"
INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY      = "days_since_last_activity"

INPUT_KEYS: Tuple[str, ...] = (
    INPUT_KEY_ACTIVE_DOB_VIOLATIONS,
    INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION,
    INPUT_KEY_INSPECTION_COMPLIANCE_MISSED,
    INPUT_KEY_DEFICIENCY_COUNT_30D,
    INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP,
    INPUT_KEY_MISSING_LOGS_30D,
    INPUT_KEY_SST_EXPIRATIONS_NEXT_30D,
    INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY,
)


# ── Weights (sum to 100) ──────────────────────────────────────────
#
# Rationale per weight is documented in
# docs/features/v2-risk-score-weights.md. Inline summary:

WEIGHTS: Dict[str, float] = {
    # 22 — Active DOB violations against this BIN. Directly visible
    # to the inspector; the failure mode every other input is
    # leading-indicator FOR. Highest weight.
    INPUT_KEY_ACTIVE_DOB_VIOLATIONS:        22.0,
    # 18 — Permit expiration imminent / past due. Expired permits
    # halt work + trigger violations. Severe but recoverable.
    INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION:    18.0,
    # 15 — Inspection windows past their by_date with no record
    # of compliance. Inspectors flag this on first walkthrough.
    INPUT_KEY_INSPECTION_COMPLIANCE_MISSED: 15.0,
    # 12 — V2.0 logbook deficiencies. Process indicator — high
    # density correlates with lapses inspectors find.
    INPUT_KEY_DEFICIENCY_COUNT_30D:         12.0,
    # 10 — Subcontractors whose COI has expired. GC liability;
    # contributes to the "prime contractor responsible" finding
    # on incidents.
    INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP:  10.0,
    # 9 — Missing daily-log days. Lower than deficiency count
    # because operators sometimes forget but it's mostly process
    # not safety.
    INPUT_KEY_MISSING_LOGS_30D:              9.0,
    # 8 — SST card expirations in the next 30 days. LL196 issue;
    # zero-grace-period violations are rare in practice but
    # citations can stack.
    INPUT_KEY_SST_EXPIRATIONS_NEXT_30D:      8.0,
    # 6 — Days since last activity. Stale data isn't directly bad
    # (could be a finished project), but high staleness on a
    # project marked "active" is a red flag for monitoring gaps.
    INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY:      6.0,
}

# Sanity check at import time — if a future edit forgets to keep
# the weights summing to 100, fail loudly rather than silently
# producing capped-at-something-other-than-100 scores.
_WEIGHT_SUM = sum(WEIGHTS.values())
if abs(_WEIGHT_SUM - 100.0) > 0.001:
    raise AssertionError(
        f"risk_score WEIGHTS must sum to 100; got {_WEIGHT_SUM}",
    )


# ── Normalization caps ────────────────────────────────────────────
#
# Each input has a "max-meaningful" value. Anything past this caps
# at 1.0 in the normalized score — diminishing returns once you've
# gone fully nonconforming on one axis. Tuned to roughly match what
# a worst-case site looks like in practice.

NORMALIZATION_CAPS: Dict[str, float] = {
    # 5+ active violations = max risk on this axis. Above 5 the
    # building is already a regulatory disaster; the score doesn't
    # need to keep climbing.
    INPUT_KEY_ACTIVE_DOB_VIOLATIONS:        5.0,
    # Permit days inverted: 0 days = 1.0 (expired), 30+ days = 0.
    # Handled specially in `_normalize_input`.
    INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION:   30.0,
    # 10+ missed inspection windows = max. Most projects won't
    # hit 5.
    INPUT_KEY_INSPECTION_COMPLIANCE_MISSED: 10.0,
    # 20+ deficiencies in 30 days = max. Average compliant project
    # has 1-3.
    INPUT_KEY_DEFICIENCY_COUNT_30D:         20.0,
    INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP:   5.0,
    # 22 expected workdays in 30 days; 22 missing = total absence.
    INPUT_KEY_MISSING_LOGS_30D:             22.0,
    # 50+ workers expiring in next 30 days = max (serious LL196
    # exposure).
    INPUT_KEY_SST_EXPIRATIONS_NEXT_30D:     50.0,
    # 30+ days stale on an active project = max.
    INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY:     30.0,
}


# ── Confidence interval parameters ────────────────────────────────
#
# Bootstrap with Gaussian noise on each input. Models the
# uncertainty in input *measurement* — did we miss a violation?
# is the SST roster current? did one daily log silently fail to
# write? — rather than uncertainty in the weights themselves
# (which is what we'd model if we had a posterior over the WEIGHTS
# dict, which we don't until we have ≥100 calibration reviews).

BOOTSTRAP_SAMPLES        = 1000
BOOTSTRAP_NOISE_SIGMA    = 0.10   # 10% gaussian noise per sample
CONFIDENCE_INTERVAL_PCT  = 95     # 95% CI = (2.5th, 97.5th) pct

# Top-N contributing factors surfaced on the FE drilldown. 5 picked
# because the score has 8 inputs total — showing 5 keeps the card
# scannable while still surfacing what an operator might not have
# guessed.
TOP_FACTOR_COUNT = 5


# ── Pure scoring math ─────────────────────────────────────────────


def _normalize_input(key: str, raw_value: Optional[float]) -> float:
    """Map a raw input value to [0, 1] using NORMALIZATION_CAPS.

    For most inputs `0 = clean, cap = max risk`. The exception is
    `permit_days_to_expiration`, which inverts (0 days remaining
    is the most-risk side; 30+ days is the least-risk side).
    """
    if raw_value is None:
        return 0.0
    v = float(raw_value)
    cap = NORMALIZATION_CAPS.get(key, 1.0)
    if cap <= 0:
        return 0.0
    if key == INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION:
        # Invert: 0 days remaining → 1.0; cap (30) days → 0.0.
        # Negative days (already expired) clamp to 1.0.
        if v < 0:
            v = 0.0
        if v >= cap:
            return 0.0
        return max(0.0, min(1.0, (cap - v) / cap))
    if v < 0:
        v = 0.0
    if v >= cap:
        return 1.0
    return v / cap


def _per_factor_breakdown(
    inputs: Dict[str, Optional[float]],
) -> List[Dict[str, float]]:
    """Return one row per input with raw value, weight,
    normalized value (0-1), and contribution (weight * normalized).

    Order matches INPUT_KEYS for deterministic test pinning."""
    out: List[Dict[str, float]] = []
    for key in INPUT_KEYS:
        raw = inputs.get(key)
        norm = _normalize_input(key, raw)
        weight = WEIGHTS[key]
        contribution = weight * norm
        out.append({
            "factor": key,
            "value": float(raw) if raw is not None else 0.0,
            "weight": weight,
            "normalized": norm,
            "contribution": contribution,
        })
    return out


def score_from_inputs(inputs: Dict[str, Optional[float]]) -> float:
    """Pure scoring function — sums weight * normalized for every
    input, clamps to [0, 100]. Same call shape as
    `_per_factor_breakdown` but only returns the scalar."""
    total = 0.0
    for key in INPUT_KEYS:
        norm = _normalize_input(key, inputs.get(key))
        total += WEIGHTS[key] * norm
    if total < 0.0:
        total = 0.0
    if total > 100.0:
        total = 100.0
    return total


def bootstrap_confidence_interval(
    inputs: Dict[str, Optional[float]],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    sigma: float = BOOTSTRAP_NOISE_SIGMA,
    rng: Optional[random.Random] = None,
) -> Tuple[float, float]:
    """Return (low, high) of the 95% CI by resampling each input
    with multiplicative Gaussian noise and recomputing the score
    `samples` times.

    Why bootstrap rather than a closed-form variance: the
    normalization step is non-linear (clamps at 0 and at the cap),
    so propagating variance analytically would mis-state the
    interval near the boundaries. A 1000-sample bootstrap is fast
    enough (~5ms) and handles the boundary cases by construction.

    Deterministic inputs (every input == 0) collapse the CI to the
    point estimate, which is correct.
    """
    rng = rng or random.Random(0)
    samples = max(1, int(samples))
    pct_low = (100 - CONFIDENCE_INTERVAL_PCT) / 2.0    # 2.5
    pct_high = 100.0 - pct_low                          # 97.5

    bootstrap_scores: List[float] = []
    for _ in range(samples):
        perturbed: Dict[str, Optional[float]] = {}
        for key in INPUT_KEYS:
            raw = inputs.get(key)
            if raw is None or float(raw) == 0.0:
                perturbed[key] = raw
                continue
            noise = 1.0 + rng.gauss(0.0, sigma)
            perturbed[key] = max(0.0, float(raw) * noise)
        bootstrap_scores.append(score_from_inputs(perturbed))

    bootstrap_scores.sort()

    def _percentile(sorted_vals: List[float], p: float) -> float:
        if not sorted_vals:
            return 0.0
        # Nearest-rank method — simple, no numpy dep.
        k = max(0, min(len(sorted_vals) - 1,
                       int(round((p / 100.0) * (len(sorted_vals) - 1)))))
        return sorted_vals[k]

    low = _percentile(bootstrap_scores, pct_low)
    high = _percentile(bootstrap_scores, pct_high)
    return float(low), float(high)


def top_contributing_factors(
    inputs: Dict[str, Optional[float]],
    *,
    n: int = TOP_FACTOR_COUNT,
) -> List[Dict[str, float]]:
    """Return the top-N inputs by absolute `contribution`. Used by
    the FE drilldown ("what's pushing my score up?"). Stable order:
    contribution desc, then INPUT_KEYS order on ties (so two zero-
    contribution inputs always sort the same way)."""
    breakdown = _per_factor_breakdown(inputs)
    # Stable sort: secondary key is INPUT_KEYS order which is
    # already the iteration order, so we just need a stable sort by
    # negative contribution.
    indexed = list(enumerate(breakdown))
    indexed.sort(key=lambda pair: (-pair[1]["contribution"], pair[0]))
    out = [b for _i, b in indexed[: max(0, n)]]
    return out


# ── Async DB-side input gathering ─────────────────────────────────


async def gather_inputs(
    db,
    *,
    project: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, float]:
    """Compute every model input from live data. One project, one
    call. Designed to be safely re-run — every input has a graceful
    fallback to 0 if a query fails or the data is missing.

    Inputs collected:

      • active_dob_violations         — count of dob_logs with
        signal_kind='violation_dob' detected in the last 90 days.
      • permit_days_to_expiration     — minimum days remaining
        across all active permits on this BIN. Negative if any
        already expired; capped at 0 below.
      • inspection_compliance_missed  — len(inspection_windows)
        where by_date < today and not done.
      • deficiency_count_30d          — count of logbook_entries
        with category='deficiency' in the last 30 days.
      • subcontractor_insurance_expirations — count of
        subcontractors with coi_on_file=False or coi_expiration
        in the past or within 30 days from today.
      • missing_logs_30d              — count of logbook_entries
        with category='daily_log' status='missing' in the last
        30 days.
      • sst_expirations_next_30d      — count of workers whose
        SST cert expiration falls in the next 30 days.
      • days_since_last_activity      — max(now - latest dob_log
        detected_at, now - latest daily_log date). NULL → 0.
    """
    cur_now = now or datetime.now(timezone.utc)
    today = cur_now.date()
    project_id = str(project.get("_id") or project.get("id") or "")
    company_id = project.get("company_id")
    nyc_bin = project.get("nyc_bin")
    inputs: Dict[str, float] = {k: 0.0 for k in INPUT_KEYS}
    if not project_id:
        return inputs

    # 1) Active DOB violations on the BIN, last 90 days.
    cutoff_90 = cur_now - timedelta(days=90)
    try:
        q: Dict[str, Any] = {
            "project_id": project_id,
            "signal_kind": "violation_dob",
            "detected_at": {"$gte": cutoff_90},
        }
        n = await db.dob_logs.count_documents(q)
        inputs[INPUT_KEY_ACTIVE_DOB_VIOLATIONS] = float(n)
    except Exception as e:
        logger.warning(f"[risk_score] dob_violations count failed: {e!r}")

    # 2) Permit days to expiration (min across active permits).
    try:
        permit_cursor = db.dob_logs.find({
            "project_id": project_id,
            "signal_kind": {"$in": ["permit_issued", "permit_renewed"]},
        })
        min_days: Optional[float] = None
        async for p in permit_cursor:
            exp = p.get("expiration_date")
            if not exp:
                continue
            if isinstance(exp, str):
                try:
                    exp_dt = datetime.strptime(exp[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
            elif isinstance(exp, datetime):
                exp_dt = exp.date()
            else:
                continue
            days = (exp_dt - today).days
            if min_days is None or days < min_days:
                min_days = float(days)
        # If no permits were found, treat as full-window remaining
        # (no risk on this axis). The spec capped at 30 days; we
        # encode "no data" as the cap so unmonitored projects don't
        # get flagged on permit-expiration.
        inputs[INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION] = (
            float(min_days) if min_days is not None else 30.0
        )
    except Exception as e:
        logger.warning(f"[risk_score] permit_days failed: {e!r}")
        inputs[INPUT_KEY_PERMIT_DAYS_TO_EXPIRATION] = 30.0

    # 3) Inspection compliance missed (project.inspection_windows[]).
    try:
        windows = project.get("inspection_windows") or []
        missed = 0
        for w in windows:
            if not isinstance(w, dict):
                continue
            if w.get("done"):
                continue
            by_date_raw = w.get("by_date")
            if not by_date_raw:
                continue
            try:
                by_date = datetime.strptime(
                    str(by_date_raw)[:10], "%Y-%m-%d",
                ).date()
            except ValueError:
                continue
            if by_date < today:
                missed += 1
        inputs[INPUT_KEY_INSPECTION_COMPLIANCE_MISSED] = float(missed)
    except Exception as e:
        logger.warning(f"[risk_score] inspection_compliance failed: {e!r}")

    # 4) Deficiencies last 30 days (V2.0 logbook).
    cutoff_30_str = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    try:
        n = await db.logbook_entries.count_documents({
            "project_id": project_id,
            "category": "deficiency",
            "entry_date": {"$gte": cutoff_30_str},
        })
        inputs[INPUT_KEY_DEFICIENCY_COUNT_30D] = float(n)
    except Exception as e:
        logger.warning(f"[risk_score] deficiency_count failed: {e!r}")

    # 5) Subcontractor insurance expirations.
    try:
        subs_cursor = db.subcontractors.find(
            {"company_id": company_id} if company_id else {},
        )
        cutoff_future = today + timedelta(days=30)
        expired_or_soon = 0
        async for s in subs_cursor:
            if s.get("coi_on_file") is False:
                expired_or_soon += 1
                continue
            exp = s.get("coi_expiration") or s.get("coi_expiration_date")
            if not exp:
                continue
            if isinstance(exp, str):
                try:
                    exp_d = datetime.strptime(exp[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
            elif isinstance(exp, datetime):
                exp_d = exp.date()
            else:
                continue
            if exp_d <= cutoff_future:
                expired_or_soon += 1
        inputs[INPUT_KEY_SUBCONTRACTOR_INSURANCE_EXP] = float(expired_or_soon)
    except Exception as e:
        logger.warning(f"[risk_score] sub_insurance failed: {e!r}")

    # 6) Missing daily logs last 30 days.
    try:
        n = await db.logbook_entries.count_documents({
            "project_id": project_id,
            "category": "daily_log",
            "status": "missing",
            "entry_date": {"$gte": cutoff_30_str},
        })
        inputs[INPUT_KEY_MISSING_LOGS_30D] = float(n)
    except Exception as e:
        logger.warning(f"[risk_score] missing_logs failed: {e!r}")

    # 7) SST expirations in next 30 days.
    try:
        # Workers query: project workers whose company matches and
        # who have certifications. We count distinct workers, not
        # cert rows.
        workers_cursor = db.workers.find(
            {"company_id": company_id} if company_id else {},
        )
        cutoff_future = today + timedelta(days=30)
        expiring = 0
        async for w in workers_cursor:
            certs = w.get("certifications") or []
            worker_expires_in_window = False
            for c in certs:
                if not isinstance(c, dict):
                    continue
                if c.get("type") not in (
                    "SST_FULL", "SST_LIMITED", "SST_SUPERVISOR",
                ):
                    continue
                exp = c.get("expiration_date")
                if not exp:
                    continue
                if isinstance(exp, str):
                    try:
                        exp_d = datetime.strptime(exp[:10], "%Y-%m-%d").date()
                    except ValueError:
                        continue
                elif isinstance(exp, datetime):
                    exp_d = exp.date()
                else:
                    continue
                if today <= exp_d <= cutoff_future:
                    worker_expires_in_window = True
                    break
            if worker_expires_in_window:
                expiring += 1
        inputs[INPUT_KEY_SST_EXPIRATIONS_NEXT_30D] = float(expiring)
    except Exception as e:
        logger.warning(f"[risk_score] sst_expirations failed: {e!r}")

    # 8) Days since last activity (max staleness).
    try:
        latest_dob = None
        latest_log = None
        cur = db.dob_logs.find(
            {"project_id": project_id},
        ).sort("detected_at", -1).limit(1)
        async for d in cur:
            latest_dob = d.get("detected_at")
        cur = db.daily_logs.find(
            {"project_id": project_id, "is_deleted": {"$ne": True}},
        ).sort("date", -1).limit(1)
        async for d in cur:
            ds = d.get("date")
            if isinstance(ds, str):
                try:
                    latest_log = datetime.strptime(
                        ds[:10], "%Y-%m-%d",
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            elif isinstance(ds, datetime):
                latest_log = ds
        candidates = []
        if isinstance(latest_dob, datetime):
            if latest_dob.tzinfo is None:
                latest_dob = latest_dob.replace(tzinfo=timezone.utc)
            candidates.append((cur_now - latest_dob).days)
        if isinstance(latest_log, datetime):
            if latest_log.tzinfo is None:
                latest_log = latest_log.replace(tzinfo=timezone.utc)
            candidates.append((cur_now - latest_log).days)
        if candidates:
            inputs[INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY] = float(min(candidates))
        else:
            inputs[INPUT_KEY_DAYS_SINCE_LAST_ACTIVITY] = 0.0
    except Exception as e:
        logger.warning(f"[risk_score] days_since_activity failed: {e!r}")

    return inputs


def calculate_risk_score(
    inputs: Dict[str, Optional[float]],
    *,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Pure end-to-end scorer: inputs → {score, ci, top factors,
    full breakdown}. Used by the orchestrator before persisting,
    and by the on-demand `/calculate` endpoint."""
    score = score_from_inputs(inputs)
    low, high = bootstrap_confidence_interval(inputs, rng=rng)
    factors = top_contributing_factors(inputs)
    return {
        "score": score,
        "confidence_low": low,
        "confidence_high": high,
        "contributing_factors": factors,
        "all_factors": _per_factor_breakdown(inputs),
    }
