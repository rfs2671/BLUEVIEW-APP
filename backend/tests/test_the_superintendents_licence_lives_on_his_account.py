"""The DOB registration is a fact about a PERSON, and it warns at thirty days.

── WHERE IT USED TO LIVE, AND WHY THAT WAS WRONG ───────────────────────────

`cs_registrations` is PER PROJECT and it is the FILING GATE -- "who is the
construction superintendent on 588 Thomas". The licence number was being typed
into it again for every project, which makes one fact -- one man, one DOB
registration, one expiry -- into N copies that can disagree, with no third
place to ask which is right.

The licence now lives on the USER DOCUMENT and the gate is untouched. Those two
sentences have to both be true, and the second one is asserted by
test_the_superintendent_migration_does_not_move_his_filing_right.py.

── THIRTY DAYS, AND FOUR ANSWERS RATHER THAN TWO ───────────────────────────

An expired DOB registration makes every log signed afterwards an attestation by
an unregistered person. Thirty days is the operator's number: a renewal takes
weeks, and an alert on the day it lapses is an alert about a job that has
already stopped.

UNKNOWN IS NOT OK, AND THAT IS THE POINT OF THE FOURTH STATE. An account with
no expiry recorded is a licence NOBODY HAS CHECKED. Two states -- valid or
expiring -- would print the unchecked one as valid, which is this system
asserting something no person asserted. Michael arrives in exactly that state
the moment the migration runs, because nobody has typed his number in yet.

── THE BOUNDARY IS TESTED FROM BOTH SIDES ──────────────────────────────────

31 days is OK, 30 is EXPIRING, 0 is EXPIRING (it lapses today, it has not
lapsed), -1 is EXPIRED. A test that only checked "15 days is expiring" would
pass on a window of 7, of 30 and of 300.
"""

import datetime
import inspect
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://example.test")

import server  # noqa: E402

TODAY = datetime.date(2026, 9, 16)


def _state(expiry, today=TODAY):
    return server.superintendent_licence_state(
        {"role": server.ROLE_SUPERINTENDENT,
         "dob_registration_expiry": expiry}, today)


class ThirtyDaysIsTheWindow(unittest.TestCase):
    def test_the_number_is_declared_and_it_is_thirty(self):
        self.assertEqual(server.SUPERINTENDENT_LICENCE_WARNING_DAYS, 30)

    def test_thirty_one_days_out_is_ok(self):
        self.assertEqual(_state("2026-10-17")["state"], server.LICENCE_OK)

    def test_thirty_days_out_is_expiring(self):
        self.assertEqual(_state("2026-10-16")["state"], server.LICENCE_EXPIRING)

    def test_it_lapses_today_and_has_not_lapsed(self):
        self.assertEqual(_state("2026-09-16")["state"], server.LICENCE_EXPIRING)

    def test_yesterday_is_expired(self):
        self.assertEqual(_state("2026-09-15")["state"], server.LICENCE_EXPIRED)

    def test_the_window_is_read_from_the_constant(self):
        """A numeric cap disarmed by a neighbouring constant is a gate that
        cannot fail. Drive the boundary FROM the declared number so a change to
        it moves the test with it rather than leaving the test asserting 30
        while the code uses 7."""
        n = server.SUPERINTENDENT_LICENCE_WARNING_DAYS
        edge = (TODAY + datetime.timedelta(days=n)).isoformat()
        past_edge = (TODAY + datetime.timedelta(days=n + 1)).isoformat()
        self.assertEqual(_state(edge)["state"], server.LICENCE_EXPIRING)
        self.assertEqual(_state(past_edge)["state"], server.LICENCE_OK)


class UnknownIsNotOk(unittest.TestCase):
    def test_a_missing_expiry_is_unknown(self):
        self.assertEqual(_state(None)["state"], server.LICENCE_UNKNOWN)

    def test_an_empty_string_is_unknown(self):
        """The form sends "" for a field the admin did not fill. Absent, null
        and "" are one state, as `_same_company_or_403` documents."""
        for blank in ("", "   "):
            self.assertEqual(_state(blank)["state"], server.LICENCE_UNKNOWN)

    def test_a_date_nobody_can_parse_is_UNREADABLE_and_not_a_crash(self):
        """THIS ASSERTED `LICENCE_UNKNOWN` AND THE RULING CHANGED IT.

        Not a stricter version of the same rule — the opposite conclusion about
        what the two facts are. The old docstring called the conflation
        deliberate and for DISPLAY it was sound: neither an absent expiry nor an
        unreadable one is a date anybody can act on.

        WHAT IT COST WAS DISCOVERY, IN PRODUCTION. '07/212029' — '07/21/2029'
        with a slash missing — was saved on a real account and read back as
        `unknown`, which the screen renders as "No DOB registration recorded",
        a sentence about the registration NUMBER, which was recorded. A typo and
        an empty field produced the same state, so nothing anywhere could find
        the row and say somebody had typed something that did not take.

        STILL NOT A CRASH, which is the half of this test that did not change.
        """
        for junk in ("2027", "soon", "12/31/2027", "next year", "0000-00-00",
                     "07/212029"):
            self.assertEqual(_state(junk)["state"], server.LICENCE_UNREADABLE, junk)

    def test_and_it_is_a_different_state_from_an_absent_one(self):
        self.assertNotEqual(server.LICENCE_UNKNOWN, server.LICENCE_UNREADABLE)
        self.assertNotEqual(_state("soon")["state"], _state(None)["state"])

    def test_unknown_carries_no_days_remaining(self):
        """A number here would be read as a countdown to something."""
        self.assertIsNone(_state(None)["days_remaining"])


class TheAnswerCarriesTheDate(unittest.TestCase):
    def test_it_returns_the_date_it_judged(self):
        out = _state("2026-10-01")
        self.assertEqual(out["expires_on"], "2026-10-01")
        self.assertEqual(out["days_remaining"], 15)

    def test_it_takes_today_rather_than_reading_the_clock(self):
        """Every statutory gate in this codebase resolves against a date it was
        handed. A helper that reads datetime.now() inside a branch is one a
        test can only observe, never drive."""
        self.assertIn("today", inspect.signature(
            server.superintendent_licence_state).parameters)


class OnlyASuperintendentHasOne(unittest.TestCase):
    def test_the_response_helper_leaves_everybody_else_alone(self):
        for role in ("cp", "admin", "owner", server.ROLE_PM):
            doc = server._with_licence(
                {"role": role, "dob_registration_expiry": "2026-09-15"})
            self.assertIsNone(doc.get("licence"), role)

    def test_a_superintendent_gets_the_verdict(self):
        doc = server._with_licence({
            "role": server.ROLE_SUPERINTENDENT,
            "dob_registration_expiry": "2000-01-01",
        })
        self.assertEqual(doc["licence"]["state"], server.LICENCE_EXPIRED)

    def test_the_verdict_is_derived_on_read_and_never_stored(self):
        """A stored verdict is only ever the state of the world on the day
        somebody wrote it. A licence that lapsed while nobody opened the screen
        must still read as expired.

        THIS ASSERTION WAS MEASURING THE WRONG THING, and the CS-registration
        work found it. It banned the literal `"licence":
        superintendent_licence_state` ANYWHERE in server.py -- which catches a
        RESPONSE FIELD as readily as a database write, and
        GET /admin/users/{id}/cs-registrations returns exactly that key so the
        screen can show the state. Computing the verdict into a response is the
        thing this test WANTS; computing it into a `$set` is the thing it
        forbids. It now asks about the write.
        """
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        # THE STORED FIELDS ARE THE LICENCE FACTS. The verdict is not one of
        # them, and naming the whole set means a fifth field cannot be added
        # without somebody deciding whether it is a fact or an opinion.
        self.assertEqual(
            set(server.SUPERINTENDENT_LICENCE_FIELDS),
            {"dob_superintendent_number", "dob_registration_expiry",
             "dob_card_r2_key", "dob_card_r2_url"},
        )
        # NO WRITER STAMPS A VERDICT ONTO THE DOCUMENT.
        self.assertNotIn('"$set": {"licence"', src)
        self.assertNotIn('"licence": 1', src)      # nor into a projection

    def test_the_created_user_is_INSERTED_before_the_verdict_is_attached(self):
        """create_admin_user sets `user_dict["licence"]` for the response, and
        `user_dict` is the same object that was handed to insert_one. The
        ordering is what keeps the verdict out of the document: attach it
        before the insert and Mongo stores a dated opinion about a credential.
        """
        import inspect
        code = inspect.getsource(server.create_admin_user)
        self.assertLess(code.index("insert_one(user_dict)"),
                        code.index('user_dict["licence"]'))


class TheListScreenCanBadgeIt(unittest.TestCase):
    """The 30-day warning is only an alert if something shows it. The admin
    Users list is where it is shown, so the expiry has to come back in the SAME
    call that draws the row -- a per-user follow-up request is a badge that
    appears late or not at all, and on a lapsed licence that is the wrong
    direction to fail."""

    def test_the_list_projection_carries_the_licence_fields(self):
        src = inspect.getsource(server.get_admin_users)
        fields = src[src.index("USER_LIST_FIELDS = {"):]
        fields = fields[:fields.index("}")]
        for f in ("dob_superintendent_number", "dob_registration_expiry",
                  "dob_card_r2_url"):
            self.assertIn(f, fields)

    def test_the_list_projection_carries_NO_image_bytes(self):
        """`USER_LIST_FIELDS` exists because an EXCLUSION projection over
        db.users held inline signatures in a blocking in-memory sort and
        returned 500 twice in one day. The card is an R2 object; only its URL
        rides this list."""
        src = inspect.getsource(server.get_admin_users)
        fields = src[src.index("USER_LIST_FIELDS = {"):]
        fields = fields[:fields.index("}")]
        self.assertNotIn("dob_card_image", fields)

    def test_every_row_gets_the_same_derivation_the_detail_screen_gets(self):
        """One helper, so the badge on the list and the panel on the detail
        screen cannot disagree about the same account."""
        self.assertIn("_with_licence", inspect.getsource(server.get_admin_users))


class TheCardGoesToR2(unittest.TestCase):
    def test_the_key_is_a_function_of_the_user_id(self):
        key = server._superintendent_card_r2_key("abc123")
        self.assertIn("abc123", key)
        self.assertTrue(key.startswith("superintendent-cards/"))

    def test_it_is_its_own_prefix(self):
        """Not the worker card prefix and not the object-locked card-audit
        bucket: that one carries 7-year retention, and a working copy rewritten
        on every re-upload must not be created under a retention lock."""
        self.assertNotIn("worker-osha-cards", server._superintendent_card_r2_key("x"))

    def test_no_pointer_is_ever_invented(self):
        """A failed upload records the EVENT and never a key, a URL or an empty
        string -- `""` is a value and reads as a fact about the image."""
        src = inspect.getsource(server._store_superintendent_card)
        self.assertIn("dob_card_upload_failed", src)
        self.assertNotIn('"dob_card_r2_url": ""', src)


if __name__ == "__main__":
    unittest.main()
