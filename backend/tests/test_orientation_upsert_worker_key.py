"""POST /api/logbooks — subcontractor_orientation is deduped PER WORKER.

Background (docs/audits): register_and_checkin inserts one orientation logbook
per worker directly, deduped on data.worker_id. POST /api/logbooks used to
dedup EVERY log_type on (project_id, log_type, date), which omits worker_id — so
a UI-created orientation's find_one matched a DIFFERENT worker's check-in row
that merely shared the date, and the $set overwrote it (nondeterministic which
one; find_one has no sort). Three orientations for project
6a5f63bc147407d3261df2c7 on 2026-07-29 coexist precisely because the check-in
path bypasses the endpoint; the risk is the UI path clobbering one of them.

Fix under test: for log_type == "subcontractor_orientation", the upsert filter
additionally keys on data.worker_id. When the incoming data has no worker_id
(null/empty/absent), the server MINTS one (uuid4 hex, srv_ prefix), writes it
into the document, and keys on it — a fresh id can never match an existing row,
so the create always inserts and never clobbers. (A 400 was rejected: server.py
deploys immediately but the frontend ships by OTA and the field build cannot
receive OTA, so a 400 would break manual orientation creation until a rebuild.)
Every other log_type still upserts on (project_id, log_type, date) unchanged.

These call server.create_logbook directly against a fake db that implements the
dot-path (`data.worker_id`) and {$ne} semantics the real query relies on. The
existing shared fake in test_project_model_endpoints does neither, hence a
purpose-built one here.
"""

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from server import LogbookCreate  # noqa: E402

PROJECT_ID = "6a5f63bc147407d3261df2c7"
DATE = "2026-07-29"
USER = {"_id": "admin1", "id": "admin1", "role": "admin", "company_id": "co1"}


def _get(doc, key):
    """Dot-path aware getter: 'data.worker_id' -> doc['data']['worker_id']."""
    if "." not in key:
        return doc.get(key)
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict) and "$ne" in v:
            if _get(doc, k) == v["$ne"]:
                return False
            continue
        if _get(doc, k) != v:
            return False
    return True


class _Result:
    def __init__(self, _id):
        self.inserted_id = _id


class _Coll:
    def __init__(self):
        self.docs = []
        self._seq = 0

    async def find_one(self, query):
        # First match in natural (insertion) order — mirrors Mongo find_one
        # with no sort, which is the nondeterminism the fix removes.
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def insert_one(self, doc):
        self._seq += 1
        _id = doc.get("_id") or f"oid_{self._seq}"
        doc = dict(doc)
        doc["_id"] = _id
        self.docs.append(doc)
        return _Result(_id)

    async def update_one(self, flt, update, upsert=False):
        setd = update.get("$set", {})
        for d in self.docs:
            if _match(d, flt):
                d.update(setd)
                return
        if upsert:
            nd = dict(flt)
            nd.update(setd)
            self.docs.append(nd)


class _DB:
    def __init__(self):
        self.logbooks = _Coll()
        self.projects = _Coll()


async def _noop(*a, **k):
    return None


def _orientation_row(worker_id, worker_name, extra=None):
    """A check-in-created orientation row, as register_and_checkin writes it."""
    data = {
        "worker_id": worker_id,
        "worker_name": worker_name,
        "worker_company": "Acme Sub",
        "worker_trade": "Laborer",
        "checklist": {"ppe": True, "fall": True},
        "completed_at": "2026-07-29T16:34:59.328000+00:00",
    }
    if extra:
        data.update(extra)
    return {
        "_id": f"row_{worker_id}",
        "project_id": PROJECT_ID,
        "project_name": "588 Boyland",
        "company_id": "co1",
        "log_type": "subcontractor_orientation",
        "date": DATE,
        "status": "draft",
        "cp_signature": None,
        "cp_name": None,
        "data": data,
        "created_at": "2026-07-29T16:34:59.328000+00:00",
        "updated_at": "2026-07-29T16:34:59.328000+00:00",
        "is_deleted": False,
    }


def _payload(worker_id, worker_name, log_type="subcontractor_orientation"):
    data = {"worker_name": worker_name, "worker_company": "New Sub", "checklist": {"ppe": True}}
    if worker_id is not None:
        data["worker_id"] = worker_id
    return LogbookCreate(
        project_id=PROJECT_ID, log_type=log_type, date=DATE, data=data,
        cp_signature=None, cp_name=None, status="draft",
    )


class OrientationUpsertWorkerKey(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.projects.docs.append({"_id": PROJECT_ID, "company_id": "co1", "is_deleted": False})
        self._orig = {
            "db": server.db,
            "gcid": server.get_user_company_id,
            "tqid": server.to_query_id,
            "enh": server._enhance_logbook_photos,
            "audit": server.audit_log,
        }
        server.db = self.db
        server.get_user_company_id = lambda u: "co1"
        server.to_query_id = lambda x: x            # store/lookup projects by string _id
        server._enhance_logbook_photos = _noop      # fire-and-forget task, no-op in test
        server.audit_log = _noop

    def tearDown(self):
        server.db = self._orig["db"]
        server.get_user_company_id = self._orig["gcid"]
        server.to_query_id = self._orig["tqid"]
        server._enhance_logbook_photos = self._orig["enh"]
        server.audit_log = self._orig["audit"]
        self.loop.close()

    def _create(self, payload):
        return self.loop.run_until_complete(
            server.create_logbook(data=payload, current_user=USER)
        )

    # 1 — UI create for worker B does NOT modify worker A's existing row.
    def test_manual_create_for_B_does_not_touch_A(self):
        row_a = _orientation_row("A", "Alice")
        self.db.logbooks.docs.append(copy.deepcopy(row_a))
        a_before = copy.deepcopy(self.db.logbooks.docs[0])

        self._create(_payload("B", "Bob"))

        a_after = next(d for d in self.db.logbooks.docs if d["_id"] == "row_A")
        self.assertEqual(a_before, a_after, "worker A's row must be byte-identical after B's create")
        self.assertEqual(len(self.db.logbooks.docs), 2, "B's create must insert a new row, not overwrite A")
        self.assertTrue(any(d["data"]["worker_id"] == "B" for d in self.db.logbooks.docs))

    # 2 — two manual creates on the same day produce two rows, not one overwrite.
    def test_two_manual_creates_same_day_two_rows(self):
        self._create(_payload("manual_1", "Manny One"))
        self._create(_payload("manual_2", "Manny Two"))
        self.assertEqual(len(self.db.logbooks.docs), 2)
        ids = {d["data"]["worker_id"] for d in self.db.logbooks.docs}
        self.assertEqual(ids, {"manual_1", "manual_2"})

    # 3 — a manual create for a worker who already has an orientation updates
    #     THAT worker's row, not another.
    def test_manual_create_for_existing_worker_updates_that_row(self):
        self.db.logbooks.docs.append(_orientation_row("A", "Alice"))
        self.db.logbooks.docs.append(_orientation_row("B", "Bob"))

        self._create(_payload("A", "Alice Updated"))

        self.assertEqual(len(self.db.logbooks.docs), 2, "no new row — A's existing row is updated in place")
        a = next(d for d in self.db.logbooks.docs if d["data"]["worker_id"] == "A")
        b = next(d for d in self.db.logbooks.docs if d["data"]["worker_id"] == "B")
        self.assertEqual(a["data"]["worker_name"], "Alice Updated")
        self.assertEqual(b["data"]["worker_name"], "Bob", "worker B untouched")

    # 4 — a create with NO worker_id inserts a NEW row (server mints an id),
    #     leaves existing rows byte-identical, and the written doc has a
    #     non-null data.worker_id. Defense for older OTA-stale clients: the
    #     server never 400s and never clobbers.
    def test_missing_worker_id_mints_new_row_no_clobber(self):
        row_a = _orientation_row("A", "Alice")
        self.db.logbooks.docs.append(copy.deepcopy(row_a))
        a_before = copy.deepcopy(self.db.logbooks.docs[0])

        self._create(_payload(None, "Nameless"))

        a_after = next(d for d in self.db.logbooks.docs if d["_id"] == "row_A")
        self.assertEqual(a_before, a_after, "existing row A must be byte-identical (no clobber)")
        self.assertEqual(len(self.db.logbooks.docs), 2, "a keyless create must insert a new row")
        minted = next(d for d in self.db.logbooks.docs if d["_id"] != "row_A")
        self.assertTrue(minted["data"].get("worker_id"), "server must write a non-null data.worker_id")
        self.assertNotEqual(minted["data"]["worker_id"], "A")

    # 4b — two keyless creates produce two rows, not one overwrite (each mint
    #      is unique, so neither matches the other).
    def test_two_keyless_creates_two_rows(self):
        self._create(_payload(None, "Nameless One"))
        self._create(_payload(None, "Nameless Two"))
        self.assertEqual(len(self.db.logbooks.docs), 2)
        ids = {d["data"].get("worker_id") for d in self.db.logbooks.docs}
        self.assertEqual(len(ids), 2, "two distinct minted worker_ids")
        self.assertTrue(all(ids), "no null minted id")

    # 5 — every other log_type still upserts on (project_id, log_type, date).
    def test_daily_jobsite_upsert_unchanged(self):
        existing = {
            "_id": "dj1", "project_id": PROJECT_ID, "log_type": "daily_jobsite",
            "date": DATE, "data": {"weather": "clear", "activities": [{"crew_id": "C-1"}]},
            "cp_signature": None, "cp_name": None, "status": "draft",
            "created_at": "x", "updated_at": "x", "is_deleted": False,
        }
        self.db.logbooks.docs.append(existing)

        dj = LogbookCreate(
            project_id=PROJECT_ID, log_type="daily_jobsite", date=DATE,
            data={"weather": "rain", "activities": [{"crew_id": "C-9"}]},
            cp_signature=None, cp_name=None, status="submitted",
        )
        self._create(dj)

        self.assertEqual(len(self.db.logbooks.docs), 1, "daily_jobsite stays a per-day singleton (date-only upsert)")
        self.assertEqual(self.db.logbooks.docs[0]["data"]["weather"], "rain")
        self.assertEqual(self.db.logbooks.docs[0]["status"], "submitted")


if __name__ == "__main__":
    unittest.main()
