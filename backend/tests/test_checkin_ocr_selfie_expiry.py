"""Coverage for the LIVE NFC check-in enhancements (checkin.html +
register_and_checkin):

  1. OCR autofill flow-through — a corrected expiration/card number sent on
     register_and_checkin flows into the SST certificate the backend builds.
  2. Selfie capture — selfie_image is stored INLINE on the workers doc (not
     R2); a missing selfie never blocks the check-in.
  3. EXPIRY RELAX (the deliberate behavior change) — an expired SST no longer
     hard-blocks; the worker checks in normally, a compliance_alerts row is
     still written, and dispatch_notification fires to the project's admins +
     assigned CP with kind="expired_sst_checkin". A dispatch failure is
     isolated (check-in still succeeds), and a same-day re-tap does not
     double-alert.

These exercise the live path ONLY — register_and_checkin in server.py. The
shadowed card_audit / worker_enrollments / R2 flow is not touched.
"""

from __future__ import annotations

import os
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
        self._find_one = None      # value or callable(query) -> doc | None
        self._find_docs = []
        self.inserted = []
        self.updated = []
        self.raise_on_insert = False
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
        if self.raise_on_insert:
            raise RuntimeError("simulated insert failure")
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


# ── Shared fixture helpers ────────────────────────────────────────────────

_TRADE = "Carpenter"
_COMPANY = "Acme Co"


def _make_db(*, existing_checkin=None):
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
    db.workers.set_find_one(None)        # new worker
    db.logbooks.set_find_one(None)
    db.checkins.set_find_one(existing_checkin)
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
        "osha_data": {"sst_number": "SST12345678", "expiration": None},
        "osha_card_image": "data:image/jpeg;base64,CARDIMG",
    }
    body.update(overrides)
    return body


def _client():
    return TestClient(server.app)


# ── Tests ─────────────────────────────────────────────────────────────────

class ExpiredSstRelaxTest(unittest.TestCase):
    """The one deliberate behavior change: expired SST → allow + alert."""

    def test_validate_expired_sst_is_warning_not_block(self):
        """Pure-function assertion: an expired SST cert no longer produces a
        block; it is downgraded to a warning and cleared stays True."""
        worker = {
            "certifications": [{
                "type": "SST_LIMITED",
                "expiration_date": datetime(2020, 1, 1, tzinfo=timezone.utc),
            }],
        }
        result = server.validate_worker_certifications(worker, {})
        self.assertTrue(result["cleared"], "expired SST must NOT block anymore")
        self.assertFalse(
            any(b.get("type") == "EXPIRED_SST" for b in result["blocks"]),
            "EXPIRED_SST must not be in blocks",
        )
        self.assertTrue(
            any(w.get("type") == "EXPIRED_SST" for w in result["warnings"]),
            "EXPIRED_SST must be present as a warning",
        )

    def test_expired_sst_checks_in_and_dispatches(self):
        db = _make_db()
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ) as mock_dispatch:
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(osha_data={
                    "sst_number": "SST12345678", "expiration": "01/01/2020",
                }),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        # NOT blocked — worker checks in normally.
        self.assertNotEqual(data.get("blocked"), True)
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("is_new_worker"))
        # compliance_alerts row still written (admin screen stays populated).
        self.assertEqual(len(db.compliance_alerts.inserted), 1)
        # Notification dispatched to the project's recipients.
        self.assertEqual(mock_dispatch.await_count, 1)
        kwargs = mock_dispatch.await_args.kwargs
        self.assertEqual(kwargs["kind"], "expired_sst_checkin")
        self.assertEqual(kwargs["project"]["_id"], "proj1")
        self.assertEqual(kwargs["source_kind"], "checkin")
        # source_id is keyed on (worker, EST check-in day) for idempotency —
        # it is the check-in day, NOT the card's expiration date.
        source_id = str(kwargs["source_id"])
        self.assertIn(":", source_id)
        self.assertFalse(source_id.endswith(":2020-01-01"))

    def test_dispatch_failure_is_isolated(self):
        """If dispatch_notification raises, the check-in STILL succeeds."""
        db = _make_db()
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
                 side_effect=RuntimeError("inbox down"),
             ):
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(osha_data={
                    "sst_number": "SST12345678", "expiration": "01/01/2020",
                }),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertNotEqual(data.get("blocked"), True)
        # Check-in was written despite the dispatch failure.
        self.assertEqual(len(db.checkins.inserted), 1)

    def test_same_day_retap_does_not_double_alert(self):
        """A second tap the same day short-circuits on the existing check-in
        and never re-dispatches (idempotency)."""
        existing = {
            "check_in_time": datetime.now(timezone.utc),
            "status": "checked_in",
        }
        db = _make_db(existing_checkin=existing)
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ) as mock_dispatch:
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(osha_data={
                    "sst_number": "SST12345678", "expiration": "01/01/2020",
                }),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json().get("message"), "Already checked in")
        self.assertEqual(mock_dispatch.await_count, 0)
        # No second check-in row created.
        self.assertEqual(len(db.checkins.inserted), 0)


class SelfieStorageTest(unittest.TestCase):

    def test_selfie_stored_inline_on_worker_doc(self):
        db = _make_db()
        selfie = "data:image/jpeg;base64,SELFIEBYTES"
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ):
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(selfie_image=selfie),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.workers.inserted), 1)
        worker_doc = db.workers.inserted[0]
        # Inline base64 on the worker doc — NOT an R2 key/URL.
        self.assertEqual(worker_doc.get("selfie_image"), selfie)

    def test_checkin_succeeds_without_selfie(self):
        db = _make_db()
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ):
            body = _body()
            body.pop("selfie_image", None)  # no selfie at all
            resp = _client().post(
                "/api/checkin/register-and-checkin", json=body,
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertEqual(len(db.workers.inserted), 1)
        self.assertIsNone(db.workers.inserted[0].get("selfie_image"))


class OcrCorrectionFlowThroughTest(unittest.TestCase):

    def test_corrected_ocr_values_flow_through_and_are_stored(self):
        """The (possibly corrected) card number + expiration sent from the
        form flow through register_and_checkin — stored on the worker doc and
        fed to the cert logic. A corrected FUTURE expiration reads as a valid
        SST (not blocked, no expired-alert). The complementary proof that a
        corrected expiration reaches the cert logic is
        ExpiredSstRelaxTest.test_expired_sst_checks_in_and_dispatches, where a
        corrected past expiration drives the EXPIRED_SST alert."""
        db = _make_db()
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ) as mock_dispatch:
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(
                    osha_number="CORRECTED99",
                    osha_data={
                        "sst_number": "CORRECTED99",
                        "card_type": "SST",
                        "card_class": "LIMITED",
                        "expiration": "01/01/2030",
                    },
                ),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotEqual(resp.json().get("blocked"), True)
        # Corrected values were sent and stored inline on the worker doc.
        worker_doc = db.workers.inserted[0]
        self.assertEqual(worker_doc.get("osha_number"), "CORRECTED99")
        self.assertEqual(worker_doc.get("osha_data", {}).get("expiration"), "01/01/2030")
        # A future expiration is a valid SST → no expired-SST alert fires.
        self.assertEqual(mock_dispatch.await_count, 0)


if __name__ == "__main__":
    unittest.main()
