"""A2 Change 3 — legacy poller stamps `dataset` field on every write.

Test 9 of the A2 PR. Pins that ``_query_dob_apis`` in server.py
stamps each returned raw record with ``_dataset: "<slug>"`` matching
the Socrata dataset URL it was fetched from, AND that the value
propagates through ``run_dob_sync_for_project`` to the dob_logs
write (``dataset`` field on the persisted document, no leading
underscore — by convention, the underscore-prefixed form is the
in-flight tag and the bare form is the persisted field).

Before Stage 3 implementation, ``_query_dob_apis`` does not stamp
``_dataset`` and ``run_dob_sync_for_project`` does not write the
``dataset`` field to dob_logs. This test fails today with clear
"missing key" assertion errors on whichever endpoint slug is
checked first.

NOTE: forward-only. Existing 624 dob_logs records remain unstamped.
A backfill is out of scope for this PR (see C2 in Stage 1 v3).
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock, AsyncMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.run(coro)


# Canonical slug → endpoint URL mapping per server.py:_query_dob_apis.
# Stage 3 must populate _dataset on every record with one of these
# slugs (parsed from the URL path).
#
# NOTE: 14 distinct slugs match what server.py:_query_dob_apis polls
# (verified by grep at A2 Stage 5). The 311 dataset ``erm2-nwe9`` is
# NOT polled by _query_dob_apis — it has its own dedicated fast-poll
# function elsewhere in server.py that writes to dob_logs separately.
# Don't add erm2-nwe9 here unless _query_dob_apis is extended to
# poll it directly.
EXPECTED_SLUGS = {
    "855j-jady",   # DOB NOW Safety violations
    "3h2n-5cm9",   # BIS legacy violations
    "6bgk-3dad",   # ECB / OATH violations
    "eabe-havv",   # DOB complaints received
    "p937-wjvj",   # DOB inspections
    "rbx6-tga4",   # DOB NOW Build permits
    "dm9a-ab7w",   # DOB NOW Electrical permits
    "ipu4-2q9a",   # BIS legacy permits
    "w9ak-ipjd",   # DOB NOW Job filings
    "3usq-5cid",   # Stop Work Orders dedicated dataset
    "pkdm-hqz6",   # DOB NOW CofO
    "xubg-57si",   # DOB NOW Façade FISP
    "52dp-yji6",   # DOB NOW Boiler
    "e5aq-a4j2",   # DOB NOW Elevator
}


class _StubResponse:
    """Mimics enough of httpx.Response for _query_dob_apis."""

    def __init__(self, payload: List[Dict[str, Any]], status_code: int = 200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _ResponseRouter:
    """Routes ServerHttpClient.get(url, params=) to a canned response
    per dataset slug. Returns 1 distinct record per endpoint so the
    test can verify the per-endpoint _dataset stamp."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def get(self, url, **kwargs):
        self.calls.append({"url": url, "params": kwargs.get("params")})
        # Parse the dataset slug from the URL path.
        slug = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        # Return one record carrying a synthetic id field. The id_field
        # name varies per endpoint, so use the same name as the slug
        # for traceability.
        return _StubResponse([
            {"_synthetic_slug_marker": slug,
             # cover the various id_field names _query_dob_apis expects.
             # Include all candidates so the function's `id_field`
             # lookup always finds one.
             "violation_number":     f"{slug}_id",
             "isn_dob_bis_viol":     f"{slug}_id",
             "ecb_violation_number": f"{slug}_id",
             "stop_work_order_number": f"{slug}_id",
             "complaint_number":     f"{slug}_id",
             "job_filing_number":    f"{slug}_id",
             "job__":                f"{slug}_id",
             "job_ticket_or_work_order_id": f"{slug}_id",
             "co_number":            f"{slug}_id",
             "filing_number":        f"{slug}_id",
             "tracking_number":      f"{slug}_id",
             "device_number":        f"{slug}_id",
             # BIN passthrough so address-fallback BIN-heal doesn't
             # re-trigger.
             "bin":  "1234567",
             "bin__": "1234567"}
        ])


class _StubAsyncContextManager:
    """Wraps the response router as an async-context-manager matching
    ``async with ServerHttpClient(...) as http_client:``."""

    def __init__(self, router):
        self._router = router

    async def __aenter__(self):
        return self._router

    async def __aexit__(self, exc_type, exc, tb):
        return None


class TestLegacyPollerDatasetStamp(unittest.TestCase):
    """A2 Change 3 — verify _query_dob_apis stamps _dataset on
    every returned record, and that run_dob_sync_for_project
    propagates it through to dob_logs writes as the `dataset` field.
    """

    def test_query_dob_apis_stamps_dataset_on_every_record(self):
        """Pin Change 3 at the _query_dob_apis layer."""
        from server import _query_dob_apis

        router = _ResponseRouter()

        # ServerHttpClient context manager → router.
        def _http_factory(*args, **kwargs):
            return _StubAsyncContextManager(router)

        with patch("server.ServerHttpClient", _http_factory):
            records = _run(_query_dob_apis(
                nyc_bin="1234567",
                project_address="100 Main St, BROOKLYN, NY 11221",
            ))

        # Every returned record MUST carry _dataset.
        self.assertGreater(
            len(records), 0,
            "_query_dob_apis returned no records — the mock router "
            "may not be wired correctly. Cannot verify _dataset stamp.",
        )
        for rec in records:
            self.assertIn(
                "_dataset", rec,
                f"record missing _dataset stamp: "
                f"_record_type={rec.get('_record_type')!r} "
                f"id={rec.get('violation_number') or rec.get('job__') or '?'}",
            )
            self.assertIn(
                rec["_dataset"], EXPECTED_SLUGS,
                f"record carries unknown _dataset slug "
                f"{rec.get('_dataset')!r}; expected one of EXPECTED_SLUGS",
            )

    def test_run_dob_sync_persists_dataset_field_on_dob_logs(self):
        """Pin Change 3 at the dob_logs write layer.

        Mock the HTTP layer to return one record per endpoint, run
        run_dob_sync_for_project, then inspect every dob_logs
        insert_one call's argument and assert it carries a `dataset`
        field (no leading underscore — the in-flight `_dataset` tag
        becomes the persisted `dataset` field).
        """
        from server import run_dob_sync_for_project

        router = _ResponseRouter()
        inserted_docs: List[Dict[str, Any]] = []

        def _http_factory(*args, **kwargs):
            return _StubAsyncContextManager(router)

        # Stub db.dob_logs.insert_one (capture argument).
        async def _capture_insert(doc):
            inserted_docs.append(doc)
            r = MagicMock()
            r.inserted_id = f"id_{len(inserted_docs)}"
            return r

        # Stub db.dob_logs.find — return empty cursor (no existing
        # records, so every new record triggers an insert path).
        class _EmptyCursor:
            def __init__(self):
                pass

            async def to_list(self, length=None):
                return []

            def __aiter__(self):
                async def _gen():
                    if False:
                        yield None
                return _gen()

        async def _find_stub(*_a, **_kw):
            return _EmptyCursor()

        async def _find_one_stub(*_a, **_kw):
            return None

        async def _update_one_stub(*_a, **_kw):
            r = MagicMock(); r.matched_count = 0
            return r

        async def _delete_many_stub(*_a, **_kw):
            r = MagicMock(); r.deleted_count = 0
            return r

        # Async cursor stub for dob_logs.find()
        class _MockFind:
            def __init__(self):
                pass

            def __aiter__(self):
                async def _gen():
                    if False:
                        yield None
                return _gen()

            async def to_list(self, *_a, **_kw):
                return []

        mock_dob_logs = MagicMock()
        mock_dob_logs.find = MagicMock(return_value=_MockFind())
        mock_dob_logs.find_one = AsyncMock(return_value=None)
        mock_dob_logs.insert_one = _capture_insert
        mock_dob_logs.update_one = _update_one_stub
        mock_dob_logs.delete_many = _delete_many_stub

        # Stub db.projects.update_one (BIN auto-heal path).
        mock_projects = MagicMock()
        mock_projects.update_one = AsyncMock()

        # Stub the global db handle.
        mock_db = MagicMock()
        mock_db.dob_logs = mock_dob_logs
        mock_db.projects = mock_projects

        project = {
            "_id": "test_project_X",
            "company_id": "company_X",
            "nyc_bin": "1234567",
            "address": "100 Main St, BROOKLYN, NY 11221",
        }

        with patch("server.db", mock_db), \
             patch("server.ServerHttpClient", _http_factory):
            _run(run_dob_sync_for_project(project))

        self.assertGreater(
            len(inserted_docs), 0,
            "run_dob_sync_for_project did not insert any dob_logs; "
            "cannot verify dataset field stamping",
        )
        for doc in inserted_docs:
            self.assertIn(
                "dataset", doc,
                f"dob_logs doc missing `dataset` field: "
                f"record_type={doc.get('record_type')!r} "
                f"raw_dob_id={doc.get('raw_dob_id')!r}",
            )
            self.assertIn(
                doc["dataset"], EXPECTED_SLUGS,
                f"dob_logs doc carries unknown dataset slug "
                f"{doc.get('dataset')!r}; expected one of EXPECTED_SLUGS",
            )


if __name__ == "__main__":
    unittest.main()
