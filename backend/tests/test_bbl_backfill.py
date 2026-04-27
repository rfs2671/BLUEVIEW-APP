"""Step 9.1 BBL backfill — unit + integration tests.

Pure-function tests cover address parsing + multi-match disambiguation.
Integration test exercises the PLUTO query against a recorded fixture
response (no live network call). The recorded fixture was captured
2026-04-27 by hitting `64uk-42ks` for "9 Menahan Street, Brooklyn" —
real Socrata response shape preserved verbatim.

Why integration test matters: both prod projects already have BBL
populated, so the dry-run never actually invoked the PLUTO query
path. First time PLUTO runs in prod will be when a customer adds a
third project. That can't be the moment we discover the query is
broken. Fixture-backed test catches it pre-deploy.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

# Import directly from migration script — same path as tests/test_fee_schedule.py
# imports inlined helpers from its migration.
import importlib.util
_MIG = _BACKEND / "migrations" / "20260427_projects_bbl_backfill.py"
spec = importlib.util.spec_from_file_location("bbl_backfill", _MIG)
bbl_backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bbl_backfill)


# ── Recorded PLUTO fixture (2026-04-27 capture) ────────────────────
# Real response shape from 64uk-42ks.json. Edit only when re-recording
# from a current Socrata response.

PLUTO_RESPONSE_9_MENAHAN = [
    {
        "bbl": "3033040024",
        "address": "9 MENAHAN STREET",
        "borough": "BK",
        "block": "3304",
        "lot": "24",
        "bin": "3325703",
    }
]

PLUTO_RESPONSE_MULTI_MATCH = [
    # Two rows for the same physical address (large lot split into
    # multiple BIN-stamped buildings — common in NYC for multi-tower
    # developments). Real shape; BBLs are realistic.
    {"bbl": "1015860001", "address": "350 5 AVENUE", "borough": "MN",
     "block": "1586", "lot": "1", "bin": "1015862"},
    {"bbl": "1015860002", "address": "350 5 AVENUE", "borough": "MN",
     "block": "1586", "lot": "2", "bin": "1015863"},
]

PLUTO_RESPONSE_EMPTY = []


def _run(coro):
    return asyncio.run(coro)


# ── parse_address ──────────────────────────────────────────────────

class TestParseAddress(unittest.TestCase):

    def test_brooklyn_address(self):
        result = bbl_backfill.parse_address("9 Menahan Street, Brooklyn, NY 11221")
        self.assertEqual(result, {
            "house_no": "9",
            "street_name": "MENAHAN STREET",
            "boro": "BK",
            "zip": "11221",
        })

    def test_bronx_address(self):
        result = bbl_backfill.parse_address("852 East 176th Street, The Bronx, NY, USA")
        self.assertEqual(result["house_no"], "852")
        self.assertEqual(result["boro"], "BX")
        self.assertIn("EAST 176", result["street_name"])

    def test_no_zip_still_parses(self):
        result = bbl_backfill.parse_address("123 Main St, Manhattan, NY")
        self.assertIsNotNone(result)
        self.assertEqual(result["boro"], "MN")
        self.assertIsNone(result["zip"])

    def test_empty_returns_none(self):
        self.assertIsNone(bbl_backfill.parse_address(""))
        self.assertIsNone(bbl_backfill.parse_address(None))

    def test_no_borough_returns_none(self):
        self.assertIsNone(bbl_backfill.parse_address("123 Main St"))

    def test_unknown_borough_returns_none(self):
        self.assertIsNone(bbl_backfill.parse_address("123 Main St, Newark, NJ"))

    def test_house_with_letter_suffix(self):
        result = bbl_backfill.parse_address("12A Main Street, Queens, NY")
        self.assertEqual(result["house_no"], "12A")


# ── disambiguate_pluto_rows ────────────────────────────────────────

class TestDisambiguate(unittest.TestCase):

    def test_no_rows_returns_none(self):
        chosen, reason = bbl_backfill.disambiguate_pluto_rows([])
        self.assertIsNone(chosen)
        self.assertEqual(reason, "no_rows")

    def test_single_match(self):
        chosen, reason = bbl_backfill.disambiguate_pluto_rows(PLUTO_RESPONSE_9_MENAHAN)
        self.assertEqual(chosen["bbl"], "3033040024")
        self.assertEqual(reason, "single_match")

    def test_multi_match_with_bin_hint_picks_correct(self):
        chosen, reason = bbl_backfill.disambiguate_pluto_rows(
            PLUTO_RESPONSE_MULTI_MATCH,
            nyc_bin_hint="1015863",
        )
        self.assertEqual(chosen["bbl"], "1015860002")
        self.assertEqual(reason, "bin_match_disambiguation")

    def test_multi_match_without_hint_picks_first(self):
        chosen, reason = bbl_backfill.disambiguate_pluto_rows(
            PLUTO_RESPONSE_MULTI_MATCH,
            nyc_bin_hint=None,
        )
        self.assertEqual(chosen["bbl"], "1015860001")
        self.assertEqual(reason, "first_of_multi")

    def test_multi_match_with_unmatched_hint_picks_first(self):
        chosen, reason = bbl_backfill.disambiguate_pluto_rows(
            PLUTO_RESPONSE_MULTI_MATCH,
            nyc_bin_hint="9999999",  # doesn't match either row
        )
        self.assertEqual(chosen["bbl"], "1015860001")
        self.assertEqual(reason, "first_of_multi")


# ── query_pluto integration (against fixture) ──────────────────────

class TestQueryPluto(unittest.TestCase):
    """Exercises the actual PLUTO query function against a recorded
    fixture. Catches breakage in the URL shape, $where construction,
    response parsing, and Socrata token header injection.

    The first time prod hits PLUTO will be when a customer adds a
    third project. Fixture-backed test ensures the code path works
    on day one rather than discovering breakage live."""

    def test_query_returns_rows_on_200(self):
        captured = {}

        class _StubClient:
            async def get(self, url, **kwargs):
                captured["url"] = url
                captured["params"] = kwargs.get("params") or {}
                captured["headers"] = kwargs.get("headers") or {}
                return httpx.Response(200, json=PLUTO_RESPONSE_9_MENAHAN)

        async def go():
            parsed = bbl_backfill.parse_address("9 Menahan Street, Brooklyn, NY")
            return await bbl_backfill.query_pluto(_StubClient(), parsed)

        rows = _run(go())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bbl"], "3033040024")

        # URL + query shape verification
        self.assertEqual(captured["url"], bbl_backfill.PLUTO_URL)
        params = captured["params"]
        self.assertIn("$where", params)
        self.assertIn("borough='BK'", params["$where"])
        self.assertIn("9 MENAHAN STREET", params["$where"])
        self.assertEqual(params["$select"], "bbl,address,borough,block,lot,bin")
        self.assertEqual(params["$limit"], "5")

    def test_socrata_token_header_attached_when_env_set(self):
        captured = {}

        class _StubClient:
            async def get(self, url, **kwargs):
                captured["headers"] = kwargs.get("headers") or {}
                return httpx.Response(200, json=PLUTO_RESPONSE_9_MENAHAN)

        async def go():
            parsed = bbl_backfill.parse_address("9 Menahan Street, Brooklyn, NY")
            os.environ["SOCRATA_APP_TOKEN"] = "fake-token-25-chars-1234567"
            try:
                return await bbl_backfill.query_pluto(_StubClient(), parsed)
            finally:
                os.environ.pop("SOCRATA_APP_TOKEN", None)

        _run(go())
        self.assertEqual(
            captured["headers"].get("X-App-Token"),
            "fake-token-25-chars-1234567",
        )

    def test_query_returns_empty_on_non_200(self):
        class _StubClient:
            async def get(self, url, **kwargs):
                return httpx.Response(429, text="rate limited")

        async def go():
            parsed = bbl_backfill.parse_address("9 Menahan Street, Brooklyn, NY")
            return await bbl_backfill.query_pluto(_StubClient(), parsed)

        rows = _run(go())
        self.assertEqual(rows, [])

    def test_query_returns_empty_on_no_rows(self):
        class _StubClient:
            async def get(self, url, **kwargs):
                return httpx.Response(200, json=[])

        async def go():
            parsed = bbl_backfill.parse_address("123 Nonexistent St, Manhattan, NY")
            return await bbl_backfill.query_pluto(_StubClient(), parsed)

        rows = _run(go())
        self.assertEqual(rows, [])

    def test_sql_injection_house_no_escaped(self):
        """Defense: a project address with apostrophes shouldn't break
        the SoQL query. Probably impossible from real data, but the
        sanitization is part of the contract."""
        captured = {}

        class _StubClient:
            async def get(self, url, **kwargs):
                captured["params"] = kwargs.get("params") or {}
                return httpx.Response(200, json=[])

        async def go():
            # Attacker-controlled house number with embedded quote.
            parsed = {
                "house_no": "9' OR '1'='1",
                "street_name": "MENAHAN STREET",
                "boro": "BK",
                "zip": None,
            }
            return await bbl_backfill.query_pluto(_StubClient(), parsed)

        _run(go())
        # Single quotes in house_no are doubled (SoQL escape) — the
        # injected condition can't break out.
        self.assertIn("''", captured["params"]["$where"])


if __name__ == "__main__":
    unittest.main()
