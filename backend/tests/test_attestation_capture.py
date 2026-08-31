"""The CP's signature records what was printed above it.

THE ASYMMETRY THIS CLOSES. A worker tapping Affirm at a turnstile produces a
signature event carrying the exact sentence he read, in his language, with a
version. The CP signing a filed logbook -- a document that goes to DOB, to
lenders, and to an OATH hearing -- produced an event whose content_snapshot was
the logbook payload and NOTHING about what the signature block said above his
name. The party whose signature carries statutory weight had the weaker record.

It was not carelessness: when the CP's signature event was written there WAS no
sentence above the signature. All three attestations were added in one week, as
module constants the renderer prints, and nothing fed them into the snapshot
because the snapshot's shape predated them.

THREE THINGS ARE ASSERTED HERE.

1. ONE DEFINITION. The text lives in lib/logbook/attestations.py and server.py
   imports it. Two copies of a sentence are two sentences the moment one is
   edited, and this one is both printed on a compliance document and stored in
   an audit ledger -- the two places a divergence is hardest to notice.

2. THE CLIENT DOES NOT SUPPLY IT. The snapshot arrives from the client; the
   attestation is injected server-side from the log type resolved off the
   DOCUMENT. A snapshot whose attestation the client could choose is evidence
   of nothing.

3. NINE OF TWELVE TYPES PRINT NOTHING, AND THE SNAPSHOT SAYS SO. An absent key
   cannot be told apart from an event nobody captured one for -- which is the
   permanent, unrepairable state of every event written before this existed,
   and is labelled PREDATES_CAPTURE rather than fixed. Writing the key onto a
   stored audit event would be altering the ledger.
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

try:
    from lib.logbook import attestations as A  # noqa: E402
except ImportError:  # pragma: no cover — control runs report a count
    A = None

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")


class OneDefinition(unittest.TestCase):
    def test_the_server_constants_ARE_the_registry(self):
        self.assertEqual(server.PRESHIFT_ATTESTATION,
                         A.ATTESTATIONS["preshift_signin"]["text"])
        self.assertEqual(server.OSHA_LOG_ATTESTATION,
                         A.ATTESTATIONS["osha_log"]["text"])
        self.assertEqual(server.CS_LOG_ATTESTATION,
                         A.ATTESTATIONS["site_superintendent_log"]["text"])

    def test_the_server_holds_no_second_copy_of_the_prose(self):
        """Each constant reads the registry rather than restating the sentence
        -- otherwise editing one leaves the document and the ledger disagreeing
        about what a signer was shown."""
        for line in ("PRESHIFT_ATTESTATION = _ATTESTATIONS",
                     "OSHA_LOG_ATTESTATION = _ATTESTATIONS",
                     "CS_LOG_ATTESTATION = _ATTESTATIONS"):
            self.assertIn(line, SRC)
        self.assertEqual(SRC.count("Each worker named below was present"), 0)
        self.assertEqual(SRC.count("This register lists the certifications"), 0)

    def test_the_import_precedes_the_constants(self):
        """Module-level order: the constants READ the registry at import, so an
        import placed below them raises NameError at boot -- the shape that
        crash-looped production on 2026-08-29."""
        self.assertLess(SRC.index("from lib.logbook.attestations import"),
                        SRC.index("PRESHIFT_ATTESTATION = _ATTESTATIONS"))

    def test_every_registered_version_is_in_HISTORY(self):
        for log_type, entry in A.ATTESTATIONS.items():
            self.assertEqual(
                A.attestation_text(log_type, entry["version"]), entry["text"],
                log_type)

    def test_the_versions_are_dated(self):
        for log_type, entry in A.ATTESTATIONS.items():
            self.assertRegex(entry["version"], r"^\d{4}-\d{2}-\d{2}\.\d+$",
                             log_type)

    def test_an_unknown_version_is_None_not_a_guess(self):
        """A snapshot written by a LATER build naming a version this one does
        not carry is newer, not corrupt."""
        self.assertIsNone(A.attestation_text("osha_log", "2099-01-01.1"))
        self.assertIsNone(A.attestation_text(None, None))


class ThreeRecordedStatesAndOneInferred(unittest.TestCase):
    def test_a_type_with_a_sentence_records_it(self):
        snap = A.attestation_snapshot("preshift_signin")
        self.assertEqual(snap["state"], A.PRESENT)
        self.assertEqual(snap["text"], server.PRESHIFT_ATTESTATION)
        self.assertTrue(snap["version"])

    def test_the_OTHER_NINE_record_that_there_is_nothing(self):
        """Not an omitted key. An absent key cannot be told apart from an event
        nobody captured one for."""
        for log_type in ("hot_work", "crane_operations", "daily_jobsite",
                         "toolbox_talk", "scaffold_maintenance"):
            snap = A.attestation_snapshot(log_type)
            self.assertEqual(snap["state"], A.NONE_ON_DOCUMENT, log_type)
            self.assertIsNone(snap["text"])

    def test_an_unresolved_log_type_is_UNDETERMINED(self):
        for missing in (None, "", "   "):
            self.assertEqual(A.attestation_snapshot(missing)["state"],
                             A.UNDETERMINED)

    def test_the_key_is_NEVER_omitted(self):
        for log_type in ("preshift_signin", "hot_work", None):
            self.assertIn(A.SNAPSHOT_KEY,
                          A.attach_attestation({"x": 1}, log_type))

    def test_the_counts_match_the_registry(self):
        """Three of twelve. If a fourth type gains a sentence this fails and
        gets re-stated rather than drifting."""
        registered = set(A.ATTESTATIONS)
        all_types = set(server.LOGBOOK_TIMING_CLASS)
        self.assertEqual(registered,
                         {"preshift_signin", "osha_log",
                          "site_superintendent_log"})
        self.assertEqual(len(all_types - registered), 10)


class TheClientDoesNotSupplyIt(unittest.TestCase):
    CODE = None

    @classmethod
    def setUpClass(cls):
        cls.CODE = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.record_signature_event))))

    def test_the_log_type_is_resolved_from_the_DOCUMENT(self):
        self.assertIn("db.logbooks.find_one", self.CODE)
        self.assertIn("'log_type': 1", self.CODE)

    def test_the_attestation_is_injected_server_side(self):
        self.assertIn("attach_attestation(data.content_snapshot, _log_type)",
                      self.CODE)
        self.assertIn("content_snapshot=_snapshot", self.CODE)

    def test_the_raw_client_snapshot_is_NOT_stored(self):
        self.assertNotIn("content_snapshot=data.content_snapshot", self.CODE)

    def test_a_client_supplied_attestation_is_OVERWRITTEN(self):
        """Deliberately. The wording is what the signer was SHOWN."""
        out = A.attach_attestation(
            {"attestation": {"state": "present", "text": "I agree to anything"}},
            "osha_log")
        self.assertEqual(out["attestation"]["text"], server.OSHA_LOG_ATTESTATION)

    def test_the_rest_of_the_snapshot_is_preserved(self):
        out = A.attach_attestation({"weather": "clear", "crews": 3}, "osha_log")
        self.assertEqual(out["weather"], "clear")
        self.assertEqual(out["crews"], 3)

    def test_a_failed_lookup_records_UNDETERMINED_not_a_wrong_answer(self):
        """A signature must not be refused because a lookup failed, and it must
        not claim an attestation it could not resolve."""
        self.assertIn("except Exception", self.CODE)
        self.assertEqual(A.attach_attestation({}, None)["attestation"]["state"],
                         A.UNDETERMINED)


class ReadingAStoredEvent(unittest.TestCase):
    def test_a_captured_event_verifies(self):
        ev = {"content_snapshot": A.attach_attestation({}, "osha_log")}
        out = A.attestation_of(ev)
        self.assertEqual(out["state"], A.PRESENT)
        self.assertIs(out["verified"], True)

    def test_altered_wording_does_not_verify(self):
        snap = A.attach_attestation({}, "osha_log")
        snap["attestation"]["text"] = "something else"
        self.assertIs(A.attestation_of({"content_snapshot": snap})["verified"],
                      False)

    def test_a_version_this_build_lacks_is_UNCHECKABLE_not_WRONG(self):
        """None, not False. "This build cannot check it" is a different fact
        from "the text is wrong" -- the distinction the OSHA register draws
        between No findings and Not checked."""
        snap = A.attach_attestation({}, "osha_log")
        snap["attestation"]["version"] = "2099-01-01.1"
        self.assertIsNone(A.attestation_of({"content_snapshot": snap})["verified"])

    def test_an_event_with_no_key_PREDATES_CAPTURE(self):
        for legacy in ({"content_snapshot": {}},
                       {"content_snapshot": {"weather": "clear"}},
                       {}, None, "not a dict"):
            self.assertEqual(A.attestation_of(legacy)["state"],
                             A.PREDATES_CAPTURE)

    def test_that_marker_says_the_absence_is_NOT_EVIDENCE_EITHER_WAY(self):
        """The whole point of labelling rather than backfilling."""
        s = A.attestation_sentence(A.attestation_of({"content_snapshot": {}}))
        self.assertIn("predates attestation capture", s)
        self.assertIn("not evidence", s)

    def test_none_on_document_reads_as_a_fact_about_the_TYPE(self):
        ev = {"content_snapshot": A.attach_attestation({}, "hot_work")}
        s = A.attestation_sentence(A.attestation_of(ev))
        self.assertIn("prints no attestation", s)

    def test_nothing_here_writes(self):
        """Labelling a legacy event, never repairing it: writing the key onto a
        stored audit event would be altering the ledger."""
        for fn in (A.attestation_of, A.attestation_snapshot,
                   A.attach_attestation, A.attestation_sentence):
            code = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))
            for write in ("update_one", "insert_one", "$set", "db."):
                self.assertNotIn(write, code)


class TheDocumentAndTheLedgerAgree(unittest.TestCase):
    """The sentence a signer SEES and the sentence STORED are one string."""

    def test_each_printed_attestation_is_the_registered_one(self):
        for const, key in ((server.PRESHIFT_ATTESTATION, "preshift_signin"),
                           (server.OSHA_LOG_ATTESTATION, "osha_log"),
                           (server.CS_LOG_ATTESTATION,
                            "site_superintendent_log")):
            self.assertEqual(A.attestation_snapshot(key)["text"], const)

    def test_the_rendered_html_carries_the_same_text(self):
        self.assertIn(server.PRESHIFT_ATTESTATION,
                      server.PRESHIFT_ATTESTATION_HTML)
        self.assertIn(server.OSHA_LOG_ATTESTATION,
                      server.OSHA_LOG_ATTESTATION_HTML)
        self.assertIn(server.CS_LOG_ATTESTATION,
                      server.CS_LOG_ATTESTATION_HTML)


if __name__ == "__main__":
    unittest.main()
