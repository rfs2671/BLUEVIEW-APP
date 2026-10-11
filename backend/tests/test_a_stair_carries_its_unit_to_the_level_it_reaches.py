"""A STAIR CARRIES ITS UNIT TO THE LEVEL IT REACHES.

588 Boyland's 4A-4D are duplexes. A-103.00 prints each "1 BEDROOM APT.
LOWER" with a private stair labelled UP; A-104.00 (the mezzanine) prints no
unit tag and no occupancy table, so M-104.00's symbols were counted at sheet
scope and never placed, and "4A has 3 exhaust fans" - the true answer -
refused.

Rule (b) (operator 2026-10-07) and rulings 2026-10-11:
  1. the sheet a stair reaches is the next plan in the series, CONFIRMED
     against the printed title ordinals where both sheets print one; a title
     that contradicts the series refuses, it is never picked between;
  2. one stair label in the unit, or no seeding;
  3. the gate sums an apartment across the sheets its stair links - only
     when every linked sheet lists the unit, each is complete, and every
     symbol there was placed; the render names both sheets;
  4. a seeded region's area is reported beside the unit's NET on its own
     floor (informational).

Measured 2026-10-11 (local, fixture PDFs): A-103 -> A-104 registers at
(-0.01, 0.00) with 1413 anchors; seeded from the four stair labels, A-104's
wall layer closes four single-unit regions (4A 482, 4B 483, 4C 443, 4D 444
sf), one quadrant each by render; M-104 places 1 EF-1, 1 PTAC-1 and 1 PTAC-2
in each - the sheet by eye.
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

from lib import plan_derive as D  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402
from tests.test_a_located_count_is_complete_or_refused import (  # noqa: E402
    PID, _census, _floor, _numbered, _pages)
from tests.test_a_sheet_it_cannot_place_still_counts import (  # noqa: E402
    EF, PTAC, WH, SAF, FAMS, QTY, _arch_refusal, _boyland, _sheet_scope)
from tests import test_a_located_count_is_complete_or_refused as _LC  # noqa: E402

_LC.FLOORS.setdefault("104", ("MEZZANINE FLOOR HVAC PLANS", ["4A", "4B", "4C", "4D"]))
_LC.FLOORS.setdefault("105", ("ROOF HVAC PLANS", []))

DUPLEX_UNITS = ("4A", "4B", "4C", "4D")
STAIRS = {"4A": (1244, 691), "4B": (1244, 893), "4C": (1505, 691), "4D": (1505, 893)}


def _present():
    assert hasattr(D, "stair_target") and hasattr(D, "title_ordinal"), \
        "no stair carries its unit to another level in this tree"


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


def _lower(linked=True):
    return {u: ["level word LOWER at (1127, 590)",
                f"stair label UP at ({x}, {y})" + (" reaches A-104.00" if linked else "")]
            for u, (x, y) in STAIRS.items()}


def _upper():
    return {u: [f"seeded from A-103.00: stair label UP at ({x}, {y})"]
            for u, (x, y) in STAIRS.items()}


def _seeded(*, linked=True, upper_placed=True):
    """Production's shape after a rebuild with seeding: floors 1-3 as now;
    A-103.00's 4A-4D link to A-104.00, where M-104.00's symbols are placed
    in the seeded units - 1 EF-1, 1 PTAC-1, 1 PTAC-2 each. Totals as
    production: EF 36, PTAC-1 21, PTAC-2 9, PTAC-3 11, WH-1 9, SAF-1 1."""
    rows = []
    for lvl, us in (("100", ("1A", "1B", "1C", "1D")), ("101", ("2A", "2B", "2C", "2D")),
                    ("102", ("3A", "3B", "3C", "3D"))):
        rows += _floor(lvl, EF, [(t, u) for u in us for t in ("EF-1", "EF-2")])
    rows += _floor("100", PTAC, [("PTAC-1", "1A"), ("PTAC-2", "1B"), ("PTAC-3", "1C"),
                                 ("PTAC-3", "1D"), ("PTAC-3", "1A")])
    for lvl, us in (("101", ("2A", "2B", "2C", "2D")), ("102", ("3A", "3B", "3C", "3D"))):
        rows += _floor(lvl, PTAC, [("PTAC-1", us[0])] * 3 + [("PTAC-1", us[2])] * 3
                       + [("PTAC-2", us[1]), ("PTAC-2", us[3]), ("PTAC-3", us[1]),
                          ("PTAC-3", us[3])])
    rows += _floor("100", WH, [("WH-1", "non-unit:PUBLIC")] * 6)
    rows += _floor("105", WH, [("WH-1", "non-unit:ROOF")] * 3)
    rows += _floor("103", EF, [(t, u) for u in DUPLEX_UNITS for t in ("EF-1", "EF-2")],
                   multi=_lower(linked))
    rows += _floor("103", PTAC, [(t, u) for u in DUPLEX_UNITS for t in ("PTAC-1", "PTAC-3")],
                   multi=_lower(linked))
    upper = (lambda u: u) if upper_placed else (lambda u: None)
    rows += _floor("104", EF, [("EF-1", upper(u)) for u in DUPLEX_UNITS], multi=_upper())
    rows += _floor("104", PTAC, [(t, upper(u)) for u in DUPLEX_UNITS
                                 for t in ("PTAC-1", "PTAC-2")], multi=_upper())
    rows += _sheet_scope("M-106.00", "BULKHEAD HVAC PLANS", SAF, [("SAF-1", 1)])
    rows += [_arch_refusal(f"A.1.{i}") for i in range(1, 8)]
    rows = _numbered(rows)
    pages = _pages(rows)
    census = []
    for c in _census(rows, pages, FAMS):
        if c.get("kind") == "family":
            c = S.glyph_census("family", PID, pages, c["count"], family=c["family"],
                               tags=c["tags"], qty=QTY.get(c["family"]))
        census.append(c)
    return rows + census


class ADuplexIsCountedWhole(unittest.TestCase):

    def test_4a_has_3_exhaust_fans_and_4_ptacs(self):
        _present()
        recs = _seeded()
        self.assertTrue(_ok("4A has 3 exhaust fans.", recs))
        self.assertTrue(_ok("4A has 4 PTAC units.", recs))
        self.assertTrue(_ok("4D has 3 exhaust fans.", recs))
        # each tag of the whole apartment: 2 EF-1 (one per level), 1 EF-2
        self.assertTrue(_ok("4A has 2 EF-1.", recs))
        self.assertTrue(_ok("4A has 1 EF-2.", recs))

    def test_half_an_apartment_still_refuses(self):
        _present()
        recs = _seeded()
        for s in ("4A has 2 exhaust fans.", "4A has 1 exhaust fan.",
                  "4A has 2 PTAC units.", "Each unit on the mezzanine has 1 EF-1.",
                  "Each unit on the fourth floor has 2 exhaust fans."):
            self.assertFalse(_ok(s, recs), s)

    def test_a_floor_named_alongside_says_which_units_not_which_part(self):
        """Ruling 2026-10-07 (2): 'each unit on the fourth floor' is the
        whole of each apartment there - 3 once the mezzanine is linked."""
        _present()
        recs = _seeded()
        self.assertTrue(_ok("Each unit on the fourth floor has 3 exhaust fans.", recs))
        self.assertTrue(_ok("4A on the mezzanine has 3 exhaust fans.", recs))
        self.assertFalse(_ok("4A on the third floor has 3 exhaust fans.", recs))

    def test_floor_and_building_totals_are_unchanged(self):
        """Every floor and building clause binds exactly what it bound with
        M-104.00 at sheet scope."""
        _present()
        new, old = S.glyph_book(_seeded()), S.glyph_book(_boyland())
        for clause in ("There are 36 exhaust fans.", "There are 21 PTAC-1.",
                       "There are 9 PTAC-2.", "There are 11 PTAC-3.", "There are 41 PTAC units.",
                       "The mezzanine has 4 EF-1.", "There are 4 PTAC-1 on the mezzanine.",
                       "There are 4 PTAC-2 on the mezzanine.",
                       "The fourth floor has 8 exhaust fans.", "There is 1 SAF-1."):
            # no subTest: pytest reports a test whose subtests failed as PASSED
            self.assertEqual(S.glyph_values(clause, new), S.glyph_values(clause, old), clause)
            self.assertTrue(S.glyph_values(clause, new), clause)

    def test_the_render_names_both_sheets(self):
        _present()
        text = S.render_glyph_evidence(_seeded())
        line = next(l for l in text.splitlines() if "FOURTH FLOOR" in l and "EF-1" in l)
        self.assertIn("each unit (4A, 4B, 4C, 4D) has 3", line)
        self.assertIn("the whole apartment, counted across A-103.00 / M-103.00 + "
                      "A-104.00 / M-104.00", line)


class ALinkMustBeFollowedToTheEnd(unittest.TestCase):

    def test_a_unit_that_continues_with_no_link_refuses(self):
        """The rows before seeding: LOWER and a stair, no 'reaches'."""
        recs = _seeded(linked=False)
        self.assertFalse(_ok("4A has 3 exhaust fans.", recs))
        self.assertFalse(_ok("4A has 2 exhaust fans.", recs))

    def test_a_linked_level_with_an_unplaced_symbol_refuses(self):
        _present()
        recs = _seeded(upper_placed=False)
        self.assertFalse(_ok("4A has 3 exhaust fans.", recs))
        self.assertFalse(_ok("4A has 2 exhaust fans.", recs))


class WhichSheetAStairReaches(unittest.TestCase):

    def test_title_ordinals(self):
        _present()
        for title, n in (("FOURTH FLOOR PLAN", 4), ("4TH FLOOR FRAMING PLAN", 4),
                         ("MEZZANINE PLAN", None), ("ROOF AND BULKEAD PLAN", None),
                         ("FIRST AND SECOND FLOOR PLANS", None),
                         ("FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN", None)):
            self.assertEqual(D.title_ordinal(title), n, title)

    def test_the_series_decides_where_no_title_contradicts_it(self):
        _present()
        a103 = {"sheet_number": "A-103.00", "sheet_title": "FOURTH FLOOR PLAN"}
        plans = [a103, {"sheet_number": "A-104.00", "sheet_title": "MEZZANINE PLAN"},
                 {"sheet_number": "A-102.00", "sheet_title": "THIRD FLOOR PLAN"}]
        self.assertEqual(D.stair_target(a103, "UP", plans)[0]["sheet_number"], "A-104.00")
        self.assertEqual(D.stair_target(a103, "DN", plans)[0]["sheet_number"], "A-102.00")

    def test_a_title_that_contradicts_the_series_refuses(self):
        _present()
        a103 = {"sheet_number": "A-103.00", "sheet_title": "FOURTH FLOOR PLAN"}
        plans = [a103, {"sheet_number": "A-104.00", "sheet_title": "SIXTH FLOOR PLAN"}]
        target, why = D.stair_target(a103, "UP", plans)
        self.assertIsNone(target)
        self.assertIn("the title and the series disagree", why)


def _fake_floor(sheet, title, stairs, tags=("4A",), units_tags=True):
    return {"arch_p": {"sheet_number": sheet, "sheet_title": title}, "a_sheet": sheet,
            "data": {"words": []},
            "units": {"tags": list(tags) if units_tags else None, "multi_level": {}},
            "stairs": stairs}


class WhatIsNotSeeded(unittest.TestCase):

    def _seed(self, floors):
        from lib import plan_glyph_pass as G
        return G.seed_from_stairs(floors, lambda p: None, 56.0)

    def test_a_unit_with_two_stair_labels_is_not_seeded(self):
        _present()
        src = _fake_floor("A-103.00", "FOURTH FLOOR PLAN",
                          {"4A": [("UP", 1244.0, 691.0), ("DN", 1260.0, 700.0)]})
        tgt = _fake_floor("A-104.00", "MEZZANINE PLAN", {}, tags=(), units_tags=False)
        notes = self._seed([src, tgt])
        self.assertIsNone(tgt["units"]["tags"])
        self.assertTrue(any("2 stair labels" in n and "not seeded" in n for n in notes), notes)

    def test_a_contradicting_title_is_not_seeded(self):
        _present()
        src = _fake_floor("A-103.00", "FOURTH FLOOR PLAN", {"4A": [("UP", 1244.0, 691.0)]})
        tgt = _fake_floor("A-104.00", "SIXTH FLOOR PLAN", {}, tags=(), units_tags=False)
        notes = self._seed([src, tgt])
        self.assertIsNone(tgt["units"]["tags"])
        self.assertTrue(any("the title and the series disagree" in n for n in notes), notes)

    def test_a_plan_that_names_its_own_units_is_not_seeded(self):
        _present()
        src = _fake_floor("A-103.00", "FOURTH FLOOR PLAN", {"4A": [("UP", 1244.0, 691.0)]})
        tgt = _fake_floor("A-104.00", "MEZZANINE PLAN", {}, tags=("5A",))
        notes = self._seed([src, tgt])
        self.assertEqual(tgt["units"]["tags"], ["5A"])
        self.assertTrue(any("names its own units" in n for n in notes), notes)


# ── on the real sheets ─────────────────────────────────────────────────────

class OnTheRealSheets(unittest.TestCase):
    """A-103.00 seeds A-104.00 through the pass's own reading. Loaded once,
    inside the first test: a presence check in setUpClass reports as an
    ERROR, not a failure by assertion."""

    _done = False

    @classmethod
    def _load(cls):
        if cls._done:
            return
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet
        from lib.plan_space import build_space
        from lib.plan_takeoff import Units
        from lib import plan_glyph_pass as G
        pdf = str(require_pdf("Owners set - 6.9.26.pdf"))
        cls.pages = {n: PlanPage(pdf, n) for n in (4, 5)}
        a3, a4 = load_sheet(cls.pages[4]), load_sheet(cls.pages[5])
        u3 = D.unit_tags(a3["words"], a3["corners"])
        sp3 = build_space(cls.pages[4], u3["tags"], 56.0, a3)
        member = Units(sp3["units"], sp3["lo"], sp3["cell_pt"], sp3["refused"], sp3, sp3["tags"])
        cls.src = {"arch_p": {"sheet_number": "A-103.00", "sheet_title": "FOURTH FLOOR PLAN"},
                   "a_sheet": "A-103.00", "data": a3, "space": sp3,
                   "units": dict(u3, multi_level=D.multi_level_units(
                       cls.pages[4].directed_words, member.at, u3["tags"])),
                   "stairs": D.unit_stairs(cls.pages[4].directed_words, member.at, u3["tags"])}
        cls.tgt = {"arch_p": {"sheet_number": "A-104.00", "sheet_title": "MEZZANINE PLAN"},
                   "a_sheet": "A-104.00", "data": a4,
                   "units": D.unit_tags(a4["words"], a4["corners"])}
        cls.notes = G.seed_from_stairs([cls.src, cls.tgt], lambda p: cls.pages[5], 56.0)
        cls._done = True

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "pages", {}).values():
            p.close()

    def test_four_units_seeded_one_region_each(self):
        _present()
        self._load()
        u = self.tgt["units"]
        self.assertEqual(u["tags"], ["4A", "4B", "4C", "4D"], self.notes)
        self.assertEqual(u["method"], "stair_seeded")
        self.assertEqual(self.tgt["space"]["refused"], [])
        self.assertEqual(self.tgt["space"].get("incomplete") or {}, {})
        areas = {t: s_["area_sf"] for t, s_ in u["seeded"].items()}
        self.assertEqual(areas, {"4A": 482, "4B": 483, "4C": 443, "4D": 444})

    def test_the_area_is_reported_against_the_net_on_its_own_floor(self):
        _present()
        self._load()
        s_ = self.tgt["units"]["seeded"]["4A"]
        self.assertEqual((s_["from"], s_["net_on"]), ("A-103.00", "A-103.00"))
        self.assertEqual(s_["net_sf_on_own_floor"], 507)
        self.assertAlmostEqual(s_["ratio"], round(482 / 507, 2))

    def test_both_sheets_name_the_link(self):
        _present()
        self._load()
        self.assertIn("stair label UP at (1244, 691) reaches A-104.00",
                      self.src["units"]["multi_level"]["4A"])
        self.assertEqual(self.tgt["units"]["multi_level"]["4A"],
                         ["seeded from A-103.00: stair label UP at (1244, 691)"])


if __name__ == "__main__":
    unittest.main()
