"""Phase V2.3 Commit 2 — SocrataClient wrapper tests.

Pin every contract:

  • URL construction: hits ``data.cityofnewyork.us/resource/<id>.json``
    with the right SoQL params (``$where``, ``$select`` joined,
    ``$order``, ``$limit``, ``$offset``, ``$group``) and OMITS params
    that weren't specified.
  • Happy path: 200 → returns parsed JSON rows.
  • Retry on 429 with Retry-After (integer seconds) honored —
    NO computed backoff applied when the server told us how long.
  • Retry on 503 — falls back to exponential backoff when no
    Retry-After header.
  • 4xx other than 429 — NO retry, raise immediately. The retry
    loop wasting quota on a permanent SoQL error is precisely the
    failure mode SocrataQueryError exists to surface.
  • Exhausted retries on 429/5xx → SocrataQueryError with
    status_code preserved.
  • Transport exception (ConnectError etc.) → retries, eventually
    raises SocrataQueryError with cause attached.
  • query_all paginates by incrementing offset, stops on short
    page (len < page_size).
  • query_all respects max_pages cap even when pages are full.
  • query_all forwards where/select/order/group to inner query().
  • Dataset-id constants match the canonical Socrata 4x4 slug
    regex ``^[a-z0-9]{4}-[a-z0-9]{4}$``.

All tests use ``httpx.MockTransport`` so no live Socrata traffic.
``asyncio.sleep`` is patched module-wide to keep retry tests
under a millisecond.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Callable, List, Optional
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402

from lib.server_http import ServerHttpClient  # noqa: E402
from lib.statistical_engine import socrata_client as sc  # noqa: E402
from lib.statistical_engine.socrata_client import (  # noqa: E402
    ALL_DATASET_IDS,
    DATASET_DOB_VIOLATIONS,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_PERMITS,
    DATASET_COMPLAINTS_311,
    DATASET_ECB_VIOLATIONS,
    DATASET_HPD_VIOLATIONS,
    DATASET_PLUTO,
    SOCRATA_BASE_URL,
    SocrataClient,
    SocrataQueryError,
    _build_soql_params,
    _parse_retry_after,
)


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Mock transport helpers
# ──────────────────────────────────────────────────────────────────


class _RecordingHandler:
    """Records every request httpx hands to it, replays a queued
    list of responses in order. If the queue runs dry, the test
    has under-prepared — we raise to surface that instead of
    silently re-using the last response."""

    def __init__(self, responses: List[httpx.Response]) -> None:
        self._responses = list(responses)
        self.requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError(
                "_RecordingHandler ran out of queued responses; "
                "test queued fewer than the client demanded.",
            )
        return self._responses.pop(0)


def _make_client(
    responses: List[httpx.Response],
    *,
    max_retries: int = 5,
    base_backoff_seconds: float = 1.0,
) -> tuple[SocrataClient, _RecordingHandler, ServerHttpClient]:
    """Build (SocrataClient, handler, http_client) wired to a
    MockTransport so each call pops one response from `responses`.
    Caller is responsible for awaiting http_client.aclose() (or
    using `async with`) at the end of the test."""
    handler = _RecordingHandler(responses)
    http = ServerHttpClient(transport=httpx.MockTransport(handler))
    client = SocrataClient(
        http,
        max_retries=max_retries,
        base_backoff_seconds=base_backoff_seconds,
    )
    return client, handler, http


def _json_resp(rows: list, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=rows)


def _err_resp(status: int, *, retry_after: Optional[str] = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(status, headers=headers, json={"error": True})


# Patch asyncio.sleep inside the socrata_client module so retry
# tests don't waste real wall-clock seconds. Each test that uses
# the retry path applies this patch.
def _patch_sleep():
    return patch.object(sc.asyncio, "sleep", new=AsyncMock(return_value=None))


# ──────────────────────────────────────────────────────────────────
# SoQL parameter builder (unit-level, no HTTP)
# ──────────────────────────────────────────────────────────────────


class TestBuildSoqlParams(unittest.TestCase):

    def test_includes_only_limit_and_offset_by_default(self):
        params = _build_soql_params(
            where=None, select=None, order=None,
            limit=1000, offset=0, group=None,
        )
        self.assertEqual(params, {"$limit": 1000, "$offset": 0})

    def test_where_included_when_present(self):
        params = _build_soql_params(
            where="bin = 1000001", select=None, order=None,
            limit=1000, offset=0, group=None,
        )
        self.assertEqual(params["$where"], "bin = 1000001")

    def test_select_list_joined_with_commas(self):
        params = _build_soql_params(
            where=None, select=["bin", "bbl", "occurred_date"],
            order=None, limit=1000, offset=0, group=None,
        )
        self.assertEqual(params["$select"], "bin,bbl,occurred_date")

    def test_empty_select_list_omitted(self):
        # Edge case: an empty list would otherwise become "$select"
        # → "" which Socrata interprets as zero columns. Caller
        # almost certainly didn't mean that.
        params = _build_soql_params(
            where=None, select=[], order=None,
            limit=1000, offset=0, group=None,
        )
        self.assertNotIn("$select", params)

    def test_order_and_group_included(self):
        params = _build_soql_params(
            where=None, select=None, order="occurred_date DESC",
            limit=1000, offset=500, group="bbl",
        )
        self.assertEqual(params["$order"], "occurred_date DESC")
        self.assertEqual(params["$group"], "bbl")
        self.assertEqual(params["$offset"], 500)


# ──────────────────────────────────────────────────────────────────
# Retry-After header parsing
# ──────────────────────────────────────────────────────────────────


class TestParseRetryAfter(unittest.TestCase):

    def test_none_returns_none(self):
        self.assertIsNone(_parse_retry_after(None))

    def test_empty_returns_none(self):
        self.assertIsNone(_parse_retry_after(""))

    def test_integer_seconds(self):
        self.assertEqual(_parse_retry_after("30"), 30.0)

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_retry_after("not a date"))

    def test_http_date_in_future(self):
        # HTTP-date a few seconds in the future. We don't assert
        # the exact value (test execution latency makes that
        # flaky); we just confirm a non-None positive answer.
        from datetime import datetime, timedelta, timezone
        target = datetime.now(timezone.utc) + timedelta(seconds=30)
        # HTTP-date format: "Wed, 21 Oct 2026 07:28:00 GMT"
        http_date = target.strftime("%a, %d %b %Y %H:%M:%S GMT")
        result = _parse_retry_after(http_date)
        self.assertIsNotNone(result)
        # Allow ±10s tolerance for test latency / clock skew.
        self.assertTrue(20 <= result <= 40, f"got {result}")

    def test_http_date_in_past_collapses_to_zero(self):
        from datetime import datetime, timedelta, timezone
        target = datetime.now(timezone.utc) - timedelta(seconds=30)
        http_date = target.strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.assertEqual(_parse_retry_after(http_date), 0.0)


# ──────────────────────────────────────────────────────────────────
# Happy-path GET
# ──────────────────────────────────────────────────────────────────


class TestQueryHappyPath(unittest.TestCase):

    def test_url_and_params_correctly_constructed(self):
        client, handler, http = _make_client([
            _json_resp([{"bin": "1234567"}]),
        ])

        async def go():
            try:
                rows = await client.query(
                    DATASET_COMPLAINTS_311,
                    where="bbl='1000000001'",
                    select=["bin", "bbl"],
                    order="created_date DESC",
                    limit=500,
                    offset=0,
                )
                self.assertEqual(rows, [{"bin": "1234567"}])

                self.assertEqual(len(handler.requests), 1)
                req = handler.requests[0]
                self.assertEqual(req.method, "GET")
                # URL prefix matches base + dataset id .json
                self.assertTrue(
                    str(req.url).startswith(
                        f"{SOCRATA_BASE_URL}/{DATASET_COMPLAINTS_311}.json?",
                    ),
                    f"unexpected URL: {req.url}",
                )
                # SoQL params present.
                self.assertEqual(req.url.params["$where"], "bbl='1000000001'")
                self.assertEqual(req.url.params["$select"], "bin,bbl")
                self.assertEqual(req.url.params["$order"], "created_date DESC")
                self.assertEqual(req.url.params["$limit"], "500")
                self.assertEqual(req.url.params["$offset"], "0")
            finally:
                await http.aclose()

        _run(go())

    def test_returns_empty_list_for_empty_payload(self):
        client, _h, http = _make_client([_json_resp([])])

        async def go():
            try:
                rows = await client.query(DATASET_PLUTO)
                self.assertEqual(rows, [])
            finally:
                await http.aclose()

        _run(go())

    def test_non_list_payload_collapses_to_empty(self):
        # Defensive — if Socrata ever returns a dict (e.g. an
        # error payload that somehow snuck in with 200), we
        # return [] rather than blowing up downstream code that
        # iterates the result.
        client, _h, http = _make_client([
            httpx.Response(200, json={"unexpected": "shape"}),
        ])

        async def go():
            try:
                rows = await client.query(DATASET_PLUTO)
                self.assertEqual(rows, [])
            finally:
                await http.aclose()

        _run(go())


# ──────────────────────────────────────────────────────────────────
# Retry on 429
# ──────────────────────────────────────────────────────────────────


class TestRetryOn429(unittest.TestCase):

    def test_429_honors_retry_after_then_succeeds(self):
        client, handler, http = _make_client([
            _err_resp(429, retry_after="2"),
            _err_resp(429, retry_after="3"),
            _json_resp([{"bin": "1234567"}]),
        ], base_backoff_seconds=0.01)

        async def go():
            try:
                with _patch_sleep() as sleep_mock:
                    rows = await client.query(DATASET_DOB_VIOLATIONS)
                    self.assertEqual(rows, [{"bin": "1234567"}])

                    # Three HTTP requests fired.
                    self.assertEqual(len(handler.requests), 3)
                    # Two sleeps (between the three attempts).
                    self.assertEqual(sleep_mock.await_count, 2)
                    # First sleep waited the Retry-After value.
                    self.assertEqual(
                        sleep_mock.await_args_list[0].args[0], 2.0,
                    )
                    self.assertEqual(
                        sleep_mock.await_args_list[1].args[0], 3.0,
                    )
            finally:
                await http.aclose()

        _run(go())


# ──────────────────────────────────────────────────────────────────
# Retry on 503 — exponential backoff
# ──────────────────────────────────────────────────────────────────


class TestRetryOn5xx(unittest.TestCase):

    def test_503_uses_exponential_backoff_then_succeeds(self):
        client, handler, http = _make_client([
            _err_resp(503),
            _err_resp(503),
            _json_resp([{"ok": True}]),
        ], base_backoff_seconds=1.0)

        async def go():
            try:
                with _patch_sleep() as sleep_mock:
                    # Pin the jitter to zero so the assertion is
                    # deterministic — actual production code adds
                    # 0..RETRY_JITTER_SECONDS on top of the base.
                    with patch.object(sc.random, "uniform", return_value=0.0):
                        rows = await client.query(DATASET_DOB_INSPECTIONS)
                self.assertEqual(rows, [{"ok": True}])

                self.assertEqual(len(handler.requests), 3)
                self.assertEqual(sleep_mock.await_count, 2)
                # base=1.0, then doubled to 2.0 on the next attempt.
                self.assertEqual(sleep_mock.await_args_list[0].args[0], 1.0)
                self.assertEqual(sleep_mock.await_args_list[1].args[0], 2.0)
            finally:
                await http.aclose()

        _run(go())


# ──────────────────────────────────────────────────────────────────
# No retry on permanent 4xx
# ──────────────────────────────────────────────────────────────────


class TestNoRetryOn4xx(unittest.TestCase):

    def test_400_raises_immediately(self):
        # A second response is queued to PROVE we didn't retry —
        # if we did, the test would silently succeed by getting
        # the 200 from attempt 2.
        client, handler, http = _make_client([
            _err_resp(400),
            _json_resp([{"oops": "would-have-retried"}]),
        ])

        async def go():
            try:
                with _patch_sleep():
                    with self.assertRaises(SocrataQueryError) as ctx:
                        await client.query(DATASET_DOB_PERMITS)
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertEqual(ctx.exception.dataset_id, DATASET_DOB_PERMITS)
                # Exactly one request.
                self.assertEqual(len(handler.requests), 1)
            finally:
                await http.aclose()

        _run(go())

    def test_404_raises_immediately(self):
        client, handler, http = _make_client([_err_resp(404)])

        async def go():
            try:
                with _patch_sleep():
                    with self.assertRaises(SocrataQueryError) as ctx:
                        await client.query(DATASET_HPD_VIOLATIONS)
                self.assertEqual(ctx.exception.status_code, 404)
                self.assertEqual(len(handler.requests), 1)
            finally:
                await http.aclose()

        _run(go())


# ──────────────────────────────────────────────────────────────────
# Exhausted retries
# ──────────────────────────────────────────────────────────────────


class TestRetriesExhausted(unittest.TestCase):

    def test_persistent_429_raises_after_max_retries(self):
        client, handler, http = _make_client(
            [_err_resp(429, retry_after="1") for _ in range(5)],
            max_retries=5, base_backoff_seconds=0.01,
        )

        async def go():
            try:
                with _patch_sleep():
                    with self.assertRaises(SocrataQueryError) as ctx:
                        await client.query(DATASET_ECB_VIOLATIONS)
                self.assertEqual(ctx.exception.status_code, 429)
                # Hit max_retries times — no more, no less.
                self.assertEqual(len(handler.requests), 5)
            finally:
                await http.aclose()

        _run(go())

    def test_transport_exception_retries_then_raises(self):
        # The MockTransport handler raises a ConnectError on every
        # call — the client should retry per its budget, then
        # raise SocrataQueryError with .cause set.
        raise_count = {"n": 0}

        def explode(_request: httpx.Request) -> httpx.Response:
            raise_count["n"] += 1
            raise httpx.ConnectError(
                "boom",
                request=_request,
            )

        http = ServerHttpClient(transport=httpx.MockTransport(explode))
        client = SocrataClient(
            http, max_retries=3, base_backoff_seconds=0.01,
        )

        async def go():
            try:
                with _patch_sleep():
                    with self.assertRaises(SocrataQueryError) as ctx:
                        await client.query(DATASET_PLUTO)
                self.assertEqual(raise_count["n"], 3)
                self.assertIsNotNone(ctx.exception.cause)
                self.assertIsInstance(
                    ctx.exception.cause, httpx.ConnectError,
                )
            finally:
                await http.aclose()

        _run(go())


# ──────────────────────────────────────────────────────────────────
# query_all — pagination
# ──────────────────────────────────────────────────────────────────


class TestQueryAll(unittest.TestCase):

    def test_paginates_until_short_page(self):
        # page_size=2; pages: [a,b], [c,d], [e] → exhausted on 3rd
        # page (short).
        client, handler, http = _make_client([
            _json_resp([{"i": 1}, {"i": 2}]),
            _json_resp([{"i": 3}, {"i": 4}]),
            _json_resp([{"i": 5}]),
        ])

        async def go():
            try:
                rows = await client.query_all(
                    DATASET_COMPLAINTS_311, page_size=2,
                )
                self.assertEqual(
                    rows,
                    [{"i": 1}, {"i": 2}, {"i": 3}, {"i": 4}, {"i": 5}],
                )
                # Three HTTP requests with incrementing offset.
                self.assertEqual(len(handler.requests), 3)
                self.assertEqual(handler.requests[0].url.params["$offset"], "0")
                self.assertEqual(handler.requests[1].url.params["$offset"], "2")
                self.assertEqual(handler.requests[2].url.params["$offset"], "4")
            finally:
                await http.aclose()

        _run(go())

    def test_respects_max_pages_cap(self):
        client, handler, http = _make_client([
            _json_resp([{"i": 1}, {"i": 2}]),
            _json_resp([{"i": 3}, {"i": 4}]),
            # Third full page would be fetched without the cap.
            _json_resp([{"i": 5}, {"i": 6}]),
        ])

        async def go():
            try:
                rows = await client.query_all(
                    DATASET_PLUTO, page_size=2, max_pages=2,
                )
                self.assertEqual(
                    rows, [{"i": 1}, {"i": 2}, {"i": 3}, {"i": 4}],
                )
                # Only two requests, not three.
                self.assertEqual(len(handler.requests), 2)
            finally:
                await http.aclose()

        _run(go())

    def test_forwards_where_select_order_group(self):
        client, handler, http = _make_client([
            _json_resp([]),  # immediately short → one request only
        ])

        async def go():
            try:
                await client.query_all(
                    DATASET_DOB_VIOLATIONS,
                    where="bbl in ('1','2')",
                    select=["bbl", "occurred_date"],
                    order="occurred_date DESC",
                    group="bbl",
                    page_size=1000,
                )
                req = handler.requests[0]
                self.assertEqual(req.url.params["$where"], "bbl in ('1','2')")
                self.assertEqual(req.url.params["$select"], "bbl,occurred_date")
                self.assertEqual(req.url.params["$order"], "occurred_date DESC")
                self.assertEqual(req.url.params["$group"], "bbl")
                self.assertEqual(req.url.params["$limit"], "1000")
            finally:
                await http.aclose()

        _run(go())


# ──────────────────────────────────────────────────────────────────
# Dataset id constants
# ──────────────────────────────────────────────────────────────────


class TestDatasetIdConstants(unittest.TestCase):
    """The 4x4 slug format is canonical for Socrata. A typo (wrong
    length, capitalization, missing hyphen) shows up as 404s in
    production — much better to catch at test time."""

    _SLUG_RE = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")

    def test_each_constant_matches_slug_regex(self):
        for dataset_id in (
            DATASET_DOB_VIOLATIONS,
            DATASET_DOB_INSPECTIONS,
            DATASET_DOB_PERMITS,
            DATASET_COMPLAINTS_311,
            DATASET_ECB_VIOLATIONS,
            DATASET_HPD_VIOLATIONS,
            DATASET_PLUTO,
        ):
            self.assertRegex(dataset_id, self._SLUG_RE)

    def test_all_dataset_ids_tuple_has_seven_entries(self):
        self.assertEqual(len(ALL_DATASET_IDS), 7)

    def test_all_dataset_ids_unique(self):
        # Catches a future copy-paste regression where two
        # constants accidentally point at the same dataset.
        self.assertEqual(len(set(ALL_DATASET_IDS)), 7)


# ──────────────────────────────────────────────────────────────────
# Constructor validation
# ──────────────────────────────────────────────────────────────────


class TestConstructor(unittest.TestCase):

    def test_zero_max_retries_rejected(self):
        http = ServerHttpClient()
        try:
            with self.assertRaises(ValueError):
                SocrataClient(http, max_retries=0)
        finally:
            _run(http.aclose())

    def test_negative_backoff_rejected(self):
        http = ServerHttpClient()
        try:
            with self.assertRaises(ValueError):
                SocrataClient(http, base_backoff_seconds=-1.0)
        finally:
            _run(http.aclose())


if __name__ == "__main__":
    unittest.main()
