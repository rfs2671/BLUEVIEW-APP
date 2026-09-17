"""Three defects from the first live test of the WhatsApp agent, 2026-09-14.

Each class below is one thing the bot got wrong in front of a real
superintendent, with the reason it got it wrong.

  1. Asked whether a man on site had a current SST card, it said to check with
     HR. The card status was two fields away on the very check-in row the
     roster was built from, and the roster handler did not render it.

  2. "show me how many outlets are on the roof plan" came back as a drawing.
     And when every candidate sheet answered NOT_SHOWN_ON_SHEET, the handler
     sent the top sheet as a picture anyway — the model had just looked at that
     exact drawing and said the thing is not on it.

  3. Asked a follow-up about one worker, it re-listed the whole crew first, and
     signed off with "anything else?".
"""

from __future__ import annotations

import inspect
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _cert(kind, days=None, **extra):
    exp = NOW + timedelta(days=days) if days is not None else None
    return {"certifications": [dict({"type": kind, "expiration_date": exp}, **extra)]}


# ══════════════════════════════════════════════════════════════════
# 1. "Check with HR" for data the system holds
# ══════════════════════════════════════════════════════════════════

class TheCardStateTravelsWithTheName(unittest.TestCase):

    def test_every_state_renders_something_a_person_can_act_on(self):
        cases = {
            "valid":         ("SST ok", True),
            "expiring_soon": ("SST EXPIRING", True),
            "expired":       ("SST EXPIRED", True),
            "missing":       ("NO SST CARD", False),
            "unknown":       ("SST unconfirmed", False),
        }
        for status, (label, wants_date) in cases.items():
            with self.subTest(status=status):
                out = server._sst_suffix(status, NOW + timedelta(days=5))
                self.assertIn(label, out)
                if wants_date:
                    self.assertIn("2026-09-19", out)

    def test_a_worker_with_no_card_data_reads_as_it_always_did(self):
        """The suffix has to be empty, not "unknown", when the field is simply
        absent — otherwise every roster in a company that does not track cards
        grows a column of noise."""
        self.assertEqual(server._sst_suffix(None, None), "")
        self.assertEqual(server._sst_suffix("", None), "")

    def test_an_unknown_card_prints_no_date(self):
        """`unknown` exists because the expiry could not be read. Printing a
        date next to it would be asserting the thing we just said we do not
        know."""
        self.assertNotIn("exp", server._sst_suffix("unknown", None))

    def test_a_string_expiry_is_handled_like_a_datetime(self):
        """Frozen check-in fields are datetimes; a re-serialised row is a
        string. Both reach this."""
        self.assertIn("2027-01-05", server._sst_suffix("valid", "2027-01-05T00:00:00Z"))


class TheRosterDerivesTheSameVerdict(unittest.TestCase):
    """who_on_site reads the frozen check-in fields; list_workers has no
    check-in and derives it live. The two must never produce two words for one
    state, or the agent reads them as different facts."""

    def test_no_sst_card_is_missing(self):
        self.assertEqual(
            server._sst_from_worker({"certifications": []}, NOW)[0], "missing")

    def test_a_current_card_is_valid(self):
        self.assertEqual(
            server._sst_from_worker(_cert("SST_FULL", 200), NOW)[0], "valid")

    def test_within_thirty_days_is_expiring_soon(self):
        self.assertEqual(
            server._sst_from_worker(_cert("SST_FULL", 10), NOW)[0], "expiring_soon")

    def test_a_lapsed_card_is_expired(self):
        self.assertEqual(
            server._sst_from_worker(_cert("SST_FULL", -1), NOW)[0], "expired")

    def test_an_unreadable_class_is_never_silently_valid(self):
        """SST_UNSPECIFIED means the card was there and the class could not be
        read. That is the distinction the whole cert vocabulary exists for."""
        self.assertEqual(
            server._sst_from_worker(_cert("SST_UNSPECIFIED", 200), NOW)[0], "unknown")

    def test_a_missing_expiry_is_unknown_not_valid(self):
        self.assertEqual(
            server._sst_from_worker(_cert("SST_FULL", None), NOW)[0], "unknown")

    def test_a_rejected_ocr_expiry_is_unknown(self):
        w = _cert("SST_FULL", 200, expiration_raw_rejected=True)
        self.assertEqual(server._sst_from_worker(w, NOW)[0], "unknown")

    def test_expired_beats_unknown(self):
        """A card that has definitely lapsed is not "unconfirmed". Ordering
        matters: the worse, more certain state wins."""
        w = _cert("SST_UNSPECIFIED", -5)
        self.assertEqual(server._sst_from_worker(w, NOW)[0], "expired")

    def test_a_class_confirmed_card_is_preferred_over_an_unspecified_one(self):
        w = {"certifications": [
            {"type": "SST_UNSPECIFIED", "expiration_date": None},
            {"type": "SST_FULL", "expiration_date": NOW + timedelta(days=300)},
        ]}
        self.assertEqual(server._sst_from_worker(w, NOW)[0], "valid")

    def test_both_paths_use_the_same_five_words(self):
        derived = {server._sst_from_worker(w, NOW)[0] for w in (
            {"certifications": []},
            _cert("SST_FULL", 200), _cert("SST_FULL", 10),
            _cert("SST_FULL", -1), _cert("SST_UNSPECIFIED", 200),
        )}
        self.assertTrue(derived.issubset(set(server._SST_LABEL)))


class TheHeadlineAnswersTheQuestionWithoutCounting(unittest.TestCase):

    def test_the_tally_leads_with_what_is_wrong(self):
        """"Is everyone current?" should be answerable off the first line. The
        bad states come first because they are the reason to read on."""
        out = server._sst_tally(
            ["valid", "valid", "expired", "missing", "expiring_soon"])
        self.assertLess(out.index("SST EXPIRED"), out.index("SST ok"))
        self.assertLess(out.index("NO SST CARD"), out.index("SST ok"))

    def test_an_all_clear_crew_still_gets_a_line(self):
        self.assertIn("3 SST ok", server._sst_tally(["valid"] * 3))

    def test_no_card_data_produces_no_line(self):
        self.assertEqual(server._sst_tally([None, None]), "")


class TheToolsSayTheCardDataIsThere(unittest.TestCase):
    """The handler can return the data and the agent will still say "check with
    HR" if nothing tells it the data is in the result."""

    def _desc(self, name):
        for t in server._AGENT_TOOLS:
            if t["function"]["name"] == name:
                return t["function"]["description"]
        raise AssertionError(f"no tool named {name}")

    def test_both_roster_tools_advertise_card_status(self):
        for name in ("who_on_site", "list_workers"):
            with self.subTest(tool=name):
                self.assertIn("SST", self._desc(name))

    def test_both_forbid_the_deflection_that_was_reported(self):
        for name in ("who_on_site", "list_workers"):
            with self.subTest(tool=name):
                self.assertIn("HR", self._desc(name))


# ══════════════════════════════════════════════════════════════════
# 2. Plan questions — where this section went
# ══════════════════════════════════════════════════════════════════
#
# Three classes lived here: a count must not be answered with a picture,
# an auxiliary in the middle of a sentence is grammar and not a yes/no,
# and a vision model that said NOT_SHOWN_ON_SHEET must not have its sheet
# sent anyway. All three tested _classify_plan_question and the vision
# fallback inside _handle_plan_query, and both are deleted.
#
# Nothing routes on phrasing now. The agent calls search_plans to answer
# and query_plan to send a sheet, and may call both; query_plan answers
# nothing at all, so a count cannot be answered with a picture because a
# picture is not an answer to anything. Held by
# test_one_reader_reads_the_drawings.py. The third class is moot: there
# is no vision model on the answer path to say NOT_SHOWN_ON_SHEET.
#
# eval/migrated-from-the-matcher.md records the move.


# ══════════════════════════════════════════════════════════════════
# 3. Saying it twice, and signing off
# ══════════════════════════════════════════════════════════════════

class DoNotSayItTwice(unittest.TestCase):

    PROMPT = server._AGENT_SYSTEM_PROMPT_BASE

    def test_the_prompt_forbids_re_listing(self):
        self.assertIn("DO NOT REPEAT WHAT YOU JUST SENT", self.PROMPT)

    def test_it_says_why_the_user_can_still_see_it(self):
        """A rule without its reason gets dropped the next time the prompt is
        edited. In a group chat the previous reply is two inches up the
        screen."""
        self.assertIn("can still see", self.PROMPT)

    def test_a_follow_up_about_one_item_gets_one_item(self):
        self.assertIn("one item", self.PROMPT)

    def test_generic_sign_offs_are_named_and_banned(self):
        for phrase in ("anything else?", "let me know", "happy to help"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.PROMPT.lower())
        self.assertIn("NEVER end with a generic offer", self.PROMPT)

    def test_the_specific_next_step_doctrine_survives(self):
        """The ban is on the empty offer, not on a useful one: "want me to
        start renewal for <permit>?" is the behaviour worth keeping."""
        self.assertIn("Want me to start renewal", self.PROMPT)
        self.assertIn("names a", self.PROMPT)


if __name__ == "__main__":
    unittest.main()
