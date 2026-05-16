"""Phase V2.2 — collections + indexes + canonical band thresholds.

Eleven additive collections:

  • nyc_violations              — DOB violations, BIN-keyed
  • nyc_inspections             — DOB inspections, BIN-keyed
  • nyc_permits                 — DOB permits, BIN-keyed
  • nyc_complaints_311          — 311 complaints, BIN-keyed (also BBL)
  • nyc_ecb_violations          — ECB violations, BIN-keyed
  • nyc_hpd_violations          — HPD violations, BIN-keyed
  • nyc_pluto                   — PLUTO building characteristics, BIN-keyed
  • statistical_baselines       — pre-aggregated peer stats, keyed by
                                  (borough, project_class, use_type, year_month)
  • predicted_events            — active per-project predictions
  • prediction_outcomes         — closed predictions with hit/miss
  • ingestion_state             — backfill cursor + crash resumability

Indexes are wired in server.py at startup via _ensure_index_resilient
using the *_INDEXES tuples below. ALL_V22_INDEX_SPECS lets the
startup loop iterate the whole set with one walk instead of
hand-listing each collection.

──────────────────────────────────────────────────────────────────
Schema notes
──────────────────────────────────────────────────────────────────

  Every NYC-source collection MUST have:
    • record_id   — the canonical record id from the source dataset
                    (used as the unique-index dedupe key for upserts)
    • bin         — building identifier (NYC DOB BIN, 7 digits)
    • bbl         — borough-block-lot, 10 digits (for proximity / peer)
    • borough     — 1-letter (M/B/Q/X/SI) or full name
    • occurred_date — the event date (datetime UTC, indexed desc)
    • ingested_at — when our fetcher upserted this record

  predicted_events:
    • project_id, trigger_kind, predicted_at, expires_at,
      confidence (0..1), peer_sample_size,
      historical_match_rate, days_window_min, days_window_max,
      input_snapshot (the data that produced the prediction)

  prediction_outcomes:
    • project_id, prediction_id, trigger_kind,
      predicted_at, expired_at, actual_event_at | None,
      outcome ("hit" | "miss" | "expired"),
      hit_window_days  | None
"""

from __future__ import annotations

# ── Collection names ──────────────────────────────────────────────
#
# V2.3 Commit 1: the NYC_* mirror collection constants and
# STATISTICAL_BASELINES_COLLECTION + INGESTION_STATE_COLLECTION
# were removed from this file because the V2.2 local-mirror
# architecture is being replaced by lazy Socrata queries.
#
# Transitional placement of the deleted names: see
# lib/statistical_engine/utils.py. Consumer files
# (baselines.py, triggers.py, score.py, calibration.py) import
# from there for Commits 1–2; Commit 3 rewrites them to lazy
# queries and removes those names entirely.

PREDICTED_EVENTS_COLLECTION       = "predicted_events"
PREDICTION_OUTCOMES_COLLECTION    = "prediction_outcomes"

# PR #15A — Predictive Inference Engine Phase 1 collections.
# ``daily_panels`` is the transient training table the nightly
# cron materializes per active project. 7-day TTL (single missed
# nightly leaves yesterday's panel usable for debugging).
DAILY_PANELS_COLLECTION                  = "daily_panels"

# ``prediction_validation_ledger`` records one canonical entry per
# (project_id, calendar_date) with predicted_probability +
# observed_outcome + brier_score_delta. Per Stage 2.A T7 lock:
# intra-day re-predictions UPSERT the canonical entry, they do not
# insert duplicates. Drives the rolling-30d Brier audit cron and
# the structural-recalibration alert at threshold > 0.20.
PREDICTION_VALIDATION_LEDGER_COLLECTION  = "prediction_validation_ledger"


# ── Model version + band thresholds ───────────────────────────────
#
# Bumped from V2.1's "heuristic-v1" to mark the discontinuity with
# the prior model. Old `risk_scores` rows from V2.1 are NOT
# migrated — V2.2 produces fresh rows on first calculation.

MODEL_VERSION = "statistical-v1"

SCORE_BAND_GREEN  = "green"
SCORE_BAND_YELLOW = "yellow"
SCORE_BAND_ORANGE = "orange"
SCORE_BAND_RED    = "red"


def score_band(score):
    """Map a 0..100 score to a band label.

    Same cutoffs as V2.1 (≤30 / ≤60 / ≤80 / >80) — the FE band
    classification didn't change between versions. The frontend
    `bandFor` helper in RiskScoreCircle.jsx is pinned against
    this function via the V2.1.2 boundary tests.
    """
    if score is None:
        return SCORE_BAND_GREEN
    s = float(score)
    if s <= 30:
        return SCORE_BAND_GREEN
    if s <= 60:
        return SCORE_BAND_YELLOW
    if s <= 80:
        return SCORE_BAND_ORANGE
    return SCORE_BAND_RED


# ── Sample-size + confidence guards ───────────────────────────────
#
# Spec §peer matching: "Fallback only if sample < 20."
# Spec §triggers: "Confidence threshold 70% AND sample size 20+."

MIN_PEER_SAMPLE_SIZE     = 20
MIN_CONFIDENCE_THRESHOLD = 0.70


# ── NYC-source dataset indexes ────────────────────────────────────
#
# V2.3 Commit 1: removed.
#   • _nyc_source_indexes() helper
#   • NYC_VIOLATIONS_INDEXES, NYC_INSPECTIONS_INDEXES,
#     NYC_PERMITS_INDEXES, NYC_COMPLAINTS_311_INDEXES,
#     NYC_ECB_VIOLATIONS_INDEXES, NYC_HPD_VIOLATIONS_INDEXES,
#     NYC_PLUTO_INDEXES — local-mirror is being deprecated.
#   • STATISTICAL_BASELINES_INDEXES — baselines collection deleted.
#   • INGESTION_STATE_INDEXES — ingestion_state collection deleted.
#
# Mongo collections behind those names get dropped by the
# operator post-deploy. Surviving index specs below cover the
# predicted_events + prediction_outcomes collections only.


# ── Aggregation + prediction collections ──────────────────────────

PREDICTED_EVENTS_INDEXES = (
    # Active predictions per project — drawer + score recomputation
    # both query this path.
    {
        "keys": [("project_id", 1), ("expires_at", -1)],
        "name": "predicted_events_project_expires",
    },
    # Calibration sweep: walk every prediction expiring on/before
    # `now` to attribute outcomes.
    {
        "keys": [("expires_at", 1)],
        "name": "predicted_events_expires",
    },
    # Per-trigger query for calibration breakdown.
    {
        "keys": [("trigger_kind", 1), ("predicted_at", -1)],
        "name": "predicted_events_trigger_predicted",
    },
)

PREDICTION_OUTCOMES_INDEXES = (
    # Calibration breakdown by trigger.
    {
        "keys": [("trigger_kind", 1), ("expired_at", -1)],
        "name": "prediction_outcomes_trigger_expired",
    },
    # Per-project history.
    {
        "keys": [("project_id", 1), ("expired_at", -1)],
        "name": "prediction_outcomes_project_expired",
    },
)


# ── Combined index walk for the startup hook ──────────────────────
#
# server.py iterates this list at startup and calls
# _ensure_index_resilient for each entry. V2.3 Commit 1: the
# nyc_* mirror + statistical_baselines + ingestion_state index
# specs were removed alongside their collection-name constants
# (see top of file). Only predicted_events + prediction_outcomes
# survive the V2.3 commit chain — they're written by the trigger
# detector (Commit 6) and calibration (untouched).

ALL_V22_INDEX_SPECS = (
    (PREDICTED_EVENTS_COLLECTION,      PREDICTED_EVENTS_INDEXES),
    (PREDICTION_OUTCOMES_COLLECTION,   PREDICTION_OUTCOMES_INDEXES),
)


# ── PR #15A — Daily Panel + Validation Ledger indexes ─────────────

DAILY_PANELS_INDEXES = (
    # Per-project panel reads + nightly insert_many sweep.
    {
        "keys": [("project_id", 1), ("built_at", -1)],
        "name": "panels_project_built",
    },
    # TTL — auto-expire 7 days post-build per Stage 2.A T6 cadence
    # (single missed nightly leaves yesterday's panel usable).
    {
        "keys": [("built_at", 1)],
        "name": "panels_built_ttl",
        "expireAfterSeconds": 7 * 86400,
    },
)

PREDICTION_VALIDATION_LEDGER_INDEXES = (
    # Daily audit cron — walks predictions whose horizon is today.
    {
        "keys": [("target_horizon_at", 1)],
        "name": "validation_horizon",
    },
    # Per-project history view (rolling-30d aggregation feeds here).
    {
        "keys": [("project_id", 1), ("prediction_timestamp", -1)],
        "name": "validation_project_predicted",
    },
    # Brier-score sweep for structural-recalibration alert.
    {
        "keys": [("scored_at", -1), ("brier_score_delta", -1)],
        "name": "validation_scored_brier",
    },
    # Per-project per-calendar-day upsert key (T7 canonical-per-day).
    # ``unique`` enforces the one-doc-per-day contract at the DB layer.
    {
        "keys": [("project_id", 1), ("calendar_date", 1)],
        "name": "validation_project_day",
        "unique": True,
    },
)

# PR #15A — combined index walk extends ALL_V22_INDEX_SPECS so
# server.py's startup hook ensures the new collections' indexes.
ALL_PR15A_INDEX_SPECS = (
    (DAILY_PANELS_COLLECTION,                 DAILY_PANELS_INDEXES),
    (PREDICTION_VALIDATION_LEDGER_COLLECTION, PREDICTION_VALIDATION_LEDGER_INDEXES),
)
