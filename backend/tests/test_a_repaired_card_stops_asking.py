"""A card repaired at 12:33 must stop asking the roster to fix it at 06:57.

THE DEFECT. `sst_status` is frozen onto the check-in row at tap time and, by
its own design note, never overwritten -- it is the durable per-check-in
compliance artifact and the filed LL196 register reads it. Angel Lopez tapped
at 10:57:53Z with an unreadable expiry, his cert row was repaired at 12:33:56Z,
and the Workers roster still printed "Unknown SST card" against his 06:57 row
for the rest of the day. The row is not wrong. The ROSTER is asking a different
question -- "what needs doing NOW" -- and answering it from a snapshot of
"what was known THEN".

WHAT THIS PINS. GET /api/checkins keeps every frozen field byte-for-byte and
adds the LIVE cert state beside it, derived through the SAME functions the gate
itself uses (validate_worker_certifications / _sst_cert_state), batched into
ONE $in over the page's worker ids.

THE FIXTURES ARE THE TWO PRODUCTION ROWS, not invented ones:

  Angel Lopez  frozen: unknown / EXPIRY / no expiry / cert_warnings SST_UNKNOWN
               live:   SST_FULL RUQ24T3LVF exp 2031-03-01, class from
                       color_and_text, needs_review False
               -> STALE. The roster must stop warning.

  Juan Lopez   frozen: unknown / BOTH / no expiry
               live:   SST_UNSPECIFIED TYPN6JCNJ1 exp 2029-10-27,
                       needs_review True, review_reason CLASS_UNVERIFIED
               -> GENUINELY OPEN, but only the CLASS half. The frozen `BOTH`
                  still claims the expiry is unknown and it is now on file.
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


# ── Minimal async Mongo fakes ─────────────────────────────────────────────

class _FakeFind:
    """Supports .sort().skip().limit().to_list() and plain .to_list()."""

    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []
        # EVERY call recorded, not just the last. The batching assertion is a
        # claim about HOW MANY times this collection was queried, so a
        # `last_query` slot -- which is what the sibling fixtures keep -- could
        # not state it at all.
        self.find_calls = []
        self.find_one_calls = []
        self._find_one = None

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        self.find_one_calls.append(query)
        v = self._find_one
        return v(query) if callable(v) else v

    def find(self, query=None, *a, **k):
        self.find_calls.append(query)
        if self.name == "workers":
            # Honour the $in the endpoint is required to send, so a fixture
            # cannot pass by handing back every worker regardless of the query.
            ids = ((query or {}).get("_id") or {}).get("$in")
            if ids is not None:
                wanted = {str(i) for i in ids}
                return _FakeFind([d for d in self.docs if str(d["_id"]) in wanted])
        return _FakeFind(self.docs)

    async def count_documents(self, *a, **k):
        return len(self.docs)


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


# ── The two production rows, as they stand today ──────────────────────────

_TAP = datetime(2026, 9, 18, 10, 57, 53, tzinfo=timezone.utc)   # 6:57 AM EDT

ANGEL_CHECKIN = {
    "_id": "6aad1931e11a679c8c322f6a",
    "company_id": "co_a",
    "project_id": "proj1",
    "worker_id": "w_angel",
    "worker_name": "Angel Lopez",
    "worker_company": "Acme Co",
    "check_in_time": _TAP,
    "sst_status": "unknown",
    "sst_unknown_reason": "EXPIRY",
    "sst_card_number": "RUQ24T3LVF",
    "sst_expiration": None,
    "cert_cleared": True,
    "cert_warnings": ["SST_UNKNOWN"],
    "review_decision": None,
}

ANGEL_WORKER = {
    "_id": "w_angel",
    "name": "Angel Lopez",
    "company": "Acme Co",
    "certifications": [{
        "type": "SST_FULL",
        "card_number": "RUQ24T3LVF",
        "expiration_date": datetime(2031, 3, 1, tzinfo=timezone.utc),
        "needs_review": False,
        "review_reason": None,
        "extraction_completeness": 1.0,
        "verified": False,
        "class_source": "color_and_text",
    }],
}

JUAN_CHECKIN = {
    "_id": "chk_juan",
    "company_id": "co_a",
    "project_id": "proj1",
    "worker_id": "w_juan",
    "worker_name": "Juan Lopez",
    "worker_company": "Acme Co",
    "check_in_time": _TAP,
    "sst_status": "unknown",
    "sst_unknown_reason": "BOTH",
    "sst_card_number": "TYPN6JCNJ1",
    "sst_expiration": None,
    "cert_cleared": True,
    "cert_warnings": ["SST_UNKNOWN"],
    "review_decision": None,
}

JUAN_WORKER = {
    "_id": "w_juan",
    "name": "Juan Lopez",
    "company": "Acme Co",
    "certifications": [{
        "type": "SST_UNSPECIFIED",
        "card_number": "TYPN6JCNJ1",
        "expiration_date": datetime(2029, 10, 27, tzinfo=timezone.utc),
        "needs_review": True,
        "review_reason": "CLASS_UNVERIFIED",
        "extraction_completeness": 0.75,
    }],
}


def _mk_db(checkins, workers):
    db = _FakeDb()
    db.checkins.docs = list(checkins)
    db.workers.docs = list(workers)
    return db


def _get(db, path="/api/checkins"):
    user = {
        "_id": "u1", "id": "u1", "role": "admin",
        "company_id": "co_a", "full_name": "Ada Admin",
        "assigned_projects": [],
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            return TestClient(server.app).get(path)
    finally:
        server.app.dependency_overrides.clear()


def _by_id(resp):
    return {i["id"]: i for i in resp.json()["items"]}


class LiveSstBesideFrozenTest(unittest.TestCase):

    def test_angels_repaired_card_reports_live_valid(self):
        """The whole defect, in one assertion."""
        db = _mk_db([ANGEL_CHECKIN], [ANGEL_WORKER])
        resp = _get(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = _by_id(resp)["6aad1931e11a679c8c322f6a"]
        self.assertEqual(row["sst_status_live"], "valid")
        self.assertIsNone(row["sst_review_reason"])

    def test_the_frozen_snapshot_is_returned_untouched(self):
        """THE SAFETY PROPERTY. The filed LL196 register reads these fields.

        Adding a live reading must not repair, replace or drop a single one of
        them -- a filed document shows what was filed, and `sst_status` is the
        source the register's UNVERIFIED marker is frozen from.
        """
        db = _mk_db([ANGEL_CHECKIN], [ANGEL_WORKER])
        row = _by_id(_get(db))["6aad1931e11a679c8c322f6a"]
        self.assertEqual(row["sst_status"], "unknown")
        self.assertEqual(row["sst_unknown_reason"], "EXPIRY")
        self.assertEqual(row["sst_card_number"], "RUQ24T3LVF")
        self.assertIsNone(row["sst_expiration"])
        self.assertEqual(row["cert_warnings"], ["SST_UNKNOWN"])
        self.assertIs(row["cert_cleared"], True)

    def test_juan_is_still_unknown_and_names_only_the_open_half(self):
        """A warning is correct for him; the FROZEN reason is not.

        `sst_unknown_reason` froze `BOTH` -- class AND expiry. His expiry is
        now on file, so only the class is open, and the live `review_reason`
        is the field that can say so.
        """
        db = _mk_db([JUAN_CHECKIN], [JUAN_WORKER])
        row = _by_id(_get(db))["chk_juan"]
        self.assertEqual(row["sst_status_live"], "unknown")
        self.assertEqual(row["sst_review_reason"], "CLASS_UNVERIFIED")
        # And the frozen half-truth stays exactly where it is.
        self.assertEqual(row["sst_unknown_reason"], "BOTH")

    def test_one_query_for_the_whole_page_not_one_per_row(self):
        """`limit` goes to 500. A per-row lookup here is 500 round trips.

        Counted rather than described: this asserts the NUMBER of reads against
        db.workers, which is the only thing that distinguishes a batch from an
        N+1 that happens to return the right answer.
        """
        rows, workers = [], []
        for n in range(12):
            c = dict(JUAN_CHECKIN)
            c["_id"] = f"chk_{n}"
            c["worker_id"] = f"w_{n}"
            c["worker_name"] = ""          # forces the name-resolution path too
            # CARRIED BECAUSE THE ENDPOINT WOULD 500 WITHOUT IT, not because
            # this test is about trades. That path ends in
            # `s["trade"] = s["worker_trade"]` -- a subscript, not a .get -- so
            # a nameless row with no frozen trade raises KeyError and takes the
            # whole page with it. PRE-EXISTING and deliberately NOT fixed here
            # (it is a different defect on a different field); it is reported
            # in the PR body. Real rows written by register_and_checkin carry
            # the field, which is why nobody has hit it.
            c["worker_trade"] = "Laborer"
            rows.append(c)
            w = dict(JUAN_WORKER)
            w["_id"] = f"w_{n}"
            workers.append(w)
        db = _mk_db(rows, workers)
        resp = _get(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.workers.find_calls), 1,
                         "the page's workers must be read in ONE $in query")
        self.assertEqual(db.workers.find_one_calls, [],
                         "no per-row find_one may survive beside the batch")
        ids = (db.workers.find_calls[0]["_id"] or {}).get("$in")
        self.assertEqual(len(ids), 12)

    def test_an_unresolvable_worker_gets_no_live_field_at_all(self):
        """ABSENT, NOT GUESSED.

        A deleted worker, or an id that no longer resolves, means we have no
        live reading -- not that the card is fine and not that it is broken.
        Emitting a default here would put a fabricated verdict on the roster;
        the client falls back to the frozen snapshot and labels it as of the
        check-in instead.
        """
        db = _mk_db([ANGEL_CHECKIN], [])       # worker row gone
        row = _by_id(_get(db))["6aad1931e11a679c8c322f6a"]
        self.assertNotIn("sst_status_live", row)
        self.assertNotIn("sst_review_reason", row)
        self.assertEqual(row["sst_status"], "unknown")

    def test_the_live_verdict_comes_from_the_gates_own_rules(self):
        """NOT A SECOND DEFINITION OF "VALID".

        A dead-scheme card (SST_LIMITED ceased to be a valid SST card in August
        2020) with a legible class and a FUTURE expiry is `unknown` -- a rule
        that lives only in _sst_cert_state. A hand-rolled "has a number and a
        future date" comparison on this read path would call it valid, so this
        row is what tells the two apart.
        """
        worker = {
            "_id": "w_angel", "name": "Angel Lopez", "company": "Acme Co",
            "certifications": [{
                "type": "SST_LIMITED",
                "card_number": "XCAS2DYB8G",
                "expiration_date": datetime(2028, 2, 26, tzinfo=timezone.utc),
                "review_reason": "CLASS_EXPIRED_SCHEME",
                "class_source": "color_and_text",
            }],
        }
        db = _mk_db([ANGEL_CHECKIN], [worker])
        row = _by_id(_get(db))["6aad1931e11a679c8c322f6a"]
        self.assertEqual(row["sst_status_live"], "unknown")
        self.assertEqual(row["sst_review_reason"], "CLASS_EXPIRED_SCHEME")

    def test_a_card_that_expired_since_check_in_reads_expired_now(self):
        """The staleness runs BOTH ways and the fix must not be one-directional.

        A card that was fine at 06:57 and lapsed at midnight is the same defect
        wearing the other face: the frozen snapshot would keep saying it is
        fine. Nothing about this row is 'repaired', so it also proves the live
        read is not merely a way of clearing warnings.
        """
        checkin = dict(ANGEL_CHECKIN)
        checkin["sst_status"] = "valid"
        checkin["sst_unknown_reason"] = None
        checkin["cert_warnings"] = []
        worker = dict(ANGEL_WORKER)
        worker["certifications"] = [{
            "type": "SST_FULL",
            "card_number": "RUQ24T3LVF",
            "expiration_date": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "class_source": "color_and_text",
        }]
        db = _mk_db([checkin], [worker])
        row = _by_id(_get(db))["6aad1931e11a679c8c322f6a"]
        self.assertEqual(row["sst_status"], "valid", "frozen field untouched")
        self.assertEqual(row["sst_status_live"], "expired")


if __name__ == "__main__":
    unittest.main()
