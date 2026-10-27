"""lib/dm_answer_eval + eval/boyland-dm-2026-10-27.json: the owner's Oct 27
588 Boyland DM questions, scored on the answer he got.

The rule this exists for: a case whose right answer is not known yet (the
A-302.00 detail 4 quote) is FAILING-PENDING -- reported, never a pass -- and
any forbidden phrase fails it outright, curly apostrophe or not.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

import dm_answer_eval as runner  # noqa: E402
from lib import dm_answer_eval as de  # noqa: E402

SUITE = str(_BACKEND / "eval" / "boyland-dm-2026-10-27.json")

GOOD_FOAM = ("Your 5th floor is the Mezzanine (A-104.00), so its ceiling is the roof assembly. "
             "A-302.00 detail 4, ROOF ASSEMBLY DETAIL, shows the insulation.")


def _case(cid):
    return {c["id"]: c for c in de.load_suite(SUITE)["cases"]}[cid]


class TheSuite(unittest.TestCase):

    def test_it_loads_and_holds_every_question_of_the_day(self):
        ids = [c["id"] for c in de.load_suite(SUITE)["cases"]]
        self.assertEqual(ids, ["spray-foam-5th-floor-ceiling", "roof-details", "kitchen-soffits",
                               "en-001-en-002", "what-file-is-it-on", "send-me-the-pdf"])

    def test_the_spray_foam_quote_is_unknown_and_says_how_to_find_it(self):
        c = _case("spray-foam-5th-floor-ceiling")
        self.assertIsNone(c["expect"]["quote"])
        self.assertIn("scripts/plan_sheet_text.py --sheet A-302.00 --contains 'ROOF ASSEMBLY'",
                      c["pending"])

    def test_an_unknown_quote_without_pending_is_refused(self):
        suite = json.loads(Path(SUITE).read_text(encoding="utf-8"))
        del suite["cases"][0]["pending"]
        with self.assertRaises(de.SuiteError):
            de.validate_suite(suite)

    def test_a_case_that_checks_nothing_and_is_not_pending_is_refused(self):
        suite = json.loads(Path(SUITE).read_text(encoding="utf-8"))
        del suite["cases"][1]["pending"]
        with self.assertRaises(de.SuiteError):
            de.validate_suite(suite)


class SprayFoam(unittest.TestCase):

    def test_a_right_answer_is_still_failing_pending_not_pass(self):
        r = de.score_answer(_case("spray-foam-5th-floor-ceiling"), GOOD_FOAM)
        self.assertEqual(r["outcome"], "failing-pending")
        self.assertTrue(all(r["checks"].values()))
        self.assertTrue(r["reasons"][-1].startswith("PENDING: exact A-302.00 detail 4 text"))

    def test_each_forbidden_phrase_fails_it(self):
        c = _case("spray-foam-5th-floor-ceiling")
        for bad in ("Spray foam is not required there.", "Nothing calls for it on the 5th floor.",
                    "No spray foam at that ceiling.", "The roof doesn’t require it."):
            r = de.score_answer(c, GOOD_FOAM + " " + bad)
            self.assertEqual(r["outcome"], "fail", bad)

    def test_the_old_answer_fails_on_what_it_missed(self):
        r = de.score_answer(_case("spray-foam-5th-floor-ceiling"),
                            "Spray foam at the 5th floor ceiling: 2\" closed cell, A-501.")
        self.assertEqual(r["outcome"], "fail")
        self.assertIn("does not say 'Mezzanine'", r["reasons"])


class SendThePdf(unittest.TestCase):

    def test_send_plan_file_ran_and_nothing_refused_passes(self):
        r = de.score_answer(_case("send-me-the-pdf"), "Sent AR - 3.28.25.pdf.", ["send_plan_file"])
        self.assertEqual(r["outcome"], "pass")

    def test_a_sheet_image_is_not_the_pdf(self):
        r = de.score_answer(_case("send-me-the-pdf"), "Sent A-302.00.", ["send_sheet"])
        self.assertEqual(r["outcome"], "fail")

    def test_i_cant_send_files_fails_with_either_apostrophe(self):
        for said in ("Sorry, I can't send files here.", "Sorry, I can’t send files here."):
            r = de.score_answer(_case("send-me-the-pdf"), said, ["send_plan_file"])
            self.assertEqual(r["outcome"], "fail", said)


class KitchenSoffits(unittest.TestCase):

    def test_equating_bulkhead_and_soffit_fails(self):
        for said in ("The kitchen bulkhead (soffit) over the cabinets is 12\" deep.",
                     "Kitchen soffits, aka bulkheads, drop to 7'-6\" at the ceiling."):
            r = de.score_answer(_case("kitchen-soffits"), said)
            self.assertEqual(r["outcome"], "fail", said)

    def test_naming_the_eave_to_set_it_aside_is_allowed_but_still_pending(self):
        r = de.score_answer(_case("kitchen-soffits"),
                            "The kitchen soffit is the dropped ceiling over the cabinets "
                            "(not the exterior eave).")
        self.assertEqual(r["outcome"], "failing-pending")


class TheRunner(unittest.TestCase):

    def test_a_day_scored_from_the_timeline_file(self):
        day = {"messages": [
            {"inbound": {"body": "588 do I need spray foam on 5th floor ceiling", "at": "t1"},
             "answer": {"answer": "Not required on the 5th floor.",
                        "tool_data": [{"tool": "search_plans"}]}, "outbound": []},
            {"inbound": {"body": "send me the PDF", "at": "t2"},
             "answer": {"answer": "", "tool_data": [{"tool": "send_plan_file"}]},
             "outbound": [{"body": "Sent AR - 3.28.25.pdf"}]}]}
        with tempfile.TemporaryDirectory() as d:
            tl = os.path.join(d, "day.json")
            res = os.path.join(d, "out.json")
            Path(tl).write_text(json.dumps(day), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = runner.main(["--suite", SUITE, "--timeline", tl, "--out", res])
            saved = json.loads(Path(res).read_text(encoding="utf-8"))
        text = buf.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("FAIL            spray-foam-5th-floor-ceiling", text)
        self.assertIn("says the forbidden 'not required'", text)
        self.assertIn("PASS            send-me-the-pdf", text)
        self.assertIn("NOT-ASKED       kitchen-soffits", text)
        self.assertEqual(saved["summary"]["pass"], 1)
        self.assertEqual(saved["summary"]["pass_rate"], round(1 / 6, 3))

    def test_a_reply_to_another_message_is_not_scored_as_this_answer(self):
        # Overlapping turns: the late refusal of an earlier ask went out after
        # "send me the PDF" and is attributed to that earlier message.
        case = {"id": "pdf", "match": r"send me the pdf"}
        day = {"messages": [
            {"inbound": {"body": "send me the PDF", "at": "t2"},
             "answer": {"answer": "Sent AR - 3.28.25.pdf", "tool_data": [{"tool": "send_plan_file"}]},
             "outbound": [
                 {"body": "Sorry, I can't send files.", "answers_mine": False, "late": False},
                 {"body": "Sent AR - 3.28.25.pdf", "answers_mine": True, "late": False},
                 {"body": "Unrelated late reply", "answers_mine": None, "late": True},
                 {"body": "Here is page 2 too", "answers_mine": None, "late": False}]}]}
        (turn,) = de.find_turns(case, day)
        self.assertIsNone(re.search(r"can't send files", turn["answer"]))
        self.assertIsNone(re.search(r"Unrelated late reply", turn["answer"]))
        self.assertRegex(turn["answer"], r"Here is page 2 too")

    def test_pending_counts_against_the_rate(self):
        s = de.summarise(["pass", "failing-pending"])
        self.assertEqual((s["pass"], s["failing-pending"], s["pass_rate"]), (1, 1, 0.5))


if __name__ == "__main__":
    unittest.main()
