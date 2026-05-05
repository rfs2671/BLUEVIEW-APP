"""Phase B1b — GET /api/users/me/recent-signals tests.

Covers:
  • happy path: aggregates dob_logs by signal_kind for the caller's
    company over the requested window.
  • days param sanitization: 0 / negative → 1; absurd → capped at 90.
  • site-mode device → 403 (preferences are per-user, not per-device).
  • no company_id → empty payload (graceful, doesn't 500).
  • aggregation exception → soft-fail empty counts (don't break the
    UI's settings page render).

Tenant scoping: pipeline filter pins company_id; we verify by reading
the literal $match clause that was passed to db.dob_logs.aggregate.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _setup_client(*, role="admin", user_id="u1", company_id="co_a", site_mode=False):
    import server
    user = {
        "id": user_id, "_id": user_id, "user_id": user_id,
        "role": role, "company_id": company_id,
        "site_mode": site_mode,
    }
    async def _fake_user():
        return user
    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _build_db_with_aggregate(rows):
    """Mock motor db whose dob_logs.aggregate yields the supplied
    grouping rows (each row: {_id: signal_kind, count: int})."""
    db = MagicMock()
    captured = {"pipeline": None}

    async def _async_iter(items):
        for it in items:
            yield it

    class _Cursor:
        def __init__(self, items):
            self._items = items
        def __aiter__(self):
            return _async_iter(self._items).__aiter__()

    def _aggregate(pipeline):
        captured["pipeline"] = pipeline
        return _Cursor(rows)

    db.dob_logs = MagicMock()
    db.dob_logs.aggregate = MagicMock(side_effect=_aggregate)
    return db, captured


# ── Happy path ────────────────────────────────────────────────────

class TestHappyPath(unittest.TestCase):

    def test_returns_counts_grouped_by_signal_kind(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        rows = [
            {"_id": "violation_dob", "count": 3},
            {"_id": "complaint_311", "count": 12},
            {"_id": "permit_issued", "count": 5},
        ]
        mock_db, captured = _build_db_with_aggregate(rows)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/users/me/recent-signals?days=7")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["days"], 7)
            self.assertEqual(body["total"], 3 + 12 + 5)
            self.assertEqual(body["counts_by_signal_kind"]["violation_dob"], 3)
            self.assertEqual(body["counts_by_signal_kind"]["complaint_311"], 12)
            # Pipeline scopes to the caller's company.
            match_stage = captured["pipeline"][0]["$match"]
            self.assertEqual(match_stage["company_id"], "co_a")
            self.assertIn("detected_at", match_stage)
        finally:
            restore()


# ── Window sanitization ──────────────────────────────────────────

class TestDaysSanitization(unittest.TestCase):

    def test_zero_days_floors_to_one(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db, _ = _build_db_with_aggregate([])
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/users/me/recent-signals?days=0")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["days"], 1)
        finally:
            restore()

    def test_negative_days_floors_to_one(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db, _ = _build_db_with_aggregate([])
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/users/me/recent-signals?days=-5")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["days"], 1)
        finally:
            restore()

    def test_absurd_days_capped_at_90(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db, _ = _build_db_with_aggregate([])
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/users/me/recent-signals?days=9999")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["days"], 90)
        finally:
            restore()


# ── Auth + company scoping ────────────────────────────────────────

class TestAuthAndScoping(unittest.TestCase):

    def test_site_mode_device_rejected_403(self):
        import server
        client, restore = _setup_client(site_mode=True)
        try:
            resp = client.get("/api/users/me/recent-signals")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_no_company_id_returns_empty_payload(self):
        import server
        client, restore = _setup_client(company_id=None)
        # We don't even build a mock db; the endpoint returns the
        # empty-shaped payload before touching Mongo.
        try:
            resp = client.get("/api/users/me/recent-signals")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["counts_by_signal_kind"], {})
            self.assertEqual(body["total"], 0)
        finally:
            restore()


class TestSoftFailOnAggregate(unittest.TestCase):

    def test_aggregate_exception_returns_empty_counts(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = MagicMock()
        mock_db.dob_logs = MagicMock()
        mock_db.dob_logs.aggregate = MagicMock(
            side_effect=Exception("boom"),
        )
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/users/me/recent-signals")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["counts_by_signal_kind"], {})
            self.assertEqual(resp.json()["total"], 0)
        finally:
            restore()


# ── Static-source pin: route stays public, tenant filter present ──

class TestRoutePins(unittest.TestCase):

    def test_endpoint_path_pinned(self):
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn(
            '"/users/me/recent-signals"',
            text,
            "GET /users/me/recent-signals must remain wired",
        )

    def test_company_id_filter_in_pipeline(self):
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8")
        # Tenant scoping must remain — defensive against a future
        # commit that "simplifies" the pipeline and drops it.
        self.assertIn('"company_id": company_id', text)


if __name__ == "__main__":
    unittest.main()
