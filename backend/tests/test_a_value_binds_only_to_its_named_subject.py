"""A printed value binds only when its record names the claim's subject or one
of its alternative names (operator ruling 2026-10-27).

The attribute gate bound a printed value to whatever subject the sentence
named: "The ceiling height is 10'-0"." passed on A-300.00, which prints only
floor-to-floor level marks, and on production 13 printed values bound as the
ceiling height - 1'-4" out of A-500.00's partition table, 1/2" out of "1/2"
METAL FLUSHED ON THE CEILING". The records below are those, verbatim.

Each test fails by assertion on the branch before this change.
"""

import inspect
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_eval as ev  # noqa: E402
from lib import plan_search as ps  # noqa: E402


def rec(**kw):
    base = {"page_id": "p1", "record_type": "text", "ordinal": 0, "tier": "text_layer",
            "source": "text_layer", "quote": "", "label": None, "subject_terms": [],
            "payload": {}, "sheet_number": "A-300.00", "file_id": "AR"}
    base.update(kw)
    return base


def gate(text, records, intent="attribute", aliases=None):
    """The gate, given the alternative names when it takes them."""
    kw = ({"aliases": aliases} if aliases is not None
          and "aliases" in inspect.signature(ps.answer_is_grounded).parameters else {})
    return ps.answer_is_grounded(text, records, intent=intent, **kw)[0]


A300 = [rec(quote="SECOND FLOOR 43.37' +10'-0\""),
        rec(record_type="dimension", quote="10'-0\"")]
PARAPET = [rec(sheet_number="A-105.01", quote="42\" PARAPET")]
METAL = [rec(sheet_number="A.3.5", quote="1/2 \" METAL FLUSHED ON THE CEILING"),
         rec(sheet_number="A-302.00", quote="1 HOUR FIRE RATED CEILING W/ ONE LAYER OF 5/8\" GYPSUM BOARD")]
# A-500.00's partition table as the table finder stores it: each partition
# type is a COLUMN, so its one row holds a cell from every type - CEILING in
# P1's runner note, FULL HEIGHT and the reversed 1'-4" in P2's build-up.
PARTITIONS = rec(
    sheet_number="A-500.00", record_type="schedule", tier="schedule_cell", source="table_finder",
    subject_terms=["TABLE"],
    quote=("TABLE PARTITION TYPE 1 P1 INTERIOR STUD WALL | PARTITION TYPE 2 P2 INTERIOR STUD WALL "
           "RUNNERS SHALL BE SECURELY ATTACHED AT THE FLOOR AND CEILING | 2 LAYERS 5 \" 8 GYPSUM "
           "BOARD 3 1 \" METAL STUD 2 16\" O.C. .PYT FULL HEIGHT SOUND ATTENUATION BLANKET \"4-'1"),
    payload={"name": "TABLE",
             "columns": [{"header": "PARTITION TYPE 1 P1 INTERIOR STUD WALL", "role": None},
                         {"header": "PARTITION TYPE 2 P2 INTERIOR STUD WALL", "role": None}],
             "rows": [["RUNNERS SHALL BE SECURELY ATTACHED AT THE FLOOR AND CEILING",
                       "2 LAYERS 5 \" 8 GYPSUM BOARD 3 1 \" METAL STUD 2 16\" O.C. .PYT FULL "
                       "HEIGHT SOUND ATTENUATION BLANKET \"4-'1"]]})
HEATER = rec(
    sheet_number="M-200.00", record_type="schedule", tier="ocr_grid_cell", source="ocr_grid",
    subject_terms=["DUCT ELECTRIC HEATER"],
    quote="DUCT ELECTRIC HEATER MARK | QTY | CAPACITY (KW) DH-1 | 1 | 15.0 DH-2 | 1 | 7.5",
    payload={"name": "DUCT ELECTRIC HEATER",
             "columns": [{"header": "MARK", "role": "identifier"},
                         {"header": "QTY", "role": "quantity"},
                         {"header": "CAPACITY (KW)", "role": None}],
             "rows": [["DH-1", "1", "15.0"], ["DH-2", "1", "7.5"]]})
# S-002.00's text layer, as production stores it.
S002_TEXT = ("IMMEDIATELY.\nABBREVIATIONS\nARCH.\nARCHITECTURAL\nCFS\nCOLD FORMED STEEL\n"
             "ELEV.\nELEVATION OR ELEVATOR\nFT.\nFEET/FOOT\nGA.\nGAUGE\nMTL.\nMETAL\n"
             "WT.\nWEIGHT\nGRAVITY LOADS:\nUNIFORMLY DISTRIBUTED LIVE LOADS:\nGROUND FLOOR LOBBY\n100 PSF.")


def s002_table():
    return getattr(ps, "abbreviation_table", lambda _t: {})(S002_TEXT)


class AValueBindsToTheSubjectItsRecordNames(unittest.TestCase):

    def test_a_dimension_its_record_does_not_name_as_the_subject_is_refused(self):
        self.assertFalse(gate("The ceiling height is 10'-0\".", A300))
        self.assertFalse(gate("ceiling height: 10'-0\".", A300))
        # A-300.00 names the floor, and binds the value as the floor's.
        self.assertTrue(gate("The second floor is 10'-0\".", A300))

    def test_a_record_naming_the_subject_binds_its_value(self):
        self.assertFalse(gate("The ceiling is 42\".", PARAPET))
        self.assertTrue(gate("parapet: 42.", PARAPET))
        self.assertTrue(gate("The parapet is 42\" high.", PARAPET))
        self.assertTrue(gate("There is a 42\" parapet.", PARAPET))

    def test_every_word_of_the_subject_is_named_where_the_value_is(self):
        """The records print CEILING beside 1/2" and 5/8": they name the
        ceiling, not its height."""
        self.assertFalse(gate("ceiling height: 1/2\".", METAL))
        self.assertFalse(gate("ceiling height: 5/8\".", METAL))
        self.assertTrue(gate("ceiling: 1/2\".", METAL))

    def test_a_clause_that_names_nothing_binds_nothing(self):
        self.assertFalse(gate("It is 42\".", PARAPET))
        self.assertFalse(gate("There are 42.", PARAPET))


class WhereTheValueIs(unittest.TestCase):

    def test_a_grid_without_an_identifier_names_a_cell_by_its_headers_not_another_cell(self):
        self.assertFalse(gate("ceiling height: 1'-4\".", [PARTITIONS]))
        self.assertTrue(gate("partition type 2: 1'-4\".", [PARTITIONS]))

    def test_a_grid_with_an_identifier_names_a_value_by_its_own_row(self):
        self.assertFalse(gate("DH-2 capacity is 15.0 kW.", [HEATER]))
        self.assertTrue(gate("DH-1 capacity is 15.0 kW.", [HEATER]))
        self.assertTrue(gate("The duct electric heater is 15.0 KW.", [HEATER]))

    def test_a_subject_is_a_word_never_part_of_one(self):
        stairs = [rec(sheet_number="A-104.00", quote="STAIRS 9'-0\" WIDE")]
        self.assertFalse(gate("air: 9'-0\".", stairs))
        self.assertTrue(gate("stair: 9'-0\".", stairs))


class AlternativeNames(unittest.TestCase):

    def test_the_sets_abbreviations_table_is_read_off_its_text_layer(self):
        self.assertEqual(s002_table(), {
            "ARCH.": ["ARCHITECTURAL"], "CFS": ["COLD FORMED STEEL"],
            "ELEV.": ["ELEVATION", "ELEVATOR"], "FT.": ["FEET", "FOOT"],
            "GA.": ["GAUGE"], "MTL.": ["METAL"], "WT.": ["WEIGHT"]})

    def test_an_alternative_name_binds_on_the_values_own_record(self):
        studs = [rec(sheet_number="S-101.00", file_id="ST", quote="6\" CFS STUDS @ 16\" O.C. 18 GA.")]
        table = s002_table()
        self.assertFalse(gate("stud gauge: 18.", studs))
        self.assertTrue(gate("stud gauge: 18.", studs, aliases={"ST": table}))
        self.assertTrue(gate("cold formed steel stud gauge: 18.", studs, aliases={"ST": table}))

    def test_a_table_names_only_in_its_own_files_drawings(self):
        studs = [rec(sheet_number="A-500.00", file_id="AR", quote="2 1/2\" CH STUDS 16\" O.C. 20 GA.")]
        self.assertFalse(gate("stud gauge: 20.", studs, aliases={"ST": s002_table()}))

    def test_an_alternative_name_printed_elsewhere_on_the_sheet_names_nothing(self):
        sheet = [rec(sheet_number="S-101.00", file_id="ST", ordinal=0, quote="6\" STUDS @ 16\" O.C. 18"),
                 rec(sheet_number="S-101.00", file_id="ST", ordinal=1, quote="ALL STUDS GA. PER SCHEDULE")]
        self.assertFalse(gate("stud gauge: 18.", sheet, aliases={"ST": s002_table()}))


class WhatDoesNotChange(unittest.TestCase):

    def test_other_intents_keep_the_union_and_a_count_keeps_its_rule(self):
        self.assertFalse(gate("The ceiling height is 10'-0\".", A300))
        self.assertTrue(gate("The ceiling height is 10'-0\".", A300, intent=""))
        self.assertTrue(gate("The ceiling height is 10'-0\".", A300, intent="identify"))
        qty = rec(sheet_number="M-200.00", record_type="schedule", quote="PTAC SCHEDULE UNIT NO. | QTY PTAC-1 | 21",
                  payload={"name": "PTAC SCHEDULE",
                           "columns": [{"header": "UNIT NO.", "role": "identifier"},
                                       {"header": "QTY", "role": "quantity"}],
                           "rows": [["PTAC-1", "21"]]})
        self.assertTrue(gate("There are 21 PTAC-1.", [qty], intent="count"))
        self.assertFalse(gate("There are 22 PTAC-1.", [qty], intent="count"))


class TheEvalStatesAnAttributeOfItsSubject(unittest.TestCase):

    CASE = {"id": "x", "question": "how high is the parapet", "subject": "parapet",
            "intent": "attribute", "attribute": "height", "kind": "answer",
            "expect": {"sheets": ["A-105.01"], "values": [42]}}

    def test_the_true_answer_names_the_subject(self):
        """42 printed only by a record that names no parapet: the union let
        "The drawings show 42." through; the true answer is the parapet's."""
        out = ev.score_case(self.CASE, [rec(sheet_number="A-105.01", quote="42 PERSONS")], {})
        self.assertFalse(out["checks"].get("gate_allows_the_true_answer"))
        out = ev.score_case(self.CASE, PARAPET, {})
        self.assertTrue(out["checks"].get("gate_allows_the_true_answer"))

    def test_the_ceiling_case_binds_no_printed_value(self):
        """Production's ceiling-height records, verbatim: every dimension they
        print is put to the gate as the ceiling height, and none binds."""
        import json
        suite = Path(__file__).resolve().parents[1] / "eval" / "boyland.json"
        case = next(c for c in json.loads(suite.read_text(encoding="utf-8"))["cases"]
                    if c["id"] == "ceiling-height")
        out = ev.score_case(case, A300 + METAL + [PARTITIONS], {})
        self.assertGreaterEqual(out["checks"]["printed_values_put_to_the_gate"], 5)
        self.assertIs(out["checks"]["no_value_binds"], True, out["reasons"])


if __name__ == "__main__":
    unittest.main()
