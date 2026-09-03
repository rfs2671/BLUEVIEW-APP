"""ITEM 1 — something can finally clear `needs_review`, and it is ATTESTED.

THE DEFECT. The only `needs_review = False` in the backend was the Pydantic
model default (server.py, WorkerCertification). Every other write was the
literal `True` or the extraction-completeness computation at card-scan time:

    needs_review = not (name_ok and number_ok and class_ok and bool(stored_exp))
    if class_source in ("color_only", "conflict"):
        needs_review = True

The second line forces review on a card whose class came from its COLOUR even
when name, number, class and expiry are all good -- "A COLOUR-DERIVED CLASS
ALWAYS NEEDS A HUMAN". The design demanded a human confirmation and shipped no
mechanism to give one. The CP's approve/deny writes `review_decision` onto
`db.checkins`; `needs_review` lives on the certification inside `db.workers`,
and approval never touched it. 20 workers carried `needs_review: true` and that
number could only rise.

THE RULING. The CP clears it -- he is the man on site who can look at the card
in the worker's hand -- and it is ATTESTED: who, when, and against WHICH
`card_number`. If the card number later changes the clearance does NOT carry,
the same join key the OSHA register's Review column uses. A clearance keyed on
a null card number would carry to every future card, so it is refused.

WHAT THE ATTESTATION DOES AND DOES NOT DO, pinned below because the line is the
whole design:

  * It clears `needs_review`. That flag asks "must a human look at this card";
    a human has now looked at it.
  * It lifts EXACTLY ONE demotion in `_sst_cert_state` -- the
    `class_source in ("color_only", "conflict")` one, which exists solely for
    want of a human. That is what stops the warning regenerating tomorrow.
  * It does NOT invent a class the OCR could not read, revive a dead card
    scheme, or supply a missing expiry. Those are gaps in the RECORD, not a
    missing human, so they survive the check and keep saying so. The CP attests
    to name, card number and class -- never to an expiry he was not asked about.

Run:  python -m pytest backend/tests/test_sst_card_check_clears_review.py -q
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=400)
PAST = NOW - timedelta(days=30)


def cert(**kw):
    """A colour-derived SST_FULL with everything else clean -- example 4 from
    production (card 4YU1RY8KKM, fully classified, flagged only because
    `class_source` was colour-derived)."""
    c = {
        "type": "SST_FULL",
        "card_number": "4YU1RY8KKM",
        "expiration_date": FUTURE,
        "verified": False,
        "needs_review": True,
        "review_reason": "CLASS_FROM_COLOR_UNCONFIRMED",
        "class_source": "color_only",
        "card_color_seen": "BLUE",
    }
    c.update(kw)
    return c


def checked(card_number="4YU1RY8KKM", **kw):
    d = {
        "card_number": card_number,
        "checked_by": "u1",
        "checked_by_name": "Carl CP",
        "checked_at": NOW,
    }
    d.update(kw)
    return d


# ── The join key: who, when, and against WHICH card number ──────────────────

class CardCheckCoversTest(unittest.TestCase):
    """`card_check_covers` is the read-time evaluation of the clearance. It is
    a JOIN, not a boolean: a stored flag keyed to a card number is orphaned by
    any later correction to that number, and that is the hazard the OSHA
    register's Review column already refuses to re-create."""

    def test_a_check_against_the_current_card_number_covers(self):
        self.assertTrue(server.card_check_covers(cert(card_check=checked())))

    def test_a_check_against_a_different_card_number_does_not_carry(self):
        c = cert(card_check=checked("SOMEOTHER1"))
        self.assertFalse(server.card_check_covers(c))

    def test_a_check_recorded_against_no_card_number_never_covers(self):
        """A clearance keyed on null would carry to every future card."""
        self.assertFalse(
            server.card_check_covers(cert(card_number=None, card_check=checked(None))))
        self.assertFalse(
            server.card_check_covers(cert(card_number="", card_check=checked(""))))

    def test_no_check_block_does_not_cover(self):
        self.assertFalse(server.card_check_covers(cert()))

    def test_a_malformed_check_block_does_not_cover(self):
        self.assertFalse(server.card_check_covers(cert(card_check="yes")))
        self.assertFalse(
            server.card_check_covers(cert(card_check={"card_number": "4YU1RY8KKM"})))
        self.assertFalse(server.card_check_covers("not a cert"))

    def test_whitespace_is_not_a_different_card(self):
        self.assertTrue(
            server.card_check_covers(cert(card_number=" 4YU1RY8KKM ",
                                          card_check=checked("4YU1RY8KKM"))))


# ── The daily regeneration: what the clearance actually clears ──────────────

class DailyRegenerationTest(unittest.TestCase):
    """`sst_status` is frozen onto each check-in row AT CHECK-IN from
    `_sst_cert_state`, so approving row A does nothing for row B tomorrow. The
    only way a clearance survives the night is to change what
    `_sst_cert_state` says about the CERT."""

    def test_colour_derived_class_is_unknown_without_a_check(self):
        """Guard on the pre-existing rule -- if this ever passes vacuously the
        test below proves nothing."""
        self.assertEqual(server._sst_cert_state(cert(), NOW), "unknown")

    def test_colour_derived_class_is_valid_once_the_card_is_checked(self):
        self.assertEqual(
            server._sst_cert_state(cert(card_check=checked()), NOW), "valid")

    def test_a_conflict_is_settled_by_the_human_the_conflict_asked_for(self):
        c = cert(class_source="conflict", review_reason="CLASS_CONFLICTED")
        self.assertEqual(server._sst_cert_state(c, NOW), "unknown")
        c["card_check"] = checked()
        self.assertEqual(server._sst_cert_state(c, NOW), "valid")

    def test_a_check_against_a_stale_card_number_does_not_clear_it(self):
        c = cert(card_check=checked("THEOLDONE1"))
        self.assertEqual(server._sst_cert_state(c, NOW), "unknown")

    def test_a_check_does_not_invent_a_class_the_ocr_could_not_read(self):
        c = cert(type="SST_UNSPECIFIED", class_source=None,
                 review_reason="CLASS_UNVERIFIED", card_check=checked())
        self.assertEqual(server._sst_cert_state(c, NOW), "unknown")

    def test_a_check_does_not_revive_a_dead_card_scheme(self):
        c = cert(type="SST_LIMITED", class_source="color_and_text",
                 card_check=checked())
        self.assertEqual(server._sst_cert_state(c, NOW), "unknown")

    def test_a_check_does_not_supply_an_expiry_the_card_never_gave(self):
        c = cert(expiration_date=None, card_check=checked())
        self.assertEqual(server._sst_cert_state(c, NOW), "unknown")

    def test_a_check_does_not_un_expire_a_card(self):
        c = cert(expiration_date=PAST, card_check=checked())
        self.assertEqual(server._sst_cert_state(c, NOW), "expired")


# ── Minimal async Mongo fakes (same shape as
#    test_checkin_cert_snapshot_review.py, kept local so this module does not
#    couple to another test's harness) ───────────────────────────────────────

class _Result:
    def __init__(self, _id):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
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
        return _FakeCursor([])

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


def _card_check_db(certs=None):
    db = _FakeDb()
    db.checkins.set_find_one({
        "_id": "chk1", "project_id": "proj1", "worker_id": "wkr1",
        "worker_name": "Jane Worker", "sst_status": "unknown",
        "sst_card_number": "4YU1RY8KKM",
    })
    db.projects.set_find_one({"_id": "proj1", "company_id": "co_a"})
    db.workers.set_find_one({
        "_id": "wkr1",
        "name": "Jane Worker",
        # TWO certs, and the SST one is SECOND. A control that patched index 0
        # would clear the OSHA row and pass -- exactly the wrong-occurrence
        # failure this repo has been bitten by.
        "certifications": [
            {"type": "OSHA_30", "card_number": "OSHA-1", "needs_review": True},
        ] + (certs if certs is not None else [cert()]),
    })
    return db


def _client(*, role="cp", company_id="co_a", user_id="u1",
            assigned_projects=("proj1",), name="Carl CP"):
    user = {
        "_id": user_id, "id": user_id, "role": role,
        "company_id": company_id, "full_name": name,
        "assigned_projects": list(assigned_projects),
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _post(db, body, **client_kw):
    client, cleanup = _client(**client_kw)
    try:
        with patch.object(server, "db", db):
            return client.post("/api/checkins/chk1/card-check", json=body)
    finally:
        cleanup()


class CardCheckEndpointTest(unittest.TestCase):

    def test_the_cp_can_clear_it_and_the_attestation_is_recorded(self):
        db = _card_check_db()
        resp = _post(db, {"card_number": "4YU1RY8KKM"})
        self.assertEqual(resp.status_code, 200, resp.text)

        # INDEX 1, not 0 -- the SST row, not the OSHA row beside it.
        self.assertIs(db.workers.last_set("certifications.1.needs_review"), False)
        self.assertIsNone(db.workers.last_set("certifications.0.needs_review"))

        block = db.workers.last_set("certifications.1.card_check")
        self.assertEqual(block["card_number"], "4YU1RY8KKM")
        self.assertEqual(block["checked_by"], "u1")
        self.assertEqual(block["checked_by_name"], "Carl CP")
        self.assertIsInstance(block["checked_at"], datetime)

    def test_attribution_is_server_derived_not_client_supplied(self):
        db = _card_check_db()
        resp = _post(db, {
            "card_number": "4YU1RY8KKM",
            "checked_by": "HACKER", "checked_by_name": "Not Me",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        block = db.workers.last_set("certifications.1.card_check")
        self.assertEqual(block["checked_by"], "u1")
        self.assertEqual(block["checked_by_name"], "Carl CP")

    def test_the_checkin_row_carries_the_attestation_for_display(self):
        db = _card_check_db()
        resp = _post(db, {"card_number": "4YU1RY8KKM"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            db.checkins.last_set("sst_card_checked_number"), "4YU1RY8KKM")
        self.assertEqual(db.checkins.last_set("sst_card_checked_by_name"), "Carl CP")
        self.assertIsInstance(db.checkins.last_set("sst_card_checked_at"), datetime)

    def test_no_card_number_is_refused_not_recorded_against_null(self):
        db = _card_check_db()
        for body in ({}, {"card_number": ""}, {"card_number": "   "}):
            resp = _post(db, body)
            self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(db.workers.updated, [])

    def test_a_card_number_that_matches_no_live_cert_is_refused(self):
        """The number the screen showed is submitted back and must still be the
        number on the record. If it is not, the card was corrected since the
        screen loaded and the CP looked at a different card."""
        db = _card_check_db()
        resp = _post(db, {"card_number": "THEOLDONE1"})
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(db.workers.updated, [])

    def test_a_cert_with_no_card_number_offers_nothing_to_attest_against(self):
        db = _card_check_db(certs=[cert(card_number=None)])
        resp = _post(db, {"card_number": "4YU1RY8KKM"})
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(db.workers.updated, [])

    def test_wrong_company_is_forbidden(self):
        db = _card_check_db()
        resp = _post(db, {"card_number": "4YU1RY8KKM"},
                     company_id="co_other", assigned_projects=())
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertEqual(db.workers.updated, [])

    def test_it_is_audited(self):
        db = _card_check_db()
        resp = _post(db, {"card_number": "4YU1RY8KKM"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.audit_logs.inserted), 1)
        entry = db.audit_logs.inserted[0]
        self.assertEqual(entry["action"], "sst_card_check")
        self.assertEqual(entry["resource_type"], "checkin")
        self.assertEqual(entry["resource_id"], "chk1")
        self.assertEqual(entry["details"], {"card_number": "4YU1RY8KKM"})

    def test_it_is_a_separate_claim_from_approve_send_home(self):
        """"I checked this card" is not "approved". The review endpoint's
        fields must not be written by this one."""
        db = _card_check_db()
        resp = _post(db, {"card_number": "4YU1RY8KKM"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(db.checkins.last_set("review_decision"))
        self.assertIsNone(db.checkins.last_set("reviewed_by"))


class RouteIsMountedTest(unittest.TestCase):
    def test_the_endpoint_exists_under_api(self):
        paths = {
            (r.path, tuple(sorted(r.methods or ())))
            for r in server.app.routes if hasattr(r, "methods")
        }
        self.assertIn(("/api/checkins/{checkin_id}/card-check", ("POST",)), paths)


if __name__ == "__main__":
    unittest.main()
