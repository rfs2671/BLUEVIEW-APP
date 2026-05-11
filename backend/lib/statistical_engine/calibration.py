"""Phase V2.2 Commit 6 — calibration loop.

Outcome tracking + per-trigger calibration math + admin-tunable
priors. Auto-update of priors is deliberately NOT wired —
operator reads stats, manually edits weights via the admin
endpoint. Same human-in-loop discipline as V2.1's calibration
framework.

Daily cron (3 AM ET):

  attribute_outcomes_for_expired_predictions(db, now=...)

  Walks every predicted_events row whose expires_at has passed
  and outcome_status is 'active'. For each, scans the project's
  source events in [predicted_at, expires_at) for an event of
  the trigger's "expected" kind. Records the outcome
  (hit / miss / expired-without-data) into prediction_outcomes
  and flips outcome_status on the original prediction.

Calibration query (admin endpoint, on demand):

  compute_calibration_stats(db, model_version=None) →
    {model_version, sample_size, by_trigger:
      {trigger_kind: {n, hits, misses, accuracy,
                      false_positive_rate, false_negative_rate}}}

Weight tuning (admin endpoint, manual):

  set_trigger_prior(db, trigger_kind, prior) — persists an
  operator override into a small `trigger_priors` collection.
  triggers.py reads from it (with the static fallback) so a
  prior change takes effect on the next score recompute.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from lib.server_http import ServerHttpClient
from lib.statistical_engine.schema import (
    PREDICTED_EVENTS_COLLECTION,
    PREDICTION_OUTCOMES_COLLECTION,
    MODEL_VERSION,
)
from lib.statistical_engine.socrata_client import (
    DATASET_COMPLAINTS_311,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_VIOLATIONS,
    SocrataClient,
    SocrataQueryError,
)
from lib.statistical_engine.triggers import (
    ALL_TRIGGER_KINDS,
    TRIGGER_311_AT_BIN,
    TRIGGER_311_INSPECTION_PREDICTION,
    TRIGGER_311_NEIGHBOR,
    TRIGGER_BOROUGH_SWEEP,
    TRIGGER_CSC_PERIODIC,
    TRIGGER_CSE_FOLLOWUP,
    TRIGGER_CURE_DEADLINE_REINSPECT,
    TRIGGER_NEIGHBOR_SWO,
    TRIGGER_SSMR_SHED_AGING,
)

logger = logging.getLogger(__name__)


# ── Outcome statuses ──────────────────────────────────────────────

OUTCOME_HIT  = "hit"
OUTCOME_MISS = "miss"
OUTCOME_EXPIRED_NO_DATA = "expired_no_data"

# Per-trigger expected event mapping. When a prediction expires,
# we query the configured Socrata dataset for any matching event
# in the [predicted_at, expires_at] window for the project's BIN.
# Hit → at least one event found; miss → none.
#
# Each entry is (dataset_id, date_column_name). The date column
# differs per dataset because Socrata's source columns aren't
# normalized — V2.2 canonicalized them to ``occurred_date`` at
# ingest time, V2.3 references each source's actual column.

TRIGGER_EVIDENCE_DATASET = {
    TRIGGER_311_AT_BIN:              (DATASET_COMPLAINTS_311,  "created_date"),
    TRIGGER_311_NEIGHBOR:            (DATASET_COMPLAINTS_311,  "created_date"),
    TRIGGER_BOROUGH_SWEEP:           (DATASET_DOB_INSPECTIONS, "inspection_date"),
    TRIGGER_CSC_PERIODIC:            (DATASET_DOB_INSPECTIONS, "inspection_date"),
    TRIGGER_CSE_FOLLOWUP:            (DATASET_DOB_VIOLATIONS,  "issue_date"),
    TRIGGER_CURE_DEADLINE_REINSPECT: (DATASET_DOB_INSPECTIONS, "inspection_date"),
    TRIGGER_NEIGHBOR_SWO:            (DATASET_DOB_VIOLATIONS,  "issue_date"),
    TRIGGER_SSMR_SHED_AGING:         (DATASET_DOB_INSPECTIONS, "inspection_date"),
    # V2.3 Commit 6 — event-driven 311 inspection prediction.
    # Evidence is a DOB inspection at the project's BIN within
    # the prediction window. Predictions module has its own
    # resolution sweep (sweep_prediction_resolutions); this
    # entry exists so the calibration framework can also see
    # this trigger kind if it's later re-wired to a daily cron.
    TRIGGER_311_INSPECTION_PREDICTION: (DATASET_DOB_INSPECTIONS, "inspection_date"),
}


# ── Outcome attribution ───────────────────────────────────────────


def _soql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _iso_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


async def _first_event_in_window(
    socrata: SocrataClient,
    *,
    dataset_id: str,
    date_field: str,
    bin_: Optional[str],
    since: datetime,
    until: datetime,
) -> Optional[Dict[str, Any]]:
    """Return the first matching event for the BIN in [since, until]
    via Socrata, or None. Used by outcome attribution to find a
    matching enforcement event after a prediction expires."""
    if not bin_:
        return None
    try:
        rows = await socrata.query(
            dataset_id,
            where=(
                f"bin = {_soql_quote(bin_)} AND "
                f"{date_field} >= {_soql_quote(_iso_z(since))} AND "
                f"{date_field} <= {_soql_quote(_iso_z(until))}"
            ),
            order=f"{date_field} ASC",
            limit=1,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[calibration] event search for %s failed: %r",
            dataset_id, e,
        )
        return None
    if not rows:
        return None
    return rows[0]


async def _resolve_project_bin(db, project_id: str) -> Optional[str]:
    """Look up the project's BIN for outcome attribution."""
    try:
        from bson import ObjectId  # type: ignore
        proj = await db.projects.find_one({"_id": ObjectId(project_id)})
    except Exception:
        proj = None
    if proj is None:
        proj = await db.projects.find_one({"_id": project_id})
    if proj is None:
        return None
    return proj.get("nyc_bin") or proj.get("bin")


def _parse_socrata_dt(value: Any) -> Optional[datetime]:
    """Parse a Socrata floating-timestamp into a UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        s = value.rstrip("Z")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


async def attribute_outcome_for_prediction(
    db,
    prediction: Dict[str, Any],
    *,
    socrata: SocrataClient,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Decide whether a single prediction was a hit or miss.
    Writes one row to prediction_outcomes and flips
    outcome_status on the original prediction.

    V2.3 signature change: ``socrata`` is a REQUIRED keyword arg
    here (inner function). The outermost batch entrypoint
    ``attribute_outcomes_for_expired_predictions`` accepts an
    optional ``socrata`` and constructs one inline if absent.

    Returns the outcome row (or None on degenerate input)."""
    if not prediction:
        return None
    cur_now = now or datetime.now(timezone.utc)
    project_id = prediction.get("project_id")
    trigger_kind = prediction.get("trigger_kind")
    predicted_at = prediction.get("predicted_at")
    expires_at = prediction.get("expires_at")
    if not project_id or not trigger_kind or not predicted_at \
            or not expires_at:
        return None
    bin_ = await _resolve_project_bin(db, project_id)
    dataset_spec = TRIGGER_EVIDENCE_DATASET.get(trigger_kind)
    if dataset_spec is None:
        return None
    dataset_id, date_field = dataset_spec

    if bin_ is None:
        outcome_status = OUTCOME_EXPIRED_NO_DATA
        actual_at = None
    else:
        first_match = await _first_event_in_window(
            socrata,
            dataset_id=dataset_id,
            date_field=date_field,
            bin_=bin_,
            since=predicted_at,
            until=expires_at,
        )
        if first_match is None:
            outcome_status = OUTCOME_MISS
            actual_at = None
        else:
            outcome_status = OUTCOME_HIT
            actual_at = (
                _parse_socrata_dt(first_match.get(date_field))
                or _parse_socrata_dt(first_match.get("occurred_date"))
            )

    outcome_doc = {
        "prediction_id":   prediction.get("_id"),
        "project_id":      project_id,
        "trigger_kind":    trigger_kind,
        "predicted_at":    predicted_at,
        "expired_at":      expires_at,
        "actual_event_at": actual_at,
        "outcome":         outcome_status,
        "hit_window_days": (
            (actual_at - predicted_at).days
            if actual_at is not None
            else None
        ),
        "attributed_at":   cur_now,
        "model_version":   MODEL_VERSION,
    }
    res = await db[PREDICTION_OUTCOMES_COLLECTION].insert_one(outcome_doc)
    outcome_doc["_id"] = res.inserted_id

    # Flip the original prediction's outcome_status so the
    # daily sweep doesn't reprocess it.
    if prediction.get("_id"):
        await db[PREDICTED_EVENTS_COLLECTION].update_one(
            {"_id": prediction["_id"]},
            {"$set": {"outcome_status": outcome_status}},
        )
    return outcome_doc


async def attribute_outcomes_for_expired_predictions(
    db,
    *,
    socrata: Optional[SocrataClient] = None,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Daily cron entry point. Walks every prediction whose
    expires_at <= now and outcome_status == 'active', attributes
    each, returns a summary.

    V2.3 signature change: accepts an optional ``socrata``
    SocrataClient. When None, constructs one inline backed by a
    fresh ServerHttpClient for the duration of the sweep. The
    same client is reused across every prediction's evidence
    lookup so the connection pool warms once per sweep.

    NOTE: V2.3 Commit 1 removed the APScheduler tick that
    invoked this. A future commit will rewire a daily cron once
    the surrounding lazy-query infrastructure is settled. The
    function itself is otherwise ready to call.
    """
    cur_now = now or datetime.now(timezone.utc)
    summary = {"processed": 0, "hits": 0, "misses": 0, "expired_no_data": 0,
               "errors": 0}

    inline_http: Optional[ServerHttpClient] = None
    if socrata is None:
        inline_http = ServerHttpClient(timeout=10.0)
        await inline_http.__aenter__()
        socrata = SocrataClient(inline_http)
    try:
        cursor = db[PREDICTED_EVENTS_COLLECTION].find({
            "expires_at": {"$lte": cur_now},
            "outcome_status": "active",
        })
        async for prediction in cursor:
            summary["processed"] += 1
            try:
                outcome = await attribute_outcome_for_prediction(
                    db, prediction, socrata=socrata, now=cur_now,
                )
                if outcome is None:
                    summary["errors"] += 1
                    continue
                if outcome["outcome"] == OUTCOME_HIT:
                    summary["hits"] += 1
                elif outcome["outcome"] == OUTCOME_MISS:
                    summary["misses"] += 1
                else:
                    summary["expired_no_data"] += 1
            except Exception as e:
                summary["errors"] += 1
                logger.warning(f"[calibration] attribute failed: {e!r}")
    finally:
        if inline_http is not None:
            await inline_http.__aexit__(None, None, None)

    logger.info(f"[calibration] daily attribution: {summary}")
    return summary


# ── Stats aggregation ─────────────────────────────────────────────


def _safe_div(num: float, denom: float) -> float:
    return num / denom if denom else 0.0


async def compute_calibration_stats(
    db,
    *,
    model_version: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Walk prediction_outcomes for the requested model_version
    and compute per-trigger accuracy + false-positive-rate +
    false-negative-rate. Returns a dict the admin endpoint
    renders.

      {
        model_version, sample_size, evaluated_at,
        by_trigger: {trigger_kind: {n, hits, misses, expired_no_data,
                                    accuracy,
                                    false_positive_rate,
                                    false_negative_rate}},
        overall: {n, hits, misses, accuracy, ...},
      }
    """
    cur_now = now or datetime.now(timezone.utc)
    target_version = model_version or MODEL_VERSION
    by_trigger: Dict[str, Dict[str, int]] = {
        kind: {"n": 0, "hits": 0, "misses": 0, "expired_no_data": 0}
        for kind in ALL_TRIGGER_KINDS
    }
    cursor = db[PREDICTION_OUTCOMES_COLLECTION].find({
        "model_version": target_version,
    })
    total_n = 0
    total_hits = 0
    total_misses = 0
    total_expired = 0
    async for outcome in cursor:
        kind = outcome.get("trigger_kind") or ""
        if kind not in by_trigger:
            continue
        by_trigger[kind]["n"] += 1
        total_n += 1
        if outcome.get("outcome") == OUTCOME_HIT:
            by_trigger[kind]["hits"] += 1
            total_hits += 1
        elif outcome.get("outcome") == OUTCOME_MISS:
            by_trigger[kind]["misses"] += 1
            total_misses += 1
        else:
            by_trigger[kind]["expired_no_data"] += 1
            total_expired += 1

    # Compute per-trigger derived metrics.
    for kind, stats in by_trigger.items():
        n = stats["n"]
        hits = stats["hits"]
        misses = stats["misses"]
        # Accuracy: hits / (hits + misses). Excludes
        # expired_no_data because we couldn't measure those.
        decided = hits + misses
        stats["accuracy"] = _safe_div(hits, decided)
        # False-positive-rate: misses / decided. (Among predictions
        # we surfaced to the operator, what fraction were wrong?)
        stats["false_positive_rate"] = _safe_div(misses, decided)
        # False-negative-rate: we don't directly observe FN here
        # because we only track predictions the model surfaced.
        # Reported as 0 with a documented caveat in the docs.
        stats["false_negative_rate"] = 0.0

    overall_decided = total_hits + total_misses
    overall = {
        "n": total_n,
        "hits": total_hits,
        "misses": total_misses,
        "expired_no_data": total_expired,
        "accuracy":            _safe_div(total_hits, overall_decided),
        "false_positive_rate": _safe_div(total_misses, overall_decided),
    }

    return {
        "model_version": target_version,
        "evaluated_at":  cur_now,
        "sample_size":   total_n,
        "by_trigger":    by_trigger,
        "overall":       overall,
    }


# ── Manual weight / prior tuning ──────────────────────────────────
#
# Operator-tunable priors live in their own tiny collection so a
# new prior takes effect without a code deploy. triggers.py's
# `_historical_match_rate_for_trigger` falls back to its static
# default when no override exists.

TRIGGER_PRIORS_COLLECTION = "trigger_priors"


async def set_trigger_prior(
    db,
    *,
    trigger_kind: str,
    prior: float,
    set_by_user_id: Optional[str] = None,
    note: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Persist an operator override for one trigger's prior. Used
    by the admin weight-tuner endpoint. No auto-update — the
    operator reads calibration stats, decides, edits."""
    if trigger_kind not in ALL_TRIGGER_KINDS:
        raise ValueError(f"unknown trigger_kind: {trigger_kind}")
    if not (0.0 <= prior <= 1.0):
        raise ValueError(f"prior must be in [0, 1]; got {prior}")
    cur_now = now or datetime.now(timezone.utc)
    doc = {
        "trigger_kind":   trigger_kind,
        "prior":          float(prior),
        "set_by_user_id": set_by_user_id or "",
        "note":           note or "",
        "updated_at":     cur_now,
    }
    await db[TRIGGER_PRIORS_COLLECTION].update_one(
        {"trigger_kind": trigger_kind},
        {"$set": doc},
        upsert=True,
    )
    return doc


async def get_trigger_prior(
    db, trigger_kind: str,
) -> Optional[float]:
    """Read an operator-set prior. Returns None if no override
    exists (caller falls back to static default)."""
    doc = await db[TRIGGER_PRIORS_COLLECTION].find_one(
        {"trigger_kind": trigger_kind},
    )
    if doc is None:
        return None
    return doc.get("prior")
