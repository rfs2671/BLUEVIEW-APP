"""One render is a guess; two renders that agree are a reading.

MEASURED ACROSS EVERY READABLE GRID IN THE 588 BOYLAND SET, 2026-09-18.
Fifty-seven grids were rendered at the pipeline's own 400 dpi twice — once
with the two-pixel pad `_render_pdf_crop` adds, once without it — and the OCR
was asked to read both:

    grids that read DIFFERENTLY under a two-pixel change   30 of 57
    text read only WITHOUT the pad                         197 tokens
    text read only WITH the pad                            190 tokens
    grids whose NUMERIC readings differ                    11

That is the whole case. The pad is not a mistake to correct — the two
directions are symmetric, and two grids read a different digit in OPPOSITE
directions: M-200.00's PTAC-2 QTY is 9 unpadded and 6 padded, FA-001 has a
cell that is 6 unpadded and 9 padded. The sheet prints 9 on M-200.00. There is
no better geometry to move to; the engine is unstable at this operating point
and a single read cannot tell a stable cell from a coin-flip.

So every grid is read at both geometries. A cell they agree on is a reading
two independent rasterisations produced. A cell they disagree on is contested,
and nothing downstream will state it as a value — the same rule already
shipped for vision-versus-OCR, applied where the instability actually is.

NO THRESHOLD DECIDES ANY OF THIS. The engine's confidence is carried because
it is evidence worth keeping — it separated cleanly on the one cell that can
be checked by eye, 0.960 wrong against 0.997 right — and it is stored as
evidence, never as a ranking input.
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
from lib import plan_ocr  # noqa: E402
from lib import plan_records as pr  # noqa: E402
from lib import plan_search as ps  # noqa: E402
from lib import plan_text as pt  # noqa: E402

# Two columns, three rows: a title band, a header, and two data rows.
GRID = {"bbox": [0, 0, 200, 100],
        "rows": [0, 25, 50, 75, 100],
        "cols": [0, 100, 200]}


def _box(col, row, text, score=0.99):
    """A box whose centre lands in that cell, in device pixels at OCR_DPI."""
    s = plan_ocr.OCR_DPI / 72.0
    cx = (GRID["cols"][col] + GRID["cols"][col + 1]) / 2
    cy = (GRID["rows"][row] + GRID["rows"][row + 1]) / 2
    return (cx * s, cy * s, text, score)


def _read_twice(first, second):
    """read_grid_twice over two prepared reads.

    Patched at `_boxes`, not at the engine: everything above `_boxes` is a
    PNG decode, and this is a test of the MERGE — which cell wins, which is
    contested — not of image handling."""
    reads = {b"a": list(first), b"b": list(second)}
    real = plan_ocr._boxes
    plan_ocr._boxes = lambda image_bytes: reads.get(image_bytes, [])
    try:
        return plan_ocr.read_grid_twice(b"a", b"b", GRID)
    finally:
        plan_ocr._boxes = real


AGREE = [_box(0, 0, "PTAC SCHEDULE"), _box(0, 1, "UNIT NO."), _box(1, 1, "QTY"),
         _box(0, 2, "PTAC-1"), _box(1, 2, "21"),
         _box(0, 3, "PTAC-2"), _box(1, 3, "9", 0.997)]
DISAGREE = list(AGREE[:-1]) + [_box(1, 3, "6", 0.960)]


class TwoReadsThatAgreeAreAReading(unittest.TestCase):

    def test_the_value_stands(self):
        sched = _read_twice(AGREE, AGREE)
        row = next(r for r in sched["rows"] if r and r[0] == "PTAC-2")
        self.assertEqual(row[1], "9")

    def test_nothing_is_contested(self):
        sched = _read_twice(AGREE, AGREE)
        self.assertEqual(sched.get("contested_cells"), [])

    def test_the_schedule_says_it_was_read_twice(self):
        self.assertTrue(_read_twice(AGREE, AGREE)["read_twice"])

    def test_the_confidence_is_kept(self):
        sched = _read_twice(AGREE, AGREE)
        scores = [s for row in sched["cell_scores"] for s in row if s > 0]
        self.assertTrue(scores, "no confidence reached the schedule")
        self.assertLessEqual(max(scores), 1.0)


class TwoReadsThatDisagreeAreAContest(unittest.TestCase):

    def test_the_cell_states_no_value(self):
        sched = _read_twice(AGREE, DISAGREE)
        row = next(r for r in sched["rows"] if r and r[0] == "PTAC-2")
        self.assertEqual(row[1], plan_ocr.CONTESTED_CELL)

    def test_both_readings_are_kept_with_the_mark(self):
        sched = _read_twice(AGREE, DISAGREE)
        self.assertEqual(len(sched["contested_cells"]), 1)
        c = sched["contested_cells"][0]
        self.assertEqual(c["readings"], ["6", "9"])
        self.assertEqual(c["mark"], "PTAC-2")

    def test_the_agreed_cells_are_untouched(self):
        sched = _read_twice(AGREE, DISAGREE)
        row = next(r for r in sched["rows"] if r and r[0] == "PTAC-1")
        self.assertEqual(row[1], "21")

    def test_a_blank_against_a_value_is_not_a_disagreement(self):
        """A crop two pixels wider catches a glyph the other clipped — that is
        the padded read finding a '5' where the unpadded found nothing.
        Choosing the text over the blank loses nothing; calling it a contest
        would throw away a reading that was never disputed."""
        blank = [b for b in AGREE if b[2] != "9"]
        sched = _read_twice(blank, AGREE)
        row = next(r for r in sched["rows"] if r and r[0] == "PTAC-2")
        self.assertEqual(row[1], "9")
        self.assertEqual(sched["contested_cells"], [])

    def test_the_contested_cell_keeps_the_worse_confidence(self):
        sched = _read_twice(AGREE, DISAGREE)
        c = sched["contested_cells"][0]
        self.assertEqual(min(c["scores"]), 0.960)


class ItReachesTheRecordAndStopsThere(unittest.TestCase):

    def _records(self):
        sched = _read_twice(AGREE, DISAGREE)
        sched["source"] = "ocr_grid"
        f = dict(pe.EMPTY_FIELDS)
        f["schedules"] = [sched]
        f["elements"] = pt.elements_from_evidence([], [sched], [])
        return pr.build_records(f, page={"sheet_number": "M-200.00",
                                         "page_number": 9}, raw_text="M-200.00")

    def test_the_element_is_contested(self):
        el = next(r for r in self._records()
                  if r["record_type"] == "element" and "PTAC-2" in r["quote"])
        self.assertTrue(el["payload"]["count_contested"])
        self.assertEqual([x["value"] for x in el["payload"]["count_readings"]],
                         [6, 9])

    def test_the_render_still_says_what_it_knows(self):
        """NEVER 'not available'. The sheet, the mark, the schedule and the
        disagreement — a reader who is told only that something failed cannot
        act, and everything here is known except which digit it is."""
        recs = self._records()
        out = ps.render_records(ps.rank(recs, ps.search_terms("PTAC-2")), "PTAC-2")
        self.assertIn("M-200.00", out)
        self.assertIn("PTAC-2", out)
        self.assertIn("PTAC SCHEDULE", out, "the schedule it came from is gone")
        self.assertIn("readings disagree", out)
        self.assertIn("6 and 9", out, "the readings themselves are gone")
        # Asserted as the SENTENCE a reader would meet, not as a bare word:
        # "unavailable" is a substring of nothing here today and of anything
        # tomorrow, and a ban that loose stops meaning what it says.
        for evasion in ("is not available", "value unavailable",
                        "could not be read", "no value"):
            with self.subTest(evasion=evasion):
                self.assertNotIn(evasion, out.lower())

    def test_the_gate_refuses_both_numbers(self):
        recs = self._records()
        for n in (6, 9):
            with self.subTest(said=n):
                ok, _missing = ps.answer_is_grounded(f"There are {n} PTAC-2 units.", recs)
                self.assertFalse(ok)

    def test_but_the_agreed_count_is_still_quotable(self):
        ok, missing = ps.answer_is_grounded("There are 21 PTAC-1 units.",
                                            self._records())
        self.assertTrue(ok, missing)


class TheTwoMarkersAreOneMarker(unittest.TestCase):
    """plan_ocr writes the marker into a cell; plan_records writes it when it
    redacts a schedule. Two spellings would be two markers, and a reader would
    meet both."""

    def test_they_are_the_same_string(self):
        self.assertEqual(plan_ocr.CONTESTED_CELL, pr.CONTESTED_CELL)


class ABoxNeedNotCarryAConfidence(unittest.TestCase):
    """place_in_grid is the half that decides which column a value lands in,
    and it is tested with boxes built by hand. Those say nothing about
    confidence and should not have to."""

    def test_a_three_tuple_is_still_a_box(self):
        s = plan_ocr.OCR_DPI / 72.0
        table, strays, scores = plan_ocr.place_in_grid([(50 * s, 60 * s, "21")], GRID)
        self.assertEqual(table[2][0], "21")
        self.assertEqual(strays, 0)
        self.assertEqual(scores[2][0], -1.0)


class TheRenderGeometryIsAParameter(unittest.TestCase):

    def test_both_geometries_are_asked_for(self):
        import inspect
        src = inspect.getsource(server._ocr_blind_grids)
        self.assertIn("plan_ocr.OCR_DPI, 2", src)
        self.assertIn("plan_ocr.OCR_DPI, 0", src)
        self.assertIn("read_grid_twice", src)

    def test_one_geometry_failing_is_still_a_read(self):
        import inspect
        src = inspect.getsource(server._ocr_blind_grids)
        self.assertIn("ocr_single_geometry", src)
        self.assertIn("pngs[0] or pngs[1]", src)


if __name__ == "__main__":
    unittest.main()
