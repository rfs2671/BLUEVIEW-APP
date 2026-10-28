"""The ceiling-height case, rewritten to the operator's ruling (2026-10-27):

    truth = "floor-to-floor 10'-0" (A-300.00); ceiling height not shown on
    the drawings". The case expects that, and fails if any ceiling height
    value is stated.

"Stated" is what the gate lets through: an answer may say a value only when
answer_is_grounded binds it. So the case puts EVERY dimension its returned
records print to the gate as a ceiling height (`no_stated_value`), and fails
on any that binds. Measured 2026-10-27: the gate binds "The ceiling height is
10'-0"." on A-300.00's floor-to-floor 10'-0" - a printed dimension is bound
to whatever subject the sentence names - so this case fails until the gate
ties a value to its subject. That is the case working, not a broken case.

Each test fails by assertion on the branch before this change.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_eval as ev  # noqa: E402
from tests.test_plan_eval_scores_what_it_claims import rec  # noqa: E402

SUITE = Path(__file__).resolve().parents[1] / "eval" / "boyland.json"


def _case():
    return next(c for c in json.loads(SUITE.read_text(encoding="utf-8"))["cases"]
                if c["id"] == "ceiling-height")


def _a300():
    return [rec(sheet_number="A-300.00", quote="SECOND FLOOR 43.37' +10'-0\""),
            rec(sheet_number="A-300.00", record_type="dimension", quote="10'-0\"")]


class TheCaseIsTheRuling(unittest.TestCase):

    def test_floor_to_floor_on_a300_and_no_ceiling_height(self):
        c = _case()
        exp = c["expect"]
        self.assertEqual(exp.get("sheets"), ["A-300.00"])
        self.assertIn("10'-0\"", exp.get("text") or [])
        self.assertIs(exp.get("no_stated_value"), True)
        self.assertIn("floor-to-floor 10'-0\" (A-300.00)", c["truth"]["evidence"])
        self.assertIn("not shown on the drawings", c["truth"]["evidence"])
        suite = json.loads(SUITE.read_text(encoding="utf-8"))
        ev.validate_suite(suite)
        # Only an attribute case can say no value of it is stated.
        bad = dict(c, intent="count", expect=dict(exp))
        bad.pop("attribute", None)
        suite["cases"] = [bad if x["id"] == c["id"] else x for x in suite["cases"]]
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(suite)


class AStatedValueFailsTheCase(unittest.TestCase):

    def test_a_printed_ceiling_height_that_binds_fails_it(self):
        returned = _a300() + [rec(sheet_number="A-500.00", quote="TYP. CEILING HEIGHT 9'-0\" A.F.F.")]
        out = ev.score_case(_case(), returned, {})
        self.assertEqual(out["outcome"], "fail")
        self.assertTrue(any("9'-0\"" in r and "ceiling height" in r for r in out["reasons"]), out["reasons"])

    def test_the_floor_to_floor_dimension_is_put_to_the_gate_as_a_ceiling_height(self):
        """Today's gate binds it: the case reports that, by name."""
        out = ev.score_case(_case(), _a300(), {})
        self.assertGreaterEqual(out["checks"].get("printed_values_put_to_the_gate", 0), 1)
        self.assertEqual(out["checks"].get("no_value_binds"), False)
        self.assertTrue(any("10'-0\"" in r and "ceiling height" in r for r in out["reasons"]), out["reasons"])

    def test_nothing_printed_is_nothing_stated(self):
        """Records that print no dimension leave the check vacuous, and say so
        (0 values put to the gate) rather than calling it a pass on evidence."""
        out = ev.score_case(_case(), [rec(sheet_number="A-302.00", quote="6 CEILING DETAIL")], {})
        self.assertEqual(out["checks"].get("printed_values_put_to_the_gate"), 0)
        self.assertEqual(out["checks"].get("no_value_binds"), True)


if __name__ == "__main__":
    unittest.main()
