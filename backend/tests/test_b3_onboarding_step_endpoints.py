"""Phase B3 — per-step persistence endpoints.

Pin the contract for the three new onboarding-only endpoints that
each step's submit hits:

  • POST /api/onboarding/company       (step 1)
  • POST /api/onboarding/project       (step 2)
  • POST /api/onboarding/filing-reps   (step 3)

The fourth step (notification preferences) reuses the existing
B1a/B1b PUT endpoint and is exercised by its own pre-existing tests.

Each endpoint is gated on the user's onboarding_step being in the
in-flight set {1,2,3,4}. A user post-completion or pre-B3 (no
field on doc) gets 409 — the endpoints can't be replayed after the
flow is done.
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


def _setup_client(*, user):
    """Override the auth dependency. Caller supplies the user dict."""
    import server

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _build_db(**kwargs):
    db = MagicMock()
    db.companies = MagicMock()
    db.companies.find_one = AsyncMock(return_value=kwargs.get("company_existing"))
    db.companies.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=kwargs.get("company_inserted_id", "co_new"))
    )
    db.companies.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    db.users = MagicMock()
    db.users.find_one = AsyncMock(return_value=kwargs.get("user_doc"))
    db.users.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    db.projects = MagicMock()
    db.projects.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=kwargs.get("project_inserted_id", "proj_new"))
    )
    db.projects.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    return db


# ──────────────────────────────────────────────────────────────────
# POST /api/onboarding/company  (step 1)
# ──────────────────────────────────────────────────────────────────


class TestOnboardingCompany(unittest.TestCase):

    def test_creates_company_and_links_user(self):
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": None,
            "onboarding_step": "1",
        }
        db = _build_db(company_existing=None)
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/company",
                    json={
                        "name": "ACME Construction Inc",
                        "license_number": "0123456",
                        "office_address": "123 Main St",
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertIn("company_id", body)
                self.assertEqual(body["name"], "ACME Construction Inc")

                # Company doc had key fields.
                inserted = db.companies.insert_one.call_args[0][0]
                self.assertEqual(inserted["name"], "ACME Construction Inc")
                self.assertEqual(inserted["gc_license_number"], "0123456")
                self.assertEqual(inserted["office_address"], "123 Main St")
                self.assertEqual(inserted["filing_reps"], [])

                # User got linked.
                user_set = db.users.update_one.call_args[0][1]["$set"]
                self.assertIn("company_id", user_set)
                self.assertEqual(user_set["company_name"], "ACME Construction Inc")
        finally:
            restore()

    def test_links_user_to_existing_company_with_same_name(self):
        """Two co-workers from the same GC: the second user lands on
        the existing tenant rather than creating a duplicate."""
        import server

        user = {
            "id": "u2", "_id": "u2",
            "role": "admin",
            "company_id": None,
            "onboarding_step": "1",
        }
        existing = {"_id": "co_existing", "name": "ACME Construction Inc"}
        db = _build_db(company_existing=existing)
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/company",
                    json={"name": "ACME Construction Inc"},
                )
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertEqual(body["company_id"], "co_existing")
                # No new company doc was created.
                db.companies.insert_one.assert_not_called()
                # User still got linked.
                self.assertTrue(db.users.update_one.called)
        finally:
            restore()

    def test_409_when_user_already_has_company(self):
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": "co_existing",
            "onboarding_step": "1",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/company",
                    json={"name": "Other Co"},
                )
                self.assertEqual(r.status_code, 409)
        finally:
            restore()

    def test_409_when_onboarding_completed(self):
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": None,
            "onboarding_step": "completed",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/company",
                    json={"name": "Test Co"},
                )
                self.assertEqual(r.status_code, 409)
        finally:
            restore()

    def test_422_on_empty_name(self):
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": None,
            "onboarding_step": "1",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/company",
                    json={"name": "   "},
                )
                self.assertEqual(r.status_code, 422)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# POST /api/onboarding/project  (step 2)
# ──────────────────────────────────────────────────────────────────


class TestOnboardingProject(unittest.TestCase):

    def test_creates_project_under_user_company(self):
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": "co_a",
            "onboarding_step": "2",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            # BIN auto-resolve isn't required for the test; skip
            # network by patching the helper to return a stub.
            with patch.object(server, "db", db), \
                 patch.object(server, "fetch_nyc_bin_from_address",
                              new=AsyncMock(return_value={
                                  "nyc_bin": "1000001",
                                  "bbl": "1000010001",
                                  "track_dob_status": True,
                                  "normalized_address": "123 Front St, Brooklyn, NY 11201",
                              })):
                r = client.post(
                    "/api/onboarding/project",
                    json={
                        "name": "123 Front Street Renovation",
                        "address": "123 Front St, Brooklyn, NY 11201",
                        "expected_start_date": "2026-06-01",
                        "expected_completion_date": "2027-06-01",
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)

                inserted = db.projects.insert_one.call_args[0][0]
                self.assertEqual(inserted["name"], "123 Front Street Renovation")
                self.assertEqual(inserted["company_id"], "co_a")
                # track_dob_status defaults to True so the 15-min poll
                # picks it up immediately.
                self.assertTrue(inserted["track_dob_status"])
                self.assertEqual(inserted["expected_start_date"], "2026-06-01")
                self.assertEqual(inserted["expected_completion_date"], "2027-06-01")
                self.assertEqual(inserted["nyc_bin"], "1000001")
        finally:
            restore()

    def test_409_without_company_id(self):
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": None,
            "onboarding_step": "2",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/project",
                    json={"name": "Test Project"},
                )
                self.assertEqual(r.status_code, 409)
        finally:
            restore()

    def test_soft_fail_on_bin_lookup_error(self):
        """A GeoSearch outage doesn't break onboarding — the project
        gets created without a BIN, the nightly poller backfills it
        later via auto-heal."""
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": "co_a",
            "onboarding_step": "2",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db), \
                 patch.object(server, "fetch_nyc_bin_from_address",
                              new=AsyncMock(side_effect=RuntimeError("boom"))):
                r = client.post(
                    "/api/onboarding/project",
                    json={
                        "name": "Foo",
                        "address": "100 Some St",
                    },
                )
                self.assertEqual(r.status_code, 200)
                inserted = db.projects.insert_one.call_args[0][0]
                self.assertIsNone(inserted.get("nyc_bin"))
                self.assertTrue(inserted["track_dob_status"])
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# POST /api/onboarding/filing-reps  (step 3)
# ──────────────────────────────────────────────────────────────────


class TestOnboardingFilingReps(unittest.TestCase):

    def test_pushes_reps_into_company(self):
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": "co_a",
            "onboarding_step": "3",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/filing-reps",
                    json={
                        "filing_reps": [
                            {
                                "name": "Jane Doe",
                                "license_number": "0123",
                                "email": "jane@example.com",
                                "phone": "555-555-5555",
                            },
                            {"name": "John Smith"},
                        ],
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["added"], 2)

                # $push call carried the right structure.
                args = db.companies.update_one.call_args[0]
                update = args[1]
                pushed = update["$push"]["filing_reps"]["$each"]
                self.assertEqual(len(pushed), 2)
                self.assertEqual(pushed[0]["name"], "Jane Doe")
                # Credentials list seeded empty — B3 doesn't collect creds.
                self.assertEqual(pushed[0]["credentials"], [])
                # is_primary defaults False.
                self.assertFalse(pushed[0]["is_primary"])
        finally:
            restore()

    def test_drops_empty_rows(self):
        """Empty-name rows from the FE form (the user added a row
        and didn't fill it) get silently skipped."""
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": "co_a",
            "onboarding_step": "3",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/filing-reps",
                    json={
                        "filing_reps": [
                            {"name": ""},
                            {"name": "  "},
                            {"name": "Real Person", "license_number": "X"},
                        ],
                    },
                )
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["added"], 1)
                pushed = db.companies.update_one.call_args[0][1]["$push"]["filing_reps"]["$each"]
                self.assertEqual(len(pushed), 1)
                self.assertEqual(pushed[0]["name"], "Real Person")
        finally:
            restore()

    def test_409_without_company_id(self):
        import server

        user = {
            "id": "u1", "_id": "u1",
            "role": "admin",
            "company_id": None,
            "onboarding_step": "3",
        }
        db = _build_db()
        client, restore = _setup_client(user=user)
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/onboarding/filing-reps",
                    json={"filing_reps": [{"name": "Jane"}]},
                )
                self.assertEqual(r.status_code, 409)
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
