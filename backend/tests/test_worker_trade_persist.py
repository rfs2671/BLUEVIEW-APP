"""Trade is confirmed PER PROJECT — a worker-level trade is never a shortcut.

An earlier change made POST /checkins/{id}/assign-trade authoritative on
the WORKER document (trade + company + trade_source="cp_assignment") and
let both gate paths reuse that marked pair to suppress
needs_trade_assignment. That ruling was superseded.

The rule this file locks in:
  • a worker re-confirms trade and company on every project, even if he
    has checked in elsewhere before — the gate never reads a worker-level
    trade to decide the flag;
  • the CP assigns a trade ONLY where none was captured (fill-if-empty,
    never overwrite) — asserted in test_checkin_assign_trade.py;
  • no cp_assignment provenance is written anywhere.

The Fix 5 `worker.update(update_fields)` refreshes that follow each
worker update_one are guarded here too — without them a returning worker
who changed employer freezes the STALE company onto today's check-in.
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

_NO_CERT_GATE = {"cleared": True, "warnings": [], "blocks": []}


# ── assign-trade touches only the trade, and only when it is empty ───────

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


class AssignTradeWorkerWriteIsMinimalTest(unittest.TestCase):

    def test_no_cp_assignment_provenance_is_written(self):
        """trade_source / trade_assigned_* on the WORKER were the state the
        superseded ruling needed. Nothing may write them again."""
        db = _assign_db({"_id": "w1", "name": "Jane", "trade": ""})
        resp = _assign(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        for field in ("trade_source", "trade_assigned_by", "trade_assigned_at"):
            self.assertIsNone(
                db.workers.last_set(field), f"worker.{field} was written",
            )

    def test_company_is_not_persisted_to_the_worker(self):
        """Company is confirmed per project too; assign-trade fills the
        empty trade and nothing else."""
        db = _assign_db({"_id": "w1", "name": "Jane", "trade": ""})
        _assign(db)
        self.assertEqual(db.workers.last_set("trade"), "Carpenter")
        self.assertIsNone(db.workers.last_set("company"))

    def test_the_checkin_row_is_still_updated_and_unflagged(self):
        """The revert removes only the worker-document overwrite — the
        check-in row keeps every field assign-trade has always set."""
        db = _assign_db({"_id": "w1", "name": "Jane", "trade": ""})
        _assign(db)
        self.assertEqual(db.checkins.last_set("trade"), "Carpenter")
        self.assertEqual(db.checkins.last_set("company"), "Acme Co")
        self.assertEqual(db.checkins.last_set("worker_trade"), "Carpenter")
        self.assertEqual(db.checkins.last_set("worker_company"), "Acme Co")
        self.assertIs(db.checkins.last_set("needs_trade_assignment"), False)


# ── the gate never reuses a worker-level trade ───────────────────────────

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

# The exact shape the superseded ruling would have reused at the gate.
_MARKED_WORKER = {
    "_id": "w1", "name": "Jane", "trade": "Carpenter", "company": "Acme Co",
    "trade_source": "cp_assignment",
}


class TradeIsConfirmedPerProjectTest(unittest.TestCase):

    def test_no_roster_still_flags_a_worker_with_a_prior_trade(self):
        """A worker who confirmed Carpenter/Acme on another project still
        gets flagged here — trade is confirmed per project."""
        db = _gate_db(roster=[], worker=dict(_MARKED_WORKER))
        resp = _register(db, dict(_REG_BODY))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], True)
        self.assertEqual(row["trade"], "UNASSIGNED")

    def test_not_listed_still_flags_even_when_the_pair_is_on_the_roster(self):
        db = _gate_db(roster=_ROSTER, worker=dict(_MARKED_WORKER))
        resp = _register(db, dict(_REG_BODY, trade_not_listed=True))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIs(
            db.checkins.inserted[-1]["needs_trade_assignment"], True,
        )

    def test_submit_endpoint_also_flags(self):
        db = _gate_db(roster=[], worker=dict(_MARKED_WORKER))
        resp = _submit(db, {
            "project_id": "proj1", "tag_id": "t1", "name": "Jane",
            "phone": "5551234567", "trade": "", "company": "",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], True)
        self.assertEqual(row["trade"], "UNASSIGNED")


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
