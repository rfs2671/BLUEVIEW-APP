"""Trade + company are stored PER WORKER PER PROJECT.

The rule (operator, final):

  • first check-in on a project — the worker picks trade + company and the
    {worker_id, project_id} -> {trade, company} pairing is stored in
    `worker_project_trades`;
  • later check-ins on the SAME project — the pairing is read back, the
    worker is not re-prompted, and needs_trade_assignment is NOT raised;
  • a DIFFERENT project — no pairing exists, so he picks again, entirely
    independently. A framer on one job may be a painter for another sub on
    the next;
  • NOTHING writes trade or company to the global `workers` document. That
    single worker-level slot is exactly how a value bled between projects.

Covered here: both gate paths (register-and-checkin, /checkin/submit), both
admin/NFC paths (POST /checkins, POST /checkin), assign-trade, and
lookup-worker.
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


# ── fake mongo ───────────────────────────────────────────────────────────

class _Result:
    def __init__(self, _id="new_id"):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1
        self.upserted_id = None


def _matches(doc, query):
    """Equality / $in / $ne matching — enough for the queries under test."""
    for key, cond in (query or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict):
            if "$in" in cond and val not in cond["$in"]:
                return False
            if "$ne" in cond and val == cond["$ne"]:
                return False
        elif val != cond:
            return False
    return True


class _CannedCollection:
    """find_one returns a fixed value regardless of the query; inserts and
    updates are recorded. Used for the collections whose reads the tests do
    not need to discriminate (workers, projects, nfc_tags, checkins)."""

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
            if field in (u.get("$set") or {}):
                return (u.get("$set") or {})[field]
        return None

    def any_set(self, field):
        return any(field in (u.get("$set") or {}) for _q, u in self.updated)


class _StoreCollection:
    """A real (tiny) document store — find_one actually filters, and
    update_one(upsert=True) writes. worker_project_trades MUST use this: the
    whole point of the rule is that a query for project B does not find
    project A's row."""

    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _matches(d, query or {}):
                return dict(d)
        return None

    async def insert_one(self, doc, *a, **k):
        self.docs.append(dict(doc))
        return _Result()

    async def update_one(self, q, u, *a, upsert=False, **k):
        for d in self.docs:
            if _matches(d, q or {}):
                d.update(u.get("$set") or {})
                return _Result()
        if upsert:
            new = dict(q)
            new.update(u.get("$set") or {})
            self.docs.append(new)
        return _Result()

    def pair_for(self, worker_id, project_id):
        for d in self.docs:
            if (d.get("worker_id") == worker_id
                    and d.get("project_id") == project_id):
                return d
        return None


class _FakeDb:
    def __init__(self):
        self._c = {}
        # the one collection that needs real per-project discrimination
        self._c[server.WORKER_PROJECT_TRADES_COLLECTION] = _StoreCollection()

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _CannedCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)

    @property
    def pairs(self):
        return self._c[server.WORKER_PROJECT_TRADES_COLLECTION]


_NO_CERT_GATE = {"cleared": True, "warnings": [], "blocks": []}

_ROSTER_A = [{"trade": "Carpenter", "company": "Acme Co", "id": "a1"}]
_ROSTER_B = [{"trade": "Painter", "company": "Brush LLC", "id": "b1"}]

_WORKER = {"_id": "w1", "name": "Jane Worker", "phone": "5551234567"}


def _mk_db(*, project_id="projA", roster=_ROSTER_A, worker=None, pairs=None):
    db = _FakeDb()
    db.nfc_tags.set_find_one({
        "tag_id": "t1", "project_id": project_id, "status": "active",
    })
    db.projects.set_find_one({
        "_id": project_id, "name": "Test Tower", "company_id": "co_a",
        "admin_id": "admin1", "trade_assignments": roster,
    })
    db.workers.set_find_one(worker)
    db.checkins.set_find_one(None)
    for p in (pairs or []):
        db.pairs.docs.append(dict(p))
    return db


def _pair(worker_id, project_id, trade, company):
    return {
        "worker_id": worker_id, "project_id": project_id,
        "trade": trade, "company": company,
        "updated_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }


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


def _lookup(db, body):
    with patch.object(server, "db", db):
        return TestClient(server.app).post(
            "/api/checkin/lookup-worker", json=body,
        )


def _reg_body(project_id="projA", **kw):
    body = {
        "project_id": project_id, "tag_id": "t1",
        "name": "Jane Worker", "phone": "5551234567",
    }
    body.update(kw)
    return body


def _sub_body(project_id="projA", trade="", company="", **kw):
    body = {
        "project_id": project_id, "tag_id": "t1",
        "name": "Jane Worker", "phone": "5551234567",
        "trade": trade, "company": company,
    }
    body.update(kw)
    return body


# ── 1. first check-in stores the pairing ─────────────────────────────────

class FirstCheckInStoresThePairingTest(unittest.TestCase):

    def test_register_and_checkin_stores_it(self):
        db = _mk_db(worker=dict(_WORKER))
        resp = _register(db, _reg_body(trade="Carpenter", company="Acme Co"))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.pairs.pair_for("w1", "projA")
        self.assertIsNotNone(row, "no pairing was stored")
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["company"], "Acme Co")

    def test_submit_stores_it(self):
        db = _mk_db(worker=dict(_WORKER))
        resp = _submit(db, _sub_body(trade="Carpenter", company="Acme Co"))
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.pairs.pair_for("w1", "projA")
        self.assertIsNotNone(row, "no pairing was stored")
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["company"], "Acme Co")

    def test_the_pairing_is_keyed_on_both_ids(self):
        db = _mk_db(worker=dict(_WORKER))
        _register(db, _reg_body(trade="Carpenter", company="Acme Co"))
        row = db.pairs.pair_for("w1", "projA")
        self.assertEqual(row["worker_id"], "w1")
        self.assertEqual(row["project_id"], "projA")

    def test_a_flagged_unassigned_checkin_stores_no_pairing(self):
        """UNASSIGNED is a placeholder for an answer the CP still owes. If it
        were stored, the next visit would read it back and silently skip the
        flag the CP has to clear."""
        db = _mk_db(roster=[], worker=dict(_WORKER))
        resp = _register(db, _reg_body())
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIs(
            db.checkins.inserted[-1]["needs_trade_assignment"], True,
        )
        self.assertIsNone(db.pairs.pair_for("w1", "projA"))

    def test_a_flagged_submit_stores_no_pairing(self):
        db = _mk_db(roster=[], worker=dict(_WORKER))
        resp = _submit(db, _sub_body())
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(db.pairs.pair_for("w1", "projA"))


# ── 2. the SECOND check-in on the SAME project reads it ──────────────────

class SecondCheckInSameProjectReadsThePairingTest(unittest.TestCase):

    def test_register_reads_it_and_does_not_flag(self):
        """The client sends NO trade — the returning-worker screen has none
        to send now that lookup-worker withholds it. The pairing answers."""
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _register(db, _reg_body())
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], False)
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["company"], "Acme Co")
        self.assertEqual(row["worker_trade"], "Carpenter")
        self.assertEqual(row["worker_company"], "Acme Co")

    def test_submit_reads_it_and_does_not_flag(self):
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _submit(db, _sub_body())
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIs(resp.json()["needs_trade_assignment"], False)
        row = db.checkins.inserted[-1]
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["worker_company"], "Acme Co")

    def test_an_empty_roster_no_longer_flags_a_worker_who_has_a_pairing(self):
        """The trade is not pending — it is on file for this project. An
        admin who empties the roster afterwards must not re-open it."""
        db = _mk_db(
            roster=[], worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _register(db, _reg_body())
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], False)
        self.assertEqual(row["trade"], "Carpenter")

    def test_no_400_reprompt_when_the_pairing_exists(self):
        """Without a pairing, a roster'd project 400s a blank submission to
        make the page re-prompt. With one, there is nothing to ask."""
        no_pair = _mk_db(worker=dict(_WORKER))
        self.assertEqual(_register(no_pair, _reg_body()).status_code, 400)

        with_pair = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        self.assertEqual(_register(with_pair, _reg_body()).status_code, 200)


# ── 3. a DIFFERENT project starts clean ──────────────────────────────────

class ADifferentProjectStartsCleanTest(unittest.TestCase):

    def test_projA_pairing_is_invisible_on_projB(self):
        """The bleed, pinned: Carpenter/Acme on projA must not answer for
        projB, where this worker is a painter for a different sub."""
        db = _mk_db(
            project_id="projB", roster=_ROSTER_B, worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _register(
            db, _reg_body("projB", trade="Painter", company="Brush LLC"),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertEqual(row["trade"], "Painter")
        self.assertEqual(row["company"], "Brush LLC")

    def test_the_two_pairings_coexist_independently(self):
        db = _mk_db(
            project_id="projB", roster=_ROSTER_B, worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        _register(db, _reg_body("projB", trade="Painter", company="Brush LLC"))
        self.assertEqual(
            db.pairs.pair_for("w1", "projA")["trade"], "Carpenter",
        )
        self.assertEqual(db.pairs.pair_for("w1", "projB")["trade"], "Painter")

    def test_he_is_asked_again_on_the_new_project(self):
        """No pairing on projB, so a blank submission gets the same 400 that
        makes the check-in page re-prompt — his projA answer does not stand
        in for one here."""
        db = _mk_db(
            project_id="projB", roster=_ROSTER_B, worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        self.assertEqual(_register(db, _reg_body("projB")).status_code, 400)

    def test_projA_trade_is_not_accepted_on_projB(self):
        """And the old answer is not even a valid pick here — projB's roster
        does not carry it."""
        db = _mk_db(
            project_id="projB", roster=_ROSTER_B, worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _register(
            db, _reg_body("projB", trade="Carpenter", company="Acme Co"),
        )
        self.assertEqual(resp.status_code, 400, resp.text)


# ── 4. nothing writes trade/company to the global workers doc ────────────

class TheGlobalWorkerDocIsNeverWrittenTest(unittest.TestCase):

    def _assert_clean(self, db):
        for doc in db.workers.inserted:
            self.assertNotIn("trade", doc, "worker INSERT carried a trade")
            self.assertNotIn("company", doc, "worker INSERT carried a company")
        self.assertFalse(
            db.workers.any_set("trade"), "worker UPDATE set a trade",
        )
        self.assertFalse(
            db.workers.any_set("company"), "worker UPDATE set a company",
        )

    def test_register_new_worker(self):
        db = _mk_db(worker=None)
        resp = _register(db, _reg_body(trade="Carpenter", company="Acme Co"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(db.workers.inserted, "no worker was created")
        self._assert_clean(db)

    def test_register_returning_worker(self):
        db = _mk_db(worker=dict(_WORKER, company="Old Co", trade="Roofer"))
        resp = _register(db, _reg_body(trade="Carpenter", company="Acme Co"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self._assert_clean(db)

    def test_register_still_updates_the_other_worker_fields(self):
        """Fix 5 guard: the worker update_one and the in-memory refresh after
        it must survive — only trade/company came out of it."""
        db = _mk_db(worker=dict(_WORKER, name="Old Name"))
        resp = _register(db, _reg_body(
            trade="Carpenter", company="Acme Co", osha_number="OSHA-9",
        ))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.workers.last_set("name"), "Jane Worker")
        self.assertEqual(db.workers.last_set("osha_number"), "OSHA-9")
        # ...and the refreshed name reached the check-in row.
        self.assertEqual(db.checkins.inserted[-1]["worker_name"], "Jane Worker")

    def test_submit_new_worker(self):
        db = _mk_db(worker=None)
        resp = _submit(db, _sub_body(trade="Carpenter", company="Acme Co"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(db.workers.inserted, "no worker was created")
        self._assert_clean(db)

    def test_submit_returning_worker(self):
        db = _mk_db(worker=dict(_WORKER, company="Old Co", trade="Roofer"))
        resp = _submit(db, _sub_body(trade="Carpenter", company="Acme Co"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self._assert_clean(db)

    def test_submit_still_updates_the_name(self):
        db = _mk_db(worker=dict(_WORKER, name="Old Name"))
        resp = _submit(db, _sub_body(trade="Carpenter", company="Acme Co"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.workers.last_set("name"), "Jane Worker")

    def test_flagged_checkin_writes_nothing_either(self):
        """The UNASSIGNED sentinel must not reach the worker doc either."""
        db = _mk_db(roster=[], worker=dict(_WORKER))
        _register(db, _reg_body())
        self._assert_clean(db)


# ── 5. the admin / NFC paths read the pairing, never the worker doc ──────

def _post_checkins(db, project_id="projA"):
    """POST /api/checkins — the authenticated admin-panel path."""
    user = {
        "_id": "u1", "id": "u1", "role": "admin", "company_id": "co_a",
        "full_name": "Ada Admin", "assigned_projects": [],
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "validate_worker_certifications",
                             lambda *a, **k: _NO_CERT_GATE):
            return TestClient(server.app).post(
                "/api/checkins",
                json={"worker_id": "w1", "project_id": project_id},
            )
    finally:
        server.app.dependency_overrides.clear()


def _post_checkin(db, project_id="projA"):
    """POST /api/checkin — the public NFC/manual path."""
    with patch.object(server, "db", db), \
            patch.object(server, "validate_worker_certifications",
                         lambda *a, **k: _NO_CERT_GATE):
        return TestClient(server.app).post(
            "/api/checkin",
            json={"worker_id": "w1", "project_id": project_id},
        )


class AdminAndNfcPathsReadThePairingTest(unittest.TestCase):

    def test_post_checkins_uses_this_projects_pairing(self):
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _post_checkins(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertEqual(row["worker_trade"], "Carpenter")
        self.assertEqual(row["worker_company"], "Acme Co")

    def test_post_checkins_returns_nothing_without_a_pairing(self):
        """The worker doc carries a stale global trade — it must not be used."""
        db = _mk_db(worker=dict(_WORKER, trade="Roofer", company="Old Co"))
        resp = _post_checkins(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIsNone(row["worker_trade"])
        self.assertIsNone(row["worker_company"])

    def test_post_checkins_ignores_another_projects_pairing(self):
        db = _mk_db(
            project_id="projB", roster=_ROSTER_B, worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _post_checkins(db, "projB")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(db.checkins.inserted[-1]["worker_trade"])

    def test_post_checkin_uses_this_projects_pairing(self):
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _post_checkin(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertEqual(row["worker_trade"], "Carpenter")
        self.assertEqual(row["worker_company"], "Acme Co")

    def test_post_checkin_returns_nothing_without_a_pairing(self):
        db = _mk_db(worker=dict(_WORKER, trade="Roofer", company="Old Co"))
        resp = _post_checkin(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.checkins.inserted[-1]
        self.assertIsNone(row["worker_trade"])
        self.assertIsNone(row["worker_company"])

    def test_post_checkin_ignores_another_projects_pairing(self):
        db = _mk_db(
            project_id="projB", roster=_ROSTER_B, worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _post_checkin(db, "projB")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(db.checkins.inserted[-1]["worker_trade"])


# ── 6. assign-trade writes the pairing, not the worker doc ───────────────

def _assign_db(*, worker, pairs=None):
    db = _FakeDb()
    db.checkins.set_find_one({
        "_id": "chk1", "project_id": "projA", "worker_id": "w1",
        "worker_name": "Jane Worker", "needs_trade_assignment": True,
        "check_in_time": datetime(2026, 8, 1, tzinfo=timezone.utc),
    })
    db.projects.set_find_one({
        "_id": "projA", "name": "Test Tower", "company_id": "co_a",
        "trade_assignments": _ROSTER_A,
    })
    db.workers.set_find_one(worker)
    for p in (pairs or []):
        db.pairs.docs.append(dict(p))
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


class AssignTradeWritesThePairingTest(unittest.TestCase):

    def test_it_stores_the_pairing_for_the_checkins_project(self):
        db = _assign_db(worker=dict(_WORKER))
        resp = _assign(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = db.pairs.pair_for("w1", "projA")
        self.assertIsNotNone(row, "assign-trade stored no pairing")
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["company"], "Acme Co")

    def test_it_writes_nothing_to_the_global_worker_doc(self):
        db = _assign_db(worker=dict(_WORKER))
        _assign(db)
        self.assertFalse(db.workers.any_set("trade"))
        self.assertFalse(db.workers.any_set("company"))

    def test_the_checkin_row_update_is_untouched(self):
        db = _assign_db(worker=dict(_WORKER))
        _assign(db)
        self.assertEqual(db.checkins.last_set("trade"), "Carpenter")
        self.assertEqual(db.checkins.last_set("company"), "Acme Co")
        self.assertEqual(db.checkins.last_set("worker_trade"), "Carpenter")
        self.assertEqual(db.checkins.last_set("worker_company"), "Acme Co")
        self.assertIs(db.checkins.last_set("needs_trade_assignment"), False)
        self.assertEqual(db.checkins.last_set("trade_assigned_by"), "u1")

    def test_the_next_checkin_here_is_no_longer_flagged(self):
        """The loop the CP is closing: assign, then the worker taps again on
        the same project and sails through."""
        assign = _assign_db(worker=dict(_WORKER))
        _assign(assign)
        stored = assign.pairs.pair_for("w1", "projA")

        gate = _mk_db(roster=[], worker=dict(_WORKER), pairs=[stored])
        resp = _register(gate, _reg_body())
        self.assertEqual(resp.status_code, 200, resp.text)
        row = gate.checkins.inserted[-1]
        self.assertIs(row["needs_trade_assignment"], False)
        self.assertEqual(row["trade"], "Carpenter")


# ── 7. lookup-worker answers from the project's pairing only ─────────────

class LookupWorkerTest(unittest.TestCase):

    def test_it_returns_this_projects_pairing(self):
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _lookup(db, {"phone": "5551234567", "project_id": "projA"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["found"])
        self.assertEqual(body["trade"], "Carpenter")
        self.assertEqual(body["company"], "Acme Co")

    def test_it_returns_nothing_when_this_project_has_no_pairing(self):
        db = _mk_db(worker=dict(_WORKER))
        body = _lookup(
            db, {"phone": "5551234567", "project_id": "projA"},
        ).json()
        self.assertTrue(body["found"])
        self.assertIsNone(body["trade"])
        self.assertIsNone(body["company"])

    def test_it_never_returns_another_projects_pairing(self):
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        body = _lookup(
            db, {"phone": "5551234567", "project_id": "projB"},
        ).json()
        self.assertIsNone(body["trade"])
        self.assertIsNone(body["company"])

    def test_it_never_falls_back_to_the_global_worker_doc(self):
        """The worker doc still carries a legacy trade from before this rule
        — pre-existing rows are not deleted. It must never be returned."""
        db = _mk_db(worker=dict(_WORKER, trade="Roofer", company="Old Co"))
        body = _lookup(
            db, {"phone": "5551234567", "project_id": "projA"},
        ).json()
        self.assertIsNone(body["trade"])
        self.assertIsNone(body["company"])

    def test_a_request_with_no_project_gets_no_trade(self):
        """checkin.html sends only { phone } today. With no project named
        there is no pairing to read, so nothing is returned — the page
        re-prompts instead of pre-filling another job's answer."""
        db = _mk_db(
            worker=dict(_WORKER, trade="Roofer"),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        body = _lookup(db, {"phone": "5551234567"}).json()
        self.assertIsNone(body["trade"])
        self.assertIsNone(body["company"])

    def test_the_pii_fields_are_deliberately_unchanged(self):
        """Only the trade source moved. name / osha_number / orientations
        still come back exactly as before — the PII question on this
        endpoint is a separate, pending decision."""
        db = _mk_db(worker=dict(
            _WORKER, osha_number="OSHA-9",
            safety_orientations=[{"project_id": "projA"}],
        ))
        body = _lookup(
            db, {"phone": "5551234567", "project_id": "projA"},
        ).json()
        self.assertEqual(body["name"], "Jane Worker")
        self.assertEqual(body["osha_number"], "OSHA-9")


# ── 8. the store helpers themselves ──────────────────────────────────────

class StoreHelperTest(unittest.IsolatedAsyncioTestCase):

    async def test_the_unassigned_sentinel_is_refused(self):
        db = _FakeDb()
        with patch.object(server, "db", db):
            await server._store_worker_project_trade(
                "w1", "projA", "UNASSIGNED", "UNASSIGNED",
            )
        self.assertIsNone(db.pairs.pair_for("w1", "projA"))

    async def test_an_empty_trade_is_refused(self):
        db = _FakeDb()
        with patch.object(server, "db", db):
            await server._store_worker_project_trade("w1", "projA", "", "Acme")
        self.assertIsNone(db.pairs.pair_for("w1", "projA"))

    async def test_a_second_store_updates_in_place(self):
        """The unique (worker_id, project_id) index means one row per pair —
        a correction overwrites, it does not accumulate."""
        db = _FakeDb()
        with patch.object(server, "db", db):
            await server._store_worker_project_trade(
                "w1", "projA", "Carpenter", "Acme Co",
            )
            await server._store_worker_project_trade(
                "w1", "projA", "Painter", "Brush LLC",
            )
        self.assertEqual(len(db.pairs.docs), 1)
        self.assertEqual(db.pairs.docs[0]["trade"], "Painter")

    async def test_get_returns_none_for_a_missing_project_id(self):
        db = _FakeDb()
        db.pairs.docs.append(_pair("w1", "projA", "Carpenter", "Acme Co"))
        with patch.object(server, "db", db):
            self.assertIsNone(
                await server._get_worker_project_trade("w1", None),
            )
            self.assertIsNone(
                await server._get_worker_project_trade(None, "projA"),
            )

    async def test_a_write_failure_never_propagates(self):
        """A bookkeeping write must not be able to fail a check-in."""
        class _Boom:
            async def update_one(self, *a, **k):
                raise RuntimeError("mongo down")

        db = _FakeDb()
        db._c[server.WORKER_PROJECT_TRADES_COLLECTION] = _Boom()
        with patch.object(server, "db", db):
            await server._store_worker_project_trade(
                "w1", "projA", "Carpenter", "Acme Co",
            )  # must not raise


if __name__ == "__main__":
    unittest.main()
