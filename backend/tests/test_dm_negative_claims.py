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


class CodexFindings(unittest.TestCase):
    def test_curly_apostrophes_are_flagged_too(self):
        s = "The drawings don\u2019t show spray foam."
        self.assertEqual(gate.detect(s), [s])

    def test_a_mixed_turn_keeps_its_attendance_negative(self):
        trace = PLANS + [{"tool": "headcount", "args": {}, "result": "0 on site"}]
        out, n = gate.rewrite("There are no workers on site today. Spray foam is not required.",
                              trace)
        self.assertEqual(n, 1)
        self.assertRegex(out, r"^There are no workers on site today\. ")
        self.assertRegex(out, r"Not found in the sheets I searched: A-302\.00\.")

    def test_a_phone_in_the_closest_detail_is_redacted(self):
        trace = [{"tool": "search_plans", "args": {}, "result": "",
                  "records": [{"sheet": "A-302.00",
                               "quote": "FIXTURE TEXT: ROOF BY ACME CALL 718-555-0142"}]}]
        out = server._dm_no_negative_claims("Spray foam is not required.", trace, {})
        self.assertRegex(out, r'Closest detail: A-302\.00 — "FIXTURE TEXT: ROOF BY ACME CALL ')
        self.assertIsNone(re.search(r"555.?0142", out))


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


class ClauseSplit(unittest.TestCase):
    """11-03: the stored ceiling-height render says 'Ceiling height not shown;
    floor-to-floor 10'-0" (A-300.00)'. The gate took the WHOLE sentence for
    an absence claim and dropped the 10'-0": a measured value replaced by
    'Not found'. Only the absence clause is the gate's; a clause that states
    a value stays."""

    RENDER = "Ceiling height not shown; floor-to-floor 10'-0\" (A-300.00)"
    TRACE = [{"tool": "search_plans", "args": {}, "result": "",
              "records": [{"sheet": "A-300.00",
                           "quote": "BASE PLANE 33.37' 0'-0\" | SECOND FLOOR 43.37' +10'-0\""},
                          {"sheet": "A-500.00", "quote": "TABLE PARTITION TYPE 1"}]}]

    def test_the_stored_ceiling_height_render_keeps_its_number(self):
        out, n = gate.rewrite(self.RENDER, self.TRACE)
        self.assertEqual(n, 1)
        lines = out.split("\n")
        self.assertEqual(lines[0], "Not found in the sheets I searched: A-300.00, A-500.00.")
        self.assertIn("Floor-to-floor 10'-0\" (A-300.00)", lines)
        # the value is on a line of its own, not inside the gate's line
        self.assertNotIn("10'-0\"", lines[0])
        self.assertTrue(lines[-1].startswith("Closest detail: A-300.00"))

    def test_the_value_clause_comes_first_too(self):
        out, n = gate.rewrite("Floor-to-floor is 10'-0\" (A-300.00); ceiling height not shown.",
                              self.TRACE)
        self.assertEqual(n, 1)
        self.assertIn("Floor-to-floor is 10'-0\" (A-300.00)", out.split("\n"))
        self.assertNotIn("not shown", out)

    def test_semicolon_inside_a_quote_does_not_split(self):
        out, n = gate.rewrite('Nothing on the drawings calls for it; see "NOTE 4; 2 HR RATED".',
                              self.TRACE)
        self.assertEqual(n, 1)
        self.assertTrue(out.startswith(gate.NOT_FOUND_PREFIX))

    def test_a_sentence_with_no_value_clause_is_replaced_whole(self):
        out, n = gate.rewrite("Nothing is specified; check with the architect.", self.TRACE)
        self.assertEqual(n, 1)
        self.assertNotIn("architect", out)

    def test_an_answer_with_no_semicolon_is_unchanged_by_the_split(self):
        out, n = gate.rewrite("Spray foam is not required, 2 coats are shown.", self.TRACE)
        self.assertEqual(n, 1)
        self.assertNotIn("2 coats", out)

    # ── 11-03 review: fail toward the old behaviour ──────────────────────
    def _whole(self, text):
        out, n = gate.rewrite(text, self.TRACE)
        self.assertEqual(n, 1)
        self.assertEqual(out.split("\n")[0], "Not found in the sheets I searched: A-300.00, A-500.00.")
        return out

    def test_two_feet_inch_dimensions_are_not_a_fake_quote(self):
        out, n = gate.rewrite("Plenum is 2'-0\" deep; ceiling height not shown; "
                              "floor is 10'-0\" high.", self.TRACE)
        self.assertEqual(n, 1)
        lines = out.split("\n")
        self.assertIn("Plenum is 2'-0\" deep", lines)
        self.assertIn("Floor is 10'-0\" high.", lines)
        self.assertNotIn("not shown", out)

    def test_semicolon_inside_parentheses_does_not_split(self):
        out, n = gate.rewrite("Fire rating not specified (see A-300; A-301); floor is 10 ft.",
                              self.TRACE)
        self.assertEqual(n, 1)
        lines = out.split("\n")
        self.assertIn("Floor is 10 ft.", lines)         # the paren is not split: no "A-301)"
        self.assertFalse([l for l in lines if "A-301" in l and "Closest" not in l])
        # an unbalanced paren is not split at all: whole replacement
        out2 = self._whole("Fire rating not specified (see A-300; floor is 10 ft.")
        self.assertNotIn("10 ft", out2)

    def test_a_sheet_only_clause_is_not_kept(self):
        out = self._whole("Ceiling height not shown; see A-300.00.")
        self.assertNotIn("See A-300.00", out.split("\n")[1:-1])
        self.assertEqual(len(out.split("\n")), 2)       # not-found + closest only

    def test_three_clauses(self):
        out, n = gate.rewrite("Plenum is 2'-0\" deep; ceiling height not shown; "
                              "slab is 8 in; floor is 10'-0\" high.", self.TRACE)
        self.assertEqual(n, 1)
        lines = out.split("\n")
        for want in ("Plenum is 2'-0\" deep", "Slab is 8 in", "Floor is 10'-0\" high."):
            self.assertIn(want, lines)

    def test_a_mixed_run_with_one_unvalidated_clause_is_replaced_whole(self):
        out = self._whole("No PTAC shown on 5; 12 on floor 4; none on floor 3.")
        self.assertNotIn("none on floor 3", out.lower())
        self.assertNotIn("12 on floor 4", out)

    def test_none_on_floor_3_does_not_survive(self):
        out = self._whole("Ceiling height not shown; none on floor 3.")
        self.assertNotIn("None on floor 3", out)

    def test_a_number_inside_the_absence_clause_is_still_dropped(self):
        # documented, as before: only the absence clause's numbers go with it
        out, n = gate.rewrite("Fire rating of 2 hr not shown; floor is 10 ft.", self.TRACE)
        self.assertEqual(n, 1)
        self.assertIn("Floor is 10 ft.", out.split("\n"))
        self.assertNotIn("2 hr", out)
        # and a clause with no unit is not kept, even holding a number
        out2 = self._whole("Ceiling not shown; 12 are on floor 4.")
        self.assertNotIn("12", out2.split("\n")[1])

    def test_a_conjunction_led_clause_is_not_kept(self):
        out = self._whole("Ceiling not shown; but floor-to-floor is 10 ft.")
        self.assertNotIn("floor-to-floor", out)

    def test_sheet_ids_keep_their_case(self):
        self.assertEqual(gate.measured_clauses("Ceiling height not shown; a-300 shows 10 ft."),
                         ["a-300 shows 10 ft."])

    def test_gate_twice_is_the_same(self):
        for text in (self.RENDER,
                     "Plenum is 2'-0\" deep; ceiling height not shown; floor is 10'-0\" high.",
                     "No PTAC shown on 5; 12 on floor 4; none on floor 3."):
            once, _ = gate.rewrite(text, self.TRACE)
            twice, n2 = gate.rewrite(once, self.TRACE)
            self.assertEqual(n2, 0)
            self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
