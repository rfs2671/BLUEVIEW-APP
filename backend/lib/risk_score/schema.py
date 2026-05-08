"""Phase V2.1 — risk_scores collection schema + index specs.

Three collections, all additive (no schema changes to existing
collections):

  risk_scores
    {
      _id, company_id, project_id,
      calculated_at:   datetime (UTC, indexed desc),
      score:           float [0..100],
      confidence_low:  float [0..100]   (95% CI lower bound),
      confidence_high: float [0..100]   (95% CI upper bound),
      contributing_factors: [
        {factor: str, weight: float, value: float,
         contribution: float}
      ],
      model_version:   str (currently "heuristic-v1"),
      inputs_snapshot: dict   (every input value at calc time —
                                used for backtest + audit; NOT
                                used by the live model after
                                write).
    }

  risk_score_reviews
    {
      _id, score_id (-> risk_scores._id),
      project_id, model_version,
      was_high_risk_correct: bool,    (operator's verdict)
      notes: str,
      reviewed_at: datetime (UTC),
      reviewed_by_user_id: str,
    }

  risk_score_calibration
    {
      _id, model_version,
      evaluated_at: datetime,
      sample_size: int,
      brier_score: float,
      roc_auc: float,
      inspector_review_count: int,
      notes: str | None,
    }

Indexes are wired in server.py at startup via
_ensure_index_resilient using the *_INDEXES tuples below.
"""

from __future__ import annotations

# ── Collection names ──────────────────────────────────────────────

RISK_SCORES_COLLECTION              = "risk_scores"
RISK_SCORE_REVIEWS_COLLECTION       = "risk_score_reviews"
RISK_SCORE_CALIBRATION_COLLECTION   = "risk_score_calibration"

# ── Model version constant ────────────────────────────────────────
#
# Bump this when the WEIGHTS dict, the bootstrap parameters, or the
# input gathering logic changes meaningfully. The version string is
# stamped on every risk_scores doc so downstream consumers
# (calibration aggregator, history charts, backtests) can scope
# comparisons to a single version.

MODEL_VERSION = "heuristic-v1"

# ── Score band thresholds ─────────────────────────────────────────
#
# Same color taxonomy used by the FE RiskScoreCard. Centralized here
# so the BE classification (e.g. for notification triggers in a
# future phase) stays consistent with the FE.

SCORE_BAND_GREEN  = "green"   # 0..30
SCORE_BAND_YELLOW = "yellow"  # 31..60
SCORE_BAND_ORANGE = "orange"  # 61..80
SCORE_BAND_RED    = "red"     # 81..100


def score_band(score: float) -> str:
    """Resolve a numeric score to its band label."""
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


# ── Indexes (consumed by server.py startup) ───────────────────────
#
# Format mirrors the existing _ensure_index_resilient call sites
# used by V2.0 logbook: (keys, name, **opts).

RISK_SCORES_INDEXES = (
    # Primary query path: latest score per project (ProjectDetail page).
    {
        "keys": [("company_id", 1), ("project_id", 1), ("calculated_at", -1)],
        "name": "risk_scores_company_project_calculated",
    },
    # History endpoint: time-series for one project, newest first.
    {
        "keys": [("project_id", 1), ("calculated_at", -1)],
        "name": "risk_scores_project_calculated_desc",
    },
    # Calibration aggregator + admin scans.
    {
        "keys": [("model_version", 1), ("calculated_at", -1)],
        "name": "risk_scores_model_calculated",
    },
)

RISK_SCORE_REVIEWS_INDEXES = (
    # Admin calibration query (per-version aggregate).
    {
        "keys": [("model_version", 1), ("reviewed_at", -1)],
        "name": "risk_score_reviews_model_reviewed",
    },
    # One-shot fetch of the review for a specific score doc.
    {
        "keys": [("score_id", 1)],
        "name": "risk_score_reviews_score",
    },
    # Per-project review history.
    {
        "keys": [("project_id", 1), ("reviewed_at", -1)],
        "name": "risk_score_reviews_project_reviewed",
    },
)

RISK_SCORE_CALIBRATION_INDEXES = (
    # One row per (model_version, evaluated_at) — newest-first
    # admin reads.
    {
        "keys": [("model_version", 1), ("evaluated_at", -1)],
        "name": "risk_score_calibration_model_evaluated",
    },
)
