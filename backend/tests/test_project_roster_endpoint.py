"""THE PICKER'S ROSTER, AND THE TWO GATES THAT SCOPE IT.

`+ Add Row` on the pre-shift sheet took a hand-typed name into a document where
the gate already knew who was on site. This endpoint is the upstream fix: pick
the man. Everything below is about the two ways it could leak, and the one way
it could quietly lie.

WHY THE JOIN IS NOT ITS OWN. `roster_for_window` is the LL196 attestation's
roster build with the calendar window dropped. Two joins would let a statutory
filing and the sheet a CP fills disagree about which men were on the site --
the same class of defect as one report printing one man under two names.
`_roster_for_period` is now a thin month-shaped wrapper over it, so the two can
only diverge by someone deleting the wrapper.

THE TENANT GUARD IS THE WHOLE RISK, and it is two gates rather than one:

  * `_assert_project_access` on the PATH PARAMETER. The company filter alone
    does not scope a project -- a CP at a legitimate company could otherwise
    name any project id and read its roster.

  * a COMPANY-SCOPED hydrate, refusing the `if company_id:` shape that leaked
    `GET /workers`. `company_id = None` is the DEFAULT account state, not an
    edge case: self-serve registration sets it and a company is attached later.

DUPLICATES ARE RETURNED ON PURPOSE, and that is asserted below. A man who
exists as two worker documents appears twice; the CP is the only person who
knows they are the same man. Collapsing them in the picker would perform in the
UI the exact merge `test_report_six_defects.py` forbids in a normaliser, and
deleting a man from the record of who was on site is worse than showing two
rows.
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
from fastapi import HTTPException  # noqa: E402

PROJECT = "p1"
OTHER = "p2"


def _match(doc, query):
    """Enough of Mongo for these fixtures: $in, $ne, $and, and equality."""
    if "$and" in query:
        return all(_match(doc, sub) for sub in query["$and"])
    for k, cond in query.items():
        v = doc.get("_id") if k == "_id" else doc.get(k)
        if isinstance(cond, dict):
            if "$in" in cond and v not in cond["$in"]:
                return False
            if "$ne" in cond and v == cond["$ne"]:
                return False
            if "$gte" in cond and (v is None or v < cond["$gte"]):
                return False
            if "$lt" in cond and (v is None or v >= cond["$lt"]):
                return False
        elif v != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield copy.deepcopy(d)
        return gen()


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.queries = []

    def find(self, query=None, projection=None):
        self.queries.append((query or {}, projection))
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query=None, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query or {}):
                return copy.deepcopy(d)
        return None


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


def _checkin(project, wid, when="2026-08-12T11:00:00Z"):
    return {"project_id": project, "worker_id": wid, "is_deleted": False,
            "worker_trade": "Laborer", "check_in_time": when}


def _worker(wid, name, company="AAZ", cid="c1"):
    return {"_id": wid, "name": name, "company": company, "company_id": cid,
            "osha_number": "OSHA-" + wid, "is_deleted": False,
            "osha_card_image": "BASE64-BLOB-THAT-MUST-NOT-SHIP"}


class Base(unittest.TestCase):
    def setUp(self):
        self.db = _DB()
        self.db.checkins.docs = [
            _checkin(PROJECT, "w1"), _checkin(PROJECT, "w2"),
            _checkin(PROJECT, "w1"),                       # a second visit
            _checkin(OTHER, "w9"),                         # another project
        ]
        self.db.workers.docs = [
            _worker("w1", "Wilmer Carrillo"),
            _worker("w2", "Segundo Pilamunga"),
            _worker("w9", "Somebody Else"),
        ]
        self._orig = {"db": server.db, "apa": server._assert_project_access,
                      "gid": server.get_user_company_id,
                      "op": server.is_platform_operator}
        server.db = self.db
        self.access_calls = []

        async def _apa(pid, user):
            self.access_calls.append((pid, user))
        server._assert_project_access = _apa

    def tearDown(self):
        server.db = self._orig["db"]
        server._assert_project_access = self._orig["apa"]
        server.get_user_company_id = self._orig["gid"]
        server.is_platform_operator = self._orig["op"]

    def call(self, user):
        return asyncio.run(server.get_project_roster(PROJECT, user))


class TheRosterIsTheOneTheRegisterUses(Base):
    def setUp(self):
        super().setUp()
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False

    def test_it_returns_the_men_who_checked_in_here(self):
        out = self.call({"id": "u1"})
        self.assertEqual({r["name"] for r in out["workers"]},
                         {"Wilmer Carrillo", "Segundo Pilamunga"})

    def test_a_man_on_ANOTHER_project_is_not_on_this_roster(self):
        out = self.call({"id": "u1"})
        self.assertNotIn("Somebody Else", {r["name"] for r in out["workers"]})

    def test_two_visits_are_one_row(self):
        out = self.call({"id": "u1"})
        self.assertEqual(len(out["workers"]), 2)
        self.assertEqual(out["total"], 2)

    def test_it_goes_through_the_registers_own_join(self):
        """A second answer to "who was on this site" is the defect this
        endpoint exists to prevent, one level up. Asserted on the dataflow: the
        month-shaped wrapper the attestation calls must delegate here."""
        import inspect
        from lib.logbook import ll196
        body = inspect.getsource(ll196._roster_for_period)
        self.assertIn("roster_for_window", body)
        self.assertNotIn("db.checkins.find", body,
                         "the wrapper grew its own join")

    def test_the_card_image_never_leaves_the_database(self):
        """`osha_card_image` is base64 on the worker document and is what took
        GET /workers over Mongo's 32MB sort limit. A projection, asserted on
        the QUERY rather than on the response, because a response that merely
        does not mention it was still loaded."""
        self.call({"id": "u1"})
        projections = [p for q, p in self.db.workers.queries if p]
        self.assertTrue(projections, "no projection was passed")
        for p in projections:
            self.assertNotIn("osha_card_image", p)
            self.assertIn("name", p)

    def test_the_trade_comes_across(self):
        out = self.call({"id": "u1"})
        self.assertTrue(all(r["trade"] == "Laborer" for r in out["workers"]))


class DuplicatesAreShownToTheCP(Base):
    """The ruling: a man who exists twice appears twice."""

    def setUp(self):
        super().setUp()
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False
        self.db.workers.docs.append(_worker("w3", "Wilmer J Carrillo"))
        self.db.checkins.docs.append(_checkin(PROJECT, "w3"))

    def test_both_spellings_are_offered(self):
        names = [r["name"] for r in self.call({"id": "u1"})["workers"]]
        self.assertIn("Wilmer Carrillo", names)
        self.assertIn("Wilmer J Carrillo", names)

    def test_nothing_collapsed_them(self):
        """The exact pair `test_report_six_defects.py` asserts `_norm_key` must
        keep apart. A picker that hid one would perform that merge in the UI."""
        self.assertEqual(len(self.call({"id": "u1"})["workers"]), 3)


class TheTenantGuard(Base):
    def test_project_access_is_checked_FIRST_and_on_the_PATH_id(self):
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False
        self.call({"id": "u1"})
        self.assertEqual([p for p, _ in self.access_calls], [PROJECT])

    def test_a_caller_refused_the_project_gets_nothing_and_no_query_runs(self):
        """403 before any read. The company filter cannot substitute for this:
        a CP at a legitimate company could otherwise name any project id."""
        async def _deny(pid, user):
            raise HTTPException(status_code=403, detail="no")
        server._assert_project_access = _deny
        server.get_user_company_id = lambda u: "c1"
        server.is_platform_operator = lambda u: False
        with self.assertRaises(HTTPException) as cm:
            self.call({"id": "u1"})
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(self.db.workers.queries, [],
                         "the roster was read before the caller was authorised")

    def test_a_caller_with_NO_COMPANY_gets_an_empty_list(self):
        """THE DEFAULT ACCOUNT STATE, not an edge case. Self-serve
        registration sets company_id = None and a company is attached later by
        POST /onboarding/company. `GET /workers` had `if company_id:` alone and
        handed every trial user the whole platform's roster."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        out = self.call({"id": "u-new"})
        self.assertEqual(out["workers"], [])
        self.assertEqual(out["total"], 0)

    def test_and_the_refusal_is_an_UNSATISFIABLE_FILTER_not_a_second_path(self):
        """`_id: None` merged with `$and`, so the shape of the query is
        identical to a company that simply owns nobody. Dict-merging it would
        REPLACE the `_id: {$in: ...}` term and return the wrong men."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: False
        self.call({"id": "u-new"})
        q = [q for q, _ in self.db.workers.queries]
        self.assertTrue(q, "no worker query was issued at all")
        self.assertIn("$and", q[0])
        self.assertIn({"_id": None}, q[0]["$and"])

    def test_a_caller_with_a_DIFFERENT_company_sees_none_of_these_men(self):
        server.get_user_company_id = lambda u: "c-other"
        server.is_platform_operator = lambda u: False
        self.assertEqual(self.call({"id": "u2"})["workers"], [])

    def test_the_platform_operator_carve_out_is_explicit(self):
        """Never inferred from `role` — "owner" is what every self-serve signup
        receives."""
        server.get_user_company_id = lambda u: None
        server.is_platform_operator = lambda u: True
        self.assertEqual(len(self.call({"id": "root"})["workers"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
