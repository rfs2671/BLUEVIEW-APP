"""GET /projects/{id}/daily-headcount must carry the ROSTER ID.

Daily Jobsite Log builds one activity row per (sub, trade) pair straight from
this endpoint. Until now the response was {sub_name, trade, worker_count_today}
and nothing else, so a seeded row had no way to name the subcontractor it
belongs to — only its INDEX in data.activities[], which changes the moment a row
is added or reordered. Anything that has to group a subcontractor's rows (the
10-photo-per-subcontractor cap, most immediately) had nothing to group by.

So the endpoint now resolves each pair against project.trade_assignments and
returns `subcontractor_id`. What is pinned here:

  • the id comes from the project roster row, matched on the SAME
    normalization as the check-in strict-roster match (_roster_key: strip +
    casefold), so a case-only or whitespace difference still resolves
  • a pair with NO roster row gets None — never a minted id. A read must not
    create roster identity, and a fabricated id would silently merge two
    unrelated subs into one photo bucket
  • 'UNASSIGNED' check-ins resolve to None for the same reason
  • a soft-deleted ("inactive") roster row still supplies the id it was minted
    with — the day's work really was done by that sub — but an ACTIVE row for
    the same pair always wins
  • the pre-existing keys are untouched, so an older client that ignores the
    new field is unaffected
"""

from __future__ import annotations

import os
import sys
import unittest
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


# ── fakes ────────────────────────────────────────────────────────────────

# Valid 24-hex so ObjectId() accepts them (the endpoint converts before $in).
EID_A = "0123456789abcdef01234501"
EID_B = "0123456789abcdef01234502"
EID_C = "0123456789abcdef01234503"


class _Cursor:
    """to_list() for the sign_ins/checkins reads, async-iteration for the
    worker_enrollments read — the endpoint uses both shapes."""

    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, *a, **k):
        return list(self._docs)

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _FakeCollection:
    def __init__(self, docs=None, one=None):
        self.docs = list(docs or [])
        self.one = one

    async def find_one(self, query=None, *a, **k):
        return self.one

    def find(self, query=None, *a, **k):
        return _Cursor(self.docs)


class _FakeDb:
    def __init__(self, **collections):
        self._c = dict(collections)

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


def _project(trade_assignments):
    return {
        "_id": "proj1",
        "name": "Test Tower",
        "company_id": "co_test",
        "is_deleted": False,
        "trade_assignments": list(trade_assignments),
    }


def _enrollment(eid, sub, trade, worker):
    return {"_id": eid, "sub_name": sub, "trade": trade, "worker_name": worker}


def _client():
    user = {
        "_id": "cp_1", "id": "cp_1", "role": "cp",
        "company_id": "co_test", "account_status": "approved",
        "full_name": "Casey CP", "assigned_projects": ["proj1"],
    }

    async def _fake_user():
        return user

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    ov[server.require_approved] = _fake_user
    return TestClient(server.app), ov.clear


def _headcount(trade_assignments, enrollments):
    """Run the endpoint over one day of gate sign-ins."""
    sign_ins = [{"worker_enrollment_id": e["_id"]} for e in enrollments]
    db = _FakeDb(
        projects=_FakeCollection(one=_project(trade_assignments)),
        sign_ins=_FakeCollection(docs=sign_ins),
        worker_enrollments=_FakeCollection(docs=enrollments),
        checkins=_FakeCollection(docs=[]),
        workers=_FakeCollection(one=None),
    )
    client, cleanup = _client()
    try:
        with patch.object(server, "db", db):
            resp = client.get("/api/projects/proj1/daily-headcount?date=2026-08-07")
    finally:
        cleanup()
    return resp


def _by_sub(rows):
    return {r["sub_name"]: r for r in rows}


# ── the roster id reaches the row ────────────────────────────────────────

class HeadcountCarriesRosterIdTest(unittest.TestCase):

    def test_matched_pair_carries_the_roster_row_id(self):
        resp = _headcount(
            [{"trade": "Carpenter", "company": "Acme Co", "id": "srv_acme1"}],
            [_enrollment(EID_A, "Acme Co", "Carpenter", "Ann")],
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subcontractor_id"], "srv_acme1")

    def test_the_original_fields_are_untouched(self):
        """Additive only — an older client that ignores the new key is
        unaffected."""
        resp = _headcount(
            [{"trade": "Carpenter", "company": "Acme Co", "id": "srv_acme1"}],
            [
                _enrollment(EID_A, "Acme Co", "Carpenter", "Ann"),
                _enrollment(EID_B, "Acme Co", "Carpenter", "Bob"),
            ],
        )
        row = resp.json()[0]
        self.assertEqual(row["sub_name"], "Acme Co")
        self.assertEqual(row["trade"], "Carpenter")
        self.assertEqual(row["worker_count_today"], 2)

    def test_case_and_whitespace_differences_still_resolve(self):
        """_roster_key is strip + casefold, and the check-in strict-roster
        match uses the same rule — the two must not disagree."""
        resp = _headcount(
            [{"trade": " carpenter ", "company": "ACME CO", "id": "srv_acme1"}],
            [_enrollment(EID_A, "Acme Co", "Carpenter", "Ann")],
        )
        self.assertEqual(resp.json()[0]["subcontractor_id"], "srv_acme1")

    def test_each_pair_gets_its_own_id(self):
        resp = _headcount(
            [
                {"trade": "Carpenter", "company": "Acme Co", "id": "srv_acme1"},
                {"trade": "Electrician", "company": "Volt LLC", "id": "srv_volt1"},
            ],
            [
                _enrollment(EID_A, "Acme Co", "Carpenter", "Ann"),
                _enrollment(EID_B, "Volt LLC", "Electrician", "Bea"),
            ],
        )
        rows = _by_sub(resp.json())
        self.assertEqual(rows["Acme Co"]["subcontractor_id"], "srv_acme1")
        self.assertEqual(rows["Volt LLC"]["subcontractor_id"], "srv_volt1")
        self.assertNotEqual(
            rows["Acme Co"]["subcontractor_id"],
            rows["Volt LLC"]["subcontractor_id"],
        )

    def test_one_company_two_trades_gets_two_distinct_ids(self):
        """The roster's identity is (trade, company), not company. Two trades
        are two roster rows and therefore two ids."""
        resp = _headcount(
            [
                {"trade": "Carpenter", "company": "Acme Co", "id": "srv_acme_c"},
                {"trade": "Laborer", "company": "Acme Co", "id": "srv_acme_l"},
            ],
            [
                _enrollment(EID_A, "Acme Co", "Carpenter", "Ann"),
                _enrollment(EID_B, "Acme Co", "Laborer", "Bob"),
            ],
        )
        ids = sorted(r["subcontractor_id"] for r in resp.json())
        self.assertEqual(ids, ["srv_acme_c", "srv_acme_l"])


# ── absence is represented honestly ──────────────────────────────────────

class HeadcountNeverFabricatesAnIdTest(unittest.TestCase):

    def test_pair_absent_from_the_roster_is_null(self):
        """The CP with a crew the admin has not entered yet. That is an admin
        gap, and the honest answer is 'no roster identity' — not a new id."""
        resp = _headcount(
            [{"trade": "Carpenter", "company": "Acme Co", "id": "srv_acme1"}],
            [_enrollment(EID_A, "Ghost Crew", "Demolition", "Gus")],
        )
        rows = _by_sub(resp.json())
        self.assertIsNone(rows["Ghost Crew"]["subcontractor_id"])
        self.assertIn("subcontractor_id", rows["Ghost Crew"])

    def test_right_company_wrong_trade_is_null(self):
        resp = _headcount(
            [{"trade": "Carpenter", "company": "Acme Co", "id": "srv_acme1"}],
            [_enrollment(EID_A, "Acme Co", "Plumber", "Ann")],
        )
        self.assertIsNone(resp.json()[0]["subcontractor_id"])

    def test_unassigned_checkins_are_null(self):
        resp = _headcount(
            [{"trade": "Carpenter", "company": "Acme Co", "id": "srv_acme1"}],
            [_enrollment(EID_A, "UNASSIGNED", "", "Ann")],
        )
        rows = _by_sub(resp.json())
        self.assertIsNone(rows["UNASSIGNED"]["subcontractor_id"])

    def test_a_roster_row_with_no_id_yields_null(self):
        """Legacy rows predate id minting; nothing is invented for them."""
        resp = _headcount(
            [{"trade": "Carpenter", "company": "Acme Co"}],
            [_enrollment(EID_A, "Acme Co", "Carpenter", "Ann")],
        )
        self.assertIsNone(resp.json()[0]["subcontractor_id"])

    def test_an_empty_roster_yields_null_for_everyone(self):
        resp = _headcount(
            [],
            [
                _enrollment(EID_A, "Acme Co", "Carpenter", "Ann"),
                _enrollment(EID_B, "Volt LLC", "Electrician", "Bea"),
            ],
        )
        self.assertTrue(all(r["subcontractor_id"] is None for r in resp.json()))

    def test_two_unrostered_subs_do_not_share_an_id(self):
        """The property the photo cap depends on: no id is not 'the same id'."""
        resp = _headcount(
            [],
            [
                _enrollment(EID_A, "Ghost One", "Demolition", "Gus"),
                _enrollment(EID_B, "Ghost Two", "Demolition", "Gil"),
            ],
        )
        rows = _by_sub(resp.json())
        self.assertIsNone(rows["Ghost One"]["subcontractor_id"])
        self.assertIsNone(rows["Ghost Two"]["subcontractor_id"])


# ── soft-deleted roster rows ─────────────────────────────────────────────

class HeadcountSoftDeletedRosterTest(unittest.TestCase):

    def test_inactive_row_still_supplies_its_id(self):
        """The sub was soft-deleted after the work was logged; the day's rows
        still belong to it."""
        resp = _headcount(
            [{"trade": "Carpenter", "company": "Acme Co",
              "id": "srv_acme1", "status": "inactive"}],
            [_enrollment(EID_A, "Acme Co", "Carpenter", "Ann")],
        )
        self.assertEqual(resp.json()[0]["subcontractor_id"], "srv_acme1")

    def test_an_active_row_wins_over_an_inactive_one(self):
        resp = _headcount(
            [
                {"trade": "Carpenter", "company": "Acme Co",
                 "id": "srv_old", "status": "inactive"},
                {"trade": "Carpenter", "company": "Acme Co", "id": "srv_new"},
            ],
            [_enrollment(EID_A, "Acme Co", "Carpenter", "Ann")],
        )
        self.assertEqual(resp.json()[0]["subcontractor_id"], "srv_new")

    def test_a_malformed_roster_row_does_not_break_the_read(self):
        resp = _headcount(
            [None, "junk", {"trade": "Carpenter", "company": "Acme Co", "id": "srv_acme1"}],
            [_enrollment(EID_A, "Acme Co", "Carpenter", "Ann")],
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()[0]["subcontractor_id"], "srv_acme1")

    def test_a_project_with_no_trade_assignments_key_at_all(self):
        db = _FakeDb(
            projects=_FakeCollection(one={
                "_id": "proj1", "company_id": "co_test", "is_deleted": False,
            }),
            sign_ins=_FakeCollection(docs=[{"worker_enrollment_id": EID_C}]),
            worker_enrollments=_FakeCollection(
                docs=[_enrollment(EID_C, "Acme Co", "Carpenter", "Ann")]),
            checkins=_FakeCollection(docs=[]),
            workers=_FakeCollection(one=None),
        )
        client, cleanup = _client()
        try:
            with patch.object(server, "db", db):
                resp = client.get("/api/projects/proj1/daily-headcount?date=2026-08-07")
        finally:
            cleanup()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()[0]["subcontractor_id"])


if __name__ == "__main__":
    unittest.main()
