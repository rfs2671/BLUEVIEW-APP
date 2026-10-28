"""A table the finder could not name takes the one heading printed directly
above it (ruling 2026-10-25).

A-400.00 on 588 Boyland draws its door schedule as door elevations. The
finder found no cell saying SCHEDULE and named the table "TABLE"; the
heading "INTERIOR DOOR SCHEDULE" 15 pt over its corner became loose text, so
the record that prints 3'-0" X 7'-0" matched half of "door schedule" and
ranked ninth of eight.

The rule: left edges aligned (within a quarter of the heading's height), a
gap of at most one line, nothing printed in between, and a word in it. The
negatives are the four wrong names a looser rule gave on production's 26
untitled tables: a floor label 16 pt off a zoning diagram's corner, and a
dimension 26 pt off an elevation.

Every test goes through `fields_from_layout`, which main has, so the control
run on main fails by assertion.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

#: A-400.00's interior door table as production stores it: the finder's box
#: and the heading's box (plan_records, read 2026-10-25).
DOOR_TABLE_BBOX = [1041.0, 111.18, 2188.56, 1191.26]
DOOR_HEADING_BBOX = [1039.02, 75.13, 1272.17, 96.40]
ROWS = [["NUMBER A", "", "NUMBER B", "", "NUMBER E"],
        ["3'-0\" X 7'-0\"", "", "3'-0\" X 7'-0\"", "", "3'-0\" X 7'-0\""]]


def _schedules(lines, table_bbox=DOOR_TABLE_BBOX, rows=ROWS):
    from lib import plan_text as T
    blocks = [{"bbox": bb, "lines": [t], "line_bboxes": [bb], "text": t} for t, bb in lines]
    layout = {"width": 2592.0, "height": 1728.0, "blocks": blocks,
              "tables": [{"rows": rows, "bbox": table_bbox}]}
    return T.fields_from_layout(layout)["schedules"]


class TheHeadingAbove(unittest.TestCase):

    def test_the_door_schedule_is_named_by_its_heading(self):
        (s,) = _schedules([("INTERIOR DOOR SCHEDULE", DOOR_HEADING_BBOX)])
        self.assertEqual(s["name"], "INTERIOR DOOR SCHEDULE")

    def test_and_its_record_says_so(self):
        from lib import plan_records as R
        (s,) = _schedules([("INTERIOR DOOR SCHEDULE", DOOR_HEADING_BBOX)])
        recs = R.build_records({"schedules": [s]},
                               page={"sheet_number": "A-400.00", "page_number": 23})
        (rec,) = [r for r in recs if r["record_type"] == "schedule"]
        self.assertTrue(rec["quote"].startswith("INTERIOR DOOR SCHEDULE NUMBER A"), rec["quote"][:40])
        self.assertEqual(rec["subject_terms"][:1], ["INTERIOR DOOR SCHEDULE"])


class WhatIsNotAHeading(unittest.TestCase):

    def test_a_label_off_the_corner_is_not_a_heading(self):
        # Z-002.00: THIRD FLOOR, 7 pt above a zoning diagram the finder read
        # as a table, its left edge 16 pt in from the table's.
        (s,) = _schedules([("THIRD FLOOR", [656.2, 1273.6, 760.0, 1294.9])],
                          table_bbox=[640.0, 1302.0, 787.0, 1508.0])
        self.assertEqual(s["name"], "TABLE")

    def test_a_dimension_is_not_a_heading(self):
        bb = [DOOR_TABLE_BBOX[0], 85.0, DOOR_TABLE_BBOX[0] + 60, 106.0]
        (s,) = _schedules([("5'-0\"", bb)])
        self.assertEqual(s["name"], "TABLE")

    def test_a_heading_too_far_above_is_not_its_heading(self):
        far = [1039.02, 30.0, 1272.17, 51.27]     # 60 pt up, three lines
        (s,) = _schedules([("INTERIOR DOOR SCHEDULE", far)])
        self.assertEqual(s["name"], "TABLE")

    def test_nothing_may_be_printed_in_between(self):
        note = [1100.0, 98.0, 1500.0, 108.0]
        (s,) = _schedules([("INTERIOR DOOR SCHEDULE", DOOR_HEADING_BBOX), ("SEE NOTE 4", note)])
        self.assertEqual(s["name"], "TABLE")

    def test_two_lines_in_the_heading_place_name_nothing(self):
        (s,) = _schedules([("INTERIOR DOOR SCHEDULE", DOOR_HEADING_BBOX),
                           ("REVISED DOORS", DOOR_HEADING_BBOX)])
        self.assertEqual(s["name"], "TABLE")

    def test_a_titled_table_keeps_its_title(self):
        rows = [["DOOR SCHEDULE", "", ""], ["MARK", "SIZE", "TYPE"], ["A", "3'-0\" X 7'-0\"", "F"]]
        (s,) = _schedules([("SOMETHING ELSE", DOOR_HEADING_BBOX)], rows=rows)
        self.assertEqual(s["name"], "DOOR SCHEDULE")


class TheRealSheet(unittest.TestCase):
    """A-400.00 itself (AR - 3.28.25.pdf p23, fixture PDFs): its three
    untitled tables take their three headings."""

    def test_a400(self):
        from lib import plan_text as T
        layout = T.page_layout_at(str(require_pdf("AR - 3.28.25.pdf")), 23)
        names = {s["name"] for s in T.fields_from_layout(layout)["schedules"]}
        self.assertTrue({"WINDOW SCHEDULE", "INTERIOR DOOR SCHEDULE",
                         "EXTERIOR DOOR SCHEDULE"} <= names, names)


if __name__ == "__main__":
    unittest.main()
