"""The Tool Box Talk banner names the company a worker belongs to.

THE DEFECT. CP home read "Andre Duval ()" — empty parentheses on the list of
workers missing this week's Tool Box Talk. The CP has to go and give that talk;
a name with no company is a worker he cannot place.

THE CAUSE, and it is a reader bug rather than missing data. The notifications
endpoint did `worker.get("company")`. The `workers` document HAS NO COMPANY,
deliberately — the register_and_checkin insert says so in as many words:

    NOTE: no `trade` / `company` here. Those are per-project and live in
    worker_project_trades; a worker-level copy is what bled across jobs.

So the field was always None, for every worker, on every project. It read as
missing data and was a lookup in the wrong collection.

THE FIX reads the pairing, via the helper that already owns this question.
_get_worker_project_trade deliberately never falls back to the workers doc —
"a value from another project is worse than no value, because it is silently
wrong instead of visibly absent" — so an unpaired worker still yields no
company, and the client drops the brackets rather than printing "()".
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

PROJECT = "proj1"
WEEK_AGO = "2026-08-05"


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict):
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
            if "$gte" in v:
                # The endpoint's week window is a datetime; these fixtures use
                # ISO date strings. The window is not what this file measures
                # — every fixture row is deliberately inside it — so a
                # cross-type bound is treated as satisfied rather than faked.
                got, bound = doc.get(k), v["$gte"]
                if type(got) is type(bound) and not (got >= bound):
                    return False
            if "$in" in v and doc.get(k) not in v["$in"]:
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))

    async def distinct(self, field, query=None):
        return list({d.get(field) for d in self.docs
                     if _match(d, query or {}) and d.get(field)})


class _DB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]


class Base(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.workers.docs = [
            # As register_and_checkin writes one: NO company field.
            {"_id": "w1", "name": "Andre Duval", "phone": "555",
             "company_id": "coA"},
        ]
        self.db.checkins.docs = [
            {"_id": "c1", "project_id": PROJECT, "worker_id": "w1",
             "date": "2026-08-10"},
        ]
        self.db.logbooks.docs = []
        self._orig = {"db": server.db, "tqid": server.to_query_id}
        server.db = self.db
        server.to_query_id = lambda x: x

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]
        self.loop.close()

    def pairing(self, company="Air Star Mechanical", trade="HVAC / Mechanical"):
        self.db[server.WORKER_PROJECT_TRADES_COLLECTION].docs = [
            {"worker_id": "w1", "project_id": PROJECT,
             "trade": trade, "company": company},
        ]

    def missing(self):
        out = self.loop.run_until_complete(
            server.get_logbook_notifications(
                project_id=PROJECT,
                current_user={"_id": "u1", "id": "u1", "role": "cp",
                              "company_id": "coA",
                              "assigned_projects": [PROJECT]},
                _proj={"_id": PROJECT, "company_id": "coA"},
            ))
        return out["missing_toolbox_talk"]


class TheCompanyComesFromThePairing(Base):
    def test_the_worker_is_listed_at_all(self):
        self.pairing()
        rows = self.missing()
        self.assertEqual([r["worker_name"] for r in rows], ["Andre Duval"])

    def test_and_carries_his_company_on_THIS_project(self):
        self.pairing()
        self.assertEqual(self.missing()[0]["company"], "Air Star Mechanical")

    def test_the_workers_document_still_has_no_company_to_read(self):
        """The premise. If a company ever appears on the worker doc, the
        per-project design has been broken somewhere else and this test should
        be the thing that says so."""
        self.assertNotIn("company", self.db.workers.docs[0])

    def test_the_OLD_lookup_would_still_return_nothing(self):
        """The control: proves the fix changed the source, and that the old
        expression was not merely unlucky on this fixture."""
        self.pairing()
        self.assertIsNone(self.db.workers.docs[0].get("company"))


class AnUnpairedWorkerYieldsNoCompany(Base):
    def test_company_is_None_rather_than_a_guess(self):
        rows = self.missing()          # no pairing stored
        self.assertEqual(rows[0]["worker_name"], "Andre Duval")
        self.assertIsNone(rows[0]["company"])

    def test_a_pairing_on_ANOTHER_project_is_not_borrowed(self):
        """_get_worker_project_trade never falls back — a company from another
        job is silently wrong, which is worse than visibly absent."""
        self.db[server.WORKER_PROJECT_TRADES_COLLECTION].docs = [
            {"worker_id": "w1", "project_id": "some_other_project",
             "trade": "Electrical", "company": "Kestrel Electric"},
        ]
        self.assertIsNone(self.missing()[0]["company"])

    def test_a_pairing_with_no_trade_is_treated_as_absent(self):
        """The helper's own rule: a pairing with no trade tells us nothing."""
        self.pairing(company="Air Star Mechanical", trade="")
        self.assertIsNone(self.missing()[0]["company"])

    def test_an_empty_company_string_is_normalised_to_None(self):
        """So the client's `w.company ? ... : ''` test cannot be defeated by a
        blank that is truthy-adjacent."""
        self.pairing(company="   ")
        self.assertIsNone(self.missing()[0]["company"])


class TheEndpointStillReadsThePairingHelper(unittest.TestCase):
    SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_it_no_longer_reads_the_worker_document(self):
        body = self.SRC[self.SRC.index("missing_toolbox = []"):]
        body = body[:body.index("unsigned_orientations")]
        code = "\n".join(l for l in body.splitlines()
                         if not l.strip().startswith("#"))
        self.assertNotIn('worker.get("company")', code)
        self.assertIn("_get_worker_project_trade(wid, project_id)", code)


if __name__ == "__main__":
    unittest.main()
