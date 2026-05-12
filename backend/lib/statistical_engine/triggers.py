"""Phase V2.2 — 8 trigger detectors + event predictor.

Each trigger is a pure detector (no DB writes). Given the
project + recent NYC source data + peer baselines, returns
either:

    None                                # trigger did not fire
    {                                   # trigger fired
      "trigger_kind":             str,
      "confidence":               float (0..1),
      "peer_sample_size":         int,
      "historical_match_rate":    float (0..1),
      "days_window_min":          int,
      "days_window_max":          int,
      "input_snapshot":           dict,
    }

Sample-size + confidence gating happens at write time
(`upsert_prediction`) per spec: surface predictions only with
sample ≥ 20 AND confidence ≥ 0.70.

The 8 triggers (commit-spec ordering):

  1. trigger_311_at_bin             — fresh 311 at the project's BIN
  2. trigger_311_neighbor           — fresh 311 at neighboring BIN
                                      (same BBL block component)
  3. trigger_csc_periodic           — CSC inspection due based on
                                      project class + days since
                                      last CSC visit
  4. trigger_borough_sweep          — inspection density 2σ above
                                      90-day rolling mean for borough
  5. trigger_neighbor_swo           — SWO on neighboring construction
                                      site (BBL-proximity, no PostGIS)
  6. trigger_cse_followup           — CSE follow-up after prior
                                      violation nearby
  7. trigger_cure_deadline_reinspection — re-inspection on cure
                                      deadline of existing violation
  8. trigger_ssmr_shed_aging        — SSMR Unit visit when shed > 90 days

run_triggers_for_project(db, project) is the orchestrator —
walks all 8, gathers historical match rates from baselines,
upserts predictions that clear the gate.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from lib.server_http import ServerHttpClient
from lib.statistical_engine.schema import (
    MIN_CONFIDENCE_THRESHOLD,
    MIN_PEER_SAMPLE_SIZE,
    PREDICTED_EVENTS_COLLECTION,
)
from lib.statistical_engine.socrata_client import (
    DATASET_COMPLAINTS_311,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_VIOLATIONS,
    SocrataClient,
    SocrataQueryError,
)
from lib.statistical_engine.utils import normalize_bbl

logger = logging.getLogger(__name__)


# ── Trigger kind constants ────────────────────────────────────────

TRIGGER_311_AT_BIN              = "311_at_bin"
TRIGGER_311_NEIGHBOR            = "311_neighbor"
TRIGGER_CSC_PERIODIC            = "csc_periodic"
TRIGGER_BOROUGH_SWEEP           = "borough_sweep"
TRIGGER_NEIGHBOR_SWO            = "neighbor_swo"
TRIGGER_CSE_FOLLOWUP            = "cse_followup"
TRIGGER_CURE_DEADLINE_REINSPECT = "cure_deadline_reinspection"
TRIGGER_SSMR_SHED_AGING         = "ssmr_shed_aging"
# V2.3 Commit 6 — event-driven predictive surfacing. Distinct
# from TRIGGER_311_AT_BIN (which is score-driven, fires inside
# recompute_and_persist). This one fires from the 311 poll
# hook when a fresh complaint lands on a tracked BIN and the
# similar-case correlation passes the confidence threshold.
TRIGGER_311_INSPECTION_PREDICTION = "311_inspection_prediction"

ALL_TRIGGER_KINDS = (
    TRIGGER_311_AT_BIN,
    TRIGGER_311_NEIGHBOR,
    TRIGGER_CSC_PERIODIC,
    TRIGGER_BOROUGH_SWEEP,
    TRIGGER_NEIGHBOR_SWO,
    TRIGGER_CSE_FOLLOWUP,
    TRIGGER_CURE_DEADLINE_REINSPECT,
    TRIGGER_SSMR_SHED_AGING,
    TRIGGER_311_INSPECTION_PREDICTION,
)


# ── Default windows (operator-tunable in Commit 6 admin UI) ───────
#
# Each trigger has a "look-ahead" window — how many days into the
# future the predicted event might occur. Tuned from MR.14 sample
# observations + DOB enforcement-cycle norms. Operator can edit
# per-trigger via the admin endpoint that lands in Commit 6.

DEFAULT_WINDOWS = {
    TRIGGER_311_AT_BIN:              (1,  14),
    TRIGGER_311_NEIGHBOR:            (3,  21),
    TRIGGER_CSC_PERIODIC:            (1,  30),
    TRIGGER_BOROUGH_SWEEP:           (1,  10),
    TRIGGER_NEIGHBOR_SWO:            (1,  14),
    TRIGGER_CSE_FOLLOWUP:            (3,  30),
    TRIGGER_CURE_DEADLINE_REINSPECT: (0,   7),
    TRIGGER_SSMR_SHED_AGING:         (1,  21),
    # V2.3 Commit 6 — predictions ship with a fixed 7-day window
    # (matches PREDICTION_INSPECTION_WINDOW_DAYS in predictions.py).
    # days_window_min=0 because the predicted inspection might
    # land same-day if the complaint was registered overnight.
    TRIGGER_311_INSPECTION_PREDICTION: (0,   7),
}


# ── BBL helpers ───────────────────────────────────────────────────


def _bbl_block(bbl: Any) -> Optional[str]:
    """Return the borough+block prefix of a BBL (first 6 chars).
    NYC BBLs are 10 chars: 1 borough + 5 block + 4 lot. Two BBLs
    on the same block share the first 6 chars."""
    if not bbl or not isinstance(bbl, str) or len(bbl) < 6:
        return None
    return bbl[:6]


# ── Trigger 1: 311 at BIN ─────────────────────────────────────────


def trigger_311_at_bin(
    project: Dict[str, Any],
    *,
    recent_311_at_bin: Sequence[Dict[str, Any]],
    historical_match_rate: float,
    peer_sample_size: int,
) -> Optional[Dict[str, Any]]:
    """Fired when a 311 complaint exists at the project's BIN
    within the past 24 hours. Confidence comes from peer
    historical: how often does a same-BIN 311 within 24h
    correlate with a violation in the next 14 days?"""
    if not recent_311_at_bin:
        return None
    lo, hi = DEFAULT_WINDOWS[TRIGGER_311_AT_BIN]
    return {
        "trigger_kind":          TRIGGER_311_AT_BIN,
        "confidence":            float(historical_match_rate),
        "peer_sample_size":      int(peer_sample_size),
        "historical_match_rate": float(historical_match_rate),
        "days_window_min":       lo,
        "days_window_max":       hi,
        "input_snapshot": {
            "recent_311_count": len(recent_311_at_bin),
            "latest_311_id": (recent_311_at_bin[0] or {}).get("record_id"),
        },
    }


# ── Trigger 2: 311 at neighboring BIN ─────────────────────────────


def trigger_311_neighbor(
    project: Dict[str, Any],
    *,
    recent_311_neighbor: Sequence[Dict[str, Any]],
    historical_match_rate: float,
    peer_sample_size: int,
) -> Optional[Dict[str, Any]]:
    if not recent_311_neighbor:
        return None
    lo, hi = DEFAULT_WINDOWS[TRIGGER_311_NEIGHBOR]
    return {
        "trigger_kind":          TRIGGER_311_NEIGHBOR,
        "confidence":            float(historical_match_rate),
        "peer_sample_size":      int(peer_sample_size),
        "historical_match_rate": float(historical_match_rate),
        "days_window_min":       lo,
        "days_window_max":       hi,
        "input_snapshot": {
            "neighbor_311_count": len(recent_311_neighbor),
        },
    }


# ── Trigger 3: CSC periodic ───────────────────────────────────────


def trigger_csc_periodic(
    project: Dict[str, Any],
    *,
    days_since_last_csc: Optional[int],
    historical_match_rate: float,
    peer_sample_size: int,
    csc_cycle_days: int = 90,
) -> Optional[Dict[str, Any]]:
    """Fired when days_since_last_csc >= csc_cycle_days. Major-A /
    Major-B sites have shorter cycles than regular; the caller
    is responsible for picking csc_cycle_days appropriately."""
    if days_since_last_csc is None:
        return None
    if days_since_last_csc < csc_cycle_days:
        return None
    lo, hi = DEFAULT_WINDOWS[TRIGGER_CSC_PERIODIC]
    return {
        "trigger_kind":          TRIGGER_CSC_PERIODIC,
        "confidence":            float(historical_match_rate),
        "peer_sample_size":      int(peer_sample_size),
        "historical_match_rate": float(historical_match_rate),
        "days_window_min":       lo,
        "days_window_max":       hi,
        "input_snapshot": {
            "days_since_last_csc": days_since_last_csc,
            "csc_cycle_days":      csc_cycle_days,
        },
    }


# ── Trigger 4: borough sweep ──────────────────────────────────────


def trigger_borough_sweep(
    project: Dict[str, Any],
    *,
    borough_inspection_counts_90d: Sequence[int],
    last_7d_count: int,
    historical_match_rate: float,
    peer_sample_size: int,
    sigma_threshold: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """Fired when borough-wide inspection density in the past 7
    days is `sigma_threshold` standard deviations above the
    rolling 90-day mean. Caller passes the per-day inspection
    count history (~90 ints)."""
    if len(borough_inspection_counts_90d) < 14:
        return None
    mean = statistics.mean(borough_inspection_counts_90d)
    try:
        stdev = statistics.stdev(borough_inspection_counts_90d)
    except statistics.StatisticsError:
        return None
    if stdev <= 0:
        return None
    z = (last_7d_count - mean) / stdev
    if z < sigma_threshold:
        return None
    lo, hi = DEFAULT_WINDOWS[TRIGGER_BOROUGH_SWEEP]
    return {
        "trigger_kind":          TRIGGER_BOROUGH_SWEEP,
        "confidence":            float(historical_match_rate),
        "peer_sample_size":      int(peer_sample_size),
        "historical_match_rate": float(historical_match_rate),
        "days_window_min":       lo,
        "days_window_max":       hi,
        "input_snapshot": {
            "borough_z_score":      z,
            "last_7d_count":        last_7d_count,
            "rolling_mean_90d":     mean,
            "rolling_stdev_90d":    stdev,
            "sigma_threshold":      sigma_threshold,
        },
    }


# ── Trigger 5: neighbor SWO ───────────────────────────────────────


def trigger_neighbor_swo(
    project: Dict[str, Any],
    *,
    neighbor_swo_count_30d: int,
    historical_match_rate: float,
    peer_sample_size: int,
) -> Optional[Dict[str, Any]]:
    """Fired when at least one Stop Work Order has been issued on
    a neighboring construction site (same BBL block) in the past
    30 days. Proxy for a borough-level enforcement focus."""
    if neighbor_swo_count_30d <= 0:
        return None
    lo, hi = DEFAULT_WINDOWS[TRIGGER_NEIGHBOR_SWO]
    return {
        "trigger_kind":          TRIGGER_NEIGHBOR_SWO,
        "confidence":            float(historical_match_rate),
        "peer_sample_size":      int(peer_sample_size),
        "historical_match_rate": float(historical_match_rate),
        "days_window_min":       lo,
        "days_window_max":       hi,
        "input_snapshot": {
            "neighbor_swo_count_30d": neighbor_swo_count_30d,
        },
    }


# ── Trigger 6: CSE follow-up ──────────────────────────────────────


def trigger_cse_followup(
    project: Dict[str, Any],
    *,
    nearby_violations_60d: int,
    historical_match_rate: float,
    peer_sample_size: int,
) -> Optional[Dict[str, Any]]:
    """Fired when nearby (BBL block) violations in past 60 days
    suggest a CSE (Construction Safety Enforcement) follow-up
    is likely on the project's own site."""
    if nearby_violations_60d <= 0:
        return None
    lo, hi = DEFAULT_WINDOWS[TRIGGER_CSE_FOLLOWUP]
    return {
        "trigger_kind":          TRIGGER_CSE_FOLLOWUP,
        "confidence":            float(historical_match_rate),
        "peer_sample_size":      int(peer_sample_size),
        "historical_match_rate": float(historical_match_rate),
        "days_window_min":       lo,
        "days_window_max":       hi,
        "input_snapshot": {
            "nearby_violations_60d": nearby_violations_60d,
        },
    }


# ── Trigger 7: cure deadline re-inspection ────────────────────────


def trigger_cure_deadline_reinspection(
    project: Dict[str, Any],
    *,
    open_violations_with_cure: Sequence[Dict[str, Any]],
    historical_match_rate: float,
    peer_sample_size: int,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Fired when an open violation's cure deadline is within
    the next 7 days — DOB typically re-inspects on/around that
    date."""
    cur_now = now or datetime.now(timezone.utc)
    soon = cur_now + timedelta(days=7)
    matching = []
    for v in (open_violations_with_cure or []):
        cure = v.get("cure_deadline")
        if not isinstance(cure, datetime):
            continue
        if cur_now <= cure <= soon:
            matching.append(v)
    if not matching:
        return None
    lo, hi = DEFAULT_WINDOWS[TRIGGER_CURE_DEADLINE_REINSPECT]
    return {
        "trigger_kind":          TRIGGER_CURE_DEADLINE_REINSPECT,
        "confidence":            float(historical_match_rate),
        "peer_sample_size":      int(peer_sample_size),
        "historical_match_rate": float(historical_match_rate),
        "days_window_min":       lo,
        "days_window_max":       hi,
        "input_snapshot": {
            "violations_with_imminent_cure": len(matching),
        },
    }


# ── Trigger 8: SSMR shed aging ────────────────────────────────────


def trigger_ssmr_shed_aging(
    project: Dict[str, Any],
    *,
    shed_age_days: Optional[int],
    historical_match_rate: float,
    peer_sample_size: int,
    aging_threshold_days: int = 90,
) -> Optional[Dict[str, Any]]:
    """Fired when a sidewalk shed has been up >90 days — DOB's
    SSMR (Sidewalk Shed Maintenance & Removal) Unit increases
    visit frequency past this threshold."""
    if shed_age_days is None:
        return None
    if shed_age_days <= aging_threshold_days:
        return None
    lo, hi = DEFAULT_WINDOWS[TRIGGER_SSMR_SHED_AGING]
    return {
        "trigger_kind":          TRIGGER_SSMR_SHED_AGING,
        "confidence":            float(historical_match_rate),
        "peer_sample_size":      int(peer_sample_size),
        "historical_match_rate": float(historical_match_rate),
        "days_window_min":       lo,
        "days_window_max":       hi,
        "input_snapshot": {
            "shed_age_days":       shed_age_days,
            "aging_threshold_days": aging_threshold_days,
        },
    }


ALL_TRIGGERS = (
    trigger_311_at_bin,
    trigger_311_neighbor,
    trigger_csc_periodic,
    trigger_borough_sweep,
    trigger_neighbor_swo,
    trigger_cse_followup,
    trigger_cure_deadline_reinspection,
    trigger_ssmr_shed_aging,
)


# ── Sample-size + confidence gate ─────────────────────────────────


def passes_publication_gate(prediction: Dict[str, Any]) -> bool:
    """Spec: "Confidence threshold 70% AND sample size 20+ for
    notifications." A trigger that fires but fails this gate is
    logged for calibration but not surfaced to the operator."""
    if prediction is None:
        return False
    return (
        prediction.get("peer_sample_size", 0) >= MIN_PEER_SAMPLE_SIZE
        and prediction.get("confidence", 0) >= MIN_CONFIDENCE_THRESHOLD
    )


# ── Predicted-event upsert ────────────────────────────────────────


async def upsert_prediction(
    db,
    *,
    project: Dict[str, Any],
    prediction: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Persist a fired prediction into predicted_events. Returns
    the inserted/updated doc, or None if the prediction failed
    the publication gate (sample size + confidence)."""
    if not passes_publication_gate(prediction):
        return None
    cur_now = now or datetime.now(timezone.utc)
    days_max = int(prediction.get("days_window_max", 14))
    project_id = str(project.get("_id") or project.get("id") or "")
    if not project_id:
        return None
    # Dedupe per (project, trigger_kind, day) so re-running the
    # orchestrator within the same day doesn't create N copies.
    # `predicted_at` is the day-truncated timestamp so the upsert
    # filter matches on subsequent same-day calls.
    predicted_at_day = cur_now.replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    doc = {
        "project_id":            project_id,
        "company_id":            str(project.get("company_id") or ""),
        "trigger_kind":          prediction["trigger_kind"],
        "predicted_at":          predicted_at_day,
        "first_seen_at":         cur_now,
        "expires_at":            predicted_at_day + timedelta(days=days_max),
        "confidence":            prediction["confidence"],
        "peer_sample_size":      prediction["peer_sample_size"],
        "historical_match_rate": prediction["historical_match_rate"],
        "days_window_min":       prediction["days_window_min"],
        "days_window_max":       prediction["days_window_max"],
        "input_snapshot":        prediction.get("input_snapshot", {}),
        "outcome_status":        "active",
    }
    key = {
        "project_id":   project_id,
        "trigger_kind": prediction["trigger_kind"],
        "predicted_at": predicted_at_day,
    }
    res = await db[PREDICTED_EVENTS_COLLECTION].update_one(
        key, {"$set": doc}, upsert=True,
    )
    if res.upserted_id is not None:
        doc["_id"] = res.upserted_id
    return doc


async def expire_stale_predictions(
    db, *, now: Optional[datetime] = None,
) -> int:
    """Sweep predicted_events for entries whose expires_at <= now
    and whose outcome_status is still 'active'. Mark them
    'expired'. (Outcome attribution itself lands in Commit 6.)
    Returns the number of predictions expired."""
    cur_now = now or datetime.now(timezone.utc)
    res = await db[PREDICTED_EVENTS_COLLECTION].update_many(
        {
            "expires_at": {"$lte": cur_now},
            "outcome_status": "active",
        },
        {"$set": {"outcome_status": "expired"}},
    )
    return getattr(res, "modified_count", 0) or 0


# ── Active predictions query (used by score + drawer) ─────────────


async def active_predictions_for_project(
    db, project_id: str, *, now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    cur_now = now or datetime.now(timezone.utc)
    cursor = db[PREDICTED_EVENTS_COLLECTION].find({
        "project_id": project_id,
        "expires_at": {"$gt": cur_now},
        "outcome_status": "active",
    })
    out: List[Dict[str, Any]] = []
    async for doc in cursor:
        out.append(doc)
    return out


# ── Orchestrator ──────────────────────────────────────────────────


async def _historical_match_rate_for_trigger(
    db,
    *,
    trigger_kind: str,
    peer_sample_size: int,
) -> float:
    """Look up the historical match rate for a trigger kind
    from prior outcome data. Until Commit 6 lands the calibration
    aggregator, we use a static prior per trigger (best-guess
    from MR.14 + DOB enforcement-cycle norms). The operator can
    tune these via the admin endpoint in Commit 6.

    Returns a float in [0, 1].
    """
    # Static priors. Override via the admin weight tuner once
    # outcome data accumulates.
    PRIORS = {
        TRIGGER_311_AT_BIN:              0.78,
        TRIGGER_311_NEIGHBOR:            0.72,
        TRIGGER_CSC_PERIODIC:            0.81,
        TRIGGER_BOROUGH_SWEEP:           0.74,
        TRIGGER_NEIGHBOR_SWO:            0.71,
        TRIGGER_CSE_FOLLOWUP:            0.75,
        TRIGGER_CURE_DEADLINE_REINSPECT: 0.85,
        TRIGGER_SSMR_SHED_AGING:         0.73,
    }
    return PRIORS.get(trigger_kind, 0.70)


# ── Socrata helpers (V2.3 Commit 3 — lazy event fetches) ──────────


def _soql_quote(value: str) -> str:
    """Wrap a value in single quotes and escape internal quotes for
    SoQL inclusion."""
    return "'" + str(value).replace("'", "''") + "'"


def _iso_z(dt: datetime) -> str:
    """Format a datetime in ISO-8601 form Socrata accepts as a
    floating-timestamp comparator RHS. Used for 311 +
    inspections (which carry true timestamp columns).
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _yyyymmdd(dt: datetime) -> str:
    """Format a datetime as ``YYYYMMDD``, the no-separator string
    format dob_violations (3h2n-5cm9) uses for ``issue_date``.
    """
    return dt.strftime("%Y%m%d")


# DOB inspections (p937-wjvj) ships a numeric ``boro_code`` (1-5)
# alongside its mixed-case ``borough`` ("Brooklyn") column. The
# borough_code is the stable identifier — the casing of the
# string column has flipped across past dataset versions. Use the
# numeric code for borough-sweep queries.
_INSPECTION_BORO_CODE = {
    "MANHATTAN":     "1",
    "BRONX":         "2",
    "BROOKLYN":      "3",
    "QUEENS":        "4",
    "STATEN ISLAND": "5",
}


def _inspection_boro_code(stored: Optional[str]) -> Optional[str]:
    """Translate Blueview's stored UPPER-case full borough name to
    the 1-5 numeric ``boro_code`` p937-wjvj uses. Returns None for
    unknown inputs so the caller can drop the filter rather than
    send a malformed query."""
    if not stored:
        return None
    return _INSPECTION_BORO_CODE.get(stored.strip().upper())


def _parse_socrata_dt(value: Any) -> Optional[datetime]:
    """Best-effort parse of Socrata floating-timestamp strings into
    tz-aware UTC datetimes. Robust to None / non-strings."""
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


def _parse_socrata_yyyymmdd(value: Any) -> Optional[datetime]:
    """Parse the ``issue_date`` column from dob_violations
    (3h2n-5cm9), which is a YYYYMMDD string like ``"20171227"``.
    Returns a tz-aware UTC datetime at midnight on that date.
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


async def gather_trigger_inputs(
    socrata: SocrataClient,
    project: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pre-fetch the data each trigger needs in one pass so we
    don't fire 8 sequential per-trigger Socrata calls.

    V2.3 signature change: takes ``SocrataClient`` in place of
    ``db`` (the V2.2 nyc_* mirror is gone). All five reads switch
    from local Mongo cursors to lazy Socrata GETs. Block-prefix
    filters (``bbl LIKE '<block>%'``) are pushed down to SoQL via
    ``starts_with(bbl, '<block>')`` so we don't pull the borough's
    full daily 311 / violations feed just to post-filter in
    Python.

    Soft-fail per-dataset: a SocrataQueryError on one source
    leaves the corresponding output list/count empty but lets
    the other triggers' inputs populate normally. This preserves
    the V2.2 behavior of degrading gracefully when one source
    times out.
    """
    cur_now = now or datetime.now(timezone.utc)
    bin_ = project.get("nyc_bin") or project.get("bin")
    bbl = normalize_bbl(project.get("bbl") or project.get("nyc_bbl"))
    block = _bbl_block(bbl)

    out: Dict[str, Any] = {
        "now": cur_now,
        "recent_311_at_bin": [],
        "recent_311_neighbor": [],
        "borough_inspection_counts_90d": [],
        "last_7d_count": 0,
        "neighbor_swo_count_30d": 0,
        "nearby_violations_60d": 0,
        "open_violations_with_cure": [],
        "shed_age_days": project.get("shed_age_days"),
        "days_since_last_csc": project.get("days_since_last_csc"),
    }

    cutoff_24h = cur_now - timedelta(days=1)
    cutoff_30d = cur_now - timedelta(days=30)
    cutoff_60d = cur_now - timedelta(days=60)
    cutoff_90d = cur_now - timedelta(days=90)
    last7_cutoff = cur_now - timedelta(days=7)

    # 311 at OWN BUILDING — past 24h. Schema-corrections hotfix:
    # erm2-nwe9 has NO ``bin`` column; filter by ``bbl`` instead.
    # The trigger function (trigger_311_at_bin) keeps its name for
    # backwards compatibility but its semantics are now "311 at
    # the project's BBL", not "311 at the project's BIN".
    if bbl:
        try:
            rows = await socrata.query_all(
                DATASET_COMPLAINTS_311,
                where=(
                    f"bbl = {_soql_quote(bbl)} AND created_date > "
                    f"{_soql_quote(_iso_z(cutoff_24h))}"
                ),
                page_size=1000,
            )
            out["recent_311_at_bin"] = list(rows)
        except SocrataQueryError as e:
            logger.warning("[triggers] recent_311_at_bin failed: %r", e)

    # 311 neighbor — past 24h, same block, NOT same building. We
    # push the block-prefix filter down to SoQL via starts_with()
    # — smaller wire size than V2.2's "fetch whole day, filter in
    # Python" pattern. Schema-corrections hotfix: skip own-building
    # via ``bbl`` (not ``bin``, which doesn't exist on 311).
    if block:
        try:
            rows = await socrata.query_all(
                DATASET_COMPLAINTS_311,
                where=(
                    f"starts_with(bbl, {_soql_quote(block)}) AND "
                    f"created_date > {_soql_quote(_iso_z(cutoff_24h))}"
                ),
                page_size=1000,
            )
            for doc in rows:
                if doc.get("bbl") != bbl:
                    out["recent_311_neighbor"].append(doc)
        except SocrataQueryError as e:
            logger.warning("[triggers] recent_311_neighbor failed: %r", e)

    # Borough inspection rolling 90-day counts (per-day list).
    # Schema-corrections hotfix: inspections (p937-wjvj) ships
    # ``borough`` in mixed case ("Brooklyn") and ``boro_code`` as
    # a 1-5 numeric. The numeric is stable across dataset
    # republications; use that instead of the brittle string.
    boro_code = _inspection_boro_code(project.get("borough"))
    if boro_code:
        try:
            rows = await socrata.query_all(
                DATASET_DOB_INSPECTIONS,
                where=(
                    f"boro_code = {_soql_quote(boro_code)} AND "
                    f"inspection_date > {_soql_quote(_iso_z(cutoff_90d))}"
                ),
                select=["inspection_date"],
                page_size=5000,
            )
            per_day: Dict[str, int] = {}
            last7 = 0
            for doc in rows:
                occ = _parse_socrata_dt(doc.get("inspection_date"))
                if occ is None:
                    continue
                day_key = occ.strftime("%Y-%m-%d")
                per_day[day_key] = per_day.get(day_key, 0) + 1
                if occ >= last7_cutoff:
                    last7 += 1
            out["borough_inspection_counts_90d"] = list(per_day.values())
            out["last_7d_count"] = last7
        except SocrataQueryError as e:
            logger.warning("[triggers] borough inspections failed: %r", e)

    # Neighbor SWO + nearby violations (block proximity).
    # Schema-corrections hotfix: dob_violations (3h2n-5cm9) does
    # NOT carry a ``bbl`` column; the block-proximity filter has
    # to go through ``boro``+``block`` instead. ``issue_date`` is
    # also a YYYYMMDD string column (not ISO datetime) so cutoffs
    # and parsing both switch to ``_yyyymmdd`` /
    # ``_parse_socrata_yyyymmdd``.
    if bbl and len(bbl) >= 6:
        boro_digit = bbl[:1]
        block_only = bbl[1:6].lstrip("0") or "0"
        try:
            rows = await socrata.query_all(
                DATASET_DOB_VIOLATIONS,
                where=(
                    f"boro = {_soql_quote(boro_digit)} AND "
                    f"block = {_soql_quote(block_only)} AND "
                    f"issue_date > {_soql_quote(_yyyymmdd(cutoff_60d))}"
                ),
                page_size=5000,
            )
            for doc in rows:
                # Skip same-BIN — that feeds the cure_deadline
                # trigger via the own-BIN query below.
                if doc.get("bin") == bin_:
                    continue
                occ = _parse_socrata_yyyymmdd(doc.get("issue_date"))
                if occ is None:
                    continue
                if occ >= cutoff_60d:
                    out["nearby_violations_60d"] += 1
                if occ >= cutoff_30d:
                    desc = (doc.get("description") or "").lower()
                    if "stop work" in desc or doc.get("violation_type") == "SWO":
                        out["neighbor_swo_count_30d"] += 1
        except SocrataQueryError as e:
            logger.warning("[triggers] neighbor violations failed: %r", e)

    # Open violations with cure deadline on the project's own BIN.
    # Socrata dataset 3h2n-5cm9 doesn't ship a typed cure_deadline
    # column on the public schema (V2.2 sourced it from a
    # synthetic field populated by the ingestion canonicalizer).
    # For Commit 3 we look at every row for the BIN and surface
    # any whose cure_deadline is parseable in the future; this
    # preserves V2.2 behavior with the limited data Socrata
    # exposes. If a future commit needs richer cure-deadline
    # detection it can pull from the DOB NOW endpoint via the
    # worker queue.
    if bin_:
        try:
            rows = await socrata.query_all(
                DATASET_DOB_VIOLATIONS,
                where=f"bin = {_soql_quote(bin_)}",
                page_size=1000,
            )
            for doc in rows:
                cure_raw = doc.get("cure_deadline")
                cure = _parse_socrata_dt(cure_raw) if cure_raw else None
                if cure is not None:
                    # Materialize the parsed datetime so downstream
                    # trigger logic (which expects a datetime) works.
                    doc = dict(doc)
                    doc["cure_deadline"] = cure
                    out["open_violations_with_cure"].append(doc)
        except SocrataQueryError as e:
            logger.warning("[triggers] own-BIN violations failed: %r", e)

    return out


async def run_triggers_for_project(
    db,
    project: Dict[str, Any],
    *,
    socrata: Optional[SocrataClient] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Walk all 8 triggers for one project. Returns the list of
    persisted predictions (those that passed the publication
    gate). Predictions that fired but failed the gate are NOT
    persisted (saves storage + avoids low-quality noise).

    V2.3 signature change: accepts an optional ``socrata``
    SocrataClient. When None (the default), constructs one
    inline backed by a fresh ServerHttpClient for the duration
    of the call. Score.py's ``recompute_and_persist`` passes a
    shared client through so the same connection pool is reused
    across triggers + peer comparison + own-building counts.
    """
    cur_now = now or datetime.now(timezone.utc)

    inline_http: Optional[ServerHttpClient] = None
    if socrata is None:
        inline_http = ServerHttpClient(timeout=10.0)
        await inline_http.__aenter__()
        socrata = SocrataClient(inline_http)
    try:
        inputs = await gather_trigger_inputs(socrata, project, now=cur_now)
        return await _run_triggers_with_inputs(
            db, project, inputs, now=cur_now,
        )
    finally:
        if inline_http is not None:
            await inline_http.__aexit__(None, None, None)


async def _run_triggers_with_inputs(
    db,
    project: Dict[str, Any],
    inputs: Dict[str, Any],
    *,
    now: datetime,
) -> List[Dict[str, Any]]:
    """Dispatch + persist step, split out of run_triggers_for_project
    so the orchestrator's I/O setup is separated from the
    dispatch logic."""
    cur_now = now

    # Peer sample size — for now we use a placeholder pulled from
    # the project's recently-cached compare doc; Commit 5 wires
    # the real `peer_bins` / `compare_project_to_peers` call.
    # Tests inject this directly via the helper below.
    peer_sample_size = int(project.get("_peer_sample_size_for_test", 25))

    out: List[Dict[str, Any]] = []
    # Each trigger has its own kwargs subset; we route them via
    # an explicit dispatch table.
    dispatch = (
        (
            trigger_311_at_bin,
            TRIGGER_311_AT_BIN,
            {"recent_311_at_bin": inputs["recent_311_at_bin"]},
        ),
        (
            trigger_311_neighbor,
            TRIGGER_311_NEIGHBOR,
            {"recent_311_neighbor": inputs["recent_311_neighbor"]},
        ),
        (
            trigger_csc_periodic,
            TRIGGER_CSC_PERIODIC,
            {"days_since_last_csc": inputs["days_since_last_csc"]},
        ),
        (
            trigger_borough_sweep,
            TRIGGER_BOROUGH_SWEEP,
            {
                "borough_inspection_counts_90d":
                    inputs["borough_inspection_counts_90d"],
                "last_7d_count": inputs["last_7d_count"],
            },
        ),
        (
            trigger_neighbor_swo,
            TRIGGER_NEIGHBOR_SWO,
            {"neighbor_swo_count_30d": inputs["neighbor_swo_count_30d"]},
        ),
        (
            trigger_cse_followup,
            TRIGGER_CSE_FOLLOWUP,
            {"nearby_violations_60d": inputs["nearby_violations_60d"]},
        ),
        (
            trigger_cure_deadline_reinspection,
            TRIGGER_CURE_DEADLINE_REINSPECT,
            {
                "open_violations_with_cure":
                    inputs["open_violations_with_cure"],
                "now": cur_now,
            },
        ),
        (
            trigger_ssmr_shed_aging,
            TRIGGER_SSMR_SHED_AGING,
            {"shed_age_days": inputs["shed_age_days"]},
        ),
    )
    for fn, kind, kwargs in dispatch:
        try:
            rate = await _historical_match_rate_for_trigger(
                db, trigger_kind=kind,
                peer_sample_size=peer_sample_size,
            )
            prediction = fn(
                project,
                historical_match_rate=rate,
                peer_sample_size=peer_sample_size,
                **kwargs,
            )
            if prediction is None:
                continue
            persisted = await upsert_prediction(
                db, project=project, prediction=prediction, now=cur_now,
            )
            if persisted is not None:
                out.append(persisted)
        except Exception as e:
            logger.warning(
                f"[triggers] {kind} for project {project.get('_id')} "
                f"raised: {e!r}",
            )
    return out
