"""The walkthrough in a DM, Sun Oct 11 8:31-8:37 PM (588), and the rules it
broke.

What happened: three photos (table, tile floor, bulb) picked together; reply
captions "Table cracked", "Time wrong" (for "Tile wrong"), "Bulb burnt"; a
reply to "Time wrong": "I meant tile". "Done", two location questions (2D,
4f): the draft had TWO items, the tile photo was on none. "1 → electrical / 2
→ carpentry / add: tile cracked 4F" worked; "Done" went to the assistant
("Checklist creation… use the app"); "Send" asked "Who gets what?" with
electrical → Yeyzmar B Bate (Power Direct), a checked-in worker; "Chris from
gc." went to the assistant too, which answered in free text and kept nothing.

Why: the three photos were three webhooks in one second; each turn saved its
own copy of the item list, the last one won. The draft and "Who gets what?"
handed anything they did not parse to the assistant. Suggestions came from
whoever checked in with that trade in the last 14 days.

The rules now (numbers are the 8:31 PM list): every photo is one item (1),
and one on no item is named at review (3); "I meant X" / "should be X" /
"typo" / "*X" corrects THAT caption (2); "add:" keeps the words without the
location, capitalized (4); a trade read from a caption is a guess, shown
"electrical?" (5); nothing during a walk reaches the assistant, and at review
"done" / "ok" / "looks good" / "send it" send (6); the cancel words (7);
names are read against People, users and punch contacts, filling the "?"
trades (8); "all → Chris" sends the whole list as one message (9); "Punch
list goes to: one person" skips "Who gets what?" (10); only a sub's punch
contact or the last assignee of that trade is suggested (11); and nothing is
sent before the recap and an 'ok' (12).
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

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import punch, wa_sender_map  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO = "co_588"
CHAT = "17185550100@c.us"
GROUP = "120363000000000588@g.us"
P588 = {"_id": "p588", "name": "588 Thomas St", "address": "588 Thomas St, Brooklyn, NY",
        "company_id": CO,
        "trade_assignments": [{"id": "r_el", "trade": "Electrical", "company": "Power Direct"},
                              {"id": "r_pl", "trade": "Plumbing", "company": "Good Plumbing"}]}
THUMB = "/9j/4AAQSkZJRgABAQAAAQABAAD" + "A" * 400
NOW = datetime.now(timezone.utc)


def _world():
    return FakeDb(
        projects=[dict(P588)],
        users=[{"_id": "u_roy", "company_id": CO, "name": "Roy Fishman", "phone": "17185550100",
                "role": "admin"},
               {"_id": "u_chris", "company_id": CO, "name": "Chris Weiss", "phone": "17185550111",
                "role": "pm"}],
        notification_preferences=[{
            "_id": "np", "user_id": None, "project_id": "p588", "scope": "project",
            "whatsapp_project": {"gc_group_id": GROUP, "gc_group_confirmed": True,
                                 "punch_sends": "shadow"}}],
        # Yeyzmar checked in at 588 this week as an electrician: never a pick.
        checkins=[{"_id": "c1", "project_id": "p588", "company_id": CO, "worker_id": "w1",
                   "worker_name": "Yeyzmar B Bate", "worker_phone": "17185550199",
                   "company": "Power Direct", "trade": "Electrical",
                   "check_in_time": NOW - timedelta(days=1)}],
        attention_items=[],
        **{wa_sender_map.COLLECTION: [
            {"_id": "m_dov", "company_id": CO, "person_name": "Dov Klein",
             "sub_company": "Power Direct", "sender_jid": "17185550222@c.us"},
            {"_id": "m_sam", "company_id": CO, "person_name": "Sam Gold",
             "sub_company": "Good Plumbing", "sender_jid": "17185550333@c.us"}]})


class _Walk(unittest.TestCase):
    """Messages go through _punch_dm_turn, and to the assistant only when it
    says the message is not a walk turn -- the webhook's order."""

    def setUp(self):
        self.db = _world()
        self.said, self.reacts, self.assistant = [], [], []
        self.n = 0
        self.ident = {"user_id": "u_roy", "company_id": CO, "role": "admin",
                      "user": {"_id": "u_roy", "name": "Roy"}, "projects": [P588]}

    def _parsed(self, photo=False, reply_to=None, quoted_body=None):
        self.n += 1
        p = {"has_image": photo, "message_id": f"3EB0{self.n:04d}",
             "message_id_serialized": f"false_{CHAT}_3EB0{self.n:04d}"}
        if reply_to:
            p.update(quoted_message_id=f"3EB0{reply_to:04d}",
                     quoted_type="image" if quoted_body is None else "chat",
                     quoted_body=THUMB if quoted_body is None else quoted_body)
        return p

    def _patches(self):
        async def send(chat, msg, *a, **k):
            self.said.append(msg)
            return True

        async def react(chat, mid, emoji):
            self.reacts.append(emoji)
            return True

        async def assistant(*a, **k):
            self.assistant.append(a[2] if len(a) > 2 else k)

        async def image(parsed):
            await asyncio.sleep(0.01)              # a real download takes a moment
            return b"\xff\xd8\xff" + b"\x00" * 64

        async def targets(people, company_id, now):
            return [{"handle": "@" + (p.get("name") or ""), "resolved": bool(p.get("jid")),
                     "source": "jid"} for p in people]
        return [patch.object(server, "db", self.db),
                patch.object(server, "send_whatsapp_message", send),
                patch.object(server, "_react_to_message", react),
                patch.object(server, "_dm_assistant_reply", assistant),
                patch.object(server, "download_image", image),
                patch.object(server, "_upload_to_r2", lambda *a, **k: True),
                patch.object(server, "_mention_targets", targets)]

    async def _one(self, parsed, text):
        if not await server._punch_dm_turn(self.ident, CHAT, parsed, text):
            await server._dm_assistant_reply(self.ident, CHAT, text, parsed["message_id"])

    def _run(self, coro):
        ps = self._patches()
        for p in ps:
            p.start()
        try:
            return asyncio.run(coro)
        finally:
            for p in ps:
                p.stop()

    def turn(self, text="", photo=False, reply_to=None, quoted_body=None):
        before = len(self.said)
        self._run(self._one(self._parsed(photo, reply_to, quoted_body), text))
        return self.said[before:]

    def photos_together(self, *captions):
        """A multi-photo pick: one webhook per photo, all at once."""
        msgs = [(self._parsed(photo=True), c) for c in captions]

        async def all_at_once():
            await asyncio.gather(*(self._one(p, c) for p, c in msgs))
        self._run(all_at_once())

    def sess(self):
        (s,) = [r for r in self.db[punch.SESSIONS].rows if r["status"] != "expired"]
        return s

    def item(self, captured):
        return next(it for it in self.sess()["items"] if it["captured"] == captured)


class The2031Sequence(_Walk):

    def test_exactly_as_sent(self):
        # 8:31 PM: table, tile floor, bulb -- picked together.
        self.photos_together("", "", "")
        s = self.sess()
        self.assertEqual(len(s["items"]), 3)                      # (1) every photo, one item
        self.assertEqual(len(s["photos"]), 3)
        self.assertEqual(sorted(it["n"] for it in s["items"]), [1, 2, 3])
        # Reply-captions, one per photo.
        self.turn("Table cracked", reply_to=1)                    # message 4
        self.turn("Time wrong", reply_to=2)                       # message 5
        self.turn("Bulb burnt", reply_to=3)                       # message 6
        # "I meant tile", a reply to "Time wrong": THAT caption (2).
        out = self.turn("I meant tile", reply_to=5, quoted_body="Time wrong")
        self.assertEqual(out, [])
        self.assertEqual(self.item(2)["text"], "Tile wrong")
        self.assertEqual((self.item(2)["trade"], self.item(2)["trade_guess"]), ("tile", True))
        self.assertEqual(self.item(1)["text"], "Table cracked")   # nothing on the others
        self.assertEqual(self.item(3)["text"], "Bulb burnt")
        self.assertFalse(self.item(1).get("notes") or self.item(3).get("notes"))
        self.assertEqual((self.item(1)["trade"], self.item(3)["trade"]), ("carpentry", "electrical"))
        # "Done": every photo needs a place.
        (q,) = self.turn("Done")
        self.assertIn("3 items need a location", q)
        self.turn("2D")
        self.turn("4f")
        (draft,) = self.turn("4F")
        self.assertIn("3 items (draft)", draft)
        self.assertIn("Tile wrong (Apt 4F) — tile?", draft)       # (5) a guess, shown so
        self.assertIn("Bulb burnt (Apt 4F) — electrical?", draft)
        self.assertIn("Table cracked (Apt 2D) — carpentry?", draft)
        # The same edit message as at 8:35 PM.
        (draft,) = self.turn("1 → electrical\n2 → carpentry\nadd: tile cracked 4F")
        added = next(it for it in self.sess()["items"] if it.get("added"))
        self.assertEqual((added["text"], added["floor"], added["area"]),    # (4)
                         ("Tile cracked", "4", "Apt 4F"))
        self.assertIn("Tile cracked (Apt 4F)", draft)
        # "Done" at review is send (6): "Who gets what?", never the assistant.
        (who,) = self.turn("Done")
        self.assertTrue(who.startswith("Who gets what?"), who)
        self.assertNotIn("Yeyzmar", who)                           # (11) a checked-in worker: never
        self.assertIn("electrical → ?", who)
        # "Chris from gc." (8): Chris, the GC's user, gets every "?" trade.
        (recap,) = self.turn("Chris from gc.")
        self.assertTrue(recap.startswith("Ready to send (shadow mode"), recap)   # (12)
        self.assertIn("Chris Weiss (GC team): #1, #2, #3, #4", recap)
        self.assertEqual(self.db[punch.COLLECTION].rows, [])       # nothing before 'ok'
        (sent,) = self.turn("ok")
        self.assertIn("shadow mode: nothing was posted", sent)
        rows = self.db[punch.COLLECTION].rows
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["assignee"]["name"] for r in rows}, {"Chris Weiss"})
        self.assertEqual(self.assistant, [])                        # (6) never once


class EveryPhotoIsAnItem(_Walk):

    def test_photos_together_are_all_kept(self):
        self.photos_together("Table cracked 2D", "Tile wrong 4F", "Bulb burnt 4F", "Loose outlet 3B")
        s = self.sess()
        self.assertEqual(len(s["items"]), 4)
        self.assertEqual(len({it["message_id"] for it in s["items"]}), 4)
        self.assertEqual(len(self.db[punch.SESSIONS].rows), 1)     # one walk

    def test_a_photo_on_no_item_is_named_at_review(self):
        self.turn("Table cracked 2D", photo=True)
        self.turn("Bulb burnt 4F", photo=True)
        # A photo stored on the walk but on no item (as at 8:31 PM).
        self.db[punch.SESSIONS].rows[0]["photos"].append(
            {"message_id": "false_x_3EB0LOST", "at": datetime(2026, 10, 12, 0, 31, tzinfo=timezone.utc),
             "key": "wa-photos/p588/w/3.jpg"})
        (q,) = self.turn("done")
        self.assertIn("Photo at 8:31 PM isn't on the list. Add it? (reply: add photo 3: description)", q)
        self.turn("add photo 3: tile cracked 4F")
        it = next(i for i in self.sess()["items"] if i.get("photo_key") == "wa-photos/p588/w/3.jpg")
        self.assertEqual((it["text"], it["area"]), ("Tile cracked", "Apt 4F"))
        (draft,) = self.turn("done")
        self.assertIn("3 items (draft)", draft)

    def test_done_again_goes_on_without_it(self):
        self.turn("Bulb burnt 4F", photo=True)
        self.db[punch.SESSIONS].rows[0]["photos"].append(
            {"message_id": "false_x_LOST", "at": NOW, "key": None})
        self.turn("done")
        (draft,) = self.turn("done")
        self.assertIn("1 item (draft)", draft)


class CaptionCorrections(_Walk):

    def test_the_forms(self):
        for fix in ("I meant tile", "should be tile", "typo: tile", "*tile", "Typo, should be tile"):
            with self.subTest(fix):
                self.setUp()
                self.turn("Bulb burnt 4F", photo=True)
                self.turn("", photo=True)
                self.turn("Time wrong 4F", reply_to=2)              # message 3
                self.turn(fix, reply_to=3, quoted_body="Time wrong 4F")
                # The reply-caption's place is its own field ("Apt 4F").
                self.assertEqual((self.item(2)["text"], self.item(2)["area"]), ("Tile wrong", "Apt 4F"))
                self.assertEqual(self.item(1)["trade"], "electrical")
                self.assertFalse(self.item(1).get("notes"))

    def test_typed_right_after_the_caption(self):
        self.turn("Time wrong 4F", photo=True)
        self.turn("*tile")
        self.assertEqual(self.item(1)["text"], "Tile wrong 4F")

    def test_a_bare_typo_asks(self):
        self.turn("Time wrong 4F", photo=True)
        (q,) = self.turn("typo", reply_to=1)
        self.assertIn("What should #1 say?", q)

    def test_no_item_to_correct_asks_never_touches_another(self):
        self.turn("Bulb burnt 4F", photo=True)
        (q,) = self.turn("I meant tile", reply_to=999, quoted_body="something else")
        self.assertIn("Which photo is that for?", q)
        self.assertEqual((self.item(1)["text"], self.item(1)["trade"]), ("Bulb burnt 4F", "electrical"))
        self.assertFalse(self.item(1).get("notes"))


class NothingReachesTheAssistant(_Walk):

    def _to_draft(self):
        self.turn("Bulb burnt 4F", photo=True)
        self.turn("done")

    def test_review_words_send(self):
        for w in ("done", "Done", "ok", "looks good", "send it", "send"):
            with self.subTest(w):
                self.setUp()
                self._to_draft()
                (out,) = self.turn(w)
                self.assertTrue(out.startswith("Who gets what?"), out)
                self.assertEqual(self.assistant, [])

    def test_cancel_words(self):
        for w in ("cancel", "cancel walkthrough", "cancel punch", "cancel punch list"):
            for stage in ("capture", "draft", "assign", "recap"):
                with self.subTest(w=w, stage=stage):
                    self.setUp()
                    self.turn("Bulb burnt 4F", photo=True)
                    if stage != "capture":
                        self.turn("done")
                    if stage in ("assign", "recap"):
                        self.turn("send")
                    if stage == "recap":
                        self.turn("all → Chris")
                    (out,) = self.turn(w)
                    self.assertEqual(out, "Walkthrough cancelled. Nothing was sent.")
                    self.assertEqual(self.sess()["status"] if False else
                                     self.db[punch.SESSIONS].rows[0]["status"], "cancelled")

    def test_anything_else_stays_in_the_walk(self):
        self._to_draft()
        self.turn("what is this")                                   # draft: the draft again
        self.turn("send")
        self.turn("hmm not sure")                                   # assign: the question again
        self.turn("all to Chris")
        self.turn("what happens now?")                              # recap: the recap again
        self.assertEqual(self.assistant, [])
        self.assertEqual(self.db[punch.COLLECTION].rows, [])


class Assigning(_Walk):

    def _to_assign(self):
        self.turn("Bulb burnt 4F", photo=True)
        self.turn("Faucet leaking 2D", photo=True)
        self.turn("done")
        return self.turn("send")[0]

    def test_a_punch_contact_is_suggested(self):
        self.db.notification_preferences.rows[0]["whatsapp_project"]["punch_contacts"] = {
            "r_el": "m_dov"}
        who = self._to_assign()
        self.assertIn("electrical → Dov Klein (Power Direct)", who)
        self.assertIn("plumbing → ?", who)

    def test_the_last_assignee_of_the_trade_on_this_job(self):
        self.db[punch.COLLECTION].rows.append({
            "_id": "p588:P-588-1", "project_id": "p588", "trade": "plumbing", "pid": "P-588-1",
            "assigned_at": NOW - timedelta(days=3),
            "assignee": {"kind": "sender_map", "id": "m_sam", "name": "Sam Gold",
                         "company": "Good Plumbing", "jid": "17185550333@c.us"}})
        who = self._to_assign()
        self.assertIn("plumbing → Sam Gold (Good Plumbing)", who)
        self.assertIn("electrical → ?", who)                         # Yeyzmar checked in: no

    def test_pairs_and_unknown_names(self):
        self._to_assign()
        (out,) = self.turn("electrical → Nobody")
        self.assertIn("I don't know Nobody on this job", out)
        (out,) = self.turn("electrical → Dov; plumbing → Sam")
        self.assertTrue(out.startswith("Ready to send"), out)
        self.assertIn("Dov Klein (Power Direct): #", out)

    def test_whole_list_to_one_person(self):
        for said in ("all → Chris", "all to Chris", "send all to Chris", "whole list to Chris"):
            with self.subTest(said):
                self.setUp()
                self._to_assign()
                (recap,) = self.turn(said)
                self.assertIn("Chris Weiss (GC team): #1, #2", recap)
                (sent,) = self.turn("ok")
                # ONE message, by floor and trade, with the photos.
                self.assertEqual(sent.count("punch list — due"), 1, sent)
                self.assertIn("*Floor 2*", sent)
                self.assertIn("_plumbing_", sent)
                self.assertIn("*Floor 4*", sent)
                self.assertIn("(+2 photos)", sent)

    def test_one_person_setting_skips_who_gets_what(self):
        self.db.notification_preferences.rows[0]["whatsapp_project"].update(
            punch_to="one_person", punch_to_user="u_chris")
        out = self._to_assign()
        self.assertTrue(out.startswith("Ready to send"), out)
        self.assertIn("Chris Weiss (GC team): #1, #2", out)

    def test_due_days_change_the_recap(self):
        self._to_assign()
        self.turn("all → Chris")
        (recap,) = self.turn("electrical Mon, everything else Fri")
        self.assertIn("Due electrical Mon, the rest Fri", recap)
        self.turn("ok")
        due = {r["trade"]: r["due"]["due_text"] for r in self.db[punch.COLLECTION].rows}
        self.assertEqual(due, {"electrical": "Mon", "plumbing": "Fri"})


class TheSettings(unittest.TestCase):
    """Project → WhatsApp: "Punch list goes to", and each sub's punch contact."""

    ADMIN = {"_id": "u_roy", "id": "u_roy", "company_id": CO, "role": "admin"}

    def _call(self, fn, *a):
        db = _world()

        async def scope(company_id, project_id):
            return {"_id": "p588"}
        with patch.object(server, "db", db), patch.object(server, "_bot_project_scope", scope), \
                patch.object(server, "is_company_admin", lambda u: True), \
                patch.object(server, "get_user_company_id", lambda u: CO), \
                patch.object(server, "_gc_group_bound_to", lambda *a: asyncio.sleep(0, True)):
            out = asyncio.run(fn(*a))
            return out, db

    def test_the_view(self):
        out, _ = self._call(server.get_project_whatsapp_settings, "p588", self.ADMIN)
        self.assertEqual(out["punch_to"], "per_trade")
        self.assertEqual([o["name"] for o in out["punch_to_options"]], ["Chris Weiss", "Roy Fishman"])
        el = next(r for r in out["punch_contacts"] if r["row_id"] == "r_el")
        self.assertEqual((el["company"], el["contact_id"]), ("Power Direct", None))
        self.assertEqual([o["name"] for o in el["options"]], ["Dov Klein"])   # that sub's People
        self.assertNotIn("1718555", str(out))                                 # no phone numbers

    def test_set_and_validate(self):
        out, db = self._call(server.patch_project_whatsapp_alerts, "p588",
                             {"punch_to": "one_person", "punch_to_user": "u_chris",
                              "punch_contacts": {"r_el": "m_dov"}}, self.ADMIN)
        self.assertEqual((out["punch_to"], out["punch_to_user"]), ("one_person", "u_chris"))
        el = next(r for r in out["punch_contacts"] if r["row_id"] == "r_el")
        self.assertEqual(el["contact_name"], "Dov Klein")
        for bad in ({"punch_to": "everyone"}, {"punch_to_user": "u_nobody"},
                    {"punch_contacts": {"r_nope": "m_dov"}}, {"punch_contacts": {"r_el": "m_x"}}):
            with self.subTest(bad), self.assertRaises(HTTPException) as e:
                self._call(server.patch_project_whatsapp_alerts, "p588", bad, self.ADMIN)
            self.assertEqual(e.exception.status_code, 422)


class TheRules(unittest.TestCase):

    def test_trade_guesses(self):
        for words, trade in {"Bulb burnt": "electrical", "outlet loose": "electrical",
                             "switch plate missing": "electrical", "Tile wrong": "tile",
                             "grout missing": "tile", "Table cracked": "carpentry",
                             "cabinet door off": "carpentry", "trim gap": "carpentry",
                             "paint touch-up": "paint", "faucet leak": "plumbing",
                             "sheetrock patch": "drywall"}.items():
            with self.subTest(words):
                self.assertEqual(punch.trade_for(words), (trade, True))
        self.assertEqual(punch.trade_for("Time wrong"), (punch.UNKNOWN, False))

    def test_add_text(self):
        self.assertEqual(punch.clean_caption("tile cracked 4F"), "Tile cracked")
        self.assertEqual(punch.clean_caption("bulb out 3rd floor corridor"), "Bulb out")
        self.assertEqual(punch.clean_caption("roof drain clogged"), "Roof drain clogged")


if __name__ == "__main__":
    unittest.main()
