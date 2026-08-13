"""GET /logbooks/project/{id}/checkins-today — the opt-in roster envelope.

WHY THIS EXISTS. The endpoint runs three passes and each one swallows its own
failure: pass 1 logs a warning, passes 2 and 3 fall back to an empty list. It
then returns a BARE LIST, so a caller cannot tell "nobody else was on site"
from "a query failed and those men are missing". The daily jobsite stepper
builds a SIGNED compliance record off that roster, and a CP attesting to a
short list is attesting to a jobsite that did not exist.

`?envelope=1` reports what the bare list never could. The bare shape is
UNCHANGED and pinned below, because three screens already parse it
(osha_log.jsx, preshift_signin.jsx, toolbox_talk.jsx) and none of them should
have to change to add a capability they do not use.

The `collapsed` counter is the subtle one. The (name, company) dedupe guard in
passes 2 and 3 normally drops a duplicate of the SAME man. But WorkerEnrollment
carries no worker_id (card_audit.py:272-290), so the gate and legacy id spaces
have no join key, and that guard cannot tell a duplicate apart from two
different men who share a name at one subcontractor. The drop is therefore
counted rather than silently taken.
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


class _RaisingColl(_Coll):
    """A collection whose reads blow up — the degraded-pass case."""

    def find(self, query=None, *a, **k):
        raise RuntimeError("simulated read failure")


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())


def _get(db, envelope=False):
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    client = TestClient(server.app)
    qs = f"?date={DAY}" + ("&envelope=1" if envelope else "")
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v):
            return client.get(f"/api/logbooks/project/proj1/checkins-today{qs}")
    finally:
        server.app.dependency_overrides.clear()


def _worker_doc(_q=None):
    return {"_id": "w1", "osha_number": "OSHA-1", "certifications": [],
            "signature": None}


def _legacy_row(**over):
    row = {
        "_id": "chk_1", "worker_id": "w1", "worker_name": "Bob Builder",
        "worker_company": "Acme Co", "worker_trade": "Carpenter",
        "check_in_time": TS, "is_deleted": False, "sst_status": "valid",
        "needs_trade_assignment": False, "review_decision": None,
        "cert_warnings": [],
    }
    row.update(over)
    return row


def _db(sign_ins=None, enrollments=None, checkins=None, alerts=None,
        raise_on=None):
    def _c(name, docs):
        return _RaisingColl() if raise_on == name else _Coll(docs or [])
    return _Db(
        projects=_Coll(find_one=lambda q: PROJECT),
        sign_ins=_c("sign_ins", sign_ins),
        worker_enrollments=_Coll(enrollments or []),
        daily_signatures=_Coll([]),
        checkins=_c("checkins", checkins),
        workers=_Coll(find_one=_worker_doc),
        compliance_alerts=_c("compliance_alerts", alerts),
    )


class TestBareShapeUnchanged(unittest.TestCase):
    """The three existing consumers must see exactly what they always saw."""

    def test_default_is_still_a_bare_list(self):
        resp = _get(_db(checkins=[_legacy_row()]))
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIsInstance(body, list, "default response must stay a list")
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["worker_name"], "Bob Builder")

    def test_envelope_carries_the_identical_rows(self):
        bare = _get(_db(checkins=[_legacy_row()])).json()
        wrapped = _get(_db(checkins=[_legacy_row()]), envelope=True).json()
        self.assertEqual(wrapped["workers"], bare,
                         "envelope must not alter the rows themselves")


class TestCleanRosterIsNotPartial(unittest.TestCase):
    def test_healthy_read_reports_complete(self):
        body = _get(_db(checkins=[_legacy_row()]), envelope=True).json()
        self.assertIs(body["partial"], False)
        self.assertEqual(body["degraded_passes"], [])
        self.assertEqual(body["truncated_passes"], [])
        self.assertEqual(body["collapsed"], 0)

    def test_genuinely_empty_day_is_complete_not_partial(self):
        """An empty jobsite must NOT warn — that would train the CP to ignore
        the warning on the day it is real."""
        body = _get(_db(), envelope=True).json()
        self.assertEqual(body["workers"], [])
        self.assertIs(body["partial"], False)


class TestDegradedPassIsReported(unittest.TestCase):
    def test_legacy_read_failure_marks_partial(self):
        body = _get(_db(raise_on="checkins"), envelope=True).json()
        self.assertIs(body["partial"], True)
        self.assertIn("legacy", body["degraded_passes"])

    def test_blocked_read_failure_marks_partial(self):
        body = _get(_db(raise_on="compliance_alerts"), envelope=True).json()
        self.assertIs(body["partial"], True)
        self.assertIn("blocked", body["degraded_passes"])

    def test_gate_read_failure_marks_partial(self):
        body = _get(_db(raise_on="sign_ins"), envelope=True).json()
        self.assertIs(body["partial"], True)
        self.assertIn("gate", body["degraded_passes"])

    def test_a_failed_pass_still_returns_the_others(self):
        """Degradation must not be fatal — the men we DO know about still
        reach the CP, they are just labelled incomplete."""
        body = _get(_db(checkins=[_legacy_row()], raise_on="compliance_alerts"),
                    envelope=True).json()
        self.assertEqual(len(body["workers"]), 1)
        self.assertIs(body["partial"], True)

    def test_bare_caller_is_unaffected_by_degradation(self):
        """The legacy shape has nowhere to put the signal; it must still 200
        with the rows it has rather than start erroring on old callers."""
        resp = _get(_db(checkins=[_legacy_row()], raise_on="compliance_alerts"))
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)


class TestCollapseIsCounted(unittest.TestCase):
    """Two men, one name, one sub — one of them vanishes. It is counted."""

    def _same_name_in_both_systems(self):
        return _db(
            sign_ins=[{"_id": "si1", "worker_enrollment_id": "e1",
                       "timestamp": TS}],
            enrollments=[{"_id": "e1", "worker_name": "Luis Alvarez",
                          "sub_name": "Vanguard", "trade": "Concrete",
                          "card_id": "CARD-1"}],
            checkins=[_legacy_row(worker_id="w9", worker_name="Luis Alvarez",
                                  worker_company="Vanguard")],
        )

    def test_collapsed_row_is_counted_and_marks_partial(self):
        body = _get(self._same_name_in_both_systems(), envelope=True).json()
        self.assertEqual(len(body["workers"]), 1,
                         "the guard still drops the row — behaviour unchanged")
        self.assertEqual(body["collapsed"], 1,
                         "but the drop is now REPORTED, not silent")
        self.assertIs(body["partial"], True)

    def test_distinct_names_do_not_collapse(self):
        body = _get(_db(
            sign_ins=[{"_id": "si1", "worker_enrollment_id": "e1",
                       "timestamp": TS}],
            enrollments=[{"_id": "e1", "worker_name": "Luis Alvarez",
                          "sub_name": "Vanguard", "trade": "Concrete",
                          "card_id": "CARD-1"}],
            checkins=[_legacy_row(worker_name="Marta Reyes",
                                  worker_company="Vanguard")],
        ), envelope=True).json()
        self.assertEqual(len(body["workers"]), 2)
        self.assertEqual(body["collapsed"], 0)
        self.assertIs(body["partial"], False)

    def test_two_gate_workers_sharing_a_name_both_survive(self):
        """Pass 1 keys on the enrollment id, which is unique per card
        (worker_enrollments has a unique index on project_id+card_id), so the
        gate pass never had this defect and must not acquire one."""
        body = _get(_db(
            sign_ins=[{"_id": "si1", "worker_enrollment_id": "e1",
                       "timestamp": TS},
                      {"_id": "si2", "worker_enrollment_id": "e2",
                       "timestamp": TS}],
            enrollments=[{"_id": "e1", "worker_name": "Luis Alvarez",
                          "sub_name": "Vanguard", "trade": "Concrete",
                          "card_id": "CARD-1"},
                         {"_id": "e2", "worker_name": "Luis Alvarez",
                          "sub_name": "Vanguard", "trade": "Concrete",
                          "card_id": "CARD-2"}],
        ), envelope=True).json()
        self.assertEqual(len(body["workers"]), 2,
                         "both men must appear — they carry different cards")
        self.assertEqual(body["collapsed"], 0)


class TestTheSameManIsNeverListedTwice(unittest.TestCase):
    """THE PRODUCTION DUPLICATE, reproduced from the stored roster.

    Project 6a5f63bc147407d3261df2c7, preshift_signin, 2026-08-12:
    worker_id 6a79b9f19d8cee518e4712c4 appeared TWICE in data.workers — once
    complete (company "AAZ", OSHA number, signature) and once stripped of all
    three. Both rows carried auto_filled: true, so both came from
    buildWorkerList, i.e. from this endpoint. There were ZERO
    worker_enrollments for him, so pass 1 never ran.

    The cause was pass 3: a CERT_BLOCK alert carries no worker_company, so its
    key was ('wilmer carrillo', '') against pass 2's ('wilmer carrillo', 'aaz').
    A miss, and the same man was emitted again.
    """

    WID = "6a79b9f19d8cee518e4712c4"

    def test_a_blocked_alert_with_no_company_does_not_re_emit_him(self):
        body = _get(_db(
            checkins=[_legacy_row(worker_id=self.WID,
                                  worker_name="WILMER CARRILLO",
                                  worker_company="AAZ")],
            alerts=[{"_id": "al1", "alert_type": "CERT_BLOCK",
                     "worker_id": self.WID, "worker_name": "WILMER CARRILLO",
                     "worker_company": ""}],          # <- the empty company
        ), envelope=True).json()
        ids = [w["worker_id"] for w in body["workers"]]
        self.assertEqual(ids.count(self.WID), 1,
                         "the same worker_id was emitted twice")
        self.assertEqual(len(body["workers"]), 1)
        self.assertEqual(body["collapsed"], 1, "the drop is reported, not silent")

    def test_the_row_that_SURVIVES_is_the_complete_one(self):
        """Pass 2 runs first and carries the company, the OSHA number and the
        signature. Dropping IT and keeping the stripped alert row would be a
        worse document than the duplicate."""
        body = _get(_db(
            checkins=[_legacy_row(worker_id=self.WID,
                                  worker_name="WILMER CARRILLO",
                                  worker_company="AAZ")],
            alerts=[{"_id": "al1", "alert_type": "CERT_BLOCK",
                     "worker_id": self.WID, "worker_name": "WILMER CARRILLO",
                     "worker_company": ""}],
        ), envelope=True).json()
        row = body["workers"][0]
        self.assertEqual(row["company"], "AAZ")
        self.assertTrue(row.get("osha_number"))

    def test_a_company_MISMATCH_no_longer_splits_him_either(self):
        """The id wins over the string, so "AAZ" against "AAZ Construction" —
        one of the paths reported as still open — is closed too whenever both
        rows carry the same worker_id."""
        body = _get(_db(
            checkins=[_legacy_row(worker_id=self.WID,
                                  worker_name="WILMER CARRILLO",
                                  worker_company="AAZ")],
            alerts=[{"_id": "al1", "alert_type": "CERT_BLOCK",
                     "worker_id": self.WID, "worker_name": "Wilmer J Carrillo",
                     "worker_company": "AAZ Construction"}],
        ), envelope=True).json()
        self.assertEqual(len(body["workers"]), 1)

    def test_two_different_men_sharing_a_name_are_NOT_collapsed_by_the_id(self):
        """The whole point of preferring the id: different men have different
        worker_ids, so the safer key cannot delete a worker."""
        body = _get(_db(
            checkins=[_legacy_row(_id="c1", worker_id="w_one",
                                  worker_name="Luis Alvarez",
                                  worker_company="Vanguard"),
                      _legacy_row(_id="c2", worker_id="w_two",
                                  worker_name="Luis Alvarez",
                                  worker_company="Ironworks")],
        ), envelope=True).json()
        self.assertEqual(len(body["workers"]), 2)

    def test_a_row_with_NO_id_still_falls_back_to_the_string_key(self):
        """A gate-sourced alert can carry no worker_id at all; the old guard
        remains for exactly that row."""
        body = _get(_db(
            checkins=[_legacy_row(worker_id="w_one", worker_name="Marta Reyes",
                                  worker_company="Vanguard")],
            alerts=[{"_id": "al1", "alert_type": "CERT_BLOCK",
                     "worker_id": None, "worker_name": "Marta Reyes",
                     "worker_company": "Vanguard"}],
        ), envelope=True).json()
        self.assertEqual(len(body["workers"]), 1)


class TestTruncationIsReported(unittest.TestCase):
    def test_legacy_ceiling_marks_partial(self):
        rows = [_legacy_row(_id=f"chk_{i}", worker_id=f"w{i}",
                            worker_name=f"Worker {i}") for i in range(500)]
        body = _get(_db(checkins=rows), envelope=True).json()
        self.assertIn("legacy", body["truncated_passes"])
        self.assertIs(body["partial"], True)

    def test_below_the_ceiling_is_not_truncated(self):
        rows = [_legacy_row(_id=f"chk_{i}", worker_id=f"w{i}",
                            worker_name=f"Worker {i}") for i in range(3)]
        body = _get(_db(checkins=rows), envelope=True).json()
        self.assertEqual(body["truncated_passes"], [])
        self.assertIs(body["partial"], False)


if __name__ == "__main__":
    unittest.main()
