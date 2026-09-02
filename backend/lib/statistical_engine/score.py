"""Phase V2.2 — Risk score recomputation using statistical inputs.

Replaces V2.1's heuristic scoring with a model that combines four
signal groups:

  • own_building       — events on the project's own BIN
  • peer_comparison    — percentile rank vs peer set
  • active_triggers    — currently-active predictions
  • internal_compliance — V2.0 logbook + worker certifications

Each group is normalized to [0, 100] and weighted; the weighted
sum is clamped to [0, 100]. Bootstrap with 1000 samples + 10%
gaussian noise produces the 95% CI (same approach as V2.1, with
the new input set).

GROUP_WEIGHTS sum to 1.0 by design so the final score's 0..100
range is preserved without an extra rescale step. Operator can
tune via the admin endpoint in Commit 6.

Initial weight rationale:

  • own_building       (0.40) — direct evidence of risk on the
    project's actual building. Highest signal-to-noise.
  • peer_comparison    (0.25) — how the project compares to its
    peer set. Useful but less direct than own-building events.
  • active_triggers    (0.25) — forward-looking; active
    predictions imply imminent enforcement events. Equal weight
    to peer_comparison because the trigger set is already
    quality-gated (confidence ≥ 0.70, sample ≥ 20).
  • internal_compliance (0.10) — V2.0 logbook deficiencies +
    SST gaps. Lower weight because internal lapses don't always
    surface in DOB enforcement; they're a process indicator.

Returns the same `risk_scores` document shape the FE expects so
RiskScoreCircle / RiskScoreDrawer keep rendering unchanged at
the network level.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lib.cert_vocab import SST_CLASS_TYPES
from lib.worker_projection import WORKER_NO_CARD_IMAGE
from lib.server_http import ServerHttpClient
from lib.statistical_engine.baselines import (
    compare_project_to_peers,
    count_own_building_events,
)
from lib.statistical_engine.schema import (
    MODEL_VERSION,
)
from lib.statistical_engine.socrata_client import SocrataClient
from lib.statistical_engine.triggers import (
    active_predictions_for_project,
    compute_active_triggers_for_project,
    run_triggers_for_project,
)

logger = logging.getLogger(__name__)


# ── Initial group weights (operator-tunable in Commit 6) ──────────

GROUP_OWN_BUILDING        = "own_building"
GROUP_PEER_COMPARISON     = "peer_comparison"
GROUP_ACTIVE_TRIGGERS     = "active_triggers"
GROUP_INTERNAL_COMPLIANCE = "internal_compliance"

ALL_GROUPS = (
    GROUP_OWN_BUILDING,
    GROUP_PEER_COMPARISON,
    GROUP_ACTIVE_TRIGGERS,
    GROUP_INTERNAL_COMPLIANCE,
)

GROUP_WEIGHTS: Dict[str, float] = {
    GROUP_OWN_BUILDING:        0.40,
    GROUP_PEER_COMPARISON:     0.25,
    GROUP_ACTIVE_TRIGGERS:     0.25,
    GROUP_INTERNAL_COMPLIANCE: 0.10,
}

# Sanity check: weights sum to 1.0.
_W_SUM = sum(GROUP_WEIGHTS.values())
if abs(_W_SUM - 1.0) > 0.0001:
    raise AssertionError(
        f"GROUP_WEIGHTS must sum to 1.0; got {_W_SUM}",
    )


# Bootstrap parameters (kept consistent with V2.1's approach so
# the FE's CI rendering is unchanged).
BOOTSTRAP_SAMPLES = 1000
BOOTSTRAP_NOISE_SIGMA = 0.10
CONFIDENCE_INTERVAL_PCT = 95


# ── Group normalizers ─────────────────────────────────────────────


# Module-level constants — own-building coefficient weights.
# Named so that test fixtures + future calibration tuning can refer
# to them without touching every reader of the formula. Extracted
# from the inline literals at A2 (V2.3.A2 C3 Path 1).
OWN_BUILDING_WEIGHT_VIOLATIONS_30D         = 8
OWN_BUILDING_WEIGHT_VIOLATIONS_90D         = 2
OWN_BUILDING_WEIGHT_INSPECTIONS_FAILED_60D = 12
OWN_BUILDING_WEIGHT_OPEN_COMPLAINTS_30D    = 4


def _normalize_own_building(
    *,
    violations_30d: int,
    violations_90d: int,
    inspections_failed_60d: int,
    open_complaints_30d: int,
) -> float:
    """Map own-building event counts to [0, 100]. Caps tuned for
    a high-but-recoverable site (5 recent violations + 2 failed
    inspections + 5 complaints = ~75).

    Coefficients are exposed as module-level constants
    (``OWN_BUILDING_WEIGHT_*``) so test fixtures + calibration
    tuning can read them by name. A future re-tune is a one-line
    change at the constant definition; this function follows
    mechanically.
    """
    score = (
        violations_30d         * OWN_BUILDING_WEIGHT_VIOLATIONS_30D +
        violations_90d         * OWN_BUILDING_WEIGHT_VIOLATIONS_90D +
        inspections_failed_60d * OWN_BUILDING_WEIGHT_INSPECTIONS_FAILED_60D +
        open_complaints_30d    * OWN_BUILDING_WEIGHT_OPEN_COMPLAINTS_30D
    )
    return float(max(0.0, min(100.0, score)))


def _percentile_or_none(dataset_summary: Optional[Dict[str, Any]]) -> Optional[float]:
    """Extract the percentile_rank for one dataset dim of a
    ``peer_compare`` dict, returning None when the dimension is
    flagged ``available=False`` by the V2.3 schema-corrections
    hotfix. Backward-compat: a missing ``available`` field
    defaults to True (legacy caches without the flag).
    """
    if not dataset_summary:
        return None
    if dataset_summary.get("available", True) is False:
        return None
    return float(dataset_summary.get("percentile_rank", 0.0))


def _normalize_peer_comparison(
    *,
    violations_percentile: Optional[float],
    inspections_percentile: Optional[float],
    complaints_percentile: Optional[float],
) -> float:
    """Take the project's percentile rank across the available
    event types; mean. 50th = average; 99th = far worse than
    peers. Clipped to [0, 100].

    V2.3 schema-corrections hotfix: any dimension may be ``None``
    (e.g. violations, which is gated off the peer comparison
    because dob_violations has no bbl column). Average is taken
    over the measurable dimensions only — the divisor is the
    count of non-None inputs, not a hard-coded 3. This prevents
    a gated dimension from biasing the subscore (pinning to 100
    or 0 depending on the project_count).

    If ALL three dimensions are unavailable (theoretical edge
    case), returns 0.0 — distinct from the timeout / empty
    cases, which surface 0 with all-zero percentile_ranks via
    ``baselines._zero_peer_marker``. An info log line records
    the case for diagnostics.
    """
    dims = [
        p for p in (violations_percentile,
                    inspections_percentile,
                    complaints_percentile)
        if p is not None
    ]
    if not dims:
        logger.info(
            "[score] peer_subscore=0 reason=all_dimensions_unavailable",
        )
        return 0.0
    pct = sum(dims) / len(dims)
    return float(max(0.0, min(100.0, pct)))


# V2.3.A2 Amendment 1 follow-up — step function on the count of
# fired trigger kinds. Cap at 5. Values pinned by the operator spec
# (active_count → value mapping):
#   0 triggers → 0
#   1 trigger  → 30
#   2 triggers → 55
#   3 triggers → 75
#   4 triggers → 90
#   5 triggers → 100
_ACTIVE_TRIGGERS_VALUE_BY_COUNT = {
    0: 0.0,
    1: 30.0,
    2: 55.0,
    3: 75.0,
    4: 90.0,
    5: 100.0,
}


def _normalize_active_triggers(
    active_triggers: Sequence[Dict[str, Any]],
) -> float:
    """Map fired triggers to [0, 100] via the step function pinned
    by ``_ACTIVE_TRIGGERS_VALUE_BY_COUNT``. Counts the items in
    ``active_triggers`` (each dict represents one fired trigger
    kind), caps at 5, returns the corresponding value.

    Replaces the V2.3 Commit 6 confidence×diminishing-returns
    formula. The new upstream is
    ``triggers.compute_active_triggers_for_project`` (current-state
    dob_logs-derived triggers), which produces unweighted dicts of
    shape ``{"trigger_kind": <name>}`` — confidence is no longer
    part of the signal.
    """
    count = min(5, len(active_triggers or []))
    return _ACTIVE_TRIGGERS_VALUE_BY_COUNT[count]


def _normalize_internal_compliance(
    *,
    deficiency_count_30d: int,
    missing_logs_30d: int,
    sst_expiring_30d: int,
) -> float:
    """V2.0 logbook + worker-cert lapses. Caps similar to V2.1's
    weights but normalized to [0, 100]."""
    score = (
        deficiency_count_30d * 5 +
        missing_logs_30d * 3 +
        sst_expiring_30d * 1.5
    )
    return float(max(0.0, min(100.0, score)))


# ── Scoring math ──────────────────────────────────────────────────


def _score_from_group_values(group_values: Dict[str, float]) -> float:
    """Weighted sum of group values, clamped to [0, 100]."""
    s = 0.0
    for g, w in GROUP_WEIGHTS.items():
        s += w * float(group_values.get(g, 0.0))
    return float(max(0.0, min(100.0, s)))


def _bootstrap_ci(
    group_values: Dict[str, float],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    sigma: float = BOOTSTRAP_NOISE_SIGMA,
    rng: Optional[random.Random] = None,
) -> Tuple[float, float]:
    """1000-sample bootstrap with multiplicative gaussian noise on
    each group. Returns (low, high) of the 95% CI by 2.5th /
    97.5th percentile. Deterministic inputs (zero values)
    collapse the CI to (0, 0)."""
    rng = rng or random.Random(0)
    samples = max(1, int(samples))
    pct_low = (100 - CONFIDENCE_INTERVAL_PCT) / 2.0
    pct_high = 100.0 - pct_low

    bootstrap_scores: List[float] = []
    for _ in range(samples):
        perturbed: Dict[str, float] = {}
        for g, v in group_values.items():
            if v == 0.0:
                perturbed[g] = 0.0
                continue
            noise = 1.0 + rng.gauss(0.0, sigma)
            perturbed[g] = max(0.0, v * noise)
        bootstrap_scores.append(_score_from_group_values(perturbed))

    bootstrap_scores.sort()

    def _percentile(vals, p):
        if not vals:
            return 0.0
        k = max(0, min(len(vals) - 1,
                       int(round((p / 100.0) * (len(vals) - 1)))))
        return vals[k]

    return (
        float(_percentile(bootstrap_scores, pct_low)),
        float(_percentile(bootstrap_scores, pct_high)),
    )


def _factor_breakdown(
    *,
    group_values: Dict[str, float],
    own_inputs: Dict[str, Any],
    peer_compare: Dict[str, Any],
    active_predictions: Sequence[Dict[str, Any]],
    internal_inputs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return one factor row per group, with the contribution to
    the final score and a small bag of per-group raw inputs the
    drawer renders as bars / sparklines."""
    out: List[Dict[str, Any]] = []
    for group in ALL_GROUPS:
        value = group_values.get(group, 0.0)
        weight = GROUP_WEIGHTS[group]
        contribution = value * weight
        details: Dict[str, Any] = {}
        if group == GROUP_OWN_BUILDING:
            details = dict(own_inputs)
        elif group == GROUP_PEER_COMPARISON:
            # PR #14B: surface the per-dataset
            # ``lifecycle_normalized_percentile`` alongside the
            # raw ``percentile_rank``. Tests 59 + 60 pin both the
            # non-null pass-through (lifecycle math fired) and the
            # null pass-through (lifecycle skipped per T2.a). The
            # peer_set dict is passed through verbatim so PR #14B's
            # new keys (``dob_project_type``, ``geography_tier_used``,
            # ``low_confidence_flag``) reach the FE without further
            # plumbing here.
            inspections_block = peer_compare.get("inspections") or {}
            complaints_block  = peer_compare.get("complaints") or {}
            violations_block  = peer_compare.get("violations") or {}
            details = {
                "peer_set":         peer_compare.get("peer_set", {}),
                "violations_pct":   violations_block.get("percentile_rank"),
                "inspections_pct":  inspections_block.get("percentile_rank"),
                "complaints_pct":   complaints_block.get("percentile_rank"),
                "peer_sample_size": (peer_compare.get("peer_set") or {}).get("sample_size"),
                "inspections_lifecycle_normalized_percentile":
                    inspections_block.get("lifecycle_normalized_percentile"),
                "complaints_lifecycle_normalized_percentile":
                    complaints_block.get("lifecycle_normalized_percentile"),
            }
        elif group == GROUP_ACTIVE_TRIGGERS:
            details = {
                "active_count": len(active_predictions),
                "trigger_kinds": [
                    p.get("trigger_kind") for p in active_predictions
                ],
            }
        elif group == GROUP_INTERNAL_COMPLIANCE:
            details = dict(internal_inputs)
        out.append({
            "group":         group,
            "value":         value,
            "weight":        weight,
            "contribution":  contribution,
            "details":       details,
        })
    return out


# ── Async input gathering ─────────────────────────────────────────


async def gather_score_inputs(
    db,
    project: Dict[str, Any],
    *,
    socrata: SocrataClient,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pre-fetch every input the score needs.

    V2.3 signature change: ``socrata`` is a REQUIRED keyword arg
    here (the inner function expects a live client). The
    outermost entrypoint ``recompute_and_persist`` constructs one
    inline if its caller didn't supply one, and threads it down.
    """
    cur_now = now or datetime.now(timezone.utc)
    project_id = str(project.get("_id") or project.get("id") or "")

    # Own-building counts. V2.3.A2: pivots from lazy Socrata
    # queries (subset of datasets) to a single Mongo aggregate
    # against db.dob_logs (legacy-poller-populated, full DOB
    # dataset coverage). Soft-fails inside the helper so a
    # dob_logs query hiccup never blocks the score compute.
    try:
        own = await count_own_building_events(
            project_id=project_id,
            db=db,
            now=cur_now,
        )
    except Exception as e:
        logger.warning(
            f"[score] count_own_building_events failed: {e!r}",
        )
        own = {
            "violations_30d":         0,
            "violations_90d":         0,
            "inspections_failed_60d": 0,
            "open_complaints_30d":    0,
        }

    # Peer comparison.
    try:
        peer_compare = await compare_project_to_peers(
            db, project, socrata=socrata, now=cur_now,
        )
    except Exception as e:
        logger.warning(
            f"[score] compare_project_to_peers failed: {e!r}",
        )
        peer_compare = {"peer_set": {"sample_size": 0}}

    # Active triggers. V2.3.A2 Amendment 1 follow-up: pivots from
    # the V2.3-Commit-6 ``active_predictions_for_project`` reader
    # (which pulled from the predicted_events collection — empty in
    # production for current projects) to the current-state
    # dob_logs-derived ``compute_active_triggers_for_project``
    # (5 trigger kinds: active_swo, recent_swo_60d,
    # escalating_violations, repeat_violator_90d,
    # open_severe_complaint). Soft-fails inside the helper so a
    # dob_logs query hiccup never blocks the score compute.
    active_predictions = []
    if project_id:
        try:
            active_predictions = await compute_active_triggers_for_project(
                db, project_id, now=cur_now,
            )
        except Exception as e:
            logger.warning(
                f"[score] compute_active_triggers_for_project failed: {e!r}",
            )

    # Internal compliance — V2.0 logbook deficiencies + missing
    # logs + SST expirations soon. We re-use the V2.0 schema
    # constants directly to avoid drift.
    internal = {
        "deficiency_count_30d":     0,
        "missing_logs_30d":         0,
        "sst_expiring_30d":         0,
    }
    if project_id:
        cutoff_30_str = (cur_now - timedelta(days=30)).strftime("%Y-%m-%d")
        try:
            internal["deficiency_count_30d"] = (
                await db.logbook_entries.count_documents({
                    "project_id": project_id,
                    "category": "deficiency",
                    "entry_date": {"$gte": cutoff_30_str},
                })
            )
            internal["missing_logs_30d"] = (
                await db.logbook_entries.count_documents({
                    "project_id": project_id,
                    "category": "daily_log",
                    "status": "missing",
                    "entry_date": {"$gte": cutoff_30_str},
                })
            )
        except Exception as e:
            logger.warning(f"[score] logbook count failed: {e!r}")
        # SST: count workers in the company whose certs expire
        # in next 30 days.
        company_id = project.get("company_id")
        if company_id:
            try:
                cutoff_future = (cur_now + timedelta(days=30)).date()
                # Every worker in the company, to count expiring SST certs.
                # The loop below reads `certifications` and nothing else, so
                # the base64 card photo on each document is projected out.
                cursor = db.workers.find(
                    {"company_id": company_id}, WORKER_NO_CARD_IMAGE,
                )
                async for w in cursor:
                    certs = w.get("certifications") or []
                    for c in certs:
                        if not isinstance(c, dict):
                            continue
                        # THE COPY IS GONE. This was a hardcoded
                        # ("SST_FULL", "SST_LIMITED", "SST_SUPERVISOR") --
                        # three members against the canonical four, dropping
                        # SST_TEMPORARY. A temporary card is the SHORTEST-LIVED
                        # SST credential, so it is the one most likely to lapse
                        # unnoticed, which made this the worst place to drop it:
                        # the expiring-soon count silently excluded exactly the
                        # cards most likely to be expiring soon.
                        if c.get("type") not in SST_CLASS_TYPES:
                            continue
                        exp = c.get("expiration_date")
                        if not exp:
                            continue
                        try:
                            if isinstance(exp, str):
                                exp_d = datetime.strptime(
                                    exp[:10], "%Y-%m-%d",
                                ).date()
                            elif isinstance(exp, datetime):
                                exp_d = exp.date()
                            else:
                                continue
                        except ValueError:
                            continue
                        if cur_now.date() <= exp_d <= cutoff_future:
                            internal["sst_expiring_30d"] += 1
                            break
            except Exception as e:
                logger.warning(f"[score] sst count failed: {e!r}")

    return {
        "now":                cur_now,
        "own":                own,
        "peer_compare":       peer_compare,
        "active_predictions": active_predictions,
        "internal":           internal,
    }


# ── End-to-end scorer ─────────────────────────────────────────────


def _scores_from_inputs(
    inputs: Dict[str, Any],
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Pure scoring step (no DB). Returns (group_values,
    aux_for_breakdown).
    """
    own = inputs["own"]
    peer = inputs["peer_compare"] or {}
    active = inputs["active_predictions"] or []
    internal = inputs["internal"]

    own_value = _normalize_own_building(
        violations_30d=own.get("violations_30d", 0),
        violations_90d=own.get("violations_90d", 0),
        inspections_failed_60d=own.get("inspections_failed_60d", 0),
        open_complaints_30d=own.get("open_complaints_30d", 0),
    )
    peer_value = _normalize_peer_comparison(
        violations_percentile=_percentile_or_none(peer.get("violations")),
        inspections_percentile=_percentile_or_none(peer.get("inspections")),
        complaints_percentile=_percentile_or_none(peer.get("complaints")),
    )
    triggers_value = _normalize_active_triggers(active)
    internal_value = _normalize_internal_compliance(
        deficiency_count_30d=internal.get("deficiency_count_30d", 0),
        missing_logs_30d=internal.get("missing_logs_30d", 0),
        sst_expiring_30d=internal.get("sst_expiring_30d", 0),
    )

    return (
        {
            GROUP_OWN_BUILDING:        own_value,
            GROUP_PEER_COMPARISON:     peer_value,
            GROUP_ACTIVE_TRIGGERS:     triggers_value,
            GROUP_INTERNAL_COMPLIANCE: internal_value,
        },
        {
            "own_inputs":         own,
            "peer_compare":       peer,
            "active_predictions": active,
            "internal_inputs":    internal,
        },
    )


def calculate_risk_score(
    inputs: Dict[str, Any],
    *,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Pure scoring pipeline: inputs → group values → score + CI
    + factor breakdown. Async-input-gathering is in
    `gather_score_inputs`; this function does the math only."""
    group_values, aux = _scores_from_inputs(inputs)
    score = _score_from_group_values(group_values)
    low, high = _bootstrap_ci(group_values, rng=rng)
    factors = _factor_breakdown(
        group_values=group_values,
        own_inputs=aux["own_inputs"],
        peer_compare=aux["peer_compare"],
        active_predictions=aux["active_predictions"],
        internal_inputs=aux["internal_inputs"],
    )
    return {
        "score":               score,
        "confidence_low":      low,
        "confidence_high":     high,
        "group_values":        group_values,
        "contributing_factors": factors,
    }


# ── Persist + recompute ───────────────────────────────────────────


async def recompute_and_persist(
    db,
    project: Dict[str, Any],
    *,
    socrata: Optional[SocrataClient] = None,
    now: Optional[datetime] = None,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Full pipeline: gather inputs, calculate score, run all 8
    triggers (so freshly-fired predictions feed the next read),
    then persist a row to risk_scores. Returns the inserted doc.

    V2.3 signature change: accepts an optional ``socrata``
    SocrataClient. When None, constructs one inline backed by a
    fresh ServerHttpClient that lives for the duration of this
    call. That single client + connection pool is threaded into
    triggers + peer comparison + own-building counts so the whole
    recompute pipeline reuses one HTTP connection where possible
    (typically 7-10 Socrata calls per recompute on a cache miss,
    1-2 on a cache hit).

    server.py:calculate_project_risk_score passes ``project``
    without a SocrataClient — Commit 3 keeps that endpoint
    untouched by handling client construction here. Commit 4 may
    eventually wire a shared application-level client through
    request scope.
    """
    cur_now = now or datetime.now(timezone.utc)
    project_id = str(project.get("_id") or project.get("id") or "")
    if not project_id:
        return {}

    inline_http: Optional[ServerHttpClient] = None
    if socrata is None:
        inline_http = ServerHttpClient(timeout=10.0)
        await inline_http.__aenter__()
        socrata = SocrataClient(inline_http)
    try:
        # Fire triggers first — they may persist new
        # predicted_events rows that other UI surfaces read.
        # V2.3.A2 Amendment 1 follow-up: score input gathering
        # no longer reads predicted_events; it reads current-
        # state triggers from dob_logs via
        # compute_active_triggers_for_project. The
        # run_triggers_for_project call still runs to maintain
        # the predicted_events pipeline for non-score consumers.
        try:
            await run_triggers_for_project(
                db, project, socrata=socrata, now=cur_now,
            )
        except Exception as e:
            logger.warning(f"[score] run_triggers_for_project: {e!r}")

        inputs = await gather_score_inputs(
            db, project, socrata=socrata, now=cur_now,
        )
        result = calculate_risk_score(inputs, rng=rng)

        doc = {
            "project_id":           project_id,
            "company_id":           str(project.get("company_id") or ""),
            "calculated_at":        cur_now,
            "score":                result["score"],
            "confidence_low":       result["confidence_low"],
            "confidence_high":      result["confidence_high"],
            "contributing_factors": result["contributing_factors"],
            "group_values":         result["group_values"],
            "model_version":        MODEL_VERSION,
            "weights_snapshot":     dict(GROUP_WEIGHTS),
        }
        res = await db.risk_scores.insert_one(doc)
        doc["_id"] = res.inserted_id
        return doc
    finally:
        if inline_http is not None:
            await inline_http.__aexit__(None, None, None)
