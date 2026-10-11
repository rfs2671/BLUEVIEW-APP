"""Operator-only "send test mention" (server.owner_send_mention_test).

Pinned: only the platform operator (everyone else: 404, from the shared gate);
a person with a number gets "@<number> test" posted in the chosen group with
a real mention (the app's copy reads "@Name test"); a person with no number
gets a 409 and nothing is posted; every send is audit-logged; the people list
never carries a number or an id.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import wa_sender_map  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO = "co_588"
GROUP = "120363000000000588@g.us"
OPERATOR = {"_id": "op", "id": "op", "is_platform_operator": True, "role": "admin"}
ADMIN = {"_id": "a1", "id": "a1", "role": "admin", "company_id": CO}


def _db():
    return FakeDb(
        whatsapp_groups=[{"_id": "g1", "wa_group_id": GROUP, "group_name": "588 Thomas",
                          "project_id": "p588", "company_id": CO, "active": True}],
        projects=[{"_id": "p588", "company_id": CO, "name": "588 Thomas St",
                   "address": "588 Thomas St, Brooklyn"}],
        companies=[{"_id": CO, "name": "Levelog GC"}],
        users=[], checkins=[], audit_logs=[],
        whatsapp_sender_map=[{"_id": "s1", "company_id": CO, "sender_jid": "84894491394148@lid",
                              "person_name": "Patricia", "phone": "17187559520"}],
        whatsapp_messages=[
            {"_id": "m1", "group_id": GROUP, "company_id": CO, "sender": "84894491394148",
             "sender_jid": "84894491394148@lid", "sender_name": "Pat", "body": "hi"},
            {"_id": "m2", "group_id": GROUP, "company_id": CO, "sender": "99999999999999",
             "sender_jid": "99999999999999@lid", "sender_name": "Nobody", "body": "yo"}])


class _Sends:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    async def __call__(self, chat, text, reply_to=None, **k):
        self.calls.append({"chat": chat, "text": text, **k})
        return {"data": {"status": "success"}} if self.ok else None


def _run(coro, db, sends):
    async def no_lookup(lids):
        return {l: None for l in lids}
    with patch.object(server, "db", db), patch.object(server, "send_whatsapp_message", sends), \
            patch.object(server, "_waapi_lid_phones", no_lookup):
        return asyncio.run(coro)


class OperatorOnly(unittest.TestCase):

    def test_the_routes_carry_the_operator_gate(self):
        for path in ("/api/owner/whatsapp/mention-test",
                     "/api/owner/whatsapp/mention-test/{group_key}/people"):
            routes = [r for r in server.app.routes if getattr(r, "path", "") == path]
            self.assertTrue(routes, path)
            for r in routes:
                deps = [d.call for d in r.dependant.dependencies]
                self.assertIn(server.require_operator_404, deps, path)

    def test_anyone_else_gets_404(self):
        async def not_operator(**k):
            return ADMIN
        with patch.object(server, "get_current_user", not_operator):
            with self.assertRaises(HTTPException) as e:
                asyncio.run(server.require_operator_404(request=None, credentials=None))
        self.assertEqual(e.exception.status_code, 404)


class Sending(unittest.TestCase):

    def test_lists_groups_and_people_without_numbers_or_ids(self):
        db, sends = _db(), _Sends()
        groups = _run(server.owner_mention_test_groups(operator=OPERATOR), db, sends)["groups"]
        self.assertEqual(groups, [{"key": GROUP, "name": "588 Thomas", "project": "588 Thomas St",
                                   "company": "Levelog GC", "bot_on": True}])
        people = _run(server.owner_mention_test_people(GROUP, operator=OPERATOR), db, sends)["people"]
        self.assertEqual({p["name"]: p["has_number"] for p in people},
                         {"Patricia": True, "Nobody": False})
        flat = json.dumps(people)
        self.assertNotIn("9520", flat)
        self.assertNotIn("@lid", flat)

    def test_a_real_mention_is_posted_and_logged(self):
        db, sends = _db(), _Sends()
        key = wa_sender_map.sender_key(CO, "84894491394148@lid")
        out = _run(server.owner_send_mention_test(
            server.MentionTestBody(group_key=GROUP, person_key=key), operator=OPERATOR), db, sends)
        self.assertEqual(out, {"sent": True, "text": "@Patricia test", "source": "people",
                               "detail": None})
        (call,) = sends.calls
        self.assertEqual((call["chat"], call["text"], call["mentions"]),
                         (GROUP, "@17187559520 test", ["17187559520@c.us"]))
        self.assertEqual(call["display_text"], "@Patricia test")
        (log,) = [a for a in db.audit_logs.rows if a.get("action") == "whatsapp_mention_test"]
        self.assertTrue(log["details"]["sent"])

    def test_no_number_posts_nothing(self):
        db, sends = _db(), _Sends()
        key = wa_sender_map.sender_key(CO, "99999999999999@lid")
        with self.assertRaises(HTTPException) as e:
            _run(server.owner_send_mention_test(
                server.MentionTestBody(group_key=GROUP, person_key=key), operator=OPERATOR), db, sends)
        self.assertEqual(e.exception.status_code, 409)
        self.assertIn("would not notify", e.exception.detail)
        self.assertEqual(sends.calls, [])

    def test_a_failed_send_says_so(self):
        db, sends = _db(), _Sends(ok=False)
        key = wa_sender_map.sender_key(CO, "84894491394148@lid")
        out = _run(server.owner_send_mention_test(
            server.MentionTestBody(group_key=GROUP, person_key=key), operator=OPERATOR), db, sends)
        self.assertFalse(out["sent"])
        self.assertTrue(out["detail"])

    def test_unknown_group_or_person(self):
        db, sends = _db(), _Sends()
        with self.assertRaises(HTTPException) as e:
            _run(server.owner_send_mention_test(
                server.MentionTestBody(group_key="nope@g.us", person_key="x"), operator=OPERATOR),
                db, sends)
        self.assertEqual(e.exception.status_code, 404)
        with self.assertRaises(HTTPException) as e:
            _run(server.owner_send_mention_test(
                server.MentionTestBody(group_key=GROUP, person_key="x"), operator=OPERATOR), db, sends)
        self.assertEqual(e.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
