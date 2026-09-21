"""A TOTAL MAY NOT REST ON A RECORD THAT DOES NOT KNOW WHAT IT IS.

Nor on a unit that was never registered. Both refusals are partial: the
resolved part is still true and still quotable, and the remainder is STATED
rather than counted or dropped.

The numbers below are the real ones from M-103.00 of the Boyland set: eight
exhaust fan glyphs, four EF-1 and four EF-2, one per type per apartment.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_tally as pt  # noqa: E402

UNITS = ("4A", "4B", "4C", "4D")


def _eight():
    out = []
    for u in UNITS:
        out.append({"tag": "EF-1", "unit": u, "status": pt.RESOLVED})
        out.append({"tag": "EF-2", "unit": u, "status": pt.RESOLVED})
    return out


class TheCleanCase(unittest.TestCase):

    def test_eight_resolved_glyphs_bind_a_total(self):
        t = pt.tally(_eight(), UNITS)
        self.assertTrue(t.bound)
        self.assertEqual(t.total, 8)
        self.assertEqual(t.by_tag, {"EF-1": 4, "EF-2": 4})

    def test_and_a_per_unit_figure(self):
        t = pt.tally(_eight(), UNITS)
        self.assertEqual(pt.per_unit(t), {"4A": 2, "4B": 2, "4C": 2, "4D": 2})

    def test_the_statement_leads_with_what_is_bound(self):
        s = pt.statement(pt.tally(_eight(), UNITS), "exhaust fan")
        self.assertIn("4 EF-1 located", s)
        self.assertIn("4 EF-2 located", s)


class AnUnnamedGlyphBreaksTheTotalButNotTheAnswer(unittest.TestCase):
    """The case that decided the rule: one of eight fans unread. `8` must not
    be available, `7` must be, and the eighth must be mentioned."""

    def _seven_and_one(self, status):
        recs = _eight()
        recs[-1] = {"tag": None, "unit": "4D", "status": status}
        return recs

    def test_the_total_is_refused(self):
        for status in (pt.UNREAD, pt.CONTESTED):
            t = pt.tally(self._seven_and_one(status), UNITS)
            self.assertFalse(t.bound, status)
            self.assertIsNone(t.total, status)

    def test_but_seven_is_still_bound(self):
        t = pt.tally(self._seven_and_one(pt.UNREAD), UNITS)
        self.assertEqual(t.resolved, 7)
        self.assertEqual(t.by_tag, {"EF-1": 4, "EF-2": 3})

    def test_and_the_remainder_is_stated_not_dropped(self):
        s = pt.statement(pt.tally(self._seven_and_one(pt.UNREAD), UNITS),
                         "EF glyph")
        self.assertIn("4 EF-1 located", s)
        self.assertIn("3 EF-2 located", s)
        self.assertIn("1 more EF glyph in 4D unread", s)

    def test_a_contested_glyph_says_contested(self):
        s = pt.statement(pt.tally(self._seven_and_one(pt.CONTESTED), UNITS),
                         "EF glyph")
        self.assertIn("contested", s)

    def test_per_unit_is_withheld_too(self):
        """Three units at 2 and one at 1-plus-an-unknown is not a per-unit
        figure; quoting it invites the reader to complete the pattern."""
        t = pt.tally(self._seven_and_one(pt.UNREAD), UNITS)
        self.assertIsNone(pt.per_unit(t))

    def test_a_record_with_no_status_but_no_tag_is_unresolved(self):
        """Defaulting a missing status to resolved would let a record with no
        tag be counted. The default is derived from the tag, not assumed."""
        t = pt.tally([{"tag": None, "unit": "4A"}], UNITS)
        self.assertFalse(t.bound)
        self.assertEqual(t.resolved, 0)


class AUnitThatWasNeverRegisteredIsNotAUnitWithZero(unittest.TestCase):

    def test_an_unregistered_unit_refuses_the_total(self):
        recs = [r for r in _eight() if r["unit"] != "4D"]
        t = pt.tally(recs, UNITS, unregistered_units=["4D"])
        self.assertFalse(t.bound)
        self.assertEqual(t.unsupported_units, ["4D"])

    def test_and_says_so_rather_than_reporting_zero(self):
        recs = [r for r in _eight() if r["unit"] != "4D"]
        s = pt.statement(pt.tally(recs, UNITS, unregistered_units=["4D"]),
                         "exhaust fan")
        self.assertIn("4D", s)
        self.assertIn("unsupported", s)
        self.assertIn("not zero", s)

    def test_per_unit_is_withheld_for_all_units_not_just_the_missing_one(self):
        """Reporting three units as "2 each" invites the fourth to be read as
        the same. It is not known at all."""
        recs = [r for r in _eight() if r["unit"] != "4D"]
        self.assertIsNone(
            pt.per_unit(pt.tally(recs, UNITS, unregistered_units=["4D"])))

    def test_a_unit_that_simply_has_none_is_a_count_of_none(self):
        """NOT DERIVED FROM ABSENCE. 4D holding no EF-2 is a true count of
        zero EF-2 in 4D. Only a unit that could not be REGISTERED is unknown,
        and that has to be said explicitly - deriving it from absence made a
        tally announce "no registration for 4D" when 4D was registered and
        merely had none of the tag being counted."""
        recs = [r for r in _eight() if not (r["unit"] == "4D"
                                            and r["tag"] == "EF-2")]
        t = pt.tally(recs, UNITS)
        self.assertTrue(t.bound)
        self.assertEqual(t.total, 7)
        self.assertEqual(t.unsupported_units, [])
        self.assertEqual(pt.per_unit(t)["4D"], 1)

    def test_sheet_scope_still_works_with_no_units(self):
        """No architectural partner: the sheet can still say how many glyphs
        it carries, and must not say which unit.

        `per_unit` is None and NOT an empty dict. An empty dict reads as "no
        unit has any of these", which is false — eight of them are on the
        sheet. None says the split cannot be made, which is the true thing."""
        recs = [{"tag": "EF-1", "unit": None, "status": pt.RESOLVED}
                for _ in range(8)]
        t = pt.tally(recs, scope_units=None)
        self.assertTrue(t.bound)
        self.assertEqual(t.total, 8)
        self.assertEqual(t.by_unit, {})
        self.assertIsNone(pt.per_unit(t))
        self.assertEqual(pt.unplaced(t), 8)


class ALocatedSymbolWithNoUnitBreaksTheSplitNotTheTotal(unittest.TestCase):
    """FOUND BY FIXING A CROP. With the sheet's right edge no longer clipped,
    one of eight exhaust fans could not be placed in a unit. The total was
    right at 8 and the distribution came back {4A: 1, 4B: 2, 4C: 2, 4D: 2} -
    4A reading as one when the unplaced fan is very likely its second.

    A right total with a wrong distribution is worse than either missing."""

    def _seven_placed_one_not(self):
        recs = _eight()
        recs[0] = {"tag": "EF-1", "unit": None, "status": pt.RESOLVED}
        return recs

    def test_the_total_still_holds(self):
        t = pt.tally(self._seven_placed_one_not(), UNITS)
        self.assertTrue(t.bound)
        self.assertEqual(t.total, 8)

    def test_but_the_per_unit_split_is_withheld(self):
        t = pt.tally(self._seven_placed_one_not(), UNITS)
        self.assertEqual(pt.unplaced(t), 1)
        self.assertIsNone(pt.per_unit(t))

    def test_and_the_statement_says_which_it_is(self):
        s = pt.statement(pt.tally(self._seven_placed_one_not(), UNITS),
                         "exhaust fan")
        self.assertIn("could not be placed", s)
        self.assertIn("total still holds", s)

    def test_all_placed_means_no_unplaced(self):
        self.assertEqual(pt.unplaced(pt.tally(_eight(), UNITS)), 0)


class TheStatementIsNeverEmptyWhenThereIsSomethingToSay(unittest.TestCase):

    def test_an_all_unread_tally_still_reports(self):
        t = pt.tally([{"tag": None, "unit": "4A", "status": pt.UNREAD}], UNITS)
        s = pt.statement(t, "EF glyph")
        self.assertTrue(s.strip())
        self.assertIn("unread", s)

    def test_an_empty_tally_says_nothing_rather_than_zero(self):
        self.assertEqual(pt.statement(pt.tally([], None)), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
