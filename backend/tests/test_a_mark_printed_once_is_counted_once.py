"""A MARK PRINTED ONCE AND STORED TWICE IS ONE MARK.

`count_tags` counted OCCURRENCES of a token in the text layer. A CAD export
writes the same annotation into the content stream more than once, so the
count was of writes, not of marks.

MEASURED ON P-206.00 (PL - 6.29.26.pdf p14) 2026-09-19: the page's layout
yields FOUR blocks whose text is exactly `AD`, at TWO distinct positions —
every bbox exactly duplicated:

    [971.5, 720.5, 984.0, 731.2]     <- twice
    [1697.5, 720.5, 1710.0, 731.2]   <- twice

and the sheet carries two area drains. A superintendent asking how many was
told four.

── WHAT THIS MUST NOT BREAK ─────────────────────────────────────────────────

Two real marks on a plan are metres apart on the sheet. The threshold is two
POINTS, which is generous in the direction of counting both — a mark is about
ten points tall, so two prints inside two points of each other are the same
print. The tests below push from both sides: duplicates must collapse, and
marks that are genuinely near each other must not.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402
from lib import plan_text as pt  # noqa: E402

VOCAB = frozenset({"AD", "RD", "PTAC-1"})


def _block(text, x, y, h=12.0, w=11.0):
    return {"text": text, "bbox": [x, y, x + w, y + h], "lines": [text]}


def _count(blocks, tag="AD"):
    got = pt.count_tags({"blocks": blocks}, VOCAB)
    return next((t["count"] for t in got if t["tag"] == tag), 0)


class TheDuplicatedContentStream(unittest.TestCase):

    def test_p206_shape_collapses_to_two(self):
        """The real page, reduced to what decides it."""
        blocks = [_block("AD", 971.5, 720.5), _block("AD", 971.5, 720.5),
                  _block("AD", 1697.5, 720.5), _block("AD", 1697.5, 720.5)]
        self.assertEqual(_count(blocks), 2)

    def test_the_old_behaviour_is_named_so_it_cannot_return(self):
        """Occurrence counting would say four. Written out because a future
        reader needs to know which number was wrong."""
        blocks = [_block("AD", 971.5, 720.5)] * 4
        self.assertNotEqual(_count(blocks), 4)
        self.assertEqual(_count(blocks), 1)

    def test_a_triplicated_stream_is_still_one_mark(self):
        self.assertEqual(_count([_block("AD", 10, 10)] * 3), 1)


class TryingToDefeatIt(unittest.TestCase):
    """Every rule gets the test that tries to break it."""

    def test_two_marks_a_hand_span_apart_are_two(self):
        self.assertEqual(_count([_block("AD", 100, 100),
                                 _block("AD", 400, 900)]), 2)

    def test_two_marks_just_outside_the_threshold_are_two(self):
        """The boundary, from the side that must count both."""
        d = pt.TAG_SAME_SPOT_PTS + 0.5
        self.assertEqual(_count([_block("AD", 100.0, 100.0),
                                 _block("AD", 100.0 + d, 100.0)]), 2)

    def test_two_prints_just_inside_the_threshold_are_one(self):
        d = pt.TAG_SAME_SPOT_PTS - 0.5
        self.assertEqual(_count([_block("AD", 100.0, 100.0),
                                 _block("AD", 100.0 + d, 100.0)]), 1)

    def test_the_threshold_is_smaller_than_a_mark_is_tall(self):
        """If it ever grew past the height of a glyph it would start merging
        marks on adjacent rows of a dense plan."""
        self.assertLess(pt.TAG_SAME_SPOT_PTS, 10.0)

    def test_different_tags_at_the_same_spot_are_both_counted(self):
        """A drain symbol and its mark can share a coordinate. Deduping on
        position alone, without the tag, would lose one."""
        blocks = [_block("AD", 500, 500), _block("RD", 500, 500)]
        self.assertEqual(_count(blocks, "AD"), 1)
        self.assertEqual(_count(blocks, "RD"), 1)

    def test_a_block_with_no_bbox_does_not_crash_or_vanish(self):
        blocks = [{"text": "AD", "lines": ["AD"]}, _block("AD", 900, 900)]
        self.assertEqual(_count(blocks), 2)

    def test_a_malformed_bbox_is_survived(self):
        blocks = [{"text": "AD", "bbox": ["x", None], "lines": ["AD"]},
                  _block("AD", 900, 900)]
        self.assertEqual(_count(blocks), 2)

    def test_the_long_block_rule_still_applies(self):
        """A tag inside a sentence is not a tag on the plan, unchanged."""
        long_text = "AD " + "x" * (pt.LABEL_MAX_CHARS + 10)
        self.assertEqual(_count([{"text": long_text, "bbox": [0, 0, 9, 9],
                                  "lines": [long_text]}]), 0)

    def test_case_sensitivity_is_unchanged(self):
        """'128 Museum Village Rd' must not become an RD tag."""
        self.assertEqual(_count([_block("Rd", 10, 10)], "RD"), 0)


class OnTheRealSheet(unittest.TestCase):
    """The fixture above is a reduction. This reads the PDF itself when it is
    present, so the reduction cannot quietly stop matching reality."""

    PDF_NAME = "PL - 6.29.26.pdf"

    def test_p206_counts_two_area_drains(self):
        layout = pt.page_layout_at(str(require_pdf(self.PDF_NAME)), 14)
        vocab = pt.tag_vocabulary([layout])
        counts = {t["tag"]: t["count"] for t in pt.count_tags(layout, vocab)}
        self.assertEqual(counts.get("AD"), 2,
                         f"expected two area drains, got {counts}")

    def test_the_roof_drains_are_invisible_to_the_text_layer(self):
        """Not a defect in THIS code, and the reason roof-drain-count is
        expected to fail: RD-1 and RD-2 are outlined vector text."""
        layout = pt.page_layout_at(str(require_pdf(self.PDF_NAME)), 14)
        text = " ".join(b["text"] for b in (layout.get("blocks") or []))
        self.assertNotIn("RD-1", text)
        self.assertNotIn("RD-2", text)


if __name__ == "__main__":
    unittest.main()
