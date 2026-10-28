"""The operator's review queue (L6.4): /api/owner/review-queue routes.

  * Gate: require_operator_404 (#790 / the owner portal) on every route. A
    company admin and a regular user get exactly its bare 404 on every
    route, with real item ids, and no review field anywhere in the body.
  * The operator lists BOTH sources (answer_disputes and review_queue),
    newest first, across companies, with each answer_log row's question,
    final text, records, gates, model and code sha -- each read with the
    ITEM's company (a row of another company is never joined).
  * Default view "Needs decision": pending, normal priority (low hidden);
    reason / priority / kind / company filters.
  * Decide: an explanation is required; the decision writes status + one
    audit row; answer_log is byte-for-byte unchanged; a second decision is
    a 409. Notify sends exactly one plain line to a dispute's asker and
    nothing for a group dispute (no user_id) or a queue item.
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
               "reason", "priority", "notify", "answer", "evidence"}
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
        answer_disputes=[
            {"_id": "d_dm", "answer_log_id": "al_a", "company_id": A, "user_id": str(ASKER),
             "surface": "dm", "text": "that's wrong, it's 3'-6\"",
             "created_at": T0 + timedelta(minutes=10), "status": "pending"},
            # A group dispute: the asker is known by key only (no user_id).
            {"_id": "d_grp", "answer_log_id": "al_b", "company_id": B,
             "asker_key": "k1", "surface": "dm", "text": "incorrect",
             "created_at": T0 + timedelta(minutes=8), "status": "pending"},
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
        self.patches = [patch.object(server, "db", self.db)]
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

    def decide(self, source, item, headers, **body):
        return self.client.post(f"/api/owner/review-queue/{source}/{item}/decide",
                                headers=headers, json=body)


class TheGate(_Base):
    """Every route, a company admin and a regular user: the gate's 404."""

    def _routes(self):
        return [("GET", "/api/owner/review-queue", None),
                ("GET", "/api/owner/review-queue?status=approved&priority=all", None),
                ("GET", "/api/owner/review-queue/dispute/d_dm", None),
                ("GET", "/api/owner/review-queue/queue/q_conf", None),
                ("POST", "/api/owner/review-queue/dispute/d_dm/decide",
                 {"decision": "approve", "explanation": "the plans say 3'-6\"", "notify": True}),
                ("POST", "/api/owner/review-queue/queue/q_conf/decide",
                 {"decision": "deny", "explanation": "the gate was right here"})]

    def test_every_route_carries_require_operator_404_first(self):
        paths = {"/api/owner/review-queue", "/api/owner/review-queue/{source}/{item_id}",
                 "/api/owner/review-queue/{source}/{item_id}/decide"}
        seen = set()
        for r in server.app.routes:
            if getattr(r, "path", None) in paths:
                seen.add(r.path)
                self.assertIs(r.dependant.dependencies[0].call, server.require_operator_404, r.path)
        self.assertEqual(seen, paths)

    def test_admin_and_regular_user_get_the_gates_404_and_no_review_field(self):
        sent = []

        async def dm(*a, **k):
            sent.append(a)
            return {"ok": 1}
        with patch.object(server, "send_whatsapp_dm", dm):
            for who, headers in (("company admin", self.h(ADMIN)),
                                 ("regular user", self.h(WORKER, role="worker")),
                                 ("no token", {})):
                for method, path, body in self._routes():
                    with self.subTest(who=who, route=f"{method} {path}"):
                        r = self.client.request(method, path, headers=headers, json=body)
                        self.assertEqual(r.status_code, 404)
                        self.assertEqual(r.json(), {"detail": "Not Found"})
                        self.assertEqual(_keys(r.json()) & REVIEW_KEYS, set())
                        self.assertIsNone(_REVIEW_VALUE.search(r.text))
        # Nothing was decided, sent or audited by any of them.
        self.assertEqual({d["status"] for d in self.db.answer_disputes.rows}, {"pending"})
        self.assertEqual({d["status"] for d in self.db.review_queue.rows}, {"pending"})
        self.assertEqual(sent, [])
        self.assertEqual(self.db.audit_logs.rows, [])


class TheList(_Base):
    def test_default_is_needs_decision_both_sources_newest_first(self):
        r = self.get("", self.op())
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        # q_info is low priority (set_health_info): hidden by default.
        self.assertEqual([i["id"] for i in out["items"]], ["d_dm", "q_conf", "d_grp", "q_old"])
        self.assertEqual({i["source"] for i in out["items"]}, {"dispute", "queue"})
        d = out["items"][0]
        self.assertEqual((d["kind"], d["reason"], d["priority"]), ("dispute", "dispute", "normal"))
        self.assertEqual(d["company"], {"id": A, "name": "ACME BUILDERS"})
        self.assertEqual(d["project"], {"id": str(P_A), "name": "12 Main St"})
        self.assertEqual(d["asker"]["name"], "Pat PM")
        self.assertEqual(d["summary"], "that's wrong, it's 3'-6\"")
        ans = d["answer"]
        self.assertEqual((ans["question"], ans["final_text"], ans["model"], ans["code_sha"]),
                         ("door 101 width?", "Door 101 is 3'-0\" wide (A-101).",
                          "model-under-test", "abc1234"))
        self.assertEqual(ans["records"][0]["sheet"], "A-101")
        self.assertEqual(ans["gates"], [{"gate": "plan_answer_gate", "outcome": "grounded"}])
        self.assertEqual(out["items"][1]["reason"], "conflict")
        self.assertEqual(out["items"][3]["priority"], "normal")

    def test_low_priority_and_filters(self):
        ids = lambda **p: [i["id"] for i in self.get("", self.op(), **p).json()["items"]]  # noqa: E731
        self.assertEqual(ids(priority="low"), ["q_info"])
        self.assertEqual(ids(priority="all"), ["q_info", "d_dm", "q_conf", "d_grp", "q_old"])
        self.assertEqual(ids(kind="dispute"), ["d_dm", "d_grp"])
        self.assertEqual(ids(reason="dispute"), ["d_dm", "d_grp"])
        self.assertEqual(ids(reason="conflict"), ["q_conf"])
        self.assertEqual(ids(kind="conflicting_sources"), ["q_conf"])
        self.assertEqual(ids(company_id=B, priority="all"), ["q_info", "d_grp"])
        self.assertEqual(ids(status="approved"), [])
        self.assertEqual(self.get("", self.op(), kind="nope").status_code, 422)
        self.assertEqual(self.get("", self.op(), priority="urgent").status_code, 422)

    def test_paged(self):
        a = self.get("", self.op(), limit=2).json()
        b = self.get("", self.op(), limit=2, offset=2).json()
        self.assertEqual([i["id"] for i in a["items"]], ["d_dm", "q_conf"])
        self.assertTrue(a["has_more"])
        self.assertEqual([i["id"] for i in b["items"]], ["d_grp", "q_old"])
        self.assertFalse(b["has_more"])

    def test_each_answer_is_read_with_its_items_company(self):
        """A dispute of company B naming company A's answer id is shown with no
        answer: the answer_log read is that item's company's only."""
        self.db.answer_disputes.rows.append(
            {"_id": "d_cross", "answer_log_id": "al_a", "company_id": B, "user_id": "u9",
             "surface": "app", "text": "wrong", "status": "pending",
             "created_at": T0 + timedelta(minutes=30)})
        items = {i["id"]: i for i in self.get("", self.op()).json()["items"]}
        self.assertIsNone(items["d_cross"]["answer"])
        self.assertEqual(items["d_grp"]["answer"]["question"], "slab thickness?")
        self.assertEqual(items["d_grp"]["company"]["name"], "OTHER CO")

    def test_one_item_has_full_evidence(self):
        r = self.get("/queue/q_conf", self.op())
        self.assertEqual(r.status_code, 200)
        it = r.json()["item"]
        self.assertEqual(it["evidence"], {"reasons": ["plan_gate:ungrounded"]})
        self.assertEqual(it["answer"]["records_total"], 1)
        self.assertIn("tools", it["answer"])
        self.assertEqual(self.get("/queue/nope", self.op()).status_code, 404)
        self.assertEqual(self.get("/other/q_conf", self.op()).status_code, 404)


class TheDecision(_Base):
    def setUp(self):
        super().setUp()
        self.sent = []

        async def dm(user_id, message, **k):
            self.sent.append((str(user_id), message, k.get("kind")))
            return {"ok": 1}
        p = patch.object(server, "send_whatsapp_dm", dm)
        p.start()
        self.patches.append(p)

    def test_an_explanation_is_required(self):
        for body in ({"decision": "approve"}, {"decision": "approve", "explanation": "   "},
                     {"decision": "deny", "explanation": "too short"},
                     {"decision": "maybe", "explanation": "a long enough reason"}, {}):
            with self.subTest(body=body):
                r = self.decide("dispute", "d_dm", self.op(), **body)
                self.assertEqual(r.status_code, 422)
        self.assertEqual(self.db.answer_disputes.rows[0]["status"], "pending")
        self.assertEqual(self.db.audit_logs.rows, [])

    def test_decide_writes_status_and_one_audit_row_and_never_touches_answer_log(self):
        before = copy.deepcopy(self.db.answer_log.rows)
        r = self.decide("dispute", "d_dm", self.op(), decision="approve",
                        explanation="Sheet A-101 says 3'-6\"; the answer read the wrong door.",
                        notify=True)
        self.assertEqual(r.status_code, 200, r.text)
        row = next(d for d in self.db.answer_disputes.rows if d["_id"] == "d_dm")
        self.assertEqual(row["status"], "approved")
        self.assertEqual((row["decision"]["decision"], row["decision"]["notify"],
                          row["decision"]["operator_id"]), ("approve", True, str(OP)))
        self.assertEqual(r.json()["item"]["decision"]["decision"], "approve")
        audits = [a for a in self.db.audit_logs.rows if a["action"] == "review_decision"]
        self.assertEqual(len(audits), 1)
        a = audits[0]
        self.assertEqual((a["user_id"], a["resource_type"], a["resource_id"]),
                         (str(OP), "answer_dispute", "d_dm"))
        self.assertEqual({k: a["details"][k] for k in ("kind", "decision", "notify", "notified")},
                         {"kind": "dispute", "decision": "approve", "notify": True,
                          "notified": True})
        self.assertTrue(a["details"]["explanation"].startswith("Sheet A-101"))
        self.assertIsInstance(a["timestamp"], datetime)
        self.assertEqual(self.db.answer_log.rows, before)
        # Decided once: a second decision is refused and writes nothing.
        r2 = self.decide("dispute", "d_dm", self.op(), decision="deny",
                         explanation="changing my mind on this one")
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(len(self.db.audit_logs.rows), 1)
        self.assertEqual(len(self.sent), 1)

    def test_notify_sends_exactly_one_plain_line_to_the_dm_asker(self):
        self.decide("dispute", "d_dm", self.op(), decision="deny",
                    explanation="Checked A-101: the answer stands.", notify=True)
        self.assertEqual(self.sent, [(str(ASKER), "Thanks — we checked; the answer stands.",
                                      "review_decision")])

    def test_approve_line(self):
        self.decide("dispute", "d_dm", self.op(), decision="approve",
                    explanation="The sheet disagrees with it.", notify=True)
        self.assertEqual([m for _, m, _ in self.sent], ["Thanks — you were right; we're fixing it."])

    def test_no_notify_unless_asked(self):
        r = self.decide("dispute", "d_dm", self.op(), decision="deny",
                        explanation="Checked A-101: the answer stands.")
        self.assertEqual(r.json()["notify"], {"sent": False, "reason": "not_requested"})
        self.assertEqual(self.sent, [])

    def test_a_group_dispute_is_never_notified(self):
        r = self.decide("dispute", "d_grp", self.op(), decision="approve",
                        explanation="S-201 shows 10 inches.", notify=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["notify"], {"sent": False, "reason": "no_asker"})
        self.assertEqual(self.sent, [])
        self.assertEqual(self.db.audit_logs.rows[0]["details"]["notify_reason"], "no_asker")

    def test_a_queue_item_decides_and_notifies_nobody(self):
        before = copy.deepcopy(self.db.answer_log.rows)
        r = self.decide("queue", "q_conf", self.op(), decision="deny",
                        explanation="Both readings agree on A-101.", notify=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(next(q for q in self.db.review_queue.rows
                              if q["_id"] == "q_conf")["status"], "denied")
        self.assertEqual(r.json()["notify"]["reason"], "not_a_dispute")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.db.audit_logs.rows[0]["resource_type"], "review_queue")
        self.assertEqual(self.db.answer_log.rows, before)
        # It leaves the Needs decision view.
        ids = [i["id"] for i in self.get("", self.op()).json()["items"]]
        self.assertNotIn("q_conf", ids)
        self.assertEqual([i["id"] for i in self.get("", self.op(), status="denied").json()["items"]],
                         ["q_conf"])

    def test_the_disputer_still_only_sees_flagged_for_review(self):
        self.decide("dispute", "d_dm", self.op(), decision="approve",
                    explanation="The sheet disagrees with it.")
        from lib import answer_disputes
        self.assertEqual(answer_disputes.user_view(), {"status": "Flagged for review"})


class Pure(unittest.TestCase):
    def test_check_decision(self):
        self.assertIsNone(rq.check_decision("approve", "ten chars!"))
        self.assertIsNotNone(rq.check_decision("approve", "  short  "))
        self.assertIsNotNone(rq.check_decision("ok", "long enough reason"))

    def test_sources_for(self):
        self.assertEqual(rq.sources_for(None), ["dispute", "queue"])
        self.assertEqual(rq.sources_for("dispute"), ["dispute"])
        self.assertEqual(rq.sources_for(None, "conflict"), ["queue"])
        self.assertEqual(rq.sources_for(None, None, "low"), ["queue"])
        self.assertEqual(rq.sources_for("dispute", None, "low"), [])

    def test_the_view_carries_no_phone(self):
        v = rq.item_view("queue", {"_id": "x", "kind": "registration_refusal",
                                   "summary": "chat 0000000100 refused"})
        self.assertEqual(v["summary"], "chat […0100] refused")
        self.assertIsNone(re.search(r"\d{7,}", json.dumps(v, ensure_ascii=False)))


if __name__ == "__main__":
    unittest.main()
