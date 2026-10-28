"""The operator's review queue (L6.4): /api/owner/review-queue routes.

  * Gate: require_operator_404 (#790 / the owner portal) on every route. A
    company admin and a regular user get exactly its bare 404 on every
    route, with real item ids, and no review field anywhere in the body.
  * The operator lists the queue newest first, across companies, with each
    answer_log row's question, final text, records, gates, model and code
    sha -- each read with the ITEM's company (a row of another company is
    never joined).
  * Default view "Needs decision": pending, normal priority (low hidden);
    reason / priority / kind / company filters.
  * Decide: an explanation is required; the decision writes status + one
    audit row; answer_log is byte-for-byte unchanged. A decided item may be
    decided again with a NEW explanation (its own audit row, appended to
    `decisions`); the same explanation again is a 409 SAME_EXPLANATION.
    Nobody is notified: no message is sent by any decision.
"""

from __future__ import annotations

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
from lib import review_queue as rq  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO_A, CO_B = ObjectId(), ObjectId()
A, B = str(CO_A), str(CO_B)
P_A = ObjectId()
OP, ADMIN, WORKER, ASKER = ObjectId(), ObjectId(), ObjectId(), ObjectId()
T0 = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)

#: Keys that are review state. None may appear in a non-operator's body.
REVIEW_KEYS = {"status", "decision", "explanation", "approve", "deny", "items", "item",
               "reason", "priority", "answer", "evidence"}
#: Review words as whole JSON string values (anchored by the quotes).
_REVIEW_VALUE = re.compile(r'"(?:pending|approved|denied|approve|deny)"')


def _keys(v, out=None):
    out = set() if out is None else out
    if isinstance(v, dict):
        for k, x in v.items():
            out.add(k)
            _keys(x, out)
    elif isinstance(v, list):
        for x in v:
            _keys(x, out)
    return out


def _answer(_id, company, minutes, question, final_text):
    return {"_id": _id, "surface": "dm", "company_id": company, "user_id": str(ASKER),
            "question": question, "final_text": final_text, "project_ids": [str(P_A)],
            "records": [{"id": "r1", "sheet": "A-101", "text": "DOOR 101 3'-0\" x 7'-0\""}],
            "gates": [{"gate": "plan_answer_gate", "outcome": "grounded"}],
            "tools": [], "model": "model-under-test", "code_sha": "abc1234",
            "created_at": T0 + timedelta(minutes=minutes), "content_hash": "h-" + _id}


def _db():
    return FakeDb(
        companies=[{"_id": CO_A, "name": "ACME BUILDERS"}, {"_id": CO_B, "name": "OTHER CO"}],
        projects=[{"_id": P_A, "name": "12 Main St", "company_id": A}],
        users=[
            {"_id": OP, "email": "ops@levelog.test", "role": "admin",
             "account_status": "approved", "is_platform_operator": True},
            {"_id": ADMIN, "email": "admin@acme.test", "role": "admin", "company_id": A,
             "account_status": "approved"},
            {"_id": WORKER, "email": "w@acme.test", "role": "worker", "company_id": A,
             "account_status": "approved"},
            {"_id": ASKER, "email": "pm@acme.test", "name": "Pat PM", "role": "pm",
             "company_id": A, "account_status": "approved"},
        ],
        answer_log=[
            _answer("al_a", A, 1, "door 101 width?", "Door 101 is 3'-0\" wide (A-101)."),
            _answer("al_b", B, 2, "slab thickness?", "8 inches (S-201)."),
        ],
        review_queue=[
            {"_id": "q_conf", "kind": "conflicting_sources", "company_id": A,
             "project_id": str(P_A), "answer_log_id": "al_a",
             "summary": "plan_gate:ungrounded on door 101", "reason": "conflict",
             "priority": "normal", "evidence": {"reasons": ["plan_gate:ungrounded"]},
             "created_at": T0 + timedelta(minutes=9), "status": "pending"},
            {"_id": "q_info", "kind": "set_health", "company_id": B, "project_id": None,
             "answer_log_id": None, "summary": "set_health_info on A-001",
             "reason": "set_health_info", "priority": "low", "evidence": {},
             "created_at": T0 + timedelta(minutes=11), "status": "pending"},
            {"_id": "q_repl", "kind": "conflicting_sources", "company_id": B,
             "answer_log_id": "al_b", "summary": "plan_gate:label_leak",
             "reason": "replaced", "priority": "normal", "evidence": {},
             "created_at": T0 + timedelta(minutes=8), "status": "pending"},
            {"_id": "q_old", "kind": "registration_refusal", "company_id": A,
             "summary": "START refused (phone_missing)", "evidence": {},
             "reason": "registration", "priority": "normal",
             "created_at": T0 + timedelta(minutes=5), "status": "pending"},
        ],
        audit_logs=[],
    )


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = _db()
        self.sent = []

        async def dm(*a, **k):
            self.sent.append(a)
            return {"ok": 1}

        async def wa(*a, **k):
            self.sent.append(a)
            return {"ok": 1}
        self.patches = [patch.object(server, "db", self.db),
                        patch.object(server, "send_whatsapp_dm", dm),
                        patch.object(server, "send_whatsapp_message", wa)]
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

    def get(self, path, headers, **params):
        return self.client.get(f"/api/owner/review-queue{path}", headers=headers, params=params)

    def decide(self, item, headers, **body):
        return self.client.post(f"/api/owner/review-queue/{item}/decide",
                                headers=headers, json=body)


class TheGate(_Base):
    """Every route, a company admin and a regular user: the gate's 404."""

    def _routes(self):
        return [("GET", "/api/owner/review-queue", None),
                ("GET", "/api/owner/review-queue?status=approved&priority=all", None),
                ("GET", "/api/owner/review-queue/q_conf", None),
                ("POST", "/api/owner/review-queue/q_conf/decide",
                 {"decision": "deny", "explanation": "the gate was right here"})]

    def test_every_route_carries_require_operator_404_first(self):
        paths = {"/api/owner/review-queue", "/api/owner/review-queue/{item_id}",
                 "/api/owner/review-queue/{item_id}/decide"}
        seen = set()
        for r in server.app.routes:
            if getattr(r, "path", None) in paths:
                seen.add(r.path)
                self.assertIs(r.dependant.dependencies[0].call, server.require_operator_404, r.path)
        self.assertEqual(seen, paths)

    def test_admin_and_regular_user_get_the_gates_404_and_no_review_field(self):
        for who, headers in (("company admin", self.h(ADMIN)),
                             ("regular user", self.h(WORKER, role="worker")),
                             ("no token", {}),
                             ("bad token", {"Authorization": "Bearer nope"})):
            for method, path, body in self._routes():
                with self.subTest(who=who, route=f"{method} {path}"):
                    r = self.client.request(method, path, headers=headers, json=body)
                    self.assertEqual(r.status_code, 404)
                    self.assertEqual(r.json(), {"detail": "Not Found"})
                    self.assertEqual(_keys(r.json()) & REVIEW_KEYS, set())
                    self.assertIsNone(_REVIEW_VALUE.search(r.text))
        # Nothing was decided or audited by any of them.
        self.assertEqual({d["status"] for d in self.db.review_queue.rows}, {"pending"})
        self.assertEqual(self.db.audit_logs.rows, [])


class TheList(_Base):
    def test_default_is_needs_decision_newest_first(self):
        r = self.get("", self.op())
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        # q_info is low priority (set_health_info): hidden by default.
        self.assertEqual([i["id"] for i in out["items"]], ["q_conf", "q_repl", "q_old"])
        d = out["items"][0]
        self.assertEqual((d["kind"], d["reason"], d["priority"]),
                         ("conflicting_sources", "conflict", "normal"))
        self.assertEqual(d["company"], {"id": A, "name": "ACME BUILDERS"})
        self.assertEqual(d["project"], {"id": str(P_A), "name": "12 Main St"})
        ans = d["answer"]
        self.assertEqual((ans["question"], ans["final_text"], ans["model"], ans["code_sha"]),
                         ("door 101 width?", "Door 101 is 3'-0\" wide (A-101).",
                          "model-under-test", "abc1234"))
        self.assertEqual(ans["records"][0]["sheet"], "A-101")
        self.assertEqual(ans["gates"], [{"gate": "plan_answer_gate", "outcome": "grounded"}])
        self.assertNotIn("dispute", out["kinds"])
        self.assertNotIn("dispute", out["reasons"])
        self.assertEqual({c["name"] for c in out["companies"]}, {"ACME BUILDERS", "OTHER CO"})

    def test_low_priority_and_filters(self):
        ids = lambda **p: [i["id"] for i in self.get("", self.op(), **p).json()["items"]]  # noqa: E731
        self.assertEqual(ids(priority="low"), ["q_info"])
        self.assertEqual(ids(priority="all"), ["q_info", "q_conf", "q_repl", "q_old"])
        self.assertEqual(ids(reason="conflict"), ["q_conf"])
        self.assertEqual(ids(kind="conflicting_sources"), ["q_conf", "q_repl"])
        self.assertEqual(ids(company_id=B, priority="all"), ["q_info", "q_repl"])
        self.assertEqual(ids(status="approved"), [])
        for bad in ({"kind": "nope"}, {"kind": "dispute"}, {"reason": "dispute"},
                    {"priority": "urgent"}, {"status": "open"}):
            with self.subTest(bad=bad):
                self.assertEqual(self.get("", self.op(), **bad).status_code, 422)

    def test_paged(self):
        a = self.get("", self.op(), limit=2).json()
        b = self.get("", self.op(), limit=2, offset=2).json()
        self.assertEqual([i["id"] for i in a["items"]], ["q_conf", "q_repl"])
        self.assertTrue(a["has_more"])
        self.assertEqual([i["id"] for i in b["items"]], ["q_old"])
        self.assertFalse(b["has_more"])

    def test_each_answer_is_read_with_its_items_company(self):
        """An item of company B naming company A's answer id is shown with no
        answer: the answer_log read is that item's company's only."""
        self.db.review_queue.rows.append(
            {"_id": "q_cross", "kind": "conflicting_sources", "answer_log_id": "al_a",
             "company_id": B, "summary": "x", "reason": "unverified", "priority": "normal",
             "status": "pending", "created_at": T0 + timedelta(minutes=30)})
        items = {i["id"]: i for i in self.get("", self.op()).json()["items"]}
        self.assertIsNone(items["q_cross"]["answer"])
        self.assertEqual(items["q_repl"]["answer"]["question"], "slab thickness?")
        self.assertEqual(items["q_repl"]["company"]["name"], "OTHER CO")

    def test_one_item_has_full_evidence(self):
        r = self.get("/q_conf", self.op())
        self.assertEqual(r.status_code, 200)
        it = r.json()["item"]
        self.assertEqual(it["evidence"], {"reasons": ["plan_gate:ungrounded"]})
        self.assertEqual(it["answer"]["records_total"], 1)
        self.assertIn("tools", it["answer"])
        self.assertEqual(self.get("/nope", self.op()).status_code, 404)


class TheDecision(_Base):
    def test_an_explanation_is_required(self):
        for body in ({"decision": "approve"}, {"decision": "approve", "explanation": "   "},
                     {"decision": "deny", "explanation": "too short"},
                     {"decision": "maybe", "explanation": "a long enough reason"}, {}):
            with self.subTest(body=body):
                r = self.decide("q_conf", self.op(), **body)
                self.assertEqual(r.status_code, 422)
        self.assertEqual(self.db.review_queue.rows[0]["status"], "pending")
        self.assertEqual(self.db.audit_logs.rows, [])

    def test_decide_writes_status_and_one_audit_row_and_never_touches_answer_log(self):
        before = copy.deepcopy(self.db.answer_log.rows)
        r = self.decide("q_conf", self.op(), decision="approve",
                        explanation="Sheet A-101 says 3'-6\"; the answer read the wrong door.")
        self.assertEqual(r.status_code, 200, r.text)
        row = next(d for d in self.db.review_queue.rows if d["_id"] == "q_conf")
        self.assertEqual(row["status"], "approved")
        self.assertEqual((row["decision"]["decision"], row["decision"]["operator_id"]),
                         ("approve", str(OP)))
        self.assertNotIn("notify", row["decision"])
        self.assertEqual(r.json()["item"]["decision"]["decision"], "approve")
        self.assertNotIn("notify", r.json())
        audits = [a for a in self.db.audit_logs.rows if a["action"] == "review_decision"]
        self.assertEqual(len(audits), 1)
        a = audits[0]
        self.assertEqual((a["user_id"], a["resource_type"], a["resource_id"]),
                         (str(OP), "review_queue", "q_conf"))
        self.assertEqual({k: a["details"][k] for k in ("kind", "reason", "decision")},
                         {"kind": "conflicting_sources", "reason": "conflict",
                          "decision": "approve"})
        self.assertTrue(a["details"]["explanation"].startswith("Sheet A-101"))
        self.assertIsInstance(a["timestamp"], datetime)
        self.assertEqual(self.db.answer_log.rows, before)
        self.assertEqual(len(row["decisions"]), 1)
        self.assertEqual(self.sent, [], "no decision sends anything")
        # It leaves the Needs decision view.
        self.assertNotIn("q_conf", [i["id"] for i in self.get("", self.op()).json()["items"]])
        self.assertEqual([i["id"] for i in self.get("", self.op(), status="approved")
                          .json()["items"]], ["q_conf"])

    def test_re_decide_twice_two_audit_rows_and_a_history(self):
        before = copy.deepcopy(self.db.answer_log.rows)
        r1 = self.decide("q_conf", self.op(), decision="approve",
                         explanation="Sheet A-101 says 3'-6\"; wrong door read.")
        self.assertEqual(r1.status_code, 200, r1.text)
        r2 = self.decide("q_conf", self.op(), decision="deny",
                         explanation="Rechecked: A-101 rev 2 says 3'-0\"; it stands.")
        self.assertEqual(r2.status_code, 200, r2.text)
        row = next(d for d in self.db.review_queue.rows if d["_id"] == "q_conf")
        self.assertEqual(row["status"], "denied")
        self.assertEqual([d["decision"] for d in row["decisions"]], ["approve", "deny"])
        self.assertEqual([d["decision"] for d in r2.json()["item"]["decisions"]],
                         ["approve", "deny"])
        audits = [a for a in self.db.audit_logs.rows if a["action"] == "review_decision"]
        self.assertEqual([(a["details"]["decision"], a["details"]["decision_number"],
                           a["details"]["previous_decision"]) for a in audits],
                         [("approve", 1, None), ("deny", 2, "approve")])
        r3 = self.decide("q_conf", self.op(), decision="approve",
                         explanation="Third look: the field note confirms 3'-6\".")
        self.assertEqual(r3.status_code, 200, r3.text)
        row = next(d for d in self.db.review_queue.rows if d["_id"] == "q_conf")
        self.assertEqual(len(row["decisions"]), 3)
        self.assertEqual(self.db.answer_log.rows, before, "answer_log never touched")
        self.assertEqual(self.sent, [])

    def test_re_decide_needs_a_new_explanation(self):
        expl = "Checked A-101: the answer stands."
        self.assertEqual(self.decide("q_conf", self.op(), decision="deny",
                                     explanation=expl).status_code, 200)
        for e in (expl, "  checked a-101:   the answer STANDS. "):
            r = self.decide("q_conf", self.op(), decision="approve", explanation=e)
            self.assertEqual(r.status_code, 409)
            self.assertEqual(r.json()["detail"]["code"], "SAME_EXPLANATION")
        r = self.decide("q_conf", self.op(), decision="approve", explanation="short")
        self.assertEqual(r.status_code, 422, "a missing / short explanation is still a 422")
        row = next(d for d in self.db.review_queue.rows if d["_id"] == "q_conf")
        self.assertEqual((row["status"], len(row["decisions"])), ("denied", 1))
        self.assertEqual(len(self.db.audit_logs.rows), 1)

    def test_a_row_decided_before_the_history_keeps_its_first_decision(self):
        row = next(d for d in self.db.review_queue.rows if d["_id"] == "q_conf")
        row.update(status="approved", decision={
            "decision": "approve", "explanation": "an older decision text",
            "operator_id": str(OP), "decided_at": T0})
        r = self.decide("q_conf", self.op(), decision="deny",
                        explanation="A newer look at sheet A-101.")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([d["explanation"] for d in row["decisions"]],
                         ["an older decision text", "A newer look at sheet A-101."])

    def test_decided_meanwhile_is_a_409_and_writes_nothing(self):
        real = server._review_item
        calls = {"n": 0}

        async def stale(item_id):
            doc = await real(item_id)
            calls["n"] += 1
            if calls["n"] == 1:
                # Someone else decides between this read and the write.
                live = next(d for d in self.db.review_queue.rows if d["_id"] == item_id)
                live["decisions"] = [{"decision": "deny", "explanation": "other operator"}]
                live["status"] = "denied"
            return doc
        with patch.object(server, "_review_item", stale):
            r = self.decide("q_conf", self.op(), decision="approve",
                            explanation="The sheet disagrees with it.")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["code"], "DECIDED_MEANWHILE")
        self.assertEqual(self.db.audit_logs.rows, [])

    def test_a_low_priority_item_decides_too(self):
        r = self.decide("q_info", self.op(), decision="deny",
                        explanation="Informational only; nothing to fix.")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(next(q for q in self.db.review_queue.rows
                              if q["_id"] == "q_info")["status"], "denied")


class Pure(unittest.TestCase):
    def test_check_decision(self):
        self.assertIsNone(rq.check_decision("approve", "ten chars!"))
        self.assertIsNotNone(rq.check_decision("approve", "  short  "))
        self.assertIsNotNone(rq.check_decision("ok", "long enough reason"))

    def test_no_notify_text_and_no_dispute_kind(self):
        self.assertFalse(hasattr(rq, "NOTIFY_TEXT"))
        self.assertFalse(hasattr(rq, "notify_text"))
        self.assertNotIn("dispute", rq.KINDS)

    def test_the_view_carries_no_phone(self):
        v = rq.item_view({"_id": "x", "kind": "registration_refusal",
                          "summary": "chat 0000000100 refused"})
        self.assertEqual(v["summary"], "chat […0100] refused")
        self.assertIsNone(re.search(r"\d{7,}", json.dumps(v, ensure_ascii=False)))


if __name__ == "__main__":
    unittest.main()
