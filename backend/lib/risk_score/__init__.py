"""Phase V2.1 — NYC DOB Risk Score (heuristic v1).

A v2-only feature that synthesizes signals from `dob_logs`,
`logbook_entries` (V2.0), workers, subcontractors, and project
metadata into a single 0-100 risk score with a 95% confidence
interval and per-factor contribution breakdown.

  • schema.py        — collection names, indexes spec, model
                       version constant.
  • heuristic.py     — input collection + scoring + bootstrap CI
                       + factor breakdown.
  • calibration.py   — inspector-review logging + Brier score +
                       ROC-AUC.
  • orchestrator.py  — per-project recalc + daily-tick all-projects
                       runner. Idempotent via the 12h freshness
                       check.

Every consumer surface (endpoints, scheduler tick, FE) is gated by
the `v2_risk_score` feature flag (E1 infra). Flag default OFF; v1
customers see nothing. Inspector-review weight updates are MANUAL
(operator review of aggregate stats) — never auto-applied.
"""

from lib.risk_score.schema import (  # noqa: F401
    RISK_SCORES_COLLECTION,
    RISK_SCORE_REVIEWS_COLLECTION,
    RISK_SCORE_CALIBRATION_COLLECTION,
    RISK_SCORES_INDEXES,
    RISK_SCORE_REVIEWS_INDEXES,
    RISK_SCORE_CALIBRATION_INDEXES,
    MODEL_VERSION,
    SCORE_BAND_GREEN,
    SCORE_BAND_YELLOW,
    SCORE_BAND_ORANGE,
    SCORE_BAND_RED,
    score_band,
)
from lib.risk_score.heuristic import (  # noqa: F401
    WEIGHTS,
    INPUT_KEYS,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_NOISE_SIGMA,
    CONFIDENCE_INTERVAL_PCT,
    gather_inputs,
    score_from_inputs,
    bootstrap_confidence_interval,
    top_contributing_factors,
    calculate_risk_score,
)
from lib.risk_score.calibration import (  # noqa: F401
    log_inspector_review,
    brier_score,
    compute_calibration_stats,
)
from lib.risk_score.orchestrator import (  # noqa: F401
    SCORE_FRESHNESS_HOURS,
    run_risk_score_for_project,
    run_risk_score_for_all_projects,
)
