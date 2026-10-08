"""A UNIT COUNT IS THE WHOLE APARTMENT.

Measured on 588 Boyland 2026-10-07: the gate bound "4A has 2 exhaust fans."
4A is a duplex. A-103.00 prints it "1 BEDROOM APT. LOWER", and its private
stair ("UP 16") lands on the mezzanine, where M-104.00 gives it a third fan.
The mezzanine is refused (A-104.00 names no units), so the 2 was A-103.00's
half of the apartment, stated as the apartment.

Rulings (operator, 2026-10-07):
  detection   a unit continues on another sheet when a level word (LOWER,
              UPPER, ...) or a stair label (UP / DN) sits INSIDE it - either
              one. The core stair sits outside every unit.
  the pass    records each unit's evidence on its rows (emit_version 2);
  the gate    unit scope - a named unit, or each/per unit - is the whole
              apartment, and binds only for a unit the rows say is
              single-sheet. "Each unit on the fourth floor has 2" refuses: a
              floor named alongside says which units, not which part.
  fail closed rows that never read the evidence (emit_version 1) refuse unit
              scope on their floor - the correct floors too - until the pass
              is re-run. Floor scope stays.

Every test fails on main by assertion.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_derive as D  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402
from tests.test_a_located_count_is_complete_or_refused import (  # noqa: E402
    EF, FLOORS, _census, _floor, _numbered, _pages, _refusal)

FOURTH = ("4A", "4B", "4C", "4D")
THIRD = ("3A", "3B", "3C", "3D")
#: what A-103.00 prints inside each duplex, as the pass records it
DUPLEX = {u: ["level word LOWER", "stair label UP"] for u in FOURTH}


def _present():
    assert hasattr(D, "multi_level_units"), "plan_derive.multi_level_units is not in this tree"


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


def _world(fourth="duplex", third="single"):
    """EF on the fourth floor (2 per unit) and the third (2 per unit), the
    mezzanine refused - Boyland's shape. `fourth` / `third`: "duplex"
    (DUPLEX evidence), "single", or None (a version-1 row)."""
    def ev(kind):
        return {"duplex": DUPLEX, "single": "single", None: None}[kind]
    rows = _floor("103", EF, [(t, u) for u in FOURTH for t in ("EF-1", "EF-2")],
                  multi=ev(fourth))
    rows += _floor("102", EF, [(t, u) for u in THIRD for t in ("EF-1", "EF-2")],
                   multi=ev(third))
    rows.append(_refusal("M-104.00", "A-104.00: no occupancy table and no unit tags on the sheet"))
    rows = _numbered(rows)
    return rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})


class TheDuplexRefusesAtUnitScope(unittest.TestCase):

    def test_4a_has_2_exhaust_fans_refuses(self):
        _present()
        self.assertFalse(_ok("4A has 2 exhaust fans.", _world()))
        self.assertFalse(_ok("4A has 1 EF-1.", _world()))

    def test_each_unit_on_the_fourth_floor_has_2_refuses(self):
        """Read as per apartment, and each apartment has 3."""
        _present()
        self.assertFalse(_ok("Each unit on the fourth floor has 2 exhaust fans.", _world()))
        self.assertFalse(_ok("Each unit on A-103.00 has 2 exhaust fans.", _world()))

    def test_the_floor_total_stays(self):
        _present()
        self.assertTrue(_ok("The fourth floor has 8 exhaust fans.", _world()))
        self.assertTrue(_ok("There are 4 EF-1 on the fourth floor.", _world()))

    def test_a_floor_named_alongside_does_not_rescue_it(self):
        _present()
        self.assertFalse(_ok("4A on the fourth floor has 2 exhaust fans.", _world()))


class RowsThatNeverReadItFailClosed(unittest.TestCase):

    def test_a_correct_floor_refuses_unit_scope_until_the_rebuild(self):
        """Floor 3 has no duplex - and its version-1 rows cannot say so."""
        _present()
        old = _world(fourth=None, third=None)
        for s in ("3A has 2 exhaust fans.", "Each unit on the third floor has 2 exhaust fans.",
                  "4A has 2 exhaust fans."):
            self.assertFalse(_ok(s, old), s)
        self.assertTrue(_ok("The third floor has 8 exhaust fans.", old))

    def test_one_old_row_makes_its_floor_unknown(self):
        _present()
        rows = (_floor("102", EF, [("EF-1", u) for u in THIRD], multi="single")
                + _floor("102", EF, [("EF-2", u) for u in THIRD], multi=None))
        rows = _numbered(rows)
        recs = rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})
        self.assertFalse(_ok("3A has 2 exhaust fans.", recs))


class FloorsOneToThreeBindAfterTheRebuild(unittest.TestCase):

    def test_the_single_sheet_floor_binds_while_the_duplex_floor_refuses(self):
        _present()
        new = _world()
        self.assertTrue(_ok("3A has 2 exhaust fans.", new))
        self.assertTrue(_ok("Each unit on the third floor has 2 exhaust fans.", new))
        self.assertFalse(_ok("4A has 2 exhaust fans.", new))

    def test_the_render_says_which_apartments_continue(self):
        _present()
        text = S.render_glyph_evidence(_world())
        self.assertIn("4A, 4B, 4C, 4D continue on another sheet", text)
        self.assertIn("each unit (3A, 3B, 3C, 3D) has 2", text)
        old = S.render_glyph_evidence(_world(fourth=None, third=None))
        self.assertIn("predate", old)
        self.assertNotIn("each unit", old)


class TheDetection(unittest.TestCase):

    @staticmethod
    def _at(x, y):
        """4A west of x=100, 4B to x=200, a refused merged region to 300,
        then the core."""
        return "4A" if x < 100 else "4B" if x < 200 else "!4C,4D" if x < 300 else ""

    def test_either_signal_marks_the_unit_and_every_unit_gets_a_key(self):
        _present()
        words = [("LOWER", 50, 10, "ltr"), ("UP", 150, 20, "ltr")]
        got = D.multi_level_units(words, self._at, ["4A", "4B", "4C"])
        self.assertEqual(set(got), {"4A", "4B", "4C"})
        self.assertTrue(got["4A"] and "LOWER" in got["4A"][0])
        self.assertTrue(got["4B"] and "UP" in got["4B"][0])
        self.assertEqual(got["4C"], [])

    def test_the_core_stair_and_a_merged_region_mark_nothing(self):
        _present()
        words = [("UP", 400, 20, "ltr"), ("DN", 410, 20, "ltr"), ("LOWER", 250, 5, "ltr")]
        got = D.multi_level_units(words, self._at, ["4A", "4B"])
        self.assertEqual(got, {"4A": [], "4B": []})

    def test_ordinary_words_mark_nothing(self):
        _present()
        words = [("UPDATE", 50, 1, "ltr"), ("BEDROOM", 50, 2, "ltr"), ("4A", 50, 3, "ltr")]
        self.assertEqual(D.multi_level_units(words, self._at, ["4A"]), {"4A": []})


class ThePassRecordsItOnEveryRow(unittest.TestCase):

    def test_rows_carry_the_evidence_and_the_new_version(self):
        _present()
        from lib import plan_glyph_pass as G

        class FakeUnits:
            def __init__(self, *a, **k):
                pass

            def at(self, x, y):
                return "4A" if x < 100 else "4B" if x < 200 else ""

        class Page:
            directed_words = [("LOWER", 50, 10, "ltr"), ("UP", 60, 20, "ltr"),
                              ("UP", 500, 20, "ltr")]

        title, _units = FLOORS["103"]
        pages = [{"page_id": "pa", "sheet_number": "A-103.00", "sheet_title": "FOURTH FLOOR PLAN"},
                 {"page_id": "pm", "sheet_number": "M-103.00", "sheet_title": title}]
        schedules = [{"name": EF, "tier": "ocr_grid_cell", "sheet_number": "M-200.00",
                      "columns": [{"header": "TAG", "role": "identifier"}],
                      "rows": [["EF-1"], ["EF-2"]]}]
        takeoff = {"records": [{"tag": "EF-1", "unit": "4A", "glyph_status": "resolved",
                                "placement": "placed", "label_text": "EF-1(50)"}],
                   "method": "layers", "registration": {"usable": True}}
        with patch.object(D, "unit_tags", lambda w, c: {
                "tags": ["4A", "4B"], "method": "occupancy_table", "zero_units": False,
                "why": None}), \
                patch("lib.plan_sheet.load_sheet", lambda pg: {"words": [], "corners": [], "segs": []}), \
                patch("lib.plan_space.build_space", lambda *a, **k: {
                    "units": {}, "lo": (0, 0), "cell_pt": 1.0, "refused": [], "tags": {},
                    "method": "layers"}), \
                patch("lib.plan_takeoff.Units", FakeUnits), \
                patch("lib.plan_takeoff.sweep", lambda *a, **k: []), \
                patch("lib.plan_takeoff.run_takeoff", lambda *a, **k: takeoff):
            out = G.run_pass(pages, lambda p: Page(), schedules, [])
        located = [r for r in out["rows"] if r.get("label")]
        self.assertTrue(located)
        for r in located:
            ml = r["payload"]["units"]["multi_level"]
            self.assertEqual(set(ml), {"4A", "4B"})
            self.assertEqual(len(ml["4A"]), 2)          # LOWER and the private UP
            self.assertEqual(ml["4B"], [])
            # 2 introduced multi_level; later versions keep it
            self.assertEqual(r["payload"]["emit_version"], E.EMIT_VERSION)
        self.assertGreaterEqual(E.EMIT_VERSION, 2)


class OnTheRealSheets(unittest.TestCase):
    """The measurement of 2026-10-07, held: A-103.00's four apartments, and
    nothing on A-102.00 or A-100.01. Needs the source-PDF fixtures."""

    def _evidence(self, fname, page_no):
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet
        from lib.plan_space import build_space
        from lib.plan_takeoff import Units
        # CLOSED EXPLICITLY, page before document. Left to the garbage
        # collector, the document can be freed before its page, and pdfium
        # faults: the first fixture run of this file died with a Windows
        # access violation inside pytest's unraisable-exception collector.
        pg = PlanPage(require_pdf(fname), page_no)
        try:
            sheet = load_sheet(pg)
            tags = D.unit_tags(sheet["words"], sheet["corners"])["tags"]
            space = build_space(pg, tags, 56.0, sheet)
            member = Units(space["units"], space["lo"], space["cell_pt"], space["refused"],
                           space, space["tags"])
            return D.multi_level_units(pg.directed_words, member.at, tags)
        finally:
            pg.close()

    def test_a103_four_duplexes_by_both_signals(self):
        _present()
        got = self._evidence("Owners set - 6.9.26.pdf", 4)
        self.assertEqual(sorted(got), list(FOURTH))
        for u in FOURTH:
            kinds = " ".join(got[u])
            self.assertIn("LOWER", kinds, u)
            self.assertIn("stair label UP", kinds, u)

    def test_a102_and_a100_are_single_sheet(self):
        _present()
        for fname, page_no in (("Owners set - 6.9.26.pdf", 3), ("AR - 8.18.26.pdf", 6)):
            got = self._evidence(fname, page_no)
            self.assertTrue(got, fname)
            self.assertEqual({u: v for u, v in got.items() if v}, {}, fname)


if __name__ == "__main__":
    unittest.main()
