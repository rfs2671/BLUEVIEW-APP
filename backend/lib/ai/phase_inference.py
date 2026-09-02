"""PR #48 — weekly Gemini phase inference.

Replaces the manual phase dropdown (PR #36/#37) with weekly Gemini
inference from existing daily-log fields. The project phase is derived
automatically from ``work_performed``, ``subcontractor_cards``,
``notes`` and ``worker_count`` across the last 7 days — fields field
crews already enter — so GCs don't maintain yet another field by hand.

Two public surfaces:

  • ``infer_phase_for_project(db, project, now)`` — per-project Gemini
    call. Returns the storage dict or None (no logs / no key / Gemini
    failure / invalid enum).
  • ``run_weekly_phase_inference(db, now)`` — cron driver. Iterates
    active projects, persists results to
    ``db.projects.ai_inferred_phase``, tolerates per-project failures.

Cadence: Sunday 4:00 AM ET weekly cron (registered in server.py),
~23h ahead of the Monday 3:00 AM baseline_aggregator so downstream
consumers wake up with fresh phase signals.

The google-genai SDK (already pinned in requirements.txt) is imported
at module level so tests can patch ``phase_inference.genai``. Structured
JSON output constrains the model to one of the 6 phase enum values.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# gemini-3.5-flash-lite. gemini-2.5-flash-lite was RETIRED under this key and
# every call returned 404 NOT_FOUND: "no longer available to new users. Please
# update your code to use models/gemini-3.5-flash-lite". The env var is unset in
# production (checked 2026-08-28), so this default IS the live value -- there is
# no override to change and nothing else to update.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Six locked lifecycle phases — must match the Literal[...] enum in
# server.py:DailyLogCreate and the PHASE_TO_RATIO keys in
# live_mutation.py.
PHASE_ENUM: List[str] = [
    "foundation", "superstructure", "interior",
    "mep", "finishes", "closeout",
]

# Gemini structured-output schema. response_schema + response_mime_type
# constrain the model to emit exactly this shape; phase is enum-bounded.
PHASE_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "phase":     {"type": "string", "enum": PHASE_ENUM},
        "reasoning": {"type": "string"},
    },
    "required": ["phase"],
}

# Gemini input window — last 7 days of daily logs (L7). Cron runs
# Sunday 4am and looks back 7 days.
_WINDOW_DAYS = 7

# Field-length caps for the prompt — keep token count low + bounded.
_WORK_MAX = 300
_NOTES_MAX = 200

_PROMPT_TEMPLATE = """You are analyzing NYC construction site daily logs to determine the project's current phase.

Project lifecycle phases (in order):
1. foundation: excavation, footings, foundation pour
2. superstructure: framing, structural steel, floor slabs
3. interior: drywall, partitions, rough trades start
4. mep: mechanical/electrical/plumbing rough-in
5. finishes: paint, flooring, fixtures, tile
6. closeout: punch list, inspections, certificate of occupancy

Below are the last 7 days of daily logs for this project. Determine the CURRENT phase based on the work performed, subcontractor mix, and safety conditions.

Logs:
{logs}

Return JSON: {{"phase": <one of the 6 values>, "reasoning": <brief explanation>}}
"""


def _format_logs_for_prompt(logs: List[Dict[str, Any]]) -> str:
    """Format daily logs into a compact text block for the prompt.

    Each log becomes one pipe-delimited line. work_performed is capped
    at 300 chars, notes at 200, to bound token count. Empty
    subcontractor lists omit the Trades segment entirely."""
    if not logs:
        return "(no logs in window)"

    formatted: List[str] = []
    for log in logs:
        parts = [f"Date: {log.get('date', 'unknown')}"]
        work = log.get("work_performed")
        if work:
            parts.append(f"Work: {work[:_WORK_MAX]}")
        notes = log.get("notes")
        if notes:
            parts.append(f"Notes: {notes[:_NOTES_MAX]}")
        subs_raw = log.get("subcontractor_cards") or []
        if subs_raw:
            subs = ", ".join(
                (c.get("company_name", "") or c.get("trade", ""))
                for c in subs_raw
                if (c.get("company_name") or c.get("trade"))
            )
            if subs:
                parts.append(f"Trades: {subs}")
        workers = log.get("worker_count")
        if workers:
            parts.append(f"Workers: {workers}")
        formatted.append(" | ".join(parts))

    return "\n\n".join(formatted)


async def infer_phase_for_project(
    db: Any,
    project: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Infer current phase via Gemini from last 7 days of daily logs.

    Returns a storage dict:
      {phase, inferred_at, source_log_count,
       source_log_window_start, source_log_window_end}
    OR None if:
      • GEMINI_API_KEY unset
      • project has no _id
      • no daily logs in the 7-day window
      • Gemini call raises
      • Gemini returns a phase outside the 6-value enum
    """
    if not GEMINI_API_KEY:
        return None

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window_start = now - timedelta(days=_WINDOW_DAYS)

    project_id = str(project.get("_id") or "")
    if not project_id:
        return None

    # Query last 7 days of logs (date stored as YYYY-MM-DD ISO text).
    logs = await db.daily_logs.find(
        {
            "project_id": project_id,
            "is_deleted": {"$ne": True},
            "date": {"$gte": window_start.strftime("%Y-%m-%d")},
        },
        {
            "work_performed": 1,
            "notes": 1,
            "subcontractor_cards": 1,
            "worker_count": 1,
            "date": 1,
        },
    ).sort("date", -1).to_list(length=50)

    if not logs:
        return None

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = _PROMPT_TEMPLATE.format(
            logs=_format_logs_for_prompt(logs),
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PHASE_RESPONSE_SCHEMA,
                temperature=0,
            ),
        )
        parsed = json.loads(response.text)
        phase = parsed.get("phase")
        if phase not in PHASE_ENUM:
            logger.warning(
                "Gemini returned invalid phase=%r for project %s",
                phase, project_id,
            )
            return None
        return {
            "phase":                   phase,
            "inferred_at":             now,
            "source_log_count":        len(logs),
            "source_log_window_start": window_start,
            "source_log_window_end":   now,
        }
    except Exception as e:  # noqa: BLE001 — per-project tolerance (L8)
        logger.error(
            "Gemini phase inference failed for project %s: %r",
            project_id, e,
        )
        return None


async def run_weekly_phase_inference(
    db: Any,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Weekly cron driver. Iterates active projects, infers phase per
    project, persists results to ``db.projects.ai_inferred_phase``.

    Per-project failure tolerance (L8): an exception on one project is
    logged + counted, then the loop continues. A None return (no logs /
    no key / Gemini failure / invalid enum) leaves the project's
    existing ``ai_inferred_phase`` untouched — prior value preserved.

    Returns:
      {n_projects_processed, n_phase_updated, n_failed, elapsed_seconds}
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    t0 = time.perf_counter()

    projects = await db.projects.find(
        {"is_deleted": {"$ne": True}},
        {"_id": 1, "name": 1},
    ).to_list(length=None)

    n_processed = 0
    n_updated = 0
    n_failed = 0

    for project in projects or []:
        n_processed += 1
        try:
            result = await infer_phase_for_project(db, project, now=now)
            if result:
                await db.projects.update_one(
                    {"_id": project["_id"]},
                    {"$set": {"ai_inferred_phase": result, "updated_at": now}},
                )
                n_updated += 1
            # result is None → leave ai_inferred_phase at prior value.
        except Exception as e:  # noqa: BLE001 — per-project tolerance
            n_failed += 1
            logger.error(
                "Phase inference failed for project %s: %r",
                project.get("_id"), e,
            )

    elapsed = time.perf_counter() - t0
    return {
        "n_projects_processed": n_processed,
        "n_phase_updated":      n_updated,
        "n_failed":             n_failed,
        "elapsed_seconds":      elapsed,
    }
