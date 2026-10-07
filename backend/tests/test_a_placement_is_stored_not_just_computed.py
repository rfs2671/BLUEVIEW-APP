"""A PLACEMENT IS STORED, NOT JUST COMPUTED.

The takeoff (lib.plan_takeoff) answered "which apartment does this fan serve"
and nothing kept the answer: nothing called it, and the count-answer gate
(plan_search.glyph_tallies) read registered-glyph rows nobody wrote. This
covers the emission - the rows, the derivations that feed them, and the
server's writer - against the consumer that already existed.

  derivations  pairing by sheet number, units from the sheet, the widest
               door from the door schedule - each answers or REFUSES;
  rows         record_type "glyph", cited to the mechanical sheet,
               glyph_status in plan_tally's vocabulary, placement in payload;
  consumer     the real glyph_tallies / count gate, not a stand-in;
  server       the writer exists, a re-indexed architectural page stales its
               placements, and the indexer never starts the pass.

Real-sheet derivation cases need the source-PDF fixtures (fixture_pdfs).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

try:                                     # absent on main: tests FAIL, not error
    from lib import plan_derive as D
    from lib import plan_emit as E
except ImportError:                      # pragma: no cover
    D = E = None

from lib import plan_search as S  # noqa: E402
from lib import plan_tally as T  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402
from tests.source_text import strip_python  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _present():
    assert D is not None and E is not None, \
        "lib.plan_derive / lib.plan_emit are not in this tree"


#: the CURRENT sheets of 588 Boyland that matter to pairing, from the
#: production index (2026-10-06): every plan, the series a number-only rule
#: would mis-pair, the second consultant's dotted numbering, an unnumbered
#: roof plan, and a fire-alarm plan
BOYLAND = [
    ("A-100.01", "FIRST FLOOR PLAN"), ("A-101.00", "SECOND FLOOR PLAN"),
    ("A-102.00", "THIRD FLOOR PLAN"), ("A-103.00", "FOURTH FLOOR PLAN"),
    ("A-104.00", "MEZZANINE PLAN"), ("A-105.01", "ROOF AND BULKEAD PLAN"),
    ("A-200.01", "FRONT AND REAR ELEVATIONS"), ("A-201.01", "SIDE ELEVATION"),
    ("A-400.00", "WINDOW SCHEDULE"),
    ("M-001.00", "GENERAL NOTES, HVAC NOTES AND SYMBOL LIST"),
    ("M-100.00", "FIRST FLOOR HVAC PLANS"), ("M-101.00", "SECOND FLOOR HVAC PLANS"),
    ("M-102.00", "THIRD FLOOR HVAC PLANS"), ("M-103.00", "FOURTH FLOOR HVAC PLANS"),
    ("M-104.00", "MEZZANINE FLOOR HVAC PLANS"), ("M-105.00", "ROOF HVAC PLANS"),
    ("M-106.00", "BULKHEAD HVAC PLANS"), ("M-200.00", "HVAC SCHEDULES AND DETAILS"),
    ("M-201.00", "HVAC DETAILS"),
    ("A.1.1", "FLOOR PLAN"), ("A.1.4", "FLOOR PLAN"), ("A.0.1", "RENDERS- EXTERIOR"),
    (None, "Roof Plan"), ("FA-007", "FOURTH FLOOR FIRE ALARM PLAN"),
]


def _pages(rows=BOYLAND):
    return [{"sheet_number": n, "sheet_title": t, "page_id": f"p{i}"}
            for i, (n, t) in enumerate(rows)]


class PairingIsBySheetNumberInThePlanSeries(unittest.TestCase):

    def test_the_six_boyland_pairs(self):
        _present()
        got = D.pair_plan_sheets(_pages())
        self.assertEqual([(a["sheet_number"], m["sheet_number"]) for a, m in got["pairs"]],
                         [("A-100.01", "M-100.00"), ("A-101.00", "M-101.00"),
                          ("A-102.00", "M-102.00"), ("A-103.00", "M-103.00"),
                          ("A-104.00", "M-104.00"), ("A-105.01", "M-105.00")])

    def test_what_is_refused_and_what_is_not(self):
        """M-106.00 is never paired to A-105.01 (ruling); the dotted A.1.x
        plans and an unnumbered plan have no partner; elevations, schedules,
        renders and the fire-alarm plan are not apartment plans at all."""
        _present()
        refused = {p["sheet_number"] for p, _w in D.pair_plan_sheets(_pages())["refused"]}
        self.assertEqual(refused, {"M-106.00", "A.1.1", "A.1.4", None})

    def test_number_alone_would_pair_elevations_with_hvac_schedules(self):
        """A-200.01 and M-200.00 share a number; they are not a floor."""
        _present()
        pairs = D.pair_plan_sheets(_pages([("A-200.01", "ELEVATIONS"),
                                           ("M-200.00", "HVAC SCHEDULES")]))
        self.assertEqual((pairs["pairs"], pairs["refused"]), ([], []))

    def test_two_current_sheets_on_one_number_are_ambiguous(self):
        _present()
        got = D.pair_plan_sheets(_pages([("A-103.00", "FOURTH FLOOR PLAN"),
                                         ("A-103.00", "FOURTH FLOOR PLAN"),
                                         ("M-103.00", "FOURTH FLOOR HVAC")]))
        self.assertEqual(got["pairs"], [])
        self.assertEqual(len([w for _p, w in got["refused"] if "ambiguous" in w]), 2)


def _w(text, x, y):
    return (text, float(x), float(y))


#: a plan extent the bubbles sit inside
CORNERS = [(0.0, 0.0), (2000.0, 0.0), (2000.0, 1500.0), (0.0, 1500.0)]


def _table(*tags, y0=1300, first_line_neighbour=False):
    ws = [_w("OCCUPANCY", 900, y0), _w("LOAD", 960, y0)]
    for i, t in enumerate(tags):
        y = y0 + 30 + 20 * i
        if first_line_neighbour and i == 0:
            ws += [_w("#######", 750, y), _w("#######", 800, y)]
        ws += [_w("APT", 820, y), _w(t, 840, y), _w("320", 880, y), _w("SF.", 900, y)]
    return ws


def _bubbles(*tags):
    ws = []
    for i, t in enumerate(tags):
        ws += [_w("APT", 300 + 300 * i, 500), _w(t, 300 + 300 * i, 515)]
    return ws


class UnitsComeFromTheSheet(unittest.TestCase):

    def test_the_table_first(self):
        _present()
        got = D.unit_tags(_table("1A", "1B") + _bubbles("1A", "1B"), CORNERS)
        self.assertEqual((got["tags"], got["method"]), (["1A", "1B"], "occupancy_table"))

    def test_the_plan_when_there_is_no_table(self):
        _present()
        got = D.unit_tags(_bubbles("2A", "2B"), CORNERS)
        self.assertEqual((got["tags"], got["method"]), (["2A", "2B"], "plan_tags"))

    def test_a_sheet_that_contradicts_itself_is_refused(self):
        _present()
        got = D.unit_tags(_table("1A", "1B") + _bubbles("1A", "1C"), CORNERS)
        self.assertIsNone(got["tags"])
        self.assertIn("contradicts", got["why"])

    def test_a_table_with_no_apartment_is_zero_units_not_a_refusal(self):
        """A-105.01, the roof: one PASSIVE RECREATION row (ruling)."""
        _present()
        ws = [_w("OCCUPANCY", 900, 1300), _w("PASSIVE", 820, 1330),
              _w("1970", 880, 1340), _w("SF.", 900, 1340)]
        got = D.unit_tags(ws, CORNERS)
        self.assertEqual((got["tags"], got["zero_units"]), ([], True))

    def test_neither_is_refused(self):
        """A-104.00, the mezzanine: no table, no tag."""
        _present()
        got = D.unit_tags([_w("MEZZANINE", 500, 500)], CORNERS)
        self.assertIsNone(got["tags"])
        self.assertIn("no occupancy table", got["why"])

    def test_a_row_sharing_a_line_with_the_next_table_is_read(self):
        """A.1.5: '####### ####### APT 4A UPPER' - the row's first word is
        another table's cell."""
        _present()
        got = D.unit_tags(_table("4A", "4B", first_line_neighbour=True), CORNERS)
        self.assertEqual(got["tags"], ["4A", "4B"])

    def test_tags_never_areas(self):
        """The table's area is GROSS by its own header (ruling)."""
        _present()
        got = D.unit_tags(_table("1A"), CORNERS)
        self.assertEqual(set(got), {"tags", "method", "zero_units", "why"})


def _dw(text, x, y, d="ltr"):
    return (text, float(x), float(y), d)


class TheDoorWidthIsTheHorizontalDimension(unittest.TestCase):

    def _schedule(self):
        return [_dw("EXTERIOR", 160, 700), _dw("DOOR", 240, 715), _dw("SCHEDULE", 316, 715),
                _dw("NUMBER", 162, 755), _dw("D1", 210, 755),
                _dw("NUMBER", 405, 755), _dw("D2", 453, 755),
                _dw("1'-4\"", 205, 913), _dw("4'-8\"", 250, 893), _dw("3'-4\"", 268, 913),
                _dw("8'-0\"", 327, 1040, "btt"),
                _dw("3'-4\"", 489, 913), _dw("8'-0\"", 548, 1040, "btt")]

    def test_the_widest_door_on_a400(self):
        """Measured on A-400.00: D1 4'-8" (56in), D2 3'-4"; 8'-0" is a height."""
        _present()
        got = D.widest_door_in(self._schedule())
        self.assertEqual((got["inches"], got["doors"]), (56.0, {"D1": 56.0, "D2": 40.0}))

    def test_heights_read_vertically_and_are_not_widths(self):
        _present()
        ws = [w for w in self._schedule() if w[0] != "4'-8\""]
        self.assertEqual(D.widest_door_in(ws)["doors"]["D1"], 40.0)

    def test_no_schedule_is_none(self):
        _present()
        got = D.widest_door_in([_dw("FLOOR", 10, 10), _dw("PLAN", 50, 10)])
        self.assertIsNone(got["inches"])


MECH = {"project_id": "p1", "company_id": "c1", "file_id": "f-mh", "file_hash": "h",
        "file_name": "MH - 7.2.26.pdf", "page_id": "pg-m103", "page_number": 5,
        "sheet_number": "M-103.00", "sheet_title": "FOURTH FLOOR HVAC PLANS",
        "discipline": "mechanical"}
ARCH = {"page_id": "pg-a103", "file_id": "f-own", "page_number": 4, "sheet_number": "A-103.00"}


def _takeoff(units, refused=()):
    return {"records": [{"tag": "EF-1", "unit": u, "glyph_status": "resolved",
                         "placement": "placed", "label_text": "EF-1(50)",
                         "label_box": (1, 2, 3, 4), "symbol_bbox": (5, 6, 7, 8),
                         "symbol_at": (6, 7), "at_arch": (9, 9), "label_at": (2, 3)}
                        for u in units],
            "refused_tags": list(refused), "method": "layers",
            "registration": {"rms_in": 0.05, "anchors": 600, "usable": True}}


def _rows(units, refused=()):
    return E.glyph_rows(_takeoff(units, refused), mech=MECH, arch=ARCH, family="EXHAUST FAN SCHEDULE",
                        pass_key="A-103.00|M-103.00|EXHAUST FAN SCHEDULE",
                        units={"tags": ["4A", "4B", "4C", "4D"], "method": "occupancy_table",
                               "zero_units": False}, widest_door={"inches": 56.0})


class TheRowsAreTheApprovedShape(unittest.TestCase):

    def test_cited_to_the_mechanical_sheet(self):
        _present()
        r = _rows(["4A"])[0]
        self.assertEqual((r["record_type"], r["sheet_number"], r["page_id"]),
                         ("glyph", "M-103.00", "pg-m103"))
        self.assertEqual(r["payload"]["arch"]["sheet_number"], "A-103.00")

    def test_tag_label_quote_and_boxes(self):
        _present()
        r = _rows(["4A"])[0]
        self.assertEqual((r["label"], r["quote"], r["tier"]),
                         ("EF-1", "EF-1(50)", "registered_glyph"))
        self.assertEqual(r["bbox"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(r["payload"]["symbol_bbox"], [5.0, 6.0, 7.0, 8.0])

    def test_glyph_status_is_the_tally_vocabulary_and_placement_is_apart(self):
        _present()
        r = _rows(["4A"])[0]
        self.assertIn(r["glyph_status"], (T.RESOLVED, T.UNREAD, T.CONTESTED,
                                          T.UNSUPPORTED_UNIT))
        self.assertEqual(r["payload"]["placement"], "placed")
        self.assertNotIn("placement", r)

    def test_a_sheet_refusal_is_one_row_with_its_reason(self):
        _present()
        r = E.sheet_refusal(dict(MECH, sheet_number="M-104.00"),
                            "A-104.00: no occupancy table and no unit tags on the sheet",
                            pass_key="k")
        self.assertEqual((r["unit"], r["glyph_status"]), ("sheet:M-104.00", T.UNSUPPORTED_UNIT))
        self.assertIn("no occupancy table", r["payload"]["refusal"])


class TheConsumerReadsThem(unittest.TestCase):
    """plan_search.glyph_tallies and the count gate, unmodified."""

    def test_a_complete_floor_counts_and_splits(self):
        _present()
        t = S.glyph_tallies(_rows(["4A", "4A", "4B", "4B", "4C", "4C", "4D", "4D"]))["EF-1"]
        self.assertEqual((t.total, T.per_unit(t)), (8, {"4A": 2, "4B": 2, "4C": 2, "4D": 2}))

    def test_the_gate_binds_the_count(self):
        """With the census search_plans attaches beside the rows - and not
        without it: rows alone were how a partial 2 of 16 was bound as a
        total (test_a_located_count_is_complete_or_refused)."""
        _present()
        self.assertTrue(hasattr(S, "glyph_census"), "no census in this tree")
        rows = _rows(["4A", "4A", "4B", "4B", "4C", "4C", "4D", "4D"])
        pages = sorted({r["page_id"] for r in rows})
        census = [S.glyph_census("family", "p1", pages, 8,
                                 family="EXHAUST FAN SCHEDULE", tags=["EF-1", "EF-2"]),
                  S.glyph_census("refusals", "p1", pages, 0)]
        ok, bad = S._count_answer_is_bound("There are 8 EF-1 exhaust fans.", rows + census)
        self.assertEqual((ok, bad), (True, []))
        ok, bad = S._count_answer_is_bound("There are 8 EF-1 exhaust fans.", rows)
        self.assertEqual((ok, bad), (False, ["8"]))

    def test_a_refused_unit_withholds_the_split(self):
        _present()
        t = S.glyph_tallies(_rows(["4A", "4A", "4B", "4B", "4C", "4C"], refused=["4D"]))["EF-1"]
        self.assertIsNone(T.per_unit(t))
        self.assertEqual(t.unsupported_units, ["4D"])

    def test_a_refused_placement_withholds_the_split(self):
        """A resolved fan with no unit: the total stands, the split does not."""
        _present()
        t = S.glyph_tallies(_rows(["4A", "4A", "4B", None]))["EF-1"]
        self.assertEqual(t.resolved, 4)
        self.assertIsNone(T.per_unit(t))


class TheServerWritesThemAndOnlyAnOperatorStartsIt(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = strip_python((BACKEND / "server.py").read_text(encoding="utf-8"))

    def _body(self, name):
        self.assertIn(f"def {name}(", self.src, f"{name} is not in this tree")
        i = self.src.index(f"def {name}(")
        j = self.src.find("\nasync def ", i + 10)
        k = self.src.find("\ndef ", i + 10)
        ends = [e for e in (j, k, self.src.find("\n@", i + 10)) if e > 0]
        return self.src[i:min(ends)]

    def test_glyph_is_a_record_type(self):
        from lib import plan_records
        self.assertIn("glyph", plan_records.RECORD_TYPES)

    def test_the_writer_replaces_the_projects_glyph_rows(self):
        body = self._body("_write_glyph_records")
        self.assertIn('"record_type": "glyph"', body)
        self.assertIn("delete_many", body)
        self.assertIn("insert_many", body)

    def test_a_reindexed_architectural_page_stales_its_placements(self):
        body = self._body("_write_page_records")
        self.assertIn('"payload.arch.file_id": file_id', body)
        self.assertIn('"payload.arch.page_number": page_number', body)

    def test_only_the_operator_endpoint_starts_the_pass(self):
        """Its rows change what the count gate allows; indexing must not
        write them on its own (the first write is reviewed by render)."""
        import re
        # a word boundary: run_plan_glyph_pass( contains the name as a suffix
        uses = [m.start() for m in re.finditer(r"(?<![\w])_plan_glyph_pass\(", self.src)]
        calls = [i for i in uses if not self.src.startswith("def ", i - 4)]
        self.assertEqual(len(calls), 1, "one call site, in the endpoint")
        self.assertIn("_plan_glyph_pass(", self._body("run_plan_glyph_pass"))

    def test_the_endpoint_is_admin_only(self):
        self.assertIn("def run_plan_glyph_pass(", self.src, "no endpoint in this tree")
        i = self.src.index("def run_plan_glyph_pass(")
        self.assertIn("get_admin_user", self.src[i:i + 200])


class TheDerivationsOnTheRealSheets(unittest.TestCase):
    """Measured 2026-10-06 on the hash-verified source PDFs."""

    def _sheet(self, fn, pn):
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet
        pg = PlanPage(require_pdf(fn), pn)
        return pg, load_sheet(pg)

    def test_units_by_floor(self):
        _present()
        for fn, pn, want in (("AR - 8.18.26.pdf", 6, ["1A", "1B", "1C", "1D"]),
                             ("Owners set - 6.9.26.pdf", 4, ["4A", "4B", "4C", "4D"]),
                             ("Owners set - 6.9.26.pdf", 5, None),
                             ("AR - 8.18.26.pdf", 7, [])):
            with self.subTest(file=fn, page=pn):
                _pg, sh = self._sheet(fn, pn)
                self.assertEqual(D.unit_tags(sh["words"], sh["corners"])["tags"], want)

    def test_the_door_schedule_on_a400(self):
        _present()
        pg, _sh = self._sheet("AR - 3.28.25.pdf", 23)
        got = D.widest_door_in(pg.directed_words)
        self.assertEqual((got["inches"], got["doors"]), (56.0, {"D1": 56.0, "D2": 40.0}))


if __name__ == "__main__":
    unittest.main()
