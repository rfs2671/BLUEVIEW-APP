"""A logbook may not be signed through the public signature endpoint.

THE AUTHENTICATED ENDPOINT INJECTS THE ATTESTATION; THIS ONE CANNOT.
`POST /signature-events` resolves the log type off the document and stores the
sentence printed above the signature, so a signer's record says what they were
shown. `POST /signature-events/public` takes `content_snapshot` from the request
body and stores it verbatim -- correct for its callers today, which are the NFC
gate paths, where the affirmation writes its own event with its own server-held
wording.

THE FAILURE MODE IS SILENCE, WHICH IS WHY THIS REFUSES RATHER THAN WARNS. A
logbook signed here would write cleanly: no error, a computed hash, a ledger
that looks complete -- and a snapshot with no attestation key, which
`attestation_of` reads as PREDATES_CAPTURE. That state is reserved for events
written BEFORE capture existed, so a 2027 signature would be indistinguishable
from a 2026 one, and the marker built to be honest about old records would be
quietly lying about new ones.

THE FULL FIX IS DELIBERATELY NOT BUILT. Injecting here would mean a public,
unauthenticated endpoint reading db.logbooks on every gate check-in to answer a
question nothing currently asks. The guard costs nothing because nothing
legitimate sends a logbook here.

THE FOUR SCENARIOS ARE NAMED IN THIS FILE ON PURPOSE. Anyone relaxing the guard
has to read what it was protecting against, rather than deleting a one-line
check that looks like it forbids something harmless.
"""

import ast
import asyncio
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib.logbook import attestations as A  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")

BODY = {
    "document_type": "logbook",
    "document_id": "lb1",
    "event_type": "cp_sign",
    "signer_name": "M Rivera",
    "signature_data": {"data": "x"},
    "content_snapshot": {"weather": "clear"},
}


def _request():
    r = MagicMock()
    r.client.host = "203.0.113.7"
    return r


def _post(body):
    return asyncio.run(server.record_public_signature_event(body, _request()))


class ALogbookIsRefused(unittest.TestCase):
    def test_it_refuses(self):
        with self.assertRaises(server.HTTPException) as cm:
            _post(dict(BODY))
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail["code"],
                         "LOGBOOK_SIGNATURE_REQUIRES_AUTH")

    def test_however_it_is_spelled(self):
        """A guard that a different case defeats is not a guard."""
        for spelling in ("logbook", "LOGBOOK", "Logbook", "  logbook  "):
            with self.assertRaises(server.HTTPException, msg=spelling):
                _post(dict(BODY, document_type=spelling))

    def test_it_refuses_BEFORE_writing_anything(self):
        """The whole point: nothing may reach the ledger. The check sits above
        create_signature_event in the function body."""
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.record_public_signature_event))))
        self.assertLess(code.index("LOGBOOK_SIGNATURE_REQUIRES_AUTH"),
                        code.index("create_signature_event"))

    def test_the_gate_paths_are_untouched(self):
        """It forbids ONE document_type. The affirmation and every other public
        caller must still work, or the guard has broken the thing it protects."""
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.record_public_signature_event))))
        self.assertIn("== 'logbook'", code)
        for allowed in ("preshift_signature_affirmation", "worker_enrollment",
                        "checkin", "toolbox_talk"):
            self.assertNotIn(f"'{allowed}'", code)


class TheRefusalNamesWHY(unittest.TestCase):
    """Its reader is a developer in 2027, not a CP on a phone."""

    REASON = None

    @classmethod
    def setUpClass(cls):
        try:
            _post(dict(BODY))
        except server.HTTPException as e:
            cls.REASON = e.detail.get("reason", "")

    def test_it_carries_prose_at_all(self):
        self.assertTrue(self.REASON and len(self.REASON) > 120)

    def test_it_names_the_endpoint_to_use_instead(self):
        self.assertIn("/api/signature-events", self.REASON)

    def test_it_says_what_that_endpoint_does_that_this_one_cannot(self):
        self.assertIn("resolves the log type", self.REASON)
        self.assertIn("attestation", self.REASON)

    def test_it_names_the_consequence_not_merely_the_rule(self):
        """"Indistinguishable from an event written before capture existed" is
        the fact that makes this worth refusing."""
        self.assertIn("indistinguishable", self.REASON)

    def test_it_points_at_where_to_read_more(self):
        self.assertIn("attestations.py", self.REASON)
        self.assertIn("followups", self.REASON)

    def test_prose_here_is_a_DEPARTURE_from_the_gateCopy_rule(self):
        """The server normally names a condition and the client owns the
        wording, because a CP must not read the server's English. This refusal
        has no CP and no screen, so the departure is deliberate and is stated
        in the code beside it."""
        block = SRC.split("LOGBOOK_SIGNATURE_REQUIRES_AUTH")[0][-3000:]
        self.assertIn("gateCopy", block)
        self.assertIn("no CP and no screen", block)


class TheFourScenariosAreNamedWhereTheGuardIs(unittest.TestCase):
    """ANYONE RELAXING THIS HAS TO READ WHAT IT WAS PROTECTING AGAINST.

    A one-line check forbidding a document_type looks harmless to delete. These
    assertions make the reasons impossible to miss: they live beside the guard
    in server.py, and this test fails if they are removed.
    """

    BLOCK = None

    @classmethod
    def setUpClass(cls):
        i = SRC.index("A LOGBOOK MAY NOT BE SIGNED THROUGH THIS ENDPOINT")
        j = SRC.index("LOGBOOK_SIGNATURE_REQUIRES_AUTH", i)
        cls.BLOCK = SRC[i:j]

    def test_1_a_worker_signing_the_preshift_SHEET(self):
        """Rather than affirming a stored stroke. That signature would be a
        public-endpoint event on an attested document."""
        self.assertIn("pre-shift SHEET", self.BLOCK)

    def test_2_a_site_device_flow_pointed_here_because_it_needs_no_auth(self):
        self.assertIn("site-device flow", self.BLOCK)
        self.assertIn("needs no auth", self.BLOCK)

    def test_3_a_FOURTH_log_type_gaining_an_attestation(self):
        """Three of twelve carry one today, and that count is asserted
        elsewhere precisely so a fourth is noticed."""
        self.assertIn("fourth log type", self.BLOCK)
        self.assertEqual(len(A.ATTESTATIONS), 3)

    def test_4_the_superintendent_logs_alternate_signer_work(self):
        """Item 8's competent person and item 9's incoming CS each need a
        signature from someone who is not the document's author."""
        self.assertIn("alternate-signer", self.BLOCK)
        self.assertIn("competent person", self.BLOCK)
        self.assertIn("incoming CS", self.BLOCK)

    def test_the_silence_is_named_as_the_reason_to_REFUSE(self):
        self.assertIn("FAILURE MODE IS SILENCE", self.BLOCK)
        self.assertIn("PREDATES_CAPTURE", self.BLOCK)

    def test_and_why_the_full_fix_is_NOT_built(self):
        """So the next reader does not "finish the job" by adding a
        db.logbooks read to a public unauthenticated endpoint."""
        self.assertIn("DELIBERATELY NOT BUILT", self.BLOCK)
        self.assertIn("db.logbooks on every gate", self.BLOCK)


class TheAuthenticatedPathStillDoesTheRealThing(unittest.TestCase):
    def test_it_injects_rather_than_refusing(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.record_signature_event))))
        self.assertIn("attach_attestation", code)
        self.assertNotIn("LOGBOOK_SIGNATURE_REQUIRES_AUTH", code)


if __name__ == "__main__":
    unittest.main()
