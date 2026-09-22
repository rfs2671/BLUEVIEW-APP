"""A SCHEDULE'S COLUMN HEADINGS WERE READ AS ITS TITLE, AND A DATA ROW TOOK
THEIR PLACE. THE FIRST FIX FOR THAT LOST EVERY TITLE THAT FILLED HALF A ROW.

`_title_and_body` accepted any top row with NO DIGIT ANYWHERE as the
schedule's title, on the reasoning that "a title reads as words; a data row
reads as values". Column headings read as words too.

── MEASURED ON SP-003.00 ──────────────────────────────────────────────────

The sheet was rendered and read. It prints exactly three bands, and
`plan_text.ruled_grids` finds exactly 3 x 14, so the grid detection was right.

    r0  12/14 filled   CENTRAL MODEL | RELIABLE MANUFACTURER'S | VIKING No.
                       | PLAN DESIGNATION SYMBOL | ... | THIRD FLOOR |
                       TOTAL HEADS FOURTH FLOOR
    r1   4/14 filled   RFC49   | 256 SQ.FT. (16FTx16FT) |  7 |  8
    r2   4/14 filled   F1RES44 | 256 SQ.FT.             | 16 |  4

No digit in r0, so r0 became the TITLE and r1, a data row, became the COLUMN
HEADINGS. The RFC49 sprinkler, 7 heads on the third floor and 8 on the
fourth, was not in the record at all. The same on SP-002.00 and SP-004.00.

── THE FIRST FIX, AND WHAT IT BROKE ───────────────────────────────────────

Density alone, "a title fills fewer than half the cells", recovered those and
was written up as 82 -> 88 rows with no schedule losing one. Both true, and
the tests said so, because they COUNTED ROWS. Compared on names and columns
it had lost five titles that fill exactly half a row or more (DUCT ELECTRIC
HEATER is 3 of 6) and merged them into the column names, and two of its six
"recovered" rows on P-400.00 were its heading row and a note, demoted to
data. That is why the property below compares the whole structure.

── WHAT A CAPTION IS ──────────────────────────────────────────────────────

A caption is one piece of text over the table, cut wherever its words fall.
A heading row names the columns, so it fills more cells than the caption
over it. A data row is neither and is never the comparison. See
`plan_ocr._title_and_body` for the four rules.

── WHAT THESE TESTS ARE BUILT ON: PRODUCTION'S OWN READ ────────────────────

`ocr_grid_tables.json` holds, for all 30 ocr_grid schedules on the 173-page
corpus, the MERGED TABLE `schedule_from_table` is handed: both renders read,
disagreeing cells marked. It was read 2026-09-22 in a container built to the
deployment that OCR'd the corpus (6eea5ba4: pdftoppm 25.03.0 measured from its
startup log; poppler-utils 25.03.0-5+deb13u4, onnxruntime 1.30.0,
opencv-python 4.14.0.94 and the base image inferred), network off, running
production's own _render_pdf_crop and _ocr_blind_grids.

`faithful` is true for the 27 whose read the code production ran (plan_ocr at
f8fd7cfa) turns into EXACTLY what production stored, contested readings
included. The other 3 (EN-001.00, M-202.00, P-400.00 WATER BOOSTER) differ
from production by a contested cell's text. They stay in the file, and NOTHING
IS PINNED ON THEM.

THE FIXTURE THIS REPLACED was a PyMuPDF single-read capture. On P-400.00's
rough-in schedule it put the note in ONE cell where production's read has
TWO, and the test built on it pinned a right answer for a read production
never made: with production's read the title became the column names. See
`plan_ocr._title_and_body` rule (4).
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_ocr  # noqa: E402

TABLES = json.loads(
    (Path(__file__).resolve().parent / "ocr_grid_tables.json")
    .read_text(encoding="utf-8"))
FAITHFUL = [x for x in TABLES if x["faithful"]]
NOT_FAITHFUL = {("EN-001.00", (16, 11)), ("M-202.00", (13, 3)),
                ("P-400.00", (3, 9))}

GRID = {"bbox": [0.0, 0.0, 100.0, 100.0]}

# The value pattern as it was, before a dimension in inches counted as a value.
_OLD_VALUE_CELL = re.compile(r"^[\d.,/\-]+$")


def _old_title_and_body(table):
    """The predicate as it was before either fix. Kept so the properties
    below compare two structurings of the SAME table rather than a number
    from a report."""
    if not table:
        return "", []
    first = table[0]
    filled = [c for c in first if c]
    if len(filled) == 1 and len(table) > 2:
        return re.sub(r"\s+", " ", filled[0]).strip(), table[1:]
    if len(filled) >= 2 and len(table) > 1:
        joined = " ".join(filled)
        if not re.search(r"\d", joined) or len(filled) < len(first) * 0.5:
            return re.sub(r"\s+", " ", joined).strip(), table[1:]
    return "", table


def _density_only_title_and_body(table):
    """The first fix: density alone. Kept to show what the walk repairs."""
    if not table:
        return "", []
    first = table[0]
    filled = [c for c in first if c]
    if len(filled) == 1 and len(table) > 2:
        return re.sub(r"\s+", " ", filled[0]).strip(), table[1:]
    if len(filled) >= 2 and len(table) > 1:
        if len(filled) < len(first) * 0.5:
            return re.sub(r"\s+", " ", " ".join(filled)).strip(), table[1:]
    return "", table


def _structure(table, title_fn, value_cell=None):
    """schedule_from_table, then read_grid_twice's own post-step: a contested
    marker never names a schedule. That is what production stores."""
    saved = plan_ocr._title_and_body, plan_ocr._VALUE_CELL
    try:
        plan_ocr._title_and_body = title_fn
        if value_cell is not None:
            plan_ocr._VALUE_CELL = value_cell
        sched = plan_ocr.schedule_from_table([list(r) for r in table], GRID)
    finally:
        plan_ocr._title_and_body, plan_ocr._VALUE_CELL = saved
    name = (sched or {}).get("name") or ""
    if plan_ocr.CONTESTED_CELL in name:
        sched["name"] = " ".join(name.replace(plan_ocr.CONTESTED_CELL, " ").split())
        sched["name_partly_unread"] = True
    return sched


def _old(table):
    return _structure(table, _old_title_and_body, _OLD_VALUE_CELL)


def _new(table):
    return _structure(table, plan_ocr._title_and_body)


def _rows(sched):
    return len((sched or {}).get("rows") or [])


def _shape(sched):
    s = sched or {}
    return s.get("name") or "", s.get("columns") or [], s.get("rows") or []


def _key(x):
    return x["sheet"], tuple(x["grid"])


def _table(sheet, grid):
    for x in TABLES:
        if _key(x) == (sheet, tuple(grid)):
            return x["table"]
    raise AssertionError(f"no captured table for {sheet} {grid}")


class TheSprinklerScheduleKeepsBothItsSprinklers(unittest.TestCase):
    """SP-003.00, the case that was rendered and read."""

    def setUp(self):
        self.table = _table("SP-003.00", [3, 14])

    def test_the_grid_really_is_three_bands(self):
        """Stated so a future reader does not go looking for a missing row in
        `ruled_grids`. The sheet prints one heading band and two sprinklers."""
        self.assertEqual(len(self.table), 3)
        self.assertEqual(len(self.table[0]), 14)

    def test_the_heading_row_is_not_taken_as_the_title(self):
        self.assertEqual(_new(self.table)["name"], "")

    def test_both_sprinkler_rows_survive(self):
        sched = _new(self.table)
        self.assertEqual([r[0] for r in sched["rows"]], ["RFC49", "F1RES44"])

    def test_the_head_counts_are_in_the_record(self):
        """The reason this matters. 7 and 8 are the third- and fourth-floor
        head counts for RFC49, and they were absent from the corpus."""
        rfc = next(r for r in _new(self.table)["rows"] if r[0] == "RFC49")
        self.assertEqual(rfc[-2:], ["7", "8"])

    def test_the_columns_are_headings_and_not_data(self):
        """VIKING No. and THIRD FLOOR are printed; production's two reads
        disagreed on both, so they are `(readings disagree)` here."""
        cols = [c for c in _new(self.table)["columns"] if c]
        self.assertIn("PLAN DESIGNATION SYMBOL", cols)
        self.assertIn("TOTAL HEADS FOURTH FLOOR", cols)
        self.assertNotIn("RFC49", cols)

    def test_the_old_predicate_reproduces_the_defect(self):
        """A regression test proves nothing unless the thing it guards
        against can still be demonstrated."""
        sched = _old(self.table)
        self.assertEqual(_rows(sched), 1)
        self.assertIn("RFC49", sched["columns"])


class ACaptionIsSparseRelativeToTheHeadingsUnderIt(unittest.TestCase):
    """The property, on synthetic tables so the shape is unmistakable. Every
    first row here is digit-free, so none of it is the digit test at work.
    The data rows carry a value (a CFM), as every equipment schedule's do;
    a data row of nothing but words is a different question, asked by
    test_a_row_of_prose_is_data_not_a_heading."""

    HEADINGS = ["TAG", "TYPE", "LOCATION", "CFM"]
    DATA = [["EF-1", "INLINE", "BATH", "50"],
            ["EF-2", "CABINET", "KITCHEN", "100"]]

    def test_no_digit_in_any_first_row(self):
        for t in (self.dense(), self.half(), self.sparse(), self.noted()):
            self.assertFalse(re.search(r"\d", " ".join(t[0])),
                             "the fixture no longer isolates the digit test")

    def dense(self):
        return [self.HEADINGS] + self.DATA

    def sparse(self):
        """Fewer than half, with NO heading row under it to compare with:
        rule (3), standing alone, as on P-400.00's WATER BOOSTER PUMP."""
        return [["", "EXHAUST", "", "FAN", "", "SCHEDULE", "", ""],
                ["EF-1", "INLINE", "BATH", "50", "", "", "", ""]]

    def half(self):
        """Exactly half the cells, as M-200.00's DUCT ELECTRIC HEATER is."""
        return [["EXHAUST FAN", "", "SCHEDULE", ""],
                self.HEADINGS] + self.DATA

    def noted(self):
        """A one-cell note between caption and headings, as on P-400.00."""
        return [["EXHAUST", "", "FAN SCHEDULE", ""],
                ["", "VERIFY ALL MODELS WITH OWNER", "", ""],
                self.HEADINGS] + self.DATA

    def test_a_dense_heading_row_becomes_the_columns(self):
        sched = _new(self.dense())
        self.assertEqual(_shape(sched), ("", self.HEADINGS, self.DATA))

    def test_the_old_predicate_ate_the_dense_one(self):
        self.assertEqual(_old(self.dense())["name"], "TAG TYPE LOCATION CFM")

    def test_a_sparse_caption_is_a_title_with_nothing_to_compare(self):
        name, _, rows = _shape(_new(self.sparse()))
        self.assertEqual(name, "EXHAUST FAN SCHEDULE")
        self.assertEqual(rows[0][0], "EF-1")

    def test_a_caption_filling_exactly_half_is_still_a_title(self):
        """What density alone got wrong: half is not "fewer than half", and
        the caption was merged into the column names."""
        self.assertEqual(_shape(_new(self.half())),
                         ("EXHAUST FAN SCHEDULE", self.HEADINGS, self.DATA))
        broken = _structure(self.half(), _density_only_title_and_body)
        self.assertEqual(broken["name"], "")
        self.assertEqual(broken["columns"][0], "EXHAUST FAN TAG")

    def test_a_note_under_the_caption_does_not_make_the_caption_a_heading(self):
        """Compared only with the row directly under it (one cell), the
        caption looks dense. Walked down to the headings, it is not."""
        name, columns, rows = _shape(_new(self.noted()))
        self.assertEqual(name,
                         "EXHAUST FAN SCHEDULE VERIFY ALL MODELS WITH OWNER")
        self.assertEqual((columns, rows), (self.HEADINGS, self.DATA))

    def banded(self):
        """A TWO-cell note band between caption and headings: the shape of
        production's read of P-400.00's rough-in schedule."""
        return [["EXHAUST", "", "FAN SCHEDULE", ""],
                ["SIZES AS REQUIRED FOR PARTICULAR FIXTURES.",
                 "VERIFY ALL MODEL NUMBERS WITH OWNER", "", ""],
                self.HEADINGS] + self.DATA

    def test_a_two_cell_note_band_does_not_make_the_caption_a_heading(self):
        """Rule (4). The band is not a heading row, so the caption's rule (2)
        used to compare with it, find nothing, and make the CAPTION the column
        names. Now the band is skipped to the headings under it."""
        name, columns, rows = _shape(_new(self.banded()))
        self.assertEqual(name, "EXHAUST FAN SCHEDULE SIZES AS REQUIRED FOR "
                               "PARTICULAR FIXTURES. VERIFY ALL MODEL NUMBERS "
                               "WITH OWNER")
        self.assertEqual((columns, rows), (self.HEADINGS, self.DATA))

    def test_a_two_tier_heading_is_not_a_note_band(self):
        """MORE cells, not as many: an upper tier filling as many cells as the
        tier under it is a heading tier, merged by schedule_from_table."""
        table = [["FAN", "SCHEDULE", ""], ["TAG", "MOTOR DATA", ""],
                 ["", "HP", "VOLTS"], ["SAF-1", "1/3", "208"]]
        self.assertFalse(plan_ocr._is_note_band(table, 1))
        self.assertEqual(_new(table)["columns"], ["TAG", "MOTOR DATA HP", "VOLTS"])

    def test_a_blank_top_band_means_no_caption(self):
        """A caption is printed at the top. A stray mark under a blank band
        is not lifted into the name."""
        table = [["", "", "", ""], ["", "PTAC-1", "", ""],
                 ["", "", "", ""], ["", "X", "", ""]]
        self.assertEqual(plan_ocr._title_and_body(table), ("", table))


class ProductionsReadOfTheRoughInSchedule(unittest.TestCase):
    """P-400.00's PLUMBING ROUGH-IN SCHEDULE as production read it: title,
    a note band in TWO cells, then the headings."""

    def setUp(self):
        self.table = _table("P-400.00", [13, 6])

    def test_the_read_really_has_a_two_cell_note_band(self):
        band = [c for c in self.table[1] if c]
        self.assertEqual(len(band), 2)
        self.assertTrue(band[0].startswith("SIZES OR AS REQUIRED"))
        self.assertTrue(band[1].startswith("VERIFY ALL MODEL NUMBERS"))
        self.assertTrue(plan_ocr._is_note_band(self.table, 1))

    def test_the_headings_are_the_columns(self):
        sched = _new(self.table)
        self.assertEqual(sched["columns"],
                         ["FIXTURES", "ABBR", "H.W.", "C.W.", "WASTE", "VENT"])
        self.assertEqual(sched["rows"][0][0], "LAVATORIES")
        self.assertEqual(_rows(sched), 10)
        self.assertTrue(sched["name"].startswith("PLUMBING ROUGH-IN SCHEDULE"))

    def test_without_rule_4_the_title_becomes_the_columns(self):
        """The defect, still demonstrable: rule (4) switched off."""
        saved = plan_ocr._is_note_band
        plan_ocr._is_note_band = lambda table, i: False
        try:
            sched = _new(self.table)
        finally:
            plan_ocr._is_note_band = saved
        self.assertEqual(sched["name"], "")
        self.assertEqual(sched["columns"],
                         ["PLUMBING", "", "ROUGH-IN", "", "SCHEDULE", ""])
        self.assertEqual(_rows(sched), 12)


class ADimensionIsAValue(unittest.TestCase):
    """A pipe size is data. Without the inch mark P-400.00's LAVATORIES row
    read as a second band of headings and was merged into the columns."""

    def test_inch_and_foot_marks(self):
        for cell in ('1/2"', '1-1/4"', "6”", "4'", "12", "7'-2\"",
                     '3",4"', "--", '"'):
            self.assertTrue(plan_ocr._VALUE_CELL.match(cell), cell)

    def test_a_heading_is_still_a_heading(self):
        for cell in ("KW", "H.W.", 'SIZE "A"', "1/2 IN"):
            self.assertFalse(plan_ocr._VALUE_CELL.match(cell), cell)

    def test_the_fixture_row_is_data(self):
        self.assertFalse(plan_ocr._is_heading_row(
            ["LAVATORIES", "LAV", '1/2"', '1/2"', '1-1/4"', '1-1/4"']))


# ── EVERY TABLE THIS CHANGE TOUCHES, AND WHAT IT BECOMES ─────────────────
#
# Row counts cannot tell an improvement from damage: the first fix scored +2
# on P-400.00 by demoting its heading row to data. So each changed table is
# listed with the reason, and checked against the RENDERED SHEET (PyMuPDF
# crop of pdfplumber's grid rect, 2026-09-21: SP - 6.24.26 pp2-4, FA -
# 6.30.26 p1, PL - 6.29.26 p20).
CHANGED = {
    ("SP-002.00", (3, 14)): (
        "improved. Printed: one heading band, RFC49 16/7 and F1RES44 9/16. "
        "Stored: the same"),
    ("SP-003.00", (3, 14)): (
        "improved. Printed: RFC49 7/8, F1RES44 16/4. Stored: the same"),
    ("SP-004.00", (3, 14)): (
        "improved. Printed: RFC49 3/6, F1RES44 20/blank. Stored: the same"),
    ("FA-001", (9, 12)): (
        "improved, NOT CORRECT. Printed: A-L over EIGHT device rows. Stored: "
        "seven; '1 MANUAL PULL STATION' is merged into the first column name "
        "by schedule_from_table's one-extra-band merge. The grid also has 12 "
        "columns where 13 are printed, so L is missing: a grid defect, "
        "untouched here"),
    ("P-400.00", (13, 6)): (
        "improved. Printed: title, a three-line note, FIXTURES | ABBR | H.W. "
        "| C.W. | WASTE | VENT, nine fixtures and a NOTE row. Production's "
        "read puts the note's last two lines in TWO cells; rule (4) skips that "
        "band, so the headings are the columns and ten rows stay ten. Without "
        "rule (4) the TITLE became the columns and rows went 10 -> 12. The "
        "note's first line never reached the OCR table"),
    ("P-400.00", (2, 3)): (
        "WORSE. Printed: 'STORAGE TANK SCHEDULE' and an ST # tag box over ONE "
        "unruled key/unit/value block, which lands in one cell. With one "
        "one-cell row under it there is no heading row to compare with, and "
        "FA-001 is the same shape (its dots are graphics), so naming it would "
        "take a rule keyed on row count: a guess. The old rule named it only "
        "because it has no digit. The fix belongs in reading that layout"),
}

EXPECTED = {
    ('SP-003.00', (3, 14)): ('',
        ['', '(readings disagree)', '(readings disagree)', '(readings disagree)', '', 'PLAN DESIGNATION SYMBOL', 'CONCEALED RESIDENTIAL', 'SPRINKLER UPRIGHT', 'PENDENT CONCEALED', 'SIDEWALL DRY', '(readings disagree)', 'MAXIMUM SPRINKLER COVERAGE AREA', '(readings disagree)', 'TOTAL HEADS FOURTH FLOOR']),
    ('FA-001', (9, 12)): ('',
        ['1 MANUAL PULL STATION', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', '', 'J', 'K']),
    ('P-400.00', (13, 6)): ("PLUMBING ROUGH-IN SCHEDULE SIZES OR AS REQUIRED FOR PARTICULAR FIXTURES. VERIFY ALL MODEL NUMBERS WITH OWNER OWNERS'S REP AD ARCH, PRIOR TO ORDERING.",
        ['FIXTURES', 'ABBR', 'H.W.', 'C.W.', 'WASTE', 'VENT']),
    ('P-400.00', (2, 3)): ('',
        ['STORAGE TANK SCHEDULE', 'ST #', '']),
}

# ── FIXED VALUES FOR ALL 30: (name, row count, first row) ────────────────
#
# Written out, not computed from either version of the code, so a change to
# any schedule's structure fails here whatever the old code would have said.
# The 27 FAITHFUL reads only. The six in CHANGED were read against the
# rendered sheet; the other 21 are what the old code produced, unchanged.
# Rows: 58 under the old code, 62 now.
PINNED = {
    ('A.3.0', (4, 5)): ('', 1, ['', '', 'T', '', '']),
    ('A.4.0', (7, 14)): ('', 1, ['', '', '', '', '', '', '(readings disagree)', '', '', '', '', '', '', '']),
    ('FA-001', (2, 13)): ('', 1, ['△', '', 'A', '', '', '', '', '', '', '', '', 'A', '']),
    ('FA-001', (9, 12)): ('', 7, ['2 SPRK, WATERFLOW/PRESSURE SW.', '', '', '', '', '', '', '', '', '', '', '']),
    ('M-001.00', (3, 5)): ('', 2, ['141-200 (HOT WATER)', '0.25-0.29', '125', '1.5', '1.5']),
    ('M-001.00', (22, 4)): ('', 1, ['', '', 'SV-', '']),
    ('M-104.00', (5, 7)): ('', 1, ['', '', 'TE 10"X10"UP＆DN 2 PTAC-1', '', '', '', '']),
    ('M-104.00', (3, 7)): ('PTAC-1', 1, ['', '', '', '', 'TE 10"X10"UP＆DN 1 PTAC-1', '', '']),
    ('M-200.00', (5, 16)): ('ROOMS PTAC UNITS SCHEDULE', 3, ['PTAC-1', '21', 'AMANA', 'PTH093K', 'WALL', '9,000', '2.1', '8,000', '2.0', '12.0', '3.4', '208/1/60', '14.1', '15', '117', 'SEE NOTES']),
    ('M-200.00', (3, 12)): ('WALL ELECTRIC UNIT HEATER SCHEDULE', 1, ['WH-1', 'PER PLANS', '9', '(readings disagree)', 'E3323TD-RP', '1.5', '5120', '175', '120/1/60', '12.5', '26', '(readings disagree)']),
    ('M-200.00', (3, 6)): ('DUCT ELECTRIC HEATER', 1, ['DH-1', '8PD15-1812-3', '1', '15.0', '208/3/60', '41.7']),
    ('M-200.00', (4, 8)): ('DIFFUSER & REGISTER SCHEDULE', 2, ['A1', 'CARNES', 'RSDB', '125-235', 'SUPPLY', '', '8X6', '1,2,3,4,5']),
    ('M-200.00', (5, 15)): ('FAN SCHEDULE', 1, ['SAF-1', '1', 'CORRIDORS', 'GREENHECK', 'QEI-12', '900', 'BELT', '0.6', 'MIXED FLOW', '61', '1/3', '208', '3', '200', 'SEE NOTES']),
    ('M-200.00', (6, 14)): ('EXHAUST FAN SCHEDULE', 2, ['EF-1', 'APARTMENTSBATHROOMS EXHAUST', 'NUTONE', 'AEN110', '50', 'DIRECT', '0.3', 'CEILING FAN', '1.3', '0.3', '115', '', '10', 'SEE NOTES']),
    ('M-200.00', (2, 6)): ('C408 MAINTENANCE INFORMATION AND SYSTEM COMMISSIONING', 1, ['C408.2', 'SYSTEMCOMMISSIONING', '(readings disagree)', 'HVACSYSTEMREQUIRE COMMISSIONING', '(readings disagree)', '(readings disagree)']),
    ('P-001.00', (4, 9)): ('', 2, ['105°F-140°F', '0.22-0.28', '100', '1.0', '1.0', '1.5', '1.5', '1.5', '1.0 / 1.5']),
    ('P-400.00', (13, 6)): ("PLUMBING ROUGH-IN SCHEDULE SIZES OR AS REQUIRED FOR PARTICULAR FIXTURES. VERIFY ALL MODEL NUMBERS WITH OWNER OWNERS'S REP AD ARCH, PRIOR TO ORDERING.", 10, ['LAVATORIES', 'LAV', '1/2"', '1/2"', '1-1/4"', '1-1/4"']),
    ('P-400.00', (2, 7)): ('', 1, ['GWH-1', 'ROOF', '3', 'NATURAL', '199', '140', '5.7']),
    ('P-400.00', (2, 3)): ('', 1, ['(readings disagree)', '', '']),
    ('P-400.00', (4, 14)): ('DOMESTIC HOT WATER RECIRCULATION PUMP SCHEDULE', 2, ['HWRP-1', '2', 'ROOF MECH ROOM', 'IN-LINE', 'WATER HEATER', '13', '120', '17.2', '115', '1', '60', '1/8', '3/4"', 'SERIES 011']),
    ('P-400.00', (13, 3)): ('WITH', 10, ['UP TO 3”', '', '18']),
    ('Page 2 of 2', (3, 4)): ('', 2, ['(readings disagree)', '', 'CITYOFNEWYORK DEPARTMENTOFENVIRONMENTAL Environmental Protection PROTECTION SEWERINFORMATIONCERTIFIED REVIEWUNIT DIGITALLYSIGNEDBY: Md Golam Farhad DATECERTIFIED: CERTIFICATION 04/01/2027 EXPIRES:', '04/01/2025']),
    ('SP-003.00', (3, 14)): ('', 2, ['RFC49', '', '', '', '', '', '', '', '', '', '', '256 SQ.FT. (16FTx16FT)', '7', '8']),
    ('SP-002.00', (3, 14)): ('', 2, ['RFC49', '', '', '', '', '', '', '', '', '', '', '256 SQ.FT. (16FTx16FT)', '16', '7']),
    ('SP-004.00', (3, 14)): ('', 2, ['RFC49', '', '', '', '', '', '', '', '', '', '', '256 SQ.FT. (16FTx16FT)', '3', '6']),
    ('SP-004.00', (3, 3)): ('', 1, ['-7\'-2"', '0-. 8', '7\'-2"']),
    ('S-302.00', (3, 19)): ('', 1, ['', '', '二', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '']),
}


class EveryScheduleKeepsItsNameAndColumns(unittest.TestCase):
    """THE PROPERTY OVER THE WHOLE POPULATION, on the full structure."""

    def test_the_population_is_the_whole_corpus_not_the_five(self):
        self.assertEqual(len(TABLES), 30)
        self.assertEqual({_key(x) for x in TABLES if not x["faithful"]},
                         NOT_FAITHFUL)
        self.assertEqual(sorted(_key(x) for x in FAITHFUL), sorted(PINNED))

    def test_nothing_is_pinned_on_a_read_production_did_not_make(self):
        for key in NOT_FAITHFUL:
            self.assertNotIn(key, PINNED)
            self.assertNotIn(key, CHANGED)
            self.assertNotIn(key, EXPECTED)

    def test_every_schedule_matches_its_fixed_values(self):
        for x in FAITHFUL:
            name, _, rows = _shape(_new(x["table"]))
            got = (name, len(rows), rows[0] if rows else [])
            self.assertEqual(got, PINNED[_key(x)], _key(x))

    def test_every_unlisted_schedule_is_identical_to_before(self):
        moved = sorted(_key(x) for x in FAITHFUL
                       if _shape(_old(x["table"])) != _shape(_new(x["table"])))
        self.assertEqual(moved, sorted(CHANGED),
                         "a schedule changed that nobody looked at, or a "
                         "listed change no longer happens")

    def test_each_listed_change_is_the_one_that_was_read(self):
        for key, (name, columns) in EXPECTED.items():
            sched = _new(_table(key[0], key[1]))
            self.assertEqual((sched["name"], sched["columns"]),
                             (name, columns), key)

    def test_the_total(self):
        self.assertEqual(sum(n for _, n, _ in PINNED.values()), 62)
        after = sum(_rows(_new(x["table"])) for x in FAITHFUL)
        self.assertEqual(after, 62)

    def test_density_alone_is_what_lost_the_titles(self):
        """The first fix, on the same population, so the reason for the
        walk stays demonstrable."""
        lost = sorted(_key(x) for x in FAITHFUL
                      if _shape(_old(x["table"]))[0]
                      and not _structure(x["table"],
                                         _density_only_title_and_body)["name"]
                      and _key(x) not in {("SP-002.00", (3, 14)),
                                          ("SP-003.00", (3, 14)),
                                          ("SP-004.00", (3, 14)),
                                          ("FA-001", (9, 12))})
        self.assertIn(("M-200.00", (3, 6)), lost)      # DUCT ELECTRIC HEATER
        self.assertIn(("M-200.00", (4, 8)), lost)      # DIFFUSER & REGISTER
        self.assertIn(("P-400.00", (13, 6)), lost)     # PLUMBING ROUGH-IN


# ── WHAT STILL STORES ONE ROW, AND WHY ───────────────────────────────────
#
# The handoff said "five schedules, all empty OCR rows". Listed in full it is
# fifteen, and three kinds. A schedule that PRINTS one item is right at one
# row; four of M-200.00's are that, and its FAN SCHEDULE's blank bands are
# the gap in a two-tier heading, not unread data.
ONE_ITEM = {("M-200.00", (3, 12)), ("M-200.00", (3, 6)),
            ("M-200.00", (5, 15)), ("M-200.00", (2, 6)),
            ("P-400.00", (2, 7))}
# The grid's bands came back from OCR with nothing in them: a reading or
# placement defect, logged and not chased. Render the sheet before touching.
OCR_EMPTY = {("A.3.0", (4, 5)), ("A.4.0", (7, 14)), ("M-001.00", (22, 4)),
             ("M-104.00", (5, 7)), ("M-104.00", (3, 7)),
             ("S-302.00", (3, 19))}
# A fragment of a schedule. (P-400.00 (3, 9), heading and value fused in one
# cell, was here; its container read is not faithful, so nothing is pinned
# on it.)
FRAGMENT = {("FA-001", (2, 13)), ("P-400.00", (2, 3)), ("SP-004.00", (3, 3))}


class WhatStillStoresOneRow(unittest.TestCase):

    def test_the_list_is_complete(self):
        still = {_key(x) for x in FAITHFUL if _rows(_new(x["table"])) <= 1}
        self.assertEqual(still, ONE_ITEM | OCR_EMPTY | FRAGMENT)

    def test_one_item_schedules_store_a_real_item(self):
        for key in ONE_ITEM:
            row = _new(_table(*key))["rows"][0]
            self.assertGreaterEqual(sum(1 for c in row if c), len(row) * 0.5,
                                    key)

    def test_the_ocr_empty_ones_really_have_blank_bands(self):
        for key in OCR_EMPTY:
            table = _table(*key)
            blank = sum(1 for r in table if not any(str(c).strip() for c in r))
            self.assertGreater(blank, 0, f"{key} has no blank band: a third "
                               f"mechanism, and it needs its own look")


if __name__ == "__main__":
    unittest.main()
