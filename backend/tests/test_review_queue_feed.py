"""The review queue feed (lib/review_queue.py, server._review_queue_add; L6
step 3: the items and their producers only).

  * Each producer queues one item with its kind and company and no phone:
    a refused / doubted answer (from _answer_log_write), a set-health finding
    (from _write_set_health), a refused START (from _handle_dm_start), and the
    L7 set-membership question hook.
  * The same finding twice is one row (the _id is derived from it).
  * Per company: an item carries its company, one without is not queued, and
    two companies' findings are two companies' rows.
  * The writer never raises.
  * TWO WRITERS, EACH ONE WRITE: _review_queue_add inserts, and the operator's
    decision (L6.4, _review_decide) is the one update; nothing else in
    server.py, lib/ or scripts/ writes the collection.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import review_queue as rq  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    ADMIN_PHONE, CO_A, CO_B, CP_PHONE, UNKNOWN_PHONE, _Ctx, _db)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)

#: Any write on the review queue, however the collection is named.
_WRITE = re.compile(
    r"(?:\breview_queue|REVIEW_QUEUE|['\"]review_queue['\"]\]|review_queue\.COLLECTION\])"
    r"\s*\.\s*(insert_one|insert_many|update_one|update_many|replace_one|delete_one|"
    r"delete_many|find_one_and_update|find_one_and_replace|find_one_and_delete|"
    r"bulk_write|drop)\b")


def _run(coro):
    return asyncio.run(coro)


def _rows(db):
    return db[rq.COLLECTION].rows


def _no_full_phone(test, rows, phone):
    blob = json.dumps(rows, default=str)
    test.assertIsNone(re.search(re.escape(phone[1:]), blob), "a phone in full")


def _write_answer(db, *, gates=None, records=None, company_id=CO_A, question="door F count",
                  project_ids=("proj_a",), note_gate=None):
    with patch.object(server, "db", db):
        async def go():
            server._answer_turn_begin()
            if note_gate:
                server._answer_turn_note(gate=note_gate)
            return await server._answer_log_write(
                "group", question=question, final_text="Type F doors: 36 (A-101).",
                company_id=company_id, project_ids=list(project_ids),
                asker_phone=ADMIN_PHONE, records=records, gates=gates, path="agent")
        return _run(go())


# ══════════════════════════════════════════════════════════════════════════
# conflicting_sources: queued from _answer_log_write
# ══════════════════════════════════════════════════════════════════════════

class ConflictingSources(unittest.TestCase):
    GATE = {"gate": "plan_answer_gate", "outcome": "ungrounded",
            "subject": f"type F doors call {ADMIN_PHONE}", "records": 2}

    def test_a_gate_refusal_noted_by_the_turn_queues_one_item(self):
        db = FakeDb()
        log_id = _write_answer(db, note_gate=self.GATE,
                               records=[{"_id": "r1", "sheet_number": "A-101",
                                         "quote": "TYPE F DOOR"}])
        rows = _rows(db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["kind"], row["company_id"], row["project_id"], row["status"]),
                         (rq.KIND_CONFLICTING_SOURCES, CO_A, "proj_a", rq.STATUS_PENDING))
        self.assertEqual(row["answer_log_id"], log_id)
        self.assertEqual(row["evidence"]["reasons"], ["plan_gate:ungrounded"])
        self.assertEqual(row["evidence"]["record_ids"], ["r1"])
        self.assertEqual(row["evidence"]["sheets"], ["A-101"])
        self.assertTrue(row["summary"].startswith("plan_gate:ungrounded on type F doors"))
        self.assertTrue(f"[…{ADMIN_PHONE[-4:]}]" in row["summary"])
        _no_full_phone(self, rows, ADMIN_PHONE)

    def test_a_contested_record_queues_with_its_quote(self):
        db = FakeDb()
        _write_answer(db, gates=[{"gate": "plan_answer_gate", "outcome": "grounded",
                                  "subject": "PTAC-2 count"}],
                      records=[{"_id": "r9", "sheet_number": "M-101",
                                "quote": "PTAC-2 QTY (readings disagree)",
                                "payload": {"count_contested": True}},
                               {"_id": "r10", "sheet_number": "M-102", "quote": "PTAC-1 QTY 4"}])
        rows = _rows(db)
        self.assertEqual(len(rows), 1)
        ev = rows[0]["evidence"]
        self.assertEqual(ev["reasons"], ["records_contested"])
        self.assertEqual(ev["record_ids"], ["r9"])
        self.assertEqual(ev["quotes"], [{"id": "r9", "sheet": "M-101",
                                         "text": "PTAC-2 QTY (readings disagree)"}])

    def test_a_dm_brain_unverified_stop_queues(self):
        db = FakeDb()
        _write_answer(db, gates=[{"gate": "dm_brain", "stop": "unverified"}])
        self.assertEqual([r["evidence"]["reasons"] for r in _rows(db)],
                         [["dm_brain:unverified"]])

    def test_a_grounded_answer_queues_nothing(self):
        db = FakeDb()
        _write_answer(db, gates=[{"gate": "plan_answer_gate", "outcome": "grounded",
                                  "subject": "door F"},
                                 {"gate": "dm_brain", "stop": None}],
                      records=[{"_id": "r1", "sheet_number": "A-101", "quote": "F"}])
        self.assertEqual(_rows(db), [])
        self.assertEqual(len(db.answer_log.rows), 1)

    def test_the_same_question_refused_again_is_one_row(self):
        db = FakeDb()
        first = _write_answer(db, note_gate=self.GATE)
        second = _write_answer(db, note_gate=dict(self.GATE, outcome="label_leak"))
        self.assertNotEqual(first, second)
        self.assertEqual(len(db.answer_log.rows), 2)
        self.assertEqual([r["answer_log_id"] for r in _rows(db)], [first])

    def test_no_company_no_item(self):
        db = FakeDb()
        _write_answer(db, note_gate=self.GATE, company_id=None)
        self.assertEqual(_rows(db), [])

    def test_two_companies_same_subject_are_two_rows(self):
        db = FakeDb()
        _write_answer(db, note_gate=self.GATE, company_id=CO_A)
        _write_answer(db, note_gate=self.GATE, company_id=CO_B, project_ids=("proj_b",))
        self.assertEqual(sorted(r["company_id"] for r in _rows(db)), [CO_A, CO_B])
        self.assertEqual(len({r["_id"] for r in _rows(db)}), 2)


# ══════════════════════════════════════════════════════════════════════════
# set_health: queued from _write_set_health
# ══════════════════════════════════════════════════════════════════════════

def _health_db():
    db = FakeDb(projects=[{"_id": "proj_a", "company_id": CO_A},
                          {"_id": "proj_b", "company_id": CO_B}])
    coll = db["plan_set_health"]

    async def insert_many(docs):
        for d in docs:
            await coll.insert_one(d)
    coll.insert_many = insert_many
    return db


ITEMS = [
    {"kind": "missing_referenced_sheet", "sheet": "A-101", "subject": "S-204",
     "detail": "SEE S-204, not in the current set"},
    {"kind": "duplicate_sheet_number", "sheet": "A-102", "subject": "A-102", "track": "filed"},
]


class SetHealth(unittest.TestCase):
    def _pass(self, db, pid, items):
        with patch.object(server, "db", db):
            return _run(server._write_set_health(pid, [dict(i) for i in items]))

    def test_each_finding_queues_once(self):
        db = _health_db()
        self.assertEqual(self._pass(db, "proj_a", ITEMS), 2)
        self._pass(db, "proj_a", ITEMS)            # the next pass: same findings
        rows = _rows(db)
        self.assertEqual(len(rows), 2)
        self.assertEqual({(r["kind"], r["company_id"], r["project_id"]) for r in rows},
                         {(rq.KIND_SET_HEALTH, CO_A, "proj_a")})
        self.assertEqual(sorted(r["evidence"]["finding"] for r in rows),
                         ["duplicate_sheet_number", "missing_referenced_sheet"])
        self.assertEqual(sorted(r["summary"] for r in rows),
                         ["duplicate_sheet_number on A-102",
                          "missing_referenced_sheet on A-101: S-204"])

    def test_a_clean_set_queues_nothing(self):
        db = _health_db()
        from lib import plan_set_health as H
        self._pass(db, "proj_a", [H.clean(NOW)])
        self.assertEqual(_rows(db), [])

    def test_each_project_queues_under_its_company(self):
        db = _health_db()
        self._pass(db, "proj_a", ITEMS[:1])
        self._pass(db, "proj_b", ITEMS[:1])
        self.assertEqual(sorted((r["company_id"], r["project_id"]) for r in _rows(db)),
                         [(CO_A, "proj_a"), (CO_B, "proj_b")])

    def test_a_project_with_no_company_queues_nothing(self):
        db = _health_db()
        self._pass(db, "proj_orphan", ITEMS)
        self.assertEqual(_rows(db), [])


# ══════════════════════════════════════════════════════════════════════════
# registration_refusal: queued from _handle_dm_start
# ══════════════════════════════════════════════════════════════════════════

class Registration(unittest.TestCase):
    def _start(self, c, phone):
        _run(server._open_dm_reply_window(phone))
        _run(server._handle_dm_start(f"{phone}@c.us"))

    def test_a_cp_start_queues_one_item_with_last4_only(self):
        with _Ctx() as c:
            self._start(c, CP_PHONE)
            self._start(c, CP_PHONE)
        rows = _rows(c.db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["kind"], row["company_id"], row["project_id"]),
                         (rq.KIND_REGISTRATION_REFUSAL, CO_A, None))
        self.assertEqual(row["evidence"], {"reason": "role_not_eligible", "user_id": "u_cp",
                                           "chat_last4": CP_PHONE[-4:], "role": "cp"})
        self.assertEqual(row["summary"],
                         f"START refused (role_not_eligible) for a cp from chat …{CP_PHONE[-4:]}")
        _no_full_phone(self, rows, CP_PHONE)

    def test_an_unknown_number_queues_nothing(self):
        with _Ctx() as c:
            self._start(c, UNKNOWN_PHONE)
        self.assertEqual(_rows(c.db), [])

    def test_a_shared_number_queues_once_per_company(self):
        db = _db()
        db.users.rows.append({"_id": "u_dup", "company_id": CO_B,
                              "role": "admin", "phone": ADMIN_PHONE})
        with _Ctx(db) as c:
            self._start(c, ADMIN_PHONE)
        rows = _rows(c.db)
        self.assertEqual(sorted((r["company_id"], r["evidence"]["user_id"]) for r in rows),
                         [(CO_A, "u_admin"), (CO_B, "u_dup")])
        self.assertEqual({r["evidence"]["reason"] for r in rows}, {"ambiguous"})
        # Each company's item names only its own person.
        b = [r for r in rows if r["company_id"] == CO_B]
        self.assertEqual([r["evidence"]["user_id"] for r in b], ["u_dup"])
        _no_full_phone(self, rows, ADMIN_PHONE)

    def test_an_eligible_start_queues_nothing(self):
        with _Ctx() as c:
            self._start(c, ADMIN_PHONE)
        self.assertEqual(_rows(c.db), [])


# ══════════════════════════════════════════════════════════════════════════
# plan_set_question: the L7 (#889) hook
# ══════════════════════════════════════════════════════════════════════════

class PlanSetQuestion(unittest.TestCase):
    Q = {"_id": "q1", "code": "K7Q2", "sheets": ["A.1.1", "A.1.2"],
         "question": "Are A.1.1-A.1.7 part of the filed set?",
         "readings": ["not part of the filed set: 36 type F", "part of it: 72 type F"]}

    def test_a_question_queues_once(self):
        db = FakeDb()
        with patch.object(server, "db", db):
            _run(server._review_queue_plan_set_question(CO_A, "proj_a", dict(self.Q)))
            _run(server._review_queue_plan_set_question(CO_A, "proj_a", dict(self.Q)))
        rows = _rows(db)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["kind"], rows[0]["company_id"], rows[0]["project_id"]),
                         (rq.KIND_PLAN_SET_QUESTION, CO_A, "proj_a"))
        self.assertEqual(rows[0]["evidence"]["sheets"], ["A.1.1", "A.1.2"])

    def test_no_company_no_item(self):
        db = FakeDb()
        with patch.object(server, "db", db):
            _run(server._review_queue_plan_set_question(None, "proj_a", dict(self.Q)))
        self.assertEqual(_rows(db), [])


# ══════════════════════════════════════════════════════════════════════════
# The writer
# ══════════════════════════════════════════════════════════════════════════

class Writer(unittest.TestCase):
    def test_the_id_is_kind_company_subject(self):
        a = rq.item(rq.KIND_SET_HEALTH, CO_A, "k", summary="s", now=NOW)
        self.assertEqual(a["_id"], rq.item_id(rq.KIND_SET_HEALTH, CO_A, "k"))
        self.assertNotEqual(a["_id"], rq.item_id(rq.KIND_SET_HEALTH, CO_B, "k"))
        self.assertIsNone(rq.item(rq.KIND_DISPUTE, CO_A, "k", summary="s", now=NOW))

    def test_it_never_raises(self):
        class Boom:
            async def insert_one(self, doc):
                raise RuntimeError("down")
        db = FakeDb()
        doc = rq.item(rq.KIND_SET_HEALTH, CO_A, "k", summary="s", now=NOW)
        with patch.object(server, "db", {rq.COLLECTION: Boom()}):
            self.assertIsNone(_run(server._review_queue_add(doc)))
        with patch.object(server, "db", db):
            self.assertFalse(_run(server._review_queue_add(None)))
            self.assertFalse(_run(server._review_queue_add({"kind": "set_health"})))
            self.assertFalse(_run(server._review_queue_add({"kind": "other",
                                                            "company_id": CO_A})))
            # Producers given garbage say nothing and raise nothing.
            _run(server._review_queue_answer({"company_id": CO_A, "gates": 7}, None))
            _run(server._review_queue_registration([None, "x"], "ambiguous", None))
            _run(server._review_queue_set_health("proj_a", [None, 3]))
            _run(server._review_queue_plan_set_question(CO_A, "proj_a", {}))
        self.assertEqual(_rows(db), [])

    def test_an_answer_whose_queue_write_fails_is_still_logged(self):
        db = FakeDb()

        async def boom(doc):
            raise RuntimeError("down")
        db[rq.COLLECTION].insert_one = boom
        log_id = _write_answer(db, note_gate=ConflictingSources.GATE)
        self.assertEqual([r["_id"] for r in db.answer_log.rows], [log_id])


def _sources():
    files = [BACKEND / "server.py"]
    for d in ("lib", "scripts"):
        files += sorted((BACKEND / d).rglob("*.py"))
    return files


class OneWriter(unittest.TestCase):
    def test_the_pattern_catches_each_write_shape(self):
        for planted in ('await db.review_queue.update_one({"_id": x}, {})',
                        'await db["review_queue"].delete_many({})',
                        'await db[review_queue.COLLECTION].insert_one(doc)',
                        'await db.review_queue.find_one_and_update({}, {})'):
            self.assertIsNotNone(_WRITE.search(planted), planted)
        self.assertIsNone(_WRITE.search("await db.review_queue.create_index([('status', 1)])"))

    def test_only_review_queue_add_writes_and_only_inserts(self):
        hits = []
        for f in _sources():
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = _WRITE.search(line)
                if m:
                    hits.append((f.relative_to(BACKEND).as_posix(), n, m.group(1)))
        # The insert (the feed) and, since L6.4, the operator's decision: one
        # update_one, in _review_decide, conditional on status "pending".
        self.assertEqual([(h[0], h[2]) for h in hits],
                         [("server.py", "insert_one"), ("server.py", "update_one")])
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
        fns = {node.name: node for node in ast.walk(tree)
               if isinstance(node, ast.AsyncFunctionDef)
               and node.name in ("_review_queue_add", "_review_decide")}
        add, decide = fns["_review_queue_add"], fns["_review_decide"]
        self.assertTrue(add.lineno <= hits[0][1] <= add.end_lineno)
        self.assertTrue(decide.lineno <= hits[1][1] <= decide.end_lineno)
        self.assertIn('"status": review_queue.STATUS_PENDING',
                      ast.unparse(decide).replace("'", '"'))

    def test_it_is_listed_by_status_and_by_company(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertTrue('db.review_queue.create_index([("status", 1), ("created_at", -1)])' in src)
        self.assertTrue('db.review_queue.create_index([("company_id", 1), ("created_at", -1)])'
                        in src)


if __name__ == "__main__":
    unittest.main()
