"""THE TAKEOFF EXPORT, PER DRAWING SET (rulings 72, 73, 101/102, 2026-10-28).

Measured on 588 Boyland 2026-10-28 (read-only probe): WH-1 has 18 located
rows - 9 in the filed set (6 on M-100 -> A-100.01, 3 on M-105 -> A-105.01)
and 9 in the owner's post-CO set (6 on M-100 -> A-100.00, placed outside the
apartments; 3 on M-105 -> A-105.00, "no occupancy table and no unit tags on
the sheet: counted at sheet scope, not placed"). The export listed the
filed set's alone: the mechanical lines were read off the totals book,
which counts each sheet's symbols from one set. The owner's set's 9 were on
no line.

  72. "one line per set, same as doors/windows (owner's set: 6 on A-100.00
      placed outside apartments; ...)."
  101/102 (withdrawing 72's roof refusal): "a whole-sheet count binds at
      sheet scope (Oct 7 rule) in both chat and export. Owner's-set roof line
      = 3 WH-1 at sheet scope, 'not placed in apartments: A-105.00 has no unit
      tags'. Owner's building total = 9, agreeing with schedule QTY 9. The
      export and the chat must apply the same rule; add a test asserting they
      agree on every equipment line."
  73. "'not checked: schedule QTY unreadable (6 or 9)', not refused."
      PTAC-2's QTY cell on M-200.00 is contested: two readings, 6 and 9
      (plan_ocr.read_grid_twice stores them in payload.contested_cells).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from lib import plan_takeoff_export as X  # noqa: E402
from tests import test_a_door_is_counted_by_its_tag as D  # noqa: E402
from tests import test_two_drawing_tracks as T  # noqa: E402

OWNER = T.LABEL
FILED = "the filed set"
WH = "WALL ELECTRIC UNIT HEATER SCHEDULE"
WHY = ("refused: A-105.00: no occupancy table and no unit tags on the sheet: "
       "counted at sheet scope, not placed")
#: plan_glyph_pass.SHEET_SCOPE_UNITS, as the pass writes it
SHEET_SCOPE = {"tags": [], "method": "sheet_scope", "zero_units": False, "multi_level": {}}
TITLES = {"100": "FIRST FLOOR HVAC PLANS", "105": "ROOF HVAC PLANS"}


def _wh_rows(track, level, n, *, arch_sheet, sheet_scope=False):
    """n WH-1 on M-{level}.00, paired with `arch_sheet` of `track`: placed
    outside the apartments, or - `sheet_scope` - on a plan that could place
    nothing (plan_glyph_pass.sheet_scope)."""
    mech = {"project_id": T.PID, "company_id": "c1", "file_id": "f-mh", "file_hash": "h",
            "file_name": "MH.pdf", "page_id": f"pg-m{level}", "page_number": 2,
            "sheet_number": f"M-{level}.00", "sheet_title": TITLES[level],
            "discipline": "mechanical"}
    arch = {"page_id": f"pg-a{level}-{track}", "file_id": f"f-{track}", "page_number": 6,
            "sheet_number": arch_sheet, "drawing_track": track,
            "drawing_track_label": OWNER if track == "post_co" else None}
    recs = [{"tag": "WH-1", "unit": None if sheet_scope else "non-unit:PUBLIC",
             "glyph_status": "resolved",
             "placement": "refused" if sheet_scope else "placed-non-unit",
             "reason": WHY if sheet_scope else None,
             "label_text": "WH-1", "label_box": (1, 2, 3, 4), "symbol_bbox": (5, 6, 7, 8),
             "symbol_at": (6, 7), "at_arch": (9, 9), "label_at": (2 + i, 3)} for i in range(n)]
    units = SHEET_SCOPE if sheet_scope else {"tags": [], "method": "plan_tags",
                                             "zero_units": False, "multi_level": {}}
    rows = E.glyph_rows({"records": recs, "method": "layers",
                         "registration": {"anchors": 900, "usable": True}},
                        mech=mech, arch=arch, family=WH,
                        pass_key=f"{arch_sheet}|M-{level}.00|{WH}", units=units,
                        widest_door={"inches": 56.0}, mech_count=n)
    for r in rows:
        r["payload"]["track"] = track
    return rows


def _wh_world():
    """WH-1 as 588 Boyland holds it, two in place of six on the first floor."""
    rows = T._numbered(_wh_rows("filed", "100", 2, arch_sheet="A-100.01")
                       + _wh_rows("filed", "105", 3, arch_sheet="A-105.01")
                       + _wh_rows("post_co", "100", 2, arch_sheet="A-100.00")
                       + _wh_rows("post_co", "105", 3, arch_sheet="A-105.00", sheet_scope=True))
    recs = list(rows)
    pages = sorted({r["page_id"] for r in rows})
    for t in ("filed", "post_co"):
        c = T._gc("family", pages, 0, t, family=WH, tags=["WH-1"])
        recs.append(T._gc("family", pages, sum(S.glyph_in_census(r, c) for r in rows), t,
                          family=WH, tags=["WH-1"], qty={"WH-1": "5"}))
        recs.append(T._gc("refusals", pages, 0, t))
    return recs


def _one(lines, **kw):
    got = [ln for ln in lines if all(getattr(ln, k) == v for k, v in kw.items())]
    assert len(got) == 1, f"{len(got)} lines for {kw}: {lines}"
    return got[0]


class EveryMechanicalLineIsPerItsSet(unittest.TestCase):
    """72: the owner's set's WH-1 are on their own lines."""

    def test_the_owners_set_has_its_own_lines(self):
        recs = _wh_world()
        t = X.build(recs)
        first = _one(t.lines, tag="WH-1", scope=X.FLOOR, set_label=OWNER,
                     level="FIRST FLOOR HVAC PLANS")
        self.assertEqual((first.qty, first.level), (2, "FIRST FLOOR HVAC PLANS"))
        self.assertIn("A-100.00", first.sheets)
        self.assertEqual(first.check, "placed outside apartments")
        self.assertEqual(first.sentence, f"The first floor has 2 WH-1 per {OWNER}.")
        # every exported figure is one the gate binds, the filed set's too
        filed = [ln for ln in t.lines if ln.set_label == FILED]
        self.assertEqual(sorted((ln.scope, ln.level, ln.qty) for ln in filed),
                         [(X.BUILDING, "", 5), (X.FLOOR, "FIRST FLOOR HVAC PLANS", 2),
                          (X.FLOOR, "ROOF HVAC PLANS", 3)])
        for ln in t.lines:
            self.assertTrue(S.answer_is_grounded(ln.sentence, recs, intent="count")[0], ln)
            self.assertTrue(ln.sentence.endswith(f"per {ln.set_label}."), ln)

    def test_a_whole_sheet_count_binds_at_sheet_scope(self):
        """The owner's roof: A-105.00 names no unit, so its 3 WH-1 were
        counted at sheet scope, not placed. The line stands (rulings 101/102,
        the Oct 7 rule), and says they were not placed in apartments; the
        owner's total stands with it, checked against the schedule's QTY."""
        t = X.build(_wh_world())
        self.assertFalse([ln for ln in t.refused if ln.tag == "WH-1"])
        roof = _one(t.lines, tag="WH-1", scope=X.FLOOR, set_label=OWNER,
                    level="ROOF HVAC PLANS")
        self.assertEqual((roof.qty, roof.check),
                         (3, "not placed in apartments: A-105.00 has no unit tags"))
        self.assertIn("A-105.00", roof.sheets)
        self.assertEqual(roof.sentence, f"The roof has 3 WH-1 per {OWNER}.")
        total = _one(t.lines, tag="WH-1", scope=X.BUILDING, set_label=OWNER)
        self.assertEqual((total.qty, total.check), (5, "schedule QTY 5 agrees"))
        # the filed set's roof was placed - outside the apartments
        self.assertEqual(_one(t.lines, tag="WH-1", scope=X.FLOOR, set_label=FILED,
                              level="ROOF HVAC PLANS").check, "placed outside apartments")

    def test_one_symbol_a_placed_plan_could_not_place_is_no_such_refusal(self):
        """'refused: in a wall' on a plan that placed the rest: the floor
        line stands (the two-track world's filed second floor)."""
        t = X.build(T._world())
        ln = _one(t.lines, tag="PTAC-1", scope=X.FLOOR, level="SECOND FLOOR HVAC PLANS",
                  set_label=FILED)
        self.assertEqual(ln.qty, 2)
        self.assertEqual(ln.check, "")

    def test_a_set_that_does_not_read_the_sheet_gets_no_line(self):
        """SAF-1 on M-106.00 (the bulkhead) is read by the filed set alone:
        the owner's set gives no line for it. A set that reads the sheet and
        locates none still gets its refused line."""
        rows = T._numbered(T._rows("filed", "106", [("SAF-1", None)], family=T.SAF))
        pages = sorted({r["page_id"] for r in rows})

        def world(owner_reads):
            recs = list(rows)
            for t in ("filed", "post_co"):
                c = T._gc("family", pages, 0, t, family=T.SAF, tags=["SAF-1"])
                c = T._gc("family", pages, sum(S.glyph_in_census(r, c) for r in rows), t,
                          family=T.SAF, tags=["SAF-1"], qty={"SAF-1": "1"},
                          reads={"pages": pages if t == "filed" or owner_reads else [],
                                 "sheets": []})
                recs.append(c)
            # a second family both sets locate (and each set's refusals)
            return recs + T._world()

        t = X.build(world(owner_reads=False))
        self.assertEqual([ln.set_label for ln in t.lines + t.refused if ln.tag == "SAF-1"
                          and ln.scope == X.BUILDING], [FILED])
        t = X.build(world(owner_reads=True))
        self.assertEqual(_one(t.refused, tag="SAF-1", scope=X.BUILDING,
                              set_label=OWNER).reason, "no located symbols")


def _gate_sentences(recs, ln):
    """Every sentence the chat could state for `ln`'s subject, scope and set,
    figure 0..60 - the export's own sentence shape (X._sentence), so a
    refused line with no figure is checked too."""
    gb = S.glyph_books(recs)
    ob = S.opening_books(recs)
    books = ob if ln.trade == X.DOORS_WINDOWS else gb
    t = next((t for t, lab in books.labels.items() if lab == ln.set_label), None)
    book = books.tracks.get(t) if t in books.tracks else books.totals
    sets = len(books.tracks)
    subject = ""
    if ln.scope == X.FLOOR:
        k = next((k for k, title in book.titles.items() if title == ln.level), ln.level)
        subject = X._floor_subject(book, k)
    fam = book.families[ln.item]
    tag = ln.tag[len("type "):] if ln.tag.startswith("type ") else ln.tag
    phrase = X._set_phrase(ln.set_label, sets)
    return {v: X._sentence(subject, v, X._thing(fam, tag, v, book.opening), phrase)
            for v in range(0, 61)}


class TheExportAndTheChatAgree(unittest.TestCase):
    """Rulings 101/102: one rule in both. For every equipment, roof-drain and
    door/window line, in each set, at floor (placed or sheet scope) and
    building scope: a verified line's sentence is one the chat gate binds,
    with the line's figure and no other; a refused line's subject binds no
    figure at all in the chat."""

    WORLDS = {
        "WH-1, both sets, a sheet-scope roof": _wh_world,
        "PTAC, both sets, doors and windows": lambda: T._world() + D._world(
            D._first_floor("filed"), D._first_floor("post_co")),
        "PTAC, the owner's first floor short": lambda: T._world(
            owner_100=T.OWNER_100[:4], owner_mech=5),
    }

    def test_every_line(self):
        for name, world in self.WORLDS.items():
            with self.subTest(name):
                recs = world()
                with self.assertLogs("lib.plan_search", "WARNING") if "short" in name \
                        else _quiet():
                    t = X.build(recs)
                checked = 0
                for ln, verified in [(ln, True) for ln in t.lines] + [(ln, False) for ln in t.refused]:
                    if ln.trade == X.AREAS or ln.tag == "(all)":
                        continue
                    bound = {v for v, sent in _gate_sentences(recs, ln).items()
                             if S.answer_is_grounded(sent, recs, intent="count")[0]}
                    if verified:
                        self.assertEqual(bound, {int(ln.qty)}, ln)
                        self.assertTrue(S.answer_is_grounded(ln.sentence, recs, intent="count")[0])
                    else:
                        self.assertEqual(bound, set(), ln)
                    checked += 1
                self.assertGreaterEqual(checked, 6)


class _quiet:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AnUnreadableQtyIsNotChecked(unittest.TestCase):
    """73: the total stands, and the line says it was not checked, with
    what the two readings said."""

    def _world(self, readings):
        recs = T._world()
        for c in recs:
            if c.get("record_type") == S.GLYPH_CENSUS and c.get("kind") == "family":
                c["qty"] = {"PTAC-1": "3", "PTAC-2": "(readings disagree)", "PTAC-3": "3"}
                if readings:
                    c["qty_readings"] = readings
        return recs

    def test_the_line_names_the_readings(self):
        t = X.build(self._world({"PTAC-2": ["6", "9"]}))
        for label in (FILED, OWNER):
            ln = _one(t.lines, tag="PTAC-2", scope=X.BUILDING, set_label=label)
            self.assertEqual(ln.check, "not checked: schedule QTY unreadable (6 or 9)")
        self.assertEqual(_one(t.lines, tag="PTAC-1", scope=X.BUILDING,
                              set_label=FILED).check, "schedule QTY 3 agrees")

    def test_without_the_readings_it_still_says_not_checked(self):
        t = X.build(self._world(None))
        self.assertEqual(_one(t.lines, tag="PTAC-2", scope=X.BUILDING, set_label=FILED).check,
                         "not checked: schedule QTY unreadable")


class TheReadingsAreTheQuantityColumns(unittest.TestCase):
    """schedule_quantity_readings: the contested cells of the QTY column
    only (M-200.00's WH-1 row is contested in MANUFACTURER and REMARKS,
    not in QTY), carried by the census for the reader and never a figure."""

    PAYLOAD = {"name": "ROOMS PTAC UNITS SCHEDULE",
               "columns": [{"header": "SYMBOL", "role": "identifier"},
                           {"header": "QTY", "role": "quantity"},
                           {"header": "MANUFACTURER", "role": "make"}],
               "rows": [["PTAC-1", "21", "AMANA"], ["PTAC-2", "(readings disagree)",
                                                    "(readings disagree)"]],
               "contested_cells": [
                   {"row": 3, "col": 1, "mark": "PTAC-2", "readings": ["6", "9"]},
                   {"row": 3, "col": 2, "mark": "PTAC-2", "readings": ["AMANA", "AMANA."]}]}

    def test_only_the_qty_column(self):
        self.assertEqual(S.schedule_quantity_readings(self.PAYLOAD, ["PTAC-1", "PTAC-2"]),
                         {"PTAC-2": ["6", "9"]})
        self.assertEqual(S.schedule_quantity_readings(self.PAYLOAD, ["PTAC-1"]), {})
        self.assertEqual(S.schedule_quantity_readings({"rows": []}, ["PTAC-2"]), {})

    def test_the_census_carries_them_and_the_gate_reads_none(self):
        c = S.glyph_census("family", "p", ["pg"], 0, family="X", tags=["PTAC-2"],
                           qty={"PTAC-2": "(readings disagree)"},
                           qty_readings={"PTAC-2": ["6", "9"]})
        self.assertEqual(c["qty_readings"], {"PTAC-2": ["6", "9"]})
        self.assertNotIn("qty_readings", S.glyph_census("family", "p", ["pg"], 0))
        # a reading lends nothing: 6 is no figure for PTAC-2
        recs = self._readings_world()
        self.assertFalse(S.answer_is_grounded("There are 6 PTAC-2.", recs, intent="count")[0])

    def _readings_world(self):
        recs = T._world()
        for c in recs:
            if c.get("record_type") == S.GLYPH_CENSUS and c.get("kind") == "family":
                c["qty"] = {"PTAC-2": "(readings disagree)"}
                c["qty_readings"] = {"PTAC-2": ["6", "9"]}
        return recs


if __name__ == "__main__":
    unittest.main()
