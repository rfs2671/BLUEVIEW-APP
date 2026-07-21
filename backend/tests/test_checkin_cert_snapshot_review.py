"""Coverage for the check-in compliance-proof / decision changes:

  PART 1 — cert-validity snapshot FROZEN onto the immutable `checkins` row
           (sst_card_number, parsed sst_expiration, sst_status, cert_cleared).
  PART 2 — the certifications[] persistence bug: `worker_certs` used to alias
           `worker["certifications"]`, so the length-guard never fired and
           db.workers.certifications stayed [] forever. These tests assert the
           certs (incl. SST expiration_date) now persist for BOTH a new and a
           returning worker.
  PART 3 — checkin.html OCR retake loop (bounded at 3) with manual-entry
           fallback; asserted as source invariants (mirrors the existing
           frontend-invariant test style in this suite).
  PART 4 — POST /checkins/{id}/review: authorization, server-derived
           attribution, audit_log, and re-review overwrite.

Live path only (register_and_checkin). The shadowed card_audit/R2 flow is
untouched.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ── Minimal async Mongo fakes ─────────────────────────────────────────────

class _Result:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id
        self.matched_count = 1
        self.modified_count = 1


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._i = 0

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._docs):
            raise StopAsyncIteration
        d = self._docs[self._i]
        self._i += 1
        return d

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
        self._find_docs = []
        self.inserted = []
        self.updated = []
        self._seq = 0

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query) if callable(v) else v

    def find(self, query=None, *a, **k):
        return _FakeCursor(self._find_docs)

    async def insert_one(self, doc, *a, **k):
        self._seq += 1
        _id = doc.get("_id") or f"{self.name}_{self._seq}"
        rec = dict(doc)
        rec["_id"] = _id
        self.inserted.append(rec)
        return _Result(_id)

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result("upd")

    async def count_documents(self, *a, **k):
        return 0

    def last_set(self, field):
        """Value of `field` from the most recent update_one that $set it."""
        for _q, u in reversed(self.updated):
            s = u.get("$set") or {}
            if field in s:
                return s[field]
        return None


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, name):
        if name not in self._c:
            self._c[name] = _FakeCollection(name)
        return self._c[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._get(name)

    def __getitem__(self, name):
        return self._get(name)


_TRADE = "Carpenter"
_COMPANY = "Acme Co"


def _make_db(*, existing_worker=None):
    db = _FakeDb()
    db.nfc_tags.set_find_one({
        "tag_id": "tag1", "project_id": "proj1", "status": "active",
    })
    db.projects.set_find_one({
        "_id": "proj1",
        "name": "Test Tower",
        "company_id": "co_a",
        "admin_id": "admin_a",
        "trade_assignments": [{"trade": _TRADE, "company": _COMPANY}],
    })
    db.workers.set_find_one(existing_worker)
    db.logbooks.set_find_one(None)
    db.checkins.set_find_one(None)
    return db


def _body(**overrides):
    body = {
        "project_id": "proj1",
        "tag_id": "tag1",
        "name": "Jane Worker",
        "phone": "5551234567",
        "trade": _TRADE,
        "company": _COMPANY,
        "osha_number": "SST12345678",
        "osha_data": {"sst_number": "SST12345678", "expiration": "01/01/2030"},
        "osha_card_image": "data:image/jpeg;base64,CARDIMG",
    }
    body.update(overrides)
    return body


def _post_checkin(db, body):
    with patch.object(server, "db", db), \
         patch.object(
             server._notifications_inbox, "dispatch_notification",
             new_callable=AsyncMock,
         ):
        return TestClient(server.app).post(
            "/api/checkin/register-and-checkin", json=body,
        )


# ── PART 1: cert snapshot on the checkin row ──────────────────────────────

class CertSnapshotTest(unittest.TestCase):

    def test_valid_cert_snapshot_written_to_checkin_row(self):
        db = _make_db()
        resp = _post_checkin(db, _body())
        self.assertEqual(resp.status_code, 200, resp.text)

        row = db.checkins.inserted[0]
        self.assertEqual(row["sst_status"], "valid")
        self.assertTrue(row["cert_cleared"])
        self.assertEqual(row["sst_card_number"], "SST12345678")
        # Structured, PARSED date on the row — not a raw OCR string, not a photo.
        exp = row["sst_expiration"]
        self.assertIsInstance(exp, datetime)
        self.assertEqual((exp.year, exp.month, exp.day), (2030, 1, 1))

    def test_expired_cert_snapshot_records_expired_status(self):
        db = _make_db()
        resp = _post_checkin(db, _body(osha_data={
            "sst_number": "SST12345678", "expiration": "01/01/2020",
        }))
        self.assertEqual(resp.status_code, 200, resp.text)

        row = db.checkins.inserted[0]
        self.assertEqual(row["sst_status"], "expired")
        # Flag-but-allow: still cleared, worker not blocked.
        self.assertTrue(row["cert_cleared"])
        self.assertNotEqual(resp.json().get("blocked"), True)
        self.assertEqual(row["sst_expiration"].year, 2020)

    def test_unparseable_expiration_records_unparseable_status(self):
        db = _make_db()
        resp = _post_checkin(db, _body(osha_data={
            "sst_number": "SST12345678", "expiration": "not-a-date",
        }))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[0]
        self.assertEqual(row["sst_status"], "unparseable")
        self.assertIsNone(row["sst_expiration"])


# ── PART 2: certifications[] persistence bug ──────────────────────────────

class CertificationsPersistenceTest(unittest.TestCase):
    """The bug: worker_certs aliased worker["certifications"], so the
    length-guard was always equal and the update_one never fired."""

    def _assert_sst_cert_persisted(self, db):
        certs = db.workers.last_set("certifications")
        self.assertIsNotNone(
            certs, "certifications must be persisted to db.workers",
        )
        self.assertTrue(certs, "certifications must be NON-EMPTY after check-in")
        sst = [c for c in certs if str(c.get("type", "")).startswith("SST")]
        self.assertEqual(len(sst), 1, f"expected one SST cert, got {certs}")
        exp = sst[0].get("expiration_date")
        self.assertIsInstance(exp, datetime)
        self.assertEqual(exp.year, 2030)
        return certs

    def test_new_worker_certifications_persisted(self):
        db = _make_db()  # workers.find_one -> None => new worker
        resp = _post_checkin(db, _body())
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("is_new_worker"))
        certs = self._assert_sst_cert_persisted(db)
        # OSHA baseline cert persisted alongside the SST one.
        self.assertTrue(
            any(str(c.get("type", "")).startswith("OSHA") for c in certs),
        )

    def test_returning_worker_certifications_persisted(self):
        # A returning worker left in the legacy broken state: stored
        # certifications == [] because the guard never fired before.
        existing = {
            "_id": "worker_existing",
            "name": "Jane Worker",
            "phone": "555-123-4567",
            "certifications": [],
            "osha_card_image": "data:image/jpeg;base64,OLD",
        }
        db = _make_db(existing_worker=existing)
        resp = _post_checkin(db, _body())
        self.assertEqual(resp.status_code, 200, resp.text)
        self._assert_sst_cert_persisted(db)

    def test_existing_certs_are_not_duplicated(self):
        """A worker who already has both certs gets no duplicate append."""
        existing = {
            "_id": "worker_existing",
            "name": "Jane Worker",
            "phone": "555-123-4567",
            "certifications": [
                {"type": "OSHA_10", "card_number": "X"},
                {
                    "type": "SST_LIMITED",
                    "card_number": "X",
                    "expiration_date": datetime(2030, 1, 1, tzinfo=timezone.utc),
                },
            ],
        }
        db = _make_db(existing_worker=existing)
        resp = _post_checkin(db, _body())
        self.assertEqual(resp.status_code, 200, resp.text)
        # No cert-rewrite needed => the cert update_one should not have fired.
        self.assertIsNone(db.workers.last_set("certifications"))
        # And the snapshot still reads the existing SST expiration.
        self.assertEqual(db.checkins.inserted[0]["sst_status"], "valid")


# ── PART 3: checkin.html OCR retake invariants ────────────────────────────

class CheckinHtmlOcrRetakeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = (_BACKEND / "checkin.html").read_text(encoding="utf-8")

    def test_retake_capped_at_three(self):
        m = re.search(r"const\s+OCR_MAX_ATTEMPTS\s*=\s*(\d+)", self.html)
        self.assertIsNotNone(m, "OCR_MAX_ATTEMPTS must be defined")
        self.assertEqual(int(m.group(1)), 3, "retakes must be capped at 3")

    def test_both_ocr_paths_route_through_outcome_handler(self):
        """Success AND failure of the OCR call must run the retake/fallback
        decision, so neither path can dead-end the worker."""
        self.assertIn("handleOcrOutcome(ocrMissingCriticalFields(res))", self.html)
        self.assertIn("handleOcrOutcome(null)", self.html)
        self.assertIn("ocrAttempts++", self.html)

    def test_manual_entry_fallback_exists(self):
        self.assertIn('id="ocrManualFields"', self.html)
        self.assertIn("function revealManualFields", self.html)
        # Once the cap is hit the fields are revealed and Next is re-enabled.
        self.assertIn("ocrAttempts < OCR_MAX_ATTEMPTS", self.html)
        self.assertIn("resetCardCameraZone", self.html)

    def test_manual_values_still_flow_through_on_submit(self):
        """The #81 wiring must remain: submit reads the editable inputs, not
        just the raw OCR blob."""
        for field in ("regCardNumber", "regIssued", "regExpiration"):
            self.assertIn(f"getElementById('{field}').value", self.html)
        self.assertIn("correctedOshaData", self.html)
        self.assertIn("osha_data: correctedOshaData", self.html)


# ── PART 4: the review endpoint ───────────────────────────────────────────

def _review_client(db, *, role="admin", company_id="co_a",
                   user_id="u1", assigned_projects=None, name="Ada Admin"):
    user = {
        "_id": user_id, "id": user_id, "role": role,
        "company_id": company_id, "full_name": name,
        "assigned_projects": assigned_projects or [],
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _review_db():
    db = _FakeDb()
    db.checkins.set_find_one({
        "_id": "chk1", "project_id": "proj1", "worker_name": "Jane Worker",
        "sst_status": "expired",
    })
    db.projects.set_find_one({"_id": "proj1", "company_id": "co_a"})
    return db


class ReviewEndpointTest(unittest.TestCase):

    def test_admin_records_decision_and_audit_log(self):
        db = _review_db()
        client, cleanup = _review_client(db)
        try:
            with patch.object(server, "db", db):
                resp = client.post(
                    "/api/checkins/chk1/review", json={"decision": "approved"},
                )
        finally:
            cleanup()
        self.assertEqual(resp.status_code, 200, resp.text)

        self.assertEqual(db.checkins.last_set("review_decision"), "approved")
        self.assertEqual(db.checkins.last_set("reviewed_by"), "u1")
        self.assertEqual(db.checkins.last_set("reviewed_by_name"), "Ada Admin")
        self.assertIsInstance(db.checkins.last_set("reviewed_at"), datetime)

        # Mirrors checkout's audit_log call.
        self.assertEqual(len(db.audit_logs.inserted), 1)
        entry = db.audit_logs.inserted[0]
        self.assertEqual(entry["action"], "checkin_review")
        self.assertEqual(entry["resource_type"], "checkin")
        self.assertEqual(entry["resource_id"], "chk1")
        self.assertEqual(entry["details"], {"decision": "approved"})

    def test_reviewed_by_is_server_derived_not_client_supplied(self):
        db = _review_db()
        client, cleanup = _review_client(db)
        try:
            with patch.object(server, "db", db):
                resp = client.post(
                    "/api/checkins/chk1/review",
                    json={
                        "decision": "sent_home",
                        "reviewed_by": "HACKER",
                        "reviewed_by_name": "Not Me",
                    },
                )
        finally:
            cleanup()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.checkins.last_set("reviewed_by"), "u1")
        self.assertEqual(db.checkins.last_set("reviewed_by_name"), "Ada Admin")

    def test_wrong_company_admin_forbidden(self):
        db = _review_db()
        client, cleanup = _review_client(
            db, company_id="co_other", assigned_projects=[],
        )
        try:
            with patch.object(server, "db", db):
                resp = client.post(
                    "/api/checkins/chk1/review", json={"decision": "approved"},
                )
        finally:
            cleanup()
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertEqual(db.checkins.updated, [])

    def test_assigned_cp_allowed(self):
        """Mirrors the CP write-gate: assignment to the project grants access
        even without a company-admin role."""
        db = _review_db()
        client, cleanup = _review_client(
            db, role="cp", company_id="co_other",
            user_id="cp1", assigned_projects=["proj1"], name="Carl CP",
        )
        try:
            with patch.object(server, "db", db):
                resp = client.post(
                    "/api/checkins/chk1/review", json={"decision": "sent_home"},
                )
        finally:
            cleanup()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.checkins.last_set("reviewed_by"), "cp1")

    def test_re_review_overwrites_latest_decision(self):
        db = _review_db()
        client, cleanup = _review_client(db)
        try:
            with patch.object(server, "db", db):
                r1 = client.post(
                    "/api/checkins/chk1/review", json={"decision": "approved"},
                )
                r2 = client.post(
                    "/api/checkins/chk1/review", json={"decision": "sent_home"},
                )
        finally:
            cleanup()
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Latest decision wins on the row; audit_logs keeps both.
        self.assertEqual(db.checkins.last_set("review_decision"), "sent_home")
        self.assertEqual(len(db.audit_logs.inserted), 2)

    def test_invalid_decision_rejected(self):
        db = _review_db()
        client, cleanup = _review_client(db)
        try:
            with patch.object(server, "db", db):
                resp = client.post(
                    "/api/checkins/chk1/review", json={"decision": "maybe"},
                )
        finally:
            cleanup()
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(db.checkins.updated, [])


if __name__ == "__main__":
    unittest.main()
