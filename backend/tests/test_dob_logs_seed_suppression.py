"""MR.14 (commit 2b) — seed-suppression on the activity feed.

The first poll after MR.14 commit 2a deployed inserted ~25k
seed-transition rows (one per pre-existing dob_logs entry) with
previous_status=None. The activity feed must not surface these by
default — operator UX would be drowning in "we started tracking
this on May 3" rows.

This test pins:
  • The query helper _mr14_seed_window() reads the env var correctly
    (start + duration).
  • Default behavior (env unset) returns (None, None) — suppression off.
  • Env var malformed → suppression off (fail-closed).
  • include_seed=true query param disables suppression at the
    endpoint level (admin/debug view).

End-to-end suppression behavior with a live db is exercised via
TestClient against a mocked db with both seed + non-seed rows.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


# ── Helper-level tests ────────────────────────────────────────────


class TestMr14SeedWindowHelper(unittest.TestCase):
    def setUp(self):
        self._saved_start = os.environ.get("MR14_SEED_WINDOW_START")
        self._saved_duration = os.environ.get("MR14_SEED_WINDOW_DURATION_MIN")

    def tearDown(self):
        for key, val in [
            ("MR14_SEED_WINDOW_START", self._saved_start),
            ("MR14_SEED_WINDOW_DURATION_MIN", self._saved_duration),
        ]:
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_default_unset_returns_none(self):
        os.environ.pop("MR14_SEED_WINDOW_START", None)
        from server import _mr14_seed_window
        start, end = _mr14_seed_window()
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_malformed_start_returns_none(self):
        os.environ["MR14_SEED_WINDOW_START"] = "not-a-date"
        from server import _mr14_seed_window
        start, end = _mr14_seed_window()
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_default_duration_90_minutes(self):
        os.environ["MR14_SEED_WINDOW_START"] = "2026-05-03T20:00:00"
        os.environ.pop("MR14_SEED_WINDOW_DURATION_MIN", None)
        from server import _mr14_seed_window
        start, end = _mr14_seed_window()
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        self.assertEqual((end - start).total_seconds(), 90 * 60)

    def test_explicit_duration_override(self):
        os.environ["MR14_SEED_WINDOW_START"] = "2026-05-03T20:00:00"
        os.environ["MR14_SEED_WINDOW_DURATION_MIN"] = "30"
        from server import _mr14_seed_window
        start, end = _mr14_seed_window()
        self.assertEqual((end - start).total_seconds(), 30 * 60)

    def test_naive_datetime_assumes_utc(self):
        """Operator may set the env var without a timezone offset.
        We assume UTC to match how dob_logs.created_at is written."""
        os.environ["MR14_SEED_WINDOW_START"] = "2026-05-03T20:00:00"
        from server import _mr14_seed_window
        start, _ = _mr14_seed_window()
        self.assertEqual(start.tzinfo, timezone.utc)


# ── Endpoint-level test (TestClient + mocked db) ──────────────────


def _build_test_client_with_logs(*, logs):
    """Build a TestClient with auth stubbed + db.dob_logs.find
    returning the supplied logs."""
    import server

    admin_user = {
        "_id": "admin_1", "id": "admin_1", "role": "admin",
        "company_id": "co_test", "company_name": "Test Co",
    }

    async def _fake_admin():
        return admin_user

    server.app.dependency_overrides[server.get_admin_user] = _fake_admin
    server.app.dependency_overrides[server.get_current_user] = _fake_admin

    original_get_company = server.get_user_company_id
    server.get_user_company_id = lambda u: "co_test"
    original_db = server.db

    project_doc = {
        "_id": "proj_test_1",
        "name": "Test Project",
        "company_id": "co_test",
        "is_deleted": False,
    }

    db_mock = MagicMock()
    db_mock.projects.find_one = AsyncMock(return_value=project_doc)

    # Build a chained-find mock that captures the query, then
    # filter logs in memory accordingly.
    captured_query = {}

    class _LogsCursor:
        def __init__(self, items):
            self._items = items

        def sort(self, *args, **kwargs):
            return self

        def skip(self, n):
            self._items = self._items[n:]
            return self

        def limit(self, n):
            self._items = self._items[:n]
            return self

        async def to_list(self, n):
            return self._items[:n]

    def _find(query):
        captured_query.clear()
        captured_query.update(query)
        # Apply minimal filtering for our test cases:
        out = []
        for log in logs:
            if log.get("project_id") != query.get("project_id"):
                continue
            if log.get("is_deleted") is True:
                continue
            # MR.14 seed-suppression filter shape:
            nor = query.get("$nor")
            if nor:
                # Only one suppression clause used.
                clause = nor[0]
                ps = clause.get("previous_status")
                ca = clause.get("created_at") or {}
                gte = ca.get("$gte")
                lt = ca.get("$lt")
                # Suppress if previous_status matches AND created_at in window.
                if (
                    log.get("previous_status") == ps
                    and gte is not None
                    and lt is not None
                ):
                    if gte <= log.get("created_at") < lt:
                        continue  # suppressed
            out.append(log)
        return _LogsCursor(out)

    async def _count_documents(query):
        return len(_find(query)._items)

    db_mock.dob_logs.find = MagicMock(side_effect=_find)
    db_mock.dob_logs.count_documents = AsyncMock(side_effect=_count_documents)

    server.db = db_mock

    def _restore():
        server.db = original_db
        server.get_user_company_id = original_get_company
        server.app.dependency_overrides.clear()

    return TestClient(server.app), _restore, captured_query


class TestSeedSuppressionEndpoint(unittest.TestCase):
    """End-to-end: GET /api/projects/{id}/dob-logs filters seed
    rows by default, includes them when include_seed=true."""

    def setUp(self):
        self._saved_start = os.environ.get("MR14_SEED_WINDOW_START")
        self._saved_duration = os.environ.get("MR14_SEED_WINDOW_DURATION_MIN")
        # Set a known seed window for the test.
        os.environ["MR14_SEED_WINDOW_START"] = "2026-05-03T20:00:00"
        os.environ["MR14_SEED_WINDOW_DURATION_MIN"] = "60"

    def tearDown(self):
        for key, val in [
            ("MR14_SEED_WINDOW_START", self._saved_start),
            ("MR14_SEED_WINDOW_DURATION_MIN", self._saved_duration),
        ]:
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def _logs_fixture(self):
        """One seed row (in-window, prev=None) + one real new
        signal (also prev=None but post-window) + one unrelated
        transition row."""
        in_window = datetime(2026, 5, 3, 20, 30, tzinfo=timezone.utc)
        post_window = datetime(2026, 5, 3, 22, 0, tzinfo=timezone.utc)
        # NB: record_type is required by DOBLogResponse Pydantic
        # validation in the endpoint's serialization step. Without
        # it, every log fails to serialize and the response carries
        # an empty list — which would silently make this test pass
        # the suppression assertion for the wrong reason.
        common = {"project_id": "proj_test_1", "is_deleted": False, "record_type": "permit"}
        return [
            {
                **common,
                "_id": "log_seed_1",
                "raw_dob_id": "permit:B0001",
                "previous_status": None,
                "current_status": "ISSUED",
                "created_at": in_window,
                "detected_at": in_window,
            },
            {
                **common,
                "_id": "log_real_new_2",
                "raw_dob_id": "permit:B0002",
                "previous_status": None,
                "current_status": "ISSUED",
                "created_at": post_window,  # POST seed window
                "detected_at": post_window,
            },
            {
                **common,
                "_id": "log_transition_3",
                "raw_dob_id": "permit:B0003",
                "previous_status": "ISSUED",
                "current_status": "EXPIRED",
                "created_at": in_window,
                "detected_at": in_window,
            },
        ]

    def test_default_view_suppresses_seed_only(self):
        """Default include_seed=False: seed row hidden, real new
        signal AND status-change transition both visible."""
        client, restore, _captured = _build_test_client_with_logs(
            logs=self._logs_fixture(),
        )
        try:
            resp = client.get("/api/projects/proj_test_1/dob-logs")
        finally:
            restore()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # Response shape: {"logs": [...], "total": N, ...}
        logs_list = body.get("logs") if isinstance(body, dict) else body
        ids = [l.get("id") or l.get("_id") for l in (logs_list or [])]
        # The seed row MUST be filtered out.
        self.assertNotIn("log_seed_1", ids, f"seed row should be hidden; got ids={ids}")
        # Real new signal AND transition row MUST appear.
        self.assertIn("log_real_new_2", ids, f"real new-signal row hidden; got ids={ids}")
        self.assertIn("log_transition_3", ids, f"transition row hidden; got ids={ids}")

    def test_include_seed_true_disables_suppression(self):
        """include_seed=true admin/debug view: ALL rows visible."""
        client, restore, _captured = _build_test_client_with_logs(
            logs=self._logs_fixture(),
        )
        try:
            resp = client.get(
                "/api/projects/proj_test_1/dob-logs?include_seed=true",
            )
        finally:
            restore()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # Response shape: {"logs": [...], "total": N, ...}
        logs_list = body.get("logs") if isinstance(body, dict) else body
        ids = [l.get("id") or l.get("_id") for l in (logs_list or [])]
        self.assertIn("log_seed_1", ids)
        self.assertIn("log_real_new_2", ids)
        self.assertIn("log_transition_3", ids)


if __name__ == "__main__":
    unittest.main()
