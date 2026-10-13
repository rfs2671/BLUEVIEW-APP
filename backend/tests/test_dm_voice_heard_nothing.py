"""wa_voice.heard_nothing: a DM voice note with nothing usable in it (Tue
Oct 13: a 1-second note answering "what's the address?")."""

from __future__ import annotations

import inspect
import os
import unittest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import wa_voice  # noqa: E402


class HeardNothing(unittest.TestCase):

    def test_no_words(self):
        for t in ("", "   ", "…", "...", "?!", None):
            with self.subTest(t):
                self.assertTrue(wa_voice.heard_nothing(t, 3.0))

    def test_silence_words_from_a_short_note(self):
        for t in ("Thank you.", "you", "Bye.", "Thanks for watching!", "Um"):
            with self.subTest(t):
                self.assertTrue(wa_voice.heard_nothing(t, 1.0))

    def test_said_something(self):
        for t, d in (("9 Menahan", 1.0), ("yes", 1.0), ("ok", 0.8), ("Brooklyn", 1.2),
                     ("Thank you.", 4.0),                 # a long note: maybe really said
                     ("588", None)):
            with self.subTest(t):
                self.assertFalse(wa_voice.heard_nothing(t, d))

    def test_the_reply(self):
        self.assertEqual(wa_voice.DM_CANT_HEAR,
                         "I couldn't hear that voice note — can you type it?")


class TheDmPath(unittest.TestCase):

    def test_checked_before_any_reply_or_answer(self):
        import server
        src = inspect.getsource(server._process_whatsapp_message)
        i = src.index("await _dm_voice_unheard(dm_chat, vresult, voice_message_id)")
        self.assertLess(i, src.index("if not vresult.ok:\n                    # Short-circuit"))
        self.assertLess(i, src.index("_dm_assistant_reply("))

    def test_every_open_question_counts(self):
        import server
        self.assertEqual(set(server.DM_OPEN_QUESTIONS),
                         {server.DM_ACTION_STATE, server.UPCOMING_REMIND_STATE,
                          "dm_clarify", "dm_menu"})


if __name__ == "__main__":
    unittest.main()
