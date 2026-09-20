"""THE DRAWING SAYS 9'-7 1/4". THE READER SAID 9'-714".

Found 2026-09-20 while measuring something else entirely. A stacked fraction
whose pieces were run together produced a number that is printed NOWHERE on
the sheet, stored it as a record quote, and made it citable to a
superintendent as a dimension.

WHY NOTHING CAUGHT IT. Value-level grounding (#614) checks that a number in
an answer came from a record. The record genuinely contains 714, so an answer
quoting it is correctly grounded — the gate and the model both did their jobs
and the reader still said something untrue. A fabricated record is the
direction that arc did not cover, and `verified` could not have covered it
either: it is written on every plan record and read by nothing.

WHY IT WAS INVISIBLE. `rebuild_line` finds a stacked fraction by looking for
a SMALLER span, which is how some CAD fonts set one. On 588 Boyland they are
not smaller. Measured on the p30 section of the updated set, every character
of 9'-7 1/4" is size 3.448 and the fraction is stacked purely by offset: the
9'-7" on the baseline, the 1 half a size above it, the 4 half a size below.
`spans_of` keeps only text and size, so the offset was gone one step after it
was computed.

── MEASURED, BEFORE AND AFTER ──────────────────────────────────────────────

Across the 7 source PDFs, 173 pages, the production text path:

  101 stacked fractions were concatenated, on 20 pages.
   57 of those produced a structurally IMPOSSIBLE value (inches >= 12).
   44 produced a value that READS LIKE AN ORDINARY NUMBER, and no pattern
      over the output can find those. Among them:

        CAST IN PLACE 34" ANCHOR 12" EMBEDMENT   <- 3/4" anchor, 1/2" embedment
        SCALE: 116" = 1' - 0"                    <- 1/16"
        1 58'' DIA STEEL                         <- 1 5/8"
        334" x6,  312" x4,  9 12" x2

A 3/4" anchor bolt reported as 34" is the worst thing this reader can say.

── THE THREE PARTS, AND WHY EACH IS NEEDED ─────────────────────────────────

1. `fold_stacked_fractions` reads the geometry while it still exists. This is
   the only part that recovers the 44 plausible ones.
2. `dimension_defect` refuses a value that cannot exist. A BACKSTOP, not the
   fix — it catches the 57 impossible ones and by construction cannot catch
   `34"`, which is a perfectly good dimension that happens to be wrong here.
3. `drop_impossible_dimensions` keeps a flagged record out of an answer,
   because a flag nothing reads is decoration.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_records as pr  # noqa: E402
from lib import plan_search as ps  # noqa: E402
from lib import plan_text as pt  # noqa: E402


def ch(text, size, along, perp):
    return {"text": text, "size": size, "along": along, "perp": perp}


def line(spec, size=3.448, off=0.478):
    """A line of characters. `spec` is (text, row) with row -1 up, +1 down."""
    out = []
    a = 0.0
    for text, row in spec:
        out.append(ch(text, size, a, row * off * size))
        a += size * 0.5
    return out


class TheGeometryIsWhatSaysItIsAFraction(unittest.TestCase):
    """The real characters, at the sizes and offsets measured on the sheet."""

    def test_the_measured_case_reads_back(self):
        # 9'-7 1/4" as p30 draws it: baseline 9'-7", 1 above, 4 below, the
        # two stacked in the gap between the 7 and the inch mark.
        chars = [
            ch("9", 3.448, -5.670, 1.650), ch("'", 3.448, -4.382, 1.650),
            ch("-", 3.448, -3.479, 1.650), ch("7", 3.448, -1.947, 1.650),
            ch("1", 3.448, -0.060, 0.000),           # numerator, above
            ch("4", 3.448, -0.060, 3.300),           # denominator, below
            ch('"', 3.448, 1.484, 1.650),
        ]
        out, odd = pt.fold_stacked_fractions(chars)
        self.assertEqual("9'-7 1/4\"", "".join(c["text"] for c in out))
        self.assertEqual([], odd)

    def test_a_two_digit_denominator(self):
        chars = [
            ch("7", 1.0, 0.0, 0.0),
            ch("3", 1.0, 0.5, -0.4),
            ch("1", 1.0, 1.0, 0.4), ch("6", 1.0, 1.5, 0.4),
            ch('"', 1.0, 2.2, 0.0),
        ]
        out, _odd = pt.fold_stacked_fractions(chars)
        self.assertEqual('7 3/16"', "".join(c["text"] for c in out))

    def test_a_line_with_no_stacked_anything_is_untouched(self):
        chars = [ch(c, 3.0, i * 1.5, 0.0) for i, c in enumerate("10'-8\"")]
        out, odd = pt.fold_stacked_fractions(chars)
        self.assertEqual("10'-8\"", "".join(c["text"] for c in out))
        self.assertEqual([], odd)
        self.assertIs(out, chars, "an untouched line is returned as it came")

    def test_the_size_is_judged_locally(self):
        """A 5.18pt callout and a 0.94pt dimension share one line on SSP-003,
        and judging the dimension's 0.35pt offset against the callout's size
        hid the fraction completely. Each size cluster is judged on its own."""
        big = [ch(c, 5.181, i * 2.5, 0.0) for i, c in enumerate('4\'-0" ')]
        small = [
            ch("7", 0.937, 29.392, 0.151),
            ch("3", 0.937, 29.900, -0.089),
            ch("1", 0.937, 30.500, 0.511), ch("6", 0.937, 31.021, 0.511),
            ch('"', 0.937, 31.366, 0.151),
        ]
        out, _odd = pt.fold_stacked_fractions(big + small)
        self.assertIn('7 3/16"', "".join(c["text"] for c in out))

    def test_only_a_digit_can_be_half_of_a_fraction(self):
        """And a non-digit is LEFT WHERE IT WAS, not folded and not removed.

        The inch mark is why this matters rather than being tidiness: " sits
        high by design. On A-500.00 it was read as a numerator over the 2 of
        an adjacent 2 1/2", and folding that pair removed both characters
        from the line — 8" 21 became 8 1. Dropping a character is the same
        class of harm as running two together, so the rule is that this
        function only ever touches digits.
        """
        chars = [
            ch("8", 2.0, 0.0, 0.0),
            ch('"', 2.0, 1.0, -0.8),     # an inch mark rides high
            ch("2", 2.0, 1.0, 0.8),
            ch("1", 2.0, 2.5, 0.0),
        ]
        out, odd = pt.fold_stacked_fractions(chars)
        self.assertEqual('8"21', "".join(c["text"] for c in out),
                         "the line came back with a character missing")
        self.assertEqual([], odd)
        self.assertIs(out, chars, "nothing to do means nothing done")

    def test_an_unusual_denominator_is_reported_not_swallowed(self):
        chars = [
            ch("1", 2.0, 0.0, 0.0),
            ch("5", 2.0, 1.0, -0.8), ch("7", 2.0, 1.0, 0.8),
            ch('"', 2.0, 2.5, 0.0),
        ]
        out, odd = pt.fold_stacked_fractions(chars)
        self.assertIn("5/7", "".join(c["text"] for c in out),
                      "the offset already established it is a fraction")
        self.assertEqual(["5/7"], odd, "but 7 is not a drawing denominator")


class ADimensionThatCannotExistIsADefect(unittest.TestCase):

    def test_the_fabricated_values_are_caught(self):
        for bad in ("9'-714\"", "5'-412\"", "21'-7316\"", "43'-238\"",
                    "14'-41316\"", "2'-12\""):
            self.assertIsNotNone(pr.dimension_defect(bad), bad)

    def test_real_dimensions_are_not(self):
        for ok in ("9'-7 1/4\"", "10'-8\"", "0'-0\"", "2'-11\"", "1'-0\"",
                   "3/4\"", "7/8\"", "1 5/8\" DIA STEEL"):
            self.assertIsNone(pr.dimension_defect(ok), ok)

    def test_a_scale_a_date_and_a_model_number_are_not_dimensions(self):
        """The guard fires only on text already SHAPED like a dimension."""
        for ok in ("Scale:3/16\" = 1'-0\"", "6/13/25", "MODEL 1200-X",
                   "EF-1", "", "1 PER 25' OF STREET FRONTAGE"):
            self.assertIsNone(pr.dimension_defect(ok), ok)

    def test_it_cannot_catch_a_plausible_fabrication_and_does_not_pretend_to(self):
        """34" IS a dimension — 34 inches — so nothing structural can tell it
        from the 3/4" the drawing prints. Those 44 cases are recovered by
        reading the geometry, and by nothing else. Asserted so the guard is
        never mistaken for the fix."""
        self.assertIsNone(pr.dimension_defect('34"'))
        self.assertIsNone(
            pr.dimension_defect('CAST IN PLACE 34" ANCHOR 12" EMBEDMENT'))


class AFlaggedRecordNeverReachesAnAnswer(unittest.TestCase):
    """`verified` is written on every plan record and read by NOTHING —
    plan_search and the answer gate never consult it. So the flag needed a
    reader of its own or it would have been decoration."""

    BAD = {"record_type": "dimension", "tier": "text_layer", "page_id": "p1",
           "sheet_number": "A-500.00", "quote": "9'-714\"",
           "dimension_defect": "714 is not a number of inches",
           "payload": {"value_text": "9'-714\""}}
    GOOD = {"record_type": "dimension", "tier": "text_layer", "page_id": "p2",
            "sheet_number": "A-500.00", "quote": "9'-7 1/4\"",
            "payload": {"value_text": "9'-7 1/4\""}}

    def test_it_is_recognised_from_either_place_it_is_recorded(self):
        self.assertTrue(ps.dimension_is_impossible(self.BAD))
        self.assertTrue(ps.dimension_is_impossible(
            {"payload": {"dimension_defect": "x"}}))
        self.assertFalse(ps.dimension_is_impossible(self.GOOD))
        self.assertFalse(ps.dimension_is_impossible({}))

    def test_it_is_dropped(self):
        got = ps.drop_impossible_dimensions([self.BAD, self.GOOD])
        self.assertEqual([r["quote"] for r in got], ["9'-7 1/4\""])

    def test_it_is_dropped_even_when_it_is_all_there_is(self):
        """UNLIKE drop_indexes, which keeps an index as a pointer. An index
        still points somewhere; 9'-714" points nowhere — it is not a weaker
        reading of the real dimension, it is a different number the drawing
        does not contain. Preferring it to 'not found' is the one trade this
        reader does not make."""
        self.assertEqual([], ps.drop_impossible_dimensions([self.BAD]))

    def test_an_empty_set_stays_empty(self):
        self.assertEqual([], ps.drop_impossible_dimensions([]))
        self.assertEqual([], ps.drop_impossible_dimensions(None))


class TheWriterIsTheChokepoint(unittest.TestCase):

    def test_the_check_sits_in_emit_not_at_a_call_site(self):
        """Every record passes through emit, so no future call site can add a
        dimension that skips the check."""
        src = (Path(__file__).resolve().parents[1]
               / "lib" / "plan_records.py").read_text(encoding="utf-8")
        head = src[src.index("    def emit("):src.index("        out.append(rec)")]
        self.assertIn("dimension_defect(quote)", head)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
