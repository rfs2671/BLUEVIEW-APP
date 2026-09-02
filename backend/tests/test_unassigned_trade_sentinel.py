"""The "UNASSIGNED" sentinel is an ABSENT trade, and the submit gate must read it as one.

THE DEFECT, IN ONE LINE: "UNASSIGNED" is a truthy string, and the two
safeguards that ask "does this worker have a trade?" both ask by truthiness.

  THE WRITE. register_and_checkin coerces a blank trade to the literal
  "UNASSIGNED" on its no_roster and not_listed branches (`trade = trade or
  "UNASSIGNED"`). A few dozen lines later the SAME `trade` local is stamped onto
  the subcontractor_orientation draft as `"worker_trade": trade or ""`. That
  `or ""` looks like it handles the empty case, and it does — but by then the
  value is no longer empty, it is the sentinel. The orientation record therefore
  carries "UNASSIGNED" as the man's trade.

  THE READS. `_submit_missing_trade_detail` asks
  `if str(d.get("worker_trade") or "").strip(): return None` — the sentinel is a
  non-empty string, so the gate that exists to stop a trade-less orientation
  being FILED waves it straight through. The client's repair affordance
  (subcontractor_orientation.jsx) asks the same truthiness question, so the row
  that most needs fixing is the one row never offered the fix. The two failures
  compound: the CP is never told, and the server never objects.

  THE FIX IS AT THE READS, NOT THE WRITE. `_recorded_trade` already exists and
  already says, in its own docstring, "Anything that reads a frozen trade to
  decide whether one exists has to ask through here". The submit gate did not.
  The stored value is deliberately left alone — rows already carry the sentinel,
  and the check-in row's "UNASSIGNED" is load-bearing elsewhere (it is what
  needs_trade_assignment reporting and _display_sub_company's "Pending
  assignment" read). No migration; the reader learns the sentinel instead.

THE TURNSTILE IS UNTOUCHED. Creating the draft still succeeds with no trade and
with the sentinel. Only SUBMIT is blocked. A worker is never held at the gate
for an admin's unfinished roster.
"""

from __future__ import annotations

import os
import sys
import unittest
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

ORIENT = "subcontractor_orientation"
SENTINEL = "UNASSIGNED"

PROJECT = {"_id": "proj1", "name": "857 Prescott Pl", "company_id": "co_a"}
USER = {
    "_id": "u1", "id": "u1", "role": "admin", "company_id": "co_a",
    "assigned_projects": ["proj1"], "full_name": "Ada Admin",
}
SIG = {"image": "data:image/png;base64,AAA", "signed_at": "2026-03-04T12:00:00Z",
       "affirmed": True, "affirmedAt": "2026-03-04T12:00:00Z"}


# ── Minimal async Mongo fakes (same shape as the neighbouring gate tests) ────

class _Result:
    def __init__(self, inserted_id="x"):
        self.inserted_id = inserted_id
        self.matched_count = 1
        self.modified_count = 1
        self.upserted_id = None


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
        rec = dict(doc)
        rec["_id"] = doc.get("_id") or f"{self.name}_{self._seq}"
        self.inserted.append(rec)
        return _Result(rec["_id"])

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


def _valid_osha():
    return {
        "name": "Jane Worker", "sst_number": "SST12345678", "card_type": "SST",
        "card_class": "WORKER", "issued": None, "expiration": "01/01/2030",
    }


def _gate_db(*, roster):
    db = _FakeDb()
    db.nfc_tags.set_find_one({
        "tag_id": "tag1", "project_id": "proj1", "status": "active",
    })
    db.projects.set_find_one({
        "_id": "proj1", "name": "Test Tower", "company_id": "co_a",
        "admin_id": "admin_a",
        "trade_assignments": [dict(r) for r in roster],
    })
    db.workers.set_find_one(None)
    db.logbooks.set_find_one(None)
    db.checkins.set_find_one(None)
    return db


def _gate_body(**over):
    body = {
        "project_id": "proj1", "tag_id": "tag1",
        "name": "Jane Worker", "phone": "5551234567",
        "trade": "", "company": "",
        "osha_number": "SST12345678", "osha_data": _valid_osha(),
        "signature": "data:image/png;base64,SIG",
        "safety_orientation": {"hard_hats": True},
    }
    body.update(over)
    return body


def _dispatch_patch():
    return patch.object(
        server._notifications_inbox, "dispatch_notification",
        new_callable=AsyncMock,
    )


def _register(db, body=None):
    with patch.object(server, "db", db), _dispatch_patch():
        return TestClient(server.app).post(
            "/api/checkin/register-and-checkin", json=dict(body or _gate_body()),
        )


# ── 1. THE WRITE SITE ────────────────────────────────────────────────────────

class TheWriteSite(unittest.TestCase):
    """Where the sentinel enters the orientation record.

    This is the SETUP, not the defect: it documents that the value the two
    read sites are handed is the literal string, so nobody later reads the
    `or ""` on the insert line and concludes the record holds "".
    """

    def _orientation_row(self, db):
        rows = [d for d in db.logbooks.inserted
                if d.get("log_type") == ORIENT]
        self.assertEqual(len(rows), 1,
                         "the gate writes exactly one orientation draft")
        return rows[0]

    def test_no_roster_stamps_the_sentinel_onto_the_orientation(self):
        db = _gate_db(roster=[])
        r = _register(db)
        self.assertEqual(r.status_code, 200, r.text)
        row = self._orientation_row(db)
        self.assertEqual(row["data"]["worker_trade"], SENTINEL,
                         "`trade or \"\"` writes the ALREADY-COERCED local")
        self.assertEqual(row["status"], "draft")

    def test_not_listed_stamps_it_too(self):
        db = _gate_db(roster=[{"trade": "Concrete", "company": "AAZ"}])
        r = _register(db, _gate_body(trade_not_listed=True))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            self._orientation_row(db)["data"]["worker_trade"], SENTINEL)

    def test_the_worker_is_still_admitted(self):
        """The turnstile stays fail-open. This is the property the fix must not
        touch: the record is created, sentinel and all."""
        db = _gate_db(roster=[])
        r = _register(db)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotEqual(r.json().get("blocked"), True)


# ── 2. THE SUBMIT GATE (read site A) ─────────────────────────────────────────

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


class TheSubmitGateReadsTheSentinelAsAbsent(unittest.TestCase):

    def test_the_sentinel_refuses_the_submit(self):
        d = server._submit_missing_trade_detail(ORIENT, _data(worker_trade=SENTINEL))
        self.assertIsNotNone(
            d, 'a filed orientation reading "UNASSIGNED" names no scope of work')
        self.assertEqual(d["code"], "SUBMIT_MISSING_TRADE")

    def test_the_refusal_still_names_the_worker(self):
        d = server._submit_missing_trade_detail(ORIENT, _data(worker_trade=SENTINEL))
        self.assertEqual(d["worker_name"], "Hector Ramirez")
        self.assertEqual(d["worker_id"], "w1")

    def test_casing_and_padding_do_not_smuggle_it_through(self):
        for v in ("unassigned", "Unassigned", "  UNASSIGNED  ", "\tunassigned\n"):
            with self.subTest(v=v):
                self.assertIsNotNone(
                    server._submit_missing_trade_detail(ORIENT, _data(worker_trade=v)),
                    v)

    def test_it_asks_through_the_one_helper_that_knows_the_sentinel(self):
        """_recorded_trade is the existing shared predicate and its docstring
        already claims this gate as a caller. Behaviourally pinned: the gate's
        verdict must agree with the helper on every input."""
        for v in ("Concrete", "", "   ", SENTINEL, "unassigned", None,
                  "Unassigned Laborer"):
            with self.subTest(v=v):
                refused = server._submit_missing_trade_detail(
                    ORIENT, _data(worker_trade=v)) is not None
                self.assertEqual(refused, not server._recorded_trade(v), v)

    def test_a_real_trade_that_merely_contains_the_word_still_passes(self):
        """Only the EXACT sentinel is an absence. A trade is not disqualified
        for containing the letters."""
        for v in ("Unassigned Laborer", "UNASSIGNED WORKS LLC", "Assigned"):
            with self.subTest(v=v):
                self.assertIsNone(
                    server._submit_missing_trade_detail(ORIENT, _data(worker_trade=v)),
                    v)

    def test_the_existing_rules_are_untouched(self):
        self.assertIsNone(server._submit_missing_trade_detail(ORIENT, _data()))
        self.assertIsNotNone(
            server._submit_missing_trade_detail(ORIENT, _data(worker_trade="")))
        self.assertIsNone(
            server._submit_missing_trade_detail("daily_jobsite",
                                                _data(worker_trade=SENTINEL)))
        for junk in (None, [], "x", 7):
            self.assertIsNone(server._submit_missing_trade_detail(ORIENT, junk), junk)


# ── 3. THE TWO HALVES, JOINED ────────────────────────────────────────────────

class _Coll:
    def __init__(self, docs=None, find_one=None):
        self.docs = list(docs or [])
        self._find_one = find_one
        self.inserted = []
        self.updated = []

    def find(self, q=None, *a, **k):
        return _FakeCursor(self.docs)

    async def find_one(self, q=None, *a, **k):
        return self._find_one(q) if callable(self._find_one) else self._find_one

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return _Result("new_id")

    async def update_one(self, q, u, **k):
        self.updated.append((q, u))
        return _Result("upd")

    async def count_documents(self, *a, **k):
        return 0


class _Db:
    def __init__(self, **c):
        self._c = dict(c)

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._c.setdefault(n, _Coll())


async def _noop(*a, **k):
    return None


def _post(db, body):
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v), \
                patch.object(server, "audit_log", _noop):
            return TestClient(server.app).post("/api/logbooks", json=body)
    finally:
        server.app.dependency_overrides.clear()


def _put(db, logbook_id, body):
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v), \
                patch.object(server, "audit_log", _noop):
            return TestClient(server.app).put(f"/api/logbooks/{logbook_id}",
                                              json=body)
    finally:
        server.app.dependency_overrides.clear()


class TheRecordTheGateActuallyWroteCannotBeFiled(unittest.TestCase):
    """The end-to-end join: take the EXACT data the turnstile wrote in §1 and
    put it back through the endpoint the CP's signature travels on."""

    def _written_orientation_data(self):
        db = _gate_db(roster=[])
        r = _register(db)
        self.assertEqual(r.status_code, 200, r.text)
        row = next(d for d in db.logbooks.inserted if d.get("log_type") == ORIENT)
        return row["data"]

    def test_signing_it_via_PUT_is_refused(self):
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": ORIENT,
            "data": self._written_orientation_data(),
            "cp_signature": None, "is_locked": False,
        }
        db = _Db(projects=_Coll(find_one=lambda q: PROJECT),
                 logbooks=_Coll(find_one=lambda q: stored))
        r = _put(db, "lb1", {"cp_signature": SIG, "cp_name": "Ada",
                             "status": "submitted"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"]["code"], "SUBMIT_MISSING_TRADE")

    def test_a_refused_submit_still_mutates_nothing(self):
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": ORIENT,
            "data": self._written_orientation_data(),
            "cp_signature": None, "is_locked": False,
        }
        db = _Db(projects=_Coll(find_one=lambda q: PROJECT),
                 logbooks=_Coll(find_one=lambda q: stored))
        _put(db, "lb1", {"cp_signature": SIG, "cp_name": "Ada",
                         "status": "submitted"})
        self.assertEqual(db.logbooks.updated, [])

    def test_creating_it_as_submitted_is_refused(self):
        db = _Db(projects=_Coll(find_one=lambda q: PROJECT),
                 logbooks=_Coll(find_one=lambda q: None))
        r = _post(db, {
            "project_id": "proj1", "log_type": ORIENT, "date": "2026-03-04",
            "data": _data(worker_trade=SENTINEL),
            "cp_signature": SIG, "cp_name": "Ada", "status": "submitted",
        })
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"]["code"], "SUBMIT_MISSING_TRADE")
        self.assertEqual(db.logbooks.inserted, [])

    def test_saving_it_as_a_DRAFT_is_still_allowed(self):
        """The fail-open half, restated at the endpoint: the sentinel blocks
        FILING, never DRAFTING."""
        db = _Db(projects=_Coll(find_one=lambda q: PROJECT),
                 logbooks=_Coll(find_one=lambda q: None))
        r = _post(db, {
            "project_id": "proj1", "log_type": ORIENT, "date": "2026-03-04",
            "data": _data(worker_trade=SENTINEL),
            "cp_signature": SIG, "cp_name": "Ada", "status": "draft",
        })
        self.assertNotEqual(r.status_code, 400, r.text)

    def test_assigning_a_real_trade_in_the_same_request_lets_it_through(self):
        """The repair path: the CP assigns the trade and signs. The sentinel
        must not be sticky."""
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": ORIENT,
            "data": _data(worker_trade=SENTINEL),
            "cp_signature": None, "is_locked": False,
        }
        db = _Db(projects=_Coll(find_one=lambda q: PROJECT),
                 logbooks=_Coll(find_one=lambda q: stored))
        r = _put(db, "lb1", {"data": _data(worker_trade="Concrete"),
                             "cp_signature": SIG, "cp_name": "Ada",
                             "status": "submitted"})
        self.assertNotEqual(r.status_code, 400, r.text)


# ── 4. THE REPAIR UI (read site B) ───────────────────────────────────────────

class TheRepairUiOffersTheFixOnASentinelRow(unittest.TestCase):
    """The client half, asserted on source.

    The screen is JSX and cannot be imported here; frontend/src/utils/
    orientationTradeGate.test.cjs is the behavioural companion. What this pins
    is the one thing the server cannot: that the CP-facing "No trade assigned"
    box and the pre-flight guard both route the value through the shared
    sentinel-aware helper rather than asking a bare truthiness question. A
    truthiness test here means the row carrying the sentinel is the ONE row
    never offered the fix.
    """

    SCREEN = (_BACKEND.parent / "frontend" / "app" / "logbooks"
              / "subcontractor_orientation.jsx")

    def setUp(self):
        self.src = self.SCREEN.read_text(encoding="utf-8")

    def test_the_screen_imports_the_shared_predicate(self):
        self.assertIn("cleanTrade", self.src,
                      "the sentinel rule lives in dailyJobsiteModel, not here")
        self.assertRegex(
            self.src,
            r"import \{[^}]*cleanTrade[^}]*\} from '\.\./\.\./src/utils/dailyJobsiteModel'",
        )

    def test_the_no_trade_box_no_longer_asks_by_truthiness(self):
        self.assertNotIn("!String(d.worker_trade || '').trim()", self.src,
                         'a truthy "UNASSIGNED" passes this and hides the fix')
        self.assertIn("!cleanTrade(d.worker_trade)", self.src)

    def test_the_preflight_guard_asks_the_same_way(self):
        self.assertIn(
            "const orientationTrade = (o) => cleanTrade((o?.data || {}).worker_trade)",
            self.src,
            "the pre-flight and the box must not disagree about what a trade is",
        )


if __name__ == "__main__":
    unittest.main()
