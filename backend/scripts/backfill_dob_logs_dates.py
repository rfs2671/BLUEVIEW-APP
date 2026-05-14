"""V2.3.A3 PR #9 — Backfill script for heterogeneous date formats
in db.dob_logs.

Two independent branches:

  Branch 4.1 — MDY complaint normalization
    Find:    record_type=complaint, complaint_date matches /^[0-9]{1,2}\\//
    Apply:   _normalize_dob_date_to_iso  → ISO output
    Rollback: stamps _original_complaint_date (and _original_closed_date
              if closed_date also normalized) preserving the pre-fix
              value so a future rollback can restore from the doc
              alone, no Socrata re-query needed.
    Idempotent — re-running over already-ISO records is no-op via
    a strict MDY pre-check inside the loop.

  Branch 4.2 — Null violation_date re-query (pre-A2 only)
    Find:    record_type in (violation, swo), violation_date null or
             missing, dataset field absent (pre-A2 records only).
    Route:   _detect_pattern(raw_dob_id) → known slug, or sequential
             try-all if pattern not recognized.
    Three outcome classes per Stage 2 design + Stage 2 amendments:
      • Socrata returns record with date → use Socrata (authoritative)
      • Socrata returns record with all-null source → fallback to
        raw_dob_id parse; on parse failure stamp
        ``_date_extraction_failed: True``
      • Socrata returns no record (404 / empty)  → fallback to
        raw_dob_id parse; stamps ``_record_not_in_socrata: True``
        and ``_recovered_from_raw_dob_id: True`` if parse succeeded
      • Socrata 5xx / network error → log warning, skip, no marker
        (simple always-retry on next run)

Hybrid T1 routing per operator's Stage 2 resolution. Three raw_dob_id
patterns observed in production's 13 null records:

  • ``aeuhaz``     — ``^[0-9]{6}AEUHAZ[0-9]+$``  (3h2n-5cm9 / BIS)
  • ``ll629``      — ``^[0-9]{6}LL629[0-9]+$``   (3h2n-5cm9 / BIS)
  • ``vio_ftf_pl`` — ``^VIO-FTF-PL-PER-[0-9]{6}-[0-9]+$``  (855j-jady)

Year cutoff for the 6-char MMDDYY patterns (per operator's
hybrid resolution): ``yr ≤ 30 → 20xx``, ``yr > 30 → 19xx``.

Usage:
  python -m scripts.backfill_dob_logs_dates           # dry-run (default)
  python -m scripts.backfill_dob_logs_dates --execute # write changes
  python -m scripts.backfill_dob_logs_dates --verbose # DEBUG logging
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from server import _normalize_dob_date_to_iso  # noqa: E402


logger = logging.getLogger(__name__)


# ─── Pattern definitions (Stage 1.5 T1 hybrid resolution) ─────────

_PATTERN_AEUHAZ_RE = re.compile(r"^[0-9]{6}AEUHAZ[0-9]+$")
_PATTERN_LL629_RE = re.compile(r"^[0-9]{6}LL629[0-9]+$")
_PATTERN_VIO_FTF_PL_RE = re.compile(r"^VIO-FTF-PL-PER-([0-9]{6})-[0-9]+$")

# Slug routing per pattern → (Socrata dataset slug, id_field name).
_PATTERN_SLUG_MAP: Dict[str, tuple] = {
    "aeuhaz":     ("3h2n-5cm9", "isn_dob_bis_viol"),
    "ll629":      ("3h2n-5cm9", "isn_dob_bis_viol"),
    "vio_ftf_pl": ("855j-jady", "violation_number"),
}

# Sequential try-all order when pattern is unrecognized.
_FALLBACK_TRY_ORDER: List[tuple] = [
    ("855j-jady", "violation_number"),
    ("3h2n-5cm9", "isn_dob_bis_viol"),
    ("6bgk-3dad", "ecb_violation_number"),
]

# Strict MDY shape check for idempotency pre-filter inside Branch 4.1.
_MDY_STORED_RE = re.compile(r"^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}$")


def _detect_pattern(raw_dob_id: str) -> Optional[str]:
    """Returns ``'aeuhaz'`` | ``'ll629'`` | ``'vio_ftf_pl'`` | ``None``."""
    if not raw_dob_id:
        return None
    if _PATTERN_AEUHAZ_RE.match(raw_dob_id):
        return "aeuhaz"
    if _PATTERN_LL629_RE.match(raw_dob_id):
        return "ll629"
    if _PATTERN_VIO_FTF_PL_RE.match(raw_dob_id):
        return "vio_ftf_pl"
    return None


def _parse_raw_dob_id_date(raw_dob_id: str) -> Optional[str]:
    """Parse a date from a known-pattern raw_dob_id. Returns
    YYYYMMDD (matches violation_date storage format) or ``None``.

    Year cutoff per operator's hybrid T1 resolution:
      • 2-digit year ``≤ 30`` → ``20yy``
      • 2-digit year ``> 30``  → ``19yy``
    """
    pattern = _detect_pattern(raw_dob_id)
    if pattern is None:
        return None

    if pattern in ("aeuhaz", "ll629"):
        # First 6 chars = MMDDYY
        try:
            mo = int(raw_dob_id[0:2])
            dy = int(raw_dob_id[2:4])
            yr_2 = int(raw_dob_id[4:6])
            yr_4 = 2000 + yr_2 if yr_2 <= 30 else 1900 + yr_2
            datetime(yr_4, mo, dy)  # validation
            return f"{yr_4:04d}{mo:02d}{dy:02d}"
        except (ValueError, IndexError):
            return None

    if pattern == "vio_ftf_pl":
        m = _PATTERN_VIO_FTF_PL_RE.match(raw_dob_id)
        if not m:
            return None
        yyyymm = m.group(1)
        try:
            yr = int(yyyymm[0:4])
            mo = int(yyyymm[4:6])
            datetime(yr, mo, 1)  # validation
            # Day defaults to 01 — no day info in the id segment.
            return f"{yr:04d}{mo:02d}01"
        except (ValueError, IndexError):
            return None

    return None


# ─── Default Socrata getter (production path) ─────────────────────


async def _default_socrata_get(slug: str, id_field: str, raw_id: str) -> Optional[dict]:
    """Default async Socrata fetch used when the caller doesn't
    inject one. Tests pass a mock via ``run_backfill(..., socrata_get=...)``.

    Returns:
      • ``dict`` — first record matching the filter
      • ``None`` — record not found (empty result list OR 404)
      • raises  — network / 5xx error (caller treats as transient
                  and skips with no marker)
    """
    from lib.server_http import ServerHttpClient
    url = f"https://data.cityofnewyork.us/resource/{slug}.json"
    params = {id_field: raw_id, "$limit": "1"}
    async with ServerHttpClient(timeout=20.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ConnectionError(f"Socrata returned {resp.status_code}")
        records = resp.json()
        if not isinstance(records, list) or not records:
            return None
        return records[0]


def _extract_violation_date_from_rec(rec: dict) -> Optional[str]:
    """Apply the same 4-field fallback chain as
    ``server._extract_violation_fields`` to a Socrata re-fetched
    record. Returns first non-null value or ``None``."""
    return (
        rec.get("issue_date")
        or rec.get("violation_date")
        or rec.get("issued_date")
        or rec.get("infraction_date")
        or None
    )


# ─── Top-level driver ─────────────────────────────────────────────


async def run_backfill(
    db: Any,
    *,
    execute: bool = False,
    socrata_get: Optional[Callable[[str, str, str], Awaitable[Optional[dict]]]] = None,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, int]:
    """Two-branch backfill driver.

    Args:
      db          — Mongo db handle (Motor in production; stub in tests).
      execute     — ``True`` to write, ``False`` for dry-run (default).
      socrata_get — async ``fn(slug, id_field, raw_id) -> dict | None``.
                    Defaults to ``_default_socrata_get`` (ServerHttpClient).
      logger      — logger to use; defaults to module logger.

    Returns: stats dict per Stage 2 design + Stage 2 amendments.
    """
    log = logger if logger is not None else logging.getLogger(__name__)
    sget = socrata_get or _default_socrata_get

    stats: Dict[str, int] = {
        "mdy_scanned":                    0,
        "mdy_normalized":                 0,
        "mdy_skipped_already_iso":        0,
        "null_scanned":                   0,
        "null_recovered_from_socrata":    0,
        "null_recovered_from_raw_dob_id": 0,
        "null_unrecoverable":             0,
        "null_not_in_socrata":            0,
        "null_network_failures":          0,
    }

    mode = "execute" if execute else "dry-run"
    log.info(f"backfill_dob_logs_dates starting (mode={mode})")

    # ─── Branch 4.1 — MDY complaint normalization ─────────────────
    mdy_cursor = db.dob_logs.find({
        "record_type":    "complaint",
        "complaint_date": {"$regex": r"^[0-9]{1,2}/"},
    })
    mdy_docs = await mdy_cursor.to_list(length=None)

    for doc in mdy_docs:
        stats["mdy_scanned"] += 1
        old_complaint = doc.get("complaint_date")
        # Strict idempotency pre-check inside the loop. The find
        # regex (``^[0-9]{1,2}/``) is broad enough that ISO-shaped
        # values starting with a single digit followed by '/' could
        # theoretically slip through; the strict MDY regex
        # (``^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}$``) is the gate.
        if not isinstance(old_complaint, str) or not _MDY_STORED_RE.match(
            old_complaint.strip()
        ):
            stats["mdy_skipped_already_iso"] += 1
            continue

        new_complaint = _normalize_dob_date_to_iso(old_complaint)
        if new_complaint is None:
            log.warning(
                f"[backfill 4.1] complaint normalize returned None "
                f"for {old_complaint!r} on doc {doc.get('_id')!r}"
            )
            continue

        # T3.B parity: if closed_date is also MDY, normalize it in
        # the same write so a single record never carries one ISO
        # date and one MDY date.
        update_set: Dict[str, Any] = {
            "complaint_date":           new_complaint,
            "_original_complaint_date": old_complaint,
        }
        old_closed = doc.get("closed_date")
        if isinstance(old_closed, str) and _MDY_STORED_RE.match(old_closed.strip()):
            new_closed = _normalize_dob_date_to_iso(old_closed)
            if new_closed is not None:
                update_set["closed_date"] = new_closed
                update_set["_original_closed_date"] = old_closed

        if execute:
            await db.dob_logs.update_one(
                {"_id": doc["_id"]}, {"$set": update_set},
            )
            log.info(
                f"[backfill 4.1] normalized complaint_date "
                f"{old_complaint!r} → {new_complaint!r} "
                f"(raw_dob_id={doc.get('raw_dob_id')!r})"
            )
        else:
            log.info(
                f"[DRY-RUN 4.1] complaint_date {old_complaint!r} → "
                f"{new_complaint!r} (raw_dob_id={doc.get('raw_dob_id')!r})"
            )
        stats["mdy_normalized"] += 1

    # ─── Branch 4.2 — Null violation re-query (pre-A2 only) ───────
    null_cursor = db.dob_logs.find({
        "record_type": {"$in": ["violation", "swo"]},
        "$or": [
            {"violation_date": None},
            {"violation_date": {"$exists": False}},
        ],
        # Pre-A2 filter — A2-era records carry a `dataset` stamp
        # via Change 3 of PR #8 (legacy poller dataset stamping).
        # Forward-only invariant: any A2-era null-date violation
        # is out of scope for this backfill (would indicate a
        # different bug worth surfacing separately).
        "dataset": {"$exists": False},
    })
    null_docs = await null_cursor.to_list(length=None)

    for doc in null_docs:
        stats["null_scanned"] += 1
        raw_dob_id = doc.get("raw_dob_id", "") or ""

        # Routing per Stage 2 T1.C hybrid:
        #   • Pattern detected   → single targeted slug
        #   • No pattern         → sequential try-all
        pattern = _detect_pattern(raw_dob_id)
        if pattern is not None:
            slug, id_field = _PATTERN_SLUG_MAP[pattern]
            tries = [(slug, id_field)]
        else:
            tries = list(_FALLBACK_TRY_ORDER)

        socrata_rec: Optional[dict] = None
        network_failed = False
        for slug, id_field in tries:
            try:
                rec = await sget(slug, id_field, raw_dob_id)
            except Exception as e:
                log.warning(
                    f"[backfill 4.2] Socrata network error for "
                    f"{raw_dob_id!r} at {slug}/{id_field}: {e}"
                )
                network_failed = True
                break
            if rec is not None:
                socrata_rec = rec
                break

        if network_failed:
            stats["null_network_failures"] += 1
            # No marker — simple always-retry on next run per
            # Stage 2 amendment (no time-based suppression).
            continue

        update_set = {}
        if socrata_rec is not None:
            extracted = _extract_violation_date_from_rec(socrata_rec)
            if extracted:
                # Authoritative Socrata date wins (T1 precedence).
                update_set["violation_date"] = extracted
                stats["null_recovered_from_socrata"] += 1
            else:
                # Source returned record but all 4 fallback fields
                # null → attempt raw_dob_id parse as last resort.
                parsed = _parse_raw_dob_id_date(raw_dob_id)
                if parsed:
                    update_set["violation_date"] = parsed
                    update_set["_recovered_from_raw_dob_id"] = True
                    stats["null_recovered_from_raw_dob_id"] += 1
                else:
                    update_set["_date_extraction_failed"] = True
                    stats["null_unrecoverable"] += 1
        else:
            # Socrata had no record at all → mark + fallback parse.
            update_set["_record_not_in_socrata"] = True
            stats["null_not_in_socrata"] += 1
            parsed = _parse_raw_dob_id_date(raw_dob_id)
            if parsed:
                update_set["violation_date"] = parsed
                update_set["_recovered_from_raw_dob_id"] = True
                stats["null_recovered_from_raw_dob_id"] += 1
            else:
                update_set["_date_extraction_failed"] = True
                stats["null_unrecoverable"] += 1

        if execute:
            await db.dob_logs.update_one(
                {"_id": doc["_id"]}, {"$set": update_set},
            )
            markers = [k for k in update_set if k.startswith("_")]
            log.info(
                f"[backfill 4.2] {raw_dob_id!r} → "
                f"violation_date={update_set.get('violation_date')!r} "
                f"markers={markers}"
            )
        else:
            log.info(
                f"[DRY-RUN 4.2] {raw_dob_id!r} would set: {update_set!r}"
            )

    log.info(f"backfill_dob_logs_dates complete: {stats}")
    return stats


# ─── CLI entry point ──────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true",
        help="Write changes (default: dry-run)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="DEBUG logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "blueview")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    stats = asyncio.run(run_backfill(db, execute=args.execute))
    print(stats)


if __name__ == "__main__":
    main()
