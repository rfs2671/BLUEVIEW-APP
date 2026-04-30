"""MR.6 — GET /api/admin/filing-jobs (owner-tier observability surface).

Coverage:
  - Owner-tier auth gate (admin → 403, owner → 200).
  - Filters: status, company_id, created_after / created_before.
  - Sort: validated against VALID_FILING_JOB_SORT_FIELDS, sort_dir
    must be -1 or 1.
  - Invalid status → 400.
  - Invalid sort_by → 400.
  - Invalid date format → 400.
  - Pagination response shape: {items, total, limit, skip, has_more}.
  - Ciphertext stripped from items defensively even if it sneaks
    onto a doc.
  - GET /api/permit-renewals/{id}/filing-jobs — per-renewal listing
    smoke (includes tenant guard).
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


def _setup_client(*, role: str = "owner", company_id: str = "co_a"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": company_id}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _make_mongo_cursor(jobs):
    """Build a Mongo cursor mock that supports .sort().skip().limit()
    chaining and async iteration."""

    async def _async_iter(self):
        for j in jobs:
            yield j

    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.skip = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.__aiter__ = _async_iter
    return cursor


def _job(_id="fj_1", status="queued", company_id="co_a",
         created_at=None, retry_count=0):
    return {
        "_id": _id,
        "permit_renewal_id": "r1",
        "company_id": company_id,
        "filing_rep_id": "rep_1",
        "credential_version": 1,
        "pw2_field_map": {},
        "status": status,
        "retry_count": retry_count,
        "audit_log": [],
        "created_at": created_at or datetime.now(timezone.utc),
        "updated_at": created_at or datetime.now(timezone.utc),
    }


# ── /admin/filing-jobs ─────────────────────────────────────────────

class TestAdminListAuth(unittest.TestCase):

    def test_admin_role_rejected(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.get("/api/admin/filing-jobs")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_owner_role_accepted(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find = MagicMock(return_value=_make_mongo_cursor([]))
        mock_db.filing_jobs.count_documents = AsyncMock(return_value=0)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/filing-jobs")
            self.assertEqual(resp.status_code, 200, resp.text)
        finally:
            restore()


class TestAdminListFilters(unittest.TestCase):

    def test_filter_by_status(self):
        import server
        client, restore = _setup_client(role="owner")
        jobs = [_job(_id="fj_1", status="queued")]
        mock_db = MagicMock()
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find = MagicMock(return_value=_make_mongo_cursor(jobs))
        mock_db.filing_jobs.count_documents = AsyncMock(return_value=1)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/filing-jobs?status=queued")
            self.assertEqual(resp.status_code, 200)
            # Filter passed through.
            query = mock_db.filing_jobs.find.call_args.args[0]
            self.assertEqual(query["status"], "queued")
        finally:
            restore()

    def test_invalid_status_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/filing-jobs?status=bogus")
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()

    def test_filter_by_company_id(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find = MagicMock(return_value=_make_mongo_cursor([]))
        mock_db.filing_jobs.count_documents = AsyncMock(return_value=0)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/filing-jobs?company_id=co_xyz")
            self.assertEqual(resp.status_code, 200)
            query = mock_db.filing_jobs.find.call_args.args[0]
            self.assertEqual(query["company_id"], "co_xyz")
        finally:
            restore()

    def test_filter_by_date_range(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find = MagicMock(return_value=_make_mongo_cursor([]))
        mock_db.filing_jobs.count_documents = AsyncMock(return_value=0)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/admin/filing-jobs"
                    "?created_after=2026-01-01T00:00:00Z"
                    "&created_before=2026-12-31T23:59:59Z"
                )
            self.assertEqual(resp.status_code, 200)
            query = mock_db.filing_jobs.find.call_args.args[0]
            self.assertIn("created_at", query)
            self.assertIn("$gte", query["created_at"])
            self.assertIn("$lte", query["created_at"])
        finally:
            restore()

    def test_invalid_date_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get(
                    "/api/admin/filing-jobs?created_after=not-a-date"
                )
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()

    def test_invalid_sort_by_400(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/filing-jobs?sort_by=worker_id")
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()


class TestAdminListResponseShape(unittest.TestCase):

    def test_pagination_envelope(self):
        import server
        client, restore = _setup_client(role="owner")
        jobs = [_job(_id=f"fj_{i}") for i in range(3)]
        mock_db = MagicMock()
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find = MagicMock(return_value=_make_mongo_cursor(jobs))
        mock_db.filing_jobs.count_documents = AsyncMock(return_value=10)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/filing-jobs?limit=3&skip=0")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(len(body["items"]), 3)
            self.assertEqual(body["total"], 10)
            self.assertEqual(body["limit"], 3)
            self.assertEqual(body["skip"], 0)
            self.assertTrue(body["has_more"])
        finally:
            restore()

    def test_strips_ciphertext_defensively(self):
        """The schema doesn't carry ciphertext on filing_jobs, but if
        a future migration ever attaches one, the admin response must
        strip it. This is belt-and-suspenders."""
        import server
        client, restore = _setup_client(role="owner")
        leaky_job = _job()
        leaky_job["encrypted_ciphertext"] = "should-not-leak"
        mock_db = MagicMock()
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find = MagicMock(
            return_value=_make_mongo_cursor([leaky_job])
        )
        mock_db.filing_jobs.count_documents = AsyncMock(return_value=1)
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/admin/filing-jobs")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertNotIn("encrypted_ciphertext", body["items"][0])
        finally:
            restore()


# ── Per-renewal /filing-jobs listing ───────────────────────────────

class TestPerRenewalFilingJobsList(unittest.TestCase):

    def test_lists_jobs_for_renewal(self):
        import server
        client, restore = _setup_client(role="admin", company_id="co_a")
        jobs = [_job(_id="fj_1"), _job(_id="fj_2")]
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value={
            "_id": "r1", "company_id": "co_a",
        })
        mock_db.filing_jobs = MagicMock()
        mock_db.filing_jobs.find = MagicMock(return_value=_make_mongo_cursor(jobs))
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r1/filing-jobs")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["total"], 2)
            self.assertEqual(len(body["filing_jobs"]), 2)
        finally:
            restore()

    def test_cross_tenant_403(self):
        import server
        client, restore = _setup_client(role="admin", company_id="co_other")
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value={
            "_id": "r1", "company_id": "co_a",
        })
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r1/filing-jobs")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_404_when_renewal_missing(self):
        import server
        client, restore = _setup_client(role="admin", company_id="co_a")
        mock_db = MagicMock()
        mock_db.permit_renewals = MagicMock()
        mock_db.permit_renewals.find_one = AsyncMock(return_value=None)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/permit-renewals/r_missing/filing-jobs")
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
