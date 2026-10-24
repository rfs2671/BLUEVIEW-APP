"""THE DUPLEX EVAL CASE IS THE WHOLE APARTMENT.

#667's case claimed "each apartment on the fourth floor has 2 exhaust fans" -
A-103.00's half of each duplex. #671 made that refuse by design (a unit is the
whole apartment), and #747 made the whole apartment answerable: A-103.00's
stair carries 4A-4D to the mezzanine, where M-104.00 adds one EF-1 each.
Rewritten 2026-10-23 (roadmap F2):

  exhaust-fans-per-unit-fourth-floor   each apartment there has 3; 2 refused
  exhaust-fans-in-duplex-4a            4A has 3 - a claim at UNIT scope, which
                                       the harness could not write before; the
                                       halves (2 and 1) refused

Both are scored here on rows shaped as production writes them after #747's
rebuild, and on rows without the stair link (production before it): the cases
pass on the first and fail on the second, so they measure the duplex fix
itself, not the sentence's shape.
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

from lib import plan_eval as ev  # noqa: E402
from tests.test_an_eval_claim_is_checked_at_its_scope import _printed  # noqa: E402
from tests.test_a_stair_carries_its_unit_to_the_level_it_reaches import _seeded  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
UNIT = {"unit": "4A"}


def _present():
    assert "unit" in ev.SCOPE_KEYS, "the eval harness cannot write a claim about one apartment"


def _case(cid):
    return {c["id"]: c for c in ev.load_suite(str(BACKEND / "eval" / "boyland.json"))["cases"]}[cid]


class AClaimAboutOneApartment(unittest.TestCase):

    def test_is_written_as_the_apartment_has_n(self):
        _present()
        self.assertEqual(ev._sentence("exhaust fans", 3, UNIT), "4A has 3 exhaust fans.")

    def test_its_scope_is_the_unit_alone(self):
        _present()
        base = _case("exhaust-fans-in-duplex-4a")

        def suite(scope):
            c = dict(base, expect=dict(base["expect"], claims=[
                {"subject": "exhaust fans", "value": 3, "scope": scope}]))
            return {"schema": 1, "project": {"id": "p", "baseline": {"pages": 1}}, "cases": [c]}

        ev.validate_suite(suite(UNIT))
        for bad in ({"unit": ""}, {"unit": "4A", "per": "unit"},
                    {"unit": "4A", "floor": "A-103.00"}):
            with self.assertRaises(ev.SuiteError, msg=repr(bad)):
                ev.validate_suite(suite(bad))


class TheShippedCasesMeasureTheDuplexFix(unittest.TestCase):

    def _score(self, cid, linked):
        return ev.score_case(_case(cid), _printed() + _seeded(linked=linked), {})

    def test_4a_has_3_passes_on_linked_rows(self):
        _present()
        r = self._score("exhaust-fans-in-duplex-4a", True)
        self.assertEqual(r["outcome"], "pass", r["reasons"])
        self.assertTrue(r["checks"]["gate_allows_the_true_answer"])
        self.assertTrue(r["checks"]["refuses:4A has 2 exhaust fans."])
        self.assertTrue(r["checks"]["refuses:4A has 1 exhaust fans."])

    def test_4a_has_3_fails_without_the_stair_link(self):
        _present()
        r = self._score("exhaust-fans-in-duplex-4a", False)
        self.assertEqual(r["outcome"], "fail")
        self.assertFalse(r["checks"]["gate_allows_the_true_answer"])

    def test_each_apartment_on_the_fourth_floor_has_3(self):
        _present()
        r = self._score("exhaust-fans-per-unit-fourth-floor", True)
        self.assertEqual(r["outcome"], "pass", r["reasons"])
        self.assertTrue(r["checks"]["refuses:Each unit on A-103.00 has 2 exhaust fans."])
        self.assertTrue(r["checks"]["refuses:EF-1: 2."])
        self.assertTrue(r["checks"]["refuses:exhaust fans: 32."])
        self.assertEqual(self._score("exhaust-fans-per-unit-fourth-floor", False)["outcome"],
                         "fail")


if __name__ == "__main__":
    unittest.main()
