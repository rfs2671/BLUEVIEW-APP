"""POST /logbooks/{id}/finalize — completeness gate.

Finalizing is what makes a log immutable, so an empty or unsigned document
must not be able to reach that state; after the lock, the only way back is an
amendment. The gate asserts two conditions and nothing else:

  * `data` is non-empty
  * `cp_signature` is present

Placement matters as much as the rule:
  * AFTER the is_locked early-return, so re-finalizing an already-locked log
    is still idempotent and never starts returning 400.
  * BEFORE the update_one, so a rejected finalize mutates nothing — no lock,
    no status change, no audit entry.

The rejection carries a machine CODE, not prose. The server names the
condition and the client owns the wording (the BLOCK_LABELS map in
backend/checkin.html is the existing instance of this); there is no
server-side bilingual error shape in this codebase and this does not add one.
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
    def __init__(self, _id):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
        self.inserted = []
        self.updated = []

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query or {}) if callable(v) else v

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))
        return _Result("x")

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result("x")


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection(n)
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


_SIG = {"paths": [[1, 2]], "signed_at": "2026-07-20T12:00:00Z"}


def _mk_db(**overrides):
    log = {
        "_id": "lb1", "project_id": "proj1", "company_id": "co_a",
        "log_type": "pre_shift", "date": "2026-07-20",
        "data": {"workers": [{"name": "Jane"}]},
        "cp_signature": _SIG,
        "created_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
    }
    log.update(overrides)
    db = _FakeDb()
    db.logbooks.set_find_one(lambda q: log)
    return db


def _finalize(db, *, role="admin", assigned_projects=None):
    user = {
        "_id": "u1", "id": "u1", "role": role, "company_id": "co_a",
        "full_name": "Ada Admin",
        "assigned_projects": assigned_projects or ["proj1"],
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            return TestClient(server.app).post("/api/logbooks/lb1/finalize")
    finally:
        server.app.dependency_overrides.clear()


class FinalizeCompletenessGateTest(unittest.TestCase):

    # ── the happy path is not broken ─────────────────────────────────────

    def test_complete_log_finalizes(self):
        db = _mk_db()
        resp = _finalize(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(db.logbooks.updated)

    # ── empty data ───────────────────────────────────────────────────────

    def test_missing_data_key_rejected(self):
        db = _mk_db(data=None)
        resp = _finalize(db)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "FINALIZE_EMPTY_LOG")

    def test_empty_dict_data_rejected(self):
        db = _mk_db(data={})
        resp = _finalize(db)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "FINALIZE_EMPTY_LOG")

    def test_non_empty_data_of_any_shape_is_accepted(self):
        """Empty-vs-non-empty only. The gate must not grow per-field rules —
        what a complete payload looks like differs per log type."""
        for payload in ({"anything": 1}, {"workers": []}, {"x": None}):
            with self.subTest(payload=payload):
                db = _mk_db(data=payload)
                self.assertEqual(_finalize(db).status_code, 200)

    # ── cp_signature ─────────────────────────────────────────────────────

    def test_missing_cp_signature_rejected(self):
        db = _mk_db(cp_signature=None)
        resp = _finalize(db)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(
            resp.json()["detail"]["code"], "FINALIZE_MISSING_CP_SIGNATURE",
        )

    def test_empty_cp_signature_rejected(self):
        db = _mk_db(cp_signature={})
        resp = _finalize(db)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(
            resp.json()["detail"]["code"], "FINALIZE_MISSING_CP_SIGNATURE",
        )

    def test_signature_presence_only_no_content_rules(self):
        """Presence, not shape. Validating the signature's internals here would
        duplicate _finalize_cp_signature, which owns that on the save path."""
        db = _mk_db(cp_signature={"paths": []})
        self.assertEqual(_finalize(db).status_code, 200)

    # ── placement ────────────────────────────────────────────────────────

    def test_rejection_mutates_nothing(self):
        db = _mk_db(data={})
        _finalize(db)
        self.assertEqual(db.logbooks.updated, [], "log was mutated on rejection")
        self.assertEqual(db.audit_logs.inserted, [], "audit entry on rejection")

    def test_locked_log_stays_idempotent_even_when_incomplete(self):
        """The gate sits after the is_locked early-return. A log locked before
        the gate existed must keep returning 200, not start 400ing."""
        db = _mk_db(is_locked=True, data={}, cp_signature=None)
        resp = _finalize(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.logbooks.updated, [])

    def test_auth_still_runs_before_the_gate(self):
        """An unassigned CP gets 403, not a 400 that would leak completeness."""
        db = _mk_db(data={})
        resp = _finalize(db, role="cp", assigned_projects=["other"])
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_missing_log_is_still_404(self):
        db = _FakeDb()
        db.logbooks.set_find_one(lambda q: None)
        self.assertEqual(_finalize(db).status_code, 404)

    # ── no server-side bilingual shape ───────────────────────────────────

    def test_detail_carries_a_code_and_no_translated_prose(self):
        db = _mk_db(data={})
        detail = _finalize(db).json()["detail"]
        self.assertEqual(list(detail), ["code"])
        for banned in ("detail_en", "detail_es", "message_en", "message_es"):
            self.assertNotIn(banned, detail)


if __name__ == "__main__":
    unittest.main()
