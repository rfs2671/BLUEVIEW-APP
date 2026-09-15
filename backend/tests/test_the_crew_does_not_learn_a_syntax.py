"""Addressing, after the measurement that said a third of the questions were lost.

THE NUMBER THIS FILE EXISTS FOR. The only group that has ever carried real
traffic produced 34 unaddressed messages. Eleven of them were questions the bot
could have answered and never saw:

    "Who's on site?"   "Active permits"   "Permit status?"   "Who's on sote"
    "Done 2"           "Done 3"           "lunch at 12?"     "Yes" x3   "?"

Not one was malformed. They were people talking normally to something they
believed was listening. Three separate rules were each dropping a share, and
each one has a class below:

  * the soft-trigger list was unreachable outside loose mode, and loose was not
    the default
  * a reply to one of the bot's own messages did not count, because the parser
    returned the quoted TEXT and never the quoted AUTHOR
  * the session window ran from the last explicit mention rather than the last
    exchange, so a live conversation died at 180 seconds

WHY THE STUBS. `_is_bot_addressed` reaches the database for session state and
nothing else. Standing up Mongo to prove a branch ordering would test the
scaffolding; the session helpers are replaced with in-memory equivalents that
record what was asked and what was written, which is the only thing these
assertions are about.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _Sessions:
    """In-memory stand-in for the two conversation-state helpers."""

    def __init__(self, live=False):
        self.live = live
        self.marks = []

    async def mark(self, group_id, sender):
        self.marks.append((group_id, sender))
        self.live = True

    async def is_in(self, group_id, sender):
        return self.live


class _AddressingCase(unittest.TestCase):
    """Shared plumbing: swap the session helpers, restore them after."""

    def setUp(self):
        self.sessions = _Sessions()
        self._real_mark = server._mark_bot_session
        self._real_is_in = server._is_in_bot_session
        server._mark_bot_session = self.sessions.mark
        server._is_in_bot_session = self.sessions.is_in

    def tearDown(self):
        server._mark_bot_session = self._real_mark
        server._is_in_bot_session = self._real_is_in

    def addressed(self, body="", *, mode="loose", voice=False,
                  quoted_body="", quoted_from_bot=False, mentioned=None):
        return _run(server._is_bot_addressed(
            body, "15165494475", voice,
            group_id="1203@g.us", sender="17185551212",
            mode=mode, quoted_body=quoted_body,
            mentioned_jids=mentioned, quoted_from_bot=quoted_from_bot,
        ))


class TheNameIsAWordPeopleSay(_AddressingCase):
    """It used to need the name at the FRONT of the message.

    `startswith("levelog ")` accepts "levelog who is on site" and rejects
    every natural way a person refers to something in a sentence."""

    def test_the_name_anywhere_in_the_sentence(self):
        for body in (
            "levelog who is on site",
            "ask levelog who is on site",
            "who is on site levelog",
            "Levelog, who is on site?",
            "@levelog who is on site",
            "hey Levelog can you check permits",
        ):
            with self.subTest(body=body):
                self.assertTrue(self.addressed(body, mode="strict"),
                                f"not addressed: {body!r}")

    def test_it_is_a_word_and_not_a_substring(self):
        """A substring test would fire on anything containing the letters."""
        for body in ("we are leveloging the slab", "see levelogger.example.com"):
            with self.subTest(body=body):
                self.assertFalse(self.addressed(body, mode="strict"),
                                 f"matched inside a longer word: {body!r}")

    def test_case_does_not_matter(self):
        self.assertTrue(self.addressed("LEVELOG status?", mode="strict"))


class ReplyingToTheBotIsAddressingIt(_AddressingCase):
    """The docstring promised this for as long as the function has existed.

    "Done 2" and "Done 3" — replies to a checklist the bot itself posted —
    were among the eleven lost messages."""

    def test_a_reply_to_the_bot_counts_in_strict_mode(self):
        self.assertTrue(self.addressed("Done 2", mode="strict",
                                       quoted_from_bot=True))

    def test_it_counts_in_loose_mode_too(self):
        self.assertTrue(self.addressed("Done 2", mode="loose",
                                       quoted_from_bot=True))

    def test_without_the_signal_a_bare_reply_is_not_addressed(self):
        """Strict mode and no other route in: the old behaviour, which is
        still correct when the quoted message was written by a person."""
        self.assertFalse(self.addressed("Done 2", mode="strict",
                                        quoted_from_bot=False))

    def test_a_quoted_message_that_mentions_the_bot_still_counts(self):
        """The pre-existing route, unbroken by the new one."""
        self.assertTrue(self.addressed("and the roof?", mode="strict",
                                       quoted_body="@levelog who is on site"))


class TheWindowRollsForward(_AddressingCase):
    """It used to be marked only on the two explicit branches, so riding the
    window never renewed it: the 180 seconds ran from the tag, not from the
    conversation, and a live exchange died mid-sentence."""

    def test_every_route_in_marks_the_session(self):
        cases = {
            "mention":      dict(body="levelog who is on site", mode="strict"),
            "reply_to_bot": dict(body="Done 2", quoted_from_bot=True, mode="strict"),
            "trigger":      dict(body="who is on site", mode="loose"),
            "voice":        dict(body="", voice=True, mode="loose"),
        }
        for name, kw in cases.items():
            with self.subTest(route=name):
                self.sessions = _Sessions()
                server._mark_bot_session = self.sessions.mark
                server._is_in_bot_session = self.sessions.is_in
                self.assertTrue(self.addressed(**kw))
                self.assertEqual(len(self.sessions.marks), 1,
                                 f"{name} did not renew the window")

    def test_riding_the_window_renews_it(self):
        """The regression itself. A follow-up that routes ON the session must
        push the session out, or the conversation has a hard three-minute
        ceiling no matter how active it is."""
        self.sessions.live = True
        self.assertTrue(self.addressed("and the roof?", mode="strict"))
        self.assertEqual(self.sessions.marks, [("1203@g.us", "17185551212")])

    def test_a_message_that_is_not_addressed_marks_nothing(self):
        self.assertFalse(self.addressed("bring the truck around back",
                                        mode="strict"))
        self.assertEqual(self.sessions.marks, [])


class LooseHonoursTheSessionToo(_AddressingCase):
    """Loose mode used to `return False` before ever reaching the session
    check, so a follow-up with no trigger word was dropped in the mode that
    was supposed to be the forgiving one."""

    def test_a_follow_up_with_no_trigger_word_rides_the_session(self):
        self.sessions.live = True
        self.assertTrue(self.addressed("and the roof", mode="loose"))

    def test_the_same_message_without_a_session_is_not_addressed(self):
        self.sessions.live = False
        self.assertFalse(self.addressed("and the roof", mode="loose"))


class TheEeventualQuestions(_AddressingCase):
    """The eleven, run through the new rules. This is the test that would have
    caught the problem, written against the messages that exposed it."""

    LOST = [
        "Who's on site?",
        "Active permits",
        "Permit status?",
        "Who's on sote",
        "lunch at 12?",
    ]

    def test_the_real_questions_now_reach_the_agent(self):
        for body in self.LOST:
            with self.subTest(body=body):
                self.assertTrue(self.addressed(body, mode="loose"),
                                f"still dropped: {body!r}")

    def test_the_checklist_replies_reach_it_as_replies(self):
        for body in ("Done 2", "Done 3"):
            with self.subTest(body=body):
                self.assertTrue(
                    self.addressed(body, mode="loose", quoted_from_bot=True))

    def test_loose_is_not_a_promise_to_answer(self):
        """"lunch at 12?" routes to the AGENT under loose. It does not follow
        that the bot speaks: NOREPLY is what keeps loose from being noisy, and
        that clause is in the prompt rather than in this function."""
        self.assertIn("NOREPLY", server._AGENT_NOREPLY_CLAUSE)
        self.assertIn("not for", server._AGENT_NOREPLY_CLAUSE.lower())


class TheParserLearnsWhoWroteTheQuotedMessage(unittest.TestCase):
    """Without the author, "is this a reply to the bot" cannot be asked, which
    is why the check the docstring described was never implemented."""

    def _parse(self, msg):
        return server.parse_inbound_message(
            {"data": {"message": msg}}, vendor="waapi")

    def test_from_me_on_the_quoted_node_is_read(self):
        p = self._parse({
            "from": "1203@g.us", "author": "17185551212@c.us", "body": "Done 2",
            "quotedMsg": {"body": "1. Patch the slab", "id": {"fromMe": True}},
        })
        self.assertTrue(p["quoted_from_me"])

    def test_a_quoted_message_from_a_person_is_not_from_me(self):
        p = self._parse({
            "from": "1203@g.us", "author": "17185551212@c.us", "body": "Done 2",
            "quotedMsg": {"body": "who's bringing rebar", "id": {"fromMe": False}},
        })
        self.assertFalse(p["quoted_from_me"])

    def test_the_participant_jid_is_the_fallback(self):
        """Payloads that carry the author but not the flag. The JID is matched
        against the bot identifier set at the call site, not here."""
        p = self._parse({
            "from": "1203@g.us", "author": "17185551212@c.us", "body": "Done 2",
            "contextInfo": {"participant": "15165494475@c.us"},
            "quotedMsg": {"body": "1. Patch the slab"},
        })
        self.assertEqual(p["quoted_author"], "15165494475@c.us")

    def test_the_fields_are_always_present(self):
        """Absent, they would be a KeyError on every message without a quote."""
        p = self._parse({"from": "1203@g.us", "author": "1@c.us", "body": "hi"})
        self.assertIn("quoted_from_me", p)
        self.assertIn("quoted_author", p)
        self.assertFalse(p["quoted_from_me"])


class SilenceIsTheFailureThisTeaches(unittest.TestCase):
    """A question nobody answered is worse than a wrong answer: the person
    learns the bot is broken and stops asking. That is how the measured group
    went quiet."""

    def test_a_question_mark_is_a_question(self):
        for body in ("Who's on site?", "lunch at 12?", "permits?"):
            with self.subTest(body=body):
                self.assertTrue(server._looks_like_a_question(body))

    def test_a_question_word_at_the_start_counts_without_one(self):
        """Most people do not type the mark on a phone."""
        for body in ("who is on site", "any permits expiring", "how many guys"):
            with self.subTest(body=body):
                self.assertTrue(server._looks_like_a_question(body))

    def test_a_statement_is_not_a_question(self):
        for body in ("bring the truck around back", "that's what I said",
                     "ok", "Done 2", ""):
            with self.subTest(body=body):
                self.assertFalse(server._looks_like_a_question(body))

    def test_the_question_word_is_anchored_to_the_start(self):
        """"what" in the middle of a sentence is usually a statement, and a
        nudge fired at one is the bot correcting a conversation it was not
        part of."""
        self.assertFalse(server._looks_like_a_question("that is what we did"))


class OneNumberManySpellings(unittest.TestCase):
    """Five of six contacts writers store +1XXXXXXXXXX; both readers searched
    bare digits. Every row written since the integration was switched on was
    unfindable, silently, on both sides."""

    def test_bare_digits_find_an_e164_row(self):
        self.assertIn("+15165494475",
                      server._contact_phone_variants("15165494475"))

    def test_an_e164_sender_finds_a_bare_digits_row(self):
        self.assertIn("15165494475",
                      server._contact_phone_variants("+15165494475"))

    def test_a_ten_digit_profile_entry_is_reachable(self):
        """What a user types into a settings field, against what WhatsApp
        sends, which always carries the country code."""
        self.assertIn("5165494475",
                      server._contact_phone_variants("15165494475"))

    def test_punctuation_is_irrelevant(self):
        self.assertEqual(server._contact_phone_variants("(516) 549-4475"),
                         server._contact_phone_variants("5165494475"))

    def test_an_empty_phone_produces_no_candidates(self):
        """The guard the whole of test_empty_phone_matches_nobody exists for:
        no digits means no query, not a query that matches a stored blank."""
        for bad in ("", "   ", "---", None):
            with self.subTest(phone=bad):
                self.assertEqual(server._contact_phone_variants(bad), [])

    def test_no_candidate_is_ever_empty(self):
        for phone in ("15165494475", "+15165494475", "5165494475"):
            with self.subTest(phone=phone):
                for v in server._contact_phone_variants(phone):
                    self.assertTrue(v)


class WhatAGroupGetsBeforeAnybodyConfiguresIt(unittest.TestCase):

    def test_new_groups_are_loose(self):
        """Flipped on measurement, not on taste. Strict lost about a third of
        the real questions put to it."""
        cfg = server._default_bot_config()
        self.assertEqual(cfg["features"]["address_mode"], "loose")

    def test_checklists_are_on(self):
        """Off-by-default and does-not-exist are the same thing to every user
        who has not read the source, and no screen advertises the feature."""
        self.assertTrue(server._default_bot_config()["checklist_extraction_enabled"])

    def test_plan_queries_are_on(self):
        self.assertTrue(server._default_bot_config()["features"]["plan_queries"])

    def test_voice_notes_are_on(self):
        self.assertTrue(server._default_bot_config()["features"]["voice_notes"])

    def test_unprompted_sending_stays_off(self):
        """The surprise argument still holds for anything the bot sends without
        being asked. A digest arriving at 17:00 in a group that never requested
        one is spam; a checklist only appears when somebody asks."""
        self.assertFalse(server._default_bot_config()["daily_summary_enabled"])

    def test_every_default_feature_is_an_accepted_config_key(self):
        """A default the config endpoint rejects is a group that cannot be
        edited without a 422."""
        for k in server._default_bot_config()["features"]:
            with self.subTest(feature=k):
                self.assertIn(k, server._WHATSAPP_FEATURE_KEYS)


class TheCodeDoesNotHaveToBeTheWholeMessage(unittest.TestCase):
    """It was anchored at both ends, so "code 481920" did nothing — and the
    natural response to nothing happening is to generate another code and fail
    the same way."""

    PATTERN = re.compile(r"\b(\d{6})\b")

    def test_a_code_with_a_word_in_front_is_found(self):
        self.assertEqual(self.PATTERN.findall("code 481920"), ["481920"])

    def test_a_bare_code_still_works(self):
        self.assertEqual(self.PATTERN.findall("481920"), ["481920"])

    def test_every_run_is_offered_not_only_the_first(self):
        self.assertEqual(self.PATTERN.findall("job 447102 code 481920"),
                         ["447102", "481920"])

    def test_a_longer_number_is_not_a_code(self):
        """Word boundaries: a phone number or a permit number must not be
        chopped into a six-digit candidate."""
        self.assertEqual(self.PATTERN.findall("call 15165494475"), [])

    def test_the_loosened_pattern_is_the_one_in_the_handler(self):
        """CODE LINES ONLY. The first draft of this test read the raw source
        and failed on the comment directly above the fix, which quotes the
        anchored pattern in order to explain what it used to be. A regression
        guard that trips on its own rationale is a guard nobody keeps."""
        import inspect
        src = inspect.getsource(server._process_whatsapp_message)
        code = "\n".join(
            line for line in src.split("\n")
            if not line.lstrip().startswith("#")
        )
        self.assertIn(r'findall(r"\b(\d{6})\b"', code)
        self.assertNotIn(r'match(r"^\s*(\d{6})\s*$"', code,
                         "the anchored pattern is back in the code")


if __name__ == "__main__":
    unittest.main()
