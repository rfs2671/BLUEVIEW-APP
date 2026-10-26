"""The walk reads like a person, not a form (Tue Oct 13, 1:43 PM, 588).

Live, a 46-item walk: "Ignore all trades and location. The floor and
description enough for this list" got the "Reply to fix (...)" hint again;
"Send" got "43 still need a trade (5, 2, 3, 8, 19 ...)"; "Send to me" got "I
don't know me on this job."; "Stucco work" was "roofing?", "Elevator beam
pockets" roofing.

The rules now:
1. Every free-text message during a walk goes to the model WITH the walk's
   state; the model answers with actions; the code checks and applies them.
   Fixed commands stay a fast path (no model).
2. "me / myself / to me" is the walker.
3. Simple mode (company "Punch list detail", default Simple; a walk switches
   in plain words): no trade or location asked or shown -- floor + words.
4. Nothing optional stops a send; at most one soft line, never the numbers.
5. A trade only when sure; never "?" rows or "? → ?".
6. Short, warm replies; no command syntax until the walker seems stuck.
7. The 12:02-1:43 PM walk, replayed: every message gets a sensible answer.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import punch, punch_brain  # noqa: E402
from tests.test_punch_walkthrough_2031 import CO, CHAT, P588, _Walk, _world  # noqa: E402


def _no_model():
    """The model is down (no key): the walk still answers."""
    async def none(state, said):
        return None
    return patch.object(server, "_punch_brain_model", none)


class _Brain(_Walk):
    """A walk in the company's default (Simple) unless a test says so; the
    model is a fake that records what it was shown."""

    detail = None

    def setUp(self):
        super().setUp()
        if self.detail:
            self.db[server.WA_COMPANY_SETTINGS].rows.append(
                {"_id": CO, "whatsapp_company": {"punch_detail": self.detail}})
        self.shown = []
        self.plans = {}

    def _patches(self):
        async def model(state, said):
            self.shown.append((state, said))
            plan = self.plans.get(said)
            return plan(state) if callable(plan) else plan
        return super()._patches() + [patch.object(server, "_punch_brain_model", model)]

    def photos(self, *captions):
        for c in captions:
            self.turn(c, photo=True)

    def start(self, *captions):
        self.turn("starting walkthrough at 588")
        self.photos(*captions)


# ── 2. "me" ──────────────────────────────────────────────────────────────────

class MeIsTheWalker(_Brain):

    def test_send_to_me(self):
        self.start("Stucco work 2nd floor", "Elevator beam pockets roof")
        (recap,) = self.turn("Send to me")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Roy Fishman (GC team)"), recap)
        self.assertNotIn("don't know", recap)
        self.assertEqual(self.sess()["whole"]["id"], "u_roy")

    def test_me_myself_at_who_gets_it(self):
        for said in ("me", "myself", "to me", "Me."):
            with self.subTest(said):
                self.setUp()
                self.start("Stucco work 2nd floor")
                self.turn("done")
                (q,) = self.turn("send")
                self.assertEqual(q, punch.WHO_GETS_IT)
                (recap,) = self.turn(said)
                self.assertTrue(recap.startswith("Ready to DM the whole list to Roy Fishman"), recap)

    def test_the_recap_sends_to_the_walkers_own_dm(self):
        self.start("Stucco work 2nd floor")
        self.turn("Send to me")
        (out,) = self.turn("ok")
        self.assertIn("Would DM Roy Fishman (GC team)", out)
        self.assertIn("*Floor 2*", out)
        self.assertIn("Stucco work", out)

    def test_the_name_is_the_walkers_user_record(self):
        # Whatever the walker's user record says -- never a name from the
        # chat or the session ("Roy Fishman" is only this file's fixture).
        u = next(r for r in self.db["users"].rows if r["_id"] == "u_roy")
        u["name"] = "Meilich Friedman"
        self.ident["user"] = {"_id": "u_roy", "name": "someone else"}
        self.start("Stucco work 2nd floor")
        (recap,) = self.turn("Send to me")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Meilich Friedman (GC team)"), recap)
        self.assertNotIn("Roy", recap)
        self.assertEqual(self.sess()["whole"]["name"], u["name"])
        (out,) = self.turn("ok")
        self.assertIn("Would DM Meilich Friedman (GC team)", out)
        self.assertEqual({r["assignee"]["name"] for r in self.db["punch_items"].rows}, {u["name"]})

    def test_is_me(self):
        for yes in ("me", "Me", "to me", "myself", "my self", "mine", "me!"):
            self.assertTrue(punch.is_me(yes), yes)
        for no in ("Mike", "meet", "me and Chris", "send me the list"):
            self.assertFalse(punch.is_me(no), no)


# ── 3. Simple mode ───────────────────────────────────────────────────────────

class SimpleMode(_Brain):

    def test_the_company_default_is_simple(self):
        self.start("Stucco work 2nd floor", "outlet cover missing 3rd floor", "rear yard fence loose")
        self.assertEqual(self.sess()["detail"], "simple")
        (draft,) = self.turn("done")                        # never a location question
        self.assertIn("(draft)", draft)
        self.assertIn("*Floor 2*\n1. 📷 Stucco work", draft)
        self.assertIn("2. 📷 Outlet cover missing", draft)
        self.assertNotIn("electrical", draft)               # no trades shown
        self.assertNotIn("no trade", draft)
        self.assertNotIn("→", draft)
        self.assertTrue(draft.endswith(punch.DRAFT_FOOT))

    def test_send_never_asks_trades_and_the_message_is_floor_and_words(self):
        self.start("Stucco work 2nd floor apt 2B", "Elevator beam pockets roof")
        self.turn("done")
        (q,) = self.turn("Send")
        self.assertEqual(q, punch.WHO_GETS_IT)
        self.turn("Chris")
        (out,) = self.turn("ok")
        self.assertIn("Would DM Chris Weiss (GC team)", out)
        body = out.split("Would DM Chris Weiss (GC team):")[1]
        self.assertIn("*Floor 2*", body)
        self.assertRegex(body, r"• P-588-\d+ Stucco work\n")       # no unit, no trade
        self.assertNotIn("Apt 2B", body)
        self.assertNotIn("_concrete_", body)
        self.assertNotIn("_masonry_", body)

    def test_the_group_gets_the_simple_list(self):
        self.start("Stucco work 2nd floor")
        self.turn("done")
        self.turn("send")
        (recap,) = self.turn("to the group")
        self.assertTrue(recap.startswith("Ready to post the whole list in"), recap)
        (out,) = self.turn("ok")
        self.assertIn("*Floor 2*", out)
        self.assertNotIn("_?_", out)

    def test_a_walk_switches_in_plain_words_with_the_model(self):
        self.detail = "detailed"
        self.setUp()
        self.start("Stucco work 2nd floor", "door closer broken")
        self.plans["Ignore all trades and location. The floor and description enough for this list"] = {
            "actions": [{"do": "simple"}], "reply": "Sure thing."}
        self.turn("done")                                   # detailed: the one location question
        self.assertEqual(self.sess()["status"], "locating")
        (out, draft) = self.turn("Ignore all trades and location. The floor and description "
                                 "enough for this list")
        self.assertEqual(out, punch_brain.SIMPLE_OK)
        self.assertIn("(draft)", draft)
        self.assertNotIn("doors", draft)
        self.assertEqual(self.sess()["detail"], "simple")
        # The model was shown the walk: its stage, counts and items.
        state, said = self.shown[-1]
        self.assertEqual((state["stage"], state["detail"], state["item_count"]),
                         ("locating", "detailed", 2))
        self.assertEqual(state["no_location"], 1)
        self.assertEqual([it["says"] for it in state["items"]], ["Stucco work", "door closer broken"])

    def test_and_back_to_detailed(self):
        self.start("Stucco work 2nd floor")
        self.plans["actually I want trades on this one"] = {"actions": [{"do": "detailed"}], "reply": ""}
        (out,) = self.turn("actually I want trades on this one")
        self.assertEqual(out, punch_brain.DETAILED_OK)
        self.assertEqual(self.sess()["detail"], "detailed")

    def test_without_the_model_the_plain_ask_still_works(self):
        self.detail = "detailed"
        self.setUp()
        self.start("Stucco work 2nd floor", "door closer broken")
        self.turn("done")
        with _no_model():
            out = self.turn("Ignore all trades and location. The floor and description enough "
                            "for this list")
        self.assertEqual(out[0], punch_brain.SIMPLE_OK)
        self.assertEqual(self.sess()["detail"], "simple")
        for said in ("keep it simple", "just floor and description", "ignore trades",
                     "no need for locations", "skip the trades and locations"):
            self.assertTrue(punch_brain.wants_simple(said), said)
        for said in ("tile cracked by the trades entrance", "ignore that", "simple fix"):
            self.assertFalse(punch_brain.wants_simple(said), said)


class TheCompanySetting(unittest.TestCase):

    def _call(self, fn, *a):
        db = _world()
        admin = {"_id": "u_roy", "id": "u_roy", "company_id": CO, "role": "admin"}

        async def audit(*a, **k):
            return None
        with patch.object(server, "db", db), patch.object(server, "audit_log", audit):
            return asyncio.run(fn(*a, current_user=admin)), db

    def test_simple_unless_set(self):
        got, _ = self._call(server.get_company_whatsapp_settings)
        self.assertEqual(got["punch_detail"], "simple")

    def test_set_and_checked(self):
        db = _world()
        admin = {"_id": "u_roy", "id": "u_roy", "company_id": CO, "role": "admin"}

        async def audit(*a, **k):
            return None
        with patch.object(server, "db", db), patch.object(server, "audit_log", audit):
            got = asyncio.run(server.patch_company_whatsapp_settings({"punch_detail": "detailed"},
                                                                     current_user=admin))
            self.assertEqual(got["punch_detail"], "detailed")
            self.assertEqual(asyncio.run(server._punch_company_detail(CO)), "detailed")
            for bad in ({"punch_detail": "fancy"}, {"punch_detail": True}, {"shabbos_off": "simple"}):
                with self.subTest(bad):
                    with self.assertRaises(HTTPException) as e:
                        asyncio.run(server.patch_company_whatsapp_settings(bad, current_user=admin))
                    self.assertEqual(e.exception.status_code, 422)
            self.assertEqual(asyncio.run(server._punch_company_detail(CO)), "detailed")


# ── 4. Nothing optional stops a send ─────────────────────────────────────────

class NeverBlocked(_Brain):

    detail = "detailed"

    def test_send_with_43_no_trade_goes_on_with_one_soft_line(self):
        self.turn("starting walkthrough at 588")
        self.photos("outlet cover missing 2nd floor", "faucet leaking 2nd floor",
                    *[f"defect {i} 3rd floor" for i in range(3, 46)])
        self.turn("done")
        (out,) = self.turn("Send")
        self.assertTrue(out.startswith("43 have no trade — fine to send as is."), out)
        self.assertNotRegex(out, r"\(\d+, \d+")                 # never the numbers in bulk
        self.assertNotIn("? → ?", out)
        self.assertIn("• No trade → Roy Fishman (GC team)", out)   # the walker's, unless said
        self.assertEqual(self.sess()["status"], "assign")
        # 'ok' with two trades nobody has: one short question, not the list.
        (q,) = self.turn("ok")
        self.assertEqual(q, 'Who should get the electrical and plumbing items? A name, or "me".')
        (recap,) = self.turn("me")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Roy Fishman (GC team)"), recap)
        self.assertIn(": 45 items", recap)                 # a count, never 45 numbers

    def test_missing_locations_never_stop_a_send(self):
        self.start("tile cracked", "paint scuff")
        (out,) = self.turn("send it to chris")
        self.assertTrue(out.startswith("Ready to DM the whole list to Chris Weiss"), out)


# ── 5. A trade only when sure ────────────────────────────────────────────────

class SureTradesOnly(unittest.TestCase):

    def test_the_live_ones(self):
        self.assertEqual(punch.trade_for("Stucco work")[0], "masonry")
        self.assertEqual(punch.trade_for("Elevator beam pockets")[0], "concrete")
        # "roof" is where, never who.
        for words in ("roof", "Stucco work roof", "debris on roof", "roof door"):
            with self.subTest(words):
                self.assertNotEqual(punch.trade_for(words)[0], "roofing")
        self.assertEqual(punch.trade_for("roof membrane torn")[0], "roofing")
        self.assertEqual(punch.trade_for("flashing loose")[0], "roofing")

    def test_unsure_is_blank(self):
        for words in ("Table cracked", "marks on wall", "hole in hallway", "something off here"):
            with self.subTest(words):
                self.assertEqual(punch.trade_for(words), (punch.UNKNOWN, False))

    def test_a_location_note_never_makes_a_trade(self):
        it = punch.new_item(1, "Stucco work", photo_key="k", message_id="m")
        punch.update_item(it, "roof")
        self.assertEqual(it["trade"], "masonry")
        it = punch.new_item(2, "missing access ladder", photo_key="k", message_id="m")
        punch.update_item(it, "roof")
        self.assertEqual(it["trade"], punch.UNKNOWN)

    def test_an_open_walk_is_read_again_once(self):
        items = [{"n": 1, "captured": 1, "text": "Stucco work", "trade": "roofing", "trade_guess": True},
                 {"n": 2, "captured": 2, "text": "Elevator beam pockets", "trade": "roofing",
                  "trade_guess": False, "notes": [{"text": "roof"}]},          # from a "roof" note
                 {"n": 3, "captured": 3, "text": "Table cracked", "trade": "carpentry", "trade_guess": True},
                 {"n": 4, "captured": 4, "text": "Patch hole", "trade": "paint", "trade_guess": False,
                  "trade_src": "walker"}]
        self.assertEqual(punch.reguess_trades(items), 3)
        self.assertEqual([it["trade"] for it in items], ["masonry", "concrete", punch.UNKNOWN, "paint"])

    def test_a_roofing_the_walker_gave_stays(self):
        # Codex on #784: an old walk cannot say who set a trade; roofing is
        # only re-read when a bare "roof" note (a place) is what made it.
        items = [{"n": 1, "captured": 1, "text": "loose shingles", "trade": "roofing", "trade_guess": False},
                 {"n": 2, "captured": 2, "text": "Elevator beam pockets", "trade": "roofing",
                  "trade_guess": False, "notes": [{"text": "roof"}]},
                 {"n": 3, "captured": 3, "text": "roof leak by drain", "trade": "roofing",
                  "trade_guess": False, "notes": [{"text": "roof"}]}]
        self.assertEqual(punch.reguess_trades(items), 1)
        self.assertEqual([it["trade"] for it in items], ["roofing", "concrete", "roofing"])

    def test_no_question_marks_in_the_draft(self):
        items = [punch.new_item(1, "Table cracked 2nd floor", photo_key="k", message_id="m"),
                 punch.new_item(2, "Bulb burnt 2nd floor", photo_key="k", message_id="m")]
        draft = punch.draft_text("588", items)
        self.assertNotIn("?", draft)
        self.assertIn("1. 📷 Table cracked\n", draft)
        self.assertIn("2. 📷 Bulb burnt — electrical", draft)


# ── 1. The model reads; the code checks ──────────────────────────────────────

class TheModelIsChecked(unittest.TestCase):

    STATE = {"stage": "draft", "numbers": [1, 2, 3]}

    def test_only_real_numbers_trades_and_places(self):
        got = punch_brain.clean_plan({"actions": [
            {"do": "trade", "items": [2, 9], "trade": "plumber"},
            {"do": "trade", "items": [1], "trade": "astrology"},
            {"do": "drop", "items": [7]},
            {"do": "location", "items": "missing", "place": "back of building"},
            {"do": "location", "items": [3], "place": "ok"},
            {"do": "teleport"},
        ], "reply": "Done →  #2 plumbing"}, self.STATE, "2 is plumbing, back of building for the rest")
        self.assertEqual(got["actions"], [
            {"do": "trade", "items": [2], "trade": "plumbing"},
            {"do": "location", "scope": "missing", "items": [],
             "place": {"floor": None, "area": "back of building"}}])
        self.assertNotIn("→", got["reply"])

    def test_cancel_only_when_said(self):
        plan = {"actions": [{"do": "cancel"}], "reply": ""}
        self.assertEqual(punch_brain.clean_plan(plan, self.STATE, "never mind that one")["actions"], [])
        self.assertEqual(punch_brain.clean_plan(plan, self.STATE, "cancel the whole thing")["actions"],
                         [{"do": "cancel"}])

    def test_a_send_at_the_recap_only_when_asked(self):
        plan = {"actions": [{"do": "send"}], "reply": ""}
        recap = {"stage": "recap", "numbers": [1]}
        self.assertEqual(punch_brain.clean_plan(plan, recap, "who is on it?")["actions"], [])
        self.assertEqual(punch_brain.clean_plan(plan, recap, "yeah go ahead")["actions"],
                         [{"do": "send", "to": None}])

    def test_names(self):
        plan = {"actions": [{"do": "send", "to": "myself"}, {"do": "assign", "to": "the group"},
                            {"do": "assign", "to": "17185550100"}], "reply": ""}
        got = punch_brain.clean_plan(plan, self.STATE, "send it")["actions"]
        self.assertEqual(got, [{"do": "send", "to": "me"}, {"do": "assign", "to": "group", "trade": None}])

    def test_a_trade_it_does_not_know_is_never_the_whole_list(self):
        # Codex on #784: "landscaping to Mike" must not give Mike everything.
        plan = {"actions": [{"do": "assign", "to": "Mike", "trade": "landscaping"},
                            {"do": "due", "when": "friday", "trade": "landscaping"},
                            {"do": "assign", "to": "Mike", "trade": None}], "reply": ""}
        got = punch_brain.clean_plan(plan, self.STATE, "landscaping to Mike friday")["actions"]
        self.assertEqual(got, [{"do": "assign", "to": "Mike", "trade": None}])

    def test_a_reply_is_two_lines_at_most(self):
        self.assertEqual(punch_brain.clean_reply("a\n\nb\nc\nd"), "a\nb")

    def test_not_an_object_is_nothing(self):
        self.assertIsNone(punch_brain.clean_plan(["send"], self.STATE, "send"))

    def test_the_state_never_carries_photos_or_phones(self):
        sess = {"status": "draft", "job_name": "588 Thomas St",
                "items": [{"n": 1, "captured": 1, "text": "Stucco work", "photo_key": "wa-photos/x.jpg",
                           "message_id": "3EB0", "floor": "2", "area": "?", "trade": "masonry"}],
                "whole": {"name": "Roy", "jid": "17185550100@c.us"}}
        state = punch_brain.state_for(sess, detail="simple", walker="Roy",
                                      recipients={"whole_list_to": "Roy (GC team)"})
        text = json.dumps(state)
        self.assertNotIn("wa-photos", text)
        self.assertNotIn("17185550100", text)
        self.assertEqual(state["items"], [{"n": 1, "says": "Stucco work", "floor": "2", "trade": "masonry"}])


class FreeTextGoesToTheModel(_Brain):

    def test_fixed_commands_never_do(self):
        self.start("Stucco work 2nd floor", "door closer broken 3rd floor")
        self.turn("done")
        for said in ("2 → doors", "drop 1", "send", "me", "ok"):
            self.assertTrue(self.turn(said), said)
        self.assertEqual(self.shown, [])

    def test_free_text_does_with_the_state(self):
        self.start("Stucco work 2nd floor", "door closer broken 3rd floor")
        self.turn("done")
        self.plans["the door one is for the carpenter, and forget the stucco"] = {
            "actions": [{"do": "trade", "items": [2], "trade": "carpentry"},
                        {"do": "drop", "items": [1]}], "reply": "ok!"}
        (out,) = self.turn("the door one is for the carpenter, and forget the stucco")
        self.assertEqual(out, "#2: carpentry.\nDropped #1.")
        self.assertEqual(len(out.splitlines()), 2)
        self.assertEqual(self.item(2)["trade"], "carpentry")
        self.assertEqual(self.item(1)["status"], "dropped")
        state, _ = self.shown[0]
        self.assertEqual((state["stage"], state["item_count"], state["numbers"]), ("draft", 2, [1, 2]))

    def test_a_question_is_answered_in_its_words(self):
        self.start("Stucco work 2nd floor")
        self.plans["how many do I have so far?"] = {"actions": [{"do": "answer"}],
                                                    "reply": "You have 1 so far."}
        self.assertEqual(self.turn("how many do I have so far?"), ["You have 1 so far."])

    def test_send_to_a_name_through_the_model(self):
        self.start("Stucco work 2nd floor")
        self.turn("done")
        self.plans["give the whole thing to chris please, by friday"] = {
            "actions": [{"do": "send", "to": "Chris", "due": "friday"}], "reply": ""}
        (recap,) = self.turn("give the whole thing to chris please, by friday")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Chris Weiss"), recap)
        self.assertIn("Due friday", recap)

    def test_the_model_down_falls_back_to_the_stage(self):
        self.start("Stucco work 2nd floor")
        self.turn("done")
        with _no_model():
            (out,) = self.turn("hmm what")
        self.assertEqual(out, "Sorry, I didn't catch that. " + punch.DRAFT_FOOT)
        with _no_model():
            (out,) = self.turn("hmm what")
        self.assertEqual(out, "Sorry, I didn't catch that. " + punch.DRAFT_HELP)   # stuck: examples


class NoItemIsLeftOut(_Brain):
    """Codex on #784: an item whose trade nobody has is asked about --
    never skipped by the send while the walk is called sent."""

    detail = "detailed"

    def test_an_item_added_at_the_recap_through_the_model(self):
        self.start("outlet cover missing 2nd floor", "faucet leaking 2nd floor")
        self.turn("done")
        self.turn("send")
        self.turn("electrical to chris; plumbing to sam")
        self.assertEqual(self.sess()["status"], "recap")
        self.plans["oh and the door closer is broken in 2B"] = {
            "actions": [{"do": "add", "text": "door closer broken 2B"}], "reply": ""}
        (out,) = self.turn("oh and the door closer is broken in 2B")
        self.assertTrue(out.startswith("Added #3 'Door closer broken' (Apt 2B)"), out)
        self.assertEqual(self.sess()["status"], "assign")
        self.assertIn("doors → who?", out)
        self.assertEqual(self.db["punch_items"].rows, [])

    def test_with_one_person_for_the_whole_list_it_goes_to_them(self):
        self.start("outlet cover missing 2nd floor")
        self.turn("done")
        self.turn("send")
        self.turn("electrical to chris")
        self.plans["oh and the faucet is leaking in 2B"] = {
            "actions": [{"do": "add", "text": "faucet leaking 2B"}], "reply": ""}
        (out,) = self.turn("oh and the faucet is leaking in 2B")
        self.assertIn("Ready to DM the whole list to Chris Weiss", out)
        self.assertIn("#1, #2", out)

    def test_the_send_asks_for_a_trade_nobody_has(self):
        self.start("outlet cover missing 2nd floor", "faucet leaking 2nd floor")
        self.turn("done")
        self.turn("send")
        self.turn("electrical to chris; plumbing to chris")
        s = self.sess()
        s["assign"].pop("plumbing")                     # a map missing a trade, however it came
        s["whole"] = None
        (out,) = self.turn("ok")
        self.assertEqual(out, 'Who should get the plumbing items? A name, or "me".')
        self.assertEqual(self.db["punch_items"].rows, [])
        self.assertEqual(self.sess()["status"], "assign")


# ── 6. Tone ──────────────────────────────────────────────────────────────────

class Tone(unittest.TestCase):

    def test_no_command_syntax_until_stuck(self):
        for text in (punch.DRAFT_FOOT, punch.ASSIGN_HINT, punch.RECAP_FOOT, punch.WHO_GETS_IT,
                     punch.ASSIGN_SHORT, punch.no_trade_line(12)):
            with self.subTest(text):
                self.assertNotIn("→", text)
                self.assertLessEqual(len(text.splitlines()), 2)
        self.assertEqual(punch.no_trade_line(12), "12 have no trade — fine to send as is.")

    def test_noted_is_one_short_line(self):
        it = punch.new_item(3, "tile chipped 4D", photo_key="k", message_id="m")
        self.assertEqual(punch.noted_text(it), "#3 'Tile chipped' (Floor 4 · Apt 4D) — got it.")


# ── 7. The 12:02 - 1:43 PM walk, replayed ────────────────────────────────────

#: The 588 walk as it stood at 12:02 PM: 45 photos, 39 with no location,
#: asked one at a time the old way ("Where on floor 1 is #3?"); some captions
#: with a "roof" note under the old rule (and a roofing trade from it).
CAPTIONS = (["Stucco work", "Elevator beam pockets", "Missing fire caulk"]
            + [f"Defect {i}" for i in range(4, 46)])


class The588WalkReplayed(_Brain):
    """Every message the walker sent, 12:02 PM to 1:43 PM, in order -- each
    gets a sensible, human answer: never the same prompt three times, never
    "I don't know me", never item numbers in bulk, at most 2 lines unless it
    is the list."""

    MESSAGES = [
        ("1st floor", {}),
        ("Back of building is location", {}),
        ("Ignore all that and just finish", {}),
        (".", {}),
        ("Add missing access ladder", {"reply_to_stucco": True}),
        ("Ignore all trades and location. The floor and description enough for this list", {}),
        ("Send", {}),
        ("Send to me", {}),
        ("ok", {}),
    ]

    def _live_walk(self):
        """The stored walk at 12:02 PM (before #781, #783 and this)."""
        self.turn("starting walkthrough at 588")
        self.photos(*CAPTIONS)
        s = self.sess()
        for i, it in enumerate(s["items"]):
            if i < 6:
                it.update(floor="2", area="interior")
            if i in (0, 1):
                # The old rule: a "roof" note on the photo, and roofing from it.
                it.update(trade="roofing", trade_guess=i == 0, notes=[{"text": "roof"}])
        s.pop("detail", None)                        # from before "Punch list detail"
        s.pop("group_loc_v2", None)
        s.update(status="locating", asking=7, where_asked=False)
        return s

    def _replay(self, model):
        self._live_walk()
        stucco_msg = 2                               # the stucco photo's message (turn 2)
        answers = []
        with model:
            for said, how in self.MESSAGES:
                reply_to = stucco_msg if how.get("reply_to_stucco") else None
                out = self.turn(said, reply_to=reply_to)
                answers.append((said, out))
        return answers

    def _check(self, answers):
        prompts = []
        for said, out in answers:
            with self.subTest(said):
                self.assertTrue(out, f"no answer to {said!r}")
                for o in out:
                    self.assertNotIn("I don't know me", o)
                    self.assertNotIn("still need a trade", o)
                    self.assertNotIn("Reply to fix", o)
                    self.assertNotRegex(o, r"\(\d+, \d+, \d+")           # numbers in bulk
                    self.assertNotIn("? → ?", o)
                    self.assertNotIn("roofing", o)
                    is_list = "(draft)" in o or o.startswith(("Ready to", "Punch sends", "Who gets what?"))
                    if not is_list:
                        self.assertLessEqual(len(o.splitlines()), 2, o)
                prompts.extend(out)
        for p in set(prompts):
            self.assertLessEqual(prompts.count(p), 2, f"said 3 times: {p!r}")

    def test_with_the_model(self):
        plans = {
            "1st floor": lambda st: {"actions": [{"do": "location", "items": [st["asked_where_is"]],
                                                   "place": "1st floor"}], "reply": ""},
            "Back of building is location": {"actions": [], "reply":
                                             "Which ones are at the back of the building?"},
            "Ignore all trades and location. The floor and description enough for this list": {
                "actions": [{"do": "simple"}], "reply": "Got it."},
        }
        self.plans.update(plans)
        answers = self._replay(patch.object(server, "LLM_API_KEY", "k"))
        self._check(answers)
        said = dict(answers)
        self.assertIn("(draft)", said["1st floor"][-1])                 # the asked one set; the list
        self.assertEqual(said["Back of building is location"],
                         ["Which ones are at the back of the building?"])
        self.assertEqual(said["Ignore all that and just finish"], [punch.WHO_GETS_IT])
        self.assertEqual(said["."], [punch.WHO_GETS_IT])                 # asked twice at most
        self.assertEqual(said["Send"], [punch.WHO_STUCK])                # then the easy answer
        self.assertEqual(said["Add missing access ladder"],
                         ["Added #46 'Missing access ladder' (Floor 2 · interior). " + punch.WHO_GETS_IT])
        self.assertEqual(said["Ignore all trades and location. The floor and description enough "
                              "for this list"], [punch_brain.SIMPLE_OK])
        self.assertTrue(said["Send to me"][0].startswith(
            "Ready to DM the whole list to Roy Fishman (GC team) (shadow mode: nothing will be sent): "
            "46 items"), said["Send to me"])
        sent = said["ok"][0]
        self.assertIn("Would DM Roy Fishman (GC team)", sent)
        self.assertIn("Stucco work", sent)
        self.assertIn("Missing access ladder", sent)
        self.assertNotIn("_masonry_", sent)                              # simple: floor + words
        # The trades were read again: no roofing left anywhere.
        self.assertEqual({it["trade"] for it in self.sess()["items"]} & {"roofing"}, set())
        # Every free-text message reached the model with the walk's state.
        seen = [s for _st, s in self.shown]
        for msg in ("1st floor", "Back of building is location",
                    "Ignore all trades and location. The floor and description enough for this list"):
            self.assertIn(msg, seen)
        self.assertNotIn("Send", seen)                                   # a fixed command
        self.assertNotIn("ok", seen)

    def test_with_the_model_down(self):
        answers = self._replay(_no_model())
        self._check(answers)
        said = dict(answers)
        self.assertEqual(said["Ignore all trades and location. The floor and description enough "
                              "for this list"], [punch_brain.SIMPLE_OK])
        self.assertTrue(said["Send to me"][0].startswith("Ready to DM the whole list to Roy Fishman"))
        self.assertIn("Would DM Roy Fishman (GC team)", said["ok"][0])


if __name__ == "__main__":
    unittest.main()
