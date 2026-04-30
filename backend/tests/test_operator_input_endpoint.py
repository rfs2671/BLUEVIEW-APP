"""MR.7 — POST /api/permit-renewals/{id}/filing-jobs/{job_id}/operator-input.

The operator → worker channel for CAPTCHA / 2FA responses raised
during a live filing. UI panel from FilingStatusCard.jsx posts to
this endpoint; worker consumes the matching `operator_response`
event from audit_log on its next poll.

Coverage:
  - Happy path: appends operator_response audit event with metadata
    {response_kind, response_value}; returns updated FilingJob.
  - In-progress gate: 409 when status is queued/claimed/terminal.
  - Tenant guard: cross-tenant returns 403.
  - Body validation: missing/invalid event_type returns 422; missing
    or empty `value` returns 422.
  - 404 when renewal or filing_job missing.
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
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _setup_client(*, role: str = "admin", company_id: str = "co_a"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": company_id}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _stub_db(*, job_status="in_progress", renewal_company_id="co_a",
             missing_renewal=False, missing_job=False):
    mock_db = MagicMock()
    mock_db.permit_renewals = MagicMock()
    mock_db.permit_renewals.find_one = AsyncMock(
        return_value=None if missing_renewal else {
            "_id": "r1", "company_id": renewal_company_id,
        },
    )
    mock_db.filing_jobs = MagicMock()
    if missing_job:
        mock_db.filing_jobs.find_one = AsyncMock(return_value=None)
    else:
        # The endpoint calls find_one twice: once before update (status
        # check), once after (refetch for response). Return the same job
        # both times so the response shape is straightforward to assert.
        job = {
            "_id": "fj_1",
            "permit_renewal_id": "r1",
            "company_id": renewal_company_id,
            "status": job_status,
            "audit_log": [],
        }
        mock_db.filing_jobs.find_one = AsyncMock(return_value=job)
    mock_db.filing_jobs.update_one = AsyncMock()
    return mock_db


HEADERS = {}


# ── Happy path ─────────────────────────────────────────────────────

class TestOperatorInputHappyPath(unittest.TestCase):

    def test_captcha_response_appends_audit_event(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _stub_db(job_status="in_progress")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/r1/filing-jobs/fj_1/operator-input",
                    json={"event_type": "captcha_response", "value": "abc123"},
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            mock_db.filing_jobs.update_one.assert_awaited_once()
            update_doc = mock_db.filing_jobs.update_one.await_args.args[1]
            self.assertIn("$push", update_doc)
            event = update_doc["$push"]["audit_log"]
            self.assertEqual(event["event_type"], "operator_response")
            self.assertEqual(event["metadata"]["response_kind"], "captcha_response")
            self.assertEqual(event["metadata"]["response_value"], "abc123")
        finally:
            restore()

    def test_2fa_response_appends_audit_event(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _stub_db(job_status="in_progress")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/r1/filing-jobs/fj_1/operator-input",
                    json={"event_type": "2fa_response", "value": "654321"},
                )
            self.assertEqual(resp.status_code, 200)
            event = mock_db.filing_jobs.update_one.await_args.args[1]["$push"]["audit_log"]
            self.assertEqual(event["metadata"]["response_kind"], "2fa_response")
        finally:
            restore()


# ── Status gate ────────────────────────────────────────────────────

class TestOperatorInputStatusGate(unittest.TestCase):

    def _post(self, mock_db):
        import server
        client, restore = _setup_client(company_id="co_a")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                return client.post(
                    "/api/permit-renewals/r1/filing-jobs/fj_1/operator-input",
                    json={"event_type": "captcha_response", "value": "x"},
                )
        finally:
            restore()

    def test_409_when_queued(self):
        resp = self._post(_stub_db(job_status="queued"))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"]["code"], "not_in_progress")

    def test_409_when_claimed(self):
        resp = self._post(_stub_db(job_status="claimed"))
        self.assertEqual(resp.status_code, 409)

    def test_409_when_completed(self):
        resp = self._post(_stub_db(job_status="completed"))
        self.assertEqual(resp.status_code, 409)

    def test_409_when_failed(self):
        resp = self._post(_stub_db(job_status="failed"))
        self.assertEqual(resp.status_code, 409)


# ── Tenant guard ───────────────────────────────────────────────────

class TestOperatorInputTenantGuard(unittest.TestCase):

    def test_403_cross_tenant(self):
        import server
        client, restore = _setup_client(company_id="co_other")
        mock_db = _stub_db(renewal_company_id="co_a")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/r1/filing-jobs/fj_1/operator-input",
                    json={"event_type": "captcha_response", "value": "x"},
                )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


# ── Body validation ────────────────────────────────────────────────

class TestOperatorInputBodyValidation(unittest.TestCase):

    def _post(self, body):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _stub_db(job_status="in_progress")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                return client.post(
                    "/api/permit-renewals/r1/filing-jobs/fj_1/operator-input",
                    json=body,
                )
        finally:
            restore()

    def test_invalid_event_type_422(self):
        resp = self._post({"event_type": "bogus_kind", "value": "x"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"]["code"], "invalid_event_type")

    def test_missing_event_type_422(self):
        resp = self._post({"value": "x"})
        self.assertEqual(resp.status_code, 422)

    def test_empty_value_422(self):
        resp = self._post({"event_type": "captcha_response", "value": ""})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"]["code"], "invalid_value")

    def test_whitespace_value_422(self):
        resp = self._post({"event_type": "captcha_response", "value": "   "})
        self.assertEqual(resp.status_code, 422)

    def test_non_string_value_422(self):
        resp = self._post({"event_type": "captcha_response", "value": 12345})
        self.assertEqual(resp.status_code, 422)


# ── 404 cases ──────────────────────────────────────────────────────

class TestOperatorInputNotFound(unittest.TestCase):

    def test_404_when_renewal_missing(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _stub_db(missing_renewal=True)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/r_missing/filing-jobs/fj_1/operator-input",
                    json={"event_type": "captcha_response", "value": "x"},
                )
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_404_when_job_missing(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _stub_db(missing_job=True)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/r1/filing-jobs/fj_missing/operator-input",
                    json={"event_type": "captcha_response", "value": "x"},
                )
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
