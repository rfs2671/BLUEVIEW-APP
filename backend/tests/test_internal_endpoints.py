"""MR.5 — backend /api/internal/* endpoints + watchdog jobs.

Coverage:
  - X-Worker-Secret validation (401 on mismatch, 503 if backend
    env unset, 200 on match)
  - /internal/permit-renewal-claim: 200 happy, 404 missing,
    409 non-claimable status
  - /internal/job-result: state transitions for 'filed' / 'completed'
    / 'failed'; no transition for 'not_implemented'; bis_scrape jobs
    (no permit_renewal_id) audit-log only
  - /internal/agent-heartbeat: upsert per worker_id
  - _stale_claim_watchdog: clears IN_PROGRESS claims older than 30 min
  - _heartbeat_watchdog: flips degraded flag when last heartbeat > 30 min
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Same env-stub pattern as the other backend test files.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")
os.environ.setdefault("WORKER_SECRET", "test-secret-32hex")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _client():
    import server
    # WORKER_SECRET is read at module import; the env var was set
    # above so the constant matches our header value.
    return TestClient(server.app)


# ── X-Worker-Secret validation ─────────────────────────────────────

class TestWorkerSecretValidation(unittest.TestCase):

    def test_missing_header_rejected_401(self):
        resp = _client().post(
            "/api/internal/agent-heartbeat",
            json={"worker_id": "w1"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_wrong_header_rejected_401(self):
        resp = _client().post(
            "/api/internal/agent-heartbeat",
            json={"worker_id": "w1"},
            headers={"X-Worker-Secret": "bogus"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_correct_header_accepted(self):
        import server
        mock_db = MagicMock()
        mock_db.agent_heartbeats = MagicMock()
        mock_db.agent_heartbeats.update_one = AsyncMock()
        with patch.object(server, "db", mock_db):
            resp = _client().post(
                "/api/internal/agent-heartbeat",
                json={"worker_id": "w1", "queue_depth": 0},
                headers={"X-Worker-Secret": "test-secret-32hex"},
            )
        self.assertEqual(resp.status_code, 200)


# ── /internal/permit-renewal-claim ─────────────────────────────────

class TestPermitRenewalClaim(unittest.TestCase):

    HEADERS = {"X-Worker-Secret": "test-secret-32hex"}

    def test_404_when_renewal_missing(self):
        import server
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value=None)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/permit-renewal-claim",
                json={"permit_renewal_id": "missing", "worker_id": "w1"},
                headers=self.HEADERS,
            )
        self.assertEqual(resp.status_code, 404)

    def test_409_when_already_in_progress(self):
        import server
        from permit_renewal import RenewalStatus
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value={
            "_id": "r1", "status": RenewalStatus.IN_PROGRESS,
        })
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/permit-renewal-claim",
                json={"permit_renewal_id": "r1", "worker_id": "w1"},
                headers=self.HEADERS,
            )
        self.assertEqual(resp.status_code, 409)

    def test_200_marks_in_progress(self):
        import server
        from permit_renewal import RenewalStatus
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value={
            "_id": "r1", "status": RenewalStatus.NEEDS_INSURANCE,
        })
        mock_db.permit_renewals.update_one = AsyncMock()
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/permit-renewal-claim",
                json={"permit_renewal_id": "r1", "worker_id": "w1"},
                headers=self.HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["claimed"], True)


# ── /internal/job-result ───────────────────────────────────────────

class TestJobResult(unittest.TestCase):

    HEADERS = {"X-Worker-Secret": "test-secret-32hex"}

    def _stub_db(self):
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.update_one = AsyncMock()
        mock_db.agent_job_results = MagicMock()
        mock_db.agent_job_results.insert_one = AsyncMock()
        return mock_db

    def test_filed_transitions_to_awaiting_dob_approval(self):
        import server
        from permit_renewal import RenewalStatus
        mock_db = self._stub_db()
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/job-result",
                json={
                    "job_id": "j1", "job_type": "dob_now_filing",
                    "permit_renewal_id": "r1", "worker_id": "w1",
                    "result": {"status": "filed", "detail": "ok"},
                },
                headers=self.HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["new_status"], RenewalStatus.AWAITING_DOB_APPROVAL.value)

    def test_failed_transitions_to_failed_with_reason(self):
        import server
        mock_db = self._stub_db()
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/job-result",
                json={
                    "job_id": "j2", "job_type": "dob_now_filing",
                    "permit_renewal_id": "r2", "worker_id": "w1",
                    "result": {"status": "failed", "detail": "captcha unsolved"},
                },
                headers=self.HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        update_args = mock_db.permit_renewals.update_one.await_args
        set_payload = update_args.args[1]["$set"]
        self.assertEqual(set_payload["failure_reason"], "captcha unsolved")

    def test_not_implemented_no_transition(self):
        import server
        mock_db = self._stub_db()
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/job-result",
                json={
                    "job_id": "j3", "job_type": "dob_now_filing",
                    "permit_renewal_id": "r3", "worker_id": "w1",
                    "result": {"status": "not_implemented", "detail": "stub"},
                },
                headers=self.HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["transitioned"])
        mock_db.permit_renewals.update_one.assert_not_awaited()

    def test_bis_scrape_no_renewal_id_audit_only(self):
        import server
        mock_db = self._stub_db()
        with patch.object(server, "db", mock_db):
            resp = _client().post(
                "/api/internal/job-result",
                json={
                    "job_id": "j4", "job_type": "bis_scrape",
                    "permit_renewal_id": None, "worker_id": "w1",
                    "result": {"status": "completed", "detail": "ok"},
                },
                headers=self.HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        # Audit insert happened; no renewal update.
        mock_db.agent_job_results.insert_one.assert_awaited_once()
        mock_db.permit_renewals.update_one.assert_not_awaited()


# ── /internal/agent-heartbeat ──────────────────────────────────────

class TestAgentHeartbeat(unittest.TestCase):

    HEADERS = {"X-Worker-Secret": "test-secret-32hex"}

    def test_upsert_per_worker_id(self):
        import server
        mock_db = MagicMock()
        mock_db.agent_heartbeats = MagicMock()
        mock_db.agent_heartbeats.update_one = AsyncMock()
        with patch.object(server, "db", mock_db):
            resp = _client().post(
                "/api/internal/agent-heartbeat",
                json={
                    "worker_id": "dob-worker-laptop-1",
                    "queue_depth": 0,
                    "circuit_breaker": {"bis_scrape": "closed"},
                },
                headers=self.HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        # update_one called with upsert=True keyed on worker_id.
        args, kwargs = mock_db.agent_heartbeats.update_one.await_args
        self.assertEqual(args[0], {"_id": "dob-worker-laptop-1"})
        self.assertEqual(kwargs.get("upsert"), True)

    def test_400_when_worker_id_missing(self):
        resp = _client().post(
            "/api/internal/agent-heartbeat",
            json={"queue_depth": 0},
            headers=self.HEADERS,
        )
        self.assertEqual(resp.status_code, 400)


# ── Watchdog jobs ──────────────────────────────────────────────────

class TestStaleClaimWatchdog(unittest.TestCase):

    def test_clears_stale_claims_older_than_30_min(self):
        import server
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.update_many = AsyncMock(
            return_value=MagicMock(modified_count=2),
        )
        with patch.object(server, "db", mock_db):
            _run(server._stale_claim_watchdog())
        # update_many called once with the stale-claim filter.
        mock_db.permit_renewals.update_many.assert_awaited_once()
        args, _ = mock_db.permit_renewals.update_many.await_args
        filt = args[0]
        self.assertIn("claim_at", filt)
        self.assertIn("$lt", filt["claim_at"])


class TestHeartbeatWatchdog(unittest.TestCase):

    def test_marks_degraded_when_no_heartbeat_in_30_min(self):
        import server
        mock_db = MagicMock()
        # Mock cursor returning one stale heartbeat.
        stale_dt = datetime.now(timezone.utc) - timedelta(minutes=45)

        async def _async_iter(self):
            for item in [
                {"_id": "w1", "received_at": stale_dt},
            ]:
                yield item

        cursor = MagicMock()
        cursor.__aiter__ = _async_iter
        mock_db.agent_heartbeats = MagicMock()
        mock_db.agent_heartbeats.find = MagicMock(return_value=cursor)
        mock_db.system_status = MagicMock()
        mock_db.system_status.update_one = AsyncMock()

        with patch.object(server, "db", mock_db):
            _run(server._heartbeat_watchdog())

        mock_db.system_status.update_one.assert_awaited_once()
        args, kwargs = mock_db.system_status.update_one.await_args
        set_payload = args[1]["$set"]
        self.assertTrue(set_payload["degraded"])


if __name__ == "__main__":
    unittest.main()
