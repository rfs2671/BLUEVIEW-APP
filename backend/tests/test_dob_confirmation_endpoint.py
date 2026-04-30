"""MR.8 — GET /api/permit-renewals/{id}/dob-confirmation tests.

Coverage:
  • happy completed shape: status=completed, confirmation_number from
    FilingJob, old/new expiration set, watch_started_at populated,
    days_in_dob_queue computed.
  • awaiting_dob_filing: pre-claim state — status returned, watch
    fields null/None.
  • awaiting_dob_approval: filing in DOB queue — watch_started_at and
    days_in_dob_queue populated from the `filed` audit event.
  • stuck_at_dob flag surfaces when a stuck_at_dob audit event exists.
  • tenant guard: 403 cross-tenant.
  • 404 when renewal missing.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _setup_client(*, role="admin", company_id="co_a"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": company_id}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _build_db(
    *,
    renewal=None,
    filing_job=None,
):
    mock_db = MagicMock()
    mock_db.permit_renewals = MagicMock()
    mock_db.permit_renewals.find_one = AsyncMock(return_value=renewal)
    mock_db.filing_jobs = MagicMock()
    mock_db.filing_jobs.find_one = AsyncMock(return_value=filing_job)
    return mock_db


# ── completed shape ────────────────────────────────────────────────

class TestCompletedShape(unittest.TestCase):

    def test_full_completed_response(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        renewal = {
            "_id": "r1",
            "company_id": "co_a",
            "status": "completed",
            "current_expiration": "2026-04-01",
            "new_expiration_date": "2027-04-01",
            "filed_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        }
        filed_iso = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        filing_job = {
            "_id": "fj1",
            "permit_renewal_id": "r1",
            "dob_confirmation_number": "DOB-77777",
            "audit_log": [
                {"event_type": "queued",  "timestamp": filed_iso},
                {"event_type": "claimed", "timestamp": filed_iso},
                {"event_type": "filed",   "timestamp": filed_iso},
                {"event_type": "renewal_confirmed_in_dob",
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "metadata": {"old_expiration": "2026-04-01",
                              "new_expiration": "2027-04-01"}},
            ],
        }
        mock_db = _build_db(renewal=renewal, filing_job=filing_job)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r1/dob-confirmation")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["status"], "completed")
            self.assertEqual(body["confirmation_number"], "DOB-77777")
            self.assertEqual(body["old_expiration"], "2026-04-01")
            self.assertEqual(body["new_expiration_date"], "2027-04-01")
            self.assertIsNotNone(body["watch_started_at"])
            # ~7 days, give or take rounding.
            self.assertGreaterEqual(body["days_in_dob_queue"], 6)
            self.assertLessEqual(body["days_in_dob_queue"], 7)
            self.assertFalse(body["stuck_at_dob"])
        finally:
            restore()


# ── partial states ─────────────────────────────────────────────────

class TestPartialStates(unittest.TestCase):

    def test_awaiting_dob_filing_returns_partial(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        renewal = {
            "_id": "r1", "company_id": "co_a",
            "status": "awaiting_dob_filing",
            "current_expiration": "2026-04-01",
        }
        # No FilingJob audit_log entries yet beyond queued.
        filing_job = {
            "_id": "fj1", "permit_renewal_id": "r1",
            "audit_log": [{"event_type": "queued",
                           "timestamp": datetime.now(timezone.utc).isoformat()}],
        }
        mock_db = _build_db(renewal=renewal, filing_job=filing_job)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r1/dob-confirmation")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["status"], "awaiting_dob_filing")
            self.assertIsNone(body["new_expiration_date"])
            # No `filed` event yet → no watch_started_at.
            self.assertIsNone(body["watch_started_at"])
            self.assertIsNone(body["days_in_dob_queue"])
        finally:
            restore()

    def test_awaiting_dob_approval_populates_queue_days(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        renewal = {
            "_id": "r1", "company_id": "co_a",
            "status": "awaiting_dob_approval",
            "current_expiration": "2026-04-01",
        }
        filed_iso = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        filing_job = {
            "_id": "fj1", "permit_renewal_id": "r1",
            "audit_log": [
                {"event_type": "queued", "timestamp": filed_iso},
                {"event_type": "filed",  "timestamp": filed_iso},
            ],
        }
        mock_db = _build_db(renewal=renewal, filing_job=filing_job)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r1/dob-confirmation")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["status"], "awaiting_dob_approval")
            self.assertIsNotNone(body["watch_started_at"])
            self.assertGreaterEqual(body["days_in_dob_queue"], 2)
            self.assertLessEqual(body["days_in_dob_queue"], 3)
        finally:
            restore()

    def test_stuck_flag_surfaces_when_audit_event_present(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        renewal = {
            "_id": "r1", "company_id": "co_a",
            "status": "awaiting_dob_approval",
            "current_expiration": "2026-04-01",
        }
        filed_iso = (datetime.now(timezone.utc) - timedelta(days=18)).isoformat()
        filing_job = {
            "_id": "fj1", "permit_renewal_id": "r1",
            "audit_log": [
                {"event_type": "filed",        "timestamp": filed_iso},
                {"event_type": "stuck_at_dob", "timestamp": datetime.now(timezone.utc).isoformat()},
            ],
        }
        mock_db = _build_db(renewal=renewal, filing_job=filing_job)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r1/dob-confirmation")
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["stuck_at_dob"])
        finally:
            restore()


# ── auth + 404 ─────────────────────────────────────────────────────

class TestEndpointAuth(unittest.TestCase):

    def test_404_when_renewal_missing(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _build_db(renewal=None)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r_missing/dob-confirmation")
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_403_cross_tenant(self):
        import server
        client, restore = _setup_client(company_id="co_other")
        renewal = {"_id": "r1", "company_id": "co_a", "status": "completed"}
        mock_db = _build_db(renewal=renewal)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r1/dob-confirmation")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
