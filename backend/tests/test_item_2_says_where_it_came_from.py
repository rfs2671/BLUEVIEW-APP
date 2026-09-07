"""ITEM 2 PRINTS WHERE ITS TEXT CAME FROM, AND THE FILED RECORD IS UNTOUCHED.

BC 3301.13.13 item 2, verbatim from the 2022 BC Chapter 33:

    2. The general progress of work at the job site, including a summary of
       that day's work activity;

on a log the CONSTRUCTION SUPERINTENDENT "must maintain" and whose "each day's
log entry must be signed and dated by the construction superintendent". The
CP's daily jobsite log is a different document with a different signer, so the
item cannot be dropped on the grounds that the information exists elsewhere.

BUT NOTHING REQUIRES HIM TO HAVE COMPOSED THE SENTENCE. Item 3 one line down is
expressly "the CONSTRUCTION SUPERINTENDENT'S activities"; item 2 is a fact
about the site. Adopting the CP's summary into his log, which he signs and
dates, puts the required information in the required document.

── SO THE DOCUMENT SAYS WHICH IT WAS, AND THESE LINES WERE DARK ────────────

`superintendent_log.py` declared `provenance` and argued for shipping it before
the client half, because RETROFITTING PROVENANCE ONTO FILED RECORDS IS
IMPOSSIBLE. The client half never landed, so `PROVENANCE_ADOPTED` could not be
produced by any code path that existed and the render was removed as a
distinction the data could not make. It is restored here with the half that
makes it real.

── WHY UNMARKED PRINTS NOTHING, ASSERTED RATHER THAN LEFT TO CHANCE ────────

`NOT_RECORDED` is this codebase's sanctioned string for a field the form
OFFERED and he left blank. Provenance was never offered on a log filed before
the flag existed, so the app has no statement to make about it rather than a
statement that it is missing. One such record exists -- 2026-09-04, holding
`{"summary": "First floor C joist framing"}` and no `source` -- and its exact
shape is a fixture below. Printing "not recorded" there would report a gap in
HIS answers that is really a gap in the app's history.

THIS IS THE FORWARD-ONLY ASSERTION. Nothing rewrites what is filed, and the one
filed record must render exactly as it did before this change.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from lib.logbook.superintendent_log import (  # noqa: E402
    PROVENANCE_ADOPTED, PROVENANCE_OWN, PROVENANCE_UNMARKED, item_provenance,
)

ADOPTED_LINE = "Adopted from the competent person"
OWN_LINE = "own account of the day"

#: The record production actually holds, verbatim from the filed row.
FILED_2026_09_04 = {
    "date": "2026-09-04",
    "cp_name": "Michael Cespedes",
    "data": {
        "presence": {"printed_name": "Michael Cespedes",
                     "arrived_at": "07:00", "departed_at": "16:00"},
        "progress": {"summary": "First floor C joist framing"},
        "competent_person": {},
    },
}


def _render(progress_block, **over):
    lb = {
        "date": "2026-09-04",
        "cp_name": "Michael Cespedes",
        "data": {
            "presence": {"printed_name": "Michael Cespedes"},
            "progress": progress_block,
        },
    }
    lb.update(over)
    return server._superintendent_log_html(lb)


class TheLineSaysWhichItWas(unittest.TestCase):

    def test_adopted_text_says_so_and_says_he_signed_for_it(self):
        html = _render({"summary": "carpentry", "source": PROVENANCE_ADOPTED})
        self.assertIn(ADOPTED_LINE, html)
        # THE HALF THAT MATTERS. Without it the line reads as a disclaimer --
        # "this is somebody else's sentence" -- when the legal position is the
        # opposite: he adopted it and signed it, so it is his statement.
        self.assertIn("signed for by the superintendent", html)

    def test_his_own_account_says_so(self):
        html = _render({"summary": "First floor C joist framing",
                        "source": PROVENANCE_OWN})
        self.assertIn(OWN_LINE, html)
        self.assertNotIn(ADOPTED_LINE, html)

    def test_the_summary_itself_still_prints_either_way(self):
        """The line is an ADDITION. A change that replaced the content with a
        note about the content would be the worst outcome available here."""
        for source in (PROVENANCE_ADOPTED, PROVENANCE_OWN):
            with self.subTest(source):
                html = _render({"summary": "carpentry", "source": source})
                self.assertIn("Carpentry", html)


class TheAlreadyFiledRecordIsUNTOUCHED(unittest.TestCase):
    """FORWARD-ONLY. The one filed superintendent log must render exactly as it
    did before this change."""

    def test_it_resolves_to_unmarked(self):
        self.assertEqual(item_provenance(FILED_2026_09_04["data"]),
                         PROVENANCE_UNMARKED)

    def test_and_prints_no_provenance_line_at_all(self):
        html = server._superintendent_log_html(FILED_2026_09_04)
        self.assertNotIn(ADOPTED_LINE, html)
        self.assertNotIn(OWN_LINE, html)

    def test_but_still_prints_its_summary(self):
        html = server._superintendent_log_html(FILED_2026_09_04)
        self.assertIn("First floor C joist framing", html)

    def test_and_does_not_print_NOT_RECORDED_for_the_provenance(self):
        """The sanctioned absence string is for a field the form OFFERED. This
        log was never asked the question, so reporting the answer as missing
        would describe a gap in his answers that is a gap in the app's
        history."""
        html = server._superintendent_log_html(FILED_2026_09_04)
        row = html[html.index("General progress of work"):]
        row = row[:row.index("</tr>")]
        self.assertNotIn(server.NOT_RECORDED, row)


class AnEmptyItemTwoGetsNoLineEither(unittest.TestCase):

    def test_an_unanswered_item_2_reads_not_recorded_and_nothing_else(self):
        """A provenance line under "— Not recorded" would be a statement about
        the origin of a sentence that does not exist."""
        html = _render({})
        self.assertIn(server.NOT_RECORDED, html)
        self.assertNotIn(ADOPTED_LINE, html)
        self.assertNotIn(OWN_LINE, html)

    def test_a_source_with_no_summary_still_prints_nothing(self):
        """Defensive: a malformed block must not manufacture a claim about
        text nobody wrote."""
        html = _render({"source": PROVENANCE_ADOPTED})
        self.assertNotIn(ADOPTED_LINE, html)


class OnlyItemTwoCarriesIt(unittest.TestCase):

    def test_no_other_item_prints_a_provenance_line(self):
        """`provenance` is declared on item 2 alone. A loop that printed it for
        every item would put an origin claim on items nobody derived."""
        lb = {
            "date": "2026-09-04", "cp_name": "Michael Cespedes",
            "data": {
                "presence": {"printed_name": "Michael Cespedes"},
                "progress": {"summary": "carpentry",
                             "source": PROVENANCE_ADOPTED},
                "cs_activities": {"summary": "Walked floors 1-3"},
                "daily_inspection": {"location": "Floor 2", "result": "Clear"},
            },
        }
        html = server._superintendent_log_html(lb)
        self.assertEqual(html.count(ADOPTED_LINE), 1)


class TheLineIsOnBOTHDOCUMENTS(unittest.TestCase):
    """`legal_record` governs three things and this is none of them: the
    affirmation banner, the statutory citations, and the attestation
    paragraph -- all apparatus a DOB inspector needs and a lender does not.

    WHERE ITEM 2'S TEXT CAME FROM IS CONTENT, NOT APPARATUS. A lender reading
    "adopted from the competent person's daily log" learns something about the
    record in front of him. Asserted rather than left implicit, because the
    default for a new line is to inherit `legal_record` and this one
    deliberately does not.
    """

    def test_the_investor_report_carries_it_too(self):
        html = server._superintendent_log_html(
            {"date": "2026-09-04", "cp_name": "M",
             "data": {"progress": {"summary": "carpentry",
                                   "source": PROVENANCE_ADOPTED}}},
            legal_record=False)
        self.assertIn(ADOPTED_LINE, html)
        # The control on the flag itself, so this test cannot pass because
        # `legal_record` stopped doing anything.
        self.assertNotIn("BC 3301.13.13", html)


class TheLinesAreReachable(unittest.TestCase):
    """THE ASSERTIONS ABOVE ARE ABOUT ABSENCE AS MUCH AS PRESENCE, and a table
    nobody reads satisfies every absence test in this file."""

    def test_the_table_is_keyed_on_what_item_provenance_returns(self):
        for value in (PROVENANCE_ADOPTED, PROVENANCE_OWN):
            with self.subTest(value):
                self.assertIn(value, server._CS_PROVENANCE_LINES)

    def test_and_unmarked_is_deliberately_absent_from_it(self):
        self.assertNotIn(PROVENANCE_UNMARKED, server._CS_PROVENANCE_LINES)

    def test_item_2_is_the_item_that_declares_provenance(self):
        by_key = {i["key"]: i for i in server.CS_LOG_ITEMS}
        self.assertTrue(by_key["progress"].get("provenance"))
        self.assertEqual(
            [k for k, i in by_key.items() if i.get("provenance")], ["progress"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
