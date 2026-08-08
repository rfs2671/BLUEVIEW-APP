"""An empty roster must never block a worker at the gate.

POST /api/checkin/submit used to hard-400 ("This project has no
subcontractors configured yet") when the project had no
trade_assignments — a pure config gap became a hard block on a real
person standing at the gate. register_and_checkin already failed open on
the same condition; /checkin/submit now mirrors it: admit, mark the trade
UNASSIGNED, flag needs_trade_assignment, notify the CP.

The strict roster match is UNCHANGED for projects that DO have trades.
"""

from __future__ import annotations

import os
import sys
import unittest
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


class _Result:
    def __init__(self, _id="x"):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _FakeCollection:
    def __init__(self):
        self._find_one = None
        self.inserted = []
        self.updated = []

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query) if callable(v) else v

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))
        return _Result()

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result()

    def last_set(self, field):
        for _q, u in reversed(self.updated):
            s = u.get("$set") or {}
            if field in s:
                return s[field]
        return None


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


_ROSTER = [{"trade": "Carpenter", "company": "Acme Co"}]


def _mk_db(*, roster, worker=None, existing_checkin=None):
    db = _FakeDb()
    db.nfc_tags.set_find_one({
        "tag_id": "t1", "project_id": "proj1", "status": "active",
    })
    db.projects.set_find_one({
        "_id": "proj1", "name": "Test Tower", "company_id": "co_a",
        "admin_id": "admin1", "trade_assignments": roster,
    })
    db.workers.set_find_one(worker)
    db.checkins.set_find_one(existing_checkin)
    return db


_BODY = {
    "project_id": "proj1", "tag_id": "t1",
    "name": "Jane Worker", "phone": "5551234567",
    "trade": "", "company": "",
}


def _submit(db, body=None):
    with patch.object(server, "db", db), \
            patch.object(server, "validate_worker_certifications",
                         lambda *a, **k: {"cleared": True, "warnings": [],
                                          "blocks": []}):
        return TestClient(server.app).post(
            "/api/checkin/submit", json=dict(body or _BODY),
        )


class EmptyRosterAdmitsTest(unittest.TestCase):

    def test_empty_roster_admits_instead_of_400(self):
        db = _mk_db(roster=[])
        resp = _submit(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["needs_trade_assignment"])

    def test_admitted_row_is_flagged_and_marked_unassigned(self):
        db = _mk_db(roster=[])
        _submit(db)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], True)
        self.assertEqual(row["trade"], "UNASSIGNED")
        self.assertEqual(row["company"], "UNASSIGNED")
        self.assertEqual(row["worker_trade"], "UNASSIGNED")

    def test_a_roster_of_only_inactive_rows_counts_as_empty(self):
        """Soft-deleting the last sub must not re-create the hard block."""
        db = _mk_db(roster=[
            {"trade": "Carpenter", "company": "Acme Co", "id": "srv_1",
             "status": "inactive"},
        ])
        resp = _submit(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIs(
            db.checkins.inserted[-1]["needs_trade_assignment"], True,
        )

    def test_cp_is_notified(self):
        db = _mk_db(roster=[])
        seen = {}

        async def _fake_dispatch(_db, **kw):
            seen.update(kw)

        with patch.object(server._notifications_inbox, "dispatch_notification",
                          _fake_dispatch):
            resp = _submit(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(seen.get("kind"), "checkin_needs_trade")
        self.assertEqual(seen["metadata"]["reason"], "no_roster")

    def test_a_failed_notification_never_blocks_the_worker(self):
        db = _mk_db(roster=[])

        async def _boom(_db, **kw):
            raise RuntimeError("inbox down")

        with patch.object(server._notifications_inbox, "dispatch_notification",
                          _boom):
            resp = _submit(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.checkins.inserted), 1)


class StrictRosterStillEnforcedTest(unittest.TestCase):

    def test_non_empty_roster_still_rejects_a_pair_not_on_it(self):
        db = _mk_db(roster=_ROSTER)
        resp = _submit(db, dict(
            _BODY, trade="Plumber", company="Pipes Inc",
        ))
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("pick your trade and company", resp.json()["detail"])

    def test_non_empty_roster_admits_a_matching_pair_unflagged(self):
        db = _mk_db(roster=_ROSTER)
        resp = _submit(db, dict(
            _BODY, trade="carpenter", company="acme co",
        ))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], False)
        # Canonicalized to the admin's exact casing.
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["company"], "Acme Co")


class RegisterAndCheckinStillFailsOpenTest(unittest.TestCase):
    """The behaviour /checkin/submit was aligned TO — pinned so the two
    gate paths cannot drift apart again."""

    def test_register_and_checkin_admits_on_empty_roster(self):
        db = _mk_db(roster=[])
        with patch.object(server, "db", db), \
                patch.object(server, "validate_worker_certifications",
                             lambda *a, **k: {"cleared": True,
                                              "warnings": [], "blocks": []}):
            resp = TestClient(server.app).post(
                "/api/checkin/register-and-checkin",
                json={"project_id": "proj1", "tag_id": "t1",
                      "name": "Jane Worker", "phone": "5551234567"},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIs(
            db.checkins.inserted[-1]["needs_trade_assignment"], True,
        )


if __name__ == "__main__":
    unittest.main()
