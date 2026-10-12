"""588, Sun Oct 11 11:03-11:07 PM: a walk end to end (photos, locations,
trades, recap, ok, shadow send to Chris). What it showed:

NAMES / RECIPIENTS
 1. "Everything to Chris GC" -> "I don't know Chris GC". Whole-list phrases.
 2. A role / company tag on a name ("Chris GC", "the super Chris").
 3. "to the group": the whole list posted in the job's group, @mentioning
    each trade's owner where known. Recap + 'ok'; shadow applies.
 4. "Who can you send it to?" repeated the list. Now: who, then the question.
 5. An unknown name ends with the closest three ("Did you mean: …?").
 6. "all → Chris" read like "send to everyone": the hint says "whole list".
DUE
 7. "No due date. Asap on all" was ignored ("Due Fri", a fixed default).
LOCATION / TEXT
 8. The location comes out at either end, and in the middle.
 9. A room is the unit's sub-location: "3d br" -> Apt 3D · bedroom.
SENDING
10. The "done" hint names a real id; "done 1" / "done P1" / "done P-588-1".
11. Where it goes is said: "Would DM Chris Weiss (GC team)", "Would post in
    588 Thomas s boyland - tets, mentioning Dov Klein".
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from tests.test_punch_walkthrough_2031 import CO, GROUP, NOW, P588, _Walk, _world  # noqa: F401
import server
from lib import punch, wa_chase

GROUP_NAME = "588 Thomas s boyland - tets"


class _Live(_Walk):

    def setUp(self):
        super().setUp()
        self.db.whatsapp_groups.rows.append({"_id": "g588", "wa_group_id": GROUP,
                                             "group_name": GROUP_NAME, "project_id": "p588",
                                             "company_id": CO})

    def _patches(self):
        # Every message, with where it went.
        ps = super()._patches()
        self.sent_to = []

        async def send(chat, msg, *a, **k):
            self.sent_to.append(chat)
            self.said.append(msg)
            return True
        return [p for p in ps if getattr(p, "attribute", "") != "send_whatsapp_message"] + [
            patch.object(server, "send_whatsapp_message", send)]

    def _to_assign(self):
        self.turn("Bulb burnt 4F", photo=True)
        self.turn("Faucet leaking 2D", photo=True)
        self.turn("done")
        return self.turn("send")[0]

    def setting(self, **kw):
        self.db.notification_preferences.rows[0]["whatsapp_project"].update(kw)


class Names(_Live):

    def test_1_whole_list_phrases(self):
        for said in ("Everything to Chris GC", "all → Chris", "everything to Chris", "whole list to Chris",
                     "the list to Chris", "all items for Chris", "all of it to Chris", "send all to Chris"):
            with self.subTest(said):
                self.setUp()
                self._to_assign()
                (recap,) = self.turn(said)
                self.assertTrue(recap.startswith("Ready to DM the whole list to Chris Weiss (GC team)"),
                                recap)
                self.assertEqual(self.sess()["whole"]["name"], "Chris Weiss")

    def test_2_a_role_or_company_tag(self):
        for said in ("electrical → Chris GC", "electrical → Chris GC team", "electrical → the super Chris",
                     "electrical → Chris from GC", "electrical → Dov Power Direct"):
            with self.subTest(said):
                self.setUp()
                self._to_assign()
                self.turn(said)
                want = "Dov Klein" if "Dov" in said else "Chris Weiss"
                self.assertEqual(self.sess()["assign"]["electrical"]["name"], want)

    def test_2_ambiguous_still_asks(self):
        from lib import wa_sender_map
        self.db[wa_sender_map.COLLECTION].rows.append({
            "_id": "m_lopez", "company_id": CO, "person_name": "Chris Lopez",
            "sub_company": "Arkon", "sender_jid": "17185550444@c.us"})
        self._to_assign()
        (q,) = self.turn("electrical → Chris")
        self.assertTrue(q.startswith("Which Chris? 1) Chris Weiss (GC team)"), q)
        (out,) = self.turn("electrical → Chris GC")
        self.assertEqual(self.sess()["assign"]["electrical"]["name"], "Chris Weiss")

    def test_3_to_the_group(self):
        self._to_assign()
        self.turn("electrical → Dov")
        for said in ("to the group", "post in group", "GC group"):
            with self.subTest(said):
                (recap,) = self.turn(said)
                self.assertTrue(recap.startswith(
                    f"Ready to post the whole list in {GROUP_NAME} (shadow mode: nothing will be sent): "
                    "#1, #2"), recap)
                self.assertIn("Mentioning Dov Klein (Power Direct) (electrical)", recap)
                self.assertEqual(self.db[punch.COLLECTION].rows, [])       # 'ok' still required
        (sent,) = self.turn("ok")
        self.assertIn(f"Would post in {GROUP_NAME}, mentioning Dov Klein:", sent)
        self.assertIn("_electrical_ @Dov Klein", sent)
        self.assertIn("_plumbing_\n", sent)                                 # no one to mention
        rows = self.db[punch.COLLECTION].rows
        self.assertEqual({r["sent_via"] for r in rows}, {"group_list"})
        self.assertIsNone(next(r for r in rows if r["trade"] == "plumbing")["assignee"])

    def test_3_live_posts_once_in_the_group(self):
        self.setting(punch_sends="live")
        posted, dms = [], []

        async def gpost(gid, text, targets, reply_to=None):
            posted.append((gid, text, [t["handle"] for t in targets]))
            return True

        async def photo(*a, **k):
            return True
        self._to_assign()
        self.turn("electrical → Dov")
        self.turn("to the group")
        with patch.object(server, "_group_post", gpost), patch.object(server, "_punch_send_photo", photo):
            (out,) = self.turn("ok")
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0][0], GROUP)
        self.assertEqual(posted[0][2], ["@Dov Klein"])
        self.assertEqual(out, f"Posted in {GROUP_NAME}, mentioning Dov Klein: 2 items.")

    def test_4_who_can_you_send_it_to(self):
        self._to_assign()
        for said in ("Who can you send it to?", "who's available", "options", "list people"):
            with self.subTest(said):
                (out,) = self.turn(said)
                self.assertTrue(out.startswith("Who can get it:"), out)
                self.assertIn("Your team: Chris Weiss · GC team; Roy Fishman · GC team", out)
                self.assertIn("People on this job: Dov Klein · Power Direct; Sam Gold · Good Plumbing", out)
                self.assertIn(f"Or the group: \"to the group\" posts the list in {GROUP_NAME}", out)
                self.assertIn("Who gets what?", out)                       # then the question again
                self.assertNotIn("Yeyzmar", out)

    def test_5_did_you_mean(self):
        self._to_assign()
        (out,) = self.turn("electrical → Kris")
        self.assertIn("I don't know Kris on this job.", out)
        self.assertIn("Did you mean: Chris Weiss (GC team)", out)
        self.assertEqual(out.split("Did you mean: ")[1].split("?")[0].count(",") + 1, 3)

    def test_6_the_hint_says_whole_list(self):
        who = self._to_assign()
        self.assertIn("Reply 'ok', fix one (\"electrical → Mike\"), or send the whole list to one "
                      "person (\"whole list → Chris\").", who)
        self.assertNotIn('"all → Chris"', who)


class Due(_Live):

    def _recap(self):
        self._to_assign()
        return self.turn("electrical → Dov; plumbing → Sam")[0]

    def test_7_the_default_is_asap_not_fri(self):
        recap = self._recap()
        self.assertIn("\nDue ASAP\n", recap)
        self.turn("ok")
        for r in self.db[punch.COLLECTION].rows:
            self.assertEqual(r["due"]["due_text"], "ASAP")
            self.assertEqual(r["due"]["due_at"][:10],
                             (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat())

    def test_7_as_said_at_1106(self):
        self._recap()
        (recap,) = self.turn("No due date. Asap on all")
        self.assertIn("\nDue ASAP\n", recap)
        (recap,) = self.turn("no due date")
        self.assertIn("\nNo due date\n", recap)
        self.turn("ok")
        for r in self.db[punch.COLLECTION].rows:
            self.assertEqual((r["due"]["due_text"], r["due"]["due_at"]), ("", None))   # never chased

    def test_7_per_trade_and_days(self):
        self._recap()
        (recap,) = self.turn("electrical Mon, the rest asap")
        self.assertIn("Due electrical Mon, the rest ASAP", recap)
        for said, want in (("all today", "Due today"), ("tomorrow", "Due tomorrow"), ("by Wed", "Due Wed"),
                           ("Oct 20", "Due Oct 20"), ("all asap", "Due ASAP")):
            with self.subTest(said):
                (recap,) = self.turn(said)
                self.assertIn(f"\n{want}\n", recap)

    def test_7_unread_due_is_asked(self):
        self._recap()
        (out,) = self.turn("due when the inspector comes")
        self.assertEqual(out, "Due when? (asap / no date / a day)")

    def test_7_the_project_setting(self):
        self.setting(punch_due_default="fri")
        self.assertIn("\nDue Fri\n", self._recap())
        self.setUp()
        self.setting(punch_due_default="none")
        self.assertIn("\nNo due date\n", self._recap())

    def test_7_asap_is_chased_every_day_from_tomorrow(self):
        item = {"type": "request", "status": "open", "owner": {"status": "resolved", "id": "m_dov",
                                                                "kind": "sender_map", "jid": "1@c.us"},
                "evidence": {"quote": "Bulb burnt"}, "extraction": {"prompt_version": "att-v9"},
                "due": {"due_text": "ASAP", "due_at": "2026-10-13T13:00:00+00:00"}}
        with patch.object(wa_chase, "_prompt_ok", lambda it: True):
            self.assertEqual(wa_chase.skip_reason(item, date(2026, 10, 12)), "not_due_today")
            for d in (13, 14, 20):
                self.assertIsNone(wa_chase.skip_reason(item, date(2026, 10, d)))
            item["due"] = {"due_text": "", "due_at": None}                       # no due date
            self.assertEqual(wa_chase.skip_reason(item, date(2026, 10, 14)), "no_explicit_due")


class Locations(unittest.TestCase):

    def test_8_either_end_and_the_middle(self):
        for said, text, area in (("Bathroom tile 2b broken", "Bathroom tile broken", "Apt 2B"),
                                 ("4d tile chipped", "Tile chipped", "Apt 4D"),
                                 ("tile chipped 4d", "Tile chipped", "Apt 4D")):
            with self.subTest(said):
                it = punch.new_item(1, said, photo_key=None, message_id="m")
                self.assertEqual((it["text"], it["area"], it.get("room")), (text, area, None))

    def test_9_a_room_in_the_unit(self):
        for said, text, area, room in (
                ("Light fixture broke 3d br", "Light fixture broke", "Apt 3D", "bedroom"),
                ("3d bedroom outlet dead", "Outlet dead", "Apt 3D", "bedroom"),
                ("leak 2b bath", "Leak", "Apt 2B", "bathroom"),
                ("outlet loose 4c, in the kitchen", "Outlet loose", "Apt 4C", "kitchen"),
                ("door sticks apt 5a lr", "Door sticks", "Apt 5A", "living room"),
                ("door off 6b closet", "Door off", "Apt 6B", "closet"),
                ("railing loose 7a terrace", "Railing loose", "Apt 7A", "terrace"),
                ("enchufe roto 4c en el baño", "Enchufe roto", "Apt 4C", "bathroom"),
                ("lampara rota 3d dormitorio", "Lampara rota", "Apt 3D", "bedroom"),
                ("צינור רינט 3d קיך", "צינור רינט", "Apt 3D", "kitchen"),
                ("שלאפצימער 3d לאמפ צובראכן", "לאמפ צובראכן", "Apt 3D", "bedroom")):
            with self.subTest(said):
                it = punch.new_item(1, said, photo_key=None, message_id="m")
                self.assertEqual((it["text"], it["area"], it.get("room")), (text, area, room))
        it = punch.new_item(1, "Light fixture broke 3d br", photo_key=None, message_id="m")
        self.assertEqual(punch.added_text(it), "Added #1 'Light fixture broke' (Apt 3D · bedroom).")
        self.assertIn("(Apt 3D · bedroom)", punch.item_line(it))

    def test_9_a_room_then_its_unit(self):
        it = punch.new_item(1, "outlet dead in the kitchen", photo_key=None, message_id="m")
        punch.merge_location(it, punch.read_location("4C"))
        self.assertEqual((it["area"], it.get("room")), ("Apt 4C", "kitchen"))


class Sending(_Live):

    def test_10_the_done_hint_names_a_real_id(self):
        self._to_assign()
        self.turn("electrical → Dov; plumbing → Sam")
        (sent,) = self.turn("ok")
        self.assertIn('Reply "done P-588-1" (a photo helps)', sent)
        self.assertNotIn("P23", sent)

    def test_10_done_forms(self):
        for said, want in (("done 1", (None, 1)), ("done P1", (None, 1)), ("done P-588-1", ("588", 1)),
                           ("Done #2", (None, 2)), ("done", None), ("done 1 and 2", None)):
            with self.subTest(said):
                self.assertEqual(punch.parse_done_ref(said), want)

    def test_10_done_1_in_the_group_from_its_owner(self):
        self._to_assign()
        self.turn("electrical → Dov; plumbing → Sam")
        self.turn("ok")
        row = next(r for r in self.db[punch.COLLECTION].rows if r["trade"] == "electrical")
        # Marked by the live handler (no checklist open, his item).
        msg = {"body": f"done {row['seq']}", "sender": "17185550222", "message_id": "g1",
               "done_for": "punch"}
        ctx = {"project_id": "p588", "company_id": CO, "group_id": GROUP}

        async def who(m, c):
            return None
        with patch.object(server, "db", self.db), patch.object(server, "_attention_sender", who):
            self.assertTrue(asyncio.run(server._punch_done_is_theirs("p588", row["seq"], msg)))
            self.assertFalse(asyncio.run(server._punch_done_is_theirs(
                "p588", row["seq"], {"sender": "17185550333"})))       # Sam: not his
            self.assertTrue(asyncio.run(server._punch_group_message(msg, ctx)))
        self.assertEqual(next(r for r in self.db[punch.COLLECTION].rows
                              if r["_id"] == row["_id"])["status"], "ready_to_check")

    def test_10_done_by_dm_from_the_one_who_got_it(self):
        self._to_assign()
        self.turn("whole list → Chris")
        self.turn("ok")
        row = self.db[punch.COLLECTION].rows[0]
        chris = {"user_id": "u_chris", "company_id": CO, "role": "pm",
                 "user": {"_id": "u_chris"}, "projects": [P588]}
        said = []

        async def send(chat, msg, *a, **k):
            said.append(msg)
        with patch.object(server, "db", self.db), patch.object(server, "send_whatsapp_message", send):
            handled = asyncio.run(server._punch_dm_turn(chris, "17185550111@c.us",
                                                        {"message_id": "d1"}, f"done {row['pid']}"))
        self.assertTrue(handled)
        self.assertEqual(said, [f"{row['pid']} marked done — ready to check."])
        self.assertEqual(next(r for r in self.db[punch.COLLECTION].rows if r["_id"] == row["_id"])["status"],
                         "ready_to_check")

    def test_11_the_whole_list_is_a_dm_and_says_so(self):
        self._to_assign()
        self.turn("whole list → Chris")
        (sent,) = self.turn("ok")
        self.assertIn("Would DM Chris Weiss (GC team):", sent)
        self.assertIn("588 Thomas St punch list — due ASAP:", sent)
        self.assertEqual({r["sent_via"] for r in self.db[punch.COLLECTION].rows}, {"dm"})

    def test_11_live_dm_goes_to_their_number(self):
        self.setting(punch_sends="live")
        photos = []

        async def photo(chat, key, caption):
            photos.append(chat)
            return True
        self._to_assign()
        self.turn("whole list → Chris")
        with patch.object(server, "_punch_send_photo", photo):
            (list_dm, out) = self.turn("ok")
        self.assertEqual(self.sent_to[-2], "17185550111@c.us")            # Chris's own chat
        self.assertTrue(list_dm.startswith("588 Thomas St punch list — due ASAP:"), list_dm)
        self.assertEqual(photos, ["17185550111@c.us"] * 2)                 # the photos to him too
        self.assertEqual(out, "DM'd Chris Weiss (GC team): 2 items.")

    def test_11_per_trade_says_the_group(self):
        self._to_assign()
        self.turn("electrical → Dov; plumbing → Sam")
        (sent,) = self.turn("ok")
        self.assertIn(f"Would post in {GROUP_NAME}, mentioning Dov Klein:", sent)
        self.assertIn(f"Would post in {GROUP_NAME}, mentioning Sam Gold:", sent)


if __name__ == "__main__":
    unittest.main()


class CodexOn759(_Live):

    def test_a_sub_dmd_the_whole_list_can_say_done(self):
        # The whole list DM'd to Dov (People, not a user): his "done P-588-1"
        # never reaches the admin/PM assistant, so it is answered before it.
        self._to_assign()
        self.turn("whole list → Dov")
        self.turn("ok")
        row = self.db[punch.COLLECTION].rows[0]
        self.assertEqual(row["sent_via"], "dm")
        with patch.object(server, "db", self.db):
            # Someone else's number: nothing.
            self.assertIsNone(asyncio.run(server._punch_dm_done_by_number(
                "17185550333@c.us", ("588", row["seq"]), {"body": "done"})))
            out = asyncio.run(server._punch_dm_done_by_number(
                "17185550222@c.us", punch.parse_done_ref(f"done {row['pid']}"),
                {"body": f"done {row['pid']}", "message_id": "d1"}))
        self.assertEqual(out, f"{row['pid']} marked done — ready to check.")
        self.assertEqual(self.db[punch.COLLECTION].rows[0]["status"], "ready_to_check")
        import inspect
        src = inspect.getsource(server._process_whatsapp_message)
        gate = src.index("ident = await _dm_assistant_identity(dm_chat)")
        self.assertIn("_punch_dm_done_by_number", src[gate:gate + 900])     # before NOT_FOR_YOU

    def test_asap_items_are_in_the_chase_query_every_day(self):
        from tests._fake_mongo import matches
        seen = []

        class _Find:
            def __init__(self, q):
                seen.append(q)

            async def to_list(self, n=None):
                return []
        now = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)            # 11 AM New York
        with patch.object(server, "db", self.db), \
                patch.object(self.db.attention_items, "find", lambda q, *a, **k: _Find(q)):
            asyncio.run(server._chase_tick(now))
        (q,) = seen
        base = {"type": "request", "status": "open"}
        due = lambda text, at: {**base, "due": {"due_text": text, "due_at": at}}   # noqa: E731
        self.assertTrue(matches(due("Fri", "2026-10-14"), q))                # due today
        self.assertTrue(matches(due("ASAP", "2026-10-13"), q))               # ASAP, since yesterday
        self.assertTrue(matches(due("ASAP", "2026-10-14"), q))
        self.assertFalse(matches(due("ASAP", "2026-10-15"), q))              # not yet
        self.assertTrue(matches(due("Fri", "2026-10-13"), q))                # overdue: chased mornings
        self.assertFalse(matches(due("", None), q))                          # no due date: never

    def test_asap_due_at_is_a_day(self):
        self.assertEqual(punch.due_date(punch.ASAP, datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc)),
                         date(2026, 10, 13))

    def test_a_new_place_drops_the_old_room(self):
        it = punch.new_item(1, "Light fixture broke 3d br", photo_key=None, message_id="m")
        punch.merge_location(it, punch.read_location("lobby"))
        self.assertEqual((it["area"], it.get("room")), ("lobby", None))
        it = punch.new_item(1, "Light fixture broke 3d br", photo_key=None, message_id="m")
        punch.merge_location(it, punch.read_location("4C"))
        self.assertEqual((it["area"], it.get("room")), ("Apt 4C", None))
        it = punch.new_item(1, "Light fixture broke 3d br", photo_key=None, message_id="m")
        punch.merge_location(it, punch.read_location("4c kitchen"))
        self.assertEqual((it["area"], it.get("room")), ("Apt 4C", "kitchen"))
        items = [punch.new_item(1, "Light fixture broke 3d br", photo_key=None, message_id="m")]
        punch.apply_edit(items, {"op": "area", "n": 1, "area": "hallway"}, next_n=2)
        self.assertIsNone(items[0].get("room"))

    def test_the_punch_list_shows_the_room(self):
        self._to_assign()
        self.turn("whole list → Chris")
        self.db[punch.COLLECTION].rows.clear()
        self.db[punch.SESSIONS].rows.clear()
        self.turn("Light fixture broke 3d br", photo=True)
        self.turn("done")
        self.turn("send")
        self.turn("whole list → Chris")
        self.turn("ok")
        row = self.db[punch.COLLECTION].rows[0]
        self.assertEqual(server._punch_view(row)["room"], "bedroom")


class DoneNInAGroup(_Live):
    """Follow-up to #759: in a group, a bare "done 1" is the checklist's;
    "done P1" / "done P-588-1" close a punch item. With no checklist open for
    the job today, "done 1" from the item's assignee may close punch #1 --
    decided once, by the live handler, and marked on the stored message. In
    a DM, "done 1" is the punch item."""

    CTX = {"project_id": "p588", "company_id": CO, "group_id": GROUP}

    def _sent(self):
        self._to_assign()
        self.turn("electrical → Dov; plumbing → Sam")
        self.turn("ok")
        return next(r for r in self.db[punch.COLLECTION].rows if r["trade"] == "electrical")

    def _say(self, text, sender="17185550222", done_for=None):
        """The attention run on the stored message."""
        async def who(m, c):
            return None
        msg = {"body": text, "sender": sender, "message_id": "g1",
               **({"done_for": done_for} if done_for else {})}
        with patch.object(server, "db", self.db), patch.object(server, "_attention_sender", who):
            return asyncio.run(server._punch_group_message(msg, self.CTX))

    def _live(self, seq, sender="17185550222"):
        """What the live handler decides for "done N": the punch item?"""
        async def go():
            return (not await server._checklist_open_today(GROUP, "p588", CO)
                    and await server._punch_done_is_theirs("p588", seq, {"sender": sender}))
        with patch.object(server, "db", self.db):
            return asyncio.run(go())

    def _status(self, row):
        return next(r for r in self.db[punch.COLLECTION].rows if r["_id"] == row["_id"])["status"]

    def _checklist(self, when, done=False, _id="cl1"):
        self.db.whatsapp_checklists.rows.append({
            "_id": _id, "project_id": "p588", "company_id": CO, "group_id": GROUP,
            "generated_at": when, "items": [{"text": "Clean up", "completed": done}]})

    def test_an_open_checklist_today_keeps_done_1(self):
        row = self._sent()
        self._checklist(datetime.now(timezone.utc))
        self.assertFalse(self._live(row["seq"]))                            # not marked
        self.assertFalse(self._say(f"done {row['seq']}"))
        self.assertEqual(self._status(row), "open")
        self.assertTrue(self._say(f"done P{row['seq']}"))                   # "done P1": the punch item
        self.assertEqual(self._status(row), "ready_to_check")

    def test_done_p_588_1_with_a_checklist_open(self):
        row = self._sent()
        self._checklist(datetime.now(timezone.utc))
        self.assertTrue(self._say(f"done {row['pid']}"))
        self.assertEqual(self._status(row), "ready_to_check")

    def test_no_checklist_today_done_1_from_its_assignee(self):
        row = self._sent()
        self._checklist(datetime.now(timezone.utc) - timedelta(days=2))     # an old one: not today
        self.assertFalse(self._live(row["seq"], sender="17185550333"))      # Sam: not his
        self.assertTrue(self._live(row["seq"]))
        self.assertTrue(self._say(f"done {row['seq']}", done_for="punch"))
        self.assertEqual(self._status(row), "ready_to_check")

    def test_a_bare_done_never_marked_is_never_punch(self):
        # Codex review on #760: the "done N" that ticked the checklist's last
        # item ran through the attention run later, found no checklist open
        # and closed punch #N too. The run never re-decides: unmarked, it is
        # the checklist's.
        row = self._sent()
        self._checklist(datetime.now(timezone.utc), done=True)              # its last item, just ticked
        self.assertFalse(self._say(f"done {row['seq']}"))
        self.assertEqual(self._status(row), "open")

    def test_todays_checklist_all_ticked_is_not_open(self):
        row = self._sent()
        self._checklist(datetime.now(timezone.utc), done=True)
        self.assertTrue(self._live(row["seq"]))

    def test_the_latest_checklist_is_the_one_asked(self):
        # Codex review on #760: an older unfinished checklist of today kept
        # "done N" though "done N" ticks only the latest, already complete.
        row = self._sent()
        now = datetime.now(timezone.utc)
        self._checklist(now - timedelta(minutes=30), done=False, _id="cl_old")
        self._checklist(now, done=True, _id="cl_new")
        self.assertTrue(self._live(row["seq"]))

    def test_in_a_dm_done_1_is_the_punch_item(self):
        self._to_assign()
        self.turn("whole list → Chris")
        self.turn("ok")
        self._checklist(datetime.now(timezone.utc))                         # a DM never asks
        row = self.db[punch.COLLECTION].rows[0]
        chris = {"user_id": "u_chris", "company_id": CO, "role": "pm",
                 "user": {"_id": "u_chris"}, "projects": [P588]}
        said = []

        async def send(chat, msg, *a, **k):
            said.append(msg)
        with patch.object(server, "db", self.db), patch.object(server, "send_whatsapp_message", send):
            self.assertTrue(asyncio.run(server._punch_dm_turn(
                chris, "17185550111@c.us", {"message_id": "d1"}, f"done {row['seq']}")))
        self.assertEqual(said, [f"{row['pid']} marked done — ready to check."])
        self.assertEqual(self._status(row), "ready_to_check")
