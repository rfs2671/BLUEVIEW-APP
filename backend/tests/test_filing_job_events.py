"""MR.6 — FilingJob audit_log invariants + state-transition coverage.

Coverage:
  - _filing_job_audit_event() helper produces the canonical shape.
  - /api/internal/job-result with filing_job_id propagates to:
      • filing_jobs.update_one with $set + $push audit_log
      • Status mappings: filed → FILED, completed → COMPLETED,
        failed → FAILED, cancelled → CANCELLED.
      • Cancellation override: when cancellation_requested=True AND
        worker reports a non-cancelled status, force CANCELLED.
      • dob_confirmation_number, when present, lands on filing_jobs
        AND on permit_renewals.
  - Stale-claim watchdog (_stale_claim_watchdog):
      • Stale claimed/in_progress filing_jobs with retry_count<3
        revert to QUEUED, retry_count++, audit_log appends
        "stale_claim_recovered".
      • retry_count>=3 → FAILED with reason "exceeded_retry_limit"
        and audit_log "retry_limit_exceeded".
  - DELETE cancellation:
      • Queued: status → CANCELLED, audit_log appends "cancelled".
      • In-flight: cancellation_requested=True, audit_log appends
        "cancellation_requested" — status preserved.
      • Terminal: 409 (cannot cancel).
"""

from __future__ import annotations

import asyncio
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
os.environ.setdefault("WORKER_SECRET", "test-secret-32hex")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _client():
    import server
    return TestClient(server.app)


def _setup_user_client(*, role: str = "admin", company_id: str = "co_a"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": company_id}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


HEADERS = {"X-Worker-Secret": "test-secret-32hex"}


# ── _filing_job_audit_event helper ─────────────────────────────────

class TestAuditEventHelper(unittest.TestCase):

    def test_event_shape(self):
        from server import _filing_job_audit_event
        ev = _filing_job_audit_event(
            event_type="claimed",
            actor="worker_id_42",
            detail="Worker picked up the job",
            metadata={"queue_depth": 7},
        )
        self.assertEqual(ev["event_type"], "claimed")
        self.assertEqual(ev["actor"], "worker_id_42")
        self.assertEqual(ev["detail"], "Worker picked up the job")
        self.assertEqual(ev["metadata"], {"queue_depth": 7})
        self.assertIsInstance(ev["timestamp"], datetime)

    def test_metadata_defaults_to_empty_dict(self):
        from server import _filing_job_audit_event
        ev = _filing_job_audit_event(
            event_type="queued", actor="op", detail="x",
        )
        self.assertEqual(ev["metadata"], {})


# ── /internal/job-result drives filing_jobs ────────────────────────

class TestJobResultFilingJobsTransitions(unittest.TestCase):

    def _stub_db_with_job(self, *, status="in_progress", cancellation_requested=False):
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.update_one = AsyncMock()
        mock_db.agent_job_results = MagicMock()
        mock_db.agent_job_results.insert_one = AsyncMock()
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find_one = AsyncMock(return_value={
            "_id": "fj_1",
            "status": status,
            "cancellation_requested": cancellation_requested,
            "retry_count": 0,
        })
        mock_db.filing_jobs.update_one = AsyncMock()
        return mock_db

    def test_filed_appends_filed_event_and_sets_status(self):
        import server
        mock_db = self._stub_db_with_job(status="in_progress")
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/job-result",
                json={
                    "job_id": "j", "job_type": "dob_now_filing",
                    "filing_job_id": "fj_1",
                    "permit_renewal_id": "r1", "worker_id": "w1",
                    "result": {"status": "filed", "detail": "ok",
                               "dob_confirmation_number": "DOB-12345"},
                },
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        # filing_jobs update fired.
        mock_db.filing_jobs.update_one.assert_awaited_once()
        args = mock_db.filing_jobs.update_one.await_args.args
        update_doc = args[1]
        self.assertEqual(update_doc["$set"]["status"], "filed")
        self.assertEqual(update_doc["$set"]["dob_confirmation_number"], "DOB-12345")
        # Audit event $push.
        event = update_doc["$push"]["audit_log"]
        self.assertEqual(event["event_type"], "filed")
        self.assertEqual(event["actor"], "w1")

    def test_failed_appends_failed_event_and_records_reason(self):
        import server
        mock_db = self._stub_db_with_job(status="in_progress")
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/job-result",
                json={
                    "job_id": "j", "job_type": "dob_now_filing",
                    "filing_job_id": "fj_1",
                    "permit_renewal_id": "r1", "worker_id": "w1",
                    "result": {"status": "failed", "detail": "captcha"},
                },
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        update_doc = mock_db.filing_jobs.update_one.await_args.args[1]
        self.assertEqual(update_doc["$set"]["status"], "failed")
        self.assertEqual(update_doc["$set"]["failure_reason"], "captcha")
        self.assertEqual(update_doc["$push"]["audit_log"]["event_type"], "failed")

    def test_cancellation_override_when_worker_reports_completed(self):
        """Operator clicked cancel while the worker was filing.
        Worker still managed to finish DOB and reported 'completed'.
        Cloud must override to CANCELLED — operator intent wins."""
        import server
        mock_db = self._stub_db_with_job(
            status="in_progress",
            cancellation_requested=True,
        )
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/job-result",
                json={
                    "job_id": "j", "job_type": "dob_now_filing",
                    "filing_job_id": "fj_1",
                    "permit_renewal_id": "r1", "worker_id": "w1",
                    "result": {"status": "completed", "detail": "ok"},
                },
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        update_doc = mock_db.filing_jobs.update_one.await_args.args[1]
        self.assertEqual(update_doc["$set"]["status"], "cancelled")
        self.assertEqual(update_doc["$push"]["audit_log"]["event_type"], "cancelled")

    def test_no_filing_job_id_falls_back_to_renewal_only(self):
        """Pre-MR.6 worker doesn't carry filing_job_id — backend
        must keep transitioning permit_renewals like before."""
        import server
        mock_db = self._stub_db_with_job(status="in_progress")
        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            resp = _client().post(
                "/api/internal/job-result",
                json={
                    "job_id": "j", "job_type": "dob_now_filing",
                    # no filing_job_id
                    "permit_renewal_id": "r1", "worker_id": "w1",
                    "result": {"status": "filed"},
                },
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        # filing_jobs branch not invoked.
        mock_db.filing_jobs.update_one.assert_not_awaited()
        # permit_renewals still transitioned.
        mock_db.permit_renewals.update_one.assert_awaited_once()


# ── Stale-claim watchdog: filing_jobs branch ───────────────────────

class TestStaleClaimWatchdogFilingJobs(unittest.TestCase):

    def _stub_db_with_stale_jobs(self, jobs):
        mock_db = MagicMock()
        # permit_renewals branch — empty.
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.update_many = AsyncMock(
            return_value=MagicMock(modified_count=0),
        )
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.update_one = AsyncMock()

        async def _async_iter(self):
            for j in jobs:
                yield j

        cursor = MagicMock()
        cursor.__aiter__ = _async_iter
        mock_db.filing_jobs.find = MagicMock(return_value=cursor)
        return mock_db

    def test_recovers_stale_job_under_retry_limit(self):
        import server
        stale_dt = datetime.now(timezone.utc) - timedelta(minutes=45)
        jobs = [{
            "_id": "fj_stale_1",
            "status": "claimed",
            "claimed_at": stale_dt,
            "claimed_by_worker_id": "w_dead",
            "retry_count": 0,
        }]
        mock_db = self._stub_db_with_stale_jobs(jobs)
        with patch.object(server, "db", mock_db):
            _run(server._stale_claim_watchdog())
        # Updated to queued, retry_count=1, audit appended.
        mock_db.filing_jobs.update_one.assert_awaited_once()
        update_doc = mock_db.filing_jobs.update_one.await_args.args[1]
        self.assertEqual(update_doc["$set"]["status"], "queued")
        self.assertEqual(update_doc["$set"]["retry_count"], 1)
        self.assertEqual(
            update_doc["$push"]["audit_log"]["event_type"],
            "stale_claim_recovered",
        )

    def test_marks_failed_when_retry_limit_exceeded(self):
        import server
        stale_dt = datetime.now(timezone.utc) - timedelta(minutes=45)
        jobs = [{
            "_id": "fj_doomed",
            "status": "in_progress",
            "started_at": stale_dt,
            "claimed_by_worker_id": "w_repeat",
            "retry_count": 3,  # at the limit
        }]
        mock_db = self._stub_db_with_stale_jobs(jobs)
        with patch.object(server, "db", mock_db):
            _run(server._stale_claim_watchdog())
        update_doc = mock_db.filing_jobs.update_one.await_args.args[1]
        self.assertEqual(update_doc["$set"]["status"], "failed")
        self.assertEqual(update_doc["$set"]["failure_reason"], "exceeded_retry_limit")
        self.assertEqual(
            update_doc["$push"]["audit_log"]["event_type"],
            "retry_limit_exceeded",
        )


# ── DELETE cancellation flow ───────────────────────────────────────

class TestCancelFilingJob(unittest.TestCase):

    def _stub_db(self, *, job_status="queued",
                 cancellation_requested=False, renewal_company_id="co_a"):
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(
            return_value={"_id": "r1", "company_id": renewal_company_id},
        )
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find_one = AsyncMock(return_value={
            "_id": "fj_1",
            "permit_renewal_id": "r1",
            "status": job_status,
            "cancellation_requested": cancellation_requested,
        })
        mock_db.filing_jobs.update_one = AsyncMock()
        return mock_db

    def test_queued_cancels_immediately(self):
        import server
        client, restore = _setup_user_client(company_id="co_a")
        mock_db = self._stub_db(job_status="queued")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/permit-renewals/r1/filing-jobs/fj_1"
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            update_doc = mock_db.filing_jobs.update_one.await_args.args[1]
            self.assertEqual(update_doc["$set"]["status"], "cancelled")
            self.assertEqual(
                update_doc["$push"]["audit_log"]["event_type"], "cancelled"
            )
        finally:
            restore()

    def test_inflight_uses_soft_cancel_flag(self):
        import server
        client, restore = _setup_user_client(company_id="co_a")
        mock_db = self._stub_db(job_status="in_progress")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/permit-renewals/r1/filing-jobs/fj_1"
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            update_doc = mock_db.filing_jobs.update_one.await_args.args[1]
            # Status NOT flipped — soft cancel.
            self.assertNotIn("status", update_doc["$set"])
            self.assertTrue(update_doc["$set"]["cancellation_requested"])
            self.assertEqual(
                update_doc["$push"]["audit_log"]["event_type"],
                "cancellation_requested",
            )
        finally:
            restore()

    def test_terminal_status_409(self):
        import server
        client, restore = _setup_user_client(company_id="co_a")
        mock_db = self._stub_db(job_status="completed")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/permit-renewals/r1/filing-jobs/fj_1"
                )
            self.assertEqual(resp.status_code, 409)
            self.assertEqual(
                resp.json()["detail"]["code"], "cannot_cancel_terminal"
            )
        finally:
            restore()

    def test_cross_tenant_403(self):
        import server
        client, restore = _setup_user_client(company_id="co_other")
        mock_db = self._stub_db(renewal_company_id="co_a", job_status="queued")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete(
                    "/api/permit-renewals/r1/filing-jobs/fj_1"
                )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
