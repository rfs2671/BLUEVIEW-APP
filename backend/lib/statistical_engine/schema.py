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

NYC_VIOLATIONS_COLLECTION         = "nyc_violations"
NYC_INSPECTIONS_COLLECTION        = "nyc_inspections"
NYC_PERMITS_COLLECTION            = "nyc_permits"
NYC_COMPLAINTS_311_COLLECTION     = "nyc_complaints_311"
NYC_ECB_VIOLATIONS_COLLECTION     = "nyc_ecb_violations"
NYC_HPD_VIOLATIONS_COLLECTION     = "nyc_hpd_violations"
NYC_PLUTO_COLLECTION              = "nyc_pluto"
STATISTICAL_BASELINES_COLLECTION  = "statistical_baselines"
PREDICTED_EVENTS_COLLECTION       = "predicted_events"
PREDICTION_OUTCOMES_COLLECTION    = "prediction_outcomes"
INGESTION_STATE_COLLECTION        = "ingestion_state"

ALL_V22_COLLECTIONS = (
    NYC_VIOLATIONS_COLLECTION,
    NYC_INSPECTIONS_COLLECTION,
    NYC_PERMITS_COLLECTION,
    NYC_COMPLAINTS_311_COLLECTION,
    NYC_ECB_VIOLATIONS_COLLECTION,
    NYC_HPD_VIOLATIONS_COLLECTION,
    NYC_PLUTO_COLLECTION,
    STATISTICAL_BASELINES_COLLECTION,
    PREDICTED_EVENTS_COLLECTION,
    PREDICTION_OUTCOMES_COLLECTION,
    INGESTION_STATE_COLLECTION,
)


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
# Format mirrors the existing _ensure_index_resilient call sites:
# (keys, name, **opts). Every NYC-source collection has the same
# four-index baseline:
#   • record_id UNIQUE    — dedupe key for upsert ingestion
#   • (bin, occurred_date) — primary read path (per-project lookup)
#   • (borough, occurred_date) — peer aggregation walk
#   • (occurred_date)      — sweep-detection / time-window queries

def _nyc_source_indexes(prefix):
    """Build the standard 4 indexes for a BIN-keyed NYC source
    collection. Index names are uniquified by the `prefix`
    argument so two collections can have logically-equivalent
    indexes without colliding on names."""
    return (
        {
            "keys": [("record_id", 1)],
            "name": f"{prefix}_record_id_unique",
            "unique": True,
        },
        {
            "keys": [("bin", 1), ("occurred_date", -1)],
            "name": f"{prefix}_bin_date",
        },
        {
            "keys": [("borough", 1), ("occurred_date", -1)],
            "name": f"{prefix}_borough_date",
        },
        {
            "keys": [("occurred_date", -1)],
            "name": f"{prefix}_date",
        },
    )


NYC_VIOLATIONS_INDEXES     = _nyc_source_indexes("nyc_violations")
NYC_INSPECTIONS_INDEXES    = _nyc_source_indexes("nyc_inspections")
NYC_PERMITS_INDEXES        = _nyc_source_indexes("nyc_permits")
NYC_COMPLAINTS_311_INDEXES = (
    *_nyc_source_indexes("nyc_complaints_311"),
    # 311 also queried by BBL block component for "neighbor"
    # trigger; 10-char BBL → first 7 chars = borough+block.
    {
        "keys": [("bbl", 1), ("occurred_date", -1)],
        "name": "nyc_complaints_311_bbl_date",
    },
)
NYC_ECB_VIOLATIONS_INDEXES = _nyc_source_indexes("nyc_ecb_violations")
NYC_HPD_VIOLATIONS_INDEXES = _nyc_source_indexes("nyc_hpd_violations")

# PLUTO is a snapshot, not a stream of events. Different schema:
# one row per BIN, refreshed on PLUTO release cadence (~quarterly).
NYC_PLUTO_INDEXES = (
    {
        "keys": [("bin", 1)],
        "name": "nyc_pluto_bin_unique",
        "unique": True,
    },
    {
        "keys": [("bbl", 1)],
        "name": "nyc_pluto_bbl",
    },
    {
        "keys": [("borough", 1), ("bldgclass", 1)],
        "name": "nyc_pluto_borough_class",
    },
)


# ── Aggregation + prediction collections ──────────────────────────

STATISTICAL_BASELINES_INDEXES = (
    # Primary read path: peer-set lookup keyed by the four-tuple.
    {
        "keys": [
            ("borough", 1),
            ("project_class", 1),
            ("use_type", 1),
            ("year_month", -1),
        ],
        "name": "statistical_baselines_peer_key",
    },
    # Calibration sweep: read every baseline for a given month
    # (used by the per-month re-aggregation cron).
    {
        "keys": [("year_month", -1)],
        "name": "statistical_baselines_year_month",
    },
)

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

INGESTION_STATE_INDEXES = (
    # One row per dataset. The dataset name is the natural key.
    {
        "keys": [("dataset", 1)],
        "name": "ingestion_state_dataset_unique",
        "unique": True,
    },
)


# ── Combined index walk for the startup hook ──────────────────────
#
# server.py iterates this list at startup and calls
# _ensure_index_resilient for each entry. Adding a new collection
# here is a one-line change at the spec site (above) plus an entry
# in this tuple — no coordination with the startup hook needed.

ALL_V22_INDEX_SPECS = (
    (NYC_VIOLATIONS_COLLECTION,        NYC_VIOLATIONS_INDEXES),
    (NYC_INSPECTIONS_COLLECTION,       NYC_INSPECTIONS_INDEXES),
    (NYC_PERMITS_COLLECTION,           NYC_PERMITS_INDEXES),
    (NYC_COMPLAINTS_311_COLLECTION,    NYC_COMPLAINTS_311_INDEXES),
    (NYC_ECB_VIOLATIONS_COLLECTION,    NYC_ECB_VIOLATIONS_INDEXES),
    (NYC_HPD_VIOLATIONS_COLLECTION,    NYC_HPD_VIOLATIONS_INDEXES),
    (NYC_PLUTO_COLLECTION,             NYC_PLUTO_INDEXES),
    (STATISTICAL_BASELINES_COLLECTION, STATISTICAL_BASELINES_INDEXES),
    (PREDICTED_EVENTS_COLLECTION,      PREDICTED_EVENTS_INDEXES),
    (PREDICTION_OUTCOMES_COLLECTION,   PREDICTION_OUTCOMES_INDEXES),
    (INGESTION_STATE_COLLECTION,       INGESTION_STATE_INDEXES),
)
