"""POST /checkin/lookup-worker answers PER PROJECT, and only per project.

Two separate rules meet on this one endpoint, and both of them are things a
worker standing at a gate feels immediately:

  1. Trade + company come from the {worker_id, project_id} pairing in
     `worker_project_trades`. No project_id in the request means no pairing
     can be found, which means every returning worker gets re-prompted for
     trade and company. That is the regression this file pins: checkin.html
     posted only { phone } and so could never hit the pairing.

  2. Site safety orientation is per project under §3301.11. The endpoint
     used to ship the worker's WHOLE `safety_orientations` list to the gate
     page and let the page decide. It now returns one server-computed,
     project-scoped boolean, `oriented_on_this_project`. A "has any
     orientation" boolean would have marked a worker oriented at project A
     as oriented at project B and skipped his site orientation there — a
     false compliance record, which is worse than a repeated orientation.

Also pinned here, because both are load-bearing at the gate:
  • `safety_orientations` is GONE from the response (the page no longer
    needs the history, so it no longer receives it);
  • `osha_number` is still the REAL value, not a boolean — checkin.html
    forwards it straight back into the register-and-checkin payload for
    returning workers, so a boolean there would corrupt the check-in;
  • a genuine returning worker NEVER gets found: false, whatever else is
    missing from the request. found: false sends him through full
    re-registration including re-photographing his OSHA card.
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


# ── fake mongo (only what lookup_worker actually touches) ────────────────

class _Result:
    def __init__(self):
        self.inserted_id = "new_id"
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
    """find_one returns a fixed value regardless of the query."""

    def __init__(self, value=None):
        self._value = value

    async def find_one(self, query=None, *a, **k):
        return self._value

    async def insert_one(self, doc, *a, **k):
        return _Result()

    async def update_one(self, q, u, *a, **k):
        return _Result()


class _StoreCollection:
    """A real (tiny) document store — find_one actually filters. The pairing
    collection MUST use this: the entire rule is that a query naming project
    B does not find project A's row."""

    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _matches(d, query or {}):
                return dict(d)
        return None

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


class _FakeDb:
    def __init__(self):
        self._c = {
            server.WORKER_PROJECT_TRADES_COLLECTION: _StoreCollection(),
        }

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


_PHONE = "5551234567"
_WORKER = {"_id": "w1", "name": "Jane Worker", "phone": _PHONE}


def _pair(worker_id, project_id, trade, company):
    return {
        "worker_id": worker_id, "project_id": project_id,
        "trade": trade, "company": company,
        "updated_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }


def _mk_db(worker=None, pairs=None):
    db = _FakeDb()
    db._c["workers"] = _CannedCollection(worker)
    for p in (pairs or []):
        db.pairs.docs.append(dict(p))
    return db


def _lookup(db, body):
    with patch.object(server, "db", db):
        return TestClient(server.app).post(
            "/api/checkin/lookup-worker", json=body,
        )


# ── 1. the pairing needs the project_id the page now sends ───────────────

class PairingNeedsProjectIdTest(unittest.TestCase):

    def test_the_pairing_comes_back_when_project_id_is_supplied(self):
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        resp = _lookup(db, {"phone": _PHONE, "project_id": "projA"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["found"])
        self.assertEqual(body["trade"], "Carpenter")
        self.assertEqual(body["company"], "Acme Co")

    def test_the_same_pairing_is_unreachable_without_project_id(self):
        """The live regression, stated as a test: identical worker,
        identical stored pairing, request missing project_id — and the
        worker comes back with no trade, which the gate page reads as
        "not on this project's roster" and re-prompts him for."""
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        body = _lookup(db, {"phone": _PHONE}).json()
        self.assertTrue(body["found"])
        self.assertIsNone(body["trade"])
        self.assertIsNone(body["company"])

    def test_another_projects_pairing_is_never_borrowed(self):
        db = _mk_db(
            worker=dict(_WORKER),
            pairs=[_pair("w1", "projA", "Carpenter", "Acme Co")],
        )
        body = _lookup(db, {"phone": _PHONE, "project_id": "projB"}).json()
        self.assertTrue(body["found"])
        self.assertIsNone(body["trade"])
        self.assertIsNone(body["company"])


# ── 2. orientation is a project-scoped boolean ───────────────────────────

class OrientedOnThisProjectTest(unittest.TestCase):

    def _db(self):
        return _mk_db(worker=dict(
            _WORKER,
            safety_orientations=[
                {"project_id": "projA", "completed_at": "2026-07-01"},
            ],
        ))

    def test_it_is_true_for_the_project_he_was_oriented_on(self):
        body = _lookup(
            self._db(), {"phone": _PHONE, "project_id": "projA"},
        ).json()
        self.assertIs(body["oriented_on_this_project"], True)

    def test_it_is_false_for_a_project_he_was_not_oriented_on(self):
        """The §3301.11 case. A naive "has any orientation" boolean would
        return True here and the gate would skip this site's orientation,
        writing a compliance record for training that never happened."""
        body = _lookup(
            self._db(), {"phone": _PHONE, "project_id": "projB"},
        ).json()
        self.assertIs(body["oriented_on_this_project"], False)

    def test_it_is_false_when_the_request_names_no_project(self):
        """No project named means no project to be oriented ON. Fail
        closed: the cost is a repeated orientation, not a missing one."""
        body = _lookup(self._db(), {"phone": _PHONE}).json()
        self.assertIs(body["oriented_on_this_project"], False)

    def test_it_is_false_when_the_worker_has_no_orientations_at_all(self):
        db = _mk_db(worker=dict(_WORKER))
        body = _lookup(db, {"phone": _PHONE, "project_id": "projA"}).json()
        self.assertIs(body["oriented_on_this_project"], False)


# ── 3. the trimmed response shape ────────────────────────────────────────

class ResponseShapeTest(unittest.TestCase):

    def test_the_orientation_list_is_no_longer_shipped_to_the_gate(self):
        db = _mk_db(worker=dict(
            _WORKER, safety_orientations=[{"project_id": "projA"}],
        ))
        body = _lookup(db, {"phone": _PHONE, "project_id": "projA"}).json()
        self.assertNotIn("safety_orientations", body)

    def test_osha_number_is_still_the_real_value_not_a_boolean(self):
        """checkin.html forwards this straight into the
        register-and-checkin payload for a returning worker
        (checkin.html:1142). A boolean here corrupts the check-in."""
        db = _mk_db(worker=dict(_WORKER, osha_number="OSHA-9"))
        body = _lookup(db, {"phone": _PHONE, "project_id": "projA"}).json()
        self.assertEqual(body["osha_number"], "OSHA-9")

    def test_a_returning_worker_is_never_answered_found_false(self):
        """found: false sends him through FULL re-registration, OSHA card
        photo included. A missing project_id, a missing pairing and a
        missing orientation are all normal states — none of them may
        degrade into "we do not know this person"."""
        db = _mk_db(worker=dict(_WORKER))
        for req in (
            {"phone": _PHONE},
            {"phone": _PHONE, "project_id": "projA"},
            {"phone": _PHONE, "project_id": "unknown-project"},
        ):
            with self.subTest(req=req):
                body = _lookup(db, req).json()
                self.assertTrue(body["found"])
                self.assertEqual(body["worker_id"], "w1")
                self.assertEqual(body["name"], "Jane Worker")

    def test_an_unknown_phone_still_gets_found_false(self):
        db = _mk_db(worker=None)
        body = _lookup(db, {"phone": "5559999999", "project_id": "projA"}).json()
        self.assertEqual(body, {"found": False})


if __name__ == "__main__":
    unittest.main()
