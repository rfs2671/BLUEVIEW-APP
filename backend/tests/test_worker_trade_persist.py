"""A CP's trade correction sticks to the WORKER, not just the check-in.

POST /checkins/{id}/assign-trade previously wrote the trade onto the
worker only when the worker had none, so the same person re-flagged on
every subsequent check-in and the CP re-corrected them daily. The
correction is now authoritative on the worker document and is marked
trade_source="cp_assignment"; the gate paths reuse that marked pair
instead of re-raising needs_trade_assignment.

This is deliberately cross-project and cross-company — the worker doc is
not project-scoped.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
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


_ROSTER = [{"trade": "Carpenter", "company": "Acme Co", "id": "srv_1"}]
_CORRECTED_WORKER = {
    "_id": "w1", "name": "Jane", "trade": "Carpenter", "company": "Acme Co",
    "trade_source": "cp_assignment",
}

_NO_CERT_GATE = {"cleared": True, "warnings": [], "blocks": []}


# ── assign-trade writes the correction onto the worker ───────────────────

def _assign_db(worker):
    db = _FakeDb()
    db.checkins.set_find_one({
        "_id": "chk1", "project_id": "proj1", "worker_id": "w1",
        "worker_name": "Jane", "needs_trade_assignment": True,
        "check_in_time": datetime(2026, 7, 20, tzinfo=timezone.utc),
    })
    db.projects.set_find_one({
        "_id": "proj1", "name": "Test Tower", "company_id": "co_a",
        "trade_assignments": _ROSTER,
    })
    db.workers.set_find_one(worker)
    return db


def _assign(db, body=None):
    user = {
        "_id": "u1", "id": "u1", "role": "admin", "company_id": "co_a",
        "full_name": "Ada Admin", "assigned_projects": [],
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            return TestClient(server.app).post(
                "/api/checkins/chk1/assign-trade",
                json=body or {"trade": "Carpenter", "company": "Acme Co"},
            )
    finally:
        server.app.dependency_overrides.clear()


class AssignTradePersistsToWorkerTest(unittest.TestCase):

    def test_correction_is_written_to_the_worker(self):
        db = _assign_db({"_id": "w1", "name": "Jane", "trade": ""})
        resp = _assign(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.workers.last_set("trade"), "Carpenter")
        self.assertEqual(db.workers.last_set("company"), "Acme Co")
        self.assertEqual(db.workers.last_set("trade_source"), "cp_assignment")
        self.assertEqual(db.workers.last_set("trade_assigned_by"), "u1")

    def test_correction_overwrites_a_trade_the_worker_already_carried(self):
        """The CP's decision is authoritative. This is the behaviour change
        that stops the same worker re-flagging every day; it is deliberately
        cross-project."""
        db = _assign_db({"_id": "w1", "name": "Jane", "trade": "Electrician"})
        resp = _assign(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.workers.last_set("trade"), "Carpenter")

    def test_the_checkin_row_is_still_updated_and_unflagged(self):
        db = _assign_db({"_id": "w1", "name": "Jane", "trade": ""})
        _assign(db)
        self.assertEqual(db.checkins.last_set("trade"), "Carpenter")
        self.assertIs(
            db.checkins.last_set("needs_trade_assignment"), False,
        )


# ── the marker suppresses re-flagging at the gate ────────────────────────

def _gate_db(*, roster, worker=None):
    db = _FakeDb()
    db.nfc_tags.set_find_one({
        "tag_id": "t1", "project_id": "proj1", "status": "active",
    })
    db.projects.set_find_one({
        "_id": "proj1", "name": "Test Tower", "company_id": "co_a",
        "admin_id": "admin1", "trade_assignments": roster,
    })
    db.workers.set_find_one(worker)
    db.checkins.set_find_one(None)
    return db


def _register(db, body):
    with patch.object(server, "db", db), \
            patch.object(server, "validate_worker_certifications",
                         lambda *a, **k: _NO_CERT_GATE):
        return TestClient(server.app).post(
            "/api/checkin/register-and-checkin", json=body,
        )


def _submit(db, body):
    with patch.object(server, "db", db), \
            patch.object(server, "validate_worker_certifications",
                         lambda *a, **k: _NO_CERT_GATE):
        return TestClient(server.app).post("/api/checkin/submit", json=body)


_REG_BODY = {
    "project_id": "proj1", "tag_id": "t1",
    "name": "Jane", "phone": "5551234567",
}


class CorrectedTradeSuppressesReflagTest(unittest.TestCase):

    def test_no_roster_reuses_the_corrected_pair_and_does_not_reflag(self):
        db = _gate_db(roster=[], worker=dict(_CORRECTED_WORKER))
        resp = _register(db, dict(_REG_BODY))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], False)
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["company"], "Acme Co")

    def test_an_unmarked_trade_is_still_flagged(self):
        """A trade the worker typed for themselves carries no CP marker and
        must still reach a human."""
        db = _gate_db(roster=[], worker={
            "_id": "w1", "name": "Jane", "trade": "Carpenter",
            "company": "Acme Co",
        })
        resp = _register(db, dict(_REG_BODY))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIs(
            db.checkins.inserted[-1]["needs_trade_assignment"], True,
        )

    def test_an_unassigned_placeholder_does_not_count_as_corrected(self):
        db = _gate_db(roster=[], worker={
            "_id": "w1", "name": "Jane", "trade": "UNASSIGNED",
            "company": "UNASSIGNED", "trade_source": "cp_assignment",
        })
        _register(db, dict(_REG_BODY))
        self.assertIs(
            db.checkins.inserted[-1]["needs_trade_assignment"], True,
        )

    def test_not_listed_reuses_a_corrected_pair_that_is_on_the_roster(self):
        db = _gate_db(roster=_ROSTER, worker=dict(_CORRECTED_WORKER))
        resp = _register(db, dict(_REG_BODY, trade_not_listed=True))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], False)
        self.assertEqual(row["trade"], "Carpenter")

    def test_not_listed_still_flags_when_the_corrected_pair_left_the_roster(self):
        """A correction that has since been removed from the roster must not
        become a back door around the strict match."""
        db = _gate_db(
            roster=[{"trade": "Plumber", "company": "Pipes Inc"}],
            worker=dict(_CORRECTED_WORKER),
        )
        _register(db, dict(_REG_BODY, trade_not_listed=True))
        self.assertIs(
            db.checkins.inserted[-1]["needs_trade_assignment"], True,
        )

    def test_submit_endpoint_also_reuses_the_corrected_pair(self):
        db = _gate_db(roster=[], worker=dict(_CORRECTED_WORKER))
        resp = _submit(db, {
            "project_id": "proj1", "tag_id": "t1", "name": "Jane",
            "phone": "5551234567", "trade": "", "company": "",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], False)
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["company"], "Acme Co")


class WorkerRefreshNotRegressedTest(unittest.TestCase):
    """Fix 5's `worker.update(update_fields)` after each worker update_one:
    without it the check-in row freezes the STALE company of a returning
    worker who changed employer."""

    def test_register_and_checkin_row_uses_the_fresh_company(self):
        db = _gate_db(roster=_ROSTER, worker={
            "_id": "w1", "name": "Jane", "trade": "Electrician",
            "company": "Old Co",
        })
        resp = _register(db, dict(
            _REG_BODY, trade="Carpenter", company="Acme Co",
        ))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertEqual(row["worker_company"], "Acme Co")
        self.assertEqual(row["worker_trade"], "Carpenter")

    def test_submit_row_uses_the_fresh_company(self):
        db = _gate_db(roster=_ROSTER, worker={
            "_id": "w1", "name": "Jane", "trade": "Electrician",
            "company": "Old Co",
        })
        resp = _submit(db, {
            "project_id": "proj1", "tag_id": "t1", "name": "Jane",
            "phone": "5551234567",
            "trade": "Carpenter", "company": "Acme Co",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertEqual(row["worker_company"], "Acme Co")
        self.assertEqual(row["worker_trade"], "Carpenter")


if __name__ == "__main__":
    unittest.main()
