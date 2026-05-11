"""Phase V2.3 — Statistical Risk Engine + Event Predictor.

V2.3 architecture: lazy Socrata queries replace the V2.2 local
nyc_* mirror. No backfill cron, no weekly ingest, no
statistical_baselines pre-aggregation cache. Per-project peer
stats are computed once at creation, cached on the project doc,
and incrementally refreshed every 14 days.

This is the post-Commit-1 surface. baselines.py and triggers.py
are still V2.2-shaped internally (they query local mirror
collections that no longer have data); Commit 3 rewrites them
to lazy queries.

  • schema.py        — model version + score bands + predicted_events /
                       prediction_outcomes index specs (only).
                       The nyc_* mirror constants moved to utils.py
                       transitionally; deleted entirely in Commit 3.
  • utils.py         — BBL synthesis + normalization. Holds the
                       transitional collection-name constants.
  • baselines.py     — peer-comparison (V2.2-shaped, rewritten Commit 3).
  • triggers.py      — 8 trigger detectors (V2.2-shaped,
                       rewritten Commit 3).
  • score.py         — risk-score recomputation. Untouched in Commit 1.
  • calibration.py   — outcome attribution. Untouched in Commit 1.
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
from lib.statistical_engine.utils import (  # noqa: F401
    _construct_bbl_from_components,
    normalize_bbl,
)
from lib.statistical_engine.schema import (  # noqa: F401
    # Surviving collection constants
    PREDICTED_EVENTS_COLLECTION,
    PREDICTION_OUTCOMES_COLLECTION,
    # Surviving index specs (consumed by server.py startup)
    PREDICTED_EVENTS_INDEXES,
    PREDICTION_OUTCOMES_INDEXES,
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
