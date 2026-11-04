"""RULING 154, step 3 (Roy, 2026-10-30), REFUSALS ONLY: in a schedule with no
identifier column and two or more tags in its headers, a claim that names none of
the tags is about the whole family (A-400.00: "windows ...", "exterior doors
...") and binds only if EVERY cell of the family prints the figure (every tag
column AND every blank-header column; no adjacency attribution), or the family
is a single cell. The grid as a whole is no candidate. A claim that names a tag
(step 2), a grid that prints one tag, and a schedule with an identifier column
are decided as before.
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
    return {"record_type": "schedule", "sheet_number": "A-999.00",
            "quote": name + " " + " ".join(str(c) for r in rows for c in r),
            "payload": {"name": name, "columns": [{"header": h, "role": role} for h, role in columns], "rows": rows}}


COLS = [("W1 NUMBER", None), ("", None), ("W2 NUMBER", None), ("", None)]


def _ok(text, rec):
    return S.answer_is_grounded(text, [rec], intent="attribute")[0]


class AnUntaggedClaimNeedsEveryCellOfItsFamily(unittest.TestCase):

    def test_all_cells_agree_binds(self):
        rec = _sched(COLS, [["bracket 11", "bracket 11", "bracket 11", "bracket 11"]])
        self.assertTrue(_ok("Window bracket 11.", rec))

    def test_two_tags_that_differ_refuse(self):
        rec = _sched(COLS, [["bracket 11", "", "bracket 22", ""]])
        self.assertFalse(_ok("Window bracket 11.", rec))
        self.assertFalse(_ok("Window bracket 22.", rec))

    def test_a_blank_header_cell_is_a_candidate(self):
        rec = _sched(COLS, [["bracket 11", "bracket 22", "bracket 11", ""]])
        self.assertFalse(_ok("Window bracket 11.", rec))

    def test_a_single_cell_family_binds(self):
        rec = _sched(COLS, [["bracket 11", "", "tray 33", ""]])
        self.assertTrue(_ok("Window tray 33.", rec))
        self.assertTrue(_ok("Window bracket 11.", rec))

    def test_a_dimension_must_agree_too(self):
        rec = _sched(COLS, [["frame 4'-0\"", "", "frame 3'-0\"", ""]])
        self.assertFalse(_ok("Window frame 4'-0\".", rec))
        same = _sched(COLS, [["frame 4'-0\"", "", "frame 4'-0\"", ""]])
        self.assertTrue(_ok("Window frame 4'-0\".", same))

    def test_a_claim_naming_a_tag_is_step_two(self):
        rec = _sched(COLS, [["bracket 11", "", "bracket 22", ""]])
        self.assertTrue(_ok("W1 bracket 11.", rec))
        self.assertTrue(_ok("W2 bracket 22.", rec))

    def test_a_tag_claim_is_not_a_family_claim(self):
        # two cells under W1 that differ: "W1 ... 11" still binds on the one that prints it (step 2)
        rec = _sched(COLS, [["bracket 11", "", "x", ""], ["bracket 22", "", "x", ""]])
        self.assertTrue(_ok("W1 bracket 11.", rec))

    def test_a_claim_one_columns_header_names_is_column_specific(self):
        # "partition type 2" is P2's header words: step 2 decides it, not the family rule
        rec = _sched([("PARTITION TYPE 1 P1 STUD", None), ("PARTITION TYPE 2 P2 STUD", None)],
                     [["tray 11", "tray 22"]], name="TABLE")
        self.assertTrue(_ok("Partition type 2 tray 22.", rec))

    def test_the_whole_grid_is_no_candidate(self):
        rec = _sched(COLS, [["bracket 11", "", "bracket 11", ""]])
        self.assertFalse(_ok("Window schedule 22.", rec))

    def test_a_grid_printing_one_tag_is_unchanged(self):
        rec = _sched([("SYMBOL WBP-1", None), ("PUMP GPM 47", None), ("HP 2", None)],
                     [["tray 11", "", ""]], name="WATER BOOSTER SCHEDULE")
        self.assertTrue(_ok("Water booster pump gpm 47.", rec))

    def test_a_schedule_with_an_identifier_column_is_unchanged(self):
        rec = _sched([("TAG", "identifier"), ("W1 NOTE", None), ("W2 NOTE", None)],
                     [["EF-1", "bracket 11", "bracket 22"], ["EF-2", "bracket 33", "bracket 44"]],
                     name="EXHAUST FAN SCHEDULE")
        self.assertTrue(_ok("Exhaust fan EF-1 bracket 11.", rec))
        self.assertTrue(_ok("Exhaust fan bracket 11.", rec))   # one row prints it; rows are not a family

    def test_helpers(self):
        assert hasattr(S, "_idless_tags"), "not built: plan_search._idless_tags"
        assert hasattr(S, "_cells_agree"), "not built: plan_search._cells_agree"
        self.assertEqual(S._idless_tags(_sched(COLS, [["a"]])), {"W1", "W2"})
        self.assertEqual(S._idless_tags(_sched([("SYMBOL WBP-1", None)], [["a"]])), set())


if __name__ == "__main__":
    unittest.main()
