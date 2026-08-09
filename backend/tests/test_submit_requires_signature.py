"""POST /logbooks and PUT /logbooks/{id} — the submit gate.

For the nine IMMEDIATE log types the SIGNATURE IS THE FREEZE: both endpoints set
`is_locked` from `status == "submitted"` alone. Before this gate, a request
carrying status="submitted" with no cp_signature minted a LOCKED, UNSIGNED legal
record that could only ever be corrected by an amendment.

BOTH endpoints, not just create. The ordinary CP flow is Save Draft (POST,
status=draft) then Submit — and because the log already exists by then, Submit
arrives as a PUT. A gate on create alone would never see the path the CP
actually walks.

WHAT THIS GATE DOES NOT DO — stated here because the previous round's tests hid
exactly this. It is a PRESENCE check, matching the finalize gate. Every fixture
below is the REAL payload its form produces when untouched, read off each
form's `const data = {...}` and its initial useState. Those payloads are
non-empty DICTS full of blank VALUES, so SUBMIT_EMPTY_LOG does not fire for any
of them — and there are explicit tests asserting that, so the limit is recorded
rather than discovered later on a jobsite. Closing the blank-content case needs
a per-form minimum-content list, which is the operator's knowledge and is
deliberately out of scope.
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


# ── the nine IMMEDIATE types, and the payload each form ACTUALLY sends ───────
#
# Read from frontend/app/logbooks/<form>.jsx — the `const data = {...}` (or the
# inline `data: {...}`) at each form's save site, with every field at its
# initial useState value. NOT simplified: the point of these fixtures is that
# they are non-empty dicts of blank values, which is what a real untouched
# submit looks like on a phone.
UNTOUCHED_PAYLOADS = {
    # preshift_signin.jsx — `data: {...}` at the writeDraft site
    "preshift_signin": {
        "company": "", "project_location": "", "workers": [], "total_count": 0,
    },
    # toolbox_talk.jsx
    "toolbox_talk": {
        "location": "", "company_name": "", "type_of_work": "",
        "meeting_time": "", "performed_by": "", "checked_topics": {},
        "attendees": [],
    },
    # subcontractor_orientation.jsx
    "subcontractor_orientation": {
        "worker_id": None, "worker_name": "", "worker_company": "",
        "worker_trade": "", "osha_number": "", "orientation_number": "",
        "checklist": {}, "completed_at": "2026-08-09T12:00:00.000Z",
        "worker_signature": None, "language_provided": "en",
    },
    # osha_log.jsx — `data: { entries }`
    "osha_log": {"entries": []},
    # scaffold_maintenance.jsx — `const data = { general_info, answers }`
    "scaffold_maintenance": {"general_info": {}, "answers": {}},
    # hot_work.jsx
    "hot_work": {
        "work_type": "", "location": "", "worker_name": "",
        "worker_cert_number": "", "start_time": "", "end_time": "",
        "fire_watch_end_time": "", "fire_watch_name": "", "precautions": {},
    },
    # concrete_operations.jsx
    "concrete_operations": {
        "pour_location": "", "concrete_supplier": "", "mix_design": "",
        "volume_ordered": "", "slump_tests": [], "formwork_checklist": {},
        "weather_conditions": "", "temperature": "",
    },
    # crane_operations.jsx
    "crane_operations": {
        "crane_type": "", "crane_id": "", "operator_name": "",
        "operator_license": "", "pre_operation_checklist": {},
        "load_entries": [],
    },
    # excavation_monitoring.jsx
    "excavation_monitoring": {
        "excavation_depth": "", "soil_type": "", "adjacent_buildings": [],
        "vibration_threshold": "", "vibration_current": "",
        "vibration_over_threshold": False, "protection_system": "",
        "groundwater_observed": False, "atmospheric_testing": {},
    },
}

# daily_jobsite is END_OF_DAY, not immediate — it does not auto-lock on submit.
# Its untouched payload is here because it is the exact shape the operator
# submitted blank on production: nine keys, auto-filled address/weather, and one
# seed activity row carrying a generated activity_id.
DAILY_JOBSITE_UNTOUCHED = {
    "project_address": "8 Walworth St, Brooklyn, NY",
    "weather": "Clear", "weather_temp": "72F", "weather_wind": "5 mph",
    "general_description": "",
    "activities": [{
        "activity_id": "act_1754000000000_1", "subcontractor_id": None,
        "crew_id": "", "company": "", "num_workers": "",
        "work_description": "", "work_locations": "", "photos": [],
    }],
    "equipment_on_site": {}, "checklist_items": {}, "observations": [],
}

_SIG = {"paths": [[1, 2]], "signed_at": "2026-08-09T12:00:00Z"}


class _Result:
    def __init__(self, _id="x"):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
        self.inserted = []
        self.updated = []

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query or {}) if callable(v) else v

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))
        return _Result()

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result()

    async def count_documents(self, *a, **k):
        return 0

    def find(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return []


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


def _db_for_create():
    """No existing log (dedupe misses), project exists."""
    db = _FakeDb()
    db.projects.set_find_one(lambda q: {"_id": "proj1", "name": "8 Walworth"})
    db.logbooks.set_find_one(lambda q: None)
    return db


def _db_for_update(stored):
    db = _FakeDb()
    db.projects.set_find_one(lambda q: {"_id": "proj1", "name": "8 Walworth"})
    db.logbooks.set_find_one(lambda q: stored)
    return db


def _user(role="cp"):
    return {
        "_id": "u1", "id": "u1", "role": role, "company_id": "co_a",
        "full_name": "Carl CP", "assigned_projects": ["proj1"],
    }


def _post(db, body, role="cp"):
    async def _fake_user():
        return _user(role)

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            return TestClient(server.app).post("/api/logbooks", json=body)
    finally:
        server.app.dependency_overrides.clear()


def _put(db, body, role="cp", log_id="lb1"):
    async def _fake_user():
        return _user(role)

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            return TestClient(server.app).put(f"/api/logbooks/{log_id}", json=body)
    finally:
        server.app.dependency_overrides.clear()


def _create_body(log_type, *, status, signature, data=None):
    return {
        "project_id": "proj1",
        "log_type": log_type,
        "date": "2026-08-09",
        "data": UNTOUCHED_PAYLOADS[log_type] if data is None else data,
        "cp_signature": signature,
        "cp_name": "Carl CP",
        "status": status,
    }


class AllNineImmediateTypesCannotLockUnsigned(unittest.TestCase):
    """The headline rule, asserted per type rather than once on a stand-in."""

    def test_every_immediate_type_is_rejected_unsigned_on_create(self):
        for log_type in UNTOUCHED_PAYLOADS:
            with self.subTest(log_type=log_type):
                self.assertTrue(
                    server.is_immediate_preshift(log_type),
                    f"{log_type} is supposed to be an IMMEDIATE type",
                )
                db = _db_for_create()
                resp = _post(db, _create_body(log_type, status="submitted", signature=None))
                self.assertEqual(resp.status_code, 400, resp.text)
                self.assertEqual(
                    resp.json()["detail"]["code"], "SUBMIT_MISSING_CP_SIGNATURE"
                )

    def test_every_immediate_type_is_rejected_unsigned_on_update(self):
        for log_type in UNTOUCHED_PAYLOADS:
            with self.subTest(log_type=log_type):
                stored = {
                    "_id": "lb1", "project_id": "proj1", "log_type": log_type,
                    "date": "2026-08-09", "data": UNTOUCHED_PAYLOADS[log_type],
                    "cp_signature": None, "is_locked": False,
                }
                db = _db_for_update(stored)
                resp = _put(db, {"status": "submitted"})
                self.assertEqual(resp.status_code, 400, resp.text)
                self.assertEqual(
                    resp.json()["detail"]["code"], "SUBMIT_MISSING_CP_SIGNATURE"
                )

    def test_a_rejected_submit_writes_nothing_at_all(self):
        db = _db_for_create()
        _post(db, _create_body("hot_work", status="submitted", signature=None))
        self.assertEqual(db.logbooks.inserted, [], "a refused submit must not insert")
        self.assertEqual(db.logbooks.updated, [], "a refused submit must not update")

    def test_a_rejected_update_writes_nothing_at_all(self):
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": "hot_work",
            "date": "2026-08-09", "data": UNTOUCHED_PAYLOADS["hot_work"],
            "cp_signature": None, "is_locked": False,
        }
        db = _db_for_update(stored)
        _put(db, {"status": "submitted"})
        self.assertEqual(db.logbooks.updated, [], "a refused submit must not update")


class SignedSubmitsStillWork(unittest.TestCase):
    """The gate must not cost a CP who did everything right."""

    def test_signed_submit_creates_and_locks(self):
        db = _db_for_create()
        resp = _post(db, _create_body("hot_work", status="submitted", signature=_SIG))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.logbooks.inserted), 1)
        self.assertTrue(db.logbooks.inserted[0]["is_locked"])

    def test_signed_submit_updates_and_locks(self):
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": "hot_work",
            "date": "2026-08-09", "data": UNTOUCHED_PAYLOADS["hot_work"],
            "cp_signature": None, "is_locked": False,
        }
        db = _db_for_update(stored)
        resp = _put(db, {"status": "submitted", "cp_signature": _SIG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(db.logbooks.updated)
        self.assertTrue(db.logbooks.updated[0][1]["$set"]["is_locked"])

    def test_update_uses_the_STORED_signature_when_the_request_omits_it(self):
        """LogbookUpdate's fields are all Optional. A submit that does not
        re-send an already-stored signature is signed, and must be accepted —
        judging the request alone would reject a properly signed log."""
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": "hot_work",
            "date": "2026-08-09", "data": UNTOUCHED_PAYLOADS["hot_work"],
            "cp_signature": _SIG, "is_locked": False,
        }
        db = _db_for_update(stored)
        resp = _put(db, {"status": "submitted"})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_update_uses_the_STORED_data_when_the_request_omits_it(self):
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": "hot_work",
            "date": "2026-08-09", "data": UNTOUCHED_PAYLOADS["hot_work"],
            "cp_signature": _SIG, "is_locked": False,
        }
        db = _db_for_update(stored)
        self.assertEqual(_put(db, {"status": "submitted"}).status_code, 200)


class DraftsAreNotGated(unittest.TestCase):
    """A draft is allowed to be empty and unsigned — that is what a draft is."""

    def test_unsigned_draft_create_is_accepted(self):
        for log_type in UNTOUCHED_PAYLOADS:
            with self.subTest(log_type=log_type):
                db = _db_for_create()
                resp = _post(db, _create_body(log_type, status="draft", signature=None))
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertFalse(db.logbooks.inserted[0]["is_locked"])

    def test_completely_empty_unsigned_draft_is_accepted(self):
        db = _db_for_create()
        resp = _post(db, _create_body("hot_work", status="draft", signature=None, data={}))
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_unsigned_draft_update_is_accepted(self):
        stored = {
            "_id": "lb1", "project_id": "proj1", "log_type": "hot_work",
            "date": "2026-08-09", "data": {}, "cp_signature": None,
            "is_locked": False,
        }
        db = _db_for_update(stored)
        self.assertEqual(_put(db, {"status": "draft"}).status_code, 200)


class StructurallyEmptySubmits(unittest.TestCase):
    """Matching the finalize gate: {} and a missing key are refused."""

    def test_empty_dict_submit_is_rejected(self):
        db = _db_for_create()
        resp = _post(db, _create_body("hot_work", status="submitted", signature=_SIG, data={}))
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "SUBMIT_EMPTY_LOG")

    def test_empty_beats_unsigned_when_both_are_wrong(self):
        """Ordering is deliberate and pinned: the emptier problem is named
        first, so a CP fixes content before being sent to sign."""
        db = _db_for_create()
        resp = _post(db, _create_body("hot_work", status="submitted", signature=None, data={}))
        self.assertEqual(resp.json()["detail"]["code"], "SUBMIT_EMPTY_LOG")

    def test_false_and_zero_are_CONTENT_not_emptiness(self):
        """A checklist answered "no" is answered. Treating False or 0 as blank
        would throw away real answers, so the check is on the DICT, never on
        the truthiness of the values inside it."""
        for payload in ({"all_clear": False}, {"worker_count": 0}, {"x": None}):
            with self.subTest(payload=payload):
                db = _db_for_create()
                resp = _post(
                    db, _create_body("hot_work", status="submitted", signature=_SIG, data=payload)
                )
                self.assertEqual(resp.status_code, 200, resp.text)


class TheBlankContentHoleIsStillOpen(unittest.TestCase):
    """RECORDED, NOT FIXED.

    These assert the gate's LIMIT. Every payload here is the real shape a form
    sends when the CP has touched nothing, and every one of them is accepted
    once signed. That is the operator's ruling — presence only, per-form
    minimum content deferred — and it is pinned here so the next person reads
    the boundary in a test instead of finding it on a jobsite.
    """

    def test_untouched_payloads_are_non_empty_dicts(self):
        for log_type, payload in UNTOUCHED_PAYLOADS.items():
            with self.subTest(log_type=log_type):
                self.assertTrue(
                    payload, f"{log_type}'s untouched payload is falsy — "
                    "if this ever becomes true the empty gate starts catching it"
                )

    def test_a_signed_but_untouched_submit_is_ACCEPTED(self):
        for log_type in UNTOUCHED_PAYLOADS:
            with self.subTest(log_type=log_type):
                db = _db_for_create()
                resp = _post(db, _create_body(log_type, status="submitted", signature=_SIG))
                self.assertEqual(
                    resp.status_code, 200,
                    "this branch does NOT close the blank-content case",
                )

    def test_the_daily_jobsite_log_the_operator_filed_blank_is_still_accepted(self):
        """The exact production case. Auto-filled address and weather, one seed
        activity row with a generated activity_id, everything the CP would type
        left blank. Non-empty by construction, so a presence gate cannot see it."""
        db = _db_for_create()
        resp = _post(db, {
            "project_id": "proj1", "log_type": "daily_jobsite", "date": "2026-08-09",
            "data": DAILY_JOBSITE_UNTOUCHED, "cp_signature": _SIG,
            "cp_name": "Carl CP", "status": "submitted",
        })
        self.assertEqual(resp.status_code, 200, resp.text)


class TheGateAppliesToEveryType(unittest.TestCase):
    """Not scoped to the immediate nine. An END_OF_DAY log does not auto-lock,
    but an unsigned SUBMITTED record is wrong for it too, and finalize would
    refuse it seconds later anyway."""

    def test_daily_jobsite_unsigned_submit_is_rejected(self):
        db = _db_for_create()
        resp = _post(db, {
            "project_id": "proj1", "log_type": "daily_jobsite", "date": "2026-08-09",
            "data": DAILY_JOBSITE_UNTOUCHED, "cp_signature": None,
            "cp_name": "Carl CP", "status": "submitted",
        })
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "SUBMIT_MISSING_CP_SIGNATURE")

    def test_daily_jobsite_is_not_an_immediate_type(self):
        self.assertFalse(server.is_immediate_preshift("daily_jobsite"))


class RejectionShape(unittest.TestCase):
    """A machine code and no prose — the client owns the wording."""

    def test_detail_is_a_code_with_no_english_prose(self):
        db = _db_for_create()
        detail = _post(
            db, _create_body("hot_work", status="submitted", signature=None)
        ).json()["detail"]
        self.assertIsInstance(detail, dict)
        self.assertEqual(list(detail.keys()), ["code"])

    def test_both_codes_have_bilingual_copy(self):
        """A code with no EN/ES entry renders as the generic message, which
        tells the CP nothing about what to fix."""
        root = _BACKEND.parent / "frontend" / "src" / "i18n"
        for locale in ("en", "es"):
            text = (root / f"{locale}.js").read_text(encoding="utf-8")
            for code in ("SUBMIT_EMPTY_LOG", "SUBMIT_MISSING_CP_SIGNATURE"):
                with self.subTest(locale=locale, code=code):
                    self.assertIn(f"code_{code}:", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
