"""A safety orientation may be CREATED without a trade. It may not be SUBMITTED.

THE SPLIT IS THE WHOLE RULE, AND THESE TESTS EXIST TO STOP IT COLLAPSING.

  CREATE stays fail-open. register_and_checkin writes the orientation draft
  itself with `"worker_trade": trade or ""`, and that path must never block a
  man standing at the turnstile. This codebase already learned that the hard
  way — see the strict-roster comment, "a pure config gap became a hard block
  on a real person". A worker is not turned away because an admin has not
  finished the roster.

  SUBMIT is where the trade has to exist. A filed orientation with no trade
  names no scope of work, and the record is entirely about what this man was
  oriented TO do on this site. The CP is blocked, not the worker.

Built on the mechanism that was already there: SUBMIT_MISSING_TRADE sits
alongside SUBMIT_EMPTY_LOG and SUBMIT_MISSING_CP_SIGNATURE, same machine-code
convention, client owns the wording. No new mechanism was invented.
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

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

PROJECT = {"_id": "proj1", "name": "857 Prescott Pl", "company_id": "co_a"}
USER = {
    "_id": "u1", "id": "u1", "role": "admin", "company_id": "co_a",
    "assigned_projects": ["proj1"], "full_name": "Ada Admin",
}
ORIENT = "subcontractor_orientation"
# cp_signature is Optional[Dict] on the models, never a bare string.
SIG = {"image": "data:image/png;base64,AAA", "signed_at": "2026-03-04T12:00:00Z",
       # AFFIRMED: this fixture stands for a CP who signed AND affirmed.
       # The submit gate now asks `affirmed is True`, the same question the
       # PDF renderer and the EOD sweep ask, instead of mere presence.
       "affirmed": True, "affirmedAt": "2026-03-04T12:00:00Z"}


def _data(**over):
    d = {
        "worker_id": "w1",
        "worker_name": "Hector Ramirez",
        "worker_company": "Vanguard Concrete Corp",
        "worker_trade": "Concrete",
        "checklist": {"hard_hats": True},
        "completed_at": "2026-03-04T12:00:00Z",
    }
    d.update(over)
    return d


# ── THE PURE RULE ────────────────────────────────────────────────────────────
class TestTheRuleItself(unittest.TestCase):
    """_submit_missing_trade_detail — the one helper both endpoints call."""

    def test_a_trade_allows_the_submit(self):
        self.assertIsNone(server._submit_missing_trade_detail(ORIENT, _data()))

    def test_no_trade_refuses_and_names_the_worker(self):
        d = server._submit_missing_trade_detail(ORIENT, _data(worker_trade=""))
        self.assertEqual(d["code"], "SUBMIT_MISSING_TRADE")
        self.assertEqual(d["worker_name"], "Hector Ramirez",
                         "the refusal must name WHO, or it is a dead end")
        self.assertEqual(d["worker_id"], "w1",
                         "and identify the row, so the client can point at it")

    def test_whitespace_is_not_a_trade(self):
        self.assertIsNotNone(
            server._submit_missing_trade_detail(ORIENT, _data(worker_trade="   ")))

    def test_a_missing_key_is_not_a_trade(self):
        d = dict(_data())
        d.pop("worker_trade")
        self.assertIsNotNone(server._submit_missing_trade_detail(ORIENT, d))

    def test_no_other_log_type_is_touched(self):
        for lt in ("daily_jobsite", "toolbox_talk", "preshift_signin", "osha_log",
                   "hot_work", "crane_operations", None, ""):
            self.assertIsNone(
                server._submit_missing_trade_detail(lt, {"anything": 1}), lt)

    def test_a_nameless_worker_still_refuses(self):
        """The refusal stands even when there is no name to report — it degrades
        to a null name rather than letting the submit through."""
        d = server._submit_missing_trade_detail(
            ORIENT, {"worker_trade": "", "worker_id": "w9"})
        self.assertEqual(d["code"], "SUBMIT_MISSING_TRADE")
        self.assertIsNone(d["worker_name"])

    def test_a_non_dict_payload_does_not_crash_the_endpoint(self):
        for junk in (None, [], "x", 7):
            self.assertIsNone(server._submit_missing_trade_detail(ORIENT, junk), junk)


# ── THE ENDPOINTS ────────────────────────────────────────────────────────────
class _Cursor:
    def __init__(self, docs): self._d = list(docs)
    async def to_list(self, n=None): return list(self._d)
    def __aiter__(self):
        async def g():
            for x in self._d:
                yield x
        return g()


class _Coll:
    def __init__(self, docs=None, find_one=None):
        self.docs = list(docs or [])
        self._find_one = find_one
        self.inserted = []
        self.updated = []

    def find(self, q=None, *a, **k): return _Cursor(self.docs)

    async def find_one(self, q=None, *a, **k):
        return self._find_one(q) if callable(self._find_one) else self._find_one

    async def insert_one(self, doc):
        self.inserted.append(doc)
        class R: inserted_id = "new_id"
        return R()

    async def update_one(self, q, u, **k):
        self.updated.append((q, u))
        class R:
            modified_count = 1
            matched_count = 1
            upserted_id = None
        return R()

    async def count_documents(self, *a, **k): return 0


class _Db:
    def __init__(self, **c): self._c = dict(c)
    def __getattr__(self, n):
        if n.startswith("_"): raise AttributeError(n)
        return self._c.setdefault(n, _Coll())


def _post(db, body):
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    client = TestClient(server.app)
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v), \
                patch.object(server, "audit_log", _noop):
            return client.post("/api/logbooks", json=body)
    finally:
        server.app.dependency_overrides.clear()


def _put(db, logbook_id, body):
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    client = TestClient(server.app)
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v), \
                patch.object(server, "audit_log", _noop):
            return client.put(f"/api/logbooks/{logbook_id}", json=body)
    finally:
        server.app.dependency_overrides.clear()


async def _noop(*a, **k):
    return None


def _create_db():
    return _Db(
        projects=_Coll(find_one=lambda q: PROJECT),
        logbooks=_Coll(find_one=lambda q: None),
    )


class TestCreateEndpoint(unittest.TestCase):
    def _body(self, status, **over):
        return {
            "project_id": "proj1", "log_type": ORIENT, "date": "2026-03-04",
            "data": _data(**over), "cp_signature": SIG, "cp_name": "Ada",
            "status": status,
        }

    def test_DRAFT_with_no_trade_is_ALLOWED(self):
        """The fail-open half. The gate check-in creates exactly this."""
        r = _post(_create_db(), self._body("draft", worker_trade=""))
        self.assertNotEqual(r.status_code, 400, r.text)

    def test_SUBMIT_with_no_trade_is_REFUSED_by_code(self):
        r = _post(_create_db(), self._body("submitted", worker_trade=""))
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"]["code"], "SUBMIT_MISSING_TRADE")

    def test_the_refusal_names_the_worker(self):
        r = _post(_create_db(), self._body("submitted", worker_trade=""))
        self.assertEqual(r.json()["detail"]["worker_name"], "Hector Ramirez")

    def test_SUBMIT_with_a_trade_passes_the_gate(self):
        r = _post(_create_db(), self._body("submitted"))
        self.assertNotEqual(r.status_code, 400, r.text)

    def test_a_refused_submit_WRITES_NOTHING(self):
        db = _create_db()
        _post(db, self._body("submitted", worker_trade=""))
        self.assertEqual(db.logbooks.inserted, [],
                         "a rejected submit must mutate nothing at all")

    def test_another_log_type_submits_without_a_trade(self):
        body = {
            "project_id": "proj1", "log_type": "daily_jobsite", "date": "2026-03-04",
            "data": {"weather": "Sunny"}, "cp_signature": SIG, "cp_name": "Ada",
            "status": "submitted",
        }
        r = _post(_create_db(), body)
        self.assertNotEqual(r.status_code, 400, r.text)


class TestUpdateEndpoint(unittest.TestCase):
    """THE PATH THE CP ACTUALLY WALKS. The gate check-in creates the draft, so
    the CP's signature always arrives as a PUT — a gate on create alone would
    never see it."""

    def _db(self, stored_trade):
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": ORIENT,
            "data": _data(worker_trade=stored_trade),
            "cp_signature": None, "is_locked": False,
        }
        return _Db(
            projects=_Coll(find_one=lambda q: PROJECT),
            logbooks=_Coll(find_one=lambda q: stored),
        )

    def test_signing_a_trade_less_draft_is_REFUSED(self):
        r = _put(self._db(""), "lb1", {"cp_signature": SIG, "cp_name": "Ada",
                                       "status": "submitted"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"]["code"], "SUBMIT_MISSING_TRADE")

    def test_signing_once_the_trade_is_assigned_SUCCEEDS(self):
        r = _put(self._db("Concrete"), "lb1", {"cp_signature": SIG,
                                               "cp_name": "Ada", "status": "submitted"})
        self.assertNotEqual(r.status_code, 400, r.text)

    def test_a_trade_arriving_IN_THIS_REQUEST_is_accepted(self):
        """Judged on the EFFECTIVE post-update state: assigning the trade and
        signing in one call must work, not be rejected on the stale doc."""
        r = _put(self._db(""), "lb1", {
            "data": _data(worker_trade="Concrete"),
            "cp_signature": SIG, "cp_name": "Ada", "status": "submitted",
        })
        self.assertNotEqual(r.status_code, 400, r.text)

    def test_clearing_the_trade_IN_THIS_REQUEST_is_refused(self):
        """...and the reverse: a stored trade cannot be blanked on the way in."""
        r = _put(self._db("Concrete"), "lb1", {
            "data": _data(worker_trade=""),
            "cp_signature": SIG, "cp_name": "Ada", "status": "submitted",
        })
        self.assertEqual(r.status_code, 400, r.text)

    def test_saving_a_trade_less_DRAFT_is_still_allowed(self):
        r = _put(self._db(""), "lb1", {"data": _data(worker_trade=""),
                                       "status": "draft"})
        self.assertNotEqual(r.status_code, 400, r.text)

    def test_a_refused_submit_DOES_NOT_LOCK_THE_RECORD(self):
        db = self._db("")
        _put(db, "lb1", {"cp_signature": SIG, "cp_name": "Ada",
                         "status": "submitted"})
        for _q, u in db.logbooks.updated:
            flat = str(u)
            self.assertNotIn("is_locked", flat,
                             "a refusal must never freeze the record")
        self.assertEqual(db.logbooks.updated, [],
                         "a refused submit mutates nothing at all")


class TestTheGateCheckInPathStaysFailOpen(unittest.TestCase):
    def test_register_and_checkin_still_writes_a_trade_less_draft(self):
        """Asserted on the SOURCE: the orientation insert must keep tolerating an
        empty trade and must keep creating it as a draft. If this ever becomes a
        hard requirement, a worker gets blocked at the turnstile for an admin's
        unfinished roster — the exact failure the fail-open policy exists for."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn('"worker_trade": trade or ""', src)
        i = src.index('"worker_trade": trade or ""')
        window = src[max(0, i - 2000):i]
        self.assertIn('"log_type": "subcontractor_orientation"', window)
        self.assertIn('"status": "draft"', window)

    def test_the_gate_is_wired_into_both_endpoints_exactly_once(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("_submit_missing_trade_detail("), 3,
                         "1 definition + create + update")

    def test_the_code_matches_the_existing_machine_code_convention(self):
        """draftSync's GATE_CODE is /^(?:FINALIZE|SUBMIT)_[A-Z_]+$/ — a code it
        does not match is silently dropped and the CP sees generic copy."""
        import re
        self.assertTrue(re.match(r"^(?:FINALIZE|SUBMIT)_[A-Z_]+$",
                                 "SUBMIT_MISSING_TRADE"))


if __name__ == "__main__":
    unittest.main()
