"""MR.14 commit 4a — seed-suppression via stored field.

Replaces the commit-2b/3 time-window heuristic
(MR14_SEED_WINDOW_START env var) with a stored
`is_seed_transition: bool` field set at insert time.

Pins:
  • GET /api/projects/{id}/dob-logs default view filters
    {is_seed_transition: {$ne: true}} — synthetic seeds hidden.
  • include_seed=true disables the filter (admin/debug view).
  • The legacy time-window helper is GONE; tests for it removed.
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


# ── Source-level pin: the time-window helper is gone ──────────────


class TestTimeWindowHelperRemoved(unittest.TestCase):
    """The MR14_SEED_WINDOW_START env var path is dead post-4a.
    Static-source check so a future commit can't accidentally
    re-introduce it."""

    def test_no_mr14_seed_window_function(self):
        """The helper function is gone AND no code path reads the
        env vars. Comment mentions of the var name (historical
        context for "what we removed") are allowed."""
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8", errors="ignore")
        self.assertNotIn("def _mr14_seed_window", text)
        # No code path reads the env vars. Comments are allowed.
        self.assertNotIn('os.environ.get("MR14_SEED_WINDOW_START"', text)
        self.assertNotIn("os.environ.get('MR14_SEED_WINDOW_START'", text)
        self.assertNotIn('os.environ.get("MR14_SEED_WINDOW_DURATION_MIN"', text)
        self.assertNotIn("os.environ.get('MR14_SEED_WINDOW_DURATION_MIN'", text)

    def test_field_based_filter_is_used(self):
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8", errors="ignore")
        # The filter shape MUST appear at the GET endpoint. Match
        # the actual Python source idiom (subscript-assign, single
        # quotes for the key, double quotes for the operator).
        self.assertIn('query["is_seed_transition"]', text)
        self.assertIn('"$ne": True', text)


# ── End-to-end test: field-based filter ──────────────────────────


def _build_test_client_with_logs(*, logs):
    """TestClient with auth stubbed + db.dob_logs.find returning
    the supplied logs through a chained-cursor mock that respects
    the new is_seed_transition filter."""
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
        out = []
        for log in logs:
            if log.get("project_id") != query.get("project_id"):
                continue
            if log.get("is_deleted") is True:
                continue
            # MR.14 commit 4a — field-based seed-suppression filter.
            seed_filter = query.get("is_seed_transition")
            if isinstance(seed_filter, dict) and seed_filter.get("$ne") is True:
                if log.get("is_seed_transition") is True:
                    continue
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
    """End-to-end: GET filters rows with is_seed_transition=True
    by default; include_seed=true exposes them."""

    def _logs_fixture(self):
        """One seed row (is_seed_transition=True) + one real new
        signal (is_seed_transition=False) + one unrelated
        transition row (is_seed_transition=False)."""
        now = datetime.now(timezone.utc)
        common = {
            "project_id": "proj_test_1",
            "is_deleted": False,
            "record_type": "permit",
            "company_id": "co_test",
            "raw_dob_id": "permit:X",
            "ai_summary": "Test",
            "severity": "Action",
        }
        return [
            {
                **common,
                "_id": "log_seed",
                "raw_dob_id": "permit:B0001",
                "is_seed_transition": True,
                "previous_status": None,
                "current_status": "ISSUED",
                "detected_at": now,
                "created_at": now,
            },
            {
                **common,
                "_id": "log_real_new",
                "raw_dob_id": "permit:B0002",
                "is_seed_transition": False,
                "previous_status": None,
                "current_status": "ISSUED",
                "detected_at": now,
                "created_at": now,
            },
            {
                **common,
                "_id": "log_transition",
                "raw_dob_id": "permit:B0003",
                "is_seed_transition": False,
                "previous_status": "ISSUED",
                "current_status": "EXPIRED",
                "detected_at": now,
                "created_at": now,
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
        logs_list = body.get("logs") or []
        ids = [l.get("id") for l in logs_list]
        self.assertNotIn("log_seed", ids, f"seed row should be hidden; got {ids}")
        self.assertIn("log_real_new", ids)
        self.assertIn("log_transition", ids)

    def test_include_seed_true_disables_suppression(self):
        """include_seed=true: ALL rows visible including seeds."""
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
        ids = [l.get("id") for l in (body.get("logs") or [])]
        self.assertIn("log_seed", ids)
        self.assertIn("log_real_new", ids)
        self.assertIn("log_transition", ids)


# ── Insert-time stamping ─────────────────────────────────────────


class TestIsSeedTransitionStampedOnInsert(unittest.TestCase):
    """Static-source check: the discriminator MUST be stamped on
    the inserted dob_log doc (not just used as a local variable
    for alert gating). Otherwise the GET filter has nothing to
    query against."""

    def test_dob_path_stores_is_seed_transition(self):
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8", errors="ignore")
        # The DOB-side insertion path MUST set the field on dob_log.
        self.assertIn('dob_log["is_seed_transition"] = is_seed_transition', text)

    def test_311_path_stores_is_seed_transition(self):
        path = _BACKEND / "server.py"
        text = path.read_text(encoding="utf-8", errors="ignore")
        # The 311-side insertion path MUST set the field on doc.
        self.assertIn('doc["is_seed_transition"] = is_seed_transition_311', text)


if __name__ == "__main__":
    unittest.main()
