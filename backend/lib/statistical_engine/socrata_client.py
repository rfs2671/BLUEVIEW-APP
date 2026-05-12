"""Phase V2.3 Commit 2 — Async wrapper for NYC Socrata queries.

Built on top of ``lib.server_http.ServerHttpClient``, which already:
  • Auto-attaches ``X-App-Token`` from ``SOCRATA_APP_TOKEN`` for
    ``data.cityofnewyork.us`` hosts (so we stay above the 1000
    req/hr anonymous quota).
  • Enforces the Akamai-egress guard (``data.cityofnewyork.us`` is
    NOT on the blocklist, so Socrata queries pass through cleanly).
  • Defaults ``follow_redirects`` to False.

This module adds the Socrata-specific concerns ServerHttpClient
doesn't know about:

  1. SoQL parameter construction (``$where`` / ``$select`` /
     ``$order`` / ``$limit`` / ``$offset`` / ``$group``).
  2. Retry/backoff on 429 + 5xx with Retry-After honoring. Logic
     is lifted from the deleted V2.2 ``ingestion._fetch_socrata_page``
     so the production tuning (MAX_RETRIES=5, INITIAL=1.0s,
     MAX=60.0s, jitter ≤ 0.5s, exponential doubling) is preserved.
  3. Pagination via ``query_all`` — short page (rows < page_size)
     terminates the loop, ``max_pages`` caps run time.
  4. Permanent failures (4xx other than 429, exhausted retries on
     429/5xx, transport exceptions exhausting retries) surface as
     ``SocrataQueryError`` so callers can fail-fast cleanly.

NOT INSTANTIATED IN PRODUCTION CODE YET. Commit 2 only builds and
tests the client in isolation; Commit 3 rewrites baselines.py /
triggers.py / score.py / calibration.py to use it in place of the
deleted local-mirror collection reads.

Dataset-id constants live at module top so all callers reference
the same canonical 4x4 slugs. Field-mapping details from the V2.2
``DATASETS`` dict are NOT migrated — Commit 3 inlines the (small,
per-call-site) projection logic into the specific query helpers
that need it.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from lib.server_http import ServerHttpClient


logger = logging.getLogger(__name__)


# ── Socrata endpoint + retry tuning ───────────────────────────────

SOCRATA_BASE_URL = "https://data.cityofnewyork.us/resource"

# Production-tuned defaults lifted verbatim from the deleted
# ``ingestion.py`` so retry behavior is unchanged across the V2.2 →
# V2.3 transition.
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0
RETRY_JITTER_SECONDS = 0.5


# ── Canonical dataset-id constants ────────────────────────────────
#
# Each value is a Socrata 4x4 slug (the tail of the dataset URL).
# Verified against d19a4b9~1:backend/lib/statistical_engine/
# ingestion.py:DATASETS, which was validated against live Socrata
# metadata during V2.2.2 + V2.2.3 bugfixes:
#
#   • dob_violations  3h2n-5cm9   — V2.2.4 Path A curl probe 2026-05-10
#   • dob_inspections p937-wjvj   — V2.2.2 BUG 1 fix
#   • dob_permits     rbx6-tga4   — V2.3 schema-corrections hotfix
#                                  (ipu4-2q9a deprecated; rbx6-tga4
#                                  is current-of-record and carries
#                                  both bin AND bbl)
#   • complaints_311  erm2-nwe9   — original
#   • ecb_violations  6bgk-3dad   — original
#   • hpd_violations  wvxf-dwi5   — original
#   • pluto           64uk-42ks   — V2.2.3 BUG 7 fix

DATASET_DOB_VIOLATIONS  = "3h2n-5cm9"
DATASET_DOB_INSPECTIONS = "p937-wjvj"
DATASET_DOB_PERMITS     = "rbx6-tga4"
DATASET_COMPLAINTS_311  = "erm2-nwe9"
DATASET_ECB_VIOLATIONS  = "6bgk-3dad"
DATASET_HPD_VIOLATIONS  = "wvxf-dwi5"
DATASET_PLUTO           = "64uk-42ks"

ALL_DATASET_IDS = (
    DATASET_DOB_VIOLATIONS,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_PERMITS,
    DATASET_COMPLAINTS_311,
    DATASET_ECB_VIOLATIONS,
    DATASET_HPD_VIOLATIONS,
    DATASET_PLUTO,
)


# ── Exception type ────────────────────────────────────────────────


class SocrataQueryError(RuntimeError):
    """Raised when a Socrata query fails after exhausting retries
    (429/5xx) OR on the first 4xx response other than 429 (since
    those are permanent — bad SoQL, missing dataset, auth — and
    retrying just wastes the quota).

    Carries the failing dataset id + a status / exception summary
    so the caller can log or sentry-report.
    """

    def __init__(
        self,
        message: str,
        *,
        dataset_id: Optional[str] = None,
        status_code: Optional[int] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.dataset_id = dataset_id
        self.status_code = status_code
        self.cause = cause


# ── Internal helpers ──────────────────────────────────────────────


def _build_soql_params(
    *,
    where: Optional[str],
    select: Optional[list[str]],
    order: Optional[str],
    limit: int,
    offset: int,
    group: Optional[str],
) -> dict[str, Any]:
    """Construct the SoQL parameter dict for a Socrata GET.

    Only includes a parameter if it was explicitly provided —
    Socrata defaults are reasonable (no filter, no group, etc.)
    when omitted. ``$select`` as a list joins to a comma-delimited
    string per the Socrata convention; an empty list is omitted
    entirely so the caller can't accidentally request zero columns.
    """
    params: dict[str, Any] = {"$limit": limit, "$offset": offset}
    if where:
        params["$where"] = where
    if select:
        params["$select"] = ",".join(select)
    if order:
        params["$order"] = order
    if group:
        params["$group"] = group
    return params


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Honor either the integer-seconds form (``Retry-After: 30``)
    or the HTTP-date form (``Retry-After: Wed, 21 Oct 2026 07:28:00 GMT``).

    Returns the wait duration in seconds, or None if the header
    is absent / unparseable. Negative deltas (a date in the past)
    collapse to 0 so the caller doesn't wait.
    """
    if not value:
        return None
    value = value.strip()
    # Integer seconds — the common case from Socrata.
    if value.isdigit():
        return float(value)
    # HTTP-date — RFC 7231 §7.1.3 allows this form.
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    now = datetime.now(timezone.utc) if target.tzinfo else datetime.utcnow()
    delta = (target - now).total_seconds()
    return max(0.0, delta)


# ── Public client ─────────────────────────────────────────────────


class SocrataClient:
    """Async wrapper over ServerHttpClient for NYC Socrata queries.

    Usage::

        async with ServerHttpClient(timeout=20.0) as http:
            client = SocrataClient(http)
            rows = await client.query(
                DATASET_COMPLAINTS_311,
                where="bbl in ('1000000001','1000000002')",
                limit=1000,
            )

    The client itself does NOT own the underlying HTTP connection
    pool — the caller passes in an already-constructed
    ``ServerHttpClient``. This keeps the lifecycle predictable
    (the caller's ``async with`` controls connection cleanup) and
    makes test stubbing straightforward (pass a ServerHttpClient
    built with a ``transport=httpx.MockTransport(handler)``).
    """

    def __init__(
        self,
        http_client: ServerHttpClient,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be ≥ 1")
        if base_backoff_seconds <= 0:
            raise ValueError("base_backoff_seconds must be > 0")
        self._http = http_client
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds

    async def query(
        self,
        dataset_id: str,
        *,
        where: Optional[str] = None,
        select: Optional[list[str]] = None,
        order: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        group: Optional[str] = None,
    ) -> list[dict]:
        """Issue a single Socrata GET. Returns a list of row dicts.

        Retries on HTTP 429 and 5xx up to ``max_retries`` times
        with exponential backoff. Honors the ``Retry-After``
        header (integer seconds OR HTTP-date) when present.

        Raises ``SocrataQueryError`` on any 4xx other than 429
        (treated as permanent — bad SoQL / missing dataset / auth)
        or after the retry budget is exhausted.
        """
        url = f"{SOCRATA_BASE_URL}/{dataset_id}.json"
        params = _build_soql_params(
            where=where, select=select, order=order,
            limit=limit, offset=offset, group=group,
        )

        backoff = self._base_backoff
        last_status: Optional[int] = None
        last_exc_repr: Optional[str] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = await self._http.get(url, params=params)
            except Exception as e:
                # Transport-level failure (ConnectError, ReadTimeout,
                # etc.). Treat as retryable — same as 5xx.
                last_exc_repr = repr(e)
                if attempt >= self._max_retries:
                    logger.error(
                        "[socrata] %s transport-failed after %d attempts: %s",
                        dataset_id, attempt, last_exc_repr,
                    )
                    raise SocrataQueryError(
                        f"Socrata query for {dataset_id} failed after "
                        f"{attempt} attempts: {last_exc_repr}",
                        dataset_id=dataset_id,
                        cause=e,
                    ) from e
                wait = min(MAX_BACKOFF_SECONDS, backoff) \
                    + random.uniform(0, RETRY_JITTER_SECONDS)
                logger.warning(
                    "[socrata] %s raised %s; sleeping %.1fs "
                    "(attempt %d/%d)",
                    dataset_id, last_exc_repr, wait,
                    attempt, self._max_retries,
                )
                await asyncio.sleep(wait)
                backoff = min(MAX_BACKOFF_SECONDS, backoff * 2)
                continue

            last_status = resp.status_code

            # Success — parse and return.
            if resp.status_code == 200:
                # Socrata returns a JSON array on success. An empty
                # array is a legitimate zero-result query (not an
                # error) — callers decide whether that's an
                # end-of-data signal or a query that genuinely
                # returned nothing.
                payload = resp.json()
                return payload if isinstance(payload, list) else []

            # 429 or 5xx — retry path.
            if resp.status_code == 429 or resp.status_code >= 500:
                ra = _parse_retry_after(resp.headers.get("Retry-After"))
                if ra is not None:
                    # Server told us how long to wait; trust it, no
                    # jitter (the server already accounts for load).
                    wait = min(MAX_BACKOFF_SECONDS, ra)
                else:
                    wait = min(MAX_BACKOFF_SECONDS, backoff) \
                        + random.uniform(0, RETRY_JITTER_SECONDS)
                if attempt >= self._max_retries:
                    logger.error(
                        "[socrata] %s returned %d after %d attempts; "
                        "giving up",
                        dataset_id, resp.status_code, attempt,
                    )
                    raise SocrataQueryError(
                        f"Socrata query for {dataset_id} got HTTP "
                        f"{resp.status_code} after {attempt} attempts",
                        dataset_id=dataset_id,
                        status_code=resp.status_code,
                    )
                logger.warning(
                    "[socrata] %s got %d, sleeping %.1fs "
                    "(attempt %d/%d)",
                    dataset_id, resp.status_code, wait,
                    attempt, self._max_retries,
                )
                await asyncio.sleep(wait)
                backoff = min(MAX_BACKOFF_SECONDS, backoff * 2)
                continue

            # 4xx other than 429 — permanent failure, don't retry.
            logger.error(
                "[socrata] %s returned %d (permanent, not retrying)",
                dataset_id, resp.status_code,
            )
            raise SocrataQueryError(
                f"Socrata query for {dataset_id} got HTTP "
                f"{resp.status_code} (permanent, not retrying)",
                dataset_id=dataset_id,
                status_code=resp.status_code,
            )

        # Should not reach here — the loop above either returns or
        # raises on the final attempt. Defensive fallthrough.
        raise SocrataQueryError(
            f"Socrata query for {dataset_id} exhausted retries "
            f"(last_status={last_status}, last_exc={last_exc_repr})",
            dataset_id=dataset_id,
            status_code=last_status,
        )

    async def query_all(
        self,
        dataset_id: str,
        *,
        where: Optional[str] = None,
        select: Optional[list[str]] = None,
        order: Optional[str] = None,
        page_size: int = 5000,
        max_pages: Optional[int] = None,
        group: Optional[str] = None,
    ) -> list[dict]:
        """Exhaustively paginate a Socrata query.

        Walks pages of size ``page_size`` (or up to ``max_pages``
        pages) by incrementing ``$offset``. Stops when a short
        page is returned (``len(rows) < page_size``) — Socrata's
        end-of-data signal — or when ``max_pages`` is reached.

        Per-page failures raise ``SocrataQueryError`` from the
        inner ``query()`` call; ``query_all`` does not suppress
        them.
        """
        all_rows: list[dict] = []
        offset = 0
        pages_fetched = 0

        while True:
            page = await self.query(
                dataset_id,
                where=where,
                select=select,
                order=order,
                limit=page_size,
                offset=offset,
                group=group,
            )
            all_rows.extend(page)
            pages_fetched += 1

            # Short page → end of data.
            if len(page) < page_size:
                return all_rows

            # max_pages cap.
            if max_pages is not None and pages_fetched >= max_pages:
                return all_rows

            offset += page_size
