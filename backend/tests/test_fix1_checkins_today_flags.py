"""FIX 1 / TASK A — GET /logbooks/project/{id}/checkins-today carries the
flag fields the pre-shift roster needs.

Before this change the endpoint returned none of checkin_id, sst_status,
needs_trade_assignment, review_decision or cert_warnings, so the roster had
no reason to display and — more importantly — no id to POST against
/checkins/{checkin_id}/review or /checkins/{checkin_id}/assign-trade.

The endpoint has three passes and only ONE of them can honestly populate
those fields:

  PASS 1  sign_ins + worker_enrollments (the gate system). card_audit.py
          never writes to the `checkins` collection, so these workers have
          NO checkins row and therefore no id to review against. The fields
          are emitted as null/false/[] — never fabricated.
  PASS 2  the legacy `checkins` collection. This is the only source that
          HAS the state; the fields are read straight off the row.
  PASS 3  compliance_alerts CERT_BLOCK (turned away for missing OSHA).
          register_and_checkin returns BEFORE the checkins insert for this
          population, so again no row and no id. Out of scope for actions.

Also pinned: the pre-existing row shape is preserved (additive only).
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


PROJECT = {"_id": "proj1", "name": "Test Tower", "company_id": "co_a"}
USER = {
    "_id": "u1", "id": "u1", "role": "admin", "company_id": "co_a",
    "assigned_projects": [], "full_name": "Ada Admin",
}

DAY = "2026-03-04"
TS = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)


class _Cursor:
    """Supports both `await find(...).to_list()` and `async for x in find(...)`."""

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

    def find(self, query=None, *a, **k):
        return _Cursor(self.docs)

    async def find_one(self, query=None, *a, **k):
        if callable(self._find_one):
            return self._find_one(query)
        return self._find_one


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())


def _client():
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    return TestClient(server.app), (
        lambda: server.app.dependency_overrides.clear()
    )


def _get(db):
    client, cleanup = _client()
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v):
            resp = client.get(
                f"/api/logbooks/project/proj1/checkins-today?date={DAY}",
            )
    finally:
        cleanup()
    return resp


# ── PASS 2 — the legacy checkins row, the only one that HAS the state ────────
class TestLegacyPassCarriesFlags(unittest.TestCase):
    def _db(self, **overrides):
        row = {
            "_id": "chk_1",
            "worker_id": "w1",
            "worker_name": "Bob Builder",
            "worker_company": "Acme Co",
            "worker_trade": "Carpenter",
            "check_in_time": TS,
            "is_deleted": False,
            "sst_status": "expired",
            "needs_trade_assignment": False,
            "review_decision": None,
            "cert_warnings": [{"type": "EXPIRED_SST", "message": "card expired"}],
        }
        row.update(overrides)
        return _Db(
            projects=_Coll(find_one=lambda q: PROJECT),
            sign_ins=_Coll([]),
            worker_enrollments=_Coll([]),
            daily_signatures=_Coll([]),
            checkins=_Coll([row]),
            workers=_Coll(find_one=lambda q: {
                "_id": "w1", "osha_number": "OSHA-1", "certifications": [],
                "signature": None,
            }),
            compliance_alerts=_Coll([]),
        )

    def test_expired_sst_row_carries_all_five_fields(self):
        resp = _get(self._db())
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = resp.json()
        self.assertEqual(len(rows), 1, rows)
        r = rows[0]
        self.assertEqual(r["checkin_id"], "chk_1")
        self.assertEqual(r["sst_status"], "expired")
        self.assertIs(r["needs_trade_assignment"], False)
        self.assertIsNone(r["review_decision"])
        self.assertEqual(
            [w["type"] for w in r["cert_warnings"]], ["EXPIRED_SST"],
        )

    def test_unknown_sst_row_carries_status_and_warning(self):
        resp = _get(self._db(
            sst_status="unknown",
            cert_warnings=[{"type": "SST_UNKNOWN"}],
        ))
        r = resp.json()[0]
        self.assertEqual(r["sst_status"], "unknown")
        self.assertEqual([w["type"] for w in r["cert_warnings"]], ["SST_UNKNOWN"])
        self.assertEqual(r["checkin_id"], "chk_1")

    def test_needs_trade_assignment_is_surfaced(self):
        resp = _get(self._db(
            sst_status="valid", cert_warnings=[], needs_trade_assignment=True,
        ))
        r = resp.json()[0]
        self.assertIs(r["needs_trade_assignment"], True)
        self.assertEqual(r["checkin_id"], "chk_1")

    def test_review_decision_round_trips(self):
        """A reviewed row reports its decision — but the row is NOT removed.
        Deny marks, it never removes: the worker stays on the roster."""
        resp = _get(self._db(review_decision="sent_home"))
        rows = resp.json()
        self.assertEqual(len(rows), 1, "a denied worker must stay on the roster")
        self.assertEqual(rows[0]["review_decision"], "sent_home")

    def test_missing_flag_fields_default_safely(self):
        """Rows written before these fields existed must not 500 or lie."""
        db = self._db()
        db.checkins.docs = [{
            "_id": "chk_old", "worker_id": "w1", "worker_name": "Old Row",
            "check_in_time": TS, "is_deleted": False,
        }]
        r = _get(db).json()[0]
        self.assertEqual(r["checkin_id"], "chk_old")
        self.assertIsNone(r["sst_status"])
        self.assertIs(r["needs_trade_assignment"], False)
        self.assertIsNone(r["review_decision"])
        self.assertEqual(r["cert_warnings"], [])

    def test_existing_row_shape_preserved(self):
        """Additive only — every pre-existing key still ships."""
        r = _get(self._db()).json()[0]
        for key in (
            "worker_id", "worker_name", "company", "trade", "check_in_time",
            "osha_number", "certifications", "worker_signature", "signin_id",
            "source", "toolbox_talk_confirmed", "toolbox_talk_confirmed_at",
        ):
            self.assertIn(key, r, f"legacy key {key} disappeared from the row")
        self.assertEqual(r["source"], "legacy_checkin")


# ── PASS 1 — gate sign-ins have NO checkins row ──────────────────────────────
class TestGatePassHasNoCheckinId(unittest.TestCase):
    """The known complication, pinned.

    card_audit.py writes sign_ins + worker_enrollments and never touches
    `checkins`, so there is no id to review against. The endpoint must say so
    with null rather than invent one.
    """

    def _db(self):
        return _Db(
            projects=_Coll(find_one=lambda q: PROJECT),
            sign_ins=_Coll([{
                "_id": "si_1", "worker_enrollment_id": "enr_1",
                "project_id": "proj1", "timestamp": TS,
            }]),
            worker_enrollments=_Coll([{
                "_id": "enr_1", "worker_name": "Gate Gary",
                "sub_name": "Acme Co", "trade": "Laborer", "card_id": "SST-9",
            }]),
            daily_signatures=_Coll([]),
            checkins=_Coll([]),
            workers=_Coll(find_one=lambda q: None),
            compliance_alerts=_Coll([]),
        )

    def test_gate_row_reports_null_checkin_id_not_a_fabricated_one(self):
        with patch.object(server, "ObjectId", lambda v: v):
            rows = _get(self._db()).json()
        self.assertEqual(len(rows), 1, rows)
        r = rows[0]
        self.assertEqual(r["source"], "gate_checkin")
        self.assertIsNone(
            r["checkin_id"],
            "a gate sign-in has no checkins row — an id here would be invented",
        )
        # The worker_id on this row is the ENROLLMENT id; it must never be
        # mistaken for a checkin id.
        self.assertEqual(r["worker_id"], "enr_1")
        self.assertNotEqual(r["checkin_id"], r["worker_id"])

    def test_gate_row_carries_the_toolbox_keys_at_all(self):
        """DEVICE ROUND 4, finding 3 (second half).

        The two toolbox keys were ABSENT from this row — the legacy pass below
        emits them, this one did not — so the client read `undefined` and the
        toolbox roster's Confirmed column was unreachable for every gate-enrolled
        worker rather than merely false. Emitting them makes the two passes the
        same shape, which is what the roster builder assumes.
        """
        with patch.object(server, "ObjectId", lambda v: v):
            r = _get(self._db()).json()[0]
        self.assertIn("toolbox_talk_confirmed", r)
        self.assertIn("toolbox_talk_confirmed_at", r)

    def test_gate_row_toolbox_confirmation_is_false_and_says_why(self):
        """AND IT CANNOT YET BE TRUE, which is the honest part.

        The optional confirmation is offered on ONE path: checkin.html posts
        `toolbox_talk_confirm` to /checkin/register-and-checkin, which writes it
        onto a `checkins` row. card_audit.py — the card/enrollment path that
        produces THIS row — contains no reference to a toolbox confirmation at
        all: no control on the page, no field on the sign-in. So False here is a
        report of a gap, not a value read from a row, and this test pins the gap
        so closing it upstream is visible rather than silent.
        """
        with patch.object(server, "ObjectId", lambda v: v):
            r = _get(self._db()).json()[0]
        self.assertIs(r["toolbox_talk_confirmed"], False)
        self.assertIsNone(r["toolbox_talk_confirmed_at"])

        card_audit_src = (
            Path(server.__file__).parent / "card_audit.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            "toolbox", card_audit_src.lower(),
            "the enrollment path now mentions a toolbox confirmation — if it "
            "captures one, this row must READ it instead of hardcoding False",
        )

    def test_gate_row_reports_no_flag_state_rather_than_guessing(self):
        with patch.object(server, "ObjectId", lambda v: v):
            r = _get(self._db()).json()[0]
        self.assertIsNone(r["sst_status"])
        self.assertIs(r["needs_trade_assignment"], False)
        self.assertIsNone(r["review_decision"])
        self.assertEqual(r["cert_warnings"], [])


# ── PASS 3 — the blocked population, out of scope for actions ───────────────
class TestBlockedPassOffersNoAction(unittest.TestCase):
    def _db(self):
        return _Db(
            projects=_Coll(find_one=lambda q: PROJECT),
            sign_ins=_Coll([]),
            worker_enrollments=_Coll([]),
            daily_signatures=_Coll([]),
            checkins=_Coll([]),
            workers=_Coll(find_one=lambda q: None),
            compliance_alerts=_Coll([{
                "_id": "al_1", "alert_type": "CERT_BLOCK", "project_id": "proj1",
                "worker_id": "w9", "worker_name": "Blocked Ben",
                "worker_company": "Acme Co", "created_at": TS,
                "blocks": [{"type": "MISSING_OSHA"}],
            }]),
        )

    def test_blocked_row_has_null_checkin_id_and_keeps_blocked_flags(self):
        r = _get(self._db()).json()[0]
        self.assertEqual(r["source"], "cert_block")
        self.assertIs(r["blocked"], True)
        self.assertEqual(r["blocks"], ["MISSING_OSHA"])
        self.assertIsNone(
            r["checkin_id"],
            "a turned-away worker never reached the checkins insert",
        )
        self.assertIsNone(r["sst_status"])
        self.assertIs(r["needs_trade_assignment"], False)
        self.assertIsNone(r["review_decision"])
        self.assertEqual(r["cert_warnings"], [])


if __name__ == "__main__":
    unittest.main()
