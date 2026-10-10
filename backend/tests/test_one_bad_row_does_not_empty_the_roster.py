"""ONE MALFORMED CHECK-IN MUST NOT REMOVE EVERY GOOD ONE.

    python -m pytest backend/tests/test_one_bad_row_does_not_empty_the_roster.py

── THE DEFECT ──────────────────────────────────────────────────────────────

`GET /api/checkins` enriches rows whose `worker_name` is missing by reading the
worker document. That branch ended:

    s["name"]    = s["worker_name"]      # assigned two lines up  -- safe
    s["company"] = s["worker_company"]   # assigned two lines up  -- safe
    s["trade"]   = s["worker_trade"]     # NEVER assigned         -- KeyError

Nothing in the branch writes `worker_trade` and no schema guarantees it, so a
check-in document without the key raised KeyError out of the loop, out of the
handler, and returned 500 for the WHOLE response.

THE BLAST RADIUS IS THE POINT. This is not one row rendering badly. It is every
other worker's row disappearing with it, on the roster a CP opens to see who is
on site. A degraded row is a nuisance; an empty screen during a walkthrough is
the CP unable to answer who is on his job.

Measured 2026-09-18: 0 rows of this shape in production, so it was latent. It
is fixed anyway, because the condition that reaches it -- a check-in carrying a
worker_id and no worker_name -- is exactly what a half-written or hand-edited
row looks like, and 0 is a fact about today.

── WHY THE ASSERTION IS THE PAGE AND NOT THE FIELD ─────────────────────────

Asserting `trade is None` would pass against a handler that returned that one
row and dropped the rest. The invariant worth pinning is that the response
still carries the other workers -- so the test puts GOOD rows either side of
the bad one and counts them.

`trade` is None rather than a fallback DELIBERATELY: `workers.trade` is one
slot for a man who holds different trades on different jobs, so the fallback
was removed on purpose. A blank trade is visibly incomplete; another site's
trade is invisibly wrong.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_roster_bad_row")

import server  # noqa: E402


def _run(coro):
    """`asyncio.run`, not `get_event_loop().run_until_complete`.

    The latter passes alone and raises "There is no current event loop" once
    another module in the same suite has called `asyncio.run`. That has already
    been reported on this repo as a product defect when it was a test defect.
    """
    return asyncio.run(coro)


WORKER_ID = "6a9576da611a543244a9ccac"

#: The row that crashed: a worker_id, NO worker_name, and NO worker_trade key.
BAD_ROW = {
    "_id": "6aad1931e11a679c8c322f6a",
    "worker_id": WORKER_ID,
    "company_id": "c1",
    "sst_status": "valid",
    # worker_name  -- absent, which is what sends it down the enrich branch
    # worker_trade -- absent, which is what used to raise
}

def _good_row(n):
    return {
        "_id": f"good{n}", "worker_id": f"w{n}", "company_id": "c1",
        "worker_name": f"Good Worker {n}", "worker_company": "Arkon Builders",
        "worker_trade": "Framers", "sst_status": "valid",
    }


class OneBadRowLeavesTheOthersStanding(unittest.TestCase):

    def _call(self, rows, capture=None):
        """Drive the real handler over `rows` and return the response.

        THE HANDLER QUERIES `db.checkins` DIRECTLY -- `count_documents` and a
        chained `find().sort().skip().limit().to_list()`. It does NOT go
        through `paginated_query`; the first version of this test patched that
        instead and every case failed with "object MagicMock can't be used in
        'await' expression". Five red tests that never reached the defect, and
        a control run that looked like proof.
        """
        # The worker the bad row points at RESOLVES -- that is what puts
        # execution inside the branch. A worker that did not resolve would skip
        # it entirely and the test would pass without exercising anything.
        worker_doc = {"_id": server.to_query_id(WORKER_ID),
                      "name": "Angel Lopez", "company": "Arkon Builders",
                      "certifications": []}

        def _chain(result):
            """A motor cursor: sort/skip/limit return self, to_list awaits."""
            cur = MagicMock()
            cur.sort.return_value = cur
            cur.skip.return_value = cur
            cur.limit.return_value = cur
            cur.to_list = AsyncMock(return_value=result)
            return cur

        db = MagicMock()
        db.checkins = MagicMock()
        db.checkins.count_documents = AsyncMock(return_value=len(rows))

        def _find(query, *a, **kw):
            if capture is not None:
                capture["query"] = query
            return _chain([dict(r) for r in rows])

        db.checkins.find = MagicMock(side_effect=_find)
        db.workers = MagicMock()
        db.workers.find = MagicMock(return_value=_chain([worker_doc]))

        user = {"_id": "u1", "id": "u1", "email": "a@b.c", "role": "admin",
                "company_id": "c1", "account_status": "approved"}

        orig_db = server.db
        server.db = db
        try:
            return _run(server.get_all_checkins(
                date=None, current_user=user, limit=50, skip=0))
        finally:
            server.db = orig_db

    def test_the_bad_row_alone_does_not_raise(self):
        """Before the fix this was KeyError: 'worker_trade'."""
        resp = self._call([BAD_ROW])
        self.assertEqual(len(resp["items"]), 1)

    def test_the_GOOD_rows_still_come_back(self):
        """THE ASSERTION THIS FILE IS FOR.

        Three good rows with the bad one in the middle. A handler that raises
        returns none of them; a handler that drops the bad row silently returns
        three. Both are wrong and they are different wrongs, so the count is
        checked exactly.
        """
        rows = [_good_row(1), BAD_ROW, _good_row(2), _good_row(3)]
        resp = self._call(rows)
        self.assertEqual(
            len(resp["items"]), 4,
            "the malformed row took the other workers off the roster")
        names = [r.get("worker_name") for r in resp["items"]]
        for n in ("Good Worker 1", "Good Worker 2", "Good Worker 3"):
            self.assertIn(n, names, f"{n} disappeared from the response")

    def test_the_enriched_row_carries_the_name_it_resolved(self):
        """The branch still does its job -- the fix must not turn the crash
        into a silently unenriched row."""
        resp = self._call([BAD_ROW])
        row = resp["items"][0]
        self.assertEqual(row.get("worker_name"), "Angel Lopez")
        self.assertEqual(row.get("name"), "Angel Lopez")

    def test_trade_is_blank_and_NOT_borrowed(self):
        """None, deliberately. See the module docstring: `workers.trade` holds
        one trade for a man who may hold a different one on each job, so
        filling this in from the worker document would be invisibly wrong on
        every multi-project worker."""
        resp = self._call([BAD_ROW])
        self.assertIsNone(
            resp["items"][0].get("trade"),
            "the trade fallback came back — a blank trade is visibly "
            "incomplete, another site's trade is invisibly wrong")

    def test_the_tenant_filter_is_unchanged(self):
        """This handler's company scoping is a tenancy boundary and this change
        is three lines away from it. Pinned so a later edit here cannot widen
        it unnoticed."""
        captured = {}
        self._call([_good_row(1)], capture=captured)
        self.assertEqual(
            captured["query"].get("company_id"), "c1",
            "the tenant filter changed — this handler spans every project a "
            "company runs and the rows carry worker names, SST card numbers "
            "and device fingerprints")


if __name__ == "__main__":
    unittest.main(verbosity=2)
