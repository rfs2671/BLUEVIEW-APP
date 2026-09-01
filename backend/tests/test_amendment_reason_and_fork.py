"""A correction explains itself, and a record has ONE open correction.

TWO GUARDS, ONE INCIDENT. On 2026-08-31 a CP filed FIVE amendments to one
worker's orientation in eight minutes, each with a one-character reason -- "1"
four times and "0" once -- and the fifth forked: two unsigned children on the
same parent, neither of which is the record and both of which claim to be.

Nothing wrote those digits. The client gate was `if (!reason.trim())` and the
server gate was `if not reason or not str(reason).strip()`. Both ask only
whether the field is non-empty. "1" is the shortest thing that passes, and the
button enabled on the first keystroke. A check on PRESENCE standing in for a
check on CONTENT -- the same defect as every other one that day.

── WHY THIS RULE, AND NOT A LENGTH ALONE ───────────────────────────────────

A bare minimum length is defeated by "11111111". A rule banning numerals would
refuse "corrected count to 4", which is a better reason than most. So the test
is: SIX characters after trimming, AND at least one run of three letters -- a
word.

Six, because a real short reason must pass: "wrong trade" (11), "bad trade"
(9), "no OSHA" (7) are all legitimate and all clear it. Lower would admit "ok";
higher would start refusing reasons a CP would reasonably give. The word
requirement is what actually does the work: it is what "1", "0", "11" and
"12345678" fail, without the rule ever mentioning digits.

It is not proof against a determined bypass -- "aaaaaa" passes -- and it is not
meant to be. It stops the accidental digit, which is what happened.

── THE REFUSAL TEACHES, AND THE CLIENT OWNS THE WORDING ────────────────────

The server names the CONDITION with a machine code and the minimum; the client
renders the sentence the CP reads. That is this codebase's gateCopy rule and it
applies here because, unlike the public signature endpoint, there IS a CP and
there IS a screen. A refusal that does not teach produces "11" on the next
attempt.

── ONE OPEN CORRECTION PER RECORD ──────────────────────────────────────────

An unsigned amendment is an intention, not a correction. Two of them on one
parent are two competing intentions, and since the record is the deepest SIGNED
link, neither is the record while both are unsigned. The second is refused --
and the refusal CARRIES THE OPEN ONE so the client can offer it instead of
dead-ending the CP, which is what produced five amendments in the first place.

The head is chosen DETERMINISTICALLY, by the same (created_at, _id) ordering
_filed_log uses. With two open children a raw find_one would return whichever
Mongo happened to hand back first, and the refusal would point at a different
draft on each attempt.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

T0 = datetime(2026, 8, 31, 17, 9, 58, tzinfo=timezone.utc)


class TheReasonMustBeReadable(unittest.TestCase):
    def test_the_digits_that_actually_happened_are_refused(self):
        for typed in ("1", "0", "11", "  1  "):
            self.assertEqual(server.amendment_reason_problem(typed),
                             server.AMENDMENT_REASON_NOT_A_SENTENCE, repr(typed))

    def test_an_empty_reason_is_its_own_code(self):
        """"You left it blank" and "that is not a sentence" are different
        things to be told."""
        for blank in ("", "   ", None):
            self.assertEqual(server.amendment_reason_problem(blank),
                             server.AMENDMENT_REASON_REQUIRED, repr(blank))

    def test_short_but_REAL_reasons_pass(self):
        """The floor has to clear the reasons a CP would actually give."""
        for good in ("wrong trade", "bad trade", "no OSHA", "wrong company",
                     "corrected count to 4", "Fixed the weather entry",
                     "duplicate of the 11am orientation"):
            self.assertIsNone(server.amendment_reason_problem(good), good)

    def test_it_does_NOT_ban_numerals(self):
        """A rule that refused digits would refuse the best reasons."""
        self.assertIsNone(server.amendment_reason_problem("corrected count to 4"))
        self.assertIsNone(server.amendment_reason_problem("4 men not 6, per gate"))

    def test_a_string_of_digits_fails_on_the_WORD_rule_not_a_digit_rule(self):
        """Long enough to clear the length floor, still not a reason."""
        self.assertEqual(server.amendment_reason_problem("12345678"),
                         server.AMENDMENT_REASON_NOT_A_SENTENCE)
        self.assertEqual(server.amendment_reason_problem("1 2 3 4 5 6"),
                         server.AMENDMENT_REASON_NOT_A_SENTENCE)

    def test_two_letters_is_not_a_word(self):
        self.assertEqual(server.amendment_reason_problem("ok ok"),
                         server.AMENDMENT_REASON_NOT_A_SENTENCE)

    def test_the_floor_is_stated_for_the_client_to_render(self):
        """The client owns the wording and needs the number to say it."""
        self.assertEqual(server.AMENDMENT_REASON_MIN_CHARS, 6)


class TheHeadIsChosenDeterministically(unittest.TestCase):
    """With TWO open children a raw find_one returns whichever Mongo hands
    back first, and the refusal would name a different draft each attempt."""

    A = {"_id": "aaa", "created_at": T0, "cp_signature": None}
    B = {"_id": "bbb", "created_at": T0 + timedelta(seconds=49), "cp_signature": None}

    def test_the_newest_open_child_is_the_head(self):
        self.assertEqual(server.open_amendment_head([self.A, self.B])["_id"], "bbb")

    def test_order_of_the_input_does_not_change_it(self):
        self.assertEqual(server.open_amendment_head([self.B, self.A])["_id"], "bbb")

    def test_a_tie_on_created_at_breaks_on_id_not_on_luck(self):
        x = {"_id": "zzz", "created_at": T0, "cp_signature": None}
        y = {"_id": "aaa", "created_at": T0, "cp_signature": None}
        self.assertEqual(server.open_amendment_head([x, y])["_id"], "zzz")
        self.assertEqual(server.open_amendment_head([y, x])["_id"], "zzz")

    def test_a_missing_created_at_does_not_crash_or_win(self):
        n = {"_id": "nnn", "cp_signature": None}
        self.assertEqual(server.open_amendment_head([n, self.B])["_id"], "bbb")

    def test_no_open_children_is_None(self):
        self.assertIsNone(server.open_amendment_head([]))
        self.assertIsNone(server.open_amendment_head(None))


class TheRefusalCarriesTheOpenOne(unittest.TestCase):
    """NEVER A DEAD END. Dead-ending the CP is what produced five amendments."""

    def test_the_endpoint_refuses_a_second_open_amendment(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("async def amend_logbook")
        body = src[i:i + 4000]
        self.assertIn("AMENDMENT_ALREADY_OPEN", body)
        self.assertIn("open_amendment_head", body)

    def test_it_returns_the_open_childs_id(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("AMENDMENT_ALREADY_OPEN")
        block = src[i - 400:i + 700]
        self.assertIn("logbook_id", block)

    def test_it_refuses_BEFORE_inserting(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("async def amend_logbook")
        body = src[i:i + 6000]
        self.assertLess(body.index("AMENDMENT_ALREADY_OPEN"),
                        body.index("db.logbooks.insert_one"))

    def test_the_reason_check_also_runs_before_the_insert(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("async def amend_logbook")
        body = src[i:i + 6000]
        self.assertLess(body.index("amendment_reason_problem"),
                        body.index("db.logbooks.insert_one"))


class ASIGNEDChildDoesNotBlock(unittest.TestCase):
    """The chain must keep growing. Only an UNSIGNED head blocks — a signed
    amendment is a correction that landed, and the next one amends it."""

    def test_a_signed_child_is_not_open(self):
        signed = {"_id": "s", "created_at": T0, "cp_signature": {"data": "ink"}}
        self.assertIsNone(server.open_amendment_head([signed]))

    def test_a_submitted_child_is_not_open(self):
        sub = {"_id": "s", "created_at": T0, "status": "submitted"}
        self.assertIsNone(server.open_amendment_head([sub]))

    def test_a_locked_child_is_not_open(self):
        lk = {"_id": "s", "created_at": T0, "is_locked": True}
        self.assertIsNone(server.open_amendment_head([lk]))

    def test_the_unsigned_one_among_signed_siblings_is_still_the_head(self):
        signed = {"_id": "s", "created_at": T0, "status": "submitted"}
        openc = {"_id": "o", "created_at": T0 + timedelta(seconds=10),
                 "cp_signature": None}
        self.assertEqual(server.open_amendment_head([signed, openc])["_id"], "o")


if __name__ == "__main__":
    unittest.main()
