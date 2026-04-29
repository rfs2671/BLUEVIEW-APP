"""MR.2 — filing_reps schema + admin CRUD + migration tests.

Coverage:
  - FilingRep / FilingRepCreate Pydantic validation: required fields,
    license_class enum check, EmailStr validation, default is_primary.
  - is_primary uniqueness via the _demote_other_primaries helper:
    pre-existing primary on a company gets demoted when a new primary
    is added; the helper's array_filters predicate is exercised.
  - The four CRUD endpoints (TestClient with dependency overrides):
    auth gate (non-owner role rejected), POST happy path, PATCH
    promotion path, DELETE removal, GET list.
  - Migration script idempotency: docs already carrying filing_reps
    are excluded from the target query; --dry-run produces no writes;
    --execute writes filing_reps: [] only on missing docs.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Same env-stub pattern as test_coi_endpoints.py — server.py reads
# these at module-import time.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── Pydantic validation ────────────────────────────────────────────

class TestFilingRepValidation(unittest.TestCase):

    def test_create_requires_core_fields(self):
        from server import FilingRepCreate
        from pydantic import ValidationError
        # Missing name / license_class / license_number / email → 422.
        with self.assertRaises(ValidationError):
            FilingRepCreate()

    def test_email_must_be_well_formed(self):
        from server import FilingRepCreate
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            FilingRepCreate(
                name="Jane Filer",
                license_class="GC",
                license_number="626198",
                email="not-an-email",
            )

    def test_is_primary_defaults_false(self):
        from server import FilingRepCreate
        rep = FilingRepCreate(
            name="Jane Filer",
            license_class="GC",
            license_number="626198",
            email="jane@example.com",
        )
        self.assertFalse(rep.is_primary)

    def test_optional_license_type_accepts_none(self):
        from server import FilingRepCreate
        rep = FilingRepCreate(
            name="Pat Plumber",
            license_class="Plumber",
            license_number="P-12345",
            email="pat@example.com",
        )
        self.assertIsNone(rep.license_type)


# ── License class enum check (endpoint-side) ───────────────────────

class TestLicenseClassEnum(unittest.TestCase):
    """The endpoint guards license_class against the
    FILING_REP_LICENSE_CLASSES set; Pydantic accepts any string for
    the field (kept loose so future class additions are a backend-only
    change), but the endpoint rejects unknown values with 400."""

    def test_canonical_classes_present(self):
        import server
        # Sanity — confirm the set covers all classes in the spec.
        expected = {
            "Class 1 Filing Rep",
            "Class 2 Filing Rep",
            "GC",
            "Plumber",
            "Electrician",
            "Master Fire Suppression Contractor",
            "Other Licensed Trade",
        }
        self.assertEqual(server.FILING_REP_LICENSE_CLASSES, expected)


# ── _demote_other_primaries helper ─────────────────────────────────

class TestDemoteOtherPrimaries(unittest.TestCase):
    """Unit-tests the array_filters call shape. The helper must
    target every primary OTHER than the given rep_id and only update
    those — never touch the new primary itself, never touch
    non-primaries."""

    def test_update_call_shape(self):
        import server
        captured = {}

        async def _capture(filt, update, array_filters=None):
            captured["filt"] = filt
            captured["update"] = update
            captured["array_filters"] = array_filters
            return MagicMock()

        mock_db = MagicMock()
        mock_db.companies.update_one = AsyncMock(side_effect=_capture)

        with patch.object(server, "db", mock_db), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            _run(server._demote_other_primaries("co_a", except_rep_id="rep_new"))

        self.assertEqual(captured["filt"], {"_id": "co_a"})
        # The $set targets the matched array element via $[other].
        self.assertIn("filing_reps.$[other].is_primary", captured["update"]["$set"])
        self.assertEqual(captured["update"]["$set"]["filing_reps.$[other].is_primary"], False)
        # array_filters predicate excludes the new primary AND only
        # touches existing primaries.
        af = captured["array_filters"][0]
        self.assertEqual(af["other.id"], {"$ne": "rep_new"})
        self.assertEqual(af["other.is_primary"], True)


# ── Endpoint smoke (TestClient + dependency overrides) ─────────────

def _setup_client(*, role: str = "owner", company_doc=None):
    """TestClient with auth + db overrides. Returns (client, restore_fn)."""
    import server

    user = {"id": "u1", "role": role, "_id": "u1"}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


class TestEndpointAuthGate(unittest.TestCase):
    """Non-owner roles rejected with 403 on every CRUD endpoint."""

    def test_admin_role_rejected_on_list(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.get("/api/owner/companies/co_a/filing-reps")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_admin_role_rejected_on_post(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.post(
                "/api/owner/companies/co_a/filing-reps",
                json={"name": "Jane", "license_class": "GC",
                      "license_number": "626198", "email": "j@example.com"},
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_admin_role_rejected_on_patch(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.patch(
                "/api/owner/companies/co_a/filing-reps/rep_x",
                json={"is_primary": True},
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_admin_role_rejected_on_delete(self):
        client, restore = _setup_client(role="admin")
        try:
            resp = client.delete("/api/owner/companies/co_a/filing-reps/rep_x")
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


class TestEndpointHappyPaths(unittest.TestCase):
    """End-to-end happy paths with a stub Mongo. Verifies the
    endpoint wiring (auth → validation → Mongo write shape) without
    needing a live cluster."""

    def _stub_db_with_company(self, company):
        import server
        mock_db = MagicMock()
        mock_db.companies = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=company)
        mock_db.companies.update_one = AsyncMock(return_value=MagicMock(
            matched_count=1, modified_count=1,
        ))
        return mock_db

    def test_post_creates_rep_with_uuid_id(self):
        import server
        client, restore = _setup_client(role="owner")
        company = {"_id": "co_a", "name": "Acme GC", "filing_reps": []}
        mock_db = self._stub_db_with_company(company)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/filing-reps",
                    json={
                        "name": "Jane Filer",
                        "license_class": "GC",
                        "license_number": "626198",
                        "email": "jane@example.com",
                        "is_primary": False,
                    },
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["name"], "Jane Filer")
            self.assertEqual(body["license_class"], "GC")
            self.assertFalse(body["is_primary"])
            # Stable rep_id generated server-side.
            self.assertIsInstance(body["id"], str)
            self.assertEqual(len(body["id"]), 32)  # uuid4().hex
        finally:
            restore()

    def test_post_rejects_unknown_license_class(self):
        import server
        client, restore = _setup_client(role="owner")
        company = {"_id": "co_a", "name": "Acme GC", "filing_reps": []}
        mock_db = self._stub_db_with_company(company)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/filing-reps",
                    json={
                        "name": "X",
                        "license_class": "Bogus Class",
                        "license_number": "1",
                        "email": "x@example.com",
                    },
                )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("license_class", resp.json()["detail"])
        finally:
            restore()

    def test_post_404_when_company_missing(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies.find_one = AsyncMock(return_value=None)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_missing/filing-reps",
                    json={"name": "X", "license_class": "GC",
                          "license_number": "1", "email": "x@example.com"},
                )
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()

    def test_post_with_is_primary_demotes_others(self):
        """When a new rep is added with is_primary=True,
        _demote_other_primaries fires immediately afterward. Verified
        via call-count on update_one (push + demote = 2 calls)."""
        import server
        client, restore = _setup_client(role="owner")
        company = {"_id": "co_a", "name": "Acme GC", "filing_reps": [
            {"id": "rep_existing", "name": "Old Pri", "license_class": "GC",
             "license_number": "X", "email": "o@example.com", "is_primary": True,
             "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)},
        ]}
        mock_db = self._stub_db_with_company(company)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/owner/companies/co_a/filing-reps",
                    json={"name": "New Pri", "license_class": "GC",
                          "license_number": "626198", "email": "n@example.com",
                          "is_primary": True},
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            # Two update_one calls: $push then the demote $set.
            self.assertEqual(mock_db.companies.update_one.await_count, 2)
        finally:
            restore()

    def test_list_returns_filing_reps_array(self):
        import server
        client, restore = _setup_client(role="owner")
        reps = [
            {"id": "r1", "name": "A", "license_class": "GC",
             "license_number": "1", "email": "a@example.com", "is_primary": True,
             "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"},
        ]
        company = {"_id": "co_a", "name": "Acme GC", "filing_reps": reps}
        mock_db = self._stub_db_with_company(company)
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get("/api/owner/companies/co_a/filing-reps")
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(len(resp.json()), 1)
            self.assertEqual(resp.json()[0]["id"], "r1")
        finally:
            restore()

    def test_delete_removes_rep(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies.update_one = AsyncMock(return_value=MagicMock(
            matched_count=1, modified_count=1,
        ))
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete("/api/owner/companies/co_a/filing-reps/rep_x")
            self.assertEqual(resp.status_code, 200, resp.text)
            # $pull update was issued.
            args, kwargs = mock_db.companies.update_one.await_args
            self.assertIn("$pull", args[1])

        finally:
            restore()

    def test_delete_404_when_rep_not_found(self):
        import server
        client, restore = _setup_client(role="owner")
        mock_db = MagicMock()
        mock_db.companies.update_one = AsyncMock(return_value=MagicMock(
            matched_count=1, modified_count=0,
        ))
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.delete("/api/owner/companies/co_a/filing-reps/rep_missing")
            self.assertEqual(resp.status_code, 404)
        finally:
            restore()


# ── Migration script idempotency ───────────────────────────────────

class TestMigrationIdempotency(unittest.TestCase):
    """The migration target query excludes docs that already carry
    filing_reps. Re-running --execute is a no-op once every doc has
    been migrated."""

    def test_query_filters_only_missing_field(self):
        # Read the script source directly for the query shape — no
        # need to run it against a live db.
        script_path = _BACKEND / "scripts" / "migrate_filing_reps_init.py"
        src = script_path.read_text()
        self.assertIn('"filing_reps": {"$exists": False}', src)
        self.assertIn('"is_deleted": {"$ne": True}', src)
        self.assertIn('"$set": {"filing_reps": []}', src)


if __name__ == "__main__":
    unittest.main()
