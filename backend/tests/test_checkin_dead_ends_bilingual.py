"""Coverage for the three LIVE worker check-in dead-end fixes:

  FIX 1 — a project with NO configured trades no longer blocks the worker.
          They check in, the row is flagged needs_trade_assignment=True, and
          the CP/admins are notified. Projects that DO have trades keep the
          strict roster-pair enforcement unchanged.
  FIX 2 — a worker who cannot photograph their card can complete check-in via
          manual entry; register_and_checkin accepts a missing card image.
  FIX 3 — every user-facing string in checkin.html is bilingual (EN + ES) and
          no hardcoded English remains in the worker flow.

Live path only (checkin.html + register_and_checkin). card_audit untouched.
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


def _make_db(*, trade_assignments):
    db = _FakeDb()
    db.nfc_tags.set_find_one({
        "tag_id": "tag1", "project_id": "proj1", "status": "active",
    })
    db.projects.set_find_one({
        "_id": "proj1",
        "name": "Test Tower",
        "company_id": "co_a",
        "admin_id": "admin_a",
        "trade_assignments": trade_assignments,
    })
    db.workers.set_find_one(None)
    db.logbooks.set_find_one(None)
    db.checkins.set_find_one(None)
    return db


def _body(**overrides):
    body = {
        "project_id": "proj1",
        "tag_id": "tag1",
        "name": "Jane Worker",
        "phone": "5551234567",
        "osha_number": "SST12345678",
        "osha_data": {"sst_number": "SST12345678", "card_type": "SST",
                      "card_class": "LIMITED", "expiration": "01/01/2030"},
        "osha_card_image": "data:image/jpeg;base64,CARDIMG",
    }
    body.update(overrides)
    return body


def _post(db, body, *, dispatch=None):
    ctx = dispatch or AsyncMock()
    with patch.object(server, "db", db), \
         patch.object(
             server._notifications_inbox, "dispatch_notification", ctx,
         ):
        resp = TestClient(server.app).post(
            "/api/checkin/register-and-checkin", json=body,
        )
    return resp, ctx


# ── FIX 1: no trades configured → proceed + flag ──────────────────────────

class NoTradesProceedTest(unittest.TestCase):

    def test_no_trades_check_in_succeeds_and_is_flagged(self):
        db = _make_db(trade_assignments=[])
        # Worker sends no trade/company — there was nothing to pick.
        resp, dispatch = _post(db, _body(trade="", company=""))

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertNotEqual(data.get("blocked"), True)

        row = db.checkins.inserted[0]
        self.assertTrue(row["needs_trade_assignment"])
        self.assertEqual(row["trade"], "UNASSIGNED")

        # CP + admins notified.
        self.assertEqual(dispatch.await_count, 1)
        kwargs = dispatch.await_args.kwargs
        self.assertEqual(kwargs["kind"], "checkin_needs_trade")
        self.assertEqual(kwargs["severity"], "warning")
        self.assertEqual(kwargs["project"]["_id"], "proj1")

    def test_notification_failure_does_not_block_check_in(self):
        db = _make_db(trade_assignments=[])
        failing = AsyncMock(side_effect=RuntimeError("inbox down"))
        resp, _ = _post(db, _body(trade="", company=""), dispatch=failing)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        # The check-in row was still written.
        self.assertEqual(len(db.checkins.inserted), 1)

    def test_configured_project_still_enforces_roster(self):
        """The bypass must NOT weaken normal projects."""
        db = _make_db(trade_assignments=[{"trade": _TRADE, "company": _COMPANY}])
        resp, dispatch = _post(
            db, _body(trade="Plumber", company="Not On Roster"),
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("not assigned", resp.json().get("detail", ""))
        self.assertEqual(db.checkins.inserted, [])
        self.assertEqual(dispatch.await_count, 0)

    def test_configured_project_valid_pair_not_flagged(self):
        db = _make_db(trade_assignments=[{"trade": _TRADE, "company": _COMPANY}])
        resp, dispatch = _post(db, _body(trade=_TRADE, company=_COMPANY))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[0]
        self.assertFalse(row["needs_trade_assignment"])
        self.assertEqual(row["trade"], _TRADE)
        self.assertEqual(dispatch.await_count, 0)

    def test_configured_project_still_requires_company(self):
        db = _make_db(trade_assignments=[{"trade": _TRADE, "company": _COMPANY}])
        resp, _ = _post(db, _body(trade=_TRADE, company=""))
        self.assertEqual(resp.status_code, 400, resp.text)


# ── FIX 2: manual entry, no card photo ────────────────────────────────────

class ManualEntryNoPhotoTest(unittest.TestCase):

    def test_check_in_succeeds_without_card_image(self):
        """Manual entry sends a card number but no photo."""
        db = _make_db(trade_assignments=[{"trade": _TRADE, "company": _COMPANY}])
        body = _body(trade=_TRADE, company=_COMPANY)
        body.pop("osha_card_image")  # no photo at all
        resp, _ = _post(db, body)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertNotEqual(resp.json().get("blocked"), True)
        self.assertIsNone(db.workers.inserted[0].get("osha_card_image"))

    def test_expiration_only_manual_entry_is_accepted(self):
        """A worker who can read only the expiration date still gets in
        (the SST cert satisfies the OSHA baseline)."""
        db = _make_db(trade_assignments=[{"trade": _TRADE, "company": _COMPANY}])
        body = _body(
            trade=_TRADE, company=_COMPANY,
            osha_number="",
            osha_data={"sst_number": None, "expiration": "01/01/2030"},
        )
        body.pop("osha_card_image")
        resp, _ = _post(db, body)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotEqual(resp.json().get("blocked"), True)


# ── FIX 3: bilingual coverage ─────────────────────────────────────────────

class BilingualCoverageTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = (_BACKEND / "checkin.html").read_text(encoding="utf-8")

    def _lang_keys(self, lang):
        """Extract the top-level key names of TRANSLATIONS.<lang>."""
        m = re.search(
            r"^  %s: \{$(.*?)^  \},$" % lang,
            self.html, re.S | re.M,
        )
        self.assertIsNotNone(m, f"TRANSLATIONS.{lang} block not found")
        return set(re.findall(r"^    (\w+):", m.group(1), re.M))

    def test_en_and_es_key_sets_match(self):
        en, es = self._lang_keys("en"), self._lang_keys("es")
        self.assertEqual(
            en - es, set(), f"keys missing a Spanish translation: {sorted(en - es)}",
        )
        self.assertEqual(
            es - en, set(), f"keys missing an English translation: {sorted(es - en)}",
        )

    def test_all_new_and_fixed_strings_are_translated(self):
        en, es = self._lang_keys("en"), self._lang_keys("es")
        required = {
            # FIX 1
            "noTradesProceed",
            # FIX 2
            "manualEntryLink", "manualEntryNote", "cardNumberLabel",
            "expirationLabel", "needCardOrManual",
            # FIX 3 — previously English-only
            "tagNotRegistered", "invalidPhone", "lookingUp", "checkingIn",
            "readingCard", "couldNotReadCard", "orientationNeeded",
            "completeOrientation", "enterName", "selectTradeCompanyErr",
            "completeAllItems", "signatureRequired",
            "blockedTitle", "blockedContact", "blockedCompliance",
            "blockMissingOsha", "blockExpiredSst", "blockMissingSst",
            "genericError",
        }
        self.assertEqual(required - en, set(), "missing EN keys")
        self.assertEqual(required - es, set(), "missing ES keys")

    def test_no_hardcoded_english_in_worker_flow(self):
        """The specific English literals the audit flagged must no longer be
        used as inline copy. They legitimately remain as VALUES inside the
        TRANSLATIONS map, so that block is excluded before checking."""
        body = re.sub(
            r"const TRANSLATIONS = \{.*?\n\};", "", self.html, flags=re.S,
        )
        self.assertNotIn("const TRANSLATIONS", body, "TRANSLATIONS strip failed")

        forbidden = [
            "This NFC tag is not registered to any project.",
            "Enter a valid phone number (10+ digits)",
            "Looking you up...",
            "Checking you in...",
            "Reading your card...",
            "Please take a photo of your OSHA/SST card",
            "⚠ Safety orientation needed for this site",
            "Complete Safety Orientation",
            "CHECK-IN BLOCKED",
            "NYC DOB Local Law 196 Compliance",
            "Site Safety Manager",
        ]
        for lit in forbidden:
            self.assertNotIn(
                lit, body, f"hardcoded English still used as copy: {lit}",
            )

    def test_backend_errors_go_through_translator(self):
        """Raw backend detail text must not be shown to the worker."""
        self.assertIn("function translateApiError", self.html)
        self.assertIn("BACKEND_ERROR_MAP", self.html)
        self.assertNotIn("showError(e.message)", self.html)

    def test_manual_entry_does_not_require_a_photo(self):
        """The goStep gate accepts manually typed card details in place of an
        image, so no camera / a damaged card is never a dead-end."""
        self.assertIn("function hasManualCardDetails", self.html)
        self.assertIn(
            "!oshaImage && !oshaData && !hasManualCardDetails()", self.html,
        )
        # The old photo-mandatory gate is gone.
        self.assertNotIn("if (!oshaImage && !oshaData) {", self.html)

    def test_no_trades_enables_rather_than_disables_next(self):
        m = re.search(
            r"if \(!tradeAssignments\.length\) \{(.*?)\n  \}",
            self.html, re.S,
        )
        self.assertIsNotNone(m)
        block = m.group(1)
        self.assertIn("nextBtn.disabled = false", block)
        self.assertIn("noTradesConfigured = true", block)


if __name__ == "__main__":
    unittest.main()
