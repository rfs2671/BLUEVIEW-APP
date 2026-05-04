"""MR.14 commit 4c — POST /api/permit-renewals/{id}/start-renewal-clicked.

Pins the new endpoint that replaced the legacy /file enqueue path:

  • Records a `manual_renewal_started` event on
    permit_renewals.{id}.manual_renewal_audit_log
    + stamps manual_renewal_started_at + manual_renewal_started_by.
  • Returns the MR.4 PW2 mapper output for the slide-out panel.
  • 404 when the renewal is missing.
  • 403 cross-tenant.
  • 409 when filing-readiness reports ready=false (with the blocker
    list surfaced in the response detail).
  • Static-source pin: the legacy POST /file 503-stub is GONE
    (no `enqueue_filing_job` definition + no `/{permit_renewal_id}/file`
    route declaration).
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


def _setup_client(*, role="admin", company_id="co_a"):
    import server
    user = {"id": "u1", "_id": "u1", "role": role, "company_id": company_id}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _build_db(*, renewal):
    mock_db = MagicMock()
    mock_db.permit_renewals = MagicMock()
    mock_db.permit_renewals.find_one = AsyncMock(return_value=renewal)
    mock_db.permit_renewals.update_one = AsyncMock()
    return mock_db


# ── Static-source pins ─────────────────────────────────────────────

class TestLegacyEndpointGone(unittest.TestCase):
    """The legacy /file 503-stub is fully removed in 4c. Pin via
    source-text inspection so a future commit can't accidentally
    re-introduce the endpoint."""

    def test_no_enqueue_filing_job_definition(self):
        path = _BACKEND / "permit_renewal.py"
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("def enqueue_filing_job", text)

    def test_no_file_route_decorator(self):
        path = _BACKEND / "permit_renewal.py"
        text = path.read_text(encoding="utf-8")
        # The literal route declaration the FastAPI decorator carried.
        # We allow the historical-context comment ("POST /file") to
        # mention the path; only the @api_router.post(...) declaration
        # must be absent.
        self.assertNotIn(
            '@api_router.post("/permit-renewals/{permit_renewal_id}/file")',
            text,
        )

    def test_start_renewal_route_is_declared(self):
        path = _BACKEND / "permit_renewal.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn(
            '"/permit-renewals/{permit_renewal_id}/start-renewal-clicked"',
            text,
        )
        self.assertIn("async def start_renewal_clicked", text)


# ── Behavioural tests ──────────────────────────────────────────────

def _stub_readiness(ready=True, blockers=None):
    class _R:
        pass
    r = _R()
    r.ready = ready
    r.blockers = blockers or []
    return r


def _stub_field_map():
    """Minimal Pw2FieldMap-shaped object whose model_dump() matches
    the contract the endpoint serializes."""
    class _F:
        pass
    f = _F()
    f.unmappable_fields = [
        "work_permit_number: not stored on dob_logs; canonical -PL/-SP/-FB ...",
    ]

    def _model_dump():
        return {
            "permit_renewal_id": "r1",
            "permit_class": "DOB_NOW",
            "fields": {
                "applicant_name": {
                    "value": "Jane Filer",
                    "field_type": "text",
                    "source": "filing_rep",
                },
                "job_filing_number": {
                    "value": "B00736930",
                    "field_type": "text",
                    "source": "dob_log",
                },
            },
            "attachments_required": [
                "Current Certificate of Insurance (GL/WC/DBL)",
            ],
            "notes": [],
            "unmappable_fields": f.unmappable_fields,
        }
    f.model_dump = _model_dump
    return f


class TestHappyPath(unittest.TestCase):

    def _renewal(self, **overrides):
        base = {
            "_id": "r1",
            "company_id": "co_a",
            "status": "eligible",
            "current_expiration": "2026-06-01",
        }
        base.update(overrides)
        return base

    def test_records_audit_log_and_returns_field_map(self):
        import server
        import lib.filing_readiness as fr_mod
        import lib.pw2_field_mapper as pw_mod

        client, restore = _setup_client(role="admin", company_id="co_a")
        mock_db = _build_db(renewal=self._renewal())

        try:
            with patch.object(fr_mod, "check_filing_readiness",
                              AsyncMock(return_value=_stub_readiness(ready=True))), \
                 patch.object(pw_mod, "map_pw2_fields",
                              AsyncMock(return_value=_stub_field_map())), \
                 patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/r1/start-renewal-clicked"
                )
        finally:
            restore()

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["renewal_id"], "r1")
        self.assertIn("started_at", body)
        self.assertEqual(body["started_by"], "u1")

        field_map = body["field_map"]
        self.assertEqual(field_map["permit_renewal_id"], "r1")
        self.assertEqual(field_map["permit_class"], "DOB_NOW")
        self.assertIn("applicant_name", field_map["fields"])
        self.assertIn(
            "Current Certificate of Insurance (GL/WC/DBL)",
            field_map["attachments_required"],
        )
        # Partition is computed from unmappable_fields.
        self.assertEqual(field_map["critical_unmappable_fields"], [])
        self.assertEqual(len(field_map["non_critical_unmappable_fields"]), 1)

        # Audit log + started_at + started_by are all written in a
        # single update_one call ($set + $push).
        mock_db.permit_renewals.update_one.assert_awaited_once()
        args, kwargs = mock_db.permit_renewals.update_one.await_args
        update_doc = args[1]
        self.assertIn("$set", update_doc)
        self.assertIn("manual_renewal_started_at", update_doc["$set"])
        self.assertEqual(
            update_doc["$set"]["manual_renewal_started_by"], "u1"
        )
        self.assertIn("$push", update_doc)
        push_event = update_doc["$push"]["manual_renewal_audit_log"]
        self.assertEqual(push_event["event_type"], "manual_renewal_started")
        self.assertEqual(push_event["actor"], "u1")
        self.assertEqual(push_event["renewal_id"], "r1")


class TestReadinessGate(unittest.TestCase):

    def test_409_when_readiness_blocked(self):
        import server
        import lib.filing_readiness as fr_mod
        import lib.pw2_field_mapper as pw_mod

        client, restore = _setup_client(company_id="co_a")
        mock_db = _build_db(renewal={
            "_id": "r1", "company_id": "co_a", "status": "eligible",
        })
        readiness = _stub_readiness(
            ready=False,
            blockers=["GC license expired", "No filing rep configured"],
        )

        try:
            with patch.object(fr_mod, "check_filing_readiness",
                              AsyncMock(return_value=readiness)), \
                 patch.object(pw_mod, "map_pw2_fields",
                              AsyncMock(return_value=_stub_field_map())), \
                 patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/r1/start-renewal-clicked"
                )
        finally:
            restore()

        self.assertEqual(resp.status_code, 409)
        detail = resp.json()["detail"]
        self.assertEqual(detail["code"], "readiness_blocked")
        self.assertEqual(detail["blockers"], readiness.blockers)
        # No audit-log write when readiness fails — the click is
        # short-circuited before update_one.
        mock_db.permit_renewals.update_one.assert_not_awaited()


class TestErrorPaths(unittest.TestCase):

    def test_404_when_renewal_missing(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        mock_db = _build_db(renewal=None)

        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/missing/start-renewal-clicked"
                )
        finally:
            restore()
        self.assertEqual(resp.status_code, 404)

    def test_403_cross_tenant(self):
        import server
        client, restore = _setup_client(company_id="co_a")
        # Renewal lives on co_b — caller is co_a.
        mock_db = _build_db(renewal={
            "_id": "r1", "company_id": "co_b", "status": "eligible",
        })

        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.post(
                    "/api/permit-renewals/r1/start-renewal-clicked"
                )
        finally:
            restore()
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
