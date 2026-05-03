"""MR.5+ — third instance of "Pydantic default protects reads but
not writes" — projects.gates (and 5 sibling list fields).

Background
──────────
ProjectCreate.gates: Optional[List[ProjectGate]] = None
    → model_dump() produces {"gates": None}
    → create_project inserts that dict into Mongo as-is
    → ProjectResponse(**project_dict) on the response path validates
      against gates: List[Dict[str, Any]] = []
    → Pydantic v2 raises ValidationError on None for non-Optional List
    → unhandled exception escapes middleware → 500 → browser sees
      CORS preflight failure as a side effect.

Three production project docs landed in this state on 2026-05-03
before this fix: all named "638 Lafayette Avenue, Brooklyn, NY,
USA" — operator's failed create attempts. Without the fix, they
also 500 on GET /projects/{id}.

Same shape as MR.10's filing_reps.credentials regression; same
fix shape (forward-init in write path + defensive lift on read
path + backfill migration for stranded docs).

Tests pinned here:
  1. POST /api/projects with the canonical frontend payload
     (no `gates` key) → 200, response.gates == [].
  2. GET /api/projects/{id} on a legacy doc with gates=None →
     200, response.gates == [].
  3. _lift_project_list_defaults helper is idempotent and
     preserves real data.
  4. _lift_project_list_defaults handles the "key missing"
     case by setting it to [].
"""

from __future__ import annotations

import os
import sys
import unittest
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


# ── Helper unit tests (pure function) ─────────────────────────────


class TestLiftProjectListDefaultsHelper(unittest.TestCase):

    def test_lift_project_list_defaults_idempotent_and_handles_missing(self):
        """Combined coverage: (a) None coerces to []; (b) missing
        keys get [] explicitly; (c) running twice has no further
        effect (the property the migration script depends on for
        safe re-runs); (d) nullish inputs don't raise."""
        from server import (
            _lift_project_list_defaults,
            _PROJECT_LIST_DEFAULT_FIELDS,
        )

        # (a) The production-500 trigger: gates present with None.
        d_none = {"name": "Test", "gates": None, "report_email_list": None}
        result_none = _lift_project_list_defaults(dict(d_none))
        self.assertEqual(result_none["gates"], [])
        self.assertEqual(result_none["report_email_list"], [])
        self.assertEqual(result_none["name"], "Test")

        # (b) Missing keys: defensive cleanup populates them.
        d_missing = {"name": "Test"}
        result_missing = _lift_project_list_defaults(dict(d_missing))
        for fld in _PROJECT_LIST_DEFAULT_FIELDS:
            self.assertIn(fld, result_missing)
            self.assertEqual(result_missing[fld], [])

        # (c) Idempotency: lift(lift(x)) == lift(x).
        once = _lift_project_list_defaults(dict(d_none))
        twice = _lift_project_list_defaults(dict(once))
        self.assertEqual(once, twice)

        # (d) Nullish inputs: pass through without raising.
        self.assertEqual(_lift_project_list_defaults({}), {})
        self.assertIsNone(_lift_project_list_defaults(None))

    def test_lift_does_not_overwrite_non_none_lists(self):
        """Data-preservation: a real value MUST survive the lift.
        Otherwise running the migration on production data would
        silently destroy gate definitions, email distribution
        lists, trade rosters, etc."""
        from server import _lift_project_list_defaults
        gates = [{"name": "Main Gate", "lat": 40.7, "lng": -73.9}]
        emails = ["foo@example.com", "bar@example.com"]
        trades = [{"trade": "electrical", "company": "Acme"}]
        d = {
            "gates": gates,
            "report_email_list": emails,
            "trade_assignments": trades,
            # Mixed state: one real value, one None — verify the
            # real value isn't accidentally clobbered while the
            # None next to it gets lifted.
            "site_device_subfolders": None,
        }
        result = _lift_project_list_defaults(d)
        self.assertEqual(result["gates"], gates)
        self.assertEqual(result["report_email_list"], emails)
        self.assertEqual(result["trade_assignments"], trades)
        self.assertEqual(result["site_device_subfolders"], [])


# ── Endpoint smoke tests ──────────────────────────────────────────


def _make_admin_test_client(db_mock):
    """Build a TestClient with auth dependencies stubbed + a
    MagicMock db. Tests inject behavior into db_mock for the
    specific endpoint paths they exercise."""
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
    server.db = db_mock

    def _restore():
        server.db = original_db
        server.get_user_company_id = original_get_company
        server.app.dependency_overrides.clear()

    return TestClient(server.app), _restore


class TestCreateProjectGatesForwardInit(unittest.TestCase):
    """The exact production trigger: frontend POSTs the canonical
    payload (no gates key), endpoint must respond 200 with
    response.gates == []."""

    def test_create_project_returns_gates_as_empty_list(self):
        import server

        # Inserted doc captured here so the test can assert what
        # actually went into Mongo (forward-init proof).
        captured_insert = {}

        async def _fake_insert_one(doc):
            captured_insert.update(doc)
            return MagicMock(inserted_id="proj_test_id")

        async def _fake_audit_log_insert(doc):
            return MagicMock(inserted_id="audit_test_id")

        db_mock = MagicMock()
        db_mock.projects.insert_one = _fake_insert_one
        db_mock.compliance_alerts.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="ca_id")
        )
        db_mock.audit_logs.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="audit_id")
        )

        client, restore = _make_admin_test_client(db_mock)

        # Patch the BIN/BBL fetch so the test doesn't hit live
        # NYC GeoSearch / Socrata. Returns a no-match shape that's
        # safe for any address.
        async def _fake_fetch_nyc_bin(address):
            return {
                "nyc_bin": None,
                "bbl": None,
                "track_dob_status": False,
                "normalized_address": None,
            }

        try:
            with patch.object(
                server, "fetch_nyc_bin_from_address", _fake_fetch_nyc_bin,
            ):
                # Canonical frontend payload — no gates key, no
                # report_email_list, no site_device_subfolders,
                # no trade_assignments. Mirrors
                # frontend/app/projects/index.jsx:105-110.
                resp = client.post("/api/projects", json={
                    "name": "638 Lafayette Avenue, Brooklyn, NY, USA",
                    "address": "638 Lafayette Avenue, Brooklyn, NY, USA",
                    "location": "638 Lafayette Avenue, Brooklyn, NY, USA",
                    "project_class": "regular",
                })
        finally:
            restore()

        self.assertEqual(
            resp.status_code, 200,
            f"expected 200, got {resp.status_code}: body={resp.text!r}",
        )
        body = resp.json()
        self.assertEqual(body["gates"], [])
        self.assertEqual(body["report_email_list"], [])
        self.assertEqual(body["site_device_subfolders"], [])
        self.assertEqual(body["trade_assignments"], [])
        self.assertEqual(body["nfc_tags"], [])

        # The forward-init proof: the doc that landed in Mongo has
        # gates=[] (NOT null). Pre-MR.5+-fix, this would have been
        # gates=None — the production-500 root cause.
        self.assertEqual(captured_insert.get("gates"), [])
        self.assertIsNotNone(captured_insert.get("gates"))


class TestGetProjectLegacyNullGates(unittest.TestCase):
    """The legacy-data trigger: a project doc with gates=None
    (the three '638 Lafayette' stranded docs) must read back
    cleanly via GET /projects/{id} after the fix."""

    def test_get_project_with_legacy_null_gates_returns_empty_list(self):
        # Doc shape mirrors what the operator's failed create
        # attempts left in production: gates=null explicitly,
        # other list fields entirely missing.
        legacy_doc = {
            "_id": "legacy_proj_1",
            "name": "638 Lafayette Avenue, Brooklyn, NY, USA",
            "address": "638 Lafayette Avenue, Brooklyn, NY, USA",
            "company_id": "co_test",
            "status": "active",
            "is_deleted": False,
            "gates": None,  # ← THE TRIGGER
            # report_email_list, site_device_subfolders,
            # trade_assignments, required_logbooks all MISSING (the
            # observed production state per the diagnosis dump).
        }

        db_mock = MagicMock()
        db_mock.projects.find_one = AsyncMock(return_value=legacy_doc)

        client, restore = _make_admin_test_client(db_mock)
        try:
            resp = client.get("/api/projects/legacy_proj_1")
        finally:
            restore()

        self.assertEqual(
            resp.status_code, 200,
            f"expected 200, got {resp.status_code}: body={resp.text!r}",
        )
        body = resp.json()
        # gates lifted from null → [] by the read-path defensive lift.
        self.assertEqual(body["gates"], [])
        # Missing fields use Pydantic defaults on response construction.
        self.assertEqual(body["report_email_list"], [])
        self.assertEqual(body["trade_assignments"], [])


if __name__ == "__main__":
    unittest.main()
