"""A dimension in a claim binds only as a whole (ruling 2026-10-25).

The gate split a dimension into its digits and checked each against every
number the returned records print. Asked for the door sizes on 588 Boyland,
with A-400.00's door schedule returned, "The doors are 3'-5" X 7'-0"." was
allowed: nothing prints 3'-5", but a 3, a 5, a 7 and a 0 are each printed.

Now the whole dimension, normalized, must be printed: a length (12' is
12'-0" is 144"), an A X B in its order, and the text layer's reversed runs
("0-'7 is 7'-0") read the right way round. A single-number count is
untouched.

These use only `answer_is_grounded`, which main has, so the control run on
main fails by assertion, not by import.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

#: A-400.00's door-elevation schedule as production stores it (plan_records,
#: schedule_cell, table_finder; read 2026-10-25): the height of door E is
#: drawn vertically and the text layer gives it back reversed, "0-'7.
A400_TABLE = ("TABLE NUMBER A | | NUMBER B | | NUMBER C | | NUMBER D | | NUMBER E | "
              "3'-0\" \"0-'7 FINISHED FLOOR | | 3'-0\" \"0-'7 FINISHED FLOOR")
#: The size line printed beside each door on the same sheet.
A400_SIZE = "3'-0\" X 7'-0\""


def _gate(text, quotes, intent="attribute"):
    from lib import plan_search as ps
    recs = [{"quote": q, "sheet_number": "A-400.00", "record_type": "schedule"} for q in quotes]
    return ps.answer_is_grounded(text, recs, intent=intent)


class TheWholeDimensionMustBePrinted(unittest.TestCase):

    def test_an_invented_size_made_of_printed_digits_refuses(self):
        ok, bad = _gate("The doors are 3'-5\" X 7'-0\".", [A400_TABLE, A400_SIZE, "SEE NOTE 5"])
        self.assertFalse(ok)
        self.assertEqual(bad, ["3'-5\" X 7'-0\""])

    def test_the_printed_size_binds(self):
        self.assertEqual(_gate("The doors are 3'-0\" X 7'-0\" [A-400.00].", [A400_TABLE, A400_SIZE]),
                         (True, []))

    def test_an_a_x_b_binds_only_in_its_printed_order(self):
        ok, bad = _gate("The doors are 7'-0\" X 3'-0\".", [A400_SIZE])
        self.assertFalse(ok)
        self.assertEqual(bad, ["7'-0\" X 3'-0\""])

    def test_an_a_x_b_is_not_assembled_from_two_printed_lengths(self):
        # 5'-0" and 2'-6" are both printed on A-400.00, never as one size.
        ok, bad = _gate("The opening is 5'-0\" X 2'-6\".", ["OPENINGS 5'-0\" 2'-6\" 2'-6\""])
        self.assertFalse(ok)
        self.assertEqual(bad, ["5'-0\" X 2'-6\""])
        self.assertEqual(_gate("The opening is 5'-0\" wide.", ["OPENINGS 5'-0\" 2'-6\""]), (True, []))

    def test_a_single_length_needs_the_whole_length(self):
        ok, bad = _gate("The door is 3'-5\" wide.", [A400_SIZE, "SEE NOTE 5"])
        self.assertFalse(ok)
        self.assertEqual(bad, ["3'-5\""])

    def test_the_same_length_in_another_notation_binds(self):
        self.assertEqual(_gate("The shed is 8'-0\" high.", ["8' HIGH SHED"]), (True, []))
        self.assertEqual(_gate("The shed is 8 feet high.", ["8' HIGH SHED"]), (True, []))
        self.assertEqual(_gate("The door is 36 inches wide.", [A400_SIZE]), (True, []))
        ok, bad = _gate("The shed is 9 feet high.", ["8' HIGH SHED"])
        self.assertEqual((ok, bad), (False, ["9 feet"]))

    def test_another_notation_binds_only_by_exact_equality(self):
        # Lengths are compared as exact fractions, never rounded: 25.5' IS
        # 25'-6" (306 in); 25.4' is 304.8 in, which no rounding may carry to
        # 25'-6", and 25'-5" (305 in) is not 25.4' either.
        self.assertEqual(_gate("It is 25'-6\".", ["25.5'"]), (True, []))
        self.assertEqual(_gate("It is 25'-6\".", ["25.4'"]), (False, ["25'-6\""]))
        self.assertEqual(_gate("It is 25'-5\".", ["25.4'"]), (False, ["25'-5\""]))
        self.assertEqual(_gate("It is 25.4'.", ["25'-6\""]), (False, ["25.4'"]))
        self.assertEqual(_gate("It is 0'-0 3/4\".", ["3/4\""]), (True, []))
        self.assertEqual(_gate("It is 0.75\".", ["3/4\""]), (True, []))
        self.assertEqual(_gate("It is 0.7\".", ["3/4\""]), (False, ["0.7\""]))

    def test_a_size_printed_with_its_unit_after_binds(self):
        quote = "Use MAGZO Adjustable Window Screen, 48x99 Inch Durable Fiberglass Screen Mesh"
        self.assertEqual(_gate("It specifies a 48x99 Inch screen mesh.", [quote]), (True, []))
        ok, bad = _gate("It specifies a 48x98 Inch screen mesh.", [quote])
        self.assertEqual((ok, bad), (False, ["48x98 Inch"]))

    def test_the_unit_after_an_a_x_b_is_its_unit(self):
        # 3x7 INCHES is a small plate, not a door; read without its unit the
        # bare 3 and 7 would pass for whole feet.
        ok, bad = _gate("The opening is 3' X 7'.", ["ACCESS PLATE 3x7 INCHES"])
        self.assertEqual((ok, bad), (False, ["3' X 7'"]))
        self.assertEqual(_gate("The plate is 3\" X 7\".", ["ACCESS PLATE 3x7 INCHES"]), (True, []))

    def test_a_bare_number_takes_its_neighbours_unit(self):
        # 10x8" is a 10" X 8" duct; the bare 10 must not pass for ten feet.
        ok, bad = _gate("The duct is 10' X 8\".", ["DUCT 10x8\" UP"])
        self.assertEqual((ok, bad), (False, ["10' X 8\""]))
        self.assertEqual(_gate("The duct is 10\" X 8\".", ["DUCT 10x8\" UP"]), (True, []))


class TheReversedTextLayer(unittest.TestCase):

    def test_a_reversed_run_reads_the_right_way_round(self):
        # "0-'7 is the only 7'-0" in this record.
        self.assertEqual(_gate("Door E is 7'-0\" high.", [A400_TABLE]), (True, []))

    def test_and_does_not_lend_a_length_it_does_not_print(self):
        ok, bad = _gate("Door E is 7'-1\" high.", [A400_TABLE, "SEE DETAIL 1"])
        self.assertEqual((ok, bad), (False, ["7'-1\""]))


class WhatIsNotADimension(unittest.TestCase):

    def test_a_closing_quotation_mark_is_not_an_inch_mark(self):
        self.assertEqual(_gate('The schedule reads "PTAC-1: 21".', ["PTAC-1 | 21"]), (True, []))

    def test_a_count_is_unchanged(self):
        from lib import plan_search as ps
        recs = [{"quote": "PTAC UNITS SCHEDULE UNIT NO. | QTY", "sheet_number": "M-200.00",
                 "record_type": "schedule", "payload": {"name": "PTAC UNITS SCHEDULE",
                                                        "columns": [{"header": "UNIT NO."}, {"header": "QTY"}],
                                                        "rows": [["PTAC-1", "21"]]}}]
        main_like = ps._count_answer_is_bound("There are 21 PTAC-1.", recs)
        self.assertEqual(ps.answer_is_grounded("There are 21 PTAC-1.", recs, intent="count"), main_like)

    def test_a_dimension_in_a_count_answer_is_checked_whole_too(self):
        from lib import plan_search as ps
        recs = [{"quote": "PTAC UNIT 3'-8\" X 1'-6\" = 5.5'", "sheet_number": "A.2.3", "record_type": "text"}]
        ok, bad = ps.answer_is_grounded("Each PTAC is 3'-8\" X 1'-7\".", recs, intent="count")
        self.assertFalse(ok)
        self.assertIn("3'-8\" X 1'-7\"", bad)


class TheRealSheet(unittest.TestCase):
    """A-400.00's own text layer (AR - 3.28.25.pdf p23, fixture PDFs)."""

    def test_a400_text_layer(self):
        import pypdfium2 as pdfium
        path = str(require_pdf("AR - 3.28.25.pdf"))
        text = pdfium.PdfDocument(path)[22].get_textpage().get_text_range()
        self.assertIn("INTERIOR DOOR SCHEDULE", text)
        self.assertEqual(_gate("The doors are 3'-0\" X 7'-0\".", [text]), (True, []))
        for invented in ("3'-5\" X 7'-0\"", "3'-0\" X 7'-1\"", "7'-0\" X 3'-0\""):
            ok, bad = _gate(f"The doors are {invented}.", [text])
            self.assertFalse(ok, invented)
            self.assertEqual(bad, [invented])


if __name__ == "__main__":
    unittest.main()
