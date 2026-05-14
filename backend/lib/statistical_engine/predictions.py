"""Phase V2.3 Commit 6 — Predictive inspection surfacing from 311 complaints.

When a new 311 complaint lands on a tracked project's BIN
(``_ingest_311_for_project`` in server.py), this module computes
a statistical prediction: how likely is a DOB inspection in the
next 7 days, and approximately when?

Algorithm (``predict_inspection_from_complaint``):

  1. Pull historical 311 complaints matching ``{complaint_type,
     borough}`` over the past 2 years (single paginated Socrata
     query against erm2-nwe9).
  2. Extract unique BBLs.
  3. Pull DOB inspections at those BBLs over the same window
     (chunked ``bbl IN (...)`` against p937-wjvj).
  4. Python-side join: for each historical complaint, count it
     as "inspection-following" if a DOB inspection occurred at
     the same BBL within 7 days of the complaint date.
  5. Compute inspection_rate + median_hours_to_inspection +
     mode_hour_of_day from the matched pairs.
  6. Apply guards (min sample size, min inspection rate).
  7. Confidence = inspection_rate × min(1.0, sample_size / 50),
     capped at 0.99.
  8. If confidence ≥ 0.70, build a display message and return
     the prediction dict. Otherwise return None.

The wrapper ``try_predict_inspection_from_complaint`` is what
server.py spawns as a fire-and-forget ``asyncio.create_task``.
It owns ServerHttpClient lifecycle, applies the 30-second
compute timeout, persists the prediction to ``predicted_events``
on success, and (in this commit) logs a TODO-shaped marker
where Commit 7's notifications will eventually go.

Resolution flow:
  • ``sweep_prediction_resolutions`` — APScheduler tick every
    30 minutes. Walks active 311-inspection-prediction rows;
    for each, queries Socrata for actual DOB inspections at
    the project's BIN since predicted_at. On match → hit; on
    past-expiry-without-match → miss; on past-expiry-no-BIN →
    expired_no_data.
  • ``opportunistic_resolution_check`` — same logic scoped to
    one project. Fire-and-forget from the GET risk-score
    endpoint so operators viewing a project's score also see
    fresh resolution status.
  • ``cleanup_resolved_predictions`` — daily cron at 03:45 ET.
    Deletes resolved rows older than 30 days (analytical
    retention window).

Storage shape: extends the V2.2 ``predicted_events`` document
shape (used by ``triggers.upsert_prediction``) with four new
fields (``trigger_complaint_id``, ``display_message``,
``method``, ``resolved_at``). The ``outcome_status`` lifecycle
reuses the calibration framework's vocabulary verbatim
(``active`` / ``hit`` / ``miss`` / ``expired_no_data``) so the
prediction docs remain calibration-compatible.

NOT WIRED FROM THIS COMMIT:
  • Push notifications / in-app bell — Commit 7 builds the
    notifications collection. This commit logs INFO "would have
    notified" and stops.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from bson import ObjectId  # type: ignore
except ImportError:  # pragma: no cover
    ObjectId = None  # type: ignore

from lib.notifications_inbox import dispatch_notification
from lib.server_http import ServerHttpClient
from lib.statistical_engine.schema import PREDICTED_EVENTS_COLLECTION
from lib.statistical_engine.socrata_client import (
    DATASET_COMPLAINTS_311,
    DATASET_DOB_INSPECTIONS,
    SocrataClient,
    SocrataQueryError,
)


logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────

# Confidence cutoff for storage + notification. Locked product
# decision (Commit 6 spec preamble): predictions at <70%
# confidence are not surfaced. Use the named constant
# everywhere; no magic 0.70 in the code.
PREDICTION_CONFIDENCE_THRESHOLD = 0.70

# Lookback window for the training data (historical complaints +
# matching DOB inspections). 2 years matches the same window
# used by the V2.3 peer-stats engine (PEER_STATS_LOOKBACK_DAYS).
PREDICTION_LOOKBACK_YEARS = 2

# How long after a complaint a follow-up inspection still counts
# as "caused by" the complaint. Empirical NYC DOB enforcement
# cycle norm — most inspector responses to 311 land within a
# week.
PREDICTION_INSPECTION_WINDOW_DAYS = 7

# Minimum training-set size before a prediction can be
# considered statistically meaningful. Below this, the
# inspection_rate is too noisy.
PREDICTION_MIN_SAMPLE_SIZE = 10

# Minimum historical inspection rate to bother predicting from.
# If <50% of similar complaints triggered inspections, the
# predictive signal is too weak to be useful.
PREDICTION_MIN_INSPECTION_RATE = 0.50

# Hard cap on the per-prediction compute. Mirrors prewarm.py's
# PREWARM_TIMEOUT_SECONDS — both are async background tasks
# that should never block a 311-poll tick indefinitely.
PREDICTION_COMPUTE_TIMEOUT_SECONDS = 30.0

# Retention window for resolved predictions. Past this, the
# daily cleanup cron deletes them. Tuned long enough for
# operator review + post-hoc calibration analysis, short
# enough to not accumulate forever.
RESOLVED_PREDICTION_RETENTION_DAYS = 30

# Confidence calc — the sample-size scale factor saturates at
# this many samples. Below 50 samples, confidence is dampened
# proportionally; at/above 50, the full inspection_rate carries.
PREDICTION_CONFIDENCE_SATURATION_SAMPLES = 50

# Hour-window display half-width. mode_hour ± this = "X-Y".
# Spec example "between 3-5 PM" implies span=1 (2-hour window).
PREDICTION_HOUR_WINDOW_SPAN = 1

# Method label stored in predicted_events.method. Lets the
# cleanup + sweep crons scope strictly to Commit-6 predictions
# (other entries on this collection from the V2.2 trigger
# detectors carry no method field).
PREDICTION_METHOD = "complaint_inspection_correlation"

# Page size for Socrata queries during prediction compute.
# 5000 = one round trip for typical (complaint_type, borough)
# pairs; safety cap of max_pages prevents runaway.
_SOCRATA_PAGE_SIZE = 5000
_SOCRATA_MAX_PAGES = 5

# Chunk size for ``bbl IN (...)`` in the inspections query.
# Same value as baselines.py:SOQL_IN_CHUNK_SIZE — keeps URL
# under Socrata's ~2KB limit.
_SOQL_IN_CHUNK_SIZE = 250


# ── Helpers (project-id coercion + datetime parsing, mirror prewarm) ──


def _to_mongo_id(project_id: Any) -> Any:
    """Coerce a project_id into the Mongo storage form."""
    if ObjectId is None or isinstance(project_id, ObjectId):
        return project_id
    if isinstance(project_id, str) and len(project_id) == 24:
        try:
            return ObjectId(project_id)
        except Exception:
            return project_id
    return project_id


def _parse_socrata_dt(value: Any) -> Optional[datetime]:
    """Parse Socrata floating-timestamp into UTC datetime. Robust
    to None and non-strings."""
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


def _soql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _iso_prefix(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _chunk(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i:i + n] for i in range(0, len(seq), n)]


# ── Display message formatting ────────────────────────────────────


def _hour_to_12h(hour: int) -> tuple:
    """Convert a 24-hour value to (hour_12, "AM"|"PM")."""
    h = hour % 24
    if h == 0:
        return 12, "AM"
    if h < 12:
        return h, "AM"
    if h == 12:
        return 12, "PM"
    return h - 12, "PM"


def _format_display_message(
    median_hours_to_inspection: float,
    mode_hour: int,
    *,
    span_hours: int = PREDICTION_HOUR_WINDOW_SPAN,
) -> str:
    """Build the operator-facing 1-sentence display string.

    Format: ``Inspection likely {day_phrase} between {window}.``

    Examples:
      • median 28h, mode 16 (4 PM), span 1 →
        "Inspection likely tomorrow between 3-5 PM."
      • median 4h, mode 10 (10 AM), span 1 →
        "Inspection likely today between 9-11 AM."
      • median 72h, mode 14 (2 PM), span 1 →
        "Inspection likely in 3 days between 1-3 PM."
    """
    # Day phrase from median hours.
    days_offset = int(median_hours_to_inspection // 24)
    if days_offset <= 0:
        day_phrase = "today"
    elif days_offset == 1:
        day_phrase = "tomorrow"
    else:
        day_phrase = f"in {days_offset} days"

    # Hour window (centered on mode, ±span_hours).
    lo = (mode_hour - span_hours) % 24
    hi = (mode_hour + span_hours) % 24
    lo_h, lo_ampm = _hour_to_12h(lo)
    hi_h, hi_ampm = _hour_to_12h(hi)
    if lo_ampm == hi_ampm:
        window = f"{lo_h}-{hi_h} {lo_ampm}"
    else:
        window = f"{lo_h} {lo_ampm} - {hi_h} {hi_ampm}"

    return f"Inspection likely {day_phrase} between {window}."


# ── Confidence calculation ────────────────────────────────────────


def _compute_confidence(*, inspection_rate: float, sample_size: int) -> float:
    """Confidence = inspection_rate × min(1.0, sample_size / 50),
    capped at 0.99. The sample-size dampener prevents a tiny
    high-rate sample (e.g., 5/5 inspections from 5 complaints)
    from producing 1.0 confidence.

    Hits the ≥0.70 publication threshold only when BOTH:
      • inspection_rate ≥ 0.70 (matches the threshold) AND
      • sample_size ≥ ~50 (saturation point), OR
      • inspection_rate × sample_size / 50 ≥ 0.70 by other
        combinations (e.g., 0.85 rate × 40/50 = 0.68 — fails;
        0.90 rate × 45/50 = 0.81 — passes).
    """
    if sample_size <= 0:
        return 0.0
    scale = min(1.0, sample_size / PREDICTION_CONFIDENCE_SATURATION_SAMPLES)
    raw = inspection_rate * scale
    return min(0.99, raw)


# ── Core prediction compute ───────────────────────────────────────


async def predict_inspection_from_complaint(
    socrata: SocrataClient,
    project: Dict[str, Any],
    complaint: Dict[str, Any],
    *,
    lookback_years: int = PREDICTION_LOOKBACK_YEARS,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Compute inspection prediction from a fresh 311 complaint.

    Returns prediction dict (ready for ``predicted_events``
    insert) if confidence ≥ ``PREDICTION_CONFIDENCE_THRESHOLD``,
    otherwise ``None``.

    Soft-fails to ``None`` when the training set is too small or
    Socrata raises — predictions are best-effort, never block
    the calling 311-poll task.
    """
    cur_now = now or datetime.now(timezone.utc)
    complaint_type = (complaint.get("complaint_type") or "").strip()
    # TODO(schema-corrections): both sides of this OR happen to
    # produce the same UPPER-case full borough name format that
    # the 311 dataset (erm2-nwe9) stores natively — Blueview
    # projects also store "BROOKLYN" — so the query at line ~320
    # works by coincidence. If a future commit normalizes
    # project.borough to 2-letter PLUTO codes ("BK") or mixed
    # case ("Brooklyn"), this line MUST translate back to the
    # 311 storage format ("BROOKLYN") before issuing the query.
    # The other dataset-specific borough translations live in
    # baselines.py (_pluto_borough) and triggers.py
    # (_inspection_boro_code) — model the fix on those.
    borough = (complaint.get("borough") or project.get("borough") or "").strip()
    complaint_id = (complaint.get("unique_key") or "").strip()
    complaint_date = _parse_socrata_dt(complaint.get("created_date")) or cur_now

    if not complaint_type or not borough or not complaint_id:
        # Missing data — can't form a similar-case query.
        return None

    window_start = cur_now - timedelta(days=365 * lookback_years)
    # Strictly-before so we don't include the complaint itself.
    upper_bound = complaint_date

    # ── Step 1: historical complaints with same (type, borough) ──
    try:
        hist_rows = await socrata.query_all(
            DATASET_COMPLAINTS_311,
            where=(
                f"complaint_type = {_soql_quote(complaint_type)} AND "
                f"borough = {_soql_quote(borough)} AND "
                f"created_date > {_soql_quote(_iso_prefix(window_start))} AND "
                f"created_date < {_soql_quote(_iso_prefix(upper_bound))}"
            ),
            select=["unique_key", "bbl", "created_date"],
            page_size=_SOCRATA_PAGE_SIZE,
            max_pages=_SOCRATA_MAX_PAGES,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[predict] historical complaints query failed: %r", e,
        )
        return None

    # Filter to rows with a parseable date + a BBL.
    historical: List[Dict[str, Any]] = []
    for r in hist_rows:
        bbl = (r.get("bbl") or "").strip()
        dt = _parse_socrata_dt(r.get("created_date"))
        if bbl and dt is not None:
            historical.append({"bbl": bbl, "date": dt})

    sample_size = len(historical)
    if sample_size < PREDICTION_MIN_SAMPLE_SIZE:
        return None

    # ── Step 2: DOB inspections at those BBLs (chunked) ──
    unique_bbls = sorted({h["bbl"] for h in historical})
    inspections_by_bbl: Dict[str, List[datetime]] = {b: [] for b in unique_bbls}
    for bbl_chunk in _chunk(unique_bbls, _SOQL_IN_CHUNK_SIZE):
        in_clause = ",".join(_soql_quote(b) for b in bbl_chunk)
        try:
            rows = await socrata.query_all(
                DATASET_DOB_INSPECTIONS,
                where=(
                    f"bbl IN ({in_clause}) AND "
                    f"inspection_date > {_soql_quote(_iso_prefix(window_start))}"
                ),
                select=["bbl", "inspection_date"],
                page_size=_SOCRATA_PAGE_SIZE,
                max_pages=_SOCRATA_MAX_PAGES,
            )
        except SocrataQueryError as e:
            logger.warning(
                "[predict] inspections chunk failed: %r", e,
            )
            # Partial-failure tolerance: continue with whatever
            # we collected. Other chunks may still produce
            # signal. Sample-size guard below catches the
            # degenerate-empty case.
            continue
        for r in rows:
            b = (r.get("bbl") or "").strip()
            dt = _parse_socrata_dt(r.get("inspection_date"))
            if b in inspections_by_bbl and dt is not None:
                inspections_by_bbl[b].append(dt)

    # ── Step 3: training join (complaint → inspection-in-window) ──
    matches: List[float] = []  # hours-to-inspection per match
    mode_hours: List[int] = []
    for h in historical:
        c_bbl, c_date = h["bbl"], h["date"]
        window_close = c_date + timedelta(days=PREDICTION_INSPECTION_WINDOW_DAYS)
        # Take the EARLIEST inspection at this BBL in the
        # forward window. Multiple inspections in the same
        # 7-day window count as one event (rate-of-trigger
        # matters more than count).
        candidates = [
            i for i in inspections_by_bbl.get(c_bbl, [])
            if c_date < i <= window_close
        ]
        if not candidates:
            continue
        first_inspection = min(candidates)
        delta_hours = (first_inspection - c_date).total_seconds() / 3600.0
        matches.append(delta_hours)
        mode_hours.append(first_inspection.hour)

    if not matches:
        return None

    inspection_rate = len(matches) / sample_size
    if inspection_rate < PREDICTION_MIN_INSPECTION_RATE:
        return None

    # ── Step 4: confidence + display ──
    confidence = _compute_confidence(
        inspection_rate=inspection_rate, sample_size=sample_size,
    )
    if confidence < PREDICTION_CONFIDENCE_THRESHOLD:
        return None

    median_hours = statistics.median(matches)
    # Mode hour-of-day from the matched inspections. If multimodal,
    # statistics.mode picks the first; Counter.most_common is
    # equivalent but deterministic.
    mode_hour = Counter(mode_hours).most_common(1)[0][0]

    display = _format_display_message(median_hours, mode_hour)

    expires_at = cur_now + timedelta(days=PREDICTION_INSPECTION_WINDOW_DAYS)
    project_id = str(project.get("_id") or project.get("id") or "")
    company_id = str(project.get("company_id") or "")

    return {
        # V2.2-compat / calibration-framework-compat fields:
        "project_id":             project_id,
        "company_id":             company_id,
        "trigger_kind":           "311_inspection_prediction",
        "predicted_at":           cur_now,
        "first_seen_at":          cur_now,
        "expires_at":             expires_at,
        "confidence":             confidence,
        "peer_sample_size":       sample_size,
        "historical_match_rate":  inspection_rate,
        "days_window_min":        0,
        "days_window_max":        PREDICTION_INSPECTION_WINDOW_DAYS,
        "input_snapshot": {
            "complaint_type":              complaint_type,
            "borough":                     borough,
            "complaint_date":              complaint_date,
            "median_hours_to_inspection":  median_hours,
            "mode_hour":                   int(mode_hour),
        },
        "outcome_status":         "active",
        # V2.3 Commit 6 additions:
        "method":                 PREDICTION_METHOD,
        "trigger_complaint_id":   complaint_id,
        "display_message":        display,
        "resolved_at":            None,
        "actual_inspection_date": None,
    }


# ── Fire-and-forget wrapper called from server.py ─────────────────


async def try_predict_inspection_from_complaint(
    db,
    project: Dict[str, Any],
    complaint: Dict[str, Any],
) -> None:
    """Background task body. Spawned via ``asyncio.create_task``
    from the 311-poll hook in server.py. Owns the
    ServerHttpClient lifecycle, applies the 30-second compute
    timeout, persists the prediction on success, and stubs the
    notification path.

    Designed fire-and-forget — entire body is wrapped in a
    catch-all so nothing escapes to the asyncio loop's
    unhandled-exception logger. Per-failure-mode logging
    (timeout, Socrata error, unexpected) parallels prewarm.py's
    error categorization.
    """
    project_id = str(project.get("_id") or project.get("id") or "")
    complaint_id = (complaint.get("unique_key") or "").strip()
    log_tag = f"{project_id}:{complaint_id}"

    try:
        async with ServerHttpClient(timeout=10.0) as http:
            socrata = SocrataClient(http)
            try:
                prediction = await asyncio.wait_for(
                    predict_inspection_from_complaint(
                        socrata, project, complaint,
                    ),
                    timeout=PREDICTION_COMPUTE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[predict] %s compute timed out after %.1fs",
                    log_tag, PREDICTION_COMPUTE_TIMEOUT_SECONDS,
                )
                return
            except SocrataQueryError as e:
                logger.warning(
                    "[predict] %s Socrata error: dataset=%s "
                    "status=%s",
                    log_tag, e.dataset_id, e.status_code,
                )
                return
            except Exception as e:  # pragma: no cover — defensive
                logger.exception(
                    "[predict] %s unexpected exception during "
                    "compute: %r", log_tag, e,
                )
                return

        if prediction is None:
            # Below threshold / insufficient sample. Quiet path
            # — predictions below 70% are the common case.
            logger.debug(
                "[predict] %s below threshold; skipping store",
                log_tag,
            )
            return

        # Persist. Each complaint produces at most one
        # prediction row (no write-side dedup needed because
        # the upstream hook fires only on existing-is-None;
        # status transitions never reach us).
        try:
            res = await db[PREDICTED_EVENTS_COLLECTION].insert_one(prediction)
            prediction["_id"] = getattr(res, "inserted_id", None)
        except Exception as e:
            logger.exception(
                "[predict] %s insert failed: %r", log_tag, e,
            )
            return

        # V2.3 Commit 7 — dispatch to the in-app notifications
        # inbox. The prediction is already persisted above; the
        # dispatch is a read-side projection of it, NOT a
        # source-of-truth write. So this call is wrapped in its
        # own try/except — a dispatch failure (Mongo blip in the
        # users collection, fan-out exceeds cap, etc.) MUST NOT
        # roll back the prediction storage that already succeeded.
        # The operator can still see the prediction via the
        # admin diagnostics; only the inbox surface is affected.
        try:
            # Severity tier: predictions ≥85% confidence surface
            # as "warning" (more visually prominent in the FE),
            # 70-85% as plain "info". The threshold is tunable —
            # holds at 0.85 for V2.3 ship.
            _severity = (
                "warning" if prediction["confidence"] >= 0.85 else "info"
            )
            await dispatch_notification(
                db,
                project=project,
                kind="inspection_prediction",
                severity=_severity,
                title="Inspection Prediction",
                message=prediction["display_message"],
                source_kind="prediction",
                source_id=str(prediction["_id"]),
                metadata={
                    "confidence": prediction["confidence"],
                    "trigger_complaint_id": prediction.get(
                        "trigger_complaint_id",
                    ),
                },
                expires_at=prediction["expires_at"],
                deeplink_anchor="predictions",
            )
        except Exception as e:
            logger.exception(
                "[predict] %s dispatch_notification failed "
                "(prediction stored, inbox dispatch did not): %r",
                log_tag, e,
            )
    except Exception as e:  # pragma: no cover — defensive outer
        logger.exception(
            "[predict] %s top-level exception swallowed: %r",
            log_tag, e,
        )


# ── Resolution sweep ──────────────────────────────────────────────


async def _resolve_one_prediction(
    db,
    socrata: SocrataClient,
    prediction: Dict[str, Any],
    *,
    now: datetime,
) -> str:
    """Process one active prediction. Returns the resolved
    outcome_status string ("hit" / "miss" / "expired_no_data")
    or "" if the prediction is still active (not yet expired
    and no inspection found).
    """
    pred_id = prediction.get("_id")
    project_id = prediction.get("project_id")
    predicted_at = prediction.get("predicted_at")
    expires_at = prediction.get("expires_at")

    # Resolve project to get the BIN (predictions store
    # project_id, not BIN, so a renamed/edited project still
    # works through this indirection).
    project = None
    try:
        project = await db.projects.find_one(
            {"_id": _to_mongo_id(project_id)},
        )
    except Exception as e:
        logger.warning(
            "[predict_resolution] project lookup failed for %s: %r",
            project_id, e,
        )

    bin_ = (project or {}).get("nyc_bin") if project else None

    if not bin_:
        # No BIN — can't query Socrata for inspections. If the
        # prediction has expired, mark expired_no_data; else
        # leave for the next sweep (the BIN may get backfilled
        # by the DOB poller).
        if isinstance(expires_at, datetime):
            exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
            if exp <= now:
                await db[PREDICTED_EVENTS_COLLECTION].update_one(
                    {"_id": pred_id},
                    {"$set": {
                        "outcome_status": "expired_no_data",
                        "resolved_at":    now,
                    }},
                )
                return "expired_no_data"
        return ""

    # Look for an inspection at this BIN since predicted_at.
    try:
        predicted_since = predicted_at if predicted_at else (now - timedelta(days=PREDICTION_INSPECTION_WINDOW_DAYS))
        if isinstance(predicted_since, datetime) and predicted_since.tzinfo is None:
            predicted_since = predicted_since.replace(tzinfo=timezone.utc)
        rows = await socrata.query(
            DATASET_DOB_INSPECTIONS,
            where=(
                f"bin = {_soql_quote(bin_)} AND "
                f"inspection_date >= {_soql_quote(_iso_prefix(predicted_since))}"
            ),
            order="inspection_date ASC",
            limit=1,
        )
    except SocrataQueryError as e:
        logger.warning(
            "[predict_resolution] inspection lookup failed for "
            "prediction %s (bin=%s): %r", pred_id, bin_, e,
        )
        return ""

    if rows:
        # Hit. Record the actual inspection date for analytics.
        actual = _parse_socrata_dt(rows[0].get("inspection_date"))
        await db[PREDICTED_EVENTS_COLLECTION].update_one(
            {"_id": pred_id},
            {"$set": {
                "outcome_status":         "hit",
                "resolved_at":            now,
                "actual_inspection_date": actual,
            }},
        )
        return "hit"

    # No matching inspection. If past expiry, mark miss; else
    # leave active for the next sweep.
    if isinstance(expires_at, datetime):
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if exp <= now:
            await db[PREDICTED_EVENTS_COLLECTION].update_one(
                {"_id": pred_id},
                {"$set": {
                    "outcome_status": "miss",
                    "resolved_at":    now,
                }},
            )
            return "miss"

    return ""


async def sweep_prediction_resolutions(
    db,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Walk active 311-inspection predictions, resolve each.

    Returns a stats dict::

      {
        "checked": int,
        "hit": int,
        "miss": int,
        "expired_no_data": int,
        "still_active": int,
        "errors": int,
      }

    Designed for APScheduler cron registration with
    ``max_instances=1 + coalesce=True``. A long sweep over many
    active predictions doesn't stack with the next tick.
    Sequential per-prediction processing — pacing matches
    refresh_cron's design intent: one HTTP client across the
    batch, one Socrata call per prediction.
    """
    cur_now = now or datetime.now(timezone.utc)
    stats = {
        "checked": 0, "hit": 0, "miss": 0,
        "expired_no_data": 0, "still_active": 0, "errors": 0,
    }

    try:
        cursor = db[PREDICTED_EVENTS_COLLECTION].find({
            "outcome_status": "active",
            "method":         PREDICTION_METHOD,
        })
        active: List[Dict[str, Any]] = []
        async for doc in cursor:
            active.append(doc)
    except Exception as e:
        logger.error(
            "[predict_resolution] active-prediction query failed: %r",
            e,
        )
        return stats

    if not active:
        return stats

    async with ServerHttpClient(timeout=10.0) as http:
        socrata = SocrataClient(http)
        for prediction in active:
            stats["checked"] += 1
            try:
                result = await _resolve_one_prediction(
                    db, socrata, prediction, now=cur_now,
                )
                if result == "hit":
                    stats["hit"] += 1
                elif result == "miss":
                    stats["miss"] += 1
                elif result == "expired_no_data":
                    stats["expired_no_data"] += 1
                else:
                    stats["still_active"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.warning(
                    "[predict_resolution] %s resolution failed: %r",
                    prediction.get("_id"), e,
                )
    return stats


# ── Page-load opportunistic check ─────────────────────────────────


async def opportunistic_resolution_check(
    db,
    project_id: Any,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Same logic as ``sweep_prediction_resolutions`` but scoped
    to one project. Wired into the GET risk-score endpoint as a
    fire-and-forget so operators viewing a project's score also
    pick up fresh resolution status without waiting for the
    next 30-minute sweep tick.

    Returns the same stats dict shape so callers/tests can
    treat them identically.
    """
    cur_now = now or datetime.now(timezone.utc)
    stats = {
        "checked": 0, "hit": 0, "miss": 0,
        "expired_no_data": 0, "still_active": 0, "errors": 0,
    }

    project_id_str = str(project_id) if project_id is not None else ""
    if not project_id_str:
        return stats

    try:
        cursor = db[PREDICTED_EVENTS_COLLECTION].find({
            "project_id":     project_id_str,
            "outcome_status": "active",
            "method":         PREDICTION_METHOD,
        })
        active: List[Dict[str, Any]] = []
        async for doc in cursor:
            active.append(doc)
    except Exception as e:
        logger.warning(
            "[predict_resolution] opportunistic query failed for %s: %r",
            project_id_str, e,
        )
        return stats

    if not active:
        return stats

    try:
        async with ServerHttpClient(timeout=10.0) as http:
            socrata = SocrataClient(http)
            for prediction in active:
                stats["checked"] += 1
                try:
                    result = await _resolve_one_prediction(
                        db, socrata, prediction, now=cur_now,
                    )
                    if result == "hit":
                        stats["hit"] += 1
                    elif result == "miss":
                        stats["miss"] += 1
                    elif result == "expired_no_data":
                        stats["expired_no_data"] += 1
                    else:
                        stats["still_active"] += 1
                except Exception as e:
                    stats["errors"] += 1
                    logger.warning(
                        "[predict_resolution] opportunistic %s "
                        "resolution failed: %r",
                        prediction.get("_id"), e,
                    )
    except Exception as e:  # pragma: no cover — defensive outer
        logger.exception(
            "[predict_resolution] opportunistic outer exception "
            "for %s: %r", project_id_str, e,
        )
    return stats


# ── Daily cleanup ─────────────────────────────────────────────────


async def cleanup_resolved_predictions(
    db,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Daily 03:45 ET cron entry. Deletes resolved predictions
    older than ``RESOLVED_PREDICTION_RETENTION_DAYS`` to bound
    collection size. Scoped via ``method == PREDICTION_METHOD``
    so V2.2-trigger predictions on the same collection (which
    have no ``method`` field) aren't touched.
    """
    cur_now = now or datetime.now(timezone.utc)
    cutoff = cur_now - timedelta(days=RESOLVED_PREDICTION_RETENTION_DAYS)
    stats = {"deleted": 0}
    try:
        result = await db[PREDICTED_EVENTS_COLLECTION].delete_many({
            "method":          PREDICTION_METHOD,
            "outcome_status":  {"$in": ["hit", "miss", "expired_no_data"]},
            "resolved_at":     {"$lt": cutoff},
        })
        stats["deleted"] = getattr(result, "deleted_count", 0) or 0
    except Exception as e:
        logger.error(
            "[predict_cleanup] delete failed: %r", e,
        )
    return stats
