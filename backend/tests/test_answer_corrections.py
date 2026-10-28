"""Answer corrections: the operator's "Mark wrong" on a logged answer.

  * Gate: require_operator_404 on every route. A company admin, a regular
    user, no token and a bad token get the bare 404 and write nothing.
  * Search: the operator finds any logged answer (question or answer text,
    literal, case-insensitive), across companies, newest first.
  * Mark wrong: the correct answer is required, a note optional. ONE insert
    into answer_corrections with the documented schema, one audit row;
    answer_log is unchanged; nothing is sent to anyone.
  * Append-only: correcting again is a new row, the first one unchanged;
    the only write to the collection anywhere is that one insert.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from bson import ObjectId  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from lib import answer_corrections as ac  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO_A, CO_B = ObjectId(), ObjectId()
A, B = str(CO_A), str(CO_B)
P_A, P_B = ObjectId(), ObjectId()
OP, ADMIN, WORKER = ObjectId(), ObjectId(), ObjectId()
T0 = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)

#: The documented schema (lib/answer_corrections.py), every field.
SCHEMA = {"_id", "schema_version", "answer_log_id", "question", "wrong_answer",
          "correct_answer", "note", "project_ids", "project_id", "company_id", "surface",
          "code_sha", "model", "answer_created_at", "answer_content_hash", "operator_id",
          "ts", "content_hash"}

_WRITE = re.compile(
    r"(?:\banswer_corrections|['\"]answer_corrections['\"]\]|answer_corrections\.COLLECTION\])"
    r"\s*\.\s*(insert_one|insert_many|update_one|update_many|replace_one|delete_one|"
    r"delete_many|find_one_and_update|find_one_and_replace|find_one_and_delete|"
    r"bulk_write|drop)\b")


def _answer(_id, company, minutes, question, final_text, surface="dm", pids=None):
    return {"_id": _id, "surface": surface, "company_id": company, "user_id": "u1",
            "question": question, "final_text": final_text,
            "project_ids": pids if pids is not None else [str(P_A)],
            "records": [{"id": "r1", "sheet": "A-101", "text": "DOOR 101 3'-0\""}],
            "gates": [], "tools": [], "model": "model-under-test", "code_sha": "abc1234",
            "created_at": T0 + timedelta(minutes=minutes), "content_hash": "h-" + _id}


def _db():
    return FakeDb(
        companies=[{"_id": CO_A, "name": "ACME BUILDERS"}, {"_id": CO_B, "name": "OTHER CO"}],
        users=[
            {"_id": OP, "email": "ops@levelog.test", "role": "admin",
             "account_status": "approved", "is_platform_operator": True},
            {"_id": ADMIN, "email": "admin@acme.test", "role": "admin", "company_id": A,
             "account_status": "approved"},
            {"_id": WORKER, "email": "w@acme.test", "role": "worker", "company_id": A,
             "account_status": "approved"},
        ],
        answer_log=[
            _answer("al_a", A, 1, "Door 101 width?", "Door 101 is 3'-0\" wide (A-101)."),
            _answer("al_b", B, 2, "slab thickness?", "8 inches (S-201).", surface="group",
                    pids=[str(P_B), str(P_A)]),
            _answer("al_c", A, 3, "who was on site?", "Call 0000000100 for the roster.",
                    surface="app", pids=[]),
        ],
        answer_corrections=[],
        audit_logs=[],
    )


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = _db()
        self.sent = []

        async def send(*a, **k):
            self.sent.append(a)
            return {"ok": 1}
        self.patches = [patch.object(server, "db", self.db),
                        patch.object(server, "send_whatsapp_dm", send),
                        patch.object(server, "send_whatsapp_message", send)]
        for p in self.patches:
            p.start()
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def h(self, uid, role="admin", company=A):
        return {"Authorization": f"Bearer {server.create_token(str(uid), 'x@x.test', role, company_id=company)}"}

    def op(self):
        return self.h(OP)

    def correct(self, answer_id, headers=None, **body):
        return self.client.post(f"/api/owner/answers/{answer_id}/corrections",
                                headers=headers if headers is not None else self.op(), json=body)


class TheGate(_Base):
    ROUTES = [("GET", "/api/owner/answers", None),
              ("GET", "/api/owner/answers?q=door", None),
              ("GET", "/api/owner/answers/al_a", None),
              ("POST", "/api/owner/answers/al_a/corrections",
               {"correct_answer": "3'-6\" per A-101 rev 2", "note": "x"})]

    def test_every_route_carries_require_operator_404_first(self):
        paths = {"/api/owner/answers", "/api/owner/answers/{answer_log_id}",
                 "/api/owner/answers/{answer_log_id}/corrections"}
        seen = set()
        for r in server.app.routes:
            if getattr(r, "path", None) in paths:
                seen.add(r.path)
                self.assertIs(r.dependant.dependencies[0].call, server.require_operator_404, r.path)
        self.assertEqual(seen, paths)

    def test_admin_regular_user_and_no_token_get_404_and_write_nothing(self):
        for who, headers in (("company admin", self.h(ADMIN)),
                             ("regular user", self.h(WORKER, role="worker")),
                             ("no token", {}),
                             ("bad token", {"Authorization": "Bearer nope"})):
            for method, path, body in self.ROUTES:
                with self.subTest(who=who, route=f"{method} {path}"):
                    r = self.client.request(method, path, headers=headers, json=body)
                    self.assertEqual(r.status_code, 404)
                    self.assertEqual(r.json(), {"detail": "Not Found"})
                    self.assertNotIn("Door 101", r.text)
        self.assertEqual(self.db.answer_corrections.rows, [])
        self.assertEqual(self.db.audit_logs.rows, [])


class TheSearch(_Base):
    def ids(self, **params):
        r = self.client.get("/api/owner/answers", headers=self.op(), params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return [i["answer"]["id"] for i in r.json()["items"]]

    def test_newest_first_across_companies(self):
        self.assertEqual(self.ids(), ["al_c", "al_b", "al_a"])

    def test_q_matches_question_or_answer_literally_any_case(self):
        self.assertEqual(self.ids(q="door"), ["al_a"])
        self.assertEqual(self.ids(q="S-201"), ["al_b"])
        self.assertEqual(self.ids(q="3'-0\""), ["al_a"])
        self.assertEqual(self.ids(q=".*"), [], "a regex is matched literally")

    def test_filters_and_paging(self):
        self.assertEqual(self.ids(company_id=B), ["al_b"])
        self.assertEqual(self.ids(surface="app"), ["al_c"])
        r = self.client.get("/api/owner/answers", headers=self.op(), params={"limit": 2}).json()
        self.assertTrue(r["has_more"])
        self.assertEqual(self.ids(limit=2, offset=2), ["al_a"])
        self.assertEqual(self.client.get("/api/owner/answers", headers=self.op(),
                                         params={"surface": "email"}).status_code, 422)

    def test_an_item_carries_company_and_correction_count(self):
        self.correct("al_a", correct_answer="Door 101 is 3'-6\" (A-101 rev 2).")
        items = {i["answer"]["id"]: i for i in self.client.get(
            "/api/owner/answers", headers=self.op()).json()["items"]}
        self.assertEqual(items["al_a"]["company"], {"id": A, "name": "ACME BUILDERS"})
        self.assertEqual(items["al_a"]["corrections_count"], 1)
        self.assertEqual(items["al_b"]["corrections_count"], 0)

    def test_no_phone_in_full(self):
        r = self.client.get("/api/owner/answers", headers=self.op())
        self.assertNotIn("0000000100", r.text)
        self.assertIn("[…0100]", r.text)

    def test_one_answer_in_full_and_404(self):
        r = self.client.get("/api/owner/answers/al_a", headers=self.op())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["answer"]["question"], "Door 101 width?")
        self.assertEqual(r.json()["corrections"], [])
        self.assertIn("tools", r.json()["answer"])
        self.assertEqual(self.client.get("/api/owner/answers/nope",
                                         headers=self.op()).status_code, 404)


class MarkWrong(_Base):
    def test_the_correct_answer_is_required(self):
        for body in ({}, {"correct_answer": ""}, {"correct_answer": "   "},
                     {"correct_answer": "x"}, {"note": "only a note"},
                     {"correct_answer": "ok answer", "note": "n" * (ac.MAX_NOTE + 1)}):
            with self.subTest(body=body):
                self.assertEqual(self.correct("al_a", **body).status_code, 422)
        self.assertEqual(self.correct("nope", correct_answer="something").status_code, 404)
        self.assertEqual(self.db.answer_corrections.rows, [])
        self.assertEqual(self.db.audit_logs.rows, [])

    def test_one_row_with_the_documented_schema_and_one_audit_row(self):
        before = copy.deepcopy(self.db.answer_log.rows)
        r = self.correct("al_a", correct_answer="  Door 101 is 3'-6\" (A-101 rev 2).  ",
                         note="Rev 2 changed the door schedule.")
        self.assertEqual(r.status_code, 200, r.text)
        rows = self.db.answer_corrections.rows
        self.assertEqual(len(rows), 1)
        c = rows[0]
        self.assertEqual(set(c), SCHEMA)
        self.assertEqual({k: c[k] for k in (
            "schema_version", "answer_log_id", "question", "wrong_answer", "correct_answer",
            "note", "project_ids", "project_id", "company_id", "surface", "code_sha", "model",
            "answer_content_hash", "operator_id")}, {
            "schema_version": 1, "answer_log_id": "al_a", "question": "Door 101 width?",
            "wrong_answer": "Door 101 is 3'-0\" wide (A-101).",
            "correct_answer": "Door 101 is 3'-6\" (A-101 rev 2).",
            "note": "Rev 2 changed the door schedule.", "project_ids": [str(P_A)],
            "project_id": str(P_A), "company_id": A, "surface": "dm", "code_sha": "abc1234",
            "model": "model-under-test", "answer_content_hash": "h-al_a",
            "operator_id": str(OP)})
        self.assertEqual(c["answer_created_at"], T0 + timedelta(minutes=1))
        self.assertIsInstance(c["ts"], datetime)
        self.assertEqual(c["content_hash"], ac.content_hash(c))
        self.assertEqual(r.json()["correction"]["id"], c["_id"])
        audits = [a for a in self.db.audit_logs.rows if a["action"] == "answer_correction"]
        self.assertEqual(len(audits), 1)
        self.assertEqual((audits[0]["user_id"], audits[0]["resource_type"],
                          audits[0]["resource_id"]), (str(OP), "answer_log", "al_a"))
        self.assertEqual(audits[0]["details"]["correction_id"], c["_id"])
        self.assertEqual(self.db.answer_log.rows, before, "answer_log never touched")
        self.assertEqual(self.sent, [], "nothing is sent to anyone")

    def test_no_note_is_none_and_several_projects_no_single_project(self):
        self.assertEqual(self.correct("al_b", correct_answer="10 inches (S-201 rev 1)")
                         .status_code, 200)
        c = self.db.answer_corrections.rows[0]
        self.assertIsNone(c["note"])
        self.assertEqual((c["project_ids"], c["project_id"]), ([str(P_B), str(P_A)], None))
        self.assertEqual((c["company_id"], c["surface"]), (B, "group"))

    def test_append_only_correcting_again_is_a_new_row(self):
        self.correct("al_a", correct_answer="Door 101 is 3'-6\".")
        first = copy.deepcopy(self.db.answer_corrections.rows[0])
        r = self.correct("al_a", correct_answer="Door 101 is 3'-4\" per the field note.",
                         note="Field measured.")
        self.assertEqual(r.status_code, 200)
        rows = self.db.answer_corrections.rows
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], first, "the first correction is unchanged")
        self.assertEqual([c["correct_answer"] for c in r.json()["corrections"]],
                         ["Door 101 is 3'-6\".", "Door 101 is 3'-4\" per the field note."])
        got = self.client.get("/api/owner/answers/al_a", headers=self.op()).json()
        self.assertEqual(len(got["corrections"]), 2)
        self.assertEqual(len([a for a in self.db.audit_logs.rows
                              if a["action"] == "answer_correction"]), 2)

    def test_no_phone_in_full_in_the_row(self):
        self.correct("al_c", correct_answer="Ask the super at 0000000200.",
                     note="Number 0000000300 is the office.")
        blob = json.dumps(self.db.answer_corrections.rows, default=str, ensure_ascii=False)
        for d in ("0000000100", "0000000200", "0000000300"):
            self.assertNotIn(d, blob)
        self.assertIn("[…0200]", blob)


class IdsAndDatesSurvive(_Base):
    """Ids, hashes and dates are never redacted (a sha256 or an ObjectId can
    hold 7 digits in a row): only the text fields are."""

    def test_ids_hashes_and_ts_come_back_as_stored(self):
        digit_id = "1234567" * 3 + "abc"
        self.db.answer_log.rows.append(_answer(digit_id, A, 9, "q 2125550199?", "a"))
        r = self.correct(digit_id, correct_answer="the right answer")
        self.assertEqual(r.status_code, 200, r.text)
        c = r.json()["correction"]
        row = self.db.answer_corrections.rows[0]
        self.assertEqual(c["answer_log_id"], digit_id)
        self.assertEqual(c["id"], row["_id"])
        self.assertEqual(c["content_hash"], row["content_hash"])
        self.assertEqual(c["ts"], row["ts"].isoformat())
        self.assertEqual(c["question"], "q […0199]?")
        items = self.client.get("/api/owner/answers", headers=self.op()).json()["items"]
        self.assertEqual(items[0]["answer"]["id"], digit_id)
        self.assertEqual(self.client.get(f"/api/owner/answers/{digit_id}",
                                         headers=self.op()).status_code, 200)

    def test_past_the_offset_cap_is_a_422(self):
        from lib import review_queue as rq
        self.assertEqual(self.client.get("/api/owner/answers", headers=self.op(), params={
            "offset": rq.MAX_OFFSET + 1}).status_code, 422)


class AppendOnly(unittest.TestCase):
    def _sources(self):
        files = [BACKEND / "server.py"]
        for d in ("lib", "scripts"):
            files += sorted((BACKEND / d).rglob("*.py"))
        return files

    def test_the_pattern_catches_each_write_shape(self):
        for planted in ('await db.answer_corrections.update_one({"_id": x}, {})',
                        'await db["answer_corrections"].delete_many({})',
                        'await db[answer_corrections.COLLECTION].insert_one(doc)',
                        'await db.answer_corrections.find_one_and_update({}, {})'):
            self.assertIsNotNone(_WRITE.search(planted), planted)
        self.assertIsNone(_WRITE.search("await db.answer_corrections.create_index([('ts', 1)])"))

    def test_the_only_write_is_one_insert_in_the_one_writer(self):
        hits = []
        for f in self._sources():
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = _WRITE.search(line)
                if m:
                    hits.append((f.relative_to(BACKEND).as_posix(), n, m.group(1)))
        self.assertEqual([(h[0], h[2]) for h in hits], [("server.py", "insert_one")])
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
        fn = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_answer_correction_write")
        self.assertTrue(fn.lineno <= hits[0][1] <= fn.end_lineno)


class Pure(unittest.TestCase):
    def test_check(self):
        self.assertIsNone(ac.check("3'-6\""))
        self.assertIsNotNone(ac.check(" "))
        self.assertIsNotNone(ac.check("a" * (ac.MAX_CORRECT + 1)))

    def test_the_hash_survives_a_mongo_round_trip(self):
        """BSON keeps milliseconds and the driver reads back naive UTC: the
        hash of the row as read must equal the hash written (Codex, #906)."""
        from datetime import timezone as tz
        row = _answer("al_x", A, 0, "q?", "wrong")
        now = datetime(2026, 10, 28, 9, 1, 2, 345678, tzinfo=tz.utc)
        doc = ac.build(row, "right", None, operator_id=OP, now=now, _id="c1")
        self.assertEqual(doc["ts"].microsecond, 345000)
        read_back = dict(doc, ts=doc["ts"].replace(tzinfo=None),
                         answer_created_at=doc["answer_created_at"].replace(tzinfo=None))
        self.assertEqual(ac.content_hash(read_back), doc["content_hash"])

    def test_the_hash_covers_the_correction(self):
        row = _answer("al_x", A, 0, "q?", "wrong")
        a = ac.build(row, "right", None, operator_id=OP, now=T0, _id="c1")
        b = ac.build(row, "right!", None, operator_id=OP, now=T0, _id="c1")
        self.assertNotEqual(a["content_hash"], b["content_hash"])
        self.assertEqual(a["content_hash"], ac.content_hash(a))


if __name__ == "__main__":
    unittest.main()
