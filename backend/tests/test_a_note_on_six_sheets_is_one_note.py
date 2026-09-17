"""A general note stamped on every sheet of a discipline is one fact.

MEASURED ON 588 THOMAS S BOYLAND STREET, 2026-09-17, by asking the shipped
`search_plans` and counting what came back:

    'refrigerant piping'   8 records,  2 distinct quotes — 6 slots repeated
    'AC units'             8 records,  5 distinct quotes — 3 slots repeated
    'condensate pump'      8 records,  5 distinct quotes — 3 slots repeated

Asked what type of AC units the building has, the reader answered with one
sentence said five times, and the PTAC schedule — the thing that answers the
question — sat at positions six, seven and eight, below the fold of any
citation. That is eval case `ac-type` and its known failure class
`boilerplate_outranks_specific`.

WHY THE NOTES AND NOT THE REST. `boilerplate_lines` strips lines repeated
across a file's TEXT LAYER before extraction ever sees them. A note read off
the IMAGE never passes through it: the vision model sees each page alone and
transcribes the same paragraph again on every sheet. Of the 323 repeated note
rows on this project, 230 are vision-read.

WHY COLLAPSE AND NOT DELETE. Six of those repeated notes are the project's
specifications — `COLD & HOT WATER SHALL BE COPPER TYPE L, HARD DRAWN` is
stamped on six plumbing sheets and is the answer to what the hot water pipe is
made of. Deleting a repeated note would throw away the answer along with the
repetition. The copies collapse to one record and the survivor carries the
sheets the others were on, so the reader is told `P-100.00 (+5 sheets)`.

WHY NOT EVERYTHING ELSE. A parapet height measured on two plans is two facts
about two sheets and a reader wants both. Only a `note` is the same document
reproduced.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib import plan_search as ps  # noqa: E402

NOTE = ("2. CONTRACTOR SHALL RUN REFRIGERANT PIPES UP TO ROOF AS PER "
        "MANUFACTURER'S REQUIREMENTS FROM EACH INDOOR UNIT. EACH AC UNIT "
        "SHALL HAVE A MINI-CONDENSATE PUMP.")


def _note(sheet, page, quote=NOTE):
    return {"record_type": "note", "quote": quote, "tier": "vision_read",
            "sheet_number": sheet, "page_id": page, "page_number": int(page[-1]),
            "ordinal": 0}


def _elem(sheet, page, quote):
    return {"record_type": "element", "quote": quote, "tier": "schedule_cell",
            "sheet_number": sheet, "page_id": page, "page_number": 9,
            "ordinal": 0, "payload": {"mark": "PTAC-1", "count": 21}}


SIX_SHEETS = [_note(f"M-10{n}.00", f"pg{n}") for n in range(6)]


class TheCopiesCollapseToOne(unittest.TestCase):

    def test_one_record_survives(self):
        out = ps.dedupe_quotes(SIX_SHEETS)
        self.assertEqual(len(out), 1)

    def test_and_it_carries_the_sheets_the_others_were_on(self):
        out = ps.dedupe_quotes(SIX_SHEETS)[0]
        self.assertEqual(sorted(out["also_on"]),
                         ["M-101.00", "M-102.00", "M-103.00", "M-104.00", "M-105.00"])

    def test_nothing_is_dropped_that_the_reader_would_have_been_told(self):
        """The merge must not make one stamping look like the only one."""
        out = ps.render_records(ps.dedupe_quotes(SIX_SHEETS), "refrigerant")
        self.assertIn("M-100.00 (+5 sheets)", out)

    def test_one_other_sheet_is_singular(self):
        out = ps.dedupe_quotes(SIX_SHEETS[:2])
        self.assertIn("(+1 sheet)", ps.render_records(out, "refrigerant"))

    def test_the_model_is_told_too(self):
        out = server._render_records_for_model(ps.dedupe_quotes(SIX_SHEETS),
                                               "refrigerant")
        self.assertIn("M-100.00 (+5 sheets)", out)

    def test_the_strongest_copy_is_the_one_kept(self):
        """Same words, read off the image on five sheets and printed in the
        text layer on the sixth: the text-layer copy is the one to cite."""
        mixed = SIX_SHEETS[:5] + [dict(_note("M-105.00", "pg5"), tier="text_layer")]
        kept = ps.dedupe_quotes(mixed)[0]
        self.assertEqual(kept["tier"], "text_layer")
        self.assertEqual(kept["sheet_number"], "M-105.00")


class OnlyANoteIsTheSameDocumentTwice(unittest.TestCase):

    def test_a_measurement_on_two_sheets_stays_two_records(self):
        """42" PARAPET on the roof plan and on the section is two facts about
        two drawings. Collapsing them would answer half a question."""
        two = [{"record_type": "text", "quote": '42" PARAPET', "tier": "text_layer",
                "sheet_number": s, "page_id": p, "page_number": 1, "ordinal": 0}
               for s, p in (("A-105.01", "pg1"), ("A-300.00", "pg2"))]
        self.assertEqual(len(ps.dedupe_quotes(two)), 2)

    def test_and_so_does_a_schedule_row(self):
        two = [_elem("M-200.00", "pg9", "PTAC-1 COUNT 21"),
               _elem("M-201.00", "pg10", "PTAC-1 COUNT 21")]
        self.assertEqual(len(ps.dedupe_quotes(two)), 2)

    def test_the_same_note_twice_on_ONE_page_still_collapses(self):
        """The original rule, unchanged: a page repeating itself adds nothing."""
        same = [_note("M-100.00", "pg0"), _note("M-100.00", "pg0")]
        out = ps.dedupe_quotes(same)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].get("also_on"), None)


class WhatTheSlotsAreSpentOn(unittest.TestCase):
    """The harm, stated as the measurement that found it."""

    def test_the_schedule_reaches_the_lead_once_the_copies_are_one(self):
        records = SIX_SHEETS + [_elem("M-200.00", "pg9",
                                      "PTAC-1 COUNT 21 ROOMS PTAC UNITS SCHEDULE")]
        ranked = ps.rank(records, ps.search_terms("AC units"))
        sheets = [r.get("sheet_number") for r in ranked[:4]]
        self.assertIn("M-200.00", sheets,
                      f"the schedule is still below five copies of one note: {sheets}")

    def test_and_the_answer_is_no_longer_one_sentence_five_times(self):
        records = SIX_SHEETS + [_elem("M-200.00", "pg9", "PTAC-1 COUNT 21")]
        ranked = ps.rank(records, ps.search_terms("refrigerant pipes"))
        quotes = [r.get("quote") for r in ranked]
        self.assertEqual(len(quotes), len(set(quotes)))


if __name__ == "__main__":
    unittest.main()
