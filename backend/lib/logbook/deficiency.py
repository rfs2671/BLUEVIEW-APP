"""Phase V2.0 — daily-log deficiency rules engine.

Scans completed daily_logs and flags missing-but-required fields
or unmet workflow requirements as logbook_entries with
status=deficient. Pure rules — each rule lives in its own
function so tests can exercise positive + negative cases
deterministically.

Why this is separate from missing_detector: a `missing` row says
"there's no daily_log at all for this date". A `deficient` row
says "there IS a daily_log, but it doesn't meet the bar." Two
different remediation paths for the operator.

Pipeline contract:

  detect_deficiencies(daily_log, project, *, today=None,
                      project_workers=None, project_subs=None)
      → list of {rule, reason} dicts (one per detected deficiency)

The detector is pure (no DB access). The orchestrator below is
the cron-tick entry point that loads daily_logs + workers + subs
in a batch, runs the detector, and upserts logbook_entries.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from lib.logbook.schema import (
    CATEGORY_DEFICIENCY,
    SOURCE_AUTO_DETECTED,
    STATUS_DEFICIENT,
    str_to_date,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Individual rules (pure)
# ──────────────────────────────────────────────────────────────────


def rule_missing_manpower(daily_log: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Daily log MUST report worker_count > 0 OR explicitly note
    a no-work day. Worker_count==0 with no explanation is a
    deficiency (DOB inspectors flag this — the project either had
    workers and didn't count them, or wasn't really a "work day"
    and the log shouldn't have been written)."""
    count = daily_log.get("worker_count")
    if count is None or (isinstance(count, int) and count <= 0):
        notes = (daily_log.get("notes") or "").lower()
        work_performed = (daily_log.get("work_performed") or "").lower()
        # An explicit "no work today" / "rain day" / "shutdown"
        # marker in notes/work_performed waives the rule.
        for marker in ("no work", "rain day", "shutdown", "site closed", "stop work"):
            if marker in notes or marker in work_performed:
                return None
        return {
            "rule": "missing_manpower",
            "reason": "worker_count is 0 or missing with no no-work marker",
        }
    return None


def rule_missing_weather(daily_log: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Weather conditions are a DOB-required field on daily logs
    (NYC DOB Daily Log Form §A4). The legacy `weather` string is
    accepted; the newer split fields (weather_temp + weather_wind +
    weather_condition) also satisfy. Both empty = deficient."""
    legacy = (daily_log.get("weather") or "").strip()
    if legacy:
        return None
    has_split = any(
        (daily_log.get(k) or "").strip()
        for k in ("weather_temp", "weather_wind", "weather_condition")
    )
    if has_split:
        return None
    return {
        "rule": "missing_weather",
        "reason": "no weather field populated (legacy or split)",
    }


def rule_missing_trade_work(daily_log: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """`work_performed` describes which trades did what. Empty
    string = deficient. `notes` is a free-form catchall and does
    NOT substitute (DOB inspectors look for the structured field)."""
    work = (daily_log.get("work_performed") or "").strip()
    if work:
        return None
    return {
        "rule": "missing_trade_work",
        "reason": "work_performed field is empty",
    }


def rule_subcontractor_without_insurance(
    daily_log: Dict[str, Any],
    *,
    project_subs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[Dict[str, str]]:
    """If the daily log lists subcontractors on site
    (subcontractor_cards[]) AND any of them have no certificate of
    insurance on file in the project's sub roster, that's a
    deficiency. NYC GCs are liable for sub COI compliance.

    Soft-fail: if `project_subs` isn't supplied, the rule abstains
    rather than guessing — the caller is expected to provide the
    list when the rule is meaningful (orchestrator does)."""
    if project_subs is None:
        return None
    sub_cards = daily_log.get("subcontractor_cards") or []
    if not sub_cards:
        return None
    by_name: Dict[str, Dict[str, Any]] = {}
    for s in project_subs:
        name = (s.get("name") or s.get("company_name") or "").strip().lower()
        if name:
            by_name[name] = s

    missing = []
    for card in sub_cards:
        sub_name = (card.get("company") or card.get("company_name") or "").strip().lower()
        if not sub_name:
            continue
        sub_doc = by_name.get(sub_name)
        if not sub_doc:
            # Sub on site but not in the company's roster — also a
            # deficiency, but a different rule. We just flag the
            # COI angle here; the missing-roster case is a
            # candidate for a future rule.
            continue
        if not sub_doc.get("coi_on_file"):
            missing.append(card.get("company") or sub_name)
    if missing:
        return {
            "rule": "subcontractor_without_insurance",
            "reason": (
                "subcontractor(s) on site without COI on file: "
                + ", ".join(missing[:5])
            ),
        }
    return None


def rule_inspection_window_missed(
    daily_log: Dict[str, Any],
    *,
    project: Dict[str, Any],
    today: Optional[date] = None,
) -> Optional[Dict[str, str]]:
    """A DOB-required inspection (e.g. concrete pour, fire-rated
    assembly) was scheduled in `project.inspection_windows[]` and
    the daily log DOESN'T mark it as inspected, AND the window has
    expired.

    Project schema for inspection windows (used by this rule):

        project.inspection_windows = [
            {"label": str, "by_date": "YYYY-MM-DD", "completed": bool}, ...
        ]

    This rule abstains when the project doesn't carry inspection
    windows (most projects don't yet — feature flag gates the
    surface).
    """
    windows = project.get("inspection_windows") or []
    if not windows:
        return None
    cur_today = today or datetime.now(timezone.utc).date()
    log_date = str_to_date(daily_log.get("date") or "")
    if log_date is None:
        return None
    overdue = []
    for w in windows:
        if w.get("completed"):
            continue
        by = str_to_date(w.get("by_date") or "")
        if by is None:
            continue
        if cur_today > by and log_date >= by:
            overdue.append(w.get("label") or "(unnamed)")
    if overdue:
        return {
            "rule": "inspection_window_missed",
            "reason": (
                "inspection deadline passed without completion: "
                + ", ".join(overdue[:5])
            ),
        }
    return None


# Ordered tuple — same order is reflected in tests so a regression
# that drops one rule becomes obvious.
ALL_RULES = (
    rule_missing_manpower,
    rule_missing_weather,
    rule_missing_trade_work,
    # The next two require external context; the orchestrator
    # supplies it via kwargs.
)


# ──────────────────────────────────────────────────────────────────
# Detector (pure)
# ──────────────────────────────────────────────────────────────────


def detect_deficiencies(
    daily_log: Dict[str, Any],
    project: Dict[str, Any],
    *,
    today: Optional[date] = None,
    project_subs: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """Run every rule against one daily_log. Returns a list of
    `{rule, reason}` dicts — one per detected deficiency. Empty
    list = clean.
    """
    out: List[Dict[str, str]] = []
    for fn in ALL_RULES:
        try:
            r = fn(daily_log)
        except Exception as e:
            logger.warning(f"[deficiency] rule {fn.__name__} raised: {e!r}")
            continue
        if r:
            out.append(r)

    # Rules that need external context — call separately so tests
    # can assert each in isolation.
    try:
        r = rule_subcontractor_without_insurance(
            daily_log, project_subs=project_subs,
        )
        if r:
            out.append(r)
    except Exception as e:
        logger.warning(
            f"[deficiency] rule_subcontractor_without_insurance "
            f"raised: {e!r}",
        )

    try:
        r = rule_inspection_window_missed(
            daily_log, project=project, today=today,
        )
        if r:
            out.append(r)
    except Exception as e:
        logger.warning(
            f"[deficiency] rule_inspection_window_missed raised: {e!r}",
        )

    return out


# ──────────────────────────────────────────────────────────────────
# Orchestrator (writes logbook_entries)
# ──────────────────────────────────────────────────────────────────


async def upsert_deficiency_entries(
    db,
    *,
    daily_log: Dict[str, Any],
    project: Dict[str, Any],
    deficiencies: List[Dict[str, str]],
    now: Optional[datetime] = None,
) -> int:
    """Upsert a logbook_entry per detected deficiency. Returns
    the count written.

    Dedupe key: (project_id, entry_date, category=deficiency,
    deficiency_reason). Same rule re-firing on the same
    daily_log produces no duplicate.
    """
    if not deficiencies:
        return 0
    project_id = str(project.get("_id") or project.get("id") or "")
    company_id = str(project.get("company_id") or "")
    entry_date = (daily_log.get("date") or "")[:10]
    if not entry_date:
        return 0
    cur_now = now or datetime.now(timezone.utc)

    written = 0
    for d in deficiencies:
        rule = d.get("rule") or ""
        reason = d.get("reason") or ""
        key_reason = f"{rule}: {reason}"
        try:
            await db.logbook_entries.update_one(
                {
                    "project_id": project_id,
                    "entry_date": entry_date,
                    "category": CATEGORY_DEFICIENCY,
                    "deficiency_reason": key_reason,
                },
                {
                    "$set": {
                        "company_id": company_id,
                        "project_id": project_id,
                        "entry_date": entry_date,
                        "category": CATEGORY_DEFICIENCY,
                        "status": STATUS_DEFICIENT,
                        "source": SOURCE_AUTO_DETECTED,
                        "linked_dob_log_ids": [],
                        "deficiency_reason": key_reason,
                        "attestation_data": None,
                        "updated_at": cur_now,
                    },
                    "$setOnInsert": {
                        "created_at": cur_now,
                        "created_by_user_id": None,
                    },
                },
                upsert=True,
            )
            written += 1
        except Exception as e:
            logger.warning(
                f"[deficiency] upsert failed project={project_id} "
                f"date={entry_date} rule={rule}: {e!r}",
            )
    return written


async def run_deficiency_detector_for_all_projects(
    db,
    *,
    now: Optional[datetime] = None,
    lookback_days: int = 30,
) -> Dict[str, int]:
    """Cron-tick entry point. For every active project, scans
    daily_logs in the lookback window, runs the rule engine on
    each, upserts deficiency entries.

    Soft-fails per-project so one bad doc doesn't kill the whole
    run.
    """
    cur_now = now or datetime.now(timezone.utc)
    cutoff_date = (cur_now.date() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    summary = {
        "projects_scanned": 0,
        "logs_scanned": 0,
        "deficiencies_written": 0,
        "errors": 0,
    }
    project_cursor = db.projects.find({
        "status": "active",
        "is_deleted": {"$ne": True},
    })
    async for project in project_cursor:
        summary["projects_scanned"] += 1
        project_id = str(project.get("_id"))
        # Pull subs once per project — used by the COI rule.
        try:
            subs = await db.subcontractors.find(
                {"company_id": project.get("company_id")},
            ).to_list(500)
        except Exception:
            subs = []

        log_cursor = db.daily_logs.find({
            "project_id": project_id,
            "is_deleted": {"$ne": True},
            "date": {"$gte": cutoff_date},
        })
        async for log in log_cursor:
            summary["logs_scanned"] += 1
            try:
                deficiencies = detect_deficiencies(
                    log, project,
                    today=cur_now.date(),
                    project_subs=subs,
                )
                if deficiencies:
                    n = await upsert_deficiency_entries(
                        db,
                        daily_log=log, project=project,
                        deficiencies=deficiencies, now=cur_now,
                    )
                    summary["deficiencies_written"] += n
            except Exception as e:
                summary["errors"] += 1
                logger.warning(
                    f"[deficiency] log failed project={project_id} "
                    f"log_id={log.get('_id')}: {e!r}",
                )

    logger.info(f"[deficiency] tick complete: {summary}")
    return summary


# ──────────────────────────────────────────────────────────────────
# Post-save hook (called from create_daily_log)
# ──────────────────────────────────────────────────────────────────


async def run_deficiency_check_post_save(
    db,
    *,
    daily_log: Dict[str, Any],
    project: Dict[str, Any],
    now: Optional[datetime] = None,
) -> int:
    """Hook called immediately after create_daily_log writes a
    new daily_log. Loads the project's subs (one query) and runs
    the rules. Wrapped in try/except by the caller — never blocks
    the daily_log save."""
    cur_now = now or datetime.now(timezone.utc)
    try:
        subs = await db.subcontractors.find(
            {"company_id": project.get("company_id")},
        ).to_list(500)
    except Exception:
        subs = []
    deficiencies = detect_deficiencies(
        daily_log, project,
        today=cur_now.date(),
        project_subs=subs,
    )
    if not deficiencies:
        return 0
    return await upsert_deficiency_entries(
        db,
        daily_log=daily_log, project=project,
        deficiencies=deficiencies, now=cur_now,
    )
