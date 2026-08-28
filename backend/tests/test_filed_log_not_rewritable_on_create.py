"""A filed log's content is not rewritable — on the CREATE path too.

`update_logbook` has refused a `data` write onto a stored-`submitted` row since
#214 (409 FILED_LOG_DATA_IMMUTABLE). `create_logbook`'s upsert did not, and it
refused only `is_locked`. An END_OF_DAY log is `status: submitted,
is_locked: false` until the overnight sweep, so in that window a POST matched
the dedupe and `$set` over the filed record.

WHICH VERB THE CLIENT USED DECIDED WHETHER THE RECORD SURVIVED. A client that
can see the row holds its id and sends PUT (refused). A client that cannot —
the log invisible to it, or a read that failed — has no id, sends POST, and
destroyed it. The second device is exactly that client.

THE PREDICATE IS NOT PAYLOAD EMPTINESS, and the first test says so. The screen
rebuilds crews from the check-in roster before anything else, so the destroying
payload is fourteen keys with three populated crews in it — no `len(data) == 0`
check would ever have fired on the write that took the log.

Both directions, because a guard that refuses everything is as broken as one
that refuses nothing: the ordinary draft flow, the submit-through-create flow,
and the immediate-type freeze model all still pass.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402


PROJECT = {"_id": "projA", "name": "588 Thomas", "company_id": "co_a"}
CP = {
    "_id": "cp1", "id": "cp1", "role": "cp", "company_id": "co_a",
    "name": "Cara CP", "assigned_projects": ["projA"],
}
DATE = "2026-08-28"

SIGNATURE = {
    "paths": [[{"x": 1, "y": 2}]],
    "signed_at": f"{DATE}T18:00:00Z",
    "affirmed_at": f"{DATE}T18:00:00Z",
    "signer_name": "Cara CP",
    # AFFIRMED FOR THIS DOCUMENT — _is_affirmed_signature asks for exactly this
    # key and nothing weaker. Without it the submit gate refuses first and the
    # test never reaches the guard it is about.
    "affirmed": True,
}

# What the CP filed: three crews, each with work and photos.
FILED_DATA = {
    "activities": [
        {"company": "Arkon Builders", "trade": "Framers", "num_workers": 5,
         "work_description": "wall framing, blocking",
         "work_locations": "floor 3",
         "photos": [{"id": "p1", "original_r2_key": "k1"}]},
        {"company": "Power Direct", "trade": "Electrician", "num_workers": 6,
         "work_description": "rough-in", "work_locations": "floor 2",
         "photos": [{"id": "p2", "original_r2_key": "k2"}]},
    ],
    "observations": [{"text": "clear"}],
    "general_description": "Framing and electrical rough-in.",
    "checklist_items": {"fire_safety": True},
}

# What the SECOND DEVICE sends: the same shape, crews rebuilt from the gate
# roster, and nothing the CP typed. Fourteen keys, three populated crews —
# not an empty object, which is the whole point.
EMPTY_EDITOR_DATA = {
    "activities": [
        {"company": "Arkon Builders", "trade": "Framers", "num_workers": 5,
         "work_description": "", "work_locations": "", "photos": []},
        {"company": "Power Direct", "trade": "Electrician", "num_workers": 6,
         "work_description": "", "work_locations": "", "photos": []},
    ],
    "observations": [],
    "general_description": "",
    "checklist_items": {},
}


def _row(status="submitted", is_locked=False, log_type="daily_jobsite", data=None):
    return {
        "_id": "lb1", "project_id": "projA", "company_id": "co_a",
        "log_type": log_type, "date": DATE,
        "data": FILED_DATA if data is None else data,
        "cp_signature": SIGNATURE, "cp_name": "Cara CP",
        "status": status, "is_locked": is_locked, "is_deleted": False,
        "is_amendment": False,
    }


def _match(doc, query):
    for key, cond in (query or {}).items():
        value = doc.get(key)
        if isinstance(cond, dict):
            if "$ne" in cond and value == cond["$ne"]:
                return False
            if "$in" in cond and value not in cond["$in"]:
                return False
        elif isinstance(value, list):
            if cond not in value:
                return False
        elif value != cond:
            return False
    return True


class _Coll:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
        self.updates = []
        self.inserted = []

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _match(d, query):
                return dict(d)
        return None

    async def count_documents(self, query=None, *a, **k):
        return len([d for d in self.docs if _match(d, query)])

    async def update_one(self, query, update, *a, **k):
        self.updates.append((query, update))

        class _R:
            matched_count = 1
        return _R()

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))

        class _R:
            inserted_id = "lb_new"
        return _R()


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())


def _db(rows=None):
    return _Db(projects=_Coll([PROJECT]), logbooks=_Coll(rows or []))


async def _noop(*a, **k):
    return None


def _post(db, *, data, status="submitted", log_type="daily_jobsite"):
    payload = server.LogbookCreate(
        project_id="projA", log_type=log_type, date=DATE, data=data,
        cp_signature=SIGNATURE, cp_name="Cara CP", status=status,
    )
    with patch.object(server, "db", db), \
            patch.object(server, "to_query_id", lambda v: v), \
            patch.object(server, "_enhance_logbook_photos", _noop), \
            patch.object(server, "_remember_other_activities", _noop), \
            patch.object(server, "audit_log", _noop):
        return asyncio.run(server.create_logbook(payload, CP))


def _status(fn, *a, **k):
    try:
        fn(*a, **k)
    except HTTPException as exc:
        return exc.status_code, exc.detail
    return 200, None


# ------------------------------------------------------------- refused ------

class TestCreateRefusesAWriteOntoAFiledRow(unittest.TestCase):
    def test_the_second_devices_empty_editor_is_refused(self):
        """The write that took the log. Note the payload is NOT empty."""
        db = _db([_row(status="submitted")])
        code, detail = _status(_post, db, data=EMPTY_EDITOR_DATA)
        self.assertEqual(code, 409)
        self.assertEqual(detail, {"code": "FILED_LOG_DATA_IMMUTABLE"})

    def test_a_refused_write_mutates_nothing(self):
        db = _db([_row(status="submitted")])
        _status(_post, db, data=EMPTY_EDITOR_DATA)
        self.assertEqual(db.logbooks.updates, [])
        self.assertEqual(db.logbooks.inserted, [])
        self.assertEqual(db.logbooks.docs[0]["data"], FILED_DATA)

    def test_a_payload_emptiness_check_would_not_have_fired(self):
        """Stated as its own case because it is the reason the predicate is the
        stored STATUS and not the size of `data`."""
        self.assertNotEqual(EMPTY_EDITOR_DATA, {})
        self.assertGreater(len(EMPTY_EDITOR_DATA), 1)
        self.assertTrue(EMPTY_EDITOR_DATA["activities"])
        self.assertTrue(all(not a["work_description"]
                            for a in EMPTY_EDITOR_DATA["activities"]))

    def test_a_full_payload_is_refused_too(self):
        """Not a loss check. A filed day is not rewritable by a fuller day
        either — that is what amendment is for."""
        db = _db([_row(status="submitted")])
        code, _ = _status(_post, db, data=dict(FILED_DATA, general_description="more"))
        self.assertEqual(code, 409)

    def test_same_code_as_the_update_path(self):
        """One condition, one code, whichever verb the client used."""
        import inspect
        create = inspect.getsource(server.create_logbook)
        update = inspect.getsource(server.update_logbook)
        self.assertIn("FILED_LOG_DATA_IMMUTABLE", create)
        self.assertIn("FILED_LOG_DATA_IMMUTABLE", update)
        self.assertIn('"status") == "submitted"', create)


# ------------------------------------------------------------- allowed ------

class TestTheOrdinaryFlowsStillPass(unittest.TestCase):
    def test_a_draft_row_still_upserts(self):
        """Save, edit, save again — the ordinary path, untouched."""
        db = _db([_row(status="draft")])
        out = _post(db, data=FILED_DATA, status="draft")
        self.assertEqual(len(db.logbooks.updates), 1)
        self.assertIsNotNone(out)

    def test_submitting_a_draft_through_create_still_passes(self):
        """The predicate is the STORED status. A draft being submitted sends
        data and status together and must land."""
        db = _db([_row(status="draft")])
        _post(db, data=FILED_DATA, status="submitted")
        _query, update = db.logbooks.updates[0]
        self.assertEqual(update["$set"]["status"], "submitted")

    def test_a_first_filing_still_inserts(self):
        db = _db([])
        _post(db, data=FILED_DATA, status="submitted")
        self.assertEqual(len(db.logbooks.inserted), 1)
        self.assertEqual(db.logbooks.inserted[0]["status"], "submitted")

    def test_a_locked_immediate_type_still_mints_the_next_instance(self):
        """The freeze model. A locked immediate row falls out of the dedupe, so
        the second scaffold inspection of the day inserts rather than being
        refused — this guard must not reach it."""
        db = _db([_row(status="submitted", is_locked=True,
                       log_type="scaffold_maintenance")])
        _post(db, data=FILED_DATA, status="submitted",
              log_type="scaffold_maintenance")
        self.assertEqual(len(db.logbooks.inserted), 1)
        self.assertEqual(db.logbooks.updates, [])

    def test_a_locked_end_of_day_row_is_still_the_423(self):
        """Once the sweep freezes it, the older refusal is the one that fires."""
        db = _db([_row(status="submitted", is_locked=True)])
        code, _ = _status(_post, db, data=FILED_DATA)
        self.assertEqual(code, 423)


if __name__ == "__main__":
    unittest.main()
