"""A worker is oriented once. create_logbook now says so.

WHAT HAPPENED. subcontractor_orientation is `immediate`, so create_logbook's
dedupe filter excluded LOCKED rows -- correct for a scaffold inspection, where
the post-alteration one is a genuinely new discrete record. It is also
PER-WORKER, which the handler already knew and keyed on.

The two together are the defect. Submitting an immediate log sets is_locked.
The locked row then falls out of the dedupe filter. The next create for the
SAME worker matches nothing and INSERTS. Self-accelerating: every submit makes
the previous row invisible to the next dedupe.

    30 rows for worker 6a85b670b1fde8599be71e7f on 2026-08-25, 14:43-15:07.
    FOURTEEN submitted -- fourteen signed attestations that a CP witnessed one
    orientation. Thirteen assert something that did not happen. It recurred on
    08-26 for two more workers.

THE FIX, and both halves are load-bearing:

    is_locked  OUT of the filter for this type. A man is oriented once; there
               is no second discrete orientation of the same worker.
    date       OUT too, matching the gate exactly. Orientation is FIRST-TIME-
               ON-PROJECT, not daily -- the combined report already matches
               across all dates ("a worker oriented weeks ago counts as
               covered"). Leaving date in is the same bug on a slower clock.

THE 423 IS THE CORRECT OUTCOME. A second tap now meets "This log is finalized
and cannot be edited. Create an amendment instead." That does not violate the
never-block rule: the orientation is already filed, the worker is already
oriented, and THE CHECK-IN PATH DOES NOT CONSULT IT -- asserted below.

    python backend/tests/test_orientation_dedupe_per_worker.py
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

CP = {"_id": "u1", "id": "u1", "role": "cp", "company_id": "companyA",
      "account_status": "approved", "assigned_projects": ["projA", "projB"],
      "full_name": "Michael Cespedes"}
PROJECTS = {
    "projA": {"_id": "projA", "id": "projA", "company_id": "companyA", "name": "588 Thomas"},
    "projB": {"_id": "projB", "id": "projB", "company_id": "companyA", "name": "857 Prescott"},
}
# The real worker from the incident.
WORKER = "6a85b670b1fde8599be71e7f"
AFFIRMED = {"paths": [[{"x": 1, "y": 1}]], "affirmed": True,
            "affirmedAt": "2026-08-25T18:43:00Z", "signerName": "Michael Cespedes"}


class FakeLogbooks:
    """A tiny store that answers find_one by evaluating the dedupe filter.

    Only the operators create_logbook actually uses: equality, $ne, and the
    dotted data.worker_id path. Anything else raises rather than quietly
    matching -- a fake that silently ignores a key would make this whole file
    agree with itself instead of with the handler.
    """

    def __init__(self):
        self.docs = []

    def _match(self, q, doc):
        for k, v in q.items():
            if k == "data.worker_id":
                actual = (doc.get("data") or {}).get("worker_id")
            elif "." in k:
                raise AssertionError(f"fake does not model dotted key {k}")
            else:
                actual = doc.get(k)
            if isinstance(v, dict):
                if set(v) != {"$ne"}:
                    raise AssertionError(f"fake does not model operator {v} on {k}")
                if actual == v["$ne"]:
                    return False
            elif actual != v:
                return False
        return True

    async def find_one(self, q, *a, **kw):
        for d in self.docs:
            if self._match(q, d):
                # A COPY, because Mongo returns one. serialize_id does
                # `del obj['_id']` IN PLACE on whatever it is handed, so a fake
                # returning a live reference lets the handler delete the id out
                # of the store -- and every later lookup then fails for a reason
                # that exists nowhere in production.
                return dict(d)
        return None

    async def insert_one(self, doc):
        # `_id` is stamped the way Mongo would: the handler reads it back off
        # the stored document, and a fake that omits it fails for a reason that
        # has nothing to do with what is under test.
        stored = dict(doc)
        stored["_id"] = f"lb{len(self.docs) + 1}"
        self.docs.append(stored)
        r = MagicMock()
        r.inserted_id = stored["_id"]
        return r

    async def update_one(self, q, upd, *a, **kw):
        for d in self.docs:
            if self._match(q, d):
                d.update(upd.get("$set", {}))
                break
        r = MagicMock()
        r.matched_count = 1
        return r

    async def count_documents(self, q, *a, **kw):
        return sum(1 for d in self.docs if self._match(q, d))


def _create(store, *, log_type, project_id, date, worker_id=None, status="draft",
            signature=None, data=None):
    """Drive the real create_logbook against the store. Returns its result, or
    raises whatever the handler raised."""
    body = {
        "project_id": project_id,
        "log_type": log_type,
        "date": date,
        "status": status,
        "cp_signature": signature,
        "cp_name": "Michael Cespedes",
        "data": dict(data or {"checklist": {"ppe": True}}),
    }
    if worker_id is not None:
        body["data"]["worker_id"] = worker_id
    if log_type == "subcontractor_orientation":
        # SUBMIT_MISSING_TRADE is a real gate on this type
        # (_submit_missing_trade_detail): an orientation cannot be submitted for
        # a worker with no trade. It is not what this file tests, so the
        # fixtures carry one rather than silencing the guard -- a fixture that
        # tripped it would fail here for the wrong reason and hide the dedupe.
        body["data"].setdefault("worker_name", "Cristian B Rojas")
        body["data"].setdefault("worker_company", "Arkon Builders")
        body["data"].setdefault("worker_trade", "Framing")

    db = MagicMock()
    db.logbooks = store
    db.projects.find_one = AsyncMock(side_effect=lambda q, *a, **kw: dict(PROJECTS[project_id]))

    payload = server.LogbookCreate(**body)
    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()), \
         patch.object(server, "_remember_other_activities", AsyncMock()), \
         patch.object(server, "_refresh_required_logbooks", AsyncMock()):
        return asyncio.run(server.create_logbook(data=payload, current_user=CP))


def _orientations(store, worker_id=None):
    out = [d for d in store.docs if d.get("log_type") == "subcontractor_orientation"]
    if worker_id is not None:
        out = [d for d in out if (d.get("data") or {}).get("worker_id") == worker_id]
    return out


class TheLoopIsClosed(unittest.TestCase):
    """create, submit, create again -- the exact incident sequence."""

    def test_a_second_create_over_a_LOCKED_orientation_does_not_insert(self):
        """THE REPRODUCTION. Against main this inserts a second row; the third
        call a third, and so on to thirty."""
        store = FakeLogbooks()
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id=WORKER, status="submitted",
                signature=AFFIRMED)
        self.assertEqual(len(_orientations(store, WORKER)), 1)
        self.assertIs(store.docs[0]["is_locked"], True,
                      "an immediate type must lock on submit; without that the "
                      "loop this test reproduces cannot occur at all")

        with self.assertRaises(HTTPException) as c:
            _create(store, log_type="subcontractor_orientation", project_id="projA",
                    date="2026-08-25", worker_id=WORKER, status="submitted",
                    signature=AFFIRMED)
        self.assertEqual(c.exception.status_code, 423)
        self.assertEqual(len(_orientations(store, WORKER)), 1,
                         "a second orientation was inserted for the same worker")

    def test_fourteen_taps_produce_ONE_record(self):
        """The incident, at its real magnitude. Thirteen of the fourteen were
        assertions that a CP witnessed something that did not happen."""
        store = FakeLogbooks()
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id=WORKER, status="submitted",
                signature=AFFIRMED)
        refused = 0
        for _ in range(13):
            try:
                _create(store, log_type="subcontractor_orientation", project_id="projA",
                        date="2026-08-25", worker_id=WORKER, status="submitted",
                        signature=AFFIRMED)
            except HTTPException as e:
                self.assertEqual(e.status_code, 423)
                refused += 1
        self.assertEqual(refused, 13)
        self.assertEqual(len(_orientations(store, WORKER)), 1)

    def test_a_LATER_DATE_does_not_mint_a_second_record(self):
        """DATE IS OUT OF THE FILTER. Orientation is first-time-on-project, not
        daily -- the combined report already matches across all dates. Leaving
        date in would be the same bug on a slower clock."""
        store = FakeLogbooks()
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id=WORKER, status="submitted",
                signature=AFFIRMED)
        with self.assertRaises(HTTPException) as c:
            _create(store, log_type="subcontractor_orientation", project_id="projA",
                    date="2026-08-26", worker_id=WORKER, status="submitted",
                    signature=AFFIRMED)
        self.assertEqual(c.exception.status_code, 423)
        self.assertEqual(len(_orientations(store, WORKER)), 1)

    def test_an_unlocked_draft_still_UPSERTS_rather_than_duplicating(self):
        """Unchanged behaviour, and the ordinary path: a draft edited twice is
        one record."""
        store = FakeLogbooks()
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id=WORKER, status="draft")
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id=WORKER, status="draft",
                data={"checklist": {"ppe": True, "fall": True}})
        self.assertEqual(len(_orientations(store, WORKER)), 1)


class ItDedupesTheRIGHTThings(unittest.TestCase):
    """A filter that matches too much is as wrong as one that matches nothing."""

    def _seed(self):
        store = FakeLogbooks()
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id=WORKER, status="submitted",
                signature=AFFIRMED)
        return store

    def test_a_DIFFERENT_WORKER_on_the_same_project_still_inserts(self):
        """JOSE I LOPEZ after Cristian. Refusing this would stop a CP orienting
        the next man on the crew."""
        store = self._seed()
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id="other_worker_id", status="submitted",
                signature=AFFIRMED)
        self.assertEqual(len(_orientations(store)), 2)
        self.assertEqual(len(_orientations(store, "other_worker_id")), 1)

    def test_the_SAME_WORKER_on_a_DIFFERENT_PROJECT_still_inserts(self):
        """Orientation is first-time-ON-PROJECT. A man on two jobs is oriented
        on each, and the filter is project-scoped for exactly that reason."""
        store = self._seed()
        _create(store, log_type="subcontractor_orientation", project_id="projB",
                date="2026-08-25", worker_id=WORKER, status="submitted",
                signature=AFFIRMED)
        self.assertEqual(len(_orientations(store, WORKER)), 2)
        self.assertEqual(
            {d["project_id"] for d in _orientations(store, WORKER)}, {"projA", "projB"})

    def test_a_keyless_create_still_mints_an_id_and_inserts(self):
        """Unchanged, and it is defence for OLDER CLIENTS: a field build that
        cannot take an OTA still sends no worker_id, and a 400 would break
        manual orientation on a live site until a rebuild."""
        store = self._seed()
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id=None, status="draft")
        self.assertEqual(len(_orientations(store)), 2)
        minted = [d for d in _orientations(store)
                  if str((d.get("data") or {}).get("worker_id", "")).startswith("srv_")]
        self.assertEqual(len(minted), 1)

    def test_a_soft_deleted_orientation_does_not_block_a_new_one(self):
        """is_deleted stays in the filter. A removed record must not stop the
        worker being oriented again."""
        store = self._seed()
        store.docs[0]["is_deleted"] = True
        _create(store, log_type="subcontractor_orientation", project_id="projA",
                date="2026-08-25", worker_id=WORKER, status="submitted",
                signature=AFFIRMED)
        self.assertEqual(len(_orientations(store, WORKER)), 2)


class OtherImmediateTypesAreUNTOUCHED(unittest.TestCase):
    """The freeze model is CORRECT for everything else. A post-alteration
    scaffold inspection is a genuinely new discrete record."""

    def test_a_second_scaffold_inspection_after_a_locked_one_still_inserts(self):
        store = FakeLogbooks()
        _create(store, log_type="scaffold_maintenance", project_id="projA",
                date="2026-08-25", status="submitted", signature=AFFIRMED)
        _create(store, log_type="scaffold_maintenance", project_id="projA",
                date="2026-08-25", status="submitted", signature=AFFIRMED)
        rows = [d for d in store.docs if d["log_type"] == "scaffold_maintenance"]
        self.assertEqual(len(rows), 2, "the freeze model broke for scaffold")
        self.assertEqual([r.get("instance_seq") for r in rows], [1, 2])

    def test_a_second_toolbox_talk_after_a_locked_one_still_inserts(self):
        store = FakeLogbooks()
        for _ in range(2):
            _create(store, log_type="toolbox_talk", project_id="projA",
                    date="2026-08-25", status="submitted", signature=AFFIRMED)
        self.assertEqual(len([d for d in store.docs if d["log_type"] == "toolbox_talk"]), 2)

    def test_the_exclusion_is_scoped_by_NAME_not_removed(self):
        """The mechanism, not just the outcome: is_locked must still enter the
        filter for every immediate type except this one."""
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        i = src.index("async def create_logbook")
        body = src[i:src.index("existing = await db.logbooks.find_one", i)]
        self.assertIn('dedupe_filter["is_locked"] = {"$ne": True}', body)
        self.assertIn('data.log_type != "subcontractor_orientation"', body)

    def test_an_END_OF_DAY_type_never_had_the_exclusion_and_still_does_not(self):
        """daily_jobsite keeps its 423: the daily narrative is one record per
        day and corrections go through /amend."""
        store = FakeLogbooks()
        _create(store, log_type="daily_jobsite", project_id="projA",
                date="2026-08-25", status="draft")
        _create(store, log_type="daily_jobsite", project_id="projA",
                date="2026-08-25", status="draft", data={"note": "second write"})
        self.assertEqual(len([d for d in store.docs if d["log_type"] == "daily_jobsite"]), 1)


class TheCheckInPathIsUNTOUCHED(unittest.TestCase):
    """THE NEVER-BLOCK RULE. A refusal anywhere on the check-in path is a man
    turned away at a turnstile because an admin did not finish a form.

    The 423 this PR introduces is on create_logbook -- the CP's app -- and the
    gate does not go through it.
    """

    def test_the_gate_writes_its_orientation_with_its_OWN_insert(self):
        """register_and_checkin inserts directly; it never calls create_logbook,
        so it cannot receive the 423."""
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        i = src.index("async def register_and_checkin")
        body = src[i:src.index("\n@api_router", i)]
        self.assertIn('"log_type": "subcontractor_orientation"', body)
        self.assertIn("db.logbooks.insert_one", body)
        self.assertNotIn("create_logbook(", body)

    def test_the_gate_dedupe_is_unchanged(self):
        """It already keyed on (log_type, project_id, data.worker_id,
        is_deleted). This PR made create_logbook match it; it did not touch the
        gate."""
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        i = src.index("async def register_and_checkin")
        body = src[i:src.index("\n@api_router", i)]
        j = body.index('existing_orient_log = await db.logbooks.find_one({')
        f = body[j:body.index("})", j)]
        self.assertIn('"log_type": "subcontractor_orientation"', f)
        self.assertIn('"project_id": project_id', f)
        self.assertIn('"data.worker_id": worker_id_str', f)
        self.assertIn('"is_deleted": {"$ne": True}', f)
        self.assertNotIn('"date"', f)
        self.assertNotIn('"is_locked"', f)

    def test_the_gate_still_skips_when_one_exists(self):
        """`if not existing_orient_log:` -- the gate SKIPS rather than
        refusing. That is what keeps it fail-open."""
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        i = src.index("existing_orient_log = await db.logbooks.find_one({")
        self.assertIn("if not existing_orient_log:", src[i:i + 900])

    def test_every_gate_route_is_still_mounted(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        for p in ("/api/checkin/register-and-checkin", "/api/checkin/submit",
                  "/api/checkin/lookup-worker",
                  "/api/checkin/{project_id}/{tag_id}/info"):
            self.assertIn(p, paths, f"gate route disappeared: {p}")


class WhatThisPRDoesNotDo(unittest.TestCase):
    """Scope, pinned so nobody mistakes this for the rest."""

    SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8")

    def test_the_existing_rows_are_NOT_cleaned_up(self):
        """Filed logbooks are never rewritten. The 30 rows stay until the
        operator rules on them; nothing here touches them."""
        i = self.SRC.index("async def create_logbook")
        body = self.SRC[i:self.SRC.index("async def ", i + 40)]
        self.assertNotIn("delete_many", body)
        self.assertNotIn("update_many", body)

    def test_no_idempotency_key_was_added_to_this_handler(self):
        """The button guard is FRONTEND and sequenced separately. It would not
        have closed this anyway: a dropped response, a drain replay or a second
        device all reach the server without a second tap -- the dedupe is what
        closes those, which is why this PR is the dedupe alone.

        SCOPED TO THE HANDLER, not the file: server.py already has an unrelated
        `idempotency_key()` at ~25466, and a whole-file assertion matched it.
        """
        i = self.SRC.index("async def create_logbook")
        body = self.SRC[i:self.SRC.index("async def ", i + 40)]
        self.assertNotIn("idempotency", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
