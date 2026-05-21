"""Phase 1 Week 13-19 PR-A — causal lift matrix.

Final phase of the 19-week Phase 1 roadmap. Computes the joint
distribution between DOB complaint buckets (the cause) and subsequent
ECB violation buckets (the effect) using the Phase 1 Week 1 backfilled
historical data.

For each (complaint_bucket X, violation_bucket Y, window_days W ∈ {30,
60, 90}):

    lift_ratio = P(Y in W days | X complaint) / P(Y in pool baseline)

Output: 300 cells in ``causal_lift_matrix`` (10 buckets × 10 buckets × 3
windows). ``lift_ratio > 1.0`` means the complaint pattern increases
subsequent-violation probability vs the whole-pool baseline.

Locked decisions (operator, Stage 2.A):

  L1 — Windows: 30 / 60 / 90 days.
  L2 — Confidence: HIGH ≥100 BINs, MEDIUM 30-99, LOW <30.
  L3 — Forward only (complaint → violation). No reverse direction.
  L4 — Baseline: whole-pool (``B_y / total_pool``), not conditional on
       "BINs that had any complaint" — simpler operator interpretation.
  L5 — Persist all 300 rows; default API filter applied at the
       endpoint layer (``lift_ratio ≥ 1.5 AND confidence ∈ {HIGH,
       MEDIUM}``). Pass ``?include_all=true`` to bypass.

Date handling — carried forward from PR #33 and PR #39 silent-miss
lessons:

  • ``socrata_complaints_historical.date_entered`` is MM/DD/YYYY text.
    Parse with ``_parse_mmddyyyy``; never lex-compare against ISO or
    YYYYMMDD bounds.
  • ``socrata_ecb_violations_historical.issue_date`` is YYYYMMDD text.
    Use YYYYMMDD bounds for ``$gte`` / ``$lt``; lex-compares as
    chronological for matched-format strings.

Module structure mirrors ``violation_baseline_aggregator.py``:

  • ``_compute_lift_ratio``, ``_resolve_confidence``,
    ``_within_window_days``, ``_parse_mmddyyyy``, ``_parse_yyyymmdd`` —
    pure helpers, directly unit-testable.
  • ``_build_lift_row`` — pure row builder.
  • ``compute_causal_lift_matrix`` — integration driver; pulls
    complaints + violations, classifies, aggregates, writes the 300
    cells.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── Locked constants ──────────────────────────────────────────────


# L1 — three forward-look windows.
WINDOWS_DAYS: Tuple[int, int, int] = (30, 60, 90)

# L2 — confidence cutoffs by complaint-cohort size.
CONF_HIGH: str = "HIGH"
CONF_MEDIUM: str = "MEDIUM"
CONF_LOW: str = "LOW"
_CONF_HIGH_MIN = 100
_CONF_MEDIUM_MIN = 30

# Cap on reported lift_ratio. Without this, very small baselines (e.g.
# 1 BIN out of 5,000 hit by an obscure bucket) inflate the ratio into
# the hundreds and dominate the UI. The cap is loose enough that "real"
# high-signal patterns still surface but bounded enough to keep the
# rendering sane.
LIFT_RATIO_CAP: float = 100.0

# Analysis window: 3 years back from now, minus a 90-day follow-up tail
# so every complaint in the window has the full 90 days of follow-up
# violations available.
_ANALYSIS_LOOKBACK_DAYS = 3 * 365
_FOLLOWUP_TAIL_DAYS = 90


# ── Pure helpers ─────────────────────────────────────────────────


def _compute_lift_ratio(
    *,
    rate_with: float,
    rate_baseline: float,
) -> float:
    """Pure lift formula. Returns:

      • 0.0 when both rates are zero (no signal anywhere).
      • 0.0 when rate_with is 0 but baseline > 0 (perfectly protective).
      • LIFT_RATIO_CAP when baseline is 0 but rate_with > 0 (rare in
        pool, present in cohort).
      • min(rate_with / rate_baseline, LIFT_RATIO_CAP) otherwise.
    """
    if rate_baseline is None or rate_with is None:
        return 0.0
    if rate_baseline <= 0:
        # Both zero → no signal.
        if rate_with <= 0:
            return 0.0
        # Present in cohort but absent from pool → cap rather than +inf.
        return LIFT_RATIO_CAP
    if rate_with <= 0:
        return 0.0
    raw = rate_with / rate_baseline
    if raw > LIFT_RATIO_CAP:
        return LIFT_RATIO_CAP
    return raw


def _resolve_confidence(n_bins_with_complaint: int) -> str:
    """L2 — complaint-cohort size buckets the confidence band."""
    n = int(n_bins_with_complaint or 0)
    if n >= _CONF_HIGH_MIN:
        return CONF_HIGH
    if n >= _CONF_MEDIUM_MIN:
        return CONF_MEDIUM
    return CONF_LOW


def _within_window_days(
    complaint_dt: datetime,
    violation_dt: datetime,
    window_days: int,
) -> bool:
    """L3 — forward-only causal direction. The violation must occur
    AFTER the complaint (delta > 0) AND within window_days. Strictly
    greater-than-zero on the delta so a same-day violation does NOT
    count (we don't know which came first; conservatively excluded)."""
    if complaint_dt is None or violation_dt is None:
        return False
    delta = (violation_dt - complaint_dt).total_seconds() / 86400.0
    if delta <= 0:
        return False
    return delta <= float(window_days)


def _parse_mmddyyyy(s: Optional[str]) -> Optional[datetime]:
    """eabe-havv date_entered → datetime (UTC). MM/DD/YYYY text.
    Returns None on malformed input."""
    if not s or not isinstance(s, str):
        return None
    parts = s.strip().split("/")
    if len(parts) != 3:
        return None
    mm, dd, yyyy = parts
    try:
        return datetime(int(yyyy), int(mm), int(dd), tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_yyyymmdd(s: Optional[str]) -> Optional[datetime]:
    """6bgk-3dad issue_date → datetime (UTC). 8-character YYYYMMDD
    text. Returns None on malformed input."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime(
            int(s[0:4]), int(s[4:6]), int(s[6:8]),
            tzinfo=timezone.utc,
        )
    except (ValueError, TypeError):
        return None


def _build_lift_row(
    *,
    complaint_bucket: str,
    violation_bucket: str,
    window_days: int,
    n_bins_with_complaint: int,
    n_bins_with_subsequent_violation: int,
    n_bins_with_violation_baseline: int,
    total_pool: int,
    computed_at: datetime,
) -> Dict[str, Any]:
    """Construct one causal_lift_matrix row. Pure for testability."""
    if n_bins_with_complaint > 0:
        rate_with = (
            n_bins_with_subsequent_violation / n_bins_with_complaint
        )
    else:
        rate_with = 0.0
    if total_pool > 0:
        rate_baseline = n_bins_with_violation_baseline / total_pool
    else:
        rate_baseline = 0.0
    lift = _compute_lift_ratio(
        rate_with=rate_with, rate_baseline=rate_baseline,
    )
    confidence = _resolve_confidence(n_bins_with_complaint)
    return {
        "complaint_bucket":                  complaint_bucket,
        "violation_bucket":                  violation_bucket,
        "window_days":                       int(window_days),
        "n_bins_with_complaint":             int(n_bins_with_complaint),
        "n_bins_with_subsequent_violation":  int(n_bins_with_subsequent_violation),
        "lift_ratio":                        float(lift),
        "confidence":                        confidence,
        "sample_size":                       int(total_pool),
        "computed_at":                       computed_at,
    }


# ── Public driver ────────────────────────────────────────────────


async def compute_causal_lift_matrix(
    db: Any,
    *,
    run_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """End-to-end causal-lift computation.

    Steps:
      1. Determine analysis window.
      2. Pull all complaints in window; classify per BIN.
      3. Pull all violations in window + 90d follow-up; classify per BIN.
      4. For each BIN, walk each complaint forward and check if any
         violation lands within 30/60/90 days.
      5. Aggregate into the 300 cells.
      6. Replace prior causal_lift_matrix contents in a single batch.
      7. Return telemetry.

    Returns:
      {
        n_rows_written:    int,    # always 300 (full grid)
        n_bins_processed:  int,
        window_start:      datetime UTC,
        window_end:        datetime UTC,
        elapsed_seconds:   float,
      }
    """
    from lib.statistical_engine.violation_taxonomy import (
        BUCKETS,
        classify_complaint,
        classify_violation,
    )

    t_start = time.perf_counter()

    cur_now = run_date or datetime.now(timezone.utc)
    if cur_now.tzinfo is None:
        cur_now = cur_now.replace(tzinfo=timezone.utc)

    complaint_window_end = cur_now - timedelta(days=_FOLLOWUP_TAIL_DAYS)
    complaint_window_start = cur_now - timedelta(days=_ANALYSIS_LOOKBACK_DAYS)
    # For violations we look in [complaint_window_start, cur_now] so
    # any complaint in the window can have its 90-day follow-up checked.
    violation_window_start = complaint_window_start
    violation_window_end = cur_now

    # ── Step 2 — pull complaints ──────────────────────────────────
    # date_entered is MM/DD/YYYY text — cannot filter at Mongo level
    # with a chronological range. Pull all + filter in Python after
    # parsing. Two helpful filters do apply at Mongo level: bin must be
    # non-null, date_entered must be non-null.
    complaints_coll = getattr(db, "socrata_complaints_historical", None)
    crows: List[Dict[str, Any]] = []
    if complaints_coll is not None:
        try:
            crows = await complaints_coll.find(
                {"bin": {"$ne": None}},
                {"bin": 1, "complaint_category": 1, "date_entered": 1},
            ).to_list(length=None)
        except Exception as e:  # pragma: no cover
            logger.warning(
                "[phase1w13] complaints fetch failed: %r", e,
            )
            crows = []

    # Per-BIN map: {bin: {bucket: [dt, dt, ...]}}
    complaints_by_bin: Dict[str, Dict[str, List[datetime]]] = defaultdict(
        lambda: defaultdict(list),
    )
    for c in crows or []:
        bin_id = c.get("bin")
        if not bin_id:
            continue
        dt = _parse_mmddyyyy(c.get("date_entered"))
        if dt is None:
            continue
        if dt < complaint_window_start or dt >= complaint_window_end:
            continue
        bucket = classify_complaint(c.get("complaint_category"))
        complaints_by_bin[bin_id][bucket].append(dt)

    # ── Step 3 — pull violations ──────────────────────────────────
    # issue_date is YYYYMMDD — lex-compares as chronological. Bound at
    # Mongo level for the window.
    violations_coll = getattr(db, "socrata_ecb_violations_historical", None)
    vrows: List[Dict[str, Any]] = []
    if violations_coll is not None:
        vwin_start = violation_window_start.strftime("%Y%m%d")
        vwin_end = violation_window_end.strftime("%Y%m%d")
        try:
            vrows = await violations_coll.find(
                {
                    "bin": {"$ne": None},
                    "issue_date": {"$gte": vwin_start, "$lt": vwin_end},
                },
                {
                    "bin": 1,
                    "issue_date": 1,
                    "violation_type": 1,
                    "violation_description": 1,
                },
            ).to_list(length=None)
        except Exception as e:  # pragma: no cover
            logger.warning(
                "[phase1w13] violations fetch failed: %r", e,
            )
            vrows = []

    # Per-BIN: list of (datetime, bucket).
    violations_by_bin: Dict[str, List[Tuple[datetime, str]]] = defaultdict(list)
    # Also track the set of BINs that experienced any violation in
    # ANY bucket (whole-pool baseline counts: per L4).
    bins_with_violation_per_bucket: Dict[str, Set[str]] = defaultdict(set)
    for v in vrows or []:
        bin_id = v.get("bin")
        if not bin_id:
            continue
        dt = _parse_yyyymmdd(v.get("issue_date"))
        if dt is None:
            continue
        bucket = classify_violation(
            v.get("violation_type"),
            v.get("violation_description"),
        )
        violations_by_bin[bin_id].append((dt, bucket))
        bins_with_violation_per_bucket[bucket].add(bin_id)

    # ── Step 4 — aggregate per-BIN matches into 3-D grid ─────────
    # cell[X][Y][W] = set of BINs that had a complaint X followed by
    # a violation Y within W days.
    cell_bins: Dict[
        str, Dict[str, Dict[int, Set[str]]]
    ] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set)),
    )
    # complaint_bin_count[X] = set of BINs with ≥1 X complaint.
    bins_with_complaint_per_bucket: Dict[str, Set[str]] = defaultdict(set)

    for bin_id, by_bucket in complaints_by_bin.items():
        bin_violations = violations_by_bin.get(bin_id, [])
        for x_bucket, complaint_dts in by_bucket.items():
            bins_with_complaint_per_bucket[x_bucket].add(bin_id)
            # For each complaint date of this bucket on this BIN, find
            # the earliest follow-up violation per (y_bucket, window).
            # We mark cell[X][Y][W] once per BIN; multiple matches
            # within the same BIN do not multi-count (matches the
            # "BIN-level" denominator semantics).
            for c_dt in complaint_dts:
                for v_dt, y_bucket in bin_violations:
                    for w in WINDOWS_DAYS:
                        if _within_window_days(c_dt, v_dt, w):
                            cell_bins[x_bucket][y_bucket][w].add(bin_id)

    # ── Pool size (denominator for whole-pool baseline) ─────────
    # L4 — pool = union of BINs with complaints and BINs with
    # violations in the window. Either side alone is informative for
    # the baseline; the union gives the largest stable denominator.
    total_pool_bins: Set[str] = set(complaints_by_bin.keys())
    total_pool_bins.update(violations_by_bin.keys())
    total_pool = len(total_pool_bins)

    # ── Step 5 — emit 300 rows ────────────────────────────────────
    computed_at = datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    for x in BUCKETS:
        n_x = len(bins_with_complaint_per_bucket.get(x, set()))
        for y in BUCKETS:
            n_y_baseline = len(
                bins_with_violation_per_bucket.get(y, set()),
            )
            for w in WINDOWS_DAYS:
                n_xy_w = len(cell_bins.get(x, {}).get(y, {}).get(w, set()))
                row = _build_lift_row(
                    complaint_bucket=x,
                    violation_bucket=y,
                    window_days=w,
                    n_bins_with_complaint=n_x,
                    n_bins_with_subsequent_violation=n_xy_w,
                    n_bins_with_violation_baseline=n_y_baseline,
                    total_pool=total_pool,
                    computed_at=computed_at,
                )
                rows.append(row)

    # ── Step 6 — replace prior contents atomically (best-effort) ──
    coll = getattr(db, "causal_lift_matrix", None)
    if coll is not None:
        try:
            await coll.delete_many({})
        except Exception as e:  # pragma: no cover
            logger.warning(
                "[phase1w13] delete_many before insert failed: %r", e,
            )
        try:
            await coll.insert_many(rows)
        except Exception as e:  # pragma: no cover
            logger.exception(
                "[phase1w13] insert_many failed: %r", e,
            )

    elapsed = time.perf_counter() - t_start
    logger.info(
        "[phase1w13] causal_lift: %d rows, %d BINs in %.2fs "
        "(window [%s, %s) for complaints)",
        len(rows), total_pool, elapsed,
        complaint_window_start.isoformat(),
        complaint_window_end.isoformat(),
    )

    return {
        "n_rows_written":   len(rows),
        "n_bins_processed": total_pool,
        "window_start":     complaint_window_start,
        "window_end":       complaint_window_end,
        "elapsed_seconds":  elapsed,
    }


# ── Per-project recent-complaint rollup (Phase 1 Week 13-19 PR-B) ──


# Tactical Recommendations support endpoint:
# GET /api/projects/{id}/recent-complaint-buckets returns the project's
# complaints from the last 90 days, classified into the 10 violation
# taxonomy buckets and sorted by count DESC. The FE component fans out
# from this rollup into per-bucket /api/causal-lift queries to surface
# the top recommendation cards.
_RECENT_COMPLAINTS_WINDOW_DAYS = 90


async def _resolve_recent_complaint_buckets(
    db: Any,
    bin_id: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Return ``[{bucket, n_complaints}, ...]`` sorted by count DESC.

    Pulls all complaints for ``bin_id`` (cheap — per-BIN result set is
    small, served by the existing ``complaints_bin_1_date_entered_1``
    index), filters in Python because ``date_entered`` is MM/DD/YYYY
    text (PR #33 lesson — can't lex-compare against ISO bounds), and
    classifies each via ``classify_complaint``.

    Per-complaint accumulation (not per-BIN). 3 complaints with the
    same bucket on the same BIN → ``n_complaints = 3``. Distinct from
    the BIN-level dedup used by ``compute_causal_lift_matrix``.

    Empty / null ``bin_id`` → empty list. Defensive against the
    project-without-BIN case (new projects, projects added before BIN
    resolution lands).
    """
    from collections import Counter
    from lib.statistical_engine.violation_taxonomy import classify_complaint

    if not bin_id:
        return []
    coll = getattr(db, "socrata_complaints_historical", None)
    if coll is None:
        return []

    cur_now = now or datetime.now(timezone.utc)
    if cur_now.tzinfo is None:
        cur_now = cur_now.replace(tzinfo=timezone.utc)
    cutoff = cur_now - timedelta(days=_RECENT_COMPLAINTS_WINDOW_DAYS)

    try:
        rows = await coll.find(
            {"bin": bin_id},
            {"complaint_category": 1, "date_entered": 1},
        ).to_list(length=None)
    except Exception as e:  # pragma: no cover
        logger.warning(
            "[phase1w13b] complaints lookup failed for bin=%r: %r",
            bin_id, e,
        )
        return []

    counter: "Counter[str]" = Counter()
    for r in rows or []:
        dt = _parse_mmddyyyy(r.get("date_entered"))
        if dt is None or dt < cutoff:
            continue
        bucket = classify_complaint(r.get("complaint_category"))
        counter[bucket] += 1

    return [
        {"bucket": b, "n_complaints": int(n)}
        for b, n in counter.most_common()
    ]
