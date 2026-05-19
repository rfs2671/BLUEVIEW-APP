"""Phase 1 Week 1 — 3-year Socrata historical backfill driver.

Resume-capable, idempotent backfill for three datasets into per-dataset
"*_historical" Mongo collections. ONE DATASET PER INVOCATION — operator
authorizes each dataset separately per Gate 4 of the directive.

Datasets (in operator-prescribed order, smallest first):
  1. ecb-violations    (6bgk-3dad)  → socrata_ecb_violations_historical
  2. permits           (rbx6-tga4)  → socrata_permits_historical
  3. complaints        (eabe-havv)  → socrata_complaints_historical

Resume / cursor:
  Each run writes the cursor file `backend/scripts/_backfill_cursor.json`
  after every batch. Re-invoking with the same --dataset resumes from
  the cursor. The cursor file is rejected if its `dataset_id` doesn't
  match --dataset, so a wrong-dataset resume isn't possible.

Idempotency:
  Mongo writes use `update_one(filter, $set, upsert=True)` keyed on the
  per-dataset natural key. Re-running over already-inserted rows is a
  no-op (or, more precisely, an idempotent overwrite of fields that
  haven't changed).

Pagination strategy (per directive):
  • $limit=1000 per batch, $order=<natural_key>, $offset increment.
  • For complaints (high volume): date-window slicing of 30 days,
    iterated chronologically. Each window paginates independently.

BIN filtering:
  The backfill scope is the 5,000-BIN target list produced by
  `_select_backfill_target_bins.py` (output:
  `_backfill_target_bins.json`). The list is chunked (default 200 BINs)
  into IN-clauses to stay under Socrata's WHERE-length budget. Cursor
  tracks (chunk_index, offset) so a mid-chunk restart resumes cleanly.

Per-batch failure recovery:
  A single batch's `SocrataQueryError` or Mongo `BulkWriteError` is
  logged with full traceback + cursor state, then the loop continues
  to the next batch. Failed-row counts are tracked in the cursor.

Logging:
  Standard Python logging → `backend/scripts/_backfill.log` (file) +
  stderr. Per-batch summary on INFO; full tracebacks on ERROR.

Modes:
  • DEFAULT (no flag) — `--dry-run`: NO Socrata calls, NO Mongo writes.
    Prints planned queries, BIN-chunk count, date-window count, sample
    SoQL WHERE clauses. Use this during Gate 1 (no Socrata calls
    allowed). Synthetic-data verification of pagination/cursor/retry
    logic happens via the test harness, not this CLI.
  • `--execute` — Real Socrata calls + real Mongo upserts. Use only
    after operator authorizes Gate 4 for the specific --dataset.

Usage (operator workflow):
  # Gate 1 — print the plan; safe to run pre-merge (no network)
  python -m scripts.socrata_3year_backfill \
      --dataset ecb-violations

  # Gate 4 — actual backfill (operator-authorized, one dataset)
  python -m scripts.socrata_3year_backfill \
      --dataset ecb-violations --execute

  # Resume after interruption — same command resumes from cursor
  python -m scripts.socrata_3year_backfill \
      --dataset ecb-violations --execute

Exit codes:
  0  — backfill ran to completion (or no work remaining)
  1  — runtime failure (unrecoverable: cursor mismatch, Mongo unreach,
       too-many-consecutive-failures circuit breaker tripped)
  2  — bad invocation (missing args/env)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.server_http import ServerHttpClient  # noqa: E402
from lib.statistical_engine.socrata_client import (  # noqa: E402
    SocrataClient,
    SocrataQueryError,
)


# ── Paths + constants ─────────────────────────────────────────────

CURSOR_PATH = _HERE / "_backfill_cursor.json"
TARGET_BINS_PATH = _HERE / "_backfill_target_bins.json"
LOG_PATH = _HERE / "_backfill.log"

# 3-year window. Computed at process start so a long-running backfill
# uses one consistent cutoff (won't drift mid-run).
BACKFILL_WINDOW_YEARS = 3

# BIN-list IN-clause chunk. Socrata SoQL WHERE clauses have a length
# budget around 16 KB; 200 BINs × ~10 chars each + quoting ≈ 2.5 KB
# fits comfortably and keeps per-query response shape reasonable.
BIN_CHUNK_SIZE = 200

# $limit per batch — directive value.
BATCH_LIMIT = 1000

# Date-window length for the complaints dataset only (per directive).
COMPLAINTS_WINDOW_DAYS = 30

# Circuit breaker: abort the run if this many consecutive batches
# fail. Single-batch failures are logged + skipped per directive;
# but a run of consecutive failures means the upstream is unhealthy
# and continuing wastes the Socrata quota.
MAX_CONSECUTIVE_BATCH_FAILURES = 10


# ── Per-dataset config ────────────────────────────────────────────

@dataclass(frozen=True)
class DatasetConfig:
    """Static config for one of the three backfill datasets."""
    key: str                          # CLI value (--dataset <key>)
    socrata_id: str                   # 4x4 slug
    collection: str                   # Mongo collection name
    natural_key: str                  # field used for upsert filter
    natural_key_is_composite: bool    # True ⇒ natural_key is "a,b" comma-list
    date_field: str                   # Socrata date column for 3y filter
    use_date_windows: bool            # True ⇒ slice into N-day windows
    bin_field: str                    # column to filter the target BIN list on


DATASETS: Dict[str, DatasetConfig] = {
    "ecb-violations": DatasetConfig(
        key="ecb-violations",
        socrata_id="6bgk-3dad",
        collection="socrata_ecb_violations_historical",
        natural_key="ecb_violation_number",
        natural_key_is_composite=False,
        date_field="issue_date",
        use_date_windows=False,
        bin_field="bin",
    ),
    "permits": DatasetConfig(
        key="permits",
        socrata_id="rbx6-tga4",
        collection="socrata_permits_historical",
        # OPEN QUESTION (surfaced in Stage 1 report): rbx6-tga4 has
        # both `permit_si_no` (Socrata serial — expected to be unique
        # per row) and a composite (job_filing_number, work_permit).
        # Defaulting to permit_si_no because:
        #   • The directive says "investigate which is reliably unique"
        #   • work_permit is empty/null for not-yet-issued filings
        #   • permit_si_no is the Socrata-provided primary identifier
        # If permit_si_no turns out to have collisions or nulls in
        # live data, switch to composite via --permit-natural-key
        # composite at next run; the upsert filter changes shape but
        # the rest of the pipeline is identical.
        natural_key="permit_si_no",
        natural_key_is_composite=False,
        date_field="issued_date",
        use_date_windows=False,
        bin_field="bin",
    ),
    "complaints": DatasetConfig(
        key="complaints",
        socrata_id="eabe-havv",
        collection="socrata_complaints_historical",
        natural_key="complaint_number",
        natural_key_is_composite=False,
        date_field="date_entered",
        use_date_windows=True,
        bin_field="bin",
    ),
}


# ── Cursor file ───────────────────────────────────────────────────

@dataclass
class Cursor:
    """Mutable on-disk resume state. Persisted to CURSOR_PATH after
    every batch. A cursor's `dataset_id` field must match the
    --dataset CLI arg or the run aborts (prevents accidental
    cross-dataset resume).

    Fields:
      dataset_id        — Socrata slug for the in-flight dataset.
      started_at        — ISO timestamp of the first run that wrote
                          this cursor (preserved across resumes).
      last_update_at    — ISO timestamp of the most recent batch.
      total_inserted    — running upsert-success count.
      total_failed      — running batch-failure count (rows skipped).
      total_seen        — total Socrata rows iterated (success+fail).
      bin_chunk_index   — next BIN chunk to process (0-based).
      last_offset       — next Socrata $offset within current chunk.
      window_start      — ISO date string; complaints date-window start
                          (null for datasets without windowing).
      window_end        — ISO date string; complaints date-window end.
      done              — True if the run reached the natural end.
    """
    dataset_id: str
    started_at: str
    last_update_at: str
    total_inserted: int = 0
    total_failed: int = 0
    total_seen: int = 0
    bin_chunk_index: int = 0
    last_offset: int = 0
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    done: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "started_at": self.started_at,
            "last_update_at": self.last_update_at,
            "total_inserted": self.total_inserted,
            "total_failed": self.total_failed,
            "total_seen": self.total_seen,
            "bin_chunk_index": self.bin_chunk_index,
            "last_offset": self.last_offset,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "done": self.done,
        }


def _load_cursor(path: Path, expected_dataset: str) -> Optional[Cursor]:
    """Returns the persisted Cursor if it exists AND matches
    expected_dataset; raises if the file exists but is for a
    different dataset (prevents cross-dataset cursor reuse)."""
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("dataset_id") != expected_dataset:
        raise RuntimeError(
            f"Cursor file {path} is for dataset_id={raw.get('dataset_id')!r}; "
            f"current run is for dataset_id={expected_dataset!r}. Delete the "
            f"cursor file explicitly to start a different dataset."
        )
    return Cursor(**raw)


def _save_cursor(path: Path, cursor: Cursor) -> None:
    """Atomic-ish write: stage to <path>.tmp, rename in place. The
    rename is atomic on POSIX and best-effort on Windows; either way
    we never leave a half-written cursor behind."""
    cursor.last_update_at = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cursor.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)


# ── BIN target list ───────────────────────────────────────────────


def _load_target_bins(path: Path) -> List[str]:
    """Returns the flat de-duplicated BIN list from
    _backfill_target_bins.json. Order is stable across reads so cursor
    chunk indices stay valid for resume."""
    if not path.exists():
        raise RuntimeError(
            f"Target BIN list not found at {path}. Run "
            f"_select_backfill_target_bins.py first (Gate 3)."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    bins: List[str] = []
    seen: set = set()
    for source_key in ("active_projects", "recently_completed",
                       "supplemental_random"):
        for b in payload.get(source_key, []):
            b_str = str(b).strip()
            if b_str and b_str not in seen:
                bins.append(b_str)
                seen.add(b_str)
    return bins


def _chunk_bins(bins: List[str], chunk_size: int) -> List[List[str]]:
    """Split the flat BIN list into chunks of <= chunk_size. Chunk
    boundaries are deterministic (same input → same chunks), so a
    cursor's bin_chunk_index always points to the same BIN subset
    across runs."""
    return [bins[i:i + chunk_size] for i in range(0, len(bins), chunk_size)]


def _bin_in_clause(chunk: List[str], field_name: str) -> str:
    """Build the SoQL fragment `<field> IN ('a','b',...)`. BINs are
    digit strings, so SoQL injection isn't a concern — but quote-escape
    defensively anyway in case the BIN list ever picks up unexpected
    characters."""
    quoted = ",".join("'" + b.replace("'", "''") + "'" for b in chunk)
    return f"{field_name} IN ({quoted})"


# ── Date windowing ────────────────────────────────────────────────


def _backfill_start_date(now_utc: datetime) -> datetime:
    """3-year rolling cutoff. Pinned at process start so a long run
    doesn't drift its lower bound mid-iteration."""
    return now_utc - timedelta(days=365 * BACKFILL_WINDOW_YEARS)


def _date_windows(
    start: datetime, end: datetime, window_days: int,
) -> List[tuple[datetime, datetime]]:
    """Yields chronological [window_start, window_end) pairs covering
    [start, end]. Last window may be shorter than window_days."""
    out: List[tuple[datetime, datetime]] = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=window_days), end)
        out.append((cur, nxt))
        cur = nxt
    return out


# ── Upsert helpers ────────────────────────────────────────────────


def _upsert_filter(row: Dict[str, Any], cfg: DatasetConfig) -> Optional[Dict[str, Any]]:
    """Build the Mongo filter that selects exactly the row identified
    by its natural key. Returns None if the row is missing the key
    (caller skips + increments failed count)."""
    if cfg.natural_key_is_composite:
        # Reserved for future use if permits switches to composite key.
        keys = [k.strip() for k in cfg.natural_key.split(",")]
        filt: Dict[str, Any] = {}
        for k in keys:
            v = row.get(k)
            if v is None or v == "":
                return None
            filt[k] = v
        return filt
    v = row.get(cfg.natural_key)
    if v is None or v == "":
        return None
    return {cfg.natural_key: v}


# ── Core run loop ─────────────────────────────────────────────────


@dataclass
class RunStats:
    """In-memory counters for the current invocation (cursor persists
    across invocations; this is per-process)."""
    batches_succeeded: int = 0
    batches_failed: int = 0
    rows_upserted: int = 0
    rows_skipped_no_key: int = 0
    consecutive_failures: int = 0


async def _execute_batch(
    rows: List[Dict[str, Any]],
    db: Any,
    cfg: DatasetConfig,
    log: logging.Logger,
) -> tuple[int, int]:
    """Upsert one Socrata page into Mongo. Returns
    (rows_upserted, rows_skipped_no_key). Rows missing the natural
    key are dropped (logged WARNING + counted) so a malformed row
    doesn't poison the whole batch.

    Only invoked on the --execute path; the --dry-run path short-
    circuits before reaching here (see run())."""
    upserted = 0
    no_key = 0
    for r in rows:
        filt = _upsert_filter(r, cfg)
        if filt is None:
            no_key += 1
            log.warning(
                "[%s] row missing natural key (%s); skipping. "
                "Sample fields: %s",
                cfg.key, cfg.natural_key,
                {k: r.get(k) for k in list(r.keys())[:5]},
            )
            continue
        # $set the full row + a backfill-provenance stamp. The natural
        # key is implicitly in $set via the row spread, so re-runs
        # over identical Socrata rows are no-ops (Mongo treats equal
        # $set as unchanged).
        update_doc = {
            "$set": {**r, "_backfilled_at": datetime.now(timezone.utc)},
            "$setOnInsert": {"_first_backfilled_at": datetime.now(timezone.utc)},
        }
        await db[cfg.collection].update_one(filt, update_doc, upsert=True)
        upserted += 1
    return (upserted, no_key)


async def _run_one_window(
    cfg: DatasetConfig,
    bin_chunks: List[List[str]],
    window_start: Optional[datetime],
    window_end: Optional[datetime],
    socrata: SocrataClient,
    db: Any,
    cursor: Cursor,
    stats: RunStats,
    log: logging.Logger,
) -> None:
    """Walk all BIN chunks within one date window (or one chunk-only
    pass for windowless datasets). Persists cursor after every batch.

    Cursor resume: if the persisted bin_chunk_index/last_offset point
    mid-window, this function starts from there. On clean window
    completion, resets last_offset=0 + bin_chunk_index=0 (the caller
    advances window_start/window_end before invoking the next window).
    """
    start_chunk = cursor.bin_chunk_index
    for chunk_idx in range(start_chunk, len(bin_chunks)):
        chunk = bin_chunks[chunk_idx]
        cursor.bin_chunk_index = chunk_idx

        # Within a chunk, resume from cursor.last_offset on the first
        # iteration; subsequent chunks reset to 0.
        offset = cursor.last_offset if chunk_idx == start_chunk else 0
        cursor.last_offset = offset

        where_parts: List[str] = [_bin_in_clause(chunk, cfg.bin_field)]
        if window_start is not None and window_end is not None:
            where_parts.append(
                f"{cfg.date_field} >= '{window_start.strftime('%Y-%m-%dT00:00:00')}' "
                f"AND {cfg.date_field} < '{window_end.strftime('%Y-%m-%dT00:00:00')}'"
            )
        elif window_start is None and window_end is None:
            # Windowless path — still apply the 3-year lower bound.
            three_year_start = _backfill_start_date(
                datetime.now(timezone.utc),
            )
            where_parts.append(
                f"{cfg.date_field} >= '{three_year_start.strftime('%Y-%m-%dT00:00:00')}'"
            )
        where = " AND ".join(where_parts)

        while True:
            try:
                page = await socrata.query(
                    cfg.socrata_id,
                    where=where,
                    order=cfg.natural_key,
                    limit=BATCH_LIMIT,
                    offset=offset,
                )
            except SocrataQueryError as e:
                stats.batches_failed += 1
                stats.consecutive_failures += 1
                cursor.total_failed += 1
                log.error(
                    "[%s] batch failed (chunk_idx=%d offset=%d "
                    "window=[%s,%s)): %s\n%s",
                    cfg.key, chunk_idx, offset,
                    window_start, window_end, e, traceback.format_exc(),
                )
                _save_cursor(CURSOR_PATH, cursor)
                if stats.consecutive_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                    raise RuntimeError(
                        f"Circuit breaker tripped — "
                        f"{stats.consecutive_failures} consecutive batches "
                        f"failed. Last error: {e!r}"
                    )
                # Skip this batch — advance the offset and keep going.
                offset += BATCH_LIMIT
                cursor.last_offset = offset
                continue
            except Exception as e:  # transport / Mongo down / etc.
                stats.batches_failed += 1
                stats.consecutive_failures += 1
                cursor.total_failed += 1
                log.error(
                    "[%s] batch raised unexpected %s "
                    "(chunk_idx=%d offset=%d): %s\n%s",
                    cfg.key, type(e).__name__, chunk_idx, offset,
                    e, traceback.format_exc(),
                )
                _save_cursor(CURSOR_PATH, cursor)
                if stats.consecutive_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                    raise
                offset += BATCH_LIMIT
                cursor.last_offset = offset
                continue

            page_size = len(page)
            cursor.total_seen += page_size

            try:
                upserted, no_key = await _execute_batch(
                    page, db, cfg, log,
                )
            except Exception as e:
                stats.batches_failed += 1
                stats.consecutive_failures += 1
                cursor.total_failed += 1
                log.error(
                    "[%s] mongo upsert failed (chunk_idx=%d offset=%d): "
                    "%s\n%s",
                    cfg.key, chunk_idx, offset, e, traceback.format_exc(),
                )
                _save_cursor(CURSOR_PATH, cursor)
                if stats.consecutive_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                    raise
                offset += BATCH_LIMIT
                cursor.last_offset = offset
                continue

            stats.batches_succeeded += 1
            stats.consecutive_failures = 0
            stats.rows_upserted += upserted
            stats.rows_skipped_no_key += no_key
            cursor.total_inserted += upserted

            log.info(
                "[%s] Inserted %d rows (chunk_idx=%d/%d offset=%d, "
                "page_size=%d, total=%d, skipped_no_key=%d)",
                cfg.key, upserted, chunk_idx, len(bin_chunks) - 1,
                offset, page_size, cursor.total_inserted, no_key,
            )

            offset += BATCH_LIMIT
            cursor.last_offset = offset
            _save_cursor(CURSOR_PATH, cursor)

            # Short page → end of this chunk's data.
            if page_size < BATCH_LIMIT:
                break

        # Chunk exhausted — reset offset so next chunk starts at 0.
        cursor.last_offset = 0
        _save_cursor(CURSOR_PATH, cursor)

    # All chunks complete for this window. Reset chunk index for the
    # next window (caller advances window dates).
    cursor.bin_chunk_index = 0
    cursor.last_offset = 0
    _save_cursor(CURSOR_PATH, cursor)


def _print_plan(
    cfg: DatasetConfig,
    target_bin_count: int,
    bin_chunks: List[List[str]],
    log: logging.Logger,
) -> None:
    """Dry-run output: no Socrata calls, no Mongo writes. Prints the
    planned scope so the operator can sanity-check chunk count, date
    windows, and sample WHERE clauses before authorizing --execute."""
    log.info("=" * 60)
    log.info("DRY-RUN PLAN — dataset=%s (Socrata id=%s)",
             cfg.key, cfg.socrata_id)
    log.info("=" * 60)
    log.info("  collection         : %s", cfg.collection)
    log.info("  natural_key        : %s", cfg.natural_key)
    log.info("  date_field         : %s", cfg.date_field)
    log.info("  target BINs        : %d", target_bin_count)
    log.info("  BIN chunks         : %d (chunk_size=%d)",
             len(bin_chunks), BIN_CHUNK_SIZE)
    log.info("  batch limit        : %d ($limit per Socrata call)",
             BATCH_LIMIT)

    now_utc = datetime.now(timezone.utc)
    start_date = _backfill_start_date(now_utc)
    log.info("  3-year cutoff      : %s ≤ %s ≤ %s",
             start_date.date(), cfg.date_field, now_utc.date())

    if cfg.use_date_windows:
        windows = _date_windows(start_date, now_utc, COMPLAINTS_WINDOW_DAYS)
        log.info("  date windows       : %d × %d days",
                 len(windows), COMPLAINTS_WINDOW_DAYS)
        total_queries_estimate = len(windows) * len(bin_chunks)
        log.info("  est. min queries   : %d (windows × chunks; pagination "
                 "extends this when chunk has >%d rows)",
                 total_queries_estimate, BATCH_LIMIT)
    else:
        log.info("  date windows       : none (single-pass with 3y floor)")
        total_queries_estimate = len(bin_chunks)
        log.info("  est. min queries   : %d (1 per chunk; pagination extends "
                 "this when chunk has >%d rows)",
                 total_queries_estimate, BATCH_LIMIT)

    # Sample WHERE clause for the first chunk.
    if bin_chunks:
        sample_chunk = bin_chunks[0][:5]  # truncate for readability
        sample_where = _bin_in_clause(sample_chunk, cfg.bin_field)
        log.info("  sample WHERE       : %s ... (first %d of %d BINs)",
                 sample_where, len(sample_chunk), len(bin_chunks[0]))

    log.info("=" * 60)
    log.info("No Socrata calls made. No Mongo writes performed.")
    log.info("To execute the backfill, re-invoke with --execute "
             "(operator-authorized, per Gate 4).")


async def run(
    dataset_key: str,
    *,
    execute: bool,
    socrata: Optional[SocrataClient] = None,
    db: Any = None,
    log: Optional[logging.Logger] = None,
) -> int:
    """Top-level driver. Returns process exit code."""
    log = log or logging.getLogger(__name__)
    cfg = DATASETS[dataset_key]

    target_bins = _load_target_bins(TARGET_BINS_PATH)
    if not target_bins:
        log.error("Target BIN list is empty — nothing to backfill.")
        return 1
    bin_chunks = _chunk_bins(target_bins, BIN_CHUNK_SIZE)
    log.info(
        "[%s] %d target BINs → %d chunks of up to %d",
        cfg.key, len(target_bins), len(bin_chunks), BIN_CHUNK_SIZE,
    )

    if not execute:
        _print_plan(cfg, len(target_bins), bin_chunks, log)
        return 0

    # Load or initialize cursor.
    cursor = _load_cursor(CURSOR_PATH, cfg.socrata_id)
    if cursor is None:
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor = Cursor(
            dataset_id=cfg.socrata_id,
            started_at=now_iso,
            last_update_at=now_iso,
        )
        _save_cursor(CURSOR_PATH, cursor)
        log.info("[%s] starting fresh — no prior cursor", cfg.key)
    else:
        if cursor.done:
            log.info(
                "[%s] cursor reports done=True (total_inserted=%d); "
                "nothing to do. Delete %s to re-run.",
                cfg.key, cursor.total_inserted, CURSOR_PATH,
            )
            return 0
        log.info(
            "[%s] resuming from cursor: chunk_idx=%d offset=%d "
            "window=[%s,%s) total_inserted=%d",
            cfg.key, cursor.bin_chunk_index, cursor.last_offset,
            cursor.window_start, cursor.window_end, cursor.total_inserted,
        )

    stats = RunStats()

    # Datasets without date windowing run as a single "window" with
    # both bounds None (the inner loop applies the 3-year lower bound).
    if not cfg.use_date_windows:
        await _run_one_window(
            cfg, bin_chunks, None, None,
            socrata, db, cursor, stats, log,
        )
    else:
        now_utc = datetime.now(timezone.utc)
        start_date = _backfill_start_date(now_utc)
        windows = _date_windows(start_date, now_utc, COMPLAINTS_WINDOW_DAYS)
        log.info(
            "[%s] %d date windows of %d days "
            "([%s ... %s])",
            cfg.key, len(windows), COMPLAINTS_WINDOW_DAYS,
            start_date.date(), now_utc.date(),
        )

        # Resume which window we were on. The cursor's window_start
        # field, if present, identifies the in-flight window; we
        # match it against the prebuilt window list.
        start_window_idx = 0
        if cursor.window_start is not None:
            for i, (ws, _we) in enumerate(windows):
                if ws.strftime("%Y-%m-%d") == cursor.window_start[:10]:
                    start_window_idx = i
                    break

        for window_idx in range(start_window_idx, len(windows)):
            ws, we = windows[window_idx]
            cursor.window_start = ws.isoformat()
            cursor.window_end = we.isoformat()
            log.info(
                "[%s] window %d/%d: [%s, %s)",
                cfg.key, window_idx, len(windows) - 1, ws.date(), we.date(),
            )
            await _run_one_window(
                cfg, bin_chunks, ws, we,
                socrata, db, cursor, stats, log,
            )

    cursor.done = True
    _save_cursor(CURSOR_PATH, cursor)
    log.info(
        "[%s] BACKFILL COMPLETE: batches_succeeded=%d batches_failed=%d "
        "rows_upserted=%d rows_skipped_no_key=%d "
        "(cursor totals: inserted=%d failed=%d seen=%d)",
        cfg.key, stats.batches_succeeded, stats.batches_failed,
        stats.rows_upserted, stats.rows_skipped_no_key,
        cursor.total_inserted, cursor.total_failed, cursor.total_seen,
    )
    return 0


# ── CLI ───────────────────────────────────────────────────────────


def _configure_logging(verbose: bool) -> logging.Logger:
    """File + stderr handlers, INFO by default, DEBUG with --verbose."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    root = logging.getLogger()
    root.setLevel(level)

    # Clear any pre-existing handlers (idempotent across imports).
    for h in list(root.handlers):
        root.removeHandler(h)

    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter(fmt))
    root.addHandler(sh)

    return logging.getLogger("socrata_3year_backfill")


def _build_db():
    """Lazily import + connect motor. Mirrors the pattern used by
    the existing migration scripts."""
    from motor.motor_asyncio import AsyncIOMotorClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise SystemExit(
            "MONGO_URL and DB_NAME environment variables are required."
        )
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


async def _amain(args: argparse.Namespace) -> int:
    log = _configure_logging(args.verbose)
    log.info(
        "socrata_3year_backfill starting: dataset=%s execute=%s",
        args.dataset, args.execute,
    )

    # Dry-run path: no network, no DB. Just print the plan.
    if not args.execute:
        return await run(
            args.dataset, execute=False,
            socrata=None, db=None, log=log,
        )

    # --execute path: real Socrata + Mongo.
    db = _build_db()
    async with ServerHttpClient(timeout=30.0) as http:
        socrata = SocrataClient(http)
        return await run(
            args.dataset, execute=True,
            socrata=socrata, db=db, log=log,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="3-year Socrata historical backfill driver.",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        choices=sorted(DATASETS.keys()),
        help="Which dataset to backfill (one per invocation).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Perform real Socrata calls + Mongo upserts. Default is "
            "dry-run (no Socrata calls — synthetic local test only)."
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true", help="DEBUG-level logging.",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_amain(args))
    except RuntimeError as e:
        # Circuit breaker or cursor mismatch.
        logging.getLogger(__name__).error("Run aborted: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
