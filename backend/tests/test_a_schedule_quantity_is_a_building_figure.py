"""A SCHEDULE QUANTITY IS A BUILDING FIGURE.

Measured on 588 Boyland 2026-10-10, on the rebuilt rows: a printed counting
source - a schedule's QTY cell, or an element count read from one - bound in
ANY clause naming its mark. 80 wrong answers across the four tags a printed
QTY lends a figure to (PTAC-1 21, PTAC-3 11, WH-1 9, DH-1 1), in every scoped
shape on every floor:

    "The fourth floor has 21 PTAC-1."            a floor
    "There are 9 WH-1 on A-103.00."               a floor, by its sheet
    "4A has 11 PTAC-3."                           a unit
    "Each unit on the second floor has 1 DH-1."   a per-apartment share

The schedule prints how many there are in the building; it says nothing about
any floor or unit. Rule (operator, 2026-10-10): a QTY figure binds only at
building scope. A floor or unit figure comes from the located symbols, at
their own scope, or not at all.

The fixture is production's shape: the printed schedules WITH their QTY
column AND the glyph rows with their census (the #728 condition).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as S  # noqa: E402
from tests.test_the_schedule_and_the_located_count_agree_or_neither import _world  # noqa: E402

#: the four tags a printed QTY lends a figure to on Boyland, and that figure
QTY_FIGURES = [("PTAC-1", "21"), ("PTAC-3", "11"), ("WH-1", "9"), ("DH-1", "1")]
SHAPES = [("floor", "The {floor} has {q} {t}."),
          ("floor by sheet", "There are {q} {t} on {sheet}."),
          ("unit", "{unit} has {q} {t}."),
          ("per apartment", "Each unit on the {floor} has {q} {t}.")]
FLOORS = [("fourth floor", "A-103.00", "4A"), ("third floor", "A-102.00", "3A"),
          ("mezzanine", "A-104.00", "4A"), ("bulkhead", "M-106.00", "4A")]


def _present():
    assert hasattr(S, "_building_scope"), "building scope is not in this tree"


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


class TheMeasuredReachRefuses(unittest.TestCase):
    """The 4 tags x 4 shapes measured on production, on every floor."""

    def test_no_scoped_clause_borrows_the_building_figure(self):
        """A scoped clause binds EXACTLY when the located symbols support the
        figure at that scope - as the production measurement counted it. (In
        this fixture all 11 PTAC-3 and all 9 WH-1 sit on the third floor, so
        'The third floor has 11 PTAC-3.' is true, from the symbols.)"""
        _present()
        recs = _world()
        book = S.glyph_book(recs)
        wrong, checked = [], 0
        for t, q in QTY_FIGURES:
            for shape, tmpl in SHAPES:
                for floor, sheet, unit in FLOORS:
                    s = tmpl.format(floor=floor, sheet=sheet, unit=unit, q=q, t=t)
                    by_symbols = q in S.glyph_values(s.rstrip("."), book)
                    checked += 1
                    if _ok(s, recs) != by_symbols:
                        wrong.append((shape, s, "binds" if _ok(s, recs) else "refuses"))
        self.assertEqual(wrong, [])
        self.assertEqual(checked, 64)


class TheBuildingFigureStillBinds(unittest.TestCase):

    def test_at_building_scope(self):
        _present()
        recs = _world()
        for s in ("There are 21 PTAC-1.", "There are 11 PTAC-3.", "There are 9 WH-1.",
                  "There is 1 DH-1.", "PTAC-1: 21 [M-200.00]."):
            self.assertTrue(_ok(s, recs), s)

    def test_its_source_named_alongside_is_not_a_scope(self):
        """'per the schedule' is where the figure comes from, not a share."""
        _present()
        self.assertTrue(_ok("There are 21 PTAC-1 per the schedule.", _world()))

    def test_a_per_apartment_share_of_the_whole_building_refuses(self):
        _present()
        recs = _world()
        for s in ("Each unit has 21 PTAC-1.", "There are 9 WH-1 per apartment.",
                  "Every apartment has 1 DH-1."):
            self.assertFalse(_ok(s, recs), s)


class AScopedFigureComesFromTheLocatedSymbols(unittest.TestCase):

    def test_the_true_floor_figure_binds_and_the_building_figure_does_not(self):
        _present()
        recs = _world()
        self.assertTrue(_ok("There are 4 PTAC-1 on the mezzanine.", recs))
        self.assertFalse(_ok("There are 21 PTAC-1 on the mezzanine.", recs))
        self.assertTrue(_ok("There are 17 PTAC-1 on the third floor.", recs))
        self.assertFalse(_ok("There are 21 PTAC-1 on the third floor.", recs))


if __name__ == "__main__":
    unittest.main()
