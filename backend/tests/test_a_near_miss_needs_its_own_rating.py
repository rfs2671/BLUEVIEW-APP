"""A NEAR-MISS SNAP NEEDS THE LABEL'S OWN RATING. A MISREAD TAG CAN BE READ BY IT.

Measured on M-103.00 of the Boyland set, 2026-09-21. "4 EF-2 located" was
right, and it was right by accident. Two defects cancelled:

    'F2 HOUR FIRE'  - the note "2 HOUR FIRE RATED ENCLOSURE" with a stray
                      leader tick read as F. `F` is one prefix edit from `EF`
                      and the digit matched exactly, so it snapped to EF-2
                      and a symbol search then claimed nearby linework.
    'EF=2(1' + '2(100)' - 4A's real kitchen fan label, hyphen read as `=`.
                      It did not snap at all, and `corroborated_tag`, written
                      for exactly this misread, was called by nothing but its
                      own tests.

Only the per-unit split showed it: 4A had one fan and 4B three.

The rule: an EXACT snap stands on the tag. Where the schedule has a rating
column, a snap that needed a prefix edit is accepted only if the label's own
rating names the same tag, and a read that does not snap is accepted if its
rating, printed in the label's `(value)` form, names exactly one tag. Reads
within the merge distance are one printed label. With no rating column (PTAC)
nothing changes - there is nothing to corroborate with.

WHAT IS REAL AND WHAT IS WRITTEN. Two inputs are verbatim OCR output from
the sweep of M-103.00, text and position both: FIRE_NOTE (three reads) and
KITCHEN_4A (two reads). The seven clean EF labels in the last test are
PRINTED LABELS - their positions are the sweep's, their text is what the
sheet prints, not what the OCR returned. Every other input is synthetic.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_symbols as ps  # noqa: E402

EF = ("EF-1", "EF-2")
CORR = {"EF-1": "50", "EF-2": "100"}
PTAC = ("PTAC-1", "PTAC-3")

#: REAL OCR READS - verbatim from the sweep of M-103.00 (text, x, y in
#: display points). The only two real inputs in this file.
FIRE_NOTE = [("F2 HOUR FIRE", 1177.0, 884.0),
             ("RATED ENCLOSURE", 1189.0, 896.0), ("RE", 1222.0, 896.0)]
KITCHEN_4A = [("EF=2(1", 1083.0, 439.0), ("2(100)", 1097.0, 439.0)]


class ANearMissNeedsItsOwnRating(unittest.TestCase):

    def test_a_fire_rating_note_is_not_an_exhaust_fan(self):
        self.assertEqual(ps.labels_in(FIRE_NOTE, EF, corroborations=CORR), [])

    def test_the_same_near_miss_carrying_its_rating_is_kept(self):
        reads = [("F-2(100)", 500.0, 500.0)]
        self.assertEqual(ps.labels_in(reads, EF, corroborations=CORR),
                         [("EF-2", 500.0, 500.0)])

    def test_a_rating_naming_another_tag_does_not_rescue_it(self):
        reads = [("F-2(50)", 500.0, 500.0)]
        self.assertEqual(ps.labels_in(reads, EF, corroborations=CORR), [])

    def test_an_exact_snap_stands_on_the_tag(self):
        reads = [("EF-1", 100.0, 100.0)]
        self.assertEqual(ps.labels_in(reads, EF, corroborations=CORR),
                         [("EF-1", 100.0, 100.0)])


class AMisreadTagIsReadByItsRating(unittest.TestCase):

    def test_4a_kitchen_fan_is_found(self):
        got = ps.labels_in(KITCHEN_4A, EF, corroborations=CORR)
        # One label, at the printed label - either of its two reads.
        self.assertEqual([t for t, _x, _y in got], ["EF-2"])
        self.assertTrue(1083.0 <= got[0][1] <= 1097.0 and got[0][2] == 439.0)

    def test_a_bare_number_is_not_a_label(self):
        """`100'-0" LOT` carries a 100. The rating counts in the label's own
        form, `(100)`, not anywhere a number appears."""
        reads = [("100'-0\" LOT", 900.0, 300.0)]
        self.assertEqual(ps.labels_in(reads, EF, corroborations=CORR), [])

    def test_a_rating_read_beside_a_good_tag_does_not_double_count(self):
        reads = [("EF-2", 100.0, 100.0), ("(100)", 115.0, 100.0)]
        self.assertEqual(len(ps.labels_in(reads, EF, corroborations=CORR,
                                          merge_pt=36.0)), 1)


class NoRatingColumnNothingChanges(unittest.TestCase):

    def test_ptac_near_miss_still_snaps_without_a_rating_column(self):
        reads = [("PTAC-1", 100.0, 100.0), ("PTC-3", 900.0, 100.0)]
        self.assertEqual(ps.labels_in(reads, PTAC),
                         ps.labels_in(reads, PTAC, corroborations={}))
        self.assertEqual(len(ps.labels_in(reads, PTAC, corroborations={})), 2)


class BothDefectsTogetherGiveTheRightSplit(unittest.TestCase):

    def test_the_sheets_eight_fan_labels(self):
        """The sheet's EF labels.

        7 PRINTED LABELS: the first seven reads - sweep positions, text as
          the sheet prints it, NOT the OCR's string.
        2 REAL OCR INPUTS: FIRE_NOTE and KITCHEN_4A, verbatim.

        Before: the fire note counted and 4A's kitchen fan did not, and the
        total was still 8."""
        reads = ([("EF-1(50)", 1050.0, 655.0), ("EF-1(50)", 1050.0, 832.0),
                  ("EF-2(100)", 1083.0, 1041.0), ("EF-2(100)", 1618.0, 439.0),
                  ("EF-1(50)", 1644.0, 647.0), ("EF-1(50)", 1641.0, 830.0),
                  ("EF-2(100)", 1617.0, 1041.0)] + FIRE_NOTE + KITCHEN_4A)
        got = ps.labels_in(reads, EF, corroborations=CORR, merge_pt=36.0)
        self.assertEqual(len(got), 8)
        self.assertNotIn((1177.0, 884.0), [(x, y) for _t, x, y in got])
        self.assertEqual(sum(1 for t, x, y in got
                             if t == "EF-2" and 1083.0 <= x <= 1097.0
                             and y == 439.0), 1)


if __name__ == "__main__":
    unittest.main()
