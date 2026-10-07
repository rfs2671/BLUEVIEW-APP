"""A COUNT BINDS ONLY FROM A COUNTING SOURCE.

Measured on 588 Boyland 2026-10-07, on the rebuilt production rows, after
#664 made located-symbol counts complete-or-refused: the count gate still let
numbers through that count nothing.

  the schedule-cell leak  a clause naming a mark could state ANY number a
                          record about it carried. 2,843 (mark, number) pairs
                          could vouch for a count; 66 were counts. "There are
                          10 EF-1." passed on EF-1's 10 lb weight, "50 EF-1"
                          on its CFM, "9000 PTAC-1" on a BTU rating, and the
                          legend symbol 'A' - named by the article "a" - lent
                          its bbox coordinates.
  the citation leak       every returned record's sheet_number, filing_id and
                          issued_date were read as numbers and allowed in
                          EVERY clause. issued_date 8/18/2026 (1,264 records)
                          lent 8, 18 and 2026, so "There are 8 exhaust fans."
                          passed naming nothing.

Rule (operator, 2026-10-07): a count binds only from a counting source - a
located-symbol tally (#664), a cell under a printed quantity header in the
named mark's row, or an element count read from one. Excluded: per-sheet
label tallies, vision-read counts. A citation is removed as TEXT, never
whitelisted as digits. A mixed clause ("21 PTAC-1 at 9,000 BTU") refuses and
falls back to the record render.

EVERY test fails on main by assertion: the "still binds" tests pin that the
true count is the ONLY number that binds, and main binds others beside it.
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
from tests.test_a_located_count_is_complete_or_refused import (  # noqa: E402
    EF, _census, _floor, _numbered, _pages, _refusal)

MH = {"filing_id": "B01141294-P5", "issued_date": "7/2/2026"}
AR = {"filing_id": "B01141294-P5", "issued_date": "8/18/2026"}


def _rec(rt, sheet, quote, payload, tier="ocr_grid_cell", page=None, **cite):
    return {"project_id": "p1", "record_type": rt, "tier": tier,
            "page_id": page or f"pg-{sheet}", "sheet_number": sheet,
            "quote": quote, "payload": payload, **cite}


def _cols(*pairs):
    return [{"header": h, "role": r} for h, r in pairs]


#: The shapes measured on production, reduced to what decides the outcome.
EF_SCHEDULE = _rec("schedule", "M-200.00", "EXHAUST FAN SCHEDULE TAG | ... | WEIGHT LBS", {
    "name": "EXHAUST FAN SCHEDULE",
    "columns": _cols(("TAG", "identifier"), ("SERVING", None), ("MANUF.", "make"),
                     ("MODEL", "model"), ("CFM", None), ("SP", None),
                     ("AMP", None), ("VOLTS", None), ("WEIGHT LBS", None)),
    "rows": [["EF-1", "APARTMENTS BATHROOMS EXHAUST", "NUTONE", "AEN110",
              "50", "0.3", "0.3", "115", "10"],
             ["EF-2", "APARTMENTS KITCHEN EXHAUST", "BROAN", "BRN503",
              "100", "0.35", "1.5", "120", "7.85"]]}, **MH)
PTAC_SCHEDULE = _rec("schedule", "M-200.00", "ROOMS PTAC UNITS SCHEDULE UNIT NO. | QTY | ...", {
    "name": "ROOMS PTAC UNITS SCHEDULE",
    "columns": _cols(("UNIT NO.", "identifier"), ("QTY", "quantity"), ("MAKE", "make"),
                     ("MODEL", "model"), ("BTU COOLING", None), ("BTU HEATING", None)),
    "rows": [["PTAC-1", "21", "AMANA", "PTH093G35AXXX", "9000", "8000"],
             ["PTAC-2", "(readings disagree)", "AMANA", "PTH123G35AXXX", "11400", "10500"],
             ["PTAC-3", "11", "AMANA", "PTH153G50AXXX", "14000", "13700"]]}, **MH)
WH_SCHEDULE = _rec("schedule", "M-200.00", "WALL ELECTRIC UNIT HEATER SCHEDULE MARK | QTY | WATTS", {
    "name": "WALL ELECTRIC UNIT HEATER SCHEDULE",
    "columns": _cols(("MARK", "identifier"), ("QTY", "quantity"), ("WATTS", None),
                     ("VOLTS", None)),
    "rows": [["WH-1", "9", "5120", "208"]]}, **MH)
PTAC1_ELEMENT = _rec("element", "M-200.00", "PTAC-1 - count 21", {
    "tag": "PTAC-1", "count_if_stated": 21, "count_basis": "ocr_schedule_qty"}, **MH)
#: issued_date 8/18/2026, and the one-letter symbol the article "a" names,
#: with the coordinates production stores in its payload.
LEGEND_A = _rec("legend_entry", "A-100.01", "A", {
    "symbol": "A", "meaning": "", "bbox": [1360, 1755, 1396, 1769]},
    tier="tag_legend", **AR)
#: A per-sheet label tally and a vision count: excluded sources.
SD_TALLY = _rec("element", "A.1.2", "SD - count 8", {
    "tag": "SD", "count_if_stated": 8, "count_basis": "tag_occurrences"},
    tier="tag_legend", issued_date="2/27/2025")
BACKFLOW_VISION = _rec("element", "P-001.00", "Backflow Prevention Device - count 1", {
    "name": "Backflow Prevention Device", "tag": "BACKFLOW PREVENTION DEVICE",
    "count_if_stated": 1, "count_basis": "vision_read"}, tier="vision_read")
#: 26 production records carry sheet_number '1'.
SHEET_ONE = _rec("note", "1", "SEE PLAN", {}, tier="text_layer")

PRINTED = [EF_SCHEDULE, PTAC_SCHEDULE, WH_SCHEDULE, PTAC1_ELEMENT, LEGEND_A,
           SD_TALLY, BACKFLOW_VISION, SHEET_ONE]


def _ok(sentence, records=PRINTED):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


def _every_number(records):
    """Every number anywhere in the records, plus 1..40: the candidates a
    count could be invented from."""
    out = {str(n) for n in range(1, 41)}

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, (str, int, float)) and not isinstance(v, bool):
            out.update(S._values(str(v)))
    walk(records)
    return sorted(out, key=float)


def _binds(template, records=PRINTED):
    return [n for n in _every_number(records) if _ok(template.format(n), records)]


# ═══════════════════════════════════════════════════════════════════════════

class TheLeaksMeasuredRefuse(unittest.TestCase):

    def test_a_weight_is_not_a_count(self):
        self.assertFalse(_ok("There are 10 EF-1."))

    def test_a_cfm_is_not_a_count(self):
        self.assertFalse(_ok("There are 50 EF-1."))

    def test_a_btu_rating_is_not_a_count(self):
        self.assertFalse(_ok("There are 9000 PTAC-1."))

    def test_an_issue_date_lends_nothing_to_a_clause_naming_nothing(self):
        for s in ("There are 8 exhaust fans.", "There are 8 of them.",
                  "There are 18 fans.", "There are 2026 units."):
            self.assertFalse(_ok(s), s)

    def test_a_one_letter_legend_mark_reached_by_the_word_a(self):
        self.assertIn("A", S._idents_named_in("There are 1396 fans in a unit.", ["A"]))
        for n in (1360, 1396, 1755):
            self.assertFalse(_ok(f"There are {n} fans in a unit."), n)

    def test_a_numeric_sheet_number_is_neither_stripped_nor_lent(self):
        """sheet_number '1': removing it as text would wave any '1' through;
        lending it as a number let 'There is 1 EF-1.' pass."""
        self.assertFalse(_ok("There is 1 EF-1."))


class TheExcludedSourcesRefuse(unittest.TestCase):

    def test_a_per_sheet_label_tally_is_not_a_count(self):
        self.assertFalse(_ok("There are 8 SD."))

    def test_a_vision_read_count_is_not_a_count(self):
        self.assertFalse(_ok("There is 1 BACKFLOW PREVENTION DEVICE."))

    def test_a_mixed_clause_refuses_to_the_record_render(self):
        """Accepted 2026-10-07: 9000 is not a count, so the clause refuses.
        Written without the thousands comma: '9,000' splits the clause at the
        comma, and the test would then pass on main for that reason alone."""
        self.assertFalse(_ok("There are 21 PTAC-1 at 9000 BTU."))


class TheRealCountsStillBindAndNothingElseDoes(unittest.TestCase):
    """Each pins the true count as the ONLY number that binds - which is
    what fails on main, where the weight, the BTU and the date bind too."""

    def test_ptac_1_is_21(self):
        self.assertEqual(_binds("There are {} PTAC-1."), ["21"])

    def test_ptac_3_is_11(self):
        self.assertEqual(_binds("There are {} PTAC-3."), ["11"])

    def test_wh_1_is_9(self):
        self.assertEqual(_binds("There are {} WH-1."), ["9"])

    def test_ptac_1_from_the_element_alone(self):
        """A count read off the QTY cell, carried by the element when the
        schedule itself was not returned."""
        recs = [PTAC1_ELEMENT, LEGEND_A]
        self.assertEqual(_binds("There are {} PTAC-1.", recs), ["21"])

    def test_the_contested_cell_binds_nothing(self):
        self.assertEqual(_binds("There are {} PTAC-2."), [])

    def test_a_citation_in_a_true_answer_is_harmless_and_lends_nothing(self):
        """The citation stays sayable; its digits stay unsayable as a count."""
        self.assertEqual(_binds("PTAC-1: {} [M-200.00 issued 7/2/2026]."), ["21"])
        self.assertTrue(_ok("PTAC-1: 21, PTAC-3: 11 [M-200.00, filing B01141294-P5]."))


class TheScopedGlyphFiguresStillBindAndNothingElseDoes(unittest.TestCase):
    """#664's figures, with the printed records - and the 8/18/2026 date -
    returned beside them, as production returns them."""

    def setUp(self):
        rows = _numbered(_floor("103", EF, [(t, u) for u in ("4A", "4B", "4C", "4D")
                                            for t in ("EF-1", "EF-2")])
                         + [_refusal("M-104.00", "A-104.00: no units")])
        self.glyph = rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})
        self.recs = PRINTED + self.glyph

    def test_each_unit_on_the_fourth_floor_has_2(self):
        self.assertEqual(_binds("Each unit on the fourth floor has {} exhaust fans.",
                                self.recs), ["2"])

    def test_the_fourth_floor_has_8_and_the_glyphs_are_what_bind_it(self):
        self.assertEqual(_binds("The fourth floor has {} exhaust fans.", self.recs), ["8"])
        self.assertFalse(_ok("The fourth floor has 8 exhaust fans.", PRINTED),
                         "the 8 bound without the located symbols")

    def test_a_unit_and_a_tag_on_the_floor(self):
        self.assertEqual(_binds("There are {} EF-1 on the fourth floor.", self.recs), ["4"])
        self.assertEqual(_binds("4A has {} exhaust fans.", self.recs), ["2"])

    def test_no_building_total(self):
        self.assertEqual(_binds("There are {} exhaust fans.", self.recs), [])


if __name__ == "__main__":
    unittest.main()
