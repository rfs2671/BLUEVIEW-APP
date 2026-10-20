"""Tue Oct 20, 12:28-2:08 PM, live (old pipeline), and what the brain does now.

1. Walk: "All of the above is for 3rd floor moving up to 4th now" set #2-#4
   only (the photos since the last TEXT) and was added as a note. Now: the
   walk brain (the DM brain's model, with the walk's state and the chat's
   last turns) reads it: every untagged photo since the last LOCATION ->
   3rd floor, no note; the next photos default to 4th floor, said back.
2. "How many days hvac worked in 588" -> "check with the site manager".
   Now: sub_attendance takes a trade -> the job's HVAC sub(s) -> their days.
3. The brain never says "check with X" / "not sure" before the tools: it is
   asked again with what it tried; a can't-answer is logged with the tools.

The model is scripted (FakeClaude); the real one is in scripts/dm_brain_eval.py
(FIXED_CASES).
"""

from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import server  # noqa: E402
from lib import attendance, dm_brain, punch, punch_brain, wa_assistant  # noqa: E402
from tests import _punch_detailed  # noqa: E402
from tests.test_dm_brain import FakeClaude, _Brain, last_tool_results, resp, text, use  # noqa: E402
from tests.test_punch_walkthrough_1821 import CHAT as WALK_CHAT, P588, _Walk  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402

setUpModule, tearDownModule = _punch_detailed.module_hooks()

SAID = "All of the above is for 3rd floor moving up to 4th now"


def answer(obj, i="w1"):
    """The walk brain's one tool call: its JSON answer."""
    return resp(use("answer", obj, i))


class TheWalk(_Walk):
    projects = (P588,)

    def setUp(self):
        super().setUp()
        self.claude = FakeClaude()

    def _deliver(self, parsed, text_):
        async def go():
            if not await server._punch_dm_turn(self.ident, WALK_CHAT, parsed, text_, brain=True):
                await server._dm_assistant_reply(self.ident, WALK_CHAT, text_, parsed["message_id"])
        with patch.object(server, "ANTHROPIC_API_KEY", "k"), \
                patch.object(server, "_dm_brain_client", lambda: self.claude), \
                patch.object(server, "OPENAI_API_KEY", None):
            asyncio.run(go())

    def test_all_of_the_above_then_moving_up(self):
        self._turn("starting walkthrough at 588")
        self._turn("", photo=True)
        # A text after #1: words about it (the brain says so; the batch reader applies them).
        self.claude.script += [answer({"actions": [{"do": "describe", "text": "Cracked tile"}], "reply": ""}),
                               answer({"kind": "annotation", "description": "Cracked tile"}, "b1")]
        self._turn("cracked tile")
        for _ in range(3):
            self._turn("", photo=True)

        def plan(kw):
            state = json.loads(kw["messages"][-1]["content"].split("STATE:\n", 1)[1].split("\n\nMESSAGE:")[0])
            self.assertEqual(state["stage"], "capturing")
            self.assertEqual(state["since_last_location"], [1, 2, 3, 4])   # not #2-#4
            self.assertEqual(kw["tool_choice"], {"type": "tool", "name": "answer"})
            return answer({"actions": [{"do": "location", "items": "since_last", "place": "3rd floor"},
                                       {"do": "default_location", "place": "4th floor"}],
                           "reply": "Got it."})
        self.claude.script.append(plan)
        out = self._turn(SAID)
        self.assertEqual(len(self.claude.calls), 3)
        self.assertEqual(out, ["Set 3rd floor for #1–#4 (4 photos).\nNext photos: 4th floor."])
        self.assertEqual([self.item(n)["floor"] for n in (1, 2, 3, 4)], ["3"] * 4)
        self.assertFalse(any(self.item(n).get("notes") for n in (1, 2, 3, 4)))   # never a note
        self.assertEqual(self.item(1)["text"], "Cracked tile")
        # The next photo: 4th floor, with no word about it.
        self._turn("", photo=True)
        self.assertEqual(self.item(5)["floor"], "4")
        self.assertEqual(self.item(5)["loc_src"], "default")
        # A later "these are roof" is free to set it again.
        self.claude.script.append(answer({"actions": [{"do": "location", "items": "since_last",
                                                       "place": "roof"}], "reply": ""}))
        out = self._turn("that one is the roof actually")
        self.assertEqual(self.item(5)["area"], "roof")

    def test_exact_commands_stay_in_code(self):
        self._turn("starting walkthrough at 588")
        self._turn("tile cracked", photo=True)
        for said in ("#1 lobby", "#1-1 roof"):
            self._turn(said)
        self.assertEqual(self.claude.calls, [])
        out = self._turn("done")
        self.assertEqual(self.claude.calls, [])
        self.assertTrue(out)

    def test_the_chats_last_turns_go_with_it(self):
        now = datetime.now(timezone.utc)
        self.db.whatsapp_messages.rows.extend([
            {"_id": "m1", "group_id": WALK_CHAT, "is_dm": True, "body": "we're on the 3rd floor now",
             "sender": "17185550100", "created_at": now - timedelta(minutes=3)},
            {"_id": "m2", "group_id": WALK_CHAT, "is_dm": True, "body": "👍", "sender": "bot",
             "created_at": now - timedelta(minutes=2)}])
        self._turn("starting walkthrough at 588")
        self._turn("", photo=True)
        self.claude.script.append(answer({"actions": [], "reply": "Which floor?"}))
        self._turn("same as before")
        msgs = self.claude.calls[0]["messages"]
        self.assertIn("we're on the 3rd floor now", json.dumps(msgs))
        self.assertTrue(msgs[-1]["content"].startswith("we're on the 3rd floor now")
                        or "STATE:" in msgs[-1]["content"])


class TheWalkLib(unittest.TestCase):
    def test_default_location(self):
        it = punch.new_item(5, "", photo_key="k", message_id="m")
        self.assertTrue(punch.apply_default_location(it, {"floor": "4", "area": None}))
        self.assertEqual((it["floor"], it["loc_src"]), ("4", "default"))
        own = punch.new_item(6, "Apt 4C outlet missing", photo_key="k", message_id="m")
        punch.apply_default_location(own, {"floor": "4", "area": None})
        self.assertEqual(own.get("loc_src"), None)                    # its own place kept
        roof = punch.new_item(7, "roof drain clogged", photo_key="k", message_id="m")
        if punch.location_ok(roof):
            self.assertFalse(punch.apply_default_location(roof, {"floor": "4", "area": None}))

    def test_clean_plan(self):
        state = {"stage": "capturing", "numbers": [1, 2]}
        got = punch_brain.clean_plan({"actions": [
            {"do": "default_location", "place": "4th floor"}, {"do": "describe", "text": "cracked"},
            {"do": "default_location", "place": None}, {"do": "default_location", "place": "??"}],
            "reply": ""}, state, SAID)
        self.assertEqual([a["do"] for a in got["actions"]],
                         ["default_location", "describe", "default_location"])
        self.assertIsNone(got["actions"][2]["place"])
        draft = punch_brain.clean_plan({"actions": [{"do": "describe", "text": "x"}]},
                                       {"stage": "draft", "numbers": [1]}, "x")
        self.assertEqual(draft["actions"], [])                       # words for photos: capture only


def _days(db, company, days):
    now = datetime.now(timezone.utc)
    for d in days:
        for w in range(2):
            db.checkins.rows.append({
                "_id": f"h{company[:3]}{d}{w}", "project_id": THOMAS, "company_id": CO_A,
                "worker_id": f"{company[:3]}{w}", "worker_name": f"Tech {w}", "worker_company": company,
                "check_in_time": now - timedelta(days=d, hours=1), "status": "checked_out"})


class TheHvacDays(_Brain):
    def setUp(self):
        super().setUp()
        for p in self.db.projects.rows:
            if p["_id"] == THOMAS:
                p["trade_assignments"].append({"id": "r9", "company": "Cool Air Corp", "trade": "HVAC"})
        _days(self.db, "Cool Air Corp", (3, 4, 6))

    def test_hvac_to_the_sub_to_its_days(self):
        def answer_(kw):
            (res,) = last_tool_results(kw)
            self.assertIn("HVAC / Mechanical at 588", res)
            self.assertIn("Cool Air Corp (subs list)", res)
            self.assertIn("Cool Air Corp: 3 days", res)
            self.assertIn("6 man-days", res)
            return resp(text("HVAC on 588 is Cool Air Corp: 3 days on site, 6 man-days."))
        claude = FakeClaude(resp(use("sub_attendance", {"job": "588", "trade": "hvac"})), answer_)
        with _Ctx(db=self.db) as c:
            out = self.say(c, "How many days hvac worked in 588", claude)
        self.assertEqual(out, ["HVAC on 588 is Cool Air Corp: 3 days on site, 6 man-days."])
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual((log["fallback"], log["tools_tried"][0][:14]), (False, "sub_attendance"))

    def test_by_name_when_not_on_the_list(self):
        _days(self.db, "Arctic Mechanical Inc", (1, 2))
        rows = self.db.checkins.rows
        out = attendance.trade_text(rows, datetime.now(timezone.utc), "HVAC / Mechanical",
                                    ["Cool Air Corp"], ["Arctic Mechanical Inc"], "588")
        self.assertIn("Arctic Mechanical Inc (by name)", out)
        self.assertIn("Together: 5 distinct days", out)

    def test_no_sub_for_the_trade_says_so(self):
        out = attendance.trade_text([], datetime.now(timezone.utc), "Elevator", [], [], "588")
        self.assertTrue(out.startswith("No sub is listed for Elevator at 588"), out)
        self.assertNotIn("check with", out.lower())


class TheNoDeflectRule(_Brain):
    def test_check_with_the_site_manager_is_asked_again(self):
        def again(kw):
            note = kw["messages"][-1]["content"]
            self.assertIn("never send them elsewhere", note)
            self.assertIn("Tools called so far: none", note)
            return resp(use("sub_attendance", {"job": "588", "trade": "plumber"}))
        claude = FakeClaude(resp(text("Check with the site manager on that.")), again,
                            lambda kw: resp(text("Quality Plumbing: no check-ins at 588 in that time.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "how many days did the plumber work", claude)
        self.assertEqual(out, ["Quality Plumbing: no check-ins at 588 in that time."])
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual(log["deflect_retries"], 1)

    def test_a_cant_answer_after_the_tools_is_logged_with_them(self):
        claude = FakeClaude(resp(use("find_sub", {"trade_or_name": "elevator"})),
                            resp(text("I don't have an elevator sub on your list.")),
                            resp(text("I checked the subs list: no elevator sub on it.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "how many days did the elevator guys work", claude)
        self.assertEqual(out, ["I checked the subs list: no elevator sub on it."])
        claude2 = FakeClaude(resp(use("find_sub", {"trade_or_name": "elevator"})),
                             resp(text("I don't have an elevator sub.")),
                             resp(text("I don't have an elevator sub on the subs list.")))
        with _Ctx(db=self.db) as c:
            self.say(c, "and the elevator?", claude2)
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual((log["fallback"], log["reason"]), (True, "cant_answer"))
        self.assertTrue(log["tools_tried"][0].startswith("find_sub("), log["tools_tried"])

    def test_lib(self):
        for t in ("Check with the site manager.", "You'd have to ask the super.",
                  "I'm not sure.", "I don't have that in the records."):
            self.assertTrue(dm_brain.cant_answer(t), t)
        for t in ("Cool Air Corp: 3 days.", "Not sure which job you mean — 588 or Walworth?"):
            self.assertFalse(dm_brain.cant_answer(t), t)
        self.assertEqual(wa_assistant.answer_outcome("brain", "Check with the office."),
                         (True, "cant_answer"))
        self.assertIn("never", dm_brain.SYSTEM_PROMPT.split("They ARE the site manager")[1][:80])


if __name__ == "__main__":
    unittest.main()
