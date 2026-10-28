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
        # Nothing before the value: it states a value of nothing (ruling 6).
        self.assertFalse(gate("There is a 42\" parapet.", PARAPET))

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


SHED = [rec(sheet_number="SSP-003.00", record_type="legend_entry", file_id="SSP", quote="8' HIGH SHED",
            subject_terms=["8' HIGH SHED"])]
# M-001.00's GENERAL ABBREVIATIONS as production stores it: a VISION-read
# grid (source vision, verified False), its rows visibly misaligned.
M001 = rec(sheet_number="M-001.00", record_type="schedule", tier="vision_read", source="vision",
           file_id="MH", subject_terms=["GENERAL ABBREVIATIONS"],
           quote="GENERAL ABBREVIATIONS ABBREVIATION | MEANING CLG | CEILING HGT | HEIGHT GA | GAUGE DXF | ROOM",
           payload={"name": "GENERAL ABBREVIATIONS", "verified": False,
                    "columns": [{"header": "ABBREVIATION", "role": "identifier"},
                                {"header": "MEANING", "role": None}],
                    "rows": [["CLG", "CEILING"], ["HGT", "HEIGHT"], ["GA", "GAUGE"], ["DXF", "ROOM"]]})


class Ruling5EveryWordOfTheSubjectIsNamed(unittest.TestCase):
    """Ruling 2026-10-28 (5): every word of the subject must be named where
    the value is. 8' HIGH SHED names the shed, not the sidewalk shed."""

    def test_the_sidewalk_shed_is_not_named_by_high_shed(self):
        self.assertFalse(gate("sidewalk shed: 8.", SHED))
        self.assertFalse(gate("sidewalk shed: 8'.", SHED))
        self.assertFalse(gate("The sidewalk shed is 8' high.", SHED))

    def test_the_word_it_does_print_names_it(self):
        self.assertTrue(gate("shed: 8.", SHED))
        self.assertTrue(gate("The shed is 8' high.", SHED))


class Ruling6TheSubjectIsTheWordsBeforeTheValue(unittest.TestCase):
    """Ruling 2026-10-28 (6): the subject is the words before the value, and
    only those. Words after it are not required, and they never stand in for
    a subject: "a 42" parapet" names nothing before its value."""

    def test_trailing_words_are_not_required(self):
        self.assertTrue(gate("The parapet is 42\" high.", PARAPET))
        self.assertTrue(gate("parapet: 42\" above the roof.", PARAPET))

    def test_every_word_before_the_value_is(self):
        self.assertFalse(gate("The parapet height is 42\".", PARAPET))
        self.assertFalse(gate("The roof parapet is 42\".", PARAPET))

    def test_what_follows_the_value_never_stands_in_for_a_subject(self):
        self.assertFalse(gate("A 42\" parapet.", PARAPET))
        self.assertFalse(gate("42\" parapet.", PARAPET))
        self.assertFalse(gate("42\".", PARAPET))
        # A-302.00's fire-rated ceiling note names the ceiling; 5/8" is its
        # gypsum board, and "a 5/8" ceiling" bound on it as the ceiling's.
        note = [rec(sheet_number="A-302.00",
                    quote="1 HOUR FIRE RATED CEILING W/ ONE LAYER OF 5/8\" GYPSUM BOARD")]
        self.assertFalse(gate("A 5/8\" ceiling.", note))


class Ruling7AVisionTableNamesNothing(unittest.TestCase):
    """Ruling 2026-10-28 (7): M-001.00's vision-read abbreviations stay out.
    The alternative names come only from a text layer's table, handed in by
    file (aliases); a returned record's grid never lends one."""

    def test_a_vision_abbreviations_grid_among_the_records_names_nothing(self):
        recs = [M001, rec(sheet_number="M-101.00", file_id="MH", quote="8'-0\" CLG HGT")]
        self.assertFalse(gate("ceiling height: 8'-0\".", recs))
        self.assertFalse(gate("ceiling height: 8'-0\".", recs, aliases={}))
        self.assertTrue(gate("CLG HGT: 8'-0\".", recs))

    def test_the_text_layer_reader_reads_no_vision_grid(self):
        # A grid's quote is not a text layer's alternating lines.
        self.assertEqual(ps.abbreviation_table(M001["quote"]), {})


class Ruling8AndRuling9WhereAnAlternativeNameComesFrom(unittest.TestCase):

    def test_8_a_table_names_only_in_its_own_file(self):
        studs = [rec(sheet_number="A-500.00", file_id="AR", quote="2 1/2\" CH STUDS 16\" O.C. 20 GA.")]
        self.assertFalse(gate("stud gauge: 20.", studs, aliases={"ST": s002_table()}))
        self.assertTrue(gate("stud gauge: 20.", studs, aliases={"AR": s002_table()}))

    def test_9_the_agents_also_never_reaches_the_gate(self):
        """The gate takes the records, the intent and the file's own tables;
        no parameter carries the agent's other names, so none can bind."""
        params = inspect.signature(ps.answer_is_grounded).parameters
        self.assertEqual(list(params), ["text", "records", "intent", "aliases", "sources"])
        self.assertFalse(any(p.kind is p.VAR_KEYWORD for p in params.values()))
        src = inspect.getsource(ps._attribute_answer_is_bound) + inspect.getsource(ps._subject_bound)
        self.assertNotIn("also", src.replace("also\"", ""))


class Ruling12AGridWithoutAnIdentifier(unittest.TestCase):

    def test_a_cell_is_named_by_itself_its_headers_and_the_grids_name_only(self):
        # CEILING is in P1's cell, 1'-4" in P2's: no identifier column joins them.
        self.assertFalse(gate("ceiling: 1'-4\".", [PARTITIONS]))
        self.assertFalse(gate("ceiling height: 1'-4\".", [PARTITIONS]))
        # P2's own header names P2's cell.
        self.assertTrue(gate("partition type 2: 1'-4\".", [PARTITIONS]))
        # The grid's name ("TABLE") names every cell.
        self.assertTrue(gate("table: 1'-4\".", [PARTITIONS]))


# P-400.00's pump row as production stores it: ROOF MECH ROOM and 13 GPM in
# one identified row. It names the roof, and it is no count of anything.
PUMPS = rec(sheet_number="P-400.00", record_type="schedule", tier="schedule_cell", file_id="PL",
            subject_terms=["PUMP SCHEDULE"],
            quote="PUMP SCHEDULE MARK | LOCATION | GPM HWRP-1 | ROOF MECH ROOM | 13",
            payload={"name": "PUMP SCHEDULE",
                     "columns": [{"header": "MARK", "role": "identifier"},
                                 {"header": "LOCATION", "role": None},
                                 {"header": "GPM", "role": None}],
                     "rows": [["HWRP-1", "ROOF MECH ROOM", "13"]]})
# Z-001.01's zoning analysis: it names FIRST FLOOR beside its figures.
ZONING = rec(sheet_number="Z-001.01", file_id="ZN", subject_terms=["ZONING ANALYSIS"],
             quote="ZONING ANALYSIS FIRST FLOOR 8 DWELLING UNITS 16 PARKING 2")
PTAC_QTY = rec(sheet_number="M-200.00", record_type="schedule", file_id="MH",
               quote="PTAC SCHEDULE UNIT NO. | QTY PTAC-1 | 21",
               payload={"name": "PTAC SCHEDULE",
                        "columns": [{"header": "UNIT NO.", "role": "identifier"},
                                    {"header": "QTY", "role": "quantity"}],
                        "rows": [["PTAC-1", "21"]]})


class ACountNeverBindsThroughTheValuePath(unittest.TestCase):
    """Ruling 2026-10-28 (must-fix): a count claim never binds through the
    value path. Under intent=attribute it is decided by the count rule - its
    counting sources - or refused."""

    def test_a_record_naming_the_scope_is_no_count_of_what_is_on_it(self):
        self.assertFalse(gate("The roof has 13 EF-1.", [PUMPS]))
        self.assertFalse(gate("The roof has 13 exhaust fans.", [PUMPS]))
        self.assertFalse(gate("There are 13 HWRP-1.", [PUMPS]))
        self.assertFalse(gate("The first floor has 8 exhaust fans.", [ZONING]))
        self.assertFalse(gate("The first floor has 16 PTAC units.", [ZONING]))
        self.assertFalse(gate("The first floor has 2 EF-1 per the owner's set.", [ZONING]))
        self.assertFalse(gate("The first floor has 1 exhaust fan.", [ZONING]))

    def test_the_count_rule_decides_it_from_a_counting_source(self):
        self.assertTrue(gate("There are 21 PTAC-1.", [PTAC_QTY]))
        self.assertFalse(gate("There are 22 PTAC-1.", [PTAC_QTY]))
        for t in ("There are 21 PTAC-1.", "There are 22 PTAC-1.", "The roof has 13 EF-1."):
            self.assertEqual(gate(t, [PTAC_QTY, PUMPS]), gate(t, [PTAC_QTY, PUMPS], intent="count"), t)

    def test_a_value_of_the_thing_keeps_the_value_path(self):
        self.assertTrue(gate("HWRP-1: 13.", [PUMPS]))
        self.assertTrue(gate("HWRP-1 is 13 GPM.", [PUMPS]))
        self.assertTrue(gate("The roof mech room pump is 13 GPM.", [PUMPS]))
        self.assertTrue(gate("PTAC-1: 21.", [PTAC_QTY]))

    def test_what_states_a_count(self):
        counts = ["The roof has 13 EF-1.", "The first floor has 8 exhaust fans.",
                  "There are 36 type F doors.", "4A has 1 EF-1.", "The roof has 1 exhaust fan.",
                  "There are 5 A2.", "The roof has 2 PTAC units and 1 SAF-1."]
        values = ["parapet: 42.", "The parapet is 42 high.", "The heater is 15.0 KW.",
                  "The pump is 13 GPM.", "The roof is 1970 sq ft.", "The studs are 20 gauge.",
                  "PTAC-1: 21.", "There are 42.", "occupancy load: 10.", "16 O.C."]
        states = getattr(ps, "states_a_count", lambda _t: False)
        for c in counts:
            self.assertTrue(states(c), c)
        for v in values:
            self.assertFalse(states(v), v)


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
