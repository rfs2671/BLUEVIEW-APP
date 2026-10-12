"""P0, 588 Sun Oct 11 8:31 PM: "Who gets what?" suggested "Yeyzmar B Bate
(Power Direct)" -- a worker who had only checked in on the job. A live send
would have @mentioned a stranger in the group; shadow mode saved it.

1. Check-ins are never a source for a punch assignee: a user of the company,
   a named person in People, or "?".
2. A punch post or a chase refuses anyone the company did not name (users,
   People) -- except, for a chase, the item's own owner who said it in the
   group: the refusal is logged and a review row goes to Attention instead.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import punch, wa_sender_map  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO = "co_588"
GROUP = "120363000000000588@g.us"
NOW = datetime.now(timezone.utc)
P588 = {"_id": "p588", "name": "588 Thomas St", "company_id": CO,
        "trade_assignments": [{"id": "r_el", "trade": "Electrical", "company": "Power Direct"}]}
YEYZMAR = {"kind": "worker", "id": "w1", "name": "Yeyzmar B Bate", "company": "Power Direct",
           "jid": "17185550199@c.us"}


def _world(people=()):
    return FakeDb(
        projects=[dict(P588)],
        users=[{"_id": "u_chris", "company_id": CO, "name": "Chris Weiss", "phone": "17185550111"}],
        checkins=[{"_id": "c1", "project_id": "p588", "company_id": CO, "worker_id": "w1",
                   "worker_name": "Yeyzmar B Bate", "worker_phone": "17185550199",
                   "company": "Power Direct", "trade": "Electrical",
                   "check_in_time": NOW - timedelta(days=1)}],
        notification_preferences=[{
            "_id": "np", "user_id": None, "project_id": "p588", "scope": "project",
            "whatsapp_project": {"gc_group_id": GROUP, "gc_group_confirmed": True,
                                 "punch_sends": "live"}}],
        attention_items=[],
        **{wa_sender_map.COLLECTION: list(people)})


def _run(db, coro):
    with patch.object(server, "db", db):
        return asyncio.run(coro)


class CheckInsAreNeverAssignees(unittest.TestCase):

    SESS = {"_id": "walk1", "company_id": CO, "project_id": "p588"}

    def test_the_831_pm_suggestion_is_gone(self):
        db = _world()
        self.assertEqual(_run(db, server._punch_suggest(dict(self.SESS), ["electrical"])),
                         {"electrical": None})
        self.assertIn("electrical → ?", punch.assign_text({"electrical": None}))
        # Nor can the walker name him: he is no one the company named.
        pool = _run(db, server._punch_name_pool(dict(self.SESS)))
        self.assertNotIn("Yeyzmar B Bate", [p["name"] for p in pool])
        self.assertIsNone(punch.pick_person("Yeyzmar", pool))

    def test_a_named_person_in_people_or_a_user_is(self):
        db = _world([{"_id": "m_dov", "company_id": CO, "person_name": "Dov Klein",
                      "sub_company": "Power Direct", "sender_jid": "17185550222@c.us"}])
        pool = _run(db, server._punch_name_pool(dict(self.SESS)))
        self.assertEqual(punch.pick_person("Dov", pool)["name"], "Dov Klein")
        self.assertEqual(punch.pick_person("Chris", pool)["kind"], "user")


class TheGuard(unittest.TestCase):

    def test_who_may_be_messaged(self):
        db = _world([{"_id": "m_dov", "company_id": CO, "person_name": "Dov Klein",
                      "sender_jid": "17185550222@c.us"}])
        ok = {"kind": "user", "id": "u_chris", "name": "Chris", "jid": "17185550111@c.us"}
        dov = {"kind": "sender_map", "id": "m_dov", "name": "Dov", "jid": "17185550222@c.us"}
        self.assertIsNone(_run(db, server._recipient_refusal(CO, ok)))
        self.assertIsNone(_run(db, server._recipient_refusal(CO, dov)))
        self.assertEqual(_run(db, server._recipient_refusal(CO, YEYZMAR)), server.RECIPIENT_REFUSED)
        # Another company's user: no.
        self.assertEqual(_run(db, server._recipient_refusal("co_other", ok)), server.RECIPIENT_REFUSED)
        # A chase: the item's own owner, who said it in the group, may be.
        self.assertIsNone(_run(db, server._recipient_refusal(
            CO, YEYZMAR, group_id=GROUP, spoke="17185550199")))
        # Having written in the group about something else is not enough
        # (Codex review on #755).
        db.whatsapp_messages.rows.append({"_id": "old", "group_id": GROUP, "company_id": CO,
                                          "sender_jid": "17185550199@c.us", "body": "hi"})
        self.assertEqual(_run(db, server._recipient_refusal(
            CO, YEYZMAR, group_id=GROUP, spoke="17185550222")), server.RECIPIENT_REFUSED)

    def test_a_punch_send_refuses_and_posts_nothing(self):
        db = _world()
        posted = []

        async def post(*a, **k):
            posted.append(a)
            return True
        sess = {"_id": "walk1", "user_id": "u_roy", "company_id": CO, "project_id": "p588",
                "chat": "17185550100@c.us", "job_name": "588 Thomas St", "job_code": "588",
                "status": "due", "assign": {"electrical": dict(YEYZMAR)},
                "due": {"electrical": "Fri"},
                "items": [{"n": 1, "captured": 1, "text": "Bulb burnt", "trade": "electrical",
                           "floor": "4", "area": "Apt 4F", "photo_key": "k1", "message_id": "m1"}]}
        db[punch.SESSIONS].rows.append(dict(sess))
        with patch.object(server, "_group_post", post), \
                patch.object(server, "_punch_send_photo", post):
            reply = _run(db, server._punch_send({"user_id": "u_roy"}, sess))
        self.assertTrue(reply.startswith("Not sent: electrical → Yeyzmar B Bate"), reply)
        self.assertIn("Nothing was posted", reply)
        self.assertIn("electrical → ?", reply)                     # asked again
        self.assertEqual(posted, [])
        self.assertEqual(db[punch.COLLECTION].rows, [])             # nothing made
        self.assertEqual(db[punch.SESSIONS].rows[0]["status"], "assign")
        (rev,) = [a for a in db.attention_items.rows if a["type"] == server.RECIPIENT_REVIEW_TYPE]
        self.assertTrue(rev["summary"].startswith("Not sent (punch): Yeyzmar B Bate"))
        self.assertTrue(rev["needs_review"])
        self.assertNotIn("17185550199", str(rev))                   # never the number


class NamesAreNeverGuessed(unittest.TestCase):
    """#755: company-wide, with guards. This job's people first; a name more
    than one person answers to is a question; one off the job is marked."""

    def _walk(self, db, assign=None):
        sess = {"_id": "walk9", "user_id": "u_chris", "company_id": CO, "project_id": "p588",
                "chat": "17185550111@c.us", "job_name": "588 Thomas St", "job_code": "588",
                "status": "assign", "assign": assign or {"electrical": None},
                "items": [{"n": 1, "text": "Bulb", "trade": "electrical", "floor": "4"}]}
        db[punch.SESSIONS].rows.append(dict(sess))
        return sess

    def _say(self, db, sess, text):
        sent = []

        async def send(chat, body, *a, **k):
            sent.append(body)
        with patch.object(server, "send_whatsapp_message", send):
            _run(db, server._punch_assign_turn({"user_id": "u_chris"}, sess, sess["chat"], text))
        return sent[-1], db[punch.SESSIONS].rows[0] | sess

    LOPEZ = {"_id": "m_lopez", "company_id": CO, "person_name": "Chris Lopez",
             "sub_company": "Arkon", "sender_jid": "17185550333@c.us"}
    DOV = {"_id": "m_dov", "company_id": CO, "person_name": "Dov Klein",
           "sub_company": "Power Direct", "sender_jid": "17185550222@c.us"}

    def test_two_chrises_is_a_question_never_a_pick(self):
        db = _world([self.LOPEZ])
        sess = self._walk(db)
        reply, sess = self._say(db, sess, "electrical → Chris")
        self.assertEqual(reply.splitlines()[0],
                         "Which Chris? 1) Chris Weiss (GC team) "
                         "2) Chris Lopez (Arkon, not on this job)")
        self.assertIsNone(sess["assign"]["electrical"])
        reply, sess = self._say(db, sess, "ok")                 # not an answer
        self.assertTrue(reply.startswith("Which Chris?"))
        reply, sess = self._say(db, sess, "2")
        self.assertEqual(sess["assign"]["electrical"]["name"], "Chris Lopez")
        # The recap, marked; 'ok' to it is still what sends.
        self.assertIn("Chris Lopez (Arkon, not on this job): #1", reply)
        self.assertIn("Reply 'ok' to send", reply)
        self.assertIsNone(sess.get("choose"))
        self.assertEqual(sess["status"], "recap")

    def test_this_jobs_people_come_first(self):
        db = _world([self.LOPEZ, {**self.LOPEZ, "_id": "m_lopez2", "person_name": "Chris Diaz",
                                  "sub_company": "Bright", "sender_jid": "17185550444@c.us"}])
        db.whatsapp_messages.rows.append({"_id": "w1", "project_id": "p588", "company_id": CO,
                                          "group_id": GROUP, "sender_jid": "17185550444@c.us"})
        sess = self._walk(db)
        reply, _ = self._say(db, sess, "electrical → Chris from Arkon")
        self.assertIn("Chris Lopez (Arkon, not on this job): #1", reply)   # narrowed: one
        db[punch.SESSIONS].rows.clear()
        sess = self._walk(db)
        reply, _ = self._say(db, sess, "electrical → Chris")
        # Chris Diaz wrote in the job's group: first; then the GC team;
        # then company-wide, marked.
        self.assertEqual(reply.splitlines()[0],
                         "Which Chris? 1) Chris Diaz (Bright) 2) Chris Weiss (GC team) "
                         "3) Chris Lopez (Arkon, not on this job)")

    def test_one_match_on_the_job_is_unmarked(self):
        db = _world([self.DOV])
        db[punch.COLLECTION].rows.append({"_id": "p588:P-588-1", "project_id": "p588",
                                          "assignee": {"kind": "sender_map", "id": "m_dov"}})
        sess = self._walk(db)
        reply, sess = self._say(db, sess, "electrical → Dov")
        self.assertIn("Dov Klein (Power Direct): #1\n", reply)
        self.assertFalse(sess["assign"]["electrical"]["not_on_job"])

    def test_all_to_an_ambiguous_name_asks_then_the_whole_list(self):
        db = _world([self.LOPEZ])
        sess = self._walk(db)
        reply, sess = self._say(db, sess, "all → Chris")
        self.assertTrue(reply.startswith("Which Chris? 1) Chris Weiss (GC team) "), reply)
        self.assertIsNone(sess.get("whole"))
        reply, sess = self._say(db, sess, "1")
        self.assertEqual(sess["whole"]["name"], "Chris Weiss")
        self.assertEqual(sess["status"], "recap")
        self.assertIn("Chris Weiss (GC team): #1", reply)

    def test_filling_the_question_marks_with_an_ambiguous_name_asks(self):
        db = _world([self.LOPEZ])
        sess = self._walk(db)
        reply, sess = self._say(db, sess, "Chris")
        self.assertTrue(reply.startswith("Which Chris?"), reply)
        self.assertIsNone(sess["assign"]["electrical"])
        reply, sess = self._say(db, sess, "2")
        self.assertIn("Chris Lopez (Arkon, not on this job): #1", reply)
        self.assertTrue(sess["assign"]["electrical"]["not_on_job"])

    def test_a_worker_who_only_checked_in_is_unknown(self):
        db = _world()
        sess = self._walk(db)
        reply, sess = self._say(db, sess, "electrical → Yeyzmar")
        self.assertTrue(reply.startswith("I don't know Yeyzmar on this job. A name has to be "
                                         "in People, a user of your company, or a sub's punch "
                                         "contact"), reply)
        self.assertIsNone(sess["assign"]["electrical"])


if __name__ == "__main__":
    unittest.main()


class TheDiag(unittest.TestCase):

    def test_two_walks_the_first_with_punch_items(self):
        # Codex review on #755: the first walk's items overwrote the CLI
        # arguments, and the second walk raised.
        import argparse
        from scripts import punch_session_diag as diag
        db = _world()
        for i in (1, 2):
            db[punch.SESSIONS].rows.append({
                "_id": f"walk{i}", "user_id": "u_chris", "company_id": CO, "project_id": "p588",
                "chat": "17185550111@c.us", "status": "sent", "items": [],
                "created_at": NOW + timedelta(minutes=i), "updated_at": NOW})
        db[punch.COLLECTION].rows.append({"_id": "p588:P-588-1", "walk_id": "walk1", "pid": "P-588-1",
                                          "assignee": {"name": "Dov", "kind": "sender_map"},
                                          "send_mode": "shadow"})
        out = []
        with patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))):
            _run(db, diag.main_async(argparse.Namespace(since=NOW.isoformat(), walker="")))
        text = "\n".join(out)
        self.assertIn("punch item P-588-1 → Dov [sender_map] send_mode shadow", text)
        self.assertIn("job's Punch sends: live", text)
        self.assertEqual(text.count("punch items made: none"), 1)       # the second walk
