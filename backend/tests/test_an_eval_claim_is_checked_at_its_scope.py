"""AN EVAL CLAIM IS CHECKED AT ITS SCOPE.

A located-symbol count binds only at the scope its clause names (#664): "each
unit on the fourth floor has 2 exhaust fans" binds, "exhaust fans: 2." does
not, whatever the number. The harness wrote every claim as "<subject>:
<value>.", so a scoped case would have failed its true answer for the
sentence's shape - and its invented-number probe would have passed for the
same reason, the vacuous-probe mistake _invented_number's note records.

Pinned here (operator rulings 2026-10-07):
  scope      a claim may say {floor, per: unit}; the true answer and the
             invented probe are both written at it;
  refused    claims the gate must refuse - the partial "There are 2 EF-1."
             it once bound, a building total over refused sheets;
  sheets     for a scoped claim, the expected sheet is where the located
             symbols are; they never lead, they follow the ranked slice;
  no_unscoped_count
             vent-fan-count-not-stated NARROWED, not deleted: no record states
             a count, and no number binds at building scope - scoped counts
             may.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_eval as ev  # noqa: E402
from tests.test_a_located_count_is_complete_or_refused import (  # noqa: E402
    EF, _census, _floor, _numbered, _pages, _refusal)

BACKEND = Path(__file__).resolve().parents[1]
SCOPE = {"floor": "A-103.00", "per": "unit"}


def _present():
    assert hasattr(ev, "SCOPE_KEYS"), "plan_eval has no claim scope in this tree"
    assert "scope" in inspect.signature(ev._sentence).parameters, \
        "_sentence does not write a claim at its scope"


def _printed():
    """What leads for 'exhaust fans' on Boyland: the schedule that names the
    tags (no QTY column) and EXHAUST FAN legend entries - none on M-103.00."""
    sched = {"project_id": "p1", "record_type": "schedule", "tier": "ocr_grid_cell",
             "source": "ocr_grid", "page_id": "pg-m200", "sheet_number": "M-200.00",
             "ordinal": 0, "label": None, "subject_terms": ["EXHAUST FAN SCHEDULE"],
             "quote": "EXHAUST FAN SCHEDULE TAG | SERVING | CFM\nEF-1 | BATH | 50\nEF-2 | KITCHEN | 100",
             "payload": {"name": "EXHAUST FAN SCHEDULE",
                         "columns": [{"header": "TAG", "role": "identifier"},
                                     {"header": "SERVING", "role": None},
                                     {"header": "CFM", "role": None}],
                         "rows": [["EF-1", "BATH", "50"], ["EF-2", "KITCHEN", "100"]]}}
    legends = [{"project_id": "p1", "record_type": "legend_entry", "tier": "tag_legend",
                "source": "text_layer", "page_id": f"pg-{s}", "sheet_number": s,
                "ordinal": 0, "label": None, "subject_terms": ["EXHAUST FAN"],
                "quote": "EXHAUST FAN", "payload": {"symbol": "EF", "meaning": "EXHAUST FAN"}}
               for s in ("A-100.01", "A-105.01", "A.1.1")]
    return [sched] + legends


def _located(refused_sheet=True):
    rows = _floor("103", EF, [(t, u) for u in ("4A", "4B", "4C", "4D")
                              for t in ("EF-1", "EF-2")])
    rows += _floor("102", EF, [(t, u) for u in ("3A", "3B", "3C", "3D")
                               for t in ("EF-1", "EF-2")])
    if refused_sheet:
        rows.append(_refusal("M-104.00", "A-104.00: no occupancy table and no unit tags"))
    rows = _numbered(rows)
    return rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})


CASE = {"id": "exhaust-fans-per-unit-fourth-floor", "kind": "answer",
        "subject": "exhaust fans", "intent": "count",
        "question": "how many exhaust fans does each apartment on the fourth floor have",
        "expect": {"sheets": ["M-103.00"], "values": [2],
                   "claims": [{"subject": "exhaust fans", "value": 2, "scope": SCOPE}],
                   "refused": [{"subject": "EF-1", "value": 2},
                               {"subject": "exhaust fans", "value": 32}]},
        "truth": {"how": "by_eye", "evidence": "read it"}}

VENT = {"id": "vent-fan-count-not-stated", "kind": "absent", "subject": "exhaust fan",
        "intent": "count", "question": "how many vent fans are there",
        "expect": {"no_unscoped_count": True, "text": ["EF-1"]},
        "truth": {"how": "absent", "evidence": "no QTY column"}}


def _score(case, returned):
    return ev.score_case(case, returned, {})


class AScopedClaimIsWrittenAtItsScope(unittest.TestCase):

    def test_per_unit_on_a_floor(self):
        _present()
        self.assertEqual(ev._sentence("exhaust fans", 2, SCOPE),
                         "Each unit on A-103.00 has 2 exhaust fans.")

    def test_a_floor_total(self):
        _present()
        self.assertEqual(ev._sentence("EF-1", 4, {"floor": "A-103.00"}),
                         "EF-1 on A-103.00: 4.")

    def test_an_unscoped_claim_is_written_as_before(self):
        _present()
        self.assertEqual(ev._sentence("PTAC-1", 21), "PTAC-1: 21.")


class TheCaseIsScoredOnTheLocatedSymbols(unittest.TestCase):

    def test_it_passes_when_the_symbols_come_back(self):
        _present()
        r = _score(CASE, _printed() + _located())
        self.assertEqual(r["outcome"], "pass", r["reasons"])
        self.assertTrue(r["checks"]["gate_allows_the_true_answer"])
        self.assertTrue(r["checks"]["gate_refuses_an_invented_number"])
        self.assertTrue(r["checks"]["expected_sheet_in_lead"])
        self.assertTrue(r["checks"]["refuses:EF-1: 2."])
        self.assertTrue(r["checks"]["refuses:exhaust fans: 32."])

    def test_the_invented_probe_is_written_at_the_scope_too(self):
        """Written unscoped, every number is refused for the sentence's shape
        and the probe proves nothing; at the scope, the first refused number
        is one the gate refused on its merits."""
        _present()
        returned = _printed() + _located()
        n = ev._invented_number(returned, "exhaust fans", "count", SCOPE)
        self.assertNotEqual(n, "2")
        from lib import plan_search as ps
        self.assertTrue(ps.answer_is_grounded(ev._sentence("exhaust fans", 2, SCOPE),
                                              returned, intent="count")[0])

    def test_without_the_symbols_it_fails(self):
        _present()
        r = _score(CASE, _printed())
        self.assertEqual(r["outcome"], "fail")
        self.assertFalse(r["checks"]["gate_allows_the_true_answer"])
        self.assertFalse(r["checks"]["expected_sheet_in_lead"])

    def test_a_refused_claim_that_binds_fails_the_case(self):
        """A QTY column printing 2 for EF-1 would make 'EF-1: 2.' true - and
        the case, which says it is wrong, must then fail loudly."""
        _present()
        qty = dict(_printed()[0], ordinal=1, payload={
            "name": "EXHAUST FAN SCHEDULE",
            "columns": [{"header": "TAG", "role": "identifier"},
                        {"header": "QTY", "role": "quantity"}],
            "rows": [["EF-1", "2"]]})
        r = _score(CASE, [qty] + _printed() + _located())
        self.assertEqual(r["outcome"], "fail")
        self.assertFalse(r["checks"]["refuses:EF-1: 2."])
        self.assertTrue(any("the gate allowed 'EF-1: 2.'" in x for x in r["reasons"]))

    def test_glyph_rows_stand_for_the_sheet_only_for_a_scoped_claim(self):
        _present()
        unscoped = dict(CASE, expect=dict(CASE["expect"],
                                          claims=[{"subject": "exhaust fans", "value": 2}]))
        r = _score(unscoped, _printed() + _located())
        self.assertFalse(r["checks"]["expected_sheet_in_lead"])


class NoUnscopedCountIsTheNarrowedAbsence(unittest.TestCase):

    def test_scoped_counts_are_allowed(self):
        _present()
        r = _score(VENT, _printed() + _located())
        self.assertEqual(r["outcome"], "pass", r["reasons"])
        self.assertTrue(r["checks"]["no_unscoped_count_binds"])
        self.assertTrue(r["checks"]["no_record_states_a_count"])

    def test_a_building_count_that_binds_fails(self):
        """With nothing refused the building total is complete, and binds -
        which is exactly what this absence says must not happen here."""
        _present()
        r = _score(VENT, _printed() + _located(refused_sheet=False))
        self.assertEqual(r["outcome"], "fail")
        self.assertFalse(r["checks"]["no_unscoped_count_binds"])
        self.assertTrue(any("an unscoped count" in x for x in r["reasons"]))

    def test_a_record_stating_a_count_fails(self):
        _present()
        stated = {"project_id": "p1", "record_type": "element", "tier": "vision_read",
                  "source": "vision", "page_id": "pg-m200", "sheet_number": "M-200.00",
                  "ordinal": 9, "label": None, "subject_terms": ["EF-1"],
                  "quote": "EF-1 - count 3 - EXHAUST FAN SCHEDULE",
                  "payload": {"tag": "EF-1", "count_if_stated": 3,
                              "count_basis": "vision_read"}}
        r = _score(VENT, [stated] + _printed() + _located())
        self.assertEqual(r["outcome"], "fail")
        self.assertFalse(r["checks"]["no_record_states_a_count"])


class TheSuiteRefusesAScopeItCannotCheck(unittest.TestCase):

    def _suite(self, **expect):
        case = dict(CASE, expect=dict(CASE["expect"], **expect))
        return {"schema": 1, "project": {"id": "p", "baseline": {"pages": 1}},
                "cases": [case]}

    def test_the_case_as_written_is_valid(self):
        _present()
        ev.validate_suite(self._suite())

    def test_a_bad_scope_is_refused(self):
        _present()
        for scope in ({"floor": "A-103.00", "per": "floor"}, {"per": "unit"},
                      {"floor": "A-103.00", "unit": "4A"}, "A-103.00"):
            with self.assertRaises(ev.SuiteError, msg=repr(scope)):
                ev.validate_suite(self._suite(
                    claims=[{"subject": "exhaust fans", "value": 2, "scope": scope}]))

    def test_a_refused_claim_names_its_value(self):
        _present()
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(self._suite(refused=[{"subject": "EF-1"}]))

    def test_no_unscoped_count_is_an_absence(self):
        _present()
        bad = dict(VENT, truth={"how": "by_eye", "evidence": "x"})
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite({"schema": 1, "project": {"id": "p", "baseline": {"pages": 1}},
                               "cases": [bad]})


class TheShippedSuite(unittest.TestCase):

    def setUp(self):
        self.s = ev.load_suite(str(BACKEND / "eval" / "boyland.json"))
        self.by_id = {c["id"]: c for c in self.s["cases"]}

    def test_the_fourth_floor_case_claims_2_per_unit_and_refuses_the_rest(self):
        c = self.by_id.get("exhaust-fans-per-unit-fourth-floor")
        self.assertIsNotNone(c, "the case is not in the suite")
        self.assertEqual(c["expect"]["claims"],
                         [{"subject": "exhaust fans", "value": 2, "scope": SCOPE}])
        self.assertEqual(c["expect"]["sheets"], ["M-103.00"])
        self.assertEqual(c["expect"]["refused"],
                         [{"subject": "EF-1", "value": 2},
                          {"subject": "exhaust fans", "value": 32}])

    def test_vent_fan_is_narrowed_not_deleted(self):
        c = self.by_id.get("vent-fan-count-not-stated")
        self.assertIsNotNone(c, "vent-fan-count-not-stated was deleted")
        self.assertTrue(c["expect"].get("no_unscoped_count"))
        self.assertNotIn("no_stated_count", c["expect"])


if __name__ == "__main__":
    unittest.main()
