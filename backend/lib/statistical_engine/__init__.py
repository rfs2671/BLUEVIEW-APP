"""Phase V2.3 — Statistical Risk Engine + Event Predictor.

V2.3 architecture: lazy Socrata queries replace the V2.2 local
nyc_* mirror. No backfill cron, no weekly ingest, no
statistical_baselines pre-aggregation cache. Per-project peer
stats are computed once at creation, cached on the project doc,
and incrementally refreshed every 14 days.

This is the post-Commit-3 surface. All four consumer modules
(baselines / triggers / score / calibration) now query Socrata
lazily via the shared ``SocrataClient`` instead of reading from
the V2.2 local mirror. ``peer_stats_cache`` lives on each project
document with a 14-day staleness window.

  • schema.py        — model version + score bands + predicted_events /
                       prediction_outcomes index specs (only).
  • utils.py         — BBL synthesis + normalization (only).
                       Transitional NYC_* collection-name constants
                       deleted in Commit 3.
  • socrata_client.py — async Socrata query wrapper over
                       ServerHttpClient (retry/backoff + SoQL
                       construction + pagination + dataset-id
                       constants).
  • baselines.py     — V2.3: lazy peer-comparison + 14-day cache
                       lifecycle. compute_peer_stats_full,
                       refresh_peer_stats_incremental,
                       count_own_building_events, and the
                       cache-aware compare_project_to_peers.
  • triggers.py      — V2.3: 8 trigger detectors. gather_trigger_inputs
                       now takes a SocrataClient.
  • score.py         — V2.3: recompute_and_persist takes an
                       optional SocrataClient (defaults to inline
                       construction so server.py doesn't change).
  • calibration.py   — V2.3: outcome attribution via lazy Socrata
                       queries keyed on the new TRIGGER_EVIDENCE_DATASET
                       mapping.
  • prewarm.py       — V2.3 Commit 4: background pre-warm of
                       peer_stats_cache fired by server.py on
                       project creation. compare_project_to_peers
                       grew pending/failed/24h-TTL state guards
                       in the same commit.
  • refresh_cron.py  — V2.3 Commit 5: stagger-paced refresh sweep
                       run every 15 min by APScheduler. Three
                       eligibility classes (stale-ready,
                       failed-past-24h, orphan-pending-past-15min)
                       with explicit per-status routing.
  • predictions.py   — V2.3 Commit 6: event-driven predictive
                       inspection surfacing. Hooked from the
                       311 poll on truly-new + action-severity
                       complaints. Similar-case correlation
                       against historical 311 + DOB inspections
                       → display message + ≥70% confidence
                       store. Plus a 30-min resolution sweep
                       and a daily cleanup at 03:45 ET.
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
    # PR #14C Q7 lock — peer_bbls retired alongside the V2.3 4-tier
    # ladder. Cohort discovery now goes through compute_cohort_for_project.
    compare_project_to_peers,
    compute_peer_stats_full,
    refresh_peer_stats_incremental,
    count_own_building_events,
    PEER_STATS_FRESH_DAYS,
    PEER_STATS_LOOKBACK_DAYS,
    PEER_STATS_COMPUTE_TIMEOUT_SECONDS,
    PEER_STATS_FAILED_RETRY_TTL_HOURS,
    # PR #14B — cohort-aware peer comparison
    PEER_STATS_COHORT_TTL_DAYS,
    compute_cohort_for_project,
    # PR #14C — cohort wiring + schema-version invalidation
    PR14C_SCHEMA_VERSION,
    # PR #14D — cohort cap for PLUTO BIN→BBL join
    COHORT_MAX_PEERS_FOR_PLUTO_JOIN,
    # PR #14E — Unified Cohort: Modern primary + Legacy fallback
    PR14E_SCHEMA_VERSION,
    PR14E_MODERN_COHORT_FLOOR,
    PR14E_LEGACY_WINDOW_START_ISO,
    PR14E_LEGACY_WINDOW_END_ISO,
    PR14E_MODERN_WINDOW_MONTHS,
    DATASET_DOB_C_OF_O,
    # PR #14F — BIS MDY date parser (Stage 10 lex-comparison fix)
    _parse_bis_mdy_date,
    # PR #14G — PLUTO bbl format normalization (Stage 10 zero-cohort fix)
    _normalize_pluto_bbl,
)
from lib.statistical_engine.prewarm import (  # noqa: F401
    prewarm_peer_stats,
    PREWARM_TIMEOUT_SECONDS,
    ERROR_KIND_TIMEOUT,
    ERROR_KIND_SOCRATA,
    ERROR_KIND_UNEXPECTED,
    # PR #14B — auto-classification trigger
    maybe_classify_project_dob_type,
)
# PR #14B — cohort spec + parser + classifier (new modules)
from lib.statistical_engine.cohort_config import (  # noqa: F401
    COHORT_CONFIG,
    compute_tolerance_band,
)
from lib.statistical_engine.dob_now_parser import (  # noqa: F401
    parse_dob_now_description,
)
from lib.statistical_engine.dob_classifier import (  # noqa: F401
    fetch_project_dob_classification,
)
from lib.statistical_engine.refresh_cron import (  # noqa: F401
    refresh_stale_peer_stats_caches,
    REFRESH_BATCH_SIZE,
    REFRESH_TICK_MINUTES,
    REFRESH_COMPUTE_TIMEOUT_SECONDS,
    ORPHAN_PENDING_THRESHOLD_MINUTES,
)
from lib.statistical_engine.predictions import (  # noqa: F401
    predict_inspection_from_complaint,
    try_predict_inspection_from_complaint,
    sweep_prediction_resolutions,
    opportunistic_resolution_check,
    cleanup_resolved_predictions,
    PREDICTION_CONFIDENCE_THRESHOLD,
    PREDICTION_LOOKBACK_YEARS,
    PREDICTION_INSPECTION_WINDOW_DAYS,
    PREDICTION_MIN_SAMPLE_SIZE,
    PREDICTION_MIN_INSPECTION_RATE,
    PREDICTION_COMPUTE_TIMEOUT_SECONDS,
    RESOLVED_PREDICTION_RETENTION_DAYS,
    PREDICTION_METHOD,
)
from lib.statistical_engine.utils import (  # noqa: F401
    _construct_bbl_from_components,
    normalize_bbl,
)
from lib.statistical_engine.socrata_client import (  # noqa: F401
    SocrataClient,
    SocrataQueryError,
    ALL_DATASET_IDS,
    DATASET_DOB_VIOLATIONS,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_PERMITS,
    DATASET_COMPLAINTS_311,
    DATASET_ECB_VIOLATIONS,
    DATASET_HPD_VIOLATIONS,
    DATASET_PLUTO,
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
