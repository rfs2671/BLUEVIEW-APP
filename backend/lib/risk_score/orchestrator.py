"""Phase V2.1 — risk-score orchestrator.

Two entry points:

  • run_risk_score_for_project(db, project, *, force=False, now=None)
        — single-project recalc. Used by the on-demand
          `POST /risk-score/calculate` endpoint and by the daily
          tick (with `force=False`).

  • run_risk_score_for_all_projects(db, *, now=None)
        — daily 4 AM ET tick wrapper. Iterates every active
          project and calls `run_risk_score_for_project`. Soft-fails
          per-project (one bad doc doesn't kill the run).

Idempotency: calls with `force=False` are no-ops if a score for the
same project already exists with `calculated_at` within
`SCORE_FRESHNESS_HOURS` (default 12h). The daily tick relies on
this to be safe under retries / overlapping ticks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from lib.risk_score.heuristic import (
    INPUT_KEYS,
    WEIGHTS,
    calculate_risk_score,
    gather_inputs,
)
from lib.risk_score.schema import (
    MODEL_VERSION,
    RISK_SCORES_COLLECTION,
)

logger = logging.getLogger(__name__)


# Don't recalculate if the most-recent score is within this window.
# 12h chosen so the 4 AM tick + an ad-hoc operator recalc at noon
# both do real work, but two ticks in the same hour (say a manual
# rerun) don't. Override with `force=True`.
SCORE_FRESHNESS_HOURS = 12


async def _has_recent_score(
    db, *, project_id: str, now: datetime,
) -> bool:
    """Return True iff a risk_scores doc exists for this project
    whose calculated_at is within SCORE_FRESHNESS_HOURS of `now`.
    """
    cutoff = now - timedelta(hours=SCORE_FRESHNESS_HOURS)
    cur = db[RISK_SCORES_COLLECTION].find({
        "project_id": project_id,
        "calculated_at": {"$gte": cutoff},
    }).sort("calculated_at", -1).limit(1)
    async for _doc in cur:
        return True
    return False


async def run_risk_score_for_project(
    db,
    *,
    project: Dict[str, Any],
    force: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Compute and persist one risk-score row.

    Returns the inserted document, or None if skipped due to the
    freshness check.
    """
    cur_now = now or datetime.now(timezone.utc)
    project_id = str(project.get("_id") or project.get("id") or "")
    if not project_id:
        logger.warning("[risk_score] project missing _id/id")
        return None
    company_id = str(project.get("company_id") or "")

    if not force and await _has_recent_score(
        db, project_id=project_id, now=cur_now,
    ):
        return None

    inputs = await gather_inputs(db, project=project, now=cur_now)
    result = calculate_risk_score(inputs)

    doc = {
        "company_id": company_id,
        "project_id": project_id,
        "calculated_at": cur_now,
        "score": result["score"],
        "confidence_low": result["confidence_low"],
        "confidence_high": result["confidence_high"],
        "contributing_factors": result["contributing_factors"],
        "model_version": MODEL_VERSION,
        "inputs_snapshot": {k: inputs.get(k, 0.0) for k in INPUT_KEYS},
        "weights_snapshot": dict(WEIGHTS),
    }

    res = await db[RISK_SCORES_COLLECTION].insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


async def run_risk_score_for_all_projects(
    db,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Daily-tick entry point. For every active project, compute a
    score and persist it. Soft-fails per-project so one bad doc
    doesn't kill the whole run.

    Returns a summary dict for logging.
    """
    cur_now = now or datetime.now(timezone.utc)
    summary = {
        "projects_scanned": 0,
        "scores_written": 0,
        "scores_skipped_fresh": 0,
        "errors": 0,
    }
    project_cursor = db.projects.find({
        "status": "active",
        "is_deleted": {"$ne": True},
    })
    async for project in project_cursor:
        summary["projects_scanned"] += 1
        try:
            written = await run_risk_score_for_project(
                db, project=project, force=False, now=cur_now,
            )
            if written is None:
                summary["scores_skipped_fresh"] += 1
            else:
                summary["scores_written"] += 1
        except Exception as e:
            summary["errors"] += 1
            logger.warning(
                f"[risk_score] project {project.get('_id')!r} "
                f"failed: {e!r}",
            )
    logger.info(f"[risk_score] tick complete: {summary}")
    return summary
