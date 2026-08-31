"""One evaluation, two reads: the register and the CP's own screen.

THE GAP THAT MADE READ-TIME EVALUATION INCOMPLETE. The card-number finding is
evaluated at read time and never stored, which is right -- a stored flag keyed
to a card number is orphaned by any later correction to that number. But it was
evaluated at ONE read. The register rendered "Unexpected card format" to an
investor, and `get_worker_certifications` returned the stored document verbatim
to the CP'S OWN SCREEN, where he could actually fix it.

A flag the CP cannot see is a flag he cannot act on. It appeared on the
document he cannot edit and not on the screen where he could.

BOTH READS NOW GO THROUGH card_number_finding. Written once, because two copies
of a rule are two rules -- and this rule already had to be scoped to SST types
after a first version would have flagged every OSHA card on every register.

STILL NOTHING IS WRITTEN. The CP's read COPIES each row before setting the
finding on it, so nothing can mutate the document the request just read and
nothing is persisted. Same posture as the pre-shift affirmation overlay: a read
may describe a record without amending it.
"""

import ast
import asyncio
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

SCREEN = (BACKEND.parent / "frontend" / "app" / "workers"
          / "[id].jsx").read_text(encoding="utf-8")
EN = (BACKEND.parent / "frontend" / "src" / "i18n"
      / "en.js").read_text(encoding="utf-8")

WORKER = "64f0aa11bb22cc33dd44ee55"

BAD = {"type": "SST_SUPERVISOR", "card_number": "Supervisor"}
GOOD = {"type": "SST_FULL", "card_number": "JH447TBBXG"}
OSHA = {"type": "OSHA_30", "card_number": "OSHA30-111"}
FLAGGED = {"type": "SST_SUPERVISOR", "card_number": "Supervisor",
           "needs_review": True, "review_reason": "CLASS_UNVERIFIED"}


def _read(certs):
    """get_worker_certifications, with the auth dependency already resolved."""
    worker = {"_id": WORKER, "name": "Cristian B Rojas", "certifications": certs}
    with patch.object(server, "validate_worker_certifications",
                      lambda *a, **k: {"cleared": True, "blocks": [], "warnings": []}):
        return asyncio.run(server.get_worker_certifications(WORKER, worker))


class TheOneEvaluation(unittest.TestCase):
    def test_a_malformed_sst_row_has_a_finding(self):
        self.assertEqual(server.card_number_finding(BAD), "CARD_NUMBER_FORMAT")

    def test_a_good_one_does_not(self):
        self.assertIsNone(server.card_number_finding(GOOD))

    def test_an_osha_card_is_never_judged_by_it(self):
        self.assertIsNone(server.card_number_finding(OSHA))

    def test_a_stored_flag_outranks_it(self):
        """A claim about the CREDENTIAL outranks a claim about DATA ENTRY, and
        the precedence lives HERE rather than at each call site -- so both
        readers make the same call without either having to remember."""
        self.assertIsNone(server.card_number_finding(FLAGGED))

    def test_it_survives_junk(self):
        for junk in (None, "", 3, [], {}):
            self.assertIsNone(server.card_number_finding(junk))


class BothReadsUseIt(unittest.TestCase):
    def test_the_register_calls_it(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.osha_review_index))))
        self.assertIn("card_number_finding(cert)", code)

    def test_the_cp_screen_read_calls_it(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.get_worker_certifications))))
        self.assertIn("card_number_finding(_c)", code)

    def test_neither_reimplements_the_rule(self):
        """Two copies of a rule are two rules. This one already had to be
        scoped to SST types once."""
        for fn in (server.osha_review_index, server.get_worker_certifications):
            code = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))
            self.assertNotIn("_card_number_shape", code)

    def test_the_two_reads_agree_on_the_same_row(self):
        """The document and the queue must not disagree about whether a row
        has a finding."""
        review, _cards, _workers = server.osha_review_index(
            [{"_id": WORKER, "certifications": [BAD]}])
        on_register = review.get((WORKER, "Supervisor"))
        on_screen = _read([BAD])["certifications"][0].get("review_reason")
        self.assertEqual(on_register, on_screen)
        self.assertEqual(on_register, "CARD_NUMBER_FORMAT")


class TheCPScreenNowSeesIt(unittest.TestCase):
    def test_the_finding_reaches_the_returned_certification(self):
        out = _read([BAD])["certifications"][0]
        self.assertTrue(out["needs_review"])
        self.assertEqual(out["review_reason"], "CARD_NUMBER_FORMAT")

    def test_it_arrives_through_the_keys_every_reader_already_understands(self):
        """The screen's row renderer keys on `needs_review || review_reason`.
        An evaluated finding reaches the CP through the path a stored one
        takes, rather than a second field every reader would have to learn."""
        self.assertIn("c.needs_review || c.review_reason", SCREEN)

    def test_a_clean_row_is_returned_untouched(self):
        out = _read([GOOD])["certifications"][0]
        self.assertNotIn("review_reason", out)
        self.assertFalse(out.get("needs_review"))

    def test_a_stored_flag_is_not_overwritten(self):
        out = _read([FLAGGED])["certifications"][0]
        self.assertEqual(out["review_reason"], "CLASS_UNVERIFIED")

    def test_an_osha_row_is_returned_untouched(self):
        out = _read([OSHA])["certifications"][0]
        self.assertNotIn("review_reason", out)

    def test_every_row_is_returned_none_are_dropped(self):
        certs = _read([BAD, GOOD, OSHA, FLAGGED])["certifications"]
        self.assertEqual(len(certs), 4)

    def test_the_rest_of_the_response_is_unchanged(self):
        out = _read([GOOD])
        self.assertEqual(out["worker_id"], WORKER)
        self.assertEqual(out["worker_name"], "Cristian B Rojas")
        self.assertIn("validation", out)


class NothingIsWritten(unittest.TestCase):
    """The whole safety of the read-time approach, asserted rather than said."""

    def test_the_read_does_not_mutate_the_stored_row(self):
        """It COPIES before setting. If it did not, the document this request
        just read would carry a flag nobody stored -- and a later writer that
        happened to hold that object would persist it."""
        stored = dict(BAD)
        _read([stored])
        self.assertNotIn("review_reason", stored)
        self.assertNotIn("needs_review", stored)

    def test_the_endpoint_writes_to_nothing(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.get_worker_certifications))))
        for write in ("update_one", "insert_one", "update_many", "$set", "$push"):
            self.assertNotIn(write, code)

    def test_the_row_is_copied_explicitly(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.get_worker_certifications))))
        self.assertIn("_c = dict(_c)", code)

    def test_still_no_backfill_exists(self):
        for p in (BACKEND / "scripts").glob("*card_number*"):
            self.fail(f"a card-number backfill exists: {p.name}")


class TheCPCanReadWhatItSays(unittest.TestCase):
    """A code shipped without copy renders as its raw key. This is the third
    surface in two days to need the same reminder."""

    def test_the_screen_maps_the_code(self):
        self.assertIn("CARD_NUMBER_FORMAT:", SCREEN)

    def test_the_i18n_catalogue_maps_it_too(self):
        self.assertIn("reason_CARD_NUMBER_FORMAT:", EN)

    def test_the_copy_is_an_observation_not_a_judgement(self):
        block = SCREEN.split("CARD_NUMBER_FORMAT:")[1].split("\n")[0].lower()
        self.assertIn("does not match the expected format", block)
        for judgement in ("incorrect", "invalid", "wrong", "you entered"):
            self.assertNotIn(judgement, block)

    def test_it_tells_him_what_to_do(self):
        """A finding he cannot act on is the thing this change exists to fix."""
        block = SCREEN.split("CARD_NUMBER_FORMAT:")[1].split("\n")[0].lower()
        self.assertIn("check the card", block)


if __name__ == "__main__":
    unittest.main()
