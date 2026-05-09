"""Phase V2.2 — NYC Open Data ingestion engine.

Pulls 6 BIN-keyed event datasets + PLUTO snapshot from NYC Open
Data via Socrata into the V2.2 collections defined in schema.py.

Two ingestion modes:

  • Initial backfill (operator-triggered, runs once after V2.2
    deploys): paginated 2-year historical pull per dataset.
    Idempotent — `record_id` unique index dedupes re-runs.
    Resumable — `ingestion_state` collection tracks the last
    cursor (offset / occurred_date) so a crash doesn't lose
    progress.

  • Weekly delta (scheduled cron, Sunday 2 AM ET): pulls the past
    7 days of new records per dataset. Same upsert path as
    backfill, so a delta that overlaps a backfill window is a
    no-op.

Plus event hooks: when the existing pollers
(`nightly_dob_scan`, `_poll_311_fast_complaints`) detect a fresh
record, they ALSO upsert into the V2.2 source collections via
`forward_to_v22(...)`. This keeps the score reflecting the
freshest data without waiting for the next weekly cron.

Rate limiting is handled by `lib/server_http.py` (auto-attaches
X-App-Token, surfaces 429s as EgressViolation-shaped retries
with exponential backoff).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from lib.server_http import ServerHttpClient
from lib.statistical_engine.schema import (
    INGESTION_STATE_COLLECTION,
    NYC_VIOLATIONS_COLLECTION,
    NYC_INSPECTIONS_COLLECTION,
    NYC_PERMITS_COLLECTION,
    NYC_COMPLAINTS_311_COLLECTION,
    NYC_ECB_VIOLATIONS_COLLECTION,
    NYC_HPD_VIOLATIONS_COLLECTION,
    NYC_PLUTO_COLLECTION,
)

logger = logging.getLogger(__name__)


# ── Dataset registry ──────────────────────────────────────────────
#
# Each NYC Open Data dataset has a stable Socrata 4x4 identifier
# (the slug at the end of the dataset URL). Field mapping is
# explicit — Socrata column names are inconsistent across datasets
# and we want a single canonical shape in our collections so the
# rest of the engine doesn't have to know which dataset a record
# came from.

# Format: source_id, mongo_collection, socrata_4x4, field_map.
# field_map keys are our canonical names; values are Socrata column
# names. Missing fields get None at upsert time.

DATASETS = {
    "dob_violations": {
        "collection": NYC_VIOLATIONS_COLLECTION,
        "socrata_id": "3h2n-5cm9",
        "date_field": "issue_date",
        "field_map": {
            "record_id":      "isn_dob_bis_viol",
            "bin":            "bin",
            "bbl":            "bbl",
            "borough":        "boro",
            "occurred_date":  "issue_date",
            "violation_type": "violation_type",
            "description":    "description",
            "disposition":    "disposition_comments",
        },
    },
    "dob_inspections": {
        "collection": NYC_INSPECTIONS_COLLECTION,
        "socrata_id": "ic3t-wcy2",
        "date_field": "inspection_date",
        "field_map": {
            "record_id":       "id",
            "bin":             "bin_number",
            "bbl":             "bbl",
            "borough":         "borough",
            "occurred_date":   "inspection_date",
            "inspection_type": "inspection_type",
            "result":          "result",
        },
    },
    "dob_permits": {
        "collection": NYC_PERMITS_COLLECTION,
        "socrata_id": "ipu4-2q9a",
        "date_field": "issuance_date",
        "field_map": {
            "record_id":       "job__",
            "bin":             "bin__",
            "bbl":             "bbl",
            "borough":         "borough",
            "occurred_date":   "issuance_date",
            "permit_status":   "permit_status",
            "permit_type":     "permit_type",
            "expiration_date": "expiration_date",
        },
    },
    "complaints_311": {
        "collection": NYC_COMPLAINTS_311_COLLECTION,
        "socrata_id": "erm2-nwe9",
        "date_field": "created_date",
        "field_map": {
            "record_id":       "unique_key",
            "bin":             "bin",
            "bbl":             "bbl",
            "borough":         "borough",
            "occurred_date":   "created_date",
            "complaint_type":  "complaint_type",
            "descriptor":      "descriptor",
            "agency":          "agency",
            "status":          "status",
        },
    },
    "ecb_violations": {
        "collection": NYC_ECB_VIOLATIONS_COLLECTION,
        "socrata_id": "6bgk-3dad",
        "date_field": "issue_date",
        "field_map": {
            "record_id":      "ecb_violation_number",
            "bin":            "bin",
            "bbl":            "bbl",
            "borough":        "boro",
            "occurred_date":  "issue_date",
            "violation_type": "violation_type",
            "description":    "violation_description",
            "hearing_status": "hearing_status",
        },
    },
    "hpd_violations": {
        "collection": NYC_HPD_VIOLATIONS_COLLECTION,
        "socrata_id": "wvxf-dwi5",
        "date_field": "novissueddate",
        "field_map": {
            "record_id":           "violationid",
            "bin":                 "bin",
            "bbl":                 "bbl",
            "borough":             "boro",
            "occurred_date":       "novissueddate",
            "class_":              "class",
            "novdescription":      "novdescription",
            "currentstatus":       "currentstatus",
        },
    },
    # PLUTO is special — snapshot, not event stream. Lower
    # ingestion frequency. Full table re-pulled on PLUTO release
    # (~quarterly per NYC City Planning); upsert by BIN.
    "pluto": {
        "collection": NYC_PLUTO_COLLECTION,
        "socrata_id": "64uk-42ks",
        "date_field": None,  # snapshot, no occurred_date
        "field_map": {
            "bin":           "bin",
            "bbl":           "bbl",
            "borough":       "borough",
            "bldgclass":     "bldgclass",
            "landuse":       "landuse",
            "yearbuilt":     "yearbuilt",
            "numfloors":     "numfloors",
            "lotarea":       "lotarea",
            "bldgarea":      "bldgarea",
        },
    },
}


# ── Constants ─────────────────────────────────────────────────────

BACKFILL_YEARS = 2
SOCRATA_PAGE_LIMIT = 5000          # max rows per Socrata GET
SOCRATA_BASE_URL = "https://data.cityofnewyork.us/resource"
WEEKLY_DELTA_DAYS = 7
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0


# ── Field normalization ───────────────────────────────────────────


def _to_canonical_record(
    raw_row: Dict[str, Any], dataset_spec: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Map a raw Socrata row to our canonical record shape using
    the dataset's field_map. Returns None if the record_id is
    missing or empty (degenerate row — skip rather than upsert
    a record without a dedupe key)."""
    out: Dict[str, Any] = {}
    fm = dataset_spec["field_map"]
    for canonical, source in fm.items():
        out[canonical] = raw_row.get(source)
    rec_id = out.get("record_id") or raw_row.get(fm.get("record_id", ""))
    # PLUTO uses `bin` as its natural key (no record_id).
    if "record_id" in fm and not rec_id:
        return None
    if "record_id" not in fm:
        # PLUTO: synthesize a stable record_id from bin so the
        # generic upsert path works for both event and snapshot
        # collections.
        if not out.get("bin"):
            return None
        out["record_id"] = f"pluto_{out['bin']}"
    # Parse occurred_date if present.
    if "occurred_date" in fm and out.get("occurred_date"):
        parsed = _parse_socrata_datetime(out["occurred_date"])
        if parsed is not None:
            out["occurred_date"] = parsed
    out["ingested_at"] = datetime.now(timezone.utc)
    out["dataset"] = next(
        k for k, v in DATASETS.items() if v is dataset_spec
    )
    return out


def _parse_socrata_datetime(value: Any) -> Optional[datetime]:
    """Socrata serves dates as ISO 8601 strings (with or without
    trailing 'Z' / timezone). Parse defensively; return None on
    bad input rather than raising."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Common Socrata shapes: "2026-05-08T00:00:00.000", "2026-05-08T00:00:00Z"
    fmts = (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in fmts:
        try:
            dt = datetime.strptime(s.replace("Z", "").split("+")[0], fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ── Socrata client ────────────────────────────────────────────────


async def _fetch_socrata_page(
    client: ServerHttpClient,
    socrata_id: str,
    *,
    where: Optional[str],
    order_by: Optional[str],
    limit: int,
    offset: int,
) -> List[Dict[str, Any]]:
    """One page of a Socrata dataset. Builds the SoQL params,
    issues the GET, retries on 429/5xx with exponential backoff.

    Returns the list of raw rows or [] on terminal failure."""
    url = f"{SOCRATA_BASE_URL}/{socrata_id}.json"
    params: Dict[str, Any] = {
        "$limit": limit,
        "$offset": offset,
    }
    if where:
        params["$where"] = where
    if order_by:
        params["$order"] = order_by

    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(MAX_RETRIES):
        try:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json() or []
            if r.status_code == 429 or r.status_code >= 500:
                # Honor Retry-After if present, else exponential
                # backoff with jitter.
                ra = r.headers.get("Retry-After")
                wait = (
                    float(ra) if ra and ra.isdigit() else backoff
                )
                wait = min(MAX_BACKOFF_SECONDS, wait)
                wait += random.uniform(0, 0.5)
                logger.warning(
                    f"[ingestion] socrata {socrata_id} got "
                    f"{r.status_code}, sleeping {wait:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})",
                )
                await asyncio.sleep(wait)
                backoff = min(MAX_BACKOFF_SECONDS, backoff * 2)
                continue
            # Other non-200 — don't loop; surface a warning.
            logger.warning(
                f"[ingestion] socrata {socrata_id} returned "
                f"{r.status_code}; aborting page",
            )
            return []
        except Exception as e:
            wait = min(MAX_BACKOFF_SECONDS, backoff)
            logger.warning(
                f"[ingestion] socrata {socrata_id} raised: {e!r}; "
                f"sleeping {wait:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})",
            )
            await asyncio.sleep(wait)
            backoff = min(MAX_BACKOFF_SECONDS, backoff * 2)
    return []


# ── Upsert ────────────────────────────────────────────────────────


async def upsert_record(
    db, collection_name: str, record: Dict[str, Any],
) -> bool:
    """Idempotent upsert of one canonical record into its
    collection. Dedupe key is `record_id` (unique index).

    Returns True if the record was new, False if it was a
    no-op (already present)."""
    if not record or not record.get("record_id"):
        return False
    try:
        res = await db[collection_name].update_one(
            {"record_id": record["record_id"]},
            {
                "$set": {
                    k: v for k, v in record.items()
                    if k not in ("ingested_at",)
                },
                "$setOnInsert": {
                    "ingested_at": record.get(
                        "ingested_at", datetime.now(timezone.utc)
                    ),
                },
            },
            upsert=True,
        )
        return bool(res.upserted_id)
    except Exception as e:
        logger.warning(
            f"[ingestion] upsert failed coll={collection_name} "
            f"record_id={record.get('record_id')}: {e!r}",
        )
        return False


# ── Ingestion-state cursor ────────────────────────────────────────


async def get_ingestion_state(db, dataset: str) -> Dict[str, Any]:
    doc = await db[INGESTION_STATE_COLLECTION].find_one(
        {"dataset": dataset},
    )
    return doc or {"dataset": dataset}


async def set_ingestion_state(
    db, dataset: str, **updates,
) -> None:
    updates["updated_at"] = datetime.now(timezone.utc)
    await db[INGESTION_STATE_COLLECTION].update_one(
        {"dataset": dataset},
        {"$set": {"dataset": dataset, **updates}},
        upsert=True,
    )


# ── Backfill orchestrator ─────────────────────────────────────────


async def backfill_dataset(
    db,
    dataset: str,
    *,
    years: int = BACKFILL_YEARS,
    page_limit: int = SOCRATA_PAGE_LIMIT,
    http_client: Optional[ServerHttpClient] = None,
    max_pages: Optional[int] = None,
) -> Dict[str, int]:
    """Pull up to `years` of history for one dataset, paginated.

    Resumable: reads the last `offset` from
    `ingestion_state` and continues from there. Updates the
    cursor after every page so a crash mid-backfill resumes
    cleanly.

    Returns a summary dict (pages, rows_seen, rows_upserted,
    errors).
    """
    spec = DATASETS.get(dataset)
    if spec is None:
        raise ValueError(f"unknown dataset: {dataset}")
    socrata_id = spec["socrata_id"]
    coll_name = spec["collection"]
    date_field = spec.get("date_field")

    state = await get_ingestion_state(db, dataset)
    offset = int(state.get("backfill_offset", 0) or 0)
    pages = 0
    rows_seen = 0
    rows_upserted = 0
    errors = 0

    where = None
    order = None
    if date_field:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=365 * years)
        cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S")
        where = f"{date_field} >= '{cutoff_iso}'"
        order = f"{date_field} ASC"

    # Use the caller-supplied client if any (tests inject a stub),
    # else open a new one.
    own_client = http_client is None
    client = http_client or ServerHttpClient(timeout=60.0)
    if own_client:
        await client.__aenter__()

    try:
        while True:
            page = await _fetch_socrata_page(
                client, socrata_id,
                where=where, order_by=order,
                limit=page_limit, offset=offset,
            )
            pages += 1
            if not page:
                # Either end-of-data or terminal error. End the
                # backfill — operator can re-run if it was an
                # error (the offset stays put so we resume).
                break
            for raw in page:
                rows_seen += 1
                rec = _to_canonical_record(raw, spec)
                if rec is None:
                    continue
                ok = await upsert_record(db, coll_name, rec)
                if ok:
                    rows_upserted += 1

            offset += len(page)
            await set_ingestion_state(
                db, dataset,
                backfill_offset=offset,
                last_page_pulled_at=datetime.now(timezone.utc),
                last_page_size=len(page),
            )
            if len(page) < page_limit:
                # Final page (Socrata returns fewer than
                # `$limit` when the result set is exhausted).
                break
            if max_pages is not None and pages >= max_pages:
                break
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    # Mark backfill complete iff we drained naturally (last page
    # was short OR returned nothing).
    finished = pages > 0 and rows_seen < pages * page_limit
    await set_ingestion_state(
        db, dataset,
        backfill_finished=finished,
    )

    summary = {
        "dataset": dataset,
        "pages": pages,
        "rows_seen": rows_seen,
        "rows_upserted": rows_upserted,
        "errors": errors,
        "final_offset": offset,
        "finished": finished,
    }
    logger.info(f"[ingestion] backfill complete: {summary}")
    return summary


async def backfill_all_datasets(
    db,
    *,
    years: int = BACKFILL_YEARS,
    http_client: Optional[ServerHttpClient] = None,
    max_pages_per_dataset: Optional[int] = None,
) -> List[Dict[str, int]]:
    """Run backfill across every registered dataset
    sequentially. Returns per-dataset summaries."""
    out: List[Dict[str, int]] = []
    for dataset in DATASETS.keys():
        try:
            summary = await backfill_dataset(
                db, dataset, years=years,
                http_client=http_client,
                max_pages=max_pages_per_dataset,
            )
            out.append(summary)
        except Exception as e:
            logger.error(
                f"[ingestion] backfill {dataset} failed: {e!r}",
                exc_info=True,
            )
            out.append({"dataset": dataset, "error": repr(e)})
    return out


# ── Weekly delta ──────────────────────────────────────────────────


async def weekly_delta_dataset(
    db,
    dataset: str,
    *,
    days: int = WEEKLY_DELTA_DAYS,
    http_client: Optional[ServerHttpClient] = None,
    page_limit: int = SOCRATA_PAGE_LIMIT,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Pull only the past `days` of new rows. Same upsert path as
    backfill so an overlap with a backfill window is a no-op."""
    spec = DATASETS.get(dataset)
    if spec is None:
        raise ValueError(f"unknown dataset: {dataset}")
    if spec.get("date_field") is None:
        # PLUTO has no date — weekly-delta degenerates to a no-op.
        # Operator triggers the PLUTO refresh on a separate
        # cadence (quarterly).
        return {"dataset": dataset, "skipped": "no date_field"}

    cur_now = now or datetime.now(timezone.utc)
    since = cur_now - timedelta(days=days)
    socrata_id = spec["socrata_id"]
    coll_name = spec["collection"]
    date_field = spec["date_field"]
    cutoff_iso = since.strftime("%Y-%m-%dT%H:%M:%S")
    where = f"{date_field} >= '{cutoff_iso}'"
    order = f"{date_field} ASC"

    own_client = http_client is None
    client = http_client or ServerHttpClient(timeout=60.0)
    if own_client:
        await client.__aenter__()

    pages = 0
    rows_seen = 0
    rows_upserted = 0
    offset = 0
    try:
        while True:
            page = await _fetch_socrata_page(
                client, socrata_id,
                where=where, order_by=order,
                limit=page_limit, offset=offset,
            )
            pages += 1
            if not page:
                break
            for raw in page:
                rows_seen += 1
                rec = _to_canonical_record(raw, spec)
                if rec is None:
                    continue
                ok = await upsert_record(db, coll_name, rec)
                if ok:
                    rows_upserted += 1
            offset += len(page)
            if len(page) < page_limit:
                break
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    await set_ingestion_state(
        db, dataset,
        last_weekly_delta_at=cur_now,
        last_weekly_delta_rows=rows_seen,
    )
    return {
        "dataset": dataset,
        "pages": pages,
        "rows_seen": rows_seen,
        "rows_upserted": rows_upserted,
    }


async def weekly_delta_all_datasets(
    db,
    *,
    now: Optional[datetime] = None,
    http_client: Optional[ServerHttpClient] = None,
) -> List[Dict[str, int]]:
    """Cron entry point — Sunday 2 AM ET wrapper. Walks every
    dataset, soft-fails per-dataset so one bad endpoint doesn't
    kill the run."""
    out: List[Dict[str, int]] = []
    for dataset in DATASETS.keys():
        try:
            summary = await weekly_delta_dataset(
                db, dataset,
                now=now,
                http_client=http_client,
            )
            out.append(summary)
        except Exception as e:
            logger.error(
                f"[ingestion] weekly delta {dataset} failed: {e!r}",
                exc_info=True,
            )
            out.append({"dataset": dataset, "error": repr(e)})
    return out


# ── Event hooks (called from existing pollers) ────────────────────


async def forward_to_v22(
    db, dataset: str, raw_row: Dict[str, Any],
) -> bool:
    """Public hook for the existing pollers (nightly_dob_scan,
    _poll_311_fast_complaints) to write a fresh record into the
    V2.2 collections in addition to dob_logs.

    Returns True if a new V2.2 record was upserted, False if
    duplicate or invalid."""
    spec = DATASETS.get(dataset)
    if spec is None:
        return False
    rec = _to_canonical_record(raw_row, spec)
    if rec is None:
        return False
    return await upsert_record(db, spec["collection"], rec)
