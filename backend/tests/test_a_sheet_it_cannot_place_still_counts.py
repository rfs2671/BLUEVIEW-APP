"""A SHEET IT CANNOT PLACE STILL COUNTS.

Measured on 588 Boyland 2026-10-07. Two mechanical sheets were refused whole,
and every building total with them:
  M-106.00  the bulkhead: no A-106 exists. The only sheet SAF-1 and DH-1 are
            on, so both families had no rows at all.
  M-104.00  the mezzanine: A-104.00 names no units. It carries 4 EF-1, 4
            PTAC-1 and 4 PTAC-2 - and with them, the located PTAC totals equal
            the schedule's QTY exactly: 21, 9 (the contested cell's by-eye
            reading), 11. WH-1 9 and SAF-1 1 agree too.
And eight ARCHITECTURAL sheets with no mechanical partner (the second set's
A.1.x, an unnumbered roof plan) blocked every building total, though they
carry no mechanical symbol a total could miss.

Rulings (operator, 2026-10-07):
  sheet scope   a mechanical sheet the pass cannot place is located and named
                on its own; placement refused, with the reason; floor totals
                bind, no unit scope does. M-104 too: 4A-4D per apartment stays
                refused until stair seeding.
  roles         the pass writes each refusal row's role; architectural refusals
                do not block a building total; a refusal row with no role does.
  QTY           where a family's schedule has a QTY column, the building total
                is reported against it; a disagreement is said, not stated past.

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
    PID, _census, _floor, _numbered, _pages)

PTAC = "ROOMS PTAC UNITS SCHEDULE"
WH, SAF, DH, EF = ("WALL ELECTRIC UNIT HEATER SCHEDULE", "FAN SCHEDULE",
                   "DUCT ELECTRIC HEATER", "EXHAUST FAN SCHEDULE")
FAMS = {EF: ["EF-1", "EF-2"], PTAC: ["PTAC-1", "PTAC-2", "PTAC-3"],
        WH: ["WH-1"], SAF: ["SAF-1"], DH: ["DH-1"]}
#: what the schedules print in their QTY column (PTAC-2's cell is contested)
QTY = {PTAC: {"PTAC-1": "21", "PTAC-2": "(readings disagree)", "PTAC-3": "11"},
       WH: {"WH-1": "9"}, SAF: {"SAF-1": "1"}, DH: {"DH-1": "1"}}


def _present():
    assert hasattr(D, "ROLE_ARCHITECTURAL"), "refusal roles are not in this tree"
    assert hasattr(S, "schedule_quantities"), "QTY cross-check is not in this tree"


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


def _sheet_scope(sheet, title, family, tags_n, arch=None, why="no architectural partner"):
    """Rows a sheet counted at sheet scope emits: located and named, not placed."""
    mech = {"project_id": PID, "company_id": "c1", "file_id": "f-mh", "file_hash": "h",
            "file_name": "MH.pdf", "page_id": f"pg-{sheet}", "page_number": 8,
            "sheet_number": sheet, "sheet_title": title, "discipline": "mechanical"}
    recs = [{"tag": t, "unit": None, "glyph_status": "resolved", "placement": "refused",
             "how": f"refused: {why}", "reason": f"refused: {why}",
             "label_text": f"{t}", "label_box": (1, 2, 3, 4), "symbol_bbox": (5, 6, 7, 8),
             "symbol_at": (6, 7), "at_arch": None, "label_at": (2, 3 + i)}
            for t, n in tags_n for i in range(n)]
    return E.glyph_rows({"records": recs, "method": None,
                         "registration": {"usable": False, "sheet_scope": True}},
                        mech=mech, arch=arch, family=family,
                        pass_key=f"{sheet}|{family}",
                        units={"tags": [], "method": "sheet_scope", "zero_units": False,
                               "multi_level": {}},
                        widest_door={"inches": 56.0})


def _arch_refusal(sheet, role=D.ROLE_ARCHITECTURAL if hasattr(D, "ROLE_ARCHITECTURAL") else None,
                  **kw):
    page = {"project_id": PID, "page_id": f"pg-{sheet}", "page_number": 9,
            "sheet_number": sheet, "sheet_title": "FLOOR PLAN"}
    if "role" in E.sheet_refusal.__code__.co_varnames:
        return E.sheet_refusal(page, f"{sheet} is a plan with no mechanical partner",
                               pass_key="k", role=role)
    return E.sheet_refusal(page, f"{sheet} is a plan with no mechanical partner", pass_key="k")


# The shared FLOORS table knows floors 102 and 103; the building needs 100
# and 101 as well (registered here, read by _floor at call time).
from tests import test_a_located_count_is_complete_or_refused as _LC  # noqa: E402
_LC.FLOORS.setdefault("100", ("FIRST FLOOR HVAC PLANS", ["1A", "1B", "1C", "1D"]))
_LC.FLOORS.setdefault("101", ("SECOND FLOOR HVAC PLANS", ["2A", "2B", "2C", "2D"]))

A104 = {"page_id": "pg-a104", "file_id": "f-own", "page_number": 5, "sheet_number": "A-104.00"}
DUPLEX = {u: ["level word LOWER", "stair label UP"] for u in ("4A", "4B", "4C", "4D")}


def _boyland(*, refusals=None, qty=QTY, ptac1_extra=0):
    """The Boyland shape after the rebuild: floors 1-4 placed (4A-4D duplex),
    M-104 and M-106 at sheet scope, the architectural-only refusals with
    their role. Building totals: PTAC-1 21, PTAC-2 9, PTAC-3 11, WH-1 9,
    SAF-1 1, EF 36, DH none."""
    rows = []
    rows += _floor("100", EF, [(t, u) for u in ("1A", "1B", "1C", "1D") for t in ("EF-1", "EF-2")])
    rows += _floor("101", EF, [(t, u) for u in ("2A", "2B", "2C", "2D") for t in ("EF-1", "EF-2")])
    rows += _floor("102", EF, [(t, u) for u in ("3A", "3B", "3C", "3D") for t in ("EF-1", "EF-2")])
    rows += _floor("103", EF, [(t, u) for u in ("4A", "4B", "4C", "4D") for t in ("EF-1", "EF-2")],
                   multi=DUPLEX)
    # PTAC: 17 / 5 / 11 placed on floors 1-4, as production
    rows += _floor("102", PTAC, [("PTAC-1", "3A")] * (17 + ptac1_extra) + [("PTAC-2", "3B")] * 5
                   + [("PTAC-3", "3C")] * 11)
    rows += _floor("102", WH, [("WH-1", "3D")] * 9)
    rows += _sheet_scope("M-104.00", "MEZZANINE FLOOR HVAC PLANS", EF, [("EF-1", 4)], arch=A104,
                         why="A-104.00: no occupancy table and no unit tags on the sheet")
    rows += _sheet_scope("M-104.00", "MEZZANINE FLOOR HVAC PLANS", PTAC,
                         [("PTAC-1", 4), ("PTAC-2", 4)], arch=A104,
                         why="A-104.00: no occupancy table and no unit tags on the sheet")
    rows += _sheet_scope("M-106.00", "BULKHEAD HVAC PLANS", SAF, [("SAF-1", 1)])
    rows += refusals if refusals is not None else [_arch_refusal(f"A.1.{i}") for i in range(1, 8)]
    rows = _numbered(rows)
    pages = _pages(rows)
    census = []
    for c in _census(rows, pages, FAMS):
        if c.get("kind") == "family":
            c = S.glyph_census("family", PID, pages, c["count"], family=c["family"],
                               tags=c["tags"], qty=(qty or {}).get(c["family"]))
        census.append(c)
    return rows + census




class TheBulkheadCountsAtSheetScope(unittest.TestCase):

    def test_saf_1_on_the_bulkhead(self):
        _present()
        recs = _boyland()
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", recs))
        self.assertTrue(_ok("There is 1 SAF-1.", recs))

    def test_its_rows_say_why_they_are_not_placed(self):
        _present()
        r = [x for x in _boyland() if x.get("label") == "SAF-1"][0]
        self.assertIsNone(r["unit"])
        self.assertIsNone(r["payload"]["arch"])
        self.assertEqual(r["payload"]["placement"], "refused")
        self.assertIn("no architectural partner", r["payload"]["reason"])


class TheMezzanineCountsAtSheetScope(unittest.TestCase):

    def test_its_floor_totals_bind(self):
        _present()
        recs = _boyland()
        self.assertTrue(_ok("The mezzanine has 4 EF-1.", recs))
        self.assertTrue(_ok("There are 4 PTAC-1 on the mezzanine.", recs))
        self.assertTrue(_ok("There are 4 PTAC-2 on the mezzanine.", recs))

    def test_unit_scope_stays_refused(self):
        _present()
        recs = _boyland()
        for s in ("4A has 3 exhaust fans.", "4A has 2 exhaust fans.",
                  "Each unit on the mezzanine has 1 EF-1.",
                  "Each unit on the fourth floor has 3 exhaust fans."):
            self.assertFalse(_ok(s, recs), s)


class ARefusalBlocksOnlyIfItCouldCarryTheSymbols(unittest.TestCase):

    def test_architectural_only_refusals_do_not_block_a_building_total(self):
        _present()
        recs = _boyland()
        self.assertTrue(_ok("There are 21 PTAC-1.", recs))
        self.assertTrue(_ok("There are 36 exhaust fans.", recs))

    def test_a_refusal_row_with_no_role_still_blocks(self):
        _present()
        page = {"project_id": PID, "page_id": "pg-A.1.1", "page_number": 9,
                "sheet_number": "A.1.1", "sheet_title": "FLOOR PLAN"}
        old = E.sheet_refusal(page, "A.1.1 is a plan with no mechanical partner", pass_key="k")
        old["payload"].pop("role", None)            # written before emit_version 3
        recs = _boyland(refusals=[old])
        self.assertFalse(_ok("There are 21 PTAC-1.", recs))
        self.assertFalse(_ok("There are 36 exhaust fans.", recs))

    def test_a_mechanical_refusal_blocks(self):
        _present()
        page = {"project_id": PID, "page_id": "pg-M-105.00", "page_number": 7,
                "sheet_number": "M-105.00", "sheet_title": "ROOF HVAC PLANS"}
        recs = _boyland(refusals=[E.sheet_refusal(page, "takeoff failed", pass_key="k",
                                                  role=D.ROLE_MECHANICAL)])
        self.assertFalse(_ok("There are 21 PTAC-1.", recs))


class TheBuildingTotalIsCheckedAgainstTheSchedule(unittest.TestCase):

    def test_each_total_that_agrees_binds(self):
        _present()
        recs = _boyland()
        for s in ("There are 21 PTAC-1.", "There are 9 PTAC-2.", "There are 11 PTAC-3.",
                  "There are 9 WH-1.", "There is 1 SAF-1."):
            self.assertTrue(_ok(s, recs), s)

    def test_a_readable_9_for_ptac_2_agrees(self):
        _present()
        qty = dict(QTY, **{PTAC: {"PTAC-1": "21", "PTAC-2": "9", "PTAC-3": "11"}})
        recs = _boyland(qty=qty)
        self.assertTrue(_ok("There are 9 PTAC-2.", recs))
        self.assertTrue(_ok("There are 41 PTAC units.", recs))
        self.assertIn("PTAC-2 9 (agrees with the schedule's QTY 9)", S.render_glyph_evidence(recs))

    def test_the_render_reports_agreement_and_an_unreadable_cell(self):
        _present()
        text = S.render_glyph_evidence(_boyland())
        for want in ("PTAC-1 21 (agrees with the schedule's QTY 21)",
                     "PTAC-3 11 (agrees with the schedule's QTY 11)",
                     "WH-1 9 (agrees with the schedule's QTY 9)",
                     "SAF-1 1 (agrees with the schedule's QTY 1)",
                     "PTAC-2 9 (the schedule's QTY cell cannot be read"):
            self.assertIn(want, text)

    def test_a_disagreement_is_said_and_neither_number_binds(self):
        _present()
        recs = _boyland(ptac1_extra=-1)             # 20 located, QTY prints 21
        self.assertFalse(_ok("There are 20 PTAC-1.", recs))
        self.assertFalse(_ok("There are 21 PTAC-1.", recs))
        self.assertIn("PTAC-1: located 20 but the schedule's QTY prints 21 - THEY DISAGREE",
                      S.render_glyph_evidence(recs))

    def test_dh_1_is_refused_not_zero(self):
        """REVISED 2026-10-10, ruling (a): nothing located + QTY printed -> the
        QTY stands. This pinned "There is 1 DH-1." as refused while the gate,
        through the schedule's own QTY cell, accepted it on production - the
        model was told "state no count" beside a count the gate allowed. The
        located count is still never zero."""
        _present()
        recs = _boyland()
        self.assertTrue(_ok("There is 1 DH-1.", recs))
        for s in ("There are 0 DH-1.", "There are 2 DH-1.",
                  "The bulkhead has 1 DH-1."):         # a QTY is a building figure
            self.assertFalse(_ok(s, recs), s)
        text = S.render_glyph_evidence(recs)
        self.assertIn(f"{DH} (DH-1): the schedule prints QTY DH-1 1; its symbols were "
                      f"not located.", text)
        self.assertNotIn(f"{DH} (DH-1): NOT COUNTED", text)


class TheScheduleQuantityIsReadAtQuestionTime(unittest.TestCase):

    def test_schedule_quantities_reads_the_printed_qty_column(self):
        _present()
        payload = {"columns": [{"header": "UNIT NO.", "role": "identifier"},
                               {"header": "QTY", "role": "quantity"}],
                   "rows": [["PTAC-1", "21"], ["PTAC-2", "(readings disagree)"],
                            ["PTAC-3", "11"], ["PTAC-9", "4"]]}
        self.assertEqual(S.schedule_quantities(payload, ["PTAC-1", "PTAC-2", "PTAC-3"]),
                         {"PTAC-1": "21", "PTAC-2": "(readings disagree)", "PTAC-3": "11"})
        self.assertEqual(S.schedule_quantities({"columns": [{"header": "TAG", "role": "identifier"}],
                                                "rows": [["EF-1"]]}, ["EF-1"]), {})

    def test_search_plans_puts_it_on_the_census(self):
        _present()
        from tests.test_a_located_count_is_complete_or_refused import _search, _schedule
        sched = _schedule(PTAC, ["PTAC-1", "PTAC-2"])
        sched["payload"]["columns"] = [{"header": "UNIT NO.", "role": "identifier"},
                                       {"header": "QTY", "role": "quantity"}]
        sched["payload"]["rows"] = [["PTAC-1", "21"], ["PTAC-2", "9"]]
        rows = _numbered(_floor("102", PTAC, [("PTAC-1", "3A"), ("PTAC-2", "3B")]))
        got, _db = _search([sched] + rows, "PTAC-1", limit=8)
        census = [c for c in got if c.get("record_type") == S.GLYPH_CENSUS and c.get("family") == PTAC]
        self.assertEqual([c.get("qty") for c in census], [{"PTAC-1": "21", "PTAC-2": "9"}])


class ThePassCountsWhatItCannotPlace(unittest.TestCase):

    def _run(self, pages, unit_tags):
        from lib import plan_glyph_pass as G

        class Page:
            directed_words = []

        seen = []

        def takeoff(arch_page, mech_page, tags, *a, unplaced_reason=None, **k):
            seen.append((arch_page, unplaced_reason))
            return {"records": [{"tag": tags[0], "unit": None, "glyph_status": "resolved",
                                 "placement": "refused", "reason": unplaced_reason,
                                 "how": unplaced_reason, "label_text": tags[0]}],
                    "method": None, "registration": {"usable": False}}
        schedules = [{"name": SAF, "tier": "ocr_grid_cell", "sheet_number": "M-200.00",
                      "columns": [{"header": "MARK", "role": "identifier"}],
                      "rows": [["SAF-1"]]}]
        with patch.object(D, "unit_tags", lambda w, c: unit_tags), \
                patch("lib.plan_sheet.load_sheet", lambda pg: {"words": [], "corners": [], "segs": []}), \
                patch("lib.plan_takeoff.sweep", lambda *a, **k: []), \
                patch("lib.plan_takeoff.run_takeoff", takeoff):
            out = G.run_pass(pages, lambda p: Page(), schedules, [])
        return out, seen

    def test_an_unpaired_mechanical_sheet_is_counted_not_refused(self):
        _present()
        pages = [{"page_id": "pm", "sheet_number": "M-106.00", "sheet_title": "BULKHEAD HVAC PLANS"},
                 {"page_id": "pa", "sheet_number": "A.1.1", "sheet_title": "FLOOR PLAN"}]
        out, seen = self._run(pages, {"tags": None})
        located = [r for r in out["rows"] if r.get("label")]
        self.assertEqual([r["label"] for r in located], ["SAF-1"])
        self.assertEqual(seen[0][0], None)          # no architectural page
        self.assertIn("M-106.00 has no architectural partner A-106", seen[0][1])
        self.assertIsNone(located[0]["payload"]["arch"])
        refusals = [r for r in out["rows"] if r["payload"].get("refusal")]
        self.assertEqual([(r["sheet_number"], r["payload"]["role"]) for r in refusals],
                         [("A.1.1", D.ROLE_ARCHITECTURAL)])
        self.assertEqual(located[0]["payload"]["emit_version"], E.EMIT_VERSION)
        self.assertGreaterEqual(E.EMIT_VERSION, 3)

    def test_a_floor_whose_plan_names_no_units_is_counted_not_refused(self):
        _present()
        pages = [{"page_id": "pa", "sheet_number": "A-104.00", "sheet_title": "MEZZANINE PLAN"},
                 {"page_id": "pm", "sheet_number": "M-104.00", "sheet_title": "MEZZANINE FLOOR HVAC PLANS"}]
        out, seen = self._run(pages, {"tags": None,
                                      "why": "no occupancy table and no unit tags on the sheet"})
        located = [r for r in out["rows"] if r.get("label")]
        self.assertTrue(located)
        self.assertFalse([r for r in out["rows"] if r["payload"].get("refusal")])
        self.assertIn("A-104.00: no occupancy table", seen[0][1])
        self.assertEqual(located[0]["payload"]["arch"]["sheet_number"], "A-104.00")
        self.assertEqual(located[0]["payload"]["units"]["method"], "sheet_scope")


class TheTakeoffRunsWithNoArchitecturalPage(unittest.TestCase):

    def test_located_and_named_placement_refused_with_the_reason(self):
        _present()
        from lib import plan_takeoff as T

        class Page:
            pass
        reads = [("SAF-1", 100.0, 100.0, (95.0, 96.0, 105.0, 104.0))]
        with patch("lib.plan_ocr.probe", lambda: (True, "")), \
                patch.object(T, "load_sheet", lambda pg: {"segs": [], "words": [], "corners": []}), \
                patch.object(T, "symbol_objects", lambda pg: []), \
                patch("lib.plan_symbols.symbol_at_label",
                      lambda *a, **k: ((110.0, 100.0), 12)):
            res = T.run_takeoff(None, Page(), ["SAF-1"], {}, [], 56.0, reads=reads,
                                unplaced_reason="refused: M-106.00 has no architectural "
                                                "partner A-106: counted at sheet scope")
        (r,) = res["records"]
        self.assertEqual((r["tag"], r["glyph_status"], r["placement"], r["unit"]),
                         ("SAF-1", "resolved", "refused", None))
        self.assertIn("counted at sheet scope", r["reason"])
        self.assertIsNone(r["at_arch"])


_SWEEPS = {}


class OnTheRealSheets(unittest.TestCase):
    """The measurement of 2026-10-07, held. Needs the source-PDF fixtures and
    the OCR engine; each sheet is swept once."""

    def _count(self, page_no, family_tags):
        _present()
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet
        from lib import plan_takeoff as T
        pg = PlanPage(require_pdf("MH - 7.2.26.pdf"), page_no)
        try:
            if page_no not in _SWEEPS:
                _SWEEPS[page_no] = T.sweep(pg, load_sheet(pg)["segs"])
            out = {}
            for tags in family_tags:
                res = T.run_takeoff(None, pg, tags, {}, [], 56.0, reads=_SWEEPS[page_no],
                                    unplaced_reason="refused: sheet scope")
                for r in res.get("records") or []:
                    key = (r["tag"], r["placement"])
                    out[key] = out.get(key, 0) + 1
            return out
        finally:
            pg.close()

    def test_m106_saf_1_one_and_dh_1_unread(self):
        got = self._count(8, [["SAF-1"], ["DH-1"]])
        self.assertEqual(got, {("SAF-1", "refused"): 1})

    def test_m104_four_four_four(self):
        got = self._count(6, [["EF-1", "EF-2"], ["PTAC-1", "PTAC-2", "PTAC-3"]])
        self.assertEqual(got, {("EF-1", "refused"): 4, ("PTAC-1", "refused"): 4,
                               ("PTAC-2", "refused"): 4})


if __name__ == "__main__":
    unittest.main()
