"""A trade from another project never surfaces as this project's.

Five check-in read paths carried the same fallback:

    s["worker_trade"] = s.get("worker_trade") or worker.get("trade")

`workers.trade` is ONE SLOT for a man who holds different trades on different
jobs, filled by whichever project got to him first. register_and_checkin
deliberately stopped writing it -- "a worker-level copy is what bled across
jobs" -- but five readers kept it alive, and #246 only closed the sixth (the
daily-jobsite roster). The reasoning there governs all of them:

    A trade from another project is worse than no trade. It is silently wrong
    instead of visibly absent.

WHICH ONES RESOLVE THE PAIRING, AND WHY IT IS NOT ALL OF THEM:

    /flagged, /checkins/project/{id}, /active, /today   PROJECT-scoped. The
        pairing is well defined, so a row that froze no trade gets this
        project's answer. `/flagged` matters most: it is the trade the CP reads
        on the picker before tapping Change.

    GET /checkins                                       COMPANY-scoped. One
        response spans every project the company runs, so there is no single
        project_id to key a pairing on. The fallback still goes; resolving
        needs a per-row (worker_id, project_id) lookup and is its own change.

Run:  python -m pytest backend/tests/test_no_cross_project_trade_bleed.py -q
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

PROJECT = {"_id": "proj1", "name": "588 Thomas", "company_id": "co_a"}
USER = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "co_a",
        "assigned_projects": [], "full_name": "Ada Admin"}
TS = datetime(2026, 8, 27, 7, 30, tzinfo=timezone.utc)
SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)

    def sort(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _Coll:
    def __init__(self, docs=None, find_one=None):
        self.docs = list(docs or [])
        self._find_one = find_one
        self.queries = []

    def find(self, query=None, *a, **k):
        self.queries.append(query)
        return _Cursor(self.docs)

    async def find_one(self, query=None, *a, **k):
        if callable(self._find_one):
            return self._find_one(query)
        return self._find_one

    async def count_documents(self, *a, **k):
        return len(self.docs)

    def aggregate(self, *a, **k):
        return _Cursor([])


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())

    def __getitem__(self, name):
        return self._c.setdefault(name, _Coll())


BLED = "Demolition (another job)"


def _checkin(**over):
    row = {"_id": "chk_1", "worker_id": "w1", "worker_name": "Wilmer Carrillo",
           "worker_company": "Arkon Builders", "worker_trade": "",
           "project_id": "proj1", "check_in_time": TS, "is_deleted": False,
           "status": "checked_in", "sst_status": "valid",
           "needs_trade_assignment": True, "review_decision": None,
           "cert_warnings": []}
    row.update(over)
    return row


def _worker(_q=None):
    # The bleed: a trade on the worker document, from a different project.
    return {"_id": "w1", "name": "Wilmer Carrillo", "trade": BLED,
            "company": "Arkon Builders", "osha_number": "OSHA-1",
            "certifications": [], "signature": None, "osha_card_image": None}


def _pairing(**over):
    row = {"worker_id": "w1", "project_id": "proj1", "trade": "Framers",
           "company": "Arkon Builders"}
    row.update(over)
    return row


def _db(checkins=None, pairings=None):
    db = _Db(
        projects=_Coll(find_one=lambda q: PROJECT),
        checkins=_Coll(checkins if checkins is not None else [_checkin()]),
        workers=_Coll([_worker()], find_one=_worker),
        compliance_alerts=_Coll([]),
        sign_ins=_Coll([]),
        worker_enrollments=_Coll([]),
        daily_signatures=_Coll([]),
        subcontractors=_Coll([]),
    )
    db._c[server.WORKER_PROJECT_TRADES_COLLECTION] = _Coll(pairings or [])
    return db


def _get(path, db):
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    client = TestClient(server.app)
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v):
            return client.get(path)
    finally:
        server.app.dependency_overrides.clear()


def _rows(resp):
    body = resp.json()
    if isinstance(body, dict):
        for key in ("results", "checkins", "items", "workers"):
            if isinstance(body.get(key), list):
                return body[key]
        return []
    return body


PROJECT_SCOPED = [
    "/api/checkins/project/proj1/flagged",
    "/api/checkins/project/proj1",
    "/api/checkins/project/proj1/active",
    "/api/checkins/project/proj1/today",
]


class TheBleedIsGoneEverywhere(unittest.TestCase):
    def test_no_endpoint_falls_back_to_the_worker_document(self):
        for path in PROJECT_SCOPED + ["/api/checkins"]:
            with self.subTest(path=path):
                resp = _get(path, _db(pairings=[]))
                self.assertEqual(resp.status_code, 200, resp.text)
                rows = _rows(resp)
                self.assertTrue(rows, f"{path} returned no rows to check")
                for r in rows:
                    self.assertNotEqual(
                        r.get("worker_trade"), BLED,
                        f"{path} leaked another project's trade",
                    )

    def test_the_fallback_expression_is_gone_from_the_source(self):
        self.assertNotIn(
            's["worker_trade"] = s.get("worker_trade") or worker.get("trade")',
            SRC,
            "every site must be converted, not just the ones with a test",
        )


class ProjectScopedEndpointsResolveThePairing(unittest.TestCase):
    def test_an_unrecorded_trade_is_answered_from_the_pairing(self):
        for path in PROJECT_SCOPED:
            with self.subTest(path=path):
                rows = _rows(_get(path, _db(pairings=[_pairing()])))
                self.assertEqual(rows[0].get("worker_trade"), "Framers")

    def test_the_sentinel_is_resolved_too(self):
        for path in PROJECT_SCOPED:
            with self.subTest(path=path):
                db = _db(checkins=[_checkin(worker_trade="UNASSIGNED")],
                         pairings=[_pairing()])
                rows = _rows(_get(path, db))
                self.assertEqual(rows[0].get("worker_trade"), "Framers")

    def test_a_frozen_trade_still_wins(self):
        # Same precedence as #246: the check-in is an observation of the day and
        # a later pairing edit must not rewrite it.
        for path in PROJECT_SCOPED:
            with self.subTest(path=path):
                db = _db(checkins=[_checkin(worker_trade="Carpenter")],
                         pairings=[_pairing(trade="Framers")])
                rows = _rows(_get(path, db))
                self.assertEqual(rows[0].get("worker_trade"), "Carpenter")

    def test_no_pairing_leaves_it_empty(self):
        for path in PROJECT_SCOPED:
            with self.subTest(path=path):
                rows = _rows(_get(path, _db(pairings=[])))
                self.assertEqual(rows[0].get("worker_trade"), "")


class TheFlaggedPickerReadsTheRightTrade(unittest.TestCase):
    """The one the CP looks at before tapping Change."""

    def test_it_resolves_even_when_the_row_already_has_a_name(self):
        # The three list endpoints nested the trade inside `if not worker_name`.
        # A row that already carries a name -- which every gate check-in does --
        # would never have had its trade resolved at all.
        db = _db(checkins=[_checkin(worker_name="Wilmer Carrillo",
                                    worker_trade="")],
                 pairings=[_pairing()])
        for path in PROJECT_SCOPED:
            with self.subTest(path=path):
                rows = _rows(_get(path, db))
                self.assertEqual(rows[0].get("worker_trade"), "Framers")

    def test_flagged_still_carries_its_other_fields(self):
        resp = _get("/api/checkins/project/proj1/flagged", _db(pairings=[_pairing()]))
        row = _rows(resp)[0]
        self.assertEqual(row["worker_name"], "Wilmer Carrillo")
        self.assertEqual(row["worker_company"], "Arkon Builders")
        self.assertIn("flag_reasons", row)


class TheCompanyScopedListOnlyRemoves(unittest.TestCase):
    def test_get_checkins_does_not_resolve_and_does_not_leak(self):
        # No project to key a pairing on, so a pairing that exists for proj1 is
        # deliberately NOT applied here -- and the bled value is still gone.
        rows = _rows(_get("/api/checkins", _db(pairings=[_pairing()])))
        self.assertTrue(rows)
        self.assertNotEqual(rows[0].get("worker_trade"), BLED)
        self.assertNotEqual(rows[0].get("worker_trade"), "Framers")


class TheBatchHelper(unittest.TestCase):
    def test_one_query_per_request_not_one_per_row(self):
        rows = [_checkin(_id=f"c{i}", worker_id=f"w{i}") for i in range(12)]
        for path in PROJECT_SCOPED:
            with self.subTest(path=path):
                db = _db(checkins=rows, pairings=[])
                _get(path, db)
                pair = db._c[server.WORKER_PROJECT_TRADES_COLLECTION]
                self.assertEqual(len(pair.queries), 1)

    def test_the_query_is_scoped_to_this_project(self):
        db = _db(pairings=[_pairing()])
        _get("/api/checkins/project/proj1/flagged", db)
        q = db._c[server.WORKER_PROJECT_TRADES_COLLECTION].queries[0]
        self.assertEqual(q["project_id"], "proj1")
        self.assertEqual(q["worker_id"], {"$in": ["w1"]})

    def test_a_blank_pairing_trade_is_absent_not_an_empty_answer(self):
        rows = _rows(_get("/api/checkins/project/proj1/flagged",
                          _db(pairings=[_pairing(trade="   ")])))
        self.assertEqual(rows[0].get("worker_trade"), "")

    def test_a_failed_lookup_returns_empty_and_never_raises(self):
        class _Boom(_Coll):
            def find(self, query=None, *a, **k):
                raise RuntimeError("simulated pairing failure")

        db = _db(checkins=[_checkin(worker_trade="Carpenter")], pairings=[])
        db._c[server.WORKER_PROJECT_TRADES_COLLECTION] = _Boom([])
        resp = _get("/api/checkins/project/proj1/flagged", db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(_rows(resp)[0].get("worker_trade"), "Carpenter")


if __name__ == "__main__":
    unittest.main()
