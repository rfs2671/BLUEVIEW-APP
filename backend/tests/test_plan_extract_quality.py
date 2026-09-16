"""Extraction may report what is PRINTED, and nothing else.

Measured on the 588 Boyland index, 2026-09-16, while deriving a concept
vocabulary from the corpus. The corpus could not be used, because:

  * 39% of legend payload was symbol == meaning
  * 23 of 117 symbols carried conflicting meanings, some of them the model
    expanding an abbreviation it could not read: KE 1 = KICKER 1 beside
    KITCHEN EXHAUST 1, TE 1 = THERMOSTATIC EXPANSION VALVE 1 beside TOILET
    EXHAUST 1
  * 7 of 9 element records were sentence fragments carrying a count
  * two schedule names were mirrored text off a rotated page

Agreement across sheets does not filter any of it: the same legend is misread
the same way on every sheet it appears on, so a guess corroborates itself.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_extract as pe  # noqa: E402
from lib import plan_text as pt  # noqa: E402


def block(lines, bbox):
    """The raw page-dict shape layout_from_dict reads."""
    return {"type": 0, "bbox": list(bbox),
            "lines": [{"spans": [{"text": l, "size": 10.0}]} for l in lines]}


def lb(text, bbox):
    """The layout shape legend_from_blocks reads: lines are strings."""
    return {"bbox": [float(v) for v in bbox], "lines": text.splitlines(), "text": text}


class AMarkTheSheetDoesNotExplain(unittest.TestCase):
    """The M-set legend prints KE 1 and TE 1 against exhaust ducts. The model
    returned KICKER 1 and THERMOSTATIC EXPANSION VALVE 1 for them on the
    sheets where it could not read the expansion."""

    PAGE = ("MECHANICAL LEGEND\n"
            "KE 1 KITCHEN EXHAUST 1\n"
            "TE 1 TOILET EXHAUST 1\n"
            "SA 1 SUPPLY AIR 1\n"
            + "GENERAL MECHANICAL NOTES. " * 24)

    def test_a_meaning_the_page_prints_is_kept(self):
        out, flags = pe.constrain_legend_to_page(
            [{"symbol": "KE 1", "meaning": "KITCHEN EXHAUST 1"}], self.PAGE)
        self.assertEqual(out, [{"symbol": "KE 1", "meaning": "KITCHEN EXHAUST 1",
                                "verified": True, "tier": pe.TIER_TAG_LEGEND}])
        self.assertEqual(flags, [])

    def test_a_meaning_the_page_does_not_print_is_removed(self):
        out, flags = pe.constrain_legend_to_page(
            [{"symbol": "KE 1", "meaning": "KICKER 1"},
             {"symbol": "TE 1", "meaning": "THERMOSTATIC EXPANSION VALVE 1"}],
            self.PAGE)
        self.assertEqual([(e["symbol"], e["meaning"]) for e in out],
                         [("KE 1", ""), ("TE 1", "")])
        # The words are kept as a LABEL at the vision tier: they widen what the
        # search finds and never become what the reader is shown.
        self.assertEqual([(e["label"], e["tier"]) for e in out],
                         [("KICKER 1", pe.TIER_VISION),
                          ("THERMOSTATIC EXPANSION VALVE 1", pe.TIER_VISION)])
        self.assertEqual(flags, ["legend_meaning_not_printed:2"])

    def test_the_mark_survives_its_meaning(self):
        # 'KE 1' is a true record of what is on the sheet. It is the answer to
        # "what is KE 1" — the sheet does not say — and it keeps the mark
        # countable and searchable.
        out, _ = pe.constrain_legend_to_page(
            [{"symbol": "KE 1", "meaning": "KICKER 1"}], self.PAGE)
        self.assertEqual(out[0]["symbol"], "KE 1")

    def test_a_meaning_with_no_symbol_is_dropped_outright(self):
        out, flags = pe.constrain_legend_to_page(
            [{"symbol": "", "meaning": "KICKER"}], self.PAGE)
        self.assertEqual(out, [])
        self.assertEqual(flags, ["legend_meaning_not_printed:1"])

    def test_a_page_with_no_text_layer_cannot_check_itself(self):
        # A scanned sheet: the model is the only reader there is. The entries
        # stay and say they were not verified, exactly as a schedule read off
        # the image does.
        out, flags = pe.constrain_legend_to_page(
            [{"symbol": "KE 1", "meaning": "KICKER 1"}], "M-200.00\nP:\nE:\nW:\n9")
        self.assertEqual(out, [{"symbol": "KE 1", "meaning": "KICKER 1",
                                "verified": False, "tier": pe.TIER_VISION}])
        self.assertEqual(flags, ["legend_unverifiable:1"])


class ALegendIsTwoColumns(unittest.TestCase):

    def test_a_mark_pairs_with_the_text_on_its_own_row(self):
        blocks = [
            lb("LEGEND", (100, 100, 140, 110)),
            lb("PTAC-1", (100, 130, 130, 140)),
            lb("PACKAGE TERMINAL AIR CONDITIONER", (150, 131, 340, 141)),
            lb("EF-1", (100, 160, 128, 170)),
            lb("EXHAUST FAN", (150, 161, 230, 171)),
        ]
        entries, _ = pt.legend_from_blocks(blocks)
        self.assertEqual({e["symbol"]: e["meaning"] for e in entries if e["symbol"]},
                         {"PTAC-1": "PACKAGE TERMINAL AIR CONDITIONER",
                          "EF-1": "EXHAUST FAN"})

    def test_text_on_another_row_is_never_borrowed(self):
        """The architectural fault: 'EXIT SIGN = 2.5" STUD, 1 LAYER GYB.' The
        wall types are a different column of a different table, and radius
        matching reached across to them."""
        blocks = [
            lb("LEGEND", (100, 100, 140, 110)),
            lb("SD", (100, 130, 118, 140)),
            lb('2.5" STUD, 1 LAYER GYB.', (150, 300, 320, 310)),
        ]
        entries, _ = pt.legend_from_blocks(blocks)
        marks = {e["symbol"]: e["meaning"] for e in entries if e["symbol"]}
        self.assertEqual(marks, {"SD": ""}, "a mark two rows away means nothing")

    def test_a_symbol_is_a_mark_not_a_short_phrase(self):
        for mark in ("A", "W1", "PTAC-1", "RD OD", "DHW&R", "KE 1"):
            with self.subTest(mark=mark):
                self.assertTrue(pt._looks_like_a_symbol(mark))
        for phrase in ("PTAC UNIT", "EXIT SIGN", "EXHAUST FAN", "ROOF DRAIN OUTLET"):
            with self.subTest(phrase=phrase):
                self.assertFalse(pt._looks_like_a_symbol(phrase))


class TheTagListComesFromTheSheet(unittest.TestCase):

    def test_a_legend_mark_is_added_to_the_vocabulary(self):
        blocks = [
            lb("LEGEND", (100, 100, 140, 110)),
            lb("RD OD", (100, 130, 140, 140)),
            lb("ROOF DRAIN OUTLET", (150, 131, 280, 141)),
        ]
        vocab = pt.tag_vocabulary([{"blocks": blocks, "tables": []}])
        self.assertIn("RD OD", vocab)

    def test_the_seed_set_is_still_there(self):
        self.assertTrue(pt.SEED_TAGS <= pt.tag_vocabulary([]))


class AMirroredLineIsNotAQuote(unittest.TestCase):
    """'"6-'5 33'-0" GNIDLIUB PROPOSED 4 STORY' — a schedule name off a rotated
    page. A reversed string inside a citation is a fabrication that looks
    verified, and no check downstream can tell it from a real quote."""

    @staticmethod
    def _chars(word, x0, step):
        return [{"text": c, "size": 10.0, "x0": x0 + step * i, "x1": x0 + step * i + 6,
                 "top": 100, "bottom": 110, "matrix": (1, 0, 0, 1, x0 + step * i, 100)}
                for i, c in enumerate(word)]

    def test_a_line_written_right_to_left_is_turned_back(self):
        d = pt.page_dict_from_chars(self._chars("GNIDLIUB", 200, -6))
        L = pt.layout_from_dict(d, width=800, height=600, page_number=1)
        self.assertEqual(L["text"], "BUILDING")
        self.assertEqual(L["lines_mirrored"], 1)
        self.assertEqual(L["lines_dropped_mirrored"], 0)

    def test_a_line_written_left_to_right_is_left_alone(self):
        d = pt.page_dict_from_chars(self._chars("BUILDING", 200, 6))
        L = pt.layout_from_dict(d, width=800, height=600, page_number=1)
        self.assertEqual(L["text"], "BUILDING")
        self.assertEqual(L["lines_mirrored"], 0)

    def test_two_lines_drawn_in_opposite_directions_are_each_read_correctly(self):
        # A step wider than _LINE_ALONG_BACK starts a new line, so these are
        # two lines, not one, and each is internally consistent.
        d = pt.page_dict_from_chars(self._chars("DESOPORP", 200, -6)
                                    + self._chars("XX", 400, 6))
        L = pt.layout_from_dict(d, width=800, height=600, page_number=1)
        self.assertIn("PROPOSED", L["text"])
        self.assertNotIn("DESOPORP", L["text"])

    def test_a_line_that_doubles_back_is_dropped_rather_than_quoted(self):
        # Backwards, backwards, backwards, forwards: the order the glyphs were
        # drawn in no longer tells us the order they are read in, so there is
        # no safe string to quote.
        xs = [200, 194, 188, 182, 188]
        chars = [{"text": c, "size": 10.0, "x0": x, "x1": x + 6,
                  "top": 100, "bottom": 110, "matrix": (1, 0, 0, 1, x, 100)}
                 for c, x in zip("ABCDE", xs)]
        L = pt.layout_from_dict(pt.page_dict_from_chars(chars),
                                width=800, height=600, page_number=1)
        self.assertEqual(L["text"], "")
        self.assertEqual(L["lines_dropped_mirrored"], 1)


class TheSameMarkInTwoDisciplines(unittest.TestCase):
    """'S' is the sanitary stack on five plumbing sheets, the storm stack on
    two, and a smoke detector on one architectural sheet. All three are
    correct. Nothing may merge them into one project-wide meaning."""

    def test_a_record_carries_the_discipline_it_was_read_in(self):
        import inspect
        import server
        src = inspect.getsource(server._write_page_chunks)
        self.assertIn('"discipline"', src)
        self.assertIn("discipline: Optional[str] = None", src)

    def test_every_caller_passes_it(self):
        import inspect
        import server
        src = inspect.getsource(server._index_single_page)
        self.assertEqual(src.count("_write_page_chunks("),
                         src.count("discipline=discipline"))


if __name__ == "__main__":
    unittest.main()
