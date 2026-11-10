"""The model's inspection result is a claim: it is read back from the words.

Owner ruling (2026-11-09): never trust the extracted result without checking
it against the person's own statement (or, for a sign-off, the page's OCR
text). Exactly one result in the words, and the model's: stored. None,
several, or a different one: kept as UNRESOLVED with the words, the claim and
why, and one short question asked. "Failed" must never become "passed".
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import server  # noqa: E402
from lib import inspection_reports as IR  # noqa: E402
from lib import voice_ingest  # noqa: E402
from tests.test_dm_brain import FakeLLM, _Brain, last_tool_results, resp, text, use  # noqa: E402
from tests.test_dm_short_answers import CHAT  # noqa: E402
from tests import test_inspection_reports as TIR  # noqa: E402  (a module: its classes are not re-collected)
from tests.test_whatsapp_dm_assistant import _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx  # noqa: E402

#: Every phrasing of a FAILURE we could find: typed, voice-transcript, Spanish.
FAILED = (
    "plumbing rough failed on 3", "Plumbing rough didn't pass on floor 3", "plumbing rough did not pass on 3",
    "plumbing rough didnt pass on 3", "plumbing rough not passed on 3", "Plumbing rough NOT PASSED floor 3",
    "plumbing rough never passed on 3", "it did not, uh, pass on floor 3", "it didn't um pass on 3",
    "the plumbing rough on three uh it failed", "Hydro was a no-go on 5", "hydro no go floor 5",
    "yeah so the hydro on five, no go", "Inspector rejected the firestopping on 4", "firestopping got rejected on 4",
    "electric rough was disapproved on 2", "red tagged on 3", "red tag on the plumbing rough 3", "NOT APPROVED",
    "plumbing rough wasn't approved on 3", "no pass on 3", "failure on the hydro, floor 5", "flunked the hydro on 5",
    "it was supposed to pass but failed", "the plumbing rough on 3 did not get approved",
    "no pasó la inspección en el piso 3", "falló el hydro en el 5", "la rechazaron en el piso 4",
    "fue rechazada en el piso 4", "no la aprobaron en el 3", "reprobado en el piso 3",
)
PASSED = (
    "Plumbing rough passed on floor 3", "plumbing rough passed on 3 at 588, inspector Ruiz, yesterday", "Passed",
    "No, it passed", "No issues, passed", "passed with no issues", "Approved", "signed off on the plumbing rough 3",
    "got a pass on 3", "Plumbing rough inspection on the third floor it passed",
    "La inspección de plomería pasó en el piso 3", "aprobado", "Si, pasó",
)
PARTIAL = ("plumbing rough partially passed on 3", "partial pass on the hydro, floor 5", "passed partially",
           "pasó parcialmente")
SCHEDULED = ("Hydro is booked for Tuesday floor 5", "hydro scheduled for friday on 5", "está programada para el martes")
NOTHING = (
    "Plumbing rough hasn't passed yet on 3", "todavía no pasó", "the inspector failed to show up for plumbing rough",
    "hydro isn't booked yet", "plumbing rough should pass tomorrow", "hopefully passes", "if it passes we can close up",
    "awaiting approval on the plumbing rough", "didn't fail", "we didn't get the inspector till noon but it passed",
    "plumbing rough on 3",
)
SEVERAL = ("plumbing passed on 3 and hydro failed on 5", "hydro failed on 5, rescheduled for Tuesday")


class ReadingTheWords(unittest.TestCase):

    def test_failures(self):
        for said in FAILED:
            with self.subTest(said):
                self.assertEqual(IR.read_result(said)["results"], ["failed"])

    def test_passes(self):
        for said in PASSED:
            with self.subTest(said):
                self.assertEqual(IR.read_result(said)["results"], ["passed"])

    def test_partial_and_booked(self):
        for said in PARTIAL:
            with self.subTest(said):
                self.assertEqual(IR.read_result(said)["results"], ["partial"])
        for said in SCHEDULED:
            with self.subTest(said):
                self.assertEqual(IR.read_result(said)["results"], ["scheduled"])

    def test_words_that_state_no_result(self):
        for said in NOTHING:
            with self.subTest(said):
                self.assertEqual(IR.read_result(said)["results"], [])

    def test_several_results(self):
        for said in SEVERAL:
            with self.subTest(said):
                self.assertGreater(len(IR.read_result(said)["results"]), 1)

    def test_whole_words_only(self):
        for said in ("we bypassed it", "passenger elevator", "compassion", "unfailing crew", "approvedness"):
            with self.subTest(said):
                self.assertNotIn("passed", IR.read_result(said)["results"])
                self.assertNotIn("failed", IR.read_result(said)["results"])

    def test_why_a_word_was_set_aside(self):
        self.assertIn("not_yet", IR.read_result("hasn't passed yet")["unclear"])
        self.assertIn("no_show", IR.read_result("inspector failed to show")["unclear"])
        self.assertIn("hedged_passed", IR.read_result("should pass")["unclear"])
        self.assertIn("negated_fail", IR.read_result("didn't fail")["unclear"])
        self.assertIn("negation_before_pass", IR.read_result("didn't see him but passed")["unclear"])


class FailedNeverBecomesPassed(unittest.TestCase):

    def test_a_model_that_says_passed_over_a_failure_stores_nothing(self):
        for said in FAILED:
            with self.subTest(said):
                v = IR.validate_statement(said, said, "passed")
                self.assertFalse(v["agree"])
                self.assertIsNone(v["result"])
                self.assertEqual(v["model_result"], "passed")
                self.assertTrue(v["reason"])

    def test_the_whole_sentence_is_read_not_the_part_the_model_copied(self):
        v = IR.validate_statement("plumbing rough did not pass on 3", "pass on 3", "passed")
        self.assertEqual((v["agree"], v["read"]), (False, ["failed"]))
        self.assertEqual(v["span"], "plumbing rough did not pass on 3")

    def test_each_sentence_is_its_own_statement(self):
        own = "Plumbing rough passed on 3. Electric rough failed on 4."
        self.assertTrue(IR.validate_statement(own, "plumbing rough passed on 3", "passed")["agree"])
        self.assertTrue(IR.validate_statement(own, "electric rough failed on 4", "failed")["agree"])
        self.assertFalse(IR.validate_statement(own, "electric rough failed on 4", "passed")["agree"])

    def test_agreement(self):
        for said, claim in [(s, "passed") for s in PASSED] + [(s, "failed") for s in FAILED] + \
                [(s, "partial") for s in PARTIAL] + [(s, "scheduled") for s in SCHEDULED]:
            with self.subTest(said):
                v = IR.validate_statement(said, said, claim)
                self.assertTrue(v["agree"], v)
                self.assertEqual(v["result"], claim)

    def test_none_or_several_is_unresolved_whatever_the_model_says(self):
        for said in NOTHING + SEVERAL:
            for claim in IR.RESULTS:
                with self.subTest(said=said, claim=claim):
                    self.assertFalse(IR.validate_statement(said, said, claim)["agree"])

    def test_a_question_is_a_question_with_or_without_the_mark(self):
        for said in ("did the plumbing rough pass on 3", "Did plumbing rough pass on floor 3?",
                     "was the hydro approved on 5", "¿pasó la plomería en el 3?"):
            with self.subTest(said):
                self.assertTrue(IR.validate_statement(said, said, "passed")["question"])
        self.assertFalse(IR.validate_statement("plumbing rough passed on 3", "passed on 3", "passed")["question"])

    def test_no_claimed_result_is_never_a_result_even_when_the_words_have_one(self):
        for claim in (None, "", "ok i guess", "PASSED!"):
            with self.subTest(claim=claim):
                v = IR.validate_statement("plumbing rough passed on 3", "plumbing rough passed on 3", claim)
                self.assertEqual((v["agree"], v["result"], v["reason"]), (False, None, "no result was claimed for it"))

    def test_no_quote_in_their_words_reads_nothing(self):
        v = IR.validate_statement("plumbing rough on 3", "plumbing rough passed", "passed")
        self.assertEqual((v["span"], v["agree"]), ("", False))


class TheDocument(unittest.TestCase):

    def test_the_quoted_line_is_found_on_the_page(self):
        ocr = "DEPARTMENT OF BUILDINGS\nPLUMBING ROUGH INSPECTION\nFLOOR 3\nRESULT: NOT APPROVED\nINSPECTOR J. RUIZ"
        v = IR.validate_document(ocr, "APPROVED", "passed")
        self.assertEqual((v["agree"], v["read"], v["source"]), (False, ["failed"], "ocr"))
        self.assertEqual(v["span"], "result: not approved")

    def test_a_page_that_agrees(self):
        v = IR.validate_document("PLUMBING ROUGH\nRESULT: APPROVED\nFLOOR 3", "Result: Approved", "passed")
        self.assertEqual((v["agree"], v["result"]), (True, "passed"))

    def test_a_checkbox_form_names_both_and_is_unresolved(self):
        v = IR.validate_document("RESULT: PASS FAIL\nFLOOR 3", "RESULT: PASS", "passed")
        self.assertFalse(v["agree"])
        self.assertIn("more than one result", v["reason"])

    def test_a_quote_not_on_the_page_reads_the_whole_page(self):
        v = IR.validate_document("HYDROSTATIC TEST\nREJECTED\nFLOOR 5", "Passed", "passed")
        self.assertEqual((v["agree"], v["read"]), (False, ["failed"]))

    def test_with_no_ocr_the_models_quote_is_marked_as_such(self):
        v = IR.validate_document("", "FAILED", "passed")
        self.assertEqual((v["agree"], v["source"]), (False, "vision_quote"))
        self.assertEqual(IR.validate_document("", None, "passed")["source"], "none")
        self.assertFalse(IR.validate_document("", None, "passed")["agree"])

    def test_merged_ocr_capitals_are_read(self):
        """RapidOCR on a rendered sign-off returned "RESULT:NOTAPPROVED" (no
        spaces): read as not approved, never as approved."""
        for line, want in (("RESULT:NOTAPPROVED", ["failed"]), ("RESULT:APPROVED", ["passed"]),
                           ("INSPECTIONPASSED", ["passed"]), ("DISAPPROVED", ["failed"]),
                           ("PASSENGERELEVATOR", []), ("RESULT:REJECTED", ["failed"])):
            with self.subTest(line):
                self.assertEqual(IR.read_result(IR.unmerge_ocr(line))["results"], want)
        v = IR.validate_document("PLUMBINGROUGHINSPECTION\nFLOOR3\nRESULT:NOTAPPROVED", "APPROVED", "passed")
        self.assertEqual((v["agree"], v["read"], v["span"]), (False, ["failed"], "result:not approved"))

    def test_ocr_lines(self):
        boxes = [(300, 101, "APPROVED"), (40, 99, "RESULT:"), (40, 50, "PLUMBING ROUGH"), (40, 160, "FLOOR 3", 0.9)]
        self.assertEqual(IR.ocr_lines(boxes), "PLUMBING ROUGH\nRESULT: APPROVED\nFLOOR 3")

    def test_the_audit_keeps_claim_result_and_why(self):
        a = IR.audit(IR.validate_document("RESULT: REJECTED", "REJECTED", "passed"))
        self.assertEqual((a["model_result"], a["validated_result"]), ("passed", None))
        self.assertEqual(a["validation"]["read"], ["failed"])
        self.assertFalse(a["validation"]["agree"])
        self.assertIn("the words say failed, not passed", a["validation"]["reason"])
        self.assertEqual(a["validation"]["source"], "ocr")

    def test_an_unresolved_document_line_asks_one_question(self):
        out = IR.document_unresolved_line("Ada", "588", "Plumbing rough", ["Floor 3"], "the words say failed, not passed")
        self.assertIn("No result recorded: the words say failed, not passed", out)
        self.assertTrue(out.endswith("Did the Plumbing rough on Floor 3 pass, fail, partly pass, or is it booked?"))
        self.assertEqual(out.count("?"), 1)


# ── THROUGH THE REAL PIPELINE ───────────────────────────────────────────────

class AStatement(_Brain):

    def rows(self):
        return list(self.db[IR.COLLECTION].rows)

    def _say(self, body, args):
        seen = {}

        def answer(kw):
            seen["tool"] = last_tool_results(kw)[0]
            return resp(text("ok"))
        with _Ctx(db=self.db) as c:
            self.say(c, body, FakeLLM(resp(use("report_inspection", args)), answer))
        return seen["tool"]

    def _args(self, **over):
        return dict({"job": "588", "inspection": "plumbing rough", "levels": "3", "result": "passed",
                     "quote": "plumbing rough"}, **over)

    def test_a_failure_the_model_called_passed_is_kept_unresolved(self):
        tool = self._say("Plumbing rough didn't pass on floor 3 at 588", self._args())
        (r,) = self.rows()
        self.assertEqual((r["status"], r["result"], r["model_result"], r["validated_result"]),
                         (IR.UNRESOLVED, None, "passed", None))
        self.assertEqual(r["validation"]["read"], ["failed"])
        self.assertEqual(r["quote"], "plumbing rough")
        self.assertEqual(r["levels"], ["FLOOR_3"])
        self.assertEqual(IR.current_state([r]), {})                    # no gate moved
        self.assertIn("UNRESOLVED", tool)
        self.assertIn('"Did the plumbing rough on Floor 3 pass, fail, partly pass, or is it booked?"', tool)

    def test_an_agreed_result_keeps_the_check_too(self):
        self._say("Plumbing rough passed on floor 3 at 588", self._args(quote="plumbing rough passed on floor 3"))
        (r,) = self.rows()
        self.assertEqual((r["status"], r["result"], r["model_result"], r["validated_result"]),
                         (IR.ATTESTED, "passed", "passed", "passed"))
        self.assertTrue(r["validation"]["agree"])

    def test_two_results_in_one_sentence_store_no_result(self):
        tool = self._say("plumbing rough passed on 3 and hydro failed on 5 at 588",
                         self._args(quote="plumbing rough passed on 3"))
        (r,) = self.rows()
        self.assertEqual((r["status"], r["result"]), (IR.UNRESOLVED, None))
        self.assertIn("more than one result", tool)

    def test_a_question_without_a_mark_is_not_recorded(self):
        tool = self._say("did the plumbing rough pass on 3 at 588", self._args(quote="plumbing rough pass on 3"))
        self.assertIn("NOT RECORDED", tool)
        self.assertEqual(self.rows(), [])

    def test_spanish(self):
        self._say("no pasó la plomería en el piso 3 en 588",
                  self._args(inspection="plomería", result="passed", quote="no pasó la plomería en el piso 3"))
        (r,) = self.rows()
        self.assertEqual((r["status"], r["validation"]["read"]), (IR.UNRESOLVED, ["failed"]))


class AVoiceNote(_Brain):

    def test_a_transcript_failure_is_never_stored_as_passed(self):
        said = "yeah the plumbing rough on the third floor uh it didn't pass"

        async def on(ident):
            return True

        async def audio(parsed):
            return b"OggS" + b"\x00" * 3996

        async def ingest(audio_bytes, **kw):
            return voice_ingest.VoiceIngestResult(
                ok=True, english_transcript=said, original_transcript=said, language_detected="english",
                no_speech_prob=0.01, confidence=0.95, duration_sec=4.0, telemetry={})
        args = {"job": "588", "inspection": "plumbing rough", "levels": "3", "result": "passed",
                "quote": "the plumbing rough on the third floor"}
        payload = {"event": "message", "data": {"message": {
            "id": {"id": "v1", "fromMe": False, "_serialized": f"false_{CHAT}_v1"}, "from": CHAT, "body": "",
            "type": "ptt"}}}
        with _Ctx(db=self.db), patch.object(server, "_dm_brain_on", on), \
                patch.object(server, "_dm_brain_client", lambda: FakeLLM(resp(use("report_inspection", args)),
                                                                         resp(text("ok")))), \
                patch.object(server, "download_audio", audio), patch.object(voice_ingest, "process_voice_note", ingest), \
                patch.object(server, "LLM_API_KEY", None):
            _run(server._process_whatsapp_message(payload))
        (r,) = self.db[IR.COLLECTION].rows
        self.assertEqual((r["status"], r["result"], r["source"]), (IR.UNRESOLVED, None, "voice"))


class ASignOff(_Brain):
    rows = TIR.ADocument.rows
    send = TIR.ADocument.send

    def _send(self, ocr_text, said):
        with _Ctx(db=self.db) as c, patch.object(server, "_inspection_doc_ocr", lambda page: ocr_text):
            return self.send(c, "plumbing rough sign off 588", said=said, punch=True)

    def test_the_page_says_rejected_and_the_model_said_passed(self):
        said = json.dumps({"is_signoff": True, "inspection": "Plumbing rough", "levels": "Floor 3", "result": "passed",
                           "quote": "APPROVED"})
        out = self._send("PLUMBING ROUGH\nFLOOR 3\nRESULT: NOT APPROVED", said)
        (r,) = self.rows()
        self.assertEqual((r["status"], r["result"], r["model_result"]), (IR.UNRESOLVED, None, "passed"))
        self.assertEqual(r["validation"]["source"], "ocr")
        self.assertTrue(r["r2_key"])                                     # the file is kept
        self.assertEqual(IR.current_state([r]), {})
        self.assertIn("No result recorded", out[0])
        self.assertIn("pass, fail, partly pass, or is it booked?", out[0])

    def test_a_page_that_agrees_is_on_file_with_its_result(self):
        said = json.dumps({"is_signoff": True, "inspection": "Plumbing rough", "levels": "Floor 3", "result": "passed",
                           "quote": "RESULT: APPROVED"})
        self._send("PLUMBING ROUGH\nFLOOR 3\nRESULT: APPROVED", said)
        (r,) = self.rows()
        self.assertEqual((r["status"], r["result"], r["validated_result"]), (IR.DOCUMENT, "passed", "passed"))


if __name__ == "__main__":
    unittest.main()
