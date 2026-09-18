"""Two readings of one cell that disagree make the disagreement the fact.

MEASURED ON M-200.00, 588 Thomas S Boyland Street, re-index of 2026-09-18.
The page is read twice: the vision model reads the ROOMS PTAC UNITS SCHEDULE
off the image, and the grid OCR reads the same table out of its ruling lines.
They agreed on every cell of both rows except one —

    PTAC-2, QTY:   vision 9,   OCR 6

— and the sheet, rendered at 330 dpi and read by eye, prints 9.

The OCR reading won, because `ocr_grid_cell` outranks `vision_read`. So a
superintendent asking how many PTAC-2 units the job has would have been told
SIX, cited as a printed schedule cell, with the correct 9 sitting in the same
corpus one tier below. That is `41 PTAC units` in a new costume: not a model
summing what no cell prints, but one reader misreading a digit and being
believed because of its badge.

WHY NOT PICK THE WINNER. A tier says how a number was come by, not whether it
is right. On the pass before this one the two readers agreed 42 of 42, so the
tier order is evidence about provenance and no evidence at all about which
reader is correct on the one cell where they differ. Picking would be a guess
wearing a citation.

So: both readings are kept, the cell is marked contested, and nothing will
quote either number as the quantity — not the element record, not the schedule
record it came from, and not the gate. What the crew gets is the sheet, the
mark, and the sentence that the readings disagree.
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
from lib import plan_extract as pe  # noqa: E402
from lib import plan_records as pr  # noqa: E402
from lib import plan_search as ps  # noqa: E402
from lib import plan_text as pt  # noqa: E402

COLS = ["UNIT NO.", "QTY", "MAKE", "NET COOLING CAPACITY (BTUH)"]


def _sched(source, ptac2_qty):
    return {"name": "ROOMS PTAC UNITS SCHEDULE", "source": source,
            "columns": list(COLS),
            "rows": [["PTAC-1", "21", "AMANA", "9,000"],
                     ["PTAC-2", str(ptac2_qty), "AMANA", "11,400"],
                     ["PTAC-3", "11", "AMANA", "14,000"]]}


def _records(vision_qty=9, ocr_qty=6, schedules=None):
    f = dict(pe.EMPTY_FIELDS)
    f["schedules"] = schedules if schedules is not None else [
        _sched("vision", vision_qty), _sched("ocr_grid", ocr_qty)]
    f["elements"] = pt.elements_from_evidence([], f["schedules"], [])
    return pr.build_records(f, page={"sheet_number": "M-200.00", "page_number": 9},
                            raw_text="M-200.00")


def _elements(recs, mark):
    return [r for r in recs
            if r["record_type"] == "element" and mark in (r.get("quote") or "")]


class TheDisagreementIsRecordedAtWriteTime(unittest.TestCase):

    def test_both_readings_are_kept(self):
        els = _elements(_records(), "PTAC-2")
        self.assertEqual(len(els), 2, "a reading was dropped rather than kept")
        self.assertEqual({e["tier"] for e in els}, {"vision_read", "ocr_grid_cell"})

    def test_both_are_marked_contested(self):
        for e in _elements(_records(), "PTAC-2"):
            with self.subTest(tier=e["tier"]):
                self.assertTrue(e["payload"]["count_contested"])

    def test_each_carries_both_numbers_and_who_read_them(self):
        e = _elements(_records(), "PTAC-2")[0]
        self.assertEqual(
            [(x["value"], x["read_by"]) for x in e["payload"]["count_readings"]],
            [(6, "ocr_schedule_qty"), (9, "vision_read")])

    def test_a_cell_the_readers_agree_on_is_untouched(self):
        for e in _elements(_records(), "PTAC-1"):
            with self.subTest(tier=e["tier"]):
                self.assertNotIn("count_contested", e["payload"])
                self.assertIn("count 21", e["quote"])

    def test_one_reading_alone_is_not_a_disagreement(self):
        """Most sheets are read once. A single reading is the ordinary case and
        must not be dressed up as a dispute."""
        recs = _records(schedules=[_sched("vision", 9)])
        for e in _elements(recs, "PTAC-2"):
            self.assertNotIn("count_contested", e["payload"])

    def test_a_tag_count_and_a_schedule_row_are_not_one_cell(self):
        """Nine PTAC-2 in the schedule and seven PTAC-2 tags drawn on the plan
        are two different facts — how many the job buys and how many this sheet
        shows — and neither is wrong. Only two readings of the SAME cell are a
        contest."""
        f = dict(pe.EMPTY_FIELDS)
        f["schedules"] = [_sched("vision", 9)]
        f["elements"] = pt.elements_from_evidence(
            [], f["schedules"], [{"tag": "PTAC-2", "count": 7}])
        recs = pr.build_records(f, page={"sheet_number": "M-200.00", "page_number": 9},
                                raw_text="M-200.00")
        for e in _elements(recs, "PTAC-2"):
            with self.subTest(basis=e["payload"].get("count_basis")):
                self.assertNotIn("count_contested", e["payload"])


class NothingQuotesAContestedValue(unittest.TestCase):

    def test_the_element_stops_stating_a_count(self):
        for e in _elements(_records(), "PTAC-2"):
            with self.subTest(tier=e["tier"]):
                self.assertIn("readings disagree", e["quote"])
                self.assertNotIn("count 6", e["quote"])
                self.assertNotIn("count 9", e["quote"])

    def test_and_so_does_the_schedule_it_came_from(self):
        """THE HOLE THIS CLOSED. The element stopped quoting a quantity and the
        SCHEDULE record still printed every cell of the table, so `PTAC-2 | 6`
        was a printed number as far as the gate was concerned."""
        for r in _records():
            if r["record_type"] != "schedule":
                continue
            with self.subTest(tier=r["tier"]):
                self.assertIn("(readings disagree)", r["quote"])
                self.assertNotIn("| 6 |", r["quote"])
                self.assertNotIn("| 9 |", r["quote"])

    def test_the_gate_refuses_both_numbers(self):
        recs = _records()
        for n in (6, 9):
            with self.subTest(said=n):
                ok, missing = ps.answer_is_grounded(
                    f"There are {n} PTAC-2 units.", recs)
                self.assertFalse(ok, "a contested value passed the gate")
                self.assertIn(str(n), missing)

    def test_but_only_that_cell(self):
        """A redaction that took the whole row with it would refuse true
        answers about the rest of the table. 21 is agreed, and 9,000 BTUH is a
        different cell that happens to start with the disputed digit."""
        recs = _records()
        for text in ("There are 21 PTAC-1 units.",
                     "Net cooling capacity is 9,000 BTUH.",
                     "There are 11 PTAC-3 units."):
            with self.subTest(said=text):
                ok, missing = ps.answer_is_grounded(text, recs)
                self.assertTrue(ok, f"refused a true answer: {missing}")

    def test_the_crew_is_told_what_to_do(self):
        recs = ps.rank(_records(), ps.search_terms("PTAC-2"))
        out = ps.render_records(recs, "PTAC-2")
        self.assertIn("M-200.00", out)
        self.assertIn("readings disagree", out)
        self.assertIn("verify against the sheet", out)
        self.assertIn("6 and 9", out)

    def test_and_so_is_the_model(self):
        out = server._render_records_for_model(
            ps.rank(_records(), ps.search_terms("PTAC-2")), "PTAC-2")
        self.assertIn("READINGS DISAGREE", out)
        self.assertIn("Do not state either", out)


if __name__ == "__main__":
    unittest.main()
