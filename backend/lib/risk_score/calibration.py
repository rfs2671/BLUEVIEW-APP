"""Phase V2.1 — risk-score calibration framework.

Inspector reviews are logged via `log_inspector_review`; aggregate
stats are computed lazily by `compute_calibration_stats`. Weight
updates are MANUAL (operator reads the stats, edits
heuristic.py::WEIGHTS, bumps schema.py::MODEL_VERSION). Auto-
update would let a noisy inspector ("I like this GC, mark them
OK") corrupt the model. Human in loop.

────────────────────────────────────────────────────────────────────
Brier score
────────────────────────────────────────────────────────────────────

For each review, we have:
  • predicted probability "is high risk" — derived from the score
    at review time, normalized to [0, 1] as `score / 100`
  • observed outcome (was the score correct?) — operator-supplied
    boolean `was_high_risk_correct`

Convention:
  • If the score was ≥61 (orange / red bands), the model
    "predicted high risk". `was_high_risk_correct=True` means the
    prediction matched reality (truly high risk); False means it
    over-predicted.
  • If the score was ≤60 (green / yellow), the model
    "predicted low risk". `was_high_risk_correct` is reused —
    True means the model was right (truly low risk),
    False means it under-predicted.

Brier = mean((predicted_prob - observed_label)^2). Lower is better.
0.0 = perfect; 0.25 = chance.

────────────────────────────────────────────────────────────────────
ROC-AUC
────────────────────────────────────────────────────────────────────

Needs both positive and negative examples. We treat a review as a
positive example (label=1) when the operator said it was truly
high-risk and the model said yes, OR when the operator said it was
NOT truly low-risk and the model said no — i.e., the model's
prediction direction was correct. For ranking we use the raw score.
ROC-AUC is computed by counting concordant pairs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from lib.risk_score.schema import (
    MODEL_VERSION,
    RISK_SCORES_COLLECTION,
    RISK_SCORE_REVIEWS_COLLECTION,
)

logger = logging.getLogger(__name__)


HIGH_RISK_THRESHOLD = 61   # orange band onwards


# ── Inspector review logging ──────────────────────────────────────


async def log_inspector_review(
    db,
    *,
    score_id: str,
    project_id: str,
    was_high_risk_correct: bool,
    notes: Optional[str],
    reviewed_by_user_id: Optional[str],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Persist an inspector review against an existing risk_scores
    row. Returns the inserted document.

    Idempotency note: we do NOT dedupe on score_id. Two reviews for
    the same score (different inspectors, or one operator changing
    their mind) are both kept — the calibration aggregator picks
    them up as separate samples. This is intentional; reviewer
    disagreement is signal we want to surface, not suppress.
    """
    cur_now = now or datetime.now(timezone.utc)
    # Resolve the score doc to capture its model_version (so a
    # later WEIGHTS rev doesn't retro-mislabel old reviews).
    score_doc = await db[RISK_SCORES_COLLECTION].find_one(
        {"_id": score_id},
    )
    if score_doc is None:
        # Try ObjectId conversion as a fallback — older test
        # fixtures store ObjectIds. Soft-fail to None model_version
        # rather than crashing the endpoint.
        try:
            from bson import ObjectId  # type: ignore
            score_doc = await db[RISK_SCORES_COLLECTION].find_one(
                {"_id": ObjectId(score_id)},
            )
        except Exception:
            score_doc = None
    model_version = (
        (score_doc or {}).get("model_version") or MODEL_VERSION
    )
    record = {
        "score_id": score_id,
        "project_id": project_id,
        "model_version": model_version,
        "was_high_risk_correct": bool(was_high_risk_correct),
        "notes": notes or "",
        "reviewed_at": cur_now,
        "reviewed_by_user_id": reviewed_by_user_id or "",
    }
    res = await db[RISK_SCORE_REVIEWS_COLLECTION].insert_one(record)
    record["_id"] = res.inserted_id
    return record


# ── Brier score ───────────────────────────────────────────────────


def brier_score(
    samples: List[Dict[str, Any]],
) -> float:
    """Compute the Brier score on a list of samples. Each sample
    must have:
      • predicted_prob: float in [0, 1]
      • observed_label: 0 or 1

    Returns 0.0 if `samples` is empty (caller should check
    sample_size separately).
    """
    if not samples:
        return 0.0
    total = 0.0
    n = 0
    for s in samples:
        pred = float(s.get("predicted_prob") or 0.0)
        obs = float(s.get("observed_label") or 0.0)
        total += (pred - obs) ** 2
        n += 1
    return total / n if n else 0.0


def roc_auc(
    samples: List[Dict[str, Any]],
) -> float:
    """ROC-AUC via concordant-pair counting. Each sample needs
    `predicted_prob` (the model's continuous output) and
    `observed_label` (0 or 1). With only one class present the AUC
    is undefined; we return 0.5 (chance) as a graceful fallback —
    same convention as scikit-learn's `roc_auc_score` does NOT
    use, but it's clearer here than raising.
    """
    if not samples:
        return 0.5
    positives = [s for s in samples if int(s.get("observed_label") or 0) == 1]
    negatives = [s for s in samples if int(s.get("observed_label") or 0) == 0]
    if not positives or not negatives:
        return 0.5
    concordant = 0.0
    total_pairs = 0
    for p in positives:
        for n in negatives:
            total_pairs += 1
            if float(p.get("predicted_prob") or 0.0) > float(n.get("predicted_prob") or 0.0):
                concordant += 1.0
            elif float(p.get("predicted_prob") or 0.0) == float(n.get("predicted_prob") or 0.0):
                concordant += 0.5
    return concordant / total_pairs if total_pairs else 0.5


# ── Aggregate calibration stats ───────────────────────────────────


async def compute_calibration_stats(
    db,
    *,
    model_version: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Walk every review for the requested model version, pair it
    with the original risk_scores row (to recover the predicted
    score), and compute Brier + ROC-AUC + counts.

    Returns a dict shaped like a `risk_score_calibration` document
    but does NOT persist it. The admin endpoint may render this
    directly; a future operator-action step can persist a snapshot
    by inserting the dict (with `evaluated_at` set) into the
    `risk_score_calibration` collection.
    """
    cur_now = now or datetime.now(timezone.utc)
    target_version = model_version or MODEL_VERSION

    review_cursor = db[RISK_SCORE_REVIEWS_COLLECTION].find(
        {"model_version": target_version},
    )
    samples: List[Dict[str, Any]] = []
    review_count = 0
    async for review in review_cursor:
        review_count += 1
        score_id = review.get("score_id")
        if not score_id:
            continue
        score_doc = await db[RISK_SCORES_COLLECTION].find_one(
            {"_id": score_id},
        )
        if score_doc is None:
            try:
                from bson import ObjectId  # type: ignore
                score_doc = await db[RISK_SCORES_COLLECTION].find_one(
                    {"_id": ObjectId(score_id)},
                )
            except Exception:
                score_doc = None
        if score_doc is None:
            continue
        score_value = float(score_doc.get("score") or 0.0)
        # Predicted "high risk probability" — we treat the score/100
        # as the calibrated probability of "this site is truly high
        # risk".
        predicted_prob = max(0.0, min(1.0, score_value / 100.0))
        was_correct = bool(review.get("was_high_risk_correct"))
        # Convert "model right/wrong" flag into observed truth:
        #   model said high (≥threshold) and was correct → label=1
        #   model said high (≥threshold) and was wrong   → label=0
        #   model said low  (<threshold) and was correct → label=0
        #   model said low  (<threshold) and was wrong   → label=1
        if score_value >= HIGH_RISK_THRESHOLD:
            observed_label = 1.0 if was_correct else 0.0
        else:
            observed_label = 0.0 if was_correct else 1.0
        samples.append({
            "predicted_prob": predicted_prob,
            "observed_label": observed_label,
        })

    return {
        "model_version": target_version,
        "evaluated_at": cur_now,
        "sample_size": len(samples),
        "brier_score": brier_score(samples),
        "roc_auc": roc_auc(samples),
        "inspector_review_count": review_count,
        "notes": (
            f"computed on demand for model_version={target_version}"
        ),
    }
