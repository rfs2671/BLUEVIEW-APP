"""GET /logbooks/project/{id}/checkins-today — the trade a crew is reported with.

THE DEFECT, from the CP's device. Arkon Builders' pairing was corrected to
Framers / Arkon Builders in `worker_project_trades`, and the Daily Jobsite Log
still showed "No trade assigned" on all three crews. This endpoint returned

    "trade": c.get("worker_trade") or (worker.get("trade") if worker else "")

so it read the FROZEN check-in and then the `workers` document, and never the
pairing. A check-in written that morning could not be changed by a correction
made that afternoon, so a signed §3301.2 record named crews with no trade — and
because the activity chips key on the crew's trade, every crew also fell back
to the unfiltered project-wide catalogue and was offered another trade's work.

THE RULE, and it is a precedence rule, not a lookup:

    FROZEN WINS WHEN IT SAYS ANYTHING.   A check-in is an OBSERVATION of what
        was recorded at the gate. It is either what the worker picked or what a
        CP put there through POST /checkins/{id}/assign-trade, which writes the
        row and the pairing together. Letting today's pairing override it would
        let a pairing edited next week silently rewrite the roster on a log
        already signed — the retroactive mutation the frozen cert snapshot on
        this same row exists to prevent.

    THE PAIRING FILLS A GAP.   A frozen value that records nothing is not
        evidence that the man has no trade; it is evidence nobody had recorded
        one. worker_project_trades is the current truth for THIS project.

    "UNASSIGNED" RECORDS NOTHING.   register_and_checkin stamps the sentinel
        when the project has no roster or the worker picked "my company isn't
        listed". Treating it as an answer is what would keep Arkon reading
        "No trade assigned" even after this change.

Run:  python -m pytest backend/tests/test_checkins_today_resolves_pairing.py -q
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
DAY = "2026-08-27"
TS = datetime(2026, 8, 27, 7, 30, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _Coll:
    def __init__(self, docs=None, find_one=None):
        self.docs = list(docs or [])
        self._find_one = find_one
        self.queries = []          # every find() query, for the batching test

    def find(self, query=None, *a, **k):
        self.queries.append(query)
        return _Cursor(self.docs)

    async def find_one(self, query=None, *a, **k):
        if callable(self._find_one):
            return self._find_one(query)
        return self._find_one


class _RaisingColl(_Coll):
    def find(self, query=None, *a, **k):
        self.queries.append(query)
        raise RuntimeError("simulated pairing read failure")


class _Db:
    """Supports BOTH db.name and db["name"].

    The pairing collection is reached as `db[WORKER_PROJECT_TRADES_COLLECTION]`
    — a subscript, not an attribute. A fake that only implements __getattr__
    raises TypeError there, which the endpoint catches and logs, so the whole
    feature would degrade to "no pairings" and every assertion below would pass
    for the wrong reason.
    """

    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())

    def __getitem__(self, name):
        return self._c.setdefault(name, _Coll())


def _worker_doc(trade=None):
    def _f(_q=None):
        doc = {"_id": "w1", "osha_number": "OSHA-1", "certifications": [],
               "signature": None, "company": None}
        if trade is not None:
            doc["trade"] = trade
        return doc
    return _f


def _legacy_row(**over):
    row = {"_id": "chk_1", "worker_id": "w1", "worker_name": "Wilmer Carrillo",
           "worker_company": "Arkon Builders", "worker_trade": "",
           "check_in_time": TS, "is_deleted": False, "sst_status": "valid",
           "needs_trade_assignment": False, "review_decision": None,
           "cert_warnings": []}
    row.update(over)
    return row


def _pairing(**over):
    row = {"worker_id": "w1", "project_id": "proj1",
           "trade": "Framers", "company": "Arkon Builders"}
    row.update(over)
    return row


def _build(checkins=None, pairings=None, worker_trade=None, raise_pairings=False):
    pair_coll = (_RaisingColl(pairings or []) if raise_pairings
                 else _Coll(pairings or []))
    db = _Db(
        projects=_Coll(find_one=lambda q: PROJECT),
        sign_ins=_Coll([]),
        worker_enrollments=_Coll([]),
        daily_signatures=_Coll([]),
        checkins=_Coll(checkins or []),
        workers=_Coll(find_one=_worker_doc(worker_trade)),
        compliance_alerts=_Coll([]),
    )
    db._c[server.WORKER_PROJECT_TRADES_COLLECTION] = pair_coll
    return db, pair_coll


def _get(db):
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    client = TestClient(server.app)
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v):
            r = client.get(f"/api/logbooks/project/proj1/checkins-today?date={DAY}")
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        server.app.dependency_overrides.clear()


class TheSentinelRecordsNothing(unittest.TestCase):
    def test_blank_and_unassigned_both_read_as_no_trade(self):
        self.assertEqual(server._recorded_trade(""), "")
        self.assertEqual(server._recorded_trade(None), "")
        self.assertEqual(server._recorded_trade("UNASSIGNED"), "")
        self.assertEqual(server._recorded_trade("unassigned"), "",
                         "case must not decide whether a sentinel is a trade")
        self.assertEqual(server._recorded_trade("  UNASSIGNED  "), "")

    def test_a_real_trade_survives_intact(self):
        self.assertEqual(server._recorded_trade("Framers"), "Framers")
        self.assertEqual(server._recorded_trade("  Framers  "), "Framers")


class ThePairingFillsAGap(unittest.TestCase):
    def test_empty_frozen_trade_is_resolved_from_the_pairing(self):
        db, _ = _build(checkins=[_legacy_row(worker_trade="")],
                       pairings=[_pairing()])
        self.assertEqual(_get(db)[0]["trade"], "Framers")

    def test_the_sentinel_is_resolved_too(self):
        # THE ARKON CASE. A crew flagged needs_trade_assignment carries the
        # literal string, not an empty one; a check that only tested for ""
        # would leave this exact worker reading "No trade assigned".
        db, _ = _build(checkins=[_legacy_row(worker_trade="UNASSIGNED")],
                       pairings=[_pairing()])
        self.assertEqual(_get(db)[0]["trade"], "Framers")

    def test_no_pairing_leaves_it_empty(self):
        db, _ = _build(checkins=[_legacy_row(worker_trade="")], pairings=[])
        self.assertEqual(_get(db)[0]["trade"], "",
                         "absent is the honest answer; the log names it "
                         "'No trade assigned' rather than guessing")

    def test_a_pairing_with_no_trade_is_treated_as_absent(self):
        # Mirrors _get_worker_project_trade: a pairing that names no trade
        # tells us nothing and must not be written back as an empty answer.
        db, _ = _build(checkins=[_legacy_row(worker_trade="")],
                       pairings=[_pairing(trade="  ")])
        self.assertEqual(_get(db)[0]["trade"], "")

    def test_a_pairing_for_another_worker_is_not_borrowed(self):
        db, _ = _build(checkins=[_legacy_row(worker_trade="")],
                       pairings=[_pairing(worker_id="someone_else")])
        self.assertEqual(_get(db)[0]["trade"], "")


class TheFrozenValueIsNeverOverwritten(unittest.TestCase):
    def test_a_frozen_trade_wins_over_a_different_pairing(self):
        # The precedence rule, stated as a test. A pairing edited after this
        # check-in must not be able to rewrite what the day recorded.
        db, _ = _build(checkins=[_legacy_row(worker_trade="Carpenter")],
                       pairings=[_pairing(trade="Framers")])
        self.assertEqual(_get(db)[0]["trade"], "Carpenter")

    def test_the_pairing_is_not_even_consulted_for_a_frozen_row(self):
        db, pair = _build(checkins=[_legacy_row(worker_trade="Carpenter")],
                          pairings=[_pairing()])
        _get(db)
        # It is read (one batch for the whole page) but cannot win. The
        # assertion that matters is the value above; this pins that a frozen
        # row does not somehow acquire a second lookup of its own.
        self.assertLessEqual(len(pair.queries), 1)


class TheWorkerDocumentNoLongerLeaks(unittest.TestCase):
    def test_workers_trade_is_not_used_as_a_fallback(self):
        # `workers.trade` is the cross-project bleed register_and_checkin
        # deliberately stopped writing — one slot for a man who holds different
        # trades on different jobs, answered by whichever project filled it
        # first. Reading it here kept that wrong answer alive on the one
        # surface that prints it onto a compliance record.
        db, _ = _build(checkins=[_legacy_row(worker_trade="")],
                       pairings=[], worker_trade="Demolition (another job)")
        self.assertEqual(_get(db)[0]["trade"], "",
                         "a trade from another project is worse than no trade: "
                         "it is silently wrong instead of visibly absent")

    def test_the_pairing_beats_the_worker_document(self):
        db, _ = _build(checkins=[_legacy_row(worker_trade="")],
                       pairings=[_pairing()], worker_trade="Demolition")
        self.assertEqual(_get(db)[0]["trade"], "Framers")


class TheLookupIsCheapAndScoped(unittest.TestCase):
    def test_one_query_for_the_whole_roster(self):
        rows = [_legacy_row(_id=f"chk_{i}", worker_id=f"w{i}",
                            worker_name=f"Worker {i}", worker_trade="")
                for i in range(13)]
        db, pair = _build(checkins=rows, pairings=[])
        _get(db)
        self.assertEqual(len(pair.queries), 1,
                         "thirteen men at shift start must not cost thirteen "
                         "extra round trips on the roster read")

    def test_the_query_is_scoped_to_this_project_and_these_workers(self):
        db, pair = _build(checkins=[_legacy_row(worker_trade="")],
                          pairings=[_pairing()])
        _get(db)
        q = pair.queries[0]
        self.assertEqual(q["project_id"], "proj1",
                         "a pairing from another project must be unreachable")
        self.assertEqual(q["worker_id"], {"$in": ["w1"]})

    def test_no_checkins_means_no_pairing_query_at_all(self):
        db, pair = _build(checkins=[], pairings=[_pairing()])
        self.assertEqual(_get(db), [])
        self.assertEqual(pair.queries, [])


class AFailedLookupCostsNothing(unittest.TestCase):
    def test_the_roster_still_returns_when_the_pairing_read_blows_up(self):
        # The CP gets what the check-ins froze, which is what he got before
        # this existed. A bookkeeping read must never cost him the roster.
        db, _ = _build(checkins=[_legacy_row(worker_trade="Carpenter")],
                       pairings=[_pairing()], raise_pairings=True)
        body = _get(db)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["trade"], "Carpenter")

    def test_an_unresolvable_row_is_empty_not_an_error(self):
        db, _ = _build(checkins=[_legacy_row(worker_trade="")],
                       pairings=[_pairing()], raise_pairings=True)
        body = _get(db)
        self.assertEqual(body[0]["trade"], "")


class TheRestOfTheRowIsUnchanged(unittest.TestCase):
    def test_shape_and_neighbours_are_untouched(self):
        db, _ = _build(checkins=[_legacy_row(worker_trade="")],
                       pairings=[_pairing()])
        row = _get(db)[0]
        self.assertEqual(row["worker_id"], "w1")
        self.assertEqual(row["worker_name"], "Wilmer Carrillo")
        self.assertEqual(row["company"], "Arkon Builders",
                         "company is NOT resolved from the pairing here — it is "
                         "the crew grouping key and belongs in its own change")
        self.assertEqual(row["source"], "legacy_checkin")
        self.assertEqual(row["osha_number"], "OSHA-1")


if __name__ == "__main__":
    unittest.main()
