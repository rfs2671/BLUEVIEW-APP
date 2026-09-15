"""A card number typed on a phone is scored wrong because of one capital letter.

THE DEFECT, MEASURED ON PRODUCTION 2026-09-14. Four SST rows, all typed on
2026-09-11 on one project, all the right length, the right character class, and
all scored "unexpected" for one reason only -- the first letter is a capital and
the other nine are not:

    Rzsszstz78   Geovany Baten
    Ckald4crd7   Amaury ayala ontero
    Kp82q7k5hb   Abel Alvarez
    Vg61sfldfg   Marcelino c garcia

That is not a shape a person types. It is the shape a PHONE types. The live gate
is backend/checkin.html, its card field was a plain `<input type="text">`, and a
plain text input defaults to `autocapitalize="sentences"` on iOS and Android --
which capitalises the first letter and nothing else. The census below is the
proof: 4 of 74 SST card numbers in the database are "unexpected" today and "ok"
after one `.upper()`, and all four are that exact shape.

BOTH HALVES OR NEITHER.
  THE INPUT      stops the phone doing it, and shows the worker what is being
                 recorded. It is a COURTESY: a different client -- a cached gate
                 page, a retried submit, a future app -- will not honour it.
  THE SERVER     uppercases at the write boundary so a value that reaches
                 storage is already normalised, and compares case-insensitively
                 so the answer is right regardless of what reached it.

THE TRAP IS NOT WEAKENED, and this is the assertion that proves it. The rule is
`[A-Z0-9]{10}` AND at least one digit, and it exists to catch "Supervisor" -- a
CP who typed the card CLASS into the card NUMBER field, in exactly ten
alphanumeric characters. Case-folding the compare turns "Supervisor" into
"SUPERVISOR", which passes the character class. THE DIGIT REQUIREMENT IS WHAT
CATCHES IT, and test_card_number_shape.py has said so since the rule was
written: "upper casing it does not rescue it". Case was doing a job the digit
rule already does, and it was rejecting real cards to do it.

NOTHING IS BACKFILLED. The four rows above are LEFT AS THEY ARE, deliberately,
and test_the_four_rows_are_not_backfilled below keeps that. The reasons are
measured in the PR: their numbers are frozen into five LOCKED logbooks, one
signature snapshot and four never-overwritten check-in rows, and normalising the
live row alone would make the live record disagree with all ten. It would also
clear nothing -- their review reasons are EXPIRY_UNPARSEABLE and
CLASS_UNVERIFIED, neither of which is about the card number.
"""

import ast
import inspect
import os
import re
import sys
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

GATE = (BACKEND / "checkin.html").read_text(encoding="utf-8")

# The four production rows, verbatim. Named so a reader knows these are not
# invented fixtures.
PRODUCTION_ROWS = (
    ("Rzsszstz78", "Geovany Baten"),
    ("Ckald4crd7", "Amaury ayala ontero"),
    ("Kp82q7k5hb", "Abel Alvarez"),
    ("Vg61sfldfg", "Marcelino c garcia"),
)

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)


def _src(fn):
    return ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))


# ── THE SHAPE ───────────────────────────────────────────────────────────────
class TheShapeStopsCaringAboutCase(unittest.TestCase):

    def test_all_four_production_rows_score_ok(self):
        """THE DEFECT, as data. Each of these is a real card number a real man
        typed on a real phone, and each was called 'unexpected'."""
        for number, worker in PRODUCTION_ROWS:
            self.assertEqual(server._card_number_shape(number), "ok",
                             f"{number} ({worker}) is a real card number")

    def test_the_shape_is_the_phone_shape(self):
        """Stated so the next reader sees WHY these four look alike: one
        capital, nine lower -- autocapitalize="sentences", not a human."""
        for number, _ in PRODUCTION_ROWS:
            self.assertEqual(len(number), 10)
            self.assertTrue(number[0].isupper(), number)
            self.assertTrue(number[1:].islower() or any(c.isdigit()
                                                        for c in number[1:]))
            self.assertFalse(any(c.isupper() for c in number[1:]), number)

    def test_fully_lower_case_is_also_ok(self):
        """A client that honours nothing at all still sends a real card."""
        self.assertEqual(server._card_number_shape("jh447tbbxg"), "ok")
        self.assertEqual(server._card_number_shape("4yu1ry8kkm"), "ok")

    def test_surrounding_whitespace_still_does_not_matter(self):
        self.assertEqual(server._card_number_shape("  rzsszstz78  "), "ok")

    def test_the_upper_case_samples_are_untouched(self):
        for n in ("JH447TBBXG", "4YU1RY8KKM", "1234567890"):
            self.assertEqual(server._card_number_shape(n), "ok", n)

    def test_absent_is_still_missing(self):
        for blank in ("", "   ", None):
            self.assertEqual(server._card_number_shape(blank), "missing")

    def test_wrong_length_is_still_unexpected(self):
        for n in ("jh447tbbx", "jh447tbbxgx", "sst-88213"):
            self.assertEqual(server._card_number_shape(n), "unexpected", n)


class TheSupervisorTrapSurvivesTheCaseFold(unittest.TestCase):
    """THE ONE THING THAT COULD HAVE GONE WRONG HERE, and the reason it did
    not: the rule was always two rules, and only the weaker one is being
    dropped."""

    def test_Supervisor_is_still_caught(self):
        self.assertEqual(server._card_number_shape("Supervisor"), "unexpected")

    def test_and_so_is_every_casing_of_it(self):
        for spelling in ("Supervisor", "SUPERVISOR", "supervisor",
                         "SuPeRvIsOr"):
            self.assertEqual(server._card_number_shape(spelling), "unexpected",
                             spelling)

    def test_the_digit_requirement_is_what_does_it(self):
        """Ten letters, any case, no digit -- refused. If someone ever deletes
        the digit clause, THIS is the test that goes red, not a case test."""
        for letters in ("ABCDEFGHIJ", "abcdefghij", "Abcdefghij"):
            self.assertEqual(server._card_number_shape(letters), "unexpected",
                             letters)

    def test_one_digit_is_enough_to_make_it_a_number(self):
        self.assertEqual(server._card_number_shape("Abcdefghi1"), "ok")


# ── THE NORMALISER ──────────────────────────────────────────────────────────
class OneNormaliserWithOneAddress(unittest.TestCase):
    """Written once, because two copies of a rule are two rules -- the same
    reason card_number_finding and lib/ocr_text.py exist."""

    def test_it_exists(self):
        self.assertTrue(hasattr(server, "normalize_card_number"))

    def test_it_upper_cases_and_strips(self):
        self.assertEqual(server.normalize_card_number("  rzsszstz78 "),
                         "RZSSZSTZ78")

    def test_every_production_row_normalises_to_its_upper_form(self):
        for number, _ in PRODUCTION_ROWS:
            self.assertEqual(server.normalize_card_number(number),
                             number.upper())

    def test_absence_stays_absence(self):
        """None, not "". A gap in the record must not become a value, which is
        the distinction _card_number_shape's three states rest on."""
        for blank in (None, "", "   "):
            self.assertIsNone(server.normalize_card_number(blank))

    def test_it_is_pure(self):
        code = _src(server.normalize_card_number)
        for io_ish in ("db.", "await", "find_one", "update_one"):
            self.assertNotIn(io_ish, code)


# ── THE WRITE BOUNDARIES ────────────────────────────────────────────────────
class TheCheckInPathNormalisesOnWrite(unittest.TestCase):
    """register_and_checkin is the gate's endpoint. One normalisation there
    reaches the worker document, the certification row AND the frozen
    sst_card_number on the check-in, because all three read this one name."""

    def setUp(self):
        self.code = _src(server.register_and_checkin)

    def test_the_arriving_number_is_normalised(self):
        self.assertIn("normalize_card_number", self.code)

    def test_the_nullish_cleaning_runs_FIRST(self):
        """norm_ocr_str first (so "N/A" becomes None), then the case rule.
        Reversing them would upper-case the string "n/a" into "N/A" and hand a
        nullish token to a reader that no longer recognises it."""
        nullish = self.code.index("norm_ocr_str(data.get('osha_number'))")
        cased = self.code.index("normalize_card_number(osha_number)")
        self.assertLess(nullish, cased,
                        "the case rule runs before the nullish rule")

    def test_the_nullish_cleaning_is_still_a_PLAIN_assignment(self):
        """It must stay `osha_number = norm_ocr_str(...)` and not be nested
        inside the case call. test_osha_ocr_null_boundary walks this
        function's AST for exactly that assignment shape, and nesting it
        silently disarms that guard -- which is how a card number of "N/A"
        would reach the register again."""
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(server.register_and_checkin)))
        normalised = {
            t.id
            for node in ast.walk(tree) if isinstance(node, ast.Assign)
            if isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "norm_ocr_str"
            for t in node.targets if isinstance(t, ast.Name)
        }
        self.assertIn("osha_number", normalised)


class TheAdminEntryNormalisesBeforeItJudges(unittest.TestCase):
    """POST /workers/{id}/certifications. The order matters twice: normalise
    before the shape gate, or a lowercase card is refused from a screen where
    the admin is holding the card; and normalise before the $push, or the row
    is stored in whatever case was typed."""

    def setUp(self):
        self.code = _src(server.add_worker_certification)

    def test_it_normalises(self):
        self.assertIn("normalize_card_number", self.code)

    def test_it_normalises_before_the_shape_gate(self):
        self.assertLess(self.code.index("normalize_card_number"),
                        self.code.index("_card_number_shape"),
                        "a lowercase card is judged before it is normalised")

    def test_it_normalises_before_the_push(self):
        self.assertLess(self.code.index("normalize_card_number"),
                        self.code.index("'$push'"),
                        "the row is stored before it is normalised")

    def test_the_gate_itself_is_untouched(self):
        """This change makes the gate accept a real card. It does not remove
        the gate, nor widen it past case."""
        self.assertIn("RECOGNIZED_SST_TYPES", self.code)
        self.assertIn("== 'unexpected'", self.code)
        self.assertIn("'code': 'CARD_NUMBER_FORMAT'", self.code)


class TheWorkerEditNormalisesBothFields(unittest.TestCase):
    """PUT /workers/{id}. The easiest boundary to miss and the likeliest to be
    used: its allowlist admits `osha_number` AND a whole `certifications`
    array, and it is the screen an admin uses to CORRECT a card number."""

    def setUp(self):
        self.code = _src(server.update_worker)

    def test_it_normalises(self):
        self.assertIn("normalize_card_number", self.code)

    def test_it_normalises_before_the_set(self):
        self.assertLess(self.code.index("normalize_card_number"),
                        self.code.index("'$set'"),
                        "the edit is stored before it is normalised")

    def test_both_fields_are_reached(self):
        """osha_number is the worker-level identifier; card_number is on every
        row of the certifications array. Normalising one and not the other is
        how the two disagree on the same document."""
        i = self.code.index("ALLOWED_WORKER_FIELDS")
        tail = self.code[i:]
        self.assertIn("osha_number", tail)
        self.assertIn("card_number", tail)

    def test_the_allowlist_is_not_widened(self):
        """This change normalises what the allowlist already admitted. It does
        not admit anything new -- trade and company are still out, for the
        reason written above it."""
        for forbidden in ("'trade'", "'company'", "'company_id'"):
            self.assertNotIn(forbidden, self.code.split("update_data")[0])


class TheCertificationBuilderMintsUpperCase(unittest.TestCase):
    """build_worker_certifications is the function that CREATES a card_number.
    It is pure, so it can be asserted on directly rather than through source."""

    def _build(self, osha_number, existing=None, od=None):
        certs, _not_sst = server.build_worker_certifications(
            existing or [],
            od if od is not None else {"card_type": "SST", "name": "A Worker",
                                       "expiration": "06/01/2029"},
            osha_number, None, NOW)
        return certs

    def test_a_lower_case_scan_is_stored_upper_case(self):
        certs = self._build("rzsszstz78")
        self.assertEqual(len(certs), 1)
        self.assertEqual(certs[0]["card_number"], "RZSSZSTZ78")

    def test_the_phone_shape_is_stored_upper_case(self):
        for number, worker in PRODUCTION_ROWS:
            certs = self._build(number)
            self.assertEqual(certs[0]["card_number"], number.upper(), worker)

    def test_an_osha_row_is_normalised_too(self):
        certs = self._build("abc1234567",
                            od={"card_type": "OSHA", "name": "A Worker",
                                "card_class": "30"})
        self.assertEqual(certs[0]["card_number"], "ABC1234567")

    def test_no_number_still_stores_none_not_empty_string(self):
        certs = self._build(None)
        self.assertIsNone(certs[0]["card_number"])

    def test_a_rescan_matches_a_stored_row_of_DIFFERENT_CASE(self):
        """THE COMPARE SITE, and the reason it must fold. A worker whose row
        was stored mixed-case before this shipped rescans his card; the scan
        now normalises to upper. If the match is case-sensitive the two are
        different cards, and the row he already has is not the row that is
        updated."""
        existing = [{"type": "SST_FULL", "card_number": "Rzsszstz78",
                     "verified": False, "needs_review": True,
                     "expiration_date": None}]
        certs = self._build("RZSSZSTZ78", existing=existing)
        self.assertEqual(len(certs), 1,
                         "a second row was created for the same card")

    def test_a_VERIFIED_row_of_different_case_is_still_never_touched(self):
        """Folding the compare must not become a way past the verified rule --
        it makes MORE rows match, so the rule protecting them matters more."""
        existing = [{"type": "SST_FULL", "card_number": "Rzsszstz78",
                     "verified": True, "needs_review": False,
                     "expiration_date": None}]
        certs = self._build("RZSSZSTZ78", existing=existing)
        self.assertEqual(len(certs), 1)
        self.assertTrue(certs[0]["verified"])
        self.assertIsNone(certs[0]["expiration_date"],
                          "a re-scan modified an admin-confirmed row")


# ── THE REGISTER JOIN ───────────────────────────────────────────────────────
class TheRegisterJoinDoesNotCareAboutCase(unittest.TestCase):
    """osha_review_index keys on the LIVE card number; osha_review_cell looks
    up with the FILED one. Normalising the live side is precisely what makes
    those two disagree, and the codebase already names the consequence: "A row
    whose card number matches NO live cert was not checked, whatever it says" --
    the row prints CLEAN, which is the dangerous direction.

    A FILED DOCUMENT IS NOT REWRITTEN, so the filed side keeps its mixed case
    forever. The join is what has to fold."""

    WID = "64f0aa11bb22cc33dd44ee55"

    def _cell(self, certs, entry):
        review, cards, workers = server.osha_review_index(
            [{"_id": self.WID, "certifications": certs}])
        return server.osha_review_cell(entry, review, cards, workers)

    def test_a_flag_reaches_a_filed_row_of_different_case(self):
        out = self._cell(
            [{"type": "SST_UNSPECIFIED", "card_number": "RZSSZSTZ78",
              "needs_review": True, "review_reason": "CLASS_UNVERIFIED"}],
            {"worker_id": self.WID, "card_number": "Rzsszstz78"})
        self.assertIn("Class unverified", out)
        self.assertNotIn("Not checked", out)

    def test_a_clean_row_of_different_case_reads_as_checked(self):
        out = self._cell(
            [{"type": "SST_UNSPECIFIED", "card_number": "RZSSZSTZ78",
              "needs_review": False}],
            {"worker_id": self.WID, "card_number": "Rzsszstz78"})
        self.assertIn("No findings", out)

    def test_a_row_matching_nothing_still_says_not_checked(self):
        """The fold must not turn a genuine miss into a false clean."""
        out = self._cell(
            [{"type": "SST_UNSPECIFIED", "card_number": "RZSSZSTZ78",
              "needs_review": False}],
            {"worker_id": self.WID, "card_number": "9999999999"})
        self.assertIn("Not checked", out)

    def test_a_no_number_row_still_keys_on_the_empty_string(self):
        out = self._cell(
            [{"type": "SST_UNSPECIFIED", "card_number": "",
              "needs_review": True, "review_reason": "CLASS_UNVERIFIED"}],
            {"worker_id": self.WID, "card_number": ""})
        self.assertIn("Class unverified", out)


# ── THE GATE'S INPUT ────────────────────────────────────────────────────────
class TheGateStopsThePhoneDoingIt(unittest.TestCase):
    """backend/checkin.html, the SERVER-RENDERED gate. It ships with the
    BACKEND deploy, not by EAS OTA -- so this half reaches a worker's phone
    when the backend deploys, and the server half above is what protects every
    check-in until it does."""

    def setUp(self):
        m = re.search(r"<input[^>]*id=\"regCardNumber\"[^>]*>", GATE)
        self.assertIsNotNone(m, "the card number input is gone")
        self.tag = m.group(0)

    def test_it_asks_the_keyboard_for_capitals(self):
        """The whole defect in one missing attribute. Without it a plain text
        input is autocapitalize="sentences" on iOS and Android."""
        self.assertIn('autocapitalize="characters"', self.tag)

    def test_it_turns_off_autocorrect_and_spellcheck(self):
        """A card number is not a word. Autocorrect on a ten-character
        alphanumeric string is a second way to get a wrong one."""
        self.assertIn('autocorrect="off"', self.tag)
        self.assertIn('spellcheck="false"', self.tag)

    def test_the_worker_can_SEE_what_is_being_recorded(self):
        """An attribute the keyboard may ignore is not enough: the value on
        screen has to read the way the record will."""
        self.assertRegex(
            GATE, r"#regCardNumber\s*\{[^}]*text-transform:\s*uppercase")

    def test_the_placeholder_is_not_shouted(self):
        """text-transform hits the placeholder too. "CARD NUMBER" in a field a
        worker is being asked to fill is a different tone, and not the one the
        rest of this page uses."""
        self.assertRegex(
            GATE,
            r"#regCardNumber::placeholder\s*\{[^}]*text-transform:\s*none")

    def test_the_field_is_still_read_the_same_way(self):
        """The client change is presentation. The value still arrives as typed
        and the server still owns the normalisation -- this asserts nobody
        replaced the server rule with a client one."""
        self.assertIn("document.getElementById('regCardNumber').value.trim()",
                      GATE)


# ── THE RULING THAT DID NOT CHANGE ──────────────────────────────────────────
class NothingIsBackfilled(unittest.TestCase):
    """Carried forward from test_card_number_shape.py, restated here because
    THIS is the change that would have tempted someone to run one."""

    def test_the_four_rows_are_not_backfilled(self):
        scripts = BACKEND / "scripts"
        for p in scripts.glob("*card_number*"):
            self.fail(f"a card-number backfill exists: {p.name}")

    def test_the_index_still_writes_nothing(self):
        code = _src(server.osha_review_index)
        for write in ("update_one", "insert_one", "update_many", "$set",
                      "save"):
            self.assertNotIn(write, code)


if __name__ == "__main__":
    unittest.main()
