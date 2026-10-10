"""THE SCHEDULE'S QTY AND THE LOCATED COUNT AGREE, OR NEITHER IS SAID.

Re-probe of the rebuilt Boyland rows, 2026-10-10: "There is 1 DH-1." BOUND
while the model was told "state no count of these". The 1 is the printed QTY
in M-200.00's DUCT ELECTRIC HEATER row - a counting source since #666 - and
the pass locates no DH-1 (its label reads "DH-1. DUCT HEATER"). The #679
tests never saw it: their fixture carried the census's QTY but no schedule
record, so the path that bound it was never in the room.

Rulings (operator, 2026-10-10):
  (a) nothing located, QTY printed: the QTY stands, and the model is told so
      - "the schedule prints QTY N; its symbols were not located".
  (b) both exist and disagree: the QTY is withheld too. "Neither" holds in
      the gate as well as the render.
Condition: EVERY fixture here carries BOTH a schedule record with its QTY
column AND glyph rows with their census - the shape production returns.

Gate-only: no row the pass writes changes, so no rebuild.
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
from tests.test_a_located_count_is_complete_or_refused import PID  # noqa: E402
from tests.test_a_sheet_it_cannot_place_still_counts import (  # noqa: E402
    DH, PTAC, QTY, SAF, WH, _boyland)


def _present():
    assert hasattr(S, "_qty_in_clause"), "the QTY ruling is not in this tree"


def _schedule(name, columns, rows, ordinal):
    """A printed schedule record as production stores it (M-200.00, OCR grid)."""
    return {"project_id": PID, "record_type": "schedule", "tier": "ocr_grid_cell",
            "source": "ocr_grid", "page_id": "pg-M-200.00", "sheet_number": "M-200.00",
            "ordinal": ordinal, "label": None, "subject_terms": [name],
            "quote": name + " " + " | ".join(h for h, _r in columns),
            "payload": {"name": name,
                        "columns": [{"header": h, "role": r} for h, r in columns],
                        "rows": rows}}


def _schedules(ptac1_qty="21"):
    """The four schedules with a QTY column, as M-200.00 prints them."""
    return [
        _schedule(PTAC, [("UNIT NO.", "identifier"), ("QTY", "quantity"), ("MAKE", "make")],
                  [["PTAC-1", ptac1_qty, "AMANA"], ["PTAC-2", "(readings disagree)", "AMANA"],
                   ["PTAC-3", "11", "AMANA"]], 900),
        _schedule(WH, [("MARK", "identifier"), ("QTY", "quantity"), ("WATTS", None)],
                  [["WH-1", "9", "5120"]], 901),
        _schedule(SAF, [("MARK", "identifier"), ("QTY", "quantity"), ("CFM", None)],
                  [["SAF-1", "1", "900"]], 902),
        _schedule(DH, [("MARK", "identifier"), ("BASIS OF DESIGN", None), ("QTY", "quantity"),
                       ("CAPACITY (KW)", None), ("VOLTAGE", None), ("AMPS", None)],
                  [["DH-1", "8PD15-1812-3", "1", "15.0", "208/3/60", "41.7"]], 903),
    ]


def _world(ptac1_extra=0, with_schedules=True, ptac1_qty="21"):
    """Production's shape: the printed schedules AND the rebuilt glyph rows
    (PTAC-1 17 placed + 4 on the mezzanine = 21 located, unless shifted) AND
    the census, whose QTY is read from the same schedule cells."""
    qty = dict(QTY, **{PTAC: dict(QTY[PTAC], **{"PTAC-1": ptac1_qty})})
    recs = _boyland(qty=qty, ptac1_extra=ptac1_extra)
    return (_schedules(ptac1_qty) if with_schedules else []) + recs


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


class NothingLocatedTheScheduleStands(unittest.TestCase):
    """Ruling (a)."""

    def test_one_dh_1_binds_and_the_model_is_told_the_same(self):
        _present()
        recs = _world()
        self.assertTrue(_ok("There is 1 DH-1.", recs))
        for s in ("There are 0 DH-1.", "There are 2 DH-1."):
            self.assertFalse(_ok(s, recs), s)
        text = S.render_glyph_evidence(recs)
        self.assertIn(f"{DH} (DH-1): the schedule prints QTY DH-1 1; its symbols were "
                      f"not located.", text)
        self.assertNotIn("State no count of these", text.split(DH, 1)[1].split("\n", 1)[0])

    def test_the_census_carries_it_when_the_schedule_record_did_not_come_back(self):
        """The render reads the census; so does the gate - one source, so they
        cannot disagree about whether the figure may be said."""
        _present()
        recs = _world(with_schedules=False)
        self.assertTrue(_ok("There is 1 DH-1.", recs))

    def test_a_qty_is_a_building_figure(self):
        _present()
        self.assertFalse(_ok("The bulkhead has 1 DH-1.", _world(with_schedules=False)))


class BothExistAndDisagreeNeitherIsSaid(unittest.TestCase):
    """Ruling (b): 20 PTAC-1 located, the schedule prints 21."""

    def test_neither_number_binds_with_the_schedule_record_present(self):
        _present()
        recs = _world(ptac1_extra=-1)
        self.assertFalse(_ok("There are 21 PTAC-1.", recs))
        self.assertFalse(_ok("There are 20 PTAC-1.", recs))
        self.assertIn("PTAC-1: located 20 but the schedule's QTY prints 21 - THEY DISAGREE",
                      S.render_glyph_evidence(recs))

    def test_a_scoped_located_figure_is_untouched(self):
        _present()
        recs = _world(ptac1_extra=-1)
        self.assertTrue(_ok("There are 4 PTAC-1 on the mezzanine.", recs))

    def test_a_disagreement_where_the_located_count_is_incomplete_withholds_nothing(self):
        """Disagreement needs a COMPLETE located count; with a mechanical sheet
        refused the 20 is not a building figure, and the schedule's 21 stands."""
        _present()
        from lib import plan_emit as E
        page = {"project_id": PID, "page_id": "pg-M-105.00", "page_number": 7,
                "sheet_number": "M-105.00", "sheet_title": "ROOF HVAC PLANS"}
        refusal = E.sheet_refusal(page, "takeoff failed", pass_key="k", role="mechanical")
        qty = dict(QTY, **{PTAC: dict(QTY[PTAC])})
        recs = _schedules() + _boyland(qty=qty, ptac1_extra=-1, refusals=[refusal])
        self.assertTrue(_ok("There are 21 PTAC-1.", recs))
        self.assertFalse(_ok("There are 20 PTAC-1.", recs))


class TheAgreeingFamiliesStillBind(unittest.TestCase):

    def test_ptac_1_ptac_3_wh_1_saf_1(self):
        _present()
        recs = _world()
        for s in ("There are 21 PTAC-1.", "There are 11 PTAC-3.", "There are 9 WH-1.",
                  "There is 1 SAF-1."):
            self.assertTrue(_ok(s, recs), s)
        text = S.render_glyph_evidence(recs)
        for want in ("PTAC-1 21 (agrees with the schedule's QTY 21)",
                     "PTAC-3 11 (agrees with the schedule's QTY 11)",
                     "WH-1 9 (agrees with the schedule's QTY 9)",
                     "SAF-1 1 (agrees with the schedule's QTY 1)"):
            self.assertIn(want, text)


class AnUnreadableCellStillBindsUnchecked(unittest.TestCase):

    def test_ptac_2(self):
        _present()
        recs = _world()
        self.assertTrue(_ok("There are 9 PTAC-2.", recs))
        self.assertIn("PTAC-2 9 (the schedule's QTY cell cannot be read: "
                      "'(readings disagree)' - not checked)", S.render_glyph_evidence(recs))


if __name__ == "__main__":
    unittest.main()
