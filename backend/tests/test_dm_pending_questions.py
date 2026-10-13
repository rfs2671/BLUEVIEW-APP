"""Open questions in the DM (live, Mon 7:17 PM -> 8:28 PM).

A "Which job?" picker answered "Disregard" and two gibberish messages with the
same picker, 4 times. Now, for ANY open question -- a change's ("Add it?",
"Which company?"), the "Which job?" menu, "Since 8:07 or since 7am?":
  * "disregard / never mind / cancel / forget it / stop" drops it:
    "OK, dropped it.";
  * after 2 non-answers it is dropped and the message handled as a new one;
  * it expires 30 minutes after it was FIRST asked (asking again does not
    keep it alive);
  * a message that asks nothing and names no job never gets "Which job?".
Through the real DM entry point.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import dm_actions, wa_assistant  # noqa: E402
from tests.test_dm_routing_order import CHAT, _Dm, _world  # noqa: E402
from tests.test_whatsapp_dm_assistant import WALWORTH, _Ctx  # noqa: E402

DROPPED = "OK, dropped it."
HINT = wa_assistant.NOT_A_QUESTION_TEXT


class _Q(_Dm):

    def state(self, db, kind):
        return next((r for r in db[server._DM_STATE].rows if r.get("kind") == kind), None)


class TheLiveEvening(_Q, unittest.TestCase):

    def test_disregard_then_gibberish_never_the_picker_again(self):
        db = _world()
        with _Ctx(db=db) as c:
            (menu,) = self.dm(c, "what's open?")
            drop, g1, g2 = self.dm(c, "Disregard", "asdkjh qwe", "fjfjf kkk")
        self.assertTrue(menu[0].startswith("Which job?"), menu)
        self.assertEqual(drop, [DROPPED])
        self.assertEqual((g1, g2), ([HINT], [HINT]))
        self.assertIsNone(self.state(db, "dm_menu"))

    def test_the_picker_from_an_hour_ago_is_gone(self):
        db = _world()
        with _Ctx(db=db) as c:
            self.dm(c, "what's open?")
            self.state(db, "dm_menu")["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            (r,) = self.dm(c, "2")                                   # 71 minutes later
        self.assertEqual(r, [HINT])
        self.assertEqual(self.agent_calls, [])


class DropWordsClearAnyOpenQuestion(_Q, unittest.TestCase):

    WORDS = ("disregard", "Disregard.", "never mind", "nvm", "cancel", "cancel that",
             "forget it", "forget about it", "ok never mind", "olvídalo")

    def test_the_which_job_menu(self):
        for word in self.WORDS:
            with self.subTest(word):
                db = _world()
                with _Ctx(db=db) as c:
                    self.dm(c, "what's open?")
                    (r,) = self.dm(c, word)
                self.assertIn(r[0], (DROPPED, "Listo, lo dejé."))
                self.assertIsNone(self.state(db, "dm_menu"))

    def test_a_change_question(self):
        for word in self.WORDS:
            with self.subTest(word):
                db = _world()
                with _Ctx(db=db) as c:
                    ask, r = self.dm(c, "I want to add a sub", word)
                self.assertEqual(ask, ["Which company?"])
                self.assertIn(r[0], (DROPPED, "Listo, lo dejé."))
                self.assertIsNone(self.state(db, "dm_action"))

    def test_since_when(self):
        db = _world()
        with _Ctx(db=db) as c:
            server_now = datetime.now(timezone.utc)
            db[server._DM_STATE].rows.append({
                "kind": "dm_clarify", "group_id": "".join(ch for ch in CHAT if ch.isdigit()),
                "sender": "", "project_id": WALWORTH, "question": "who got added?",
                "options": [{"label": "7:00", "since": server_now.isoformat(), "keys": ["7"]}],
                "asked": "Since your 8:07 brief or since 7:00?",
                "expires_at": server_now + timedelta(minutes=30)})
            (r,) = self.dm(c, "forget it")
        self.assertEqual(r, [DROPPED])
        self.assertIsNone(self.state(db, "dm_clarify"))

    def test_with_nothing_open_disregard_is_just_ok(self):
        with _Ctx(db=_world()) as c:
            (r,) = self.dm(c, "disregard")
        self.assertEqual(r, ["OK."])

    def test_not_a_drop_word(self):
        for said in ("stop chasing on shabbos", "cancel the 588 job", "disregard the last photo please"):
            with self.subTest(said):
                self.assertFalse(dm_actions.is_drop(said))


class TwoNonAnswers(_Q, unittest.TestCase):

    def test_a_change_question_asked_once_more_then_dropped(self):
        db = _world()
        with _Ctx(db=db) as c:
            ask, again, new = self.dm(c, "put bright electric on 588 they're the electrician",
                                      "asdf", "qwer zxcv")
        self.assertTrue(ask[0].startswith("Add Bright Electric"), ask)
        self.assertEqual(again, ["Should I go ahead? Yes or no."])
        self.assertEqual(new, [HINT])                                # read as a new message
        self.assertIsNone(self.state(db, "dm_action"))

    def test_the_menu_asked_once_more_then_dropped(self):
        db = _world()
        with _Ctx(db=db) as c:
            menu, again, new = self.dm(c, "what's open?", "kk", "ok sure")
        self.assertTrue(menu[0].startswith("Which job?"))
        self.assertTrue(again[0].startswith("Which job?"))
        self.assertIn("never mind", again[0])
        self.assertEqual(new, [HINT])
        self.assertIsNone(self.state(db, "dm_menu"))

    def test_a_real_answer_after_one_miss_still_works(self):
        with _Ctx(db=_world()) as c:
            self.dm(c, "what's open?", "kk")
            self._send(c, CHAT, "2", mid="Z9")
        self.assertEqual(self.agent_calls[-1]["project_id"], WALWORTH)

    def test_a_new_request_is_never_a_non_answer(self):
        with _Ctx(db=_world()) as c:
            ask, new = self.dm(c, "I want to add a sub", "need to add someone")
        self.assertEqual((ask, new), (["Which company?"], ["What's their name?"]))


class ThirtyMinutesFromFirstAsked(_Q, unittest.TestCase):

    def test_the_lifetimes(self):
        self.assertEqual(dm_actions.PENDING_SECONDS, 30 * 60)
        self.assertEqual(wa_assistant.MENU_SECONDS, 30 * 60)

    def test_asking_again_does_not_extend_it(self):
        db = _world()
        with _Ctx(db=db) as c:
            self.dm(c, "what's open?")
            first = self.state(db, "dm_menu")["expires_at"]
            self.dm(c, "kk")
            self.assertEqual(self.state(db, "dm_menu")["expires_at"], first)
            self.dm(c, "I want to add a sub")
            first = self.state(db, "dm_action")["expires_at"]
            self.dm(c, "!!!")
            self.assertEqual(self.state(db, "dm_action")["expires_at"], first)

    def test_an_expired_change_question_is_gone(self):
        db = _world()
        with _Ctx(db=db) as c:
            self.dm(c, "I want to add a sub")
            self.state(db, "dm_action")["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            (r,) = self.dm(c, "Power Direct")
        self.assertNotEqual(r, ["Which job?"])
        self.assertNotIn("trade", r[0])                              # not read as the answer


class Stop(_Q, unittest.TestCase):

    def optin(self, db):
        return next(o for o in db[server.WA_OPTINS].rows if o["user_id"] == "u_admin")

    def test_stop_with_a_question_open_drops_it_and_keeps_the_opt_in(self):
        db = _world()
        with _Ctx(db=db) as c:
            self.dm(c, "what's open?")
            (r,) = self.dm(c, "STOP")
        self.assertEqual(r, ["OK, dropped it. (Send STOP again to stop all messages from me.)"])
        self.assertEqual(self.optin(db)["status"], "active")
        self.assertIsNone(self.state(db, "dm_menu"))

    def test_stop_with_nothing_open_is_the_opt_out(self):
        db = _world()
        with _Ctx(db=db) as c:
            self.dm(c, "STOP")
        self.assertEqual(self.optin(db)["status"], "opted_out")


    def test_codex_772_a_reminders_yes_no_is_an_open_question_too(self):
        for word in ("STOP", "disregard"):
            with self.subTest(word):
                db = _world()
                with _Ctx(db=db) as c:
                    (ask,) = self.dm(c, "remind me to order rebar tomorrow")
                    self.assertIsNotNone(self.state(db, server.UPCOMING_REMIND_STATE), ask)
                    (r,) = self.dm(c, word)
                self.assertTrue(r[0].startswith(DROPPED), r)
                self.assertEqual(self.optin(db)["status"], "active")
                self.assertIsNone(self.state(db, server.UPCOMING_REMIND_STATE))


class Codex772PoliteQuestions(_Q, unittest.TestCase):
    """A real question with no "?" and no job still gets "Which job?" --
    only a message that asks nothing gets the hint."""

    def test_which_job_not_the_hint(self):
        for said in ("Could you check whether Joe arrived", "would the inspector come today",
                     "should we expect the plumbers", "have the plumbers shown up",
                     "has anyone signed in"):
            with self.subTest(said):
                with _Ctx(db=_world()) as c:
                    (r,) = self.dm(c, said)
                self.assertNotEqual(r, [HINT])

    def test_gibberish_still_the_hint(self):
        for said in ("asdkjh qwe", "sdfsdf", "jjjj kkkk llll", "fgh dfg sdf werq asd"):
            with self.subTest(said):
                self.assertFalse(server._dm_is_new_question(said))


if __name__ == "__main__":
    unittest.main()
