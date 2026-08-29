"""An SST card number is refused at the write and observed at the read.

THE ROW THIS EXISTS FOR holds the word "Supervisor" where a card number belongs
-- a CP typed the card CLASS into the card NUMBER field.

AND "Supervisor" IS EXACTLY TEN ALPHANUMERIC CHARACTERS. The first rule
proposed for this was "10 alphanumeric", and it passes the very value it was
written to catch. What separates it from the two real numbers on the register
is CASE and DIGITS:

    JH447TBBXG    len 10, alphanumeric, upper case, contains digits
    4YU1RY8KKM    len 10, alphanumeric, upper case, contains digits
    Supervisor    len 10, alphanumeric, MIXED case, NO digits

So the rule is [A-Z0-9]{10} AND at least one digit.

THE RULE RESTS ON TWO PRODUCTION SAMPLES. An all-letter SST number has not been
proven impossible, only unobserved: ten uppercase letters with no digit would
fail this and might be a real card. That single uncertainty is why the rule
behaves differently at each end --

    WRITE   refuses, before the $push. The person who typed it is present and
            can look at the card in their hand, so a refusal costs one
            correction.
    READ    observes, and writes NOTHING. The row is historical, nobody is
            there to ask, and a rule this young must not overwrite a record.

NOTHING IS BACKFILLED, in either direction. A backfill would write onto a
worker record to describe a defect in it, and would re-create the hazard the
Review column closed yesterday: a stored flag keyed to a card number, orphaned
by any later correction. Evaluating at read time applies to every row the
instant it ships and needs no un-backfill if the rule proves too tight.
"""

import ast
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")
SCREEN = (BACKEND.parent / "frontend" / "app" / "workers"
          / "[id].jsx").read_text(encoding="utf-8")

WORKER = "64f0aa11bb22cc33dd44ee55"

# The two real numbers from the 2026-08-28 register.
REAL = ("JH447TBBXG", "4YU1RY8KKM")


class TheTenCharacterTrap(unittest.TestCase):
    """The finding, asserted with the value that produced it."""

    def test_Supervisor_is_exactly_ten_alphanumeric_characters(self):
        """Stated as a fact of the data, so the next person to propose a
        length-only rule sees why it fails before writing it."""
        self.assertEqual(len("Supervisor"), 10)
        self.assertTrue("Supervisor".isalnum())

    def test_and_it_is_still_caught(self):
        self.assertEqual(server._card_number_shape("Supervisor"), "unexpected")

    def test_upper_casing_it_does_not_rescue_it(self):
        """SUPERVISOR passes [A-Z0-9]{10}. The digit requirement is what
        catches it, and this is the assertion that keeps that requirement."""
        self.assertEqual(server._card_number_shape("SUPERVISOR"), "unexpected")
        self.assertEqual(server._card_number_shape("ABCDEFGHIJ"), "unexpected")


class TheRealNumbersPass(unittest.TestCase):
    def test_both_production_samples_are_ok(self):
        for n in REAL:
            self.assertEqual(server._card_number_shape(n), "ok", n)

    def test_an_all_digit_number_is_ok(self):
        """Not observed, but nothing about the rule excludes it and inventing
        an exclusion would be a second guess."""
        self.assertEqual(server._card_number_shape("1234567890"), "ok")


class ThreeStatesBecauseThereAreThree(unittest.TestCase):
    def test_absent_is_missing_not_unexpected(self):
        """A GAP IN THE RECORD, not a false value. Only the second deceives a
        reader, and only the second is surfaced."""
        for blank in ("", "   ", None):
            self.assertEqual(server._card_number_shape(blank), "missing")

    def test_wrong_length_is_unexpected(self):
        for n in ("JH447TBBX", "JH447TBBXGX", "SST-88213"):
            self.assertEqual(server._card_number_shape(n), "unexpected", n)

    def test_lower_case_is_unexpected(self):
        self.assertEqual(server._card_number_shape("jh447tbbxg"), "unexpected")

    def test_it_is_pure_and_takes_no_database(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server._card_number_shape))))
        for io_ish in ("db.", "await", "find_one", "update_one"):
            self.assertNotIn(io_ish, code)


class TheWriteRefusesBeforeThePush(unittest.TestCase):
    """The ruling, and the reason it is a ruling: validation already ran on
    this endpoint -- AFTER the write, on the row it had just created -- and its
    result was returned to the caller and never acted on."""

    CODE = None

    @classmethod
    def setUpClass(cls):
        cls.CODE = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.add_worker_certification))))

    def test_the_check_runs_before_the_push(self):
        self.assertIn("_card_number_shape", self.CODE)
        self.assertLess(self.CODE.index("_card_number_shape"),
                        self.CODE.index("'$push'"),
                        "the row is written before it is checked")

    def test_it_raises_a_machine_code_not_prose(self):
        """The server names the condition; the client owns the wording."""
        self.assertIn("'code': 'CARD_NUMBER_FORMAT'", self.CODE)

    def test_it_refuses_only_SST_rows(self):
        """An OSHA card number has a different shape entirely; refusing one
        would block a legitimate entry the rule says nothing about."""
        self.assertIn("RECOGNIZED_SST_TYPES", self.CODE)

    def test_it_refuses_only_the_unexpected_shape(self):
        """A missing number is a gap, not a false value, and is not refused:
        the register already states its absence twice."""
        self.assertIn("== 'unexpected'", self.CODE)
        self.assertNotIn("== 'missing'", self.CODE)

    def test_the_post_write_validation_call_is_untouched(self):
        """It still runs and still reports. This adds a gate; it does not
        remove the report that was doing the gate's job badly."""
        self.assertIn("validate_worker_certifications", self.CODE)


class TheReadObservesAndWritesNothing(unittest.TestCase):
    CODE = None

    @classmethod
    def setUpClass(cls):
        cls.CODE = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.osha_review_index))))

    def test_the_index_flags_an_unexpected_number(self):
        self.assertIn("CARD_NUMBER_FORMAT", self.CODE)

    def test_it_writes_nothing_at_all(self):
        for write in ("update_one", "insert_one", "update_many", "$set", "save"):
            self.assertNotIn(write, self.CODE)

    def test_no_backfill_script_was_added(self):
        """Neither a backfill NOR an un-backfill. The whole point of read-time
        evaluation is that a rule this young leaves no residue to undo."""
        scripts = (BACKEND / "scripts")
        for p in scripts.glob("*card_number*"):
            self.fail(f"a card-number backfill exists: {p.name}")

    def _index(self, certs):
        return server.osha_review_index([{"_id": WORKER, "certifications": certs}])

    def test_a_malformed_row_is_surfaced(self):
        review, _cards, _workers, _cls = self._index(
            [{"type": "SST_FULL", "card_number": "Supervisor",
              "needs_review": False}])
        self.assertEqual(review[(WORKER, "Supervisor")], "CARD_NUMBER_FORMAT")

    def test_a_good_row_is_not(self):
        review, _c, _w, _cl = self._index(
            [{"type": "SST_FULL", "card_number": "JH447TBBXG",
              "needs_review": False}])
        self.assertEqual(review, {})

    def test_an_OSHA_CARD_IS_NEVER_JUDGED_BY_THIS_RULE(self):
        """THE BUG THE FULL SUITE CAUGHT, one commit after the ratchet lesson
        it repeats. The shape is an SST card's shape; an OSHA 10 or 30 carries
        a completely different number, and running this rule over them would
        flag EVERY OSHA row on EVERY register -- a check that cries wolf until
        its baseline is padded and it means nothing.

        An existing fixture holding "OSHA30-111" is what failed."""
        for osha in ("OSHA30-111", "OSHA-10-2291", "12345"):
            review, _c, _w, _cl = self._index(
                [{"type": "OSHA_30", "card_number": osha,
                  "needs_review": False}])
            self.assertEqual(review, {}, osha)

    def test_nor_is_any_other_certification_type(self):
        for other in ("Forklift", "Scaffold", "Flagman"):
            review, _c, _w, _cl = self._index(
                [{"type": other, "card_number": "not-a-card",
                  "needs_review": False}])
            self.assertEqual(review, {}, other)

    def test_a_row_with_no_number_is_not_flagged(self):
        """It is already stated twice on the document: an em dash in Card #,
        and "Not checked" in Review, because the credential join cannot happen
        without a number. A third statement of one fact adds nothing, and
        flagging every blank floods a queue whose value is being scarce."""
        review, _c, _w, _cl = self._index(
            [{"type": "SST_FULL", "card_number": "", "needs_review": False}])
        self.assertEqual(review, {})


class ThePrecedenceRule(unittest.TestCase):
    """A claim about the CREDENTIAL outranks a claim about DATA ENTRY."""

    def _cell(self, certs, entry):
        review, cards, workers, _cls = server.osha_review_index(
            [{"_id": WORKER, "certifications": certs}])
        return server.osha_review_cell(entry, review, cards, workers)

    def test_the_class_flag_wins_when_a_row_has_both(self):
        out = self._cell(
            [{"type": "SST_SUPERVISOR", "card_number": "Supervisor",
              "needs_review": True, "review_reason": "CLASS_UNVERIFIED"}],
            {"worker_id": WORKER, "card_number": "Supervisor"})
        self.assertIn("Class unverified", out)
        self.assertNotIn("Unexpected card format", out)

    def test_the_format_flag_shows_when_it_is_the_only_one(self):
        out = self._cell(
            [{"type": "SST_SUPERVISOR", "card_number": "Supervisor",
              "needs_review": False}],
            {"worker_id": WORKER, "card_number": "Supervisor"})
        self.assertIn("Unexpected card format", out)

    def test_the_label_is_an_observation_not_a_judgement(self):
        """The register cannot make a claim about what the CP meant. It states
        the system's expectation and that this value differs from it."""
        text = server.OSHA_REVIEW_LABELS["CARD_NUMBER_FORMAT"]
        self.assertEqual(text, "Unexpected card format")
        for judgement in ("incorrect", "invalid", "wrong", "error", "bad",
                          "not recognised", "not recognized"):
            self.assertNotIn(judgement, text.lower())


class TheClientOwnsTheWording(unittest.TestCase):
    """A CODE SHIPPED WITHOUT COPY is the defect #285 shipped and #286 had to
    come back for. The branch lands in the same change as the refusal."""

    def test_the_screen_reads_the_code(self):
        self.assertIn("CARD_NUMBER_FORMAT", SCREEN)

    def test_it_shows_the_expected_shape_rather_than_blaming_the_typist(self):
        self.assertIn("10 letters and numbers", SCREEN)
        self.assertIn("JH447TBBXG", SCREEN)

    def test_the_generic_toast_is_still_there_for_everything_else(self):
        self.assertIn("Could not save certification", SCREEN)

    def test_no_english_from_the_server_is_rendered(self):
        """The server sends {"code": ...} and no prose for this condition."""
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.add_worker_certification))))
        i = code.index("CARD_NUMBER_FORMAT")
        self.assertNotIn("detail='", code[max(0, i - 300):i + 200])


if __name__ == "__main__":
    unittest.main()
