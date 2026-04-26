"""End-to-end smoke tests for the COI upload endpoints.

These hit the FastAPI app via TestClient with auth dependencies stubbed
out, so we can exercise the auth gate, Pydantic validation, magic-byte
rejection, and the GC-only business rule without needing a live admin
token. Replaces the curl-from-prod loop the human had to run before
this file existed.

Pattern for any future endpoint:
  - Override get_admin_user / get_current_user via app.dependency_overrides
  - Stub out external side effects (R2 upload, OCR, Mongo writes) via
    monkey-patching at the module level
  - Assert HTTP status codes for each gate firing in isolation

Five tests here:
  - 401 path is already validated against prod (curl 401 from outside
    auth context); not duplicated here, but the dependency-override
    pattern proves the rest of the chain even with auth bypassed.
  - 422 — Pydantic file-required validation
  - 400 — invalid insurance_type passes auth, fails whitelist
  - 400 — magic-byte rejection (non-PDF body)
  - 409 — GC-only gate (HIC company)
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

# server.py reads several env vars at module-import time. Set safe
# stubs BEFORE the path insert + first server import below so tests
# work under `python -m unittest discover` without needing the caller
# to export them. Production sets these in Railway env.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

# Important: import fastapi.testclient via the FastAPI package so the
# httpx version actually used by TestClient matches what we depend on.
from fastapi.testclient import TestClient  # noqa: E402


def _make_test_client(*, admin_user, company_doc):
    """Build a TestClient with auth dependencies stubbed.

    Each test gets its own app + client so dependency overrides don't
    leak between cases. We also patch the global `db` motor handle to
    a MagicMock so endpoints that do `await db.companies.find_one(...)`
    return our injected company_doc.
    """
    import server

    # Override get_admin_user → admin_user dict, get_user_company_id →
    # the company id that points at company_doc.
    async def _fake_admin():
        return admin_user

    server.app.dependency_overrides[server.get_admin_user] = _fake_admin
    server.app.dependency_overrides[server.get_current_user] = _fake_admin

    # Patch get_user_company_id (it reads the user dict; we know the shape)
    original_get_company = server.get_user_company_id

    def _fake_get_company(user):
        return company_doc.get("_id") if company_doc else None

    server.get_user_company_id = _fake_get_company

    # Patch the db handle so .companies.find_one returns our doc.
    db_mock = MagicMock()
    db_mock.companies.find_one = AsyncMock(return_value=company_doc)
    db_mock.coi_ocr_drafts.find_one = AsyncMock(return_value=None)
    db_mock.coi_ocr_drafts.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="test_draft_123")
    )

    original_db = server.db
    server.db = db_mock

    client = TestClient(server.app)
    return client, lambda: _restore(server, original_db, original_get_company)


def _restore(server_mod, original_db, original_get_company):
    server_mod.db = original_db
    server_mod.get_user_company_id = original_get_company
    server_mod.app.dependency_overrides.clear()


def _minimal_pdf_bytes() -> bytes:
    """Minimal PDF that pypdf parses cleanly."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000052 00000 n\n"
        b"0000000098 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n149\n%%EOF\n"
    )


ADMIN_USER = {"id": "admin_user_1", "role": "admin"}
GC_COMPANY = {
    "_id": "gc_co_1",
    "name": "Acme GC",
    "license_class": "GC_LICENSED",
    "is_deleted": False,
    "gc_insurance_records": [],
}
HIC_COMPANY = {
    "_id": "hic_co_1",
    "name": "Acme HIC",
    "license_class": "HIC",
    "is_deleted": False,
    "gc_insurance_records": [],
}


class TestUploadCoiEndpoint(unittest.TestCase):
    """All four post-auth gates exercised end-to-end via TestClient."""

    def test_422_when_no_file(self):
        """FastAPI returns 422 from Pydantic when File(...) field is
        missing. Pre-auth-pass, but the auth override means this
        validates that Pydantic + form parsing run in the right order."""
        client, restore = _make_test_client(
            admin_user=ADMIN_USER,
            company_doc=GC_COMPANY,
        )
        try:
            r = client.post(
                "/api/admin/company/insurance/upload-coi",
                data={"insurance_type": "general_liability"},
                # no files= → File(...) Pydantic constraint fires
            )
            self.assertEqual(r.status_code, 422, r.text)
        finally:
            restore()

    def test_400_when_unknown_insurance_type(self):
        """Whitelist check after auth pass. 'auto' is a real ACORD
        coverage type but we don't track it for DOB renewal."""
        client, restore = _make_test_client(
            admin_user=ADMIN_USER,
            company_doc=GC_COMPANY,
        )
        try:
            r = client.post(
                "/api/admin/company/insurance/upload-coi",
                data={"insurance_type": "auto"},
                files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")},
            )
            self.assertEqual(r.status_code, 400, r.text)
            self.assertIn("insurance_type", r.text)
        finally:
            restore()

    def test_400_when_non_pdf_body(self):
        """Magic-byte check catches a .txt renamed to .pdf BEFORE we
        spend Qwen budget on garbage. The exact bug class users hit
        when they upload from a phone gallery instead of email."""
        client, restore = _make_test_client(
            admin_user=ADMIN_USER,
            company_doc=GC_COMPANY,
        )
        try:
            r = client.post(
                "/api/admin/company/insurance/upload-coi",
                data={"insurance_type": "general_liability"},
                files={
                    "file": (
                        "fake.pdf",
                        b"this is not actually a PDF body",
                        "application/pdf",
                    ),
                },
            )
            self.assertEqual(r.status_code, 400, r.text)
            # Surface the user-facing message — must mention "PDF"
            # so the admin knows what they did wrong.
            self.assertIn("PDF", r.text)
        finally:
            restore()

    def test_409_when_company_is_hic(self):
        """GC-only gate: HIC companies see a 409 with a pointer to
        DCWP for HIC license renewal. Defense in depth — the frontend
        also hides the upload UI for HIC, but the backend is the
        authoritative gate."""
        client, restore = _make_test_client(
            admin_user=ADMIN_USER,
            company_doc=HIC_COMPANY,
        )
        try:
            r = client.post(
                "/api/admin/company/insurance/upload-coi",
                data={"insurance_type": "general_liability"},
                files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")},
            )
            self.assertEqual(r.status_code, 409, r.text)
            # Surface DCWP guidance to the admin.
            self.assertIn("DCWP", r.text)
        finally:
            restore()

    def test_404_when_user_has_no_company(self):
        """Edge: admin user without a company assignment shouldn't
        be able to upload anywhere. Returns 404 (not 403) because
        revealing 'you have an account but no company' is fine,
        revealing 'someone else's company exists' is not — pattern
        matches the cross-tenant 404 in the confirm endpoint."""
        client, restore = _make_test_client(
            admin_user=ADMIN_USER,
            company_doc=None,  # _fake_get_company returns None
        )
        try:
            r = client.post(
                "/api/admin/company/insurance/upload-coi",
                data={"insurance_type": "general_liability"},
                files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")},
            )
            self.assertEqual(r.status_code, 404, r.text)
        finally:
            restore()


class TestConfirmCoiEndpoint(unittest.TestCase):
    """The confirm endpoint pulls a draft, replaces an insurance record.
    Smoke-test the auth gate + cross-tenant 404 + invalid-type 400."""

    def test_400_when_unknown_insurance_type(self):
        client, restore = _make_test_client(
            admin_user=ADMIN_USER,
            company_doc=GC_COMPANY,
        )
        try:
            r = client.put(
                "/api/admin/company/insurance/upload-coi/confirm",
                json={
                    "draft_id": "anything",
                    "insurance_type": "auto",  # not in whitelist
                },
            )
            self.assertEqual(r.status_code, 400, r.text)
        finally:
            restore()

    def test_404_when_draft_missing(self):
        """Draft never existed (or expired). 404 — no PII leak."""
        client, restore = _make_test_client(
            admin_user=ADMIN_USER,
            company_doc=GC_COMPANY,
        )
        try:
            r = client.put(
                "/api/admin/company/insurance/upload-coi/confirm",
                json={
                    "draft_id": "507f1f77bcf86cd799439011",  # any valid ObjectId shape
                    "insurance_type": "general_liability",
                },
            )
            self.assertEqual(r.status_code, 404, r.text)
        finally:
            restore()

    def test_404_when_draft_belongs_to_other_company(self):
        """Cross-tenant safety: even if the draft exists, returning
        anything other than 404 leaks existence to a different tenant."""
        import server
        # First, override the db so the draft lookup returns a doc
        # for a DIFFERENT company.
        client, restore = _make_test_client(
            admin_user=ADMIN_USER,
            company_doc=GC_COMPANY,
        )
        server.db.coi_ocr_drafts.find_one = AsyncMock(return_value={
            "_id": "draft_x",
            "company_id": "OTHER_COMPANY_ID",  # not GC_COMPANY._id
            "insurance_type": "general_liability",
            "ocr_result": {},
        })
        try:
            r = client.put(
                "/api/admin/company/insurance/upload-coi/confirm",
                json={
                    "draft_id": "507f1f77bcf86cd799439011",
                    "insurance_type": "general_liability",
                },
            )
            self.assertEqual(r.status_code, 404, r.text)
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
