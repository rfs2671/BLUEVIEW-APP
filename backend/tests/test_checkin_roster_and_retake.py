"""Coverage for two NFC check-in features on register_and_checkin:

FEATURE 1 — ROSTER PICK / "NOT LISTED"
  * One roster pick sets BOTH worker_trade and worker_company and clears
    needs_trade_assignment.
  * "My company isn't listed" (trade_not_listed) admits the worker, flags the
    check-in (needs_trade_assignment), notifies the CP, and NEVER blocks.
  * A returning worker whose stored (trade, company) is still on the roster is
    accepted directly (not re-prompted). One whose roster entry was
    renamed/removed and who did NOT pick "not listed" gets a 400 — the signal
    the check-in page uses to re-prompt for a current entry.
  * Historical immutability: the trade/company frozen on a checkin row and a
    filed logbook are COPIES — renaming the roster afterwards never mutates them.

FEATURE 2 — CARD OCR RETAKE / FAIL-OPEN
  * A missing card_class ONLY (name + number present) is NOT a retake trigger —
    it stores SST_UNSPECIFIED and resolves to `unknown`, worker admitted.
  * The bounded-retake fall-through: three failed attempts still admit the
    worker with sst_status `unknown`, flag for review, notify the CP, and freeze
    the attempt count + last failure reason on the checkin row.
  * Check-in succeeds in every failure path.

These drive the live endpoint (register_and_checkin) via a hand-rolled async
Mongo fake — no HTTP server, no real DB. The card-photo RETAKE PROMPT itself is
client-side (checkin.html); its gate function is unit-tested separately in
frontend/src/utils/checkinCardGate.test.cjs.
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


# ── Fixture helpers ───────────────────────────────────────────────────────

_ROSTER = [{"trade": "Concrete", "company": "AAZ"}]


def _make_db(*, roster=_ROSTER, worker=None, existing_checkin=None):
    db = _FakeDb()
    db.nfc_tags.set_find_one({
        "tag_id": "tag1", "project_id": "proj1", "status": "active",
    })
    db.projects.set_find_one({
        "_id": "proj1",
        "name": "Test Tower",
        "company_id": "co_a",
        "admin_id": "admin_a",
        # Deep-copy inner dicts so a test that mutates the roster (the rename
        # immutability test) can't corrupt the shared _ROSTER for other tests.
        "trade_assignments": [dict(r) for r in roster],
    })
    db.workers.set_find_one(worker)      # None => new worker
    db.logbooks.set_find_one(None)
    db.checkins.set_find_one(existing_checkin)
    return db


def _valid_osha(**overrides):
    """OCR blob that builds a VALID SST cert (legible class + future expiry) so
    the cert gate clears and trade behavior is isolated."""
    data = {
        "name": "Jane Worker",
        "sst_number": "SST12345678",
        "card_type": "SST",
        "card_class": "LIMITED",
        "issued": None,
        "expiration": "01/01/2030",
    }
    data.update(overrides)
    return data


def _body(**overrides):
    body = {
        "project_id": "proj1",
        "tag_id": "tag1",
        "name": "Jane Worker",
        "phone": "5551234567",
        "trade": "Concrete",
        "company": "AAZ",
        "osha_number": "SST12345678",
        "osha_data": _valid_osha(),
    }
    body.update(overrides)
    return body


def _client():
    return TestClient(server.app)


def _dispatch_patch():
    return patch.object(
        server._notifications_inbox, "dispatch_notification",
        new_callable=AsyncMock,
    )


def _kinds(mock):
    return [c.kwargs.get("kind") for c in mock.await_args_list]


def _cert_types_written(db):
    """The certification types persisted for the worker (from the update_one
    that build_worker_certifications triggers)."""
    for q, u in db.workers.updated:
        certs = u.get("$set", {}).get("certifications")
        if certs is not None:
            return [c.get("type") for c in certs]
    return []


# ── FEATURE 1 ─────────────────────────────────────────────────────────────

class RosterPickTest(unittest.TestCase):

    def test_roster_pick_sets_trade_company_and_clears_flag(self):
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch() as disp:
            resp = _client().post(
                "/api/checkin/register-and-checkin", json=_body(),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertNotEqual(resp.json().get("blocked"), True)
        # ONE pick set BOTH fields on the worker doc.
        w = db.workers.inserted[0]
        self.assertEqual(w.get("trade"), "Concrete")
        self.assertEqual(w.get("company"), "AAZ")
        # ...and on the frozen checkin row, with the flag cleared.
        row = db.checkins.inserted[0]
        self.assertEqual(row.get("worker_trade"), "Concrete")
        self.assertEqual(row.get("worker_company"), "AAZ")
        self.assertFalse(row.get("needs_trade_assignment"))
        # A valid card + valid roster pick raises no CP notification.
        self.assertNotIn("checkin_needs_trade", _kinds(disp))

    def test_not_listed_admits_flags_and_notifies(self):
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch() as disp:
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(trade="", company="", trade_not_listed=True),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        # NEVER blocked.
        self.assertNotEqual(resp.json().get("blocked"), True)
        row = db.checkins.inserted[0]
        self.assertTrue(row.get("needs_trade_assignment"))
        # CP is notified, tagged with the reason.
        needs_trade = [
            c for c in disp.await_args_list
            if c.kwargs.get("kind") == "checkin_needs_trade"
        ]
        self.assertEqual(len(needs_trade), 1)
        self.assertEqual(
            needs_trade[0].kwargs.get("metadata", {}).get("reason"), "not_listed"
        )

    def test_not_listed_preserves_typed_values(self):
        """FIX 2: not_listed mirrors the no-roster shape (`x or 'UNASSIGNED'`),
        so a typed trade/company is kept, not overwritten with the sentinel."""
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(trade="Roofing", company="Real Sub LLC",
                           trade_not_listed=True),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        w = db.workers.inserted[0]
        self.assertEqual(w.get("trade"), "Roofing")
        self.assertEqual(w.get("company"), "Real Sub LLC")
        # Still flagged for the CP — a typed value doesn't put it on the roster.
        self.assertTrue(db.checkins.inserted[0].get("needs_trade_assignment"))

    def test_returning_valid_pair_not_reprompted(self):
        existing = {
            "_id": "w_existing",
            "name": "Jane Worker",
            "phone": "5551234567",
            "trade": "Concrete",
            "company": "AAZ",
            "certifications": [],
            "is_deleted": False,
        }
        db = _make_db(worker=existing)
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin", json=_body(),
            )
        # Accepted directly — no 400, flag stays clear (not re-prompted).
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertFalse(db.checkins.inserted[0].get("needs_trade_assignment"))

    def test_returning_removed_entry_is_reprompted(self):
        """Stored pair is no longer on the roster and the worker did NOT pick
        'not listed' → 400. That 400 is what the page uses to re-prompt."""
        existing = {
            "_id": "w_existing",
            "name": "Jane Worker",
            "phone": "5551234567",
            "trade": "Demolition",   # was renamed/removed from the roster
            "company": "OldCo",
            "certifications": [],
            "is_deleted": False,
        }
        db = _make_db(worker=existing)
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(trade="Demolition", company="OldCo"),
            )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("not assigned", resp.json().get("detail", ""))

    def test_case_only_roster_edit_does_not_400_or_reprompt(self):
        """FIX 1: a case-only admin edit to a roster entry must NOT dead-end a
        returning worker. The backend match is normalized (strip + casefold), so
        the worker's stored casing still matches the re-cased roster entry — no
        400, and the trade resolves normally (needs_trade_assignment stays
        False, i.e. not treated as a re-prompt/flag)."""
        existing = {
            "_id": "w_existing",
            "name": "Jane Worker",
            "phone": "5551234567",
            "trade": "Concrete",
            "company": "AAZ",           # stored in the ORIGINAL casing
            "certifications": [],
            "is_deleted": False,
        }
        # Admin re-cased the roster entry after the worker registered.
        db = _make_db(
            roster=[{"trade": "concrete", "company": "Aaz"}],
            worker=existing,
        )
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(trade="Concrete", company="AAZ"),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertFalse(db.checkins.inserted[0].get("needs_trade_assignment"))

    def test_rename_roster_does_not_mutate_existing_records(self):
        """The trade/company on a checkin row and a filed logbook are COPIES —
        renaming the roster entry afterwards leaves them untouched."""
        db = _make_db()
        orientation = {"Hard hat required": {"checked": True}}
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(safety_orientation=orientation, signature="data:sig"),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[0]
        logbook = db.logbooks.inserted[0]
        self.assertEqual(row.get("worker_trade"), "Concrete")
        self.assertEqual(logbook["data"].get("worker_trade"), "Concrete")
        self.assertEqual(logbook["data"].get("worker_company"), "AAZ")

        # Admin renames the roster entry AFTER the fact.
        proj = db.projects._find_one
        proj["trade_assignments"][0]["trade"] = "Concrete & Cement"
        proj["trade_assignments"][0]["company"] = "AAZ Holdings"

        # The already-filed records are unchanged (copies, not live lookups).
        self.assertEqual(db.checkins.inserted[0].get("worker_trade"), "Concrete")
        self.assertEqual(
            db.logbooks.inserted[0]["data"].get("worker_trade"), "Concrete"
        )
        self.assertEqual(
            db.logbooks.inserted[0]["data"].get("worker_company"), "AAZ"
        )


# ── FEATURE 2 ─────────────────────────────────────────────────────────────

class CardOcrRetakeTest(unittest.TestCase):

    def test_missing_card_class_only_stores_unspecified_and_admits(self):
        """card_class missing but name + number present → NOT a retake trigger.
        Stores SST_UNSPECIFIED, resolves to `unknown`, worker admitted."""
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(osha_data=_valid_osha(card_class=None)),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertNotEqual(resp.json().get("blocked"), True)
        self.assertEqual(db.checkins.inserted[0].get("sst_status"), "unknown")
        self.assertIn("SST_UNSPECIFIED", _cert_types_written(db))

    def test_three_failed_attempts_admit_flag_notify_and_record_telemetry(self):
        """Bounded fail-open: after 3 bad photos the worker is admitted with
        state `unknown`, flagged, CP notified, and the attempt count + last
        failure reason are frozen on the row."""
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch() as disp:
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(
                    # unreadable class + expiry → unknown state
                    osha_data=_valid_osha(card_class=None, expiration=None),
                    card_ocr_attempts=3,
                    card_ocr_failure_reason="missing_fields:name,sst_number",
                ),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        row = db.checkins.inserted[0]
        self.assertEqual(row.get("sst_status"), "unknown")
        self.assertEqual(row.get("card_ocr_attempts"), 3)
        self.assertEqual(
            row.get("card_ocr_failure_reason"), "missing_fields:name,sst_number"
        )
        # CP notified about the unverifiable credential.
        self.assertIn("unknown_sst_checkin", _kinds(disp))

    def test_ocr_telemetry_absent_stores_none(self):
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin", json=_body(),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[0]
        self.assertIsNone(row.get("card_ocr_attempts"))
        self.assertIsNone(row.get("card_ocr_failure_reason"))

    def test_bad_attempts_value_coerced_to_none(self):
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(card_ocr_attempts="not-a-number"),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(db.checkins.inserted[0].get("card_ocr_attempts"))


class CheckInNeverBlocksTest(unittest.TestCase):
    """The worker checks in successfully in every failure path."""

    def _run(self, **body_overrides):
        db = _make_db(**body_overrides.pop("_db_kwargs", {}))
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin", json=_body(**body_overrides),
            )
        return resp

    def test_not_listed_succeeds(self):
        r = self._run(trade="", company="", trade_not_listed=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("success"))

    def test_no_roster_configured_succeeds(self):
        db = _make_db(roster=[])
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(trade="", company=""),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertTrue(db.checkins.inserted[0].get("needs_trade_assignment"))

    def test_unknown_class_succeeds(self):
        r = self._run(osha_data=_valid_osha(card_class=None, expiration=None))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("success"))

    def test_three_attempts_succeeds(self):
        r = self._run(card_ocr_attempts=3,
                      card_ocr_failure_reason="ocr_error:timeout")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("success"))


class SstUnknownReasonTest(unittest.TestCase):
    """PR B: the checkin row freezes WHAT was unknown at check-in."""

    def _row(self, **osha):
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(osha_data=_valid_osha(**osha)),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        return db.checkins.inserted[0]

    def test_class_unknown(self):
        # Illegible class + valid future expiry → class is the unknown.
        row = self._row(card_class=None, expiration="01/01/2030")
        self.assertEqual(row.get("sst_status"), "unknown")
        self.assertEqual(row.get("sst_unknown_reason"), "CLASS")

    def test_expiry_unknown(self):
        # Legible class + missing expiry → expiry is the unknown.
        row = self._row(card_class="LIMITED", expiration=None)
        self.assertEqual(row.get("sst_status"), "unknown")
        self.assertEqual(row.get("sst_unknown_reason"), "EXPIRY")

    def test_both_unknown(self):
        row = self._row(card_class=None, expiration=None)
        self.assertEqual(row.get("sst_status"), "unknown")
        self.assertEqual(row.get("sst_unknown_reason"), "BOTH")

    def test_valid_has_no_unknown_reason(self):
        db = _make_db()
        with patch.object(server, "db", db), _dispatch_patch():
            resp = _client().post(
                "/api/checkin/register-and-checkin", json=_body(),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[0]
        self.assertEqual(row.get("sst_status"), "valid")
        self.assertIsNone(row.get("sst_unknown_reason"))


class DisplaySubCompanyTest(unittest.TestCase):
    """PR B: the UNASSIGNED sentinel renders as pending, never a company."""

    def test_unassigned_is_pending(self):
        self.assertEqual(server._display_sub_company("UNASSIGNED"), "Pending assignment")
        self.assertEqual(server._display_sub_company("unassigned"), "Pending assignment")

    def test_empty_is_pending(self):
        self.assertEqual(server._display_sub_company(""), "Pending assignment")
        self.assertEqual(server._display_sub_company(None), "Pending assignment")

    def test_real_company_passes_through(self):
        self.assertEqual(server._display_sub_company("AAZ"), "AAZ")
        self.assertEqual(server._display_sub_company("  Real Sub LLC "), "Real Sub LLC")


if __name__ == "__main__":
    unittest.main()
