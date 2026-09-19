"""A CALLOUT IS AN EDGE, AND THE FIRST SET-WIDE CHECK ASKS WHETHER IT LANDS.

Everything else the reader does answers a question about one subject. A
superintendent reading the set before mobilising has a different need: not
"what does the drawing say about X" — he can read a drawing — but "what in
this set does not add up".

MEASURED ON 588 BOYLAND 2026-09-19: 120 callouts on current pages, 47 with a
sheet-number-shaped target, and **8 pointing at a sheet the set does not
contain**. Seven of those eight are the structural drawings all referencing
S-400; the eighth is S-302.00 referencing FO-101.

── TWO THINGS THAT DECIDE WHETHER ANYONE READS THE REPORT ───────────────────

THE TARGET MUST LOOK LIKE A SHEET NUMBER. A naive version of this counted 24
findings, of which roughly half were a neighbouring building's street number
('NO. 586'), a detail-bubble label ('ELEV.') and riser tags. 66 of the 120
targets are rejected by the shape check. Reporting them would teach a
superintendent to ignore the report, which costs more than the check is worth.

AND ONE MISSING SHEET IS ONE FINDING, NOT SEVEN. Eight rows say eight
problems. The truth is two.

── THE WORDING IS PART OF THE CONTRACT ──────────────────────────────────────

'referenced but not in the indexed set', never 'missing'. A sheet may never
have been issued, or may simply not have been uploaded, and nothing in the
records distinguishes those. Saying 'missing' asserts the first and would send
somebody to the architect over an upload.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as ps  # noqa: E402


def callout(from_sheet, target, detail="", text=""):
    return {"sheet_number": from_sheet,
            "quote": text or f"SEE {target}",
            "payload": {"target_sheet": target, "detail_number": detail}}


class ACalloutThatLandsIsNotAFinding(unittest.TestCase):

    def test_a_target_in_the_set_is_silent(self):
        self.assertEqual(
            ps.dangling_callouts([callout("A-101.00", "A-201")],
                                 ["A-201", "A-101.00"]), [])

    def test_a_target_not_in_the_set_is_reported(self):
        got = ps.dangling_callouts([callout("A-101.00", "A-201", "3")],
                                   ["A-101.00"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["target_sheet"], "A-201")
        self.assertEqual(got[0]["from_sheet"], "A-101.00")
        self.assertEqual(got[0]["detail_number"], "3")

    def test_a_revision_satisfies_the_base_sheet(self):
        """A-105 and A-105.01 are the same drawing at different issues.
        Without this every reissued sheet generates a false finding."""
        self.assertEqual(
            ps.dangling_callouts([callout("A-102.00", "A-105")],
                                 ["A-105.01"]), [])

    def test_and_the_other_way_round(self):
        self.assertEqual(
            ps.dangling_callouts([callout("A-102.00", "A-105.01")],
                                 ["A-105"]), [])


class ThingsThatAreNotSheetReferences(unittest.TestCase):
    """66 of 120 targets on the real corpus. Each of these was really there."""

    def test_a_neighbouring_street_number_is_not_a_sheet(self):
        got = ps.dangling_callouts(
            [callout("M-101.00", "NO. 586",
                     text="ADJACENT 2 STORY BRICK & CELLAR No. 586")], [])
        self.assertEqual(got, [])

    def test_a_detail_bubble_label_is_not_a_sheet(self):
        self.assertEqual(
            ps.dangling_callouts([callout("3 OF 3", "ELEV.", "1")], []), [])

    def test_a_riser_tag_is_not_a_sheet(self):
        self.assertEqual(
            ps.dangling_callouts(
                [callout("P-100.00", "NO. 586",
                         text="SEE D.W. RISER. 1A No. 586")], []), [])

    def test_an_empty_target_is_not_a_finding(self):
        self.assertEqual(ps.dangling_callouts([callout("A-1.00", "")], []), [])

    def test_a_bare_word_is_not_a_sheet(self):
        for junk in ("TYPICAL", "SEE PLAN", "ARCH", "-", "1"):
            self.assertEqual(
                ps.dangling_callouts([callout("A-1.00", junk)], []), [],
                f"{junk!r} was read as a sheet reference")


class OneMissingSheetIsOneFinding(unittest.TestCase):

    def _seven_plus_one(self):
        cs = [callout(f"S-10{i}.00", "S-400") for i in range(1, 8)]
        cs.append(callout("S-302.00", "FO-101", "2"))
        return cs

    def test_seven_callouts_to_one_sheet_group_into_one_row(self):
        rows = ps.referenced_sheets_missing(self._seven_plus_one(),
                                            ["S-302.00"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["target_sheet"], "S-400")
        self.assertEqual(len(rows[0]["referenced_by"]), 7)

    def test_the_most_referenced_comes_first(self):
        rows = ps.referenced_sheets_missing(self._seven_plus_one(), [])
        self.assertEqual([r["target_sheet"] for r in rows][0], "S-400")

    def test_the_summary_says_how_many_sheets_point_at_it(self):
        rows = ps.referenced_sheets_missing(self._seven_plus_one(), [])
        self.assertIn("7 sheets", rows[0]["summary"])
        self.assertIn("1 sheet", rows[1]["summary"])
        self.assertNotIn("1 sheets", rows[1]["summary"])

    def test_the_referencing_sheets_are_not_duplicated(self):
        cs = [callout("S-101.00", "S-400"), callout("S-101.00", "S-400", "2")]
        rows = ps.referenced_sheets_missing(cs, [])
        self.assertEqual(rows[0]["referenced_by"], ["S-101.00"])


class TheWordingIsPartOfTheContract(unittest.TestCase):

    def test_the_summary_never_says_missing(self):
        """A sheet may not have been issued, or may not have been uploaded.
        The records cannot tell those apart and the report must not pretend."""
        rows = ps.referenced_sheets_missing(
            [callout("S-101.00", "S-400")], [])
        summary = rows[0]["summary"].lower()
        self.assertIn("not in the indexed set", summary)
        # Checked as WORDS. `assertNotIn("missing", summary)` is a substring
        # test that any word containing it would break, which
        # test_absence_literals_are_specific bans - and caught here.
        self.assertNotIn("missing", summary.split(),
                         "the report claims a sheet is MISSING; it cannot "
                         "know whether it was never issued or never uploaded")

    def test_the_tool_description_carries_the_same_instruction(self):
        """The model composes the sentence a person reads, so the wording rule
        has to reach it too."""
        import server
        tools = [t for t in server._AGENT_TOOLS
                 if t.get("function", {}).get("name") == "check_drawing_set"]
        self.assertEqual(len(tools), 1, "the tool is not registered")
        desc = tools[0]["function"]["description"]
        self.assertIn("referenced but not in the indexed set", desc)
        self.assertIn("NEVER", desc)


class NothingWrongIsAnAnswerToo(unittest.TestCase):

    def test_a_clean_set_reports_nothing(self):
        self.assertEqual(
            ps.referenced_sheets_missing(
                [callout("A-101.00", "A-201")], ["A-201"]), [])

    def test_no_callouts_at_all_is_not_an_error(self):
        self.assertEqual(ps.referenced_sheets_missing([], ["A-1.00"]), [])
        self.assertEqual(ps.referenced_sheets_missing(None, None), [])


if __name__ == "__main__":
    unittest.main()
