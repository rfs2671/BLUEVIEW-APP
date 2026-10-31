"""TYPE-BY-PANEL (Roy, 2026-10-30, after #938): on a sheet drawn as panels a printed
figure binds to a type only when its cell lies inside exactly one type's panel.

A-400.00 draws one panel per door and window type: its tag, its dimensioned drawing,
its info table beneath. Door types F and G sit in a second row UNDER D and E, so the
grid reads F's table in column "NUMBER D". #938 refused every value-path bind from the
sheet; this restores the ones in the type's own panel (120 of the 217 it refused, each
checked against the crop-read word boxes) and keeps the wrong ones refused:

  - a panel starts at its LABEL: the header cell over its column, or a body cell that is
    only a label ("NUMBER F") - from there down to the next label in that column;
  - a cell binds to the one tag whose panel holds it; a column with no tag, a label of
    several tags, or no label at all owns nothing - the claim refuses;
  - a claim that names NO type (a family claim), or states a bare tag-and-integer count,
    still needs a counting source on a panel sheet (the count rule is untouched).

The grids below are the real A-400.00 interior-door and window grids, shortened.
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

B = ""
DOOR_COLS = [("NUMBER A", None), ("", None), ("NUMBER B", None), ("", None), ("NUMBER C", None), ("", None),
             ("NUMBER D", None), ("", None), ("NUMBER E", None), ("", None)]
DOOR_ROWS = [
    ["3'-0\" FINISHED FLOOR", B, "3'-0\" FINISHED FLOOR", B, "3'-0\" FINISHED FLOOR", B,
     "APPLY EXPANDABLE SPRAY 3'-0\" FINISHED FLOOR", B, "3'-0\" FINISHED FLOOR", B],
    ["STAIRS EXIT DOOR", B, "APARTMENT ENTRANCE", B, "STORAGE ROOM", B, "INSULATED METAL SELF CLOSING", B, "INTERIOR ADA DOOR", B],
    ["SIZE", "3'-0\" X 7'-0\"", "SIZE", "3'-0\" X 7'-0\"", "SIZE", "3'-0\" X 7'-0\"", "SIZE", "3'-0\" X 7'-0\"", "SIZE", "3'-0\" X 6'-8\""],
    [B, B, B, B, B, B, "NUMBER F", B, "NUMBER G", B],
    [B, B, B, B, B, B, "2'-6\" FINISHED FLOOR", B, "VARIES FINISHED FLOOR", B],
    [B, B, B, B, B, B, "INTERIOR STANDARD DOOR TYPE STANDARD SIZE 2'-10\" X 6'-8\"", B,
     "INTERIOR CLOSED DOOR TYPE STANDARD SIZE G.C. TO DECIDE", B],
]
WIN_COLS = [("W1 NUMBER", None), ("", None), ("W2 NUMBER", None), ("", None), ("W3 NUMBER", None), ("", None)]
WIN_ROWS = [["APPLY EXPANDABLE 5'-0\" 2'-6\" FINISHED FLOOR", B, "APPLY EXPANDABLE 4'-0\" 5'-0\" FINISHED FLOOR", B,
             "APPLY EXPANDABLE 3'-0\" 5'-0\" FINISHED FLOOR", B],
            ["AIR INFILTRATION RATE: 0.20 U = 0.25", B, "AIR INFILTRATION RATE: 0.20 U = 0.25", B,
             "AIR INFILTRATION RATE: 0.20 U = 0.25", B]]


def _sched(columns, rows, sheet, name):
    return {"record_type": "schedule", "sheet_number": sheet,
            "quote": name + " " + " ".join(str(c) for r in rows for c in r),
            "payload": {"name": name, "columns": [{"header": h, "role": role} for h, role in columns], "rows": rows}}


def _ok(text, rec):
    return S.answer_is_grounded(text, [rec], intent="attribute")[0]


def _doors(sheet="A-400.00"):
    return _sched(DOOR_COLS, DOOR_ROWS, sheet, "INTERIOR DOOR SCHEDULE")


def _windows(sheet="A-400.00"):
    return _sched(WIN_COLS, WIN_ROWS, sheet, "WINDOW SCHEDULE")


class AnA400TypeBindsByItsPanel(unittest.TestCase):

    def test_the_second_row_of_panels_is_not_the_column_above_it(self):
        rec = _doors()
        # the finding: F's size is NOT type D's, E's or G's ...
        self.assertFalse(_ok("type D door INTERIOR STANDARD: 2'-10\" X 6'-8\".", rec))
        self.assertFalse(_ok("type E door INTERIOR STANDARD: 2'-10\" X 6'-8\".", rec))
        self.assertFalse(_ok("type G door INTERIOR STANDARD: 2'-10\" X 6'-8\".", rec))
        # ... it is type F's
        self.assertTrue(_ok("type F door INTERIOR STANDARD: 2'-10\" X 6'-8\".", rec))

    def test_the_fragments_of_the_wrong_type_stay_refused(self):
        rec = _doors()
        for n in ("2", "10", "6", "8"):
            self.assertFalse(_ok(f"type D door INTERIOR STANDARD: {n}.", rec), n)
            self.assertFalse(_ok(f"type G door INTERIOR STANDARD: {n}.", rec), n)

    def test_a_type_above_its_neighbours_label_keeps_its_own_cells(self):
        rec = _doors()
        self.assertTrue(_ok("Door D APPLY EXPANDABLE: 3'-0\".", rec))
        self.assertFalse(_ok("Door F APPLY EXPANDABLE: 3'-0\".", rec))       # D's drawing is not F's
        self.assertFalse(_ok("Door G APPLY EXPANDABLE: 3'-0\".", rec))

    def test_a_window_figure_binds_in_its_own_panel_only(self):
        rec = _windows()
        self.assertTrue(_ok("W1 APPLY EXPANDABLE: 5'-0\".", rec))
        self.assertTrue(_ok("W2 APPLY EXPANDABLE: 4'-0\".", rec))
        self.assertTrue(_ok("W3 APPLY EXPANDABLE: 3'-0\".", rec))
        self.assertFalse(_ok("W1 APPLY EXPANDABLE: 4'-0\".", rec))
        self.assertFalse(_ok("W3 APPLY EXPANDABLE: 4'-0\".", rec))
        self.assertTrue(_ok("W2 AIR INFILTRATION: 0.25.", rec))

    def test_a_claim_that_names_no_type_still_needs_a_counting_source(self):
        # #938's refusal, kept: a family claim would have to hold in every panel
        self.assertFalse(_ok("Window APPLY EXPANDABLE: 5'-0\".", _windows()))
        self.assertFalse(_ok("Door APPLY EXPANDABLE: 3'-0\".", _doors()))

    def test_a_bare_tag_and_integer_is_a_count_and_needs_a_counting_source(self):
        rec = _doors()
        for c in ("Door D: 3.", "Door B: 3.", "Door C: 7.", "Door E: 6.", "Door D: 0."):
            self.assertFalse(_ok(c, rec), c)
        # the same words on another sheet are not under the panel-sheet rule
        self.assertTrue(_ok("Door D: 3.", _doors("A-401.00")))

    def test_a_fragment_of_a_dimension_refuses_in_every_panel(self):
        # Roy 2026-10-31: whole printed dimensions only; the 5 of 5'-0", the 10 of 2'-10" are fragments
        w, d = _windows(), _doors()
        for n in ("5", "0", "2", "6"):
            self.assertFalse(_ok(f"W1 APPLY EXPANDABLE: {n}.", w), n)
        for n in ("2", "10", "6", "8"):
            self.assertFalse(_ok(f"type F door INTERIOR STANDARD: {n}.", d), n)
        # the whole dimension and the whole decimal bind
        self.assertTrue(_ok("W1 APPLY EXPANDABLE: 5'-0\".", w))
        self.assertTrue(_ok("W2 AIR INFILTRATION: 0.25.", w))
        self.assertTrue(_ok("type F door INTERIOR STANDARD: 2'-10\" X 6'-8\".", d))

    def test_a_confirmed_count_still_binds(self):
        rec = _windows()
        with mock.patch.object(S, "_located_tags", return_value={"W2"}), \
                mock.patch.object(S, "_count_answer_is_bound", return_value=(True, [])), \
                mock.patch.object(S, "_every_track_states_it", return_value=True):
            self.assertTrue(_ok("W2: 4.", rec))

    def test_the_cells_of_a_tagless_column_own_nothing(self):
        rec = _doors()
        # the odd columns carry no tag: the size printed in A's value column names no type
        self.assertFalse(_ok("type B door SIZE: 3'-0\" X 7'-0\".", rec))

    def test_the_panel_sheets_are_named(self):
        self.assertIn("A-400.00", getattr(S, "_PANEL_SHEETS", ()))
        is_panel = getattr(S, "_is_panel_sheet", lambda r: None)
        self.assertTrue(is_panel({"sheet_number": " a-400.00 "}))
        self.assertFalse(is_panel({"sheet_number": "A-500.00"}))


class APanelIsDerivedFromTheLayoutNotTheSheet(unittest.TestCase):
    """The same rule on a synthetic layout that is not A-400: a top row M1 M2 M3, a second row started by
    labels under M2 and M3 (N4, N5), and a third under N5 (N6)."""

    COLS = [("M1 MARK", None), ("", None), ("M2 MARK", None), ("", None), ("M3 MARK", None), ("", None)]
    ROWS = [
        ["WIDTH 11", B, "WIDTH 22", B, "WIDTH 33", B],
        [B, B, "N4 MARK", B, "N5 MARK", B],
        [B, B, "WIDTH 44", B, "WIDTH 55", B],
        [B, B, B, B, "N6 MARK", B],
        [B, B, B, B, "WIDTH 66", B],
    ]

    def rec(self, rows=None):
        return _sched(self.COLS, rows or self.ROWS, "A-999.00", "FRAME SCHEDULE")

    def test_panel_regions(self):
        f = getattr(S, "_panel_tags", None)
        self.assertIsNotNone(f)
        got = f([S._header_tags(h) for h, _r in self.COLS], self.ROWS)
        self.assertEqual([r[2] for r in got], ["M2", "N4", "N4", "N4", "N4"])
        self.assertEqual([r[4] for r in got], ["M3", "N5", "N5", "N6", "N6"])
        self.assertEqual([r[0] for r in got], ["M1"] * 5)

    def test_each_figure_binds_to_the_one_panel_that_holds_it(self):
        r = self.rec()
        for tag, w in (("M1", 11), ("M2", 22), ("M3", 33), ("N4", 44), ("N5", 55), ("N6", 66)):
            self.assertTrue(_ok(f"{tag} WIDTH: {w}.", r), tag)
        for tag, w in (("M2", 44), ("M3", 55), ("N5", 66), ("N4", 22), ("N5", 33), ("M1", 66)):
            self.assertFalse(_ok(f"{tag} WIDTH: {w}.", r), (tag, w))

    def test_a_label_of_two_types_leaves_its_panel_unowned(self):
        rows = [["WIDTH 11", B, "WIDTH 22", B, "WIDTH 33", B],
                [B, B, "N4 N5 MARK", B, B, B],
                [B, B, "WIDTH 44", B, B, B]]
        r = self.rec(rows)
        self.assertTrue(_ok("M2 WIDTH: 22.", r))
        for tag in ("M2", "N4", "N5"):
            self.assertFalse(_ok(f"{tag} WIDTH: 44.", r), tag)

    def test_a_header_over_two_types_owns_nothing(self):
        cols = self.COLS + [("M7 M8 MARK", None)]
        rows = [["WIDTH 11", B, "WIDTH 22", B, "WIDTH 33", B, "WIDTH 99"]]
        r = _sched(cols, rows, "A-999.00", "FRAME SCHEDULE")
        self.assertTrue(_ok("M1 WIDTH: 11.", r))
        for tag in ("M7", "M8"):
            self.assertFalse(_ok(f"{tag} WIDTH: 99.", r), tag)

    def test_only_a_label_starts_a_panel(self):
        for stray in ("N4", "N4 NOTE", "TYPE N4.P.S.C"):
            rows = [["WIDTH 11", B, "WIDTH 22", B, "WIDTH 33", B], [B, B, stray, B, B, B],
                    [B, B, "WIDTH 44", B, B, B]]
            r = self.rec(rows)
            self.assertTrue(_ok("M2 WIDTH: 44.", r), stray)
            self.assertFalse(_ok("N4 WIDTH: 44.", r), stray)


if __name__ == "__main__":
    unittest.main()
