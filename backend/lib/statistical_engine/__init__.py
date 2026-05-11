"""Phase V2.2 — Statistical Risk Engine + Event Predictor.

Replaces the V2.1 heuristic risk score with a statistical model
driven by NYC Open Data + project peer comparison + active
trigger detection. NO feature flag — V2.2 ships as the only
risk-score code path.

  • schema.py        — collection names, indexes spec, model
                       version constant, score_band helper.
  • ingestion.py     — NYC Open Data Socrata client + 6 dataset
                       fetchers + PLUTO + backfill + weekly delta.
                       (Commit 2)
  • baselines.py     — peer-set query, sample-size fallback,
                       compare-to-peer aggregation.
                       (Commit 3)
  • triggers.py      — 8 trigger detectors + event predictor
                       (Commit 4).
  • score.py         — risk score recomputation using statistical
                       inputs (Commit 5).
  • calibration.py   — outcome tracking + calibration math
                       + admin tunable weights (Commit 6).

Every NYC dataset is BIN-keyed where possible. PLUTO and the
peer-baseline pre-aggregations live in their own collections.
Event-driven re-stat is wired through the existing pollers
(nightly_dob_scan, _poll_311_fast_complaints) — they upsert into
both the v1 dob_logs collection AND the V2.2 statistical
collections so the score reflects the freshest data without
waiting for the weekly cron.
"""

from lib.statistical_engine.calibration import (  # noqa: F401
    OUTCOME_HIT,
    OUTCOME_MISS,
    OUTCOME_EXPIRED_NO_DATA,
    TRIGGER_PRIORS_COLLECTION,
    attribute_outcome_for_prediction,
    attribute_outcomes_for_expired_predictions,
    compute_calibration_stats,
    set_trigger_prior,
    get_trigger_prior,
)
from lib.statistical_engine.score import (  # noqa: F401
    GROUP_WEIGHTS,
    ALL_GROUPS,
    GROUP_OWN_BUILDING,
    GROUP_PEER_COMPARISON,
    GROUP_ACTIVE_TRIGGERS,
    GROUP_INTERNAL_COMPLIANCE,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_NOISE_SIGMA,
    CONFIDENCE_INTERVAL_PCT,
    gather_score_inputs,
    calculate_risk_score,
    recompute_and_persist,
)
from lib.statistical_engine.triggers import (  # noqa: F401
    ALL_TRIGGER_KINDS,
    TRIGGER_311_AT_BIN,
    TRIGGER_311_NEIGHBOR,
    TRIGGER_CSC_PERIODIC,
    TRIGGER_BOROUGH_SWEEP,
    TRIGGER_NEIGHBOR_SWO,
    TRIGGER_CSE_FOLLOWUP,
    TRIGGER_CURE_DEADLINE_REINSPECT,
    TRIGGER_SSMR_SHED_AGING,
    DEFAULT_WINDOWS,
    passes_publication_gate,
    upsert_prediction,
    expire_stale_predictions,
    active_predictions_for_project,
    run_triggers_for_project,
)
from lib.statistical_engine.baselines import (  # noqa: F401
    peer_bbls,
    compute_baseline_for_peer_set,
    upsert_baseline,
    run_baseline_aggregator,
    compare_project_to_peers,
)
from lib.statistical_engine.ingestion import (  # noqa: F401
    DATASETS,
    BACKFILL_YEARS,
    WEEKLY_DELTA_DAYS,
    SOCRATA_PAGE_LIMIT,
    backfill_dataset,
    backfill_all_datasets,
    weekly_delta_dataset,
    weekly_delta_all_datasets,
    forward_to_v22,
    upsert_record,
)
from lib.statistical_engine.schema import (  # noqa: F401
    # Collection names
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
    ALL_V22_COLLECTIONS,
    # Index specs (consumed by server.py startup)
    NYC_VIOLATIONS_INDEXES,
    NYC_INSPECTIONS_INDEXES,
    NYC_PERMITS_INDEXES,
    NYC_COMPLAINTS_311_INDEXES,
    NYC_ECB_VIOLATIONS_INDEXES,
    NYC_HPD_VIOLATIONS_INDEXES,
    NYC_PLUTO_INDEXES,
    STATISTICAL_BASELINES_INDEXES,
    PREDICTED_EVENTS_INDEXES,
    PREDICTION_OUTCOMES_INDEXES,
    INGESTION_STATE_INDEXES,
    ALL_V22_INDEX_SPECS,
    # Model + bands
    MODEL_VERSION,
    SCORE_BAND_GREEN,
    SCORE_BAND_YELLOW,
    SCORE_BAND_ORANGE,
    SCORE_BAND_RED,
    score_band,
    # Sample-size + confidence thresholds
    MIN_PEER_SAMPLE_SIZE,
    MIN_CONFIDENCE_THRESHOLD,
)
