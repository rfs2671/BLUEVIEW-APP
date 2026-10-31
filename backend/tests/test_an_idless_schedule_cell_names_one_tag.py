"""RULING 154 (Roy, 2026-10-30), interim and REFUSALS ONLY: a schedule with no
identifier column and tags in its headers (588 Boyland's A-400.00 WINDOW,
INTERIOR DOOR and EXTERIOR DOOR schedules: W1/W2/W3, NUMBER A-E, D1/D2) named
every cell by every header, so a digit under W3 "named" W1. A figure binds
through such a cell only for the tag its OWN column header prints; a cell whose
column prints no tag (or several) is named by none; the grid as a whole is
named by none. A schedule with an identifier column, or with no tag in its
headers, is named as before.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_search as S  # noqa: E402


def _sched(columns, rows, name="WINDOW SCHEDULE"):
    return {"record_type": "schedule", "sheet_number": "A-999.00", "quote": name + " " + " ".join(
        str(c) for r in rows for c in r), "payload": {
            "name": name, "columns": [{"header": h, "role": role} for h, role in columns], "rows": rows}}


IDLESS = _sched([("W1 NUMBER", None), ("", None), ("W2 NUMBER", None), ("", None)],
                [["bracket 11", "bracket 22", "bracket 33", "bracket 44"]])


def _ok(text, rec):
    return S.answer_is_grounded(text, [rec], intent="attribute")[0]


class AnIdlessCellNamesOneTag(unittest.TestCase):

    def test_the_cell_binds_for_its_own_columns_tag(self):
        self.assertTrue(_ok("W1 bracket 11.", IDLESS))
        self.assertTrue(_ok("W2 bracket 33.", IDLESS))

    def test_another_tags_cell_no_longer_binds(self):
        self.assertFalse(_ok("W1 bracket 33.", IDLESS))
        self.assertFalse(_ok("W2 bracket 11.", IDLESS))

    def test_a_cell_in_a_column_with_no_tag_binds_for_no_tag(self):
        self.assertFalse(_ok("W1 bracket 22.", IDLESS))
        self.assertFalse(_ok("W2 bracket 44.", IDLESS))

    def test_the_grid_as_a_whole_names_no_tag(self):
        # the quote prints every cell's figure; the headers name every tag
        self.assertFalse(_ok("W1 number 33.", IDLESS))
        self.assertFalse(_ok("W2 number 11.", IDLESS))

    def test_a_claim_naming_no_tag_is_step_threes(self):
        # step 2 left it bound on any cell; step 3 (tests/test_an_untagged_claim_needs_every_cell_of_its_family.py)
        # binds it only when every cell of the family prints the figure - here the four differ
        self.assertFalse(_ok("The window schedule bracket 22.", IDLESS))

    def test_the_real_a400_shape(self):
        rec = _sched([("W1 NUMBER", None), ("", None), ("W2 NUMBER", None), ("", None)],
                     [["ROUGH OPENING 5'-0\" 2'-6\"", "", "ROUGH OPENING 4'-0\"", ""]])
        self.assertTrue(_ok("W2 rough opening: 4'-0\".", rec))
        self.assertFalse(_ok("W1 rough opening: 4'-0\".", rec))

    def test_door_types_after_number(self):
        rec = _sched([("NUMBER A", None), ("", None), ("NUMBER B", None), ("", None)],
                     [["door leaf 36", "", "door leaf 32", ""]], name="INTERIOR DOOR SCHEDULE")
        self.assertTrue(_ok("Door B leaf 32.", rec))
        self.assertFalse(_ok("Door B leaf 36.", rec))

    def test_a_schedule_with_an_identifier_column_is_unchanged(self):
        rec = _sched([("TAG", "identifier"), ("W1 NOTE", None), ("W2 NOTE", None)],
                     [["EF-1", "bracket 11", "bracket 33"]], name="EXHAUST FAN SCHEDULE")
        self.assertTrue(_ok("EF-1 bracket 11.", rec))
        self.assertTrue(_ok("EF-1 bracket 33.", rec))

    def test_a_schedule_with_no_tag_in_its_headers_is_unchanged(self):
        rec = _sched([("DESCRIPTION", None), ("NOTES", None)], [["bracket 11", "bracket 22"]], name="LIGHTING SCHEDULE")
        self.assertTrue(_ok("Lighting bracket 11.", rec))
        self.assertTrue(_ok("Lighting bracket 22.", rec))

    def test_a_grid_printing_one_tag_is_unchanged(self):
        # a pump's SYMBOL WBP-1 over its GPM and HP: every cell is that one thing's
        rec = _sched([("SYMBOL WBP-1", None), ("PUMP GPM 47", None), ("HP 2", None)],
                     [["NOTES bracket 11", "", ""]], name="WATER BOOSTER SCHEDULE")
        self.assertTrue(_ok("WBP-1 pump gpm: 47.", rec))
        self.assertTrue(_ok("WBP-1 hp: 2.", rec))

    def test_a_ul_design_number_is_not_a_tag(self):
        assert hasattr(S, "_header_tags"), "not built: plan_search._header_tags"
        self.assertEqual(S._header_tags("WALL TYPE 1 W1 EXTERIOR STUD WALL UL DESIGN NO. U42"), ["W1"])

    def test_the_helpers(self):
        assert hasattr(S, "_header_tags"), "not built: plan_search._header_tags"
        self.assertEqual(S._header_tags("W1 NUMBER"), ["W1"])
        self.assertEqual(S._header_tags("NUMBER A"), ["A"])
        self.assertEqual(S._header_tags("MODEL"), [])
        self.assertEqual(S._strip_header_tags("D1 NUMBER"), "NUMBER")


if __name__ == "__main__":
    unittest.main()
