"""scripts/negative_claims_bindings.py: Roy's merge bar for the negative-claims
gate, run on the repo's stored claim sets. The gate changes no number in any
stored plan answer, and on the 10-27 spray-foam case it removes the false
absence claim; a right answer goes through it unchanged."""

from __future__ import annotations

import unittest

from scripts import negative_claims_bindings as nb


class Bindings(unittest.TestCase):
    def test_no_number_changes_in_any_claim_set(self):
        per = nb.bindings()
        for name in ("equipment", "doors/windows", "RD", "areas"):
            self.assertTrue(per[name]["answers"] > 0, name)
        for name, s in per.items():
            self.assertEqual((s["numeric_changes"], s["non_absence_changes"]), (0, 0), name)
            self.assertEqual(s["numbers_before"], s["numbers_after"], name)
            self.assertEqual(s["values_before"], s["values_after"], name)

    def test_spray_foam(self):
        out = nb.spray_foam()
        live, right = out["10-27 answer as sent"], out["a right answer"]
        self.assertEqual(live["forbidden_hit"], [])
        self.assertRegex(live["gated"], r"^Not found in the sheets I searched: A-302\.00, A-104\.00\.")
        self.assertEqual((right["outcome"], right["missing"], right["forbidden_hit"]),
                         ("failing-pending", [], []))
        self.assertEqual(right["gated"], nb.RIGHT_1027)


if __name__ == "__main__":
    unittest.main()
