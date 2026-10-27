"""NEVER ABSENCE AS FACT (lib/dm_negative_claims): a DM answer about the
drawings says what was not FOUND in the sheets searched, never what the
building does not have.

10-27, spray foam on 588: search_plans returned A-104.00 and A-302.00
records, and the model answered "Nothing on the drawings calls for spray
foam on the 5th floor ceiling." The quotes in these fixtures are made up
(marked FIXTURE TEXT) -- not read off a real sheet.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import server  # noqa: E402
from lib import dm_negative_claims as gate  # noqa: E402
from tests.test_dm_brain import FakeLLM, _Brain, resp, text, use  # noqa: E402
from tests.test_dm_short_answers import _Site  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx  # noqa: E402

FIXTURES = json.loads((Path(__file__).resolve().parent / "fixtures"
                       / "dm_negative_claims.json").read_text())["cases"]
SPRAY = next(c for c in FIXTURES if c["id"] == "10-27-spray-foam")
ROOF_Q = "FIXTURE TEXT: ROOF ASSEMBLY: 2-PLY MOD BIT ON RIGID INSULATION ON DECK"
CEIL_Q = "FIXTURE TEXT: 5TH FLOOR REFLECTED CEILING, GWB ON RESILIENT CHANNEL"
SPRAY_SAID = "Nothing on the drawings calls for spray foam on the 5th floor ceiling."
NOT_FOUND = re.compile(r"^Not found in the sheets I searched: ")
CLOSEST_ROOF = re.compile(r'Closest detail: A-302\.00 — "' + re.escape(ROOF_Q) + '"$')
# The asserted-absence wording itself, anchored on its verb phrase.
SAYS_NOTHING_CALLS_FOR = re.compile(r"(?i)\bnothing on the drawings calls for\b")
PLANS = [{"tool": "search_plans", "args": {}, "result": "",
          "records": [{"sheet": "A-302.00", "quote": ROOF_Q}]}]


class Detect(unittest.TestCase):
    def test_absence_assertions_are_flagged(self):
        for s in (SPRAY_SAID,
                  "No spray foam is required at the 5th floor.",
                  "Spray foam is not required.",
                  "The plans don't show an access hatch.",
                  "The insulation type isn't specified.",
                  "There is no fire rating listed for that wall.",
                  "None of the sheets mention blocking.",
                  "Los planos no indican espuma en el techo."):
            self.assertEqual(gate.detect(s), [s], s)

    def test_not_flagged(self):
        for s in ('A-302.00 note: "SPRAYED FIREPROOFING NOT REQUIRED AT ROOF DECK".',
                  "- ROOF INSULATION NOT REQUIRED AT PARAPET [A-302.00]",
                  "Is spray foam not required on 5?",
                  "Not found in the sheets I searched: A-104.00, A-302.00.",
                  "I didn't search the sheets for that.",
                  "I couldn't find that in the drawings I've indexed.",
                  "EF-3 is an exhaust fan, 800 CFM, on A-201.",
                  "No need to call send_sheet."):
            self.assertEqual(gate.detect(s), [], s)

    def test_a_model_paraphrase_of_a_note_is_still_flagged(self):
        """Only the sheet's own words (quoted, or its capitals) with its sheet
        are exempt -- "not required" in the model's words is a claim."""
        s = "Per A-302.00, fireproofing is not required at the roof."
        self.assertEqual(gate.detect(s), [s])

    def test_attendance_turn_is_untouched(self):
        said = "No one from Arkon checked in at 588 today. Nothing shows for J&G either."
        trace = [{"tool": "headcount", "args": {}, "result": "0"}]
        self.assertEqual(gate.rewrite(said, trace), (said, 0))


class Rewrite(unittest.TestCase):
    def test_spray_foam(self):
        out, n = gate.rewrite(SPRAY["answer"], SPRAY["trace"])
        self.assertEqual(n, 1)
        self.assertEqual(out, "Not found in the sheets I searched: A-302.00, A-104.00.\n"
                              f'Closest detail: A-302.00 — "{ROOF_Q}"')

    def test_the_rest_of_the_answer_stays(self):
        out, n = gate.rewrite("Spray foam is not required. The roof is on A-302.00.", PLANS)
        self.assertEqual(n, 1)
        self.assertEqual(out.split("\n"), [
            "Not found in the sheets I searched: A-302.00. The roof is on A-302.00.",
            f'Closest detail: A-302.00 — "{ROOF_Q}"'])

    def test_two_claims_say_it_once(self):
        out, n = gate.rewrite("No spray foam is required. The plans don't show it.", PLANS)
        self.assertEqual(n, 2)
        self.assertEqual(len(re.findall(r"Not found in the sheets I searched", out)), 1)

    def test_searched_sheets_from_the_tool_text(self):
        """Roof-assembly scope and the empty-search list, as the tool printed them."""
        trace = [{"tool": "search_plans", "args": {}, "result":
                  "(The search for 'spray foam' returned no records.)\n"
                  "searched_sheets: the ceiling of the top occupied level is the underside of "
                  "the roof assembly, so the roof sections/details were searched too "
                  "(A-501.00, A-502.00).\nAnswer in two separate parts. ... say only: "
                  "'Not found in the sheets searched: A-501.00, A-502.00, the rest of the "
                  "indexed set.' That is a fact about this search"}]
        out, n = gate.rewrite("No spray foam is shown on the drawings.", trace)
        self.assertEqual(n, 1)
        self.assertEqual(out, "Not found in the sheets I searched: A-501.00, A-502.00, "
                              "the rest of the indexed set.")

    def test_old_path_trace_reads_the_rendered_records(self):
        trace = [{"tool": "search_plans", "args": {}, "result":
                  f"Records for 'spray foam'.\n- {ROOF_Q} [A-302.00 (+2 sheets)]\n- {CEIL_Q} [A-104.00]"}]
        out, _n = gate.rewrite(SPRAY_SAID, trace)
        self.assertEqual(out, "Not found in the sheets I searched: A-302.00, A-104.00.\n"
                              f'Closest detail: A-302.00 — "{ROOF_Q}"')

    def test_no_plan_tool_never_invents_sheets(self):
        out, n = gate.rewrite("The drawings don't show any blocking for the TVs.", [])
        self.assertEqual((out, n), ("I didn't search the sheets for that.", 1))

    def test_every_fixture(self):
        for c in FIXTURES:
            out, n = gate.rewrite(c["answer"], c["trace"])
            self.assertEqual(bool(n), c["expect_rewritten"], c["id"])
            plans = bool(gate.plan_calls(c["trace"]))
            self.assertEqual(gate.detect(out, plans), [], c["id"])


class TheBrainSaysNotFound(_Brain):
    def test_spray_foam_after_search_plans(self):
        records = [{"page_id": "pgR", "project_id": THOMAS, "sheet_number": "A-302.00",
                    "file_name": "A-set.pdf", "page_number": 30, "record_type": "note",
                    "quote": ROOF_Q, "tier": "text_layer", "verified": True},
                   {"page_id": "pgC", "project_id": THOMAS, "sheet_number": "A-104.00",
                    "file_name": "A-set.pdf", "page_number": 4, "record_type": "note",
                    "quote": CEIL_Q, "tier": "text_layer", "verified": True}]

        async def search(project_id, subject, **kw):
            return [dict(r) for r in records]

        async def shots(dm_chat, shots):
            return None
        llm = FakeLLM(resp(use("search_plans", {"job": "588", "subject": "spray foam 5th floor"})),
                      resp(text(SPRAY_SAID)))
        with _Ctx(db=self.db) as c, patch.object(server, "search_plans", search), \
                patch.object(server, "_dm_send_plan_shots", shots), \
                self.assertLogs(server.logger, "INFO") as logs:
            out = self.say(c, "does 588 need spray foam on the 5th floor ceiling", llm)
        self.assertEqual(len(out), 1)
        lines = out[0].split("\n")
        self.assertRegex(lines[0], NOT_FOUND)
        self.assertEqual(lines[0], "Not found in the sheets I searched: A-302.00, A-104.00.")
        self.assertRegex(lines[-1], CLOSEST_ROOF)
        self.assertIsNone(SAYS_NOTHING_CALLS_FOR.search(out[0]))
        said = "\n".join(logs.output)
        self.assertRegex(said, r"\[dm-gate\] negative claim rewritten company="
                         + re.escape(CO_A) + r" n=1\b")
        for line in logs.output:
            if "[dm-gate]" in line:
                self.assertIsNone(re.search(r"\d{7,}|(?i:spray foam)", line), line)
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertRegex(str(log.get("answer") or ""), r"^Not found in the sheets I searched: ")


class TheOldPathSaysNotFound(_Site, unittest.TestCase):
    def test_job_agent_spray_foam(self):
        async def agent(**kw):
            kw["tool_trace"].append({"tool": "search_plans", "args": {}, "result":
                                     f"Records for 'spray foam'.\n- {ROOF_Q} [A-302.00]\n"
                                     f"- {CEIL_Q} [A-104.00]"})
            return SPRAY_SAID
        with _Ctx(db=self.db) as c, patch.object(server, "DM_BRAIN_API_KEY", ""), \
                patch.object(server, "_run_group_agent", agent), \
                self.assertLogs(server.logger, "INFO") as logs:
            out = self._say(c, "does 588 need spray foam on the 5th floor ceiling",
                            None, False, None, None)
        self.assertIsNotNone(out)
        self.assertRegex(out, r"^Not found in the sheets I searched: A-302\.00, A-104\.00\.")
        self.assertRegex(out, re.escape('Closest detail: A-302.00 — "'))
        self.assertIsNone(SAYS_NOTHING_CALLS_FOR.search(out))
        self.assertRegex("\n".join(logs.output), r"\[dm-gate\] negative claim rewritten company="
                         + re.escape(CO_A) + r" n=1\b")
        self.assertIsNone(re.search(re.escape(ADMIN_PHONE), "\n".join(
            x for x in logs.output if "[dm-gate]" in x)))

    def test_attendance_answer_is_untouched(self):
        async def agent(**kw):
            kw["tool_trace"].append({"tool": "open_items", "result": "none"})
            return "No open violations at 588."
        with _Ctx(db=self.db) as c, patch.object(server, "DM_BRAIN_API_KEY", ""), \
                patch.object(server, "_run_group_agent", agent):
            out = self._say(c, "any violations at 588?", None, False, None, None)
        self.assertRegex(out, r"^No open violations at 588\.")


if __name__ == "__main__":
    unittest.main()
