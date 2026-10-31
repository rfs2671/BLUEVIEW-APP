"""ROLE-SPLIT FINDING 2026-10-30 (crop-read of AR 3.28.25 p23), REFUSALS ONLY:
A-400.00 is not a column table. Each door and window type has its own panel;
F and G sit in a second row under D and E, so the grid read F's info table as
column "NUMBER D": "INTERIOR STANDARD, 2'-10" X 6'-8"" (type F's) bound to D and
to A. Roy's standing instruction: refuse EVERY A-400 own-column bind that no
counting source confirms, until the type-by-panel mapping is built (a later PR).

A figure read from A-400.00 through a cell's own column therefore does not bind.
A count the count rule binds from a counting source (W2 5, W3 2: the glyph
census) still binds, exactly as before. Another sheet's tag-headed grid keeps its
own-column naming (ruling 154 step 2).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_search as S  # noqa: E402

COLS = [("W1 NUMBER", None), ("", None), ("W2 NUMBER", None), ("", None)]
ROWS = [["ROUGH OPENING 5'-0\" 2'-6\"", "", "ROUGH OPENING 4'-0\" 5", ""]]
DCOLS = [("NUMBER D", None), ("", None), ("NUMBER E", None), ("", None)]
DROWS = [["SIZE 2'-10\" X 6'-8\"", "", "SIZE 3'-0\" X 6'-8\"", ""]]


def _sched(columns, rows, sheet, name="WINDOW SCHEDULE"):
    return {"record_type": "schedule", "sheet_number": sheet,
            "quote": name + " " + " ".join(str(c) for r in rows for c in r),
            "payload": {"name": name, "columns": [{"header": h, "role": role} for h, role in columns],
                        "rows": rows}}


def _ok(text, rec):
    return S.answer_is_grounded(text, [rec], intent="attribute")[0]


class AnA400OwnColumnNeedsACountingSource(unittest.TestCase):

    def test_a_window_figure_through_its_own_column_refuses(self):
        rec = _sched(COLS, ROWS, "A-400.00")
        self.assertFalse(_ok("W2 rough opening: 4'-0\".", rec))
        self.assertFalse(_ok("W1 rough opening: 5'-0\".", rec))

    def test_the_wrong_door_binding_refuses(self):
        # the real finding: F's size read as column D's
        rec = _sched(DCOLS, DROWS, "A-400.00", "INTERIOR DOOR SCHEDULE")
        self.assertFalse(_ok("Door D size: 2'-10\" X 6'-8\".", rec))
        self.assertFalse(_ok("Door E size: 3'-0\" X 6'-8\".", rec))

    def test_the_same_grid_on_another_sheet_keeps_its_own_column(self):
        rec = _sched(COLS, ROWS, "A-401.00")
        self.assertTrue(_ok("W2 rough opening: 4'-0\".", rec))
        self.assertFalse(_ok("W1 rough opening: 4'-0\".", rec))
        rec = _sched(DCOLS, DROWS, "A-401.00", "INTERIOR DOOR SCHEDULE")
        self.assertTrue(_ok("Door D size: 2'-10\" X 6'-8\".", rec))

    def test_a_confirmed_count_still_binds(self):
        rec = _sched(COLS, ROWS, "A-400.00")
        with mock.patch.object(S, "_located_tags", return_value={"W2"}), \
                mock.patch.object(S, "_count_answer_is_bound", return_value=(True, [])), \
                mock.patch.object(S, "_every_track_states_it", return_value=True):
            self.assertTrue(_ok("W2: 5.", rec))

    def test_an_unconfirmed_count_refuses(self):
        rec = _sched(COLS, ROWS, "A-400.00")
        with mock.patch.object(S, "_located_tags", return_value={"W2"}), \
                mock.patch.object(S, "_count_answer_is_bound", return_value=(False, ["5"])):
            self.assertFalse(_ok("W2: 5.", rec))

    def test_a_confirmed_count_never_binds_a_figure_the_cell_does_not_print(self):
        # the counting source confirms; the value path (own column, as before) must still agree
        rec = _sched(COLS, ROWS, "A-400.00")
        with mock.patch.object(S, "_located_tags", return_value={"W2"}), \
                mock.patch.object(S, "_count_answer_is_bound", return_value=(True, [])), \
                mock.patch.object(S, "_every_track_states_it", return_value=True):
            self.assertFalse(_ok("W2: 9.", rec))

    def test_the_unmapped_sheets_are_named(self):
        self.assertIn("A-400.00", S._OWN_COLUMN_UNMAPPED_SHEETS)
        self.assertTrue(S._own_column_unmapped({"sheet_number": " a-400.00 "}))
        self.assertFalse(S._own_column_unmapped({"sheet_number": "A-500.00"}))

    def test_a_grid_printing_one_tag_or_with_an_identifier_is_unchanged(self):
        pump = _sched([("SYMBOL WBP-1", None), ("PUMP GPM 47", None), ("HP 2", None)],
                      [["tray 11", "", ""]], "A-400.00", "WATER BOOSTER SCHEDULE")
        self.assertTrue(_ok("WBP-1 pump gpm: 47.", pump))
        ident = _sched([("TAG", "identifier"), ("W1 NOTE", None), ("W2 NOTE", None)],
                       [["EF-1", "bracket 11", "bracket 33"]], "A-400.00", "EXHAUST FAN SCHEDULE")
        self.assertTrue(_ok("EF-1 bracket 11.", ident))


if __name__ == "__main__":
    unittest.main()
