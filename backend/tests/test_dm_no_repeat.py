"""dm_eval, Oct 20: never the same answer to a different question.

"Show me" after a plans answer got the plans text again, 16 s later; "the
drawing" and "picture" did too; "Cancel checklist" and "Done" got one
sentence twice. An answer word for word Levelog's last one, for a
different question inside 30 minutes, is not sent: one short question goes
instead, logged as path "no_repeat" with the answer it would have sent.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import server  # noqa: E402
from lib import wa_assistant  # noqa: E402
from tests.test_dm_short_answers import _Site  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx  # noqa: E402

WINDOW = ("Window protection details are on SSP-011.00. It specifies using MAGZO Adjustable "
          "Window Screen, 48x99 Inch Durable Fiberglass Screen Mesh or an accepted equal.")
CHECKLIST = "Checklist creation or cancellation is done in the app."


class _Agent(_Site):
    """The job agent, answering every question with the same words."""
    words = WINDOW

    def say(self, c, body, quoted=None, from_bot=False, llm=None, key=None):
        async def agent(**kw):
            self.agent_calls.append(kw)
            kw["tool_trace"].append({"tool": "search_plans", "result": self.words})
            return self.words
        with patch.object(server, "_run_group_agent", agent):
            return self._say(c, body, quoted, from_bot, llm, key)


class TheOct20Repeats(_Agent, unittest.TestCase):

    def test_a_different_question_does_not_get_the_same_words(self):
        with _Ctx(db=self.db) as c:
            first = self.say(c, "Any info about window protection at ssp for 588?")
            second = self.say(c, "what about the details at 588")
        self.assertTrue(first.startswith("Window protection details are on SSP-011.00."), first)
        self.assertEqual(second, "That's what I just sent. Want the drawing — SSP-011.00? Say “show me”.")
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual(log["path"], "no_repeat")
        self.assertTrue(log["repeated"].startswith("Window protection details"))

    def test_never_the_same_question_twice_either(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Any info about window protection at ssp for 588?")
            second = self.say(c, "what about the details at 588")
            third = self.say(c, "and the specs for 588 windows")
        self.assertTrue(second.startswith("That's what I just sent."), second)
        self.assertEqual(third, "I'm not getting it — say it another way, or “show me” for the drawing.")

    def test_the_same_question_again_may_get_the_same_answer(self):
        with _Ctx(db=self.db) as c:
            first = self.say(c, "Any info about window protection at ssp for 588?")
            again = self.say(c, "Any info about window protection at ssp for 588?")
        self.assertEqual(first, again)

    def test_no_sheet_cited_asks_plainly(self):
        self.words = CHECKLIST
        with _Ctx(db=self.db) as c:
            self.say(c, "whats the checklist status at 588")
            second = self.say(c, "anything else open at 588")
        self.assertEqual(second, "That's what I just sent. What should I look at differently?")

    def test_a_headcount_reworded_still_gets_its_count(self):
        """"How many subs" / "How many companies": the same answer is right."""
        with _Ctx(db=self.db) as c:
            a = self.say(c, "How many subs on site at 588?")
            b = self.say(c, "How many companies on site at 588")
        self.assertEqual(a, b)
        self.assertNotIn("what I just sent", b)


class TheRule(unittest.TestCase):
    now = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)

    def hist(self, q, a, minutes_ago=1):
        at = self.now - timedelta(minutes=minutes_ago)
        return [{"sender": "15550001111", "body": q, "created_at": at - timedelta(seconds=5)},
                {"sender": "bot", "body": a, "created_at": at}]

    def test_identical_answer_different_question(self):
        self.assertEqual(wa_assistant.repeat_of_last("A.", self.hist("q one", "A."), "q two", self.now), "A.")

    def test_same_question(self):
        self.assertIsNone(wa_assistant.repeat_of_last("A.", self.hist("Q one?", "A."), "q one", self.now))

    def test_outside_the_window(self):
        self.assertIsNone(wa_assistant.repeat_of_last("A.", self.hist("q1", "A.", 31), "q2", self.now))

    def test_a_different_answer(self):
        self.assertIsNone(wa_assistant.repeat_of_last("B.", self.hist("q1", "A."), "q2", self.now))

    def test_a_voice_answer_compares_without_heard(self):
        h = self.hist("q1", 'Heard: "where is it"\n\nA.')
        self.assertEqual(wa_assistant.repeat_of_last("A.", h, "q2", self.now), "A.")

    def test_a_reworded_question_is_the_same_question(self):
        h = self.hist("open items at 8 walworth", "A.")
        self.assertIsNone(wa_assistant.repeat_of_last("A.", h, "and the open items?", self.now))

    def test_a_reply_to_points_at_context(self):
        q = 'The list\n\n(This is a reply to your (Levelog Assistant\'s) earlier message: "x")'
        self.assertIsNone(wa_assistant.repeat_of_last("A.", self.hist("Was it sent?", "A."), q, self.now))

    def test_the_oct_20_pairs_are_different_questions(self):
        for q1, q2 in [("Any info about window protection at ssp for 588?", "the drawing"),
                       ("the drawing", "picture"), ("Cancel checklist", "Done"),
                       ("Any info about window protection at ssp for 588?", "Show me")]:
            self.assertEqual(wa_assistant.repeat_of_last("A.", self.hist(q1, "A."), q2, self.now), "A.",
                             (q1, q2))

    def test_a_sheet_in_between_is_not_the_last_answer(self):
        h = self.hist("Any info about window protection?", "A.", 3) + [
            {"sender": "15550001111", "body": "send it", "created_at": self.now - timedelta(minutes=2)},
            {"sender": "bot", "body": "[Sheet] SSP-011.00 — Window Protection Details",
             "created_at": self.now - timedelta(minutes=2)}]
        self.assertEqual(wa_assistant.repeat_of_last("A.", h, "the drawing", self.now), "A.")

    def test_any_text_answer_in_the_window_counts(self):
        """"the drawing" got a question back; "picture" must not then get
        the plans text from two messages before."""
        h = self.hist("q one", "A.", 5) + self.hist("q two", "B.", 1)
        self.assertEqual(wa_assistant.repeat_of_last("A.", h, "q three", self.now), "A.")


if __name__ == "__main__":
    unittest.main()
