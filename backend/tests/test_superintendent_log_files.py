"""THE CONSTRUCTION SUPERINTENDENT LOG IS ACTUALLY FILED — through the endpoint.

A CS filled the BC 3301.13.13 log on production, submitted it, saw no error, and
`db.logbooks.countDocuments({log_type: "site_superintendent_log"})` returned ZERO
across every project. The editor had shipped that day and had never successfully
filed anything.

NOTHING IN THIS SUITE WOULD HAVE CAUGHT THAT. test_superintendent_log.py holds no
TestClient at all: it tests the item vocabulary, the sunset dates and the three
kinds of empty, and every one of its assertions passes on a system that files
nothing. Every other log type that a CP can file has a test that drives the real
endpoint; this one, the only STATUTORY record signed under a DOB licence, did
not. So this file drives POST /api/logbooks and asks the only question that
matters afterwards: IS THERE A DOCUMENT.

── WHAT THIS FILE ESTABLISHES, AND WHICH HALF WAS BROKEN ────────────────────────

1. A complete, attested submit LANDS. 200, one row, status submitted, and the
   visit-class contract honoured: create leaves it unlocked and the author's
   finalize is what seals it. This half already worked, and it is written down
   here because an endpoint with no test is one refactor from silence.

2. A 200 MUST CARRY AN ID. This half did not work, and it is the silent-loss
   mechanism. create_logbook ends:

       result = await db.logbooks.insert_one(doc)
       created = await db.logbooks.find_one({"_id": result.inserted_id})
       ...
       return serialize_id(created)

   `serialize_id(None)` is None, which FastAPI renders as HTTP 200 with the body
   `null`. A read that does not see its own write -- a secondary that has not
   caught up is the ordinary way to get one -- therefore answers the client 200
   and nothing else.

   THE CLIENT READS `saved?.id || saved?._id`. On a null body that is undefined,
   and site_superintendent_log.jsx then SKIPS the signature-ledger event, SKIPS
   logbooksAPI.finalize, sets locked, and toasts "Log filed and locked" -- the
   copy asserts the seal by name. Nothing throws, so the catch never runs. The
   record stays `submitted, is_locked: false` forever: a visit log is excluded
   from sweep_stale_end_of_day_logs by design, so there is no second actor that
   will ever freeze it. A document that shows as filed and locked, is neither.

   The endpoint holds the inserted document in a local variable while it answers
   `null`. Returning what it just wrote is the fix, and the assertion below is
   the contract: this endpoint never answers 200 with a body the client cannot
   get an id from.

3. A REFUSAL NAMES WHAT TO FIX. SUBMIT_UNATTESTED_ITEMS carries an `items` list
   precisely so the client can point at the unanswered items instead of printing
   a machine code at a man on a jobsite. And a refused submit writes nothing.

── THE PAYLOADS ARE THE SCREEN'S, NOT INVENTED ─────────────────────────────────

FULL_VISIT and CONDITION_WITHOUT_ORDER are what `buildData()` in
frontend/app/logbooks/site_superintendent_log.jsx produces -- read off its
`return {...}` and off deriveConditionAndOrderBlocks (src/utils/csFindings.js).
CONDITION_WITHOUT_ORDER is not a contrived body: when the CS logs a finding,
derive IGNORES the "nothing to report" tick and `orders_given` comes back `{}`,
so an ordinary visit where he saw something and gave no written order is exactly
this shape.

    python backend/tests/test_superintendent_log_files.py
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

LOG_TYPE = "site_superintendent_log"
DATE = "2026-09-01"


# ── a store that answers queries, because "is there a document" is the question ──
#
# The suite's usual _FakeCollection returns a canned find_one and keeps the
# inserted dicts in a list. That is enough to assert a REFUSAL wrote nothing; it
# cannot assert that a document EXISTS AND CAN BE READ BACK, which is the whole
# subject here and is what production disagreed with. So this one stores.


class _InsertResult:
    def __init__(self, _id):
        self.inserted_id = _id


class _UpdateResult:
    def __init__(self, n):
        self.matched_count = n
        self.modified_count = n


def _matches(doc, query):
    for key, cond in (query or {}).items():
        value = doc
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(cond, dict) and any(str(k).startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$ne" and value == arg:
                    return False
                if op == "$eq" and value != arg:
                    return False
                if op == "$in" and value not in arg:
                    return False
        elif value != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return self._docs


class _Collection:
    def __init__(self, name):
        self.name = name
        self.docs = []
        # Set to True to make a read-back of a just-inserted _id miss, which is
        # what a secondary that has not caught up does. See class 2 below.
        self.read_your_writes = True
        self._just_inserted = set()

    async def find_one(self, query=None, *a, **k):
        # ONE-SHOT LAG, WHICH IS WHAT REPLICATION LAG IS. The read that
        # immediately follows the insert misses; the next one, a request later,
        # sees the row. A permanent miss would be a different (and much louder)
        # fault, and would make the finalize test below assert nothing about
        # the id -- it would 404 on a row that genuinely was not readable.
        if not self.read_your_writes and (query or {}).get("_id") in self._just_inserted:
            self._just_inserted.discard(query["_id"])
            return None
        for d in self.docs:
            if _matches(d, query or {}):
                return dict(d)
        return None

    async def insert_one(self, doc, *a, **k):
        d = dict(doc)
        d.setdefault("_id", str(uuid.uuid4()))
        self.docs.append(d)
        self._just_inserted.add(d["_id"])
        return _InsertResult(d["_id"])

    async def update_one(self, query, update, *a, **k):
        for d in self.docs:
            if _matches(d, query or {}):
                d.update(update.get("$set", {}))
                return _UpdateResult(1)
        return _UpdateResult(0)

    async def update_many(self, query, update, *a, **k):
        n = 0
        for d in self.docs:
            if _matches(d, query or {}):
                d.update(update.get("$set", {}))
                n += 1
        return _UpdateResult(n)

    async def count_documents(self, query=None, *a, **k):
        return sum(1 for d in self.docs if _matches(d, query or {}))

    async def delete_many(self, query=None, *a, **k):
        self.docs = [d for d in self.docs if not _matches(d, query or {})]
        return _UpdateResult(0)

    def find(self, query=None, *a, **k):
        return _Cursor([dict(d) for d in self.docs if _matches(d, query or {})])

    async def create_index(self, *a, **k):
        return None


class _Db:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _Collection(n)
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


# ── the CS, his project, and his affirmed signature ─────────────────────────
CS_USER = {
    "_id": "u_cs", "id": "u_cs", "role": "cp", "company_id": "co_a",
    "full_name": "Roy Fishman", "assigned_projects": ["proj1"],
    "account_status": "approved",
}

# AFFIRMED, because the submit gate asks _is_affirmed_signature and a merely
# populated credential is what put "UNAFFIRMED" on 65 filed logs.
SIGNATURE = {
    "paths": [[1, 2]], "signerName": "Roy Fishman",
    "signed_at": f"{DATE}T15:40:00Z",
    "affirmed": True, "affirmedAt": f"{DATE}T15:40:00Z",
}

# buildData() with every field entered and all four attestable items explicitly
# nothing-to-report. The ordinary complete visit.
FULL_VISIT = {
    "presence": {"printed_name": "Roy Fishman", "arrived_at": "07:15",
                 "departed_at": "15:40"},
    "progress": {"summary": "Deck pour 3rd floor completed; shoring left in place."},
    "cs_activities": {"summary": "Walked floors 1-4, roof and sidewalk shed.",
                      "locations": "Floors 1-4, roof"},
    "unsafe_conditions": {"none_to_report": True},
    "orders_given": {"none_to_report": True},
    "dob_actions": {"none_to_report": True},
    "incidents": {"none_to_report": True},
    "competent_person": {"name": "Roy Fishman"},
    "daily_inspection": {"inspected_on": DATE, "location": "Floors 1-4",
                         "result": "No defects observed"},
}

# He observed a condition and gave no written order. deriveConditionAndOrderBlocks
# ignores the nothing-to-report tick as soon as a row exists, so orders_given
# arrives EMPTY and item 5 is unanswered.
CONDITION_WITHOUT_ORDER = {
    **FULL_VISIT,
    "unsafe_conditions": {"entries": [{
        "location": "3rd floor east", "observed_at": "10:20",
        "condition": "Guardrail section removed at the hoist opening",
        "corrected": "corrected",
    }]},
    "orders_given": {},
}


def _body(data, status="submitted"):
    return {
        "project_id": "proj1", "log_type": LOG_TYPE, "date": DATE,
        "data": data, "cp_signature": SIGNATURE, "cp_name": "Roy Fishman",
        "status": status,
    }


def _fresh_db():
    db = _Db()
    db.projects.docs.append({"_id": "proj1", "name": "8 Walworth St",
                             "company_id": "co_a"})
    return db


class _Filing:
    """One CS filing driven through the ASGI app, create then finalize."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        async def _user():
            return CS_USER

        server.app.dependency_overrides[server.get_current_user] = _user
        self._patches = [
            patch.object(server, "db", self.db),
            # Fire-and-forget background work. Not this file's subject, and an
            # un-awaited task against a double is noise in the failure output.
            patch.object(server, "_enhance_logbook_photos", AsyncMock()),
            patch.object(server, "_remember_other_activities", AsyncMock()),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(server.app)
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        server.app.dependency_overrides.clear()
        return False

    def create(self, data, status="submitted"):
        return self.client.post("/api/logbooks", json=_body(data, status))

    def finalize(self, log_id):
        return self.client.post(f"/api/logbooks/{log_id}/finalize")

    @property
    def rows(self):
        return [d for d in self.db.logbooks.docs if d.get("log_type") == LOG_TYPE]


class ASubmittedSuperintendentLogBecomesADocument(unittest.TestCase):
    """countDocuments({log_type: "site_superintendent_log"}) must not be zero."""

    def test_the_post_is_accepted(self):
        with _Filing(_fresh_db()) as f:
            r = f.create(FULL_VISIT)
            self.assertEqual(r.status_code, 200, r.text)

    def test_a_document_exists_afterwards(self):
        """THE HEADLINE. Nothing else in this suite asks it for this log type."""
        with _Filing(_fresh_db()) as f:
            f.create(FULL_VISIT)
            self.assertEqual(len(f.rows), 1, "no site_superintendent_log was written")

    def test_it_is_stored_with_the_right_status_and_identity(self):
        with _Filing(_fresh_db()) as f:
            f.create(FULL_VISIT)
            row = f.rows[0]
            self.assertEqual(row["status"], "submitted")
            self.assertEqual(row["date"], DATE)
            self.assertEqual(row["project_id"], "proj1")
            self.assertEqual(row["company_id"], "co_a")
            self.assertEqual(row["data"]["presence"]["departed_at"], "15:40")

    def test_it_is_a_visit_log_and_create_leaves_it_unlocked(self):
        """The published contract for class `visit`: freeze_on_sign false,
        freeze_on_finalize true. Create must NOT lock it."""
        self.assertEqual(server.logbook_timing_class(LOG_TYPE), "visit")
        with _Filing(_fresh_db()) as f:
            f.create(FULL_VISIT)
            row = f.rows[0]
            self.assertEqual(row["timing_class"], "visit")
            self.assertIs(row["is_locked"], False)

    def test_the_authors_finalize_seals_it(self):
        """3301.13.13 "prior to departing the job site". Nothing else will ever
        do it -- sweep_stale_end_of_day_logs excludes VISIT_LOG_TYPES."""
        self.assertIn(LOG_TYPE, server.VISIT_LOG_TYPES)
        with _Filing(_fresh_db()) as f:
            created = f.create(FULL_VISIT).json()
            r = f.finalize(created["id"])
            self.assertEqual(r.status_code, 200, r.text)
            row = f.rows[0]
            self.assertIs(row["is_locked"], True)
            self.assertEqual(row["status"], "submitted")


class TheResponseCarriesTheIdTheClientNeeds(unittest.TestCase):
    """A 200 the client cannot get an id from is a silent loss.

    site_superintendent_log.jsx reads `saved?.id || saved?._id`; with no id it
    skips the ledger event AND the finalize, then toasts "Log filed and locked".
    """

    def test_an_ordinary_create_answers_with_an_id(self):
        with _Filing(_fresh_db()) as f:
            body = f.create(FULL_VISIT).json()
            self.assertIsInstance(body, dict, "the body must be a document")
            self.assertTrue(body.get("id") or body.get("_id"),
                            "no id in the create response")

    def test_a_read_that_does_not_see_its_own_write_still_answers_with_an_id(self):
        """THE SILENT LOSS, REPRODUCED.

        create_logbook re-reads the row it just inserted and returns
        serialize_id(that read). A secondary that has not caught up returns None,
        serialize_id(None) is None, and FastAPI renders 200 `null` -- while the
        row is on disk. The endpoint is holding the document it just wrote.
        """
        db = _fresh_db()
        db.logbooks.read_your_writes = False
        with _Filing(db) as f:
            r = f.create(FULL_VISIT)
            self.assertEqual(r.status_code, 200, r.text)
            # The write happened. That is what makes the null body a defect
            # rather than an honest report of failure.
            self.assertEqual(len(f.rows), 1)
            body = r.json()
            self.assertIsNotNone(
                body,
                "200 with a null body: the client's saved?.id is undefined, so "
                "finalize is skipped and it still says 'Log filed and locked'",
            )
            self.assertTrue(
                isinstance(body, dict) and (body.get("id") or body.get("_id")),
                "200 with no id: the client cannot finalize what it cannot name",
            )

    def test_the_id_it_answers_with_is_the_row_it_wrote(self):
        """An id that names nothing would be worse than none: the client would
        finalize into a 404 it reports as a failure to file."""
        db = _fresh_db()
        db.logbooks.read_your_writes = False
        with _Filing(db) as f:
            body = f.create(FULL_VISIT).json() or {}
            self.assertEqual(str(body.get("id") or body.get("_id")),
                             str(f.rows[0]["_id"]))

    def test_and_that_id_finalizes(self):
        """The end-to-end consequence: the seal the statute requires happens."""
        db = _fresh_db()
        db.logbooks.read_your_writes = False
        with _Filing(db) as f:
            body = f.create(FULL_VISIT).json() or {}
            r = f.finalize(str(body.get("id") or body.get("_id")))
            self.assertEqual(r.status_code, 200, r.text)
            self.assertIs(f.rows[0]["is_locked"], True)


class AnUnattestedItemIsRefusedAndNamed(unittest.TestCase):
    """The refusal a CS can act on, and a refusal that writes nothing."""

    def test_an_unanswered_attestable_item_is_a_400(self):
        with _Filing(_fresh_db()) as f:
            r = f.create(CONDITION_WITHOUT_ORDER)
            self.assertEqual(r.status_code, 400, r.text)

    def test_it_carries_the_code_and_the_items(self):
        with _Filing(_fresh_db()) as f:
            detail = f.create(CONDITION_WITHOUT_ORDER).json()["detail"]
            self.assertEqual(detail["code"], "SUBMIT_UNATTESTED_ITEMS")
            self.assertEqual(detail["items"], ["orders_given"],
                             "the client points at the item with this list")

    def test_the_named_items_are_declared_item_keys(self):
        """The client maps these onto CS_LOG_ITEMS labels. A key that is not in
        the declared list would render as a raw identifier on a jobsite."""
        from lib.logbook.superintendent_log import ITEMS_BY_KEY
        with _Filing(_fresh_db()) as f:
            items = f.create(CONDITION_WITHOUT_ORDER).json()["detail"]["items"]
            for key in items:
                self.assertIn(key, ITEMS_BY_KEY)

    def test_a_refused_submit_writes_nothing(self):
        with _Filing(_fresh_db()) as f:
            f.create(CONDITION_WITHOUT_ORDER)
            self.assertEqual(f.rows, [], "a refused submit must not insert")

    def test_a_draft_is_not_held_to_the_attestation_rule(self):
        """Empty is the normal state while the visit is open. The gate is on
        SUBMIT, and refusing a draft would stop him saving work in progress."""
        with _Filing(_fresh_db()) as f:
            r = f.create(CONDITION_WITHOUT_ORDER, status="draft")
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(len(f.rows), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
